local metals_config = require("metals").bare_config()

vim.keymap.set("n", "<leader>fm", function() require("telescope").extensions.metals.commands() end , {})
vim.keymap.set("n", "<leader>fmt", function() require("metals.tvp").toggle_tree_view() end , {})

-- Example of settings
metals_config.settings = {
  defaultBspToBuildTool = true, -- So that we can have sbt by default instead of bloop
  showImplicitArguments = true,
  showImplicitConversionsAndClasses = true,
  showInferredType = true,
  superMethodLensesEnabled = true,
  -- useGlobalExecutable = false, -- For when i finally decide to fork metals
  -- metalsBinaryPath = '',
  bloopSbtAlreadyInstalled = true, -- Bloop, ofcourse is not installed, so dont do it !!!
  enableSemanticHighlighting = true,  -- Disable this if there are problems, still experimental
  verboseCompilation = true,
  excludedPackages = { "akka.actor.typed.javadsl", "com.github.swagger.akka.javadsl" },
}

-- *READ THIS*
-- I *highly* recommend setting statusBarProvider to true, however if you do,
-- you *have* to have a setting to display this in your statusline or else
-- you'll not see any messages from metals. There is more info in the help
-- docs about this
metals_config.init_options.statusBarProvider = "on"

-- Example if you are using cmp how to make sure the correct capabilities for snippets are set
metals_config.capabilities = require("cmp_nvim_lsp").default_capabilities()

metals_config.tvp.icons = {
      enabled = true,
}

vim.filetype.add({
	extension = {
		thrift = "thrift",
		sbt = "scala"
	}
})

metals_config.on_attach = function(client, bufnr)
  require("metals").setup_dap()
end

-- Autocmd that will actually be in charge of starting the whole thing
local nvim_metals_group = vim.api.nvim_create_augroup("nvim-metals", { clear = true })

vim.api.nvim_create_autocmd("FileType", {
  -- NOTE: You may or may not want java included here. You will need it if you
  -- want basic Java support but it may also conflict if you are using
  -- something like nvim-jdtls which also works on a java filetype autocmd.
  pattern = { "scala", "sbt", "java" },
  callback = function()
    require("metals").initialize_or_attach(metals_config)
  end,
  group = nvim_metals_group,
})
