"""
OSM feature extraction via the Overpass API. No API key needed.

Given a route as a list of (lat, lon) points, buffers a corridor around it
and pulls: lit ways, POI density (shops/pharmacies/police), and a simple
dead-end/isolation signal from way endpoints.
"""
import requests
from config import OVERPASS_URL


def _bbox_from_route(route, pad=0.003):
    lats = [p[0] for p in route]
    lons = [p[1] for p in route]
    return (min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad)


def fetch_osm_data(route):
    south, west, north, east = _bbox_from_route(route)
    query = f"""
    [out:json][timeout:25];
    (
      way["highway"]({south},{west},{north},{east});
      node["shop"]({south},{west},{north},{east});
      node["amenity"~"pharmacy|police"]({south},{west},{north},{east});
    );
    out body geom;
    """
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=30)
    resp.raise_for_status()
    return resp.json()["elements"]


def lighting_score(elements):
    ways = [e for e in elements if e.get("type") == "way" and "highway" in e.get("tags", {})]
    if not ways:
        return 0.5  # no data -> neutral, don't let it tank the score
    lit = [w for w in ways if w.get("tags", {}).get("lit") == "yes"]
    return round(len(lit) / len(ways), 3)


def business_score(elements):
    pois = [
        e for e in elements
        if e.get("type") == "node"
        and ("shop" in e.get("tags", {}) or e.get("tags", {}).get("amenity") in ("pharmacy", "police"))
    ]
    # 15+ relevant POIs along the corridor -> treat as a fully-served score
    return round(min(len(pois) / 15, 1.0), 3)


def isolation_score(elements):
    """Crude proxy: fraction of way endpoints that don't connect to anything
    else nearby (dead ends). Higher return value = LESS isolated = safer."""
    endpoint_counts = {}
    for e in elements:
        if e.get("type") == "way" and "geometry" in e and len(e["geometry"]) >= 2:
            for pt in (e["geometry"][0], e["geometry"][-1]):
                key = (round(pt["lat"], 5), round(pt["lon"], 5))
                endpoint_counts[key] = endpoint_counts.get(key, 0) + 1
    if not endpoint_counts:
        return 0.5
    dead_ends = sum(1 for v in endpoint_counts.values() if v == 1)
    return round(1 - (dead_ends / len(endpoint_counts)), 3)


def safe_islands(elements):
    """Fallback safe-stop points to pin on the map: open shops, pharmacies, police."""
    islands = []
    for e in elements:
        if e.get("type") == "node":
            tags = e.get("tags", {})
            kind = tags.get("amenity") or tags.get("shop")
            if kind:
                islands.append({"lat": e["lat"], "lon": e["lon"], "type": kind})
    return islands
