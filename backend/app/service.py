"""Orchestrates the full analysis for the API."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from enum import Enum
from decimal import Decimal
from typing import Any

from . import advisor as A
from . import params as P
from .bemessung import Month, bemessungszeitraum, mutterschutz_months_before_birth, steuerklassenwechsel_frist
from .eligibility import Check, Eligibility, Grundvoraussetzungen, Status, check_basics, check_income_cap
from .elterngeld import (
    ZERO,
    Abzugsmerkmale,
    Erwerbsart,
    Monatsbetraege,
    Steuerklasse,
    cent,
    ek_nach_geburt,
    elterngeld_netto,
    monatsbetraege,
)
from .fmt import eur
from .models import AnalyseRequest, ParentIn, PayslipPersonIn, ZvEPersonIn
from .mutterschutz import Mutterschaftsgeld, estimate_net_monthly, mutterschaftsgeld
from .plan import (EG_TYPES, MaternityCredit, ParentContext, PlanResult, add_months, candidate_fixes, evaluate,
                   from_counts)
from .plan import presets as plan_presets
from . import sozial
from .zve import ZvEHaushalt, ZvEPerson, freibetraege_fuer_kinder, schaetze_zve


def _jsonable(x: Any) -> Any:
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if dataclasses.is_dataclass(x):
        return _jsonable(dataclasses.asdict(x))
    return x


def _month_str(m: Month) -> str:
    return f"{m[0]}-{m[1]:02d}"


def _parse_month(s: str) -> Month:
    y, m = s.split("-")
    return int(y), int(m)


def _age(born: date, at: date) -> int:
    return at.year - born.year - ((at.month, at.day) < (born.month, born.day))


def geschwisterbonus_at(siblings: list, at: date) -> bool:
    """§ 2a Abs. 1, 2 BEEG. The newborn counts: 'two children under 3' = one sibling under 3."""
    under3 = sum(1 for s in siblings if _age(s.birth_date, at) < 3)
    under6 = sum(1 for s in siblings if _age(s.birth_date, at) < 6)
    disabled14 = sum(1 for s in siblings if s.disability and _age(s.birth_date, at) < 14)
    return under3 >= 1 or under6 >= 2 or disabled14 >= 1


def _merkmale(p: ParentIn, steuerklasse: Steuerklasse | None = None) -> Abzugsmerkmale:
    return Abzugsmerkmale(
        erwerbsart=p.erwerbsart,
        steuerklasse=steuerklasse or p.steuerklasse,
        faktor=p.faktor,
        kirchensteuer=p.kirchensteuer,
        kinderfreibetraege=p.kinderfreibetraege,
        kv_pflichtversichert=p.kv_pflichtversichert,
        rv_pflichtversichert=p.rv_pflichtversichert,
    )


def bav_tax_free_monthly(p: ParentIn, ty: P.TaxYear) -> Decimal:
    """Tax-free part of the monthly salary conversion (§ 3 Nr. 63 EStG: 8 % of the RV ceiling per year).

    Tax-free income is not part of the Steuerbrutto and therefore not counted
    for Elterngeld (Richtlinien zum BEEG 2.1.3.1.2, 2c.2.3).
    """
    return cent(min(p.bav_monthly, ty.bbg_rv * P.BAV_TAX_FREE_SHARE_OF_BBG / 12))


def elterngeld_brutto(p: ParentIn, ty: P.TaxYear) -> Decimal:
    """Monthly gross relevant for Elterngeld: regular pay minus tax-free bAV conversion."""
    return max(p.average_gross - bav_tax_free_monthly(p, ty), ZERO)


def pv_an_rate(children: int) -> Decimal:
    """Employee care-insurance rate: + 0,6 % childless surcharge (§ 55 Abs. 3 SGB XI), − 0,25 % per child
    from the 2nd to the 5th (§ 55 Abs. 3a). Assumes parents aged 23 or older."""
    if children == 0:
        return P.PV_AN_RATE + P.PV_CHILDLESS
    return P.PV_AN_RATE - P.PV_CHILD_REDUCTION * (min(children, 5) - 1)


def _children_in_cap_year(req: AnalyseRequest, ty: P.TaxYear) -> int:
    """Children already born in the cap year (the expected child is born the year after)."""
    return sum(1 for s in req.siblings if s.birth_date <= date(ty.year, 12, 31))


def _private_kv(p: ParentIn, ty: P.TaxYear, kv_base: Decimal) -> tuple[Decimal, Decimal]:
    """(annual private premium, tax-free employer subsidy) – § 257 Abs. 2 SGB V: half the premium,
    at most the employer share of the GKV rate on the salary up to the ceiling."""
    if _kv_art(p) != "privat" or not p.private_premium:
        return ZERO, ZERO
    premium = p.private_premium * 12
    if p.erwerbsart != Erwerbsart.ANGESTELLT:
        return premium, ZERO
    max_subsidy = min(kv_base, ty.bbg_kv) * (P.KV_GENERAL / 2 + ty.avg_kv_zusatzbeitrag_pct / 200 + P.PV_TOTAL / 2)
    return premium, cent(min(premium / 2, max_subsidy))


def annualise_payslip(ps: PayslipPersonIn, p: ParentIn, ty: P.TaxYear) -> ZvEPersonIn:
    """Full cap year from one payslip: Jan–month as paid (year to date), the remaining months at this
    month's values, plus one-off payments still due. Their contributions only fill the room left under
    the annual ceilings, at this month's effective rates."""
    rest = 12 - ps.month
    sv_gross = ps.brutto_ytd + rest * ps.brutto_month  # Steuer-Brutto as a proxy for the SV gross

    def annual(ytd: Decimal, month: Decimal, ceiling: Decimal) -> Decimal:
        base_month = min(ps.brutto_month, ceiling / 12)
        rate = month / base_month if base_month > 0 else ZERO
        room = max(ceiling - sv_gross, ZERO)
        return cent(ytd + rest * month + min(ps.one_off_due, room) * rate)

    rv = annual(ps.rv_ytd, ps.rv_month, ty.bbg_rv)
    premium, subsidy = _private_kv(p, ty, ty.bbg_kv)
    return ZvEPersonIn(
        jahresbrutto=ps.brutto_ytd + rest * ps.brutto_month + ps.one_off_due,
        werbungskosten=ps.werbungskosten,
        rv_arbeitnehmer=rv,
        rv_arbeitgeber=rv,  # same rate for employer and employee (§ 168 SGB VI)
        kv_arbeitnehmer=annual(ps.kv_ytd, ps.kv_month, ty.bbg_kv),
        pv_arbeitnehmer=annual(ps.pv_ytd, ps.pv_month, ty.bbg_kv),
        alv_arbeitnehmer=annual(ps.alv_ytd, ps.alv_month, ty.bbg_rv),
        krankengeldanspruch=ps.kv_month > 0,
        private_kv_pv_basis=premium,
        private_kv_ag_zuschuss=subsidy,
        rv_frei_mit_versorgung=p.erwerbsart == Erwerbsart.BEAMT,
        pending_one_off=ps.one_off_due,
        bav_existing=cent(p.bav_monthly * 12),
    )


def _payslip_notes(req: AnalyseRequest, payslips: list[PayslipPersonIn], ty: P.TaxYear) -> list[str]:
    notes = []
    for ps, p in zip(payslips, req.parents):
        due = f", plus {eur(ps.one_off_due)} one-off payments still due" if ps.one_off_due else ""
        rest = (f"{ps.month + 1:02d}–12/{ty.year} at that month's values" if ps.month < 12
                else "no months left to extrapolate")
        notes.append(f"{p.label}: from the payslip of {ps.month:02d}/{ty.year} – 01–{ps.month:02d}/{ty.year} as paid, "
                     f"{rest}{due}.")
        if p.monthly_gross and ps.brutto_month > p.monthly_gross * Decimal("1.5"):
            notes.append(f"{p.label}: this month's gross ({eur(ps.brutto_month)}) is far above the regular monthly "
                         "pay – if it contains a one-off payment, use a regular month's payslip, or the rest of the "
                         "year is overstated.")
    notes.append("Replace these figures with the Lohnsteuerbescheinigung once you have it (usually by end of February).")
    return notes


def _quick_zve_person(p: ParentIn, ty: P.TaxYear, children: int = 0) -> ZvEPersonIn:
    """Rough annual figures from the monthly gross plus one-off payments, minus the
    tax-free company pension conversion (used if no Lohnsteuerbescheinigung data was entered)."""
    if p.erwerbsart == Erwerbsart.MINIJOB:
        return ZvEPersonIn()  # flat-taxed (§ 40a Abs. 2 EStG): not part of the zvE
    gross = p.average_gross * 12 + p.one_off_annual
    bav = p.bav_monthly * 12
    jb = cent(max(gross - min(bav, ty.bbg_rv * P.BAV_TAX_FREE_SHARE_OF_BBG), ZERO))
    sv_gross = max(gross - min(bav, ty.bbg_rv * P.BAV_SV_FREE_SHARE_OF_BBG), ZERO)  # § 1 Abs. 1 Nr. 9 SvEV
    angestellt = p.erwerbsart == Erwerbsart.ANGESTELLT
    rv_base = min(sv_gross, ty.bbg_rv)
    kv_base = min(sv_gross, ty.bbg_kv)
    # compulsory and voluntary members alike pay the employee share (§ 10 Abs. 1 Nr. 3 EStG)
    gkv = angestellt and _kv_art(p) != "privat"
    premium, subsidy = _private_kv(p, ty, kv_base)
    return ZvEPersonIn(
        jahresbrutto=jb,
        rv_arbeitnehmer=cent(rv_base * ty.rv_rate_total / 2) if angestellt else ZERO,
        rv_arbeitgeber=cent(rv_base * ty.rv_rate_total / 2) if angestellt else ZERO,
        kv_arbeitnehmer=cent(kv_base * (P.KV_AN_GENERAL_RATE + ty.avg_kv_zusatzbeitrag_pct / 200)) if gkv else ZERO,
        pv_arbeitnehmer=cent(kv_base * pv_an_rate(children)) if gkv else ZERO,
        alv_arbeitnehmer=cent(rv_base * P.ALV_AN_RATE) if angestellt else ZERO,
        krankengeldanspruch=gkv,
        private_kv_pv_basis=premium,
        private_kv_ag_zuschuss=subsidy,
        rv_frei_mit_versorgung=p.erwerbsart == Erwerbsart.BEAMT,
        pending_one_off=p.one_off_pending,
        bav_existing=cent(bav),
    )


@dataclasses.dataclass
class ParentOutcome:
    label: str
    merkmale: Abzugsmerkmale
    bmz: list[Month]
    excluded: list[Month]
    netto: Any
    amounts: Monatsbetraege
    checks: list[Check]
    bmz_early: list[Month]  # if the child is born in the calendar month before the expected one


def _excluded(req: AnalyseRequest, p: ParentIn, birth: date) -> set[Month]:
    """§ 2b Abs. 1 Satz 2 BEEG: entered exclusions plus the Mutterschutz months before `birth`."""
    excluded = {_parse_month(s) for s in p.extra_excluded_months}
    if p.birthing_parent and p.erwerbsart != Erwerbsart.KEINE and not p.include_mutterschutz_months:
        excluded |= mutterschutz_months_before_birth(req.due_date or req.birth_date, birth)
    return excluded


def _early_birth(birth: date) -> date:
    return birth.replace(day=1) - timedelta(days=1)


def _parent_outcome(req: AnalyseRequest, p: ParentIn, gb: bool, steuerklasse: Steuerklasse | None = None) -> ParentOutcome:
    m = _merkmale(p, steuerklasse)
    excluded = _excluded(req, p, req.birth_date)
    bmz = bemessungszeitraum(req.birth_date, excluded)
    early = _early_birth(req.birth_date)
    bmz_early = bemessungszeitraum(early, _excluded(req, p, early))
    netto = elterngeld_netto(elterngeld_brutto(p, P.tax_year_for_birth(req.birth_date)), m, req.birth_date)
    pt_gross, _ = p.part_time
    ek_nach = ek_nach_geburt(pt_gross, m, req.birth_date) if pt_gross else None
    amounts = monatsbetraege(netto.elterngeld_netto, geschwisterbonus_berechtigt=gb,
                             anzahl_kinder=req.children_expected, ek_nach=ek_nach)
    checks = check_basics(Grundvoraussetzungen(
        wochenstunden_waehrend_bezug=p.part_time_hours, **p.basics.model_dump()))
    return ParentOutcome(p.label, m, bmz, sorted(e for e in excluded if e < (req.birth_date.year, req.birth_date.month)),
                         netto, amounts, checks, bmz_early)


def _first_parent(req: AnalyseRequest) -> int:
    return next((i for i, p in enumerate(req.parents) if p.birthing_parent), 0)


def _timeline(req: AnalyseRequest) -> list[list[str]]:
    if req.timeline is not None:
        return req.timeline
    counts = [(p.plan.basis_months, p.plan.plus_months, p.plan.bonus_months) for p in req.parents]
    return from_counts(counts, _first_parent(req), works=[bool(p.part_time[0]) for p in req.parents])


def _kv_art(p: ParentIn) -> str:
    if p.kv_art:
        return p.kv_art
    if p.erwerbsart == Erwerbsart.BEAMT:
        return "privat"  # civil servants: Beihilfe plus private cover unless stated otherwise
    return "gkv_pflicht" if p.kv_pflichtversichert else "gkv_freiwillig"


def _part_time_net(req: AnalyseRequest, p: ParentIn) -> Decimal | None:
    """Take-home pay of the part-time job (real tax class and contributions, child now born)."""
    gross, _ = p.part_time
    if not gross:
        return None
    return estimate_net_monthly(gross, erwerbsart=p.erwerbsart, steuerklasse=p.steuerklasse, faktor=p.faktor,
                                kirchensteuer=p.kirchensteuer, kinderfreibetraege=p.kinderfreibetraege,
                                kv_art=_kv_art(p), children_under_25=len(req.siblings) + req.children_expected,
                                year=req.birth_date.year)


def _part_time_json(req: AnalyseRequest, p: ParentIn) -> dict | None:
    gross, source = p.part_time
    if not gross:
        return None
    return {"gross": gross, "source": source, "hours": p.part_time_hours, "weekly_hours": p.weekly_hours,
            "net_pay": _part_time_net(req, p)}


def _maternity(req: AnalyseRequest) -> tuple[int, Mutterschaftsgeld] | None:
    """Mutterschaftsgeld of the birthing parent (None if nobody gives birth in this household).
    Depends only on the request, so it is computed once per request."""
    if "maternity" not in req._memo:
        req._memo["maternity"] = _compute_maternity(req)
    return req._memo["maternity"]


def _compute_maternity(req: AnalyseRequest) -> tuple[int, Mutterschaftsgeld] | None:
    i = next((k for k, p in enumerate(req.parents) if p.birthing_parent), None)
    if i is None:
        return None
    p = req.parents[i]
    weeks = 12 if (req.children_expected > 1 or req.premature_or_disability) else 8
    due = req.due_date or req.birth_date
    ty = P.tax_year_for_birth(req.birth_date)
    gross = elterngeld_brutto(p, ty)
    if p.net_monthly is not None:
        net, source = p.net_monthly, "input"
    else:
        start_year = (due - timedelta(weeks=6) - timedelta(days=45)).year  # middle of the 3 reference months
        net = estimate_net_monthly(gross, erwerbsart=p.erwerbsart, steuerklasse=p.steuerklasse, faktor=p.faktor,
                                   kirchensteuer=p.kirchensteuer, kinderfreibetraege=p.kinderfreibetraege,
                                   kv_art=_kv_art(p), children_under_25=len(req.siblings), year=start_year)
        source = "estimate"
    return i, mutterschaftsgeld(due=due, birth=req.birth_date, weeks_after=weeks, erwerbsart=p.erwerbsart,
                                kv_art=_kv_art(p), net_monthly=net, net_source=source)


def _salary(req: AnalyseRequest, p: ParentIn):
    """weekly hours -> (gross, net) per month from the employer, pro rata to the contract hours."""
    if p.erwerbsart == Erwerbsart.KEINE or p.average_gross <= 0:
        return None
    pt_gross, pt_source = p.part_time
    cache: dict[Decimal, tuple[Decimal, Decimal]] = {}

    def pay(hours: Decimal) -> tuple[Decimal, Decimal]:
        if hours not in cache:
            if pt_source == "input" and hours == p.part_time_hours:
                gross = pt_gross  # the entered part-time gross for exactly these hours
            else:
                gross = cent(p.average_gross * hours / p.weekly_hours)
            net = estimate_net_monthly(gross, erwerbsart=p.erwerbsart, steuerklasse=p.steuerklasse, faktor=p.faktor,
                                       kirchensteuer=p.kirchensteuer, kinderfreibetraege=p.kinderfreibetraege,
                                       kv_art=_kv_art(p), children_under_25=len(req.siblings) + req.children_expected,
                                       year=req.birth_date.year)
            cache[hours] = (gross, net)
        return cache[hours]

    return pay


def _work_amounts(req: AnalyseRequest, o: "ParentOutcome"):
    """Elterngeld with income in the Bezugszeitraum, per group average (§ 2 Abs. 3 BEEG)."""
    def amounts(avg_basis: Decimal | None, avg_plus: Decimal | None, gb: bool):
        def calc(avg: Decimal | None):
            if not avg:
                return None
            ek_nach = ek_nach_geburt(avg, o.merkmale, req.birth_date)
            return monatsbetraege(o.netto.elterngeld_netto, geschwisterbonus_berechtigt=gb,
                                  anzahl_kinder=req.children_expected, ek_nach=ek_nach)
        b, p = calc(avg_basis), calc(avg_plus)
        return (b.basis_mit_teilzeit if b else None, p.plus_mit_teilzeit if p else None)
    return amounts


_FROM_REQUEST = object()


def _plan_inputs(req: AnalyseRequest, outcomes: list[ParentOutcome]) -> tuple[list[ParentContext], dict]:
    """Parent contexts and the keyword arguments shared by evaluate() and candidate_fixes()."""
    mat = _maternity(req)
    birthing = mat[0] if mat and mat[1].status != "none" else None
    credit = None
    if birthing is not None:
        m = mat[1]
        credit = MaternityCredit(end=m.fristen.end, credited_per_day=m.credited_per_day, paid_per_day=m.paid_per_day)
    contexts = [
        ParentContext(
            label=p.label,
            amounts=o.amounts,
            amounts_plain=monatsbetraege(o.amounts.elterngeld_netto, anzahl_kinder=req.children_expected,
                                         ek_nach=o.amounts.ek_nach),
            part_time_hours=p.part_time_hours,
            part_time_net=_part_time_net(req, p),
            part_time_in_basis=p.part_time_in_basis,
            employee=p.erwerbsart != Erwerbsart.KEINE,
            earned_before=o.netto.brutto > 0,
            civil_servant=p.erwerbsart == Erwerbsart.BEAMT,
            contract_hours=p.weekly_hours,
            pay=_salary(req, p),
            work_amounts=_work_amounts(req, o),
        )
        for p, o in zip(req.parents, outcomes)
    ]

    def gb_active(lm: int) -> bool:
        return geschwisterbonus_at(req.siblings, add_months(req.birth_date, lm - 1))

    # § 4 Abs. 6 Satz 4 BEEG: simultaneous Basis allowed for multiples, premature births, disability
    exception = req.children_expected > 1 or req.premature_or_disability
    return contexts, {"birth": req.birth_date, "birthing": birthing, "maternity": credit,
                      "single_parent_4c": req.single_parent_4c, "simultaneous_exception": exception,
                      "gb_active": gb_active}


def _plan(req: AnalyseRequest, outcomes: list[ParentOutcome], timeline: list[list[str]] | None = None,
          hours=_FROM_REQUEST) -> PlanResult:
    if hours is _FROM_REQUEST:
        hours = req.hours if timeline is None else None  # presets start from default hours
    contexts, kw = _plan_inputs(req, outcomes)
    return evaluate(timeline if timeline is not None else _timeline(req), contexts, hours=hours, **kw)


MAX_FIXES = 3


def _plan_fixes(req: AnalyseRequest, outcomes: list[ParentOutcome], plan: PlanResult) -> list[dict]:
    """For an invalid plan: the best valid plans that change one month (or the same month for both
    parents), ranked by the household's Elterngeld. Empty if no such change exists."""
    if plan.valid:
        return []
    contexts, kw = _plan_inputs(req, outcomes)
    kw.pop("gb_active")
    candidates = candidate_fixes(plan.timeline, contexts, hours=req.hours, **kw)
    scored = []
    for c in candidates:
        r = _plan(req, outcomes, c["timeline"], hours=c["hours"])
        scored.append({**c, "totals": r.totals, "household_total": r.household_total})
    # equal amounts: prefer fewer changes, then the plainer month type
    plain = {"plus": 0, "basis": 1, "none": 2, "ez": 3, "plus_tz": 4, "bonus": 5}
    scored.sort(key=lambda c: (-c["household_total"], len(c["changes"]), max(plain[x["to"]] for x in c["changes"])))
    fixes, seen = [], set()
    for c in scored:  # one suggestion per changed month
        where = tuple((x["parent"], x["lm"]) for x in c["changes"])
        if where not in seen:
            seen.add(where)
            fixes.append(c)
    return fixes[:MAX_FIXES]


def _plan_json(plan: PlanResult) -> dict:
    return {
        "valid": plan.valid, "errors": plan.errors, "notes": plan.notes,
        "timeline": plan.timeline, "rows": plan.rows, "months": plan.months,
        "totals": plan.totals, "household_total": plan.household_total,
        "months_with_elterngeld": plan.months_with_elterngeld, "elternzeit": plan.elternzeit,
        "budget": plan.budget, "maternity_after_birth": plan.maternity_after_birth,
        "net_pay_total": plan.net_pay_total,
        "hours": plan.hours, "plan_end_lm": plan.plan_end_lm, "month_totals": plan.month_totals,
    }


def analyse(req: AnalyseRequest) -> dict:
    ty = P.tax_year_for_birth(req.birth_date)
    today = req.today or date.today()
    gb = geschwisterbonus_at(req.siblings, req.birth_date)
    outcomes = [_parent_outcome(req, p, gb) for p in req.parents]
    plan = _plan(req, outcomes)
    preset_results = []
    for pr in plan_presets(len(req.parents), _first_parent(req), req.single_parent_4c):
        r = _plan(req, outcomes, pr["timeline"])
        preset_results.append({**pr, "timeline": r.timeline, "valid": r.valid, "errors": r.errors,
                               "totals": r.totals, "household_total": r.household_total,
                               "months_with_elterngeld": r.months_with_elterngeld})

    # --- income cap -------------------------------------------------------
    z = req.zve
    from_bescheid = z.mode == "bescheid" and bool(z.bescheid_values)
    zve_detail = None
    quick = False
    payslip = z.mode == "payslip" and len(z.payslips) == len(req.parents)
    persons_in = z.persons
    if from_bescheid:
        zve_total = sum(z.bescheid_values, ZERO)
        if not z.bescheid_kfb_abgezogen:
            zve_total = max(zve_total - freibetraege_fuer_kinder(z.kinderfreibetrag_zaehler, ty), ZERO)
    else:
        if payslip:
            persons_in = [annualise_payslip(ps, p, ty) for ps, p in zip(z.payslips, req.parents)]
        elif not persons_in:
            quick = True
            children = _children_in_cap_year(req, ty)
            persons_in = [_quick_zve_person(p, ty, children) for p in req.parents]
        persons = [ZvEPerson(**pi.model_dump(exclude={"bav_existing", "pending_one_off"})) for pi in persons_in]
        res = schaetze_zve(ZvEHaushalt(
            tax_year=ty.year, personen=persons,
            zusammenveranlagung=z.zusammenveranlagung and req.household == "married",
            kinderfreibetrag_zaehler=z.kinderfreibetrag_zaehler,
            alleinerziehend=z.alleinerziehend and req.household == "single",
            kinder_im_haushalt=z.kinder_im_haushalt,
        ))
        if quick:
            res.hinweise.insert(0, "Quick estimate from 12 × monthly gross pay plus the bonuses entered (no other "
                                   "income or individual deductions). Enter Lohnsteuerbescheinigung figures for a "
                                   "better estimate.")
            res.hinweise.insert(1, (
                f"Care insurance: no child yet in {ty.year}, so the 0,6 % childless surcharge is included "
                f"(employee rate {str((pv_an_rate(0) * 100).normalize()).replace('.', ',')} %, § 55 Abs. 3 SGB XI)."
                if children == 0 else
                f"Care insurance: {children} child{'ren' if children > 1 else ''} in {ty.year} – no childless "
                f"surcharge{', reduced rate for 2+ children' if children > 1 else ''} (§ 55 Abs. 3, 3a SGB XI)."))
        if payslip:
            res.hinweise[:0] = _payslip_notes(req, z.payslips, ty)
        if quick or payslip:
            for p in req.parents:
                if _kv_art(p) == "privat" and not p.private_premium:
                    res.hinweise.insert(1, f"{p.label}: enter the private premium – without it no health-insurance "
                                           "contributions are deducted and the zvE is overstated.")
                elif _kv_art(p) == "privat":
                    res.hinweise.insert(1, f"{p.label}: the full private premium is deducted; only the basic-cover "
                                           "share (Basisabsicherung, see the insurer's annual certificate) counts.")
        zve_total = res.zve
        zve_detail = res.as_dict()
    cap_check = check_income_cap(zve_total, from_bescheid)

    eligibility = []
    for o in outcomes:
        e = Eligibility(checks=[*o.checks, cap_check])
        eligibility.append({"label": o.label, "overall": e.overall.value, "checks": _jsonable(e.checks)})

    # --- recommendations ---------------------------------------------------
    recs: list[A.Recommendation] = []
    gap = zve_total - P.INCOME_CAP_ZVE
    closable = None
    if gap > 0 or cap_check.status == Status.CONDITIONAL:
        levers = []
        if persons_in:
            for p_in, parent in zip(persons_in, req.parents):
                cap = ty.altersvorsorge_hoechstbetrag
                if p_in.rv_frei_mit_versorgung:
                    cap = max(cap - min(p_in.jahresbrutto, ty.bbg_rv) * ty.rv_rate_total, ZERO)
                levers.append(A.PersonLevers(
                    label=parent.label,
                    is_employee=p_in.jahresbrutto > 0,
                    jahresbrutto=p_in.jahresbrutto,
                    rv_total=p_in.rv_arbeitnehmer + p_in.rv_arbeitgeber + p_in.basisrente_beitraege,
                    altersvorsorge_cap=cap,
                    bav_existing=p_in.bav_existing or parent.bav_monthly * 12,
                    pending_one_off=p_in.pending_one_off or parent.one_off_pending,
                ))
        path, quantified = A.eligibility_path(gap=max(gap, ZERO), tax_year=ty.year, today=today,
                                              levers=levers, from_tax_assessment=from_bescheid)
        recs.extend(path)
        if gap > 0:
            # cheapest first: deferral (no cost) -> bAV (pension, partly SV-free) -> Basisrente (cash)
            order = {"defer_bonus": 0, "bav": 1, "basisrente": 2}
            buffer = ZERO if from_bescheid else Decimal(1000)  # safety margin for estimates
            needed = gap + buffer
            combo = []
            for r in sorted((r for r in path if r.impact_eur and r.id.split("_")[0] in ("defer", "bav", "basisrente")),
                            key=lambda r: order["defer_bonus" if r.id.startswith("defer") else r.id.split("_")[0]]):
                if needed <= 0:
                    break
                use = min(r.impact_eur, needed)
                combo.append({"id": r.id, "title": r.title, "amount": cent(use)})
                needed -= use
            closable = {
                "gap": cent(gap),
                "safety_buffer": buffer,
                "quantified_levers": cent(quantified),
                "closable_with_quantified_levers": quantified >= gap + buffer,
                "cap_year_open": today <= date(ty.year, 12, 31),
                "suggested_combination": combo if needed <= 0 else [],
            }

    amount_recs = _amount_recommendations(req, outcomes, plan, today, preset_results)
    if cap_check.status != Status.MET:
        for r in amount_recs:
            r.caveats.insert(0, "Only relevant once the income cap is met.")
    recs.extend(amount_recs)
    recs.extend(_process_recommendations(req, outcomes, gb))

    return _jsonable({
        "scope": {
            "birth_date": req.birth_date,
            "tax_year_before_birth": ty.year,
            "pap": f"Lohnsteuer-Programmablaufplan {ty.year} (BMF, bundled verbatim)",
            "kv_zusatzbeitrag_used_pct": ty.avg_kv_zusatzbeitrag_pct,
            "income_cap": P.INCOME_CAP_ZVE,
        },
        "parents": [
            {
                "label": o.label,
                "bemessungszeitraum": [_month_str(m) for m in o.bmz],
                "excluded_months": [_month_str(m) for m in o.excluded],
                "netto": o.netto,
                "bonuses_excluded": p.one_off_annual,
                "part_time": _part_time_json(req, p),
                "works": p.erwerbsart != Erwerbsart.KEINE and p.average_gross > 0,
                "gross_before_bav": cent(p.average_gross),
                "bav_deducted": bav_tax_free_monthly(p, P.tax_year_for_birth(req.birth_date)),
                "amounts": o.amounts,
                "minijob_midijob_note": bool(ty.geringfuegigkeitsgrenze < o.netto.brutto <= P.UEBERGANGSBEREICH_OBERGRENZE)
                or o.merkmale.erwerbsart == Erwerbsart.MINIJOB,
            }
            for o, p in zip(outcomes, req.parents)
        ],
        "geschwisterbonus": gb,
        "income_cap": {
            "source": ("steuerbescheid" if from_bescheid else "payslip" if payslip
                       else "quick_estimate" if quick else "estimate"),
            "zve_total": zve_total,
            "detail": zve_detail,
            "check": cap_check,
            "gap_analysis": closable,
        },
        "eligibility": eligibility,
        "plan": {**_plan_json(plan), "presets": preset_results, "fixes": _plan_fixes(req, outcomes, plan)},
        "mutterschutz": _maternity_json(req),
        "social": {**_social_json(req, plan), "tax_class": _tax_class_json(req, outcomes, plan, today)},
        "recommendations": [r.as_dict() for r in recs],
    })


def _social_json(req: AnalyseRequest, plan: PlanResult) -> dict:
    mat = _maternity(req)
    birthing = mat[0] if mat else None
    ms_start = mat[1].fristen.start if mat and mat[1].status != "none" else None
    kez = req.kez_parent if req.kez_parent is not None and req.kez_parent < len(req.parents) else (birthing or 0)
    children = len(req.siblings) + req.children_expected
    siblings = tuple(sb.birth_date for sb in req.siblings) + ((req.birth_date,) if req.children_expected > 1 else ())
    health = sozial.health(req.parents, plan, req.birth_date, children, req.household, _kv_art)
    # § 56 Abs. 4 SGB VI: civil servants are excluded from the Kindererziehungszeit
    candidates = [i for i, p in enumerate(req.parents) if p.erwerbsart != Erwerbsart.BEAMT]
    by_parent = {i: sozial.pension(req.parents, plan, req.birth_date, i, ms_start, birthing, siblings) for i in candidates}
    return {
        "vacation": [v for i, p in enumerate(req.parents) if (v := sozial.vacation(p, plan, i, req.birth_date))],
        "pension": sozial.pension(req.parents, plan, req.birth_date, kez, ms_start, birthing, siblings),
        "health": health,
        "kez_advice": sozial.kez_advice(by_parent, req.parents, birthing) if len(req.parents) == 2 else None,
        "child_insurance": sozial.child_insurance_advice(req.parents, _kv_art, req.household, health["child"]),
        "years": {y: {"note": s.note} for y, s in P.SOCIAL_YEARS.items()},
    }


_COMBOS = [(Steuerklasse.IV, Steuerklasse.IV), (Steuerklasse.III, Steuerklasse.V), (Steuerklasse.V, Steuerklasse.III)]


def _tax_class_json(req: AnalyseRequest, outcomes: list[ParentOutcome], plan: PlanResult, today: date) -> dict:
    """Elterngeld over the current month plan for each tax-class combination (§ 2c Abs. 3 BEEG)."""
    if req.household != "married" or len(req.parents) != 2:
        return {"applicable": False}
    current = tuple(p.steuerklasse for p in req.parents)
    combos = list(_COMBOS)
    if current not in combos:
        combos.insert(0, current)
    gb = geschwisterbonus_at(req.siblings, req.birth_date)
    year = min(max(today.year, min(P.TAX_YEARS)), max(P.TAX_YEARS))
    options = []
    for combo in combos:
        alt = outcomes if combo == current else [_parent_outcome(req, p, gb, k) for p, k in zip(req.parents, combo)]
        alt_plan = plan if combo == current else _plan(req, alt)
        net_now = sum((estimate_net_monthly(
            p.average_gross, erwerbsart=p.erwerbsart, steuerklasse=k, faktor=p.faktor, kirchensteuer=p.kirchensteuer,
            kinderfreibetraege=p.kinderfreibetraege, kv_art=_kv_art(p), children_under_25=len(req.siblings), year=year,
        ) for p, k in zip(req.parents, combo)), ZERO)
        options.append({"classes": [k.value for k in combo], "current": combo == current,
                        "elterngeld_total": alt_plan.household_total, "per_parent": alt_plan.totals,
                        "net_pay_now_per_month": net_now})
    base = next(o for o in options if o["current"])["elterngeld_total"]
    for o in options:
        o["difference"] = cent(o["elterngeld_total"] - base)
    best = max(options, key=lambda o: (o["elterngeld_total"], o["current"]))
    # the switch must be decisive for each parent whose Elterngeld rises (§ 2c Abs. 3 Satz 2 BEEG)
    current_opt = next(o for o in options if o["current"])
    gaining = [i for i in range(2) if best["per_parent"][i] > current_opt["per_parent"][i]] or [0, 1]
    latest = min((steuerklassenwechsel_frist(outcomes[i].bmz).antrag_spaetestens for i in gaining), default=None)
    # safe even if the child is born in the month before the expected one
    safe = min((steuerklassenwechsel_frist(outcomes[i].bmz_early).antrag_spaetestens for i in gaining), default=None)
    return {
        "applicable": True, "options": options, "best": best["classes"], "keep_current": best["current"],
        "deadline": (safe if today <= safe else latest) if latest else None,
        "deadline_latest": latest,
        "early_birth_risk": bool(latest) and safe < today <= latest,
        "too_late": bool(latest) and today > latest,
        "plan_valid": plan.valid,
    }


def _maternity_json(req: AnalyseRequest) -> dict | None:
    mat = _maternity(req)
    if mat is None:
        return None
    i, m = mat
    f = m.fristen
    return {
        "label": req.parents[i].label,
        "status": m.status,
        "start": f.start, "birth": f.birth, "end": f.end,
        "days_before": f.days_before, "days_after": f.days_after, "total_days": f.total_days,
        "weeks_after": f.weeks_after, "extension_days": f.extension_days,
        "net_monthly": m.net_monthly, "net_source": m.net_source, "daily_net": m.daily_net,
        "kk_per_day": m.kk_per_day, "employer_per_day": m.employer_per_day, "bas_total": m.bas_total,
        "before_birth": m.before_birth, "from_birth": m.from_birth, "total": m.total,
        "kk_total": cent(m.kk_per_day * f.total_days), "employer_total": cent(m.employer_per_day * f.total_days),
        "credited_per_day": m.credited_per_day,
    }


def _amount_recommendations(req: AnalyseRequest, outcomes: list[ParentOutcome], plan: PlanResult,
                            today: date, preset_results: list[dict]) -> list[A.Recommendation]:
    recs: list[A.Recommendation] = []
    gb = geschwisterbonus_at(req.siblings, req.birth_date)

    # Steuerklassenwechsel (married couples, both employed)
    working = [p for p in req.parents if p.erwerbsart in (Erwerbsart.ANGESTELLT, Erwerbsart.BEAMT)
               and elterngeld_brutto(p, P.tax_year_for_birth(req.birth_date)) > 0]
    if req.household == "married" and len(working) == 2 and plan.valid:
        base_total = plan.household_total
        for i in (0, 1):
            j = 1 - i
            if req.parents[i].steuerklasse == Steuerklasse.III:
                continue
            alt = [None, None]
            alt[i], alt[j] = Steuerklasse.III, Steuerklasse.V
            alt_outcomes = [_parent_outcome(req, p, gb, alt[k]) for k, p in enumerate(req.parents)]
            alt_plan = _plan(req, alt_outcomes)
            gain = alt_plan.household_total - base_total
            gain_parent = alt_plan.totals[i] - plan.totals[i]
            if gain > 1:
                recs.append(A.steuerklassen_recommendation(
                    label=req.parents[i].label, partner_label=req.parents[j].label, bmz=outcomes[i].bmz,
                    bmz_early=outcomes[i].bmz_early,
                    today=today, gain_household=cent(gain), gain_parent=cent(gain_parent),
                    current=req.parents[i].steuerklasse.value.replace("_FAKTOR", " mit Faktor"), target="III"))

    # Part-time during Plus
    for p, o in zip(req.parents, outcomes):
        r = A.part_time_recommendation(p.label, o.netto.elterngeld_netto, o.merkmale, req.birth_date,
                                       monthly_gross=p.average_gross, weekly_hours=p.weekly_hours)
        if r:
            recs.append(r)

    # Partner months / Partnerschaftsbonus (based on the month plan)
    claims = [any(t in EG_TYPES for t in row) for row in plan.timeline]
    if len(req.parents) == 2 and claims.count(False) == 1 and any(o.netto.brutto > 0 for o in outcomes):
        k = claims.index(False)
        value = cent(outcomes[k].amounts.basis * 2)
        recs.append(A.Recommendation(
            id="partnermonate", category="amount",
            title=f"Partnermonate: {req.parents[k].label} takes at least 2 months",
            detail=(f"Only if both parents claim, the couple gets 14 instead of 12 Basis months. Two Basis "
                    f"months for {req.parents[k].label} are worth about {eur(value)}."),
            legal_basis="§ 4 Abs. 3 Satz 2, Abs. 4 Satz 2 BEEG", confidence="exact", impact_eur=value))
    has_bonus = any(t == "bonus" for row in plan.timeline for t in row)
    by_id = {p["id"]: p for p in preset_results}
    base = by_id.get("classic") or by_id.get("basis")
    if not has_bonus and "bonus" in by_id and base:
        value = cent(by_id["bonus"]["household_total"] - base["household_total"])
        hours_ok = all(24 <= p.part_time_hours <= 32 for p in req.parents)
        recs.append(A.Recommendation(
            id="partnerschaftsbonus", category="amount",
            title="Partnerschaftsbonus: up to 4 extra ElterngeldPlus months each",
            detail=(f"If {'both parents work' if len(req.parents) == 2 else 'you work'} 24–32 hours/week at the same "
                    f"time for 2–4 consecutive months, each gets one extra ElterngeldPlus month per month. 4 bonus "
                    f"months add about {eur(value)} to the household (compare the presets in the planner). "
                    + ("The entered hours meet the requirement." if hours_ok else
                       "Enter planned part-time hours of 24–32 h for each parent to use it.")),
            legal_basis="§ 4b BEEG" + ("" if len(req.parents) == 2 else ", § 4c Abs. 2 BEEG"),
            confidence="exact" if all(o.amounts.plus_mit_teilzeit for o in outcomes) else "estimate",
            impact_eur=value,
            caveats=["Amounts use the planned part-time pay; without it the full Plus amount is assumed.",
                     "Each bonus month requires both parents to work 24–32 h; if one misses it, that month's bonus "
                     "is lost for both – the other bonus months and the consecutive-months rule stay intact "
                     "(§ 4b Abs. 1, 5 BEEG)."]))

    # One-off payments: no effect on Elterngeld, but on the income cap
    for p in req.parents:
        if p.one_off_annual > 0:
            recs.append(A.Recommendation(
                id=f"bonuses_{p.label}", category="info",
                title=f"{p.label}: bonuses don't raise Elterngeld – but count for the income cap",
                detail=(f"One-off payments ({eur(p.one_off_annual)} entered) are sonstige Bezüge and are left out of "
                        "the Elterngeld-Netto. They are still part of the zvE of the year before birth. Bonuses or "
                        "allowances paid regularly every month are laufender Arbeitslohn and belong in the monthly "
                        "gross pay instead."),
                legal_basis="§ 2c Abs. 1 Satz 2 BEEG; § 38a Abs. 1 Satz 3, § 39b Abs. 3 EStG; R 39b.2 LStR",
                confidence="exact"))

    # Church tax (information only)
    for p, o in zip(req.parents, outcomes):
        if p.kirchensteuer and o.netto.brutto > 0:
            without = elterngeld_netto(o.netto.brutto, dataclasses.replace(o.merkmale, kirchensteuer=False),
                                       req.birth_date)
            delta = monatsbetraege(without.elterngeld_netto).basis - monatsbetraege(o.netto.elterngeld_netto).basis
            if delta > 0:
                recs.append(A.Recommendation(
                    id=f"kirchensteuer_{p.label}", category="info",
                    title=f"{p.label}: effect of church tax",
                    detail=(f"The flat 8 % church tax lowers the Elterngeld-Netto; without it the Basiselterngeld "
                            f"would be about {eur(delta, True)}/month higher. This only applies if no church tax "
                            "was due in the majority of the months of the Bemessungszeitraum. A personal decision "
                            "– mentioned for completeness only."),
                    legal_basis="§ 2e Abs. 5, § 2c Abs. 3 BEEG", confidence="exact", impact_eur=delta))
    return recs


def _process_recommendations(req: AnalyseRequest, outcomes: list[ParentOutcome], gb: bool) -> list[A.Recommendation]:
    recs = []
    for p, o in zip(req.parents, outcomes):
        if p.erwerbsart == Erwerbsart.KEINE:
            continue
        months = ", ".join(_month_str(m) for m in o.bmz)
        excl = ", ".join(_month_str(m) for m in o.excluded) or "none"
        recs.append(A.Recommendation(
            id=f"bmz_{p.label}", category="process",
            title=f"{p.label}: payslips that count (Bemessungszeitraum)",
            detail=(f"Use the regular gross pay (without one-off payments) of: {months}. Excluded months: {excl}. "
                    "Months with pregnancy-related illness and income loss, or with Elterngeld for an older child "
                    "(first 14 months), are also skipped – enter them as excluded months if they apply."),
            legal_basis="§ 2b Abs. 1, § 2c Abs. 1 Satz 2 BEEG", confidence="exact"))
    deadline = add_months(req.birth_date, 4) - timedelta(days=1)
    recs.append(A.Recommendation(
        id="antrag", category="process", title="Apply in time – retroactive payment is limited to 3 months",
        detail=("Elterngeld is paid retroactively only for the last 3 Lebensmonate before the Lebensmonat in "
                f"which the application arrives. To receive it from Lebensmonat 1, the application must arrive by "
                f"{deadline.strftime('%d.%m.%Y')} (end of Lebensmonat 4). Apply soon after birth."),
        legal_basis="§ 7 Abs. 1 BEEG", confidence="exact", deadline=deadline))
    if gb:
        last = None  # last Lebensmonat with the bonus
        for lm in range(2, 33):
            if not geschwisterbonus_at(req.siblings, add_months(req.birth_date, lm - 1)):
                last = lm - 1
                break
        end = add_months(req.birth_date, last) - timedelta(days=1) if last else None
        recs.append(A.Recommendation(
            id="geschwisterbonus", category="info", title="Geschwisterbonus included (+10 %, min. 75 €)",
            detail=("Included in the amounts. It ends with the month in which the condition lapses"
                    + (f" – here Lebensmonat {last} is the last month with the bonus (until "
                       f"{end.strftime('%d.%m.%Y')})." if last else ".")),
            legal_basis="§ 2a Abs. 1, 3 BEEG", confidence="exact"))
    return recs
