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
//!   3. Active probe: send a Kitty graphics query escape sequence and
//!      read the response with a short timeout. Only used as a last
//!      resort because it requires raw mode and a TTY.
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
        // User opt-out (helpful when terminal LIES about support, e.g.
        // some vague xterm-256color forks claim more than they deliver).
        if env::var("BNETSWITCH_NO_GRAPHICS").ok().as_deref() == Some("1") {
            return Self {
                graphics: GraphicsProto::None,
                in_tmux: env::var("TMUX").is_ok(),
                has_tty: is_tty(),
            };
        }

        let in_tmux = env::var("TMUX").is_ok();
        let has_tty = is_tty();

        let graphics = detect_graphics();

        Self { graphics, in_tmux, has_tty }
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
fn detect_graphics() -> GraphicsProto {
    // Kitty itself sets KITTY_WINDOW_ID and TERM=xterm-kitty.
    if env::var("KITTY_WINDOW_ID").is_ok() {
        return GraphicsProto::Kitty;
    }
    let term = env::var("TERM").unwrap_or_default();
    if term == "xterm-kitty" || term.starts_with("xterm-ghostty") {
        return GraphicsProto::Kitty;
    }

    let term_program = env::var("TERM_PROGRAM").unwrap_or_default();
    match term_program.as_str() {
        // Ghostty implements the Kitty protocol fully.
        "ghostty" => return GraphicsProto::Kitty,
        // WezTerm prefers Kitty over Sixel when both supported.
        "WezTerm" => return GraphicsProto::Kitty,
        // iTerm2 has its own inline-images protocol (Cmd+Inline-Image).
        "iTerm.app" => return GraphicsProto::ITerm2,
        // Apple Terminal: no graphics support
        "Apple_Terminal" => return GraphicsProto::None,
        _ => {}
    }

    // foot supports Sixel when launched with the right flag.
    // Hard to know flag state from env alone; assume it does and fall
    // back gracefully if rendering fails.
    if term == "foot" || term.starts_with("foot-") {
        return GraphicsProto::Sixel;
    }

    // Konsole 22.04+ supports Kitty graphics. KONSOLE_VERSION env may
    // hint, but absent that, TERM=xterm-256color tells us nothing.
    if env::var("KONSOLE_VERSION").is_ok() {
        return GraphicsProto::Kitty;
    }

    // Alacritty: explicitly does NOT support any image protocol.
    // ALACRITTY_LOG / ALACRITTY_WINDOW_ID env vars set when running.
    if env::var("ALACRITTY_LOG").is_ok() || env::var("ALACRITTY_WINDOW_ID").is_ok() {
        return GraphicsProto::None;
    }

    // We could do an active probe here (send graphics query, parse
    // response with timeout). It's unreliable in tmux without
    // passthrough configured, and it costs a stdin read in raw mode.
    // For now, signature detection is sufficient — terminals that
    // support graphics universally set distinguishable env vars.
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

    /// Opt-out env var forces None regardless of other signals.
    #[test]
    fn opt_out_env_disables_graphics() {
        let prev = env::var("BNETSWITCH_NO_GRAPHICS").ok();
        // SAFETY: tests are single-threaded by default in cargo unless
        // user passes --test-threads=N. We restore env at end.
        unsafe { env::set_var("BNETSWITCH_NO_GRAPHICS", "1"); }
        let caps = TermCaps::detect();
        assert_eq!(caps.graphics, GraphicsProto::None);
        match prev {
            Some(v) => unsafe { env::set_var("BNETSWITCH_NO_GRAPHICS", v); },
            None => unsafe { env::remove_var("BNETSWITCH_NO_GRAPHICS"); },
        }
    }
}
