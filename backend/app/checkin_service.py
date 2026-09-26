"""
SafeRoute Backend – Check-In & Alert business-logic service.

All safety feature logic lives here.  The API layer (safety_routes.py)
calls these functions — it never touches the store or notification
provider directly.

Responsibilities:
  - Trusted-contact CRUD
  - Check-in lifecycle management
  - Overdue detection
  - Alert creation and notification dispatch
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app import safety_store as store
from app.geo_utils import min_distance_to_route
from app.notification_service import dispatch_notification
from app.safety_schemas import (
    Alert,
    AlertStatus,
    AlertType,
    CheckIn,
    CheckInCreate,
    CheckInStatus,
    CheckInStatusResponse,
    DemoResetResponse,
    Feedback,
    FeedbackCreate,
    FeedbackListResponse,
    LocationUpdate,
    LocationUpdateResponse,
    PrivacySessionResponse,
    RouteFeedbackSummary,
    TrustedContact,
    TrustedContactCreate,
)
from app.services import get_route_by_id

# ── Phase 3 & 5 Engine Configuration ─────────────────────────────────
DEFAULT_DEVIATION_THRESHOLD_METERS: float = 200.0
DEFAULT_ETA_DELAY_THRESHOLD_MINUTES: float = 5.0


def _get_config() -> dict:
    try:
        cfg_file = Path(__file__).parent.parent / "config.json"
        if cfg_file.exists():
            with open(cfg_file) as f:
                return json.load(f)
    except Exception:
        pass
    return {}




# ── Helpers ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Trusted Contact service ──────────────────────────────────────────

def create_contact(payload: TrustedContactCreate) -> TrustedContact:
    """Register a new trusted contact and persist it."""
    contact = TrustedContact(
        contact_id=_new_id(),
        name=payload.name,
        contact_method=payload.contact_method,
        created_at=_now(),
    )
    store.save_contact(contact)
    return contact


def get_contact(contact_id: str) -> Optional[TrustedContact]:
    """Return a trusted contact or None."""
    return store.get_contact(contact_id)


def list_contacts() -> List[TrustedContact]:
    return store.all_contacts()


# ── Check-In service ─────────────────────────────────────────────────

def create_checkin(payload: CheckInCreate) -> CheckIn:
    """
    Start a new active check-in session.

    Raises ValueError if the referenced trusted contact does not exist.
    """
    if store.get_contact(payload.contact_id) is None:
        raise ValueError(f"Trusted contact '{payload.contact_id}' not found")

    now = _now()
    checkin = CheckIn(
        checkin_id=_new_id(),
        user_id=payload.user_id,
        contact_id=payload.contact_id,
        duration_minutes=payload.duration_minutes,
        route_id=payload.route_id,
        status=CheckInStatus.ACTIVE,
        started_at=now,
        expected_at=now + timedelta(minutes=payload.duration_minutes),
        completed_at=None,
    )
    store.save_checkin(checkin)
    return checkin


def get_checkin(checkin_id: str) -> Optional[CheckIn]:
    """Return a check-in session or None."""
    return store.get_checkin(checkin_id)


def list_checkins() -> List[CheckIn]:
    return store.all_checkins()


def complete_checkin(checkin_id: str) -> CheckIn:
    """
    Mark a check-in as safely completed.

    Raises:
        KeyError  – check-in not found
        ValueError – check-in is not in ACTIVE or OVERDUE state
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")
    if checkin.status not in (CheckInStatus.ACTIVE, CheckInStatus.OVERDUE):
        raise ValueError(
            f"Cannot complete check-in with status '{checkin.status.value}'. "
            "Only ACTIVE or OVERDUE check-ins can be completed."
        )
    # Pydantic models are immutable by default — use model_copy
    updated = checkin.model_copy(update={
        "status": CheckInStatus.COMPLETED,
        "completed_at": _now(),
    })
    store.save_checkin(updated)
    store.clear_active_deviation_alert_id(checkin_id)
    return updated


def cancel_checkin(checkin_id: str) -> CheckIn:
    """
    Cancel a check-in session.

    Raises:
        KeyError  – check-in not found
        ValueError – check-in is already in a terminal state
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")
    if checkin.status in (CheckInStatus.COMPLETED, CheckInStatus.CANCELLED):
        raise ValueError(
            f"Cannot cancel check-in with status '{checkin.status.value}'."
        )
    updated = checkin.model_copy(update={"status": CheckInStatus.CANCELLED})
    store.save_checkin(updated)
    store.clear_active_deviation_alert_id(checkin_id)
    return updated


def get_checkin_status(checkin_id: str) -> CheckInStatusResponse:
    """
    Evaluate whether a check-in is overdue.

    Automatically transitions ACTIVE → OVERDUE in the store when the
    expected time has passed.

    Raises:
        KeyError – check-in not found
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")

    is_overdue = False
    current_status = checkin.status

    if checkin.status == CheckInStatus.ACTIVE and _now() > checkin.expected_at:
        # Transition to OVERDUE
        updated = checkin.model_copy(update={"status": CheckInStatus.OVERDUE})
        store.save_checkin(updated)
        current_status = CheckInStatus.OVERDUE
        is_overdue = True

    messages = {
        CheckInStatus.ACTIVE:    "Check-in is active and within the expected time window.",
        CheckInStatus.OVERDUE:   "Check-in is OVERDUE — trusted contact should be alerted.",
        CheckInStatus.COMPLETED: "Check-in completed safely.",
        CheckInStatus.CANCELLED: "Check-in was cancelled.",
    }

    return CheckInStatusResponse(
        checkin_id=checkin_id,
        status=current_status,
        is_overdue=is_overdue,
        message=messages[current_status],
    )


# ── Alert service ─────────────────────────────────────────────────────

def create_overdue_alert(checkin_id: str) -> Alert:
    """
    Create a CHECKIN_OVERDUE alert, dispatch mock notification, persist.

    Raises:
        KeyError  – check-in or contact not found
        ValueError – check-in is not overdue
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")

    # Auto-evaluate overdue status
    status_resp = get_checkin_status(checkin_id)
    if not status_resp.is_overdue and checkin.status != CheckInStatus.OVERDUE:
        raise ValueError(
            f"Check-in '{checkin_id}' is not overdue (status: {checkin.status.value}). "
            "Alert not created."
        )

    contact = store.get_contact(checkin.contact_id)
    if contact is None:
        raise KeyError(f"Trusted contact '{checkin.contact_id}' not found")

    now = _now()
    message = (
        f"SAFETY ALERT: {checkin.user_id} has not checked in. "
        f"Expected by {checkin.expected_at.strftime('%H:%M UTC')}. "
        f"Please check on them."
    )

    alert = Alert(
        alert_id=_new_id(),
        checkin_id=checkin_id,
        alert_type=AlertType.CHECKIN_OVERDUE,
        alert_status=AlertStatus.PENDING,
        trusted_contact=contact,
        message=message,
        created_at=now,
        sent_at=None,
    )

    # Dispatch to the (mock) notification provider
    delivery_status = dispatch_notification(contact, alert)
    alert = alert.model_copy(update={
        "alert_status": delivery_status,
        "sent_at": _now() if delivery_status == AlertStatus.SENT else None,
    })

    store.save_alert(alert)
    return alert


def get_alert(alert_id: str) -> Optional[Alert]:
    return store.get_alert(alert_id)


def list_alerts() -> List[Alert]:
    return store.all_alerts()


def alerts_for_checkin(checkin_id: str) -> List[Alert]:
    return store.alerts_for_checkin(checkin_id)


# ── Batch overdue scan ────────────────────────────────────────────────
# Foundation for a future periodic scheduler (Phase 3+)

def scan_overdue_checkins() -> List[CheckIn]:
    """
    Evaluate all ACTIVE check-ins, transition overdue ones, return the list.

    Called by the /checkins/overdue-scan endpoint.
    Does NOT auto-fire alerts — that is an explicit action by the caller.
    """
    now = _now()
    newly_overdue: List[CheckIn] = []

    for checkin in store.all_checkins():
        if checkin.status == CheckInStatus.ACTIVE and now > checkin.expected_at:
            updated = checkin.model_copy(update={"status": CheckInStatus.OVERDUE})
            store.save_checkin(updated)
            newly_overdue.append(updated)

    return newly_overdue


# ── Phase 3: Location & Deviation Alert Engine ───────────────────────

def process_location_update(
    checkin_id: str,
    payload: LocationUpdate,
    deviation_threshold_meters: float = DEFAULT_DEVIATION_THRESHOLD_METERS,
    eta_delay_threshold_minutes: float = DEFAULT_ETA_DELAY_THRESHOLD_MINUTES,
) -> LocationUpdateResponse:
    """
    Process a location and progress update for an active safety check-in.

    1. Validates check-in existence and active lifecycle state.
    2. Calculates shortest perpendicular distance to the assigned route polyline.
    3. Evaluates if user position exceeds the deviation threshold.
    4. Evaluates if progress or elapsed time indicates an ETA delay.
    5. Deduplicates alerts: if an active deviation episode already has an alert,
       avoids firing repeated alerts on every subsequent location ping.
    6. Handles recovery: when user returns within threshold, clears the active
       deviation state cleanly.

    Raises:
        KeyError: If check-in is not found.
        ValueError: If check-in is not in an active or overdue state.
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")

    if checkin.status not in (CheckInStatus.ACTIVE, CheckInStatus.OVERDUE):
        raise ValueError(
            f"Cannot update location for check-in with status '{checkin.status.value}'. "
            "Session is not active."
        )

    now = payload.timestamp if payload.timestamp is not None else _now()
    # Ensure now is timezone-aware
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Evaluate Route Deviation
    is_deviated = False
    deviation_distance_meters: Optional[float] = None

    if checkin.route_id:
        route = get_route_by_id(checkin.route_id)
        if route and route.coordinates:
            dist = min_distance_to_route(payload.lat, payload.lng, route.coordinates)
            deviation_distance_meters = round(dist, 1)
            if dist > deviation_threshold_meters:
                is_deviated = True
        else:
            is_deviated = False
            deviation_distance_meters = None
    else:
        is_deviated = False
        deviation_distance_meters = None

    # 2. Evaluate ETA Delay
    is_eta_delayed = False
    if payload.estimated_remaining_minutes is not None:
        projected_arrival = now + timedelta(minutes=payload.estimated_remaining_minutes)
        delay_seconds = (projected_arrival - checkin.expected_at).total_seconds()
        if delay_seconds > (eta_delay_threshold_minutes * 60.0):
            is_eta_delayed = True
    else:
        # Check if elapsed time has exceeded expected_at + threshold
        if now > (checkin.expected_at + timedelta(minutes=eta_delay_threshold_minutes)):
            is_eta_delayed = True

    # 3. Alert Generation, Deduplication & Recovery Handling
    alert_triggered = False
    active_alert: Optional[Alert] = None

    if is_deviated or is_eta_delayed:
        # Check if an active alert already exists for this ongoing episode
        active_alert_id = store.get_active_deviation_alert_id(checkin_id)
        if active_alert_id:
            existing_alert = store.get_alert(active_alert_id)
            if existing_alert:
                active_alert = existing_alert
                alert_triggered = False
                msg_parts = []
                if is_deviated:
                    msg_parts.append(f"deviated ({deviation_distance_meters}m)")
                if is_eta_delayed:
                    msg_parts.append("ETA delayed")
                message = f"Check-in is currently {' and '.join(msg_parts)}. Existing active alert ({active_alert_id}) retained."
            else:
                # Alert was somehow missing from store, generate fresh
                active_alert = None

        if active_alert is None:
            # Create NEW deviation/ETA alert
            contact = store.get_contact(checkin.contact_id)
            if contact is None:
                raise KeyError(f"Trusted contact '{checkin.contact_id}' not found")

            reasons = []
            if is_deviated:
                reasons.append(f"deviated from route by {deviation_distance_meters:.0f}m")
            if is_eta_delayed:
                reasons.append(f"delayed past expected ETA ({checkin.expected_at.strftime('%H:%M UTC')})")
            reason_str = " and ".join(reasons)
            alert_msg = (
                f"SAFETY ALERT: {checkin.user_id} has {reason_str}. "
                f"Last location: ({payload.lat:.4f}, {payload.lng:.4f})."
            )

            new_alert = Alert(
                alert_id=_new_id(),
                checkin_id=checkin_id,
                alert_type=AlertType.ETA_DEVIATION,
                alert_status=AlertStatus.PENDING,
                trusted_contact=contact,
                message=alert_msg,
                created_at=_now(),
                sent_at=None,
            )

            delivery_status = dispatch_notification(contact, new_alert)
            new_alert = new_alert.model_copy(update={
                "alert_status": delivery_status,
                "sent_at": _now() if delivery_status == AlertStatus.SENT else None,
            })
            store.save_alert(new_alert)
            store.set_active_deviation_alert_id(checkin_id, new_alert.alert_id)
            active_alert = new_alert
            alert_triggered = True
            message = f"New safety alert triggered and notification dispatched: {alert_msg}"
    else:
        # Normal or Recovered: user is within tolerance and on schedule
        store.clear_active_deviation_alert_id(checkin_id)
        alert_triggered = False
        active_alert = None
        message = "Location update normal: User is on expected route and within ETA window."

    return LocationUpdateResponse(
        checkin_id=checkin_id,
        status=checkin.status,
        is_deviated=is_deviated,
        is_eta_delayed=is_eta_delayed,
        deviation_distance_meters=deviation_distance_meters,
        alert_triggered=alert_triggered,
        alert=active_alert,
        message=message,
    )


# ── Phase 4: Post-Walk Feedback & Scoring Pipeline ───────────────────

def submit_feedback(checkin_id: str, payload: FeedbackCreate) -> Feedback:
    """
    Record post-walk 1-tap feedback for a safely completed check-in.

    Validates that the check-in exists and has completed, prevents duplicate
    feedback for the same session, and associates feedback with the route.

    Raises:
        KeyError: If check-in is not found.
        ValueError: If check-in is not completed or feedback was already submitted.
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")

    if checkin.status != CheckInStatus.COMPLETED:
        raise ValueError(
            f"Feedback can only be submitted for completed check-ins. "
            f"Current status is '{checkin.status.value}'."
        )

    if store.get_feedback_by_checkin(checkin_id) is not None:
        raise ValueError("Feedback has already been submitted for this check-in session.")

    feedback = Feedback(
        feedback_id=_new_id(),
        checkin_id=checkin_id,
        route_id=checkin.route_id,
        user_id=checkin.user_id,
        rating=payload.rating,
        issue_tags=payload.issue_tags or [],
        comment=payload.comment,
        created_at=_now(),
    )
    store.save_feedback(feedback)
    return feedback


def get_feedback_by_checkin(checkin_id: str) -> Optional[Feedback]:
    """Retrieve feedback submitted for a specific check-in session."""
    return store.get_feedback_by_checkin(checkin_id)


def list_all_feedbacks() -> List[Feedback]:
    """List all recorded post-walk feedbacks."""
    return store.all_feedbacks()


def get_route_feedback_summary(route_id: str) -> RouteFeedbackSummary:
    """
    Aggregate post-walk feedback signals for a specific route.

    Exposes structured scoring signals (average rating, tag frequencies,
    recent feedback records) that Track A (ML / scoring model) can consume
    directly for route score retraining and calibration.
    """
    feedbacks = store.feedbacks_for_route(route_id)
    total = len(feedbacks)
    avg_rating = round(sum(f.rating for f in feedbacks) / total, 2) if total > 0 else 0.0

    tag_counts: Dict[str, int] = {}
    for f in feedbacks:
        for tag in f.issue_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    sorted_recent = sorted(feedbacks, key=lambda x: x.created_at, reverse=True)[:20]

    return RouteFeedbackSummary(
        route_id=route_id,
        total_reviews=total,
        average_rating=avg_rating,
        issue_tag_counts=tag_counts,
        recent_feedbacks=sorted_recent,
    )


# ── Phase 4: Privacy & Location Session Lifecycle ────────────────────

def get_privacy_session_status(checkin_id: str) -> PrivacySessionResponse:
    """
    Evaluate privacy and location-sharing status for a safety session.

    Guarantees that location sharing is only active while the user is in transit
    (ACTIVE or OVERDUE) and automatically ceases upon completion or cancellation.

    Raises:
        KeyError: If check-in is not found.
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")

    is_active = checkin.status in (CheckInStatus.ACTIVE, CheckInStatus.OVERDUE)
    if is_active:
        notice = "Location sharing is currently active in transit for live safety monitoring."
    else:
        notice = (
            f"Location sharing has ended (session status: {checkin.status.value}). "
            "No location history is stored after arrival."
        )

    return PrivacySessionResponse(
        checkin_id=checkin_id,
        status=checkin.status,
        location_sharing_active=is_active,
        privacy_notice=notice,
    )


# ── Phase 5: Demo State Management ───────────────────────────────────

def reset_demo_state() -> DemoResetResponse:
    """
    Reset all dynamic in-memory store states and re-seed default demo contacts.
    Returns status and the default demo contact ID.
    """
    store.reset_store()
    return DemoResetResponse(
        status="ok",
        message="Demo state has been reset and seeded with default demo contact.",
        demo_contact_id=store.DEFAULT_DEMO_CONTACT_ID,
    )



