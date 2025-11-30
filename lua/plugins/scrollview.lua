local M = {}

function M.setup()
  require('scrollview').setup({
    excluded_filetypes = { 'nerdtree' },
    current_only = false,
    base = 'right',
    signs_on_startup = { 'all' },
    diagnostics_severities = { vim.diagnostic.severity.HINT },
  })
end

return M

