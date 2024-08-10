-- Pull in the wezterm API
local wezterm                       = require 'wezterm'

-- This will hold the configuration.
local config                        = wezterm.config_builder()
local io                            = require 'io'
local os                            = require 'os'
local math                          = require 'math'

-- This is where you actually apply your config choices

-- For example, changing the color scheme:
config.color_scheme                 = 'GruvboxDark'
config.hide_tab_bar_if_only_one_tab = true
config.use_fancy_tab_bar            = false


local hsb = {
  -- Darken the background image
  brightness = 0.05,

  -- You can adjust the hue by scaling its value.
  -- a multiplier of 1.0 leaves the value unchanged.
  hue = 1.0,

  -- You can adjust the saturation also.
  saturation = 1.0,
}


-- Path to your waifu directory
local waifu_dir = os.getenv("HOME") .. "/Pictures/Waifu"

-- Function to get a random file from the waifu directory
local function get_random_waifu()
  local files = {}
  for file in io.popen('ls "' .. waifu_dir .. '"'):lines() do
    table.insert(files, file)
  end
  if #files == 0 then
    return nil
  end
  local random_file = files[math.random(#files)]
  return waifu_dir .. '/' .. random_file
end

config.background = {
  -- This is the deepest/back-most layer. It will be rendered first
  {
    source = {
      File =
      -- '/home/djmittens/Pictures/Waifu/wallhaven-j82veq.jpg'
      -- '/home/djmittens/Pictures/Waifu/wallhaven-expqmk.jpg'
      -- '/home/djmittens/Pictures/Waifu/684896_49040378423_o.png'
          get_random_waifu()
    },
    -- The texture tiles vertically but not horizontally.
    -- When we repeat it, mirror it so that it appears "more seamless".
    -- An alternative to this is to set `width = "100%"` and have
    -- it stretch across the display
    repeat_x = 'Mirror',
    hsb = hsb,
    -- When the viewport scrolls, move this layer 10% of the number of
    -- pixels moved by the main viewport. This makes it appear to be
    -- further behind the text.
    attachment = 'Fixed',
  },
}

-- and finally, return the configuration to wezterm
return config
