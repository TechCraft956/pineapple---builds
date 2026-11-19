"""Licence / sellability classification + filament-fit heuristic.

GPT-folded hardening (2026-11-17, brief #3): unknown licence is a HARD
default — sellable: False, reason "licence: unknown". A model is sellable
only when its licence, recorded verbatim from the source page, affirmatively
permits commercial use. Licence is proven per model, from the source page —
never inherited from a category or site default.
"""
from __future__ import annotations

import re

# Licences that affirmatively permit commercial use of verbatim prints
# (matched with word boundaries in classify_licence; see there).
# Substrings that always mean "not sellable" when present in the licence text.
NON_COMMERCIAL_MARKERS = ("NC", "NON-COMMERCIAL", "NONCOMMERCIAL",
                          "NON COMMERCIAL", "NON-COMMERCIAL")
NO_DERIVATIVES_MARKERS = ("ND", "NO DERIVATIVES", "NO-DERIVATIVES",
                          "NODERIVATIVES")

# Owner's filament on hand (brief #3): white/black Overture PLA+ Fast,
# clear PETG, a little gold silk PLA.
OWNER_FILAMENT = ("Overture PLA+ Fast (white/black)", "clear PETG",
                  "gold silk PLA")


def _normalise_licence(licence: str | None) -> str:
    return (licence or "").strip()


def classify_licence(licence: str | None) -> tuple[bool, str]:
    """Return (sellable, reason) for a verbatim licence string.

    - None / empty / "unknown"        -> (False, "licence: unknown")
    - contains a non-commercial mark  -> (False, "licence: non-commercial")
    - contains a no-derivatives mark  -> (False, "licence: no-derivatives — "
                                            "commercial sale of prints not cleared")
      (conservative: selling prints of an ND work is distribution, but the
       brief's sellable track only clears affirmative commercial licences)
    - matches a known commercial-ok licence -> (True, "licence: <verbatim>
      permits commercial use")
    - anything else                    -> (False, "licence: unrecognized '<verbatim>'")
    """
    raw = _normalise_licence(licence)
    if not raw or raw.lower() in ("unknown", "none", "not stated", "no licence stated"):
        return False, "licence: unknown"
    upper = raw.upper()
    if any(m in upper for m in NON_COMMERCIAL_MARKERS):
        return False, "licence: non-commercial"
    if any(m in upper for m in NO_DERIVATIVES_MARKERS):
        return False, "licence: no-derivatives — commercial sale of prints not cleared"
    # Short tokens (MIT/BSD/GPL/...) need word boundaries: "LIMITED" must not
    # match MIT. CC strings are distinctive enough for substring matching.
    if re.search(r"\b(CC BY|CC-BY|CC BY-SA|CC-BY-SA|CC0|CC-0)\b", upper):
        return True, f"licence: {raw} permits commercial use"
    if re.search(r"\b(MIT|APACHE|GPL|LGPL|BSD|PUBLIC DOMAIN)\b", upper):
        return True, f"licence: {raw} permits commercial use"
    return False, f"licence: unrecognized '{raw}'"


def apply_licence(rec) -> None:
    """Fill sellable/sellable_reason on a TrendRecord from its licence."""
    rec.sellable, rec.sellable_reason = classify_licence(rec.licence)


# --- Filament-fit heuristic (labelled heuristic, never a guarantee) -------

_FIT_RULES = (
    (("tpu", "flexible", "flexi ", "resin", "sla"), "not_compatible",
     "needs TPU/flexible filament or resin — not on hand (heuristic)"),
    (("silk", "metallic", "gold", "copper", "shiny"), "silk_pla",
     "silk/metallic look matches gold silk PLA on hand (heuristic)"),
    (("outdoor", "waterproof", "functional", "bracket", "holder",
      "mechanical", "gear"), "petg",
     "functional/outdoor use suits clear PETG on hand (heuristic)"),
)


def filament_fit(title: str, description: str = "") -> tuple[str, str]:
    """Heuristic filament fit from title/description keywords.

    Default is pla_plus (Overture PLA+ Fast is the bulk stock); the note
    always says it is a heuristic, never a print guarantee.
    """
    text = f"{title or ''} {description or ''}".lower()
    for keywords, fit, note in _FIT_RULES:
        if any(k in text for k in keywords):
            return fit, note + " — heuristic, not a print guarantee"
    return "pla_plus", ("fits Overture PLA+ Fast on hand (heuristic) — "
                        "heuristic, not a print guarantee")


def extract_licence_from_text(text: str) -> str | None:
    """Best-effort licence extraction from a model's page text.

    Looks for Creative Commons / CC strings near a 'License' label first,
    then anywhere in the text. Returns the verbatim match or None when the
    page states no licence (unknown stays unknown).
    """
    if not text:
        return None
    # "License: CC BY-NC-SA 4.0" style
    m = re.search(
        r"licen[cs]e\s*[:\-]?\s*((?:CC|Creative Commons)[^,\n]{0,60})",
        text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(
        r"\b(CC(?:\s+BY(?:-[A-Z]{2})?){0,3}|CC0|Creative Commons[^,\n]{0,60})",
        text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None
