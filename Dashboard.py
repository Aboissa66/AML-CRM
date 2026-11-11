"""Entry point of Sanad. Run with:  streamlit run Dashboard.py

It shows the sign-in page until someone signs in, then sets the order, names and sections of the pages
in the sidebar, keeping only the pages the signed-in role may see. Each page lives in pages/.
"""

import streamlit as st

import auth

if not auth.signed_in():
    st.navigation([st.Page(auth.login_page, title="Sign in", url_path="sign-in")], position="hidden").run()
    st.stop()

sections = {
    "": [
        st.Page("pages/0_Home.py", title="Dashboard", icon="🏠", default=True),
        st.Page("pages/1_Customers.py", title="Customers", icon="👥"),
        st.Page("pages/2_Add_Customer.py", title="Add Customer", icon="➕"),
        st.Page("pages/3_Ownership_UBO.py", title="Ownership & UBO", icon="🕸️"),
        st.Page("pages/4_Sanctions_Screening.py", title="Sanctions Screening", icon="🛰️"),
        st.Page("pages/5_Transaction_Monitoring.py", title="Transaction Monitoring", icon="💸"),
        st.Page("pages/6_Investigations.py", title="Investigations", icon="🗂️"),
    ],
    "Governance": [
        st.Page("pages/11_Governance_Dashboard.py", title="Governance Dashboard", icon="🛡️"),
        st.Page("pages/8_Policy_Management.py", title="Policy Management", icon="📘"),
        st.Page("pages/9_Effectiveness_Testing.py", title="Effectiveness Testing", icon="🧪"),
        st.Page("pages/10_Reports.py", title="Reports", icon="📄"),
        st.Page("pages/7_Audit_Log.py", title="Audit Log", icon="📜"),
    ],
}
# Each role sees only its own pages (see auth.ROLES).
visible = {sec: [p for p in pages if auth.allowed(p.title)] for sec, pages in sections.items()}
nav = st.navigation({sec: pages for sec, pages in visible.items() if pages})
nav.run()
