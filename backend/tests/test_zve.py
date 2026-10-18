from decimal import Decimal as D

from app.zve import ZvEHaushalt, ZvEPerson, schaetze_zve


def test_employee_couple_by_hand():
    """Worked example (2026), every step by statute:
    Einkünfte: (120 000 - 1 230) + (110 000 - 1 230) = 227 540           § 19, § 9a EStG
    Altersvorsorge: min(2 * 18 860, 2 * 30 826) - 18 860 (AG) = 18 860   § 10 Abs. 3 EStG
    KV/PV: 2 * (5 440 * 0.96 + 1 255) = 12 954.80 (> 1 900 each)          § 10 Abs. 1 Nr. 3, Abs. 4
    Sonderausgaben-Pauschbetrag (joint): 72                               § 10c
    Kinderfreibeträge: Zähler 1 * 2 * (3 414 + 1 464) = 9 756              § 32 Abs. 6
    zvE = 227 540 - 18 860 - 12 954.80 - 72 - 9 756 = 185 897.20 -> 185 897
    """
    p = dict(rv_arbeitnehmer=D(9430), rv_arbeitgeber=D(9430), kv_arbeitnehmer=D(5440),
             pv_arbeitnehmer=D(1255), alv_arbeitnehmer=D(1318))
    r = schaetze_zve(ZvEHaushalt(
        tax_year=2026,
        personen=[ZvEPerson(jahresbrutto=D(120000), **p), ZvEPerson(jahresbrutto=D(110000), **p)],
        zusammenveranlagung=True, kinderfreibetrag_zaehler=D(1)))
    assert r.zve == D(185897)
    assert r.freibetraege_fuer_kinder == D(9756)


def test_low_basic_insurance_lets_alv_count_up_to_1900():
    r = schaetze_zve(ZvEHaushalt(tax_year=2025, personen=[ZvEPerson(
        jahresbrutto=D(20000), kv_arbeitnehmer=D(1000), pv_arbeitnehmer=D(300), alv_arbeitnehmer=D(260))]))
    # basic cover 1000 * 0.96 + 300 = 1 260 < 1 900 -> ALV counts too: 1 260 + 260 = 1 520
    assert r.kranken_pflege_sonstige_vorsorge == D(1520)


def test_childcare_is_80_percent_capped_per_child():
    r = schaetze_zve(ZvEHaushalt(tax_year=2026, personen=[ZvEPerson(
        jahresbrutto=D(50000), kinderbetreuungskosten=D(8000), kinder_betreut=1)]))
    assert r.uebrige_sonderausgaben == D(4800)


def test_single_parent_relief():
    r = schaetze_zve(ZvEHaushalt(tax_year=2026, personen=[ZvEPerson(jahresbrutto=D(60000))],
                                 alleinerziehend=True, kinder_im_haushalt=2))
    assert r.entlastungsbetrag_alleinerziehende == D(4500)


def test_civil_servant_cap_reduction():
    """§ 10 Abs. 3 Satz 3 EStG: cap minus 18.6 % of pay (up to BBG)."""
    r = schaetze_zve(ZvEHaushalt(tax_year=2026, personen=[ZvEPerson(
        jahresbrutto=D(70000), basisrente_beitraege=D(20000), rv_frei_mit_versorgung=True)]))
    assert r.altersvorsorge == D(30826) - D(70000) * D("0.186")
