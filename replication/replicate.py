"""
Replication of:
"AI is simultaneously aiding and replacing workers, wage data suggest"
J. Scott Davis, Federal Reserve Bank of Dallas
Published: February 24, 2026
https://www.dallasfed.org/research/economics/2026/0224

This script replicates the five charts and regression analysis from the article
using publicly available data from:
- Felten, Raj, and Seamans (2021) AI Occupational Exposure Index (AIOE/AIIE)
- Bureau of Labor Statistics QCEW (Quarterly Census of Employment and Wages)
- Bureau of Labor Statistics OEWS (Occupational Employment and Wage Statistics)
"""

import os
import glob
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import statsmodels.api as sm

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ChatGPT release: November 30, 2022 → use Q4 2022 as baseline
BASELINE_YEAR = 2022
BASELINE_QTR = 4

# Dallas Fed color palette (approximation)
COLORS = {
    "dark_blue": "#003366",
    "teal": "#007A7A",
    "light_blue": "#4A90D9",
    "red": "#C0392B",
    "gray": "#7F8C8D",
    "orange": "#E67E22",
}

plt.rcParams.update({
    "figure.figsize": (10, 6),
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
})


# ===========================================================================
# PART 1: Load AIOE / AIIE data
# ===========================================================================
def load_aioe():
    """Load occupation-level AI exposure scores."""
    df = pd.read_excel(
        os.path.join(DATA_DIR, "AIOE_DataAppendix.xlsx"),
        sheet_name="Appendix A",
    )
    df.columns = ["soc_code", "occ_title", "aioe"]
    # Create clean 6-digit code (no hyphen)
    df["occ_code_clean"] = df["soc_code"].str.replace("-", "")
    return df


def load_aiie():
    """Load industry-level AI exposure scores."""
    df = pd.read_excel(
        os.path.join(DATA_DIR, "AIOE_DataAppendix.xlsx"),
        sheet_name="Appendix B",
    )
    df.columns = ["naics", "industry_title", "aiie"]
    df["naics"] = df["naics"].astype(str).str.strip()
    return df


# ===========================================================================
# PART 2: Load and process QCEW data (industry-level employment & wages)
# ===========================================================================
def load_qcew():
    """Load all downloaded QCEW quarterly files for national data."""
    qcew_dir = os.path.join(DATA_DIR, "qcew")
    frames = []
    for fpath in sorted(glob.glob(os.path.join(qcew_dir, "us_*.csv"))):
        try:
            df = pd.read_csv(fpath, dtype=str)
            if len(df) > 10:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        raise FileNotFoundError("No QCEW data found")
    qcew = pd.concat(frames, ignore_index=True)

    # Convert numeric columns
    num_cols = [
        "month1_emplvl", "month2_emplvl", "month3_emplvl",
        "total_qtrly_wages", "avg_wkly_wage", "qtrly_estabs",
    ]
    for c in num_cols:
        qcew[c] = pd.to_numeric(qcew[c], errors="coerce")

    qcew["year"] = pd.to_numeric(qcew["year"], errors="coerce")
    qcew["qtr"] = pd.to_numeric(qcew["qtr"], errors="coerce")

    # Average monthly employment for the quarter
    qcew["avg_emp"] = qcew[["month1_emplvl", "month2_emplvl", "month3_emplvl"]].mean(
        axis=1
    )

    # Filter: private sector (own_code=5), 4-digit NAICS (agglvl_code=54)
    # Also keep total private (agglvl_code=51, industry_code=10)
    qcew["own_code"] = qcew["own_code"].str.strip()
    qcew["agglvl_code"] = qcew["agglvl_code"].str.strip()
    qcew["industry_code"] = qcew["industry_code"].str.strip()

    # Total private sector (agglvl_code 11 = national, supersector level)
    total_priv = qcew[
        (qcew["own_code"] == "5") & (qcew["industry_code"] == "10")
    ].copy()

    # 4-digit NAICS, private sector (agglvl_code 16 = national, 4-digit NAICS)
    ind_4digit = qcew[
        (qcew["own_code"] == "5")
        & (qcew["agglvl_code"] == "16")
    ].copy()

    return total_priv, ind_4digit


def merge_qcew_aiie(ind_4digit, aiie):
    """Merge QCEW 4-digit NAICS data with AIIE scores."""
    aiie_str = aiie.copy()
    aiie_str["naics"] = aiie_str["naics"].astype(str).str.strip()
    merged = ind_4digit.merge(
        aiie_str[["naics", "aiie"]],
        left_on="industry_code",
        right_on="naics",
        how="inner",
    )
    return merged


# ===========================================================================
# PART 3: Load OEWS data (occupation-level wages)
# ===========================================================================
def load_oews_2024():
    """Load 2024 OEWS national data from flat file extract."""
    path = os.path.join(DATA_DIR, "oews_2024_national.csv")
    df = pd.read_csv(path, dtype={"occ_code": str})
    return df


def load_oews_historical(year):
    """Load historical OEWS national data from Excel download."""
    path = os.path.join(DATA_DIR, f"oews_{year}_national.csv")
    df = pd.read_csv(path, dtype={"occ_code": str, "occ_code_clean": str})
    return df


# ===========================================================================
# CHART 1: Employment trends — AI-exposed sectors vs. broader economy
# ===========================================================================
def chart1_employment_trends(total_priv, merged_qcew, aiie):
    """
    Index employment in AI-exposed industries (top 10%) and total economy
    to 100 at Q4 2022 (ChatGPT release).
    """
    print("\n=== Chart 1: Employment Trends ===")

    # Identify top 10% AI-exposed 4-digit NAICS industries
    threshold = aiie["aiie"].quantile(0.90)
    top_ai_industries = [str(n) for n in aiie[aiie["aiie"] >= threshold]["naics"].tolist()]
    print(f"  Top 10% AI-exposed industries (AIIE >= {threshold:.3f}): {len(top_ai_industries)}")
    print(f"  Sample: {top_ai_industries[:5]}")

    # Computer systems design (NAICS 5415)
    cs_design = merged_qcew[merged_qcew["industry_code"] == "5415"].copy()

    # Top 10% AI-exposed aggregate
    top_ai = merged_qcew[merged_qcew["industry_code"].isin(top_ai_industries)].copy()
    top_ai_agg = (
        top_ai.groupby(["year", "qtr"])
        .agg(avg_emp=("avg_emp", "sum"))
        .reset_index()
    )

    # Total private economy
    total_ts = total_priv[["year", "qtr", "avg_emp"]].copy()

    # Create time index
    for df in [total_ts, top_ai_agg, cs_design]:
        df["time"] = df["year"] + (df["qtr"] - 1) / 4

    # Index to Q4 2022 = 100
    def index_to_baseline(df, col="avg_emp"):
        if len(df) == 0:
            df["index"] = pd.Series(dtype=float)
            return df
        baseline = df[(df["year"] == BASELINE_YEAR) & (df["qtr"] == BASELINE_QTR)][col]
        if len(baseline) == 0:
            baseline = df[(df["year"] == 2022) & (df["qtr"] == 3)][col]
        if len(baseline) == 0:
            df["index"] = pd.Series(dtype=float)
            return df
        base_val = baseline.values[0]
        df["index"] = (df[col] / base_val) * 100
        return df

    total_ts = index_to_baseline(total_ts)
    top_ai_agg = index_to_baseline(top_ai_agg)
    cs_design = index_to_baseline(cs_design)

    # Filter to post-2019
    total_ts = total_ts[total_ts["year"] >= 2019]
    top_ai_agg = top_ai_agg[top_ai_agg["year"] >= 2019]
    cs_design = cs_design[cs_design["year"] >= 2019]

    # Print key statistics
    latest_total = total_ts.iloc[-1]["index"] if len(total_ts) > 0 and "index" in total_ts.columns else None
    latest_top_ai = top_ai_agg.iloc[-1]["index"] if len(top_ai_agg) > 0 and "index" in top_ai_agg.columns else None
    latest_cs = cs_design.iloc[-1]["index"] if len(cs_design) > 0 and "index" in cs_design.columns else None
    if latest_total is not None:
        print(f"  Latest total employment index: {latest_total:.1f}")
    if latest_top_ai is not None:
        print(f"  Latest top 10% AI-exposed index: {latest_top_ai:.1f}")
    if latest_cs is not None:
        print(f"  Latest computer systems design index: {latest_cs:.1f}")

    # Plot
    fig, ax = plt.subplots()
    if "index" in total_ts.columns and total_ts["index"].notna().any():
        ax.plot(total_ts["time"], total_ts["index"], color=COLORS["dark_blue"],
                linewidth=2, label="Total private employment")
    if "index" in top_ai_agg.columns and top_ai_agg["index"].notna().any():
        ax.plot(top_ai_agg["time"], top_ai_agg["index"], color=COLORS["red"],
                linewidth=2, label="Top 10% AI-exposed industries")
    if "index" in cs_design.columns and cs_design["index"].notna().any():
        ax.plot(cs_design["time"], cs_design["index"], color=COLORS["teal"],
                linewidth=2, linestyle="--", label="Computer systems design (NAICS 5415)")

    ax.axvline(x=2022.75, color="gray", linestyle=":", alpha=0.7)
    ax.annotate("ChatGPT\nrelease", xy=(2022.75, ax.get_ylim()[0]),
                xytext=(2022.75, ax.get_ylim()[0] + 2),
                fontsize=9, ha="center", color="gray")

    ax.axhline(y=100, color="gray", linestyle="-", alpha=0.3)
    ax.set_xlabel("")
    ax.set_ylabel("Employment index (Q4 2022 = 100)")
    ax.set_title("Chart 1: Employment Trends in AI-Exposed Sectors\nvs. Broader Economy",
                 fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", frameon=False)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "chart1_employment_trends.png"), bbox_inches="tight")
    plt.close(fig)
    print("  Saved chart1_employment_trends.png")


# ===========================================================================
# CHART 2: Wage growth comparison
# ===========================================================================
def chart2_wage_growth(total_priv, merged_qcew, aiie):
    """
    Compare average weekly wage growth: national average, computer systems
    design, and top 10% AI-exposed industries.
    """
    print("\n=== Chart 2: Wage Growth Comparison ===")

    threshold = aiie["aiie"].quantile(0.90)
    top_ai_industries = [str(n) for n in aiie[aiie["aiie"] >= threshold]["naics"].tolist()]

    # Computer systems design
    cs_design = merged_qcew[merged_qcew["industry_code"] == "5415"].copy()

    # Top 10% AI-exposed — employment-weighted average weekly wage
    top_ai = merged_qcew[merged_qcew["industry_code"].isin(top_ai_industries)].copy()
    top_ai_agg = (
        top_ai.groupby(["year", "qtr"])
        .apply(
            lambda g: pd.Series({
                "avg_wkly_wage": np.average(g["avg_wkly_wage"], weights=g["avg_emp"])
                if g["avg_emp"].sum() > 0 else np.nan,
            })
        )
        .reset_index()
    )

    total_ts = total_priv[["year", "qtr", "avg_wkly_wage"]].copy()

    # Apply 4-quarter moving average to remove seasonality
    for df in [total_ts, top_ai_agg, cs_design]:
        df.sort_values(["year", "qtr"], inplace=True)
        df["time"] = df["year"] + (df["qtr"] - 1) / 4
        df["avg_wkly_wage_ma"] = df["avg_wkly_wage"].rolling(4, min_periods=4).mean()

    # Compute cumulative growth from Q4 2022 using smoothed wages
    for label, df in [("total", total_ts), ("top_ai", top_ai_agg), ("cs_design", cs_design)]:
        baseline = df[(df["year"] == BASELINE_YEAR) & (df["qtr"] == BASELINE_QTR)]
        if len(baseline) == 0:
            baseline = df[(df["year"] == 2022) & (df["qtr"] == 3)]
        if len(baseline) > 0:
            base_val = baseline["avg_wkly_wage_ma"].values[0]
            if pd.notna(base_val) and base_val > 0:
                df["wage_growth_pct"] = ((df["avg_wkly_wage_ma"] / base_val) - 1) * 100

    total_ts = total_ts[total_ts["year"] >= 2020].dropna(subset=["wage_growth_pct"])
    top_ai_agg = top_ai_agg[top_ai_agg["year"] >= 2020].dropna(subset=["wage_growth_pct"])
    cs_design = cs_design[cs_design["year"] >= 2020].dropna(subset=["wage_growth_pct"])

    # Print key statistics
    if "wage_growth_pct" in total_ts.columns and len(total_ts) > 0:
        latest = total_ts.iloc[-1]
        print(f"  National wage growth since Q4 2022: {latest['wage_growth_pct']:.1f}%")
    if "wage_growth_pct" in top_ai_agg.columns and len(top_ai_agg) > 0:
        latest = top_ai_agg.iloc[-1]
        print(f"  Top 10% AI-exposed wage growth: {latest['wage_growth_pct']:.1f}%")
    if "wage_growth_pct" in cs_design.columns and len(cs_design) > 0:
        latest = cs_design.iloc[-1]
        print(f"  Computer systems design wage growth: {latest['wage_growth_pct']:.1f}%")

    # Plot
    fig, ax = plt.subplots()

    def safe_plot(df, label, color, ls="-"):
        if "wage_growth_pct" in df.columns and len(df) > 0:
            ax.plot(df["time"], df["wage_growth_pct"], color=color, linewidth=2,
                    linestyle=ls, label=label)

    safe_plot(total_ts, "National average", COLORS["dark_blue"])
    safe_plot(top_ai_agg, "Top 10% AI-exposed industries", COLORS["red"])
    safe_plot(cs_design, "Computer systems design", COLORS["teal"], ls="--")

    ax.axvline(x=2022.75, color="gray", linestyle=":", alpha=0.7)
    ax.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
    ax.set_xlabel("")
    ax.set_ylabel("Cumulative wage growth since Q4 2022 (%)\n(4-quarter moving average)")
    ax.set_title(
        "Chart 2: Average Weekly Wage Growth\nNational vs. AI-Exposed Industries",
        fontsize=13, fontweight="bold",
    )
    ax.legend(loc="upper left", frameon=False)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "chart2_wage_growth.png"), bbox_inches="tight")
    plt.close(fig)
    print("  Saved chart2_wage_growth.png")


# ===========================================================================
# CHART 3: Scatterplot — post-2022 wage growth vs. AI exposure (occupations)
# ===========================================================================
def chart3_wage_growth_scatter(oews_2022, oews_2024, aioe):
    """
    Scatterplot of post-2022 wage growth against AI exposure across
    ~205 occupations.
    """
    print("\n=== Chart 3: Wage Growth vs. AI Exposure (Occupations) ===")

    # Merge 2022 and 2024 OEWS data on occupation code
    df22 = oews_2022[["occ_code_clean", "occ_title", "a_mean"]].copy()
    df22.columns = ["occ_code", "occ_title", "a_mean_2022"]

    df24 = oews_2024[["occ_code", "a_mean"]].copy()
    df24.columns = ["occ_code", "a_mean_2024"]
    df24["occ_code"] = df24["occ_code"].astype(str).str.strip()

    merged = df22.merge(df24, on="occ_code", how="inner")
    merged = merged.dropna(subset=["a_mean_2022", "a_mean_2024"])
    merged = merged[(merged["a_mean_2022"] > 0) & (merged["a_mean_2024"] > 0)]

    # Compute percentage wage growth
    merged["wage_growth"] = (
        (merged["a_mean_2024"] - merged["a_mean_2022"]) / merged["a_mean_2022"]
    ) * 100

    # Merge with AIOE
    aioe_clean = aioe[["occ_code_clean", "aioe"]].copy()
    aioe_clean.columns = ["occ_code", "aioe"]
    merged = merged.merge(aioe_clean, on="occ_code", how="inner")

    print(f"  Matched occupations: {len(merged)}")
    print(f"  Mean wage growth: {merged['wage_growth'].mean():.1f}%")
    print(f"  Median wage growth: {merged['wage_growth'].median():.1f}%")

    # Regression: wage_growth ~ aioe
    X = sm.add_constant(merged["aioe"])
    y = merged["wage_growth"]
    model = sm.OLS(y, X).fit()
    print(f"  OLS coefficient on AIOE: {model.params['aioe']:.3f} (p={model.pvalues['aioe']:.3f})")

    # Plot
    fig, ax = plt.subplots()
    ax.scatter(merged["aioe"], merged["wage_growth"], alpha=0.4, s=30,
               color=COLORS["dark_blue"], edgecolor="white", linewidth=0.3)

    # Trend line
    x_range = np.linspace(merged["aioe"].min(), merged["aioe"].max(), 100)
    y_pred = model.predict(sm.add_constant(x_range))
    ax.plot(x_range, y_pred, color=COLORS["red"], linewidth=2, label="OLS fit")

    ax.set_xlabel("AI Occupational Exposure (AIOE)")
    ax.set_ylabel("Wage growth, May 2022 to May 2024 (%)")
    ax.set_title(
        "Chart 3: Post-2022 Wage Growth vs. AI Exposure\nAcross Occupations",
        fontsize=13, fontweight="bold",
    )
    ax.legend(loc="upper right", frameon=False)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "chart3_wage_ai_scatter.png"), bbox_inches="tight")
    plt.close(fig)
    print("  Saved chart3_wage_ai_scatter.png")

    return merged


# ===========================================================================
# CHART 4: Experience premium vs. AI exposure
# ===========================================================================
def chart4_experience_premium(oews_2024, aioe):
    """
    Scatterplot of the experience premium (ratio of 75th to 25th percentile
    wages) against AI exposure for each occupation.

    The article defines experience premium as the gap between experienced
    and entry-level workers. We approximate this using OEWS wage percentiles:
    experience_premium = (a_pct75 - a_pct25) / a_pct25 * 100
    """
    print("\n=== Chart 4: Experience Premium vs. AI Exposure ===")

    df = oews_2024.copy()
    df["occ_code"] = df["occ_code"].astype(str).str.strip()

    # Compute experience premium
    df = df.dropna(subset=["a_pct75", "a_pct25"])
    df = df[(df["a_pct25"] > 0) & (df["a_pct75"] > 0)]
    df["exp_premium"] = ((df["a_pct75"] - df["a_pct25"]) / df["a_pct25"]) * 100

    # Merge with AIOE
    aioe_clean = aioe[["occ_code_clean", "aioe"]].copy()
    aioe_clean.columns = ["occ_code", "aioe"]
    merged = df.merge(aioe_clean, on="occ_code", how="inner")

    print(f"  Matched occupations: {len(merged)}")
    print(f"  Median experience premium: {merged['exp_premium'].median():.0f}%")
    print(f"  Range: {merged['exp_premium'].min():.0f}% to {merged['exp_premium'].max():.0f}%")

    # Regression
    X = sm.add_constant(merged["aioe"])
    y = merged["exp_premium"]
    model = sm.OLS(y, X).fit()
    print(f"  OLS coefficient on AIOE: {model.params['aioe']:.3f} (p={model.pvalues['aioe']:.3f})")

    # Plot
    fig, ax = plt.subplots()
    ax.scatter(merged["aioe"], merged["exp_premium"], alpha=0.4, s=30,
               color=COLORS["dark_blue"], edgecolor="white", linewidth=0.3)

    # Trend line
    x_range = np.linspace(merged["aioe"].min(), merged["aioe"].max(), 100)
    y_pred = model.predict(sm.add_constant(x_range))
    ax.plot(x_range, y_pred, color=COLORS["red"], linewidth=2, label="OLS fit")

    ax.set_xlabel("AI Occupational Exposure (AIOE)")
    ax.set_ylabel("Experience premium (%)")
    ax.set_title(
        "Chart 4: Experience Premium vs. AI Exposure\nAcross Occupations",
        fontsize=13, fontweight="bold",
    )
    ax.legend(loc="upper right", frameon=False)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "chart4_experience_premium.png"), bbox_inches="tight")
    plt.close(fig)
    print("  Saved chart4_experience_premium.png")

    return merged


# ===========================================================================
# CHART 5 + REGRESSION: Wage growth effects conditional on experience premium
# ===========================================================================
def chart5_conditional_effects(oews_2022, oews_2024, aioe):
    """
    Regression of post-2022 wage growth on AI exposure interacted with
    experience premium. Then plot estimated effects at different levels
    of the experience premium.

    Model: wage_growth = β₀ + β₁·AIOE + β₂·exp_premium + β₃·AIOE×exp_premium + ε

    The article finds:
    - At median experience premium (40%): ~0.05 pp decline per 1-SD AIOE increase
    - At 0% experience premium: 0.28 pp reduction
    - At 90th pctile experience premium: 0.2 pp increase
    """
    print("\n=== Chart 5 + Regression: Conditional Effects ===")

    # Merge 2022 and 2024 wages
    df22 = oews_2022[["occ_code_clean", "a_mean"]].copy()
    df22.columns = ["occ_code", "a_mean_2022"]

    df24 = oews_2024[["occ_code", "a_mean", "a_pct25", "a_pct75"]].copy()
    df24["occ_code"] = df24["occ_code"].astype(str).str.strip()

    merged = df22.merge(df24, on="occ_code", how="inner")
    merged = merged.dropna(subset=["a_mean_2022", "a_mean", "a_pct25", "a_pct75"])
    merged = merged[
        (merged["a_mean_2022"] > 0)
        & (merged["a_mean"] > 0)
        & (merged["a_pct25"] > 0)
        & (merged["a_pct75"] > 0)
    ]

    # Wage growth
    merged["wage_growth"] = (
        (merged["a_mean"] - merged["a_mean_2022"]) / merged["a_mean_2022"]
    ) * 100

    # Experience premium
    merged["exp_premium"] = (
        (merged["a_pct75"] - merged["a_pct25"]) / merged["a_pct25"]
    ) * 100

    # Merge with AIOE
    aioe_clean = aioe[["occ_code_clean", "aioe"]].copy()
    aioe_clean.columns = ["occ_code", "aioe"]
    merged = merged.merge(aioe_clean, on="occ_code", how="inner")

    print(f"  Observations: {len(merged)}")

    # Interaction term
    merged["aioe_x_exp"] = merged["aioe"] * merged["exp_premium"]

    # Regression
    X = merged[["aioe", "exp_premium", "aioe_x_exp"]]
    X = sm.add_constant(X)
    y = merged["wage_growth"]
    model = sm.OLS(y, X).fit()

    print("\n  Regression results:")
    print(f"  {'Variable':<20} {'Coef':>10} {'Std Err':>10} {'t':>8} {'P>|t|':>8}")
    print(f"  {'-'*56}")
    for var in model.params.index:
        print(
            f"  {var:<20} {model.params[var]:>10.4f} {model.bse[var]:>10.4f} "
            f"{model.tvalues[var]:>8.3f} {model.pvalues[var]:>8.4f}"
        )
    print(f"\n  R-squared: {model.rsquared:.4f}")
    print(f"  N: {int(model.nobs)}")

    # Compute marginal effect of AIOE at different experience premium levels
    # ∂(wage_growth)/∂(AIOE) = β₁ + β₃ × exp_premium
    beta1 = model.params["aioe"]
    beta3 = model.params["aioe_x_exp"]

    exp_range = np.linspace(0, merged["exp_premium"].quantile(0.95), 200)
    marginal_effect = beta1 + beta3 * exp_range

    # Confidence intervals for marginal effect
    # Var(β₁ + β₃·x) = Var(β₁) + x²·Var(β₃) + 2x·Cov(β₁,β₃)
    vcov = model.cov_params()
    var_b1 = vcov.loc["aioe", "aioe"]
    var_b3 = vcov.loc["aioe_x_exp", "aioe_x_exp"]
    cov_b1_b3 = vcov.loc["aioe", "aioe_x_exp"]
    se_marginal = np.sqrt(var_b1 + exp_range**2 * var_b3 + 2 * exp_range * cov_b1_b3)
    ci_lo = marginal_effect - 1.96 * se_marginal
    ci_hi = marginal_effect + 1.96 * se_marginal

    # Scale by 1 standard deviation of AIOE for interpretation
    aioe_sd = merged["aioe"].std()
    marginal_1sd = marginal_effect * aioe_sd
    ci_lo_1sd = ci_lo * aioe_sd
    ci_hi_1sd = ci_hi * aioe_sd

    # Key statistics from article
    median_exp = merged["exp_premium"].median()
    p90_exp = merged["exp_premium"].quantile(0.90)
    effect_at_median = (beta1 + beta3 * median_exp) * aioe_sd
    effect_at_0 = beta1 * aioe_sd
    effect_at_p90 = (beta1 + beta3 * p90_exp) * aioe_sd

    print(f"\n  AIOE std dev: {aioe_sd:.3f}")
    print(f"  Median experience premium: {median_exp:.0f}%")
    print(f"  90th pctile experience premium: {p90_exp:.0f}%")
    print(f"\n  Effect of 1-SD AIOE increase on wage growth (pp):")
    print(f"    At 0% experience premium:      {effect_at_0:.3f}")
    print(f"    At median experience premium:   {effect_at_median:.3f}")
    print(f"    At 90th pctile exp premium:     {effect_at_p90:.3f}")

    # Plot
    fig, ax = plt.subplots()
    ax.plot(exp_range, marginal_1sd, color=COLORS["dark_blue"], linewidth=2)
    ax.fill_between(exp_range, ci_lo_1sd, ci_hi_1sd, alpha=0.2, color=COLORS["light_blue"])
    ax.axhline(y=0, color="gray", linestyle="-", alpha=0.5)

    # Mark key points
    ax.plot(median_exp, effect_at_median, "o", color=COLORS["red"], markersize=8, zorder=5)
    ax.annotate(
        f"Median ({median_exp:.0f}%)\n{effect_at_median:.2f} pp",
        xy=(median_exp, effect_at_median),
        xytext=(median_exp + 15, effect_at_median - 0.3),
        fontsize=9,
        arrowprops=dict(arrowstyle="->", color="gray"),
    )

    ax.set_xlabel("Experience premium (%)")
    ax.set_ylabel("Effect of 1-SD increase in AIOE\non wage growth (percentage points)")
    ax.set_title(
        "Chart 5: Estimated Wage Growth Effect of AI Exposure\nConditional on Experience Premium",
        fontsize=13, fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "chart5_conditional_effects.png"), bbox_inches="tight")
    plt.close(fig)
    print("  Saved chart5_conditional_effects.png")

    return model


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("=" * 70)
    print("Replication: 'AI is simultaneously aiding and replacing workers,")
    print("              wage data suggest'")
    print("  J. Scott Davis, Federal Reserve Bank of Dallas, Feb 24, 2026")
    print("=" * 70)

    # Load AI exposure data
    print("\nLoading AI exposure indices...")
    aioe = load_aioe()
    aiie = load_aiie()
    print(f"  AIOE: {len(aioe)} occupations")
    print(f"  AIIE: {len(aiie)} industries")

    # Load QCEW data
    print("\nLoading QCEW data...")
    total_priv, ind_4digit = load_qcew()
    merged_qcew = merge_qcew_aiie(ind_4digit, aiie)
    print(f"  Total private observations: {len(total_priv)}")
    print(f"  4-digit NAICS with AIIE: {len(merged_qcew)}")
    print(f"  Unique industries: {merged_qcew['industry_code'].nunique()}")

    quarters = merged_qcew.groupby(["year", "qtr"]).size().reset_index()
    print(f"  Quarters: {quarters['year'].min()}-Q{quarters['qtr'].min()} to "
          f"{quarters['year'].max()}-Q{quarters['qtr'].max()}")

    # Load OEWS data
    print("\nLoading OEWS data...")
    oews_2024 = load_oews_2024()
    oews_2022 = load_oews_historical(2022)
    print(f"  OEWS 2024: {len(oews_2024)} occupations")
    print(f"  OEWS 2022: {len(oews_2022)} occupations")

    # Generate charts
    chart1_employment_trends(total_priv, merged_qcew, aiie)
    chart2_wage_growth(total_priv, merged_qcew, aiie)
    scatter_data = chart3_wage_growth_scatter(oews_2022, oews_2024, aioe)
    exp_data = chart4_experience_premium(oews_2024, aioe)
    regression_model = chart5_conditional_effects(oews_2022, oews_2024, aioe)

    print("\n" + "=" * 70)
    print("Replication complete. Charts saved to:", OUTPUT_DIR)
    print("=" * 70)


if __name__ == "__main__":
    main()
