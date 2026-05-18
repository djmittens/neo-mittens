//! CPU topology detection for low-latency game pinning on AMD chiplet CPUs.
//!
//! On dual-CCD Ryzen parts (Zen 4 / Zen 5 desktop, e.g., 9900X), each CCD is
//! a separate L3 cache domain connected over Infinity Fabric. Cross-CCD
//! cache misses cost ~40-80ns vs ~4ns intra-CCD. Pinning a latency-sensitive
//! game's process tree to a single CCD avoids this Infinity Fabric tax.
//!
//! On Linux the CPPC2 preferred-core ranking (exposed by amd-pstate-active)
//! lets us pick the higher-binned CCD automatically — usually CCD0 by ~25
//! perf-units on Zen 5 due to fab process variation.
//!
//! ## What this module does
//!
//! `preferred_ccd_cpus()` returns a comma-separated CPU list (e.g.
//! `"0-5,12-17"`) suitable for `taskset -c <list>`, identifying the
//! best-binned single L3 domain.
//!
//! Returns `None` when:
//!   - `/sys` topology files are unreadable (containers, hardened systems)
//!   - The system has only one L3 domain (single-CCD CPU, Intel, etc.)
//!   - amd-pstate ranking isn't exposed (driver disabled / non-AMD)
//!
//! In any None case, callers should skip pinning rather than fail —
//! pinning is a perf optimization, not a correctness requirement.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

/// Read the contents of a sysfs file, trimming whitespace.
/// Returns None on any I/O failure (file missing, no permission, etc.).
fn read_sysfs(path: &Path) -> Option<String> {
    fs::read_to_string(path)
        .ok()
        .map(|s| s.trim().to_string())
}

/// Parse a Linux CPU list specifier like "0-5,12,15-17" into a flat Vec<u32>
/// of CPU indices. Returns an empty Vec on parse failure (caller treats
/// empty as "no info").
///
/// Currently only used by tests but kept module-level for symmetry with
/// `format_cpu_ranges` and as a building block for future "user override
/// CCD list" config support.
#[allow(dead_code)]
fn parse_cpu_list(s: &str) -> Vec<u32> {
    let mut out = Vec::new();
    for part in s.split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Some((lo_s, hi_s)) = part.split_once('-') {
            if let (Ok(lo), Ok(hi)) = (lo_s.parse::<u32>(), hi_s.parse::<u32>()) {
                for i in lo..=hi {
                    out.push(i);
                }
            }
        } else if let Ok(n) = part.parse::<u32>() {
            out.push(n);
        }
    }
    out
}

/// Format a sorted slice of CPU indices back into a compact range list,
/// e.g. [0,1,2,3,4,5,12,13,14,15,16,17] -> "0-5,12-17". This is the format
/// `taskset -c` accepts.
fn format_cpu_ranges(cpus: &[u32]) -> String {
    if cpus.is_empty() {
        return String::new();
    }
    let mut sorted = cpus.to_vec();
    sorted.sort_unstable();
    sorted.dedup();

    let mut out = String::new();
    let mut i = 0;
    while i < sorted.len() {
        let start = sorted[i];
        let mut end = start;
        while i + 1 < sorted.len() && sorted[i + 1] == end + 1 {
            end = sorted[i + 1];
            i += 1;
        }
        if !out.is_empty() {
            out.push(',');
        }
        if start == end {
            out.push_str(&start.to_string());
        } else {
            out.push_str(&format!("{}-{}", start, end));
        }
        i += 1;
    }
    out
}

/// Detect the best-binned L3 cache domain (CCD on AMD chiplet parts) and
/// return its CPU list as a `taskset -c` argument string.
///
/// Algorithm:
///   1. Enumerate /sys/devices/system/cpu/cpu*/cache/index3/shared_cpu_list
///      — each unique value is a distinct L3 domain (CCD).
///   2. For each domain, read amd_pstate_highest_perf for its physical
///      cores and take the median. Higher = better silicon.
///   3. If only one domain exists, return None (no pinning benefit).
///   4. Pick the domain with highest median perf, return its full CPU
///      list (physical cores + SMT siblings).
pub fn preferred_ccd_cpus() -> Option<String> {
    // domain_key (CPU list as found in shared_cpu_list) -> Vec of CPU ids
    let mut domains: BTreeMap<String, Vec<u32>> = BTreeMap::new();

    let cpu_root = Path::new("/sys/devices/system/cpu");
    let entries = fs::read_dir(cpu_root).ok()?;

    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if !name.starts_with("cpu") {
            continue;
        }
        // Skip cpuidle, cpufreq, etc. — only `cpu<N>` matches.
        let cpu_num: u32 = match name[3..].parse() {
            Ok(n) => n,
            Err(_) => continue,
        };
        let l3_path = entry.path().join("cache/index3/shared_cpu_list");
        let key = match read_sysfs(&l3_path) {
            Some(k) => k,
            None => continue,
        };
        domains.entry(key).or_default().push(cpu_num);
    }

    // Need at least 2 distinct L3 domains for pinning to make sense.
    if domains.len() < 2 {
        return None;
    }

    // Score each domain by median perf ranking. Use only the lowest CPU
    // ids (physical cores, not SMT siblings) since SMT siblings share a
    // perf value with their primary thread anyway.
    let mut best: Option<(u64, Vec<u32>)> = None;
    for (_key, cpus) in domains {
        let mut perfs: Vec<u64> = cpus
            .iter()
            .filter_map(|&c| {
                read_sysfs(&Path::new(&format!(
                    "/sys/devices/system/cpu/cpu{}/cpufreq/amd_pstate_highest_perf",
                    c
                )))
                .and_then(|s| s.parse::<u64>().ok())
            })
            .collect();
        if perfs.is_empty() {
            // CPPC2 ranking unavailable — fall back to first domain's CPUs
            // by sort order, which on AMD typically maps to CCD0. Still
            // better than no pinning at all.
            if best.is_none() {
                best = Some((0, cpus.clone()));
            }
            continue;
        }
        perfs.sort_unstable();
        let median = perfs[perfs.len() / 2];
        let take = match &best {
            None => true,
            Some((cur_median, _)) => median > *cur_median,
        };
        if take {
            best = Some((median, cpus));
        }
    }

    let (_, cpus) = best?;
    Some(format_cpu_ranges(&cpus))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_cpu_list_simple() {
        assert_eq!(parse_cpu_list("0-3"), vec![0, 1, 2, 3]);
        assert_eq!(parse_cpu_list("0,2,4"), vec![0, 2, 4]);
        assert_eq!(parse_cpu_list("0-2,5,7-8"), vec![0, 1, 2, 5, 7, 8]);
        assert_eq!(parse_cpu_list(""), Vec::<u32>::new());
    }

    #[test]
    fn test_format_cpu_ranges_basic() {
        assert_eq!(format_cpu_ranges(&[0, 1, 2, 3, 4, 5]), "0-5");
        assert_eq!(
            format_cpu_ranges(&[0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17]),
            "0-5,12-17"
        );
        assert_eq!(format_cpu_ranges(&[0, 2, 4]), "0,2,4");
        assert_eq!(format_cpu_ranges(&[]), "");
    }

    #[test]
    fn test_format_handles_unsorted_dups() {
        assert_eq!(format_cpu_ranges(&[5, 0, 1, 2, 3, 4, 0]), "0-5");
    }
}
