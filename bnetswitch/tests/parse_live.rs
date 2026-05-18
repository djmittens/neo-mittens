//! Dump parsed rank ranges for every description currently in bnetswitch.
//! Run: cargo test --test parse_live -- --nocapture --test-threads=1

#[path = "../src/lfg_parse.rs"]
#[allow(dead_code)]
mod lfg_parse;
#[path = "../src/ranks.rs"]
#[allow(dead_code)]
mod ranks;

use lfg_parse::parse_description;
use std::io::BufRead;

#[test]
fn dump_live_lfg_parses() {
    let f = std::fs::File::open("/tmp/live_descs.txt").unwrap();
    for line in std::io::BufReader::new(f).lines() {
        let desc = line.unwrap();
        let p = parse_description(&desc);
        let rng = match (p.rank_min, p.rank_max) {
            (Some(a), Some(b)) if a == b => a.label(),
            (Some(a), Some(b)) => format!("{} - {}", a.label(), b.label()),
            (Some(a), None) | (None, Some(a)) => a.label(),
            _ => "?".to_string(),
        };
        println!("{:25}  {:?}", rng, desc);
    }
}
