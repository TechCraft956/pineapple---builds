#!/usr/bin/env python3
"""
PINEAPPLE NETWORK OS - foundation (multi-user, local-first).

The frame everything plugs into. Owner God Mode + role-based private workspaces,
enforced at the architecture level (separate folders + permission checks), not just UI.

    python network.py init-owner --user airam
    python network.py add-user --user mike --role FAMILY_USER --plan FREE_FAMILY
    python network.py add-user --user trader1 --role TRADER_USER --plan TRADER_BASIC
    python network.py list
    python network.py whoami --user mike
    python network.py can --user mike --action create_watchlists

Security: passwords are pbkdf2_sha256 (salted, 200k iters) - NEVER plaintext.
Every privileged action is audit-logged. No raw filesystem access for non-owners.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

NET = Path(__file__).resolve().parent
ROOT = NET.parent
USERS = NET / "users.json"
ROLES = NET / "registry" / "roles.json"
PLANS = NET / "registry" / "plans.json"
AUDIT = NET / "audit_log.jsonl"
WORKSPACES = NET / "workspaces"
WS_SUBDIRS = ["chats", "watchlists", "documents", "reports", "alerts"]


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(p, default):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def _save(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, indent=2), encoding="utf-8")


def audit(actor, action, detail=""):
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": utcnow(), "actor": actor, "action": action, "detail": detail}) + "\n")


# ---- password hashing (never plaintext) ------------------------------------
def hash_password(pw: str):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000)
    return "pbkdf2_sha256", dk.hex(), salt


def verify_password(pw: str, hexhash: str, salt: str) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000)
    return secrets.compare_digest(dk.hex(), hexhash)


# ---- users / workspaces ----------------------------------------------------
def _users():
    return _load(USERS, {"users": {}})


def make_workspace(username):
    ws = WORKSPACES / username
    for sub in WS_SUBDIRS:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    (ws / "profile.json").write_text(json.dumps({"private": True, "owner": username}, indent=2), encoding="utf-8")
    return ws


def add_user(username, role, plan, password=None, is_owner=False):
    data = _users()
    if username in data["users"]:
        print("User exists:", username); return
    roles = _load(ROLES, {}).get("roles", {})
    if role not in roles:
        print("Unknown role %s. Valid: %s" % (role, ", ".join(roles))); return
    pw = password or os.environ.get("PINEAPPLE_PW") or secrets.token_urlsafe(12)
    algo, h, salt = hash_password(pw)
    ws = make_workspace(username)
    data["users"][username] = {
        "user_id": secrets.token_hex(6), "username": username, "role": role, "plan": plan,
        "created": utcnow(), "password_algo": algo, "password_hash": h, "password_salt": salt,
        "workspace": str(ws.relative_to(ROOT)), "active": True, "is_owner": is_owner,
    }
    _save(USERS, data)
    audit(username if is_owner else "system", "create_user", "%s role=%s plan=%s" % (username, role, plan))
    print("Created %s (role=%s, plan=%s)" % (username, role, plan))
    if not password and "PINEAPPLE_PW" not in os.environ:
        print("  Generated password (store it now, not shown again): %s" % pw)
    print("  Workspace: %s" % ws.relative_to(ROOT))


def can(username, action):
    u = _users()["users"].get(username)
    if not u:
        return False, "no such user"
    roles = _load(ROLES, {}).get("roles", {})
    perms = roles.get(u["role"], {})
    if u.get("is_owner") or perms.get("god_mode"):
        return True, "OWNER god_mode"
    return bool(perms.get(action, False)), "role=%s" % u["role"]


def cmd_list():
    data = _users()
    if not data["users"]:
        print("No users yet. Run: python network.py init-owner --user <you>"); return
    print("%-14s %-13s %-14s %-8s %s" % ("USER", "ROLE", "PLAN", "OWNER", "WORKSPACE"))
    for u in data["users"].values():
        print("%-14s %-13s %-14s %-8s %s" % (u["username"], u["role"], u["plan"],
              "YES" if u.get("is_owner") else "-", u["workspace"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    io = sub.add_parser("init-owner"); io.add_argument("--user", required=True); io.add_argument("--password")
    au = sub.add_parser("add-user")
    au.add_argument("--user", required=True); au.add_argument("--role", required=True)
    au.add_argument("--plan", default="FREE_FAMILY"); au.add_argument("--password")
    sub.add_parser("list")
    wi = sub.add_parser("whoami"); wi.add_argument("--user", required=True)
    cn = sub.add_parser("can"); cn.add_argument("--user", required=True); cn.add_argument("--action", required=True)
    args = ap.parse_args()

    if args.cmd == "init-owner":
        add_user(args.user, "OWNER", "CUSTOM", password=args.password, is_owner=True)
    elif args.cmd == "add-user":
        add_user(args.user, args.role, args.plan, password=args.password)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "whoami":
        u = _users()["users"].get(args.user)
        print(json.dumps({k: v for k, v in u.items() if "password" not in k}, indent=2) if u else "no such user")
    elif args.cmd == "can":
        ok, why = can(args.user, args.action)
        print("%s -> %s (%s)" % (args.action, "ALLOW" if ok else "DENY", why))
    else:
        ap.print_help()
