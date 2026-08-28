vim.g.mapleader = " "                     -- Make sure to set `mapleader` before lazy so your mappings are correct

-- Treat ambiguous .h headers as C (not C++). C system headers parse and
-- highlight correctly with the C grammar; the C++ default is wrong for them.
-- Must be set before any .h buffer is opened.
vim.g.c_syntax_for_h = 1

-- [Nvim-Tree] disable netrw at the very start of your init.lua
vim.g.loaded_netrw = 1
vim.g.loaded_netrwPlugin = 1

-- optionally enable 24-bit colour
vim.opt.termguicolors = true

require("neo-mittens.lazy-config")
require("neo-mittens.plugins.treesitter").setup() -- self-contained TS manager (no plugin)
require("neo-mittens.misc-config")
require("neo-mittens.gdb-bridge")
require("neo-mittens.debug").setup()
