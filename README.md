
## Scala Dev
- [ ] Add support for copying fully qualifed classname for an object.
- [x] Surround selected text with braces / quotes
- [x] Toggle comments sections of code
- [ ] Surround code with a snippet

## Linux Ricing
- [ ] use `pywal16` to make all color schemes match with desktop background
    - [ ] Term colors
    - [ ] Waybar
    - [ ] GTK
    - [ ] KDE kvantum
- [ ] Generate live backgrounds
- [ ] Figure out whats going on with that weird usb shit
- [ ] Implement hotkey switch between headphones and hdmi

### Hyprland context aware nav

Basically the idea here is that in hyprland + tmux + nvim setup i want to
navigate panes windows, and whatever else using the same shortcut thats context
aware

One way to achieve this would be to define top level hyprland shortcuts such as
$META + h, j, k, l that kicks off a script such as

1. Check the current window name
    1. Iff the name is a terminal app
        1. Check if the current commad is tmux or neovim
            1. If not fallback to hyprland
            1. If Tmux, check if the current pane is neovim
                1. If neovim, check if we can move to the next pane
                    1. Done
                    1. Otherwise fallthrough
                1. If tmux, check if we can move to the pane next to the right
                    1. Done
                    1. Otherwise fallthrough
                1. If neither, fallback to hyprland


Ok so then i need to figure out how to do the following

- [ ] Figure out how to dispatch key commands to terminal app(alacritty?)
- [ ] Figure out how to query the current window 
    - [ ] hyprland
    - [ ] tmux
- [ ] Figure out how to query whether movent can be completed
    - [ ] tmux
    - [ ] neovim
- [ ] Figure out how to perform the movement
    - [ ] hyprland
    - [ ] tmux
    - [ ] neovim
