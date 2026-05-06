"""Recovery page."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from ui.charts import sleep_performance_chart, sleep_recovery_chart, vo2max_trend_chart
from utils.bootstrap import load_training_bundle
from utils.formatting import format_metric_number

st.title("Recovery")

bundle = load_training_bundle()
health = bundle.health_metrics.copy()
snapshot = bundle.snapshot

if health.empty:
    st.info("No recovery data available yet. Import health metrics CSV to unlock this page.")
else:
    latest = snapshot["recovery"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sleep Score", format_metric_number(latest.get("sleep_score"), decimals=0))
    c2.metric("HRV", format_metric_number(latest.get("hrv"), decimals=0, suffix=" ms"))
    c3.metric("Resting HR", format_metric_number(latest.get("resting_hr"), decimals=0, suffix=" bpm"))
    c4.metric("Recovery Time", format_metric_number(latest.get("recovery_time"), decimals=0, suffix=" h"))

    col1, col2 = st.columns(2)
    col1.plotly_chart(sleep_recovery_chart(health), width="stretch")
    col2.plotly_chart(vo2max_trend_chart(health), width="stretch")

    hr_chart = px.line(
        health,
        x="date",
        y=["resting_hr", "hrv", "body_battery"],
        title="HRV, Resting HR, and Body Battery",
    )
    hr_chart.update_layout(template="plotly_white")
    st.plotly_chart(hr_chart, width="stretch")

    st.subheader("Sleep vs Performance")
    st.caption(f"Correlation between sleep score and pace: {snapshot['correlations']['correlation']:.3f}")
    st.plotly_chart(sleep_performance_chart(snapshot["correlations"]["series"]), width="stretch")
