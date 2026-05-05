use anyhow::{Context, Result};
use std::process::{Command, Stdio};

/// Patterns we recognize as "Blizzard process tree".
///
/// Order matters in spirit: kill the leaf processes (game, helper) before
/// their parents (launcher, agent) so we don't get respawn races. In
/// practice `pkill` on each is fast enough that order rarely matters.
const BNET_KILL_PATTERNS: &[&str] = &[
    "Overwatch.exe",            // game itself
    "Battle.net Helper.exe",    // CEF/Electron helper subprocess
    "Battle.net.exe",           // launcher
    "Battle.net Launcher.exe",  // alternate launcher binary name
    "Agent.exe",                // background update agent
    "BlizzardError.exe",        // crash reporter (if running)
];

/// Kill the Battle.net launcher, Agent, and any running Blizzard games.
///
/// This is the "fast" kill — `pkill -f` against process command lines.
/// Wine itself keeps running (the wineserver process for the prefix).
/// That's intentional; it makes a follow-up account switch + relaunch
/// snappier because the prefix doesn't have to cold-start.
///
/// **Blocks until processes are actually gone** (or until a hard
/// timeout). Without this, the caller can race with a dying Battle.net
/// Agent which may rewrite Battle.net.config after our edit. Symptoms
/// of that race: switch loads the previous account instead of the new
/// one, or the launcher gets stuck "logging in" because Agent and the
/// new launcher fight over auth state.
///
/// Strategy:
/// 1. SIGTERM via `pkill` to give processes a chance to clean up.
/// 2. Poll `pgrep -f` every 100ms for up to 2s waiting for SIGTERM to land.
/// 3. If any survivors remain, escalate to SIGKILL.
/// 4. Final 200ms settle so wineserver releases file handles before we
///    rewrite Battle.net.config.
///
/// For a full prefix tear-down (also kill wineserver and Lutris wrapper),
/// use [`kill_bnet_aggressive`].
pub fn kill_bnet_processes() -> Result<()> {
    // Send SIGTERM to all matching processes. pkill returns nonzero when
    // no matches found — that's normal, ignored.
    for pattern in BNET_KILL_PATTERNS {
        let _ = Command::new("pkill")
            .args(["-TERM", "-f", pattern])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    // Poll for clean exit. 2s budget split into 100ms checks = 20 polls.
    let poll_interval = std::time::Duration::from_millis(100);
    let timeout = std::time::Duration::from_secs(2);
    let start = std::time::Instant::now();
    while start.elapsed() < timeout {
        if !any_bnet_running() {
            // All processes died cleanly. Final brief settle for FS sync.
            std::thread::sleep(std::time::Duration::from_millis(200));
            return Ok(());
        }
        std::thread::sleep(poll_interval);
    }

    // Timeout: anything still running gets SIGKILL. The Wine processes
    // most prone to ignoring SIGTERM are the Electron Helper and Agent.
    for pattern in BNET_KILL_PATTERNS {
        let _ = Command::new("pkill")
            .args(["-KILL", "-f", pattern])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    // SIGKILL is immediate, but give the kernel a moment to reap the
    // processes and let wineserver notice they're gone.
    std::thread::sleep(std::time::Duration::from_millis(300));
    Ok(())
}

/// True if any process matching one of [`BNET_KILL_PATTERNS`] is alive.
fn any_bnet_running() -> bool {
    for pattern in BNET_KILL_PATTERNS {
        let status = Command::new("pgrep")
            .args(["-f", pattern])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        if let Ok(s) = status {
            if s.success() {
                return true;
            }
        }
    }
    false
}

/// Kill Blizzard processes AND the wineserver for the given prefix.
///
/// Use this when the user explicitly wants Battle.net stopped and isn't
/// about to relaunch immediately. Also runs `wineserver -k` so the prefix
/// fully unloads, freeing GPU/file resources.
pub fn kill_bnet_aggressive(install: &crate::config::BnetInstall) -> Result<()> {
    kill_bnet_processes()?;

    // Send SIGTERM via wineserver -k. This is graceful — wineserver tells
    // its child wine processes to exit cleanly, then itself exits.
    let _ = Command::new("wineserver")
        .args(["-k"])
        .env("WINEPREFIX", &install.prefix)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    // Also kill umu-launcher / lutris-wrapper so they don't relaunch
    // anything for our prefix. Match by prefix path in their cmdline.
    let prefix_str = install.prefix.to_string_lossy().to_string();
    let _ = Command::new("pkill")
        .args(["-f", &prefix_str])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    std::thread::sleep(std::time::Duration::from_millis(500));
    Ok(())
}

/// Path to the spawn log file. Children's stdout+stderr get appended
/// here so we can debug "I pressed Enter and nothing launched" by
/// `tail`-ing it.
fn spawn_log_path() -> std::path::PathBuf {
    dirs::cache_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("/tmp"))
        .join("bnetswitch")
        .join("spawn.log")
}

/// Cheap PATH-walk lookup: returns true if `bin` is found in any $PATH dir.
///
/// We avoid spawning `which`/`command -v` since spawn_detached gets called
/// on every launch and shelling out adds startup latency for no reason.
fn is_on_path(bin: &str) -> bool {
    std::env::var_os("PATH")
        .map(|paths| std::env::split_paths(&paths).any(|p| p.join(bin).is_file()))
        .unwrap_or(false)
}

/// Wrap `cmd` with `gamemoderun` (and optionally `taskset` for CCD pinning)
/// to push the launched process tree into a low-latency configuration.
///
/// ## Layer 1: gamemoderun
///
/// `gamemoderun` is a no-op shim that:
///   1. Sets `LD_PRELOAD=libgamemodeauto.so.0` so the child registers
///      with the gamemoded daemon on startup.
///   2. Execs the next program in the chain.
///
/// gamemoded then flips:
///   - CPU governor: powersave -> performance (on amd-pstate-EPP this
///     pins to max boost, eliminating pstate ramp-up jitter).
///   - I/O priority of the game process group (best-effort class 0).
///   - Process CPU affinity bits (process gets full mask if it was
///     previously restricted by user-session cgroup limits).
///
/// All of these reduce input-to-photon latency under load. Reversed when
/// the registered process exits.
///
/// ## Layer 2: taskset CCD pinning
///
/// On dual-CCD AMD chiplet CPUs (Zen 4/5 desktop), `taskset -c` pins the
/// process tree to the higher-binned CCD's cores + SMT siblings. This
/// avoids cross-CCD Infinity Fabric cache misses (~40-80ns) which dominate
/// the latency tail of multi-threaded games like Overwatch.
///
/// `cpu_topology::preferred_ccd_cpus()` does the detection and returns
/// None on single-CCD systems, non-AMD systems, or unreadable /sys (in
/// containers). When None, we just skip the taskset wrap.
///
/// ## Final command shape
///
/// Best case (gamemoderun + taskset both available):
///   `gamemoderun taskset -c 0-5,12-17 <orig_program> <orig_args...>`
///
/// gamemoderun missing, taskset present:
///   `taskset -c 0-5,12-17 <orig_program> <orig_args...>`
///
/// Both missing or non-AMD-chiplet:
///   `<orig_program> <orig_args...>` (unchanged)
fn wrap_with_gamemoderun(cmd: Command) -> Command {
    let has_gamemoderun = is_on_path("gamemoderun");
    let pin_cpus = if is_on_path("taskset") {
        crate::cpu_topology::preferred_ccd_cpus()
    } else {
        None
    };

    if !has_gamemoderun && pin_cpus.is_none() {
        // Nothing to wrap with; preserve original cmd identically.
        return cmd;
    }

    // Capture the original cmd's program/args/env/cwd so we can rebuild
    // a new Command with the wrappers prepended.
    let orig_program = cmd.get_program().to_owned();
    let orig_args: Vec<std::ffi::OsString> =
        cmd.get_args().map(|a| a.to_owned()).collect();
    let orig_envs: Vec<(std::ffi::OsString, Option<std::ffi::OsString>)> = cmd
        .get_envs()
        .map(|(k, v)| (k.to_owned(), v.map(|v| v.to_owned())))
        .collect();
    let orig_cwd = cmd.get_current_dir().map(|p| p.to_owned());

    // Build the wrapper layers from outside-in. The outermost call is the
    // first argv[0] the kernel will exec; each inner layer is exec'd in
    // turn until we reach orig_program.
    //
    // Order matters: gamemoderun MUST be outermost so the LD_PRELOAD is
    // set before taskset runs, and gamemoded sees the registered child's
    // pid (taskset just exec()s, doesn't fork, so the pid lineage is fine).
    let mut wrapped = if has_gamemoderun {
        let mut c = Command::new("gamemoderun");
        if let Some(cpus) = &pin_cpus {
            c.arg("taskset").arg("-c").arg(cpus);
        }
        c.arg(orig_program);
        c
    } else if let Some(cpus) = &pin_cpus {
        let mut c = Command::new("taskset");
        c.arg("-c").arg(cpus).arg(orig_program);
        c
    } else {
        unreachable!("guarded by early-return above")
    };

    for a in orig_args {
        wrapped.arg(a);
    }

    if let Some(cwd) = orig_cwd {
        wrapped.current_dir(cwd);
    }
    for (k, v) in orig_envs {
        match v {
            Some(val) => {
                wrapped.env(k, val);
            }
            None => {
                wrapped.env_remove(k);
            }
        }
    }

    wrapped
}

/// Spawn `cmd` fully detached from the calling terminal.
///
/// We can't inherit the TUI's stdio (Lutris is chatty and would corrupt
/// the ratatui frame). But routing to `/dev/null` blinds us when launches
/// fail mysteriously. Compromise: capture stdout+stderr to a per-user
/// log file. Cheap to write, easy to inspect with `tail -f`.
///
/// Also `setsid()`s in pre-exec so the child outlives bnetswitch.
///
/// All spawns are wrapped with `gamemoderun` (when available) so the
/// gamemoded daemon flips CPU governor + ioprio for the duration of the
/// launched process tree. See `wrap_with_gamemoderun` for what that buys.
fn spawn_detached(cmd: Command) -> Result<()> {
    let mut cmd = wrap_with_gamemoderun(cmd);
    use std::os::unix::process::CommandExt;

    // Open (create + append) the log file so multiple spawns interleave.
    let log_path = spawn_log_path();
    if let Some(parent) = log_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path);

    cmd.stdin(Stdio::null());
    match log_file {
        Ok(f) => {
            // Same fd for stdout+stderr — order is preserved as written.
            let stdout = Stdio::from(f.try_clone().unwrap_or_else(|_| {
                std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&log_path)
                    .expect("reopen log file")
            }));
            let stderr = Stdio::from(f);
            cmd.stdout(stdout).stderr(stderr);
        }
        Err(_) => {
            // Couldn't open log; fall back to /dev/null silencing.
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }

    // SAFETY: setsid() is async-signal-safe and has no Rust-relevant side
    // effects beyond detaching the child from our session/process group.
    unsafe {
        cmd.pre_exec(|| {
            libc_setsid();
            Ok(())
        });
    }

    // Log a header line so multiple spawns are distinguishable.
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
    {
        use std::io::Write;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(
            f,
            "\n=== spawn @ epoch={} program={:?} args={:?} ===",
            now,
            cmd.get_program(),
            cmd.get_args().collect::<Vec<_>>()
        );
    }

    cmd.spawn().with_context(|| "Failed to spawn child process")?;
    Ok(())
}

/// Minimal libc::setsid binding — avoids pulling in the libc crate just for
/// one syscall. The return value is intentionally unused; if setsid() fails
/// (e.g., we're already a session leader) the child still inherits the null
/// stdio redirects, which is the important part.
fn libc_setsid() -> i32 {
    extern "C" {
        fn setsid() -> i32;
    }
    unsafe { setsid() }
}

/// Launch Overwatch directly, bypassing Battle.net's launcher UI.
///
/// ## How we figured this out
///
/// strace on wineserver while user clicked Play in Battle.net captured
/// the spawn. Battle.net.exe runs:
///
/// ```text
/// C:\Program Files (x86)\Overwatch\_retail_\Overwatch.exe -uid prometheus
/// ```
///
/// with the env variable `AGENT=1`. Overwatch then connects to the
/// running Agent (over HTTP on the port from `Agent.dat`) for auth
/// tokens and game-session registration. No more secret sauce — the
/// launch is just `Overwatch.exe -uid prometheus`.
///
/// ## Prerequisites
///
/// Agent must be running. Agent is started by Battle.net.exe and dies
/// when Battle.net.exe exits. So we ensure Battle.net.exe is up before
/// launching OW. If it's not running, we start it first and poll for
/// Agent reachability.
///
/// ## Why earlier attempts failed
///
/// - `battlenet://Pro/launch` URI — only navigates to OW tab.
/// - `--exec="launch Pro"` — same.
/// - `Overwatch Launcher.exe` direct — different binary, needs separate
///   handshake we never figured out.
/// - Bare `Overwatch.exe` — works, but only if Agent is up first.
pub fn launch_overwatch(
    install: &crate::config::BnetInstall,
    use_lutris: bool,
    warm_launch_ttl_secs: u64,
) -> Result<LaunchOutcome> {
    // ## Two-tier strategy
    //
    // **Warm path** — when Battle.net is running AND has recently
    // written `Launch Options\Pro` registry tokens (within
    // `warm_launch_ttl_secs`), we can spawn Overwatch.exe directly. OW
    // reads the still-valid DPAPI-encrypted `WEB_TOKEN` from the Wine
    // registry on startup and authenticates against Blizzard's servers
    // using it. We follow up with the same `POST /gamesession` and
    // `POST /priorities` calls Battle.net itself makes — using real
    // tokens written by real Battle.net, not faked.
    //
    // **Navigate path** — when warm launch isn't possible (Battle.net
    // not running, tokens stale, Agent unreachable), we fall back to
    // launching Battle.net's UI to the OW tab. User clicks Play once.
    // Battle.net writes fresh tokens, OW launches via the official
    // path. This is what TCNO does too.
    //
    // The warm path is fingerprint-clean: we read tokens Battle.net
    // wrote, and only do the post-spawn HTTP calls Battle.net normally
    // does. We are not generating auth material ourselves.

    if let Some(outcome) = try_warm_launch_overwatch(install, use_lutris, warm_launch_ttl_secs) {
        return Ok(outcome);
    }

    // Cold path: navigate to OW tab in Battle.net launcher.
    let bnet_exe = match resolve_bnet_exe_for_overwatch(install) {
        Some(p) => p,
        None => anyhow::bail!(
            "Battle.net.exe not found under {}",
            install.prefix.display()
        ),
    };

    let mut attempts: Vec<String> = Vec::new();

    // Path 1: umu-run with Lutris env, navigate to OW tab.
    if use_lutris {
        if let Some(umu) = crate::lutris::find_umu_run() {
            for slug in &["battlenet", "battlenet-standard"] {
                if let Ok((_, mut env)) = crate::lutris::load_launch_config(slug) {
                    crate::lutris::add_proton_runtime_env(&mut env);
                    let mut cmd = Command::new(&umu);
                    cmd.envs(&env);
                    cmd.arg(&bnet_exe).arg("--exec=launch Pro");
                    match spawn_detached(cmd) {
                        Ok(_) => return Ok(LaunchOutcome::Cold),
                        Err(e) => {
                            attempts.push(format!("umu-run({}): {}", slug, e));
                        }
                    }
                }
            }
        }
    }

    // Path 2: direct GE-Proton wine64.
    if let Some(wine64) = crate::lutris::find_proton_wine64() {
        let mut env: std::collections::BTreeMap<String, String> =
            crate::lutris::load_launch_config("battlenet")
                .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
                .map(|(_, e)| e)
                .unwrap_or_else(|_| {
                    let mut e = std::collections::BTreeMap::new();
                    e.insert(
                        "WINEPREFIX".to_string(),
                        install.prefix.to_string_lossy().to_string(),
                    );
                    e
                });
        env.entry("WINEDLLOVERRIDES".to_string())
            .or_insert_with(|| crate::lutris::dxvk_dll_overrides().to_string());

        let mut cmd = Command::new(&wine64);
        cmd.envs(&env);
        cmd.arg(&bnet_exe).arg("--exec=launch Pro");
        match spawn_detached(cmd) {
            Ok(_) => return Ok(LaunchOutcome::Cold),
            Err(e) => attempts.push(format!("proton-wine64: {}", e)),
        }
    }

    // Path 3: system wine.
    let mut cmd = Command::new("wine");
    cmd.env("WINEPREFIX", &install.prefix)
        .env("WINEDLLOVERRIDES", crate::lutris::dxvk_dll_overrides())
        .arg(&bnet_exe)
        .arg("--exec=launch Pro");
    match spawn_detached(cmd) {
        Ok(_) => return Ok(LaunchOutcome::Cold),
        Err(e) => attempts.push(format!("system wine: {}", e)),
    }

    anyhow::bail!("All launch paths failed: [{}]", attempts.join("; "))
}

/// Result of [`launch_overwatch`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LaunchOutcome {
    /// Direct OW spawn succeeded using fresh Battle.net-written tokens
    /// from the Wine registry. OW should auto-auth and skip the login
    /// screen.
    Warm,
    /// Fell back to opening Battle.net's UI to the OW tab. User clicks
    /// Play once. Battle.net writes fresh tokens, OW launches.
    Cold,
}

/// Attempt the warm launch path. Returns `Some(LaunchOutcome::Warm)` on
/// success. Returns `None` for any "we shouldn't try this right now"
/// reason — caller falls back to the cold path.
///
/// If Battle.net+Agent aren't running but registry tokens are fresh, we
/// transparently start Battle.net first and wait for Agent to come
/// online. From the user's POV: press `o`, OW launches. Battle.net's
/// startup is invisible.
fn try_warm_launch_overwatch(
    install: &crate::config::BnetInstall,
    use_lutris: bool,
    warm_ttl_secs: u64,
) -> Option<LaunchOutcome> {
    // Step 1: registry tokens fresh enough?
    //
    // Tokens are written to `user.reg` each time the user clicks Play
    // on a game in Battle.net. If never clicked, no section exists. If
    // older than the TTL, tokens may have been invalidated server-side
    // and OW will reject them on auth.
    let age = match crate::wine_reg::launch_options_age_secs(&install.prefix, "Pro") {
        Ok(Some(age)) => age,
        _ => return None,
    };
    if age > warm_ttl_secs {
        return None;
    }

    // Step 2: Agent reachable. If not, fall back to cold path.
    //
    // We considered auto-starting Battle.net + waiting for Agent here,
    // but that path is fragile: if Wine has leftover state from a prior
    // session, the spawn races with wineserver shutdown and produces
    // `wine client error:414: write: Bad file descriptor` mid-startup.
    // Battle.net then dies before Agent comes online.
    //
    // The cold path handles "Battle.net not running" robustly (it
    // navigates to OW tab and lets Battle.net authenticate cleanly).
    // User clicks Play once. Tokens get refreshed. Next press of `o`
    // can use the warm path because Battle.net is running.
    let agent = crate::agent::AgentClient::discover(&install.prefix)?;

    // Step 3: get a known-good caller PID for the `pid:` header.
    let caller_pid = match agent.battle_net_pid() {
        Ok(Some(p)) => p,
        _ => return None, // Battle.net.exe not visible to Agent.
    };

    // Step 4: snapshot existing prometheus PIDs so we can detect the new
    // one we're about to spawn.
    let pre_existing: std::collections::HashSet<u32> =
        agent.pids_for_uid("prometheus").ok()?.into_iter().collect();

    // Step 5: spawn Overwatch.exe directly. The same env vars Battle.net
    // sets work fine — Wine handles the rest via the prefix's existing
    // wineserver.
    let ow_exe = install
        .prefix
        .join("drive_c/Program Files (x86)/Overwatch/_retail_/Overwatch.exe");
    if !ow_exe.is_file() {
        return None;
    }

    if !spawn_overwatch_in_prefix(install, &ow_exe, use_lutris) {
        return None;
    }

    // Step 6: poll Agent for the spawned process to appear in
    // /gamesession (GameProcessManager auto-discovers it within ~1s).
    let new_pid = poll_for_new_prometheus_pid(&agent, &pre_existing, std::time::Duration::from_secs(15))?;

    // Step 7: do the registration + priorities calls Battle.net would do.
    // These aren't strictly required if GameProcessManager auto-registers,
    // but matching Battle.net's behavior keeps Agent's view of the world
    // consistent and may unlock features OW expects.
    let _ = agent.register_game("prometheus", new_pid, caller_pid);
    let _ = agent.set_priorities(&["prometheus"], caller_pid);

    Some(LaunchOutcome::Warm)
}

/// Spawn Overwatch.exe with the args + env that Battle.net uses.
/// Returns `false` if no working spawn path was found.
fn spawn_overwatch_in_prefix(
    install: &crate::config::BnetInstall,
    ow_exe: &std::path::Path,
    use_lutris: bool,
) -> bool {
    // Build the env. Lutris YAML for the Battle.net game gives us the
    // right WINEPREFIX, DXVK_CONFIG, etc. Add `AGENT=1` (Battle.net's
    // signal to OW that an Agent is available) + Proton runtime vars.
    let mut env: std::collections::BTreeMap<String, String> =
        match crate::lutris::load_launch_config("battlenet")
            .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
        {
            Ok((_, env)) => env,
            Err(_) => {
                let mut env = std::collections::BTreeMap::new();
                env.insert(
                    "WINEPREFIX".to_string(),
                    install.prefix.to_string_lossy().to_string(),
                );
                env
            }
        };
    crate::lutris::add_proton_runtime_env(&mut env);
    env.insert("AGENT".to_string(), "1".to_string());
    // The prefix is already initialized (Battle.net is running in it),
    // so use runinprefix to skip Proton's prefix-init pass.
    env.insert("PROTON_VERB".to_string(), "runinprefix".to_string());

    // Path 1: umu-run.
    if use_lutris {
        if let Some(umu) = crate::lutris::find_umu_run() {
            let mut cmd = Command::new(&umu);
            cmd.envs(&env);
            cmd.arg(ow_exe).arg("-uid").arg("prometheus");
            if spawn_detached(cmd).is_ok() {
                return true;
            }
        }
    }

    // Path 2: GE-Proton wine64 directly.
    if let Some(wine64) = crate::lutris::find_proton_wine64() {
        env.entry("WINEDLLOVERRIDES".to_string())
            .or_insert_with(|| crate::lutris::dxvk_dll_overrides().to_string());
        env.entry("WINEESYNC".to_string())
            .or_insert_with(|| "1".to_string());
        env.entry("WINEFSYNC".to_string())
            .or_insert_with(|| "1".to_string());
        let mut cmd = Command::new(&wine64);
        cmd.envs(&env);
        cmd.arg(ow_exe).arg("-uid").arg("prometheus");
        if spawn_detached(cmd).is_ok() {
            return true;
        }
    }

    // Path 3: system wine.
    let mut cmd = Command::new("wine");
    cmd.env("WINEPREFIX", &install.prefix)
        .env("WINEDLLOVERRIDES", crate::lutris::dxvk_dll_overrides())
        .env("AGENT", "1")
        .arg(ow_exe)
        .arg("-uid")
        .arg("prometheus");
    spawn_detached(cmd).is_ok()
}

/// Poll Agent's GET /gamesession until a new PID appears under the
/// "prometheus" key (i.e., the OW process we just spawned). Returns the
/// Wine PID, or None on timeout.
fn poll_for_new_prometheus_pid(
    agent: &crate::agent::AgentClient,
    pre_existing: &std::collections::HashSet<u32>,
    timeout: std::time::Duration,
) -> Option<u32> {
    let start = std::time::Instant::now();
    let interval = std::time::Duration::from_millis(250);
    while start.elapsed() < timeout {
        if let Ok(pids) = agent.pids_for_uid("prometheus") {
            for pid in pids {
                if !pre_existing.contains(&pid) && pid > 0 {
                    return Some(pid);
                }
            }
        }
        std::thread::sleep(interval);
    }
    None
}

/// Find the path to `Battle.net.exe` (not the `Launcher` wrapper) for
/// use with the `--exec="launch Pro"` flag. Falls back to whatever
/// `install.exe_path` provides if the canonical Battle.net.exe path
/// doesn't exist.
fn resolve_bnet_exe_for_overwatch(
    install: &crate::config::BnetInstall,
) -> Option<std::path::PathBuf> {
    let candidates = [
        "drive_c/Program Files (x86)/Battle.net/Battle.net.exe",
        "drive_c/Program Files/Battle.net/Battle.net.exe",
    ];
    for rel in &candidates {
        let p = install.prefix.join(rel);
        if p.is_file() {
            return Some(p);
        }
    }
    install.exe_path.clone()
}

/// Launch a `battlenet://` style URL through Wine's `start` command.
///
/// Currently unused — kept for potential future use if a verb-style URI
/// is found that triggers a real launch (vs just navigating).
#[allow(dead_code)]
fn try_launch_url_in_prefix(
    install: &crate::config::BnetInstall,
    url: &str,
    use_lutris: bool,
) -> Result<Option<bool>> {
    // 1. umu-run + start command.
    if use_lutris {
        if let Some(umu) = crate::lutris::find_umu_run() {
            let mut env: std::collections::BTreeMap<String, String> =
                match crate::lutris::load_launch_config("battlenet")
                    .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
                {
                    Ok((_, env)) => env,
                    Err(_) => {
                        let mut env = std::collections::BTreeMap::new();
                        env.insert(
                            "WINEPREFIX".to_string(),
                            install.prefix.to_string_lossy().to_string(),
                        );
                        env
                    }
                };
            crate::lutris::add_proton_runtime_env(&mut env);
            // umu-run doesn't accept "start url" syntax directly because
            // it expects an .exe path. We invoke wine's `start.exe`
            // explicitly (it's bundled in the prefix).
            let start_exe = install
                .prefix
                .join("drive_c/windows/system32/start.exe");
            if start_exe.is_file() {
                let mut cmd = Command::new(&umu);
                cmd.envs(&env);
                cmd.arg(&start_exe).arg(url);
                if spawn_detached(cmd).is_ok() {
                    return Ok(Some(true));
                }
            }
        }
    }

    // 2. Direct wine64 with `start` builtin. wine64 supports `start url`
    // natively without needing the prefix's start.exe.
    if let Some(wine64) = crate::lutris::find_proton_wine64() {
        let mut env: std::collections::BTreeMap<String, String> =
            match crate::lutris::load_launch_config("battlenet")
                .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
            {
                Ok((_, env)) => env,
                Err(_) => {
                    let mut env = std::collections::BTreeMap::new();
                    env.insert(
                        "WINEPREFIX".to_string(),
                        install.prefix.to_string_lossy().to_string(),
                    );
                    env
                }
            };
        env.entry("WINEDLLOVERRIDES".to_string())
            .or_insert_with(|| crate::lutris::dxvk_dll_overrides().to_string());
        env.entry("WINEESYNC".to_string()).or_insert_with(|| "1".to_string());
        env.entry("WINEFSYNC".to_string()).or_insert_with(|| "1".to_string());

        let mut cmd = Command::new(&wine64);
        cmd.envs(&env);
        cmd.arg("start").arg(url);
        if spawn_detached(cmd).is_ok() {
            return Ok(Some(true));
        }
    }

    // 3. System wine.
    let mut cmd = Command::new("wine");
    cmd.env("WINEPREFIX", &install.prefix)
        .arg("start")
        .arg(url);
    if spawn_detached(cmd).is_ok() {
        return Ok(Some(true));
    }

    Ok(Some(false))
}

/// Generic "launch a Windows .exe inside our prefix" helper.
///
/// Currently unused after the OW launch was rewritten to navigate to
/// the OW tab instead of spawning OW directly. Kept in case future
/// features need to launch arbitrary Windows binaries in our prefix.
#[allow(dead_code)]
///
/// Reuses the same launch fallback chain as [`launch_bnet`]:
/// 1. umu-run with full Lutris-equivalent env (matches Lutris)
/// 2. GE-Proton wine64 directly (Python-free)
/// 3. System wine (last resort)
///
/// Returns `Ok(Some(true))` on first successful spawn. Args after the
/// exe are forwarded as-is to wine.
fn try_launch_exe_in_prefix(
    install: &crate::config::BnetInstall,
    exe: &std::path::Path,
    args: &[&str],
    use_lutris: bool,
) -> Result<Option<bool>> {
    // 1. umu-run + Lutris YAML env + Proton runtime env.
    if use_lutris {
        if let Some(umu) = crate::lutris::find_umu_run() {
            let mut env: std::collections::BTreeMap<String, String> =
                match crate::lutris::load_launch_config("battlenet")
                    .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
                {
                    Ok((_, env)) => env,
                    Err(_) => {
                        let mut env = std::collections::BTreeMap::new();
                        env.insert(
                            "WINEPREFIX".to_string(),
                            install.prefix.to_string_lossy().to_string(),
                        );
                        env
                    }
                };
            crate::lutris::add_proton_runtime_env(&mut env);
            let mut cmd = Command::new(&umu);
            cmd.envs(&env);
            cmd.arg(exe);
            for a in args {
                cmd.arg(a);
            }
            if spawn_detached(cmd).is_ok() {
                return Ok(Some(true));
            }
        }
    }

    // 2. GE-Proton wine64 directly.
    if let Some(wine64) = crate::lutris::find_proton_wine64() {
        let mut env: std::collections::BTreeMap<String, String> =
            match crate::lutris::load_launch_config("battlenet")
                .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
            {
                Ok((_, env)) => env,
                Err(_) => {
                    let mut env = std::collections::BTreeMap::new();
                    env.insert(
                        "WINEPREFIX".to_string(),
                        install.prefix.to_string_lossy().to_string(),
                    );
                    env
                }
            };
        env.entry("WINEDLLOVERRIDES".to_string())
            .or_insert_with(|| crate::lutris::dxvk_dll_overrides().to_string());
        env.entry("WINEESYNC".to_string()).or_insert_with(|| "1".to_string());
        env.entry("WINEFSYNC".to_string()).or_insert_with(|| "1".to_string());

        let mut cmd = Command::new(&wine64);
        cmd.envs(&env);
        cmd.arg(exe);
        for a in args {
            cmd.arg(a);
        }
        if spawn_detached(cmd).is_ok() {
            return Ok(Some(true));
        }
    }

    // 3. System wine.
    let mut cmd = Command::new("wine");
    cmd.env("WINEPREFIX", &install.prefix)
        .env("WINEDLLOVERRIDES", crate::lutris::dxvk_dll_overrides())
        .arg(exe);
    for a in args {
        cmd.arg(a);
    }
    if spawn_detached(cmd).is_ok() {
        return Ok(Some(true));
    }

    Ok(Some(false))
}

/// Copy a string to the system clipboard.
///
/// Uses `wl-copy` (Wayland) or `xclip` (X11) depending on what's
/// available. On a Hyprland session both might be present (XWayland
/// includes xclip as a fallback for X clients), so we prefer wl-copy.
pub fn copy_to_clipboard(text: &str) -> Result<()> {
    let cmds: &[(&str, &[&str])] = &[
        ("wl-copy", &[]),
        ("xclip", &["-selection", "clipboard"]),
        ("xsel", &["--clipboard", "--input"]),
    ];

    for (binary, args) in cmds {
        if which_in_path(binary).is_none() {
            continue;
        }
        use std::io::Write;
        let mut child = match Command::new(binary)
            .args(*args)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(_) => continue,
        };
        if let Some(mut stdin) = child.stdin.take() {
            // wl-copy reads from stdin until EOF and stores the contents.
            // We must drop stdin (close it) before waiting, otherwise
            // wl-copy keeps the pipe open indefinitely.
            let _ = stdin.write_all(text.as_bytes());
        }
        // wl-copy daemonizes itself after reading stdin, so wait_with_output
        // returns quickly. Don't wait too long if anything is wedged.
        let _ = child.wait();
        return Ok(());
    }
    anyhow::bail!("No clipboard tool found (need wl-copy, xclip, or xsel)")
}

/// Minimal "is X on PATH" check without pulling in `which` as a dep.
fn which_in_path(name: &str) -> Option<std::path::PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        let candidate = dir.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Launch Battle.net.
///
/// Strategy in order of preference:
///
/// 1. **`umu-run`** (the same chain Lutris uses) — when its Python deps
///    are healthy. This is the "use what Lutris already set up" path:
///    Steam Runtime sandbox, protonfixes, Proton-managed env. Most
///    consistent with Lutris GUI launches.
///
/// 2. **GE-Proton's `wine64` directly** — fallback when umu-run can't
///    work (e.g., its Python deps are broken on this system). No Python
///    in the chain, just the native Wine binary. Loses the Steam Runtime
///    sandbox and protonfixes but works for well-behaved games like
///    Battle.net where neither is critical.
///
/// 3. **`lutris lutris:rungame/<slug>` URI** — let Lutris itself do
///    everything. Notoriously unreliable when Lutris GUI is already
///    open (silent no-op), but worth a final shot.
///
/// 4. **System `wine`** — last resort. No DXVK, no GE-Proton patches.
///
/// Returns `Err` only when every path failed, with diagnostics for each.
pub fn launch_bnet(install: &crate::config::BnetInstall, use_lutris: bool) -> Result<()> {
    let mut attempts: Vec<String> = Vec::new();

    // Path 1: umu-run with full Lutris-equivalent env (PROTONPATH set
    // so umu doesn't enter the Proton-update path that needs cbor2).
    // Matches what Lutris does for its own GUI launches.
    if use_lutris {
        if let Some(launched) = try_launch_umu(install, &mut attempts)? {
            if launched {
                return Ok(());
            }
        }
    }

    // Path 2: direct wine64. No Python required.
    if let Some(launched) = try_launch_proton_wine64(install, &mut attempts)? {
        if launched {
            return Ok(());
        }
    }

    if use_lutris {
        // Lutris CLI URI dispatch.
        let mut cmd = Command::new("lutris");
        cmd.arg("lutris:rungame/battlenet");
        match spawn_detached(cmd) {
            Ok(_) => return Ok(()),
            Err(e) => attempts.push(format!("lutris CLI: spawn failed: {}", e)),
        }
    }

    // System wine, no Proton context. Last resort.
    if let Some(exe) = &install.exe_path {
        let mut cmd = Command::new("wine");
        cmd.env("WINEPREFIX", &install.prefix).arg(exe);
        // Best-effort DXVK overrides — wine's built-in d3d will be used
        // if DXVK isn't installed in the prefix (graceful degradation).
        cmd.env("WINEDLLOVERRIDES", crate::lutris::dxvk_dll_overrides());
        match spawn_detached(cmd) {
            Ok(_) => return Ok(()),
            Err(e) => attempts.push(format!("system wine: spawn failed: {}", e)),
        }
    } else {
        attempts.push("system wine: install.exe_path is None".to_string());
    }

    anyhow::bail!(
        "All launch paths failed. Attempts: [{}]",
        attempts.join("; ")
    )
}

/// Direct `wine64` launch from GE-Proton. No Python, no Steam Runtime.
///
/// Returns `Ok(Some(true))` on successful spawn, `Ok(Some(false))` if
/// the path isn't usable (no Proton found, no exe path), `Err` only on
/// hard errors. Diagnostics get pushed to `attempts`.
fn try_launch_proton_wine64(
    install: &crate::config::BnetInstall,
    attempts: &mut Vec<String>,
) -> Result<Option<bool>> {
    let wine64 = match crate::lutris::find_proton_wine64() {
        Some(p) => p,
        None => {
            attempts.push("proton-wine64: no GE-Proton install found".to_string());
            return Ok(Some(false));
        }
    };

    // Find exe + env. Prefer Lutris YAML env if available; otherwise use
    // the installation we detected earlier with minimal env.
    let (exe_path, mut env): (std::path::PathBuf, std::collections::BTreeMap<String, String>) =
        match crate::lutris::load_launch_config("battlenet")
            .or_else(|_| crate::lutris::load_launch_config("battlenet-standard"))
        {
            Ok((cfg, env)) => {
                let exe = std::path::Path::new(&cfg.game.prefix).join(&cfg.game.exe);
                (exe, env)
            }
            Err(_) => match &install.exe_path {
                Some(exe) => {
                    let mut env = std::collections::BTreeMap::new();
                    env.insert(
                        "WINEPREFIX".to_string(),
                        install.prefix.to_string_lossy().to_string(),
                    );
                    (exe.clone(), env)
                }
                None => {
                    attempts.push("proton-wine64: no exe path resolvable".to_string());
                    return Ok(Some(false));
                }
            },
        };

    if !exe_path.is_file() {
        attempts.push(format!(
            "proton-wine64: exe not found at {}",
            exe_path.display()
        ));
        return Ok(Some(false));
    }

    // Set DXVK overrides if not already present. Proton expects the user
    // (or itself) to set this; without it Wine uses its built-in D3D.
    env.entry("WINEDLLOVERRIDES".to_string())
        .or_insert_with(|| crate::lutris::dxvk_dll_overrides().to_string());

    // Esync/Fsync are Proton's standard sync optimizations — usually safe
    // to enable with modern kernels. Don't override if user set them.
    env.entry("WINEESYNC".to_string())
        .or_insert_with(|| "1".to_string());
    env.entry("WINEFSYNC".to_string())
        .or_insert_with(|| "1".to_string());

    let mut cmd = Command::new(&wine64);
    cmd.envs(&env);
    cmd.arg(&exe_path);

    match spawn_detached(cmd) {
        Ok(_) => Ok(Some(true)),
        Err(e) => {
            attempts.push(format!("proton-wine64: spawn failed: {}", e));
            Ok(Some(false))
        }
    }
}

/// umu-run + Lutris YAML fallback. Returns `Ok(Some(true))` on success.
fn try_launch_umu(
    install: &crate::config::BnetInstall,
    attempts: &mut Vec<String>,
) -> Result<Option<bool>> {
    let umu = match crate::lutris::find_umu_run() {
        Some(p) => p,
        None => {
            attempts.push("umu-run: not found".to_string());
            return Ok(Some(false));
        }
    };

    for slug in &["battlenet", "battlenet-standard"] {
        match crate::lutris::load_launch_config(slug) {
            Ok((config, mut env)) => {
                // Critical: add the Proton runtime env vars Lutris sets
                // dynamically (PROTONPATH, GAMEID, WINEARCH, PROTON_VERB).
                // Without these umu-run thinks it has to download Proton
                // and hits the cbor2 dep.
                crate::lutris::add_proton_runtime_env(&mut env);

                let exe = std::path::Path::new(&config.game.prefix).join(&config.game.exe);
                if !exe.is_file() {
                    attempts.push(format!(
                        "umu-run+yaml({}): exe not found at {}",
                        slug,
                        exe.display()
                    ));
                    continue;
                }
                let mut cmd = Command::new(&umu);
                cmd.envs(&env);
                cmd.arg(&exe);
                match spawn_detached(cmd) {
                    Ok(_) => return Ok(Some(true)),
                    Err(e) => {
                        attempts.push(format!("umu-run+yaml({}): spawn failed: {}", slug, e))
                    }
                }
            }
            Err(e) => attempts.push(format!("yaml lookup({}): {}", slug, e)),
        }
    }

    // Bare umu-run without YAML env, but still with Proton runtime env.
    if let Some(exe) = &install.exe_path {
        let mut env = std::collections::BTreeMap::new();
        env.insert(
            "WINEPREFIX".to_string(),
            install.prefix.to_string_lossy().to_string(),
        );
        crate::lutris::add_proton_runtime_env(&mut env);
        let mut cmd = Command::new(&umu);
        cmd.envs(&env).arg(exe);
        match spawn_detached(cmd) {
            Ok(_) => return Ok(Some(true)),
            Err(e) => attempts.push(format!("umu-run+plain: spawn failed: {}", e)),
        }
    }

    Ok(Some(false))
}

/// Check if Battle.net processes are currently running.
pub fn is_bnet_running() -> bool {
    let output = Command::new("pgrep")
        .args(["-f", "Battle.net"])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output();
    matches!(output, Ok(o) if o.status.success())
}
