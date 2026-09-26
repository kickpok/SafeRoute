"""
SafeRoute Backend – Integration & Regression Test Suite.

Verifies:
1. Track A scoring engine direct import and execution.
2. SQLite incident persistence and report extraction.
3. POST /api/routes/score end-to-end integration.
4. Track A response schema compliance (id, polyline, score, breakdown, safe_islands).
5. Phase 1-5 existing API regression (frozen contracts).
6. POST /api/alert/distress emergency workflow.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app import incident_store, safety_store, track_a_bridge
from main import app

client = TestClient(app)

# Sample OSRM mock response for tests
MOCK_OSRM_RESPONSE = {
    "code": "Ok",
    "routes": [
        {
            "geometry": {
                "coordinates": [
                    [77.2090, 28.6139],
                    [77.2110, 28.6145],
                    [77.2130, 28.6150],
                ],
                "type": "LineString",
            },
            "legs": [],
            "weight_name": "routability",
            "weight": 400.0,
            "duration": 360.0,
            "distance": 620.0,
        }
    ],
    "waypoints": [],
}


def test_1_track_a_import():
    """Test 1 — Backend can import and call real score_all_routes() from Track A."""
    assert track_a_bridge.is_track_a_available() is True

    dummy_osrm = {
        "routes": [
            {
                "geometry": {
                    "coordinates": [[77.2090, 28.6139], [77.2130, 28.6150]],
                },
                "distance": 500.0,
                "duration": 300.0,
            }
        ]
    }
    results = track_a_bridge.score_routes(
        osrm_response=dummy_osrm,
        reports=[],
        persona="default",
        hour=18,
    )
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["id"] == "route_a"
    assert "score" in results[0]
    assert "breakdown" in results[0]
    assert "safe_islands" in results[0]


def test_2_incident_storage_sqlite(tmp_path):
    """Test 2 — SQLite incident store correctly persists and shapes reports."""
    test_db = str(tmp_path / "test_incidents.db")
    incident_store.init_db(test_db)

    # Insert incident
    record = incident_store.create_incident(
        lat=28.6139,
        lon=77.2090,
        severity=0.8,
        description="Dark alley near gate",
        db_path=test_db,
    )
    assert record["id"].startswith("incident_")
    assert record["lat"] == 28.6139
    assert record["lon"] == 77.2090
    assert record["severity"] == 0.8
    assert isinstance(record["timestamp"], float)

    # Query for Track A scoring
    reports = incident_store.get_reports_for_scoring(test_db)
    assert len(reports) == 1
    rep = reports[0]
    assert set(rep.keys()) == {"lat", "lon", "timestamp", "severity"}
    assert rep["lat"] == 28.6139
    assert rep["lon"] == 77.2090
    assert rep["severity"] == 0.8

    # Test via API
    resp = client.post(
        "/api/incidents",
        json={
            "lat": 28.6200,
            "lon": 77.2100,
            "severity": 0.6,
            "description": "API test incident",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "received"
    assert "id" in data


def test_3_and_4_route_scoring_and_track_a_output():
    """Test 3 & 4 — POST /api/routes/score with mocked OSRM returns expected Track A output."""
    with patch("app.osrm_client.fetch_candidate_routes", return_value=MOCK_OSRM_RESPONSE):
        resp = client.post(
            "/api/routes/score",
            json={
                "start": {"lat": 28.6139, "lon": 77.2090},
                "end": {"lat": 28.6150, "lon": 77.2130},
                "persona": "solo_night",
                "hour": 22,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "routes" in body
        routes = body["routes"]
        assert len(routes) == 1

        route = routes[0]
        # Verify required Track A fields
        assert route["id"] == "route_a"
        assert isinstance(route["distance_km"], (int, float))
        assert isinstance(route["duration_min"], (int, float))
        assert isinstance(route["polyline"], list)
        assert len(route["polyline"]) >= 2
        assert isinstance(route["score"], (int, float))
        assert 0.0 <= route["score"] <= 100.0

        # Verify breakdown structure
        breakdown = route["breakdown"]
        for factor in ["lighting", "crowd", "business", "transit", "incident", "isolation"]:
            assert factor in breakdown
            assert "value" in breakdown[factor]
            assert "weight" in breakdown[factor]
            assert "contribution" in breakdown[factor]

        # Verify safe islands
        assert "safe_islands" in route
        assert isinstance(route["safe_islands"], list)


def test_5_existing_regression_phase_1_to_5():
    """Test 5 — Verify existing Phase 1-5 routes and contracts remain completely intact."""
    # Reset store for clean state
    safety_store.reset_store()

    # Meta health
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "ok"

    # Phase 1: GET /api/v1/routes (Frozen contract)
    r_resp = client.get("/api/v1/routes")
    assert r_resp.status_code == 200
    r_data = r_resp.json()
    assert "origin" in r_data
    assert "destination" in r_data
    assert "routes" in r_data
    first_r = r_data["routes"][0]
    assert "route_id" in first_r
    assert "name" in first_r
    assert "safety_score" in first_r
    assert "factors" in first_r
    assert "coordinates" in first_r
    assert hasattr(first_r["factors"], "__getitem__")

    # Phase 2: Trusted contact
    c_resp = client.post(
        "/api/v1/contacts",
        json={"name": "Alice Contact", "contact_method": "+91-9999988888"},
    )
    assert c_resp.status_code == 201
    contact_id = c_resp.json()["contact_id"]

    # Phase 2: Check-in start
    chk_resp = client.post(
        "/api/v1/checkins",
        json={
            "user_id": "u-test-1",
            "contact_id": contact_id,
            "duration_minutes": 25,
            "route_id": "route-001",
        },
    )
    assert chk_resp.status_code == 201
    checkin_id = chk_resp.json()["checkin_id"]

    # Phase 3: Location update / deviation
    loc_resp = client.post(
        f"/api/v1/checkins/{checkin_id}/location",
        json={"lat": 28.6315, "lng": 77.2167, "estimated_remaining_minutes": 15.0},
    )
    assert loc_resp.status_code == 200
    assert loc_resp.json()["is_deviated"] is False

    # Complete check-in
    comp_resp = client.post(f"/api/v1/checkins/{checkin_id}/complete")
    assert comp_resp.status_code == 200
    assert comp_resp.json()["status"] == "completed"

    # Phase 4: Post-walk feedback
    fb_resp = client.post(
        f"/api/v1/checkins/{checkin_id}/feedback",
        json={"rating": 5, "issue_tags": ["well_lit", "felt_safe"], "comment": "Great walk"},
    )
    assert fb_resp.status_code == 201

    # Phase 5: Demo reset
    reset_resp = client.post("/api/v1/demo/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "ok"


def test_6_distress_alert_endpoint():
    """Test 6 — POST /api/alert/distress triggers emergency alert to trusted contact."""
    # Reset store
    safety_store.reset_store()

    # Trigger distress with seeded contact
    resp = client.post(
        "/api/alert/distress",
        json={
            "user_id": "user-in-danger",
            "lat": 28.6145,
            "lon": 77.2110,
            "message": "Immediate danger! Please help.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alert_sent"
    assert "alert_id" in data

    # Verify alert exists in safety store
    saved_alert = safety_store.get_alert(data["alert_id"])
    assert saved_alert is not None
    assert saved_alert.alert_type == "distress"
    assert "Immediate danger" in saved_alert.message
    assert saved_alert.trusted_contact is not None


if __name__ == "__main__":
    print("Running integration tests...")
    test_1_track_a_import()
    print("[PASS] Test 1: Track A real import")
    test_2_incident_storage_sqlite(Path("."))
    print("[PASS] Test 2: SQLite incident storage")
    test_3_and_4_route_scoring_and_track_a_output()
    print("[PASS] Test 3 & 4: Route scoring & Track A output")
    test_5_existing_regression_phase_1_to_5()
    print("[PASS] Test 5: Existing Phase 1-5 regression")
    test_6_distress_alert_endpoint()
    print("[PASS] Test 6: Distress alert")
    print("\n==========================================")
    print("ALL 6/6 INTEGRATION TESTS PASSED (0 FAILED)")
    print("==========================================")
