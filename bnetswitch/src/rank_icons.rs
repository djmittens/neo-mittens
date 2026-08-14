//! OW rank-tier icon rendering for the LFG TUI view.
//!
//! Two rendering paths share this module:
//!   1. **Phase 1 (Unicode fallback)** — implemented in `lfg_parse::Tier::glyph()`
//!      and `Tier::color_rgb()`. Used when the terminal can't render
//!      images (Alacritty, plain xterm, no-TTY mode).
//!   2. **Phase 2 (real PNGs)** — this module. Used when `term_caps`
//!      reports a supported graphics protocol. Embeds 8 PNGs at compile
//!      time via `include_bytes!()` and renders them inline at the
//!      requested cell location through ratatui-image's `Picker`.
//!
//! ## Why pre-decode at startup
//!
//! ratatui re-renders every frame. Decoding a PNG per frame would burn
//! CPU and cause flicker. We decode all 8 tier icons once at startup
//! and keep them in `RankIcons::loaded` — a static-lifetime cache the
//! TUI clones cheap references out of.
//!
//! ## Rendering model
//!
//! ratatui-image draws into a `Rect`. For inline use in a list, we:
//!   1. Render the list normally with TEXT placeholders for icons
//!      (so layout/scrolling/highlighting all work).
//!   2. After the list is drawn, walk the visible rows, compute the
//!      icon Rect for each visible row, and render the matching tier
//!      icon ON TOP of the placeholder area.
//!
//! Kitty graphics protocol uses placement IDs — the same image at the
//! same cell location reuses the existing placement instead of
//! re-uploading bytes, so this is cheap on each frame.

use anyhow::{Context, Result};
use image::DynamicImage;
use ratatui_image::picker::Picker;
use ratatui_image::protocol::Protocol;
use ratatui_image::{Image, Resize};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::widgets::Widget;

use crate::lfg_parse::{Tier, TIER_COUNT};
use crate::term_caps::TermCaps;

// ============================================================================
// Embedded PNG bytes (compiled into the binary)
// ============================================================================

/// Tier icons embedded at compile time. Source: HaruChanHeart/OW2RankPack
/// (CC-licensed OW2 stream-overlay pack), processed to ~64x58 PNGs of
/// just the badge area — except Emerald, which the pack predates. See
/// `assets/ranks/` for the source files.
///
/// Embedding keeps the binary self-contained — no asset directory to
/// ship alongside — at the cost of ~50KB of binary size (negligible).
const ICON_BRONZE:      &[u8] = include_bytes!("../assets/ranks/bronze.png");
const ICON_SILVER:      &[u8] = include_bytes!("../assets/ranks/silver.png");
const ICON_GOLD:        &[u8] = include_bytes!("../assets/ranks/gold.png");
const ICON_PLATINUM:    &[u8] = include_bytes!("../assets/ranks/platinum.png");
/// Emerald postdates the icon pack, so this one was keyed out of an
/// in-game rank screenshot (background removed, cropped and scaled to
/// match the pack's 80px-tall framing).
const ICON_EMERALD:     &[u8] = include_bytes!("../assets/ranks/emerald.png");
const ICON_DIAMOND:     &[u8] = include_bytes!("../assets/ranks/diamond.png");
const ICON_MASTER:      &[u8] = include_bytes!("../assets/ranks/master.png");
const ICON_GRANDMASTER: &[u8] = include_bytes!("../assets/ranks/grandmaster.png");
const ICON_CHAMPION:    &[u8] = include_bytes!("../assets/ranks/champion.png");

/// PNG for a tier, or `None` when we don't have artwork for it yet.
///
/// `None` is a supported state, not an error: the renderer skips the
/// overlay and the Unicode glyph the list already drew underneath (see
/// `Tier::glyph`) shows through. That's the fallback for any future tier
/// Blizzard adds before we have a badge for it.
fn icon_bytes(tier: Tier) -> Option<&'static [u8]> {
    Some(match tier {
        Tier::Bronze      => ICON_BRONZE,
        Tier::Silver      => ICON_SILVER,
        Tier::Gold        => ICON_GOLD,
        Tier::Platinum    => ICON_PLATINUM,
        Tier::Emerald     => ICON_EMERALD,
        Tier::Diamond     => ICON_DIAMOND,
        Tier::Master      => ICON_MASTER,
        Tier::Grandmaster => ICON_GRANDMASTER,
        Tier::Champion    => ICON_CHAMPION,
    })
}

/// Every tier, in ladder order. Index into this is the index into
/// `RankIcons::protos`.
const ALL_TIERS: [Tier; TIER_COUNT] = [
    Tier::Bronze,
    Tier::Silver,
    Tier::Gold,
    Tier::Platinum,
    Tier::Emerald,
    Tier::Diamond,
    Tier::Master,
    Tier::Grandmaster,
    Tier::Champion,
];

// ============================================================================
// RankIcons: app-state-owned icon set
// ============================================================================

/// Loaded + protocol-prepared rank icons, ready to render. Owned by
/// `App`. Construction is fallible (Picker init can fail in odd
/// terminals); on failure, the field stays None and the TUI uses
/// Phase 1 Unicode fallback rendering everywhere.
pub struct RankIcons {
    /// One Protocol per tier. Pre-built so render is just a draw call.
    /// `None` element means decode failed for that tier (we still ship,
    /// other tiers will render correctly).
    protos: [Option<Protocol>; TIER_COUNT],
    /// Width/height in font cells the icon occupies. 2 cells wide, 1
    /// cell tall fits inside our two-line LFG row design without
    /// expanding row height.
    cell_w: u16,
    cell_h: u16,
}

impl RankIcons {
    /// Initialize the icon set for a graphics-capable terminal.
    /// Returns Ok(None) if the terminal doesn't support graphics; the
    /// caller should use Unicode fallback in that case.
    pub fn try_new(caps: &TermCaps) -> Result<Option<Self>> {
        if !caps.supports_images() {
            return Ok(None);
        }

        // Picker reads font cell dimensions (pixels per cell) so it can
        // size images correctly. `from_query_stdio()` does several
        // things in one call:
        //   1. Detects tmux via $TERM / $TERM_PROGRAM and runs
        //      `tmux set -p allow-passthrough on` so escapes traverse
        //      to the outer terminal.
        //   2. Detects outer terminal via env hints (KITTY_WINDOW_ID,
        //      ITERM_SESSION_ID, WEZTERM_EXECUTABLE).
        //   3. Sends a graphics capability query through tmux
        //      passthrough (when in tmux) and parses the response.
        //   4. Reads font cell size from the same query.
        //
        // We do NOT fall back to Picker::from_fontsize() on error --
        // that constructor produces a Picker with is_tmux=false, which
        // breaks rendering inside tmux+kitty (escapes leak as raw
        // text). If the query fails, we report the error to the
        // caller, which records the failure and falls back to the
        // Unicode glyph path.
        let picker = Picker::from_query_stdio()
            .map_err(|e| anyhow::anyhow!("Picker::from_query_stdio failed: {:?}", e))?;

        // Decode the tier PNGs into protocols sized for our 2x1 cell
        // area. Each protocol caches the encoded image bytes; render is
        // cheap. Tiers without artwork stay None and fall back to the
        // Unicode glyph.
        const CELL_W: u16 = 2;
        const CELL_H: u16 = 1;
        let mut protos: [Option<Protocol>; TIER_COUNT] = Default::default();
        for (i, tier) in ALL_TIERS.iter().enumerate() {
            let Some(bytes) = icon_bytes(*tier) else { continue };
            match decode(bytes) {
                Ok(img) => {
                    // Build a non-resizing Protocol at the target cell
                    // area. We use Resize::Fit so the icon scales to fit
                    // the 2x1 cell box while preserving aspect ratio
                    // (the source is 64x58, roughly square).
                    let area = Rect::new(0, 0, CELL_W, CELL_H);
                    match picker.new_protocol(img, area, Resize::Fit(None)) {
                        Ok(p) => protos[i] = Some(p),
                        Err(e) => eprintln!(
                            "[bnetswitch] could not build protocol for {:?}: {}",
                            tier, e
                        ),
                    }
                }
                Err(e) => eprintln!(
                    "[bnetswitch] could not decode embedded icon for {:?}: {}",
                    tier, e
                ),
            }
        }

        Ok(Some(RankIcons {
            protos,
            cell_w: CELL_W,
            cell_h: CELL_H,
        }))
    }

    /// Cell-area footprint of one rank icon. Render code uses this to
    /// reserve space before drawing.
    pub fn cell_size(&self) -> (u16, u16) {
        (self.cell_w, self.cell_h)
    }

    /// Render the icon for `tier` at `area`. No-op if the protocol
    /// for that tier failed to build at startup (silent fallback —
    /// the placeholder text underneath will show through).
    pub fn render(&self, tier: Tier, area: Rect, buf: &mut Buffer) {
        let idx = tier_index(tier);
        if let Some(proto) = &self.protos[idx] {
            // Image widget renders the protocol into the buffer at area.
            // For Kitty graphics, this writes a placement command; the
            // actual pixels live in the terminal's image store keyed by
            // the protocol's image ID.
            let widget = Image::new(proto);
            widget.render(area, buf);
        }
    }
}

fn tier_index(t: Tier) -> usize {
    match t {
        Tier::Bronze      => 0,
        Tier::Silver      => 1,
        Tier::Gold        => 2,
        Tier::Platinum    => 3,
        Tier::Emerald     => 4,
        Tier::Diamond     => 5,
        Tier::Master      => 6,
        Tier::Grandmaster => 7,
        Tier::Champion    => 8,
    }
}

fn decode(bytes: &[u8]) -> Result<DynamicImage> {
    image::load_from_memory(bytes).context("png decode")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Sanity-check that every embedded PNG decodes. This catches
    /// build-time asset corruption (e.g., someone overwrites the PNG
    /// with garbage). Tiers with no artwork are skipped, not failed.
    #[test]
    fn all_tier_icons_decode() {
        for tier in ALL_TIERS {
            let Some(bytes) = icon_bytes(tier) else { continue };
            assert!(bytes.len() > 100, "{:?} icon suspiciously short", tier);
            decode(bytes).unwrap_or_else(|e| panic!("{:?} decode failed: {}", tier, e));
        }
    }

    /// `tier_index` must agree with the position in `ALL_TIERS`, or
    /// icons render against the wrong tier.
    #[test]
    fn tier_index_matches_all_tiers_order() {
        for (i, tier) in ALL_TIERS.iter().enumerate() {
            assert_eq!(tier_index(*tier), i, "index mismatch for {:?}", tier);
        }
    }
}
