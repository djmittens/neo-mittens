local M = {}

-- Languages to install and enable treesitter for
local languages = { 'c', 'cpp', 'python', 'lua', 'vim', 'vimdoc', 'query', 'javascript', 'html', 'markdown', 'markdown_inline' }

function M.setup()
  local treesitter = require('nvim-treesitter')

  -- New API (nvim-treesitter main branch, requires Neovim 0.11+)
  if type(treesitter.install) == 'function' then
    -- install() is a no-op if parsers are already installed
    treesitter.install(languages)

    -- Enable treesitter features via FileType autocmd
    vim.api.nvim_create_autocmd('FileType', {
      pattern = languages,
      callback = function()
        vim.treesitter.start()
        vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
      end,
    })
  else
    -- Old API (nvim-treesitter master branch)
    require('nvim-treesitter.configs').setup({
      ensure_installed = languages,
      highlight = { enable = true },
      indent = { enable = true },
    })
  end
end

return M

