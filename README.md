# EPVR Benefit-Sharing Replication Package

<p align="center">
  <a href="#replication-steps"><img src="https://img.shields.io/badge/replication-4%20steps-2ea44f" alt="Replication steps"></a>
  <a href="#intuition"><img src="https://img.shields.io/badge/intuition-capture--risk%20support%20map-7c3aed" alt="Intuition"></a>
  <a href="#api-key-configuration"><img src="https://img.shields.io/badge/config-OpenAI%20%7C%20Anthropic-f97316" alt="API key configuration"></a>
  <a href="#repository-structure"><img src="https://img.shields.io/badge/modules-crawler%20%7C%20BSI%20%7C%20panel%20%7C%20DID-2563eb" alt="Repository modules"></a>
  <a href="#citation"><img src="https://img.shields.io/badge/citation-Land%20Use%20Policy-64748b" alt="Citation"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/method-staggered%20DID-lightgrey" alt="Staggered DID">
  <img src="https://img.shields.io/badge/index-BSI%2012%20indicators-lightgrey" alt="BSI index">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license">
</p>

This repository contains replication code and analysis for the paper:

> Anonymous (2026). "Benefit-Sharing Institutions in China's Ecosystem Product Value Realization Markets: A Diagnostic Framework and Distributional Evidence." *Land Use Policy* (under review).

We develop a **Benefit-Sharing Institution Index (BSI)** from 168 EPVR policy cases, construct a province-year panel (2015-2024), and estimate distributional effects using staggered difference-in-differences.

## Intuition

<p align="center">
  <img src="analysis/figures/figure2_capture_support_map.png" width="800" alt="Capture-risk case-support map">
</p>

The capture-risk analysis relies on uneven provincial case support. Hubei has pre/post support for capture-risk comparisons, while Yunnan, Guangdong, and Fujian provide sparse support cases. The map makes the empirical support structure visible before the DID and robustness exercises.

## Highlights

- Benefit-Sharing Institution Index built from 168 EPVR policy cases and 12 indicators.
- Triple-source BSI coding pipeline: rule-based coding, LLM-assisted coding, and automated cross-validation.
- Province-year panel construction from government bulletins and supporting remote-sensing/panel data.
- Staggered DID, event-study, matching DID, mechanism regressions, and robustness checks.
- Publication table and figure generation for Land Use Policy-style replication artifacts.

## Repository Structure

```text
.
|-- README.md
|-- requirements.txt
|-- src/
|   |-- crawler/                 # Web crawling and document collection
|   |-- bsi_coding/              # BSI coding pipeline
|   |-- panel/                   # Province-year panel construction
|   `-- empirical/               # DID estimation and robustness
|-- analysis/
|   |-- tables/                  # Output tables
|   `-- figures/                 # Publication figures
|       `-- figure2_capture_support_map.png
|-- docs/                        # Coding protocol, data dictionary, identification notes
`-- paper/                       # Manuscript artifacts
```

## Requirements

```bash
git clone git@github.com:Hik289/agricultural-economics.git
cd agricultural-economics

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Key packages include `pandas`, `numpy`, `statsmodels`, `linearmodels`, `pyfixest`, `csdid`, `requests`, `beautifulsoup4`, `openai`, and `anthropic`.

## Replication Steps

### 1. Data Collection

Crawl EPVR policy documents from Chinese government portals:

```bash
python src/crawler/crawl_seed_pages.py
python src/crawler/crawl_gov_search.py
python src/crawler/download_pdfs.py
python src/crawler/parse_html_pdf.py
```

Expected outputs include `data/cases_raw.csv`, `data/raw_html/`, and `data/raw_pdf/`.

### 2. BSI Coding

Apply triple-source BSI coding:

```bash
python src/bsi_coding/code_bsi_rules.py
python src/bsi_coding/llm_assisted_coding.py
python src/bsi_coding/auto_validation_pipeline.py
```

Expected output: `data/processed/cases_bsi.csv` with 168 cases and 12 BSI indicators.

### 3. Panel Construction

Build the province-year panel from NBS bulletins:

```bash
python src/panel/crawl_province_bulletins.py
python src/panel/fetch_bulletins_parallel.py
python src/panel/parse_bulletin.py
python src/panel/merge_bulletins_to_skeleton.py
python src/panel/extract_panel.py
python src/panel/merge_panel.py
```

Expected output: `data/processed/panel_province_bulletins.csv`.

### 4. Empirical Analysis

Run staggered DID estimation and robustness checks:

```bash
python src/empirical/build_provincial_panel.py
python src/empirical/main_did.py
python src/empirical/staggered_did.py
python src/empirical/event_study.py
python src/empirical/robustness.py
python src/empirical/phase_d_v3_robustness.py
python src/empirical/make_lup_figures.py
```

Expected outputs: `analysis/tables/` and `analysis/figures/`.

## Data Availability

- Province-level panel data: available in `epvr-benefit-sharing-data/` through the companion data package.
- Raw HTML/PDF documents: available upon request because government publications may carry copyright restrictions.
- BSI-coded cases: `cases_bsi_public.csv` in the companion data package.

## API Key Configuration

The LLM-assisted coding step requires API keys:

```bash
export OPENAI_API_KEY="YOUR_API_KEY_HERE"
export ANTHROPIC_API_KEY="YOUR_API_KEY_HERE"
```

Do not commit real API keys or local credential files.

## Citation

Anonymous (2026). "Benefit-Sharing Institutions in China's Ecosystem Product Value Realization Markets: A Diagnostic Framework and Distributional Evidence." *Land Use Policy* (under review). Repository will be updated with full citation upon acceptance.

## License

MIT License.
