vim.keymap.set("n", "<leader>fm", function() require("telescope").extensions.metals.commands() end, {})
vim.keymap.set("n", "<leader>fmt", function() require("metals.tvp").toggle_tree_view() end, {})

local builtin = require('telescope.builtin')
vim.keymap.set('n', '<leader>fp', function()
  builtin.live_grep({
    search_dirs = {
      '~/.cache/coursier',
      '~/.ivy2',
    },
    glob_pattern = '*-sources.jar',
    find_command = {
      "rga",
      "--color=never",
      "--no-heading",
      "--line-number",
      "--column",
      "--smart-case",
      "--hidden",       -- Include hidden files
      -- "--trim",
      --            "--glob", "*.java", -- Adjust glob for file types
    }
  })
end, {})


local metals_config = require("metals").bare_config()
-- Example of settings
metals_config.settings = {
  defaultBspToBuildTool = true, -- So that we can have sbt by default instead of bloop
  showImplicitArguments = true,
  showImplicitConversionsAndClasses = true,
  showInferredType = true,
  superMethodLensesEnabled = true,
  -- useGlobalExecutable = false, -- For when i finally decide to fork metals
  -- metalsBinaryPath = '',
  bloopSbtAlreadyInstalled = true,   -- Bloop, ofcourse is not installed, so dont do it !!!
  enableSemanticHighlighting = true, -- Disable this if there are problems, still experimental
  verboseCompilation = true,
  excludedPackages = { "akka.actor.typed.javadsl", "com.github.swagger.akka.javadsl" },
}

-- *READ THIS*
-- I *highly* recommend setting statusBarProvider to true, however if you do,
-- you *have* to have a setting to display this in your statusline or else
-- you'll not see any messages from metals. There is more info in the help
-- docs about this
metals_config.init_options.statusBarProvider = "on"

-- Example if you are using cmp how to make sure the correct capabilities for snippets are set
metals_config.capabilities = require("cmp_nvim_lsp").default_capabilities()

metals_config.tvp.icons = {
  enabled = true,
}

vim.filetype.add({
  extension = {
    thrift = "thrift",
    sbt = "scala"
  }
})

metals_config.on_attach = function(client, bufnr)
  require("metals").setup_dap()
end

-- Autocmd that will actually be in charge of starting the whole thing
local nvim_metals_group = vim.api.nvim_create_augroup("nvim-metals", { clear = true })

vim.api.nvim_create_autocmd("FileType", {
  -- NOTE: You may or may not want java included here. You will need it if you
  -- want basic Java support but it may also conflict if you are using
  -- something like nvim-jdtls which also works on a java filetype autocmd.
  pattern = { "scala", "sbt", "java" },
  callback = function()
    require("metals").initialize_or_attach(metals_config)
  end,
  group = nvim_metals_group,
})


local pickers = require('telescope.pickers')
local finders = require('telescope.finders')
local previewers = require('telescope.previewers')
local conf = require('telescope.config').values
local actions = require('telescope.actions')
local action_state = require('telescope.actions.state')

-- Directory containing your JAR files:
local jar_dir = "~/.cache/coursier"
-- Pattern to search for:
local search_pattern = "class"

-- We run the rga command and capture its output
local function get_rga_results(pattern, dir)
  local cmd = { "rga", "--no-heading", "--line-number", "--ignore-case", pattern, dir }
  local results = {}
  local handle = io.popen(table.concat(cmd, " "))
  if handle then
    for line in handle:lines() do
      table.insert(results, line)
    end
    handle:close()
  end
  return results
end

-- Entry maker: parse each line from rga output into a structured table
local function make_entry(line)
  -- Format: jarPath:internalPath:lineNum:lineContent
  -- We need to be careful with splitting because file paths can contain ':'
  -- We'll assume jarPath and internalPath have no embedded newlines.
  -- A robust approach: split by ':' from the right.
  
  local parts = {}
  for p in string.gmatch(line, "[^:]+") do
    table.insert(parts, p)
  end

  -- parts = { jar_path, internal_path, line_num, line_content... }
  -- The line_content itself could contain ':', so let's reassemble carefully.
  -- We'll assume:
  -- jar_path = parts[1]
  -- internal_path = parts[2]
  -- line_num = parts[3]
  -- the rest is line_content
  local jar_path = parts[1]
  local internal_path = parts[2]
  local line_num = parts[3]
  local line_content = table.concat(parts, ":", 4)

  return {
    value = {
      jar = jar_path,
      filepath = internal_path,
      line_num = tonumber(line_num),
      line_content = line_content
    },
    display = jar_path .. " : " .. internal_path,
    ordinal = jar_path .. " " .. internal_path .. " " .. line_content
  }
end

-- A custom previewer that shows file contents inside the JAR
local JarPreviewer = previewers.new_buffer_previewer({
  define_preview = function(self, entry, status)
    local jar = entry.value.jar
    local internal_file = entry.value.filepath

    -- Extract file content using unzip -p
    local cmd = string.format("unzip -p %q %q", jar, internal_file)
    local output = {}
    local handle = io.popen(cmd)
    if handle then
      for line in handle:lines() do
        table.insert(output, line)
      end
      handle:close()
    end

    vim.api.nvim_buf_set_lines(self.state.bufnr, 0, -1, false, output)
    vim.api.nvim_buf_set_option(self.state.bufnr, "filetype", "text")
  end
})

-- Action when selecting an entry: open the file in a temporary buffer read-only
local function open_selected_file(prompt_bufnr)
  local entry = action_state.get_selected_entry()
  actions.close(prompt_bufnr)

  local jar = entry.value.jar
  local internal_file = entry.value.filepath

  local tmpfile = vim.fn.tempname()
  os.execute(string.format("unzip -p %q %q > %q", jar, internal_file, tmpfile))

  vim.cmd("edit " .. vim.fn.fnameescape(tmpfile))
  vim.api.nvim_buf_set_option(0, "readonly", true)
  vim.api.nvim_buf_set_option(0, "modifiable", false)
  vim.api.nvim_buf_set_option(0, "bufhidden", "wipe")
end

-- The main picker function
local function search_jars()
  local lines = get_rga_results(search_pattern, jar_dir)
  local entries = {}
  for _, line in ipairs(lines) do
    table.insert(entries, make_entry(line))
  end

  pickers.new({}, {
    prompt_title = "Search in JAR files",
    finder = finders.new_table {
      results = entries,
      entry_maker = function(entry) return entry end,
    },
    sorter = conf.generic_sorter({}),
    previewer = JarPreviewer,
    attach_mappings = function(prompt_bufnr, map)
      actions.select_default:replace(function() open_selected_file(prompt_bufnr) end)
      return true
    end,
  }):find()
end

-- Optional: Map this to a command or key
vim.api.nvim_create_user_command("SearchInJars", search_jars, {})
