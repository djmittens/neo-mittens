-- Self-contained treesitter parser manager -- NO third-party plugin.
--
-- Neovim 0.12 ships the treesitter runtime (`vim.treesitter`) and bundles a
-- handful of parsers, but it has no parser installer and no :TSInstall /
-- :TSUpdate commands. Those came from the nvim-treesitter plugin, which we no
-- longer use (the archived original + the typosquat "neovim-treesitter" fork).
--
-- This module reimplements the small slice we actually need:
--   * :TSInstall <lang...>   git clone + cc compile a grammar into the site dir
--   * :TSUpdate  [<lang...>] re-pull + recompile (all installed if none given)
--   * :TSUninstall <lang...> remove the compiled parser + its queries
--   * :TSList                show install status
-- plus a FileType autocmd that turns on highlighting via vim.treesitter.start().
--
-- Trust model: parser grammars are cloned ONLY from the explicit upstream URLs
-- in `sources` below. Query .scm files are plain text and are fetched from the
-- (archived, read-only) canonical nvim-treesitter repo; audit them if paranoid.

local M = {}

local uv = vim.loop or vim.uv
local site = vim.fn.stdpath('data') .. '/site'
local parser_dir = site .. '/parser'
local query_root = site .. '/queries'

-- Parser ABI to generate grammars at. We pin this instead of using the CLI
-- default ("latest", currently 15) to work around a bug in the tree-sitter
-- runtime vendored into Neovim 0.12.x.
--
-- The bug: ABI 15 added *supertype* metadata to generated parsers. In the
-- nvim-treesitter `main` queries, patterns match named children directly under
-- supertype nodes (e.g. python `(expression_statement (string (string_content)
-- @spell))` -- `expression_statement` is a supertype at ABI 15). Neovim
-- 0.12.3's bundled tree-sitter has an older query analyzer whose supertype
-- child-reachability check is broken, so it rejects such patterns at load time
-- with "Query error ... Impossible pattern", which crashes the highlighter
-- (seen as an error on LSP hover). The standalone tree-sitter CLI (0.26.x) and
-- newer runtimes analyze these correctly.
--
-- Generating at ABI 14 emits no supertype metadata (SUPERTYPE_COUNT 0), so the
-- affected nodes are ordinary concrete nodes and the analyzer is happy.
--
-- TODO(abi): revisit after upgrading Neovim. Once nvim ships a tree-sitter with
-- the fixed supertype analyzer, bump this to 15 (or drop the pin and use the
-- CLI default). To check: install python at ABI 15 and confirm
--   :lua vim.treesitter.query.get('python', 'highlights')
-- loads without "Impossible pattern". Upstream context: tree-sitter supertype
-- query analysis; nvim vendors tree-sitter under its own release cadence.
local PARSER_ABI = 14

-- Where query .scm files come from. Archived but canonical & read-only.
local QUERY_BASE =
  'https://raw.githubusercontent.com/nvim-treesitter/nvim-treesitter/main/runtime/queries'
local QUERY_FILES = { 'highlights.scm', 'injections.scm', 'folds.scm', 'locals.scm' }

-- Explicit, auditable grammar sources. Each entry:
--   url      : git repo to clone
--   location : subdir containing src/parser.c (for monorepos); nil = repo root
--   lang     : parser name (defaults to the table key)
local sources = {
  c          = { url = 'https://github.com/tree-sitter/tree-sitter-c' },
  cpp        = { url = 'https://github.com/tree-sitter/tree-sitter-cpp' },
  lua        = { url = 'https://github.com/tree-sitter-grammars/tree-sitter-lua' },
  python     = { url = 'https://github.com/tree-sitter/tree-sitter-python' },
  javascript = { url = 'https://github.com/tree-sitter/tree-sitter-javascript' },
  html       = { url = 'https://github.com/tree-sitter/tree-sitter-html' },
  scala      = { url = 'https://github.com/tree-sitter/tree-sitter-scala' },
  vim        = { url = 'https://github.com/neovim/tree-sitter-vim' },
  vimdoc     = { url = 'https://github.com/neovim/tree-sitter-vimdoc' },
  query      = { url = 'https://github.com/tree-sitter-grammars/tree-sitter-query' },
  markdown   = {
    url = 'https://github.com/tree-sitter-grammars/tree-sitter-markdown',
    location = 'tree-sitter-markdown',
  },
  markdown_inline = {
    url = 'https://github.com/tree-sitter-grammars/tree-sitter-markdown',
    location = 'tree-sitter-markdown-inline',
  },
}

-- Languages we want present by default.
local install_languages = {
  'c', 'cpp', 'python', 'lua', 'vim', 'vimdoc', 'query',
  'javascript', 'html', 'markdown', 'markdown_inline', 'scala',
}

-- ---------------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------------

local function log(level, msg)
  vim.schedule(function() vim.notify('[ts] ' .. msg, level) end)
end
local function info(msg) log(vim.log.levels.INFO, msg) end
local function warn(msg) log(vim.log.levels.WARN, msg) end
local function err(msg) log(vim.log.levels.ERROR, msg) end

local function parser_path(lang) return parser_dir .. '/' .. lang .. '.so' end
local function is_installed(lang) return uv.fs_stat(parser_path(lang)) ~= nil end

-- fidget progress handle, with a plain-notify fallback if fidget isn't loaded.
local function progress_start(title, message)
  local ok, fidget = pcall(require, 'fidget')
  if ok and fidget.progress and fidget.progress.handle then
    return fidget.progress.handle.create({
      title = title,
      message = message,
      lsp_client = { name = 'treesitter' },
      cancellable = false,
      percentage = 0,
    })
  end
  -- fallback shim mirroring the fidget handle API
  info(('%s: %s'):format(title, message or ''))
  return {
    report = function(_, p) if p and p.message then info(p.message) end end,
    finish = function() end,
  }
end

-- Async command runner (non-blocking). Calls cb(ok, output) on the main loop.
local function run_async(cmd, opts, cb)
  vim.system(cmd, opts or {}, function(res)
    vim.schedule(function()
      local out = (res.stderr ~= '' and res.stderr) or res.stdout or ''
      cb(res.code == 0, out)
    end)
  end)
end

-- Pick a C/C++ compiler.
local function compiler(is_cpp)
  for _, c in ipairs(is_cpp and { 'c++', 'clang++', 'g++' } or { 'cc', 'clang', 'gcc' }) do
    if vim.fn.executable(c) == 1 then return c end
  end
  return nil
end

-- Download query .scm files for a language into <query_root>/<lang>/ (async).
-- Fires all curl jobs, then calls done() when the last finishes.
local function fetch_queries(lang, done)
  if vim.fn.executable('curl') ~= 1 then return done() end
  local dir = query_root .. '/' .. lang
  vim.fn.mkdir(dir, 'p')
  local remaining = #QUERY_FILES
  for _, f in ipairs(QUERY_FILES) do
    local url = string.format('%s/%s/%s', QUERY_BASE, lang, f)
    run_async({ 'curl', '-fsSL', '-o', dir .. '/' .. f, url }, {}, function()
      remaining = remaining - 1
      if remaining == 0 then done() end -- missing files (e.g. no folds.scm) are fine
    end)
  end
end

-- Install (or reinstall) a single language asynchronously.
-- Pipeline: git clone -> cc compile -> fetch queries -> cb(ok).
local function install_one(lang, cb)
  cb = cb or function() end
  local srcinfo = sources[lang]
  if not srcinfo then
    err(('unknown language %q (add it to `sources`)'):format(lang))
    return cb(false)
  end
  if vim.fn.executable('git') ~= 1 then
    err('git not found on PATH')
    return cb(false)
  end

  local h = progress_start('treesitter', ('%s: cloning'):format(lang))
  local tmp = vim.fn.tempname()

  run_async({ 'git', 'clone', '--depth', '1', srcinfo.url, tmp }, {}, function(ok, out)
    if not ok then
      h:finish()
      err(('clone failed for %s: %s'):format(lang, out))
      return cb(false)
    end

    -- compile
    h:report({ message = ('%s: compiling'):format(lang), percentage = 50 })
    local srcdir = srcinfo.location and (tmp .. '/' .. srcinfo.location) or tmp
    local src = srcdir .. '/src'
    if not uv.fs_stat(src .. '/parser.c') then
      h:finish(); vim.fn.delete(tmp, 'rf')
      err(('no src/parser.c for %s'):format(lang))
      return cb(false)
    end
    local has_cpp = uv.fs_stat(src .. '/scanner.cc') ~= nil
    local cc = compiler(has_cpp)
    if not cc then
      h:finish(); vim.fn.delete(tmp, 'rf')
      err('no C/C++ compiler on PATH')
      return cb(false)
    end

    -- Regenerate parser.c pinned to PARSER_ABI (see the comment on that
    -- constant for why). Requires the tree-sitter CLI; if it's missing we fall
    -- back to the committed parser.c, which may be at the CLI-default ABI and
    -- thus hit the nvim 0.12.x "Impossible pattern" analyzer bug for grammars
    -- with supertypes (python, etc.).
    if vim.fn.executable('tree-sitter') == 1 then
      local gen = vim.system(
        { 'tree-sitter', 'generate', '--abi', tostring(PARSER_ABI) },
        { cwd = srcdir }
      ):wait()
      if gen.code ~= 0 then
        warn(('%s: `tree-sitter generate --abi %d` failed, using committed parser.c'):format(lang, PARSER_ABI))
      end
    else
      warn(('%s: tree-sitter CLI not found; using committed parser.c (may hit the ABI %d+ analyzer bug)'):format(lang, PARSER_ABI + 1))
    end

    local ccmd = { cc, '-o', parser_path(srcinfo.lang or lang), '-shared', '-Os', '-fPIC', '-I', src, src .. '/parser.c' }
    if uv.fs_stat(src .. '/scanner.c') then table.insert(ccmd, src .. '/scanner.c') end
    if has_cpp then table.insert(ccmd, src .. '/scanner.cc') end

    run_async(ccmd, {}, function(cok, cout)
      if not cok then
        h:finish(); vim.fn.delete(tmp, 'rf')
        err(('compile failed for %s: %s'):format(lang, cout))
        return cb(false)
      end
      -- queries
      h:report({ message = ('%s: fetching queries'):format(lang), percentage = 80 })
      fetch_queries(lang, function()
        vim.fn.delete(tmp, 'rf')
        h:report({ message = ('%s: done'):format(lang), percentage = 100 })
        h:finish()
        -- retro-activate highlighting for buffers already open in this language
        if M._on_installed then pcall(M._on_installed, srcinfo.lang or lang) end
        cb(true)
      end)
    end)
  end)
end

-- Install a set of languages asynchronously with limited concurrency.
local function install_many(langs, label)
  if #langs == 0 then return end
  local queue = vim.deepcopy(langs)
  local max_concurrent = 3
  local active, done, failed, total = 0, 0, 0, #queue

  local group ---@type table fidget handle for the batch
  local function refresh_group()
    if group then
      group:report({ message = ('%d/%d done'):format(done + failed, total),
        percentage = math.floor((done + failed) / total * 100) })
    end
  end

  local pump
  pump = function()
    while active < max_concurrent and #queue > 0 do
      local lang = table.remove(queue, 1)
      active = active + 1
      install_one(lang, function(ok)
        active = active - 1
        if ok then done = done + 1 else failed = failed + 1 end
        refresh_group()
        if #queue == 0 and active == 0 then
          if group then group:finish() end
          info(('%s: %d ok, %d failed'):format(label or 'done', done, failed))
        else
          pump()
        end
      end)
    end
  end

  group = progress_start('treesitter', ('%s (%d)'):format(label or 'install', total))
  pump()
end

-- ---------------------------------------------------------------------------
-- public: ensure default parsers, define commands + highlight autocmd
-- ---------------------------------------------------------------------------

function M.setup()
  vim.fn.mkdir(parser_dir, 'p')

  -- Ensure `site` is on runtimepath so parsers + queries are found.
  if not vim.tbl_contains(vim.opt.rtp:get(), site) then
    vim.opt.rtp:prepend(site)
  end

  -- Install any missing default parsers in the background on startup.
  local missing = vim.tbl_filter(function(l) return not is_installed(l) end, install_languages)
  install_many(missing, 'startup install')

  -- Enable highlighting per-filetype. Neovim core has no TS-based indent, so
  -- we no longer set indentexpr here. Folds are left to nvim-ufo.
  local fts = vim.deepcopy(install_languages)
  if is_installed('valk') then
    vim.treesitter.language.register('valk', 'valk')
    table.insert(fts, 'valk')
  end

  -- Start TS highlighting for a buffer, but only if the parser is present.
  local function try_start(buf)
    buf = buf or vim.api.nvim_get_current_buf()
    local ft = vim.bo[buf].filetype
    local lang = vim.treesitter.language.get_lang(ft) or ft
    if not is_installed(lang) then return end -- parser not ready yet; retried later
    pcall(vim.treesitter.start, buf, lang)
  end

  vim.api.nvim_create_autocmd('FileType', {
    pattern = fts,
    callback = function(a) try_start(a.buf) end,
  })

  -- When a parser finishes installing, (re)start highlighting for every
  -- already-open buffer whose language matches -- fixes the startup race where
  -- a file opened before its parser was compiled.
  M._on_installed = function(lang)
    for _, buf in ipairs(vim.api.nvim_list_bufs()) do
      if vim.api.nvim_buf_is_loaded(buf) then
        local ft = vim.bo[buf].filetype
        if (vim.treesitter.language.get_lang(ft) or ft) == lang then
          pcall(vim.treesitter.start, buf, lang)
        end
      end
    end
  end

  -- :TSInstall <lang...>  (force-reinstall even if present)
  vim.api.nvim_create_user_command('TSInstall', function(a)
    install_many(a.fargs, 'install')
  end, { nargs = '+', complete = function() return vim.tbl_keys(sources) end })

  -- :TSUpdate [<lang...>]  (default: everything currently installed)
  vim.api.nvim_create_user_command('TSUpdate', function(a)
    local langs = a.fargs
    if #langs == 0 then
      langs = vim.tbl_filter(is_installed, vim.tbl_keys(sources))
    end
    install_many(langs, 'update')
  end, { nargs = '*', complete = function() return vim.tbl_keys(sources) end })

  -- :TSUninstall <lang...>
  vim.api.nvim_create_user_command('TSUninstall', function(a)
    for _, lang in ipairs(a.fargs) do
      vim.fn.delete(parser_path(lang))
      vim.fn.delete(query_root .. '/' .. lang, 'rf')
      info(('uninstalled %s'):format(lang))
    end
  end, { nargs = '+', complete = function()
    return vim.tbl_filter(is_installed, vim.tbl_keys(sources))
  end })

  -- :TSList  (status of every known language)
  vim.api.nvim_create_user_command('TSList', function()
    local lines = {}
    for _, lang in ipairs(vim.fn.sort(vim.tbl_keys(sources))) do
      lines[#lines + 1] = ('  [%s] %s'):format(is_installed(lang) and 'x' or ' ', lang)
    end
    vim.notify('treesitter parsers:\n' .. table.concat(lines, '\n'), vim.log.levels.INFO)
  end, {})
end

return M
