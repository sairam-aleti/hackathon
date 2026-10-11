"""
Enterprise Multi-Plant Order Allocation & Re-Planning Control Tower.
Designed for executive decision support and mathematical operations research.
"""

import os
import sys
from pathlib import Path

# Add project root directory to sys.path so 'src' module is always discoverable
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from src.pdf_generator import generate_allocation_pdf
from src.database import get_connection
from src.solver import explain_order_choice

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Multi-Plant Allocation Control Tower",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Enterprise SaaS CSS Theme (Palantir Foundry / Flexport / Datadog inspired)
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Main container styling */
    .stApp {
        background-color: #0B0F19;
        color: #F1F5F9;
    }

    /* Header title */
    .main-title {
        font-size: 24px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: #F8FAFC;
        margin-bottom: 2px;
    }

    .main-subtitle {
        font-size: 13px;
        color: #94A3B8;
        margin-bottom: 24px;
        font-weight: 400;
    }

    /* Status badge */
    .status-badge {
        display: inline-flex;
        align-items: center;
        background: #111827;
        border: 1px solid #1E293B;
        border-radius: 9999px;
        padding: 4px 12px;
        font-size: 11px;
        font-weight: 500;
        color: #94A3B8;
        margin-bottom: 16px;
    }

    .status-dot {
        width: 6px;
        height: 6px;
        background: #10B981;
        border-radius: 50%;
        margin-right: 8px;
    }

    /* Custom KPI Metric Cards */
    .kpi-container {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 16px;
        margin-bottom: 24px;
    }

    .kpi-card {
        background: #111827;
        border: 1px solid #1E293B;
        border-radius: 8px;
        padding: 16px 20px;
        transition: border-color 0.15s ease;
    }

    .kpi-card:hover {
        border-color: #334155;
    }

    .kpi-label {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #64748B;
        margin-bottom: 6px;
    }

    .kpi-value {
        font-size: 24px;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.5px;
        margin-bottom: 4px;
    }

    .kpi-subtext {
        font-size: 11px;
        color: #94A3B8;
    }

    /* Alert / Operational Notice Banner */
    .alert-banner {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid #334155;
        border-left: 4px solid #3B82F6;
        border-radius: 6px;
        padding: 14px 18px;
        margin-bottom: 24px;
    }

    .alert-banner-warning {
        background: rgba(245, 158, 11, 0.06);
        border: 1px solid rgba(245, 158, 11, 0.25);
        border-left: 4px solid #F59E0B;
        border-radius: 6px;
        padding: 14px 18px;
        margin-bottom: 24px;
    }

    /* Section Headers */
    .section-title {
        font-size: 15px;
        font-weight: 600;
        color: #F1F5F9;
        margin-top: 16px;
        margin-bottom: 12px;
        letter-spacing: -0.2px;
    }

    /* Streamlit widgets overrides */
    .stTextInput > div > div > input {
        background-color: #111827 !important;
        border: 1px solid #1E293B !important;
        color: #F1F5F9 !important;
        border-radius: 6px !important;
    }

    .stTextInput > div > div > input:focus {
        border-color: #3B82F6 !important;
    }

    button[kind="primary"] {
        background-color: #2563EB !important;
        border-color: #2563EB !important;
        font-weight: 500 !important;
        border-radius: 6px !important;
        color: #FFFFFF !important;
    }

    button[kind="primary"]:hover {
        background-color: #1D4ED8 !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
        border-bottom: 1px solid #1E293B;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
        border: none !important;
        color: #94A3B8 !important;
        font-weight: 500;
        font-size: 13px;
        padding-bottom: 10px;
    }

    .stTabs [aria-selected="true"] {
        color: #60A5FA !important;
        border-bottom: 2px solid #3B82F6 !important;
    }

    /* Sidebar adjustments */
    section[data-testid="stSidebar"] {
        background-color: #0F172A;
        border-right: 1px solid #1E293B;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================

st.sidebar.markdown(
    """
    <div style="margin-bottom: 18px;">
        <div style="font-size: 11px; font-weight: 700; color: #3B82F6; text-transform: uppercase; letter-spacing: 1px;">Control Console</div>
        <div style="font-size: 17px; font-weight: 700; color: #F8FAFC;">Optimization Engine</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# API Status indicator
try:
    health_resp = requests.get(f"{API_URL}/health", timeout=2)
    if health_resp.status_code == 200:
        h_data = health_resp.json()
        st.sidebar.markdown(
            f"""
            <div class="status-badge">
                <span class="status-dot"></span>
                <span>API: Ready &nbsp;|&nbsp; Solver: CBC MILP &nbsp;|&nbsp; LLM: {h_data['llm']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.warning("API reachable with degraded status.")
except Exception:
    st.sidebar.error("Backend API offline (verify port 8000).")

# Preset Scenarios Section
st.sidebar.markdown("<div style='font-size: 12px; font-weight: 600; color: #94A3B8; margin-top: 10px; margin-bottom: 6px;'>PRESET SCENARIOS</div>", unsafe_allow_html=True)
p_col1, p_col2 = st.sidebar.columns(2)
with p_col1:
    if st.button("Normal Operations", use_container_width=True):
        st.session_state["trigger_query"] = "Allocate all orders balancing cost and carbon under normal baseline operations."
        st.session_state["preset_weights"] = {"cost": 0.7, "carbon": 0.3, "lateness": 0.0}
        st.session_state["preset_scenario"] = None
with p_col2:
    if st.button("Plant B -30% Outage", use_container_width=True):
        st.session_state["trigger_query"] = "Plant B loses 30% capacity due to maintenance. Re-allocate all orders."
        st.session_state["preset_weights"] = {"cost": 0.7, "carbon": 0.3, "lateness": 0.2}
        st.session_state["preset_scenario"] = {"plant_id": "B", "capacity_reduction_pct": 0.30}

p_col3, p_col4 = st.sidebar.columns(2)
with p_col3:
    if st.button("Green Minimization", use_container_width=True):
        st.session_state["trigger_query"] = "Minimize total carbon emissions across all orders."
        st.session_state["preset_weights"] = {"cost": 0.1, "carbon": 0.9, "lateness": 0.1}
        st.session_state["preset_scenario"] = None
with p_col4:
    if st.button("Cost Minimization", use_container_width=True):
        st.session_state["trigger_query"] = "Minimize total landed cost across all manufacturing plants."
        st.session_state["preset_weights"] = {"cost": 1.0, "carbon": 0.0, "lateness": 0.0}
        st.session_state["preset_scenario"] = None

st.sidebar.markdown("<hr style='border: 0; border-top: 1px solid #1E293B; margin: 18px 0;'>", unsafe_allow_html=True)

# Optimization Weights Sliders
st.sidebar.markdown("<div style='font-size: 12px; font-weight: 600; color: #94A3B8; margin-bottom: 12px;'>OBJECTIVE WEIGHTS</div>", unsafe_allow_html=True)

default_cost = st.session_state.get("preset_weights", {}).get("cost", 0.7)
cost_weight = st.sidebar.slider(
    "Cost Objective Weight",
    min_value=0.0,
    max_value=1.0,
    value=float(default_cost),
    step=0.05,
    help="Higher weight minimizes unit landed cost, prioritizing high-efficiency facilities.",
)

carbon_weight = round(1.0 - cost_weight, 2)
st.sidebar.markdown(
    f"""
    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #94A3B8; margin-top: -8px; margin-bottom: 12px;">
        <span>Carbon Weight (Linked)</span>
        <strong style="color: #10B981;">{carbon_weight}</strong>
    </div>
    """,
    unsafe_allow_html=True,
)

late_weight = st.sidebar.slider(
    "Delivery Strictness (Late Penalty)",
    min_value=0.0,
    max_value=1.0,
    value=float(st.session_state.get("preset_weights", {}).get("lateness", 0.0)),
    step=0.1,
    help="Enforces severe mathematical penalties for orders with long transit times approaching deadlines.",
)

# Initial data load if session state empty
if "last_analysis" not in st.session_state:
    try:
        init_res = requests.post(
            f"{API_URL}/analyze",
            json={"request": "Allocate all orders balancing cost and carbon under normal baseline operations."},
            timeout=8,
        )
        if init_res.status_code == 200:
            st.session_state["last_analysis"] = init_res.json()
    except Exception:
        pass

# Sidebar Actions
curr_analysis = st.session_state.get("last_analysis")
pdf_data = None
if curr_analysis and curr_analysis.get("answer_type") != "clarification_needed":
    try:
        pdf_data = generate_allocation_pdf(curr_analysis)
    except Exception as e:
        logger_err = str(e)

if pdf_data:
    st.sidebar.download_button(
        label="Generate Plan (PDF)",
        data=pdf_data,
        file_name=f"Executive_Allocation_Plan_{curr_analysis.get('run_id', 'latest')}.pdf",
        mime="application/pdf",
        key="sidebar_pdf_btn",
        type="primary",
        use_container_width=True,
    )
else:
    sidebar_gen_btn = st.sidebar.button("Run Optimization", key="sidebar_gen_plan_btn", type="primary", use_container_width=True)

st.sidebar.markdown("<hr style='border: 0; border-top: 1px solid #1E293B; margin: 18px 0;'>", unsafe_allow_html=True)

# Disruption Simulator
st.sidebar.markdown("<div style='font-size: 12px; font-weight: 600; color: #94A3B8; margin-bottom: 12px;'>FACILITY DISRUPTION SIMULATOR</div>", unsafe_allow_html=True)
disrupt_enabled = st.sidebar.checkbox("Simulate Plant Disruption", value=bool(st.session_state.get("preset_scenario") is not None))
selected_plant = st.sidebar.selectbox("Affected Plant", ["A", "B", "C"], index=1)
reduction_pct = st.sidebar.slider("Capacity Loss (%)", min_value=10, max_value=90, value=30, step=5)

scenario_payload = st.session_state.get("preset_scenario", None)
if disrupt_enabled:
    scenario_payload = {
        "plant_id": selected_plant,
        "capacity_reduction_pct": reduction_pct / 100.0,
    }
    st.sidebar.caption(f"Active Disruption: Plant {selected_plant} loses {reduction_pct}% capacity.")

st.sidebar.markdown("<hr style='border: 0; border-top: 1px solid #1E293B; margin: 18px 0;'>", unsafe_allow_html=True)

# Data Ingestion
st.sidebar.markdown("<div style='font-size: 12px; font-weight: 600; color: #94A3B8; margin-bottom: 8px;'>BATCH DATA INGESTION</div>", unsafe_allow_html=True)
upload_table = st.sidebar.selectbox("Target Table", ["orders", "plants", "transport_duties", "capacity_events"])
uploaded_file = st.sidebar.file_uploader("Upload CSV", type=["csv"], label_visibility="collapsed")
if uploaded_file is not None and st.sidebar.button("Validate & Load to SQLite"):
    with st.spinner("Executing schema validation..."):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")}
        data = {"table_name": upload_table}
        try:
            res = requests.post(f"{API_URL}/ingest", files=files, data=data, timeout=10)
            if res.status_code == 200:
                ing_res = res.json()
                st.sidebar.success(f"Loaded {ing_res['rows_loaded'].get(upload_table, 0)} records.")
            else:
                st.sidebar.error("Ingest failed.")
        except Exception as e:
            st.sidebar.error(f"Upload error: {e}")


# =============================================================================
# MAIN DASHBOARD CONTENT
# =============================================================================

st.markdown("<div class='main-title'>Multi-Plant Order Allocation Control Tower</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Mathematical Mixed-Integer Linear Programming Optimization &bull; Zero-Hallucination Verified Briefs</div>", unsafe_allow_html=True)

# Natural Language Query & Action Buttons
col_q, col_run, col_pdf = st.columns([3, 1, 1.2])
with col_q:
    input_default = st.session_state.pop("trigger_query", "")
    user_query = st.text_input(
        "Natural Language Query / Operational Directive",
        value=input_default,
        placeholder="e.g. Plant B lost 30% so give me a new plan balancing cost and delivery SLAs",
        label_visibility="collapsed",
    )
with col_run:
    run_query_btn = st.button("Run Query", key="main_run_query_btn", use_container_width=True, type="primary")
with col_pdf:
    if pdf_data:
        st.download_button(
            label="Generate Plan (PDF)",
            data=pdf_data,
            file_name=f"Allocation_Plan_{curr_analysis.get('run_id', 'latest')}.pdf",
            mime="application/pdf",
            key="main_pdf_download_btn",
            use_container_width=True,
        )
    else:
        st.button("Generate Plan", key="main_disabled_pdf_btn", disabled=True, use_container_width=True)

# Track active weight and scenario parameters
curr_weights = {"cost": round(cost_weight, 2), "carbon": round(carbon_weight, 2), "lateness": round(late_weight, 2)}
curr_scenario = scenario_payload

# Initialize tracking on first run if not present
if "last_executed_weights" not in st.session_state:
    st.session_state["last_executed_weights"] = curr_weights
if "last_executed_scenario" not in st.session_state:
    st.session_state["last_executed_scenario"] = curr_scenario

weights_changed = (curr_weights != st.session_state.get("last_executed_weights"))
scenario_changed = (curr_scenario != st.session_state.get("last_executed_scenario"))
query_changed = bool(user_query and user_query != st.session_state.get("last_executed_query", ""))
button_clicked = run_query_btn or ("trigger_query" in st.session_state)

should_execute = button_clicked or weights_changed or scenario_changed or query_changed
if should_execute:
    active_query = user_query.strip("'\" \t\n") if user_query else "Allocate all customer manufacturing orders across plants."
    payload = {
        "request": active_query,
        "weights": curr_weights,
        "scenario": curr_scenario,
    }
    with st.spinner("Executing CBC MILP Optimization & Synthesizing Leadership Brief..."):
        try:
            resp = requests.post(f"{API_URL}/analyze", json=payload, timeout=15)
            if resp.status_code == 200:
                st.session_state["last_analysis"] = resp.json()
                st.session_state["last_executed_query"] = user_query
                st.session_state["last_executed_weights"] = curr_weights
                st.session_state["last_executed_scenario"] = curr_scenario
                st.rerun()
            else:
                st.error(f"Solver API Error: {resp.status_code} - {resp.text}")
        except Exception as err:
            st.error(f"Network connection failed: {err}")

# Render Results
if "last_analysis" in st.session_state:
    data = st.session_state["last_analysis"]
    answer_type = data.get("answer_type", "allocation")

    # If the user entered an irrelevant query, display ONLY the operational refusal message
    if answer_type == "clarification_needed":
        st.markdown(
            f"""
            <div class="alert-banner-warning">
                <div style="font-size: 13px; font-weight: 700; color: #F59E0B; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
                    Notice: Insufficient Information / Out of Domain Query
                </div>
                <div style="font-size: 13.5px; color: #E2E8F0; line-height: 1.6;">
                    {data.get("summary", "The query does not contain recognized operational parameters.")}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1E293B; border-radius: 8px; padding: 18px 22px; margin-top: 12px; margin-bottom: 24px;">
                <div style="font-size: 12px; font-weight: 600; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                    Supported Operational Query Patterns:
                </div>
                <ul style="font-size: 13px; color: #CBD5E1; line-height: 1.8; margin-left: -15px;">
                    <li><strong>Baseline Re-Plan:</strong> <code>Allocate all manufacturing orders balancing cost and carbon.</code></li>
                    <li><strong>Facility Disruption:</strong> <code>Plant B loses 30% capacity due to scheduled maintenance.</code></li>
                    <li><strong>Multi-Objective Weighting:</strong> <code>Minimize carbon emissions across all customer shipments.</code></li>
                    <li><strong>Explainable Counterfactual:</strong> <code>Why was order O-001 assigned to Plant A instead of Plant B?</code></li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    kpis = data.get("kpis") or {}
    allocation = data.get("allocation", [])
    tradeoff = data.get("tradeoff", [])
    run_id = data.get("run_id", "N/A")
    unfulfilled_list = data.get("unfulfilled_orders", [])
    unfulfilled_count = len(unfulfilled_list)

    total_cost = kpis.get("total_cost", 0.0)
    total_carbon = kpis.get("total_carbon_t", 0.0)
    late_orders = kpis.get("late_orders", 0)
    total_orders = len(allocation)
    on_time_count = sum(1 for a in allocation if a.get("on_time", False))
    on_time_pct = (on_time_count / total_orders * 100) if total_orders > 0 else 0.0

    # Operational Notice Banner (Only show warning if orders were actually deferred)
    if unfulfilled_count > 0:
        total_demand_orders = total_orders + unfulfilled_count
        st.markdown(
            f"""
            <div class="alert-banner-warning">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <div style="font-size: 13px; font-weight: 700; color: #F59E0B; text-transform: uppercase; letter-spacing: 0.5px;">
                        Capacity-Constrained Operations Notice
                    </div>
                    <div style="font-size: 12px; color: #94A3B8;">
                        Allocated: <strong style="color: #10B981;">{total_orders} Orders</strong> &bull; Deferred: <strong style="color: #F59E0B;">{unfulfilled_count} Orders</strong> (Total Demand: {total_demand_orders})
                    </div>
                </div>
                <div style="font-size: 13px; color: #E2E8F0; line-height: 1.5;">
                    Aggregate customer demand ({total_demand_orders} orders) exceeds net facility operating throughput under current disruption parameters. 
                    The solver prioritized and fulfilled <strong>{total_orders} high-priority orders</strong>, absorbing excess volume via mathematical elastic slack variables to maintain deterministic stability and protect on-time delivery SLAs ({on_time_pct:.1f}% on-time rate).
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="alert-banner">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 13px; font-weight: 600; color: #60A5FA;">
                        Optimal Feasible Allocation Plan Established
                    </div>
                    <div style="font-size: 12px; color: #94A3B8;">
                        Fulfillment: <strong style="color: #10B981;">100% ({total_orders} of {total_orders} Orders)</strong>
                    </div>
                </div>
                <div style="font-size: 12px; color: #94A3B8; margin-top: 4px;">
                    All {total_orders} customer manufacturing orders successfully assigned within operating throughput ceilings. Zero unallocated demand.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 4 Enterprise Metric Cards
    st.markdown(
        f"""
        <div class="kpi-container">
            <div class="kpi-card">
                <div class="kpi-label">Total Landed Cost</div>
                <div class="kpi-value">${total_cost:,.2f}</div>
                <div class="kpi-subtext">Production, energy, freight, duties</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Carbon Footprint</div>
                <div class="kpi-value">{total_carbon:,.1f} <span style="font-size: 14px; font-weight: 500; color: #94A3B8;">t CO2e</span></div>
                <div class="kpi-subtext">Plant operations + shipping emissions</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Delivery Timeliness</div>
                <div class="kpi-value">{late_orders} <span style="font-size: 14px; font-weight: 500; color: #94A3B8;">/ {total_orders} late</span></div>
                <div class="kpi-subtext">{total_orders - late_orders} delivered on schedule</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">On-Time SLA Rate</div>
                <div class="kpi-value" style="color: {'#10B981' if on_time_pct >= 90 else '#F59E0B'};">{on_time_pct:.1f}%</div>
                <div class="kpi-subtext">Customer SLA fulfillment target: 90%</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Main Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Executive Overview & Charts",
        "Order Allocation Manifest",
        "Order Choice Explanations",
        "Audit Log & Trace",
    ])

    with tab1:
        # Visualizations Row
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='section-title'>Facility Capacity Utilization</div>", unsafe_allow_html=True)
            plant_util = kpis.get("plant_utilisation", {})
            if plant_util:
                util_df = pd.DataFrame([
                    {"Facility": f"Plant {p}", "Utilization": round(u * 100, 1)}
                    for p, u in sorted(plant_util.items())
                ])
                fig_bar = px.bar(
                    util_df,
                    x="Facility",
                    y="Utilization",
                    text="Utilization",
                    range_y=[0, 115],
                    labels={"Utilization": "Effective Capacity Utilized (%)"},
                    color="Facility",
                    color_discrete_sequence=["#3B82F6", "#0EA5E9", "#10B981"],
                )
                fig_bar.add_hline(
                    y=100,
                    line_dash="dash",
                    line_color="#EF4444",
                    annotation_text="100% Operating Ceiling",
                    annotation_position="top left",
                    annotation_font_color="#EF4444",
                )
                fig_bar.update_layout(
                    template="plotly_dark",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    height=320,
                    margin=dict(l=10, r=10, t=30, b=10),
                    showlegend=False,
                    xaxis=dict(gridcolor="#1E293B", linecolor="#334155"),
                    yaxis=dict(gridcolor="#1E293B", linecolor="#334155"),
                )
                fig_bar.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("No facility utilization data available.")

        with c2:
            st.markdown("<div class='section-title'>Pareto Trade-Off Frontier (Cost vs. Carbon)</div>", unsafe_allow_html=True)
            if tradeoff:
                trade_df = pd.DataFrame(tradeoff)
                fig_pareto = px.line(
                    trade_df,
                    x="cost",
                    y="carbon_cut_pct",
                    markers=True,
                    labels={
                        "cost": "Total Landed Cost ($)",
                        "carbon_cut_pct": "Carbon Reduction (%)",
                    },
                )
                # Plot active position
                fig_pareto.add_trace(
                    go.Scatter(
                        x=[total_cost],
                        y=[0],
                        mode="markers+text",
                        name="Active Plan",
                        text=["Selected"],
                        textposition="top right",
                        marker=dict(color="#38BDF8", size=12, symbol="diamond"),
                    )
                )
                fig_pareto.update_layout(
                    template="plotly_dark",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    height=320,
                    margin=dict(l=10, r=10, t=30, b=10),
                    showlegend=False,
                    xaxis=dict(gridcolor="#1E293B", linecolor="#334155"),
                    yaxis=dict(gridcolor="#1E293B", linecolor="#334155"),
                )
                st.plotly_chart(fig_pareto, use_container_width=True)
            else:
                st.info("Pareto frontier data unavailable.")

        # Leadership Executive Brief
        st.markdown("<div class='section-title'>Executive Leadership Brief (Zero-Hallucination Certified)</div>", unsafe_allow_html=True)
        summary_text = data.get("summary", "No brief generated.")
        st.markdown(
            f"""
            <div style="background: #111827; border: 1px solid #1E293B; border-radius: 8px; padding: 18px 22px; font-size: 13.5px; line-height: 1.6; color: #E2E8F0;">
                {summary_text}
            </div>
            """,
            unsafe_allow_html=True,
        )

        if pdf_data:
            st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
            st.download_button(
                label="Download Full Executive PDF Plan & Allocation Manifest",
                data=pdf_data,
                file_name=f"Executive_Allocation_Plan_{data.get('run_id', 'latest')}.pdf",
                mime="application/pdf",
                key="tab1_pdf_dl_btn",
                use_container_width=True,
            )

    with tab2:
        st.markdown("<div class='section-title'>Allocated Order Manifest</div>", unsafe_allow_html=True)
        if allocation:
            alloc_df = pd.DataFrame(allocation)
            alloc_df = alloc_df.rename(columns={
                "order_id": "Order ID",
                "plant": "Assigned Facility",
                "cost": "Landed Cost ($)",
                "carbon_kg": "Carbon (kg CO2e)",
                "arrival": "Est. Arrival Date",
                "on_time": "On-Time Status",
            })
            st.dataframe(alloc_df, use_container_width=True, height=420)
        else:
            st.warning("No allocation records returned.")

    with tab3:
        st.markdown("<div class='section-title'>Explainable Counterfactual Analysis</div>", unsafe_allow_html=True)
        explain_data = data.get("counterfactuals")
        
        # Interactive Order Selector Dropdown
        all_order_ids = [a.get("order_id") for a in allocation if a.get("order_id")] if allocation else []
        if all_order_ids:
            # Match current order or default to first
            default_oid = explain_data.get("order_id") if explain_data else all_order_ids[0]
            sel_idx = all_order_ids.index(default_oid) if default_oid in all_order_ids else 0
            selected_inspect_oid = st.selectbox(
                "Inspect Order Decision Logic",
                all_order_ids,
                index=sel_idx,
                key="tab3_order_select",
                help="Select any order to analyze why the solver chose its plant over alternative facilities.",
            )
            # Recompute explanation dynamically for the chosen order on the fly
            try:
                with get_connection() as conn:
                    explain_data = explain_order_choice(conn, selected_inspect_oid, data)
            except Exception as e:
                pass

        if explain_data and "chosen_plant" in explain_data:
            oid = explain_data.get("order_id")
            c_plant = explain_data.get("chosen_plant")
            c_cost = explain_data.get("chosen_cost")
            c_carb = explain_data.get("chosen_carbon")
            st.markdown(
                f"""
                <div style="background: #111827; border: 1px solid #1E293B; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; margin-top: 12px;">
                    <div style="font-size: 14px; font-weight: 600; color: #38BDF8;">Order Evaluation Rationale: {oid}</div>
                    <div style="font-size: 12px; color: #94A3B8; margin-top: 4px;">
                        Selected Facility: <strong>Plant {c_plant}</strong> &bull; Landed Cost: <strong>${c_cost:,.2f}</strong> &bull; Carbon: <strong>{c_carb:,.1f} kg CO2e</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            alts = explain_data.get("alternatives", {})
            alt_rows = []
            for pid, info in alts.items():
                alt_rows.append({
                    "Facility": f"Plant {pid}",
                    "Cost ($)": f"${info.get('landed_cost', 0):,.2f}",
                    "Carbon (kg)": f"{info.get('carbon_kg', 0):,.1f}",
                    "Transit (Days)": info.get("transit_days"),
                    "On-Time Status": "Yes" if info.get("on_time") else "Late",
                    "Evaluation Reason": info.get("reason", "N/A"),
                })
            st.dataframe(pd.DataFrame(alt_rows), use_container_width=True)
        else:
            st.info("To generate counterfactual explanations, enter a query like 'Why was order O-001 assigned to Plant A?' in the top command bar or choose an order above.")

    with tab4:
        st.markdown(f"<div class='section-title'>Execution Audit Log & Pipeline Latency (Run: {run_id})</div>", unsafe_allow_html=True)
        try:
            trace_resp = requests.get(f"{API_URL}/trace/{run_id}", timeout=3)
            if trace_resp.status_code == 200:
                t_json = trace_resp.json()
                t_col1, t_col2, t_col3 = st.columns(3)
                with t_col1:
                    st.metric("Total Execution Latency", f"{t_json.get('total_duration_ms', 0):.1f} ms")
                with t_col2:
                    st.metric("Pipeline Steps Executed", len(t_json.get("steps", [])))
                with t_col3:
                    st.metric("External LLM Calls", t_json.get("llm_calls", 0))

                steps_df = pd.DataFrame(t_json.get("steps", []))
                if not steps_df.empty:
                    st.dataframe(steps_df[["step_name", "duration_ms", "timestamp"]], use_container_width=True)
            else:
                st.caption("Trace unavailable for this execution run.")
        except Exception as e:
            st.caption(f"Error loading trace: {e}")
