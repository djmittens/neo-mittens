//! Lightweight parser for Wine's `user.reg` files.
//!
//! Wine stores HKEY_CURRENT_USER as a flat text file at
//! `<prefix>/pfx/user.reg` (Proton convention) or `<prefix>/user.reg`
//! (plain Wine). The format is roughly INI-like with `[Section\Path]`
//! headers and `"key"=value` pairs.
//!
//! We parse it for one purpose: find the timestamp of the
//! `Battle.net\Launch Options\<game>` section, which Battle.net writes
//! right before spawning a game. The timestamp tells us whether the
//! DPAPI-encrypted `WEB_TOKEN` blobs in that section are still likely
//! to be valid — i.e., whether we can do a "warm launch" of the game
//! by spawning it directly without going through Battle.net's UI.
//!
//! ## Format quick reference
//!
//! ```text
//! WINE REGISTRY Version 2
//! ;; All keys relative to \\User\\<sid>
//!
//! [Software\\Blizzard Entertainment\\Battle.net\\Launch Options\\Pro] 1777520860
//! #time=1dcd84979d3aaf1
//! "ACCOUNT"=hex:01,00,00,00,...
//! "ACCOUNT_TS"="1777520860"
//! "WEB_TOKEN"=hex:01,00,00,00,...
//! ```
//!
//! The integer after `[Section]` is a Wine-specific Unix timestamp
//! (seconds) of when the section was last written. We use this rather
//! than the `#time=` Win32 FILETIME value because it's simpler to
//! parse and has the same semantics for our use case.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// Find Wine's user.reg, supporting both Proton-style (`prefix/pfx/`)
/// and plain Wine layouts.
fn find_user_reg(prefix: &Path) -> Option<PathBuf> {
    let candidates = [
        prefix.join("pfx").join("user.reg"),
        prefix.join("user.reg"),
    ];
    candidates.into_iter().find(|p| p.is_file())
}

/// Parse the section timestamp for `Software\Blizzard Entertainment\Battle.net\Launch Options\<game_uid>`.
/// Returns the Unix epoch seconds the section was last written, or None
/// if the section doesn't exist.
///
/// `game_uid` is the Battle.net product code, e.g. "Pro" for Overwatch.
pub fn launch_options_timestamp(prefix: &Path, game_uid: &str) -> Result<Option<u64>> {
    let user_reg = find_user_reg(prefix).with_context(|| {
        format!("user.reg not found under {}", prefix.display())
    })?;
    let content = std::fs::read_to_string(&user_reg)
        .with_context(|| format!("reading {}", user_reg.display()))?;

    // Section header format Wine writes (verified by hexdump against
    // an actual user.reg file: bytes are 0x5c5c = `\\`, two literal
    // backslashes per separator):
    //
    //   [Software\\Blizzard Entertainment\\Battle.net\\Launch Options\\<game>] <unix_ts>
    //
    // Wine doubles backslashes in section paths in user.reg even though
    // they're single in registry-key strings — INI-style escape rules.
    // The `r"..."` raw string here means each `\\` is two literal
    // backslash characters, matching the file format.
    let target_section = format!(
        r"[Software\\Blizzard Entertainment\\Battle.net\\Launch Options\\{}]",
        game_uid
    );

    for line in content.lines() {
        if !line.starts_with(&target_section) {
            continue;
        }
        // Split off the timestamp suffix
        let after = &line[target_section.len()..];
        let ts_str = after.trim();
        if let Ok(ts) = ts_str.parse::<u64>() {
            return Ok(Some(ts));
        }
    }
    Ok(None)
}

/// Convenience: returns the age in seconds of the launch-options
/// section for the given game, or None if the section doesn't exist.
pub fn launch_options_age_secs(prefix: &Path, game_uid: &str) -> Result<Option<u64>> {
    let ts = match launch_options_timestamp(prefix, game_uid)? {
        Some(t) => t,
        None => return Ok(None),
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(ts);
    Ok(Some(now.saturating_sub(ts)))
}
