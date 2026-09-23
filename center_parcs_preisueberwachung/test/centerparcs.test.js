"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === "playwright") return { chromium: {} };
  return originalLoad.call(this, request, parent, isMain);
};
const {
  buildProviderAvailabilityUrl,
  buildSearchUrl,
  normalizeSearch,
} = require("../src/centerparcs");
const {
  offersForExactTravelPeriod,
  matchesProviderOffer,
  normalizeHouseInfoUrl,
  partnerArrivalDecision,
  providerAvailabilityContextConfirmed,
  providerContextConfirmed,
} = require("../src/scraper");
Module._load = originalLoad;

const search = {
  park: {
    id: "l2_SL",
    code: "SL",
    name: "Park Hochsauerland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_SL_ferienpark-park-hochsauerland/ferienhaeuser",
  },
  start_date: "2027-01-08",
  end_date: "2027-01-11",
  adults: 2,
  pets: 0,
  child_ages: [5, 8],
};

test("Felicitas price search stays on Felicitas partner page with portal code", () => {
  const url = new URL(buildSearchUrl(search, "felicitas"));
  assert.equal(url.pathname, "/de-de/felicitas_sck");
  assert.equal(url.searchParams.get("facet[PROMOCODE][portalCode]"), "fel_b2c");
  assert.equal(url.searchParams.get("c"), "CPE_SINGLECLICK_ONE");
  assert.equal(url.searchParams.get("type"), "SINGLECLICK_ONE");
  assert.equal(url.searchParams.get("group"), "housing");
  assert.equal(url.searchParams.get("item"), "88");
  assert.equal(url.searchParams.get("facet[DATE]"), search.start_date);
  assert.equal(url.searchParams.get("facet[DATEEND]"), search.end_date);
  assert.equal(url.searchParams.get("facet[COUNTRYSITE][]"), search.park.id);
});

test("Benefits price search stays on Benefits partner page with portal code", () => {
  const url = new URL(buildSearchUrl(search, "benefits"));
  assert.equal(url.pathname, "/de-de/corporate-benefits_sck");
  assert.equal(url.searchParams.get("facet[PROMOCODE][portalCode]"), "corpbe_b2c");
  assert.equal(url.searchParams.get("c"), "CPE_SINGLECLICK_ONE");
  assert.equal(url.searchParams.get("type"), "SINGLECLICK_ONE");
  assert.equal(url.searchParams.get("group"), "housing");
  assert.equal(url.searchParams.get("item"), "115");
  assert.equal(url.searchParams.get("facet[DATE]"), search.start_date);
  assert.equal(url.searchParams.get("facet[DATEEND]"), search.end_date);
  assert.equal(url.searchParams.get("facet[COUNTRYSITE][]"), search.park.id);
});

test("Benefits availability URL stays on partner page and contains no forced travel dates", () => {
  const url = new URL(buildProviderAvailabilityUrl(search, "benefits"));
  assert.equal(url.pathname, "/de-de/corporate-benefits_sck");
  assert.equal(url.searchParams.get("facet[PROMOCODE][portalCode]"), "corpbe_b2c");
  assert.equal(url.searchParams.get("facet[COUNTRYSITE][]"), search.park.id);
  assert.equal(url.searchParams.has("facet[DATE]"), false);
  assert.equal(url.searchParams.has("facet[DATEEND]"), false);
});

test("Felicitas availability URL stays on partner page and contains no forced travel dates", () => {
  const url = new URL(buildProviderAvailabilityUrl(search, "felicitas"));
  assert.equal(url.pathname, "/de-de/felicitas_sck");
  assert.equal(url.searchParams.get("facet[PROMOCODE][portalCode]"), "fel_b2c");
  assert.equal(url.searchParams.get("facet[COUNTRYSITE][]"), search.park.id);
  assert.equal(url.searchParams.has("facet[DATE]"), false);
  assert.equal(url.searchParams.has("facet[DATEEND]"), false);
});

test("A partner arrival date that is not selectable is rejected before price search", () => {
  const result = partnerArrivalDecision(["2027-01-04", "2027-01-11", "2027-01-15"], search);
  assert.equal(result.status, "not_offered");
  assert.equal(result.status_text, "Aktuell nicht im Angebot");
});

test("A partner arrival date that is selectable allows the price search", () => {
  const result = partnerArrivalDecision(["2027-01-04", "2027-01-08", "2027-01-11"], search);
  assert.equal(result.status, "available");
});

test("Missing partner calendar data is never treated as an offer", () => {
  const result = partnerArrivalDecision([], search);
  assert.equal(result.status, "provider_unverified");
});

test("Partner context is not confirmed by the normal search path alone", () => {
  assert.equal(providerContextConfirmed("felicitas", "https://www.centerparcs.de/de-de/search", "normale Seite"), false);
  assert.equal(providerContextConfirmed("benefits", "https://www.centerparcs.de/de-de/search", "normale Seite"), false);
});

test("Partner portal codes confirm the correct provider context", () => {
  assert.equal(providerContextConfirmed(
    "felicitas",
    "https://www.centerparcs.de/de-de/search?facet%5BPROMOCODE%5D%5BportalCode%5D=fel_b2c",
    "",
  ), true);
  assert.equal(providerContextConfirmed(
    "benefits",
    "https://www.centerparcs.de/de-de/search?facet%5BPROMOCODE%5D%5BportalCode%5D=corpbe_b2c",
    "",
  ), true);
});

test("Partner calendar context requires the selected park as well as the partner context", () => {
  const validUrl = "https://www.centerparcs.de/de-de/corporate-benefits_sck?facet%5BPROMOCODE%5D%5BportalCode%5D=corpbe_b2c&facet%5BCOUNTRYSITE%5D%5B%5D=l2_SL";
  const wrongParkUrl = "https://www.centerparcs.de/de-de/corporate-benefits_sck?facet%5BPROMOCODE%5D%5BportalCode%5D=corpbe_b2c&facet%5BCOUNTRYSITE%5D%5B%5D=l2_BS";
  assert.equal(providerAvailabilityContextConfirmed("benefits", validUrl, "", search), true);
  assert.equal(providerAvailabilityContextConfirmed("benefits", wrongParkUrl, "", search), false);
});

test("Exact offer filtering rejects another park or travel period", () => {
  const offers = [
    { park_code: "SL", start_date: "2027-01-08", end_date: "2027-01-11", code: "ok" },
    { park_code: "HE", start_date: "2027-01-08", end_date: "2027-01-11", code: "wrong-park" },
    { park_code: "SL", start_date: "2027-01-11", end_date: "2027-01-15", code: "wrong-date" },
  ];
  assert.deepEqual(offersForExactTravelPeriod(offers, search).map((offer) => offer.code), ["ok"]);
});


test("Benefits rejects a regular early-booker price as partner price", () => {
  assert.equal(matchesProviderOffer({ action_name: "Frühbucher-Rabatt" }, "benefits"), false);
  assert.equal(matchesProviderOffer({ action_name: "Last Minute" }, "benefits"), false);
});

test("Benefits can accept an unlabeled price from the confirmed partner page", () => {
  assert.equal(matchesProviderOffer({ action_name: "" }, "benefits"), true);
});

test("Felicitas is not rejected only because a generic action label is present", () => {
  assert.equal(matchesProviderOffer({ action_name: "Frühbucher-Rabatt" }, "felicitas"), true);
});

test("Load-more matcher recognizes the current Center Parcs partner label", () => {
  const { LOAD_MORE_OFFERS_PATTERN } = require("../src/scraper");
  assert.equal(LOAD_MORE_OFFERS_PATTERN.test("Mehr Ergebnisse anzeigen"), true);
  assert.equal(LOAD_MORE_OFFERS_PATTERN.test("Mehr Unterkünfte anzeigen"), true);
  assert.equal(LOAD_MORE_OFFERS_PATTERN.test("Mehr anzeigen"), true);
  assert.equal(LOAD_MORE_OFFERS_PATTERN.test("Mehr Info"), false);
});

test("Partner result loading clicks 'Mehr Ergebnisse anzeigen' and waits for appended cards", async () => {
  const { loadAllOffers } = require("../src/scraper");
  let offerCount = 10;
  let clicked = false;

  const emptyLocator = {
    count: async () => 0,
    nth() { return this; },
    isVisible: async () => false,
    filter() { return this; },
  };

  const visibleLoadMore = {
    count: async () => (clicked ? 0 : 1),
    nth() { return this; },
    isVisible: async () => !clicked,
    scrollIntoViewIfNeeded: async () => {},
    click: async () => {
      clicked = true;
      offerCount = 13;
    },
    filter() { return this; },
  };

  const page = {
    getByRole(role, options) {
      if (role === "button" && options?.name?.test?.("Mehr Ergebnisse anzeigen")) {
        return visibleLoadMore;
      }
      return emptyLocator;
    },
    getByText() { return emptyLocator; },
    locator() { return emptyLocator; },
    waitForFunction: async () => {},
    waitForTimeout: async () => {},
  };

  const offers = { count: async () => offerCount };
  const result = await loadAllOffers(page, offers);

  assert.equal(result.initial_count, 10);
  assert.equal(result.final_count, 13);
  assert.equal(result.clicks, 1);
});


test("Captured Center Parcs 'Mehr Info' targets are resolved and kept", () => {
  const url = normalizeHouseInfoUrl(
    "https://www.centerparcs.de/de-de/deutschland/fp_SL_ferienpark-park-hochsauerland/ferienhaeuser",
    "/de-de/light/popin/housing?hc=SL1711",
  );
  assert.equal(url, "https://www.centerparcs.de/de-de/light/popin/housing?hc=SL1711");
  assert.equal(normalizeHouseInfoUrl("https://www.centerparcs.de/", "https://example.com/fake"), "");
});

test("UI removes observation-name field, includes clear search, and shows cheapest price per folder", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("Bezeichnung der Beobachtung"), false);
  assert.equal(html.includes("Jede ausgewählte Unterkunft wird automatisch"), false);
  assert.equal(html.includes('id="clear-search"'), true);
  assert.equal(html.includes("Günstigster Preis im Ordner"), true);
  assert.equal(html.includes("Mehr Infos zum Haus"), true);
});

test("Full Center Parcs house-info URL uses responsive cottage page and preserves travel context", () => {
  const { buildHouseInfoPageUrl } = require("../src/centerparcs");
  const url = new URL(buildHouseInfoPageUrl(search, "SL1711", "Comfort-Ferienhaus"));
  assert.equal(
    url.pathname,
    "/de-de/deutschland/fp_SL_ferienpark-park-hochsauerland/ferienhaus/SL1711",
  );
  assert.equal(url.searchParams.get("facet[DATE]"), search.start_date);
  assert.equal(url.searchParams.get("facet[DATEEND]"), search.end_date);
  assert.equal(url.searchParams.get("facet[COUNTRYSITE][]"), search.park.id);
  assert.equal(url.searchParams.get("facet[MULTIPARTICIPANTS][0][adult]"), "2");
  assert.equal(url.searchParams.getAll("facet[MULTIPARTICIPANTS][0][ages][]").join(","), "5,8");
  assert.equal(url.pathname.includes("/light/popin/"), false);
});

test("Nature-wonder houses use the dedicated responsive Center Parcs path", () => {
  const { buildHouseInfoPageUrl } = require("../src/centerparcs");
  const eifelSearch = {
    ...search,
    park: {
      id: "l2_HE",
      code: "HE",
      name: "Park Eifel",
      base_url: "https://www.centerparcs.de/de-de/deutschland/fp_HE_ferienpark-park-eifel/ferienhaeuser",
    },
  };
  const url = new URL(buildHouseInfoPageUrl(eifelSearch, "HE2641", "Naturwunder-Ferienhaus"));
  assert.equal(
    url.pathname,
    "/de-de/deutschland/fp_HE_ferienpark-park-eifel/naturwunder-ferienhaus/HE2641",
  );
});

test("Notification change detector reports newly available partner offers", () => {
  const { collectProviderChanges } = require("../src/notification_changes");
  const before = {
    prices: {
      benefits: { price: null, available: false, status: "not_offered" },
    },
  };
  const current = {
    prices: {
      benefits: { price: 356, available: true, status: "available" },
    },
  };
  assert.deepEqual(collectProviderChanges(before, current, ["benefits"]), [{
    type: "available",
    providerId: "benefits",
    oldPrice: null,
    newPrice: 356,
    difference: null,
    oldStatus: "not_offered",
    newStatus: "available",
  }]);
});

test("Notification change detector reports partner offers that disappear", () => {
  const { collectProviderChanges } = require("../src/notification_changes");
  const before = {
    prices: {
      felicitas: { price: 380, available: true, status: "available" },
    },
  };
  const current = {
    prices: {
      felicitas: { price: null, available: false, status: "not_offered" },
    },
  };
  assert.equal(collectProviderChanges(before, current, ["felicitas"])[0].type, "unavailable");
});

test("Technical partner verification errors do not create false unavailable notifications", () => {
  const { collectProviderChanges } = require("../src/notification_changes");
  const before = {
    prices: {
      benefits: { price: 356, available: true, status: "available" },
    },
  };
  const current = {
    prices: {
      benefits: { price: null, available: false, status: "provider_unverified" },
    },
  };
  assert.deepEqual(collectProviderChanges(before, current, ["benefits"]), []);
});

test("Observation details no longer show folder quick-edit or entity/last-check line", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("data-folder-save"), false);
  assert.equal(html.includes("Ordner speichern"), false);
  assert.equal(html.includes("Entität:"), false);
  assert.equal(html.includes("Letzte Prüfung:"), false);
  assert.equal(html.includes("tone-"), true);
  assert.equal(html.includes("fullHouseInfoUrl"), true);
  assert.equal(html.includes("infoHouseUrl"), true);
});


test("Niedersachsen calendar marks official holidays and school holidays", () => {
  const calendar = require("../public/niedersachsen-calendar");
  assert.equal(calendar.publicHolidayInfo("2027-03-26")?.name, "Karfreitag");
  assert.equal(calendar.publicHolidayInfo("2027-10-31")?.name, "Reformationstag");
  assert.equal(calendar.schoolHolidayInfo("2027-07-08")?.name, "Sommerferien Niedersachsen");
  assert.equal(calendar.schoolHolidayInfo("2027-08-18")?.name, "Sommerferien Niedersachsen");
  assert.equal(calendar.schoolHolidayInfo("2027-08-19"), null);
});

test("Niedersachsen calendar UI includes two distinct colors and legend", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("school-holiday"), true);
  assert.equal(html.includes("public-holiday"), true);
  assert.equal(html.includes("Schulferien NDS"), true);
  assert.equal(html.includes("Feiertag NDS"), true);
});


test("Mobile overview is compact and folders can collapse independently", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("overview-toolbar"), true);
  assert.equal(html.includes("folder-toggle"), true);
  assert.equal(html.includes("mobile-collapsed"), true);
  assert.equal(html.includes("folder-mobile-detail"), true);
  assert.equal(html.includes("comparison-tag-mobile"), true);
  assert.equal(html.includes("houseSummaryHtml"), true);
});

test("Desktop folder layout remains available outside the mobile media query", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("grid-template-columns:minmax(160px,1.05fr) minmax(145px,1fr) minmax(190px,1.35fr) auto auto"), true);
  assert.equal(html.includes("@media(max-width:760px)"), true);
});


test("Mobile folder header is slim, colored and contains only the folder title", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("data-folder-head"), true);
  assert.equal(html.includes(".folder-meta,.folder-best,.folder-mobile-detail{display:none!important}"), true);
  assert.equal(html.includes("background:var(--folder-accent)"), true);
  assert.equal(html.includes("window.matchMedia('(max-width:760px)')"), true);
});


test("Range search normalizes mode, window and 3/4/7 nights", () => {
  const parks = [search.park];
  for (const nights of [3, 4, 7]) {
    const result = normalizeSearch({
      mode: "range",
      park_id: "l2_SL",
      start_date: "2027-03-01",
      end_date: "2027-03-31",
      nights,
      adults: 2,
      pets: 2,
      child_ages: [5, 8],
    }, parks);
    assert.equal(result.mode, "range");
    assert.equal(result.range_start, "2027-03-01");
    assert.equal(result.range_end, "2027-03-31");
    assert.equal(result.nights, nights);
  }
});

test("Range search rejects unsupported night counts", () => {
  assert.throws(() => normalizeSearch({
    mode: "range",
    park_id: "l2_SL",
    start_date: "2027-03-01",
    end_date: "2027-03-31",
    nights: 5,
  }, [search.park]), /3, 4 oder 7/);
});

test("Flexible candidate stays never extend past range end", () => {
  const { buildCandidateStays } = require("../src/flexible_search");
  const flexible = {
    mode: "range",
    range_start: "2027-03-01",
    range_end: "2027-03-31",
    nights: 3,
  };
  const stays = buildCandidateStays(flexible, [
    "2027-03-01",
    "2027-03-28",
    "2027-03-29",
    "2027-03-30",
  ]);
  assert.deepEqual(stays, [
    { start_date: "2027-03-01", end_date: "2027-03-04" },
    { start_date: "2027-03-28", end_date: "2027-03-31" },
  ]);
});

test("Flexible aggregation keeps a separate cheapest stay for each house", () => {
  const { aggregateFlexibleScans } = require("../src/flexible_search");
  const provider = (id, price) => ({
    provider: id,
    provider_name: id === "direct" ? "Center Parcs direkt" : id,
    price,
    available: Number.isFinite(price),
    status: Number.isFinite(price) ? "available" : "unavailable",
    status_text: Number.isFinite(price) ? "Verfügbar" : "Nicht verfügbar",
  });
  const makeOffer = (code, name, direct, felicitas, benefits) => ({
    code,
    name,
    capacity: "4 Personen",
    prices: {
      direct: provider("direct", direct),
      felicitas: provider("felicitas", felicitas),
      benefits: provider("benefits", benefits),
    },
  });
  const result = aggregateFlexibleScans({ mode: "range" }, [
    {
      search: { start_date: "2027-03-05", end_date: "2027-03-08" },
      result: {
        provider_urls: { direct: "https://www.centerparcs.de/a", felicitas: "https://www.centerparcs.de/b", benefits: "https://www.centerparcs.de/c" },
        provider_statuses: { direct: { status: "available" }, felicitas: { status: "available" }, benefits: { status: "available" } },
        offers: [makeOffer("A", "Comfort", 500, 450, 430), makeOffer("B", "Premium", 610, 590, 580)],
      },
    },
    {
      search: { start_date: "2027-03-12", end_date: "2027-03-15" },
      result: {
        provider_urls: { direct: "https://www.centerparcs.de/d", felicitas: "https://www.centerparcs.de/e", benefits: "https://www.centerparcs.de/f" },
        provider_statuses: { direct: { status: "available" }, felicitas: { status: "available" }, benefits: { status: "available" } },
        offers: [makeOffer("A", "Comfort", 390, 370, 360), makeOffer("B", "Premium", 700, 680, 660)],
      },
    },
    {
      search: { start_date: "2027-03-19", end_date: "2027-03-22" },
      result: {
        provider_urls: { direct: "https://www.centerparcs.de/g", felicitas: "https://www.centerparcs.de/h", benefits: "https://www.centerparcs.de/i" },
        provider_statuses: { direct: { status: "available" }, felicitas: { status: "available" }, benefits: { status: "available" } },
        offers: [makeOffer("A", "Comfort", 450, 430, 420), makeOffer("B", "Premium", 520, 500, 465)],
      },
    },
  ]);
  const a = result.offers.find((offer) => offer.code === "A");
  const b = result.offers.find((offer) => offer.code === "B");
  assert.deepEqual(a.best_stay, { start_date: "2027-03-12", end_date: "2027-03-15" });
  assert.equal(a.best_price, 360);
  assert.deepEqual(b.best_stay, { start_date: "2027-03-19", end_date: "2027-03-22" });
  assert.equal(b.best_price, 465);
});

test("Range mode UI is inside New Search and asks for nights only there", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes('id="search-mode-fixed"'), true);
  assert.equal(html.includes('id="search-mode-range"'), true);
  assert.equal(html.includes('id="range-nights"'), true);
  assert.equal(html.includes('id="nights"'), true);
  assert.equal(html.includes("Gewünschte Anzahl Übernachtungen"), true);
  assert.equal(html.includes("Wochenende • 3 Übernachtungen"), true);
  assert.equal(html.includes("Wochenmitte • 4 Übernachtungen"), true);
  assert.equal(html.includes("Woche • 7 Übernachtungen"), true);
  assert.equal(html.includes("Günstigster Aufenthalt"), true);
});

test("Automatic trip checks route range searches through full-window scanner", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes('if (search.mode !== "range") return scrapeOffers(search, browser);'), true);
  assert.equal(server.includes("buildCandidateStays(search, availableDates)"), true);
  assert.equal(server.includes("const result = await scrapeSearch(trip.search, browser, {"), true);
});


test("Flexible scans preload each partner calendar once for the whole window", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes("fetchProviderAvailability(search, providerId, activeBrowser)"), true);
  assert.equal(server.includes("exactSearch.partner_availability = partnerAvailability"), true);
});

test("Range search notifies when the overall cheapest stay changes", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes('type: "stay"'), true);
  assert.equal(server.includes("Günstigster Zeitraum geändert"), true);
});


test("Range preview loads house types first instead of scanning the whole window", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(server.includes("previewRangeCatalog(search)"), true);
  assert.equal(server.includes("catalog_only: search.mode === \"range\""), true);
  assert.equal(html.includes("Preisprüfung startet nach dem Speichern"), true);
  assert.equal(html.includes("Die erste vollständige Zeitraum-Prüfung läuft jetzt im Hintergrund"), true);
});

test("New range observations are queued and scanned in the background", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes('initial_scan_notification_pending: isRange'), true);
  assert.equal(server.includes('status: "queued"'), true);
  assert.equal(server.includes('queueOperation(() => checkOneTrip(trip))'), true);
  assert.equal(server.includes('background_scan_started: isRange'), true);
});

test("Range background scans persist progress and continue past individual provider errors", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  const scraper = fs.readFileSync(path.join(__dirname, "../src/scraper.js"), "utf8");
  assert.equal(server.includes("onProgress"), true);
  assert.equal(server.includes("failedStays.push"), true);
  assert.equal(server.includes("await saveDatabase();"), true);
  assert.equal(scraper.includes("background_range_scan"), true);
  assert.equal(scraper.includes("allow_empty_after_timeout"), true);
  assert.equal(scraper.includes("providerErrors.push"), true);
});

test("First complete range scan sends one dedicated completion notification", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes("sendInitialRangeCompletionNotification"), true);
  assert.equal(server.includes("Center Parcs: Erste Zeitraum-Prüfung abgeschlossen"), true);
  assert.equal(server.includes("initial_scan_notification_sent_at"), true);
  assert.equal(server.includes("if (sent) trip.initial_scan_notification_pending = false"), true);
});

test("Incomplete recurring range scans apply fresh stays and isolate technical failures", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes("mergeRangeOptions("), true);
  assert.equal(server.includes("aggregateRangeOptions(trip.catalog_offers || [], trip.range_options || {})"), true);
  assert.equal(server.includes("Die zuletzt vollständig ermittelten Bestpreise bleiben angezeigt"), false);
  assert.equal(server.includes("unter „Alle ansehen“ gezielt wiederholt werden"), true);
  assert.equal(server.includes('status: result.complete ? "complete" : "partial"'), true);
});

test("Flexible scan stores every priced stay for later 'Alle ansehen' list", () => {
  const { buildRangeOptionsByCode } = require("../src/flexible_search");
  const scans = [
    {
      search: { start_date: "2027-01-08", end_date: "2027-01-11" },
      result: {
        provider_urls: {
          direct: "https://www.centerparcs.de/direct-1",
          felicitas: "https://www.centerparcs.de/felicitas-1",
          benefits: "https://www.centerparcs.de/benefits-1",
        },
        provider_statuses: {
          direct: { status: "available", status_text: "Verfügbar" },
          felicitas: { status: "available", status_text: "Verfügbar" },
          benefits: { status: "not_offered", status_text: "Aktuell nicht im Angebot" },
        },
        offers: [{
          code: "SL1711",
          prices: {
            direct: { provider: "direct", provider_name: "Center Parcs direkt", price: 405, available: true },
            felicitas: { provider: "felicitas", provider_name: "Felicitas", price: 390, available: true },
            benefits: { provider: "benefits", provider_name: "Benefits", price: null, available: false, status: "not_offered" },
          },
        }],
      },
    },
    {
      search: { start_date: "2027-01-15", end_date: "2027-01-18" },
      result: {
        provider_urls: {
          direct: "https://www.centerparcs.de/direct-2",
          felicitas: "https://www.centerparcs.de/felicitas-2",
          benefits: "https://www.centerparcs.de/benefits-2",
        },
        provider_statuses: {
          direct: { status: "available", status_text: "Verfügbar" },
          felicitas: { status: "available", status_text: "Verfügbar" },
          benefits: { status: "available", status_text: "Verfügbar" },
        },
        offers: [{
          code: "SL1711",
          prices: {
            direct: { provider: "direct", provider_name: "Center Parcs direkt", price: 380, available: true },
            felicitas: { provider: "felicitas", provider_name: "Felicitas", price: 375, available: true },
            benefits: { provider: "benefits", provider_name: "Benefits", price: 360, available: true },
          },
        }],
      },
    },
  ];
  const options = buildRangeOptionsByCode(scans);
  assert.equal(options.SL1711.length, 2);
  assert.equal(options.SL1711[0].best_price, 390);
  assert.equal(options.SL1711[0].best_provider, "felicitas");
  assert.equal(options.SL1711[0].prices.benefits.status, "not_offered");
  assert.equal(options.SL1711[1].best_price, 360);
  assert.equal(options.SL1711[1].best_provider, "benefits");
});

test("Range observation UI offers four action buttons including Alle ansehen", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("data-options"), true);
  assert.equal(html.includes("Alle ansehen"), true);
  assert.equal(html.includes("trip-actions"), true);
  assert.equal(html.includes("view-options"), true);
});

test("Background refresh avoids rebuilding unchanged observation cards and image elements", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.equal(html.includes("overviewRenderSignature"), true);
  assert.equal(html.includes("overviewSignatureFor"), true);
  assert.equal(html.includes("updateLiveTripStatus"), true);
});

test("Push delivery is pinned to primary iPhone and range-options endpoint is available", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(server.includes('const NOTIFICATION_SERVICE = "notify.mobile_app_iphone A"'), true);
  assert.equal(server.includes("notificationFallbackCandidates"), false);
  assert.equal(server.includes("Push-Fallback erfolgreich"), false);
  assert.equal(server.includes('/api/trips/:id/options'), true);
});

test("Push target is not editable in app settings", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  const config = fs.readFileSync(path.join(__dirname, "../config.yaml"), "utf8");
  assert.equal(html.includes('id="notification-service"'), false);
  assert.equal(html.includes("Push-Ziel fest"), true);
  assert.equal(html.includes("primary iPhone"), true);
  assert.equal(config.includes("notification_service:"), false);
});


test("Current range aggregation ignores stale or partial rows when choosing the best price", () => {
  const { aggregateRangeOptions } = require("../src/flexible_search");
  const provider = (id, price) => ({
    provider: id,
    provider_name: id,
    price,
    available: Number.isFinite(price),
    status: Number.isFinite(price) ? "available" : "unavailable",
  });
  const offers = aggregateRangeOptions([{ code: "SL1711", name: "Comfort-Ferienhaus" }], {
    SL1711: [
      {
        start_date: "2027-01-08", end_date: "2027-01-11", check_status: "current",
        prices: { direct: provider("direct", 485), felicitas: provider("felicitas", 429), benefits: provider("benefits", 402) },
      },
      {
        start_date: "2027-01-15", end_date: "2027-01-18", check_status: "stale",
        prices: { direct: provider("direct", 431), felicitas: provider("felicitas", 382), benefits: provider("benefits", 358) },
      },
    ],
  });
  assert.equal(offers.length, 1);
  assert.equal(offers[0].best_price, 402);
  assert.deepEqual(offers[0].best_stay, { start_date: "2027-01-08", end_date: "2027-01-11" });
});

test("Range UI exposes targeted retry and exact Center Parcs search links", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  const server = fs.readFileSync(path.join(__dirname, "../src/server.js"), "utf8");
  assert.equal(html.includes("Nur diesen Zeitraum erneut prüfen"), true);
  assert.equal(html.includes("exactProviderUrl"), true);
  assert.equal(html.includes("Aktuell geprüft"), true);
  assert.equal(server.includes('/api/trips/:id/check-stay'), true);
  assert.equal(server.includes("scrapeRangeStayWithTimeout"), true);
});

test("Price parsing is intentionally unchanged in the partial-refresh release", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const centerparcs = fs.readFileSync(path.join(__dirname, "../src/centerparcs.js"), "utf8");
  assert.equal(centerparcs.includes("active.rawBeforeTax ?? active.valueBeforeTax ?? active.value"), true);
});
