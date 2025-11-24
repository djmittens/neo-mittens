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
    end,
  })
end

function M.mason_setup()
  local mason_lspconfig = require('mason-lspconfig')
  for _, server in ipairs(mason_lspconfig.get_installed_servers()) do
    if server == 'clangd' then
      vim.lsp.config('clangd', {
        cmd = { 'clangd', '--clang-tidy', '--fallback-style=Google', '--background-index', '--completion-style=detailed', '--header-insertion=iwyu' },
        init_options = { clangdFileStatus = true },
      })
    end
    vim.lsp.enable(server)
  end
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

-- Enhanced syntax highlighting for common Vulkan types
vim.api.nvim_create_autocmd("FileType", {
  pattern = {"c", "cpp"},
  callback = function()
    vim.cmd([[
      syn keyword cType VkResult VkInstance VkDevice VkQueue VkCommandBuffer
      syn keyword cType VkBuffer VkImage VkImageView VkPipeline VkRenderPass
      syn keyword cType VkFramebuffer VkSemaphore VkFence VkDeviceMemory
      syn keyword cType VkSurfaceKHR VkSwapchainKHR VkExtent2D VkExtent3D
      syn keyword cType VkPhysicalDevice VkCommandPool VkDescriptorSet
      syn keyword cType VkShaderModule VkPipelineLayout VkDescriptorSetLayout
    ]])
  end
})

return M

