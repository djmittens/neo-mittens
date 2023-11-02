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
	vim.keymap.set("n", "<leader>e", ":Hex<CR>")
	vim.keymap.set("n", "<leader>E", ":Sex!<CR>")
	vim.keymap.set("n", "<leader>m", ":marks<CR>")
	-- vim.api.nvim_create_user_command("CopyRelPath", "call setreg('+', expand('%'))", {}) 
	-- Copy relative file path
	vim.keymap.set("n", "<leader>fy", ":call setreg('+', expand('%'))<CR>")
	vim.g.fileformat = "unix"
	vim.o.colorcolumn = "80,120"
	vim.o.cursorline = true
	vim.o.relativenumber = true
	vim.o.number = true
	vim.g.netrw_liststyle= 3 -- tree style listings by default
end

vim.keymap.set({ 'n', 'v' }, "<leader>y", "\"+y")
vim.keymap.set({ 'n', 'v' }, "<leader>p", "\"+p")
vim.keymap.set("n", "<leader>s", ":w<CR>:so %<CR>")
