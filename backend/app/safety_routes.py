"""
SafeRoute Backend – Phase 2 Safety API routes.

Endpoints for:
  - Trusted contact management
  - Check-in lifecycle
  - Alert creation and retrieval
  - Overdue detection

All business logic is delegated to app/checkin_service.py.
Phase 1 routes (app/routes.py) are NOT modified.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import checkin_service as svc
from app.safety_schemas import (
    Alert,
    AlertListResponse,
    CheckIn,
    CheckInCreate,
    CheckInListResponse,
    CheckInStatusResponse,
    DemoResetResponse,
    ErrorResponse,
    Feedback,
    FeedbackCreate,
    FeedbackListResponse,
    LocationUpdate,
    LocationUpdateResponse,
    ManualCheckInResponse,
    PrivacySessionResponse,
    RouteFeedbackSummary,
    TrustedContact,
    TrustedContactCreate,
    TrustedContactListResponse,
)

router = APIRouter(prefix="/api/v1", tags=["safety"])


# ════════════════════════════════════════════════════════════════════
# TRUSTED CONTACTS
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/contacts",
    response_model=TrustedContact,
    status_code=201,
    summary="Register a trusted contact",
    description=(
        "Register a trusted contact who will receive alerts. "
        "`contact_method` is a free-form destination string "
        "(phone number, email, etc.) interpreted by the notification provider."
    ),
    responses={
        201: {"description": "Contact created"},
        422: {"description": "Validation error", "model": ErrorResponse},
    },
)
async def create_contact(payload: TrustedContactCreate) -> TrustedContact:
    return svc.create_contact(payload)


@router.get(
    "/contacts",
    response_model=TrustedContactListResponse,
    summary="List all trusted contacts",
)
async def list_contacts() -> TrustedContactListResponse:
    items = svc.list_contacts()
    return TrustedContactListResponse(items=items, count=len(items))


@router.get(
    "/contacts/{contact_id}",
    response_model=TrustedContact,
    summary="Get a trusted contact by ID",
    responses={
        200: {"description": "Contact found"},
        404: {"description": "Not found", "model": ErrorResponse},
    },
)
async def get_contact(contact_id: str) -> TrustedContact:
    contact = svc.get_contact(contact_id)
    if contact is None:
        raise HTTPException(status_code=404,
                            detail=f"Contact '{contact_id}' not found")
    return contact


@router.delete(
    "/contacts/{contact_id}",
    summary="Delete a trusted contact",
    responses={
        200: {"description": "Contact deleted"},
        404: {"description": "Not found", "model": ErrorResponse},
    },
)
async def delete_contact(contact_id: str):
    success = svc.delete_contact(contact_id)
    if not success:
        raise HTTPException(status_code=404,
                            detail=f"Contact '{contact_id}' not found")
    return {"status": "deleted", "contact_id": contact_id}


# ════════════════════════════════════════════════════════════════════
# CHECK-INS
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/checkins",
    response_model=CheckIn,
    status_code=201,
    summary="Start a check-in session",
    description=(
        "Create a new ACTIVE check-in session for a user. "
        "The trusted contact identified by `contact_id` will be alerted "
        "if the session becomes overdue."
    ),
    responses={
        201: {"description": "Check-in created"},
        404: {"description": "Trusted contact not found", "model": ErrorResponse},
        422: {"description": "Validation error", "model": ErrorResponse},
    },
)
async def create_checkin(payload: CheckInCreate) -> CheckIn:
    try:
        return svc.create_checkin(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/checkins",
    response_model=CheckInListResponse,
    summary="List all check-in sessions",
)
async def list_checkins() -> CheckInListResponse:
    items = svc.list_checkins()
    return CheckInListResponse(items=items, count=len(items))


@router.get(
    "/checkins/{checkin_id}",
    response_model=CheckIn,
    summary="Get a check-in session by ID",
    responses={
        200: {"description": "Check-in found"},
        404: {"description": "Not found", "model": ErrorResponse},
    },
)
async def get_checkin(checkin_id: str) -> CheckIn:
    checkin = svc.get_checkin(checkin_id)
    if checkin is None:
        raise HTTPException(status_code=404,
                            detail=f"Check-in '{checkin_id}' not found")
    return checkin


@router.post(
    "/checkins/{checkin_id}/complete",
    response_model=CheckIn,
    summary="Mark a check-in as safely completed",
    description="Transitions an ACTIVE or OVERDUE check-in to COMPLETED.",
    responses={
        200: {"description": "Check-in completed"},
        404: {"description": "Not found", "model": ErrorResponse},
        409: {"description": "Cannot complete (already terminal)", "model": ErrorResponse},
    },
)
async def complete_checkin(checkin_id: str) -> CheckIn:
    try:
        return svc.complete_checkin(checkin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/checkins/{checkin_id}/im-safe",
    response_model=ManualCheckInResponse,
    summary="Perform manual 'I'm Safe' check-in",
    description=(
        "Records that the user is safe during an active trip. "
        "Advances next_checkin_due_at by interval_minutes, increments checkin_count, "
        "and clears overdue state."
    ),
    responses={
        200: {"description": "Manual check-in recorded"},
        404: {"description": "Not found", "model": ErrorResponse},
        409: {"description": "Session already completed or cancelled", "model": ErrorResponse},
    },
)
@router.post(
    "/checkins/{checkin_id}/safe-ping",
    response_model=ManualCheckInResponse,
    include_in_schema=False,
)
async def manual_im_safe_checkin(checkin_id: str) -> ManualCheckInResponse:
    try:
        return svc.record_manual_checkin(checkin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/checkins/{checkin_id}/cancel",
    response_model=CheckIn,
    summary="Cancel a check-in session",
    description="Transitions an ACTIVE or OVERDUE check-in to CANCELLED.",
    responses={
        200: {"description": "Check-in cancelled"},
        404: {"description": "Not found", "model": ErrorResponse},
        409: {"description": "Cannot cancel (already terminal)", "model": ErrorResponse},
    },
)
async def cancel_checkin(checkin_id: str) -> CheckIn:
    try:
        return svc.cancel_checkin(checkin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/checkins/{checkin_id}/status",
    response_model=CheckInStatusResponse,
    summary="Check overdue status of a check-in",
    description=(
        "Evaluates whether the check-in has passed its expected completion "
        "time. If overdue, the status is transitioned automatically. "
        "Track D should call this before deciding whether to trigger an alert."
    ),
    responses={
        200: {"description": "Status evaluated"},
        404: {"description": "Not found", "model": ErrorResponse},
    },
)
async def get_checkin_status(checkin_id: str) -> CheckInStatusResponse:
    try:
        return svc.get_checkin_status(checkin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/checkins/overdue-scan",
    response_model=CheckInListResponse,
    summary="Scan all active check-ins for overdue status",
    description=(
        "Iterates all ACTIVE check-ins and transitions those past their "
        "expected time to OVERDUE. Returns the list of newly overdue sessions. "
        "Intended for periodic polling or manual triggering by Track D / demo."
    ),
)
async def overdue_scan() -> CheckInListResponse:
    items = svc.scan_overdue_checkins()
    return CheckInListResponse(items=items, count=len(items))


@router.post(
    "/checkins/{checkin_id}/location",
    response_model=LocationUpdateResponse,
    summary="Report live location & progress update for a safety check-in",
    description=(
        "Ingests user GPS coordinates and optional remaining ETA. "
        "Evaluates whether the user has deviated beyond tolerance from the assigned route polyline "
        "or is significantly delayed past expected ETA. Automatically triggers a safety alert to "
        "the trusted contact if an alert condition is detected and not already active (with deduplication)."
    ),
    responses={
        200: {"description": "Location processed and evaluated"},
        404: {"description": "Check-in not found", "model": ErrorResponse},
        409: {"description": "Check-in is not active", "model": ErrorResponse},
        422: {"description": "Validation error", "model": ErrorResponse},
    },
)
async def update_location(checkin_id: str, payload: LocationUpdate) -> LocationUpdateResponse:
    try:
        return svc.process_location_update(checkin_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))



# ════════════════════════════════════════════════════════════════════
# ALERTS
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/checkins/{checkin_id}/alert",
    response_model=Alert,
    status_code=201,
    summary="Trigger a check-in overdue alert",
    description=(
        "Creates a CHECKIN_OVERDUE alert and dispatches a (mock) notification "
        "to the trusted contact. Only valid when the check-in is OVERDUE. "
        "Call GET /checkins/{checkin_id}/status first to evaluate overdue state."
    ),
    responses={
        201: {"description": "Alert created and notification dispatched"},
        404: {"description": "Check-in or contact not found", "model": ErrorResponse},
        409: {"description": "Check-in is not overdue", "model": ErrorResponse},
    },
)
async def trigger_alert(checkin_id: str) -> Alert:
    try:
        return svc.create_overdue_alert(checkin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/alerts",
    response_model=AlertListResponse,
    summary="List all alerts",
)
async def list_alerts() -> AlertListResponse:
    items = svc.list_alerts()
    return AlertListResponse(items=items, count=len(items))


@router.get(
    "/alerts/{alert_id}",
    response_model=Alert,
    summary="Get an alert by ID",
    responses={
        200: {"description": "Alert found"},
        404: {"description": "Not found", "model": ErrorResponse},
    },
)
async def get_alert(alert_id: str) -> Alert:
    alert = svc.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404,
                            detail=f"Alert '{alert_id}' not found")
    return alert


@router.get(
    "/checkins/{checkin_id}/alerts",
    response_model=AlertListResponse,
    summary="List all alerts for a specific check-in",
    responses={
        200: {"description": "Alerts retrieved"},
        404: {"description": "Check-in not found", "model": ErrorResponse},
    },
)
async def get_alerts_for_checkin(checkin_id: str) -> AlertListResponse:
    if svc.get_checkin(checkin_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"Check-in '{checkin_id}' not found")
    items = svc.alerts_for_checkin(checkin_id)
    return AlertListResponse(items=items, count=len(items))


# ════════════════════════════════════════════════════════════════════
# POST-WALK FEEDBACK (Phase 4 Scoring Loop)
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/checkins/{checkin_id}/feedback",
    response_model=Feedback,
    status_code=201,
    summary="Submit 1-tap post-walk safety feedback",
    description=(
        "Submits post-walk experience/safety rating (1-5), optional tags, and comments. "
        "Only valid for completed check-in sessions. Associated with the route for scoring pipeline."
    ),
    responses={
        201: {"description": "Feedback submitted successfully"},
        404: {"description": "Check-in not found", "model": ErrorResponse},
        409: {"description": "Check-in not completed or feedback already submitted", "model": ErrorResponse},
        422: {"description": "Validation error", "model": ErrorResponse},
    },
)
async def submit_feedback(checkin_id: str, payload: FeedbackCreate) -> Feedback:
    try:
        return svc.submit_feedback(checkin_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/checkins/{checkin_id}/feedback",
    response_model=Feedback,
    summary="Get feedback for a check-in session",
    responses={
        200: {"description": "Feedback found"},
        404: {"description": "Feedback or check-in not found", "model": ErrorResponse},
    },
)
async def get_feedback(checkin_id: str) -> Feedback:
    feedback = svc.get_feedback_by_checkin(checkin_id)
    if feedback is None:
        raise HTTPException(status_code=404, detail=f"Feedback for check-in '{checkin_id}' not found")
    return feedback


@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    summary="List all recorded post-walk feedback entries",
)
async def list_all_feedbacks() -> FeedbackListResponse:
    items = svc.list_all_feedbacks()
    return FeedbackListResponse(items=items, count=len(items))


@router.get(
    "/routes/{route_id}/feedback",
    response_model=RouteFeedbackSummary,
    summary="Get aggregated route feedback summary for Track A scoring pipeline",
    description=(
        "Returns aggregated rating metrics, issue tag frequencies, and recent feedback entries "
        "for a route. Designed for direct consumption by Track A ML scoring pipeline."
    ),
)
async def get_route_feedback(route_id: str) -> RouteFeedbackSummary:
    return svc.get_route_feedback_summary(route_id)


# ════════════════════════════════════════════════════════════════════
# PRIVACY & LOCATION SESSION LIFECYCLE (Phase 4)
# ════════════════════════════════════════════════════════════════════

@router.get(
    "/checkins/{checkin_id}/privacy",
    response_model=PrivacySessionResponse,
    summary="Check privacy & location-sharing lifecycle state for a session",
    description=(
        "Confirms whether live location sharing is currently active (only in transit) "
        "or has ceased upon arrival/cancellation."
    ),
    responses={
        200: {"description": "Privacy status returned"},
        404: {"description": "Check-in not found", "model": ErrorResponse},
    },
)
async def get_privacy_status(checkin_id: str) -> PrivacySessionResponse:
    try:
        return svc.get_privacy_session_status(checkin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ════════════════════════════════════════════════════════════════════
# DEMO MANAGEMENT & HARDENING (Phase 5)
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/demo/reset",
    response_model=DemoResetResponse,
    summary="Reset and re-seed clean demo state",
    description=(
        "Clears all dynamic session data, alerts, and feedback entries, and "
        "re-initializes default demo trusted contacts and candidate route cache. "
        "Use before live presentations to guarantee a clean, deterministic state."
    ),
)
async def reset_demo() -> DemoResetResponse:
    return svc.reset_demo_state()


