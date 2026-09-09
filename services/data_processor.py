"""
services/data_processor.py

Normalizes raw Conduit observations (from the historical CSV or the
live API) into a consistent canonical schema so the rest of the app
never has to think about raw column names.

Design principle: if a variable is not present in the raw data, it is
simply absent from the normalized output -- we never fabricate it.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional

# Map of RAW Conduit column name -> canonical name.
# Only columns we actually understand and use are mapped; unmapped
# columns are preserved under their original name (not dropped) so
# nothing is silently lost, but the risk engine only looks at
# canonical fields.
RAW_TO_CANONICAL = {
    "ts": "timestamp",
    "rg1": "rainfall_mm",
    "rg2": "rainfall_mm_2",
    "rg1tt": "rain_event_accum_mm",
    "rg2tt": "rain_event_accum_mm_2",
    "rg1tp": "rain_period_accum_mm",
    "rg2tp": "rain_period_accum_mm_2",
    "temp_bmx": "temperature_c",
    "temp_mcp": "temperature_c_alt1",
    "temp_sht": "temperature_c_alt2",
    "humidity_sht": "humidity_pct",
    "press_bmx": "pressure_hpa",
    "wind_spd": "wind_speed",
    "wind_dir": "wind_dir",
    "wind_gust": "wind_gust",
    "wind_gust_dir": "wind_gust_dir",
    "heat_idx": "heat_index_c",
    "wet_bulb_temp": "wet_bulb_temp_c",
    "wet_bulb_globe_temp": "wet_bulb_globe_temp_c",
    # si1145_* (light/UV sensor) intentionally not mapped -- not
    # relevant to flash-flood risk.
}

# Plausible physical ranges used for basic validity checks.
# Anything outside these bounds is flagged, not silently kept.
VALID_RANGES = {
    "rainfall_mm": (0, 200),          # mm per 15-min interval
    "temperature_c": (-10, 55),
    "humidity_pct": (0, 100),
    "pressure_hpa": (800, 1100),
    "wind_speed": (0, 60),
}


def load_historical_csv(path: str) -> pd.DataFrame:
    """Load the raw historical Conduit CSV without assuming column names
    beyond what's actually present."""
    df = pd.read_csv(path)
    return normalize_observations(df)


def normalize_observations(df: pd.DataFrame) -> pd.DataFrame:
    """Rename known raw columns to canonical names, parse timestamps,
    coerce numerics, and flag invalid values. Unknown columns are kept
    as-is (not used by downstream logic, but not discarded either).
    """
    df = df.copy()

    rename_map = {k: v for k, v in RAW_TO_CANONICAL.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    numeric_cols = [c for c in df.columns if c != "timestamp"]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Flag (not drop) out-of-range values so data-quality reporting can
    # surface them; the risk engine treats flagged values as missing.
    for col, (lo, hi) in VALID_RANGES.items():
        if col in df.columns:
            invalid = ~df[col].between(lo, hi) & df[col].notna()
            if invalid.any():
                df.loc[invalid, col] = np.nan

    return df


def available_canonical_columns(df: pd.DataFrame) -> list[str]:
    """Which canonical variables actually exist (non-null somewhere) in
    this dataframe. Used to dynamically decide what the risk engine can
    use, rather than assuming a fixed schema."""
    candidates = [
        "rainfall_mm", "rainfall_mm_2", "rain_event_accum_mm",
        "rain_period_accum_mm", "temperature_c", "humidity_pct",
        "pressure_hpa", "wind_speed", "wind_gust", "heat_index_c",
    ]
    return [c for c in candidates if c in df.columns and df[c].notna().any()]


def latest_observation(df: pd.DataFrame) -> Optional[dict]:
    """Return the most recent normalized observation as a plain dict,
    or None if the dataframe is empty."""
    if df.empty:
        return None
    row = df.sort_values("timestamp").iloc[-1]
    return row.to_dict()


def data_quality_score(observation: dict, expected_fields: list[str]) -> float:
    """Simple completeness-based data-quality score (0-100). This
    measures how much of the expected data is present and valid for
    THIS observation -- it is NOT a flood probability."""
    if not expected_fields:
        return 0.0
    present = sum(
        1 for f in expected_fields
        if f in observation and observation[f] is not None and not _is_nan(observation[f])
    )
    return round(100 * present / len(expected_fields), 1)


def _is_nan(v) -> bool:
    try:
        return bool(np.isnan(v))
    except (TypeError, ValueError):
        return False


def rolling_trend(df: pd.DataFrame, column: str, window: int = 4) -> Optional[float]:
    """Simple trend indicator: difference between the mean of the last
    `window` readings and the previous `window` readings for a given
    column. Positive = increasing. Returns None if not enough data or
    column missing."""
    if column not in df.columns:
        return None
    series = df[column].dropna()
    if len(series) < window * 2:
        return None
    recent = series.iloc[-window:].mean()
    prior = series.iloc[-2 * window:-window].mean()
    return round(float(recent - prior), 4)
