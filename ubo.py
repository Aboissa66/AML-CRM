"""Ultimate beneficial owner (UBO) calculation.

UAE rule of thumb (Cabinet Decision No. 109 of 2023 on beneficial ownership):
  1. A UBO is a natural person who ultimately owns or controls 25% or more of the
     company, directly or indirectly (through other companies).
  2. If nobody reaches 25%, look for a natural person who controls it by other means.
  3. If still nobody, the natural person in the senior management position is
     recorded as the UBO.

Ownership is stored as a tree: each owner row either owns the customer directly
(parent_owner_id is empty) or owns a corporate owner one layer up.
Indirect ownership is the product of the percentages along the chain, so a person
holding 50% of a company that holds 60% of the customer has 30%.
"""

from collections import defaultdict

from risk import FATF_BLACKLIST, FATF_GREYLIST

UBO_THRESHOLD = 25.0

# Jurisdictions often used for layering through shell companies. Sample list only.
OFFSHORE = {
    "British Virgin Islands", "Cayman Islands", "Seychelles", "Panama", "Belize",
    "Marshall Islands", "Bahamas", "Isle of Man", "Jersey", "Guernsey",
}

ROLES = ["Shareholder", "Director", "Senior manager"]


def analyse(owners: list[dict]) -> dict:
    """Work out effective ownership, UBOs and red flags for one company."""
    children = defaultdict(list)
    for o in owners:
        children[o["parent_owner_id"]].append(o)

    people: dict[str, dict] = {}   # natural persons, merged by name
    corporates = []
    max_layers = 0
    gaps = []                      # (entity name, % not accounted for)

    def walk(parent_id, parent_name, factor, depth):
        nonlocal max_layers
        holders = [o for o in children[parent_id] if o["role"] == "Shareholder"]
        declared = sum(o["pct"] or 0 for o in holders)
        # A company with no shareholders at all (e.g. a charity) is handled by the
        # senior management fallback; a corporate owner with gaps is always a red flag.
        if declared < 99.99 and (holders or depth > 1):
            gaps.append((parent_name, round(100 - declared, 2)))
        for o in children[parent_id]:
            eff = factor * (o["pct"] or 0) / 100 if o["role"] == "Shareholder" else 0
            if o["owner_type"] == "Company":
                max_layers = max(max_layers, depth)
                corporates.append({**o, "effective_pct": round(eff * 100, 2), "layer": depth})
                walk(o["id"], o["name"], eff, depth + 1)
            else:
                p = people.setdefault(o["name"], {
                    "name": o["name"], "nationality": o["nationality"], "pep": 0,
                    "effective_pct": 0.0, "roles": set(), "paths": 0})
                p["effective_pct"] += eff * 100
                p["roles"].add(o["role"])
                p["pep"] = max(p["pep"], o["pep"] or 0)
                p["paths"] += 1

    walk(None, "the customer", 1.0, 1)

    for p in people.values():
        p["effective_pct"] = round(p["effective_pct"], 2)
        p["roles"] = ", ".join(sorted(p["roles"]))

    ubos = [p for p in people.values() if p["effective_pct"] >= UBO_THRESHOLD]
    basis = "Ownership of 25% or more"
    if not ubos:
        ubos = [p for p in people.values() if "Senior manager" in p["roles"]] or \
               [p for p in people.values() if "Director" in p["roles"]]
        basis = "No one reaches 25%: senior management recorded as UBO (fallback)"
    for p in people.values():
        p["is_ubo"] = p in ubos

    risky_corporates = [c for c in corporates
                        if c["nationality"] in OFFSHORE | FATF_GREYLIST | FATF_BLACKLIST]
    return {
        "people": sorted(people.values(), key=lambda p: -p["effective_pct"]),
        "corporates": corporates,
        "ubos": ubos,
        "basis": basis,
        "fallback": basis.startswith("No one"),
        "layers": max_layers,                       # number of corporate layers
        "gaps": [g for g in gaps if g[1] > 0],
        "risky_corporates": risky_corporates,
        "pep_involved": any(p["pep"] for p in people.values()),
        "has_owners": bool(owners),
    }


def risk_factors(a: dict) -> list[tuple[int, str]]:
    """Extra risk points that come from the ownership structure."""
    if not a["has_owners"]:
        return [(10, "Ownership not yet recorded")]
    out = []
    if a["layers"] >= 2:
        out.append((15, f"Complex structure: {a['layers']} layers of companies"))
    if a["risky_corporates"]:
        names = ", ".join(f"{c['name']} ({c['nationality']})" for c in a["risky_corporates"])
        out.append((15, f"Owned through offshore or high risk jurisdiction: {names}"))
    if a["fallback"]:
        out.append((10, "No natural person owns 25% or more"))
    if a["gaps"]:
        g = ", ".join(f"{pct:g}% of {name}" for name, pct in a["gaps"])
        out.append((10, f"Ownership not fully identified: {g}"))
    return out
