Files involved
Git-tracked — in /home/xyzyx/src/neo-mittens/hypr/, symlinked as ~/.config/hypr:
File	Mine vs yours
hypr/hypridle.conf	Only two things are mine: the INERT — hypridle.service is MASKED header (lines 3–16) and commenting out on-timeout. Everything else is your uncommitted Sep 19 work.
hypr/hyprland.conf	Mine: the misc block addition (2 *_enables_dpms lines + comment), and the TV mode 119.88 → 60.00 with its comment. The $ultrawide/$tv desc: vars, the catch-all monitor = , preferred, auto, 1, and bitdepth/brightness values are yours.
Not in git — systemd masks I created:
~/.config/systemd/user/hypridle.service -> /dev/null
~/.config/systemd/user/swayidle.service -> /dev/null
~/.config/systemd/user/idlehack.service -> /dev/null
~/.config/systemd/user/wluma.service   -> /dev/null
Undo all four:
systemctl --user unmask hypridle.service swayidle.service idlehack.service wluma.service
Revert my config edits: git diff hypr/ then git checkout -- hypr/hyprland.conf. Do not blanket-revert hypridle.conf — HEAD is a 23-line stub, you'd lose the Sep 19 work again (see below).
