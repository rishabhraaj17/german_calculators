"""Request schema of the /api/analyse endpoint."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .eligibility import Aufenthalt
from .elterngeld import Erwerbsart, Steuerklasse

Money = Decimal
NonNegMoney = Annotated[Decimal, Field(ge=0, le=10_000_000)]
CalendarMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]  # "YYYY-MM"


class Sibling(BaseModel):
    birth_date: date
    disability: bool = False


class Basics(BaseModel):
    wohnsitz_in_deutschland: bool = True
    entsendung_oder_ausnahme: bool = False
    lebt_mit_kind_im_haushalt: bool = True
    betreut_kind_selbst: bool = True
    in_berufsausbildung: bool = False
    aufenthalt: Aufenthalt = Aufenthalt.DE_EU_EEA_CH
    erwerbstaetig_oder_elternzeit_oder_alg1: bool = True
    aufenthalt_seit_monaten: int = 0


class PlanIn(BaseModel):
    basis_months: int = Field(0, ge=0, le=16)
    plus_months: int = Field(0, ge=0, le=32)
    bonus_months: int = Field(0, ge=0, le=4)


class OneOffPayment(BaseModel):
    month: CalendarMonth
    amount: Money = Field(gt=0, le=10_000_000)


class ParentIn(BaseModel):
    label: str = Field("Parent A", max_length=40)
    birthing_parent: bool = False
    erwerbsart: Erwerbsart = Erwerbsart.ANGESTELLT
    monthly_gross: Money | None = Field(None, ge=0, le=100_000)
    monthly_gross_list: list[NonNegMoney] | None = None  # 12 months of the Bemessungszeitraum
    steuerklasse: Steuerklasse = Steuerklasse.IV
    faktor: Decimal = Field(Decimal(1), gt=0, le=1)
    kirchensteuer: bool = False
    kinderfreibetraege: Decimal = Field(Decimal(0), ge=0, le=10)
    kv_pflichtversichert: bool = True
    # Health insurance type; overrides kv_pflichtversichert when given. Decides who
    # pays Mutterschaftsgeld (§ 19 MuSchG) and the 9 % flat deduction (§ 2f BEEG).
    kv_art: Literal["gkv_pflicht", "gkv_freiwillig", "privat"] | None = None
    # Net pay per month from the payslip (regular pay) – for Mutterschaftsgeld; estimated if empty
    net_monthly: Money | None = Field(None, ge=0, le=100_000)
    vacation_days: int | None = Field(None, ge=0, le=60)  # annual leave entitlement
    private_premium: Money | None = Field(None, ge=0, le=10_000)  # private KV+PV premium per month
    rv_pflichtversichert: bool = True
    part_time_gross: Money | None = Field(None, ge=0, le=100_000)
    part_time_hours: Decimal = Field(Decimal(0), ge=0, le=60)
    # contractual weekly hours before birth; part-time gross is derived from it if not entered
    weekly_hours: Decimal = Field(Decimal(40), gt=0, le=60)
    part_time_in_basis: bool = False
    part_time_other_employer: bool = False  # § 17 Abs. 1 Satz 2 BEEG protects leave only with the same employer
    # One-off payments (sonstige Bezüge: 13th salary, holiday/Christmas pay, annual bonus).
    # Excluded from Elterngeld (§ 2c Abs. 1 Satz 2 BEEG) but part of the zvE for the income cap.
    bonuses_annual: Money = Field(Decimal(0), ge=0, le=10_000_000)  # in the calendar year before birth
    bonuses_pending: Money = Field(Decimal(0), ge=0, le=10_000_000)  # part of it not yet paid out
    # "one_off": sonstige Bezüge (annual bonus, 13th salary). "monthly": paid in equal parts with every
    # salary – then it is laufender Arbeitslohn and counts for Elterngeld like the monthly gross.
    bonus_payment: Literal["one_off", "monthly"] = "one_off"
    # One-off payments expected from the year of birth on (e.g. next year's annual bonus). They don't
    # count for Elterngeld but raise the income tax on Mutterschaftsgeld/Elterngeld (§ 32b EStG).
    future_one_offs: list[OneOffPayment] = Field(default_factory=list, max_length=12)
    # Employee salary conversion into a company pension (Direktversicherung, Pensionskasse,
    # Pensionsfonds) per month. `monthly_gross` is the gross BEFORE this conversion.
    bav_monthly: Money = Field(Decimal(0), ge=0, le=100_000)
    extra_excluded_months: list[CalendarMonth] = Field(default_factory=list, max_length=24)
    include_mutterschutz_months: bool = False  # § 2b Abs. 1 Satz 3 BEEG: keep them on request
    plan: PlanIn = PlanIn()
    basics: Basics = Basics()

    @model_validator(mode="after")
    def _gross(self) -> "ParentIn":
        if self.monthly_gross_list is not None and len(self.monthly_gross_list) != 12:
            raise ValueError("monthly_gross_list must contain exactly 12 months")
        if self.kv_art is not None:
            self.kv_pflichtversichert = self.kv_art == "gkv_pflicht"
        if self.bonuses_pending > self.bonuses_annual:
            raise ValueError("bonuses still to be paid cannot exceed the annual bonuses")
        if self.steuerklasse == Steuerklasse.VI:
            raise ValueError("Steuerklasse VI is disregarded for Elterngeld (§ 2e Abs. 3 BEEG); use the class of the main job")
        return self

    @property
    def part_time(self) -> tuple[Decimal | None, str]:
        """Part-time gross per month while on Elterngeld: entered, or pro rata from the hours."""
        if self.part_time_gross is not None:
            return self.part_time_gross, "input"
        if self.part_time_hours > 0 and self.average_gross > 0:
            gross = (self.average_gross * self.part_time_hours / self.weekly_hours).quantize(Decimal("0.01"))
            return gross, "hours"
        return None, "none"

    @property
    def average_gross(self) -> Decimal:
        """§ 2c Abs. 1 BEEG: monthly average over the 12 months (months without pay count as 0).
        A bonus paid with every salary is part of it; per-month lists are taken to include it."""
        if self.monthly_gross_list is not None:
            return sum(self.monthly_gross_list, Decimal(0)) / 12
        regular = self.bonuses_annual / 12 if self.bonus_payment == "monthly" else Decimal(0)
        return (self.monthly_gross or Decimal(0)) + regular

    @property
    def one_off_annual(self) -> Decimal:
        """Sonstige Bezüge: left out of Elterngeld (§ 2c Abs. 1 Satz 2 BEEG), part of the zvE."""
        return self.bonuses_annual if self.bonus_payment == "one_off" else Decimal(0)

    @property
    def one_off_pending(self) -> Decimal:
        return self.bonuses_pending if self.bonus_payment == "one_off" else Decimal(0)


class ZvEPersonIn(BaseModel):
    jahresbrutto: Money = Field(Decimal(0), ge=0)
    rv_arbeitnehmer: Money = Field(Decimal(0), ge=0)
    rv_arbeitgeber: Money = Field(Decimal(0), ge=0)
    kv_arbeitnehmer: Money = Field(Decimal(0), ge=0)
    pv_arbeitnehmer: Money = Field(Decimal(0), ge=0)
    alv_arbeitnehmer: Money = Field(Decimal(0), ge=0)
    krankengeldanspruch: bool = True
    private_kv_pv_basis: Money = Field(Decimal(0), ge=0)
    private_kv_ag_zuschuss: Money = Field(Decimal(0), ge=0)
    rv_frei_mit_versorgung: bool = False
    werbungskosten: Money | None = Field(None, ge=0)
    andere_einkuenfte: Money = Decimal(0)
    basisrente_beitraege: Money = Field(Decimal(0), ge=0)
    kirchensteuer_gezahlt: Money = Field(Decimal(0), ge=0)
    spenden: Money = Field(Decimal(0), ge=0)
    kinderbetreuungskosten: Money = Field(Decimal(0), ge=0)
    kinder_betreut: int = Field(0, ge=0, le=10)
    weitere_sonderausgaben: Money = Field(Decimal(0), ge=0)
    aussergewoehnliche_belastungen: Money = Field(Decimal(0), ge=0)
    # for the advisor (not part of the zvE itself)
    bav_existing: Money = Field(Decimal(0), ge=0)
    pending_one_off: Money = Field(Decimal(0), ge=0)


class PayslipPersonIn(BaseModel):
    """One payslip of the cap year: "this month" and "year to date" columns. The rest of the year is
    extrapolated with this month's values, so this month should be a regular one (no one-off payment)."""

    month: int = Field(ge=1, le=12)  # month of the payslip in the year before birth
    brutto_month: NonNegMoney = Decimal(0)  # Steuer-Brutto
    brutto_ytd: NonNegMoney = Decimal(0)
    rv_month: NonNegMoney = Decimal(0)  # employee shares
    rv_ytd: NonNegMoney = Decimal(0)
    alv_month: NonNegMoney = Decimal(0)
    alv_ytd: NonNegMoney = Decimal(0)
    kv_month: NonNegMoney = Decimal(0)  # own share: voluntary members net of the employer subsidy
    kv_ytd: NonNegMoney = Decimal(0)
    pv_month: NonNegMoney = Decimal(0)
    pv_ytd: NonNegMoney = Decimal(0)
    one_off_due: NonNegMoney = Decimal(0)  # one-off payments still to come until 31 Dec
    werbungskosten: Money | None = Field(None, ge=0)  # actual Werbungskosten for the year, if above the Pauschbetrag

    @model_validator(mode="after")
    def _ytd_covers_month(self) -> "PayslipPersonIn":
        for k in ("brutto", "rv", "alv", "kv", "pv"):
            if getattr(self, f"{k}_ytd") < getattr(self, f"{k}_month"):
                raise ValueError(f"{k}: the year-to-date value cannot be lower than this month's")
        return self


class ZvEIn(BaseModel):
    mode: Literal["bescheid", "estimate", "payslip"] = "estimate"
    bescheid_values: list[NonNegMoney] = Field(default_factory=list, max_length=2)  # zvE per person (or one joint value)
    # The Bescheid deducts the Freibeträge für Kinder only if they beat Kindergeld (§ 31 EStG);
    # for the income cap they are always deducted, so subtract them here if the Bescheid did not.
    bescheid_kfb_abgezogen: bool = True
    persons: list[ZvEPersonIn] = Field(default_factory=list, max_length=2)
    payslips: list[PayslipPersonIn] = Field(default_factory=list, max_length=2)  # mode "payslip", per parent
    zusammenveranlagung: bool = False
    kinderfreibetrag_zaehler: Decimal = Field(Decimal(0), ge=0, le=20)
    alleinerziehend: bool = False
    kinder_im_haushalt: int = Field(0, ge=0, le=20)


class AnalyseRequest(BaseModel):
    birth_date: date
    due_date: date | None = None
    household: Literal["single", "married", "partnership"] = "married"
    single_parent_4c: bool = False  # § 4c Abs. 1 Nr. 1 (Alleinerziehende) etc.
    children_expected: int = Field(1, ge=1, le=6)
    premature_or_disability: bool = False  # extends Mutterschutz to 12 weeks (§ 3 Abs. 2 MuSchG)
    siblings: list[Sibling] = Field(default_factory=list, max_length=15)
    parents: list[ParentIn] = Field(min_length=1, max_length=2)
    # Month plan: per parent one entry per Lebensmonat 1-36 (overrides ParentIn.plan counts)
    timeline: list[list[Literal["none", "basis", "plus", "plus_tz", "bonus", "ez"]]] | None = Field(None, max_length=2)
    # weekly working hours per parent and Lebensmonat (None = default for the month type)
    hours: list[list[Decimal | None]] | None = Field(None, max_length=2)
    kez_parent: int | None = Field(None, ge=0, le=1)  # who gets the Kindererziehungszeit (§ 56 SGB VI)
    zve: ZvEIn = ZvEIn()
    today: date | None = None
    _memo: dict = PrivateAttr(default_factory=dict)  # values the service derives once per request

    @model_validator(mode="after")
    def _consistency(self) -> "AnalyseRequest":
        if self.household == "single" and len(self.parents) != 1:
            raise ValueError("household 'single' needs exactly one parent")
        if self.household != "single" and len(self.parents) != 2:
            raise ValueError("couples need two parents")
        if sum(p.birthing_parent for p in self.parents) > 1:
            raise ValueError("only one birthing parent")
        if self.hours is not None:
            if len(self.hours) != len(self.parents) or any(len(h) > 36 for h in self.hours):
                raise ValueError("hours need one row (max. 36 months) per parent")
            if any(x is not None and not 0 <= x <= 60 for row in self.hours for x in row):
                raise ValueError("hours per week must be between 0 and 60")
        if self.timeline is not None:
            if len(self.timeline) != len(self.parents) or any(len(t) > 36 for t in self.timeline):
                raise ValueError("timeline needs one row (max. 36 months) per parent")
        for p in self.parents:
            if any(int(x.month[:4]) < self.birth_date.year for x in p.future_one_offs):
                raise ValueError(f"one-off payments before {self.birth_date.year} belong in the bonuses of the "
                                 "year before birth")
        return self
