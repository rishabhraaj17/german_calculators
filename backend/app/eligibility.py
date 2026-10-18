"""Entitlement check per § 1 BEEG (including the income cap, § 1 Abs. 8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from . import params as P
from .fmt import eur


class Status(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    CONDITIONAL = "conditional"  # depends on something the user must verify


class Aufenthalt(str, Enum):
    """§ 1 Abs. 7 BEEG categories (simplified selection)."""

    DE_EU_EEA_CH = "de_eu_eea_ch"  # German or freizügigkeitsberechtigt (EU/EEA/CH)
    NIEDERLASSUNG = "niederlassung"  # Niederlassungserlaubnis / Daueraufenthalt-EU (Nr. 1)
    BLAUE_KARTE_ICT = "blaue_karte_ict"  # Blaue Karte EU, ICT-/Mobiler-ICT-Karte (Nr. 2)
    AE_ERWERB = "ae_erwerb"  # other residence permit allowing work for >= 6 months, not excluded (Nr. 2)
    AE_AUSBILDUNG_SAISON = "ae_ausbildung_saison"  # §§ 16e, 19c (au pair/seasonal), 19e, 20a V 1 (Nr. 2 a)
    AE_STUDIUM_SUCHE = "ae_studium_suche"  # §§ 16b, 16d, 20, 20a V 2 AufenthG (Nr. 2 b)
    AE_HUMANITAER = "ae_humanitaer"  # § 23 I (war), § 23a, § 25 III-V AufenthG (Nr. 2 c, 3, 4)
    BESCHAEFTIGUNGSDULDUNG = "beschaeftigungsduldung"  # § 60d AufenthG (Nr. 5)
    SONSTIGE = "sonstige"  # e.g. visa, Duldung, Gestattung


@dataclass(frozen=True)
class Grundvoraussetzungen:
    wohnsitz_in_deutschland: bool  # § 1 Abs. 1 Nr. 1
    entsendung_oder_ausnahme: bool  # § 1 Abs. 2 (e.g. posted abroad under German social insurance)
    lebt_mit_kind_im_haushalt: bool  # Nr. 2
    betreut_kind_selbst: bool  # Nr. 3
    wochenstunden_waehrend_bezug: Decimal  # Nr. 4 / Abs. 6: max 32 h monthly average
    in_berufsausbildung: bool = False  # Abs. 6 Nr. 2
    aufenthalt: Aufenthalt = Aufenthalt.DE_EU_EEA_CH
    erwerbstaetig_oder_elternzeit_oder_alg1: bool = False
    aufenthalt_seit_monaten: int = 0


@dataclass
class Check:
    id: str
    title: str
    status: Status
    explanation: str
    legal_basis: str


@dataclass
class Eligibility:
    checks: list[Check] = field(default_factory=list)

    @property
    def overall(self) -> Status:
        states = {c.status for c in self.checks}
        if Status.NOT_MET in states:
            return Status.NOT_MET
        if Status.CONDITIONAL in states:
            return Status.CONDITIONAL
        return Status.MET


_TITLE_RESIDENCE = "Nationality / residence permit"


def check_residence_permit(g: Grundvoraussetzungen) -> Check:
    a, basis = g.aufenthalt, "§ 1 Abs. 7 BEEG"
    ok = Status.MET
    if a in (Aufenthalt.DE_EU_EEA_CH, Aufenthalt.NIEDERLASSUNG, Aufenthalt.BLAUE_KARTE_ICT, Aufenthalt.AE_ERWERB):
        return Check("residence", _TITLE_RESIDENCE, ok, "This status qualifies for Elterngeld.", basis)
    if a == Aufenthalt.BESCHAEFTIGUNGSDULDUNG:
        return Check("residence", _TITLE_RESIDENCE, ok, "A Beschäftigungsduldung (§ 60d AufenthG) qualifies.",
                     basis + " Satz 1 Nr. 5")
    if a == Aufenthalt.AE_AUSBILDUNG_SAISON:
        return Check("residence", _TITLE_RESIDENCE, Status.NOT_MET,
                     "Permits for vocational training, au pair, seasonal work, voluntary service or job search "
                     "under § 20a Abs. 5 Satz 1 AufenthG are excluded.", basis + " Satz 1 Nr. 2 Buchst. a")
    if a == Aufenthalt.AE_STUDIUM_SUCHE:
        if g.erwerbstaetig_oder_elternzeit_oder_alg1:
            return Check("residence", _TITLE_RESIDENCE, ok,
                         "Study/job-search permit qualifies because you work, take Elternzeit or receive "
                         "unemployment benefit (SGB III).", basis + " Satz 1 Nr. 2 Buchst. b")
        return Check("residence", _TITLE_RESIDENCE, Status.NOT_MET,
                     "A study/job-search permit only qualifies while you work, take Elternzeit or receive "
                     "unemployment benefit (SGB III).", basis + " Satz 1 Nr. 2 Buchst. b")
    if a == Aufenthalt.AE_HUMANITAER:
        if g.erwerbstaetig_oder_elternzeit_oder_alg1 or g.aufenthalt_seit_monaten >= 15:
            return Check("residence", _TITLE_RESIDENCE, ok,
                         "Humanitarian permit qualifies (working/Elternzeit/SGB III benefits, or >= 15 months "
                         "of permitted stay).", basis + " Satz 1 Nr. 3, 4")
        return Check("residence", _TITLE_RESIDENCE, Status.NOT_MET,
                     "Humanitarian permit qualifies only when working/on Elternzeit/receiving SGB III benefits, "
                     "or after 15 months of permitted, tolerated or authorised stay.", basis + " Satz 1 Nr. 3, 4")
    return Check("residence", _TITLE_RESIDENCE, Status.NOT_MET,
                 "Without one of the titles listed in § 1 Abs. 7 there is no entitlement.", basis)


def check_basics(g: Grundvoraussetzungen) -> list[Check]:
    def simple(id_: str, title: str, ok: bool, fail: str, basis: str) -> Check:
        return Check(id_, title, Status.MET if ok else Status.NOT_MET, "Met." if ok else fail, basis)

    hours_ok = g.in_berufsausbildung or g.wochenstunden_waehrend_bezug <= P.MAX_HOURS_PER_WEEK
    return [
        simple("residence_de", "Residence (Wohnsitz) in Germany", g.wohnsitz_in_deutschland or g.entsendung_oder_ausnahme,
               "Without residence in Germany only in exceptional cases (e.g. posted abroad).",
               "§ 1 Abs. 1 Nr. 1, Abs. 2 BEEG"),
        simple("household", "Lives with the child in one household", g.lebt_mit_kind_im_haushalt,
               "Requirement not met.", "§ 1 Abs. 1 Nr. 2 BEEG"),
        simple("care", "Cares for and raises the child personally", g.betreut_kind_selbst,
               "Requirement not met.", "§ 1 Abs. 1 Nr. 3 BEEG"),
        simple("hours", "Not working full-time (max. 32 h/week, monthly average)", hours_ok,
               f"{g.wochenstunden_waehrend_bezug} h/week exceed the 32 h limit. Reduce to at most 32 h in "
               "the months you receive Elterngeld.", "§ 1 Abs. 1 Nr. 4, Abs. 6 BEEG"),
        check_residence_permit(g),
    ]


def check_income_cap(zve_total: Decimal, from_tax_assessment: bool) -> Check:
    """§ 1 Abs. 8 BEEG."""
    cap = P.INCOME_CAP_ZVE
    margin = abs(zve_total - cap)
    if zve_total > cap:
        status, text = Status.NOT_MET, f"zvE {eur(zve_total)} is {eur(margin)} above the {eur(cap)} cap."
    else:
        status, text = Status.MET, f"zvE {eur(zve_total)} is {eur(margin)} below the {eur(cap)} cap."
    if not from_tax_assessment and margin <= cap * Decimal("0.05"):
        status = Status.CONDITIONAL
        text += " This is an estimate within 5 % of the cap – confirm with your Steuerbescheid."
    return Check("income_cap", "Income cap (zu versteuerndes Einkommen, year before birth)", status, text,
                 "§ 1 Abs. 8 BEEG; Richtlinien zum BEEG 1.8")
