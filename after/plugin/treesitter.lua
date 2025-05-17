-- treesitter-config.lua
local configs = require("nvim-treesitter.configs")

configs.setup {
  -- Add a language of your choice
  ensure_installed = {
    "c", "cpp", "python",
    "lua", "vim", "vimdoc", "query",
    "javascript", "html", },
  sync_install = false,
  -- ignore_install = { "" }, -- List of parsers to ignore installing
  highlight = {
    enable = true, -- false will disable the whole extension
    -- disable = { "" }, -- list of language that will be disabled
    additional_vim_regex_highlighting = false,

  },
  indent = { enable = true, disable = { "yaml" } },
  incremental_selection = {
    enable = true,
    keymaps = {
      init_selection    = "vn", -- set to `false` to disable one of the mappings
      scope_incremental = "H",
      --scope_decremental = "L",
      node_incremental  = "K",
      node_decremental  = "J",
    },
  },
}

require('nvim-treesitter.parsers').get_parser_configs().stacktrace = {
  install_info = {
    url = "https://github.com/Tudyx/tree-sitter-log/",
    files = {"src/parser.c"},
    branch = "main"
  },
  filetype = "log"
}
