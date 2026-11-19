#!/usr/bin/env python3
"""Standalone CLI for the extracted Vehicle Financing Deal Optimizer.

Reads a JSON evaluation request, ranks the vehicle purchase scenarios with
payment math, and prints the ranked JSON result.

Usage:
    python3 vehicle_deals_cli.py --json request.json
    cat request.json | python3 vehicle_deals_cli.py --json -
    python3 vehicle_deals_cli.py --json request.json --output result.json

Input schema (same contract as the original POST /api/vehicle-deals/evaluate):
    {"deals": [{"listing_title": ..., "asking_price": ..., "year": ...,
                "make": ..., "model": ..., "mileage": ..., "apr": ...,
                "loan_term_months": ..., "down_payment": ...,
                "estimated_taxes_and_fees": ..., "distance_miles": ...,
                "estimated_fair_market_value": ..., ...}, ...]}

    1-10 deals per request. Pure function of its inputs: no network, no
    account, no state, no scraper/dashboard/Facebook imports.

Exit codes: 0 = evaluated OK; 2 = bad input (unreadable JSON or failed
validation — details on stderr, nothing on stdout).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from vehicle_deals import VehicleDealEvaluationRequest, evaluate_vehicle_deals


def _read_input(path: str) -> dict:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object with a 'deals' list")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank vehicle purchase scenarios (payment math, no network)."
    )
    parser.add_argument("--json", required=True,
                        help="path to the request JSON file, or '-' for stdin")
    parser.add_argument("--output",
                        help="write ranked JSON here instead of stdout")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent (default 2)")
    args = parser.parse_args(argv)

    try:
        data = _read_input(args.json)
        request = VehicleDealEvaluationRequest.model_validate(data)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read input: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"error: invalid request: {exc}", file=sys.stderr)
        return 2

    result = evaluate_vehicle_deals(request)
    text = result.model_dump_json(indent=args.indent)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
