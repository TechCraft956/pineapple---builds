#!/usr/bin/env python3
"""Pineapple sensor — Texas educator certification registry (TEA / SBEC VirtCert).

Read-only collector for the SBEC Official Record of Educator Certificates,
the public lookup TEA links from its Certificate Lookup page. Standard
library only. $0 recurring cost. No signup, no API key, no account, no
payment, no CAPTCHA on the lookup as verified 2026-11-26.

What it does
------------
The lookup is name-keyed: POST a last + first name, get either a match
list or (single match) the certificate record directly. Each match row
carries a per-row anti-forgery token + ``spid`` (the registry's person
key); posting that row's form to the ``/Display`` action returns the
official certificate record: certificate category (STANDARD, PROVISIONAL,
PARAPROFESSIONAL, ...), description, grade span, effective date,
expiration date and status, split across a current table and a history
table. The collector verifies a small configured roster of sitting
public-school officials (superintendents — certification is a job
requirement and a public record) and disambiguates same-name matches by
the expected credential: exactly one exact-name match holding it is
VERIFIED; zero or several is REPORTED with an ambiguity note; a name
with no matches at all is UNKNOWN. It never invents a name, never
guesses which same-name record is the official, and never collects
anything beyond the public certificate record (no addresses, no
personal-life material, no dossiers).

Scope rule: PUBLIC LICENSE RECORDS ONLY. The roster is public officials
only. Do not add private individuals to the roster.

How to run
----------
    cd builds/regint-public-sector
    python3 tea_certification.py --out evidence/tea_certification_run_<date>.json

Options: ``--roster FILE`` (JSON list of roster entries, default: the
built-in 3-district Starr County roster), ``--max-details N`` (cap on
detail fetches per roster name, default 40 — common names return 30+
matches, all of which must be checked before the credential can
identify the official), ``--delay SECONDS``
(politeness delay between requests, default 0.5). Refuses to overwrite
an existing output file. Exit code 0 on a completed run (even with
UNKNOWN entries); exit code 2 only if no output could be produced.

Live evidence (2026-11-26): Gonzalez, Carlos -> 34 name matches, 8
exact-name; the Superintendent credential identifies spid 335508
(Carlos Miguel Gonzalez Jr, Roma ISD): Superintendent Valid
07/01/2024-06/30/2030, Principal Valid same dates. Garza, Guadalupe ->
26 matches, 13 exact-name; Morris, Elsa -> single match straight to
detail (Elsa V Morris): Superintendent Valid 11/01/2026-10/31/2032.
See ``evidence/tea_certification_evidence.md``.
"""
import argparse
import datetime as dt
import html as htmlmod
import http.cookiejar
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

SEARCH_URL = "https://tealprod.tea.state.tx.us/ECOS-External/EcosOnline/VirtCert"
DISPLAY_URL = SEARCH_URL + "/Display"
USER_AGENT = "Pineapple public-record research/1.0"

# The lookup's own name rule (from the form's data-val-regex-pattern).
NAME_RE = re.compile(r"^[a-zA-Z0-9.'\s\-& ]{1,30}$")
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

# Built-in roster: sitting superintendents of the three Starr County
# districts. Names from public sources: TEA 2025-26 Superintendent
# Salary Report (Region 01, Oct 2025) and the districts' own sites.
# Morris's TEA record name was verified live 2026-11-26 ("Villarreal
# Morris" returns zero matches; "Morris" returns the record).
ROSTER = [
    {"key": "roma-isd-superintendent",
     "district": "Roma ISD", "district_id": "214903",
     "role": "Superintendent",
     "last_name": "Gonzalez", "first_name": "Carlos",
     "expected_credential": "Superintendent"},
    {"key": "rgc-grulla-isd-superintendent",
     "district": "Rio Grande City Grulla ISD", "district_id": "214901",
     "role": "Superintendent",
     "last_name": "Garza", "first_name": "Guadalupe",
     "expected_credential": "Superintendent"},
    {"key": "san-isidro-isd-superintendent",
     "district": "San Isidro ISD", "district_id": "214902",
     "role": "Superintendent",
     "last_name": "Morris", "first_name": "Elsa",
     "expected_credential": "Superintendent"},
]

DEFAULT_MAX_DETAILS = 40
DEFAULT_DELAY = 0.5


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def validate_name(value, field):
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise ValueError(
            f"invalid {field} name: {value!r} (must match the lookup's name rule)")
    return value


def normalize_name(name):
    """Collapse whitespace and casefold for comparison."""
    return " ".join(str(name).split()).casefold()


def name_tokens(name):
    """Name tokens minus suffixes (jr/sr/ii/iii/iv), for exact matching."""
    return [t for t in normalize_name(name).split() if t not in NAME_SUFFIXES]


def is_exact_match(display_name, last_name, first_name):
    """True when the display name is the searched person ignoring middle
    names/initials and suffixes: first token == first name, last
    non-suffix token == last name."""
    toks = name_tokens(display_name)
    if len(toks) < 2:
        return False
    return (toks[0] == normalize_name(first_name)
            and toks[-1] == normalize_name(last_name))


class TableParser(HTMLParser):
    """Collect tables as lists of rows; each row is a list of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def parse_search_page(page):
    """Parse a VirtCert search response.

    Returns {"kind": "zero"|"list"|"detail", "matches": [...]} where each
    match is {"display_name", "token", "spid"}. For kind "detail" the
    page is already a certificate record (single match); matches is [].
    """
    text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", page))
    text = " ".join(text.split())
    if "Your Criteria Did Not Locate Any Educators" in text:
        return {"kind": "zero", "matches": []}
    if "This certifies that" in text:
        return {"kind": "detail", "matches": []}
    if "Educators Matching Selection Criteria" not in text:
        raise ValueError(
            "unrecognized search response (no match list, no record, no zero-match message)")
    names = re.findall(r'class="lnkEducator">\s*&nbsp;([^<]+)', page)
    tokens = re.findall(
        r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', page)
    spids = re.findall(r'name="spid" value="([^"]+)"', page)
    if not (len(names) == len(tokens) == len(spids)):
        raise ValueError(
            f"match list is ragged: {len(names)} names, "
            f"{len(tokens)} tokens, {len(spids)} spids")
    matches = [{"display_name": " ".join(n.split()), "token": t, "spid": s}
               for n, t, s in zip(names, tokens, spids)]
    return {"kind": "list", "matches": matches}


def parse_detail_page(page):
    """Parse a VirtCert certificate record page.

    Returns {"record_name", "official_record_date", "certificates": [...]}.
    Each certificate: category, description, grades (or None), effective,
    expiration, status, section ("current" = first table, "history" =
    later tables; the site renders current certificates first, history
    second, verified 2026-11-26). Duplicate rows are kept once per
    section.
    """
    text = htmlmod.unescape(re.sub(r"<[^>]+>", "\n", page))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    record_name = None
    record_date = None
    for i, ln in enumerate(lines):
        if ln == "This certifies that" and i + 1 < len(lines):
            record_name = lines[i + 1]
            break
    for i, ln in enumerate(lines):
        if ln == "Official Record of Certification" and i + 1 < len(lines):
            record_date = lines[i + 1]
            break
    parser = TableParser()
    parser.feed(page)
    certificates = []
    for ti, table in enumerate(parser.tables):
        section = "current" if ti == 0 else "history"
        category = None
        seen = set()
        last_cert = None
        for row in table:
            cells = list(row)
            if len(cells) == 1:
                cell = cells[0]
                if cell.startswith("Grades"):
                    if last_cert is not None:
                        last_cert["grades"] = cell
                    continue
                if cell.isupper() and len(cell) > 2:
                    category = cell
                    continue
                # Single-cell certificate sub-header (e.g. "Principal"):
                # the data row below carries the same name; ignore it.
                continue
            if len(cells) == 4 and cells[0] == "Description":
                continue  # column header row
            if len(cells) == 5 and cells[0] == "" and cells[1] != "":
                cert = {"category": category, "description": cells[1],
                        "grades": None, "effective": cells[2],
                        "expiration": cells[3], "status": cells[4],
                        "section": section}
            elif len(cells) == 4:
                cert = {"category": category, "description": cells[0],
                        "grades": None, "effective": cells[1],
                        "expiration": cells[2], "status": cells[3],
                        "section": section}
            else:
                continue
            key = (cert["category"], cert["description"], cert["effective"],
                   cert["expiration"], cert["status"], section)
            if key in seen:
                continue
            seen.add(key)
            certificates.append(cert)
            last_cert = cert
    if record_name is None and not certificates:
        raise ValueError("detail page has no certificate record and no name")
    return {"record_name": record_name, "official_record_date": record_date,
            "certificates": certificates}


def holds_credential(certificates, credential):
    """True when any certificate description contains the credential."""
    want = normalize_name(credential)
    return any(want in normalize_name(c["description"]) for c in certificates)


class Client:
    """Minimal VirtCert HTTP client (stdlib urllib + cookie jar)."""

    def __init__(self, delay=DEFAULT_DELAY):
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        self.delay = delay

    def _fetch(self, url, data=None):
        req = urllib.request.Request(
            url, data=data,
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml"})
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with self._opener.open(req, timeout=30) as resp:
            if resp.status != 200:
                raise ValueError(f"{url} answered HTTP {resp.status}")
            return resp.read().decode("utf-8", errors="replace")

    def search(self, last_name, first_name, middle_name=""):
        """POST a name search. Returns (parsed result, raw page HTML)."""
        body = urllib.parse.urlencode({
            "LastName": last_name, "FirstName": first_name,
            "MiddleName": middle_name, "btnSearch": "Search"}).encode("ascii")
        page = self._fetch(SEARCH_URL, data=body)
        return parse_search_page(page), page

    def detail(self, token, spid):
        """POST one match row's form; returns the parsed record."""
        body = urllib.parse.urlencode({
            "__RequestVerificationToken": token, "spid": spid}).encode("ascii")
        return parse_detail_page(self._fetch(DISPLAY_URL, data=body))


def _base_obs(entry, stamp):
    return {"sensor": "tea-educator-certification",
            "roster_key": entry.get("key"),
            "district": entry.get("district"),
            "district_id": entry.get("district_id"),
            "role": entry.get("role"),
            "searched_last_name": entry["last_name"],
            "searched_first_name": entry["first_name"],
            "expected_credential": entry.get("expected_credential"),
            "source": SEARCH_URL, "retrieved_at_utc": stamp}


def collect_entry(client, entry, max_details=DEFAULT_MAX_DETAILS):
    """Verify one roster entry. Returns one observation dict."""
    last = validate_name(entry["last_name"], "last")
    first = validate_name(entry["first_name"], "first")
    expected = entry.get("expected_credential")
    obs = _base_obs(entry, now())
    result, page = client.search(last, first)
    if result["kind"] == "zero":
        obs.update(status="UNKNOWN", record_name=None, spid=None,
                   match_count=0, exact_match_count=0, certificates=[],
                   expected_credential_found=None,
                   note="No educators matched this name spelling; roster spelling may be wrong.")
        return obs
    if result["kind"] == "detail":
        detail = parse_detail_page(page)
        return _finish_direct(obs, detail, expected)
    matches = result["matches"]
    exact = [m for m in matches
             if is_exact_match(m["display_name"], last, first)]
    obs["match_count"] = len(matches)
    obs["exact_match_count"] = len(exact)
    if not exact:
        obs.update(status="REPORTED", record_name=None, spid=None,
                   certificates=[], expected_credential_found=False,
                   note=("Name matched %d educator(s) but none with the exact "
                         "first+last name; not attributed to any record."
                         % len(matches)))
        return obs
    if len(exact) > max_details:
        obs.update(status="REPORTED", record_name=None, spid=None,
                   certificates=[], expected_credential_found=None,
                   note=("Too many exact-name matches (%d, cap %d) to "
                         "disambiguate safely; not attributed to any record."
                         % (len(exact), max_details)))
        return obs
    holders = []
    checked = []
    for m in exact:
        detail = client.detail(m["token"], m["spid"])
        checked.append({"display_name": m["display_name"], "spid": m["spid"],
                        "record_name": detail["record_name"],
                        "certificates": detail["certificates"]})
        if expected and holds_credential(detail["certificates"], expected):
            holders.append((m, detail))
        time.sleep(client.delay)
    if len(holders) == 1:
        m, detail = holders[0]
        obs.update(status="VERIFIED", record_name=detail["record_name"],
                   spid=m["spid"], certificates=detail["certificates"],
                   expected_credential_found=True,
                   official_record_date=detail["official_record_date"],
                   note=("Uniquely identified among %d exact-name match(es) "
                         "by the %s credential." % (len(exact), expected)))
        return obs
    if len(holders) > 1:
        obs.update(status="REPORTED", record_name=None, spid=None,
                   certificates=[], expected_credential_found=None,
                   note=("%d exact-name matches hold the %s credential; "
                         "cannot attribute to one record."
                         % (len(holders), expected)))
        return obs
    obs.update(status="REPORTED", record_name=None, spid=None,
               certificates=[], expected_credential_found=False,
               note=("None of the %d exact-name match(es) holds the %s "
                     "credential; not attributed to any record."
                     % (len(exact), expected)))
    obs["exact_match_summaries"] = [
        {"display_name": c["display_name"], "spid": c["spid"],
         "record_name": c["record_name"],
         "certificate_descriptions": sorted(
             {d["description"] for d in c["certificates"]})}
        for c in checked]
    return obs


def _finish_direct(obs, detail, expected):
    """Finish an observation from a direct-detail (single-match) page."""
    name_ok = is_exact_match(detail["record_name"] or "",
                             obs["searched_last_name"],
                             obs["searched_first_name"])
    found = bool(expected) and holds_credential(detail["certificates"], expected)
    obs.update(match_count=1, exact_match_count=1 if name_ok else 0,
               record_name=detail["record_name"], spid=None,
               certificates=detail["certificates"],
               expected_credential_found=found,
               official_record_date=detail["official_record_date"])
    if name_ok and (not expected or found):
        obs.update(status="VERIFIED",
                   note="Single match landed straight on the record; name and credential agree.")
    elif name_ok:
        obs.update(status="REPORTED",
                   note="Single match, but the record does not hold the expected credential.")
    else:
        obs.update(status="REPORTED",
                   note="Single match, but the record name does not match the roster name exactly.")
    return obs


def collect(roster, client, max_details=DEFAULT_MAX_DETAILS):
    """Verify every roster entry; returns the output document."""
    out = {"sensor": "tea-educator-certification", "source": SEARCH_URL,
           "observed_at": now(), "mode": "LIVE",
           "observations": [], "errors": []}
    for entry in roster:
        try:
            out["observations"].append(
                collect_entry(client, entry, max_details=max_details))
        except Exception as exc:  # per-entry failure never kills the run
            out["errors"].append({"roster_key": entry.get("key"),
                                  "error": str(exc)})
        time.sleep(client.delay)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Verify the TEA/SBEC educator certification roster.")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--roster", type=pathlib.Path,
                        help="JSON list of roster entries (default: built-in Starr County roster)")
    parser.add_argument("--max-details", type=int, default=DEFAULT_MAX_DETAILS)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"Refusing to overwrite existing output: {args.out}")
    roster = ROSTER
    if args.roster:
        roster = json.loads(args.roster.read_text())
        if not isinstance(roster, list) or not roster:
            raise SystemExit("roster file must be a non-empty JSON list")
    client = Client(delay=args.delay)
    out = collect(roster, client, max_details=args.max_details)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    verified = sum(1 for o in out["observations"] if o["status"] == "VERIFIED")
    print(f"LIVE: {len(out['observations'])} roster entries, "
          f"{verified} VERIFIED, {len(out['errors'])} errors -> {args.out}")
    return 2 if (not out["observations"] and out["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
