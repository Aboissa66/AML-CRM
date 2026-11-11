"""Demo sign-in with roles. Each role sees its own set of pages, and the signed-in name goes into the audit log.

This is a DEMO login: the accounts and passwords are public and filled in for you. For real use, replace it with
proper accounts (hashed passwords) or single sign-on such as Streamlit's st.login.
"""

import streamlit as st

DEMO_PASSWORD = "sanad-demo"

ALL = None   # sees every page
ROLES = {
    "MLRO": {"name": "Layla Haddad", "username": "layla.mlro", "pages": ALL,
             "about": "Runs the AML/CFT programme. Sees and does everything."},
    "Compliance Analyst": {"name": "Omar Farouk", "username": "omar.analyst",
                           "pages": {"Dashboard", "Customers", "Add Customer", "Ownership & UBO",
                                     "Sanctions Screening", "Transaction Monitoring", "Investigations",
                                     "Reports", "Audit Log"},
                           "about": "Onboards customers, reviews alerts and investigates. No governance pages."},
    "Senior Management": {"name": "Sara Al Nuaimi", "username": "sara.ceo",
                          "pages": {"Dashboard", "Customers", "Investigations", "Governance Dashboard",
                                    "Policy Management", "Effectiveness Testing", "Reports", "Audit Log"},
                          "about": "Oversees the programme: governance pages, customers and investigations."},
    "Board": {"name": "Khalid Rahman", "username": "khalid.board",
              "pages": {"Dashboard", "Governance Dashboard", "Policy Management", "Reports"},
              "about": "Approves policies and reviews reports. Governance view only."},
}


def signed_in() -> bool:
    return st.session_state.get("role") in ROLES


def allowed(page_title: str) -> bool:
    pages = ROLES[st.session_state["role"]]["pages"]
    return pages is ALL or page_title in pages


def sign_out():
    for k in ("role", "user"):
        st.session_state.pop(k, None)
    st.rerun()


def login_page():
    from ui import ASSETS
    st.set_page_config(page_title="Sanad · Sign in", page_icon=str(ASSETS / "sanad-mark.png"), layout="centered",
                       initial_sidebar_state="expanded")
    # Something in the sidebar keeps it open, so it is still open after signing in.
    st.logo(str(ASSETS / "sanad-logo-compact.png"), icon_image=str(ASSETS / "sanad-mark.png"), size="large")
    with st.sidebar:
        st.markdown("**Welcome to Sanad**")
        st.caption("Pick a role and sign in. Each role sees the pages that person would use in a real "
                   "compliance team. You can sign out and try another role at any time.")
    _, mid, _ = st.columns([1, 6, 1])
    with mid:
        st.image(str(ASSETS / "sanad-logo.png"), width=360)
        st.caption("Customer due diligence, sanctions screening, monitoring and governance, in one place.")
        with st.container(border=True):
            st.subheader("Sign in")
            role = st.radio("Sign in as", list(ROLES), captions=[r["about"] for r in ROLES.values()])
            r = ROLES[role]
            username = st.text_input("Username", r["username"], key=f"user_{role}")
            password = st.text_input("Password", DEMO_PASSWORD, type="password", key=f"pw_{role}")
            if st.button(f"Sign in as {r['name']}", type="primary", width="stretch"):
                if username.strip().lower() == r["username"] and password == DEMO_PASSWORD:
                    st.session_state["role"] = role
                    st.session_state["user"] = r["name"]
                    st.rerun()
                else:
                    st.error("Wrong username or password.")
        st.info(f"**Demo:** the accounts are fictional and the password (**{DEMO_PASSWORD}**) is filled in for "
                "you. Pick a role to see what each person in a compliance team would see.", icon="🧪")
