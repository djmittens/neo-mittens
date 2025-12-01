-- neo-mittens unified debug interface
-- Single keymaps that work with both gdb and DAP backends

local M = {}

M.debug_mode = false
M.active_backend = nil  -- 'gdb' or 'dap'

-- Debug state from gdb
M.state = {
  breakpoints = {},  -- {num, file, line, enabled}
  frame = nil,       -- {file, line, func}
}

-- Use extmarks for debug signs - they respect sign column ordering better
local ns = vim.api.nvim_create_namespace('neo_mittens_debug')

-- Placeholder sign to reserve the left column for gitsigns
local signs_defined = false
local function define_signs()
  if signs_defined then return end
  vim.fn.sign_define('DbgPlaceholder', { text = '  ' })
  signs_defined = true
end

local sign_group = 'neo_mittens_debug'

-- Cache file path -> bufnr mapping
local path_to_buf_cache = {}

-- Find buffer by file path (handles relative/absolute path differences)
local function find_buffer(filepath)
  if not filepath or type(filepath) ~= 'string' or filepath == '' then
    return -1
  end

  -- Check cache first
  local cached = path_to_buf_cache[filepath]
  if cached and vim.api.nvim_buf_is_valid(cached) then
    return cached
  end

  -- Try exact match
  local bufnr = vim.fn.bufnr(filepath)
  if bufnr ~= -1 then
    path_to_buf_cache[filepath] = bufnr
    return bufnr
  end

  -- Try full path match
  local fullpath = vim.fn.fnamemodify(filepath, ':p')
  bufnr = vim.fn.bufnr(fullpath)
  if bufnr ~= -1 then
    path_to_buf_cache[filepath] = bufnr
    return bufnr
  end

  return -1
end

-- Check if value is valid (not nil, not vim.NIL)
local function is_valid(v)
  return v ~= nil and v ~= vim.NIL
end

-- Track which buffers have our signs (for efficient cleanup)
local signed_buffers = {}

-- Update signs based on current state
local function update_signs()
  define_signs()

  -- Clear only buffers we've touched (not all buffers)
  vim.fn.sign_unplace(sign_group)
  for bufnr in pairs(signed_buffers) do
    if vim.api.nvim_buf_is_valid(bufnr) then
      vim.api.nvim_buf_clear_namespace(bufnr, ns, 0, -1)
    end
  end
  signed_buffers = {}

  -- Get frame location
  local frame = M.state.frame
  local frame_file, frame_line
  if is_valid(frame) and is_valid(frame.file) and is_valid(frame.line) then
    frame_file = vim.fn.fnamemodify(frame.file, ':p')
    frame_line = frame.line
  end

  -- Build map of lines needing signs: [bufnr][line] = {bp, frame}
  local signs_needed = {}

  -- Add breakpoints
  local bps = M.state.breakpoints
  if is_valid(bps) then
    for _, bp in ipairs(bps) do
      if is_valid(bp.file) and is_valid(bp.line) then
        local bufnr = find_buffer(bp.file)
        if bufnr ~= -1 then
          signs_needed[bufnr] = signs_needed[bufnr] or {}
          signs_needed[bufnr][bp.line] = signs_needed[bufnr][bp.line] or {}
          signs_needed[bufnr][bp.line].bp = bp.enabled and 'enabled' or 'disabled'
        end
      end
    end
  end

  -- Add frame
  if frame_file and frame_line then
    local bufnr = find_buffer(frame_file)
    if bufnr ~= -1 then
      signs_needed[bufnr] = signs_needed[bufnr] or {}
      signs_needed[bufnr][frame_line] = signs_needed[bufnr][frame_line] or {}
      signs_needed[bufnr][frame_line].frame = true
    end
  end

  -- Place signs
  for bufnr, lines in pairs(signs_needed) do
    signed_buffers[bufnr] = true
    for line, info in pairs(lines) do
      -- Placeholder for left column
      vim.fn.sign_place(0, sign_group, 'DbgPlaceholder', bufnr, { lnum = line, priority = 99 })

      -- Determine sign
      local sign_text, sign_hl, line_hl
      if info.frame and info.bp then
        sign_text = info.bp == 'enabled' and '●→' or '○→'
        sign_hl = info.bp == 'enabled' and 'DiagnosticError' or 'DiagnosticHint'
        line_hl = 'CursorLine'
      elseif info.frame then
        sign_text = '→'
        sign_hl = 'DiagnosticWarn'
        line_hl = 'CursorLine'
      elseif info.bp then
        sign_text = info.bp == 'enabled' and '●' or '○'
        sign_hl = info.bp == 'enabled' and 'DiagnosticError' or 'DiagnosticHint'
      end

      vim.api.nvim_buf_set_extmark(bufnr, ns, line - 1, 0, {
        sign_text = sign_text,
        sign_hl_group = sign_hl,
        line_hl_group = line_hl,
        priority = 10,
      })
    end
  end
end

-- Called from gdb via nvim socket
function M.on_gdb_state(state_json)
  local ok, state = pcall(vim.json.decode, state_json)
  if ok and state then
    local old_frame = M.state.frame
    M.state = state
    update_signs()
    -- Jump to new frame location if changed
    local frame = state.frame
    if is_valid(frame) and is_valid(frame.file) and is_valid(frame.line) then
      local new_file = frame.file
      local new_line = frame.line
      local should_jump = not is_valid(old_frame)
        or old_frame.file ~= new_file
        or old_frame.line ~= new_line
      if should_jump then
        M.goto_location(new_file, new_line)
      end
    end
    -- Trigger screen refresh
    vim.cmd('redraw')
  end
end

-- Jump to file:line from gdb (smart - only loads file if needed)
function M.goto_location(file, line)
  local current = vim.fn.expand('%:p')
  if current ~= file then
    -- Different file - check if buffer exists
    local bufnr = vim.fn.bufnr(file)
    if bufnr ~= -1 then
      vim.api.nvim_set_current_buf(bufnr)
    else
      vim.cmd('e ' .. vim.fn.fnameescape(file))
    end
  end
  vim.api.nvim_win_set_cursor(0, { line, 0 })
  vim.cmd('normal! zz')
end

-- Statusline component
function M.statusline()
  if not M.debug_mode then
    return ''
  end

  local parts = {}

  -- Breakpoint count
  local bp_count = #M.state.breakpoints
  if bp_count > 0 then
    local enabled = 0
    for _, bp in ipairs(M.state.breakpoints) do
      if bp.enabled then enabled = enabled + 1 end
    end
    table.insert(parts, string.format(' %d', enabled))
  end

  -- Current frame
  if M.state.frame then
    local func = M.state.frame.func or '??'
    local line = M.state.frame.line or 0
    table.insert(parts, string.format(' %s:%d', func, line))
  end

  if #parts == 0 then
    return '  Debug'
  end

  return '  ' .. table.concat(parts, '  ')
end

-- Backend modules (lazy loaded)
local function get_gdb()
  return require('neo-mittens.gdb-bridge')
end

local function get_dap()
  return require('dap')
end

-- Unified commands that route to active backend
function M.step_over()
  if M.active_backend == 'gdb' then
    get_gdb().next()
  elseif M.active_backend == 'dap' then
    get_dap().step_over()
  end
end

function M.step_into()
  if M.active_backend == 'gdb' then
    get_gdb().step()
  elseif M.active_backend == 'dap' then
    get_dap().step_into()
  end
end

function M.step_out()
  if M.active_backend == 'gdb' then
    get_gdb().finish()
  elseif M.active_backend == 'dap' then
    get_dap().step_out()
  end
end

function M.continue()
  if M.active_backend == 'gdb' then
    get_gdb().continue()
  elseif M.active_backend == 'dap' then
    get_dap().continue()
  end
end

function M.breakpoint_toggle()
  if M.active_backend == 'gdb' then
    get_gdb().breakpoint_toggle()
  elseif M.active_backend == 'dap' then
    get_dap().toggle_breakpoint()
  end
end

function M.run()
  if M.active_backend == 'gdb' then
    get_gdb().run()
  elseif M.active_backend == 'dap' then
    get_dap().continue()  -- DAP uses continue to start
  end
end

function M.stop()
  if M.active_backend == 'gdb' then
    get_gdb().kill()
  elseif M.active_backend == 'dap' then
    get_dap().terminate()
  end
  M.exit_debug_mode()
end

function M.up()
  if M.active_backend == 'gdb' then
    get_gdb().up()
  elseif M.active_backend == 'dap' then
    get_dap().up()
  end
end

function M.down()
  if M.active_backend == 'gdb' then
    get_gdb().down()
  elseif M.active_backend == 'dap' then
    get_dap().down()
  end
end

function M.print_word()
  local word = vim.fn.expand('<cword>')
  if M.active_backend == 'gdb' then
    get_gdb().print_word()
  elseif M.active_backend == 'dap' then
    require('dap.ui.widgets').hover()
  end
end

-- Debug mode keymaps
-- In debug mode you shouldn't edit (line numbers would desync with gdb)
-- So we hijack edit keys for debug commands (mnemonic: s=step, i=into, c=continue, etc.)
local debug_keys = {
  { 's', 'step_over', 'Step over' },
  { 'i', 'step_into', 'Step into' },
  { 'o', 'step_out', 'Step out' },
  { 'c', 'continue', 'Continue' },
  { 'b', 'breakpoint_toggle', 'Toggle breakpoint' },
  { 'r', 'run', 'Run/restart' },
  { 'x', 'stop', 'Stop/kill' },
  { 'u', 'up', 'Frame up' },
  { 'd', 'down', 'Frame down' },
  { 'p', 'print_word', 'Print word' },
  { 'q', 'exit_debug_mode', 'Exit debug mode' },
}

local function set_debug_keymaps()
  local o = { noremap = true, silent = true }
  for _, km in ipairs(debug_keys) do
    vim.keymap.set('n', km[1], function() M[km[2]]() end, vim.tbl_extend('force', o, { desc = km[3] }))
  end
end

local function clear_debug_keymaps()
  for _, km in ipairs(debug_keys) do
    pcall(vim.keymap.del, 'n', km[1])
  end
end

function M.enter_debug_mode(backend)
  if not M.debug_mode then
    M.debug_mode = true
    M.active_backend = backend
    set_debug_keymaps()
    -- Expand sign column to fit both gitsigns and debug signs
    vim.o.signcolumn = 'yes:2'
    -- Sync state from debugger (in case it was started before nvim)
    if backend == 'gdb' then
      vim.defer_fn(function()
        get_gdb().request_state()
      end, 100)
    end
    vim.schedule(function()
      vim.api.nvim_echo({{'Debug mode (' .. backend .. ') - q to exit', 'Normal'}}, false, {})
    end)
  end
end

function M.exit_debug_mode()
  if M.debug_mode then
    M.debug_mode = false
    M.active_backend = nil
    clear_debug_keymaps()
    -- Clear debug signs and restore single sign column
    vim.fn.sign_unplace(sign_group)
    for _, buf in ipairs(vim.api.nvim_list_bufs()) do
      if vim.api.nvim_buf_is_valid(buf) then
        vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
      end
    end
    vim.o.signcolumn = 'yes'
    vim.api.nvim_echo({{'Exited debug mode', 'Normal'}}, false, {})
  end
end

function M.toggle_debug_mode()
  if M.debug_mode then
    M.exit_debug_mode()
  else
    -- Enter with default backend
    local backend = get_gdb().get_backend()
    M.enter_debug_mode(backend)
  end
end

-- Get preferred backend for current filetype
function M.get_backend()
  return get_gdb().get_backend()
end

-- Last used config (persists across runs)
M.last_config = nil

-- Launch debug session with a specific config (no picker)
function M.launch_config(cfg)
  if not cfg then
    vim.notify('No config to launch', vim.log.levels.WARN)
    return
  end

  M.last_config = cfg
  local backend = M.get_backend()

  if backend == 'gdb' then
    M.enter_debug_mode('gdb')
    get_gdb().start_with_config(cfg)
  else
    M.enter_debug_mode('dap')
    require('dapui').open()
    get_dap().run(cfg)
  end
end

-- Launch last config, or pick if none
function M.launch()
  if M.last_config then
    M.launch_config(M.last_config)
  else
    M.launch_pick()
  end
end

-- Show picker and launch selected config
function M.launch_pick()
  local backend = M.get_backend()

  if backend == 'gdb' then
    local gdb = get_gdb()
    local configs = gdb.load_configs()
    if #configs == 0 then
      vim.notify('No debug configs for this filetype', vim.log.levels.WARN)
      return
    end

    vim.ui.select(configs, {
      prompt = 'Debug config:',
      format_item = function(c) return c.name end,
    }, function(cfg)
      if cfg then
        M.launch_config(cfg)
      end
    end)
  else
    local dap = get_dap()
    local ft = vim.bo.filetype
    local configs = dap.configurations[ft]
    if not configs or #configs == 0 then
      vim.notify('No DAP configs for this filetype', vim.log.levels.WARN)
      return
    end

    vim.ui.select(configs, {
      prompt = 'Debug config:',
      format_item = function(c) return c.name end,
    }, function(cfg)
      if cfg then
        M.launch_config(cfg)
      end
    end)
  end
end

-- Sync state from gdb (call on entering debug mode or periodically)
function M.sync_state()
  if M.active_backend == 'gdb' then
    get_gdb().request_state()
  end
end

-- Setup main keybindings
function M.setup()
  vim.keymap.set('n', '<leader>r', M.launch, { desc = 'Run last debug config (or pick)' })
  vim.keymap.set('n', '<leader>R', M.launch_pick, { desc = 'Pick debug config' })
  vim.keymap.set('n', '<leader>dd', M.toggle_debug_mode, { desc = 'Toggle debug mode' })
end

return M
