"""Enterprise-wide risk assessment (EWRA): how exposed the whole firm is to ML/TF/PF and sanctions risk.

For each risk factor:
  inherent risk     from live Sanad data (thresholds in INHERENT_RULES below), or an MLRO override with a reason
  control strength  from the latest Effectiveness testing result of the control areas mapped to the factor
  residual risk     inherent adjusted by control strength (RESIDUAL matrix)
The assessment goes through the same approval workflow as policies. When the Board approves it, the results
are frozen (snapshot) so the approved version never changes afterwards.
"""

import json
from datetime import date

import pandas as pd

import db
import governance as gov

WORKFLOW = gov.WORKFLOW
LEVELS = ["Low", "Medium", "Medium-High", "High"]          # residual levels, in order
INHERENT_LEVELS = ["Low", "Medium", "High"]
STRENGTHS = ["Strong", "Adequate", "Needs improvement", "Weak"]

# Residual risk = RESIDUAL[inherent][control strength]
RESIDUAL = {
    "High": {"Strong": "Medium", "Adequate": "Medium-High", "Needs improvement": "High", "Weak": "High"},
    "Medium": {"Strong": "Low", "Adequate": "Medium", "Needs improvement": "Medium", "Weak": "Medium-High"},
    "Low": {"Strong": "Low", "Adequate": "Low", "Needs improvement": "Low", "Weak": "Medium"},
}

# Factor -> control areas (from Effectiveness testing) that mitigate it
FACTORS = {
    "Customers": ["KYC / CDD", "UBO identification", "Periodic review"],
    "Geography": ["Sanctions screening"],
    "Products and services": [],
    "Delivery channels": ["KYC / CDD"],
    "Transactions": ["Transaction monitoring", "Alert handling"],
    "Sanctions and proliferation financing": ["Sanctions screening"],
}

INHERENT_RULES = {
    "Customers": "High if over 25% of customers are High risk or over 40% are in high-risk activities; "
                 "Medium if over 10% are High risk or any PEP; otherwise Low.",
    "Geography": "High if any customer is linked to a FATF black list country or over 20% of volume is with "
                 "grey or black list countries; Medium if over 5% of customers or volume; otherwise Low.",
    "Products and services": "Set by the MLRO from the products the firm offers.",
    "Delivery channels": "High if over 40% of customers were onboarded non face to face; Medium if over 15%; "
                         "otherwise Low.",
    "Transactions": "High if over 20% of value is cash; Medium if over 10% or over 10 open monitoring alerts; "
                    "otherwise Low.",
    "Sanctions and proliferation financing": "High if any confirmed sanctions match; Medium if any open or "
                                             "potential match; otherwise Low.",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ewra (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER, version TEXT, stage INTEGER DEFAULT 0, appetite TEXT DEFAULT 'Medium',
    products_text TEXT, products_rating TEXT DEFAULT 'Medium',
    created_on TEXT, approved_on TEXT, snapshot TEXT
);
CREATE TABLE IF NOT EXISTS ewra_overrides (
    ewra_id INTEGER, factor TEXT, rating TEXT, reason TEXT, by_user TEXT, on_date TEXT,
    PRIMARY KEY (ewra_id, factor)
);
CREATE TABLE IF NOT EXISTS ewra_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ewra_id INTEGER, factor TEXT, action TEXT, owner TEXT, due TEXT, status TEXT DEFAULT 'Open', note TEXT
);
"""


def init():
    with db.connect() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Live indicators and scoring
# ---------------------------------------------------------------------------
def indicators() -> dict:
    """The live numbers each factor is rated on."""
    import risk
    import sanctions
    import tm
    c = db.customers_df()
    n = max(len(c), 1)
    grey_black = risk.FATF_BLACKLIST | risk.FATF_GREYLIST
    linked = c.nationality.isin(grey_black) | c.residence_country.isin(grey_black)
    black = c.nationality.isin(risk.FATF_BLACKLIST) | c.residence_country.isin(risk.FATF_BLACKLIST)
    tm.init()
    t = tm.transactions_df()
    vol = t.amount_aed.sum() if not t.empty else 0
    alerts = tm.alerts_df()
    s = sanctions.alerts_df()
    return {
        "customers": len(c),
        "high_pct": 100 * (c.risk_rating == "High").sum() / n,
        "high": int((c.risk_rating == "High").sum()),
        "peps": int(c.pep.fillna(0).astype(int).sum()),
        "high_activity_pct": 100 * c.activity.isin(risk.HIGH_RISK_ACTIVITIES).sum() / n,
        "company_pct": 100 * (c.customer_type == "Company").sum() / n,
        "geo_cust_pct": 100 * linked.sum() / n,
        "geo_black": int(black.sum()),
        "geo_vol_pct": 100 * t[t.counterparty_country.isin(grey_black)].amount_aed.sum() / vol if vol else 0,
        "nf2f_pct": 100 * (c.channel == "Non face to face").sum() / n,
        "nf2f": int((c.channel == "Non face to face").sum()),
        "cash_pct": 100 * t[t.channel == "Cash"].amount_aed.sum() / vol if vol else 0,
        "cash_intensive": int(c.cash_intensive.fillna(0).astype(int).sum()),
        "tm_open": int((alerts.status == "Open").sum()),
        "tm_alerts": len(alerts),
        "cases_open": int(tm.cases_df().status.isin(["Open", "Investigating"]).sum()),
        "s_open": int((s.status == "Open").sum()),
        "s_potential": int((s.status == "Potential match (escalate)").sum()),
        "s_true": int((s.status == "True match").sum()),
    }


def _auto_inherent(factor: str, i: dict, products_rating: str) -> tuple[str, str]:
    """(rating, the live figures it is based on)."""
    if factor == "Customers":
        text = (f"{i['high_pct']:.0f}% of customers High risk ({i['high']} of {i['customers']}) · {i['peps']} PEP(s) · "
                f"{i['high_activity_pct']:.0f}% in high-risk activities · {i['company_pct']:.0f}% companies")
        r = ("High" if i["high_pct"] > 25 or i["high_activity_pct"] > 40
             else "Medium" if i["high_pct"] > 10 or i["peps"] else "Low")
    elif factor == "Geography":
        text = (f"{i['geo_cust_pct']:.0f}% of customers linked to FATF grey or black list countries · "
                f"{i['geo_vol_pct']:.0f}% of volume with those countries")
        r = ("High" if i["geo_black"] or i["geo_vol_pct"] > 20
             else "Medium" if i["geo_cust_pct"] > 5 or i["geo_vol_pct"] > 5 else "Low")
    elif factor == "Products and services":
        text, r = "Set by the MLRO (see below)", products_rating
    elif factor == "Delivery channels":
        text = f"{i['nf2f_pct']:.0f}% onboarded non face to face ({i['nf2f']} of {i['customers']})"
        r = "High" if i["nf2f_pct"] > 40 else "Medium" if i["nf2f_pct"] > 15 else "Low"
    elif factor == "Transactions":
        text = (f"{i['cash_pct']:.0f}% of value in cash · {i['cash_intensive']} cash-intensive customers · "
                f"{i['tm_open']} open monitoring alerts · {i['cases_open']} investigation(s) open")
        r = "High" if i["cash_pct"] > 20 else "Medium" if i["cash_pct"] > 10 or i["tm_open"] > 10 else "Low"
    else:
        text = (f"{i['s_open']} open screening alert(s) · {i['s_potential']} potential match(es) · "
                f"{i['s_true']} confirmed match(es)")
        r = "High" if i["s_true"] else "Medium" if i["s_open"] or i["s_potential"] else "Low"
    return r, text


def _latest_results() -> dict:
    """Latest Effectiveness testing result per control area."""
    t = gov.tests_df().sort_values(["tested_on", "id"])
    return {area: g.iloc[-1].result for area, g in t.groupby("area")}


def control_strength(areas: list[str], latest: dict) -> tuple[str, str]:
    """Any Ineffective = Weak; all Effective = Strong; mostly Effective = Adequate; otherwise (or never tested)
    Needs improvement."""
    if not areas:
        return "Needs improvement", "No control test mapped"
    results = [latest.get(a, "Not tested") for a in areas]
    text = " · ".join(f"{a}: {r}" for a, r in zip(areas, results))
    eff = results.count("Effective")
    if "Ineffective" in results:
        s = "Weak"
    elif eff == len(results):
        s = "Strong"
    elif eff > len(results) / 2:
        s = "Adequate"
    else:
        s = "Needs improvement"
    return s, text


def overall(levels: list[str]) -> str:
    """The highest factor level, except that a single High factor gives Medium-High; two or more give High."""
    if not levels:
        return "Low"
    if levels.count("High") >= 2:
        return "High"
    top = max(levels, key=LEVELS.index)
    return "Medium-High" if top == "High" else top


def above(level: str, appetite: str) -> bool:
    return LEVELS.index(level) > LEVELS.index(appetite)


def compute(e: dict) -> pd.DataFrame:
    """One row per factor with inherent, control strength and residual risk. Frozen once approved."""
    if e.get("snapshot"):
        return pd.DataFrame(json.loads(e["snapshot"]))
    i = indicators()
    latest = _latest_results()
    over = overrides(e["id"])
    rows = []
    for factor, areas in FACTORS.items():
        auto, text = _auto_inherent(factor, i, e.get("products_rating") or "Medium")
        o = over.get(factor)
        inh = o["rating"] if o else auto
        strength, ctl = control_strength(areas, latest)
        res = RESIDUAL[inh][strength]
        rows.append({"Risk factor": factor, "Live indicators": text, "Calculated": auto,
                     "Inherent": inh, "Override reason": o["reason"] if o else "",
                     "Controls (latest test)": ctl, "Control strength": strength, "Residual": res,
                     "Above appetite": above(res, e.get("appetite") or "Medium")})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Assessments, overrides, actions
# ---------------------------------------------------------------------------
def assessments_df() -> pd.DataFrame:
    init()
    with db.connect() as conn:
        return pd.read_sql_query("SELECT * FROM ewra ORDER BY year DESC, id DESC", conn)


def get(eid: int) -> dict:
    with db.connect() as conn:
        return dict(conn.execute("SELECT * FROM ewra WHERE id=?", (eid,)).fetchone())


def latest_approved() -> dict | None:
    a = assessments_df()
    a = a[a.stage >= 3]
    return a.iloc[0].to_dict() if not a.empty else None


def create(year: int, appetite: str, products_text: str, products_rating: str, user="analyst") -> int:
    init()
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM ewra WHERE year=?", (year,)).fetchone()[0]
        cur = conn.execute("INSERT INTO ewra (year, version, stage, appetite, products_text, products_rating, "
                           "created_on) VALUES (?,?,?,?,?,?,?)",
                           (year, f"v{n + 1}.0", 0, appetite, products_text, products_rating,
                            date.today().isoformat()))
        db.log(conn, "ewra", cur.lastrowid, "created", f"EWRA {year} v{n + 1}.0, appetite {appetite}", user)
    return cur.lastrowid


def update_settings(eid: int, appetite: str, products_text: str, products_rating: str, user="analyst"):
    with db.connect() as conn:
        conn.execute("UPDATE ewra SET appetite=?, products_text=?, products_rating=? WHERE id=?",
                     (appetite, products_text, products_rating, eid))
        db.log(conn, "ewra", eid, "settings changed",
               f"appetite {appetite}; products {products_rating}: {products_text}", user)


def overrides(eid: int) -> dict:
    with db.connect() as conn:
        return {r["factor"]: dict(r) for r in conn.execute("SELECT * FROM ewra_overrides WHERE ewra_id=?", (eid,))}


def set_override(eid: int, factor: str, rating: str | None, reason: str, user="analyst"):
    """rating None removes the override (back to the calculated rating)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM ewra_overrides WHERE ewra_id=? AND factor=?", (eid, factor))
        if rating:
            conn.execute("INSERT INTO ewra_overrides VALUES (?,?,?,?,?,?)",
                         (eid, factor, rating, reason, user, date.today().isoformat()))
        db.log(conn, "ewra", eid, f"inherent override: {factor}",
               f"{rating or 'removed, back to calculated'}. {reason}", user)


def advance(eid: int, note: str, user="analyst"):
    """Next workflow step. Board approval freezes the results."""
    e = get(eid)
    stage = min(e["stage"] + 1, len(WORKFLOW) - 1)
    snapshot, approved_on = e["snapshot"], e["approved_on"]
    if WORKFLOW[stage] == "Board approved":
        snapshot = compute(e).to_json(orient="records")
        approved_on = date.today().isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE ewra SET stage=?, snapshot=?, approved_on=? WHERE id=?",
                     (stage, snapshot, approved_on, eid))
        db.log(conn, "ewra", eid, f"workflow: {WORKFLOW[stage]}", note, user)


def actions_df(eid: int) -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("SELECT * FROM ewra_actions WHERE ewra_id=? ORDER BY id", conn, params=[eid])
    today = date.today().isoformat()
    df["status"] = [("Overdue" if s == "Open" and d and d < today else s) for s, d in zip(df.status, df.due)]
    return df


def add_action(eid: int, factor: str, action: str, owner: str, due: str, user="analyst") -> int:
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO ewra_actions (ewra_id, factor, action, owner, due) VALUES (?,?,?,?,?)",
                           (eid, factor, action, owner, due))
        db.log(conn, "ewra", eid, "action added", f"{factor}: {action} ({owner}, due {due})", user)
    return cur.lastrowid


def close_action(aid: int, note: str, user="analyst"):
    with db.connect() as conn:
        eid = conn.execute("SELECT ewra_id FROM ewra_actions WHERE id=?", (aid,)).fetchone()[0]
        conn.execute("UPDATE ewra_actions SET status='Done', note=? WHERE id=?", (note, aid))
        db.log(conn, "ewra", eid, f"action #{aid} done", note, user)


def seed_demo():
    """One draft assessment for this year, at compliance review, with an action plan."""
    init()
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM ewra").fetchone()[0]:
            return
    t = date.today()
    eid = create(t.year, "Medium", "Current and corporate accounts, cross-border transfers, cash deposits",
                 "Medium", "seed")
    advance(eid, "Draft complete, sent to the Compliance Manager for review", "seed")
    d = lambda days: date.fromordinal(t.toordinal() + days).isoformat()   # noqa: E731
    for factor, action, owner, due in [
        ("Transactions", "Fix alert handling: named alert owner, weekly ageing review, retest next quarter",
         "Compliance Manager", d(80)),
        ("Transactions", "Review the cash-intensive customers; EDD or exit where cash is not explained", "MLRO",
         d(110)),
        ("Customers", "Bring periodic reviews up to date and add a monthly overdue report", "Compliance Analyst",
         d(50)),
        ("Sanctions and proliferation financing", "Add name-variant matching and retest screening", "MLRO",
         d(50)),
    ]:
        add_action(eid, factor, action, owner, due, "seed")


def report_sections(e: dict) -> list:
    """Sections for the Reports page and the Excel download."""
    df = compute(e)
    summary = pd.DataFrame({
        "Item": ["Assessment", "Stage", "Approved on", "Risk appetite", "Overall inherent risk",
                 "Overall residual risk", "Factors above appetite"],
        "Value": [f"EWRA {e['year']} {e['version']}", WORKFLOW[e["stage"]], e["approved_on"] or "not yet",
                  e["appetite"], overall(list(df.Inherent)), overall(list(df.Residual)),
                  ", ".join(df[df["Above appetite"]]["Risk factor"]) or "none"]})
    factors = df.drop(columns=["Calculated", "Above appetite"])
    acts = actions_df(e["id"])[["factor", "action", "owner", "due", "status"]].rename(
        columns={"factor": "Risk factor", "action": "Action", "owner": "Owner", "due": "Due", "status": "Status"})
    return [("EWRA summary", summary), ("Risk factors", factors), ("Action plan", acts)]


def current() -> dict | None:
    """The assessment to report on: the newest approved one, else the newest draft."""
    a = assessments_df()
    if a.empty:
        return None
    return latest_approved() or a.iloc[0].to_dict()
