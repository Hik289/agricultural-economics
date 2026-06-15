"""
Phase C3 — Merge the socio-economic skeleton (C1) and the remote sensing
skeleton (C2) into the final county_panel.csv expected by Phase D.

Column order follows docs/data_dictionary.md §3 (Layer 2: county-year panel).
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"

FINAL_COLS = [
    "county_code",
    "county_name",
    "province",
    "prefecture",
    "year",
    "rural_disposable_income",
    "urban_disposable_income",
    "urban_rural_income_ratio",
    "gdp",
    "primary_industry_value_added",
    "agri_forestry_animal_fishery_output",
    "fiscal_revenue",
    "fiscal_expenditure",
    "agricultural_machinery_power",
    "grain_output",
    "population",
    "rural_population",
    "tourism_revenue",
    "forest_coverage",
    "nighttime_light_mean",
    "ndvi_mean",
    "land_use_cropland_share",
    "land_use_forest_share",
    "land_use_grassland_share",
    "restricted_or_licensed",
]


def main():
    se = pd.read_csv(PROC / "county_panel_socioeconomic.csv", dtype={"county_code": str})
    rs = pd.read_csv(PROC / "remote_sensing_panel.csv", dtype={"county_code": str})

    se["county_code"] = se["county_code"].str.zfill(6)
    rs["county_code"] = rs["county_code"].str.zfill(6)

    merged = se.merge(
        rs[["county_code", "year", "ndvi_mean", "nighttime_light_mean"]],
        on=["county_code", "year"],
        how="left",
        validate="one_to_one",
    )

    # Ensure all spec columns exist
    for c in FINAL_COLS:
        if c not in merged.columns:
            merged[c] = pd.NA

    merged = merged[FINAL_COLS]
    out = PROC / "county_panel.csv"
    merged.to_csv(out, index=False, encoding="utf-8")
    print(f"wrote {out}: rows={len(merged)} cols={merged.shape[1]}")
    print(f"unique counties={merged['county_code'].nunique()}, years={sorted(merged['year'].unique())}")


if __name__ == "__main__":
    main()
