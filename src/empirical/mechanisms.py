"""Phase D — D10: Mechanism channels."""
import sys
sys.path.insert(0, '/home/user/projects/epvr-replication/src/empirical')
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import pyfixest as pf

warnings.filterwarnings("ignore")

ROOT = Path('/home/user/projects/epvr-replication')
OUT = ROOT / "analysis"
TAB = OUT / "tables"
LOG = OUT / "logs"


def main():
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    panel["epvr_x_bsi_high"] = panel["epvr_active_pt"] * panel["bsi_high_p"]
    panel["epvr_x_cr_high"] = panel["epvr_active_pt"] * panel["capture_risk_high_p"]

    log = ["=== D10: Mechanism channels (BSI heterogeneity) ===", ""]
    rows = []
    for outcome in ["log_tourism_revenue", "log_primary_industry_value_added",
                     "log_fiscal_revenue", "log_population"]:
        df = panel.dropna(subset=[outcome]).copy()
        formula1 = f"{outcome} ~ epvr_active_pt | province_code + year"
        formula2 = f"{outcome} ~ epvr_active_pt + epvr_x_bsi_high | province_code + year"
        formula3 = f"{outcome} ~ epvr_active_pt + epvr_x_bsi_high + epvr_x_cr_high | province_code + year"
        for spec_name, formula in [("main", formula1), ("bsi_het", formula2), ("bsi_capture", formula3)]:
            try:
                fit = pf.feols(formula, data=df, vcov={"CRV1": "province_code"})
                tidy = fit.tidy()
                for term, label in [("epvr_active_pt", "b1"),
                                     ("epvr_x_bsi_high", "b2_bsi"),
                                     ("epvr_x_cr_high", "b3_cr")]:
                    if term in tidy.index:
                        r = tidy.loc[term]
                        rows.append({
                            "outcome": outcome, "spec": spec_name, "term": term,
                            "label": label,
                            "beta": round(float(r["Estimate"]), 4),
                            "se": round(float(r["Std. Error"]), 4),
                            "p": round(float(r["Pr(>|t|)"]), 4),
                            "n": int(fit._N),
                        })
            except Exception as e:
                rows.append({"outcome": outcome, "spec": spec_name, "term": "",
                             "label": "", "beta": np.nan, "se": np.nan, "p": np.nan,
                             "n": 0, "error": str(e)[:80]})

    df_out = pd.DataFrame(rows)
    df_out.to_csv(TAB / "table5_mechanisms.csv", index=False)
    log.append(df_out.to_string(index=False))
    log.append(f"\nWrote {TAB / 'table5_mechanisms.csv'}")
    (LOG / "d10.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
