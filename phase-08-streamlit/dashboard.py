import streamlit as st
import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import streamlit.components.v1 as components

# Page config
st.set_page_config(
    page_title="App Review Pulse Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium Dark Theme CSS
st.markdown("""
    <style>
    /* Global Background */
    [data-testid="stAppViewContainer"] {
        background-color: #0f1014;
    }
    [data-testid="stHeader"] {
        background: rgba(0,0,0,0);
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #16171d;
        border-right: 1px solid #23242b;
    }
    
    /* Cards */
    .metric-card {
        background-color: #1c1d22;
        padding: 24px;
        border-radius: 16px;
        border: 1px solid #2d2e35;
        margin-bottom: 20px;
    }
    .metric-value {
        font-size: 32px;
        font-weight: 700;
        color: #ffffff;
        margin-top: 8px;
    }
    .metric-label {
        font-size: 14px;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .metric-delta {
        font-size: 14px;
        margin-top: 4px;
    }
    
    /* Activity List (Themes/Actions) */
    .activity-row {
        background-color: #1c1d22;
        padding: 16px;
        border-radius: 12px;
        margin-bottom: 12px;
        border: 1px solid #23242b;
        display: flex;
        align-items: center;
        transition: all 0.2s ease;
    }
    .activity-row:hover {
        border-color: #4f46e5;
        background-color: #23242b;
    }
    .item-icon {
        width: 40px;
        height: 40px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 16px;
        font-size: 18px;
    }
    
    /* Typography */
    h1, h2, h3 {
        color: #f8fafc !important;
        font-family: 'Inter', sans-serif;
    }
    p, span, li {
        color: #cbd5e1;
    }
    
    /* Custom Scrollbar */
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #0f1014; }
    ::-webkit-scrollbar-thumb { background: #2d2e35; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #3b82f6; }

    /* Buttons */
    .stButton>button {
        background-color: #1c1d22;
        color: white;
        border: 1px solid #334155;
        border-radius: 8px;
        transition: all 0.2s;
    }
    .stButton>button:hover {
        border-color: #6366f1;
        background-color: #23242b;
    }
    </style>
    """, unsafe_allow_html=True)

# Path Resolution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
HISTORY_PATH = DATA_DIR / "history" / "index.json"

@st.cache_data
def load_data():
    if not HISTORY_PATH.exists():
        return None
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def trigger_email_send(week_id):
    try:
        cmd = [sys.executable, str(PROJECT_ROOT / "phase-06-email-draft" / "email_drafter.py"), "--run-label", week_id, "--force"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

def main():
    # --- Sidebar Setup ---
    st.sidebar.markdown("<h2 style='color:#7c3aed; margin-bottom:20px;'>PulseDash</h2>", unsafe_allow_html=True)
    
    data = load_data()
    if not data or not data.get("runs"):
        st.warning("No data found.")
        return

    runs = data["runs"]
    rows = []
    for label, r in runs.items():
        rows.append({
            "Week": label,
            "Health Score": r.get("health_score", 0),
            "Avg Rating": r.get("weighted_avg_rating", 0),
            "Reviews": r.get("total_raw_reviews", 0),
            "Sentiment": r.get("health_label", "Unknown"),
            "Timestamp": r.get("archived_at", "")
        })
    df = pd.DataFrame(rows).sort_values("Timestamp")

    st.sidebar.markdown("<p style='font-size:12px; color:#64748b; text-transform:uppercase;'>Global Controls</p>", unsafe_allow_html=True)
    selected_week = st.sidebar.selectbox("Active Week", df["Week"].unique(), index=len(df)-1)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("<p style='font-size:12px; color:#64748b; text-transform:uppercase;'>Automation</p>", unsafe_allow_html=True)
    
    receipt_path = DATA_DIR / selected_week / "06-email" / "send_receipt.json"
    draft_path = DATA_DIR / selected_week / "06-email" / "email_draft.html"
    
    if receipt_path.exists():
        with open(receipt_path, "r") as f:
            receipt = json.load(f)
        status_color = "#22c55e" if receipt.get("sent") else "#f59e0b"
        st.sidebar.markdown(f"<div style='background:{status_color}20; border:1px solid {status_color}; padding:10px; border-radius:8px;'><span style='color:{status_color}; font-size:12px;'>● {receipt.get('timestamp', 'Recent')}</span></div>", unsafe_allow_html=True)
    
    if st.sidebar.button("🚀 Dispatch Report", use_container_width=True):
        with st.sidebar.status("Sending..."):
            success, _ = trigger_email_send(selected_week)
            if success: st.rerun()

    if draft_path.exists():
        if st.sidebar.button("👁️ Preview Report", use_container_width=True):
            st.session_state["show_preview"] = True

    # --- Header ---
    st.markdown(f"<h1>Dashboard</h1><p style='color:#64748b;'>Insights for {selected_week}</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # --- KPI Grid ---
    curr = runs[selected_week]
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    with kpi1:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">Health Score</div>
            <div class="metric-value">{curr.get('health_score')}/100</div>
            <div class="metric-delta" style="color:#22c55e;">{curr.get('health_label')}</div>
        </div>""", unsafe_allow_html=True)
    
    with kpi2:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">Avg Rating</div>
            <div class="metric-value">{curr.get('weighted_avg_rating'):.2f} ★</div>
            <div class="metric-delta" style="color:#64748b;">Total Stars</div>
        </div>""", unsafe_allow_html=True)
    
    with kpi3:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">Review Volume</div>
            <div class="metric-value">{curr.get('total_raw_reviews'):,}</div>
            <div class="metric-delta" style="color:#64748b;">Weekly Total</div>
        </div>""", unsafe_allow_html=True)
        
    with kpi4:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">Active Themes</div>
            <div class="metric-value">{curr.get('theme_count')}</div>
            <div class="metric-delta" style="color:#3b82f6;">Top Categories</div>
        </div>""", unsafe_allow_html=True)

    # --- Trends & Activity Section ---
    col_graph, col_activity = st.columns([2, 1])
    
    with col_graph:
        st.markdown("<h3 style='margin-bottom:20px;'>Pulse Trends</h3>", unsafe_allow_html=True)
        # Styled Plotly Bar Chart
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df["Week"], y=df["Health Score"],
            marker=dict(
                color='#6366f1',
                line=dict(color='#818cf8', width=1)
            ),
            name="Health Score"
        ))
        fig.update_layout(
            template="plotly_dark",
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=10, b=10),
            height=400,
            xaxis=dict(showgrid=False),
            yaxis=dict(gridcolor="#2d2e35")
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

        # Mini Narrative
        pulse_path = DATA_DIR / selected_week / "04-pulse" / "pulse.json"
        if pulse_path.exists():
            with open(pulse_path, "r", encoding="utf-8") as f:
                pulse_json = json.load(f)
            st.markdown(f"""<div class="metric-card" style="padding:20px;">
                <h4>PM Narrative</h4>
                <p style="font-size:14px; line-height:1.6;">{pulse_json.get('summary')}</p>
            </div>""", unsafe_allow_html=True)

    with col_activity:
        st.markdown("<h3 style='margin-bottom:20px;'>Top Action Plans</h3>", unsafe_allow_html=True)
        action_path = DATA_DIR / selected_week / "05-actions" / "actions.json"
        if action_path.exists():
            with open(action_path, "r", encoding="utf-8") as f:
                actions = json.load(f).get("actions", [])[:3]
            for a in actions:
                p = a.get("priority", "P3")
                icon_color = "#ef4444" if p == "P1" else "#f59e0b" if p == "P2" else "#3b82f6"
                st.markdown(f"""
                <div class="activity-row">
                    <div class="item-icon" style="background:{icon_color}20; color:{icon_color}; font-weight:bold;">{p}</div>
                    <div style="flex:1;">
                        <div style="font-weight:600; font-size:14px;">{a.get('title')}</div>
                        <div style="font-size:12px; color:#64748b;">{a.get('category')} • Effort: {a.get('effort')}</div>
                    </div>
                </div>""", unsafe_allow_html=True)
        else:
            st.caption("No actions generated yet.")

        st.markdown("<br><h3 style='margin-bottom:20px;'>Themes Legend</h3>", unsafe_allow_html=True)
        theme_path = DATA_DIR / selected_week / "03-themes" / "themes.json"
        if theme_path.exists():
            with open(theme_path, "r", encoding="utf-8") as f:
                themes = json.load(f).get("themes", [])[:5]
            for t in themes:
                sent = t.get('sentiment')
                # Use more refined, modern colors
                sent_color = "#10b981" if sent == "positive" else "#f43f5e" if sent == "negative" else "#fbbf24"
                st.markdown(f"""
                <div class="activity-row" style="padding:12px;">
                    <div style="width:10px; height:10px; border-radius:50%; background:{sent_color}; margin-right:12px;"></div>
                    <div style="font-size:13px; font-weight:500;">{t.get('theme_name')}</div>
                </div>""", unsafe_allow_html=True)

    # --- Preview Modal ---
    if st.session_state.get("show_preview"):
        st.markdown("---")
        c_p1, c_p2 = st.columns([10, 1])
        c_p1.subheader("📧 Email Report Preview")
        if c_p2.button("✕"):
            st.session_state["show_preview"] = False
            st.rerun()
        with open(draft_path, "r", encoding="utf-8") as f:
            components.html(f.read(), height=800, scrolling=True)

if __name__ == "__main__":
    main()
