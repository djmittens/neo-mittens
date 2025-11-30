local M = {}

function M.setup()
  local configs = require('nvim-treesitter.configs')
  configs.setup({
    ensure_installed = { 'c', 'cpp', 'python', 'lua', 'vim', 'vimdoc', 'query', 'javascript', 'html' },
    sync_install = false,
    highlight = { enable = true, additional_vim_regex_highlighting = false },
    indent = { enable = true, disable = { 'yaml' } },
    incremental_selection = {
      enable = true,
      keymaps = { init_selection = 'vn', scope_incremental = 'H', node_incremental = 'K', node_decremental = 'J' },
    },
  })

  require('nvim-treesitter.parsers').get_parser_configs().stacktrace = {
    install_info = {
      url = 'https://github.com/Tudyx/tree-sitter-log/',
      files = { 'src/parser.c' },
      branch = 'main',
    },
    filetype = 'log',
  }
end

return M

