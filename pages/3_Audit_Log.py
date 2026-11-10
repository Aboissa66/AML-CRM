"""Every action taken in the app, newest first."""

import streamlit as st

import db
from ui import setup

setup("Audit log")
st.title("Audit log")
log = db.audit_df()
hide_seed = st.toggle("Hide seed data entries", value=True)
if hide_seed:
    log = log[log["user"] != "seed"]
st.dataframe(log, hide_index=True, width="stretch")

with st.sidebar:
    st.divider()
    if st.button("Reset to fresh dummy data"):
        import seed
        seed.main()
        st.rerun()
