# Snapshot — marketplace-scraper (historical, read-only)

This is a **read-only historical snapshot** of the recovered
`marketplace-scraper` repository (public GitHub repo, 33 commits,
2026-04-16 → 2026-04-21, HEAD `93216010ca68a45633e41315b6865a58a5db0332`).

**It is NOT a build input.** Nothing here is built, run, deployed, or
rebuilt. It exists so the archive decision in `../ARCHIVE_RECORD.md` can be
audited against the code it describes.

- Source: `~/workspace/pineapple/recovered/marketplace-scraper/` (untouched
  originals — verified after the build via `git status` / `git diff HEAD`
  and a recursive diff of this snapshot against the clone; see
  `../BUILD_REPORT.md`).
- Contents: the full code tree **excluding** `.git/` and `__pycache__` /
  `*.pyc` build artifacts (52 files). The repo's own `README.md` is preserved
  inside as-is; this file is the archive label.
- The one piece carried forward is the Vehicle Financing Deal Optimizer,
  extracted separately as `../vehicle_deals.py` (byte-identical to
  `snapshot/backend/vehicle_deals.py`) with its own CLI and test suite.
  Everything else in this snapshot is superseded by the live Deal Scout
  system and the shared feed + Dash — see `../ARCHIVE_RECORD.md`.
- No Facebook cookies are present in this snapshot (none existed in the
  recovered repo). No cookies were created, uploaded, or refreshed.
- Do not push, publish, or deploy anything from this directory.
