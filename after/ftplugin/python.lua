-- Python script dev loop:
--   <leader>r  run current file ONCE. Output renders in a terminal split
--              (colors, streaming) AND is captured unwrapped for parsing.
--              On non-zero exit, the traceback goes to quickfix (]q / [q).
--
-- How it stays single-execution + gets unwrapped output:
--   * jobstart with pty=true so the program keeps tty behavior (colors),
--     but width is forced huge so Python never wraps the traceback.
--   * We DON'T parse the rendered terminal (a pty always wraps at its width).
--     Instead we tee each raw chunk to two consumers of the same byte stream:
--       1. nvim_open_term channel  -> real terminal rendering for reading
--       2. a Lua buffer            -> unwrapped text for quickfix parsing
-- No buffer-global makeprg is set.

-- PEP 8: 4-space indentation, spaces only. Buffer-local so it doesn't affect
-- other filetypes (which use the global shiftwidth=2).
vim.bo.expandtab = true
vim.bo.shiftwidth = 4
vim.bo.softtabstop = 4
vim.bo.tabstop = 4

-- The runtime Python indenter (python#GetIndent) decides whether a "(" is a
-- real open paren by asking the LEGACY syntax highlighter (synID()) if the
-- char is inside a string/comment. We highlight with treesitter only, so
-- legacy syntax isn't loaded (b:current_syntax is empty) and synID() returns 0.
-- Result: a bracket inside a string literal, e.g. type.split("(", 1), is
-- miscounted as an unclosed paren and every following line aligns to it
-- (cursor jumps far right on <CR>). Disabling paren-alignment indentation
-- sidesteps the broken synID lookup; continuation lines just use shiftwidth.
vim.g.python_indent = vim.tbl_extend("force", vim.g.python_indent or {}, {
  disable_parentheses_indenting = 1,
})

-- Resolve the interpreter: active shell venv -> venv next to the script -> python3
local function python_bin()
  local venv = vim.env.VIRTUAL_ENV
  if venv and vim.uv.fs_stat(venv .. "/bin/python") then
    return venv .. "/bin/python"
  end

  local dir = vim.fn.expand("%:p:h")
  for _, name in ipairs({ ".venv", "venv" }) do
    local p = dir .. "/" .. name .. "/bin/python"
    if vim.uv.fs_stat(p) then
      return p
    end
  end

  return "python3"
end

-- Extract quickfix items from raw (unwrapped) Python traceback text.
-- Python frames look like:  File "path", line N, in func
-- We do this by hand rather than errorformat because tracebacks are multiline
-- and modern (3.11+) ones interleave caret/underline annotation lines.
local function parse_traceback(text)
  local items = {}
  local last_msg = nil

  for line in (text .. "\n"):gmatch("(.-)\n") do
    local f, l = line:match('^%s*File "([^"]+)", line (%d+)')
    if f then
      items[#items + 1] = { filename = f, lnum = tonumber(l), text = "" }
    else
      -- The final "ExceptionType: message" line has no leading whitespace.
      local exc = line:match("^(%a[%w_.]*Error:.*)")
        or line:match("^(%a[%w_.]*Exception:.*)")
        or line:match("^(%a[%w_.]*: .+)$")
      if exc then
        last_msg = exc
      end
    end
  end

  -- Attach the exception message to the innermost (last) frame so the qf
  -- entry you land on shows what actually went wrong.
  if last_msg and #items > 0 then
    items[#items].text = last_msg
  end
  return items
end

-- Track the previous run so repeated runs reuse one split instead of stacking.
-- Module-level (not buffer-local) so it's shared across all Python buffers.
local run = { win = nil, job = nil }

vim.keymap.set("n", "<leader>r", function()
  if vim.bo.modified then
    vim.cmd("write")
  end

  local py = python_bin()
  local file = vim.fn.expand("%:p")
  local name = vim.fn.fnamemodify(file, ":t")

  local ok_fidget, progress = pcall(require, "fidget.progress")
  local handle = ok_fidget
    and progress.handle.create({
      title = "Run",
      message = name,
      lsp_client = { name = "python" },
      percentage = nil,
    })
    or nil

  local raw = {} -- unwrapped byte chunks, for parsing
  local main = vim.api.nvim_get_current_win()

  -- Kill a still-running previous job before reusing/replacing its window.
  if run.job then
    pcall(vim.fn.jobstop, run.job)
    run.job = nil
  end

  -- Reuse the previous window if valid; otherwise open a bottom split.
  local term_win
  if run.win and vim.api.nvim_win_is_valid(run.win) then
    term_win = run.win
    vim.api.nvim_set_current_win(term_win)
  else
    vim.cmd("botright 15split")
    term_win = vim.api.nvim_get_current_win()
  end

  -- A fresh terminal buffer we feed ourselves (no process attached to it).
  local term_buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_win_set_buf(term_win, term_buf)
  local chan = vim.api.nvim_open_term(term_buf, {})
  run.win = term_win

  local function on_output(_, data)
    if not data then
      return
    end
    -- jobstart's channel protocol: items are split on "\n", and the last item
    -- of one callback joins the first item of the next (a partial line). So a
    -- newline is exactly the boundary *between* items within a callback.
    -- Rebuild the byte stream with "\n" between items (no separator across
    -- callbacks), strip any pty-inserted "\r", then translate "\n" -> "\r\n"
    -- so nvim_open_term returns the cursor to column 0 on every line. Doing it
    -- on the reconstructed string (not per-item with i>1) is correct no matter
    -- how libuv chunks the output -- the old i>1 approach dropped carriage
    -- returns whenever a line arrived as its own callback (large output).
    local s = table.concat(data, "\n"):gsub("\r", "")
    raw[#raw + 1] = s
    vim.api.nvim_chan_send(chan, (s:gsub("\n", "\r\n")))
  end

  run.job = vim.fn.jobstart({ py, file }, {
    pty = true,
    width = 10000, -- effectively disable pty line wrapping
    on_stdout = on_output,
    on_stderr = on_output,
    on_exit = function(job_id, code)
      if handle then
        handle.message = code == 0 and "done" or ("exited " .. code)
        handle:finish()
      end

      if run.job == job_id then
        run.job = nil
      end

      vim.api.nvim_chan_send(chan, "\r\n[exit " .. code .. "]\r\n")

      -- Leave output visible. On failure, parse traceback into quickfix.
      if code ~= 0 then
        local items = parse_traceback(table.concat(raw, "\n"))
        vim.fn.setqflist({}, "r", { title = "python " .. name, items = items })
        if #items > 0 then
          vim.cmd("cwindow")
        end
      end
    end,
  })

  -- Return focus to your code immediately; output streams in the split.
  if vim.api.nvim_win_is_valid(main) then
    vim.api.nvim_set_current_win(main)
  end
end, { buffer = true, desc = "Run Python script (terminal + qf on error)" })
