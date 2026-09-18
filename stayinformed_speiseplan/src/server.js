"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const express = require("express");
const { chromium } = require("playwright");
const { WEEKDAYS, parseLunchPlanPdf } = require("./pdf-parser");

const PORT = 8099;
const DATA_DIR = "/data";
const SHARE_DIR = "/share";
const OPTIONS_FILE = path.join(DATA_DIR, "options.json");
const SETTINGS_FILE = path.join(DATA_DIR, "settings.json");
const PLANS_FILE = path.join(DATA_DIR, "parsed-plans.json");
const BROWSER_PROFILE = path.join(DATA_DIR, "browser-profile");
const LUNCH_URL = "https://app.stayinformed.de/lunch-plans";
const HOME_ASSISTANT_API = "http://supervisor/core/api";

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "32kb" }));

let settings = {
  email: "",
  password: "",
  interval_hours: 6,
  download_directory: "Kindergarten/Speiseplan",
};

let status = {
  state: "waiting_for_settings",
  message: "Bitte Zugangsdaten speichern.",
  running: false,
  last_check: null,
  next_check: null,
  found: 0,
  downloaded: 0,
  unchanged: 0,
  home_assistant: "noch nicht aktualisiert",
  plans: [],
};

let timer = null;
let stateRefreshTimer = null;
let runningPromise = null;

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

async function readJson(file, fallback = {}) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") {
      log(`Konfiguration konnte nicht gelesen werden: ${error.message}`);
    }
    return fallback;
  }
}

function normalizedSettings(input, previous = settings) {
  const interval = Number.parseInt(input.interval_hours, 10);
  return {
    email: String(input.email ?? previous.email ?? "").trim(),
    password:
      typeof input.password === "string" && input.password.length > 0
        ? input.password
        : String(previous.password ?? ""),
    interval_hours:
      Number.isFinite(interval) && interval >= 1 && interval <= 168
        ? interval
        : 6,
    download_directory: String(
      input.download_directory ??
        previous.download_directory ??
        "Kindergarten/Speiseplan",
    ).trim(),
  };
}

async function loadSettings() {
  const options = await readJson(OPTIONS_FILE);
  const saved = await readJson(SETTINGS_FILE);
  settings = normalizedSettings({ ...options, ...saved }, settings);
}

async function saveSettings(next) {
  settings = normalizedSettings(next, settings);
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(SETTINGS_FILE, JSON.stringify(settings, null, 2), {
    mode: 0o600,
  });
}

function configured() {
  return Boolean(settings.email && settings.password);
}

function resolveDownloadDirectory() {
  const relative = settings.download_directory
    .replace(/\\/g, "/")
    .replace(/^\/+/, "");
  const resolved = path.resolve(SHARE_DIR, relative);
  if (resolved !== SHARE_DIR && !resolved.startsWith(`${SHARE_DIR}${path.sep}`)) {
    throw new Error("Der Downloadordner muss innerhalb von /share liegen.");
  }
  return resolved;
}

function safeName(value) {
  return String(value || "Speiseplan")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 100) || "Speiseplan";
}

function datePart(value) {
  if (!value) return "ohne_Datum";
  const match = String(value).match(/\d{4}-\d{2}-\d{2}/);
  if (match) return match[0];
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "ohne_Datum";
  return parsed.toISOString().slice(0, 10);
}

function itemList(payload) {
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.data?.items)) return payload.data.items;
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
}

function quoteAttribute(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

async function sameContent(file, buffer) {
  try {
    const existing = await fs.readFile(file);
    return crypto.createHash("sha256").update(existing).digest("hex") ===
      crypto.createHash("sha256").update(buffer).digest("hex");
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

function addDays(dateString, amount) {
  const value = new Date(`${dateString}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + amount);
  return value.toISOString().slice(0, 10);
}

function berlinToday() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function mondayOfWeek(dateString) {
  const value = new Date(`${dateString}T12:00:00Z`);
  const day = value.getUTCDay();
  return addDays(dateString, -((day + 6) % 7));
}

function formatGermanDate(dateString) {
  const [year, month, day] = String(dateString).split("-");
  return year && month && day ? `${day}.${month}.${year}` : "–";
}

function isoWeekNumber(dateString) {
  const value = new Date(`${dateString}T12:00:00Z`);
  const dayNumber = value.getUTCDay() || 7;
  value.setUTCDate(value.getUTCDate() + 4 - dayNumber);
  const yearStart = new Date(Date.UTC(value.getUTCFullYear(), 0, 1));
  return Math.ceil(((value - yearStart) / 86_400_000 + 1) / 7);
}

function planForWeek(plans, weekStart) {
  const weekEnd = addDays(weekStart, 6);
  return (
    plans
      .filter(
        (plan) =>
          plan.start_date <= weekEnd &&
          plan.end_date >= weekStart,
      )
      .sort((left, right) =>
        String(right.parsed_at || "").localeCompare(String(left.parsed_at || "")),
      )[0] || null
  );
}

async function loadPlanArchive() {
  const stored = await readJson(PLANS_FILE, { plans: [] });
  return Array.isArray(stored) ? stored : Array.isArray(stored.plans) ? stored.plans : [];
}

async function mergePlanArchive(parsedPlans) {
  const existing = await loadPlanArchive();
  const byRange = new Map(
    existing.map((plan) => [`${plan.start_date}_${plan.end_date}`, plan]),
  );
  const handledThisScan = new Set();

  for (const plan of parsedPlans) {
    const key = `${plan.start_date}_${plan.end_date}`;
    if (handledThisScan.has(key)) continue;
    handledThisScan.add(key);
    byRange.set(key, plan);
  }

  const plans = [...byRange.values()]
    .filter((plan) => plan.start_date && plan.end_date)
    .sort((left, right) => left.start_date.localeCompare(right.start_date))
    .slice(-104);

  await fs.writeFile(
    PLANS_FILE,
    JSON.stringify({ plans }, null, 2),
    { mode: 0o600 },
  );
  return plans;
}

function emptyDayValues() {
  return Object.fromEntries(
    WEEKDAYS.map((day) => [day, "Kein Speiseplan veröffentlicht"]),
  );
}

function entityPayload(plan, weekStart, label) {
  const fallbackEnd = addDays(weekStart, 4);
  const startDate = plan?.start_date || weekStart;
  const endDate = plan?.end_date || fallbackEnd;
  const range = `${formatGermanDate(startDate)} - ${formatGermanDate(endDate)}`;
  const days = plan?.days || emptyDayValues();

  return {
    state: plan ? "vorhanden" : "nicht veröffentlicht",
    attributes: {
      friendly_name: `Kindergarten-Speiseplan ${label}`,
      icon: "mdi:food",
      vorhanden: Boolean(plan),
      woche: `KW ${isoWeekNumber(weekStart)} (${range})`,
      zeitraum: range,
      start_date: startDate,
      end_date: endDate,
      montag: days.montag || "Kein Essen angegeben",
      dienstag: days.dienstag || "Kein Essen angegeben",
      mittwoch: days.mittwoch || "Kein Essen angegeben",
      donnerstag: days.donnerstag || "Kein Essen angegeben",
      freitag: days.freitag || "Kein Essen angegeben",
      hinweise: Array.isArray(plan?.notes) ? plan.notes.join(" ") : "",
      quell_datei: plan?.source_file || null,
      zuletzt_ausgewertet: plan?.parsed_at || null,
      zuletzt_geprüft: status.last_check,
    },
  };
}

async function publishEntity(entityId, payload) {
  const token = process.env.SUPERVISOR_TOKEN;
  if (!token) {
    throw new Error("Home-Assistant-Zugriff ist für die App nicht verfügbar.");
  }

  const response = await fetch(`${HOME_ASSISTANT_API}/states/${entityId}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(
      `Home Assistant meldete beim Aktualisieren von ${entityId} Status ${response.status}.`,
    );
  }
}

async function publishHomeAssistantState(plans = null) {
  const archive = plans || (await loadPlanArchive());
  const currentWeek = mondayOfWeek(berlinToday());
  const nextWeek = addDays(currentWeek, 7);
  const currentPlan = planForWeek(archive, currentWeek);
  const nextPlan = planForWeek(archive, nextWeek);

  await Promise.all([
    publishEntity(
      "sensor.kindergarten_speiseplan_aktuell",
      entityPayload(currentPlan, currentWeek, "aktuelle Woche"),
    ),
    publishEntity(
      "sensor.kindergarten_speiseplan_naechste_woche",
      entityPayload(nextPlan, nextWeek, "nächste Woche"),
    ),
  ]);

  status.home_assistant = currentPlan || nextPlan
    ? "Sensoren aktualisiert"
    : "Sensoren geleert; für aktuelle und nächste Woche liegt kein Plan vor";
  return { currentPlan, nextPlan };
}

async function isLoginPage(page) {
  const email = page.locator('input[type="email"], input[name="username"]').first();
  return (
    page.url().startsWith("https://login.stayinformed.de/") ||
    (await email.isVisible().catch(() => false))
  );
}

function isLunchListResponse(response) {
  return (
    response.request().method() === "POST" &&
    response.url().includes("/lunch-plans/list")
  );
}

async function waitForListOrLogin(page, getListResponse, timeoutMs) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    if (getListResponse()) return "list";
    if (await isLoginPage(page)) return "login";
    await page.waitForTimeout(250);
  }

  return "timeout";
}

async function waitForCapturedResponse(page, getResponse, timeoutMs) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const response = getResponse();
    if (response) return response;
    await page.waitForTimeout(250);
  }

  return null;
}

async function loginIfNeeded(page) {
  if (!(await isLoginPage(page))) return false;

  log("Stay-Informed-Anmeldung wird ausgeführt.");
  const email = page.locator('input[type="email"], input[name="username"]').first();
  const password = page.locator('input[type="password"]').first();

  await email.waitFor({ state: "visible", timeout: 30_000 });
  await email.fill(settings.email);
  await password.fill(settings.password);

  const submit = page.getByRole("button", { name: /Anmelden|Login|Sign in/i }).first();
  await submit.click();

  try {
    await page.waitForURL(/^https:\/\/app\.stayinformed\.de\//, {
      timeout: 60_000,
      waitUntil: "domcontentloaded",
    });
  } catch {
    throw new Error(
      "Die Stay-Informed-Anmeldung wurde nicht angenommen. Bitte E-Mail-Adresse und Passwort prüfen.",
    );
  }

  return true;
}

async function acquireList(page) {
  let listResponse = null;
  const captureListResponse = (response) => {
    if (isLunchListResponse(response)) listResponse = response;
  };

  page.on("response", captureListResponse);

  try {
    await page.goto(LUNCH_URL, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    let pageState = await waitForListOrLogin(
      page,
      () => listResponse,
      30_000,
    );

    if (pageState === "login") {
      await loginIfNeeded(page);
      pageState = await waitForListOrLogin(
        page,
        () => listResponse,
        35_000,
      );
    }

    if (pageState !== "list") {
      listResponse = null;

      if (await isLoginPage(page)) {
        await loginIfNeeded(page);
      }

      if (page.url().startsWith(LUNCH_URL)) {
        await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
      } else {
        await page.goto(LUNCH_URL, {
          waitUntil: "domcontentloaded",
          timeout: 60_000,
        });
      }

      pageState = await waitForListOrLogin(
        page,
        () => listResponse,
        60_000,
      );
    }

    if (pageState === "login") {
      throw new Error(
        "Stay Informed hat erneut die Anmeldeseite geöffnet. Bitte Zugangsdaten prüfen.",
      );
    }

    if (!listResponse) {
      throw new Error(
        "Stay Informed hat keine Speiseplanliste geliefert. Die Seite wird bei der nächsten Prüfung erneut geladen.",
      );
    }

    if (!listResponse.ok()) {
      throw new Error(
        `Die Speiseplanliste antwortete mit Status ${listResponse.status()}.`,
      );
    }

    return itemList(await listResponse.json());
  } finally {
    page.off("response", captureListResponse);
  }
}

async function downloadPlan(page, item, index, directory) {
  const title = String(item.title || `Speiseplan_${index + 1}`);
  const selector = `.v-list-item[aria-label="${quoteAttribute(title)}"]`;
  let candidates = page.locator(selector);
  let count = await candidates.count();
  if (count === 0) {
    throw new Error(`Der Eintrag „${title}“ wurde auf der Seite nicht gefunden.`);
  }

  let card = candidates.nth(Math.min(index, count - 1));
  await card.scrollIntoViewIfNeeded();

  let pdfResponse = null;
  const capturePdfResponse = (response) => {
    if (
      response.request().method() === "POST" &&
      response.url().includes("/lunch-plans/pdf")
    ) {
      pdfResponse = response;
    }
  };

  page.on("response", capturePdfResponse);

  try {
    await card.click();
    pdfResponse = await waitForCapturedResponse(
      page,
      () => pdfResponse,
      35_000,
    );

    if (!pdfResponse) {
      log(`PDF-Abruf für „${title}“ wird nach einem Neuladen einmal wiederholt.`);
      await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
      candidates = page.locator(selector);
      await candidates.first().waitFor({ state: "visible", timeout: 60_000 });
      count = await candidates.count();
      card = candidates.nth(Math.min(index, count - 1));
      pdfResponse = null;
      await card.click();
      pdfResponse = await waitForCapturedResponse(
        page,
        () => pdfResponse,
        60_000,
      );
    }
  } finally {
    page.off("response", capturePdfResponse);
  }

  if (!pdfResponse) {
    throw new Error(
      `Stay Informed hat die PDF für „${title}“ nicht geliefert.`,
    );
  }

  const response = pdfResponse;
  if (!response.ok()) {
    throw new Error(`PDF-Abruf für „${title}“ meldete Status ${response.status()}.`);
  }

  const buffer = await response.body();
  if (buffer.length < 5 || buffer.subarray(0, 5).toString() !== "%PDF-") {
    throw new Error(`„${title}“ wurde nicht als gültige PDF geliefert.`);
  }

  const filename = [datePart(item.start), datePart(item.end), safeName(title)].join("_") + ".pdf";
  const target = path.join(directory, filename);
  const unchanged = await sameContent(target, buffer);
  if (!unchanged) {
    await fs.writeFile(target, buffer);
  }

  const parsed = await parseLunchPlanPdf(buffer, {
    title,
    start: item.start,
    end: item.end,
  });
  const sourceHash = crypto.createHash("sha256").update(buffer).digest("hex");
  const { extracted_lines: _extractedLines, ...parsedPlan } = parsed;

  return {
    title,
    start: parsed.start_date,
    end: parsed.end_date,
    file: target,
    result: unchanged ? "unverändert" : "gespeichert",
    analysis: "ausgewertet",
    parsed: {
      ...parsedPlan,
      source_file: target,
      source_hash: sourceHash,
      parsed_at: new Date().toISOString(),
    },
  };
}

async function performScan() {
  if (!configured()) {
    status = {
      ...status,
      state: "waiting_for_settings",
      message: "Bitte E-Mail-Adresse und Passwort speichern.",
      running: false,
    };
    return status;
  }

  status = {
    ...status,
    state: "running",
    message: "Stay Informed wird geprüft …",
    running: true,
  };

  let context;
  try {
    const directory = resolveDownloadDirectory();
    await fs.mkdir(directory, { recursive: true });
    await fs.mkdir(BROWSER_PROFILE, { recursive: true });

    context = await chromium.launchPersistentContext(BROWSER_PROFILE, {
      headless: true,
      args: ["--disable-dev-shm-usage", "--no-sandbox"],
      locale: "de-DE",
    });

    const pages = context.pages();
    const page = pages[0] || (await context.newPage());
    page.setDefaultTimeout(30_000);
    page.on("popup", (popup) => popup.close().catch(() => {}));

    const items = await acquireList(page);
    const plans = [];
    const parsedPlans = [];
    let downloaded = 0;
    let unchanged = 0;

    for (let index = 0; index < items.length; index += 1) {
      const result = await downloadPlan(page, items[index], index, directory);
      parsedPlans.push(result.parsed);
      plans.push({
        title: result.title,
        start: result.start,
        end: result.end,
        file: result.file,
        result: result.result,
        analysis: result.analysis,
      });
      if (result.result === "gespeichert") downloaded += 1;
      else unchanged += 1;
    }

    const archive = await mergePlanArchive(parsedPlans);
    status.last_check = new Date().toISOString();
    await publishHomeAssistantState(archive);

    status = {
      ...status,
      state: "success",
      message:
        items.length === 0
          ? "Zurzeit sind keine Speisepläne vorhanden; Home Assistant wurde aktualisiert."
          : `${items.length} Speiseplan/Pläne geprüft, ${downloaded} neu gespeichert und ${parsedPlans.length} ausgewertet.`,
      running: false,
      last_check: status.last_check,
      found: items.length,
      downloaded,
      unchanged,
      plans,
    };
    log(status.message);
  } catch (error) {
    status = {
      ...status,
      state: "error",
      message: error.message || String(error),
      running: false,
      last_check: new Date().toISOString(),
    };
    log(`Prüfung fehlgeschlagen: ${status.message}`);
  } finally {
    if (context) await context.close().catch(() => {});
    updateNextCheck();
  }

  return status;
}

function updateNextCheck() {
  status.next_check = configured()
    ? new Date(Date.now() + settings.interval_hours * 60 * 60 * 1000).toISOString()
    : null;
}

function runScan() {
  if (!runningPromise) {
    runningPromise = performScan().finally(() => {
      runningPromise = null;
    });
  }
  return runningPromise;
}

function schedule() {
  if (timer) clearInterval(timer);
  if (stateRefreshTimer) clearInterval(stateRefreshTimer);
  updateNextCheck();
  timer = setInterval(runScan, settings.interval_hours * 60 * 60 * 1000);
  stateRefreshTimer = setInterval(() => {
    publishHomeAssistantState().catch((error) => {
      status.home_assistant = `Fehler: ${error.message}`;
      log(`Home-Assistant-Sensoren konnten nicht aktualisiert werden: ${error.message}`);
    });
  }, 15 * 60 * 1000);
}

function publicSettings() {
  return {
    email: settings.email,
    has_password: Boolean(settings.password),
    interval_hours: settings.interval_hours,
    download_directory: settings.download_directory,
  };
}

app.get("/api/status", (_request, response) => {
  response.json({ status, settings: publicSettings() });
});

app.post("/api/settings", async (request, response) => {
  try {
    await saveSettings(request.body || {});
    schedule();
    response.json({ ok: true, settings: publicSettings() });
    setTimeout(runScan, 250);
  } catch (error) {
    response.status(400).json({ ok: false, message: error.message });
  }
});

app.post("/api/run", (_request, response) => {
  if (!configured()) {
    response.status(400).json({ ok: false, message: "Bitte zuerst Zugangsdaten speichern." });
    return;
  }
  response.status(202).json({ ok: true });
  setTimeout(runScan, 50);
});

app.get("/", (_request, response) => {
  response.type("html").send(`<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Stay Informed Speiseplan</title>
  <style>
    :root{color-scheme:light;font-family:Inter,system-ui,-apple-system,sans-serif;background:#f4f6fb;color:#17213a}
    *{box-sizing:border-box}body{margin:0;padding:24px}.wrap{max-width:880px;margin:auto}.hero{background:linear-gradient(135deg,#1a44fd,#5272ff);color:#fff;padding:28px;border-radius:22px;box-shadow:0 12px 32px #1a44fd33}.hero h1{margin:0 0 8px;font-size:28px}.hero p{margin:0;opacity:.9}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.card{background:#fff;border:1px solid #e3e7f1;border-radius:18px;padding:22px;box-shadow:0 6px 20px #22305a0b}.wide{grid-column:1/-1}h2{font-size:18px;margin:0 0 16px}.state{display:flex;gap:10px;align-items:center}.dot{width:12px;height:12px;border-radius:50%;background:#aab2c5}.running .dot{background:#f5a623}.success .dot{background:#21a366}.error .dot{background:#d93d4c}.waiting_for_settings .dot{background:#718096}.message{font-weight:650}.meta{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.metric{background:#f6f8fd;border-radius:12px;padding:12px}.metric span{display:block;color:#68738d;font-size:12px}.metric strong{font-size:22px}label{display:block;font-size:13px;color:#526078;margin:12px 0 6px}input{width:100%;border:1px solid #ccd3e2;border-radius:10px;padding:11px 12px;font:inherit}button{border:0;border-radius:10px;padding:11px 16px;font:inherit;font-weight:650;cursor:pointer}.primary{background:#1a44fd;color:white}.secondary{background:#eaf0ff;color:#173ecb}.actions{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}.small{font-size:12px;color:#6c7891;margin-top:8px}.plans{margin:0;padding:0;list-style:none}.plans li{padding:12px 0;border-bottom:1px solid #edf0f5}.plans li:last-child{border:0}.file{font-size:12px;color:#68738d;word-break:break-all}.toast{margin-top:12px;color:#b42318;min-height:20px}@media(max-width:720px){body{padding:14px}.grid{grid-template-columns:1fr}.wide{grid-column:auto}.meta{grid-template-columns:1fr}}
  </style>
</head>
<body>
<main class="wrap">
  <section class="hero"><h1>Stay Informed Speiseplan</h1><p>Prüft automatisch auf neue Kita-Speisepläne und speichert die PDFs in Home Assistant.</p></section>
  <div class="grid">
    <section class="card">
      <h2>Status</h2>
      <div id="state" class="state"><span class="dot"></span><span id="message" class="message">Wird geladen …</span></div>
      <div class="meta"><div class="metric"><span>Gefunden</span><strong id="found">–</strong></div><div class="metric"><span>Neu</span><strong id="downloaded">–</strong></div><div class="metric"><span>Unverändert</span><strong id="unchanged">–</strong></div></div>
      <div class="small">Letzte Prüfung: <span id="last">–</span><br>Nächste Prüfung: <span id="next">–</span><br>Home Assistant: <span id="ha">–</span></div>
      <div class="actions"><button id="run" class="secondary">Jetzt prüfen</button></div>
    </section>
    <section class="card">
      <h2>Einstellungen</h2>
      <form id="settings">
        <label for="email">E-Mail-Adresse</label><input id="email" type="email" autocomplete="username" required>
        <label for="password">Passwort</label><input id="password" type="password" autocomplete="current-password" placeholder="Unverändert lassen">
        <label for="interval">Prüfintervall in Stunden</label><input id="interval" type="number" min="1" max="168" required>
        <label for="directory">Ordner innerhalb von /share</label><input id="directory" required>
        <div class="actions"><button class="primary" type="submit">Speichern und prüfen</button></div>
        <div id="toast" class="toast"></div>
      </form>
    </section>
    <section class="card wide"><h2>Gefundene Dateien</h2><ul id="plans" class="plans"><li>Noch keine Prüfung durchgeführt.</li></ul></section>
  </div>
</main>
<script>
const $=id=>document.getElementById(id);let initialized=false;
const fmt=value=>value?new Date(value).toLocaleString('de-DE'):'–';
async function refresh(){
  const data=await fetch('api/status').then(r=>r.json());const s=data.status,c=data.settings;
  $('state').className='state '+s.state;$('message').textContent=s.message;$('found').textContent=s.found;$('downloaded').textContent=s.downloaded;$('unchanged').textContent=s.unchanged;$('last').textContent=fmt(s.last_check);$('next').textContent=fmt(s.next_check);$('ha').textContent=s.home_assistant||'–';$('run').disabled=s.running;
  if(!initialized){$('email').value=c.email||'';$('interval').value=c.interval_hours;$('directory').value=c.download_directory;$('password').placeholder=c.has_password?'Gespeichertes Passwort bleibt erhalten':'Passwort eingeben';initialized=true}
  $('plans').innerHTML=s.plans.length?s.plans.map(p=>'<li><strong>'+esc(p.title)+'</strong> · '+esc(p.result)+' · '+esc(p.analysis||'nicht ausgewertet')+'<div class="file">'+esc(p.file)+'</div></li>').join(''):'<li>Keine Dateien gefunden.</li>';
}
function esc(v){const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML}
$('settings').addEventListener('submit',async e=>{e.preventDefault();$('toast').textContent='';const body={email:$('email').value,password:$('password').value,interval_hours:$('interval').value,download_directory:$('directory').value};const r=await fetch('api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();$('toast').textContent=data.ok?'Gespeichert. Die Prüfung läuft jetzt.':data.message;$('password').value='';setTimeout(refresh,500)});
$('run').addEventListener('click',async()=>{const r=await fetch('api/run',{method:'POST'});const data=await r.json();if(!data.ok)$('toast').textContent=data.message;setTimeout(refresh,300)});
refresh().catch(()=>{});setInterval(()=>refresh().catch(()=>{}),3000);
</script>
</body>
</html>`);
});

async function start() {
  await loadSettings();
  schedule();
  app.listen(PORT, "0.0.0.0", () => {
    log(`Weboberfläche läuft auf Port ${PORT}.`);
    setTimeout(() => {
      publishHomeAssistantState().catch((error) => {
        status.home_assistant = `Fehler: ${error.message}`;
        log(`Home-Assistant-Sensoren konnten nicht aktualisiert werden: ${error.message}`);
      });
    }, 3_000);
    if (configured()) setTimeout(runScan, 10_000);
  });
}

if (require.main === module) {
  start().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = {
  addDays,
  berlinToday,
  entityPayload,
  mondayOfWeek,
  planForWeek,
};
