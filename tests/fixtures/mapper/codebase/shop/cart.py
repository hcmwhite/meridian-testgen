"""A tiny cart, used as mapper fixture input."""


def add_item(cart, item, quantity=1):
    """Add *quantity* of *item* to *cart* and return the new total count."""
    cart[item] = cart.get(item, 0) + quantity
    return sum(cart.values())


def total_price(cart, prices):
    """Sum the price of everything in *cart*."""
    return sum(prices[item] * count for item, count in cart.items())


class Checkout:
    def summarise(self, cart):
        """One line per item, in insertion order."""
        return "\n".join(f"{item} x{count}" for item, count in cart.items())
