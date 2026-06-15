"""
Phase C1 — Build the county-year socioeconomic panel skeleton.

Inputs:
  data/external/admin_provinces.csv
  data/external/admin_cities.csv
  data/external/admin_areas.csv
    Source: github.com/modood/Administrative-divisions-of-China (MIT licensed)
    Compiled from MCA/NBS GB/T 2260 official county codes (snapshot ~2023).

Logic:
  1. Build crosswalk: 6-digit county_code → (county_name, prefecture, province).
  2. Cross-join with year ∈ 2015..2024 (spec §3.2 minimum coverage).
  3. Fill all numeric socio-economic columns with NaN (NA_NOT_REPORTED equivalent).
     We DO NOT fabricate values. The Director / Phase D must supply licensed
     yearbook extractions before estimation.
  4. Set restricted_or_licensed = 0 by row since no licensed values have been
     loaded yet. When licensed yearbook data is plugged in for specific rows,
     set this flag to 1 on those rows.

Output:
  data/processed/county_panel_socioeconomic.csv  (skeleton — Phase C1 only)

Note: the FINAL merged panel (with remote sensing) is produced by merge_panel.py
and written to data/processed/county_panel.csv.
"""

from __future__ import annotations

import os
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "data" / "external"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

YEARS = list(range(2015, 2025))  # 2015–2024 inclusive

SOCIOECON_COLS = [
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
    "land_use_cropland_share",
    "land_use_forest_share",
    "land_use_grassland_share",
]


def build_crosswalk() -> pd.DataFrame:
    prov = pd.read_csv(EXT / "admin_provinces.csv", dtype={"code": str})
    cit = pd.read_csv(EXT / "admin_cities.csv", dtype={"code": str, "provinceCode": str})
    area = pd.read_csv(
        EXT / "admin_areas.csv",
        dtype={"code": str, "cityCode": str, "provinceCode": str},
    )
    prov = prov.rename(columns={"code": "provinceCode", "name": "province"})
    cit = cit.rename(columns={"code": "cityCode", "name": "prefecture"})
    area = area.rename(columns={"code": "county_code", "name": "county_name"})

    df = area.merge(cit[["cityCode", "prefecture"]], on="cityCode", how="left")
    df = df.merge(prov[["provinceCode", "province"]], on="provinceCode", how="left")

    # zero-pad to 6 chars (already is, but defensive)
    df["county_code"] = df["county_code"].astype(str).str.zfill(6)
    return df[["county_code", "county_name", "prefecture", "province"]]


def build_panel(crosswalk: pd.DataFrame) -> pd.DataFrame:
    years_df = pd.DataFrame({"year": YEARS})
    panel = crosswalk.merge(years_df, how="cross")

    for c in SOCIOECON_COLS:
        panel[c] = pd.NA

    # restricted_or_licensed: per the data dictionary, this is per-row.
    # Skeleton has no licensed values loaded yet, so 0 for every row.
    panel["restricted_or_licensed"] = 0

    panel = panel.sort_values(["province", "prefecture", "county_code", "year"]).reset_index(drop=True)
    return panel


def main():
    cw = build_crosswalk()
    print(f"crosswalk: {len(cw)} counties, {cw['province'].nunique()} provinces")

    panel = build_panel(cw)
    out_path = OUT / "county_panel_socioeconomic.csv"
    panel.to_csv(out_path, index=False, encoding="utf-8")
    print(f"wrote {out_path} rows={len(panel)} cols={panel.shape[1]}")
    print(f"unique counties: {panel['county_code'].nunique()}, years: {sorted(panel['year'].unique())}")


if __name__ == "__main__":
    main()
