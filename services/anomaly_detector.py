"""
services/anomaly_detector.py

Compares current Conduit observations against the JKUAT historical
baseline to detect unusual environmental conditions.

Important methodological note (from actually inspecting the March
2026 dataset -- see analysis/exploratory_analysis.py):

Rainfall at this station is heavily zero-inflated -- only ~1.9% of
15-minute intervals show any rain at all, so the mean is close to
zero and the standard deviation is tiny relative to the max. A
z-score on raw rainfall_mm is unstable and misleading (a single 0.2mm
tip can produce a huge, meaningless z-score). So for rainfall we use
PERCENTILE RANK against the historical distribution instead of a
z-score. For roughly-continuous, non-zero-inflated variables
(humidity, pressure, temperature) a z-score is appropriate and used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.baseline import Baseline

# Variables where percentile-based anomaly detection is used instead
# of z-score, because their distributions are zero-inflated / highly
# skewed in this dataset.
PERCENTILE_BASED_VARS = {"rainfall_mm", "rainfall_mm_2", "rain_event_accum_mm", "rain_period_accum_mm"}


@dataclass
class AnomalyResult:
    variable: str
    current_value: float
    baseline_mean: float
    method: str  # "zscore" or "percentile"
    score: float  # z-score OR percentile (0-100), depending on method
    is_unusual: bool
    description: str


def detect_anomalies(observation: dict, baseline: Baseline) -> list[AnomalyResult]:
    """Compare each available variable in `observation` against the
    baseline. Returns only variables that exist in BOTH the
    observation and the baseline -- never fabricates missing ones."""
    results = []

    for var, vb in baseline.variables.items():
        if var not in observation or observation[var] is None:
            continue
        try:
            value = float(observation[var])
        except (TypeError, ValueError):
            continue

        if var in PERCENTILE_BASED_VARS:
            result = _percentile_anomaly(var, value, vb)
        else:
            result = _zscore_anomaly(var, value, vb)
        results.append(result)

    return results


def _zscore_anomaly(var: str, value: float, vb) -> AnomalyResult:
    if vb.std == 0:
        z = 0.0
    else:
        z = (value - vb.mean) / vb.std
    unusual = abs(z) >= 2.0
    direction = "above" if z > 0 else "below"
    desc = (
        f"{_label(var)} is {abs(round(z,1))} standard deviations {direction} "
        f"the recent JKUAT baseline."
        if unusual else
        f"{_label(var)} is within the normal recent range."
    )
    return AnomalyResult(var, value, vb.mean, "zscore", round(z, 2), unusual, desc)


def _percentile_anomaly(var: str, value: float, vb) -> AnomalyResult:
    # Approximate percentile rank using the baseline's stored quantiles.
    if value <= vb.median:
        pct = 50.0 * (value / vb.median) if vb.median > 0 else (0.0 if value == 0 else 90.0)
    elif value <= vb.p90:
        pct = 50 + 40 * ((value - vb.median) / (vb.p90 - vb.median)) if vb.p90 > vb.median else 90.0
    elif value <= vb.p95:
        pct = 90 + 5 * ((value - vb.p90) / (vb.p95 - vb.p90)) if vb.p95 > vb.p90 else 95.0
    elif value <= vb.p99:
        pct = 95 + 4 * ((value - vb.p95) / (vb.p99 - vb.p95)) if vb.p99 > vb.p95 else 99.0
    else:
        pct = 99.5

    unusual = pct >= 95 and value > 0
    desc = (
        f"{_label(var)} ({value}mm) is higher than {round(pct,1)}% of recent "
        f"JKUAT observations -- this is an unusually wet reading for this station."
        if unusual else
        f"{_label(var)} is within the normal recent range for this station."
    )
    return AnomalyResult(var, value, vb.mean, "percentile", round(pct, 1), unusual, desc)


def _label(var: str) -> str:
    labels = {
        "rainfall_mm": "Rainfall intensity",
        "rainfall_mm_2": "Rainfall (secondary gauge)",
        "rain_event_accum_mm": "Rain-event accumulation",
        "rain_period_accum_mm": "Rainfall accumulation",
        "temperature_c": "Temperature",
        "humidity_pct": "Humidity",
        "pressure_hpa": "Atmospheric pressure",
        "wind_speed": "Wind speed",
        "wind_gust": "Wind gust",
        "heat_index_c": "Heat index",
    }
    return labels.get(var, var.replace("_", " ").title())
