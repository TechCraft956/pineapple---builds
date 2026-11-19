"""Shared HTTP fetch for runners. Injectable so tests run offline.

Default implementation: urllib, identifying User-Agent, no cookies, no auth.
Returns (status:int|None, body_text:str). status None = transport error.

v1.1 hardening (GPT review gates 3-4):
- Redirects are followed only to the same public host (or an allowlisted
  public host). A redirect to a different host, to a private/loopback/
  link-local IP, or to any non-public target raises RedirectRejected and is
  NEVER followed. The validating handler sorts ahead of urllib's default
  redirect handler (handler_order 100 < 500) so the default handler can
  never silently follow a redirect first.
- Every fetch target is validated before any socket use: http/https only,
  no credentials in the URL, no localhost / private-IP / link-local target
  (SSRF guard). RedirectRejected is raised, never swallowed, so callers can
  record the reason as UNKNOWN instead of guessing.
"""
from __future__ import annotations

import ipaddress
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Panopticon/1.1 (Pineapple research; public OSINT; stdlib)"

# Public hosts a redirect may land on besides the origin host. Empty by
# design in v1.1: same-host only. Add a host here only with a recorded reason.
ALLOWED_REDIRECT_HOSTS: frozenset[str] = frozenset()

MAX_REDIRECTS = 5


class RedirectRejected(ValueError):
    """A redirect (or fetch target) failed host validation — never followed."""


def is_private_host(host: str) -> bool:
    """True for localhost names and IP literals in non-public ranges."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or h == "localhost":
        return True
    if h.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False  # a DNS name, not an IP literal; the same-host rule governs it
    return not ip.is_global


def validate_fetch_url(url: str, allowed_host: str | None = None) -> urllib.parse.ParseResult:
    """Validate a URL before any fetch. Raises RedirectRejected on violation."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RedirectRejected("unsupported URL scheme %r" % parsed.scheme)
    if parsed.username or parsed.password:
        raise RedirectRejected("credentials in URL are never fetched")
    host = (parsed.hostname or "").lower()
    if not host:
        raise RedirectRejected("URL has no host: %r" % url)
    if is_private_host(host):
        raise RedirectRejected("private/loopback/link-local target refused: %r" % host)
    if allowed_host is not None and host != allowed_host.lower():
        raise RedirectRejected(
            "target host %r leaves allowed host %r" % (host, allowed_host))
    return parsed


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows redirects only to the same public host (or allowlisted host).

    handler_order 100 sorts this ahead of urllib's default redirect handler
    (500) in the opener's error chain, so validation always runs first.
    """

    handler_order = 100

    def __init__(self):
        super().__init__()
        self.redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.redirects >= MAX_REDIRECTS:
            raise RedirectRejected("too many redirects (>%d)" % MAX_REDIRECTS)
        origin = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
        target = urllib.parse.urlparse(urllib.parse.urljoin(req.full_url, newurl))
        host = (target.hostname or "").lower()
        if host != origin and host not in ALLOWED_REDIRECT_HOSTS:
            raise RedirectRejected(
                "redirect to different host %r refused (origin %r)" % (host, origin))
        validate_fetch_url(target.geturl())
        self.redirects += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener() -> urllib.request.OpenerDirector:
    """Opener with redirect validation (proxy support kept via defaults)."""
    return urllib.request.build_opener(ValidatingRedirectHandler())


def http_fetch(url: str, timeout: float = 12.0, user_agent: str | None = None):
    validate_fetch_url(url)
    opener = build_opener()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent or USER_AGENT,
                                               "Accept": "*/*"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(200_000).decode("utf-8", "replace")
            return resp.status, body
    except RedirectRejected:
        raise
    except urllib.error.HTTPError as e:
        try:
            body = e.read(200_000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception:
        return None, ""
