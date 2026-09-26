"""
SafeRoute Backend – Notification Service (MOCK implementation).

This module defines the NotificationProvider interface and the
MockNotificationProvider used in Phase 2.

┌─────────────────────────────────────────────────────────────────────┐
│  MOCK  — No real SMS / WhatsApp / email is sent in Phase 2.        │
│                                                                     │
│  HOW TO CONNECT A REAL PROVIDER (Phase 3+)                         │
│                                                                     │
│  1. Create a new class that inherits NotificationProvider.          │
│  2. Implement the `send` method using Twilio / SendGrid / etc.      │
│  3. Change the ACTIVE_PROVIDER assignment at the bottom of this     │
│     file — nothing else in the codebase needs to change.           │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.safety_schemas import Alert, AlertStatus, TrustedContact

logger = logging.getLogger("saferoute.notifications")


# ── Abstract interface ───────────────────────────────────────────────

class NotificationProvider(ABC):
    """Base class for all notification providers.

    Track D depends on the Alert schema, not on this class.
    """

    @abstractmethod
    def send(self, contact: TrustedContact, alert: Alert) -> bool:
        """Dispatch a notification for the given alert.

        Returns True on success, False on failure.
        """


# ── MOCK implementation ─────────────────────────────────────────────

class MockNotificationProvider(NotificationProvider):
    """[MOCK] Simulates notification delivery via structured logging.

    Nothing is actually sent over the network.
    Replace with a real provider when ready.
    """

    def send(self, contact: TrustedContact, alert: Alert) -> bool:
        logger.info(
            "[MOCK NOTIFICATION] "
            "alert_id=%s | type=%s | to=%s (%s) | msg=%s",
            alert.alert_id,
            alert.alert_type.value,
            contact.name,
            contact.contact_method,
            alert.message,
        )
        print(
            f"\n[MOCK NOTIFICATION SENT]\n"
            f"  Alert ID   : {alert.alert_id}\n"
            f"  Alert Type : {alert.alert_type.value}\n"
            f"  To         : {contact.name} @ {contact.contact_method}\n"
            f"  Message    : {alert.message}\n"
            f"  Timestamp  : {datetime.now(timezone.utc).isoformat()}\n"
        )
        return True  # mock always succeeds


# ── Active provider (swap this line to change providers) ────────────

ACTIVE_PROVIDER: NotificationProvider = MockNotificationProvider()


def dispatch_notification(contact: TrustedContact, alert: Alert) -> AlertStatus:
    """Send a notification and return the resulting AlertStatus.

    Called by the alert service — provider-agnostic.
    """
    try:
        success = ACTIVE_PROVIDER.send(contact, alert)
        return AlertStatus.SENT if success else AlertStatus.FAILED
    except Exception as exc:  # noqa: BLE001
        logger.error("Notification dispatch failed: %s", exc)
        return AlertStatus.FAILED
