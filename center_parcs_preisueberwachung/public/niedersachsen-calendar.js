"use strict";

(function attachCalendar(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.NiedersachsenCalendar = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function calendarFactory() {
  const SCHOOL_HOLIDAYS = [
    { start: "2024-02-01", end: "2024-02-02", name: "Halbjahresferien Niedersachsen" },
    { start: "2024-03-18", end: "2024-03-28", name: "Osterferien Niedersachsen" },
    { start: "2024-05-10", end: "2024-05-10", name: "Ferientag Niedersachsen" },
    { start: "2024-05-21", end: "2024-05-21", name: "Pfingstferien Niedersachsen" },
    { start: "2024-06-24", end: "2024-08-03", name: "Sommerferien Niedersachsen" },
    { start: "2024-10-04", end: "2024-10-19", name: "Herbstferien Niedersachsen" },
    { start: "2024-11-01", end: "2024-11-01", name: "Ferientag Niedersachsen" },
    { start: "2024-12-23", end: "2025-01-04", name: "Weihnachtsferien Niedersachsen" },

    { start: "2025-02-03", end: "2025-02-04", name: "Halbjahresferien Niedersachsen" },
    { start: "2025-04-07", end: "2025-04-19", name: "Osterferien Niedersachsen" },
    { start: "2025-04-30", end: "2025-04-30", name: "Ferientag Niedersachsen" },
    { start: "2025-05-02", end: "2025-05-02", name: "Ferientag Niedersachsen" },
    { start: "2025-05-30", end: "2025-05-30", name: "Ferientag Niedersachsen" },
    { start: "2025-06-10", end: "2025-06-10", name: "Pfingstferien Niedersachsen" },
    { start: "2025-07-03", end: "2025-08-13", name: "Sommerferien Niedersachsen" },
    { start: "2025-10-13", end: "2025-10-25", name: "Herbstferien Niedersachsen" },
    { start: "2025-12-22", end: "2026-01-05", name: "Weihnachtsferien Niedersachsen" },

    { start: "2026-02-02", end: "2026-02-03", name: "Halbjahresferien Niedersachsen" },
    { start: "2026-03-23", end: "2026-04-07", name: "Osterferien Niedersachsen" },
    { start: "2026-05-15", end: "2026-05-15", name: "Ferientag Niedersachsen" },
    { start: "2026-05-26", end: "2026-05-26", name: "Pfingstferien Niedersachsen" },
    { start: "2026-07-02", end: "2026-08-12", name: "Sommerferien Niedersachsen" },
    { start: "2026-10-12", end: "2026-10-24", name: "Herbstferien Niedersachsen" },
    { start: "2026-12-23", end: "2027-01-09", name: "Weihnachtsferien Niedersachsen" },

    { start: "2027-02-01", end: "2027-02-02", name: "Halbjahresferien Niedersachsen" },
    { start: "2027-03-22", end: "2027-04-03", name: "Osterferien Niedersachsen" },
    { start: "2027-05-07", end: "2027-05-07", name: "Ferientag Niedersachsen" },
    { start: "2027-05-18", end: "2027-05-18", name: "Pfingstferien Niedersachsen" },
    { start: "2027-07-08", end: "2027-08-18", name: "Sommerferien Niedersachsen" },
    { start: "2027-10-16", end: "2027-10-30", name: "Herbstferien Niedersachsen" },
    { start: "2027-12-23", end: "2028-01-08", name: "Weihnachtsferien Niedersachsen" },

    { start: "2028-01-31", end: "2028-02-01", name: "Halbjahresferien Niedersachsen" },
    { start: "2028-04-10", end: "2028-04-22", name: "Osterferien Niedersachsen" },
    { start: "2028-05-26", end: "2028-05-26", name: "Ferientag Niedersachsen" },
    { start: "2028-06-06", end: "2028-06-06", name: "Pfingstferien Niedersachsen" },
    { start: "2028-07-20", end: "2028-08-30", name: "Sommerferien Niedersachsen" },
    { start: "2028-10-02", end: "2028-10-02", name: "Ferientag Niedersachsen" },
    { start: "2028-10-23", end: "2028-11-04", name: "Herbstferien Niedersachsen" },
    { start: "2028-12-27", end: "2029-01-06", name: "Weihnachtsferien Niedersachsen" },

    { start: "2029-02-01", end: "2029-02-02", name: "Halbjahresferien Niedersachsen" },
    { start: "2029-03-19", end: "2029-04-03", name: "Osterferien Niedersachsen" },
    { start: "2029-04-30", end: "2029-04-30", name: "Ferientag Niedersachsen" },
    { start: "2029-05-11", end: "2029-05-11", name: "Ferientag Niedersachsen" },
    { start: "2029-05-22", end: "2029-05-22", name: "Pfingstferien Niedersachsen" },
    { start: "2029-07-19", end: "2029-08-29", name: "Sommerferien Niedersachsen" },
    { start: "2029-10-04", end: "2029-10-05", name: "Ferientage Niedersachsen" },
    { start: "2029-10-22", end: "2029-11-02", name: "Herbstferien Niedersachsen" },
    { start: "2029-12-21", end: "2030-01-05", name: "Weihnachtsferien Niedersachsen" },

    { start: "2030-01-31", end: "2030-02-01", name: "Halbjahresferien Niedersachsen" },
    { start: "2030-04-08", end: "2030-04-23", name: "Osterferien Niedersachsen" },
    { start: "2030-05-31", end: "2030-05-31", name: "Ferientag Niedersachsen" },
    { start: "2030-06-11", end: "2030-06-11", name: "Pfingstferien Niedersachsen" },
    { start: "2030-07-11", end: "2030-08-21", name: "Sommerferien Niedersachsen" },
  ];

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function isoFromDate(date) {
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
  }

  function dateFromIso(value) {
    const [year, month, day] = String(value).split("-").map(Number);
    return new Date(Date.UTC(year, month - 1, day, 12));
  }

  function addDays(value, amount) {
    const date = typeof value === "string" ? dateFromIso(value) : new Date(value.getTime());
    date.setUTCDate(date.getUTCDate() + amount);
    return isoFromDate(date);
  }

  // Gregorian Easter calculation (Meeus/Jones/Butcher).
  function easterSunday(year) {
    const a = year % 19;
    const b = Math.floor(year / 100);
    const c = year % 100;
    const d = Math.floor(b / 4);
    const e = b % 4;
    const f = Math.floor((b + 8) / 25);
    const g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4);
    const k = c % 4;
    const l = (32 + 2 * e + 2 * i - h - k) % 7;
    const m = Math.floor((a + 11 * h + 22 * l) / 451);
    const month = Math.floor((h + l - 7 * m + 114) / 31);
    const day = ((h + l - 7 * m + 114) % 31) + 1;
    return `${year}-${pad(month)}-${pad(day)}`;
  }

  function publicHolidayMap(year) {
    const easter = easterSunday(year);
    return new Map([
      [`${year}-01-01`, "Neujahr"],
      [addDays(easter, -2), "Karfreitag"],
      [addDays(easter, 1), "Ostermontag"],
      [`${year}-05-01`, "Tag der Arbeit"],
      [addDays(easter, 39), "Christi Himmelfahrt"],
      [addDays(easter, 50), "Pfingstmontag"],
      [`${year}-10-03`, "Tag der Deutschen Einheit"],
      [`${year}-10-31`, "Reformationstag"],
      [`${year}-12-25`, "1. Weihnachtstag"],
      [`${year}-12-26`, "2. Weihnachtstag"],
    ]);
  }

  function publicHolidayInfo(value) {
    const year = Number(String(value).slice(0, 4));
    const name = publicHolidayMap(year).get(value);
    return name ? { name } : null;
  }

  function schoolHolidayInfo(value) {
    const match = SCHOOL_HOLIDAYS.find((item) => value >= item.start && value <= item.end);
    return match ? { ...match } : null;
  }

  function dayInfo(value) {
    return {
      publicHoliday: publicHolidayInfo(value),
      schoolHoliday: schoolHolidayInfo(value),
    };
  }

  return {
    SCHOOL_HOLIDAYS,
    addDays,
    dayInfo,
    easterSunday,
    publicHolidayInfo,
    schoolHolidayInfo,
  };
});
