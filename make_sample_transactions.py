"""Writes data/sample_transactions.csv: ~90 days of fictional transactions with planted red flags.

Run `python make_sample_transactions.py` to regenerate. Customer IDs match the seeded dummy customers.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

rng = random.Random(2026)
END = datetime(2026, 11, 9, 17, 0)
START = END - timedelta(days=90)
rows = []


def add(cid, when, amount, direction, channel, cp, country, desc, currency="AED"):
    rows.append([None, cid, when.strftime("%Y-%m-%d %H:%M"), round(amount, 2), currency, direction, channel,
                 cp, country, desc])


def day(n, hour=11):
    return START + timedelta(days=n, hours=hour - START.hour, minutes=rng.randint(0, 59))


# --- Normal background activity for every seeded customer -------------------
NORMAL = {  # customer id: (monthly volume, typical counterparties)
    1: 55_000, 7: 22_000, 8: 250_000, 9: 12_000, 10: 90_000, 11: 60_000, 12: 8_000, 13: 120_000,
    14: 15_000, 15: 20_000, 16: 9_000, 17: 30_000, 18: 14_000, 19: 70_000, 20: 25_000, 21: 11_000,
    22: 150_000, 23: 18_000, 24: 80_000, 25: 16_000, 26: 7_000, 27: 110_000, 28: 140_000, 29: 13_000, 30: 21_000,
}
LOCAL = ["Emirates Supplies LLC", "Al Noor Foodstuff Trading", "Dubai Electricity & Water", "Etisalat",
         "Carrefour", "Noon.com", "Al Futtaim Motors", "Gulf Logistics FZE", "Sharjah Rentals"]
for cid, vol in NORMAL.items():
    for month in range(3):
        add(cid, day(month * 30 + 1, 9), vol * rng.uniform(0.5, 0.65), "IN", "Transfer", "Payroll / receivables",
            "United Arab Emirates", "Monthly income")
        for _ in range(rng.randint(3, 6)):
            add(cid, day(month * 30 + rng.randint(2, 28), rng.randint(9, 20)), vol * rng.uniform(0.04, 0.12), "OUT",
                rng.choice(["Card", "Transfer", "Transfer", "Cheque"]), rng.choice(LOCAL), "United Arab Emirates",
                "Payment")

# --- Planted red flags --------------------------------------------------------
# Reza Tehrani (2): structuring, four cash deposits just under AED 55,000 in six days
for d, amt in [(40, 49_500), (42, 52_000), (44, 47_800), (45, 53_900)]:
    add(2, day(d, 13), amt, "IN", "Cash", "Branch deposit", "United Arab Emirates", "Cash deposit")
add(2, day(47, 10), 180_000, "OUT", "Wire", "Pars Commodities Co", "Iran", "Goods payment")

# Golden Sands Jewellery (3): large cash and round amounts
for d, amt in [(10, 60_000), (25, 120_000), (55, 80_000), (70, 95_500)]:
    add(3, day(d, 16), amt, "IN", "Cash", "Walk-in customer", "United Arab Emirates", "Gold bullion sale")
for d in (12, 20, 30):
    add(3, day(d), 100_000, "OUT", "Wire", "Istanbul Gold Refinery", "Turkey", "Gold purchase")

# Blue Harbour Holdings (4): money in from offshore and straight out again, sanctioned counterparty
add(4, day(60, 10), 400_000, "IN", "Wire", "Northwind Ventures Ltd", "Seychelles", "Shareholder loan", "USD")
add(4, day(61, 15), 720_000, "OUT", "Wire", "Lakeview Trading", "Turkey", "Consultancy fees")
add(4, day(62, 11), 650_000, "OUT", "Wire", "Coral Trust Holdings S.A.", "Panama", "Management fees")

# Falcon Exchange House (5): remittances to high risk jurisdictions
for d, amt, cp, ctry in [(15, 210_000, "Kish Exchange", "Iran"), (35, 95_000, "Damascus Money Transfer", "Syria"),
                         (50, 130_000, "Sanaa Remit", "Yemen"), (75, 88_000, "Lagos Express FX", "Nigeria")]:
    add(5, day(d), amt, "OUT", "Wire", cp, ctry, "Customer remittance")
for d in range(3, 90, 21):
    add(5, day(d, 9), rng.uniform(300_000, 500_000), "IN", "Cash", "Branch cash collection", "United Arab Emirates",
        "Daily cash takings")

# Hope Bridge Charity (6): cash donations wired abroad
for d in (5, 18, 33, 48, 63):
    add(6, day(d, 12), rng.uniform(20_000, 35_000), "IN", "Cash", "Donation box", "United Arab Emirates", "Donations")
for d, amt in [(20, 70_000), (50, 85_000)]:
    add(6, day(d), amt, "OUT", "Wire", "Relief Partners Sanaa", "Yemen", "Aid project")

# Priya Nair (7): salaried employee suddenly receiving far more than expected
for d, amt, cp in [(66, 30_000, "R. Kapoor"), (68, 25_000, "S. Mehta"), (70, 28_000, "Unknown remitter"),
                   (72, 20_000, "Unknown remitter")]:
    add(7, day(d), amt, "IN", "Transfer", cp, "India", "Transfer")
add(7, day(74), 95_000, "OUT", "Transfer", "Crypto Exchange FZE", "United Arab Emirates", "Top-up")

rows.sort(key=lambda r: r[2])
for i, r in enumerate(rows, 1):
    r[0] = f"T-{i:05d}"
out = Path(__file__).with_name("data") / "sample_transactions.csv"
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["txn_id", "customer_id", "date", "amount", "currency", "direction", "channel", "counterparty",
                "counterparty_country", "description"])
    w.writerows(rows)
print(f"Wrote {len(rows)} transactions to {out}")
