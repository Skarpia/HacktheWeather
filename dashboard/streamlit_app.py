"""
dashboard/streamlit_app.py

FlowSafe dashboard -- built for a farmer or agricultural officer, not
a data scientist. Run with:

    streamlit run dashboard/streamlit_app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import config
from services.data_processor import load_historical_csv, latest_observation
from analysis.baseline import build_baseline
from services.conduit_api import get_current_observation, _mock_observation
from services.risk_engine import assess_risk
from services.recommendation_engine import generate_recommendations, farm_vulnerability_multiplier
from services.alerts import build_alert, format_alert_text

# ----------------------------------------------------------------------
# Page setup
# ----------------------------------------------------------------------
st.set_page_config(page_title="FlowSafe", page_icon="🌊", layout="wide")

RISK_COLORS = {"LOW": "#2ecc71", "MODERATE": "#f1c40f", "HIGH": "#e67e22", "CRITICAL": "#e74c3c"}


@st.cache_data
def _load_history():
    return load_historical_csv(str(config.HISTORICAL_DATA_PATH))


@st.cache_data
def _load_baseline(_df):
    return build_baseline(_df)


history_df = _load_history()
baseline = _load_baseline(history_df)

# ----------------------------------------------------------------------
# Sidebar: farm profile + demo controls
# ----------------------------------------------------------------------
st.sidebar.title("👨‍🌾 Farm Profile")
farm_location = st.sidebar.text_input("Location", "Juja")
terrain = st.sidebar.selectbox(
    "Terrain", ["low-lying", "flat", "sloped", "near river/stream", "unknown"], index=0
)
crop = st.sidebar.text_input("Crop type", "Maize")
livestock = st.sidebar.text_input("Livestock", "12 cows")
assets = st.sidebar.multiselect(
    "Farm assets to protect",
    ["livestock", "fertilizer", "seeds", "machinery", "harvested crops", "irrigation equipment"],
    default=["livestock", "fertilizer", "machinery"],
)

farm_profile = {
    "location": farm_location,
    "terrain": terrain,
    "crop": crop,
    "livestock": livestock,
    "assets": assets,
}

st.sidebar.markdown("---")
st.sidebar.title("🎛️ Demo Controls")
demo_mode = st.sidebar.checkbox("Use MOCK_MODE (no live API needed)", value=config.MOCK_MODE)
forced_level = st.sidebar.selectbox(
    "Force a scenario (demo only)", ["Auto / Random", "LOW", "MODERATE", "HIGH", "CRITICAL"], index=0
)
refresh = st.sidebar.button("🔄 Refresh live reading")

# ----------------------------------------------------------------------
# Get current observation (mock or live)
# ----------------------------------------------------------------------
if demo_mode:
    level_hint = None if forced_level == "Auto / Random" else forced_level
    result = _mock_observation(level_hint)
else:
    result = get_current_observation()

# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------
st.title("🌊 FLOWSAFE")
st.caption("Hyperlocal Flash-Flood Early Warning — *From weather data to farm-saving decisions.*")
st.markdown(f"**Location:** JKUAT • JUJA • KIAMBU &nbsp;&nbsp;|&nbsp;&nbsp; {config.COVERAGE_LABEL}")

if result.get("is_mock"):
    st.warning("⚠️ **DEMO DATA — NOT LIVE CONDUIT OBSERVATIONS**")

if result.get("status") == "error":
    st.error(f"⚠️ Live Conduit API connection failed: {result.get('error')}")
    st.info("Falling back to the most recent historical observation so the dashboard still functions.")
    observation = latest_observation(history_df)
    is_mock = False
    trend_df = history_df
else:
    observation = result["observation"]
    is_mock = result.get("is_mock", False)
    # Use the freshly-fetched recent window for trend calculations when
    # available (live or mock), since it reflects what's happening RIGHT
    # NOW rather than the fixed March baseline window.
    trend_df = result.get("recent_df") if result.get("recent_df") is not None else history_df

# ----------------------------------------------------------------------
# Risk assessment
# ----------------------------------------------------------------------
mult = farm_vulnerability_multiplier(farm_profile)
risk = assess_risk(observation, baseline, history_df=trend_df, farm_vulnerability_multiplier=mult)
recommendations = generate_recommendations(risk["risk_level"], farm_profile)

# ----------------------------------------------------------------------
# Main risk display
# ----------------------------------------------------------------------
col1, col2 = st.columns([1, 2])

with col1:
    color = RISK_COLORS.get(risk["risk_level"], "#7f8c8d")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=risk["risk_score"],
        number={"suffix": " / 100"},
        title={"text": "FLASH-FLOOD RISK"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 30], "color": "#eafaf1"},
                {"range": [30, 60], "color": "#fef9e7"},
                {"range": [60, 80], "color": "#fdebd0"},
                {"range": [80, 100], "color": "#fadbd8"},
            ],
        },
    ))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(
        f"<h2 style='text-align:center;color:{color};'>{risk['risk_level']}</h2>",
        unsafe_allow_html=True,
    )

with col2:
    st.subheader("Current Environmental Observations")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rainfall", f"{observation.get('rainfall_mm', 'N/A')} mm/15min")
    m2.metric("Humidity", f"{observation.get('humidity_pct', 'N/A')}%")
    m3.metric("Pressure", f"{observation.get('pressure_hpa', 'N/A')} hPa")
    m4.metric("Temperature", f"{observation.get('temperature_c', 'N/A')} °C")

    dq = risk["data_quality"]["completeness_pct"]
    st.markdown("**DATA QUALITY** (completeness of this reading, *not* flood probability)")
    st.progress(min(int(dq), 100) / 100, text=f"{dq}%")

st.markdown("---")

# ----------------------------------------------------------------------
# Why are we alerting you?
# ----------------------------------------------------------------------
st.subheader("🧭 WHY ARE WE ALERTING YOU?")
for factor in risk["risk_factors"]:
    st.markdown(f"- {factor}")

st.markdown("---")

# ----------------------------------------------------------------------
# Action center
# ----------------------------------------------------------------------
st.subheader("✅ WHAT SHOULD YOU DO NOW?")
for i, action in enumerate(recommendations, 1):
    st.markdown(f"**{i}.** {action}")

if risk["risk_level"] in ("HIGH", "CRITICAL"):
    alert = build_alert(farm_location, risk, recommendations, is_mock_data=is_mock)
    if alert:
        st.markdown("---")
        st.error(f"🚨 **ALERT TRIGGERED**\n\n{format_alert_text(alert)}")

st.markdown("---")

# ----------------------------------------------------------------------
# Current vs baseline
# ----------------------------------------------------------------------
st.subheader("📊 CURRENT CONDITIONS vs JKUAT BASELINE (6–24 March 2026)")
compare_vars = [v for v in ["rainfall_mm", "humidity_pct", "pressure_hpa", "temperature_c"] if v in observation]
comp_col1, comp_col2 = st.columns(2)
for i, var in enumerate(compare_vars):
    vb = baseline.get(var)
    if vb is None:
        continue
    current_val = observation.get(var)
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=["Baseline mean", "Baseline p95", "Current"],
                           y=[vb.mean, vb.p95, current_val],
                           marker_color=["#95a5a6", "#f39c12", color]))
    fig2.update_layout(title=var.replace("_", " ").title(), height=250, margin=dict(l=10, r=10, t=40, b=10))
    (comp_col1 if i % 2 == 0 else comp_col2).plotly_chart(fig2, use_container_width=True)

st.markdown("---")

# ----------------------------------------------------------------------
# Historical trends
# ----------------------------------------------------------------------
st.subheader("📈 HISTORICAL RAINFALL & CONDITIONS (6–24 March 2026)")
tab1, tab2, tab3 = st.tabs(["Rainfall trend", "Humidity & Pressure", "Risk timeline (simulated)"])

with tab1:
    fig3 = px.bar(history_df, x="timestamp", y="rainfall_mm", title="15-minute rainfall (mm)")
    st.plotly_chart(fig3, use_container_width=True)
    daily = history_df.set_index("timestamp")["rainfall_mm"].resample("1D").sum().reset_index()
    fig3b = px.bar(daily, x="timestamp", y="rainfall_mm", title="Daily rainfall total (mm)")
    st.plotly_chart(fig3b, use_container_width=True)

with tab2:
    fig4 = px.line(history_df, x="timestamp", y="humidity_pct", title="Humidity (%)")
    st.plotly_chart(fig4, use_container_width=True)
    fig5 = px.line(history_df, x="timestamp", y="pressure_hpa", title="Pressure (hPa)")
    st.plotly_chart(fig5, use_container_width=True)

with tab3:
    st.caption(
        "Illustrative retrospective risk score computed by re-running the "
        "same risk engine over historical data, at 4-hour intervals -- "
        "demonstrates the engine responding to real local rainfall spikes."
    )

    @st.cache_data
    def compute_risk_timeline(_df, _baseline):
        rows = []
        step = 16  # ~4 hours at 15-min intervals
        for i in range(step * 2, len(_df), step):
            window = _df.iloc[: i + 1]
            obs_i = window.iloc[-1].to_dict()
            r = assess_risk(obs_i, _baseline, history_df=window)
            rows.append({"timestamp": obs_i["timestamp"], "risk_score": r["risk_score"], "risk_level": r["risk_level"]})
        return pd.DataFrame(rows)

    timeline = compute_risk_timeline(history_df, baseline)
    fig6 = px.line(timeline, x="timestamp", y="risk_score", title="Retrospective Flash-Flood Risk Index")
    fig6.add_hline(y=30, line_dash="dot", line_color="green")
    fig6.add_hline(y=60, line_dash="dot", line_color="orange")
    fig6.add_hline(y=80, line_dash="dot", line_color="red")
    st.plotly_chart(fig6, use_container_width=True)

st.markdown("---")
st.caption(
    "FlowSafe is a decision-support tool, not a flood prediction guarantee. "
    "Risk scores reflect current conditions relative to the recent local "
    "JKUAT baseline, not a calibrated probability of flooding."
)
