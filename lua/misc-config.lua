vim.cmd.colorscheme("gruvbox")

--- HMM are there actual settings i want to use for vscode then ?
vim.keymap.set("n", "<C-u>", "<C-u>zz")
vim.keymap.set("n", "<C-d>", "<C-d>zz")
vim.keymap.set("n", "<C-]>", "<C-]>zz")
vim.keymap.set("n", "<C-[>", "<C-[>zz")
vim.keymap.set("n", "<C-o>", "<C-o>zz")
vim.keymap.set("n", "<C-i>", "<C-i>zz")
vim.keymap.set("n", "n", "nzz")
vim.keymap.set("n", "N", "Nzz")
vim.keymap.set("n", "<leader>ct", ":bd term<C-A><CR>")
vim.keymap.set("n", "<M-o>", ":ClangdSwitchSourceHeader<CR>")
vim.keymap.set("v", "q", ":norm @q<CR>")
vim.keymap.set("n", "<leader>m", ":marks<CR>")
vim.keymap.set({ 'n', 'v' }, "<leader>y", "\"+y")
vim.keymap.set({ 'n', 'v' }, "<leader>p", "\"+p")
vim.keymap.set("", "<leader>w", ":w<CR>")
vim.keymap.set("", "<leader>x", ":x<CR>")
vim.keymap.set("", "<leader>n", ":noh<CR>")

--
-- this only should work with lua files
-- vim.keymap.set("n", "<leader>s", ":w<CR>:so %<CR>")
vim.api.nvim_create_autocmd("FileType", {
  pattern = "lua",
  callback = function(ev)
    -- buffer-local so it only affects Lua files
    vim.keymap.set("n", "s", "<Cmd>luafile %<CR>", { buffer = ev.buf, desc = "Source current Lua file" })
  end,
})

-- NetRW config
-- Disabling in favor of nvim-tree
-- vim.keymap.set("n", "<leader>e", ":Explore<CR>")
-- vim.keymap.set("n", "<leader>E", ":Sex!<CR>")

vim.filetype.add({
  extension = {
    valk = "racket"
  }
})

-- Navigating quickfix list n stuff
vim.keymap.set("", "]q", ":cn<CR>")
vim.keymap.set("", "[q", ":cp<CR>")

-- Check the current files changes against whats on the file system, before storing
vim.api.nvim_create_user_command("Fdiff", "w !diff % -", {})

-- Copy relative file path
vim.api.nvim_create_user_command("CopyRelPath", "call setreg('+', expand('%'))", {})
vim.keymap.set("n", "<leader>yp", ":CopyRelPath<CR>", { desc = "Copy relative path to current buffer" })
vim.keymap.set("n", "<leader>v", "`[v`]", { desc = "Select last paste" })

vim.o.colorcolumn = "80,120"
vim.o.cursorline = true
vim.o.number = true

-- indentation settings, weird stuff huh
vim.o.smartindent = true
vim.o.autoindent = true
vim.o.expandtab = true
vim.o.tabstop = 2
vim.o.shiftwidth = 2
vim.o.timeoutlen = 650

vim.keymap.set("n", "<leader>o", "o<Esc>")
vim.keymap.set("n", "<leader>O", "O<Esc>")

-- tree style listings by default
vim.g.netrw_liststyle = 0
vim.o.splitright = true
vim.o.ignorecase = true
vim.o.smartcase = true
-- vim.o.signcolumn = 'number'

vim.o.wrap = false

-- So i dont kill my wrist
vim.keymap.set("i", "jj", "<ESC>")

-- This makes shit transparent so i can see the waifu's in the background
-- :hi normal guibg=NONE
vim.cmd.highlight({ "normal", "guibg=NONE" })
vim.cmd.highlight({ "SignColumn", "guibg=NONE" })  -- or you can also set it to darkgrey, for now tho.... its pretty good like this.
vim.cmd.highlight({ "FloatBorder", "guibg=NONE" }) -- this is a hack for some themes, for telescope and so on

-- Relative line number settings
vim.o.relativenumber = true
vim.api.nvim_create_autocmd({ 'InsertEnter' }, {
  pattern = { "*.*" },
  command = "set nornu | set number",
})
vim.api.nvim_create_autocmd({ 'InsertLeavePre' }, {
  pattern = { "*.*" },
  command = "set number | set rnu",
})

-- Terminal UX tweaks
vim.api.nvim_command("autocmd TermOpen * setlocal nonumber")
vim.api.nvim_command("autocmd TermOpen * setlocal norelativenumber")
vim.api.nvim_command("autocmd TermEnter * setlocal signcolumn=no")


-- Function to get the current git branch name
local function get_git_branch()
  return vim.fn.systemlist('git rev-parse --abbrev-ref HEAD')[1]
end

-- Function to insert TODO with the current git branch name
local function insert_todo()
  -- Construct TODO text with the git branch name
  -- Insert TODO text below the cursor position
  vim.api.nvim_put({ 'TODO(' .. get_git_branch() .. '): ' }, '', true, true)
end

vim.keymap.set({ 'i', 'n' }, '<M-t>', function() insert_todo() end, { noremap = true, silent = true })

vim.o.grepprg = 'rg --vimgrep --hidden --glob "!.git"'

vim.filetype.add({
  extension = {
    thrift = "thrift",
    sbt = "scala",
    tf = "hcl",
  }
})

-- Highlighting lines in the editor, this is useful for marking up big files, or code reviews
--

local hl_groups = {
  LineHighlightPurple = "darkmagenta",
  LineHighlightCyan = "darkcyan",
  LineHighlightGreen = "green",
}

for g, c in pairs(hl_groups) do
  vim.api.nvim_set_hl(0, g, {
    ctermbg = c,
    background = c,
  })
end


local function highlight_lines(group)
  if vim.fn.mode() == 'v' or vim.fn.mode() == 'V' then
    vim.cmd(vim.api.nvim_replace_termcodes("normal! <esc>", true, false, true)) -- hack to quit visual mode. probably better way of doing this
    -- Wish this worked but it always higlights the last selection when it changes
    -- its hilarious, but not what i need
    -- vim.fn.matchadd(group, "\\%>'<\\_.*\\%'>")
    vim.fn.matchadd(group, "\\%>" .. (vim.fn.line("'<") - 1) .. "l\\%<" .. (vim.fn.line("'>") + 1) .. "l")
  else
    vim.fn.matchadd(group, '\\%' .. vim.fn.line("v") .. 'l')
  end
end


vim.keymap.set({ 'v', 'n' }, '<leader>h', function() highlight_lines("LineHighlightPurple") end,
  { noremap = true, silent = false })
vim.keymap.set({ 'v', 'n' }, '<leader>hg', function() highlight_lines("LineHighlightGreen") end,
  { noremap = true, silent = false })
vim.keymap.set({ 'v', 'n' }, '<leader>hc', function() highlight_lines("LineHighlightCyan") end,
  { noremap = true, silent = false })
vim.keymap.set({ 'n' }, '<leader>c', function() vim.fn.clearmatches() end, { noremap = true, silent = true })

local function surround_last_edit(txt)
  local start_pos = vim.fn.getpos("'[")
  local end_pos = vim.fn.getpos("']")
  vim.api.nvim_buf_set_text(0, start_pos[2] - 1, start_pos[3] - 1, start_pos[2] - 1, start_pos[3] - 1, { txt })
  vim.api.nvim_buf_set_text(0, end_pos[2] - 1, end_pos[3], end_pos[2] - 1, end_pos[3], { txt })
end

vim.keymap.set({ 'n' }, '<leader><C-q>', function() surround_last_edit('"') end, { noremap = true, silent = true })

-- List of quote patterns to cycle through
local quote_patterns = {
  { left = "'", right = "'" },
  { left = '"', right = '"' },
  { left = "`", right = "`" },
  --{left = "<", right = ">"}
}

-- Function to find the nearest matching quotes
local function find_nearest_quotes(line, col)
  local left_quote, right_quote
  local left_pos, right_pos

  -- Search left for the nearest quote
  for i = col, 1, -1 do
    local char = line:sub(i, i)
    for _, pattern in ipairs(quote_patterns) do
      if char == pattern.left then
        left_quote, left_pos = pattern.left, i
        break
      end
    end
    if left_quote then break end
  end

  -- Search right for the nearest quote
  for i = col + 1, #line do
    local char = line:sub(i, i)
    for _, pattern in ipairs(quote_patterns) do
      if char == pattern.right then
        right_quote, right_pos = pattern.right, i
        break
      end
    end
    if right_quote then break end
  end

  return left_quote, right_quote, left_pos, right_pos
end

-- Function to cycle the quote style around the word under the cursor
local function cycle_quote_style()
  local row, col = unpack(vim.api.nvim_win_get_cursor(0))
  local line = vim.api.nvim_get_current_line()

  -- Find nearest quotes around the cursor
  local left_quote, right_quote, left_pos, right_pos = find_nearest_quotes(line, col)

  -- Detect current quote style
  local current_quote_index = nil
  for i, pattern in ipairs(quote_patterns) do
    if left_quote == pattern.left and right_quote == pattern.right then
      current_quote_index = i
      break
    end
  end

  -- Determine the next quote pattern to apply
  local next_quote_index
  if current_quote_index then
    next_quote_index = current_quote_index % #quote_patterns + 1
  else
    -- If no matching quotes were found, wrap the word under the cursor with the first quote pattern
    while col > 0 and line:sub(col, col):match("%S") do
      col = col - 1
    end
    next_quote_index = 1
    left_pos = col + 1
    right_pos = col + 1
  end

  local new_left_quote = quote_patterns[next_quote_index].left
  local new_right_quote = quote_patterns[next_quote_index].right

  -- Replace the text with the new quotes
  local new_line = line:sub(1, left_pos - 1) ..
      new_left_quote .. line:sub(left_pos + 1, right_pos - 1) .. new_right_quote .. line:sub(right_pos + 1)
  vim.api.nvim_set_current_line(new_line)
  -- vim.api.nvim_win_set_cursor(0, {row, right_pos + 1})
end
vim.keymap.set({ 'n' }, '<C-q>', function() cycle_quote_style() end, { noremap = true, silent = true })


-- Create an alias for helpgrep as Hg
vim.api.nvim_create_user_command('Hg', function(opts)
  vim.cmd("helpgrep " .. table.concat(opts.fargs, " "))
end, { nargs = "+" })

if vim.g.neovide then
  -- Put anything you want to happen only in Neovide here
  vim.g.neovide_normal_opacity = 0.8
end


-- Hypernav integration
local function detect_env()
  local env = {}

  env.in_tmux = os.getenv("TMUX") ~= nil
  env.in_hyprland = os.getenv("XDG_CURRENT_DESKTOP") == "Hyprland"

  return env
end

local env = detect_env()

local dir_map = {
  h = {
    hypr = "l",
    tmux = { "L", "pane_at_left" }
  },
  j = {
    hypr = "d",
    tmux = { "D", "pane_at_bottom" }
  },
  k = {
    hypr = "u",
    tmux = { "U", "pane_at_top" }
  },
  l = {
    hypr = "r",
    tmux = { "R", "pane_at_right" }
  }
}

local function tmux_command(cmd)
  local tmux_socket = vim.fn.split(vim.env.TMUX, ',')[1]
  return vim.fn.system("tmux -S " .. tmux_socket .. " " .. cmd)
end


local function nvim_nav(dir)
  local winnr = vim.fn.winnr()
  pcall(vim.cmd, 'wincmd '.. dir)
  -- Check if we navigated 
  return vim.fn.winnr() ~= winnr
end

local function hypr_nav(dir)
  vim.fn.system("hyprctl dispatch movefocus " .. dir_map[dir]['hypr'])
end

local function tmux_nav(dir)
  if not nvim_nav(dir) then
    local res = tmux_command('display -p "#{'.. dir_map[dir]['tmux'][2] ..'}"');
    -- print("Display res ".. res)
    -- Trimming the extra spaces n shit
    if res:match("^%s*(.-)%s*$") == '0' then
      res = tmux_command('select-pane "-'.. dir_map[dir]['tmux'][1]..'"');
    elseif env.in_hyprland then
      -- No panes in that direction, lets default to hypr_nav
      hypr_nav(dir)
    end
  end
end

-- Meta(windows) key gets eaten by tmux / terminal, so have to use ALT ... Fun
--
if env.in_tmux and env.in_hyprland then
  vim.keymap.set({ 'i', 'n' }, '<M-h>', function() tmux_nav('h') end, { noremap = true, silent = true })
  vim.keymap.set({ 'i', 'n' }, '<M-j>', function() tmux_nav('j') end, { noremap = true, silent = true })
  vim.keymap.set({ 'i', 'n' }, '<M-k>', function() tmux_nav('k') end, { noremap = true, silent = true })
  vim.keymap.set({ 'i', 'n' }, "<M-l>", function() tmux_nav('l') end, { noremap = true, silent = true })
else
  vim.keymap.set({ 'i', 'n' }, '<M-h>', function() nvim_nav('h') end, { noremap = true, silent = true })
  vim.keymap.set({ 'i', 'n' }, '<M-j>', function() nvim_nav('j') end, { noremap = true, silent = true })
  vim.keymap.set({ 'i', 'n' }, '<M-k>', function() nvim_nav('k') end, { noremap = true, silent = true })
  vim.keymap.set({ 'i', 'n' }, '<M-l>', function() nvim_nav('l') end, { noremap = true, silent = true })
end
