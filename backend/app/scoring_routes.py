"""
SafeRoute Backend – Track A Integration, Safety Assistant & Escape Mode Endpoints.

Implements the Track A / Track C integration and Safety Assistant interface:
  - POST /api/routes/score     (OSRM candidate routes -> SQLite incidents -> Track A score_all_routes)
  - POST /api/routes/compare   (Compare same route across multiple personas / What-If analysis)
  - POST /api/routes/explain   (Structured explanation of safety score & factor breakdown)
  - POST /api/safe-islands     (Find verified nearby refuge points: police, pharmacies, 24hr shops)
  - POST /api/escape           (Escape Mode: find closest refuge, OSRM escape route, optional distress alert)
  - POST /api/escape/location  (Live GPS update / deviation check during active Escape Mode)
  - POST /api/incidents        (Crowdsourced incident reports stored in SQLite)
  - POST /api/alert/distress   (Distress / panic button alerts to trusted contacts)

Preserves existing Phase 1-5 endpoints under /api/v1/* without modification.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app import assistant_service
from app import geo_utils
from app import incident_store
from app import notification_service
from app import osrm_client
from app import safety_store
from app import track_a_bridge
from app.safety_schemas import Alert, AlertStatus, AlertType, TrustedContact

logger = logging.getLogger("saferoute.scoring_routes")

router = APIRouter(prefix="/api", tags=["scoring_assistant_and_escape"])


# ══════════════════════════════════════════════════════════════════════
# Common Schemas
# ══════════════════════════════════════════════════════════════════════

class CoordinatePoint(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude", examples=[28.6139])
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude", examples=[77.2090])


PersonaType = Literal["default", "solo_night", "with_kids", "late_shift"]


# ══════════════════════════════════════════════════════════════════════
# 1. Dynamic Persona / Route Scoring & What-If
# ══════════════════════════════════════════════════════════════════════

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
    persona_applied: Optional[str] = Field("default", description="Persona profile applied during scoring")
    hour_applied: Optional[int] = Field(None, description="Hour of day applied (0-23)")
    origin: Optional[CoordinatePoint] = Field(None, description="Start coordinates")
    destination: Optional[CoordinatePoint] = Field(None, description="End coordinates")


@router.post(
    "/routes/score",
    response_model=ScoreRoutesResponse,
    summary="Score candidate routes using Track A engine",
    description=(
        "1. Requests candidate routes from OSRM.\n"
        "2. Loads recent incident reports from SQLite.\n"
        "3. Calls Track A composite scoring engine `score_all_routes()`.\n"
        "4. Returns scored routes with detailed factor breakdown, persona, and time metadata."
    ),
    responses={
        200: {"description": "Candidate routes scored successfully"},
        400: {"description": "Bad coordinates or routing failure"},
        500: {"description": "Scoring engine failure"},
    },
)
async def score_candidate_routes(payload: ScoreRoutesRequest) -> ScoreRoutesResponse:
    applied_hour = payload.hour if payload.hour is not None else int(time.strftime("%H"))
    applied_persona = payload.persona or "default"

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
            persona=applied_persona,
            hour=applied_hour,
        )
    except Exception as exc:
        logger.error("Track A scoring engine failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Track A scoring engine error: {exc}",
        )

    return ScoreRoutesResponse(
        routes=scored_routes,
        persona_applied=applied_persona,
        hour_applied=applied_hour,
        origin=payload.start,
        destination=payload.end,
    )


# ══════════════════════════════════════════════════════════════════════
# 2. Safety Assistant: What-If Comparison & Explanations
# ══════════════════════════════════════════════════════════════════════

class RouteCompareRequest(BaseModel):
    start: CoordinatePoint = Field(..., description="Origin coordinate point")
    end: CoordinatePoint = Field(..., description="Destination coordinate point")
    personas: Optional[List[PersonaType]] = Field(
        ["default", "solo_night", "with_kids", "late_shift"],
        description="List of persona profiles to compare",
    )
    hour: Optional[int] = Field(None, ge=0, le=23, description="Hour of day (0-23)")


class RouteCompareResponse(BaseModel):
    origin: CoordinatePoint
    destination: CoordinatePoint
    hour_applied: int
    routes_by_persona: Dict[str, List[Dict[str, Any]]] = Field(
        ...,
        description="Scored routes grouped by persona profile",
    )
    comparison_summary: str = Field(..., description="Structured summary comparing persona score differences")


@router.post(
    "/routes/compare",
    response_model=RouteCompareResponse,
    summary="Compare route safety across multiple personas (What-If Simulator)",
    description=(
        "Evaluates the same physical candidate routes across different persona weight profiles "
        "(e.g. Solo Night vs. With Kids vs. Late Shift) to expose trade-offs."
    ),
)
async def compare_routes_what_if(payload: RouteCompareRequest) -> RouteCompareResponse:
    try:
        result = assistant_service.compare_personas_for_route(
            start_lat=payload.start.lat,
            start_lon=payload.start.lon,
            end_lat=payload.end.lat,
            end_lon=payload.end.lon,
            personas=payload.personas,
            hour=payload.hour,
        )
        return RouteCompareResponse(
            origin=payload.start,
            destination=payload.end,
            hour_applied=result["hour_applied"],
            routes_by_persona=result["routes_by_persona"],
            comparison_summary=result["comparison_summary"],
        )
    except Exception as exc:
        logger.error("What-If comparison failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route comparison failed: {exc}",
        )


class RouteExplainRequest(BaseModel):
    score: Optional[float] = Field(None, description="Composite safety score (0-100)")
    breakdown: Optional[Dict[str, Any]] = Field(None, description="Track A factor breakdown dictionary")
    persona: Optional[PersonaType] = Field("default", description="Persona profile")
    hour: Optional[int] = Field(None, ge=0, le=23, description="Hour of day")


class RouteExplainResponse(BaseModel):
    score: float
    safety_tier: str
    persona_applied: str
    hour_applied: int
    key_strengths: List[str]
    key_risks: List[str]
    factor_analysis: Dict[str, Any]
    explanation: str


@router.post(
    "/routes/explain",
    response_model=RouteExplainResponse,
    summary="Explain route safety breakdown in structured form",
    description="Translates Track A score and factor contributions into human/assistant-readable safety insights.",
)
async def explain_route(payload: RouteExplainRequest) -> RouteExplainResponse:
    score = payload.score if payload.score is not None else 75.0
    breakdown = payload.breakdown or {
        "lighting": {"value": 0.8, "weight": 0.28, "contribution": 0.224},
        "crowd": {"value": 0.6, "weight": 0.22, "contribution": 0.132},
        "business": {"value": 0.5, "weight": 0.10, "contribution": 0.05},
        "transit": {"value": 0.7, "weight": 0.08, "contribution": 0.056},
        "incident": {"value": 0.9, "weight": 0.22, "contribution": 0.198},
        "isolation": {"value": 0.75, "weight": 0.10, "contribution": 0.075},
    }
    result = assistant_service.explain_route_safety(
        score=score,
        breakdown=breakdown,
        persona=payload.persona or "default",
        hour=payload.hour,
    )
    return RouteExplainResponse(**result)


# ══════════════════════════════════════════════════════════════════════
# 3. Safe Islands / Refuges
# ══════════════════════════════════════════════════════════════════════

class SafeIsland(BaseModel):
    name: str = Field(..., description="Refuge name or POI label")
    type: str = Field(..., description="Refuge category (police, pharmacy, hospital, shop)")
    lat: float = Field(..., description="Refuge latitude")
    lon: float = Field(..., description="Refuge longitude")
    distance_meters: float = Field(..., description="Distance in meters from query location")
    address: Optional[str] = Field(None, description="Address or landmark")


class SafeIslandsRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Search center latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Search center longitude")
    radius_meters: Optional[float] = Field(1500.0, ge=50.0, le=10000.0, description="Search radius in meters")


class SafeIslandsResponse(BaseModel):
    safe_islands: List[SafeIsland] = Field(..., description="Verified safe islands sorted by proximity")
    count: int = Field(..., description="Total safe islands found")
    center: CoordinatePoint = Field(..., description="Query center point")


@router.post(
    "/safe-islands",
    response_model=SafeIslandsResponse,
    summary="Find verified nearby safe islands / refuges",
    description="Queries OpenStreetMap / Overpass for verified police posts, 24hr pharmacies, hospitals, and open shops.",
)
async def get_nearby_safe_islands(payload: SafeIslandsRequest) -> SafeIslandsResponse:
    radius = payload.radius_meters or 1500.0
    islands_data = assistant_service.fetch_nearby_safe_islands(
        lat=payload.lat,
        lon=payload.lon,
        radius_meters=radius,
    )
    islands = [SafeIsland(**item) for item in islands_data]
    return SafeIslandsResponse(
        safe_islands=islands,
        count=len(islands),
        center=CoordinatePoint(lat=payload.lat, lon=payload.lon),
    )


# ══════════════════════════════════════════════════════════════════════
# 4. Escape Mode
# ══════════════════════════════════════════════════════════════════════

class EscapeRequest(BaseModel):
    current_location: CoordinatePoint = Field(..., description="User's current GPS location")
    trigger_distress: Optional[bool] = Field(True, description="Whether to automatically dispatch distress alert")
    user_id: Optional[str] = Field(None, description="User identifier")
    checkin_id: Optional[str] = Field(None, description="Active check-in ID if session exists")
    message: Optional[str] = Field(None, max_length=300, description="Optional custom emergency message")


class EscapeRouteInfo(BaseModel):
    distance_km: float = Field(..., description="Distance to refuge in kilometers")
    duration_min: float = Field(..., description="Estimated walking time in minutes")
    polyline: List[List[float]] = Field(..., description="Route coordinates [[lon, lat], ...]")


class EscapeResponse(BaseModel):
    status: str = Field("escape_active", description="Escape operation status")
    refuge: SafeIsland = Field(..., description="Selected nearest safe refuge")
    route: EscapeRouteInfo = Field(..., description="Fastest route to refuge")
    distress_alert: Optional[Dict[str, Any]] = Field(None, description="Distress alert details if triggered")
    nearby_refuges: List[SafeIsland] = Field(default_factory=list, description="Other safe havens nearby")


@router.post(
    "/escape",
    response_model=EscapeResponse,
    summary="Activate Escape Mode (navigate to nearest safe refuge + optional distress alert)",
    description=(
        "1. Identifies the nearest verified safe island (police, pharmacy, hospital, 24hr shop).\n"
        "2. Generates the fastest pedestrian route from current GPS location to refuge via OSRM.\n"
        "3. If trigger_distress is True, dispatches an immediate emergency alert to the trusted contact.\n"
        "4. Returns route polyline, refuge details, and alternative safe points."
    ),
)
async def activate_escape_mode(payload: EscapeRequest) -> EscapeResponse:
    # 1. Generate escape plan (closest refuge + OSRM route)
    target_refuge_dict, route_dict, other_refuges_list = assistant_service.generate_escape_plan(
        current_lat=payload.current_location.lat,
        current_lon=payload.current_location.lon,
    )

    target_refuge = SafeIsland(**target_refuge_dict)
    other_refuges = [SafeIsland(**r) for r in other_refuges_list]
    escape_route = EscapeRouteInfo(**route_dict)

    # 2. Trigger distress alert if requested
    alert_info = None
    if payload.trigger_distress:
        emergency_msg = (
            payload.message
            or f"EMERGENCY ESCAPE MODE: User is routing to safe haven '{target_refuge.name}' ({target_refuge.type}) "
               f"located {target_refuge.distance_meters:.0f}m away at ({target_refuge.lat:.5f}, {target_refuge.lon:.5f})."
        )
        distress_payload = DistressRequest(
            user_id=payload.user_id,
            checkin_id=payload.checkin_id,
            lat=payload.current_location.lat,
            lon=payload.current_location.lon,
            message=emergency_msg,
        )
        distress_res = await trigger_distress_alert(distress_payload)
        alert_info = {
            "status": distress_res.status,
            "alert_id": distress_res.alert_id,
            "message": emergency_msg,
        }

    return EscapeResponse(
        status="escape_active",
        refuge=target_refuge,
        route=escape_route,
        distress_alert=alert_info,
        nearby_refuges=other_refuges,
    )


class EscapeLocationUpdate(BaseModel):
    current_location: CoordinatePoint = Field(..., description="User's updated GPS coordinate")
    target_refuge: CoordinatePoint = Field(..., description="Target refuge coordinate")
    checkin_id: Optional[str] = Field(None, description="Active check-in session ID if linked")
    reroute: Optional[bool] = Field(False, description="Force recalculating OSRM escape route")


class EscapeLocationResponse(BaseModel):
    distance_to_refuge_meters: float = Field(..., description="Remaining distance in meters to refuge")
    reached_refuge: bool = Field(..., description="Whether user is within 30 meters of refuge")
    route: Optional[EscapeRouteInfo] = Field(None, description="Updated OSRM route if rerouted")


@router.post(
    "/escape/location",
    response_model=EscapeLocationResponse,
    summary="Update live GPS location during Escape Mode",
    description="Monitors distance to refuge and provides dynamic rerouting when user deviates or requests new path.",
)
async def update_escape_location(payload: EscapeLocationUpdate) -> EscapeLocationResponse:
    dist = geo_utils.haversine_distance(
        payload.current_location.lat,
        payload.current_location.lon,
        payload.target_refuge.lat,
        payload.target_refuge.lon,
    )
    reached = dist <= 30.0

    updated_route = None
    if payload.reroute and not reached:
        try:
            osrm_resp = osrm_client.fetch_candidate_routes(
                start_lat=payload.current_location.lat,
                start_lon=payload.current_location.lon,
                end_lat=payload.target_refuge.lat,
                end_lon=payload.target_refuge.lon,
            )
            first_route = osrm_resp.get("routes", [])[0]
            updated_route = EscapeRouteInfo(
                distance_km=round(first_route.get("distance", dist) / 1000.0, 2),
                duration_min=round(first_route.get("duration", (dist / 80.0) * 60) / 60.0, 1),
                polyline=first_route.get("geometry", {}).get("coordinates", []),
            )
        except Exception as exc:
            logger.warning("Escape reroute OSRM failed: %s", exc)

    return EscapeLocationResponse(
        distance_to_refuge_meters=round(dist, 1),
        reached_refuge=reached,
        route=updated_route,
    )


# ══════════════════════════════════════════════════════════════════════
# 5. Incident Reporting
# ══════════════════════════════════════════════════════════════════════

class IncidentReportRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Incident latitude", examples=[28.6139])
    lon: float = Field(..., ge=-180.0, le=180.0, description="Incident longitude", examples=[77.2090])
    severity: float = Field(0.5, ge=0.0, le=1.0, description="Severity score 0.0 (minor) to 1.0 (severe)")
    description: Optional[str] = Field(None, max_length=500, description="Optional incident note")


class IncidentReportResponse(BaseModel):
    status: str = Field("received", description="Status code")
    id: str = Field(..., description="Generated incident identifier")


@router.post(
    "/incidents",
    response_model=IncidentReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an incident report",
    description="Records a crowdsourced safety incident in SQLite for Track A scoring integration.",
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


# ══════════════════════════════════════════════════════════════════════
# 6. Distress Alerts
# ══════════════════════════════════════════════════════════════════════

class DistressRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="User identifier", examples=["u1"])
    checkin_id: Optional[str] = Field(None, description="Active check-in session ID, if known", examples=["c1"])
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Current latitude")
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Current longitude")
    message: Optional[str] = Field(None, max_length=300, description="Optional distress note")


class DistressResponse(BaseModel):
    status: str = Field("alert_sent", description="Operation status")
    alert_id: str = Field(..., description="Dispatched alert identifier")


@router.post(
    "/alert/distress",
    response_model=DistressResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger immediate distress / panic alert",
    description="Dispatches an emergency distress alert to the user's trusted contact via notification provider.",
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
