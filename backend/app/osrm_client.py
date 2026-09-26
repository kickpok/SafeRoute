"""
SafeRoute Backend – OSRM Routing Client.

Fetches candidate routes between coordinates using OpenStreetMap Routing Machine (OSRM).
Passes raw GeoJSON-enabled responses directly to Track A's scoring engine.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

import requests

logger = logging.getLogger("saferoute.osrm_client")


def _get_osrm_base_url() -> str:
    # 1. Environment variable override
    env_url = os.getenv("OSRM_BASE_URL")
    if env_url:
        return env_url.rstrip("/")

    # 2. config.json
    try:
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
        if cfg_path.exists():
            with open(cfg_path) as f:
                cfg = json.load(f)
                if "osrm_base_url" in cfg:
                    return cfg["osrm_base_url"].rstrip("/")
    except Exception as e:
        logger.warning("Could not read OSRM_BASE_URL from config: %s", e)

    # 3. Default public OSRM demo server
    return "http://router.project-osrm.org"


def fetch_candidate_routes(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    timeout_seconds: float = 10.0,
) -> Dict[str, Any]:
    """
    Fetch candidate routes from OSRM between start and end coordinates.

    Uses alternatives=true, overview=full, geometries=geojson.
    Tries 'foot' profile first, falling back to 'driving' if the server does
    not support pedestrian routing (e.g. public demo server).
    """
    base_url = _get_osrm_base_url()
    coords_param = f"{start_lon},{start_lat};{end_lon},{end_lat}"

    # Try pedestrian profile first, then driving
    profiles = ["foot", "driving"]
    last_error = None

    for profile in profiles:
        url = f"{base_url}/route/v1/{profile}/{coords_param}"
        params = {
            "alternatives": "true",
            "overview": "full",
            "geometries": "geojson",
        }
        try:
            resp = requests.get(url, params=params, timeout=timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    return data
                elif data.get("code") == "NoRoute":
                    raise ValueError(f"No route found between coordinates ({start_lat},{start_lon}) and ({end_lat},{end_lon})")
            elif resp.status_code in (400, 404) and profile == "foot":
                # Public server may only support driving
                logger.info("OSRM 'foot' profile not supported at %s; trying 'driving'", base_url)
                continue
            else:
                resp.raise_for_status()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if profile == "foot":
                continue
            break

    logger.error("Failed to fetch routes from OSRM (%s): %s", base_url, last_error)
    raise RuntimeError(f"OSRM routing request failed: {last_error}")
