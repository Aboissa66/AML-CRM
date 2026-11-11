"""Dashboard: the home page of the AML CRM (opened through Dashboard.py)."""

from datetime import date

import pandas as pd
import streamlit as st

import db
from ui import ASSETS, NEON, setup, stat_card

setup("Dashboard")
st.image(str(ASSETS / "sanad-logo.png"), width=420)
st.info("**Demo:** every customer, transaction and alert here is fictional. Explore freely: open a customer, "
        "check the sanctions alerts, or follow the open investigation on the Investigations page.", icon="🧪")
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
stat_card(d3, "Open investigations", int(cases.status.isin(["Open", "Investigating"]).sum()), NEON["cyan"], "under investigation")
stat_card(d4, "STRs filed", int((cases.status == "STR filed").sum()), NEON["violet"], "reported via goAML")

left, right = st.columns(2)
with left:
    st.subheader("Risk distribution")
    counts = df["risk_rating"].value_counts().reindex(["Low", "Medium", "High"], fill_value=0)
    st.bar_chart(pd.DataFrame({"Customers": counts}), horizontal=True)
with right:
    st.subheader("KYC status")
    st.bar_chart(pd.DataFrame({"Customers": df["kyc_status"].value_counts()}), horizontal=True)

st.subheader("Needs attention")
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
