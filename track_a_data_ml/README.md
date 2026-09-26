# SafeRoute — Track A: Data / ML Pipeline

## What's in here
- `osm_features.py` — lighting, business density, isolation from OpenStreetMap (free, no key needed)
- `vision_features.py` — crowd count (YOLOv8) + lighting proxy from street-level images (Mapillary, free tier)
- `incident_features.py` — time-decayed, corroboration-filtered incident scoring
- `scoring.py` — combines everything into one 0–100 score with a full factor breakdown
- `main.py` — run this to test the whole pipeline end to end; also exposes `score_all_routes()`, the function Track B's endpoint should call directly
- `osrm_utils.py` — parses OSRM's route response (fixes the lon/lat order gotcha) into what the rest of the pipeline expects
- `chart_format.py` — turns a score into radar-chart-ready JSON for Track C
- `API_CONTRACT.md` — the endpoints Track B needs to build on top of this

No paid APIs anywhere in this pipeline, on purpose — nobody's blocked by a missing credit card mid-hackathon.

## Laptop setup (one-time)

1. Install Python 3.10+ if you don't have it: https://python.org/downloads

2. Open a terminal in this folder and create a virtual environment:
   - Windows: `python -m venv venv` then `venv\Scripts\activate`
   - Mac/Linux: `python3 -m venv venv` then `source venv/bin/activate`

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   (`ultralytics` pulls in PyTorch — this step can take a few minutes on the first run.)

4. **Optional but recommended** — free Mapillary token for real street images:
   - Sign up at mapillary.com → Developer → create an app → copy the access token
   - Create a file named `.env` in this folder containing:
     ```
     MAPILLARY_TOKEN=your_token_here
     ```
   - No token yet? Nothing breaks — `vision_features.py` falls back to a neutral default so the pipeline still runs.

5. First real (non-mock) run auto-downloads the YOLOv8 weights (~6MB) — needs internet once.

## Try it right now — no setup beyond step 3

```
python main.py --mock
```

Prints a fully-shaped score using fixed sample numbers. Send this exact JSON shape to whoever's building the frontend or the alert backend today — they can build against it while you wire up real data underneath.

## Run it for real

```
python main.py --persona solo_night --hour 22
```

Personas: `default`, `solo_night`, `with_kids`, `late_shift` — each has different factor weights (see `config.py`).

Before running for real, edit the `route` and `reports` placeholders at the bottom of `main.py` with your actual demo route and any crowdsourced reports Track B's backend is storing.

## The output contract (share this with Track B / Track C now)

```json
{
  "score": 62.2,
  "persona": "solo_night",
  "hour": 23,
  "breakdown": {
    "lighting":  {"value": 0.72, "weight": 0.28, "contribution": 0.202},
    "crowd":     {"value": 0.33, "weight": 0.22, "contribution": 0.073},
    "business":  {"value": 0.30, "weight": 0.10, "contribution": 0.030},
    "transit":   {"value": 0.50, "weight": 0.08, "contribution": 0.040},
    "incident":  {"value": 0.90, "weight": 0.22, "contribution": 0.198},
    "isolation": {"value": 0.80, "weight": 0.10, "contribution": 0.080}
  }
}
```

Every factor in `breakdown` maps directly to one bar on the explainability radar chart — that's not a coincidence, it's the whole pitch.

## Notes for the demo
- If Wi-Fi at the venue is unreliable, pre-run `main.py` for your actual demo route beforehand and save the JSON output as a static file — call that from the frontend instead of hitting Overpass/Mapillary live on stage.
- `isolation_score` and `lighting_score` are intentionally crude (endpoint-counting, tag-ratio) rather than "real" GIS analysis — that's a fine tradeoff for a hackathon; don't spend time making them fancier unless everything else is already working.
