//! Read Lutris game configurations to launch games directly via umu-run.
//!
//! ## Why not just use `lutris lutris:rungame/<slug>`?
//!
//! When Lutris's GUI is already running, the URI dispatch (sending the
//! arg to the existing process via GTK single-instance) frequently
//! silently no-ops. The spawn returns success, but Lutris doesn't act
//! on the URI. Result: users press "switch" in bnetswitch and nothing
//! happens, then they have to manually click Play in Lutris.
//!
//! Bypassing Lutris and invoking `umu-run` directly avoids this entirely.
//! umu-run is the launcher Lutris itself uses internally — it sets up
//! the GE-Proton runtime, applies WINEPREFIX, and invokes the wine
//! binary. By calling it ourselves with the same env Lutris would have
//! set, we get equivalent behaviour without the GUI dispatch flakiness.

use anyhow::{Context, Result};
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Subset of the Lutris game YAML we care about for launching. Lutris
/// writes much more (script, install metadata, etc.) — we ignore it.
#[derive(Debug, Deserialize)]
pub struct LutrisGameConfig {
    pub game: GameSection,
    /// Top-level system overrides (env, exclude_processes, etc.). The
    /// nested `script.system` is the *original install template* and is
    /// shadowed by these top-level values when launching.
    #[serde(default)]
    pub system: Option<SystemSection>,
    /// Wine-specific overrides. We mostly care about the DLL overrides.
    #[serde(default)]
    pub wine: Option<WineSection>,
}

#[derive(Debug, Deserialize)]
pub struct GameSection {
    pub exe: String,
    pub prefix: String,
    /// "win64" usually. We don't currently branch on this but capture
    /// it for future use.
    #[serde(default)]
    #[allow(dead_code)]
    pub arch: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct SystemSection {
    #[serde(default)]
    pub env: BTreeMap<String, serde_norway::Value>,
}

#[derive(Debug, Deserialize, Default)]
pub struct WineSection {
    /// e.g. {"locationapi": "d"} — translates to WINEDLLOVERRIDES entries.
    #[serde(default)]
    pub overrides: BTreeMap<String, String>,
}

/// Find the Lutris game YAML for a given slug.
///
/// Lutris stores game configs at `~/.local/share/lutris/games/<configpath>.yml`
/// where `<configpath>` is `<slug>-<creation_timestamp>`. The mapping
/// from slug to configpath lives in `pga.db`. We query that to find the
/// right file rather than guessing.
pub fn find_game_yaml(slug: &str) -> Option<PathBuf> {
    let lutris_data = dirs::data_dir()?.join("lutris");
    let pga_db = lutris_data.join("pga.db");
    if !pga_db.is_file() {
        return None;
    }

    // We already shell out to `sqlite3` for Battle.net's CachedData.db,
    // so re-using the same approach keeps deps minimal.
    let output = Command::new("sqlite3")
        .arg(&pga_db)
        .arg(format!(
            "SELECT configpath FROM games WHERE slug='{}' LIMIT 1;",
            slug.replace('\'', "''")
        ))
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let configpath = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if configpath.is_empty() {
        return None;
    }
    let yaml_path = lutris_data.join("games").join(format!("{}.yml", configpath));
    if yaml_path.is_file() {
        Some(yaml_path)
    } else {
        None
    }
}

/// Parse a Lutris game YAML into our subset structure.
pub fn read_game_config(yaml_path: &Path) -> Result<LutrisGameConfig> {
    let content = std::fs::read_to_string(yaml_path)
        .with_context(|| format!("Failed to read {}", yaml_path.display()))?;
    let config: LutrisGameConfig = serde_norway::from_str(&content)
        .with_context(|| format!("Failed to parse YAML at {}", yaml_path.display()))?;
    Ok(config)
}

/// Path to umu-run inside the user's Lutris install, if present.
pub fn find_umu_run() -> Option<PathBuf> {
    let candidate = dirs::data_dir()?
        .join("lutris")
        .join("runtime")
        .join("umu")
        .join("umu-run");
    if candidate.is_file() {
        Some(candidate)
    } else {
        None
    }
}

/// Locate a Proton-bundled `wine64` binary, preferring the most recent
/// GE-Proton install. We pick the lexicographically-last entry under
/// `~/.local/share/Steam/compatibilitytools.d/` whose name starts with
/// "GE-Proton" — version numbers are zero-padded enough that this gets
/// the latest in practice ("GE-Proton10-34" sorts after "GE-Proton9-x").
///
/// Returns the path to `<proton-root>/files/bin/wine64` if found.
///
/// We prefer Proton's wine64 over system wine because Proton bundles
/// DXVK/VKD3D and various Wine patches that improve game compatibility
/// considerably.
pub fn find_proton_wine64() -> Option<PathBuf> {
    let compat_root = dirs::data_dir()?
        .join("Steam")
        .join("compatibilitytools.d");
    if !compat_root.is_dir() {
        return None;
    }

    let mut ge_proton_dirs: Vec<PathBuf> = std::fs::read_dir(&compat_root)
        .ok()?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.is_dir()
                && p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.starts_with("GE-Proton"))
                    .unwrap_or(false)
        })
        .collect();
    ge_proton_dirs.sort();

    for proton_root in ge_proton_dirs.iter().rev() {
        let wine64 = proton_root.join("files").join("bin").join("wine64");
        if wine64.is_file() {
            return Some(wine64);
        }
    }
    None
}

/// Build the `WINEDLLOVERRIDES` value that enables DXVK + VKD3D for a
/// Proton-managed prefix. Without this Wine uses its own (slower) D3D
/// implementations even though Proton has installed DXVK DLLs into the
/// prefix.
///
/// `n,b` means "try native DLL first, fall back to builtin Wine".
pub fn dxvk_dll_overrides() -> &'static str {
    "d3d9,d3d10core,d3d11,d3d12,d3d12core,dxgi=n,b"
}

/// Quick health check for umu-run's Python dependencies.
///
/// Currently unused — we discovered the cbor2 path is only hit when
/// `PROTONPATH` is unset, so setting that env var properly is enough
/// to avoid the dep entirely. Kept for future diagnostic use.
#[allow(dead_code)]
///
/// umu-run is a Python zipapp using the system `/usr/bin/env python3`.
/// On rolling distros umu-launcher's deps occasionally outpace what's
/// installed system-wide (the package's runtime requires lag behind its
/// upstream code). The most common offender is `cbor2`, used by the
/// Proton delta-update code path.
///
/// We probe by trying to import the modules umu-run pulls. If any are
/// missing, we know umu-run will explode at launch time and can fall
/// back to a Python-free path.
///
/// Cheap (~50ms): just spawns `python3 -c "import cbor2..."`.
pub fn umu_python_deps_available() -> bool {
    use std::process::{Command, Stdio};
    // Modules we know umu-run imports at startup or in normal launch paths.
    // cbor2 is the one currently breaking; the others rarely break but
    // it's free to check them too.
    const PROBE: &str = "import cbor2; import zstandard";
    let status = Command::new("python3")
        .arg("-c")
        .arg(PROBE)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    matches!(status, Ok(s) if s.success())
}

/// Build the full set of env vars Lutris would set for this game. Handles
/// `$GAMEDIR` and `$USER` variable expansion which Lutris does internally.
///
/// Returns a flat `BTreeMap<String, String>` ready to feed into
/// `Command::envs()`. Numeric and boolean YAML values are coerced to
/// strings (e.g., `STAGING_SHARED_MEMORY: 1` becomes `"1"`).
pub fn build_env(config: &LutrisGameConfig) -> BTreeMap<String, String> {
    let mut env = BTreeMap::new();

    let gamedir = &config.game.prefix;
    let username = std::env::var("USER").unwrap_or_else(|_| "user".to_string());

    // System env block — the primary source of Lutris-managed env vars.
    if let Some(system) = &config.system {
        for (k, raw) in &system.env {
            if let Some(value) = yaml_value_to_string(raw) {
                let expanded = expand_lutris_vars(&value, gamedir, &username);
                env.insert(k.clone(), expanded);
            }
        }
    }

    // WINEPREFIX is implicit from game.prefix.
    env.insert("WINEPREFIX".to_string(), gamedir.clone());

    // DLL overrides → WINEDLLOVERRIDES. Lutris formats them as
    // "lib1=mode;lib2=mode" and merges with whatever's already set.
    if let Some(wine) = &config.wine {
        if !wine.overrides.is_empty() {
            let formatted: Vec<String> = wine
                .overrides
                .iter()
                .map(|(lib, mode)| format!("{}={}", lib, mode))
                .collect();
            let combined = match env.get("WINEDLLOVERRIDES") {
                Some(existing) => format!("{};{}", existing, formatted.join(";")),
                None => formatted.join(";"),
            };
            env.insert("WINEDLLOVERRIDES".to_string(), combined);
        }
    }

    env
}

/// Coerce a YAML scalar (string, integer, float, bool) into its string
/// representation. Returns `None` for non-scalar values like maps/sequences,
/// which shouldn't appear in env config but we defensively skip rather
/// than crash.
fn yaml_value_to_string(v: &serde_norway::Value) -> Option<String> {
    match v {
        serde_norway::Value::String(s) => Some(s.clone()),
        serde_norway::Value::Number(n) => Some(n.to_string()),
        serde_norway::Value::Bool(b) => Some(b.to_string()),
        serde_norway::Value::Null => None,
        _ => None,
    }
}

/// Expand `$GAMEDIR` and `$USER` references within an env value, the way
/// Lutris does internally.
fn expand_lutris_vars(value: &str, gamedir: &str, username: &str) -> String {
    value
        .replace("$GAMEDIR", gamedir)
        .replace("${GAMEDIR}", gamedir)
        .replace("$USER", username)
        .replace("${USER}", username)
}

/// Convenience wrapper: load + parse + build env for the given slug.
/// Returns Err if the YAML can't be located or parsed.
pub fn load_launch_config(slug: &str) -> Result<(LutrisGameConfig, BTreeMap<String, String>)> {
    let yaml = find_game_yaml(slug)
        .with_context(|| format!("No Lutris game YAML found for slug '{}'", slug))?;
    let config = read_game_config(&yaml)?;
    let env = build_env(&config);
    Ok((config, env))
}

/// Augment an env map with the umu/Proton runtime variables Lutris sets
/// dynamically at launch time. These don't live in the game YAML — Lutris
/// computes them in `lutris.util.wine.proton.update_proton_env`.
///
/// Without these, umu-run falls into "I need to install/update Proton"
/// code paths which pull in the `cbor2` dependency. With them set
/// correctly, umu-run sees a valid existing Proton and skips that path
/// entirely.
///
/// We don't overwrite existing keys — caller may have set custom values.
pub fn add_proton_runtime_env(env: &mut BTreeMap<String, String>) {
    // PROTONPATH: literal "GE-Proton" makes umu look up the latest
    // GE-Proton install in standard locations. This matches what
    // Lutris's `update_proton_env` does for umu wine paths.
    env.entry("PROTONPATH".to_string())
        .or_insert_with(|| "GE-Proton".to_string());

    // GAMEID is required by umu for non-Steam games. Lutris uses
    // "umu-default" as the fallback when no specific game ID is known.
    env.entry("GAMEID".to_string())
        .or_insert_with(|| "umu-default".to_string());

    env.entry("WINEARCH".to_string())
        .or_insert_with(|| "win64".to_string());

    // PROTON_VERB controls Proton's prefix initialization behavior.
    // "waitforexitandrun" runs the full prefix-setup pass with proton-fixes;
    // "runinprefix" skips re-init for already-running prefixes. Lutris
    // tracks active prefixes to choose between them — we don't have that
    // visibility, so we always pick the safer "waitforexitandrun".
    env.entry("PROTON_VERB".to_string())
        .or_insert_with(|| "waitforexitandrun".to_string());

    // Forward locale hints. Steam Runtime container resets LC_ALL by
    // default; HOST_LC_ALL preserves the host's setting.
    if let Ok(lc_all) = std::env::var("LC_ALL") {
        env.entry("HOST_LC_ALL".to_string()).or_insert(lc_all);
    }

    // ====================================================================
    // NVIDIA Reflex / NVAPI passthrough.
    //
    // Verified prerequisites on this machine:
    //   - Driver 590.48 (>= 555 required for VK_NV_low_latency2 path)
    //   - DXVK 2.6+ (we have 2.6.2 in GE-Proton 10-34)
    //   - DXVK-NVAPI 0.9+ ships with GE-Proton
    //   - vulkaninfo confirms VK_NV_low_latency2 extension is present
    //
    // Without these env vars, DXVK silently disables the NVAPI bridge and
    // OW's "Reflex On + Boost" toggle is a no-op.
    // ====================================================================

    // Enables Proton's NVAPI compatibility layer. Required for Wine apps
    // to even *find* nvapi64.dll. Without this, OW falls back to its
    // generic latency reduction path (no Reflex hardware integration).
    env.entry("PROTON_FORCE_NVAPI".to_string())
        .or_insert_with(|| "1".to_string());

    // Tells DXVK to expose its NVAPI shim to the game. The shim translates
    // NVAPI calls (Reflex, frame metric reporting) into Vulkan
    // VK_NV_low_latency2 / VK_KHR_present_wait calls.
    env.entry("DXVK_ENABLE_NVAPI".to_string())
        .or_insert_with(|| "1".to_string());

    // ====================================================================
    // What we DON'T set, and why
    // ====================================================================
    //
    //   PROTON_ENABLE_WAYLAND=1
    //     Tested. Breaks Battle.net's Electron UI (white blank window) and
    //     paradoxically also breaks Reflex by routing presents through a
    //     different Wayland backend that doesn't expose low_latency2 yet.
    //     Stay on XWayland for the OW process.
    //
    //   DXVK_FRAME_RATE=234
    //     OW's internal frame limiter is more latency-friendly than DXVK's
    //     external cap (OW's limiter integrates with Reflex pacing; DXVK's
    //     just sleeps the present thread, which adds jitter). Configure
    //     the cap inside OW Settings -> Video instead.
    //
    //   WINE_FULLSCREEN_FSR=*
    //     We render at native res; FSR is upscaling and adds a post-process
    //     pass = +0.5 to 1ms latency. Off.
}
