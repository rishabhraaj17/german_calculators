from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

COUPLE = {
    "birth_date": "2027-06-20",
    "household": "married",
    "today": "2026-10-18",
    "parents": [
        {"label": "Anna", "birthing_parent": True, "monthly_gross": 2600, "plan": {"basis_months": 12}},
        {"label": "Ben", "monthly_gross": 4500, "plan": {"basis_months": 2}},
    ],
}


def test_health_and_index():
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 200


def test_couple_analysis_with_steuerklasse_advice():
    r = client.post("/api/analyse", json=COUPLE).json()
    assert r["scope"]["tax_year_before_birth"] == 2026
    assert r["income_cap"]["check"]["status"] == "met"
    sk = next(x for x in r["recommendations"] if x["id"] == "steuerklasse_Anna")
    assert sk["deadline"] == "2026-10-31"
    assert float(sk["impact_eur"]) > 0
    assert r["parents"][0]["excluded_months"] == ["2027-05"]  # Mutterschutz from 09.05.2027


def test_steuerklasse_advice_marked_too_late_after_deadline():
    r = client.post("/api/analyse", json={**COUPLE, "today": "2026-11-02"}).json()
    sk = next(x for x in r["recommendations"] if x["id"] == "steuerklasse_Anna")
    assert sk["deadline"] is None and "has passed" in sk["detail"]


def test_over_cap_gives_closable_lever_combination():
    body = {
        **COUPLE,
        "parents": [
            {**COUPLE["parents"][0], "monthly_gross": 9500},
            {**COUPLE["parents"][1], "monthly_gross": 9000},
        ],
        "zve": {
            "mode": "estimate", "zusammenveranlagung": True,
            "persons": [
                {"jahresbrutto": 120000, "rv_arbeitnehmer": 9430, "rv_arbeitgeber": 9430, "kv_arbeitnehmer": 5440,
                 "pv_arbeitnehmer": 1255, "alv_arbeitnehmer": 1318, "pending_one_off": 8000},
                {"jahresbrutto": 110000, "rv_arbeitnehmer": 9430, "rv_arbeitgeber": 9430, "kv_arbeitnehmer": 5440,
                 "pv_arbeitnehmer": 1255, "alv_arbeitnehmer": 1318},
            ],
        },
    }
    r = client.post("/api/analyse", json=body).json()
    gap = r["income_cap"]["gap_analysis"]
    assert r["income_cap"]["check"]["status"] == "not_met"
    assert gap["cap_year_open"] is True and gap["closable_with_quantified_levers"] is True
    combo = gap["suggested_combination"]
    assert combo[0]["id"].startswith("defer_bonus")  # cheapest lever first
    assert sum(float(c["amount"]) for c in combo) >= float(gap["gap"]) + float(gap["safety_buffer"])


def test_closed_cap_year_only_offers_tax_return_levers():
    body = {**COUPLE, "birth_date": "2026-11-20", "today": "2026-10-18",
            "zve": {"mode": "bescheid", "bescheid_values": [180000]}}
    r = client.post("/api/analyse", json=body).json()
    ids = {x["id"] for x in r["recommendations"]}
    assert "closed_year_return" in ids
    assert not any(i.startswith(("bav_", "basisrente_")) for i in ids)


def test_out_of_scope_birth_date_is_rejected():
    assert client.post("/api/analyse", json={**COUPLE, "birth_date": "2025-11-01"}).status_code == 422


def test_single_parent_with_partnermonate():
    body = {
        "birth_date": "2027-02-01", "household": "single", "single_parent_4c": True, "today": "2026-10-18",
        "parents": [{"label": "Mia", "birthing_parent": True, "monthly_gross": 3000, "steuerklasse": "II",
                     "plan": {"basis_months": 14}}],
        "zve": {"mode": "estimate", "alleinerziehend": True, "kinder_im_haushalt": 1},
    }
    r = client.post("/api/analyse", json=body).json()
    assert r["plan"]["valid"], r["plan"]["errors"]


def test_plan_rule_violation_is_reported():
    body = {**COUPLE, "parents": [{**COUPLE["parents"][0], "plan": {"basis_months": 13}}, COUPLE["parents"][1]]}
    r = client.post("/api/analyse", json=body).json()
    assert not r["plan"]["valid"]


def test_bonuses_count_for_income_cap_but_not_for_elterngeld():
    """§ 2c Abs. 1 Satz 2 BEEG excludes sonstige Bezüge; the zvE (§ 1 Abs. 8) includes them."""
    base = client.post("/api/analyse", json=COUPLE).json()
    with_bonus = {**COUPLE, "parents": [{**COUPLE["parents"][0], "bonuses_annual": 20000, "bonuses_pending": 5000},
                                        COUPLE["parents"][1]]}
    r = client.post("/api/analyse", json=with_bonus).json()
    assert r["parents"][0]["amounts"] == base["parents"][0]["amounts"]
    assert r["parents"][0]["bonuses_excluded"] == "20000"
    assert float(r["income_cap"]["zve_total"]) > float(base["income_cap"]["zve_total"]) + 15000
    assert any(x["id"] == "bonuses_Anna" for x in r["recommendations"])


def test_pending_bonus_becomes_defer_lever_when_over_cap():
    body = {**COUPLE, "parents": [
        {**COUPLE["parents"][0], "monthly_gross": 9000, "bonuses_annual": 15000, "bonuses_pending": 10000},
        {**COUPLE["parents"][1], "monthly_gross": 8500}]}
    r = client.post("/api/analyse", json=body).json()
    assert r["income_cap"]["check"]["status"] == "not_met"
    defer = next(x for x in r["recommendations"] if x["id"] == "defer_bonus_Anna")
    assert defer["impact_eur"] == "10000"


def test_pending_bonus_cannot_exceed_annual():
    body = {**COUPLE, "parents": [{**COUPLE["parents"][0], "bonuses_annual": 100, "bonuses_pending": 200},
                                  COUPLE["parents"][1]]}
    assert client.post("/api/analyse", json=body).status_code == 422


def _anna(**kw):
    return {**COUPLE, "parents": [{**COUPLE["parents"][0], **kw}, COUPLE["parents"][1]]}


def test_bav_conversion_is_not_counted_for_elterngeld():
    """Tax-free § 3 Nr. 63 EStG conversion is not part of the Steuerbrutto (Richtlinien 2.1.3.1.2)."""
    with_bav = client.post("/api/analyse", json=_anna(monthly_gross=2600, bav_monthly=200)).json()
    lower_gross = client.post("/api/analyse", json=_anna(monthly_gross=2400)).json()
    assert with_bav["parents"][0]["amounts"] == lower_gross["parents"][0]["amounts"]
    assert with_bav["parents"][0]["bav_deducted"] == "200.00"


def test_bav_deduction_capped_at_tax_free_limit():
    # birth 2027 -> year 2026: 8 % of 101 400 = 8 112 EUR / 12 = 676 EUR per month
    r = client.post("/api/analyse", json=_anna(monthly_gross=6000, bav_monthly=1000)).json()
    assert r["parents"][0]["bav_deducted"] == "676.00"
    assert r["parents"][0]["netto"]["brutto"] == "5324.00"


def test_bav_lowers_quick_zve_and_remaining_lever():
    def body(**kw):
        b = _anna(monthly_gross=9500, bonuses_annual=30000, **kw)
        b["parents"][1] = {**b["parents"][1], "monthly_gross": 7000}  # couple clearly over the cap
        return b
    base = client.post("/api/analyse", json=body()).json()
    r = client.post("/api/analyse", json=body(bav_monthly=300)).json()
    assert r["income_cap"]["check"]["status"] == "not_met"
    assert float(base["income_cap"]["zve_total"]) - float(r["income_cap"]["zve_total"]) > 3000
    lever = next(x for x in r["recommendations"] if x["id"] == "bav_Anna")
    assert lever["impact_eur"] == "4512.00"  # 8 112 - 12 * 300
    assert any("bonus" in c for c in lever["caveats"])


def test_month_planner_timeline_and_presets():
    parents = [{**COUPLE["parents"][0], "part_time_gross": 1500, "part_time_hours": 25},
               {**COUPLE["parents"][1], "part_time_gross": 2500, "part_time_hours": 30}]
    r = client.post("/api/analyse", json={**COUPLE, "parents": parents}).json()
    ids = [p["id"] for p in r["plan"]["presets"]]
    assert ids == ["classic", "split", "plus", "bonus", "together", "long", "early"]
    assert all(p["valid"] for p in r["plan"]["presets"]), [p["errors"] for p in r["plan"]["presets"]]
    bonus = next(p for p in r["plan"]["presets"] if p["id"] == "bonus")
    rec = next(x for x in r["recommendations"] if x["id"] == "partnerschaftsbonus")
    assert rec["confidence"] == "exact"
    # apply the bonus preset as the user's own timeline
    r2 = client.post("/api/analyse", json={**COUPLE, "parents": parents, "timeline": bonus["timeline"]}).json()
    assert r2["plan"]["valid"] and r2["plan"]["household_total"] == bonus["household_total"]
    assert not any(x["id"] == "partnerschaftsbonus" for x in r2["recommendations"])  # already used
    assert r2["plan"]["elternzeit"][0]["blocks"][0]["request_by"]


def test_timeline_must_match_parents():
    assert client.post("/api/analyse", json={**COUPLE, "timeline": [["basis"] * 12]}).status_code == 422


def test_mutterschaftsgeld_in_analysis():
    r = client.post("/api/analyse", json=COUPLE).json()
    m = r["mutterschutz"]
    assert m["status"] == "gkv" and m["net_source"] == "estimate" and m["total_days"] == 99
    assert m["kk_per_day"] == "13" and float(m["employer_per_day"]) > 0
    with_net = client.post("/api/analyse", json=_anna(net_monthly=1800)).json()["mutterschutz"]
    assert with_net["net_source"] == "input" and with_net["daily_net"] == "60.00"
    priv = client.post("/api/analyse", json=_anna(kv_art="privat", net_monthly=1800)).json()
    assert priv["mutterschutz"]["bas_total"] == "210"
    assert priv["parents"][0]["netto"]["sozialabgaben"] != r["parents"][0]["netto"]["sozialabgaben"]  # no 9 % KV/PV


def test_budget_in_plan():
    b = client.post("/api/analyse", json=COUPLE).json()["plan"]["budget"]
    assert b["shared_used"] == "14" and b["partnermonate"] == "unlocked"


def test_part_time_gross_derived_from_hours():
    """Without an entered part-time gross: monthly gross x part-time hours / contract hours."""
    body = _anna(monthly_gross=4000, part_time_hours=20, weekly_hours=40)
    r = client.post("/api/analyse", json=body).json()
    pt = r["parents"][0]["part_time"]
    assert pt["source"] == "hours" and pt["gross"] == "2000.00"
    assert 0 < float(pt["net_pay"]) < 2000
    same = client.post("/api/analyse", json=_anna(monthly_gross=4000, part_time_gross=2000, part_time_hours=20)).json()
    assert r["parents"][0]["amounts"] == same["parents"][0]["amounts"]  # identical Elterngeld
    assert same["parents"][0]["part_time"]["source"] == "input"


def test_net_pay_shown_in_working_months():
    parents = [{**COUPLE["parents"][0], "part_time_hours": 25},
               {**COUPLE["parents"][1], "part_time_hours": 30}]
    tl = [["basis"] * 12 + ["none"] * 2 + ["bonus"] * 4 + ["none"] * 18,
          ["none"] * 12 + ["basis"] * 2 + ["bonus"] * 4 + ["none"] * 18]
    r = client.post("/api/analyse", json={**COUPLE, "parents": parents, "timeline": tl}).json()
    assert r["plan"]["valid"], r["plan"]["errors"]
    lm15 = r["plan"]["rows"][14]["parents"]
    assert all("net_pay" in c for c in lm15)
    assert "net_pay" not in r["plan"]["rows"][2]["parents"][0]  # not working in Basis months
    assert lm15[0]["net_pay"] == r["parents"][0]["part_time"]["net_pay"]
    lm13 = r["plan"]["rows"][12]["parents"][0]
    assert lm13["hours"] == "40" and float(lm13["net_pay"]) > float(lm15[0]["net_pay"])  # back at work full-time


HOURS_BODY = {**COUPLE, "parents": [{**COUPLE["parents"][0], "part_time_hours": 25},
                                    {**COUPLE["parents"][1], "part_time_hours": 30}],
              "timeline": [["basis"] * 12 + ["none"] * 2 + ["bonus"] * 4 + ["none"] * 18,
                           ["none"] * 12 + ["basis"] * 2 + ["bonus"] * 4 + ["none"] * 18]}


def _hours(a=None, b=None):
    rows = [[None] * 36, [None] * 36]
    for lm, h in (a or {}).items():
        rows[0][lm - 1] = h
    for lm, h in (b or {}).items():
        rows[1][lm - 1] = h
    return rows


def test_hours_per_month_drive_salary_and_elterngeld():
    base = client.post("/api/analyse", json=HOURS_BODY).json()["plan"]
    r = client.post("/api/analyse", json={**HOURS_BODY, "hours": _hours(a={15: 24, 16: 24, 17: 32, 18: 32})}).json()["plan"]
    assert r["valid"], r["errors"]
    m15, m17 = r["rows"][14]["parents"][0], r["rows"][16]["parents"][0]
    assert m15["gross_pay"] == "1560.00" and m17["gross_pay"] == "2080.00"  # 2 600 * 24/40, * 32/40
    # § 2 Abs. 3 Satz 3: one Plus amount from the average income of all Plus/Bonus months
    assert m15["amount"] == m17["amount"]
    avg_same = client.post("/api/analyse", json={**HOURS_BODY, "hours": _hours(a={k: 28 for k in range(15, 19)})}).json()["plan"]
    assert avg_same["rows"][14]["parents"][0]["amount"] == m15["amount"]  # average 28 h either way
    assert m15["total_net"] == str(round(float(m15["amount"]) + float(m15["net_pay"]), 2))
    assert base["month_totals"][0]["total"] != r["month_totals"][0]["total"]


def test_hours_limits_per_month():
    over = client.post("/api/analyse", json={**HOURS_BODY, "hours": _hours(a={3: 35})}).json()["plan"]
    assert any("32 h/week in month 3" in e for e in over["errors"])
    bonus = client.post("/api/analyse", json={**HOURS_BODY, "hours": _hours(b={16: 20})}).json()["plan"]
    assert any("check month 16" in e for e in bonus["errors"])


def test_no_work_during_mutterschutz():
    r = client.post("/api/analyse", json={**HOURS_BODY, "hours": _hours(a={1: 20})}).json()["plan"]
    assert r["rows"][0]["parents"][0]["hours"] == "0"



def _quick_zve(kv_art, **extra):
    body = {**COUPLE, "parents": [{**p, "monthly_gross": 7500, "kv_art": kv_art, **extra} for p in COUPLE["parents"]]}
    return client.post("/api/analyse", json=body).json()["income_cap"]


def test_quick_zve_deducts_voluntary_gkv_contributions():
    # voluntary members pay the same employee share as compulsory members (§ 10 Abs. 1 Nr. 3 EStG)
    pflicht, freiwillig = _quick_zve("gkv_pflicht"), _quick_zve("gkv_freiwillig")
    assert freiwillig["zve_total"] == pflicht["zve_total"]


def test_quick_zve_deducts_private_premium_minus_employer_subsidy():
    without = _quick_zve("privat")
    with_premium = _quick_zve("privat", private_premium=800)
    # 800 €/month premium, employer pays half (below the § 257 cap): 400 × 12 = 4 800 € own share per person;
    # above the 1 900 € cap the basic cover is deducted in full and crowds out the ALV contributions
    assert with_premium["detail"]["kranken_pflege_sonstige_vorsorge"] == "9600"
    assert int(with_premium["zve_total"]) < int(without["zve_total"])
    assert any("private premium" in h for h in without["detail"]["hinweise"])


def test_bescheid_zve_reduced_by_kinderfreibetraege_if_not_yet_deducted():
    # Kindergeld was more favourable, so the Bescheid did not deduct the Freibeträge für Kinder;
    # for § 1 Abs. 8 BEEG they are always deducted (Richtlinien 1.8): 2 × (3 414 + 1 464) = 9 756 € in 2026
    zve = {"mode": "bescheid", "bescheid_values": [180000], "kinderfreibetrag_zaehler": 1}
    as_is = client.post("/api/analyse", json={**COUPLE, "zve": zve}).json()["income_cap"]
    reduced = client.post("/api/analyse", json={**COUPLE, "zve": {**zve, "bescheid_kfb_abgezogen": False}}).json()
    assert as_is["zve_total"] == "180000" and as_is["check"]["status"] == "not_met"
    assert reduced["income_cap"]["zve_total"] == "170244"
    assert reduced["income_cap"]["check"]["status"] == "met"


def test_steuerklasse_deadline_has_buffer_for_early_birth():
    # nobody gives birth in this household's data -> no Mutterschutz exclusion; BMZ 06/2026–05/2027.
    # Latest switch: effective 12/2026 (6 of 12 months). If the child arrives in May, the BMZ moves
    # to 05/2026–04/2027 and the switch must already apply from 11/2026.
    parents = [{**p, "birthing_parent": False} for p in COUPLE["parents"]]
    r = client.post("/api/analyse", json={**COUPLE, "parents": parents}).json()
    sk = next(x for x in r["recommendations"] if x["id"] == "steuerklasse_Anna")
    assert sk["deadline"] == "2026-10-31"
    assert "30.11.2026" in sk["detail"] and "early" in sk["detail"]
    assert r["social"]["tax_class"]["deadline"] == "2026-10-31"
    assert r["social"]["tax_class"]["deadline_latest"] == "2026-11-30"

    late = client.post("/api/analyse", json={**COUPLE, "parents": parents, "today": "2026-11-10"}).json()
    sk = next(x for x in late["recommendations"] if x["id"] == "steuerklasse_Anna")
    assert sk["deadline"] == "2026-11-30" and any("early" in c for c in sk["caveats"])


def test_mutterschutz_months_kept_on_request():
    # § 2b Abs. 1 Satz 3 BEEG: on request the Mutterschutz months are not skipped
    anna = {**COUPLE["parents"][0], "include_mutterschutz_months": True}
    r = client.post("/api/analyse", json={**COUPLE, "parents": [anna, COUPLE["parents"][1]]}).json()
    assert r["parents"][0]["excluded_months"] == []
    assert r["parents"][0]["bemessungszeitraum"][-1] == "2027-05"


def test_explicit_zero_part_time_gross_is_kept():
    from app.models import ParentIn
    p = ParentIn(monthly_gross=3000, part_time_hours=20, part_time_gross=0)
    assert p.part_time == (0, "input")


def test_civil_servant_without_kv_art_is_privately_insured():
    from app.models import ParentIn
    from app.service import _kv_art
    assert _kv_art(ParentIn(erwerbsart="beamt", monthly_gross=4000)) == "privat"
    assert _kv_art(ParentIn(monthly_gross=4000)) == "gkv_pflicht"


def test_quick_zve_ignores_flat_taxed_minijob():
    # § 40a Abs. 2 EStG: pauschal taxed Minijob pay is not part of the zvE
    body = {**COUPLE, "parents": [{**COUPLE["parents"][0], "erwerbsart": "minijob", "monthly_gross": 500},
                                  COUPLE["parents"][1]]}
    only_ben = {**COUPLE, "parents": [{**COUPLE["parents"][0], "erwerbsart": "keine", "monthly_gross": 0},
                                      COUPLE["parents"][1]]}
    assert client.post("/api/analyse", json=body).json()["income_cap"]["zve_total"] == \
        client.post("/api/analyse", json=only_ben).json()["income_cap"]["zve_total"]


def test_geschwisterbonus_names_last_month_with_bonus():
    # sibling born 01.08.2024 turns 3 on 01.08.2027; birth 20.06.2027 -> LM 2 starts 20.07.2027 (sibling 2),
    # LM 3 starts 20.08.2027 (sibling 3): the bonus is paid through LM 2
    r = client.post("/api/analyse", json={**COUPLE, "siblings": [{"birth_date": "2024-08-01"}]}).json()
    gb = next(x for x in r["recommendations"] if x["id"] == "geschwisterbonus")
    assert "Lebensmonat 2 " in gb["detail"]


@pytest.mark.parametrize("patch", [
    {"parents": [{**COUPLE["parents"][0], "monthly_gross_list": [-100] + [3000] * 11}, COUPLE["parents"][1]]},
    {"parents": [{**COUPLE["parents"][0], "extra_excluded_months": ["2026-13"]}, COUPLE["parents"][1]]},
    {"parents": [{**COUPLE["parents"][0], "extra_excluded_months": ["abc"]}, COUPLE["parents"][1]]},
    {"parents": [{**COUPLE["parents"][0], "extra_excluded_months": ["2026-01"] * 40}, COUPLE["parents"][1]]},
    {"siblings": [{"birth_date": "2024-01-01"}] * 30},
    {"zve": {"mode": "bescheid", "bescheid_values": [-5]}},
    {"zve": {"mode": "bescheid", "bescheid_values": [1, 2, 3]}},
    {"zve": {"persons": [{}] * 3}},
])
def test_input_limits_are_validated(patch):
    r = client.post("/api/analyse", json={**COUPLE, **patch})
    assert r.status_code == 422


def test_invalid_plan_gets_best_single_month_fix():
    # B takes Basis in LM 1–2 while A's Mutterschaftsgeld months count as Basis: two simultaneous
    # Basis months (§ 4 Abs. 6 BEEG). Best fix: B's LM 2 as Plus instead of Basis.
    tl = [["basis"] * 12 + ["none"] * 24, ["basis"] * 2 + ["none"] * 34]
    r = client.post("/api/analyse", json={**COUPLE, "timeline": tl}).json()["plan"]
    assert not r["valid"]
    best = r["fixes"][0]
    assert len(best["changes"]) == 1 and best["changes"][0]["parent"] == 1
    assert best["changes"][0]["from"] == "basis" and best["changes"][0]["to"] in ("plus", "plus_tz", "none", "ez")
    valid = client.post("/api/analyse", json={**COUPLE, "timeline": best["timeline"], "hours": best["hours"]}).json()
    assert valid["plan"]["valid"] and valid["plan"]["household_total"] == best["household_total"]
    assert valid["plan"]["fixes"] == []


def test_bonus_paid_monthly_is_regular_pay():
    # paid with every salary = laufender Arbeitslohn: counts for Elterngeld (unlike sonstige Bezüge)
    def run(kind):
        ben = {**COUPLE["parents"][1], "monthly_gross": 3000, "bonuses_annual": 6000, "bonus_payment": kind}
        return client.post("/api/analyse", json={**COUPLE, "parents": [COUPLE["parents"][0], ben]}).json()
    one_off, monthly = run("one_off"), run("monthly")
    assert one_off["parents"][1]["netto"]["brutto"] == "3000.00"
    assert monthly["parents"][1]["netto"]["brutto"] == "3500.00"
    assert monthly["parents"][1]["bonuses_excluded"] == "0"
    assert one_off["income_cap"]["zve_total"] == monthly["income_cap"]["zve_total"]  # same annual pay
    assert not any(r["id"].startswith("bonuses_") for r in monthly["recommendations"])


def test_quick_zve_includes_childless_care_surcharge():
    # § 55 Abs. 3 SGB XI: +0.6 % for childless members in the cap year (the child is born the year after);
    # each parent at 7 500 €/month pays it on the KV/PV ceiling 69 750 € (2026): 418,50 € more deduction each
    childless = client.post("/api/analyse", json={**COUPLE, "parents": [{**p, "monthly_gross": 7500} for p in COUPLE["parents"]]}).json()
    with_child = client.post("/api/analyse", json={**COUPLE, "siblings": [{"birth_date": "2024-05-01"}],
                                                   "parents": [{**p, "monthly_gross": 7500} for p in COUPLE["parents"]]}).json()
    d0, d1 = childless["income_cap"]["detail"], with_child["income_cap"]["detail"]
    assert int(d0["kranken_pflege_sonstige_vorsorge"]) - int(d1["kranken_pflege_sonstige_vorsorge"]) == 837
    assert any("childless" in h for h in d0["hinweise"])


def _payslip(**kw):
    base = {"month": 9, "brutto_month": 6000, "brutto_ytd": 64000, "rv_month": 558, "rv_ytd": 5952,
            "alv_month": 78, "alv_ytd": 832, "kv_month": 508.5, "kv_ytd": 4576.5, "pv_month": 104.63, "pv_ytd": 941.67}
    return {**base, **kw}


def test_payslip_ytd_is_extrapolated_without_scaling_one_offs():
    # Jan–Sep actual (incl. a 10 000 € bonus), Oct–Dec at September's values: 64 000 + 3 × 6 000 = 82 000
    from app.models import ParentIn, PayslipPersonIn
    from app.service import annualise_payslip
    from app import params as P
    p = annualise_payslip(PayslipPersonIn(**_payslip()), ParentIn(monthly_gross=6000), P.TAX_YEARS[2026])
    assert p.jahresbrutto == 82000
    assert p.rv_arbeitnehmer == p.rv_arbeitgeber == 5952 + 3 * 558
    assert p.kv_arbeitnehmer == D("4576.5") + 3 * D("508.5")
    assert p.pv_arbeitnehmer == D("941.67") + 3 * D("104.63") and p.alv_arbeitnehmer == 832 + 3 * 78


def test_payslip_one_off_still_due_gets_contributions_only_up_to_the_ceiling():
    from app.models import ParentIn, PayslipPersonIn
    from app.service import annualise_payslip
    from app import params as P
    ty = P.TAX_YEARS[2026]  # RV ceiling 101 400, KV ceiling 69 750
    p = annualise_payslip(PayslipPersonIn(**_payslip(one_off_due=50000)), ParentIn(monthly_gross=6000), ty)
    assert p.jahresbrutto == 132000 and p.pending_one_off == 50000
    # RV room: 101 400 − (64 000 + 3 × 6 000) = 19 400 at September's rate 558 / 6 000 = 9.3 %
    assert p.rv_arbeitnehmer == 5952 + 3 * 558 + D("1804.20")
    # KV room: 69 750 − 82 000 < 0 -> nothing more
    assert p.kv_arbeitnehmer == D("4576.5") + 3 * D("508.5")


def test_payslip_mode_in_analysis():
    zve = {"mode": "payslip", "zusammenveranlagung": True, "payslips": [_payslip(), _payslip(brutto_ytd=54000)]}
    r = client.post("/api/analyse", json={**COUPLE, "zve": zve}).json()["income_cap"]
    assert r["source"] == "payslip"
    assert any("09/2026" in h for h in r["detail"]["hinweise"])
    assert r["detail"]["einkuenfte_nichtselbstaendig"] == str(82000 + 72000 - 2 * 1230)


def test_payslip_year_to_date_cannot_be_below_the_month():
    zve = {"mode": "payslip", "payslips": [_payslip(rv_ytd=100), _payslip()]}
    assert client.post("/api/analyse", json={**COUPLE, "zve": zve}).status_code == 422


def test_fix_search_scores_a_bounded_number_of_candidates(monkeypatch):
    # an invalid plan with many valid one-month fixes must not trigger one full evaluation per candidate
    from app import service as S
    calls = []
    real = S._plan
    monkeypatch.setattr(S, "_plan", lambda *a, **kw: calls.append(1) or real(*a, **kw))
    tl = [["plus"] * 13 + ["none"] * 23, ["basis"] + ["none"] * 35]
    parents = [{**p, "part_time_hours": 28} for p in COUPLE["parents"]]
    r = client.post("/api/analyse", json={**COUPLE, "parents": parents, "timeline": tl}).json()
    assert not r["plan"]["valid"] and r["plan"]["fixes"]
    assert sum(calls) <= S.MAX_SCORED_FIXES + 15  # + the plan itself, presets and tax-class scenarios


def test_bundles_show_income_and_time_at_home_and_apply_with_their_hours():
    r = client.post("/api/analyse", json=COUPLE).json()["plan"]
    by_id = {p["id"]: p for p in r["presets"]}
    assert all(p["valid"] for p in r["presets"]), {p["id"]: p["errors"] for p in r["presets"]}
    # no part-time hours entered: bonus and part-time months get 24 h, so the bundles are valid as offered
    assert by_id["bonus"]["hours"][0][14] == "24" and by_id["early"]["hours"][0][2] == "24"
    classic, long_ = by_id["classic"], by_id["long"]
    assert classic["home_months"] == [12, 2] and long_["home_months"] == [22, 2]
    assert classic["household_total"] == long_["household_total"]  # same Elterngeld budget
    assert float(long_["household_net_24"]) < float(classic["household_net_24"])  # more salary lost
    assert "household_net_24" in r and "home_months" in r
    applied = client.post("/api/analyse", json={**COUPLE, "timeline": by_id["early"]["timeline"],
                                                "hours": by_id["early"]["hours"]}).json()["plan"]
    assert applied["valid"] and applied["household_net_24"] == by_id["early"]["household_net_24"]


def test_partnerschaftsbonus_advice_includes_lost_salary():
    rec = next(x for x in client.post("/api/analyse", json=COUPLE).json()["recommendations"]
               if x["id"] == "partnerschaftsbonus")
    assert "household income" in rec["detail"]


@pytest.mark.parametrize("change", [
    {},
    {"children_expected": 2},  # 12 weeks Mutterschutz: months 1–3 count as Basis
    {"premature_or_disability": True},
    {"due_date": "2027-07-15"},  # born 3½ weeks early: Schutzfrist extended
    {"parents": [{**COUPLE["parents"][0], "erwerbsart": "keine", "monthly_gross": 0}, COUPLE["parents"][1]]},
    {"parents": [{**p, "erwerbsart": "keine", "monthly_gross": 0} for p in COUPLE["parents"]]},  # no Partnermonate
    {"parents": [COUPLE["parents"][0], {**COUPLE["parents"][1], "birthing_parent": True}],
     "household": "partnership"},
])
def test_every_offered_bundle_is_feasible(change):
    body = {**COUPLE, **change}
    if "parents" in change and sum(p.get("birthing_parent", False) for p in body["parents"]) > 1:
        body["parents"][0] = {**body["parents"][0], "birthing_parent": False}
    r = client.post("/api/analyse", json=body).json()["plan"]["presets"]
    assert r and all(p["valid"] for p in r), {p["id"]: p["errors"] for p in r if not p["valid"]}
    for p in r:  # and it stays valid when applied as the user's plan
        applied = client.post("/api/analyse", json={**body, "timeline": p["timeline"], "hours": p["hours"]}).json()
        assert applied["plan"]["valid"], (p["id"], applied["plan"]["errors"])


def test_bundles_adapt_to_mutterschutz_and_jobs():
    twins = {p["id"]: p for p in client.post("/api/analyse", json={**COUPLE, "children_expected": 2}).json()["plan"]["presets"]}
    assert twins["long"]["timeline"][0][:4] == ["basis", "basis", "basis", "plus"]
    jobless = [{**COUPLE["parents"][0], "erwerbsart": "keine", "monthly_gross": 0}, COUPLE["parents"][1]]
    ids = [p["id"] for p in client.post("/api/analyse", json={**COUPLE, "parents": jobless}).json()["plan"]["presets"]]
    assert "bonus" not in ids and "early" not in ids and "classic" in ids


def test_bundle_applied_without_its_hours_still_valid():
    # an older page applied bundles without their hours: bonus months must not default to 0 h
    bundle = next(p for p in client.post("/api/analyse", json=COUPLE).json()["plan"]["presets"] if p["id"] == "together")
    r = client.post("/api/analyse", json={**COUPLE, "timeline": bundle["timeline"], "hours": None}).json()["plan"]
    assert r["valid"], r["errors"]
    assert r["hours"][0][14] == r["hours"][1][14] == "24"  # bonus month 15 -> 24 h when none planned
    assert r["household_net_24"] == bundle["household_net_24"]


def test_index_references_assets_with_current_version():
    # cache busting: the ?v= stamp must change whenever app.js or styles.css change
    import hashlib
    from pathlib import Path
    public = Path(__file__).resolve().parents[2] / "public"
    stamp = hashlib.sha256(b"".join((public / "static" / f).read_bytes()
                                    for f in ("app.js", "styles.css"))).hexdigest()[:10]
    html = (public / "index.html").read_text()
    assert f"/static/styles.css?v={stamp}" in html and f"/static/app.js?v={stamp}" in html, \
        f"update the asset version in index.html to ?v={stamp}"


def _mg_rec(body):
    r = client.post("/api/analyse", json=body)
    assert r.status_code == 200, r.text
    return next((x for x in r.json()["recommendations"] if x["id"] == "steuerklasse_mutterschaftsgeld"), None)


def test_tax_class_switch_for_more_mutterschaftsgeld():
    # Anna gives birth 20.06.2027: Schutzfrist from 09.05.2027, so Mutterschaftsgeld uses the net pay of
    # Feb–Apr 2027. Latest switch that covers all 3 months: class III from February, filed by 31.01.2027.
    rec = _mg_rec(COUPLE)
    assert rec and rec["deadline"] == "2027-01-31" and float(rec["impact_eur"]) > 0
    assert "02/2027" in rec["detail"] and "Mutterschaftsgeld" in rec["title"]


def test_mutterschaftsgeld_switch_partial_when_late_and_absent_when_not_applicable():
    late = _mg_rec({**COUPLE, "today": "2027-02-10"})  # only March and April can still change
    full = _mg_rec(COUPLE)
    assert late["deadline"] == "2027-02-28" and float(late["impact_eur"]) < float(full["impact_eur"])
    assert _mg_rec({**COUPLE, "today": "2027-04-05"}) is None  # all reference months settled or decided
    already_iii = [{**COUPLE["parents"][0], "steuerklasse": "III"}, {**COUPLE["parents"][1], "steuerklasse": "V"}]
    assert _mg_rec({**COUPLE, "parents": already_iii}) is None
    assert _mg_rec({**COUPLE, "household": "partnership"}) is None  # tax classes III/V only for spouses


def test_mutterschaftsgeld_switch_independent_of_income_cap():
    over = {**COUPLE, "zve": {"mode": "bescheid", "bescheid_values": [180000]}}
    rec = _mg_rec(over)
    assert rec and not any("income cap" in c for c in rec["caveats"])
