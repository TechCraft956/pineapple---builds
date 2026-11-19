#!/usr/bin/env python3
"""
PINEAPPLE OS - Learning Loop.

This is the most important module: it makes the system get better. Every
recommendation the Decision Engine makes is logged. When you record what actually
happened, the system compares prediction vs outcome and nudges the quant weights -
so the next score is sharper. Measure everything; scores improve forever.

    python learning.py list                         # open recommendations awaiting outcome
    python learning.py record <id> --status sold --actual-roi 0.42 --notes "flipped in 9 days"
    python learning.py recalibrate                  # update quant weights from closed outcomes
    python learning.py stats

Statuses: recommended | acted | bought | sold | skipped | expired
Outcomes: 06_DECISION/outcomes_log.jsonl   Weights: 00_INDEX/quant_weights.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_lib"))
import pineapple_quant as pq  # noqa: E402

LOG = ROOT / "06_DECISION" / "outcomes_log.jsonl"
REPORT = ROOT / "06_DECISION" / "learning_report.md"
CLOSED = {"sold", "skipped", "expired"}


def _rows():
    if not LOG.exists():
        return []
    out = []
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def _write(rows):
    LOG.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def cmd_list():
    rows = [r for r in _rows() if r.get("status") == "recommended"]
    if not rows:
        print("No open recommendations. Run decision_engine.py first.")
        return
    print("Open recommendations (awaiting outcome):\n")
    for r in rows[-30:]:
        print("  %s  [%5.1f]  %-12s  %s" % (r["id"], r.get("predicted_quant", 0),
                                            r.get("category", ""), r.get("title", "")[:46]))
    print("\nRecord one:  python learning.py record <id> --status sold --actual-roi 0.40")


def cmd_record(args):
    rows = _rows()
    hit = False
    for r in rows:
        if r.get("id") == args.id:
            r["status"] = args.status
            if args.actual_roi is not None:
                r["actual_roi"] = args.actual_roi
            if args.notes:
                r["notes"] = args.notes
            hit = True
            break
    if not hit:
        print("id %s not found." % args.id)
        return
    _write(rows)
    print("Recorded %s -> %s (actual_roi=%s)" % (args.id, args.status, args.actual_roi))
    if args.status in CLOSED:
        print("Tip: run  python learning.py recalibrate  to update the scoring weights.")


def cmd_recalibrate():
    rows = [r for r in _rows() if r.get("status") in CLOSED and r.get("actual_roi") is not None]
    if len(rows) < 3:
        print("Need >=3 closed outcomes with actual_roi to recalibrate. Have %d." % len(rows))
        return
    # Correlate each dimension's value with realized ROI; shift weight toward dims
    # whose (favorable) value tracked good outcomes. Transparent, no ML deps.
    dims = pq.DIMENSIONS
    w = pq.load_weights()
    rois = [float(r["actual_roi"]) for r in rows]
    mean_roi = sum(rois) / len(rois)
    adjust = {}
    for d in dims:
        num = 0.0
        cnt = 0
        for r in rows:
            dv = r.get("dims", {}).get(d)
            if dv is None:
                continue
            eff = (100 - dv) if d in pq.LOWER_IS_BETTER else dv
            num += (eff - 50) * (float(r["actual_roi"]) - mean_roi)
            cnt += 1
        adjust[d] = (num / cnt) if cnt else 0.0
    # normalize adjustments into small weight nudges
    span = max(abs(v) for v in adjust.values()) or 1.0
    new_w = {}
    for d in dims:
        nudge = 0.04 * (adjust[d] / span)   # max +/-0.04 per cycle
        new_w[d] = max(0.04, w[d] + nudge)
    s = sum(new_w.values())
    new_w = {d: round(new_w[d] / s, 4) for d in dims}
    pq.save_weights(new_w, note="recalibrated from %d closed outcomes" % len(rows))

    lines = ["# Pineapple Learning Report", "",
             "Closed outcomes used: %d  ·  mean realized ROI: %.3f" % (len(rows), mean_roi), "",
             "| Dimension | old weight | new weight | signal->ROI corr |", "|---|---|---|---|"]
    for d in dims:
        lines.append("| %s | %.3f | %.3f | %+.1f |" % (d, w[d], new_w[d], adjust[d]))
    lines += ["", "Interpretation: dimensions with positive correlation got more weight;",
              "the next decision brief will rank using these sharpened weights."]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("Recalibrated. New weights:", new_w)
    print("Report: %s" % REPORT)


def cmd_stats():
    rows = _rows()
    by = {}
    for r in rows:
        by[r.get("status", "?")] = by.get(r.get("status", "?"), 0) + 1
    print("Outcomes log: %d total" % len(rows))
    for k, v in sorted(by.items()):
        print("  %-12s %d" % (k, v))
    closed = [r for r in rows if r.get("actual_roi") is not None]
    if closed:
        avg = sum(float(r["actual_roi"]) for r in closed) / len(closed)
        print("  mean realized ROI: %.3f (n=%d)" % (avg, len(closed)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list"); sub.add_parser("recalibrate"); sub.add_parser("stats")
    rec = sub.add_parser("record")
    rec.add_argument("id")
    rec.add_argument("--status", required=True)
    rec.add_argument("--actual-roi", type=float, default=None)
    rec.add_argument("--notes", default="")
    args = ap.parse_args()
    if args.cmd == "list": cmd_list()
    elif args.cmd == "record": cmd_record(args)
    elif args.cmd == "recalibrate": cmd_recalibrate()
    elif args.cmd == "stats": cmd_stats()
    else: ap.print_help()
