"""Annual income tax (§ 32a EStG) and the Progressionsvorbehalt (§ 32b EStG).

The tariff comes from the official BMF Programmablaufplan of the year (see pap/interpreter.py). Years
without a published PAP use the nearest one, so results for those years are estimates.
"""

from __future__ import annotations

from decimal import Decimal

from .pap.interpreter import SUPPORTED_YEARS, load_pap


def income_tax(zve: Decimal, year: int, joint: bool) -> int:
    pap_year = min(max(year, min(SUPPORTED_YEARS)), max(SUPPORTED_YEARS))
    return load_pap(pap_year).income_tax(zve, joint)


def with_progressionsvorbehalt(zve: Decimal, benefits: Decimal, year: int, joint: bool) -> int:
    """§ 32b Abs. 2 EStG: tax-free benefits (Elterngeld, Mutterschaftsgeld incl. employer top-up) raise
    the tax rate; that special rate – the average rate on zvE + benefits – applies to the zvE."""
    if zve <= 0:
        return 0
    if benefits <= 0:
        return income_tax(zve, year, joint)
    base = zve + benefits
    return int(zve * income_tax(base, year, joint) / base)
