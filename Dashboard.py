"""Entry point of the AML CRM. Run with:  streamlit run Dashboard.py

It only sets the order and names of the pages in the sidebar. Each page lives in pages/.
"""

import streamlit as st

nav = st.navigation([
    st.Page("pages/0_Home.py", title="Dashboard", icon="🏠", default=True),
    st.Page("pages/1_Customers.py", title="Customers", icon="👥"),
    st.Page("pages/2_Add_Customer.py", title="Add Customer", icon="➕"),
    st.Page("pages/3_Ownership_UBO.py", title="Ownership & UBO", icon="🕸️"),
    st.Page("pages/4_Sanctions_Screening.py", title="Sanctions Screening", icon="🛰️"),
    st.Page("pages/5_Transaction_Monitoring.py", title="Transaction Monitoring", icon="💸"),
    st.Page("pages/6_Investigations.py", title="Investigations", icon="🗂️"),
    st.Page("pages/7_Audit_Log.py", title="Audit Log", icon="📜"),
])
nav.run()
