const NUMBER_WORDS = {
  ein: 1, eine: 1, einen: 1, einem: 1, einer: 1, eins: 1,
  zwei: 2, drei: 3, vier: 4, fünf: 5, fuenf: 5, sechs: 6,
  sieben: 7, acht: 8, neun: 9, zehn: 10,
};

const DIGIT_WORDS = {
  null: 0, nullen: 0, eins: 1, ein: 1, eine: 1, einen: 1,
  funf: 5,
  zwei: 2, drei: 3, vier: 4, fünf: 5, fuenf: 5, sechs: 6,
  sieben: 7, acht: 8, neun: 9,
};

function normalizeText(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/ß/g, "ss").replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
}

function firstUpper(value) {
  const text = String(value || "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function numberValue(value) {
  const text = normalizeText(value);
  if (NUMBER_WORDS[text] !== undefined) return NUMBER_WORDS[text];
  const wordDigits = text.split(" ");
  if (wordDigits.length > 1 && wordDigits.every((word) => DIGIT_WORDS[word] !== undefined)) {
    return Number(wordDigits.map((word) => DIGIT_WORDS[word]).join(""));
  }
  const numeric = Number(String(value).replace(",", "."));
  return Number.isFinite(numeric) ? numeric : null;
}

function numberExpressionValue(value) {
  const text = normalizeText(value);
  const comma = text.match(/^(.+?)\s+komma\s+(.+)$/);
  if (!comma) return numberValue(value);
  const whole = numberValue(comma[1]);
  if (whole === null) return null;
  const fractionText = comma[2].trim();
  const fractionWords = fractionText.split(" ");
  const fraction = /^\d+$/.test(fractionText)
    ? fractionText
    : (fractionWords.length > 0 && fractionWords.every((word) => DIGIT_WORDS[word] !== undefined)
      ? fractionWords.map((word) => DIGIT_WORDS[word]).join("")
      : null);
  if (fraction === null || !fraction.length) return null;
  const result = Number(`${whole}.${fraction}`);
  return Number.isFinite(result) ? result : null;
}

function parseQuantity(value, unit) {
  const quantity = numberExpressionValue(value);
  if (quantity === null) return null;
  const normalizedUnit = normalizeText(unit || "stück");
  const aliases = { stk: "stück", stueck: "stück", stuck: "stück", x: "stück", kilo: "kg", liter: "l", kisten: "kiste", kartons: "karton", packungen: "packung", flaschen: "flasche", dosen: "dose", beutel: "beutel", nachfuellbeutel: "nachfüllbeutel", nachfullbeutel: "nachfüllbeutel", "nachfüllbeutel": "nachfüllbeutel", tueten: "tüte", tüten: "tüte", rollen: "rolle" };
  return { value: quantity, unit: aliases[normalizedUnit] || normalizedUnit };
}

function parseItemInput(input) {
  const original = String(input || "").trim().replace(/\s+/g, " ");
  if (!original) throw new Error("Bitte einen Artikel eingeben.");
  const numberWordPattern = "(?:ein|eine|einen|einem|einer|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)";
  const decimalDigitWordPattern = "(?:null|nullen|eins|ein|eine|einen|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun)";
  const numberPattern = `(?:\\d+(?:[.,]\\d+)?|${numberWordPattern})(?:\\s+komma\\s+(?:\\d+|${decimalDigitWordPattern})(?:\\s+(?:${decimalDigitWordPattern}))*)?`;
  const unitPattern = "(kg|kilo|g|mg|l|liter|ml|stück|stueck|stk|packung|packungen|paket|flasche|flaschen|dose|dosen|bund|kiste|kisten|karton|kartons|beutel|nachfüllbeutel|nachfuellbeutel|nachfullbeutel|tüte|tüten|tuete|tueten|rolle|rollen|x)?";
  const leading = new RegExp(`^(${numberPattern})\\s*(?:mal\\s*)?${unitPattern}\\s+(.+)$`, "i").exec(original);
  const unitFirst = new RegExp(`^(stück|stueck|stk|packung|paket|flasche|dose|bund|kiste|karton|beutel|nachfüllbeutel|nachfuellbeutel|nachfullbeutel|tüte|tuete|rolle)\\s+(.+)$`, "i").exec(original);
  const trailing = new RegExp(`^(.+?)\\s+(${numberPattern})\\s*(?:mal\\s*)?(kg|kilo|g|mg|l|liter|ml|stück|stueck|stk|packung|packungen|paket|flasche|flaschen|dose|dosen|bund|kiste|kisten|karton|kartons|beutel|nachfüllbeutel|nachfuellbeutel|nachfullbeutel|tüte|tüten|tuete|tueten|rolle|rollen|x)?$`, "i").exec(original);
  const trailingUnitOnly = new RegExp(`^(.+?)\\s+(nachfüllbeutel|nachfuellbeutel|nachfullbeutel|packung|paket|flasche|dose|bund|kiste|karton|beutel|tüte|tuete|rolle)$`, "i").exec(original);
  let name = original;
  let quantity = null;
  if (leading) {
    quantity = parseQuantity(leading[1], leading[2] || "stück");
    name = leading[3];
  } else if (unitFirst) {
    quantity = parseQuantity(1, unitFirst[1]);
    name = unitFirst[2];
  } else if (trailing) {
    quantity = parseQuantity(trailing[2], trailing[3]);
    name = trailing[1];
  } else if (trailingUnitOnly) {
    quantity = parseQuantity(1, trailingUnitOnly[2]);
    name = trailingUnitOnly[1];
  }
  return { original, name: firstUpper(name), quantity };
}

function quantitySignature(quantity) {
  if (!quantity || quantity.value === null || quantity.value === undefined) return "none";
  const value = Number(quantity.value);
  const unit = normalizeText(quantity.unit || "stück");
  const factors = { mg: [0.001, "g"], g: [1, "g"], kg: [1000, "g"], ml: [1, "ml"], l: [1000, "ml"] };
  if (factors[unit]) return `${Math.round(value * factors[unit][0] * 1000) / 1000}${factors[unit][1]}`;
  return `${value}${unit}`;
}

function duplicateKey(productKey, quantity) {
  return `${productKey}|${quantitySignature(quantity)}`;
}

module.exports = { normalizeText, firstUpper, parseItemInput, quantitySignature, duplicateKey };
