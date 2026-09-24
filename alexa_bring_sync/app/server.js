const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { URL } = require("node:url");
const AlexaCookie = require("alexa-cookie2");
const AlexaRemote = require("alexa-remote2");
const {
  alexaItemName,
  alexaRawNameFields,
  sanitizeAlexaRaw,
  normalizeItem,
  processedItemName,
  updateAlexaCandidates,
  importPayloadForCandidate,
} = require("./sync-logic");
const { writeNotificationImages } = require("./notification-assets");
const { mobileAppNotifyTargets, notificationPayload, targetItemAlreadyKnown, targetItemAlreadyNotified } = require("./notification-routing");

const APP_PORT = 8154;
// The Amazon proxy temporarily takes over the app port during login. This
// avoids a second host-port allocation, which can collide with another app.
const PROXY_PORT = APP_PORT;
const DATA_DIR = "/data";
const CONFIG_FILE = path.join(DATA_DIR, "config.json");
const STATE_FILE = path.join(DATA_DIR, "state.json");
const KEY_FILE = path.join(DATA_DIR, ".secret");
const VERSION = "0.6.12";
const NOTIFY_SERVICE = "notify.notify";
const FALLBACK_MOBILE_NOTIFY = "notify.mobile_app_iphone A";
const NOTIFY_TAG = "alexa-bring-sync";
const NOTIFICATION_MEDIA_DIR = "/homeassistant/www/alexa_bring_sync";
let notificationMediaAvailable = false;

const defaults = {
  amazonPage: "amazon.de",
  proxyHost: "",
  shoppingListHost: "",
  shoppingListPort: 8156,
  shoppingListToken: "",
  shoppingListId: "",
  shoppingListName: "",
  syncEnabled: true,
  alexaListId: "",
  alexaListName: "",
};

let config = loadJson(CONFIG_FILE, defaults);
config = { ...defaults, ...config };
const stateDefaults = {
  registration: null,
  auth: "not_configured",
  lastError: "",
  lastSync: null,
  lastSyncCount: 0,
  lastSyncSkipped: 0,
  totalTransferred: 0,
  syncRunning: false,
  nextLoginUrl: "",
  knownTargetItems: {},
  targetSnapshotInitialized: false,
  lastAlexaRawItems: [],
  lastAlexaRawAt: null,
  lastAlexaRawSignature: "",
  lastAlexaImportPayload: [],
  lastAlexaInterpretations: [],
  updatedAt: null,
};
let state = { ...stateDefaults, ...loadJson(STATE_FILE, {}) };
state.knownTargetItems = state.knownTargetItems || state.knownTodoItems || {};
state.targetSnapshotInitialized = state.targetSnapshotInitialized || state.todoSnapshotInitialized || false;
let remote = null;
let syncTimer = null;
let syncInFlight = false;
let loginInFlight = false;
const alexaCandidateMemory = new Map();

function loadJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function saveJson(file, value) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), { mode: 0o600 });
  fs.renameSync(temp, file);
}

function getKey() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  if (!fs.existsSync(KEY_FILE)) fs.writeFileSync(KEY_FILE, crypto.randomBytes(32), { mode: 0o600 });
  return fs.readFileSync(KEY_FILE);
}

function encrypt(value) {
  if (!value) return null;
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", getKey(), iv);
  const data = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  return `${iv.toString("base64url")}.${cipher.getAuthTag().toString("base64url")}.${data.toString("base64url")}`;
}

function decrypt(value) {
  if (!value) return null;
  try {
    const [ivText, tagText, dataText] = value.split(".");
    const decipher = crypto.createDecipheriv("aes-256-gcm", getKey(), Buffer.from(ivText, "base64url"));
    decipher.setAuthTag(Buffer.from(tagText, "base64url"));
    return JSON.parse(Buffer.concat([decipher.update(Buffer.from(dataText, "base64url")), decipher.final()]).toString("utf8"));
  } catch (error) {
    log(`Gespeicherte Alexa-Session konnte nicht entschlüsselt werden: ${error.message}`);
    return null;
  }
}

function persist() {
  saveJson(CONFIG_FILE, config);
  saveJson(STATE_FILE, { ...state, registration: state.registration ? encrypt(state.registration) : null });
}

function restoreRegistration() {
  if (state.registration && typeof state.registration === "string") state.registration = decrypt(state.registration);
}

restoreRegistration();

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  state.updatedAt = new Date().toISOString();
}

function setError(error) {
  state.lastError = error instanceof Error ? error.message : String(error);
  log(state.lastError);
  persist();
}

function publicState() {
  return {
    version: VERSION,
    auth: state.auth,
    connected: state.auth === "connected",
    lastError: state.lastError,
    lastSync: state.lastSync,
    lastSyncCount: state.lastSyncCount,
    lastSyncSkipped: state.lastSyncSkipped,
    totalTransferred: state.totalTransferred,
    syncEnabled: config.syncEnabled,
    shoppingListHost: config.shoppingListHost || config.proxyHost,
    shoppingListPort: Number(config.shoppingListPort) || 8156,
    shoppingListId: config.shoppingListId,
    shoppingListName: config.shoppingListName,
    shoppingListTokenConfigured: Boolean(config.shoppingListToken),
    amazonPage: config.amazonPage,
    proxyHost: config.proxyHost,
    alexaListId: config.alexaListId,
    alexaListName: config.alexaListName,
    loginUrl: state.nextLoginUrl || "",
    loginInFlight,
    lastAlexaRawItems: Array.isArray(state.lastAlexaRawItems) ? state.lastAlexaRawItems : [],
    lastAlexaRawAt: state.lastAlexaRawAt || null,
    lastAlexaImportPayload: Array.isArray(state.lastAlexaImportPayload) ? state.lastAlexaImportPayload : [],
    lastAlexaInterpretations: Array.isArray(state.lastAlexaInterpretations) ? state.lastAlexaInterpretations : [],
  };
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(payload);
}

function body(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 100000) reject(new Error("Anfrage ist zu groß"));
    });
    req.on("end", () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch { reject(new Error("Ungültiges JSON")); }
    });
    req.on("error", reject);
  });
}

function callbackPromise(method, ...args) {
  return new Promise((resolve, reject) => {
    method(...args, (error, result) => {
      if (error) return reject(error instanceof Error ? error : new Error(String(error)));
      resolve(result);
    });
  });
}

function makeRemote() {
  if (!state.registration) return null;
  const registration = state.registration;
  const instance = new AlexaRemote();
  return { instance, registration };
}

async function connectAlexa() {
  const client = makeRemote();
  if (!client) {
    state.auth = "not_configured";
    return false;
  }
  try {
    await new Promise((resolve, reject) => {
      client.instance.init({
        amazonPage: config.amazonPage,
        cookie: client.registration.localCookie || client.registration.cookie,
        formerRegistrationData: client.registration,
        logger: (message) => log(message),
        cookieRefreshInterval: 4 * 24 * 60 * 60 * 1000,
      }, (error) => error ? reject(error) : resolve());
    });
    remote = client.instance;
    state.auth = "connected";
    state.lastError = "";
    persist();
    log("Alexa-Session ist gültig.");
    return true;
  } catch (error) {
    remote = null;
    state.auth = "reauth_required";
    setError(`Alexa-Verbindung ungültig oder abgelaufen: ${error.message}`);
    return false;
  }
}

function startLogin(requestHost) {
  if (loginInFlight) return;
  const configuredHost = String(config.proxyHost || "").trim().replace(/^https?:\/\//, "").replace(/:\d+$/, "");
  const host = configuredHost || String(requestHost || "").split(":")[0];
  if (!host || host === "0.0.0.0" || host === "127.0.0.1" || host === "localhost") {
    throw new Error("Bitte zuerst die lokale IP-Adresse des Home-Assistant-Hosts als Proxy-Adresse eintragen.");
  }
  loginInFlight = true;
  state.auth = "waiting_for_amazon_login";
  state.nextLoginUrl = `http://${host}:${PROXY_PORT}/`;
  state.lastError = "";
  persist();
  const options = {
    amazonPage: config.amazonPage,
    proxyOwnIp: host,
    proxyPort: PROXY_PORT,
    proxyListenBind: "0.0.0.0",
    proxyOnly: true,
    setupProxy: true,
    deviceAppName: "Alexa Einkaufsliste Sync",
    formerRegistrationData: state.registration || undefined,
    proxyCloseWindowHTML: "<h2>Alexa ist verbunden.</h2><p>Dieses Fenster kann geschlossen werden.</p>",
    logger: (message) => log(message),
  };
  // The proxy library starts its own HTTP server. Stop the UI listener first;
  // otherwise both servers would race for port 8154.
  setTimeout(() => {
    stopAppServer(() => {
      AlexaCookie.generateAlexaCookie(options, (error, result) => {
        // alexa-cookie calls back once with an instructional error when the
        // manual proxy has successfully started, then again with the result
        // after Amazon login/2FA/CAPTCHA is complete.
        if (error && !result && /Please open http:\/\//i.test(error.message || "")) {
          log("Amazon-Login-Proxy läuft auf Port 8154; warte auf den manuellen Login.");
          return;
        }
        loginInFlight = false;
        state.nextLoginUrl = "";
        if (error || !result) {
          state.auth = "reauth_required";
          setError(`Amazon-Login nicht abgeschlossen: ${error ? error.message : "keine Session erhalten"}`);
          AlexaCookie.stopProxyServer(() => startAppServer());
          return;
        }
        state.registration = result;
        state.auth = "connected";
        state.lastError = "";
        state.updatedAt = new Date().toISOString();
        persist();
        AlexaCookie.stopProxyServer(() => {
          startAppServer();
          log("Amazon-Login erfolgreich abgeschlossen; Alexa-Session gespeichert.");
          connectAlexa().catch(setError);
        });
      });
    });
  }, 50);
}

async function fetchAlexaLists() {
  if (!remote) await connectAlexa();
  if (!remote) throw new Error("Alexa ist nicht verbunden.");
  return callbackPromise(remote.getListsV2.bind(remote));
}

async function selectedAlexaList() {
  const lists = await fetchAlexaLists();
  let list = lists.find((candidate) => candidate.listId === config.alexaListId);
  if (!list) list = lists.find((candidate) => candidate.listType === "SHOPPING_LIST") || lists[0];
  if (!list) throw new Error("Keine Alexa-Liste gefunden.");
  if (config.alexaListId !== list.listId || config.alexaListName !== (list.listName || list.listType || "")) {
    config.alexaListId = list.listId;
    config.alexaListName = list.listName || list.listType || "Alexa-Liste";
    persist();
  }
  return list;
}

function haRequest(endpoint, method, payload) {
  const token = process.env.SUPERVISOR_TOKEN;
  if (!token) throw new Error("SUPERVISOR_TOKEN fehlt; Home-Assistant-API ist nicht verfügbar.");
  return new Promise((resolve, reject) => {
    const request = http.request({
      hostname: "supervisor",
      port: 80,
      path: `/core/api${endpoint}`,
      method,
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      timeout: 10000,
    }, (response) => {
      let raw = "";
      response.on("data", (chunk) => { raw += chunk; });
      response.on("end", () => {
        let parsed;
        try { parsed = raw ? JSON.parse(raw) : {}; } catch { parsed = { raw }; }
        if (response.statusCode < 200 || response.statusCode >= 300) return reject(new Error(`Home Assistant API ${response.statusCode}: ${parsed.message || raw}`));
        resolve(parsed);
      });
    });
    request.on("timeout", () => request.destroy(new Error("Zeitüberschreitung bei Home Assistant")));
    request.on("error", reject);
    if (payload) request.write(JSON.stringify(payload));
    request.end();
  });
}

function shoppingListBaseUrl() {
  const raw = String(config.shoppingListHost || config.proxyHost || "").trim();
  const host = raw.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").replace(/:\d+$/, "");
  if (!host || host === "0.0.0.0" || host === "127.0.0.1" || host === "localhost") {
    throw new Error("Bitte zuerst die IP-Adresse der Home-Assistant-Instanz für die eigene Einkaufsliste eintragen.");
  }
  return `http://${host}:${Number(config.shoppingListPort) || 8156}`;
}

async function shoppingListRequest(endpoint, method = "GET", payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  const headers = { "content-type": "application/json" };
  if (config.shoppingListToken) headers["x-sync-token"] = config.shoppingListToken;
  try {
    const response = await fetch(`${shoppingListBaseUrl()}${endpoint}`, { method, headers, body: payload === undefined ? undefined : JSON.stringify(payload), signal: controller.signal });
    const raw = await response.text();
    let parsed = {};
    try { parsed = raw ? JSON.parse(raw) : {}; } catch { parsed = { raw }; }
    if (!response.ok) throw new Error(`Eigene Einkaufsliste ${response.status}: ${parsed.error || parsed.raw || "unbekannter Fehler"}`);
    return parsed;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Zeitüberschreitung bei der eigenen Einkaufsliste.");
    throw error;
  } finally { clearTimeout(timer); }
}

async function shoppingListInfo() {
  const response = await shoppingListRequest("/api/integration/lists");
  const lists = Array.isArray(response.lists) ? response.lists : [];
  const selected = lists.find((list) => list.id === config.shoppingListId) || lists.find((list) => list.id === response.syncListId) || lists[0];
  if (!selected) throw new Error("Keine Liste in der eigenen Einkaufsliste gefunden.");
  if (config.shoppingListId && config.shoppingListName !== selected.name) {
    config.shoppingListName = selected.name;
    persist();
  }
  return { ...response, selected };
}

async function getOwnListState() {
  const info = await shoppingListInfo();
  return shoppingListRequest(`/api/integration/state?listId=${encodeURIComponent(info.selected.id)}`);
}

async function importOwnItems(items) {
  const info = await shoppingListInfo();
  return shoppingListRequest("/api/integration/import", "POST", { listId: info.selected.id, items });
}

function ensureNotificationImages() {
  try {
    writeNotificationImages(NOTIFICATION_MEDIA_DIR);
    notificationMediaAvailable = true;
    log("Benachrichtigungsbilder unter /local/alexa_bring_sync bereitgestellt.");
  } catch (error) {
    log(`Benachrichtigungsbilder konnten nicht in /homeassistant/www bereitgestellt werden: ${error.message}`);
  }
}

function ownItemName(item) {
  return processedItemName(item);
}

function notificationIconUrl(kind) {
  if (kind === "added") return null;
  if (notificationMediaAvailable) return `/local/alexa_bring_sync/${kind}.png`;
  return "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/26a0.png";
}

async function notifyAllDevices(message, kind) {
  try {
    const services = await haRequest("/services", "GET");
    const targets = mobileAppNotifyTargets(services);
    // On newer HA releases the legacy mobile_app action may not be exposed in
    // the service listing even though it still works. Keep primary's known
    // Companion-App target as a direct fallback before the generic notify alias.
    const actualTargets = [...new Set(targets.length ? targets : [FALLBACK_MOBILE_NOTIFY, NOTIFY_SERVICE])];
    const payload = notificationPayload(message, kind, notificationIconUrl(kind), `${shoppingListBaseUrl()}/`);
    const errors = [];
    for (const target of actualTargets) {
      const [domain, service] = target.split(".");
      try {
        await haRequest(`/services/${domain}/${service}`, "POST", payload);
      } catch (error) {
        // A rich mobile payload should never prevent the basic text push.
        // Retry once with the minimum universally accepted notify payload.
        try {
          await haRequest(`/services/${domain}/${service}`, "POST", { title: "Einkaufsliste", message });
        } catch (retryError) {
          errors.push(`${target}: ${retryError.message}`);
        }
      }
    }
    if (errors.length === actualTargets.length) throw new Error(errors.join("; "));
    if (errors.length) log(`Push teilweise gesendet; Fehler: ${errors.join("; ")}`);
    log(`Push an ${actualTargets.length} Gerät(e) gesendet: ${message}`);
  } catch (error) {
    log(`Push konnte nicht gesendet werden: ${error.message}`);
  }
}

function targetItemKey(item, name = "") {
  const id = String(item && (item.id || item.entryId) || "").trim();
  if (id) return `id:${id}`;
  const normalizedName = normalizeItem(name || ownItemName(item));
  return normalizedName ? `name:${normalizedName}` : "";
}

function rememberTargetItem(item, name) {
  const key = targetItemKey(item, name);
  if (!key) return;
  state.knownTargetItems = { ...(state.knownTargetItems || {}), [key]: name };
}

async function notifyNewOwnItems(items) {
  const known = { ...(state.knownTargetItems || {}) };
  const newlyArrived = [];
  for (const item of items || []) {
    if (item && item.status === "completed") continue;
    const name = ownItemName(item);
    const key = targetItemKey(item, name);
    const stableId = String(item && (item.id || item.entryId) || "").trim();
    const legacyNameKey = normalizeItem(name);
    if (!key) continue;
    const alreadyKnown = targetItemAlreadyKnown(known, key, legacyNameKey, Boolean(stableId));
    if (state.targetSnapshotInitialized && !alreadyKnown && !targetItemAlreadyNotified(item)) newlyArrived.push({ item, name });
    known[key] = name;
  }
  state.knownTargetItems = known;
  const shouldNotify = state.targetSnapshotInitialized;
  state.targetSnapshotInitialized = true;
  if (shouldNotify) {
    for (const entry of newlyArrived) {
      await notifyAllDevices(`Es wurde ${entry.name} zur Einkaufsliste hinzugefügt!`, "added");
    }
  }
}

function completeAlexaItem(listId, item) {
  const value = alexaItemName(item);
  return callbackPromise(remote.updateListItem.bind(remote), listId, item.id || item.itemId, {
    value,
    version: item.version,
    completed: true,
  });
}

function recordAlexaRawItems(items, interpretations = []) {
  const snapshot = (Array.isArray(items) ? items : []).map((item, index) => ({
    position: index + 1,
    ...alexaRawNameFields(item),
    raw: sanitizeAlexaRaw(item),
  }));
  // Ein leerer Folge-Poll darf die letzte relevante Diagnose nicht auslöschen.
  // Genau das machte 0.6.6 nach dem Erledigen eines Alexa-Eintrags unbrauchbar.
  if (!snapshot.length) return;
  const signature = JSON.stringify(snapshot);
  state.lastAlexaRawItems = snapshot;
  state.lastAlexaRawAt = new Date().toISOString();
  state.lastAlexaInterpretations = interpretations;
  persist();
  if (signature === state.lastAlexaRawSignature) return;
  state.lastAlexaRawSignature = signature;
  for (const entry of snapshot) {
    log(`ALEXA_RAW [${entry.position}/${snapshot.length}]: ${JSON.stringify(entry)}`);
  }
}

async function syncOnce() {
  if (syncInFlight || !config.syncEnabled) return;
  syncInFlight = true;
  state.syncRunning = true;
  try {
    if (state.auth !== "connected") return;
    const targetState = await getOwnListState();
    await notifyNewOwnItems(targetState.entries);
    const list = await selectedAlexaList();
    // Amazon currently rejects the upper boundary 200 although the API error
    // says that 0..200 is allowed. The default/portable page size is 100.
    const alexaItems = await callbackPromise(remote.getListItemsV2.bind(remote), list.listId, { limit: 100 });
    if (!Array.isArray(alexaItems)) {
      throw new Error("Alexa-Einkaufsliste konnte nicht gelesen werden.");
    }
    const pendingItems = alexaItems.filter((item) => !item.completed && item.itemStatus !== "COMPLETE");

    // Alexa updates a spoken shopping-list entry in more than one step in some
    // cases. Example observed in practice: "Butter 10x" first, then a few
    // seconds later "Butter 4 Stück" when "Firma" was heard as "vier mal".
    // Import only after the same item has been unchanged for >=10 seconds /
    // three polls. The history of the same Alexa item is kept so that this
    // transition can be reconstructed as Butter · 10 Stück · Firma.
    const candidates = updateAlexaCandidates(alexaCandidateMemory, pendingItems, Date.now(), { minStableMs: 10000, minStablePolls: 3 });
    const interpretations = [
      ...candidates.waiting.map((candidate) => ({
        name: candidate.rawName,
        status: "wartet",
        stablePolls: candidate.stablePolls,
        history: candidate.history,
        interpretedAs: candidate.interpretation ? importPayloadForCandidate(candidate) : null,
      })),
      ...candidates.ready.map((candidate) => ({
        name: candidate.rawName,
        status: "bereit",
        stablePolls: candidate.stablePolls,
        history: candidate.history,
        interpretedAs: candidate.interpretation ? importPayloadForCandidate(candidate) : null,
      })),
    ];
    recordAlexaRawItems(pendingItems, interpretations);

    if (!candidates.ready.length) {
      state.lastSync = new Date().toISOString();
      state.lastSyncCount = 0;
      state.lastSyncSkipped = 0;
      state.lastError = "";
      log(`Synchronisation wartet auf stabile Alexa-Einträge: ${candidates.waiting.length}.`);
      return;
    }

    const importItems = candidates.ready.map(importPayloadForCandidate);
    state.lastAlexaImportPayload = importItems.map((item) => ({ ...item }));
    persist();
    log(`ALEXA_IMPORT: ${JSON.stringify(state.lastAlexaImportPayload)}`);
    const imported = await importOwnItems(importItems);
    let transferred = 0;
    let duplicates = 0;
    const failures = [];
    for (let index = 0; index < candidates.ready.length; index += 1) {
      const candidate = candidates.ready[index];
      const sourceItem = candidate.item;
      const result = imported.results?.[index];
      const name = alexaItemName(sourceItem);
      if (!result || result.status === "error") { failures.push(`${name}: ${result?.error || "keine Rückmeldung"}`); continue; }
      const processedName = processedItemName(result.entry, name);
      // Push unmittelbar nach der Antwort der Einkaufsliste senden. Er darf
      // weder auf Alexa-Erledigung noch auf Gemini-/Bildbearbeitung warten.
      if (result.status === "added") {
        rememberTargetItem(result.entry, processedName);
        await notifyAllDevices(`Es wurde ${processedName} zur Einkaufsliste hinzugefügt!`, "added");
        transferred += 1;
      } else if (result.status === "duplicate") {
        await notifyAllDevices(`${processedName} befindet sich schon auf der Einkaufsliste!`, "duplicate");
        duplicates += 1;
      }
      await completeAlexaItem(list.listId, sourceItem);
      alexaCandidateMemory.delete(candidate.key);
    }
    if (failures.length) throw new Error(`Einige Alexa-Einträge wurden nicht übernommen: ${failures.join("; ")}`);
    state.lastSync = new Date().toISOString();
    state.lastSyncCount = transferred;
    state.lastSyncSkipped = duplicates;
    state.totalTransferred += transferred;
    state.lastError = "";
    log(`Synchronisation abgeschlossen: ${transferred} übertragen, ${duplicates} Duplikate erledigt.`);
  } catch (error) {
    setError(`Synchronisation fehlgeschlagen: ${error.message}`);
    if (/Alexa|Authentication|csrf|401|403/i.test(error.message)) {
      state.auth = "reauth_required";
      remote = null;
    }
  } finally {
    state.syncRunning = false;
    syncInFlight = false;
    persist();
  }
}

async function listInfo() {
  const lists = await fetchAlexaLists();
  return lists.map((list) => ({ id: list.listId, name: list.listName || list.listType, type: list.listType }));
}

function html() {
  return `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Alexa Einkaufsliste Sync</title><style>
  :root{color-scheme:dark;--bg:#101414;--panel:#182020;--line:#2c3a38;--text:#eaf3ee;--muted:#9eb0a9;--mint:#a9e6c7;--orange:#ffb86b;--red:#ff8989}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#1b3831 0,#101414 42%);font:15px system-ui,-apple-system,Segoe UI,sans-serif;color:var(--text)}main{max-width:980px;margin:0 auto;padding:32px 18px 50px}.hero{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:24px}.eyebrow{letter-spacing:.18em;color:var(--mint);font-size:12px;text-transform:uppercase}.hero h1{font-size:clamp(28px,6vw,48px);line-height:1;margin:10px 0 0}.hero p{color:var(--muted);max-width:560px;line-height:1.5}.orb{width:86px;height:86px;border:1px solid #7ad1ad;border-radius:50%;box-shadow:0 0 0 9px #1b3831,0 0 30px #79d1ad66;display:grid;place-items:center;color:var(--mint);font-size:38px;flex:none}.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:15px}@media(max-width:740px){.grid{grid-template-columns:1fr}.hero{align-items:start}.orb{width:62px;height:62px;font-size:26px}}.card{background:#182020dd;border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 18px 45px #0003}.wide{grid-column:1/-1}.card h2{font-size:16px;margin:0 0 16px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.stat{background:#101818;border-radius:12px;padding:13px}.stat b{display:block;font-size:22px;color:var(--mint)}.stat span{color:var(--muted);font-size:12px}.status{display:flex;align-items:center;gap:10px;margin-bottom:18px}.dot{width:11px;height:11px;border-radius:50%;background:var(--orange);box-shadow:0 0 13px currentColor}.dot.ok{background:var(--mint);color:var(--mint)}.dot.bad{background:var(--red);color:var(--red)}label{display:block;color:var(--muted);font-size:12px;margin:13px 0 6px}input,select{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:#0d1313;color:var(--text);font:inherit}button{border:0;border-radius:9px;padding:11px 14px;background:var(--mint);color:#102019;font-weight:700;cursor:pointer;margin:12px 8px 0 0}button.secondary{background:#29443d;color:var(--text)}button.warn{background:var(--orange)}.hint,.error,.success{border-radius:10px;padding:11px 12px;line-height:1.45;margin-top:13px}.hint{background:#20312d;color:var(--muted)}.error{background:#3b2225;color:#ffc3c3}.success{background:#1d3a2d;color:#c9f7dd}.muted{color:var(--muted)}code{color:var(--mint)}a{color:var(--mint)}#login-link{word-break:break-all}.hidden{display:none}.footer{color:#71857c;font-size:12px;margin-top:20px}
  </style></head><body><main><section class="hero"><div><div class="eyebrow">Home Assistant App · v${VERSION}</div><h1>Alexa<br>Einkaufsliste Sync</h1><p>Die Alexa-Einkaufsliste wandert automatisch in die eigene Einkaufsliste — mit listenbezogener Duplikatprüfung, Kategorisierung und sicherem Amazon-Login.</p></div><div class="orb">↘</div></section><section class="grid"><article class="card wide"><div class="status"><span id="dot" class="dot"></span><strong id="auth">Status wird geladen …</strong><span id="syncing" class="muted"></span></div><div class="stats"><div class="stat"><b id="last-count">–</b><span>zuletzt übertragen</span></div><div class="stat"><b id="total">–</b><span>insgesamt übertragen</span></div><div class="stat"><b id="skipped">–</b><span>Duplikate erledigt</span></div></div><div id="notice"></div></article><article class="card"><h2>Amazon-Verbindung</h2><p class="muted">Der Login öffnet Amazons eigene Seite. Passwort, 2FA und CAPTCHA werden nicht in dieser App verarbeitet.</p><label for="amazon">Amazon-Land</label><select id="amazon"><option value="amazon.de">amazon.de</option><option value="amazon.com">amazon.com</option><option value="amazon.co.uk">amazon.co.uk</option><option value="amazon.at">amazon.at</option></select><label for="proxy">Home-Assistant-IP für den Login-Proxy</label><input id="proxy" placeholder="z. B. 192.168.178.20"><button id="login" class="warn">Login / Reauth starten</button><div id="login-help" class="hint hidden"></div></article><article class="card"><h2>Synchronisation</h2><label for="target-host">IP-Adresse der eigenen Einkaufsliste</label><input id="target-host" placeholder="z. B. 192.168.10.199"><label for="target-token">Sync-Schlüssel der eigenen Einkaufsliste (optional)</label><input id="target-token" type="password" placeholder="leer lassen, wenn keiner gesetzt ist"><label for="target-list">Ziel-Liste</label><select id="target-list"><option value="">wird geladen</option></select><label for="list">Alexa-Liste</label><select id="list"><option value="">wird nach Verbindung geladen</option></select><label><input type="checkbox" id="enabled" style="width:auto;margin-right:7px"> Synchronisation aktiv</label><button id="save">Einstellungen speichern</button><button id="test" class="secondary">Jetzt synchronisieren</button></article><article class="card wide"><h2>Diagnose</h2><p class="muted">Abfrage alle 5 Sekunden. Neue Alexa-Einträge und erledigte Duplikate lösen einen Push an alle Home-Assistant-Geräte aus. Ein Alexa-Eintrag wird erst dann erledigt, wenn er in der eigenen Einkaufsliste angekommen ist. Ist er dort bereits vorhanden, wird er als Duplikat übersprungen und ebenfalls erledigt.</p><div id="raw-alexa" class="hint hidden"></div><div id="error" class="error hidden"></div><div id="ok" class="success hidden"></div><p class="footer">Sessiondaten und Zugangsdaten werden unter <code>/data</code> mit einem lokal erzeugten Schlüssel geschützt gespeichert.</p></article></section></main><script>
  const $=id=>document.getElementById(id);let lastState=null;
  async function api(path, options={}){const r=await fetch(path,{headers:{'content-type':'application/json'},...options});const j=await r.json();if(!r.ok)throw new Error(j.error||'Fehler');return j}
  function show(el,text,visible){el.textContent=text;el.classList.toggle('hidden',!visible)}
  function render(s){lastState=s;$('auth').textContent={connected:'Alexa verbunden',not_configured:'Alexa noch nicht eingerichtet',reauth_required:'Reauth erforderlich',waiting_for_amazon_login:'Warte auf Amazon-Login'}[s.auth]||s.auth;$('dot').className='dot '+(s.connected?'ok':s.auth==='reauth_required'?'bad':'');$('syncing').textContent=s.syncEnabled?(s.syncRunning?'· Synchronisation läuft':'· aktiv alle 5 Sekunden'):'· pausiert';$('last-count').textContent=s.lastSyncCount;$('total').textContent=s.totalTransferred;$('skipped').textContent=s.lastSyncSkipped;$('target-host').value=s.shoppingListHost||s.proxyHost||'';$('target-list').value=s.shoppingListId||'';$('enabled').checked=s.syncEnabled;$('amazon').value=s.amazonPage;$('proxy').value=s.proxyHost||'';if(s.loginUrl){show($('login-help'),'Öffne jetzt '+s.loginUrl+' und melde dich dort bei Amazon an. Nach erfolgreichem Login wird dieses Fenster automatisch aktualisiert.',true)}else show($('login-help'),'',false);const raw=(s.lastAlexaRawItems||[]).map(x=>{const n=x.itemName||x.value||x.name||'';return n?JSON.stringify(n):JSON.stringify(x.raw||x)}).filter(Boolean);const interp=(s.lastAlexaInterpretations||[]).map(x=>{const target=x.interpretedAs?(' → '+x.interpretedAs.name+(x.interpretedAs.quantity!=null?' · '+x.interpretedAs.quantity+' '+(x.interpretedAs.unit||''):'') ):'';return x.status+': '+x.name+' ('+x.stablePolls+'/3)'+target});const sent=(s.lastAlexaImportPayload||[]).map(x=>JSON.stringify(x));const diag=[raw.length?('Alexa roh: '+raw.join(' | ')):'',interp.length?('Auswertung: '+interp.join(' | ')):'',sent.length?('Gesendet: '+sent.join(' | ')):''].filter(Boolean).join(' · ');show($('raw-alexa'),diag,!!diag);show($('error'),s.lastError,!!s.lastError);if(s.lastError)show($('ok'),'',false);}
  async function refresh(){try{const s=await api('/api/status');render(s);await loadTargetLists();if(s.connected)await loadLists()}catch(e){show($('error'),e.message,true)}}
  async function loadTargetLists(){try{const data=await api('/api/target/lists');const selected=lastState?.shoppingListId||'';$('target-list').innerHTML='<option value="">Auswahl aus eigener Einkaufsliste übernehmen</option>'+data.lists.map(x=>'<option value="'+x.id+'">'+x.name+' ('+x.itemCount+')</option>').join('');$('target-list').value=selected}catch(e){if($('target-list'))$('target-list').innerHTML='<option value="">Ziel nicht erreichbar</option>'}}
  async function loadLists(){try{const lists=await api('/api/alexa/lists');const selected=lastState?.alexaListId||'';$('list').innerHTML=lists.map(x=>'<option value="'+x.id+'">'+x.name+' ('+x.type+')</option>').join('');$('list').value=selected||lists[0]?.id||''}catch(e){}}
  $('login').onclick=async()=>{try{await api('/api/alexa/login',{method:'POST',body:JSON.stringify({})});await refresh()}catch(e){show($('error'),e.message,true)}};
  $('save').onclick=async()=>{try{await api('/api/config',{method:'POST',body:JSON.stringify({amazonPage:$('amazon').value,proxyHost:$('proxy').value,shoppingListHost:$('target-host').value,shoppingListToken:$('target-token').value,shoppingListId:$('target-list').value,alexaListId:$('list').value,syncEnabled:$('enabled').checked})});show($('ok'),'Einstellungen gespeichert.',true);await refresh()}catch(e){show($('error'),e.message,true)}};
  $('test').onclick=async()=>{try{await api('/api/sync',{method:'POST'});show($('ok'),'Synchronisation angestoßen.',true);await refresh()}catch(e){show($('error'),e.message,true)}};
  refresh();setInterval(refresh,5000);
  </script></body></html>`;
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    if (req.method === "GET" && url.pathname === "/api/status") return json(res, 200, publicState());
    if (req.method === "GET" && url.pathname === "/api/target/lists") return json(res, 200, await shoppingListInfo());
    if (req.method === "GET" && url.pathname === "/api/alexa/lists") return json(res, 200, await listInfo());
    if (req.method === "POST" && url.pathname === "/api/config") {
      const input = await body(req);
      if (input.amazonPage) config.amazonPage = String(input.amazonPage).trim();
      if (input.proxyHost !== undefined) config.proxyHost = String(input.proxyHost).trim();
      if (input.shoppingListHost !== undefined) config.shoppingListHost = String(input.shoppingListHost).trim();
      if (input.shoppingListToken !== undefined && String(input.shoppingListToken).trim()) config.shoppingListToken = String(input.shoppingListToken).trim();
      if (input.shoppingListId !== undefined) config.shoppingListId = String(input.shoppingListId).trim();
      if (input.shoppingListName !== undefined) config.shoppingListName = String(input.shoppingListName).trim();
      if (input.alexaListId !== undefined) config.alexaListId = String(input.alexaListId).trim();
      if (input.syncEnabled !== undefined) config.syncEnabled = Boolean(input.syncEnabled);
      persist();
      return json(res, 200, publicState());
    }
    if (req.method === "POST" && url.pathname === "/api/alexa/login") {
      startLogin(req.headers.host);
      return json(res, 202, publicState());
    }
    if (req.method === "POST" && url.pathname === "/api/sync") {
      if (state.auth !== "connected") return json(res, 409, { error: "Alexa ist noch nicht verbunden." });
      syncOnce();
      return json(res, 202, publicState());
    }
    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      return res.end(html());
    }
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    res.end("Nicht gefunden");
  } catch (error) {
    json(res, 400, { error: error.message });
  }
});

function startAppServer() {
  if (server.listening) return;
  server.listen(APP_PORT, "0.0.0.0", () => {
    log(`Alexa Einkaufsliste Sync ${VERSION} hört auf Port ${APP_PORT}.`);
    if (!syncTimer) syncTimer = setInterval(syncOnce, 5000);
  });
}

function stopAppServer(callback) {
  if (!server.listening) return callback();
  server.close(callback);
  if (typeof server.closeAllConnections === "function") server.closeAllConnections();
}

ensureNotificationImages();
startAppServer();
if (state.registration) connectAlexa().catch(setError);

module.exports = { server, html, publicState };

process.on("SIGTERM", () => {
  if (syncTimer) clearInterval(syncTimer);
  AlexaCookie.stopProxyServer(() => {
    if (!server.listening) return process.exit(0);
    server.close(() => process.exit(0));
    if (typeof server.closeAllConnections === "function") server.closeAllConnections();
  });
  setTimeout(() => process.exit(0), 1500).unref();
});
