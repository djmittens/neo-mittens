-- treesitter-config.lua

local configs = require("nvim-treesitter.configs")
configs.setup {
	-- Add a language of your choice
	ensure_installed = { "c", "lua", "vim", "vimdoc", "query", "elixir", "heex",
		"javascript", "thrift", "html", "scala" },
	sync_install = false,
	-- ignore_install = { "" }, -- List of parsers to ignore installing
	highlight = {
		enable = true, -- false will disable the whole extension
		-- disable = { "" }, -- list of language that will be disabled
		additional_vim_regex_highlighting = false,

	},
	indent = { enable = true, disable = { "yaml" } },
}
