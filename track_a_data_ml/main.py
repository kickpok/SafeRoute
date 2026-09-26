"""
End-to-end demo: score a single route.

Run with --mock to get an instant, correctly-shaped result with zero API
calls -- use this output TODAY to unblock whoever's building the frontend
or the alert backend, while you wire up real data underneath it.
"""
import argparse
import json
import time

import osm_features
import vision_features
import incident_features
from scoring import score_route
from osrm_utils import parse_osrm_response, sample_points


def build_features_mock():
    return {
        "lighting": 0.72,
        "crowd": 0.60,
        "business": 0.55,
        "transit": 0.50,
        "incident": 0.90,
        "isolation": 0.80,
    }


def build_features_live(route, reports):
    # route here is a list of (lat, lon) points -- e.g. one entry from
    # osrm_utils.parse_osrm_response(osrm_json)[i]["coordinates"], thinned
    # with sample_points() before being passed in.
    elements = osm_features.fetch_osm_data(route)
    lighting = osm_features.lighting_score(elements)
    business = osm_features.business_score(elements)
    isolation = osm_features.isolation_score(elements)
    islands = osm_features.safe_islands(elements)

    mid_lat, mid_lon = route[len(route) // 2]
    vf = vision_features.vision_features_for_point(mid_lat, mid_lon)
    crowd = min((vf["person_count"] or 3) / 10, 1.0)
    lighting = max(lighting, vf["brightness"])  # take whichever signal is stronger

    incident_scores = [incident_features.incident_score(lat, lon, reports) for lat, lon in route]
    incident = sum(incident_scores) / len(incident_scores) if incident_scores else 1.0

    features = {
        "lighting": lighting,
        "crowd": crowd,
        "business": business,
        "transit": 0.5,  # wire up GTFS lookup here once Track B's transit feed is ready
        "incident": incident,
        "isolation": isolation,
    }
    return features, islands


def score_all_routes(osrm_response, reports=None, persona="default", hour=None):
    """
    Ties together OSRM parsing + the full feature pipeline + scoring engine.
    This is what Track B's POST /api/routes/score handler should call directly.

    osrm_response: raw JSON from OSRM's /route/v1/... endpoint
                   (call it with alternatives=true&overview=full&geometries=geojson)
    Returns: list of dicts matching API_CONTRACT.md's response shape.
    """
    reports = reports or []
    hour = hour if hour is not None else int(time.strftime("%H"))
    parsed_routes = parse_osrm_response(osrm_response)

    results = []
    for i, route in enumerate(parsed_routes):
        thin_coords = sample_points(route["coordinates"], every_n=5)
        features, islands = build_features_live(thin_coords, reports)
        scored = score_route(features, persona=persona, hour=hour)
        results.append({
            "id": f"route_{chr(97 + i)}",  # route_a, route_b, ...
            "distance_km": route["distance_km"],
            "duration_min": route["duration_min"],
            "polyline": route["coordinates"],
            "score": scored["score"],
            "breakdown": scored["breakdown"],
            "safe_islands": islands,
        })
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="skip live API calls, use fixed sample features")
    parser.add_argument("--persona", default="default", choices=["default", "solo_night", "with_kids", "late_shift"])
    parser.add_argument("--hour", type=int, default=int(time.strftime("%H")))
    args = parser.parse_args()

    if args.mock:
        result = score_route(build_features_mock(), persona=args.persona, hour=args.hour)
        print(json.dumps(result, indent=2))
    else:
        # TODO: replace with a real call to your OSRM instance, e.g.:
        #   requests.get(f"{OSRM_HOST}/route/v1/foot/{lon1},{lat1};{lon2},{lat2}"
        #                "?alternatives=true&overview=full&geometries=geojson").json()
        route = [(28.6139, 77.2090), (28.6145, 77.2110), (28.6150, 77.2130)]
        reports = []
        features, islands = build_features_live(route, reports)
        result = score_route(features, persona=args.persona, hour=args.hour)
        result["safe_islands"] = islands
        print(json.dumps(result, indent=2))
