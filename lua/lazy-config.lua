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
  { 'scalameta/nvim-metals',           dependencies = { 'nvim-lua/plenary.nvim' }, main = 'neo-mittens.plugins.metals',     config = true },
  { "nvim-treesitter/nvim-treesitter", build = ":TSUpdate", config = function() require('neo-mittens.plugins.treesitter').setup() end },
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
    ft = "markdown",   -- Lazy-load only for markdown files

    -- For `nvim-treesitter` users.
    priority = 49,

    config = function(_, opts)
      -- Set up distinct heading colors (gruvbox-inspired)
      vim.api.nvim_set_hl(0, "MarkviewHeading1", { fg = "#fb4934", bold = true })        -- red
      vim.api.nvim_set_hl(0, "MarkviewHeading2", { fg = "#fabd2f", bold = true })        -- yellow
      vim.api.nvim_set_hl(0, "MarkviewHeading3", { fg = "#b8bb26", bold = true })        -- green
      vim.api.nvim_set_hl(0, "MarkviewHeading4", { fg = "#83a598", bold = true })        -- blue
      vim.api.nvim_set_hl(0, "MarkviewHeading5", { fg = "#d3869b", bold = true })        -- purple
      vim.api.nvim_set_hl(0, "MarkviewHeading6", { fg = "#8ec07c", bold = true })        -- aqua
      vim.api.nvim_set_hl(0, "MarkviewCheckboxChecked", { fg = "#b8bb26" })              -- green
      vim.api.nvim_set_hl(0, "MarkviewCheckboxUnchecked", { fg = "#928374" })            -- gray
      vim.api.nvim_set_hl(0, "MarkviewCheckboxPending", { fg = "#fabd2f" })              -- yellow

      require("markview").setup(opts)
    end,

    opts = {
      preview = {
        modes = { "n", "c" },
        hybrid_modes = { "n" },
        linewise_hybrid_mode = true,
        max_buf_lines = 1000,
        debounce = 50,
        map_gx = true,
      },

      markdown = {
        headings = {
          enable = true,
          shift_width = 0,

          heading_1 = { style = "icon", icon = "█ ", hl = "MarkviewHeading1" },
          heading_2 = { style = "icon", icon = "▓ ", hl = "MarkviewHeading2" },
          heading_3 = { style = "icon", icon = "▒ ", hl = "MarkviewHeading3" },
          heading_4 = { style = "icon", icon = "░ ", hl = "MarkviewHeading4" },
          heading_5 = { style = "icon", icon = "◆ ", hl = "MarkviewHeading5" },
          heading_6 = { style = "icon", icon = "◇ ", hl = "MarkviewHeading6" },
        },

        list_items = {
          enable = true,
          indent_size = 2,
          shift_width = 0,

          marker_minus = { add_padding = false, text = "•" },
          marker_plus = { add_padding = false, text = "◦" },
          marker_star = { add_padding = false, text = "★" },
          marker_dot = { add_padding = false },
          marker_parenthesis = { add_padding = false },
        },

        code_blocks = {
          style = "language",
          pad_amount = 1,
          language_names = {
            lua = "Lua",
            python = "Python",
            javascript = "JavaScript",
            typescript = "TypeScript",
            bash = "Bash",
            sh = "Shell",
            c = "C",
            cpp = "C++",
            rust = "Rust",
          },
        },

        horizontal_rules = {
          enable = true,
          parts = {
            { type = "repeating", text = "─", repeat_amount = function() return vim.o.columns end },
          },
        },

        tables = {
          enable = true,
          use_virt_lines = true,
        },

        block_quotes = {
          enable = true,
          default = { border = "▋", border_hl = "MarkviewBlockQuoteDefault" },
        },
      },

      markdown_inline = {
        checkboxes = {
          enable = true,
          checked = { text = "󰄵", hl = "MarkviewCheckboxChecked" },
          unchecked = { text = "󰄱", hl = "MarkviewCheckboxUnchecked" },
          custom = {
            { match_string = "-", text = "󰍶", hl = "MarkviewCheckboxPending" },
            { match_string = ">", text = "󰒭", hl = "MarkviewCheckboxCancelled" },
            { match_string = "~", text = "󰰱", hl = "MarkviewCheckboxCancelled" },
          },
        },

        inline_codes = {
          enable = true,
          hl = "MarkviewInlineCode",
          corner_left = " ",
          corner_right = " ",
        },

        hyperlinks = {
          enable = true,
          icon = " ",
          hl = "MarkviewHyperlink",
        },

        images = {
          enable = true,
          icon = " ",
          hl = "MarkviewImage",
        },

        emphasis = {
          enable = true,
          hl = "MarkviewItalic",
        },

        strong = {
          enable = true,
          hl = "MarkviewBold",
        },
      },
    },
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
            "rg", -- Use rg instead of rga (ripgrep-all is slower)
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


  { "ThePrimeagen/harpoon",                branch = "harpoon2",                     dependencies = { "nvim-lua/plenary.nvim" }, main = 'neo-mittens.plugins.harpoon', config = true },
  { "mbbill/undotree",                     main = 'neo-mittens.plugins.undotree',   config = true },
  { 'dstein64/nvim-scrollview',            main = 'neo-mittens.plugins.scrollview', config = true },
  { "lukas-reineke/indent-blankline.nvim", main = 'neo-mittens.plugins.indent',     config = true },
  {
    "Fildo7525/pretty_hover",
    event = "LspAttach",
    opts = {}
  },
  { 'stevearc/oil.nvim',      dependencies = { "nvim-tree/nvim-web-devicons" }, main = 'neo-mittens.plugins.oil',                     config = true },
  { 'echasnovski/mini.pairs', version = '*',                                    config = function() require('mini.pairs')
        .setup() end },
  {
    'echasnovski/mini.surround',
    version = '*',
    config = function()
      require('mini.surround').setup({
        custom_surroundings = {
          b = { output = function() return { left = '**', right = '**' } end },
          i = { output = function() return { left = '_', right = '_' } end },
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
  { 'echasnovski/mini.comment',   version = '*', config = function() require('mini.comment').setup() end },
  { 'echasnovski/mini.splitjoin', version = '*', config = function() require('mini.splitjoin').setup() end },
  {
    'echasnovski/mini.operators',
    version = '*',
    config = function()
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
  { "ellisonleao/gruvbox.nvim", priority = 1000 },   -- My theme

  -- Git Support
  { "lewis6991/gitsigns.nvim",  main = 'neo-mittens.plugins.gitsigns', config = true },

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
        url_rules = {
          -- Override to use current branch (HEAD) instead of upstream
          {
            pattern = "^https?://([^/]+)/(.+)$",
            replace = "https://%1/%2",
            format_url = function(base_url, params)
              -- Use current branch instead of upstream
              local branch = vim.fn.trim(vim.fn.system("git rev-parse --abbrev-ref HEAD"))
              if branch == "" or branch == "HEAD" then
                branch = params.branch -- fallback to plugin's branch
              end
              local single_line_url =
                string.format("%s/blob/%s/%s#L%d", base_url, branch, params.file_path, params.start_line)
              if params.start_line == params.end_line then
                return single_line_url
              end
              return string.format("%s-L%d", single_line_url, params.end_line)
            end,
          },
        },
      })

      vim.keymap.set({ 'n', 'v' }, "<leader>gy", function() require("git-link").copy_line_url() end)
      vim.keymap.set({ 'n', 'v' }, "<leader>go", function() require("git-link").open_line_url() end)
    end,
  },
  -- { 'tpope/vim-fugitive' },      -- This is the greatest git plugin for vim
  -- { 'tpope/vim-rhubarb' },       -- Extension for fugitive specifically for github, eg open stuff in browsers

  -- Debugger Support
  { 'mfussenegger/nvim-dap',     dependencies = { "nvim-neotest/nvim-nio" } },
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
  },
})
