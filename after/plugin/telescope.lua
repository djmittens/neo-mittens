local builtin = require('telescope.builtin')

local symbol_search_opts = {
  symbol_width = 80,
  symbol_type_width = 20,
  show_line = true,
}
vim.keymap.set('n', '<leader>ff', function() builtin.find_files() end, {})
vim.keymap.set('n', '<leader>ffh', function() builtin.find_files({ hidden = true }) end, {})
vim.keymap.set('n', '<leader>fg', function() builtin.live_grep() end, {})
vim.keymap.set('v', '<leader>fg', function() builtin.grep_string() end, {})
vim.keymap.set('n', '<leader>fc', function() builtin.git_commits() end, {})
vim.keymap.set('v', '<leader>fc', function() builtin.git_bcommits_range() end, {})
vim.keymap.set('n', '<leader>fb', function() builtin.buffers() end, {})
vim.keymap.set('n', '<leader>fh', function() builtin.help_tags() end, {})
vim.keymap.set('n', '<leader>fq', function() builtin.quickfix() end, {})
vim.keymap.set('n', '<leader>fqq', function() builtin.quickfixhistory() end, {})
vim.keymap.set('n', '<leader>fj', function() builtin.jumplist() end, {})
vim.keymap.set('n', '<leader>ft', function() builtin.treesitter() end, {})

vim.keymap.set('n', '<leader>d', function() builtin.commands() end, {})
vim.keymap.set('n', '<leader>k', function() builtin.man_pages({ sections = { "ALL" } }) end, {})

--vim.keymap.set('n', '<leader>fm', function() builtin.marks() end, {})
vim.keymap.set('n', '<leader>fr', function() builtin.lsp_references(symbol_search_opts) end, {})
-- vim.keymap.set('n', '<leader>frr', function() builtin.registers() end, {})
vim.keymap.set('n', '<leader>fo', function() builtin.lsp_outgoing_calls(symbol_search_opts) end, {})
vim.keymap.set('n', '<leader>fd', function() builtin.lsp_definitions(symbol_search_opts) end, {})
vim.keymap.set('n', '<leader>fs', function() builtin.lsp_document_symbols(symbol_search_opts) end, {})
vim.keymap.set('n', '<leader>fws', function() builtin.lsp_dynamic_workspace_symbols(symbol_search_opts) end, {})
-- vim.keymap.set('n', '<leader>fws', function() builtin.lsp_workspace_symbols(symbol_search_opts) end, {})
