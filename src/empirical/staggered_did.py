"""
Phase D — D6: Staggered DID (Callaway-Sant'Anna + Sun-Abraham).
Province-year level.
"""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis"
TAB = OUT / "tables"
LOG = OUT / "logs"


def run_csdid(panel, yname):
    from csdid.att_gt import ATTgt

    df = panel.dropna(subset=[yname]).copy()
    df["gname"] = df["epvr_first_year_p"].fillna(0).astype(int)
    tmax = int(df["year"].max())
    df.loc[df["gname"] > tmax, "gname"] = 0
    df["province_code"] = df["province_code"].astype(int)
    df = df[["province_code", "year", "gname", yname]].copy()

    try:
        att = ATTgt(
            yname=yname,
            tname="year",
            idname="province_code",
            gname="gname",
            data=df,
            panel=True,
            allow_unbalanced_panel=True,
            control_group="nevertreated",
            anticipation=0,
        )
        att.fit(est_method="reg", bstrap=False)
    except Exception as e:
        return {"error": str(e), "outcome": yname}

    out = {"outcome": yname, "error": ""}
    # Manual aggregation from att.MP (csdid aggte has a bug with scalar boolean
    # in compute_aggte/utils.py; we compute aggregates directly from group-time
    # ATTs to avoid that codepath).
    mp = att.MP
    g = np.array(mp["group"])
    t = np.array(mp["t"])
    a = np.array(mp["att"], dtype=float)
    inff_obj = mp["inffunc"]
    if isinstance(inff_obj, dict):
        inff = np.array(inff_obj["inffunc"])
    else:
        inff = np.array(inff_obj)
    n_units = mp["n"]

    # Filter to post-treatment (t >= g) and finite values
    post_mask = (t >= g) & np.isfinite(a)
    a_post = a[post_mask]
    inff_post = inff[:, post_mask]

    if len(a_post) > 0:
        # Simple ATT = mean of post-treatment att
        w = np.ones(len(a_post)) / len(a_post)
        out["att_simple"] = float(np.dot(w, a_post))
        # SE via influence functions: var = (1/n) * Var(IF @ w)
        if_aggr = inff_post @ w
        se = float(np.sqrt(np.var(if_aggr, ddof=0) / n_units))
        out["att_simple_se"] = se
    else:
        out["att_simple"] = np.nan
        out["att_simple_se"] = np.nan

    # Group ATT: average post-treatment att within each group, then average across groups
    groups = sorted(set(g[g > 0]))
    grp_atts = []
    grp_ses = []
    for gg in groups:
        mask = (g == gg) & (t >= gg) & np.isfinite(a)
        if mask.sum() == 0:
            continue
        a_g = a[mask]
        if_g = inff[:, mask]
        wg = np.ones(len(a_g)) / len(a_g)
        grp_atts.append(np.dot(wg, a_g))
        grp_ses.append(np.sqrt(np.var(if_g @ wg, ddof=0) / n_units))
    if grp_atts:
        out["att_group"] = float(np.mean(grp_atts))
        # SE for group-aggregated ATT: combine influence functions
        all_if = []
        all_w = []
        for gg in groups:
            mask = (g == gg) & (t >= gg) & np.isfinite(a)
            if mask.sum() == 0:
                continue
            all_if.append(inff[:, mask])
            wg = np.ones(mask.sum()) / mask.sum() / len(groups)
            all_w.append(wg)
        if all_if:
            big_if = np.concatenate(all_if, axis=1)
            big_w = np.concatenate(all_w)
            out["att_group_se"] = float(np.sqrt(np.var(big_if @ big_w, ddof=0) / n_units))
        else:
            out["att_group_se"] = np.nan
    else:
        out["att_group"] = np.nan
        out["att_group_se"] = np.nan

    # Dynamic / event-study aggregation: average post-treatment att by event time e = t - g
    e = t - g
    post_mask = (g > 0) & np.isfinite(a)
    e_post = e[post_mask]
    a_post = a[post_mask]
    inff_post = inff[:, post_mask]
    dyn_e_list = []
    dyn_att_list = []
    dyn_se_list = []
    for ek in sorted(set(e_post)):
        if ek < -5 or ek > 5:
            continue
        m = (e_post == ek)
        if m.sum() == 0:
            continue
        a_e = a_post[m]
        if_e = inff_post[:, m]
        we = np.ones(len(a_e)) / len(a_e)
        att_e = float(np.dot(we, a_e))
        se_e = float(np.sqrt(np.var(if_e @ we, ddof=0) / n_units))
        dyn_e_list.append(int(ek))
        dyn_att_list.append(att_e)
        dyn_se_list.append(se_e)
    out["dyn_e"] = dyn_e_list
    out["dyn_att"] = dyn_att_list
    out["dyn_se"] = dyn_se_list

    # Dynamic overall = average over post-treatment event times (k >= 0)
    post_dyn_idx = [i for i, ek in enumerate(dyn_e_list) if ek >= 0]
    if post_dyn_idx:
        atts = np.array([dyn_att_list[i] for i in post_dyn_idx])
        ses = np.array([dyn_se_list[i] for i in post_dyn_idx])
        out["att_dyn"] = float(np.mean(atts))
        out["att_dyn_se"] = float(np.sqrt(np.mean(ses ** 2)))
    else:
        out["att_dyn"] = np.nan
        out["att_dyn_se"] = np.nan
    return out


def run_sun_abraham(panel, yname):
    """Approximate Sun-Abraham IW via event-time dummies in cohort-saturated FE."""
    import pyfixest as pf

    df = panel.dropna(subset=[yname, "epvr_first_year_p"]).copy()
    df["cohort"] = df["epvr_first_year_p"].astype(int)
    df["event_time"] = df["year"] - df["cohort"]
    df["et"] = df["event_time"].clip(-5, 5).astype(int)

    def k_name(k):
        return f"kpre{abs(k)}" if k < 0 else f"kpost{k}"

    ks = sorted(df["et"].unique())
    for k in ks:
        if k == -1:
            continue
        df[k_name(k)] = (df["et"] == k).astype(int)

    rhs_terms = [k_name(k) for k in ks if k != -1]
    formula = f"{yname} ~ " + " + ".join(rhs_terms) + " | province_code + year"
    try:
        fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
        tidy = fit.tidy()
    except Exception as e:
        return {"error": str(e)}

    rows = [{"method": "sun_abraham_iw_proxy", "outcome": yname, "k": -1,
              "coef": 0.0, "se": 0.0, "note": "reference"}]
    for k in ks:
        if k == -1:
            continue
        key = k_name(k)
        if key in tidy.index:
            r = tidy.loc[key]
            rows.append({
                "method": "sun_abraham_iw_proxy", "outcome": yname, "k": int(k),
                "coef": float(r["Estimate"]), "se": float(r["Std. Error"]),
                "note": "",
            })
    return {"dynamic": rows, "n": int(fit._N)}


def main():
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    log = ["=== D6: Staggered DID (Callaway-Sant'Anna + Sun-Abraham IW proxy) ===", ""]
    outcomes = ["log_rural_disposable_income", "log_urban_disposable_income",
                "urban_rural_income_ratio", "log_gdp"]

    cs_rows = []
    sa_rows = []
    for outcome in outcomes:
        log.append(f"\n--- Outcome: {outcome} ---")
        cs = run_csdid(panel, outcome)
        cs_rows.append(cs)
        log.append(f"CS simple ATT: {cs.get('att_simple', np.nan)} (SE {cs.get('att_simple_se', np.nan)})")
        log.append(f"CS dynamic overall ATT: {cs.get('att_dyn', np.nan)} (SE {cs.get('att_dyn_se', np.nan)})")
        log.append(f"CS group ATT: {cs.get('att_group', np.nan)} (SE {cs.get('att_group_se', np.nan)})")
        if cs.get("error"):
            log.append(f"CS error: {cs['error']}")

        sa = run_sun_abraham(panel, outcome)
        if "error" not in sa:
            sa_rows.extend(sa["dynamic"])
            log.append(f"Sun-Abraham IW proxy: N={sa['n']}")
        else:
            log.append(f"Sun-Abraham error: {sa['error']}")

    cs_df_data = []
    for r in cs_rows:
        cs_df_data.append({
            "outcome": r["outcome"],
            "att_simple": round(r.get("att_simple", np.nan), 4) if r.get("att_simple") is not None and not pd.isna(r.get("att_simple")) else np.nan,
            "att_simple_se": round(r.get("att_simple_se", np.nan), 4) if r.get("att_simple_se") is not None and not pd.isna(r.get("att_simple_se")) else np.nan,
            "att_dyn_overall": round(r.get("att_dyn", np.nan), 4) if r.get("att_dyn") is not None and not pd.isna(r.get("att_dyn")) else np.nan,
            "att_dyn_overall_se": round(r.get("att_dyn_se", np.nan), 4) if r.get("att_dyn_se") is not None and not pd.isna(r.get("att_dyn_se")) else np.nan,
            "att_group_overall": round(r.get("att_group", np.nan), 4) if r.get("att_group") is not None and not pd.isna(r.get("att_group")) else np.nan,
            "att_group_overall_se": round(r.get("att_group_se", np.nan), 4) if r.get("att_group_se") is not None and not pd.isna(r.get("att_group_se")) else np.nan,
            "error": r.get("error", ""),
        })
    cs_df = pd.DataFrame(cs_df_data)
    cs_df.to_csv(TAB / "table4b_staggered_did.csv", index=False)

    if sa_rows:
        sa_df = pd.DataFrame(sa_rows)
        sa_df["coef"] = sa_df["coef"].round(4)
        sa_df["se"] = sa_df["se"].round(4)
        sa_df.to_csv(TAB / "table4b_sun_abraham_dynamic.csv", index=False)

    head = cs_rows[0]
    if head.get("dyn_e"):
        dyn_df = pd.DataFrame({
            "k": head["dyn_e"],
            "att": [round(x, 4) for x in head["dyn_att"]],
            "se": [round(x, 4) for x in head["dyn_se"]],
        })
        dyn_df.to_csv(TAB / "table4b_cs_dynamic_rural.csv", index=False)

    log.append(f"\nWrote {TAB / 'table4b_staggered_did.csv'}")
    (LOG / "d6.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
