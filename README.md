# EPVR Benefit-Sharing Replication Package

## Overview

This repository contains replication code and analysis for the paper:

> Anonymous (2026). "Benefit-Sharing Institutions in China's Ecosystem Product Value Realization Markets: A Diagnostic Framework and Distributional Evidence." *Land Use Policy* (under review).

We develop a **Benefit-Sharing Institution Index (BSI)** from 168 EPVR policy cases, construct a province-year panel (2015–2024), and estimate distributional effects using staggered difference-in-differences.

## Repository Structure

```
epvr-benefit-sharing-replication/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
│
├── src/
│   ├── crawler/                 # Web crawling & document collection
│   │   ├── _common.py           # Shared utilities (paths, HTTP, dedup)
│   │   ├── crawl_seed_pages.py  # Seed page crawling from gov portals
│   │   ├── crawl_gov_search.py  # Government search API crawling
│   │   ├── crawl_gov_search_more.py  # Extended search with pagination
│   │   ├── download_pdfs.py     # PDF download pipeline
│   │   └── parse_html_pdf.py    # HTML/PDF text extraction
│   │
│   ├── bsi_coding/              # BSI coding pipeline (triple-source)
│   │   ├── code_bsi_rules.py         # Rule-based BSI coding (12 indicators)
│   │   ├── llm_assisted_coding.py    # LLM-assisted coding (GPT-4 + Claude)
│   │   └── auto_validation_pipeline.py  # Automated cross-validation
│   │
│   ├── panel/                   # Province-year panel construction
│   │   ├── _bulletin_common.py           # Shared bulletin utilities
│   │   ├── crawl_province_bulletins.py   # Provincial bulletin crawling
│   │   ├── parse_bulletin.py             # Bulletin parsing & extraction
│   │   ├── extract_panel.py              # Panel variable extraction
│   │   ├── merge_bulletins_to_skeleton.py # Merge to province-year skeleton
│   │   ├── merge_panel.py                # Final panel merge
│   │   ├── build_county_panel.py         # County-level panel construction
│   │   ├── build_remote_sensing_panel.py # Remote sensing data integration
│   │   ├── fetch_bulletins_parallel.py   # Parallel bulletin fetching
│   │   ├── fetch_bulletins_gapfill.py    # Gap-filling for missing bulletins
│   │   ├── fetch_bulletins_gapfill_parallel.py  # Parallel gap-filling
│   │   ├── gapfill_priority_5.py         # Priority gap-fill (tier 5 provinces)
│   │   ├── wayback_gapfill.py            # Wayback Machine gap-filling
│   │   ├── wayback_fetch_from_candidates.py  # Candidate URL fetching
│   │   └── validate_provincial_hosts.py  # Host validation for bulletins
│   │
│   └── empirical/               # DID estimation & robustness
│       ├── build_provincial_panel.py  # Assemble province-year panel for DID
│       ├── main_did.py                # Main DID specification (Table 2)
│       ├── staggered_did.py           # Callaway-Sant'Anna staggered DID
│       ├── event_study.py             # Event-study plots (Figure 4)
│       ├── matching_did.py            # Propensity-score matching DID
│       ├── mechanisms.py              # Mechanism channel regressions (Table 5)
│       ├── robustness.py              # Robustness checks (Table 6)
│       ├── phase_d_v3_robustness.py   # Extended v3 robustness (LOPO, timing)
│       └── make_lup_figures.py        # Publication figures (Figures 4–8)
│
├── docs/
│   ├── coding_protocol.md       # BSI indicator definitions & coding rules
│   ├── data_dictionary.md       # Variable definitions for all datasets
│   ├── identification_notes.md  # Identification strategy discussion
│   └── journal_fit_notes.md     # Journal submission notes
│
├── analysis/
│   ├── tables/                  # CSV output tables (Tables 1–9)
│   │   ├── table1_coverage_matrix.csv
│   │   ├── table2_main_did.csv
│   │   ├── table3_bsi_heterogeneity.csv
│   │   ├── table3b_capture_risk.csv
│   │   ├── table4_event_study.csv
│   │   ├── table4b_staggered_did.csv
│   │   ├── table4b_sun_abraham_dynamic.csv
│   │   ├── table4b_cs_dynamic_rural.csv
│   │   ├── table5_mechanisms.csv
│   │   ├── table6_matching_did.csv
│   │   ├── table6_robustness.csv
│   │   ├── table8_lopo_capture_risk.csv
│   │   └── table9_timing_sensitivity.csv
│   │
│   └── figures/                 # Publication figures (PDF + PNG)
│       ├── figure4_event_study.*
│       ├── figure5_bsi_heterogeneity.*
│       ├── figure6_capture_risk.*
│       ├── figure7_lopo_capture_risk.*
│       └── figure8_timing_sensitivity.*
│
└── paper/
    └── manuscript_lup.pdf       # Submitted manuscript (Land Use Policy)
```

## Requirements

- Python 3.9+
- Install dependencies: `pip install -r requirements.txt`
- Key packages: `pandas`, `numpy`, `statsmodels`, `linearmodels`, `pyfixest`, `csdid`, `requests`, `beautifulsoup4`, `openai`, `anthropic`

## Replication Steps

### 1. Data Collection (`src/crawler/`)

Crawl EPVR policy documents from Chinese government portals:

```bash
python src/crawler/crawl_seed_pages.py      # Seed page collection
python src/crawler/crawl_gov_search.py      # Government search crawl
python src/crawler/download_pdfs.py         # PDF download
python src/crawler/parse_html_pdf.py        # Text extraction
```

Output: `data/cases_raw.csv`, `data/raw_html/`, `data/raw_pdf/`

### 2. BSI Coding (`src/bsi_coding/`)

Apply triple-source BSI coding (rule-based + LLM + human verification):

```bash
python src/bsi_coding/code_bsi_rules.py          # Rule-based pass
python src/bsi_coding/llm_assisted_coding.py      # LLM-assisted pass (requires API keys)
python src/bsi_coding/auto_validation_pipeline.py # Cross-validation
```

Output: `data/processed/cases_bsi.csv` (168 cases, 12 BSI indicators)

### 3. Panel Construction (`src/panel/`)

Build province-year panel from NBS bulletins (2015–2024):

```bash
python src/panel/crawl_province_bulletins.py
python src/panel/fetch_bulletins_parallel.py
python src/panel/parse_bulletin.py
python src/panel/merge_bulletins_to_skeleton.py
python src/panel/extract_panel.py
python src/panel/merge_panel.py
```

Output: `data/processed/panel_province_bulletins.csv`

### 4. Empirical Analysis (`src/empirical/`)

Run staggered DID estimation (Callaway–Sant'Anna 2021):

```bash
python src/empirical/build_provincial_panel.py
python src/empirical/main_did.py          # Main specification
python src/empirical/staggered_did.py     # CS staggered DID
python src/empirical/event_study.py       # Event-study
python src/empirical/robustness.py        # Robustness checks
python src/empirical/phase_d_v3_robustness.py  # LOPO + timing sensitivity
python src/empirical/make_lup_figures.py  # Generate figures
```

Output: `analysis/tables/`, `analysis/figures/`

## Data Availability

- **Province-level panel data**: available in `epvr-benefit-sharing-data/` (see companion data package)
- **Raw HTML/PDF documents**: available upon request (copyright restrictions apply for government publications)
- **BSI-coded cases**: `cases_bsi_public.csv` in companion data package

## API Key Configuration

The LLM-assisted coding step (`src/bsi_coding/llm_assisted_coding.py`) requires API keys:

```bash
export OPENAI_API_KEY="YOUR_API_KEY_HERE"
export ANTHROPIC_API_KEY="YOUR_API_KEY_HERE"
```

## Citation

Anonymous (2026). "Benefit-Sharing Institutions in China's Ecosystem Product Value Realization Markets: A Diagnostic Framework and Distributional Evidence." *Land Use Policy* (under review). Repository will be updated with full citation upon acceptance.

## License

MIT License
