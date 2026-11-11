"""Shared Streamlit pieces used by several pages."""

import streamlit as st

import db
from risk import ACTIVITIES, CHANNELS, COUNTRIES, SOURCES_OF_FUNDS

RATING_COLORS = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}


# Neon palette shared by the CSS and every chart.
NEON = {
    "cyan": "#00E5FF", "violet": "#8B5CF6", "pink": "#FF3D71", "amber": "#FFB020",
    "green": "#00F5A0", "text": "#E6F1FF", "muted": "#7D8BA6", "grid": "#1B2740",
}
RISK_PALETTE = {"Low": NEON["green"], "Medium": NEON["amber"], "High": NEON["pink"]}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Exo+2:wght@300;400;600&display=swap');
html, body, .stMarkdown, p, label, input, textarea, [data-testid="stWidgetLabel"] { font-family: 'Exo 2', sans-serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded { font-family: 'Material Symbols Rounded' !important; }
h1, h2, h3, h4 { font-family: 'Orbitron', sans-serif !important; letter-spacing: .04em; }
h1 { background: linear-gradient(90deg, #00E5FF, #8B5CF6 60%, #FF3D71);
     -webkit-background-clip: text; background-clip: text; color: transparent !important; }
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(139,92,246,.18), transparent 60%),
    radial-gradient(900px 500px at -10% 20%, rgba(0,229,255,.12), transparent 60%),
    linear-gradient(rgba(0,229,255,.035) 1px, transparent 1px) 0 0 / 40px 40px,
    linear-gradient(90deg, rgba(0,229,255,.035) 1px, transparent 1px) 0 0 / 40px 40px,
    #060A14;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0B1222, #070B16);
  border-right: 1px solid rgba(0,229,255,.15); }
.neon-card { position: relative; padding: 18px 20px; border-radius: 16px;
  background: linear-gradient(145deg, rgba(14,22,38,.85), rgba(10,16,30,.6));
  border: 1px solid rgba(0,229,255,.18); backdrop-filter: blur(8px);
  box-shadow: 0 0 0 1px rgba(255,255,255,.02) inset, 0 10px 30px rgba(0,0,0,.35); overflow: hidden; }
.neon-card::before { content: ""; position: absolute; left: 0; top: 0; height: 2px; width: 100%;
  background: linear-gradient(90deg, transparent, var(--c), transparent); }
.neon-card .lbl { color: #7D8BA6; font-size: .78rem; text-transform: uppercase; letter-spacing: .14em; }
.neon-card .val { font-family: 'Orbitron', sans-serif; font-size: 2.3rem; font-weight: 700; color: var(--c);
  text-shadow: 0 0 18px var(--c); line-height: 1.2; margin-top: 6px; }
.neon-card .sub { color: #7D8BA6; font-size: .8rem; }
.panel-title { font-family: 'Orbitron', sans-serif; font-size: .85rem; letter-spacing: .18em;
  text-transform: uppercase; color: #9FB3D1; margin: 8px 0 2px; }
[data-testid="stVegaLiteChart"], [data-testid="stDataFrame"], [data-testid="stExpander"], [data-testid="stForm"] {
  border-radius: 16px; border: 1px solid rgba(0,229,255,.12);
  background: rgba(14,22,38,.55); padding: 6px; }
.stButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: 10px; border: 1px solid #00E5FF; box-shadow: 0 0 14px rgba(0,229,255,.35); }
.stTabs [data-baseweb="tab"] { font-family: 'Orbitron', sans-serif; font-size: .75rem; letter-spacing: .08em; }
</style>
"""


def setup(title: str):
    st.set_page_config(page_title=f"AML CRM · {title}", page_icon="🛡️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
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


def stat_card(col, label: str, value, color: str, sub: str = ""):
    col.markdown(f'<div class="neon-card" style="--c:{color}"><div class="lbl">{label}</div>'
                 f'<div class="val">{value}</div><div class="sub">{sub}</div></div>',
                 unsafe_allow_html=True)
