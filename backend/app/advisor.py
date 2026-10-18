"""Recommendations: how to become eligible, and how to optimise the amount.

Rules for every recommendation:
* only levers that are lawful and grounded in a cited provision,
* quantified where the inputs allow it (otherwise marked "qualitative"),
* honest about deadlines: the income-cap year (year before birth) can only be
  influenced while it is still running; afterwards only via the tax return.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from . import params as P
from .bemessung import Month, steuerklassenwechsel_frist
from .elterngeld import ZERO, Abzugsmerkmale, Erwerbsart, ek_nach_geburt, elterngeld_plus
from .fmt import eur


@dataclass
class Recommendation:
    id: str
    category: str  # "eligibility" | "amount" | "process" | "info"
    title: str
    detail: str
    legal_basis: str
    confidence: str  # "exact" | "estimate" | "qualitative"
    impact_eur: Decimal | None = None  # zvE reduction (eligibility) or Elterngeld gain (amount)
    deadline: date | None = None
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["impact_eur"] = str(self.impact_eur) if self.impact_eur is not None else None
        d["deadline"] = self.deadline.isoformat() if self.deadline else None
        return d


@dataclass(frozen=True)
class PersonLevers:
    """Per-person data for quantifying zvE levers (from the estimate inputs)."""

    label: str
    is_employee: bool
    jahresbrutto: Decimal
    rv_total: Decimal  # AN + AG statutory pension + existing Basisrente
    altersvorsorge_cap: Decimal
    bav_existing: Decimal
    pending_one_off: Decimal  # one-off payments still due in the cap year


def eligibility_path(
    *,
    gap: Decimal,
    tax_year: int,
    today: date,
    levers: list[PersonLevers],
    from_tax_assessment: bool,
) -> tuple[list[Recommendation], Decimal]:
    """Levers to bring the zvE of `tax_year` to <= 175 000 EUR. Returns (recs, quantified total)."""
    ty = P.TAX_YEARS[tax_year]
    recs: list[Recommendation] = []
    year_end = date(tax_year, 12, 31)
    quantified = ZERO

    if today <= year_end:
        for p in levers:
            if p.is_employee:
                headroom = max(ty.bbg_rv * P.BAV_TAX_FREE_SHARE_OF_BBG - p.bav_existing, ZERO)
                if headroom > 0:
                    quantified += headroom
                    recs.append(Recommendation(
                        id=f"bav_{p.label}", category="eligibility",
                        title=f"{p.label}: salary conversion into a company pension (bAV)",
                        detail=(f"Converting up to {eur(headroom)} of gross pay still to be paid in {tax_year} "
                                f"into a Direktversicherung/Pensionskasse/Pensionsfonds is tax-free up to 8 % of the "
                                f"RV ceiling ({eur(ty.bbg_rv * P.BAV_TAX_FREE_SHARE_OF_BBG)} in {tax_year}). It lowers "
                                "taxable gross pay – and thus the zvE – almost euro for euro."),
                        legal_basis="§ 3 Nr. 63 EStG; § 1a BetrAVG",
                        confidence="estimate", impact_eur=headroom, deadline=year_end,
                        caveats=["Only future pay can be converted; agree with your employer before the payout.",
                                 "Prefer converting a one-off bonus: bonuses don't count for Elterngeld anyway, so "
                                 "the zvE drops without lowering Elterngeld. Converting regular monthly pay in "
                                 "Bemessungszeitraum months lowers the Elterngeld basis (no effect only if the "
                                 "Elterngeld-Netto stays above 2.770 €) – Richtlinien zum BEEG 2.1.3.1.2.",
                                 "Social-insurance free only up to 4 % of the RV ceiling.",
                                 "Money is locked until retirement."],
                    ))
            headroom = max(p.altersvorsorge_cap - p.rv_total, ZERO)
            if headroom > 0:
                quantified += headroom
                recs.append(Recommendation(
                    id=f"basisrente_{p.label}", category="eligibility",
                    title=f"{p.label}: contributions to a Basisrente (Rürup)",
                    detail=(f"Unused deduction room for retirement contributions in {tax_year}: about {eur(headroom)} "
                            f"(cap {eur(p.altersvorsorge_cap)} minus statutory pension contributions incl. employer "
                            "share). Contributions paid by 31 Dec are 100 % deductible as Sonderausgaben."),
                    legal_basis="§ 10 Abs. 1 Nr. 2 Buchst. b, Abs. 3 EStG",
                    confidence="estimate", impact_eur=headroom, deadline=year_end,
                    caveats=["Real cash outlay; the contract pays only a lifelong pension (no lump sum).",
                             "Payment must leave your account in the cap year (§ 11 Abs. 2 EStG)."],
                ))
            if p.pending_one_off > 0:
                quantified += p.pending_one_off
                recs.append(Recommendation(
                    id=f"defer_bonus_{p.label}", category="eligibility",
                    title=f"{p.label}: defer one-off payments to next year",
                    detail=(f"One-off payments (sonstige Bezüge) are taxed in the year they are received. Moving the "
                            f"expected {eur(p.pending_one_off)} into January {tax_year + 1} – if your employer "
                            "agrees – removes it from the cap year."),
                    legal_basis="§ 38a Abs. 1 Satz 3, § 11 Abs. 1 EStG",
                    confidence="estimate", impact_eur=p.pending_one_off, deadline=year_end,
                    caveats=["Must be a genuine contractual deferral before the payment becomes due.",
                             "It then counts in the next year (relevant if you plan another child)."],
                ))
        recs.append(Recommendation(
            id="werbungskosten", category="eligibility",
            title="Claim (and incur) all genuine work-related expenses",
            detail=("Everything above the 1 230 € Arbeitnehmer-Pauschbetrag lowers the zvE: home office (6 €/day, "
                    "max. 1 260 €), commuting, work equipment, training, union fees, double household. Expenses "
                    "you genuinely need anyway can be brought forward into the cap year."),
            legal_basis="§ 9, § 9a, § 4 Abs. 5 Satz 1 Nr. 6c EStG",
            confidence="qualitative", deadline=year_end,
        ))
        recs.append(Recommendation(
            id="spenden", category="eligibility",
            title="Donations (up to 20 % of the Gesamtbetrag der Einkünfte)",
            detail="Donations to tax-privileged organisations reduce the zvE euro for euro – but cost the full amount.",
            legal_basis="§ 10b Abs. 1 EStG", confidence="qualitative", deadline=year_end,
        ))
        recs.append(Recommendation(
            id="self_employed_timing", category="eligibility",
            title="Self-employed / side income: timing of receipts and expenses",
            detail=("Under cash accounting (EÜR) income counts when received and expenses when paid; an "
                    "Investitionsabzugsbetrag can bring forward up to 50 % of planned investment costs."),
            legal_basis="§ 4 Abs. 3, § 11, § 7g EStG", confidence="qualitative", deadline=year_end,
            caveats=["Have a tax adviser check eligibility and consequences."],
        ))
    else:
        recs.append(Recommendation(
            id="closed_year_return", category="eligibility",
            title=f"{tax_year} is closed: only your tax return can still change the zvE",
            detail=("Make sure the return claims every deduction actually incurred in that year (Werbungskosten, "
                    "church tax paid, 80 % of childcare costs up to 4 800 €/child, donations, extraordinary "
                    "burdens, loss carry-forwards). If the assessment already exists, you can object (Einspruch) "
                    "within one month of notification."),
            legal_basis="§§ 9, 10, 10b, 10d, 33 EStG; § 355 Abs. 1 AO",
            confidence="qualitative",
        ))
        if not from_tax_assessment:
            recs.append(Recommendation(
                id="provisional", category="process",
                title="No assessment yet? Apply anyway",
                detail=("If the Steuerbescheid for the cap year is not available, the Elterngeldstelle decides "
                        "provisionally and checks the zvE later."),
                legal_basis="§ 8 Abs. 2 Satz 2 BEEG; Richtlinien zum BEEG 1.8",
                confidence="qualitative",
            ))
    recs.append(Recommendation(
        id="elternzeit_independent", category="info",
        title="Elternzeit does not depend on the income cap",
        detail="Even without Elterngeld you can take up to 3 years of job-protected Elternzeit per child.",
        legal_basis="§ 15, § 18 BEEG", confidence="exact",
    ))
    return recs, quantified


def steuerklassen_recommendation(
    *, label: str, partner_label: str, bmz: list[Month], today: date,
    gain_household: Decimal, gain_parent: Decimal, current: str, target: str,
) -> Recommendation:
    frist = steuerklassenwechsel_frist(bmz)
    too_late = today > frist.antrag_spaetestens
    wirksam = f"{frist.wirksam_ab[1]:02d}/{frist.wirksam_ab[0]}"
    detail = (f"With Steuerklasse {target} instead of {current}, {label}'s Elterngeld-Netto rises. Expected "
              f"Elterngeld gain over your plan: {eur(gain_household)} for the household "
              f"({eur(gain_parent)} for {label}). The new class must apply from {wirksam} at the latest, so that "
              f"it holds in at least {frist.monate_neu} of the 12 months of the Bemessungszeitraum (ties go to "
              f"the last payslip). File the change by {frist.antrag_spaetestens.strftime('%d.%m.%Y')}.")
    if too_late:
        detail = (f"A switch to Steuerklasse {target} would raise Elterngeld by about {eur(gain_household)}, but "
                  f"the deadline ({frist.antrag_spaetestens.strftime('%d.%m.%Y')}) has passed for this child.")
    return Recommendation(
        id=f"steuerklasse_{label}", category="amount",
        title=f"Steuerklassenwechsel: {label} {target} / {partner_label} {'V' if target == 'III' else 'III'}",
        detail=detail,
        legal_basis="§ 2c Abs. 3 BEEG, Richtlinien 2c.3.2; § 39 Abs. 6 Satz 3, 5 EStG; BSG 25.06.2009 – B 10 EG 3/08 R",
        confidence="exact", impact_eur=gain_household, deadline=None if too_late else frist.antrag_spaetestens,
        caveats=[f"{partner_label}'s monthly net pay drops until the annual tax return (mandatory with III/V, "
                 "§ 46 Abs. 2 Nr. 3a EStG); the joint annual tax is unchanged.",
                 "Only for married couples / registered partners.",
                 "Changes after birth do not affect the Elterngeld any more (Richtlinien 2c.3.2.2) – you can "
                 "switch back afterwards."],
    )


def max_part_time_gross_full_plus(ek_vor: Decimal, m: Abzugsmerkmale, birth: date) -> Decimal:
    """Highest monthly gross (whole euros) during Plus that keeps the full Plus amount."""
    full = elterngeld_plus(ek_vor)
    lo, hi = 0, 20_000
    if elterngeld_plus(ek_vor, ek_nach_geburt(Decimal(hi), m, birth)) == full:
        return Decimal(hi)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if elterngeld_plus(ek_vor, ek_nach_geburt(Decimal(mid), m, birth)) == full:
            lo = mid
        else:
            hi = mid - 1
    return Decimal(lo)


def part_time_recommendation(label: str, ek_vor: Decimal, m: Abzugsmerkmale, birth: date,
                             monthly_gross: Decimal = ZERO, weekly_hours: Decimal = Decimal(40)) -> Recommendation | None:
    if m.erwerbsart == Erwerbsart.KEINE or ek_vor <= 0:
        return None
    limit = max_part_time_gross_full_plus(ek_vor, m, birth)
    if limit <= 0:
        return None
    hours = ""
    if monthly_gross > 0 and limit < 20_000:
        h = min(limit / monthly_gross * weekly_hours, Decimal(32))
        hours = f" – about {h.quantize(Decimal('0.5'), rounding=ROUND_DOWN):g} h/week at your current pay"
    return Recommendation(
        id=f"teilzeit_{label}", category="amount",
        title=f"{label}: part-time during ElterngeldPlus without losing a cent",
        detail=(f"ElterngeldPlus is capped at half the Basiselterngeld. Up to about {eur(limit)} gross per month"
                f"{hours} (max. 32 h/week) of part-time pay during Plus months leaves {label}'s ElterngeldPlus of "
                f"{eur(elterngeld_plus(ek_vor), True)} untouched – the pay comes on top."),
        legal_basis="§ 2 Abs. 3, § 4a Abs. 2 BEEG",
        confidence="exact", impact_eur=None,
        caveats=["Computed with the same deduction features as before birth (§ 2c Abs. 3 BEEG).",
                 "Pay above this threshold reduces Plus gradually, not abruptly."],
    )
