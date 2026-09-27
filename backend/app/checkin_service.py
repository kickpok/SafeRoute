"""
SafeRoute Backend – Check-In & Alert business-logic service.

All safety feature logic lives here.  The API layer (safety_routes.py)
calls these functions — it never touches the store or notification
provider directly.

Responsibilities:
  - Trusted-contact CRUD
  - Check-in lifecycle management (one-time & user-controlled periodic check-ins)
  - Trip-start & trip-completion notifications
  - Manual 'I'm Safe' check-in registration
  - Overdue detection (periodic interval & final ETA)
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
    ManualCheckInResponse,
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


def delete_contact(contact_id: str) -> bool:
    """Remove a trusted contact from the store."""
    return store.delete_contact(contact_id)


# ── Check-In service ─────────────────────────────────────────────────

def create_checkin(payload: CheckInCreate) -> CheckIn:
    """
    Start a new active check-in session.

    Supports:
      - Periodic check-ins (e.g. 30-min intervals) with backend calculation of next check-in time
      - Optional trip-start notification to trusted contact with destination and ETA
      - Sessions without trusted contact when check-ins are OFF
    """
    contact = None
    if payload.contact_id:
        contact = store.get_contact(payload.contact_id)
        if contact is None:
            raise ValueError(f"Trusted contact '{payload.contact_id}' not found")

    now = _now()
    duration = payload.duration_minutes or 30
    expected_arrival = now + timedelta(minutes=duration)

    is_periodic = bool(payload.periodic_checkin_enabled)
    interval = payload.interval_minutes if (is_periodic and payload.interval_minutes) else (duration if is_periodic else None)

    if is_periodic and interval:
        next_due = now + timedelta(minutes=interval)
        if next_due > expected_arrival:
            next_due = expected_arrival
    else:
        next_due = expected_arrival

    checkin = CheckIn(
        checkin_id=_new_id(),
        user_id=payload.user_id,
        contact_id=payload.contact_id,
        duration_minutes=duration,
        route_id=payload.route_id,
        status=CheckInStatus.ACTIVE,
        started_at=now,
        expected_at=expected_arrival,
        completed_at=None,
        periodic_checkin_enabled=is_periodic,
        interval_minutes=interval,
        next_checkin_due_at=next_due,
        last_checkin_at=now,
        destination_name=payload.destination_name,
        notify_on_start=bool(payload.notify_on_start),
        notify_on_arrival=bool(payload.notify_on_arrival),
        checkin_count=0,
    )
    store.save_checkin(checkin)

    # Dispatch trip-start notification if requested and contact is registered
    if payload.notify_on_start and contact:
        dest_str = payload.destination_name or (f"Route {payload.route_id}" if payload.route_id else "Destination")
        start_msg = (
            f"Trip started.\n"
            f"Destination: {dest_str}\n"
            f"Estimated arrival: {expected_arrival.strftime('%H:%M UTC')}"
        )
        start_alert = Alert(
            alert_id=_new_id(),
            checkin_id=checkin.checkin_id,
            alert_type=AlertType.TRIP_START,
            alert_status=AlertStatus.PENDING,
            trusted_contact=contact,
            message=start_msg,
            created_at=now,
            sent_at=None,
        )
        deliv = dispatch_notification(contact, start_alert)
        start_alert = start_alert.model_copy(update={
            "alert_status": deliv,
            "sent_at": _now() if deliv == AlertStatus.SENT else None,
        })
        store.save_alert(start_alert)

    return checkin


def get_checkin(checkin_id: str) -> Optional[CheckIn]:
    """Return a check-in session or None."""
    return store.get_checkin(checkin_id)


def list_checkins() -> List[CheckIn]:
    return store.all_checkins()


def record_manual_checkin(checkin_id: str) -> ManualCheckInResponse:
    """
    Process an 'I'm Safe' manual check-in from the user.

    1. Validates that the session is active or overdue.
    2. Resets/clears overdue status back to ACTIVE.
    3. Calculates the next scheduled check-in time if periodic check-ins are enabled.
    4. Updates checkin_count and last_checkin_at.
    """
    checkin = store.get_checkin(checkin_id)
    if checkin is None:
        raise KeyError(f"Check-in '{checkin_id}' not found")
    if checkin.status not in (CheckInStatus.ACTIVE, CheckInStatus.OVERDUE):
        raise ValueError(
            f"Cannot perform manual check-in with status '{checkin.status.value}'. "
            "Session is already finished."
        )

    now = _now()
    new_count = checkin.checkin_count + 1

    if checkin.periodic_checkin_enabled and checkin.interval_minutes:
        next_due = now + timedelta(minutes=checkin.interval_minutes)
        if next_due > checkin.expected_at:
            next_due = checkin.expected_at
    else:
        next_due = checkin.expected_at

    updated = checkin.model_copy(update={
        "status": CheckInStatus.ACTIVE,
        "last_checkin_at": now,
        "next_checkin_due_at": next_due,
        "checkin_count": new_count,
    })
    store.save_checkin(updated)

    seconds_remaining = max(0.0, (next_due - now).total_seconds()) if next_due else None

    if checkin.periodic_checkin_enabled and checkin.interval_minutes:
        msg = f"Check-in #{new_count} recorded. Next check-in scheduled for {next_due.strftime('%H:%M UTC')}."
    else:
        msg = f"Check-in recorded. Expected arrival by {checkin.expected_at.strftime('%H:%M UTC')}."

    return ManualCheckInResponse(
        checkin_id=checkin_id,
        status=CheckInStatus.ACTIVE,
        last_checkin_at=now,
        next_checkin_due_at=next_due,
        seconds_until_next_checkin=round(seconds_remaining, 1) if seconds_remaining is not None else None,
        checkin_count=new_count,
        message=msg,
    )


def complete_checkin(checkin_id: str) -> CheckIn:
    """
    Mark a check-in as safely completed and optionally send an arrival notification.

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

    now = _now()
    updated = checkin.model_copy(update={
        "status": CheckInStatus.COMPLETED,
        "completed_at": now,
        "next_checkin_due_at": None,
    })
    store.save_checkin(updated)
    store.clear_active_deviation_alert_id(checkin_id)

    # Dispatch arrival notification if requested
    if checkin.notify_on_arrival and checkin.contact_id:
        contact = store.get_contact(checkin.contact_id)
        if contact:
            dest_str = checkin.destination_name or (f"Route {checkin.route_id}" if checkin.route_id else "destination")
            arrival_msg = (
                f"Trip completed.\n"
                f"Arrived at {dest_str}."
            )
            arrival_alert = Alert(
                alert_id=_new_id(),
                checkin_id=checkin.checkin_id,
                alert_type=AlertType.TRIP_COMPLETED,
                alert_status=AlertStatus.PENDING,
                trusted_contact=contact,
                message=arrival_msg,
                created_at=now,
                sent_at=None,
            )
            deliv = dispatch_notification(contact, arrival_alert)
            arrival_alert = arrival_alert.model_copy(update={
                "alert_status": deliv,
                "sent_at": _now() if deliv == AlertStatus.SENT else None,
            })
            store.save_alert(arrival_alert)

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
    updated = checkin.model_copy(update={
        "status": CheckInStatus.CANCELLED,
        "next_checkin_due_at": None,
    })
    store.save_checkin(updated)
    store.clear_active_deviation_alert_id(checkin_id)
    return updated


def get_checkin_status(checkin_id: str) -> CheckInStatusResponse:
    """
    Evaluate whether a check-in is overdue (checking both periodic interval and arrival ETA).

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
    now = _now()

    if checkin.status == CheckInStatus.ACTIVE:
        is_past_eta = now > checkin.expected_at
        is_past_interval = bool(
            checkin.periodic_checkin_enabled
            and checkin.next_checkin_due_at
            and now > checkin.next_checkin_due_at
        )

        if is_past_eta or is_past_interval:
            # Transition to OVERDUE
            updated = checkin.model_copy(update={"status": CheckInStatus.OVERDUE})
            store.save_checkin(updated)
            current_status = CheckInStatus.OVERDUE
            is_overdue = True
            checkin = updated
    elif checkin.status == CheckInStatus.OVERDUE:
        is_overdue = True

    seconds_remaining = None
    if checkin.status == CheckInStatus.ACTIVE and checkin.next_checkin_due_at:
        seconds_remaining = max(0.0, (checkin.next_checkin_due_at - now).total_seconds())

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
        next_checkin_due_at=checkin.next_checkin_due_at,
        seconds_until_next_checkin=round(seconds_remaining, 1) if seconds_remaining is not None else None,
        periodic_checkin_enabled=checkin.periodic_checkin_enabled,
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

    if not checkin.contact_id:
        raise KeyError(f"No trusted contact registered for check-in '{checkin_id}'")

    contact = store.get_contact(checkin.contact_id)
    if contact is None:
        raise KeyError(f"Trusted contact '{checkin.contact_id}' not found")

    now = _now()
    deadline = checkin.next_checkin_due_at or checkin.expected_at
    message = (
        f"SAFETY ALERT: {checkin.user_id} has not checked in. "
        f"Expected by {deadline.strftime('%H:%M UTC')}. "
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

    # Dispatch to notification provider
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

def scan_overdue_checkins() -> List[CheckIn]:
    """
    Evaluate all ACTIVE check-ins, transition overdue ones, return the list.

    Evaluates both ETA and periodic interval deadlines.
    """
    now = _now()
    newly_overdue: List[CheckIn] = []

    for checkin in store.all_checkins():
        if checkin.status == CheckInStatus.ACTIVE:
            is_past_eta = now > checkin.expected_at
            is_past_interval = bool(
                checkin.periodic_checkin_enabled
                and checkin.next_checkin_due_at
                and now > checkin.next_checkin_due_at
            )
            if is_past_eta or is_past_interval:
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
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Evaluate Route Deviation
    is_deviated = False
    deviation_distance_meters: Optional[float] = None

    if checkin.route_id:
        route = get_route_by_id(checkin.route_id)
        if route and route.coordinates:
            deviation_distance_meters = min_distance_to_route(
                payload.lat, payload.lng, route.coordinates
            )
            if deviation_distance_meters > deviation_threshold_meters:
                is_deviated = True

    # 2. Evaluate ETA Delay
    is_eta_delayed = False
    if payload.estimated_remaining_minutes is not None:
        current_projected_arrival = now + timedelta(minutes=payload.estimated_remaining_minutes)
        allowed_arrival_deadline = checkin.expected_at + timedelta(minutes=eta_delay_threshold_minutes)
        if current_projected_arrival > allowed_arrival_deadline:
            is_eta_delayed = True

    # 3. Alert Triggering & Deduplication
    alert_triggered = False
    active_alert: Optional[Alert] = None
    existing_alert_id = store.get_active_deviation_alert_id(checkin_id)

    if is_deviated or is_eta_delayed:
        if existing_alert_id is None:
            # Need to trigger new alert
            if checkin.contact_id:
                contact = store.get_contact(checkin.contact_id)
                if contact:
                    reasons = []
                    if is_deviated and deviation_distance_meters is not None:
                        reasons.append(f"deviated {deviation_distance_meters:.0f}m from planned route")
                    if is_eta_delayed:
                        reasons.append("significant arrival delay detected")

                    msg = (
                        f"SAFETY ALERT: {checkin.user_id} may need assistance ({', '.join(reasons)}). "
                        f"Current position: ({payload.lat:.4f}, {payload.lng:.4f})."
                    )

                    new_alert = Alert(
                        alert_id=_new_id(),
                        checkin_id=checkin_id,
                        alert_type=AlertType.ETA_DEVIATION,
                        alert_status=AlertStatus.PENDING,
                        trusted_contact=contact,
                        message=msg,
                        created_at=now,
                        sent_at=None,
                    )
                    deliv = dispatch_notification(contact, new_alert)
                    new_alert = new_alert.model_copy(update={
                        "alert_status": deliv,
                        "sent_at": _now() if deliv == AlertStatus.SENT else None,
                    })
                    store.save_alert(new_alert)
                    store.set_active_deviation_alert_id(checkin_id, new_alert.alert_id)
                    active_alert = new_alert
                    alert_triggered = True
        else:
            active_alert = store.get_alert(existing_alert_id)
    else:
        if existing_alert_id is not None:
            store.clear_active_deviation_alert_id(checkin_id)

    if is_deviated:
        message = f"Route deviation detected ({deviation_distance_meters:.0f}m from path)."
    elif is_eta_delayed:
        message = "ETA delay detected past tolerance threshold."
    else:
        message = "Location update processed normally. On route."

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
    """Record post-walk 1-tap feedback for a safely completed check-in."""
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
    return store.get_feedback_by_checkin(checkin_id)


def list_all_feedbacks() -> List[Feedback]:
    return store.all_feedbacks()


def get_route_feedback_summary(route_id: str) -> RouteFeedbackSummary:
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
    store.reset_store()
    return DemoResetResponse(
        status="ok",
        message="Demo state has been reset and seeded with default demo contact.",
        demo_contact_id=store.DEFAULT_DEMO_CONTACT_ID,
    )
