# Research notes (as of 18.10.2026)

Primary sources used (all downloaded and read; no secondary sources for rules):

- **BEEG**, full text from gesetze-im-internet.de, as last amended by Art. 19 Abs. 2 G v. 22.12.2025
- **Richtlinien zum BEEG**, BMBFSFJ, version 07/2026
- **EStG**, gesetze-im-internet.de, as last amended by Art. 7 G v. 29.6.2026
- **BMF Programmablaufplan** XML pseudocode 2025 and 2026 (bmf-steuerrechner.de)
- **Official Elterngeldrechner** source, gitlab.opencode.de/digitalservicebund/elterngeldrechner (EUPL-1.2), commit 05e1176 of 07.10.2026
- BMG Bekanntmachung of the average Zusatzbeitragssatz 2026: 2,9 % (BAnz AT 10.11.2025 B7)
- BSG, 25.06.2009 – B 10 EG 3/08 R: switching Steuerklasse to raise Elterngeld is not an abuse of rights

## 1. Eligibility (§ 1 BEEG)

- Residence in Germany (or the exceptions in Abs. 2), living with the child in one household, caring for it personally, and not working full-time: **max. 32 h/week** on monthly average (Abs. 6). Vocational training is never full-time.
- Non-EU nationals: only with the titles in Abs. 7 (Niederlassungserlaubnis, Blue Card, ICT, other work-authorising permits of ≥ 6 months). Study and job-search permits only while working, on Elternzeit or receiving ALG I. Humanitarian titles only when working, or after 15 months of stay.
- **Income cap (Abs. 8, § 28 Abs. 5):** births from 01.04.2025: zvE **> 175.000 €** excludes the claim. This applies to single parents and to couples, where both zvE are summed if the other person also lives with the child (married or not). Births 01.04.2024–31.03.2025: 200.000 €.
  - zvE per § 2 Abs. 5 EStG, **always reduced by the Freibeträge für Kinder**. Capital income taxed only by Abgeltungsteuer is ignored. EU/EEA/CH income counts (Richtlinien 1.8).
  - The year is **always the calendar year before birth**; it never shifts back. Without a Steuerbescheid the office decides provisionally (§ 8 Abs. 2).

## 2. Amount

- Elterngeld-Netto (§§ 2c–2f): average monthly regular gross pay over the Bemessungszeitraum, **without sonstige Bezüge** (bonuses, 13th salary). Then subtract:
  - 1/12 of the Arbeitnehmer-Pauschbetrag (1.230 € → 102,50 €)
  - Lohnsteuer + Soli + 8 % church tax per the **PAP valid on 1 January of the year before birth**, with the Steuerklasse/Faktor of the payslips
    - Kinderfreibeträge only affect Soli and church tax (§ 2e Abs. 4–6)
    - Vorsorgepauschale parts a–c and e, never d (private KV); no childless surcharge, no Saxony rate
    - KV-Zusatzbeitrag = the BMG average for that year
  - Flat social contributions: 9 % KV/PV (only if compulsorily insured in the GKV), 10 % RV, 2 % ALV.
- Replacement rate (§ 2 Abs. 2): 67 %. Below 1.000 € it rises by 0,1 pp per 2 € (up to 100 %); above 1.200 € it falls by 0,1 pp per 2 €, down to 65 % from 1.240 €. Min 300 €, max 1.800 €. With income after birth: rate × (min(pre, 2.770 €) − post).
- ElterngeldPlus (§ 4a): at most half of Basis without income. Min 150 €; bonuses and the multiples supplement are halved.
- Geschwisterbonus (§ 2a): +10 %, min 75 €, with 1 sibling < 3, or 2 siblings < 6, or a disabled sibling < 14. It ends after the Lebensmonat in which the condition lapses.
- Bemessungszeitraum (§ 2b): the 12 months before the birth month. Months with Mutterschutz, Elterngeld for an older child (first 14 months) or pregnancy-related illness are skipped – unless the parent applies to keep them (§ 2b Abs. 1 Satz 3).
- Steuerklasse (§ 2c Abs. 3, Richtlinien 2c.3.2): the class on the last payslip applies, unless another class applied "in der überwiegenden Zahl der Kalendermonate" – a **majority**, more than 6 of 12. Ties go to the last payslip. A birth in an earlier month than expected moves the Bemessungszeitraum back, so the tool also gives a safe deadline one month earlier. A change takes effect from the month after filing (§ 39 Abs. 6 EStG), and filing for the current year is possible until 30.11.

## 3. Duration (§§ 4–4c)

12 Basis months + 2 Partnermonate if both parents claim (or single-parent § 4c) **and** a parent's earned income drops in 2 Lebensmonate (§ 4 Abs. 3 Satz 2) – without any earned income before birth there are no Partnermonate. Each parent takes at least 2 months and at most 12 (§ 4c: 14). 1 Basis = 2 Plus. Partnerschaftsbonus: 2–4 extra Plus months each, simultaneously, while both work 24–32 h. The Mutterschaftsgeld months of the birthing parent count as Basis months (§ 4 Abs. 4 Satz 3).

## 4. Levers if the cap is exceeded (only lawful ones)

While the cap year is still running:
- bAV salary conversion: up to 8 % of the RV ceiling is tax-free (§ 3 Nr. 63 EStG): 8.112 € in 2026
- Basisrente up to the Altersvorsorge cap: 30.826 € in 2026, minus RV contributions incl. the employer share (§ 10 Abs. 3)
- Deferring one-off payments to January (§ 38a Abs. 1 Satz 3)
- Genuine Werbungskosten (home office 6 €/day, max. 1.260 €)
- Donations (≤ 20 %)
- For the self-employed: timing and the Investitionsabzugsbetrag (§ 7g)

After the year has ended, only the tax return (and an Einspruch within one month, § 355 AO) can change the zvE. Elternzeit remains available regardless (§ 15).

Levers that look like they reduce the zvE but do not: Handwerker and household services (§ 35a reduces the tax, not the zvE), and choosing separate vs. joint assessment (the sum is what counts).

## 5. Status of reform discussions

- Steuerklassen III/V: abolition was dropped from the final Steuerfortentwicklungsgesetz. The EStG in force still contains them.
- No further change to the income cap or the 300/1.800 € amounts was found in the statute in force (18.10.2026).
