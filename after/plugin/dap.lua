local dap, dapui = require("dap"), require("dapui")
dapui.setup()

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

dap.adapters.codelldb = {
  type = 'server',
  port = "${port}",
  executable = {
    -- CHANGE THIS to your path!
    command = vim.fn.expand('$HOME/bin/codelldb/adapter/codelldb'),
    args = {"--port", "${port}"},

    -- On windows you may have to uncomment this:
    -- detached = false,
  }
}

dap.configurations.cpp = {
  {
    name = "Launch file",
    type = "codelldb",
    request = "launch",
    -- program = function()
    --   return vim.fn.input('Path to executable: ', vim.fn.getcwd() .. '/', 'file')
    -- end,
    program = vim.fn.getcwd() .. "/build/bin/hello-opengl",
   cwd = '${workspaceFolder}',
    stopOnEntry = false,
  },
}

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
}
