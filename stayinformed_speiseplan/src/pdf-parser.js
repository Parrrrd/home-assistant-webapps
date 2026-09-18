"use strict";

const WEEKDAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag"];
const WEEKDAY_LABELS = {
  montag: "Montag",
  dienstag: "Dienstag",
  mittwoch: "Mittwoch",
  donnerstag: "Donnerstag",
  freitag: "Freitag",
};

function normalizeLine(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/([„(])\s+/g, "$1")
    .replace(/\s+([)”])/g, "$1")
    .replace(/\s*-\s*/g, "-")
    .trim();
}

function removeAllergenSuffix(value) {
  let result = normalizeLine(value);

  while (/\s+\([A-Za-zÄÖÜäöüß0-9*,.\s()]+\)$/.test(result)) {
    result = result.replace(/\s+\([A-Za-zÄÖÜäöüß0-9*,.\s()]+\)$/, "").trim();
  }

  return result;
}

function isoDate(year, month, day) {
  const value = new Date(Date.UTC(year, month - 1, day));
  if (
    value.getUTCFullYear() !== year ||
    value.getUTCMonth() !== month - 1 ||
    value.getUTCDate() !== day
  ) {
    return null;
  }
  return value.toISOString().slice(0, 10);
}

function parseDateRange(lines, fallback = {}) {
  const compact = lines.slice(0, 8).join("").replace(/\s+/g, "");

  let match = compact.match(
    /(\d{1,2})\.(\d{1,2})\.(\d{4})[–-](\d{1,2})\.(\d{1,2})\.(\d{4})/,
  );
  if (match) {
    return {
      start_date: isoDate(Number(match[3]), Number(match[2]), Number(match[1])),
      end_date: isoDate(Number(match[6]), Number(match[5]), Number(match[4])),
    };
  }

  match = compact.match(
    /(\d{1,2})\.(\d{1,2})\.[–-](\d{1,2})\.(\d{1,2})\.(\d{4})/,
  );
  if (match) {
    return {
      start_date: isoDate(Number(match[5]), Number(match[2]), Number(match[1])),
      end_date: isoDate(Number(match[5]), Number(match[4]), Number(match[3])),
    };
  }

  match = compact.match(
    /(\d{1,2})\.([–-])(\d{1,2})\.(\d{1,2})\.(\d{4})/,
  );
  if (match) {
    return {
      start_date: isoDate(Number(match[5]), Number(match[4]), Number(match[1])),
      end_date: isoDate(Number(match[5]), Number(match[4]), Number(match[3])),
    };
  }

  return {
    start_date: String(fallback.start_date || fallback.start || "").slice(0, 10) || null,
    end_date: String(fallback.end_date || fallback.end || "").slice(0, 10) || null,
  };
}

async function extractPdfLines(buffer) {
  const { getDocument } = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const document = await getDocument({
    data: new Uint8Array(buffer),
    disableFontFace: true,
  }).promise;
  const lines = [];

  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent();
    const groups = [];

    for (const item of content.items) {
      const text = String(item.str || "").trim();
      if (!text) continue;

      const y = item.transform[5];
      let group = groups.find((entry) => Math.abs(entry.y - y) < 2);
      if (!group) {
        group = { y, items: [] };
        groups.push(group);
      }
      group.items.push({ x: item.transform[4], text });
    }

    groups.sort((left, right) => right.y - left.y);
    for (const group of groups) {
      const line = normalizeLine(
        group.items
          .sort((left, right) => left.x - right.x)
          .map((item) => item.text)
          .join(" "),
      );
      if (line) lines.push(line);
    }
  }

  return lines;
}

function parseWeekdaySections(lines) {
  const days = Object.fromEntries(WEEKDAYS.map((day) => [day, []]));
  const notes = [];
  let currentDay = null;
  let notesStarted = false;

  for (const rawLine of lines) {
    const line = normalizeLine(rawLine);
    const lower = line.toLocaleLowerCase("de-DE");
    const weekday = WEEKDAYS.find((day) => lower === day);

    if (weekday) {
      currentDay = weekday;
      notesStarted = false;
      continue;
    }

    if (/^speiseplan\b/i.test(line)) continue;
    if (/^allergene und zusatzstoffe/i.test(line)) break;
    if (/^\(\*\)\s*bei bedarf/i.test(line)) break;

    if (/^täglich\b/i.test(line) || /^zum eintopf\b/i.test(line)) {
      notesStarted = true;
      currentDay = null;
    }

    if (notesStarted) {
      notes.push(line.replace(/,$/, "."));
      continue;
    }

    if (currentDay) days[currentDay].push(removeAllergenSuffix(line));
  }

  const joinedDays = {};
  for (const day of WEEKDAYS) {
    const value = days[day].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
    joinedDays[day] = value || "Kein Essen angegeben";
  }

  return {
    days: joinedDays,
    notes: notes.filter(Boolean),
  };
}

async function parseLunchPlanPdf(buffer, fallback = {}) {
  const lines = await extractPdfLines(buffer);
  const range = parseDateRange(lines, fallback);
  const sections = parseWeekdaySections(lines);

  if (!range.start_date || !range.end_date) {
    throw new Error("Im PDF konnte kein gültiger Datumsbereich erkannt werden.");
  }

  const meaningfulDays = WEEKDAYS.filter(
    (day) => sections.days[day] !== "Kein Essen angegeben",
  );
  if (meaningfulDays.length < 3) {
    throw new Error("Im PDF konnten nicht genügend Wochentage erkannt werden.");
  }

  return {
    title: String(fallback.title || "Kindergarten-Speiseplan"),
    start_date: range.start_date,
    end_date: range.end_date,
    days: sections.days,
    notes: sections.notes,
    extracted_lines: lines,
  };
}

module.exports = {
  WEEKDAYS,
  WEEKDAY_LABELS,
  extractPdfLines,
  parseLunchPlanPdf,
};
