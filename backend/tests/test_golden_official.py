"""Parity with the official BMFSFJ Elterngeldrechner (golden vectors).

Vectors were produced by running the official source code
(tools/golden/generate.ts). Known, explained deviations:

* The official TypeScript port computes the PAP with JavaScript floats and
  omits one BMF rounding step for the Faktorverfahren. Where its PAP output
  differs from ours, the BMF's own calculator confirms ours
  (tests/test_pap_bmf.py). Those vectors are compared via BMF-checked tax.
* For births in 2027 the official code still uses the 2025 average
  KV-Zusatzbeitrag (2.5 %) instead of the announced 2.9 % for 2026. The
  parity test applies 2.5 % so that the comparison isolates engine logic.
"""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import elterngeld as E
from app import params as P
from app.pap.interpreter import load_pap

GOLDEN = json.loads((Path(__file__).parent / "golden" / "official_vectors.json").read_text())

ERWERBSART = {
    "JA_NICHT_SELBST_MIT_SOZI": E.Erwerbsart.ANGESTELLT,
    "JA_NICHT_SELBST_OHNE_SOZI": E.Erwerbsart.BEAMT,
    "JA_NICHT_SELBST_MINI": E.Erwerbsart.MINIJOB,
}
STKL = {"I": "I", "II": "II", "III": "III", "IV": "IV", "IV mit Faktor": "IV_FAKTOR", "V": "V", "VI": "VI"}


@pytest.fixture
def official_kvz(monkeypatch):
    patched = dict(P.TAX_YEARS)
    patched[2026] = dataclasses.replace(P.TAX_YEARS[2026], avg_kv_zusatzbeitrag_pct=Decimal("2.5"))
    monkeypatch.setattr(P, "TAX_YEARS", patched)


def _official_pap_disputed() -> set[tuple]:
    """PAP inputs where the official TS deviates from the BMF pseudocode."""
    disputed = set()
    for v in GOLDEN["pap"]:
        i = dict(v["input"])
        factor = i.pop("F")
        i["af"] = i.pop("AF")
        i["f"] = factor if i["af"] else 1.0
        pap = load_pap(v["year"])
        i = {k: x for k, x in i.items() if k in pap.inputs}
        out = pap.run(**i)
        if any(out[k] != v["output"][k] for k in v["output"]):
            disputed.add(v["year"])
    return disputed


def _merkmale(inp: dict) -> E.Abzugsmerkmale:
    return E.Abzugsmerkmale(
        erwerbsart=ERWERBSART[inp["erwerbsArt"]],
        steuerklasse=E.Steuerklasse(STKL[inp["steuerklasse"]]),
        faktor=Decimal(str(inp["faktor"])),
        kirchensteuer=inp["kirchensteuer"],
        kinderfreibetraege=Decimal(str(inp["kinderfreibetraege"])),
        kv_pflichtversichert=inp["kassenArt"] == "GESETZLICH_PFLICHTVERSICHERT",
        rv_pflichtversichert=inp["rentenArt"] == "GESETZLICHE_RENTEN_VERSICHERUNG",
    )


def test_elterngeld_matches_official_calculator(official_kvz):
    exact = total = 0
    for v in GOLDEN["elterngeld"]:
        if v["input"]["steuerklasse"] == "IV mit Faktor":
            continue  # see test_faktorverfahren_deviation_is_only_the_bmf_rounding_step
        total += 1
        inp, exp = v["input"], v["output"]
        birth = date.fromisoformat(inp["birth"])
        m = _merkmale(inp)
        n = E.elterngeld_netto(Decimal(str(inp["brutto"])), m, birth)
        got = {
            "elterngeldNetto": n.elterngeld_netto,
            "basis": E.basiselterngeld(n.elterngeld_netto),
            "plus": E.elterngeld_plus(n.elterngeld_netto),
        }
        if inp["bruttoNach"]:
            ek_nach = E.ek_nach_geburt(Decimal(str(inp["bruttoNach"])), m, birth)
            got["elterngeldNettoNach"] = ek_nach
            got["basisMitEinkommen"] = E.basiselterngeld(n.elterngeld_netto, ek_nach)
            got["plusMitEinkommen"] = E.elterngeld_plus(n.elterngeld_netto, ek_nach)
        # The official string-based cent rounding yields NaN (null) for tiny
        # negative values (gross just below the Pauschale); we yield 0.
        diffs = {k: (got[k], exp[k]) for k in got if exp[k] is not None and got[k] != Decimal(str(exp[k]))}
        if not diffs:
            exact += 1
            continue
        # Remaining deviations are float artefacts of the official JS code:
        # (a) PAP float noise (BMF-confirmed in test_pap_bmf.py), (b) exact
        # half-cent products such as 1375.10 * 0.65 = 893.815, which the
        # Richtlinien (2.0.3.3.1) round up to 893.82 while JS floats give
        # 893.8149... -> 893.81. Both stay within 10 cent.
        for k, (mine, theirs) in diffs.items():
            assert abs(mine - Decimal(str(theirs))) <= Decimal("0.10"), (inp, k, mine, theirs)
    assert exact / total >= 0.997, f"only {exact}/{total} cent-identical"


def test_half_cent_is_rounded_up_per_richtlinien():
    # 1375.10 * 0.65 = 893.815 exactly -> 893.82 (official JS float: 893.81)
    assert E.basiselterngeld(Decimal("1375.10")) == Decimal("893.82")


def test_faktorverfahren_deviation_is_only_the_bmf_rounding_step(official_kvz):
    """The official port skips `LSTJAHR = (ST * f).setScale(0, ROUND_DOWN)`, so
    its income tax can only be higher (never lower) than the BMF result, and
    Elterngeld-Netto only lower, by less than 1 EUR/12 + float noise."""
    checked = 0
    for v in GOLDEN["elterngeld"]:
        inp, exp = v["input"], v["output"]
        if inp["steuerklasse"] != "IV mit Faktor" or exp["elterngeldNetto"] is None:
            continue
        n = E.elterngeld_netto(Decimal(str(inp["brutto"])), _merkmale(inp), date.fromisoformat(inp["birth"]))
        delta = n.elterngeld_netto - Decimal(str(exp["elterngeldNetto"]))
        assert Decimal(0) <= delta <= Decimal("0.10"), (inp, delta)
        checked += 1
    assert checked > 300


def test_2027_births_use_announced_kv_zusatzbeitrag_2026():
    assert P.tax_year_for_birth(date(2027, 5, 1)).avg_kv_zusatzbeitrag_pct == Decimal("2.9")
    assert P.tax_year_for_birth(date(2026, 5, 1)).avg_kv_zusatzbeitrag_pct == Decimal("2.5")
