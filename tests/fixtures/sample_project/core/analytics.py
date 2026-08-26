# Fixture file: core/analytics.py
#
# EXPECTED-INCLUDE: core.analytics.aggregate
# EXPECTED-INCLUDE: core.analytics.Report.summarize
# EXPECTED-INCLUDE: core.analytics.Report.summarize#2
# EXPECTED-INCLUDE: core.analytics.Report.summarize#3
# EXPECTED-EXCLUDE: core.analytics.test_aggregate_smoke :: test_function
# EXPECTED-EXCLUDE: core.analytics.Report.__init__ :: dunder_method
# EXPECTED-EXCLUDE: core.analytics.Report._rows_for :: private_name


def aggregate(rows: list[dict], key: str) -> dict:
    return {key: len(rows)}


def test_aggregate_smoke() -> None:
    assert aggregate([], "n") == {"n": 0}


class Report:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def _rows_for(self, key: str) -> list[dict]:
        return [row for row in self.rows if key in row]

    def summarize(self) -> dict:
        return aggregate(self.rows, "count")

    def summarize(self, window: int = 7) -> dict:
        return aggregate(self.rows[:window], "count")

    def summarize(self, window: int, kind: str = "mean") -> dict:
        return {kind: len(self.rows[:window])}
