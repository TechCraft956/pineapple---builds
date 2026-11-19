"""GEOINT adapters package — live county AD + FEMA NFHL adapters.

Pure-stdlib. All HTTP goes through client.fetch_json (retries + cache).
Mapping functions are pure and tested offline against recorded fixtures in
../fixtures/. No outbound calls happen unless a run_* function is invoked.
"""
