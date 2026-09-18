from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for

PORT = int(os.environ.get("PORT", "8134"))
DATA_DIR = Path(os.environ.get("STUNDEN_DATA_DIR", "/data"))
IMPORT_DIR = Path(os.environ.get("STUNDEN_IMPORT_DIR", "/share/Stunden"))
PROCESSED_DIR = IMPORT_DIR / "processed"
DB_PATH = DATA_DIR / "stundenplanung.db"
SCAN_INTERVAL_SECONDS = int(os.environ.get("STUNDEN_SCAN_INTERVAL", "30"))
AI_PROVIDER = str(os.environ.get("STUNDEN_AI_PROVIDER") or "gemini").strip().lower()
GEMINI_API_KEY = str(os.environ.get("STUNDEN_GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = str(os.environ.get("STUNDEN_GEMINI_MODEL") or "gemini-2.5-flash").strip()
OLLAMA_URL = str(os.environ.get("STUNDEN_OLLAMA_URL") or "http://192.168.10.199:11434").strip().rstrip("/")
OLLAMA_MODEL = str(os.environ.get("STUNDEN_OLLAMA_MODEL") or "gemma3:4b").strip()
PARSER_MODE = str(os.environ.get("STUNDEN_PARSER_MODE") or "ai").strip().lower()
AI_TIMEOUT_SECONDS = int(os.environ.get("STUNDEN_AI_TIMEOUT", "180"))
DEBUG_DIR = IMPORT_DIR / "debug"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("STUNDEN_SESSION_SECRET") or os.environ.get("STUNDEN_WEB_PASSWORD") or "stundenplanung-secret"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DEFAULT_TARGET_MINUTES = 7 * 60 + 58
WEDNESDAY_TARGET_MINUTES = 7 * 60 + 56
PROCESSING_LOCK = threading.RLock()
AI_REQUEST_LOCK = threading.Lock()
GEMINI_STATE_LOCK = threading.Lock()
GEMINI_COOLDOWN_UNTIL = 0.0



def configured_web_password() -> str:
    value = str(os.environ.get("STUNDEN_WEB_PASSWORD") or "").strip()
    if value.lower() in {"null", "none"}:
        return ""
    return value


def configured_parser_mode() -> str:
    value = str(PARSER_MODE or "ai").strip().lower()
    if value not in {"ai", "ai_then_ocr", "ocr"}:
        return "ai"
    return value


def configured_ai_provider() -> str:
    value = str(AI_PROVIDER or "gemini").strip().lower()
    if value not in {"gemini", "ollama"}:
        return "gemini"
    return value


def configured_gemini_api_key() -> str:
    return str(GEMINI_API_KEY or "").strip()


def configured_gemini_model() -> str:
    return str(GEMINI_MODEL or "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def configured_ollama_url() -> str:
    return str(OLLAMA_URL or "http://192.168.10.199:11434").strip().rstrip("/")


def configured_ollama_model() -> str:
    return str(OLLAMA_MODEL or "gemma3:4b").strip() or "gemma3:4b"


WEB_PASSWORD = configured_web_password()
TELEGRAM_FOLLOWUP_PROMPT = "Vielen Dank für das Bild. Hast du heute Zeit nachlaufen lassen? Schicke mir die exakten Minuten oder den Zeitblock. (z.B. 30 Minuten oder 17:32-18:05)"
TELEGRAM_INVALID_REPLY_PROMPT = "Ich konnte das noch nicht lesen. Bitte schicke nur die Minuten oder einen Zeitblock, z.B. 30 Minuten oder 17:32-18:05."
DEFAULT_PUSH_NOTIFY_SERVICE = "all_mobile_app_devices"
FALLBACK_PUSH_NOTIFY_SERVICE = "mobile_app_iphone_Hauptprofil"
DEFAULT_PUSH_NOTIFY_TITLE = "Stundenplanung"


def configured_api_token() -> str:
    value = str(os.environ.get("STUNDEN_API_TOKEN") or "").strip()
    if value.lower() in {"null", "none"}:
        return ""
    return value


def api_access_token() -> str:
    return configured_api_token() or WEB_PASSWORD


def configured_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "ja"}:
        return True
    if raw in {"0", "false", "no", "off", "nein"}:
        return False
    return default


def configured_push_notify_enabled() -> bool:
    return configured_bool("STUNDEN_PUSH_NOTIFY_ENABLED", True)


def configured_push_notify_service() -> str:
    value = str(os.environ.get("STUNDEN_PUSH_NOTIFY_SERVICE") or DEFAULT_PUSH_NOTIFY_SERVICE).strip()
    if value.lower() in {"null", "none", "false", "off"}:
        return ""
    return value


def configured_push_notify_title() -> str:
    return str(os.environ.get("STUNDEN_PUSH_NOTIFY_TITLE") or DEFAULT_PUSH_NOTIFY_TITLE).strip() or DEFAULT_PUSH_NOTIFY_TITLE


def auth_enabled() -> bool:
    return bool(WEB_PASSWORD)


def is_authenticated() -> bool:
    return bool(session.get("stunden_authenticated"))


@app.context_processor
def inject_auth_state() -> dict[str, Any]:
    return {
        "auth_enabled": auth_enabled(),
        "is_authenticated": is_authenticated(),
        "today_iso": date.today().isoformat(),
        "parser_mode": configured_parser_mode(),
        "ai_provider": configured_ai_provider(),
        "ai_model": configured_ollama_model() if configured_ai_provider() == "ollama" else configured_gemini_model(),
        "gemini_cooldown_seconds": get_gemini_cooldown_remaining() if configured_ai_provider() == "gemini" else 0,
    }


@app.before_request
def require_login() -> Any:
    if not auth_enabled() or is_authenticated() or request.endpoint in {"login", "static", "telegram_import_prompt_api", "telegram_reply_api"}:
        return None
    target = request.full_path if request.query_string else request.path
    if target.endswith("?"):
        target = target[:-1]
    return redirect(url_for("login", next=target))


@app.template_filter("minutes_hm")
def minutes_hm(value: int | None) -> str:
    total = int(value or 0)
    sign = "+" if total >= 0 else "-"
    total_abs = abs(total)
    hours, minutes = divmod(total_abs, 60)
    return f"{sign}{hours}:{minutes:02d}"


@app.template_filter("minutes_plain")
def minutes_plain(value: int | None) -> str:
    total = int(value or 0)
    sign = "-" if total < 0 else ""
    total_abs = abs(total)
    hours, minutes = divmod(total_abs, 60)
    if hours:
        return f"{sign}{hours}:{minutes:02d}"
    return f"{sign}{minutes} Min"


@app.template_filter("dt")
def dt_filter(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return text


@app.template_filter("date_de")
def date_de_filter(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).strftime("%d.%m.%Y")
    except ValueError:
        return text


@app.template_filter("status_badge")
def status_badge(value: Any) -> str:
    status = str(value or "").strip()
    labels = {
        "parsed": ("Automatisch verarbeitet", "ok"),
        "updated_existing": ("Vorhandenen Tag aktualisiert", "ok"),
        "needs_check": ("Bitte prüfen", "warn"),
        "retry_waiting": ("Wartet auf Neuversuch", "info"),
        "duplicate": ("Duplikat", "info"),
        "error": ("Fehler", "danger"),
        "deleted": ("Gelöscht", "danger"),
    }
    label, css = labels.get(status, (status or "offen", "info"))
    return f'<span class="badge {css}">{label}</span>'


@app.template_filter("weekday_name")
def weekday_name_filter(value: Any) -> str:
    try:
        d = datetime.strptime(str(value), "%Y-%m-%d").date()
        return WEEKDAY_NAMES[d.weekday()]
    except Exception:
        return ""


@app.template_filter("weekday_short")
def weekday_short_filter(value: Any) -> str:
    try:
        d = datetime.strptime(str(value), "%Y-%m-%d").date()
        return WEEKDAY_SHORT[d.weekday()]
    except Exception:
        return ""


@app.template_filter("nl2br")
def nl2br(value: Any) -> str:
    return str(value or "").replace("\n", "<br>")


def safe_next_target(raw: Any) -> str:
    target = str(raw or "").strip()
    if not target.startswith("/") or target.startswith("//"):
        return url_for("dashboard")
    return target


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def init_db() -> None:
    with closing(get_db()) as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                stored_name TEXT,
                source_path TEXT,
                processed_path TEXT,
                file_hash TEXT,
                status TEXT NOT NULL DEFAULT 'needs_check',
                notes TEXT,
                parser_summary TEXT,
                imported_at TEXT NOT NULL,
                processed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_imports_hash_processed ON imports(file_hash, processed_path);

            CREATE TABLE IF NOT EXISTS work_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL UNIQUE,
                weekday TEXT NOT NULL,
                come_time TEXT,
                go_time TEXT,
                system_plusminus_min INTEGER NOT NULL DEFAULT 0,
                deducted_break_min INTEGER NOT NULL DEFAULT 0,
                manual_correction_min INTEGER NOT NULL DEFAULT 0,
                carryover_budget_min INTEGER NOT NULL DEFAULT 0,
                imported_rest_component_min INTEGER NOT NULL DEFAULT 0,
                effective_day_value_min INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                import_id INTEGER,
                status TEXT NOT NULL DEFAULT 'confirmed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(import_id) REFERENCES imports(id)
            );

            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_date TEXT NOT NULL UNIQUE,
                planned_start TEXT,
                planned_end TEXT,
                planned_break_min INTEGER NOT NULL DEFAULT 0,
                expected_result_min INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS account_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_date TEXT NOT NULL,
                minutes INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS telegram_followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_key TEXT NOT NULL UNIQUE,
                chat_id TEXT NOT NULL,
                user_id TEXT,
                import_id INTEGER,
                work_date TEXT,
                prompt_text TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                context_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(import_id) REFERENCES imports(id)
            );
            """
        )
        if not column_exists(conn, "imports", "parser_summary"):
            conn.execute("ALTER TABLE imports ADD COLUMN parser_summary TEXT")
        if not column_exists(conn, "work_entries", "carryover_budget_min"):
            conn.execute("ALTER TABLE work_entries ADD COLUMN carryover_budget_min INTEGER NOT NULL DEFAULT 0")
        if not column_exists(conn, "work_entries", "imported_rest_component_min"):
            conn.execute("ALTER TABLE work_entries ADD COLUMN imported_rest_component_min INTEGER NOT NULL DEFAULT 0")
        if not column_exists(conn, "work_entries", "work_segments_text"):
            conn.execute("ALTER TABLE work_entries ADD COLUMN work_segments_text TEXT")
        if not column_exists(conn, "work_entries", "work_segments_json"):
            conn.execute("ALTER TABLE work_entries ADD COLUMN work_segments_json TEXT")
        if not column_exists(conn, "plans", "plan_segments_text"):
            conn.execute("ALTER TABLE plans ADD COLUMN plan_segments_text TEXT")
        if not column_exists(conn, "plans", "plan_segments_json"):
            conn.execute("ALTER TABLE plans ADD COLUMN plan_segments_json TEXT")
        if not column_exists(conn, "account_transactions", "kind"):
            conn.execute("ALTER TABLE account_transactions ADD COLUMN kind TEXT NOT NULL DEFAULT 'balance'")
        conn.execute(
            "UPDATE work_entries SET imported_rest_component_min = CASE WHEN deducted_break_min BETWEEN 0 AND 180 THEN deducted_break_min ELSE 0 END WHERE COALESCE(imported_rest_component_min, 0) = 0"
        )
        conn.execute(
            "UPDATE work_entries SET work_segments_text = TRIM(COALESCE(come_time, '')) || CASE WHEN COALESCE(come_time, '') != '' AND COALESCE(go_time, '') != '' THEN ' – ' ELSE '' END || TRIM(COALESCE(go_time, '')) WHERE COALESCE(work_segments_text, '') = '' AND (COALESCE(come_time, '') != '' OR COALESCE(go_time, '') != '')"
        )
        rows = conn.execute(
            """
            SELECT w.id, w.come_time, w.go_time, w.work_segments_text, w.work_segments_json, i.parser_summary
            FROM work_entries w
            LEFT JOIN imports i ON i.id = w.import_id
            """
        ).fetchall()
        for row in rows:
            parser_segments = segments_list_from_parser_summary(str(row["parser_summary"] or ""))
            stored_segments = load_segments_json(row["work_segments_json"])
            text_segments = segments_list_from_text(str(row["work_segments_text"] or ""))
            default_segments = segments_list_from_text(default_segments_text(row["come_time"], row["go_time"]))
            chosen_segments = parser_segments or stored_segments or text_segments or default_segments
            if chosen_segments:
                new_json = serialize_segments_json(chosen_segments)
                new_text = build_segments_text(chosen_segments)
                if new_json != (row["work_segments_json"] or "") or new_text != (row["work_segments_text"] or ""):
                    conn.execute(
                        "UPDATE work_entries SET work_segments_json = ?, work_segments_text = ? WHERE id = ?",
                        (new_json, new_text, int(row["id"]))
                    )
        plan_rows = conn.execute(
            "SELECT id, planned_start, planned_end, plan_segments_text, plan_segments_json FROM plans WHERE COALESCE(plan_segments_json, '') = ''"
        ).fetchall()
        for row in plan_rows:
            text_segments = segments_list_from_text(str(row["plan_segments_text"] or ""))
            default_segments = segments_list_from_text(default_segments_text(row["planned_start"], row["planned_end"]))
            chosen_segments = text_segments or default_segments
            if chosen_segments:
                conn.execute(
                    "UPDATE plans SET plan_segments_json = ?, plan_segments_text = ? WHERE id = ?",
                    (serialize_segments_json(chosen_segments), build_segments_text(chosen_segments), int(row["id"]))
                )
        migrate_legacy_telegram_catchups(conn)
        conn.commit()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with closing(get_db()) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with closing(get_db()) as conn:
        row = conn.execute(sql, params).fetchone()
        return row_to_dict(row)


def infer_weekday(work_date: str) -> str:
    try:
        d = datetime.strptime(work_date, "%Y-%m-%d").date()
        return WEEKDAY_NAMES[d.weekday()]
    except ValueError:
        return ""


def target_minutes_for_work_date(work_date: str | None) -> int:
    text = str(work_date or "").strip()
    if not text:
        return DEFAULT_TARGET_MINUTES
    try:
        d = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return DEFAULT_TARGET_MINUTES
    return WEDNESDAY_TARGET_MINUTES if d.weekday() == 2 else DEFAULT_TARGET_MINUTES


def target_label_for_work_date(work_date: str | None) -> str:
    minutes = target_minutes_for_work_date(work_date)
    hours, mins = divmod(minutes, 60)
    return f"{hours}:{mins:02d}"


def booked_target_times_for_work_date(work_date: str | None) -> tuple[str, str, list[dict[str, str]]]:
    start_minutes = 8 * 60
    target_minutes = target_minutes_for_work_date(work_date)
    end_minutes = start_minutes + target_minutes
    start = f"{start_minutes // 60:02d}:{start_minutes % 60:02d}"
    end = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
    return start, end, [{"start": start, "end": end}]


def build_parser_summary(
    work_date: str | None,
    come_time: str | None,
    go_time: str | None,
    system_plusminus_min: int | None,
    system_plusminus_found: bool,
    deducted_break_min: int | None,
    deducted_break_found: bool,
    extra_lines: list[str] | None = None,
    work_duration_min: int | None = None,
    work_duration_found: bool = False,
    target_minutes: int | None = None,
) -> str:
    lines = [f"Datum erkannt: {str(work_date or '—').strip() or '—'}"]
    lines.append(f"Kommen/Gehen aus fester Spalte: {str(come_time or '—').strip() or '—'} / {str(go_time or '—').strip() or '—'}")
    if work_duration_found:
        lines.append(f"Gesamtarbeitszeit (berechnet aus Arbeitsblöcken): {minutes_plain(int(work_duration_min or 0))}")
    else:
        lines.append("Gesamtarbeitszeit (berechnet aus Arbeitsblöcken): —")
    if target_minutes is not None:
        lines.append(f"Sollarbeitszeit laut Wochentag: {minutes_plain(int(target_minutes or 0))}")
    if system_plusminus_found:
        lines.append(f"Tagesplus/-minus (berechnet): {minutes_hm(int(system_plusminus_min or 0))}")
    else:
        lines.append("Tagesplus/-minus (berechnet): —")
    if deducted_break_found:
        lines.append(f"Restpausenabzug / Zuschlag: {minutes_hm(int(deducted_break_min or 0))}")
    else:
        lines.append("Restpausenabzug / Zuschlag: —")
    effective_min = compute_effective(int(system_plusminus_min or 0), int(deducted_break_min or 0), 0)
    if system_plusminus_found or deducted_break_found:
        lines.append(f"Effektiver Tageswert: {minutes_hm(effective_min)}")
    else:
        lines.append("Effektiver Tageswert: —")
    extras = [str(line).strip() for line in (extra_lines or []) if str(line).strip()]
    if extras:
        lines.append("")
        lines.extend(extras)
    return "\n".join(lines)




def build_parser_summary_for_saved_entry(conn: sqlite3.Connection, import_id: int, parsed: dict[str, Any]) -> str:
    work_date = str(parsed.get("work_date") or "").strip()
    entry_row = conn.execute("SELECT work_date FROM work_entries WHERE import_id = ? LIMIT 1", (import_id,)).fetchone()
    if entry_row is None and work_date:
        entry_row = conn.execute("SELECT work_date FROM work_entries WHERE work_date = ? LIMIT 1", (work_date,)).fetchone()
    entry = dict(entry_row) if entry_row is not None else {}
    effective_work_date = entry.get("work_date") or work_date
    return build_parser_summary(
        work_date=effective_work_date,
        come_time=parsed.get("come_time"),
        go_time=parsed.get("go_time"),
        system_plusminus_min=int(parsed.get("system_plusminus_min") or 0),
        system_plusminus_found=bool(parsed.get("system_plusminus_found")),
        deducted_break_min=int(parsed.get("deducted_break_min") or 0),
        deducted_break_found=bool(parsed.get("deducted_break_found")),
        extra_lines=list(parsed.get("parser_debug_lines") or []),
        work_duration_min=int(parsed.get("work_duration_min") or 0),
        work_duration_found=bool(parsed.get("work_duration_found")),
        target_minutes=target_minutes_for_work_date(effective_work_date),
    )

def parse_minutes(raw: Any, default: int = 0) -> int:
    text = str(raw or "").strip()
    if not text:
        return default
    text = text.replace("−", "-").replace("–", "-").replace("—", "-").replace("O", "0").replace("o", "0")
    sign = -1 if text.startswith("-") else 1
    if text.startswith(("+", "-")):
        text = text[1:].strip()
    text = re.sub(r"\s*min(?:uten)?\b", "", text, flags=re.IGNORECASE).strip()
    if ":" in text:
        try:
            hours, minutes = text.split(":", 1)
            return sign * (int(hours or "0") * 60 + int(minutes or "0"))
        except ValueError:
            return default
    try:
        return sign * int(text)
    except ValueError:
        return default


def parse_time_to_minutes(raw: Any) -> int | None:
    text = str(raw or '').strip()
    if not text:
        return None
    if ':' not in text:
        return None
    try:
        hours_s, minutes_s = text.split(':', 1)
        hours = int(hours_s)
        minutes = int(minutes_s)
    except ValueError:
        return None
    if hours < 0 or minutes < 0 or minutes >= 60:
        return None
    return hours * 60 + minutes


def compute_effective(system_plusminus_min: int, deducted_break_min: int, manual_correction_min: int) -> int:
    return int(system_plusminus_min) + int(deducted_break_min) - int(manual_correction_min)


def compute_carryover_budget(imported_rest_component_min: int, manual_correction_min: int, manual_budget_base: int = 0) -> int:
    return int(manual_budget_base) + int(imported_rest_component_min) - abs(int(manual_correction_min or 0))


def ensure_debug_dir() -> Path:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return DEBUG_DIR


def debug_file_base(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("_") or "import"
    return stem


def write_debug_text(path: Path, content: str) -> None:
    ensure_debug_dir()
    path.write_text(str(content or ""), encoding="utf-8")


def normalize_clock_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace(".", ":")
    match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if not match:
        digits = re.sub(r"\D", "", text)
        if len(digits) == 4:
            hours, minutes = digits[:2], digits[2:]
        elif len(digits) == 3:
            hours, minutes = digits[:1], digits[1:]
        else:
            return ""
    else:
        hours, minutes = match.groups()
    try:
        hours_i = int(hours)
        minutes_i = int(minutes)
    except ValueError:
        return ""
    if not (0 <= hours_i <= 23 and 0 <= minutes_i <= 59):
        return ""
    return f"{hours_i:02d}:{minutes_i:02d}"


def normalize_ai_date(value: Any, fallback_year: int | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    iso_match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))).isoformat()
        except ValueError:
            return ""
    normalized = text.replace("/", ".").replace("-", ".")
    match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", normalized)
    if match:
        day, month, year = match.groups()
        try:
            year_i = int(year) if year else int(fallback_year or date.today().year)
            if year_i < 100:
                year_i += 2000
            return date(year_i, int(month), int(day)).isoformat()
        except ValueError:
            return ""
    try:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    except Exception:
        return ""


def normalize_ai_duration_minutes(value: Any, *, signed: bool) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if signed:
            return int(round(numeric)) if abs(numeric) > 24 else int(round(numeric * 60))
        return max(0, int(round(numeric)) if numeric > 24 else int(round(numeric * 60)))
    text = str(value or "").strip()
    if not text:
        return 0
    parsed = parse_work_duration_minutes(text)
    if parsed is not None:
        return int(parsed) if signed else max(0, int(parsed))
    parsed_simple = parse_minutes(text, default=0)
    return int(parsed_simple) if signed else max(0, int(parsed_simple))


def normalize_ai_segments(value: Any) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    if not isinstance(value, list):
        return segments
    for item in value:
        if not isinstance(item, dict):
            continue
        start = normalize_clock_time(item.get("start") or item.get("von") or item.get("kommt") or item.get("begin"))
        end = normalize_clock_time(item.get("end") or item.get("bis") or item.get("geht") or item.get("finish"))
        if start and end:
            segments.append({"start": start, "end": end})
    return segments


def segments_list_from_text(text: str | None) -> list[dict[str, str]]:
    raw = str(text or '').strip()
    if not raw:
        return []
    normalized = raw.replace(' und ', ', ').replace('–', '-').replace('—', '-')
    parts: list[dict[str, str]] = []
    for chunk in normalized.split(','):
        item = chunk.strip()
        if not item or '-' not in item:
            continue
        start, end = item.split('-', 1)
        start_n = normalize_clock_time(start)
        end_n = normalize_clock_time(end)
        if start_n and end_n:
            parts.append({"start": start_n, "end": end_n})
    return parts


def segments_list_from_parser_summary(summary: str | None) -> list[dict[str, str]]:
    text = str(summary or '').strip()
    if not text:
        return []
    match = re.search(r"Arbeitsblöcke:\s*(.+)", text)
    if not match:
        return []
    return segments_list_from_text(match.group(1).strip())


def serialize_segments_json(segments: list[dict[str, str]]) -> str:
    cleaned = normalize_ai_segments(segments)
    return json.dumps(cleaned, ensure_ascii=False)


def load_segments_json(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    try:
        data = json.loads(str(value))
    except Exception:
        return []
    return normalize_ai_segments(data)


def load_json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    raw = str(value).strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def preferred_segments(entry: dict[str, Any] | None, parser_summary: str | None = None) -> list[dict[str, str]]:
    if not entry:
        return []
    stored = load_segments_json(entry.get('work_segments_json'))
    if stored:
        return stored
    parser_segments = segments_list_from_parser_summary(parser_summary)
    if parser_segments:
        return parser_segments
    text_segments = segments_list_from_text(entry.get('work_segments_text'))
    if text_segments:
        return text_segments
    return segments_list_from_text(default_segments_text(entry.get('come_time'), entry.get('go_time')))


def apply_last_segment_override_for_rest_break(segments: list[dict[str, str]], override_time: str) -> tuple[list[dict[str, str]], bool]:
    if not segments:
        return segments, False
    normalized_override = normalize_clock_time(override_time)
    if not normalized_override:
        return segments, False
    last_segment = dict(segments[-1])
    current_start = normalize_clock_time(last_segment.get("start"))
    current_end = normalize_clock_time(last_segment.get("end"))
    if not current_start or not current_end:
        return segments, False
    if normalized_override == current_end:
        return segments, False
    if segment_minutes(current_start, normalized_override) <= 0:
        return segments, False
    if segment_minutes(normalized_override, current_end) <= 0:
        return segments, False
    updated_segments = [dict(item) for item in segments]
    updated_segments[-1]["end"] = normalized_override
    return updated_segments, True


def segment_minutes(start: str, end: str) -> int:
    try:
        start_dt = datetime.strptime(start, "%H:%M")
        end_dt = datetime.strptime(end, "%H:%M")
    except ValueError:
        return 0
    delta = int((end_dt - start_dt).total_seconds() // 60)
    return delta if delta >= 0 else 0


def compute_work_duration_from_segments(segments: list[dict[str, str]]) -> int:
    return sum(segment_minutes(str(item.get("start") or ""), str(item.get("end") or "")) for item in segments)


def build_segments_text(segments: list[dict[str, str]]) -> str:
    cleaned: list[str] = []
    for item in segments or []:
        start = normalize_clock_time(item.get("start"))
        end = normalize_clock_time(item.get("end"))
        if not start or not end:
            continue
        cleaned.append(f"{start}–{end}")
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} und {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f" und {cleaned[-1]}"


def extract_segments_from_form(data: dict[str, Any], prefix: str = "segment") -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    for idx in range(1, 5):
        start = normalize_clock_time(data.get(f"{prefix}{idx}_start"))
        end = normalize_clock_time(data.get(f"{prefix}{idx}_end"))
        if not start and not end:
            continue
        if start and end:
            if segment_minutes(start, end) > 0:
                segments.append({"start": start, "end": end})
            continue
    return segments


def api_request_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if request.is_json:
        json_payload = request.get_json(silent=True)
        if isinstance(json_payload, dict):
            payload.update(json_payload)
    payload.update({key: value for key, value in request.form.items()})
    for key in request.args.keys():
        payload.setdefault(key, request.args.get(key))
    return payload


def api_request_authorized(payload: dict[str, Any] | None = None) -> bool:
    expected = api_access_token()
    if not expected:
        return True
    data = payload or {}
    candidates = [
        str(request.headers.get("X-Stunden-Token") or "").strip(),
        str(data.get("token") or "").strip(),
        str(request.args.get("token") or "").strip(),
    ]
    return any(candidate and candidate == expected for candidate in candidates)


def telegram_chat_key(chat_id: Any, user_id: Any = None) -> str:
    chat = str(chat_id or "").strip()
    user = str(user_id or "").strip()
    return f"{chat}:{user}" if user else chat


def normalize_filename(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return Path(text).name


def extract_work_date_from_parser_summary(summary: str | None) -> str:
    text = str(summary or "").strip()
    if not text:
        return ""
    match = re.search(r"Datum erkannt:\s*([^\n]+)", text)
    if not match:
        return ""
    raw = str(match.group(1) or "").strip()
    if raw in {"", "—", "-", "None", "none"}:
        return ""
    return normalize_ai_date(raw)


def resolve_work_date_from_import(conn: sqlite3.Connection, import_row: sqlite3.Row | dict[str, Any] | None) -> tuple[int | None, str]:
    if import_row is None:
        return None, ""
    import_id = int(import_row["id"] or 0) if import_row["id"] is not None else None
    parser_summary = str(import_row["parser_summary"] or "")

    if import_id:
        linked_entry = conn.execute(
            "SELECT work_date FROM work_entries WHERE import_id = ? LIMIT 1",
            (import_id,),
        ).fetchone()
        if linked_entry is not None:
            return import_id, str(linked_entry["work_date"] or "").strip()

    parsed_date = extract_work_date_from_parser_summary(parser_summary)
    if parsed_date:
        linked_by_date = conn.execute(
            "SELECT import_id, work_date FROM work_entries WHERE work_date = ? LIMIT 1",
            (parsed_date,),
        ).fetchone()
        if linked_by_date is not None:
            resolved_import_id = int(linked_by_date["import_id"] or import_id or 0) or import_id
            return resolved_import_id, str(linked_by_date["work_date"] or parsed_date).strip()
        return import_id, parsed_date

    imported_at = str(import_row["imported_at"] or "").strip()
    if imported_at:
        try:
            fallback_date = datetime.fromisoformat(imported_at.replace("Z", "+00:00")).date().isoformat()
            return import_id, fallback_date
        except Exception:
            pass
    return import_id, ""


def parse_iso_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def find_recent_import_for_followup(conn: sqlite3.Connection, pending: sqlite3.Row, *, window_minutes: int = 90) -> sqlite3.Row | None:
    target_times = [
        parse_iso_timestamp(pending["updated_at"]),
        parse_iso_timestamp(pending["created_at"]),
    ]
    target_times = [dt for dt in target_times if dt is not None]
    rows = conn.execute(
        """
        SELECT *
        FROM imports
        WHERE (stored_name LIKE 'telegram_%' OR original_name LIKE 'telegram_%')
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()
    if not rows:
        return None
    if not target_times:
        return rows[0]
    best_row = None
    best_score = None
    max_seconds = max(int(window_minutes or 0), 1) * 60
    for row in rows:
        row_times = [
            parse_iso_timestamp(row["processed_at"]),
            parse_iso_timestamp(row["imported_at"]),
        ]
        row_times = [dt for dt in row_times if dt is not None]
        if not row_times:
            continue
        deltas = [abs((row_dt - target_dt).total_seconds()) for row_dt in row_times for target_dt in target_times]
        if not deltas:
            continue
        score = min(deltas)
        if score > max_seconds:
            continue
        if best_score is None or score < best_score:
            best_row = row
            best_score = score
    return best_row


def find_import_for_telegram(conn: sqlite3.Connection, *, source_path: str = "", filename: str = "", allow_fallback: bool = True) -> sqlite3.Row | None:
    source_path = str(source_path or "").strip()
    filename = normalize_filename(filename)
    if source_path:
        row = conn.execute(
            "SELECT * FROM imports WHERE source_path = ? OR processed_path = ? ORDER BY id DESC LIMIT 1",
            (source_path, source_path),
        ).fetchone()
        if row is not None:
            return row
    if filename:
        patterns = (filename, f"%/{filename}", f"%\\{filename}")
        row = conn.execute(
            """
            SELECT *
            FROM imports
            WHERE original_name = ? OR stored_name = ? OR source_path LIKE ? OR source_path LIKE ? OR processed_path LIKE ? OR processed_path LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (filename, filename, patterns[1], patterns[2], patterns[1], patterns[2]),
        ).fetchone()
        if row is not None:
            return row
    if allow_fallback:
        return conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 1").fetchone()
    return None


def upsert_telegram_followup(conn: sqlite3.Connection, *, chat_id: str, user_id: str, import_id: int | None, work_date: str, prompt_text: str, context: dict[str, Any] | None = None) -> None:
    chat_key = telegram_chat_key(chat_id, user_id)
    conn.execute(
        """
        INSERT INTO telegram_followups (chat_key, chat_id, user_id, import_id, work_date, prompt_text, status, context_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        ON CONFLICT(chat_key) DO UPDATE SET
            chat_id = excluded.chat_id,
            user_id = excluded.user_id,
            import_id = excluded.import_id,
            work_date = excluded.work_date,
            prompt_text = excluded.prompt_text,
            status = 'pending',
            context_json = excluded.context_json,
            updated_at = excluded.updated_at
        """,
        (
            chat_key,
            chat_id,
            user_id or None,
            import_id,
            work_date or None,
            prompt_text,
            json.dumps(context or {}, ensure_ascii=False),
            now_iso(),
            now_iso(),
        ),
    )


def find_pending_telegram_followup(conn: sqlite3.Connection, *, chat_id: str, user_id: str) -> sqlite3.Row | None:
    chat = str(chat_id or '').strip()
    user = str(user_id or '').strip()
    if not chat:
        return None
    candidates: list[sqlite3.Row | None] = []
    if chat and user:
        candidates.append(
            conn.execute(
                "SELECT * FROM telegram_followups WHERE chat_key = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (telegram_chat_key(chat, user),),
            ).fetchone()
        )
    candidates.append(
        conn.execute(
            "SELECT * FROM telegram_followups WHERE chat_key = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (telegram_chat_key(chat, ''),),
        ).fetchone()
    )
    candidates.append(
        conn.execute(
            "SELECT * FROM telegram_followups WHERE chat_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (chat,),
        ).fetchone()
    )
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def apply_catchup_minutes_to_entry(conn: sqlite3.Connection, *, work_date: str, minutes_value: int, note_line: str = "") -> bool:
    work_date = str(work_date or "").strip()
    if not work_date:
        return False
    entry = conn.execute("SELECT * FROM work_entries WHERE work_date = ? LIMIT 1", (work_date,)).fetchone()
    if entry is None:
        return False
    current_manual = abs(int(entry["manual_correction_min"] or 0))
    new_manual = current_manual + abs(int(minutes_value or 0))
    imported_rest_component_min = int(entry["imported_rest_component_min"] or 0)
    current_budget = int(entry["carryover_budget_min"] or 0)
    manual_budget_base = current_budget - imported_rest_component_min + current_manual
    new_budget = compute_carryover_budget(imported_rest_component_min, new_manual, manual_budget_base)
    new_effective = compute_effective(
        int(entry["system_plusminus_min"] or 0),
        int(entry["deducted_break_min"] or 0),
        new_manual,
    )
    updated_note = merge_notes(entry["note"], note_line) if note_line else (entry["note"] or "")
    conn.execute(
        "UPDATE work_entries SET manual_correction_min = ?, carryover_budget_min = ?, effective_day_value_min = ?, note = ?, updated_at = ? WHERE id = ?",
        (new_manual, new_budget, new_effective, updated_note or None, now_iso(), int(entry["id"])),
    )
    if entry["import_id"]:
        current_import = conn.execute("SELECT notes FROM imports WHERE id = ?", (int(entry["import_id"]),)).fetchone()
        merged_import_note = merge_notes(current_import["notes"] if current_import else "", "Telegram-Nachlauf übernommen.")
        conn.execute(
            "UPDATE imports SET status = 'needs_check', notes = ?, processed_at = ? WHERE id = ?",
            (merged_import_note or None, now_iso(), int(entry["import_id"])),
        )
    return True


def build_telegram_pending_reply_context(parsed: dict[str, Any], reply_text: str, *, import_id: int | None, work_date: str) -> dict[str, Any]:
    return {
        "pending_reply": {
            "reply_text": str(reply_text or "").strip(),
            "parsed": parsed,
            "queued_at": now_iso(),
            "import_id": import_id or None,
            "work_date": work_date or "",
        }
    }


def process_pending_telegram_followups(conn: sqlite3.Connection, limit: int = 20) -> int:
    rows = conn.execute(
        """
        SELECT *
        FROM telegram_followups
        WHERE status = 'pending'
        ORDER BY updated_at ASC, id ASC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    applied = 0
    for row in rows:
        context = load_json_object(row["context_json"])
        pending_reply = context.get("pending_reply") or {}
        parsed = pending_reply.get("parsed") or {}
        minutes_value = abs(int(parsed.get("minutes") or 0))
        if minutes_value <= 0:
            continue
        import_id, work_date = resolve_pending_followup_target(conn, row)
        if not work_date:
            work_date = str(pending_reply.get("work_date") or "").strip()
        if not work_date:
            continue
        if str(parsed.get("kind")) == "block":
            note = f"Telegram Nachlauf: {parsed.get('display')} ({minutes_value} Min)"
        else:
            note = f"Telegram Nachlauf: {minutes_value} Min"
        if not apply_catchup_minutes_to_entry(conn, work_date=work_date, minutes_value=minutes_value, note_line=note):
            continue
        result_context = dict(context)
        result_context["resolved_at"] = now_iso()
        result_context["import_id"] = import_id or None
        result_context["work_date"] = work_date
        result_context["applied_to"] = "work_entry"
        result_context["reply_text"] = str(pending_reply.get("reply_text") or "").strip()
        result_context["parsed"] = parsed
        result_context.pop("pending_reply", None)
        conn.execute(
            "UPDATE telegram_followups SET status = 'resolved', import_id = ?, work_date = ?, context_json = ?, updated_at = ? WHERE id = ?",
            (import_id or None, work_date, json.dumps(result_context, ensure_ascii=False), now_iso(), int(row["id"])),
        )
        applied += 1
    return applied


def migrate_legacy_telegram_catchups(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, booking_date, minutes, note
        FROM account_transactions
        WHERE COALESCE(kind, 'balance') = 'catchup'
          AND COALESCE(note, '') LIKE 'Telegram Nachlauf:%'
        ORDER BY booking_date, id
        """
    ).fetchall()
    for row in rows:
        minutes_value = abs(int(row["minutes"] or 0))
        if minutes_value <= 0:
            continue
        if apply_catchup_minutes_to_entry(
            conn,
            work_date=str(row["booking_date"] or "").strip(),
            minutes_value=minutes_value,
            note_line=str(row["note"] or "").strip(),
        ):
            conn.execute("DELETE FROM account_transactions WHERE id = ?", (int(row["id"]),))


def parse_telegram_catchup_reply(text: Any) -> tuple[dict[str, Any] | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return None, TELEGRAM_INVALID_REPLY_PROMPT
    lowered = raw.lower().strip()
    if lowered in {"0", "0 min", "0 minuten", "nein", "ne", "kein", "keine", "nö", "nope"}:
        return {"minutes": 0, "kind": "none", "display": "0 Min"}, None
    block_match = re.search(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})", raw)
    if block_match:
        start = normalize_clock_time(block_match.group(1))
        end = normalize_clock_time(block_match.group(2))
        minutes = segment_minutes(start, end)
        if minutes > 0:
            return {"minutes": minutes, "kind": "block", "display": f"{start}–{end}"}, None
        return None, TELEGRAM_INVALID_REPLY_PROMPT
    minute_match = re.search(r"[+-]?\d+(?::\d{1,2})?", raw)
    if minute_match:
        minutes = abs(parse_minutes(minute_match.group(0), default=0))
        if minutes > 0:
            return {"minutes": minutes, "kind": "minutes", "display": minutes_plain(minutes)}, None
    return None, TELEGRAM_INVALID_REPLY_PROMPT


def resolve_pending_followup_target(conn: sqlite3.Connection, pending: sqlite3.Row) -> tuple[int | None, str]:
    import_id = int(pending["import_id"] or 0) if pending["import_id"] is not None else None
    work_date = str(pending["work_date"] or "").strip()
    if import_id:
        import_row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
        if import_row is not None:
            resolved_import_id, resolved_work_date = resolve_work_date_from_import(conn, import_row)
            if resolved_import_id or resolved_work_date:
                return resolved_import_id, resolved_work_date or work_date
    context = load_json_object(pending["context_json"])
    filename = normalize_filename(context.get("filename") or context.get("file_name") or context.get("original_name"))
    source_path = str(context.get("source_path") or context.get("path") or "").strip()
    import_row = find_import_for_telegram(conn, source_path=source_path, filename=filename, allow_fallback=False)
    if import_row is not None:
        resolved_import_id, resolved_work_date = resolve_work_date_from_import(conn, import_row)
        if resolved_import_id or resolved_work_date:
            return resolved_import_id, resolved_work_date or work_date
    fallback_import = find_recent_import_for_followup(conn, pending)
    if fallback_import is not None:
        resolved_import_id, resolved_work_date = resolve_work_date_from_import(conn, fallback_import)
        if resolved_import_id or resolved_work_date:
            return resolved_import_id, resolved_work_date or work_date
    return import_id, work_date


def apply_telegram_catchup_reply(conn: sqlite3.Connection, *, chat_id: str, user_id: str, reply_text: str) -> tuple[bool, str, dict[str, Any]]:
    pending = find_pending_telegram_followup(conn, chat_id=chat_id, user_id=user_id)
    if pending is None:
        return False, "Ich habe gerade keinen offenen Screenshot für eine Nachlauf-Rückfrage.", {}
    parsed, error = parse_telegram_catchup_reply(reply_text)
    if error:
        return False, error, {"pending_id": int(pending["id"])}
    import_id, work_date = resolve_pending_followup_target(conn, pending)
    import_id = int(import_id or 0)
    if not work_date:
        work_date = str(pending["work_date"] or "").strip() or date.today().isoformat()
    minutes_value = int(parsed.get("minutes") or 0)
    result_context = {
        "reply_text": str(reply_text or "").strip(),
        "parsed": parsed,
        "resolved_at": now_iso(),
        "import_id": import_id or None,
        "work_date": work_date,
    }
    if minutes_value <= 0:
        conn.execute(
            "UPDATE telegram_followups SET status = 'resolved', import_id = ?, work_date = ?, context_json = ?, updated_at = ? WHERE id = ?",
            (import_id or None, work_date, json.dumps(result_context, ensure_ascii=False), now_iso(), int(pending["id"])),
        )
        return True, f"Okay, ich habe für den {date_de_filter(work_date)} keinen Nachlauf eingetragen.", {"work_date": work_date, "minutes": 0}
    if str(parsed.get("kind")) == "block":
        note = f"Telegram Nachlauf: {parsed.get('display')} ({minutes_value} Min)"
        confirmation = f"Danke, ich habe den Nachlauf {parsed.get('display')} ({minutes_value} Minuten) für den {date_de_filter(work_date)} übernommen."
    else:
        note = f"Telegram Nachlauf: {minutes_value} Min"
        confirmation = f"Danke, ich habe {minutes_value} Minuten Nachlauf für den {date_de_filter(work_date)} übernommen."
    applied_to_entry = work_date and apply_catchup_minutes_to_entry(conn, work_date=work_date, minutes_value=minutes_value, note_line=note)
    if not applied_to_entry:
        base_context = load_json_object(pending["context_json"])
        base_context.update(build_telegram_pending_reply_context(parsed, reply_text, import_id=import_id or None, work_date=work_date))
        conn.execute(
            "UPDATE telegram_followups SET status = 'pending', import_id = ?, work_date = ?, context_json = ?, updated_at = ? WHERE id = ?",
            (import_id or None, work_date or None, json.dumps(base_context, ensure_ascii=False), now_iso(), int(pending["id"])),
        )
        return True, f"Danke, ich habe {minutes_value} Minuten vorgemerkt. Sobald der Screenshot fertig verarbeitet ist, trage ich sie automatisch für den {date_de_filter(work_date)} ein.", {"work_date": work_date, "minutes": minutes_value, "queued": True}
    result_context["applied_to"] = "work_entry"
    conn.execute(
        "UPDATE telegram_followups SET status = 'resolved', import_id = ?, work_date = ?, context_json = ?, updated_at = ? WHERE id = ?",
        (import_id or None, work_date, json.dumps(result_context, ensure_ascii=False), now_iso(), int(pending["id"])),
    )
    # Wird der Nachlauf erst nach dem Import beantwortet, war die erste Push-Nachricht
    # noch ohne Nachlauf. Danach deshalb die finale Dashboard-Zeile erneut senden.
    notify_telegram_catchup_result(conn, import_id or None, work_date)
    return True, confirmation, {"work_date": work_date, "minutes": minutes_value, "applied_to": result_context["applied_to"]}


def default_segments_text(come_time: str | None, go_time: str | None) -> str:
    start = normalize_clock_time(come_time)
    end = normalize_clock_time(go_time)
    if start and end:
        return f"{start}–{end}"
    return ""


def segments_text_from_parser_summary(summary: str | None) -> str:
    return build_segments_text(segments_list_from_parser_summary(summary))


def preferred_work_time_text(entry: dict[str, Any] | None, parser_summary: str | None = None) -> str:
    if not entry:
        return ''
    segments = preferred_segments(entry, parser_summary)
    if segments:
        return build_segments_text(segments)
    current = str(entry.get('work_segments_text') or '').strip()
    default_text = default_segments_text(entry.get('come_time'), entry.get('go_time'))
    return current or default_text or ''


def preferred_plan_segments(plan: dict[str, Any] | None) -> list[dict[str, str]]:
    if not plan:
        return []
    stored = load_segments_json(plan.get('plan_segments_json'))
    if stored:
        return stored
    text_segments = segments_list_from_text(plan.get('plan_segments_text'))
    if text_segments:
        return text_segments
    return segments_list_from_text(default_segments_text(plan.get('planned_start'), plan.get('planned_end')))


def preferred_plan_time_text(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ''
    segments = preferred_plan_segments(plan)
    if segments:
        return build_segments_text(segments)
    current = str(plan.get('plan_segments_text') or '').strip()
    default_text = default_segments_text(plan.get('planned_start'), plan.get('planned_end'))
    return current or default_text or ''


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def resize_for_ai(image: Image.Image, max_width: int = 1200) -> Image.Image:
    work = ImageOps.exif_transpose(image).convert("RGB")
    work = ImageOps.autocontrast(work)
    if work.width <= max_width:
        return work
    ratio = max_width / float(work.width)
    return work.resize((max(1, int(work.width * ratio)), max(1, int(work.height * ratio))), Image.Resampling.LANCZOS)


def save_ai_variant(image: Image.Image, output_path: Path, max_width: int = 1200, quality: int = 70) -> Path:
    prepared = resize_for_ai(image, max_width=max_width)
    prepared.save(output_path, format="JPEG", quality=quality, optimize=True)
    return output_path


def prepare_ai_images(path: Path, provider: str = "gemini") -> list[Path]:
    ensure_debug_dir()
    source = Image.open(path)
    full = ImageOps.exif_transpose(source).convert("RGB")
    width, height = full.size
    base = debug_file_base(path)

    variants: list[tuple[Image.Image, str, int, int]] = []
    if provider == "ollama":
        lower_band = full.crop((0, int(height * 0.58), width, int(height * 0.97)))
        tight_band = full.crop((0, int(height * 0.66), width, int(height * 0.95)))
        variants = [
            (lower_band, "ai_local_lower", 1000, 65),
            (tight_band, "ai_local_tight", 900, 60),
        ]
    else:
        lower_top = int(height * 0.34)
        lower = full.crop((0, lower_top, width, height))
        variants = [
            (full, "ai_full", 1400, 80),
            (lower, "ai_lower", 1200, 75),
        ]

    paths: list[Path] = []
    for image, suffix, max_width, quality in variants:
        out_path = DEBUG_DIR / f"{base}_{suffix}.jpg"
        save_ai_variant(image, out_path, max_width=max_width, quality=quality)
        paths.append(out_path)
    return paths


def extract_json_block(text: str) -> dict[str, Any]:
    payload = str(text or "").strip()
    if not payload:
        raise ValueError("Leere Modellantwort")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", payload, re.S | re.I)
    if fenced:
        payload = fenced.group(1)
    try:
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r"\{.*\}", payload, re.S)
    if not match:
        raise ValueError(f"Kein JSON in Modellantwort gefunden: {payload[:400]}")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Modellantwort ist kein JSON-Objekt")
    return data


def parse_retry_seconds(detail: str, default_seconds: int = 60) -> int:
    text = str(detail or "")
    match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", text, re.I)
    if match:
        try:
            return max(5, int(float(match.group(1))) + 1)
        except Exception:
            pass
    match = re.search(r'"retryDelay"\s*:\s*"([0-9]+)s"', text, re.I)
    if match:
        try:
            return max(5, int(match.group(1)))
        except Exception:
            pass
    return max(5, int(default_seconds))


def set_gemini_cooldown(seconds: int) -> int:
    global GEMINI_COOLDOWN_UNTIL
    wait = max(5, int(seconds))
    with GEMINI_STATE_LOCK:
        GEMINI_COOLDOWN_UNTIL = max(GEMINI_COOLDOWN_UNTIL, time.time() + wait)
    return wait


def get_gemini_cooldown_remaining() -> int:
    with GEMINI_STATE_LOCK:
        remaining = int(round(GEMINI_COOLDOWN_UNTIL - time.time()))
    return max(0, remaining)


def gemini_in_cooldown() -> bool:
    return get_gemini_cooldown_remaining() > 0


def is_transient_ai_error_message(message: str) -> bool:
    text = str(message or "").lower()
    return "gemini-limit erreicht" in text or "gemini ist gerade überlastet" in text or "bereits eine ai-analyse" in text


def retry_waiting_summary() -> str:
    return "Analyse wartet automatisch auf den nächsten freien Gemini-Versuch."


def normalize_notify_service(raw_service: str) -> tuple[str, str] | None:
    value = str(raw_service or "").strip()
    if not value:
        return None
    if "." in value:
        domain, service = value.split(".", 1)
    else:
        domain, service = "notify", value
    domain = re.sub(r"[^A-Za-z0-9_]+", "", domain.strip())
    service = re.sub(r"[^A-Za-z0-9_]+", "", service.strip())
    if not domain or not service:
        return None
    return domain, service


def home_assistant_api_request(path: str) -> Any:
    token = str(os.environ.get("SUPERVISOR_TOKEN") or "").strip()
    if not token:
        return None
    normalized_path = "/" + str(path or "").lstrip("/")
    url = f"http://supervisor/core/api{normalized_path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if not 200 <= int(response.status) < 300:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError):
        return None


def discover_mobile_app_notify_targets() -> list[tuple[str, str]]:
    services = home_assistant_api_request("/services")
    if not isinstance(services, list):
        return []

    targets: list[tuple[str, str]] = []
    for domain_entry in services:
        if not isinstance(domain_entry, dict) or str(domain_entry.get("domain") or "") != "notify":
            continue
        domain_services = domain_entry.get("services")
        if not isinstance(domain_services, dict):
            continue
        for service_name in sorted(domain_services):
            service = str(service_name or "").strip()
            if service.startswith("mobile_app_"):
                targets.append(("notify", service))

    return targets


def configured_explicit_notify_targets() -> list[tuple[str, str]]:
    raw = configured_push_notify_service()
    if not raw:
        return []

    special_values = {
        "all",
        "all_devices",
        "all_mobile_apps",
        "all_mobile_app_devices",
        "alle",
        "alle_geraete",
    }
    targets: list[tuple[str, str]] = []
    for value in re.split(r"[,;\s]+", raw):
        candidate = str(value or "").strip()
        if not candidate or candidate.lower() in special_values:
            continue
        target = normalize_notify_service(candidate)
        if target is not None:
            targets.append(target)
    return targets


def all_push_notify_targets() -> list[tuple[str, str]]:
    # Immer alle über die Home-Assistant-App registrierten Mobilgeräte ermitteln.
    # Explizit konfigurierte Dienste bleiben als zusätzliche Fallback-Ziele erhalten.
    targets = discover_mobile_app_notify_targets()
    targets.extend(configured_explicit_notify_targets())

    if not targets:
        fallback = normalize_notify_service(FALLBACK_PUSH_NOTIFY_SERVICE)
        if fallback is not None:
            targets.append(fallback)

    unique_targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        unique_targets.append(target)
    return unique_targets


def call_home_assistant_service(domain: str, service: str, payload: dict[str, Any]) -> bool:
    token = str(os.environ.get("SUPERVISOR_TOKEN") or "").strip()
    if not token:
        return False
    url = f"http://supervisor/core/api/services/{domain}/{service}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return 200 <= int(response.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def send_push_notification(message: str, *, title: str | None = None, data: dict[str, Any] | None = None) -> bool:
    if not configured_push_notify_enabled():
        return False

    payload: dict[str, Any] = {
        "title": title or configured_push_notify_title(),
        "message": str(message or "").strip(),
    }
    if not payload["message"]:
        return False
    if data:
        payload["data"] = data

    targets = all_push_notify_targets()
    if not targets:
        return False

    successful = 0
    for domain, service in targets:
        # Jedes Gerät wird unabhängig benachrichtigt. Ein Fehler darf die
        # nachfolgenden Geräte nicht blockieren.
        try:
            if call_home_assistant_service(domain, service, payload):
                successful += 1
            else:
                print(f"Push an {domain}.{service} fehlgeschlagen.", flush=True)
        except Exception as exc:
            print(f"Push an {domain}.{service} fehlgeschlagen: {exc}", flush=True)

    return successful > 0


def catchup_adjustment_for_date(conn: sqlite3.Connection, work_date: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(minutes), 0) AS total
        FROM account_transactions
        WHERE COALESCE(kind, 'balance') = 'catchup' AND booking_date = ?
        """,
        (work_date,),
    ).fetchone()
    return int(row["total"] or 0) if row is not None else 0


def format_push_work_date(work_date: str | None) -> str:
    text = str(work_date or "").strip()
    if not text:
        return ""
    try:
        d = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    return f"{WEEKDAY_SHORT[d.weekday()]}, {d.strftime('%d.%m')}"


def build_import_push_line(conn: sqlite3.Connection, import_id: int, fallback_work_date: str | None = None) -> tuple[str, str]:
    entry_row = conn.execute("SELECT * FROM work_entries WHERE import_id = ? LIMIT 1", (import_id,)).fetchone()
    fallback = str(fallback_work_date or "").strip()
    if entry_row is None and fallback:
        entry_row = conn.execute("SELECT * FROM work_entries WHERE work_date = ? LIMIT 1", (fallback,)).fetchone()
    if entry_row is None:
        return "", fallback

    entry = dict(entry_row)
    work_date = str(entry.get("work_date") or fallback).strip()
    date_adjustment = catchup_adjustment_for_date(conn, work_date) if work_date else 0
    effective = adjusted_effective_for_entry(entry, date_adjustment)

    plan_row = None
    if work_date:
        plan_row = conn.execute("SELECT expected_result_min FROM plans WHERE plan_date = ? LIMIT 1", (work_date,)).fetchone()
    prefix = format_push_work_date(work_date)
    prefix_text = f"{prefix}, " if prefix else ""
    if plan_row is not None:
        planned = int(plan_row["expected_result_min"] or 0)
        return f"{prefix_text}Effektiver Tageswert: {minutes_hm(effective)}, geplant war: {minutes_hm(planned)}", work_date
    return f"{prefix_text}Effektiver Tageswert: {minutes_hm(effective)}", work_date


def notify_import_result(conn: sqlite3.Connection, import_id: int, parsed: dict[str, Any], original_name: str) -> None:
    try:
        line, work_date = build_import_push_line(conn, import_id, str(parsed.get("work_date") or ""))
        if not line:
            return
        send_push_notification(
            line,
            title=configured_push_notify_title(),
            data={
                "tag": f"stundenplanung_import_{work_date or import_id}",
                "group": "stundenplanung",
                "url": "/",
                "import_id": import_id,
                "work_date": work_date,
                "source": str(original_name or ""),
            },
        )
    except Exception:
        # Eine fehlgeschlagene Push-Nachricht darf den Import niemals verhindern.
        pass


def notify_telegram_catchup_result(conn: sqlite3.Connection, import_id: int | None, work_date: str | None) -> None:
    try:
        line, resolved_work_date = build_import_push_line(conn, int(import_id or 0), str(work_date or ""))
        if not line:
            return
        send_push_notification(
            line,
            title=configured_push_notify_title(),
            data={
                "tag": f"stundenplanung_import_{resolved_work_date or import_id or 'nachlauf'}",
                "group": "stundenplanung",
                "url": "/",
                "import_id": int(import_id or 0),
                "work_date": resolved_work_date or work_date or "",
                "source": "telegram_nachlauf",
            },
        )
    except Exception:
        # Eine fehlgeschlagene Push-Nachricht darf die Telegram-Antwort nicht verhindern.
        pass


def queue_import_for_retry(
    conn: sqlite3.Connection,
    import_id: int,
    message: str,
    *,
    processed_at: str | None = None,
    prefix: str = "Wartet auf Neuversuch",
) -> None:
    note_text = f"{prefix}: {str(message or '').strip()}".strip()
    if processed_at is None:
        conn.execute(
            "UPDATE imports SET status = ?, notes = ?, parser_summary = ? WHERE id = ?",
            ("retry_waiting", note_text, retry_waiting_summary(), import_id),
        )
    else:
        conn.execute(
            "UPDATE imports SET status = ?, notes = ?, parser_summary = ?, processed_at = ? WHERE id = ?",
            ("retry_waiting", note_text, retry_waiting_summary(), processed_at, import_id),
        )


def analyze_import_and_store(
    conn: sqlite3.Connection,
    import_id: int,
    path: Path,
    original_name: str,
    *,
    error_prefix: str = "Parserfehler",
    queue_prefix: str = "Automatischer Neuversuch wartet",
) -> tuple[str, str]:
    try:
        parsed = parse_screenshot(path, original_name)
        # Datumsschutz: Wenn eine Reanalyse das Datum lokal korrigiert,
        # darf der Import nicht weiter an einem zuvor falsch erkannten Tag hängen.
        parsed_work_date = str(parsed.get("work_date") or "").strip()
        if parsed_work_date:
            conn.execute(
                "UPDATE work_entries SET import_id = NULL, updated_at = ? WHERE import_id = ? AND work_date <> ?",
                (now_iso(), import_id, parsed_work_date),
            )

        status, note = auto_create_or_update_entry(
            conn,
            parsed,
            import_id,
            datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
            original_name,
        )
        if parsed.get("confidence", 0) < 2:
            status = "needs_check"
            note += " Bitte Werte prüfen."
        conn.execute(
            "UPDATE imports SET status = ?, notes = ?, parser_summary = ?, processed_at = ? WHERE id = ?",
            (status, note, build_parser_summary_for_saved_entry(conn, import_id, parsed), now_iso(), import_id),
        )
        process_pending_telegram_followups(conn)
        notify_import_result(conn, import_id, parsed, original_name)
        return "success", note
    except Exception as exc:
        message = str(exc)
        if is_transient_ai_error_message(message):
            queue_import_for_retry(conn, import_id, message, processed_at=now_iso(), prefix=queue_prefix)
            return "queued", message
        conn.execute(
            "UPDATE imports SET status = ?, notes = ?, parser_summary = ?, processed_at = ? WHERE id = ?",
            ("error", f"{error_prefix}: {message}", "Automatische Verarbeitung fehlgeschlagen.", now_iso(), import_id),
        )
        return "error", message


def retry_pending_imports(limit: int = 3) -> int:
    if configured_ai_provider() == "gemini" and gemini_in_cooldown():
        return 0
    processed_count = 0
    with PROCESSING_LOCK:
        with closing(get_db()) as conn:
            pending_rows = conn.execute(
                """
                SELECT *
                FROM imports
                WHERE status = 'retry_waiting' AND processed_path IS NOT NULL
                ORDER BY COALESCE(processed_at, imported_at) ASC, id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            for import_row in pending_rows:
                processed_path = str(import_row["processed_path"] or "").strip()
                if not processed_path:
                    continue
                path = Path(processed_path)
                if not path.exists():
                    conn.execute(
                        "UPDATE imports SET status = ?, notes = ?, processed_at = ? WHERE id = ?",
                        ("error", "Datei fehlt auf dem Dateisystem.", now_iso(), int(import_row["id"])),
                    )
                    conn.commit()
                    continue
                outcome, _ = analyze_import_and_store(
                    conn,
                    int(import_row["id"]),
                    path,
                    str(import_row["original_name"] or path.name),
                    error_prefix="Automatischer Neuversuch fehlgeschlagen",
                    queue_prefix="Automatischer Neuversuch wartet",
                )
                conn.commit()
                if outcome == "queued":
                    break
                processed_count += 1
    return processed_count


def call_ollama_generate(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request_obj = urllib.request.Request(
        f"{configured_ollama_url()}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=max(10, AI_TIMEOUT_SECONDS)) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama nicht erreichbar: {exc.reason}") from exc
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Ollama-Antwort konnte nicht gelesen werden")
    return data


def call_gemini_generate(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = configured_gemini_api_key()
    if not api_key:
        raise RuntimeError("Gemini API-Key fehlt. Bitte im Add-on gemini_api_key setzen.")

    cooldown_remaining = get_gemini_cooldown_remaining()
    if cooldown_remaining > 0:
        raise RuntimeError(f"Gemini-Limit aktiv. Neuer Versuch in {cooldown_remaining} Sekunden.")

    if not AI_REQUEST_LOCK.acquire(blocking=False):
        raise RuntimeError("Es läuft bereits eine AI-Analyse. Bitte kurz warten.")

    body = json.dumps(payload).encode("utf-8")
    model = configured_gemini_model()
    request_obj = urllib.request.Request(
        f"{GEMINI_API_BASE}/models/{model}:generateContent",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=max(10, AI_TIMEOUT_SECONDS)) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 429:
            wait = set_gemini_cooldown(parse_retry_seconds(detail, 70))
            raise RuntimeError(f"Gemini-Limit erreicht. Neuer Versuch in {wait} Sekunden.") from exc
        if exc.code == 503:
            wait = set_gemini_cooldown(parse_retry_seconds(detail, 30))
            raise RuntimeError(f"Gemini ist gerade überlastet. Neuer Versuch in {wait} Sekunden.") from exc
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini nicht erreichbar: {exc.reason}") from exc
    finally:
        AI_REQUEST_LOCK.release()

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Gemini-Antwort konnte nicht gelesen werden")
    return data


def extract_gemini_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("Gemini lieferte keine Kandidaten")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        if chunks:
            return "".join(chunks).strip()
    prompt_feedback = response.get("promptFeedback")
    raise RuntimeError(f"Gemini lieferte keinen Text zurück: {json.dumps(prompt_feedback, ensure_ascii=False)[:300]}")


def extract_ollama_text(response: dict[str, Any]) -> str:
    raw_text = str(response.get("response") or "").strip()
    if not raw_text:
        raise RuntimeError("Ollama lieferte keinen Text zurück")
    return raw_text


def ai_result_field_count(item: dict[str, Any] | None) -> int:
    item = item or {}
    count = 0
    if item.get("work_date"):
        count += 1
    if item.get("come_time"):
        count += 1
    if item.get("go_time"):
        count += 1
    if item.get("work_duration_found"):
        count += 1
    if item.get("deducted_break_found"):
        count += 1
    return count


def ai_result_is_usable(item: dict[str, Any] | None) -> bool:
    item = item or {}
    return bool(item.get("work_date") and item.get("come_time") and item.get("go_time") and item.get("work_duration_found"))


def finalize_ai_result(model_json: dict[str, Any], raw_text: str, provider: str, model_label: str, debug_base: str, original_name: str = "") -> dict[str, Any]:
    suffix = "gemini" if provider == "gemini" else "ollama"
    write_debug_text(DEBUG_DIR / f"{debug_base}_{suffix}_raw.txt", raw_text)
    write_debug_text(DEBUG_DIR / f"{debug_base}_{suffix}_json.json", json.dumps(model_json, ensure_ascii=False, indent=2))

    fallback_year = None
    fallback_date = extract_date_from_filename(original_name)
    if fallback_date:
        fallback_year = int(fallback_date[:4])

    work_date = normalize_ai_date(model_json.get("date") or model_json.get("datum"), fallback_year=fallback_year) or fallback_date or ""
    raw_segments = normalize_ai_segments(model_json.get("segments"))
    segments = [dict(item) for item in raw_segments]
    come_time = normalize_clock_time(model_json.get("kommt") or model_json.get("kommen") or model_json.get("come_time"))
    go_time = normalize_clock_time(model_json.get("geht") or model_json.get("go_time") or model_json.get("ende"))
    if not come_time and raw_segments:
        come_time = raw_segments[0]["start"]
    if not go_time and raw_segments:
        go_time = raw_segments[-1]["end"]

    rest_raw = model_json.get("restpausenabzug")
    if rest_raw in (None, ""):
        rest_raw = model_json.get("pause_abgezogen", model_json.get("deducted_break"))

    last_work_end_before_rest = normalize_clock_time(
        model_json.get("letztes_arbeitsende_vor_rest")
        or model_json.get("arbeitsende_vor_rest")
        or model_json.get("last_work_end_before_rest")
        or model_json.get("end_before_rest")
    )
    rest_override_applied = False
    calc_segments = [dict(item) for item in raw_segments]
    if rest_raw not in (None, "") and last_work_end_before_rest:
        calc_segments, rest_override_applied = apply_last_segment_override_for_rest_break(calc_segments, last_work_end_before_rest)

    display_segments = [dict(item) for item in raw_segments]
    if display_segments and go_time:
        last_display = dict(display_segments[-1])
        last_start = normalize_clock_time(last_display.get("start"))
        last_end = normalize_clock_time(last_display.get("end"))
        if last_start and last_end and last_end != go_time and segment_minutes(last_start, go_time) > 0:
            should_restore_visible_end = False
            if rest_raw not in (None, ""):
                if last_work_end_before_rest and last_end == last_work_end_before_rest:
                    should_restore_visible_end = True
                elif segment_minutes(last_end, go_time) > 0:
                    should_restore_visible_end = True
            if should_restore_visible_end:
                display_segments[-1]["end"] = go_time

    work_duration_min = compute_work_duration_from_segments(calc_segments) if calc_segments else 0
    work_duration_found = work_duration_min > 0
    deducted_break_found = rest_raw not in (None, "")
    deducted_break_min = normalize_ai_duration_minutes(rest_raw, signed=False) if deducted_break_found else 0

    target_minutes = target_minutes_for_work_date(work_date)
    system_plusminus_found = work_duration_found
    system_plusminus_min = work_duration_min - target_minutes if work_duration_found else 0

    model_conf = model_json.get("confidence")
    try:
        model_conf_f = float(model_conf)
    except Exception:
        model_conf_f = 0.0
    confidence = ai_result_field_count({
        "work_date": work_date,
        "come_time": come_time,
        "go_time": go_time,
        "work_duration_found": work_duration_found,
        "deducted_break_found": deducted_break_found,
    })
    if model_conf_f >= 0.75:
        confidence += 1
    if len(segments) >= 1:
        confidence += 1

    hints = model_json.get("hinweise")
    if isinstance(hints, list):
        hint_lines = [str(item).strip() for item in hints if str(item).strip()]
    else:
        hint_lines = []

    provider_label = "Gemini" if provider == "gemini" else "Ollama lokal"
    parser_debug_lines = [
        f"Quelle: AI ({model_label})",
        f"Parser-Modus: {configured_parser_mode()}",
        f"Provider: {provider_label}",
        f"Sollzeit aus Wochentag: {target_label_for_work_date(work_date)}",
        "Gesamtarbeitszeit wird aus Arbeitsblöcken berechnet",
    ]
    if provider == "ollama":
        parser_debug_lines.append("Bildvorbereitung: enger Tabellen-Crop + starke Verkleinerung")
    if display_segments:
        seg_text = ", ".join(f"{item['start']}-{item['end']}" for item in display_segments)
        parser_debug_lines.append(f"Arbeitsblöcke: {seg_text}")
    if rest_override_applied and last_work_end_before_rest:
        parser_debug_lines.append(f"Restpausenabzug-Zeile überschreibt letztes Arbeitsende: {last_work_end_before_rest}")
    parser_debug_lines.extend(hint_lines[:3])

    parser_summary = build_parser_summary(
        work_date=work_date,
        come_time=come_time,
        go_time=go_time,
        system_plusminus_min=system_plusminus_min,
        system_plusminus_found=system_plusminus_found,
        deducted_break_min=deducted_break_min,
        deducted_break_found=deducted_break_found,
        extra_lines=parser_debug_lines,
        work_duration_min=work_duration_min,
        work_duration_found=work_duration_found,
        target_minutes=target_minutes,
    )

    result = {
        "work_date": work_date,
        "come_time": come_time,
        "go_time": go_time,
        "come_time_found": bool(come_time),
        "go_time_found": bool(go_time),
        "work_duration_min": work_duration_min,
        "work_duration_found": work_duration_found,
        "segments": calc_segments,
        "display_segments": display_segments,
        "segments_text": build_segments_text(display_segments),
        "system_plusminus_min": system_plusminus_min,
        "system_plusminus_found": system_plusminus_found,
        "deducted_break_min": deducted_break_min,
        "deducted_break_found": deducted_break_found,
        "parser_debug_lines": parser_debug_lines,
        "parser_summary": parser_summary,
        "ocr_excerpt": raw_text[:5000],
        "confidence": confidence,
    }
    write_debug_text(DEBUG_DIR / f"{debug_base}_parsed_result.json", json.dumps(result, ensure_ascii=False, indent=2))
    return result


def parse_screenshot_with_gemini(path: Path, original_name: str = "") -> dict[str, Any]:
    debug_base = debug_file_base(path)
    image_paths = prepare_ai_images(path, provider="gemini")

    parts: list[dict[str, Any]] = []
    for image_path in image_paths:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": image_to_base64(image_path),
            }
        })

    prompt = """
Analysiere einen Screenshot eines Arbeitszeit-/Stempelsystems.

Das erste Bild zeigt den ganzen Screenshot, das zweite Bild fokussiert den unteren Tabellenbereich.
Wichtige Regeln:
- Relevanter Tag ist nur der aktuelle sichtbare Tag. Obere Reste vom Vortag ignorieren.
- Die Spalte mit Zeitbereichen wie 06:00-20:00 immer ignorieren.
- Arbeitsblöcke müssen in zeitlicher Reihenfolge zurückgegeben werden.
- erster Beginn = kommt, letztes Ende aus der oberen Hauptzeile = geht.
- Gib für jeden erkannten Arbeitsblock nur Start und Ende zurück.
- Wichtig: segments sollen immer die SICHTBAREN Blöcke aus der oberen Hauptzeile enthalten und NICHT um den Restpausenabzug gekürzt werden.
- Die Gesamtarbeitszeit wird NICHT aus dem Bild abgelesen, sondern später serverseitig aus den Arbeitsblöcken berechnet.
- Lies den sichtbaren Restpausenabzug / Zuschlag separat ab.
- Ganz wichtig: restpausenabzug darf NUR gesetzt werden, wenn im Bild wirklich eine eigene Restpausenabzug-/Zuschlag-Zeile oder ein eigener sichtbarer Rohwert dafür erkennbar ist.
- Wenn nur ein einziger normaler Arbeitsblock sichtbar ist und KEINE eigene Restpausenabzug-Zeile / KEIN eigener Restwert zu sehen ist, dann muss restpausenabzug leer bleiben.
- Die Dauer eines sichtbaren Arbeitsblocks oder die gesamte Arbeitszeit darf NIEMALS als restpausenabzug übernommen werden.
- Wenn unten eine Restpausenabzug-Zeile steht und dort links eine Zeit in Klammern wie (17:55) zu sehen ist, dann ist diese Klammerzeit das echte Ende des letzten Arbeitsblocks vor dem Restpausenabzug.
- Die rechte Zeit derselben unteren Zeile bleibt trotzdem die finale Ausstempelzeit und gehört zu geht.
- In so einem Fall muss letztes_arbeitsende_vor_rest genau die Klammerzeit enthalten, damit die Web-App intern rechnen kann.
- segments selbst bleiben trotzdem beim sichtbaren Ende der oberen Hauptzeile.
- Versuche NICHT, Tagesplus, Tagesminus oder Gesamtarbeitszeit selbst zu berechnen.
- Antworte ausschließlich im geforderten JSON-Schema.

Zusatzregeln für die Ausgabe:
- date soll nach Möglichkeit YYYY-MM-DD sein, alternativ DD.MM.YYYY.
- kommt und geht immer als HH:MM.
- restpausenabzug ist der sichtbare Rohwert aus dem Bild, z. B. 0.30 oder 0:30.
- segments soll Start/Ende je Arbeitsblock enthalten.
- letztes_arbeitsende_vor_rest ist leer, wenn keine Klammerzeit in der Restpausenabzug-Zeile sichtbar ist.
""".strip()
    parts.append({"text": prompt})

    response_schema = {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD oder DD.MM.YYYY oder leer."},
            "kommt": {"type": "string", "description": "HH:MM oder leer."},
            "geht": {"type": "string", "description": "HH:MM oder leer."},
            "restpausenabzug": {"type": "string", "description": "Rohwert aus dem Bild wie 0.30 oder leer."},
            "letztes_arbeitsende_vor_rest": {"type": "string", "description": "Zeit aus Klammern in der Restpausenabzug-Zeile, z. B. 17:55, sonst leer."},
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"}
                    },
                    "required": ["start", "end"]
                }
            },
            "hinweise": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"}
        },
        "required": ["date", "kommt", "geht", "restpausenabzug", "letztes_arbeitsende_vor_rest", "segments", "hinweise", "confidence"]
    }

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": response_schema,
        },
    }
    response = call_gemini_generate(payload)
    raw_text = extract_gemini_text(response)
    model_json = extract_json_block(raw_text)
    return finalize_ai_result(model_json, raw_text, "gemini", configured_gemini_model(), debug_base, original_name)


def parse_screenshot_with_ollama(path: Path, original_name: str = "") -> dict[str, Any]:
    debug_base = debug_file_base(path)
    image_paths = prepare_ai_images(path, provider="ollama")
    images_b64 = [image_to_base64(item) for item in image_paths]
    prompt = """
Analysiere die bereitgestellten komprimierten Ausschnitte eines Arbeitszeit-/Stempelsystems.

Wichtige Regeln:
- Nur der aktuell sichtbare Tag ist relevant. Obere Reste vom Vortag ignorieren.
- Die Spalte mit Zeitbereichen wie 06:00-20:00 immer ignorieren.
- Arbeitsblöcke müssen in zeitlicher Reihenfolge zurückgegeben werden.
- erster Beginn = kommt, letztes Ende aus der oberen Hauptzeile = geht.
- Gib für jeden erkannten Arbeitsblock nur Start und Ende zurück.
- Wichtig: segments sollen immer die SICHTBAREN Blöcke aus der oberen Hauptzeile enthalten und NICHT um den Restpausenabzug gekürzt werden.
- Die Gesamtarbeitszeit wird NICHT aus dem Bild abgelesen, sondern später serverseitig aus den Arbeitsblöcken berechnet.
- Lies den sichtbaren Restpausenabzug / Zuschlag separat ab.
- Ganz wichtig: restpausenabzug darf NUR gesetzt werden, wenn im Bild wirklich eine eigene Restpausenabzug-/Zuschlag-Zeile oder ein eigener sichtbarer Rohwert dafür erkennbar ist.
- Wenn nur ein einziger normaler Arbeitsblock sichtbar ist und KEINE eigene Restpausenabzug-Zeile / KEIN eigener Restwert zu sehen ist, dann muss restpausenabzug leer bleiben.
- Die Dauer eines sichtbaren Arbeitsblocks oder die gesamte Arbeitszeit darf NIEMALS als restpausenabzug übernommen werden.
- Wenn unten eine Restpausenabzug-Zeile steht und dort links eine Zeit in Klammern wie (17:55) zu sehen ist, dann ist diese Klammerzeit das echte Ende des letzten Arbeitsblocks vor dem Restpausenabzug.
- Die rechte Zeit derselben unteren Zeile bleibt trotzdem die finale Ausstempelzeit und gehört zu geht.
- In so einem Fall muss letztes_arbeitsende_vor_rest genau die Klammerzeit enthalten.
- segments selbst bleiben trotzdem beim sichtbaren Ende der oberen Hauptzeile.
- Versuche NICHT, Tagesplus, Tagesminus oder Gesamtarbeitszeit selbst zu berechnen.
- Antworte ausschließlich mit einem JSON-Objekt ohne Zusatztext.

JSON-Schema:
{
  "date": "YYYY-MM-DD oder DD.MM.YYYY oder leer",
  "kommt": "HH:MM oder leer",
  "geht": "HH:MM oder leer",
  "restpausenabzug": "0.30 oder leer",
  "letztes_arbeitsende_vor_rest": "17:55 oder leer",
  "segments": [{"start": "08:42", "end": "15:14"}],
  "hinweise": ["kurz"],
  "confidence": 0.0
}
""".strip()
    payload = {
        "model": configured_ollama_model(),
        "prompt": prompt,
        "images": images_b64,
        "stream": False,
        "options": {"temperature": 0},
    }
    response = call_ollama_generate(payload)
    raw_text = extract_ollama_text(response)
    model_json = extract_json_block(raw_text)
    return finalize_ai_result(model_json, raw_text, "ollama", configured_ollama_model(), debug_base, original_name)




def extract_visual_work_date(path: Path) -> str:
    """Best-effort: Datum nur aus der sichtbaren Tabellenzeile lesen.

    Wichtig: Diese Funktion verändert keine Zeiten, keine Arbeitsblöcke und keinen
    Restpausenabzug. Sie dient ausschließlich als Schutz gegen falsch erkannte Tage.
    """
    candidates: list[tuple[int, str, str]] = []

    def add_candidate(score: int, value: Any, source: str) -> None:
        normalized = normalize_ai_date(value)
        if normalized:
            candidates.append((int(score), normalized, source))

    # Vorhandene lokale Tabellen-Extractor verwenden; diese waren bereits für Zeiten/Tabellenlogik da.
    for score, extractor_name, extractor in [
        (90, "table", extract_table_based_fields),
        (80, "global_table", extract_table_based_fields_global),
    ]:
        try:
            item = extractor(path)
        except Exception:
            item = {}
        if isinstance(item, dict) and item.get("work_date"):
            bonus = 0
            try:
                bonus = min(8, int(item.get("date_score") or 0))
            except Exception:
                bonus = 0
            add_candidate(score + bonus, item.get("work_date"), extractor_name)

    # Fallback: OCR-Zeilen nur für Datum durchsuchen, ohne weitere Werte zu übernehmen.
    try:
        texts = ocr_texts(path)
    except Exception:
        texts = []

    for text in texts[:8]:
        for line in str(text or "").splitlines():
            if not re.search(r"\d{1,2}[./-]\d{1,2}", line):
                continue
            candidate = extract_first_date(line)
            if candidate:
                lower = line.lower()
                bonus = 8 if any(day in lower for day in ["mo", "di", "mi", "do", "fr", "sa", "so"]) else 0
                add_candidate(55 + bonus, candidate, "ocr_line")

    if not candidates:
        return ""

    grouped: dict[str, dict[str, Any]] = {}
    for score, value, source in candidates:
        item = grouped.setdefault(value, {"score": 0, "count": 0, "sources": []})
        item["score"] += int(score)
        item["count"] += 1
        item["sources"].append(source)
    best_value, _ = max(grouped.items(), key=lambda kv: (kv[1]["count"], kv[1]["score"]))
    return best_value



WEEKDAY_ALIASES = {
    "mo": 0, "montag": 0,
    "di": 1, "dienstag": 1,
    "mi": 2, "mittwoch": 2,
    "do": 3, "donnerstag": 3,
    "fr": 4, "freitag": 4,
    "sa": 5, "samstag": 5,
    "so": 6, "sonntag": 6,
}


def _weekday_tokens_from_line(line: str) -> list[int]:
    lower = str(line or "").lower()
    found = []
    for token, weekday in WEEKDAY_ALIASES.items():
        if re.search(rf"\b{re.escape(token)}\\b", lower):
            found.append(weekday)
    return found


def _date_weekday_matches_line(value: str, line: str) -> bool:
    tokens = _weekday_tokens_from_line(line)
    if not tokens:
        return True
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
        return d.weekday() in tokens
    except Exception:
        return False


def _line_contains_date_value(line: str, value: str) -> bool:
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return False
    variants = [
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day}.{d.month:02d}.{d.year}",
        f"{d.day:02d}.{d.month}.{d.year}",
        f"{d.day}.{d.month}.{d.year}",
        f"{d.day:02d}.{d.month:02d}.",
        f"{d.day}.{d.month:02d}.",
        f"{d.day:02d}.{d.month}.",
        f"{d.day}.{d.month}.",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day:02d}-{d.month:02d}-{d.year}",
    ]
    normalized = str(line or "").replace(" ", "")
    return any(v.replace(" ", "") in normalized for v in variants)


def visual_date_has_direct_ocr_support(path: Path, value: str) -> bool:
    if not value:
        return False
    try:
        texts = ocr_texts(path)
    except Exception:
        texts = []
    for text in texts[:12]:
        for line in str(text or "").splitlines():
            if _line_contains_date_value(line, value) and _date_weekday_matches_line(value, line):
                return True
    return False


def add_date_guard_debug(result: dict[str, Any], message: str) -> dict[str, Any]:
    updated = dict(result)
    debug_lines = list(updated.get("parser_debug_lines") or [])
    if message not in debug_lines:
        debug_lines.append(message)
    updated["parser_debug_lines"] = debug_lines
    try:
        updated["parser_summary"] = build_parser_summary(
            work_date=updated.get("work_date"),
            come_time=updated.get("come_time"),
            go_time=updated.get("go_time"),
            system_plusminus_min=int(updated.get("system_plusminus_min") or 0),
            system_plusminus_found=bool(updated.get("system_plusminus_found")),
            deducted_break_min=int(updated.get("deducted_break_min") or 0),
            deducted_break_found=bool(updated.get("deducted_break_found")),
            extra_lines=debug_lines,
            work_duration_min=int(updated.get("work_duration_min") or 0),
            work_duration_found=bool(updated.get("work_duration_found")),
            target_minutes=target_minutes_for_work_date(str(updated.get("work_date") or "")),
        )
    except Exception:
        pass
    return updated


def apply_visual_date_guard_only(result: dict[str, Any], path: Path, original_name: str = "") -> dict[str, Any]:
    """Nur work_date korrigieren; Zeit-/Pausen-/Effektiv-Logik bleibt unverändert.

    v0.3.90: Kein blindes OCR-Überschreiben mehr. Wenn AI und Dateiname
    zusammenpassen, OCR aber etwas anderes meldet, bleibt das AI-Datum.
    OCR darf nur überschreiben, wenn der Wert direkt in der OCR-Zeile gestützt
    wird oder mit dem Dateinamen übereinstimmt.
    """
    visual_date = extract_visual_work_date(path)
    if not visual_date:
        return result

    ai_date = str(result.get("work_date") or "").strip()
    if ai_date == visual_date:
        return result

    filename_date = extract_date_from_filename(original_name or path.name or "")
    visual_supported = visual_date_has_direct_ocr_support(path, visual_date)

    # Typischer Fehlerfall vom 20.05.: OCR/Tabellen-Extractor liest aus Zeiten
    # ein falsches Datum. Wenn AI und Dateiname denselben Tag sagen, nicht überschreiben.
    if ai_date and filename_date and ai_date == filename_date and visual_date != ai_date:
        return add_date_guard_debug(
            result,
            f"Datumskonflikt: AI und Dateiname melden {ai_date}, OCR/Tabellencheck meldete {visual_date}. AI-Datum behalten.",
        )

    # Sicherer Fall: OCR/Tabellencheck und Dateiname sind identisch.
    # Oder: Das OCR-Datum ist direkt in einer OCR-Zeile mit passendem Wochentag gestützt.
    if filename_date and visual_date == filename_date:
        allow_override = True
        reason = f"Datum lokal korrigiert: AI meldete {ai_date or '—'}, OCR/Dateiname {visual_date}."
    elif visual_supported:
        allow_override = True
        reason = f"Datum lokal korrigiert: AI meldete {ai_date or '—'}, sichtbare Tabellenzeile {visual_date}."
    else:
        allow_override = False
        reason = f"Unsicherer Datumskonflikt: AI meldete {ai_date or '—'}, OCR/Tabellencheck {visual_date}. Keine automatische Korrektur."

    if not allow_override:
        return add_date_guard_debug(result, reason)

    corrected = dict(result)
    corrected["work_date"] = visual_date

    # Nur wenn die App ohnehin schon die Arbeitszeit berechnet hat, muss das Tagesplus
    # zum korrigierten Wochentag neu berechnet werden. Zeiten/Segmente/Rest bleiben unverändert.
    if corrected.get("work_duration_found") and corrected.get("work_duration_min") is not None:
        target_minutes = target_minutes_for_work_date(visual_date)
        corrected["system_plusminus_min"] = int(corrected.get("work_duration_min") or 0) - int(target_minutes)
        corrected["system_plusminus_found"] = True

        debug_lines = list(corrected.get("parser_debug_lines") or [])
        if reason not in debug_lines:
            debug_lines.append(reason)
        corrected["parser_debug_lines"] = debug_lines

        corrected["parser_summary"] = build_parser_summary(
            work_date=visual_date,
            come_time=corrected.get("come_time"),
            go_time=corrected.get("go_time"),
            system_plusminus_min=int(corrected.get("system_plusminus_min") or 0),
            system_plusminus_found=bool(corrected.get("system_plusminus_found")),
            deducted_break_min=int(corrected.get("deducted_break_min") or 0),
            deducted_break_found=bool(corrected.get("deducted_break_found")),
            extra_lines=debug_lines,
            work_duration_min=int(corrected.get("work_duration_min") or 0),
            work_duration_found=bool(corrected.get("work_duration_found")),
            target_minutes=target_minutes_for_work_date(visual_date),
        )
    return corrected


def parse_screenshot_with_ai(path: Path, original_name: str = "") -> dict[str, Any]:
    provider = configured_ai_provider()
    if provider == "ollama":
        result = parse_screenshot_with_ollama(path, original_name)
    else:
        result = parse_screenshot_with_gemini(path, original_name)

    # Ausschließlich das Datum wird lokal gegen die sichtbare Tabellenzeile geprüft.
    # Zeiten, Arbeitsblöcke, Pausen-/Restpausenlogik und effektiver Tageswert bleiben wie in v0.3.87.
    result = apply_visual_date_guard_only(result, path, original_name)

    if ai_deducted_break_suspicious(result):
        try:
            ocr_result = parse_screenshot_ocr(path, original_name)
        except Exception:
            ocr_result = {}
        if ocr_result:
            result = override_deducted_break_from_ocr(result, ocr_result)
            result = apply_visual_date_guard_only(result, path, original_name)
    return result




def ai_deducted_break_suspicious(result: dict[str, Any]) -> bool:
    if not result.get("deducted_break_found"):
        return False
    deducted_break_min = int(result.get("deducted_break_min") or 0)
    if deducted_break_min <= 0:
        return False
    display_segments = normalize_ai_segments(result.get("display_segments") or result.get("segments") or [])
    if not display_segments:
        return False
    segment_durations = [segment_minutes(str(item.get("start") or ""), str(item.get("end") or "")) for item in display_segments]
    positive_durations = [value for value in segment_durations if value > 0]
    if deducted_break_min in positive_durations:
        return True
    work_duration_min = int(result.get("work_duration_min") or 0)
    # Extra guard for one-line days: the only block duration / total work duration must never become a rest deduction.
    if len(display_segments) == 1 and work_duration_min > 0 and deducted_break_min == work_duration_min:
        return True
    return False


def override_deducted_break_from_ocr(ai_result: dict[str, Any], ocr_result: dict[str, Any]) -> dict[str, Any]:
    merged = dict(ai_result)
    debug_lines = list(merged.get("parser_debug_lines") or [])
    if ocr_result.get("deducted_break_found"):
        merged["deducted_break_min"] = int(ocr_result.get("deducted_break_min") or 0)
        merged["deducted_break_found"] = True
        debug_lines.append(f"Restpausenabzug aus OCR übernommen: {minutes_hm(int(merged['deducted_break_min']))}")
    else:
        merged["deducted_break_min"] = 0
        merged["deducted_break_found"] = False
        debug_lines.append("Verdächtiger Restpausenabzug verworfen: OCR fand keinen Restpausenabzug.")
    merged["parser_debug_lines"] = debug_lines
    merged["parser_summary"] = build_parser_summary(
        work_date=merged.get("work_date"),
        come_time=merged.get("come_time"),
        go_time=merged.get("go_time"),
        system_plusminus_min=int(merged.get("system_plusminus_min") or 0),
        system_plusminus_found=bool(merged.get("system_plusminus_found")),
        deducted_break_min=int(merged.get("deducted_break_min") or 0),
        deducted_break_found=bool(merged.get("deducted_break_found")),
        extra_lines=debug_lines,
        work_duration_min=int(merged.get("work_duration_min") or 0),
        work_duration_found=bool(merged.get("work_duration_found")),
        target_minutes=target_minutes_for_work_date(str(merged.get("work_date") or "")),
    )
    return merged

def unique_processed_path(original_name: str) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    candidate = PROCESSED_DIR / original_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        new_candidate = PROCESSED_DIR / f"{stem}_{counter}{suffix}"
        if not new_candidate.exists():
            return new_candidate
        counter += 1


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_ocr_text(text: str) -> str:
    cleaned = text.replace("\x0c", "\n")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    cleaned = cleaned.replace("|", " ").replace(";", ":")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def image_variants(path: Path) -> list[Image.Image]:
    source = Image.open(path)
    source = ImageOps.exif_transpose(source).convert("L")
    width, height = source.size
    variants: list[Image.Image] = []

    def prepare(img: Image.Image, threshold: int | None = None, scale: float = 2.2) -> Image.Image:
        work = ImageOps.autocontrast(img)
        work = ImageEnhance.Sharpness(work).enhance(2.0)
        work = ImageEnhance.Contrast(work).enhance(1.5)
        if threshold is not None:
            work = work.point(lambda p: 255 if p > threshold else 0)
        new_size = (max(1, int(work.width * scale)), max(1, int(work.height * scale)))
        work = work.resize(new_size)
        return work.filter(ImageFilter.MedianFilter(size=3))

    variants.append(prepare(source, None))
    variants.append(prepare(source, 170))
    bottom = source.crop((0, int(height * 0.55), width, height))
    variants.append(prepare(bottom, None, 2.5))
    variants.append(prepare(bottom, 165, 2.5))
    tight_bottom = source.crop((0, int(height * 0.68), width, height))
    variants.append(prepare(tight_bottom, None, 3.0))
    variants.append(prepare(tight_bottom, 160, 3.0))
    return variants


def ocr_texts(path: Path) -> list[str]:
    texts: list[str] = []
    configs = ["--oem 3 --psm 6", "--oem 3 --psm 11"]
    for variant in image_variants(path):
        for config in configs:
            try:
                text = pytesseract.image_to_string(variant, lang="deu+eng", config=config)
            except Exception:
                text = ""
            cleaned = normalize_ocr_text(text)
            if cleaned:
                texts.append(cleaned)
    return texts


def detect_table_band(
    path: Path,
    top_ratio: float = 0.74,
    bottom_ratio: float = 0.90,
    left_ratio: float = 0.03,
    right_ratio: float = 0.99,
) -> Image.Image:
    source = Image.open(path)
    source = ImageOps.exif_transpose(source).convert("L")
    width, height = source.size
    crop_left = max(0, min(width - 1, int(width * left_ratio)))
    crop_right = max(crop_left + 1, min(width, int(width * right_ratio)))
    crop_top = max(0, min(height - 1, int(height * top_ratio)))
    crop_bottom = max(crop_top + 1, min(height, int(height * bottom_ratio)))
    return source.crop((crop_left, crop_top, crop_right, crop_bottom))


def prepare_table_band_for_ocr(table_band: Image.Image, threshold: int | None = 170, scale: float = 4) -> Image.Image:
    work = ImageOps.autocontrast(table_band)
    work = ImageEnhance.Contrast(work).enhance(2.0)
    work = ImageEnhance.Sharpness(work).enhance(2.0)
    if threshold is not None:
        work = work.point(lambda p: 255 if p > threshold else 0)
    target_width = max(1, int(round(work.width * float(scale))))
    target_height = max(1, int(round(work.height * float(scale))))
    work = work.resize((target_width, target_height))
    return work.filter(ImageFilter.MedianFilter(size=3))


def table_ocr_tokens(table_band: Image.Image, threshold: int = 170, scale: float = 4, psm: int = 11) -> list[dict[str, Any]]:
    prepared = prepare_table_band_for_ocr(table_band, threshold=threshold, scale=scale)
    raw = pytesseract.image_to_data(
        prepared,
        lang="deu+eng",
        config=f"--oem 3 --psm {psm}",
        output_type=pytesseract.Output.DICT,
    )
    tokens: list[dict[str, Any]] = []
    for idx in range(len(raw.get("text", []))):
        text = str(raw["text"][idx] or "").strip()
        confidence_raw = str(raw["conf"][idx] or "").strip()
        try:
            confidence = float(confidence_raw)
        except ValueError:
            confidence = -1.0
        if not text or confidence < 0:
            continue
        cleaned = (
            text.replace("O", "0")
            .replace("o", "0")
            .replace(",", ".")
            .replace(";", ":")
            .replace("I.", "1.")
            .replace("l.", "1.")
        )
        tokens.append(
            {
                "text": cleaned,
                "raw_text": text,
                "left": int(raw["left"][idx]),
                "top": int(raw["top"][idx]),
                "width": int(raw["width"][idx]),
                "height": int(raw["height"][idx]),
                "conf": confidence,
                "image_width": prepared.width,
                "image_height": prepared.height,
                "psm": psm,
            }
        )
    return tokens


def group_table_lines(tokens: list[dict[str, Any]], y_tolerance: int = 60) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for token in sorted(tokens, key=lambda item: (item["top"], item["left"])):
        center_y = token["top"] + token["height"] / 2
        matched_line: dict[str, Any] | None = None
        for line in lines:
            if abs(center_y - line["center_y"]) <= y_tolerance:
                matched_line = line
                break
        if matched_line is None:
            matched_line = {"center_y": center_y, "tokens": []}
            lines.append(matched_line)
        matched_line["tokens"].append(token)
        positions = [item["top"] + item["height"] / 2 for item in matched_line["tokens"]]
        matched_line["center_y"] = sum(positions) / len(positions)

    for line in lines:
        line["tokens"] = sorted(line["tokens"], key=lambda item: item["left"])
        line["text"] = " ".join(item["text"] for item in line["tokens"])
    return sorted(lines, key=lambda item: item["center_y"])


def token_x_ratio(token: dict[str, Any]) -> float:
    width = max(1, int(token.get("image_width") or 1))
    return float(token["left"]) / float(width)


def token_center_y(token: dict[str, Any]) -> float:
    return float(token["top"]) + float(token["height"]) / 2.0


def candidate_table_crop_variants(path: Path) -> list[dict[str, Any]]:
    source = Image.open(path)
    source = ImageOps.exif_transpose(source).convert("L")
    width, height = source.size
    aspect_ratio = float(width) / float(max(1, height))

    if height <= 260 or aspect_ratio >= 4.5:
        return [
            {"top_ratio": 0.0, "bottom_ratio": 1.0, "threshold": None, "scale": 4, "source": "strip_full_gray"},
            {"top_ratio": 0.0, "bottom_ratio": 1.0, "threshold": 170, "scale": 4, "source": "strip_full_bw"},
            {"top_ratio": 0.0, "bottom_ratio": 1.0, "threshold": 185, "scale": 4, "source": "strip_full_bw185"},
        ]

    return [
        {"top_ratio": 0.022, "bottom_ratio": 0.11, "threshold": None, "scale": 4, "source": "top_022_11_gray"},
        {"top_ratio": 0.022, "bottom_ratio": 0.15, "threshold": None, "scale": 4, "source": "top_022_15_gray"},
        {"top_ratio": 0.028, "bottom_ratio": 0.17, "threshold": None, "scale": 4, "source": "top_028_17_gray"},
        {"top_ratio": 0.028, "bottom_ratio": 0.17, "threshold": 170, "scale": 4, "source": "top_028_17_bw"},
        {"top_ratio": 0.035, "bottom_ratio": 0.20, "threshold": None, "scale": 4, "source": "top_035_20_gray"},
        {"top_ratio": 0.035, "bottom_ratio": 0.20, "threshold": 170, "scale": 4, "source": "top_035_20_bw"},
    ]


def parse_hhmm_or_hdot_minutes(raw: str) -> int | None:
    text = str(raw or "").strip().strip("[]()|,:;")
    if not text:
        return None
    text = text.replace(",", ".")
    sign = -1 if text.startswith("-") else 1
    if text.startswith(("+", "-")):
        text = text[1:]
    if ":" in text:
        hours, minutes = text.split(":", 1)
    elif "." in text:
        hours, minutes = text.split(".", 1)
    else:
        compact = re.sub(r"\D", "", text)
        if compact.isdigit() and 3 <= len(compact) <= 4:
            hours, minutes = compact[:-2], compact[-2:]
        else:
            return None
    hours = re.sub(r"\D.*$", "", hours)
    minutes = re.sub(r"\D.*$", "", minutes)
    if not hours.isdigit() or not minutes.isdigit():
        return None
    return sign * (int(hours) * 60 + int(minutes[:2]))


def parse_work_duration_minutes(raw: str) -> int | None:
    text = str(raw or "").strip().strip("[]()|,:;")
    if not text:
        return None
    text = text.replace(",", ".")
    sign = -1 if text.startswith("-") else 1
    if text.startswith(("+", "-")):
        text = text[1:]
    compact = re.sub(r"[^0-9:.]", "", text)
    if not compact:
        return None
    if re.fullmatch(r"\d{1,2}", compact):
        return sign * int(compact) * 60
    parsed = parse_hhmm_or_hdot_minutes(("-" if sign < 0 else "") + compact)
    return parsed



def prepare_full_image_for_ocr(image: Image.Image, threshold: int | None = 200, scale: float = 2.0) -> Image.Image:
    work = ImageOps.autocontrast(image)
    work = ImageEnhance.Contrast(work).enhance(2.0)
    work = ImageEnhance.Sharpness(work).enhance(2.0)
    if threshold is not None:
        work = work.point(lambda p: 255 if p > threshold else 0)
    target_width = max(1, int(round(work.width * float(scale))))
    target_height = max(1, int(round(work.height * float(scale))))
    work = work.resize((target_width, target_height))
    return work.filter(ImageFilter.MedianFilter(size=3))


def whole_image_ocr_tokens(path: Path, threshold: int | None = 200, scale: float = 2.0, psm: int = 11) -> list[dict[str, Any]]:
    source = Image.open(path)
    source = ImageOps.exif_transpose(source).convert("L")
    prepared = prepare_full_image_for_ocr(source, threshold=threshold, scale=scale)
    raw = pytesseract.image_to_data(
        prepared,
        lang="deu+eng",
        config=f"--oem 3 --psm {psm}",
        output_type=pytesseract.Output.DICT,
    )
    tokens: list[dict[str, Any]] = []
    for idx in range(len(raw.get("text", []))):
        text_value = str(raw["text"][idx] or "").strip()
        confidence_raw = str(raw["conf"][idx] or "").strip()
        try:
            confidence = float(confidence_raw)
        except ValueError:
            confidence = -1.0
        if not text_value or confidence < 0:
            continue
        cleaned = (
            text_value.replace("O", "0")
            .replace("o", "0")
            .replace(",", ".")
            .replace(";", ":")
            .replace("I.", "1.")
            .replace("l.", "1.")
        )
        tokens.append(
            {
                "text": cleaned,
                "raw_text": text_value,
                "left": int(raw["left"][idx]),
                "top": int(raw["top"][idx]),
                "width": int(raw["width"][idx]),
                "height": int(raw["height"][idx]),
                "conf": confidence,
                "image_width": prepared.width,
                "image_height": prepared.height,
                "psm": psm,
                "threshold": threshold if threshold is not None else -1,
                "scale": scale,
            }
        )
    return tokens


def looks_like_rest_label(token_text: str) -> bool:
    cleaned = re.sub(r"[^a-zäöüß]", "", str(token_text or "").lower())
    if not cleaned:
        return False
    return (
        cleaned.startswith("rest")
        or "restpause" in cleaned
        or ("rest" in cleaned and "abzug" in cleaned)
        or ("pause" in cleaned and "abzug" in cleaned)
    )


def extract_table_based_fields_global(path: Path) -> dict[str, Any]:
    date_token_pattern = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}")
    time_token_pattern = re.compile(r"^\(?[0-2]?\d[:.]\d{2}\)?$")
    duration_token_pattern = re.compile(r"^[-+]?(?:\d{1,2}[.:]\d{2}|\d{3,4})[\]\):,.;|!]*$")

    def strip_token(token_text: str) -> str:
        return str(token_text or "").strip().strip("[]|()")

    def normalized(token_text: str) -> str:
        return strip_token(token_text).replace(",", ".")

    def is_parenthesized(token_text: str) -> bool:
        stripped = str(token_text or "").strip()
        return stripped.startswith("(") or stripped.endswith(")")

    def choose_time(candidates: list[dict[str, Any]], prefer: str) -> str:
        filtered = [item for item in candidates if not item.get("parenthesized")]
        pool = filtered or candidates
        if not pool:
            return ""
        pool = sorted(pool, key=lambda item: (item["center_y"], item["x_ratio"], -item["conf"]))
        return pool[0]["value"] if prefer == "first" else pool[-1]["value"]

    def choose_duration(candidates: list[dict[str, Any]], prefer: str = "best") -> str:
        if not candidates:
            return ""
        if prefer == "leftmost":
            ordered = sorted(candidates, key=lambda item: (item["x_ratio"], abs(item["center_y"] - item.get("anchor_y", item["center_y"])), -item["conf"]))
        else:
            ordered = sorted(candidates, key=lambda item: (-item["conf"], abs(item["center_y"] - item.get("anchor_y", item["center_y"])), item["x_ratio"]))
        return ordered[0]["value"]

    variants = [
        {"threshold": 200, "scale": 2.0, "psm": 11, "source": "global_full_200_psm11"},
        {"threshold": 180, "scale": 2.0, "psm": 11, "source": "global_full_180_psm11"},
        {"threshold": None, "scale": 2.0, "psm": 11, "source": "global_full_gray_psm11"},
        {"threshold": 200, "scale": 2.0, "psm": 6, "source": "global_full_200_psm6"},
    ]

    best_result: dict[str, Any] = {}
    best_score = -1

    for variant in variants:
        try:
            tokens = whole_image_ocr_tokens(path, threshold=variant["threshold"], scale=variant["scale"], psm=variant["psm"])
        except Exception:
            tokens = []
        if not tokens:
            continue

        avg_height = sum(int(token["height"]) for token in tokens) / max(1, len(tokens))
        line_y_tolerance = max(20, int(avg_height * 1.2))
        lines = group_table_lines(tokens, y_tolerance=line_y_tolerance)

        upper_line: dict[str, Any] | None = None
        work_date = ""
        best_line_score = -1

        for line in lines:
            line_text = " ".join(normalized(token["text"]) for token in line["tokens"])
            candidate_date = extract_first_date(line_text)
            if not candidate_date:
                continue
            date_x = min((token_x_ratio(token) for token in line["tokens"] if date_token_pattern.search(normalized(token["text"]))), default=1.0)
            if date_x > 0.20:
                continue

            begin_tokens = [token for token in line["tokens"] if 0.31 <= token_x_ratio(token) <= 0.39 and time_token_pattern.match(normalized(token["text"]))]
            end_tokens = [token for token in line["tokens"] if 0.40 <= token_x_ratio(token) <= 0.50 and time_token_pattern.match(normalized(token["text"]))]
            plus_tokens = [token for token in line["tokens"] if 0.85 <= token_x_ratio(token) <= 0.93 and duration_token_pattern.match(normalized(token["text"]))]
            range_tokens = [token for token in line["tokens"] if 0.20 <= token_x_ratio(token) <= 0.30 and (time_token_pattern.match(normalized(token["text"])) or normalized(token["text"]) == "-")]

            line_score = 4 + (3 if begin_tokens else 0) + (3 if end_tokens else 0) + (3 if plus_tokens else 0) + (1 if range_tokens else 0)
            if line_score > best_line_score:
                best_line_score = line_score
                upper_line = line
                work_date = candidate_date

        if upper_line is None:
            continue

        upper_anchor_y = float(upper_line["center_y"])
        lower_line_candidates = [line for line in lines if upper_anchor_y + avg_height * 0.5 <= float(line["center_y"]) <= upper_anchor_y + avg_height * 4.0]
        lower_line = min(lower_line_candidates, key=lambda line: float(line["center_y"])) if lower_line_candidates else None
        lower_anchor_y = float(lower_line["center_y"]) if lower_line else upper_anchor_y + avg_height * 2.0

        def collect_candidates(
            line_tokens: list[dict[str, Any]],
            x_min: float,
            x_max: float,
            *,
            time_like: bool = False,
            duration_like: bool = False,
            anchor_y: float | None = None,
        ) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for token in line_tokens:
                x_ratio = token_x_ratio(token)
                if x_ratio < x_min or x_ratio > x_max:
                    continue
                value = normalized(token["text"])
                value = value.rstrip(".") if duration_like else value
                if time_like and not time_token_pattern.match(value):
                    continue
                if duration_like and not duration_token_pattern.match(value):
                    continue
                items.append(
                    {
                        "value": value,
                        "x_ratio": x_ratio,
                        "center_y": token_center_y(token),
                        "conf": float(token.get("conf") or 0.0),
                        "parenthesized": is_parenthesized(token.get("raw_text") or token["text"]),
                        "anchor_y": anchor_y if anchor_y is not None else token_center_y(token),
                        "raw_text": token.get("raw_text") or token["text"],
                    }
                )
            return items

        upper_tokens = upper_line["tokens"]
        lower_tokens = lower_line["tokens"] if lower_line else []

        line_window = [
            line
            for line in lines
            if upper_anchor_y - avg_height * 0.6 <= float(line["center_y"]) <= upper_anchor_y + avg_height * 5.6
        ]

        def line_has_signal(line: dict[str, Any]) -> bool:
            for token in line["tokens"]:
                x_ratio = token_x_ratio(token)
                value = normalized(token["text"])
                if 0.30 <= x_ratio <= 0.50 and time_token_pattern.match(value):
                    return True
                if 0.50 <= x_ratio <= 0.56 and parse_work_duration_minutes(value) is not None:
                    return True
                if 0.56 <= x_ratio <= 0.82 and looks_like_rest_label(value):
                    return True
            return False

        relevant_lines = [line for line in sorted(line_window, key=lambda item: float(item["center_y"])) if line_has_signal(line)][:5]
        relevant_tokens = [token for line in relevant_lines for token in line["tokens"]]
        if not relevant_lines:
            relevant_lines = [upper_line] + ([lower_line] if lower_line else [])
            relevant_tokens = [token for line in relevant_lines for token in line["tokens"]]

        begin_candidates = collect_candidates(relevant_tokens, 0.30, 0.39, time_like=True, anchor_y=upper_anchor_y)
        end_candidates = collect_candidates(relevant_tokens, 0.40, 0.50, time_like=True, anchor_y=upper_anchor_y)

        def line_duration_candidates(line_tokens: list[dict[str, Any]], anchor_y: float) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for token in line_tokens:
                x_ratio = token_x_ratio(token)
                if x_ratio < 0.50 or x_ratio > 0.56:
                    continue
                value = normalized(token["text"]).rstrip(".")
                parsed = parse_work_duration_minutes(value)
                if parsed is None or parsed < 0 or parsed > 16 * 60:
                    continue
                items.append(
                    {
                        "value": value,
                        "minutes": parsed,
                        "x_ratio": x_ratio,
                        "center_y": token_center_y(token),
                        "conf": float(token.get("conf") or 0.0),
                        "anchor_y": anchor_y,
                    }
                )
            return items

        work_duration_sum_min = 0
        restpausenabzug_min = 0
        work_duration_tokens: list[str] = []
        rest_tokens_raw: list[str] = []
        rest_label_present = False
        for line in relevant_lines:
            anchor_y = float(line["center_y"])
            lower_text = " ".join(normalized(token["text"]) for token in line["tokens"]).lower()
            rest_label_tokens = [
                token
                for token in line["tokens"]
                if 0.56 <= token_x_ratio(token) <= 0.82 and looks_like_rest_label(normalized(token["text"]))
            ]
            is_rest_line = bool(rest_label_tokens) or "rest" in lower_text
            duration_candidates = line_duration_candidates(line["tokens"], anchor_y)
            chosen_duration = choose_duration(duration_candidates, prefer="leftmost") if duration_candidates else ""
            chosen_minutes = int(parse_work_duration_minutes(chosen_duration) or 0) if chosen_duration else 0
            if is_rest_line:
                rest_label_present = True
                if chosen_minutes > 0:
                    restpausenabzug_min += chosen_minutes
                    rest_tokens_raw.append(chosen_duration)
            else:
                if chosen_minutes > 0:
                    work_duration_sum_min += chosen_minutes
                    work_duration_tokens.append(chosen_duration)

        come_time = choose_time(begin_candidates, "first")
        go_time = choose_time(end_candidates, "last")
        system_plusminus_found = work_duration_sum_min > 0
        deducted_break_found = restpausenabzug_min > 0
        target_minutes = target_minutes_for_work_date(work_date)
        system_plusminus_min = work_duration_sum_min - target_minutes if system_plusminus_found else 0

        work_duration_debug = ", ".join(work_duration_tokens) if work_duration_tokens else "—"
        rest_token = ", ".join(rest_tokens_raw) if rest_tokens_raw else ""
        debug_upper = f"Beginn={come_time or '—'}, Ende={go_time or '—'}, Arbeitszeiten Spalte 9={work_duration_debug}"
        debug_lower = f"Restwerte Spalte 9={rest_token or '—'}, Label={'ja' if rest_label_present else 'nein'}"
        relevant_tokens = [
            token["text"]
            for token in sorted(tokens, key=lambda item: (item["top"], item["left"]))
            if upper_anchor_y - avg_height * 2.0 <= token_center_y(token) <= lower_anchor_y + avg_height * 2.0
        ]

        score = 0
        score += 3 if work_date else 0
        score += 3 if come_time else 0
        score += 3 if go_time else 0
        score += 3 if system_plusminus_found else 0
        score += 3 if restpausenabzug_min else 0
        score += 2 if rest_label_present else 0

        parser_debug_lines = [
            f"Quelle: {variant.get('source', 'global')}",
            debug_upper,
            debug_lower,
        ]
        parser_summary = build_parser_summary(
            work_date=work_date,
            come_time=come_time,
            go_time=go_time,
            system_plusminus_min=system_plusminus_min,
            system_plusminus_found=system_plusminus_found,
            deducted_break_min=restpausenabzug_min,
            deducted_break_found=deducted_break_found,
            extra_lines=parser_debug_lines,
        )

        result = {
            "work_date": work_date,
            "come_time": come_time,
            "go_time": go_time,
            "come_time_found": bool(come_time),
            "go_time_found": bool(go_time),
            "system_plusminus_min": system_plusminus_min,
            "system_plusminus_found": system_plusminus_found,
            "deducted_break_min": restpausenabzug_min,
            "deducted_break_found": deducted_break_found,
            "parser_summary": parser_summary,
            "parser_debug_lines": parser_debug_lines,
            "ocr_excerpt": " ".join(relevant_tokens)[:5000],
            "confidence": score,
        }
        if score > best_score:
            best_result = result
            best_score = score

    return best_result


def extract_table_based_fields(path: Path) -> dict[str, Any]:
    date_token_pattern = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}")
    time_token_pattern = re.compile(r"^\(?[0-2]?\d[:.]\d{2}\)?$")

    def strip_token(token_text: str) -> str:
        return str(token_text or "").strip().strip("[]|()")

    def normalized(token_text: str) -> str:
        return strip_token(token_text).replace(",", ".")

    def is_parenthesized(token_text: str) -> bool:
        stripped = str(token_text or "").strip()
        return stripped.startswith("(") or stripped.endswith(")")

    def choose_time(candidates: list[dict[str, Any]], prefer: str) -> str:
        filtered = [item for item in candidates if not item.get("parenthesized")]
        pool = filtered or candidates
        if not pool:
            return ""
        pool = sorted(pool, key=lambda item: (item["center_y"], item["x_ratio"], -item["conf"]))
        return pool[0]["value"] if prefer == "first" else pool[-1]["value"]

    def choose_duration(candidates: list[dict[str, Any]]) -> tuple[str, int]:
        if not candidates:
            return "", 0
        ordered = sorted(candidates, key=lambda item: (item["x_ratio"], -item["conf"], item["center_y"]))
        token = ordered[0]
        return str(token["value"]), int(token["minutes"])

    def has_left_date(line: dict[str, Any]) -> tuple[str, float]:
        left_tokens = [token for token in line["tokens"] if token_x_ratio(token) <= 0.22]
        line_text = " ".join(normalized(token["text"]) for token in left_tokens)
        candidate = extract_first_date(line_text)
        if candidate:
            return candidate, min((token_x_ratio(token) for token in left_tokens), default=1.0)
        for token in left_tokens:
            match = date_token_pattern.search(normalized(token["text"]))
            if match:
                candidate = extract_first_date(match.group(0))
                if candidate:
                    return candidate, token_x_ratio(token)
        return "", 1.0

    def collect_candidates(tokens: list[dict[str, Any]], x_min: float, x_max: float, *, time_like: bool = False, duration_like: bool = False) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for token in tokens:
            x_ratio = token_x_ratio(token)
            if x_ratio < x_min or x_ratio > x_max:
                continue
            value = normalized(token["text"])
            if time_like:
                if not time_token_pattern.match(value):
                    continue
                items.append(
                    {
                        "value": value,
                        "x_ratio": x_ratio,
                        "center_y": token_center_y(token),
                        "conf": float(token.get("conf") or 0.0),
                        "parenthesized": is_parenthesized(token.get("raw_text") or token["text"]),
                    }
                )
                continue
            if duration_like:
                parsed = parse_work_duration_minutes(value)
                if parsed is None or parsed < 0 or parsed > 16 * 60:
                    continue
                items.append(
                    {
                        "value": value.rstrip("."),
                        "minutes": parsed,
                        "x_ratio": x_ratio,
                        "center_y": token_center_y(token),
                        "conf": float(token.get("conf") or 0.0),
                    }
                )
        return items

    def to_minutes_of_day(value: str) -> int:
        hours, minutes = str(value).replace('.', ':').split(':', 1)
        return int(hours) * 60 + int(minutes)

    def parse_run(tokens: list[dict[str, Any]], source: str, psm: int) -> dict[str, Any] | None:
        if not tokens:
            return None
        avg_height = sum(int(token["height"]) for token in tokens) / max(1, len(tokens))
        lines = group_table_lines(tokens, y_tolerance=max(28, int(avg_height * 0.9)))
        if not lines:
            return None

        best_date_idx = -1
        best_date = ""
        best_date_score = -1
        for idx, line in enumerate(lines):
            candidate, left_x = has_left_date(line)
            if not candidate or left_x > 0.22:
                continue
            score = 0
            for follow in lines[idx: idx + 6]:
                for token in follow["tokens"]:
                    x_ratio = token_x_ratio(token)
                    value = normalized(token["text"])
                    if 0.29 <= x_ratio <= 0.47 and time_token_pattern.match(value):
                        score += 2
                    if 0.49 <= x_ratio <= 0.58 and parse_work_duration_minutes(value) is not None:
                        score += 1
                    if 0.58 <= x_ratio <= 0.84 and looks_like_rest_label(value):
                        score += 1
            if score > best_date_score:
                best_date_idx = idx
                best_date = candidate
                best_date_score = score

        if best_date_idx < 0:
            best_date_idx = 0

        parsed_rows: list[dict[str, Any]] = []
        for idx in range(best_date_idx, min(len(lines), best_date_idx + 8)):
            line = lines[idx]
            if idx > best_date_idx:
                next_candidate, next_left_x = has_left_date(line)
                if next_candidate and next_left_x <= 0.22:
                    break
            lower_text = " ".join(normalized(token["text"]) for token in line["tokens"]).lower()
            begin_candidates = collect_candidates(line["tokens"], 0.29, 0.40, time_like=True)
            end_candidates = collect_candidates(line["tokens"], 0.40, 0.47, time_like=True)
            duration_candidates = collect_candidates(line["tokens"], 0.49, 0.58, duration_like=True)
            duration_text, duration_min = choose_duration(duration_candidates)
            rest_tokens = [token for token in line["tokens"] if 0.58 <= token_x_ratio(token) <= 0.84 and looks_like_rest_label(normalized(token["text"]))]
            is_rest_line = bool(rest_tokens) or "rest" in lower_text
            if not (begin_candidates or end_candidates or duration_min > 0 or is_rest_line):
                continue
            parsed_rows.append(
                {
                    "begin": choose_time(begin_candidates, "first") if begin_candidates else "",
                    "end": choose_time(end_candidates, "last") if end_candidates else "",
                    "duration": duration_text,
                    "minutes": duration_min,
                    "is_rest": is_rest_line,
                }
            )

        if not parsed_rows:
            return None

        work_rows = [row for row in parsed_rows if not row["is_rest"] and (row["minutes"] > 0 or row["begin"] or row["end"])]
        rest_rows = [row for row in parsed_rows if row["is_rest"]]
        if not work_rows and not rest_rows:
            return None

        come_time = next((str(row["begin"]) for row in work_rows if str(row["begin"])), "")
        go_time = next((str(row["end"]) for row in reversed(work_rows) if str(row["end"])), "")
        work_duration_sum_min = sum(int(row["minutes"]) for row in work_rows if int(row["minutes"]) > 0)
        restpausenabzug_min = sum(int(row["minutes"]) for row in rest_rows if int(row["minutes"]) > 0)
        work_duration_tokens = [str(row["duration"]) for row in work_rows if str(row["duration"])]
        rest_tokens_raw = [str(row["duration"]) for row in rest_rows if str(row["duration"])]
        rest_label_present = bool(rest_rows)

        fit_penalty = 9999
        if come_time and go_time and work_duration_sum_min > 0:
            diff = to_minutes_of_day(go_time) - to_minutes_of_day(come_time)
            if diff >= 0:
                fit_penalty = abs(diff - work_duration_sum_min)

        row_score = 0
        row_score += 4 if come_time else 0
        row_score += 4 if go_time else 0
        row_score += 4 if work_duration_sum_min else 0
        row_score += min(6, len(work_rows) * 2)
        row_score += min(4, sum(1 for row in work_rows if row["begin"]) * 2)
        row_score += min(4, sum(1 for row in work_rows if row["end"]) * 2)
        row_score += 2 if rest_label_present else 0

        return {
            "source": f"{source}_psm{psm}",
            "work_date": best_date,
            "date_score": best_date_score,
            "come_time": come_time,
            "go_time": go_time,
            "come_time_found": bool(come_time),
            "go_time_found": bool(go_time),
            "work_duration_sum_min": work_duration_sum_min,
            "restpausenabzug_min": restpausenabzug_min,
            "system_plusminus_found": work_duration_sum_min > 0,
            "deducted_break_found": restpausenabzug_min > 0,
            "fit_penalty": fit_penalty,
            "row_score": row_score,
            "parsed_rows": parsed_rows,
            "work_duration_tokens": work_duration_tokens,
            "rest_tokens_raw": rest_tokens_raw,
            "rest_label_present": rest_label_present,
        }

    def merged_variant_result(run_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not run_candidates:
            return None
        best_row = max(
            run_candidates,
            key=lambda item: (
                int(item.get("row_score") or 0),
                -int(item.get("fit_penalty") or 9999),
                int(bool(item.get("go_time"))),
                int(bool(item.get("come_time"))),
                int(bool(str(item.get("source") or "").endswith("psm11"))),
            ),
        )
        best_date = max(run_candidates, key=lambda item: (int(bool(item.get("work_date"))), int(item.get("date_score") or 0), int(item.get("row_score") or 0)))
        merged = dict(best_row)
        if not merged.get("work_date") and best_date.get("work_date"):
            merged["work_date"] = best_date.get("work_date")
        def supplement_fit(item: dict[str, Any]) -> int:
            come = str(item.get("come_time") or "")
            go = str(item.get("go_time") or "")
            target_sum = int(merged.get("work_duration_sum_min") or item.get("work_duration_sum_min") or 0)
            if not come or not go or target_sum <= 0:
                return 9999
            try:
                return abs(to_minutes_of_day(go) - to_minutes_of_day(come) - target_sum)
            except Exception:
                return 9999

        time_supplement = max(
            run_candidates,
            key=lambda item: (
                int(bool(item.get("come_time"))) + int(bool(item.get("go_time"))),
                -supplement_fit(item),
                int(bool(str(item.get("source") or "").endswith("psm11"))),
                int(item.get("row_score") or 0),
            ),
        )
        if (not merged.get("come_time")) and time_supplement.get("come_time"):
            merged["come_time"] = time_supplement.get("come_time")
            merged["come_time_found"] = True
        if (not merged.get("go_time")) and time_supplement.get("go_time"):
            merged["go_time"] = time_supplement.get("go_time")
            merged["go_time_found"] = True
        if (
            time_supplement.get("come_time")
            and time_supplement.get("go_time")
            and int(time_supplement.get("fit_penalty") or 9999 ) <= int(merged.get("fit_penalty") or 9999)
        ):
            merged["come_time"] = time_supplement.get("come_time")
            merged["go_time"] = time_supplement.get("go_time")
            merged["come_time_found"] = True
            merged["go_time_found"] = True

        rest_supplement = max(run_candidates, key=lambda item: (int(item.get("restpausenabzug_min") or 0), int(item.get("row_score") or 0)))
        if int(rest_supplement.get("restpausenabzug_min") or 0) > int(merged.get("restpausenabzug_min") or 0):
            merged["restpausenabzug_min"] = int(rest_supplement.get("restpausenabzug_min") or 0)
            merged["deducted_break_found"] = bool(rest_supplement.get("deducted_break_found"))
            merged["rest_tokens_raw"] = list(rest_supplement.get("rest_tokens_raw") or [])
            merged["rest_label_present"] = bool(rest_supplement.get("rest_label_present"))
        target_minutes = target_minutes_for_work_date(str(merged.get("work_date") or ""))
        system_plusminus_min = int(merged.get("work_duration_sum_min") or 0) - target_minutes if merged.get("system_plusminus_found") else 0
        work_duration_debug = ", ".join(str(item) for item in merged.get("work_duration_tokens") or []) or "—"
        rest_debug = ", ".join(str(item) for item in merged.get("rest_tokens_raw") or []) or "—"
        parser_debug_lines = [
            f"Quelle: {merged.get('source') or 'crop'}",
            f"Beginn={merged.get('come_time') or '—'}, Ende={merged.get('go_time') or '—'}, Arbeitszeiten Spalte 9={work_duration_debug}",
            f"Restwerte Spalte 9={rest_debug}, Label={'ja' if merged.get('rest_label_present') else 'nein'}",
        ]
        for idx, row in enumerate(list(merged.get("parsed_rows") or [])[:8], start=1):
            parser_debug_lines.append(
                f"Zeile {idx}: Beginn={row.get('begin') or '—'}, Ende={row.get('end') or '—'}, Spalte9={row.get('duration') or '—'}, Rest={'ja' if row.get('is_rest') else 'nein'}"
            )
        parser_summary = build_parser_summary(
            work_date=merged.get("work_date"),
            come_time=merged.get("come_time"),
            go_time=merged.get("go_time"),
            system_plusminus_min=system_plusminus_min,
            system_plusminus_found=bool(merged.get("system_plusminus_found")),
            deducted_break_min=int(merged.get("restpausenabzug_min") or 0),
            deducted_break_found=bool(merged.get("deducted_break_found")),
            extra_lines=parser_debug_lines,
        )
        confidence = int(merged.get("row_score") or 0) + min(4, int(merged.get("date_score") or 0))
        if str(merged.get("source") or "").startswith("strip_"):
            confidence += 2
        return {
            "work_date": merged.get("work_date") or "",
            "come_time": merged.get("come_time") or "",
            "go_time": merged.get("go_time") or "",
            "come_time_found": bool(merged.get("come_time")),
            "go_time_found": bool(merged.get("go_time")),
            "system_plusminus_min": system_plusminus_min,
            "system_plusminus_found": bool(merged.get("system_plusminus_found")),
            "deducted_break_min": int(merged.get("restpausenabzug_min") or 0),
            "deducted_break_found": bool(merged.get("deducted_break_found")),
            "parser_summary": parser_summary,
            "parser_debug_lines": parser_debug_lines,
            "ocr_excerpt": "",
            "confidence": confidence,
        }

    best_result: dict[str, Any] = {}
    best_score = -1
    for variant in candidate_table_crop_variants(path):
        table_band = detect_table_band(path, top_ratio=variant["top_ratio"], bottom_ratio=variant["bottom_ratio"])
        run_candidates: list[dict[str, Any]] = []
        for psm in (6, 11):
            tokens = table_ocr_tokens(table_band, threshold=variant["threshold"], scale=variant["scale"], psm=psm)
            run_result = parse_run(tokens, str(variant.get("source") or "crop"), psm)
            if run_result:
                run_candidates.append(run_result)
        merged = merged_variant_result(run_candidates)
        if not merged:
            continue
        score = int(merged.get("confidence") or 0)
        if score > best_score:
            best_result = merged
            best_score = score
    return best_result


def extract_first_date(text: str) -> str | None:
    for day, month, year in re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", text):
        try:
            year_i = int(year)
            if year_i < 100:
                year_i += 2000
            return date(year_i, int(month), int(day)).isoformat()
        except ValueError:
            continue
    for day, month in re.findall(r"\b(\d{1,2})[./-](\d{1,2})\b", text):
        try:
            return date(date.today().year, int(month), int(day)).isoformat()
        except ValueError:
            continue
    return None


def extract_date_from_filename(name: str) -> str | None:
    patterns = [
        r"(20\d{2})[-_](\d{2})[-_](\d{2})",
        r"(20\d{2})(\d{2})(\d{2})",
        r"(\d{2})[-_](\d{2})[-_](20\d{2})",
        r"(\d{2})(\d{2})(20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if not match:
            continue
        a, b, c = match.groups()
        if len(a) == 4:
            year, month, day = int(a), int(b), int(c)
        else:
            day, month, year = int(a), int(b), int(c)
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def extract_times_from_texts(texts: list[str]) -> list[str]:
    keyword_lines: list[str] = []
    for text in texts:
        for line in text.splitlines():
            lower = line.lower()
            if any(keyword in lower for keyword in ["kommen", "gehen", "von", "bis", "start", "ende"]):
                keyword_lines.append(line)

    def parse_lines(lines: list[str]) -> list[str]:
        times: list[str] = []
        for line in lines:
            cleaned = re.sub(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", " ", line)
            matches = re.findall(r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)", cleaned)
            for hours, minutes in matches:
                value = f"{int(hours):02d}:{minutes}"
                if value not in times:
                    times.append(value)
        return times

    times = parse_lines(keyword_lines)
    if len(times) >= 2:
        return times
    return parse_lines(texts)


def fallback_main_times_from_texts(
    texts: list[str],
    *,
    work_date: str = "",
    existing_come: str = "",
    existing_go: str = "",
    work_duration_min: int | None = None,
) -> tuple[str, str]:
    times = extract_times_from_texts(texts)
    cleaned: list[str] = []
    for value in times:
        normalized_value = str(value or '').strip()
        if re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", normalized_value) and normalized_value not in cleaned:
            cleaned.append(normalized_value)

    def date_like_time(value: str) -> bool:
        if not work_date:
            return False
        try:
            d = datetime.strptime(str(work_date), "%Y-%m-%d").date()
        except ValueError:
            return False
        return value == f"{d.day:02d}:{d.month:02d}" or value == f"{d.month:02d}:{d.day:02d}"

    if len(cleaned) > 2 and '06:00' in cleaned and '20:00' in cleaned:
        cleaned = [value for value in cleaned if value not in {'06:00', '20:00'}] or cleaned

    comparable = [value for value in cleaned if not date_like_time(value)] or cleaned

    def to_minutes(value: str) -> int:
        hours, minutes = value.split(':', 1)
        return int(hours) * 60 + int(minutes)

    def interval_valid(come: str, go: str) -> bool:
        if not come or not go:
            return True
        diff = to_minutes(go) - to_minutes(come)
        if diff < 0:
            return False
        if work_duration_min is None:
            return True
        return diff >= int(work_duration_min)

    if existing_go and not existing_come:
        candidates = [value for value in comparable if to_minutes(value) <= to_minutes(existing_go) and interval_valid(value, existing_go)]
        if candidates:
            return min(candidates, key=to_minutes), existing_go
    if existing_come and not existing_go:
        candidates = [value for value in comparable if to_minutes(value) >= to_minutes(existing_come) and interval_valid(existing_come, value)]
        if candidates:
            return existing_come, max(candidates, key=to_minutes)

    valid_pairs: list[tuple[str, str]] = []
    for i, come in enumerate(comparable):
        for go in comparable[i + 1:]:
            if interval_valid(come, go):
                valid_pairs.append((come, go))
    if valid_pairs:
        if work_duration_min is not None:
            valid_pairs.sort(key=lambda pair: (to_minutes(pair[1]) - to_minutes(pair[0]) - int(work_duration_min), to_minutes(pair[0])))
            return valid_pairs[0]
        return valid_pairs[0][0], valid_pairs[-1][1]

    if len(comparable) >= 2:
        return comparable[0], comparable[-1]
    return '', ''


def duration_candidates(text: str) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    for match in re.finditer(r"([+-]?\s*\d{1,2}:\d{2})", text):
        token = match.group(1).replace(" ", "")
        candidates.append((parse_minutes(token), token))
    for match in re.finditer(r"([+-]?\s*\d{1,3})\s*min", text, flags=re.IGNORECASE):
        token = match.group(1).replace(" ", "")
        candidates.append((parse_minutes(token), token + " min"))
    return candidates


def extract_by_keywords(texts: list[str], keywords: list[str], signed_required: bool | None = None) -> int | None:
    for text in texts:
        for line in text.splitlines():
            lower = line.lower()
            if not any(keyword in lower for keyword in keywords):
                continue
            for value, token in duration_candidates(line):
                if signed_required is True and not token.strip().startswith(("+", "-")):
                    continue
                if signed_required is False and token.strip().startswith(("+", "-")):
                    continue
                return value
    return None


def parse_screenshot_ocr(path: Path, original_name: str = "") -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    def field_count(item: dict[str, Any] | None) -> int:
        item = item or {}
        count = 0
        if item.get("work_date"):
            count += 1
        if item.get("come_time_found") or item.get("come_time"):
            count += 1
        if item.get("go_time_found") or item.get("go_time"):
            count += 1
        if item.get("system_plusminus_found"):
            count += 1
        if item.get("deducted_break_found"):
            count += 1
        return count

    def left_columns_are_sufficient(item: dict[str, Any] | None) -> bool:
        item = item or {}
        return bool(
            item.get("work_date")
            and (item.get("come_time_found") or item.get("come_time"))
            and (item.get("go_time_found") or item.get("go_time"))
            and item.get("system_plusminus_found")
        )

    table_based = extract_table_based_fields(path)
    fallback_texts: list[str] | None = None

    def apply_time_fallback(item: dict[str, Any] | None) -> dict[str, Any] | None:
        nonlocal fallback_texts
        if not item:
            return item
        if item.get("come_time") and item.get("go_time"):
            return item
        if fallback_texts is None:
            fallback_texts = ocr_texts(path)
        work_date = str(item.get("work_date") or "")
        work_duration_min = None
        if item.get("system_plusminus_found") and work_date:
            work_duration_min = int(item.get("system_plusminus_min") or 0) + target_minutes_for_work_date(work_date)
            if work_duration_min <= 0:
                work_duration_min = None
        come_fallback, go_fallback = fallback_main_times_from_texts(
            fallback_texts or [],
            work_date=work_date,
            existing_come=str(item.get("come_time") or ""),
            existing_go=str(item.get("go_time") or ""),
            work_duration_min=work_duration_min,
        )
        if not item.get("come_time") and come_fallback:
            item["come_time"] = come_fallback
            item["come_time_found"] = True
        if not item.get("go_time") and go_fallback:
            item["go_time"] = go_fallback
            item["go_time_found"] = True
        item["parser_summary"] = build_parser_summary(
            work_date=item.get("work_date"),
            come_time=item.get("come_time"),
            go_time=item.get("go_time"),
            system_plusminus_min=int(item.get("system_plusminus_min") or 0),
            system_plusminus_found=bool(item.get("system_plusminus_found")),
            deducted_break_min=int(item.get("deducted_break_min") or 0),
            deducted_break_found=bool(item.get("deducted_break_found")),
            extra_lines=list(item.get("parser_debug_lines") or []),
        )
        return item

    if table_based:
        table_based = apply_time_fallback(table_based)
        if field_count(table_based) >= 5 or left_columns_are_sufficient(table_based):
            if not table_based.get("work_date"):
                table_based["work_date"] = extract_date_from_filename(original_name) or ""
            return table_based
        candidates.append(table_based)

    if field_count(table_based) < 2:
        global_based = extract_table_based_fields_global(path)
        if global_based:
            global_based = apply_time_fallback(global_based)
            if field_count(global_based) >= 5:
                if not global_based.get("work_date"):
                    global_based["work_date"] = extract_date_from_filename(original_name) or ""
                return global_based
            candidates.append(global_based)

    if candidates:
        base = max(candidates, key=field_count)
        supplement = next((item for item in candidates if item is not base), {})
        merged = dict(base or {})
        if not merged.get("work_date") and supplement.get("work_date"):
            merged["work_date"] = supplement.get("work_date")
        if (not merged.get("come_time_found") and not merged.get("come_time")) and supplement.get("come_time"):
            merged["come_time"] = supplement.get("come_time")
            merged["come_time_found"] = bool(supplement.get("come_time_found") or supplement.get("come_time"))
        if (not merged.get("go_time_found") and not merged.get("go_time")) and supplement.get("go_time"):
            merged["go_time"] = supplement.get("go_time")
            merged["go_time_found"] = bool(supplement.get("go_time_found") or supplement.get("go_time"))
        if not merged.get("system_plusminus_found") and supplement.get("system_plusminus_found"):
            merged["system_plusminus_min"] = int(supplement.get("system_plusminus_min") or 0)
            merged["system_plusminus_found"] = True
        if not merged.get("deducted_break_found") and supplement.get("deducted_break_found"):
            merged["deducted_break_min"] = int(supplement.get("deducted_break_min") or 0)
            merged["deducted_break_found"] = True
        merged["confidence"] = max(int(base.get("confidence") or 0), int(supplement.get("confidence") or 0))
        merged["parser_summary"] = build_parser_summary(
            work_date=merged.get("work_date"),
            come_time=merged.get("come_time"),
            go_time=merged.get("go_time"),
            system_plusminus_min=int(merged.get("system_plusminus_min") or 0),
            system_plusminus_found=bool(merged.get("system_plusminus_found")),
            deducted_break_min=int(merged.get("deducted_break_min") or 0),
            deducted_break_found=bool(merged.get("deducted_break_found")),
            extra_lines=list(merged.get("parser_debug_lines") or []),
        )
        merged["ocr_excerpt"] = (str(base.get("ocr_excerpt") or "") + " " + str(supplement.get("ocr_excerpt") or "")).strip()[:5000]
        if not merged.get("work_date"):
            merged["work_date"] = extract_date_from_filename(original_name) or ""
        merged["parser_summary"] = build_parser_summary(
            work_date=merged.get("work_date"),
            come_time=merged.get("come_time"),
            go_time=merged.get("go_time"),
            system_plusminus_min=int(merged.get("system_plusminus_min") or 0),
            system_plusminus_found=bool(merged.get("system_plusminus_found")),
            deducted_break_min=int(merged.get("deducted_break_min") or 0),
            deducted_break_found=bool(merged.get("deducted_break_found")),
            extra_lines=list(merged.get("parser_debug_lines") or []),
        )
        return merged

    texts = ocr_texts(path)
    combined = "\n".join(texts)
    work_date = extract_first_date(combined) or extract_date_from_filename(original_name)
    times = extract_times_from_texts(texts)
    system_plusminus = extract_by_keywords(texts, ["plus", "minus", "saldo", "tag", "tages"], True)
    system_plusminus_found = system_plusminus is not None
    if system_plusminus is None:
        signed_values = [value for value, token in duration_candidates(combined) if token.strip().startswith(("+", "-"))]
        if signed_values:
            system_plusminus = signed_values[0]
            system_plusminus_found = True
        else:
            system_plusminus = 0
    deducted_break = extract_by_keywords(texts, ["pause", "abzug", "abgezogen", "automatisch"], False)
    deducted_break_found = deducted_break is not None
    if deducted_break is None:
        unsigned_values = [value for value, token in duration_candidates(combined) if not token.strip().startswith(("+", "-")) and 0 <= value <= 180]
        if unsigned_values:
            deducted_break = unsigned_values[0]
            deducted_break_found = True
        else:
            deducted_break = 0

    confidence = 0
    if work_date:
        confidence += 1
    if times:
        confidence += 1
    if system_plusminus_found:
        confidence += 1
    if deducted_break_found:
        confidence += 1

    parser_summary = build_parser_summary(
        work_date=work_date,
        come_time=times[0] if len(times) >= 1 else "",
        go_time=times[1] if len(times) >= 2 else "",
        system_plusminus_min=system_plusminus,
        system_plusminus_found=system_plusminus_found,
        deducted_break_min=deducted_break,
        deducted_break_found=deducted_break_found,
        extra_lines=["Quelle: Textfallback"],
    )

    return {
        "work_date": work_date,
        "come_time": times[0] if len(times) >= 1 else "",
        "go_time": times[1] if len(times) >= 2 else "",
        "come_time_found": len(times) >= 1,
        "go_time_found": len(times) >= 2,
        "system_plusminus_min": system_plusminus,
        "system_plusminus_found": system_plusminus_found,
        "deducted_break_min": deducted_break,
        "deducted_break_found": deducted_break_found,
        "parser_summary": parser_summary,
        "ocr_excerpt": combined[:5000],
        "confidence": confidence,
    }


def merge_parser_results(primary: dict[str, Any], supplement: dict[str, Any], note: str) -> dict[str, Any]:
    merged = dict(primary or {})
    supplement = dict(supplement or {})
    for key in ["work_date", "come_time", "go_time"]:
        if not merged.get(key) and supplement.get(key):
            merged[key] = supplement.get(key)
    if not merged.get("come_time_found") and supplement.get("come_time"):
        merged["come_time_found"] = True
    if not merged.get("go_time_found") and supplement.get("go_time"):
        merged["go_time_found"] = True
    if not merged.get("system_plusminus_found") and supplement.get("system_plusminus_found"):
        merged["system_plusminus_found"] = True
        merged["system_plusminus_min"] = int(supplement.get("system_plusminus_min") or 0)
    if not merged.get("deducted_break_found") and supplement.get("deducted_break_found"):
        merged["deducted_break_found"] = True
        merged["deducted_break_min"] = int(supplement.get("deducted_break_min") or 0)
    debug_lines = list(merged.get("parser_debug_lines") or [])
    if note:
        debug_lines.append(note)
    merged["parser_debug_lines"] = debug_lines
    merged["confidence"] = max(int(primary.get("confidence") or 0), int(supplement.get("confidence") or 0))
    merged["parser_summary"] = build_parser_summary(
        work_date=merged.get("work_date"),
        come_time=merged.get("come_time"),
        go_time=merged.get("go_time"),
        system_plusminus_min=int(merged.get("system_plusminus_min") or 0),
        system_plusminus_found=bool(merged.get("system_plusminus_found")),
        deducted_break_min=int(merged.get("deducted_break_min") or 0),
        deducted_break_found=bool(merged.get("deducted_break_found")),
        extra_lines=debug_lines,
    )
    return merged


def parse_screenshot(path: Path, original_name: str = "") -> dict[str, Any]:
    mode = configured_parser_mode()
    ai_result: dict[str, Any] | None = None
    ai_error = ""
    if mode in {"ai", "ai_then_ocr"}:
        try:
            ai_result = parse_screenshot_with_ai(path, original_name)
        except Exception as exc:
            ai_error = str(exc)
            if mode == "ai":
                raise
        else:
            if mode == "ai" or ai_result_is_usable(ai_result):
                return ai_result

    ocr_result = parse_screenshot_ocr(path, original_name)
    debug_lines = list(ocr_result.get("parser_debug_lines") or [])
    if ai_error:
        debug_lines.append(f"AI-Versuch fehlgeschlagen: {ai_error[:220]}")
    elif ai_result:
        ocr_result = merge_parser_results(ocr_result, ai_result, "AI lieferte Zusatzwerte; OCR blieb Hauptquelle.")
        debug_lines = list(ocr_result.get("parser_debug_lines") or [])
    elif mode == "ocr":
        debug_lines.append("Quelle: OCR")
    ocr_result["parser_debug_lines"] = debug_lines
    ocr_result["parser_summary"] = build_parser_summary(
        work_date=ocr_result.get("work_date"),
        come_time=ocr_result.get("come_time"),
        go_time=ocr_result.get("go_time"),
        system_plusminus_min=int(ocr_result.get("system_plusminus_min") or 0),
        system_plusminus_found=bool(ocr_result.get("system_plusminus_found")),
        deducted_break_min=int(ocr_result.get("deducted_break_min") or 0),
        deducted_break_found=bool(ocr_result.get("deducted_break_found")),
        extra_lines=debug_lines,
    )
    return ocr_result



def merge_notes(existing_note: str | None, added: str | None) -> str:
    left = str(existing_note or "").strip()
    right = str(added or "").strip()
    if left and right:
        if right in left:
            return left
        return f"{left}\n{right}"
    return left or right


def delete_import_file(import_item: dict[str, Any]) -> None:
    processed_path = Path(str(import_item.get("processed_path") or ""))
    if processed_path and processed_path.exists():
        processed_path.unlink()


def remove_processed_image_only(conn: sqlite3.Connection, import_row: sqlite3.Row) -> bool:
    import_item = dict(import_row)
    had_path = bool(import_item.get("processed_path"))
    delete_import_file(import_item)
    conn.execute(
        "UPDATE imports SET processed_path = NULL, stored_name = NULL, notes = ? WHERE id = ?",
        (merge_notes(import_item.get("notes"), "Bilddatei wurde manuell gelöscht."), import_row["id"]),
    )
    linked_entry = conn.execute("SELECT id FROM work_entries WHERE import_id = ?", (import_row["id"],)).fetchone()
    if linked_entry is not None:
        conn.execute(
            "UPDATE work_entries SET note = COALESCE(note, '') || CASE WHEN COALESCE(note, '') = '' THEN '' ELSE '\n' END || ?, updated_at = ? WHERE import_id = ?",
            ("Originalbild wurde nach dem Import gelöscht.", now_iso(), import_row["id"]),
        )
    return had_path


def auto_create_or_update_entry(conn: sqlite3.Connection, parsed: dict[str, Any], import_id: int, fallback_date: str, original_name: str) -> tuple[str, str]:
    work_date = parsed.get("work_date") or fallback_date
    weekday = infer_weekday(work_date)
    system_plusminus_found = bool(parsed.get("system_plusminus_found"))
    deducted_break_found = bool(parsed.get("deducted_break_found"))
    system_plusminus_min = int(parsed.get("system_plusminus_min") or 0) if system_plusminus_found else 0
    deducted_break_min = int(parsed.get("deducted_break_min") or 0) if deducted_break_found else 0
    note_add = f"Automatisch importiert aus {original_name}"
    display_segments = parsed.get("display_segments") if isinstance(parsed.get("display_segments"), list) else parsed.get("segments")
    work_segments = normalize_ai_segments(display_segments or [])
    work_segments_text = str(parsed.get("segments_text") or build_segments_text(work_segments) or default_segments_text(parsed.get("come_time"), parsed.get("go_time"))).strip()
    work_segments_json = serialize_segments_json(work_segments) if work_segments else ""
    existing_row = conn.execute("SELECT * FROM work_entries WHERE work_date = ?", (work_date,)).fetchone()
    existing = dict(existing_row) if existing_row is not None else None
    if existing is None:
        manual_correction_min = 0
        imported_rest_component_min = deducted_break_min if deducted_break_found else 0
        carryover_budget_min = compute_carryover_budget(imported_rest_component_min, manual_correction_min)
        effective = compute_effective(system_plusminus_min, deducted_break_min, manual_correction_min)
        conn.execute(
            """
            INSERT INTO work_entries (
                work_date, weekday, come_time, go_time, work_segments_text, work_segments_json, system_plusminus_min, deducted_break_min,
                manual_correction_min, carryover_budget_min, imported_rest_component_min, effective_day_value_min, note, import_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)
            """,
            (
                work_date,
                weekday,
                parsed.get("come_time") or None,
                parsed.get("go_time") or None,
                work_segments_text or None,
                work_segments_json or None,
                system_plusminus_min,
                deducted_break_min,
                manual_correction_min,
                carryover_budget_min,
                imported_rest_component_min,
                effective,
                note_add,
                import_id,
                now_iso(),
                now_iso(),
            ),
        )
        return "parsed", f"Arbeitstag {work_date} automatisch angelegt."

    manual_correction_min = int(existing["manual_correction_min"] or 0)
    old_imported_rest_component_min = int(existing.get("imported_rest_component_min") or 0)
    current_carryover_budget_min = int(existing.get("carryover_budget_min") or 0)
    manual_budget_base = current_carryover_budget_min - old_imported_rest_component_min + abs(manual_correction_min)
    chosen_system_plusminus_min = system_plusminus_min if system_plusminus_found else int(existing.get("system_plusminus_min") or 0)
    # Import re-analysis must be authoritative for restpausenabzug. If the parser now
    # finds no valid imported rest component, previously stored imported values must be cleared.
    imported_rest_component_min = max(0, min(180, deducted_break_min))
    chosen_deducted_break_min = deducted_break_min
    carryover_budget_min = compute_carryover_budget(imported_rest_component_min, manual_correction_min, manual_budget_base)
    effective = compute_effective(chosen_system_plusminus_min, chosen_deducted_break_min, manual_correction_min)
    conn.execute(
        """
        UPDATE work_entries
        SET weekday = ?, come_time = ?, go_time = ?, work_segments_text = ?, work_segments_json = ?, system_plusminus_min = ?, deducted_break_min = ?,
            carryover_budget_min = ?, imported_rest_component_min = ?, effective_day_value_min = ?, note = ?, import_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            weekday,
            parsed.get("come_time") or existing.get("come_time"),
            parsed.get("go_time") or existing.get("go_time"),
            work_segments_text or existing.get("work_segments_text") or default_segments_text(parsed.get("come_time") or existing.get("come_time"), parsed.get("go_time") or existing.get("go_time")) or None,
            work_segments_json or existing.get("work_segments_json") or None,
            chosen_system_plusminus_min,
            chosen_deducted_break_min,
            carryover_budget_min,
            imported_rest_component_min,
            effective,
            merge_notes(existing["note"], note_add),
            import_id,
            now_iso(),
            existing["id"],
        ),
    )
    return "updated_existing", f"Vorhandener Arbeitstag {work_date} automatisch aktualisiert."


def scan_import_dir() -> int:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    imported_count = 0
    with PROCESSING_LOCK:
        with closing(get_db()) as conn:
            for item in sorted(IMPORT_DIR.iterdir(), key=lambda p: p.stat().st_mtime):
                if item.name.startswith(".") or item.is_dir() or item.parent == PROCESSED_DIR:
                    continue
                if item.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                source_hash = file_hash(item)
                existing_by_hash = conn.execute("SELECT id FROM imports WHERE file_hash = ? LIMIT 1", (source_hash,)).fetchone()
                target = unique_processed_path(item.name)
                shutil.move(str(item), str(target))
                imported_at = now_iso()
                cursor = conn.execute(
                    """
                    INSERT INTO imports (original_name, stored_name, source_path, processed_path, file_hash, status, notes, parser_summary, imported_at, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.name,
                        target.name,
                        str(item),
                        str(target),
                        source_hash,
                        "needs_check",
                        "Screenshot übernommen.",
                        "",
                        imported_at,
                        None,
                    ),
                )
                import_id = int(cursor.lastrowid)
                conn.commit()

                if existing_by_hash is not None:
                    conn.execute(
                        "UPDATE imports SET status = ?, notes = ?, parser_summary = ? WHERE id = ?",
                        (
                            "duplicate",
                            "Dateiinhalt bereits bekannt. Kein neuer Tag angelegt.",
                            "Duplikat anhand Dateihash erkannt.",
                            import_id,
                        ),
                    )
                    conn.commit()
                    imported_count += 1
                    continue

                if configured_ai_provider() == "gemini" and gemini_in_cooldown():
                    queue_import_for_retry(conn, import_id, f"Gemini-Limit noch {get_gemini_cooldown_remaining()} Sekunden aktiv.", prefix="Automatische Analyse wartet")
                    conn.commit()
                    imported_count += 1
                    continue

                outcome, _ = analyze_import_and_store(
                    conn,
                    import_id,
                    target,
                    item.name,
                    error_prefix="Parserfehler",
                    queue_prefix="Automatische Analyse wartet",
                )
                conn.commit()
                imported_count += 1
                if outcome == "queued" and configured_ai_provider() == "gemini":
                    continue
    return imported_count


def background_scanner() -> None:
    while True:
        try:
            retry_pending_imports()
            scan_import_dir()
        except Exception:
            pass
        time.sleep(max(10, SCAN_INTERVAL_SECONDS))


def start_background_scanner() -> None:
    thread = threading.Thread(target=background_scanner, daemon=True, name="stunden-import-scanner")
    thread.start()


def account_balance() -> dict[str, int]:
    balance_entries_row = query_one("SELECT COALESCE(SUM(system_plusminus_min), 0) AS total FROM work_entries") or {"total": 0}
    catchup_entries_row = query_one("SELECT COALESCE(SUM(carryover_budget_min), 0) AS total FROM work_entries") or {"total": 0}
    balance_tx_row = query_one("SELECT COALESCE(SUM(minutes), 0) AS total FROM account_transactions WHERE COALESCE(kind, 'balance') = 'balance'") or {"total": 0}
    catchup_tx_row = query_one("SELECT COALESCE(SUM(minutes), 0) AS total FROM account_transactions WHERE COALESCE(kind, 'balance') = 'catchup'") or {"total": 0}
    current_balance = int(balance_entries_row["total"] or 0) + int(balance_tx_row["total"] or 0)
    catch_up = int(catchup_entries_row["total"] or 0) + int(catchup_tx_row["total"] or 0)
    total = current_balance + catch_up
    return {
        "entries_total": int(balance_entries_row["total"] or 0),
        "transactions_total": int(balance_tx_row["total"] or 0),
        "carryover_total": int(catchup_entries_row["total"] or 0),
        "carryover_transactions_total": int(catchup_tx_row["total"] or 0),
        "current_balance": current_balance,
        "catch_up": catch_up,
        "total_hours": total,
    }


def catchup_adjustments_by_date(start_date: str, end_date: str) -> dict[str, int]:
    rows = query_all(
        """
        SELECT booking_date, COALESCE(SUM(minutes), 0) AS total
        FROM account_transactions
        WHERE COALESCE(kind, 'balance') = 'catchup' AND booking_date BETWEEN ? AND ?
        GROUP BY booking_date
        """,
        (start_date, end_date),
    )
    return {str(row.get("booking_date") or ""): int(row.get("total") or 0) for row in rows}


def sum_entries_between(start_date: str, end_date: str) -> int:
    row = query_one(
        "SELECT COALESCE(SUM(effective_day_value_min), 0) AS total FROM work_entries WHERE work_date BETWEEN ? AND ?",
        (start_date, end_date),
    )
    return int((row or {}).get("total") or 0)


def current_week_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def upcoming_week_bounds(today: date | None = None) -> tuple[date, date]:
    start, _ = current_week_bounds(today)
    next_start = start + timedelta(days=7)
    return next_start, next_start + timedelta(days=6)


def week_bounds_for_preset(preset: str, today: date | None = None) -> tuple[date, date]:
    preset = str(preset or '').strip().lower()
    if preset == 'next_week':
        return upcoming_week_bounds(today)
    if preset == 'last_week':
        start, _ = current_week_bounds(today)
        prev_start = start - timedelta(days=7)
        return prev_start, prev_start + timedelta(days=6)
    return current_week_bounds(today)


def monday_for_iso(iso_text: str) -> date:
    day = datetime.strptime(iso_text, "%Y-%m-%d").date()
    return day - timedelta(days=day.weekday())


def resolve_plan_week(request_args: Any, request_form: Any) -> tuple[str, date, date]:
    custom_week_start = str(request_args.get("week_start") or request_form.get("week_start") or "").strip()
    if custom_week_start:
        try:
            start = monday_for_iso(custom_week_start)
            return "custom", start, start + timedelta(days=6)
        except Exception:
            pass
    active_preset = str(request_args.get("preset") or request_form.get("week_preset") or "next_week").strip().lower()
    if active_preset not in {"current_week", "next_week"}:
        active_preset = "next_week"
    start, end = week_bounds_for_preset(active_preset)
    return active_preset, start, end


def future_plan_week_buttons() -> list[dict[str, str]]:
    next_start, _ = upcoming_week_bounds()
    rows = query_all("SELECT DISTINCT plan_date FROM plans WHERE plan_date IS NOT NULL ORDER BY plan_date ASC")
    seen: set[str] = set()
    buttons: list[dict[str, str]] = []
    for row in rows:
        plan_date = str(row.get("plan_date") or "").strip()
        if not plan_date:
            continue
        week_start = monday_for_iso(plan_date)
        if week_start <= next_start:
            continue
        start_iso = week_start.isoformat()
        if start_iso in seen:
            continue
        seen.add(start_iso)
        buttons.append({"week_start": start_iso, "label": f"Woche ab {week_start.strftime('%d.%m.')}"})
    return buttons


def display_catchup_for_entry(entry: dict[str, Any] | None, date_adjustment_min: int = 0) -> int:
    if entry is None:
        return int(date_adjustment_min or 0)
    manual_correction_min = abs(int(entry.get("manual_correction_min") or 0))
    if manual_correction_min > 0:
        return -manual_correction_min
    return int(date_adjustment_min or 0)


def adjusted_effective_for_entry(entry: dict[str, Any] | None, date_adjustment_min: int = 0) -> int:
    if entry is None:
        return int(date_adjustment_min or 0)
    # Immer aus den Einzelwerten neu berechnen, damit Dashboard, Formular und Push
    # denselben finalen Wert zeigen. Das ist besonders wichtig, wenn Telegram-Nachlauf
    # kurz nach dem Import eingetragen wird.
    manual_correction_min = abs(int(entry.get("manual_correction_min") or 0))
    base_effective = compute_effective(
        int(entry.get("system_plusminus_min") or 0),
        int(entry.get("deducted_break_min") or 0),
        manual_correction_min,
    )
    if manual_correction_min > 0:
        return base_effective
    return base_effective + int(date_adjustment_min or 0)


def weekly_forecast_for_range(start_iso: str, end_iso: str) -> dict[str, int]:
    entries = query_all(
        "SELECT * FROM work_entries WHERE work_date BETWEEN ? AND ?",
        (start_iso, end_iso),
    )
    catchup_adjustments = catchup_adjustments_by_date(start_iso, end_iso)
    actual_adjusted = sum(
        adjusted_effective_for_entry(entry, int(catchup_adjustments.get(str(entry.get("work_date") or ""), 0) or 0))
        for entry in entries
    )
    row = query_one(
        """
        SELECT COALESCE(SUM(p.expected_result_min), 0) AS total
        FROM plans p
        LEFT JOIN work_entries w ON w.work_date = p.plan_date
        WHERE p.plan_date BETWEEN ? AND ? AND w.id IS NULL
        """,
        (start_iso, end_iso),
    )
    planned_total = int((row or {}).get('total') or 0)
    return {"actual": actual_adjusted, "planned_total": planned_total, "forecast": actual_adjusted + planned_total}


def weekly_forecast() -> dict[str, int]:
    start, end = current_week_bounds()
    return weekly_forecast_for_range(start.isoformat(), end.isoformat())


def current_week_cards() -> list[dict[str, Any]]:
    start, _ = current_week_bounds()
    days = [start + timedelta(days=i) for i in range(5)]
    start_iso = days[0].isoformat()
    end_iso = days[-1].isoformat()
    entries = query_all("SELECT * FROM work_entries WHERE work_date BETWEEN ? AND ?", (start_iso, end_iso))
    plans = query_all("SELECT * FROM plans WHERE plan_date BETWEEN ? AND ?", (start_iso, end_iso))
    catchup_adjustments = catchup_adjustments_by_date(start_iso, end_iso)
    import_ids = [int(item.get('import_id') or 0) for item in entries if int(item.get('import_id') or 0) > 0]
    parser_summary_by_import: dict[int, str] = {}
    if import_ids:
        placeholders = ",".join("?" for _ in import_ids)
        imported_rows = query_all(f"SELECT id, parser_summary FROM imports WHERE id IN ({placeholders})", tuple(import_ids))
        parser_summary_by_import = {int(row['id']): str(row.get('parser_summary') or '') for row in imported_rows}
    entry_map = {item["work_date"]: item for item in entries}
    plan_map = {item["plan_date"]: item for item in plans}
    cards: list[dict[str, Any]] = []
    for day in days:
        iso = day.isoformat()
        entry = entry_map.get(iso)
        plan = plan_map.get(iso)
        catchup_adjustment = int(catchup_adjustments.get(iso) or 0)
        display_catchup = display_catchup_for_entry(entry, catchup_adjustment)
        adjusted_effective = None
        if entry is not None:
            adjusted_effective = adjusted_effective_for_entry(entry, catchup_adjustment)
        work_time_text = ""
        if entry is not None:
            parser_summary = parser_summary_by_import.get(int(entry.get('import_id') or 0), '')
            work_time_text = preferred_work_time_text(entry, parser_summary)
        if plan is not None:
            plan["plan_time_text"] = preferred_plan_time_text(plan)
        cards.append({
            "date": iso,
            "weekday_short": ["Mo", "Di", "Mi", "Do", "Fr"][day.weekday()],
            "display_date": day.strftime("%d.%m.%Y"),
            "target_label": target_label_for_work_date(iso),
            "entry": entry,
            "plan": plan,
            "catchup_adjustment": catchup_adjustment,
            "display_catchup": display_catchup,
            "adjusted_effective": adjusted_effective,
            "work_time_text": work_time_text,
        })
    return cards


def dashboard_metrics() -> dict[str, int]:
    balance = account_balance()
    week = weekly_forecast()
    return {
        "week_actual": week["actual"],
        "week_forecast": week["forecast"],
        **balance,
    }


def default_entry_form(entry: dict[str, Any] | None = None) -> dict[str, Any]:
    if entry:
        segments = preferred_segments(entry)
        form = {
            "work_date": entry.get("work_date", ""),
            "weekday": entry.get("weekday", ""),
            "come_time": entry.get("come_time") or "",
            "go_time": entry.get("go_time") or "",
            "system_plusminus": minutes_hm(entry.get("system_plusminus_min", 0)) if int(entry.get("system_plusminus_min", 0) or 0) else "0",
            "deducted_break": minutes_hm(entry.get("deducted_break_min", 0)) if int(entry.get("deducted_break_min", 0) or 0) else "0",
            "manual_correction": minutes_hm(-abs(int(entry.get("manual_correction_min", 0) or 0))) if int(entry.get("manual_correction_min", 0) or 0) else "0",
            "carryover_budget": minutes_hm(entry.get("carryover_budget_min", 0)) if int(entry.get("carryover_budget_min", 0) or 0) else "0",
            "note": entry.get("note") or "",
        }
        for idx in range(1, 5):
            form[f"segment{idx}_start"] = ""
            form[f"segment{idx}_end"] = ""
        for idx, seg in enumerate(segments[:4], start=1):
            form[f"segment{idx}_start"] = seg.get("start", "")
            form[f"segment{idx}_end"] = seg.get("end", "")
        return form
    today = date.today().isoformat()
    form = {
        "work_date": today,
        "weekday": infer_weekday(today),
        "come_time": "",
        "go_time": "",
        "system_plusminus": "0",
        "deducted_break": "0",
        "manual_correction": "0",
        "carryover_budget": "0",
        "note": "",
    }
    for idx in range(1, 5):
        form[f"segment{idx}_start"] = ""
        form[f"segment{idx}_end"] = ""
    return form


def default_plan_form(plan: dict[str, Any] | None = None, preset: str = "next_week", week_start: str | None = None) -> dict[str, Any]:
    if plan:
        form = {
            "plan_date": plan.get("plan_date", ""),
            "planned_start": plan.get("planned_start") or "",
            "planned_end": plan.get("planned_end") or "",
            "planned_break": str(plan.get("planned_break_min", 0)),
            "expected_result": minutes_hm(plan.get("expected_result_min", 0)) if int(plan.get("expected_result_min", 0) or 0) else "0",
            "note": plan.get("note") or "",
            "week_preset": preset,
            "week_start": week_start or "",
        }
        for idx in range(1, 5):
            form[f"planned_segment{idx}_start"] = ""
            form[f"planned_segment{idx}_end"] = ""
        for idx, seg in enumerate(preferred_plan_segments(plan)[:4], start=1):
            form[f"planned_segment{idx}_start"] = seg.get("start", "")
            form[f"planned_segment{idx}_end"] = seg.get("end", "")
        return form
    if week_start:
        start = monday_for_iso(week_start)
    else:
        start, _ = week_bounds_for_preset(preset)
    default_date = start
    if preset == "current_week":
        today = date.today()
        if start <= today <= start + timedelta(days=4):
            default_date = today
    form = {
        "plan_date": default_date.isoformat(),
        "planned_start": "08:00",
        "planned_end": "16:00",
        "planned_break": "0",
        "expected_result": "0",
        "note": "",
        "week_preset": preset,
        "week_start": week_start or "",
    }
    for idx in range(1,5):
        form[f"planned_segment{idx}_start"] = ""
        form[f"planned_segment{idx}_end"] = ""
    form["planned_segment1_start"] = "08:00"
    form["planned_segment1_end"] = "16:00"
    return form


def default_account_form(tx: dict[str, Any] | None = None, kind: str | None = None) -> dict[str, Any]:
    kind = str(kind or (tx.get("kind") if tx else "balance") or "balance").strip().lower()
    if kind not in {"balance", "catchup"}:
        kind = "balance"
    if tx:
        return {
            "booking_date": tx.get("booking_date") or date.today().isoformat(),
            "minutes": str(tx.get("minutes", 0)),
            "note": tx.get("note") or ("Zeit nachlaufen" if kind == "catchup" else "Korrektur"),
            "kind": kind,
        }
    return {
        "booking_date": date.today().isoformat(),
        "minutes": "-0:10" if kind == "catchup" else "+0:10",
        "note": "Zeit nachlaufen" if kind == "catchup" else "Korrektur",
        "kind": kind,
    }


def planning_time_options() -> list[str]:
    values: list[str] = []
    for hour in range(6, 23):
        for minute in (0, 15, 30, 45):
            if hour == 22 and minute != 0:
                continue
            values.append(f"{hour:02d}:{minute:02d}")
    return values


def planning_break_options() -> list[tuple[str, str]]:
    options = [0, 15, 30, 45, 60, 75, 90, 105, 120]
    result: list[tuple[str, str]] = []
    for minutes in options:
        hours, mins = divmod(minutes, 60)
        result.append((str(minutes), f"{hours}:{mins:02d}"))
    return result


def upsert_entry(data: dict[str, Any], entry_id: int | None = None) -> tuple[bool, str]:
    work_date = str(data.get("work_date") or "").strip()
    if not work_date:
        return False, "Datum fehlt."
    weekday = str(data.get("weekday") or "").strip() or infer_weekday(work_date)
    system_plusminus_min = parse_minutes(data.get("system_plusminus"))
    deducted_break_min = parse_minutes(data.get("deducted_break"))
    manual_correction_min = abs(parse_minutes(data.get("manual_correction")))
    carryover_budget_min = parse_minutes(data.get("carryover_budget"))
    effective_day_value_min = compute_effective(system_plusminus_min, deducted_break_min, manual_correction_min)
    note = str(data.get("note") or "").strip()
    work_segments = extract_segments_from_form(data)
    come_time = str(data.get("come_time") or "").strip()
    go_time = str(data.get("go_time") or "").strip()
    if work_segments:
        come_time = work_segments[0]["start"]
        go_time = work_segments[-1]["end"]
    else:
        work_segments = segments_list_from_text(default_segments_text(come_time, go_time))
    work_segments_text = build_segments_text(work_segments)
    work_segments_json = serialize_segments_json(work_segments) if work_segments else ""
    with closing(get_db()) as conn:
        existing = conn.execute("SELECT id, import_id FROM work_entries WHERE work_date = ?", (work_date,)).fetchone()
        if existing is not None and entry_id is None:
            entry_id = int(existing["id"])
        if entry_id is None:
            conn.execute(
                """
                INSERT INTO work_entries (
                    work_date, weekday, come_time, go_time, work_segments_text, work_segments_json, system_plusminus_min, deducted_break_min,
                    manual_correction_min, carryover_budget_min, imported_rest_component_min, effective_day_value_min, note, import_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'confirmed', ?, ?)
                """,
                (
                    work_date,
                    weekday,
                    come_time or None,
                    go_time or None,
                    work_segments_text or None,
                    work_segments_json or None,
                    system_plusminus_min,
                    deducted_break_min,
                    manual_correction_min,
                    carryover_budget_min,
                    max(0, deducted_break_min),
                    effective_day_value_min,
                    note,
                    now_iso(),
                    now_iso(),
                ),
            )
        else:
            current = conn.execute("SELECT import_id, imported_rest_component_min, carryover_budget_min, manual_correction_min FROM work_entries WHERE id = ?", (entry_id,)).fetchone()
            current_import_rest = int(current["imported_rest_component_min"] or 0) if current else 0
            current_carryover_budget = int(current["carryover_budget_min"] or 0) if current else 0
            current_manual_correction = abs(int(current["manual_correction_min"] or 0)) if current else 0
            if current and current["import_id"]:
                # For import-linked entries, the rest component shown in the form belongs to the import.
                # When the user keeps the budget field unchanged, recalculate it from import rest and catch-up.
                imported_rest_component_min = max(0, deducted_break_min)
                if carryover_budget_min == current_carryover_budget:
                    manual_budget_base = current_carryover_budget - current_import_rest + current_manual_correction
                    carryover_budget_min = compute_carryover_budget(imported_rest_component_min, manual_correction_min, manual_budget_base)
            else:
                imported_rest_component_min = current_import_rest
            conn.execute(
                """
                UPDATE work_entries
                SET work_date = ?, weekday = ?, come_time = ?, go_time = ?, work_segments_text = ?, work_segments_json = ?, system_plusminus_min = ?, deducted_break_min = ?,
                    manual_correction_min = ?, carryover_budget_min = ?, imported_rest_component_min = ?, effective_day_value_min = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    work_date,
                    weekday,
                    come_time or None,
                    go_time or None,
                    work_segments_text or None,
                    work_segments_json or None,
                    system_plusminus_min,
                    deducted_break_min,
                    manual_correction_min,
                    carryover_budget_min,
                    imported_rest_component_min,
                    effective_day_value_min,
                    note,
                    now_iso(),
                    entry_id,
                ),
            )
            if current and current["import_id"]:
                conn.execute("UPDATE imports SET status = 'needs_check', notes = 'Werte manuell geändert.' WHERE id = ?", (current["import_id"],))
        conn.commit()
    return True, "Eintrag gespeichert."


def upsert_plan(data: dict[str, Any], plan_id: int | None = None) -> tuple[bool, str]:
    plan_date = str(data.get("plan_date") or "").strip()
    if not plan_date:
        return False, "Datum fehlt."
    planned_break_min = max(0, parse_minutes(data.get("planned_break")))
    plan_segments = extract_segments_from_form(data, prefix="planned_segment")
    planned_start = str(data.get("planned_start") or "").strip() or None
    planned_end = str(data.get("planned_end") or "").strip() or None
    if plan_segments:
        planned_start = plan_segments[0]["start"]
        planned_end = plan_segments[-1]["end"]
    expected_result_min = 0
    if plan_segments:
        work_min = compute_work_duration_from_segments(plan_segments)
        expected_result_min = work_min - target_minutes_for_work_date(plan_date)
        planned_break_min = 0
    elif planned_start and planned_end:
        start_min = parse_time_to_minutes(planned_start)
        end_min = parse_time_to_minutes(planned_end)
        if start_min is None or end_min is None:
            return False, "Start oder Ende ist ungültig."
        if end_min < start_min:
            return False, "Das geplante Ende liegt vor dem Start."
        work_min = max(0, end_min - start_min - planned_break_min)
        expected_result_min = work_min - target_minutes_for_work_date(plan_date)
    plan_segments_text = build_segments_text(plan_segments) if plan_segments else default_segments_text(planned_start, planned_end)
    plan_segments_json = serialize_segments_json(plan_segments) if plan_segments else serialize_segments_json(segments_list_from_text(plan_segments_text)) if plan_segments_text else ""
    with closing(get_db()) as conn:
        if plan_id is None:
            existing = conn.execute("SELECT id FROM plans WHERE plan_date = ?", (plan_date,)).fetchone()
            if existing is not None:
                plan_id = int(existing["id"])
        if plan_id is None:
            conn.execute(
                """
                INSERT INTO plans (plan_date, planned_start, planned_end, planned_break_min, expected_result_min, plan_segments_text, plan_segments_json, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_date,
                    planned_start,
                    planned_end,
                    planned_break_min,
                    expected_result_min,
                    plan_segments_text or None,
                    plan_segments_json or None,
                    str(data.get("note") or "").strip(),
                    now_iso(),
                    now_iso(),
                ),
            )
        else:
            conn.execute(
                """
                UPDATE plans
                SET plan_date = ?, planned_start = ?, planned_end = ?, planned_break_min = ?, expected_result_min = ?, plan_segments_text = ?, plan_segments_json = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    plan_date,
                    planned_start,
                    planned_end,
                    planned_break_min,
                    expected_result_min,
                    plan_segments_text or None,
                    plan_segments_json or None,
                    str(data.get("note") or "").strip(),
                    now_iso(),
                    plan_id,
                ),
            )
        conn.commit()
    return True, "Planung gespeichert."


def upsert_account_transaction(data: dict[str, Any], tx_id: int | None = None) -> tuple[bool, str]:
    booking_date = str(data.get("booking_date") or "").strip() or date.today().isoformat()
    minutes = parse_minutes(data.get("minutes"))
    note = str(data.get("note") or "").strip()
    kind = str(data.get("kind") or "balance").strip().lower()
    if kind not in {"balance", "catchup"}:
        kind = "balance"
    with closing(get_db()) as conn:
        if tx_id is None:
            conn.execute(
                "INSERT INTO account_transactions (booking_date, minutes, note, kind, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (booking_date, minutes, note, kind, now_iso(), now_iso()),
            )
        else:
            conn.execute(
                "UPDATE account_transactions SET booking_date = ?, minutes = ?, note = ?, kind = ?, updated_at = ? WHERE id = ?",
                (booking_date, minutes, note, kind, now_iso(), tx_id),
            )
        conn.commit()
    return True, "Buchung gespeichert."


def set_current_balance_now(target_minutes: int, note: str) -> None:
    balance = account_balance()
    delta = int(target_minutes) - int(balance["current_balance"])
    if delta == 0:
        return
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO account_transactions (booking_date, minutes, note, kind, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (date.today().isoformat(), delta, note or "Kontostand gesetzt", "balance", now_iso(), now_iso()),
        )
        conn.commit()


def range_from_request(default_preset: str | None = None) -> tuple[str, str, str]:
    raw_preset = str(request.args.get("preset") or "").strip()
    today = date.today()
    from_arg = str(request.args.get("from") or "").strip()
    to_arg = str(request.args.get("to") or "").strip()

    # Frei gesetzte Datumsfilter sollen den Standard-Preset überschreiben.
    if not raw_preset and (from_arg or to_arg):
        from_date = from_arg or (today - timedelta(days=30)).isoformat()
        to_date = to_arg or today.isoformat()
        return from_date, to_date, "custom"

    preset = raw_preset or str(default_preset or "").strip()
    if preset in {"current_week", "next_week", "last_week"}:
        start, end = week_bounds_for_preset(preset, today)
        return start.isoformat(), end.isoformat(), preset
    if preset == "month":
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat(), preset
    if preset == "year":
        start_last_year = date(today.year - 1, 1, 1)
        end_last_year = date(today.year - 1, 12, 31)
        return start_last_year.isoformat(), end_last_year.isoformat(), preset

    from_date = from_arg or (today - timedelta(days=30)).isoformat()
    to_date = to_arg or today.isoformat()
    return from_date, to_date, (preset or "custom")




@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "0.3.91", "feature": "desktop-layout-fix"})

@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if not auth_enabled():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        password = str(request.form.get("password") or "")
        if password == WEB_PASSWORD:
            session["stunden_authenticated"] = True
            flash("Anmeldung erfolgreich.")
            return redirect(safe_next_target(request.form.get("next")))
        flash("Passwort falsch.", "error")
    return render_template("login.html", next_target=safe_next_target(request.args.get("next")), title="Anmeldung")


@app.route("/logout")
def logout() -> Any:
    session.pop("stunden_authenticated", None)
    flash("Abgemeldet.")
    return redirect(url_for("login"))




def cleanup_old_import_images(retain: int = 10) -> None:
    rows = query_all("SELECT id, processed_path FROM imports WHERE processed_path IS NOT NULL ORDER BY imported_at DESC, id DESC")
    for row in rows[retain:]:
        path = Path(str(row.get("processed_path") or "").strip())
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        with closing(get_db()) as conn:
            conn.execute("UPDATE imports SET processed_path = NULL WHERE id = ?", (row["id"],))
            conn.commit()


@app.route("/")
def dashboard() -> Any:
    metrics = dashboard_metrics()
    week_cards = current_week_cards()
    return render_template(
        "dashboard.html",
        title="Übersicht",
        metrics=metrics,
        week_cards=week_cards,
    )


@app.route("/scan", methods=["POST"])
def scan_now() -> Any:
    count = scan_import_dir()
    flash(f"Importordner geprüft. Verarbeitete Dateien: {count}.")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/imports")
def imports_page() -> Any:
    cleanup_old_import_images(10)
    imports = query_all(
        """
        SELECT i.*, w.id AS entry_id, w.work_date
        FROM imports i
        LEFT JOIN work_entries w ON w.import_id = i.id
        ORDER BY i.id DESC
        LIMIT 10
        """
    )
    return render_template("imports.html", title="Import", imports=imports)


@app.route("/imports/retry-all", methods=["POST"])
def retry_all_imports() -> Any:
    flash("Diese Funktion ist deaktiviert.", "error")
    return redirect(url_for("imports_page"))

    success_count = 0
    error_count = 0
    stopped_early = False
    with PROCESSING_LOCK:
        with closing(get_db()) as conn:
            for import_item in imports:
                processed_path = str(import_item.get("processed_path") or "").strip()
                if not processed_path:
                    continue
                path = Path(processed_path)
                if not path.exists():
                    error_count += 1
                    conn.execute(
                        "UPDATE imports SET status = ?, notes = ?, processed_at = ? WHERE id = ?",
                        ("error", "Datei fehlt auf dem Dateisystem.", now_iso(), int(import_item["id"])),
                    )
                    conn.commit()
                    continue
                try:
                    parsed = parse_screenshot(path, str(import_item.get("original_name") or ""))
                    status, note = auto_create_or_update_entry(
                        conn,
                        parsed,
                        int(import_item["id"]),
                        datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
                        str(import_item.get("original_name") or path.name),
                    )
                    if parsed.get("confidence", 0) < 2:
                        status = "needs_check"
                        note += " Bitte Werte prüfen."
                    conn.execute(
                        "UPDATE imports SET status = ?, notes = ?, parser_summary = ?, processed_at = ? WHERE id = ?",
                        (status, note, build_parser_summary_for_saved_entry(conn, int(import_item["id"]), parsed), now_iso(), int(import_item["id"])),
                    )
                    conn.commit()
                    success_count += 1
                except Exception as exc:
                    error_count += 1
                    message = str(exc)
                    conn.execute(
                        "UPDATE imports SET status = ?, notes = ?, parser_summary = ?, processed_at = ? WHERE id = ?",
                        ("error", f"Erneute Verarbeitung fehlgeschlagen: {message}", "Automatische Verarbeitung fehlgeschlagen.", now_iso(), int(import_item["id"])),
                    )
                    conn.commit()
                    if is_transient_ai_error_message(message):
                        stopped_early = True
                        break
    if stopped_early:
        flash(f"Neu-Verarbeitung gestoppt: {success_count} erfolgreich, {error_count} mit Limit/Überlastung.", "error")
    elif error_count:
        flash(f"Alle Imports neu verarbeitet: {success_count} erfolgreich, {error_count} mit Fehler.", "error")
    else:
        flash(f"Alle Imports neu verarbeitet: {success_count} erfolgreich.")
    return redirect(url_for("imports_page"))


@app.route("/imports/<int:import_id>/image")
def view_import_image(import_id: int) -> Any:
    import_item = query_one("SELECT * FROM imports WHERE id = ?", (import_id,))
    if not import_item or not import_item.get("processed_path"):
        flash("Bild nicht gefunden.", "error")
        return redirect(url_for("imports_page"))
    path = Path(import_item["processed_path"])
    if not path.exists():
        flash("Datei auf dem Dateisystem nicht gefunden.", "error")
        return redirect(url_for("imports_page"))
    return send_file(path)


@app.route("/imports/<int:import_id>/retry", methods=["POST"])
def retry_import(import_id: int) -> Any:
    import_item = query_one("SELECT * FROM imports WHERE id = ?", (import_id,))
    if not import_item or not import_item.get("processed_path"):
        flash("Import nicht gefunden.", "error")
        return redirect(url_for("imports_page"))
    path = Path(import_item["processed_path"])
    if not path.exists():
        flash("Datei fehlt auf dem Dateisystem.", "error")
        return redirect(url_for("imports_page"))
    with PROCESSING_LOCK:
        with closing(get_db()) as conn:
            outcome, detail = analyze_import_and_store(
                conn,
                import_id,
                path,
                str(import_item["original_name"] or path.name),
                error_prefix="Erneute Verarbeitung fehlgeschlagen",
                queue_prefix="Neuversuch vorgemerkt",
            )
            conn.commit()
    if outcome == "success":
        flash("Import erneut verarbeitet.")
    elif outcome == "queued":
        flash(f"Import für automatischen Neuversuch vorgemerkt: {detail}")
    else:
        flash(f"Erneute Verarbeitung fehlgeschlagen: {detail}", "error")
    return redirect(url_for("imports_page"))


@app.route("/imports/<int:import_id>/delete-image", methods=["POST"])
def delete_import_image(import_id: int) -> Any:
    with closing(get_db()) as conn:
        import_row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
        if import_row is None:
            flash("Import nicht gefunden.", "error")
            return redirect(url_for("imports_page"))
        if not import_row["processed_path"]:
            flash("Für diesen Import ist kein Bild mehr vorhanden.", "error")
            return redirect(url_for("imports_page"))

        removed = remove_processed_image_only(conn, import_row)
        conn.commit()

    if removed:
        flash("Bilddatei des Imports wurde gelöscht. Der angelegte Tag bleibt erhalten.")
    else:
        flash("Für diesen Import war kein Bild mehr vorhanden.", "error")
    return redirect(url_for("imports_page"))


@app.route("/imports/<int:import_id>/delete", methods=["POST"])
def delete_import(import_id: int) -> Any:
    delete_linked_entry = str(request.form.get("delete_linked_entry") or "").lower() in {"1", "true", "on", "yes"}
    with closing(get_db()) as conn:
        import_row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
        if import_row is None:
            flash("Import nicht gefunden.", "error")
            return redirect(url_for("imports_page"))

        linked_entry = conn.execute("SELECT id FROM work_entries WHERE import_id = ?", (import_id,)).fetchone()
        if linked_entry is not None and delete_linked_entry:
            conn.execute("DELETE FROM work_entries WHERE import_id = ?", (import_id,))
            entry_msg = " Verknüpfter Tag wurde mit gelöscht."
        elif linked_entry is not None:
            conn.execute("UPDATE work_entries SET import_id = NULL, updated_at = ? WHERE import_id = ?", (now_iso(), import_id))
            entry_msg = " Verknüpfter Tag bleibt erhalten."
        else:
            entry_msg = ""

        delete_import_file(dict(import_row))
        conn.execute("DELETE FROM imports WHERE id = ?", (import_id,))
        conn.commit()

    flash("Import gelöscht." + entry_msg)
    return redirect(url_for("imports_page"))



@app.route("/api/telegram/import-prompt", methods=["POST"])
def telegram_import_prompt_api() -> Any:
    payload = api_request_payload()
    if not api_request_authorized(payload):
        response = jsonify({"ok": False, "reply_text": "Nicht autorisiert.", "error": "Nicht autorisiert."})
        response.status_code = 401
        return response
    chat_id = str(payload.get("chat_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    if not chat_id:
        response = jsonify({"ok": False, "reply_text": "chat_id fehlt.", "error": "chat_id fehlt."})
        response.status_code = 400
        return response
    filename = normalize_filename(payload.get("filename") or payload.get("original_name") or payload.get("file_name"))
    source_path = str(payload.get("source_path") or payload.get("path") or "").strip()
    scan_import_dir()
    with closing(get_db()) as conn:
        import_row = find_import_for_telegram(conn, source_path=source_path, filename=filename, allow_fallback=False)
        if import_row is not None:
            import_id, work_date = resolve_work_date_from_import(conn, import_row)
        else:
            import_id, work_date = None, ""
        upsert_telegram_followup(
            conn,
            chat_id=chat_id,
            user_id=user_id,
            import_id=import_id,
            work_date=work_date,
            prompt_text=TELEGRAM_FOLLOWUP_PROMPT,
            context={
                "filename": filename,
                "source_path": source_path,
            },
        )
        conn.commit()
    return jsonify({
        "ok": True,
        "reply_text": TELEGRAM_FOLLOWUP_PROMPT,
        "work_date": work_date,
        "import_id": import_id,
    })


@app.route("/api/telegram/reply", methods=["POST"])
def telegram_reply_api() -> Any:
    payload = api_request_payload()
    if not api_request_authorized(payload):
        response = jsonify({"ok": False, "reply_text": "Nicht autorisiert.", "error": "Nicht autorisiert."})
        response.status_code = 401
        return response
    chat_id = str(payload.get("chat_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    reply_text = str(
        payload.get("text")
        or payload.get("message")
        or payload.get("reply")
        or payload.get("content")
        or payload.get("data")
        or ""
    ).strip()
    if not chat_id:
        response = jsonify({"ok": False, "reply_text": "chat_id fehlt.", "error": "chat_id fehlt."})
        response.status_code = 400
        return response
    scan_import_dir()
    retry_pending_imports()
    scan_import_dir()
    with closing(get_db()) as conn:
        ok, message, extra = apply_telegram_catchup_reply(conn, chat_id=chat_id, user_id=user_id, reply_text=reply_text)
        if ok:
            conn.commit()
            return jsonify({
                "ok": True,
                "reply_text": message,
                **extra,
            })
        conn.rollback()
    response = jsonify({"ok": False, "reply_text": message, "error": message})
    response.status_code = 400
    return response


@app.route("/entries/book-target/<work_date>", methods=["POST"])
def book_target_day(work_date: str) -> Any:
    target = target_minutes_for_work_date(work_date)
    weekday = infer_weekday(work_date)
    note = str(request.form.get("note") or "Sollzeit gebucht").strip() or "Sollzeit gebucht"
    come_time, go_time, work_segments = booked_target_times_for_work_date(work_date)
    work_segments_text = build_segments_text(work_segments)
    work_segments_json = serialize_segments_json(work_segments)
    with closing(get_db()) as conn:
        existing = conn.execute("SELECT id, import_id FROM work_entries WHERE work_date = ?", (work_date,)).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO work_entries (
                    work_date, weekday, come_time, go_time, work_segments_text, work_segments_json,
                    system_plusminus_min, deducted_break_min, manual_correction_min, carryover_budget_min,
                    imported_rest_component_min, effective_day_value_min, note, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, ?, 'confirmed', ?, ?)
                """,
                (work_date, weekday, come_time, go_time, work_segments_text, work_segments_json, note, now_iso(), now_iso()),
            )
        else:
            conn.execute(
                """
                UPDATE work_entries
                SET weekday = ?, come_time = ?, go_time = ?, work_segments_text = ?, work_segments_json = ?,
                    system_plusminus_min = 0, deducted_break_min = 0, manual_correction_min = 0, effective_day_value_min = 0,
                    note = ?, updated_at = ?
                WHERE id = ?
                """,
                (weekday, come_time, go_time, work_segments_text, work_segments_json, note, now_iso(), int(existing["id"])),
            )
        conn.commit()
    flash(f"Sollzeit für {work_date} gebucht ({come_time}–{go_time}).")
    return redirect(url_for("dashboard"))

@app.route("/entries")
def entries_page() -> Any:
    from_date, to_date, active_preset = range_from_request(default_preset="current_week")
    entries = query_all(
        "SELECT * FROM work_entries WHERE work_date BETWEEN ? AND ? ORDER BY work_date ASC",
        (from_date, to_date),
    )
    transactions = query_all(
        "SELECT * FROM account_transactions WHERE booking_date BETWEEN ? AND ? ORDER BY booking_date ASC, id ASC",
        (from_date, to_date),
    )
    import_ids = [int(entry.get('import_id') or 0) for entry in entries if int(entry.get('import_id') or 0) > 0]
    parser_summary_by_import: dict[int, str] = {}
    if import_ids:
        placeholders = ",".join("?" for _ in import_ids)
        imported_rows = query_all(f"SELECT id, parser_summary FROM imports WHERE id IN ({placeholders})", tuple(import_ids))
        parser_summary_by_import = {int(row['id']): str(row.get('parser_summary') or '') for row in imported_rows}
    catchup_adjustments = catchup_adjustments_by_date(from_date, to_date)
    summary = {
        "count": len(entries),
        "effective_total": sum(int(entry.get("effective_day_value_min") or 0) for entry in entries),
        "effective_total_adjusted": sum(adjusted_effective_for_entry(entry, int(catchup_adjustments.get(str(entry.get("work_date") or ""), 0) or 0)) for entry in entries),
        "balance_total": sum(int(entry.get("system_plusminus_min") or 0) for entry in entries),
        "catchup_total": sum(int(entry.get("imported_rest_component_min") or 0) for entry in entries),
    }
    booking_items: list[dict[str, Any]] = []
    for entry in entries:
        work_date = str(entry.get("work_date") or "")
        catchup_adjustment = int(catchup_adjustments.get(work_date, 0) or 0)
        imported_rest = int(entry.get("imported_rest_component_min") or 0)
        booking_items.append({
            "item_type": "entry",
            "sort_date": work_date,
            "sort_id": int(entry.get("id") or 0),
            "entry": entry,
            "catchup_adjustment": catchup_adjustment,
            "display_catchup": display_catchup_for_entry(entry, catchup_adjustment),
            "combined_catchup": imported_rest + display_catchup_for_entry(entry, catchup_adjustment),
            "adjusted_effective": adjusted_effective_for_entry(entry, catchup_adjustment),
            "work_time_text": preferred_work_time_text(entry, parser_summary_by_import.get(int(entry.get('import_id') or 0), '')),
        })
    balance_transactions: list[dict[str, Any]] = []
    catchup_transactions: list[dict[str, Any]] = []
    for tx in transactions:
        if str(tx.get("kind") or "balance") == "catchup":
            catchup_transactions.append(tx)
        else:
            balance_transactions.append(tx)
    for tx in balance_transactions:
        booking_items.append({
            "item_type": "tx",
            "sort_date": str(tx.get("booking_date") or ""),
            "sort_id": int(tx.get("id") or 0),
            "tx": tx,
        })
    booking_items.sort(key=lambda item: (item["sort_date"], 0 if item["item_type"] == "entry" else 1, item["sort_id"]))
    balance = account_balance()
    return render_template(
        "entries.html",
        title="Buchungen",
        entries=entries,
        summary=summary,
        balance=balance,
        booking_items=booking_items,
        catchup_transactions=catchup_transactions,
        filters={"from_date": from_date, "to_date": to_date, "preset": active_preset},
    )


@app.route("/entries/new", methods=["GET", "POST"])
def new_entry() -> Any:
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in ["work_date", "weekday", "come_time", "go_time", "system_plusminus", "deducted_break", "manual_correction", "carryover_budget", "note", "segment1_start", "segment1_end", "segment2_start", "segment2_end", "segment3_start", "segment3_end", "segment4_start", "segment4_end"]}
        ok, message = upsert_entry(form)
        flash(message, "error" if not ok else "message")
        if ok:
            return redirect(url_for("entries_page"))
        return render_template("entry_form.html", title="Neuer Arbeitstag", heading="Arbeitstag anlegen", form=form, import_item=None, preview_effective=minutes_hm(compute_effective(parse_minutes(form["system_plusminus"]), parse_minutes(form["deducted_break"]), abs(parse_minutes(form["manual_correction"])))), entry_id=None)
    form = default_entry_form()
    return render_template("entry_form.html", title="Neuer Arbeitstag", heading="Arbeitstag anlegen", form=form, import_item=None, preview_effective=minutes_hm(0), entry_id=None)


@app.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
def edit_entry(entry_id: int) -> Any:
    entry = query_one("SELECT * FROM work_entries WHERE id = ?", (entry_id,))
    if not entry:
        flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("entries_page"))
    import_item = query_one("SELECT * FROM imports WHERE id = ?", (entry.get("import_id"),)) if entry.get("import_id") else None
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in ["work_date", "weekday", "come_time", "go_time", "system_plusminus", "deducted_break", "manual_correction", "carryover_budget", "note", "segment1_start", "segment1_end", "segment2_start", "segment2_end", "segment3_start", "segment3_end", "segment4_start", "segment4_end"]}
        ok, message = upsert_entry(form, entry_id=entry_id)
        flash(message, "error" if not ok else "message")
        if ok:
            return redirect(url_for("entries_page"))
        return render_template("entry_form.html", title="Arbeitstag bearbeiten", heading="Arbeitstag bearbeiten", form=form, import_item=import_item, preview_effective=minutes_hm(compute_effective(parse_minutes(form["system_plusminus"]), parse_minutes(form["deducted_break"]), abs(parse_minutes(form["manual_correction"])))), entry_id=entry_id)
    form = default_entry_form(entry=entry)
    return render_template("entry_form.html", title="Arbeitstag bearbeiten", heading="Arbeitstag bearbeiten", form=form, import_item=import_item, preview_effective=minutes_hm(entry.get("effective_day_value_min", 0)), entry_id=entry_id)


@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
def delete_entry(entry_id: int) -> Any:
    with closing(get_db()) as conn:
        entry = conn.execute("SELECT import_id FROM work_entries WHERE id = ?", (entry_id,)).fetchone()
        conn.execute("DELETE FROM work_entries WHERE id = ?", (entry_id,))
        if entry and entry["import_id"]:
            conn.execute("UPDATE imports SET status = 'needs_check', notes = 'Verknüpfter Tag wurde gelöscht.' WHERE id = ?", (entry["import_id"],))
        conn.commit()
    flash("Eintrag gelöscht.")
    return redirect(url_for("entries_page"))


@app.route("/plans")
def plans_page() -> Any:
    active_preset, start, _ = resolve_plan_week(request.args, request.args)
    start_iso = start.isoformat()
    end_iso = (start + timedelta(days=4)).isoformat()
    plans = query_all("SELECT * FROM plans WHERE plan_date BETWEEN ? AND ? ORDER BY plan_date ASC", (start_iso, end_iso))
    for plan in plans:
        plan["plan_time_text"] = preferred_plan_time_text(plan)
    forecast = weekly_forecast_for_range(start_iso, end_iso)
    return render_template(
        "plans.html",
        title="Planung",
        plans=plans,
        active_preset=active_preset,
        week_start=start_iso,
        week_end=end_iso,
        week_label=f"{start.strftime('%d.%m.%Y')} – {(start + timedelta(days=4)).strftime('%d.%m.%Y')}",
        forecast=forecast,
        future_week_buttons=future_plan_week_buttons(),
    )


@app.route("/plans/new", methods=["GET", "POST"])
def new_plan() -> Any:
    active_preset, start, _ = resolve_plan_week(request.args, request.form)
    week_start = start.isoformat()
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in ["plan_date", "planned_start", "planned_end", "planned_break", "expected_result", "note", "week_preset", "week_start", "planned_segment1_start", "planned_segment1_end", "planned_segment2_start", "planned_segment2_end", "planned_segment3_start", "planned_segment3_end", "planned_segment4_start", "planned_segment4_end"]}
        try:
            ok, message = upsert_plan(form)
        except Exception as exc:
            ok, message = False, f"Planung konnte nicht gespeichert werden: {exc}"
        flash(message, "error" if not ok else "message")
        if ok:
            if active_preset == "custom":
                return redirect(url_for("plans_page", week_start=week_start))
            return redirect(url_for("plans_page", preset=active_preset))
        return render_template("plan_form.html", title="Neue Planung", heading="Planung anlegen", form=form, time_options=planning_time_options(), break_options=planning_break_options(), plan_id=None)
    return render_template("plan_form.html", title="Neue Planung", heading="Planung anlegen", form=default_plan_form(preset=active_preset, week_start=week_start), time_options=planning_time_options(), break_options=planning_break_options(), plan_id=None)


@app.route("/plans/<int:plan_id>/edit", methods=["GET", "POST"])
def edit_plan(plan_id: int) -> Any:
    plan = query_one("SELECT * FROM plans WHERE id = ?", (plan_id,))
    if not plan:
        flash("Planung nicht gefunden.", "error")
        return redirect(url_for("plans_page"))
    active_preset, start, _ = resolve_plan_week(request.args, request.form)
    week_start = start.isoformat()
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in ["plan_date", "planned_start", "planned_end", "planned_break", "expected_result", "note", "week_preset", "week_start", "planned_segment1_start", "planned_segment1_end", "planned_segment2_start", "planned_segment2_end", "planned_segment3_start", "planned_segment3_end", "planned_segment4_start", "planned_segment4_end"]}
        try:
            ok, message = upsert_plan(form, plan_id=plan_id)
        except Exception as exc:
            ok, message = False, f"Planung konnte nicht gespeichert werden: {exc}"
        flash(message, "error" if not ok else "message")
        if ok:
            if active_preset == "custom":
                return redirect(url_for("plans_page", week_start=week_start))
            return redirect(url_for("plans_page", preset=active_preset))
        return render_template("plan_form.html", title="Planung bearbeiten", heading="Planung bearbeiten", form=form, time_options=planning_time_options(), break_options=planning_break_options(), plan_id=plan_id)
    return render_template("plan_form.html", title="Planung bearbeiten", heading="Planung bearbeiten", form=default_plan_form(plan=plan, preset=active_preset, week_start=week_start), time_options=planning_time_options(), break_options=planning_break_options(), plan_id=plan_id)




@app.route("/plans/<int:plan_id>/target", methods=["POST"])
def plan_target_day(plan_id: int) -> Any:
    active_preset, start, _ = resolve_plan_week(request.args, request.form)
    week_start = start.isoformat()
    work_date = str(request.form.get("plan_date") or "").strip()
    if not work_date:
        flash("Datum fehlt.", "error")
        if active_preset == "custom":
            return redirect(url_for("edit_plan", plan_id=plan_id, week_start=week_start))
        return redirect(url_for("edit_plan", plan_id=plan_id, preset=active_preset))
    planned_start, planned_end, plan_segments = booked_target_times_for_work_date(work_date)
    form = {key: request.form.get(key, "") for key in [
        "plan_date", "planned_start", "planned_end", "planned_break", "expected_result", "note",
        "week_preset", "week_start",
        "planned_segment1_start", "planned_segment1_end",
        "planned_segment2_start", "planned_segment2_end",
        "planned_segment3_start", "planned_segment3_end",
        "planned_segment4_start", "planned_segment4_end",
    ]}
    form["plan_date"] = work_date
    form["planned_start"] = planned_start
    form["planned_end"] = planned_end
    form["planned_break"] = "0"
    form["expected_result"] = "0"
    form["note"] = str(request.form.get("note") or "Sollzeit geplant").strip() or "Sollzeit geplant"
    for idx in range(1, 5):
        form[f"planned_segment{idx}_start"] = ""
        form[f"planned_segment{idx}_end"] = ""
    if plan_segments:
        form["planned_segment1_start"] = plan_segments[0]["start"]
        form["planned_segment1_end"] = plan_segments[0]["end"]
    try:
        ok, message = upsert_plan(form, plan_id=plan_id)
    except Exception as exc:
        ok, message = False, f"Sollzeit konnte nicht geplant werden: {exc}"
    if ok:
        flash(f"Sollzeit für {work_date} geplant ({planned_start}–{planned_end}).")
    else:
        flash(message, "error")
    if active_preset == "custom":
        return redirect(url_for("edit_plan", plan_id=plan_id, week_start=week_start))
    return redirect(url_for("edit_plan", plan_id=plan_id, preset=active_preset))


@app.route("/plans/<int:plan_id>/delete", methods=["POST"])
def delete_plan(plan_id: int) -> Any:
    active_preset, start, _ = resolve_plan_week(request.args, request.form)
    week_start = start.isoformat()
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        conn.commit()
    flash("Planung gelöscht.")
    if active_preset == "custom":
        return redirect(url_for("plans_page", week_start=week_start))
    return redirect(url_for("plans_page", preset=active_preset))


@app.route("/konto")
def account_page() -> Any:
    transactions = query_all("SELECT * FROM account_transactions ORDER BY booking_date DESC, id DESC")
    balance = account_balance()
    return render_template("account.html", title="Stundenkonto", transactions=transactions, balance=balance)


@app.route("/konto/new", methods=["GET", "POST"])
def new_account_transaction() -> Any:
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in ["booking_date", "minutes", "note", "kind"]}
        ok, message = upsert_account_transaction(form)
        flash(message, "error" if not ok else "message")
        if ok:
            return redirect(url_for("entries_page"))
        return render_template("account_form.html", title="Neue Buchung", heading="Buchung anlegen", form=form)
    kind = str(request.args.get("kind") or "balance")
    return render_template("account_form.html", title="Neue Buchung", heading="Buchung anlegen", form=default_account_form(kind=kind))


@app.route("/konto/<int:tx_id>/edit", methods=["GET", "POST"])
def edit_account_transaction(tx_id: int) -> Any:
    tx = query_one("SELECT * FROM account_transactions WHERE id = ?", (tx_id,))
    if not tx:
        flash("Kontobuchung nicht gefunden.", "error")
        return redirect(url_for("entries_page"))
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in ["booking_date", "minutes", "note", "kind"]}
        ok, message = upsert_account_transaction(form, tx_id=tx_id)
        flash(message, "error" if not ok else "message")
        if ok:
            return redirect(url_for("entries_page"))
        return render_template("account_form.html", title="Kontobuchung bearbeiten", heading="Kontobuchung bearbeiten", form=form)
    return render_template("account_form.html", title="Kontobuchung bearbeiten", heading="Kontobuchung bearbeiten", form=default_account_form(tx))


@app.route("/konto/<int:tx_id>/delete", methods=["POST"])
def delete_account_transaction(tx_id: int) -> Any:
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM account_transactions WHERE id = ?", (tx_id,))
        conn.commit()
    flash("Kontobuchung gelöscht.")
    return redirect(url_for("entries_page"))


@app.route("/konto/set-current", methods=["POST"])
def set_current_balance_route() -> Any:
    target = parse_minutes(request.form.get("current_balance"))
    note = str(request.form.get("note") or "Kontostand gesetzt").strip()
    before = account_balance()["current_balance"]
    set_current_balance_now(target, note)
    after = account_balance()["current_balance"]
    if before == after:
        flash("Kontostand war bereits auf diesem Wert.")
    else:
        flash(f"Kontostand auf {minutes_hm(after)} gesetzt.")
    return redirect(request.referrer or url_for("dashboard"))


def bootstrap() -> None:
    init_db()
    scan_import_dir()
    start_background_scanner()


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)