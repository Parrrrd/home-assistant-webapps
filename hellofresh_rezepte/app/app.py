from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests
import pdfplumber
try:
    import pytesseract
    from PIL import Image, ImageOps
except Exception:
    pytesseract = None
    Image = None
    ImageOps = None
from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from pypdf import PdfReader
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("HF_DATA_DIR", "/data"))
PDF_DIR = DATA_DIR / "pdfs"
PREVIEW_DIR = DATA_DIR / "previews"
DB_PATH = DATA_DIR / "hf_recipes.db"
SHARE_DIR = Path(os.environ.get("HF_SHARE_DIR", "/share/HelloFresh"))
MEDIA_DIR = Path(os.environ.get("HF_MEDIA_DIR", "/media"))
IMPORT_DIR = MEDIA_DIR / "Import" / "Rezepte"
IMPORT_ERROR_DIR = IMPORT_DIR / "Fehler"
# Der bisherige Archivordner bleibt aus Kompatibilitätsgründen erhalten.
# Neue Importe werden nach erfolgreicher Übernahme wie beim Kleinanzeigen-Manager
# aus dem Importordner entfernt.
IMPORTED_DIR = SHARE_DIR / "importiert"
DUPLICATE_DIR = SHARE_DIR / "duplikate"
IMPORT_STATE_PATH = DATA_DIR / "import-state.json"
HELLOFRESH_STATE_PATH = DATA_DIR / "hellofresh-import-state.json"
HELLOFRESH_PROFILE_DIR = DATA_DIR / "hellofresh-browser"
ALLOWED_EXTENSIONS = {"pdf"}
AUTO_IMPORT_INTERVAL_SECONDS = int(os.environ.get("HF_IMPORT_INTERVAL_SECONDS", "3600"))
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HASS_API_BASE = os.environ.get("HF_HASS_API_BASE", "http://supervisor/core/api")
SHOPPING_LIST_PORT = int(os.environ.get("HF_SHOPPING_LIST_PORT", "8156"))
SHOPPING_LIST_HOST = os.environ.get("HF_SHOPPING_LIST_HOST", "").strip()
SHOPPING_LIST_TOKEN = os.environ.get("HF_SHOPPING_LIST_TOKEN", "").strip()
SHOPPING_LIST_ID = os.environ.get("HF_SHOPPING_LIST_ID", "").strip()
APP_BRAND = "Rezeptverwaltung"
APP_EYEBROW = "Rezepte lokal im Home Assistant"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
DASH_CLASS = r"[\-–—]"

app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))
app.config["SECRET_KEY"] = os.environ.get("HF_SECRET", "hellofresh-local-secret")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.config["AUTO_IMPORT_THREAD_STARTED"] = False
_import_lock = threading.Lock()
_hellofresh_lock = threading.Lock()
_hellofresh_visible_browser_lock = threading.Lock()
_hellofresh_visible_browser_process: subprocess.Popen[bytes] | None = None
_hellofresh_visible_browser_account_key = ""
_hellofresh_visible_browser_launching = False

CORRECTION_CACHE: dict[str, str] = {}
CORRECTION_CACHE_LOADED_AT = 0.0
CORRECTION_CACHE_TTL_SECONDS = 30.0

STATUS_OPEN = "offen"
STATUS_PRESENT = "vorhanden"
STATUS_COOKED = "gekocht"
VALID_RECIPE_STATUSES = {STATUS_OPEN, STATUS_PRESENT, STATUS_COOKED}


def normalize_recipe_status(value: str | None, default: str = STATUS_OPEN) -> str:
    value = (value or "").strip().lower()
    return value if value in VALID_RECIPE_STATUSES else default


def recipe_status_label(value: str | None) -> str:
    status = normalize_recipe_status(value)
    if status == STATUS_COOKED:
        return "Gekocht"
    if status == STATUS_PRESENT:
        return "Vorhanden"
    return "Offen"


def recipe_status_css_class(value: str | None) -> str:
    status = normalize_recipe_status(value)
    if status == STATUS_COOKED:
        return "status-cooked"
    if status == STATUS_PRESENT:
        return "status-present"
    return "status-open"



# ---------- filesystem / db ----------
def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    IMPORT_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
    DUPLICATE_DIR.mkdir(parents=True, exist_ok=True)
    HELLOFRESH_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        HELLOFRESH_PROFILE_DIR.chmod(0o700)
    except OSError:
        pass


def move_file_safe(src: Path, dst: Path) -> None:
    """Move a file safely even when /data and /share are different filesystems."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dst)
    except OSError:
        shutil.move(str(src), str(dst))


def get_conn() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_conn(_: Any) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subtitle TEXT,
                recipe_number TEXT,
                filename TEXT NOT NULL DEFAULT '',
                preview_filename TEXT,
                original_filename TEXT,
                uploaded_at TEXT NOT NULL,
                delivered_at TEXT,
                cooked_at TEXT,
                status TEXT NOT NULL DEFAULT 'offen',
                rating INTEGER NOT NULL DEFAULT 0,
                favorite INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                tags TEXT,
                search_text TEXT,
                archive INTEGER NOT NULL DEFAULT 0,
                import_source TEXT NOT NULL DEFAULT 'upload',
                cooked_count INTEGER NOT NULL DEFAULT 0,
                cook_preference TEXT NOT NULL DEFAULT '',
                is_custom INTEGER NOT NULL DEFAULT 0,
                image_filename TEXT NOT NULL DEFAULT '',
                base_servings INTEGER NOT NULL DEFAULT 3,
                ingredients_json TEXT NOT NULL DEFAULT '[]',
                instructions TEXT NOT NULL DEFAULT '',
                duplicate_group TEXT NOT NULL DEFAULT '',
                duplicate_detached INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_recipes_status ON recipes(status);
            CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating);
            CREATE INDEX IF NOT EXISTS idx_recipes_favorite ON recipes(favorite);
            CREATE INDEX IF NOT EXISTS idx_recipes_original_filename ON recipes(original_filename);
            CREATE TABLE IF NOT EXISTS meal_plans (
                plan_date TEXT PRIMARY KEY,
                recipe_id INTEGER,
                free_text TEXT NOT NULL DEFAULT '',
                iphone_title TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(recipe_id) REFERENCES recipes(id)
            );
            CREATE TABLE IF NOT EXISTS ingredient_name_corrections (
                wrong_key TEXT PRIMARY KEY,
                wrong_name TEXT NOT NULL DEFAULT '',
                corrected_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                use_count INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(recipes)")}
        recipe_columns = {
            "preview_filename": "TEXT",
            "cooked_count": "INTEGER NOT NULL DEFAULT 0",
            "cook_preference": "TEXT NOT NULL DEFAULT ''",
            "is_custom": "INTEGER NOT NULL DEFAULT 0",
            "image_filename": "TEXT NOT NULL DEFAULT ''",
            "base_servings": "INTEGER NOT NULL DEFAULT 3",
            "ingredients_json": "TEXT NOT NULL DEFAULT '[]'",
            "instructions": "TEXT NOT NULL DEFAULT ''",
            "duplicate_group": "TEXT NOT NULL DEFAULT ''",
            "duplicate_detached": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in recipe_columns.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE recipes ADD COLUMN {column} {definition}")
        plan_columns = {row[1] for row in conn.execute("PRAGMA table_info(meal_plans)")}
        for column, definition in {
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
            "note": "TEXT NOT NULL DEFAULT ''",
            "iphone_title": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in plan_columns:
                conn.execute(f"ALTER TABLE meal_plans ADD COLUMN {column} {definition}")
        conn.commit()


def _load_ingredient_correction_cache(force: bool = False) -> dict[str, str]:
    global CORRECTION_CACHE, CORRECTION_CACHE_LOADED_AT
    now = time.time()
    if not force and CORRECTION_CACHE and now - CORRECTION_CACHE_LOADED_AT < CORRECTION_CACHE_TTL_SECONDS:
        return CORRECTION_CACHE
    ensure_dirs()
    cache: dict[str, str] = {}
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            rows = conn.execute(
                "SELECT wrong_key, corrected_name FROM ingredient_name_corrections WHERE wrong_key <> '' AND corrected_name <> ''"
            ).fetchall()
        for wrong_key, corrected_name in rows:
            key = clean_recipe_title(wrong_key or '').lower().strip()
            value = clean_pdf_cell(corrected_name)
            if key and value:
                cache[key] = value
    except Exception:
        pass
    CORRECTION_CACHE = cache
    CORRECTION_CACHE_LOADED_AT = now
    return CORRECTION_CACHE


def get_learned_ingredient_correction(name: str) -> str | None:
    key = normalize_title(name)
    if not key:
        return None
    return _load_ingredient_correction_cache().get(key)


def save_ingredient_name_correction(wrong_name: str, corrected_name: str) -> bool:
    wrong_name = clean_pdf_cell(wrong_name)
    corrected_name = clean_pdf_cell(corrected_name)
    wrong_key = normalize_title(wrong_name)
    corrected_key = normalize_title(corrected_name)
    if not wrong_key or not corrected_key or wrong_key == corrected_key:
        return False
    now = datetime.now().isoformat(timespec="seconds")
    ensure_dirs()
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute(
                """
                INSERT INTO ingredient_name_corrections (wrong_key, wrong_name, corrected_name, created_at, updated_at, use_count)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(wrong_key) DO UPDATE SET
                    wrong_name = excluded.wrong_name,
                    corrected_name = excluded.corrected_name,
                    updated_at = excluded.updated_at,
                    use_count = ingredient_name_corrections.use_count + 1
                """,
                (wrong_key, wrong_name, corrected_name, now, now),
            )
            conn.commit()
        _load_ingredient_correction_cache(force=True)
        return True
    except Exception:
        return False


# ---------- general helpers ----------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def fmt_date(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return date_str


def _hellofresh_delivery_date(value: str) -> date | None:
    """Extract a date from HelloFresh' compact delivery text."""
    compact = " ".join(str(value or "").split())
    months = {
        "jan": 1, "januar": 1, "jan": 1, "feb": 2, "februar": 2,
        "mar": 3, "mär": 3, "maerz": 3, "märz": 3, "april": 4, "apr": 4,
        "mai": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "okt": 10, "oct": 10, "oktober": 10, "nov": 11, "november": 11,
        "dez": 12, "dec": 12, "dezember": 12,
    }
    match = re.search(r"\b(\d{1,2})\.?\s+([A-Za-zÄÖÜäöü]+)\b", compact)
    if not match:
        return None
    month = months.get(match.group(2).lower().rstrip("."))
    if not month:
        return None
    try:
        day = int(match.group(1))
        candidates = [date(year, month, day) for year in (date.today().year - 1, date.today().year, date.today().year + 1)]
    except ValueError:
        return None
    return min(candidates, key=lambda candidate: abs((candidate - date.today()).days))


def _hellofresh_delivery_label(value: str) -> str:
    """Turn HelloFresh' compact date text into a useful, local delivery label."""
    compact = " ".join(str(value or "").split())
    delivery_date = _hellofresh_delivery_date(compact)
    if delivery_date is None:
        return compact
    difference = (delivery_date - date.today()).days
    weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][delivery_date.weekday()]
    if difference == 0:
        return "Heute"
    if difference == -1:
        return "Gestern"
    if difference == 1:
        return "Morgen"
    if -6 <= difference < 0:
        return f"Letzten {weekday}"
    if 0 < difference <= 6:
        return f"Kommenden {weekday}"
    short_weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][delivery_date.weekday()]
    short_month = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"][delivery_date.month - 1]
    return f"{short_weekday}., {delivery_date.day}. {short_month}."


def iso_week_label(value: str | None) -> str:
    dt = parse_date(value)
    if not dt:
        return ""
    year, week, _ = dt.isocalendar()
    return f"KW {week:02d}/{year}"


def is_this_week(value: str | None) -> bool:
    dt = parse_date(value)
    if not dt:
        return False
    return dt.isocalendar()[:2] == date.today().isocalendar()[:2]


@app.template_filter("date_de")
def date_de(value: str | None) -> str:
    return fmt_date(value)


@app.template_filter("weekday_de")
def weekday_de(value: str | None) -> str:
    dt = parse_date(value)
    if not dt:
        return ""
    return ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]


@app.template_filter("week_de")
def week_de(value: str | None) -> str:
    return iso_week_label(value)


@app.context_processor
def inject_recipe_status_helpers() -> dict[str, Any]:
    return {
        "recipe_status_label": recipe_status_label,
        "recipe_status_css_class": recipe_status_css_class,
        "normalize_recipe_status": normalize_recipe_status,
        "STATUS_OPEN": STATUS_OPEN,
        "STATUS_PRESENT": STATUS_PRESENT,
        "STATUS_COOKED": STATUS_COOKED,
    }


@app.template_filter("stars")
def stars(value: int) -> str:
    value = int(value or 0)
    return "★" * value + "☆" * max(0, 5 - value)


@app.template_filter("tags_list")
def tags_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@app.template_filter("first_n")
def first_n(value, count: int = 5):
    try:
        return list(value)[: int(count)]
    except Exception:
        return []


@app.template_filter("ingredient_lines")
def ingredient_lines_filter(value: str | None) -> list[str]:
    return ingredients_json_to_lines(value)


@app.context_processor
def inject_app_brand() -> dict[str, Any]:
    return {"app_brand": APP_BRAND, "app_eyebrow": APP_EYEBROW, "nav_counts": recipe_counts()}


# ---------- preview helpers ----------
def detect_image_ext(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None


def preview_is_valid(preview_path: Path) -> bool:
    if not preview_path.exists() or preview_path.stat().st_size < 16:
        return False
    try:
        head = preview_path.read_bytes()[:16]
    except Exception:
        return False
    ext = detect_image_ext(head)
    if not ext:
        return False
    return preview_path.suffix.lower() == ext


def create_preview(pdf_path: Path) -> str | None:
    ensure_dirs()
    if not pdf_path.exists():
        return None
    preview_stem = PREVIEW_DIR / uuid4().hex
    png_path = preview_stem.with_suffix(".png")
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-singlefile",
                "-f",
                "1",
                "-l",
                "1",
                str(pdf_path),
                str(preview_stem),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if png_path.exists() and png_path.stat().st_size > 0:
            return png_path.name
    except Exception:
        pass
    return None


def store_uploaded_image(file_storage: FileStorage) -> str:
    ensure_dirs()
    original = secure_filename(file_storage.filename or "bild.png")
    ext = "." + original.rsplit(".", 1)[1].lower() if "." in original else ".png"
    filename = f"custom-{uuid4().hex}{ext}"
    target = PREVIEW_DIR / filename
    file_storage.save(target)
    return filename


# ---------- title parsing ----------
CONNECTOR_WORDS = ("dazu", "und", "mit", "auf", "an", "in", "zu", "aus", "von", "für", "ohne")
TITLE_FIXUPS: list[tuple[str, str]] = [
    (r"\bProte\s+in\b", "Protein"),
    (r"\bM\s+in\b", "Min"),
    (r"\bda\s+zu\b", "dazu"),
    (r"\bKum\s+in\s+da\s+zu\b", "Kumin dazu"),
    (r"\bKum\s+in\b", "Kumin"),
    (r"\bAir[ -]?Fryer\s*Zubereitung\b", "Air-Fryer-Zubereitung"),
    (r"\bOregano(?=dazu\b)", "Oregano "),
    (r"\bLimone(?=[A-ZÄÖÜ])", "Limone "),
]


def repair_joined_connector_words(text: str) -> str:
    def fix_token(match: re.Match[str]) -> str:
        token = match.group(0)
        lowered = token.lower()
        for word in CONNECTOR_WORDS:
            if lowered.endswith(word) and len(token) > len(word) + 3:
                base = token[:-len(word)]
                if len(base) > 4:
                    return base + " " + token[-len(word):]
        return token

    repaired = re.sub(r"\b[^\s]+\b", fix_token, text or "")
    return re.sub(r"\s+", " ", repaired).strip()


def clean_recipe_title(text: str) -> str:
    cleaned = repair_joined_connector_words((text or "").strip())
    for pattern, replacement in TITLE_FIXUPS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b([A-Za-zÄÖÜäöüß-]{4,})\s+(ung|en|er)\b", lambda m: m.group(1) + m.group(2), cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—")
    return cleaned


def split_title_and_subtitle(candidate: str) -> tuple[str, str]:
    candidate = clean_recipe_title(candidate)
    split_match = re.search(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])", candidate)
    if split_match and split_match.start() > 8:
        split_at = split_match.start()
        return candidate[:split_at].strip(), candidate[split_at:].strip()
    idx = candidate.lower().find(" dazu ")
    if idx > 12:
        return candidate[:idx].strip(), candidate[idx + 1 :].strip()
    return candidate.strip(), ""


def normalize_title(value: str) -> str:
    value = clean_recipe_title(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9äöüß]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


# ---------- ingredients ----------
UNITS = [
    "g", "kg", "ml", "l", "EL", "TL", "Stück", "Stk", "Stk.", "x", "Zehe", "Zehen", "Bund", "Beutel",
    "Packung", "Packungen", "Pck", "Pck.", "Dose", "Dosen", "Glas", "Becher", "Kugel", "Scheibe", "Scheiben",
    "Stange", "Stangen", "Zweig", "Zweige", "Prise", "Prisen", "Handvoll", "Paket", "Pakete", "Rolle", "Rollen",
]
INGREDIENT_SKIP_PATTERNS = [
    r"hello ?fresh",
    r"^zutaten$",
    r"^zubereitung$",
    r"^nährwerte$",
    r"kalorien",
    r"protein",
    r"min$",
    r"arbeitszeit",
    r"schwierigkeit",
    r"gesamtzeit",
    r"nutri",
    r"www\.",
    r"kochutensilien",
]


def parse_amount_token(token: str) -> float | None:
    token = token.strip().replace(",", ".")
    fractions = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}
    if token in fractions:
        return fractions[token]
    if token.isdigit():
        return float(token)
    try:
        return float(token)
    except ValueError:
        pass
    if "/" in token:
        try:
            num, den = token.split("/", 1)
            return float(num) / float(den)
        except Exception:
            return None
    return None


def looks_like_ingredient_line(line: str) -> bool:
    low = line.lower().strip()
    if len(low) < 2 or len(low) > 90:
        return False
    if any(re.search(pattern, low) for pattern in INGREDIENT_SKIP_PATTERNS):
        return False
    if re.fullmatch(r"\d+", low):
        return False
    if re.search(r"\b(kcal|protein|kohlenhydrate|fett)\b", low):
        return False
    return True


def parse_ingredient_line(line: str) -> dict[str, Any] | None:
    line = clean_pdf_cell(line)
    line = re.sub(r"^[•·\-–—]+\s*", "", line).strip()
    if not looks_like_ingredient_line(line):
        return None

    patterns = [
        r"^(?P<amount>\d+[\.,]?\d*|[½¼¾⅓⅔])\s*[xX]\s+(?P<name>.+)$",
        r"^(?P<amount>\d+[\.,]?\d*|[½¼¾⅓⅔])\s+(?P<unit>[A-Za-zÄÖÜäöüß\.]+)\s+(?P<name>.+)$",
        r"^(?P<amount>\d+[\.,]?\d*|[½¼¾⅓⅔])\s+(?P<name>.+)$",
    ]
    valid_units = {u.lower().rstrip('.') for u in UNITS}
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            amount = parse_amount_token(match.group("amount"))
            name = match.group("name").strip(" ,")
            unit = (match.groupdict().get("unit") or "x").strip(" .")
            if match.groupdict().get("unit") and unit.lower().rstrip('.') not in valid_units:
                if pattern != patterns[-1]:
                    continue
                unit = ""
            if pattern == patterns[-1]:
                unit = ""
            if name and amount is not None:
                return {"name": name, "amount": amount, "unit": unit, "text": line}

    if len(line.split()) <= 6:
        return {"name": line, "amount": None, "unit": "", "text": line}
    return None


def parse_ingredients_from_text(text: str, base_servings: int = 3) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        ingredient = parse_ingredient_line(line)
        if not ingredient:
            continue
        key = normalize_title(ingredient.get("name") or ingredient.get("text") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        ingredient["base_servings"] = base_servings
        results.append(ingredient)
    return results[:30]




def clean_pdf_cell(value: str | None) -> str:
    value = (value or "").replace("\n", " ").replace("\t", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" |•*- ")


def strip_amount_prefix(line: str) -> str:
    line = clean_pdf_cell(line)
    patterns = [
        r"^(?:ca\.?\s*)?(?:\d+[\.,]?\d*|[½¼¾⅓⅔])\s*[xX]\s+(?P<name>.+)$",
        r"^(?:ca\.?\s*)?(?:\d+[\.,]?\d*|[½¼¾⅓⅔])\s+(?:[A-Za-zÄÖÜäöüß.]+)\s+(?P<name>.+)$",
        r"^(?:ca\.?\s*)?(?:\d+[\.,]?\d*|[½¼¾⅓⅔])\s+(?P<name>.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            return clean_pdf_cell(match.group("name"))
    return line


def is_base_ingredient_name(name: str) -> bool:
    return normalize_title(name) in COMMON_BASE_INGREDIENTS


def is_base_ingredient_item(ingredient: dict[str, Any]) -> bool:
    name = ingredient.get("name") or ingredient.get("text") or ""
    return is_base_ingredient_name(name)


def learn_ingredient_correction_from_lines(original_line: str, edited_line: str) -> bool:
    original_line = clean_pdf_cell(original_line)
    edited_line = clean_pdf_cell(edited_line)
    if not original_line or not edited_line or original_line == edited_line:
        return False
    original_parsed = parse_ingredient_line(original_line)
    edited_parsed = parse_ingredient_line(edited_line)
    if original_parsed and edited_parsed:
        original_amount = original_parsed.get("amount")
        edited_amount = edited_parsed.get("amount")
        original_unit = clean_pdf_cell(original_parsed.get("unit") or "").lower().rstrip(".")
        edited_unit = clean_pdf_cell(edited_parsed.get("unit") or "").lower().rstrip(".")
        if original_amount == edited_amount and original_unit == edited_unit:
            return save_ingredient_name_correction(original_parsed.get("name") or "", edited_parsed.get("name") or "")
    return save_ingredient_name_correction(strip_amount_prefix(original_line), strip_amount_prefix(edited_line))


COMMON_BASE_INGREDIENTS = {
    "salz", "pfeffer", "wasser", "öl", "olivenöl", "butter", "milch", "zucker", "essig",
    "weinessig", "balsamico", "honig", "mehl", "ei", "eier", "senf"
}
UTENSIL_WORDS = {
    "kochutensilien", "gemüseschäler", "messbecher", "topf", "deckel", "schüssel", "pfanne",
    "messer", "küchenpapier", "sieb", "dose", "reibe", "schäler"
}
NON_INGREDIENT_NAME_PATTERNS = [
    r"\bkochutensilien\b",
    r"\b(zutaten|zubereitung|nährwerte|portion|los geht|guten appetit)\b",
    r"\b(gemüseschäler|messbecher|topf|deckel|schüssel|pfanne|messer|küchenpapier|sieb|reibe|schäler)\b",
]
INGREDIENT_NAME_FIXUPS: list[tuple[str, str]] = [
    (r"\bHahnchen\b", "Hähnchen"),
    (r"\bHuhnerbruhe\b", "Hühnerbrühe"),
    (r"\bMaisstarke\b", "Maisstärke"),
    (r"\bSesamol\b", "Sesamöl"),
    (r"\bZitronenthymi\s*an\b", "Zitronenthymian"),
    (r"\bMil\b", "Milch"),
    (r"\bMusk\b", "Muskat"),
    (r"\bHähnchengeschnetzelt\b", "Hähnchengeschnetzeltes"),
    (r"\bHahnchenbrustfilet\s*in\s*Lake\b", "Hähnchenbrustfilet in Lake"),
    (r"\bHahnchenbrustfiletin\s*Lake\b", "Hähnchenbrustfilet in Lake"),
    (r"\bim Kühlbeute\b", "im Kühlbeutel"),
    (r"\bTopfmit\b", "Topf mit"),
    (r"\bHähnchenbrustfiletinLake\b", "Hähnchenbrustfilet in Lake"),
    (r"\bPetersilie\s+glatt\b", "Petersilie, glatt"),
    (r"\bZitrone\s*,\s*gewachst\b", "Zitrone, gewachst"),
    (r"\bRinderhackfleischzubereitung\b", "Bio Rinderhackfleischzubereitung"),
    (r"\brote\s+Zwiebe\b", "rote Zwiebel"),
    (r"\bSahnejoghurt\s*,?\s*Bio\b", "Sahnejoghurt, Bio"),
    (r"\bHartkase\b", "Hartkäse"),
    (r"\bGewurzmischung\b", "Gewürzmischung"),
    (r"\bAprikosenchutnev\b", "Aprikosenchutney"),
]


def is_non_ingredient_name(name: str) -> bool:
    low = clean_pdf_cell(name).lower()
    if not low:
        return True
    if any(re.search(pattern, low) for pattern in NON_INGREDIENT_NAME_PATTERNS):
        return True
    if low in {"2p", "3p", "4p"}:
        return True
    return False


def is_plausible_base_ingredient_name(name: str) -> bool:
    low = normalize_title(name)
    if not low or is_non_ingredient_name(low):
        return False
    if low in COMMON_BASE_INGREDIENTS:
        return True
    return False


def _fix_hello_mix_name(name: str) -> str:
    low = name.lower()
    if "hello" not in low:
        return name
    if "gewürzmischung hello" in low:
        return name
    if any(token in low for token in ["misch", "schung", "rzml", "gew"]):
        m = re.search(r"hello\s+(.+)$", name, flags=re.IGNORECASE)
        suffix = clean_pdf_cell(m.group(1)) if m else ""
        return clean_pdf_cell(f"Gewürzmischung Hello {suffix}" if suffix else "Gewürzmischung Hello")
    return name


def normalize_ingredient_name(name: str) -> str:
    name = clean_pdf_cell(name or "")
    name = re.sub(r"\d+\)", "", name)
    name = re.sub(r'["“”„]', '', name)
    name = re.sub(r"\*+", "", name)
    name = re.sub(r"[\[\]{}<>]", " ", name)
    name = re.sub(r"[^0-9A-Za-zÄÖÜäöüß,./() +&:-]+", " ", name)
    name = re.sub(rf"(?<=[A-Za-zÄÖÜäöüß])(?:{OCR_COUNTRY_CODES})(?=(?:|\s|[\[\]|/]))", "", name)
    name = re.sub(rf"(?<=[a-zäöüß])(?:{OCR_COUNTRY_CODES})$", "", name)
    name = re.sub(rf"(?:(?:{OCR_COUNTRY_CODES})(?:\s*\|\s*(?:{OCR_COUNTRY_CODES}))+)", "", name)
    name = re.sub(rf"(?:\s+(?:{OCR_COUNTRY_CODES}))(?=(?:\s|$))", "", name)
    name = re.sub(r"\s*\|\s*", " ", name)
    name = re.sub(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])", " ", name)
    name = re.sub(r"(?<=filet)in(?=Lake)", " in ", name, flags=re.IGNORECASE)
    name = re.sub(r"(?<=\d)(?=[A-Za-zÄÖÜäöüß])", " ", name)
    name = re.sub(r"(?<=[A-Za-zÄÖÜäöüß])(?=\d)", " ", name)
    name = re.sub(r"(?<=\w)/(?!\s)", " / ", name)
    name = re.sub(r"(?<!\s)/(?!\s)", " / ", name)
    name = re.sub(r"(?<=[a-zäöüß])(?=(?:Bio|leicht|glatt|gewachst|gerebelt|gerieben|in|mit|ohne))", " ", name)
    name = re.sub(r"(?:DE|NL|IT|EG|IL|ES|FR|AT|CH|BE|PL|PT|HU|CZ|SK|SI|HR|RO|BG|MA|ZA|AR)\s*(?:\[.*)?$", "", name)
    name = re.sub(r"\s+", " ", name).strip(" ,;:|-")
    name = re.sub(r"([A-Za-zÄÖÜäöüß]{4,})\s+([a-zäöüß]{1,3})", lambda m: f"{m.group(1)}{m.group(2)}", name)
    name = _fix_hello_mix_name(name)
    for pattern, replacement in INGREDIENT_NAME_FIXUPS:
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    learned = get_learned_ingredient_correction(name)
    if learned:
        name = learned
    name = re.sub(r"\s+", " ", name).strip(" ,;:|-")
    return name


def ingredient_from_name_amount(name: str, amount_text: str, base_servings: int) -> dict[str, Any] | None:
    name = normalize_ingredient_name(name)
    amount_text = clean_pdf_cell(amount_text)
    if not name or is_non_ingredient_name(name):
        return None
    line = f"{amount_text} {name}".strip() if amount_text else name
    parsed = parse_ingredient_line(line)
    if parsed is None:
        parsed = {"name": name, "amount": None, "unit": "", "text": line}
    parsed["base_servings"] = base_servings
    return parsed


def _qty_candidate_from_cells(cells: list[str], preferred_index: int | None = None) -> str:
    if preferred_index is not None and preferred_index < len(cells):
        cand = clean_pdf_cell(cells[preferred_index])
        if cand and re.search(r"\d", cand):
            return cand
    numeric = [clean_pdf_cell(c) for c in cells[1:] if clean_pdf_cell(c) and re.search(r"\d", clean_pdf_cell(c))]
    if len(numeric) >= 2:
        return numeric[1]
    if numeric:
        return numeric[0]
    return ""


def parse_ingredient_amount_row(line: str, base_servings: int) -> dict[str, Any] | None:
    line = clean_pdf_cell(line)
    if not line:
        return None
    m = re.match(r"^(?P<name>.+?)\s+(?P<a2>(?:\d+[\.,]?\d*|[½¼¾⅓⅔])(?:\s*[A-Za-zÄÖÜäöüß%/.-]+)?(?:\s*\*+)?)\s+(?P<a3>(?:\d+[\.,]?\d*|[½¼¾⅓⅔])(?:\s*[A-Za-zÄÖÜäöüß%/.-]+)?(?:\s*\*+)?)\s+(?P<a4>(?:\d+[\.,]?\d*|[½¼¾⅓⅔])(?:\s*[A-Za-zÄÖÜäöüß%/.-]+)?(?:\s*\*+)?)$", line)
    if not m:
        return None
    return ingredient_from_name_amount(m.group('name'), m.group('a3'), base_servings)


def _row_words_to_text(row_words: list[dict[str, Any]]) -> str:
    ordered = sorted(row_words, key=lambda w: float(w.get("x0", 0)))
    return clean_pdf_cell(" ".join((w.get("text") or "") for w in ordered))


def _extract_left_rows(page, x_ratio: float = 0.33) -> list[str]:
    try:
        words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False, use_text_flow=False) or []
    except Exception:
        return []
    left_words = [w for w in words if float(w.get("x0", 0)) <= page.width * x_ratio]
    if not left_words:
        return []
    left_words.sort(key=lambda w: (float(w.get("top", 0)), float(w.get("x0", 0))))
    rows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_top: float | None = None
    for word in left_words:
        top = float(word.get("top", 0))
        if current_top is None or abs(top - current_top) <= 3.5:
            current.append(word)
            current_top = top if current_top is None else min(current_top, top)
        else:
            rows.append(current)
            current = [word]
            current_top = top
    if current:
        rows.append(current)
    texts = [_row_words_to_text(row) for row in rows]
    return [t for t in texts if t]


def parse_ingredients_from_left_column(page, base_servings: int = 3) -> list[dict[str, Any]]:
    ingredients: list[dict[str, Any]] = []
    seen: set[str] = set()
    row_lines = _extract_left_rows(page)
    left_text = "\n".join(row_lines)
    if not left_text:
        try:
            left = page.crop((0, 0, page.width * 0.44, page.height))
            left_text = left.extract_text() or ""
            row_lines = [clean_pdf_cell(ln) for ln in left_text.splitlines() if clean_pdf_cell(ln)]
        except Exception:
            return []
    base_match = re.search(rf"Basiszutaten aus Deiner Küche\s*(.+?)\s*Zutaten\s*2\s*{DASH_CLASS}\s*4\s*Personen", left_text, flags=re.IGNORECASE | re.DOTALL)
    if base_match:
        base_text = clean_pdf_cell(base_match.group(1))
        for part in re.split(r"[,;]", base_text):
            name = clean_pdf_cell(part).strip('*')
            if not name:
                continue
            item = ingredient_from_name_amount(name, "", base_servings)
            key = normalize_title(item.get('name') if item else name)
            if item and key and key not in seen:
                seen.add(key)
                ingredients.append(item)
    start_idx = None
    for idx, line in enumerate(row_lines):
        low = line.lower()
        if "zutaten" in low and "personen" in low:
            start_idx = idx
            break
    if start_idx is None:
        return ingredients[:50]
    data_lines = row_lines[start_idx + 1:]
    for line in data_lines:
        low = line.lower()
        if any(token in low for token in ["durchschnittliche nährwerte", "allergene", "los geht", "bitte beachte", "kcal", "portion"]):
            break
        if any(token in low for token in ["2p", "3p", "4p"]):
            continue
        if re.search(r"(schneiden|formen|garen|anrichten|verrühren|erhitzen|vorheizen|nudelpfanne zubereiten|orzo kochen|orzo verfeinern)", low):
            continue
        item = parse_ingredient_amount_row(line, base_servings)
        if not item:
            continue
        key = normalize_title(item.get('name') or item.get('text') or "")
        if key and key not in seen:
            seen.add(key)
            ingredients.append(item)
    return ingredients[:50]


OCR_COUNTRY_CODES = "DE|NL|EG|IL|ES|FR|IT|AT|CH|BE|PL|PT|HU|CZ|SK|SI|HR|RO|BG|MA|ZA|AR"


def normalize_ocr_amount_text(value: str) -> str:
    value = clean_pdf_cell(value).lower()
    if not value:
        return ""
    value = value.replace("¢", "").replace("€", "").replace("°", "")
    value = value.replace("**", "").replace("*", "")
    value = re.sub(r"[^0-9a-z½¼¾⅓⅔/.,]+", "", value)
    if re.fullmatch(r"\d+", value):
        if len(value) >= 2 and value.endswith("8"):
            return f"{value[:-1]} g"
        return f"{value} x"
    m = re.fullmatch(r"(\d+(?:[\.,]\d+)?)(g|kg|ml|l)", value)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return value


def _is_ocr_noise_name(text: str) -> bool:
    raw = clean_pdf_cell(text)
    if not raw:
        return True
    compact = raw.replace(" ", "")
    if re.fullmatch(r"(?:\d+\)\s*)+", raw):
        return True
    parts = [part for part in re.split(r"[\s|]+", raw.upper()) if part]
    if parts and all(re.fullmatch(rf"(?:{OCR_COUNTRY_CODES})", part) for part in parts):
        return True
    if compact in {"2P3P4P", "2P3PAP", "2P3P4PAP"}:
        return True
    if is_non_ingredient_name(raw):
        return True
    letters = re.sub(r"[^A-Za-zÄÖÜäöüß]", "", raw)
    if letters and len(letters) >= 10 and raw.upper() == raw and raw.lower() != raw:
        return True
    return False


def _ocr_words_to_lines(data: dict[str, list[Any]]) -> list[dict[str, Any]]:
    lines_map: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    n = len(data.get("text", []))
    for i in range(n):
        text = clean_pdf_cell(str(data["text"][i] or ""))
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1
        if not text or conf < 0:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines_map.setdefault(key, []).append(
            {
                "text": text,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
            }
        )
    lines: list[dict[str, Any]] = []
    for words in lines_map.values():
        ordered = sorted(words, key=lambda w: w["left"])
        lines.append({
            "top": min(w["top"] for w in ordered),
            "words": ordered,
            "text": clean_pdf_cell(" ".join(w["text"] for w in ordered)),
        })
    return sorted(lines, key=lambda line: line["top"])


def _ordered_ocr_amount_candidates(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    for token in tokens:
        token = clean_pdf_cell(token)
        if not token:
            continue
        if re.fullmatch(r"[gGlLmMkKxX]+", token) and merged:
            merged[-1] = f"{merged[-1]}{token}"
            continue
        if re.search(r"\d", token):
            merged.append(token)
    normalized = [normalize_ocr_amount_text(token) for token in merged]
    return [token for token in normalized if token]


def _extract_ocr_columns(line: dict[str, Any], image_width: int) -> tuple[str, str, str, str]:
    words = line.get("words") or []
    if not words:
        return "", "", "", ""
    name_cutoff = image_width * 0.50
    name_words: list[str] = []
    qty_words: list[str] = []
    for word in words:
        center_x = word["left"] + word["width"] / 2
        text = word["text"]
        if center_x < name_cutoff:
            name_words.append(text)
        else:
            qty_words.append(text)
    qty_candidates = _ordered_ocr_amount_candidates(qty_words)
    qty2 = qty_candidates[0] if len(qty_candidates) >= 1 else ""
    qty3 = qty_candidates[1] if len(qty_candidates) >= 2 else (qty_candidates[0] if len(qty_candidates) == 1 else "")
    qty4 = qty_candidates[2] if len(qty_candidates) >= 3 else (qty_candidates[-1] if qty_candidates else "")
    return clean_pdf_cell(" ".join(name_words)), qty2, qty3, qty4


def preprocess_ingredients_ocr_image(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(image.convert("L"))
    return gray.resize((gray.width * 2, gray.height * 2))


def parse_ingredients_from_ocr(pdf_path: Path, base_servings: int = 3) -> list[dict[str, Any]]:
    if pytesseract is None or Image is None or ImageOps is None:
        return []
    ingredients: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with tempfile.TemporaryDirectory(prefix="hfocr_") as tmpdir:
            prefix = str(Path(tmpdir) / "page")
            subprocess.run(
                ["pdftoppm", "-f", "2", "-l", "2", "-r", "220", "-png", str(pdf_path), prefix],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            rendered = sorted(Path(tmpdir).glob("page-*.png"))
            if not rendered:
                return []
            page_image = Image.open(rendered[0])
            width, height = page_image.size
            crop = page_image.crop((int(width * 0.012), int(height * 0.08), int(width * 0.24), int(height * 0.43)))
            ocr_image = preprocess_ingredients_ocr_image(crop)
            data = pytesseract.image_to_data(
                ocr_image,
                lang="deu+eng",
                config="--psm 6 -c preserve_interword_spaces=1",
                output_type=pytesseract.Output.DICT,
            )
    except Exception:
        return []

    lines = _ocr_words_to_lines(data)
    if not lines:
        return []

    in_ingredients = False
    pending_name = ""
    base_parts: list[str] = []
    skip_until_ingredients = False

    for line in lines:
        text = clean_pdf_cell(line.get("text"))
        low = text.lower()
        if not text:
            continue
        if "basiszutaten" in low:
            skip_until_ingredients = False
            continue
        if "kochutensilien" in low:
            skip_until_ingredients = True
            continue
        if "zutaten" in low and "personen" in low:
            in_ingredients = True
            skip_until_ingredients = False
            if base_parts:
                for part in re.split(r"[,;]", " ".join(base_parts)):
                    name = clean_pdf_cell(part).strip("*")
                    if not is_plausible_base_ingredient_name(name):
                        continue
                    item = ingredient_from_name_amount(name, "", base_servings)
                    key = normalize_title(item.get("name") if item else name)
                    if item and key and key not in seen:
                        seen.add(key)
                        ingredients.append(item)
            continue
        if not in_ingredients:
            if skip_until_ingredients:
                continue
            if text and "zutaten" not in low and not re.search(r"\b2p\b|\b3p\b|\b4p\b|\bap\b", low):
                if any(ch.isalpha() for ch in text) and text.count(",") >= 1:
                    base_parts.append(text)
            continue
        if any(token in low for token in ["durchschnittliche", "nährwerte", "beachte die benötigte menge"]):
            break
        if re.search(r"\b2p\b", low) and re.search(r"\b3p\b", low):
            continue
        if is_non_ingredient_name(text):
            continue

        name_text, _qty2, qty3, _qty4 = _extract_ocr_columns(line, ocr_image.width)
        name_text = clean_pdf_cell(name_text)

        if _is_ocr_noise_name(name_text):
            if not qty3:
                continue
            name_text = ""

        if not qty3:
            if name_text and not is_non_ingredient_name(name_text):
                pending_name = clean_pdf_cell(f"{pending_name} {name_text}") if pending_name else name_text
            continue

        full_name = clean_pdf_cell(f"{pending_name} {name_text}") if pending_name else name_text
        pending_name = ""
        if is_non_ingredient_name(full_name):
            continue
        item = ingredient_from_name_amount(full_name, qty3, base_servings)
        key = normalize_title(item.get("name") if item else full_name)
        if item and key and key not in seen:
            seen.add(key)
            ingredients.append(item)

    return ingredients[:50]


def parse_ingredients_from_pdf_tables(pdf_path: Path, base_servings: int = 3) -> list[dict[str, Any]]:
    ingredients: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:3]:
                if not ingredients:
                    ingredients.extend(parse_ingredients_from_left_column(page, base_servings=base_servings))
                    seen.update(normalize_title(item.get("name") or item.get("text") or "") for item in ingredients if normalize_title(item.get("name") or item.get("text") or ""))
                page_text = page.extract_text() or ""
                base_match = re.search(rf"Basiszutaten aus Deiner Küche\s*(.+?)\s*Zutaten\s*2\s*{DASH_CLASS}\s*4\s*Personen", page_text, flags=re.IGNORECASE | re.DOTALL)
                if base_match:
                    base_text = clean_pdf_cell(base_match.group(1))
                    for part in re.split(r"[,;]", base_text):
                        name = clean_pdf_cell(part).strip("*")
                        if not name:
                            continue
                        item = ingredient_from_name_amount(name, "", base_servings)
                        key = normalize_title(item.get("name") if item else name)
                        if item and key and key not in seen:
                            seen.add(key)
                            ingredients.append(item)
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []
                for table in tables:
                    if not table:
                        continue
                    header_idx = None
                    idx3 = None
                    for i, row in enumerate(table):
                        cells = [clean_pdf_cell(c) for c in (row or [])]
                        joined = " ".join(cells).lower()
                        if "2p" in joined and "3p" in joined:
                            header_idx = i
                            for j, cell in enumerate(cells):
                                if cell.lower() == "3p":
                                    idx3 = j
                                    break
                            break
                    if header_idx is None:
                        continue
                    for row in table[header_idx + 1:]:
                        cells = [clean_pdf_cell(c) for c in (row or [])]
                        if not any(cells):
                            continue
                        joined = " ".join(cells)
                        low = joined.lower()
                        if any(token in low for token in ["durchschnittliche nährwerte", "nährwerte", "allergene", "los geht", "zubereitung"]):
                            break
                        name = cells[0] if cells else ""
                        if not name or re.fullmatch(r"\d+", name):
                            continue
                        item = ingredient_from_name_amount(name, _qty_candidate_from_cells(cells, idx3), base_servings)
                        key = normalize_title(item.get("name") if item else name)
                        if item and key and key not in seen:
                            seen.add(key)
                            ingredients.append(item)
                if ingredients:
                    continue
                sec = re.search(rf"Zutaten\s*2\s*{DASH_CLASS}\s*4\s*Personen(.+?)(?:Durchschnittliche Nährwerte|Allergene|Los geht|Zubereitung|Bitte beachte)", page_text, flags=re.IGNORECASE | re.DOTALL)
                if sec:
                    lines = [clean_pdf_cell(ln) for ln in sec.group(1).splitlines() if clean_pdf_cell(ln)]
                    i = 0
                    while i < len(lines):
                        name = lines[i]
                        if re.search(r"\b(?:2P|3P|4P)\b", name):
                            i += 1
                            continue
                        qty = ""
                        if i + 1 < len(lines) and re.search(r"\d", lines[i + 1]):
                            qty = lines[i + 1]
                            i += 1
                        item = ingredient_from_name_amount(name, qty, base_servings)
                        key = normalize_title(item.get("name") if item else name)
                        if item and key and key not in seen:
                            seen.add(key)
                            ingredients.append(item)
                        i += 1
    except Exception:
        return []
    return ingredients[:50]

def ingredients_to_json(ingredients: list[dict[str, Any]]) -> str:
    return json.dumps(ingredients, ensure_ascii=False)


def ingredients_from_json(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        data = json.loads(value)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


SUSPICIOUS_INGREDIENT_WORDS = {
    "schneiden", "formen", "garen", "kochen", "anrichten", "backen", "vermengen",
    "abschmecken", "würzen", "verteilen", "erhitzen", "wasche", "tupfe", "trocken",
    "kochutensilien", "messbecher", "topf", "deckel", "schüssel", "pfanne", "küchenpapier"
}


def ingredients_need_refresh(items: list[dict[str, Any]]) -> bool:
    if not items:
        return True
    texts = [clean_recipe_title((item.get("name") or item.get("text") or "").strip()) for item in items]
    joined = " ".join(texts).lower()
    if any(word in joined for word in SUSPICIOUS_INGREDIENT_WORDS):
        return True
    if len(items) < 4:
        return True
    if len(items) <= 2 and any(len(text.split()) > 5 for text in texts):
        return True
    if any(re.search(r"\b(schneiden|formen|garen|kochen|anrichten|kochutensilien)\b", text.lower()) for text in texts):
        return True
    amount_count = sum(1 for item in items if item.get("amount") not in (None, ""))
    if amount_count < max(2, len(items) // 3):
        return True
    suspicious_name_count = sum(1 for text in texts if is_non_ingredient_name(text))
    if suspicious_name_count >= 1:
        return True
    return False


def format_scaled_amount(amount: float) -> str:
    if abs(amount - round(amount)) < 0.01:
        return str(int(round(amount)))
    rounded = round(amount, 1)
    return str(rounded).replace(".", ",")


def ingredient_item_text(ingredient: dict[str, Any], servings: int) -> str:
    name = normalize_ingredient_name((ingredient.get("name") or ingredient.get("text") or "").strip())
    unit = clean_pdf_cell(ingredient.get("unit") or "")
    base_servings = int(ingredient.get("base_servings") or ingredient.get("servings") or 3 or 3)
    amount = ingredient.get("amount")
    if amount is None:
        return name
    scaled = float(amount) * max(servings, 1) / max(base_servings, 1)
    amount_text = format_scaled_amount(scaled)
    if unit.lower().rstrip('.') in {"x", "stück", "stk"}:
        return f"{amount_text} x {name}"
    if unit:
        return f"{amount_text} {unit} {name}".strip()
    return f"{amount_text} x {name}"


def ingredients_json_to_lines(value: str | None) -> list[str]:
    ingredients = ingredients_from_json(value)
    lines: list[str] = []
    for item in ingredients:
        text = item.get("text") or ingredient_item_text(item, int(item.get("base_servings") or 3))
        if text:
            lines.append(text)
    return lines


def parse_ingredients_text_block(text: str, base_servings: int) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    ingredients: list[dict[str, Any]] = []
    for line in lines:
        parsed = parse_ingredient_line(line)
        if parsed is None:
            parsed = {"name": normalize_ingredient_name(line), "amount": None, "unit": "", "text": clean_pdf_cell(line)}
        else:
            parsed["name"] = normalize_ingredient_name(parsed.get("name") or "")
            parsed["text"] = ingredient_item_text({**parsed, "base_servings": base_servings}, base_servings)
        parsed["base_servings"] = base_servings
        ingredients.append(parsed)
    return ingredients_to_json(ingredients)


# ---------- PDF parsing ----------

def parse_pdf(pdf_path: Path, original_filename: str, base_servings: int = 3) -> dict[str, Any]:
    title = Path(original_filename).stem.replace("_", " ").replace("-", " ").strip()
    subtitle = ""
    recipe_number = ""
    search_text = title
    tags: list[str] = []
    ingredients_json = "[]"

    try:
        reader = PdfReader(str(pdf_path))
        text_parts: list[str] = []
        for page in reader.pages[:3]:
            page_text = page.extract_text() or ""
            if page_text:
                text_parts.append(page_text)
        full_text = "\n".join(text_parts)
        search_text = full_text or title
        lines = [clean_recipe_title(ln.strip()) for ln in full_text.splitlines() if ln.strip()]
        clean_lines = [ln for ln in lines if not ln.lower().startswith("hellofresh")]
        if clean_lines:
            for line in clean_lines:
                if len(line) >= 8 and not re.fullmatch(r"\d+", line):
                    title = line
                    break
        title, subtitle = split_title_and_subtitle(title)
        if clean_lines and not subtitle:
            title_index = clean_lines.index(title) if title in clean_lines else 0
            for line in clean_lines[title_index + 1 : title_index + 6]:
                if len(line) >= 8 and len(line) <= 120 and line != title:
                    subtitle = clean_recipe_title(line)
                    break
        recipe_candidates = re.findall(r"\b(\d{2})\b", "\n".join(clean_lines[:12]))
        if recipe_candidates:
            recipe_number = recipe_candidates[0]
        tag_map = {
            "reis": "Reis",
            "pasta": "Pasta",
            "nudel": "Nudeln",
            "schnell": "Schnell",
            "famil": "Family",
            "vegetar": "Vegetarisch",
            "viel gemüse": "Viel Gemüse",
            "protein": "High Protein",
            "hähnchen": "Hähnchen",
            "kartoff": "Kartoffeln",
            "brokkoli": "Brokkoli",
        }
        low = full_text.lower()
        for needle, label in tag_map.items():
            if needle in low and label not in tags:
                tags.append(label)
        ingredients = parse_ingredients_from_pdf_tables(pdf_path, base_servings=base_servings)
        if not ingredients or ingredients_need_refresh(ingredients):
            ocr_ingredients = parse_ingredients_from_ocr(pdf_path, base_servings=base_servings)
            if ocr_ingredients and (not ingredients or ingredients_need_refresh(ocr_ingredients) is False):
                ingredients = ocr_ingredients
        if not ingredients:
            ingredients = []
        ingredients_json = ingredients_to_json(ingredients)
    except Exception:
        ingredients_json = "[]"

    return {
        "title": title[:140] or original_filename,
        "subtitle": subtitle[:180],
        "recipe_number": recipe_number[:10],
        "search_text": search_text,
        "tags": ", ".join(tags),
        "ingredients_json": ingredients_json,
    }


def extract_calories(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d{2,4})\s*kcal\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_minutes(text: str | None) -> str:
    if not text:
        return ""
    match = re.search(r"(\d{1,2}\s*[–-]\s*\d{1,2}\s*Min|\d{1,2}\s*Min)", text, flags=re.IGNORECASE)
    return match.group(1).replace("–", "-").strip() if match else ""


# ---------- recipe CRUD ----------
def recipe_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["title"] = clean_recipe_title(d.get("title") or "")
    d["subtitle"] = clean_recipe_title(d.get("subtitle") or "")
    delivered = d.get("delivered_at") or ""
    cooked = d.get("cooked_at") or ""
    search_text = d.get("search_text") or ""
    d["week_label"] = iso_week_label(delivered)
    d["this_week"] = is_this_week(delivered)
    delivery_date = parse_date(delivered)
    d["is_future_delivery"] = bool(delivery_date and delivery_date > date.today())
    d["available_from"] = delivery_date.isoformat() if d["is_future_delivery"] else ""
    d["delivery_days"] = (delivery_date - date.today()).days if d["is_future_delivery"] and delivery_date else 0
    d["last_cooked_label"] = fmt_date(cooked)
    d["calories"] = extract_calories(search_text)
    d["minutes"] = extract_minutes(search_text)
    d["status"] = normalize_recipe_status(d.get("status"), STATUS_OPEN)
    d["is_custom"] = bool(d.get("is_custom"))
    return d


def all_active_recipes() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = list(conn.execute("SELECT * FROM recipes WHERE archive = 0").fetchall())
    recipes = [recipe_to_dict(row) for row in rows]
    recipes.sort(key=lambda row: (row.get("delivered_at") or row.get("uploaded_at") or "", row.get("uploaded_at") or ""), reverse=True)
    recipes.sort(key=lambda row: bool(row.get("is_future_delivery")))
    return recipes


def find_recipe_by_title(title: str) -> sqlite3.Row | None:
    conn = get_conn()
    normalized = normalize_title(title)
    if not normalized:
        return None
    rows = conn.execute("SELECT * FROM recipes WHERE archive = 0").fetchall()
    for row in rows:
        if normalize_title(row["title"]) == normalized:
            return row
    return None


def duplicate_group_key(title: str) -> str:
    normalized = normalize_title(title)
    return f"title:{normalized}" if normalized else ""


def sync_duplicate_groups() -> None:
    """Keep title-based variant groups current without touching manually separated recipes."""
    conn = get_conn()
    rows = conn.execute("SELECT id, title, duplicate_group, duplicate_detached FROM recipes WHERE archive = 0").fetchall()
    changed = False
    for row in rows:
        if int(row["duplicate_detached"] or 0):
            continue
        wanted = duplicate_group_key(row["title"] or "")
        if wanted and (row["duplicate_group"] or "") != wanted:
            conn.execute("UPDATE recipes SET duplicate_group = ? WHERE id = ?", (wanted, row["id"]))
            changed = True
    if changed:
        conn.commit()


def grouped_recipe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return recipe cards, combining same-title variants into swipeable groups."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for recipe in rows:
        group = recipe.get("duplicate_group") or duplicate_group_key(recipe.get("title") or "") or f"recipe:{recipe.get('id')}"
        if recipe.get("duplicate_detached"):
            group = recipe.get("duplicate_group") or f"recipe:{recipe.get('id')}"
        if group not in buckets:
            buckets[group] = []
            order.append(group)
        buckets[group].append(recipe)
    result: list[dict[str, Any]] = []
    for group in order:
        variants = buckets[group]
        variants.sort(key=lambda r: (r.get("delivered_at") or r.get("uploaded_at") or "", r.get("uploaded_at") or ""), reverse=True)
        variants.sort(key=lambda r: bool(r.get("is_future_delivery")))
        primary = variants[0]
        result.append({
            "group_id": group,
            "count": len(variants),
            "title": primary.get("title") or "Rezept",
            "variants": variants,
            "is_group": len(variants) > 1,
        })
    return result


def detach_recipe_from_group(recipe_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT id FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE recipes SET duplicate_detached = 1, duplicate_group = ? WHERE id = ?",
        (f"manual:{uuid4().hex}", recipe_id),
    )
    conn.commit()
    return True


def _duplicate_candidate_meta_path(token: str) -> Path:
    safe = secure_filename(token).replace(".", "")
    return DUPLICATE_DIR / f"{safe}.json"


def _duplicate_candidate_pdf_path(token: str) -> Path:
    safe = secure_filename(token).replace(".", "")
    return DUPLICATE_DIR / f"{safe}.pdf"


def save_duplicate_candidate(temp_path: Path, original_filename: str, metadata: dict[str, Any], existing: sqlite3.Row, delivered_at: str | None, import_source: str, status: str) -> str:
    """Keep a skipped duplicate so the user can import it anyway if it was detected wrongly."""
    ensure_dirs()
    token = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:10]}"
    pdf_path = _duplicate_candidate_pdf_path(token)
    meta_path = _duplicate_candidate_meta_path(token)
    preview_name = create_preview(temp_path) or ""
    if temp_path.exists():
        move_file_safe(temp_path, pdf_path)
    meta = {
        "token": token,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "original_filename": secure_filename(original_filename) or "rezept.pdf",
        "detected_title": metadata.get("title", ""),
        "detected_subtitle": metadata.get("subtitle", ""),
        "detected_tags": metadata.get("tags", ""),
        "candidate_preview_filename": preview_name,
        "delivered_at": delivered_at or "",
        "status": normalize_recipe_status(status, STATUS_OPEN),
        "import_source": import_source or "upload",
        "existing_id": int(existing["id"]),
        "existing_title": existing["title"],
        "existing_subtitle": existing["subtitle"] or "",
        "existing_uploaded_at": existing["uploaded_at"] or "",
        "existing_status": normalize_recipe_status(existing["status"], STATUS_OPEN),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return token


def pending_duplicate_candidates() -> list[dict[str, Any]]:
    ensure_dirs()
    conn = get_conn()
    candidates: list[dict[str, Any]] = []
    for meta_path in sorted(DUPLICATE_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        token = secure_filename(meta.get("token") or meta_path.stem).replace(".", "")
        pdf_path = _duplicate_candidate_pdf_path(token)
        if not pdf_path.exists():
            continue
        meta["token"] = token
        try:
            existing_id = int(meta.get("existing_id") or 0)
        except (TypeError, ValueError):
            existing_id = 0
        existing = conn.execute("SELECT * FROM recipes WHERE id = ?", (existing_id,)).fetchone() if existing_id else None
        meta["existing"] = recipe_to_dict(existing) if existing is not None else None
        candidates.append(meta)
    candidates.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return candidates


def remove_duplicate_candidate(token: str) -> None:
    _duplicate_candidate_pdf_path(token).unlink(missing_ok=True)
    _duplicate_candidate_meta_path(token).unlink(missing_ok=True)


def import_duplicate_candidate(token: str) -> int | None:
    meta_path = _duplicate_candidate_meta_path(token)
    pdf_path = _duplicate_candidate_pdf_path(token)
    if not meta_path.exists() or not pdf_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    safe_original = secure_filename(meta.get("original_filename") or "rezept.pdf") or "rezept.pdf"
    metadata = parse_pdf(pdf_path, safe_original, base_servings=3)
    unique_name = f"{uuid4().hex}.pdf"
    final_path = PDF_DIR / unique_name
    move_file_safe(pdf_path, final_path)
    preview_name = create_preview(final_path) or ""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO recipes (
            title, subtitle, recipe_number, filename, preview_filename, original_filename, uploaded_at,
            delivered_at, status, rating, favorite, note, tags, search_text, archive, import_source,
            is_custom, image_filename, base_servings, ingredients_json, instructions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, '', ?, ?, 0, ?, 0, '', 3, ?, '')
        """,
        (
            metadata["title"],
            metadata["subtitle"],
            metadata["recipe_number"],
            unique_name,
            preview_name,
            safe_original,
            datetime.now().isoformat(timespec="seconds"),
            meta.get("delivered_at") or "",
            normalize_recipe_status(meta.get("status"), STATUS_OPEN),
            metadata["tags"],
            metadata["search_text"],
            "duplicate_keep",
            metadata.get("ingredients_json", "[]"),
        ),
    )
    conn.commit()
    recipe_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    meta_path.unlink(missing_ok=True)
    return recipe_id


def migrate_pending_duplicate_candidates() -> int:
    """0.7.0 migration: old pending duplicate files become normal stored variants."""
    migrated = 0
    for item in pending_duplicate_candidates():
        token = item.get("token") or ""
        if not token:
            continue
        try:
            if import_duplicate_candidate(token) is not None:
                migrated += 1
        except Exception as exc:
            print(f"[hf-addon] altes Duplikat konnte nicht migriert werden: {exc}")
    if migrated:
        sync_duplicate_groups()
    return migrated


def store_pdf(
    temp_path: Path,
    original_filename: str,
    delivered_at: str | None = None,
    import_source: str = "upload",
    status: str = STATUS_OPEN,
    suppress_existing_title: bool = False,
) -> tuple[bool, str]:
    """Store every import as its own recipe. Same-title recipes become variants of one group."""
    safe_original = secure_filename(original_filename) or "rezept.pdf"
    status = normalize_recipe_status(status, STATUS_OPEN)
    metadata = parse_pdf(temp_path, safe_original, base_servings=3)
    detected_title = metadata.get("title", "")
    if suppress_existing_title and find_recipe_by_title(detected_title):
        temp_path.unlink(missing_ok=True)
        return False, detected_title
    unique_name = f"{uuid4().hex}.pdf"
    final_path = PDF_DIR / unique_name
    move_file_safe(temp_path, final_path)
    preview_name = create_preview(final_path) or ""
    group_key = duplicate_group_key(detected_title)
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO recipes (
            title, subtitle, recipe_number, filename, preview_filename, original_filename, uploaded_at,
            delivered_at, status, rating, favorite, note, tags, search_text, archive, import_source,
            is_custom, image_filename, base_servings, ingredients_json, instructions, duplicate_group, duplicate_detached
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, '', ?, ?, 0, ?, 0, '', 3, ?, '', ?, 0)
        """,
        (
            metadata["title"],
            metadata["subtitle"],
            metadata["recipe_number"],
            unique_name,
            preview_name,
            safe_original,
            datetime.now().isoformat(timespec="seconds"),
            delivered_at or "",
            status,
            metadata["tags"],
            metadata["search_text"],
            import_source,
            metadata.get("ingredients_json", "[]"),
            group_key,
        ),
    )
    conn.commit()
    sync_duplicate_groups()
    return True, detected_title


def upsert_recipe_from_upload(file_storage: FileStorage, delivered_at: str | None = None, status: str = STATUS_OPEN) -> tuple[bool, str]:
    original_name = file_storage.filename or "rezept.pdf"
    unique_name = f"tmp_{uuid4().hex}.pdf"
    temp_path = PDF_DIR / unique_name
    file_storage.save(temp_path)
    return store_pdf(temp_path, original_name, delivered_at=delivered_at, import_source="upload", status=status)


def _load_import_state() -> dict[str, Any]:
    try:
        data = json.loads(IMPORT_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_import_state(state: dict[str, Any]) -> None:
    IMPORT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = IMPORT_STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(IMPORT_STATE_PATH)


def _import_file_paths() -> list[Path]:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        (path for path in IMPORT_DIR.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: (path.stat().st_mtime, path.name.lower()),
    )


def _count_import_files() -> int:
    try:
        return len(_import_file_paths())
    except Exception:
        return 0


def _move_failed_import(pdf_path: Path, error_message: str) -> Path:
    IMPORT_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    target = IMPORT_ERROR_DIR / pdf_path.name
    if target.exists():
        target = IMPORT_ERROR_DIR / (
            f"{pdf_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{pdf_path.suffix}"
        )
    try:
        move_file_safe(pdf_path, target)
    except Exception:
        target = pdf_path
    try:
        error_path = target.with_suffix(target.suffix + ".fehler.txt")
        error_path.write_text(
            f"Import fehlgeschlagen am {datetime.now().astimezone().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"{error_message}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return target


def _record_import_run(result: dict[str, Any], trigger: str) -> None:
    state = _load_import_state()
    state["last_run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    state["last_trigger"] = trigger
    state["last_imported"] = int(result.get("imported") or 0)
    state["last_duplicates"] = int(result.get("duplicates") or 0)
    state["last_failed"] = int(result.get("failed") or 0)
    state["last_titles"] = list(result.get("titles") or [])[-10:]
    state["total_imported"] = int(state.get("total_imported") or 0) + int(result.get("imported") or 0)
    if trigger == "automatic" and result.get("imported"):
        state["pending_notice"] = int(state.get("pending_notice") or 0) + int(result.get("imported") or 0)
    elif trigger == "manual":
        state["pending_notice"] = 0
    _save_import_state(state)


def _process_import_files(trigger: str = "manual") -> dict[str, Any]:
    result: dict[str, Any] = {
        "imported": 0,
        "duplicates": 0,
        "failed": 0,
        "titles": [],
        "duplicate_titles": [],
        "errors": [],
    }
    if not _import_lock.acquire(blocking=False):
        result["busy"] = True
        return result
    try:
        ensure_dirs()
        for pdf_path in _import_file_paths():
            if trigger == "automatic":
                try:
                    if time.time() - pdf_path.stat().st_mtime < 15:
                        continue
                except Exception:
                    continue

            original_name = pdf_path.name
            temp_path = PDF_DIR / f"tmp_{uuid4().hex}.pdf"
            try:
                shutil.copy2(pdf_path, temp_path)
                ok, detected_title = store_pdf(
                    temp_path,
                    original_name,
                    import_source="media_import",
                )
                pdf_path.unlink()
                if ok:
                    result["imported"] += 1
                    if detected_title:
                        result["titles"].append(detected_title)
                else:
                    result["duplicates"] += 1
                    if detected_title:
                        result["duplicate_titles"].append(detected_title)
            except Exception as exc:
                temp_path.unlink(missing_ok=True)
                message = str(exc) or exc.__class__.__name__
                failed_path = _move_failed_import(pdf_path, message)
                result["failed"] += 1
                result["errors"].append({"file": failed_path.name, "error": message})
        _record_import_run(result, trigger)
        return result
    finally:
        _import_lock.release()


def import_from_watch_dir() -> tuple[int, int, list[str]]:
    """Kompatibilitäts-Wrapper für bestehende interne Aufrufe."""
    result = _process_import_files(trigger="manual")
    return (
        int(result.get("imported") or 0),
        int(result.get("duplicates") or 0),
        list(result.get("duplicate_titles") or []),
    )


def _import_status_for_ui() -> dict[str, Any]:
    state = _load_import_state()
    last_run_label = "noch nicht geprüft"
    raw_last_run = state.get("last_run_at")
    if raw_last_run:
        try:
            parsed = datetime.fromisoformat(str(raw_last_run))
            last_run_label = parsed.astimezone().strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass
    return {
        "path": "media/Import/Rezepte",
        "pending_files": _count_import_files(),
        "last_run_label": last_run_label,
        "last_imported": int(state.get("last_imported") or 0),
        "last_duplicates": int(state.get("last_duplicates") or 0),
        "last_failed": int(state.get("last_failed") or 0),
        "last_trigger": state.get("last_trigger") or "",
    }


# ---------- HelloFresh transfer ----------
HELLOFRESH_MENU_URL = "https://www.hellofresh.de/my-account/deliveries/menu?locale=de-DE"
HELLOFRESH_PREVIEW_MAX_AGE_SECONDS = 30 * 60


def _local_options() -> dict[str, Any]:
    """Read Home Assistant app options without ever returning secrets to a template or API."""
    try:
        data = json.loads((DATA_DIR / "options.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _hellofresh_accounts() -> list[dict[str, Any]]:
    """Return the four Home Assistant account slots without exposing passwords."""
    options = _local_options()
    accounts: list[dict[str, Any]] = []
    for number in range(1, 5):
        prefix = "hellofresh" if number == 1 else f"hellofresh_account_{number}"
        email_key = "hellofresh_email" if number == 1 else f"{prefix}_email"
        password_key = "hellofresh_password" if number == 1 else f"{prefix}_password"
        label_key = "hellofresh_account_1_label" if number == 1 else f"{prefix}_label"
        email = str(options.get(email_key) or "").strip()
        password = str(options.get(password_key) or "")
        configured_label = str(options.get(label_key) or "").strip()
        label = configured_label or f"HelloFresh-Konto {number}"
        accounts.append({
            "key": str(number),
            "label": label,
            "email": email,
            "password": password,
            # A manual browser login is enough. Credentials remain optional so
            # that they never need to be copied from a personal browser.
            "configured": bool(configured_label or email or password),
            "credentials_configured": bool(email and password),
        })
    return accounts


def _hellofresh_account(account_key: str | None) -> dict[str, Any]:
    requested = str(account_key or "1")
    return next((account for account in _hellofresh_accounts() if account["key"] == requested), _hellofresh_accounts()[0])


def _load_hellofresh_state() -> dict[str, Any]:
    try:
        data = json.loads(HELLOFRESH_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_hellofresh_state(state: dict[str, Any]) -> None:
    HELLOFRESH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = HELLOFRESH_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(HELLOFRESH_STATE_PATH)


def _hellofresh_view_state() -> dict[str, Any]:
    state = _load_hellofresh_state()
    recipes = state.get("recipes") if isinstance(state.get("recipes"), list) else []
    safe_recipes = []
    for recipe in recipes:
        if not isinstance(recipe, dict):
            continue
        safe_recipes.append({
            "key": str(recipe.get("key") or ""),
            "title": str(recipe.get("title") or ""),
            "subtitle": str(recipe.get("subtitle") or ""),
            "week_label": str(recipe.get("week_label") or ""),
            "already_exists": bool(recipe.get("already_exists")),
            "selected_by_default": bool(recipe.get("selected_by_default")),
        })
    accounts = _hellofresh_accounts()
    active_key = str(state.get("account_key") or "1")
    active = _hellofresh_account(active_key)
    return {
        "phase": state.get("phase") or "idle",
        "message": state.get("message") or "",
        "week_label": state.get("week_label") or "",
        "recipes": safe_recipes,
        "total": int(state.get("total") or len(safe_recipes)),
        "completed": int(state.get("completed") or 0),
        "imported": int(state.get("imported") or 0),
        "skipped": int(state.get("skipped") or 0),
        "failed": int(state.get("failed") or 0),
        "errors": list(state.get("errors") or [])[-5:],
        "previewed_at": state.get("previewed_at") or "",
        "week_type": state.get("week_type") or "upcoming",
        "delivery_url": state.get("delivery_url") or "",
        "deliveries": [item for item in state.get("deliveries", []) if isinstance(item, dict)],
        "accounts": [{key: value for key, value in account.items() if key not in {"email", "password"}} for account in accounts],
        "active_account_key": active_key,
        "active_account_label": state.get("active_account_label") or active["label"],
        "can_preview": True,
        "browser_running": _hellofresh_visible_browser_running(),
        "browser_launching": _hellofresh_visible_browser_launching,
        "browser_account_key": _hellofresh_visible_browser_account_key,
        "browser_account_label": _hellofresh_account(_hellofresh_visible_browser_account_key)["label"] if _hellofresh_visible_browser_account_key else "",
        "browser_url": _hellofresh_vnc_url(),
    }


def _update_hellofresh_state(**changes: Any) -> dict[str, Any]:
    state = _load_hellofresh_state()
    state.update(changes)
    _save_hellofresh_state(state)
    return state


def _hellofresh_vnc_url() -> str:
    host = request.host.split(":", 1)[0]
    return f"{request.scheme}://{host}:6082/vnc.html?autoconnect=1&resize=remote"


def _hellofresh_visible_browser_running() -> bool:
    return bool(_hellofresh_visible_browser_process and _hellofresh_visible_browser_process.poll() is None)


def _clear_hellofresh_profile_locks(profile_dir: Path) -> None:
    """Remove stale Chromium process locks without touching cookies or login data."""
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = profile_dir / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except FileNotFoundError:
            pass




def _prepare_hellofresh_visible_profile(profile_dir: Path) -> None:
    """Repair profile ownership left by older root/headless runs."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    _clear_hellofresh_profile_locks(profile_dir)
    try:
        subprocess.run(
            ["chown", "-R", "hf-browser:hf-browser", str(profile_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Das gespeicherte HelloFresh-Browserprofil konnte nicht für den Browserbenutzer vorbereitet werden.") from exc
    try:
        profile_dir.chmod(0o700)
    except OSError:
        pass

def _prefill_hellofresh_visible_login(account: dict[str, Any]) -> bool:
    """Fill the visible Chromium with real X11 keyboard input.

    CDP is used only to *read* the current login form and its coordinates.  The
    credentials themselves are entered through xdotool, so Chromium receives
    normal trusted mouse/keyboard events.  This is important for HelloFresh's
    React login form: directly assigning DOM values can look correct on screen
    while the form's internal state (or anti-bot checks) still rejects the
    subsequent manual submit.

    The submit action deliberately remains manual so CAPTCHA/MFA can run in the
    real visible browser.
    """
    email = str(account.get("email") or "").strip()
    password = str(account.get("password") or "")
    if not email or not password:
        return False

    locate_expression = r"""
(() => {
  const text = (value) => String(value || '').trim().toLowerCase();
  const labelText = (el) => {
    const parts = [];
    if (el.labels) for (const label of el.labels) parts.push(label.innerText || label.textContent || '');
    const parent = el.closest('label');
    if (parent) parts.push(parent.innerText || parent.textContent || '');
    return text(parts.join(' '));
  };
  const scoreEmail = (el) => {
    const type = text(el.getAttribute('type'));
    const name = text(el.getAttribute('name'));
    const id = text(el.getAttribute('id'));
    const placeholder = text(el.getAttribute('placeholder'));
    const autocomplete = text(el.getAttribute('autocomplete'));
    const aria = text(el.getAttribute('aria-label'));
    const label = labelText(el);
    let score = 0;
    if (type === 'email') score += 100;
    if (autocomplete === 'username' || autocomplete === 'email') score += 90;
    for (const value of [name, id, placeholder, aria, label]) {
      if (value.includes('email') || value.includes('e-mail') || value.includes('mail')) score += 70;
      if (value.includes('benutzer') || value.includes('username')) score += 35;
    }
    if (type === 'password' || el.disabled || el.readOnly) score -= 200;
    return score;
  };
  const scorePassword = (el) => {
    const type = text(el.getAttribute('type'));
    const name = text(el.getAttribute('name'));
    const id = text(el.getAttribute('id'));
    const placeholder = text(el.getAttribute('placeholder'));
    const autocomplete = text(el.getAttribute('autocomplete'));
    const aria = text(el.getAttribute('aria-label'));
    const label = labelText(el);
    let score = 0;
    if (type === 'password') score += 120;
    if (autocomplete === 'current-password') score += 90;
    for (const value of [name, id, placeholder, aria, label]) {
      if (value.includes('password') || value.includes('passwort') || value.includes('kennwort')) score += 70;
      if (value.includes('pass')) score += 30;
    }
    if (el.disabled || el.readOnly) score -= 200;
    return score;
  };
  const inputs = Array.from(document.querySelectorAll('input')).filter(el => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 20 && rect.height > 10;
  });
  const best = (scorer) => inputs
    .map(el => [scorer(el), el])
    .sort((a, b) => b[0] - a[0])[0];
  const emailBest = best(scoreEmail);
  const passwordBest = best(scorePassword);
  if (!emailBest || !passwordBest || emailBest[0] <= 0 || passwordBest[0] <= 0) {
    return {ok:false, reason:'fields-not-found', url:location.href, inputs:inputs.length};
  }
  const emailEl = emailBest[1];
  const passwordEl = passwordBest[1];
  const er = emailEl.getBoundingClientRect();
  const pr = passwordEl.getBoundingClientRect();
  return {
    ok:true,
    url:location.href,
    emailValue:emailEl.value || '',
    passwordValue:passwordEl.value || '',
    emailRect:{x:er.left + er.width/2, y:er.top + er.height/2},
    passwordRect:{x:pr.left + pr.width/2, y:pr.top + pr.height/2},
    screenX:window.screenX || 0,
    screenY:window.screenY || 0,
    outerWidth:window.outerWidth || window.innerWidth,
    outerHeight:window.outerHeight || window.innerHeight,
    innerWidth:window.innerWidth,
    innerHeight:window.innerHeight
  };
})()
"""

    def evaluate(target: dict[str, Any]) -> dict[str, Any]:
        from websocket import create_connection
        ws = create_connection(str(target["webSocketDebuggerUrl"]), timeout=2.5, suppress_origin=True)
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": locate_expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            }))
            while True:
                response = json.loads(ws.recv())
                if response.get("id") != 1:
                    continue
                result = ((response.get("result") or {}).get("result") or {})
                return result.get("value") or {}
        finally:
            ws.close()

    def x11_point(info: dict[str, Any], key: str) -> tuple[int, int]:
        rect = info.get(key) or {}
        # DOM coordinates are relative to Chromium's content viewport.  Add the
        # browser chrome/title-bar inset to obtain X11 screen coordinates.
        outer_w = float(info.get("outerWidth") or info.get("innerWidth") or 0)
        inner_w = float(info.get("innerWidth") or outer_w or 0)
        outer_h = float(info.get("outerHeight") or info.get("innerHeight") or 0)
        inner_h = float(info.get("innerHeight") or outer_h or 0)
        left_inset = max(0.0, (outer_w - inner_w) / 2.0)
        top_inset = max(0.0, outer_h - inner_h)
        return (
            int(round(float(info.get("screenX") or 0) + left_inset + float(rect.get("x") or 0))),
            int(round(float(info.get("screenY") or 0) + top_inset + float(rect.get("y") or 0))),
        )

    def type_into(point: tuple[int, int], value: str, *, blur: bool = False) -> None:
        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":99")
        common = {"env": env, "check": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        subprocess.run(["xdotool", "mousemove", "--sync", str(point[0]), str(point[1]), "click", "1"], **common)
        time.sleep(0.08)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+a"], **common)
        time.sleep(0.05)
        # xdotool injects X11 keyboard events into the real visible Chromium.
        # No JavaScript value assignment or synthetic DOM input/change event is
        # used here.
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "8", "--", value], **common)
        if blur:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "Tab"], **common)
        time.sleep(0.12)

    deadline = time.time() + 35
    last_url = ""
    last_reason = ""
    stable_since: float | None = None
    last_fill_at = 0.0
    last_ok = False

    while time.time() < deadline:
        if not _hellofresh_visible_browser_running():
            raise RuntimeError("Der sichtbare HelloFresh-Browser wurde während des Starts beendet.")
        try:
            targets = requests.get("http://127.0.0.1:9224/json/list", timeout=1.5).json()
            candidates = [
                item for item in targets
                if item.get("type") in {"page", "iframe"} and item.get("webSocketDebuggerUrl")
            ]
            candidates.sort(key=lambda item: (
                0 if "hellofresh" in str(item.get("url") or "").lower() else 1,
                0 if item.get("type") == "page" else 1,
            ))

            for target in candidates:
                target_url = str(target.get("url") or "")
                if target.get("type") == "page":
                    last_url = target_url
                    if "hellofresh" in target_url.lower() and "/login" not in target_url.lower():
                        return True

                info = evaluate(target)
                if not info.get("ok"):
                    stable_since = None
                    last_reason = str(info.get("reason") or "fields-not-found")
                    continue

                last_ok = True
                email_ok = str(info.get("emailValue") or "") == email
                password_ok = str(info.get("passwordValue") or "") == password
                if email_ok and password_ok:
                    stable_since = stable_since or time.time()
                    if time.time() - stable_since >= 3.0:
                        return True
                    last_reason = "waiting-for-stable-login-form"
                    continue

                stable_since = None
                # Avoid fighting a single React render every 400 ms.  Refill only
                # when the final fields are actually empty/changed for a moment.
                if time.time() - last_fill_at >= 0.9:
                    type_into(x11_point(info, "emailRect"), email)
                    type_into(x11_point(info, "passwordRect"), password, blur=True)
                    last_fill_at = time.time()
                    last_reason = "x11-credentials-entered"
                break
        except Exception as exc:
            last_reason = str(exc)
        time.sleep(0.4)

    if last_url and "/login" not in last_url.lower():
        return True
    if last_ok:
        return True
    detail = f" ({last_reason})" if last_reason else ""
    raise RuntimeError(
        "Die gespeicherten Zugangsdaten konnten nicht automatisch in die sichtbare HelloFresh-Anmeldung eingetragen werden"
        + detail
        + "."
    )

def _start_hellofresh_login_browser(account_key: str) -> None:
    """Open one visible, account-specific Chromium profile for manual completion of login."""
    global _hellofresh_visible_browser_process, _hellofresh_visible_browser_account_key
    account = _hellofresh_account(account_key)
    with _hellofresh_visible_browser_lock:
        if _hellofresh_visible_browser_running():
            if _hellofresh_visible_browser_account_key == account["key"]:
                return
            current = _hellofresh_account(_hellofresh_visible_browser_account_key)["label"]
            raise RuntimeError(f"Der Browser für {current} ist noch geöffnet. Bitte schließe ihn erst, bevor Du das Konto wechselst.")
        if _hellofresh_lock.locked():
            raise RuntimeError("Während eines laufenden Transfers kann kein Login-Browser geöffnet werden.")
        ensure_dirs()
        profile_dir = HELLOFRESH_PROFILE_DIR / f"account-{account['key']}"
        _prepare_hellofresh_visible_profile(profile_dir)
        browser_home = HELLOFRESH_PROFILE_DIR
        for directory in (browser_home / ".config", browser_home / ".cache"):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    ["chown", "-R", "hf-browser:hf-browser", str(directory)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.CalledProcessError):
                pass
        # No ChromeDriver/WebDriver is attached to this browser.  It therefore
        # remains a normal visible Chromium session for HelloFresh/CAPTCHA.
        _hellofresh_visible_browser_process = subprocess.Popen(
            [
                "/usr/bin/chromium-browser",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--password-store=basic",
                "--window-size=1280,1024",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9224",
                "--remote-allow-origins=*",
                f"--user-data-dir={profile_dir}",
                "https://www.hellofresh.de/login",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                **os.environ,
                "DISPLAY": os.environ.get("DISPLAY", ":99"),
                "HOME": str(browser_home),
                "USER": "hf-browser",
                "LOGNAME": "hf-browser",
                "XDG_CONFIG_HOME": str(browser_home / ".config"),
                "XDG_CACHE_HOME": str(browser_home / ".cache"),
            },
            user="hf-browser",
            group="hf-browser",
        )
        _hellofresh_visible_browser_account_key = account["key"]
        time.sleep(0.8)
        if not _hellofresh_visible_browser_running():
            _hellofresh_visible_browser_process = None
            _hellofresh_visible_browser_account_key = ""
            raise RuntimeError("Der sichtbare HelloFresh-Browser wurde direkt wieder beendet.")
        if account.get("credentials_configured"):
            _prefill_hellofresh_visible_login(account)


def _hellofresh_browser_login_message(account: dict[str, Any]) -> str:
    if account["email"] and account["password"]:
        return (
            f"E-Mail-Adresse und Passwort für {account['label']} wurden aus den App-Einstellungen in den sichtbaren Browser übernommen. "
            "Klicke dort auf Anmelden und erledige nur noch CAPTCHA, MFA oder Rückfragen."
        )
    return (
        f"Der sichtbare Browser für {account['label']} ist geöffnet. Hinterlege E-Mail-Adresse und Passwort dieses Kontos "
        "in den App-Einstellungen, damit beide Felder automatisch ausgefüllt werden."
    )


def _open_hellofresh_login_browser_worker(account_key: str) -> None:
    global _hellofresh_visible_browser_launching
    account = _hellofresh_account(account_key)
    try:
        _start_hellofresh_login_browser(account_key)
        _update_hellofresh_state(
            phase="login_open",
            message=_hellofresh_browser_login_message(account),
            account_key=account_key,
            active_account_label=account["label"],
        )
    except Exception as exc:
        _update_hellofresh_state(
            phase="error",
            message=str(exc) or "Der sichtbare HelloFresh-Browser konnte nicht gestartet werden.",
            account_key=account_key,
            active_account_label=account["label"],
        )
    finally:
        with _hellofresh_visible_browser_lock:
            _hellofresh_visible_browser_launching = False


def _stop_hellofresh_login_browser() -> None:
    global _hellofresh_visible_browser_process, _hellofresh_visible_browser_account_key
    with _hellofresh_visible_browser_lock:
        process = _hellofresh_visible_browser_process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        _hellofresh_visible_browser_process = None
        if _hellofresh_visible_browser_account_key:
            profile_dir = HELLOFRESH_PROFILE_DIR / f"account-{_hellofresh_visible_browser_account_key}"
            _clear_hellofresh_profile_locks(profile_dir)
        _hellofresh_visible_browser_account_key = ""


def _make_hellofresh_profile_snapshot(account_key: str) -> Path:
    """Create a short-lived worker copy of the persistent login profile.

    Headless Selenium must never open the real profile directly. This mirrors the
    proven Kleinanzeigen pattern: cookies/login state are copied, Chromium locks
    and caches are omitted, and the persistent profile remains owned by hf-browser.
    """
    source_profile = HELLOFRESH_PROFILE_DIR / f"account-{account_key}"
    source_profile.mkdir(parents=True, exist_ok=True)
    _log_hellofresh_profile(account_key, "snapshot-source", source_profile)
    snapshot = Path(tempfile.mkdtemp(prefix=f"hellofresh-account-{account_key}-"))
    ignore = shutil.ignore_patterns(
        "SingletonLock", "SingletonSocket", "SingletonCookie",
        "Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
        "DawnCache", "Crashpad", "BrowserMetrics*",
    )
    try:
        shutil.copytree(source_profile, snapshot, dirs_exist_ok=True, symlinks=False, ignore=ignore)
        _clear_hellofresh_profile_locks(snapshot)
        _log_hellofresh_profile(account_key, "snapshot-ready", snapshot)
        return snapshot
    except Exception:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def _close_hellofresh_browser(driver: webdriver.Chrome | None) -> None:
    if driver is None:
        return
    snapshot = Path(str(getattr(driver, "_hf_profile_snapshot", "") or ""))
    try:
        driver.quit()
    except WebDriverException:
        pass
    finally:
        if str(snapshot) not in {"", "."}:
            shutil.rmtree(snapshot, ignore_errors=True)


def _hellofresh_browser(account_key: str) -> webdriver.Chrome:
    ensure_dirs()
    if _hellofresh_visible_browser_launching:
        raise RuntimeError("Der sichtbare HelloFresh-Browser wird gerade gestartet. Bitte warte kurz und schließe ihn nach der Anmeldung, bevor Du den Abruf startest.")
    if _hellofresh_visible_browser_running():
        current = _hellofresh_account(_hellofresh_visible_browser_account_key)["label"]
        raise RuntimeError(f"Der sichtbare HelloFresh-Browser für {current} ist noch geöffnet. Beende ihn nach der Anmeldung und starte dann den Abruf.")
    profile_snapshot = _make_hellofresh_profile_snapshot(account_key)
    options = ChromeOptions()
    # The add-on already has an isolated Xvfb desktop.  Use a normal Chromium
    # window there: headless Chromium exposes a different browser fingerprint
    # and can cause a challenge despite a valid saved session.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--profile-directory=Default")
    # Match the visible login browser.  This keeps Chromium from selecting a
    # different OS keyring/password-store mode when it opens copied cookies.
    options.add_argument("--password-store=basic")
    options.add_argument(f"--user-data-dir={profile_snapshot}")
    options.add_experimental_option("prefs", {
        "download.default_directory": str(IMPORT_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
    })
    try:
        driver = webdriver.Chrome(service=ChromeService("/usr/bin/chromedriver"), options=options)
        setattr(driver, "_hf_profile_snapshot", str(profile_snapshot))
        return driver
    except Exception:
        shutil.rmtree(profile_snapshot, ignore_errors=True)
        raise


def _find_first(driver: webdriver.Chrome, selectors: list[str]):
    for selector in selectors:
        found = driver.find_elements(By.CSS_SELECTOR, selector)
        if found:
            return found[0]
    return None


def _dismiss_hellofresh_consent(driver: webdriver.Chrome) -> None:
    for label in ("Ablehnen", "Nur notwendige", "Alles akzeptieren"):
        try:
            buttons = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(.), '{label}')]")
            if buttons:
                buttons[0].click()
                return
        except WebDriverException:
            continue


def _hellofresh_profile_summary(profile_dir: Path) -> str:
    """Return file-presence diagnostics only; never inspect browser contents."""
    checks = {
        "local-state": profile_dir / "Local State",
        "preferences": profile_dir / "Default" / "Preferences",
        "cookies-network": profile_dir / "Default" / "Network" / "Cookies",
        "cookies-legacy": profile_dir / "Default" / "Cookies",
        "local-storage": profile_dir / "Default" / "Local Storage",
        "session-storage": profile_dir / "Default" / "Session Storage",
    }
    values: list[str] = []
    for name, path in checks.items():
        try:
            if not path.exists():
                values.append(f"{name}=missing")
            elif path.is_dir():
                values.append(f"{name}=dir")
            else:
                values.append(f"{name}={path.stat().st_size}B")
        except OSError:
            values.append(f"{name}=unreadable")
    return ",".join(values)


def _log_hellofresh_profile(account_key: str, stage: str, profile_dir: Path) -> None:
    app.logger.info(
        "[HelloFresh] account=%s stage=%s profile=%s",
        account_key,
        stage,
        _hellofresh_profile_summary(profile_dir),
    )


def _safe_hellofresh_url(url: str) -> str:
    """Keep URL diagnostics useful without logging query values or tokens."""
    try:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:240]
    except Exception:
        return "unavailable"


def _safe_hellofresh_title(title: str) -> str:
    compact = " ".join(title.split())[:160]
    return re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", "[redacted-email]", compact, flags=re.I)


def _log_hellofresh_page(driver: webdriver.Chrome, account_key: str, stage: str) -> None:
    """Log navigation facts, never HTML, cookies, storage, credentials, or query data."""
    try:
        url = _safe_hellofresh_url(driver.current_url or "")
        title = _safe_hellofresh_title(driver.title or "")
        app.logger.info("[HelloFresh] account=%s stage=%s url=%s title=%s", account_key, stage, url, title)
    except WebDriverException:
        app.logger.info("[HelloFresh] account=%s stage=%s page-diagnostics=unavailable", account_key, stage)


def _visible_hellofresh_challenge(driver: webdriver.Chrome) -> bool:
    selectors = [
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        "[class*='captcha' i]",
        "[id*='captcha' i]",
    ]
    for selector in selectors:
        try:
            if any(element.is_displayed() for element in driver.find_elements(By.CSS_SELECTOR, selector)):
                return True
        except WebDriverException:
            continue
    return False


def _looks_like_login_or_challenge(driver: webdriver.Chrome) -> str:
    """Recognize actual login/challenge pages without treating bundled scripts as CAPTCHA."""
    try:
        url = (driver.current_url or "").lower()
        body = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
    except WebDriverException:
        return ""
    if "/login" in url or ("anmelden" in body and "passwort" in body):
        return "login"
    challenge_text = (
        "verify you are human",
        "security check",
        "sicherheitsüberprüfung",
        "unusual traffic",
        "access denied",
        "just a moment",
        "captcha required",
    )
    if _visible_hellofresh_challenge(driver) or any(text in body for text in challenge_text):
        return "HelloFresh verlangt eine CAPTCHA-Prüfung. Öffne den HelloFresh-Browser, löse sie dort einmal selbst und beende danach das Browserfenster. Der Abruf wurde nicht wiederholt."
    return ""


def _login_to_hellofresh(driver: webdriver.Chrome, account_key: str) -> None:
    account = _hellofresh_account(account_key)
    email = str(account["email"] or "").strip()
    password = str(account["password"] or "")
    if not email or not password:
        raise RuntimeError(f"Bitte hinterlege zuerst E-Mail-Adresse und Passwort für {account['label']} in den App-Einstellungen der Rezeptverwaltung.")
    driver.get("https://www.hellofresh.de/login")
    _dismiss_hellofresh_consent(driver)
    try:
        email_field = WebDriverWait(driver, 12).until(lambda d: _find_first(d, ["input[type='email']", "input[name*='email' i]"]))
        password_field = _find_first(driver, ["input[type='password']"])
        if not email_field or not password_field:
            raise RuntimeError("Die HelloFresh-Anmeldemaske wurde nicht erkannt.")
        email_field.clear()
        email_field.send_keys(email)
        password_field.clear()
        password_field.send_keys(password)
        submit = _find_first(driver, ["button[type='submit']"])
        if not submit:
            raise RuntimeError("Der HelloFresh-Anmeldebutton wurde nicht gefunden.")
        submit.click()
        WebDriverWait(driver, 15).until(lambda d: "/login" not in (d.current_url or ""))
    except TimeoutException as exc:
        detail = _looks_like_login_or_challenge(driver)
        raise RuntimeError(detail if detail and detail != "login" else "Die HelloFresh-Anmeldung wurde nicht abgeschlossen. Bitte prüfe die Zugangsdaten oder melde Dich einmal manuell an.") from exc


def _active_hellofresh_profile_name(driver: webdriver.Chrome, fallback: str) -> str:
    for button in driver.find_elements(By.CSS_SELECTOR, "button[aria-label]"):
        label = str(button.get_attribute("aria-label") or "")
        match = re.search(r"profile menu for\s+(.+)", label, re.I)
        if match:
            return match.group(1).strip()[:80]
    return fallback


def _open_hellofresh_week(driver: webdriver.Chrome, account_key: str, week_type: str, delivery_url: str = "") -> str:
    url = delivery_url if delivery_url.startswith("https://www.hellofresh.de/my-account/deliveries/menu") else (
        HELLOFRESH_MENU_URL if week_type != "past" else "https://www.hellofresh.de/my-account/deliveries/past-deliveries?locale=de-DE"
    )
    driver.get(url)
    _dismiss_hellofresh_consent(driver)
    _log_hellofresh_page(driver, account_key, "week-opened")
    issue = _looks_like_login_or_challenge(driver)
    if issue == "login":
        raise RuntimeError("Dieses Konto ist noch nicht angemeldet. Öffne zuerst den HelloFresh-Browser und melde Dich dort an.")
    elif issue:
        raise RuntimeError(issue)
    try:
        if week_type == "past":
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[id^='past-delivery-week-']")))
        else:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "weekly-menu")))
    except TimeoutException as exc:
        _log_hellofresh_page(driver, account_key, "week-not-recognized")
        issue = _looks_like_login_or_challenge(driver)
        if issue == "login":
            raise RuntimeError("Dieses Konto ist noch nicht angemeldet. Öffne zuerst den HelloFresh-Browser und melde Dich dort an.") from exc
        if issue:
            raise RuntimeError(issue) from exc
        raise RuntimeError("Die HelloFresh-Wochenansicht wurde nicht erkannt. Die Oberfläche wurde möglicherweise geändert.") from exc
    _log_hellofresh_page(driver, account_key, "week-ready")
    headings = driver.find_elements(By.CSS_SELECTOR, "h1, h2")
    return next((item.text.strip() for item in headings if item.text.strip()), "HelloFresh-Woche")


def _hellofresh_delivery_dates(driver: webdriver.Chrome, account_key: str) -> tuple[list[dict[str, str]], str]:
    _open_hellofresh_week(driver, account_key, "upcoming")
    tile_labels: list[str] = []
    for tile in driver.find_elements(By.CSS_SELECTOR, "button[id^='week-tile-']"):
        if tile.find_elements(By.CSS_SELECTOR, "img[alt='Past deliveries']"):
            continue
        label = " ".join(line.strip() for line in tile.text.splitlines() if line.strip())
        if label and label not in tile_labels:
            tile_labels.append(label)
    deliveries: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for tile_label in tile_labels:
        try:
            tile = next((item for item in driver.find_elements(By.CSS_SELECTOR, "button[id^='week-tile-']") if " ".join(line.strip() for line in item.text.splitlines() if line.strip()) == tile_label), None)
            if tile is None:
                continue
            previous_url = driver.current_url or ""
            driver.execute_script("arguments[0].click();", tile)
            try:
                WebDriverWait(driver, 8).until(lambda d: (d.current_url or "") != previous_url)
            except TimeoutException:
                pass
            current_url = driver.current_url or ""
            if "week=" not in current_url:
                continue
            if current_url in seen_urls:
                continue
            seen_urls.add(current_url)
            status = next((item.text.strip() for item in driver.find_elements(By.CSS_SELECTOR, ".view-status-bar h2") if item.text.strip()), tile_label)
            delivery_date = _hellofresh_delivery_date(status or tile_label)
            deliveries.append({
                "url": current_url,
                "label": status,
                "tile_label": tile_label,
                "display_label": _hellofresh_delivery_label(status or tile_label),
                "delivery_date": delivery_date.isoformat() if delivery_date else "",
            })
        except WebDriverException:
            continue
    if not deliveries:
        raise RuntimeError("HelloFresh hat keine auswählbaren Liefertermine angezeigt. Die Wochenansicht wurde möglicherweise geändert.")
    account = _hellofresh_account(account_key)
    return deliveries, _active_hellofresh_profile_name(driver, account["label"])


def _hellofresh_week_recipes(driver: webdriver.Chrome, week_type: str) -> list[dict[str, Any]]:
    groups: list[tuple[str, str, Any]] = []
    if week_type == "past":
        for container in driver.find_elements(By.CSS_SELECTOR, "[id^='past-delivery-week-']"):
            label = next((line.strip() for line in container.text.splitlines() if line.strip().startswith("Geliefert am")), "Gelieferte Woche")
            groups.append((container.get_attribute("id") or "", label, container))
    else:
        groups.append(("weekly-menu", "Bald liefernde Woche", driver.find_element(By.ID, "weekly-menu")))
    recipes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group_key, week_label, menu in groups:
        for card in menu.find_elements(By.CSS_SELECTOR, "button"):
            headings = card.find_elements(By.CSS_SELECTOR, "h4")
            if not headings:
                continue
            title = clean_recipe_title(headings[0].text.strip())
            unique_key = f"{group_key}:{normalize_title(title)}"
            if not title or unique_key in seen:
                continue
            seen.add(unique_key)
            lines = [line.strip() for line in card.text.splitlines() if line.strip()]
            subtitle = next((line for line in lines[1:] if not re.search(r"(?:Min\.|kcal|Protein|in Deiner Box)", line, re.I)), "")
            recipes.append({
                "key": uuid4().hex,
                "title": title[:140],
                "subtitle": clean_recipe_title(subtitle)[:180],
                "week_label": week_label,
                "delivery_group": group_key,
                "already_exists": find_recipe_by_title(title) is not None,
            })
    if not recipes:
        raise RuntimeError("In der gewählten Woche wurden keine Rezeptkarten erkannt. HelloFresh hat die Wochenansicht möglicherweise geändert.")
    return recipes


def _load_hellofresh_delivery_dates(account_key: str) -> None:
    if not _hellofresh_lock.acquire(blocking=False):
        raise RuntimeError("Ein HelloFresh-Transfer läuft bereits.")
    driver = None
    try:
        account = _hellofresh_account(account_key)
        if not account["configured"]:
            raise RuntimeError(f"Bitte richte zuerst {account['label']} in den App-Einstellungen ein.")
        _update_hellofresh_state(phase="loading_deliveries", message=f"Liefertermine für {account['label']} werden abgerufen …", recipes=[], deliveries=[], errors=[], account_key=account_key)
        driver = _hellofresh_browser(account_key)
        deliveries, profile_name = _hellofresh_delivery_dates(driver, account_key)
        _update_hellofresh_state(
            phase="delivery_ready",
            message=f"{len(deliveries)} Liefertermin(e) für {profile_name} gefunden.",
            deliveries=deliveries,
            account_key=account_key,
            active_account_label=profile_name,
            recipes=[],
            total=0,
            completed=0,
            imported=0,
            skipped=0,
            failed=0,
            errors=[],
        )
    except Exception as exc:
        _update_hellofresh_state(phase="error", message=str(exc) or "HelloFresh-Liefertermine konnten nicht abgerufen werden.", errors=[])
        raise
    finally:
        _close_hellofresh_browser(driver)
        _hellofresh_lock.release()


def _preview_hellofresh_week(week_type: str, account_key: str, delivery_url: str = "") -> None:
    if not _hellofresh_lock.acquire(blocking=False):
        raise RuntimeError("Ein HelloFresh-Transfer läuft bereits.")
    driver = None
    try:
        account = _hellofresh_account(account_key)
        if not account["configured"]:
            raise RuntimeError(f"Bitte richte zuerst {account['label']} in den App-Einstellungen ein.")
        _update_hellofresh_state(phase="previewing", message="HelloFresh-Woche wird geprüft …", recipes=[], errors=[], account_key=account_key, delivery_url=delivery_url)
        driver = _hellofresh_browser(account_key)
        week_label = _open_hellofresh_week(driver, account_key, week_type, delivery_url)
        profile_name = _active_hellofresh_profile_name(driver, account["label"])
        recipes = _hellofresh_week_recipes(driver, week_type)
        default_past_week = str(recipes[0].get("week_label") or "") if week_type == "past" else ""
        for recipe in recipes:
            recipe["selected_by_default"] = (
                week_type != "past" or recipe.get("week_label") == default_past_week
            )
        _update_hellofresh_state(
            phase="ready",
            message=(f"{len(recipes)} Rezept(e) gefunden. Zunächst ist nur die zuletzt gelieferte Woche ausgewählt." if week_type == "past" else f"{len(recipes)} Rezept(e) gefunden."),
            week_type=week_type,
            week_label=week_label,
            account_key=account_key,
            active_account_label=profile_name,
            delivery_url=delivery_url,
            recipes=recipes,
            total=len(recipes),
            completed=0,
            imported=0,
            skipped=sum(1 for recipe in recipes if recipe["already_exists"]),
            failed=0,
            errors=[],
            previewed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        _update_hellofresh_state(phase="error", message=str(exc) or "HelloFresh konnte nicht geprüft werden.", errors=[])
        raise
    finally:
        _close_hellofresh_browser(driver)
        _hellofresh_lock.release()


def _click_hellofresh_recipe(driver: webdriver.Chrome, recipe: dict[str, Any]) -> str:
    title = str(recipe["title"])
    if str(recipe.get("delivery_group") or "") == "weekly-menu":
        menu = driver.find_element(By.ID, "weekly-menu")
    else:
        menu = driver.find_element(By.ID, str(recipe.get("delivery_group") or ""))
    wanted = normalize_title(title)
    for card in menu.find_elements(By.CSS_SELECTOR, "button"):
        headings = card.find_elements(By.CSS_SELECTOR, "h4")
        if headings and normalize_title(headings[0].text) == wanted:
            driver.execute_script("arguments[0].click();", card)
            try:
                link = WebDriverWait(driver, 10).until(
                    lambda d: _find_first(d, ["a[href*='/recipecards/card/']", "a[href*='.pdf']"])
                )
                href = link.get_attribute("href") or ""
                if href:
                    return href
            except TimeoutException as exc:
                raise RuntimeError("Der Link „Herunterladen“ wurde in der HelloFresh-Rezeptkarte nicht gefunden.") from exc
    raise RuntimeError("Die Rezeptkarte wurde in der aktuellen HelloFresh-Woche nicht mehr gefunden.")


def _download_hellofresh_pdf(driver: webdriver.Chrome, recipe: dict[str, Any]) -> Path:
    href = _click_hellofresh_recipe(driver, recipe)
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
    response = requests.get(href, cookies=cookies, timeout=35)
    content = response.content
    if not response.ok or not content.startswith(b"%PDF"):
        raise RuntimeError("HelloFresh hat keine gültige Rezept-PDF geliefert.")
    file_name = f"hellofresh-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.pdf"
    destination = IMPORT_DIR / file_name
    destination.write_bytes(content)
    return destination


def _run_hellofresh_import(selected_keys: set[str]) -> None:
    state = _load_hellofresh_state()
    recipes = [item for item in state.get("recipes", []) if isinstance(item, dict) and str(item.get("key")) in selected_keys]
    if not recipes:
        _update_hellofresh_state(phase="error", message="Für den Transfer wurden keine Rezepte ausgewählt.")
        return
    driver = None
    try:
        _update_hellofresh_state(phase="importing", message="HelloFresh wird geöffnet …", total=len(recipes), completed=0, imported=0, skipped=0, failed=0, errors=[])
        with app.app_context():
            account_key = str(state.get("account_key") or "1")
            selected_delivery_url = str(state.get("delivery_url") or "")
            delivery = next((item for item in state.get("deliveries", []) if isinstance(item, dict) and str(item.get("url") or "") == selected_delivery_url), {})
            delivery_date = str(delivery.get("delivery_date") or "")
            if not parse_date(delivery_date):
                parsed_delivery_date = _hellofresh_delivery_date(str(delivery.get("label") or delivery.get("tile_label") or ""))
                delivery_date = parsed_delivery_date.isoformat() if parsed_delivery_date else ""
            driver = _hellofresh_browser(account_key)
            _open_hellofresh_week(driver, account_key, str(state.get("week_type") or "upcoming"), str(state.get("delivery_url") or ""))
            for position, recipe in enumerate(recipes, start=1):
                _update_hellofresh_state(phase="importing", message=f"{position}/{len(recipes)}: {recipe.get('title')} wird übertragen …", completed=position - 1)
                try:
                    pdf_path = _download_hellofresh_pdf(driver, recipe)
                    ok, _title = store_pdf(pdf_path, pdf_path.name, delivered_at=delivery_date, import_source="hellofresh")
                    current = _load_hellofresh_state()
                    if ok:
                        _update_hellofresh_state(imported=int(current.get("imported") or 0) + 1, completed=position)
                    else:
                        _update_hellofresh_state(skipped=int(current.get("skipped") or 0) + 1, completed=position)
                except Exception as exc:
                    current = _load_hellofresh_state()
                    errors = list(current.get("errors") or [])
                    errors.append(f"{recipe.get('title')}: {str(exc) or exc.__class__.__name__}")
                    _update_hellofresh_state(failed=int(current.get("failed") or 0) + 1, completed=position, errors=errors)
            final = _load_hellofresh_state()
            _update_hellofresh_state(phase="complete", message=f"Abgeschlossen: {final.get('imported', 0)} neu, {final.get('skipped', 0)} bereits vorhanden, {final.get('failed', 0)} Fehler.")
    except Exception as exc:
        _update_hellofresh_state(phase="error", message=str(exc) or "Der HelloFresh-Transfer wurde abgebrochen.")
    finally:
        _close_hellofresh_browser(driver)
        _hellofresh_lock.release()


def _backfill_recent_hellofresh_delivery_date() -> int:
    """Apply the selected date once to recipes imported immediately before 0.8.15."""
    state = _load_hellofresh_state()
    selected_url = str(state.get("delivery_url") or "")
    delivery = next((item for item in state.get("deliveries", []) if isinstance(item, dict) and str(item.get("url") or "") == selected_url), {})
    delivery_date = parse_date(str(delivery.get("delivery_date") or ""))
    if delivery_date is None:
        delivery_date = _hellofresh_delivery_date(str(delivery.get("label") or delivery.get("tile_label") or ""))
    try:
        previewed_at = datetime.fromisoformat(str(state.get("previewed_at") or ""))
    except ValueError:
        return 0
    if previewed_at.tzinfo is not None:
        previewed_at = previewed_at.replace(tzinfo=None)
    titles = {normalize_title(str(item.get("title") or "")) for item in state.get("recipes", []) if isinstance(item, dict)}
    if delivery_date is None or not titles:
        return 0
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, uploaded_at FROM recipes WHERE archive = 0 AND import_source = 'hellofresh' AND COALESCE(delivered_at, '') = ''"
    ).fetchall()
    changed = 0
    for row in rows:
        try:
            uploaded_at = datetime.fromisoformat(str(row["uploaded_at"] or ""))
        except ValueError:
            continue
        if uploaded_at < previewed_at or normalize_title(str(row["title"] or "")) not in titles:
            continue
        conn.execute("UPDATE recipes SET delivered_at = ? WHERE id = ?", (delivery_date.isoformat(), row["id"]))
        changed += 1
    if changed:
        conn.commit()
    return changed


def recipe_counts() -> dict[str, int]:
    rows = all_active_recipes()
    return {
        "alle": len(rows),
        "total": len(rows),
        "offen": sum(1 for row in rows if row.get("status") == STATUS_OPEN),
        "vorhanden": sum(1 for row in rows if row.get("status") == STATUS_PRESENT),
        "unterwegs": sum(1 for row in rows if row.get("is_future_delivery")),
        "gekocht": sum(1 for row in rows if row.get("status") == STATUS_COOKED),
        "favoriten": sum(1 for row in rows if row.get("favorite")),
    }




def build_search_text(title: str | None, subtitle: str | None, tags: str | None, ingredient_lines: list[str] | None = None, note: str | None = None) -> str:
    parts: list[str] = []
    for value in (title, subtitle, tags, note):
        cleaned = clean_pdf_cell(value)
        if cleaned:
            parts.append(cleaned)
    if ingredient_lines:
        for line in ingredient_lines:
            cleaned = clean_pdf_cell(line)
            if cleaned:
                parts.append(cleaned)
    return " ".join(parts).strip()


def search_matches(recipe: dict[str, Any], needle: str) -> bool:
    fields = [recipe.get("title"), recipe.get("subtitle"), recipe.get("tags"), recipe.get("note"), recipe.get("search_text")]
    joined = " ".join((field or "") for field in fields).lower()
    return all(part in joined for part in needle.lower().split() if part)


def query_recipes(search: str = "", tab: str = "alle", quick_tag: str = "", rating_filter: int = 0) -> list[dict[str, Any]]:
    rows = all_active_recipes()
    if tab == "offen":
        rows = [row for row in rows if row.get("status") == STATUS_OPEN]
    elif tab == "vorhanden":
        rows = [row for row in rows if row.get("status") == STATUS_PRESENT]
    elif tab == "lieferbar":
        rows = [row for row in rows if row.get("status") == STATUS_OPEN and not row.get("is_future_delivery")]
    elif tab == "unterwegs":
        rows = [row for row in rows if row.get("status") == STATUS_OPEN and row.get("is_future_delivery")]
    elif tab == "gekocht":
        rows = [row for row in rows if row.get("status") == STATUS_COOKED]
    elif tab == "favoriten":
        rows = [row for row in rows if row.get("favorite") or int(row.get("rating") or 0) > 0]
    elif tab == "top10":
        rows = [row for row in rows if int(row.get("rating") or 0) > 0]

    if quick_tag:
        qtag = quick_tag.lower()
        rows = [row for row in rows if qtag in (row.get("tags") or "").lower() or qtag in (row.get("search_text") or "").lower()]
    if rating_filter > 0:
        rows = [row for row in rows if int(row.get("rating") or 0) == rating_filter]
    if search:
        rows = [row for row in rows if search_matches(row, search)]
    if tab == "top10":
        rows.sort(key=lambda row: (int(row.get("rating") or 0), row.get("cooked_count") or 0, row.get("cooked_at") or "", row.get("uploaded_at") or ""), reverse=True)
        return rows[:10]
    if tab == "favoriten":
        rows.sort(key=lambda row: (row.get("favorite"), int(row.get("rating") or 0), row.get("cooked_count") or 0, row.get("uploaded_at") or ""), reverse=True)
    return rows


def recent_recipes(limit: int = 6) -> list[dict[str, Any]]:
    return all_active_recipes()[:limit]


def latest_cooked(limit: int = 5) -> list[dict[str, Any]]:
    rows = [row for row in all_active_recipes() if row.get("cooked_at")]
    rows.sort(key=lambda row: row.get("cooked_at") or "", reverse=True)
    return rows[:limit]


def top_rated() -> list[dict[str, Any]]:
    return query_recipes(tab="top10")


# ---------- meal planning ----------
def monday_for(value: date | None = None) -> date:
    value = value or date.today()
    return value - timedelta(days=value.weekday())


def week_range_label(start: date) -> str:
    end = start + timedelta(days=6)
    return f"{start.strftime('%d.%m.')} – {end.strftime('%d.%m.%Y')}"


def available_recipes_for_planning() -> list[dict[str, Any]]:
    rows = [row for row in all_active_recipes() if row.get("status") in {STATUS_OPEN, STATUS_PRESENT}]
    rows.sort(key=lambda row: row.get("title", "").lower())
    return rows


def load_meal_plans(start: date, weeks: int = 2) -> list[dict[str, Any]]:
    conn = get_conn()
    end = start + timedelta(days=7 * weeks - 1)
    plan_rows = conn.execute(
        """
        SELECT mp.plan_date, mp.recipe_id, mp.free_text, mp.note, mp.iphone_title, mp.created_at, mp.updated_at,
               r.title AS recipe_title, r.status AS recipe_status, r.rating AS recipe_rating,
               r.search_text AS recipe_search_text, r.is_custom AS recipe_is_custom
        FROM meal_plans mp
        LEFT JOIN recipes r ON r.id = mp.recipe_id
        WHERE mp.plan_date BETWEEN ? AND ?
        ORDER BY mp.plan_date ASC
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    by_date = {row["plan_date"]: dict(row) for row in plan_rows}
    day_names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    weeks_data: list[dict[str, Any]] = []
    for week_index in range(weeks):
        week_start = start + timedelta(days=7 * week_index)
        week_days: list[dict[str, Any]] = []
        for day_index in range(7):
            current = week_start + timedelta(days=day_index)
            entry = by_date.get(current.isoformat(), {})
            recipe_title = clean_recipe_title(entry.get("recipe_title") or "")
            free_text = entry.get("free_text") or ""
            iphone_title = entry.get("iphone_title") or ""
            display = iphone_title or recipe_title or free_text
            week_days.append(
                {
                    "iso": current.isoformat(),
                    "day_name": day_names[day_index],
                    "day_number": current.strftime("%d.%m."),
                    "is_today": current == date.today(),
                    "is_past": current < date.today(),
                    "recipe_id": entry.get("recipe_id") or "",
                    "free_text": free_text,
                    "iphone_title": iphone_title,
                    "note": entry.get("note") or "",
                    "recipe_title": recipe_title,
                    "display": display,
                    "recipe_rating": entry.get("recipe_rating") or 0,
                    "recipe_status": entry.get("recipe_status") or "",
                    "recipe_calories": extract_calories(entry.get("recipe_search_text") or ""),
                "recipe_is_custom": bool(entry.get("recipe_is_custom") or 0),
                }
            )
        weeks_data.append({"start": week_start, "label": iso_week_label(week_start.isoformat()), "range": week_range_label(week_start), "days": week_days})
    return weeks_data


def upcoming_plan_preview(limit: int | None = 10) -> list[dict[str, Any]]:
    today_iso = date.today().isoformat()
    conn = get_conn()
    sql = """
        SELECT mp.plan_date, mp.recipe_id, mp.free_text, mp.iphone_title, mp.note, r.title AS recipe_title, r.search_text AS recipe_search_text, r.is_custom AS recipe_is_custom
        FROM meal_plans mp
        LEFT JOIN recipes r ON r.id = mp.recipe_id
        WHERE mp.plan_date >= ?
          AND (mp.recipe_id IS NOT NULL
               OR TRIM(COALESCE(mp.free_text, '')) <> ''
               OR TRIM(COALESCE(mp.iphone_title, '')) <> '')
        ORDER BY mp.plan_date ASC
    """
    params: list[Any] = [today_iso]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    rows = conn.execute(sql, tuple(params)).fetchall()
    items = []
    for row in rows:
        title = row["iphone_title"] or row["recipe_title"] or row["free_text"] or ""
        if not title:
            continue
        items.append(
            {
                "plan_date": row["plan_date"],
                "title": clean_recipe_title(title),
                "recipe_id": row["recipe_id"] or None,
                "is_recipe": bool(row["recipe_id"]),
                "is_custom": bool(row["recipe_is_custom"] or 0),
                "calories": extract_calories(row["recipe_search_text"] or ""),
                "note": row["note"] or "",
            }
        )
    return items


def quick_plan_window() -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Future assignment options from today through the end of next week."""
    today = date.today()
    end_this_week = today + timedelta(days=6 - today.weekday())
    end_next_week = end_this_week + timedelta(days=7)
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT mp.plan_date, mp.recipe_id, mp.free_text, mp.iphone_title, r.title AS recipe_title
        FROM meal_plans mp
        LEFT JOIN recipes r ON r.id = mp.recipe_id
        WHERE mp.plan_date BETWEEN ? AND ?
        ORDER BY mp.plan_date ASC
        """,
        (today.isoformat(), end_next_week.isoformat()),
    ).fetchall()
    by_date = {row["plan_date"]: dict(row) for row in rows}
    recipe_map: dict[int, str] = {}
    days: list[dict[str, Any]] = []
    current = today
    while current <= end_next_week:
        iso = current.isoformat()
        entry = by_date.get(iso, {})
        recipe_id = int(entry.get("recipe_id") or 0)
        if recipe_id and recipe_id not in recipe_map:
            recipe_map[recipe_id] = iso
        occupied_title = clean_recipe_title(entry.get("iphone_title") or entry.get("recipe_title") or entry.get("free_text") or "")
        days.append(
            {
                "iso": iso,
                "label": f"{['Mo','Di','Mi','Do','Fr','Sa','So'][current.weekday()]} · {current.strftime('%d.%m.')}",
                "occupied": bool(occupied_title),
                "occupied_title": occupied_title,
                "recipe_id": recipe_id or None,
            }
        )
        current += timedelta(days=1)
    return days, recipe_map


def planned_recipe_label(plan_date: str | None) -> str:
    planned = parse_date(plan_date)
    if planned is None:
        return ""
    today = date.today()
    if planned == today:
        return "Geplant heute"
    if planned == today + timedelta(days=1):
        return "Geplant morgen"
    weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][planned.weekday()]
    return f"Geplant am {weekday}"


def _recipe_available_on(recipe_id: int | None, plan_date: str, conn: sqlite3.Connection) -> bool:
    """Future HelloFresh deliveries may be viewed now but planned only on/after delivery."""
    if not recipe_id:
        return True
    requested_date = parse_date(plan_date)
    if not requested_date:
        return False
    row = conn.execute("SELECT delivered_at FROM recipes WHERE id = ? AND archive = 0", (recipe_id,)).fetchone()
    if row is None:
        return False
    delivered_date = parse_date(row["delivered_at"] or "")
    return not delivered_date or requested_date >= delivered_date


def save_meal_plan(plan_date: str, recipe_id: str | None, free_text: str, note: str = "", iphone_title: str = "") -> None:
    conn = get_conn()
    plan_date = (plan_date or "").strip()
    if not parse_date(plan_date):
        return
    recipe_value = int(recipe_id) if str(recipe_id or "").strip().isdigit() else None
    free_text = (free_text or "").strip()
    note = (note or "").strip()
    iphone_title = (iphone_title or "").strip()
    if recipe_value and not _recipe_available_on(recipe_value, plan_date, conn):
        raise ValueError("Dieses HelloFresh-Rezept ist erst ab seinem Lieferdatum für die Planung verfügbar.")
    now = datetime.now().isoformat(timespec="seconds")
    if not recipe_value and not free_text and not note and not iphone_title:
        conn.execute("DELETE FROM meal_plans WHERE plan_date = ?", (plan_date,))
        conn.commit()
        return
    existing = conn.execute("SELECT plan_date FROM meal_plans WHERE plan_date = ?", (plan_date,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE meal_plans SET recipe_id = ?, free_text = ?, note = ?, iphone_title = ?, updated_at = ? WHERE plan_date = ?",
            (recipe_value, free_text, note, iphone_title, now, plan_date),
        )
    else:
        conn.execute(
            "INSERT INTO meal_plans (plan_date, recipe_id, free_text, note, iphone_title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plan_date, recipe_value, free_text, note, iphone_title, now, now),
        )
    conn.commit()


# ---------- shopping list ----------
def _supervisor_app_options(slugs: list[str]) -> dict[str, Any]:
    if not SUPERVISOR_TOKEN:
        return {}
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    for slug in slugs:
        for prefix in ("apps", "addons"):
            try:
                response = requests.get(f"http://supervisor/{prefix}/{slug}/info", headers=headers, timeout=4)
                if not response.ok:
                    continue
                payload = response.json() if response.text.strip() else {}
                data = payload.get("data") if isinstance(payload, dict) else {}
                options = data.get("options") if isinstance(data, dict) else {}
                if isinstance(options, dict):
                    return options
            except Exception:
                continue
    return {}


def _shopping_list_options() -> dict[str, Any]:
    local: dict[str, Any] = {}
    try:
        path = DATA_DIR / "options.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if isinstance(data, dict):
            local = data
    except Exception:
        local = {}
    # The Alexa sync app already contains the user's current target list. Reuse it automatically.
    alexa = _supervisor_app_options(["alexa_bring_sync", "local_alexa_bring_sync"])
    own = _supervisor_app_options(["eigene_einkaufsliste", "local_eigene_einkaufsliste"])
    merged = {
        "shopping_list_host": alexa.get("shopping_list_host") or alexa.get("proxy_host") or "",
        "shopping_list_port": alexa.get("shopping_list_port") or 8156,
        "shopping_list_token": alexa.get("shopping_list_token") or own.get("sync_token") or "",
        "shopping_list_id": alexa.get("shopping_list_id") or "",
    }
    for key in ("shopping_list_host", "shopping_list_port", "shopping_list_token", "shopping_list_id"):
        value = local.get(key)
        if value not in (None, ""):
            merged[key] = value
    return merged


def _shopping_list_hosts() -> list[str]:
    options = _shopping_list_options()
    configured = str(options.get("shopping_list_host") or SHOPPING_LIST_HOST or "").strip()
    candidates = [configured, "homeassistant.local", "172.30.32.1"]
    result: list[str] = []
    for raw in candidates:
        raw = raw.strip().replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        if raw and raw not in result:
            result.append(raw)
    return result


def _shopping_list_request(endpoint: str, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
    options = _shopping_list_options()
    port = int(options.get("shopping_list_port") or SHOPPING_LIST_PORT or 8156)
    token = str(options.get("shopping_list_token") or SHOPPING_LIST_TOKEN or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["x-sync-token"] = token
    errors: list[str] = []
    for host in _shopping_list_hosts():
        try:
            response = requests.request(method, f"http://{host}:{port}{endpoint}", headers=headers, json=payload, timeout=8)
            if response.ok:
                data = response.json() if response.text.strip() else {}
                return data if isinstance(data, dict) else {}, ""
            detail = clean_pdf_cell(response.text) or f"HTTP {response.status_code}"
            errors.append(f"{host}: {detail}")
        except Exception as exc:
            errors.append(f"{host}: {exc}")
    return None, "; ".join(errors[-3:]) or "Eigene Einkaufsliste nicht erreichbar."


def own_shopping_list_target() -> tuple[str, str, str]:
    data, error = _shopping_list_request("/api/integration/lists")
    if not data:
        return "", "", error
    lists = data.get("lists") if isinstance(data.get("lists"), list) else []
    options = _shopping_list_options()
    requested = str(options.get("shopping_list_id") or SHOPPING_LIST_ID or "").strip()
    sync_id = str(data.get("syncListId") or "").strip()
    selected = next((item for item in lists if str(item.get("id")) == requested), None) if requested else None
    if selected is None and sync_id:
        selected = next((item for item in lists if str(item.get("id")) == sync_id), None)
    if selected is None and lists:
        selected = lists[0]
    if selected is None:
        return "", "", "Keine Einkaufsliste gefunden."
    return str(selected.get("id") or ""), str(selected.get("name") or "Einkaufsliste"), ""


def add_items_to_own_shopping_list(items: list[str]) -> tuple[bool, str, str]:
    list_id, list_name, error = own_shopping_list_target()
    if not list_id:
        return False, error, ""
    cleaned = [clean_pdf_cell(item) for item in items if clean_pdf_cell(item)]
    data, error = _shopping_list_request("/api/integration/import", "POST", {"listId": list_id, "items": cleaned})
    if data is None:
        return False, error, list_name
    return True, "", list_name


def build_shopping_choices(recipe: sqlite3.Row, servings: int) -> list[dict[str, Any]]:
    ingredients = ingredients_from_json(recipe["ingredients_json"] or "")
    choices: list[dict[str, Any]] = []
    for idx, ingredient in enumerate(ingredients):
        label = ingredient_item_text(ingredient, servings)
        if not label:
            continue
        is_base = is_base_ingredient_item(ingredient)
        choices.append({
            "id": str(idx),
            "label": clean_pdf_cell(label),
            "is_base": is_base,
            "checked": not is_base,
        })
    return choices


def _ingredient_from_edited_shopping_line(edited_line: str, original_item: dict[str, Any], servings: int) -> dict[str, Any]:
    edited_line = clean_pdf_cell(edited_line)
    base_servings = int(original_item.get("base_servings") or original_item.get("servings") or 3 or 3)
    parsed = parse_ingredient_line(edited_line)
    if parsed is None:
        return {
            "name": normalize_ingredient_name(edited_line),
            "amount": None,
            "unit": "",
            "text": edited_line,
            "base_servings": base_servings,
        }

    amount = parsed.get("amount")
    if amount is not None:
        try:
            scaled_back = float(amount) * max(base_servings, 1) / max(servings, 1)
            if abs(scaled_back - round(scaled_back)) < 0.0001:
                scaled_back = int(round(scaled_back))
            parsed["amount"] = scaled_back
        except Exception:
            pass
    parsed["name"] = normalize_ingredient_name(parsed.get("name") or parsed.get("text") or "")
    parsed["base_servings"] = base_servings
    parsed["text"] = ingredient_item_text(parsed, base_servings)
    return parsed


def apply_shopping_edits_to_recipe(recipe_id: int, recipe: sqlite3.Row, servings: int, edited_labels: dict[str, str]) -> int:
    ingredients = ingredients_from_json(recipe["ingredients_json"] or "")
    if not ingredients:
        return 0
    changed = 0
    for idx_str, edited in edited_labels.items():
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        if idx < 0 or idx >= len(ingredients):
            continue
        current = ingredients[idx]
        current_label = clean_pdf_cell(ingredient_item_text(current, servings))
        edited_clean = clean_pdf_cell(edited)
        if not edited_clean or edited_clean == current_label:
            continue
        updated = _ingredient_from_edited_shopping_line(edited_clean, current, servings)
        if updated != current:
            ingredients[idx] = updated
            changed += 1
    if changed:
        conn = get_conn()
        conn.execute(
            "UPDATE recipes SET ingredients_json = ?, search_text = ? WHERE id = ?",
            (
                ingredients_to_json(ingredients),
                build_search_text(recipe["title"], recipe["subtitle"], recipe["tags"], ingredients_json_to_lines(ingredients_to_json(ingredients))),
                recipe_id,
            ),
        )
        conn.commit()
    return changed


# ---------- background ----------
def backfill_previews(limit: int = 20) -> None:
    ensure_dirs()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, filename, preview_filename, is_custom, image_filename FROM recipes WHERE archive = 0 LIMIT ?", (limit,)).fetchall()
        changed = False
        for row in rows:
            if row["is_custom"] and row["image_filename"]:
                continue
            pdf_path = PDF_DIR / (row["filename"] or "")
            if not pdf_path.exists():
                continue
            current_preview = row["preview_filename"] or ""
            current_preview_path = PREVIEW_DIR / current_preview if current_preview else None
            if current_preview_path and preview_is_valid(current_preview_path):
                continue
            preview = create_preview(pdf_path)
            if preview:
                conn.execute("UPDATE recipes SET preview_filename = ? WHERE id = ?", (preview, row["id"]))
                changed = True
        if changed:
            conn.commit()


def backfill_ingredients(limit: int = 50) -> None:
    ensure_dirs()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, filename, original_filename, ingredients_json, is_custom FROM recipes WHERE archive = 0 LIMIT ?",
            (limit,),
        ).fetchall()
        changed = False
        for row in rows:
            if row["is_custom"]:
                continue
            existing = ingredients_from_json(row["ingredients_json"] or "")
            if existing and not ingredients_need_refresh(existing):
                continue
            pdf_path = PDF_DIR / (row["filename"] or "")
            if not pdf_path.exists():
                continue
            metadata = parse_pdf(pdf_path, row["original_filename"] or row["filename"] or "rezept.pdf", base_servings=3)
            if metadata.get("ingredients_json") and metadata.get("ingredients_json") != "[]":
                conn.execute("UPDATE recipes SET ingredients_json = ? WHERE id = ?", (metadata["ingredients_json"], row["id"]))
                changed = True
        if changed:
            conn.commit()


def auto_import_loop() -> None:
    # Wie beim Kleinanzeigen-Manager: erster Hintergrundlauf kurz nach dem Start, danach stündlich.
    time.sleep(30)
    while True:
        try:
            with app.app_context():
                _process_import_files(trigger="automatic")
                backfill_previews(limit=10)
        except Exception as exc:
            print(f"[hf-addon] auto import error: {exc}")
        time.sleep(AUTO_IMPORT_INTERVAL_SECONDS)


def start_background_tasks() -> None:
    if app.config.get("AUTO_IMPORT_THREAD_STARTED"):
        return
    thread = threading.Thread(target=auto_import_loop, daemon=True)
    thread.start()
    app.config["AUTO_IMPORT_THREAD_STARTED"] = True


# ---------- routes ----------
@app.route("/")
def dashboard():
    import_state = _load_import_state()
    pending_notice = int(import_state.get("pending_notice") or 0)
    if pending_notice:
        flash(
            f"{pending_notice} neues Rezept wurde automatisch gespeichert." if pending_notice == 1 else f"{pending_notice} neue Rezepte wurden automatisch gespeichert.",
            "success",
        )
        import_state["pending_notice"] = 0
        _save_import_state(import_state)

    sync_duplicate_groups()
    upcoming_plan = upcoming_plan_preview(limit=None)
    return render_template(
        "dashboard.html",
        upcoming_plan=upcoming_plan,
        title="Die nächsten geplanten Essen",
    )


@app.route("/recipes")
def recipes_library():
    sync_duplicate_groups()
    search = request.args.get("q", "").strip()
    view = request.args.get("view", "tags").strip()
    if view not in {"tags", "availability"}:
        view = "tags"
    tab = request.args.get("tab", "alle")
    if view == "tags":
        tab = "alle"
    quick_tag = request.args.get("tag", "").strip()
    if view == "availability":
        recipe_tab = {"alle": "offen", "vorhanden": "lieferbar", "unterwegs": "unterwegs"}.get(tab, "offen")
    else:
        recipe_tab = tab
    rows = query_recipes(search=search, tab=recipe_tab, quick_tag=quick_tag if view == "tags" else "")
    plan_days, open_plan_map = quick_plan_window()
    for recipe in rows:
        recipe["planned_label"] = planned_recipe_label(open_plan_map.get(recipe.get("id")))
    groups = grouped_recipe_rows(rows)
    counts = recipe_counts()
    if view == "availability":
        counts["alle"] = counts["offen"]
        counts["vorhanden"] = sum(1 for row in all_active_recipes() if row.get("status") == STATUS_OPEN and not row.get("is_future_delivery"))
        counts["unterwegs"] = sum(1 for row in all_active_recipes() if row.get("status") == STATUS_OPEN and row.get("is_future_delivery"))
    return render_template(
        "recipes.html",
        groups=groups,
        counts=counts,
        q=search,
        tab=tab,
        view=view,
        quick_tag=quick_tag,
        quick_tags=["Reis", "Pasta", "Hähnchen", "Kartoffeln", "Vegetarisch", "Schnell", "High Protein"],
        plan_days=plan_days,
        open_plan_map=open_plan_map,
        title="Alle Rezepte",
    )


@app.route("/recipes/open/plan-batch", methods=["POST"])
def open_recipe_plan_save_batch():
    return_tab = request.form.get("return_tab", "alle").strip()
    if return_tab not in {"alle", "unterwegs"}:
        return_tab = "alle"
    return_view = request.form.get("return_view", "tags").strip()
    if return_view not in {"tags", "availability"}:
        return_view = "tags"
    plan_days, _ = quick_plan_window()
    allowed_dates = {item["iso"] for item in plan_days}
    start_iso = plan_days[0]["iso"] if plan_days else date.today().isoformat()
    end_iso = plan_days[-1]["iso"] if plan_days else date.today().isoformat()
    recipe_ids = []
    for raw in request.form.getlist("recipe_ids"):
        if str(raw).isdigit():
            rid = int(raw)
            if rid not in recipe_ids:
                recipe_ids.append(rid)

    selected: dict[int, str] = {}
    used_dates: dict[str, int] = {}
    for recipe_id in recipe_ids:
        plan_date = request.form.get(f"plan_date__{recipe_id}", "").strip()
        if plan_date and plan_date not in allowed_dates:
            flash("Mindestens eine ausgewählte Planung liegt außerhalb des erlaubten Zeitraums.", "error")
            return redirect(url_for("recipes_library", view=return_view, tab=return_tab))
        if plan_date:
            if plan_date in used_dates and used_dates[plan_date] != recipe_id:
                flash("Ein Tag wurde mehreren Rezepten zugewiesen. Bitte pro Tag nur ein Rezept wählen.", "error")
                return redirect(url_for("recipes_library", view=return_view, tab=return_tab))
            used_dates[plan_date] = recipe_id
        selected[recipe_id] = plan_date

    conn = get_conn()
    changed = 0
    for recipe_id, plan_date in selected.items():
        recipe = conn.execute("SELECT id, status FROM recipes WHERE id = ? AND archive = 0", (recipe_id,)).fetchone()
        if recipe is None or normalize_recipe_status(recipe["status"], STATUS_OPEN) != STATUS_OPEN:
            continue

        existing_rows = conn.execute(
            "SELECT plan_date FROM meal_plans WHERE recipe_id = ? AND plan_date BETWEEN ? AND ?",
            (recipe_id, start_iso, end_iso),
        ).fetchall()
        existing_dates = {row["plan_date"] for row in existing_rows}

        if not plan_date:
            if existing_dates:
                conn.execute(
                    "DELETE FROM meal_plans WHERE recipe_id = ? AND plan_date BETWEEN ? AND ?",
                    (recipe_id, start_iso, end_iso),
                )
                changed += 1
            continue

        if not _recipe_available_on(recipe_id, plan_date, conn):
            flash("Ein HelloFresh-Rezept kann erst ab seinem Lieferdatum eingeplant werden.", "error")
            return redirect(url_for("recipes_library", view=return_view, tab=return_tab))

        occupant = conn.execute(
            "SELECT recipe_id, free_text, iphone_title FROM meal_plans WHERE plan_date = ?",
            (plan_date,),
        ).fetchone()
        if occupant and int(occupant["recipe_id"] or 0) not in (0, recipe_id):
            continue
        if occupant and not occupant["recipe_id"] and ((occupant["free_text"] or "").strip() or (occupant["iphone_title"] or "").strip()):
            continue

        if existing_dates != {plan_date}:
            conn.execute(
                "DELETE FROM meal_plans WHERE recipe_id = ? AND plan_date BETWEEN ? AND ?",
                (recipe_id, start_iso, end_iso),
            )
            save_meal_plan(plan_date, str(recipe_id), "", "", "")
            changed += 1

    conn.commit()
    flash(f"{changed} Zuweisung(en) im Essensplan gespeichert.", "success")
    return redirect(url_for("recipes_library", view=return_view, tab=return_tab))


@app.route("/upload", methods=["GET", "POST"])
def upload_recipe():
    if request.method == "POST":
        delivered_at = request.form.get("delivered_at", "").strip()
        status = normalize_recipe_status(request.form.get("status"), STATUS_OPEN)
        files = request.files.getlist("pdfs")
        valid_files = [f for f in files if f and f.filename and allowed_file(f.filename)]
        if not valid_files:
            flash("Bitte mindestens eine PDF-Datei auswählen.", "error")
            return redirect(url_for("upload_recipe"))
        imported = 0
        for file_storage in valid_files:
            ok, _detected_title = upsert_recipe_from_upload(file_storage, delivered_at=delivered_at, status=status)
            if ok:
                imported += 1
        flash(f"{imported} Rezept(e) importiert. Erkannte Varianten wurden automatisch zusammengefasst.", "success")
        return redirect(url_for("recipes_library"))
    return render_template(
        "upload.html",
        import_dir=str(IMPORT_DIR),
        import_status=_import_status_for_ui(),
        recent=recent_recipes(limit=6),
        title="Import",
    )


@app.route("/hellofresh-import")
def hellofresh_import():
    return render_template(
        "hellofresh_import.html",
        hellofresh=_hellofresh_view_state(),
        title="HelloFresh übertragen",
    )


@app.route("/hellofresh-import/preview", methods=["POST"])
def hellofresh_import_preview():
    week_type = request.form.get("week_type", "upcoming")
    account_key = request.form.get("account_key", "1")
    delivery_url = request.form.get("delivery_url", "").strip()
    if week_type not in {"upcoming", "past"}:
        week_type = "upcoming"
    state = _load_hellofresh_state()
    if week_type == "upcoming":
        valid_urls = {str(item.get("url") or "") for item in state.get("deliveries", []) if isinstance(item, dict)}
        if str(state.get("account_key") or "") != str(account_key) or delivery_url not in valid_urls:
            flash("Bitte rufe zuerst die Liefertermine für dieses Konto ab und wähle einen Termin aus.", "error")
            return redirect(url_for("hellofresh_import"))
    try:
        _preview_hellofresh_week(week_type, account_key, delivery_url)
    except RuntimeError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("HelloFresh konnte nicht geprüft werden.", "error")
    return redirect(url_for("hellofresh_import"))


@app.route("/hellofresh-import/deliveries", methods=["POST"])
def hellofresh_import_deliveries():
    account_key = request.form.get("account_key", "1")
    try:
        _load_hellofresh_delivery_dates(account_key)
    except RuntimeError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("HelloFresh-Liefertermine konnten nicht abgerufen werden.", "error")
    return redirect(url_for("hellofresh_import"))


@app.route("/hellofresh-import/browser/open", methods=["POST"])
def hellofresh_import_browser_open():
    global _hellofresh_visible_browser_launching
    account_key = request.form.get("account_key", "1")
    account = _hellofresh_account(account_key)
    with _hellofresh_visible_browser_lock:
        if _hellofresh_visible_browser_launching or _hellofresh_visible_browser_running():
            return redirect(_hellofresh_vnc_url())
        if _hellofresh_lock.locked():
            flash("Während eines laufenden Transfers kann kein Login-Browser geöffnet werden.", "error")
            return redirect(url_for("hellofresh_import"))
        _hellofresh_visible_browser_launching = True
        _update_hellofresh_state(
            phase="login_starting",
            message=f"Der sichtbare Browser für {account['label']} wird gestartet …",
            account_key=account_key,
            active_account_label=account["label"],
        )
    worker = threading.Thread(target=_open_hellofresh_login_browser_worker, args=(account_key,), daemon=True)
    worker.start()
    return redirect(_hellofresh_vnc_url())


@app.route("/hellofresh-import/browser/close", methods=["POST"])
def hellofresh_import_browser_close():
    account_key = _hellofresh_visible_browser_account_key
    _stop_hellofresh_login_browser()
    if account_key:
        _update_hellofresh_state(
            phase="idle",
            message=f"Die Sitzung für {_hellofresh_account(account_key)['label']} wurde gespeichert. Du kannst jetzt die Liefertermine abrufen.",
            account_key=account_key,
            active_account_label=_hellofresh_account(account_key)["label"],
        )
    flash("Browser geschlossen. Die HelloFresh-Sitzung bleibt für dieses Konto gespeichert.", "success")
    return redirect(url_for("hellofresh_import"))


@app.route("/hellofresh-import/start", methods=["POST"])
def hellofresh_import_start():
    state = _load_hellofresh_state()
    try:
        previewed_at = datetime.fromisoformat(str(state.get("previewed_at") or ""))
    except ValueError:
        previewed_at = None
    if not previewed_at or (datetime.now().astimezone() - previewed_at.astimezone()).total_seconds() > HELLOFRESH_PREVIEW_MAX_AGE_SECONDS:
        flash("Bitte prüfe die HelloFresh-Woche erneut, bevor Du den Transfer startest.", "error")
        return redirect(url_for("hellofresh_import"))
    selected_keys = {key for key in request.form.getlist("recipe_keys") if key}
    preview_keys = {str(recipe.get("key")) for recipe in state.get("recipes", []) if isinstance(recipe, dict)}
    selected_keys &= preview_keys
    if not selected_keys:
        flash("Bitte wähle mindestens ein Rezept aus.", "error")
        return redirect(url_for("hellofresh_import"))
    if not _hellofresh_lock.acquire(blocking=False):
        flash("Ein HelloFresh-Transfer läuft bereits.", "error")
        return redirect(url_for("hellofresh_import"))
    _update_hellofresh_state(phase="importing", message="Übertragung wird vorbereitet …", total=len(selected_keys), completed=0, imported=0, skipped=0, failed=0, errors=[])
    worker = threading.Thread(target=_run_hellofresh_import, args=(selected_keys,), daemon=True)
    worker.start()
    return redirect(url_for("hellofresh_import"))


@app.route("/api/hellofresh-import/status")
def api_hellofresh_import_status():
    return jsonify(_hellofresh_view_state())


@app.route("/recipes/new", methods=["GET", "POST"])
def create_custom_recipe():
    if request.method == "POST":
        title = clean_recipe_title(request.form.get("title", "").strip())
        subtitle = clean_recipe_title(request.form.get("subtitle", "").strip())
        tags = request.form.get("tags", "").strip()
        note = request.form.get("note", "").strip()
        instructions = request.form.get("instructions", "").strip()
        status = normalize_recipe_status(request.form.get("status"), STATUS_OPEN)
        try:
            base_servings = max(1, min(12, int(request.form.get("base_servings", 3) or 3)))
        except ValueError:
            base_servings = 3
        ingredients_json = parse_ingredients_text_block(request.form.get("ingredients_text", ""), base_servings)
        image = request.files.get("image")
        if not title:
            flash("Bitte einen Rezeptnamen eingeben.", "error")
            return redirect(url_for("create_custom_recipe"))
        image_filename = ""
        if image and image.filename:
            if not allowed_image(image.filename):
                flash("Bitte nur ein Bild (PNG, JPG, WEBP oder GIF) hochladen.", "error")
                return redirect(url_for("create_custom_recipe"))
            image_filename = store_uploaded_image(image)
        conn = get_conn()
        conn.execute(
            """
            INSERT INTO recipes (
                title, subtitle, recipe_number, filename, preview_filename, original_filename, uploaded_at,
                delivered_at, cooked_at, status, rating, favorite, note, tags, search_text, archive,
                import_source, cooked_count, cook_preference, is_custom, image_filename, base_servings,
                ingredients_json, instructions, duplicate_group, duplicate_detached
            ) VALUES (?, ?, '', '', ?, '', ?, '', '', ?, 0, 0, ?, ?, ?, 0, 'custom', 0, '', 1, ?, ?, ?, ?, ?, 0)
            """,
            (
                title,
                subtitle,
                image_filename,
                datetime.now().isoformat(timespec="seconds"),
                status,
                note,
                tags,
                "\n".join([title, subtitle, tags, note]),
                image_filename,
                base_servings,
                ingredients_json,
                instructions,
                duplicate_group_key(title),
            ),
        )
        conn.commit()
        recipe_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        flash("Eigenes Rezept angelegt.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))
    return render_template("custom_recipe.html", title="Eigenes Rezept")


@app.route("/import-folder", methods=["POST"])
def import_folder():
    result = _process_import_files(trigger="manual")
    if result.get("busy"):
        flash("Der Import wird bereits geprüft.", "error")
        return redirect(request.referrer or url_for("dashboard"))

    imported = int(result.get("imported") or 0)
    duplicates = int(result.get("duplicates") or 0)
    failed = int(result.get("failed") or 0)

    if imported and not duplicates and not failed:
        if imported == 1:
            flash("1 neues Rezept wurde gespeichert.", "success")
        else:
            flash(f"{imported} neue Rezepte wurden gespeichert.", "success")
    elif imported or duplicates or failed:
        parts: list[str] = []
        if imported:
            parts.append(f"{imported} neu")
        if duplicates:
            parts.append(f"{duplicates} mögliche Duplikate vorgemerkt")
        if failed:
            parts.append(f"{failed} in den Fehlerordner verschoben")
        category = "error" if failed and not imported and not duplicates else "success"
        flash("Import abgeschlossen: " + ", ".join(parts) + ".", category)
    else:
        flash("Keine neuen PDF-Importdateien gefunden.", "error")

    return redirect(request.referrer or url_for("dashboard"))


@app.route("/recipe/<int:recipe_id>")
def recipe_detail(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        return redirect(url_for("dashboard"))
    recipe_dict = recipe_to_dict(recipe)
    available_from = parse_date(recipe_dict.get("available_from") or "")
    plan_options = []
    start = monday_for()
    for offset in range(14):
        current = start + timedelta(days=offset)
        plan_options.append({
            "iso": current.isoformat(),
            "label": f"{['Mo','Di','Mi','Do','Fr','Sa','So'][current.weekday()]} · {current.strftime('%d.%m.%Y')}",
            "available": not available_from or current >= available_from,
        })
    existing_plan = conn.execute("SELECT plan_date FROM meal_plans WHERE recipe_id = ? ORDER BY plan_date DESC LIMIT 1", (recipe_id,)).fetchone()
    ingredient_lines = ingredients_json_to_lines(recipe["ingredients_json"])
    return render_template(
        "detail.html",
        recipe=recipe_dict,
        recipe_row=recipe,
        plan_options=plan_options,
        existing_plan_date=(existing_plan["plan_date"] if existing_plan else ""),
        ingredient_lines=ingredient_lines,
        title=recipe_dict["title"],
    )


@app.route("/recipe/<int:recipe_id>/save", methods=["POST"])
def recipe_save(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        flash("Rezept nicht gefunden.", "error")
        return redirect(url_for("dashboard"))

    title = clean_recipe_title(request.form.get("title", recipe["title"] or "").strip()) or clean_recipe_title(recipe["title"] or "")
    subtitle = clean_recipe_title(request.form.get("subtitle", recipe["subtitle"] or "").strip())
    rating = max(0, min(5, int(request.form.get("rating", 0) or 0)))
    favorite = 1 if request.form.get("favorite") == "on" else 0
    status = normalize_recipe_status(request.form.get("status"), STATUS_OPEN)
    note = request.form.get("note", "").strip()
    tags = request.form.get("tags", "").strip()
    delivered_at = request.form.get("delivered_at", "").strip()
    cooked_at = request.form.get("cooked_at", "").strip()
    if status == STATUS_COOKED and not cooked_at:
        cooked_at = datetime.now().date().isoformat()
    elif status != STATUS_COOKED:
        cooked_at = ""
    try:
        base_servings = max(1, min(12, int(request.form.get("base_servings", 3) or 3)))
    except ValueError:
        base_servings = int(recipe["base_servings"] or 3)
    ingredients_json = parse_ingredients_text_block(request.form.get("ingredients_text", ""), base_servings)
    instructions = request.form.get("instructions", "").strip()
    current_ingredient_lines = ingredients_json_to_lines(ingredients_json)
    search_text = build_search_text(title, subtitle, tags, current_ingredient_lines, note)

    cooked_count = int(recipe["cooked_count"] or 0)
    old_cooked_at = recipe["cooked_at"] or ""
    old_status = normalize_recipe_status(recipe["status"], STATUS_OPEN)
    if status == STATUS_COOKED and cooked_at and cooked_at != old_cooked_at and old_status != STATUS_COOKED:
        cooked_count += 1
    elif status == STATUS_COOKED and cooked_at and not old_cooked_at:
        cooked_count += 1

    conn.execute(
        """
        UPDATE recipes
        SET title = ?, subtitle = ?, delivered_at = ?, cooked_at = ?, status = ?, rating = ?, favorite = ?, note = ?, tags = ?, search_text = ?, cooked_count = ?,
            cook_preference = '', base_servings = ?, ingredients_json = ?, instructions = ?
        WHERE id = ?
        """,
        (title, subtitle, delivered_at, cooked_at, status, rating, favorite, note, tags, search_text, cooked_count, base_servings, ingredients_json, instructions, recipe_id),
    )
    conn.commit()
    if not int(recipe["duplicate_detached"] or 0):
        conn.execute("UPDATE recipes SET duplicate_group = ? WHERE id = ?", (duplicate_group_key(title), recipe_id))
        conn.commit()
        sync_duplicate_groups()
    flash("Rezept gespeichert.", "success")
    return redirect(url_for("recipe_detail", recipe_id=recipe_id))


@app.route("/recipe/<int:recipe_id>/toggle_cooked", methods=["POST"])
def recipe_toggle_cooked(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        flash("Rezept nicht gefunden.", "error")
        return redirect(url_for("dashboard"))
    cooked_count = int(recipe["cooked_count"] or 0)
    current_status = normalize_recipe_status(recipe["status"], STATUS_OPEN)
    if current_status == STATUS_COOKED:
        # Button text and user expectation: cooked recipes go back to "offen",
        # so they appear again in the open recipe tab.
        status = STATUS_OPEN
        cooked_at = ""
    else:
        status = STATUS_COOKED
        cooked_at = datetime.now().date().isoformat()
        cooked_count += 1
    conn.execute("UPDATE recipes SET status = ?, cooked_at = ?, cooked_count = ? WHERE id = ?", (status, cooked_at, cooked_count, recipe_id))
    conn.commit()
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/recipe/<int:recipe_id>/favorite", methods=["POST"])
def recipe_favorite(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        return redirect(url_for("dashboard"))
    favorite = 0 if recipe["favorite"] else 1
    conn.execute("UPDATE recipes SET favorite = ? WHERE id = ?", (favorite, recipe_id))
    conn.commit()
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/recipe/<int:recipe_id>/archive", methods=["POST"])
def recipe_archive(recipe_id: int):
    conn = get_conn()
    conn.execute("UPDATE recipes SET archive = 1 WHERE id = ?", (recipe_id,))
    conn.commit()
    flash("Rezept archiviert.", "success")
    return redirect(url_for("dashboard"))


@app.route("/recipe/<int:recipe_id>/separate", methods=["POST"])
def recipe_separate(recipe_id: int):
    if not detach_recipe_from_group(recipe_id):
        flash("Rezept nicht gefunden.", "error")
    else:
        flash("Dieses Rezept wird jetzt als eigenständiges Rezept geführt.", "success")
    return redirect(request.referrer or url_for("recipes_library"))


@app.route("/recipe/<int:recipe_id>/pdf")
def recipe_pdf(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        return redirect(url_for("dashboard"))
    if recipe["is_custom"]:
        flash("Eigene Rezepte haben keine PDF-Datei.", "error")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))
    pdf_path = PDF_DIR / (recipe["filename"] or "")
    if not pdf_path.exists():
        flash("PDF-Datei nicht gefunden.", "error")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=recipe["original_filename"] or "rezept.pdf")


@app.route("/recipe/<int:recipe_id>/preview")
def recipe_preview(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        return redirect(url_for("static", filename="placeholder-food.svg"))
    if recipe["is_custom"] and recipe["image_filename"]:
        image_path = PREVIEW_DIR / recipe["image_filename"]
        if image_path.exists():
            mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
            return send_file(image_path, mimetype=mime)
    preview = recipe["preview_filename"] or ""
    preview_path = PREVIEW_DIR / preview if preview else None
    if not preview_path or not preview_is_valid(preview_path):
        pdf_path = PDF_DIR / (recipe["filename"] or "")
        if pdf_path.exists():
            new_preview = create_preview(pdf_path)
            if new_preview:
                conn.execute("UPDATE recipes SET preview_filename = ? WHERE id = ?", (new_preview, recipe_id))
                conn.commit()
                preview_path = PREVIEW_DIR / new_preview
    if preview_path and preview_path.exists():
        mime = mimetypes.guess_type(str(preview_path))[0] or "application/octet-stream"
        return send_file(preview_path, mimetype=mime)
    return redirect(url_for("static", filename="placeholder-food.svg"))


@app.route("/recipe/<int:recipe_id>/shopping", methods=["GET", "POST"])
def recipe_shopping(recipe_id: int):
    conn = get_conn()
    recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        flash("Rezept nicht gefunden.", "error")
        return redirect(url_for("dashboard"))
    is_custom = bool(recipe["is_custom"])
    try:
        servings = int(request.values.get("servings") or recipe["base_servings"] or 3)
    except ValueError:
        servings = int(recipe["base_servings"] or 3)
    servings = max(1, min(12, servings))
    choices = build_shopping_choices(recipe, servings)
    if request.method == "POST":
        action = clean_pdf_cell(request.form.get("action", "add")).lower() or "add"
        selected_ids = set(request.form.getlist("items"))
        selected_items: list[str] = []
        corrected_count = 0
        learned_count = 0
        edited_labels: dict[str, str] = {}
        for choice in choices:
            original_label = clean_pdf_cell(choice["label"])
            edited = clean_pdf_cell(request.form.get(f"item_text_{choice['id']}", original_label))
            if edited and edited != original_label:
                edited_labels[choice["id"]] = edited
                corrected_count += 1
                if learn_ingredient_correction_from_lines(original_label, edited):
                    learned_count += 1
            if choice["id"] not in selected_ids:
                continue
            if not edited:
                continue
            selected_items.append(edited)

        saved_count = apply_shopping_edits_to_recipe(recipe_id, recipe, servings, edited_labels)

        if action == "save":
            if not corrected_count:
                flash("Keine Änderungen zum Speichern gefunden.", "success")
            else:
                message = f"{corrected_count} Änderung(en) gespeichert"
                extras: list[str] = []
                if learned_count:
                    extras.append(f"{learned_count} für künftige Rezepte gemerkt")
                if saved_count:
                    extras.append(f"{saved_count} im Rezept aktualisiert")
                if extras:
                    message += " · " + " · ".join(extras)
                flash(message + ".", "success")
            return redirect(url_for("recipe_shopping", recipe_id=recipe_id, servings=servings))

        if not selected_items:
            flash("Bitte mindestens eine Zutat auswählen.", "error")
            return redirect(url_for("recipe_shopping", recipe_id=recipe_id, servings=servings))

        ok, error, target_name = add_items_to_own_shopping_list(selected_items)
        if ok:
            message = f"{len(selected_items)} Zutat(en) zu {target_name or 'Einkaufsliste'} hinzugefügt"
            extras: list[str] = []
            if corrected_count:
                extras.append(f"{corrected_count} manuell korrigiert")
            if learned_count:
                extras.append(f"{learned_count} für künftige Rezepte gemerkt")
            if saved_count:
                extras.append(f"{saved_count} im Rezept aktualisiert")
            if extras:
                message += " · " + " · ".join(extras)
            flash(message + ".", "success")
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))
        flash(f"Einkaufsliste konnte nicht aktualisiert werden: {error}", "error")
        return redirect(url_for("recipe_shopping", recipe_id=recipe_id, servings=servings))
    return render_template(
        "shopping.html",
        recipe=recipe_to_dict(recipe),
        servings=servings,
        choices=choices,
        is_custom=is_custom,
        shopping_target=own_shopping_list_target()[1] or "Eigene Einkaufsliste",
        title="Einkaufsliste",
        app_brand=APP_BRAND,
        app_eyebrow=APP_EYEBROW,
    )


@app.route("/duplicates/<token>/pdf")
def duplicate_candidate_pdf(token: str):
    pdf_path = _duplicate_candidate_pdf_path(token)
    meta_path = _duplicate_candidate_meta_path(token)
    if not pdf_path.exists() or not meta_path.exists():
        flash("Duplikat-Datei nicht gefunden.", "error")
        return redirect(url_for("dashboard"))
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=meta.get("original_filename") or "duplikat.pdf")


@app.route("/duplicates/<token>/preview")
def duplicate_candidate_preview(token: str):
    pdf_path = _duplicate_candidate_pdf_path(token)
    meta_path = _duplicate_candidate_meta_path(token)
    if not pdf_path.exists() or not meta_path.exists():
        return redirect(url_for("static", filename="placeholder-food.svg"))
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    preview_name = meta.get("candidate_preview_filename") or ""
    preview_path = PREVIEW_DIR / preview_name if preview_name else None
    if not preview_path or not preview_is_valid(preview_path):
        preview_name = create_preview(pdf_path) or ""
        if preview_name:
            meta["candidate_preview_filename"] = preview_name
            try:
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            preview_path = PREVIEW_DIR / preview_name
    if preview_path and preview_path.exists():
        mime = mimetypes.guess_type(str(preview_path))[0] or "application/octet-stream"
        return send_file(preview_path, mimetype=mime)
    return redirect(url_for("static", filename="placeholder-food.svg"))


@app.route("/duplicates/<token>/keep", methods=["POST"])
def duplicate_candidate_keep(token: str):
    recipe_id = import_duplicate_candidate(token)
    if recipe_id is None:
        flash("Duplikat-Datei nicht gefunden.", "error")
        return redirect(url_for("dashboard"))
    flash("Rezept wurde trotz Duplikat-Erkennung behalten.", "success")
    return redirect(url_for("recipe_detail", recipe_id=recipe_id))


@app.route("/duplicates/<token>/discard", methods=["POST"])
def duplicate_candidate_discard(token: str):
    meta_path = _duplicate_candidate_meta_path(token)
    existing_id = 0
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_id = int(meta.get("existing_id") or 0)
        except Exception:
            existing_id = 0
    if existing_id:
        conn = get_conn()
        conn.execute("UPDATE recipes SET status = ?, cooked_at = '' WHERE id = ?", (STATUS_OPEN, existing_id))
        conn.commit()
    remove_duplicate_candidate(token)
    if existing_id:
        flash("Duplikat verworfen. Das vorhandene Rezept wurde wieder als offen markiert.", "success")
    else:
        flash("Vorgemerkter Duplikat-Import wurde verworfen.", "success")
    return redirect(request.referrer or url_for("dashboard"))



def meal_plan_payload_for(plan_date: str) -> dict[str, Any]:
    dt = parse_date(plan_date)
    if not dt:
        dt = date.today()
        plan_date = dt.isoformat()

    conn = get_conn()
    row = conn.execute(
        """
        SELECT mp.plan_date, mp.recipe_id, mp.free_text, mp.note, mp.iphone_title, mp.created_at, mp.updated_at,
               r.title AS recipe_title, r.status AS recipe_status, r.rating AS recipe_rating,
               r.search_text AS recipe_search_text
        FROM meal_plans mp
        LEFT JOIN recipes r ON r.id = mp.recipe_id
        WHERE mp.plan_date = ?
        """,
        (plan_date,),
    ).fetchone()

    weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]

    if not row:
        return {
            "date": plan_date,
            "date_de": fmt_date(plan_date),
            "weekday": weekday,
            "display": "",
            "type": "empty",
            "recipe_id": None,
            "recipe_title": "",
            "free_text": "",
            "iphone_title": "",
            "note": "",
            "calories": None,
            "recipe_status": "",
            "recipe_rating": 0,
            "updated_at": "",
        }

    data = dict(row)
    recipe_title = clean_recipe_title(data.get("recipe_title") or "")
    free_text = data.get("free_text") or ""
    iphone_title = (data.get("iphone_title") or "").strip()
    display = iphone_title or recipe_title or free_text
    entry_type = "recipe" if data.get("recipe_id") else ("free_text" if free_text else "empty")
    calories = extract_calories(data.get("recipe_search_text") or "") if recipe_title else None

    return {
        "date": plan_date,
        "date_de": fmt_date(plan_date),
        "weekday": weekday,
        "display": display,
        "type": entry_type,
        "recipe_id": data.get("recipe_id"),
        "recipe_title": recipe_title,
        "free_text": free_text,
        "iphone_title": iphone_title,
        "note": data.get("note") or "",
        "calories": calories,
        "recipe_status": data.get("recipe_status") or "",
        "recipe_rating": data.get("recipe_rating") or 0,
        "updated_at": data.get("updated_at") or "",
    }


@app.route("/api/plan/today")
def api_plan_today():
    return jsonify(meal_plan_payload_for(date.today().isoformat()))


@app.route("/api/plan/<plan_date>")
def api_plan_date(plan_date: str):
    return jsonify(meal_plan_payload_for(plan_date))


@app.route("/plan")
def meal_plan():
    start = monday_for()
    weeks = load_meal_plans(start, weeks=2)
    recipes = available_recipes_for_planning()
    return render_template("plan.html", weeks=weeks, recipes=recipes, title="Essenplanung")


@app.route("/plan/save", methods=["POST"])
def meal_plan_save():
    plan_date = request.form.get("plan_date", "").strip()
    recipe_id = request.form.get("recipe_id", "").strip()
    free_text = request.form.get("free_text", "").strip()
    iphone_title = request.form.get("iphone_title", "").strip()
    note = request.form.get("note", "").strip()
    try:
        save_meal_plan(plan_date, recipe_id, free_text, note, iphone_title)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("meal_plan"))
    weekday = weekday_de(plan_date)
    flash(f"Plan für {weekday} {fmt_date(plan_date)} gespeichert.", "success")
    next_target = request.form.get("next", "").strip()
    if next_target == "detail" and str(request.form.get("detail_recipe_id", "")).isdigit():
        return redirect(url_for("recipe_detail", recipe_id=int(request.form.get("detail_recipe_id"))))
    return redirect(url_for("meal_plan"))


@app.route("/plan/save-batch", methods=["POST"])
def meal_plan_save_batch():
    plan_dates = list(dict.fromkeys(request.form.getlist("plan_dates")))
    saved = 0
    for plan_date in plan_dates:
        if not parse_date(plan_date):
            continue
        recipe_id = request.form.get(f"recipe_id__{plan_date}", "").strip()
        free_text = request.form.get(f"free_text__{plan_date}", "").strip()
        iphone_title = request.form.get(f"iphone_title__{plan_date}", "").strip()
        note = request.form.get(f"note__{plan_date}", "").strip()
        try:
            save_meal_plan(plan_date, recipe_id, free_text, note, iphone_title)
            saved += 1
        except ValueError:
            flash(f"{weekday_de(plan_date)} {fmt_date(plan_date)} liegt vor dem Lieferdatum des ausgewählten HelloFresh-Rezepts.", "error")
    flash(f"Essensplan gespeichert – {saved} Tage wurden gemeinsam übernommen.", "success")
    return redirect(url_for("meal_plan"))


@app.route("/plan/clear", methods=["POST"])
def meal_plan_clear():
    plan_date = request.form.get("plan_date", "").strip()
    save_meal_plan(plan_date, None, "", "", "")
    flash(f"Plan für {weekday_de(plan_date)} {fmt_date(plan_date)} entfernt.", "success")
    return redirect(url_for("meal_plan"))


@app.route("/refresh", methods=["POST"])
def refresh_redirect():
    result = _process_import_files(trigger="manual")
    imported = int(result.get("imported") or 0)
    duplicates = int(result.get("duplicates") or 0)
    failed = int(result.get("failed") or 0)
    if imported or duplicates or failed:
        flash(
            f"Aktualisiert: {imported} neu gespeichert, {failed} Fehler.",
            "success" if not failed else "error",
        )
    else:
        flash("Übersicht aktualisiert.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "0.8.15", "feature": "hellofresh-visible-browser-accounts-delivery-dates-and-pdf-transfer"})


with app.app_context():
    init_db()
    backfilled_deliveries = _backfill_recent_hellofresh_delivery_date()
    if backfilled_deliveries:
        print(f"[hf-addon] {backfilled_deliveries} kürzlich importierte HelloFresh-Rezept(e) mit Lieferdatum ergänzt")
    migrated_variants = migrate_pending_duplicate_candidates()
    if migrated_variants:
        print(f"[hf-addon] {migrated_variants} vorgemerkte Duplikat(e) als Varianten übernommen")
    sync_duplicate_groups()
    backfill_previews(limit=50)
    backfill_ingredients(limit=100)
    startup_result = _process_import_files(trigger="automatic")
    imported = int(startup_result.get("imported") or 0)
    duplicates = int(startup_result.get("duplicates") or 0)
    failed = int(startup_result.get("failed") or 0)
    if imported or duplicates or failed:
        print(f"[hf-addon] startup import: {imported} neu, {failed} fehler")
    start_background_tasks()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8131")), debug=False)
