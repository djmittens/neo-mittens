local M = {}

function M.setup()
  local cmp = require('cmp')
  local luasnip = require('luasnip')

  local kind_icons = {
    Text = '', Method = '󰆧', Function = '󰊕', Constructor = '', Field = '󰇽',
    Variable = '󰂡', Class = '󰠱', Interface = '', Module = '', Property = '󰜢',
    Unit = '', Value = '󰎠', Enum = '', Keyword = '󰌋', Snippet = '',
    Color = '󰏘', File = '󰈙', Reference = '', Folder = '󰉋', EnumMember = '',
    Constant = '󰏿', Struct = '', Event = '', Operator = '󰆕', TypeParameter = '󰅲',
  }

  local cmp_select = { behavior = cmp.SelectBehavior.Select }

  local has_lazydev = pcall(require, 'lazydev')

  cmp.setup({
    window = {
      documentation = cmp.config.window.bordered(),
      completion = cmp.config.window.bordered(),
    },
    completion = { keyword_length = 1, autocomplete = false },
    preselect = cmp.PreselectMode.Item,
    snippet = { expand = function(args) luasnip.lsp_expand(args.body) end },
    sources = (function()
      local s = {
        { name = 'luasnip' },
        { name = 'nvim_lsp' },
        { name = 'nvim_lua' },
      }
      if has_lazydev then
        table.insert(s, 1, { name = 'lazydev', group_index = 0 })
      end
      return s
    end)(),
    mapping = {
      ['<C-p>'] = cmp.mapping.select_prev_item(cmp_select),
      ['<C-n>'] = cmp.mapping.select_next_item(cmp_select),
      ['<C-e>'] = cmp.mapping.abort(),
      ['<C-s>'] = cmp.mapping.complete({ config = { sources = { { name = 'luasnip' } } } }),
      ['<C-l>'] = cmp.mapping.complete({ config = { sources = { { name = 'nvim_lsp' }, { name = 'buffer' } } } }),
      ['<C-y>'] = cmp.mapping.confirm({ select = true }),
      ['<CR>'] = cmp.mapping.confirm({ select = false }),
      ['<C-f>'] = cmp.mapping(function(fallback)
        if luasnip.jumpable(1) then luasnip.jump(1) else fallback() end
      end, { 'i', 's' }),
      ['<C-b>'] = cmp.mapping(function(fallback)
        if luasnip.jumpable(-1) then luasnip.jump(-1) else fallback() end
      end, { 'i', 's' }),
      ['<C-u>'] = cmp.mapping.scroll_docs(-4),
      ['<C-d>'] = cmp.mapping.scroll_docs(4),
      ['<Tab>'] = cmp.mapping(function(fallback)
        local col = vim.fn.col('.') - 1
        if cmp.visible() then
          cmp.select_next_item(cmp_select)
        elseif col == 0 or vim.fn.getline('.'):sub(col, col):match('%s') then
          fallback()
        else
          cmp.complete()
        end
      end, { 'i', 's' }),
      ['<S-Tab>'] = cmp.mapping(function(fallback)
        if cmp.visible() then cmp.select_prev_item(cmp_select) else fallback() end
      end, { 'i', 's' }),
    },
    formatting = {
      fields = { 'kind', 'abbr', 'menu' },
      expandable_indicator = true,
      format = function(entry, vim_item)
        vim_item.kind = string.format('%s %s', kind_icons[vim_item.kind], vim_item.kind)
        vim_item.menu = ({ buffer = '[Buffer]', nvim_lsp = '[LSP]', luasnip = '[LuaSnipz]', nvim_lua = '[Lua]', latex_symbols = '[LaTeX]' })[entry.source.name]
        return vim_item
      end,
    },
  })
end

return M
