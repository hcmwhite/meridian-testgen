# Fixture file: testfixtures/legacy.py
#
# This file lives in a directory whose name begins with ``test``, so the walker
# never descends into it. It contributes nothing to either output file.
#
# (no EXPECTED-INCLUDE entries)
# (no EXPECTED-EXCLUDE entries)


def legacy_helper(value: int) -> int:
    return value * 2


class LegacyReport:
    def render(self) -> str:
        return "legacy"
