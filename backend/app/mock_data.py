"""
SafeRoute Backend – Mock route data.

This file contains realistic demo routes for the Connaught Place (Delhi)
area.  Track C can develop the map UI against this data immediately.

┌──────────────────────────────────────────────────────────────────┐
│  HOW TO REPLACE WITH TRACK A'S REAL DATA                        │
│                                                                  │
│  1. Have Track A produce a JSON file matching the RouteObject    │
│     schema (see app/schemas.py).                                 │
│  2. Place the file at  backend/data/routes.json                  │
│  3. Update  app/services.py  to load from that file instead of   │
│     importing MOCK_ROUTES from this module.                      │
│  4. Alternatively, have Track A call a future ingestion endpoint │
│     (Phase 2+).                                                  │
└──────────────────────────────────────────────────────────────────┘
"""

from app.schemas import Coordinate, RouteObject, SafetyFactors

# ── Three candidate routes around Connaught Place, New Delhi ────────

MOCK_ROUTES: list[RouteObject] = [
    RouteObject(
        route_id="route-001",
        name="Via Barakhamba Road (Well-lit main road)",
        coordinates=[
            Coordinate(lat=28.6315, lng=77.2167),   # origin – Rajiv Chowk
            Coordinate(lat=28.6330, lng=77.2190),
            Coordinate(lat=28.6348, lng=77.2225),
            Coordinate(lat=28.6370, lng=77.2260),
            Coordinate(lat=28.6385, lng=77.2295),   # destination – Barakhamba
        ],
        safety_score=0.87,
        factors=SafetyFactors(
            lighting=0.92,
            crowd=0.85,
            transit=0.90,
            isolation=0.80,
            incidents=0.88,
        ),
        distance_km=1.2,
        estimated_minutes=15,
    ),
    RouteObject(
        route_id="route-002",
        name="Via Janpath (Moderate traffic, some dim stretches)",
        coordinates=[
            Coordinate(lat=28.6315, lng=77.2167),   # origin – Rajiv Chowk
            Coordinate(lat=28.6295, lng=77.2145),
            Coordinate(lat=28.6270, lng=77.2130),
            Coordinate(lat=28.6250, lng=77.2150),
            Coordinate(lat=28.6240, lng=77.2180),
            Coordinate(lat=28.6260, lng=77.2220),
            Coordinate(lat=28.6385, lng=77.2295),   # destination – Barakhamba
        ],
        safety_score=0.64,
        factors=SafetyFactors(
            lighting=0.55,
            crowd=0.70,
            transit=0.75,
            isolation=0.60,
            incidents=0.62,
        ),
        distance_km=1.8,
        estimated_minutes=22,
    ),
    RouteObject(
        route_id="route-003",
        name="Via Tolstoy Marg (Shortest but poorly lit back lanes)",
        coordinates=[
            Coordinate(lat=28.6315, lng=77.2167),   # origin – Rajiv Chowk
            Coordinate(lat=28.6325, lng=77.2200),
            Coordinate(lat=28.6350, lng=77.2240),
            Coordinate(lat=28.6385, lng=77.2295),   # destination – Barakhamba
        ],
        safety_score=0.41,
        factors=SafetyFactors(
            lighting=0.30,
            crowd=0.35,
            transit=0.50,
            isolation=0.38,
            incidents=0.45,
        ),
        distance_km=0.9,
        estimated_minutes=11,
    ),
]
