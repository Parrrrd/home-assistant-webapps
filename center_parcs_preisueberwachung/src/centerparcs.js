"use strict";

const CENTER_PARCS_ORIGIN = "https://www.centerparcs.de";
const PROVIDERS = {
  direct: {
    id: "direct",
    name: "Center Parcs direkt",
  },
  felicitas: {
    id: "felicitas",
    name: "Felicitas",
    landing_url: "https://www.centerparcs.de/de-de/felicitas_sck",
    landing_path: "/de-de/felicitas_sck",
    search_base_url: "https://www.centerparcs.de/de-de/felicitas_sck",
    expected_path: "/de-de/felicitas_sck",
    portal_code: "fel_b2c",
    item: "88",
    query: {
      "facet[PROMOCODE][portalCode]": "fel_b2c",
      pc: "fel_b2c",
      utm_source: "felicitas.de",
      utm_medium: "Indirect_Sales_Partner",
    },
  },
  benefits: {
    id: "benefits",
    name: "Benefits",
    landing_url: "https://www.centerparcs.de/de-de/corporate-benefits_sck",
    landing_path: "/de-de/corporate-benefits_sck",
    search_base_url: "https://www.centerparcs.de/de-de/corporate-benefits_sck",
    expected_path: "/de-de/corporate-benefits_sck",
    portal_code: "corpbe_b2c",
    item: "115",
    query: {
      "facet[PROMOCODE][portalCode]": "corpbe_b2c",
    },
  },
};

function text(value) {
  return String(value ?? "").trim();
}

function integer(value, fallback = 0, minimum = 0, maximum = 99) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

function isoDate(value) {
  const normalized = text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return null;
  const date = new Date(`${normalized}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : normalized;
}

function titleFromSlug(slug) {
  return text(slug)
    .replace(/^ferienpark-/, "")
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function parseParkFromUrl(parsed) {
  const match = parsed.pathname.match(/\/fp_([^_/]+)_([^/?#]+)/i);
  const domain = parsed.searchParams.get("facet[COUNTRYSITE][]") || "";
  const code = match?.[1]?.toUpperCase() || domain.replace(/^l2_/i, "").toUpperCase();
  const slug = match?.[2] || "";
  const basePath = match
    ? parsed.pathname.replace(/\?.*$/, "")
    : `/de-de/search`;
  return {
    id: domain || (code ? `l2_${code}` : ""),
    code,
    name: titleFromSlug(slug) || code || "Center Parcs",
    base_url: `${parsed.origin}${basePath}`,
  };
}

function normalizeChildAges(values) {
  const source = Array.isArray(values)
    ? values
    : text(values)
        .split(/[;,\s]+/)
        .filter(Boolean);
  return source.map((value) => integer(value, 0, 0, 17));
}

function parseSearchUrl(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Bitte einen vollständigen Center-Parcs-Ergebnislink eingeben.");
  }
  if (!/(^|\.)centerparcs\.de$/i.test(parsed.hostname)) {
    throw new Error("Der Link muss von centerparcs.de stammen.");
  }

  const startDate = isoDate(parsed.searchParams.get("facet[DATE]"));
  const endDate = isoDate(parsed.searchParams.get("facet[DATEEND]"));
  if (!startDate || !endDate || endDate <= startDate) {
    throw new Error("Im Link wurde kein gültiger Reisezeitraum gefunden.");
  }

  const prefix = "facet[MULTIPARTICIPANTS][0]";
  const childAges = normalizeChildAges(parsed.searchParams.getAll(`${prefix}[ages][]`));
  const adults = integer(parsed.searchParams.get(`${prefix}[adult]`), 2, 1, 20);
  const pets = integer(parsed.searchParams.get(`${prefix}[pet]`), 0, 0, 2);
  const park = parseParkFromUrl(parsed);
  if (!park.id) throw new Error("Der Ferienpark konnte aus dem Link nicht erkannt werden.");

  return {
    park,
    start_date: startDate,
    end_date: endDate,
    adults,
    pets,
    child_ages: childAges,
    include_felicitas: true,
    mode: "fixed",
    source_url: buildSearchUrl({
      park,
      start_date: startDate,
      end_date: endDate,
      adults,
      pets,
      child_ages: childAges,
    }),
  };
}

function normalizeSearch(input, parks = []) {
  if (input?.source_url && !input?.park) {
    const parsed = parseSearchUrl(input.source_url);
    parsed.mode = "fixed";
    return parsed;
  }

  const parkInput = input?.park || parks.find((item) => item.id === input?.park_id);
  if (!parkInput?.id || !parkInput?.base_url) {
    throw new Error("Bitte einen Ferienpark auswählen oder einen Ergebnislink übernehmen.");
  }

  const mode = input?.mode === "range" ? "range" : "fixed";
  const startDate = isoDate(input.start_date || input.range_start);
  const endDate = isoDate(input.end_date || input.range_end);
  if (!startDate || !endDate || endDate <= startDate) {
    throw new Error(mode === "range"
      ? "Bitte einen gültigen Suchzeitraum auswählen."
      : "Bitte einen gültigen An- und Abreisezeitraum auswählen.");
  }

  const search = {
    mode,
    park: {
      id: text(parkInput.id),
      code: text(parkInput.code || parkInput.id.replace(/^l2_/i, "")).toUpperCase(),
      name: text(parkInput.name || parkInput.code),
      base_url: text(parkInput.base_url),
    },
    start_date: startDate,
    end_date: endDate,
    adults: integer(input.adults, 2, 1, 20),
    pets: integer(input.pets, 0, 0, 2),
    child_ages: normalizeChildAges(input.child_ages),
    include_felicitas: input.include_felicitas !== false,
  };

  if (mode === "range") {
    const nights = integer(input.nights, 3, 1, 14);
    if (![3, 4, 7].includes(nights)) {
      throw new Error("Bitte für die Zeitraum-Suche 3, 4 oder 7 Übernachtungen auswählen.");
    }
    const durationDays = Math.round((new Date(`${endDate}T12:00:00Z`) - new Date(`${startDate}T12:00:00Z`)) / 86_400_000);
    if (durationDays < nights) {
      throw new Error(`Der Suchzeitraum muss mindestens ${nights} Tage umfassen.`);
    }
    if (durationDays > 180) {
      throw new Error("Der Suchzeitraum darf maximal 180 Tage umfassen.");
    }
    search.range_start = startDate;
    search.range_end = endDate;
    search.nights = nights;
    search.source_url = search.park.base_url;
  } else {
    search.source_url = buildSearchUrl(search);
  }
  return search;
}

function buildSearchUrl(search, providerId = "direct") {
  const provider = PROVIDERS[providerId] || PROVIDERS.direct;
  const baseUrl = providerId === "direct"
    ? (search.park.base_url || `${CENTER_PARCS_ORIGIN}/de-de/search`)
    : (provider.search_base_url || provider.landing_url || search.park.base_url || `${CENTER_PARCS_ORIGIN}/de-de/search`);
  const url = new URL(baseUrl);
  const params = url.searchParams;
  const defaults = providerId === "direct"
    ? {
        market: "de",
        language: "de",
        c: "SEARCH_CPE_LIGHT",
        univers: "cpe",
        type: "ACCUEIL",
        currency: "EUR",
        group: "offer",
        sort: "popularity_housing",
        asc: "asc",
        page: "1",
        nb: "30",
        displayPrice: "default",
        dateuser: "1",
        is_user_search: "1",
      }
    : {
        market: "de",
        language: "de",
        c: "CPE_SINGLECLICK_ONE",
        univers: "cpe",
        type: "SINGLECLICK_ONE",
        currency: "EUR",
        group: "housing",
        sort: providerId === "felicitas" ? "price" : "popularity_housing",
        asc: "asc",
        page: "1",
        nb: "10",
        displayPrice: "default",
        dateuser: "1",
        item: provider.item || "",
      };
  for (const [key, value] of Object.entries(defaults)) {
    if (value !== "") params.set(key, value);
  }
  params.set("facet[DATE]", search.start_date);
  params.set("facet[DATEEND]", search.end_date);
  params.delete("facet[COUNTRYSITE][]");
  params.append("facet[COUNTRYSITE][]", search.park.id);

  const prefix = "facet[MULTIPARTICIPANTS][0]";
  params.set(`${prefix}[adult]`, String(search.adults));
  params.set(`${prefix}[pet]`, String(search.pets));
  params.delete(`${prefix}[ages][]`);
  for (const age of normalizeChildAges(search.child_ages)) {
    params.append(`${prefix}[ages][]`, String(age));
  }
  for (const key of [
    "pc",
    "utm_source",
    "utm_medium",
    "facet[PROMOCODE][portalCode]",
  ]) params.delete(key);
  for (const [key, value] of Object.entries(provider.query || {})) {
    params.set(key, value);
  }
  return url.toString();
}

function buildProviderAvailabilityUrl(search, providerId) {
  const provider = PROVIDERS[providerId];
  if (!provider || providerId === "direct" || !provider.landing_url) return null;

  const url = new URL(provider.landing_url);
  const params = url.searchParams;
  const defaults = {
    market: "de",
    language: "de",
    c: "CPE_SINGLECLICK_ONE",
    univers: "cpe",
    type: "SINGLECLICK_ONE",
    currency: "EUR",
    group: "housing",
    sort: providerId === "felicitas" ? "price" : "popularity_housing",
    asc: "asc",
    page: "1",
    nb: "10",
    displayPrice: "default",
    dateuser: "1",
    item: provider.item || "",
  };
  for (const [key, value] of Object.entries(defaults)) {
    if (value !== "") params.set(key, value);
  }

  // Absichtlich KEIN facet[DATE]/facet[DATEEND]: Diese URL dient nur dazu,
  // den echten Partner-Kalender für den gewählten Park auszulesen.
  params.delete("facet[DATE]");
  params.delete("facet[DATEEND]");
  params.delete("facet[COUNTRYSITE][]");
  params.append("facet[COUNTRYSITE][]", search.park.id);

  const prefix = "facet[MULTIPARTICIPANTS][0]";
  params.set(`${prefix}[adult]`, String(search.adults));
  params.set(`${prefix}[pet]`, String(search.pets));
  params.delete(`${prefix}[ages][]`);
  for (const age of normalizeChildAges(search.child_ages)) {
    params.append(`${prefix}[ages][]`, String(age));
  }

  for (const key of ["pc", "utm_source", "utm_medium", "facet[PROMOCODE][portalCode]"]) {
    params.delete(key);
  }
  for (const [key, value] of Object.entries(provider.query || {})) {
    params.set(key, value);
  }
  return url.toString();
}


function buildHouseInfoPageUrl(search, housingCode, offerName = "") {
  const code = text(housingCode);
  if (!code || !search?.park?.base_url) return "";

  const url = new URL(buildSearchUrl(search, "direct"));
  const base = new URL(search.park.base_url);
  const parkMatch = base.pathname.match(/^(.*\/fp_[^/]+_[^/]+)(?:\/.*)?$/i);
  if (!parkMatch) return "";

  // Die normalen Comfort/Premium/VIP/Exclusive-Seiten liegen bei Center Parcs
  // unter /ferienhaus/<Code>. Besondere Naturwunder-Häuser haben einen eigenen
  // sprechenden Pfad. Die vollständige Seite ist mobil responsiv, anders als
  // der interne /light/popin/housing-Endpunkt.
  const category = /naturwunder/i.test(text(offerName))
    ? "naturwunder-ferienhaus"
    : "ferienhaus";
  url.pathname = `${parkMatch[1]}/${category}/${encodeURIComponent(code)}`;

  // Suchkontext beibehalten, damit Zeitraum und Belegung auf der Hausseite
  // weiterhin zum beobachteten Aufenthalt passen.
  url.searchParams.delete("hc");
  url.searchParams.delete("selected[site]");
  url.searchParams.delete("selected[housing]");
  url.searchParams.delete("facet[HOUSING][]");
  return url.toString();
}
function buildHousePageUrl(search, housingCode, providerId = "direct") {
  const url = new URL(buildSearchUrl(search, providerId));
  const code = text(housingCode);
  url.searchParams.set("hc", code);
  url.searchParams.set("selected[site]", text(search.park.code));
  url.searchParams.set("selected[housing]", code);
  url.searchParams.delete("facet[HOUSING][]");
  url.searchParams.append("facet[HOUSING][]", code);
  return url.toString();
}

function parsePrice(value) {
  try {
    return typeof value === "string" ? JSON.parse(value) : value || {};
  } catch {
    return {};
  }
}

function money(value) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : null;
}

function offerFromDataset(dataset) {
  const price = parsePrice(dataset.price);
  const active = price.promo || price.original || {};
  const visiblePrice = money(active.rawBeforeTax ?? active.valueBeforeTax ?? active.value);
  return {
    code: text(dataset.housingcode),
    park_code: text(dataset.code),
    park_name: text(dataset.offer),
    name: text(dataset.cottagename || dataset.housing),
    comfort: text(dataset.comfort),
    capacity: text(dataset.housingname),
    guests: integer(dataset.guests, 0, 0, 99),
    start_date: isoDate(dataset.start),
    end_date: isoDate(dataset.end),
    price: visiblePrice,
    original_price: money(price.original?.rawBeforeTax ?? price.original?.valueBeforeTax),
    total_with_tax: money(active.value ?? active.raw),
    pet_fee: money(price.pets?.value ?? price.pets?.raw),
    discount_percent: integer(price.discount, 0, 0, 100),
    stock: integer(dataset.stock, 0, 0, 9999),
    action_name: text(dataset.actioncodename),
    included_services: text(dataset.includedservices)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    image_url: text(dataset.photodomainurl),
    detail_url: text(dataset.detailurl),
    available: Boolean(text(dataset.housingcode) && visiblePrice !== null),
  };
}

function offerLabel(offer) {
  return [offer.name, offer.capacity, offer.code].filter(Boolean).join(" · ");
}

function entitySlug(value) {
  return text(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48) || "reise";
}

module.exports = {
  CENTER_PARCS_ORIGIN,
  PROVIDERS,
  buildHouseInfoPageUrl,
  buildHousePageUrl,
  buildProviderAvailabilityUrl,
  buildSearchUrl,
  entitySlug,
  normalizeSearch,
  offerFromDataset,
  offerLabel,
  parseSearchUrl,
};
