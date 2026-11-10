"""Customer risk scoring for the AML CRM prototype.

Every rule adds points and a plain-English reason, so you can see exactly why a
customer got their rating. All lists below are SAMPLES for learning. Before any
real use, check them against the current FATF statements, the UAE National
Risk Assessment and your own risk appetite.
"""

from datetime import date, timedelta

# --- Country risk ----------------------------------------------------------
# FATF "call for action" (black list). Always forces a High rating.
FATF_BLACKLIST = {"North Korea", "Iran", "Myanmar"}

# FATF "increased monitoring" (grey list). Sample only: this list changes
# three times a year, so update it from fatf-gafi.org.
FATF_GREYLIST = {
    "Algeria", "Angola", "Bolivia", "Bulgaria", "Burkina Faso", "Cameroon",
    "Cote d'Ivoire", "Democratic Republic of Congo", "Haiti", "Kenya", "Laos",
    "Lebanon", "Monaco", "Mozambique", "Namibia", "Nepal", "Nigeria",
    "South Africa", "South Sudan", "Syria", "Venezuela", "Vietnam", "Yemen",
    "British Virgin Islands",
}

COUNTRIES = sorted({
    "United Arab Emirates", "Saudi Arabia", "Egypt", "India", "Pakistan",
    "United Kingdom", "United States", "Germany", "France", "China", "Russia",
    "Turkey", "Jordan", "Oman", "Qatar", "Kuwait", "Bahrain", "Philippines",
    "Bangladesh", "Sri Lanka", "Switzerland", "Singapore", "Cyprus",
} | FATF_BLACKLIST | FATF_GREYLIST)

# --- Business / occupation risk -------------------------------------------
# Sectors the UAE NRA and FATF typology reports treat as higher ML/TF risk.
HIGH_RISK_ACTIVITIES = {
    "Dealer in precious metals and stones",
    "Real estate broker / developer",
    "Money exchange / remittance",
    "Virtual asset service provider",
    "General trading",
    "Charity / non-profit",
    "Used car dealer",
}
MEDIUM_RISK_ACTIVITIES = {
    "Business owner",
    "Restaurant / hospitality",
    "Construction",
    "Freight / logistics",
    "Consultancy",
}
ACTIVITIES = sorted(HIGH_RISK_ACTIVITIES | MEDIUM_RISK_ACTIVITIES | {
    "Salaried employee", "Government employee", "Student", "Retired",
    "IT services", "Healthcare", "Retail (non-cash)", "Manufacturing",
})

SOURCES_OF_FUNDS = [
    "Salary", "Business income", "Investments", "Inheritance",
    "Sale of property", "Savings", "Loan", "Other / unclear",
]

CHANNELS = ["Face to face", "Non face to face"]

# Rating bands and how often each rating must be reviewed (in years).
BANDS = [(50, "High"), (25, "Medium"), (0, "Low")]
REVIEW_YEARS = {"High": 1, "Medium": 2, "Low": 3}


def score_customer(c: dict, ownership: dict | None = None, sanction_hits: int = 0,
                   str_filed: bool = False) -> tuple[int, str, list[str]]:
    """Return (score, rating, reasons) for a customer dict.

    For companies, pass the result of ubo.analyse() as `ownership` to include
    ownership structure risk (layers, offshore entities, PEPs, missing owners).
    """
    score = 0
    reasons: list[str] = []
    force_high = False

    for label, country in (("Nationality / incorporation", c.get("nationality")),
                           ("Residence / operations", c.get("residence_country"))):
        if country in FATF_BLACKLIST:
            score += 40
            force_high = True
            reasons.append(f"+40 {label} in FATF black list country ({country}), forces High")
        elif country in FATF_GREYLIST:
            score += 20
            reasons.append(f"+20 {label} in FATF grey list country ({country})")

    if c.get("pep"):
        score += 30
        force_high = True
        reasons.append("+30 Politically exposed person, forces High (EDD required)")

    activity = c.get("activity")
    if activity in HIGH_RISK_ACTIVITIES:
        score += 25
        reasons.append(f"+25 High risk activity ({activity})")
    elif activity in MEDIUM_RISK_ACTIVITIES:
        score += 10
        reasons.append(f"+10 Medium risk activity ({activity})")

    if c.get("cash_intensive"):
        score += 15
        reasons.append("+15 Cash intensive")

    if c.get("channel") == "Non face to face":
        score += 10
        reasons.append("+10 Onboarded non face to face")

    if c.get("source_of_funds") == "Other / unclear":
        score += 15
        reasons.append("+15 Source of funds unclear")

    volume = c.get("expected_monthly_volume") or 0
    if volume >= 1_000_000:
        score += 15
        reasons.append("+15 Expected monthly volume of AED 1m or more")
    elif volume >= 250_000:
        score += 5
        reasons.append("+5 Expected monthly volume of AED 250k or more")

    if c.get("customer_type") == "Company":
        score += 5
        reasons.append("+5 Legal entity (ownership must be verified)")
        if ownership is not None:
            from ubo import risk_factors
            for points, why in risk_factors(ownership):
                score += points
                reasons.append(f"+{points} {why}")
            if ownership["pep_involved"] and not c.get("pep"):
                score += 30
                force_high = True
                reasons.append("+30 PEP among owners, directors or managers, forces High (EDD required)")

    if sanction_hits:
        score += 100
        force_high = True
        reasons.append("+100 Confirmed sanctions match: freeze funds, do not proceed, report via goAML")

    if str_filed:
        score += 40
        force_high = True
        reasons.append("+40 Suspicious transaction report filed, forces High (consider exiting the relationship)")

    rating = next(name for floor, name in BANDS if score >= floor)
    if force_high:
        rating = "High"
    if not reasons:
        reasons.append("No risk factors triggered")
    return score, rating, reasons


def next_review_date(rating: str, from_date: date | None = None) -> date:
    start = from_date or date.today()
    return start + timedelta(days=365 * REVIEW_YEARS[rating])


def required_documents(customer_type: str, rating: str) -> list[str]:
    """KYC document checklist by customer type and risk rating."""
    if customer_type == "Company":
        docs = [
            "Trade licence",
            "Memorandum / Articles of association",
            "Shareholder register",
            "Board resolution / authorised signatory",
            "UBO declaration",
            "Emirates ID / passport of signatories",
        ]
    else:
        docs = [
            "Emirates ID or passport",
            "Proof of address",
            "Source of funds evidence",
        ]
    if rating == "High":
        docs += ["Enhanced due diligence form", "Senior management approval"]
    return docs
