"""
SafeRoute Backend – SQLite Incident Store.

Stores crowdsourced incident reports for Track A's incident scoring pipeline.
Schema provides exactly the shape expected by Track A's score_all_routes():
    {"lat": float, "lon": float, "timestamp": float, "severity": float}
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("saferoute.incident_store")


def _get_db_path() -> str:
    env_path = os.getenv("SQLITE_DB_PATH")
    if env_path:
        return env_path

    try:
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
        if cfg_path.exists():
            with open(cfg_path) as f:
                cfg = json.load(f)
                if "sqlite_db_path" in cfg:
                    p = cfg["sqlite_db_path"]
                    if p == ":memory:":
                        return p
                    return str(Path(__file__).resolve().parent.parent / p)
    except Exception as e:
        logger.warning("Could not read sqlite_db_path from config: %s", e)

    return str(Path(__file__).resolve().parent.parent / "incidents.db")


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize the SQLite schema if it does not already exist."""
    path = db_path or _get_db_path()
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                timestamp REAL NOT NULL,
                severity REAL NOT NULL,
                description TEXT
            )
        """)
        conn.commit()


def create_incident(
    lat: float,
    lon: float,
    severity: float = 0.5,
    description: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create and store a new incident report.
    Timestamp is stamped server-side in Unix seconds.
    """
    path = db_path or _get_db_path()
    init_db(path)

    incident_id = f"incident_{uuid.uuid4().hex[:12]}"
    now_ts = float(time.time())
    severity = max(0.0, min(1.0, float(severity)))

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO incidents (id, lat, lon, timestamp, severity, description)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (incident_id, float(lat), float(lon), now_ts, severity, description),
        )
        conn.commit()

    return {
        "id": incident_id,
        "lat": lat,
        "lon": lon,
        "timestamp": now_ts,
        "severity": severity,
        "description": description,
    }


def get_reports_for_scoring(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve all stored incidents in the exact format Track A expects:
    [{"lat": ..., "lon": ..., "timestamp": ..., "severity": ...}]
    """
    path = db_path or _get_db_path()
    init_db(path)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT lat, lon, timestamp, severity FROM incidents")
        rows = cursor.fetchall()
        return [
            {
                "lat": row["lat"],
                "lon": row["lon"],
                "timestamp": row["timestamp"],
                "severity": row["severity"],
            }
            for row in rows
        ]


# Initialize table on import
init_db()
