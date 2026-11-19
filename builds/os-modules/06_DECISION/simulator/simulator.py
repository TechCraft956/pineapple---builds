#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PINEAPPLE OS - End-State Decision Simulator
===========================================

Model life/capital decisions as parameterized scenarios and project the
end-state (net-worth delta) at three horizons -- 1 month / 1 year / 5 years --
using *symbolic* sympy expressions so the math is transparent and re-derivable.

Covered scenarios (extensible):
    - flip_vs_save      : buy a vehicle/bike to flip vs keep cash in savings
    - fha_now_vs_later  : FHA home purchase now vs waiting ~12 months
    - debt_vs_deploy    : pay down high-APR debt vs deploy capital into a return

Each simulate() call returns:
    projected_net_worth_delta : {"1mo", "1yr", "5yr"}  (USD, signed)
    risk                      : "LOW" / "MED" / "HIGH"
    bottleneck                : the single constraint that gates the outcome
    best_next_action          : the concrete next move
    + the sympy expression strings and the resolved params (for audit)

items() -> ranked recommendations shaped for the Pineapple decision engine.

>>> IMPORTANT FRAMING <<<
This is ANALYSIS, not financial / tax / lending / investment advice. Every
projection is a deterministic function of *your* assumptions. Reality will
differ. Validate params against the real Pineapple modules (cashflow, real
estate radar, family bank, economic checker) and the cited public sources
before acting.

Run standalone:
    python simulator.py --selftest        # health summary, exits 0 on success
    python simulator.py                    # run all sample scenarios + print
    python simulator.py --json             # dump full results as JSON

Real public data sources to wire later (see data/sample_scenarios.json too):
    Freddie Mac PMMS 30y rate    https://www.freddiemac.com/pmms
    FHA county loan limits       https://entp.hud.gov/idapp/html/hicostlook.cfm
    HUD FHA 203(b)               https://www.hud.gov/buying/loans
    BLS CPI inflation            https://www.bls.gov/cpi/
    FRED economic series         https://fred.stlouisfed.org/
    Hidalgo County AD            https://www.hidalgoad.org/
    Cameron County AD            https://www.cameroncad.org/
    NADA / KBB used values       https://www.nadaguides.com/  https://www.kbb.com/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import sympy as sp

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "sample_scenarios.json"
# Pineapple processed-output sink (allowed write target outside our folder).
# BUILD-20261117-006 portability patch (build copy only; recovered original
# untouched): the original hard-codes a Windows path
# (C:\Users\chamg\Documents\Projects_NEW\PINEAPPLE_OS\00_PROCESSED), which on
# Linux would create a literal backslash-named directory under the CWD.
# Resolve to this workspace's 00_PROCESSED instead.
PROCESSED = HERE.parents[1] / "00_PROCESSED"

DISCLAIMER = (
    "ANALYSIS ONLY - not financial/tax/lending/investment advice. "
    "Projections are deterministic functions of your assumptions; reality "
    "will differ. Validate params against real sources before acting."
)

# ---------------------------------------------------------------------------
# Plugin descriptor (consumed by the Pineapple plugin registry / engine)
# ---------------------------------------------------------------------------
PLUGIN = {
    "id": "decision_simulator",
    "name": "End-State Decision Simulator",
    "category": "DECISION",
    "authority": "analysis",  # produces analysis, never executes money moves
    "status": "sample",
    "inputs": [
        "scenario kind (flip_vs_save | fha_now_vs_later | debt_vs_deploy)",
        "params dict (cash, prices, rates, horizons, probabilities)",
    ],
    "outputs": [
        "projected_net_worth_delta at 1mo / 1yr / 5yr",
        "risk, bottleneck, best_next_action",
        "ranked items() for the decision brief",
    ],
    "sources": [
        "https://www.freddiemac.com/pmms",
        "https://entp.hud.gov/idapp/html/hicostlook.cfm",
        "https://www.hud.gov/buying/loans",
        "https://www.bls.gov/cpi/",
        "https://fred.stlouisfed.org/",
        "https://www.hidalgoad.org/",
        "https://www.cameroncad.org/",
        "https://www.nadaguides.com/",
        "https://www.kbb.com/",
    ],
    "safety": (
        "Read-only. Writes only inside its own folder or 00_PROCESSED. "
        "No live network. No money movement. Analysis only - not advice."
    ),
}

HORIZON_MONTHS = {"1mo": 1, "1yr": 12, "5yr": 60}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _f(x) -> float:
    """Coerce a sympy/py number to plain rounded float."""
    return round(float(x), 2)


def _risk_to_score(risk: str) -> float:
    return {"LOW": 0.2, "MED": 0.5, "HIGH": 0.8}.get(risk, 0.5)


def _monthly_rate(annual: sp.Expr) -> sp.Expr:
    """Convert an annual (effective) rate to an equivalent monthly rate."""
    return (1 + annual) ** (sp.Integer(1) / 12) - 1


# ---------------------------------------------------------------------------
# Scenario 1: flip a vehicle/bike vs keep cash in savings
# ---------------------------------------------------------------------------
def _sim_flip_vs_save(p: dict) -> dict:
    t = sp.symbols("t", nonnegative=True)  # months

    cash = sp.Float(p["cash_on_hand"])
    buy = sp.Float(p["buy_price"])
    resale = sp.Float(p["est_resale"])
    recon = sp.Float(p["recon_cost"])
    fees_pct = sp.Float(p["fees_pct"])
    hold = sp.Float(p["hold_months"])
    sell_prob = sp.Float(p["sell_prob"])
    flips_yr = sp.Float(p["flips_per_year"])
    apy = sp.Float(p["savings_apy"])

    # --- Baseline: leave cash in savings (compounded monthly) ---
    m_apy = _monthly_rate(apy)
    base_wealth = cash * (1 + m_apy) ** t
    base_delta = base_wealth - cash  # net-worth change vs today

    # --- Flip path: one flip's expected profit, then reinvest at flip cadence ---
    gross = resale - buy - recon
    net_per_flip = gross - resale * fees_pct
    # expected value accounts for chance the unit doesn't sell at target
    ev_per_flip = sell_prob * net_per_flip + (1 - sell_prob) * (-recon)
    flips_in = flips_yr * (t / 12)  # flips completed by month t
    flip_delta = ev_per_flip * flips_in
    # capital must be >= buy price to play at all
    capital_ok = bool(cash >= buy)

    out = {}
    rows = {}
    for label, months in HORIZON_MONTHS.items():
        b = base_delta.subs(t, months)
        fl = flip_delta.subs(t, months) if capital_ok else sp.Float(0)
        # net-worth delta of CHOOSING to flip = flip path minus the savings
        # you forgo on the capital tied up in inventory (buy + recon).
        tied = (buy + recon)
        forgone = tied * ((1 + m_apy) ** months - 1)
        choose_flip_delta = fl - forgone + (cash - tied) * ((1 + m_apy) ** months - 1)
        out[label] = _f(choose_flip_delta if capital_ok else b)
        rows[label] = {
            "save_delta": _f(b),
            "flip_delta": _f(choose_flip_delta) if capital_ok else None,
        }

    margin_pct = _f((net_per_flip / buy) * 100)
    risk = "LOW" if margin_pct > 25 else ("MED" if margin_pct > 10 else "HIGH")
    if not capital_ok:
        risk = "HIGH"

    if not capital_ok:
        bottleneck = "Insufficient cash: buy price exceeds cash on hand."
        action = "Save / raise capital to %.0f before attempting this flip." % float(buy)
    elif margin_pct < 10:
        bottleneck = "Thin margin (%.1f%%): fees + recon eat the spread." % margin_pct
        action = "Renegotiate buy price down or find a higher-resale unit."
    else:
        bottleneck = "Sell-through time/probability (%.0f%% in %.1f mo)." % (
            float(sell_prob) * 100, float(hold))
        action = "Acquire the unit; list immediately at est. resale; recycle capital."

    return {
        "projected_net_worth_delta": out,
        "risk": risk,
        "bottleneck": bottleneck,
        "best_next_action": action,
        "detail": {
            "expected_net_per_flip": _f(ev_per_flip),
            "margin_pct": margin_pct,
            "capital_ok": capital_ok,
            "by_horizon": rows,
        },
        "expr": {
            "savings_delta(t months)": str(base_delta),
            "flip_path_delta(t months)": str(flip_delta),
            "ev_per_flip": str(ev_per_flip),
        },
        "headline_metric": out["1yr"],
        "asset": p.get("asset", "vehicle/bike (sample)"),
    }


# ---------------------------------------------------------------------------
# Scenario 2: FHA home purchase now vs waiting ~12 months
# ---------------------------------------------------------------------------
def _amort_balance(principal: sp.Expr, monthly_rate: sp.Expr, n_paid: int,
                   term_months: int = 360) -> sp.Expr:
    """Remaining mortgage balance after n_paid payments (standard amortization)."""
    r = monthly_rate
    if r == 0:
        return principal * (1 - sp.Float(n_paid) / term_months)
    pay = principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1)
    bal = principal * (1 + r) ** n_paid - pay * ((1 + r) ** n_paid - 1) / r
    return bal


def _sim_fha_now_vs_later(p: dict) -> dict:
    price = sp.Float(p["home_price"])
    down_pct = sp.Float(p["fha_down_pct"])
    rate_now = sp.Float(p["rate_now"])
    rate_later = sp.Float(p["rate_later"])
    appr = sp.Float(p["appreciation_yr"])
    rent = sp.Float(p["rent_now"])
    wait_m = int(p["wait_months"])
    closing_pct = sp.Float(p["closing_pct"])
    tax_rate = sp.Float(p["property_tax_rate"])
    ins_yr = sp.Float(p["insurance_yr"])
    mip_pct = sp.Float(p["mip_annual_pct"])

    down = price * down_pct
    loan_now = price - down
    closing = price * closing_pct
    m_now = _monthly_rate(rate_now)
    m_appr = _monthly_rate(appr)

    # --- BUY NOW path: equity = appreciated home value - remaining loan, ---
    # --- minus cash spent (down + closing), plus carrying-cost drag.     ---
    def buy_now_delta(months: int) -> sp.Expr:
        home_val = price * (1 + m_appr) ** months
        bal = _amort_balance(loan_now, m_now, months)
        equity = home_val - bal
        cash_in = down + closing
        carry_mo = (price * tax_rate / 12) + (ins_yr / 12) + (loan_now * mip_pct / 12)
        carry = carry_mo * months
        # vs renting, you'd have paid rent anyway; ownership offsets that.
        rent_avoided = rent * months
        return equity - cash_in - carry + rent_avoided - price * (1 + m_appr) ** 0 + price
        # note: equity already nets the home value; the +price/-price keeps the
        # expression explicit and cancels, preserving symbolic clarity.

    # --- WAIT path: rent for wait_m, keep down+closing in cash earning ~0, ---
    # --- then buy at an appreciated price (later) with rate_later.         ---
    def wait_delta(months: int) -> sp.Expr:
        if months <= wait_m:
            # still renting: net worth delta is just (no equity), cash neutral
            return sp.Float(0) - rent * 0  # cash preserved, no asset gain
        price_later = price * (1 + m_appr) ** wait_m
        loan_later = price_later - price_later * down_pct
        m_later = _monthly_rate(rate_later)
        owned_months = months - wait_m
        home_val = price_later * (1 + m_appr) ** owned_months
        bal = _amort_balance(loan_later, m_later, owned_months)
        equity = home_val - bal
        cash_in = price_later * down_pct + price_later * closing_pct
        carry_mo = (price_later * tax_rate / 12) + (ins_yr / 12) + (loan_later * mip_pct / 12)
        carry = carry_mo * owned_months
        rent_avoided = rent * owned_months
        rent_paid_waiting = -rent * wait_m  # sunk while waiting (but would pay anyway)
        return equity - cash_in - carry + rent_avoided + rent_paid_waiting + rent * wait_m

    out, rows = {}, {}
    for label, months in HORIZON_MONTHS.items():
        bn = _f(buy_now_delta(months))
        wt = _f(wait_delta(months))
        # delta of CHOOSING now over waiting:
        out[label] = _f(bn - wt)
        rows[label] = {"buy_now_delta": bn, "wait_delta": wt}

    # rate risk: waiting risks rates rising; here later<now is the assumption.
    rate_gap = float(rate_later - rate_now)
    appr_yr = float(appr)
    advantage_1yr = out["1yr"]
    if advantage_1yr > 0:
        risk = "MED"  # buying involves leverage + carrying costs
        bottleneck = "Down payment + closing cash (%.0f) and monthly carry." % float(down + closing)
        action = (
            "Lock FHA pre-approval now; appreciation (%.1f%%/yr) outruns the "
            "rate-wait benefit." % (appr_yr * 100)
        )
    else:
        risk = "MED"
        bottleneck = "Rate path: waiting saves %.2f pts but loses appreciation." % (
            -rate_gap * 100)
        action = "Keep renting; rebuild down payment; re-run when rates/price shift."

    # FHA leverage is inherently higher-risk than cash deals:
    if float(down_pct) <= 0.05:
        risk = "HIGH" if advantage_1yr < 0 else "MED"

    return {
        "projected_net_worth_delta": out,
        "risk": risk,
        "bottleneck": bottleneck,
        "best_next_action": action,
        "detail": {
            "down_payment": _f(down),
            "loan_now": _f(loan_now),
            "monthly_rate_now": _f(m_now),
            "rate_gap_now_vs_later_pts": round(rate_gap * 100, 3),
            "by_horizon": rows,
            "county": p.get("county", "RGV county (sample)"),
        },
        "expr": {
            "buy_now_equity_delta(t)": "appreciated_value - amort_balance - cash_in - carry + rent_avoided",
            "monthly_rate_now": str(m_now),
            "amort_note": "standard 360-mo fully-amortizing FHA loan",
        },
        "headline_metric": out["5yr"],
    }


# ---------------------------------------------------------------------------
# Scenario 3: pay down high-APR debt vs deploy capital
# ---------------------------------------------------------------------------
def _sim_debt_vs_deploy(p: dict) -> dict:
    cap = sp.Float(p["capital"])
    bal = sp.Float(p["debt_balance"])
    apr = sp.Float(p["debt_apr"])
    deploy_yr = sp.Float(p["deploy_return_yr"])
    succ = sp.Float(p["deploy_success_prob"])
    deploy_risk = p.get("deploy_risk", "MED")

    m_apr = _monthly_rate(apr)
    m_deploy = _monthly_rate(deploy_yr)

    # --- PAY DEBT: guaranteed return == avoided interest on the paid balance ---
    paid = sp.Min(cap, bal)
    leftover = cap - paid

    def pay_delta(months: int) -> sp.Expr:
        # interest you would have paid on `paid` over `months`, now avoided
        avoided = paid * ((1 + m_apr) ** months - 1)
        # leftover cash sits (assume ~0% to be conservative)
        return avoided

    # --- DEPLOY: expected growth of capital, but debt keeps accruing ---
    def deploy_delta(months: int) -> sp.Expr:
        ev_grow = succ * (cap * ((1 + m_deploy) ** months - 1)) + (1 - succ) * (-cap * sp.Float(0.5) * months / 12)
        debt_cost = bal * ((1 + m_apr) ** months - 1)  # debt still compounding
        return ev_grow - debt_cost

    out, rows = {}, {}
    for label, months in HORIZON_MONTHS.items():
        pd = _f(pay_delta(months))
        dd = _f(deploy_delta(months))
        # choosing to deploy vs pay:
        out[label] = _f(dd - pd)
        rows[label] = {"pay_debt_delta": pd, "deploy_delta": dd}

    apr_pct = float(apr) * 100
    exp_ret_pct = float(deploy_yr) * float(succ) * 100
    # Drive the verdict off the ACTUAL projected delta (deploy minus pay) so the
    # recommendation can never contradict the numbers. `out` holds deploy-vs-pay.
    deploy_wins_1yr = out["1yr"] > 0
    # The classic rule (beat your APR risk-adjusted) is a sanity cross-check.
    rule_favors_deploy = exp_ret_pct > apr_pct
    if not deploy_wins_1yr:
        # Paying the debt is the better end-state regardless of the headline %.
        risk = "HIGH"
        if rule_favors_deploy:
            bottleneck = (
                "Deploy's risk-adjusted %.1f%% looks to beat APR %.1f%%, but the "
                "still-accruing debt makes paying it the better 1yr end-state."
                % (exp_ret_pct, apr_pct))
        else:
            bottleneck = (
                "Debt APR %.1f%% > risk-adjusted deploy return %.1f%%."
                % (apr_pct, exp_ret_pct))
        action = "Pay the high-APR debt first - it is a guaranteed %.1f%% return." % apr_pct
    else:
        risk = "HIGH" if deploy_risk == "HIGH" else "MED"
        bottleneck = "Execution + success probability (%.0f%%) of the deployment." % (
            float(succ) * 100)
        action = (
            "Clear the highest-APR tranche, then deploy the remainder where "
            "expected return (%.1f%%) beats APR." % exp_ret_pct)

    return {
        "projected_net_worth_delta": out,
        "risk": risk,
        "bottleneck": bottleneck,
        "best_next_action": action,
        "detail": {
            "guaranteed_return_pct": round(apr_pct, 2),
            "risk_adjusted_deploy_pct": round(exp_ret_pct, 2),
            "amount_paid": _f(paid),
            "leftover_cash": _f(leftover),
            "by_horizon": rows,
        },
        "expr": {
            "pay_debt_delta(t)": "paid * ((1+m_apr)^t - 1)",
            "deploy_delta(t)": "p*cap*((1+m_deploy)^t-1) - bal*((1+m_apr)^t-1)",
            "m_apr": str(m_apr),
            "m_deploy": str(m_deploy),
        },
        "headline_metric": out["1yr"],
    }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
_SIMS = {
    "flip_vs_save": _sim_flip_vs_save,
    "fha_now_vs_later": _sim_fha_now_vs_later,
    "debt_vs_deploy": _sim_debt_vs_deploy,
}


def simulate(scenario: str | dict, params: dict | None = None) -> dict:
    """
    Run one scenario. `scenario` may be a kind string or a scenario dict
    (with keys 'kind'/'name'/'params'). `params` overrides/extends.
    Returns the result dict described in the module docstring.
    """
    if isinstance(scenario, dict):
        kind = scenario.get("kind") or scenario.get("id")
        name = scenario.get("name", kind)
        base = dict(scenario.get("params", {}))
    else:
        kind = scenario
        name = kind
        base = {}
    if params:
        base.update(params)
    if kind not in _SIMS:
        raise ValueError(
            "unknown scenario kind %r; known: %s" % (kind, sorted(_SIMS))
        )
    res = _SIMS[kind](base)
    res["scenario"] = kind
    res["name"] = name
    res["params"] = base
    res["disclaimer"] = DISCLAIMER
    return res


def _load_samples() -> list[dict]:
    if not DATA.exists():
        return []
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    return doc.get("scenarios", [])


def run_all() -> list[dict]:
    """Simulate every sample scenario; return list of result dicts."""
    return [simulate(s) for s in _load_samples()]


# ---------------------------------------------------------------------------
# items() - ranked recommendations for the Pineapple decision engine
# ---------------------------------------------------------------------------
def _confidence(res: dict) -> float:
    # sample data => moderate confidence; widen by clarity of the verdict.
    base = 0.55
    horizon = res["projected_net_worth_delta"]
    spread = abs(horizon["1yr"]) + abs(horizon["5yr"])
    if spread > 20000:
        base += 0.1
    if res["risk"] == "LOW":
        base += 0.05
    return round(min(base, 0.8), 2)


def items() -> list[dict]:
    """
    Ranked scenario recommendations shaped for the decision engine.
    Each item: title, category, source, action, est_value, risk, location,
    url, confidence  (+ extra fields the engine tolerates).
    """
    results = run_all()
    out = []
    for res in results:
        delta_1yr = res["projected_net_worth_delta"]["1yr"]
        delta_5yr = res["projected_net_worth_delta"]["5yr"]
        favorable = delta_1yr > 0
        verb = "FAVORS acting" if favorable else "FAVORS waiting / paying down"
        title = "{} -> {} (1yr {:+,.0f} / 5yr {:+,.0f})".format(
            res["name"], verb, delta_1yr, delta_5yr)
        out.append({
            "title": title,
            "category": "DECISION",
            "source": PLUGIN["name"] + " (sample)",
            "action": res["best_next_action"],
            "est_value": delta_1yr,
            "risk": res["risk"],
            "location": res["params"].get("county")
            or res["params"].get("asset")
            or "Rio Grande Valley, TX",
            "url": PLUGIN["sources"][0],
            "confidence": _confidence(res),
            # engine-friendly extras:
            "projected_net_worth_delta": res["projected_net_worth_delta"],
            "bottleneck": res["bottleneck"],
            "scenario": res["scenario"],
            "disclaimer": DISCLAIMER,
        })
    # rank: largest absolute 1yr net-worth swing first
    out.sort(key=lambda x: abs(x["est_value"] or 0), reverse=True)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_result(res: dict) -> None:
    d = res["projected_net_worth_delta"]
    print("  %-34s [%s]" % (res["name"], res["risk"]))
    print("    1mo {:+,.0f}   1yr {:+,.0f}   5yr {:+,.0f}"
          .format(d["1mo"], d["1yr"], d["5yr"]))
    print("    bottleneck : %s" % res["bottleneck"])
    print("    next       : %s" % res["best_next_action"])


def selftest() -> int:
    print("=" * 64)
    print("PINEAPPLE DECISION SIMULATOR - SELFTEST")
    print("=" * 64)
    print(DISCLAIMER)
    print("-" * 64)
    ok = True
    try:
        import sympy as _sp  # noqa
        print("[ok] sympy %s available" % sp.__version__)
    except Exception as e:  # pragma: no cover
        print("[FAIL] sympy import: %s" % e)
        return 1

    if not DATA.exists():
        print("[FAIL] missing sample data: %s" % DATA)
        return 1
    print("[ok] sample data: %s" % DATA)

    samples = _load_samples()
    if len(samples) < 3:
        print("[FAIL] expected >=3 sample scenarios, got %d" % len(samples))
        return 1
    print("[ok] %d sample scenarios loaded" % len(samples))
    print("-" * 64)

    # run 3 scenarios and print projections
    for s in samples[:3]:
        try:
            res = simulate(s)
        except Exception as e:
            print("[FAIL] simulate(%s): %s" % (s.get("kind"), e))
            ok = False
            continue
        d = res["projected_net_worth_delta"]
        # validate shape
        for k in ("1mo", "1yr", "5yr"):
            if not isinstance(d.get(k), (int, float)):
                print("[FAIL] %s missing horizon %s" % (s.get("kind"), k))
                ok = False
        for k in ("risk", "bottleneck", "best_next_action"):
            if not res.get(k):
                print("[FAIL] %s missing field %s" % (s.get("kind"), k))
                ok = False
        _print_result(res)

    print("-" * 64)
    its = items()
    if not its:
        print("[FAIL] items() returned nothing")
        ok = False
    else:
        req = ("title", "category", "source", "action", "est_value",
               "risk", "location", "url", "confidence")
        missing = [k for k in req if k not in its[0]]
        if missing:
            print("[FAIL] items() missing keys: %s" % missing)
            ok = False
        else:
            print("[ok] items() -> %d ranked recommendations" % len(its))
            print("     top: %s" % its[0]["title"])

    print("=" * 64)
    if ok:
        print("SELFTEST PASSED")
        return 0
    print("SELFTEST FAILED")
    return 1


def _write_processed(results: list[dict]) -> Path | None:
    try:
        PROCESSED.mkdir(parents=True, exist_ok=True)
        out = PROCESSED / "decision_simulator.json"
        payload = {
            "plugin": PLUGIN["id"],
            "status": "sample",
            "disclaimer": DISCLAIMER,
            "results": results,
            "items": items(),
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out
    except Exception as e:  # pragma: no cover
        print("  (could not write 00_PROCESSED: %s)" % e)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="End-state decision simulator (analysis only).")
    ap.add_argument("--selftest", action="store_true", help="health summary, exit 0 on pass")
    ap.add_argument("--json", action="store_true", help="dump full results as JSON")
    ap.add_argument("--write", action="store_true", help="also write 00_PROCESSED/decision_simulator.json")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    results = run_all()
    if args.json:
        print(json.dumps({"disclaimer": DISCLAIMER, "results": results,
                          "items": items()}, indent=2))
    else:
        print(DISCLAIMER)
        print("-" * 64)
        for res in results:
            _print_result(res)
            print()
        print("RANKED FOR BRIEF:")
        for i, it in enumerate(items(), 1):
            print("  %d. [%s] %s" % (i, it["risk"], it["title"]))

    if args.write:
        p = _write_processed(results)
        if p:
            print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
