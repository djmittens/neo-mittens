-- C indentation. Uses Vim's dedicated `cindent` engine (understands braces,
-- labels, switch/case, continuation lines) instead of the crude global
-- `smartindent`, which we disabled in misc-config.lua.
--
-- Buffer-local so it doesn't affect other filetypes (which use the global
-- shiftwidth=2). Switch expandtab=false / adjust widths if your C style uses
-- real tabs.
vim.bo.cindent = true
vim.bo.expandtab = true
vim.bo.shiftwidth = 4
vim.bo.softtabstop = 4
vim.bo.tabstop = 4
