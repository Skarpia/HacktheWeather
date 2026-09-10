"""
analysis/baseline.py

Builds the local JKUAT environmental baseline from the historical
March 2026 Conduit dataset. This is the reference point everything
else (anomaly detection, risk scoring) compares live readings against.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.data_processor import load_historical_dataset, available_canonical_columns
import config


@dataclass
class VariableBaseline:
    variable: str
    mean: float
    median: float
    std: float
    minimum: float
    maximum: float
    p90: float
    p95: float
    p99: float
    n_observations: int


@dataclass
class Baseline:
    station: str
    period_start: str
    period_end: str
    n_days: float
    variables: dict = field(default_factory=dict)
    rainy_interval_pct: float = 0.0  # % of 15-min intervals with any rainfall
    max_daily_rainfall_mm: float = 0.0
    max_single_interval_rainfall_mm: float = 0.0

    def get(self, variable: str) -> Optional[VariableBaseline]:
        return self.variables.get(variable)

    def summary_dict(self) -> dict:
        return {
            "station": self.station,
            "period": f"{self.period_start} to {self.period_end}",
            "n_days": round(self.n_days, 1),
            "rainy_interval_pct": round(self.rainy_interval_pct, 2),
            "max_daily_rainfall_mm": self.max_daily_rainfall_mm,
            "max_single_interval_rainfall_mm": self.max_single_interval_rainfall_mm,
            "variables": {
                k: {
                    "mean": v.mean, "median": v.median, "std": v.std,
                    "min": v.minimum, "max": v.maximum,
                    "p90": v.p90, "p95": v.p95, "p99": v.p99,
                }
                for k, v in self.variables.items()
            },
        }


def build_baseline(df: Optional[pd.DataFrame] = None) -> Baseline:
    """Compute the JKUAT local baseline from historical observations.

    Only computes statistics for variables actually present in the
    dataset -- nothing is assumed or fabricated.
    """
    if df is None:
        df = load_historical_dataset(config.DATA_DIR)

    variables = {}
    for col in available_canonical_columns(df):
        series = df[col].dropna()
        if series.empty:
            continue
        variables[col] = VariableBaseline(
            variable=col,
            mean=round(float(series.mean()), 4),
            median=round(float(series.median()), 4),
            std=round(float(series.std(ddof=0)), 4),
            minimum=round(float(series.min()), 4),
            maximum=round(float(series.max()), 4),
            p90=round(float(series.quantile(0.90)), 4),
            p95=round(float(series.quantile(0.95)), 4),
            p99=round(float(series.quantile(0.99)), 4),
            n_observations=int(series.count()),
        )

    period_start = df["timestamp"].min()
    period_end = df["timestamp"].max()
    n_days = (period_end - period_start).total_seconds() / 86400 if pd.notna(period_start) else 0

    rainy_pct = 0.0
    max_daily = 0.0
    max_interval = 0.0
    if "rainfall_mm" in df.columns:
        rainy_pct = float((df["rainfall_mm"] > 0).mean() * 100)
        max_interval = float(df["rainfall_mm"].max())
        daily = df.set_index("timestamp")["rainfall_mm"].resample("1D").sum()
        max_daily = float(daily.max()) if not daily.empty else 0.0

    return Baseline(
        station=config.STATION_NAME,
        period_start=str(period_start),
        period_end=str(period_end),
        n_days=n_days,
        variables=variables,
        rainy_interval_pct=rainy_pct,
        max_daily_rainfall_mm=round(max_daily, 2),
        max_single_interval_rainfall_mm=round(max_interval, 2),
    )


if __name__ == "__main__":
    b = build_baseline()
    import json
    print(json.dumps(b.summary_dict(), indent=2, default=str))
