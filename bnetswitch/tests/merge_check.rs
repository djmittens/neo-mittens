//! Verify the merge behavior end-to-end against live VC groups.
#[path = "../src/lfg_parse.rs"]
#[allow(dead_code)]
mod lfg_parse;
#[path = "../src/ranks.rs"]
#[allow(dead_code)]
mod ranks;

use lfg_parse::parse_description;

fn merge_group(descs: &[&str]) -> (Option<String>, Option<String>) {
    let mut acc = parse_description(descs[0]);
    for d in &descs[1..] {
        let p = parse_description(d);
        acc.merge_in(&p);
    }
    (acc.rank_min.map(|r| r.label()), acc.rank_max.map(|r| r.label()))
}

#[test]
fn live_vc_groups() {
    println!();
    let cases = [
        ("tuck2006 group", vec![
            "gold to plat 2 supp",
            "Plat - Gold 2 support",
            "plat-gold lf 2 supports and 1 tank",
        ]),
        ("JunkedOff group", vec![
            "p2+ need 1 support have brain?",
            "p2+ need support",
            "p1 dps please be good dawg",
        ]),
    ];
    for (label, ds) in cases {
        let (min, max) = merge_group(&ds);
        println!("{}: rank_min={:?} rank_max={:?}", label, min, max);
        for d in &ds {
            println!("    desc: {:?}", d);
        }
        println!();
    }
}
