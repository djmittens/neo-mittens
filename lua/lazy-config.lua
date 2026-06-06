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
  { "nvim-treesitter/nvim-treesitter", branch = "main", build = ":TSUpdate", config = function() require('neo-mittens.plugins.treesitter').setup() end },
  {
    dir = "~/src/valkyria/editors",
    name = "valk-editors",
    enabled = vim.loop.fs_stat(vim.fn.expand('~/src/valkyria/editors')) ~= nil,
    build = "cc -shared -o valk.so -fPIC -I src src/parser.c && cp valk.so " .. vim.fn.stdpath("data") .. "/site/parser/valk.so",
  },
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
    ft = { "markdown", "Avante" },

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
        debounce = 300,
        map_gx = true,
        filetypes = { "markdown", "quarto", "rmd", "typst", "asciidoc", "Avante" },
        ignore_buftypes = {},
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
    "sindrets/diffview.nvim",
    config = function()
      -- Track reviewed files across the diffview session
      local reviewed_ns = vim.api.nvim_create_namespace('diffview_reviewed')
      local reviewed_files = {}

      local function toggle_reviewed()
        -- Only works in the file panel buffer
        local bufname = vim.api.nvim_buf_get_name(0)
        if not bufname:match('DiffviewFilePanel') then return end

        local line = vim.fn.line('.') - 1  -- 0-indexed for extmarks
        local line_text = vim.api.nvim_buf_get_lines(0, line, line + 1, false)[1] or ''

        if reviewed_files[line] then
          -- Unmark
          reviewed_files[line] = nil
          vim.api.nvim_buf_clear_namespace(0, reviewed_ns, line, line + 1)
        else
          -- Mark as reviewed
          reviewed_files[line] = true
          vim.api.nvim_buf_set_extmark(0, reviewed_ns, line, 0, {
            virt_text = { { ' ✓', 'DiagnosticOk' } },
            virt_text_pos = 'eol',
          })
        end
      end

      local function reapply_reviewed_marks(bufnr)
        vim.api.nvim_buf_clear_namespace(bufnr, reviewed_ns, 0, -1)
        for line, _ in pairs(reviewed_files) do
          pcall(vim.api.nvim_buf_set_extmark, bufnr, reviewed_ns, line, 0, {
            virt_text = { { ' ✓', 'DiagnosticOk' } },
            virt_text_pos = 'eol',
          })
        end
      end

      require("diffview").setup({
        enhanced_diff_hl = true,
        view = {
          default    = { winbar_info = true },
          file_history = { winbar_info = true },
          merge_tool   = { winbar_info = true },
        },
        hooks = {
          diff_buf_read = function(bufnr, ctx)
            vim.opt_local.wrap = false
            vim.opt_local.list = false
            vim.opt_local.relativenumber = false
            -- Prevent diffview from wiping git-object buffers when navigating away.
            -- Without this, new/added files lose their content after switching to other files.
            vim.bo[bufnr].bufhidden = 'hide'
          end,
          diff_buf_win_enter = function(bufnr, winid, ctx)
            local label = ({ a = ' OLD ', b = ' NEW ' })[ctx.symbol]
            if label then
              vim.wo[winid].winbar = label .. ' %f'
            end
            -- Tag buffer with its diff side so <leader>go can use L vs R anchors
            vim.b[bufnr].diffview_side = ctx.symbol  -- "a" = old, "b" = new
          end,
          view_post_layout = function()
            -- Reapply marks after diffview redraws the file panel
            for _, buf in ipairs(vim.api.nvim_list_bufs()) do
              if vim.api.nvim_buf_get_name(buf):match('DiffviewFilePanel') then
                reapply_reviewed_marks(buf)
              end
            end
          end,
        },
        keymaps = {
          file_panel = {
            { 'n', '<leader>v', toggle_reviewed, { desc = 'Toggle file as reviewed' } },
            { 'n', 'p', require('diffview.actions').select_entry, { desc = 'Preview file (keep focus in panel)' } },
            { 'n', '<CR>', require('diffview.actions').focus_entry, { desc = 'Open file and focus diff' } },
          },
        },
      })
    end,
  },
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
      -- Cache PR lookup per branch to avoid shelling out on every invocation.
      -- Invalidated when the branch changes.
      local _pr_cache = { branch = nil, pr_url = nil }

      local function get_pr_url()
        local branch = vim.fn.trim(vim.fn.system("git rev-parse --abbrev-ref HEAD"))
        if branch == "" or branch == "HEAD" then return nil end
        if _pr_cache.branch == branch then return _pr_cache.pr_url end

        local out = vim.fn.trim(vim.fn.system("gh pr view --json url --jq .url 2>/dev/null"))
        local pr_url = (vim.v.shell_error == 0 and out ~= "") and out or nil
        _pr_cache = { branch = branch, pr_url = pr_url }
        return pr_url
      end

      require("git-link").setup({
        url_rules = {
          {
            pattern = "^https?://([^/]+)/(.+)$",
            replace = "https://%1/%2",
            format_url = function(base_url, params)
              local pr_url = get_pr_url()

              if pr_url then
                -- PR file view: link into the Files tab with a file anchor and line comment
                -- GitHub anchors the file diff via sha256 of the file path
                local handle = io.popen("printf '%s' '" .. params.file_path .. "' | shasum -a 256 | cut -d' ' -f1")
                local sha = handle and vim.fn.trim(handle:read("*a")) or ""
                if handle then handle:close() end

                local anchor = string.format("diff-%s", sha)
                if params.start_line == params.end_line then
                  return string.format("%s/files#%sR%d", pr_url, anchor, params.start_line)
                end
                return string.format("%s/files#%sR%d-R%d", pr_url, anchor, params.start_line, params.end_line)
              end

              -- Fallback: blob URL on current branch
              local branch = vim.fn.trim(vim.fn.system("git rev-parse --abbrev-ref HEAD"))
              if branch == "" or branch == "HEAD" then
                branch = params.branch
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

      -- Extract file path + line from a diffview buffer and open in PR/blob view.
      -- Diffview buffer names look like: diffview://.../worktrees/.../{rev}/{file_path}
      -- or diffview://.../objects/.../{rev}/{file_path}
      local function diffview_url()
        local bufname = vim.api.nvim_buf_get_name(0)
        if not bufname:match('^diffview://') then return nil end

        -- The file path follows the short rev hash (7-40 hex chars) after .git/
        local file_path = bufname:match('/[0-9a-f]+/(.+)$')
        if not file_path then return nil end

        local line = vim.fn.line('.')
        -- GitHub PR diff anchors: L = old (left) side, R = new (right) side
        local side = vim.b.diffview_side  -- "a" = old, "b" = new (set by diff_buf_win_enter hook)
        local line_prefix = (side == 'a') and 'L' or 'R'
        local pr_url = get_pr_url()

        if pr_url then
          local handle = io.popen("printf '%s' '" .. file_path .. "' | shasum -a 256 | cut -d' ' -f1")
          local sha = handle and vim.fn.trim(handle:read("*a")) or ""
          if handle then handle:close() end
          return string.format("%s/files#diff-%s%s%d", pr_url, sha, line_prefix, line)
        end

        -- Fallback: blob URL
        local remote_url = vim.fn.trim(vim.fn.system("git remote get-url origin 2>/dev/null"))
        local base = remote_url:gsub('%.git$', '')
        local branch = vim.fn.trim(vim.fn.system("git rev-parse --abbrev-ref HEAD"))
        return string.format("%s/blob/%s/%s#L%d", base, branch, file_path, line)
      end

      local function open_or_fallback()
        local url = diffview_url()
        if url then
          vim.fn.jobstart({ 'open', url }, { detach = true })
        else
          require("git-link").open_line_url()
        end
      end

      local function copy_or_fallback()
        local url = diffview_url()
        if url then
          vim.fn.setreg('+', url)
          vim.notify('Copied: ' .. url, vim.log.levels.INFO)
        else
          require("git-link").copy_line_url()
        end
      end

      vim.keymap.set({ 'n', 'v' }, "<leader>gy", copy_or_fallback)
      vim.keymap.set({ 'n', 'v' }, "<leader>go", open_or_fallback)
    end,
  },
  -- { 'tpope/vim-fugitive' },      -- This is the greatest git plugin for vim
  -- { 'tpope/vim-rhubarb' },       -- Extension for fugitive specifically for github, eg open stuff in browsers

  -- AI assistant (Cursor-like sidebar)
  {
    "yetone/avante.nvim",
    event = "VeryLazy",
    version = false,
    build = "make",
    dependencies = {
      "nvim-lua/plenary.nvim",
      "MunifTanjim/nui.nvim",
      "nvim-tree/nvim-web-devicons",
      "nvim-telescope/telescope.nvim",
      "hrsh7th/nvim-cmp",

    },
    opts = {
      provider = "opencode",
      selection = {
        enabled = true,
        hint_display = "right_align",
      },
      acp_providers = {
        opencode = {
          command = "opencode",
          args = { "acp" },
        },
      },
      mappings = {
        submit = {
          normal = "<CR>",
          insert = "<C-j>",
        },
      },
    },
  },

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
