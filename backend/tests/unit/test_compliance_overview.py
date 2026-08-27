"""U10 overview aggregation tests — pure helpers, no DB."""

from lokilinux.api.v1.routers.compliance import overview as ov


def _row(agent, category, score, weighted=None, unknown=None):
    return (agent, category, score, weighted, unknown)


class TestScoreSummary:
    def test_means_per_category(self):
        rows = [
            _row("a1", "overall", 80.0, 90.0, 2),
            _row("a2", "overall", 60.0, 70.0, 0),
            _row("a1", "security", 100.0, 100.0, 0),
        ]
        out = ov._score_summary(rows)
        by = {e["category"]: e for e in out}
        assert by["overall"]["score"] == 70.0
        assert by["overall"]["weighted_score"] == 80.0
        assert by["overall"]["agents_scored"] == 2
        assert by["overall"]["unknown_total"] == 2
        assert by["security"]["score"] == 100.0

    def test_overall_sorted_first(self):
        rows = [_row("a", "security", 50.0), _row("a", "overall", 50.0)]
        out = ov._score_summary(rows)
        assert out[0]["category"] == "overall"

    def test_null_weighted_falls_back_to_score(self):
        rows = [_row("a", "overall", 75.0, None, None)]
        out = ov._score_summary(rows)
        assert out[0]["weighted_score"] == 75.0


class TestSeverityCounts:
    def test_counts_and_unknown_alias(self):
        rows = [("HIGH", 3), (None, 1), ("LOW", 2)]
        assert ov._severity_counts(rows) == {"HIGH": 3, "UNKNOWN": 1, "LOW": 2}
