"""
SafeRoute Backend – API routes.

All HTTP endpoints live here.  Business logic is delegated to
app/services.py so routes stay thin and testable.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ErrorResponse, RouteObject, RoutesResponse
from app import services

router = APIRouter(prefix="/api/v1", tags=["routes"])


# ── GET /api/v1/routes ──────────────────────────────────────────────
@router.get(
    "/routes",
    response_model=RoutesResponse,
    summary="List candidate routes",
    description=(
        "Returns all candidate routes with safety scores and factor "
        "breakdowns.  Track C should use this endpoint to populate the "
        "map UI."
    ),
    responses={
        200: {"description": "Candidate routes returned successfully"},
    },
)
async def list_routes() -> RoutesResponse:
    routes = services.get_all_routes()
    # Use the first/last coordinate of the first route as origin/dest
    # for the response wrapper (mock data all share the same endpoints).
    origin = routes[0].coordinates[0]
    destination = routes[0].coordinates[-1]
    return RoutesResponse(
        origin=origin,
        destination=destination,
        routes=routes,
    )


# ── GET /api/v1/routes/{route_id} ──────────────────────────────────
@router.get(
    "/routes/{route_id}",
    response_model=RouteObject,
    summary="Get a single route by ID",
    description="Look up one candidate route by its unique route_id.",
    responses={
        200: {"description": "Route found"},
        404: {
            "description": "Route not found",
            "model": ErrorResponse,
        },
    },
)
async def get_route(route_id: str) -> RouteObject:
    route = services.get_route_by_id(route_id)
    if route is None:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{route_id}' not found",
        )
    return route
