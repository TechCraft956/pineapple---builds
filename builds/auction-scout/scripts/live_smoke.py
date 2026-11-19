#!/usr/bin/env python3
"""Live smoke for Auction Scout: runs the wired pulls for real, probes the
NOT WIRED stubs once each, merges into finds.json (dedupe/update in place)
and renders FINDS.md. Reports real counts per source; zero is a valid,
honest answer for a walled source.

Usage: python3 scripts/live_smoke.py
Writes only inside the auction-scout build workspace.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import auction_scout as scout  # noqa: E402

CACHE = os.path.join(ROOT, "cache")


def main() -> int:
    with open(os.path.join(ROOT, "sources.json")) as fh:
        registry = {s["id"]: s for s in json.load(fh)["sources"]}

    now = scout.utc_now()
    now_iso = scout.iso_z(now)
    results = []

    ps = scout.fetch_publicsurplus(cache_dir=os.path.join(CACHE, "publicsurplus"))
    results.append(ps)
    print(f"publicsurplus: {ps['status']} — {len(ps['finds'])} finds "
          f"({ps.get('raw_lot_count')} raw Texas lots across keyword searches; "
          f"all kept — no category filter), HTTP {ps['http_statuses']}")

    gsa = scout.fetch_gsa(cache_dir=os.path.join(CACHE, "gsa"))
    results.append(gsa)
    print(f"gsa: {gsa['status']} — {len(gsa['finds'])} finds across "
          f"{gsa.get('pages_fetched')} page(s) "
          f"(totalElements={gsa.get('total_elements')}), HTTP {gsa['http_statuses']}")

    for source_id in ("govplanet", "txsurplus"):
        stub = scout.NotWiredFetcher(registry[source_id]).fetch(
            probe=True, cache_dir=os.path.join(CACHE, source_id))
        results.append(stub)
        probe = stub["evidence"].get("live_probe", {})
        print(f"{source_id}: NOT WIRED — 0 finds. Live probe: {probe}")

    new_finds = [f for r in results for f in r.get("finds", [])]

    finds_path = os.path.join(ROOT, "finds.json")
    existing = []
    if os.path.exists(finds_path):
        with open(finds_path) as fh:
            existing = json.load(fh).get("finds", [])
    merged = scout.merge_finds(existing, new_finds, now_iso)

    source_status = [{
        "source": r["source"], "status": r["status"],
        "reason": r.get("reason", ""), "finds": r.get("finds", []),
        "total_elements": r.get("total_elements"),
    } for r in results]

    with open(finds_path, "w") as fh:
        json.dump({
            "generated_at_utc": now_iso,
            "warning": scout.WARNING_LABEL,
            "sources": [{k: v for k, v in s.items() if k != "finds"} |
                        {"find_count_this_run": len(s["finds"])} for s in source_status],
            "finds": scout.sort_open(merged),
        }, fh, indent=2)

    # FINDS.md renders THIS RUN's pull (not the accumulated store), so
    # the report's pulled count always equals its shown count.
    with open(os.path.join(ROOT, "FINDS.md"), "w") as fh:
        fh.write(scout.render_digest(new_finds, source_status, now))

    print(f"\nTotal finds in finds.json: {len(merged)} "
          f"({len(new_finds)} pulled this run, all of them in FINDS.md)")
    for r in results:
        if r.get("finds"):
            s = r["finds"][0]
            print(f"Sample ({r['source']}): {s['title']} — lot {s['lot_id']}, "
                  f"bid {s['current_bid_usd']}, closes {s['closing_at_utc']}, "
                  f"location {s['location']}, {s['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
