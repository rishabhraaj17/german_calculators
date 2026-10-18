"""Vacation (§ 17 BEEG, § 24 MuSchG), pension points (§§ 56, 70 SGB VI), health insurance (SGB V)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

TL = [["basis"] * 12 + ["none"] * 2 + ["bonus"] * 4 + ["none"] * 18,
      ["none"] * 12 + ["basis"] * 2 + ["bonus"] * 4 + ["none"] * 18]


def body(anna=None, ben=None, **kw):
    a = {"label": "Anna", "birthing_parent": True, "monthly_gross": 3200, "part_time_hours": 25, "vacation_days": 30}
    b = {"label": "Ben", "monthly_gross": 4800, "part_time_hours": 30, "vacation_days": 28}
    return {"birth_date": "2027-04-15", "household": "married", "today": "2026-10-18",
            "parents": [{**a, **(anna or {})}, {**b, **(ben or {})}], "timeline": TL, **kw}


def social(**kw):
    r = client.post("/api/analyse", json=body(**kw))
    assert r.status_code == 200, r.text
    return r.json()["social"]


def test_vacation_reduced_only_for_full_calendar_months_without_part_time():
    v = {x["label"]: x for x in social()["vacation"]}
    anna = {y["year"]: y for y in v["Anna"]["years"]}
    assert anna[2027]["months"] == [f"{m:02d}/2027" for m in range(7, 13)]  # Elternzeit starts 11.06. after Mutterschutz
    assert anna[2027]["max_reduction"] == "15.00" and anna[2027]["remaining_if_reduced"] == "15.00"
    assert anna[2028]["full_months"] == 3 and anna[2028]["part_time_months"] == ["07/2028", "08/2028", "09/2028"]
    ben = v["Ben"]["years"][0]
    assert ben["months"] == ["05/2028"] and ben["max_reduction"] == "2.33"


def test_kindererziehungszeit_three_points_and_assignment():
    p = social()["pension"]
    anna, ben = p["parents"]
    assert anna["points_kez"] == "2.9988"  # 36 x 0.0833 (§ 70 Abs. 2 SGB VI)
    assert ben["points_kez"] == "0.0000"
    swapped = social(kez_parent=1)["pension"]["parents"]
    assert swapped[0]["points_kez"] == "0.0000" and swapped[1]["points_kez_uncapped"] == "2.9988"
    # Ben's 4 800 EUR leave only (8 850 - 4 800) / 53 452 = 0.0758 points/month below the ceiling
    assert 0 < float(swapped[1]["points_kez"]) < 2.9988


def test_kindererziehungszeit_capped_at_contribution_ceiling():
    """Salary at the ceiling leaves no room for extra points (§ 70 Abs. 2 Satz 2 SGB VI)."""
    tl = [["basis"] * 12 + ["none"] * 24, ["none"] * 12 + ["basis"] * 2 + ["none"] * 22]
    p = social(ben={"monthly_gross": 12000}, kez_parent=1, timeline=tl)["pension"]["parents"][1]
    assert float(p["points_kez"]) < float(p["points_kez_uncapped"])


def test_health_compulsory_member_free_during_elterngeld():
    phases = social()["health"]["parents"][0]["phases"]
    assert phases[0]["text"].endswith("Mutterschaftsgeld") and phases[0]["per_month"] == "0"
    assert phases[1]["from_lm"] == 3 and phases[1]["per_month"] == "0"
    salary = next(ph for ph in phases if ph["status"] == "salary")
    assert salary["per_month"] == "337.60"  # 3 200 x (7.3 % + 1.45 %) + 3 200 x 1.8 %


def test_health_voluntary_member_pays_minimum_contribution():
    phases = social(anna={"kv_art": "gkv_freiwillig"})["health"]["parents"][0]["phases"]
    assert phases[0]["status"] == "free"  # Mutterschaftsgeld months (§ 224 Abs. 1 Satz 3 SGB V)
    minimum = next(ph for ph in phases if ph["status"] == "minimum")
    # 2027: 4 130 / 3 x (14.0 % + 2.9 % + 3.6 %) = 282.22
    assert minimum["per_month"] == "282.22"


def test_child_family_insurance_and_exception():
    assert social()["health"]["child"]["status"] == "family"
    excluded = social(ben={"kv_art": "privat", "monthly_gross": 9000})["health"]["child"]
    assert excluded["status"] == "excluded"  # § 10 Abs. 3 SGB V
    unmarried = client.post("/api/analyse", json={**body(ben={"kv_art": "privat", "monthly_gross": 9000}),
                                                   "household": "partnership"}).json()["social"]["health"]["child"]
    assert unmarried["status"] == "family"  # exception applies to spouses only


def test_private_premium_without_employer_subsidy_in_unpaid_months():
    phases = social(anna={"kv_art": "privat", "private_premium": 600})["health"]["parents"][0]["phases"]
    unpaid = next(ph for ph in phases if ph["from_lm"] <= 3 <= ph["to_lm"])
    assert unpaid["per_month"] == "600.00"


def test_kez_advice_prefers_parent_below_the_ceiling():
    """A high earner who keeps working gets KEZ points capped at the ceiling (§ 70 Abs. 2 SGB VI)."""
    k = social(ben={"monthly_gross": 8400})["kez_advice"]
    opts = {o["label"]: o for o in k["options"]}
    assert k["suggested"] == 0 and not k["tie"]
    assert float(opts["Ben"]["kez_points"]) < 2.9988 <= float(opts["Anna"]["kez_points"]) + 1e-9
    assert float(k["margin_points"]) == pytest.approx(float(opts["Anna"]["household_points"]) - float(opts["Ben"]["household_points"]))


def test_kez_advice_excludes_civil_servants():
    k = social(ben={"erwerbsart": "beamt", "kv_art": "privat"})["kez_advice"]
    assert [o["label"] for o in k["options"]] == ["Anna"] and k["excluded"] == ["Ben"]


def test_child_insurance_advice():
    assert social()["child_insurance"]["status"] == "either"
    c = social(ben={"kv_art": "privat"})["child_insurance"]
    assert c["status"] == "family" and c["suggested"] == 0
    c = social(anna={"kv_art": "privat"}, ben={"kv_art": "privat", "erwerbsart": "beamt"})["child_insurance"]
    assert c["status"] == "beihilfe" and c["suggested"] == 1


def test_tax_class_comparison_matches_existing_recommendation():
    t = social()["tax_class"]
    assert t["applicable"] and [o["classes"] for o in t["options"]] == [["IV", "IV"], ["III", "V"], ["V", "III"]]
    assert t["options"][0]["current"] and t["options"][0]["difference"] == "0.00"
    best = next(o for o in t["options"] if o["classes"] == t["best"])
    assert all(float(best["elterngeld_total"]) >= float(o["elterngeld_total"]) for o in t["options"])
    assert t["deadline"] == "2026-08-31" and t["too_late"] is True  # 12 months before birth, Mutterschutz excluded
    early = client.post("/api/analyse", json={**body(), "today": "2026-05-01"}).json()["social"]["tax_class"]
    assert early["too_late"] is False


def test_tax_class_not_applicable_unmarried():
    assert social(household="partnership")["tax_class"] == {"applicable": False}
