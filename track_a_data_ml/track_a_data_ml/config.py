import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env support is optional; env vars still work without it

MAPILLARY_TOKEN = os.getenv("MAPILLARY_TOKEN", "")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Persona weight presets -- each set must sum to ~1.0
PERSONA_WEIGHTS = {
    "default":    {"lighting": 0.20, "crowd": 0.20, "business": 0.15, "transit": 0.10, "incident": 0.20, "isolation": 0.15},
    "solo_night": {"lighting": 0.28, "crowd": 0.22, "business": 0.10, "transit": 0.08, "incident": 0.22, "isolation": 0.10},
    "with_kids":  {"lighting": 0.15, "crowd": 0.15, "business": 0.20, "transit": 0.20, "incident": 0.15, "isolation": 0.15},
    "late_shift": {"lighting": 0.30, "crowd": 0.15, "business": 0.10, "transit": 0.15, "incident": 0.20, "isolation": 0.10},
}
