"""
services/risk_engine.py

Combines current conditions, the JKUAT historical baseline, short-term
trend, and anomaly detection into an explainable 0-100 Flash-Flood
Risk Index.

This is a transparent, rule-based / weighted-scoring engine -- NOT a
black box, and NOT a calibrated flood probability. See config.py for
weights and analysis/exploratory_analysis.py for why they were chosen.
"""

from __future__ import annotations

from typing import Optional

import config
from analysis.baseline import Baseline
from services.anomaly_detector import detect_anomalies, AnomalyResult
from services.data_processor import rolling_trend, data_quality_score


def _risk_level(score: float) -> str:
    for level, (lo, hi) in config.RISK_THRESHOLDS.items():
        if lo <= score <= hi:
            return level
    return "CRITICAL" if score > 100 else "LOW"


def _score_rainfall_intensity(observation: dict, baseline: Baseline) -> Optional[float]:
    """0-100 sub-score for how intense current rainfall is vs baseline."""
    vb = baseline.get("rainfall_mm")
    if vb is None or "rainfall_mm" not in observation or observation["rainfall_mm"] is None:
        return None
    value = float(observation["rainfall_mm"])
    if value <= 0:
        return 0.0
    if vb.p99 <= 0:
        # Baseline has essentially no rain history -- any rain is already extreme.
        return 100.0
    # Scale: baseline p95 -> 60, baseline p99 -> 85, beyond p99 -> up to 100
    if value <= vb.p95:
        return round(60 * (value / vb.p95), 1) if vb.p95 > 0 else 60.0
    if value <= vb.p99:
        return round(60 + 25 * ((value - vb.p95) / (vb.p99 - vb.p95)), 1) if vb.p99 > vb.p95 else 85.0
    excess = min((value - vb.p99) / max(vb.p99, 0.1), 1.0)
    return round(85 + 15 * excess, 1)


def _score_rainfall_trend(df, observation: dict) -> Optional[float]:
    """0-100 sub-score for whether rain-event accumulation is building."""
    if df is None:
        return None
    trend = rolling_trend(df, "rain_event_accum_mm", window=4)
    if trend is None:
        return None
    if trend <= 0:
        return 0.0
    # A sustained increase of >=5mm across the trend window is treated as strong.
    return round(min(100.0, (trend / 5.0) * 100), 1)


def _score_anomaly(anomalies: list[AnomalyResult]) -> Optional[float]:
    rain_anoms = [a for a in anomalies if a.variable in ("rainfall_mm", "rain_event_accum_mm", "rain_period_accum_mm")]
    if not rain_anoms:
        return None
    scores = []
    for a in rain_anoms:
        if a.method == "percentile":
            scores.append(max(0.0, (a.score - 50) / 50 * 100))
        else:
            scores.append(max(0.0, min(100.0, (a.score / 3.0) * 100)))
    return round(sum(scores) / len(scores), 1) if scores else None


def _score_humidity(observation: dict, baseline: Baseline) -> Optional[float]:
    vb = baseline.get("humidity_pct")
    if vb is None or observation.get("humidity_pct") is None:
        return None
    value = float(observation["humidity_pct"])
    # Ground/air already saturated -> less capacity to absorb further rain.
    if value >= 95:
        return 100.0
    if value <= vb.median:
        return 0.0
    return round(100 * (value - vb.median) / (95 - vb.median), 1) if vb.median < 95 else 50.0


def _score_pressure_drop(df, baseline: Baseline) -> Optional[float]:
    if df is None:
        return None
    trend = rolling_trend(df, "pressure_hpa", window=4)
    vb = baseline.get("pressure_hpa")
    if trend is None or vb is None or vb.std == 0:
        return None
    if trend >= 0:
        return 0.0
    drop_z = abs(trend) / vb.std
    return round(min(100.0, drop_z * 40), 1)


def assess_risk(observation: dict, baseline: Baseline, history_df=None,
                 farm_vulnerability_multiplier: float = 1.0) -> dict:
    """Compute the Flash-Flood Risk Index for a single observation.

    Parameters
    ----------
    observation : dict
        A single normalized observation (see data_processor.normalize_observations).
    baseline : Baseline
        Precomputed JKUAT historical baseline.
    history_df : DataFrame, optional
        Recent observation history, used for trend calculation. If not
        provided, trend-based sub-scores are simply skipped (not
        fabricated).
    farm_vulnerability_multiplier : float
        Multiplier from farm profile (terrain etc.) applied to the
        environmental risk score to produce farm-specific risk.
    """
    anomalies = detect_anomalies(observation, baseline)

    sub_scores = {
        "rainfall_intensity": _score_rainfall_intensity(observation, baseline),
        "rainfall_trend": _score_rainfall_trend(history_df, observation),
        "rainfall_anomaly": _score_anomaly(anomalies),
        "humidity": _score_humidity(observation, baseline),
        "pressure_drop": _score_pressure_drop(history_df, baseline),
    }

    # Re-normalize weights over only the sub-scores we could actually
    # compute -- never assign weight to a variable we don't have.
    available = {k: v for k, v in sub_scores.items() if v is not None}
    total_weight = sum(config.RISK_WEIGHTS[k] for k in available)

    if total_weight == 0:
        environmental_score = 0.0
    else:
        environmental_score = sum(
            (config.RISK_WEIGHTS[k] / total_weight) * v for k, v in available.items()
        )

    farm_score = min(100.0, environmental_score * farm_vulnerability_multiplier)
    risk_level = _risk_level(farm_score)

    risk_factors = _build_risk_factors(observation, anomalies, sub_scores)

    expected_fields = list(config.RISK_WEIGHTS.keys())
    dq = data_quality_score(
        {
            "rainfall_intensity": sub_scores["rainfall_intensity"],
            "rainfall_trend": sub_scores["rainfall_trend"],
            "rainfall_anomaly": sub_scores["rainfall_anomaly"],
            "humidity": sub_scores["humidity"],
            "pressure_drop": sub_scores["pressure_drop"],
        },
        expected_fields,
    )

    return {
        "risk_score": round(farm_score, 1),
        "environmental_score": round(environmental_score, 1),
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "sub_scores": sub_scores,
        "anomalies": [a.__dict__ for a in anomalies],
        "data_quality": {
            "completeness_pct": dq,
            "variables_used": list(available.keys()),
            "variables_unavailable": [k for k in config.RISK_WEIGHTS if k not in available],
        },
    }


def _build_risk_factors(observation: dict, anomalies: list[AnomalyResult], sub_scores: dict) -> list[str]:
    factors = []

    for a in anomalies:
        if a.is_unusual:
            factors.append(a.description)

    if sub_scores.get("rainfall_trend") and sub_scores["rainfall_trend"] > 40:
        factors.append("Rainfall accumulation is actively increasing over the recent readings.")

    if sub_scores.get("humidity") and sub_scores["humidity"] > 70:
        factors.append("Air/ground moisture is elevated, reducing capacity to absorb further rainfall.")

    if sub_scores.get("pressure_drop") and sub_scores["pressure_drop"] > 40:
        factors.append("Atmospheric pressure is dropping, consistent with an approaching storm system.")

    if not factors:
        factors.append("Current conditions are consistent with the recent JKUAT baseline; no significant anomalies detected.")

    return factors
