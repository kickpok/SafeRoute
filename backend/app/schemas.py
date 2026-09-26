"""
SafeRoute Backend – Pydantic schemas (frozen API contract).

These schemas define the "route object" contract shared between
Track B (backend), Track A (scoring/ML), and Track C (frontend/map UI).

ANY change to these schemas is a breaking change — coordinate across tracks.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ── Factor breakdown ────────────────────────────────────────────────
class SafetyFactors(BaseModel):
    """Per-route safety factor breakdown.

    Each factor is a score from 0.0 (worst) to 1.0 (best).
    A value of ``None`` means the factor was not evaluated for this route.
    """

    lighting: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Street-lighting quality along the route",
    )
    crowd: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Pedestrian / commercial activity level",
    )
    transit: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Proximity to public-transit stops and stations",
    )
    isolation: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Inverse isolation — higher is better (less isolated)",
    )
    incidents: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Inverse incident density — higher is safer",
    )


# ── Coordinate pair ─────────────────────────────────────────────────
class Coordinate(BaseModel):
    """A single geographic point."""

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lng: float = Field(..., ge=-180.0, le=180.0, description="Longitude")


# ── Route object (the core contract) ────────────────────────────────
class RouteObject(BaseModel):
    """The canonical route-object returned by the SafeRoute API.

    This is the contract between Track A (scoring), Track B (API),
    and Track C (frontend).
    """

    route_id: str = Field(
        ..., min_length=1,
        description="Unique identifier for this candidate route",
    )
    name: str = Field(
        ..., min_length=1,
        description="Human-readable route label (e.g. 'Via MG Road')",
    )
    coordinates: List[Coordinate] = Field(
        ..., min_length=2,
        description="Ordered list of waypoints forming the route polyline",
    )
    safety_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Overall composite safety score (0 = dangerous, 1 = safest)",
    )
    factors: SafetyFactors = Field(
        ...,
        description="Breakdown of individual safety factors",
    )
    distance_km: Optional[float] = Field(
        None, ge=0.0,
        description="Total route distance in kilometres",
    )
    estimated_minutes: Optional[float] = Field(
        None, ge=0.0,
        description="Estimated walking time in minutes",
    )


# ── Request / Response wrappers ─────────────────────────────────────
class RouteRequest(BaseModel):
    """Request body for fetching candidate routes between two points."""

    origin: Coordinate = Field(..., description="Starting point")
    destination: Coordinate = Field(..., description="Destination point")


class RoutesResponse(BaseModel):
    """Response wrapper for the candidate-routes endpoint."""

    origin: Coordinate
    destination: Coordinate
    routes: List[RouteObject]


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx / 5xx."""

    detail: str = Field(..., description="Human-readable error message")
