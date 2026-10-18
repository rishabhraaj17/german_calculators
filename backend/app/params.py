"""Legal parameters. Every value carries its legal source.

Scope: births from 2026-01-01 to 2027-12-31. For these, § 2e BEEG requires the
Lohnsteuer PAP of 2025 resp. 2026 (year before birth), both bundled verbatim.
Earlier births fall under transitional law (§ 28 BEEG) and older PAPs and are
deliberately rejected instead of being approximated.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

SUPPORTED_BIRTH_FROM = date(2026, 1, 1)
SUPPORTED_BIRTH_TO = date(2027, 12, 31)

# --- BEEG (as amended by Art. 19 Abs. 2 G v. 22.12.2025) ---------------------
INCOME_CAP_ZVE = D(175_000)  # § 1 Abs. 8 BEEG, births from 2025-04-01 (§ 28 Abs. 5)
ELTERNGELD_MIN = D(300)  # § 2 Abs. 4
ELTERNGELD_MAX = D(1800)  # § 2 Abs. 1 Satz 2
NETTO_CAP_FOR_DIFFERENCE = D(2770)  # § 2 Abs. 3 Satz 2
GESCHWISTERBONUS_RATE = D("0.10")  # § 2a Abs. 1
GESCHWISTERBONUS_MIN = D(75)  # § 2a Abs. 1 (halved for Plus, § 4a Abs. 2)
MEHRLINGSZUSCHLAG = D(300)  # § 2a Abs. 4 (halved for Plus)
MAX_HOURS_PER_WEEK = 32  # § 1 Abs. 6 Nr. 1
BONUS_HOURS_MIN, BONUS_HOURS_MAX = 24, 32  # § 4b Abs. 1
SV_RATE_KV_PV = D("0.09")  # § 2f Abs. 1 Nr. 1
SV_RATE_RV = D("0.10")  # § 2f Abs. 1 Nr. 2
SV_RATE_ALV = D("0.02")  # § 2f Abs. 1 Nr. 3
KIRCHENSTEUER_RATE = D("0.08")  # § 2e Abs. 5

# Mini-/Midijob parameters. The official BMFSFJ Elterngeldrechner deliberately
# pins these to their 2024-01-01 values (see its brutto-netto-rechner.ts,
# FIXED_ZEITPUNKT_FOR_HISTORIC_PARAMETERS). We mirror that for parity and flag
# results in this income range as approximations.
GERINGFUEGIGKEITSGRENZE = D(538)
UEBERGANGSBEREICH_OBERGRENZE = D(2000)
UEBERGANGSBEREICH_F_FAKTOR = D("0.6667")


@dataclass(frozen=True)
class TaxYear:
    """Parameters of one tax (= PAP) year. Sources: EStG, PAP XML, BAnz."""

    year: int
    arbeitnehmer_pauschbetrag: D  # § 9a Satz 1 Nr. 1a EStG
    avg_kv_zusatzbeitrag_pct: D  # § 242a SGB V, BMG announcement (BAnz)
    kinderfreibetrag_per_parent: D  # § 32 Abs. 6 Satz 1 EStG (sächl. Existenzminimum)
    bea_freibetrag_per_parent: D  # § 32 Abs. 6 Satz 1 EStG (Betreuung/Erziehung/Ausbildung)
    altersvorsorge_hoechstbetrag: D  # § 10 Abs. 3 EStG (knappschaftl. RV Höchstbeitrag)
    bbg_rv: D  # Beitragsbemessungsgrenze allg. RV (as used in the PAP: BBGRV / BBGRVALV)
    rv_rate_total: D  # allg. RV Beitragssatz (AN + AG), PAP RVSATZAN * 2
    bbg_kv: D  # Beitragsbemessungsgrenze KV/PV (PAP BBGKVPV)


TAX_YEARS: dict[int, TaxYear] = {
    2025: TaxYear(
        year=2025,
        arbeitnehmer_pauschbetrag=D(1230),
        avg_kv_zusatzbeitrag_pct=D("2.5"),  # BMG Bekanntmachung for 2025 (also used by official calculator)
        kinderfreibetrag_per_parent=D(3336),  # PAP 2025: KFB 9600 = 2 * (3336 + 1464)
        bea_freibetrag_per_parent=D(1464),
        altersvorsorge_hoechstbetrag=D(29344),  # 24.7% * 118 800 (knappschaftl. BBG 2025)
        bbg_rv=D(96600),  # PAP 2025 BBGRV
        rv_rate_total=D("0.186"),  # PAP 2025 RVSATZAN 0.093
        bbg_kv=D(66150),  # PAP 2025 BBGKVPV
    ),
    2026: TaxYear(
        year=2026,
        arbeitnehmer_pauschbetrag=D(1230),
        # BMG Bekanntmachung v. 7.11.2025, BAnz AT 10.11.2025 B7: 2.9 %.
        # NOTE: the official calculator (commit 05e1176) still uses 2.5 % here.
        avg_kv_zusatzbeitrag_pct=D("2.9"),
        kinderfreibetrag_per_parent=D(3414),  # § 32 Abs. 6 EStG; PAP 2026: KFB 9756
        bea_freibetrag_per_parent=D(1464),
        altersvorsorge_hoechstbetrag=D(30826),  # 24.7% * 124 800 (knappschaftl. BBG 2026)
        bbg_rv=D(101400),  # PAP 2026 BBGRVALV
        rv_rate_total=D("0.186"),  # PAP 2026 RVSATZAN 0.093
        bbg_kv=D(69750),  # PAP 2026 BBGKVPV
    ),
}

# zvE estimation (EStG) -------------------------------------------------------
SONDERAUSGABEN_PAUSCHBETRAG = D(36)  # § 10c EStG (doubled for joint assessment)
KV_KRANKENGELD_ABSCHLAG = D("0.04")  # § 10 Abs. 1 Nr. 3a Satz 4 EStG
SONSTIGE_VORSORGE_CAP_EMPLOYEE = D(1900)  # § 10 Abs. 4 Satz 2 EStG
SONSTIGE_VORSORGE_CAP_SELF_PAID = D(2800)  # § 10 Abs. 4 Satz 1 EStG
KINDERBETREUUNG_RATE = D("0.80")  # § 10 Abs. 1 Nr. 5 EStG (from 2025)
KINDERBETREUUNG_MAX_PER_CHILD = D(4800)
SPENDEN_MAX_SHARE = D("0.20")  # § 10b Abs. 1 Nr. 1 EStG
HOMEOFFICE_PER_DAY, HOMEOFFICE_MAX = D(6), D(1260)  # § 4 Abs. 5 Satz 1 Nr. 6c EStG
BAV_TAX_FREE_SHARE_OF_BBG = D("0.08")  # § 3 Nr. 63 EStG
BAV_SV_FREE_SHARE_OF_BBG = D("0.04")  # § 1 Abs. 1 Satz 1 Nr. 9 SvEV (social-insurance free part)

# Employee contribution rates for the *quick* zvE estimate from monthly gross
# (only used when no Lohnsteuerbescheinigung figures are entered).
KV_AN_GENERAL_RATE = D("0.073")  # § 241 SGB V: 14.6 % / 2 (+ half the Zusatzbeitrag)
PV_AN_RATE = D("0.018")  # PAP PVSATZAN (without childless surcharge)
ALV_AN_RATE = D("0.013")  # PAP 2026 AVSATZAN (2.6 % / 2)


def tax_year_for_birth(birth: date) -> TaxYear:
    """§ 2e Abs. 1 / § 1 Abs. 8 BEEG: the calendar year before birth."""
    if not (SUPPORTED_BIRTH_FROM <= birth <= SUPPORTED_BIRTH_TO):
        raise ValueError(
            f"Birth date {birth.isoformat()} is outside the supported range "
            f"{SUPPORTED_BIRTH_FROM.isoformat()} – {SUPPORTED_BIRTH_TO.isoformat()}."
        )
    return TAX_YEARS[birth.year - 1]
