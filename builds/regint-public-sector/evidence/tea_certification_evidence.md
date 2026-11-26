# TEA/SBEC educator certification — live evidence 2026-11-26

Collector: `tea_certification.py` (stdlib only, keyless, $0).
Run: `python3 tea_certification.py --out evidence/tea_certification_run_20261126.json`
Output: `tea_certification_run_20261126.json` (3 roster entries, 3 VERIFIED, 0 errors, ~60 s).
Source: <https://tealprod.tea.state.tx.us/ECOS-External/EcosOnline/VirtCert>
Official record date on all three records: Thursday, November 26, 2026.

## Endpoint behavior (verified live)

- Search form: plain POST (LastName, FirstName, MiddleName, btnSearch).
  No login, no key, no CAPTCHA on the search. The old
  `secure.sbec.state.tx.us/sbeconline/virtcert.asp` URL now returns the
  TEAL login page; the live public lookup is the tealprod VirtCert URL.
- Search response shapes: match list ("Educators Matching Selection
  Criteria", one form per match with `__RequestVerificationToken` +
  `spid`), direct detail (single match lands straight on the record),
  or zero-match ("Your Criteria Did Not Locate Any Educators").
- Detail: POST the row's token + spid to `.../VirtCert/Display`.
  Returns two tables — current certificates first, history second —
  with category, description, grades, effective/expiration dates, status.

## Results (certificate summaries only; full records in the JSON)

| District | Official (record name) | Superintendent cert | Other current certs |
|---|---|---|---|
| Roma ISD (214903) | Carlos Miguel Gonzalez Jr (spid 335508) | Valid 07/01/2024–06/30/2030, EC-12 | Principal Valid same dates; Secondary Physical Education (Provisional) Life; Educational Aide II Life |
| Rio Grande City Grulla ISD (214901) | Guadalupe S Garza (spid 337366) | Valid 01/01/2026–12/31/2031, EC-12 | Principal, Elementary Self-Contained, Generic Special Education, Bilingual/ESL-Spanish Valid same dates; Educational Aide II Life |
| San Isidro ISD (214902) | Elsa V Morris (single match) | Valid 11/01/2026–10/31/2032, EC-12 | Principal Valid same dates; Secondary English (Provisional) Life; Counselor (Professional) Life |

Disambiguation load: Gonzalez 34 matches (8 no-middle-name + 26
middle-name variants), Garza 27 matches — the Superintendent
credential uniquely identified the official in both cases. Morris was
a single match. "Villarreal Morris" returns zero matches (roster uses
"Morris", verified live).
