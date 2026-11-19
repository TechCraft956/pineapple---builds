"""Explicit NOT WIRED stubs. These exist so the plan can name a capability
without faking it: each raises NotWired with the reason. Nothing here returns
fabricated findings — ever.
"""
from __future__ import annotations


class NotWired(Exception):
    pass


def wayback_lookup(subject: str):
    raise NotWired(
        "wayback_cdx: NOT WIRED in v1 — the Wayback CDX API is no-key and "
        "CODE-able; wiring it is the top v2 quick win.")


def email_lookup(subject: str):
    raise NotWired(
        "email runners: NOT WIRED in v1 — available sources are key-gated "
        "(HUMAN STEP) and purpose-gated.")


def public_records_lookup(subject: str):
    raise NotWired(
        "public_records: NOT WIRED in v1 — TX SOS / TDLR / TREC / county "
        "clerks are web-only; they arrive as BROWSER-AGENT runners in v2. "
        "The recovered osint module's sample dossiers remain the offline "
        "reference implementation.")
