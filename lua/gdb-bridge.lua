-- neo-mittens gdb bridge
-- Lightweight integration: nvim sends commands to gdb via named pipe

local M = {}

-- Project-based paths
local function get_project_name()
  local cwd = vim.fn.getcwd()
  return vim.fn.fnamemodify(cwd, ':t')
end

function M.get_socket_path()
  return '/tmp/nvim-' .. get_project_name() .. '.sock'
end

function M.get_pipe_path()
  return '/tmp/gdb-' .. get_project_name() .. '.pipe'
end

local function send_to_gdb(cmd)
  local pipe_path = M.get_pipe_path()

  -- Check if pipe exists (gdb creates it when it starts)
  local stat = vim.loop.fs_stat(pipe_path)
  if not stat then
    -- Pipe doesn't exist - gdb not running, silently ignore
    return
  end


  -- Use async job to avoid blocking on FIFO
  -- timeout after 1 second in case gdb isn't reading
  vim.fn.jobstart({ 'timeout', '1', 'sh', '-c', 'echo ' .. vim.fn.shellescape(cmd) .. ' > ' .. vim.fn.shellescape(pipe_path) }, {
    on_exit = function(_, code)
      if code == 124 then
        -- timeout - gdb not reading from pipe
        vim.schedule(function()
          vim.notify('gdb not responding', vim.log.levels.WARN)
        end)
      end
    end,
  })
end

function M.breakpoint_toggle()
  local file = vim.fn.expand('%:p')
  local line = vim.fn.line('.')
  send_to_gdb(string.format('tb %s:%d', file, line))
end

function M.breakpoint_clear()
  local file = vim.fn.expand('%:p')
  local line = vim.fn.line('.')
  send_to_gdb(string.format('clear %s:%d', file, line))
end

function M.run()
  send_to_gdb('run')
end

function M.continue()
  send_to_gdb('continue')
end

function M.step()
  send_to_gdb('step')
end

function M.next()
  send_to_gdb('next')
end

function M.finish()
  send_to_gdb('finish')
end

function M.up()
  send_to_gdb('up')
end

function M.down()
  send_to_gdb('down')
end

function M.print_word()
  local word = vim.fn.expand('<cword>')
  send_to_gdb('print ' .. word)
end

function M.kill()
  send_to_gdb('set confirm off')
  send_to_gdb('kill')
  send_to_gdb('set confirm on')
end

function M.quit()
  send_to_gdb('quit')
end

-- Get debug backend: project setting > filetype default > 'dap'
function M.get_backend()
  -- Project override
  if vim.g.debug_backend then
    return vim.g.debug_backend
  end
  -- Filetype defaults
  local ft = vim.bo.filetype
  if ft == 'c' or ft == 'cpp' then
    return 'gdb'
  end
  return 'dap'
end

-- Load configs from DAP
function M.load_configs()
  local ok, dap = pcall(require, 'dap')
  if not ok then return {} end
  local ft = vim.bo.filetype
  return dap.configurations[ft] or {}
end

-- Start debugging with selected config
function M.start_with_config(cfg)
  local args = cfg.args
  if type(args) == 'function' then args = args() end
  if type(args) == 'table' then args = table.concat(args, ' ') end
  args = args or ''

  -- Single command to gdb that handles everything
  local cmd = 'start_debug ' .. cfg.program
  if args ~= '' then
    cmd = cmd .. ' -- ' .. args
  end
  send_to_gdb(cmd)
end

-- Pick config and start
function M.pick_and_start()
  local configs = M.load_configs()
  if #configs == 0 then
    vim.notify('No debug configs for this filetype', vim.log.levels.WARN)
    return
  end

  vim.ui.select(configs, {
    prompt = 'Debug config:',
    format_item = function(c) return c.name end,
  }, function(cfg)
    if cfg then
      M.start_with_config(cfg)
    end
  end)
end

-- Request state from gdb (for polling)
function M.request_state()
  send_to_gdb('push_state')
end

-- Unified debug command - uses configured backend
function M.debug_run()
  local backend = M.get_backend()
  if backend == 'gdb' then
    M.pick_and_launch()
  else
    -- Use DAP
    local dap = require('dap')
    local dapui = require('dapui')
    local ft = vim.bo.filetype
    local configs = dap.configurations[ft]
    if not configs or not configs[1] then
      vim.notify('No DAP configs for this filetype', vim.log.levels.WARN)
      return
    end
    dapui.toggle()
    dap.run(configs[1])
  end
end

-- Commands
vim.api.nvim_create_user_command('Gb', function() M.breakpoint_toggle() end, { desc = 'Toggle gdb breakpoint' })
vim.api.nvim_create_user_command('Gc', function() M.breakpoint_clear() end, { desc = 'Clear gdb breakpoint' })
vim.api.nvim_create_user_command('Gp', function() M.print_word() end, { desc = 'Print word under cursor in gdb' })
vim.api.nvim_create_user_command('GdbRun', function() M.pick_and_start() end, { desc = 'Run gdb with config' })

-- Always start project socket for gdb communication
local socket_path = M.get_socket_path()
vim.fn.serverstart(socket_path)

return M
