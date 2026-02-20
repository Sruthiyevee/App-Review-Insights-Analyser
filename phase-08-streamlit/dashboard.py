import streamlit as st
import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
import subprocess
import sys
import yaml
from pathlib import Path
from datetime import datetime
import streamlit.components.v1 as components

# Page config
st.set_page_config(
    page_title="App Review Pulse Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for premium look
st.markdown("""
    <style>
    .main {
        background-color: #0f172a;
        color: #f8fafc;
    }
    .stMetric {
        background-color: #1e293b;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #334155;
    }
    .stMetric label {
        color: #94a3b8 !important;
    }
    .stMetric [data-testid="stMetricValue"] {
        color: #f1f5f9 !important;
    }
    .status-box {
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# Path Resolution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
HISTORY_PATH = DATA_DIR / "history" / "index.json"
CONFIG_PATH = PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml"

@st.cache_data
def load_data():
    if not HISTORY_PATH.exists():
        return None
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def trigger_email_send(week_id):
    """Triggers Phase 06 manually via subprocess."""
    try:
        cmd = [sys.executable, str(PROJECT_ROOT / "phase-06-email-draft" / "email_drafter.py"), "--run-label", week_id, "--force"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

def main():
    st.title("📊 App Review Pulse — Product Health Dashboard")
    st.markdown("---")

    data = load_data()
    
    if not data or not data.get("runs"):
        st.warning("No historical data found. Please run the pipeline first.")
        st.info("Run command: `python phase-00-orchestration/orchestrator.py --week historical-12w` (or any label)")
        return

    # Prepare DataFrame for Trends
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
    df = pd.DataFrame(rows)
    df = df.sort_values("Timestamp")

    # Sidebar: Week Selection & Email Controls
    st.sidebar.header("Navigation")
    selected_week = st.sidebar.selectbox("Select Week", df["Week"].unique(), index=len(df)-1)
    
    curr = runs[selected_week]
    
    st.sidebar.markdown("---")
    st.sidebar.header("📨 Email Report")
    
    receipt_path = DATA_DIR / selected_week / "06-email" / "send_receipt.json"
    draft_path = DATA_DIR / selected_week / "06-email" / "email_draft.html"
    
    if receipt_path.exists():
        with open(receipt_path, "r") as f:
            receipt = json.load(f)
        if receipt.get("sent"):
            st.sidebar.success(f"Last Sent: {receipt.get('timestamp', 'Unknown')}")
            st.sidebar.caption(f"To: {receipt.get('recipient')}")
        else:
            st.sidebar.warning(f"Draft Only: {receipt.get('reason')}")
    else:
        st.sidebar.info("No email sent yet for this week.")

    if st.sidebar.button("🚀 Trigger Email Report Now", use_container_width=True):
        with st.sidebar.status("Sending email..."):
            success, output = trigger_email_send(selected_week)
            if success:
                st.sidebar.success("Email dispatched successfully!")
                st.sidebar.toast("Check your inbox!")
                st.rerun()
            else:
                st.sidebar.error("Failed to send email.")
                st.sidebar.code(output)

    if draft_path.exists():
        if st.sidebar.button("👁️ View Email Draft", use_container_width=True):
            st.session_state["show_preview"] = True
    
    # Narrative Summary in Sidebar
    pulse_path = DATA_DIR / selected_week / "04-pulse" / "pulse.json"
    if pulse_path.exists():
        with open(pulse_path, "r", encoding="utf-8") as f:
            pulse_json = json.load(f)
        st.sidebar.markdown("---")
        st.sidebar.subheader("Weekly Narrative")
        st.sidebar.info(pulse_json.get("summary", "No summary available."))

    # Main Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Health Score", f"{curr.get('health_score')}/100", curr.get("health_label"))
    with col2:
        st.metric("Avg Rating", f"{curr.get('weighted_avg_rating'):.2f} ★")
    with col3:
        st.metric("Raw Reviews", f"{curr.get('total_raw_reviews')}")
    with col4:
        st.metric("Themes Found", f"{curr.get('theme_count')}")

    # Email Preview Modal (Conditional)
    if st.session_state.get("show_preview"):
        with st.container():
            st.markdown("### 📧 Email Draft Preview")
            if st.button("Close Preview"):
                st.session_state["show_preview"] = False
                st.rerun()
            with open(draft_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            components.html(html_content, height=800, scrolling=True)
            st.markdown("---")

    st.markdown("---")

    # Trends Visualization
    tab1, tab2 = st.tabs(["📈 Health Trends", "📆 Timeline Data"])
    
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            fig_score = px.line(df, x="Week", y="Health Score", text="Health Score",
                              title="Health Score Trend", markers=True, 
                              color_discrete_sequence=["#3b82f6"])
            fig_score.update_traces(textposition="top center")
            fig_score.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_score, use_container_width=True)
            
        with c2:
            fig_rating = px.line(df, x="Week", y="Avg Rating", text="Avg Rating",
                               title="Average User Rating Trend", markers=True,
                               color_discrete_sequence=["#f59e0b"])
            fig_rating.update_traces(textposition="top center")
            fig_rating.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_rating, use_container_width=True)

    with tab2:
        st.dataframe(df.iloc[::-1], use_container_width=True)

    st.markdown("---")
    
    # Drill Down into Selected Week
    st.header(f"🔍 Drill-down: {selected_week}")
    
    theme_path = DATA_DIR / selected_week / "03-themes" / "themes.json"
    action_path = DATA_DIR / selected_week / "05-actions" / "actions.json"
    
    d_col1, d_col2 = st.columns([2, 1])
    
    with d_col1:
        st.subheader("💡 Themes Legend & Voice of User")
        if theme_path.exists():
            with open(theme_path, "r", encoding="utf-8") as f:
                themes_json = json.load(f)
            
            themes = themes_json.get("themes", [])[:5]
            
            # Show a Legend first
            legend_html = "<div style='display:flex; flex-wrap:wrap; gap:10px; margin-bottom:20px;'>"
            for t in themes:
                color = "#ef4444" if t.get("sentiment") == "negative" else "#22c55e" if t.get("sentiment") == "positive" else "#f59e0b"
                legend_html += f"<span style='background:{color}; color:white; padding:4px 10px; border-radius:15px; font-size:12px; font-weight:bold;'>{t.get('theme_name')}</span>"
            legend_html += "</div>"
            st.markdown(legend_html, unsafe_allow_html=True)

            for t in themes:
                with st.expander(f"{t.get('sentiment').upper()} | {t.get('theme_name')} ({t.get('review_count')} reviews)"):
                    st.write(t.get("description"))
                    st.write("**Voice of the User:**")
                    for q in t.get("example_quotes", [])[:3]: # Also limit quotes for brevity
                        st.markdown(f"> *\"{q}\"*")
        else:
            st.info("Theme data not found for this week.")

    with d_col2:
        st.subheader("🚀 Top 3 Action Plans")
        if action_path.exists():
            with open(action_path, "r", encoding="utf-8") as f:
                actions_json = json.load(f)
            
            # Show ONLY Top 3 Actions (strict)
            actions = actions_json.get("actions", [])[:3]
            for a in actions:
                priority = a.get("priority", "P3")
                color = {"P1": "red", "P2": "orange", "P3": "blue"}.get(priority, "gray")
                st.markdown(f"**:{color}[{priority}]** {a.get('title')}")
                st.caption(f"Category: {a.get('category')} | Effort: {a.get('effort')}")
                st.write(a.get("description"))
                st.markdown("---")
        else:
            st.info("Action data not found for this week.")

if __name__ == "__main__":
    main()
