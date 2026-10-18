"""Month planner: § 4, 4b, 4c, 15, 16 BEEG rules."""

from datetime import date
from decimal import Decimal as D

from app.elterngeld import monatsbetraege
from app.plan import MAX_LM, ParentContext, evaluate, presets

BIRTH = date(2027, 4, 15)


def ctx(label, ek, hours=0, nach=None):
    a = monatsbetraege(D(ek), ek_nach=D(nach) if nach else None)
    return ParentContext(label=label, amounts=a, amounts_plain=a, part_time_hours=D(hours))


def tl(**ranges):
    """tl(a=[(1, 12, 'basis')], b=[(13, 14, 'basis')]) -> timeline rows"""
    rows = []
    for key in ("a", "b"):
        if key not in ranges:
            continue
        row = ["none"] * MAX_LM
        for frm, to, kind in ranges[key]:
            for lm in range(frm, to + 1):
                row[lm - 1] = kind
        rows.append(row)
    return rows


def run(timeline, parents, birthing=None, **kw):
    return evaluate(timeline, parents, birth=BIRTH, birthing=birthing, mutterschutz_weeks=8,
                    single_parent_4c=kw.get("single", False), simultaneous_exception=kw.get("exception", False))


COUPLE = [ctx("A", 2000), ctx("B", 3000)]


def test_classic_plan_is_valid_and_summed():
    r = run(tl(a=[(1, 12, "basis")], b=[(13, 14, "basis")]), COUPLE)
    assert r.valid, r.errors
    assert r.totals == [D("1300.00") * 12, D("1800.00") * 2]


def test_more_than_14_basis_equivalents_rejected():
    r = run(tl(a=[(1, 12, "basis")], b=[(13, 14, "basis"), (15, 16, "plus")]), COUPLE)
    assert any("max 14" in e for e in r.errors)


def test_partner_months_need_both_parents():
    r = run(tl(a=[(1, 13, "basis")]), [ctx("A", 2000)])
    assert not r.valid  # 13 > 12 for one parent alone


def test_simultaneous_basis_only_one_month():
    assert run(tl(a=[(1, 12, "basis")], b=[(1, 1, "basis"), (13, 13, "basis")]), COUPLE).valid
    r = run(tl(a=[(1, 12, "basis")], b=[(1, 2, "basis")]), COUPLE)
    assert any("§ 4 Abs. 6" in e for e in r.errors)
    assert run(tl(a=[(1, 12, "basis")], b=[(1, 2, "basis")]), COUPLE, exception=True).valid  # twins/premature


def test_basis_only_until_month_14():
    r = run(tl(a=[(1, 10, "basis")], b=[(13, 15, "basis")]), COUPLE)
    assert any("until Lebensmonat 14" in e for e in r.errors)


def test_no_gaps_after_month_14():
    ok = run(tl(a=[(1, 6, "basis"), (7, 18, "plus")], b=[(13, 14, "basis")]), COUPLE)
    assert ok.valid, ok.errors
    gap = run(tl(a=[(1, 6, "basis"), (7, 14, "plus"), (16, 19, "plus")], b=[(13, 14, "basis")]), COUPLE)
    assert any("without gaps" in e for e in gap.errors)


def test_bonus_rules():
    parents = [ctx("A", 2000, hours=25, nach=1200), ctx("B", 3000, hours=30, nach=2000)]
    base = [(1, 12, "basis")], [(13, 14, "basis")]
    ok = run(tl(a=base[0] + [(15, 18, "bonus")], b=base[1] + [(15, 18, "bonus")]), parents)
    assert ok.valid, ok.errors
    unequal = run(tl(a=base[0] + [(15, 18, "bonus")], b=base[1] + [(15, 16, "bonus")]), parents)
    assert any("same months" in e for e in unequal.errors)
    too_long = run(tl(a=base[0] + [(15, 19, "bonus")], b=base[1] + [(15, 19, "bonus")]), parents)
    assert any("2–4 consecutive" in e for e in too_long.errors)
    no_hours = run(tl(a=base[0] + [(15, 18, "bonus")], b=base[1] + [(15, 18, "bonus")]), COUPLE)
    assert any("24–32" in e for e in no_hours.errors)


def test_mutterschutz_months_forced_to_basis_and_credited():
    r = run(tl(a=[(1, 1, "plus"), (2, 12, "basis")], b=[(13, 14, "basis")]), COUPLE, birthing=0)
    assert r.timeline[0][0] == "basis" and r.notes
    lm1, lm2 = r.months[0][0], r.months[0][1]
    assert lm1["amount"] == 0  # fully covered by Mutterschutz (8 weeks)
    assert 0 < lm2["amount"] < D("1300.00")


def test_elternzeit_blocks_and_deadlines():
    r = run(tl(a=[(1, 12, "basis"), (13, 24, "ez")], b=[(13, 14, "basis")]), COUPLE, birthing=0)
    a, b = r.elternzeit
    assert len(a["blocks"]) == 1 and a["blocks"][0]["to_lm"] == 24
    assert a["blocks"][0]["start"] == date(2027, 6, 11)  # day after 8 weeks Mutterschutz
    assert a["blocks"][0]["request_by"] == date(2027, 4, 23)  # 7 weeks before (§ 16 Abs. 1)
    assert b["blocks"][0]["start"] == date(2028, 4, 15)  # Lebensmonat 13
    assert b["blocks"][0]["request_by"] == date(2028, 2, 26)


def test_presets_valid_for_typical_couple():
    parents = [ctx("A", 2000, hours=25, nach=1200), ctx("B", 3000, hours=30, nach=2000)]
    for p in presets(2, 0, False):
        r = run(p["timeline"], parents, birthing=0)
        assert r.valid, (p["id"], r.errors)
    for single4c in (False, True):
        for p in presets(1, 0, single4c):
            r = run(p["timeline"], [ctx("A", 2000, hours=25, nach=1200)], birthing=0, single=single4c)
            assert r.valid, (p["id"], single4c, r.errors)


def test_plain_plus_is_half_basis_and_part_time_only_where_chosen():
    a = ctx("A", 2000, hours=20, nach=1500)
    r = run(tl(a=[(1, 2, "basis"), (3, 4, "plus"), (5, 6, "plus_tz")]), [a])
    assert r.valid, r.errors
    amounts = [m["amount"] for m in r.months[0]]
    assert amounts[2] == a.amounts.plus == D("650.00")  # no work: exactly half of 1 300
    assert amounts[4] == a.amounts.plus_mit_teilzeit < amounts[2]


def test_hours_limit_only_in_working_months():
    a = ctx("A", 2000, hours=40, nach=1500)
    assert run(tl(a=[(1, 2, "basis"), (3, 6, "plus")]), [a]).valid  # not working in these months
    assert not run(tl(a=[(1, 2, "basis"), (3, 6, "plus_tz")]), [a]).valid


def test_partnermonate_need_earned_income_before_birth():
    # § 4 Abs. 3 Satz 2 BEEG: the 2 extra months need a reduction of earned income in 2 Lebensmonate
    none = [ParentContext(label=x, amounts=c.amounts, amounts_plain=c.amounts, earned_before=False) for x, c in
            (("A", ctx("A", 0)), ("B", ctx("B", 0)))]
    r = run(tl(a=[(1, 12, "basis")], b=[(13, 14, "basis")]), none)
    assert not r.valid and any("Partnermonate" in e for e in r.errors)
    assert r.budget["shared_limit"] == 12
    one_earner = [none[0], ctx("B", 3000)]
    assert run(tl(a=[(1, 12, "basis")], b=[(13, 14, "basis")]), one_earner).valid


def test_single_parent_needs_earned_income_for_14_months():
    a = ctx("A", 0)
    alone = [ParentContext(label="A", amounts=a.amounts, amounts_plain=a.amounts, earned_before=False)]
    r = run(tl(a=[(1, 14, "basis")]), alone, single=True)
    assert not r.valid
