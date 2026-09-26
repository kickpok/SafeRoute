"""
SafeRoute Backend – Application entry point.

Run with:
    cd backend
    uvicorn main:app --reload

Interactive API docs at:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes import router
from app.safety_routes import router as safety_router
from app import services

# ── Load config ─────────────────────────────────────────────────────
_config_path = Path(__file__).parent / "config.json"
with open(_config_path) as f:
    config = json.load(f)

# ── Create app ──────────────────────────────────────────────────────
app = FastAPI(
    title=config.get("app_name", "SafeRoute API"),
    version=config.get("version", "0.1.0"),
    description=(
        "Backend API for the SafeRoute hackathon project.\n\n"
        "Aggregates route and safety-score data into one clean API "
        "that Track C (frontend / map UI) can consume directly.\n\n"
        "**Phase 1** — mock route data, frozen API contract.\n\n"
        "**Phase 2** — check-in sessions, trusted contacts, safety alerts.\n\n"
        "**Phase 3** — live location updates, route deviation detection, ETA delay alerts.\n\n"
        "**Phase 4** — 1-tap post-walk feedback, scoring pipeline integration, privacy lifecycle, demo fallback cache.\n\n"
        "**Phase 5** — demo hardening, deterministic reset, E2E integration, config-driven thresholds."
    ),
)

# ── CORS (wide-open for hackathon dev) ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get("cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routes ─────────────────────────────────────────────────
app.include_router(router)
app.include_router(safety_router)


# ── Health & Demo Readiness check ───────────────────────────────────
@app.get("/health", tags=["meta"], summary="Health & Demo Readiness Check")
async def health():
    readiness = services.get_demo_readiness()
    return {
        "status": "ok",
        "version": config.get("version"),
        "demo_ready": readiness["route_data_available"],
        "cached_routes": readiness["cached_routes_count"],
        "fallback_active": readiness["demo_fallback_active"],
        "safety_engine_ready": readiness["safety_engine_operational"],
    }



# ── Global validation-error handler ─────────────────────────────────
@app.exception_handler(422)
async def validation_error_handler(request: Request, exc):
    """Return a cleaner 422 body so Track C gets useful feedback."""
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )
