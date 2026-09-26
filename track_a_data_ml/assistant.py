"""
SafeRoute Safety Assistant support layer.

Built ADDITIVELY on top of the existing pipeline -- does not modify or
replace anything in scoring.py, osm_features.py, vision_features.py,
incident_features.py, osrm_utils.py, chart_format.py, or main.py.

Purpose: produce deterministic, pre-computed, ranked data so an LLM-based
assistant never has to do arithmetic itself -- it only narrates what's
already been calculated here.
"""
import math

from config import PERSONA_WEIGHTS
from scoring import score_route
from main import score_all_routes


# ---------------- Dynamic persona / what-if ----------------

def list_personas() -> dict:
    """The existing personas and their weights, exactly as defined in
    config.py -- nothing invented here."""
    return PERSONA_WEIGHTS


def persona_sensitivity(features: dict, hour: int = 12, personas: list = None) -> dict:
    """Same route, same hour, every persona -- proves the score actually
    changes per persona and by how much relative to 'default'."""
    personas = personas or list(PERSONA_WEIGHTS.keys())
    baseline = score_route(features, persona="default", hour=hour)
    results = {}
    for p in personas:
        r = score_route(features, persona=p, hour=hour)
        results[p] = {
            "score": r["score"],
            "delta_vs_default": round(r["score"] - baseline["score"], 1),
            "breakdown": r["breakdown"],
        }
    return {"hour": hour, "baseline_persona": "default", "results": results}


def time_sensitivity(features: dict, persona: str = "default", hours: list = None) -> dict:
    """Same route, same persona, across several hours -- proves time-of-day
    actually changes the score."""
    hours = hours or [8, 14, 18, 22, 23]
    baseline_hour = 12
    baseline = score_route(features, persona=persona, hour=baseline_hour)
    results = {}
    for h in hours:
        r = score_route(features, persona=persona, hour=h)
        results[h] = {
            "score": r["score"],
            "delta_vs_midday": round(r["score"] - baseline["score"], 1),
            "breakdown": r["breakdown"],
        }
    return {"persona": persona, "baseline_hour": baseline_hour, "results": results}


# ---------------- Explainable scoring for the assistant ----------------

def explain_score(score: float, persona: str, hour: int, breakdown: dict) -> dict:
    """Turns one score + breakdown into a ranked, ready-to-narrate
    explanation. An LLM reads this; it never computes anything."""
    factors = [{"factor": name, **data} for name, data in breakdown.items()]
    ranked = sorted(factors, key=lambda f: f["contribution"], reverse=True)
    strongest, weakest = ranked[0], ranked[-1]
    return {
        "score": score,
        "persona": persona,
        "hour": hour,
        "ranked_factors": ranked,
        "strongest_factor": strongest,
        "weakest_factor": weakest,
        "summary": (
            f"Score {score}/100 for persona '{persona}' at hour {hour}. "
            f"Most positive factor: {strongest['factor']} (value {strongest['value']}). "
            f"Most negative factor: {weakest['factor']} (value {weakest['value']})."
        ),
    }


def compare_routes(osrm_response: dict, reports: list = None, persona: str = "default", hour: int = None) -> dict:
    """Deterministic answer to 'which route is safer' -- runs the existing
    score_all_routes() (unchanged), attaches an explanation to each route,
    and names the safest one outright so the assistant never compares
    numbers itself."""
    routes = score_all_routes(osrm_response, reports=reports, persona=persona, hour=hour)
    for route in routes:
        route["explanation"] = explain_score(route["score"], persona, hour, route["breakdown"])
    safest = max(routes, key=lambda r: r["score"])
    return {
        "persona": persona,
        "hour": hour,
        "routes": routes,
        "safest_route_id": safest["id"],
    }


# ---------------- Escape mode / safe islands ----------------

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_safe_islands(current_lat: float, current_lon: float, safe_islands: list, limit: int = 3) -> list:
    """Sorts an EXISTING safe_islands list (same lat/lon/type shape
    osm_features.safe_islands() already produces) by distance from the
    traveler's current position. Does not generate or score islands
    differently -- just orders what's already there, for 'nearest refuge'
    in escape mode."""
    with_dist = [
        {**island, "distance_m": round(_haversine_m(current_lat, current_lon, island["lat"], island["lon"]), 1)}
        for island in safe_islands
    ]
    return sorted(with_dist, key=lambda i: i["distance_m"])[:limit]
