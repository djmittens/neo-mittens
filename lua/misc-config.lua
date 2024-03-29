vim.cmd.colorscheme("gruvbox")

--- HMM are there actual settings i want to use for vscode then ?
vim.keymap.set("n", "<C-u>", "<C-u>zz")
vim.keymap.set("n", "<C-d>", "<C-d>zz")
vim.keymap.set("n", "<C-]>", "<C-]>zz")
vim.keymap.set("n", "<C-[>", "<C-[>zz")
vim.keymap.set("n", "<C-o>", "<C-o>zz")
vim.keymap.set("n", "<C-i>", "<C-i>zz")
vim.keymap.set("n", "n", "nzz")
vim.keymap.set("n", "N", "Nzz")
vim.keymap.set("n", "<leader>ct", ":bd term<C-A><CR>")
vim.keymap.set("n", "<M-o>", ":ClangdSwitchSourceHeader<CR>")
vim.keymap.set("v", "q", ":norm @q<CR>")
vim.keymap.set("n", "<leader>e", ":Explore<CR>")
vim.keymap.set("n", "<leader>E", ":Sex!<CR>")
vim.keymap.set("n", "<leader>m", ":marks<CR>")
vim.keymap.set({ 'n', 'v' }, "<leader>y", "\"+y")
vim.keymap.set({ 'n', 'v' }, "<leader>p", "\"+p")
vim.keymap.set("n", "<leader>s", ":w<CR>:so %<CR>")
vim.keymap.set("", "<leader>w", ":w<CR>")
vim.keymap.set("", "<leader>x", ":x<CR>")
vim.keymap.set("", "<leader>n", ":noh<CR>")

-- Copy relative file path
vim.api.nvim_create_user_command("CopyRelPath", "call setreg('+', expand('%'))", {})
vim.keymap.set("n", "<leader>yp", ":CopyRelPath<CR>")

vim.o.colorcolumn = "80,120"
vim.o.cursorline = true
vim.o.number = true

-- indentation settings, weird stuff huh
vim.o.smartindent = true
vim.o.autoindent = true
vim.o.expandtab = true
vim.o.tabstop = 2
vim.o.shiftwidth = 2
vim.o.timeoutlen = 350

vim.keymap.set("n", "<leader>o", "o<Esc>")
vim.keymap.set("n", "<leader>O", "O<Esc>")

-- tree style listings by default
vim.g.netrw_liststyle = 0
vim.o.splitright = true
vim.o.ignorecase = true
vim.o.smartcase = true
-- vim.o.signcolumn = 'number'

vim.o.wrap = false

-- So i dont kill my wrist
vim.keymap.set("i", "jj", "<ESC>")

-- This makes shit transparent so i can see the waifu's in the background
-- :hi normal guibg=NONE
vim.cmd.highlight({ "normal", "guibg=NONE" })
vim.cmd.highlight({ "SignColumn", "guibg=NONE" }) -- or you can also set it to darkgrey, for now tho.... its pretty good like this.

-- Relative line number settings
vim.o.relativenumber = true
vim.api.nvim_create_autocmd({ 'InsertEnter' }, {
  pattern = { "*.*" },
  command = "set nornu",
})
vim.api.nvim_create_autocmd({ 'InsertLeavePre' }, {
  pattern = { "*.*" },
  command = "set rnu",
})


-- Function to get the current git branch name
local function get_git_branch()
  return vim.fn.systemlist('git rev-parse --abbrev-ref HEAD')[1]
end

-- Function to insert TODO with the current git branch name
local function insert_todo()
  -- Construct TODO text with the git branch name
  -- Insert TODO text below the cursor position
  vim.api.nvim_put({ 'TODO(' .. get_git_branch() .. '): ' }, '', true, true)
end

vim.keymap.set({'i', 'n'}, '<M-t>', function() insert_todo() end, { noremap = true, silent = true })
