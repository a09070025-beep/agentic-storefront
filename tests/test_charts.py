"""
Tests for generate_chart.py
Validates chart generation from metrics data without requiring display.
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_chart import (
    load_metrics,
    paise_to_rupees,
    setup_style,
    chart_aov_comparison,
    chart_scenario_uplift,
    chart_upsell_acceptance,
    chart_gmv_breakdown,
    chart_dashboard,
    CHARTS_DIR,
    METRICS_PATH,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def metrics_data():
    """Load the real metrics report."""
    assert METRICS_PATH.exists(), (
        f"Metrics file not found at {METRICS_PATH}. "
        "Run 'python main.py batch' first."
    )
    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def summary(metrics_data):
    return metrics_data["summary"]


@pytest.fixture(scope="module")
def scenarios(metrics_data):
    return metrics_data["scenarios"]


@pytest.fixture(autouse=True)
def ensure_charts_dir():
    """Ensure charts directory exists before each test."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Unit Tests ───────────────────────────────────────────────

class TestPaiseConversion:
    def test_basic(self):
        assert paise_to_rupees(10000) == 100.0

    def test_zero(self):
        assert paise_to_rupees(0) == 0.0

    def test_fractional(self):
        assert paise_to_rupees(12345) == 123.45


class TestLoadMetrics:
    def test_loads_successfully(self):
        data = load_metrics()
        assert "summary" in data
        assert "scenarios" in data

    def test_has_required_summary_fields(self):
        data = load_metrics()
        s = data["summary"]
        required = [
            "total_scenarios",
            "successful",
            "failed_expected",
            "failed_unexpected",
            "avg_aov_without_upsell_paise",
            "avg_aov_with_upsell_paise",
            "aov_uplift_pct",
            "total_gmv_paise",
            "total_gmv_display",
            "conversion_rate_pct",
            "upsell_acceptance_rate_pct",
        ]
        for field in required:
            assert field in s, f"Missing summary field: {field}"

    def test_scenarios_not_empty(self):
        data = load_metrics()
        assert len(data["scenarios"]) == 55

    def test_nonexistent_file_exits(self):
        with pytest.raises(SystemExit):
            load_metrics(Path("/nonexistent/fake_metrics.json"))


class TestMetricsIntegrity:
    """Validate the metrics data makes business sense."""

    def test_aov_uplift_positive(self, summary):
        assert summary["aov_uplift_pct"] > 0, "AOV uplift should be positive"

    def test_aov_with_greater_than_without(self, summary):
        assert (
            summary["avg_aov_with_upsell_paise"]
            >= summary["avg_aov_without_upsell_paise"]
        )

    def test_no_unexpected_failures(self, summary):
        assert summary["failed_unexpected"] == 0

    def test_conversion_rate_100(self, summary):
        assert summary["conversion_rate_pct"] == 100.0

    def test_total_scenarios_55(self, summary):
        assert summary["total_scenarios"] == 55

    def test_scenario_outcomes_add_up(self, summary):
        total = (
            summary["successful"]
            + summary["failed_expected"]
            + summary["failed_unexpected"]
        )
        assert total == summary["total_scenarios"]


# ── Chart Generation Tests ───────────────────────────────────

class TestChartGeneration:
    """Test that each chart generates a valid file."""

    @pytest.fixture(autouse=True)
    def _setup_style(self):
        setup_style()

    def test_aov_comparison(self, summary):
        path = chart_aov_comparison(summary, "png")
        assert path.exists()
        assert path.stat().st_size > 1000  # non-trivial file
        assert path.suffix == ".png"

    def test_scenario_uplift(self, scenarios):
        path = chart_scenario_uplift(scenarios, "png")
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_upsell_acceptance(self, summary, scenarios):
        path = chart_upsell_acceptance(summary, scenarios, "png")
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_gmv_breakdown(self, summary, scenarios):
        path = chart_gmv_breakdown(summary, scenarios, "png")
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_dashboard(self, summary, scenarios):
        path = chart_dashboard(summary, scenarios, "png")
        assert path.exists()
        assert path.stat().st_size > 5000  # Dashboard should be larger

    def test_svg_format(self, summary):
        path = chart_aov_comparison(summary, "svg")
        assert path.exists()
        assert path.suffix == ".svg"
        # SVG is text, verify it contains SVG markup
        content = path.read_text(encoding="utf-8")
        assert "<svg" in content
