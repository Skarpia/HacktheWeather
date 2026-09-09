# HacktheWeather
JHUB AFRICA Hackathon
# FLOWSAFE 🌊

Hyperlocal Flash-Flood Risk & Early Warning System for Farmers

*From weather data to farm-saving decisions.*

Built for Hack the Weather.
 1. Problem

Smallholder farmers often receive generic weather reports ("heavy rainfall expected") that don't answer the questions that actually matter to them:

- Is my farm currently at elevated flash-flood risk?
- Are current conditions unusual compared to what's normal here?
- Why is the risk elevated?
- What should I do right now, in what order?

FlowSafe closes that gap by converting raw station telemetry into a farm-specific, explainable, actionable warning.

 2. Target users

Smallholder farmers and agricultural extension officers in the JKUAT–Juja–Kiambu area.

 3. Geographic scope

The system is centered on the JKUAT Main Campus Conduit weather station. It is described honestly as:

  > "Hyperlocal environmental risk monitoring centered around the JKUAT/Juja area."

It does not claim to precisely measure conditions at every farm across Kiambu County — a single station is a local reference point, not a county-wide sensor network. Scaling to full county coverage is discussed under Future Work.

 4. Solution

```
REAL-TIME ENVIRONMENTAL DATA
        ↓
LOCAL BASELINE COMPARISON (JKUAT, 6–24 March 2026)
        ↓
ANOMALY / RISK ANALYSIS
        ↓
FARM-SPECIFIC WARNING (0–100 index, explained)
        ↓
PRIORITIZED ACTIONS
```

FlowSafe is a decision-support / early-warning tool, not a flood predictor. It never claims certainty ("the flood will happen") — only relative risk based on how current conditions compare to the recent local baseline.

 5. Data sources

| Source | What it provides |

| Historical Conduit CSV** (`data/conduit_march_2026.csv`) | 1,805 fifteen-minute observations, 6–24 March 2026, JKUAT station. Used to build the local baseline. |
| **Live Conduit API** | Current observations (adapter in `services/conduit_api.py`); falls back to `MOCK_MODE` when unavailable. |

 6. Historical dataset — what's actually in it

The dataset was inspected before any variable was assumed (`analysis/exploratory_analysis.py`). Available fields, mapped to canonical names in `services/data_processor.py`:

- `rainfall_mm`, `rainfall_mm_2` — two independent rain gauges (mm per 15-min interval)
- `rain_event_accum_mm` — accumulation within the current rain event
- `rain_period_accum_mm` — longer-window rainfall accumulation
- `temperature_c` (+ two secondary temperature sensors)
- `humidity_pct`
- `pressure_hpa`
- `wind_speed`, `wind_gust`
- `heat_index_c`, wet-bulb temperature/globe temperature

No soil moisture sensor exists at this station. The risk engine does not fabricate it — it only uses variables that are actually present in a given observation, and re-normalizes its weights across whatever is available (see §11).

Key finding: rainfall at this station is heavily. zero-inflated — only ~1.9% of 15-minute intervals in the historical window show any rain at all. This is why anomaly detection uses **percentile rank** for rainfall variables instead of a z-score (a z-score is unstable when the mean is near-zero and the distribution is a spike-at-zero).

 7. Conduit API integration

`services/conduit_api.py` isolates all API-specific logic and matches the confirmed hackathon API contract:

```
POST https://conduit.jhubafrica.com/data.php
form-encoded body: apikey, email, fromdate (YYYY-MM-DD), todate (YYYY-MM-DD)
-> JSON response covering that date range
```

This is a **date-range** endpoint, not a single "current reading" endpoint. FlowSafe treats "live" as: request the last `CONDUIT_LIVE_LOOKBACK_DAYS` days (default 2), take the most recent row as the current observation, and use the whole window for short-term trend calculations (same trend logic used on the historical baseline).

Credentials (`CONDUIT_API_KEY`, `CONDUIT_EMAIL`) are read from environment variables only — never hard-coded, never logged, never sent anywhere except the Conduit endpoint itself.

**Response shape caveat:** the hackathon docs show the PHP example just doing `json_decode()` and dumping the result, so the exact JSON structure (bare list vs. `{"data": [...]}` vs. something else) isn't fully confirmed. `_extract_records()` in `conduit_api.py` handles several common shapes defensively and raises a clear, inspectable error if none match.

**Before your demo:** run `python services/test_conduit_connection.py` locally with real credentials in `.env`. It prints the raw response, tells you whether parsing succeeded, and tells you exactly what to change in `data_processor.py`'s `RAW_TO_CANONICAL` map if the live field names differ from the historical CSV's (`ts`, `rg1`, `temp_bmx`, etc.). This sandbox could not run that test itself — `conduit.jhubafrica.com` is outside its network allowlist.

If the live call fails for any reason at demo time, the dashboard does not crash: it shows a connection-status banner and falls back to the last known historical observation.

 8. Baseline methodology

`analysis/baseline.py` computes, for every available variable: mean, median, std, min, max, and the 90th/95th/99th percentiles over the full historical window. This baseline is the reference point for "is this reading unusual for JKUAT right now?"

 9. Risk methodology

`services/risk_engine.py` produces a transparent, weighted 0–100 **Flash-Flood Risk Index**:

| Sub-score | Weight | What it measures |
|---|---|---|
| Rainfall intensity | 35% | Current rainfall rate vs. baseline p95/p99 |
| Rainfall trend | 25% | Is rain-event accumulation actively increasing? |
| Rainfall anomaly | 20% | Percentile-rank anomaly of rainfall/accumulation |
| Humidity | 10% | Saturated air/ground → less capacity to absorb more rain |
| Pressure drop | 10% | Falling pressure → storm approaching |

Weights are configurable in `config.py` and were chosen based on what the historical data actually showed (rainfall dominates; soil moisture is unavailable and therefore excluded rather than guessed). **If a sub-score can't be computed for a given observation (missing variable), it is dropped and the remaining weights are re-normalized** — the engine never invents a value.

Thresholds:

| Score | Level |
|---|---|
| 0–29 | LOW |
| 30–59 | MODERATE |
| 60–79 | HIGH |
| 80–100 | CRITICAL |

**Environmental risk vs. farm-specific risk:** the environmental score is multiplied by a terrain-based vulnerability factor (`config.TERRAIN_VULNERABILITY`, e.g. low-lying = ×1.25, sloped = ×0.90) to produce the farm-specific score shown on the dashboard.

 10. Anomaly detection

`services/anomaly_detector.py`. Two methods, chosen per-variable based on the actual distribution in the data:

- **Z-score** for roughly-continuous variables (temperature, humidity, pressure, wind).
- **Percentile rank** for zero-inflated rainfall variables, where a z-score would be misleading.

 11. Explainability

Every risk assessment returns a `risk_factors` list of plain-language reasons (e.g. *"Rainfall intensity (5.0mm) is higher than 99.5% of recent JKUAT observations"*), not just a number. This is surfaced in the dashboard's **"Why are we alerting you?"** panel. The system is not a black box.

 12. Farmer personalization

A simple farm profile (location, terrain, crop, livestock, assets) is collected in the dashboard sidebar and used to:

1. Scale environmental risk into farm-specific risk (terrain multiplier).
2. Order the recommended actions by which assets this specific farm has (`services/recommendation_engine.py`).

 13. Recommendations & safety

Recommendations are tiered by risk level (LOW → CRITICAL) and personalized by farm assets/terrain. The engine **never** recommends entering floodwater or other dangerous actions — this is enforced directly in `recommendation_engine.py`.

 14. Alerts

`services/alerts.py` builds a structured alert (location, level, score, reason, actions, timestamp) whenever risk reaches HIGH or CRITICAL, and formats it as short text suitable for a future SMS/WhatsApp/USSD/push channel. Only alert *construction and formatting* are implemented in this MVP — no real message is sent.

 15. Architecture

```
flowsafe/
├── app.py                          # entry point
├── config.py                       # thresholds, weights, paths, env
├── requirements.txt
├── .env / .env.example
├── data/
│   └── conduit_march_2026.csv
├── services/
│   ├── conduit_api.py              # live API adapter + mock mode
│   ├── data_processor.py           # raw → canonical schema, validation
│   ├── anomaly_detector.py         # z-score / percentile anomaly detection
│   ├── risk_engine.py              # explainable 0–100 risk index
│   ├── recommendation_engine.py    # tiered, personalized actions
│   └── alerts.py                   # simulated alert construction
├── analysis/
│   ├── baseline.py                 # historical baseline statistics
│   └── exploratory_analysis.py     # standalone data-inspection script
└── dashboard/
    └── streamlit_app.py            # farmer-facing dashboard
```

Data flows one direction: `conduit_api` / historical CSV → `data_processor` → `risk_engine` (using `baseline` + `anomaly_detector`) → `recommendation_engine` / `alerts` → `dashboard`.

 16. Technology stack

Python 3.11+, Pandas, NumPy, Requests, python-dotenv, Streamlit, Plotly, OpenPyXL.

 17. Installation

```bash
cd flowsafe
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

 18. Environment configuration

```bash
cp .env.example .env
# then edit .env:
#   MOCK_MODE=true            (default; no live API needed to demo)
#   CONDUIT_API_KEY=...       (from hackathon organizers)
#   CONDUIT_API_URL=...
```

 19. Running the application

```bash
streamlit run dashboard/streamlit_app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).

To inspect the historical dataset and see the reasoning behind the risk-engine weights:

```bash
python analysis/exploratory_analysis.py
```

 20. Mock mode

With `MOCK_MODE=true` (default), the dashboard generates synthetic-but-realistic observations spanning LOW/MODERATE/HIGH/CRITICAL, clearly labeled **"DEMO DATA — NOT LIVE CONDUIT OBSERVATIONS"** in the UI. The sidebar lets you force a specific scenario for a live demo (e.g. force CRITICAL to show the alert flow) without needing real rain to fall. Set `MOCK_MODE=false` once the live Conduit endpoint is confirmed.

 21. Limitations

- Single-station coverage: risk reflects JKUAT-area conditions, not a precise measurement for every individual farm.
- No soil moisture sensor — currently omitted rather than estimated.
- Historical baseline covers only ~19 days (6–24 March 2026), which is a short season sample; it will improve as more data accumulates.
- Risk score is a transparent weighted index, **not a calibrated flood probability**.
- Live Conduit API endpoint/auth format in `conduit_api.py` should be verified against the official docs before depending on it in a live demo.

 22. Future AI/ML improvements

The current engine is intentionally rule-based and explainable for the MVP. It's structured so it can be swapped for a trained model later:

- Candidate models: Random Forest, XGBoost, Logistic Regression, Gradient Boosting.
- Candidate features: historical rainfall, rainfall intensity, humidity, pressure, soil moisture (once available), elevation, distance to rivers, soil type, drainage, satellite imagery, historical flood events.
- Target: LOW/MODERATE/HIGH/CRITICAL classification or a calibrated probability — **only once real flood-event labels exist**; none are fabricated in this MVP.
- An LLM layer (already partially demonstrated in the "Why are we alerting you?" phrasing) can be used to turn raw sub-scores into farmer-friendly natural-language explanations without ever inventing weather data itself.

 23. Scalability & expected impact

**Scalability path:** multiple weather stations → satellite rainfall estimates → digital elevation models → river-network proximity → rainfall radar → GIS layers, combined into a county-wide flood-risk map instead of a single-station view.

**Expected impact:** turning "heavy rainfall expected" into "your farm is at HIGH risk, move your livestock and fertilizer now" is the difference between a forecast a farmer reads and a warning a farmer *acts on* — potentially protecting livestock, stored inputs, and harvested crops from preventable flood losses.

---

 One-line pitch

> Traditional weather apps answer "what is the weather?" FlowSafe answers "what does the weather mean for my farm, and what should I do?"
