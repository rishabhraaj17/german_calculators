/**
 * Generates golden test vectors by running the OFFICIAL Elterngeldrechner
 * source code of the BMFSFJ / DigitalService
 * (https://gitlab.opencode.de/digitalservicebund/elterngeldrechner, EUPL-1.2).
 *
 * The Python engine in /backend must reproduce these numbers to the cent.
 * Run via tools/golden/run.sh (inside a node:24 container).
 */
import { berechneLohnsteuer } from "/official/src/lohnsteuerrechner/berechneLohnsteuer.ts";
import {
  abzuege,
  nettoEinkommenZwischenErgebnis,
} from "/official/src/elterngeldrechner/brutto-netto-rechner/brutto-netto-rechner.ts";
import { elterngeldZwischenergebnis } from "/official/src/elterngeldrechner/eg-zwischen-ergebnis-algorithmus.ts";
import {
  berechneBasiselterngeld,
  berechneElterngeldPlus,
} from "/official/src/elterngeldrechner/Einkommensersatzleistung.ts";
import { bestimmeWerbekostenpauschale } from "/official/src/elterngeldrechner/Werbekostenpauschale.ts";
import { aufDenCentRunden } from "/official/src/elterngeldrechner/common/math-util.ts";
import {
  Einkommen,
  ErwerbsArt,
  Geburtstag,
  KassenArt,
  RentenArt,
  Steuerklasse,
} from "/official/src/elterngeldrechner/model/index.ts";

// Deterministic PRNG (mulberry32) so the vectors are reproducible.
let seed = 20261018;
function rand(): number {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
const pick = <T>(xs: readonly T[]): T => xs[Math.floor(rand() * xs.length)]!;
const euros = (max: number) => Math.round(rand() * max * 100) / 100;

// --- 1. Raw Lohnsteuer PAP vectors -----------------------------------------
const pap: unknown[] = [];
for (let i = 0; i < 4000; i++) {
  const year = pick([2025, 2026] as const);
  const STKL = pick([1, 2, 3, 4, 5, 6] as const);
  const AF = STKL === 4 && rand() < 0.3 ? 1 : 0;
  const input = {
    AF,
    F: AF ? pick([0.789, 0.85, 0.912, 0.95, 1.0]) : 0,
    ALV: pick([0, 1] as const),
    KRV: pick([0, 1] as const),
    KVZ: pick([1.7, 2.5, 2.9, 0]),
    LZZ: 2 as const,
    LZZFREIB: 0,
    LZZHINZU: 0,
    PKPV: 0,
    PKPVAGZ: 0,
    PKV: 0 as const,
    PVA: pick([0, 0, 1, 2]),
    PVS: pick([0, 0, 1] as const),
    PVZ: pick([0, 1] as const),
    R: pick([0, 1] as const),
    RE4: Math.round(euros(pick([1500, 6000, 15000, 40000])) * 100),
    STKL,
    VBEZ: 0,
    ZKF: pick([0, 0, 0.5, 1, 1.5, 2, 3]),
  };
  if (input.PVZ === 1) input.PVA = 0;
  const out = berechneLohnsteuer(year, input as never);
  pap.push({ year, input, output: { LSTLZZ: out.LSTLZZ, SOLZLZZ: out.SOLZLZZ, BK: out.BK } });
}

// --- 2. Elterngeld-Netto and amounts ----------------------------------------
const steuerklassen = [
  Steuerklasse.I,
  Steuerklasse.II,
  Steuerklasse.III,
  Steuerklasse.IV,
  Steuerklasse.IVMitFaktor,
  Steuerklasse.V,
  Steuerklasse.VI,
];
const erwerbsarten = [
  ErwerbsArt.JA_NICHT_SELBST_MIT_SOZI,
  ErwerbsArt.JA_NICHT_SELBST_MIT_SOZI,
  ErwerbsArt.JA_NICHT_SELBST_MIT_SOZI,
  ErwerbsArt.JA_NICHT_SELBST_OHNE_SOZI,
  ErwerbsArt.JA_NICHT_SELBST_MINI,
];
const eg: unknown[] = [];
for (let i = 0; i < 4000; i++) {
  const birth = pick([
    "2026-01-15",
    "2026-06-30",
    "2026-12-01",
    "2027-03-10",
    "2027-11-20",
  ]);
  const erwerbsArt = pick(erwerbsarten);
  const steuerklasse = pick(steuerklassen);
  const brutto =
    erwerbsArt === ErwerbsArt.JA_NICHT_SELBST_MINI
      ? euros(556)
      : euros(pick([1200, 2500, 6000, 12000]));
  const finanzDaten = {
    bruttoEinkommen: new Einkommen(brutto),
    istKirchensteuerpflichtig: rand() < 0.4,
    kinderFreiBetrag: pick([0, 0, 0.5, 1, 1.5, 2]),
    steuerklasse,
    kassenArt: pick([
      KassenArt.GESETZLICH_PFLICHTVERSICHERT,
      KassenArt.NICHT_GESETZLICH_PFLICHTVERSICHERT,
    ]),
    rentenVersicherung: pick([
      RentenArt.GESETZLICHE_RENTEN_VERSICHERUNG,
      RentenArt.KEINE_GESETZLICHE_RENTEN_VERSICHERUNG,
    ]),
    splittingFaktor:
      steuerklasse === Steuerklasse.IVMitFaktor ? pick([0.789, 0.9, 0.95]) : 1,
    mischEinkommenTaetigkeiten: [],
    erwerbsZeitraumLebensMonatList: [],
  };
  const geburtstag = new Geburtstag(birth);
  const persoenlicheDaten = {
    geburtstagDesKindes: geburtstag,
    anzahlKuenftigerKinder: 1,
    etVorGeburt: erwerbsArt,
  };
  const input = {
    birth,
    erwerbsArt,
    brutto,
    steuerklasse,
    faktor: finanzDaten.splittingFaktor,
    kirchensteuer: finanzDaten.istKirchensteuerpflichtig,
    kinderfreibetraege: finanzDaten.kinderFreiBetrag,
    kassenArt: finanzDaten.kassenArt,
    rentenArt: finanzDaten.rentenVersicherung,
    bruttoNach: rand() < 0.5 ? euros(pick([800, 2500, 5000])) : 0,
  };

  const netto = nettoEinkommenZwischenErgebnis(
    structuredCloneFinanz(finanzDaten),
    erwerbsArt,
    geburtstag,
  );
  const zw = elterngeldZwischenergebnis(persoenlicheDaten, netto);
  const wkp = bestimmeWerbekostenpauschale(geburtstag);
  const ekVor = Math.max(aufDenCentRunden(netto.value - wkp), 0);
  const output: Record<string, number> = {
    nettoVorGeburt: netto.value,
    elterngeldNetto: ekVor,
    basis: zw.elternGeld,
    ersatzrate: zw.ersatzRate,
    plus: berechneElterngeldPlus(ekVor),
  };
  if (input.bruttoNach > 0) {
    const abz =
      erwerbsArt === ErwerbsArt.JA_NICHT_SELBST_MINI
        ? 0
        : abzuege(
            input.bruttoNach,
            structuredCloneFinanz(finanzDaten),
            erwerbsArt,
            geburtstag,
          );
    const ekNach = Math.max(
      aufDenCentRunden(Math.max(input.bruttoNach - wkp, 0)) - abz,
      0,
    );
    output.elterngeldNettoNach = aufDenCentRunden(ekNach);
    output.basisMitEinkommen = berechneBasiselterngeld(ekVor, ekNach);
    output.plusMitEinkommen = berechneElterngeldPlus(ekVor, ekNach);
  }
  eg.push({ input, output });
}

function structuredCloneFinanz<T extends { bruttoEinkommen: Einkommen }>(f: T): T {
  return { ...f, bruttoEinkommen: new Einkommen(f.bruttoEinkommen.value) };
}

console.log(
  JSON.stringify(
    {
      source:
        "https://gitlab.opencode.de/digitalservicebund/elterngeldrechner (official BMFSFJ Elterngeldrechner)",
      commit: process.env.OFFICIAL_COMMIT ?? "unknown",
      pap,
      elterngeld: eg,
    },
    null,
    0,
  ),
);
