//! Diagnostic trace of parse_description on real LFG strings.
//! Run: cargo test --test parse_trace -- --nocapture --test-threads=1

#[path = "../src/lfg_parse.rs"]
#[allow(dead_code)]
mod lfg_parse;

#[path = "../src/ranks.rs"]
#[allow(dead_code)]
mod ranks;

use lfg_parse::parse_description;

#[test]
fn trace_screenshot_lfgs() {
    let tests = [
        ("plat4+",                              "expect Pl 4 - Ch 1"),
        ("1 tank / 2 sup /// gold 5",           "expect Si 5 - Pl 5 (centered Gold 5)"),
        ("diamond need 1 supp",                 "expect Di 5 - Ma 5 (bare diamond)"),
        ("supp 1 dps high plat",                "expect Pl 1 single point (high modifier)"),
        ("1 dps bronze",                        "expect Br 5 - Si 5 (bare bronze)"),
        ("silver-gold",                         "expect Si 5 - Go 1 (range)"),
        ("plat sup and dps",                    "expect Pl 5 - Di 5 (bare plat)"),
        ("need 2 dmg 1 tank gold to bronze wide q", "expect Br 5 - Go 1 (range)"),
        ("gold tank supp dps",                  "expect Go 5 - Pl 5 (bare gold)"),
        ("gold tank",                           "WETLIQUID exact: expect Go 5 - Pl 5"),
        ("gold",                                "bare gold alone"),
        ("gold tank dps",                       "bare gold + roles"),
        ("gold to plat 2 supp",                 "tuck2006: expect Go 5 - Pl 2"),
        ("p2+ need 1 support have brain?",      "JunkedOff: expect Pl 2 - Ch 1 (open-upper)"),
        ("gold to plat 2",                      "isolated 'gold to plat 2'"),
        ("gold to plat",                        "isolated 'gold to plat'"),
        ("bronze 3 am dps",                     "expect Br 5 - Si 3 (centered Bronze 3)"),
        ("gold need supp",                      "expect Go 5 - Pl 5"),
        ("bronze to silver supports",           "expect Br 5 - Si 1 (range)"),
        ("NEED DPS OR SUP PLAT-DIA",            "expect Pl 5 - Di 1 (range)"),
    ];
    for (text, expect) in tests {
        let p = parse_description(text);
        let got = match (p.rank_min, p.rank_max) {
            (Some(a), Some(b)) if a == b => a.label(),
            (Some(a), Some(b)) => format!("{} - {}", a.label(), b.label()),
            (Some(a), None) | (None, Some(a)) => a.label(),
            _ => "?".to_string(),
        };
        println!("{:50} got={:20} | {}", format!("{:?}", text), got, expect);
    }
}
