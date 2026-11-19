import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modules.school_assistant import router as school_router

# ── CORS (tightened 2026-11-17, BUILD-20261117-008 Task 3) ─────────────────────
# BEFORE: allow_origins=["*"], allow_methods=["*"], allow_headers=["*"] with
# NO authentication — any website could call this API once the app was
# reachable. DEFAULT NOW: localhost-only origins (the app is a local-only
# student tool), GET/POST only (the only methods the API uses), and a
# minimal header allow-list. Override ONLY deliberately, e.g. to put the
# app behind an authenticated reverse proxy:
#   SSA_CORS_ORIGINS=http://localhost:3000,https://school.example.com
# See AUTH_GAP.md — tightening CORS is NOT authentication. Do not expose
# this app on a network until the auth prerequisites there are met.
_DEFAULT_ORIGINS = [
    "http://localhost",
    "http://localhost:8000",
    "http://localhost:3000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:3000",
]
_cors_origins = [
    o.strip() for o in os.environ.get("SSA_CORS_ORIGINS", "").split(",") if o.strip()
] or _DEFAULT_ORIGINS

app = FastAPI(title="School Scraper Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(school_router)


@app.get("/health")
def health():
    return {"status": "ok"}
