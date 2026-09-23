"use strict";

// Minimaler CalDAV-Leser für genau eine Erinnerungen-Liste.  Er verwendet nur
// Standard-WebDAV-Aufrufe und speichert Zugangsdaten nie im Datenbestand.
const DAV = "DAV:";
const CALDAV = "urn:ietf:params:xml:ns:caldav";

function xmlEscape(value) {
  return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}
function xmlUnescape(value) {
  return String(value || "").replace(/&apos;/g, "'").replace(/&quot;/g, '"').replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&amp;/g, "&");
}
function tagValue(xml, tag) {
  const expression = new RegExp(`<(?:(?:[\\w.-]+):)?${tag}[^>]*>([\\s\\S]*?)<\\/(?:[\\w.-]+:)?${tag}>`, "i");
  const match = expression.exec(String(xml || ""));
  return match ? xmlUnescape(match[1].replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").trim()) : "";
}
function responseBlocks(xml) {
  return String(xml || "").match(/<(?:(?:[\w.-]+):)?response\b[^>]*>[\s\S]*?<\/(?:[\w.-]+:)?response>/gi) || [];
}
function absoluteUrl(href, base) {
  return new URL(String(href || "").trim(), base).toString();
}
function icalValue(block, property) {
  const unfolded = String(block || "").replace(/\r?\n[ \t]/g, "");
  const match = new RegExp(`^${property}(?:;[^:]*)?:(.*)$`, "im").exec(unfolded);
  return match ? match[1].replace(/\\n/gi, "\n").replace(/\\,/g, ",").replace(/\\;/g, ";").replace(/\\\\/g, "\\").trim() : "";
}
function openTodos(ical, href) {
  const blocks = String(ical || "").match(/BEGIN:VTODO[\s\S]*?END:VTODO/gi) || [];
  return blocks.map((block) => ({ id: icalValue(block, "UID") || href, name: icalValue(block, "SUMMARY"), status: icalValue(block, "STATUS").toUpperCase() }))
    .filter((item) => item.name && item.status !== "COMPLETED" && item.status !== "CANCELLED");
}

function createAppleRemindersSync({ getOptions, onItems, log = console.log }) {
  let timer = null;
  let inFlight = false;
  let cachedCalendarUrl = "";
  let status = { state: "disabled", detail: "Nicht eingerichtet", lastRunAt: null, lastSuccessAt: null, imported: 0, duplicates: 0 };

  function config() {
    const options = getOptions() || {};
    const interval = Math.max(60, Number(options.reminders_sync_interval_seconds || 60));
    return {
      enabled: Boolean(options.reminders_sync_enabled),
      serverUrl: String(options.reminders_sync_server_url || "https://caldav.icloud.com/").trim(),
      username: String(options.reminders_sync_username || "").trim(),
      password: String(options.reminders_sync_password || "").trim(),
      listName: String(options.reminders_sync_list_name || "Einkaufsliste").trim(),
      targetListId: String(options.reminders_sync_target_list_id || "supermarkt").trim(),
      intervalMs: interval * 1000,
    };
  }
  async function request(url, method, body, settings, depth = "0") {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {
        method,
        redirect: "follow",
        signal: controller.signal,
        headers: {
          authorization: `Basic ${Buffer.from(`${settings.username}:${settings.password}`, "utf8").toString("base64")}`,
          depth,
          "content-type": "application/xml; charset=utf-8",
          accept: "application/xml, text/xml, text/plain",
        },
        body,
      });
      const text = await response.text();
      if (!response.ok && response.status !== 207) throw new Error(`CalDAV-Antwort ${response.status}`);
      return { text, url: response.url || url };
    } finally { clearTimeout(timeout); }
  }
  async function propfind(url, body, settings, depth = "0") { return request(url, "PROPFIND", body, settings, depth); }
  function hrefInProperty(xml, property) {
    const scope = new RegExp(`<(?:(?:[\\w.-]+):)?${property}[^>]*>([\\s\\S]*?)<\\/(?:[\\w.-]+:)?${property}>`, "i").exec(xml);
    return scope ? tagValue(scope[1], "href") : "";
  }
  async function discoverCalendar(settings) {
    if (cachedCalendarUrl) return cachedCalendarUrl;
    const principalResponse = await propfind(settings.serverUrl, `<?xml version="1.0"?><d:propfind xmlns:d="${DAV}"><d:prop><d:current-user-principal/></d:prop></d:propfind>`, settings);
    const principalHref = hrefInProperty(principalResponse.text, "current-user-principal");
    if (!principalHref) throw new Error("CalDAV-Konto konnte nicht bestimmt werden");
    const principalUrl = absoluteUrl(principalHref, principalResponse.url);
    const homeResponse = await propfind(principalUrl, `<?xml version="1.0"?><d:propfind xmlns:d="${DAV}" xmlns:c="${CALDAV}"><d:prop><c:calendar-home-set/></d:prop></d:propfind>`, settings);
    const homeHref = hrefInProperty(homeResponse.text, "calendar-home-set");
    if (!homeHref) throw new Error("CalDAV-Kalenderbereich wurde nicht gefunden");
    const homeUrl = absoluteUrl(homeHref, homeResponse.url);
    const calendars = await propfind(homeUrl, `<?xml version="1.0"?><d:propfind xmlns:d="${DAV}" xmlns:c="${CALDAV}"><d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/></d:prop></d:propfind>`, settings, "1");
    const wanted = settings.listName.toLocaleLowerCase("de-DE");
    const match = responseBlocks(calendars.text).map((block) => ({ href: tagValue(block, "href"), name: tagValue(block, "displayname"), hasTodo: /<(?:(?:[\w.-]+):)?comp[^>]+name=["']VTODO["']/i.test(block) }))
      .find((item) => item.name.toLocaleLowerCase("de-DE") === wanted);
    if (!match) throw new Error(`Die Erinnerungen-Liste „${settings.listName}“ wurde nicht gefunden`);
    if (!match.hasTodo) throw new Error(`Die Liste „${settings.listName}“ stellt keine CalDAV-Erinnerungen bereit`);
    cachedCalendarUrl = absoluteUrl(match.href, homeUrl);
    return cachedCalendarUrl;
  }
  async function fetchTodos(settings) {
    const calendarUrl = await discoverCalendar(settings);
    const report = `<?xml version="1.0"?><c:calendar-query xmlns:d="${DAV}" xmlns:c="${CALDAV}"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VTODO"/></c:comp-filter></c:filter></c:calendar-query>`;
    const response = await request(calendarUrl, "REPORT", report, settings, "1");
    return responseBlocks(response.text).flatMap((block) => openTodos(tagValue(block, "calendar-data"), tagValue(block, "href")));
  }
  async function run() {
    if (inFlight) return status;
    const settings = config();
    if (!settings.enabled) { status = { ...status, state: "disabled", detail: "Nicht aktiviert" }; return status; }
    if (!settings.username || !settings.password || !settings.listName) { status = { ...status, state: "not_configured", detail: "Apple-ID, App-Passwort oder Listenname fehlen" }; return status; }
    inFlight = true;
    status = { ...status, state: "syncing", detail: "Apple-Erinnerungen werden abgeglichen", lastRunAt: new Date().toISOString() };
    try {
      const items = await fetchTodos(settings);
      const result = await onItems(items, settings.targetListId);
      status = { ...status, state: "ready", detail: `${items.length} offene Erinnerungen geprüft`, lastSuccessAt: new Date().toISOString(), imported: result.added || 0, duplicates: result.duplicates || 0 };
    } catch (error) {
      cachedCalendarUrl = "";
      status = { ...status, state: "error", detail: `Apple-Erinnerungen konnten nicht abgeglichen werden: ${error.message}` };
      log(status.detail);
    } finally { inFlight = false; }
    return status;
  }
  function start() {
    if (timer) clearInterval(timer);
    void run();
    timer = setInterval(() => void run(), Math.max(60000, config().intervalMs));
  }
  function getStatus() { return { ...status, listName: config().listName, intervalSeconds: config().intervalMs / 1000 }; }
  return { start, run, getStatus, fetchTodos };
}

module.exports = { createAppleRemindersSync, openTodos, responseBlocks, tagValue, icalValue };
