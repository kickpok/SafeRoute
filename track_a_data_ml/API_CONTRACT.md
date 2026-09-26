# SafeRoute — API Contract (Track B)

This is what the backend needs to expose. Track A's `scoring.py` +
`osm_features.py` + `vision_features.py` + `incident_features.py` are the
internal library your route-scoring endpoint calls — you're wrapping them
in HTTP, not rewriting them.

All requests/responses are JSON. Standard HTTP status codes: `200` success,
`400` bad input, `500` server error — no custom error schema needed for a
hackathon.

---

## 1. Score candidate routes

`POST /api/routes/score`

**Request**
```json
{
  "start": {"lat": 28.6139, "lon": 77.2090},
  "end":   {"lat": 28.6200, "lon": 77.2200},
  "persona": "solo_night",
  "hour": 22
}
```
`persona` — one of `default`, `solo_night`, `with_kids`, `late_shift`.
`hour` — optional, defaults to current server hour.

**Response**
```json
{
  "routes": [
    {
      "id": "route_a",
      "distance_km": 2.1,
      "polyline": [[28.6139, 77.2090], [28.6150, 77.2130], [28.6200, 77.2200]],
      "score": 62.2,
      "breakdown": {
        "lighting":  {"value": 0.72, "weight": 0.28, "contribution": 0.202},
        "crowd":     {"value": 0.33, "weight": 0.22, "contribution": 0.073},
        "business":  {"value": 0.30, "weight": 0.10, "contribution": 0.030},
        "transit":   {"value": 0.50, "weight": 0.08, "contribution": 0.040},
        "incident":  {"value": 0.90, "weight": 0.22, "contribution": 0.198},
        "isolation": {"value": 0.80, "weight": 0.10, "contribution": 0.080}
      },
      "safe_islands": [
        {"lat": 28.6145, "lon": 77.2110, "type": "pharmacy"}
      ]
    }
  ]
}
```
`breakdown` is exactly `scoring.score_route()`'s output — pass it straight
to `chart_format.to_radar_series()` (or `to_radar_comparison()` across
routes) before sending to the frontend if you want to save Track C a step.

Implementation note: get 2–3 candidate routes from OSRM in one call —
`GET {osrm_host}/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?alternatives=true&overview=full&geometries=geojson`
— then pass the raw JSON straight to Track A's `main.score_all_routes(osrm_response, reports, persona, hour)`.
It already returns this exact response shape (id, distance_km, duration_min,
polyline, score, breakdown, safe_islands) — your endpoint can be a thin
wrapper around that one function call.

**Pedestrian routing note:** the public OSRM demo server only serves the
`driving` profile. If you're self-hosting OSRM, build it with the `foot`
profile (`profiles/foot.lua`) so routes actually follow footpaths — using
`driving` for a walking-safety app will route people down highways. If
standing up a self-hosted `foot` profile eats too much of your remaining
time, it's a fine tradeoff to demo on `driving` and say so if asked.

---

## 2. Submit an incident report

`POST /api/incidents`

**Request**
```json
{
  "lat": 28.6139,
  "lon": 77.2090,
  "severity": 0.7,
  "description": "poorly lit stretch, felt unsafe"
}
```
Server should stamp `timestamp` itself (unix seconds) on receipt — don't
trust a client-supplied timestamp. Store reports in whatever DB is fastest
to stand up (SQLite is fine); `incident_features.py` expects a list of
`{"lat", "lon", "timestamp", "severity"}` dicts, so shape your DB rows to
match on the way out.

**Response**
```json
{"status": "received", "id": "incident_123"}
```

---

## 3. Post-walk feedback

`POST /api/feedback`

**Request**
```json
{"route_id": "route_a", "felt_safe": true}
```
**Response**
```json
{"status": "recorded"}
```
Stretch goal only — feed this back into adjusting weights over time. Not
required for the demo to work.

---

## 4. Check-in / deviation alerts

`POST /api/checkin/start`
```json
{"user_id": "u1", "route_id": "route_a", "trusted_contact": "+91XXXXXXXXXX"}
```
→ `{"checkin_id": "c1"}`

`POST /api/checkin/ping`
```json
{"checkin_id": "c1", "lat": 28.6145, "lon": 77.2110}
```
→ `{"status": "on_track", "deviation": false}`
If the pinged location is more than ~150m from the chosen route's polyline,
return `"deviation": true` — frontend uses that to trigger the trusted-contact
alert.

`POST /api/alert/distress`
```json
{"user_id": "u1", "lat": 28.6145, "lon": 77.2110}
```
→ `{"status": "alert_sent"}`
For the demo, "sending" the alert can just mean logging it / showing a toast
— no need to wire up real SMS unless there's spare time.

---

## Quick checklist for Track B
- [ ] Stand up `/api/routes/score` calling into Track A's `scoring.py`
- [ ] SQLite (or similar) table for incident reports matching `incident_features.py`'s expected shape
- [ ] `/api/incidents` write endpoint
- [ ] `/api/checkin/*` endpoints (can be stubbed/in-memory for the demo)
- [ ] Share your actual routing-engine choice (Google Directions vs OSRM) with Track A early — it changes what `route` looks like going into `build_features_live()`
