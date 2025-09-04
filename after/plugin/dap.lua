local dap, dapui = require("dap"), require("dapui")

dapui.setup({})
require("dap.ext.vscode").load_launchjs(nil, {
  cppdbg     = { "vscode" },
  lldb       = { "vscode" },
  coreclr    = { "vscode" },
  go         = { "vscode" },
  python     = { "vscode" },
  node2      = { "vscode" },
  pwa_node   = { "vscode" },
  pwa_chrome = { "vscode" },
  java       = { "vscode" },
  rust       = { "vscode" },
})

-- Temporary debug single-key maps
local function set_debug_keymaps()
  local o = { noremap = true, silent = true }
  vim.keymap.set("n", "<leader>n", dap.step_over, o)      -- next
  vim.keymap.set("n", "<leader>s", dap.step_into, o)      -- step in
  vim.keymap.set("n", "<leader>o", dap.step_out, o)       -- step out
  vim.keymap.set("n", "<leader>c", dap.continue, o)       -- continue
  vim.keymap.set("n", "<leader>b", dap.toggle_breakpoint, o)
  vim.keymap.set("n", "<leader>r", dap.restart, o)
  vim.keymap.set("n", "<leader>q", dap.terminate, o)
end

local function clear_debug_keymaps()
  for _, key in ipairs({ "n", "s", "o", "c", "b", "r", "q" }) do
    pcall(vim.keymap.del, "n", "<leader>" .. key)
  end
end

-- Make K be dap hover when enabled
local api = vim.api
local keymap_restore = {}
dap.listeners.after['event_initialized']['me'] = function()
  for _, buf in pairs(api.nvim_list_bufs()) do
    local keymaps = api.nvim_buf_get_keymap(buf, 'n')
    for _, keymap in pairs(keymaps) do
      if keymap.lhs == "K" then
        table.insert(keymap_restore, keymap)
        api.nvim_buf_del_keymap(buf, 'n', 'K')
      end
    end
  end
  api.nvim_set_keymap(
    'n', 'K', '<Cmd>lua require("dap.ui.widgets").hover()<CR>', { silent = true })
end

vim.keymap.set("n", "<leader>r", function()
  local cfgs = dap.configurations.vscode
  if not (cfgs and cfgs[1]) then
    return vim.notify("No launch.json configs loaded under 'vscode'.", vim.log.levels.WARN)
  end

  local cfg = vim.deepcopy(cfgs[1])

  -- terminate first (common for C++ debuggers)
  if dap.session() then
    local key = "restart_first_vscode"
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
end, { desc = "Debug: Restart first launch config" })

-- Use a different listener key than dapui ("debug_single_keys")
-- Open dapui BEFORE we set keys, close dapui BEFORE we restore keys.
-- We set keys AFTER session starts, and restore keys AFTER it ends,
-- so UI open/close doesn’t race with our maps.
dap.listeners.after.event_initialized.debug_single_keys = function()
  set_debug_keymaps()
end

dap.listeners.before.event_terminated.debug_single_keys = function()
  -- Optional: also restore before termination, in case adapters misfire
  clear_debug_keymaps()
end
dap.listeners.before.event_exited.debug_single_keys = function()
  clear_debug_keymaps()
end
dap.listeners.after.event_terminated.debug_single_keys = function()
  clear_debug_keymaps()
end
dap.listeners.after.event_exited.debug_single_keys = function()
  clear_debug_keymaps()
end

dap.listeners.before.attach.dapui_config = function()
  dapui.open()
end
dap.listeners.before.launch.dapui_config = function()
  dapui.open()
end
dap.listeners.before.event_terminated.dapui_config = function()
  dapui.close()
end
dap.listeners.before.event_exited.dapui_config = function()
  dapui.close()
end

dap.listeners.after['event_terminated']['me'] = function()
  for _, keymap in pairs(keymap_restore) do
    if keymap.rhs then
      api.nvim_buf_set_keymap(
        keymap.buffer,
        keymap.mode,
        keymap.lhs,
        keymap.rhs,
        { silent = keymap.silent == 1 }
      )
    elseif keymap.callback then
      vim.keymap.set(
        keymap.mode,
        keymap.lhs,
        keymap.callback,
        { buffer = keymap.buffer, silent = keymap.silent == 1 }
      )
    end
  end
  keymap_restore = {}
end

-- dap.adapters.codelldb = {
--   type = 'server',
--   port = "${port}",
--   executable = {
--     -- CHANGE THIS to your path!
--     command = vim.fn.expand('$HOME/bin/codelldb/adapter/codelldb'),
--     args = { "--port", "${port}" },
--
--     -- On windows you may have to uncomment this:
--     -- detached = false,
--   }
-- }

dap.adapters.gdb = {
  type = "executable",
  command = "gdb",
  args = { "--interpreter=dap", "--eval-command", "set print pretty on" }
}


-- dap.configurations.cpp = {
--   {
--     name = "Launch file",
--     type = "codelldb",
--     request = "launch",
--     -- program = function()
--     --   return vim.fn.input('Path to executable: ', vim.fn.getcwd() .. '/', 'file')
--     -- end,
--     program = vim.fn.getcwd() .. "/build/bin/hello-opengl",
--     cwd = '${workspaceFolder}',
--     stopOnEntry = false,
--   },
-- }

dap.configurations.scala = {
  {
    type = "scala",
    request = "launch",
    name = "RunOrTest",
    metals = {
      runType = "runOrTestFile",
      --args = { "firstArg", "secondArg", "thirdArg" }, -- here just as an example
    },
  },
  {
    type = "scala",
    request = "launch",
    name = "Test Target",
    metals = {
      runType = "testTarget",
    },
  },
  {
    type = "scala",
    request = "attach",
    name = "Attach to Localhost",
    hostName = "localhost",
    port = 5005,
    -- buildTarget = "root",
    -- buildTarget = "capabilities-internal-talon-persistence",
    buildTarget = "capabilities-internal-talon-persistence-test",
  }
}


local pickers = require("telescope.pickers")
local finders = require("telescope.finders")
local conf = require("telescope.config").values
local actions = require("telescope.actions")
local action_state = require("telescope.actions.state")


local function telescope_select_exec()
  return coroutine.create(function(coro)
    local opts = {}
    pickers
        .new(opts, {
          prompt_title = "Path to executable",
          finder = finders.new_oneshot_job({ "fd", "--hidden", "--no-ignore", "--type", "x", "", "build/", "bin/" }, {}),
          sorter = conf.generic_sorter(opts),
          attach_mappings = function(buffer_number)
            actions.select_default:replace(function()
              actions.close(buffer_number)
              coroutine.resume(coro, action_state.get_selected_entry()[1])
            end)
            return true
          end,
        })
        :find()
  end)
end

-- dap.configurations.c = {
--   {
--     name = "Launch an executable",
--     type = "gdb",
--     request = "launch",
--     program = telescope_select_exec,
--     cwd = "${workspaceFolder}",
--     stopAtBeginningOfMainSubprogram = false,
--   },
-- }

vim.keymap.set('n', '<F5>', function() require('dap').continue() end)
vim.keymap.set('n', '<leader>l', function() require('dap').continue() end)
vim.keymap.set('n', '<F10>', function() require('dap').step_over() end)
vim.keymap.set('n', '<leader>j', function() require('dap').step_over() end)
vim.keymap.set('n', '<F11>', function() require('dap').step_into() end)
vim.keymap.set('n', '<leader>k', function() require('dap').step_into() end)
vim.keymap.set('n', '<F12>', function() require('dap').step_out() end)
vim.keymap.set('n', '<Leader>b', function() require('dap').toggle_breakpoint() end)
vim.keymap.set('n', '<Leader>B', function() require('dap').set_breakpoint() end)
vim.keymap.set('n', '<Leader>bp',
  function() require('dap').set_breakpoint(nil, nil, vim.fn.input('Log point message: ')) end)
vim.keymap.set('n', '<Leader>dr', function() require('dap').repl.open() end)
vim.keymap.set('n', '<Leader>dl', function() require('dap').run_last() end)
vim.keymap.set({ 'n', 'v' }, '<Leader>dh', function()
  require('dap.ui.widgets').hover()
end)
vim.keymap.set({ 'n', 'v' }, '<Leader>dp', function()
  require('dap.ui.widgets').preview()
end)
vim.keymap.set('n', '<Leader>df', function()
  local widgets = require('dap.ui.widgets')
  widgets.centered_float(widgets.frames)
end)
vim.keymap.set('n', '<Leader>ds', function()
  local widgets = require('dap.ui.widgets')
  widgets.centered_float(widgets.scopes)
end)
