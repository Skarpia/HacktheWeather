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

Confirmed real response shape:
    {"status": "success", "headers": [...], "data": [[...], [...]]}
i.e. "data" is a list of ROWS (positional arrays) matched against
"headers" -- not a list of field-named objects.

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


def get_current_observation() -> dict:
    """Return the latest observation as a normalized dict, plus a
    small recent-history dataframe (for trend calcs), plus metadata
    about whether it's live or mock data.
    """
    if config.MOCK_MODE:
        return _mock_observation()

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

    Confirmed real shape:
        {"status": "success", "headers": [...], "data": [[...], [...]]}
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
                records.append(row)
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
        if all(not isinstance(v, (list, dict)) for v in parsed.values()):
            return [parsed]
    raise ConduitAPIError(
        f"Unrecognized Conduit API response shape: {type(parsed)}. "
        f"Sample: {str(parsed)[:300]}. Update _extract_records() in "
        f"services/conduit_api.py to match the real shape."
    )


def _mock_observation(level: Optional[str] = None) -> dict:
    """Generate a clearly-labelled synthetic observation (and a small
    synthetic recent-history window) for demo purposes."""
    level = level or random.choice(["LOW", "LOW", "LOW", "MODERATE", "HIGH", "CRITICAL"])

    profiles = {
        "LOW":      dict(rainfall_mm=0.0, rain_event_accum_mm=0.0, humidity_pct=75.0, pressure_hpa=848.0),
        "MODERATE": dict(rainfall_mm=1.0, rain_event_accum_mm=8.0, humidity_pct=88.0, pressure_hpa=847.0),
        "HIGH":     dict(rainfall_mm=4.0, rain_event_accum_mm=25.0, humidity_pct=94.0, pressure_hpa=845.0),
        "CRITICAL": dict(rainfall_mm=12.0, rain_event_accum_mm=55.0, humidity_pct=97.0, pressure_hpa=841.0),
    }
    base = profiles[level]
    jitter = lambda v, pct=0.1: round(v * (1 + random.uniform(-pct, pct)), 2) if v else v

    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for i in range(8, 0, -1):
        frac = (8 - i) / 8
        rows.append({
            "timestamp": now - pd.Timedelta(minutes=15 * i),
            "rainfall_mm": jitter(base["rainfall_mm"] * frac) if base["rainfall_mm"] else 0.0,
            "rain_event_accum_mm": round(base["rain_event_accum_mm"] * frac, 2),
            "temperature_c": round(random.uniform(17, 24), 1),
            "humidity_pct": round(base["humidity_pct"] * frac + 75 * (1 - frac), 1),
            "pressure_hpa": round(848 - (848 - base["pressure_hpa"]) * frac, 1),
            "wind_speed": round(random.uniform(0.0, 1.5), 1),
            "wind_gust": round(random.uniform(0.0, 2.5), 1),
            "heat_index_c": round(random.uniform(17, 25), 1),
        })
    recent_df = pd.DataFrame(rows)
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