import json
import math
import os
import threading
import time as time_module
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, flash, redirect, render_template, request, url_for

APP_VERSION = "0.1.12"
DATA_DIR = Path(os.environ.get("MOUNJARO_DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "mounjaro_data.json"
PORT = int(os.environ.get("PORT", "8140"))
DEFAULT_WEIGHT_SENSOR = os.environ.get("MOUNJARO_WEIGHT_SENSOR", "sensor.withings_gewicht_4")
DEFAULT_HALF_LIFE = float(os.environ.get("MOUNJARO_HALF_LIFE_DAYS", "5") or 5)
AUTO_WEIGHT_INTERVAL_HOURS = float(os.environ.get("MOUNJARO_AUTO_WEIGHT_INTERVAL_HOURS", "6") or 6)
DEFAULT_AUTO_SAVE_WEIGHT = str(os.environ.get("MOUNJARO_AUTO_SAVE_WEIGHT", "true")).lower() in {"1", "true", "yes", "on", "ja"}

app = Flask(__name__)
app.secret_key = os.environ.get("MOUNJARO_SECRET", "mounjaro-local-secret")

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember"
]

DEFAULT_INJECTIONS = [
    {"number": 1, "date": "2026-01-20", "time": "13:14", "dose": 1.25, "site": "Bauch links", "note": ""},
    {"number": 2, "date": "2026-01-27", "time": "17:00", "dose": 1.25, "site": "Bauch rechts", "note": ""},
    {"number": 3, "date": "2026-02-03", "time": "14:17", "dose": 1.25, "site": "Bauch links", "note": ""},
    {"number": 4, "date": "2026-02-10", "time": "16:56", "dose": 1.25, "site": "Bauch rechts", "note": ""},
    {"number": 5, "date": "2026-02-17", "time": "19:00", "dose": 1.25, "site": "Bauch links", "note": ""},
    {"number": 6, "date": "2026-02-24", "time": "20:00", "dose": 1.5, "site": "Bauch rechts", "note": ""},
    {"number": 7, "date": "2026-03-03", "time": "20:00", "dose": 1.5, "site": "Bauch links", "note": ""},
    {"number": 8, "date": "2026-03-10", "time": "20:00", "dose": 1.5, "site": "Bauch rechts", "note": ""},
    {"number": 9, "date": "2026-03-17", "time": "20:00", "dose": 2.0, "site": "Bauch links", "note": "War Rest von der goldenen Dosis, ggf. auch ein wenig"},
    {"number": 10, "date": "2026-03-24", "time": "20:40", "dose": 2.0, "site": "Bauch rechts", "note": ""},
    {"number": 11, "date": "2026-03-31", "time": "21:11", "dose": 2.0, "site": "Bauch links", "note": ""},
    {"number": 12, "date": "2026-04-07", "time": "23:55", "dose": 2.0, "site": "Bauch rechts", "note": ""},
    {"number": 13, "date": "2026-04-14", "time": "20:50", "dose": 2.0, "site": "Bauch links", "note": ""},
    {"number": 14, "date": "2026-04-21", "time": "21:04", "dose": 2.0, "site": "Bauch rechts", "note": ""},
    {"number": 15, "date": "2026-04-28", "time": "20:52", "dose": 2.5, "site": "Bauch links", "note": ""},
]


def make_default_data() -> Dict[str, Any]:
    injections = []
    for item in DEFAULT_INJECTIONS:
        row = deepcopy(item)
        row["id"] = str(uuid.uuid4())
        injections.append(row)
    return {
        "version": 2,
        "settings": {
            "medicine_name": "Mounjaro®",
            "half_life_days": 5.4,
            "absorption_tmax_hours": 24,
            "bioavailability_factor": 1.0,
            "click_pen_mg": 7.5,
            "click_target_mg": 2.5,
            "click_full": 60,
            "weight_sensor": DEFAULT_WEIGHT_SENSOR,
            "dose_options": [1.25, 1.5, 2.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0],
            "target_weight": "",
            "start_weight": "",
            "weekly_interval_days": 7,
            "auto_save_weight": DEFAULT_AUTO_SAVE_WEIGHT,
        },
        "injections": injections,
        "weights": [],
        "symptoms": [],
        "meta": {},
    }


def ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        save_data(make_default_data())


def load_data() -> Dict[str, Any]:
    ensure_data()
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        # Wenn die JSON-Datei einmal defekt ist, App nicht mit weißer Seite sterben lassen.
        backup = DATA_FILE.with_suffix(f".broken-{int(time_module.time())}.json")
        try:
            DATA_FILE.replace(backup)
        except Exception:
            pass
        data = make_default_data()
        save_data(data)

    data, changed = ensure_data_integrity(data)
    if changed:
        save_data(data)
    return data

def save_data(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def parse_dt(date_str: str, time_str: str = "00:00") -> datetime:
    return datetime.strptime(f"{date_str} {time_str or '00:00'}", "%Y-%m-%d %H:%M")


def safe_parse_dt(date_str: str, time_str: str = "00:00") -> datetime:
    try:
        return parse_dt(date_str, time_str)
    except Exception:
        return datetime(1900, 1, 1)


def fmt_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day:02d}.{dt.month:02d}.{dt.year}"
    except Exception:
        return date_str


def fmt_short_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day:02d}.{dt.month:02d}."
    except Exception:
        return date_str


def fmt_weekday_short(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{WEEKDAYS[dt.weekday()]}, {dt.day:02d}.{dt.month:02d}."
    except Exception:
        return date_str


def fmt_dt(date_str: str, time_str: str) -> str:
    try:
        dt = parse_dt(date_str, time_str)
        return f"{WEEKDAYS[dt.weekday()]}, {dt.day}. {MONTHS[dt.month-1]} um {dt.strftime('%H:%M')} Uhr"
    except Exception:
        return f"{fmt_date(date_str)} {time_str}"


def fmt_dose(value: Any) -> str:
    try:
        x = float(value)
    except Exception:
        return str(value)
    s = f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{s} mg"


def fmt_number(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except Exception:
        return "—"


def fmt_mg_amount(value: Any, digits: int = 2) -> str:
    v = parse_float(value)
    if v is None:
        return "—"
    return f"{v:.{digits}f}".replace(".", ",") + " mg"


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("kg", "").replace("mg", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}


def normalize_site(value: Any, fallback: str = "Bauch links") -> str:
    text = str(value or "").strip().lower()
    if "rechts" in text:
        return "Bauch rechts"
    if "links" in text:
        return "Bauch links"
    return fallback if fallback in {"Bauch links", "Bauch rechts"} else "Bauch links"


def opposite_site(value: Any) -> str:
    return "Bauch rechts" if normalize_site(value) == "Bauch links" else "Bauch links"


def stable_injection_id(row: Dict[str, Any]) -> str:
    raw = str(row.get("id") or "").strip()
    if raw:
        return raw
    base = "|".join([
        str(row.get("date", "")),
        str(row.get("time", "")),
        str(row.get("dose", "")),
        str(row.get("site", "")),
        str(row.get("note", "")),
    ])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mounjaro-injection-" + base))


def ensure_data_integrity(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    changed = False
    data.setdefault("settings", {})
    data.setdefault("injections", [])
    data.setdefault("weights", [])
    data.setdefault("symptoms", [])
    data.setdefault("meta", {})

    data["settings"].setdefault("weight_sensor", DEFAULT_WEIGHT_SENSOR)
    data["settings"].setdefault("half_life_days", 5.4)
    data["settings"].setdefault("absorption_tmax_hours", 24)
    data["settings"].setdefault("bioavailability_factor", 1.0)
    data["settings"].setdefault("click_pen_mg", 7.5)
    data["settings"].setdefault("click_target_mg", 2.5)
    data["settings"].setdefault("click_full", 60)
    data["settings"].setdefault("dose_options", [1.25, 1.5, 2.0, 2.5, 5.0, 7.5])
    data["settings"].setdefault("medicine_name", "Mounjaro®")
    data["settings"].setdefault("weekly_interval_days", 7)
    data["settings"].setdefault("auto_save_weight", DEFAULT_AUTO_SAVE_WEIGHT)

    cleaned_injections = []
    seen_ids = set()
    for row in data.get("injections", []):
        if not isinstance(row, dict):
            changed = True
            continue
        old = deepcopy(row)
        row["id"] = stable_injection_id(row)
        if row["id"] in seen_ids:
            row["id"] = str(uuid.uuid4())
        seen_ids.add(row["id"])
        row.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
        row.setdefault("time", "20:00")
        row["site"] = normalize_site(row.get("site"), "Bauch links")
        row.setdefault("note", "")
        dose = parse_float(row.get("dose"))
        row["dose"] = dose if dose is not None else 0
        # Klickdaten gibt es erst ab v0.1.12. Alte Einträge bleiben bewusst ohne
        # rückwirkend erfundene Pen-/Klickwerte.
        for click_key in ("click_pen_mg", "click_target_mg", "click_full", "click_count"):
            if click_key in row:
                parsed_click = parse_float(row.get(click_key))
                if parsed_click is None:
                    row.pop(click_key, None)
                else:
                    row[click_key] = parsed_click
        if row != old:
            changed = True
        cleaned_injections.append(row)
    data["injections"] = cleaned_injections

    cleaned_weights = []
    seen_weight_ids = set()
    for row in data.get("weights", []):
        if not isinstance(row, dict):
            changed = True
            continue
        old = deepcopy(row)
        row["id"] = str(row.get("id") or uuid.uuid4())
        if row["id"] in seen_weight_ids:
            row["id"] = str(uuid.uuid4())
        seen_weight_ids.add(row["id"])
        row.setdefault("note", "")
        row.setdefault("source", "manuell")
        if row != old:
            changed = True
        cleaned_weights.append(row)
    data["weights"] = cleaned_weights
    return data, changed


def sorted_injections(data: Dict[str, Any], reverse: bool = False) -> List[Dict[str, Any]]:
    rows = deepcopy(data.get("injections", []))
    rows.sort(key=lambda x: safe_parse_dt(x.get("date", "1900-01-01"), x.get("time", "00:00")), reverse=False)
    for idx, row in enumerate(rows, start=1):
        row["number"] = idx
    if reverse:
        rows.reverse()
    return rows


def enrich_injections(data: Dict[str, Any], reverse: bool = True) -> List[Dict[str, Any]]:
    enriched = []
    for idx, row in enumerate(sorted_injections(data, reverse=False), start=1):
        item = deepcopy(row)
        item["number"] = idx
        item["date_label"] = fmt_dt(item.get("date", ""), item.get("time", ""))
        item["short_date"] = fmt_short_date(item.get("date", ""))
        item["weekday_date"] = fmt_weekday_short(item.get("date", ""))
        item["dose_label"] = fmt_dose(item.get("dose"))
        item["dose_class"] = str(item.get("dose", "")).replace(".", "_").replace(",", "_")
        enriched.append(item)
    if reverse:
        enriched.reverse()
    return enriched


def latest_injection(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = enrich_injections(data, reverse=True)
    return rows[0] if rows else None


def next_injection(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    last = latest_injection(data)
    if not last:
        return None
    interval = int(data.get("settings", {}).get("weekly_interval_days") or 7)
    last_dt = parse_dt(last["date"], last.get("time", "20:00"))
    next_dt = last_dt + timedelta(days=interval)
    next_site = opposite_site(last.get("site"))
    return {
        "number": int(last.get("number", 0)) + 1,
        "date": next_dt.strftime("%Y-%m-%d"),
        "time": next_dt.strftime("%H:%M"),
        "date_label": f"{WEEKDAYS[next_dt.weekday()]}, {next_dt.day}. {MONTHS[next_dt.month-1]} um {next_dt.strftime('%H:%M')} Uhr",
        "weekday_date": f"{WEEKDAYS[next_dt.weekday()]}, {next_dt.day:02d}.{next_dt.month:02d}.",
        "dose": last.get("dose", ""),
        "dose_label": fmt_dose(last.get("dose")),
        "dose_class": str(last.get("dose", "")).replace(".", "_").replace(",", "_"),
        "site": next_site,
    }


def elimination_rate_from_settings(data: Dict[str, Any]) -> float:
    half_life = parse_float(data.get("settings", {}).get("half_life_days")) or 5.4
    if half_life <= 0:
        half_life = 5.4
    return math.log(2) / half_life


def absorption_rate_for_tmax(elimination_rate: float, tmax_days: float) -> float:
    # First-order absorption/elimination: tmax = ln(ka/ke)/(ka-ke).
    # Für Tirzepatid nehmen wir standardmäßig ca. 24h bis zum Peak.
    tmax_days = max(0.25, float(tmax_days or 1.0))
    ke = max(0.0001, float(elimination_rate))
    lo = ke * 1.0001
    hi = 50.0
    for _ in range(80):
        mid = (lo + hi) / 2
        current_tmax = math.log(mid / ke) / (mid - ke)
        if current_tmax > tmax_days:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pk_parameters(data: Dict[str, Any]) -> Dict[str, float]:
    settings = data.get("settings", {})
    ke = elimination_rate_from_settings(data)
    tmax_hours = parse_float(settings.get("absorption_tmax_hours")) or 24
    tmax_days = max(0.25, tmax_hours / 24.0)
    ka = absorption_rate_for_tmax(ke, tmax_days)
    bioavailability = parse_float(settings.get("bioavailability_factor"))
    if bioavailability is None or bioavailability <= 0:
        bioavailability = 1.0
    return {"ke": ke, "ka": ka, "tmax_days": tmax_days, "tmax_hours": tmax_hours, "bioavailability": bioavailability}


def dose_amount_at(dose: float, elapsed_days: float, params: Dict[str, float]) -> float:
    if elapsed_days <= 0:
        return 0.0
    ka = params["ka"]
    ke = params["ke"]
    if abs(ka - ke) < 1e-6:
        amount = dose * ka * elapsed_days * math.exp(-ke * elapsed_days)
    else:
        amount = dose * (ka / (ka - ke)) * (math.exp(-ke * elapsed_days) - math.exp(-ka * elapsed_days))
    return max(0.0, amount * params.get("bioavailability", 1.0))


def active_amount_at(data: Dict[str, Any], moment: datetime) -> float:
    params = pk_parameters(data)
    total = 0.0
    for inj in data.get("injections", []):
        dose = parse_float(inj.get("dose"))
        if dose is None:
            continue
        inj_dt = safe_parse_dt(inj.get("date", "1900-01-01"), inj.get("time", "00:00"))
        elapsed_days = (moment - inj_dt).total_seconds() / 86400.0
        if elapsed_days < 0:
            continue
        total += dose_amount_at(dose, elapsed_days, params)
    return total


def pk_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    params = pk_parameters(data)
    now = datetime.now()
    next_item = next_injection(data)
    next_dt = safe_parse_dt(next_item["date"], next_item["time"]) if next_item else now + timedelta(days=7)
    start = now
    end = max(next_dt, now + timedelta(days=7))
    samples = [start + timedelta(seconds=(end-start).total_seconds()*i/140) for i in range(141)]
    vals = [(t, active_amount_at(data, t)) for t in samples]
    peak_t, peak_v = max(vals, key=lambda x: x[1]) if vals else (now, 0)
    trough_v = active_amount_at(data, next_dt) if next_item else None
    return {
        "tmax_hours": params["tmax_hours"],
        "half_life_days": (math.log(2) / params["ke"]) if params["ke"] else 0,
        "peak_until_next_time": peak_t,
        "peak_until_next": peak_v,
        "trough_before_next": trough_v,
        "model_label": f"Aufnahme-Peak ca. {params['tmax_hours']:.0f} h · Halbwertszeit {((math.log(2)/params['ke']) if params['ke'] else 0):.1f} Tage",
        "marker_note": "Marker zeigen künftig den rechnerischen Wirkstoffstand, nicht nur die gespritzte Dosis.",
    }


def chart_window_for_mode(data: Dict[str, Any], mode: str) -> Tuple[datetime, datetime, str]:
    mode = (mode or "week").lower()
    now = datetime.now()
    rows = sorted_injections(data, reverse=False)
    first_dt = safe_parse_dt(rows[0].get("date", "1900-01-01"), rows[0].get("time", "00:00")) if rows else now
    next_inj = next_injection(data)
    next_dt = safe_parse_dt(next_inj["date"], next_inj["time"]) if next_inj else now + timedelta(days=7)

    if mode in {"month", "monat"}:
        start = now - timedelta(days=30)
        end = max(now + timedelta(days=3), next_dt + timedelta(hours=12))
        return start, end, "month"
    if mode in {"90", "90d", "90tage", "90_tage"}:
        start = now - timedelta(days=90)
        end = max(now + timedelta(days=7), next_dt + timedelta(days=1))
        return start, end, "90"
    if mode in {"all", "gesamt", "insgesamt"}:
        start = first_dt - timedelta(days=1)
        end = max(now + timedelta(days=10), next_dt + timedelta(days=2))
        return start, end, "all"

    # Wochenansicht: aktuelle Woche plus nächste geplante Spritze, damit die Kurve nicht die ganze Historie zeigt.
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = monday
    end = max(monday + timedelta(days=7), next_dt + timedelta(hours=12), now + timedelta(days=1))
    return start, end, "week"


def curve_points(data: Dict[str, Any], range_mode: str = "week", samples: int = 160) -> Dict[str, Any]:
    start, end, mode = chart_window_for_mode(data, range_mode)
    now = datetime.now()
    rows = sorted_injections(data, reverse=False)
    if end <= start:
        end = start + timedelta(days=7)

    values: List[Tuple[datetime, float]] = []
    total_seconds = max((end - start).total_seconds(), 1)
    for i in range(max(samples, 2)):
        t = start + timedelta(seconds=total_seconds * i / (samples - 1))
        values.append((t, active_amount_at(data, t)))
    max_val = max([v for _, v in values] + [1.0])

    width = 1000
    height = 360
    pad_x = 46
    pad_top = 30
    pad_bottom = 68
    usable_w = width - 2 * pad_x
    usable_h = height - pad_top - pad_bottom

    coords: List[Tuple[datetime, float, float, float]] = []
    area = []
    for t, val in values:
        x = pad_x + ((t - start).total_seconds() / total_seconds) * usable_w
        y = pad_top + (1 - (val / max_val if max_val else 0)) * usable_h
        coords.append((t, val, x, y))
        area.append((x, y))

    def pts(items: List[Tuple[datetime, float, float, float]]) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for _, _, x, y in items)

    past = [c for c in coords if c[0] <= now]
    future = [c for c in coords if c[0] >= now]
    if past and future:
        # Heute als gemeinsamen Übergabepunkt approximieren, damit keine sichtbare Lücke entsteht.
        bridge = min(coords, key=lambda c: abs((c[0] - now).total_seconds()))
        if past[-1] != bridge:
            past.append(bridge)
        if future[0] != bridge:
            future.insert(0, bridge)
    elif not future:
        future = []

    area_points = " ".join([f"{x:.1f},{y:.1f}" for x, y in area] + [f"{pad_x+usable_w:.1f},{height-pad_bottom:.1f}", f"{pad_x:.1f},{height-pad_bottom:.1f}"])

    marker_lines = []
    params_for_markers = pk_parameters(data)
    tmax_days_for_markers = params_for_markers.get("tmax_days", 1.0)
    for inj in rows:
        inj_dt = safe_parse_dt(inj.get("date", "1900-01-01"), inj.get("time", "00:00"))
        if start <= inj_dt <= end:
            x = pad_x + ((inj_dt - start).total_seconds() / total_seconds) * usable_w
            level_at_injection = active_amount_at(data, inj_dt)
            peak_dt = inj_dt + timedelta(days=tmax_days_for_markers)
            level_near_peak = active_amount_at(data, peak_dt)
            marker_lines.append({
                "x": x,
                "dose_label": fmt_dose(inj.get("dose")),
                "level_label": fmt_mg_amount(level_at_injection, 2),
                "peak_label": fmt_mg_amount(level_near_peak, 2),
                "site": inj.get("site", ""),
            })

    labels = []
    if mode == "week":
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= end:
            x = pad_x + ((current - start).total_seconds() / total_seconds) * usable_w
            labels.append({"x": x, "label": f"{current.day}.{current.month}."})
            current += timedelta(days=1)
    else:
        tick_count = 6
        for i in range(tick_count + 1):
            t = start + timedelta(seconds=total_seconds * i / tick_count)
            x = pad_x + (i / tick_count) * usable_w
            labels.append({"x": x, "label": f"{t.day}.{t.month}."})

    week_ticks = []
    week_start = (start - timedelta(days=start.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    while week_start <= end:
        if week_start >= start:
            x = pad_x + ((week_start - start).total_seconds() / total_seconds) * usable_w
            iso = week_start.isocalendar()
            week_ticks.append({"x": x, "label": f"KW {iso.week}", "date": f"{week_start.day}.{week_start.month}."})
        week_start += timedelta(days=7)

    now_x = pad_x + ((now - start).total_seconds() / total_seconds) * usable_w

    point_data = []
    for idx, (t, val, x, y) in enumerate(coords):
        point_data.append({
            "id": idx,
            "x": round(x, 1),
            "y": round(y, 1),
            "time_iso": t.isoformat(),
            "time_label": fmt_dt(t.strftime("%Y-%m-%d"), t.strftime("%H:%M")),
            "amount_label": fmt_mg_amount(val, 2),
            "amount_value": round(val, 4),
        })

    return {
        "polyline": pts(coords),
        "polyline_past": pts(past),
        "polyline_future": pts(future),
        "area": area_points,
        "markers": marker_lines,
        "point_data": point_data,
        "labels": labels,
        "week_ticks": week_ticks,
        "max_value": max_val,
        "today_x": now_x,
        "range_mode": mode,
        "width": width,
        "height": height,
        "pad_x": pad_x,
        "pad_top": pad_top,
        "pad_bottom": pad_bottom,
        "plot_bottom": height - pad_bottom,
        "plot_right": width - pad_x,
    }

def next_injection_after(rows: List[Dict[str, Any]], moment: datetime) -> Optional[datetime]:
    for inj in rows:
        inj_dt = safe_parse_dt(inj.get("date", "1900-01-01"), inj.get("time", "00:00"))
        if inj_dt > moment:
            return inj_dt
    return None


def weekly_body_summary(data: Dict[str, Any], weeks_back: int = 10, weeks_forward: int = 1) -> List[Dict[str, Any]]:
    now = datetime.now()
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = monday - timedelta(weeks=weeks_back - 1)
    end = monday + timedelta(weeks=weeks_forward + 1)
    rows = sorted_injections(data, reverse=False)
    planned_next = next_injection(data)
    planned_next_dt = safe_parse_dt(planned_next["date"], planned_next["time"]) if planned_next else None

    result = []
    current = start
    sample_count = 169  # ca. stündlich über 7 Tage

    while current < end:
        week_end = current + timedelta(days=7)
        week_end_moment = week_end - timedelta(seconds=1)

        samples = [
            current + timedelta(seconds=((week_end - current).total_seconds() * i / (sample_count - 1)))
            for i in range(sample_count)
        ]
        vals = [active_amount_at(data, t) for t in samples]
        start_val = active_amount_at(data, current)
        calendar_end_val = active_amount_at(data, week_end_moment)

        doses = []
        dose_datetimes = []
        for inj in rows:
            inj_dt = safe_parse_dt(inj.get("date", "1900-01-01"), inj.get("time", "00:00"))
            if current <= inj_dt < week_end:
                dose_datetimes.append(inj_dt)
                doses.append({
                    "date": fmt_weekday_short(inj.get("date", "")),
                    "dose": fmt_dose(inj.get("dose")),
                    "site": inj.get("site", ""),
                })

        # Der alte Wert "Ende" war das Kalenderwochenende. Das wirkt unlogisch,
        # wenn die Spritze z. B. dienstags kommt. Deshalb zeigen wir in der
        # Wochenkarte jetzt den Tiefpunkt direkt vor der nächsten Spritze.
        trough_dt = None
        if dose_datetimes:
            last_dose_dt = max(dose_datetimes)
            trough_dt = next_injection_after(rows, last_dose_dt)
            if trough_dt is None and planned_next_dt and planned_next_dt > last_dose_dt:
                trough_dt = planned_next_dt

        if trough_dt:
            trough_moment = trough_dt - timedelta(seconds=1)
            trough_val = active_amount_at(data, trough_moment)
            trough_label = fmt_weekday_short(trough_moment.strftime("%Y-%m-%d"))
        else:
            trough_val = calendar_end_val
            trough_label = "Wochenende"

        iso = current.isocalendar()
        result.append({
            "label": f"KW {iso.week}",
            "range": f"{current.day:02d}.{current.month:02d}.–{(week_end - timedelta(days=1)).day:02d}.{(week_end - timedelta(days=1)).month:02d}.",
            "start": start_val,
            "end": trough_val,
            "calendar_end": calendar_end_val,
            "end_label": trough_label,
            "min": min(vals + [start_val, calendar_end_val, trough_val]),
            "max": max(vals + [start_val, calendar_end_val, trough_val]),
            "avg": sum(vals) / len(vals),
            "doses": doses,
            "is_current": current <= now < week_end,
        })
        current = week_end

    return list(reversed(result))


def fetch_ha_state(entity_id: str) -> Dict[str, Any]:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {"ok": False, "error": "SUPERVISOR_TOKEN nicht verfügbar"}
    try:
        url = f"http://supervisor/core/api/states/{entity_id}"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if r.status_code != 200:
            return {"ok": False, "error": f"Home Assistant Antwort {r.status_code}"}
        payload = r.json()
        state = payload.get("state")
        attrs = payload.get("attributes", {})
        return {"ok": True, "state": state, "attributes": attrs, "updated": payload.get("last_updated")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def current_weight_info(data: Dict[str, Any]) -> Dict[str, Any]:
    entity = data.get("settings", {}).get("weight_sensor") or DEFAULT_WEIGHT_SENSOR
    info = fetch_ha_state(entity)
    if info.get("ok"):
        value = parse_float(info.get("state"))
        return {
            "ok": True,
            "entity": entity,
            "value": value,
            "label": f"{fmt_number(value, 1)} kg" if value is not None else str(info.get("state")),
            "updated": info.get("updated"),
            "unit": info.get("attributes", {}).get("unit_of_measurement", "kg"),
        }
    return {"ok": False, "entity": entity, "error": info.get("error", "Unbekannter Fehler")}


def auto_store_weight_from_live(data: Dict[str, Any], live: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not parse_bool(data.get("settings", {}).get("auto_save_weight", True)):
        return {"saved": False, "reason": "deaktiviert"}
    if not live or not live.get("ok") or live.get("value") is None:
        return {"saved": False, "reason": "kein Sensorwert"}

    today = datetime.now().strftime("%Y-%m-%d")
    value = float(live["value"])
    sensor_updated = live.get("updated") or ""
    weights = data.setdefault("weights", [])
    auto_entry = next((w for w in weights if w.get("date") == today and w.get("source") == "withings_auto"), None)

    if auto_entry:
        old_value = parse_float(auto_entry.get("weight"))
        if old_value is not None and abs(old_value - value) < 0.05 and auto_entry.get("sensor_updated") == sensor_updated:
            return {"saved": False, "reason": "bereits aktuell"}
        auto_entry["weight"] = value
        auto_entry["sensor_updated"] = sensor_updated
        auto_entry["note"] = "Automatisch aus Withings aktualisiert"
        auto_entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        weights.sort(key=lambda x: x.get("date", ""))
        save_data(data)
        return {"saved": True, "reason": "aktualisiert"}

    weights.append({
        "id": str(uuid.uuid4()),
        "date": today,
        "weight": value,
        "note": "Automatisch aus Withings gespeichert",
        "source": "withings_auto",
        "sensor": live.get("entity"),
        "sensor_updated": sensor_updated,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    weights.sort(key=lambda x: x.get("date", ""))
    save_data(data)
    return {"saved": True, "reason": "neu gespeichert"}


def weight_stats(data: Dict[str, Any], live: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    weights = deepcopy(data.get("weights", []))
    weights.sort(key=lambda x: x.get("date", ""))
    start = parse_float(data.get("settings", {}).get("start_weight"))
    if start is None and weights:
        start = parse_float(weights[0].get("weight"))
    current = parse_float(weights[-1].get("weight")) if weights else None
    if live and live.get("ok") and live.get("value") is not None:
        current = live.get("value")
    target = parse_float(data.get("settings", {}).get("target_weight"))
    total_loss = None
    remaining = None
    if start is not None and current is not None:
        total_loss = start - current
    if target is not None and current is not None:
        remaining = current - target
    return {
        "start": start,
        "current": current,
        "target": target,
        "total_loss": total_loss,
        "remaining": remaining,
        "entries": weights,
    }


def latest_auto_weight(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = [w for w in data.get("weights", []) if w.get("source") == "withings_auto"]
    rows.sort(key=lambda x: (x.get("date", ""), x.get("created_at", x.get("updated_at", ""))), reverse=True)
    return rows[0] if rows else None


def group_by_month(injections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for inj in injections:
        dt = safe_parse_dt(inj.get("date", "1900-01-01"), inj.get("time", "00:00"))
        key = dt.strftime("%Y-%m")
        if key not in groups:
            groups[key] = {"key": key, "label": f"{MONTHS[dt.month-1]} {dt.year}", "items": []}
            order.append(key)
        groups[key]["items"].append(inj)
    return [groups[k] for k in order]


@app.context_processor
def template_helpers():
    return dict(
        version=APP_VERSION,
        fmt_date=fmt_date,
        fmt_short_date=fmt_short_date,
        fmt_weekday_short=fmt_weekday_short,
        fmt_dt=fmt_dt,
        fmt_dose=fmt_dose,
        fmt_number=fmt_number,
        active_page=request.endpoint or "dashboard",
    )


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "feature": "freie-dosis-und-live-uhrzeit"}


@app.route("/repair")
def repair():
    data = load_data()
    data, changed = ensure_data_integrity(data)
    save_data(data)
    return {"status": "ok", "changed": changed, "injections": len(data.get("injections", []))}


@app.route("/")
def dashboard():
    data = load_data()
    live_weight = current_weight_info(data)
    auto_store_weight_from_live(data, live_weight)
    data = load_data()
    wstats = weight_stats(data, live_weight)
    latest = latest_injection(data)
    next_item = next_injection(data)
    now = datetime.now()
    active = active_amount_at(data, now)
    next_active = None
    days_since = None
    if latest:
        last_dt = safe_parse_dt(latest["date"], latest.get("time", "00:00"))
        days_since = (now - last_dt).total_seconds() / 86400.0
    if next_item:
        next_active = active_amount_at(data, safe_parse_dt(next_item["date"], next_item["time"]))
    days_since_display = max(1, math.ceil(days_since)) if days_since is not None and days_since >= 0 else None
    chart = curve_points(data, "week", 140)
    recent = enrich_injections(data, reverse=True)[:5]
    return render_template(
        "dashboard.html",
        data=data,
        latest=latest,
        next_item=next_item,
        active_amount=active,
        next_active=next_active,
        days_since=days_since,
        days_since_display=days_since_display,
        chart=chart,
        recent=recent,
        live_weight=live_weight,
        wstats=wstats,
        latest_auto=latest_auto_weight(data),
        pk=pk_summary(data),
    )



def render_simple_injections_page(data: Dict[str, Any], error_message: str = ""):
    try:
        rows = enrich_injections(data, reverse=True)
    except Exception:
        rows = []
    cards = []
    for item in rows:
        iid = item.get("id", "")
        cards.append(f"""
        <div style='background:#fff;border:1px solid #dbe7f3;border-radius:18px;padding:14px;margin:10px 0;'>
          <div style='font-weight:800;color:#64748b;'>Spritze {item.get('number')} · {item.get('weekday_date')}</div>
          <div style='font-size:20px;font-weight:900;margin-top:4px;'>{data.get('settings', {}).get('medicine_name', 'Mounjaro®')} · {item.get('dose_label')}</div>
          <div style='color:#64748b;margin-top:3px;'>{item.get('site')} · {item.get('time')} Uhr</div>
          <form method='post' action='/injection/{iid}/delete' onsubmit="return confirm('Spritze wirklich löschen?')" style='margin-top:10px;'>
            <button style='border:0;border-radius:999px;background:#ffe8e8;color:#b42318;padding:10px 14px;font-weight:900;'>Löschen</button>
            <a href='/injection/{iid}/edit' style='display:inline-block;border-radius:999px;background:#edf2f8;color:#172033;padding:10px 14px;font-weight:900;text-decoration:none;margin-left:8px;'>Bearbeiten</a>
          </form>
        </div>
        """)
    error_html = f"<div style='background:#ffecec;color:#a31414;border-radius:16px;padding:12px;margin-bottom:12px;font-weight:800;'>Fehler in der normalen Ansicht: {error_message}</div>" if error_message else ""
    return f"""<!doctype html>
<html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Spritzen</title></head>
<body style='margin:0;background:#eef4fb;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:#111827;'>
<div style='max-width:900px;margin:0 auto;padding:18px;'>
  <div style='background:#071424;color:#fff;border-radius:0 0 28px 28px;padding:24px;margin:-18px -18px 18px;'>
    <h1 style='margin:0;'>Spritzen</h1>
    <p style='color:#d4e7f7;'>Spritzenverlauf</p>
    <a href='/' style='color:#fff;font-weight:900;'>← Übersicht</a>
    <a href='/injection/new' style='float:right;background:#fff;color:#2563eb;border-radius:999px;padding:10px 14px;text-decoration:none;font-weight:900;'>+ Spritze</a>
  </div>
  <details style='background:#fff;border:1px solid #dbe7f3;border-radius:16px;padding:12px;margin-bottom:12px;'>
    <summary style='font-weight:900;color:#64748b;'>Technische Details anzeigen</summary>
    {error_html}
  </details>
  {''.join(cards) if cards else "<p>Keine Spritzen erfasst.</p>"}
</div></body></html>"""


@app.route("/injections")
def injections():
    data = load_data()
    try:
        rows = enrich_injections(data, reverse=True)
        groups = group_by_month(rows)
        return render_template("injections.html", data=data, groups=groups, next_item=next_injection(data))
    except Exception as exc:
        data, _ = ensure_data_integrity(data)
        save_data(data)
        return render_simple_injections_page(data, str(exc)), 200


@app.route("/injection/new", methods=["GET", "POST"])
@app.route("/injection/<inj_id>/edit", methods=["GET", "POST"])
def injection_form(inj_id: Optional[str] = None):
    data = load_data()
    editing = inj_id is not None
    existing = None
    if editing:
        existing = next((x for x in data["injections"] if x.get("id") == inj_id), None)
        if not existing:
            flash("Spritze nicht gefunden.", "error")
            return redirect(url_for("injections"))
    if request.method == "POST":
        date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")
        time = request.form.get("time") or datetime.now().strftime("%H:%M")
        dose = parse_float(request.form.get("dose")) or 0
        site = normalize_site(request.form.get("site"), "Bauch links")
        note = request.form.get("note", "").strip()

        # Die zuletzt im Klick-Rechner tatsächlich verwendeten Werte werden
        # zusammen mit der Spritze gespeichert UND zur Vorgabe für den nächsten
        # Eintrag. So bleibt z. B. ein temporärer Wechsel 7,5 mg -> 5 mg erhalten.
        click_pen_mg = parse_float(request.form.get("click_pen_mg"))
        click_target_mg = parse_float(request.form.get("click_target_mg"))
        click_full = parse_float(request.form.get("click_full"))
        if click_pen_mg is None or click_pen_mg <= 0:
            click_pen_mg = parse_float(data["settings"].get("click_pen_mg")) or 7.5
        if click_target_mg is None or click_target_mg < 0:
            click_target_mg = dose
        if click_full is None or click_full <= 0:
            click_full = parse_float(data["settings"].get("click_full")) or 60
        click_count = (click_target_mg / click_pen_mg * click_full) if click_pen_mg else None

        data["settings"]["click_pen_mg"] = click_pen_mg
        data["settings"]["click_target_mg"] = click_target_mg
        data["settings"]["click_full"] = click_full

        item = {
            "date": date, "time": time, "dose": dose, "site": site, "note": note,
            "click_pen_mg": click_pen_mg, "click_target_mg": click_target_mg,
            "click_full": click_full, "click_count": click_count,
        }
        opts = data["settings"].setdefault("dose_options", [])
        clean_opts = []
        for o in opts:
            parsed = parse_float(o)
            if parsed is not None:
                clean_opts.append(parsed)
        if dose and all(abs(o - dose) > 0.001 for o in clean_opts):
            clean_opts.append(dose)
        data["settings"]["dose_options"] = sorted(set(round(o, 3) for o in clean_opts))
        if editing:
            existing.update(item)
            flash("Spritze gespeichert.", "ok")
        else:
            item["id"] = str(uuid.uuid4())
            data["injections"].append(item)
            flash("Spritze angelegt.", "ok")
        save_data(data)
        return redirect(url_for("injections"))

    if not existing:
        next_item = next_injection(data)
        last_item = latest_injection(data)
        now_for_form = datetime.now()
        existing = {
            # Neue Spritzen sollen beim Öffnen/Speichern die aktuelle Uhrzeit bekommen.
            # Der Browser überschreibt Datum/Uhrzeit zusätzlich mit der lokalen Gerätezeit
            # des iPhones, damit nicht immer die Zeit der automatischen Planung übernommen wird.
            "date": now_for_form.strftime("%Y-%m-%d"),
            "time": now_for_form.strftime("%H:%M"),
            "dose": data.get("settings", {}).get("click_target_mg") or (next_item["dose"] if next_item else 2.5),
            "site": next_item["site"] if next_item else (opposite_site(last_item.get("site")) if last_item else "Bauch links"),
            "note": "",
        }
    try:
        return render_template("injection_form.html", data=data, item=existing, editing=editing)
    except Exception as exc:
        site_left = "selected" if existing.get("site") == "Bauch links" else ""
        site_right = "selected" if existing.get("site") == "Bauch rechts" else ""
        return f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Spritze</title></head><body style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;background:#eef4fb;padding:18px;'><h1>Spritze erfassen</h1><p style='background:#ffecec;color:#a31414;padding:12px;border-radius:12px;'>Template-Fehler: {exc}</p><form method='post' style='display:grid;gap:12px;max-width:520px;'><label>Datum <input type='date' name='date' value='{existing.get("date","")}' required></label><label>Uhrzeit <input type='time' name='time' value='{existing.get("time","20:00")}' required></label><label>Dosis <input type='number' step='0.01' name='dose' value='{existing.get("dose","2.5")}' required></label><label>Spritzstelle <select name='site'><option value='Bauch links' {site_left}>Bauch links</option><option value='Bauch rechts' {site_right}>Bauch rechts</option></select></label><label>Notiz <textarea name='note'>{existing.get("note","")}</textarea></label><button style='border:0;border-radius:999px;background:#2563eb;color:#fff;padding:12px;font-weight:900;'>Speichern</button></form><p><a href='/injections'>Zurück</a></p></body></html>"""


@app.route("/injection/<inj_id>/delete", methods=["POST"])
def delete_injection(inj_id: str):
    data = load_data()
    before = len(data.get("injections", []))
    data["injections"] = [x for x in data.get("injections", []) if str(x.get("id") or "") != str(inj_id)]
    save_data(data)
    if len(data["injections"]) < before:
        flash("Spritze gelöscht.", "ok")
    else:
        flash("Spritze nicht gefunden. Die Einträge wurden repariert, bitte Seite neu laden.", "error")
    return redirect(url_for("injections"))


@app.route("/weight", methods=["GET", "POST"])
def weight():
    data = load_data()
    live_weight = current_weight_info(data)
    auto_status = auto_store_weight_from_live(data, live_weight)
    data = load_data()
    if request.method == "POST":
        date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")
        weight_value = parse_float(request.form.get("weight"))
        note = request.form.get("note", "").strip()
        if weight_value is None:
            flash("Bitte ein Gewicht eintragen.", "error")
        else:
            data["weights"].append({"id": str(uuid.uuid4()), "date": date, "weight": weight_value, "note": note, "source": "manuell"})
            data["weights"].sort(key=lambda x: x.get("date", ""))
            save_data(data)
            flash("Gewicht gespeichert.", "ok")
        return redirect(url_for("weight"))
    wstats = weight_stats(data, live_weight)
    chart = weight_chart(wstats["entries"], live_weight)
    today_value = live_weight.get("value") if live_weight.get("ok") else None
    return render_template(
        "weight.html",
        data=data,
        live_weight=live_weight,
        wstats=wstats,
        chart=chart,
        today_value=today_value,
        today=datetime.now().strftime("%Y-%m-%d"),
        auto_status=auto_status,
        latest_auto=latest_auto_weight(data),
    )


@app.route("/weight/<wid>/delete", methods=["POST"])
def delete_weight(wid: str):
    data = load_data()
    data["weights"] = [x for x in data.get("weights", []) if x.get("id") != wid]
    save_data(data)
    flash("Gewicht gelöscht.", "ok")
    return redirect(url_for("weight"))


def weight_chart(entries: List[Dict[str, Any]], live: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    points = []
    for row in entries:
        val = parse_float(row.get("weight"))
        if val is not None:
            points.append((datetime.strptime(row.get("date"), "%Y-%m-%d"), val, row.get("source", "gespeichert")))
    if live and live.get("ok") and live.get("value") is not None:
        points.append((datetime.now(), float(live["value"]), "Withings live"))
    if len(points) < 1:
        return None
    points.sort(key=lambda x: x[0])
    start = points[0][0]
    end = points[-1][0]
    if start == end:
        end = start + timedelta(days=1)
    min_v = min(p[1] for p in points)
    max_v = max(p[1] for p in points)
    if abs(max_v - min_v) < 0.1:
        max_v += 1
        min_v -= 1
    width, height = 1000, 320
    pad_x, pad_top, pad_bottom = 42, 30, 54
    usable_w = width - 2 * pad_x
    usable_h = height - pad_top - pad_bottom
    total_seconds = (end - start).total_seconds()
    coords = []
    for t, val, source in points:
        x = pad_x + ((t - start).total_seconds() / total_seconds) * usable_w
        y = pad_top + (1 - ((val - min_v) / (max_v - min_v))) * usable_h
        coords.append({"x": x, "y": y, "label": f"{fmt_number(val, 1)} kg", "source": source})
    poly = " ".join([f"{p['x']:.1f},{p['y']:.1f}" for p in coords])
    return {"polyline": poly, "points": coords, "min": min_v, "max": max_v, "width": width, "height": height}


@app.route("/body")
def body():
    data = load_data()
    range_mode = request.args.get("range", "week")
    if range_mode not in {"week", "month", "90", "all"}:
        range_mode = "week"
    sample_map = {"week": 140, "month": 180, "90": 240, "all": 300}
    chart = curve_points(data, range_mode, sample_map.get(range_mode, 160))
    now = datetime.now()
    active_now = active_amount_at(data, now)
    next_item = next_injection(data)
    active_next = active_amount_at(data, safe_parse_dt(next_item["date"], next_item["time"])) if next_item else None
    weeks = weekly_body_summary(data, 10, 1)
    ranges = [
        {"key": "week", "label": "Woche"},
        {"key": "month", "label": "Monat"},
        {"key": "90", "label": "90 Tage"},
        {"key": "all", "label": "Insgesamt"},
    ]
    return render_template("body.html", data=data, chart=chart, active_now=active_now, next_item=next_item, active_next=active_next, weeks=weeks, range_mode=range_mode, ranges=ranges, pk=pk_summary(data))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    data = load_data()
    if request.method == "POST":
        s = data["settings"]
        s["medicine_name"] = request.form.get("medicine_name", "Mounjaro®").strip() or "Mounjaro®"
        s["weight_sensor"] = request.form.get("weight_sensor", DEFAULT_WEIGHT_SENSOR).strip() or DEFAULT_WEIGHT_SENSOR
        s["half_life_days"] = parse_float(request.form.get("half_life_days")) or 5.4
        s["absorption_tmax_hours"] = parse_float(request.form.get("absorption_tmax_hours")) or 24
        s["bioavailability_factor"] = parse_float(request.form.get("bioavailability_factor")) or 1.0
        s["click_pen_mg"] = parse_float(request.form.get("click_pen_mg")) or 7.5
        s["click_target_mg"] = parse_float(request.form.get("click_target_mg")) or 2.5
        s["click_full"] = parse_float(request.form.get("click_full")) or 60
        s["weekly_interval_days"] = int(parse_float(request.form.get("weekly_interval_days")) or 7)
        s["start_weight"] = request.form.get("start_weight", "").strip()
        s["target_weight"] = request.form.get("target_weight", "").strip()
        s["auto_save_weight"] = request.form.get("auto_save_weight") == "on"
        raw_doses = request.form.get("dose_options", "")
        doses = []
        for part in raw_doses.replace(";", "\n").replace(",", ".").splitlines():
            value = parse_float(part)
            if value is not None and value > 0 and all(abs(value - d) > 0.001 for d in doses):
                doses.append(value)
        if doses:
            s["dose_options"] = sorted(doses)
        save_data(data)
        flash("Einstellungen gespeichert.", "ok")
        return redirect(url_for("settings"))
    dose_text = "\n".join(str(x).replace(".", ",") for x in data.get("settings", {}).get("dose_options", []))
    return render_template("settings.html", data=data, dose_text=dose_text)


@app.route("/symptoms", methods=["GET", "POST"])
def symptoms():
    data = load_data()
    if request.method == "POST":
        row = {
            "id": str(uuid.uuid4()),
            "date": request.form.get("date") or datetime.now().strftime("%Y-%m-%d"),
            "appetite": int(parse_float(request.form.get("appetite")) or 0),
            "nausea": int(parse_float(request.form.get("nausea")) or 0),
            "heartburn": int(parse_float(request.form.get("heartburn")) or 0),
            "digestion": int(parse_float(request.form.get("digestion")) or 0),
            "energy": int(parse_float(request.form.get("energy")) or 0),
            "note": request.form.get("note", "").strip(),
        }
        data["symptoms"].append(row)
        data["symptoms"].sort(key=lambda x: x.get("date", ""), reverse=True)
        save_data(data)
        flash("Eintrag gespeichert.", "ok")
        return redirect(url_for("symptoms"))
    rows = sorted(data.get("symptoms", []), key=lambda x: x.get("date", ""), reverse=True)
    return render_template("symptoms.html", data=data, rows=rows)


@app.route("/symptoms/<sid>/delete", methods=["POST"])
def delete_symptom(sid: str):
    data = load_data()
    data["symptoms"] = [x for x in data.get("symptoms", []) if x.get("id") != sid]
    save_data(data)
    flash("Eintrag gelöscht.", "ok")
    return redirect(url_for("symptoms"))


def auto_weight_worker() -> None:
    time_module.sleep(5)
    interval = max(1.0, AUTO_WEIGHT_INTERVAL_HOURS) * 3600
    while True:
        try:
            data = load_data()
            live = current_weight_info(data)
            auto_store_weight_from_live(data, live)
        except Exception as exc:
            print(f"[Mounjaro Tracker] Auto-Gewicht konnte nicht gespeichert werden: {exc}", flush=True)
        time_module.sleep(interval)


if __name__ == "__main__":
    threading.Thread(target=auto_weight_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
