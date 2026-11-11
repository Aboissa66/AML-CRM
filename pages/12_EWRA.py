"""Enterprise-wide risk assessment (EWRA): inherent risk from live data, control strength from testing,
residual risk, action plan and approval."""

from datetime import date

import pandas as pd
import streamlit as st

import ewra
import reports
from ui import setup, stat_card

setup("Risk assessment (EWRA)")
st.title("Enterprise-wide risk assessment")
st.caption("How exposed the whole firm is to money laundering, terrorist financing, proliferation financing and "
           "sanctions risk, how well the controls hold, and what must be done. Inherent risk comes from live "
           "Sanad data; control strength comes from Effectiveness testing.")
user = st.session_state["user"]

LV = {"Low": "🟢 Low", "Medium": "🟡 Medium", "Medium-High": "🟠 Medium-High", "High": "🔴 High"}
STR = {"Strong": "🟢 Strong", "Adequate": "🔵 Adequate", "Needs improvement": "🟠 Needs improvement",
       "Weak": "🔴 Weak"}

assessments = ewra.assessments_df()
top = st.columns([3, 1])
with top[1].popover("➕ New assessment", use_container_width=True):
    with st.form("new_ewra"):
        year = st.number_input("Year", 2020, 2100, date.today().year)
        appetite = st.selectbox("Risk appetite", ewra.LEVELS, index=1)
        products = st.text_area("Products and services offered", "Current and corporate accounts, transfers")
        prating = st.selectbox("Products and services inherent risk", ewra.INHERENT_LEVELS, index=1)
        if st.form_submit_button("Create draft", type="primary"):
            st.session_state["ewra_id"] = ewra.create(int(year), appetite, products, prating, user)
            st.rerun()
if assessments.empty:
    st.info("No assessment yet. Create one with **New assessment**.")
    st.stop()

labels = {f"EWRA {r.year} · {r.version} · {ewra.WORKFLOW[r.stage]}": int(r.id) for r in assessments.itertuples()}
keys = list(labels)
default = st.session_state.get("ewra_id")
idx = next((i for i, k in enumerate(keys) if labels[k] == default), 0)
eid = labels[top[0].selectbox("Assessment", keys, index=idx)]
e = ewra.get(eid)
frozen = bool(e["snapshot"])
df = ewra.compute(e)
appetite = e["appetite"] or "Medium"

# --- status strip ------------------------------------------------------------
with st.container(border=True):
    c1, c2 = st.columns([1.3, 2])
    last = ewra.latest_approved()
    c1.markdown(f"**EWRA {e['year']} · {e['version']}**  \n"
                f"Created {e['created_on']} · "
                + (f"approved {e['approved_on']}, results frozen" if frozen else "results are live until Board approval"))
    c1.caption("Last approved: " + (f"EWRA {last['year']} {last['version']} on {last['approved_on']}"
                                    if last else "none yet"))
    c2.markdown("  ".join(("✅" if i < e["stage"] else "➡️" if i == e["stage"] else "⬜") + f" {i + 1}. {s}"
                          for i, s in enumerate(ewra.WORKFLOW)))
    if e["stage"] < len(ewra.WORKFLOW) - 1:
        nxt = ewra.WORKFLOW[e["stage"] + 1]
        with c2.form(f"adv_{eid}"):
            note = st.text_input(f"Note for the move to '{nxt}' (who reviewed or approved, meeting reference)")
            if st.form_submit_button(f"Move to: {nxt}", type="primary"):
                if note.strip():
                    ewra.advance(eid, note.strip(), user)
                    st.rerun()
                else:
                    st.error("Write a note: approvals need evidence.")

# --- headline ---------------------------------------------------------------
over = df[df["Above appetite"]]
k = st.columns(5)
stat_card(k[0], "Overall residual risk", ewra.overall(list(df.Residual)), sub=f"appetite: {appetite}")
stat_card(k[1], "Inherent risk", ewra.overall(list(df.Inherent)),
          sub=f"{int((df.Inherent == 'High').sum())} of {len(df)} factors High")
ok = int(df["Control strength"].isin(["Strong", "Adequate"]).sum())
stat_card(k[2], "Controls holding", f"{ok} of {len(df)}", sub="factors with Strong or Adequate controls")
stat_card(k[3], "Above appetite", f"{len(over)} of {len(df)}", sub=", ".join(over["Risk factor"]) or "none")
acts = ewra.actions_df(eid)
stat_card(k[4], "Open actions", int((acts.status != "Done").sum()) if not acts.empty else 0,
          sub=f"{int((acts.status == 'Overdue').sum()) if not acts.empty else 0} overdue")

# --- factors ----------------------------------------------------------------
st.subheader("Risk factors")
st.caption("Indicators are pulled from Sanad. The MLRO can override an inherent rating with a reason; the "
           "override and reason go to the audit log." + (" This version is approved, so the figures are frozen."
                                                       if frozen else ""))
view = df.assign(Inherent=[LV[x] + (" (override)" if r else "") for x, r in zip(df.Inherent, df["Override reason"])],
                 **{"Control strength": df["Control strength"].map(STR), "Residual": df.Residual.map(LV),
                    "vs appetite": ["⚠️ Above" if a else "✅ Within" for a in df["Above appetite"]]})
st.table(view[["Risk factor", "Live indicators", "Inherent", "Controls (latest test)", "Control strength",
                   "Residual", "vs appetite"]].set_index("Risk factor"))   # st.table wraps long text

if True:
    st.subheader("Residual risk map")
    cols = ewra.STRENGTHS
    grid = pd.DataFrame("", index=[f"{r} inherent" for r in reversed(ewra.INHERENT_LEVELS)], columns=cols)
    for r in df.itertuples():
        cell = grid.loc[f"{r.Inherent} inherent", r[7]]
        grid.loc[f"{r.Inherent} inherent", r[7]] = (cell + " · " if cell else "") + r[1]
    colour = {"High": "#F6C9C4", "Medium-High": "#FBD9BE", "Medium": "#FCEBC6", "Low": "#D3EEDA"}

    def paint(col):
        return [f"background-color: {colour[ewra.RESIDUAL[i.split()[0]][col.name]]}; font-weight: 600"
                for i in col.index]
    st.dataframe(grid.style.apply(paint), width="stretch")
    st.caption(f"Rows: inherent risk. Columns: control strength. Colour: residual risk (green Low, yellow Medium, "
               f"orange Medium-High, red High). Appetite is **{appetite}**: anything above it needs an action.")
with st.expander("How it is scored"):
    for f, rule in ewra.INHERENT_RULES.items():
        st.markdown(f"- **{f}:** {rule}")
    st.markdown("- **Control strength:** any Ineffective test = Weak; all Effective = Strong; mostly Effective = "
                "Adequate; otherwise, or never tested = Needs improvement.\n"
                "- **Overall:** the highest factor, except that a single High factor gives Medium-High.")

# --- MLRO inputs -------------------------------------------------------------
if not frozen:
    with st.expander("✏️ MLRO inputs: appetite, products, overrides"):
        c1, c2 = st.columns(2)
        with c1.form(f"settings_{eid}"):
            st.markdown("**Appetite and products**")
            ap = st.selectbox("Risk appetite", ewra.LEVELS, index=ewra.LEVELS.index(appetite))
            pt = st.text_area("Products and services offered", e["products_text"] or "")
            pr = st.selectbox("Products and services inherent risk", ewra.INHERENT_LEVELS,
                              index=ewra.INHERENT_LEVELS.index(e["products_rating"] or "Medium"))
            if st.form_submit_button("Save"):
                ewra.update_settings(eid, ap, pt, pr, user)
                st.rerun()
        with c2.form(f"override_{eid}"):
            st.markdown("**Override an inherent rating**")
            factor = st.selectbox("Risk factor", list(ewra.FACTORS))
            rating = st.selectbox("Rating", ["Back to calculated"] + ewra.INHERENT_LEVELS)
            reason = st.text_area("Reason (required)")
            if st.form_submit_button("Apply"):
                if reason.strip():
                    ewra.set_override(eid, factor, None if rating == "Back to calculated" else rating,
                                      reason.strip(), user)
                    st.rerun()
                else:
                    st.error("Give a reason: overrides must be justified.")

# --- action plan --------------------------------------------------------------
st.subheader("Action plan")
STATUS = {"Open": "🔵 Open", "Overdue": "🔴 Overdue", "Done": "🟢 Done"}
if acts.empty:
    st.caption("No actions yet.")
else:
    st.dataframe(acts.assign(Status=acts.status.map(STATUS))[["id", "action", "factor", "owner", "due", "Status",
                                                              "note"]],
                 hide_index=True, width="stretch",
                 column_config={"id": "#", "action": "Action", "factor": "Risk factor", "owner": "Owner",
                                "due": "Due", "note": "Closure note"})
c1, c2 = st.columns(2)
with c1.form(f"act_{eid}"):
    st.markdown("**Add an action**")
    f = st.selectbox("Risk factor", list(ewra.FACTORS), key=f"af_{eid}",
                     index=list(ewra.FACTORS).index(over["Risk factor"].iloc[0]) if not over.empty else 0)
    a = st.text_input("Action")
    o = st.text_input("Owner")
    d = st.date_input("Due date", format="DD/MM/YYYY")
    if st.form_submit_button("Add action", type="primary"):
        if a.strip() and o.strip():
            ewra.add_action(eid, f, a.strip(), o.strip(), d.isoformat(), user)
            st.rerun()
        else:
            st.error("Fill in the action and the owner.")
with c2.form(f"close_{eid}"):
    st.markdown("**Mark an action done**")
    open_a = {f"#{r.id} {r.action}": int(r.id) for r in acts.itertuples() if r.status != "Done"} if not acts.empty else {}
    pick = st.selectbox("Action", list(open_a) or ["No open actions"])
    note = st.text_area("What was done and how it was checked")
    if st.form_submit_button("Mark done"):
        if open_a and note.strip():
            ewra.close_action(open_a[pick], note.strip(), user)
            st.rerun()
        else:
            st.error("Pick an action and describe what was done.")

# --- export -------------------------------------------------------------------
st.download_button("⬇️ Download the EWRA as Excel",
                   reports.to_excel("Enterprise-wide risk assessment", ewra.report_sections(e),
                                    f"EWRA {e['year']} {e['version']}"),
                   f"Sanad_EWRA_{e['year']}_{e['version']}.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with st.expander("📘 AML note: the enterprise-wide risk assessment"):
    st.markdown("""
Every UAE reporting entity must **identify and assess** its own money laundering, terrorist financing and
proliferation financing risks, **document** the assessment, keep it **up to date**, and have it **approved by
senior management** (Federal Decree-Law No. 20 of 2018 and Cabinet Decision No. 10 of 2019). It should take the
**UAE National Risk Assessment** into account.

It drives everything else: the risk appetite, the customer risk model, how often controls are tested, and where
resources go. Review it at least yearly, and sooner after a trigger event such as a new product, a new
country, a regulatory change or a serious finding. Inspectors usually ask for it first.
""")
