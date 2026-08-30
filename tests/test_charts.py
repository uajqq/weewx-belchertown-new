"""Unit tests for New Belchertown chart-config helpers.

Runs without a WeeWX install: the weewx / weeutil modules that
``new_belchertown.py`` imports are stubbed before import. Standard library only.

    python -m unittest discover -s tests
"""
import logging
import sys
import types
import unittest

# new_belchertown.py logs on some parse errors; keep that out of test output.
logging.disable(logging.CRITICAL)


def _install_weewx_stubs():
    class _Base:  # stand-in for SearchList / ReportGenerator base classes
        def __init__(self, *args, **kwargs):
            pass

    def _mod(name, **attrs):
        m = sys.modules.get(name) or types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    weewx = _mod("weewx", __version__="5.4.0")
    weewx.UnsupportedFeature = type("UnsupportedFeature", (Exception,), {})
    weewx.reportengine = _mod("weewx.reportengine", ReportGenerator=_Base)
    weewx.tags = _mod("weewx.tags", TimespanBinder=_Base)
    weewx.units = _mod("weewx.units")
    weewx.cheetahgenerator = _mod("weewx.cheetahgenerator", SearchList=_Base)
    weewx.xtypes = _mod("weewx.xtypes", XType=_Base, xtypes=[])
    weewx.manager = _mod("weewx.manager")
    weewx.station = _mod("weewx.station")

    noop = lambda *a, **k: None
    weeutil = _mod("weeutil")
    weeutil.weeutil = _mod(
        "weeutil.weeutil",
        TimeSpan=noop, archiveDaySpan=noop, archiveMonthSpan=noop,
        archiveSpanSpan=noop, archiveWeekSpan=noop, archiveYearSpan=noop,
        isStartOfDay=noop, startOfDay=noop, nominal_spans=noop,
        to_bool=lambda v: str(v).strip().lower()
        not in ("false", "0", "no", "none", ""),
        to_float=float, to_int=int,
    )
    weeutil.config = _mod("weeutil.config", accumulateLeaves=noop)

    try:
        import configobj  # noqa: F401
    except ImportError:
        _mod("configobj", ConfigObj=_Base, Section=_Base)


_install_weewx_stubs()
sys.path.insert(0, "bin")
from user.new_belchertown import (  # noqa: E402
    CHART_PLOTLINE_LABEL_RE,
    _resolve_chart_label_text,
)


class TestPlotlineLabelKeyPattern(unittest.TestCase):
    """Numbered reference-line label keys get ${label_key} resolution too.

    The generator resolves label tokens for keys in CHART_TEXT_SERIES_OPTIONS
    plus anything matching CHART_PLOTLINE_LABEL_RE, so a shared charts.conf can
    localize every reference-line label, not just the first line's.
    """

    def test_unnumbered_label_matches(self):
        self.assertTrue(CHART_PLOTLINE_LABEL_RE.match("yAxis_plotLine_label"))

    def test_numbered_labels_match(self):
        for n in (2, 3, 9, 20):
            self.assertTrue(
                CHART_PLOTLINE_LABEL_RE.match("yAxis_plotLine%d_label" % n),
                "line %d label key should match" % n,
            )

    def test_other_plotline_keys_do_not_match(self):
        # Only the label text is chart text; style keys stay literal even
        # though _labelAlign / _labelVerticalAlign contain "label".
        for key in (
            "yAxis_plotLine_value",
            "yAxis_plotLine2_value",
            "yAxis_plotLine2_color",
            "yAxis_plotLine2_dashStyle",
            "yAxis_plotLine2_width",
            "yAxis_plotLine2_zIndex",
            "yAxis_plotLine2_labelAlign",
            "yAxis_plotLine2_labelVerticalAlign",
        ):
            self.assertIsNone(CHART_PLOTLINE_LABEL_RE.match(key), key)

    def test_unrelated_keys_do_not_match(self):
        for key in (
            "yAxis_label",
            "yAxis_label_unit",
            "color2",
            "name",
            "yAxis_plotLineX_label",
            "xyAxis_plotLine_label",
        ):
            self.assertIsNone(CHART_PLOTLINE_LABEL_RE.match(key), key)


class TestResolveChartLabelText(unittest.TestCase):
    """_resolve_chart_label_text is what the generator runs on matched keys."""

    LABELS = {"conservation_pool": "Conservation pool", "dam": "Top of dam"}

    def test_token_resolved_from_labels(self):
        self.assertEqual(
            _resolve_chart_label_text("${conservation_pool}", self.LABELS),
            "Conservation pool",
        )

    def test_plain_text_passes_through(self):
        self.assertEqual(
            _resolve_chart_label_text("Top of dam", self.LABELS), "Top of dam"
        )

    def test_unknown_token_left_intact(self):
        self.assertEqual(
            _resolve_chart_label_text("${nope}", self.LABELS), "${nope}"
        )

    def test_non_string_untouched(self):
        self.assertEqual(_resolve_chart_label_text(340, self.LABELS), 340)


if __name__ == "__main__":
    unittest.main()
