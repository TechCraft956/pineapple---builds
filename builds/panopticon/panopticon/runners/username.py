"""Username presence runner — sherlock/WhatsMyName class, v1.1.

HTTP status + body-marker semantics (GPT gate 2):
  200 + confirming body marker for THIS username -> FOUND (VERIFIED)
  200 + absent / soft-404 marker                 -> NOT_FOUND (VERIFIED)
  200, no marker                                  -> CANDIDATE (REPORTED)
  404                                             -> NOT_FOUND (VERIFIED)
  403/429/5xx/transport error/rejected redirect   -> UNKNOWN (never guessed)

A confirming marker is a template containing {u}; it only confirms when the
page contains the marker formatted with the QUERIED username — a marker for
a different username is not a match (false-identity guard). Sites with no
verified reliable marker stay CANDIDATE on a bare 200, honestly: a 200 is
only a URL response, not presence proof (soft-404s, login walls, JS
challenge pages all return 200 — Reddit returns 200 even for nonexistent
users, verified live 2026-11-18).

Markers verified live 2026-11-18 against real profile pages (torvalds):
GitHub/GitLab/Twitch `<title>{u}`, Hacker News `<title>Profile: {u}`,
Keybase `data-username="{u}"`. Reddit, YouTube, Medium, Dev.to, Codeberg
have no verified handle marker and stay CANDIDATE on 200.

Username enumeration requires a documented legitimate purpose (GPT gate 1)
and a validated subject (GPT gate 4): run() refuses without a purpose, and
subjects containing URL-injection characters are rejected before any fetch.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..ethics import PurposeRequiredError
from .http_util import USER_AGENT, http_fetch

# name, url template, absent marker ("no such user" on a 200),
# confirming marker template ({u} = queried username) or None.
SITES = [
    ("GitHub", "https://github.com/{u}", None, "<title>{u}"),
    ("GitLab", "https://gitlab.com/{u}", None, "<title>{u}"),
    ("Reddit", "https://www.reddit.com/user/{u}", None, None),
    ("YouTube", "https://www.youtube.com/@{u}", None, None),
    ("Twitch", "https://www.twitch.tv/{u}", None, "<title>{u}"),
    ("Hacker News", "https://news.ycombinator.com/user?id={u}", "No such user.",
     "<title>Profile: {u}"),
    ("Keybase", "https://keybase.io/{u}", None, 'data-username="{u}"'),
    ("Medium", "https://medium.com/@{u}", None, None),
    ("Dev.to", "https://dev.to/{u}", None, None),
    ("Codeberg", "https://codeberg.org/{u}", None, None),
]

# Generic soft-404 phrases: a 200 body containing one is a checked absence,
# not a presence. Deliberately narrow and profile-specific — a real profile
# page can mention "not found" in passing, so generic "not found" is NOT here.
SOFT404_MARKERS = (
    "no such user", "user not found", "profile not found",
    "this user does not exist", "user does not exist",
    "no profile found", "account not found",
)

SOURCE_ID = "runner:username_presence"

# Usernames may only carry these characters: anything else (/, ?, #, &, =,
# %, whitespace, quotes, ...) is a URL-injection attempt and is refused.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_username(username: str) -> str:
    """Reject subjects containing URL-injection characters (gate 4)."""
    if not isinstance(username, str) or not _USERNAME_RE.match(username):
        raise ValueError(
            "invalid username %r: allowed letters, digits, '_', '.', '-' "
            "(max 64 chars); URL-injection characters are refused" % (username,))
    return username


def check_site(username: str, site, fetch) -> dict:
    name, template, absent_marker, confirm_marker = site
    url = template.format(u=username)
    now = _now()
    try:
        status, body = fetch(url, user_agent=USER_AGENT)
    except Exception as e:  # rejected redirect, invalid URL, transport failure
        return _finding(username, name, url, now, "UNKNOWN", "UNKNOWN", 0.2,
                        "Presence of username %r on %s could not be determined "
                        "(fetch refused/failed: %s)" % (username, name, e),
                        status=None, error=str(e))
    body_lower = (body or "").lower()
    if status == 200:
        if absent_marker and absent_marker.lower() in body_lower:
            return _finding(username, name, url, now, "NOT_FOUND", "VERIFIED", 0.7,
                            "No profile page for username %r on %s (checked, absent: "
                            "site reports no such user)" % (username, name),
                            status=status)
        if any(m in body_lower for m in SOFT404_MARKERS):
            return _finding(username, name, url, now, "NOT_FOUND", "VERIFIED", 0.6,
                            "No profile page for username %r on %s (checked, absent: "
                            "soft-404 body)" % (username, name),
                            status=status)
        if confirm_marker and confirm_marker.format(u=username).lower() in body_lower:
            return _finding(username, name, url, now, "FOUND", "VERIFIED", 0.85,
                            "Profile page exists for username %r on %s" % (username, name),
                            status=status)
        return _finding(username, name, url, now, "CANDIDATE", "REPORTED", 0.45,
                        "Profile page for username %r on %s returned HTTP 200 but "
                        "no confirming marker — presence unconfirmed" % (username, name),
                        status=status)
    if status == 404:
        return _finding(username, name, url, now, "NOT_FOUND", "VERIFIED", 0.7,
                        "No profile page for username %r on %s (checked, absent)"
                        % (username, name),
                        status=status)
    return _finding(username, name, url, now, "UNKNOWN", "UNKNOWN", 0.2,
                    "Presence of username %r on %s could not be determined "
                    "(HTTP %s)" % (username, name, status),
                    status=status)


def _finding(username, site_name, url, now, result, verification, confidence,
             claim, status=None, error=None) -> dict:
    detail = {"site": site_name, "result": result, "http_status": status}
    if error:
        detail["error"] = error
    return {
        "subject": username,
        "subject_type": "username",
        "claim": claim,
        "detail": detail,
        "verification": verification,
        "confidence": confidence,
        "field_confidence": {
            "presence": {"confidence": confidence, "retrieved_at_utc": now,
                         "source_id": SOURCE_ID, "site": site_name},
        },
        "source_id": SOURCE_ID,
        "source_url": url,
        "retrieved_at_utc": now,
        "method": "CODE",
    }


def run(username: str, fetch=None, sites=None, purpose: str | None = None) -> list[dict]:
    """Enumerate a username across sites. Refuses without a documented
    legitimate purpose (gate 1) and with an invalid subject (gate 4)."""
    if not purpose:
        raise PurposeRequiredError(
            "username enumeration refused: no documented legitimate purpose. "
            "Username plans are restricted to user-owned accounts or public "
            "professional/organizational subjects with a purpose on record.")
    validate_username(username)
    fetch = fetch or http_fetch
    return [check_site(username, s, fetch) for s in (sites or SITES)]
