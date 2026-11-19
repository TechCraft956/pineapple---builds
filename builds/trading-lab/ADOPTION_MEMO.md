# ADOPTION MEMO — localedge-site trading-lab (PR #2)
**To:** Airam — **From:** Everest (build BUILD-20261117-009) — **Date:** 2026-11-17

## What it is
A research-only futures lab (backtesting, risk, ML) for two discretionary
rule sets — **ES London sweep** and **CL opening range** — built around the
free London Strategic Edge market-data API. It is the only post-April-2026
work in your GitHub account (unmerged PR #2, branch
`claude/lse-trading-setup-dw4siy`, `TechCraft956/localedge-site`). **It does
not trade:** no broker connection, no orders, no funded account. It produces
evidence; a human places orders by hand.

## What it verifiably does (built + tested 2026-11-17, offline, no key)
- **Runs clean:** clean venv (Python 3.12.3), full pytest suite **263/263
  pass, 0 skipped**, with no LSE key and no network. Six invariants verified:
  UTC-internal with Chicago session windows (DST-safe — checked across the
  2024-03-10 spring-forward), CME day rolls at 17:00 CT, no lookahead
  (features + engine + release timestamps), pessimistic intrabar with
  ambiguous-bar counting, conservative cost defaults (ES $4.00 / CL $4.40
  round-turn, 1.0 tick slippage), results stamped with code params + a SHA-256
  fingerprint of the exact bars.
- **Data discipline is real:** continuity flagging correctly identifies a
  single-expiry series, a raw-stitched roll (+50 jump on an expiry date), and
  a back-adjusted series (negative prices) on synthetic fixtures. The live
  catalog audit refuses to run without a key and says exactly where to get one.
- **Config is sound:** `config.yaml` loads, unknown keys are rejected, and the
  one inconsistency found (a comment pointing at a nonexistent
  `scripts/measure_costs.py`) was a stale comment — fixed in the isolated copy.

## What it does not do
- No broker, no orders, no live data without a key (free key at
  londonstrategicedge.com/data — your step, never Everest's), no contact with
  Pineapple NEXT v1.2.0 or any live system, no feed wiring built in this build.
- **Two spec-vs-code findings** (recorded, not silently fixed): (1) the ES
  strategy computes its 15-bar prior swing from **London bars only**, so a
  sweep at 02:00 CT can never signal and sweeps before 02:15 use a truncated
  lookback — the code can emit signals the spec would not, and miss ones the
  spec would; (2) the CL strategies **do not skip news-blocked bars** when
  looking for a retest/reclaim — on inventory-report days the retest and
  failed-breakout variants will silently miss setups the spec says should
  fire. Both need a spec-or-code decision before any result from those
  strategies is trusted.
- Gaps to close on adoption: no shipped test crosses a DST boundary or asserts
  the result fingerprint (both behaviours verified in this build); the xgboost
  model rung is untested here (install failed on sandbox disk limits — the lab
  degrades gracefully without it); `features.py` uses a pandas call that a
  future pandas will remove.

## How it relates to the rest of Pineapple
A **sibling**, not a replacement: `pineapple-os/01_CORE/trading-os/` is a
separate stdlib toolkit (its own backtest engine, Monte Carlo, journal) with
no shared code, and the NEXT Research Lab is the production research system —
this lab must never be wired to NEXT, a broker, or a funded account. If
adopted, it becomes the Lab's **futures-research home**: data verification
and feed wiring would follow as separate briefs, after you hold the LSE key.

## Decision needed from Airam
**Adopt as the Lab's futures-research home** (next steps: you obtain the free
LSE key → data-verification brief → feed-wiring brief; Findings F-1/F-2 get a
spec-or-code ruling first), **or keep as reference-only recovery** (the code
stays catalogued and verified-offline, nothing further is built on it).
Either way, the LSE key is your step — Everest never creates accounts or
handles keys.
