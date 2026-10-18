"""Vacation days, pension points and health insurance during Mutterschutz and Elternzeit.

Vacation  – § 24 MuSchG: Mutterschutz counts as time worked. § 17 BEEG: the employer *may*
            reduce leave by 1/12 per full calendar month of Elternzeit (only by declaration,
            BAG 19.03.2019 – 9 AZR 362/18); not if working part-time for that employer.
Pension   – § 70 Abs. 1 SGB VI: pension points = gross pay (up to the ceiling) / average
            earnings. §§ 56, 70 Abs. 2: Kindererziehungszeit, 0.0833 points per month for 36
            months from the month after birth, credited to one parent, added on top of salary
            points up to the ceiling. Mutterschutz is an Anrechnungszeit (§ 58), no direct points.
Health    – §§ 192, 224 SGB V: compulsory members stay insured contribution-free while
            receiving Mutterschaftsgeld/Elterngeld or on Elternzeit. Voluntary members pay at
            least on 1/90 of the Bezugsgröße per day (§ 240 Abs. 4), not while receiving
            Mutterschaftsgeld. Private: premium continues; employer subsidy only on salary
            (§ 257 Abs. 2). Child: family insurance (§ 10), exception in § 10 Abs. 3.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from . import params as P
from .elterngeld import ZERO, Erwerbsart, cent
from .plan import EG_TYPES, MAX_LM, add_months, lebensmonat


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    first = date(y, m, 1)
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return first, nxt - timedelta(days=1)


def _lm_of(birth: date, d: date) -> int:
    lm = 1
    while lebensmonat(birth, lm)[1] < d:
        lm += 1
    return lm


# ---------------------------------------------------------------- vacation
def vacation(parent, plan, i: int, birth: date) -> dict | None:
    days = parent.vacation_days
    if days is None or parent.erwerbsart == Erwerbsart.KEINE:
        return None
    blocks = plan.elternzeit[i]["blocks"] if i < len(plan.elternzeit) else []
    reducible: list[tuple[int, int]] = []
    part_time: list[tuple[int, int]] = []
    for b in blocks:
        for y, m in _month_iter(b["start"], b["end"]):
            first, last = _month_bounds(y, m)
            if first < b["start"] or last > b["end"]:
                continue  # only full calendar months count (§ 17 Abs. 1 BEEG)
            lms = range(_lm_of(birth, first), _lm_of(birth, last) + 1)
            works = any(plan.hours and lm <= MAX_LM and plan.hours[i][lm - 1] > 0 for lm in lms)
            (part_time if works else reducible).append((y, m))
    years = sorted({y for b in blocks for y in range(b["start"].year, b["end"].year + 1)})
    rows = []
    for y in years:
        months = [m for (yy, m) in reducible if yy == y]
        reduction = (Decimal(days) * len(months) / 12).quantize(Decimal("0.01"))
        rows.append({
            "year": y, "entitlement": days, "full_months": len(months),
            "months": [f"{m:02d}/{y}" for m in months],
            "part_time_months": [f"{m:02d}/{yy}" for (yy, m) in part_time if yy == y],
            "max_reduction": reduction, "remaining_if_reduced": Decimal(days) - reduction,
        })
    return {"label": parent.label, "days_per_year": days, "years": rows,
            "civil_servant": parent.erwerbsart == Erwerbsart.BEAMT}


# ---------------------------------------------------------------- pension
def pension(parents, plan, birth: date, kez_parent: int | None, ms_start: date | None, birthing: int | None) -> dict:
    out = []
    for i, p in enumerate(parents):
        if p.erwerbsart == Erwerbsart.BEAMT:
            out.append({"label": p.label, "status": "beamt"})
            continue
        first_c = 0
        if i == birthing and ms_start is not None:
            first_c = -((birth.year - ms_start.year) * 12 + birth.month - ms_start.month)
        base_ep = actual_ep = kez_ep = kez_capped = ZERO
        years_used: set[int] = set()
        for c in range(first_c, P.KEZ_MONTHS + 1):
            d = add_months(date(birth.year, birth.month, 1), c)
            sy = P.social_year(d.year)
            years_used.add(d.year)
            cap = sy.bbg_rv / 12
            baseline = p.average_gross if p.erwerbsart != Erwerbsart.KEINE else ZERO
            if c < 0:
                gross = ZERO  # Mutterschutz before birth: Mutterschaftsgeld carries no pension contributions
            elif c + 1 <= len(plan.rows):
                gross = Decimal(plan.rows[c]["parents"][i].get("gross_pay", ZERO))
            else:
                gross = baseline
            ep_base = min(baseline, cap) / sy.durchschnittsentgelt
            ep_sal = min(gross, cap) / sy.durchschnittsentgelt
            base_ep += ep_base
            actual_ep += ep_sal
            if kez_parent == i and 1 <= c <= P.KEZ_MONTHS:
                kez_ep += P.KEZ_EP_PER_MONTH
                kez_capped += max(min(P.KEZ_EP_PER_MONTH, cap / sy.durchschnittsentgelt - ep_sal), ZERO)
        total = actual_ep + kez_capped
        q = Decimal("0.0001")
        out.append({
            "label": p.label, "status": "grv",
            "window": f"{add_months(date(birth.year, birth.month, 1), first_c).strftime('%m/%Y')}–"
                      f"{add_months(date(birth.year, birth.month, 1), P.KEZ_MONTHS).strftime('%m/%Y')}",
            "points_without_child": base_ep.quantize(q),
            "points_from_salary": actual_ep.quantize(q),
            "points_kez": kez_capped.quantize(q),
            "points_kez_uncapped": kez_ep.quantize(q),
            "points_total": total.quantize(q),
            "difference": (total - base_ep).quantize(q),
            "pension_per_month_difference": cent((total - base_ep) * P.RENTENWERT),
            "pension_per_month_kez": cent(kez_capped * P.RENTENWERT),
            "estimated_years": sorted(y for y in years_used if y > max(P.SOCIAL_YEARS)),
        })
    return {"parents": out, "kez_parent": kez_parent, "rentenwert": P.RENTENWERT,
            "kez_months": P.KEZ_MONTHS}


# ---------------------------------------------------------------- health insurance
def _pv_an_rate(children: int) -> Decimal:
    """Employee share of care insurance after the birth (no childless surcharge)."""
    return P.PV_TOTAL / 2 - P.PV_CHILD_REDUCTION * max(0, min(children, 5) - 1)


def health(parents, plan, birth: date, children: int, household: str, kv_art) -> dict:
    out = []
    for i, p in enumerate(parents):
        art = kv_art(p)
        phases: list[dict] = []
        for lm in range(1, max(plan.plan_end_lm, 1) + 1):
            row = plan.rows[lm - 1]
            cell = row["parents"][i]
            sy = P.social_year(row["start"].year)
            zb = sy.avg_zusatzbeitrag_pct / 100
            gross = Decimal(cell.get("gross_pay", ZERO))
            mg_full = cell.get("mutterschutz_days", 0) >= (row["end"] - row["start"]).days + 1
            kind = cell["type"]
            if art in ("gkv_pflicht", "gkv_freiwillig") and gross > 0:
                base = min(gross, sy.bbg_kv / 12)
                amount = cent(base * (P.KV_GENERAL / 2 + zb / 2) + base * _pv_an_rate(children))
                status, text = "salary", "Employee share on the salary (employer pays the other half)"
            elif art == "gkv_pflicht":
                amount = ZERO
                status = "free"
                text = ("Insured without contributions – Mutterschaftsgeld" if cell.get("mutterschutz_days")
                        else "Insured without contributions – Elterngeld" if kind in EG_TYPES
                        else "Insured without contributions – Elternzeit" if kind == "ez"
                        else "No salary entered for this month")
            elif art == "gkv_freiwillig":
                if mg_full:
                    amount, status, text = ZERO, "free", "No contributions while Mutterschaftsgeld is paid (§ 224 SGB V)"
                else:
                    base = sy.bezugsgroesse_month / 3  # 1/90 of the Bezugsgröße per day (§ 240 Abs. 4 SGB V)
                    amount = cent(base * (P.KV_REDUCED + zb + P.PV_TOTAL - P.PV_CHILD_REDUCTION * max(0, min(children, 5) - 1)))
                    status = "minimum"
                    text = "Minimum contribution of voluntary members, paid in full by you (no employer share)"
            else:
                premium = p.private_premium
                if premium is None:
                    amount, status = None, "private"
                    text = "Private premium continues" + ("; employer subsidy only on salary" if gross <= 0 else "")
                elif gross > 0:
                    base = min(gross, sy.bbg_kv / 12)
                    subsidy = min(premium / 2, cent(base * (P.KV_GENERAL / 2 + zb / 2) + base * P.PV_TOTAL / 2))
                    amount, status, text = cent(premium - subsidy), "private", "Private premium minus employer subsidy"
                else:
                    amount, status, text = cent(premium), "private", "Full private premium – no employer subsidy without salary (§ 257 SGB V)"
            key = (status, text, amount)
            if phases and phases[-1]["key"] == key:
                phases[-1]["to_lm"] = lm
            else:
                phases.append({"key": key, "from_lm": lm, "to_lm": lm, "status": status, "text": text, "per_month": amount})
        for ph in phases:
            ph.pop("key")
        out.append({"label": p.label, "kv_art": art, "phases": phases})

    # child (§ 10 SGB V)
    arts = [kv_art(p) for p in parents]
    gkv = [i for i, a in enumerate(arts) if a.startswith("gkv")]
    sy = P.social_year(birth.year)
    if not gkv:
        child = {"status": "private", "text": "Both parents are privately insured: the child needs its own private policy."}
    elif household == "married" and len(parents) == 2 and len(gkv) == 1:
        g, o = gkv[0], 1 - gkv[0]
        other_income = parents[o].average_gross
        if other_income > sy.jaeg / 12 and other_income > parents[g].average_gross:
            child = {"status": "excluded", "text": (
                f"No free family insurance: {parents[o].label} is privately insured, earns more than "
                f"{cent(sy.jaeg / 12)} € a month (1/12 of the JAEG {sy.year}) and more than {parents[g].label} "
                "(§ 10 Abs. 3 SGB V). The child needs private or voluntary insurance.")}
        else:
            child = {"status": "family", "text": f"Free family insurance through {parents[g].label} (§ 10 SGB V)."}
    else:
        child = {"status": "family", "text": f"Free family insurance through {parents[gkv[0]].label} (§ 10 SGB V)."}
    surcharge_end = [{"label": parents[i].label} for i in gkv]
    return {"parents": out, "child": child, "pv_childless_ends_for": surcharge_end}


# ---------------------------------------------------------------- who takes what
def kez_advice(by_parent: dict[int, dict], parents, birthing: int | None) -> dict | None:
    """Compare the household pension points for each possible Kindererziehungszeit assignment.

    § 56 Abs. 2 SGB VI: credited to the mother unless the parents declare otherwise jointly;
    the declaration works for future months and up to 2 months back. § 56 Abs. 4: parents
    whose own pension system already credits child-raising (civil servants) are excluded.
    § 57: the Kinderberücksichtigungszeit (up to age 10) follows the same assignment.
    """
    if not by_parent:
        return None
    options = []
    for i, res in by_parent.items():
        grv = [x for x in res["parents"] if x["status"] == "grv"]
        points = sum((x["points_total"] for x in grv), ZERO)
        options.append({"parent": i, "label": parents[i].label, "household_points": points,
                        "household_pension_per_month": cent(points * P.RENTENWERT),
                        "kez_points": res["parents"][i]["points_kez"]})
    best = max(options, key=lambda o: o["household_points"])
    others = [o for o in options if o is not best]
    margin = best["household_points"] - max((o["household_points"] for o in others), default=best["household_points"])
    tie = bool(others) and margin < Decimal("0.0001")
    if tie and birthing is not None and birthing in by_parent:
        best = next(o for o in options if o["parent"] == birthing)
    excluded = [p.label for i, p in enumerate(parents) if i not in by_parent]
    return {
        "suggested": best["parent"], "tie": tie, "margin_points": margin.quantize(Decimal("0.0001")),
        "margin_per_month": cent(margin * P.RENTENWERT), "options": options, "excluded": excluded,
    }


def child_insurance_advice(parents, kv_art, household: str, child: dict) -> dict:
    arts = [kv_art(p) for p in parents]
    gkv = [i for i, a in enumerate(arts) if a.startswith("gkv")]
    beamt = [i for i, p in enumerate(parents) if p.erwerbsart == Erwerbsart.BEAMT and arts[i] == "privat"]
    if child["status"] == "family" and len(gkv) == len(parents):
        return {"suggested": None, "status": "either",
                "text": "Both parents are statutory insured: family insurance is free through either of you "
                        "(§ 10 SGB V). It makes no difference to the cost – pick one and register the child "
                        "with that Krankenkasse after the birth."}
    if child["status"] == "family":
        g = gkv[0]
        return {"suggested": g, "status": "family",
                "text": f"Insure the child through {parents[g].label}: family insurance is free (§ 10 SGB V). "
                        "A private policy would cost a monthly premium on top."}
    if beamt:
        b = beamt[0]
        return {"suggested": b, "status": "beihilfe",
                "text": f"Insure the child privately through {parents[b].label}: as a civil servant, Beihilfe usually "
                        "pays 80 % of a child's costs (Bund: § 46 BBhV; the Länder are similar), so only a small "
                        "residual-cost policy is needed."}
    priv = [i for i, a in enumerate(arts) if a == "privat"]
    who = parents[priv[0]].label if priv else "the privately insured parent"
    extra = (" A voluntary statutory membership for the child is the alternative; compare both."
             if child["status"] == "excluded" else "")
    return {"suggested": priv[0] if priv else None, "status": "private",
            "text": f"The child needs its own policy. Add it to {who}'s private insurer within 2 months of the "
                    "birth: then cover starts at birth without a health check (Kindernachversicherung, § 198 VVG; "
                    f"the parent must have been insured there for at least 3 months).{extra}"}
