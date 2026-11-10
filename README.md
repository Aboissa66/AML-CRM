# AML Compliance CRM (prototype)

A small learning project: KYC, customer risk rating, UBO identification, sanctions screening
and transaction monitoring for a UAE context. **Dummy data only.**

See [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for the logic behind every feature.

## Run it (Windows or Mac)

1. Install Python 3.11 or newer from python.org (on Windows, tick "Add Python to PATH").
2. Open a terminal in this folder and run:

   ```
   pip install -r requirements.txt
   streamlit run Dashboard.py
   ```

3. Your browser opens at http://localhost:8501. The first launch creates 30 fictional customers.

To start over with fresh dummy data, use **Reset to fresh dummy data** on the Audit Log page,
or run `python seed.py`.

## What's in it

| Page | What you can do |
|---|---|
| Dashboard | Risk and KYC status overview, expired IDs, pending KYC, overdue reviews |
| Customers | Search and filter, open a profile, edit KYC details, see why the risk rating was given, tick off documents, approve or reject with a rationale, view the audit trail |
| Add Customer | Onboard an individual or company; risk rating and document checklist are generated |
| Audit Log | Every action, who did it and when |
| Ownership & UBO | Record shareholders (people or companies, in layers), directors and managers; see the ownership tree, effective percentages, the UBOs (25% rule with senior management fallback) and ownership red flags, which feed the risk score |
| Sanctions Screening | Download OFAC, UN and EU lists, upload the UAE Local Terrorist List, fuzzy-screen every customer, owner, director and manager, and review alerts (false positive, potential match / PNMR, true match / FFR). A fictional training list is built in |
| Transaction Monitoring | Upload transactions as CSV (or load the 436-row sample with planted red flags), run 7 tunable rules (large cash, structuring, high risk countries, rapid in/out, profile deviation, round amounts, sanctioned counterparties) and triage alerts |
| Cases | Investigate alerts, write the narrative, close or file an STR, and download a goAML-style STR draft. An STR moves the customer to High risk |

## Files

| File | Purpose |
|---|---|
| `Dashboard.py` | Home page |
| `pages/` | The other pages |
| `sanctions.py` | List download, parsing and fuzzy name screening |
| `tm.py` | Transaction import, monitoring rules, alerts, cases and STR drafts |
| `make_sample_transactions.py` | Regenerates `data/sample_transactions.csv` |
| `ubo.py` | UBO calculation and ownership red flags |
| `risk.py` | Risk scoring rules, country and sector lists, review cycles, document checklists. **Edit this to change how customers are rated.** |
| `db.py` | SQLite database (`aml_crm.db`, created automatically) |
| `seed.py` | Dummy data generator |
| `ui.py` | Shared form and layout pieces |

## Ideas for later

- Connect a payments API instead of CSV uploads
- Scheduled daily list refresh and rescreening
- User logins and four-eyes approval

The country lists in `risk.py` are samples. Check the current FATF lists before relying on them.
