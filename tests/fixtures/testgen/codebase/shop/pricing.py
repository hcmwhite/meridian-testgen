"""Pricing rules for the fixture shop."""


def apply_discount(price, percent=0):
    """Reduce price by percent, never below zero."""
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    reduced = price - (price * percent / 100)
    return max(reduced, 0.0)


def cart_total(items, prices):
    """Sum the price of every item in the cart."""
    total = 0.0
    for name, quantity in items:
        total += prices.get(name, 0.0) * quantity
    return total


def format_currency(amount: float) -> str:
    """Render an amount as a currency string."""
    return f"${amount:.2f}"


class Receipt:
    """A printable receipt."""

    def render(self, lines: list, total: float) -> str:
        """Join the receipt lines and append the total."""
        body = "\n".join(lines)
        return f"{body}\nTOTAL {format_currency(total)}"
