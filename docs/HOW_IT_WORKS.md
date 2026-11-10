# How the AML CRM works

This guide explains the logic behind every feature and points to the exact file and function that
implements it. Read it next to the code. All data in the app is fictional.

## The big picture

```
                 ┌────────────────────────── Streamlit pages (pages/*.py, Dashboard.py) ─────────────────────────┐
 you click  ───▶ │ Customers · Add Customer · Ownership & UBO · Sanctions · Transaction Monitoring · Cases · Audit │
                 └───────────────┬───────────────────────────────┬───────────────────────────────┬───────────────┘
                                 │                               │                               │
                          risk.py (scoring)              ubo.py (ownership)          sanctions.py / tm.py (detection)
                                 └───────────────┬───────────────┴───────────────────────────────┘
                                                 ▼
                                db.py  ───▶  aml_crm.db (one SQLite file)
```

* **Pages** only show things and collect input. They never contain AML rules.
* **Logic modules** (`risk.py`, `ubo.py`, `sanctions.py`, `tm.py`) hold the rules. Change a rule there and every
  page picks it up.
* **`db.py`** is the only place that talks to the database. Every change goes through it, and every change writes
  an audit log entry.

A key design idea: the customer's **risk rating is recalculated** whenever anything that affects it changes
(KYC details, owners, a confirmed sanctions match, an STR). That happens in `db.update_customer()`, which calls
`risk.score_customer()` with everything it knows about the customer.

---

## 1. Customer risk rating (KYC)

**Where:** `risk.py` → `score_customer()`, called from `db._apply_risk()`

**Logic:** a points system. Each risk factor adds points and a plain-English reason, so the rating is always
explainable (you see the reasons on the customer's *Risk assessment* tab).

| Factor | Points | Why it matters |
|---|---|---|
| Nationality or residence in a FATF **black list** country | +40, forces High | Countries under a FATF "call for action" |
| Nationality or residence in a FATF **grey list** country | +20 | Countries under increased monitoring |
| **PEP** (politically exposed person) | +30, forces High | Bribery and corruption risk; EDD is mandatory |
| **High risk activity** (gold dealers, real estate, money exchange, virtual assets, general trading, charities, used cars) | +25 | Sectors the UAE National Risk Assessment flags |
| Medium risk activity | +10 | |
| Cash intensive | +15 | Cash is hard to trace |
| Onboarded **non face to face** | +10 | Higher impersonation risk |
| Source of funds **unclear** | +15 | Can't show where money comes from |
| Expected monthly volume ≥ AED 1m / ≥ 250k | +15 / +5 | Bigger exposure |
| Company (legal entity) | +5 | Ownership must be verified |
| Ownership red flags (see section 2) | +10 to +15 each | Hidden owners |
| Confirmed **sanctions** match (section 3) | +100, forces High | |
| **STR filed** (section 4) | +40, forces High | |

**Bands:** 0–24 **Low**, 25–49 **Medium**, 50+ **High**. Some factors "force High" whatever the score, because the
law requires enhanced due diligence for them regardless of anything else.

**Periodic review** (`next_review_date()`): High every 1 year, Medium 2 years, Low 3 years. An approval resets the
clock (`db.set_kyc_status()`); a change of rating moves the review date (`db.update_customer()`).

**Document checklist** (`required_documents()`): individuals need ID, proof of address and source of funds
evidence; companies need trade licence, MOA/AOA, shareholder register, board resolution, UBO declaration and
signatory IDs. High risk adds an EDD form and senior management approval.

**Approval guard rails** (`pages/1_Customers.py`, KYC decision tab): you can't approve while documents are
missing, while sanctions alerts are open, or if there's a confirmed sanctions match. Every decision needs a
written rationale that goes into the audit trail.

---

## 2. Ownership and UBO identification

**Where:** `ubo.py` → `analyse()` and `risk_factors()`; data in the `owners` table (`db.add_owner()`)

**Data model:** ownership is a **tree**. Each owner row either owns the customer directly (`parent_owner_id` is
empty) or owns a company one layer up. Directors and senior managers hang off the entity they work for.

**Logic in `analyse()`:**

1. **Walk the tree** from the customer upwards (`walk()`), carrying a multiplier.
2. **Effective ownership** is the product of the percentages along the chain. Example: Dmitri owns 60% of Coral,
   Coral owns 100% of Northwind, Northwind owns 70% of Blue Harbour → 0.6 × 1.0 × 0.7 = **42%**.
3. A person reached through several paths has their percentages **added up**.
4. **UBO rule** (UAE Cabinet Decision 109 of 2023):
   * anyone with **25% or more** effective ownership is a UBO;
   * if nobody reaches 25%, the **senior manager** is recorded as UBO (then a director as a last resort), and the
     app says this is the fallback.
5. **Gaps:** at each company, shareholdings should add up to 100%. Anything missing is "Unidentified" and shown
   on the tree.

**Red flags** (`risk_factors()`), which feed the risk score:

| Red flag | Points |
|---|---|
| No owners recorded yet | +10 |
| 2 or more layers of companies | +15 |
| A company in the chain is offshore or in a FATF listed country | +15 |
| Nobody reaches 25% (fallback used) | +10 |
| Ownership doesn't add up to 100% somewhere | +10 |
| A PEP among owners, directors or managers | +30, forces High (in `risk.py`) |

**The tree picture** (`pages/4_Ownership_UBO.py` → `dot_graph()`) is drawn with Graphviz: one box per company,
one box per person, solid arrows for shareholdings with the percentage, dashed arrows for roles.

---

## 3. Sanctions screening

**Where:** `sanctions.py`; page `pages/5_Sanctions_Screening.py`

### Getting the lists (`update_list()`)

| List | Source | Parser |
|---|---|---|
| OFAC SDN | US Treasury CSV files `SDN.CSV` + `ALT.CSV` (aliases) | `parse_ofac()` reads name, type, programme, and pulls DOB and nationality out of the remarks text |
| UN Consolidated | UN Security Council XML | `parse_un()` joins first to fourth names, adds every alias, nationality and dates of birth |
| EU Consolidated | EU Financial Sanctions CSV (one row per name/attribute) | `parse_eu()` groups rows by entity and keeps every name variant |
| UAE Local Terrorist List | Excel file you download from uaeiec.gov.ae and upload | `parse_uae()`; you pick which column holds the name |
| Training list | Built in (`TRAINING_ENTRIES`), **fictional** | so you can practise offline |

Every name and alias becomes one row in `sanctions_entries`. Lists are refreshed on demand from the
*Sanctions lists* tab.

### Matching (`normalise()` and `screen()`)

1. **Normalise** both names: remove accents, lower-case, join "Al-"/"Al " prefixes, drop punctuation and, for
   companies, legal-form words (LLC, Ltd, FZE, S.A.…). Descriptive words such as "Trading" are kept, otherwise
   "Marina Trading LLC" would shrink to "marina" and match everything.
2. **Compare** with `token_sort_ratio` from the `rapidfuzz` library: words are sorted alphabetically and then
   compared character by character, so "KHAN, Ahmed" and "Ahmed Khan" score 100 and small spelling variations
   ("Tehrani" vs "Tehrany") still score around 90.
3. Individuals are only compared with individuals, companies with companies.
4. A **one-word name against a longer name** is ignored, and so are very short names: too weak to mean anything.
5. Anything at or above the **threshold (default 85)** becomes an alert. Lower finds more variants but more
   false positives.
6. **Secondary identifiers** are checked and shown: same nationality, same birth year.
7. Alerts are **never duplicated**: the database refuses a second alert for the same name against the same list
   entry (`UNIQUE` constraint), so reviewed alerts don't come back.

**Who is screened** (`parties()`): every customer plus every shareholder, director and manager in their ownership
tree. Screening runs automatically when you add a customer or an owner, and on demand for everyone.

### Decisions (`decide()`)

* **False positive:** identifiers differ; documented and closed.
* **Potential match (escalate):** can't rule it out → in the UAE, suspend and file a **PNMR** through goAML.
* **True match:** freeze without delay, file an **FFR** through goAML. The customer is rescored (+100, High) and
  can no longer be approved.

---

## 4. Transaction monitoring

**Where:** `tm.py`; pages `pages/6_Transaction_Monitoring.py` and `pages/7_Cases.py`

### Import (`import_csv()`)

Each row is checked: the customer must exist, date and amount must be readable, direction must be IN or OUT, the
currency must be known. Amounts are converted to AED with fixed rates (`FX_TO_AED`). Rejected rows are listed
with the reason; duplicates (same `txn_id`) are skipped.

### Rules (`run_rules()`, settings in `DEFAULT_RULES`)

| Rule | Logic | Severity | Typology |
|---|---|---|---|
| Large cash | one cash transaction ≥ AED 55,000 | Medium | Cash placement |
| Possible structuring | ≥ 3 cash transactions between AED 40,000 and 54,999 within 7 days | High | Smurfing below the threshold |
| High risk jurisdiction | any transaction with a FATF black list (High) or grey list (Medium) country | High / Medium | Cross-border risk |
| Rapid movement of funds | an incoming amount ≥ AED 100,000 and ≥ 80% of it sent out within 3 days | High | Layering, mule accounts |
| Activity above profile | a month's total > 2 × expected monthly volume (and ≥ AED 50,000) | Medium | Doesn't match KYC |
| Repeated round amounts | ≥ 3 transactions that are exact multiples of AED 10,000 within 30 days | Low | Trade-based laundering |
| Sanctioned counterparty | counterparty name scores ≥ 90 against any loaded sanctions list | Critical | Sanctions evasion |

Every number above can be changed on the *Rules* tab for experimenting. Alerts are de-duplicated by customer +
rule + period, so running the rules again only adds genuinely new alerts.

### From alert to case to STR

1. **Triage** (*Alerts* tab): either close alerts with an explanation (`close_alert()`), or tick them and
   **open a case** (`open_case()`).
2. **Investigate** (*Cases* page): see every transaction for the customer and their KYC, write the narrative.
3. **Decide** (`update_case()`): *Closed – no suspicion*, or **STR filed**. Closing or filing requires a
   narrative and a rationale.
4. **STR draft** (`str_report()`): builds a text report laid out like the goAML sections (subject, red flags,
   transactions, narrative, action taken) that you can download.
5. Filing an STR **rescores the customer** (+40, High).

**Sample data** (`make_sample_transactions.py`): 90 days of normal activity for every dummy customer, plus planted
patterns: structuring (Reza Tehrani), large cash and round amounts (Golden Sands Jewellery), pass-through to a
sanctioned name (Blue Harbour Holdings), remittances to high risk countries (Falcon Exchange House), cash
donations wired to Yemen (Hope Bridge Charity), and a salary account with sudden large inflows (Priya Nair).

---

## 5. Audit trail

**Where:** `db.log()`, page `pages/3_Audit_Log.py`

Every write (customer created or edited, document ticked, KYC decision, owner added or removed, list refreshed,
screening run, alert decision, case update) records **who, when, what and why**. Regulators expect you to show
not only the decision but the reasoning, and to keep records for at least 5 years.

---

## 6. Look and feel

`ui.py` holds the shared pieces: the dark neon CSS, the stat cards (`stat_card()`), the chart styling
(`neon_chart()`) and the customer form (`customer_form()`). `.streamlit/config.toml` sets the dark theme.

## Where to change things

| I want to… | Edit |
|---|---|
| Change risk points, bands or review cycles | `risk.py` |
| Update FATF country lists | `FATF_BLACKLIST` / `FATF_GREYLIST` in `risk.py` |
| Change the UBO threshold or offshore list | `UBO_THRESHOLD` / `OFFSHORE` in `ubo.py` |
| Tune name matching | `COMPANY_WORDS`, `normalise()`, `screen()` in `sanctions.py` |
| Change monitoring thresholds permanently | `DEFAULT_RULES` in `tm.py` |
| Add a monitoring rule | add a block in `tm.run_rules()` and an entry in `DEFAULT_RULES` |
