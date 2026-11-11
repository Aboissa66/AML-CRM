# Sanad EWRA: logic and scoring

Sanad rates six risk factors in four steps: how risky the business is (**inherent**), how well the controls work
(**control strength**), what risk is left (**residual**), and whether that is acceptable (**appetite**).

```
Live Sanad data ──► 1 Inherent risk ──┐
                                      ├──► 3 Residual risk ──► 4 Compare with appetite ──► within: monitor
Effectiveness tests ► 2 Control strength ┘                                           └──► above: action plan
```

## Step 1: Inherent risk (first rule that applies)

| Risk factor | High when | Medium when | Otherwise |
|---|---|---|---|
| Customers | Over 25% of customers High risk, or over 40% in high-risk activities | Over 10% High risk, or any PEP | Low |
| Geography | Any customer linked to a FATF black list country, or over 20% of value with grey/black list countries | Over 5% of customers or of value linked | Low |
| Products and services | Set by the MLRO | Set by the MLRO | Set by the MLRO |
| Delivery channels | Over 40% onboarded non face to face | Over 15% | Low |
| Transactions | Over 20% of value in cash | Over 10% cash, or over 10 open monitoring alerts | Low |
| Sanctions and proliferation financing | Any confirmed sanctions match | Any open alert or potential match | Low |

## Step 2: Control strength

| Risk factor | Control areas (latest Effectiveness test) |
|---|---|
| Customers | KYC / CDD, UBO identification, Periodic review |
| Geography | Sanctions screening |
| Products and services | none mapped yet |
| Delivery channels | KYC / CDD |
| Transactions | Transaction monitoring, Alert handling |
| Sanctions and proliferation financing | Sanctions screening |

1. **Weak**: any area Ineffective. 2. **Strong**: all Effective. 3. **Adequate**: more than half Effective.
4. **Needs improvement**: anything else, including never tested or nothing mapped.

## Step 3: Residual risk

| Inherent \ Controls | Strong | Adequate | Needs improvement | Weak |
|---|---|---|---|---|
| **High** | Medium | Medium-High | High | High |
| **Medium** | Low | Medium | Medium | Medium-High |
| **Low** | Low | Low | Low | Medium |

## Step 4: Appetite, overall rating, actions

- **Appetite** (default Medium) is set by the MLRO per assessment. A factor above it needs an action with an owner
  and due date.
- **Overall** = the highest factor, except that a single High factor gives Medium-High; two or more give High.

## Governance

- MLRO overrides of an inherent rating need a reason, logged in the audit trail.
- Workflow: Drafted, Compliance review, Senior management, Board approved, Published to staff; each move needs a note.
- Board approval freezes the results; the next assessment starts as a new draft.
- Review at least yearly and after trigger events. The Governance Dashboard flags a missing or old approval and
  factors above appetite.

All thresholds live in `ewra.py` (`_auto_inherent`, `FACTORS`, `RESIDUAL`, `overall`).
