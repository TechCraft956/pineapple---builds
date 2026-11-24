# Market Context Board — Research and Integration Brief

Status: research draft, 2026-11-24. No live data integration or trading logic is claimed.

## Goal

Help the operator assess context, price location, regime, catalysts, liquidity and a small number of meaningful levels. Build on the existing Pineapple trading lab and cockpit surfaces. Treat the on-chart board as a compact view; preserve detailed quantitative evidence, sources and diagnostics in the external dashboard.

## Evidence-first workstreams

1. Volume profile: identify the exact instrument, range, session and data source before labeling POC, VAH or VAL. Compare location, distance and reactions; avoid treating profile or overlapping VWAP bands as independent votes.
2. Order flow and DOM: separately identify executed trades, bid/ask aggregation (MBP) and order-level MBO; document exchange, venue, instrument, feed entitlement, depth, timestamps and gaps. Resting liquidity can cancel and inferred absorption/icebergs are hypotheses, not identity or intent.
3. Options flow and modeled positioning: retain trade timing, volume, open-interest settlement date, bid/ask context, expiry, strike, multiplier, IV and gamma. Trade-side classifications and dealer positioning are estimates, not facts. Keep stock/index option units distinct from futures price units; verify a timestamped basis before any conversion.
4. Edge research: preserve practitioner interviews, existing chart-based setups and previous quantitative experiments. Frame each idea as a falsifiable, time-stamped hypothesis with benchmark, opportunity count, fill assumptions, transaction costs, drawdown and chronological holdout. Compare incremental contribution; do not stack correlated confirmations.
5. Visuals: deliver a useful 2D context/location/levels view first, with optional details for profile, options distribution, and book data. Explore 3D for specific surfaces (strike × expiry × IV or exposure), with a 2D slice and accessible labels. A heatmap is useful for resting-liquidity behavior only when actual timestamped depth history exists; no fabricated order book.

## Existing sources to evaluate, not dependencies

- GammaGrid: https://github.com/gammagrid/gammagrid — exposure, IV surface, snapshot history; AGPL-3.0, review license before reuse; snapshot feed rather than actual dealer book.
- SPX gamma levels: https://github.com/dhawalc/spx-gamma-levels — daily modeled SPX walls and flip; inspect date, OI settlement, expiry scope, definition and license; do not treat as current futures levels without basis.
- Open DOM Heatmap: https://github.com/HannesKapsch/open-dom-heatmap — MIT visualization engine, bring your own depth data; synthetic/crypto examples do not establish CME futures depth access.
- Enrico Stucchi interview: https://www.youtube.com/watch?v=KaDDfmcQUKA — practitioner source for regime, order-flow and options-hedging hypotheses, not audited performance.
- CME MBO reference: https://www.cmegroup.com/articles/faqs/market-by-order-mbo.html — market-by-order mechanics.

## Data and provenance contract

Every captured metric should include instrument and venue, contract/expiry, value and units, source, source-as-of, observed-at, session/timezone, derivation/model/version, assumptions and expiry/validity. Volume profile adds session/range; options adds OI effective date and chain coverage; DOM adds depth scope, aggregation, snapshot/delta sequence and gap state. Missing values remain unknown, never simulated as live.

## Next small tests

- Inventory the available order-flow and options datasets in the current runtime and record entitlements, fields and timestamp quality.
- Trace existing Pineapple dashboard components and the trading lab; do not claim repository code is a deployed service.
- Compare a single context-and-location method against the same method plus one order-flow feature. Freeze classification before the outcome window and compare net cost-aware results and skipped trades.
- Display one independently timestamped external wall in a research view, with model/provider/date and contract/basis; validate against original source and label stale values.
- Test the Pine board on a reversible research layout, including indicator-slot behavior, compile, chart session, prior-day bounds, and manual input provenance. Direct Sheet-to-Pine synchronization is not established.

No automated orders, brokerage login, production schedule change or subscription purchase is implied by this research brief.
