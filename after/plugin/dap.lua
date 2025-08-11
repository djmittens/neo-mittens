local dap, dapui = require("dap"), require("dapui")

dapui.setup({})

-- Temporary debug single-key maps
local function set_debug_keymaps()
  local o = { silent = true, noremap = true }
  vim.keymap.set("n", "c", function() dap.continue() end, o)       -- Continue
  vim.keymap.set("n", "n", function() dap.step_over() end, o)      -- Next
  vim.keymap.set("n", "s", function() dap.step_into() end, o)      -- Step into
  vim.keymap.set("n", "o", function() dap.step_out() end, o)       -- Step out
  vim.keymap.set("n", "b", function() dap.toggle_breakpoint() end, o) -- Breakpoint
end

local function restore_normal_keymaps()
  pcall(vim.keymap.del, "n", "c")
  pcall(vim.keymap.del, "n", "n")
  pcall(vim.keymap.del, "n", "s")
  pcall(vim.keymap.del, "n", "o")
  pcall(vim.keymap.del, "n", "b")

  -- Restore global and lua-only maps
  vim.keymap.set("n", "c", "<Cmd>nohlsearch<CR>", { desc = "Clear highlights" })
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.bo[buf].filetype == "lua" then
      vim.keymap.set("n", "s", "<Cmd>luafile %<CR>", { buffer = buf, desc = "Source current Lua file" })
    end
  end
end

-- Use a different listener key than dapui ("debug_single_keys")
-- Open dapui BEFORE we set keys, close dapui BEFORE we restore keys.
-- We set keys AFTER session starts, and restore keys AFTER it ends,
-- so UI open/close doesn’t race with our maps.
dap.listeners.after.event_initialized.debug_single_keys = function()
  set_debug_keymaps()
end

dap.listeners.before.event_terminated.debug_single_keys = function()
  -- Optional: also restore before termination, in case adapters misfire
  restore_normal_keymaps()
end
dap.listeners.before.event_exited.debug_single_keys = function()
  restore_normal_keymaps()
end
dap.listeners.after.event_terminated.debug_single_keys = function()
  restore_normal_keymaps()
end
dap.listeners.after.event_exited.debug_single_keys = function()
  restore_normal_keymaps()
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
    buildTarget = "root",
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
