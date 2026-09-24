"use strict";

function compactParkName(value) {
  let name = String(value || "").replace(/\s+/g, " ").trim();
  name = name.replace(/^Center\s*Parcs?\s*/i, "").trim();
  name = name.replace(/^Park\s+/i, "").trim();
  if (/hoch\s*sauerland|hochsauerland|medebach/i.test(name)) return "Medebach";
  return name;
}

function compactStayLabel(stay) {
  const parse = (value) => {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return match ? { month: match[2], day: String(Number(match[3])) } : null;
  };
  const start = parse(stay?.start_date);
  const end = parse(stay?.end_date);
  if (!start || !end) return "Bestzeitraum";
  return start.month === end.month
    ? `${start.day}. - ${end.day}.${end.month}`
    : `${start.day}.${start.month} - ${end.day}.${end.month}`;
}

function signedCompactEuro(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "";
  const rounded = Math.round(number);
  const sign = rounded > 0 ? "+" : "";
  return `${sign}${rounded.toLocaleString("de-DE")}€`;
}

function formatPriceChangePush({ parkName, houseName, stay, difference }) {
  const park = compactParkName(parkName);
  const number = Number(difference);
  const prefix = park ? `CP ${park}` : "CP";
  const title = number < 0
    ? `${prefix}: Preis gefallen`
    : number > 0
      ? `${prefix}: Preis gestiegen`
      : `${prefix}: Bestpreis geändert`;
  const amount = signedCompactEuro(number);
  const message = `${String(houseName || "Unterkunft").trim()} - ${compactStayLabel(stay)}${amount ? ` ${amount}` : ""}`;
  return { title, message };
}

module.exports = { compactParkName, compactStayLabel, signedCompactEuro, formatPriceChangePush };
