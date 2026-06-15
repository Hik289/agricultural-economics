"""
Phase D — D1: Build province-year analytic panel.

Aggregates 168 EPVR cases by (province, year) and merges with provincial
outcomes from county_panel_real.csv. Province-year level only because
county_panel values are provincial averages propagated to counties.

Outputs:
    analysis/panel_provincial.csv (~310 rows)
    analysis/logs/d1.log (coverage matrix)
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed"
OUT = ROOT / "analysis"
(OUT / "logs").mkdir(parents=True, exist_ok=True)


def load_cases():
    df = pd.read_csv(DATA / "cases_bsi.csv")
    # Drop unresolved province / year
    df = df[df["province_code"].astype(str) != "NA_UNRESOLVED"].copy()
    df["province_code"] = df["province_code"].astype(int)
    df["case_year_num"] = pd.to_numeric(df["case_year"], errors="coerce")
    df = df[df["case_year_num"].notna()].copy()
    df["case_year"] = df["case_year_num"].astype(int)
    # Restrict to plausible years (panel is 2015-2024 but we keep earlier years for first_year)
    df = df[(df["case_year"] >= 2000) & (df["case_year"] <= 2029)].copy()

    # Confidence weights
    w_map = {"human_verified": 1.0, "high": 0.7, "medium": 0.4, "low": 0.3}
    df["w_conf"] = df["final_confidence"].map(w_map).fillna(0.3)
    return df


def build_treatment_panel(cases, years):
    """Cumulative EPVR exposure by (province, year) over panel years."""
    provs = sorted(cases["province_code"].unique())
    rows = []
    first_year = cases.groupby("province_code")["case_year"].min().to_dict()
    for p in provs:
        cp = cases[cases["province_code"] == p].copy()
        for y in years:
            n_cum = int((cp["case_year"] <= y).sum())
            active = int(n_cum > 0)
            rows.append({
                "province_code": p,
                "year": y,
                "epvr_first_year_p": first_year.get(p),
                "epvr_count_pt": n_cum,
                "epvr_active_pt": active,
            })
    return pd.DataFrame(rows)


def build_bsi_aggregates(cases):
    """One row per province with confidence-weighted BSI / capture-risk means."""
    out = []
    for p, g in cases.groupby("province_code"):
        w = g["w_conf"].values
        bsi = g["BSI_net"].astype(float).values
        bsi_raw = g["BSI_raw"].astype(float).values
        cr = g["capture_risk"].astype(float).values
        wsum = w.sum()
        out.append({
            "province_code": p,
            "n_cases": len(g),
            "n_cases_human_verified": int((g["final_confidence"] == "human_verified").sum()),
            "bsi_mean_p": float(np.sum(bsi * w) / wsum) if wsum > 0 else np.nan,
            "bsi_raw_mean_p": float(np.sum(bsi_raw * w) / wsum) if wsum > 0 else np.nan,
            "capture_risk_mean_p": float(np.sum(cr * w) / wsum) if wsum > 0 else np.nan,
            "bsi_mean_p_hv": float(g.loc[g["final_confidence"] == "human_verified", "BSI_net"].mean()) if (g["final_confidence"] == "human_verified").any() else np.nan,
        })
    bsi = pd.DataFrame(out)
    # Median split (across treated provinces)
    med = bsi["bsi_mean_p"].median()
    bsi["bsi_high_p"] = (bsi["bsi_mean_p"] > med).astype(int)
    med_cr = bsi["capture_risk_mean_p"].median()
    bsi["capture_risk_high_p"] = (bsi["capture_risk_mean_p"] > med_cr).astype(int)
    med_raw = bsi["bsi_raw_mean_p"].median()
    bsi["bsi_raw_high_p"] = (bsi["bsi_raw_mean_p"] > med_raw).astype(int)
    return bsi, med, med_cr


def load_outcomes():
    df = pd.read_csv(DATA / "county_panel_real.csv")
    df = df[df["province_code_resolved"].astype(str).str.match(r"^\d+$")].copy()
    df["province_code"] = df["province_code_resolved"].astype(int)

    # Provincial avg: take first non-null per province-year (values are identical for all counties in a province-year)
    agg_cols = [
        "rural_disposable_income", "urban_disposable_income", "urban_rural_income_ratio",
        "gdp", "primary_industry_value_added", "agri_forestry_animal_fishery_output",
        "fiscal_revenue", "fiscal_expenditure", "grain_output", "population",
        "rural_population", "tourism_revenue", "forest_coverage",
    ]
    g = df.groupby(["province_code", "province", "year"])[agg_cols].first().reset_index()
    return g


def main():
    log = []
    cases = load_cases()
    log.append(f"Cases retained after province/year filter: {len(cases)}/168")
    log.append(f"Cases by confidence: {cases['final_confidence'].value_counts().to_dict()}")

    outcomes = load_outcomes()
    years = sorted(outcomes["year"].unique().tolist())
    log.append(f"Outcome panel years: {years}")
    log.append(f"Provinces in outcomes: {outcomes['province_code'].nunique()}")

    # Treatment panel uses outcome years (2015-2024) but first_year can be earlier
    treat = build_treatment_panel(cases, years)
    bsi, med_bsi, med_cr = build_bsi_aggregates(cases)
    log.append(f"BSI median (across {len(bsi)} treated provinces): {med_bsi:.3f}")
    log.append(f"Capture-risk median: {med_cr:.3f}")

    # Construct full panel = outcomes + treatment merge
    panel = outcomes.merge(treat, on=["province_code", "year"], how="left")
    # For provinces with no EPVR cases, fill treatment with 0
    panel["epvr_count_pt"] = panel["epvr_count_pt"].fillna(0).astype(int)
    panel["epvr_active_pt"] = panel["epvr_active_pt"].fillna(0).astype(int)
    # epvr_first_year_p — leave NaN for never-treated provinces

    # Merge BSI
    panel = panel.merge(bsi, on="province_code", how="left")
    # Provinces without any EPVR cases: bsi_high = 0 by definition (no treatment, no BSI)
    for col in ["bsi_high_p", "capture_risk_high_p", "bsi_raw_high_p"]:
        panel[col] = panel[col].fillna(0).astype(int)

    # Logs and ratios — careful with non-positive values
    def safe_log(s):
        s = pd.to_numeric(s, errors="coerce")
        return np.log(s.where(s > 0))

    panel["log_rural_disposable_income"] = safe_log(panel["rural_disposable_income"])
    panel["log_urban_disposable_income"] = safe_log(panel["urban_disposable_income"])
    panel["log_gdp"] = safe_log(panel["gdp"])
    panel["log_primary_industry_value_added"] = safe_log(panel["primary_industry_value_added"])
    panel["log_tourism_revenue"] = safe_log(panel["tourism_revenue"])
    panel["log_fiscal_revenue"] = safe_log(panel["fiscal_revenue"])
    panel["log_population"] = safe_log(panel["population"])
    # urban_rural_income_ratio is already provided (urban / rural)
    panel["urban_rural_income_ratio"] = pd.to_numeric(panel["urban_rural_income_ratio"], errors="coerce")

    # Primary industry share (proxy)
    panel["primary_share"] = pd.to_numeric(panel["primary_industry_value_added"], errors="coerce") / \
                              pd.to_numeric(panel["gdp"], errors="coerce")
    panel["log_primary_share"] = safe_log(panel["primary_share"])
    # Lagged log_population
    panel = panel.sort_values(["province_code", "year"])
    panel["log_population_lag"] = panel.groupby("province_code")["log_population"].shift(1)

    panel.to_csv(OUT / "panel_provincial.csv", index=False)
    log.append(f"Wrote {OUT / 'panel_provincial.csv'} with {len(panel)} rows x {panel.shape[1]} cols")

    # Coverage matrix per province
    cov = panel.groupby(["province_code", "province"]).agg(
        n_years=("year", "count"),
        rural_inc_yrs=("log_rural_disposable_income", lambda s: s.notna().sum()),
        gdp_yrs=("log_gdp", lambda s: s.notna().sum()),
        n_cases=("n_cases", "first"),
        epvr_active_any=("epvr_active_pt", "max"),
        epvr_first_year=("epvr_first_year_p", "first"),
        bsi_mean=("bsi_mean_p", "first"),
        bsi_high=("bsi_high_p", "first"),
        capture_risk_high=("capture_risk_high_p", "first"),
    ).reset_index()
    cov.to_csv(OUT / "tables" / "table1_coverage_matrix.csv", index=False)
    log.append(f"Coverage matrix written: {OUT / 'tables' / 'table1_coverage_matrix.csv'}")
    log.append(f"Provinces ever treated in panel window: {int((cov['epvr_active_any']==1).sum())} / {len(cov)}")
    log.append(f"Provinces with rural income data: {int((cov['rural_inc_yrs']>0).sum())}")

    # Coverage summary text
    print("\n".join(log))
    (OUT / "logs" / "d1.log").write_text("\n".join(log) + "\n")

    # Save neighbors adjacency (province-level) for D8
    neighbors = build_province_adjacency()
    (OUT / "neighbors_provinces.json").write_text(json.dumps(neighbors, ensure_ascii=False, indent=2))
    print(f"\nWrote province adjacency: {OUT / 'neighbors_provinces.json'}")


def build_province_adjacency():
    """Static land-border adjacency between Chinese provinces (codes).

    Sources: standard Chinese geography references. Used for spatial spillover
    proxy. Approximate (excludes maritime adjacency)."""
    # adjacency dict: province_code -> list of neighbor province codes
    adj = {
        11: [12, 13],  # 北京 - 天津, 河北
        12: [11, 13],  # 天津 - 北京, 河北
        13: [11, 12, 14, 15, 21, 37, 41],  # 河北 - many
        14: [13, 15, 41, 61],  # 山西
        15: [13, 14, 21, 22, 23, 61, 62, 64, 65],  # 内蒙古
        21: [13, 15, 22],  # 辽宁
        22: [15, 21, 23],  # 吉林
        23: [15, 22],  # 黑龙江
        31: [32, 33],  # 上海
        32: [31, 33, 34, 37],  # 江苏
        33: [31, 32, 34, 35, 36],  # 浙江
        34: [32, 33, 36, 41, 42],  # 安徽
        35: [33, 36, 44],  # 福建
        36: [33, 34, 35, 42, 43, 44],  # 江西
        37: [13, 32, 41],  # 山东
        41: [13, 14, 34, 37, 42, 61],  # 河南
        42: [34, 36, 41, 43, 50, 51, 61],  # 湖北
        43: [36, 42, 44, 45, 50, 52],  # 湖南
        44: [35, 36, 43, 45, 46],  # 广东
        45: [43, 44, 46, 52, 53],  # 广西
        46: [44, 45],  # 海南
        50: [42, 43, 51, 52],  # 重庆
        51: [42, 50, 52, 53, 54, 61, 62],  # 四川
        52: [43, 45, 50, 51, 53],  # 贵州
        53: [45, 51, 52, 54],  # 云南
        54: [51, 53, 63, 65],  # 西藏
        61: [14, 15, 41, 42, 50, 51, 62, 64],  # 陕西
        62: [15, 51, 54, 61, 63, 64, 65],  # 甘肃
        63: [54, 62, 65],  # 青海
        64: [15, 61, 62],  # 宁夏
        65: [15, 54, 62, 63],  # 新疆
    }
    return adj


if __name__ == "__main__":
    main()
