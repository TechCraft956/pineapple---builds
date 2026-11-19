"""Panopticon ethics gate — inherited posture from the recovered
04_INTELLIGENCE/osint module (osint_public.py, BUILD-20261117-010).

Rules enforced here:
- Findings/records may not carry private PII fields (banned list below).
- Sources flagged `excluded` in the registry are never planned or run.
- Sources flagged `purpose_required` (people-search / data-broker
  aggregators) require an explicit legitimate purpose and are never
  executed by CODE runners.
- v1.1 (GPT gate 6): the gate recurses into nested dicts/lists, and rendered
  brief output is re-gated (structured items before render, label-shaped
  leaks in the final text after render).
Public data only. Not a consumer report (no FCRA-covered use).
"""
from __future__ import annotations

import re


class EthicsViolation(Exception):
    pass


class PurposeRequiredError(Exception):
    """A purpose-gated action was requested without a documented purpose."""


BANNED_FIELD_FRAGMENTS = (
    "ssn", "social_security", "ein", "tax_id", "dob", "date_of_birth",
    "birth_date", "drivers_license", "driver_license", "passport",
    "home_address", "residential_address", "personal_phone", "cell_phone",
    "mobile_phone", "personal_email", "bank_account", "credit_card",
    "account_number", "password", "secret",
)


def _walk_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            yield prefix + key
            yield from _walk_keys(v, prefix + key + ".")
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item, prefix)


def assert_record_clean(record) -> None:
    """Raise EthicsViolation if a record carries a banned PII field name.
    Recurses into nested dicts and lists (gate 6); accepts a single record
    or a list of records."""
    for key in _walk_keys(record):
        leaf = key.split(".")[-1]
        for frag in BANNED_FIELD_FRAGMENTS:
            if frag in leaf:
                raise EthicsViolation(
                    "banned PII field %r present in record (key path %r)" % (leaf, key))


_LABEL_RE = re.compile(
    r"\b(%s)\s*[:=]" % "|".join(re.escape(f) for f in BANNED_FIELD_FRAGMENTS),
    re.IGNORECASE)


def assert_text_clean(text: str) -> None:
    """Re-gate rendered output: raise if a banned field appears as a
    `field:` / `field=` label in output text — i.e. a leaked field/value
    pair. Plain prose words without a label are not flagged."""
    m = _LABEL_RE.search(text or "")
    if m:
        raise EthicsViolation(
            "banned PII field %r leaked into output text" % m.group(1).lower())
