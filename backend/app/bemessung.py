"""Bemessungszeitraum (§ 2b BEEG) and the Steuerklasse selection rule (§ 2c Abs. 3).

Employees only: the 12 calendar months before the month of birth, skipping
months with Mutterschutz (and other § 2b Abs. 1 Satz 2 reasons, which the
user can add). Self-employed/mixed income uses the previous calendar year
(§ 2b Abs. 2, 3) and is out of scope of this tool.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

Month = tuple[int, int]  # (year, month)


def prev_month(m: Month) -> Month:
    y, mo = m
    return (y - 1, 12) if mo == 1 else (y, mo - 1)


def next_month(m: Month) -> Month:
    y, mo = m
    return (y + 1, 1) if mo == 12 else (y, mo + 1)


def months_between(start: date, end: date) -> set[Month]:
    """All calendar months touched by [start, end]."""
    out: set[Month] = set()
    m: Month = (start.year, start.month)
    while m <= (end.year, end.month):
        out.add(m)
        m = next_month(m)
    return out


def mutterschutz_months_before_birth(due_date: date, birth: date) -> set[Month]:
    """§ 3 Abs. 1 MuSchG: Schutzfrist starts 6 weeks before the expected date.

    § 2b Abs. 1 Satz 2 Nr. 2 BEEG excludes every calendar month in which the
    mother could not be employed due to the Schutzfrist.
    """
    start = due_date - timedelta(weeks=6)
    if start >= birth:
        return set()
    return months_between(start, birth - timedelta(days=1)) - {(birth.year, birth.month)}


def bemessungszeitraum(birth: date, ausgeklammert: set[Month]) -> list[Month]:
    """§ 2b Abs. 1 BEEG: 12 months before the month of birth, skipping exclusions."""
    months: list[Month] = []
    m = prev_month((birth.year, birth.month))
    while len(months) < 12:
        if m not in ausgeklammert:
            months.append(m)
        m = prev_month(m)
    return list(reversed(months))


def massgebliches_merkmal(werte_je_monat: list[str]) -> str:
    """§ 2c Abs. 3 BEEG: the value of the last month applies, unless another value applied
    "in der überwiegenden Zahl der Kalendermonate" – in more than half of the months."""
    if not werte_je_monat:
        raise ValueError("no months with income")
    best, best_count = Counter(werte_je_monat).most_common(1)[0]
    return best if best_count * 2 > len(werte_je_monat) else werte_je_monat[-1]


@dataclass(frozen=True)
class WechselFrist:
    wirksam_ab: Month  # first month the new class must apply
    antrag_spaetestens: date  # last day to file with the Finanzamt
    monate_neu: int
    monate_alt: int


def steuerklassenwechsel_frist(bmz: list[Month]) -> WechselFrist:
    """Latest switch (single change, applied to all later months) that still
    makes the new class the decisive one: it must hold for at least as many
    months as the old class, since ties go to the last payslip.

    § 39 Abs. 6 Satz 5 EStG: effective from the month after filing.
    """
    n = len(bmz)
    k = n // 2  # new class in months k..n-1 -> n-k >= k
    wirksam = bmz[k]
    first_of_month = date(wirksam[0], wirksam[1], 1)
    return WechselFrist(
        wirksam_ab=wirksam,
        antrag_spaetestens=first_of_month - timedelta(days=1),
        monate_neu=n - k,
        monate_alt=k,
    )
