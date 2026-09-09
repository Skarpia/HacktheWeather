"""
services/recommendation_engine.py

Turns a risk assessment + farm profile into a prioritized, farm-specific
action list. Never recommends entering floodwater or other dangerous
actions.
"""

from __future__ import annotations

from typing import Optional

BASE_RECOMMENDATIONS = {
    "CRITICAL": [
        "Move livestock to higher ground immediately.",
        "Protect seeds and fertilizer from floodwater.",
        "Move machinery away from drainage channels and low areas.",
        "Protect or relocate harvested crops.",
        "Avoid entering floodwater under any circumstances.",
        "Monitor subsequent weather updates closely.",
    ],
    "HIGH": [
        "Prepare to relocate livestock to higher ground.",
        "Protect vulnerable farm inputs (seeds, fertilizer).",
        "Check and clear drainage routes now.",
        "Move important equipment away from low-lying areas.",
        "Continue monitoring the alert closely.",
    ],
    "MODERATE": [
        "Monitor weather conditions closely over the next few hours.",
        "Inspect drainage paths for blockages.",
        "Pre-position vulnerable assets somewhere they can be moved quickly.",
        "Check for the next update before deciding on further action.",
    ],
    "LOW": [
        "Continue normal farm activities and routine monitoring.",
    ],
}

ASSET_ACTIONS = {
    "livestock": "Move livestock to higher, drier ground.",
    "harvested crops": "Move harvested crops to a raised, covered storage area.",
    "fertilizer": "Cover or relocate fertilizer to prevent water damage and runoff contamination.",
    "seeds": "Move stored seeds to elevated, dry storage.",
    "irrigation equipment": "Disconnect and secure irrigation equipment away from rising water.",
    "machinery": "Move machinery to higher ground, away from drainage channels.",
}

TERRAIN_NOTES = {
    "low-lying": "Your farm's low-lying terrain increases runoff and pooling risk -- act early.",
    "near river/stream": "Proximity to a river/stream means water levels can rise quickly with little warning.",
    "flat": "Flat terrain can still pond water even without fast runoff -- watch drainage.",
    "sloped": "Sloped terrain drains faster, but watch for fast-moving runoff through the farm.",
    "unknown": None,
}


def generate_recommendations(risk_level: str, farm_profile: Optional[dict] = None) -> list[str]:
    """Build a prioritized action list for the given risk level,
    personalized by farm profile (terrain + assets) when available."""
    actions: list[str] = []

    base = BASE_RECOMMENDATIONS.get(risk_level, BASE_RECOMMENDATIONS["LOW"])

    if risk_level in ("HIGH", "CRITICAL") and farm_profile:
        assets = farm_profile.get("assets", []) or []
        # Prioritize by config.ASSET_PRIORITY_ORDER ordering if present
        try:
            import config
            order = config.ASSET_PRIORITY_ORDER
        except Exception:
            order = list(ASSET_ACTIONS.keys())
        ordered_assets = [a for a in order if a in assets] + [a for a in assets if a not in order]
        for asset in ordered_assets:
            if asset in ASSET_ACTIONS:
                actions.append(ASSET_ACTIONS[asset])

        terrain = farm_profile.get("terrain")
        note = TERRAIN_NOTES.get(terrain)
        if note:
            actions.append(note)

        actions.extend([a for a in base if a not in actions])
    else:
        actions.extend(base)

    # Safety net: never recommend dangerous actions, always end on caution
    # for elevated risk levels.
    if risk_level in ("HIGH", "CRITICAL"):
        caution = "Avoid entering floodwater under any circumstances."
        if caution not in actions:
            actions.append(caution)

    return actions


def farm_vulnerability_multiplier(farm_profile: Optional[dict]) -> float:
    """Translate farm terrain into a multiplier applied to environmental
    risk to produce farm-specific risk (see risk_engine.assess_risk)."""
    import config
    if not farm_profile:
        return 1.0
    terrain = farm_profile.get("terrain", "unknown")
    return config.TERRAIN_VULNERABILITY.get(terrain, 1.0)
