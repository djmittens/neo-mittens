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

-- Navigating quickfix list n stuff
vim.keymap.set("", "]q", ":cn<CR>")
vim.keymap.set("", "[q", ":cp<CR>")

-- Check the current files changes against whats on the file system, before storing
vim.api.nvim_create_user_command("Fdiff", "w !diff % -", {})

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
vim.o.timeoutlen = 650

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
vim.cmd.highlight({ "SignColumn", "guibg=NONE" })  -- or you can also set it to darkgrey, for now tho.... its pretty good like this.
vim.cmd.highlight({ "FloatBorder", "guibg=NONE" }) -- this is a hack for some themes, for telescope and so on

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

vim.keymap.set({ 'i', 'n' }, '<M-t>', function() insert_todo() end, { noremap = true, silent = true })

vim.o.grepprg = 'rg --vimgrep --hidden --glob "!.git"'

vim.filetype.add({
  extension = {
    thrift = "thrift",
    sbt = "scala",
    tf = "hcl",
  }
})

-- Highlighting lines in the editor, this is useful for marking up big files, or code reviews
--

local hl_groups = {
  LineHighlightPurple = "purple",
  LineHighlightYellow = "yellow",
  LineHighlightGreen = "green",
}

for g, c in pairs(hl_groups) do
  vim.api.nvim_set_hl(0, g, {
    ctermbg = "green",
    background = c,
  })
end


local function highlight_lines(group)
  if vim.fn.mode() == 'v' or vim.fn.mode() == 'V' then
    vim.cmd(vim.api.nvim_replace_termcodes("normal! <esc>", true, false, true)) -- hack to quit visual mode. probably better way of doing this
    -- Wish this worked but it always higlights the last selection when it changes
    -- its hilarious, but not what i need
    -- vim.fn.matchadd(group, "\\%>'<\\_.*\\%'>")
    vim.fn.matchadd(group, "\\%>" .. (vim.fn.line("'<") - 1 ) .. "l\\%<" .. (vim.fn.line("'>") + 1) .. "l")
  else
    vim.fn.matchadd(group, '\\%' .. vim.fn.line("v") .. 'l')
  end
end


vim.keymap.set({ 'v', 'n' }, '<leader>l', function() highlight_lines("LineHighlightGreen") end,
  { noremap = true, silent = false })
vim.keymap.set({ 'v', 'n' }, '<leader>lg', function() highlight_lines("LineHighlightPurple") end,
  { noremap = true, silent = false })
vim.keymap.set({ 'v', 'n' }, '<leader>ly', function() highlight_lines("LineHighlightYellow") end,
  { noremap = true, silent = false })
vim.keymap.set({ 'n' }, '<leader>c', function() vim.fn.clearmatches() end, { noremap = true, silent = true })
