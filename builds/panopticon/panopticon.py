#!/usr/bin/env python3
"""Panopticon CLI.

  python3 panopticon.py plan <type> <subject> [--purpose "..."]
  python3 panopticon.py username <name> --purpose "..." [--out DIR]
  python3 panopticon.py place <place...> [--out DIR]
  python3 panopticon.py brief <findings.json>   (normalized items -> brief.md on stdout)
  python3 panopticon.py selftest

Username enumeration requires a documented legitimate purpose (v1.1, GPT
gate 1): without --purpose the plan/run is refused. Live runs hit public
endpoints only — no logins, no credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from panopticon import brief as brief_mod  # noqa: E402
from panopticon import planner  # noqa: E402
from panopticon.ethics import EthicsViolation, PurposeRequiredError  # noqa: E402
from panopticon.normalize import normalize_all  # noqa: E402
from panopticon.registry import load_registry  # noqa: E402
from panopticon.runners import place as place_runner  # noqa: E402
from panopticon.runners import username as username_runner  # noqa: E402


def _emit(findings, subject, stype, reg, purpose, out_dir):
    items = normalize_all(findings)
    steps = planner.plan(stype, subject, reg, purpose)
    sk = planner.skipped(reg, stype, purpose)
    text = brief_mod.render(subject, stype, items, steps, sk, purpose)
    if out_dir:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "_" for c in subject).strip("_")
        (d / ("findings_%s.json" % slug)).write_text(
            json.dumps(items, indent=2), encoding="utf-8")
        (d / ("brief_%s.md" % slug)).write_text(text, encoding="utf-8")
        print("wrote findings + brief to %s" % d)
    print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="panopticon")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("type"); p.add_argument("subject")
    p.add_argument("--purpose", default=None)
    u = sub.add_parser("username"); u.add_argument("subject")
    u.add_argument("--purpose", default=None)
    u.add_argument("--out", default=None)
    pl = sub.add_parser("place"); pl.add_argument("subject", nargs="+")
    pl.add_argument("--out", default=None)
    b = sub.add_parser("brief"); b.add_argument("findings")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)

    reg = load_registry()
    if args.cmd == "plan":
        try:
            steps = planner.plan(args.type, args.subject, reg, args.purpose)
        except PurposeRequiredError as e:
            print("refused: %s" % e, file=sys.stderr)
            return 2
        print(json.dumps({"subject": args.subject, "type": args.type,
                          "purpose": args.purpose, "steps": steps,
                          "skipped": planner.skipped(reg, args.type, args.purpose)},
                         indent=2))
        return 0
    if args.cmd == "username":
        if not args.purpose:
            print("refused: username enumeration needs a documented legitimate "
                  "purpose — re-run with --purpose \"...\" (user-owned account "
                  "or public professional/organizational subject only; no "
                  "cross-site private-person profiles).", file=sys.stderr)
            return 2
        try:
            findings = username_runner.run(args.subject, purpose=args.purpose)
        except (PurposeRequiredError, ValueError) as e:
            print("refused: %s" % e, file=sys.stderr)
            return 2
        return _emit(findings, args.subject, "username", reg, args.purpose, args.out)
    if args.cmd == "place":
        subject = " ".join(args.subject)
        findings = place_runner.run(subject)
        return _emit(findings, subject, "place", reg, None, args.out)
    if args.cmd == "brief":
        items = json.loads(Path(args.findings).read_text(encoding="utf-8"))
        subj = items[0]["subject"] if items else "?"
        stype = items[0]["subject_type"] if items else "?"
        try:
            print(brief_mod.render(subj, stype, items), end="")
        except EthicsViolation as e:
            print("refused: %s" % e, file=sys.stderr)
            return 3
        return 0
    if args.cmd == "selftest":
        n = len(reg["sources"])
        steps = planner.plan("username", "selftest", reg,
                             purpose="selftest: pipeline smoke check")
        assert any(s["runnable"] for s in steps), "no runnable step in username plan"
        print("selftest OK: registry %d sources; username plan %d steps" % (n, len(steps)))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
