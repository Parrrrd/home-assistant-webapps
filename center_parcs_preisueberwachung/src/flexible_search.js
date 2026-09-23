"use strict";

const { PROVIDERS } = require("./centerparcs");

const PROVIDER_IDS = Object.keys(PROVIDERS);

function isoToUtc(value) {
  const [year, month, day] = String(value || "").split("-").map(Number);
  if (!year || !month || !day) return null;
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  return Number.isNaN(date.getTime()) ? null : date;
}

function utcToIso(date) {
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

function addDays(value, days) {
  const date = isoToUtc(value);
  if (!date) return null;
  date.setUTCDate(date.getUTCDate() + Number(days || 0));
  return utcToIso(date);
}

function daysBetween(start, end) {
  const startDate = isoToUtc(start);
  const endDate = isoToUtc(end);
  if (!startDate || !endDate) return null;
  return Math.round((endDate - startDate) / 86_400_000);
}

function buildCandidateStays(search, availableDates = []) {
  const nights = Number(search.nights);
  const rangeStart = String(search.range_start || search.start_date || "");
  const rangeEnd = String(search.range_end || search.end_date || "");
  const allowed = new Set(Array.isArray(availableDates) ? availableDates : []);
  if (![3, 4, 7].includes(nights)) throw new Error("Bei einer Zeitraum-Suche sind nur 3, 4 oder 7 Übernachtungen erlaubt.");
  if (!rangeStart || !rangeEnd || rangeEnd <= rangeStart) throw new Error("Bitte einen gültigen Suchzeitraum auswählen.");

  return [...allowed]
    .filter((startDate) => startDate >= rangeStart)
    .map((startDate) => ({ start_date: startDate, end_date: addDays(startDate, nights) }))
    .filter((stay) => stay.end_date && stay.end_date <= rangeEnd)
    .sort((left, right) => left.start_date.localeCompare(right.start_date));
}

function unavailableSnapshot(providerId, status = "unavailable", statusText = "Im Zeitraum nicht verfügbar") {
  return {
    provider: providerId,
    provider_name: PROVIDERS[providerId].name,
    price: null,
    available: false,
    stock: 0,
    in_offer: status !== "not_offered",
    status,
    status_text: statusText,
    start_date: null,
    end_date: null,
    source_url: null,
  };
}

function providerFallbackFromStatuses(providerId, statuses = []) {
  const values = statuses.filter(Boolean);
  if (values.includes("provider_unverified")) {
    return unavailableSnapshot(providerId, "provider_unverified", "Partnerzugang konnte im Zeitraum nicht vollständig bestätigt werden");
  }
  if (values.length && values.every((status) => status === "not_offered")) {
    return unavailableSnapshot(providerId, "not_offered", "Im Zeitraum aktuell nicht im Angebot");
  }
  return unavailableSnapshot(providerId);
}

function betterSnapshot(candidate, current) {
  if (!candidate?.available || !Number.isFinite(Number(candidate.price))) return false;
  if (!current?.available || !Number.isFinite(Number(current.price))) return true;
  const priceDifference = Number(candidate.price) - Number(current.price);
  if (priceDifference !== 0) return priceDifference < 0;
  return String(candidate.start_date || "").localeCompare(String(current.start_date || "")) < 0;
}

function aggregateFlexibleScans(search, scans = []) {
  const byCode = new Map();
  const providerStatuses = Object.fromEntries(PROVIDER_IDS.map((id) => [id, []]));

  for (const scan of scans) {
    for (const providerId of PROVIDER_IDS) {
      const status = scan.result?.provider_statuses?.[providerId]?.status;
      if (status) providerStatuses[providerId].push(status);
    }

    for (const rawOffer of scan.result?.offers || []) {
      const code = rawOffer.code;
      if (!code) continue;
      if (!byCode.has(code)) {
        byCode.set(code, {
          code,
          base: rawOffer,
          providerBest: {},
          providerOffer: {},
        });
      }
      const entry = byCode.get(code);
      for (const providerId of PROVIDER_IDS) {
        const source = rawOffer.prices?.[providerId];
        if (!source?.available || !Number.isFinite(Number(source.price))) continue;
        const candidate = {
          ...source,
          start_date: scan.search.start_date,
          end_date: scan.search.end_date,
          source_url: scan.result?.provider_urls?.[providerId] || null,
        };
        if (betterSnapshot(candidate, entry.providerBest[providerId])) {
          entry.providerBest[providerId] = candidate;
          entry.providerOffer[providerId] = rawOffer;
        }
      }
    }
  }

  const offers = [...byCode.values()].map((entry) => {
    const prices = Object.fromEntries(PROVIDER_IDS.map((providerId) => [
      providerId,
      entry.providerBest[providerId] || providerFallbackFromStatuses(providerId, providerStatuses[providerId]),
    ]));
    const best = Object.values(prices)
      .filter((item) => item.available && Number.isFinite(Number(item.price)))
      .sort((left, right) => Number(left.price) - Number(right.price) || String(left.start_date).localeCompare(String(right.start_date)))[0] || null;
    const bestOffer = best ? entry.providerOffer[best.provider] : entry.base;
    const providerBestDates = Object.fromEntries(PROVIDER_IDS.map((providerId) => [
      providerId,
      prices[providerId]?.available ? {
        start_date: prices[providerId].start_date,
        end_date: prices[providerId].end_date,
      } : null,
    ]));
    return {
      ...entry.base,
      ...bestOffer,
      code: entry.code,
      flexible: true,
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
      action_name: best?.action_name || "",
      available: Boolean(best),
      best_stay: best ? { start_date: best.start_date, end_date: best.end_date } : null,
      provider_best_stays: providerBestDates,
      start_date: best?.start_date ?? null,
      end_date: best?.end_date ?? null,
      detail_url: bestOffer?.detail_url || entry.base?.detail_url || "",
      house_info_url: bestOffer?.house_info_url || entry.base?.house_info_url || "",
      image_url: bestOffer?.image_url || entry.base?.image_url || "",
    };
  }).filter((offer) => offer.available)
    .sort((left, right) => Number(left.best_price) - Number(right.best_price) || String(left.name || "").localeCompare(String(right.name || ""), "de"));

  return {
    offers,
    candidate_count: scans.length,
  };
}


function compactProviderOption(providerId, source, fallbackStatus = null, fallbackText = null, sourceUrl = null) {
  if (source?.available && Number.isFinite(Number(source.price))) {
    return {
      provider: providerId,
      provider_name: PROVIDERS[providerId].name,
      price: Number(source.price),
      available: true,
      original_price: Number.isFinite(Number(source.original_price)) ? Number(source.original_price) : null,
      total_with_tax: Number.isFinite(Number(source.total_with_tax)) ? Number(source.total_with_tax) : null,
      pet_fee: Number.isFinite(Number(source.pet_fee)) ? Number(source.pet_fee) : null,
      action_name: source.action_name || "",
      status: source.status || "available",
      status_text: source.status_text || "Verfügbar",
      source_url: source.source_url || sourceUrl || null,
    };
  }
  const status = source?.status || (fallbackStatus === "available" ? "unavailable" : fallbackStatus) || "unavailable";
  const statusText = source?.status_text || (fallbackStatus === "available" ? "Für diesen Haustyp nicht verfügbar" : fallbackText) || "Nicht verfügbar";
  return {
    provider: providerId,
    provider_name: PROVIDERS[providerId].name,
    price: null,
    available: false,
    original_price: null,
    total_with_tax: null,
    pet_fee: null,
    action_name: "",
    status,
    status_text: statusText,
    source_url: source?.source_url || sourceUrl || null,
  };
}

function buildRangeOptionsByCode(scans = []) {
  const codes = new Set();
  for (const scan of scans) {
    for (const offer of scan.result?.offers || []) {
      if (offer?.code) codes.add(offer.code);
    }
  }

  const output = {};
  for (const code of codes) {
    const rows = [];
    for (const scan of scans) {
      const offer = (scan.result?.offers || []).find((item) => item?.code === code) || null;
      const prices = {};
      for (const providerId of PROVIDER_IDS) {
        const providerState = scan.result?.provider_statuses?.[providerId] || {};
        prices[providerId] = compactProviderOption(
          providerId,
          offer?.prices?.[providerId],
          providerState.status,
          providerState.status_text,
          scan.result?.provider_urls?.[providerId] || null,
        );
      }
      const available = Object.values(prices)
        .filter((entry) => entry.available && Number.isFinite(Number(entry.price)))
        .sort((left, right) => Number(left.price) - Number(right.price));
      if (!available.length) continue;
      rows.push({
        start_date: scan.search.start_date,
        end_date: scan.search.end_date,
        best_price: available[0].price,
        best_provider: available[0].provider,
        best_provider_name: available[0].provider_name,
        prices,
      });
    }
    output[code] = rows.sort((left, right) =>
      String(left.start_date).localeCompare(String(right.start_date)) ||
      Number(left.best_price) - Number(right.best_price)
    );
  }
  return output;
}


function aggregateRangeOptions(catalogOffers = [], optionsByCode = {}) {
  const catalogByCode = new Map((catalogOffers || []).filter((offer) => offer?.code).map((offer) => [offer.code, offer]));
  const codes = new Set([...catalogByCode.keys(), ...Object.keys(optionsByCode || {})]);
  const offers = [];

  for (const code of codes) {
    const rows = (Array.isArray(optionsByCode?.[code]) ? optionsByCode[code] : [])
      .filter((row) => row?.check_status === "current");
    const providerBest = {};
    for (const providerId of PROVIDER_IDS) {
      for (const row of rows) {
        const snapshot = row?.prices?.[providerId];
        if (!snapshot?.available || !Number.isFinite(Number(snapshot.price))) continue;
        const candidate = {
          ...snapshot,
          provider: providerId,
          provider_name: snapshot.provider_name || PROVIDERS[providerId].name,
          price: Number(snapshot.price),
          start_date: row.start_date,
          end_date: row.end_date,
          source_url: snapshot.source_url || null,
        };
        if (!providerBest[providerId] || Number(candidate.price) < Number(providerBest[providerId].price)) {
          providerBest[providerId] = candidate;
        }
      }
    }

    const available = Object.values(providerBest)
      .filter((item) => item.available && Number.isFinite(Number(item.price)))
      .sort((left, right) => Number(left.price) - Number(right.price) || String(left.start_date).localeCompare(String(right.start_date)));
    const best = available[0] || null;
    if (!best) continue;

    const base = catalogByCode.get(code) || { code, name: code };
    const prices = Object.fromEntries(PROVIDER_IDS.map((providerId) => [
      providerId,
      providerBest[providerId] || {
        provider: providerId,
        provider_name: PROVIDERS[providerId].name,
        price: null,
        available: false,
        stock: 0,
        status: "unavailable",
        status_text: "Nicht verfügbar",
      },
    ]));
    offers.push({
      ...base,
      code,
      flexible: true,
      prices,
      price: best.price,
      best_price: best.price,
      best_provider: best.provider,
      best_provider_name: best.provider_name,
      original_price: best.original_price ?? null,
      total_with_tax: best.total_with_tax ?? null,
      pet_fee: best.pet_fee ?? null,
      discount_percent: best.discount_percent ?? 0,
      stock: best.stock ?? 0,
      action_name: best.action_name || "",
      available: true,
      best_stay: { start_date: best.start_date, end_date: best.end_date },
      provider_best_stays: Object.fromEntries(PROVIDER_IDS.map((providerId) => [
        providerId,
        providerBest[providerId] ? { start_date: providerBest[providerId].start_date, end_date: providerBest[providerId].end_date } : null,
      ])),
      start_date: best.start_date,
      end_date: best.end_date,
      detail_url: base.detail_url || "",
      house_info_url: base.house_info_url || "",
      image_url: base.image_url || "",
    });
  }

  return offers.sort((left, right) => Number(left.best_price) - Number(right.best_price) || String(left.name || "").localeCompare(String(right.name || ""), "de"));
}

function exactSearchForStay(search, stay) {
  return {
    park: search.park,
    start_date: stay.start_date,
    end_date: stay.end_date,
    adults: search.adults,
    pets: search.pets,
    child_ages: search.child_ages,
    include_felicitas: search.include_felicitas !== false,
  };
}

module.exports = {
  addDays,
  aggregateFlexibleScans,
  aggregateRangeOptions,
  buildCandidateStays,
  daysBetween,
  exactSearchForStay,
  buildRangeOptionsByCode,
};
