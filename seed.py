"""Creates about 30 fictional customers so you have something to practise on.

All people and companies here are invented. Run `python seed.py` to rebuild the
database from scratch (this deletes everything in aml_crm.db).
"""

import random
from datetime import date, timedelta

import db
from risk import ACTIVITIES, SOURCES_OF_FUNDS

random.seed(42)

FIRST = ["Ahmed", "Fatima", "Omar", "Layla", "Rahul", "Priya", "John", "Sarah",
         "Wei", "Mei", "Yusuf", "Aisha", "Carlos", "Elena", "Hassan", "Noor",
         "Ivan", "Olga", "Kofi", "Amina"]
LAST = ["Al Mansoori", "Haddad", "Sharma", "Khan", "Smith", "Chen", "Petrov",
        "Okafor", "Rahman", "Garcia", "Nasser", "Mehta", "Ibrahim", "Silva"]

# Hand-picked profiles so every rating and red flag shows up at least once.
FIXED = [
    dict(customer_type="Individual", full_name="Khalid Al Shamsi", nationality="United Arab Emirates",
         residence_country="United Arab Emirates", activity="Government employee", source_of_funds="Salary",
         expected_monthly_volume=60_000, pep=1, cash_intensive=0, channel="Face to face"),
    dict(customer_type="Individual", full_name="Reza Tehrani", nationality="Iran",
         residence_country="United Arab Emirates", activity="General trading", source_of_funds="Business income",
         expected_monthly_volume=400_000, pep=0, cash_intensive=1, channel="Face to face"),
    dict(customer_type="Company", full_name="Golden Sands Jewellery LLC", nationality="United Arab Emirates",
         residence_country="United Arab Emirates", activity="Dealer in precious metals and stones",
         source_of_funds="Business income", expected_monthly_volume=2_500_000, pep=0, cash_intensive=1,
         channel="Face to face"),
    dict(customer_type="Company", full_name="Blue Harbour Holdings Ltd", nationality="British Virgin Islands",
         residence_country="United Arab Emirates", activity="General trading", source_of_funds="Other / unclear",
         expected_monthly_volume=1_200_000, pep=0, cash_intensive=0, channel="Non face to face"),
    dict(customer_type="Company", full_name="Falcon Exchange House LLC", nationality="United Arab Emirates",
         residence_country="United Arab Emirates", activity="Money exchange / remittance",
         source_of_funds="Business income", expected_monthly_volume=5_000_000, pep=0, cash_intensive=1,
         channel="Face to face"),
    dict(customer_type="Company", full_name="Hope Bridge Charity Foundation", nationality="United Arab Emirates",
         residence_country="Yemen", activity="Charity / non-profit", source_of_funds="Other / unclear",
         expected_monthly_volume=150_000, pep=0, cash_intensive=1, channel="Non face to face"),
    dict(customer_type="Individual", full_name="Priya Nair", nationality="India",
         residence_country="United Arab Emirates", activity="Salaried employee", source_of_funds="Salary",
         expected_monthly_volume=25_000, pep=0, cash_intensive=0, channel="Face to face"),
    dict(customer_type="Company", full_name="Desert Bytes IT Solutions FZ-LLC", nationality="United Arab Emirates",
         residence_country="United Arab Emirates", activity="IT services", source_of_funds="Business income",
         expected_monthly_volume=300_000, pep=0, cash_intensive=0, channel="Face to face"),
]

COMPANY_SUFFIX = ["Trading LLC", "General Trading FZE", "Logistics LLC", "Contracting LLC",
                  "Consultancy FZ-LLC", "Real Estate LLC", "Auto Trading LLC", "Restaurant LLC"]
COMPANY_WORDS = ["Oasis", "Palm", "Crescent", "Marina", "Summit", "Pearl", "Horizon", "Atlas", "Cedar", "Nile"]
COUNTRY_POOL = (["United Arab Emirates"] * 8 + ["India", "Pakistan", "Egypt", "United Kingdom",
                "Philippines", "Russia", "China", "Jordan", "Nigeria", "Lebanon", "Syria"])


def random_customer() -> dict:
    is_company = random.random() < 0.35
    if is_company:
        name = f"{random.choice(COMPANY_WORDS)} {random.choice(COMPANY_SUFFIX)}"
        activity = random.choice(["General trading", "Freight / logistics", "Construction", "Consultancy",
                                  "Real estate broker / developer", "Used car dealer", "Restaurant / hospitality"])
        sof = "Business income"
        volume = random.choice([100_000, 250_000, 500_000, 900_000, 1_500_000])
        nationality = "United Arab Emirates"
    else:
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        activity = random.choice(ACTIVITIES)
        sof = random.choice(SOURCES_OF_FUNDS)
        volume = random.choice([5_000, 15_000, 30_000, 80_000, 300_000])
        nationality = random.choice(COUNTRY_POOL)
    return dict(
        customer_type="Company" if is_company else "Individual",
        full_name=name,
        nationality=nationality,
        residence_country="United Arab Emirates" if random.random() < 0.85 else random.choice(COUNTRY_POOL),
        activity=activity,
        source_of_funds=sof,
        expected_monthly_volume=volume,
        pep=0,
        cash_intensive=int(random.random() < 0.2),
        channel="Face to face" if random.random() < 0.7 else "Non face to face",
    )


def fill_ids(c: dict) -> dict:
    if c["customer_type"] == "Company":
        c["id_number"] = f"CN-{random.randint(1000000, 9999999)}"
        c["date_of_birth"] = (date(2005, 1, 1) + timedelta(days=random.randint(0, 6500))).isoformat()
    else:
        c["id_number"] = f"784-{random.randint(1960, 2004)}-{random.randint(1000000, 9999999)}-{random.randint(1, 9)}"
        c["date_of_birth"] = (date(1960, 1, 1) + timedelta(days=random.randint(0, 16000))).isoformat()
    # A few expired IDs so the dashboard has something to flag.
    c["id_expiry"] = (date.today() + timedelta(days=random.randint(-120, 1200))).isoformat()
    c["created_at"] = (date.today() - timedelta(days=random.randint(0, 900))).isoformat()
    return c


# Ownership structures for the hand-picked companies. Each entry is
# (name, type, country, pct, role, pep, [children...]).
FIXED_OWNERS = {
    "Golden Sands Jewellery LLC": [
        ("Rashid Al Falasi", "Individual", "United Arab Emirates", 51, "Shareholder", 0, []),
        ("Vikram Soni", "Individual", "India", 49, "Shareholder", 0, []),
        ("Rashid Al Falasi", "Individual", "United Arab Emirates", 0, "Director", 0, []),
    ],
    "Blue Harbour Holdings Ltd": [
        ("Northwind Ventures Ltd", "Company", "Seychelles", 70, "Shareholder", 0, [
            ("Coral Trust Holdings SA", "Company", "Panama", 100, "Shareholder", 0, [
                ("Dmitri Orlov", "Individual", "Russia", 60, "Shareholder", 0, []),
            ]),
        ]),
        ("Anna Volkova", "Individual", "Russia", 30, "Shareholder", 0, []),
        ("Anna Volkova", "Individual", "Russia", 0, "Director", 0, []),
    ],
    "Falcon Exchange House LLC": [
        ("Saeed Al Hammadi", "Individual", "United Arab Emirates", 40, "Shareholder", 1, []),
        ("Global Remit Holdings Ltd", "Company", "United Kingdom", 60, "Shareholder", 0, [
            ("Omar Siddiqui", "Individual", "Pakistan", 50, "Shareholder", 0, []),
            ("Hira Siddiqui", "Individual", "Pakistan", 50, "Shareholder", 0, []),
        ]),
        ("Farah Haddad", "Individual", "Jordan", 0, "Senior manager", 0, []),
    ],
    "Hope Bridge Charity Foundation": [
        ("Yusuf Rahman", "Individual", "United Arab Emirates", 0, "Director", 0, []),
        ("Amina Okafor", "Individual", "Nigeria", 0, "Senior manager", 0, []),
    ],
    "Desert Bytes IT Solutions FZ-LLC": [
        ("Arjun Menon", "Individual", "India", 100, "Shareholder", 0, []),
        ("Arjun Menon", "Individual", "India", 0, "Director", 0, []),
    ],
}


def _add_tree(cid, nodes, parent=None):
    for name, otype, country, pct, role, pep, kids in nodes:
        oid = db.add_owner(cid, dict(parent_owner_id=parent, name=name, owner_type=otype, nationality=country,
                                     pct=pct, role=role, pep=pep), user="seed")
        _add_tree(cid, kids, oid)


def seed_owners():
    """Give every company customer an ownership structure (safe to run on an existing database)."""
    rng = random.Random(7)
    companies = db.customers_df().query("customer_type == 'Company'")
    for row in companies.itertuples():
        if row.full_name in FIXED_OWNERS:
            _add_tree(int(row.id), FIXED_OWNERS[row.full_name])
            continue
        n = rng.choice([1, 2, 2, 3])
        cuts = sorted(rng.sample(range(10, 91, 5), n - 1)) if n > 1 else []
        shares = [b - a for a, b in zip([0] + cuts, cuts + [100])]
        names = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in shares]
        nodes = [(nm, "Individual", rng.choice(COUNTRY_POOL), pct, "Shareholder", 0, [])
                 for nm, pct in zip(names, shares)]
        nodes.append((names[0], "Individual", nodes[0][2], 0, "Director", 0, []))
        _add_tree(int(row.id), nodes)


def main():
    db.reset()
    names = set()
    customers = list(FIXED)
    while len(customers) < 30:
        c = random_customer()
        if c["full_name"] not in names:
            names.add(c["full_name"])
            customers.append(c)
    for c in customers:
        cid = db.add_customer(fill_ids(c), user="seed")
        status = random.choices(["Approved", "Pending", "Under review"], [6, 2, 1])[0]
        db.set_kyc_status(cid, status, "Seeded dummy data", user="seed")
        for doc in db.documents_for(cid):
            if status == "Approved" or random.random() < 0.5:
                db.set_document(cid, doc["doc_type"], True, user="seed")
    seed_owners()
    print(f"Created {len(customers)} dummy customers in {db.DB_PATH}")


if __name__ == "__main__":
    main()
