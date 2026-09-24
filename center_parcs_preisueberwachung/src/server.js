"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const express = require("express");
const {
  PROVIDERS,
  buildSearchUrl,
  entitySlug,
  normalizeSearch,
  offerLabel,
  parseSearchUrl,
} = require("./centerparcs");
const {
  compareParks,
  DEFAULT_PARKS,
  discoverParks,
  fetchAvailableDates,
  fetchProviderAvailability,
  launchBrowser,
  scrapeOffers,
} = require("./scraper");
const { collectProviderChanges } = require("./notification_changes");
const {
  aggregateFlexibleScans,
  aggregateRangeOptions,
  buildCandidateStays,
  buildRangeOptionsByCode,
  exactSearchForStay,
} = require("./flexible_search");

const PORT = Number.parseInt(process.env.PORT || "8102", 10);
const DATA_DIR = process.env.DATA_DIR || "/data";
const DATA_FILE = path.join(DATA_DIR, "center-parcs-state.json");
const OPTIONS_FILE = path.join(DATA_DIR, "options.json");
const PUBLIC_DIR = path.join(__dirname, "..", "public");
const HOME_ASSISTANT_API = "http://supervisor/core/api";
const NOTIFICATION_SERVICE = "notify.mobile_app_iphone_patrick";
const HOURLY_INTERVAL_HOURS = 1;

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "256kb" }));
app.use(express.static(PUBLIC_DIR));

let database = {
  version: 1,
  settings: {
    interval_hours: HOURLY_INTERVAL_HOURS,
    max_history_points: 3000,
    notification_service: NOTIFICATION_SERVICE,
    default_adults: 2,
    default_child_ages: [5, 8],
    default_pets: 2,
  },
  parks: [...DEFAULT_PARKS],
  trips: [],
  last_scan: null,
  next_scan: null,
  home_assistant: "noch nicht aktualisiert",
};

let timer = null;
let operationQueue = Promise.resolve();
let allScanRunning = false;
let allScanQueued = false;
const RANGE_STAY_TIMEOUT_MS = 4 * 60 * 1000;
const previews = new Map();
const PROVIDER_IDS = Object.keys(PROVIDERS);
const availableDateCache = new Map();

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

async function readJson(file, fallback) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") log(`Datei konnte nicht gelesen werden: ${error.message}`);
    return fallback;
  }
}

function int(value, fallback, min, max) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : fallback;
}

function normalizeSettings(value = {}) {
  const childAgesSource = Array.isArray(value.default_child_ages)
    ? value.default_child_ages
    : String(value.default_child_ages ?? "5,8")
        .split(/[;,\s]+/)
        .filter(Boolean);
  return {
    // Jeder einzelne Preis wird stündlich neu aus seinem exakten Direktlink abgefragt.
    interval_hours: HOURLY_INTERVAL_HOURS,
    max_history_points: int(value.max_history_points, 3000, 100, 10_000),
    notification_service: NOTIFICATION_SERVICE,
    default_adults: int(value.default_adults, 2, 1, 20),
    default_child_ages: childAgesSource
      .slice(0, 12)
      .map((age) => int(age, 0, 0, 17)),
    default_pets: int(value.default_pets, 2, 0, 2),
  };
}

function mergeParks(...lists) {
  const byId = new Map();
  for (const list of lists) {
    for (const park of Array.isArray(list) ? list : []) {
      if (park?.id && park?.base_url) {
        const previous = byId.get(park.id) || {};
        byId.set(park.id, {
          ...previous,
          ...park,
          country: park.country || previous.country || "",
        });
      }
    }
  }
  return [...byId.values()].sort(compareParks);
}

function sortTripsByTravelPeriod(trips = []) {
  return [...trips].sort((left, right) => {
    const startComparison = String(left?.search?.range_start || left?.search?.start_date || "9999-12-31").localeCompare(
      String(right?.search?.range_start || right?.search?.start_date || "9999-12-31"),
    );
    if (startComparison) return startComparison;
    const endComparison = String(left?.search?.range_end || left?.search?.end_date || "9999-12-31").localeCompare(
      String(right?.search?.range_end || right?.search?.end_date || "9999-12-31"),
    );
    if (endComparison) return endComparison;
    return String(left?.name || "").localeCompare(String(right?.name || ""), "de");
  });
}

function travelFolderForSearch(search = {}) {
  const match = String(search.range_start || search.start_date || "").match(/^(\d{4})-(\d{2})-\d{2}$/);
  if (!match) return { key: "9999-weitere", label: "Weitere Reisezeiträume" };
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month === 12) return { key: `${year + 1}-winter`, label: `Winter ${year + 1}` };
  if (month <= 2) return { key: `${year}-winter`, label: `Winter ${year}` };
  if (month <= 5) return { key: `${year}-fruehling`, label: `Frühling ${year}` };
  if (month <= 8) return { key: `${year}-sommer`, label: `Sommer ${year}` };
  return { key: `${year}-herbst`, label: `Herbst ${year}` };
}

function normalizeFolderLabel(value, search = {}) {
  const label = String(value || "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim()
    .slice(0, 80);
  return label || travelFolderForSearch(search).label;
}

function folderKey(label) {
  return String(label || "weitere")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "weitere";
}

function travelFolderForTrip(trip = {}) {
  const label = normalizeFolderLabel(trip.folder, trip.search);
  return { key: folderKey(label), label };
}

function unavailableProvider(providerId) {
  return {
    provider: providerId,
    provider_name: PROVIDERS[providerId].name,
    price: null,
    available: false,
    stock: 0,
    in_offer: true,
    status: "unavailable",
    status_text: "Nicht verfügbar",
  };
}

function legacyProvider(offer) {
  return {
    provider: "direct",
    provider_name: PROVIDERS.direct.name,
    price: offer?.price ?? null,
    original_price: offer?.original_price ?? null,
    total_with_tax: offer?.total_with_tax ?? null,
    pet_fee: offer?.pet_fee ?? null,
    discount_percent: offer?.discount_percent ?? 0,
    stock: offer?.stock ?? 0,
    action_name: offer?.action_name || "",
    available: Boolean(offer?.available && Number.isFinite(offer?.price)),
    in_offer: true,
    status: offer?.available && Number.isFinite(offer?.price) ? "available" : "unavailable",
    status_text: offer?.available && Number.isFinite(offer?.price) ? "Verfügbar" : "Nicht verfügbar",
  };
}

function normalizeOfferProviders(offer) {
  const prices = Object.fromEntries(PROVIDER_IDS.map((providerId) => {
    const fallback = providerId === "direct" ? legacyProvider(offer) : unavailableProvider(providerId);
    const value = offer?.prices?.[providerId] || fallback;
    return [providerId, {
      ...fallback,
      ...value,
      status: value.status || (value.available ? "available" : "unavailable"),
      status_text: value.status_text || (value.available ? "Verfügbar" : "Nicht verfügbar"),
      in_offer: value.in_offer !== false,
    }];
  }));
  const best = Object.values(prices)
    .filter((item) => item.available && Number.isFinite(item.price))
    .sort((left, right) => left.price - right.price)[0] || null;
  return {
    ...offer,
    prices,
    price: best?.price ?? null,
    best_price: best?.price ?? null,
    best_provider: best?.provider ?? null,
    best_provider_name: best?.provider_name ?? "",
    original_price: best?.original_price ?? null,
    total_with_tax: best?.total_with_tax ?? null,
    pet_fee: best?.pet_fee ?? null,
    discount_percent: best?.discount_percent ?? 0,
    stock: best?.stock ?? 0,
    available: Boolean(best),
  };
}

function migrateTrip(trip) {
  if (!("include_felicitas" in trip.search)) trip.search.include_felicitas = true;
  if (!trip.search.mode) trip.search.mode = "fixed";
  if (trip.search.mode === "range") {
    trip.search.range_start = trip.search.range_start || trip.search.start_date;
    trip.search.range_end = trip.search.range_end || trip.search.end_date;
    trip.search.nights = [3, 4, 7].includes(Number(trip.search.nights)) ? Number(trip.search.nights) : 3;
    if (!Array.isArray(trip.catalog_offers) || !trip.catalog_offers.length) {
      trip.catalog_offers = Array.isArray(trip.offers) ? trip.offers.map((offer) => ({ ...offer })) : [];
    }
    if (!trip.scan_progress || typeof trip.scan_progress !== "object") trip.scan_progress = null;
    if (!trip.range_options || typeof trip.range_options !== "object" || Array.isArray(trip.range_options)) trip.range_options = {};
    for (const rows of Object.values(trip.range_options)) {
      for (const row of Array.isArray(rows) ? rows : []) {
        if (!row.check_status) row.check_status = "current";
        if (!row.checked_at) row.checked_at = trip.last_check || trip.updated_at || null;
        for (const snapshot of Object.values(row.prices || {})) {
          if (snapshot && !snapshot.checked_at) snapshot.checked_at = row.checked_at || trip.last_check || trip.updated_at || null;
        }
      }
    }
    if (!Array.isArray(trip.failed_stays)) trip.failed_stays = [];
    if (!("initial_scan_notification_pending" in trip)) trip.initial_scan_notification_pending = false;
    if (!("initial_scan_completed_at" in trip)) trip.initial_scan_completed_at = trip.last_check || null;
  }
  trip.folder = normalizeFolderLabel(trip.folder, trip.search);
  trip.offers = (trip.offers || []).map(normalizeOfferProviders);
  for (const offer of [...(trip.catalog_offers || []), ...(trip.offers || [])]) {
    for (const snapshot of Object.values(offer?.prices || {})) {
      if (snapshot && !snapshot.checked_at) snapshot.checked_at = trip.last_check || trip.updated_at || null;
    }
  }
  trip.search.provider_urls = trip.search.mode === "range"
    ? {}
    : Object.fromEntries(PROVIDER_IDS.map((providerId) => [
      providerId,
      trip.search.provider_urls?.[providerId] ||
        (providerId === "direct" ? trip.search.source_url : null) ||
        buildSearchUrl(trip.search, providerId),
    ]));
  for (const points of Object.values(trip.history || {})) {
    for (const point of Array.isArray(points) ? points : []) {
      if (!("direct_price" in point)) point.direct_price = point.price ?? null;
      if (!("felicitas_price" in point)) point.felicitas_price = null;
      if (!("best_price" in point)) point.best_price = point.price ?? null;
      if (!("best_provider" in point)) point.best_provider = Number.isFinite(point.price) ? "direct" : null;
      if (!("direct_available" in point)) point.direct_available = Boolean(point.available);
      if (!("felicitas_available" in point)) point.felicitas_available = false;
      if (!("direct_stock" in point)) point.direct_stock = point.stock ?? 0;
      if (!("felicitas_stock" in point)) point.felicitas_stock = 0;
      if (!("benefits_price" in point)) point.benefits_price = null;
      if (!("benefits_available" in point)) point.benefits_available = false;
      if (!("benefits_stock" in point)) point.benefits_stock = 0;
      if (!("benefits_status" in point)) point.benefits_status = "unavailable";
    }
  }
  return trip;
}

async function loadDatabase() {
  const options = await readJson(OPTIONS_FILE, {});
  const saved = await readJson(DATA_FILE, null);
  if (saved?.version === 1) {
    database = {
      ...database,
      ...saved,
      settings: normalizeSettings({ ...options, ...saved.settings }),
      parks: mergeParks(DEFAULT_PARKS, saved.parks),
      trips: Array.isArray(saved.trips) ? saved.trips.map(migrateTrip) : [],
    };
  } else {
    database.settings = normalizeSettings(options);
  }
}

async function saveDatabase() {
  await fs.mkdir(DATA_DIR, { recursive: true });
  const temporary = `${DATA_FILE}.tmp`;
  await fs.writeFile(temporary, JSON.stringify(database, null, 2), { mode: 0o600 });
  await fs.rename(temporary, DATA_FILE);
}

function queueOperation(task) {
  const run = operationQueue.then(task, task);
  operationQueue = run.catch(() => {});
  return run;
}

function formatGermanDate(dateString) {
  const [year, month, day] = String(dateString || "").split("-");
  return year && month && day ? `${day}.${month}.${year}` : "–";
}

function defaultTripName(search) {
  if (search.mode === "range") {
    return `${search.park.name} · ${formatGermanDate(search.range_start)}–${formatGermanDate(search.range_end)} · ${search.nights} Nächte`;
  }
  return `${search.park.name} · ${formatGermanDate(search.start_date)}–${formatGermanDate(search.end_date)}`;
}

function cleanPreviewCache() {
  const cutoff = Date.now() - 30 * 60 * 1000;
  for (const [token, preview] of previews.entries()) {
    if (new Date(preview.created_at).getTime() < cutoff) previews.delete(token);
  }
}

function addPark(park) {
  database.parks = mergeParks(database.parks, [park]);
}

function findTrip(id) {
  return database.trips.find((trip) => trip.id === id);
}

function findOffer(trip, code) {
  return (trip.offers || []).find((offer) => offer.code === code);
}

function historyFor(trip, code) {
  if (!trip.history || typeof trip.history !== "object") trip.history = {};
  if (!Array.isArray(trip.history[code])) trip.history[code] = [];
  return trip.history[code];
}

function appendHistory(trip, checkedAt) {
  const limit = database.settings.max_history_points;
  for (const code of trip.watched_codes || []) {
    const offer = findOffer(trip, code);
    const direct = offer?.prices?.direct || unavailableProvider("direct");
    const felicitas = offer?.prices?.felicitas || unavailableProvider("felicitas");
    const benefits = offer?.prices?.benefits || unavailableProvider("benefits");
    const points = historyFor(trip, code);
    points.push({
      at: checkedAt,
      price: offer?.price ?? null,
      best_price: offer?.best_price ?? offer?.price ?? null,
      best_provider: offer?.best_provider ?? null,
      direct_price: direct.price ?? null,
      felicitas_price: felicitas.price ?? null,
      benefits_price: benefits.price ?? null,
      direct_stock: direct.stock ?? 0,
      felicitas_stock: felicitas.stock ?? 0,
      benefits_stock: benefits.stock ?? 0,
      direct_available: Boolean(direct.available),
      felicitas_available: Boolean(felicitas.available),
      benefits_available: Boolean(benefits.available),
      direct_status: direct.status || "unavailable",
      felicitas_status: felicitas.status || "unavailable",
      benefits_status: benefits.status || "unavailable",
      best_start_date: offer?.best_stay?.start_date ?? offer?.start_date ?? null,
      best_end_date: offer?.best_stay?.end_date ?? offer?.end_date ?? null,
      direct_start_date: direct.start_date ?? null,
      direct_end_date: direct.end_date ?? null,
      felicitas_start_date: felicitas.start_date ?? null,
      felicitas_end_date: felicitas.end_date ?? null,
      benefits_start_date: benefits.start_date ?? null,
      benefits_end_date: benefits.end_date ?? null,
      original_price: offer?.original_price ?? null,
      stock: offer?.stock ?? 0,
      available: Boolean(offer?.available),
    });
    if (points.length > limit) points.splice(0, points.length - limit);
  }

  // Für „Alle ansehen“ wird pro Haus und exaktem Aufenthalt nur dann ein
  // zusätzlicher Punkt gespeichert, wenn sich dort wirklich etwas ändert.
  // So bleibt der Verlauf aussagekräftig, ohne stündliche Duplikate zu horten.
  if (trip.search?.mode !== "range") return;
  if (!trip.range_history || typeof trip.range_history !== "object") trip.range_history = {};
  for (const code of trip.watched_codes || []) {
    if (!trip.range_history[code] || typeof trip.range_history[code] !== "object") trip.range_history[code] = {};
    for (const row of trip.range_options?.[code] || []) {
      const key = `${row.start_date}|${row.end_date}`;
      const snapshots = trip.range_history[code][key] || [];
      const record = rangeHistoryPoint(row, checkedAt);
      const previous = snapshots[snapshots.length - 1];
      if (!sameRangeHistoryPoint(previous, record)) snapshots.push(record);
      if (snapshots.length > limit) snapshots.splice(0, snapshots.length - limit);
      trip.range_history[code][key] = snapshots;
    }
  }
}

function rangeHistoryPoint(row, checkedAt) {
  const provider = (id) => row?.prices?.[id] || unavailableProvider(id);
  const direct = provider("direct");
  const felicitas = provider("felicitas");
  const benefits = provider("benefits");
  return {
    at: checkedAt,
    best_price: Number.isFinite(Number(row?.best_price)) ? Number(row.best_price) : null,
    best_provider: row?.best_provider || null,
    direct_price: Number.isFinite(Number(direct.price)) ? Number(direct.price) : null,
    felicitas_price: Number.isFinite(Number(felicitas.price)) ? Number(felicitas.price) : null,
    benefits_price: Number.isFinite(Number(benefits.price)) ? Number(benefits.price) : null,
    direct_status: direct.status || "unavailable",
    felicitas_status: felicitas.status || "unavailable",
    benefits_status: benefits.status || "unavailable",
  };
}

function sameRangeHistoryPoint(left, right) {
  if (!left || !right) return false;
  return ["best_price", "best_provider", "direct_price", "felicitas_price", "benefits_price", "direct_status", "felicitas_status", "benefits_status"]
    .every((key) => left[key] === right[key]);
}

function watchSummary(trip, code) {
  const offer = findOffer(trip, code);
  const points = historyFor(trip, code);
  const priced = points.filter((point) => Number.isFinite(point.best_price ?? point.price));
  const previousPoint = points.length > 1 ? points[points.length - 2] : null;
  const previous = previousPoint?.best_price ?? previousPoint?.price ?? null;
  const current = offer?.price ?? null;
  const direct = offer?.prices?.direct || unavailableProvider("direct");
  const felicitas = offer?.prices?.felicitas || unavailableProvider("felicitas");
  const benefits = offer?.prices?.benefits || unavailableProvider("benefits");
  return {
    ...(offer || {
      code,
      name: "Unterkunft nicht mehr in der Ergebnisliste",
      available: false,
      price: null,
      stock: 0,
    }),
    label: offer ? offerLabel(offer) : code,
    previous_price: previous,
    change: Number.isFinite(current) && Number.isFinite(previous) ? current - previous : null,
    direct_price: direct.price,
    felicitas_price: felicitas.price,
    benefits_price: benefits.price,
    direct_available: direct.available,
    felicitas_available: felicitas.available,
    benefits_available: benefits.available,
    direct_status: direct.status,
    felicitas_status: felicitas.status,
    benefits_status: benefits.status,
    direct_status_text: direct.status_text,
    felicitas_status_text: felicitas.status_text,
    benefits_status_text: benefits.status_text,
    direct_stock: direct.stock,
    felicitas_stock: felicitas.stock,
    benefits_stock: benefits.stock,
    direct_change:
      Number.isFinite(direct.price) && Number.isFinite(previousPoint?.direct_price)
        ? direct.price - previousPoint.direct_price
        : null,
    felicitas_change:
      Number.isFinite(felicitas.price) && Number.isFinite(previousPoint?.felicitas_price)
        ? felicitas.price - previousPoint.felicitas_price
        : null,
    benefits_change:
      Number.isFinite(benefits.price) && Number.isFinite(previousPoint?.benefits_price)
        ? benefits.price - previousPoint.benefits_price
        : null,
    best_stay: offer?.best_stay || (offer?.start_date && offer?.end_date ? { start_date: offer.start_date, end_date: offer.end_date } : null),
    previous_best_stay: previousPoint?.best_start_date && previousPoint?.best_end_date
      ? { start_date: previousPoint.best_start_date, end_date: previousPoint.best_end_date }
      : null,
    lowest_price: priced.length
      ? Math.min(...priced.map((point) => point.best_price ?? point.price))
      : null,
    highest_price: priced.length
      ? Math.max(...priced.map((point) => point.best_price ?? point.price))
      : null,
    history_points: points.length,
  };
}

function publicTrip(trip, includeOffers = true) {
  return {
    id: trip.id,
    name: trip.name,
    search: trip.search,
    travel_folder: travelFolderForTrip(trip),
    watched_codes: trip.watched_codes || [],
    watched_offers: (trip.watched_codes || []).map((code) => watchSummary(trip, code)),
    offers: includeOffers ? trip.offers || [] : undefined,
    state: trip.state,
    message: trip.message,
    last_check: trip.last_check,
    created_at: trip.created_at,
    updated_at: trip.updated_at,
    entity_id: trip.entity_id,
    scan_progress: trip.scan_progress || null,
    latest_best_change: trip.latest_best_change || null,
    initial_scan_completed_at: trip.initial_scan_completed_at || null,
    notification_error: trip.notification_error || null,
    initial_scan_notification_sent_at: trip.initial_scan_notification_sent_at || null,
  };
}

function publicState() {
  const folders = [...new Set(database.trips.map((trip) => travelFolderForTrip(trip).label))]
    .sort((left, right) => left.localeCompare(right, "de"));
  return {
    settings: database.settings,
    parks: database.parks,
    folders,
    trips: sortTripsByTravelPeriod(database.trips).map((trip) => publicTrip(trip)),
    last_scan: database.last_scan,
    next_scan: database.next_scan,
    home_assistant: database.home_assistant,
    running: allScanRunning,
  };
}

function catalogOfferFrom(offer) {
  const base = offer || {};
  return {
    ...base,
    prices: Object.fromEntries(PROVIDER_IDS.map((providerId) => [providerId, unavailableProvider(providerId)])),
    price: null,
    best_price: null,
    best_provider: null,
    best_provider_name: "",
    original_price: null,
    total_with_tax: null,
    pet_fee: null,
    discount_percent: 0,
    stock: 0,
    action_name: "",
    available: false,
    best_stay: null,
    start_date: null,
    end_date: null,
  };
}

function mergeCatalogOffers(...groups) {
  const byCode = new Map();
  for (const group of groups) {
    for (const offer of Array.isArray(group) ? group : []) {
      if (!offer?.code) continue;
      const previous = byCode.get(offer.code) || {};
      byCode.set(offer.code, {
        ...previous,
        ...offer,
        image_url: offer.image_url || previous.image_url || "",
        detail_url: offer.detail_url || previous.detail_url || "",
        house_info_url: offer.house_info_url || previous.house_info_url || "",
      });
    }
  }
  return [...byCode.values()]
    .map(catalogOfferFrom)
    .sort((left, right) => String(left.name || left.code).localeCompare(String(right.name || right.code), "de"));
}

function catalogOffersForPark(search) {
  const groups = [];
  for (const trip of database.trips) {
    if (trip.search?.park?.id !== search.park.id) continue;
    groups.push(trip.catalog_offers || trip.offers || []);
  }
  return mergeCatalogOffers(...groups);
}

function sampleStays(stays, limit = 6) {
  if (!stays.length) return [];
  const indexes = [
    Math.floor(stays.length / 2),
    0,
    stays.length - 1,
    Math.floor(stays.length / 4),
    Math.floor((stays.length * 3) / 4),
  ];
  const seen = new Set();
  const result = [];
  for (const index of indexes) {
    if (index < 0 || index >= stays.length || seen.has(index)) continue;
    seen.add(index);
    result.push(stays[index]);
    if (result.length >= limit) return result;
  }
  for (let index = 0; index < stays.length && result.length < limit; index += 1) {
    if (seen.has(index)) continue;
    result.push(stays[index]);
  }
  return result;
}

async function previewRangeCatalog(search) {
  const availableDates = await fetchAvailableDates(search.park);
  const stays = buildCandidateStays(search, availableDates);
  if (!stays.length) {
    throw new Error(`Im gewählten Zeitraum gibt es keinen aktuell buchbaren Aufenthalt mit ${search.nights} Nächten.`);
  }

  const cached = catalogOffersForPark(search);
  if (cached.length) {
    log(`Zeitraum-Vorschau: ${cached.length} bekannte Haustypen für ${search.park.name} aus dem lokalen Katalog geladen.`);
    return {
      checked_at: new Date().toISOString(),
      offers: cached,
      candidate_count: stays.length,
      catalog_only: true,
      catalog_source: "cache",
    };
  }

  const browser = await launchBrowser();
  try {
    for (const stay of sampleStays(stays)) {
      const exactSearch = exactSearchForStay(search, stay);
      exactSearch.mode = "fixed";
      exactSearch.include_felicitas = false;
      exactSearch.catalog_preview = true;
      exactSearch.source_url = buildSearchUrl(exactSearch, "direct");
      log(`Zeitraum-Vorschau: Haustypen werden exemplarisch für ${stay.start_date} bis ${stay.end_date} geladen.`);
      const result = await scrapeOffers(exactSearch, browser);
      if (result.offers?.length) {
        return {
          checked_at: new Date().toISOString(),
          offers: mergeCatalogOffers(result.offers),
          candidate_count: stays.length,
          catalog_only: true,
          catalog_source: "sample",
        };
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }

  throw new Error("Die Haustypen konnten für diesen Park gerade nicht geladen werden. Bitte die Auswahl noch einmal versuchen.");
}

function mergeRangeResultsWithCatalog(resultOffers, catalogOffers) {
  const resultByCode = new Map((resultOffers || []).filter((offer) => offer?.code).map((offer) => [offer.code, offer]));
  const catalog = mergeCatalogOffers(catalogOffers || [], resultOffers || []);
  return catalog.map((meta) => resultByCode.has(meta.code)
    ? normalizeOfferProviders(resultByCode.get(meta.code))
    : normalizeOfferProviders(meta));
}

function rangeStayKey(startDate, endDate) {
  return `${String(startDate || "")}|${String(endDate || "")}`;
}

function rangeFailureMessage(failure) {
  const messages = (failure?.providers || []).map((entry) => entry?.message).filter(Boolean);
  return messages.join(" · ") || "Dieser Aufenthalt konnte technisch nicht vollständig geprüft werden.";
}

function unavailableRangePrices() {
  return Object.fromEntries(PROVIDER_IDS.map((providerId) => [providerId, {
    ...unavailableProvider(providerId),
    status: "provider_unverified",
    status_text: "Technisch nicht aktuell geprüft",
  }]));
}

function mergeRangeOptions(previousOptions, freshOptions, searchedStays, failedStays, checkedAt, codes, options = {}) {
  const preserveUnsearched = options.preserve_unsearched === true;
  const previousCheck = options.previous_check || null;
  const searchedKeys = new Set((searchedStays || []).map((stay) => rangeStayKey(stay.start_date, stay.end_date)));
  const failedByKey = new Map((failedStays || []).map((failure) => [rangeStayKey(failure.start_date, failure.end_date), failure]));
  const result = {};

  for (const code of codes || []) {
    const previousRows = Array.isArray(previousOptions?.[code]) ? previousOptions[code] : [];
    const freshRows = Array.isArray(freshOptions?.[code]) ? freshOptions[code] : [];
    const previousByKey = new Map(previousRows.map((row) => [rangeStayKey(row.start_date, row.end_date), row]));
    const freshByKey = new Map(freshRows.map((row) => [rangeStayKey(row.start_date, row.end_date), row]));
    const rows = preserveUnsearched
      ? previousRows.filter((row) => !searchedKeys.has(rangeStayKey(row.start_date, row.end_date))).map((row) => ({ ...row }))
      : [];

    for (const stay of searchedStays || []) {
      const key = rangeStayKey(stay.start_date, stay.end_date);
      const failure = failedByKey.get(key) || null;
      const fresh = freshByKey.get(key) || null;
      const previous = previousByKey.get(key) || null;
      if (fresh) {
        rows.push({
          ...fresh,
          check_status: failure ? "partial" : "current",
          checked_at: checkedAt,
          last_known_at: previous?.checked_at || previous?.last_known_at || previousCheck || null,
          error_message: failure ? rangeFailureMessage(failure) : null,
        });
      } else if (failure) {
        rows.push(previous ? {
          ...previous,
          check_status: "stale",
          last_known_at: previous.checked_at || previous.last_known_at || previousCheck || null,
          checked_at: null,
          error_message: rangeFailureMessage(failure),
        } : {
          start_date: stay.start_date,
          end_date: stay.end_date,
          best_price: null,
          best_provider: null,
          best_provider_name: "",
          prices: unavailableRangePrices(),
          check_status: "error",
          checked_at: null,
          last_known_at: null,
          error_message: rangeFailureMessage(failure),
        });
      }
      // Erfolgreich geprüft, aber dieser Haustyp war nicht verfügbar: alter Datensatz wird bewusst entfernt.
    }
    result[code] = rows.sort((left, right) => String(left.start_date).localeCompare(String(right.start_date)));
  }
  return result;
}

async function scrapeRangeStayWithTimeout(search, browser, timeoutMs = RANGE_STAY_TIMEOUT_MS) {
  let timer = null;
  const work = scrapeOffers(search, browser);
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      for (const context of browser?.contexts?.() || []) context.close().catch(() => {});
      reject(new Error(`Zeitlimit von ${Math.round(timeoutMs / 1000)} Sekunden für diesen Aufenthalt überschritten.`));
    }, timeoutMs);
  });
  try {
    return await Promise.race([work, timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function scrapeSearch(search, browser = null, options = {}) {
  if (search.mode !== "range") return scrapeOffers(search, browser);

  const availableDates = await fetchAvailableDates(search.park);
  const stays = buildCandidateStays(search, availableDates);
  if (!stays.length) {
    throw new Error(`Im gewählten Zeitraum gibt es keinen aktuell buchbaren Aufenthalt mit ${search.nights} Nächten.`);
  }

  const ownsBrowser = !browser;
  const activeBrowser = browser || (await launchBrowser());
  const scans = [];
  const completeScans = [];
  const failedStays = [];
  const setupErrors = [];
  const startedAt = new Date().toISOString();
  const onProgress = typeof options.onProgress === "function" ? options.onProgress : async () => {};
  const onStay = typeof options.onStay === "function" ? options.onStay : async () => {};

  await onProgress({
    status: "preparing",
    total: stays.length,
    completed: 0,
    successful: 0,
    failed: 0,
    started_at: startedAt,
    current: null,
  });

  try {
    log(`Zeitraum-Suche im Hintergrund: ${search.park.name}, ${search.range_start} bis ${search.range_end}, ${search.nights} Nächte, ${stays.length} mögliche Anreisen.`);
    const partnerAvailability = {};
    if (search.include_felicitas !== false) {
      for (const providerId of PROVIDER_IDS.filter((id) => id !== "direct")) {
        try {
          partnerAvailability[providerId] = await fetchProviderAvailability(search, providerId, activeBrowser);
          log(`${PROVIDERS[providerId].name}: Partner-Kalender einmalig für die gesamte Zeitraum-Suche geladen (${partnerAvailability[providerId].available_dates?.length || 0} Anreisetage).`);
        } catch (error) {
          setupErrors.push({ provider: providerId, message: error.message || String(error) });
          partnerAvailability[providerId] = {
            provider: providerId,
            status: "provider_unverified",
            status_text: "Partner-Kalender konnte technisch nicht vollständig geprüft werden",
            available_dates: [],
            page_url: buildSearchUrl(search, providerId),
            requested_url: buildSearchUrl(search, providerId),
          };
          log(`${PROVIDERS[providerId].name}: Partner-Kalender konnte für diesen Durchlauf nicht geladen werden: ${error.message || error}`);
        }
      }
    }

    let successful = 0;
    for (let index = 0; index < stays.length; index += 1) {
      const stay = stays[index];
      const exactSearch = exactSearchForStay(search, stay);
      exactSearch.mode = "fixed";
      exactSearch.background_range_scan = true;
      exactSearch.source_url = buildSearchUrl(exactSearch, "direct");
      exactSearch.partner_availability = partnerAvailability;
      log(`Zeitraum-Suche ${index + 1}/${stays.length}: ${stay.start_date} bis ${stay.end_date}`);

      let result = null;
      let failure = null;
      try {
        result = await scrapeRangeStayWithTimeout(exactSearch, activeBrowser);
        const scan = { search: exactSearch, result };
        scans.push(scan);
        if (Array.isArray(result.provider_errors) && result.provider_errors.length) {
          failure = {
            start_date: stay.start_date,
            end_date: stay.end_date,
            providers: result.provider_errors,
          };
          failedStays.push(failure);
        } else {
          completeScans.push(scan);
          successful += 1;
        }
      } catch (error) {
        failure = {
          start_date: stay.start_date,
          end_date: stay.end_date,
          providers: [{ provider: "all", message: error.message || String(error) }],
        };
        failedStays.push(failure);
        log(`Zeitraum ${stay.start_date} bis ${stay.end_date} konnte technisch nicht geprüft werden und wird beim nächsten Durchlauf erneut versucht: ${error.message || error}`);
      }

      const progress = {
        status: "running",
        total: stays.length,
        completed: index + 1,
        successful,
        failed: failedStays.length + setupErrors.length,
        started_at: startedAt,
        current: stay,
      };
      // Der sichtbare Stand wird nach jedem einzelnen Aufenthalt geschrieben;
      // ein langsamer Folgetermin hält bereits geprüfte Preise nicht zurück.
      await onStay({ stay, search: exactSearch, result, failure, progress });
      await onProgress(progress);
    }

    if (!scans.length) {
      throw new Error("Keiner der möglichen Aufenthalte konnte technisch geprüft werden. Die Beobachtung bleibt gespeichert und kann erneut geprüft werden.");
    }

    const aggregated = aggregateFlexibleScans(search, completeScans);
    const complete = failedStays.length === 0 && setupErrors.length === 0;
    const checkedAt = new Date().toISOString();
    return {
      checked_at: checkedAt,
      page_url: search.park.base_url,
      provider_urls: {},
      offers: aggregated.offers,
      candidate_count: stays.length,
      successful_count: successful,
      failed_count: failedStays.length + setupErrors.length,
      failed_stays: failedStays,
      setup_errors: setupErrors,
      complete,
      searched_stays: stays,
      range_options: buildRangeOptionsByCode(scans),
    };
  } finally {
    if (ownsBrowser) await activeBrowser.close().catch(() => {});
  }
}

function replaceFailedStay(failedStays, stay, failure) {
  const key = rangeStayKey(stay.start_date, stay.end_date);
  const remaining = (failedStays || []).filter((item) => rangeStayKey(item.start_date, item.end_date) !== key);
  return failure ? [...remaining, failure] : remaining;
}

async function applyRangeStayUpdate(trip, update) {
  const checkedAt = update.result?.checked_at || new Date().toISOString();
  const freshOptions = update.result
    ? buildRangeOptionsByCode([{ search: update.search, result: update.result }])
    : {};
  trip.catalog_offers = mergeCatalogOffers(trip.catalog_offers || [], update.result?.offers || []);
  trip.range_options = mergeRangeOptions(
    trip.range_options || {},
    freshOptions,
    [update.stay],
    update.failure ? [update.failure] : [],
    checkedAt,
    trip.watched_codes || [],
    { preserve_unsearched: true, previous_check: trip.last_check },
  );
  const currentRangeOffers = aggregateRangeOptions(trip.catalog_offers || [], trip.range_options || {});
  trip.offers = mergeRangeResultsWithCatalog(currentRangeOffers, trip.catalog_offers);
  trip.failed_stays = replaceFailedStay(trip.failed_stays, update.stay, update.failure);
  trip.last_check = checkedAt;
  trip.updated_at = checkedAt;
  trip.scan_progress = update.progress;
  trip.state = "running";
  trip.message = update.progress.total
    ? `${update.progress.completed} von ${update.progress.total} möglichen Aufenthalten geprüft – erfolgreiche Preise sind bereits aktualisiert.`
    : "Zeitraum-Prüfung wird vorbereitet …";
  await saveDatabase();
  await publishHomeAssistant();
}

async function scrapeTrip(trip, browser = null) {
  const isRange = trip.search.mode === "range";
  const previousOffers = new Map((trip.offers || []).map((offer) => [offer.code, offer]));
  trip.state = "running";
  trip.message = isRange ? "Gesamter Suchzeitraum wird im Hintergrund geprüft …" : "Preise werden geprüft …";
  if (isRange) {
    trip.scan_progress = {
      status: "preparing",
      total: Number(trip.search.candidate_count || 0),
      completed: 0,
      successful: 0,
      failed: 0,
      started_at: new Date().toISOString(),
      current: null,
    };
    await saveDatabase();
  }

  const result = await scrapeSearch(trip.search, browser, {
    onStay: isRange ? async (update) => {
      await applyRangeStayUpdate(trip, update);
    } : undefined,
    onProgress: isRange ? async (progress) => {
      trip.scan_progress = progress;
      trip.state = "running";
      trip.message = progress.total
        ? `${progress.completed} von ${progress.total} möglichen Aufenthalten geprüft – erfolgreiche Preise sind bereits aktualisiert.`
        : "Zeitraum-Prüfung wird vorbereitet …";
      trip.updated_at = new Date().toISOString();
      await saveDatabase();
    } : undefined,
  });

  if (isRange) {
    trip.search.candidate_count = result.candidate_count || trip.search.candidate_count || 0;
    trip.catalog_offers = mergeCatalogOffers(trip.catalog_offers || [], result.offers || []);
    trip.range_options = mergeRangeOptions(
      trip.range_options || {},
      result.range_options || {},
      result.searched_stays || [],
      result.failed_stays || [],
      result.checked_at,
      trip.watched_codes || [],
      { previous_check: trip.last_check },
    );
    const currentRangeOffers = aggregateRangeOptions(trip.catalog_offers || [], trip.range_options || {});
    trip.offers = mergeRangeResultsWithCatalog(currentRangeOffers, trip.catalog_offers);
    trip.failed_stays = result.failed_stays || [];

    trip.last_check = result.checked_at;
    trip.updated_at = result.checked_at;
    trip.scan_progress = {
      status: result.complete ? "complete" : "partial",
      total: result.candidate_count || 0,
      completed: result.candidate_count || 0,
      successful: result.successful_count || 0,
      failed: result.failed_count || 0,
      started_at: trip.scan_progress?.started_at || result.checked_at,
      finished_at: result.checked_at,
      current: null,
    };

    if (!result.complete) {
      trip.state = "partial";
      const openStays = (result.failed_stays || []).length;
      trip.message = `${result.successful_count || 0} von ${result.candidate_count || 0} Aufenthalten sind aktuell vollständig geprüft und wurden übernommen. ${openStays || result.failed_count || 0} technische Prüfung(en) sind noch offen und können unter „Alle ansehen“ gezielt wiederholt werden.`;
      return trip;
    }

    const firstCompleteScan = !trip.initial_scan_completed_at;
    trip.initial_scan_completed_at = trip.initial_scan_completed_at || result.checked_at;
    trip.state = "success";
    trip.message = `${result.candidate_count || 0} mögliche Aufenthalte mit ${trip.search.nights} Nächten im gesamten Suchzeitraum vollständig geprüft.`;

    if (trip.initial_scan_notification_pending === true) {
      const sent = await sendInitialRangeCompletionNotification(trip, result);
      if (sent) trip.initial_scan_notification_pending = false;
    } else if (!firstCompleteScan) {
      await sendPriceChangeNotifications(trip, previousOffers);
    }
    appendHistory(trip, result.checked_at);
    return trip;
  }

  trip.offers = result.offers.map(normalizeOfferProviders);
  trip.search.source_url = result.page_url || trip.search.source_url;
  trip.search.provider_urls = result.provider_urls || trip.search.provider_urls;
  trip.last_check = result.checked_at;
  trip.updated_at = result.checked_at;
  trip.state = "success";
  trip.message = trip.search.include_felicitas === false
    ? `${result.offers.length} Unterkünfte bei Center Parcs direkt geprüft.`
    : `${result.offers.length} Unterkünfte bei Center Parcs, Felicitas und Benefits geprüft.`;
  await sendPriceChangeNotifications(trip, previousOffers);
  appendHistory(trip, result.checked_at);
  return trip;
}

async function checkRangeStay(trip, startDate, endDate) {
  if (trip.search?.mode !== "range") throw new Error("Gezielte Zeitraum-Prüfungen sind nur bei Zeitraum-Beobachtungen möglich.");
  const target = (trip.failed_stays || []).find((stay) => stay.start_date === startDate && stay.end_date === endDate);
  if (!target) throw new Error("Dieser Zeitraum ist nicht mehr als technisch offen markiert.");

  const previousOffers = new Map((trip.offers || []).map((offer) => [offer.code, offer]));
  const exactSearch = exactSearchForStay(trip.search, { start_date: startDate, end_date: endDate });
  exactSearch.mode = "fixed";
  exactSearch.background_range_scan = true;
  exactSearch.source_url = buildSearchUrl(exactSearch, "direct");
  const browser = await launchBrowser();
  const checkedAt = new Date().toISOString();
  let result = null;
  let failures = [];
  try {
    result = await scrapeRangeStayWithTimeout(exactSearch, browser);
    if (Array.isArray(result.provider_errors) && result.provider_errors.length) {
      failures = [{ start_date: startDate, end_date: endDate, providers: result.provider_errors }];
    }
  } catch (error) {
    failures = [{ start_date: startDate, end_date: endDate, providers: [{ provider: "all", message: error.message || String(error) }] }];
  } finally {
    await browser.close().catch(() => {});
  }

  const scan = result ? [{ search: exactSearch, result }] : [];
  const freshOptions = buildRangeOptionsByCode(scan);
  if (result?.offers?.length) trip.catalog_offers = mergeCatalogOffers(trip.catalog_offers || [], result.offers);
  trip.range_options = mergeRangeOptions(
    trip.range_options || {},
    freshOptions,
    [{ start_date: startDate, end_date: endDate }],
    failures,
    checkedAt,
    trip.watched_codes || [],
    { preserve_unsearched: true, previous_check: trip.last_check },
  );

  trip.failed_stays = (trip.failed_stays || []).filter((stay) => !(stay.start_date === startDate && stay.end_date === endDate));
  if (failures.length) trip.failed_stays.push(...failures);
  const currentRangeOffers = aggregateRangeOptions(trip.catalog_offers || [], trip.range_options || {});
  trip.offers = mergeRangeResultsWithCatalog(currentRangeOffers, trip.catalog_offers || []);
  trip.last_check = checkedAt;
  trip.updated_at = checkedAt;
  trip.scan_progress = {
    ...(trip.scan_progress || {}),
    status: trip.failed_stays.length ? "partial" : "complete",
    failed: trip.failed_stays.length,
    finished_at: checkedAt,
    current: null,
  };

  if (trip.failed_stays.length) {
    trip.state = "partial";
    trip.message = `${trip.failed_stays.length} technische Zeitraum-Prüfung(en) sind noch offen. Erfolgreich geprüfte Aufenthalte bleiben aktuell.`;
  } else {
    const firstCompleteScan = !trip.initial_scan_completed_at;
    trip.initial_scan_completed_at = trip.initial_scan_completed_at || checkedAt;
    trip.state = "success";
    trip.message = `Alle Aufenthalte sind aktuell geprüft. Der zuvor offene Zeitraum ${formatGermanDate(startDate)}–${formatGermanDate(endDate)} wurde erfolgreich nachgeholt.`;
    if (trip.initial_scan_notification_pending === true) {
      const sent = await sendInitialRangeCompletionNotification(trip, { candidate_count: trip.search.candidate_count || 0 });
      if (sent) trip.initial_scan_notification_pending = false;
    } else if (!firstCompleteScan) {
      await sendPriceChangeNotifications(trip, previousOffers);
    }
    appendHistory(trip, checkedAt);
  }
  await saveDatabase();
  await publishHomeAssistant();
  return trip;
}

async function checkOneTrip(trip) {
  try {
    await scrapeTrip(trip);
    await saveDatabase();
    await publishHomeAssistant();
  } catch (error) {
    trip.state = "error";
    trip.message = error.message || String(error);
    trip.last_check = new Date().toISOString();
    trip.updated_at = trip.last_check;
    if (trip.search?.mode === "range") {
      trip.scan_progress = {
        ...(trip.scan_progress || {}),
        status: "error",
        finished_at: trip.last_check,
      };
    }
    await saveDatabase();
    throw error;
  }
}

async function runAllScans() {
  if (allScanRunning) return;
  allScanRunning = true;
  let browser;
  try {
    if (database.trips.length) browser = await launchBrowser();
    for (const trip of database.trips) {
      try {
        await scrapeTrip(trip, browser);
      } catch (error) {
        trip.state = "error";
        trip.message = error.message || String(error);
        trip.last_check = new Date().toISOString();
        if (trip.search?.mode === "range") {
          trip.scan_progress = {
            ...(trip.scan_progress || {}),
            status: "error",
            finished_at: trip.last_check,
          };
        }
      }
    }
    database.last_scan = new Date().toISOString();
    updateNextScan();
    await saveDatabase();
    await publishHomeAssistant();
  } finally {
    if (browser) await browser.close().catch(() => {});
    allScanRunning = false;
  }
}

function queueAllScans(reason = "automatisch") {
  if (allScanRunning || allScanQueued) {
    log(`Gesamtprüfung (${reason}) übersprungen: Eine Gesamtprüfung läuft oder wartet bereits.`);
    return Promise.resolve(false);
  }
  allScanQueued = true;
  return queueOperation(async () => {
    allScanQueued = false;
    await runAllScans();
    return true;
  }).finally(() => {
    allScanQueued = false;
  });
}

function updateNextScan() {
  database.next_scan = new Date(
    Date.now() + database.settings.interval_hours * 60 * 60 * 1000,
  ).toISOString();
}

function schedule() {
  if (timer) clearInterval(timer);
  updateNextScan();
  timer = setInterval(
    () => queueAllScans("Zeitplan").catch((error) => log(`Prüfung fehlgeschlagen: ${error.message}`)),
    database.settings.interval_hours * 60 * 60 * 1000,
  );
}

async function homeAssistantRequest(method, entityId, payload) {
  const token = process.env.SUPERVISOR_TOKEN;
  if (!token) return false;
  const response = await fetch(`${HOME_ASSISTANT_API}/states/${entityId}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Home Assistant meldete für ${entityId} Status ${response.status}.`);
  }
  return true;
}

function normalizedNotificationService(value) {
  const text = String(value || "").trim().replace(/^service:/, "");
  if (!text) return "";
  return text.startsWith("notify.") ? text : `notify.${text}`;
}

async function sendNotificationToService(title, message, data, service) {
  const token = process.env.SUPERVISOR_TOKEN;
  if (!token) throw new Error("Push-Mitteilungen können erst innerhalb von Home Assistant getestet werden.");
  const normalizedService = normalizedNotificationService(service);
  if (!normalizedService) throw new Error("Der feste Home-Assistant-Push-Dienst ist ungültig.");
  const serviceName = normalizedService.replace(/^notify\./, "");
  const response = await fetch(
    `${HOME_ASSISTANT_API}/services/notify/${encodeURIComponent(serviceName)}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title, message, data }),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `Push-Dienst ${normalizedService} meldete Status ${response.status}${detail ? `: ${detail.slice(0, 240)}` : "."}`,
    );
  }
  return normalizedService;
}

async function sendNotification(title, message, data = {}) {
  const service = await sendNotificationToService(title, message, data, NOTIFICATION_SERVICE);
  log(`Push erfolgreich an ${service} übergeben: ${title}`);
  return { ok: true, service, fallback: false };
}

async function availableNotificationServices() {
  const token = process.env.SUPERVISOR_TOKEN;
  if (!token) throw new Error("Home Assistant ist außerhalb des Add-ons nicht erreichbar.");
  const response = await fetch(`${HOME_ASSISTANT_API}/services`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(`Home Assistant konnte die Push-Dienste nicht laden (Status ${response.status}).`);
  }
  const domains = await response.json();
  const notify = Array.isArray(domains)
    ? domains.find((entry) => entry.domain === "notify")
    : null;
  return Object.keys(notify?.services || {}).map((serviceName) => `notify.${serviceName}`).sort();
}

function signedEuro(value) {
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toLocaleString("de-DE", { maximumFractionDigits: 0 })} €`;
}

function shortGermanDate(dateString) {
  const [year, month, day] = String(dateString || "").split("-");
  const monthNames = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."];
  const index = Number(month) - 1;
  return year && day && Number.isInteger(index) && monthNames[index] ? `${Number(day)}. ${monthNames[index]}` : "";
}

function shortStayLabel(stay) {
  if (!stay?.start_date || !stay?.end_date) return "";
  const [, startMonth, startDay] = stay.start_date.split("-");
  const [, endMonth] = stay.end_date.split("-");
  return startMonth === endMonth
    ? `${Number(startDay)}.–${shortGermanDate(stay.end_date)}`
    : `${shortGermanDate(stay.start_date)}–${shortGermanDate(stay.end_date)}`;
}

function offerStay(offer) {
  return offer?.best_stay || (offer?.start_date && offer?.end_date
    ? { start_date: offer.start_date, end_date: offer.end_date }
    : null);
}

function globalTripBest(trip, offers) {
  const values = offers instanceof Map ? [...offers.values()] : Array.isArray(offers) ? offers : [];
  return values
    .filter((offer) => offer && (trip.watched_codes || []).includes(offer.code))
    .map((offer) => {
      const normalized = normalizeOfferProviders(offer);
      const price = Number(normalized.best_price ?? normalized.price);
      return Number.isFinite(price) ? {
        offer: normalized,
        code: normalized.code,
        price,
        provider: normalized.best_provider,
        providerName: normalized.best_provider_name || PROVIDERS[normalized.best_provider]?.name || "Center Parcs",
        stay: offerStay(normalized),
      } : null;
    })
    .filter(Boolean)
    .sort((left, right) => left.price - right.price || String(left.code).localeCompare(String(right.code), "de"))[0] || null;
}

function sameStay(left, right) {
  return left?.start_date === right?.start_date && left?.end_date === right?.end_date;
}

function appTripUrl(trip) {
  return `/?trip=${encodeURIComponent(trip.id)}`;
}

async function sendInitialRangeCompletionNotification(trip, result) {
  const best = globalTripBest(trip, trip.offers || []);
  const message = best
    ? `Erster Bestpreis: ${shortStayLabel(best.stay)} ${best.price.toLocaleString("de-DE")} €`
    : `Erste Prüfung abgeschlossen: ${result.candidate_count || 0} Aufenthalte geprüft.`;
  try {
    await sendNotification(
      "Center Parcs Preisüberwachung",
      message,
      {
        url: appTripUrl(trip),
        clickAction: appTripUrl(trip),
        tag: `center_parcs_initial_${trip.id}`,
        group: "center_parcs_preise",
      },
    );
    trip.initial_scan_notification_sent_at = new Date().toISOString();
    trip.notification_error = null;
    return true;
  } catch (error) {
    log(`Abschluss-Push für ${trip.name} konnte nicht gesendet werden: ${error.message}`);
    trip.notification_error = error.message;
    return false;
  }
}

async function sendPriceChangeNotifications(trip, previousOffers) {
  const beforeBest = globalTripBest(trip, previousOffers);
  const currentBest = globalTripBest(trip, trip.offers || []);
  if (!beforeBest || !currentBest) return;

  const priceDifference = currentBest.price - beforeBest.price;
  const stayChanged = !sameStay(beforeBest.stay, currentBest.stay);
  if (priceDifference === 0 && !stayChanged) return;

  const change = {
    at: new Date().toISOString(),
    previous_price: beforeBest.price,
    price: currentBest.price,
    difference: priceDifference,
    previous_stay: beforeBest.stay,
    stay: currentBest.stay,
    code: currentBest.code,
    provider: currentBest.provider,
    provider_name: currentBest.providerName,
  };
  trip.latest_best_change = change;
  const period = shortStayLabel(currentBest.stay) || shortStayLabel(beforeBest.stay) || "Bestpreis";
  const message = priceDifference ? `${period} ${signedEuro(priceDifference)}` : `${period} neuer Bestzeitraum`;
  try {
    await sendNotification("Center Parcs Preisänderung", message, {
      url: appTripUrl(trip),
      clickAction: appTripUrl(trip),
      tag: `center_parcs_best_${trip.id}`,
      group: "center_parcs_preise",
    });
    trip.last_notification = { ...change, type: "trip_best_change" };
    trip.notification_error = null;
  } catch (error) {
    log(`Bestpreis-Push für ${trip.name} konnte nicht gesendet werden: ${error.message}`);
    trip.notification_error = error.message;
  }
  return;

  for (const code of trip.watched_codes || []) {
    const before = previousOffers.get(code) ? normalizeOfferProviders(previousOffers.get(code)) : null;
    const current = findOffer(trip, code);
    if (!before) continue;

    // Verschwindet eine beobachtete Unterkunft komplett aus allen drei
    // Ergebnissen, einmalig melden. Im nächsten Lauf ist sie nicht mehr in
    // previousOffers enthalten und erzeugt daher keine Endlosschleife.
    if (!current) {
      const title = "Center Parcs: Unterkunft nicht mehr verfügbar";
      const message = `${trip.name}: ${offerLabel(before)} wurde bei der aktuellen Prüfung bei keinem der drei Zugänge gefunden.`;
      try {
        await sendNotification(title, message, {
          url: trip.search.source_url,
          clickAction: trip.search.source_url,
          tag: `center_parcs_${trip.id}_${code}`,
          group: "center_parcs_preise",
        });
        trip.last_notification = {
          at: new Date().toISOString(),
          code,
          changes: [{ type: "unavailable_all", providerId: "all" }],
        };
      } catch (error) {
        log(`Push-Mitteilung konnte nicht gesendet werden: ${error.message}`);
        trip.notification_error = error.message;
      }
      continue;
    }

    const changes = collectProviderChanges(before, current, PROVIDER_IDS).map((change) => ({
      ...change,
      providerName: PROVIDERS[change.providerId].name,
    }));
    const beforeStay = before.best_stay || (before.start_date && before.end_date ? { start_date: before.start_date, end_date: before.end_date } : null);
    const currentStay = current.best_stay || (current.start_date && current.end_date ? { start_date: current.start_date, end_date: current.end_date } : null);
    if (trip.search.mode === "range" && beforeStay && currentStay &&
        (beforeStay.start_date !== currentStay.start_date || beforeStay.end_date !== currentStay.end_date)) {
      changes.push({ type: "stay", oldStay: beforeStay, newStay: currentStay });
    }
    if (!changes.length) continue;

    const priceChanges = changes.filter((change) => change.type === "price");
    const newOffers = changes.filter((change) => change.type === "available");
    const lostOffers = changes.filter((change) => change.type === "unavailable");
    const stayChanges = changes.filter((change) => change.type === "stay");

    let title;
    if (changes.length === stayChanges.length) {
      title = "Center Parcs: Günstigster Zeitraum geändert";
    } else if (changes.length === priceChanges.length) {
      const allDown = priceChanges.every((change) => change.difference < 0);
      title = allDown ? "Center Parcs: Preis gesunken" : "Center Parcs: Preis geändert";
    } else if (changes.length === newOffers.length) {
      const partnerOnly = newOffers.every((change) => change.providerId !== "direct");
      title = partnerOnly
        ? "Center Parcs: Neues Partnerangebot verfügbar"
        : "Center Parcs: Angebot wieder verfügbar";
    } else if (changes.length === lostOffers.length) {
      const partnerOnly = lostOffers.every((change) => change.providerId !== "direct");
      title = partnerOnly
        ? "Center Parcs: Partnerangebot nicht mehr verfügbar"
        : "Center Parcs: Angebot nicht mehr verfügbar";
    } else {
      title = "Center Parcs: Angebot geändert";
    }

    const details = changes.map((change) => {
      if (change.type === "price") {
        return `${change.providerName}: ${change.oldPrice.toLocaleString("de-DE")} € → ${change.newPrice.toLocaleString("de-DE")} € (${signedEuro(change.difference)})`;
      }
      if (change.type === "available") {
        return `${change.providerName}: neu verfügbar für ${change.newPrice.toLocaleString("de-DE")} €`;
      }
      if (change.type === "stay") {
        return `Günstigster Zeitraum: ${formatGermanDate(change.oldStay.start_date)}–${formatGermanDate(change.oldStay.end_date)} → ${formatGermanDate(change.newStay.start_date)}–${formatGermanDate(change.newStay.end_date)}`;
      }
      return `${change.providerName}: nicht mehr verfügbar (zuletzt ${change.oldPrice.toLocaleString("de-DE")} €)`;
    }).join(" · ");

    const staySuffix = current.best_stay?.start_date && current.best_stay?.end_date
      ? ` für ${formatGermanDate(current.best_stay.start_date)}–${formatGermanDate(current.best_stay.end_date)}`
      : "";
    const best = current.best_provider_name && Number.isFinite(current.best_price)
      ? ` Günstigster Preis: ${current.best_provider_name} mit ${current.best_price.toLocaleString("de-DE")} €${staySuffix}.`
      : "";
    const message = `${trip.name}: ${offerLabel(current)}. ${details}.${best}`;
    const targetUrl = current.prices?.[current.best_provider]?.source_url || current.detail_url || trip.search.provider_urls?.[current.best_provider] || trip.search.source_url;
    try {
      await sendNotification(title, message, {
        url: targetUrl,
        clickAction: targetUrl,
        tag: `center_parcs_${trip.id}_${code}`,
        group: "center_parcs_preise",
      });
      trip.last_notification = {
        at: new Date().toISOString(),
        code,
        changes,
        best_price: current.best_price,
        best_provider: current.best_provider,
      };
    } catch (error) {
      log(`Push-Mitteilung konnte nicht gesendet werden: ${error.message}`);
      trip.notification_error = error.message;
    }
  }
}

async function publishHomeAssistant() {
  try {
    await homeAssistantRequest("POST", "sensor.center_parcs_preisueberwachung", {
      state: String(database.trips.length),
      attributes: {
        friendly_name: "Center Parcs Preisüberwachung",
        icon: "mdi:home-search",
        aktive_reisen: database.trips.length,
        beobachtete_unterkuenfte: database.trips.reduce(
          (sum, trip) => sum + (trip.watched_codes || []).length,
          0,
        ),
        letzte_pruefung: database.last_scan,
        naechste_pruefung: database.next_scan,
      },
    });

    for (const trip of database.trips) {
      const watched = (trip.watched_codes || []).map((code) => watchSummary(trip, code));
      const availablePrices = watched
        .filter((offer) => offer.available && Number.isFinite(offer.best_price))
        .map((offer) => offer.best_price);
      await homeAssistantRequest("POST", trip.entity_id, {
        state: availablePrices.length ? String(Math.min(...availablePrices)) : "nicht verfügbar",
        attributes: {
          friendly_name: `Center Parcs ${trip.name}`,
          icon: "mdi:currency-eur",
          unit_of_measurement: availablePrices.length ? "€" : undefined,
          park: trip.search.park.name,
          suchmodus: trip.search.mode || "fixed",
          anreise: trip.search.mode === "range" ? undefined : trip.search.start_date,
          abreise: trip.search.mode === "range" ? undefined : trip.search.end_date,
          suchzeitraum_von: trip.search.mode === "range" ? trip.search.range_start : undefined,
          suchzeitraum_bis: trip.search.mode === "range" ? trip.search.range_end : undefined,
          uebernachtungen: trip.search.mode === "range" ? trip.search.nights : undefined,
          erwachsene: trip.search.adults,
          kinderalter: trip.search.child_ages,
          haustiere: trip.search.pets,
          unterkuenfte: watched.map((offer) => ({
            code: offer.code,
            name: offer.name,
            kapazitaet: offer.capacity,
            bester_preis: offer.best_price,
            guenstigster_anbieter: offer.best_provider_name,
            guenstigste_anreise: offer.best_stay?.start_date || null,
            guenstigste_abreise: offer.best_stay?.end_date || null,
            center_parcs_direkt: offer.direct_price,
            felicitas: offer.felicitas_price,
            benefits: offer.benefits_price,
            felicitas_status: offer.felicitas_status_text,
            benefits_status: offer.benefits_status_text,
            tiefstpreis: offer.lowest_price,
            aenderung: offer.change,
            verfuegbar: offer.available,
            bestand: offer.stock,
          })),
          letzte_pruefung: trip.last_check,
          quell_url: trip.search.source_url,
          quell_urls: trip.search.provider_urls,
        },
      });
    }
    database.home_assistant = "Sensoren aktualisiert";
  } catch (error) {
    database.home_assistant = `Fehler: ${error.message}`;
    log(database.home_assistant);
  }
}

async function removeHomeAssistantEntity(entityId) {
  try {
    await homeAssistantRequest("DELETE", entityId);
  } catch (error) {
    log(`Entität ${entityId} konnte nicht entfernt werden: ${error.message}`);
  }
}

app.get("/health", (_request, response) => response.json({ ok: true }));

app.get("/api/state", (_request, response) => {
  response.json(publicState());
});

app.get("/api/parks/:id/available-dates", async (request, response) => {
  try {
    const park = database.parks.find((item) => item.id === request.params.id);
    if (!park) {
      response.status(404).json({ ok: false, message: "Ferienpark nicht gefunden." });
      return;
    }
    const forceRefresh = request.query.refresh === "1";
    const cached = availableDateCache.get(park.id);
    if (!forceRefresh && cached && Date.now() - cached.at < 6 * 60 * 60 * 1000) {
      response.json({ ok: true, park_id: park.id, dates: cached.dates, cached: true });
      return;
    }
    const dates = await fetchAvailableDates(park);
    availableDateCache.set(park.id, { at: Date.now(), dates });
    response.json({ ok: true, park_id: park.id, dates, cached: false });
  } catch (error) {
    response.status(502).json({ ok: false, message: error.message || String(error) });
  }
});

app.post("/api/settings", async (request, response) => {
  database.settings = normalizeSettings({ ...database.settings, ...request.body });
  schedule();
  await saveDatabase();
  response.json({ ok: true, settings: database.settings, next_scan: database.next_scan });
});

app.post("/api/notifications/test", async (_request, response) => {
  try {
    const services = await availableNotificationServices();
    if (!services.includes(NOTIFICATION_SERVICE)) {
      const mobileServices = services.filter((item) => item.startsWith("notify.mobile_app_"));
      throw new Error(
        `Der feste Push-Dienst ${NOTIFICATION_SERVICE} existiert nicht. Verfügbare App-Dienste: ${mobileServices.join(", ") || "keine"}.`,
      );
    }
    const sent = await sendNotification(
      "Center Parcs Preisüberwachung",
      `Test erfolgreich gesendet am ${new Date().toLocaleString("de-DE")}.`,
      { tag: `center_parcs_test_${Date.now()}`, group: "center_parcs_preise" },
    );
    response.json({ ok: true, service: sent.service, message: `Test-Push wurde an ${sent.service} übergeben.` });
  } catch (error) {
    response.status(400).json({ ok: false, message: error.message || String(error) });
  }
});

app.post("/api/parks/discover", (_request, response) => {
  response.status(202).json({ ok: true });
  queueOperation(async () => {
    try {
      const parks = await discoverParks();
      database.parks = mergeParks(database.parks, parks);
      await saveDatabase();
    } catch (error) {
      log(`Parkliste konnte nicht aktualisiert werden: ${error.message}`);
    }
  });
});

app.post("/api/preview", async (request, response) => {
  try {
    const input = request.body || {};
    const search = input.source_url
      ? parseSearchUrl(input.source_url)
      : normalizeSearch(input, database.parks);
    search.include_felicitas = input.include_felicitas !== false;

    let result;
    if (search.mode === "range") {
      result = await queueOperation(() => previewRangeCatalog(search));
      search.source_url = search.park.base_url;
      search.provider_urls = {};
      search.candidate_count = result.candidate_count || 0;
    } else {
      result = await queueOperation(() => scrapeSearch(search));
      search.source_url = result.page_url || search.source_url;
      search.provider_urls = result.provider_urls || Object.fromEntries(
        PROVIDER_IDS.map((providerId) => [providerId, buildSearchUrl(search, providerId)]),
      );
    }

    addPark(search.park);
    const token = crypto.randomUUID();
    const preview = {
      token,
      created_at: new Date().toISOString(),
      search,
      offers: result.offers.map((offer) => search.mode === "range" ? catalogOfferFrom(offer) : normalizeOfferProviders(offer)),
      candidate_count: result.candidate_count || null,
      catalog_only: search.mode === "range",
      catalog_source: result.catalog_source || null,
    };
    cleanPreviewCache();
    previews.set(token, preview);
    await saveDatabase();
    response.json(preview);
  } catch (error) {
    response.status(400).json({ ok: false, message: error.message || String(error) });
  }
});

app.post("/api/trips", async (request, response) => {
  const preview = previews.get(request.body?.preview_token);
  if (!preview) {
    response.status(400).json({ ok: false, message: "Die Vorschau ist abgelaufen. Bitte erneut suchen." });
    return;
  }
  const watched = Array.isArray(request.body.watched_codes)
    ? request.body.watched_codes.filter((code) => preview.offers.some((offer) => offer.code === code))
    : [];
  if (!watched.length) {
    response.status(400).json({ ok: false, message: "Bitte mindestens eine Unterkunft auswählen." });
    return;
  }

  const id = crypto.randomUUID();
  const now = new Date().toISOString();
  const name = String(request.body.name || "").trim() || defaultTripName(preview.search);
  const isRange = preview.search.mode === "range";
  const trip = {
    id,
    name,
    folder: normalizeFolderLabel(request.body.folder, preview.search),
    search: preview.search,
    offers: preview.offers.map((offer) => isRange ? catalogOfferFrom(offer) : normalizeOfferProviders(offer)),
    catalog_offers: isRange ? preview.offers.map(catalogOfferFrom) : undefined,
    watched_codes: watched,
    history: {},
    state: isRange ? "running" : "success",
    message: isRange
      ? `Beobachtung gespeichert. Erste vollständige Zeitraum-Prüfung über ${preview.candidate_count || preview.search.candidate_count || 0} mögliche Aufenthalte startet im Hintergrund.`
      : (preview.search.include_felicitas === false
        ? `${preview.offers.length} Unterkünfte bei Center Parcs direkt gefunden.`
        : `${preview.offers.length} Unterkünfte bei Center Parcs, Felicitas und Benefits gefunden.`),
    scan_progress: isRange ? {
      status: "queued",
      total: preview.candidate_count || preview.search.candidate_count || 0,
      completed: 0,
      successful: 0,
      failed: 0,
      started_at: null,
      current: null,
    } : null,
    initial_scan_notification_pending: isRange,
    initial_scan_completed_at: null,
    range_options: isRange ? {} : undefined,
    last_check: isRange ? null : preview.created_at,
    created_at: now,
    updated_at: now,
    entity_id: `sensor.center_parcs_${entitySlug(name)}_${id.slice(0, 6).replace(/-/g, "")}`,
  };

  if (!isRange) appendHistory(trip, preview.created_at);
  database.trips.push(trip);
  previews.delete(preview.token);
  await saveDatabase();
  await publishHomeAssistant();
  response.status(201).json({ ok: true, trip: publicTrip(trip), background_scan_started: isRange });

  if (isRange) {
    queueOperation(() => checkOneTrip(trip)).catch((error) =>
      log(`Erste Zeitraum-Prüfung für ${trip.name} fehlgeschlagen: ${error.message}`),
    );
  }
});

app.put("/api/trips/:id", async (request, response) => {
  const trip = findTrip(request.params.id);
  const preview = previews.get(request.body?.preview_token);
  if (!trip || !preview) {
    response.status(404).json({ ok: false, message: "Reise oder Vorschau wurde nicht gefunden." });
    return;
  }
  const watched = Array.isArray(request.body.watched_codes)
    ? request.body.watched_codes.filter((code) => preview.offers.some((offer) => offer.code === code))
    : [];
  if (!watched.length) {
    response.status(400).json({ ok: false, message: "Bitte mindestens eine Unterkunft auswählen." });
    return;
  }

  const isRange = preview.search.mode === "range";
  trip.name = String(request.body.name || "").trim() || trip.name;
  trip.folder = normalizeFolderLabel(Object.prototype.hasOwnProperty.call(request.body || {}, "folder") ? request.body.folder : trip.folder, preview.search);
  trip.search = preview.search;
  trip.watched_codes = watched;
  trip.updated_at = new Date().toISOString();

  if (isRange) {
    trip.catalog_offers = mergeCatalogOffers(trip.catalog_offers || [], preview.offers || []);
    trip.offers = mergeRangeResultsWithCatalog([], trip.catalog_offers);
    trip.state = "running";
    trip.message = `Beobachtung aktualisiert. Der komplette Suchzeitraum über ${preview.candidate_count || preview.search.candidate_count || 0} mögliche Aufenthalte wird neu geprüft.`;
    trip.scan_progress = {
      status: "queued",
      total: preview.candidate_count || preview.search.candidate_count || 0,
      completed: 0,
      successful: 0,
      failed: 0,
      started_at: null,
      current: null,
    };
    trip.last_check = null;
    trip.range_options = {};
  } else {
    trip.catalog_offers = undefined;
    trip.offers = preview.offers.map(normalizeOfferProviders);
    trip.last_check = preview.created_at;
    trip.state = "success";
    trip.message = preview.search.include_felicitas === false
      ? `${preview.offers.length} Unterkünfte bei Center Parcs direkt gefunden.`
      : `${preview.offers.length} Unterkünfte bei Center Parcs, Felicitas und Benefits gefunden.`;
    appendHistory(trip, preview.created_at);
  }

  previews.delete(preview.token);
  await saveDatabase();
  await publishHomeAssistant();
  response.json({ ok: true, trip: publicTrip(trip), background_scan_started: isRange });

  if (isRange) {
    queueOperation(() => checkOneTrip(trip)).catch((error) =>
      log(`Zeitraum-Prüfung nach Bearbeitung für ${trip.name} fehlgeschlagen: ${error.message}`),
    );
  }
});

app.patch("/api/trips/:id/folder", async (request, response) => {
  const trip = findTrip(request.params.id);
  if (!trip) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  trip.folder = normalizeFolderLabel(request.body?.folder, trip.search);
  trip.updated_at = new Date().toISOString();
  await saveDatabase();
  await publishHomeAssistant();
  response.json({ ok: true, trip: publicTrip(trip) });
});

app.post("/api/trips/:id/preview", (request, response) => {
  const trip = findTrip(request.params.id);
  if (!trip) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  const token = crypto.randomUUID();
  const isRange = trip.search?.mode === "range";
  const preview = {
    token,
    created_at: new Date().toISOString(),
    search: trip.search,
    offers: isRange ? (trip.catalog_offers || trip.offers || []) : (trip.offers || []),
    candidate_count: trip.search?.candidate_count || null,
    catalog_only: isRange,
    catalog_source: isRange ? "saved" : null,
  };
  cleanPreviewCache();
  previews.set(token, preview);
  response.json(preview);
});

app.post("/api/trips/:id/check", (request, response) => {
  const trip = findTrip(request.params.id);
  if (!trip) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  response.status(202).json({ ok: true });
  queueOperation(() => checkOneTrip(trip)).catch((error) =>
    log(`Prüfung für ${trip.name} fehlgeschlagen: ${error.message}`),
  );
});

app.post("/api/check-all", (_request, response) => {
  if (allScanRunning || allScanQueued) {
    response.status(202).json({ ok: true, already_running: true });
    return;
  }
  response.status(202).json({ ok: true });
  queueAllScans("manuell").catch((error) => log(`Gesamtprüfung fehlgeschlagen: ${error.message}`));
});

app.post("/api/trips/:id/check-stay", async (request, response) => {
  const trip = findTrip(request.params.id);
  if (!trip) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  const startDate = String(request.body?.start_date || "");
  const endDate = String(request.body?.end_date || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate)) {
    response.status(400).json({ ok: false, message: "Ungültiger Reisezeitraum." });
    return;
  }
  const target = (trip.failed_stays || []).find((stay) => stay.start_date === startDate && stay.end_date === endDate);
  if (!target) {
    response.status(409).json({ ok: false, message: "Dieser Zeitraum ist nicht mehr als technisch offen markiert." });
    return;
  }
  for (const code of trip.watched_codes || []) {
    for (const row of trip.range_options?.[code] || []) {
      if (row.start_date === startDate && row.end_date === endDate) row.check_status = "retrying";
    }
  }
  trip.state = "running";
  trip.message = `${formatGermanDate(startDate)}–${formatGermanDate(endDate)} wird gezielt erneut geprüft …`;
  trip.updated_at = new Date().toISOString();
  await saveDatabase();
  response.status(202).json({ ok: true });
  queueOperation(() => checkRangeStay(trip, startDate, endDate)).catch((error) =>
    log(`Gezielte Zeitraum-Prüfung für ${trip.name} fehlgeschlagen: ${error.message}`),
  );
});

app.get("/api/trips/:id/options", (request, response) => {
  const trip = findTrip(request.params.id);
  if (!trip) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  if (trip.search?.mode !== "range") {
    response.status(400).json({ ok: false, message: "Alle Zeiträume gibt es nur bei einer Zeitraum-Beobachtung." });
    return;
  }
  const catalogByCode = new Map((trip.catalog_offers || trip.offers || []).filter((offer) => offer?.code).map((offer) => [offer.code, offer]));
  const houses = (trip.watched_codes || []).map((code) => {
    const offer = findOffer(trip, code) || catalogByCode.get(code) || { code, name: code, capacity: "" };
    const options = Array.isArray(trip.range_options?.[code]) ? trip.range_options[code] : [];
    return {
      code,
      name: offer.name || code,
      capacity: offer.capacity || "",
      comfort: offer.comfort || "",
      image_url: offer.image_url || "",
      best_stay: offer.best_stay || null,
      best_price: Number.isFinite(Number(offer.best_price ?? offer.price)) ? Number(offer.best_price ?? offer.price) : null,
      options,
    };
  });
  response.json({
    trip: {
      id: trip.id,
      name: trip.name,
      search: trip.search,
      travel_folder: travelFolderForTrip(trip),
      scan_progress: trip.scan_progress || null,
      initial_scan_completed_at: trip.initial_scan_completed_at || null,
      failed_stays: trip.failed_stays || [],
    },
    houses,
  });
});

app.get("/api/trips/:id/history/:code", (request, response) => {
  const trip = findTrip(request.params.id);
  if (!trip) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  const startDate = String(request.query.start_date || "");
  const endDate = String(request.query.end_date || "");
  const exactStay = /^\d{4}-\d{2}-\d{2}$/.test(startDate) && /^\d{4}-\d{2}-\d{2}$/.test(endDate);
  const rangePoints = exactStay ? trip.range_history?.[request.params.code]?.[`${startDate}|${endDate}`] : null;
  response.json({
    trip: { id: trip.id, name: trip.name, search: trip.search },
    offer: watchSummary(trip, request.params.code),
    points: Array.isArray(rangePoints) ? rangePoints : historyFor(trip, request.params.code),
    stay: exactStay ? { start_date: startDate, end_date: endDate } : null,
    exact_stay: exactStay,
  });
});

app.delete("/api/trips/:id", async (request, response) => {
  const index = database.trips.findIndex((trip) => trip.id === request.params.id);
  if (index < 0) {
    response.status(404).json({ ok: false, message: "Reise wurde nicht gefunden." });
    return;
  }
  const [removed] = database.trips.splice(index, 1);
  await saveDatabase();
  await removeHomeAssistantEntity(removed.entity_id);
  await publishHomeAssistant();
  response.json({ ok: true });
});

app.get("*", (_request, response) => {
  response.sendFile(path.join(PUBLIC_DIR, "index.html"));
});

async function start() {
  await loadDatabase();
  schedule();
  app.listen(PORT, "0.0.0.0", () => {
    log(`Weboberfläche läuft auf Port ${PORT}.`);
    setTimeout(() => publishHomeAssistant(), 2_000);
    const automaticTasksEnabled = process.env.DISABLE_AUTOMATIC_TASKS !== "1";
    if (automaticTasksEnabled && database.trips.length) {
      setTimeout(
        () => queueAllScans("Start").catch((error) => log(error.message)),
        10_000,
      );
    }
    if (automaticTasksEnabled && database.parks.length <= 1) {
      setTimeout(
        () =>
          queueOperation(async () => {
            try {
              database.parks = mergeParks(database.parks, await discoverParks());
              await saveDatabase();
            } catch (error) {
              log(`Automatische Parkliste konnte nicht geladen werden: ${error.message}`);
            }
          }),
        20_000,
      );
    }
  });
}

if (require.main === module) {
  start().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = {
  appendHistory,
  aggregateRangeOptions,
  globalTripBest,
  mergeRangeOptions,
  rangeStayKey,
  rangeHistoryPoint,
  sameRangeHistoryPoint,
  shortStayLabel,
  defaultTripName,
  normalizeFolderLabel,
  normalizeSettings,
  publicTrip,
  sortTripsByTravelPeriod,
  travelFolderForSearch,
  travelFolderForTrip,
};
