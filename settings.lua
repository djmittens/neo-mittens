
if not vim.g.vscode then
	--- HMM are there actual settings i want to use for vscode then ?
	vim.keymap.set("n", "<C-u>", "<C-u>zz")
	vim.keymap.set("n", "<C-d>", "<C-d>zz")
	vim.g.fileformat="unix"
	vim.o.colorcolumn="80,120"
end

vim.o.cursorline=true
vim.o.relativenumber = true
vim.o.number = true
vim.keymap.set("n", "<leader>y", "\"+y")
vim.keymap.set("n", "<leader>p", "\"+p")

vim.keymap.set("n", "<leader>s", ":w<CR>:so %<CR>")

