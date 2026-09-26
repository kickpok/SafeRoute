"""
Parses OSRM's /route/v1/{profile}/{coords} response into the plain
(lat, lon) list that osm_features.py, vision_features.py and
incident_features.py all expect.

Call OSRM like:
  GET {osrm_host}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}
      ?alternatives=true&overview=full&geometries=geojson

- alternatives=true  -> get 2-3 candidate routes in ONE call, instead of
                         hitting OSRM separately per route
- geometries=geojson -> this parser expects GeoJSON coordinates, not the
                         default encoded polyline string

OSRM returns coordinates as [lon, lat] (GeoJSON order) -- flipping that is
the #1 bug source when wiring OSRM into the rest of this pipeline, so it's
handled here once instead of in every caller.
"""


def parse_osrm_response(osrm_response: dict) -> list:
    """Returns a list of route dicts (one per alternative), each already in
    the (lat, lon) order the rest of the pipeline expects."""
    routes = []
    for route in osrm_response.get("routes", []):
        coords_lonlat = route["geometry"]["coordinates"]
        coords_latlon = [(lat, lon) for lon, lat in coords_lonlat]
        routes.append({
            "coordinates": coords_latlon,
            "distance_km": round(route["distance"] / 1000, 2),
            "duration_min": round(route["duration"] / 60, 1),
        })
    return routes


def sample_points(coordinates: list, every_n: int = 5) -> list:
    """OSRM route geometry can have hundreds of points -- feature extraction
    (especially the vision pipeline, one image fetch per point) doesn't need
    all of them. Thin it out, always keeping the last point."""
    if len(coordinates) <= every_n:
        return coordinates
    return coordinates[::every_n] + [coordinates[-1]]
