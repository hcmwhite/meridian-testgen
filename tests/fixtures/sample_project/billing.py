# Fixture file: billing.py
#
# EXPECTED-INCLUDE: billing.compute_total
# EXPECTED-INCLUDE: billing.compute_total#2
# EXPECTED-INCLUDE: billing.Invoice.validate
# EXPECTED-INCLUDE: billing.Invoice.validate#2
# EXPECTED-INCLUDE: billing.Invoice.total
# EXPECTED-EXCLUDE: billing._round_currency :: private_name
# EXPECTED-EXCLUDE: billing.test_compute_total :: test_function
# EXPECTED-EXCLUDE: billing.Invoice.__init__ :: dunder_method
# EXPECTED-EXCLUDE: billing.Invoice.__repr__ :: dunder_method
# EXPECTED-EXCLUDE: billing.Invoice._cache_key :: private_name


def compute_total(items, tax_rate: float = 0.0) -> float:
    return sum(items) * (1.0 + tax_rate)


def compute_total(items, tax_rate: float, discount: float = 0.0) -> float:
    return sum(items) * (1.0 + tax_rate) - discount


def _round_currency(value: float) -> float:
    return round(value, 2)


def test_compute_total() -> None:
    assert compute_total([1.0], 0.0) == 1.0


class Invoice:
    def __init__(self, items: list[float], customer: str = "anonymous") -> None:
        self.items = items
        self.customer = customer

    def __repr__(self) -> str:
        return f"Invoice({self.customer!r})"

    def _cache_key(self) -> str:
        return f"{self.customer}:{len(self.items)}"

    def validate(self) -> bool:
        return all(item >= 0 for item in self.items)

    def validate(self, strict: bool = False) -> bool:
        if strict:
            return all(item > 0 for item in self.items)
        return all(item >= 0 for item in self.items)

    def total(self, tax_rate: float = 0.0) -> float:
        return compute_total(self.items, tax_rate)
