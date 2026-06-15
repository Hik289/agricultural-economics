"""Publication-quality figures for manuscript_lup.tex
Output to analysis/figures/ as PDF + PNG (≥300 DPI).
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[2]
TBL  = ROOT / "analysis" / "tables"
OUT  = ROOT / "analysis" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# ---- Style ----------------------------------------------------------------
NAVY    = "#2E5984"
NAVY_D  = "#1B3A5C"
RED     = "#C44536"
GRAY    = "#6B7280"
GREEN   = "#2E7D32"
CI_FILL = "#A6BFD8"

mpl.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif", "Times New Roman", "Times"],
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.fontsize": 9,
    "legend.frameon": False,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "savefig.dpi": 350,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

def save(fig, stem: str) -> None:
    pdf = OUT / f"{stem}.pdf"
    png = OUT / f"{stem}.png"
    fig.savefig(pdf)
    fig.savefig(png, dpi=350)
    plt.close(fig)
    print(f"  -> {pdf.name}  +  {png.name}")

# =========================================================================
# Figure 4 — Event study (rural disposable income)
# =========================================================================
def figure4_event_study():
    df = pd.read_csv(TBL / "table4_event_study.csv")
    df = df.sort_values("k").reset_index(drop=True)
    is_ref = df["note"].astype(str).str.contains("reference", na=False)

    fig, ax = plt.subplots(figsize=(7.2, 4.4))

    # CI band (shaded) for non-reference points using interpolation
    mask = ~is_ref
    ax.fill_between(df["k"][mask], df["ci_lo"][mask], df["ci_hi"][mask],
                    color=CI_FILL, alpha=0.55, label="95% CI", linewidth=0)

    # Reference period vertical line
    ax.axvline(0, color=GRAY, ls="--", lw=0.9, alpha=0.8)
    ax.axhline(0, color="black", lw=0.6)

    # Connector line (skip reference)
    ax.plot(df["k"][mask], df["coef"][mask], color=NAVY, lw=1.5, zorder=3)

    # Points + error bars
    ax.errorbar(df["k"][mask], df["coef"][mask],
                yerr=[df["coef"][mask]-df["ci_lo"][mask], df["ci_hi"][mask]-df["coef"][mask]],
                fmt="o", color=NAVY, ecolor=NAVY, ms=5, lw=1.0, capsize=2.5, zorder=4,
                label="Point estimate")

    # Reference point (hollow)
    ref = df[is_ref]
    ax.scatter(ref["k"], ref["coef"], facecolors="white", edgecolors=NAVY,
               s=55, lw=1.4, zorder=5, label="Reference (t = −1, omitted)")

    ax.set_xlabel("Event time (years from first EPVR case)")
    ax.set_ylabel("Effect on log rural disposable income")
    ax.set_title("Event-study coefficients — log rural disposable income\n"
                 "(7 fully-covered EPVR-treated provinces, N = 65)")
    ax.set_xticks(df["k"])
    ax.legend(loc="lower left", ncol=1)

    ax.text(0.02, -0.18,
            "Notes: Reference period t = −1 omitted; vertical dashed line marks first EPVR case (t = 0). "
            "Source: analysis/tables/table4_event_study.csv (Phase D v1/v2).",
            transform=ax.transAxes, fontsize=7.5, color=GRAY, ha="left", va="top")

    fig.subplots_adjust(bottom=0.20)
    save(fig, "figure4_event_study")


# =========================================================================
# Figure 5 — BSI heterogeneity (β2 on EPVR × BSI_high)
# =========================================================================
OUTCOME_LABEL = {
    "log_rural_disposable_income":      "log rural disposable income",
    "log_urban_disposable_income":      "log urban disposable income",
    "urban_rural_income_ratio":         "urban–rural income ratio",
    "log_gdp":                          "log GDP",
    "log_primary_industry_value_added": "log primary-industry value added",
}

def _het_plot(df_b2: pd.DataFrame, outcomes: list[str], title: str,
              stem: str, p_col: str = "wild_cluster_p",
              highlight: tuple[str, float] | None = None) -> None:
    """Generic horizontal forest plot of β with 95% CI, paired fe_only vs fe_controls."""
    n_out = len(outcomes)
    fig, ax = plt.subplots(figsize=(8.6, 1.0 * n_out + 2.0))

    y_positions = np.arange(n_out)[::-1]  # top -> bottom in given order
    offset = 0.18
    color_map = {"fe_only": NAVY, "fe_controls": NAVY_D}
    label_map = {"fe_only": "FE only", "fe_controls": "FE + controls"}

    for spec_idx, spec in enumerate(["fe_only", "fe_controls"]):
        sgn = -1 if spec == "fe_only" else +1
        ys = y_positions + sgn * offset
        for i, outc in enumerate(outcomes):
            row = df_b2[(df_b2["outcome"] == outc) & (df_b2["spec"] == spec)]
            if row.empty:
                continue
            row = row.iloc[0]
            b, lo, hi = row["coef"], row["ci_lo"], row["ci_hi"]
            ax.errorbar(b, ys[i], xerr=[[b-lo], [hi-b]],
                        fmt="o", color=color_map[spec], ecolor=color_map[spec],
                        ms=5.5, lw=1.2, capsize=2.5,
                        label=label_map[spec] if i == 0 else None)
            # wild-cluster p annotation (use axes/data offset; expand later)
            p = row.get(p_col, np.nan)
            if pd.notna(p):
                ax.annotate(f"wild p={p:.2f}",
                            xy=(hi, ys[i]),
                            xytext=(6, 0), textcoords="offset points",
                            va="center", ha="left", fontsize=7.5,
                            color=color_map[spec], annotation_clip=False)

    ax.axvline(0, color=GRAY, ls="--", lw=0.9)
    ax.set_yticks(y_positions)
    ax.set_yticklabels([OUTCOME_LABEL.get(o, o) for o in outcomes])
    ax.set_xlabel(r"Coefficient $\beta$ on EPVR × (heterogeneity dummy)" + "  (95% CI)")
    ax.set_title(title, pad=18)

    # Expand x-range to fit wild-p annotations (extra right padding to avoid clip)
    x_lo, x_hi = ax.get_xlim()
    rng = x_hi - x_lo
    ax.set_xlim(x_lo - 0.04 * rng, x_hi + 0.30 * rng)
    ax.set_ylim(-0.7, n_out - 1 + 0.7)

    # Highlight callout (positioned BELOW headline row to avoid title overlap)
    if highlight is not None:
        out_name, val = highlight
        if out_name in outcomes:
            yi = y_positions[outcomes.index(out_name)]
            ax.annotate(
                f"Headline: $\\beta_3 = {val:+.3f}$\n(wild p > 0.10: not significant)",
                xy=(val, yi - offset),
                xytext=(val + 0.06, yi - 0.62),
                fontsize=8, color=RED, ha="left", va="center",
                arrowprops=dict(arrowstyle="->", color=RED, lw=0.8))

    # Legend placed OUTSIDE the axes (below the x-axis) — never collides with title or data
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14),
              ncol=2, frameon=False)

    src = "table3b_capture_risk.csv" if "capture" in stem else "table3_bsi_heterogeneity.csv"
    # Footnote: wrapped to avoid right-edge clipping under tight bbox
    note = (f"Notes: Points are point estimates; horizontal bars are 95% confidence intervals.\n"
            f"Wild-cluster bootstrap p-values shown where computed. Source: analysis/tables/{src}.")
    ax.text(0.0, -0.30, note,
            transform=ax.transAxes, fontsize=7.5, color=GRAY, ha="left", va="top",
            wrap=True)

    fig.subplots_adjust(bottom=0.28, top=0.90)
    save(fig, stem)


def figure5_bsi_heterogeneity():
    df = pd.read_csv(TBL / "table3_bsi_heterogeneity.csv")
    df_b2 = df[df["term"] == "epvr_x_bsi_high"].copy()
    outcomes = [
        "log_rural_disposable_income",
        "log_urban_disposable_income",
        "urban_rural_income_ratio",
        "log_gdp",
        "log_primary_industry_value_added",
    ]
    _het_plot(df_b2, outcomes,
              title=r"BSI heterogeneity — $\beta_2$ on EPVR × $BSI_{high}$ across five outcomes",
              stem="figure5_bsi_heterogeneity")


# =========================================================================
# Figure 6 — Capture-risk heterogeneity (β3 on EPVR × CR_high)
# =========================================================================
def figure6_capture_risk():
    df = pd.read_csv(TBL / "table3b_capture_risk.csv")
    df_b3 = df[df["term"] == "epvr_x_cr_high"].copy()
    outcomes = [
        "log_rural_disposable_income",
        "log_urban_disposable_income",
        "urban_rural_income_ratio",
        "log_gdp",
    ]
    # Headline coefficient: fe_controls rural-income β₃ = -0.0765 (-0.077)
    headline = ("log_rural_disposable_income", -0.0765)
    _het_plot(df_b3, outcomes,
              title=r"Capture-risk heterogeneity — $\beta_3$ on EPVR × $CR_{high}$ across four outcomes",
              stem="figure6_capture_risk",
              highlight=headline)


# =========================================================================
# Figure 7 — LOPO sensitivity for β3
# =========================================================================
def figure7_lopo_capture_risk():
    df = pd.read_csv(TBL / "table8_lopo_capture_risk.csv")
    # province names appear like "35 Fujian" — keep readable label
    df["prov_label"] = df["dropped_province"].str.replace(r"^\d+\s+", "", regex=True)

    outcomes = [
        ("log_rural_disposable_income", "log rural disposable income"),
        ("urban_rural_income_ratio",    "urban–rural income ratio"),
        ("log_gdp",                     "log GDP"),
    ]
    prov_order = ["Fujian", "Hubei", "Guangdong", "Yunnan"]

    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.2), sharey=False)

    for ax, (outc, label) in zip(axes, outcomes):
        sub = df[df["outcome"] == outc].set_index("prov_label").reindex(prov_order)
        full_beta = sub["full_beta_3"].dropna().iloc[0] if sub["full_beta_3"].notna().any() else np.nan
        xs = np.arange(len(prov_order))

        # Reference line for full-sample β3
        if pd.notna(full_beta):
            ax.axhline(full_beta, color=GRAY, ls="--", lw=1.0,
                       label=f"Full-sample $\\beta_3$ = {full_beta:+.3f}")

        ax.axhline(0, color="black", lw=0.5)

        valid = sub["beta_3"].notna()
        bvals = sub.loc[valid, "beta_3"].values
        bse   = sub.loc[valid, "se"].values
        xs_ok = xs[valid.values]

        ax.errorbar(xs_ok, bvals, yerr=1.96*bse, fmt="o",
                    color=NAVY, ecolor=NAVY, ms=6, lw=1.2, capsize=3,
                    label=r"LOPO $\beta_3$ (±1.96·SE)")

        # NA marker for Hubei
        na_mask = ~valid.values
        if na_mask.any():
            y_mid = full_beta if pd.notna(full_beta) else 0
            ax.scatter(xs[na_mask], [y_mid]*na_mask.sum(),
                       marker="x", color=RED, s=90, lw=2.0, zorder=5,
                       label="Identification collapsed (NA)")
            # Place annotation BELOW the marker (away from suptitle area)
            cur_lo, cur_hi = ax.get_ylim() if ax.has_data() else (-1, 1)
            for xn in xs[na_mask]:
                ax.annotate("Hubei: β₃ not identified\n(sole anchor dropped)",
                            xy=(xn, y_mid),
                            xytext=(xn, y_mid - 0.18 * abs(full_beta or 0.1) - 0.05),
                            fontsize=7.5, color=RED, ha="center", va="top",
                            arrowprops=dict(arrowstyle="->", color=RED, lw=0.7))

        ax.set_xticks(xs)
        ax.set_xticklabels(prov_order, rotation=20, ha="right")
        ax.set_title(label)
        if ax is axes[0]:
            ax.set_ylabel(r"LOPO $\beta_3$ point estimate")
        ax.legend(loc="best", fontsize=7.5)

    fig.suptitle(r"Leave-one-province-out sensitivity of $\beta_3$ (EPVR × $CR_{high}$)",
                 fontsize=11.5, y=1.02)
    fig.text(0.5, -0.04,
             "Notes: Each panel drops one capture-risk-high province and re-estimates β₃. "
             "Hubei is the only CR_high province with within-province pre/post variation; "
             "dropping it collinearises EPVR × CR_high with province FE. "
             "Source: analysis/tables/table8_lopo_capture_risk.csv.",
             fontsize=7.5, color=GRAY, ha="center")
    fig.tight_layout()
    save(fig, "figure7_lopo_capture_risk")


# =========================================================================
# Figure 8 — Timing sensitivity (CS simple ATT)
# =========================================================================
def figure8_timing_sensitivity():
    df = pd.read_csv(TBL / "table9_timing_sensitivity.csv")
    outcomes = [
        ("log_rural_disposable_income", "log rural disposable income"),
        ("urban_rural_income_ratio",    "urban–rural income ratio (headline)"),
        ("log_gdp",                     "log GDP"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(11.8, 4.2), sharex=True)

    color_for = {"stable": GREEN, "fragile": RED}

    for ax, (outc, label) in zip(axes, outcomes):
        sub = df[df["outcome"] == outc].sort_values("shift_years")
        xs = sub["shift_years"].values
        ys = sub["atts_simple"].values
        ses = sub["atts_se"].values
        flags = sub["robust_flag"].values
        base = sub.loc[sub["shift_years"] == 0, "base_atts"].iloc[0]

        ax.axhline(0, color="black", lw=0.5)
        ax.axhline(base, color=GRAY, ls="--", lw=0.9,
                   label=f"Base (shift=0): {base:+.3f}")
        ax.axvline(0, color=GRAY, ls=":", lw=0.7)

        # Connector
        ax.plot(xs, ys, color=NAVY, lw=1.0, alpha=0.5, zorder=2)
        # Markers by flag
        for flag in ("stable", "fragile"):
            m = flags == flag
            if m.any():
                ax.errorbar(xs[m], ys[m], yerr=1.96*ses[m],
                            fmt="o", color=color_for[flag], ecolor=color_for[flag],
                            ms=6, lw=1.2, capsize=3, zorder=4,
                            label=f"{flag} (|z| {'<' if flag=='stable' else '≥'} 2)")

        # Annotate base value at shift=0
        ax.annotate(f"{base:+.3f}", xy=(0, base),
                    xytext=(0.4, base), fontsize=8, color=NAVY_D,
                    va="center")

        ax.set_xticks([-2, -1, 0, 1, 2])
        ax.set_xlabel("Shift in treatment year (years)")
        ax.set_title(label, fontweight="bold" if "headline" in label else "normal")
        if ax is axes[0]:
            ax.set_ylabel("Callaway–Sant'Anna simple ATT")

        # de-duplicate legend
        handles, labels = ax.get_legend_handles_labels()
        seen = set(); H, L = [], []
        for h, l in zip(handles, labels):
            if l in seen: continue
            seen.add(l); H.append(h); L.append(l)
        ax.legend(H, L, loc="best", fontsize=7.5)

    fig.suptitle("Timing sensitivity of CS simple ATT to ±2-year shifts in treatment date",
                 fontsize=11.5, y=1.02)
    fig.text(0.5, -0.04,
             "Notes: Each panel shifts the first-treated year by Δ∈{−2,…,+2}. "
             "Green = stable (|z vs base| < 2); red = fragile (|z| ≥ 2). "
             "Source: analysis/tables/table9_timing_sensitivity.csv.",
             fontsize=7.5, color=GRAY, ha="center")
    fig.tight_layout()
    save(fig, "figure8_timing_sensitivity")


# ---- Driver ---------------------------------------------------------------
if __name__ == "__main__":
    print(f"OUT = {OUT}")
    print("→ figure4_event_study")
    figure4_event_study()
    print("→ figure5_bsi_heterogeneity")
    figure5_bsi_heterogeneity()
    print("→ figure6_capture_risk")
    figure6_capture_risk()
    print("→ figure7_lopo_capture_risk")
    figure7_lopo_capture_risk()
    print("→ figure8_timing_sensitivity")
    figure8_timing_sensitivity()
    print("DONE.")
