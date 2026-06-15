"""
Phase D — D7: PSM + DID and entropy balancing on province pre-treatment covariates.

For each treated province, compute propensity to be treated as a function of
pre-treatment rural income, GDP, primary-industry share. Match treated
provinces to nearest never-treated provinces; re-run DID on the matched
sample. Entropy balancing as robustness.

Output rows merged into analysis/tables/table6_robustness.csv (matching block).
"""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import pyfixest as pf
from sklearn.linear_model import LogisticRegression

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis"
TAB = OUT / "tables"
LOG = OUT / "logs"


def main():
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    log = ["=== D7: PSM-DID & entropy balancing ===", ""]

    # Build province-level pre-treatment covariates (mean over years 2015-2017,
    # treating as "pre" for most cohorts)
    pre = panel[panel["year"].between(2015, 2017)].copy()
    cov = pre.groupby("province_code").agg(
        rural_income_pre=("rural_disposable_income", "mean"),
        gdp_pre=("gdp", "mean"),
        primary_share_pre=("primary_share", "mean"),
    ).reset_index()

    # Determine treatment status: treated if first_year between 2018-2023 (so we
    # have at least 1 pre-treatment year in panel window)
    first_yr = panel.groupby("province_code")["epvr_first_year_p"].first().reset_index()
    cov = cov.merge(first_yr, on="province_code", how="left")
    cov["treated"] = ((cov["epvr_first_year_p"].notna()) &
                       (cov["epvr_first_year_p"] >= 2018) &
                       (cov["epvr_first_year_p"] <= 2023)).astype(int)
    # Never-treated control pool: provinces with no EPVR cases or first year > 2024
    cov["never"] = ((cov["epvr_first_year_p"].isna()) |
                     (cov["epvr_first_year_p"] >= 2024)).astype(int)

    # Drop provinces missing covariates
    cov_used = cov.dropna(subset=["rural_income_pre", "gdp_pre", "primary_share_pre"]).copy()
    log.append(f"Covariate provinces: {len(cov_used)} (treated={cov_used['treated'].sum()}, never={cov_used['never'].sum()})")

    if cov_used["treated"].sum() < 3 or cov_used["never"].sum() < 2:
        log.append("Too few provinces in treated/never groups; skipping PSM")
        (LOG / "d7.log").write_text("\n".join(log) + "\n")
        return

    # PSM via logistic regression
    X = cov_used[["rural_income_pre", "gdp_pre", "primary_share_pre"]].values
    y = cov_used["treated"].values
    # Standardize
    Xs = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-12)
    lr = LogisticRegression(penalty=None, max_iter=1000)
    try:
        lr.fit(Xs, y)
        cov_used["pscore"] = lr.predict_proba(Xs)[:, 1]
    except Exception as e:
        log.append(f"Logistic failed: {e}")
        cov_used["pscore"] = 0.5

    # 1:2 nearest-neighbor matching from never-treated pool
    treated = cov_used[cov_used["treated"] == 1].copy()
    controls = cov_used[cov_used["never"] == 1].copy()
    log.append(f"Treated provinces: {treated['province_code'].tolist()}")
    log.append(f"Control pool: {controls['province_code'].tolist()}")

    matched_provs = set(treated["province_code"].tolist())
    for _, trow in treated.iterrows():
        if controls.empty:
            break
        controls["dist"] = (controls["pscore"] - trow["pscore"]).abs()
        nearest = controls.nsmallest(2, "dist")
        for _, crow in nearest.iterrows():
            matched_provs.add(crow["province_code"])

    log.append(f"Matched sample size: {len(matched_provs)} provinces")

    # Re-run DID on matched sample
    pan_match = panel[panel["province_code"].isin(matched_provs)].copy()
    rows = []
    for outcome in ["log_rural_disposable_income", "log_urban_disposable_income",
                     "urban_rural_income_ratio", "log_gdp"]:
        df = pan_match.dropna(subset=[outcome]).copy()
        if df["epvr_active_pt"].nunique() < 2 or len(df) < 20:
            rows.append({"method": "psm_did", "outcome": outcome, "beta": np.nan,
                         "se": np.nan, "p": np.nan, "n": len(df), "note": "insufficient_variation"})
            continue
        formula = f"{outcome} ~ epvr_active_pt | province_code + year"
        try:
            fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
            tidy = fit.tidy()
            r = tidy.loc["epvr_active_pt"]
            rows.append({"method": "psm_did", "outcome": outcome,
                         "beta": round(float(r["Estimate"]), 4),
                         "se": round(float(r["Std. Error"]), 4),
                         "p": round(float(r["Pr(>|t|)"]), 4),
                         "n": int(fit._N), "note": ""})
        except Exception as e:
            rows.append({"method": "psm_did", "outcome": outcome, "beta": np.nan,
                         "se": np.nan, "p": np.nan, "n": len(df), "note": str(e)[:80]})

    # Entropy balancing (simple: re-weight controls to match treated covariate means)
    # We compute weights so that weighted control means equal treated means for
    # rural_income_pre, gdp_pre, primary_share_pre (first-moment balancing).
    treated_means = treated[["rural_income_pre", "gdp_pre", "primary_share_pre"]].mean().values
    Xc = controls[["rural_income_pre", "gdp_pre", "primary_share_pre"]].values
    # Standardize for stability
    Xc_s = (Xc - treated_means) / (Xc.std(axis=0) + 1e-12)
    # Newton-like update: log weights = lambda dot (Xc_s)
    lam = np.zeros(Xc_s.shape[1])
    for _ in range(50):
        w = np.exp(Xc_s @ lam)
        w = w / w.sum()
        grad = w @ Xc_s
        if np.linalg.norm(grad) < 1e-6:
            break
        H = (Xc_s * w[:, None]).T @ Xc_s - np.outer(grad, grad)
        try:
            step = np.linalg.solve(H + 1e-6 * np.eye(H.shape[0]), grad)
        except Exception:
            break
        lam = lam - step
    weights = np.exp(Xc_s @ lam)
    weights = weights / weights.sum() * len(controls)
    controls["eb_weight"] = weights
    log.append(f"Entropy balancing weights summary: min={weights.min():.3f}, max={weights.max():.3f}, mean={weights.mean():.3f}")

    # Apply weights: every panel row for a control province gets that province's weight; treated get 1.0
    wmap = dict(zip(controls["province_code"], controls["eb_weight"]))
    pan_eb = panel.copy()
    pan_eb["eb_w"] = pan_eb["province_code"].map(wmap).fillna(1.0)
    # Only keep treated + controls (not "partial-treated" provinces that fall outside our window)
    keep = set(treated["province_code"].tolist()) | set(controls["province_code"].tolist())
    pan_eb = pan_eb[pan_eb["province_code"].isin(keep)].copy()

    for outcome in ["log_rural_disposable_income", "log_urban_disposable_income",
                     "urban_rural_income_ratio", "log_gdp"]:
        df = pan_eb.dropna(subset=[outcome]).copy()
        if df["epvr_active_pt"].nunique() < 2 or len(df) < 20:
            rows.append({"method": "entropy_balance_did", "outcome": outcome,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "n": len(df),
                         "note": "insufficient_variation"})
            continue
        formula = f"{outcome} ~ epvr_active_pt | province_code + year"
        try:
            fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"},
                           weights="eb_w")
            tidy = fit.tidy()
            r = tidy.loc["epvr_active_pt"]
            rows.append({"method": "entropy_balance_did", "outcome": outcome,
                         "beta": round(float(r["Estimate"]), 4),
                         "se": round(float(r["Std. Error"]), 4),
                         "p": round(float(r["Pr(>|t|)"]), 4),
                         "n": int(fit._N), "note": ""})
        except Exception as e:
            rows.append({"method": "entropy_balance_did", "outcome": outcome,
                         "beta": np.nan, "se": np.nan, "p": np.nan,
                         "n": len(df), "note": str(e)[:80]})

    df_out = pd.DataFrame(rows)
    df_out.to_csv(TAB / "table6_matching_did.csv", index=False)
    log.append(f"\nMatching/EB results:")
    log.append(df_out.to_string(index=False))
    log.append(f"\nWrote {TAB / 'table6_matching_did.csv'}")
    (LOG / "d7.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
