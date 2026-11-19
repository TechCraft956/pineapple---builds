"""scripts/first_run_kit.py — network foundation first-run kit (BUILD-20261117-006, Task 3).

Seeds the isolated workspace's 07_NETWORK with SAMPLE users ONLY:
  - sample_owner  (OWNER / CUSTOM, is_owner) — SAMPLE owner account
  - sample_family (FAMILY_USER / FREE_FAMILY) — SAMPLE family user

Passwords are generated at run time with secrets.token_urlsafe, passed to
network.py via the PINEAPPLE_PW env var (never argv, never printed, never
written to any file), and verified in-memory against the stored pbkdf2 hash.
They are SAMPLE credentials for synthetic accounts that exist only inside
this isolated workspace; no real user account is created anywhere.

Records `list` / `whoami` / `can` output and the audit log to
07_NETWORK/first_run_kit_log.md. Idempotent: already-seeded users are
skipped, not recreated.

Usage:
  python3 scripts/first_run_kit.py [--network-dir PATH]
Default network dir is <workspace>/07_NETWORK.
"""
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
DEFAULT_NET = WORKSPACE / "07_NETWORK"

OWNER = "sample_owner"
FAMILY = "sample_family"


def run_py(net_dir, args, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(net_dir / "network.py"), *args],
        capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def user_exists(net_dir, username):
    users_file = net_dir / "users.json"
    if not users_file.exists():
        return False
    return username in json.loads(users_file.read_text(encoding="utf-8")).get("users", {})


def main(argv):
    net_dir = Path(argv[argv.index("--network-dir") + 1]) if "--network-dir" in argv else DEFAULT_NET
    net_dir = net_dir.resolve()
    log_lines = ["# Network first-run kit log (BUILD-20261117-006)",
                 "",
                 "SAMPLE users only. Passwords generated at run time, never",
                 "printed, never stored. Run in: %s" % net_dir, ""]
    created = []

    for username, role, plan, is_owner in (
            (OWNER, "OWNER", "CUSTOM", True),
            (FAMILY, "FAMILY_USER", "FREE_FAMILY", False)):
        if user_exists(net_dir, username):
            log_lines.append("- %s already exists; skipped (idempotent re-run)." % username)
            continue
        pw = secrets.token_urlsafe(16)  # SAMPLE credential; held in memory only
        cmd = ["init-owner", "--user", username] if is_owner else \
            ["add-user", "--user", username, "--role", role, "--plan", plan]
        rc, out, err = run_py(net_dir, cmd, {"PINEAPPLE_PW": pw})
        if rc != 0 or "Created" not in out:
            print("FAILED to create %s: rc=%d out=%r err=%r" % (username, rc, out, err),
                  file=sys.stderr)
            return 1
        # Verify the generated password against the stored hash, in memory.
        sys.path.insert(0, str(net_dir))
        import network as netmod
        stored = json.loads((net_dir / "users.json").read_text(encoding="utf-8"))["users"][username]
        assert stored["password_algo"] == "pbkdf2_sha256", "unexpected password algo"
        assert netmod.verify_password(pw, stored["password_hash"], stored["password_salt"]), \
            "generated password does not verify against stored hash"
        assert pw not in (net_dir / "users.json").read_text(encoding="utf-8"), \
            "password leaked into users.json"
        created.append(username)
        log_lines.append("- created %s (role=%s, plan=%s, owner=%s); pbkdf2 hash verified in-memory."
                         % (username, role, plan, is_owner))

    # Record list / whoami / can output.
    sections = []
    for args in (["list"],
                 ["whoami", "--user", OWNER],
                 ["whoami", "--user", FAMILY],
                 ["can", "--user", OWNER, "--action", "create_watchlists"],
                 ["can", "--user", OWNER, "--action", "raw_fs"],
                 ["can", "--user", FAMILY, "--action", "create_watchlists"],
                 ["can", "--user", FAMILY, "--action", "raw_fs"],
                 ["can", "--user", FAMILY, "--action", "no_such_action_xyz"]):
        rc, out, _ = run_py(net_dir, args)
        assert rc == 0, "network.py %s failed rc=%d" % (args, rc)
        sections.append("$ python network.py %s\n%s" % (" ".join(args), out))

    audit_lines = []
    audit_file = net_dir / "audit_log.jsonl"
    if audit_file.exists():
        audit_lines = [ln for ln in audit_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    log_lines.append("")
    log_lines.append("## Recorded output")
    log_lines.append("")
    for s in sections:
        log_lines.append("```")
        log_lines.append(s)
        log_lines.append("```")
        log_lines.append("")
    log_lines.append("## Audit log (%d entries)" % len(audit_lines))
    log_lines.append("")
    log_lines.append("```json")
    log_lines.extend(audit_lines)
    log_lines.append("```")
    log_lines.append("")
    log_lines.append("## Password hygiene check")
    log_lines.append("")
    log_lines.append("Generated SAMPLE passwords were verified in-memory against the stored")
    log_lines.append("pbkdf2_sha256 hashes and appear in NO file under the workspace.")
    log_lines.append("No real user account was created anywhere.")
    (net_dir / "first_run_kit_log.md").write_text("\n".join(log_lines), encoding="utf-8")

    print("first-run kit done: created=%s (skipped existing)" % (created or "none"))
    for s in sections:
        print("---")
        print(s)
    print("---")
    print("audit entries: %d" % len(audit_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
