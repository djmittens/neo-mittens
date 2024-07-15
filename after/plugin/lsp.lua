-- lets do some lsp shit
local lsp = require('lsp-zero')
local luasnip = require('luasnip')

-- lsp.preset("recomdended")
lsp.preset({})

lsp.ensure_installed({
  'lua_ls',
  'clangd',
  -- 'tsserver',
  -- 'eslint',
  --'sumneko_lua',
  --'rust_analyzer',
})

local cmp = require('cmp')
local cmp_action = require('lsp-zero').cmp_action()

local kind_icons = {
  Text = "",
  Method = "󰆧",
  Function = "󰊕",
  Constructor = "",
  Field = "󰇽",
  Variable = "󰂡",
  Class = "󰠱",
  Interface = "",
  Module = "",
  Property = "󰜢",
  Unit = "",
  Value = "󰎠",
  Enum = "",
  Keyword = "󰌋",
  Snippet = "",
  Color = "󰏘",
  File = "󰈙",
  Reference = "",
  Folder = "󰉋",
  EnumMember = "",
  Constant = "󰏿",
  Struct = "",
  Event = "",
  Operator = "󰆕",
  TypeParameter = "󰅲",
}

local cmp_select = { behavior = cmp.SelectBehavior.Select }

lsp.set_preferences({
  sign_icons = {}
})

cmp.setup({
  -- For some reason this config only is available here and stuff, not part of lsp setup
  window = {
    documentation = cmp.config.window.bordered(),
    completion = cmp.config.window.bordered(),
  },
})

lsp.setup_nvim_cmp({
  completion = {
    keyword_length = 1
  },
  --mapping = cmp_mappings
  snippet = {
    expand = function(args)
      -- vim.fn["vsnip#anonymous"](args.body)     -- For `vsnip` users.
      luasnip.lsp_expand(args.body) -- For `luasnip` users.
    end,
  },
  sources = {
    { name = 'luasnip' }, -- For luasnip users.
    { name = 'nvim_lsp' },
    { name = 'nvim_lua' },
  },
  mapping = {
    ['<C-p>'] = cmp.mapping.select_prev_item(cmp_select),
    ['<C-n>'] = cmp.mapping.select_next_item(cmp_select),
    ['<C-e>'] = cmp.mapping.abort(),
    ['<C-y>'] = cmp.mapping.confirm({ select = true }),
    ['<CR>'] = cmp.mapping.confirm({select = false}),
    ['<C-f>'] = cmp.mapping(function(fallback)
      if cmp.visible() then
        cmp.select_next_item({
          behavior = cmp.SelectBehavior.Select,
          count = 10
        })
      elseif luasnip.jumpable(1) then
        luasnip.jump(1)
      else
        fallback()
      end
    end, { 'i', 's' }),
    ['<C-b>'] = cmp.mapping(function(fallback)
      if cmp.visible() then
        cmp.select_next_item({
          behavior = cmp.SelectBehavior.Select,
          count = -10
        })
      elseif luasnip.jumpable(-1) then
        luasnip.jump(-1)
      else
        fallback()
      end
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
      if cmp.visible() then
        cmp.select_prev_item(cmp_select)
      else
        fallback()
      end
    end, { 'i', 's' }),
  },
  formatting = {
    fields = { 'abbr', 'kind', 'menu' },
    expandable_indicator = true,
    format = function(entry, vim_item)
      -- Kind icons
      vim_item.kind = string.format('%s %s', kind_icons[vim_item.kind], vim_item.kind) -- This concatenates the icons with the name of the item kind
      -- Source
      vim_item.menu = ({
        buffer = "[Buffer]",
        nvim_lsp = "[LSP]",
        luasnip = "[LuaSnipz]",
        nvim_lua = "[Lua]",
        latex_symbols = "[LaTeX]",
      })[entry.source.name]
      return vim_item
    end
  },
})

lsp.on_attach(function(client, bufnr)
  lsp.default_keymaps({ buffer = bufnr })
  local opts = { buffer = bufnr, remap = false }

  vim.keymap.set("n", "gd", function()
    vim.lsp.buf.definition({ reuse_win = true })
    vim.cmd("norm zz")
  end, opts)
  vim.keymap.set("n", "K", function() vim.lsp.buf.hover() end, opts)
  vim.keymap.set("n", "<leader>vws", function() vim.lsp.buf.workspace_symbol() end, opts)
  vim.keymap.set("n", "<leader>vi", function() vim.lsp.buf.implementation() end, opts)
  vim.keymap.set("n", "<leader>vd", function() vim.diagnostic.open_float() end, opts)
  vim.keymap.set("n", "[d", function()
    vim.diagnostic.goto_next({ float = false })
    vim.cmd("norm zz")
  end, opts)
  vim.keymap.set("n", "]d", function()
    vim.diagnostic.goto_prev({ float = false })
    vim.cmd("norm zz")
  end, opts)
  vim.keymap.set({ "n", "v" }, "<leader>vca", function() vim.lsp.buf.code_action() end, opts)
  vim.keymap.set("n", "<leader>vrr", function() vim.lsp.buf.references() end, opts)
  -- vim.keymap.set("n", "<leader>vrn", function() vim.lsp.buf.rename() end, opts)
  vim.keymap.set("n", "<F2>", function() vim.lsp.buf.rename() end, opts)
  vim.keymap.set("i", "<C-h>", function() vim.lsp.buf.signature_help() end, opts)

  --
  -- - [x] (LSP)   Format source on <A-S-F>
  vim.keymap.set({ "n", "v" }, "<A-S-f>", ":LspZeroFormat<CR>")
  --
end)

require('lspconfig').lua_ls.setup(lsp.nvim_lua_ls())
lsp.setup()
