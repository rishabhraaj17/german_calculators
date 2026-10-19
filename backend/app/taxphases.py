"""Tax classes through the year for married couples (§ 39 Abs. 6 EStG).

Spouses may change their tax classes as often as they like; each change applies from the month after
filing, for the current year until 30 November. The joint annual tax is the same in every combination –
the classes only decide how much is withheld each month. The plan:

* before the birth: the current classes, except Steuerklasse III for the birthing parent (other parent V)
  in the months Mutterschaftsgeld is based on (§ 21 Abs. 1 MuSchG), until the birth;
* from the birth month: one earner -> III for the earner, V for the other; both earning -> IV/IV
  (the Faktorverfahren is the most precise option); no earner -> no change.

Classes changed after the birth no longer affect Elterngeld: the Bemessungszeitraum ends before the
month of birth (§ 2b BEEG).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

Month = tuple[int, int]
ZERO = Decimal(0)


def next_month(m: Month) -> Month:
    return (m[0] + 1, 1) if m[1] == 12 else (m[0], m[1] + 1)


@dataclass(frozen=True)
class MonthIncome:
    gross: tuple[Decimal, ...]  # salary gross per parent in this calendar month
    benefits: tuple[Decimal, ...]  # Mutterschaftsgeld + Elterngeld per parent (tax-free)


def plan_classes(*, months: list[Month], current: tuple[str, str], birth: date, birthing: int | None,
                 mg_from: Month | None, income: Callable[[Month], MonthIncome]) -> list[tuple[str, str]]:
    """The class combination for each month; months[0] is the current month and cannot change."""
    birth_month = (birth.year, birth.month)
    out: list[tuple[str, str]] = []
    for k, m in enumerate(months):
        if k == 0:
            out.append(current)
            continue
        if m < birth_month:
            if mg_from is not None and birthing is not None and m >= mg_from:
                combo = ("III", "V") if birthing == 0 else ("V", "III")
            else:
                combo = current
        else:
            earners = [i for i, g in enumerate(income(m).gross) if g > 0]
            if len(earners) == 1:
                combo = ("III", "V") if earners[0] == 0 else ("V", "III")
            elif len(earners) == 2:
                combo = current if all(c in ("IV", "IV_FAKTOR") for c in current) else ("IV", "IV")
            else:
                combo = out[-1]
        out.append(combo)
    return out


def phases(*, today: date, end: Month, current: tuple[str, str], birth: date, birthing: int | None,
           mg_from: Month | None, income: Callable[[Month], MonthIncome],
           take_home: Callable[[int, Decimal, str, Month], Decimal]) -> list[dict]:
    """Consecutive months with the same classes, with the filing deadline and average take-home."""
    months: list[Month] = []
    m: Month = (today.year, today.month)
    while m <= end:
        months.append(m)
        m = next_month(m)
    combos = plan_classes(months=months, current=current, birth=birth, birthing=birthing, mg_from=mg_from,
                          income=income)
    out: list[dict] = []
    for m, combo in zip(months, combos):
        inc = income(m)
        net = [take_home(i, inc.gross[i], combo[i], m) if inc.gross[i] > 0 else ZERO for i in range(2)]
        if out and out[-1]["classes"] == list(combo):
            ph = out[-1]
        else:
            first = date(m[0], m[1], 1)
            ph = {"from": m, "to": m, "classes": list(combo), "months": 0,
                  "file_by": None if not out else first - timedelta(days=1),
                  "reason": _reason(m, inc, birth, mg_from), "_net": [ZERO, ZERO],
                  "_benefits": [ZERO, ZERO]}
            out.append(ph)
        ph["to"] = m
        ph["months"] += 1
        for i in range(2):
            ph["_net"][i] += net[i]
            ph["_benefits"][i] += inc.benefits[i]
    for ph in out:
        n = Decimal(ph["months"])
        ph["take_home"] = [_cent(ph["_net"][i] / n) for i in range(2)]
        ph["benefits"] = [_cent(ph["_benefits"][i] / n) for i in range(2)]
        ph["household"] = _cent(sum(ph["take_home"]) + sum(ph["benefits"]))
        ph["from"] = f"{ph['from'][0]}-{ph['from'][1]:02d}"
        ph["to"] = f"{ph['to'][0]}-{ph['to'][1]:02d}"
        del ph["_net"], ph["_benefits"]
    return out


def _reason(m: Month, inc: MonthIncome, birth: date, mg_from: Month | None) -> str:
    if m < (birth.year, birth.month):
        return "mutterschaftsgeld" if mg_from is not None and m >= mg_from else "current"
    earners = sum(1 for g in inc.gross if g > 0)
    return {1: "one_earner", 2: "both_earn"}.get(earners, "no_salary")


def _cent(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
