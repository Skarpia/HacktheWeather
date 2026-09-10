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
from services.data_processor import load_historical_dataset, latest_observation
from analysis.baseline import build_baseline
from services.conduit_api import get_current_observation, _mock_observation
from services.risk_engine import assess_risk
from services.recommendation_engine import generate_recommendations, farm_vulnerability_multiplier
from services.alerts import build_alert, format_alert_text

# ----------------------------------------------------------------------
# Page setup
# ----------------------------------------------------------------------
st.set_page_config(page_title="FlowSafe", page_icon="🌊", layout="wide")

RISK_COLORS = {"LOW": "#22c55e", "MODERATE": "#f0b429", "HIGH": "#f0723c", "CRITICAL": "#e5484d"}
RISK_BG = {"LOW": "#eafaf1", "MODERATE": "#fef9e7", "HIGH": "#fdebd0", "CRITICAL": "#fdecea"}
RISK_ICON = {"LOW": "✅", "MODERATE": "🌦️", "HIGH": "⚠️", "CRITICAL": "🚨"}

# ----------------------------------------------------------------------
# Theme: fonts, gradients, cards, hero banner -- self-contained CSS
# (no external images, so the demo never depends on network access).
# A faint inline-SVG raindrop pattern gives the hero a "weather" feel;
# soft greens throughout nod to the agricultural context.
# ----------------------------------------------------------------------
RAIN_PATTERN_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='60' height='60'>"
    "<g fill='%23ffffff' fill-opacity='0.10'>"
    "<path d='M8 4c3 5 3 9 0 12-3-3-3-7 0-12z'/>"
    "<path d='M38 24c3 5 3 9 0 12-3-3-3-7 0-12z'/>"
    "<path d='M20 44c3 5 3 9 0 12-3-3-3-7 0-12z'/>"
    "</g></svg>"
)

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@600;700;800&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

.stApp {{
    background: linear-gradient(180deg, #f4faff 0%, #eef7f0 45%, #f7fbf7 100%);
}}

section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #f0f7ee 0%, #e7f3e8 100%);
    border-right: 1px solid #d9ead9;
}}
section[data-testid="stSidebar"] h1 {{
    font-family: 'Poppins', sans-serif;
    font-size: 1.25rem;
    color: #1f6b3a;
}}

/* Hero banner */
.flowsafe-hero {{
    background: linear-gradient(120deg, #1f6bd8 0%, #2f9bd6 55%, #2fb6a3 100%);
    background-image:
        linear-gradient(120deg, rgba(31,107,216,0.94) 0%, rgba(47,155,214,0.94) 55%, rgba(47,182,163,0.94) 100%),
        url("{RAIN_PATTERN_SVG}");
    border-radius: 20px;
    padding: 2rem 2.2rem;
    margin-bottom: 1.4rem;
    box-shadow: 0 10px 30px rgba(31,107,216,0.18);
}}
.flowsafe-hero h1 {{
    font-family: 'Poppins', sans-serif;
    font-weight: 800;
    color: white;
    font-size: 2.1rem;
    margin: 0 0 0.2rem 0;
    letter-spacing: 0.5px;
}}
.flowsafe-hero p.tagline {{
    color: rgba(255,255,255,0.92);
    font-size: 1.02rem;
    margin: 0 0 0.9rem 0;
    font-style: italic;
}}
.flowsafe-pill {{
    display: inline-block;
    background: rgba(255,255,255,0.18);
    color: white;
    border: 1px solid rgba(255,255,255,0.35);
    border-radius: 999px;
    padding: 0.3rem 0.9rem;
    font-size: 0.85rem;
    font-weight: 600;
    margin-right: 0.5rem;
    backdrop-filter: blur(2px);
}}

/* Risk badge */
.flowsafe-risk-badge {{
    text-align: center;
    border-radius: 16px;
    padding: 0.9rem 0.5rem;
    font-family: 'Poppins', sans-serif;
    font-weight: 800;
    font-size: 1.6rem;
    letter-spacing: 1px;
    margin-top: 0.6rem;
}}

/* Section headers */
.flowsafe-section-title {{
    font-family: 'Poppins', sans-serif;
    font-weight: 700;
    font-size: 1.15rem;
    color: #14532d;
    margin: 0 0 0.6rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}}

/* Card containers (targets Streamlit's bordered container) */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 16px !important;
    box-shadow: 0 2px 14px rgba(20, 83, 45, 0.06);
    background: #ffffff;
}}

/* Metrics */
div[data-testid="stMetric"] {{
    background: #f4fbf5;
    border: 1px solid #dcf0de;
    border-radius: 12px;
    padding: 0.6rem 0.8rem 0.3rem 0.8rem;
}}
div[data-testid="stMetricLabel"] {{
    color: #3a7a4e;
    font-weight: 600;
}}

/* Buttons */
.stButton>button {{
    border-radius: 10px;
    font-weight: 600;
    border: 1px solid #2fb6a3;
    color: #14532d;
}}
.stButton>button:hover {{
    background: #e6f7f1;
    border-color: #1f6b3a;
}}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def _load_history():
    return load_historical_dataset(config.DATA_DIR)


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
# Computed up-front so mock generation can calibrate to the FARM-
# SPECIFIC score (i.e. the number actually shown on screen), not just
# the raw environmental score -- otherwise a vulnerable farm's terrain
# multiplier can push a "forced HIGH" scenario into a CRITICAL display.
mult = farm_vulnerability_multiplier(farm_profile)

if demo_mode:
    level_hint = None if forced_level == "Auto / Random" else forced_level
    result = _mock_observation(level_hint, baseline=baseline, farm_multiplier=mult)
else:
    result = get_current_observation(baseline=baseline)

# ----------------------------------------------------------------------
# Header (hero banner)
# ----------------------------------------------------------------------
st.markdown(f"""
<div class="flowsafe-hero">
    <h1>🌊 FLOWSAFE</h1>
    <p class="tagline">Hyperlocal Flash-Flood Early Warning — From weather data to farm-saving decisions.</p>
    <span class="flowsafe-pill">📍 JKUAT • JUJA • KIAMBU</span>
    <span class="flowsafe-pill">🌾 {config.COVERAGE_LABEL}</span>
</div>
""", unsafe_allow_html=True)

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
risk = assess_risk(observation, baseline, history_df=trend_df, farm_vulnerability_multiplier=mult)
recommendations = generate_recommendations(risk["risk_level"], farm_profile)

# ----------------------------------------------------------------------
# Main risk display
# ----------------------------------------------------------------------
color = RISK_COLORS.get(risk["risk_level"], "#7f8c8d")
bg = RISK_BG.get(risk["risk_level"], "#f2f2f2")
icon = RISK_ICON.get(risk["risk_level"], "ℹ️")

col1, col2 = st.columns([1, 2])

with col1:
    with st.container(border=True):
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=risk["risk_score"],
            number={"suffix": " / 100"},
            title={"text": "FLASH-FLOOD RISK"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": color},
                "bgcolor": "white",
                "steps": [
                    {"range": [0, 30], "color": RISK_BG["LOW"]},
                    {"range": [30, 60], "color": RISK_BG["MODERATE"]},
                    {"range": [60, 80], "color": RISK_BG["HIGH"]},
                    {"range": [80, 100], "color": RISK_BG["CRITICAL"]},
                ],
            },
        ))
        fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(
            f"<div class='flowsafe-risk-badge' style='background:{bg};color:{color};'>{icon} {risk['risk_level']}</div>",
            unsafe_allow_html=True,
        )

with col2:
    with st.container(border=True):
        st.markdown("<div class='flowsafe-section-title'>🌦️ Current Environmental Observations</div>", unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("💧 Rainfall", f"{observation.get('rainfall_mm', 'N/A')} mm/15min")
        m2.metric("💦 Humidity", f"{observation.get('humidity_pct', 'N/A')}%")
        m3.metric("🌡️ Pressure", f"{observation.get('pressure_hpa', 'N/A')} hPa")
        m4.metric("🌤️ Temperature", f"{observation.get('temperature_c', 'N/A')} °C")

        dq = risk["data_quality"]["completeness_pct"]
        st.markdown("**DATA QUALITY** (completeness of this reading, *not* flood probability)")
        st.progress(min(int(dq), 100) / 100, text=f"{dq}%")

st.write("")

# ----------------------------------------------------------------------
# Why are we alerting you?
# ----------------------------------------------------------------------
with st.container(border=True):
    st.markdown("<div class='flowsafe-section-title'>🧭 WHY ARE WE ALERTING YOU?</div>", unsafe_allow_html=True)
    for factor in risk["risk_factors"]:
        st.markdown(f"- {factor}")

st.write("")

# ----------------------------------------------------------------------
# Action center
# ----------------------------------------------------------------------
with st.container(border=True):
    st.markdown("<div class='flowsafe-section-title'>✅ WHAT SHOULD YOU DO NOW?</div>", unsafe_allow_html=True)
    for i, action in enumerate(recommendations, 1):
        st.markdown(f"**{i}.** {action}")

    if risk["risk_level"] in ("HIGH", "CRITICAL"):
        alert = build_alert(farm_location, risk, recommendations, is_mock_data=is_mock)
        if alert:
            st.markdown("---")
            st.error(f"🚨 **ALERT TRIGGERED**\n\n{format_alert_text(alert)}")

st.write("")

# ----------------------------------------------------------------------
# Current vs baseline
# ----------------------------------------------------------------------
with st.container(border=True):
    st.markdown(
        f"<div class='flowsafe-section-title'>📊 CURRENT CONDITIONS vs JKUAT BASELINE ({baseline.period_start[:10]} to {baseline.period_end[:10]})</div>",
        unsafe_allow_html=True,
    )
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
                               marker_color=["#9fd3a8", "#f0b429", color]))
        fig2.update_layout(title=var.replace("_", " ").title(), height=250,
                            margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)")
        (comp_col1 if i % 2 == 0 else comp_col2).plotly_chart(fig2, use_container_width=True)

st.write("")

# ----------------------------------------------------------------------
# Historical trends
# ----------------------------------------------------------------------
st.markdown(
    f"<div class='flowsafe-section-title'>📈 HISTORICAL RAINFALL & CONDITIONS ({baseline.period_start[:10]} to {baseline.period_end[:10]})</div>",
    unsafe_allow_html=True,
)
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
