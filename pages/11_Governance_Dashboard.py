"""Governance dashboard: one view of the AML/CFT programme's health for senior management and the Board."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db
import governance as gov
import sanctions
import tm
from ui import setup, stat_card

setup("Governance dashboard")
st.title("Governance dashboard")
st.caption("The health of the AML/CFT and sanctions programme in one view: policies, control testing, findings "
           "and operational backlog. Built for senior management and the Board.")

policies = gov.policies_df()
tests = gov.tests_df()
findings = gov.findings_df()
areas = gov.area_status(tests, findings)
controls = gov.policy_controls()
attention = gov.attention_items(policies, tests, findings)

approved = policies[policies.status != "Draft"]
current = int((approved.status == "Current").sum())
att = approved.staff_attested.sum() / max(approved.staff_total.sum(), 1)
tested = areas[areas.Result != "Not tested"]
effective = int((tested.Result == "Effective").sum())
open_f = findings[findings.status != "Closed"]
matches = sum(c["Status"] == "Matches" for c in controls)

st.subheader("Programme health")
k = st.columns(5)
stat_card(k[0], "Policies current", f"{current} of {len(approved)}",
          sub=f"{len(policies) - len(approved)} in draft")
stat_card(k[1], "Staff attestation", f"{att:.0%}", sub="across approved policies")
stat_card(k[2], "Controls effective", f"{effective} of {len(areas)}",
          sub=f"{len(areas) - len(tested)} area(s) not tested")
stat_card(k[3], "Open findings", len(open_f), sub=f"{int((open_f.status == 'Overdue').sum())} overdue")
stat_card(k[4], "Policy vs system", f"{matches} of {len(controls)}", sub="settings match the policy")

st.subheader("Operational risk indicators")
customers = db.customers_df()
today = date.today().isoformat()
tm.init()
alerts = tm.alerts_df()
cases = tm.cases_df()
s_alerts = sanctions.alerts_df()
o = st.columns(5)
stat_card(o[0], "High risk customers", int((customers.risk_rating == "High").sum()),
          sub=f"of {len(customers)} customers")
stat_card(o[1], "Reviews overdue", int((customers.next_review < today).sum()), sub="periodic KYC reviews")
stat_card(o[2], "Sanctions alerts open", int((s_alerts.status == "Open").sum()), sub="awaiting a decision")
stat_card(o[3], "TM alerts open", int((alerts.status == "Open").sum()), sub="awaiting triage")
stat_card(o[4], "STRs filed", int((cases.status == "STR filed").sum()),
          sub=f"{int(cases.status.isin(['Open', 'Investigating']).sum())} open investigation(s)")

st.subheader("Needs management attention")
if attention.empty:
    st.success("Nothing needs attention right now.")
else:
    label = {1: "🔴 Act now", 2: "🟠 This month", 3: "🔵 Monitor"}
    n = attention.priority.value_counts()
    st.caption(" · ".join(f"{label[p]}: {n.get(p, 0)}" for p in (1, 2, 3)))
    st.dataframe(attention.assign(Priority=attention.priority.map(label))[["Priority", "Type", "Item", "Owner"]],
                 hide_index=True, width="stretch", height=min(38 + 35 * len(attention), 420))

left, right = st.columns([2.4, 1])
with left:
    st.subheader("Control areas")
    icon = {"Effective": "🟢 Effective", "Partially effective": "🟠 Partially effective",
            "Ineffective": "🔴 Ineffective", "Not tested": "⚪ Not tested"}
    sched = {"On schedule": "✅ On schedule", "Test overdue": "⚠️ Test overdue", "Never tested": "⚠️ Never tested"}
    st.dataframe(areas.assign(Result=areas.Result.map(icon), Schedule=areas.Schedule.map(sched))
                 .fillna("-").drop(columns="Overdue findings").rename(columns={"Open findings": "Findings"}),
                 hide_index=True, width="stretch", height=38 + 35 * len(areas))
with right:
    st.subheader("Test results by quarter")
    t = tests.assign(d=pd.to_datetime(tests.tested_on, errors="coerce")).dropna(subset=["d"])
    t = t[t.d >= pd.Timestamp(date.today() - timedelta(days=365))]
    if t.empty:
        st.caption("No tests in the last 12 months.")
    else:
        q = t.d.dt.to_period("Q").astype(str)
        chart = pd.crosstab(q, t.result).reindex(columns=gov.RESULTS, fill_value=0)
        st.bar_chart(chart, color=["#2CA02C", "#E07B00", "#D62728"], height=330)

st.subheader("Coming up in the next 90 days")
horizon = (date.today() + timedelta(days=90)).isoformat()


def soon(d) -> bool:
    return isinstance(d, str) and today <= d <= horizon


up = [("Policy review", f"{p.name} {p.version}", p.next_review, p.owner)
      for p in approved.itertuples() if soon(p.next_review)]
up += [("Finding due", f.finding, f.due, f.owner)
       for f in open_f.itertuples() if soon(f.due)]
up += [("Control test", a["Control area"], a["Next test due"], "Compliance")
       for a in areas.to_dict("records") if soon(a["Next test due"])]
if up:
    st.dataframe(pd.DataFrame(up, columns=["What", "Item", "Date", "Owner"]).sort_values("Date"),
                 hide_index=True, width="stretch")
else:
    st.caption("Nothing scheduled in the next 90 days.")

with st.expander("📘 AML note: governance and senior management oversight"):
    st.markdown("""
UAE law puts responsibility for the AML/CFT programme on **senior management and the Board**, not only on the MLRO.
They must approve the policies, make sure the controls are adequate and tested, and act on what testing finds.

A governance dashboard turns that into a short list of questions: are our policies **current and approved**, do
staff **know them**, do our systems **apply them**, do the controls **work**, and are **findings fixed on time**?
The "Needs management attention" list is what the MLRO would raise at the next management or Board meeting.
""")
