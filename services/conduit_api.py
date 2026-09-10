"""
services/conduit_api.py

Adapter for the real Conduit weather station API
(https://conduit.jhubafrica.com/data.php), confirmed from the
hackathon's official docs:

    POST https://conduit.jhubafrica.com/data.php
    form fields: apikey, email, fromdate (YYYY-MM-DD), todate (YYYY-MM-DD)
    -> JSON response covering that date range

This is a DATE-RANGE endpoint, not a single "give me the current
reading" endpoint. So "live" observation means: request a small
recent window (today, or today+yesterday), take the most recent row
as "current", and use the whole window to compute short-term trends
(rain-event accumulation trend, pressure trend) the same way the
historical baseline pipeline does.

IMPORTANT -- response shape is not 100% confirmed from the docs alone
(the PHP example just does json_decode($response, true) and dumps it).
This adapter tries several common shapes defensively:
  - a bare JSON list of observation objects
  - {"data": [...]}
  - {"records": [...]}
  - {"result": [...]}
If none match, the raw response is surfaced in the error so you can
see exactly what came back and adjust `_extract_records()` below.

Run `python services/test_conduit_connection.py` locally (with real
credentials in .env) BEFORE the live demo to confirm this works --
this sandbox cannot reach conduit.jhubafrica.com to test it for you.

MOCK_MODE=true bypasses all of this and returns clearly-labelled
synthetic data.
"""

from __future__ import annotations

import random
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

import config
from services.data_processor import normalize_observations


class ConduitAPIError(Exception):
    pass


def get_current_observation(baseline=None) -> dict:
    """Return the latest observation as a normalized dict, plus a
    small recent-history dataframe (for trend calcs), plus metadata
    about whether it's live or mock data.

    `baseline` (analysis.baseline.Baseline, optional) is used to scale
    mock-mode rainfall magnitudes realistically -- see _mock_observation.

    Returns
    -------
    dict with keys:
      "observation" (normalized dict or None),
      "recent_df" (DataFrame or None) -- recent window for trend calcs,
      "is_mock" (bool),
      "fetched_at" (iso timestamp),
      "status" ("ok" | "error"),
      "error" (str, only if status == "error")
    """
    if config.MOCK_MODE:
        return _mock_observation(baseline=baseline)

    if not config.CONDUIT_API_KEY or not config.CONDUIT_EMAIL:
        return {
            "observation": None,
            "recent_df": None,
            "is_mock": False,
            "fetched_at": _now_iso(),
            "status": "error",
            "error": "CONDUIT_API_KEY or CONDUIT_EMAIL not configured. Set MOCK_MODE=true to demo without live API access.",
        }

    todate = datetime.now(timezone.utc).date()
    fromdate = todate - timedelta(days=config.CONDUIT_LIVE_LOOKBACK_DAYS)

    try:
        raw_records = _fetch_range(str(fromdate), str(todate))
        if not raw_records:
            return {
                "observation": None,
                "recent_df": None,
                "is_mock": False,
                "fetched_at": _now_iso(),
                "status": "error",
                "error": f"Conduit API returned no records for {fromdate} to {todate}.",
            }
        df = normalize_observations(pd.DataFrame(raw_records))
        if df.empty or "timestamp" not in df.columns:
            return {
                "observation": None,
                "recent_df": None,
                "is_mock": False,
                "fetched_at": _now_iso(),
                "status": "error",
                "error": f"Conduit API response could not be parsed into observations. Raw sample: {raw_records[:1]}",
            }
        df = df.sort_values("timestamp")
        latest = df.iloc[-1].to_dict()
        return {
            "observation": latest,
            "recent_df": df,
            "is_mock": False,
            "fetched_at": _now_iso(),
            "status": "ok",
        }
    except ConduitAPIError as e:
        return {
            "observation": None,
            "recent_df": None,
            "is_mock": False,
            "fetched_at": _now_iso(),
            "status": "error",
            "error": str(e),
        }


def _fetch_range(fromdate: str, todate: str) -> list[dict]:
    """POST to the Conduit API for a date range and return a list of
    raw observation records (dicts). Raises ConduitAPIError on any
    failure."""
    payload = {
        "apikey": config.CONDUIT_API_KEY,
        "email": config.CONDUIT_EMAIL,
        "fromdate": fromdate,
        "todate": todate,
    }
    try:
        resp = requests.post(config.CONDUIT_API_URL, data=payload, timeout=15)
    except requests.RequestException as e:
        raise ConduitAPIError(f"Conduit API request failed: {e}") from e

    if resp.status_code != 200:
        raise ConduitAPIError(f"Conduit API returned HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        parsed = resp.json()
    except ValueError as e:
        raise ConduitAPIError(
            f"Conduit API returned non-JSON response (first 300 chars): {resp.text[:300]}"
        ) from e

    return _extract_records(parsed)


def _extract_records(parsed) -> list[dict]:
    """Defensively pull a list of observation dicts out of whatever
    shape the API actually returns.

    Confirmed real shape (from services/test_conduit_connection.py):
        {"status": "success", "headers": [...], "data": [[...], [...]]}
    i.e. "data" is a list of ROWS (positional arrays), not a list of
    field-named objects -- each row must be zipped with "headers" to
    become a dict. This is handled first; the other shapes below are
    kept as fallbacks in case the API changes.
    """
    if isinstance(parsed, dict) and "headers" in parsed and "data" in parsed:
        headers = parsed["headers"]
        rows = parsed["data"]
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise ConduitAPIError(
                f"Conduit API 'headers'/'data' were not both lists. "
                f"headers={type(headers)}, data={type(rows)}"
            )
        records = []
        for row in rows:
            if isinstance(row, dict):
                records.append(row)  # already keyed, just in case
            elif isinstance(row, (list, tuple)):
                records.append(dict(zip(headers, row)))
            else:
                continue
        return records

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("data", "records", "result", "results", "observations"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        # Some APIs wrap a single-record response as a dict itself.
        if all(not isinstance(v, (list, dict)) for v in parsed.values()):
            return [parsed]
    raise ConduitAPIError(
        f"Unrecognized Conduit API response shape: {type(parsed)}. "
        f"Sample: {str(parsed)[:300]}. Update _extract_records() in "
        f"services/conduit_api.py to match the real shape."
    )


def _build_mock_window(severity: float, baseline, ceilings: dict) -> pd.DataFrame:
    """Build an 8-point recent-history window for a given severity
    (0.0-1.0) and set of magnitude ceilings. severity=0 -> calm/dry,
    severity=1 -> the most extreme conditions we'll ever synthesize."""
    rain_ceiling = ceilings["rain_ceiling"]
    accum_ceiling = ceilings["accum_ceiling"]

    rainfall_mm = round(severity * rain_ceiling, 3)
    accum_target = severity * accum_ceiling
    # Trend "ramp" also scales with severity, so higher severity = a
    # more visibly building trend, without ever fully saturating.
    ramp_fraction = min(0.75, 0.15 + severity * 0.5)
    humidity_pct = 72 + severity * 25       # 72% (dry) -> 97% (saturated)
    pressure_hpa = 848 - severity * 7        # 848 (calm) -> 841 (storm)

    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for i in range(8, 0, -1):
        frac = (8 - i) / 8  # 0 -> 1 across the window
        accum_start = accum_target * (1 - ramp_fraction)
        accum_now = accum_start + (accum_target - accum_start) * frac
        rows.append({
            "timestamp": now - pd.Timedelta(minutes=15 * i),
            "rainfall_mm": round(rainfall_mm * (1 + random.uniform(-0.05, 0.05)), 3) if rainfall_mm else 0.0,
            "rain_event_accum_mm": round(accum_now, 2),
            "temperature_c": round(random.uniform(17, 24), 1),
            "humidity_pct": round(humidity_pct * (1 + random.uniform(-0.01, 0.01)), 1),
            "pressure_hpa": round(848 - (848 - pressure_hpa) * frac, 1),
            "wind_speed": round(random.uniform(0.0, 1.5), 1),
            "wind_gust": round(random.uniform(0.0, 2.5), 1),
            "heat_index_c": round(random.uniform(17, 25), 1),
        })
    return pd.DataFrame(rows)


def _mock_observation(level: Optional[str] = None, baseline=None, farm_multiplier: float = 1.0) -> dict:
    """Generate a clearly-labelled synthetic observation (and a small
    synthetic recent-history window) for demo purposes.

    Rather than hand-tuning fixed mm values (which turned out to be
    very wrong for this dataset -- see git history), this SEARCHES for
    a severity level that actually produces a farm-specific risk score
    landing inside the requested band, using the real risk engine
    against the real baseline. This makes the "force a scenario" demo
    control self-calibrating: it keeps working correctly even as the
    baseline changes (e.g. when more historical datasets are added to
    data/), and it accounts for the current farm's vulnerability
    multiplier so the FINAL displayed risk level actually matches the
    level you picked.
    """
    level = level or random.choice(["LOW", "LOW", "LOW", "MODERATE", "HIGH", "CRITICAL"])

    # Magnitude ceilings scale off the real baseline where available,
    # so "extreme" always means extreme relative to THIS station's
    # history, not an arbitrary fixed mm value.
    rain_ceiling, accum_ceiling = 3.0, 80.0
    if baseline is not None:
        vb_rain = baseline.get("rainfall_mm")
        vb_accum = baseline.get("rain_event_accum_mm")
        if vb_rain:
            rain_ceiling = max(vb_rain.maximum, vb_rain.p99) * 6
        if vb_accum:
            accum_ceiling = max(vb_accum.maximum, vb_accum.p99) * 1.3
    ceilings = {"rain_ceiling": rain_ceiling, "accum_ceiling": accum_ceiling}

    if level == "LOW" or baseline is None:
        severity = 0.0
    else:
        # Binary-search severity (0-1) so the resulting FARM-SPECIFIC
        # score lands near the middle of the requested band.
        from services.risk_engine import assess_risk
        lo_b, hi_b = config.RISK_THRESHOLDS[level]
        target = (lo_b + hi_b) / 2

        lo, hi = 0.0, 1.0
        severity = 0.5
        for _ in range(14):
            severity = (lo + hi) / 2
            window = _build_mock_window(severity, baseline, ceilings)
            obs = window.iloc[-1].to_dict()
            r = assess_risk(obs, baseline, history_df=window, farm_vulnerability_multiplier=farm_multiplier)
            if r["risk_score"] < target:
                lo = severity
            else:
                hi = severity

    recent_df = _build_mock_window(severity, baseline, ceilings)
    obs = recent_df.iloc[-1].to_dict()

    return {
        "observation": obs,
        "recent_df": recent_df,
        "is_mock": True,
        "mock_level_hint": level,
        "fetched_at": _now_iso(),
        "status": "ok",
        "label": "DEMO DATA \u2014 NOT LIVE CONDUIT OBSERVATIONS",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
