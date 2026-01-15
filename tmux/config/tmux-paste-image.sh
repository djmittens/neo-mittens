#!/bin/bash

# Paste from system clipboard with special handling for images.
# If the clipboard contains an image, save it to /tmp/images/ and paste a reference.
# Otherwise, paste the text content directly.
# Supports: macOS, Wayland, X11

IMAGES_DIR="/tmp/images"
mkdir -p "$IMAGES_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="clipboard_${TIMESTAMP}.png"
FILEPATH="${IMAGES_DIR}/${FILENAME}"

# Detect platform and try to save image from clipboard
save_image() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - use pngpaste (check common install locations)
        local pngpaste_cmd=""
        if command -v pngpaste &>/dev/null; then
            pngpaste_cmd="pngpaste"
        elif [[ -x /opt/homebrew/bin/pngpaste ]]; then
            pngpaste_cmd="/opt/homebrew/bin/pngpaste"
        elif [[ -x /usr/local/bin/pngpaste ]]; then
            pngpaste_cmd="/usr/local/bin/pngpaste"
        else
            return 1
        fi
        "$pngpaste_cmd" "$FILEPATH" 2>/dev/null
    elif [[ -n "$WAYLAND_DISPLAY" ]]; then
        # Wayland - use wl-paste
        if command -v wl-paste &>/dev/null; then
            local mime_types
            mime_types=$(wl-paste --list-types 2>/dev/null)
            if echo "$mime_types" | grep -q "image/png"; then
                wl-paste --type image/png > "$FILEPATH" 2>/dev/null
            elif echo "$mime_types" | grep -q "image/"; then
                # Convert other image formats to png
                wl-paste --type image/jpeg 2>/dev/null | convert - png:"$FILEPATH" 2>/dev/null || return 1
            else
                return 1
            fi
        else
            return 1
        fi
    elif [[ -n "$DISPLAY" ]]; then
        # X11 - use xclip
        if command -v xclip &>/dev/null; then
            local targets
            targets=$(xclip -selection clipboard -t TARGETS -o 2>/dev/null)
            if echo "$targets" | grep -q "image/png"; then
                xclip -selection clipboard -t image/png -o > "$FILEPATH" 2>/dev/null
            elif echo "$targets" | grep -q "image/"; then
                xclip -selection clipboard -t image/jpeg -o 2>/dev/null | convert - png:"$FILEPATH" 2>/dev/null || return 1
            else
                return 1
            fi
        else
            return 1
        fi
    else
        return 1
    fi
}

# Paste text from clipboard
paste_text() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        pbpaste
    elif [[ -n "$WAYLAND_DISPLAY" ]]; then
        wl-paste --no-newline 2>/dev/null
    elif [[ -n "$DISPLAY" ]]; then
        xclip -selection clipboard -o 2>/dev/null
    fi
}

# Try to save image, if successful output reference, otherwise paste text
if save_image && [[ -s "$FILEPATH" ]]; then
    echo "look at ${FILEPATH}"
else
    rm -f "$FILEPATH" 2>/dev/null
    paste_text
fi
