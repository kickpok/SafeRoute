"""
SafeRoute Backend – Track A Integration Endpoints.

Implements the Track A / Track C integration API:
  - POST /api/routes/score  (OSRM candidate routes -> SQLite incidents -> Track A score_all_routes)
  - POST /api/incidents     (Crowdsourced incident reports stored in SQLite)
  - POST /api/alert/distress (Distress / panic button alerts)

Preserves existing Phase 1-5 endpoints under /api/v1/* without modification.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app import incident_store
from app import notification_service
from app import osrm_client
from app import safety_store
from app import track_a_bridge
from app.safety_schemas import Alert, AlertStatus, AlertType, TrustedContact

logger = logging.getLogger("saferoute.scoring_routes")

router = APIRouter(prefix="/api", tags=["scoring_and_incidents"])


# ── Schemas for Route Scoring ──────────────────────────────────────────

class CoordinatePoint(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude", examples=[28.6139])
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude", examples=[77.2090])


PersonaType = Literal["default", "solo_night", "with_kids", "late_shift"]


class ScoreRoutesRequest(BaseModel):
    start: CoordinatePoint = Field(..., description="Origin coordinate point")
    end: CoordinatePoint = Field(..., description="Destination coordinate point")
    persona: Optional[PersonaType] = Field("default", description="Safety persona profile")
    hour: Optional[int] = Field(None, ge=0, le=23, description="Hour of day (0-23, defaults to current time)")


class ScoreRoutesResponse(BaseModel):
    routes: List[Dict[str, Any]] = Field(
        ...,
        description="Candidate routes scored by Track A composite engine",
    )


# ── Schemas for Incident Reporting ────────────────────────────────────

class IncidentReportRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Incident latitude", examples=[28.6139])
    lon: float = Field(..., ge=-180.0, le=180.0, description="Incident longitude", examples=[77.2090])
    severity: float = Field(0.5, ge=0.0, le=1.0, description="Severity score 0.0 (minor) to 1.0 (severe)")
    description: Optional[str] = Field(None, max_length=500, description="Optional incident note")


class IncidentReportResponse(BaseModel):
    status: str = Field("received", description="Status code")
    id: str = Field(..., description="Generated incident identifier")


# ── Schemas for Distress Alerts ───────────────────────────────────────

class DistressRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="User identifier", examples=["u1"])
    checkin_id: Optional[str] = Field(None, description="Active check-in session ID, if known", examples=["c1"])
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Current latitude")
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Current longitude")
    message: Optional[str] = Field(None, max_length=300, description="Optional distress note")


class DistressResponse(BaseModel):
    status: str = Field("alert_sent", description="Operation status")
    alert_id: str = Field(..., description="Dispatched alert identifier")


# ── Route Scoring Endpoint ───────────────────────────────────────────

@router.post(
    "/routes/score",
    response_model=ScoreRoutesResponse,
    summary="Score candidate routes using Track A engine",
    description=(
        "1. Requests candidate routes from OSRM.\n"
        "2. Loads recent incident reports from SQLite.\n"
        "3. Calls Track A composite scoring engine `score_all_routes()`.\n"
        "4. Returns scored routes with detailed factor breakdown."
    ),
    responses={
        200: {"description": "Candidate routes scored successfully"},
        400: {"description": "Bad coordinates or routing failure"},
        500: {"description": "Scoring engine failure"},
    },
)
async def score_candidate_routes(payload: ScoreRoutesRequest) -> ScoreRoutesResponse:
    # 1. Fetch candidate routes from OSRM
    try:
        osrm_resp = osrm_client.fetch_candidate_routes(
            start_lat=payload.start.lat,
            start_lon=payload.start.lon,
            end_lat=payload.end.lat,
            end_lon=payload.end.lon,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        logger.error("OSRM call failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OSRM routing engine unavailable: {exc}",
        )

    # 2. Retrieve crowdsourced incident reports from SQLite
    try:
        reports = incident_store.get_reports_for_scoring()
    except Exception as exc:
        logger.warning("Failed to retrieve incident reports from SQLite: %s", exc)
        reports = []

    # 3. Call Track A scoring engine
    try:
        scored_routes = track_a_bridge.score_routes(
            osrm_response=osrm_resp,
            reports=reports,
            persona=payload.persona or "default",
            hour=payload.hour,
        )
    except Exception as exc:
        logger.error("Track A scoring engine failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Track A scoring engine error: {exc}",
        )

    return ScoreRoutesResponse(routes=scored_routes)


# ── Incident Report Endpoint ──────────────────────────────────────────

@router.post(
    "/incidents",
    response_model=IncidentReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an incident report",
    description=(
        "Records a crowdsourced safety incident in SQLite. "
        "The server stamps the Unix timestamp automatically upon receipt."
    ),
    responses={
        201: {"description": "Incident report stored successfully"},
        422: {"description": "Validation error"},
    },
)
async def submit_incident(payload: IncidentReportRequest) -> IncidentReportResponse:
    try:
        record = incident_store.create_incident(
            lat=payload.lat,
            lon=payload.lon,
            severity=payload.severity,
            description=payload.description,
        )
        return IncidentReportResponse(status="received", id=record["id"])
    except Exception as exc:
        logger.error("Failed to store incident: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record incident report",
        )


# ── Distress Alert Endpoint ───────────────────────────────────────────

@router.post(
    "/alert/distress",
    response_model=DistressResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger immediate distress / panic alert",
    description=(
        "Dispatches an emergency distress alert to the user's trusted contact "
        "via the existing notification provider."
    ),
    responses={
        200: {"description": "Distress alert dispatched"},
        404: {"description": "No trusted contact available for dispatch"},
    },
)
async def trigger_distress_alert(payload: DistressRequest) -> DistressResponse:
    # 1. Resolve contact and check-in ID
    contact: Optional[TrustedContact] = None
    checkin_id = payload.checkin_id or f"distress_{uuid.uuid4().hex[:8]}"

    if payload.checkin_id:
        ci = safety_store.get_checkin(payload.checkin_id)
        if ci:
            contact = safety_store.get_contact(ci.contact_id)

    if not contact and payload.user_id:
        # Check active check-ins for this user
        for ci in safety_store.all_checkins():
            if ci.user_id == payload.user_id:
                contact = safety_store.get_contact(ci.contact_id)
                if not payload.checkin_id:
                    checkin_id = ci.checkin_id
                break

    if not contact:
        # Fall back to default seeded demo contact or first available contact
        contacts = safety_store.all_contacts()
        if contacts:
            contact = contacts[0]

    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No trusted contact registered to receive distress alert.",
        )

    # 2. Build and persist distress alert
    alert_id = f"alert_distress_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    coords_info = f" at ({payload.lat:.5f}, {payload.lon:.5f})" if payload.lat and payload.lon else ""
    user_info = f" from user '{payload.user_id}'" if payload.user_id else ""
    msg = payload.message or f"EMERGENCY: Distress signal triggered{user_info}{coords_info}. Immediate assistance requested!"

    alert = Alert(
        alert_id=alert_id,
        checkin_id=checkin_id,
        alert_type=AlertType.DISTRESS,
        alert_status=AlertStatus.PENDING,
        trusted_contact=contact,
        message=msg,
        created_at=now,
        sent_at=now,
    )

    # 3. Dispatch notification via existing provider
    delivery_status = notification_service.dispatch_notification(contact, alert)
    alert.alert_status = delivery_status
    safety_store.save_alert(alert)

    return DistressResponse(status="alert_sent", alert_id=alert.alert_id)
