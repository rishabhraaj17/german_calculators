"""Mutterschutz periods and Mutterschaftsgeld.

* Schutzfristen: 6 weeks before the expected date (shortened/extended by the
  actual birth), 8 weeks after (12 for premature/multiple births or disability),
  extended after an early birth by the days lost before birth (§ 3 MuSchG).
* Statutory insured (GKV member): Mutterschaftsgeld of the Krankenkasse = net
  pay per calendar day, max. 13 EUR (§ 24i SGB V, § 19 Abs. 1 MuSchG), plus the
  employer top-up for the part above 13 EUR (§ 20 MuSchG). Paid for the
  Schutzfristen and the day of birth.
* Not a GKV member (e.g. privately insured): max. 210 EUR in total from the
  Bundesamt für Soziale Sicherung (§ 19 Abs. 2 MuSchG) plus the employer top-up.
* Net pay per calendar day: net pay of the last 3 settled months / 90 for a
  fixed monthly salary (health insurers' practice), one-off payments excluded
  (§ 21 Abs. 2 Nr. 1 MuSchG).
* Against Elterngeld, Mutterschaftsgeld and employer top-up from the day of
  birth are credited – except the 210 EUR of the BAS (§ 3 Abs. 1 Nr. 1 BEEG).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from . import params as P
from .elterngeld import ZERO, Erwerbsart, Steuerklasse, cent
from .pap.interpreter import SUPPORTED_YEARS, load_pap

MG_MAX_PER_DAY = Decimal(13)  # § 24i Abs. 2 Satz 2 SGB V
BAS_MAX_TOTAL = Decimal(210)  # § 19 Abs. 2 MuSchG
CHURCH_RATE_ACTUAL = Decimal("0.09")  # 9 % in 14 Länder (8 % in Bavaria and Baden-Württemberg)
PV_CHILDLESS_SURCHARGE = Decimal("0.006")  # § 55 Abs. 3 SGB XI
PV_REDUCTION_PER_CHILD = Decimal("0.0025")  # § 55 Abs. 3a SGB XI (2nd to 5th child under 25)
_STKL = {"I": 1, "II": 2, "III": 3, "IV": 4, "IV_FAKTOR": 4, "V": 5, "VI": 6}


@dataclass(frozen=True)
class Schutzfristen:
    start: date  # first day of the Schutzfrist before birth
    birth: date
    end: date  # last day of the Schutzfrist after birth
    days_before: int
    days_after: int
    extension_days: int  # extension after an early birth (§ 3 Abs. 2 Satz 3 MuSchG)
    weeks_after: int

    @property
    def total_days(self) -> int:
        return self.days_before + 1 + self.days_after  # + day of birth


def schutzfristen(due: date, birth: date, weeks_after: int) -> Schutzfristen:
    start = due - timedelta(weeks=6)
    days_before = max((birth - start).days, 0)
    extension = max((due - birth).days, 0) if birth < due else 0
    extension = min(extension, 42)  # at most the 6 weeks that were lost
    days_after = weeks_after * 7 + extension
    return Schutzfristen(start=min(start, birth), birth=birth, end=birth + timedelta(days=days_after),
                         days_before=days_before, days_after=days_after, extension_days=extension,
                         weeks_after=weeks_after)


@dataclass(frozen=True)
class Mutterschaftsgeld:
    fristen: Schutzfristen
    status: str  # "gkv" | "privat" | "beamtin" | "none"
    net_monthly: Decimal
    net_source: str  # "input" | "estimate"
    daily_net: Decimal
    kk_per_day: Decimal  # Krankenkasse (GKV) per calendar day
    employer_per_day: Decimal  # employer top-up per calendar day
    bas_total: Decimal  # one-off from the Bundesamt für Soziale Sicherung
    credited_per_day: Decimal  # amount per day credited against Elterngeld (§ 3 BEEG)

    @property
    def paid_per_day(self) -> Decimal:
        return self.kk_per_day + self.employer_per_day

    def amount_for_days(self, days: int) -> Decimal:
        return cent(self.paid_per_day * days)

    @property
    def before_birth(self) -> Decimal:
        return self.amount_for_days(self.fristen.days_before)

    @property
    def from_birth(self) -> Decimal:
        return self.amount_for_days(1 + self.fristen.days_after)

    @property
    def total(self) -> Decimal:
        return cent(self.before_birth + self.from_birth + self.bas_total)


def _pap_inputs(*, erwerbsart: Erwerbsart, steuerklasse: Steuerklasse, faktor: Decimal, kirchensteuer: bool,
                kinderfreibetraege: Decimal, kv_art: str, children_under_25: int, ty: P.TaxYear) -> dict:
    childless = children_under_25 == 0
    return {
        "af": 1 if steuerklasse == Steuerklasse.IV_FAKTOR else 0,
        "f": float(faktor) if steuerklasse == Steuerklasse.IV_FAKTOR else 1.0,
        "ALV": 0 if erwerbsart == Erwerbsart.ANGESTELLT else 1,
        "KRV": 1 if erwerbsart == Erwerbsart.BEAMT else 0,
        "KVZ": ty.avg_kv_zusatzbeitrag_pct,
        "PKV": 1 if kv_art == "privat" else 0, "PKPV": 0, "PKPVAGZ": 0,
        "PVA": 0 if childless else max(0, min(children_under_25, 5) - 1), "PVS": 0, "PVZ": 1 if childless else 0,
        "R": 1 if kirchensteuer else 0, "STKL": _STKL[steuerklasse.value], "ZKF": kinderfreibetraege,
    }


def _pap_year(year: int) -> int:
    return min(max(year, min(SUPPORTED_YEARS)), max(SUPPORTED_YEARS))


def estimate_net_monthly(
    gross: Decimal, *, erwerbsart: Erwerbsart, steuerklasse: Steuerklasse, faktor: Decimal, kirchensteuer: bool,
    kinderfreibetraege: Decimal, kv_art: str, children_under_25: int, year: int,
) -> Decimal:
    """Rough payslip net pay (real tax class and contributions, not the notional Elterngeld net)."""
    if gross <= 0:
        return ZERO
    pap_year = _pap_year(year)
    ty = P.TAX_YEARS[pap_year]
    childless = children_under_25 == 0
    pva = max(0, min(children_under_25, 5) - 1)
    pap = load_pap(pap_year)
    inputs = _pap_inputs(erwerbsart=erwerbsart, steuerklasse=steuerklasse, faktor=faktor, kirchensteuer=kirchensteuer,
                         kinderfreibetraege=kinderfreibetraege, kv_art=kv_art, children_under_25=children_under_25, ty=ty)
    inputs.update(LZZ=2, RE4=int(cent(gross) * 100))
    out = pap.run(**{k: v for k, v in inputs.items() if k in pap.inputs})
    tax = (Decimal(out["LSTLZZ"]) + Decimal(out["SOLZLZZ"])) / 100 + cent(Decimal(out["BK"]) / 100 * CHURCH_RATE_ACTUAL)
    sv = ZERO
    if erwerbsart == Erwerbsart.ANGESTELLT:
        rv_base = min(gross, ty.bbg_rv / 12)
        sv += rv_base * (ty.rv_rate_total / 2) + rv_base * P.ALV_AN_RATE
        if kv_art in ("gkv_pflicht", "gkv_freiwillig"):
            kv_base = min(gross, ty.bbg_kv / 12)
            pv_rate = P.PV_AN_RATE + (PV_CHILDLESS_SURCHARGE if childless else -PV_REDUCTION_PER_CHILD * pva)
            sv += kv_base * (P.KV_AN_GENERAL_RATE + ty.avg_kv_zusatzbeitrag_pct / 200) + kv_base * pv_rate
    return cent(max(gross - tax - sv, ZERO))


def one_off_withholding(
    amount: Decimal, annual_regular: Decimal, *, erwerbsart: Erwerbsart, steuerklasse: Steuerklasse, faktor: Decimal,
    kirchensteuer: bool, kinderfreibetraege: Decimal, kv_art: str, children_under_25: int, year: int,
) -> Decimal:
    """Lohnsteuer, Soli and church tax withheld on a one-off payment (sonstiger Bezug, § 39b Abs. 3 EStG):
    the PAP taxes it on top of the expected regular annual wage, in the payee's tax class."""
    if amount <= 0:
        return ZERO
    pap_year = _pap_year(year)
    pap = load_pap(pap_year)
    inputs = _pap_inputs(erwerbsart=erwerbsart, steuerklasse=steuerklasse, faktor=faktor, kirchensteuer=kirchensteuer,
                         kinderfreibetraege=kinderfreibetraege, kv_art=kv_art, children_under_25=children_under_25,
                         ty=P.TAX_YEARS[pap_year])
    regular = int(cent(annual_regular) * 100)
    inputs.update(LZZ=1, RE4=regular, JRE4=regular, SONSTB=int(cent(amount) * 100))
    out = pap.run(**{k: v for k, v in inputs.items() if k in pap.inputs})
    return cent((Decimal(out["STS"]) + Decimal(out["SOLZS"])) / 100 + Decimal(out["BKS"]) / 100 * CHURCH_RATE_ACTUAL)


def mutterschaftsgeld(
    *, due: date, birth: date, weeks_after: int, erwerbsart: Erwerbsart, kv_art: str,
    net_monthly: Decimal, net_source: str,
) -> Mutterschaftsgeld:
    fristen = schutzfristen(due, birth, weeks_after)
    daily = cent(net_monthly * 3 / 90)
    if erwerbsart == Erwerbsart.BEAMT:
        # civil servants keep their pay during the Schutzfristen (Mutterschutzverordnung of Bund/Länder)
        return Mutterschaftsgeld(fristen, "beamtin", net_monthly, net_source, daily, ZERO, daily, ZERO, daily)
    if erwerbsart == Erwerbsart.KEINE:
        return Mutterschaftsgeld(fristen, "none", ZERO, net_source, ZERO, ZERO, ZERO, ZERO, ZERO)
    gkv_member = kv_art in ("gkv_pflicht", "gkv_freiwillig") and erwerbsart == Erwerbsart.ANGESTELLT
    employer = max(daily - MG_MAX_PER_DAY, ZERO)
    if gkv_member:
        kk = min(daily, MG_MAX_PER_DAY)
        return Mutterschaftsgeld(fristen, "gkv", net_monthly, net_source, daily, kk, employer, ZERO, kk + employer)
    bas = min(BAS_MAX_TOTAL, cent(min(daily, MG_MAX_PER_DAY) * fristen.total_days))
    # the BAS one-off is not credited against Elterngeld; the employer top-up is
    return Mutterschaftsgeld(fristen, "privat", net_monthly, net_source, daily, ZERO, employer, bas, employer)
