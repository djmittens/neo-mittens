
-- Example using a list of specs with the default options
vim.g.mapleader = " " -- Make sure to set `mapleader` before lazy so your mappings are correct

require("neo-mittens.lazy") -- Dependencies
require("neo-mittens.lsp-config") -- LSP shit
require("neo-mittens.telescope")
require("neo-mittens.settings")
require("mini.map").setup() -- File minimap
