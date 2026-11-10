"""Sanctions list download, parsing and name screening.

Lists supported:
  * OFAC SDN (US Treasury)             downloaded automatically
  * UN Security Council Consolidated   downloaded automatically
  * EU Financial Sanctions (FSF)       downloaded automatically
  * UAE Local Terrorist List           upload the Excel / CSV file from the UAE
                                       Executive Office (uaeiec.gov.ae)
  * Training list                      fictional entries built into the app so
                                       you can practise without internet

Matching is fuzzy: names are normalised (accents, punctuation, word order,
company suffixes) and compared with a similarity score from 0 to 100. Anything
at or above the threshold becomes an alert for an analyst to review.
"""

import csv
import io
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

import db

DATA_DIR = Path(__file__).with_name("data")
USER_AGENT = "Mozilla/5.0 (compatible; aml-crm-prototype/1.0)"

SOURCES = {
    "OFAC SDN": [
        "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
        "https://www.treasury.gov/ofac/downloads/sdn.csv",
    ],
    "OFAC SDN aliases": [
        "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ALT.CSV",
        "https://www.treasury.gov/ofac/downloads/alt.csv",
    ],
    "UN Consolidated": [
        "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
    ],
    "EU Consolidated": [
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
    ],
}
AUTO_LISTS = ["OFAC SDN", "UN Consolidated", "EU Consolidated"]
ALL_LISTS = AUTO_LISTS + ["UAE Local Terrorist List", "Training list"]

DECISIONS = ["Open", "False positive", "Potential match (escalate)", "True match"]

# Fictional entries for practice. None of these are real sanctioned parties.
TRAINING_ENTRIES = [
    ("TR-001", "Dmitri ORLOV", "Individual", "TRAINING-RU", "Russia", "1971", "Fictional entry for practice"),
    ("TR-002", "Coral Trust Holdings S.A.", "Company", "TRAINING-PA", "Panama", "", "Fictional entry for practice"),
    ("TR-003", "Reza TEHRANY", "Individual", "TRAINING-IR", "Iran", "1980", "Fictional: near match on purpose"),
    ("TR-004", "Golden Sand Jewelry Trading", "Company", "TRAINING-AE", "United Arab Emirates", "",
     "Fictional: similar name, different company"),
    ("TR-005", "Ahmed KHAN", "Individual", "TRAINING-PK", "Pakistan", "1965",
     "Fictional: very common name, expect false positives"),
    ("TR-006", "Northwind Ventures Limited", "Company", "TRAINING-SC", "Seychelles", "",
     "Fictional entry for practice"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS sanctions_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_name TEXT, entry_id TEXT, name TEXT, norm TEXT, entry_type TEXT,
    program TEXT, nationality TEXT, dob TEXT, remarks TEXT
);
CREATE INDEX IF NOT EXISTS ix_sanctions_list ON sanctions_entries(list_name);
CREATE TABLE IF NOT EXISTS sanctions_lists (
    list_name TEXT PRIMARY KEY, fetched_at TEXT, entries INTEGER, names INTEGER, source TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS screening_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER, owner_id INTEGER, party TEXT, screened_name TEXT,
    list_name TEXT, entry_id TEXT, matched_name TEXT, score REAL, details TEXT,
    status TEXT DEFAULT 'Open', decision_note TEXT, decided_by TEXT, decided_at TEXT, created_at TEXT,
    UNIQUE(customer_id, screened_name, list_name, entry_id)
);
"""

# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------
# Legal-form words only. Descriptive words such as "trading" are kept, otherwise
# "Marina Trading LLC" shrinks to "marina" and matches every short listed name.
COMPANY_WORDS = {
    "llc", "ltd", "limited", "fze", "fzco", "fz", "co", "company", "inc", "corp", "corporation", "sa", "s",
    "a", "plc", "gmbh", "bv", "the", "and", "of", "est", "establishment", "l", "pjsc", "psc", "jsc", "llp",
}


def normalise(name: str, is_company: bool = False) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\b(al|el)[-\s]+", r"al", text)          # Al-Hammadi / Al Hammadi / AlHammadi
    text = re.sub(r"[^a-z0-9؀-ۿ]+", " ", text)
    words = text.split()
    if is_company:
        words = [w for w in words if w not in COMPANY_WORDS] or words
    return " ".join(words)


def score(a: str, b: str) -> float:
    """Similarity 0-100 that ignores word order."""
    return fuzz.token_sort_ratio(a, b)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
def init():
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def _store(list_name: str, rows: list[dict], source: str):
    """Replace a list's entries. Each row: entry_id, name, entry_type, program, nationality, dob, remarks."""
    init()
    with db.connect() as conn:
        conn.execute("DELETE FROM sanctions_entries WHERE list_name=?", (list_name,))
        conn.executemany(
            "INSERT INTO sanctions_entries (list_name, entry_id, name, norm, entry_type, program, nationality, dob, remarks)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [(list_name, str(r["entry_id"]), r["name"], normalise(r["name"], r["entry_type"] != "Individual"),
              r["entry_type"], r.get("program", ""), r.get("nationality", ""), r.get("dob", ""),
              (r.get("remarks") or "")[:500]) for r in rows if r.get("name")])
        entries = len({r["entry_id"] for r in rows})
        conn.execute("INSERT OR REPLACE INTO sanctions_lists VALUES (?,?,?,?,?,?)",
                     (list_name, datetime.now().isoformat(timespec="seconds"), entries, len(rows), source, "ok"))
        db.log(conn, "sanctions", 0, f"list updated: {list_name}", f"{entries} entries, {len(rows)} names")


def _mark_failed(list_name: str, error: str):
    init()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sanctions_lists (list_name, status) VALUES (?, ?) "
            "ON CONFLICT(list_name) DO UPDATE SET status=excluded.status", (list_name, f"error: {error}"[:300]))


def list_status() -> pd.DataFrame:
    init()
    with db.connect() as conn:
        df = pd.read_sql_query("SELECT * FROM sanctions_lists", conn)
    return pd.DataFrame({"list_name": ALL_LISTS}).merge(df, how="left", on="list_name")


def _download(urls: list[str]) -> tuple[bytes, str]:
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.read(), url
        except Exception as exc:   # try the next mirror
            last = exc
    raise RuntimeError(f"download failed: {last}")


# ---------------------------------------------------------------------------
# Parsers (each returns a list of row dicts, one per name or alias)
# ---------------------------------------------------------------------------
def _clean(v):
    v = (v or "").strip()
    return "" if v in {"-0-", "-0- ", "nan", "None"} else v


def parse_ofac(sdn: bytes, alt: bytes | None) -> list[dict]:
    rows, info = [], {}
    for rec in csv.reader(io.StringIO(sdn.decode("latin-1"))):
        if len(rec) < 4 or not rec[0].strip().isdigit():
            continue
        ent, name, typ, program = rec[0].strip(), _clean(rec[1]), _clean(rec[2]).lower(), _clean(rec[3])
        remarks = _clean(rec[11]) if len(rec) > 11 else ""
        etype = "Individual" if typ == "individual" else ("Other" if typ in {"vessel", "aircraft"} else "Company")
        dob = re.search(r"DOB ([^;]+)", remarks)
        nat = re.search(r"(?:nationality|Nationality) ([^;.]+)", remarks)
        info[ent] = dict(entry_type=etype, program=program, dob=dob.group(1).strip() if dob else "",
                         nationality=nat.group(1).strip() if nat else "", remarks=remarks)
        rows.append(dict(entry_id=ent, name=name, **info[ent]))
    if alt:
        for rec in csv.reader(io.StringIO(alt.decode("latin-1"))):
            if len(rec) < 4 or rec[0].strip() not in info:
                continue
            alias = _clean(rec[3])
            if alias:
                rows.append(dict(entry_id=rec[0].strip(), name=alias, **{**info[rec[0].strip()],
                                 "remarks": f"{_clean(rec[2])} alias. " + info[rec[0].strip()]["remarks"]}))
    return rows


def parse_un(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    rows = []

    def txt(el, tag):
        found = el.find(tag)
        return (found.text or "").strip() if found is not None and found.text else ""

    for ind in root.iter("INDIVIDUAL"):
        name = " ".join(filter(None, (txt(ind, t) for t in
                                      ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME"))))
        nat_el = ind.find("NATIONALITY")
        nat = ", ".join(v.text.strip() for v in nat_el.findall("VALUE") if v.text) if nat_el is not None else ""
        dobs = []
        for d in ind.iter("INDIVIDUAL_DATE_OF_BIRTH"):
            dobs += [x.text.strip() for x in d if x.tag in ("DATE", "YEAR", "FROM_YEAR") and x.text]
        base = dict(entry_id=txt(ind, "REFERENCE_NUMBER") or txt(ind, "DATAID"), entry_type="Individual",
                    program=txt(ind, "UN_LIST_TYPE"), nationality=nat, dob=", ".join(dobs[:2]),
                    remarks=txt(ind, "COMMENTS1"))
        rows.append(dict(base, name=name))
        for al in ind.iter("INDIVIDUAL_ALIAS"):
            alias = txt(al, "ALIAS_NAME")
            if alias:
                rows.append(dict(base, name=alias, remarks=f"{txt(al, 'QUALITY')} quality alias"))
    for ent in root.iter("ENTITY"):
        base = dict(entry_id=txt(ent, "REFERENCE_NUMBER") or txt(ent, "DATAID"), entry_type="Company",
                    program=txt(ent, "UN_LIST_TYPE"), nationality="", dob="", remarks=txt(ent, "COMMENTS1"))
        rows.append(dict(base, name=txt(ent, "FIRST_NAME")))
        for al in ent.iter("ENTITY_ALIAS"):
            alias = txt(al, "ALIAS_NAME")
            if alias:
                rows.append(dict(base, name=alias, remarks="alias"))
    return rows


def parse_eu(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False, on_bad_lines="skip")
    cols = {c.lower(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
        return None

    c_id = col("Entity_LogicalId", "Entity_logicalId")
    c_name = col("NameAlias_WholeName")
    c_type = col("Entity_SubjectType_ClassificationCode", "Entity_SubjectType")
    c_prog = col("Entity_Regulation_Programme", "Entity_Programme")
    c_dob = col("BirthDate_BirthDate")
    c_nat = col("Citizenship_CountryDescription")
    if not c_id or not c_name:
        raise ValueError(f"unexpected EU file format, columns: {list(df.columns)[:15]}")
    rows = []
    for eid, g in df.groupby(c_id):
        typ = (g[c_type].iloc[0] if c_type else "").lower()
        base = dict(entry_id=eid, entry_type="Individual" if typ in {"person", "p"} else "Company",
                    program=g[c_prog].iloc[0] if c_prog else "",
                    dob=", ".join(sorted({d for d in g[c_dob] if d}))[:60] if c_dob else "",
                    nationality=", ".join(sorted({n for n in g[c_nat] if n}))[:80] if c_nat else "", remarks="")
        for name in sorted({n.strip() for n in g[c_name] if n.strip()}):
            rows.append(dict(base, name=name))
    return rows


def parse_uae(df: pd.DataFrame, name_col: str, type_col: str | None = None,
              nat_col: str | None = None, dob_col: str | None = None) -> list[dict]:
    rows = []
    for i, r in df.iterrows():
        name = str(r[name_col]).strip()
        if not name or name.lower() == "nan":
            continue
        t = str(r[type_col]).lower() if type_col else ""
        rows.append(dict(entry_id=f"UAE-{i + 1}", name=name,
                         entry_type="Company" if any(k in t for k in ("entity", "company", "organi", "كيان")) else "Individual",
                         program="UAE Local Terrorist List",
                         nationality=str(r[nat_col]) if nat_col else "", dob=str(r[dob_col]) if dob_col else "",
                         remarks=""))
    return rows


# ---------------------------------------------------------------------------
# Updating lists
# ---------------------------------------------------------------------------
def load_training_list():
    _store("Training list", [dict(entry_id=e[0], name=e[1], entry_type=e[2], program=e[3], nationality=e[4],
                                  dob=e[5], remarks=e[6]) for e in TRAINING_ENTRIES], "built in")


def update_list(list_name: str) -> str:
    """Download and load one list. Returns a short status message."""
    DATA_DIR.mkdir(exist_ok=True)
    try:
        if list_name == "OFAC SDN":
            sdn, url = _download(SOURCES["OFAC SDN"])
            try:
                alt, _ = _download(SOURCES["OFAC SDN aliases"])
            except Exception:
                alt = None
            (DATA_DIR / "ofac_sdn.csv").write_bytes(sdn)
            rows = parse_ofac(sdn, alt)
        elif list_name == "UN Consolidated":
            raw, url = _download(SOURCES["UN Consolidated"])
            (DATA_DIR / "un_consolidated.xml").write_bytes(raw)
            rows = parse_un(raw)
        elif list_name == "EU Consolidated":
            raw, url = _download(SOURCES["EU Consolidated"])
            (DATA_DIR / "eu_consolidated.csv").write_bytes(raw)
            rows = parse_eu(raw)
        else:
            raise ValueError("This list cannot be downloaded automatically")
        if not rows:
            raise ValueError("file downloaded but no names were found")
        _store(list_name, rows, url)
        return f"{list_name}: {len({r['entry_id'] for r in rows}):,} entries loaded"
    except Exception as exc:
        _mark_failed(list_name, str(exc))
        return f"{list_name}: failed ({exc})"


def has_list(list_name: str) -> bool:
    init()
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM sanctions_entries WHERE list_name=?", (list_name,)).fetchone()[0] > 0


def lists_loaded() -> bool:
    init()
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM sanctions_entries").fetchone()[0] > 0


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
def _entries() -> pd.DataFrame:
    with db.connect() as conn:
        return pd.read_sql_query("SELECT * FROM sanctions_entries", conn)


def parties(customer_id: int | None = None) -> list[dict]:
    """Everyone to screen: customers plus their owners, directors and managers."""
    with db.connect() as conn:
        where = "WHERE id=?" if customer_id else ""
        args = (customer_id,) if customer_id else ()
        out = [dict(customer_id=r["id"], owner_id=None, party="Customer", name=r["full_name"],
                    is_company=r["customer_type"] == "Company", nationality=r["nationality"],
                    dob=r["date_of_birth"] or "")
               for r in conn.execute(f"SELECT * FROM customers {where}", args)]
        where = "WHERE customer_id=?" if customer_id else ""
        seen = set()
        for r in conn.execute(f"SELECT * FROM owners {where}", args):
            key = (r["customer_id"], r["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(customer_id=r["customer_id"], owner_id=r["id"], party=f"{r['role']} ({r['owner_type']})",
                            name=r["name"], is_company=r["owner_type"] == "Company",
                            nationality=r["nationality"], dob=""))
    return out


def screen(customer_id: int | None = None, threshold: float = 85, user: str = "analyst") -> int:
    """Screen customers and owners against every loaded list. Returns the number of new alerts."""
    init()
    entries = _entries()
    if entries.empty:
        return 0
    groups = {}
    for is_company in (False, True):
        sub = entries[(entries.entry_type != "Individual") == is_company]
        groups[is_company] = (sub.reset_index(drop=True), sub["norm"].tolist())
    new = 0
    now = datetime.now().isoformat(timespec="seconds")
    targets = parties(customer_id)
    with db.connect() as conn:
        for p in targets:
            sub, names = groups[p["is_company"]]
            if not names:
                continue
            query = normalise(p["name"], p["is_company"])
            for _, sc, idx in process.extract(query, names, scorer=fuzz.token_sort_ratio,
                                              score_cutoff=threshold, limit=10):
                e = sub.iloc[idx]
                # A one-word name against a longer one is too weak to alert on (e.g. "MARINA").
                n_query, n_entry = len(query.split()), len(e["norm"].split())
                if min(n_query, n_entry) == 1 and n_query != n_entry:
                    continue
                if len(e["norm"]) < 4:
                    continue
                details = []
                if p["nationality"] and e["nationality"] and p["nationality"].lower() in e["nationality"].lower():
                    details.append("nationality matches")
                if p["dob"] and e["dob"] and p["dob"][:4] in e["dob"]:
                    details.append("birth year matches")
                cur = conn.execute(
                    "INSERT OR IGNORE INTO screening_alerts (customer_id, owner_id, party, screened_name, list_name,"
                    " entry_id, matched_name, score, details, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (p["customer_id"], p["owner_id"], p["party"], p["name"], e["list_name"], e["entry_id"],
                     e["name"], round(sc, 1), "; ".join(details), now))
                new += cur.rowcount
        db.log(conn, "sanctions", customer_id or 0, "screening run",
               f"{len(targets)} names screened at threshold {threshold:g}, {new} new alerts", user)
    return new


def alerts_df(status: str | None = None, customer_id: int | None = None) -> pd.DataFrame:
    init()
    q = ("SELECT a.*, c.full_name AS customer FROM screening_alerts a JOIN customers c ON c.id = a.customer_id"
         " WHERE 1=1")
    args = []
    if status:
        q += " AND a.status=?"
        args.append(status)
    if customer_id:
        q += " AND a.customer_id=?"
        args.append(customer_id)
    with db.connect() as conn:
        return pd.read_sql_query(q + " ORDER BY a.status='Open' DESC, a.score DESC", conn, params=args)


def entry_details(list_name: str, entry_id: str) -> pd.DataFrame:
    with db.connect() as conn:
        return pd.read_sql_query(
            "SELECT name, entry_type, program, nationality, dob, remarks FROM sanctions_entries"
            " WHERE list_name=? AND entry_id=?", conn, params=(list_name, entry_id))


def decide(alert_id: int, status: str, note: str, user: str = "analyst"):
    with db.connect() as conn:
        a = conn.execute("SELECT * FROM screening_alerts WHERE id=?", (alert_id,)).fetchone()
        conn.execute("UPDATE screening_alerts SET status=?, decision_note=?, decided_by=?, decided_at=? WHERE id=?",
                     (status, note, user, datetime.now().isoformat(timespec="seconds"), alert_id))
        db.log(conn, "customer", a["customer_id"], f"screening alert: {status}",
               f"{a['screened_name']} vs {a['matched_name']} ({a['list_name']}, {a['score']:g}). {note}", user)
    db.update_customer(a["customer_id"], {}, user)   # a true match changes the risk rating


def summary() -> dict:
    df = alerts_df()
    return {s: int((df.status == s).sum()) for s in DECISIONS} | {"total": len(df)}

