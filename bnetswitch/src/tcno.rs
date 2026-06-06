use anyhow::{Context, Result};
use serde_json::Value;
use std::path::{Path, PathBuf};

/// Common TCNO data locations on Windows. We accept either the AppData
/// root directory of TCNO or the `LoginCache/BattleNet` subdirectory directly.
const TCNO_RELATIVE_IDS: &str = "LoginCache/BattleNet/ids.json";

/// One imported account from TCNO.
#[derive(Debug, Clone)]
pub struct ImportedAccount {
    pub email: String,
    pub battletag: String,
}

/// Resolve a user-provided path to a TCNO `ids.json` file.
///
/// Accepts:
/// - The `ids.json` file directly
/// - The `LoginCache/BattleNet/` directory
/// - The TCNO root data directory (e.g., `Roaming/TcNo Account Switcher/`)
fn resolve_ids_path(input: &Path) -> Option<PathBuf> {
    if input.is_file() && input.file_name().map(|n| n == "ids.json").unwrap_or(false) {
        return Some(input.to_path_buf());
    }
    let candidate = input.join("ids.json");
    if candidate.is_file() {
        return Some(candidate);
    }
    let candidate = input.join(TCNO_RELATIVE_IDS);
    if candidate.is_file() {
        return Some(candidate);
    }
    None
}

/// Parse TCNO's `ids.json` into a list of (email, BattleTag) pairs.
///
/// The file is a flat JSON object keyed by email:
/// ```json
/// { "user@example.com": "PlayerName#1234", ... }
/// ```
pub fn import_from_path(path: &Path) -> Result<Vec<ImportedAccount>> {
    let ids_path = resolve_ids_path(path).with_context(|| {
        format!(
            "Could not locate TCNO ids.json under {}. Expected the file itself, \
             the LoginCache/BattleNet directory, or the TCNO root directory.",
            path.display()
        )
    })?;

    let content = std::fs::read_to_string(&ids_path)
        .with_context(|| format!("Failed to read {}", ids_path.display()))?;
    let json: Value = serde_json::from_str(&content)
        .with_context(|| format!("Failed to parse {} as JSON", ids_path.display()))?;

    let map = json
        .as_object()
        .context("TCNO ids.json must be a JSON object keyed by email")?;

    let mut accounts = Vec::with_capacity(map.len());
    for (email, tag) in map {
        if let Some(tag_str) = tag.as_str() {
            accounts.push(ImportedAccount {
                email: email.clone(),
                battletag: tag_str.to_string(),
            });
        }
    }
    Ok(accounts)
}
