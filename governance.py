"""Governance: policy management, control effectiveness testing and the data behind the reports.

Three small registers live in the same SQLite file as everything else:
  * policies (+ policy_versions): the AML/CFT and sanctions policy library, with approval workflow,
    review dates and staff attestation;
  * control_tests (+ findings): compliance management's periodic tests of whether each control works,
    and the remediation of what failed;
  * the reports page reads these plus customers, screening and monitoring data.
All demo content is fictional.
"""

from datetime import date, timedelta

import pandas as pd

import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, version TEXT, owner TEXT, approver TEXT,
    stage INTEGER DEFAULT 1,              -- index into WORKFLOW
    approved_on TEXT, review_months INTEGER DEFAULT 12, next_review TEXT,
    basis TEXT,                           -- regulatory references, one per line
    staff_total INTEGER DEFAULT 0, staff_attested INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS policy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER, version TEXT, on_date TEXT, note TEXT, by_user TEXT
);
CREATE TABLE IF NOT EXISTS control_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT, what TEXT, method TEXT, frequency TEXT, tested_on TEXT, tester TEXT,
    sample INTEGER, passed INTEGER, result TEXT, notes TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER, finding TEXT, severity TEXT, action TEXT, owner TEXT, due TEXT,
    status TEXT DEFAULT 'Open', closed_on TEXT, closure_note TEXT
);
"""

WORKFLOW = ["Drafted", "Compliance review", "Senior management", "Board approved", "Published to staff"]
APPROVERS = ["Board", "Senior management"]
AREAS = ["KYC / CDD", "UBO identification", "Sanctions screening", "Transaction monitoring", "Alert handling",
         "STR reporting", "Periodic review", "Training", "Record keeping"]
FREQUENCIES = ["Monthly", "Quarterly", "Semi-annual", "Annual"]
RESULTS = ["Effective", "Partially effective", "Ineffective"]
SEVERITIES = ["High", "Medium", "Low"]
UAE_BASIS = [
    "Federal Decree-Law No. 20 of 2018 (as amended)",
    "Cabinet Decision No. 10 of 2019 (Executive Regulation)",
    "Cabinet Decision No. 74 of 2020 (targeted financial sanctions)",
    "Cabinet Decision No. 109 of 2023 (beneficial ownership)",
]


def init():
    with db.connect() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def result_for(sample: int, passed: int) -> str:
    """95% or more passed = Effective, 80-94% = Partially effective, below 80% = Ineffective."""
    if not sample:
        return "Effective"
    rate = passed / sample
    return "Effective" if rate >= 0.95 else "Partially effective" if rate >= 0.8 else "Ineffective"


def policy_status(stage: int, next_review: str | None, today: date | None = None) -> str:
    """Draft until the Board / senior management approves; then Overdue, Due for review (30 days) or Current."""
    today = today or date.today()
    if stage < 3:
        return "Draft"
    if not next_review:
        return "Current"
    nr = date.fromisoformat(next_review)
    if nr < today:
        return "Overdue"
    if nr <= today + timedelta(days=30):
        return "Due for review"
    return "Current"


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def policy_controls() -> list[dict]:
    """Policy rules next to the Sanad setting that enforces them. A mismatch means the policy and the app
    disagree: one of them must change, with approval."""
    import risk
    import tm
    import ubo
    rows = [
        ("UBO threshold", "25% effective ownership", f"{ubo.UBO_THRESHOLD:g}%", ubo.UBO_THRESHOLD == 25),
        ("Large cash threshold", "AED 55,000", f"AED {tm.DEFAULT_RULES['large_cash']['threshold']:,}",
         tm.DEFAULT_RULES["large_cash"]["threshold"] == 55_000),
        ("High risk review cycle", "Every 1 year", f"Every {risk.REVIEW_YEARS['High']} year(s)",
         risk.REVIEW_YEARS["High"] == 1),
        ("Medium risk review cycle", "Every 18 months", f"Every {risk.REVIEW_YEARS['Medium']} year(s)",
         risk.REVIEW_YEARS["Medium"] * 12 == 18),
        ("Low risk review cycle", "Every 3 years", f"Every {risk.REVIEW_YEARS['Low']} year(s)",
         risk.REVIEW_YEARS["Low"] == 3),
        ("Structuring window", "3 cash deposits of AED 40-55k in 7 days",
         f"{tm.DEFAULT_RULES['structuring']['count']} in {tm.DEFAULT_RULES['structuring']['days']} days",
         (tm.DEFAULT_RULES["structuring"]["count"], tm.DEFAULT_RULES["structuring"]["days"]) == (3, 7)),
        ("Sanctions match threshold", "Score 85", "85 (default)", True),
    ]
    return [{"Policy rule": r, "Policy says": p, "Sanad setting": a, "Status": "Matches" if ok else "Differs"}
            for r, p, a, ok in rows]


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
def policies_df() -> pd.DataFrame:
    init()
    with db.connect() as conn:
        df = pd.read_sql_query("SELECT * FROM policies ORDER BY id", conn)
    if df.empty:
        return df.assign(status=[], attested_pct=[])
    df["status"] = [policy_status(s, n) for s, n in zip(df.stage, df.next_review)]
    df["attested_pct"] = [round(100 * a / t) if t else None for a, t in zip(df.staff_attested, df.staff_total)]
    return df


def get_policy(pid: int) -> dict:
    with db.connect() as conn:
        return dict(conn.execute("SELECT * FROM policies WHERE id=?", (pid,)).fetchone())


def versions_df(pid: int) -> pd.DataFrame:
    with db.connect() as conn:
        return pd.read_sql_query("SELECT version, on_date, note, by_user FROM policy_versions WHERE policy_id=? "
                                 "ORDER BY id DESC", conn, params=[pid])


def add_policy(name, owner, approver, review_months, basis, staff_total, user="analyst") -> int:
    init()
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO policies (name, version, owner, approver, stage, review_months, basis, "
                           "staff_total) VALUES (?,?,?,?,?,?,?,?)",
                           (name, "v0.1", owner, approver, 0, review_months, basis, staff_total))
        pid = cur.lastrowid
        conn.execute("INSERT INTO policy_versions (policy_id, version, on_date, note, by_user) VALUES (?,?,?,?,?)",
                     (pid, "v0.1", date.today().isoformat(), "First draft", user))
        db.log(conn, "policy", pid, "created", name, user)
    return pid


def advance_policy(pid: int, note: str, user="analyst"):
    """Move a policy one step along WORKFLOW. Board / senior management approval sets the approval date and
    the next review date; publishing resets staff attestation for the new version."""
    p = get_policy(pid)
    stage = min(p["stage"] + 1, len(WORKFLOW) - 1)
    approved_on, next_review, attested = p["approved_on"], p["next_review"], p["staff_attested"]
    if WORKFLOW[stage] == "Board approved":
        approved_on = date.today().isoformat()
        next_review = _add_months(date.today(), p["review_months"] or 12).isoformat()
    if WORKFLOW[stage] == "Published to staff":
        attested = 0
    with db.connect() as conn:
        conn.execute("UPDATE policies SET stage=?, approved_on=?, next_review=?, staff_attested=? WHERE id=?",
                     (stage, approved_on, next_review, attested, pid))
        db.log(conn, "policy", pid, f"workflow: {WORKFLOW[stage]}", note, user)


def new_version(pid: int, note: str, user="analyst"):
    """Start a new version: bumps the minor version and sends it back to draft for approval."""
    p = get_policy(pid)
    major, minor = (p["version"] or "v1.0").lstrip("v").split(".")[:2]
    version = f"v{major}.{int(minor) + 1}"
    with db.connect() as conn:
        conn.execute("UPDATE policies SET version=?, stage=0 WHERE id=?", (version, pid))
        conn.execute("INSERT INTO policy_versions (policy_id, version, on_date, note, by_user) VALUES (?,?,?,?,?)",
                     (pid, version, date.today().isoformat(), note, user))
        db.log(conn, "policy", pid, f"new version {version}", note, user)


def record_attestations(pid: int, count: int, user="analyst"):
    p = get_policy(pid)
    attested = max(0, min(p["staff_total"], count))
    with db.connect() as conn:
        conn.execute("UPDATE policies SET staff_attested=? WHERE id=?", (attested, pid))
        db.log(conn, "policy", pid, "attestations recorded", f"{attested} of {p['staff_total']}", user)


# ---------------------------------------------------------------------------
# Control effectiveness tests and findings
# ---------------------------------------------------------------------------
def tests_df() -> pd.DataFrame:
    init()
    with db.connect() as conn:
        return pd.read_sql_query("SELECT * FROM control_tests ORDER BY tested_on DESC, id DESC", conn)


def add_test(area, what, method, frequency, tested_on, tester, sample, passed, notes, evidence,
             user="analyst") -> int:
    result = result_for(sample, passed)
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO control_tests (area, what, method, frequency, tested_on, tester, sample, "
                           "passed, result, notes, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (area, what, method, frequency, tested_on, tester, sample, passed, result, notes,
                            evidence))
        tid = cur.lastrowid
        db.log(conn, "control test", tid, f"test recorded: {result}", f"{area}: {passed}/{sample} passed", user)
    return tid


def findings_df() -> pd.DataFrame:
    init()
    with db.connect() as conn:
        df = pd.read_sql_query("SELECT f.*, t.area, t.tested_on FROM findings f "
                               "LEFT JOIN control_tests t ON t.id = f.test_id ORDER BY f.id DESC", conn)
    today = date.today().isoformat()
    df["status"] = [("Overdue" if s == "Open" and d and d < today else s) for s, d in zip(df.status, df.due)]
    return df


def add_finding(test_id, finding, severity, action, owner, due, user="analyst") -> int:
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO findings (test_id, finding, severity, action, owner, due) "
                           "VALUES (?,?,?,?,?,?)", (test_id, finding, severity, action, owner, due))
        fid = cur.lastrowid
        db.log(conn, "finding", fid, "raised", f"{severity}: {finding}", user)
    return fid


def close_finding(fid: int, note: str, user="analyst"):
    with db.connect() as conn:
        conn.execute("UPDATE findings SET status='Closed', closed_on=?, closure_note=? WHERE id=?",
                     (date.today().isoformat(), note, fid))
        db.log(conn, "finding", fid, "closed", note, user)


def quarter_grid(tests: pd.DataFrame, year: int) -> pd.DataFrame:
    """Latest result per control area and quarter: E, P, I or '-' (not tested)."""
    short = {"Effective": "E", "Partially effective": "P", "Ineffective": "I"}
    grid = pd.DataFrame("-", index=AREAS, columns=["Q1", "Q2", "Q3", "Q4"])
    if tests.empty:
        return grid
    t = tests.assign(d=pd.to_datetime(tests.tested_on, errors="coerce")).dropna(subset=["d"])
    t = t[t.d.dt.year == year].sort_values("d")
    for r in t.itertuples():
        if r.area in grid.index:
            grid.loc[r.area, f"Q{(r.d.month - 1) // 3 + 1}"] = short.get(r.result, "-")
    return grid


# ---------------------------------------------------------------------------
# Demo content (fictional)
# ---------------------------------------------------------------------------
def seed_demo():
    """Fill the three registers once, with dates relative to today so statuses stay meaningful."""
    init()
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]:
            return
    t = date.today()
    d = lambda days: (t + timedelta(days=days)).isoformat()   # noqa: E731
    basis = "\n".join(UAE_BASIS)
    policies = [
        # name, version, owner, approver, stage, approved_on, months, next_review, staff, attested, history
        ("AML/CFT Policy", "v3.2", "MLRO", "Board", 4, d(-240), 12, d(125), 14, 12,
         [("v3.0", d(-660), "Annual Board re-approval"), ("v3.1", d(-400), "Cash threshold aligned to AED 55,000"),
          ("v3.2", d(-240), "Added Cabinet Decision 109/2023 UBO fallback rule")]),
        ("Sanctions Compliance Policy", "v2.4", "MLRO", "Board", 4, d(-300), 12, d(65), 14, 13,
         [("v2.4", d(-300), "Added UAE Local Terrorist List screening")]),
        ("KYC / CDD Procedure", "v4.0", "Head of Onboarding", "Senior management", 4, d(-345), 12, d(20), 9, 9,
         [("v4.0", d(-345), "Company onboarding form split from individuals")]),
        ("Transaction Monitoring Procedure", "v1.6", "MLRO", "Senior management", 4, d(-450), 12, d(-85), 6, 5,
         [("v1.6", d(-450), "Added rapid movement of funds rule")]),
        ("STR / goAML Reporting Procedure", "v2.1", "MLRO", "Senior management", 4, d(-160), 12, d(205), 6, 6,
         [("v2.1", d(-160), "PNMR and FFR steps added")]),
        ("Customer Risk Assessment Methodology", "v2.0", "Compliance Manager", "Board", 4, d(-270), 12, d(95), 7, 5,
         [("v2.0", d(-270), "Ownership red flags added to the score")]),
        ("Record Keeping Procedure", "v1.3", "Operations", "Senior management", 4, d(-340), 12, d(25), 20, 20,
         [("v1.3", d(-340), "Five-year retention confirmed")]),
        ("AML Training Plan 2027", "v0.3", "Compliance Manager", "Board", 1, None, 12, None, 20, 0,
         [("v0.3", d(-6), "Draft sent for compliance review")]),
    ]
    tests = [
        ("KYC / CDD", "Customer files complete and correctly rated", "Sample of customer files", "Quarterly",
         d(-42), "Compliance Manager", 25, 24, "One file missing proof of address.", "Sample list; file checklist"),
        ("UBO identification", "UBO traced to 25% or senior manager recorded", "Sample of company files",
         "Semi-annual", d(-118), "Compliance Analyst", 10, 10, "", "Ownership trees exported"),
        ("Sanctions screening", "Known list names are detected", "Test names: exact, aliases, spelling variants",
         "Quarterly", d(-54), "Compliance Manager", 20, 18,
         "Missed 'Mohamad' vs 'Muhammad' (score 82) and a company name written without spaces (79).",
         "Test name list; screening output; MLRO sign-off"),
        ("Transaction monitoring", "Each rule fires on a planted scenario", "Planted test scenarios",
         "Semi-annual", d(-141), "MLRO", 7, 7, "", "Scenario file; alert list"),
        ("Alert handling", "Alerts closed with rationale within 10 days", "All alerts in the quarter",
         "Quarterly", d(-42), "Compliance Analyst", 21, 15, "6 alerts open longer than 10 days.", "Alert ageing report"),
        ("STR reporting", "STRs filed without delay once suspicion formed", "All STRs in the half-year",
         "Semi-annual", d(-133), "MLRO", 1, 1, "", "goAML submission receipt"),
        ("Periodic review", "Reviews completed by the due date", "Overdue review report", "Quarterly",
         d(-42), "Compliance Analyst", 15, 12, "3 reviews completed late.", "Review report"),
        ("Sanctions screening", "Known list names are detected", "Test names", "Quarterly", d(-145),
         "Compliance Manager", 20, 20, "", "Test name list"),
        ("Alert handling", "Alerts closed with rationale within 10 days", "All alerts in the quarter",
         "Quarterly", d(-133), "Compliance Analyst", 14, 12, "2 alerts closed after 12 days.", "Alert ageing report"),
    ]
    with db.connect() as conn:
        for p in policies:
            cur = conn.execute("INSERT INTO policies (name, version, owner, approver, stage, approved_on, "
                               "review_months, next_review, basis, staff_total, staff_attested) "
                               "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (*p[:8], basis, p[8], p[9]))
            for v, on, note in p[10]:
                conn.execute("INSERT INTO policy_versions (policy_id, version, on_date, note, by_user) "
                             "VALUES (?,?,?,?,?)", (cur.lastrowid, v, on, note, "seed"))
        ids = {}
        for tt in tests:
            cur = conn.execute("INSERT INTO control_tests (area, what, method, frequency, tested_on, tester, sample, "
                               "passed, result, notes, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (*tt[:8], result_for(tt[6], tt[7]), tt[8], tt[9]))
            ids.setdefault((tt[0], tt[4]), cur.lastrowid)
        f = [
            (ids[("Sanctions screening", d(-54))], "Spelling variants missed below the threshold", "High",
             "Add a name-variant table and retest at score 82", "MLRO", d(50), "Open"),
            (ids[("Alert handling", d(-42))], "6 of 21 alerts open longer than 10 days", "High",
             "Assign an owner per alert; weekly ageing review", "Compliance Manager", d(4), "Open"),
            (ids[("Periodic review", d(-42))], "3 periodic reviews completed late", "Medium",
             "Monthly reminder report to relationship managers", "Compliance Analyst", d(-11), "Open"),
            (ids[("KYC / CDD", d(-42))], "Missing proof of address in one file", "Low",
             "File remediated; refresher for onboarding team", "Head of Onboarding", d(-20), "Closed"),
        ]
        for row in f:
            conn.execute("INSERT INTO findings (test_id, finding, severity, action, owner, due, status, closed_on) "
                         "VALUES (?,?,?,?,?,?,?,?)", (*row, d(-25) if row[-1] == "Closed" else None))
