"use strict";

// Liest ausschließlich die vom lokalen Radicale-Dienst gespeicherten VTODOs.
// Der Dienst selbst ist für Apples CalDAV-Protokoll zuständig; die Einkaufsliste
// importiert nur neue, offene Einträge in ihren eigenen Datenbestand.
const fs = require("node:fs");
const path = require("node:path");
const { openTodos } = require("./apple-reminders-sync");

function todoFiles(root) {
  const files = [];
  const visit = (folder) => {
    let entries = [];
    try { entries = fs.readdirSync(folder, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const candidate = path.join(folder, entry.name);
      if (entry.isDirectory()) visit(candidate);
      else if (entry.isFile() && entry.name.toLowerCase().endsWith(".ics")) files.push(candidate);
    }
  };
  visit(root);
  return files;
}

function readOpenTodos(root) {
  const items = [];
  for (const file of todoFiles(root)) {
    try {
      const stat = fs.statSync(file);
      if (stat.size > 1024 * 1024) continue;
      items.push(...openTodos(fs.readFileSync(file, "utf8"), file).map((item) => ({ ...item, sourceFile: file })));
    } catch { /* Eine gleichzeitig geschriebene Datei wird beim nächsten Lauf gelesen. */ }
  }
  return items;
}

function removeHandledTodoFiles(root, items, handledIds, log = console.log) {
  const rootPath = path.resolve(root);
  const handled = new Set((handledIds || []).map((id) => String(id || "")).filter(Boolean));
  const byFile = new Map();
  for (const item of items || []) {
    if (!item?.sourceFile || !item?.id) continue;
    const sourceFile = path.resolve(item.sourceFile);
    const relative = path.relative(rootPath, sourceFile);
    if (!relative || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative) || !sourceFile.toLowerCase().endsWith(".ics")) continue;
    if (!byFile.has(sourceFile)) byFile.set(sourceFile, []);
    byFile.get(sourceFile).push(String(item.id));
  }
  let removed = 0;
  for (const [file, ids] of byFile) {
    if (!ids.length || !ids.every((id) => handled.has(id))) continue;
    try {
      const current = openTodos(fs.readFileSync(file, "utf8"), file);
      if (!current.length || !current.every((item) => handled.has(String(item.id)))) continue;
      fs.unlinkSync(file);
      removed += 1;
    } catch (error) {
      log(`Übernommene CalDAV-Erinnerung konnte nicht entfernt werden: ${error.message}`);
    }
  }
  return removed;
}

function createLocalCaldavSync({ getOptions, onItems, root, log = console.log }) {
  let timer = null;
  let running = false;
  let status = { state: "disabled", detail: "Nicht aktiviert", lastRunAt: null, lastSuccessAt: null, imported: 0, duplicates: 0 };
  function settings() {
    const options = getOptions() || {};
    return {
      enabled: Boolean(options.caldav_enabled),
      username: String(options.caldav_username || "").trim(),
      password: String(options.caldav_password || "").trim(),
      targetListId: String(options.caldav_target_list_id || "supermarkt").trim(),
      intervalMs: Math.max(60000, Number(options.caldav_sync_interval_seconds || 60) * 1000),
    };
  }
  async function run() {
    if (running) return status;
    const config = settings();
    if (!config.enabled) { status = { ...status, state: "disabled", detail: "Nicht aktiviert" }; return status; }
    if (!config.username || !config.password) { status = { ...status, state: "not_configured", detail: "CalDAV-Benutzer oder -Passwort fehlen" }; return status; }
    running = true;
    status = { ...status, state: "syncing", detail: "Lokale CalDAV-Erinnerungen werden abgeglichen", lastRunAt: new Date().toISOString() };
    try {
      const items = readOpenTodos(root);
      const result = await onItems(items, config.targetListId);
      const removed = removeHandledTodoFiles(root, items, result.handledSourceIds, log);
      status = { ...status, state: "ready", detail: `${items.length} offene CalDAV-Erinnerungen geprüft`, lastSuccessAt: new Date().toISOString(), imported: result.added || 0, duplicates: result.duplicates || 0 };
      if (removed) log(`${removed} übernommene CalDAV-Erinnerung(en) aus der Apple-Liste entfernt.`);
    } catch (error) {
      status = { ...status, state: "error", detail: `CalDAV-Erinnerungen konnten nicht abgeglichen werden: ${error.message}` };
      log(status.detail);
    } finally { running = false; }
    return status;
  }
  function start() {
    if (timer) clearInterval(timer);
    void run();
    timer = setInterval(() => void run(), settings().intervalMs);
  }
  function getStatus() { return { ...status, intervalSeconds: settings().intervalMs / 1000 }; }
  return { start, run, getStatus };
}

module.exports = { todoFiles, readOpenTodos, removeHandledTodoFiles, createLocalCaldavSync };
