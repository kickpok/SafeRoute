"""
SafeRoute Backend – In-memory safety data store.

Provides the storage layer for check-ins, trusted contacts, and alerts.

This module uses plain Python dicts keyed by ID — no database required.

┌─────────────────────────────────────────────────────────────────────┐
│  HOW TO REPLACE WITH A REAL DATABASE (Phase 3+)                    │
│                                                                     │
│  1. Replace the dict stores below with SQLAlchemy / MongoDB /       │
│     Redis calls.                                                    │
│  2. The service layer (checkin_service.py) imports from here;       │
│     only this file needs to change.                                 │
│  3. The API layer (safety_routes.py) and schemas are not affected. │
└─────────────────────────────────────────────────────────────────────┘

NOTE: All data is lost when the server restarts — intentional for Phase 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.safety_schemas import Alert, CheckIn, Feedback, TrustedContact

# ── In-memory stores ────────────────────────────────────────────────

# Dict[contact_id, TrustedContact]
_contacts: Dict[str, TrustedContact] = {}

# Dict[checkin_id, CheckIn]
_checkins: Dict[str, CheckIn] = {}

# Dict[alert_id, Alert]
_alerts: Dict[str, Alert] = {}

# Dict[checkin_id, alert_id] - tracks currently active deviation alert for deduplication
_active_deviation_alerts: Dict[str, str] = {}

# Dict[feedback_id, Feedback]
_feedbacks: Dict[str, Feedback] = {}

# Dict[checkin_id, feedback_id] - ensure 1 feedback per check-in
_checkin_feedback_index: Dict[str, str] = {}



# ── Trusted Contact store ────────────────────────────────────────────

def save_contact(contact: TrustedContact) -> None:
    _contacts[contact.contact_id] = contact


def get_contact(contact_id: str) -> Optional[TrustedContact]:
    return _contacts.get(contact_id)


def all_contacts() -> list[TrustedContact]:
    return list(_contacts.values())


def delete_contact(contact_id: str) -> bool:
    """Remove a trusted contact from the store. Returns True if removed, False if not found."""
    return _contacts.pop(contact_id, None) is not None


# ── Check-In store ───────────────────────────────────────────────────

def save_checkin(checkin: CheckIn) -> None:
    _checkins[checkin.checkin_id] = checkin


def get_checkin(checkin_id: str) -> Optional[CheckIn]:
    return _checkins.get(checkin_id)


def all_checkins() -> list[CheckIn]:
    return list(_checkins.values())


# ── Alert store ──────────────────────────────────────────────────────

def save_alert(alert: Alert) -> None:
    _alerts[alert.alert_id] = alert


def get_alert(alert_id: str) -> Optional[Alert]:
    return _alerts.get(alert_id)


def all_alerts() -> list[Alert]:
    return list(_alerts.values())


def alerts_for_checkin(checkin_id: str) -> list[Alert]:
    return [a for a in _alerts.values() if a.checkin_id == checkin_id]


# ── Active Deviation State (Phase 3 Deduplication & Recovery) ─────────

def get_active_deviation_alert_id(checkin_id: str) -> Optional[str]:
    return _active_deviation_alerts.get(checkin_id)


def set_active_deviation_alert_id(checkin_id: str, alert_id: str) -> None:
    _active_deviation_alerts[checkin_id] = alert_id


def clear_active_deviation_alert_id(checkin_id: str) -> None:
    _active_deviation_alerts.pop(checkin_id, None)


# ── Feedback store (Phase 4 Post-Walk Feedback Loop) ──────────────────

def save_feedback(feedback: Feedback) -> None:
    _feedbacks[feedback.feedback_id] = feedback
    _checkin_feedback_index[feedback.checkin_id] = feedback.feedback_id


def get_feedback(feedback_id: str) -> Optional[Feedback]:
    return _feedbacks.get(feedback_id)


def get_feedback_by_checkin(checkin_id: str) -> Optional[Feedback]:
    fid = _checkin_feedback_index.get(checkin_id)
    if fid:
        return _feedbacks.get(fid)
    return None


def all_feedbacks() -> list[Feedback]:
    return list(_feedbacks.values())


def feedbacks_for_route(route_id: str) -> list[Feedback]:
    return [f for f in _feedbacks.values() if f.route_id == route_id]


# ── Demo Initialization & Reset (Phase 5) ─────────────────────────────

DEFAULT_DEMO_CONTACT_ID = "demo-contact-001"


def seed_demo_data() -> None:
    """Populate default trusted contact and demo state for predictable presentation flow."""
    demo_contact = TrustedContact(
        contact_id=DEFAULT_DEMO_CONTACT_ID,
        name="Emergency Contact (Mom)",
        contact_method="+91-9876543210",
        created_at=datetime.now(timezone.utc),
    )
    save_contact(demo_contact)


def reset_store() -> None:
    """Clear all dynamic sessions/alerts/feedbacks and restore clean demo state."""
    _contacts.clear()
    _checkins.clear()
    _alerts.clear()
    _active_deviation_alerts.clear()
    _feedbacks.clear()
    _checkin_feedback_index.clear()
    seed_demo_data()


# Auto-seed on startup
seed_demo_data()



