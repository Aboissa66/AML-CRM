"""Dashboard: the home page of the AML CRM. Run with:  streamlit run Dashboard.py"""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import db
from ui import NEON, RISK_PALETTE, neon_chart, setup, stat_card

setup("Dashboard")
st.title("AML Compliance CRM")
st.caption("Customer due diligence, risk rating and periodic review, in one place.")

df = db.customers_df()
today = date.today().isoformat()
overdue = df[df["next_review"] < today]
expired_id = df[df["id_expiry"].notna() & (df["id_expiry"] < today)]
pending = df[df["kyc_status"].isin(["Pending", "Under review"])]
high = int((df["risk_rating"] == "High").sum())

c1, c2, c3, c4 = st.columns(4)
stat_card(c1, "Customers", len(df), NEON["cyan"], f"{(df.customer_type == 'Company').sum()} companies")
stat_card(c2, "High risk", high, NEON["pink"], f"{high / max(len(df), 1):.0%} of book")
stat_card(c3, "KYC open", len(pending), NEON["amber"], "pending or under review")
stat_card(c4, "Expired IDs", len(expired_id), NEON["violet"], f"{len(overdue)} reviews overdue")

import sanctions
import tm
tm.init()
s_open = int((sanctions.alerts_df().status == "Open").sum())
tm_alerts = tm.alerts_df()
cases = tm.cases_df()
d1, d2, d3, d4 = st.columns(4)
stat_card(d1, "Sanctions alerts", s_open, NEON["pink"], "open, awaiting review")
stat_card(d2, "TM alerts", int((tm_alerts.status == "Open").sum()), NEON["amber"],
          f"{int((tm_alerts[tm_alerts.status == 'Open'].severity.isin(['Critical', 'High'])).sum())} critical or high")
stat_card(d3, "Open cases", int(cases.status.isin(["Open", "Investigating"]).sum()), NEON["cyan"], "under investigation")
stat_card(d4, "STRs filed", int((cases.status == "STR filed").sum()), NEON["violet"], "reported via goAML")

risk_order = ["Low", "Medium", "High"]
scale = alt.Scale(domain=risk_order, range=[RISK_PALETTE[r] for r in risk_order])

left, mid, right = st.columns([1, 1.2, 1.2])
with left:
    st.markdown('<div class="panel-title">Risk mix</div>', unsafe_allow_html=True)
    counts = df["risk_rating"].value_counts().reindex(risk_order, fill_value=0).reset_index()
    counts.columns = ["Risk", "Customers"]
    base = alt.Chart(counts).encode(theta=alt.Theta("Customers:Q", stack=True),
                                    color=alt.Color("Risk:N", scale=scale, sort=risk_order, title=None,
                                                    legend=None),
                                    tooltip=["Risk", "Customers"])
    glow = base.mark_arc(innerRadius=62, outerRadius=100, opacity=0.25)
    ring = base.mark_arc(innerRadius=70, outerRadius=92, cornerRadius=6, padAngle=0.03)
    center = alt.Chart(pd.DataFrame({"t": [str(len(df))]})).mark_text(
        fontSize=30, fontWeight="bold", color=NEON["text"]).encode(text="t:N")
    st.altair_chart(neon_chart(glow + ring + center, height=230), width="stretch")
    st.markdown(" &nbsp; ".join(
        f'<span style="color:{RISK_PALETTE[r.Risk]};text-shadow:0 0 8px {RISK_PALETTE[r.Risk]}">●</span> '
        f'{r.Risk} <b>{r.Customers}</b>' for r in counts.itertuples()), unsafe_allow_html=True)

with mid:
    st.markdown('<div class="panel-title">Risk score spread</div>', unsafe_allow_html=True)
    bins = df.assign(band=(df["risk_score"] // 10 * 10).clip(upper=100))
    hist = bins.groupby(["band", "risk_rating"]).size().reset_index(name="Customers")
    bars = alt.Chart(hist).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=22).encode(
        x=alt.X("band:Q", title="Risk score", scale=alt.Scale(domain=[-5, 105])),
        y=alt.Y("Customers:Q", title=None),
        color=alt.Color("risk_rating:N", scale=scale, legend=None),
        tooltip=[alt.Tooltip("band:Q", title="Score from"), "risk_rating", "Customers"])
    rules = alt.Chart(pd.DataFrame({"x": [25, 50], "l": ["Medium", "High"]})).mark_rule(
        strokeDash=[4, 4], color=NEON["muted"]).encode(x="x:Q")
    st.altair_chart(neon_chart(bars + rules), width="stretch")

with right:
    st.markdown('<div class="panel-title">Book growth</div>', unsafe_allow_html=True)
    growth = (df.assign(month=pd.to_datetime(df["created_at"]).dt.to_period("M").dt.to_timestamp())
                .groupby("month").size().cumsum().reset_index(name="Customers"))
    gradient = alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                            stops=[alt.GradientStop(color="rgba(0,229,255,0)", offset=0),
                                   alt.GradientStop(color="rgba(0,229,255,0.45)", offset=1)])
    area = alt.Chart(growth).mark_area(line={"color": NEON["cyan"], "strokeWidth": 2.5},
                                       color=gradient, interpolate="monotone").encode(
        x=alt.X("month:T", title=None, axis=alt.Axis(format="%b %y", grid=False)),
        y=alt.Y("Customers:Q", title=None), tooltip=[alt.Tooltip("month:T", format="%b %Y"), "Customers"])
    st.altair_chart(neon_chart(area), width="stretch")

st.markdown('<div class="panel-title">KYC pipeline</div>', unsafe_allow_html=True)
status_order = ["Pending", "Under review", "Approved", "Rejected"]
kyc = df["kyc_status"].value_counts().reindex(status_order, fill_value=0).reset_index()
kyc.columns = ["Status", "Customers"]
kyc_colors = [NEON["amber"], NEON["violet"], NEON["green"], NEON["pink"]]
kyc_bars = alt.Chart(kyc).mark_bar(cornerRadiusEnd=8, height=18).encode(
    y=alt.Y("Status:N", sort=status_order, title=None, axis=alt.Axis(labelLimit=200, labelFontSize=13)),
    x=alt.X("Customers:Q", title=None),
    color=alt.Color("Status:N", scale=alt.Scale(domain=status_order, range=kyc_colors), legend=None),
    tooltip=["Status", "Customers"])
kyc_labels = kyc_bars.mark_text(align="left", dx=8, color=NEON["text"], fontSize=13).encode(text="Customers:Q")
st.altair_chart(neon_chart(kyc_bars + kyc_labels, height=170), width="stretch")

st.markdown('<div class="panel-title">Needs attention</div>', unsafe_allow_html=True)
cols = ["id", "full_name", "customer_type", "risk_rating", "kyc_status", "id_expiry", "next_review"]
tab1, tab2, tab3 = st.tabs([f"Expired ID / licence ({len(expired_id)})",
                            f"KYC pending ({len(pending)})",
                            f"Review overdue ({len(overdue)})"])
labels = {"id": "ID", "full_name": "Name", "customer_type": "Type", "risk_rating": "Risk",
          "kyc_status": "KYC", "id_expiry": "ID expiry", "next_review": "Next review"}
for tab, part in ((tab1, expired_id), (tab2, pending), (tab3, overdue)):
    tab.dataframe(part[cols], hide_index=True, width="stretch", column_config=labels)
st.info("Open **Customers** in the sidebar to work on any of these.")

with st.expander("📘 AML note: why a risk-based approach?"):
    st.markdown("""
UAE Federal Decree-Law No. 20 of 2018 (as amended) and Cabinet Decision No. 10 of 2019 require
financial institutions and DNFBPs to apply a **risk-based approach**: assess each customer's
money laundering and terrorist financing risk, then scale due diligence to match.

* **Low risk** customers may get simplified due diligence (where permitted).
* **Medium risk** customers get standard CDD.
* **High risk** customers (PEPs, high-risk countries, high-risk sectors) need **enhanced due
  diligence**: source of wealth, senior management approval and more frequent reviews.

The **periodic review** date in this app follows that idea: High every year, Medium every 2 years,
Low every 3 years. These intervals are common practice, not fixed by law, so each firm sets its own.
""")
