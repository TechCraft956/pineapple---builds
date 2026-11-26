# Sensor — Texas educator certification registry (TEA / SBEC VirtCert)

Pineapple sensor **#101** (added 2026-11-26). Read-only collector for the
SBEC Official Record of Educator Certificates — the public lookup TEA
links from its Certificate Lookup page. Standard library only. $0
recurring cost. No signup, no API key, no account, no payment.

## Source

- Lookup (search form): <https://tealprod.tea.state.tx.us/ECOS-External/EcosOnline/VirtCert>
- Detail action: same URL + `/Display`
- TEA's lookup page: <https://tea.texas.gov/educators/certification/certificate-lookup/certificate-lookup>

The lookup is name-keyed: POST last + first name, get a match list or
(single match) the record directly. Each match row carries a per-row
anti-forgery token + `spid` (the registry's person key); posting that
row's form returns the official certificate record: category (STANDARD,
PROVISIONAL, PARAPROFESSIONAL, PROFESSIONAL, ...), description, grade
span, effective date, expiration date, status — split across a current
table and a history table. The old `secure.sbec.state.tx.us/sbeconline/virtcert.asp`
URL now redirects to the TEAL login page; the live public lookup is the
`tealprod.tea.state.tx.us` VirtCert endpoint above.

## How to run

```bash
cd builds/regint-public-sector
python3 tea_certification.py --out evidence/tea_certification_run_<date>.json
```

Options: `--roster FILE` (JSON roster, default built-in 3-district Starr
County roster), `--max-details N` (cap on detail fetches per name,
default 40), `--delay SECONDS` (politeness delay, default 0.5). Refuses
to overwrite an existing output file. Exit 0 on a completed run; exit 2
only if no output could be produced. One full roster run takes ~1 minute
(3 searches + ~60 detail fetches for common names).

## Scope rule

PUBLIC LICENSE RECORDS ONLY. The roster is sitting public-school
officials (superintendents) whose certification is a job requirement
and a public record. Same-name matches are disambiguated by the
expected credential — exactly one exact-name match holding it is
VERIFIED; zero or several is REPORTED with an ambiguity note; no
matches is UNKNOWN. The collector never invents a name, never guesses
which same-name record is the official, and never collects anything
beyond the public certificate record (no addresses, no personal-life
material, no dossiers). Do not add private individuals to the roster.

## Live evidence (2026-11-26)

Full run: `evidence/tea_certification_run_20261126.json` — 3 roster
entries, **3 VERIFIED, 0 errors**, ~60 s. Official record date on all
three records: Thursday, November 26, 2026.

- **Roma ISD (214903), Superintendent — Carlos Miguel Gonzalez Jr**
  (spid 335508). Uniquely identified among 34 exact-name matches by
  the Superintendent credential. Current: Superintendent Valid
  07/01/2024–06/30/2030 (EC-12); Principal Valid same dates; Secondary
  Physical Education (Provisional) Life; Educational Aide II Life.
- **Rio Grande City Grulla ISD (214901), Superintendent — Guadalupe S
  Garza** (spid 337366). Uniquely identified among 27 exact-name
  matches. Current: Superintendent Valid 01/01/2026–12/31/2031 (EC-12);
  Principal, Elementary Self-Contained, Generic Special Education,
  Bilingual/ESL-Spanish Valid same dates; Educational Aide II Life.
- **San Isidro ISD (214902), Superintendent — Elsa V Morris** (single
  match, straight to detail). Current: Superintendent Valid
  11/01/2026–10/31/2032 (EC-12); Principal Valid same dates; Secondary
  English (Provisional) Life; Counselor (Professional) Life.

Name-spelling notes found live: Morris's TEA record name is "Morris"
("Villarreal Morris" returns zero matches); Gonzalez's middle name is
Miguel (found only via the credential disambiguation).

## Caveats

- **Name-keyed only — no bulk roster, no API.** TEA publishes no
  downloadable certification roster and no public API. ECOS bulk
  download ("File Transfer for Certification Information") is behind
  TEAL login for authorized users only — not a keyless path. A bulk
  leg would need an authorized ECOS account (owner step, not built).
- **Common names are expensive.** Gonzalez returned 34 matches, Garza
  27; every exact-name match must be fetched before the credential can
  identify the official. The `--max-details` cap (default 40) bounds
  this; a name over the cap reports REPORTED, never a guess.
- **Current/history section labels** come from table order (first
  table = current, later = history); the site renders current first,
  history second (verified on all three records). Every certificate
  also carries its own status + dates, so no information depends on
  the label alone.
- **Anti-forgery tokens are per-search, single-use values** from the
  public results page. They are used immediately within the run and
  never stored, logged, or written to the evidence file.
- **Aggregate alternative (not built):** TEA's TPEIR "Teacher
  Certification by Certification Program and Certification Area"
  reports give certification production counts at state + ESC Region
  level (Region 1 = RGV) — aggregate only, no per-person records.
  That would be a separate aggregate leg if Airam wants counts
  without names.
- **Roster freshness:** superintendents change. Roster names come from
  the TEA 2025–26 Superintendent Salary Report (Region 01, Oct 2025)
  + district sites. If a search returns UNKNOWN, check the district's
  current superintendent first — the roster spelling is the usual
  cause (see Morris above).

## Tests

```bash
cd builds/regint-public-sector
python3 -m unittest tests.test_tea_certification -v
```

21 tests, all passing (2026-11-26). Fixtures are synthetic HTML
mimicking the live page structure (fake names/spids, placeholder
tokens) — no network calls, no real private names in the fixtures.
The live run above is the real verification.
