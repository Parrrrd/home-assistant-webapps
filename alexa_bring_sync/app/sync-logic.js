function normalizeItem(value) {
  return String(value || "")
    .normalize("NFKC")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase("de-DE");
}

function alexaItemName(item) {
  // getListItemsV2 exposes itemName as the canonical Alexa list value.
  // Keep value/name only as compatibility fallbacks for older payload shapes.
  return String(item && (item.itemName || item.value || item.name) || "").trim();
}

function alexaItemId(item) {
  return String(item && (item.itemId || item.id) || "").trim();
}

function alexaRawNameFields(item) {
  const out = {};
  for (const key of ["itemName", "value", "name"]) {
    if (item && item[key] !== undefined && item[key] !== null) out[key] = String(item[key]);
  }
  return out;
}

function sanitizeAlexaRaw(value, depth = 0) {
  if (depth > 5) return "[gekürzt]";
  if (value === null || value === undefined) return value;
  if (["string", "number", "boolean"].includes(typeof value)) return value;
  if (Array.isArray(value)) return value.slice(0, 25).map((entry) => sanitizeAlexaRaw(entry, depth + 1));
  if (typeof value !== "object") return String(value);
  const out = {};
  const sensitive = /(token|cookie|csrf|auth|password|email|customer|account|device|serial|user)/i;
  for (const [key, entry] of Object.entries(value)) {
    if (sensitive.test(key)) continue;
    out[key] = sanitizeAlexaRaw(entry, depth + 1);
  }
  return out;
}

function capitalizeFirst(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const characters = Array.from(text);
  return characters[0].toLocaleUpperCase("de-DE") + characters.slice(1).join("");
}

function processedItemName(item, fallback = "") {
  const value = String(item && (item.productName || item.name || item.summary || item.original) || fallback || "").trim();
  return capitalizeFirst(value);
}

function isActiveTodo(item) {
  return !item || item.status === undefined || item.status === "needs_action";
}

function planTransfers(alexaItems, todoItems) {
  const existing = new Set(
    (todoItems || [])
      .filter(isActiveTodo)
      .map((item) => normalizeItem(item.summary || item.name))
      .filter(Boolean),
  );
  const seen = new Set();
  const transfers = [];
  const skipped = [];

  for (const item of alexaItems || []) {
    const name = alexaItemName(item);
    const key = normalizeItem(name);
    if (!key || item.completed || item.itemStatus === "COMPLETE") continue;
    if (existing.has(key) || seen.has(key)) {
      skipped.push({ item, reason: "duplicate" });
      continue;
    }
    seen.add(key);
    transfers.push({ item, name: capitalizeFirst(name) });
  }
  return { transfers, skipped };
}

const NUMBER_WORDS = {
  ein: 1, eine: 1, einen: 1, eins: 1,
  zwei: 2, drei: 3, vier: 4, fünf: 5, fuenf: 5,
  sechs: 6, sieben: 7, acht: 8, neun: 9, zehn: 10,
};

function parseNumberToken(value) {
  const text = normalizeItem(value);
  if (Object.prototype.hasOwnProperty.call(NUMBER_WORDS, text)) return NUMBER_WORDS[text];
  const numeric = Number(text.replace(",", "."));
  return Number.isFinite(numeric) ? numeric : null;
}

function parseQuantityName(value) {
  const raw = String(value || "").trim().replace(/\s+/g, " ");
  if (!raw) return null;
  const number = "(\\d+(?:[.,]\\d+)?|ein|eine|einen|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)";
  const unit = "(?:x|mal|stück|stueck|stk)";
  let match = new RegExp(`^(.+?)\\s+${number}\\s*${unit}\\s*$`, "i").exec(raw);
  if (match) {
    const quantity = parseNumberToken(match[2]);
    if (quantity !== null) return { baseName: capitalizeFirst(match[1]), quantity, unit: "Stück", raw };
  }
  match = new RegExp(`^${number}\\s*${unit}\\s+(.+)$`, "i").exec(raw);
  if (match) {
    const quantity = parseNumberToken(match[1]);
    if (quantity !== null) return { baseName: capitalizeFirst(match[2]), quantity, unit: "Stück", raw };
  }
  return null;
}

function directSpecialTargetInterpretation(value) {
  const raw = String(value || "").trim().replace(/\s+/g, " ");
  if (!raw) return null;

  function makeTarget(baseText, categoryName, reason) {
    const parsed = parseQuantityName(baseText);
    const baseName = parsed ? parsed.baseName : capitalizeFirst(String(baseText || "").trim());
    if (!baseName) return null;
    return {
      name: `${baseName} ${categoryName}`,
      categoryName,
      quantity: parsed ? parsed.quantity : null,
      unit: parsed ? parsed.unit : null,
      baseName,
      reason,
    };
  }

  // Echte Spezialziele werden vor jeder Mengen-/Artikelverarbeitung abgetrennt.
  // Firma kann ohne Menge vorkommen. Der typische Alexa-Fehlhörer "vier mal"
  // bleibt dagegen nur dann ein Firmenziel, wenn davor bereits eine eindeutige
  // Menge steht; "Butter vier mal" bleibt somit normale Menge 4.
  const firmaMatch = /^(.+?)\s+firma\s*$/i.exec(raw);
  if (firmaMatch) return makeTarget(firmaMatch[1], "Firma", "direktes Firma-Suffix");

  const firmaMisheard = /^(.+?)\s+(?:vier\s+mal|viermal|vier\s+ma|4\s*mal|4\s+ma)\s*$/i.exec(raw);
  if (firmaMisheard) {
    const parsed = parseQuantityName(firmaMisheard[1]);
    if (parsed) return {
      name: `${parsed.baseName} Firma`,
      categoryName: "Firma",
      quantity: parsed.quantity,
      unit: parsed.unit,
      baseName: parsed.baseName,
      reason: "direkter Firma-Fehlhörer",
    };
  }

  const targets = [
    { label: "REWE", rx: /^(.*?)(?:\s+rewe)\s*$/i, prefix: /^rewe\s+(.+)$/i },
    { label: "DM", rx: /^(.*?)(?:\s+d\.?\s*m\.?)\s*$/i, prefix: /^d\.?\s*m\.?\s+(.+)$/i },
    { label: "Rossmann", rx: /^(.*?)(?:\s+rossmann)\s*$/i, prefix: /^rossmann\s+(.+)$/i },
    { label: "Müller", rx: /^(.*?)(?:\s+(?:müller|mueller))\s*$/i, prefix: /^(?:müller|mueller)\s+(.+)$/i },
    { label: "Meyerhof", rx: /^(.*?)(?:\s+meyerhof)\s*$/i, prefix: /^meyerhof\s+(.+)$/i },
  ];
  for (const target of targets) {
    const suffix = target.rx.exec(raw);
    if (suffix && suffix[1] && suffix[1].trim()) return makeTarget(suffix[1], target.label, `direktes ${target.label}-Ziel`);
    const prefix = target.prefix.exec(raw);
    if (prefix && prefix[1] && prefix[1].trim()) return makeTarget(prefix[1], target.label, `direktes ${target.label}-Ziel`);
  }
  return null;
}

function directFirmaInterpretation(value) {
  const interpreted = directSpecialTargetInterpretation(value);
  return interpreted && interpreted.categoryName === "Firma" ? interpreted : null;
}

function firmaInterpretationFromHistory(history, currentName) {
  const direct = directFirmaInterpretation(currentName);
  if (direct) return direct;
  const current = parseQuantityName(currentName);
  if (!current || current.quantity !== 4) return null;
  const currentBase = normalizeItem(current.baseName);
  const previous = [...(history || [])].reverse().find((entry) => {
    const parsed = parseQuantityName(entry && entry.name);
    return parsed && parsed.quantity !== 4 && normalizeItem(parsed.baseName) === currentBase;
  });
  if (!previous) return null;
  const parsedPrevious = parseQuantityName(previous.name);
  return {
    name: `${parsedPrevious.baseName} Firma`,
    categoryName: "Firma",
    quantity: parsedPrevious.quantity,
    unit: parsedPrevious.unit,
    baseName: parsedPrevious.baseName,
    reason: `Alexa-Übergang ${parsedPrevious.raw} → ${current.raw}`,
  };
}

function candidateKey(item, index = 0) {
  return alexaItemId(item) || `${normalizeItem(alexaItemName(item))}#${index}`;
}

function updateAlexaCandidates(memory, items, now = Date.now(), options = {}) {
  const minStableMs = Number(options.minStableMs ?? 10000);
  const minStablePolls = Number(options.minStablePolls ?? 3);
  const maxHistoryMs = Number(options.maxHistoryMs ?? 45000);
  const ready = [];
  const waiting = [];
  const seen = new Set();

  (items || []).forEach((item, index) => {
    const name = alexaItemName(item);
    const key = candidateKey(item, index);
    if (!name || !key) return;
    seen.add(key);
    let candidate = memory.get(key);
    if (!candidate) {
      candidate = { key, itemId: alexaItemId(item), lastName: "", stableSince: now, stablePolls: 0, history: [], lastSeen: now };
      memory.set(key, candidate);
    }
    candidate.lastSeen = now;
    candidate.history = (candidate.history || []).filter((entry) => now - entry.at <= maxHistoryMs);
    if (candidate.lastName !== name) {
      candidate.lastName = name;
      candidate.stableSince = now;
      candidate.stablePolls = 1;
      candidate.history.push({ name, at: now });
    } else {
      candidate.stablePolls += 1;
    }

    const interpretation = firmaInterpretationFromHistory(candidate.history.slice(0, -1), name)
      || directSpecialTargetInterpretation(name);
    const stableFor = now - candidate.stableSince;
    const isReady = candidate.stablePolls >= minStablePolls && stableFor >= minStableMs;
    const summary = {
      key,
      item,
      rawName: name,
      stablePolls: candidate.stablePolls,
      stableFor,
      interpretation,
      history: candidate.history.map((entry) => entry.name),
    };
    if (isReady) ready.push(summary); else waiting.push(summary);
  });

  for (const [key, candidate] of memory) {
    if (!seen.has(key) && now - candidate.lastSeen > maxHistoryMs) memory.delete(key);
  }
  return { ready, waiting };
}

function importPayloadForCandidate(candidate) {
  if (candidate.interpretation) {
    // Sobald die Kategorie strukturiert bekannt ist, niemals den Kategorie-/Mengen-
    // Zusatz nochmals im Artikelnamen transportieren. Dadurch kann die Ziel-App
    // keinen Stammartikel wie "Butter 10x Firma" mehr anlegen.
    const cleanName = candidate.interpretation.baseName || candidate.interpretation.name;
    const payload = {
      name: cleanName,
      quantity: candidate.interpretation.quantity,
      unit: candidate.interpretation.unit,
    };
    if (candidate.interpretation.categoryName) payload.categoryName = candidate.interpretation.categoryName;
    return payload;
  }
  const parsed = parseQuantityName(candidate.rawName);
  if (parsed) return { name: parsed.baseName, quantity: parsed.quantity, unit: parsed.unit };
  return { name: candidate.rawName };
}

module.exports = {
  alexaItemName,
  alexaItemId,
  alexaRawNameFields,
  sanitizeAlexaRaw,
  capitalizeFirst,
  normalizeItem,
  processedItemName,
  planTransfers,
  parseQuantityName,
  directSpecialTargetInterpretation,
  directFirmaInterpretation,
  firmaInterpretationFromHistory,
  updateAlexaCandidates,
  importPayloadForCandidate,
};
