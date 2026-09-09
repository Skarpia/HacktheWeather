"""
services/test_conduit_connection.py

Standalone diagnostic script -- run this LOCALLY (not in any sandbox)
with your real CONDUIT_API_KEY and CONDUIT_EMAIL set in .env, BEFORE
your demo, to confirm:

  1. The API call succeeds (network + auth are correct).
  2. What the raw JSON response actually looks like.
  3. Whether services/conduit_api.py's _extract_records() parses it
     correctly out of the box.

Usage:
    python services/test_conduit_connection.py
    python services/test_conduit_connection.py 2026-03-06 2026-03-07
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.conduit_api import _fetch_range, _extract_records, ConduitAPIError
import requests


def main():
    if len(sys.argv) == 3:
        fromdate, todate = sys.argv[1], sys.argv[2]
    else:
        # default: today only, adjust if your station reports with a delay
        import datetime
        today = datetime.date.today().isoformat()
        fromdate, todate = today, today

    print("=" * 70)
    print("FlowSafe — Conduit API connection test")
    print("=" * 70)
    print(f"URL:      {config.CONDUIT_API_URL}")
    print(f"API key:  {'set (' + config.CONDUIT_API_KEY[:4] + '...)' if config.CONDUIT_API_KEY else 'MISSING'}")
    print(f"Email:    {config.CONDUIT_EMAIL or 'MISSING'}")
    print(f"Range:    {fromdate} to {todate}")
    print()

    if not config.CONDUIT_API_KEY or not config.CONDUIT_EMAIL:
        print("!! CONDUIT_API_KEY or CONDUIT_EMAIL is not set in your .env file.")
        print("   Copy .env.example to .env and fill them in, then re-run this script.")
        return

    payload = {
        "apikey": config.CONDUIT_API_KEY,
        "email": config.CONDUIT_EMAIL,
        "fromdate": fromdate,
        "todate": todate,
    }

    try:
        resp = requests.post(config.CONDUIT_API_URL, data=payload, timeout=15)
    except requests.RequestException as e:
        print(f"!! Network request failed: {e}")
        return

    print(f"HTTP status: {resp.status_code}")
    print()
    print("-- Raw response (first 1000 chars) --")
    print(resp.text[:1000])
    print()

    try:
        parsed = resp.json()
    except ValueError:
        print("!! Response is not valid JSON. Check the raw text above -- it may be")
        print("   an HTML error page (wrong URL/params) or a PHP error/warning.")
        return

    print("-- Parsed JSON type --")
    print(type(parsed))
    if isinstance(parsed, dict):
        print("Top-level keys:", list(parsed.keys()))
    elif isinstance(parsed, list):
        print(f"List with {len(parsed)} items.")
        if parsed:
            print("First item keys:", list(parsed[0].keys()) if isinstance(parsed[0], dict) else parsed[0])
    print()

    try:
        records = _extract_records(parsed)
        print(f"✅ _extract_records() successfully found {len(records)} record(s).")
        if records:
            print("Sample record:")
            print(json.dumps(records[0], indent=2, default=str))
            fields = set(records[0].keys())
            expected = {"ts", "rg1", "rg2", "temp_bmx", "humidity_sht", "press_bmx"}
            missing = expected - fields
            if missing:
                print()
                print(f"⚠️  Field names differ from the historical CSV. Missing expected: {missing}")
                print(f"   Actual fields present: {sorted(fields)}")
                print("   -> Update RAW_TO_CANONICAL in services/data_processor.py to match.")
            else:
                print()
                print("✅ Field names match the historical CSV column names -- no changes needed.")
    except ConduitAPIError as e:
        print(f"!! Could not extract records automatically: {e}")
        print("   Look at the raw JSON structure above and update _extract_records()")
        print("   in services/conduit_api.py to match it.")


if __name__ == "__main__":
    main()
