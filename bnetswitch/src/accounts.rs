use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Per-account metadata stored by bnetswitch.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountMeta {
    /// User-friendly nickname (e.g., "Main", "Alt DPS", "Tank Smurf")
    #[serde(default)]
    pub nickname: Option<String>,
    /// BattleTag if known (e.g., "Player#1234")
    #[serde(default)]
    pub battletag: Option<String>,
}

/// The bnetswitch config file that stores account metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// Path to the Wine prefix (if manually set).
    #[serde(default)]
    pub wine_prefix: Option<String>,
    /// Whether to launch via Lutris.
    #[serde(default = "default_true")]
    pub use_lutris: bool,
    /// Whether to auto-launch Battle.net after switching.
    #[serde(default = "default_true")]
    pub auto_launch: bool,
    /// Account metadata keyed by email.
    #[serde(default)]
    pub accounts: HashMap<String, AccountMeta>,
    /// Emails temporarily removed from Battle.net.config during an
    /// "Add New Account" workflow. When the user finishes logging in
    /// and presses Save Current, these get merged back along with the
    /// newly added account.
    #[serde(default)]
    pub pending_merge_emails: Vec<String>,
    /// Safety snapshot of SavedAccountNames taken at the moment `add_new_account`
    /// clears the list. If `save_current` produces a shorter merged list than
    /// this snapshot, something went wrong (Battle.net didn't fully restore,
    /// user pressed `s` too early, etc.) and we use the snapshot as the floor.
    /// Cleared alongside `pending_merge_emails` on successful save.
    #[serde(default)]
    pub pending_snapshot_emails: Vec<String>,
    /// Maximum age in seconds of the Wine registry's `Launch Options\Pro`
    /// section for which we'll attempt a "warm launch" (spawn OW directly
    /// using the existing Battle.net-written auth tokens rather than
    /// asking Battle.net to relaunch via UI).
    ///
    /// Default: 4 hours. Bigger = more direct launches but higher risk
    /// of stale tokens causing OW to bounce to the login screen anyway.
    #[serde(default = "default_warm_launch_ttl")]
    pub warm_launch_ttl_secs: u64,

    /// Discord guild IDs to push the active account's BattleTag to as a
    /// per-server nickname when accounts switch. Empty = nickname sync
    /// disabled. Multiple guilds = sync to all of them.
    ///
    /// To find a guild ID: enable Discord Developer Mode (Settings →
    /// Advanced), right-click the server icon → "Copy Server ID".
    #[serde(default)]
    pub discord_nickname_sync_guilds: Vec<String>,

    /// LFG messages older than this (in seconds) are hidden from the
    /// TUI's LFG view. Most LFG groups fill within 5-10 min; older
    /// entries are usually stale. Set to a very large value to disable
    /// the filter.
    #[serde(default = "default_lfg_stale_secs")]
    pub lfg_stale_threshold_secs: u64,

    /// When true, only the most recent LFG embed per author is shown.
    /// Hides spam from people posting repeatedly. False = show all.
    #[serde(default = "default_true")]
    pub lfg_dedupe_by_author: bool,

    /// When true, only the most recent LFG embed per voice channel is
    /// shown. Multiple people from the same group often post separately
    /// for the same VC; this collapses them into one row. False = show
    /// all.
    #[serde(default = "default_true")]
    pub lfg_dedupe_by_voice_channel: bool,
}

fn default_lfg_stale_secs() -> u64 {
    10 * 60 // 10 minutes
}

fn default_warm_launch_ttl() -> u64 {
    4 * 60 * 60 // 4 hours
}

fn default_true() -> bool {
    true
}

impl Default for AppConfig {
    fn default() -> Self {
        // Match the serde defaults so behavior is consistent whether the
        // config file is missing or merely missing fields.
        Self {
            wine_prefix: None,
            use_lutris: true,
            auto_launch: true,
            accounts: HashMap::new(),
            pending_merge_emails: Vec::new(),
            pending_snapshot_emails: Vec::new(),
            warm_launch_ttl_secs: default_warm_launch_ttl(),
            discord_nickname_sync_guilds: Vec::new(),
            lfg_stale_threshold_secs: default_lfg_stale_secs(),
            lfg_dedupe_by_author: true,
            lfg_dedupe_by_voice_channel: true,
        }
    }
}

impl AppConfig {
    /// Get the config file path.
    pub fn config_path() -> Result<PathBuf> {
        let config_dir = dirs::config_dir()
            .context("Could not determine config directory")?;
        let app_dir = config_dir.join("bnetswitch");
        std::fs::create_dir_all(&app_dir)
            .with_context(|| format!("Failed to create config dir {}", app_dir.display()))?;
        Ok(app_dir.join("config.toml"))
    }

    /// Load config from disk, or return default.
    pub fn load() -> Result<Self> {
        let path = Self::config_path()?;
        if !path.exists() {
            return Ok(Self::default());
        }
        let content = std::fs::read_to_string(&path)
            .with_context(|| format!("Failed to read {}", path.display()))?;
        let config: Self = toml::from_str(&content)
            .with_context(|| format!("Failed to parse {}", path.display()))?;
        Ok(config)
    }

    /// Save config to disk.
    pub fn save(&self) -> Result<()> {
        let path = Self::config_path()?;
        let content = toml::to_string_pretty(self)
            .context("Failed to serialize config")?;
        std::fs::write(&path, content)
            .with_context(|| format!("Failed to write {}", path.display()))?;
        Ok(())
    }

    /// Get display name for an account (nickname > battletag > email).
    pub fn display_name(&self, email: &str) -> String {
        if let Some(meta) = self.accounts.get(email) {
            if let Some(nick) = &meta.nickname {
                return format!("{} ({})", nick, email);
            }
            if let Some(tag) = &meta.battletag {
                return format!("{} ({})", tag, email);
            }
        }
        email.to_string()
    }

    /// Set a nickname for an account.
    pub fn set_nickname(&mut self, email: &str, nickname: String) {
        let meta = self.accounts.entry(email.to_string()).or_insert(AccountMeta {
            nickname: None,
            battletag: None,
        });
        meta.nickname = Some(nickname);
    }

    /// Set a battletag for an account.
    pub fn set_battletag(&mut self, email: &str, battletag: String) {
        let meta = self.accounts.entry(email.to_string()).or_insert(AccountMeta {
            nickname: None,
            battletag: None,
        });
        meta.battletag = Some(battletag);
    }
}
