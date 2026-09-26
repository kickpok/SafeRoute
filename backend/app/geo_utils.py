"""
SafeRoute Backend – Geographic calculation utilities for Phase 3 Deviation Engine.

Provides simple, explainable geometric distance calculations:
- Haversine distance between two coordinates in meters.
- Perpendicular / nearest distance from a point to a line segment in meters.
- Minimum distance from a coordinate to a multi-point polyline in meters.
"""

from __future__ import annotations

import math
from typing import Sequence
from app.schemas import Coordinate

# Earth's mean radius in meters
EARTH_RADIUS_METERS = 6371000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance between two points in meters using Haversine formula."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def point_to_segment_distance(
    p_lat: float, p_lng: float,
    a_lat: float, a_lng: float,
    b_lat: float, b_lng: float,
) -> float:
    """
    Calculate minimum distance from point P to line segment AB in meters.

    Uses equirectangular projection onto local Euclidean plane for segment projection,
    then evaluates distance to the closest point.
    """
    # If segment start and end are identical, return distance to point A
    if a_lat == b_lat and a_lng == b_lng:
        return haversine_distance(p_lat, p_lng, a_lat, a_lng)

    # Local planar projection in meters relative to point A
    mean_lat_rad = math.radians((a_lat + b_lat + p_lat) / 3.0)
    kx = math.cos(mean_lat_rad) * (math.pi / 180.0) * EARTH_RADIUS_METERS
    ky = (math.pi / 180.0) * EARTH_RADIUS_METERS

    px = (p_lng - a_lng) * kx
    py = (p_lat - a_lat) * ky

    bx = (b_lng - a_lng) * kx
    by = (b_lat - a_lat) * ky

    seg_len_sq = bx * bx + by * by
    if seg_len_sq == 0.0:
        return haversine_distance(p_lat, p_lng, a_lat, a_lng)

    # Projection factor t along vector AB
    t = (px * bx + py * by) / seg_len_sq
    t = max(0.0, min(1.0, t))

    # Closest point C on segment AB
    closest_lat = a_lat + t * (b_lat - a_lat)
    closest_lng = a_lng + t * (b_lng - a_lng)

    return haversine_distance(p_lat, p_lng, closest_lat, closest_lng)


def _extract_lat_lng(pt: Any) -> tuple[float, float]:
    """Extract (lat, lon) tuple from Coordinate, dict, or list/tuple."""
    if hasattr(pt, "lat") and hasattr(pt, "lng"):
        return float(pt.lat), float(pt.lng)
    if hasattr(pt, "lat") and hasattr(pt, "lon"):
        return float(pt.lat), float(pt.lon)
    if isinstance(pt, dict):
        lat = pt.get("lat")
        lng = pt.get("lng") if "lng" in pt else pt.get("lon")
        return float(lat), float(lng)
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        return float(pt[0]), float(pt[1])
    raise ValueError(f"Cannot extract lat/lng from {pt}")


def min_distance_to_route(lat: float, lng: float, coordinates: Sequence[Any]) -> float:
    """
    Calculate the shortest distance (in meters) from a coordinate to any segment
    in the route polyline. Supports Coordinate instances, [lat, lon] pairs, or dicts.
    """
    if not coordinates:
        return 0.0

    if len(coordinates) == 1:
        c_lat, c_lng = _extract_lat_lng(coordinates[0])
        return haversine_distance(lat, lng, c_lat, c_lng)

    min_dist = float("inf")
    for i in range(len(coordinates) - 1):
        a_lat, a_lng = _extract_lat_lng(coordinates[i])
        b_lat, b_lng = _extract_lat_lng(coordinates[i + 1])
        dist = point_to_segment_distance(lat, lng, a_lat, a_lng, b_lat, b_lng)
        if dist < min_dist:
            min_dist = dist

    return min_dist
