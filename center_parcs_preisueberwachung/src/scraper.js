"use strict";

const { chromium } = require("playwright");
const {
  PROVIDERS,
  buildHouseInfoPageUrl,
  buildHousePageUrl,
  buildProviderAvailabilityUrl,
  buildSearchUrl,
  offerFromDataset,
} = require("./centerparcs");

const COUNTRY_ORDER = ["Deutschland", "Niederlande", "Belgien", "Frankreich", "Dänemark"];

const DEFAULT_PARKS = [
  {
    id: "l2_BS", code: "BS", name: "Bispinger Heide", country: "Deutschland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_BS_ferienpark-bispinger-heide/ferienhaeuser",
  },
  {
    id: "l2_AG", code: "AG", name: "Park Allgäu", country: "Deutschland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_AG_ferienpark-park-allgaeu/ferienhaeuser",
  },
  {
    id: "l2_BT", code: "BT", name: "Park Bostalsee", country: "Deutschland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_BT_ferienpark-park-bostalsee/ferienhaeuser",
  },
  {
    id: "l2_SL", code: "SL", name: "Park Hochsauerland", country: "Deutschland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_SL_ferienpark-park-hochsauerland/ferienhaeuser",
  },
  {
    id: "l2_BK", code: "BK", name: "Park Nordseeküste", country: "Deutschland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_BK_ferienpark-park-nordseekueste/ferienhaeuser",
  },
  {
    id: "l2_HE", code: "HE", name: "Park Eifel", country: "Deutschland",
    base_url: "https://www.centerparcs.de/de-de/deutschland/fp_HE_ferienpark-park-eifel/ferienhaeuser",
  },
  {
    id: "l2_NO", code: "NO", name: "Nordborg Resort", country: "Dänemark",
    base_url: "https://www.centerparcs.de/de-de/danemark/fp_NO_ferienpark-nordborg-resort/ferienhaeuser",
  },
  {
    id: "l2_HB", code: "HB", name: "Het Heijderbos", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_HB_ferienpark-het-heijderbos/ferienhaeuser",
  },
  {
    id: "l2_EH", code: "EH", name: "De Eemhof", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_EH_ferienpark-de-eemhof/ferienhaeuser",
  },
  {
    id: "l2_PZ", code: "PZ", name: "Port Zélande", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_PZ_ferienpark-port-zelande/ferienhaeuser",
  },
  {
    id: "l2_ZV", code: "ZV", name: "Park Zandvoort", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_ZV_ferienpark-park-zandvoort/ferienhaeuser",
  },
  {
    id: "l2_MD", code: "MD", name: "Het Meerdal", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_MD_ferienpark-het-meerdal/ferienhaeuser",
  },
  {
    id: "l2_HH", code: "HH", name: "De Huttenheugte", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_HH_ferienpark-de-huttenheugte/ferienhaeuser",
  },
  {
    id: "l2_KV", code: "KV", name: "De Kempervennen", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_KV_ferienpark-de-kempervennen/ferienhaeuser",
  },
  {
    id: "l2_LH", code: "LH", name: "Limburgse Peel", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_LH_ferienpark-limburgse-peel/ferienhaeuser",
  },
  {
    id: "l2_SR", code: "SR", name: "Parc Sandur", country: "Niederlande",
    base_url: "https://www.centerparcs.de/de-de/niederlande/fp_SR_ferienpark-parc-sandur/ferienhaeuser",
  },
  {
    id: "l2_TH", code: "TH", name: "Terhills Resort", country: "Belgien",
    base_url: "https://www.centerparcs.de/de-de/belgien/fp_TH_ferienpark-terhills-resort/ferienhaeuser",
  },
  {
    id: "l2_VM", code: "VM", name: "De Vossemeren", country: "Belgien",
    base_url: "https://www.centerparcs.de/de-de/belgien/fp_VM_ferienpark-de-vossemeren/ferienhaeuser",
  },
  {
    id: "l2_EP", code: "EP", name: "Erperheide", country: "Belgien",
    base_url: "https://www.centerparcs.de/de-de/belgien/fp_EP_ferienpark-erperheide/ferienhaeuser",
  },
  {
    id: "l2_AR", code: "AR", name: "Les Ardennes", country: "Belgien",
    base_url: "https://www.centerparcs.de/de-de/belgien/fp_AR_ferienpark-les-ardennes/ferienhaeuser",
  },
  {
    id: "l2_HA", code: "HA", name: "Park De Haan", country: "Belgien",
    base_url: "https://www.centerparcs.de/de-de/belgien/fp_HA_ferienpark-park-de-haan/ferienhaeuser",
  },
  {
    id: "l2_LG", code: "LG", name: "Les Landes de Gascogne", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_LG_ferienpark-les-landes-de-gascogne/ferienhaeuser",
  },
  {
    id: "l2_TF", code: "TF", name: "Les Trois Forêts", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_TF_ferienpark-les-trois-forets/ferienhaeuser",
  },
  {
    id: "l2_LA", code: "LA", name: "Le Lac d'Ailette", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_LA_ferienpark-le-lac-d-ailette/ferienhaeuser",
  },
  {
    id: "l2_VN", code: "VN", name: "Villages Nature Paris", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_VN_ferienpark-villages-nature-paris/ferienhaeuser",
  },
  {
    id: "l2_BF", code: "BF", name: "Les Bois-Francs", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_BF_ferienpark-les-bois-francs/ferienhaeuser",
  },
  {
    id: "l2_CH", code: "CH", name: "Les Hauts de Bruyères", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_CH_ferienpark-les-hauts-de-bruyeres/ferienhaeuser",
  },
  {
    id: "l2_BD", code: "BD", name: "Le Bois aux Daims", country: "Frankreich",
    base_url: "https://www.centerparcs.de/de-de/frankreich/fp_BD_ferienpark-le-bois-aux-daims/ferienhaeuser",
  },
];

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

async function launchBrowser() {
  return chromium.launch({
    headless: true,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });
}

async function acceptCookies(page) {
  const choices = [
    page.getByRole("button", { name: /alle akzeptieren/i }),
    page.getByRole("button", { name: /akzeptieren/i }),
    page.locator("#didomi-notice-agree-button"),
  ];
  for (const choice of choices) {
    try {
      if (await choice.first().isVisible()) {
        await choice.first().click({ timeout: 3_000 });
        return;
      }
    } catch {
      // Der Banner ist nicht auf jeder Seite vorhanden.
    }
  }
}

async function waitForOffers(page, options = {}) {
  const offers = page.locator(".accCart-bookingButton.js-booking");
  const timeoutMs = Number.isFinite(Number(options.timeout_ms))
    ? Math.max(5_000, Number(options.timeout_ms))
    : 60_000;
  const allowEmptyAfterTimeout = options.allow_empty_after_timeout === true;
  try {
    await offers.first().waitFor({ state: "visible", timeout: timeoutMs });
  } catch {
    const body = await page.locator("body").innerText({ timeout: 5_000 }).catch(() => "");
    if (/keine.*unterk(?:u|ü)nfte|nicht verfügbar|keine verfügbare/i.test(body)) {
      return offers;
    }
    if (allowEmptyAfterTimeout) {
      log(`Center Parcs hat nach ${Math.round(timeoutMs / 1000)} Sekunden keine Unterkunftskarten geliefert; dieser einzelne Zeitraum wird als leer weiterverarbeitet.`);
      return offers;
    }
    throw new Error(
      `Center Parcs hat innerhalb von ${Math.round(timeoutMs / 1000)} Sekunden keine Unterkunftsliste geliefert.`,
    );
  }
  return offers;
}

const LOAD_MORE_OFFERS_PATTERN = /mehr(?:e|ere)?(?:\s+(?:ergebnisse|unterk(?:ü|u)nfte))?\s+anzeigen/i;

async function firstVisible(locator) {
  const count = await locator.count().catch(() => 0);
  for (let index = 0; index < count; index += 1) {
    const candidate = locator.nth(index);
    if (await candidate.isVisible().catch(() => false)) return candidate;
  }
  return null;
}

async function findLoadMoreOffersControl(page) {
  const candidates = [
    page.getByRole("button", { name: LOAD_MORE_OFFERS_PATTERN }),
    page.getByRole("link", { name: LOAD_MORE_OFFERS_PATTERN }),
    page.locator('button, a, [role="button"]').filter({ hasText: LOAD_MORE_OFFERS_PATTERN }),
    page.getByText(LOAD_MORE_OFFERS_PATTERN),
  ];

  for (const locator of candidates) {
    const visible = await firstVisible(locator);
    if (visible) return visible;
  }
  return null;
}

function normalizeHouseInfoUrl(baseUrl, value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw, baseUrl || "https://www.centerparcs.de/");
    if (url.protocol !== "https:" || !/(^|\.)centerparcs\.de$/i.test(url.hostname)) return "";
    return url.toString();
  } catch {
    return "";
  }
}

async function loadAllOffers(page, offers) {
  const initialCount = await offers.count();
  let clicks = 0;

  for (let attempt = 0; attempt < 12; attempt += 1) {
    const before = await offers.count();
    const more = await findLoadMoreOffersControl(page);
    if (!more) break;

    await more.scrollIntoViewIfNeeded().catch(() => {});
    await more.click({ force: true, timeout: 10_000 });
    clicks += 1;

    await page.waitForFunction(
      ({ selector, previousCount }) =>
        document.querySelectorAll(selector).length > previousCount,
      { selector: ".accCart-bookingButton.js-booking", previousCount: before },
      { timeout: 10_000 },
    ).catch(async () => {
      await page.waitForTimeout(1_200);
    });

    const after = await offers.count();
    if (after <= before) break;
  }

  return {
    initial_count: initialCount,
    final_count: await offers.count(),
    clicks,
  };
}

function parseAvailableDates(html) {
  const source = String(html || "");
  const match = source.match(/(?:var\s+)?arrAvailableDates\s*=\s*(\[[\s\S]*?\])\s*;/i);
  if (!match) return [];
  try {
    return [...new Set(JSON.parse(match[1]).filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value)))].sort();
  } catch {
    return [];
  }
}

async function readAvailableDatesFromPage(page) {
  const globalDates = await page.evaluate(() => {
    const candidates = [
      globalThis.arrAvailableDates,
      globalThis.availableDates,
      globalThis.__AVAILABLE_DATES__,
    ];
    for (const candidate of candidates) {
      if (Array.isArray(candidate)) return candidate;
    }
    return [];
  }).catch(() => []);

  const normalizedGlobal = [...new Set((Array.isArray(globalDates) ? globalDates : [])
    .map((value) => String(value || "").trim())
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value)))].sort();
  if (normalizedGlobal.length) return normalizedGlobal;

  return parseAvailableDates(await page.content());
}

function partnerArrivalDecision(availableDates, search) {
  const dates = Array.isArray(availableDates) ? availableDates : [];
  if (!dates.length) {
    return {
      status: "provider_unverified",
      status_text: "Partner-Anreisetage konnten nicht geprüft werden",
    };
  }
  if (!dates.includes(search.start_date)) {
    return {
      status: "not_offered",
      status_text: "Aktuell nicht im Angebot",
    };
  }
  return { status: "available", status_text: "Anreisetag im Partnerangebot" };
}

function offersForExactTravelPeriod(offers, search) {
  const expectedParkCode = String(search?.park?.code || "").trim().toUpperCase();
  return (Array.isArray(offers) ? offers : []).filter((offer) => {
    const offerParkCode = String(offer?.park_code || "").trim().toUpperCase();
    return (
      offer.start_date === search.start_date &&
      offer.end_date === search.end_date &&
      (!expectedParkCode || !offerParkCode || offerParkCode === expectedParkCode)
    );
  });
}

// Der Anbieter-Kontext wird primär über die echte Partnerseite und den Portalcode
// bestätigt. Bei Corporate Benefits dürfen normale Center-Parcs-Aktionspreise
// jedoch nicht als Mitarbeiterpreis durchrutschen: Laut Angebotsbedingungen ist
// das Corporate-Benefits-Angebot nicht mit Frühbucher- oder anderen regulären
// Center-Parcs-Angeboten kombinierbar.
function matchesProviderOffer(offer, providerId) {
  if (providerId !== "benefits") return true;
  const action = String(offer?.action_name || "").trim().toLowerCase();
  if (!action) return true;
  return !/(frühbuch|fruehbuch|last[ -]?minute|wochenvorteil|friends|willkommens|newsletter)/i.test(action);
}

function providerContextConfirmed(providerId, pageUrl, html = "") {
  if (providerId === "direct") return true;
  const provider = PROVIDERS[providerId] || {};
  let parsed = null;
  try {
    parsed = new URL(String(pageUrl || ""));
  } catch {
    // Die HTML-Signatur kann den Kontext trotzdem noch bestätigen.
  }

  const portalCode = parsed?.searchParams.get("facet[PROMOCODE][portalCode]") || "";
  const pathMatches = Boolean(
    parsed && (
      (provider.expected_path && parsed.pathname === provider.expected_path) ||
      (provider.landing_path && parsed.pathname === provider.landing_path)
    )
  );
  const portalMatches = Boolean(provider.portal_code && portalCode === provider.portal_code);
  const source = String(html || "");

  if (providerId === "felicitas") {
    const pageSignature = /(?:felicitas-angebot|felicitas-rabatt|felicitas)/i.test(source);
    return portalMatches || (pathMatches && pageSignature);
  }
  if (providerId === "benefits") {
    const pageSignature = /(?:ihr exklusives angebot|mitarbeiter[\s-]*rabatt|corporate[\s-]*benefits)/i.test(source);
    return portalMatches || (pathMatches && pageSignature);
  }
  return false;
}

function providerAvailabilityContextConfirmed(providerId, pageUrl, html, search) {
  if (!providerContextConfirmed(providerId, pageUrl, html)) return false;
  let parsed;
  try {
    parsed = new URL(String(pageUrl || ""));
  } catch {
    return false;
  }
  const selectedParks = parsed.searchParams.getAll("facet[COUNTRYSITE][]");
  return selectedParks.includes(String(search?.park?.id || ""));
}

async function fetchAvailableDates(park) {
  const response = await fetch(park.base_url, {
    headers: {
      "Accept-Language": "de-DE,de;q=0.9",
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/138 Safari/537.36",
    },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    throw new Error(`Center Parcs meldete beim Kalender Status ${response.status}.`);
  }
  const dates = parseAvailableDates(await response.text());
  if (!dates.length) {
    throw new Error("Center Parcs hat für diesen Park keine buchbaren Anreisetage geliefert.");
  }
  return dates;
}

function providerSnapshot(offer, providerId, result = {}) {
  if (!offer) {
    const notOffered = result.status === "not_offered";
    const unverified = result.status === "provider_unverified";
    return {
      provider: providerId,
      provider_name: PROVIDERS[providerId].name,
      price: null,
      available: false,
      stock: 0,
      in_offer: false,
      status: unverified ? "provider_unverified" : (notOffered ? "not_offered" : "unavailable"),
      status_text: result.status_text || (unverified
        ? "Partnerzugang nicht bestätigt"
        : (notOffered ? "Aktuell nicht im Angebot" : "Nicht verfügbar")),
      checked_at: result.checked_at || null,
    };
  }
  return {
    provider: providerId,
    provider_name: PROVIDERS[providerId].name,
    price: offer.price,
    original_price: offer.original_price,
    total_with_tax: offer.total_with_tax,
    pet_fee: offer.pet_fee,
    discount_percent: offer.discount_percent,
    stock: offer.stock,
    action_name: offer.action_name,
    available: offer.available,
    in_offer: true,
    status: offer.available ? "available" : "unavailable",
    status_text: offer.available ? "Verfügbar" : "Nicht verfügbar",
    checked_at: result.checked_at || null,
  };
}

function mergeProviderResults(results) {
  const byCode = new Map();
  for (const providerId of Object.keys(PROVIDERS)) {
    for (const offer of results[providerId]?.offers || []) {
      if (!byCode.has(offer.code)) byCode.set(offer.code, {});
      byCode.get(offer.code)[providerId] = offer;
    }
  }
  return [...byCode.entries()].map(([code, offers]) => {
    const base = Object.keys(PROVIDERS).map((providerId) => offers[providerId]).find(Boolean);
    const prices = Object.fromEntries(
      Object.keys(PROVIDERS).map((providerId) => [
        providerId,
        providerSnapshot(offers[providerId], providerId, results[providerId]),
      ]),
    );
    const available = Object.values(prices)
      .filter((item) => item.available && Number.isFinite(item.price))
      .sort((left, right) => left.price - right.price);
    const best = available[0] || null;
    return {
      ...base,
      code,
      prices,
      price: best?.price ?? null,
      original_price: best?.original_price ?? null,
      total_with_tax: best?.total_with_tax ?? null,
      pet_fee: best?.pet_fee ?? null,
      discount_percent: best?.discount_percent ?? 0,
      stock: best?.stock ?? 0,
      action_name: best?.action_name || "",
      available: Boolean(best),
      best_price: best?.price ?? null,
      best_provider: best?.provider ?? null,
      best_provider_name: best?.provider_name ?? "",
    };
  }).sort((left, right) => {
    if (left.price === null) return 1;
    if (right.price === null) return -1;
    return left.price - right.price;
  });
}

async function fetchProviderAvailability(search, providerId, activeBrowser) {
  if (providerId === "direct") {
    return { status: "available", status_text: "Verfügbar", available_dates: [], page_url: search.park.base_url };
  }
  const provider = PROVIDERS[providerId];
  const context = await activeBrowser.newContext({ locale: "de-DE" });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  const availabilityUrl = buildProviderAvailabilityUrl(search, providerId);
  try {
    await page.goto(availabilityUrl || provider.landing_url, {
      waitUntil: "domcontentloaded",
      timeout: 90_000,
    });
    await acceptCookies(page);
    await page.waitForTimeout(1_000);
    const availabilityHtml = await page.content();
    if (!providerAvailabilityContextConfirmed(providerId, page.url(), availabilityHtml, search)) {
      return {
        provider: providerId,
        status: "provider_unverified",
        status_text: "Partner-Kalender konnte nicht sicher bestätigt werden",
        available_dates: [],
        page_url: page.url(),
        requested_url: availabilityUrl,
      };
    }
    const availableDates = await readAvailableDatesFromPage(page);
    return {
      provider: providerId,
      status: "available",
      status_text: "Partner-Kalender bestätigt",
      available_dates: availableDates,
      page_url: page.url(),
      requested_url: availabilityUrl,
    };
  } finally {
    await context.close().catch(() => {});
  }
}

async function scrapeProvider(search, providerId, activeBrowser) {
  const context = await activeBrowser.newContext({ locale: "de-DE" });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  try {
    const provider = PROVIDERS[providerId];
    log(`${provider.name} wird geprüft: ${search.park.name}, ${search.start_date} bis ${search.end_date}`);
    let availableDates = [];
    let availabilityUrl = null;

    if (providerId !== "direct") {
      const preloaded = search.partner_availability?.[providerId] || null;
      if (preloaded) {
        availabilityUrl = preloaded.requested_url || buildProviderAvailabilityUrl(search, providerId);
        availableDates = Array.isArray(preloaded.available_dates) ? preloaded.available_dates : [];
        if (preloaded.status === "provider_unverified") {
          log(`${provider.name}: vorgeladener Partner-Kalender konnte nicht sicher bestätigt werden.`);
          return {
            provider: providerId,
            checked_at: new Date().toISOString(),
            page_url: preloaded.page_url || availabilityUrl,
            requested_url: availabilityUrl,
            availability_url: availabilityUrl,
            status: "provider_unverified",
            status_text: preloaded.status_text || "Partner-Kalender konnte nicht sicher bestätigt werden",
            available_dates: [],
            offers: [],
          };
        }
      } else {
        const availability = await fetchProviderAvailability(search, providerId, activeBrowser);
        availabilityUrl = availability.requested_url || buildProviderAvailabilityUrl(search, providerId);
        availableDates = availability.available_dates || [];
        if (availability.status === "provider_unverified") {
          log(`${provider.name}: Partner-Kalender-Kontext für Park ${search.park.id} konnte auf ${availability.page_url} nicht bestätigt werden.`);
          return {
            provider: providerId,
            checked_at: new Date().toISOString(),
            page_url: availability.page_url,
            requested_url: availabilityUrl,
            availability_url: availabilityUrl,
            status: availability.status,
            status_text: availability.status_text,
            available_dates: [],
            offers: [],
          };
        }
      }

      const arrivalDecision = partnerArrivalDecision(availableDates, search);
      log(`${provider.name}: Partner-Kalender ${availableDates.length} Anreisetage; ${search.start_date} => ${arrivalDecision.status}`);

      if (arrivalDecision.status !== "available") {
        return {
          provider: providerId,
          checked_at: new Date().toISOString(),
          page_url: search.partner_availability?.[providerId]?.page_url || availabilityUrl,
          requested_url: availabilityUrl,
          availability_url: availabilityUrl,
          status: arrivalDecision.status,
          status_text: arrivalDecision.status_text,
          available_dates: availableDates,
          offers: [],
        };
      }
    }

    const providerSearchUrl = buildSearchUrl(search, providerId);
    const rangeLikeScan = search.background_range_scan === true || search.catalog_preview === true;
    const navigationTimeout = search.catalog_preview === true ? 30_000 : (rangeLikeScan ? 60_000 : 90_000);
    await page.goto(providerSearchUrl, {
      waitUntil: "domcontentloaded",
      timeout: navigationTimeout,
    });
    await acceptCookies(page);
    const pageHtml = await page.content();
    if (providerId === "direct") availableDates = parseAvailableDates(pageHtml);

    if (!providerContextConfirmed(providerId, page.url(), pageHtml)) {
      log(`${provider.name}: Partnerkontext konnte auf ${page.url()} nicht bestätigt werden.`);
      return {
        provider: providerId,
        checked_at: new Date().toISOString(),
        page_url: page.url(),
        requested_url: providerSearchUrl,
        availability_url: availabilityUrl,
        status: "provider_unverified",
        status_text: "Partnerzugang nicht bestätigt",
        available_dates: availableDates,
        offers: [],
      };
    }

    const offerLocator = await waitForOffers(page, {
      timeout_ms: search.catalog_preview === true ? 15_000 : (search.background_range_scan === true ? 30_000 : 60_000),
      allow_empty_after_timeout: rangeLikeScan,
    });
    const loadMoreResult = await loadAllOffers(page, offerLocator);
    if (loadMoreResult.clicks > 0) {
      log(`${provider.name}: „Mehr Ergebnisse anzeigen“ ${loadMoreResult.clicks}x geklickt; Unterkünfte ${loadMoreResult.initial_count} -> ${loadMoreResult.final_count}.`);
    }

    const raw = await offerLocator.evaluateAll((buttons) =>
      buttons.map((button) => {
        const card = button.closest(".accCart");
        const cardImage = card?.querySelector("img[data-src], img[src]");
        const detailButton = card?.querySelector(".js-housingMoreInfo[data-src]");
        return {
          ...button.dataset,
          photodomainurl:
            cardImage?.getAttribute("data-src") ||
            cardImage?.getAttribute("src") ||
            button.dataset.photodomainurl ||
            "",
          detailurl: detailButton?.getAttribute("data-src") || "",
        };
      }),
    );
    const normalizedOffers = raw.map((dataset) => {
      const offer = offerFromDataset(dataset);
      return {
        ...offer,
        // Der interne Center-Parcs-Popin ist als allein geöffnete Seite auf
        // Mobilgeräten abgeschnitten. Deshalb verlinken wir auf die echte,
        // responsive Haustyp-Seite und behalten den Popin nur diagnostisch.
        house_info_url: buildHouseInfoPageUrl(search, offer.code, offer.name),
        house_info_popin_url: normalizeHouseInfoUrl(page.url(), offer.detail_url),
      };
    });
    const exactOffers = offersForExactTravelPeriod(normalizedOffers, search);
    const offers = exactOffers
      .filter((offer) => matchesProviderOffer(offer, providerId))
      .map((offer) => ({
        ...offer,
        detail_url: buildHousePageUrl(search, offer.code, providerId),
      }))
      .filter((offer) => offer.code)
      .sort((left, right) => {
        if (left.price === null) return 1;
        if (right.price === null) return -1;
        return left.price - right.price;
      });

    if (providerId !== "direct") {
      for (const offer of exactOffers) {
        log(`${provider.name}: Kandidat ${offer.code || "?"}: Preis=${offer.price ?? "null"}, Gesamt=${offer.total_with_tax ?? "null"}, Aktion=${offer.action_name || "keine"}, akzeptiert=${matchesProviderOffer(offer, providerId)}`);
      }
    }

    log(`${provider.name}: ${raw.length} Karten gelesen, ${offers.length} bestätigte Treffer für Park ${search.park.code} und ${search.start_date} bis ${search.end_date}; Ergebnis-URL: ${page.url()}`);

    const noExactOffer = providerId !== "direct" && exactOffers.length === 0;
    const rejectedPartnerPrice = providerId === "benefits" && exactOffers.length > 0 && offers.length === 0;
    return {
      provider: providerId,
      checked_at: new Date().toISOString(),
      page_url: page.url(),
      requested_url: providerSearchUrl,
      availability_url: availabilityUrl,
      status: rejectedPartnerPrice ? "provider_unverified" : (noExactOffer ? "unavailable" : "available"),
      status_text: rejectedPartnerPrice
        ? "Benefits-Preis konnte nicht sicher bestätigt werden"
        : (noExactOffer ? "Keine passende Partner-Unterkunft gefunden" : "Verfügbar"),
      available_dates: availableDates,
      offers,
    };
  } finally {
    await context.close().catch(() => {});
  }
}

async function scrapeOffers(search, browser = null) {
  const ownsBrowser = !browser;
  const activeBrowser = browser || (await launchBrowser());
  try {
    const results = {};
    const providerErrors = [];
    const providerIds = search.include_felicitas === false
      ? ["direct"]
      : Object.keys(PROVIDERS);
    for (const providerId of providerIds) {
      try {
        results[providerId] = await scrapeProvider(search, providerId, activeBrowser);
      } catch (error) {
        if (search.background_range_scan !== true && search.catalog_preview !== true) throw error;
        providerErrors.push({ provider: providerId, message: error.message || String(error) });
        log(`${PROVIDERS[providerId].name}: technischer Fehler innerhalb der Zeitraum-Prüfung: ${error.message || error}`);
        results[providerId] = {
          provider: providerId,
          checked_at: new Date().toISOString(),
          page_url: buildSearchUrl(search, providerId),
          status: providerId === "direct" ? "unavailable" : "provider_unverified",
          status_text: providerId === "direct"
            ? "Technisch nicht vollständig geprüft"
            : "Partnerzugang technisch nicht vollständig geprüft",
          available_dates: [],
          offers: [],
        };
      }
    }
    const offers = mergeProviderResults(results);
    if (offers[0]?.park_name) search.park.name = offers[0].park_name;
    return {
      checked_at: new Date().toISOString(),
      page_url: results.direct?.page_url || search.source_url,
      provider_urls: Object.fromEntries(
        Object.entries(results).map(([providerId, result]) => [providerId, result.page_url]),
      ),
      provider_statuses: Object.fromEntries(
        Object.entries(results).map(([providerId, result]) => [providerId, {
          status: result.status || "unavailable",
          status_text: result.status_text || "Nicht verfügbar",
        }]),
      ),
      provider_errors: providerErrors,
      offers,
    };
  } finally {
    if (ownsBrowser) await activeBrowser.close().catch(() => {});
  }
}

function parkCountryFromUrl(value) {
  try {
    const pathname = new URL(String(value)).pathname.toLowerCase();
    const countries = {
      deutschland: "Deutschland",
      niederlande: "Niederlande",
      belgien: "Belgien",
      frankreich: "Frankreich",
      danemark: "Dänemark",
    };
    const segment = pathname.split("/").find((part) => countries[part]);
    return countries[segment] || "";
  } catch {
    return "";
  }
}

function compareParks(left, right) {
  const leftCountry = String(left?.country || "");
  const rightCountry = String(right?.country || "");
  const leftIndex = COUNTRY_ORDER.indexOf(leftCountry);
  const rightIndex = COUNTRY_ORDER.indexOf(rightCountry);
  const countryComparison =
    (leftIndex < 0 ? COUNTRY_ORDER.length : leftIndex) -
    (rightIndex < 0 ? COUNTRY_ORDER.length : rightIndex);
  if (countryComparison) return countryComparison;
  const fallbackCountryComparison = leftCountry.localeCompare(rightCountry, "de");
  if (fallbackCountryComparison) return fallbackCountryComparison;
  return String(left?.name || "").localeCompare(String(right?.name || ""), "de");
}

function parkFromLink(link) {
  try {
    const url = new URL(link.href);
    const match = url.pathname.match(/\/fp_([^_/]+)_([^/?#]+)/i);
    if (!match) return null;
    const code = match[1].toUpperCase();
    const rawName = String(link.text || "")
      .replace(/\s+/g, " ")
      .trim();
    const slugName = match[2]
      .replace(/^ferienpark-/, "")
      .split("-")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
    const parkNameMatch = rawName.match(/(?:Park|Parc|Village|Les|De|Het|Terhills|Nordborg)[^€\d]{2,50}/i);
    const name = (parkNameMatch?.[0] || slugName).trim();
    const basePath = `${url.origin}${url.pathname.replace(/\/$/, "")}`;
    return {
      id: `l2_${code}`,
      code,
      name,
      country: parkCountryFromUrl(url),
      base_url: basePath.endsWith("/ferienhaeuser")
        ? basePath
        : `${basePath}/ferienhaeuser`,
    };
  } catch {
    return null;
  }
}

async function discoverParks() {
  const browser = await launchBrowser();
  const context = await browser.newContext({ locale: "de-DE" });
  const page = await context.newPage();
  try {
    await page.goto("https://www.centerparcs.de/de-de/search", {
      waitUntil: "domcontentloaded",
      timeout: 90_000,
    });
    await acceptCookies(page);
    await page.waitForTimeout(2_000);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(1_000);
    const links = await page.locator('a[href*="/fp_"]').evaluateAll((items) =>
      items.map((item) => ({ href: item.href, text: item.textContent || "" })),
    );
    const byId = new Map(DEFAULT_PARKS.map((park) => [park.id, park]));
    for (const link of links) {
      const park = parkFromLink(link);
      if (park) {
        const previous = byId.get(park.id) || {};
        byId.set(park.id, {
          ...previous,
          ...park,
          country: park.country || previous.country || "",
        });
      }
    }
    return [...byId.values()].sort(compareParks);
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

module.exports = {
  compareParks,
  DEFAULT_PARKS,
  discoverParks,
  fetchAvailableDates,
  fetchProviderAvailability,
  launchBrowser,
  loadAllOffers,
  LOAD_MORE_OFFERS_PATTERN,
  mergeProviderResults,
  matchesProviderOffer,
  normalizeHouseInfoUrl,
  offersForExactTravelPeriod,
  parkCountryFromUrl,
  parseAvailableDates,
  partnerArrivalDecision,
  providerAvailabilityContextConfirmed,
  providerContextConfirmed,
  readAvailableDatesFromPage,
  scrapeOffers,
};
