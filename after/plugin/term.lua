local api = vim.api

-- TODO: look into potentially using au groups (auto command groups to group these for some reason ?)
-- https://stackoverflow.com/questions/63906439/how-to-disable-line-numbers-in-neovim-terminal
-- api.nvim_command("autocmd TermOpen * startinsert")             -- starts in insert mode
api.nvim_command("autocmd TermOpen * setlocal nonumber")       -- no numbers
api.nvim_command("autocmd TermOpen * setlocal norelativenumber")       -- no numbers
api.nvim_command("autocmd TermEnter * setlocal signcolumn=no") -- no sign column
