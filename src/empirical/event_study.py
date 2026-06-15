"""
Phase D — D5: Event study for fully-covered provinces.

For 7 provinces with full 10-year rural income coverage
(Beijing/Shanghai/Fujian/Hubei/Hunan/Chongqing/Heilongjiang), run an
event-time regression for k ∈ {-5,...,+5}, dropping k=-1 as the reference.

Y_pt = a + Σ_k β_k 1[t - T_p = k] + mu_p + lambda_t + e_pt

Plot pre/post coefficients.
"""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import pyfixest as pf
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis"
TAB = OUT / "tables"
FIG = OUT / "figures"
LOG = OUT / "logs"
FIG.mkdir(parents=True, exist_ok=True)

# 7 fully-covered provinces (per spec)
FULL_PROVINCES = {
    11: "Beijing",
    31: "Shanghai",
    35: "Fujian",
    42: "Hubei",
    43: "Hunan",
    50: "Chongqing",
    23: "Heilongjiang",
}


def main():
    panel = pd.read_csv(OUT / "panel_provincial.csv")
    log = ["=== D5: Event study (7 fully-covered provinces) ===", ""]
    log.append(f"Provinces: {list(FULL_PROVINCES.values())}")
    sub = panel[panel["province_code"].isin(FULL_PROVINCES.keys())].copy()
    sub = sub.dropna(subset=["log_rural_disposable_income", "epvr_first_year_p"]).copy()
    sub["event_time"] = sub["year"] - sub["epvr_first_year_p"]
    sub["event_time_clip"] = sub["event_time"].clip(-5, 5).astype(int)
    log.append(f"Rows: {len(sub)}  | provinces: {sub['province_code'].nunique()}")
    log.append(f"Event time distribution:\n{sub['event_time_clip'].value_counts().sort_index().to_string()}")

    # Build event-time dummies (omit k = -1). Use names without minus signs
    # because pyfixest formula parser cannot handle 'k_-5'.
    def k_name(k):
        return f"kpre{abs(k)}" if k < 0 else f"kpost{k}"

    ks = sorted(sub["event_time_clip"].unique())
    for k in ks:
        if k == -1:
            continue
        sub[k_name(k)] = (sub["event_time_clip"] == k).astype(int)

    rhs_terms = [k_name(k) for k in ks if k != -1]
    formula = "log_rural_disposable_income ~ " + " + ".join(rhs_terms) + " | province_code + year"
    log.append(f"\nFormula: {formula}")

    try:
        fit = pf.feols(formula, data=sub, vcov={"CRV1": "province_code"})
        tidy = fit.tidy()
    except Exception as e:
        log.append(f"ERROR: {e}")
        (LOG / "d5.log").write_text("\n".join(log) + "\n")
        print("\n".join(log))
        return

    # Collect coefficients
    rows = []
    rows.append({"k": -1, "coef": 0.0, "se": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "note": "reference"})
    for k in ks:
        if k == -1:
            continue
        key = k_name(k)
        if key in tidy.index:
            r = tidy.loc[key]
            rows.append({
                "k": k,
                "coef": float(r["Estimate"]),
                "se": float(r["Std. Error"]),
                "ci_lo": float(r["2.5%"]),
                "ci_hi": float(r["97.5%"]),
                "note": "",
            })

    df = pd.DataFrame(rows).sort_values("k").reset_index(drop=True)
    df["coef"] = df["coef"].round(4)
    df["se"] = df["se"].round(4)
    df["ci_lo"] = df["ci_lo"].round(4)
    df["ci_hi"] = df["ci_hi"].round(4)
    df.to_csv(TAB / "table4_event_study.csv", index=False)
    log.append(f"\nEvent-study coefficients (relative to k=-1):")
    log.append(df.to_string(index=False))

    # Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.errorbar(df["k"], df["coef"],
                 yerr=[df["coef"] - df["ci_lo"], df["ci_hi"] - df["coef"]],
                 fmt="o-", capsize=4, color="#1f3a93", label="Point estimate (95% CI)")
    ax.axhline(0, color="black", linewidth=0.7, linestyle="--")
    ax.axvline(-0.5, color="red", linewidth=0.7, linestyle=":", label="Treatment start (k=0)")
    ax.set_xlabel("Event time k (years from EPVR first exposure)")
    ax.set_ylabel("β_k on log rural disposable income\n(province-year FE, 7 fully-covered provinces)")
    ax.set_title("Figure 4. Event study: rural disposable income around EPVR exposure\n"
                  "(province-level, N=" + str(len(sub)) + " obs, 7 provinces)")
    ax.set_xticks(sorted(df["k"].unique()))
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "figure4_event_study.pdf")
    fig.savefig(FIG / "figure4_event_study.png", dpi=150)
    plt.close(fig)
    log.append(f"\nFigure: {FIG / 'figure4_event_study.pdf'}")

    (LOG / "d5.log").write_text("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
