"""Month-by-month Elterngeld and Elternzeit plan.

Each parent gets one entry per Lebensmonat (1-36):
  "none"  – nothing
  "basis" – Basiselterngeld                      (§ 4 Abs. 1 Satz 3, § 4a Abs. 1 BEEG)
  "plus"  – ElterngeldPlus without work          (§ 4 Abs. 1 Satz 4, § 4a Abs. 2)
  "plus_tz" – ElterngeldPlus while working part-time (§ 2 Abs. 3, § 4a Abs. 2)
  "bonus" – Partnerschaftsbonus (an extra Plus month, with part-time work)  (§ 4b, § 4c Abs. 2)
  "ez"    – Elternzeit without Elterngeld        (§ 15 Abs. 2)

The part-time pay entered for a parent applies to their "plus_tz" and "bonus" months.
Mutterschaftsgeld of the birthing parent is credited day by day and those
Lebensmonate count as Basis months (§ 3 Abs. 1, § 4 Abs. 4 Satz 3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Required, TypedDict

from .elterngeld import ZERO, Monatsbetraege, cent

TYPES = ("none", "basis", "plus", "plus_tz", "bonus", "ez")
EG_TYPES = ("basis", "plus", "plus_tz", "bonus")
PLUS_TYPES = ("plus", "plus_tz")
WORK_TYPES = ("plus_tz", "bonus")
MAX_LM = 36  # Elternzeit until the 3rd birthday (§ 15 Abs. 2 Satz 1)
EG_LAST_LM = 32  # § 4 Abs. 1 Satz 4
BASIS_LAST_LM = 14  # § 4 Abs. 1 Satz 3
NOTICE = timedelta(weeks=7)  # § 16 Abs. 1 Satz 1 Nr. 1
PROTECTION_LEAD = timedelta(weeks=8)  # § 18 Abs. 1 Satz 2 Nr. 1


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)


def lebensmonat(birth: date, n: int) -> tuple[date, date]:
    """§ 4 Abs. 2 BEEG: Lebensmonate run from the birth date to the day before."""
    return add_months(birth, n - 1), add_months(birth, n) - timedelta(days=1)


def mutterschutz_end(birth: date, weeks: int) -> date:
    """§ 3 Abs. 2 MuSchG: Schutzfrist ends `weeks` weeks after delivery."""
    return birth + timedelta(weeks=weeks)


class MonthCell(TypedDict, total=False):
    """One parent in one Lebensmonat. Optional keys appear only when they apply."""

    type: Required[str]  # one of TYPES
    amount: Required[Decimal]  # Elterngeld after crediting Mutterschaftsgeld
    total_net: Required[Decimal]  # Elterngeld + Mutterschaftsgeld + net pay
    hours: Decimal  # effective weekly hours (salary model only)
    gross_pay: Decimal  # only in months with pay
    net_pay: Decimal
    mutterschutz_days: int  # days covered by the Schutzfrist after birth
    mutterschaftsgeld: Decimal
    elterngeld_before_credit: Decimal


class MonthRow(TypedDict):
    lm: int
    start: date  # first day of the Lebensmonat
    end: date  # last day
    parents: list[MonthCell]


@dataclass(frozen=True)
class ParentContext:
    label: str
    amounts: Monatsbetraege  # incl. Geschwisterbonus
    amounts_plain: Monatsbetraege  # without Geschwisterbonus
    part_time_hours: Decimal = ZERO
    part_time_net: Decimal | None = None  # take-home pay per part-time month (for display)
    part_time_in_basis: bool = False
    employee: bool = True  # Elternzeit exists only for employees (§ 15 Abs. 1)
    earned_before: bool = True  # had earned income before birth (needed for the Partnermonate, § 4 Abs. 3 Satz 2)
    civil_servant: bool = False
    contract_hours: Decimal = Decimal(40)
    # weekly hours -> (gross, net) salary per month; None = no salary model
    pay: Callable[[Decimal], tuple[Decimal, Decimal]] | None = None
    # (avg. gross of Basis months with work, avg. gross of Plus/Bonus months with work, Geschwisterbonus)
    # -> (Basis amount with work, Plus amount with work); § 2 Abs. 3 Satz 3 BEEG averages per group
    work_amounts: Callable[[Decimal | None, Decimal | None, bool], tuple[Decimal | None, Decimal | None]] | None = None


@dataclass
class PlanResult:
    valid: bool
    timeline: list[list[str]]
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rows: list[MonthRow] = field(default_factory=list)  # per Lebensmonat
    months: list[list[dict]] = field(default_factory=list)  # per parent: Elterngeld months only
    totals: list[Decimal] = field(default_factory=list)
    elternzeit: list[dict] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    maternity_after_birth: Decimal = ZERO
    net_pay_total: list[Decimal] = field(default_factory=list)
    hours: list[list[Decimal]] = field(default_factory=list)  # effective hours per parent and month
    plan_end_lm: int = 0  # last Lebensmonat with Elterngeld or Elternzeit
    month_totals: list[dict] = field(default_factory=list)  # per parent: elterngeld, mutterschaftsgeld, net pay, total

    @property
    def household_total(self) -> Decimal:
        return sum(self.totals, ZERO)

    @property
    def months_with_elterngeld(self) -> int:
        return sum(1 for r in self.rows if any(p["type"] in EG_TYPES for p in r["parents"]))


def partnermonate_possible(parents: list[ParentContext]) -> bool:
    """§ 4 Abs. 3 Satz 2, § 4c Abs. 1 BEEG: the 2 extra months need earned income that is reduced
    in 2 Lebensmonate – impossible if no parent had earned income before birth."""
    return any(p.earned_before for p in parents)


def normalise(timeline: list[list[str]], n_parents: int) -> list[list[str]]:
    out = []
    for i in range(n_parents):
        row = list(timeline[i]) if i < len(timeline) else []
        out.append((row + ["none"] * MAX_LM)[:MAX_LM])
    return out


def from_counts(counts: list[tuple[int, int, int]], first: int, works: list[bool] | None = None) -> list[list[str]]:
    """Sequential layout for count-based plans: the first parent starts at
    Lebensmonat 1, the other parent's Basis follows; bonus months come last."""
    n = len(counts)
    tl = [["none"] * MAX_LM for _ in range(n)]
    order = [first] + [i for i in range(n) if i != first]
    basis_end = 0
    ends = []
    for idx in order:
        b, p, _ = counts[idx]
        lm = basis_end + 1 if idx != first else 1
        for _ in range(b):
            if lm <= MAX_LM:
                tl[idx][lm - 1] = "basis"
            lm += 1
        if idx == first:
            basis_end = lm - 1
        for _ in range(p):
            if lm <= MAX_LM:
                tl[idx][lm - 1] = "plus_tz" if works and works[idx] else "plus"
            lm += 1
        ends.append(lm - 1)
    start = max(ends, default=0) + 1
    for idx in range(n):
        for k in range(counts[idx][2]):
            if start + k <= MAX_LM:
                tl[idx][start + k - 1] = "bonus"
    return tl


def _runs(lms: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for lm in sorted(lms):
        if runs and runs[-1][1] == lm - 1:
            runs[-1] = (runs[-1][0], lm)
        else:
            runs.append((lm, lm))
    return runs


def _effective_hours(tl: list[list[str]], parents: list[ParentContext], given: list[list[Decimal | None]] | None,
                     birthing: int | None, forced: list[int]) -> list[list[Decimal]]:
    """Weekly working hours per parent and Lebensmonat: entered value, else a default by month type.

    Defaults: back at work with contract hours in months without Elterngeld/Elternzeit, the planned
    part-time hours in "Plus + work"/Bonus months, otherwise 0. No work in Mutterschutz after birth
    (§ 3 Abs. 2 MuSchG)."""
    out = []
    for i, p in enumerate(parents):
        row = []
        for lm in range(1, MAX_LM + 1):
            kind = tl[i][lm - 1]
            value = given[i][lm - 1] if (given and i < len(given) and lm - 1 < len(given[i])) else None
            if value is None:
                if kind == "none":
                    value = p.contract_hours if p.employee else ZERO
                elif kind in WORK_TYPES or (kind == "basis" and p.part_time_in_basis):
                    value = p.part_time_hours
                else:
                    value = ZERO
            if (i == birthing and lm in forced) or not p.employee:
                value = ZERO
            row.append(Decimal(value))
        out.append(row)
    return out


def _validate(tl: list[list[str]], parents: list[ParentContext], single_parent_4c: bool,
              simultaneous_exception: bool, hours: list[list[Decimal]] | None = None) -> list[str]:
    errors: list[str] = []
    n = len(tl)
    names = [p.label for p in parents]
    partner_ok = partnermonate_possible(parents)

    def months_of(i: int, *types: str) -> list[int]:
        return [lm for lm in range(1, MAX_LM + 1) if tl[i][lm - 1] in types]

    for i in range(n):
        bad = [t for t in tl[i] if t not in TYPES]
        if bad:
            errors.append(f"{names[i]}: unknown month type {bad[0]!r}.")
        if any(lm > EG_LAST_LM for lm in months_of(i, *EG_TYPES)):
            errors.append(f"{names[i]}: Elterngeld is only possible until Lebensmonat 32 (§ 4 Abs. 1 Satz 4 BEEG).")
        if any(lm > BASIS_LAST_LM for lm in months_of(i, "basis")):
            errors.append(f"{names[i]}: Basiselterngeld only until Lebensmonat 14 – use ElterngeldPlus later "
                          "(§ 4 Abs. 1 Satz 3 BEEG).")
        b, p, bonus = len(months_of(i, "basis")), len(months_of(i, *PLUS_TYPES)), len(months_of(i, "bonus"))
        if 0 < b + p + bonus < 2:
            errors.append(f"{names[i]}: Elterngeld must be claimed for at least 2 Lebensmonate (§ 4 Abs. 4 Satz 2 BEEG).")
        per_parent = 14 if (single_parent_4c and partner_ok) else 12
        if b + Decimal(p) / 2 > per_parent:
            errors.append(f"{names[i]}: {b} Basis + {p} Plus = {b + Decimal(p) / 2:g} Basis-equivalents; max "
                          f"{per_parent} per parent (1 Basis = 2 Plus, § 4 Abs. 3 Satz 3, Abs. 4 Satz 1 / § 4c BEEG).")
        if hours is not None:
            over = [lm for lm in months_of(i, *EG_TYPES) if hours[i][lm - 1] > 32]
            if over:
                errors.append(f"{names[i]}: more than 32 h/week in month {', '.join(map(str, over))} while receiving "
                              "Elterngeld (§ 1 Abs. 6 BEEG).")
        else:
            working = months_of(i, *WORK_TYPES) or (parents[i].part_time_in_basis and b)
            if working and parents[i].part_time_hours > 32:
                errors.append(f"{names[i]}: more than 32 h/week while receiving Elterngeld (§ 1 Abs. 6 BEEG).")

    claimants = sum(1 for i in range(n) if months_of(i, *EG_TYPES))
    equivalents = sum(len(months_of(i, "basis")) + Decimal(len(months_of(i, *PLUS_TYPES))) / 2 for i in range(n))
    shared = 14 if (claimants == 2 or single_parent_4c) and partner_ok else 12
    if equivalents > shared:
        errors.append(f"Together {equivalents:g} Basis-equivalents; max {shared}. The 2 Partnermonate need both "
                      "parents to claim (§ 4 Abs. 3 Satz 2 BEEG) or single-parent status (§ 4c BEEG)"
                      + ("." if partner_ok else ", and earned income before birth that is reduced in 2 "
                         "Lebensmonate – no parent had earned income."))

    late = sorted({lm for i in range(n) for lm in months_of(i, *EG_TYPES) if lm >= 15})
    if late and late != list(range(15, late[-1] + 1)):
        errors.append("From Lebensmonat 15 on, Elterngeld must be taken without gaps – starting in month 15 – "
                      "by at least one parent (§ 4 Abs. 1 Satz 4 BEEG).")

    if n == 2 and not simultaneous_exception:
        both = [lm for lm in range(1, MAX_LM + 1) if tl[0][lm - 1] == "basis" and tl[1][lm - 1] == "basis"]
        if len(both) > 1 or any(lm > 12 for lm in both):
            errors.append("Both parents may receive Basiselterngeld at the same time in only one of the first 12 "
                          "Lebensmonate (§ 4 Abs. 6 BEEG). Use ElterngeldPlus for overlapping months.")

    bonus_sets = [months_of(i, "bonus") for i in range(n)]
    if any(bonus_sets):
        if n == 2 and bonus_sets[0] != bonus_sets[1]:
            errors.append("Partnerschaftsbonus: both parents must take it in the same months (§ 4b Abs. 3 BEEG).")
        if n == 1 and not single_parent_4c:
            errors.append("Partnerschaftsbonus alone is only possible for single parents under § 4c BEEG.")
        for i, months in enumerate(bonus_sets):
            if not months:
                continue
            if not 2 <= len(months) <= 4 or len(_runs(months)) != 1:
                errors.append(f"{names[i]}: Partnerschaftsbonus must be 2–4 consecutive months (§ 4b Abs. 2, 3 BEEG).")
            if hours is not None:
                short = [lm for lm in months if not 24 <= hours[i][lm - 1] <= 32]
                if short:
                    errors.append(f"{names[i]}: Partnerschaftsbonus requires 24–32 working hours/week in every bonus "
                                  f"month (§ 4b Abs. 1 BEEG); check month {', '.join(map(str, short))}.")
            else:
                h = parents[i].part_time_hours
                if not 24 <= h <= 32:
                    errors.append(f"{names[i]}: Partnerschaftsbonus requires 24–32 working hours/week (monthly "
                                  f"average); entered: {h:g} h (§ 4b Abs. 1 BEEG).")
    return list(dict.fromkeys(errors))


@dataclass(frozen=True)
class MaternityCredit:
    """Mutterschaftsleistungen of the birthing parent from the day of birth.

    credited_per_day: amount per calendar day credited against Elterngeld
    (§ 3 Abs. 1 Nr. 1, 2 BEEG); None = assume it exceeds the daily Elterngeld.
    paid_per_day: amount actually paid per day (for display), if known.
    """

    end: date  # last day of the Schutzfrist after birth
    credited_per_day: Decimal | None = None
    paid_per_day: Decimal | None = None


def evaluate(
    timeline: list[list[str]],
    parents: list[ParentContext],
    *,
    birth: date,
    birthing: int | None,
    single_parent_4c: bool,
    simultaneous_exception: bool,
    maternity: MaternityCredit | None = None,
    mutterschutz_weeks: int | None = None,
    gb_active: Callable[[int], bool] | None = None,
    hours: list[list[Decimal | None]] | None = None,
) -> PlanResult:
    tl = normalise(timeline, len(parents))
    notes: list[str] = []
    if maternity is None and birthing is not None and mutterschutz_weeks:
        maternity = MaternityCredit(end=mutterschutz_end(birth, mutterschutz_weeks))
    if birthing is None:
        maternity = None
    ms_end = maternity.end if maternity else None
    forced: list[int] = []
    # § 4 Abs. 4 Satz 3 BEEG: months with creditable Mutterschaftsleistungen count as Basis months
    if (maternity is not None and birthing is not None
            and (maternity.credited_per_day is None or maternity.credited_per_day > 0)):
        forced = [lm for lm in range(1, MAX_LM + 1) if lebensmonat(birth, lm)[0] <= maternity.end]
        changed = [lm for lm in forced if tl[birthing][lm - 1] != "basis"]
        for lm in forced:
            tl[birthing][lm - 1] = "basis"
        if changed:
            notes.append(f"{parents[birthing].label}: Lebensmonat {', '.join(map(str, changed))} set to Basis – "
                         "months with Mutterschaftsgeld count as Basis months (§ 4 Abs. 4 Satz 3 BEEG).")

    salary_model = any(p.pay is not None for p in parents)
    eff = _effective_hours(tl, parents, hours, birthing, forced) if salary_model else None
    errors = _validate(tl, parents, single_parent_4c, simultaneous_exception, eff)
    result = PlanResult(valid=not errors, timeline=tl, errors=errors, notes=notes)
    used = [lm for lm in range(1, MAX_LM + 1) if any(row[lm - 1] != "none" for row in tl)]
    result.plan_end_lm = max(used, default=0)

    # salary per month and Elterngeld with income, averaged per group (§ 2 Abs. 3 Satz 3 BEEG)
    pay_rows: list[list[tuple[Decimal, Decimal]]] = []
    work_amounts: list[dict[bool, tuple[Decimal | None, Decimal | None]]] = []
    for i, p in enumerate(parents):
        row_pay = [(ZERO, ZERO)] * MAX_LM
        if eff is not None and p.pay is not None:
            row_pay = [p.pay(h) if h > 0 else (ZERO, ZERO) for h in eff[i]]
        pay_rows.append(row_pay)

        def avg(types: tuple[str, ...]) -> Decimal | None:
            gross = [row_pay[k][0] for k in range(MAX_LM) if tl[i][k] in types and row_pay[k][0] > 0]
            return cent(sum(gross, ZERO) / len(gross)) if gross else None

        if eff is not None and p.work_amounts is not None:
            avg_b, avg_p = avg(("basis",)), avg((*PLUS_TYPES, "bonus"))
            work_amounts.append({gb: p.work_amounts(avg_b, avg_p, gb) for gb in (True, False)})
        else:
            work_amounts.append({})

    totals = [ZERO] * len(parents)
    net_pay = [ZERO] * len(parents)
    mg_total = [ZERO] * len(parents)
    grand = [ZERO] * len(parents)
    maternity_total = ZERO
    per_parent_months: list[list[dict]] = [[] for _ in parents]
    for lm in range(1, MAX_LM + 1):
        start, end = lebensmonat(birth, lm)
        gb = gb_active is None or gb_active(lm)
        row: MonthRow = {"lm": lm, "start": start, "end": end, "parents": []}
        for i, p in enumerate(parents):
            kind = tl[i][lm - 1]
            a = p.amounts if gb else p.amounts_plain
            amount = ZERO
            entry: MonthCell = {"type": kind, "amount": ZERO, "total_net": ZERO}
            covered = 0
            if i == birthing and ms_end is not None:
                covered = max((min(end, ms_end) - start).days + 1, 0)
            gross_m, net_m = pay_rows[i][lm - 1]
            if work_amounts[i]:
                basis_tz, plus_tz = work_amounts[i][gb]
                if kind == "basis":
                    amount = basis_tz if (gross_m > 0 and basis_tz is not None) else a.basis
                elif kind in (*PLUS_TYPES, "bonus"):
                    amount = plus_tz if (gross_m > 0 and plus_tz is not None) else a.plus
            elif kind == "basis":
                amount = a.basis_mit_teilzeit if (p.part_time_in_basis and a.basis_mit_teilzeit) else a.basis
            elif kind == "plus":
                amount = a.plus
            elif kind in WORK_TYPES:
                amount = a.plus_mit_teilzeit if a.plus_mit_teilzeit else a.plus
            if covered and maternity is not None:
                days = (end - start).days + 1
                share = amount * Decimal(covered) / Decimal(days)  # Elterngeld for the covered days
                credit = share if maternity.credited_per_day is None else min(share, maternity.credited_per_day * covered)
                entry["elterngeld_before_credit"] = amount
                amount = cent(amount - credit)
                entry["mutterschutz_days"] = covered
                if maternity.paid_per_day is not None:
                    entry["mutterschaftsgeld"] = cent(maternity.paid_per_day * covered)
                    maternity_total += entry["mutterschaftsgeld"]
            entry["amount"] = amount
            in_range = lm <= result.plan_end_lm
            if eff is not None:
                entry["hours"] = eff[i][lm - 1]
                if gross_m > 0:
                    entry["gross_pay"], entry["net_pay"] = gross_m, net_m
                    if in_range:
                        net_pay[i] += net_m
            else:
                works = kind in WORK_TYPES or (kind == "basis" and p.part_time_in_basis)
                if works and p.part_time_net is not None:
                    entry["net_pay"] = p.part_time_net
                    net_pay[i] += p.part_time_net
            mg = entry.get("mutterschaftsgeld", ZERO)
            entry["total_net"] = cent((amount if kind in EG_TYPES else ZERO) + mg + entry.get("net_pay", ZERO))
            if in_range:
                mg_total[i] += mg
                grand[i] += entry["total_net"]
            row["parents"].append(entry)
            if kind in EG_TYPES:
                totals[i] += amount
                per_parent_months[i].append({"lm": lm, "type": kind, "amount": amount})
        result.rows.append(row)
    result.totals = [cent(t) for t in totals]
    result.months = per_parent_months
    result.maternity_after_birth = cent(maternity_total)
    result.net_pay_total = [cent(x) for x in net_pay]
    result.hours = eff or []
    result.month_totals = [
        {"elterngeld": cent(totals[i]), "mutterschaftsgeld": cent(mg_total[i]), "net_pay": cent(net_pay[i]),
         "total": cent(grand[i])}
        for i in range(len(parents))
    ]

    for i, p in enumerate(parents):
        if eff is None and any(t in WORK_TYPES for t in tl[i]) and not p.amounts.plus_mit_teilzeit:
            result.notes.append(f"{p.label}: no part-time pay entered – part-time and bonus months are shown with "
                                "the full Plus amount. Enter the planned part-time pay for an exact figure.")
    result.elternzeit = _elternzeit(tl, parents, birth, birthing, ms_end)
    result.budget = _budget(tl, parents, single_parent_4c, birthing, forced)
    result.budget["simultaneous_basis_allowed"] = simultaneous_exception  # § 4 Abs. 6 Satz 4 BEEG
    result.budget["mutterschutz_months"] = forced
    result.budget["birthing"] = birthing
    return result


def _budget(tl: list[list[str]], parents: list[ParentContext], single_parent_4c: bool, birthing: int | None,
            forced: list[int]) -> dict:
    """What is used and what is left, per parent and for the couple (§§ 4, 4b, 4c, 15 BEEG)."""
    n = len(parents)

    def count(i: int, *types: str, upto: int = MAX_LM) -> int:
        return sum(1 for lm in range(1, upto + 1) if tl[i][lm - 1] in types)

    eqs = [count(i, "basis") + Decimal(count(i, *PLUS_TYPES)) / 2 for i in range(n)]
    claiming = [count(i, *EG_TYPES) > 0 for i in range(n)]
    partner_ok = partnermonate_possible(parents)
    per_parent_limit = 14 if (single_parent_4c and partner_ok) else 12
    if n == 2:
        shared_limit = 14 if all(claiming) and partner_ok else 12
    else:
        shared_limit = per_parent_limit
    shared_used = sum(eqs, Decimal(0))
    out_parents = []
    for i, p in enumerate(parents):
        # a parent who does not claim yet would unlock the 2 Partnermonate by claiming
        pool = 14 if (n == 2 and partner_ok and (all(claiming) or not claiming[i])) else shared_limit
        left = max(min(per_parent_limit - eqs[i], pool - shared_used), Decimal(0))
        free_basis_slots = count(i, "none", upto=BASIS_LAST_LM)
        free_plus_slots = count(i, "none", upto=EG_LAST_LM)
        bonus_used = count(i, "bonus")
        leave = count(i, *EG_TYPES, "ez")
        out_parents.append({
            "label": p.label,
            "basis_used": count(i, "basis"),
            "plus_used": count(i, *PLUS_TYPES),
            "plus_with_work_used": count(i, "plus_tz"),
            "mutterschutz_basis": len(forced) if i == birthing else 0,
            "equivalents_used": eqs[i],
            "equivalents_limit": per_parent_limit,
            "equivalents_left": left,
            "basis_possible": min(int(left), free_basis_slots),
            "plus_possible": min(int(left * 2), free_plus_slots),
            "bonus_used": bonus_used,
            "bonus_left": 4 - bonus_used,
            "bonus_possible": n == 2 or single_parent_4c,
            "elternzeit_used": leave if p.employee else None,
            "elternzeit_left": (MAX_LM - leave) if p.employee else None,
        })
    partner = None
    if n == 2:
        partner = ("unavailable" if not partner_ok else "unlocked" if all(claiming) else
                   "available" if any(claiming) else "not_used")
    return {
        "shared_limit": shared_limit,
        "shared_max": 14 if (n == 2 or single_parent_4c) and partner_ok else 12,
        "shared_used": shared_used,
        "shared_left": max(Decimal(shared_limit) - shared_used, Decimal(0)),
        "partnermonate": partner,
        "bonus_max": 4,
        "parents": out_parents,
    }


def _elternzeit(tl: list[list[str]], parents: list[ParentContext], birth: date, birthing: int | None,
                ms_end: date | None) -> list[dict]:
    out = []
    for i, p in enumerate(parents):
        leave = [lm for lm in range(1, MAX_LM + 1) if tl[i][lm - 1] in (*EG_TYPES, "ez")]
        info: dict = {"label": p.label, "blocks": [], "notes": []}
        if not p.employee:
            if leave:
                info["notes"].append("Elternzeit is a right of employees; without an employment relationship no "
                                     "Elternzeit request is needed (§ 15 Abs. 1 BEEG).")
            out.append(info)
            continue
        for first, last in _runs(leave):
            start = lebensmonat(birth, first)[0]
            end = lebensmonat(birth, last)[1]
            note = None
            if i == birthing and ms_end is not None and start <= ms_end:
                start = ms_end + timedelta(days=1)
                note = "Starts after Mutterschutz; the Mutterschutz period counts towards Elternzeit (§ 15 Abs. 2 Satz 3)."
            if start > end:
                continue  # entirely covered by Mutterschutz
            info["blocks"].append({
                "from_lm": first, "to_lm": last, "start": start, "end": end,
                "months": last - first + 1,
                "request_by": start - NOTICE,
                "protection_from": start - PROTECTION_LEAD,
                "note": note,
            })
        if len(info["blocks"]) > 3:
            info["notes"].append("More than 3 periods need the employer's consent (§ 16 Abs. 1 Satz 6 BEEG).")
        if info["blocks"]:
            info["notes"].append("Request in text form (e.g. e-mail with all details) at least 7 weeks before each "
                                 "start, and state all periods within the first 2 years at once (§ 16 Abs. 1 BEEG).")
            if any(t in WORK_TYPES for t in tl[i]) and p.part_time_hours > 0:
                info["notes"].append("Part-time during Elternzeit: max. 32 h. Legal claim to 15–32 h if the employer "
                                     "has more than 15 employees and you have been employed > 6 months; request it "
                                     "7 weeks ahead (§ 15 Abs. 4, 7 BEEG).")
            if p.civil_servant:
                info["notes"].append("Civil servants: the Elternzeit regulation of the federal state or the Bund "
                                     "applies instead of §§ 15, 16 BEEG – check its deadlines.")
        out.append(info)
    return out


def presets(n_parents: int, first: int, single_parent_4c: bool) -> list[dict]:
    """Common plan shapes to compare. `first` is the birthing (or first) parent."""

    def blank() -> list[list[str]]:
        return [["none"] * MAX_LM for _ in range(n_parents)]

    def fill(tl: list[list[str]], i: int, frm: int, to: int, kind: str) -> None:
        for lm in range(frm, to + 1):
            tl[i][lm - 1] = kind

    out = []
    if n_parents == 2:
        a, b = first, 1 - first
        tl = blank(); fill(tl, a, 1, 12, "basis"); fill(tl, b, 13, 14, "basis")
        out.append({"id": "classic", "name": "Classic: 12 + 2 Basis months",
                    "description": "One parent 12 Basis months, the other the 2 Partnermonate afterwards.", "timeline": tl})
        tl = blank(); fill(tl, a, 1, 7, "basis"); fill(tl, b, 8, 14, "basis")
        out.append({"id": "split", "name": "Split: 7 + 7 Basis months",
                    "description": "Both parents take 7 Basis months one after the other.", "timeline": tl})
        tl = blank(); fill(tl, a, 1, 6, "basis"); fill(tl, a, 7, 18, "plus"); fill(tl, b, 13, 14, "basis")
        out.append({"id": "plus", "name": "Longer: Basis + ElterngeldPlus",
                    "description": "6 Basis then 12 Plus months for one parent (until month 18); the other parent "
                                   "takes 2 Basis months. Same budget, spread over a longer time.", "timeline": tl})
        tl = blank(); fill(tl, a, 1, 12, "basis"); fill(tl, b, 13, 14, "basis")
        fill(tl, a, 15, 18, "bonus"); fill(tl, b, 15, 18, "bonus")
        out.append({"id": "bonus", "name": "Classic + Partnerschaftsbonus",
                    "description": "Classic plan plus 4 bonus months for each parent (months 15–18) while both work "
                                   "24–32 h/week.", "timeline": tl})
    else:
        a = 0
        cap = 14 if single_parent_4c else 12
        tl = blank(); fill(tl, a, 1, cap, "basis")
        out.append({"id": "basis", "name": f"{cap} Basis months", "description": "All Basis months in one go.", "timeline": tl})
        half = cap // 2
        tl = blank(); fill(tl, a, 1, half, "basis"); fill(tl, a, half + 1, half + cap, "plus")
        out.append({"id": "plus", "name": "Longer: Basis + ElterngeldPlus",
                    "description": f"{half} Basis then {cap} Plus months – same budget, longer coverage.", "timeline": tl})
        if single_parent_4c:
            tl = blank(); fill(tl, a, 1, cap, "basis"); fill(tl, a, 15, 18, "bonus")
            out.append({"id": "bonus", "name": "Basis + Partnerschaftsbonus (§ 4c)",
                        "description": "14 Basis months plus 4 bonus months while working 24–32 h/week.", "timeline": tl})
    return out
