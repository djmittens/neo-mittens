local M = {}

-- Languages to install and enable treesitter for
local languages = { 'c', 'cpp', 'python', 'lua', 'vim', 'vimdoc', 'query', 'javascript', 'html', 'markdown', 'markdown_inline' }

function M.setup()
  local treesitter = require('nvim-treesitter')
  treesitter.setup()

  -- Install parsers (async, won't block startup)
  local install = require('nvim-treesitter.install')
  install.ensure_installed(languages)

  -- Enable treesitter features via FileType autocmd (new API)
  vim.api.nvim_create_autocmd('FileType', {
    pattern = languages,
    callback = function()
      -- Syntax highlighting (built-in Neovim)
      vim.treesitter.start()
      -- Indentation (nvim-treesitter)
      vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
    end,
  })
end

return M

