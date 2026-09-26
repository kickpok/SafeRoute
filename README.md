# SafeRoute

Pedestrian safety-routing application — hackathon project.

## Repository layout

```
SafeRoute/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── schemas.py      # Frozen API contract (Pydantic models)
│   │   ├── mock_data.py    # Realistic mock routes (replace with Track A data)
│   │   ├── services.py     # Business logic / data-access layer
│   │   └── routes.py       # FastAPI route handlers
│   ├── main.py             # App entry point
│   ├── config.json         # Runtime configuration
│   └── requirements.txt    # Python dependencies
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

## Track integration

- **Track C (Frontend)**: Consume `GET /api/v1/routes` — returns routes with safety scores and factor breakdowns.
- **Track A (ML)**: When ready, export scored routes as JSON matching the `RouteObject` schema and update `app/services.py` to load from that source.