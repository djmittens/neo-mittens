
if not vim.g.vscode then
	--- HMM are there actual settings i want to use for vscode then ?
	vim.keymap.set("n", "<C-u>", "<C-u>zz")
	vim.keymap.set("n", "<C-d>", "<C-d>zz")
	vim.o.number = true
	vim.o.relativenumber = true
	vim.g.fileformat="unix"
	vim.o.cursorline=true
	vim.o.colorcolumn="80,120"
end

vim.keymap.set("n", "<leader>y", "\"+y")
vim.keymap.set("n", "<leader>p", "\"+p")
