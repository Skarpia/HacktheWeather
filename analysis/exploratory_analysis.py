"""
analysis/exploratory_analysis.py

Standalone script: inspects the historical JKUAT March 2026 dataset
and prints a summary used to justify the risk-engine design choices
in config.py and risk_engine.py. Run directly:

    python analysis/exploratory_analysis.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from services.data_processor import load_historical_dataset, available_canonical_columns
from analysis.baseline import build_baseline


def main():
    import config
    df = load_historical_dataset(config.DATA_DIR)

    print("=" * 70)
    print("FLOWSAFE — JKUAT Conduit Historical Data Inspection")
    print("=" * 70)
    print(f"Rows: {len(df)}")
    print(f"Date range: {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"Available canonical variables: {available_canonical_columns(df)}")
    print()

    print("-- Missing values (raw) --")
    print(df.isna().sum()[df.isna().sum() > 0])
    print()

    print("-- Rainfall behaviour --")
    rainy_pct = (df["rainfall_mm"] > 0).mean() * 100
    print(f"% of 15-min intervals with rainfall > 0: {rainy_pct:.2f}%")
    print(f"Max single-interval rainfall: {df['rainfall_mm'].max()} mm")
    daily = df.set_index("timestamp")["rainfall_mm"].resample("1D").sum()
    print("Daily rainfall totals (mm):")
    print(daily)
    print()
    print("=> Rainfall is heavily zero-inflated: z-scores on raw rainfall_mm")
    print("   are unstable. Anomaly detection uses percentile rank instead")
    print("   (see services/anomaly_detector.py).")
    print()

    print("-- Correlations with rainfall_mm --")
    numeric = df.select_dtypes("number")
    corr = numeric.corr()["rainfall_mm"].sort_values(ascending=False)
    print(corr)
    print()

    print("-- Baseline summary --")
    baseline = build_baseline(df)
    for var, vb in baseline.variables.items():
        print(f"{var:28s} mean={vb.mean:>8} std={vb.std:>8} p95={vb.p95:>8} p99={vb.p99:>8} max={vb.maximum:>8}")

    print()
    print("Conclusion: no soil-moisture sensor is present in this dataset.")
    print("The risk engine intentionally omits soil moisture rather than")
    print("fabricating it, and re-normalizes weights across whichever")
    print("variables are actually available for a given observation.")


if __name__ == "__main__":
    main()
