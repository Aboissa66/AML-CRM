"""Transaction monitoring: CSV import, detection rules, alerts and cases.

CSV columns (one row per transaction):
    txn_id, customer_id, date, amount, currency, direction, channel,
    counterparty, counterparty_country, description
direction is IN or OUT; channel is Cash, Wire, Card, Cheque or Transfer.
Amounts are converted to AED with the fixed rates below (good enough for a prototype).
"""

import json
from datetime import datetime, timedelta

import pandas as pd

import db
from risk import FATF_BLACKLIST, FATF_GREYLIST

FX_TO_AED = {"AED": 1.0, "USD": 3.6725, "EUR": 4.0, "GBP": 4.65, "SAR": 0.979, "INR": 0.044,
             "PKR": 0.0132, "CNY": 0.51, "RUB": 0.045, "EGP": 0.076}

REQUIRED = ["txn_id", "customer_id", "date", "amount", "direction", "channel"]
CASE_STATUSES = ["Open", "Investigating", "STR filed", "Closed - no suspicion"]

# Rule settings. The Rules tab lets you change these while you experiment.
DEFAULT_RULES = {
    "large_cash": {"on": True, "threshold": 55_000,
                   "label": "Large cash transaction",
                   "why": "Single cash transaction at or above the threshold (AED 55,000 is the UAE reporting "
                          "threshold for dealers in precious metals and real estate)."},
    "structuring": {"on": True, "low": 40_000, "high": 55_000, "count": 3, "days": 7,
                    "label": "Possible structuring",
                    "why": "Several cash transactions just below the threshold within a short period, a classic "
                           "way of avoiding reporting."},
    "high_risk_country": {"on": True, "label": "High risk jurisdiction",
                          "why": "Funds sent to or received from a FATF black list or grey list country."},
    "pass_through": {"on": True, "min_in": 100_000, "out_ratio": 0.8, "days": 3,
                     "label": "Rapid movement of funds",
                     "why": "Large incoming funds mostly sent out again within days, typical of layering "
                            "or a mule account."},
    "profile_deviation": {"on": True, "multiple": 2.0, "min_total": 50_000,
                          "label": "Activity above expected profile",
                          "why": "Monthly volume far above what the customer declared at onboarding."},
    "round_amounts": {"on": True, "count": 3, "days": 30, "unit": 10_000,
                      "label": "Repeated round amounts",
                      "why": "Several large round-figure transactions, which rarely occur in genuine trade."},
    "sanctioned_counterparty": {"on": True, "threshold": 90,
                                "label": "Counterparty matches a sanctions list",
                                "why": "The counterparty name closely matches a sanctions list entry."},
}
SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id TEXT UNIQUE, customer_id INTEGER, ts TEXT, amount REAL, currency TEXT, amount_aed REAL,
    direction TEXT, channel TEXT, counterparty TEXT, counterparty_country TEXT, description TEXT, batch TEXT
);
CREATE INDEX IF NOT EXISTS ix_txn_customer ON transactions(customer_id, ts);
CREATE TABLE IF NOT EXISTS tm_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER, rule TEXT, severity TEXT, description TEXT, txn_ids TEXT, total_aed REAL,
    period TEXT, status TEXT DEFAULT 'Open', case_id INTEGER, created_at TEXT,
    UNIQUE(customer_id, rule, period)
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER, title TEXT, status TEXT DEFAULT 'Open', priority TEXT, assigned_to TEXT,
    narrative TEXT, decision_note TEXT, opened_at TEXT, closed_at TEXT
);
"""


def init():
    with db.connect() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def import_csv(df: pd.DataFrame, batch: str, user: str = "analyst") -> dict:
    """Validate and store transactions. Returns counts and a list of problems."""
    init()
    df = df.rename(columns=lambda c: str(c).strip().lower())
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return {"added": 0, "skipped": 0, "problems": [f"Missing columns: {', '.join(missing)}"]}
    for col in ["currency", "counterparty", "counterparty_country", "description"]:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("")
    known = set(db.customers_df()["id"].astype(int))
    problems, rows = [], []
    for i, r in df.iterrows():
        line = i + 2
        try:
            cid = int(float(r["customer_id"]))
            ts = pd.to_datetime(r["date"]).isoformat()
            amount = float(str(r["amount"]).replace(",", ""))
        except Exception:
            problems.append(f"Row {line}: unreadable customer_id, date or amount")
            continue
        cur = (str(r["currency"]).strip().upper() or "AED")
        if cid not in known:
            problems.append(f"Row {line}: customer {cid} does not exist")
            continue
        if cur not in FX_TO_AED:
            problems.append(f"Row {line}: unknown currency {cur}")
            continue
        direction = str(r["direction"]).strip().upper()
        if direction not in {"IN", "OUT"}:
            problems.append(f"Row {line}: direction must be IN or OUT")
            continue
        rows.append((str(r["txn_id"]).strip(), cid, ts, amount, cur, round(amount * FX_TO_AED[cur], 2), direction,
                     str(r["channel"]).strip().title(), str(r["counterparty"]).strip(),
                     str(r["counterparty_country"]).strip(), str(r["description"]).strip(), batch))
    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.executemany("INSERT OR IGNORE INTO transactions (txn_id, customer_id, ts, amount, currency, amount_aed,"
                         " direction, channel, counterparty, counterparty_country, description, batch)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        added = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] - before
        db.log(conn, "transactions", 0, "CSV imported", f"{batch}: {added} added, {len(rows) - added} duplicates, "
               f"{len(problems)} rejected", user)
    return {"added": added, "skipped": len(rows) - added, "problems": problems}


def transactions_df(customer_id: int | None = None) -> pd.DataFrame:
    init()
    q = ("SELECT t.*, c.full_name AS customer FROM transactions t JOIN customers c ON c.id = t.customer_id")
    args = ()
    if customer_id:
        q += " WHERE t.customer_id=?"
        args = (customer_id,)
    with db.connect() as conn:
        df = pd.read_sql_query(q + " ORDER BY t.ts", conn, params=args)
    df["ts"] = pd.to_datetime(df["ts"])
    return df


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def _alert(out, cid, rule_key, rules, severity, text, txns, period):
    out.append(dict(customer_id=int(cid), rule=rules[rule_key]["label"], severity=severity, description=text,
                    txn_ids=json.dumps(list(txns["txn_id"])), total_aed=round(float(txns["amount_aed"].sum()), 2),
                    period=period))


def run_rules(rules: dict | None = None, user: str = "analyst") -> int:
    """Run every enabled rule over all transactions. Returns the number of new alerts."""
    rules = rules or DEFAULT_RULES
    df = transactions_df()
    if df.empty:
        return 0
    customers = db.customers_df().set_index("id")
    out = []
    cash = df[df.channel == "Cash"]

    if rules["large_cash"]["on"]:
        t = rules["large_cash"]["threshold"]
        for _, r in cash[cash.amount_aed >= t].iterrows():
            _alert(out, r.customer_id, "large_cash", rules, "Medium",
                   f"Cash {r.direction.lower()} of AED {r.amount_aed:,.0f} on {r.ts:%d %b %Y}",
                   df[df.txn_id == r.txn_id], r.txn_id)

    if rules["structuring"]["on"]:
        p = rules["structuring"]
        near = cash[(cash.amount_aed >= p["low"]) & (cash.amount_aed < p["high"])]
        for cid, g in near.groupby("customer_id"):
            g = g.sort_values("ts")
            for i in range(len(g)):
                window = g[(g.ts >= g.ts.iloc[i]) & (g.ts < g.ts.iloc[i] + timedelta(days=p["days"]))]
                if len(window) >= p["count"]:
                    _alert(out, cid, "structuring", rules, "High",
                           f"{len(window)} cash transactions between AED {p['low']:,} and {p['high']:,} within "
                           f"{p['days']} days (total AED {window.amount_aed.sum():,.0f})",
                           window, f"{window.ts.iloc[0]:%Y-%m-%d}")
                    break

    if rules["high_risk_country"]["on"]:
        risky = df[df.counterparty_country.isin(FATF_BLACKLIST | FATF_GREYLIST)]
        for (cid, country), g in risky.groupby(["customer_id", "counterparty_country"]):
            black = country in FATF_BLACKLIST
            _alert(out, cid, "high_risk_country", rules, "High" if black else "Medium",
                   f"{len(g)} transaction(s) with {country} ({'FATF black list' if black else 'FATF grey list'}), "
                   f"total AED {g.amount_aed.sum():,.0f}", g, country)

    if rules["pass_through"]["on"]:
        p = rules["pass_through"]
        for cid, g in df.groupby("customer_id"):
            ins = g[g.direction == "IN"].sort_values("ts")
            for _, r in ins.iterrows():
                if r.amount_aed < p["min_in"]:
                    continue
                outs = g[(g.direction == "OUT") & (g.ts >= r.ts) & (g.ts <= r.ts + timedelta(days=p["days"]))]
                if outs.amount_aed.sum() >= p["out_ratio"] * r.amount_aed:
                    _alert(out, cid, "pass_through", rules, "High",
                           f"AED {r.amount_aed:,.0f} received on {r.ts:%d %b} and AED {outs.amount_aed.sum():,.0f} "
                           f"({outs.amount_aed.sum() / r.amount_aed:.0%}) sent out within {p['days']} days",
                           pd.concat([g[g.txn_id == r.txn_id], outs]), f"{r.ts:%Y-%m-%d}")
                    break

    if rules["profile_deviation"]["on"]:
        p = rules["profile_deviation"]
        monthly = df.assign(month=df.ts.dt.strftime("%Y-%m")).groupby(["customer_id", "month"])
        for (cid, month), g in monthly:
            expected = customers.loc[cid, "expected_monthly_volume"] if cid in customers.index else 0
            total = g.amount_aed.sum()
            if expected and total >= p["min_total"] and total > p["multiple"] * expected:
                _alert(out, cid, "profile_deviation", rules, "Medium",
                       f"{month}: AED {total:,.0f} moved against an expected AED {expected:,.0f} per month "
                       f"({total / expected:.1f}x)", g, month)

    if rules["round_amounts"]["on"]:
        p = rules["round_amounts"]
        rnd = df[(df.amount_aed >= p["unit"]) & (df.amount % p["unit"] == 0)]
        for cid, g in rnd.groupby("customer_id"):
            g = g.sort_values("ts")
            for i in range(len(g)):
                window = g[(g.ts >= g.ts.iloc[i]) & (g.ts < g.ts.iloc[i] + timedelta(days=p["days"]))]
                if len(window) >= p["count"]:
                    _alert(out, cid, "round_amounts", rules, "Low",
                           f"{len(window)} round-figure transactions within {p['days']} days "
                           f"(total AED {window.amount_aed.sum():,.0f})", window, f"{window.ts.iloc[0]:%Y-%m-%d}")
                    break

    if rules["sanctioned_counterparty"]["on"]:
        import sanctions
        from rapidfuzz import fuzz
        entries = sanctions._entries() if sanctions.lists_loaded() else pd.DataFrame()
        if not entries.empty:
            names = entries["norm"].tolist()
            from rapidfuzz import process
            for cp, g in df[df.counterparty != ""].groupby("counterparty"):
                q = sanctions.normalise(cp, True)
                hit = process.extractOne(q, names, scorer=fuzz.token_sort_ratio,
                                         score_cutoff=rules["sanctioned_counterparty"]["threshold"])
                if hit and len(q.split()) > 1:
                    e = entries.iloc[hit[2]]
                    for cid, gg in g.groupby("customer_id"):
                        _alert(out, cid, "sanctioned_counterparty", rules, "Critical",
                               f"Counterparty '{cp}' matches '{e['name']}' on {e['list_name']} "
                               f"(score {hit[1]:.0f}), {len(gg)} transaction(s)", gg, cp)

    now = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM tm_alerts").fetchone()[0]
        conn.executemany("INSERT OR IGNORE INTO tm_alerts (customer_id, rule, severity, description, txn_ids,"
                         " total_aed, period, created_at) VALUES (?,?,?,?,?,?,?,?)",
                         [(a["customer_id"], a["rule"], a["severity"], a["description"], a["txn_ids"],
                           a["total_aed"], a["period"], now) for a in out])
        new = conn.execute("SELECT COUNT(*) FROM tm_alerts").fetchone()[0] - before
        db.log(conn, "transactions", 0, "monitoring run", f"{len(df)} transactions, {new} new alerts", user)
    return new


# ---------------------------------------------------------------------------
# Alerts and cases
# ---------------------------------------------------------------------------
def alerts_df(status: str | None = None, customer_id: int | None = None) -> pd.DataFrame:
    init()
    q = ("SELECT a.*, c.full_name AS customer, c.risk_rating FROM tm_alerts a "
         "JOIN customers c ON c.id = a.customer_id WHERE 1=1")
    args = []
    if status:
        q += " AND a.status=?"
        args.append(status)
    if customer_id:
        q += " AND a.customer_id=?"
        args.append(customer_id)
    with db.connect() as conn:
        df = pd.read_sql_query(q, conn, params=args)
    df["sev_rank"] = df["severity"].map({s: i for i, s in enumerate(SEVERITY_ORDER)})
    return df.sort_values(["sev_rank", "created_at"]).drop(columns="sev_rank")


def alert_transactions(alert_row) -> pd.DataFrame:
    ids = json.loads(alert_row["txn_ids"])
    df = transactions_df(int(alert_row["customer_id"]))
    return df[df.txn_id.isin(ids)]


def close_alert(alert_id: int, note: str, user: str = "analyst"):
    with db.connect() as conn:
        a = conn.execute("SELECT * FROM tm_alerts WHERE id=?", (alert_id,)).fetchone()
        conn.execute("UPDATE tm_alerts SET status='Closed - explained' WHERE id=?", (alert_id,))
        db.log(conn, "customer", a["customer_id"], "TM alert closed", f"{a['rule']}: {note}", user)


def open_case(customer_id: int, alert_ids: list[int], title: str, priority: str, user: str = "analyst") -> int:
    init()
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO cases (customer_id, title, status, priority, assigned_to, narrative, opened_at)"
                           " VALUES (?,?,?,?,?,?,?)", (customer_id, title, "Open", priority, user, "",
                                                       datetime.now().isoformat(timespec="seconds")))
        case_id = cur.lastrowid
        conn.executemany("UPDATE tm_alerts SET status='In case', case_id=? WHERE id=?", [(case_id, a) for a in alert_ids])
        db.log(conn, "customer", customer_id, f"case #{case_id} opened", f"{title} ({len(alert_ids)} alerts)", user)
    return case_id


def cases_df(customer_id: int | None = None) -> pd.DataFrame:
    init()
    q = "SELECT k.*, c.full_name AS customer FROM cases k JOIN customers c ON c.id = k.customer_id"
    args = ()
    if customer_id:
        q += " WHERE k.customer_id=?"
        args = (customer_id,)
    with db.connect() as conn:
        return pd.read_sql_query(q + " ORDER BY k.id DESC", conn, params=args)


def case_alerts(case_id: int) -> pd.DataFrame:
    with db.connect() as conn:
        return pd.read_sql_query("SELECT * FROM tm_alerts WHERE case_id=?", conn, params=(case_id,))


def update_case(case_id: int, status: str, narrative: str, note: str, user: str = "analyst"):
    with db.connect() as conn:
        k = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        closed = datetime.now().isoformat(timespec="seconds") if status in ("STR filed", "Closed - no suspicion") else None
        conn.execute("UPDATE cases SET status=?, narrative=?, decision_note=?, closed_at=? WHERE id=?",
                     (status, narrative, note, closed, case_id))
        if closed:
            conn.execute("UPDATE tm_alerts SET status=? WHERE case_id=?",
                         ("Closed - STR" if status == "STR filed" else "Closed - explained", case_id))
        db.log(conn, "customer", k["customer_id"], f"case #{case_id}: {status}", note, user)
    db.update_customer(k["customer_id"], {}, user)   # an STR moves the customer to High risk


def str_report(case_id: int) -> str:
    """A plain-text STR draft laid out like the goAML narrative sections."""
    k = cases_df().query("id == @case_id").iloc[0]
    c = db.get_customer(int(k.customer_id))
    alerts = case_alerts(case_id)
    txns = pd.concat([alert_transactions(a) for _, a in alerts.iterrows()]).drop_duplicates("txn_id") \
        if not alerts.empty else pd.DataFrame()
    lines = [
        "SUSPICIOUS TRANSACTION REPORT (DRAFT) - for submission via goAML to the UAE FIU",
        f"Prepared: {datetime.now():%d %b %Y %H:%M}   Case #{case_id}   Analyst: {k.assigned_to}",
        "", "1. REPORTING ENTITY", "   Sanad AML & Sanctions CMS prototype (training data only)",
        "", "2. SUBJECT",
        f"   Name: {c['full_name']} ({c['customer_type']})",
        f"   ID / licence: {c['id_number']}   Nationality / incorporation: {c['nationality']}",
        f"   Activity: {c['activity']}   Declared source of funds: {c['source_of_funds']}",
        f"   Expected monthly volume: AED {c['expected_monthly_volume']:,.0f}   Risk rating: {c['risk_rating']}",
        "", "3. RED FLAGS IDENTIFIED",
    ]
    lines += [f"   - [{a.severity}] {a.rule}: {a.description}" for a in alerts.itertuples()]
    lines += ["", "4. TRANSACTIONS"]
    if not txns.empty:
        lines += [f"   {t.ts:%Y-%m-%d}  {t.txn_id:<12} {t.direction:<3} {t.channel:<8} AED {t.amount_aed:>12,.2f}  "
                  f"{t.counterparty} ({t.counterparty_country})" for t in txns.sort_values("ts").itertuples()]
        lines.append(f"   Total: AED {txns.amount_aed.sum():,.2f} across {len(txns)} transactions")
    lines += ["", "5. REASON FOR SUSPICION (NARRATIVE)", "   " + (k.narrative or "(write the narrative in the case)"),
              "", "6. ACTION TAKEN", "   " + (k.decision_note or ""),
              "", "Reminder: do not tip off the customer. Keep this report and its evidence for at least 5 years."]
    return "\n".join(lines)


def sample_csv() -> str:
    """CSV template with two example rows."""
    return ("txn_id,customer_id,date,amount,currency,direction,channel,counterparty,counterparty_country,description\n"
            "T-0001,7,2026-10-01 10:15,12000,AED,IN,Transfer,ACME Payroll LLC,United Arab Emirates,Salary\n"
            "T-0002,3,2026-10-02 12:40,60000,AED,IN,Cash,Walk-in customer,United Arab Emirates,Gold sale\n")
