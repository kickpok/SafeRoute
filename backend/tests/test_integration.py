"""
SafeRoute Backend – Integration & Regression Test Suite.

Verifies:
1. Track A scoring engine direct import and execution.
2. SQLite incident persistence and report extraction.
3. POST /api/routes/score end-to-end integration & response metadata.
4. Track A response schema compliance (id, polyline, score, breakdown, safe_islands).
5. Phase 1-5 existing API regression (frozen contracts).
6. POST /api/alert/distress emergency workflow.
7. Persona / time scoring and explanation (What-If Simulator).
8. POST /api/routes/compare multi-persona scoring comparison.
9. POST /api/safe-islands refuge lookup.
10. POST /api/escape escape mode route generation and distress alert integration.
11. POST /api/escape/location live GPS tracking & rerouting.
12. GET /api/v1/routes?persona=<persona> query parameter support and Track A scoring integration.
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


def test_2_incident_storage_sqlite():
    """Test 2 — SQLite incident store correctly persists and shapes reports."""
    test_db = str(Path(f"test_incidents_{os.getpid()}.db"))
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
    assert record["description"] == "Dark alley near gate"

    # Query for scoring
    reports = incident_store.get_reports_for_scoring(db_path=test_db)
    assert len(reports) >= 1
    latest = reports[-1]
    assert "lat" in latest
    assert "lon" in latest
    assert "severity" in latest
    assert "timestamp" in latest

    # Clean up test db if accessible
    try:
        if os.path.exists(test_db):
            os.remove(test_db)
    except Exception:
        pass


@patch("app.osrm_client.fetch_candidate_routes")
def test_3_and_4_route_scoring_and_track_a_output(mock_osrm):
    """Test 3 & 4 — POST /api/routes/score end-to-end integration with mock OSRM."""
    mock_osrm.return_value = MOCK_OSRM_RESPONSE

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
    data = resp.json()

    assert "routes" in data
    assert len(data["routes"]) == 1
    assert data["persona_applied"] == "solo_night"
    assert data["hour_applied"] == 22

    first_route = data["routes"][0]
    assert first_route["id"] == "route_a"
    assert "distance_km" in first_route
    assert "duration_min" in first_route
    assert "polyline" in first_route
    assert "score" in first_route
    assert "breakdown" in first_route
    assert "safe_islands" in first_route

    # Validate Track A breakdown keys
    breakdown = first_route["breakdown"]
    for factor in ["lighting", "crowd", "business", "transit", "incident", "isolation"]:
        assert factor in breakdown
        assert "value" in breakdown[factor]
        assert "weight" in breakdown[factor]
        assert "contribution" in breakdown[factor]


def test_5_existing_regression_phase_1_to_5():
    """Test 5 — Verify Phase 1-5 endpoints remain functional with frozen schemas."""
    # Health check
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "ok"

    # Phase 1: List routes
    r_resp = client.get("/api/v1/routes")
    assert r_resp.status_code == 200
    routes = r_resp.json()["routes"]
    assert len(routes) >= 3
    first_r = routes[0]
    assert "route_id" in first_r
    assert "name" in first_r
    assert "safety_score" in first_r
    assert "factors" in first_r
    assert "coordinates" in first_r

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
    safety_store.reset_store()

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

    saved_alert = safety_store.get_alert(data["alert_id"])
    assert saved_alert is not None
    assert saved_alert.alert_type == "distress"
    assert "Immediate danger" in saved_alert.message


@patch("app.osrm_client.fetch_candidate_routes")
def test_7_what_if_persona_comparison(mock_osrm):
    """Test 7 — POST /api/routes/compare scores identical route under different personas."""
    mock_osrm.return_value = MOCK_OSRM_RESPONSE

    resp = client.post(
        "/api/routes/compare",
        json={
            "start": {"lat": 28.6139, "lon": 77.2090},
            "end": {"lat": 28.6150, "lon": 77.2130},
            "personas": ["default", "solo_night", "with_kids", "late_shift"],
            "hour": 23,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "routes_by_persona" in data
    assert "solo_night" in data["routes_by_persona"]
    assert "with_kids" in data["routes_by_persona"]
    assert "late_shift" in data["routes_by_persona"]
    assert data["hour_applied"] == 23
    assert len(data["comparison_summary"]) > 0


def test_8_route_explanation_endpoint():
    """Test 8 — POST /api/routes/explain translates breakdown into structured insights."""
    resp = client.post(
        "/api/routes/explain",
        json={
            "score": 82.5,
            "persona": "solo_night",
            "hour": 21,
            "breakdown": {
                "lighting": {"value": 0.9, "weight": 0.28, "contribution": 0.252},
                "crowd": {"value": 0.4, "weight": 0.22, "contribution": 0.088},
                "incident": {"value": 0.95, "weight": 0.22, "contribution": 0.209},
                "isolation": {"value": 0.8, "weight": 0.10, "contribution": 0.080},
                "business": {"value": 0.5, "weight": 0.10, "contribution": 0.050},
                "transit": {"value": 0.6, "weight": 0.08, "contribution": 0.048},
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 82.5
    assert "High Safety" in data["safety_tier"]
    assert data["persona_applied"] == "solo_night"
    assert len(data["key_strengths"]) > 0
    assert "explanation" in data


def test_9_safe_islands_lookup():
    """Test 9 — POST /api/safe-islands returns verified nearby refuges sorted by distance."""
    resp = client.post(
        "/api/safe-islands",
        json={"lat": 28.6315, "lon": 77.2167, "radius_meters": 2000},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    assert len(data["safe_islands"]) > 0

    first_island = data["safe_islands"][0]
    assert "name" in first_island
    assert "type" in first_island
    assert "lat" in first_island
    assert "lon" in first_island
    assert "distance_meters" in first_island
    for i in range(len(data["safe_islands"]) - 1):
        assert data["safe_islands"][i]["distance_meters"] <= data["safe_islands"][i + 1]["distance_meters"]


@patch("app.osrm_client.fetch_candidate_routes")
def test_10_escape_mode_activation_and_alert(mock_osrm):
    """Test 10 — POST /api/escape selects closest refuge, calculates OSRM escape route, triggers alert."""
    mock_osrm.return_value = MOCK_OSRM_RESPONSE
    safety_store.reset_store()

    resp = client.post(
        "/api/escape",
        json={
            "current_location": {"lat": 28.6310, "lon": 77.2160},
            "trigger_distress": True,
            "user_id": "user-escaping-1",
            "message": "Escape mode activated! Heading to refuge.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "escape_active"
    assert "refuge" in data
    assert "name" in data["refuge"]
    assert "route" in data
    assert data["route"]["distance_km"] > 0
    assert "polyline" in data["route"]

    # Verify distress alert was dispatched
    assert data["distress_alert"] is not None
    assert data["distress_alert"]["status"] == "alert_sent"
    assert "alert_id" in data["distress_alert"]


def test_11_escape_location_update():
    """Test 11 — POST /api/escape/location monitors distance to refuge and checks arrival."""
    resp = client.post(
        "/api/escape/location",
        json={
            "current_location": {"lat": 28.6315, "lon": 77.2167},
            "target_refuge": {"lat": 28.6315, "lon": 77.2167},
            "reroute": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["distance_to_refuge_meters"] <= 1.0
    assert data["reached_refuge"] is True


def test_12_get_routes_persona_query_param():
    """Test 12 — GET /api/v1/routes?persona=<persona> passes persona to Track A and validates invalid persona."""
    # 1. Default (omitted)
    resp_default = client.get("/api/v1/routes")
    assert resp_default.status_code == 200
    routes_default = resp_default.json()["routes"]
    assert len(routes_default) >= 3

    # 2. Solo night persona
    resp_solo = client.get("/api/v1/routes?persona=solo_night")
    assert resp_solo.status_code == 200
    routes_solo = resp_solo.json()["routes"]
    assert len(routes_solo) == len(routes_default)
    # Verify Track A weighting produced a calculated safety score
    assert isinstance(routes_solo[0]["safety_score"], float)
    assert 0.0 <= routes_solo[0]["safety_score"] <= 1.0

    # 3. With kids persona
    resp_kids = client.get("/api/v1/routes?persona=with_kids")
    assert resp_kids.status_code == 200
    routes_kids = resp_kids.json()["routes"]
    assert len(routes_kids) == len(routes_default)

    # 4. Late shift persona
    resp_shift = client.get("/api/v1/routes?persona=late_shift")
    assert resp_shift.status_code == 200
    routes_shift = resp_shift.json()["routes"]
    assert len(routes_shift) == len(routes_default)

    # 5. Invalid persona rejected with 422
    resp_invalid = client.get("/api/v1/routes?persona=invalid_persona_xyz")
    assert resp_invalid.status_code == 422


if __name__ == "__main__":
    print("Running integration tests...")
    test_1_track_a_import()
    print("[PASS] Test 1: Track A real import")
    test_2_incident_storage_sqlite()
    print("[PASS] Test 2: SQLite incident storage")
    test_3_and_4_route_scoring_and_track_a_output()
    print("[PASS] Test 3 & 4: Route scoring & Track A output")
    test_5_existing_regression_phase_1_to_5()
    print("[PASS] Test 5: Existing Phase 1-5 regression")
    test_6_distress_alert_endpoint()
    print("[PASS] Test 6: Distress alert")
    test_7_what_if_persona_comparison()
    print("[PASS] Test 7: What-If persona comparison")
    test_8_route_explanation_endpoint()
    print("[PASS] Test 8: Route explanation structured analysis")
    test_9_safe_islands_lookup()
    print("[PASS] Test 9: Safe islands lookup")
    test_10_escape_mode_activation_and_alert()
    print("[PASS] Test 10: Escape Mode activation & distress dispatch")
    test_11_escape_location_update()
    print("[PASS] Test 11: Escape Mode live GPS tracking")
    test_12_get_routes_persona_query_param()
    print("[PASS] Test 12: GET /api/v1/routes?persona=<persona> Track A integration")
    print("\n==========================================")
    print("ALL 12/12 INTEGRATION TESTS PASSED (0 FAILED)")
    print("==========================================")
