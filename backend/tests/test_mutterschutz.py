"""Mutterschutz periods and Mutterschaftsgeld (§§ 3, 19, 20, 21 MuSchG; § 24i SGB V; § 3 BEEG)."""

from datetime import date
from decimal import Decimal as D

from app.elterngeld import Erwerbsart, monatsbetraege
from app.mutterschutz import mutterschaftsgeld, schutzfristen
from app.plan import MAX_LM, MaternityCredit, ParentContext, evaluate

DUE = date(2027, 4, 15)


def test_on_time_birth_is_99_days():
    f = schutzfristen(DUE, DUE, 8)
    assert (f.days_before, f.days_after, f.total_days) == (42, 56, 99)
    assert f.start == date(2027, 3, 4) and f.end == date(2027, 6, 10)


def test_early_birth_extends_period_after_birth():
    """§ 3 Abs. 2 Satz 3 MuSchG: lost days before birth are added after birth."""
    f = schutzfristen(DUE, date(2027, 4, 5), 8)
    assert (f.days_before, f.extension_days, f.days_after, f.total_days) == (32, 10, 66, 99)


def test_late_birth_extends_period_before_birth():
    """§ 3 Abs. 1 Satz 4 MuSchG."""
    f = schutzfristen(DUE, date(2027, 4, 20), 8)
    assert (f.days_before, f.days_after, f.total_days) == (47, 56, 104)


def test_twelve_weeks_for_premature_or_multiple_births():
    assert schutzfristen(DUE, DUE, 12).days_after == 84


def test_gkv_member_13_eur_plus_employer_top_up():
    m = mutterschaftsgeld(due=DUE, birth=DUE, weeks_after=8, erwerbsart=Erwerbsart.ANGESTELLT,
                          kv_art="gkv_pflicht", net_monthly=D(2100), net_source="input")
    assert m.daily_net == D(70)  # 3 * 2 100 / 90
    assert (m.kk_per_day, m.employer_per_day) == (D(13), D(57))
    assert m.total == D(6930)  # 99 days * 70
    assert m.before_birth == D(2940) and m.from_birth == D(3990)


def test_low_net_pay_gets_no_employer_top_up():
    m = mutterschaftsgeld(due=DUE, birth=DUE, weeks_after=8, erwerbsart=Erwerbsart.ANGESTELLT,
                          kv_art="gkv_pflicht", net_monthly=D(360), net_source="input")
    assert (m.kk_per_day, m.employer_per_day) == (D(12), D(0))


def test_privately_insured_210_eur_once_plus_top_up_and_210_not_credited():
    m = mutterschaftsgeld(due=DUE, birth=DUE, weeks_after=8, erwerbsart=Erwerbsart.ANGESTELLT,
                          kv_art="privat", net_monthly=D(2100), net_source="input")
    assert m.bas_total == D(210)  # § 19 Abs. 2 MuSchG
    assert m.employer_per_day == D(57)
    assert m.credited_per_day == D(57)  # § 3 Abs. 1 Nr. 1 a BEEG excludes the 210 EUR


def _plan(credit_per_day, paid_per_day, ek=600):
    a = monatsbetraege(D(ek))
    parent = ParentContext(label="A", amounts=a, amounts_plain=a)
    row = ["basis"] * 12 + ["none"] * (MAX_LM - 12)
    return evaluate([row], [parent], birth=DUE, birthing=0, single_parent_4c=False, simultaneous_exception=False,
                    maternity=MaternityCredit(end=date(2027, 6, 10), credited_per_day=credit_per_day,
                                              paid_per_day=paid_per_day))


def test_mutterschaftsgeld_is_credited_day_by_day():
    r = _plan(D(70), D(70))
    lm1, lm2 = r.rows[0]["parents"][0], r.rows[1]["parents"][0]
    assert lm1["amount"] == 0 and lm1["mutterschaftsgeld"] == D(2100)  # 30 days * 70
    assert lm2["mutterschutz_days"] == 27 and 0 < lm2["amount"] < lm2["elterngeld_before_credit"]


def test_small_credit_leaves_part_of_elterngeld():
    """Privately insured with a small employer top-up: only that top-up is credited."""
    r = _plan(D(2), D(2), ek=600)
    lm1 = r.rows[0]["parents"][0]
    basis = lm1["elterngeld_before_credit"]
    assert lm1["amount"] == basis - D(2) * 30


def test_no_creditable_benefit_does_not_force_basis_months():
    r = _plan(D(0), D(0))
    assert r.budget["parents"][0]["mutterschutz_basis"] == 0


def test_budget_counts():
    a = monatsbetraege(D(1500))
    parents = [ParentContext(label="A", amounts=a, amounts_plain=a), ParentContext(label="B", amounts=a, amounts_plain=a)]
    one = [["basis"] * 12 + ["none"] * (MAX_LM - 12), ["none"] * MAX_LM]
    r = evaluate(one, parents, birth=DUE, birthing=0, single_parent_4c=False, simultaneous_exception=False,
                 mutterschutz_weeks=8)
    b = r.budget
    assert b["shared_limit"] == 12 and b["shared_left"] == 0 and b["partnermonate"] == "available"
    assert b["parents"][0]["mutterschutz_basis"] == 2
    assert b["parents"][1]["equivalents_left"] == 2  # B would unlock the 2 Partnermonate
    assert b["parents"][1]["basis_possible"] == 2 and b["parents"][1]["plus_possible"] == 4
    assert b["parents"][1]["bonus_left"] == 4
    both = [one[0], ["none"] * 12 + ["basis"] * 2 + ["none"] * (MAX_LM - 14)]
    r = evaluate(both, parents, birth=DUE, birthing=0, single_parent_4c=False, simultaneous_exception=False,
                 mutterschutz_weeks=8)
    assert r.budget["shared_limit"] == 14 and r.budget["shared_left"] == 0 and r.budget["partnermonate"] == "unlocked"
    assert r.budget["parents"][0]["elternzeit_left"] == MAX_LM - 12
