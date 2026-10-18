"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const form = $("#form");
const fmt = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const fmt0 = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur = (v, cents = true) => (v === null || v === undefined ? "–" : (cents ? fmt : fmt0).format(Number(v)));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- dynamic form parts ------------------------------------------
function addParent(index, name, birthing) {
  const node = $("#tpl-parent").content.firstElementChild.cloneNode(true);
  node.dataset.index = index;
  $(".n", node).textContent = String(3 + index);
  $(".name", node).value = name;
  $("[name=birthing_parent]", node).checked = birthing;
  $("[name=steuerklasse]", node).addEventListener("change", (e) =>
    node.classList.toggle("has-faktor", e.target.value === "IV_FAKTOR"));
  $("[name=kv_art]", node).addEventListener("change", (e) => node.classList.toggle("is-private", e.target.value === "privat"));
  $("[name=aufenthalt]", node).addEventListener("change", (e) =>
    node.classList.toggle("show-permit", e.target.value === "ae_humanitaer"));
  $("[name=birthing_parent]", node).addEventListener("change", (e) => {
    if (e.target.checked) $$(".parent [name=birthing_parent]").forEach((c) => { if (c !== e.target) c.checked = false; });
  });
  $("#parents").append(node);
  const syncPartTime = () => {
    const gross = Number($("[name=monthly_gross]", node).value || 0);
    const hours = Number($("[name=part_time_hours]", node).value || 0);
    const full = Number($("[name=weekly_hours]", node).value || 40);
    $("[name=part_time_gross]", node).placeholder = gross && hours ? `≈ ${eur(gross * hours / full, false)} from the hours` : "from the hours";
  };
  ["monthly_gross", "part_time_hours", "weekly_hours"].forEach((n) => $(`[name=${n}]`, node).addEventListener("input", syncPartTime));
  node.syncPartTime = syncPartTime;

  const z = $("#tpl-zve-person").content.firstElementChild.cloneNode(true);
  z.dataset.index = index;
  $("h3", z).textContent = `${name} – Lohnsteuerbescheinigung of the year before birth`;
  $(".name", node).addEventListener("input", (e) => {
    $("h3", z).textContent = `${e.target.value || name} – Lohnsteuerbescheinigung of the year before birth`;
  });
  $("#zve-persons").append(z);
}
addParent(0, "Parent A", true);
addParent(1, "Parent B", false);

let currentTimeline = null; // month plan from the planner; null = default starting plan
let currentHours = null; // weekly hours per parent and month; null entries = default for the month type
let currentKez = null; // parent index credited with the Kindererziehungszeit (§ 56 SGB VI); null = default

function syncHousehold() {
  const h = form.household.value;
  document.body.classList.toggle("single", h === "single");
  document.body.classList.toggle("married", h === "married");
  const second = $$(".parent")[1];
  second.hidden = h === "single";
  $$(".zve-person")[1].hidden = h === "single";
  $("#n-cap").textContent = h === "single" ? "4" : "5";
}
function syncMode() {
  ["quick", "estimate", "bescheid"].forEach((m) => document.body.classList.toggle(`mode-${m}`, form.zve_mode.value === m));
}
form.addEventListener("change", (e) => {
  if (e.target.name === "household") { syncHousehold(); currentTimeline = null; currentHours = null; currentKez = null; }
  if (e.target.name === "zve_mode") syncMode();
});
function syncCapYear() {
  const year = Number((form.birth_date.value || "").slice(0, 4)) - 1;
  const ok = year >= 2025;
  $$(".cap-year").forEach((el) => { el.textContent = ok ? `for ${year}` : ""; });
  $("#cap-year-hint").textContent = ok
    ? `For this birth only the Steuerbescheid for ${year} counts. An assessment for ${year - 1} or earlier is not accepted, and if no ${year} assessment exists yet, Elterngeld is paid provisionally and reclaimed if the ${year} zvE exceeds the cap (§ 1 Abs. 8, § 8 Abs. 2 BEEG).`
    : "Use the Steuerbescheid of the calendar year before birth – an older one does not count (§ 1 Abs. 8 BEEG).";
}
form.birth_date.addEventListener("input", syncCapYear);
syncHousehold();
syncMode();
syncCapYear();

function addSibling(birthDate = "", disability = false) {
  const row = document.createElement("div");
  row.className = "sibling";
  row.innerHTML = `<label class="stacked"><span class="t">Birth date</span><input type="date" name="sibling_date" required></label>
    <label class="check"><input type="checkbox" name="sibling_disability"><span>Disability</span></label>
    <button type="button" class="link">Remove</button>`;
  $("[name=sibling_date]", row).value = birthDate;
  $("[name=sibling_disability]", row).checked = disability;
  $("button", row).addEventListener("click", () => row.remove());
  $("#siblings").append(row);
}
$("#add-sibling").addEventListener("click", () => addSibling());

// ---------- request -------------------------------------------------------
const num = (el) => (el && el.value !== "" ? Number(el.value) : null);

function parentPayload(node) {
  const v = (n) => $(`[name=${n}]`, node);
  return {
    label: v("label").value.trim() || "Parent",
    birthing_parent: v("birthing_parent").checked,
    erwerbsart: v("erwerbsart").value,
    monthly_gross: num(v("monthly_gross")) ?? 0,
    bonuses_annual: num(v("bonuses_annual")) ?? 0,
    bonuses_pending: num(v("bonuses_pending")) ?? 0,
    bav_monthly: num(v("bav_monthly")) ?? 0,
    steuerklasse: v("steuerklasse").value,
    faktor: num(v("faktor")) ?? 1,
    kirchensteuer: v("kirchensteuer").checked,
    kinderfreibetraege: num(v("kinderfreibetraege")) ?? 0,
    kv_art: v("kv_art").value,
    kv_pflichtversichert: v("kv_art").value === "gkv_pflicht",
    net_monthly: num(v("net_monthly")),
    vacation_days: num(v("vacation_days")),
    private_premium: num(v("private_premium")),
    part_time_gross: num(v("part_time_gross")),
    part_time_hours: num(v("part_time_hours")) ?? 0,
    weekly_hours: num(v("weekly_hours")) ?? 40,
    extra_excluded_months: v("extra_excluded_months").value.split(/[\s,;]+/).filter((s) => /^\d{4}-\d{2}$/.test(s)),
    // starting plan before the month planner is used: birthing parent 12 Basis, the other 2
    plan: { basis_months: v("birthing_parent").checked ? (form.single_parent_4c.checked ? 14 : 12) : 2 },
    basics: {
      wohnsitz_in_deutschland: v("wohnsitz").checked,
      lebt_mit_kind_im_haushalt: v("haushalt").checked,
      betreut_kind_selbst: v("haushalt").checked,
      aufenthalt: v("aufenthalt").value,
      erwerbstaetig_oder_elternzeit_oder_alg1: v("erwerbstaetig").checked,
      aufenthalt_seit_monaten: num(v("aufenthalt_seit_monaten")) ?? 0,
    },
  };
}

function zvePersonPayload(node) {
  const out = {};
  $$("input", node).forEach((i) => {
    if (i.type === "checkbox") out[i.name] = i.checked;
    else if (i.value !== "") out[i.name] = Number(i.value);
  });
  return out;
}

function buildRequest() {
  const single = form.household.value === "single";
  const parents = $$(".parent").filter((p) => !p.hidden).map(parentPayload);
  const mode = form.zve_mode.value;
  const zve = {
    mode: mode === "bescheid" ? "bescheid" : "estimate",
    zusammenveranlagung: form.zusammenveranlagung.value === "joint",
    kinderfreibetrag_zaehler: num(form.kinderfreibetrag_zaehler) ?? 0,
    alleinerziehend: single && (num(form.kinder_im_haushalt) ?? 0) > 0, // § 24b EStG
    kinder_im_haushalt: num(form.kinder_im_haushalt) ?? 0,
  };
  if (mode === "bescheid") zve.bescheid_values = [num(form.bescheid_0), single ? null : num(form.bescheid_1)].filter((x) => x !== null);
  if (mode === "estimate") {
    const persons = $$(".zve-person").filter((z) => !z.hidden).map(zvePersonPayload);
    // all fields empty -> fall back to the quick estimate instead of a misleading zvE of 0 €
    const hasData = persons.some((p) => Object.values(p).some((v) => typeof v === "number" && v !== 0));
    if (hasData) zve.persons = persons;
  }
  return {
    birth_date: form.birth_date.value,
    due_date: form.due_date.value || null,
    household: form.household.value,
    single_parent_4c: form.single_parent_4c.checked,
    children_expected: Number(form.children_expected.value),
    premature_or_disability: form.premature_or_disability.checked,
    siblings: $$(".sibling").map((r) => ({ birth_date: $("[name=sibling_date]", r).value, disability: $("[name=sibling_disability]", r).checked })).filter((s) => s.birth_date),
    parents,
    zve,
    timeline: currentTimeline && currentTimeline.length === parents.length ? currentTimeline : null,
    hours: currentHours && currentHours.length === parents.length ? currentHours : null,
    kez_parent: currentKez !== null && currentKez < parents.length ? currentKez : null,
  };
}

async function runAnalysis({ keepScroll = false } = {}) {
  const scroll = $("#results").scrollTop;
  const res = await fetch("/api/analyse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildRequest()) });
  const body = await res.json();
  if (!res.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => `${d.loc.slice(1).join(" › ")}: ${d.msg}`).join("; ") : body.detail;
    renderError(detail);
    return false;
  }
  render(body);
  if (keepScroll) $("#results").scrollTop = scroll;
  return true;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!form.birth_date.value) {
    renderError("Enter the birth date of your child (between 01.01.2026 and 31.12.2027).");
    form.birth_date.focus();
    return;
  }
  if (await runAnalysis() && window.matchMedia("(max-width: 960px)").matches) $("#results").scrollIntoView({ behavior: "smooth" });
});

// ---------- save / export / import ---------------------------------------
// Everything stays on this device: localStorage or a JSON file the user keeps.
const STORAGE_KEY = "elterngeld-check:v1";
const FILE_MARKER = "elterngeld-check";

function snapshot() {
  const request = buildRequest();
  // keep the month plan that is on screen, even if it was never edited
  const shown = window.__lastResult?.plan?.timeline;
  if (!request.timeline && shown && shown.length === request.parents.length) request.timeline = shown;
  const shownHours = window.__lastResult?.plan?.hours;
  if (!request.hours && shownHours?.length === request.parents.length) request.hours = shownHours.map((row) => row.map(Number));
  return { app: FILE_MARKER, version: 1, saved_at: new Date().toISOString(), zve_mode: form.zve_mode.value, request };
}

async function restore(data, message) {
  fillForm(data);
  notify(message);
  if (form.birth_date.value) await runAnalysis();
}

function setField(root, name, value) {
  const el = $(`[name=${name}]`, root);
  if (!el || value === undefined || value === null) return;
  if (el.type === "checkbox") el.checked = Boolean(value);
  else el.value = String(value);
}

function fillForm(data) {
  if (!data || data.app !== FILE_MARKER || !data.request) throw new Error("This is not an Elterngeld Check file.");
  const req = data.request;
  setField(form, "birth_date", req.birth_date);
  form.due_date.value = req.due_date || "";
  $$("[name=household]").forEach((r) => { r.checked = r.value === req.household; });
  setField(form, "single_parent_4c", req.single_parent_4c);
  setField(form, "children_expected", req.children_expected);
  setField(form, "premature_or_disability", req.premature_or_disability);
  $("#siblings").replaceChildren();
  (req.siblings || []).forEach((s) => addSibling(s.birth_date, s.disability));

  const nodes = $$(".parent");
  (req.parents || []).slice(0, 2).forEach((p, i) => {
    const node = nodes[i];
    ["label", "birthing_parent", "erwerbsart", "monthly_gross", "bonuses_annual", "bonuses_pending", "bav_monthly", "steuerklasse",
      "faktor", "kirchensteuer", "kinderfreibetraege", "net_monthly", "vacation_days", "private_premium", "part_time_gross", "part_time_hours", "weekly_hours",
    ].forEach((k) => setField(node, k, p[k]));
    setField(node, "extra_excluded_months", (p.extra_excluded_months || []).join(", "));
    setField(node, "kv_art", p.kv_art || (p.kv_pflichtversichert === false ? "gkv_freiwillig" : "gkv_pflicht"));
    const b = p.basics || {};
    setField(node, "wohnsitz", b.wohnsitz_in_deutschland);
    setField(node, "haushalt", b.lebt_mit_kind_im_haushalt);
    setField(node, "aufenthalt", b.aufenthalt);
    setField(node, "erwerbstaetig", b.erwerbstaetig_oder_elternzeit_oder_alg1);
    setField(node, "aufenthalt_seit_monaten", b.aufenthalt_seit_monaten);
    node.classList.toggle("has-faktor", p.steuerklasse === "IV_FAKTOR");
    node.classList.toggle("show-permit", b.aufenthalt === "ae_humanitaer");
    node.classList.toggle("is-private", p.kv_art === "privat");
    $("[name=label]", node).dispatchEvent(new Event("input"));
    node.syncPartTime?.();
  });

  const z = req.zve || {};
  const mode = data.zve_mode || (z.mode === "bescheid" ? "bescheid" : z.persons?.length ? "estimate" : "quick");
  $$("[name=zve_mode]").forEach((r) => { r.checked = r.value === mode; });
  ["kinderfreibetrag_zaehler", "alleinerziehend", "kinder_im_haushalt"].forEach((k) => setField(form, k, z[k]));
  form.zusammenveranlagung.value = z.zusammenveranlagung === false ? "separate" : "joint";
  setField(form, "bescheid_0", z.bescheid_values?.[0] ?? "");
  setField(form, "bescheid_1", z.bescheid_values?.[1] ?? "");
  const zNodes = $$(".zve-person");
  (z.persons || []).slice(0, 2).forEach((person, i) => {
    $$("input", zNodes[i]).forEach((el) => {
      if (el.type === "checkbox") el.checked = Boolean(person[el.name]);
      else el.value = person[el.name] ?? "";
    });
  });
  syncHousehold();
  syncMode();
  syncCapYear();
  currentTimeline = Array.isArray(req.timeline) ? req.timeline : null;
  currentHours = Array.isArray(req.hours) ? req.hours : null;
  currentKez = Number.isInteger(req.kez_parent) ? req.kez_parent : null;
}

let notifyTimer;
function notify(msg) {
  const el = $("#storage-status");
  el.textContent = msg;
  el.classList.remove("gone");
  clearTimeout(notifyTimer);
  notifyTimer = setTimeout(() => el.classList.add("gone"), 5000);
}

function readSaved() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function refreshLoadButton() {
  const saved = readSaved();
  const btn = $("#load");
  const when = saved ? new Date(saved.saved_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "";
  btn.disabled = !saved;
  btn.title = saved ? `Saved ${when}` : "Nothing saved yet";
  btn.setAttribute("aria-label", saved ? `Load saved numbers from ${when}` : "Load saved – nothing saved yet");
  $(".dock-meta").textContent = saved ? `Saved ${when}` : "Not saved yet";
}


$("#save").addEventListener("click", () => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot()));
    notify("Numbers and month plan saved in this browser.");
  } catch {
    notify("This browser blocks local storage. Use Export file instead.");
  }
  refreshLoadButton();
});

$("#load").addEventListener("click", async () => {
  const saved = readSaved();
  if (!saved) return;
  try {
    await restore(saved, "Saved numbers and month plan loaded.");
  } catch (err) {
    notify(err.message);
  }
});

$("#export").addEventListener("click", () => {
  const data = snapshot();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `elterngeld-check-${data.request.birth_date || "draft"}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  notify("File exported. It contains your salary data – store it safely.");
});

$("#import").addEventListener("click", () => $("#import-file").click());
$("#import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    await restore(JSON.parse(await file.text()), `Imported ${file.name}.`);
  } catch (err) {
    notify(err instanceof SyntaxError ? "The file is not valid JSON." : err.message);
  }
});
refreshLoadButton();

// ---------- rendering -----------------------------------------------------
function renderError(msg) {
  $("#plan-section").innerHTML = "";
  $("#results").innerHTML = `<div class="card error"><h2>Check your input</h2><p>${esc(msg)}</p></div>`;
  refreshNav();
}

const STATUS_TEXT = { met: "Eligible", not_met: "Not eligible", conditional: "Probably eligible – verify" };

function verdict(r) {
  const overall = r.eligibility.some((e) => e.overall === "not_met") ? "not_met"
    : r.eligibility.some((e) => e.overall === "conditional") ? "conditional" : "met";
  const zve = Number(r.income_cap.zve_total);
  const cap = Number(r.scope.income_cap);
  const max = Math.max(cap * 1.4, zve * 1.1);
  const capPct = (cap / max) * 100;
  const youPct = Math.min((zve / max) * 100, 100);
  const src = { steuerbescheid: "from your Steuerbescheid", estimate: "estimated from your Lohnsteuerbescheinigung", quick_estimate: "quick estimate from monthly pay and bonuses" }[r.income_cap.source];
  const failing = r.eligibility.flatMap((e) => e.checks.filter((c) => c.status !== "met").map((c) => ({ ...c, who: e.label })));
  const uniqueFailing = [...new Map(failing.map((c) => [c.id + (c.id === "income_cap" ? "" : c.who), c])).values()];
  return `<div class="card verdict ${overall}">
    <p class="headline">${STATUS_TEXT[overall]}</p>
    <p>${esc(r.income_cap.check.explanation)} <span class="hint">(${src}, year ${r.scope.tax_year_before_birth})</span></p>
    <div class="gauge" style="--cap:${capPct}%;--you:${youPct}%" role="img" aria-label="zvE ${eur(zve, false)} compared with the cap of ${eur(cap, false)}">
      <div class="track"><div class="capline"></div><div class="you"></div></div>
      <div class="scale"><span>0 €</span><span>Cap ${eur(cap, false)}</span><span>${eur(max, false)}</span></div>
    </div>
    ${uniqueFailing.filter((c) => c.id !== "income_cap").map((c) => `<p class="failing"><span class="dot ${c.status}"></span><span><strong>${esc(c.who)}: ${esc(c.title)}</strong> – ${esc(c.explanation)} <span class="hint">${esc(c.legal_basis)}</span></span></p>`).join("")}
    ${gapBlock(r.income_cap.gap_analysis)}
  </div>`;
}

function gapBlock(g) {
  if (!g) return "";
  const combo = g.suggested_combination.length
    ? `<div class="combo"><strong>A combination that closes the gap</strong> (incl. ${eur(g.safety_buffer, false)} safety margin for the estimate):<ul>${g.suggested_combination.map((c) => `<li>${esc(c.title)}: ${eur(c.amount, false)}</li>`).join("")}</ul></div>`
    : `<p>The quantified levers (${eur(g.quantified_levers, false)}) do not close the gap of ${eur(g.gap, false)} on their own${g.cap_year_open ? "" : " – the year is already closed"}. See the steps below.</p>`;
  return `<p><strong>Gap to the cap: ${eur(g.gap, false)}.</strong></p>${combo}`;
}

function amounts(r) {
  const rows = r.parents.map((p) => {
    const a = p.amounts;
    return `<tr><th>${esc(p.label)}</th>
      <td class="num">${eur(p.netto.brutto)}</td>
      <td class="num">${eur(a.elterngeld_netto)}</td>
      <td class="num">${(Number(a.ersatzrate) * 100).toFixed(1).replace(".", ",")} %</td>
      <td class="num"><strong>${eur(a.basis)}</strong></td>
      <td class="num">${eur(a.plus)}${a.plus_mit_teilzeit ? `<small>${eur(a.plus_mit_teilzeit)} with part-time</small>` : ""}</td></tr>`;
  }).join("");
  const breakdown = r.parents.filter((p) => Number(p.netto.brutto) > 0).map((p) => {
    const n = p.netto;
    return `<details><summary>How ${esc(p.label)}'s Elterngeld-Netto is calculated</summary><table class="breakdown">
      ${Number(p.bav_deducted) > 0 ? `<tr><td>Average monthly gross before company pension conversion</td><td class="num">${eur(p.gross_before_bav)}</td></tr>
      <tr><td>− Tax-free company pension conversion (§ 3 Nr. 63 EStG – not counted)</td><td class="num">${eur(p.bav_deducted)}</td></tr>` : ""}
      <tr><td>Elterngeld gross (Steuerbrutto, regular pay)</td><td class="num">${eur(n.brutto)}</td></tr>
      <tr><td>− Lohnsteuer (PAP ${r.scope.tax_year_before_birth}, Kinderfreibeträge ignored, § 2e Abs. 3)</td><td class="num">${eur(n.steuern.lohnsteuer)}</td></tr>
      <tr><td>− Solidaritätszuschlag</td><td class="num">${eur(n.steuern.soli)}</td></tr>
      <tr><td>− Church tax (flat 8 %)</td><td class="num">${eur(n.steuern.kirchensteuer)}</td></tr>
      <tr><td>− Social contributions (flat 9 % / 10 % / 2 %, § 2f)</td><td class="num">${eur(n.sozialabgaben)}</td></tr>
      <tr><td>− 1/12 Arbeitnehmer-Pauschbetrag (§ 2c)</td><td class="num">${eur(n.werbungskostenpauschale)}</td></tr>
      <tfoot><tr><td>Elterngeld-Netto</td><td class="num">${eur(n.elterngeld_netto)}</td></tr></tfoot></table>
      ${p.part_time ? `<p class="hint">Part-time while on Elterngeld: ${esc(String(Number(p.part_time.hours)).replace(".", ","))} of ${esc(String(Number(p.part_time.weekly_hours)).replace(".", ","))} h/week, ${eur(p.part_time.gross)} gross ${p.part_time.source === "hours" ? "(pro rata from the hours)" : "(entered)"}, about ${eur(p.part_time.net_pay)} take-home pay per month. Elterngeld counts it as described in § 2 Abs. 3 BEEG.</p>` : ""}
      ${Number(p.bonuses_excluded) > 0 ? `<p class="hint">Bonuses and one-off payments (${eur(p.bonuses_excluded)} per year) are not counted for Elterngeld (§ 2c Abs. 1 Satz 2 BEEG) – they only count towards the income cap.</p>` : ""}
      <p class="hint">Bemessungszeitraum: ${esc(p.bemessungszeitraum[0])} to ${esc(p.bemessungszeitraum.at(-1))}${p.excluded_months.length ? `, skipped: ${esc(p.excluded_months.join(", "))}` : ""}.${p.minijob_midijob_note ? " Mini-/Midijob income: parameters as in the official calculator (approximation)." : ""}</p></details>`;
  }).join("");
  return `<div class="card"><h2>Monthly amounts</h2>
    <table class="amounts"><thead><tr><th></th><th class="num">Gross</th><th class="num">Netto</th><th class="num">Rate</th><th class="num">Basis</th><th class="num">Plus</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="hint">Netto = Elterngeld-Netto, the notional net income the Elterngeld is based on.</p>
    ${r.geschwisterbonus ? '<p class="hint">Includes the Geschwisterbonus.</p>' : ""}
    ${breakdown}</div>`;
}

// ---------- month planner ---------------------------------------------------
const TYPE_LABEL = { none: "–", basis: "Basis", plus: "Plus", plus_tz: "Plus + work", bonus: "Bonus", ez: "Leave only" };
const TYPE_KEY = [
  ["basis", "Basis", "Basiselterngeld"],
  ["plus", "Plus", "ElterngeldPlus, not working"],
  ["plus_tz", "Plus + work", "ElterngeldPlus while working part-time"],
  ["bonus", "Bonus", "Partnerschaftsbonus (24–32 h)"],
  ["ez", "Leave only", "Elternzeit without Elterngeld"],
];
const shortDate = (iso) => new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "2-digit" });
const longDate = (iso) => new Date(iso).toLocaleDateString("de-DE");
let showAllMonths = false;

function prebirth(r) {
  const m = r.mutterschutz;
  if (!m || m.status === "none" || !m.days_before) return "";
  const what = m.status === "beamtin" ? "pay continues" : `Mutterschaftsgeld ${eur(m.before_birth)}`;
  return `<tr class="prebirth"><th>–</th><td class="period">${shortDate(m.start)}</td>
    <td colspan="${r.parents.length * 5 + (r.parents.length > 1 ? 1 : 0)}">${esc(m.label)}: Mutterschutz before birth, ${m.days_before} days, ${what}</td></tr>`;
}

function totals(r) {
  const p = r.plan;
  const m = r.mutterschutz;
  const preMg = m && ["gkv", "privat"].includes(m.status) ? Number(m.before_birth) + Number(m.bas_total) : 0;
  const rows = r.parents.map((x, i) => {
    const t = p.month_totals[i];
    return `<tr><th><span class="who" style="--c:${PARENT_COLORS[i]}"></span>${esc(x.label)}</th>
      <td class="num">${eur(t.net_pay)}</td><td class="num">${eur(t.elterngeld)}</td><td class="num">${eur(t.mutterschaftsgeld)}</td>
      <td class="num"><strong>${eur(t.total)}</strong></td></tr>`;
  }).join("");
  const sum = (k) => p.month_totals.reduce((a, t) => a + Number(t[k]), 0);
  const household = r.parents.length > 1 ? `<tr class="sum"><th>Household</th><td class="num">${eur(sum("net_pay"))}</td><td class="num">${eur(sum("elterngeld"))}</td><td class="num">${eur(sum("mutterschaftsgeld"))}</td><td class="num"><strong>${eur(sum("total"))}</strong></td></tr>` : "";
  return `<div class="plan-totals"><h3>Total net, months 1–${p.plan_end_lm}</h3>
    <div class="table-scroll"><table><thead><tr><th></th><th class="num">Salary (net)</th><th class="num">Elterngeld</th><th class="num">Mutterschaftsgeld</th><th class="num">Total</th></tr></thead>
    <tbody>${rows}${household}</tbody></table></div>
    ${preMg ? `<p class="hint">Plus ${eur(preMg)} Mutterschaftsgeld before birth${Number(m.bas_total) ? " (incl. the one-off from the BAS)" : ""}.</p>` : ""}
    <p class="hint">Salaries are estimated from your gross pay and hours with your Steuerklasse and social contributions (child born, no bonuses or company pension). Months marked "–" count as back at work with the hours shown.</p>
  </div>`;
}

function meter(used, limit) {
  const pct = Math.min(100, (Number(used) / Number(limit)) * 100);
  return `<span class="meter" role="img" aria-label="${used} of ${limit}"><span style="width:${pct}%"></span></span>`;
}

const fmtMonths = (x) => String(Number(x)).replace(".", ",");

const PARENT_COLORS = ["var(--pa)", "var(--pb)"];

/** One bar for the shared pool: every slot is one Basis month (= 2 Plus months), coloured by parent. */
function poolBar(b) {
  const max = b.shared_max;
  const used = b.parents.map((q) => Number(q.equivalents_used));
  const slots = [];
  for (let k = 0; k < max; k++) {
    let from = 0;
    const stops = [];
    used.forEach((u, i) => {
      const before = used.slice(0, i).reduce((a, x) => a + x, 0);
      const part = Math.min(Math.max(before + u - k, 0), 1) - Math.min(Math.max(before - k, 0), 1);
      if (part > 0) { stops.push(`${PARENT_COLORS[i]} ${from * 100}% ${(from + part) * 100}%`); from += part; }
    });
    if (from < 1) stops.push(`transparent ${from * 100}% 100%`);
    const locked = k >= b.shared_limit && from === 0;
    const partner = max === 14 && k >= 12;
    slots.push(`<span class="slot${locked ? " locked" : ""}${partner ? " partner" : ""}" style="background:linear-gradient(90deg, ${stops.join(", ")})"></span>`);
  }
  return `<div class="pool" role="img" aria-label="${fmtMonths(b.shared_used)} of ${max} shared months used">${slots.join("")}</div>`;
}

function budget(r) {
  const b = r.plan.budget;
  if (!b || !b.parents) return "";
  const couple = b.parents.length === 2;
  const rows = b.parents.map((q, i) => {
    const left = Number(q.equivalents_left);
    const possible = left > 0
      ? [q.basis_possible ? `${q.basis_possible} Basis` : "", q.plus_possible ? `${q.plus_possible} Plus` : ""].filter(Boolean).join(" or ") || "–"
      : "–";
    const taken = [`${q.basis_used} Basis`, `${q.plus_used} Plus`].join("<br>");
    const takenNote = [q.mutterschutz_basis ? `${q.mutterschutz_basis} Basis in Mutterschutz` : "", q.plus_with_work_used ? `${q.plus_with_work_used} Plus with work` : ""].filter(Boolean).join(", ");
    return `<tr>
      <th class="name"><span class="who" style="--c:${PARENT_COLORS[i]}"></span>${esc(q.label)}</th>
      <td data-label="Taken">${taken}${takenNote ? `<small>${takenNote}</small>` : ""}</td>
      <td class="num" data-label="Share of ${b.shared_max}">${fmtMonths(q.equivalents_used)}<small>own max. ${q.equivalents_limit}</small></td>
      <td data-label="Still possible">${possible}</td>
      <td data-label="Bonus">${q.bonus_possible ? (q.bonus_used ? `<span class="chip bonus used">${q.bonus_used} of ${b.bonus_max} used</span>` : `<span class="chip bonus">${b.bonus_max} available</span>`) : "–"}</td>
      <td class="num" data-label="Elternzeit">${q.elternzeit_used === null ? "–" : `${q.elternzeit_used} of 36${meter(q.elternzeit_used, 36)}`}</td>
    </tr>`;
  }).join("");
  const other = couple ? b.parents.find((q) => q.basis_used + q.plus_used === 0) : null;
  const partner = {
    unlocked: "Both parents claim, so the 2 Partnermonate are unlocked.",
    available: `The last 2 months (Partnermonate) unlock only if ${other ? esc(other.label) : "the other parent"} takes at least 2 months.`,
    not_used: "Nobody claims Elterngeld yet.",
  }[b.partnermonate] || "";
  const left = Number(b.shared_left);
  const shares = b.parents.map((q, i) => `<span class="share"><span class="who" style="--c:${PARENT_COLORS[i]}"></span>${esc(q.label)} ${fmtMonths(q.equivalents_used)}</span>`).join("");
  const poolName = couple ? `${b.shared_max} months shared by both parents` : `${b.shared_max} months`;
  const poolSplit = b.shared_max === 14 ? (couple ? "12 + 2 Partnermonate" : "single parent, § 4c BEEG") : "";
  return `<div class="budget">
    <h3>Months used and left</h3>
    <p class="pool-title"><strong>${poolName}</strong>${poolSplit ? ` <span class="hint">(${poolSplit})</span>` : ""}</p>
    ${poolBar(b)}
    <p class="pool-status">${shares}<span class="share left"><strong>${fmtMonths(left)} left</strong>${b.shared_limit < b.shared_max ? ` of ${b.shared_limit} until the Partnermonate unlock` : ""}</span></p>
    <p class="hint">${partner} One slot = 1 Basis month or 2 Plus months; Partnerschaftsbonus months come on top. Choices that would exceed a limit are greyed out in the table.</p>
    <table class="budget-table"><thead><tr><th></th><th>Taken</th><th class="num">Share${couple ? ` of ${b.shared_max}` : ""}</th><th>Still possible</th><th>Bonus</th><th class="num">Elternzeit</th></tr></thead>
    <tbody>${rows}</tbody></table>
  </div>`;
}

function mutterschutz(r) {
  const m = r.mutterschutz;
  if (!m || m.status === "none") return "";
  const total = m.total_days;
  const seg = (days, cls, label) => `<span class="seg ${cls}" style="flex:${days}" title="${label}"></span>`;
  const bar = `<div class="ms-bar" aria-hidden="true">${seg(m.days_before, "before", "before birth")}${seg(1, "day", "day of birth")}${seg(m.days_after, "after", "after birth")}</div>
    <div class="ms-dates"><span>${longDate(m.start)}</span><span>Birth ${longDate(m.birth)}</span><span>${longDate(m.end)}</span></div>`;
  const src = m.net_source === "input" ? "from your payslip" : '<span class="badge estimate">Estimate</span> enter your payslip net pay for the exact figure';
  let rows;
  if (m.status === "beamtin") {
    rows = `<tr><td>Your pay continues during Mutterschutz (civil-service rules); it is credited against Elterngeld after birth.</td><td class="num">${eur(m.net_monthly)} / month</td></tr>`;
  } else {
    rows = `<tr><td>Net pay per calendar day: ${eur(m.net_monthly)} × 3 / 90 <small>${src}</small></td><td class="num">${eur(m.daily_net)}</td></tr>
      ${m.status === "gkv" ? `<tr><td>Krankenkasse: ${eur(m.kk_per_day)} per day × ${total} days <small>§ 24i SGB V, max. 13 € per day</small></td><td class="num">${eur(m.kk_total)}</td></tr>` : `<tr><td>Bundesamt für Soziale Sicherung, one-off <small>§ 19 Abs. 2 MuSchG, max. 210 €; not deducted from Elterngeld</small></td><td class="num">${eur(m.bas_total)}</td></tr>`}
      <tr><td>Employer top-up: ${eur(m.employer_per_day)} per day × ${total} days <small>§ 20 MuSchG</small></td><td class="num">${eur(m.employer_total)}</td></tr>`;
  }
  const foot = m.status === "beamtin" ? "" : `<tfoot><tr><td>Total</td><td class="num">${eur(m.total)}</td></tr></tfoot>`;
  const split = m.status === "beamtin" ? "" : `<p class="hint">${eur(m.before_birth)} for the ${m.days_before} days before birth and ${eur(m.from_birth)} from the day of birth. Benefits from the day of birth are deducted from Elterngeld day by day, and those months count as Basis months (§ 3 Abs. 1, § 4 Abs. 4 BEEG). Mutterschaftsgeld is tax-free but raises the tax rate on other income (§ 3 Nr. 1 d, § 32b EStG).</p>`;
  const apply = { gkv: "Apply at your Krankenkasse with the doctor's or midwife's certificate of the expected date (§ 24i Abs. 3 SGB V); the employer top-up comes with your payroll.", privat: "Apply for the 210 € at the Bundesamt für Soziale Sicherung; the employer top-up comes with your payroll.", beamtin: "" }[m.status];
  return `<div class="card mutterschutz"><h2>Mutterschutz and Mutterschaftsgeld</h2>
    <p class="hint">${esc(m.label)}: ${m.days_before} days before birth, the day of birth and ${m.days_after} days after (${m.weeks_after} weeks${m.extension_days ? ` + ${m.extension_days} days for the early birth` : ""}) – § 3 MuSchG.</p>
    ${bar}
    <table class="breakdown">${rows}${foot}</table>
    ${split}
    ${apply ? `<p class="hint">${apply}</p>` : ""}
  </div>`;
}

// Basis-equivalents a month type uses (§ 4 Abs. 3 Satz 3 BEEG: 1 Basis = 2 Plus)
const EQ = { none: 0, basis: 1, plus: 0.5, plus_tz: 0.5, bonus: 0, ez: 0 };

/** Why switching this cell from `cur` to `next` is not allowed – or "" if it is. */
function blockedReason(p, i, lm, cur, next) {
  const b = p.budget;
  const q = b.parents[i];
  const tl = p.timeline;
  if (i === b.birthing && b.mutterschutz_months.includes(lm)) return "Mutterschutz month";
  if (next === "basis" && lm > 14) return "only until month 14";
  if (EQ[next] - EQ[cur] > Number(q.equivalents_left) + 1e-9) return "none left";
  if (next === "bonus") {
    if (!q.bonus_possible) return "needs a second parent";
    if (cur !== "bonus" && q.bonus_used >= b.bonus_max) return `${b.bonus_max} of ${b.bonus_max} used`;
  }
  if (next === "basis" && tl.length === 2 && !b.simultaneous_basis_allowed) {
    const other = tl[1 - i];
    if (other[lm - 1] === "basis") {
      const together = tl[i].filter((t, k) => t === "basis" && other[k] === "basis" && k !== lm - 1).length;
      if (together >= 1 || lm > 12) return "both on Basis only once";
    }
  }
  return "";
}

function bonusWindow(p, n) {
  const tl = p.timeline;
  let last = 0;
  tl.forEach((row) => row.forEach((t, k) => { if (["basis", "plus", "plus_tz", "bonus"].includes(t) && k < 32) last = Math.max(last, k + 1); }));
  const start = last + 1;
  if (start + 3 > 32) return null;
  for (let lm = start; lm < start + 4; lm++) if (tl.some((row) => row[lm - 1] !== "none")) return null;
  return start;
}

function bonusNotice(r) {
  const p = r.plan;
  const b = p.budget;
  if (!b?.parents?.[0]?.bonus_possible) return "";
  const used = Math.max(...b.parents.map((q) => q.bonus_used));
  if (used >= b.bonus_max) return `<div class="bonus-notice done"><strong>Partnerschaftsbonus: all ${b.bonus_max} months used.</strong></div>`;
  const hours = $$(".parent").filter((x) => !x.hidden).map((x) => Number($("[name=part_time_hours]", x).value || 0));
  const hoursOk = hours.every((h) => h >= 24 && h <= 32);
  const perMonth = r.parents.reduce((sum, x) => sum + Number(x.amounts.plus_mit_teilzeit || x.amounts.plus), 0);
  const missing = b.bonus_max - used;
  const start = used === 0 ? bonusWindow(p, r.parents.length) : null;
  const action = start
    ? `<button type="button" class="bonus-add" data-bonus-start="${start}">Add ${missing} bonus months (months ${start}–${start + missing - 1})</button>`
    : used ? `<span>Extend your bonus block to up to ${b.bonus_max} consecutive months in the table.</span>`
      : "<span>Free 4 consecutive months in the table to add it.</span>";
  return `<div class="bonus-notice">
    <p><strong>Partnerschaftsbonus available: ${missing} more month${missing > 1 ? "s" : ""}${r.parents.length > 1 ? " for each parent" : ""}</strong>
    – ${r.parents.every((x) => x.amounts.plus_mit_teilzeit) ? "about" : "up to about"} ${eur(perMonth * missing, false)} extra${r.parents.every((x) => x.amounts.plus_mit_teilzeit) ? "" : "; enter the planned part-time pay for the exact amount"}.</p>
    <p class="${hoursOk ? "" : "warn"}">${hoursOk ? "Your planned hours (24–32 h/week) qualify." : `Needs 24–32 working hours/week ${r.parents.length > 1 ? "for both parents " : ""}in every bonus month – enter the planned hours under "Part-time".`}</p>
    ${action}
  </div>`;
}

function planner(r) {
  const p = r.plan;
  const n = r.parents.length;
  const valid = p.presets.filter((x) => x.valid);
  const richest = valid.reduce((a, b) => (!a || Number(b.household_total) > Number(a.household_total) ? b : a), null);
  const longest = valid.reduce((a, b) => (!a || b.months_with_elterngeld > a.months_with_elterngeld ? b : a), null);
  const current = JSON.stringify(p.timeline);
  const presets = p.presets.map((x) => {
    const tags = [x === richest ? "Most money" : "", x === longest && x !== richest ? "Longest" : "", JSON.stringify(x.timeline) === current ? "Your plan" : ""].filter(Boolean);
    return `<button type="button" class="preset${x.valid ? "" : " invalid"}${JSON.stringify(x.timeline) === current ? " current" : ""}" data-preset="${esc(x.id)}" aria-pressed="${JSON.stringify(x.timeline) === current}">
      <strong>${esc(x.name)}</strong>
      <span class="sum">${eur(x.household_total, false)}</span>
      <span class="months">${x.months_with_elterngeld} months with Elterngeld</span>
      <small>${esc(x.description)}${x.valid ? "" : `<span class="warn"><br>Not possible yet: ${esc(x.errors[0])}</span>`}</small>
      <span class="tags">${tags.map((t) => `<span class="tag">${t}</span>`).join("")}</span>
    </button>`;
  }).join("");

  const options = (sel, lm, i) => Object.entries(TYPE_LABEL)
    .filter(([k]) => !(lm > 32 && k !== "none" && k !== "ez"))
    .map(([k, v]) => {
      const why = k === sel ? "" : blockedReason(p, i, lm, sel, k);
      return `<option value="${k}"${k === sel ? " selected" : ""}${why ? " disabled" : ""}>${v}${why ? ` (${why})` : ""}</option>`;
    }).join("");
  const lastShown = Math.max(p.plan_end_lm + 1, 14);
  const rows = p.rows.map((row) => {
    const hidden = !showAllMonths && row.lm > lastShown;
    const household = row.parents.reduce((a, c) => a + Number(c.total_net || 0), 0);
    const cells = row.parents.map((c, i) => {
      const locked = (i === p.budget.birthing && p.budget.mutterschutz_months.includes(row.lm)) || !r.parents[i].works;
      const eg = ["basis", "plus", "plus_tz", "bonus"].includes(c.type);
      return `<td class="t-${c.type}">
        <select data-parent="${i}" data-lm="${row.lm}" aria-label="${esc(r.parents[i].label)}, Lebensmonat ${row.lm}">${options(c.type, row.lm, i)}</select></td>
        <td class="hrs-cell t-${c.type}"><input class="hrs" type="number" inputmode="decimal" min="0" max="60" step="0.5" value="${Number(c.hours ?? 0)}" data-parent="${i}" data-lm="${row.lm}" aria-label="${esc(r.parents[i].label)}, hours per week in Lebensmonat ${row.lm}"${locked ? " disabled" : ""}></td>
        <td class="num">${c.net_pay ? `${eur(c.net_pay)}<small>gross ${eur(c.gross_pay, false)}</small>` : ""}</td>
        <td class="num t-${c.type}"${c.mutterschutz_days ? ` title="${c.mutterschutz_days} days of Mutterschutz: Elterngeld ${eur(c.elterngeld_before_credit)} minus credited Mutterschaftsgeld"` : ""}>${eg ? eur(c.amount) : ""}${c.mutterschaftsgeld ? `<small class="mg">+${eur(c.mutterschaftsgeld)} MG</small>` : ""}</td>
        <td class="num total">${Number(c.total_net) ? eur(c.total_net) : ""}</td>`;
    }).join("");
    return `<tr${hidden ? " hidden" : ""}><th title="${shortDate(row.start)} – ${shortDate(row.end)}">${row.lm}</th><td class="period" title="${shortDate(row.start)} – ${shortDate(row.end)}">${shortDate(row.start)}</td>${cells}${n > 1 ? `<td class="num household">${household ? eur(household) : ""}</td>` : ""}</tr>`;
  }).join("");

  const head1 = r.parents.map((x, i) => `<th colspan="5" class="parent-head"><span class="who" style="--c:${PARENT_COLORS[i]}"></span>${esc(x.label)}</th>`).join("") + (n > 1 ? '<th class="parent-head">Household</th>' : "");
  const head2 = r.parents.map(() => '<th>Type</th><th>h/week</th><th class="num">Salary net</th><th class="num">Elterngeld</th><th class="num">Total net</th>').join("") + (n > 1 ? '<th class="num">Total net</th>' : "");
  const shownRows = p.rows.filter((row) => showAllMonths || row.lm <= lastShown);
  const colSum = (i, f) => shownRows.reduce((a, row) => a + Number(f(row.parents[i]) || 0), 0);
  const foot = r.parents.map((_, i) => `<td></td><td></td><td class="num">${eur(colSum(i, (c) => c.net_pay))}</td><td class="num">${eur(colSum(i, (c) => (["basis", "plus", "plus_tz", "bonus"].includes(c.type) ? Number(c.amount) : 0) + Number(c.mutterschaftsgeld || 0)))}</td><td class="num total">${eur(colSum(i, (c) => c.total_net))}</td>`).join("")
    + (n > 1 ? `<td class="num household">${eur(r.parents.reduce((a, _, i) => a + colSum(i, (c) => c.total_net), 0))}</td>` : "");
  const cols = `<colgroup><col class="c-lm"><col class="c-period">${r.parents.map(() => '<col class="c-sel"><col class="c-hrs"><col class="c-amt"><col class="c-amt"><col class="c-amt">').join("")}${n > 1 ? '<col class="c-amt">' : ""}</colgroup>`;
  const mgKey = r.mutterschutz && ["gkv", "privat"].includes(r.mutterschutz.status)
    ? `<li><span class="swatch mg-swatch">+</span><span><strong>+ … MG</strong> Mutterschaftsgeld incl. employer top-up; Elterngeld is reduced by it</span></li>` : "";
  const payKey = "";
  const key = `<ul class="legend-key">${TYPE_KEY.map(([k, short, long]) => `<li><span class="swatch t-${k}"></span><span><strong>${short}</strong> ${long}</span></li>`).join("")}${mgKey}${payKey}</ul>`;
  const errs = p.errors.map((e) => `<li><span class="dot not_met"></span>${esc(e)}</li>`).join("");
  const notes = p.notes.map((e) => `<li><span class="dot conditional"></span>${esc(e)}</li>`).join("");

  return `<div class="card planner" id="plan"><h2>Plan Elterngeld and Elternzeit</h2>
    <p class="hint">Pick a starting point, then change single months and the hours you work. Salary is calculated from your gross pay and contract hours; Elterngeld in months with work uses the average income of all Basis months, or of all Plus and Bonus months, with work (§ 2 Abs. 3 BEEG). 1 Basis month = 2 Plus months.</p>
    <div class="presets">${presets}</div>
    ${errs || notes ? `<ul class="checks">${errs}${notes}</ul>` : ""}
    ${budget(r)}
    ${bonusNotice(r)}
    ${key}
    <p class="hint scroll-hint">Swipe the table sideways to see both parents.</p>
    <div class="table-scroll"><table class="timeline">${cols}<thead><tr><th rowspan="2">#</th><th rowspan="2">From</th>${head1}</tr><tr>${head2}</tr></thead>
      <tbody>${prebirth(r)}${rows}</tbody>
      <tfoot><tr><td colspan="2">Sum</td>${foot}</tr></tfoot></table></div>
    <button type="button" class="link" id="toggle-months">${showAllMonths ? `Show months 1–${lastShown} only` : "Show all months up to 36"}</button>
    ${totals(r)}
  </div>` + elternzeit(p);
}

function elternzeit(p) {
  const parts = p.elternzeit.map((e) => {
    const blocks = e.blocks.map((b) => `<tr><td>Month ${b.from_lm}–${b.to_lm}<br><small>${b.months} months</small></td>
      <td>${longDate(b.start)} – ${longDate(b.end)}${b.note ? `<br><small>${esc(b.note)}</small>` : ""}</td>
      <td><strong>${longDate(b.request_by)}</strong></td>
      <td>${longDate(b.protection_from)}</td></tr>`).join("");
    return `<h3>${esc(e.label)}</h3>
      ${blocks ? `<table><thead><tr><th>Lebensmonate</th><th>Elternzeit</th><th>Request by</th><th>Dismissal protection from</th></tr></thead><tbody>${blocks}</tbody></table>` : `<p class="hint">No Elternzeit in this plan.</p>`}
      ${e.notes.length ? `<ul>${e.notes.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
  }).join("");
  return `<div class="card elternzeit"><h2>Elternzeit requests</h2>
    <p class="hint">Elternzeit is the job-protected leave towards your employer; Elterngeld is the money. Dismissal protection applies from your request, at the earliest 8 weeks before the start (§ 18 BEEG).</p>${parts}</div>`;
}

function hoursFromResult() {
  const shown = window.__lastResult?.plan?.hours || [];
  return currentHours ? currentHours.map((row) => row.slice()) : shown.map((row) => row.map(() => null));
}

$("#plan-section").addEventListener("change", (e) => {
  if (!window.__lastResult) return;
  if (e.target.id === "kez-parent") {
    currentKez = Number(e.target.value);
    runAnalysis({ keepScroll: true });
    return;
  }
  const sel = e.target.closest("select[data-lm]");
  const hrs = e.target.closest("input.hrs");
  const i = Number((sel || hrs)?.dataset.parent);
  const lm = Number((sel || hrs)?.dataset.lm);
  if (sel) {
    currentTimeline = window.__lastResult.plan.timeline.map((row) => row.slice());
    currentTimeline[i][lm - 1] = sel.value;
    currentHours = hoursFromResult();
    currentHours[i][lm - 1] = null; // new month type -> its default hours
  } else if (hrs) {
    currentTimeline = window.__lastResult.plan.timeline.map((row) => row.slice());
    currentHours = hoursFromResult();
    currentHours[i][lm - 1] = hrs.value === "" ? null : Math.min(60, Math.max(0, Number(hrs.value)));
  } else return;
  runAnalysis({ keepScroll: true });
});
$("#plan-section").addEventListener("click", (e) => {
  const kezBtn = e.target.closest("[data-kez]");
  if (kezBtn) {
    const sel = $("#kez-parent");
    if (!sel) return;
    sel.value = kezBtn.dataset.kez;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
  const add = e.target.closest("[data-bonus-start]");
  if (add && window.__lastResult) {
    const p = window.__lastResult.plan;
    const start = Number(add.dataset.bonusStart);
    const missing = p.budget.bonus_max - Math.max(...p.budget.parents.map((q) => q.bonus_used));
    currentTimeline = p.timeline.map((row) => row.slice());
    currentTimeline.forEach((row) => { for (let lm = start; lm < start + missing; lm++) row[lm - 1] = "bonus"; });
    currentHours = hoursFromResult();
    currentHours.forEach((row) => { for (let lm = start; lm < start + missing; lm++) row[lm - 1] = null; });
    runAnalysis({ keepScroll: true });
    return;
  }
  const preset = e.target.closest("[data-preset]");
  if (preset && window.__lastResult) {
    currentTimeline = window.__lastResult.plan.presets.find((x) => x.id === preset.dataset.preset).timeline;
    currentHours = null; // presets start from the default hours
    runAnalysis({ keepScroll: true });
  }
  if (e.target.id === "toggle-months") {
    showAllMonths = !showAllMonths;
    render(window.__lastResult, true);
  }
});

// ---------- vacation, pension, health insurance -------------------------------
const fmtNum = (x, d = 2) => Number(x).toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
const lmRange = (a, b) => (a === b ? `Month ${a}` : `Months ${a}–${b}`);

function vacationCard(r) {
  const v = r.social.vacation;
  if (!v.length) {
    return `<div class="card social" id="vacation"><h2>Vacation days</h2><p class="hint">Enter "Vacation days per year" for each parent in the form to see how Elternzeit affects them.</p></div>`;
  }
  const parts = v.map((x) => {
    const rows = x.years.map((y) => `<tr><td>${y.year}</td><td class="num">${y.entitlement}</td>
      <td>${y.full_months ? `${y.full_months}<small>${y.months.join(", ")}</small>` : "0"}</td>
      <td class="num">${Number(y.max_reduction) ? `−${fmtNum(y.max_reduction)}` : "0"}</td>
      <td class="num"><strong>${fmtNum(y.remaining_if_reduced)}</strong></td>
      <td>${y.part_time_months.length ? `<small>${y.part_time_months.join(", ")}</small>` : "–"}</td></tr>`).join("");
    return `<h3>${esc(x.label)}</h3>
      ${rows ? `<div class="table-scroll"><table class="vac"><thead><tr><th>Year</th><th class="num">Days</th><th>Full months of Elternzeit without work</th><th class="num">Max. reduction</th><th class="num">Left at worst</th><th>Part-time months (no reduction)</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : '<p class="hint">No Elternzeit in this plan – no change to the vacation days.</p>'}
      ${x.civil_servant ? '<p class="hint">Civil servants: the leave regulations of the Bund or Land apply instead of § 17 BEEG.</p>' : ""}`;
  }).join("");
  return `<div class="card social" id="vacation"><h2>Vacation days</h2>
    <p class="hint">Mutterschutz never reduces vacation (§ 24 MuSchG). During Elternzeit the employer <em>may</em> cut 1/12 of the annual leave for each <strong>full calendar month</strong> without work – only by an explicit declaration to you, and never for months in which you work part-time for that employer (§ 17 BEEG; BAG 19.03.2019 – 9 AZR 362/18). Unused leave from before is kept and can be taken afterwards (§ 17 Abs. 2).</p>
    ${parts}
    <p class="hint">"Left at worst" assumes the employer declares the full reduction. How fractions of days are rounded depends on your contract or collective agreement.</p></div>`;
}

function pensionCard(r) {
  const p = r.social.pension;
  const options = r.parents.map((x, i) => `<option value="${i}"${i === p.kez_parent ? " selected" : ""}>${esc(x.label)}</option>`).join("");
  const rows = p.parents.map((x, i) => x.status === "beamt"
    ? `<tr><th>${esc(x.label)}</th><td colspan="6">Civil servant: no statutory pension; child-raising is credited under civil-service pension rules (Kindererziehungszuschlag).</td></tr>`
    : `<tr><th><span class="who" style="--c:${PARENT_COLORS[i]}"></span>${esc(x.label)}</th>
      <td class="num">${fmtNum(x.points_without_child, 4)}</td>
      <td class="num">${fmtNum(x.points_from_salary, 4)}</td>
      <td class="num">${Number(x.points_kez) ? `+${fmtNum(x.points_kez, 4)}` : "–"}${Number(x.points_kez) && x.points_kez !== x.points_kez_uncapped ? "<small>capped at the ceiling</small>" : ""}</td>
      <td class="num"><strong>${fmtNum(x.points_total, 4)}</strong></td>
      <td class="num ${Number(x.difference) >= 0 ? "pos" : "neg"}">${Number(x.difference) >= 0 ? "+" : ""}${fmtNum(x.difference, 4)}</td>
      <td class="num ${Number(x.difference) >= 0 ? "pos" : "neg"}">${Number(x.difference) >= 0 ? "+" : ""}${eur(x.pension_per_month_difference)}</td></tr>`).join("");
  const window = p.parents.find((x) => x.window)?.window || "";
  const estimated = [...new Set(p.parents.flatMap((x) => x.estimated_years || []))];
  return `<div class="card social" id="pension"><h2>Pension points</h2>
    <p class="hint">Points for the statutory pension from Mutterschutz until the end of the 36 months of Kindererziehungszeit (${esc(window)}), compared with working your contract hours without a child. Kindererziehungszeit adds 0,0833 points per month for 36 months from the month after birth, on top of points from salary up to the contribution ceiling (§§ 56, 70 SGB VI). Elterngeld and Mutterschaftsgeld themselves carry no pension contributions; Mutterschutz counts as Anrechnungszeit (§ 58).</p>
    <label class="field kez"><span class="t">Kindererziehungszeit credited to</span><small>default: the mother; the other parent only by joint declaration to the Deutsche Rentenversicherung (§ 56 Abs. 2)</small><select id="kez-parent">${options}</select></label>
    <div class="table-scroll"><table><thead><tr><th></th><th class="num">Without child</th><th class="num">From salary</th><th class="num">Kindererziehungszeit</th><th class="num">With child</th><th class="num">Difference</th><th class="num">Pension / month</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="hint">1 point = ${eur(p.rentenwert)} monthly pension (aktueller Rentenwert from 01.07.2026), shown in today's value. Average earnings: 2026 provisional, 2027 cabinet decision${estimated.length ? `; ${estimated.join(", ")} estimated with 2027 figures` : ""}. Months after the plan count as back at work with the hours in the table.</p></div>`;
}

function healthCard(r) {
  const h = r.social.health;
  const art = { gkv_pflicht: "statutory, compulsory", gkv_freiwillig: "statutory, voluntary", privat: "private" };
  const parts = h.parents.map((x, i) => `<h3><span class="who" style="--c:${PARENT_COLORS[i]}"></span>${esc(x.label)} <small class="hint">${art[x.kv_art]}</small></h3>
    <div class="table-scroll"><table class="phases"><tbody>${x.phases.map((ph) => `<tr class="hp-${ph.status}"><td>${lmRange(ph.from_lm, ph.to_lm)}</td><td>${esc(ph.text)}</td><td class="num">${ph.per_month === null ? "–" : `${eur(ph.per_month)} / month`}</td></tr>`).join("")}</tbody></table></div>`).join("");
  const pv = h.pv_childless_ends_for.length ? `<p class="hint">The 0,6 % childless surcharge to care insurance ends with the birth for ${h.pv_childless_ends_for.map((x) => esc(x.label)).join(" and ")} (§ 55 Abs. 3 SGB XI); from the second child the rate falls by 0,25 points per child under 25.</p>` : "";
  return `<div class="card social" id="health"><h2>Health insurance and the child</h2>
    <p class="hint">Compulsorily insured members stay insured without contributions while receiving Mutterschaftsgeld or Elterngeld and during Elternzeit (§§ 192, 224 SGB V). Voluntary members pay at least the minimum contribution unless they can join the spouse's family insurance. Private premiums continue; the employer subsidy is only paid on salary. Amounts are the employee's own share, estimated with the average Zusatzbeitrag.</p>
    ${parts}
    <h3>The child</h3><p class="child-status ${esc(h.child.status)}">${esc(h.child.text)}</p>
    ${pv}</div>`;
}

const CLASS_NAME = { IV_FAKTOR: "IV with Faktor" };
const className = (k) => CLASS_NAME[k] || k;

function choicesCard(r) {
  const s = r.social;
  const label = (i) => esc(r.parents[i].label);
  const dot = (i) => `<span class="who" style="--c:${PARENT_COLORS[i]}"></span>`;

  // Kindererziehungszeit
  let kez = "";
  const k = s.kez_advice;
  if (k) {
    const chosen = s.pension.kez_parent;
    const rows = k.options.map((o) => `<tr${o.parent === k.suggested ? ' class="best"' : ""}><th>${dot(o.parent)}${label(o.parent)}</th>
      <td class="num">${fmtNum(o.kez_points, 4)}</td><td class="num">${fmtNum(o.household_points, 4)}</td><td class="num">${eur(o.household_pension_per_month)}</td></tr>`).join("");
    const verdict = k.tie
      ? `Either parent: the household gets the same points. By default it goes to the mother.`
      : `Credit it to ${label(k.suggested)}: about ${eur(k.margin_per_month)} more monthly pension for the household (${fmtNum(k.margin_points, 4)} points).`;
    kez = `<section class="choice"><h3>Kindererziehungszeit – for the pension</h3>
      <p class="pick">${verdict}${!k.tie && chosen !== k.suggested ? ` <button type="button" class="link" data-kez="${k.suggested}">Show this in the pension card</button>` : ""}</p>
      <div class="table-scroll"><table class="choice-table"><thead><tr><th>Credited to</th><th class="num">Its points</th><th class="num">Household points</th><th class="num">Household pension / month</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint">Points from Kindererziehungszeit are capped at the contribution ceiling together with salary, so they are worth less to a high earner who keeps working. The credit goes to the mother unless you both declare otherwise to the Deutsche Rentenversicherung; the declaration counts for future months and up to 2 months back (§ 56 Abs. 2 SGB VI). The Kinderberücksichtigungszeit up to age 10 follows the same choice (§ 57).${k.excluded.length ? ` ${k.excluded.map(esc).join(", ")} cannot get it as a civil servant (§ 56 Abs. 4).` : ""} The points belong to that parent personally.</p></section>`;
  }

  // child's health insurance
  const c = s.child_insurance;
  const health = `<section class="choice"><h3>The child's health insurance</h3>
    <p class="pick">${c.suggested === null || c.suggested === undefined ? "" : dot(c.suggested)}${esc(c.text)}</p>
    <p class="hint">Who receives the Kindergeld changes nothing for pension or health insurance. The childless surcharge to care insurance ends for every statutory-insured parent of the child either way (§ 55 Abs. 3 SGB XI).</p></section>`;

  // tax class
  const t = s.tax_class;
  let tax;
  if (!t.applicable) {
    tax = `<section class="choice"><h3>Tax class</h3><p class="pick">Nothing to choose: tax classes III, IV and V are only for married couples and registered partners. Unmarried parents stay in class I; a single parent living alone with the child gets class II (relief for single parents, § 24b EStG).</p></section>`;
  } else {
    const best = t.options.find((o) => o.classes.join() === t.best.join());
    const rows = t.options.map((o) => `<tr${o === best ? ' class="best"' : ""}><th>${r.parents.map((_, i) => `${dot(i)}${className(o.classes[i])}`).join(" / ")}${o.current ? " <small>now</small>" : ""}</th>
      <td class="num">${eur(o.elterngeld_total)}</td>
      <td class="num ${Number(o.difference) > 0 ? "pos" : Number(o.difference) < 0 ? "neg" : ""}">${o.current ? "–" : `${Number(o.difference) > 0 ? "+" : ""}${eur(o.difference)}`}</td>
      <td class="num">${eur(o.net_pay_now_per_month)}</td></tr>`).join("");
    const deadline = t.deadline ? new Date(t.deadline).toLocaleDateString("de-DE") : null;
    const verdict = t.keep_current
      ? "Keep your current classes: no other combination raises the Elterngeld for this month plan."
      : t.too_late
        ? `${r.parents.map((_, i) => `${label(i)} ${className(best.classes[i])}`).join(" / ")} would have brought ${eur(best.difference)} more Elterngeld, but the deadline (${deadline}) has passed for this child.`
        : `Switch to ${r.parents.map((_, i) => `${label(i)} ${className(best.classes[i])}`).join(" / ")}: ${eur(best.difference)} more Elterngeld for this month plan. Apply to the Finanzamt by ${deadline}.`;
    tax = `<section class="choice"><h3>Tax class – for the Elterngeld</h3>
      <p class="pick">${verdict}</p>
      <div class="table-scroll"><table class="choice-table"><thead><tr><th>Classes</th><th class="num">Elterngeld, this plan</th><th class="num">Difference</th><th class="num">Net pay now / month</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint">Elterngeld uses the class held in most of the 12 months before birth (Mutterschutz months excluded), so the parent who takes more Elterngeld months gains from class III (§ 2c Abs. 3 BEEG). The total income tax for the year stays the same: III/V only shifts it between the payslips and makes a tax return mandatory. "Net pay now" is the household's estimated take-home pay per month before the birth. After the birth the class no longer changes the Elterngeld, so you can switch to whatever suits your cash flow – but Elterngeld raises the tax rate on other income (§ 32b EStG), so expect a back-payment with the tax return.${t.plan_valid ? "" : " The month plan has errors, so these totals are provisional."}</p></section>`;
  }
  return `<div class="card social choices" id="choices"><h2>Who takes what</h2>
    <p class="hint">Suggestions based on your numbers and the month plan above. They change when you change the plan.</p>
    ${kez}${health}${tax}</div>`;
}

function socialCards(r) {
  if (!r.social) return "";
  return vacationCard(r) + pensionCard(r) + healthCard(r) + choicesCard(r);
}

const GROUPS = [
  ["eligibility", "How to get below the income cap"],
  ["amount", "How to get more Elterngeld"],
  ["process", "What to do next"],
  ["info", "Good to know"],
];
const CONF = { exact: "Exact", estimate: "Estimate", qualitative: "General" };

function recs(r) {
  return GROUPS.map(([key, title]) => {
    const list = r.recommendations.filter((x) => x.category === key);
    if (!list.length) return "";
    return `<div class="card"><h2>${title}</h2>${list.map((x) => `<div class="rec">
      <h3>${esc(x.title)}</h3>
      <p>${esc(x.detail)}</p>
      ${x.caveats.length ? `<ul>${x.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      <p class="meta"><span class="badge ${x.confidence}">${CONF[x.confidence]}</span>${x.impact_eur ? `<span class="impact">${eur(x.impact_eur, false)}</span>` : ""}${x.deadline ? `<span>Deadline ${new Date(x.deadline).toLocaleDateString("de-DE")}</span>` : ""}<span>${esc(x.legal_basis)}</span></p>
    </div>`).join("")}</div>`;
  }).join("");
}

function render(r) {
  window.__lastResult = r;
  $("#plan-section").innerHTML = planner(r) + socialCards(r);
  $("#results").innerHTML = verdict(r) + amounts(r) + mutterschutz(r) + `<p class="plan-link"><a href="#plan">Plan months, hours and Elternzeit below</a></p>` + recs(r) +
    `<p class="hint">Calculated with the official BMF Lohnsteuer program ${r.scope.tax_year_before_birth}, average KV-Zusatzbeitrag ${String(r.scope.kv_zusatzbeitrag_used_pct).replace(".", ",")} %. This is not legal or tax advice; the Elterngeldstelle decides.</p>`;
  refreshNav();
}

/* ---------- top navigation: available sections and scroll spy ---------- */
const navLinks = $$(".topnav-links a");
function markCurrentSection() {
  const live = navLinks.filter((a) => !a.hasAttribute("aria-disabled"));
  const atBottom = innerHeight + scrollY >= document.documentElement.scrollHeight - 4;
  // on wide screens the result column is sticky beside the form: both count as one section
  const sideBySide = getComputedStyle($("#results")).position === "sticky";
  const top = (a) => document.getElementById(sideBySide && a.hash === "#results" ? "form" : a.hash.slice(1)).getBoundingClientRect().top;
  const line = Math.max(120, innerHeight * 0.3);
  const passed = live.filter((a) => top(a) <= line);
  const current = atBottom && scrollY > 0 ? live.at(-1) : passed.at(-1) || live[0];
  const pair = sideBySide && ["#form", "#results"].includes(current?.hash) ? ["#form", "#results"] : [current?.hash];
  navLinks.forEach((a) => (pair.includes(a.hash) && live.includes(a) ? a.setAttribute("aria-current", "true") : a.removeAttribute("aria-current")));
}
function refreshNav() {
  navLinks.forEach((a) => {
    const target = document.getElementById(a.hash.slice(1));
    const ready = target && (!a.hasAttribute("data-needs-result") || !$(".empty", document.getElementById("results")));
    a.toggleAttribute("aria-disabled", !ready);
    a.tabIndex = ready ? 0 : -1;
  });
  markCurrentSection();
}
let navFrame;
addEventListener("scroll", () => {
  cancelAnimationFrame(navFrame);
  navFrame = requestAnimationFrame(markCurrentSection);
}, { passive: true });
$(".topnav-links").addEventListener("click", (e) => {
  if (e.target.closest("a[aria-disabled]")) e.preventDefault();
});
refreshNav();

/* ---------- theme switch: automatic → light → dark ---------- */
const THEMES = ["auto", "light", "dark"];
const THEME_NAMES = { auto: "Auto", light: "Light", dark: "Dark" };
function applyTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const btn = $("#theme-switch");
  btn.dataset.mode = t;
  $(".theme-name", btn).textContent = THEME_NAMES[t];
  btn.setAttribute("aria-label", `Theme: ${THEME_NAMES[t].toLowerCase()}. Switch theme`);
}
applyTheme(document.documentElement.dataset.theme || "auto");
$("#theme-switch").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf($("#theme-switch").dataset.mode) + 1) % THEMES.length];
  applyTheme(next);
  try {
    if (next === "auto") localStorage.removeItem("theme");
    else localStorage.setItem("theme", next);
  } catch { /* the choice then lasts for this page view only */ }
});
