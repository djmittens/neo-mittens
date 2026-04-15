local M = {}

-- Languages to install from nvim-treesitter registry
local install_languages = { 'c', 'cpp', 'python', 'lua', 'vim', 'vimdoc', 'query', 'javascript', 'html', 'markdown', 'markdown_inline' }

-- Languages to enable treesitter features for (includes locally-installed parsers)
local enable_languages = vim.list_extend({}, install_languages)

-- Only add valk if the parser .so is installed
local valk_parser = vim.fn.stdpath('data') .. '/site/parser/valk.so'
if vim.loop.fs_stat(valk_parser) then
  table.insert(enable_languages, 'valk')
end

function M.setup()
  local treesitter = require('nvim-treesitter')

  -- New API (nvim-treesitter main branch, requires Neovim 0.11+)
  if type(treesitter.install) == 'function' then
    -- install() is a no-op if parsers are already installed
    treesitter.install(install_languages)

    -- Enable treesitter features via FileType autocmd
    vim.api.nvim_create_autocmd('FileType', {
      pattern = enable_languages,
      callback = function()
        vim.treesitter.start()
        vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
      end,
    })
  else
    -- Old API (nvim-treesitter master branch)
    require('nvim-treesitter.configs').setup({
      ensure_installed = install_languages,
      highlight = { enable = true },
      indent = { enable = true },
    })
  end

  -- Register valk parser (installed locally via editors/ plugin)
  if vim.loop.fs_stat(valk_parser) then
    vim.treesitter.language.register('valk', 'valk')
  end
end

return M

