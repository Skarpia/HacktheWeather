"""
FlowSafe configuration.

Central place for environment variables, file paths, and TUNABLE
risk-engine parameters. Nothing about variable weights is hard-coded
elsewhere in the app -- everything the risk engine needs lives here so
judges (and you, at 2am) can see and adjust it in one place.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HISTORICAL_DATA_PATH = DATA_DIR / "conduit_march_2026.csv"

# ---------------------------------------------------------------------
# Conduit API
# ---------------------------------------------------------------------
CONDUIT_API_KEY = os.getenv("CONDUIT_API_KEY", "")
CONDUIT_EMAIL = os.getenv("CONDUIT_EMAIL", "")
CONDUIT_API_URL = os.getenv("CONDUIT_API_URL", "https://conduit.jhubafrica.com/data.php")

# How many days of recent live data to pull on each refresh. The live
# endpoint returns a date-range, not a single "current reading", so we
# fetch a small recent window: the last row is used as "current", and
# the whole window is used for trend calculations (rolling_trend).
CONDUIT_LIVE_LOOKBACK_DAYS = int(os.getenv("CONDUIT_LIVE_LOOKBACK_DAYS", "2"))

# When true, the app never calls the live API and instead generates
# clearly-labelled synthetic observations. Flip to false once the
# real Conduit endpoint/auth format has been confirmed against the
# hackathon API docs.
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------
# Location metadata (for display only -- do NOT imply station-level
# accuracy across all of Kiambu)
# ---------------------------------------------------------------------
STATION_NAME = "JKUAT Main Campus Conduit Station"
COVERAGE_LABEL = "Hyperlocal environmental risk monitoring centered around the JKUAT/Juja area"

# ---------------------------------------------------------------------
# Canonical variable names used throughout the app (post data_processor
# normalization). Raw Conduit column names are mapped to these in
# services/data_processor.py -- nothing downstream should reference
# raw column names directly.
# ---------------------------------------------------------------------
CANONICAL_COLUMNS = {
    "timestamp": "timestamp",
    "rainfall": "rainfall_mm",          # incremental rainfall this interval (rg1)
    "rainfall_secondary": "rainfall_mm_2",  # second gauge (rg2), used for cross-check/data quality
    "rain_event_accum": "rain_event_accum_mm",  # rg1tt: accumulation within current rain event
    "temperature": "temperature_c",
    "humidity": "humidity_pct",
    "pressure": "pressure_hpa",
    "wind_speed": "wind_speed",
    "wind_gust": "wind_gust",
    "heat_index": "heat_index_c",
}

# ---------------------------------------------------------------------
# Risk engine: category thresholds (0-100 index)
# ---------------------------------------------------------------------
RISK_THRESHOLDS = {
    "LOW": (0, 29),
    "MODERATE": (30, 59),
    "HIGH": (60, 79),
    "CRITICAL": (80, 100),
}

# ---------------------------------------------------------------------
# Risk engine: variable weights.
#
# These are informed by the actual JKUAT March 2026 dataset (see
# analysis/exploratory_analysis.py): rainfall is overwhelmingly the
# dominant signal for flash-flood risk in this dataset (>97% of
# 15-min readings show zero rainfall, so any real rainfall is already
# a meaningful anomaly), followed by short-term rain-event
# accumulation (a trend proxy) and humidity/pressure as supporting
# context. Soil moisture is NOT available from this station, so it is
# intentionally absent -- the engine only uses weights for variables
# that are actually present in a given observation (see risk_engine.py
# for the re-normalization logic when a variable is missing).
# ---------------------------------------------------------------------
RISK_WEIGHTS = {
    "rainfall_intensity": 0.35,   # current rainfall rate vs baseline
    "rainfall_trend": 0.25,       # rain-event accumulation trend (is it building?)
    "rainfall_anomaly": 0.20,     # z-score / percentile vs historical baseline
    "humidity": 0.10,             # saturated air -> ground already wet / runoff more likely
    "pressure_drop": 0.10,        # falling pressure -> storm approaching
}

# Baseline percentile used to define "unusually high" rainfall
BASELINE_HIGH_PERCENTILE = 95
BASELINE_EXTREME_PERCENTILE = 99

# ---------------------------------------------------------------------
# Farm vulnerability multipliers (applied on top of environmental risk)
# ---------------------------------------------------------------------
TERRAIN_VULNERABILITY = {
    "low-lying": 1.25,
    "near river/stream": 1.30,
    "flat": 1.05,
    "sloped": 0.90,
    "unknown": 1.0,
}

ASSET_PRIORITY_ORDER = [
    "livestock",
    "harvested crops",
    "fertilizer",
    "seeds",
    "irrigation equipment",
    "machinery",
]
