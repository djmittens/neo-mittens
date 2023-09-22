-- lets do some lsp shit
local lsp = require('lsp-zero')
-- lsp.preset("recommdended")
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

cmp.setup({
	sources = {
		{ name = 'nvim_lsp' },
		{ name = 'nvim_lua' },
	},
	mapping = {
		['<C-f>'] = cmp_action.luasnip_jump_forward(),
		['<C-b>'] = cmp_action.luasnip_jump_backward(),
	}
})

local cmp_select = { behavior = cmp.SelectBehavior.Select }
local cmp_mappings = lsp.defaults.cmp_mappings({
	['<C-p>'] = cmp.mapping.select_prev_item(cmp_select),
	['<C-n>'] = cmp.mapping.select_next_item(cmp_select),
	['<C-y>'] = cmp.mapping.confirm({ select = true }),
	['<C-Space>'] = cmp.mapping.complete(),
})

lsp.set_preferences({
	sign_icons = {}
})

lsp.setup_nvim_cmp({
	mapping = cmp_mappings
})

lsp.on_attach(function(client, bufnr)
	lsp.default_keymaps({ buffer = bufnr })
	local opts = { buffer = bufnr, remap = false }

	vim.keymap.set("n", "gd", function()
		vim.lsp.buf.definition({ reuse_win = false })
		vim.cmd("norm zz")
	end, opts)
	vim.keymap.set("n", "K", function() vim.lsp.buf.hover() end, opts)
	vim.keymap.set("n", "<leader>vws", function() vim.lsp.buf.workspace_symbol() end, opts)
	vim.keymap.set("n", "<leader>vd", function() vim.diagnostic.open_float() end, opts)
	vim.keymap.set("n", "[d", function()
		vim.diagnostic.goto_next({ float = false })
		vim.cmd("norm zz")
	end, opts)
	vim.keymap.set("n", "]d", function()
		vim.diagnostic.goto_prev({ float = false })
		vim.cmd("norm zz")
	end, opts)
	vim.keymap.set("n", "<leader>vca", function() vim.lsp.buf.code_action() end, opts)
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
