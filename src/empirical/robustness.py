"""
Phase D — D8 + D9: Spatial spillover & robustness battery.

Outputs:
- analysis/tables/table6_robustness.csv (combined battery)
- analysis/logs/d8.log, d9.log
"""
import json
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


def fit_did(df, outcome, formula_extra="", term="epvr_active_pt"):
    parts = [term] if not formula_extra else [term, formula_extra]
    rhs = " + ".join(parts)
    formula = f"{outcome} ~ {rhs} | province_code + year"
    df2 = df.dropna(subset=[outcome]).copy()
    if df2["epvr_active_pt"].nunique() < 2 or len(df2) < 20:
        return None
    try:
        fit = pf.feols(formula, data=df2, vcov={"CRV1": "province_code"})
        return fit
    except Exception as e:
        return {"error": str(e)[:100]}


def extract(fit, term, outcome, label):
    if fit is None:
        return {"check": label, "outcome": outcome, "beta": np.nan, "se": np.nan,
                "p": np.nan, "n": 0, "note": "no_fit"}
    if isinstance(fit, dict):
        return {"check": label, "outcome": outcome, "beta": np.nan, "se": np.nan,
                "p": np.nan, "n": 0, "note": fit.get("error", "")}
    tidy = fit.tidy()
    if term not in tidy.index:
        return {"check": label, "outcome": outcome, "beta": np.nan, "se": np.nan,
                "p": np.nan, "n": int(fit._N), "note": "term_absent"}
    r = tidy.loc[term]
    return {"check": label, "outcome": outcome,
            "beta": round(float(r["Estimate"]), 4),
            "se": round(float(r["Std. Error"]), 4),
            "p": round(float(r["Pr(>|t|)"]), 4),
            "n": int(fit._N), "note": ""}


def main():
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    cases = pd.read_csv(ROOT / "data" / "processed" / "cases_bsi.csv")
    neighbors = json.loads((OUT / "neighbors_provinces.json").read_text())
    log8 = ["=== D8: Spatial spillover ===", ""]
    log9 = ["=== D9: Robustness battery ===", ""]

    rows = []
    outcomes = ["log_rural_disposable_income", "log_urban_disposable_income",
                 "urban_rural_income_ratio", "log_gdp"]

    # ------------- D8: spatial spillover -------------
    # Compute neighbor_epvr_pt = fraction of adjacent provinces with epvr_active=1
    nbr_rows = []
    for _, row in panel.iterrows():
        p = int(row["province_code"])
        y = int(row["year"])
        nbrs = neighbors.get(str(p), [])
        if not nbrs:
            nbr_rows.append(np.nan)
            continue
        sub = panel[(panel["province_code"].isin(nbrs)) & (panel["year"] == y)]
        if len(sub) == 0:
            nbr_rows.append(np.nan)
            continue
        nbr_rows.append(float(sub["epvr_active_pt"].mean()))
    panel["neighbor_epvr_pt"] = nbr_rows
    panel["neighbor_epvr_high"] = (panel["neighbor_epvr_pt"] > 0.5).astype(int)

    for outcome in outcomes:
        fit_no = fit_did(panel, outcome)
        fit_sp = fit_did(panel, outcome, formula_extra="neighbor_epvr_pt")
        r1 = extract(fit_no, "epvr_active_pt", outcome, "spatial_baseline_no_neighbor")
        r2 = extract(fit_sp, "epvr_active_pt", outcome, "spatial_with_neighbor")
        r3 = extract(fit_sp, "neighbor_epvr_pt", outcome, "spatial_neighbor_coef")
        rows.extend([r1, r2, r3])
        log8.append(f"{outcome:40s} baseline β={r1['beta']:>7} | +neighbor β={r2['beta']:>7} (nbr coef {r3['beta']:>7})")

    log8.append(f"\nneighbor_epvr_pt range: {panel['neighbor_epvr_pt'].min():.3f} – {panel['neighbor_epvr_pt'].max():.3f}")

    # ------------- D9: robustness -------------
    # (a) Drop heavily-treated provinces (highest case counts: Fujian 27, Zhejiang 14, Yunnan 14)
    drop_provs = {35, 33, 53}
    pan_drop = panel[~panel["province_code"].isin(drop_provs)].copy()
    for outcome in outcomes:
        fit = fit_did(pan_drop, outcome)
        rows.append(extract(fit, "epvr_active_pt", outcome,
                             "drop_heavily_treated_provinces"))
    log9.append("Dropped: 35-福建, 33-浙江, 53-云南")

    # (b) Placebo year (set treatment 3 years earlier than actual; for never-treated leave 0)
    pan_placebo = panel.copy()
    pan_placebo["epvr_first_year_p_placebo"] = pan_placebo["epvr_first_year_p"] - 3
    pan_placebo["epvr_active_placebo"] = ((pan_placebo["year"] >= pan_placebo["epvr_first_year_p_placebo"])
                                            & (pan_placebo["epvr_first_year_p_placebo"].notna())).astype(int)
    for outcome in outcomes:
        df = pan_placebo.dropna(subset=[outcome]).copy()
        formula = f"{outcome} ~ epvr_active_placebo | province_code + year"
        try:
            fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
            tidy = fit.tidy()
            r = tidy.loc["epvr_active_placebo"]
            rows.append({"check": "placebo_year_minus3", "outcome": outcome,
                         "beta": round(float(r["Estimate"]), 4),
                         "se": round(float(r["Std. Error"]), 4),
                         "p": round(float(r["Pr(>|t|)"]), 4),
                         "n": int(fit._N), "note": ""})
        except Exception as e:
            rows.append({"check": "placebo_year_minus3", "outcome": outcome,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "n": 0,
                         "note": str(e)[:80]})

    # (c) Double cluster province × year
    for outcome in outcomes:
        df = panel.dropna(subset=[outcome]).copy()
        formula = f"{outcome} ~ epvr_active_pt | province_code + year"
        try:
            fit = pf.feols(formula, data=df,
                           vcov={"CRV1": "province_code+year"})
            tidy = fit.tidy()
            r = tidy.loc["epvr_active_pt"]
            rows.append({"check": "double_cluster_province_year", "outcome": outcome,
                         "beta": round(float(r["Estimate"]), 4),
                         "se": round(float(r["Std. Error"]), 4),
                         "p": round(float(r["Pr(>|t|)"]), 4),
                         "n": int(fit._N), "note": ""})
        except Exception as e:
            # pyfixest may use different syntax
            rows.append({"check": "double_cluster_province_year", "outcome": outcome,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "n": 0,
                         "note": str(e)[:80]})

    # (d) BSI heterogeneity using only human-verified cases
    cases_hv = cases[cases["final_confidence"] == "human_verified"].copy()
    cases_hv = cases_hv[cases_hv["province_code"].astype(str) != "NA_UNRESOLVED"].copy()
    cases_hv["province_code"] = cases_hv["province_code"].astype(int)
    bsi_hv = cases_hv.groupby("province_code")["BSI_net"].mean()
    med_hv = bsi_hv.median() if len(bsi_hv) > 0 else 0
    bsi_high_hv = (bsi_hv > med_hv).astype(int).to_dict()
    pan_hv = panel.copy()
    pan_hv["bsi_high_p_hv"] = pan_hv["province_code"].map(bsi_high_hv).fillna(0).astype(int)
    pan_hv["epvr_x_bsi_high_hv"] = pan_hv["epvr_active_pt"] * pan_hv["bsi_high_p_hv"]
    for outcome in outcomes:
        df = pan_hv.dropna(subset=[outcome]).copy()
        formula = f"{outcome} ~ epvr_active_pt + epvr_x_bsi_high_hv | province_code + year"
        try:
            fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
            tidy = fit.tidy()
            r = tidy.loc["epvr_x_bsi_high_hv"]
            rows.append({"check": "bsi_hv_only_interaction", "outcome": outcome,
                         "beta": round(float(r["Estimate"]), 4),
                         "se": round(float(r["Std. Error"]), 4),
                         "p": round(float(r["Pr(>|t|)"]), 4),
                         "n": int(fit._N), "note": "term=epvr_x_bsi_high_hv"})
        except Exception as e:
            rows.append({"check": "bsi_hv_only_interaction", "outcome": outcome,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "n": 0,
                         "note": str(e)[:80]})

    # (e) BSI_raw (no capture risk subtraction)
    cases_a = cases[cases["province_code"].astype(str) != "NA_UNRESOLVED"].copy()
    cases_a["province_code"] = cases_a["province_code"].astype(int)
    bsi_raw = cases_a.groupby("province_code")["BSI_raw"].mean()
    med_raw = bsi_raw.median()
    bsi_high_raw = (bsi_raw > med_raw).astype(int).to_dict()
    pan_raw = panel.copy()
    pan_raw["bsi_high_p_raw"] = pan_raw["province_code"].map(bsi_high_raw).fillna(0).astype(int)
    pan_raw["epvr_x_bsi_high_raw"] = pan_raw["epvr_active_pt"] * pan_raw["bsi_high_p_raw"]
    for outcome in outcomes:
        df = pan_raw.dropna(subset=[outcome]).copy()
        formula = f"{outcome} ~ epvr_active_pt + epvr_x_bsi_high_raw | province_code + year"
        try:
            fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
            tidy = fit.tidy()
            r = tidy.loc["epvr_x_bsi_high_raw"]
            rows.append({"check": "bsi_raw_interaction", "outcome": outcome,
                         "beta": round(float(r["Estimate"]), 4),
                         "se": round(float(r["Std. Error"]), 4),
                         "p": round(float(r["Pr(>|t|)"]), 4),
                         "n": int(fit._N), "note": "term=epvr_x_bsi_high_raw"})
        except Exception as e:
            rows.append({"check": "bsi_raw_interaction", "outcome": outcome,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "n": 0,
                         "note": str(e)[:80]})

    df_out = pd.DataFrame(rows)
    df_out.to_csv(TAB / "table6_robustness.csv", index=False)
    log9.append(f"Wrote {TAB / 'table6_robustness.csv'} with {len(df_out)} rows")
    (LOG / "d8.log").write_text("\n".join(log8) + "\n")
    (LOG / "d9.log").write_text("\n".join(log9) + "\n")
    print("\n".join(log8))
    print()
    print("\n".join(log9))
    print()
    print("=== Robustness results (head) ===")
    print(df_out.to_string(index=False))


if __name__ == "__main__":
    main()
