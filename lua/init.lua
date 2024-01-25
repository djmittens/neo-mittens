vim.g.mapleader = " "                     -- Make sure to set `mapleader` before lazy so your mappings are correct

require("neo-mittens.lazy-config")
require("neo-mittens.lsp-config")
require("neo-mittens.treesitter-config")
require("neo-mittens.telescope-config")
require("neo-mittens.indent-config")
require("neo-mittens.term-config")
require("neo-mittens.gitsigns-config")
require("neo-mittens.scrollview-config")
require("neo-mittens.metals-config")
require("neo-mittens.dap-cpp")

require("neo-mittens.misc-config")

