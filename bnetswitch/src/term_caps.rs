//! Terminal capability detection for rendering richer content (images,
//! 24-bit color, etc.) when the host terminal supports it.
//!
//! ## Why bother
//!
//! Different terminals support different graphics protocols. The TUI
//! renders OW rank icons inline in the LFG view; on Kitty / Ghostty /
//! WezTerm we use the Kitty graphics protocol for crisp PNG rendering,
//! on Alacritty / generic xterm we fall back to a Unicode tier glyph
//! plus a 24-bit color highlight that conveys the same information at
//! lower fidelity.
//!
//! ## Detection strategy
//!
//! We use a layered approach, cheapest checks first:
//!
//!   1. Environment-variable signatures (KITTY_WINDOW_ID, TERM_PROGRAM,
//!      WEZTERM_EXECUTABLE, etc.) — instant, no I/O.
//!   2. TERM string heuristics ("xterm-kitty", "foot", "wezterm").
//!   3. Outer-terminal signatures preserved through tmux, such as
//!      GHOSTTY_RESOURCES_DIR. tmux replaces TERM and TERM_PROGRAM in panes.
//!
//! No active terminal probe: reading query responses from stdin can steal
//! keyboard input from the TUI, especially through tmux.
//!
//! ## tmux passthrough
//!
//! When running under tmux, graphics escape sequences need wrapping in
//! tmux's passthrough envelope. We detect tmux via $TMUX and signal
//! that to ratatui-image; the rendering path adds the wrapping. The
//! user must have `set -g allow-passthrough on` in their tmux.conf for
//! this to work — that's a one-time config, documented for the user.
//!
//! ## Why not just always use ratatui-image's auto-detect?
//!
//! ratatui-image's `Picker::from_query_stdio()` does similar detection,
//! but it's designed to be called once at startup and configures the
//! whole rendering pipeline. We want a richer answer — beyond "can I
//! render images", we also want to know:
//!   - Are we in tmux? (affects passthrough wrapping + asks user to
//!     configure tmux.conf if not)
//!   - Do we have a TTY at all? (lfg-server headless mode has no TTY)
//!   - Should we degrade gracefully even if Picker says yes? (some
//!     environments report supported but render garbage; the user can
//!     opt out via env var BNETSWITCH_NO_GRAPHICS=1)

use std::env;

/// Inline-image protocol the active terminal speaks, if any.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GraphicsProto {
    /// Kitty graphics protocol — used by Kitty, Ghostty, WezTerm,
    /// recent Konsole. Highest fidelity, supports placement IDs for
    /// efficient repainting.
    Kitty,
    /// Sixel — used by foot (with `-g`/`--sixel`), recent xterm with
    /// `--enable-sixel-graphics`, mlterm, iTerm2 (partial). Pixel-grid
    /// based, lower fidelity than Kitty but more widely supported.
    Sixel,
    /// iTerm2's proprietary inline-image escape. macOS-only.
    ITerm2,
    /// No supported protocol — fall back to Unicode glyph rendering.
    None,
}

/// Snapshot of terminal capability, captured once at TUI startup.
/// Cheap to copy by-value (just an enum + two bools).
#[derive(Debug, Clone, Copy)]
pub struct TermCaps {
    pub graphics: GraphicsProto,
    pub in_tmux: bool,
    /// True when we have a real TTY on stdout. False in headless modes
    /// (lfg-server, lfg-backtest) where we shouldn't try to render anything.
    pub has_tty: bool,
}

impl TermCaps {
    /// Detect once. Safe to call before raw-mode setup; doesn't touch
    /// the terminal beyond reading env vars.
    pub fn detect() -> Self {
        Self::from_env(|name| env::var(name).ok(), is_tty())
    }

    fn from_env(lookup: impl Fn(&str) -> Option<String>, has_tty: bool) -> Self {
        Self {
            graphics: detect_graphics(&lookup),
            in_tmux: lookup("TMUX").is_some(),
            has_tty,
        }
    }

    /// True if we should attempt image rendering at all. Graphics
    /// protocols require both a supporting terminal AND a TTY (you
    /// can't pipe escape sequences to a file).
    pub fn supports_images(&self) -> bool {
        self.has_tty && !matches!(self.graphics, GraphicsProto::None)
    }

    /// Short human-readable summary for diagnostic logging.
    pub fn summary(&self) -> String {
        let proto = match self.graphics {
            GraphicsProto::Kitty => "kitty-graphics",
            GraphicsProto::Sixel => "sixel",
            GraphicsProto::ITerm2 => "iterm2",
            GraphicsProto::None => "no-graphics",
        };
        let tmux = if self.in_tmux { ", tmux" } else { "" };
        let tty = if self.has_tty { "" } else { ", no-tty" };
        format!("{}{}{}", proto, tmux, tty)
    }
}

/// Cheap signature-based detection. Order matters: more specific signals
/// first, fallthroughs last.
fn detect_graphics(lookup: &impl Fn(&str) -> Option<String>) -> GraphicsProto {
    if lookup("BNETSWITCH_NO_GRAPHICS").as_deref() == Some("1") {
        return GraphicsProto::None;
    }
    let present = |name| lookup(name).is_some_and(|value| !value.is_empty());
    let term_program = lookup("TERM_PROGRAM").unwrap_or_default();
    // Explicit terminal identity wins over potentially inherited hints.
    match term_program.as_str() {
        "ghostty" | "WezTerm" => return GraphicsProto::Kitty,
        "iTerm.app" => return GraphicsProto::ITerm2,
        "Apple_Terminal" | "Alacritty" | "alacritty" => return GraphicsProto::None,
        _ => {}
    }

    // Kitty itself sets KITTY_WINDOW_ID and TERM=xterm-kitty.
    if present("KITTY_WINDOW_ID") {
        return GraphicsProto::Kitty;
    }
    let term = lookup("TERM").unwrap_or_default();
    if term == "xterm-kitty" || term.starts_with("xterm-ghostty") {
        return GraphicsProto::Kitty;
    }

    // tmux sets TERM=tmux-256color and TERM_PROGRAM=tmux even when its
    // session environment contains TERM_PROGRAM=ghostty. Ghostty's resource
    // and binary directories survive in pane environments and identify the
    // outer terminal without querying stdin or changing tmux's TERM.
    if (term_program.is_empty() || term_program == "tmux")
        && (present("GHOSTTY_RESOURCES_DIR") || present("GHOSTTY_BIN_DIR"))
    {
        return GraphicsProto::Kitty;
    }

    // foot supports Sixel when launched with the right flag.
    // Hard to know flag state from env alone; assume it does and fall
    // back gracefully if rendering fails.
    if term == "foot" || term.starts_with("foot-") {
        return GraphicsProto::Sixel;
    }

    // Konsole 22.04+ supports Kitty graphics. KONSOLE_VERSION env may
    // hint, but absent that, TERM=xterm-256color tells us nothing.
    if present("KONSOLE_VERSION") {
        return GraphicsProto::Kitty;
    }

    // Alacritty: explicitly does NOT support any image protocol.
    // ALACRITTY_LOG / ALACRITTY_WINDOW_ID env vars set when running.
    if present("ALACRITTY_LOG") || present("ALACRITTY_WINDOW_ID") {
        return GraphicsProto::None;
    }

    // We could do an active probe here (send graphics query, parse
    // response with timeout). It's unreliable in tmux without
    // passthrough configured, and it costs a stdin read in raw mode.
    // Unknown terminal signatures use the Unicode fallback.
    GraphicsProto::None
}

fn is_tty() -> bool {
    use std::io::IsTerminal;
    std::io::stdout().is_terminal()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Detection results are env-dependent; the test just confirms
    /// `detect()` returns SOMETHING without panicking. Real coverage
    /// happens via manual testing in each terminal.
    #[test]
    fn detect_does_not_panic() {
        let caps = TermCaps::detect();
        let _ = caps.summary();
        let _ = caps.supports_images();
    }

    fn caps_for(vars: &[(&str, &str)], has_tty: bool) -> TermCaps {
        TermCaps::from_env(
            |name| {
                vars.iter()
                    .find(|(key, _)| *key == name)
                    .map(|(_, value)| value.to_string())
            },
            has_tty,
        )
    }

    #[test]
    fn ghostty_inside_tmux_uses_preserved_resource_signature() {
        let caps = caps_for(
            &[
                ("TERM", "tmux-256color"),
                ("TERM_PROGRAM", "tmux"),
                ("TMUX", "/tmp/tmux-1000/default,5316,2"),
                ("GHOSTTY_RESOURCES_DIR", "/usr/share/ghostty"),
                ("GHOSTTY_BIN_DIR", "/usr/bin"),
            ],
            true,
        );
        assert_eq!(caps.graphics, GraphicsProto::Kitty);
        assert!(caps.in_tmux);
        assert!(caps.supports_images());
        assert_eq!(caps.summary(), "kitty-graphics, tmux");
    }

    #[test]
    fn ghostty_bin_signature_and_direct_terminal_identity_are_supported() {
        assert_eq!(
            caps_for(
                &[("TERM_PROGRAM", "tmux"), ("GHOSTTY_BIN_DIR", "/usr/bin")],
                true
            )
            .graphics,
            GraphicsProto::Kitty
        );
        assert_eq!(
            caps_for(&[("TERM_PROGRAM", "ghostty")], true).graphics,
            GraphicsProto::Kitty
        );
        assert_eq!(
            caps_for(&[("TERM", "xterm-ghostty")], true).graphics,
            GraphicsProto::Kitty
        );
    }

    #[test]
    fn unknown_tmux_and_empty_signatures_do_not_claim_graphics_support() {
        let caps = caps_for(
            &[
                ("TERM", "tmux-256color"),
                ("TERM_PROGRAM", "tmux"),
                ("GHOSTTY_RESOURCES_DIR", ""),
                ("GHOSTTY_BIN_DIR", ""),
            ],
            true,
        );
        assert_eq!(caps.graphics, GraphicsProto::None);
        assert!(!caps.supports_images());
    }

    #[test]
    fn explicit_unsupported_terminal_overrides_inherited_ghostty_signature() {
        let caps = caps_for(
            &[
                ("TERM_PROGRAM", "Alacritty"),
                ("GHOSTTY_RESOURCES_DIR", "/usr/share/ghostty"),
            ],
            true,
        );
        assert_eq!(caps.graphics, GraphicsProto::None);
    }

    #[test]
    fn piped_output_still_disables_images() {
        let caps = caps_for(
            &[
                ("TERM_PROGRAM", "tmux"),
                ("GHOSTTY_RESOURCES_DIR", "/usr/share/ghostty"),
            ],
            false,
        );
        assert_eq!(caps.graphics, GraphicsProto::Kitty);
        assert!(!caps.supports_images());
    }

    /// Test without mutating process-wide environment shared by parallel tests.
    #[test]
    fn opt_out_env_disables_graphics() {
        let caps = caps_for(
            &[
                ("BNETSWITCH_NO_GRAPHICS", "1"),
                ("TERM_PROGRAM", "ghostty"),
                ("GHOSTTY_RESOURCES_DIR", "/usr/share/ghostty"),
            ],
            true,
        );
        assert_eq!(caps.graphics, GraphicsProto::None);
        assert!(!caps.supports_images());
    }
}
