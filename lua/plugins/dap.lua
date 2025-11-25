local M = {}

function M.setup()
  local dap = require('dap')
  local dapui = require('dapui')

  dapui.setup()
  require('dap.ext.vscode').load_launchjs(nil, {
    cppdbg = { 'vscode' }, lldb = { 'vscode' }, coreclr = { 'vscode' }, go = { 'vscode' },
    python = { 'vscode' }, node2 = { 'vscode' }, pwa_node = { 'vscode' }, pwa_chrome = { 'vscode' },
    java = { 'vscode' }, rust = { 'vscode' },
  })

  local function set_debug_keymaps()
    local o = { noremap = true, silent = true }
    vim.keymap.set('n', 's', dap.step_over, o)      -- step over
    vim.keymap.set('n', 'i', dap.step_into, o)      -- step into
    vim.keymap.set('n', 'o', dap.step_out, o)       -- step out
    vim.keymap.set('n', 'c', dap.continue, o)       -- continue
    vim.keymap.set('n', 'b', dap.toggle_breakpoint, o) -- breakpoint
    vim.keymap.set('n', 'r', dap.restart, o)        -- restart
    vim.keymap.set('n', 'x', dap.terminate, o)      -- exit/kill
    vim.keymap.set('n', 'u', dap.up, o)             -- up stack frame
    vim.keymap.set('n', 'd', dap.down, o)           -- down stack frame
    vim.keymap.set('n', 't', function()            -- switch thread
      local widgets = require('dap.ui.widgets')
      widgets.centered_float(widgets.threads)
    end, o)
    vim.keymap.set('n', 'w', function()             -- watch word under cursor
      dapui.elements.watches.add(vim.fn.expand('<cword>'))
    end, o)
    vim.keymap.set('v', 'w', function()             -- watch visual selection
      dapui.elements.watches.add(vim.fn.getreg('v'))
    end, o)
  end
  local function clear_debug_keymaps()
    for _, key in ipairs({ 's', 'i', 'o', 'c', 'b', 'r', 'x', 'u', 'd', 't', 'w' }) do
      pcall(vim.keymap.del, 'n', key)
    end
    pcall(vim.keymap.del, 'v', 'w')
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

  -- Track last used config for quick restart
  local last_config = nil

  vim.keymap.set('n', '<leader>r', function()
    local ft = vim.bo.filetype
    local cfgs = dap.configurations.vscode or dap.configurations[ft]
    if not (cfgs and cfgs[1]) then
      return vim.notify("No DAP configs for filetype '" .. ft .. "'", vim.log.levels.WARN)
    end
    -- Use last config if set, otherwise first
    local cfg = vim.deepcopy(last_config or cfgs[1])
    if dap.session() then
      local key = 'restart_config'
      local function relaunch()
        dap.listeners.after.event_terminated[key] = nil
        dap.listeners.after.event_exited[key] = nil
        dap.run(cfg)
      end
      dap.listeners.after.event_terminated[key] = relaunch
      dap.listeners.after.event_exited[key] = relaunch
      return dap.terminate()
    end
    -- Build first, then run
    vim.fn.jobstart('make build', {
      on_exit = function(_, code)
        if code == 0 then
          vim.schedule(function() dap.run(cfg) end)
        else
          vim.notify('Build failed', vim.log.levels.ERROR)
        end
      end,
    })
  end, { desc = 'Debug: Build and run/restart' })

  vim.keymap.set('n', '<leader>R', function()
    local ft = vim.bo.filetype
    local cfgs = dap.configurations.vscode or dap.configurations[ft]
    if not (cfgs and cfgs[1]) then
      return vim.notify("No DAP configs for filetype '" .. ft .. "'", vim.log.levels.WARN)
    end
    vim.ui.select(cfgs, {
      prompt = 'Select debug config:',
      format_item = function(cfg) return cfg.name end,
    }, function(cfg)
      if cfg then
        last_config = cfg
        dap.run(vim.deepcopy(cfg))
      end
    end)
  end, { desc = 'Debug: Pick config' })

  local debug_ui_open = false
  vim.keymap.set('n', '<leader>du', function()
    dapui.toggle()
    debug_ui_open = not debug_ui_open
    if debug_ui_open and dap.session() then
      set_debug_keymaps()
    else
      clear_debug_keymaps()
    end
  end, { desc = 'Debug: Toggle UI' })
  vim.keymap.set('n', '<leader>de', function() dap.repl.open() end, { desc = 'Debug: Open REPL' })

  dap.listeners.after.event_initialized.debug_single_keys = function() set_debug_keymaps() end
  dap.listeners.before.event_terminated.debug_single_keys = function() clear_debug_keymaps() end
  dap.listeners.before.event_exited.debug_single_keys = function() clear_debug_keymaps() end
  dap.listeners.after.event_terminated.debug_single_keys = function() clear_debug_keymaps() end
  dap.listeners.after.event_exited.debug_single_keys = function() clear_debug_keymaps() end


  -- Don't auto-close UI so you can see output after program exits
  -- Use <leader>du to manually close when done

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

  dap.adapters.gdb = {
    type = 'executable',
    command = 'gdb',
    args = {
      '--interpreter=dap',
      '--eval-command', 'set print pretty on',
      '--eval-command', 'handle SIGSEGV stop print',
      '--eval-command', 'handle SIGABRT stop print',
    },
  }
  dap.adapters.lldb = { type = 'executable', command = 'lldb-dap', name = 'lldb' }
end

return M
