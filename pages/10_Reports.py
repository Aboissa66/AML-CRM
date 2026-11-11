"""Reports: ready-made compliance reports from live Sanad data, with Excel and printable exports."""

import pandas as pd
import streamlit as st

import reports
from ui import setup

setup("Reports")
st.title("Reports")
st.caption("Ready-made compliance reports built from live Sanad data, for senior management, the Board, auditors "
           "and inspections.")

left, right = st.columns([1, 2.2])
with left:
    st.subheader("Choose a report")
    key = st.radio("Report", list(reports.REPORTS), label_visibility="collapsed",
                   format_func=lambda k: reports.REPORTS[k][0],
                   captions=[f"{d} For: {a}." for _, d, a in reports.REPORTS.values()])

with right:
    per = reports.periods()
    c1, c2 = st.columns([1.4, 1])
    period = c1.selectbox("Period", list(per))
    start, end = per[period]
    period_text = f"{period}: {start:%d %b %Y} to {end:%d %b %Y}"
    title, sections = reports.build(key, start, end)
    conclusions = ""
    if key == "mlro":
        conclusions = st.text_area("MLRO conclusions and actions for management",
                                   placeholder="Your overall view of the period, key risks, and what you ask "
                                               "management to approve or fund.")
    d1, d2 = st.columns(2)
    stem = f"Sanad_{title.replace(' ', '_')}_{start:%Y%m%d}-{end:%Y%m%d}"
    d1.download_button("⬇️ Excel", reports.to_excel(title, sections, period_text, conclusions), f"{stem}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                       width="stretch")
    d2.download_button("⬇️ Printable report (open, then print to PDF)",
                       reports.to_html(title, sections, period_text, conclusions), f"{stem}.html", "text/html",
                       width="stretch")

    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.caption(f"Sanad · AML & Sanctions CMS · CONFIDENTIAL · {period_text}")
        for head, body in sections:
            st.markdown(f"**{head}**")
            if isinstance(body, pd.DataFrame):
                if body.empty:
                    st.caption("None.")
                else:
                    st.dataframe(body, hide_index=True, width="stretch",
                                 height=min(38 + 35 * len(body), 360))
            else:
                st.markdown(body)
        if conclusions:
            st.markdown("**MLRO conclusions and actions for management**")
            st.markdown(conclusions)

with st.expander("📘 AML note: compliance reporting"):
    st.markdown("""
The **MLRO (compliance officer)** must keep senior management and the Board informed: at least an annual report,
and in practice a quarterly pack covering the customer risk profile, alerts and investigations, STRs, sanctions
matches, control testing results and policy status, with the MLRO's conclusions and what management must act on.

Reports to the **UAE FIU** (STR, SAR, PNMR, FFR) go through **goAML**, not through these internal reports. Keep each
report and the Board's response as evidence that senior management oversees AML/CFT risk.
""")
