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
  {
    "folke/lazydev.nvim",
    ft = "lua", -- only load on lua files
    opts = {
      library = {
        -- See the configuration section for more details
        -- Load luvit types when the `vim.uv` word is found
        { path = "luvit-meta/library", words = { "vim%.uv" } },
      },
    },
  },
  { "Bilal2453/luvit-meta", lazy = true }, -- optional `vim.uv` typings
  {                                        -- optional completion source for require statements and module annotations
    "hrsh7th/nvim-cmp",
    opts = function(_, opts)
      opts.sources = opts.sources or {}
      table.insert(opts.sources, {
        name = "lazydev",
        group_index = 0, -- set group index to 0 to skip loading LuaLS completions
      })
    end,
  },
  { 'neovim/nvim-lspconfig' },
  { 'hrsh7th/nvim-cmp' },
  { 'hrsh7th/cmp-nvim-lsp' },
  {
    'L3MON4D3/LuaSnip',
    dependencies = { 'rafamadriz/friendly-snippets' },
    config = function()
      require('luasnip.loaders.from_vscode').lazy_load({})
    end

  },
  {
    'williamboman/mason.nvim',
    build = function()
      pcall(vim.cmd, 'MasonUpdate')
    end,
  },
  { 'williamboman/mason-lspconfig.nvim' },
  { 'saadparwaiz1/cmp_luasnip', },
  { 'scalameta/nvim-metals',            dependencies = { "nvim-lua/plenary.nvim" } },
  {
    "nvim-treesitter/nvim-treesitter",
    build = ":TSUpdate",
  },
  {
    'nvim-telescope/telescope.nvim',
    -- tag = '0.1.2',
    dependencies = { 'nvim-lua/plenary.nvim', { 'nvim-telescope/telescope-fzf-native.nvim', build = 'cmake -S. -Bbuild -DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release' } },
    config = function()
      require('telescope').setup {
        defaults = {
          layout_strategy = 'flex',
          layout_config = { height = 0.95 },
          vimgrep_arguments = {
            "rga",
            "--color=never",
            "--no-heading",
            "--line-number",
            "--column",
            "--smart-case",
            "--hidden", -- Include hidden files
            "--trim",
            --            "--glob", "*.java", -- Adjust glob for file types
          },
        },
        extensions = {
          fzf = { -- Optional FZF extension for faster sorting
            fuzzy = true,
            override_generic_sorter = true,
            override_file_sorter = true,
            case_mode = "smart_case",
          },
        },
      }
      require('telescope').load_extension("fzf") -- Optional: load fzf for better performance
    end,
  },
  -- Random bullshit
  -- { "folke/which-key.nvim" }, -- Havent needed this in a long time
  { "mbbill/undotree" },                                     -- Havent figured out how to use this effectively yet. Maybe not worth having it around
  { 'dstein64/nvim-scrollview' },                            -- Code map on the right , might be useful for marks and errors
  { "lukas-reineke/indent-blankline.nvim" },                 -- rainbow guides for nesting. kinda useful
  { "ellisonleao/gruvbox.nvim",           priority = 1000 }, -- My theme
  -- LLM stuff
  -- { "zbirenbaum/copilot.lua" }, -- Turning this off as its just autocomplete
  {
    "robitx/gp.nvim",
    config = function()
      local conf = {
        -- For customization, refer to Install > Configuration in the Documentation/Readme
        openai_api_key = { "op", "item", "get", "OpenAI", "--field", "credential", "--reveal" }
      }
      require("gp").setup(conf)

      -- Setup shortcuts here (see Usage > Shortcuts in the Documentation/Readme)
    end,
  },

  -- Git Support
  { "lewis6991/gitsigns.nvim" },
  { 'tpope/vim-fugitive' },
  { 'tpope/vim-rhubarb' },

  -- Debugger Support -- is this even a good idea? maybe for scala...
  { 'mfussenegger/nvim-dap',  dependencies = { "nvim-neotest/nvim-nio" } },
  { 'rcarriga/nvim-dap-ui' },
  -- Status line mostly for scala support
  {
    'nvim-lualine/lualine.nvim',
    dependencies = { 'nvim-tree/nvim-web-devicons' }
  },
  {
    "j-hui/fidget.nvim",
    opts = {
      -- options
    },
  },
  -- SQL support ugh... better than nothing i guess in case i need to sql things up
  {
    'kristijanhusak/vim-dadbod-ui',
    dependencies = {
      { 'tpope/vim-dadbod',                     lazy = true },
      { 'kristijanhusak/vim-dadbod-completion', ft = { 'sql', 'mysql', 'plsql' }, lazy = true }, -- Optional
    },
    cmd = {
      'DBUI',
      'DBUIToggle',
      'DBUIAddConnection',
      'DBUIFindBuffer',
    },
    init = function()
      -- Your DBUI configuration
      vim.g.db_ui_use_nerd_fonts = 1
    end,
  }
})
