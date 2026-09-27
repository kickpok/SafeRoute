"""
SafeRoute Backend – API routes.

All HTTP endpoints live here.  Business logic is delegated to
app/services.py so routes stay thin and testable.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from app import services
from app.schemas import ErrorResponse, RouteObject, RouteRequest, RoutesResponse

router = APIRouter(prefix="/api/v1", tags=["routes"])

PersonaType = Literal["default", "solo_night", "with_kids", "late_shift"]


# ── GET & POST /api/v1/routes ───────────────────────────────────────
@router.get(
    "/routes",
    response_model=RoutesResponse,
    summary="List candidate routes",
    description=(
        "Returns all candidate routes with safety scores and factor "
        "breakdowns scored by Track A for the requested persona profile and hour. "
        "Track C should use this endpoint to populate the map UI."
    ),
    responses={
        200: {"description": "Candidate routes returned successfully"},
        422: {"description": "Validation error (unsupported persona or hour out of range)"},
    },
)
async def list_routes(
    persona: Optional[PersonaType] = Query(
        "default",
        description="Persona profile for safety scoring (default, solo_night, with_kids, late_shift)",
    ),
    hour: Optional[int] = Query(
        None,
        ge=0,
        le=23,
        description="Hour of day for time-of-day safety adjustment (0-23, defaults to current server hour)",
    ),
) -> RoutesResponse:
    applied_persona = persona or "default"
    routes = services.get_all_routes(persona=applied_persona, hour=hour)
    # Use the first/last coordinate of the first route as origin/dest
    # for the response wrapper (mock data all share the same endpoints).
    origin = routes[0].coordinates[0]
    destination = routes[0].coordinates[-1]
    return RoutesResponse(
        origin=origin,
        destination=destination,
        routes=routes,
    )


@router.post(
    "/routes",
    response_model=RoutesResponse,
    summary="List candidate routes for origin/destination",
    description="Accepts candidate route request with origin/destination and optional persona & hour query parameters.",
)
async def list_routes_post(
    payload: RouteRequest | None = None,
    persona: Optional[PersonaType] = Query(
        "default",
        description="Persona profile for safety scoring",
    ),
    hour: Optional[int] = Query(
        None,
        ge=0,
        le=23,
        description="Hour of day (0-23)",
    ),
) -> RoutesResponse:
    return await list_routes(persona=persona, hour=hour)


# ── GET /api/v1/routes/{route_id} ──────────────────────────────────
@router.get(
    "/routes/{route_id}",
    response_model=RouteObject,
    summary="Get a single route by ID",
    description="Look up one candidate route by its unique route_id, with optional persona and hour parameters.",
    responses={
        200: {"description": "Route found"},
        404: {
            "description": "Route not found",
            "model": ErrorResponse,
        },
        422: {"description": "Validation error (unsupported persona or hour out of range)"},
    },
)
async def get_route(
    route_id: str,
    persona: Optional[PersonaType] = Query(
        "default",
        description="Persona profile for safety scoring",
    ),
    hour: Optional[int] = Query(
        None,
        ge=0,
        le=23,
        description="Hour of day (0-23)",
    ),
) -> RouteObject:
    route = services.get_route_by_id(route_id, persona=persona or "default", hour=hour)
    if route is None:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{route_id}' not found",
        )
    return route
