"""
Phase D v3 — LUP reviewer rerun.

M2: Wild-cluster bootstrap p-values for Table 3b (capture-risk β3 across 4 outcomes × 2 specs).
M3: Leave-one-province-out (LOPO) over the 4 capture-risk-high provinces for Table 3b fe_controls.
M6: Treatment-timing sensitivity for Callaway-Sant'Anna staggered DID (shifts -2..+2).

Outputs:
    analysis/tables/table3b_capture_risk.csv        (with wild_cluster_p column appended)
    analysis/tables/table8_lopo_capture_risk.csv
    analysis/tables/table9_timing_sensitivity.csv
    analysis/logs/m2_wildboot.log
    analysis/logs/m3_lopo.log
    analysis/logs/m6_timing.log
"""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import pyfixest as pf

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis"
TAB = OUT / "tables"
LOG = OUT / "logs"
TAB.mkdir(parents=True, exist_ok=True)
LOG.mkdir(parents=True, exist_ok=True)

OUTCOMES_T3B = [
    "log_rural_disposable_income",
    "log_urban_disposable_income",
    "urban_rural_income_ratio",
    "log_gdp",
]

CAPTURE_RISK_HIGH = {35: "Fujian", 42: "Hubei", 44: "Guangdong", 53: "Yunnan"}

WCB_REPS = 1999  # > 999 as required


def controls_for(outcome):
    base = ["log_population_lag"]
    if outcome in ("log_gdp", "log_primary_industry_value_added"):
        return base
    return base + ["log_primary_share"]


def fit_t3b(panel, outcome, spec):
    """Estimate Table 3b model: Y ~ epvr + epvr*bsi_high + epvr*cr_high + (controls) | p+t FE."""
    df = panel.copy()
    df["epvr_x_bsi_high"] = df["epvr_active_pt"] * df["bsi_high_p"]
    df["epvr_x_cr_high"] = df["epvr_active_pt"] * df["capture_risk_high_p"]
    parts = ["epvr_active_pt", "epvr_x_bsi_high", "epvr_x_cr_high"]
    if spec == "fe_controls":
        ctrls = controls_for(outcome)
        parts.extend(ctrls)
        needed = [outcome] + ctrls
    else:
        needed = [outcome]
    df = df.dropna(subset=needed)
    if len(df) < 20 or df["epvr_active_pt"].nunique() < 2:
        return None, df
    formula = f"{outcome} ~ {' + '.join(parts)} | province_code + year"
    try:
        fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
    except Exception as e:
        return {"error": str(e)}, df
    return fit, df


def extract_p(wb):
    """Pull p-value out of pyfixest wildboottest return (Series-like)."""
    if wb is None:
        return np.nan
    # pyfixest returns a pandas Series with index like 'Pr(>|t|)' typically
    try:
        if hasattr(wb, "index"):
            for k in ["Pr(>|t|)", "p_value", "P-value", "Pr(>t)", "Pr(>|z|)"]:
                if k in wb.index:
                    return float(wb[k])
            # Fall back: scan for any value that looks like a p
            for v in wb.values:
                try:
                    fv = float(v)
                    if 0 <= fv <= 1:
                        return fv
                except Exception:
                    continue
        return float(wb)
    except Exception:
        return np.nan


def wild_p(fit, term, reps=WCB_REPS, seed=42):
    if fit is None or isinstance(fit, dict):
        return np.nan
    try:
        wb = fit.wildboottest(param=term, reps=reps, seed=seed)
        return extract_p(wb)
    except Exception:
        return np.nan


def beta_se_p(fit, term):
    if fit is None or isinstance(fit, dict):
        return (np.nan, np.nan, np.nan, np.nan)
    t = fit.tidy()
    if term not in t.index:
        return (np.nan, np.nan, np.nan, int(fit._N))
    r = t.loc[term]
    return (float(r["Estimate"]), float(r["Std. Error"]),
            float(r["Pr(>|t|)"]), int(fit._N))


# ---------------------------------------------------------------------------
# M2: Wild bootstrap for Table 3b
# ---------------------------------------------------------------------------
def m2(panel):
    log = [f"=== M2: Wild-cluster bootstrap for Table 3b (Rademacher, B={WCB_REPS}) ===",
           f"capture-risk-high set: {CAPTURE_RISK_HIGH}", ""]
    print(log[0])
    results = {}  # (outcome, spec, term) -> wild_p
    for outcome in OUTCOMES_T3B:
        for spec in ["fe_only", "fe_controls"]:
            fit, df = fit_t3b(panel, outcome, spec)
            if fit is None or isinstance(fit, dict):
                log.append(f"  {outcome:38s} {spec:13s}  FIT FAILED")
                continue
            n = int(fit._N)
            for term in ["epvr_active_pt", "epvr_x_bsi_high", "epvr_x_cr_high"]:
                p = wild_p(fit, term)
                results[(outcome, spec, term)] = p
                b, se, pv, _ = beta_se_p(fit, term)
                log.append(f"  {outcome:38s} {spec:13s} {term:18s} "
                           f"β={b:>8.4f} se={se:>7.4f} cl_p={pv:>6.4f} wild_p={p:>6.4f} n={n}")
            log.append("")
    # Merge wild_cluster_p into the existing table3b CSV
    src = TAB / "table3b_capture_risk.csv"
    tab = pd.read_csv(src)
    tab["wild_cluster_p"] = np.nan
    # column mapping: term in CSV matches what we used
    for i, row in tab.iterrows():
        key = (row["outcome"], row["spec"], row["term"])
        if key in results:
            p = results[key]
            tab.at[i, "wild_cluster_p"] = round(p, 4) if not (p is None or (isinstance(p, float) and np.isnan(p))) else np.nan
    tab.to_csv(src, index=False)
    log.append(f"\nWrote wild_cluster_p column → {src}")
    (LOG / "m2_wildboot.log").write_text("\n".join(log) + "\n")
    return results


# ---------------------------------------------------------------------------
# M3: Leave-one-province-out for capture-risk β3
# ---------------------------------------------------------------------------
def m3(panel):
    log = [f"=== M3: LOPO for Table 3b fe_controls (β3 on epvr × cr_high) ===",
           f"capture-risk-high provinces: {CAPTURE_RISK_HIGH}", ""]
    print(log[0])

    # Full-sample β3 reference for the three reportable outcomes
    full = {}
    for outcome in ["log_rural_disposable_income", "urban_rural_income_ratio", "log_gdp"]:
        fit, _ = fit_t3b(panel, outcome, "fe_controls")
        b, se, pv, n = beta_se_p(fit, "epvr_x_cr_high")
        wp = wild_p(fit, "epvr_x_cr_high")
        full[outcome] = {"beta": b, "se": se, "p": pv, "wild_p": wp, "n": n}
        log.append(f"  FULL {outcome:38s} β3={b:.4f} se={se:.4f} cl_p={pv:.4f} wild_p={wp:.4f} n={n}")
    log.append("")

    rows = []
    for prov_code, prov_name in CAPTURE_RISK_HIGH.items():
        sub = panel[panel["province_code"] != prov_code].copy()
        # Recompute the capture-risk-high median split after dropping the province,
        # matching build_provincial_panel.py: median over treated provinces with
        # non-missing capture_risk_mean_p, then flag > median. This implements the
        # reviewer request to remove the province from the high-flag computation.
        cr_by_p = sub[["province_code", "capture_risk_mean_p"]].drop_duplicates()
        med_cr = cr_by_p["capture_risk_mean_p"].median()
        cr_flag = (cr_by_p.set_index("province_code")["capture_risk_mean_p"] > med_cr).astype(int)
        sub["capture_risk_high_p"] = sub["province_code"].map(cr_flag).fillna(0).astype(int)
        remaining_high = sorted(sub.loc[sub["capture_risk_high_p"] == 1, "province_code"].dropna().unique().astype(int).tolist())
        log.append(f"  drop {prov_code} {prov_name}: recomputed capture median={med_cr:.6f}; remaining high={remaining_high}")
        for outcome in ["log_rural_disposable_income", "urban_rural_income_ratio", "log_gdp"]:
            fit, _ = fit_t3b(sub, outcome, "fe_controls")
            b, se, pv, n = beta_se_p(fit, "epvr_x_cr_high")
            wp = wild_p(fit, "epvr_x_cr_high")
            f = full[outcome]
            if not np.isnan(b) and not np.isnan(f["beta"]) and abs(f["beta"]) > 1e-6:
                rel = abs(b - f["beta"]) / abs(f["beta"])
                flag = "robust" if rel < 0.50 else "fragile"
            else:
                rel = np.nan
                flag = "fragile" if np.isnan(b) else "robust"
            # If sign flipped from full sample, override to fragile
            if not np.isnan(b) and not np.isnan(f["beta"]) and np.sign(b) != np.sign(f["beta"]):
                flag = "fragile_signflip"
            label = f"{prov_code} {prov_name}"
            rows.append({
                "dropped_province": label,
                "outcome": outcome,
                "beta_3": round(b, 4) if not np.isnan(b) else np.nan,
                "se": round(se, 4) if not np.isnan(se) else np.nan,
                "cluster_p": round(pv, 4) if not np.isnan(pv) else np.nan,
                "wild_p": round(wp, 4) if not (wp is None or np.isnan(wp)) else np.nan,
                "n": n if not (isinstance(n, float) and np.isnan(n)) else np.nan,
                "full_beta_3": round(f["beta"], 4),
                "rel_change": round(rel, 3) if not np.isnan(rel) else np.nan,
                "interpretation_flag": flag,
            })
            log.append(f"  drop {label:14s} {outcome:38s} β3={b:.4f} (Δrel={rel if not np.isnan(rel) else float('nan'):.2f}) "
                       f"se={se:.4f} cl_p={pv:.4f} wild_p={wp:.4f} n={n} [{flag}]")

    out_csv = TAB / "table8_lopo_capture_risk.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    log.append(f"\nWrote {out_csv}")
    (LOG / "m3_lopo.log").write_text("\n".join(log) + "\n")
    return rows, full


# ---------------------------------------------------------------------------
# M6: Treatment-timing sensitivity for CS staggered DID
# ---------------------------------------------------------------------------
def run_csdid_simple(panel, yname, shift=0):
    """Return dict with simple ATT, dyn ATT, and SEs after shifting g by `shift` years."""
    from csdid.att_gt import ATTgt

    df = panel.dropna(subset=[yname]).copy()
    g_orig = df["epvr_first_year_p"].fillna(0).astype(int)
    g_shifted = g_orig.copy()
    treated_mask = g_orig > 0
    g_shifted.loc[treated_mask] = (g_orig.loc[treated_mask] + shift).astype(int)
    tmax = int(df["year"].max())
    # Match staggered_did.py for shift=0: only cohorts after the observed panel are
    # reset to never-treated. Cohorts before the first observed year are left as-is;
    # csdid then drops units already treated in the first period, which is the v2
    # behavior and is important for reproducing table4b.
    g_shifted.loc[g_shifted > tmax] = 0
    df["gname"] = g_shifted
    df["province_code"] = df["province_code"].astype(int)
    df = df[["province_code", "year", "gname", yname]].copy()

    out = {"outcome": yname, "shift": shift}
    try:
        att = ATTgt(
            yname=yname, tname="year", idname="province_code", gname="gname",
            data=df, panel=True, allow_unbalanced_panel=True,
            control_group="nevertreated", anticipation=0,
        )
        att.fit(est_method="reg", bstrap=False)
    except Exception as e:
        out["error"] = str(e)
        return out

    mp = att.MP
    g = np.array(mp["group"])
    t = np.array(mp["t"])
    a = np.array(mp["att"], dtype=float)
    inff_obj = mp["inffunc"]
    inff = np.array(inff_obj["inffunc"]) if isinstance(inff_obj, dict) else np.array(inff_obj)
    n_units = mp["n"]

    # Match src/empirical/staggered_did.py exactly for the simple ATT:
    # post-treatment group-time ATTs are selected by t >= g and finite values.
    # Do not add an extra g > 0 filter here, or shift=0 no longer reproduces
    # the published v2 table4b simple ATT.
    post_mask = (t >= g) & np.isfinite(a)
    a_post = a[post_mask]
    if_post = inff[:, post_mask]
    if len(a_post) > 0:
        w = np.ones(len(a_post)) / len(a_post)
        out["atts_simple"] = float(np.dot(w, a_post))
        out["atts_se"] = float(np.sqrt(np.var(if_post @ w, ddof=0) / n_units))
    else:
        out["atts_simple"] = np.nan
        out["atts_se"] = np.nan

    e = t - g
    dyn_mask = (g > 0) & (e >= 0) & (e <= 5) & np.isfinite(a)
    a_dyn = a[dyn_mask]
    if_dyn = inff[:, dyn_mask]
    if len(a_dyn) > 0:
        w = np.ones(len(a_dyn)) / len(a_dyn)
        out["atts_dynamic"] = float(np.dot(w, a_dyn))
        out["atts_dynamic_se"] = float(np.sqrt(np.var(if_dyn @ w, ddof=0) / n_units))
    else:
        out["atts_dynamic"] = np.nan
        out["atts_dynamic_se"] = np.nan
    return out


def m6(panel):
    log = ["=== M6: CS staggered DID treatment-timing sensitivity ===", ""]
    print(log[0])
    outcomes = ["log_rural_disposable_income", "urban_rural_income_ratio", "log_gdp"]
    shifts = [-2, -1, 0, 1, 2]

    # First: base (shift=0) results to compute robust_flag
    base = {}
    rows = []
    for outcome in outcomes:
        r0 = run_csdid_simple(panel, outcome, shift=0)
        base[outcome] = r0
        log.append(f"  BASE shift=0 {outcome:38s} ATTs={r0.get('atts_simple', np.nan):.4f} "
                   f"se={r0.get('atts_se', np.nan):.4f} "
                   f"ATTd={r0.get('atts_dynamic', np.nan):.4f} "
                   f"se={r0.get('atts_dynamic_se', np.nan):.4f}")
    log.append("")

    for shift in shifts:
        for outcome in outcomes:
            r = run_csdid_simple(panel, outcome, shift=shift)
            atts = r.get("atts_simple", np.nan)
            atts_se = r.get("atts_se", np.nan)
            attd = r.get("atts_dynamic", np.nan)
            attd_se = r.get("atts_dynamic_se", np.nan)

            base_r = base[outcome]
            base_atts = base_r.get("atts_simple", np.nan)
            base_se = base_r.get("atts_se", np.nan)
            if not (np.isnan(atts) or np.isnan(base_atts) or np.isnan(base_se)) and base_se > 0:
                z = abs(atts - base_atts) / base_se
                robust_flag = "stable" if z < 1.5 else "fragile"
            else:
                z = np.nan
                robust_flag = "missing" if np.isnan(atts) else "stable"

            rows.append({
                "shift_years": shift,
                "outcome": outcome,
                "atts_simple": round(atts, 4) if not np.isnan(atts) else np.nan,
                "atts_se": round(atts_se, 4) if not np.isnan(atts_se) else np.nan,
                "atts_dynamic": round(attd, 4) if not np.isnan(attd) else np.nan,
                "atts_dynamic_se": round(attd_se, 4) if not np.isnan(attd_se) else np.nan,
                "base_atts": round(base_atts, 4) if not np.isnan(base_atts) else np.nan,
                "z_vs_base": round(z, 2) if not np.isnan(z) else np.nan,
                "robust_flag": robust_flag,
                "error": r.get("error", ""),
            })
            log.append(f"  shift={shift:+d} {outcome:38s} ATTs={atts:.4f} se={atts_se:.4f} "
                       f"ATTd={attd:.4f} se={attd_se:.4f} z={z if not np.isnan(z) else float('nan'):.2f} [{robust_flag}]"
                       + (f"  ERR={r['error']}" if r.get('error') else ""))
        log.append("")

    out_csv = TAB / "table9_timing_sensitivity.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    log.append(f"Wrote {out_csv}")
    (LOG / "m6_timing.log").write_text("\n".join(log) + "\n")
    return rows


if __name__ == "__main__":
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    print(f"Panel: {len(panel)} rows, {panel['province_code'].nunique()} provinces")
    print()
    m2_res = m2(panel)
    print()
    m3_res = m3(panel)
    print()
    m6_res = m6(panel)
    print()
    print("DONE.")
