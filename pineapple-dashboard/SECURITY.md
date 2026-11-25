# Security Policy

## Reporting a vulnerability

This is a personal operations dashboard. If you find a security issue, please
open a GitHub issue titled `[SECURITY]` and describe the issue without
including any live data, credentials, or personal information. Do not open a
public issue with exploit details — describe the class of issue and the
maintainer will follow up.

## What this app does and does not do

- **No authentication is built in.** The dashboard is intended to run on a
  private machine or a private network. Do not expose the backend port
  (default 3001) to the public internet without adding authentication
  (for example a reverse proxy with basic auth, or a VPN) — anyone who can
  reach the API can read and change the dashboard state.
- **No secrets are stored in this repo.** The state file
  (`server/data/dashboard.json`) holds the owner's operational data and is
  gitignored. Never commit it, and never paste API keys, tokens, or
  passwords into the dashboard or the repo.
- **No trading or spending.** This dashboard only displays and records
  state. It does not place orders, move money, or contact third parties.
- **Dependencies.** Run `npm audit` after installing or upgrading
  dependencies and address critical findings before deploying anywhere
  shared. See README.md for the audit results at the time of the last
  release.
