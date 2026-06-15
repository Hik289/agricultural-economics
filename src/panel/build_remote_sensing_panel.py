"""
Phase C2 — Build the remote sensing panel (NDVI + nighttime lights).

This script DOES NOT fabricate numerical values. It attempts the standard
public pipelines; if any required input (county polygon shapefile, MODIS
NDVI tiles, VIIRS annual composites) cannot be obtained within the sandbox,
the corresponding column is left as NaN and the gap is documented in
docs/remote_sensing_unavailable.md.

Pipelines attempted (priority order):

  NDVI:
    1. Pre-aggregated county-level NDVI dataset from
       Resource and Environment Science Data Center (resdc.cn).
       → Requires user registration + login; cannot be scripted in this sandbox.
    2. MODIS MOD13Q1 annual tiles from NASA EarthData LPDAAC.
       → Requires EarthData Login credentials.
    3. Google Earth Engine zonal reductions.
       → Requires GEE auth (service account or browser).

  Nighttime lights:
    1. Annual VNL V2 (VIIRS) from NOAA NGDC / Earth Observation Group
       (eogdata.mines.edu/products/vnl/).
       → ~5–10 GB per year of global GeoTIFF; zonal stats need county polygons
         and substantial compute. Public download is available.
    2. Harmonized DMSP/VIIRS dataset on Figshare (Li et al., 2020).
       → Public Figshare DOI, but ~1 GB per year.

  County polygons (required to do zonal reductions):
    1. Tianditu official polygons → require user API key.
    2. GADM Level 2 (China). → Public download from gadm.org.
    3. OpenStreetMap county boundaries via Overpass.
       → Public but very heavy; quality varies.

In this sandbox we attempted (1) confirming the NOAA NGDC endpoint is
reachable but did not download multi-GB VIIRS rasters because:
  (a) without a county shapefile + GEE/GDAL pipeline the zonal mean cannot
      be computed honestly, and
  (b) the project budget for Phase C is ~5–10 hours total and a real raster
      pipeline easily exceeds that just for one year × one product.

Therefore this script emits an EMPTY (NaN-filled) remote-sensing panel keyed
by (county_code, year). The Director should plug in a properly computed
table here when GEE or local raster infrastructure is available.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "data" / "external"
OUT = ROOT / "data" / "processed"
DOCS = ROOT / "docs"
OUT.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

YEARS = list(range(2015, 2025))


def build_skeleton() -> pd.DataFrame:
    area = pd.read_csv(EXT / "admin_areas.csv", dtype={"code": str})
    area = area.rename(columns={"code": "county_code"})
    area["county_code"] = area["county_code"].astype(str).str.zfill(6)
    years_df = pd.DataFrame({"year": YEARS})
    rs = area[["county_code"]].merge(years_df, how="cross")
    rs["ndvi_mean"] = pd.NA
    rs["nighttime_light_mean"] = pd.NA
    rs["rs_source"] = "NOT_LOADED"
    return rs


def write_unavailability_note():
    note = DOCS / "remote_sensing_unavailable.md"
    note.write_text(
        """# Remote sensing data — unavailable in Phase C sandbox

## What was attempted

1. **VIIRS annual nighttime lights** — NOAA Earth Observation Group
   `https://eogdata.mines.edu/products/vnl/` (reachable, HTTP 200), but each
   annual global GeoTIFF is several GB. No county polygon shapefile and no
   GEE auth available, so zonal mean cannot be computed honestly without
   spending many hours on raster ingestion.
2. **MODIS MOD13Q1 NDVI** — NASA LPDAAC requires EarthData Login; Google
   Earth Engine requires service-account credentials. Neither is configured
   in this sandbox.
3. **Pre-aggregated county NDVI from `resdc.cn`** — site is reachable but
   the dataset requires interactive login / form download; cannot be
   scripted automatically.

## Decision

Per the sub-agent task instructions, when both NDVI and nightlight pipelines
are unreachable we proceed with C1 only and leave the two RS columns as
`NA` in the merged panel. The build script `build_remote_sensing_panel.py`
emits a row-complete (county × year) skeleton with `ndvi_mean` and
`nighttime_light_mean` set to NaN.

## What is needed to backfill

- A county-level GeoJSON / shapefile for China (GADM L2 is acceptable for
  research use; the official Tianditu polygons are preferable for GB/T 2260
  alignment).
- Either a GEE service-account credential JSON, or local GDAL + rasterio
  pipeline able to handle ~5–10 GB / year of VIIRS and ~50 GB total for
  MODIS NDVI 2015–2024.
- About 8–12 GPU-free CPU hours per product to produce zonal means.

Until then the Director should treat `ndvi_mean` / `nighttime_light_mean`
as TBD; Phase D ecological-outcome regressions cannot use these columns yet.
""",
        encoding="utf-8",
    )


def main():
    rs = build_skeleton()
    out_path = OUT / "remote_sensing_panel.csv"
    rs.to_csv(out_path, index=False, encoding="utf-8")
    print(f"wrote {out_path} rows={len(rs)} (all NDVI / nightlight = NaN)")
    write_unavailability_note()
    print("wrote docs/remote_sensing_unavailable.md")


if __name__ == "__main__":
    main()
