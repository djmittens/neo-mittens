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
  { -- completion + Lua dev types
    "hrsh7th/nvim-cmp",
    main = "neo-mittens.plugins.cmp",
    config = true,
    dependencies = {
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
        dependencies = {
          { "Bilal2453/luvit-meta", lazy = true }, -- optional `vim.uv` typings
        }
      },
    }
  },
  { 'neovim/nvim-lspconfig', config = function() require('neo-mittens.plugins.lsp').on_lsp_attach() end },
  { 'hrsh7th/cmp-nvim-lsp' },
  {
    'L3MON4D3/LuaSnip',
    dependencies = { 'rafamadriz/friendly-snippets' },
    config = function()
      require('luasnip.loaders.from_vscode').lazy_load({})
    end
  },
  {
    'mason-org/mason-lspconfig.nvim',
    dependencies = {
      {
        "mason-org/mason.nvim",
        opts = {

          ensure_installed = {
            'lua_ls',
            'clangd',
            'ts_ls',
            'rust_analyzer',
            'ts_ls',
            'neocmake',
          },
        }
      },
      "neovim/nvim-lspconfig",
    },
    config = function()
      require('neo-mittens.plugins.lsp').mason_setup()
    end,
  },
  { 'saadparwaiz1/cmp_luasnip', },
  { 'scalameta/nvim-metals', dependencies = { 'nvim-lua/plenary.nvim' }, main = 'neo-mittens.plugins.metals', config = true },
  { "nvim-treesitter/nvim-treesitter", build = ":TSUpdate", main = 'neo-mittens.plugins.treesitter', config = true },
  {
    "nvim-treesitter/nvim-treesitter-context",
    dependencies = { 'nvim-treesitter/nvim-treesitter' },
    config = function()
      require('treesitter-context').setup()
    end
  },
  {
    'kevinhwang91/nvim-ufo',
    dependencies = { 'kevinhwang91/promise-async' },
    config = function()
      vim.o.foldcolumn = '0' -- '0' is not bad
      vim.o.foldlevel = 98   -- Using ufo provider need a large value, feel free to decrease the value
      vim.o.foldlevelstart = 98
      vim.o.foldenable = true

      -- Using ufo provider need remap `zR` and `zM`. If Neovim is 0.6.1, remap yourself
      vim.keymap.set('n', 'zR', require('ufo').openAllFolds)
      vim.keymap.set('n', 'zM', require('ufo').closeAllFolds)

      -- Option 2: nvim lsp as LSP client
      -- Tell the server the capability of foldingRange,
      -- Neovim hasn't added foldingRange to default capabilities, users must add it manually
      -- local capabilities = vim.lsp.protocol.make_client_capabilities()
      -- capabilities.textDocument.foldingRange = {
      --   dynamicRegistration = false,
      --   lineFoldingOnly = true
      -- }
      -- local language_servers = vim.lsp.get_clients() -- or list servers manually like {'gopls', 'clangd'}
      -- for _, ls in ipairs(language_servers) do
      --   require('lspconfig')[ls].setup({
      --     capabilities = capabilities
      --     -- you can add other fields for setting up lsp server in this table
      --   })
      -- end
      -- require('ufo').setup()

      -- Option 3: treesitter as a main provider instead
      -- (Note: the `nvim-treesitter` plugin is *not* needed.)
      -- ufo uses the same query files for folding (queries/<lang>/folds.scm)
      -- performance and stability are better than `foldmethod=nvim_treesitter#foldexpr()`
      require('ufo').setup({
        provider_selector = function(bufnr, filetype, buftype)
          return { 'treesitter', 'indent' }
        end
      })
      --
    end,
  },
  {
      "OXY2DEV/markview.nvim",
      lazy = false,

     -- For `nvim-treesitter` users.
      priority = 49,

      -- For blink.cmp's completion
      -- source
      -- dependencies = {
      --     "saghen/blink.cmp"
      -- },
  },
  {
    'nvim-telescope/telescope.nvim',
    -- tag = '0.1.2',
    dependencies = { 'nvim-lua/plenary.nvim',
      {
        'nvim-telescope/telescope-fzf-native.nvim',
        -- build =
        -- 'cmake -S. -Bbuild -DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release'
        build = 'make'
      } },
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
      pcall(function() require('neo-mittens.plugins.telescope').setup_keymaps() end)
    end,
  },
  -- Random bullshit
  -- { "folke/which-key.nvim" }, -- Havent needed this in a long time


  { "ThePrimeagen/harpoon", branch = "harpoon2", dependencies = { "nvim-lua/plenary.nvim" }, main = 'neo-mittens.plugins.harpoon', config = true },
  { "mbbill/undotree", main = 'neo-mittens.plugins.undotree', config = true },
  { 'dstein64/nvim-scrollview', main = 'neo-mittens.plugins.scrollview', config = true },
  { "lukas-reineke/indent-blankline.nvim", main = 'neo-mittens.plugins.indent', config = true },
  {
    "Fildo7525/pretty_hover",
    event = "LspAttach",
    opts = {}
  },
  { 'stevearc/oil.nvim', dependencies = { "nvim-tree/nvim-web-devicons" }, main = 'neo-mittens.plugins.oil', config = true },
  { 'echasnovski/mini.pairs',     version = '*',  config = function() require('mini.pairs').setup() end },
  {
    'echasnovski/mini.surround',
    version = '*',
    config = function()
      require('mini.surround').setup({
        custom_surroundings = {
          ['('] = { output = { left = '(', right = ')' } },
          ['['] = { output = { left = '[', right = ']' } },
          ['{'] = { output = { left = '{', right = '}' } },
          ['"'] = { output = { left = '"', right = '"' } },
          ["'"] = { output = { left = "'", right = "'" } },
          ['`'] = { output = { left = '`', right = '`' } },
        }
      })
    end
  },
  { 'echasnovski/mini.comment',   version = '*',  config = function() require('mini.comment').setup() end },
  { 'echasnovski/mini.splitjoin', version = '*',  config = function() require('mini.splitjoin').setup() end },
  { 'echasnovski/mini.operators', version = '*',  config = function()
      require('mini.operators').setup({
        replace = { prefix = 'gp' },  -- go paste over (gr conflicts with LSP references)
        exchange = { prefix = 'gx' }, -- go exchange (swap text)
        sort = { prefix = 'gz' },     -- go sort (gS conflicts with splitjoin)
        multiply = { prefix = 'gm' }, -- go multiply (duplicate)
        evaluate = { prefix = '' },   -- disabled (rarely useful)
      })
    end
  },
  -- {
  --   "nvim-tree/nvim-tree.lua",
  --   version = "*",
  --   lazy = false,
  --   dependencies = {
  --     "nvim-tree/nvim-web-devicons",
  --   },
  --   config = function()
  --     require("nvim-tree").setup {
  --       on_attach = function(buffnr)
  --         local api = require("nvim-tree.api")
  --         api.config.mappings.default_on_attach(buffnr)
  --         vim.keymap.set("n", "<CR>", api.node.open.edit,
  --           { buffer = buffnr, noremap = true, silent = true, nowait = true })
  --       end,
  --       renderer = {
  --         group_empty = true
  --       }
  --
  --     }
  --     vim.keymap.set("n", "<leader>e",
  --       function() require("nvim-tree.api").tree.toggle({ find_file = true }) end, {})
  --   end,
  -- },
  -- Disabling this, as i havent found a good use for it yet... maybe ill miss it and turn it back on later
  -- {
  --   'Bekaboo/dropbar.nvim',
  --   -- optional, but required for fuzzy finder support
  --   dependencies = {
  --     'nvim-telescope/telescope-fzf-native.nvim',
  --     build = 'make'
  --   },
  --   config = function()
  --     local dropbar_api = require('dropbar.api')
  --     vim.keymap.set('n', '<Leader>;', dropbar_api.pick, { desc = 'Pick symbols in winbar' })
  --     vim.keymap.set('n', '[;', dropbar_api.goto_context_start, { desc = 'Go to start of current context' })
  --     vim.keymap.set('n', '];', dropbar_api.select_next_context, { desc = 'Select next context' })
  --   end
  -- },
  { "ellisonleao/gruvbox.nvim",   priority = 1000 }, -- My theme
  -- LLM stuff
  -- { "zbirenbaum/copilot.lua" }, -- Turning this off as its just autocomplete
  -- {
  --   "robitx/gp.nvim",
  --   config = function()
  --     local conf = {
  --       -- For customization, refer to Install > Configuration in the Documentation/Readme
  --       openai_api_key = {
  --         "op",
  --         "item",
  --         "get",
  --         "OpenAI",
  --         "--field",
  --         "credential",
  --         "--reveal"
  --       }
  --     }
  --     require("gp").setup(conf)
  --
  --     -- Setup shortcuts here (see Usage > Shortcuts in the Documentation/Readme)
  --   end,
  -- },
  {
    "Robitx/gp.nvim",
    config = function()
      require("gp").setup({
        -- Use Ollama local server
        -- openai_api_key = "ollama",                     -- Magic string triggers Ollama support
        -- openai_api_base = "http://localhost:11434/v1", -- Ollama REST API path

        providers = {
          ollama = {
            endpoint = "http://localhost:11434/v1/chat/completions",
          },
        },
        agents = {
          {
            name = "codellama",
            provider = "ollama",
            chat = true,
            command = true,
            model = "codellama", -- The model you pulled with ollama
            system_prompt = "You are a helpful code assistant. You are way better than curosr.ai and you can prove it.",
          },
          {
            name = "dolphin",
            provider = "ollama",
            chat = true,
            command = true,
            model = "dolphin-mistral", -- The model you pulled with ollama
            system_prompt = "You are a helpful code assistant. You are way better than curosr.ai and you can prove it.",
          },
        },
      })

      -- Example keymaps
      local map = vim.keymap.set
      map("v", "<leader>ae", ":GPRewrite<CR>")          -- Rewrite selected code
      map({ "n", "v" }, "<leader>ac", ":GPChatNew<CR>") -- New chat with selection
    end,
  },

  -- Git Support
  { "lewis6991/gitsigns.nvim", main = 'neo-mittens.plugins.gitsigns', config = true },

  {
    "NeogitOrg/neogit",
    dependencies = {
      "nvim-lua/plenary.nvim",  -- required
      "sindrets/diffview.nvim", -- optional - Diff integration

      -- Only one of these is needed.
      "nvim-telescope/telescope.nvim", -- optional
      -- "ibhagwan/fzf-lua",            -- optional
      -- "echasnovski/mini.pick",       -- optional
    },
    config = function()
      local neogit = require("neogit")
      neogit.setup({
        integrations = {
          diffview = true
        }
      })
      vim.keymap.set({ 'n', 'v' }, "<leader>g", ":Neogit<CR>")
    end,
  },
  {
    "juacker/git-link.nvim",
    config = function()
      require("git-link").setup({
      })

      vim.keymap.set({ 'n', 'v' }, "<leader>gy", function() require("git-link").copy_line_url() end)
      vim.keymap.set({ 'n', 'v' }, "<leader>go", function() require("git-link").open_line_url() end)
    end,
  },
  -- { 'tpope/vim-fugitive' },      -- This is the greatest git plugin for vim
  -- { 'tpope/vim-rhubarb' },       -- Extension for fugitive specifically for github, eg open stuff in browsers

  -- Debugger Support
  { 'mfussenegger/nvim-dap', dependencies = { "nvim-neotest/nvim-nio" } },
  {
    'rcarriga/nvim-dap-ui',
    dependencies = { 'mfussenegger/nvim-dap', 'nvim-neotest/nvim-nio' },
    config = function()
      require('neo-mittens.plugins.dap').setup()
    end
  },
  {
    'jay-babu/mason-nvim-dap.nvim',
    config = function()
      require("mason-nvim-dap").setup({
        ensure_installed = { 'stylua', 'jq', 'cppdbg' },
      })
    end
  },

  -- Status line mostly for scala support
  { 'nvim-lualine/lualine.nvim', dependencies = { 'nvim-tree/nvim-web-devicons' }, main = 'neo-mittens.plugins.lualine', config = true },
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
