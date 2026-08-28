"""
Agentic Storefront -- Framing A Comparison Charts

Two charts, two honest claims:
  1. Upsell uplift on converting buyers (apples-to-apples AOV, 26 scenarios)
  2. Revenue Per Buyer across all 52 attempts (fixed pricing leaves revenue on the table)

Usage:
    python generate_comparison_chart.py
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# Brand colors
COLOR_FIXED = "#9E9E9E"       # Grey - baseline
COLOR_AI = "#3F51B5"          # Indigo - AI upsell
COLOR_ACCENT = "#4CAF50"      # Green - uplift callout
COLOR_WARN = "#FF5722"        # Deep orange - conversion gap
COLOR_BG = "#FAFAFA"


def setup_style():
    plt.rcParams.update({
        "figure.facecolor": COLOR_BG,
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": "#E0E0E0",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "figure.titlesize": 15,
        "figure.titleweight": "bold",
    })


def generate_framing_a_dashboard(report: dict, output_dir: Path) -> Path:
    """Two-panel dashboard: Cut 1 (AOV) + Cut 2 (RPB)."""
    c1 = report["metrics"]["cut1_upsell_uplift"]
    c2 = report["metrics"]["cut2_revenue_per_buyer"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(
        "Framing A: AI Upsell Engine vs Take-It-or-Leave-It Fixed Pricing",
        fontsize=15, fontweight="bold", y=1.02,
    )

    labels = ["Fixed Price", "AI + Upsell"]
    x = np.arange(len(labels))
    bw = 0.45

    # ── Panel 1: Cut 1 — AOV on converting buyers ──
    aov = [c1["fixed_aov_rupees"], c1["upsell_aov_rupees"]]
    bars1 = ax1.bar(x, aov, bw, color=[COLOR_FIXED, COLOR_AI],
                    edgecolor="white", linewidth=2, zorder=3)
    for bar, val in zip(bars1, aov):
        ax1.text(bar.get_x() + bw / 2, bar.get_height() + max(aov) * 0.02,
                 f"Rs.{val:,.0f}", ha="center", va="bottom",
                 fontsize=13, fontweight="bold")
    ax1.annotate(
        f"+{c1['uplift_pct']:.0f}%",
        xy=(1, aov[1]), xytext=(1.35, aov[0] + (aov[1] - aov[0]) * 0.5),
        fontsize=15, fontweight="bold", color=COLOR_ACCENT,
        arrowprops=dict(arrowstyle="->", color=COLOR_ACCENT, lw=2),
        ha="left", va="center",
    )
    ax1.set_title(
        f"Cut 1: AOV on Converting Buyers (+{c1['uplift_pct']:.0f}%)\n"
        f"({c1['scenario_count']} scenarios where both conditions convert)",
        fontsize=11, fontweight="bold",
    )
    ax1.set_ylabel("Avg Order Value (Rs.)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylim(0, max(aov) * 1.3)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # ── Panel 2: Cut 2 — Revenue Per Buyer across all 52 ──
    rpb = [c2["fixed_rpb_rupees"], c2["upsell_rpb_rupees"]]
    bars2 = ax2.bar(x, rpb, bw, color=[COLOR_FIXED, COLOR_AI],
                    edgecolor="white", linewidth=2, zorder=3)
    for bar, val in zip(bars2, rpb):
        ax2.text(bar.get_x() + bw / 2, bar.get_height() + max(rpb) * 0.02,
                 f"Rs.{val:,.0f}", ha="center", va="bottom",
                 fontsize=13, fontweight="bold",
                 color=COLOR_AI if val == max(rpb) else "#333")
    ax2.annotate(
        f"+{c2['rpb_uplift_pct']:.0f}%",
        xy=(1, rpb[1]), xytext=(1.35, rpb[0] + (rpb[1] - rpb[0]) * 0.5),
        fontsize=15, fontweight="bold", color=COLOR_ACCENT,
        arrowprops=dict(arrowstyle="->", color=COLOR_ACCENT, lw=2),
        ha="left", va="center",
    )
    # Conversion rate annotation below bars
    ax2.text(0, -max(rpb) * 0.12,
             f"{c2['fixed_conversion_pct']:.0f}% conversion\n({c2['fixed_successful']}/{c2['total_attempts']} buyers)",
             ha="center", va="top", fontsize=9, color="#666")
    ax2.text(1, -max(rpb) * 0.12,
             f"{c2['upsell_conversion_pct']:.0f}% conversion\n({c2['upsell_successful']}/{c2['total_attempts']} buyers)",
             ha="center", va="top", fontsize=9, color="#666")

    ax2.set_title(
        f"Cut 2: Revenue Per Buyer, All {c2['total_attempts']} Attempts (+{c2['rpb_uplift_pct']:.0f}%)\n"
        f"(Fixed pricing loses {c2['fixed_walk_aways']} of {c2['total_attempts']} buyers)",
        fontsize=11, fontweight="bold",
    )
    ax2.set_ylabel("Revenue Per Buyer Attempt (Rs.)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylim(-max(rpb) * 0.2, max(rpb) * 1.3)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fig.tight_layout(rect=[0, 0.05, 1, 0.95])
    path = output_dir / "framing_a_dashboard.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def generate_headline_chart(report: dict, output_dir: Path) -> Path:
    """Single hero chart for pitch: both cuts stacked vertically."""
    c1 = report["metrics"]["cut1_upsell_uplift"]
    c2 = report["metrics"]["cut2_revenue_per_buyer"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 10))
    fig.suptitle(
        "AI Upsell Engine: Isolating the Revenue Impact",
        fontsize=16, fontweight="bold", y=0.98,
    )

    labels = ["Fixed Price\n(No AI)", "AI Upsell\nEngine"]
    x = np.arange(len(labels))
    bw = 0.45

    # ── Top: Cut 1 ──
    aov = [c1["fixed_aov_rupees"], c1["upsell_aov_rupees"]]
    bars1 = ax1.bar(x, aov, bw, color=[COLOR_FIXED, COLOR_AI],
                    edgecolor="white", linewidth=2, zorder=3)
    for bar, val in zip(bars1, aov):
        ax1.text(bar.get_x() + bw / 2, bar.get_height() + max(aov) * 0.025,
                 f"Rs.{val:,.0f}", ha="center", va="bottom",
                 fontsize=14, fontweight="bold")
    ax1.annotate(
        f"+{c1['uplift_pct']:.0f}% AOV\non buyers who\npurchase either way",
        xy=(1, aov[1]), xytext=(1.4, aov[0] + (aov[1] - aov[0]) * 0.45),
        fontsize=12, fontweight="bold", color=COLOR_ACCENT,
        arrowprops=dict(arrowstyle="->", color=COLOR_ACCENT, lw=2,
                        connectionstyle="arc3,rad=0.15"),
        ha="left", va="center",
    )
    ax1.set_title(f"Same {c1['scenario_count']} buyers, same products -- only difference is upsell",
                  fontsize=11)
    ax1.set_ylabel("Avg Order Value (Rs.)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylim(0, max(aov) * 1.35)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # ── Bottom: Cut 2 ──
    rpb = [c2["fixed_rpb_rupees"], c2["upsell_rpb_rupees"]]
    bars2 = ax2.bar(x, rpb, bw, color=[COLOR_FIXED, COLOR_AI],
                    edgecolor="white", linewidth=2, zorder=3)
    for bar, val in zip(bars2, rpb):
        ax2.text(bar.get_x() + bw / 2, bar.get_height() + max(rpb) * 0.025,
                 f"Rs.{val:,.0f}", ha="center", va="bottom",
                 fontsize=14, fontweight="bold",
                 color=COLOR_AI if val == max(rpb) else "#666")
    ax2.annotate(
        f"+{c2['rpb_uplift_pct']:.0f}% revenue\nper buyer attempt\n"
        f"(fixed: {c2['fixed_conversion_pct']:.0f}% conv.)",
        xy=(1, rpb[1]), xytext=(1.4, rpb[0] + (rpb[1] - rpb[0]) * 0.45),
        fontsize=12, fontweight="bold", color=COLOR_ACCENT,
        arrowprops=dict(arrowstyle="->", color=COLOR_ACCENT, lw=2,
                        connectionstyle="arc3,rad=0.15"),
        ha="left", va="center",
    )
    ax2.set_title(
        f"All {c2['total_attempts']} buyer attempts -- fixed pricing fails to convert {c2['fixed_walk_aways']}",
        fontsize=11,
    )
    ax2.set_ylabel("Revenue Per Buyer (Rs.)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylim(0, max(rpb) * 1.35)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    path = output_dir / "framing_a_headline.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    setup_style()

    report_path = Path(__file__).parent / "output" / "comparison_report.json"
    if not report_path.exists():
        print("ERROR: comparison_report.json not found. Run 'python run_comparison.py' first.")
        sys.exit(1)

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    output_dir = Path(__file__).parent / "output" / "charts"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  FRAMING A CHART GENERATOR")
    print("=" * 60)

    print("\n  [1/2] Headline chart (stacked) ...", end=" ", flush=True)
    p1 = generate_headline_chart(report, output_dir)
    print("OK")

    print("  [2/2] Dashboard (side-by-side) ...", end=" ", flush=True)
    p2 = generate_framing_a_dashboard(report, output_dir)
    print("OK")

    print(f"\n  Charts saved:")
    print(f"    {p1}")
    print(f"    {p2}")
    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
