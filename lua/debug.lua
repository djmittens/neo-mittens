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

-- Sign definitions
local signs_defined = false
local function define_signs()
  if signs_defined then return end
  vim.fn.sign_define('DbgBreakpoint', { text = '', texthl = 'DiagnosticError' })
  vim.fn.sign_define('DbgBreakpointDisabled', { text = '', texthl = 'DiagnosticHint' })
  vim.fn.sign_define('DbgCurrentLine', { text = '', texthl = 'DiagnosticWarn' })
  signs_defined = true
end

-- Sign group for our signs
local sign_group = 'neo_mittens_debug'

-- Find buffer by file path (handles relative/absolute path differences)
local function find_buffer(filepath)
  if not filepath then return -1 end
  -- Try exact match first
  local bufnr = vim.fn.bufnr(filepath)
  if bufnr ~= -1 then return bufnr end
  -- Try matching by filename
  local fname = vim.fn.fnamemodify(filepath, ':t')
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(buf) then
      local bufname = vim.api.nvim_buf_get_name(buf)
      if bufname == filepath or vim.fn.fnamemodify(bufname, ':t') == fname then
        -- Verify full path matches if possible
        if vim.fn.fnamemodify(bufname, ':p') == vim.fn.fnamemodify(filepath, ':p') then
          return buf
        end
      end
    end
  end
  return -1
end

-- Update signs based on current state
local function update_signs()
  define_signs()
  -- Clear all our signs
  vim.fn.sign_unplace(sign_group)

  -- Place breakpoint signs
  for _, bp in ipairs(M.state.breakpoints) do
    if bp.file and bp.line then
      local sign_name = bp.enabled and 'DbgBreakpoint' or 'DbgBreakpointDisabled'
      local bufnr = find_buffer(bp.file)
      if bufnr ~= -1 then
        vim.fn.sign_place(0, sign_group, sign_name, bufnr, { lnum = bp.line, priority = 20 })
      end
    end
  end

  -- Place current line sign
  if M.state.frame and M.state.frame.file and M.state.frame.line then
    local bufnr = find_buffer(M.state.frame.file)
    if bufnr ~= -1 then
      vim.fn.sign_place(0, sign_group, 'DbgCurrentLine', bufnr, { lnum = M.state.frame.line, priority = 30 })
    end
  end
end

-- Called from gdb via nvim socket
function M.on_gdb_state(state_json)
  local ok, state = pcall(vim.json.decode, state_json)
  if ok and state then
    M.state = state
    update_signs()
    -- Trigger statusline refresh
    vim.cmd('redrawstatus')
  end
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
    -- Sync state from debugger (in case it was started before nvim)
    if backend == 'gdb' then
      vim.defer_fn(function()
        get_gdb().request_state()
      end, 100)
    end
    vim.notify('Debug mode (' .. backend .. ') - q to exit', vim.log.levels.INFO)
  end
end

function M.exit_debug_mode()
  if M.debug_mode then
    M.debug_mode = false
    M.active_backend = nil
    clear_debug_keymaps()
    vim.notify('Exited debug mode', vim.log.levels.INFO)
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

-- Launch debug session with appropriate backend
function M.launch()
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
        M.enter_debug_mode('gdb')
        gdb.start_with_config(cfg)
      end
    end)
  else
    local dap = get_dap()
    local dapui = require('dapui')
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
        M.enter_debug_mode('dap')
        dapui.open()
        dap.run(cfg)
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

-- Setup main keybinding
function M.setup()
  vim.keymap.set('n', '<leader>r', M.launch, { desc = 'Launch debugger' })
  vim.keymap.set('n', '<leader>dd', M.toggle_debug_mode, { desc = 'Toggle debug mode' })
end

return M
