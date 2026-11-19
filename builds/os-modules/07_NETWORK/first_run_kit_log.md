# Network first-run kit log (BUILD-20261117-006)

SAMPLE users only. Passwords generated at run time, never
printed, never stored. Run in: /home/hatch/workspace/pineapple/builds/os-modules/07_NETWORK

- sample_owner already exists; skipped (idempotent re-run).
- sample_family already exists; skipped (idempotent re-run).

## Recorded output

```
$ python network.py list
USER           ROLE          PLAN           OWNER    WORKSPACE
sample_owner   OWNER         CUSTOM         YES      07_NETWORK/workspaces/sample_owner
sample_family  FAMILY_USER   FREE_FAMILY    -        07_NETWORK/workspaces/sample_family
```

```
$ python network.py whoami --user sample_owner
{
  "user_id": "7a102c754da5",
  "username": "sample_owner",
  "role": "OWNER",
  "plan": "CUSTOM",
  "created": "2026-11-17T23:45:37Z",
  "workspace": "07_NETWORK/workspaces/sample_owner",
  "active": true,
  "is_owner": true
}
```

```
$ python network.py whoami --user sample_family
{
  "user_id": "fcbe2eb65693",
  "username": "sample_family",
  "role": "FAMILY_USER",
  "plan": "FREE_FAMILY",
  "created": "2026-11-17T23:45:37Z",
  "workspace": "07_NETWORK/workspaces/sample_family",
  "active": true,
  "is_owner": false
}
```

```
$ python network.py can --user sample_owner --action create_watchlists
create_watchlists -> ALLOW (OWNER god_mode)
```

```
$ python network.py can --user sample_owner --action raw_fs
raw_fs -> ALLOW (OWNER god_mode)
```

```
$ python network.py can --user sample_family --action create_watchlists
create_watchlists -> DENY (role=FAMILY_USER)
```

```
$ python network.py can --user sample_family --action raw_fs
raw_fs -> DENY (role=FAMILY_USER)
```

```
$ python network.py can --user sample_family --action no_such_action_xyz
no_such_action_xyz -> DENY (role=FAMILY_USER)
```

## Audit log (2 entries)

```json
{"ts": "2026-11-17T23:45:37Z", "actor": "sample_owner", "action": "create_user", "detail": "sample_owner role=OWNER plan=CUSTOM"}
{"ts": "2026-11-17T23:45:37Z", "actor": "system", "action": "create_user", "detail": "sample_family role=FAMILY_USER plan=FREE_FAMILY"}
```

## Password hygiene check

Generated SAMPLE passwords were verified in-memory against the stored
pbkdf2_sha256 hashes and appear in NO file under the workspace.
No real user account was created anywhere.