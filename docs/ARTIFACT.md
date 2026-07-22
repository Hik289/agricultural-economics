# Artifact Guide

Operational notes for reproducing `EPVR Benefit-Sharing Replication Package` from the public `agricultural-economics` repository.

## Review Path

- `src/`: Core source code and reusable implementations.
- `analysis/`: Post-processing, table, and figure-generation scripts.

## Environment Files

- `requirements.txt`: Primary Python dependency list.

## Smoke Checks

Run these checks before long jobs:

```bash
python -m compileall -q .
```

If no smoke command is tracked, use the README Quick Start with the smallest seed, sample, or task count.

## Reproduction Entry Points

No single reproduction runner is tracked. Use the README commands and keep first runs small before full grids.

## Data And Outputs

- API-backed runs should read credentials from environment variables or local `.env` files only; never commit real keys or provider-specific secrets.
- Record provider endpoint, model/deployment name, sampling parameters, and execution date for every API-backed table or figure.
- Treat generated JSONL files, logs, caches, model checkpoints, and benchmark downloads as local artifacts unless explicitly tracked as fixtures.
- For stochastic experiments, record seeds, task counts, dataset splits, and the exact git commit used for the run.

## Reporting Checklist

- `git rev-parse HEAD`
- Python version and dependency-install command
- Full command line for every table, figure, or benchmark cell
- Paths to raw outputs and aggregation scripts
- External data, benchmark, or API-backed steps that were intentionally skipped
