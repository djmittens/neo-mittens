local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable", -- latest stable release
    lazypath,
  })
end


vim.opt.rtp:prepend(lazypath)
require("lazy").setup({
  -- LSP
  { "folke/neodev.nvim" },
  {
    'VonHeikemen/lsp-zero.nvim',
    branch = 'v2.x',
    dependencies = {
      -- LSP Support
      { 'neovim/nvim-lspconfig' },
      {
        'williamboman/mason.nvim',
        build = function()
          pcall(vim.cmd, 'MasonUpdate')
        end,
      },
      { 'williamboman/mason-lspconfig.nvim' },

      -- Autocompletion
      { 'hrsh7th/nvim-cmp' },
      { 'hrsh7th/cmp-nvim-lsp' },
      { 'L3MON4D3/LuaSnip' },
    }
  },
  { 'scalameta/nvim-metals',    dependencies = { "nvim-lua/plenary.nvim" } },
  {
    "nvim-treesitter/nvim-treesitter",
    build = ":TSUpdate",
  },
  -- Session Management
  { 'rmagatti/auto-session' },
  {
    'nvim-telescope/telescope.nvim',
    -- tag = '0.1.2',
    dependencies = { 'nvim-lua/plenary.nvim' }
  },
  -- Random bullshit
  { "folke/which-key.nvim" },
  { "mbbill/undotree" },
  { 'dstein64/nvim-scrollview' },
  { "lukas-reineke/indent-blankline.nvim" },
  { "ellisonleao/gruvbox.nvim", priority = 1000 },
  -- Git Support
  { "lewis6991/gitsigns.nvim" },
  { 'tpope/vim-fugitive' },
  { 'tpope/vim-rhubarb' },
  -- Debugger Support
  { 'mfussenegger/nvim-dap' },
  { 'rcarriga/nvim-dap-ui' },
})
