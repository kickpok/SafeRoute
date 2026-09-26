# SafeRoute — Safety Assistant Contract (assistant.py)

Additive layer on top of the existing Track A pipeline. Nothing in
`scoring.py`, `main.py`, `osm_features.py`, `vision_features.py`,
`incident_features.py`, `osrm_utils.py`, or `chart_format.py` was changed.
`API_CONTRACT.md` and every existing endpoint/response shape Track B built
against are untouched.

This exists so the Safety Assistant (whether it's a feature inside Track B's
backend or a separate LLM-calling service) never has to compute a safety
score itself — it calls these functions and narrates pre-computed, ranked
facts.

---

## 1. Which personas exist (don't invent new ones)

```python
from assistant import list_personas
list_personas()
# {"default": {...weights}, "solo_night": {...}, "with_kids": {...}, "late_shift": {...}}
```

## 2. "Which route is safer for a solo traveller at 11 PM?"

```python
from assistant import compare_routes
compare_routes(osrm_response, reports=[], persona="solo_night", hour=23)
```
Returns everything `score_all_routes()` already returns, PLUS an
`explanation` block per route and a top-level `safest_route_id` naming the
answer outright:
```json
{
  "persona": "solo_night",
  "hour": 23,
  "safest_route_id": "route_a",
  "routes": [
    {
      "id": "route_a", "score": 62.2, "distance_km": 2.14, "...": "...",
      "explanation": {
        "ranked_factors": [ {"factor": "lighting", "value": 0.72, "contribution": 0.202}, "..." ],
        "strongest_factor": {"factor": "lighting", "...": "..."},
        "weakest_factor": {"factor": "business", "...": "..."},
        "summary": "Score 62.2/100 for persona 'solo_night' at hour 23. Most positive factor: lighting (value 0.72). Most negative factor: business (value 0.3)."
      }
    }
  ]
}
```
The assistant reads `summary` (or the ranked list, for more detail) and
narrates it — it never subtracts or compares numbers itself.

## 3. "How does the score change for a family / at a different time?"

```python
from assistant import persona_sensitivity, time_sensitivity

persona_sensitivity(features, hour=22)
# {"hour": 22, "baseline_persona": "default",
#  "results": {"with_kids": {"score": 57.3, "delta_vs_default": -3.2, "breakdown": {...}}, ...}}

time_sensitivity(features, persona="solo_night")
# {"persona": "solo_night", "baseline_hour": 12,
#  "results": {8: {"score": 70.7, "delta_vs_midday": 0.0, ...}, 23: {"score": 62.2, "delta_vs_midday": -8.5, ...}}}
```
`features` here is the same dict `build_features_live()` (in `main.py`)
already produces for a route — nothing new to compute upstream.

## 4. "Why did this route score lower?"

```python
from assistant import explain_score
explain_score(score, persona, hour, breakdown)  # breakdown = same dict score_route() already returns
```
Returns the ranked factors + strongest/weakest + a one-line summary, as
shown above. This is also attached automatically to every route inside
`compare_routes()`.

## 5. Escape mode — nearest usable refuge

`safe_islands` already contains real POI coordinates + types (pharmacy,
police, shop, ...) — no separate emergency scoring system was built, per
spec. One convenience function added to sort what's already there by
distance from the traveler's current position:

```python
from assistant import nearest_safe_islands
nearest_safe_islands(current_lat, current_lon, safe_islands, limit=3)
# [{"lat":.., "lon":.., "type": "pharmacy", "distance_m": 120.4}, ...]
```

---

## What did NOT change
- `score_route()` and `score_all_routes()` — same inputs, same outputs, same keys.
- OSRM input format — still raw OSRM JSON via `osrm_utils.parse_osrm_response()`.
- Track B's REST endpoints and response shapes in `API_CONTRACT.md` — untouched.
- No new personas were added — only the 4 already in `config.py` are used anywhere.
