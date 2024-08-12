#!/usr/bin/env /usr/bin/python
import re
import sys
import subprocess as subp

# these are the physical dimensions of the monitor
# in millimeters, which i guess is used for dpi calculations
WIDTH_mm = 1190
HEIGHT_mm = 340

def xrandr(*args):
    args = list(args)
    args.insert(0, "xrandr")
    res = subp.run(args, capture_output=True)
    return str(res.stdout, "utf8")

monitors = re.findall(r"\s\d\:\s([^\s]+)\s.+", xrandr("--listactivemonitors"))
mon, width_px, height_px = re.findall(r"(\S+)\sconnected\sprimary\s(\w+)x(\w+)\+", xrandr())[0]

if __name__ == "__main__":
    print(mon, width_px, height_px)

    for m in monitors:
        print("Deleting user monitor: ", m)
        xrandr("--delmonitor", m)

    layout = sys.argv[1]

    if(layout == "dual"):
        print("Using dual layout")
        wp = int(width_px)  // 2
        hp = int(height_px)
        wm = WIDTH_mm // 2
        hm = HEIGHT_mm
        xrandr("--setmonitor", f"{mon}-1", f"{wp}/{wm}x{hp}/{hm}+0+0", mon)
        xrandr("--setmonitor", f"{mon}-2", f"{wp}/{wm}x{hp}/{hm}+{wp}+0", "none")
    elif(layout == "stardeck"):
        print("Using startdeck layout")
        wp = int(width_px)  // 2
        wps = wp // 2
        hp = int(height_px)
        wm = WIDTH_mm // 2
        wms = wm // 2
        hm = HEIGHT_mm
        xrandr("--setmonitor", f"{mon}-1", f"{wp}/{wm}x{hp}/{hm}+{wps}+0", mon)
        xrandr("--setmonitor", f"{mon}-2", f"{wps}/{wms}x{hp}/{hm}+{wps + wp}+0", "none")
        xrandr("--setmonitor", f"{mon}-3", f"{wps}/{wms}x{hp}/{hm}+0+0", "none")
    else:
        print(f"Unknown layout {layout}, clearing display")
