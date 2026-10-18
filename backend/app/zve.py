"""Estimate of the zu versteuerndes Einkommen (zvE, § 2 Abs. 5 EStG).

Used for the Elterngeld income cap (§ 1 Abs. 8 BEEG): the zvE of the calendar
year before birth, always reduced by the Freibeträge für Kinder (Richtlinien
zum BEEG 1.8). The authoritative figure is the one in the income tax assessment
(Steuerbescheid). This module estimates it from the annual payslip /
Lohnsteuerbescheinigung, and is explicit about what it does not cover.

Not covered (deliberately): capital income under Abgeltungsteuer (ignored by
the Elterngeld office anyway, Richtlinien 1.8), Altersentlastungsbetrag,
Versorgungsbezüge, loss carry-forwards (enter them as negative other income),
Günstigerprüfung Riester (§ 10a), foreign income.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from . import params as P

ZERO = Decimal(0)


def euro(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ZvEPerson:
    """Annual figures of one person for the tax year before birth.

    Field references point to the Lohnsteuerbescheinigung (LStB) lines.
    """

    jahresbrutto: Decimal = ZERO  # LStB Zeile 3 (steuerpflichtiger Bruttoarbeitslohn, incl. bonuses)
    rv_arbeitnehmer: Decimal = ZERO  # LStB Zeile 23a
    rv_arbeitgeber: Decimal = ZERO  # LStB Zeile 22a (steuerfrei)
    kv_arbeitnehmer: Decimal = ZERO  # LStB Zeile 25
    pv_arbeitnehmer: Decimal = ZERO  # LStB Zeile 26
    alv_arbeitnehmer: Decimal = ZERO  # LStB Zeile 27
    krankengeldanspruch: bool = True  # GKV contributions -4 % (§ 10 Abs. 1 Nr. 3a S. 4 EStG)
    private_kv_pv_basis: Decimal = ZERO  # privately insured: basic-cover share of premiums (annual)
    private_kv_ag_zuschuss: Decimal = ZERO  # LStB Zeile 24 (tax-free employer subsidy)
    rv_frei_mit_versorgung: bool = False  # civil servant etc. (§ 10 Abs. 3 Satz 3 EStG)
    werbungskosten: Decimal | None = None  # actual Werbungskosten; None -> Pauschbetrag
    andere_einkuenfte: Decimal = ZERO  # profit, rental income, ... (net; losses negative)
    basisrente_beitraege: Decimal = ZERO  # Rürup/Basisrente, berufsständische Versorgung
    kirchensteuer_gezahlt: Decimal = ZERO  # LStB Zeilen 6/7 (Sonderausgabe)
    spenden: Decimal = ZERO
    kinderbetreuungskosten: Decimal = ZERO  # own share of the costs
    kinder_betreut: int = 0  # number of children (< 14) the childcare costs relate to
    weitere_sonderausgaben: Decimal = ZERO  # e.g. Berufsausbildung (§ 10 Abs. 1 Nr. 7)
    aussergewoehnliche_belastungen: Decimal = ZERO  # deductible amount (after zumutbare Belastung)


@dataclass(frozen=True)
class ZvEHaushalt:
    tax_year: int
    personen: list[ZvEPerson]
    zusammenveranlagung: bool = False  # married couple, joint assessment
    kinderfreibetrag_zaehler: Decimal = ZERO  # sum of Zähler (1.0 per child for married parents)
    alleinerziehend: bool = False  # § 24b EStG
    kinder_im_haushalt: int = 0  # for § 24b (children the relief applies to)


@dataclass
class ZvEErgebnis:
    einkuenfte_nichtselbstaendig: Decimal
    andere_einkuenfte: Decimal
    entlastungsbetrag_alleinerziehende: Decimal
    gesamtbetrag_der_einkuenfte: Decimal
    altersvorsorge: Decimal
    kranken_pflege_sonstige_vorsorge: Decimal
    uebrige_sonderausgaben: Decimal
    aussergewoehnliche_belastungen: Decimal
    freibetraege_fuer_kinder: Decimal
    zve: Decimal
    hinweise: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(self).items()}


def freibetraege_fuer_kinder(zaehler: Decimal, ty: P.TaxYear) -> Decimal:
    """§ 32 Abs. 6 EStG; for § 1 Abs. 8 BEEG always deducted (§ 2 Abs. 5 Satz 2 EStG, Richtlinien 1.8)."""
    return zaehler * 2 * (ty.kinderfreibetrag_per_parent + ty.bea_freibetrag_per_parent)


def _altersvorsorge_cap(p: ZvEPerson, ty: P.TaxYear) -> Decimal:
    """§ 10 Abs. 3 Satz 1, 3 EStG: Höchstbetrag, reduced for civil servants etc."""
    cap = ty.altersvorsorge_hoechstbetrag
    if p.rv_frei_mit_versorgung:
        cap -= min(p.jahresbrutto, ty.bbg_rv) * ty.rv_rate_total
    return max(cap, ZERO)


def _altersvorsorge(personen: list[ZvEPerson], ty: P.TaxYear) -> Decimal:
    """§ 10 Abs. 1 Nr. 2, Abs. 3 EStG (100 % since 2023), minus tax-free employer share."""
    total = sum((p.rv_arbeitnehmer + p.rv_arbeitgeber + p.basisrente_beitraege for p in personen), ZERO)
    cap = sum((_altersvorsorge_cap(p, ty) for p in personen), ZERO)
    arbeitgeber = sum((p.rv_arbeitgeber for p in personen), ZERO)
    return max(min(total, cap) - arbeitgeber, ZERO)


def _kranken_pflege(p: ZvEPerson) -> Decimal:
    """§ 10 Abs. 1 Nr. 3, 3a, Abs. 4 EStG."""
    kv = p.kv_arbeitnehmer * (1 - P.KV_KRANKENGELD_ABSCHLAG) if p.krankengeldanspruch else p.kv_arbeitnehmer
    basis = kv + p.pv_arbeitnehmer + max(p.private_kv_pv_basis - p.private_kv_ag_zuschuss, ZERO)
    employee = p.jahresbrutto > 0 or p.private_kv_ag_zuschuss > 0
    cap = P.SONSTIGE_VORSORGE_CAP_EMPLOYEE if employee else P.SONSTIGE_VORSORGE_CAP_SELF_PAID
    if basis >= cap:
        return basis  # basic cover is always fully deductible; other insurance is then excluded
    return min(cap, basis + p.alv_arbeitnehmer)


def schaetze_zve(h: ZvEHaushalt) -> ZvEErgebnis:
    ty = P.TAX_YEARS[h.tax_year]
    hinweise: list[str] = []
    einkuenfte_ns = ZERO
    andere = ZERO
    for p in h.personen:
        if p.jahresbrutto > 0:
            wk = max(p.werbungskosten or ZERO, ty.arbeitnehmer_pauschbetrag)
            einkuenfte_ns += max(p.jahresbrutto - wk, ZERO)
        andere += p.andere_einkuenfte

    entlastung = ZERO
    if h.alleinerziehend and h.kinder_im_haushalt > 0 and not h.zusammenveranlagung:
        entlastung = Decimal(4260) + Decimal(240) * (h.kinder_im_haushalt - 1)  # § 24b Abs. 2 EStG
    gde = einkuenfte_ns + andere - entlastung

    if h.zusammenveranlagung:
        altersvorsorge = _altersvorsorge(h.personen, ty)  # joint cap (§ 10 Abs. 3 Satz 2 EStG)
    else:
        altersvorsorge = sum((_altersvorsorge([p], ty) for p in h.personen), ZERO)

    kv_pv = sum((_kranken_pflege(p) for p in h.personen), ZERO)

    uebrige = ZERO
    for p in h.personen:
        kibe = min(
            p.kinderbetreuungskosten * P.KINDERBETREUUNG_RATE,
            P.KINDERBETREUUNG_MAX_PER_CHILD * max(p.kinder_betreut, 0),
        )
        uebrige += p.kirchensteuer_gezahlt + kibe + p.weitere_sonderausgaben
    spenden = sum((p.spenden for p in h.personen), ZERO)
    spenden_max = max(gde, ZERO) * P.SPENDEN_MAX_SHARE
    if spenden > spenden_max:
        hinweise.append("Donations above 20 % of the Gesamtbetrag der Einkünfte were capped (§ 10b Abs. 1 EStG).")
    uebrige += min(spenden, spenden_max)
    pausch = P.SONDERAUSGABEN_PAUSCHBETRAG * (2 if h.zusammenveranlagung else len(h.personen))
    uebrige = max(uebrige, pausch)

    agb = sum((p.aussergewoehnliche_belastungen for p in h.personen), ZERO)
    kinder = freibetraege_fuer_kinder(h.kinderfreibetrag_zaehler, ty)

    zve = max(gde - altersvorsorge - kv_pv - uebrige - agb - kinder, ZERO)
    hinweise.append(
        "This is an estimate. Decisive is the zvE in the Steuerbescheid, always "
        "reduced by the Freibeträge für Kinder (Richtlinien zum BEEG 1.8)."
    )
    return ZvEErgebnis(
        einkuenfte_nichtselbstaendig=euro(einkuenfte_ns),
        andere_einkuenfte=euro(andere),
        entlastungsbetrag_alleinerziehende=euro(entlastung),
        gesamtbetrag_der_einkuenfte=euro(gde),
        altersvorsorge=euro(altersvorsorge),
        kranken_pflege_sonstige_vorsorge=euro(kv_pv),
        uebrige_sonderausgaben=euro(uebrige),
        aussergewoehnliche_belastungen=euro(agb),
        freibetraege_fuer_kinder=euro(kinder),
        zve=euro(zve),
        hinweise=hinweise,
    )
