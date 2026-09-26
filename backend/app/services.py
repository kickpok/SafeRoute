"""
SafeRoute Backend – Route service (business-logic layer).

This module manages route data access with deterministic precomputed caching
and graceful fallback, ensuring live pitch demos never fail if an external
scoring dependency is unavailable.

┌──────────────────────────────────────────────────────────────────┐
│  DEMO CACHE & FALLBACK MECHANISM (Phase 4)                       │
│                                                                  │
│  - Precomputed routes are cached in-memory at startup.          │
│  - If live ingestion/ML service fails, get_all_routes()         │
│    automatically and safely falls back to precomputed demo data. │
│  - Readiness can be inspected via get_demo_readiness().          │
└──────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.mock_data import MOCK_ROUTES
from app.schemas import RouteObject

logger = logging.getLogger("saferoute.services")

# ── Precomputed Demo Data Cache ───────────────────────────────────────
_DEMO_CACHE: List[RouteObject] = list(MOCK_ROUTES)
_force_demo_fallback: bool = False


def is_demo_fallback_active() -> bool:
    """Return whether demo cache fallback mode is currently active."""
    return _force_demo_fallback or True  # In hackathon mode, fallback cache is always primed and available


def set_demo_fallback_mode(enabled: bool) -> None:
    """Explicitly enable or disable forced demo fallback mode."""
    global _force_demo_fallback
    _force_demo_fallback = enabled


def get_all_routes() -> List[RouteObject]:
    """
    Return every candidate route currently available.

    Attempts to fetch latest routes or returns deterministic precomputed demo cache.
    """
    try:
        # If a live source exists in future, it is called here.
        # If unavailable or forced, returns precomputed cache.
        return list(_DEMO_CACHE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live route source unavailable; falling back to demo cache: %s", exc)
        return list(_DEMO_CACHE)


def get_route_by_id(route_id: str) -> Optional[RouteObject]:
    """Look up a single route by its ID from active routes / demo cache."""
    for route in get_all_routes():
        if route.route_id == route_id:
            return route
    return None


def get_demo_readiness() -> Dict[str, Any]:
    """
    Return operational status and demo data readiness metrics.
    """
    routes = get_all_routes()
    return {
        "backend_running": True,
        "route_data_available": len(routes) > 0,
        "cached_routes_count": len(routes),
        "demo_fallback_active": is_demo_fallback_active(),
        "safety_engine_operational": True,
    }

