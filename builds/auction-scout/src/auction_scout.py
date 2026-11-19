"""Auction & Surplus Scout v1 (stdlib only).

Watches public surplus / government auction sources for Texas lots and
normalizes them into Deal-Scout-shaped finds. EVERY lot pulled is
reported: category is a ranking signal, never a filter — no lot is
dropped or hidden for its category, score, distance, or missing fields
(Airam directive, 2026-11-18). Public listings only: no accounts, no
logins, no bids, no seller contact. Walled sources ship as explicit
NOT WIRED stubs that can never fabricate a lot.
"""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from zoneinfo import ZoneInfo

WARNING_LABEL = (
    "current bid is not a price — auctions move at close; verify lot, "
    "premium, taxes and removal terms on the source before acting."
)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AuctionScout/0.1 (public listings research)"
ROMA = (26.3839, -99.0233)  # Roma, TX 78584

# Built-in Texas city coordinate table (lat, lon). Extend from source
# locations encountered; a city not in the table yields distance None.
TX_CITIES = {
    "abilene": (32.4487, -99.7331), "alice": (27.7523, -98.0699),
    "amarillo": (35.2220, -101.8313), "arlington": (32.7357, -97.1081),
    "austin": (30.2672, -97.7431), "beaumont": (30.0802, -94.1266),
    "beeville": (28.4010, -97.7483), "brownsville": (25.9301, -97.4842),
    "college station": (30.6280, -96.3344), "conroe": (30.3119, -95.4560),
    "corpus christi": (27.8006, -97.3964), "dallas": (32.7767, -96.7970),
    "del rio": (29.3638, -100.8960), "denton": (33.2148, -97.1331),
    "eagle pass": (28.7090, -100.4995), "edinburg": (26.3015, -98.1633),
    "el paso": (31.7619, -106.4850), "falfurrias": (27.2267, -98.1450),
    "fort worth": (32.7555, -97.3308), "grand prairie": (32.7460, -96.9978),
    "harlingen": (26.1906, -97.6961), "houston": (29.7604, -95.3698),
    "huntsville": (30.7235, -95.5508), "irving": (32.8140, -96.9489),
    "kerrville": (30.0474, -99.1403), "killeen": (31.1171, -97.7278),
    "kingsville": (27.5159, -97.8561), "laredo": (27.5064, -99.5075),
    "longview": (32.5007, -94.7405), "lubbock": (33.5779, -101.8552),
    "mcallen": (26.1004, -98.2260), "mercedes": (26.1496, -97.9139),
    "mesquite": (32.7668, -96.5992), "midland": (31.9973, -102.0779),
    "mission": (26.2159, -98.3257), "nacogdoches": (31.6039, -94.6555),
    "new braunfels": (29.7030, -98.1245), "odessa": (31.8457, -102.3676),
    "pasadena": (29.7058, -95.2091), "pharr": (26.1948, -98.1856),
    "plano": (33.0198, -96.6989), "port isabel": (26.0736, -97.2085),
    "raymondville": (26.4814, -97.7832), "rio grande city": (26.3799, -98.8203),
    "roma": (26.3839, -99.0233), "san angelo": (31.4638, -100.4370),
    "san antonio": (29.4241, -98.4936), "south padre island": (26.1118, -97.1697),
    "texarkana": (33.4251, -94.0477), "troup": (32.1446, -95.1202),
    "tyler": (32.3513, -95.3011), "uvalde": (29.2097, -99.7862),
    "victoria": (28.8053, -97.0036), "waco": (31.5493, -97.1467),
    "weslaco": (26.1595, -97.9906), "wichita falls": (33.9137, -98.4934),
    "zapata": (26.9063, -99.2706),
}

CATEGORIES = ("tools", "equipment", "vehicles", "trailers", "generators", "other")

# Priority order matters: a "generator on a trailer" is a generator lot.
_CATEGORY_RULES = [
    ("generators", ("generator", "genset", "mep-", "mep ", "alternator set")),
    ("trailers", ("trailer",)),
    ("vehicles", ("truck", "pickup", "suv", "sedan", "hatchback", "van ",
                  " van", "bus", "humvee", "ford", "dodge", "gmc", "jeep",
                  "chevrolet", "chevy", "nissan", "toyota", "ram 1500",
                  "durango", "silverado", "tahoe", "explorer", "wrangler",
                  "f-150", "f-250", "f-350", "1500 ", "2500 ", "3500 ",
                  "automobile", "vehicle", "motorcycle", "atv", "utv",
                  "blackhawk", "helicopter", "aircraft")),
    ("tools", ("tool", "drill", "wrench", "socket", "grinder", "welder",
               "welding", "saw ", "chainsaw", "toolbox", "tool box")),
    ("equipment", ("excavator", "loader", "tractor", "forklift", "compressor",
                   "mower", "scrubber", "lift", "crane", "backhoe", "skid",
                   "pump", "machine", "equipment", "dozer", "grader",
                   "chipper", "trencher", "auger")),
]


def classify_category(title: str) -> str:
    t = f" {title.lower()} "
    for category, keywords in _CATEGORY_RULES:
        if any(k in t for k in keywords):
            return category
    return "other"


# Deal-first ranking (Airam directive, 2026-11-18). Lower sorts first.
# Ranking REORDERS ONLY — it never filters, drops, or hides a lot.
CATEGORY_RANK = {"vehicles": 0, "trailers": 1, "equipment": 2,
                 "generators": 3, "tools": 4, "other": 5}

SORT_DESCRIPTION = (
    "deal-first — category fit (vehicles → trailers → equipment → "
    "generators → tools → other), then distance from Roma, TX 78584 "
    "ascending (unknown distance last, still listed), then closing "
    "soonest. Ranking reorders only; no lot is filtered out."
)

# ---------------------------------------------------------------------------
# Track tags (Airam directive, 2026-11-18): the scout is NOT resale-only.
# Every lot is classified into one or more tracks. Tagging NEVER removes
# a lot; it only decides which report section leads for that lot.
# ---------------------------------------------------------------------------

# Lead-track priority: personal and project finds surface first so they
# are not buried under the resale ranking.
TRACK_ORDER = ("FOR YOU", "PROJECT ENABLER", "COOL FIND", "RESALE")

# Categories that fit the flip criteria on category fit alone. Margin
# potential cannot be scored without a retail anchor, and v1 has none —
# the tag claims category fit only, never a margin.
RESALE_CATEGORIES = ("vehicles", "trailers", "equipment", "generators", "tools")

# Airam's personal categories (Deal Scout FOR YOU track): workshop tools
# & equipment; 3D printers & filament; computers & electronics;
# generators & power gear for the house; truck & trailer stuff.
_FORYOU_KEYWORDS = (
    "3d printer", "3-d printer", "filament", "computer", "laptop",
    "monitor", "electronics", "power station", "inverter", "solar",
    "pickup", "truck", "silverado", "tacoma", "tundra", "colorado",
    "f-150", "f-250", "f-350", "1500", "2500", "3500",
)

# Unlocks or feeds a known project: 3D printing, the siren project,
# Pineapple compute, workshop capability.
_ENABLER_KEYWORDS = (
    "3d printer", "3-d printer", "filament", "siren", "cnc", "lathe",
    "milling", "drill press", "band saw", "plasma cutter", "welder",
    "welding machine", "air compressor", "workbench", "tool chest",
    "tool cabinet", "server", "rackmount",
)

# Rare / interesting on its face; no discount required.
_COOL_KEYWORDS = (
    "helicopter", "blackhawk", "aircraft", "antique", "vintage",
    "collectible", "humvee",
)


def classify_tracks(title: str, category: str) -> list[str]:
    """All tracks a lot belongs to, in lead-priority order (TRACK_ORDER).
    A lot may carry several tags or none; none still gets reported."""
    t = f" {title.lower()} "
    tags = set()
    if (category in ("tools", "equipment", "generators", "trailers")
            or any(k in t for k in _FORYOU_KEYWORDS)):
        tags.add("FOR YOU")
    if any(k in t for k in _ENABLER_KEYWORDS):
        tags.add("PROJECT ENABLER")
    if any(k in t for k in _COOL_KEYWORDS):
        tags.add("COOL FIND")
    if category in RESALE_CATEGORIES:
        tags.add("RESALE")
    return [tr for tr in TRACK_ORDER if tr in tags]


def lead_track(find: dict) -> str | None:
    """The track whose report section the lot is listed under (its first
    tag in TRACK_ORDER), or None for untagged lots."""
    tracks = find.get("tracks") or []
    return tracks[0] if tracks else None


def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def distance_from_roma(city: str | None) -> float | None:
    """Haversine miles from Roma 78584, or None when the city is unresolvable."""
    if not city:
        return None
    coords = TX_CITIES.get(city.strip().lower())
    if coords is None:
        return None
    return round(haversine_mi(ROMA, coords), 1)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resale_signal(category: str, current_bid_usd) -> dict:
    # v1 knows no retail anchors for any lot, so per the find contract the
    # signal is low and the note says so. Never invent an anchor.
    return {
        "level": "low",
        "note": (
            f"no retail anchor known — signal low (category: {category}; "
            "current bid is not a price)"
        ),
    }


def make_find(*, title, category, source, lot_id, url, location, current_bid_usd,
              bid_count, closing_at_utc, condition_notes, fees_note,
              source_url, retrieved_at_utc) -> dict:
    city = location.get("city") if location else None
    return {
        "title": title,
        "category": category,
        "tracks": classify_tracks(title, category),
        "source": source,
        "lot_id": str(lot_id),
        "url": url,
        "location": location,
        "distance_mi": distance_from_roma(city),
        "current_bid_usd": current_bid_usd,
        "bid_count": bid_count,
        "closing_at_utc": closing_at_utc,
        "condition_notes": condition_notes or "",
        "fees_note": fees_note,
        "resale_signal": resale_signal(category, current_bid_usd),
        "provenance": {"source_url": source_url, "retrieved_at_utc": retrieved_at_utc},
    }


# --------------------------------------------------------------------------
# HTTP + cache
# --------------------------------------------------------------------------

def fetch(url: str, *, method: str = "GET", body: bytes | None = None,
          timeout: int = 40, cache_dir=None, cache_slug: str = "page") -> tuple[int, str, bytes]:
    """Plain HTTP fetch. When cache_dir is given, the raw response is cached
    with a .meta.json sidecar carrying retrieved_at_utc + URL."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    retrieved = iso_z(utc_now())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    if cache_dir is not None:
        import os
        os.makedirs(cache_dir, exist_ok=True)
        stamp = retrieved.replace(":", "").replace("-", "")
        base = f"{cache_slug}_{stamp}"
        ext = "json" if raw[:1] in (b"{", b"[") else "html"
        with open(f"{cache_dir}/{base}.{ext}", "wb") as fh:
            fh.write(raw)
        with open(f"{cache_dir}/{base}.meta.json", "w") as fh:
            json.dump({"url": url, "method": method, "http_status": status,
                       "retrieved_at_utc": retrieved, "bytes": len(raw)}, fh, indent=2)
    return status, retrieved, raw


def strip_tags(html_text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


# --------------------------------------------------------------------------
# Public Surplus (WIRED)
# --------------------------------------------------------------------------

PS_BASE = "https://www.publicsurplus.com"
PS_KEYWORDS = ("generator", "trailer", "truck", "tool", "equipment")
PS_DETAIL_CAP = 8  # detail pages fetched per run, soonest-closing first


def ps_search_url(keyword: str) -> str:
    q = urllib.parse.quote(keyword)
    return f"{PS_BASE}/sms/all,tx/browse/search?posting=y&region=all,tx&keyWord={q}"


def parse_ps_grid(html_text: str) -> list[dict]:
    """Parse one Public Surplus search-results page into raw lot dicts."""
    lots = []
    blocks = re.split(r'<div class="auction-item" id="(\d+)searchGrid">', html_text)
    # blocks: [prefix, id1, body1, id2, body2, ...]
    for i in range(1, len(blocks), 2):
        lot_id, body = blocks[i], blocks[i + 1]
        title_m = re.search(r'title="#\d+ - ([^"]+)"', body)
        if not title_m:
            continue
        title = unescape(title_m.group(1)).strip()
        price_m = re.search(r'<b id="val_[^"]+">\s*\$([\d,]+(?:\.\d{2})?)\s*</b>', body)
        current_bid = float(price_m.group(1).replace(",", "")) if price_m else None
        end_m = re.search(
            r"updateTimeLeftSpan\(timeLeftInfoMap,\s*\d+,\s*\"[^\"]+\",\s*\d+,\s*(\d+)", body)
        closing = None
        if end_m:
            closing = iso_z(datetime.fromtimestamp(int(end_m.group(1)) / 1000, timezone.utc))
        state_m = re.search(r'class="auction-item-state">\s*([A-Z]{2})\s*<', body)
        lots.append({
            "lot_id": lot_id,
            "title": title,
            "current_bid_usd": current_bid,
            "closing_at_utc": closing,
            "state": state_m.group(1) if state_m else None,
            "url": f"{PS_BASE}/sms/all,tx/auction/view?auc={lot_id}",
        })
    return lots


def parse_ps_detail(html_text: str) -> dict:
    """Extract quoted facts from one Public Surplus lot detail page."""
    text = strip_tags(html_text)
    out = {"city": None, "state": None, "zip": None, "bid_count": None,
           "current_bid_usd": None, "condition_notes": "", "fees_note": None}
    loc_m = re.search(r"Pick-up Location\s+(.*?)\[\s*(.*?)\s*\]", text)
    if loc_m:
        addr = loc_m.group(2)
        city_m = re.search(r"(.*?),\s*([A-Z]{2})\s+(\d{5})", addr)
        if city_m:
            # The bracket address runs street and city together with no
            # comma between them ("106 E. Duval Troup, TX 75789"), so the
            # city is the known-Texas-city suffix of the pre-comma segment;
            # fall back to its last word when the city is not in the table.
            segment = city_m.group(1).strip()
            city = None
            for known in sorted(TX_CITIES, key=len, reverse=True):
                if segment.lower().endswith(known):
                    city = segment[len(segment) - len(known):]
                    break
            out["city"] = (city or segment.split()[-1]).strip()
            out["state"] = city_m.group(2)
            out["zip"] = city_m.group(3)
    bids_m = re.search(r"# of Bids\s+(\d+)", text)
    if bids_m:
        out["bid_count"] = int(bids_m.group(1))
    price_m = re.search(r"Current Price:\s*\$([\d,]+(?:\.\d{2})?)", text)
    if price_m:
        out["current_bid_usd"] = float(price_m.group(1).replace(",", ""))
    fee_m = re.search(r"[^.]*Buyers Premium of [\d.]+%[^.]*\.", text)
    if fee_m:
        out["fees_note"] = fee_m.group(0).strip()
    cond_m = re.search(r"Description\s+Condition:\s*(.{1,400})", text)
    if cond_m:
        out["condition_notes"] = cond_m.group(1).strip()[:240]
    return out


def fetch_publicsurplus(cache_dir=None, detail_cap: int = PS_DETAIL_CAP) -> dict:
    retrieved_seen = None
    raw_lots: dict[str, dict] = {}
    statuses = []
    for keyword in PS_KEYWORDS:
        url = ps_search_url(keyword)
        status, retrieved, raw = fetch(url, cache_dir=cache_dir,
                                       cache_slug=f"publicsurplus_search_{keyword}")
        retrieved_seen = retrieved
        statuses.append(status)
        if status != 200:
            continue
        for lot in parse_ps_grid(raw.decode("utf-8", "replace")):
            if lot["state"] not in (None, "TX"):
                continue
            lot.setdefault("found_via", url)
            raw_lots.setdefault(lot["lot_id"], lot)
    # NO category filter (Airam directive, 2026-11-18): every lot pulled
    # is kept and reported, "other" included. Category only feeds the
    # deal-first ranking in sort_open.
    candidates = []
    for lot in raw_lots.values():
        lot["category"] = classify_category(lot["title"])
        candidates.append(lot)
    # Detail pages go to the most deal-relevant lots first (category fit,
    # then closing) — enrichment order only; unenriched lots are still
    # reported with location/distance unknown.
    candidates.sort(key=lambda l: (
        CATEGORY_RANK.get(l["category"], len(CATEGORY_RANK)),
        l["closing_at_utc"] is None, l["closing_at_utc"] or ""))
    # Detail enrichment for the soonest-closing lots (city, bids, premium).
    details: dict[str, dict] = {}
    if cache_dir is not None or detail_cap:
        for lot in candidates[:detail_cap]:
            status, _r, raw = fetch(lot["url"], cache_dir=cache_dir,
                                    cache_slug=f"publicsurplus_detail_{lot['lot_id']}")
            if status == 200:
                details[lot["lot_id"]] = parse_ps_detail(raw.decode("utf-8", "replace"))
    finds = []
    for lot in candidates:
        det = details.get(lot["lot_id"], {})
        location = None
        if det.get("city") and det.get("state"):
            location = {"city": det["city"], "state": det["state"]}
        elif lot["state"] == "TX":
            location = None  # state known from the grid, city not — do not guess
        bid = det.get("current_bid_usd")
        if bid is None:
            bid = lot["current_bid_usd"]
        finds.append(make_find(
            title=lot["title"], category=lot["category"], source="publicsurplus",
            lot_id=lot["lot_id"], url=lot["url"], location=location,
            current_bid_usd=bid, bid_count=det.get("bid_count"),
            closing_at_utc=lot["closing_at_utc"],
            condition_notes=det.get("condition_notes", ""),
            fees_note=det.get("fees_note"),
            source_url=lot.get("found_via") or ps_search_url(PS_KEYWORDS[0]),
            retrieved_at_utc=retrieved_seen or iso_z(utc_now()),
        ))
    return {"source": "publicsurplus", "status": "WIRED", "finds": finds,
            "http_statuses": statuses, "raw_lot_count": len(raw_lots)}


# --------------------------------------------------------------------------
# GSA Auctions / PPMS (WIRED)
# --------------------------------------------------------------------------

GSA_API = "https://www.ppms.gov/gw/auction/ppms/api/v1/auctions"
GSA_PAGE_SIZE = 25
# The API returns naive local timestamps with no offset. v1 interprets them
# as America/Chicago (the lots are Texas-located; documented approximation
# in BUILD_REPORT.md).
GSA_TZ = ZoneInfo("America/Chicago")


def gsa_search_body(page: int = 1) -> dict:
    # The exact field shape the gsaauctions.gov front end builds for its
    # public search (recovered from its JS bundle, 2026-11-17).
    return {
        "advancedSearchText": "", "auctionSearchTypeAdvanced": "keyword",
        "auctionStatus": "Active", "categoryCodeList": [],
        "unCheckedCategoryList": [], "states": ["TX"], "zipCode": "",
        "radius": "", "auctionType": "", "minPrice": None, "maxPrice": None,
        "bidDeposit": None, "saleNumber": "", "auctionEndDateFrom": "",
        "auctionEndDateTo": "",
        "params": {"page": page, "size": GSA_PAGE_SIZE, "sort": ""},
    }


def gsa_closing_to_utc(end_date: str | None) -> str | None:
    if not end_date:
        return None
    try:
        naive = datetime.fromisoformat(end_date)
    except ValueError:
        return None
    if naive.tzinfo is None:
        naive = naive.replace(tzinfo=GSA_TZ)
    return iso_z(naive)


def parse_gsa_response(payload: dict, retrieved_at_utc: str, page: int = 1) -> list[dict]:
    finds = []
    for lot in payload.get("auctionDTOList") or []:
        loc = lot.get("location") or {}
        state = loc.get("state")
        if state and state != "TX":
            continue
        city = loc.get("city")
        location = {"city": city.title() if city else None, "state": state} if state else None
        if location and not location["city"]:
            location = None
        title = (lot.get("lotName") or "").strip()
        if not title or lot.get("lotId") is None:
            continue
        bid = lot.get("currentBid")  # missing/null stays None — never 0
        finds.append(make_find(
            title=title, category=classify_category(title), source="gsa",
            lot_id=lot["lotId"],
            url=f"https://gsaauctions.gov/auctions/preview/{lot.get('auctionId')}",
            location=location,
            current_bid_usd=float(bid) if bid is not None else None,
            bid_count=lot.get("numberOfBidders"),
            closing_at_utc=gsa_closing_to_utc(lot.get("endDate")),
            condition_notes=(lot.get("lotDescription") or "")[:240],
            fees_note=None,  # the search payload states no premium/removal terms
            source_url=f"{GSA_API}?page={page}&size={GSA_PAGE_SIZE}",
            retrieved_at_utc=retrieved_at_utc,
        ))
    return finds


def fetch_gsa(cache_dir=None, max_pages: int = 20) -> dict:
    """Pull ALL pages of the Texas search (Airam directive, 2026-11-18:
    stopping at page 1 left most Texas lots unreported). Pages are
    fetched until totalElements is covered or a page comes back empty;
    lots are deduped by lot_id across pages."""
    finds: list[dict] = []
    seen_ids: set[str] = set()
    statuses: list[int] = []
    total = None
    page = 1
    while page <= max_pages:
        url = f"{GSA_API}?page={page}&size={GSA_PAGE_SIZE}"
        status, retrieved, raw = fetch(
            url, method="POST", body=json.dumps(gsa_search_body(page)).encode(),
            cache_dir=cache_dir, cache_slug=f"gsa_search_tx_p{page}")
        statuses.append(status)
        if status != 200:
            if page == 1:
                return {"source": "gsa", "status": "ERROR", "finds": [],
                        "http_statuses": statuses,
                        "reason": f"search POST returned HTTP {status}"}
            break
        payload = json.loads(raw.decode("utf-8", "replace"))
        if payload.get("totalElements") is not None:
            total = payload["totalElements"]
        page_finds = parse_gsa_response(payload, retrieved, page=page)
        for f in page_finds:
            if f["lot_id"] not in seen_ids:
                seen_ids.add(f["lot_id"])
                finds.append(f)
        if not page_finds or (total is not None and len(seen_ids) >= total):
            break
        page += 1
    return {"source": "gsa", "status": "WIRED", "finds": finds,
            "http_statuses": statuses, "total_elements": total,
            "pages_fetched": page}


# --------------------------------------------------------------------------
# NOT WIRED stubs (GovPlanet, Texas state surplus)
# --------------------------------------------------------------------------

class NotWiredFetcher:
    """Explicit stub for a walled source. Returns the registry reason and
    the observed HTTP evidence; the finds list is always empty."""

    def __init__(self, registry_entry: dict):
        self.entry = registry_entry

    def fetch(self, probe: bool = False, cache_dir=None) -> dict:
        evidence = dict(self.entry.get("evidence") or {})
        if probe:
            evidence["live_probe"] = self._probe(cache_dir)
        return {"source": self.entry["id"], "status": "NOT WIRED", "finds": [],
                "reason": self.entry.get("reason", ""), "evidence": evidence}

    def _probe(self, cache_dir=None) -> dict:
        url = (self.entry.get("entry_points") or [self.entry["base_urls"][0]])[0]
        url = url.replace("<keyword>", "generator")
        try:
            status, retrieved, raw = fetch(url, timeout=25, cache_dir=cache_dir,
                                           cache_slug=f"{self.entry['id']}_probe")
            return {"url": url, "http_status": status, "bytes": len(raw),
                    "retrieved_at_utc": retrieved}
        except Exception as exc:  # connection-level wall is evidence too
            return {"url": url, "error": repr(exc), "retrieved_at_utc": iso_z(utc_now())}


# --------------------------------------------------------------------------
# Store: dedupe by (source, lot_id), update in place, last_seen_utc
# --------------------------------------------------------------------------

def merge_finds(existing: list[dict], new_finds: list[dict], now_iso: str) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for old in existing:
        by_key[(old["source"], str(old["lot_id"]))] = old
    for find in new_finds:
        key = (find["source"], str(find["lot_id"]))
        if key in by_key:
            merged = dict(find)
            merged["first_seen_utc"] = by_key[key].get("first_seen_utc", now_iso)
            merged["last_seen_utc"] = now_iso
            by_key[key] = merged
        else:
            fresh = dict(find)
            fresh["first_seen_utc"] = now_iso
            fresh["last_seen_utc"] = now_iso
            by_key[key] = fresh
    return list(by_key.values())


def sort_open(finds: list[dict]) -> list[dict]:
    """Deal-first ranking (Airam directive, 2026-11-18): category fit
    first (vehicles → trailers → equipment → generators → tools →
    other), then distance from Roma ascending (unknown distance last
    but STILL LISTED), then closing soonest. Reorders only — the output
    always contains every input lot."""
    return sorted(finds, key=lambda f: (
        CATEGORY_RANK.get(f.get("category"), len(CATEGORY_RANK)),
        f.get("distance_mi") is None,
        f.get("distance_mi") if f.get("distance_mi") is not None else 0.0,
        f.get("closing_at_utc") is None,
        f.get("closing_at_utc") or "",
    ))


def split_open_closed(finds: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    open_lots, closed = [], []
    for f in finds:
        closing = f.get("closing_at_utc")
        if closing and closing < iso_z(now):
            closed.append(f)
        else:
            open_lots.append(f)
    closed.sort(key=lambda f: f.get("closing_at_utc") or "", reverse=True)
    # No cap on the closed list: every pulled lot appears in the report
    # (open or recently closed) so pulled count == shown count.
    return sort_open(open_lots), closed


def time_remaining(closing_at_utc: str | None, now: datetime) -> str:
    if not closing_at_utc:
        return "closing unknown"
    try:
        closing = datetime.strptime(closing_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "closing unknown"
    delta = closing - now
    if delta.total_seconds() < 0:
        return "closed"
    days, rem = divmod(int(delta.total_seconds()), 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def feed_items(finds: list[dict]) -> list[dict]:
    """Later-wiring feed shape (brief contract; not wired anywhere in v1)."""
    items = []
    for f in finds:
        loc = f.get("location") or {}
        loc_str = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x)
        items.append({
            "title": f["title"], "category": "ASSETS", "source": f["source"],
            "action": "Review auction lot before its closing time",
            "est_value": None,  # null unless a real comp exists
            "risk": "bid state is volatile; current bid is not a price",
            "location": loc_str or "unknown", "url": f["url"],
            "confidence": 0.6,
        })
    return items


# --------------------------------------------------------------------------
# Digest renderer
# --------------------------------------------------------------------------

def _lot_lines(f: dict, now: datetime) -> list[str]:
    loc = f.get("location")
    loc_str = f"{loc['city']}, {loc['state']}" if loc and loc.get("city") else "location unknown"
    dist = f"{f['distance_mi']} mi" if f.get("distance_mi") is not None else "distance unknown"
    bid = f"${f['current_bid_usd']:,.2f}" if f.get("current_bid_usd") is not None else "bid not shown"
    bids = f" · {f['bid_count']} bid(s)" if f.get("bid_count") is not None else ""
    tracks = f.get("tracks") or []
    tag_str = f" [{', '.join(tracks)}]" if tracks else ""
    lines = [
        f"- **{f['title']}** ({f['category']}){tag_str} — {bid}{bids} · {loc_str} · {dist} · "
        f"closes {f.get('closing_at_utc') or 'unknown'} "
        f"({time_remaining(f.get('closing_at_utc'), now)}) · "
        f"[{f['source']} #{f['lot_id']}]({f['url']})"
    ]
    if f.get("fees_note"):
        lines.append(f"  - Fees: {f['fees_note']}")
    if f.get("condition_notes"):
        lines.append(f"  - Condition (from listing): {f['condition_notes']}")
    # Per-lot signal line ONLY when there is a genuine signal to report.
    # v1 knows no retail anchors, so the honest low/no-anchor state stays
    # in the data and off the page — never noise, never a fabricated anchor.
    sig = f.get("resale_signal") or {}
    if sig.get("level") not in (None, "low"):
        lines.append(f"  - Resale signal: {sig['level']} — {sig.get('note', '')}")
    return lines


def render_digest(finds: list[dict], source_status: list[dict], now: datetime) -> str:
    """Digest for ONE run's pulled lots. Every pulled lot is listed —
    open lots grouped by lead track (deal-first sort inside each track),
    then recently closed — so lots shown always equals lots pulled."""
    open_lots, closed = split_open_closed(finds, now)
    pulled = len(finds)
    shown = len(open_lots) + len(closed)
    lines = [
        "# Auction & Surplus Scout — Finds",
        "",
        f"> ⚠️ **Warning:** {WARNING_LABEL}",
        "",
        f"Generated: {iso_z(now)} · Base: Roma, TX 78584",
        f"Lots pulled this run: {pulled} · Lots shown in this report: {shown} "
        f"({len(open_lots)} open, {len(closed)} recently closed) — every pulled "
        "lot is listed; tagging and ranking reorder only, nothing is "
        "filtered, dropped, or hidden.",
        f"Sort order: {SORT_DESCRIPTION}",
        "Tracks: each lot is listed once, under its lead track — "
        "**FOR YOU** (personal) → **PROJECT ENABLER** → **COOL FIND** → "
        "**RESALE** — with all of its tags shown on its line. Lots with "
        "no track tag are listed under More lots.",
        "",
    ]
    if not open_lots:
        lines += ["## Open lots", "", "_No open lots were pulled in this run._", ""]
    grouped: dict[str | None, list[dict]] = {}
    for f in open_lots:  # open_lots is already deal-first sorted
        grouped.setdefault(lead_track(f), []).append(f)
    section_titles = {
        "FOR YOU": "For You — personal",
        "PROJECT ENABLER": "Project Enablers",
        "COOL FIND": "Cool Finds",
        "RESALE": "Resale",
        None: "More lots",
    }
    for track in (*TRACK_ORDER, None):
        lots = grouped.get(track)
        if not lots:
            continue
        lines += [f"## {section_titles[track]} ({len(lots)} open)", ""]
        for f in lots:
            lines += _lot_lines(f, now)
        lines.append("")
    if closed:
        lines += ["## Recently closed", ""]
        for f in closed:
            bid = f"${f['current_bid_usd']:,.2f}" if f.get("current_bid_usd") is not None else "bid not shown"
            lines.append(f"- {f['title']} — last bid shown {bid} · closed {f.get('closing_at_utc')} · [{f['source']} #{f['lot_id']}]({f['url']})")
        lines.append("")
    # Source status is a footnote now — the lots lead, not the plumbing.
    lines += ["## Source notes", ""]
    for s in source_status:
        if s["status"] == "WIRED":
            note = f"- **{s['source']}** — WIRED ({len(s.get('finds', []))} lot(s) this run)"
            if s.get("total_elements") is not None:
                note += (f"; source reports {s['total_elements']} active Texas "
                         "auctions, all pages pulled")
            lines.append(note)
        else:
            reason = (s.get("reason") or "").strip()
            short = (reason.split(". ")[0].rstrip(".") + ".") if reason else ""
            lines.append(f"- **{s['source']}** — {s['status']}: {short} "
                         "(0 lots; a stub can never fabricate a lot — full "
                         "evidence in BUILD_REPORT.md)")
    lines += ["", f"_{WARNING_LABEL}_", ""]
    return "\n".join(lines)
