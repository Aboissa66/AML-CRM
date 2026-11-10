"""Onboard a new customer."""

import streamlit as st

import db
import sanctions
from risk import score_customer
from ui import badge, customer_form, setup

setup("Add customer")
st.title("Onboard a customer")
st.caption("Fill in the KYC details. The risk rating and document checklist are generated automatically.")

new = customer_form("add_customer")
if new:
    cid = db.add_customer(new, st.session_state["user"])
    hits = sanctions.screen(cid, st.session_state.get("screen_threshold", 85), st.session_state["user"])
    if hits:
        st.error(f"Sanctions screening raised {hits} alert(s) for this customer. Review them on the "
                 "Sanctions Screening page before approving.")
    score, rating, reasons = score_customer(new)
    st.success(f"Created customer #{cid}: {new['full_name']} rated {badge(rating)} (score {score}).")
    for r in reasons:
        st.markdown(f"- {r}")
    st.session_state["open_customer"] = cid
    st.page_link("pages/1_Customers.py", label="Open the customer profile", icon="👥")
