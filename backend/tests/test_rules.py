"""Unit tests pinned to the statute text and the examples in the Richtlinien."""

from datetime import date
from decimal import Decimal as D

import pytest

from app import elterngeld as E
from app import params as P
from app.bemessung import (
    bemessungszeitraum,
    massgebliches_merkmal,
    mutterschutz_months_before_birth,
    steuerklassenwechsel_frist,
)
from app.eligibility import Aufenthalt, Grundvoraussetzungen, Status, check_basics, check_income_cap


# --- § 2 BEEG: Ersatzrate, min/max -----------------------------------------
@pytest.mark.parametrize("ek,rate", [
    (D("999.99"), D("0.67")),  # (1000-999.99)/2 = 0.005 -> 0 full steps
    (D("998"), D("0.671")),
    (D("340"), D("1")),  # 0.67 + 0.330 = 1.0
    (D("100"), D("1")),  # capped at 100 %
    (D("1000"), D("0.67")),
    (D("1199.99"), D("0.67")),
    (D("1200"), D("0.67")),
    (D("1202"), D("0.669")),
    (D("1239.99"), D("0.651")),
    (D("1240"), D("0.65")),
    (D("5000"), D("0.65")),
])
def test_ersatzrate(ek, rate):
    assert E.ersatzrate(ek) == rate


def test_minimum_and_maximum():
    assert E.basiselterngeld(D(0)) == D(300)  # § 2 Abs. 4
    assert E.basiselterngeld(D(10000)) == D(1800)  # § 2 Abs. 1 Satz 2
    assert E.elterngeld_plus(D(0)) == D(150)  # § 4a Abs. 2 Nr. 1
    assert E.elterngeld_plus(D(10000)) == D(900)


def test_plus_never_exceeds_half_of_basis_without_income():
    for ek in (D(500), D(1300), D(2500), D(3500)):
        cap = E.cent(E.basiselterngeld(ek) / 2)
        for nach in (D(0), D(200), D(900)):
            assert E.elterngeld_plus(ek, nach) <= cap


def test_difference_uses_2770_cap():
    # § 2 Abs. 3: pre-birth income counted at most 2 770 EUR
    assert E.basiselterngeld(D(4000), D(1000)) == E.cent(D(1770) * D("0.65"))


def test_bonuses():
    assert E.geschwisterbonus(D(500), plus=False) == D(75)  # min 75
    assert E.geschwisterbonus(D(1800), plus=False) == D(180)
    assert E.geschwisterbonus(D(300), plus=True) == D("37.50")
    assert E.mehrlingszuschlag(2, plus=False) == D(300)
    assert E.mehrlingszuschlag(3, plus=True) == D(300)


def test_kinderfreibetrag_never_reduces_income_tax():
    """§ 2e Abs. 4-6 BEEG: only Soli/church tax depend on Kinderfreibeträge."""
    base = dict(erwerbsart=E.Erwerbsart.ANGESTELLT, steuerklasse=E.Steuerklasse.I, kirchensteuer=True)
    birth = date(2027, 3, 1)
    a = E.steuern(D(6000), E.Abzugsmerkmale(**base), birth)
    b = E.steuern(D(6000), E.Abzugsmerkmale(**base, kinderfreibetraege=D(2)), birth)
    assert a.lohnsteuer == b.lohnsteuer
    assert b.kirchensteuer < a.kirchensteuer


def test_social_contribution_flat_rates():
    """§ 2f Abs. 1 BEEG: 9 % + 10 % + 2 %."""
    m = E.Abzugsmerkmale(erwerbsart=E.Erwerbsart.ANGESTELLT)
    assert E.sozialabgaben(D(3000), m, date(2027, 5, 1)) == D(630)
    voluntary = E.Abzugsmerkmale(erwerbsart=E.Erwerbsart.ANGESTELLT, kv_pflichtversichert=False)
    assert E.sozialabgaben(D(3000), voluntary, date(2027, 5, 1)) == D(360)
    beamt = E.Abzugsmerkmale(erwerbsart=E.Erwerbsart.BEAMT)
    assert E.sozialabgaben(D(3000), beamt, date(2027, 5, 1)) == D(0)


def test_unsupported_birth_dates_are_rejected():
    with pytest.raises(ValueError):
        P.tax_year_for_birth(date(2025, 12, 31))
    with pytest.raises(ValueError):
        P.tax_year_for_birth(date(2028, 1, 1))


# --- § 2b / § 2c Abs. 3 BEEG -------------------------------------------------
def test_bemessungszeitraum_without_exclusions():
    bmz = bemessungszeitraum(date(2027, 4, 15), set())
    assert bmz[0] == (2026, 4) and bmz[-1] == (2027, 3) and len(bmz) == 12


def test_mutterschutz_shifts_bemessungszeitraum():
    excluded = mutterschutz_months_before_birth(date(2027, 4, 15), date(2027, 4, 15))
    assert excluded == {(2027, 3)}  # Schutzfrist starts 04.03.2027
    bmz = bemessungszeitraum(date(2027, 4, 15), excluded)
    assert bmz[0] == (2026, 3) and bmz[-1] == (2027, 2)


def test_mutterschutz_can_span_two_months():
    excluded = mutterschutz_months_before_birth(date(2027, 2, 5), date(2027, 2, 5))
    assert excluded == {(2026, 12), (2027, 1)}  # starts 25.12.2026


def test_steuerklasse_richtlinien_example():
    """Richtlinien 2c.3.2.2: IV (5 months), V (5), III (2) -> none prevails -> last (III)."""
    assert massgebliches_merkmal(["IV"] * 5 + ["V"] * 5 + ["III"] * 2) == "III"


@pytest.mark.parametrize("months,expected", [
    (["IV"] * 6 + ["III"] * 6, "III"),  # tie -> last payslip
    (["IV"] * 7 + ["III"] * 5, "IV"),  # IV applied longer
    (["III"] * 12, "III"),
    (["IV"] * 4 + ["V"] * 4 + ["III"] * 4, "III"),
    # § 2c Abs. 3 Satz 2: "in der überwiegenden Zahl der Kalendermonate" = a majority, not the most months
    (["V"] * 5 + ["IV"] * 3 + ["III"] * 4, "III"),
    (["V"] * 7 + ["IV"] * 1 + ["III"] * 4, "V"),
])
def test_steuerklasse_rule(months, expected):
    assert massgebliches_merkmal(months) == expected


def test_switch_deadline():
    bmz = bemessungszeitraum(date(2027, 6, 20), {(2027, 5)})  # 05/2026 - 04/2027
    f = steuerklassenwechsel_frist(bmz)
    assert f.wirksam_ab == (2026, 11)
    assert f.antrag_spaetestens == date(2026, 10, 31)
    assert f.monate_neu == 6 and f.monate_alt == 6
    assert massgebliches_merkmal(["IV"] * f.monate_alt + ["III"] * f.monate_neu) == "III"


# --- § 1 BEEG -----------------------------------------------------------------
def _basics(**kw):
    d = dict(wohnsitz_in_deutschland=True, entsendung_oder_ausnahme=False, lebt_mit_kind_im_haushalt=True,
             betreut_kind_selbst=True, wochenstunden_waehrend_bezug=D(0))
    d.update(kw)
    return Grundvoraussetzungen(**d)


def test_hours_limit():
    assert all(c.status == Status.MET for c in check_basics(_basics(wochenstunden_waehrend_bezug=D(32))))
    hours = {c.id: c for c in check_basics(_basics(wochenstunden_waehrend_bezug=D("32.5")))}["hours"]
    assert hours.status == Status.NOT_MET


@pytest.mark.parametrize("aufenthalt,working,months,ok", [
    (Aufenthalt.BLAUE_KARTE_ICT, False, 0, True),
    (Aufenthalt.AE_STUDIUM_SUCHE, False, 0, False),
    (Aufenthalt.AE_STUDIUM_SUCHE, True, 0, True),
    (Aufenthalt.AE_HUMANITAER, False, 15, True),
    (Aufenthalt.AE_HUMANITAER, False, 14, False),
    (Aufenthalt.AE_AUSBILDUNG_SAISON, True, 0, False),
    (Aufenthalt.SONSTIGE, True, 99, False),
])
def test_residence_permits(aufenthalt, working, months, ok):
    checks = {c.id: c for c in check_basics(_basics(
        aufenthalt=aufenthalt, erwerbstaetig_oder_elternzeit_oder_alg1=working, aufenthalt_seit_monaten=months))}
    assert (checks["residence"].status == Status.MET) is ok


def test_income_cap_boundary():
    assert check_income_cap(D(175000), True).status == Status.MET  # "mehr als 175 000"
    assert check_income_cap(D(175001), True).status == Status.NOT_MET
    assert check_income_cap(D(170000), False).status == Status.CONDITIONAL  # estimate within 5 %


def test_minijob_limit_of_the_year_before_birth():
    # § 8 Abs. 1a SGB IV: 556 € in 2025, 603 € in 2026 (dynamic with the minimum wage)
    m = E.Abzugsmerkmale(erwerbsart=E.Erwerbsart.ANGESTELLT, steuerklasse=E.Steuerklasse.V)
    assert E.steuern(D(550), m, date(2026, 5, 1)).summe == 0  # 2025 limit 556 €
    assert E.steuern(D(600), m, date(2027, 5, 1)).summe == 0  # 2026 limit 603 €
    assert E.steuern(D(600), m, date(2026, 5, 1)).summe > 0
    # Übergangsbereich (§ 20 Abs. 2a SGB IV) with G = 603 €: SV base at 700 € = F·G + (2000/(2000−G) − G/(2000−G)·F)·(700−G)
    g, f = D(603), D("0.6667")
    base = f * g + (D(2000) / (2000 - g) - g / (2000 - g) * f) * (700 - g)
    assert E.sozialabgaben(D(700), m, date(2027, 5, 1)) == E.cent(E.cent(base) * D("0.21"))


def test_income_tax_tariff_from_the_official_pap():
    # § 32a EStG via the PAP's own UPTAB routine; by hand: 2026, 50 000 € single:
    # z = (50 000 − 17 799) / 10 000 = 3.2201 -> (173.10 z + 2 397) z + 1 034.87 = 10 548.34 -> 10 548
    from app.pap.interpreter import load_pap
    assert load_pap(2026).income_tax(D(50000), joint=False) == 10548
    assert load_pap(2026).income_tax(D(100000), joint=True) == 2 * 10548  # splitting
    assert load_pap(2026).income_tax(D(12348), joint=False) == 0  # Grundfreibetrag
    assert load_pap(2025).income_tax(D(50000), joint=False) == 10691


def test_progressionsvorbehalt():
    # § 32b: the rate of (zvE + tax-free benefits) applies to the zvE
    from app.einkommensteuer import income_tax, with_progressionsvorbehalt
    base = income_tax(D(100000), 2026, joint=True)
    with_pv = with_progressionsvorbehalt(D(100000), D(20000), 2026, joint=True)
    assert with_pv == int(D(100000) * income_tax(D(120000), 2026, joint=True) / D(120000))
    assert with_pv > base and with_progressionsvorbehalt(D(100000), D(0), 2026, joint=True) == base
