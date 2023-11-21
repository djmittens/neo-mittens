-- Example using a list of specs with the default options
vim.g.mapleader = " " -- Make sure to set `mapleader` before lazy so your mappings are correct

require("neo-mittens.lazy") -- Dependencies
if not vim.g.vscode then
	require("neo-mittens.lsp-config") -- LSP shit
	require("neo-mittens.treesitter-config") -- Syntax highlighting shit
	require("neo-mittens.telescope")
	require("neo-mittens.indent-config")
	require("neo-mittens.term-config")
	require("mini.map").setup() -- File minimap
	vim.cmd.colorscheme("gruvbox")
end

require("neo-mittens.settings")
