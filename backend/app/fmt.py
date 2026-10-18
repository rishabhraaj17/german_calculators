from decimal import ROUND_HALF_UP, Decimal


def eur(x: Decimal, cents: bool = False) -> str:
    """German number format: 175.000 € / 1.234,56 €."""
    q = Decimal("0.01") if cents else Decimal(1)
    s = f"{x.quantize(q, rounding=ROUND_HALF_UP):,.{2 if cents else 0}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + "\u00a0€"
