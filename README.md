# SafeRoute

Pedestrian safety-routing application — hackathon project.

## Repository layout

```
SafeRoute/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── schemas.py         # Frozen API contract (Pydantic models)
│   │   ├── mock_data.py       # Realistic mock routes (replace with Track A export)
│   │   ├── services.py        # Business logic / data-access layer
│   │   └── routes.py          # FastAPI route handlers
│   ├── main.py                # App entry point
│   ├── config.json            # Runtime configuration
│   └── requirements.txt       # Python dependencies
├── track_a_data_ml/
│   ├── osm_features.py        # Lighting, business density, isolation (OpenStreetMap)
│   ├── vision_features.py     # Crowd count (YOLOv8) + lighting proxy from street imagery
│   ├── incident_features.py   # Time-decayed, corroboration-filtered incident scoring
│   ├── osrm_utils.py          # Parses OSRM route responses (candidate routes)
│   ├── scoring.py             # Composite safety score, persona weights, time-of-day
│   ├── chart_format.py        # Radar-chart-ready output for Track C
│   ├── assistant.py           # Explainable scoring + persona/time what-if for the Safety Assistant
│   ├── export_routes.py       # Exports scored routes as static JSON for the backend to serve
│   ├── main.py                # score_all_routes() — ties the whole pipeline together
│   ├── API_CONTRACT.md        # Original live-scoring endpoint spec (superseded by static export, see below)
│   └── ASSISTANT_CONTRACT.md  # What the Safety Assistant should call and expect back
└── README.md
```

## Quick start (backend)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

## API endpoints (Phase 1)

| Method | Path                        | Description               |
|--------|-----------------------------|---------------------------|
| GET    | `/api/v1/routes`            | List all candidate routes |
| GET    | `/api/v1/routes/{route_id}` | Get a single route by ID  |
| GET    | `/health`                   | Health check              |

**Needed for dynamic persona/time-of-day (see Track A section below):** add
an optional `persona` query param to `GET /api/v1/routes` — e.g.
`GET /api/v1/routes?persona=solo_night` — that picks which exported JSON
file `services.py` loads. Small addition, not an architecture change.

## Track integration

- **Track C (Frontend)**: Consume `GET /api/v1/routes` — returns routes with
  safety scores and factor breakdowns. `track_a_data_ml/chart_format.py`
  can reshape any route's `factor_breakdown` into radar-chart-ready data if
  useful on your end.

- **Track A (ML) — done, integration step below**: Run
  `python track_a_data_ml/export_routes.py` to generate one JSON file per
  persona under `track_a_data_ml/exported_routes/` (`routes_default.json`,
  `routes_solo_night.json`, `routes_with_kids.json`, `routes_late_shift.json`).
  Copy/point `app/mock_data.py` (or wherever `services.py` reads from) at
  these files instead of the placeholder mock data.

  **Field names in the export are a best guess** at `schemas.py`'s
  `RouteObject` (route_id, distance_km, duration_min, polyline, safety_score,
  factor_breakdown, safe_islands, explanation) — since that contract is
  frozen, whoever owns `schemas.py` should confirm/correct the key names in
  `export_routes.py`'s `_to_route_object()` function before wiring it in.

- **Safety Assistant**: See `track_a_data_ml/ASSISTANT_CONTRACT.md` for the
  functions backing "which route is safer for X", "why did this score
  lower", and escape-mode nearest-refuge lookups. These call the same
  scoring engine used for the export above — no separate logic to maintain.
