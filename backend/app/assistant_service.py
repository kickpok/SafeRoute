"""
SafeRoute Backend – Safety Assistant & Escape Mode Service.

Provides a thin, reliable backend capability layer for the LLM / Safety Assistant:
1. Fetching verified nearby safe refuge islands (from Overpass with curated fallbacks).
2. Escape Mode orchestrator: finding closest refuge, calculating OSRM escape path,
   and optionally triggering distress alerts.
3. Route comparison across personas (What-If simulation).
4. Structured safety explanations translating Track A breakdown metrics into human-readable insights.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from app import geo_utils, incident_store, osrm_client, track_a_bridge

logger = logging.getLogger("saferoute.assistant_service")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Curated fallback safe havens across Delhi NCR / urban reference hubs
FALLBACK_SAFE_ISLANDS = [
    {"name": "Connaught Place Police Station", "type": "police", "lat": 28.6315, "lon": 77.2167, "address": "Outer Circle, Connaught Place, New Delhi"},
    {"name": "Apollo 24hr Pharmacy", "type": "pharmacy", "lat": 28.6278, "lon": 77.2330, "address": "Barakhamba Road, Connaught Place, New Delhi"},
    {"name": "Delhi Police Post - Mandi House", "type": "police", "lat": 28.6215, "lon": 77.2420, "address": "Mandi House Metro Station, New Delhi"},
    {"name": "Medplus 24hr Chemist", "type": "pharmacy", "lat": 28.6315, "lon": 77.2320, "address": "KG Marg, New Delhi"},
    {"name": "AIIMS Emergency Care / Security", "type": "hospital", "lat": 28.5672, "lon": 77.2100, "address": "Sri Aurobindo Marg, Ansari Nagar, New Delhi"},
    {"name": "Lajpat Nagar Police Station", "type": "police", "lat": 28.5685, "lon": 77.2435, "address": "Ring Road, Lajpat Nagar, New Delhi"},
    {"name": "24hr Supermarket & Safe Kiosk", "type": "shop", "lat": 28.6145, "lon": 77.2495, "address": "Khan Market Area, New Delhi"},
    {"name": "ITO Security Post", "type": "police", "lat": 28.6252, "lon": 77.2372, "address": "ITO Crossing, New Delhi"},
]


def fetch_nearby_safe_islands(
    lat: float,
    lon: float,
    radius_meters: float = 1500.0,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    Find verified nearby safe refuge islands (police, pharmacies, hospitals, 24hr shops).
    
    1. Attempts live Overpass query around user coordinates.
    2. Gracefully incorporates fallback safe havens if Overpass fails or returns low density.
    3. Calculates exact haversine distances and returns sorted by proximity.
    """
    found_islands: List[Dict[str, Any]] = []
    seen_coords = set()

    # 1. Attempt Overpass query
    try:
        query = f"""
        [out:json][timeout:10];
        (
          node["amenity"~"pharmacy|police|hospital"](around:{int(radius_meters)},{lat},{lon});
          node["shop"~"convenience|supermarket|chemist"](around:{int(radius_meters)},{lat},{lon});
        );
        out body 25;
        """
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=8)
        if resp.status_code == 200:
            elements = resp.json().get("elements", [])
            for e in elements:
                if e.get("type") == "node" and "lat" in e and "lon" in e:
                    e_lat, e_lon = float(e["lat"]), float(e["lon"])
                    coord_key = (round(e_lat, 4), round(e_lon, 4))
                    if coord_key in seen_coords:
                        continue
                    seen_coords.add(coord_key)

                    tags = e.get("tags", {})
                    kind = tags.get("amenity") or tags.get("shop") or "refuge"
                    name = tags.get("name") or f"24hr {kind.replace('_', ' ').title()}"
                    dist = geo_utils.haversine_distance(lat, lon, e_lat, e_lon)
                    if dist <= radius_meters * 1.2:
                        found_islands.append({
                            "name": name,
                            "type": kind,
                            "lat": e_lat,
                            "lon": e_lon,
                            "distance_meters": round(dist, 1),
                            "address": tags.get("addr:street") or f"Near ({e_lat:.4f}, {e_lon:.4f})",
                        })
    except Exception as exc:
        logger.info("Overpass query bypassed or timed out: %s", exc)

    # 2. Add curated fallback islands if density is low
    if len(found_islands) < 3:
        for fb in FALLBACK_SAFE_ISLANDS:
            fb_lat, fb_lon = fb["lat"], fb["lon"]
            coord_key = (round(fb_lat, 4), round(fb_lon, 4))
            if coord_key in seen_coords:
                continue
            dist = geo_utils.haversine_distance(lat, lon, fb_lat, fb_lon)
            found_islands.append({
                "name": fb["name"],
                "type": fb["type"],
                "lat": fb_lat,
                "lon": fb_lon,
                "distance_meters": round(dist, 1),
                "address": fb.get("address", "Verified Safe Zone"),
            })
            seen_coords.add(coord_key)

    # Sort strictly by shortest distance to user
    found_islands.sort(key=lambda x: x["distance_meters"])
    return found_islands[:max_results]


def generate_escape_plan(
    current_lat: float,
    current_lon: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """
    Compute escape plan:
    1. Identifies the closest safe island.
    2. Obtains OSRM route from current position to refuge.
    3. Returns (selected_refuge, route_dict, other_nearby_refuges).
    """
    nearby = fetch_nearby_safe_islands(current_lat, current_lon, radius_meters=2500.0)
    if not nearby:
        # Ultimate fallback refuge
        nearby = [{
            "name": "Emergency Police Post",
            "type": "police",
            "lat": round(current_lat + 0.005, 5),
            "lon": round(current_lon + 0.005, 5),
            "distance_meters": 650.0,
            "address": "Nearest Safe Haven",
        }]

    target_refuge = nearby[0]

    # Fetch OSRM route from current location to refuge
    try:
        osrm_resp = osrm_client.fetch_candidate_routes(
            start_lat=current_lat,
            start_lon=current_lon,
            end_lat=target_refuge["lat"],
            end_lon=target_refuge["lon"],
        )
        first_route = osrm_resp.get("routes", [])[0]
        polyline = first_route.get("geometry", {}).get("coordinates", [])
        dist_km = round(first_route.get("distance", target_refuge["distance_meters"]) / 1000.0, 2)
        dur_min = round(first_route.get("duration", (target_refuge["distance_meters"] / 80.0) * 60) / 60.0, 1)
    except Exception as exc:
        logger.warning("OSRM escape routing fallback: %s", exc)
        # Straight line geometry fallback
        polyline = [
            [current_lon, current_lat],
            [target_refuge["lon"], target_refuge["lat"]],
        ]
        dist_km = round(target_refuge["distance_meters"] / 1000.0, 2)
        dur_min = max(1.0, round(dist_km / 4.0 * 60.0, 1))  # 4 km/h walking speed

    route_info = {
        "distance_km": dist_km,
        "duration_min": dur_min,
        "polyline": polyline,
    }

    return target_refuge, route_info, nearby[1:]


def explain_route_safety(
    score: float,
    breakdown: Dict[str, Any],
    persona: str = "default",
    hour: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Translate Track A numeric safety score and factor breakdown into structured explanations.
    """
    hour = hour if hour is not None else int(time.strftime("%H"))

    if score >= 75.0:
        safety_tier = "High Safety (Recommended)"
    elif score >= 50.0:
        safety_tier = "Moderate Safety (Caution Advised)"
    else:
        safety_tier = "High Risk (Avoid if Possible)"

    factor_analysis: Dict[str, Any] = {}
    strengths: List[str] = []
    risks: List[str] = []

    for factor_name, info in breakdown.items():
        if isinstance(info, dict):
            val = info.get("value", 0.5)
            weight = info.get("weight", 0.2)
            contrib = info.get("contribution", val * weight)
        else:
            val = float(info)
            weight = 0.2
            contrib = val * weight

        # Evaluate strength/risk
        if val >= 0.70:
            status = "good"
            strengths.append(f"{factor_name.replace('_', ' ').title()} is favorable ({int(val*100)}%)")
        elif val < 0.45:
            status = "concern"
            risks.append(f"{factor_name.replace('_', ' ').title()} is low ({int(val*100)}%)")
        else:
            status = "neutral"

        factor_analysis[factor_name] = {
            "score_pct": int(val * 100),
            "weight": weight,
            "contribution": contrib,
            "status": status,
        }

    # Generate narrative summary
    narrative_parts = [
        f"This route has an overall safety score of {score:.1f}/100 ({safety_tier}) under the '{persona}' profile at {hour:02d}:00."
    ]
    if 21 <= hour or hour < 6:
        narrative_parts.append("Late night time-of-day penalty applied to crowd and business activity.")

    if strengths:
        narrative_parts.append(f"Strengths: {', '.join(strengths)}.")
    if risks:
        narrative_parts.append(f"Areas of concern: {', '.join(risks)}.")
    else:
        narrative_parts.append("No major safety hazards identified along this corridor.")

    return {
        "score": score,
        "safety_tier": safety_tier,
        "persona_applied": persona,
        "hour_applied": hour,
        "key_strengths": strengths,
        "key_risks": risks,
        "factor_analysis": factor_analysis,
        "explanation": " ".join(narrative_parts),
    }


def compare_personas_for_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    personas: Optional[List[str]] = None,
    hour: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Score the same physical OSRM routes across multiple personas in Track A.
    """
    personas = personas or ["default", "solo_night", "with_kids", "late_shift"]
    hour = hour if hour is not None else int(time.strftime("%H"))

    # 1. Fetch OSRM candidate routes once
    osrm_resp = osrm_client.fetch_candidate_routes(
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
    )

    # 2. Get incident reports once
    reports = incident_store.get_reports_for_scoring()

    # 3. Run Track A scoring per persona
    routes_by_persona: Dict[str, List[Dict[str, Any]]] = {}
    for p in personas:
        routes_by_persona[p] = track_a_bridge.score_routes(
            osrm_response=osrm_resp,
            reports=reports,
            persona=p,
            hour=hour,
        )

    summary = (
        f"Compared {len(personas)} personas for route from ({start_lat:.4f}, {start_lon:.4f}) to "
        f"({end_lat:.4f}, {end_lon:.4f}) at {hour:02d}:00."
    )

    return {
        "hour_applied": hour,
        "routes_by_persona": routes_by_persona,
        "comparison_summary": summary,
    }
