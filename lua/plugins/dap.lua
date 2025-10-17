local M = {}

function M.setup()
  local dap = require('dap')
  local dapui = require('dapui')

  dapui.setup({})
  require('dap.ext.vscode').load_launchjs(nil, {
    cppdbg = { 'vscode' }, lldb = { 'vscode' }, coreclr = { 'vscode' }, go = { 'vscode' },
    python = { 'vscode' }, node2 = { 'vscode' }, pwa_node = { 'vscode' }, pwa_chrome = { 'vscode' },
    java = { 'vscode' }, rust = { 'vscode' },
  })

  local function set_debug_keymaps()
    local o = { noremap = true, silent = true }
    vim.keymap.set('n', '<leader>n', dap.step_over, o)
    vim.keymap.set('n', '<leader>s', dap.step_into, o)
    vim.keymap.set('n', '<leader>o', dap.step_out, o)
    vim.keymap.set('n', '<leader>c', dap.continue, o)
    vim.keymap.set('n', '<leader>b', dap.toggle_breakpoint, o)
    vim.keymap.set('n', '<leader>r', dap.restart, o)
    vim.keymap.set('n', '<leader>q', dap.terminate, o)
  end
  local function clear_debug_keymaps()
    for _, key in ipairs({ 'n', 's', 'o', 'c', 'b', 'r', 'q' }) do
      pcall(vim.keymap.del, 'n', '<leader>' .. key)
    end
  end

  local api = vim.api
  local keymap_restore = {}
  dap.listeners.after['event_initialized']['me'] = function()
    for _, buf in pairs(api.nvim_list_bufs()) do
      local keymaps = api.nvim_buf_get_keymap(buf, 'n')
      for _, keymap in pairs(keymaps) do
        if keymap.lhs == 'K' then
          table.insert(keymap_restore, keymap)
          api.nvim_buf_del_keymap(buf, 'n', 'K')
        end
      end
    end
    api.nvim_set_keymap('n', 'K', '<Cmd>lua require("dap.ui.widgets").hover()<CR>', { silent = true })
  end

  vim.keymap.set('n', '<leader>r', function()
    local cfgs = dap.configurations.vscode
    if not (cfgs and cfgs[1]) then
      return vim.notify("No launch.json configs loaded under 'vscode'.", vim.log.levels.WARN)
    end
    local cfg = vim.deepcopy(cfgs[1])
    if dap.session() then
      local key = 'restart_first_vscode'
      local function relaunch()
        dap.listeners.after.event_terminated[key] = nil
        dap.listeners.after.event_exited[key] = nil
        dap.run(cfg)
      end
      dap.listeners.after.event_terminated[key] = relaunch
      dap.listeners.after.event_exited[key] = relaunch
      return dap.terminate()
    end
    dap.run(cfg)
  end, { desc = 'Debug: Restart first launch config' })

  dap.listeners.after.event_initialized.debug_single_keys = function() set_debug_keymaps() end
  dap.listeners.before.event_terminated.debug_single_keys = function() clear_debug_keymaps() end
  dap.listeners.before.event_exited.debug_single_keys = function() clear_debug_keymaps() end
  dap.listeners.after.event_terminated.debug_single_keys = function() clear_debug_keymaps() end
  dap.listeners.after.event_exited.debug_single_keys = function() clear_debug_keymaps() end

  dap.listeners.before.attach.dapui_config = function() dapui.open() end
  dap.listeners.before.launch.dapui_config = function() dapui.open() end
  dap.listeners.before.event_terminated.dapui_config = function() dapui.close() end
  dap.listeners.before.event_exited.dapui_config = function() dapui.close() end

  dap.listeners.after['event_terminated']['me'] = function()
    for _, keymap in pairs(keymap_restore) do
      if keymap.rhs then
        api.nvim_buf_set_keymap(keymap.buffer, keymap.mode, keymap.lhs, keymap.rhs, { silent = keymap.silent == 1 })
      elseif keymap.callback then
        vim.keymap.set(keymap.mode, keymap.lhs, keymap.callback, { buffer = keymap.buffer, silent = keymap.silent == 1 })
      end
    end
    keymap_restore = {}
  end

  dap.adapters.gdb = { type = 'executable', command = 'gdb', args = { '--interpreter=dap', '--eval-command', 'set print pretty on' } }
end

return M

