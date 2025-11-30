local M = {}

function M.setup()
  vim.keymap.set('n', '<leader>fm', function() require('telescope').extensions.metals.commands() end, {})
  vim.keymap.set('n', '<leader>fmt', function() require('metals.tvp').toggle_tree_view() end, {})

  local builtin = require('telescope.builtin')
  vim.keymap.set('n', '<leader>fp', function()
    builtin.live_grep({
      search_dirs = { '~/.cache/coursier', '~/.ivy2' },
      glob_pattern = '*-sources.jar',
      find_command = { 'rga', '--color=never', '--no-heading', '--line-number', '--column', '--smart-case', '--hidden' },
    })
  end, {})

  local metals_config = require('metals').bare_config()
  metals_config.settings = {
    defaultBspToBuildTool = false,
    showImplicitArguments = true,
    showImplicitConversionsAndClasses = true,
    showInferredType = true,
    superMethodLensesEnabled = true,
    bloopSbtAlreadyInstalled = false,
    enableSemanticHighlighting = false,
    verboseCompilation = true,
    excludedPackages = { 'akka.actor.typed.javadsl', 'com.github.swagger.akka.javadsl' },
  }
  metals_config.init_options.statusBarProvider = 'on'
  metals_config.capabilities = require('cmp_nvim_lsp').default_capabilities()
  metals_config.tvp.icons = { enabled = true }

  vim.filetype.add({ extension = { thrift = 'thrift', sbt = 'scala' } })
  metals_config.on_attach = function(_, _)
    require('metals').setup_dap()
  end

  local nvim_metals_group = vim.api.nvim_create_augroup('nvim-metals', { clear = true })
  vim.api.nvim_create_autocmd('FileType', {
    pattern = { 'scala', 'sbt', 'java' },
    callback = function() require('metals').initialize_or_attach(metals_config) end,
    group = nvim_metals_group,
  })

  local pickers = require('telescope.pickers')
  local finders = require('telescope.finders')
  local previewers = require('telescope.previewers')
  local conf = require('telescope.config').values
  local actions = require('telescope.actions')
  local action_state = require('telescope.actions.state')

  local jar_dir = '~/.cache/coursier'
  local search_pattern = 'class'

  local function get_rga_results(pattern, dir)
    local cmd = { 'rga', '--no-heading', '--line-number', '--ignore-case', pattern, dir }
    local results = {}
    local handle = io.popen(table.concat(cmd, ' '))
    if handle then
      for line in handle:lines() do table.insert(results, line) end
      handle:close()
    end
    return results
  end

  local function make_entry(line)
    local parts = {}
    for p in string.gmatch(line, '[^:]+') do table.insert(parts, p) end
    local jar_path = parts[1]
    local internal_path = parts[2]
    local line_num = parts[3]
    local line_content = table.concat(parts, ':', 4)
    return {
      value = { jar = jar_path, filepath = internal_path, line_num = tonumber(line_num), line_content = line_content },
      display = jar_path .. ' : ' .. internal_path,
      ordinal = jar_path .. ' ' .. internal_path .. ' ' .. line_content,
    }
  end

  local JarPreviewer = previewers.new_buffer_previewer({
    define_preview = function(self, entry, _)
      local jar = entry.value.jar
      local internal_file = entry.value.filepath
      local cmd = string.format('unzip -p %q %q', jar, internal_file)
      local output = {}
      local handle = io.popen(cmd)
      if handle then
        for line in handle:lines() do table.insert(output, line) end
        handle:close()
      end
      vim.api.nvim_buf_set_lines(self.state.bufnr, 0, -1, false, output)
      vim.api.nvim_buf_set_option(self.state.bufnr, 'filetype', 'text')
    end,
  })

  local function open_selected_file(prompt_bufnr)
    local entry = action_state.get_selected_entry()
    actions.close(prompt_bufnr)
    local jar = entry.value.jar
    local internal_file = entry.value.filepath
    local tmpfile = vim.fn.tempname()
    os.execute(string.format('unzip -p %q %q > %q', jar, internal_file, tmpfile))
    vim.cmd('edit ' .. vim.fn.fnameescape(tmpfile))
    vim.api.nvim_buf_set_option(0, 'readonly', true)
    vim.api.nvim_buf_set_option(0, 'modifiable', false)
    vim.api.nvim_buf_set_option(0, 'bufhidden', 'wipe')
  end

  local function search_jars()
    local lines = get_rga_results(search_pattern, jar_dir)
    local entries = {}
    for _, line in ipairs(lines) do table.insert(entries, make_entry(line)) end
    pickers.new({}, {
      prompt_title = 'Search in JAR files',
      finder = finders.new_table({ results = entries, entry_maker = function(entry) return entry end }),
      sorter = conf.generic_sorter({}),
      previewer = JarPreviewer,
      attach_mappings = function(prompt_bufnr, _)
        actions.select_default:replace(function() open_selected_file(prompt_bufnr) end)
        return true
      end,
    }):find()
  end

  vim.api.nvim_create_user_command('SearchInJars', search_jars, {})
end

return M

