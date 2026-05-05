use anyhow::{Context, Result};
use serde_json::Value;
use std::path::{Path, PathBuf};

/// Known locations where Lutris/Wine might place the Battle.net prefix.
const KNOWN_PREFIX_PATHS: &[&str] = &[
    "Games/battlenet",
    "Games/battle-net",
    "Games/Battle.net",
    ".wine",
    ".local/share/lutris/runners/wine/prefix",
];

const BNET_CONFIG_FILENAME: &str = "Battle.net.config";
const BNET_APPDATA_REL: &str = "AppData/Roaming/Battle.net";

/// Represents the location of a discovered Battle.net installation.
#[derive(Debug, Clone)]
pub struct BnetInstall {
    /// Path to the Wine prefix root.
    pub prefix: PathBuf,
    /// Full path to Battle.net.config.
    pub config_path: PathBuf,
    /// Path to Battle.net.exe inside the prefix.
    pub exe_path: Option<PathBuf>,
}

/// Try to find Battle.net.config files inside a Wine prefix.
/// Searches drive_c/users/*/AppData/Roaming/Battle.net/Battle.net.config
fn find_config_in_prefix(prefix: &Path) -> Option<PathBuf> {
    let users_dir = prefix.join("drive_c/users");
    if !users_dir.is_dir() {
        return None;
    }
    let entries = std::fs::read_dir(&users_dir).ok()?;
    for entry in entries.flatten() {
        if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            continue;
        }
        let candidate = entry.path().join(BNET_APPDATA_REL).join(BNET_CONFIG_FILENAME);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Try to find Battle.net.exe inside a prefix.
fn find_exe_in_prefix(prefix: &Path) -> Option<PathBuf> {
    // Common install locations inside the prefix
    let candidates = [
        "drive_c/Program Files (x86)/Battle.net/Battle.net.exe",
        "drive_c/Program Files/Battle.net/Battle.net.exe",
        "drive_c/Program Files (x86)/Battle.net/Battle.net Launcher.exe",
    ];
    for c in &candidates {
        let p = prefix.join(c);
        if p.is_file() {
            return Some(p);
        }
    }
    None
}

/// Auto-detect Battle.net installations by scanning known prefix locations.
pub fn detect_installations() -> Vec<BnetInstall> {
    let mut installs = Vec::new();
    let home = match dirs::home_dir() {
        Some(h) => h,
        None => return installs,
    };

    for rel in KNOWN_PREFIX_PATHS {
        let prefix = home.join(rel);
        if !prefix.is_dir() {
            continue;
        }
        if let Some(config_path) = find_config_in_prefix(&prefix) {
            installs.push(BnetInstall {
                exe_path: find_exe_in_prefix(&prefix),
                prefix: prefix.clone(),
                config_path,
            });
        }
    }

    // Also scan ~/.local/share/lutris/runners/wine/ for any sub-prefixes
    let lutris_prefixes = home.join(".local/share/lutris/runners/wine");
    if lutris_prefixes.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&lutris_prefixes) {
            for entry in entries.flatten() {
                let prefix = entry.path();
                if prefix.is_dir() {
                    if let Some(config_path) = find_config_in_prefix(&prefix) {
                        installs.push(BnetInstall {
                            exe_path: find_exe_in_prefix(&prefix),
                            prefix,
                            config_path,
                        });
                    }
                }
            }
        }
    }

    // Also check the actual game directories managed by Lutris
    let lutris_pga = home.join(".local/share/lutris");
    if lutris_pga.is_dir() {
        // Lutris often puts prefixes in ~/Games/<game>/
        // We already check ~/Games/battlenet above, but let's also check
        // any directory under ~/Games/
        let games_dir = home.join("Games");
        if games_dir.is_dir() {
            if let Ok(entries) = std::fs::read_dir(&games_dir) {
                for entry in entries.flatten() {
                    let prefix = entry.path();
                    if prefix.is_dir() {
                        // Skip if we already found it
                        if installs.iter().any(|i| i.prefix == prefix) {
                            continue;
                        }
                        if let Some(config_path) = find_config_in_prefix(&prefix) {
                            installs.push(BnetInstall {
                                exe_path: find_exe_in_prefix(&prefix),
                                prefix,
                                config_path,
                            });
                        }
                    }
                }
            }
        }
    }

    installs
}

/// Read the SavedAccountNames from a Battle.net.config file.
pub fn read_saved_accounts(config_path: &Path) -> Result<Vec<String>> {
    let content = std::fs::read_to_string(config_path)
        .with_context(|| format!("Failed to read {}", config_path.display()))?;
    let json: Value = serde_json::from_str(&content)
        .with_context(|| format!("Failed to parse {} as JSON", config_path.display()))?;

    let saved = json
        .get("Client")
        .and_then(|c| c.get("SavedAccountNames"))
        .and_then(|s| s.as_str())
        .unwrap_or("");

    if saved.is_empty() {
        return Ok(Vec::new());
    }

    Ok(saved.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
}

/// Write the SavedAccountNames back, with the selected account first.
pub fn write_account_order(config_path: &Path, accounts: &[String]) -> Result<()> {
    let content = std::fs::read_to_string(config_path)
        .with_context(|| format!("Failed to read {}", config_path.display()))?;
    let mut json: Value = serde_json::from_str(&content)
        .with_context(|| format!("Failed to parse {}", config_path.display()))?;

    let new_value = accounts.join(",");

    // Navigate to Client.SavedAccountNames and set it
    let client = json
        .as_object_mut()
        .and_then(|o| o.get_mut("Client"))
        .and_then(|c| c.as_object_mut())
        .context("Battle.net.config missing Client object")?;

    client.insert(
        "SavedAccountNames".to_string(),
        Value::String(new_value),
    );

    // Write back with a backup
    let backup_path = config_path.with_extension("config.bak");
    std::fs::copy(config_path, &backup_path)
        .with_context(|| format!("Failed to create backup at {}", backup_path.display()))?;

    let output = serde_json::to_string_pretty(&json)?;
    std::fs::write(config_path, output)
        .with_context(|| format!("Failed to write {}", config_path.display()))?;

    Ok(())
}

/// Reorder accounts so the selected email is first.
pub fn reorder_accounts(accounts: &[String], selected_email: &str) -> Vec<String> {
    let mut result = vec![selected_email.to_string()];
    for a in accounts {
        if a != selected_email {
            result.push(a.clone());
        }
    }
    result
}

/// Path to Battle.net's CachedData.db inside a Wine prefix.
/// This SQLite database contains the `login_cache` table with BattleTags
/// for accounts that have logged in through this Battle.net install.
fn cached_data_db_path(prefix: &Path) -> Option<PathBuf> {
    let users_dir = prefix.join("drive_c/users");
    if !users_dir.is_dir() {
        return None;
    }
    let entries = std::fs::read_dir(&users_dir).ok()?;
    for entry in entries.flatten() {
        if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            continue;
        }
        let candidate = entry
            .path()
            .join("AppData/Local/Battle.net/CachedData.db");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Read the most recently logged-in BattleTag from Battle.net's local cache.
/// Returns the BattleTag (e.g., "PlayerName#1234") of the highest-ROWID entry
/// in `login_cache`, which corresponds to the most recently authenticated
/// account.
///
/// We shell out to `sqlite3` rather than linking a SQLite library to keep
/// the binary lean. The `sqlite3` CLI is widely available on Linux.
pub fn read_most_recent_battletag(prefix: &Path) -> Option<String> {
    let db = cached_data_db_path(prefix)?;
    let output = std::process::Command::new("sqlite3")
        .arg(&db)
        .arg("SELECT battle_tag FROM login_cache ORDER BY ROWID DESC LIMIT 1;")
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let tag = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if tag.is_empty() {
        None
    } else {
        Some(tag)
    }
}

/// Read all BattleTags from the local cache, ordered by recency (most recent first).
/// Useful when multiple accounts have been logged into.
#[allow(dead_code)]
pub fn read_all_battletags(prefix: &Path) -> Vec<String> {
    let db = match cached_data_db_path(prefix) {
        Some(p) => p,
        None => return Vec::new(),
    };
    let output = match std::process::Command::new("sqlite3")
        .arg(&db)
        .arg("SELECT battle_tag FROM login_cache ORDER BY ROWID DESC;")
        .output()
    {
        Ok(o) if o.status.success() => o,
        _ => return Vec::new(),
    };
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect()
}

/// Count of distinct accounts known to Battle.net's local login cache.
/// Used by bnetswitch to detect when SavedAccountNames has been trimmed
/// below the set of accounts Battle.net itself remembers (which happens
/// when the user logs out via Battle.net's native UI).
pub fn login_cache_count(prefix: &Path) -> usize {
    read_all_battletags(prefix).len()
}
