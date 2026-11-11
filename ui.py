"""Shared Streamlit pieces used by several pages."""

import streamlit as st

import db
from risk import ACTIVITIES, CHANNELS, COUNTRIES, SOURCES_OF_FUNDS

RATING_COLORS = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}


# Colour palette for the ownership tree and number cards (Streamlit's default light theme).
NEON = {
    "cyan": "#0068C9", "violet": "#6D3FC0", "pink": "#D62728", "amber": "#E07B00",
    "green": "#2CA02C", "text": "#31333F", "muted": "#808495", "grid": "#E6EAF1",
}
RISK_PALETTE = {"Low": NEON["green"], "Medium": NEON["amber"], "High": NEON["pink"]}


def setup(title: str):
    st.set_page_config(page_title=f"AML CRM · {title}", page_icon="🛡️", layout="wide")
    if db.is_empty():
        import seed
        seed.main()
    elif db.owners_missing():   # database created before the UBO module existed
        import seed
        seed.seed_owners()
    import sanctions
    if not sanctions.has_list("Training list"):   # always have the fictional training list to practise with
        sanctions.load_training_list()
        sanctions.screen(user="seed")
    with st.sidebar:
        st.caption("Prototype with dummy data only. Not for real customer data.")
        st.session_state.setdefault("user", "analyst")
        st.session_state["user"] = st.text_input("Your name (for the audit log)", st.session_state["user"])


def badge(rating: str) -> str:
    return f"{RATING_COLORS.get(rating, '')} {rating}"


def _idx(options, value, default=0):
    return options.index(value) if value in options else default


def customer_form(key: str, existing: dict | None = None) -> dict | None:
    """Add or edit form. Returns the field values when submitted, else None."""
    e = existing or {}
    with st.form(key):
        ctype = st.radio("Customer type", ["Individual", "Company"],
                         index=_idx(["Individual", "Company"], e.get("customer_type")), horizontal=True)
        is_co = ctype == "Company"
        c1, c2 = st.columns(2)
        name = c1.text_input("Legal name" if is_co else "Full name", e.get("full_name", ""))
        dob = c2.text_input("Date of incorporation" if is_co else "Date of birth (YYYY-MM-DD)",
                            e.get("date_of_birth") or "")
        nationality = c1.selectbox("Country of incorporation" if is_co else "Nationality", COUNTRIES,
                                   index=_idx(COUNTRIES, e.get("nationality", "United Arab Emirates")))
        residence = c2.selectbox("Country of operations" if is_co else "Country of residence", COUNTRIES,
                                 index=_idx(COUNTRIES, e.get("residence_country", "United Arab Emirates")))
        id_number = c1.text_input("Trade licence no." if is_co else "Emirates ID / passport no.",
                                  e.get("id_number") or "")
        id_expiry = c2.text_input("Licence / ID expiry (YYYY-MM-DD)", e.get("id_expiry") or "")
        activity = c1.selectbox("Business activity" if is_co else "Occupation", ACTIVITIES,
                                index=_idx(ACTIVITIES, e.get("activity")))
        sof = c2.selectbox("Source of funds", SOURCES_OF_FUNDS, index=_idx(SOURCES_OF_FUNDS, e.get("source_of_funds")))
        volume = c1.number_input("Expected monthly volume (AED)", min_value=0.0, step=10_000.0,
                                 value=float(e.get("expected_monthly_volume") or 0))
        channel = c2.selectbox("Onboarding channel", CHANNELS, index=_idx(CHANNELS, e.get("channel")))
        pep = c1.checkbox("Politically exposed person (PEP)" + (" among owners / directors" if is_co else ""),
                          bool(e.get("pep")))
        cash = c2.checkbox("Cash intensive", bool(e.get("cash_intensive")))
        submitted = st.form_submit_button("Save customer", type="primary")
    if not submitted:
        return None
    if not name.strip():
        st.error("Name is required.")
        return None
    return dict(customer_type=ctype, full_name=name.strip(), date_of_birth=dob or None,
                nationality=nationality, residence_country=residence, id_number=id_number or None,
                id_expiry=id_expiry or None, activity=activity, source_of_funds=sof,
                expected_monthly_volume=volume, pep=int(pep), cash_intensive=int(cash), channel=channel)


def stat_card(col, label: str, value, color: str = "", sub: str = ""):
    """A plain Streamlit number tile with a short note underneath."""
    col.metric(label, value)
    if sub:
        col.caption(sub)
