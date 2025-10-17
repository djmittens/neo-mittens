local M = {}

function M.on_lsp_attach()
  vim.api.nvim_create_autocmd('LspAttach', {
    desc = 'LSP actions',
    callback = function(event)
      local opts = { buffer = event.buf }
      vim.keymap.set('n', 'K', function() require('pretty_hover').hover() end, opts)
      vim.keymap.set('n', 'gd', function() vim.lsp.buf.definition() end, opts)
      vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, opts)
      vim.keymap.set('n', 'gi', function() vim.lsp.buf.implementation() end, opts)
      vim.keymap.set('n', 'go', function() vim.lsp.buf.type_definition() end, opts)
      vim.keymap.set('n', 'gr', function() vim.lsp.buf.references() end, opts)
      vim.keymap.set('n', 'gs', function() vim.lsp.buf.signature_help() end, opts)
      vim.keymap.set('n', '<F2>', function() vim.lsp.buf.rename() end, opts)
      vim.keymap.set({ 'n', 'x' }, '<F3>', function() vim.lsp.buf.format({ async = true }) end, opts)
      vim.keymap.set('n', '<F4>', function() vim.lsp.buf.code_action() end, opts)
      vim.keymap.set({ 'n', 'v' }, '<leader>va', function() vim.lsp.buf.code_action({ apply = true }) end, opts)
      vim.keymap.set('n', '[d', function()
        vim.diagnostic.jump({ float = true, _highest = true, count = -1 })
        vim.cmd('norm zz')
      end, opts)
      vim.keymap.set('n', ']d', function()
        vim.diagnostic.jump({ float = true, _highest = true, count = 1 })
        vim.cmd('norm zz')
      end, opts)
      vim.keymap.set({ 'n', 'v' }, '<A-S-f>', function() vim.lsp.buf.format() end, opts)
      vim.keymap.set('n', '<leader>vs', function() vim.lsp.buf.workspace_symbol() end, opts)
      vim.keymap.set('n', '<leader>vts', function() vim.lsp.buf.typehierarchy('subtypes') end, opts)
      vim.keymap.set('n', '<leader>vtr', function() vim.lsp.buf.typehierarchy('supertypes') end, opts)
      vim.keymap.set('n', '<leader>vd', function() vim.diagnostic.open_float() end, opts)
    end,
  })
end

function M.mason_setup()
  local mason_lspconfig = require('mason-lspconfig')
  for _, server in ipairs(mason_lspconfig.get_installed_servers()) do
    if server == 'clangd' then
      vim.lsp.config('clangd', {
        cmd = { 'clangd', '--clang-tidy', '--fallback-style=Google', '--background-index', '--completion-style=detailed', '--header-insertion=iwyu' },
        init_options = { clangdFileStatus = true },
      })
    end
    vim.lsp.enable(server)
  end
end

return M

