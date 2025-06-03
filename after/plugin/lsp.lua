-- lets do some lsp shit
-- local lsp = require('lsp-zero')
local lspconfig = require('lspconfig')


-- lsp.preset("recomdended")
vim.opt.signcolumn = 'yes'

-- Add cmp_nvim_lsp capabilities settings to lspconfig
-- This should be executed before you configure any language server
local lspconfig_defaults = lspconfig.util.default_config
lspconfig_defaults.capabilities = vim.tbl_deep_extend(
  'force',
  lspconfig_defaults.capabilities,
  require('cmp_nvim_lsp').default_capabilities()
)


local mason_lspconfig = require('mason-lspconfig')

-- Configure handlers after Mason installs them
for _, server in ipairs(mason_lspconfig.get_installed_servers()) do
  if server == "clangd" then
    lspconfig.clangd.setup({
      cmd = {
        "clangd",
        "--clang-tidy",
        "--fallback-style=Google",
        "--background-index",
        "--completion-style=detailed",
        "--header-insertion=iwyu",
      },
      init_options = {
        clangdFileStatus = true,
      },
    })
  else
    lspconfig[server].setup({})
  end
end


-- This is where you enable features that only work
-- if there is a language server active in the file
vim.api.nvim_create_autocmd('LspAttach', {
  desc = 'LSP actions',
  callback = function(event)
    local opts = { buffer = event.buf }

    vim.keymap.set('n', 'K', function() require("pretty_hover").hover() end, opts)
    vim.keymap.set('n', 'gd', function() vim.lsp.buf.definition() end, opts)
    vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, opts)
    vim.keymap.set('n', 'gi', function() vim.lsp.buf.implementation() end, opts)
    vim.keymap.set('n', 'go', function() vim.lsp.buf.type_definition() end, opts)
    vim.keymap.set('n', 'gr', function() vim.lsp.buf.references() end, opts)
    vim.keymap.set('n', 'gs', function() vim.lsp.buf.signature_help() end, opts)
    vim.keymap.set('n', '<F2>', function() vim.lsp.buf.rename() end, opts)
    vim.keymap.set({ 'n', 'x' }, '<F3>', function() vim.lsp.buf.format({ async = true }) end, opts)
    vim.keymap.set('n', '<F4>', function() vim.lsp.buf.code_action() end, opts)
    vim.keymap.set({ "n", "v" }, "<leader>va", function() vim.lsp.buf.code_action({ apply = true }) end, opts)

    -- diagnostics hotkeys
    vim.keymap.set("n", "[d", function(k)
      vim.diagnostic.jump({
        float = true,
        _highest = true,
        count = -1,
      })
      vim.cmd("norm zz")
    end, opts)
    vim.keymap.set("n", "]d", function()
      -- vim.diagnostic.goto_prev({ float = false })
      vim.diagnostic.jump({
        float = true,
        _highest = true,
        count = 1,
      })
      vim.cmd("norm zz")
    end, opts)
    -- - [x] (LSP)   Format source on <A-S-F>
    vim.keymap.set({ "n", "v" }, "<A-S-f>", function() vim.lsp.buf.format() end, opts)
    -- workspace symbols
    vim.keymap.set("n", "<leader>vs", function() vim.lsp.buf.workspace_symbol() end, opts)
    -- type navigations or something do i even need these?
    vim.keymap.set("n", "<leader>vts", function() vim.lsp.buf.typehierarchy("subtypes") end, opts)
    vim.keymap.set("n", "<leader>vtr", function() vim.lsp.buf.typehierarchy("supertypes") end, opts)
    vim.keymap.set("n", "<leader>vd", function() vim.diagnostic.open_float() end, opts)
  end,
})

local cmp = require('cmp')

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

-- lsp.set_preferences({
--   sign_icons = {}
-- })

local luasnip = require('luasnip')
cmp.setup({
  -- For some reason this config only is available here and stuff, not part of lsp setup
  window = {
    documentation = cmp.config.window.bordered(),
    completion = cmp.config.window.bordered(),
  },
  completion = {
    keyword_length = 1,
    autocomplete = false, -- basically only complete manually
  },
  preselect = cmp.PreselectMode.Item,
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

    ['<C-s>'] = cmp.mapping.complete({
      config = {
        sources = {
          { name = 'luasnip' }
        }
      }
    }),
    ['<C-l>'] = cmp.mapping.complete({
      config = {
        sources = {
          { name = 'nvim_lsp' },
          { name = 'buffer' }
        }
      }
    }),

    ['<C-y>'] = cmp.mapping.confirm({ select = true }),
    ['<CR>'] = cmp.mapping.confirm({ select = false }),

    ['<C-f>'] = cmp.mapping(function(fallback)
      if luasnip.jumpable(1) then
        luasnip.jump(1)
      else
        fallback()
      end
    end, { 'i', 's' }),
    ['<C-b>'] = cmp.mapping(function(fallback)
      if luasnip.jumpable(-1) then
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
    fields = { 'kind', 'abbr', 'menu' },
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
