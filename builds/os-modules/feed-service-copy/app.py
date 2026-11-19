"""
feed-service/app.py — Shared Feed service (FastAPI).

Routes (v1, versioned responses):
  GET  /health
  GET  /api/feed/apps           app statuses, feed.py semantics (seeded from
                                the recovered shared-feed feed.json)
  GET  /api/feed/opportunities  normalized opportunity records, Opportunity
                                Engine schema v0.2; limit/offset, filter by
                                type/source/approval_status, sort by
                                collected_at (desc) or est_value (desc)
  POST /api/feed/items          authenticated writer endpoint (bearer token
                                from FEED_API_TOKEN env var; never in the
                                frontend bundle). Validates every record
                                against opportunity.schema.json, dedupes by
                                id, supports Idempotency-Key, audit-logs
                                every write. Missing/invalid token -> 401.

Auth model: reads are unauthenticated by design (the read-only dashboard
polls them with no secret); writes require the bearer token. No roles in
v1, so 403 is unused — noted, not invented.
"""
import json
import os
from pathlib import Path

import jsonschema
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from store import (
    SCHEMA_VERSION,
    read_apps,
    read_opportunities,
    upsert_opportunities,
    write_app_status,
)

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "opportunity.schema.json"
with open(SCHEMA_PATH, encoding="utf-8") as fh:
    OPPORTUNITY_SCHEMA = json.load(fh)

FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")
MAX_BODY_BYTES = 1_000_000

app = FastAPI(title="Pineapple Shared Feed", version="1.0.0")

_cors = [o.strip() for o in os.environ.get("FEED_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )


@app.middleware("http")
async def body_limit(request: Request, call_next):
    length = request.headers.get("content-length")
    if length is not None and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large (max 1 MB)"},
                            status_code=413)
    return await call_next(request)


def _require_token(authorization: str | None = Header(default=None)):
    if not FEED_API_TOKEN:
        raise HTTPException(status_code=500,
                            detail="feed service misconfigured: FEED_API_TOKEN unset")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization[len("Bearer "):] != FEED_API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/health")
def health():
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


@app.get("/api/feed/apps")
def list_apps():
    feed = read_apps()
    apps = [{"app_id": app_id, **record} for app_id, record in feed.items()]
    apps.sort(key=lambda a: a["app_id"])
    return {"schema_version": SCHEMA_VERSION, "apps": apps}


@app.post("/api/feed/apps/{app_id}")
def post_app_status(app_id: str, payload: dict, _token=Depends(_require_token)):
    """Writer endpoint for app statuses — the HTTP form of feed.py's
    write_app_status(). Same merge semantics: other apps untouched."""
    if not isinstance(payload.get("status"), str) or not payload.get("status"):
        raise HTTPException(status_code=400, detail="body needs a non-empty status string")
    record = write_app_status(
        app_id,
        payload.get("app_name", app_id),
        payload["status"],
        metrics=payload.get("metrics"),
        recent_events=payload.get("recent_events"),
        actions=payload.get("actions"),
    )
    return {"schema_version": SCHEMA_VERSION, "app_id": app_id, **record}


@app.get("/api/feed/opportunities")
def list_opportunities(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    sort: str = Query(default="collected_at_desc",
                      pattern="^(collected_at_desc|est_value_desc)$"),
):
    items = read_opportunities()["items"]
    if type is not None:
        items = [i for i in items if i.get("type") == type]
    if source is not None:
        items = [i for i in items if i.get("source") == source]
    if approval_status is not None:
        items = [i for i in items if i.get("approval_status") == approval_status]
    key = "collected_at" if sort == "collected_at_desc" else "est_value"
    items = sorted(items, key=lambda i: i.get(key) or 0, reverse=True)
    total = len(items)
    return {
        "schema_version": SCHEMA_VERSION,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items[offset:offset + limit],
    }


@app.post("/api/feed/items")
def post_items(payload: dict, _token=Depends(_require_token),
               idempotency_key: str | None = Header(default=None)):
    records = payload.get("items")
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400,
                            detail="body must be {\"items\": [<opportunity record>, ...]}")
    errors = []
    for idx, rec in enumerate(records):
        try:
            jsonschema.validate(rec, OPPORTUNITY_SCHEMA)
        except jsonschema.ValidationError as exc:
            errors.append({"index": idx, "id": rec.get("id"), "error": exc.message})
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    inserted, duplicates, conflicts = upsert_opportunities(
        records, actor="bearer", idempotency_key=idempotency_key)
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={"conflicts": conflicts,
                    "inserted": inserted, "duplicates": duplicates,
                    "message": "same id with different payload already stored; "
                               "not overwritten"})
    return {"schema_version": SCHEMA_VERSION, "inserted": inserted,
            "duplicates": duplicates, "conflicts": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("FEED_PORT", "8100")))
