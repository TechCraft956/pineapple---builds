"""Sensor #31 — Government contracts and grants (USAspending), Starr County focus.

Read-only collector over the USAspending API v2 (keyless, no signup):

    POST https://api.usaspending.gov/api/v2/search/spending_by_award/
    POST https://api.usaspending.gov/api/v2/search/spending_by_award_count/

Scope: awards whose RECIPIENT is located in Starr County, Texas
(FIPS 48427; the API takes the 3-digit county code ``427`` with
``state: "TX"``). Two award groups are fetched separately because the
API rejects a request whose ``award_type_codes`` mix groups
(verified live 2026-11-26: mixed codes -> HTTP 422
"'award_type_codes' must only contain types from one group"):

* contracts: A (BPA Call), B (Purchase Order), C (Delivery Order),
  D (Definitive Contract)
* grants:    02 (Block Grant), 03 (Formula Grant), 04 (Project Grant),
  05 (Cooperative Agreement)

Relationship to sensor #7 (``builds/regint-econ/.../contracts_feed.py``):
#7 already wires USAspending, but contracts-only, place-of-performance
filter, single page, no grants. #31 is NOT a duplicate: it adds the
grants group (816 of 942 all-time Starr County awards), switches the
filter to recipient location, and paginates with an explicit cap.
The request shape and the 3-digit county code were reused from #7's
verified-live adapter; nothing else is shared.

Observation quality labels (never invent data; a missing field stays
missing, never zero-filled):

* VERIFIED — Award ID, Recipient Name, Award Amount and Start Date
  are all present in the API record.
* REPORTED — Award ID present, but Award Amount or Start Date (or
  both) missing from the API record. ``value`` is None, not 0.
* UNKNOWN  — Award ID present, but Recipient Name AND Award Amount
  are both missing: the record exists but says nothing usable.
* Rows with no Award ID at all cannot be keyed; they are skipped and
  counted in ``skipped_no_award_id``.

Notes on API-supplied values that look like missing data but are not:

* Recipient Name ``"REDACTED DUE TO PII"`` is a real API value (USDA
  Very Low Income Housing Repair loans/grants to individuals). It is
  kept verbatim and flagged ``recipient_redacted: true``; it is NOT
  treated as a missing recipient.
* ``"Award Type"`` and ``"recipient_location"`` fields come back null
  from this endpoint even on valid records; they are not requested
  and not relied on.

Pagination limitation (recorded honestly, not silently truncated):
the API's ``hasNext`` flag is reported unreliable past ~10,000
results. This collector pages until ``hasNext`` is false OR until
``MAX_PAGES`` (default 20 pages x 100 records = 2,000 records per
group) is reached. If the cap is hit while ``hasNext`` is still true
the run is flagged ``truncated: true`` with the page count, and the
README/evidence say so. Starr County volumes are far below the cap
(142 awards in the 2025-01-01..2026-11-26 window; 942 all-time),
so truncation is not expected here — but the guard is real.

Cost: $0. No signup, no API key, no spending, no account creation,
no contacting anyone. Read-only GET-equivalent POSTs to a public API.

Usage:
    python3 usaspending.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                           [--out FILE.json] [--max-pages N] [--limit N]
Defaults: trailing 365 days ending today, JSON report on stdout.
Exit code 0 on a completed run (even with zero awards); non-zero with
a BLOCKED report on stdout/stderr when the API is unreachable or
returns an auth/HTTP error — no workaround is attempted.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.error
import urllib.request

SENSOR_ID = 31
API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
COUNT_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
AWARD_PAGE_URL = "https://www.usaspending.gov/award/"

STATE = "TX"
COUNTY_FIPS3 = "427"          # Starr County: full FIPS 48427; API wants 3 digits
COUNTY_FIPS5 = "48427"
COUNTY_NAME = "Starr County"

# Award-type groups. NEVER mix groups in one request (API returns 422).
CONTRACT_CODES = ["A", "B", "C", "D"]
GRANT_CODES = ["02", "03", "04", "05"]
GROUPS = {"contracts": CONTRACT_CODES, "grants": GRANT_CODES}

FIELDS = ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
          "Awarding Sub Agency", "Start Date", "End Date", "Description"]

USER_AGENT = "PineappleSensor31/1.0 (read-only research collector; usaspending.gov)"
DEFAULT_LIMIT = 100
DEFAULT_MAX_PAGES = 20
REDACTED_RECIPIENT = "REDACTED DUE TO PII"


class BlockedError(RuntimeError):
    """The live source is unreachable or refused the request.

    Raised instead of building any workaround. Callers report this as
    BLOCKED-needs-feed with the attached evidence.
    """


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_window(today: _dt.date | None = None) -> tuple[str, str]:
    end = today or _dt.date.today()
    return ((end - _dt.timedelta(days=365)).isoformat(), end.isoformat())


def build_request(group: str, start: str, end: str,
                  page: int = 1, limit: int = DEFAULT_LIMIT) -> dict:
    """One single-group search request (recipient location, Starr County)."""
    if group not in GROUPS:
        raise ValueError(f"unknown award group {group!r}; expected one of {sorted(GROUPS)}")
    return {
        "filters": {
            "recipient_locations": [{"country": "USA", "state": STATE,
                                     "county": COUNTY_FIPS3}],
            "award_type_codes": list(GROUPS[group]),
            "time_period": [{"start_date": start, "end_date": end}],
        },
        "fields": list(FIELDS),
        "limit": limit,
        "page": page,
        "sort": "Start Date",
        "order": "desc",
    }


def build_count_request(group: str, start: str | None = None,
                        end: str | None = None) -> dict:
    """Count request for one group; no time_period = all-time total."""
    body: dict = {
        "filters": {
            "recipient_locations": [{"country": "USA", "state": STATE,
                                     "county": COUNTY_FIPS3}],
            "award_type_codes": list(GROUPS[group]),
        }
    }
    if start is not None and end is not None:
        body["filters"]["time_period"] = [{"start_date": start, "end_date": end}]
    return body


def default_post(url: str, body: dict) -> dict:
    """POST JSON, return parsed JSON. HTTP/auth failures -> BlockedError."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise BlockedError(
            f"USAspending API HTTP {exc.code} on {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BlockedError(
            f"USAspending API unreachable at {url}: {exc.reason}") from exc


def award_url(record: dict) -> str:
    """Public award page when the API gives an internal id, else the API URL."""
    gen_id = record.get("generated_internal_id")
    if gen_id:
        return f"{AWARD_PAGE_URL}{gen_id}"
    return API_URL


def quality_of(record: dict) -> str:
    """VERIFIED / REPORTED / UNKNOWN per the module docstring rules."""
    has_amount = record.get("Award Amount") is not None
    has_start = bool(record.get("Start Date"))
    has_recipient = bool(record.get("Recipient Name"))
    if has_amount and has_start and has_recipient:
        return "VERIFIED"
    if not has_amount and not has_recipient:
        return "UNKNOWN"
    return "REPORTED"


def normalize_record(record: dict, group: str, retrieved_at: str) -> dict | None:
    """One API result row -> one observation dict, or None if unkeyable.

    Missing fields stay None; amounts are never zero-filled.
    """
    award_id = record.get("Award ID")
    if not award_id:
        return None
    recipient = record.get("Recipient Name")
    amount = record.get("Award Amount")
    try:
        amount = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount = None
    return {
        "obs_id": f"OBS-S{SENSOR_ID:02d}-USASPENDING-{award_id}",
        "sensor_id": SENSOR_ID,
        "group": group,
        "award_id": award_id,
        "recipient_name": recipient,
        "recipient_redacted": recipient == REDACTED_RECIPIENT,
        "award_amount_usd": amount,
        "awarding_agency": record.get("Awarding Agency"),
        "awarding_sub_agency": record.get("Awarding Sub Agency"),
        "start_date": record.get("Start Date"),
        "end_date": record.get("End Date"),
        "description": record.get("Description"),
        "quality": quality_of(record),
        "source_name": "USAspending API v2",
        "source_url": award_url(record),
        "retrieved_at_utc": retrieved_at,
        "geo": f"{COUNTY_NAME}, {STATE} (FIPS {COUNTY_FIPS5})",
    }


def fetch_group(group: str, start: str, end: str, retrieved_at: str,
                post=None, limit: int = DEFAULT_LIMIT,
                max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """Page one award group until hasNext is false or the cap is hit.

    Returns {"observations": [...], "pagination": {...},
    "skipped_no_award_id": int}. ``truncated`` is True only when the
    cap stopped the walk while the API still said there was more.
    """
    post = post or default_post
    observations: list[dict] = []
    skipped = 0
    pages_fetched = 0
    has_next_at_stop: bool | None = None
    for page in range(1, max_pages + 1):
        payload = post(API_URL, build_request(group, start, end, page, limit))
        pages_fetched = page
        for row in payload.get("results") or []:
            obs = normalize_record(row, group, retrieved_at)
            if obs is None:
                skipped += 1
            else:
                observations.append(obs)
        meta = payload.get("page_metadata") or {}
        has_next_at_stop = bool(meta.get("hasNext"))
        if not has_next_at_stop:
            break
    return {
        "observations": observations,
        "skipped_no_award_id": skipped,
        "pagination": {
            "pages_fetched": pages_fetched,
            "page_limit": limit,
            "max_pages": max_pages,
            "has_next_at_stop": has_next_at_stop,
            # Honest truncation flag: cap hit while API still had more.
            "truncated": bool(has_next_at_stop and pages_fetched >= max_pages),
            "note": ("API hasNext is reported unreliable past ~10,000 "
                     "results; this run caps at max_pages x page_limit "
                     "records per group and flags truncation rather than "
                     "silently stopping."),
        },
    }


def group_total(post, group: str, start: str | None = None,
                end: str | None = None) -> int | None:
    """Total awards for one group from the count endpoint (None if absent)."""
    payload = post(COUNT_URL, build_count_request(group, start, end))
    results = payload.get("results") or {}
    key = {"contracts": "contracts", "grants": "grants"}[group]
    total = results.get(key)
    return int(total) if isinstance(total, (int, float)) else None


def collect(start: str, end: str, post=None, limit: int = DEFAULT_LIMIT,
            max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """Full run: counts + both groups + summary. One report dict."""
    post = post or default_post
    retrieved_at = utc_now_iso()
    report: dict = {
        "sensor_id": SENSOR_ID,
        "sensor_name": "Government contracts and grants (USAspending), Starr County",
        "source_name": "USAspending API v2",
        "source_url": API_URL,
        "retrieved_at_utc": retrieved_at,
        "window": {"start_date": start, "end_date": end},
        "geo": {"state": STATE, "county": COUNTY_NAME, "county_fips": COUNTY_FIPS5},
        "groups": {},
        "observations": [],
        "summary": {},
    }
    totals_all_time: dict[str, int | None] = {}
    totals_window: dict[str, int | None] = {}
    for group in ("contracts", "grants"):
        totals_all_time[group] = group_total(post, group)
        totals_window[group] = group_total(post, group, start, end)
        fetched = fetch_group(group, start, end, retrieved_at,
                              post=post, limit=limit, max_pages=max_pages)
        report["groups"][group] = {
            "award_type_codes": list(GROUPS[group]),
            "api_total_all_time": totals_all_time[group],
            "api_total_in_window": totals_window[group],
            "fetched": len(fetched["observations"]),
            "skipped_no_award_id": fetched["skipped_no_award_id"],
            "pagination": fetched["pagination"],
        }
        report["observations"].extend(fetched["observations"])

    obs = report["observations"]
    by_quality: dict[str, int] = {}
    by_group: dict[str, int] = {}
    dollars: dict[str, float] = {}
    for o in obs:
        by_quality[o["quality"]] = by_quality.get(o["quality"], 0) + 1
        by_group[o["group"]] = by_group.get(o["group"], 0) + 1
        if o["award_amount_usd"] is not None:
            dollars[o["group"]] = dollars.get(o["group"], 0.0) + o["award_amount_usd"]
    # Dollars summed ONLY over records where the API gave an amount.
    report["summary"] = {
        "observations_total": len(obs),
        "by_quality": by_quality,
        "by_group": by_group,
        "total_award_dollars_by_group (records with an amount only)": dollars,
        "truncated_any_group": any(
            g["pagination"]["truncated"] for g in report["groups"].values()),
        "redacted_recipients": sum(1 for o in obs if o["recipient_redacted"]),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sensor #31: USAspending contracts + grants, Starr County TX.")
    start_default, end_default = default_window()
    parser.add_argument("--start", default=start_default,
                        help="window start YYYY-MM-DD (default: 365 days ago)")
    parser.add_argument("--end", default=end_default,
                        help="window end YYYY-MM-DD (default: today)")
    parser.add_argument("--out", default=None, help="write JSON report to FILE")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="records per page (default 100)")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                        help="page cap per group (default 20)")
    args = parser.parse_args(argv)
    try:
        report = collect(args.start, args.end,
                         limit=args.limit, max_pages=args.max_pages)
    except BlockedError as exc:
        blocked = {
            "sensor_id": SENSOR_ID,
            "status": "BLOCKED-needs-feed",
            "source_url": API_URL,
            "retrieved_at_utc": utc_now_iso(),
            "error": str(exc),
        }
        text = json.dumps(blocked, indent=2)
        print(text, file=sys.stderr)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        return 2
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
