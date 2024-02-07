-- treesitter-config.lua

local configs = require("nvim-treesitter.configs")
configs.setup {
  -- Add a language of your choice
  ensure_installed = {
    "c", "cpp", "python",
    "lua", "vim", "vimdoc", "query",
    "javascript", "html", },
  sync_install = false,
  -- ignore_install = { "" }, -- List of parsers to ignore installing
  highlight = {
    enable = true, -- false will disable the whole extension
    -- disable = { "" }, -- list of language that will be disabled
    additional_vim_regex_highlighting = false,

  },
  indent = { enable = true, disable = { "yaml" } },
  incremental_selection = {
    enable = true,
    keymaps = {
      init_selection    = "vn", -- set to `false` to disable one of the mappings
      scope_incremental = "H",
      --scope_decremental = "L",
      node_incremental  = "K",
      node_decremental  = "J",
    },
  },
}

local hop = require('hop')

hop.setup({})
local directions = require('hop.hint').HintDirection
vim.keymap.set('', 'f', function()
  hop.hint_char1({ direction = directions.AFTER_CURSOR, current_line_only = false, match_mappings = {} })
end, { remap = true })
vim.keymap.set('', 'F', function()
  hop.hint_char1({ direction = directions.BEFORE_CURSOR, current_line_only = false, match_mappings = {} })
end, { remap = true })
vim.keymap.set('', 't', function()
  hop.hint_char1({ direction = directions.AFTER_CURSOR, current_line_only = false, hint_offset = -1, match_mappings = {} })
end, { remap = true })
vim.keymap.set('', 'T', function()
  hop.hint_char1({ direction = directions.BEFORE_CURSOR, current_line_only = false, hint_offset = 1, match_mappings = {} })
end, { remap = true })

local tsht = require("tsht")
vim.keymap.set('', '<leader>n', function() require("tsht").move({side="start"}) end)
-- Does this even work? i got no idea
