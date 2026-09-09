"""
services/alerts.py

Simulated alert generation for the MVP. Designed so a real delivery
channel (SMS/WhatsApp/USSD/push/voice) can be plugged in later without
changing how alerts are constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

ALERTING_LEVELS = {"HIGH", "CRITICAL"}


@dataclass
class Alert:
    location: str
    risk_level: str
    risk_score: float
    reason: str
    recommended_actions: list
    timestamp: str
    is_mock_data: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def build_alert(location: str, risk_assessment: dict, recommendations: list,
                 is_mock_data: bool = False) -> Optional[Alert]:
    """Construct an Alert if the risk level warrants one, else None."""
    level = risk_assessment.get("risk_level")
    if level not in ALERTING_LEVELS:
        return None

    reason = "; ".join(risk_assessment.get("risk_factors", [])[:3])

    return Alert(
        location=location,
        risk_level=level,
        risk_score=risk_assessment.get("risk_score", 0.0),
        reason=reason,
        recommended_actions=recommendations,
        timestamp=datetime.now(timezone.utc).isoformat(),
        is_mock_data=is_mock_data,
    )


def format_alert_text(alert: Alert) -> str:
    """Human-readable version of an alert, suitable for a future
    SMS/WhatsApp channel (kept short)."""
    prefix = "[DEMO] " if alert.is_mock_data else ""
    actions = " | ".join(alert.recommended_actions[:3])
    return (
        f"{prefix}FlowSafe ALERT ({alert.risk_level}, {alert.risk_score}/100) - "
        f"{alert.location}. {alert.reason}. Do now: {actions}"
    )


# Future channels (not implemented in MVP):
#   - send_sms(alert, phone_number)
#   - send_whatsapp(alert, phone_number)
#   - send_ussd_prompt(alert, phone_number)
#   - send_push_notification(alert, device_token)
#   - send_voice_alert(alert, phone_number)
