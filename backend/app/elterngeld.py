"""Elterngeld-Netto and Elterngeld amounts (§§ 2, 2a, 2c, 2e, 2f, 4a BEEG).

Mirrors the calculation order of the official BMFSFJ Elterngeldrechner so that
results are cent-identical (verified in tests/test_golden_official.py), except
where the official code deviates from the BMF pseudocode (float rounding) — in
those cases this engine follows the BMF exactly (tests/test_pap_bmf.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import Enum

from . import params as P
from .pap.interpreter import load_pap

ZERO = Decimal(0)


def cent(x: Decimal) -> Decimal:
    """Kaufmännisch auf den Cent runden (Richtlinien zum BEEG 2.0.3.3.1)."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Erwerbsart(str, Enum):
    ANGESTELLT = "angestellt"  # employee subject to social insurance (incl. Midijob)
    BEAMT = "beamt"  # employed without social insurance (civil servants etc.)
    MINIJOB = "minijob"  # only pauschal taxed marginal employment
    KEINE = "keine"  # no income in the Bemessungszeitraum


class Steuerklasse(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"
    IV_FAKTOR = "IV_FAKTOR"
    V = "V"
    VI = "VI"  # only for parity tests; § 2e Abs. 3 disregards class VI


_STKL = {"I": 1, "II": 2, "III": 3, "IV": 4, "IV_FAKTOR": 4, "V": 5, "VI": 6}


@dataclass(frozen=True)
class Abzugsmerkmale:
    """Deduction features taken from the payslip (§ 2c Abs. 3 BEEG)."""

    erwerbsart: Erwerbsart
    steuerklasse: Steuerklasse = Steuerklasse.IV
    faktor: Decimal = Decimal(1)
    kirchensteuer: bool = False
    kinderfreibetraege: Decimal = ZERO  # "Kinderfreibeträge" from the payslip (0, 0.5, 1, ...)
    kv_pflichtversichert: bool = True  # compulsorily insured in GKV (not voluntary/private)
    rv_pflichtversichert: bool = True


@dataclass(frozen=True)
class Steuern:
    lohnsteuer: Decimal
    soli: Decimal
    kirchensteuer: Decimal

    @property
    def summe(self) -> Decimal:
        return self.lohnsteuer + self.soli + self.kirchensteuer


def steuern(brutto: Decimal, m: Abzugsmerkmale, birth: date) -> Steuern:
    """Abzüge für Steuern per § 2e BEEG using the PAP of the year before birth."""
    ty = P.tax_year_for_birth(birth)
    if brutto <= ty.geringfuegigkeitsgrenze:
        return Steuern(ZERO, ZERO, ZERO)
    pap = load_pap(ty.year)
    faktor = m.steuerklasse == Steuerklasse.IV_FAKTOR
    inputs = {
        "af": 1 if faktor else 0,
        "f": float(m.faktor) if faktor else 1.0,
        "ALV": 0 if m.erwerbsart == Erwerbsart.ANGESTELLT else 1,
        "KRV": 1 if m.erwerbsart == Erwerbsart.BEAMT else 0,
        "KVZ": ty.avg_kv_zusatzbeitrag_pct,
        "LZZ": 2,
        # § 2e Abs. 2 Nr. 2: KV/PV parts b, c always; no Kinderlosenzuschlag,
        # no Kinderabschläge, no Saxony rate; never private-insurance part d.
        "PKV": 0,
        "PVA": 0,
        "PVS": 0,
        "PVZ": 0,
        "R": 1 if m.kirchensteuer else 0,
        "RE4": int(cent(brutto) * 100),
        "STKL": _STKL[m.steuerklasse.value],
        "ZKF": m.kinderfreibetraege,
    }
    inputs = {k: v for k, v in inputs.items() if k in pap.inputs}
    # § 2e Abs. 4, 5: Kinderfreibeträge only affect Soli and church tax,
    # never the income tax itself (§ 2e Abs. 6).
    with_kfb = pap.run(**inputs)
    without_kfb = pap.run(**{**inputs, "ZKF": 0})
    lst = Decimal(without_kfb["LSTLZZ"]) / 100
    soli = Decimal(with_kfb["SOLZLZZ"]) / 100
    kist = cent(Decimal(with_kfb["BK"]) / 100 * P.KIRCHENSTEUER_RATE)
    return Steuern(lst, soli, kist)


def _sv_bemessungsgrundlage(brutto: Decimal, birth: date) -> Decimal:
    """Midijob conversion per § 2f Abs. 2 BEEG / § 20 Abs. 2a SGB IV, limit of the year before birth."""
    g = P.tax_year_for_birth(birth).geringfuegigkeitsgrenze
    og, f = P.UEBERGANGSBEREICH_OBERGRENZE, P.UEBERGANGSBEREICH_F_FAKTOR
    if not (g < brutto <= og):
        return brutto
    return max(cent(f * g + (og / (og - g) - (g / (og - g)) * f) * (brutto - g)), ZERO)


def sozialabgaben(brutto: Decimal, m: Abzugsmerkmale, birth: date) -> Decimal:
    """Abzüge für Sozialabgaben per § 2f BEEG (flat rates)."""
    kv = m.kv_pflichtversichert
    rv = m.rv_pflichtversichert
    alv = m.erwerbsart == Erwerbsart.ANGESTELLT
    if m.erwerbsart == Erwerbsart.ANGESTELLT:
        rv = True
    elif m.erwerbsart == Erwerbsart.BEAMT:
        kv = rv = False
    base = _sv_bemessungsgrundlage(brutto, birth)
    total = ZERO
    if kv:
        total += max(base * P.SV_RATE_KV_PV, ZERO)
    if rv:
        total += max(base * P.SV_RATE_RV, ZERO)
    if alv:
        total += max(base * P.SV_RATE_ALV, ZERO)
    return cent(total)


def werbungskostenpauschale_monat(birth: date) -> Decimal:
    """1/12 Arbeitnehmer-Pauschbetrag (§ 2c Abs. 1 BEEG)."""
    return cent(P.tax_year_for_birth(birth).arbeitnehmer_pauschbetrag / 12)


@dataclass(frozen=True)
class NettoBerechnung:
    brutto: Decimal
    steuern: Steuern
    sozialabgaben: Decimal
    werbungskostenpauschale: Decimal
    elterngeld_netto: Decimal  # "Einkommen aus Erwerbstätigkeit" per § 2 Abs. 1 BEEG


def elterngeld_netto(brutto: Decimal, m: Abzugsmerkmale, birth: date) -> NettoBerechnung:
    """Monthly Elterngeld-Netto from the average monthly regular gross pay.

    ``brutto`` must exclude "sonstige Bezüge" (bonuses, 13th salary, ...),
    § 2c Abs. 1 Satz 2 BEEG.
    """
    brutto = cent(brutto)
    wkp = werbungskostenpauschale_monat(birth)
    if m.erwerbsart == Erwerbsart.KEINE or brutto <= 0:
        return NettoBerechnung(ZERO, Steuern(ZERO, ZERO, ZERO), ZERO, wkp, ZERO)
    if m.erwerbsart == Erwerbsart.MINIJOB:
        st, sv = Steuern(ZERO, ZERO, ZERO), ZERO
    else:
        st, sv = steuern(brutto, m, birth), sozialabgaben(brutto, m, birth)
    netto_vor_pauschale = cent(brutto - (st.summe + sv))
    return NettoBerechnung(brutto, st, sv, wkp, max(cent(netto_vor_pauschale - wkp), ZERO))


def ersatzrate(ek: Decimal) -> Decimal:
    """§ 2 Abs. 1, 2 BEEG."""
    if ek < 1000:
        zuschlag = ((1000 - ek) / 2).to_integral_value(rounding=ROUND_FLOOR) * Decimal("0.001")
        return min(Decimal("0.67") + zuschlag, Decimal(1))
    if ek < 1200:
        return Decimal("0.67")
    if ek < 1240:
        abschlag = ((ek - 1200) / 2).to_integral_value(rounding=ROUND_FLOOR) * Decimal("0.001")
        return Decimal("0.67") - abschlag
    return Decimal("0.65")


def _bezugswert(ek_vor: Decimal, ek_nach: Decimal) -> Decimal:
    """§ 2 Abs. 3 BEEG: difference, pre-birth income capped at 2 770 EUR."""
    return cent(max(min(ek_vor, P.NETTO_CAP_FOR_DIFFERENCE) - ek_nach, ZERO))


def basiselterngeld(ek_vor: Decimal, ek_nach: Decimal = ZERO) -> Decimal:
    """Basiselterngeld without bonuses (§ 2 Abs. 1-4 BEEG)."""
    value = _bezugswert(ek_vor, ek_nach) * ersatzrate(ek_vor)
    return cent(min(max(value, P.ELTERNGELD_MIN), P.ELTERNGELD_MAX))


def elterngeld_plus(ek_vor: Decimal, ek_nach: Decimal = ZERO) -> Decimal:
    """ElterngeldPlus without bonuses (§ 4a Abs. 2 BEEG)."""
    cap = cent(basiselterngeld(ek_vor) / 2)
    value = _bezugswert(ek_vor, ek_nach) * ersatzrate(ek_vor)
    return cent(min(max(value, P.ELTERNGELD_MIN / 2), cap))


def geschwisterbonus(betrag: Decimal, plus: bool) -> Decimal:
    """§ 2a Abs. 1 BEEG; minimum halved for ElterngeldPlus (§ 4a Abs. 2 Nr. 2)."""
    minimum = P.GESCHWISTERBONUS_MIN / 2 if plus else P.GESCHWISTERBONUS_MIN
    return cent(max(betrag * P.GESCHWISTERBONUS_RATE, minimum))


def mehrlingszuschlag(anzahl_kinder: int, plus: bool) -> Decimal:
    """§ 2a Abs. 4 BEEG; halved for ElterngeldPlus (§ 4a Abs. 2 Nr. 3)."""
    per_child = P.MEHRLINGSZUSCHLAG / 2 if plus else P.MEHRLINGSZUSCHLAG
    return per_child * max(anzahl_kinder - 1, 0)


def ek_nach_geburt(brutto_nach: Decimal, m: Abzugsmerkmale, birth: date) -> Decimal:
    """Elterngeld-Netto of part-time income after birth (§ 2 Abs. 3 BEEG).

    The deduction features of the Bemessungszeitraum keep applying (§ 2c Abs. 3,
    Richtlinien 2c.3.2.2).
    """
    brutto_nach = cent(brutto_nach)
    if brutto_nach <= 0:
        return ZERO
    wkp = werbungskostenpauschale_monat(birth)
    if m.erwerbsart == Erwerbsart.MINIJOB:
        abz = ZERO
    else:
        abz = steuern(brutto_nach, m, birth).summe + sozialabgaben(brutto_nach, m, birth)
    return cent(max(cent(max(brutto_nach - wkp, ZERO)) - abz, ZERO))


@dataclass(frozen=True)
class Monatsbetraege:
    elterngeld_netto: Decimal
    ersatzrate: Decimal
    basis: Decimal  # incl. bonuses
    plus: Decimal  # incl. bonuses
    basis_mit_teilzeit: Decimal | None
    plus_mit_teilzeit: Decimal | None  # also the Partnerschaftsbonus amount
    ek_nach: Decimal | None
    geschwisterbonus: bool
    mehrlinge: int


def monatsbetraege(
    ek_vor: Decimal,
    *,
    geschwisterbonus_berechtigt: bool = False,
    anzahl_kinder: int = 1,
    ek_nach: Decimal | None = None,
) -> Monatsbetraege:
    def with_bonuses(amount: Decimal, plus: bool) -> Decimal:
        total = amount
        if geschwisterbonus_berechtigt:
            total += geschwisterbonus(amount, plus)
        return cent(total + mehrlingszuschlag(anzahl_kinder, plus))

    basis = basiselterngeld(ek_vor)
    plus = elterngeld_plus(ek_vor)
    basis_tz = plus_tz = None
    if ek_nach is not None and ek_nach > 0:
        basis_tz = with_bonuses(basiselterngeld(ek_vor, ek_nach), False)
        plus_tz = with_bonuses(elterngeld_plus(ek_vor, ek_nach), True)
    return Monatsbetraege(
        elterngeld_netto=ek_vor,
        ersatzrate=ersatzrate(ek_vor),
        basis=with_bonuses(basis, False),
        plus=with_bonuses(plus, True),
        basis_mit_teilzeit=basis_tz,
        plus_mit_teilzeit=plus_tz,
        ek_nach=ek_nach,
        geschwisterbonus=geschwisterbonus_berechtigt,
        mehrlinge=anzahl_kinder,
    )
