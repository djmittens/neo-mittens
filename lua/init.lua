vim.g.mapleader = " "                     -- Make sure to set `mapleader` before lazy so your mappings are correct

-- [Nvim-Tree] disable netrw at the very start of your init.lua
vim.g.loaded_netrw = 1
vim.g.loaded_netrwPlugin = 1

-- optionally enable 24-bit colour
vim.opt.termguicolors = true

require("neo-mittens.lazy-config")
require("neo-mittens.misc-config")
