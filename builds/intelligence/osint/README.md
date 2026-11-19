# OSINT Public — Ethical Public-Records Dossiers

`04_INTELLIGENCE/osint/osint_public.py`

Given a **business or person name**, aggregate **PUBLIC-RECORD signals only** and
emit an **entity dossier** for due diligence before you transact: is the entity in
good standing, who is the registered agent, are assets encumbered (UCC liens), is a
professional license lapsing, has the entity forfeited existence?

Region: Rio Grande Valley, South Texas (Hidalgo, Cameron, Starr, Willacy + Brooks,
Kenedy, Jim Hogg, Zapata).

> **Status: SAMPLE.** Ships offline with `data/sample_entities.json` (~10 fabricated
> entities, clearly marked "SAMPLE"). No live network calls. Real source endpoints are
> documented below for later wiring.

---

## Hard ethical constraints (enforced in code)

`assert_record_clean()` is the gate every record passes through. It **rejects** any
record that contains private PII fields or references a banned source. The selftest
proves the gate actually blocks an injected `ssn` field and an injected
"facebook" source.

1. **Public records only** — government-published business filings, DBA index,
   license registries, county-clerk index. Nothing behind a login or private paywall.
2. **No private PII** — banned fields: SSN, EIN/tax id, DOB/age, driver's license,
   passport, home/residential address, personal phone/cell/mobile, personal email,
   bank/credit-card/account numbers.
3. **No PII compilation beyond a public business filing** — a *person* record is
   limited to that person's **public business role** (e.g. "managing member of X LLC
   per SOS filing") plus **public professional licenses**. No personal profile of a
   private individual.
4. **No social-media scraping** — banned sources: Facebook, Instagram, X/Twitter,
   TikTok, LinkedIn, Snapchat, and people-search / data-broker aggregators
   (Spokeo, BeenVerified, TruePeopleSearch, Whitepages, Intelius, etc.).
5. **Consent-aware** — person dossiers carry a consent note; intended for
   legitimate-interest due diligence (you are about to do business with the named
   entity), not surveillance of uninvolved individuals.

**Legal note:** public-record due diligence only. **Not a consumer report** — do not
use for FCRA-covered purposes (credit, employment, housing, insurance). Verify every
field against the official source before acting.

---

## Run

```bash
python osint_public.py --selftest          # health summary, exit 0 on success
python osint_public.py --query "Valley Sun" # dossiers matching a name
python osint_public.py --query "Starr"      # forfeited-entity example
python osint_public.py --json               # all items as JSON
python osint_public.py --write              # also write to 00_PROCESSED/people/
python osint_public.py                      # human-readable table
```

Pure Python 3.11 stdlib. UTF-8. Windows host.

---

## API

- `PLUGIN` — module-level dict: `id, name, category, authority, status="sample",
  inputs, outputs, sources (real URLs), safety` (safety embeds the ethics gate).
- `items(query=None) -> list[dict]` — decision-engine items. Each item has:
  `title, category, source, action, est_value (null — diligence is risk-reduction,
  not a priced opportunity), risk (LOW/MED/HIGH), location, url, confidence (0–1)`,
  plus a nested `dossier`.
- `dossiers(query=None) -> list[dict]` — full dossiers:
  `entity, type, filings, addresses_public, risk_flags, confidence` (+ officers,
  licenses, registered agent, status).
- `assert_record_clean(rec)` — ethics enforcement; raises `EthicsViolation`.

### Risk flags produced
`forfeited_existence` (HIGH), `no_registered_agent` (MED), `active_ucc_lien` /
`multiple_ucc_filings` (MED), `license_expiring_within_12mo` (LOW),
`multiple_active_dbas` (LOW), `entity_as_general_partner` (LOW),
`person_record_consent_note` (LOW).

---

## REAL public-record sources (wire these later)

All government / official. Respect each site's robots.txt and terms of service;
SOSDirect and TABC are official public lookups intended for manual/public use.

| Signal | Source | URL |
|---|---|---|
| Business filings (formation, status, agent) | TX Secretary of State — SOSDirect | https://www.sos.state.tx.us/corp/sosda/index.shtml |
| Entity tax status / good standing | TX Comptroller — Taxable Entity Search | https://mycpa.cpa.state.tx.us/coa/ |
| Professional licenses | TDLR License Search | https://www.tdlr.texas.gov/LicenseSearch/ |
| Real-estate licenses | TREC License Holder Search | https://www.trec.texas.gov/apps/license-holder-search/ |
| Alcohol permits | TABC Public Inquiry | https://www.tabc.texas.gov/services/public-inquiry/ |
| Motor-vehicle dealer (GDN) | TxDMV License Search | https://prod.txapps.texas.gov/tlc-search/app/license-search |
| UCC financing statements (liens) | TX SOS UCC Search | https://direct.sos.state.tx.us/ucc/ucc-search.asp |
| Assumed names (DBA) | Hidalgo County Clerk | https://www.hidalgocountyclerk.us/ |
| Assumed names (DBA) | Cameron County Clerk | https://www.cameroncountyclerk.com/ |
| County clerk records | Starr County Clerk | https://www.co.starr.tx.us/page/starr.County.Clerk |

Neighbor-county clerks (Willacy, Brooks, Kenedy, Jim Hogg, Zapata) expose
equivalent assumed-name / records search — wire as their public portals are
confirmed.

---

## How it plugs into the Decision Brief

`items()` returns records already shaped for the decision engine
(`title / category="intelligence" / source / action / est_value / risk / location /
url / confidence`). The decision engine ranks across all modules; OSINT items
surface under **RISKS / intelligence** as due-diligence actions (e.g.
"DO NOT CONTRACT — forfeited existence", "Pull full UCC before asset purchase").
`est_value` is `null` by design — these reduce risk rather than price an opportunity.

`--write` (and the selftest) emit a snapshot to
`00_PROCESSED/people/osint_public_dossiers.json`. The module writes **only** inside
its own folder or `00_PROCESSED`; it never writes to user folders and never modifies
existing Pineapple files.
