local M = {}

function M.on_lsp_attach()
  vim.api.nvim_create_autocmd('LspAttach', {
    desc = 'LSP actions',
    callback = function(event)
      local opts = { buffer = event.buf }
      vim.keymap.set('n', 'K', function() require('pretty_hover').hover() end, opts)
      vim.keymap.set('n', 'gd', function() vim.lsp.buf.definition() end, opts)
      vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, opts)
      vim.keymap.set('n', 'gi', function() vim.lsp.buf.implementation() end, opts)
      vim.keymap.set('n', 'go', function() vim.lsp.buf.type_definition() end, opts)
      vim.keymap.set('n', 'gr', function() vim.lsp.buf.references() end, opts)
      vim.keymap.set('n', 'gs', function() vim.lsp.buf.signature_help() end, opts)
      vim.keymap.set('n', '<F2>', function() vim.lsp.buf.rename() end, opts)
      vim.keymap.set({ 'n', 'x' }, '<F3>', function() vim.lsp.buf.format({ async = true }) end, opts)
      vim.keymap.set('n', '<F4>', function() vim.lsp.buf.code_action() end, opts)
      vim.keymap.set({ 'n', 'v' }, '<leader>va', function() vim.lsp.buf.code_action({ apply = true }) end, opts)
      vim.keymap.set('n', '[d', function()
        vim.diagnostic.jump({ float = true, _highest = true, count = -1 })
        vim.cmd('norm zz')
      end, opts)
      vim.keymap.set('n', ']d', function()
        vim.diagnostic.jump({ float = true, _highest = true, count = 1 })
        vim.cmd('norm zz')
      end, opts)
      vim.keymap.set({ 'n', 'v' }, '<A-S-f>', function() vim.lsp.buf.format() end, opts)
      vim.keymap.set('n', '<leader>vs', function() vim.lsp.buf.workspace_symbol() end, opts)
      vim.keymap.set('n', '<leader>vts', function() vim.lsp.buf.typehierarchy('subtypes') end, opts)
      vim.keymap.set('n', '<leader>vtr', function() vim.lsp.buf.typehierarchy('supertypes') end, opts)
      vim.keymap.set('n', '<leader>vd', function() vim.diagnostic.open_float() end, opts)

      if vim.lsp.inlay_hint then
        vim.lsp.inlay_hint.enable(true, { bufnr = event.buf })
        vim.keymap.set('n', '<leader>vh', function()
          vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled({ bufnr = event.buf }), { bufnr = event.buf })
        end, opts)
      end

      local client = vim.lsp.get_client_by_id(event.data.client_id)
      if client and client:supports_method('textDocument/documentHighlight', event.buf) then
        local hl_group = vim.api.nvim_create_augroup('lsp_document_highlight_' .. event.buf, { clear = true })
        vim.api.nvim_create_autocmd({ 'CursorHold', 'CursorHoldI' }, {
          group = hl_group,
          buffer = event.buf,
          callback = vim.lsp.buf.document_highlight,
        })
        vim.api.nvim_create_autocmd({ 'CursorMoved', 'CursorMovedI' }, {
          group = hl_group,
          buffer = event.buf,
          callback = vim.lsp.buf.clear_references,
        })
      end
    end,
  })
end

-- SINGLE SOURCE OF TRUTH for Mason-managed LSP servers.
-- Keys are LSP server names (mason-lspconfig translates them to mason
-- packages for install). Values are optional per-server `vim.lsp.config`
-- overrides (empty table = defaults). This one table drives BOTH:
--   * install:  M.server_names() -> mason-lspconfig `ensure_installed`
--   * enable:   M.mason_setup()  -> vim.lsp.config + vim.lsp.enable
-- Note: `valk` is NOT here -- it's a local (non-Mason) server configured below.
M.servers = {
  lua_ls = {},
  ts_ls = {},
  rust_analyzer = {},
  neocmake = {},
  basedpyright = {
    -- Detect a project-local virtualenv and point basedpyright at its
    -- interpreter so imports (e.g. google.cloud.*) resolve for hover and
    -- go-to-definition. Without this, basedpyright falls back to the global
    -- Python, which lacks the project's dependencies.
    --
    -- We can't rely on `root_dir` alone: this project has no root markers
    -- (pyproject.toml/.git/etc.), so basedpyright's root falls back to
    -- Neovim's cwd, which may be a different project entirely. Instead we
    -- walk upward from the opened file to find the nearest `.venv`.
    before_init = function(_, config)
      -- Directory of the file that triggered this LSP start.
      local fname = vim.api.nvim_buf_get_name(vim.api.nvim_get_current_buf())
      local start = (fname ~= '' and vim.fs.dirname(fname))
        or config.root_dir
        or vim.fn.getcwd()

      local names = { '.venv', 'venv', 'env', '.env' }
      local found
      -- vim.fs.find with upward search from the file's directory.
      for _, dir in ipairs(vim.fs.find(names, {
        path = start,
        upward = true,
        type = 'directory',
        limit = 1,
      })) do
        local py = dir .. '/bin/python'
        if vim.loop.fs_stat(py) then
          found = py
          break
        end
      end

      if found then
        config.settings = config.settings or {}
        config.settings.python = vim.tbl_deep_extend(
          'force',
          config.settings.python or {},
          { pythonPath = found }
        )
      end
    end,
  },
  ruff = {},
  clangd = {
    cmd = { 'clangd', '--clang-tidy', '--fallback-style=Google', '--background-index', '--completion-style=bundled', '--header-insertion=iwyu' },
    init_options = { clangdFileStatus = true },
  },
}

-- List of server names, for mason-lspconfig `ensure_installed`.
function M.server_names()
  return vim.tbl_keys(M.servers)
end

-- Configure + enable exactly the servers we declared. Enabling is idempotent
-- and independent of install timing: vim.lsp.enable() just registers intent,
-- and the server attaches once its binary is present.
function M.mason_setup()
  for name, cfg in pairs(M.servers) do
    if next(cfg) ~= nil then
      vim.lsp.config(name, cfg)
    end
    vim.lsp.enable(name)
  end
end

-- Valkyria LSP — prefer the AOT binary at build/valk-lsp; fall back to the
-- tree-walker only if the AOT binary is absent.
local valk_aot = vim.fn.expand('~/src/valkyria/build/valk-lsp')
local valk_tw = vim.fn.expand('~/src/valkyria/build/valk')
local valk_cmd
if vim.loop.fs_stat(valk_aot) then
  valk_cmd = { valk_aot }
elseif vim.loop.fs_stat(valk_tw) then
  valk_cmd = { valk_tw, vim.fn.expand('~/src/valkyria/scripts/lsp/main.valk') }
end
if valk_cmd then
  vim.lsp.config('valk', {
    cmd = valk_cmd,
    cmd_cwd = vim.fn.expand('~/src/valkyria'),
    cmd_env = { VALK_HEAP_HARD_LIMIT = '4294967296' },
    filetypes = { 'valk' },
    root_markers = { '.git', 'CMakeLists.txt' },
    on_attach = function(client, bufnr)
      if vim.lsp.inlay_hint then
        vim.lsp.inlay_hint.enable(true, { bufnr = bufnr })
      end
    end,
  })
  vim.lsp.enable('valk')
end

-- Vulkan documentation helper
-- Opens official Vulkan docs for function under cursor with gK
vim.api.nvim_create_autocmd("BufEnter", {
  pattern = {"*.c", "*.h", "*.cpp", "*.hpp"},
  callback = function()
    local bufnr = vim.api.nvim_get_current_buf()
    -- Check first 50 lines for Vulkan-related content
    local lines = vim.api.nvim_buf_get_lines(bufnr, 0, math.min(50, vim.api.nvim_buf_line_count(bufnr)), false)
    local content = table.concat(lines, "\n")

    -- Detect if this is a Vulkan-related file
    if content:match("#include.*vulkan") or
       content:match("#include.*volk") or
       content:match("vk[A-Z]") or
       content:match("Vk[A-Z]") then

      vim.keymap.set('n', 'gK', function()
        local word = vim.fn.expand("<cword>")
        if word:match("^[vV]k") then
          local url = "https://registry.khronos.org/vulkan/specs/1.3-extensions/man/html/" .. word .. ".html"
          vim.fn.system("xdg-open " .. url)
          vim.notify("Vulkan docs: " .. word, vim.log.levels.INFO)
        else
          vim.notify("Not a Vulkan function: " .. word, vim.log.levels.WARN)
        end
      end, { buffer = bufnr, desc = "Open Vulkan docs" })
    end
  end
})

-- Command to search Vulkan spec
vim.api.nvim_create_user_command('VkSpec', function(opts)
  local query = opts.args ~= "" and opts.args or vim.fn.expand("<cword>")
  local url = "https://registry.khronos.org/vulkan/specs/1.3-extensions/html/vkspec.html#" .. query
  vim.fn.system("xdg-open " .. url)
  vim.notify("Opening Vulkan spec: " .. query, vim.log.levels.INFO)
end, { nargs = '?', desc = 'Search Vulkan specification' })

-- :LspRestart [name] -- stop matching clients and re-attach.
-- With the native vim.lsp.config/enable API there is no built-in restart, so
-- we stop the client(s) and re-fire filetype detection to re-attach. Runs
-- before_init again, which is required to re-detect a project's venv.
vim.api.nvim_create_user_command('LspRestart', function(opts)
  local name = opts.args ~= '' and opts.args or nil
  local clients = vim.lsp.get_clients(name and { name = name } or {})
  if vim.tbl_isempty(clients) then
    vim.notify('LspRestart: no active clients' .. (name and (' named ' .. name) or ''),
      vim.log.levels.WARN)
    return
  end

  -- Remember which buffers each client was attached to so we can re-attach.
  local buffers = {}
  for _, client in ipairs(clients) do
    for bufnr in pairs(client.attached_buffers or {}) do
      buffers[bufnr] = true
    end
    client:stop(true)
  end

  -- Wait for clients to fully stop, then re-trigger filetype detection so
  -- vim.lsp.enable() re-attaches the servers.
  local ids = vim.tbl_map(function(c) return c.id end, clients)
  vim.wait(2000, function()
    for _, id in ipairs(ids) do
      if not vim.lsp.get_client_by_id(id) then
        -- still others may be alive; check all are gone
      end
    end
    for _, id in ipairs(ids) do
      if vim.lsp.get_client_by_id(id) then return false end
    end
    return true
  end, 50)

  for bufnr in pairs(buffers) do
    if vim.api.nvim_buf_is_valid(bufnr) then
      vim.api.nvim_buf_call(bufnr, function()
        vim.cmd('edit')
      end)
    end
  end
  vim.notify('LspRestart: restarted ' .. #clients .. ' client(s)', vim.log.levels.INFO)
end, {
  nargs = '?',
  desc = 'Restart LSP client(s) (optionally by name) and re-attach',
  complete = function()
    return vim.tbl_map(function(c) return c.name end, vim.lsp.get_clients())
  end,
})

return M

