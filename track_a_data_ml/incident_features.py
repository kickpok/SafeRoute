"""
Crowdsourced incident reports -> a time-decayed, distance-weighted safety
score per point on the route. Pure math, no scipy/geopandas -- installs
fast on any laptop.
"""
import math
import time

HALF_LIFE_DAYS = 90         # a report's weight halves every 90 days
INFLUENCE_RADIUS_M = 250    # reports beyond this barely affect a point
MIN_CORROBORATION = 2       # ignore isolated single reports (reduces griefing)


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _time_decay(report_ts, now_ts):
    age_days = max((now_ts - report_ts) / 86400, 0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def incident_score(lat, lon, reports, now_ts=None):
    """reports: list of {"lat", "lon", "timestamp" (unix seconds), "severity" (0-1)}
    Returns a safety score 0-1 where 1.0 = no meaningful incident signal nearby."""
    now_ts = now_ts if now_ts is not None else time.time()
    nearby_weighted = []
    for r in reports:
        dist = _haversine_m(lat, lon, r["lat"], r["lon"])
        if dist <= INFLUENCE_RADIUS_M:
            proximity = 1 - (dist / INFLUENCE_RADIUS_M)
            weight = _time_decay(r["timestamp"], now_ts) * proximity
            nearby_weighted.append(weight * r.get("severity", 0.5))

    if len(nearby_weighted) < MIN_CORROBORATION:
        return 1.0  # not enough corroborating reports to penalize the route

    penalty = min(sum(nearby_weighted) / len(nearby_weighted), 1.0)
    return round(1 - penalty, 3)
