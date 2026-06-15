"""
Phase D — D2/D3/D4: Main DID, BSI heterogeneity, capture risk.

Province-year level (no county within-province variation — county_panel
values are provincial averages propagated to counties).

Specifications:
  D2:  Y_pt = a + b1*epvr_active + X + mu_p + lambda_t + e
  D3:  Y_pt = a + b1*epvr + b2*epvr*bsi_high_p + X + mu_p + lambda_t + e
  D4:  Y_pt = a + b1*epvr + b2*epvr*bsi_high_p + b3*epvr*capture_risk_high_p + X + mu_p + lambda_t + e

Standard errors clustered at province (26 clusters). Wild cluster bootstrap
p-values reported as robustness.
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

OUTCOMES = [
    "log_rural_disposable_income",
    "log_urban_disposable_income",
    "urban_rural_income_ratio",
    "log_gdp",
    "log_primary_industry_value_added",
]

# Outcome-specific controls to avoid mechanical collinearity:
#   - for log_gdp and log_primary_industry_value_added do NOT include
#     log_primary_share (which is log(primary_VA) - log(gdp))
#   - log_population_lag is always used when available
def controls_for(outcome):
    base = ["log_population_lag"]
    if outcome in ("log_gdp", "log_primary_industry_value_added"):
        return base
    return base + ["log_primary_share"]


def run_did(panel, outcome, formula_extra="", controls=None, drop_controls=False):
    """Estimate via pyfixest feols. Returns fit or None."""
    if controls is None:
        controls = controls_for(outcome)
    if drop_controls:
        controls = []
    parts = ["epvr_active_pt"]
    if formula_extra:
        parts.append(formula_extra)
    parts.extend(controls)
    rhs = " + ".join(parts)
    formula = f"{outcome} ~ {rhs} | province_code + year"
    needed = [outcome] + controls
    df = panel.dropna(subset=needed).copy()
    if df["epvr_active_pt"].nunique() < 2 or len(df) < 20:
        return None
    try:
        fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
    except Exception as e:
        return {"error": str(e), "n": len(df)}
    return fit


def coef_row(fit, key, outcome, spec):
    if fit is None or isinstance(fit, dict):
        return {"outcome": outcome, "spec": spec, "term": key, "coef": np.nan,
                "se": np.nan, "t": np.nan, "p": np.nan, "n": np.nan,
                "ci_lo": np.nan, "ci_hi": np.nan, "error": fit.get("error") if isinstance(fit, dict) else "no_fit"}
    tidy = fit.tidy()
    if key not in tidy.index:
        return {"outcome": outcome, "spec": spec, "term": key, "coef": np.nan,
                "se": np.nan, "t": np.nan, "p": np.nan, "n": int(fit._N),
                "ci_lo": np.nan, "ci_hi": np.nan, "error": "term_absent"}
    row = tidy.loc[key]
    return {
        "outcome": outcome, "spec": spec, "term": key,
        "coef": round(float(row["Estimate"]), 4),
        "se": round(float(row["Std. Error"]), 4),
        "t": round(float(row["t value"]), 3),
        "p": round(float(row["Pr(>|t|)"]), 4),
        "n": int(fit._N),
        "ci_lo": round(float(row["2.5%"]), 4),
        "ci_hi": round(float(row["97.5%"]), 4),
        "error": "",
    }


def wild_cluster_p(panel, outcome, term, formula_extra="", controls=None, reps=999, seed=42):
    if controls is None:
        controls = controls_for(outcome)
    parts = ["epvr_active_pt"]
    if formula_extra:
        parts.append(formula_extra)
    parts.extend(controls)
    rhs = " + ".join(parts)
    formula = f"{outcome} ~ {rhs} | province_code + year"
    df = panel.dropna(subset=[outcome] + controls).copy()
    if len(df) < 20:
        return np.nan
    try:
        fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
        wb = fit.wildboottest(param=term, reps=reps, seed=seed)
        if hasattr(wb, "get"):
            for k in ["Pr(>|t|)", "p_value", "P-value"]:
                if k in wb.index:
                    return float(wb[k])
        return float(wb)
    except Exception as e:
        return np.nan


def main_d2(panel):
    rows = []
    log = ["=== D2: Main DID (province-year) ===",
           f"Panel rows: {len(panel)}",
           f"Treated rows (epvr_active_pt=1): {(panel['epvr_active_pt']==1).sum()}",
           f"Provinces: {panel['province_code'].nunique()}",
           ""]
    log.append(f"{'outcome':40s} {'spec':15s} {'beta':>8} {'se':>7} {'p':>7} {'wcb_p':>7} {'n':>4}")
    for outcome in OUTCOMES:
        for spec_name, dc in [("fe_only", True), ("fe_controls", False)]:
            fit = run_did(panel, outcome, drop_controls=dc)
            row = coef_row(fit, "epvr_active_pt", outcome, spec_name)
            # Wild cluster bootstrap p with same control set
            ctrls = [] if dc else controls_for(outcome)
            wcb_p = wild_cluster_p(panel, outcome, "epvr_active_pt", controls=ctrls)
            row["wild_cluster_p"] = round(wcb_p, 4) if not np.isnan(wcb_p) else np.nan
            rows.append(row)
            log.append(f"{outcome:40s} {spec_name:15s} {str(row['coef']):>8} {str(row['se']):>7} {str(row['p']):>7} {str(row['wild_cluster_p']):>7} {row['n']:>4}")
    df = pd.DataFrame(rows)
    df.to_csv(TAB / "table2_main_did.csv", index=False)
    log.append(f"\nWrote {TAB / 'table2_main_did.csv'}")
    (LOG / "d2.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))
    return df


def main_d3(panel):
    rows = []
    log = ["=== D3: BSI heterogeneity (epvr × bsi_high) ===", ""]
    panel = panel.copy()
    panel["epvr_x_bsi_high"] = panel["epvr_active_pt"] * panel["bsi_high_p"]
    log.append(f"{'outcome':40s} {'spec':15s} {'b2':>8} {'se':>7} {'p':>7} {'wcb_p':>7} {'n':>4}")
    for outcome in OUTCOMES:
        for spec_name, dc in [("fe_only", True), ("fe_controls", False)]:
            fit = run_did(panel, outcome, formula_extra="epvr_x_bsi_high", drop_controls=dc)
            for term, label in [("epvr_active_pt", "b1"), ("epvr_x_bsi_high", "b2_bsi_high")]:
                r = coef_row(fit, term, outcome, spec_name)
                r["label"] = label
                rows.append(r)
            # bootstrap for the interaction
            ctrls = [] if dc else controls_for(outcome)
            wcb_p = wild_cluster_p(panel, outcome, "epvr_x_bsi_high",
                                    formula_extra="epvr_x_bsi_high", controls=ctrls)
            rows[-1]["wild_cluster_p"] = round(wcb_p, 4) if not np.isnan(wcb_p) else np.nan
            log.append(f"{outcome:40s} {spec_name:15s} {str(rows[-1]['coef']):>8} {str(rows[-1]['se']):>7} {str(rows[-1]['p']):>7} {str(rows[-1]['wild_cluster_p']):>7} {rows[-1]['n']:>4}")
    df = pd.DataFrame(rows)
    df.to_csv(TAB / "table3_bsi_heterogeneity.csv", index=False)
    log.append(f"\nWrote {TAB / 'table3_bsi_heterogeneity.csv'}")
    (LOG / "d3.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))
    return df


def main_d4(panel):
    rows = []
    log = ["=== D4: Capture risk (epvr × bsi_high + epvr × capture_risk_high) ===", ""]
    panel = panel.copy()
    panel["epvr_x_bsi_high"] = panel["epvr_active_pt"] * panel["bsi_high_p"]
    panel["epvr_x_cr_high"] = panel["epvr_active_pt"] * panel["capture_risk_high_p"]
    log.append(f"{'outcome':40s} {'spec':15s} {'b3':>8} {'se':>7} {'p':>7} {'n':>4}")
    for outcome in OUTCOMES:
        for spec_name, dc in [("fe_only", True), ("fe_controls", False)]:
            fit = run_did(panel, outcome, formula_extra="epvr_x_bsi_high + epvr_x_cr_high",
                           drop_controls=dc)
            for term, label in [("epvr_active_pt", "b1"),
                                 ("epvr_x_bsi_high", "b2_bsi_high"),
                                 ("epvr_x_cr_high", "b3_cr_high")]:
                r = coef_row(fit, term, outcome, spec_name)
                r["label"] = label
                rows.append(r)
            log.append(f"{outcome:40s} {spec_name:15s} {str(rows[-1]['coef']):>8} {str(rows[-1]['se']):>7} {str(rows[-1]['p']):>7} {rows[-1]['n']:>4}")
    df = pd.DataFrame(rows)
    df.to_csv(TAB / "table3b_capture_risk.csv", index=False)
    log.append(f"\nWrote {TAB / 'table3b_capture_risk.csv'}")
    (LOG / "d4.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))
    return df


if __name__ == "__main__":
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    main_d2(panel)
    print()
    main_d3(panel)
    print()
    main_d4(panel)
