if not vim.g.vscode then
	--- HMM are there actual settings i want to use for vscode then ?
	vim.keymap.set("n", "<C-u>", "<C-u>zz")
	vim.keymap.set("n", "<C-d>", "<C-d>zz")
	vim.keymap.set("n", "<C-]>", "<C-]>zz")
	vim.keymap.set("n", "<C-[>", "<C-[>zz")
	vim.keymap.set("n", "<C-o>", "<C-o>zz")
	vim.keymap.set("n", "<C-i>", "<C-i>zz")
	vim.keymap.set("n", "n", "nzz")
	vim.keymap.set("n", "N", "Nzz")
	vim.keymap.set("n", "<leader>e", ":Explore<CR>")
	vim.keymap.set("n", "<leader>ct", ":bd term<C-A><CR>")

	vim.keymap.set("n", "<M-o>", ":ClangdSwitchSourceHeader<CR>")
	vim.keymap.set("v", "q", ":norm @q<CR>")

	vim.keymap.set("n", "<leader>E", ":Sex!<CR>")
	vim.keymap.set("n", "<leader>m", ":marks<CR>")
	vim.g.fileformat = "unix"
	vim.o.colorcolumn = "80,120"
	vim.o.cursorline = true
	vim.o.relativenumber = true
	vim.o.number = true
end

vim.keymap.set({ 'n', 'v' }, "<leader>y", "\"+y")
vim.keymap.set({ 'n', 'v' }, "<leader>p", "\"+p")
vim.keymap.set("n", "<leader>s", ":w<CR>:so %<CR>")

