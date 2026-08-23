"""
Agentic Storefront — Chart Generator
Visualizes AOV uplift, upsell effectiveness, and GMV metrics
from the batch run output (output/metrics_report.json).

Usage:
    python generate_chart.py              # Generate all charts
    python generate_chart.py --show       # Generate and display interactively
    python generate_chart.py --format svg # Export as SVG instead of PNG

Output:
    output/charts/aov_comparison.png
    output/charts/scenario_uplift.png
    output/charts/upsell_acceptance.png
    output/charts/gmv_breakdown.png
    output/charts/dashboard.png          (combined 4-panel dashboard)
"""

import json
import sys
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend by default
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


# ── Constants ────────────────────────────────────────────────
METRICS_PATH = Path(__file__).parent / "output" / "metrics_report.json"
CHARTS_DIR = Path(__file__).parent / "output" / "charts"

# Brand colors
COLOR_PRIMARY = "#3F51B5"      # Indigo
COLOR_SECONDARY = "#FF5722"    # Deep Orange
COLOR_SUCCESS = "#4CAF50"      # Green
COLOR_WARNING = "#FFC107"      # Amber
COLOR_ACCENT = "#00BCD4"       # Cyan
COLOR_MUTED = "#9E9E9E"        # Grey
COLOR_BG = "#FAFAFA"           # Light background

COLORS_GRADIENT = ["#3F51B5", "#5C6BC0", "#7986CB", "#9FA8DA", "#C5CAE9"]
COLORS_PIE = [COLOR_SUCCESS, COLOR_SECONDARY, COLOR_MUTED]


def load_metrics(path: Path = METRICS_PATH) -> dict:
    """Load metrics report from JSON file."""
    if not path.exists():
        print(f"ERROR: Metrics file not found at {path}")
        print("Run 'python main.py batch' first to generate metrics.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def paise_to_rupees(paise: int | float) -> float:
    """Convert paise to rupees."""
    return paise / 100


def setup_style():
    """Configure matplotlib for clean, professional charts."""
    plt.rcParams.update({
        "figure.facecolor": COLOR_BG,
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": "#E0E0E0",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.titlesize": 16,
        "figure.titleweight": "bold",
    })


# ── Chart 1: AOV Comparison ─────────────────────────────────
def chart_aov_comparison(summary: dict, fmt: str = "png") -> Path:
    """Bar chart comparing AOV without vs with upsell."""
    fig, ax = plt.subplots(figsize=(8, 5))

    aov_without = paise_to_rupees(summary["avg_aov_without_upsell_paise"])
    aov_with = paise_to_rupees(summary["avg_aov_with_upsell_paise"])
    uplift_pct = summary["aov_uplift_pct"]

    bars = ax.bar(
        ["Without Upsell", "With Upsell"],
        [aov_without, aov_with],
        color=[COLOR_MUTED, COLOR_PRIMARY],
        width=0.5,
        edgecolor="white",
        linewidth=2,
        zorder=3,
    )

    # Value labels on bars
    for bar, val in zip(bars, [aov_without, aov_with]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 20,
            f"₹{val:,.0f}",
            ha="center", va="bottom",
            fontsize=14, fontweight="bold",
            color=COLOR_PRIMARY,
        )

    # Uplift annotation with arrow
    ax.annotate(
        f"+{uplift_pct:.1f}% uplift",
        xy=(1, aov_with),
        xytext=(1.35, (aov_without + aov_with) / 2),
        fontsize=13, fontweight="bold", color=COLOR_SECONDARY,
        arrowprops=dict(
            arrowstyle="->", color=COLOR_SECONDARY,
            lw=2, connectionstyle="arc3,rad=0.2",
        ),
        ha="left", va="center",
    )

    ax.set_ylabel("Average Order Value (₹)")
    ax.set_title("AOV Uplift: AI-Powered Upsell Engine")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"₹{x:,.0f}"))
    ax.set_ylim(0, aov_with * 1.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    path = CHARTS_DIR / f"aov_comparison.{fmt}"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── Chart 2: Per-Scenario Uplift ────────────────────────────
def chart_scenario_uplift(scenarios: list[dict], fmt: str = "png") -> Path:
    """Horizontal bar chart showing AOV uplift per scenario (top 20)."""
    # Filter to scenarios that had actual uplift
    uplifted = [
        s for s in scenarios
        if s["aov_uplift_pct"] > 0 and s["outcome"] == "success"
    ]
    uplifted.sort(key=lambda s: s["aov_uplift_pct"], reverse=True)
    top = uplifted[:20]

    fig, ax = plt.subplots(figsize=(10, 7))

    names = [s["name"][:35] for s in top]
    values = [s["aov_uplift_pct"] for s in top]

    # Color gradient based on uplift magnitude
    max_val = max(values) if values else 1
    colors = [
        plt.cm.RdYlGn(0.3 + 0.7 * (v / max_val))  # type: ignore[attr-defined]
        for v in values
    ]

    y_pos = np.arange(len(names))
    bars = ax.barh(y_pos, values, color=colors, edgecolor="white", linewidth=1, zorder=3)

    # Value labels
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + 5, bar.get_y() + bar.get_height() / 2,
            f"+{val:.0f}%",
            va="center", fontsize=9, fontweight="bold", color="#333",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("AOV Uplift (%)")
    ax.set_title(f"Top {len(top)} Scenarios by AOV Uplift")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    path = CHARTS_DIR / f"scenario_uplift.{fmt}"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── Chart 3: Upsell Acceptance Pie ──────────────────────────
def chart_upsell_acceptance(summary: dict, scenarios: list[dict], fmt: str = "png") -> Path:
    """Donut chart showing upsell acceptance vs decline vs failed."""
    success = [s for s in scenarios if s["outcome"] == "success"]
    accepted = len([s for s in success if s["aov_uplift_pct"] > 0])
    declined = len([s for s in success if s["aov_uplift_pct"] == 0])
    failed = len([s for s in scenarios if s["outcome"].startswith("failed")])

    fig, ax = plt.subplots(figsize=(6, 6))

    sizes = [accepted, declined, failed]
    labels = [
        f"Accepted ({accepted})",
        f"Declined ({declined})",
        f"Failed—Expected ({failed})",
    ]

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=COLORS_PIE,
        autopct="%1.0f%%", startangle=90,
        pctdistance=0.75, labeldistance=1.15,
        wedgeprops=dict(width=0.4, edgecolor="white", linewidth=2),
        textprops=dict(fontsize=10),
    )

    for t in autotexts:
        t.set_fontsize(11)
        t.set_fontweight("bold")

    # Center text
    ax.text(0, 0, f"{summary['total_scenarios']}\nScenarios",
            ha="center", va="center", fontsize=14, fontweight="bold",
            color="#333")

    ax.set_title("Upsell Acceptance Rate")

    fig.tight_layout()
    path = CHARTS_DIR / f"upsell_acceptance.{fmt}"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── Chart 4: GMV Breakdown ──────────────────────────────────
def chart_gmv_breakdown(summary: dict, scenarios: list[dict], fmt: str = "png") -> Path:
    """Stacked bar showing GMV composition: base vs upsell contribution."""
    success = [s for s in scenarios if s["outcome"] == "success"]

    total_base = sum(paise_to_rupees(s["cart_without_upsell"]) for s in success)
    total_with = sum(paise_to_rupees(s["cart_with_upsell"]) for s in success)
    upsell_contribution = total_with - total_base

    fig, ax = plt.subplots(figsize=(8, 5))

    categories = ["Base GMV", "Upsell Contribution", "Total GMV"]
    values = [total_base, upsell_contribution, total_with]
    colors = [COLOR_MUTED, COLOR_SUCCESS, COLOR_PRIMARY]

    bars = ax.bar(categories, values, color=colors, width=0.5,
                  edgecolor="white", linewidth=2, zorder=3)

    # Value labels
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 200,
            f"₹{val:,.0f}",
            ha="center", va="bottom",
            fontsize=12, fontweight="bold", color="#333",
        )

    # Add percentage annotation for upsell contribution
    if total_base > 0:
        upsell_pct = (upsell_contribution / total_base) * 100
        ax.annotate(
            f"+₹{upsell_contribution:,.0f}\n({upsell_pct:.1f}% of base)",
            xy=(1, upsell_contribution),
            xytext=(1.4, upsell_contribution * 1.3),
            fontsize=11, fontweight="bold", color=COLOR_SUCCESS,
            arrowprops=dict(arrowstyle="->", color=COLOR_SUCCESS, lw=1.5),
            ha="left", va="center",
        )

    ax.set_ylabel("Revenue (₹)")
    ax.set_title("GMV Composition: Base vs Upsell Revenue")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"₹{x:,.0f}"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    path = CHARTS_DIR / f"gmv_breakdown.{fmt}"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── Combined Dashboard ──────────────────────────────────────
def chart_dashboard(summary: dict, scenarios: list[dict], fmt: str = "png") -> Path:
    """4-panel combined dashboard."""
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(
        "Agentic Storefront — AOV & Upsell Performance Dashboard",
        fontsize=18, fontweight="bold", y=0.98,
    )

    # ── Panel 1: AOV Comparison (top-left) ──
    ax1 = fig.add_subplot(2, 2, 1)
    aov_without = paise_to_rupees(summary["avg_aov_without_upsell_paise"])
    aov_with = paise_to_rupees(summary["avg_aov_with_upsell_paise"])
    bars = ax1.bar(
        ["Without\nUpsell", "With\nUpsell"],
        [aov_without, aov_with],
        color=[COLOR_MUTED, COLOR_PRIMARY], width=0.5,
        edgecolor="white", linewidth=2, zorder=3,
    )
    for bar, val in zip(bars, [aov_without, aov_with]):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 15,
                 f"₹{val:,.0f}", ha="center", fontsize=11, fontweight="bold")
    ax1.set_title(f"AOV Uplift: +{summary['aov_uplift_pct']:.1f}%")
    ax1.set_ylabel("₹")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # ── Panel 2: Upsell Acceptance (top-right) ──
    ax2 = fig.add_subplot(2, 2, 2)
    success = [s for s in scenarios if s["outcome"] == "success"]
    accepted = len([s for s in success if s["aov_uplift_pct"] > 0])
    declined = len([s for s in success if s["aov_uplift_pct"] == 0])
    failed = len([s for s in scenarios if s["outcome"].startswith("failed")])
    ax2.pie(
        [accepted, declined, failed],
        labels=[f"Accepted\n({accepted})", f"Declined\n({declined})", f"Failed\n({failed})"],
        colors=COLORS_PIE, autopct="%1.0f%%", startangle=90,
        pctdistance=0.75,
        wedgeprops=dict(width=0.4, edgecolor="white", linewidth=2),
        textprops=dict(fontsize=9),
    )
    ax2.set_title("Upsell Acceptance Rate")

    # ── Panel 3: Top Scenarios (bottom-left) ──
    ax3 = fig.add_subplot(2, 2, 3)
    uplifted = [s for s in scenarios if s["aov_uplift_pct"] > 0 and s["outcome"] == "success"]
    uplifted.sort(key=lambda s: s["aov_uplift_pct"], reverse=True)
    top10 = uplifted[:10]
    names = [s["name"][:28] for s in top10]
    vals = [s["aov_uplift_pct"] for s in top10]
    max_v = max(vals) if vals else 1
    colors = [plt.cm.RdYlGn(0.3 + 0.7 * (v / max_v)) for v in vals]  # type: ignore[attr-defined]
    y_pos = np.arange(len(names))
    ax3.barh(y_pos, vals, color=colors, edgecolor="white", linewidth=1, zorder=3)
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(names, fontsize=8)
    ax3.invert_yaxis()
    ax3.set_xlabel("AOV Uplift (%)")
    ax3.set_title("Top 10 Scenarios by Uplift")
    ax3.spines["top"].set_visible(False)
    ax3.spines["right"].set_visible(False)

    # ── Panel 4: Key Metrics Summary (bottom-right) ──
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis("off")
    metrics_data = [
        ("Total Scenarios", str(summary["total_scenarios"])),
        ("Successful", str(summary["successful"])),
        ("Failed (Expected)", str(summary["failed_expected"])),
        ("Failed (Unexpected)", str(summary["failed_unexpected"])),
        ("AOV Uplift", f"+{summary['aov_uplift_pct']:.1f}%"),
        ("Total GMV", summary["total_gmv_display"]),
        ("Conversion Rate", f"{summary['conversion_rate_pct']:.0f}%"),
        ("Upsell Acceptance", f"{summary['upsell_acceptance_rate_pct']:.0f}%"),
    ]

    table = ax4.table(
        cellText=[[m, v] for m, v in metrics_data],
        colLabels=["Metric", "Value"],
        cellLoc="center",
        loc="center",
        colWidths=[0.55, 0.35],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 1.8)

    # Style header
    for j in range(2):
        cell = table[0, j]
        cell.set_facecolor(COLOR_PRIMARY)
        cell.set_text_props(color="white", fontweight="bold")

    # Alternate row colors
    for i in range(1, len(metrics_data) + 1):
        for j in range(2):
            cell = table[i, j]
            if i % 2 == 0:
                cell.set_facecolor("#F5F5F5")
            else:
                cell.set_facecolor("#FFFFFF")
            cell.set_edgecolor("#E0E0E0")

    ax4.set_title("Key Metrics Summary", pad=20)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    path = CHARTS_DIR / f"dashboard.{fmt}"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── Main ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate AOV uplift & performance charts from batch metrics."
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Display charts interactively after generating",
    )
    parser.add_argument(
        "--format", choices=["png", "svg", "pdf"], default="png",
        help="Output format (default: png)",
    )
    parser.add_argument(
        "--metrics", type=str, default=None,
        help="Path to metrics_report.json (default: output/metrics_report.json)",
    )
    args = parser.parse_args()

    # Switch to interactive backend if --show
    if args.show:
        matplotlib.use("TkAgg")

    setup_style()

    # Load data
    metrics_path = Path(args.metrics) if args.metrics else METRICS_PATH
    data = load_metrics(metrics_path)
    summary = data["summary"]
    scenarios = data["scenarios"]

    # Create output directory
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  AGENTIC STOREFRONT — Chart Generator")
    print("=" * 60)
    print(f"\n  Metrics file : {metrics_path}")
    print(f"  Output dir   : {CHARTS_DIR}")
    print(f"  Format       : {args.format.upper()}")
    print(f"  Scenarios    : {summary['total_scenarios']}")
    print(f"  AOV Uplift   : +{summary['aov_uplift_pct']:.1f}%")
    print()

    # Generate all charts
    charts = []

    print("  [1/5] AOV Comparison ...", end=" ", flush=True)
    charts.append(chart_aov_comparison(summary, args.format))
    print("OK")

    print("  [2/5] Scenario Uplift ...", end=" ", flush=True)
    charts.append(chart_scenario_uplift(scenarios, args.format))
    print("OK")

    print("  [3/5] Upsell Acceptance ...", end=" ", flush=True)
    charts.append(chart_upsell_acceptance(summary, scenarios, args.format))
    print("OK")

    print("  [4/5] GMV Breakdown ...", end=" ", flush=True)
    charts.append(chart_gmv_breakdown(summary, scenarios, args.format))
    print("OK")

    print("  [5/5] Combined Dashboard ...", end=" ", flush=True)
    charts.append(chart_dashboard(summary, scenarios, args.format))
    print("OK")

    print(f"\n  All charts saved to: {CHARTS_DIR}/")
    for c in charts:
        print(f"    {c.name}")

    print(f"\n{'=' * 60}")
    print("  DONE")
    print(f"{'=' * 60}\n")

    if args.show:
        print("  Opening charts...")
        for c in charts:
            import subprocess
            subprocess.Popen(["start", "", str(c)], shell=True)


if __name__ == "__main__":
    main()
