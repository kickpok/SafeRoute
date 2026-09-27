"""
SafeRoute Backend – Phase 2 Safety Schemas.

Defines the API contracts for:
  - TrustedContact
  - CheckIn session (one-time & user-controlled periodic check-ins)
  - Alert & Safety Notifications
  - Location Updates & Deviation
  - Feedback & Privacy Lifecycle
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enumerations ────────────────────────────────────────────────────

class CheckInStatus(str, Enum):
    """Lifecycle states of a check-in session."""
    ACTIVE    = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE   = "overdue"


class AlertType(str, Enum):
    """Types of safety alerts and notifications the backend can generate."""
    CHECKIN_OVERDUE = "checkin_overdue"
    ETA_DEVIATION   = "eta_deviation"
    DISTRESS        = "distress"
    TRIP_START      = "trip_start"
    TRIP_COMPLETED  = "trip_completed"


class AlertStatus(str, Enum):
    """Whether the alert has been actioned by the notification layer."""
    PENDING   = "pending"
    SENT      = "sent"
    FAILED    = "failed"


# ── Trusted Contact ─────────────────────────────────────────────────

class TrustedContactCreate(BaseModel):
    """Request body: register a new trusted contact."""
    name: str = Field(..., min_length=1, max_length=100,
                      description="Full name of the trusted contact")
    contact_method: str = Field(
        ..., min_length=1, max_length=200,
        description=(
            "Destination for notifications (phone number, email address, WhatsApp handle, etc.). "
            "The notification provider interprets this field."
        ),
        examples=["+91-9876543210", "friend@example.com"],
    )


class TrustedContact(BaseModel):
    """A stored trusted contact (returned by the API)."""
    contact_id: str       = Field(..., description="Unique contact identifier (UUID)")
    name: str             = Field(..., description="Full name")
    contact_method: str   = Field(..., description="Notification destination")
    created_at: datetime  = Field(..., description="UTC timestamp of registration")


# ── Check-In ────────────────────────────────────────────────────────

class CheckInCreate(BaseModel):
    """Request body: start a new safety check-in session."""
    user_id: str = Field(
        ..., min_length=1, max_length=100,
        description="Opaque user or session identifier (no auth required)",
        examples=["user-abc-123"],
    )
    contact_id: Optional[str] = Field(
        None,
        description="ID of a previously registered TrustedContact (optional if check-ins are OFF)",
    )
    duration_minutes: Optional[int] = Field(
        30, ge=1, le=1440,
        description="Expected walk duration in minutes (1 – 1440)",
        examples=[30],
    )
    route_id: Optional[str] = Field(
        None,
        description="Optional route_id from Phase 1 — links check-in to a specific route",
    )
    # User-controlled periodic check-in options
    periodic_checkin_enabled: Optional[bool] = Field(
        False,
        description="Whether recurring periodic check-in prompts are active (e.g. every 30 minutes)",
    )
    interval_minutes: Optional[int] = Field(
        30, ge=1, le=1440,
        description="Interval in minutes between periodic check-ins (e.g. 30)",
    )
    destination_name: Optional[str] = Field(
        None, max_length=200,
        description="Destination name for trip-start / arrival notification copy (e.g. 'Lajpat Nagar')",
    )
    notify_on_start: Optional[bool] = Field(
        False,
        description="Whether to dispatch a trip-start notification with destination and ETA to trusted contact",
    )
    notify_on_arrival: Optional[bool] = Field(
        False,
        description="Whether to dispatch an arrival notification to trusted contact upon trip completion",
    )


class CheckIn(BaseModel):
    """A check-in session (returned by the API)."""
    checkin_id:               str                = Field(..., description="Unique check-in identifier (UUID)")
    user_id:                  str                = Field(..., description="User/session identifier")
    contact_id:               Optional[str]      = Field(None, description="Linked trusted contact ID")
    duration_minutes:         int                = Field(..., description="Expected walk duration in minutes")
    route_id:                 Optional[str]      = Field(None, description="Linked route ID, if any")
    status:                   CheckInStatus      = Field(..., description="Current lifecycle state")
    started_at:               datetime           = Field(..., description="UTC start time")
    expected_at:              datetime           = Field(..., description="UTC expected completion time")
    completed_at:             Optional[datetime] = Field(None, description="UTC completion time, if done")
    # Periodic check-in and notification metadata
    periodic_checkin_enabled: bool               = Field(False, description="Whether periodic check-ins are active")
    interval_minutes:         Optional[int]      = Field(None, description="Recurring check-in interval in minutes")
    next_checkin_due_at:      Optional[datetime] = Field(None, description="UTC timestamp when next 'I'm Safe' check-in is expected")
    last_checkin_at:          Optional[datetime] = Field(None, description="UTC timestamp of the most recent 'I'm Safe' check-in")
    destination_name:         Optional[str]      = Field(None, description="Destination name for notifications")
    notify_on_start:          bool               = Field(False, description="Trip-start notification preference")
    notify_on_arrival:        bool               = Field(False, description="Trip-completion notification preference")
    checkin_count:            int                = Field(0, description="Total number of safe check-ins completed in this session")


class CheckInStatusResponse(BaseModel):
    """Overdue-check response (also embeds the current check-in state)."""
    checkin_id:                  str                = Field(..., description="The check-in ID queried")
    status:                      CheckInStatus      = Field(..., description="Current status")
    is_overdue:                  bool               = Field(..., description="True when now > expected_at or now > next_checkin_due_at and still active")
    message:                     str                = Field(..., description="Human-readable status summary")
    next_checkin_due_at:         Optional[datetime] = Field(None, description="UTC timestamp when next check-in is due")
    seconds_until_next_checkin:  Optional[float]    = Field(None, description="Seconds remaining until next check-in is due")
    periodic_checkin_enabled:    bool               = Field(False, description="Whether periodic check-ins are active")


class ManualCheckInResponse(BaseModel):
    """Response returned when user registers an 'I'm Safe' check-in."""
    checkin_id:                  str                = Field(..., description="Check-in session identifier")
    status:                      CheckInStatus      = Field(..., description="Current status (e.g. active)")
    last_checkin_at:             datetime           = Field(..., description="UTC timestamp of recorded check-in")
    next_checkin_due_at:         Optional[datetime] = Field(None, description="UTC timestamp when the next check-in is expected")
    seconds_until_next_checkin:  Optional[float]    = Field(None, description="Seconds remaining until next check-in")
    checkin_count:               int                = Field(..., description="Total check-ins completed in this session")
    message:                     str                = Field(..., description="Confirmation feedback message")


# ── Alert ────────────────────────────────────────────────────────────

class Alert(BaseModel):
    """A safety alert record."""
    alert_id:        str             = Field(..., description="Unique alert identifier (UUID)")
    checkin_id:      str             = Field(..., description="Associated check-in ID")
    alert_type:      AlertType       = Field(..., description="Category of the alert")
    alert_status:    AlertStatus     = Field(..., description="Notification delivery status")
    trusted_contact: TrustedContact  = Field(..., description="Contact that was notified")
    message:         str             = Field(..., description="Human-readable alert message")
    created_at:      datetime        = Field(..., description="UTC timestamp when alert was created")
    sent_at:         Optional[datetime] = Field(
        None, description="UTC timestamp when notification was dispatched (mock or real)"
    )


# ── Convenience list wrappers ────────────────────────────────────────

class TrustedContactListResponse(BaseModel):
    """Response for listing trusted contacts."""
    items: List[TrustedContact]
    count: int


class CheckInListResponse(BaseModel):
    """Response for listing check-ins."""
    items: List[CheckIn]
    count: int


class AlertListResponse(BaseModel):
    """Response for listing alerts."""
    items: List[Alert]
    count: int


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx / 5xx."""
    detail: str = Field(..., description="Human-readable error message")


# ── Location & Progress Updates (Phase 3) ────────────────────────────

class LocationUpdate(BaseModel):
    """Request body: location and progress ping for an active check-in."""
    lat: float = Field(
        ..., ge=-90.0, le=90.0,
        description="Current latitude (-90.0 to 90.0)",
        examples=[28.6330],
    )
    lng: float = Field(
        ..., ge=-180.0, le=180.0,
        description="Current longitude (-180.0 to 180.0)",
        examples=[77.2190],
    )
    timestamp: Optional[datetime] = Field(
        None,
        description="UTC timestamp of the location ping (defaults to server now if omitted)",
    )
    estimated_remaining_minutes: Optional[float] = Field(
        None, ge=0.0,
        description="Estimated minutes remaining to destination, if computed by client",
        examples=[12.5],
    )


class LocationUpdateResponse(BaseModel):
    """Response for a location/progress update."""
    checkin_id: str = Field(..., description="Check-in session identifier")
    status: CheckInStatus = Field(..., description="Current status of the check-in session")
    is_deviated: bool = Field(..., description="True if current position exceeds route deviation threshold")
    is_eta_delayed: bool = Field(..., description="True if estimated arrival exceeds expected ETA threshold")
    deviation_distance_meters: Optional[float] = Field(
        None, description="Calculated distance in meters to nearest route waypoint/segment"
    )
    alert_triggered: bool = Field(
        ..., description="True if a NEW alert was created and dispatched on this ping"
    )
    alert: Optional[Alert] = Field(
        None, description="Newly triggered alert, or active existing alert if still in deviated state"
    )
    message: str = Field(..., description="Human-readable status assessment")


# ── Post-Walk Feedback (Phase 4) ─────────────────────────────────────

class FeedbackCreate(BaseModel):
    """Request body: 1-tap post-walk safety feedback."""
    rating: int = Field(
        ..., ge=1, le=5,
        description="Overall perceived safety and walk experience (1 = Very Unsafe, 5 = Very Safe)",
        examples=[5],
    )
    issue_tags: Optional[List[str]] = Field(
        default_factory=list,
        description=(
            "Optional predefined tags or issue categories (e.g. 'poor_lighting', "
            "'isolated_stretch', 'crowded', 'harassment', 'felt_safe', 'well_lit')"
        ),
        examples=[["well_lit", "felt_safe"]],
    )
    comment: Optional[str] = Field(
        None, max_length=500,
        description="Optional brief user note or context",
        examples=["Felt very secure, plenty of open shops along the way."],
    )


class Feedback(BaseModel):
    """A recorded post-walk feedback entry."""
    feedback_id: str = Field(..., description="Unique feedback record identifier (UUID)")
    checkin_id: str = Field(..., description="Associated check-in session ID")
    route_id: Optional[str] = Field(None, description="Associated route ID, if check-in was linked to a route")
    user_id: str = Field(..., description="User or session identifier")
    rating: int = Field(..., description="Safety score rating (1 - 5)")
    issue_tags: List[str] = Field(default_factory=list, description="Reported category tags")
    comment: Optional[str] = Field(None, description="User comment")
    created_at: datetime = Field(..., description="UTC timestamp of feedback submission")


class FeedbackListResponse(BaseModel):
    """Response for listing feedback entries."""
    items: List[Feedback]
    count: int


class RouteFeedbackSummary(BaseModel):
    """Aggregated feedback signals for Track A scoring pipeline consumption."""
    route_id: str = Field(..., description="The route ID queried")
    total_reviews: int = Field(..., description="Total feedback submissions for this route")
    average_rating: float = Field(..., description="Average star rating (1.0 to 5.0), or 0.0 if no reviews")
    issue_tag_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Frequencies of reported issue/positive tags",
    )
    recent_feedbacks: List[Feedback] = Field(
        default_factory=list,
        description="Latest feedback records for pipeline ingestion",
    )


# ── Privacy Session Lifecycle (Phase 4) ──────────────────────────────

class PrivacySessionResponse(BaseModel):
    """Privacy lifecycle state for a check-in session."""
    checkin_id: str = Field(..., description="Check-in session identifier")
    status: CheckInStatus = Field(..., description="Current lifecycle state")
    location_sharing_active: bool = Field(
        ...,
        description="True only while session is in transit (ACTIVE or OVERDUE). Automatically false upon completion/cancellation.",
    )
    privacy_notice: str = Field(..., description="Human-readable privacy explanation")


# ── Demo Management (Phase 5) ────────────────────────────────────────

class DemoResetResponse(BaseModel):
    """Response model for demo reset and state re-initialization."""
    status: str = Field("ok", description="Operation status")
    message: str = Field(..., description="Human-readable status summary")
    demo_contact_id: str = Field(..., description="Default seeded demo trusted contact ID")
