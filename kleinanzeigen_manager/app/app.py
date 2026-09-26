from __future__ import annotations

import copy
import hashlib
import io
import ctypes
import json
import os
import re
import shutil
import signal
import select
import struct
import subprocess
import sys
import threading
import traceback
import time
import uuid
import tempfile
import zipfile
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

import yaml
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify, flash, session,
    send_file, send_from_directory,
)

APP_TITLE = "Kleinanzeigen Manager"
HOME_SCREEN_TITLE = "Kleinanzeigen Manager"
PORT = int(os.environ.get("PORT", "8139"))
DATA_DIR = Path(os.environ.get("KA_DATA_DIR", "/data"))
ADS_DIR = DATA_DIR / "ads"
IMAGES_DIR = DATA_DIR / "images"
LOGS_DIR = DATA_DIR / "logs"
BOT_CONFIG = DATA_DIR / "bot-config.yaml"
ACCOUNTS_DIR = DATA_DIR / "accounts"
MAIN_ACCOUNT_ID = "main"
MAIN_ACCOUNT_NAME = "Hauptkonto"
APP_STATE = DATA_DIR / "app-state.json"
OPERATION_STATE_FILE = DATA_DIR / "operation-state.json"
SHARE_DIR = Path(os.environ.get("KA_SHARE_DIR", "/share/Kleinanzeigen"))
DIAGNOSTICS_DIR = SHARE_DIR / "debug"
BACKUP_DIR = SHARE_DIR / "Backup"
VINTED_TRANSFER_INBOX_DIR = Path(os.environ.get("KA_VINTED_TRANSFER_INBOX", "/share/Vinted/transfer-inbox"))
VINTED_TRANSFER_RECEIPT_DIR = Path(os.environ.get("KA_VINTED_TRANSFER_RECEIPTS", "/share/Vinted/transfer-receipts"))
VINTED_SOLD_ACTION_INBOX_DIR = Path(os.environ.get("KA_VINTED_SOLD_ACTION_INBOX", "/share/Vinted/cross-platform-actions/vinted-to-kleinanzeigen"))
VINTED_DELETE_ACTION_INBOX_DIR = Path(os.environ.get("KA_VINTED_DELETE_ACTION_INBOX", "/share/Vinted/cross-platform-actions/kleinanzeigen-to-vinted"))
VINTED_CROSS_ACTION_POLL_SECONDS = max(2, int(os.environ.get("KA_VINTED_CROSS_ACTION_POLL_SECONDS", "3")))
MEDIA_DIR = Path(os.environ.get("KA_MEDIA_DIR", "/media"))
IMPORT_DIR = MEDIA_DIR / "Import" / "Kleinanzeigen"
IMPORT_ERROR_DIR = IMPORT_DIR / "Fehler"
IMPORT_EXTENSION = ".kaanzeige"
IMPORT_INTERVAL_SECONDS = int(os.environ.get("KA_IMPORT_INTERVAL_SECONDS", "3600"))
GOOGLE_DRIVE_IMPORT_ENABLED = os.environ.get("KA_GOOGLE_DRIVE_IMPORT_ENABLED", "false").lower() == "true"
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("KA_GOOGLE_DRIVE_FOLDER_ID", "").strip()
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE = Path(os.environ.get("KA_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", "/share/Kleinanzeigen/google-drive-service-account.json"))
GOOGLE_DRIVE_POLL_SECONDS = max(5, int(os.environ.get("KA_GOOGLE_DRIVE_POLL_SECONDS", "5")))
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
IMPORT_MAX_FILES = 100
IMPORT_MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
IMPORT_MAX_IMAGES = 20
IMPORT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CHAT_IMAGE_MAX_FILES = 4
CHAT_IMAGE_MAX_BYTES = 15 * 1024 * 1024
CHAT_IMAGE_MAX_TOTAL_BYTES = 30 * 1024 * 1024
EDITABLE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EDITED_IMAGE_MAX_BYTES = 60 * 1024 * 1024
BACKUP_RETENTION_DAYS = 7
APP_VERSION = "1.6.54"
APP_FEATURE = "cross-platform-sold-and-delete-sync"

REPUBLISH_INTERVAL = int(os.environ.get("REPUBLISH_INTERVAL", "3"))
DEFAULT_PRICE_REDUCTION_DAYS = int(os.environ.get("KA_PRICE_REDUCTION_DAYS", "14"))
AUTO_REPUBLISH = os.environ.get("AUTO_REPUBLISH", "false").lower() == "true"
APP_TZ = ZoneInfo(os.environ.get("KA_TIMEZONE", "Europe/Berlin"))
REPOST_LIMIT_LAST_30_DAYS = int(os.environ.get("KA_REPOST_LIMIT_LAST_30_DAYS", "100"))
ACTIVITY_AUTO_REFRESH_HOUR = int(os.environ.get("KA_ACTIVITY_AUTO_REFRESH_HOUR", "0"))
ACTIVITY_AUTO_REFRESH_MINUTE = int(os.environ.get("KA_ACTIVITY_AUTO_REFRESH_MINUTE", "30"))
ACTIVITY_RETRY_SECONDS = int(os.environ.get("KA_ACTIVITY_RETRY_SECONDS", "300"))
BOT_SLOT_RETRY_SECONDS = max(30, int(os.environ.get("KA_BOT_SLOT_RETRY_SECONDS", "60")))
SCHEDULER_POLL_SECONDS = max(5, int(os.environ.get("KA_SCHEDULER_POLL_SECONDS", "10")))
UNCERTAIN_PUBLISH_CONFIRM_SECONDS = max(15, int(os.environ.get("KA_UNCERTAIN_PUBLISH_CONFIRM_SECONDS", "75")))
UNCERTAIN_PUBLISH_CONFIRM_INTERVAL = max(2.0, float(os.environ.get("KA_UNCERTAIN_PUBLISH_CONFIRM_INTERVAL", "3")))
REPUBLISH_PUBLISH_RETRY_MAX = max(1, int(os.environ.get("KA_REPUBLISH_PUBLISH_RETRY_MAX", "3")))
# Browser-/Login-Startfehler sind vor dem ersten Anzeigenzugriff zwar sicher
# wiederholbar, dürfen aber nicht endlos sichtbare Versuche erzeugen.  Jeder
# dieser Versuche hinterlässt vorher ein Manager-Diagnosepaket.
PUBLISH_PRESTART_RETRY_MAX = max(1, int(os.environ.get("KA_PUBLISH_PRESTART_RETRY_MAX", "3")))
# Must exceed the bot's 8-minute watchdog plus its bounded ZIP capture, so the
# manager preserves the bot's own exact DOM diagnostics before applying its
# independent subprocess fallback.
PUBLISH_BOT_PROCESS_TIMEOUT_SECONDS = max(510, int(os.environ.get("KA_PUBLISH_BOT_PROCESS_TIMEOUT_SECONDS", "540")))
# Neue Nachrichten gehen bewusst an den Home-Assistant-Sammeldienst. Alle
# anderen Hinweise bleiben auf primarys iPhone, damit die übrigen Geräte nicht
# mit Import-, Limit- oder Fehlerhinweisen gestört werden.
MESSAGE_NOTIFY_SERVICE = "notify.notify"
primary_NOTIFY_SERVICE = os.environ.get("KA_NOTIFY_SERVICE", "").strip() or "notify.mobile_app_iphone A"
PUBLIC_BASE_URL = os.environ.get("KA_PUBLIC_BASE_URL", "https://kleinanzeigen.primary-digital.de").strip().rstrip("/")
_last_access_base_url = ""

API_TOKEN_DIR_NAME = ".kleinanzeigen_api"
WEBPUSH_SUBSCRIPTIONS = DATA_DIR / "webpush-subscriptions.json"
WEBPUSH_PRIVATE_KEY = DATA_DIR / "webpush-vapid-private.pem"
APP_SECRET_FILE = DATA_DIR / "app-secret.key"
USER_MESSAGE_STATE_FILE = DATA_DIR / "user-message-state.json"
APP_USERS = {
    "primary": {"id": "primary", "name": "primary", "email": "primary.Person user@example.invalid", "initials": "PK"},
    "secondary": {"id": "secondary", "name": "secondary", "email": "user@example.invalid", "initials": "KK"},
}
_user_message_state_lock = threading.RLock()
_operation_state_lock = threading.RLock()
MESSAGE_POLL_SECONDS = 5
PROFILE_CHECK_TTL_SECONDS = 6 * 60 * 60
FOLLOWING_CHECK_TTL_SECONDS = 6 * 60 * 60
LIVE_ADS_POLL_SECONDS = max(120, int(os.environ.get("KA_LIVE_ADS_POLL_SECONDS", "300")))
EXTERNAL_AD_STATUS_TTL_SECONDS = max(60, int(os.environ.get("KA_EXTERNAL_AD_STATUS_TTL_SECONDS", "300")))
API_CACHE_DIR = DATA_DIR / "api-cache"
IMAGE_PROXY_DIR = API_CACHE_DIR / "image-previews"
_webpush_lock = threading.RLock()
_message_poll_lock = threading.Lock()
_live_ads_poll_lock = threading.Lock()
_external_ad_status_lock = threading.Lock()
_external_ad_status_refreshing = set()
_external_ad_status_semaphore = threading.BoundedSemaphore(2)
_thread_refresh_lock = threading.Lock()
_thread_refreshing = set()
_profile_check_lock = threading.Lock()
_profile_checks_refreshing = set()
_own_profile_refreshing = set()
_profile_backfill_refreshing = set()
_following_refreshing = set()
_ad_stats_lock = threading.Lock()
_state_lock = threading.RLock()
_cross_platform_terminal_lock = threading.RLock()
_cross_platform_terminal_slugs: set[str] = set()

PRICE_TYPES = [
    ("NEGOTIABLE", "VB"),
    ("FIXED", "Festpreis"),
    ("GIVE_AWAY", "Zu verschenken"),
]
CONDITIONS = ["Neu", "Wie neu", "Gut", "Akzeptabel"]
SHIPPING_TYPES = [
    ("SHIPPING", "Versand möglich"),
    ("PICKUP", "Nur Abholung"),
]

SHIPPING_OPTION_GROUPS = [
    {
        "key": "SMALL",
        "label": "Klein",
        "hint": "z. B. Smartphone, T-Shirt, kleine Teile",
        "options": [
            ("Hermes_Päckchen", "Hermes Päckchen"),
            ("Hermes_S", "Hermes S-Paket"),
            ("DHL_2", "DHL Paket 2 kg"),
        ],
    },
    {
        "key": "MEDIUM",
        "label": "Mittel",
        "hint": "z. B. Schuhe, Spielekonsole, Rauchmelder-Set",
        "options": [
            ("Hermes_M", "Hermes M-Paket"),
            ("DHL_5", "DHL Paket 5 kg"),
        ],
    },
    {
        "key": "LARGE",
        "label": "Groß",
        "hint": "z. B. größere Pakete",
        "options": [
            ("Hermes_L", "Hermes L-Paket"),
            ("DHL_10", "DHL Paket 10 kg"),
            ("DHL_20", "DHL Paket 20 kg"),
            ("DHL_31,5", "DHL Paket 31,5 kg"),
        ],
    },
]

SHIPPING_OPTION_TO_GROUP = {
    code: group["key"]
    for group in SHIPPING_OPTION_GROUPS
    for code, _label in group["options"]
}
DEFAULT_SHIPPING_OPTIONS = ["Hermes_Päckchen", "Hermes_S", "DHL_2"]

# Reine Anzeigehilfe fuer die Web-App. Diese Preise werden NICHT an den Bot
# oder an Kleinanzeigen uebergeben; sie dienen nur als Richtwert beim Bearbeiten.
DEFAULT_SHIPPING_PRICES = {
    "Hermes_Päckchen": "5,19",
    "Hermes_S": "5,79",
    "Hermes_M": "6,99",
    "Hermes_L": "10,99",
    "DHL_2": "6,19",
    "DHL_5": "7,69",
    "DHL_10": "10,49",
    "DHL_20": "18,99",
    "DHL_31,5": "23,99",
}
SHIPPING_PRICE_FIELDS = {
    code: "shipping_price_" + re.sub(r"[^A-Za-z0-9]+", "_", code).strip("_")
    for code in DEFAULT_SHIPPING_PRICES
}

AD_TYPES = [
    ("OFFER", "Angebot"),
    ("WANTED", "Gesuch"),
]
PRESET_CATEGORIES = [
    "Familie, Kind & Baby",
    "Haus & Garten",
    "Auto, Rad & Boot",
    "Elektronik",
    "Mode & Beauty",
]

def _load_or_create_app_secret():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        value = APP_SECRET_FILE.read_text("utf-8").strip()
        if len(value) >= 32:
            return value
    except Exception:
        pass
    value = hashlib.sha256(os.urandom(64)).hexdigest()
    tmp = APP_SECRET_FILE.with_suffix(".tmp")
    tmp.write_text(value, "utf-8")
    os.replace(tmp, APP_SECRET_FILE)
    try:
        os.chmod(APP_SECRET_FILE, 0o600)
    except OSError:
        pass
    return value


app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = _load_or_create_app_secret()
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=3650),
    SESSION_COOKIE_NAME="kleinanzeigen_manager_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# -- Helpers --

def _now():
    return datetime.now(timezone.utc).isoformat()

def _now_local():
    return datetime.now(APP_TZ).strftime("%d.%m.%Y %H:%M")


def _normalize_app_user_email(value):
    return str(value or "").strip().lower()


def _app_user_by_email(email):
    target = _normalize_app_user_email(email)
    for user in APP_USERS.values():
        if _normalize_app_user_email(user.get("email")) == target:
            return dict(user)
    return None


def _current_app_user():
    user_id = str(session.get("app_user_id") or "")
    user = APP_USERS.get(user_id)
    return dict(user) if isinstance(user, dict) else None


def _clean_profile_person_label(value):
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    if not label or label.casefold() in {"primary", "secondary", "person 1", "person 2"}:
        return ""
    return label[:80]


def _person_name_initials(value):
    parts = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", str(value or ""))
    return "".join(part[0] for part in parts if part).upper()


_profile_display_name_lock = threading.Lock()
_profile_display_name_cache = {"labels": {}, "expires_at": 0.0}


def _home_assistant_profile_display_names():
    """Resolve visible household profile names from local Home Assistant only.

    The technical profile keys remain ``primary``/``secondary``. Names are read
    at runtime from local ``person.*`` entities and are never written into the
    repository or update package.
    """
    now = time.monotonic()
    with _profile_display_name_lock:
        cached = dict(_profile_display_name_cache.get("labels") or {})
        if now < float(_profile_display_name_cache.get("expires_at") or 0.0):
            return cached

    labels = {}
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if token:
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://supervisor/core/api/states",
                headers={"Authorization": "Bearer " + token},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            people = []
            for row in payload if isinstance(payload, list) else []:
                if not isinstance(row, dict):
                    continue
                entity_id = str(row.get("entity_id") or "").strip()
                if not entity_id.startswith("person."):
                    continue
                attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
                friendly = _clean_profile_person_label(attributes.get("friendly_name"))
                slug = entity_id.split(".", 1)[1].replace("_", " ").replace("-", " ")
                if not friendly:
                    friendly = _clean_profile_person_label(" ".join(part.capitalize() for part in slug.split()))
                if friendly:
                    people.append({"friendly": friendly, "slug": slug})

            for key in ("primary", "secondary"):
                wanted = re.sub(r"[^A-Za-z]", "", str((APP_USERS.get(key) or {}).get("initials") or "")).upper()
                if not wanted:
                    continue
                ranked = []
                for person in people:
                    friendly = person["friendly"]
                    slug = person["slug"]
                    score = 0
                    if _person_name_initials(friendly) == wanted:
                        score = 100
                    elif _person_name_initials(slug) == wanted:
                        score = 95
                    elif friendly[:1].upper() == wanted[:1]:
                        score = 60
                    elif slug[:1].upper() == wanted[:1]:
                        score = 55
                    if score:
                        visible = _clean_profile_person_label(friendly.split(" ", 1)[0])
                        if visible:
                            ranked.append((score, visible))
                if ranked:
                    best_score = max(score for score, _name in ranked)
                    best = sorted({name for score, name in ranked if score == best_score})
                    if len(best) == 1:
                        labels[key] = best[0]
        except (OSError, ValueError, json.JSONDecodeError):
            labels = {}

    with _profile_display_name_lock:
        _profile_display_name_cache["labels"] = dict(labels)
        _profile_display_name_cache["expires_at"] = now + (300.0 if labels else 30.0)
    return labels


def _app_user_for_display(user):
    if not isinstance(user, dict):
        return None
    result = dict(user)
    user_id = str(result.get("id") or "").strip().casefold()
    if user_id in {"primary", "secondary"}:
        result["name"] = _home_assistant_profile_display_names().get(user_id) or (
            "Person 1" if user_id == "primary" else "Person 2"
        )
    return result


def _app_users_for_display():
    return [row for user in APP_USERS.values() if (row := _app_user_for_display(user)) is not None]


def _load_user_message_state():
    with _user_message_state_lock:
        try:
            data = json.loads(USER_MESSAGE_STATE_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                data.setdefault("version", 1)
                data.setdefault("users", {})
                return data
        except Exception:
            pass
        return {"version": 1, "users": {}}


def _save_user_message_state(data):
    with _user_message_state_lock:
        USER_MESSAGE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = USER_MESSAGE_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, USER_MESSAGE_STATE_FILE)


def _message_read_key(account_id, conversation_id):
    return f"{str(account_id or '')}:{str(conversation_id or '')}"


def _user_has_seen_marker(user_id, account_id, conversation_id, marker):
    marker = str(marker or "")
    if not marker or not user_id:
        return True
    data = _load_user_message_state()
    rec = (data.get("users") or {}).get(str(user_id)) or {}
    seen = rec.get("seen") if isinstance(rec.get("seen"), dict) else {}
    return str(seen.get(_message_read_key(account_id, conversation_id)) or "") == marker


def _mark_user_message_read(user_id, account_id, conversation_id, marker):
    marker = str(marker or "")
    if not user_id or not marker:
        return False
    with _user_message_state_lock:
        data = _load_user_message_state()
        users = data.setdefault("users", {})
        rec = users.setdefault(str(user_id), {"seen": {}, "initialized": True})
        seen = rec.setdefault("seen", {})
        key = _message_read_key(account_id, conversation_id)
        changed = str(seen.get(key) or "") != marker
        seen[key] = marker
        rec["initialized"] = True
        rec["updated_at"] = _now()
        if changed:
            _save_user_message_state(data)
        return changed


def _mark_all_user_messages_read(user_id):
    """Mark all currently cached incoming conversations as read for one profile."""
    user_id = str(user_id or "").strip()
    if not user_id:
        return 0
    state = _load_state()
    current = []
    for account_id in _accounts_from_state(state):
        cache = _read_api_cache("messages", account_id)
        for raw in cache.get("items", []) or []:
            conversation = dict(raw or {})
            conversation_id = str(conversation.get("id") or "").strip()
            marker = _message_incoming_marker(account_id, conversation_id, state).get("marker", "")
            if conversation_id and marker:
                current.append((_message_read_key(account_id, conversation_id), str(marker)))
    if not current:
        return 0

    _ensure_user_message_baseline(user_id, [])
    with _user_message_state_lock:
        data = _load_user_message_state()
        users = data.setdefault("users", {})
        rec = users.setdefault(user_id, {"seen": {}, "initialized": True})
        seen = rec.setdefault("seen", {})
        marked = 0
        for key, marker in current:
            if str(seen.get(key) or "") == marker:
                continue
            seen[key] = marker
            marked += 1
        if marked:
            rec["initialized"] = True
            rec["updated_at"] = _now()
            _save_user_message_state(data)
        return marked


def _ensure_user_message_baseline(user_id, conversations):
    """Einmalige gemeinsame Ausgangsbasis für primary und secondary.

    Beim Umstieg auf 1.6.0 werden bereits plattformseitig gelesene Marker für
    beide Profile identisch als gelesen übernommen. Aktuell ungelesene Marker
    bleiben für beide neu. Die Ausgangsbasis wird einmal gespeichert, damit ein
    späterer erster Login des zweiten Profils nicht davon abhängt, was das erste
    Profil inzwischen geöffnet hat.
    """
    if not user_id:
        return
    with _user_message_state_lock:
        data = _load_user_message_state()
        users = data.setdefault("users", {})
        rec = users.setdefault(str(user_id), {"seen": {}})
        if rec.get("initialized"):
            return

        baseline = data.get("initial_baseline_seen")
        if not isinstance(baseline, dict):
            baseline = {}
            state = _load_state()
            baseline_rows = []
            for account_id in _accounts_from_state(state):
                cache = _read_api_cache("messages", account_id)
                for raw in cache.get("items", []) or []:
                    c = dict(raw or {})
                    c["account_id"] = c.get("account_id") or account_id
                    marker = _message_incoming_marker(account_id, c.get("id"), state)
                    c["incoming_marker"] = marker.get("marker", "")
                    baseline_rows.append(c)
            if not baseline_rows:
                baseline_rows = [dict(c or {}) for c in (conversations or [])]
            for conv in baseline_rows:
                marker = str((conv or {}).get("incoming_marker") or "")
                if not marker:
                    continue
                try:
                    platform_unread = bool((conv or {}).get("platform_unread", (conv or {}).get("unread"))) or int((conv or {}).get("platform_unread_count", (conv or {}).get("unread_count") or 0) or 0) > 0
                except Exception:
                    platform_unread = bool((conv or {}).get("platform_unread", (conv or {}).get("unread")))
                if not platform_unread:
                    baseline[_message_read_key((conv or {}).get("account_id"), (conv or {}).get("id"))] = marker
            data["initial_baseline_seen"] = dict(baseline)
            data["baseline_created_at"] = _now()

        rec["seen"] = dict(baseline)
        rec["initialized"] = True
        rec["initialized_at"] = _now()
        _save_user_message_state(data)

def _decorate_profile_unread(conversations, user_id=None):
    user_id = user_id or ((_current_app_user() or {}).get("id"))
    rows = [dict(c or {}) for c in (conversations or [])]
    for c in rows:
        c["platform_unread"] = bool(c.get("platform_unread", c.get("unread")))
        c["platform_unread_count"] = int(c.get("platform_unread_count", c.get("unread_count") or 0) or 0)
    _ensure_user_message_baseline(user_id, rows)
    for c in rows:
        marker = str(c.get("incoming_marker") or "")
        profile_unread = bool(marker and not _user_has_seen_marker(user_id, c.get("account_id"), c.get("id"), marker))
        c["unread"] = profile_unread
        c["unread_count"] = 1 if profile_unread else 0
    return rows


def _today_local_date():
    return datetime.now(APP_TZ).date().isoformat()


def _local_datetime():
    return datetime.now(APP_TZ)


def _iso_to_local_date(iso_date):
    dt = _iso_dt(iso_date)
    if not dt:
        return ""
    return dt.astimezone(APP_TZ).date().isoformat()

def _slug(title):
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:60] or "anzeige"

def _age_days(iso_date):
    try:
        dt = datetime.fromisoformat(iso_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0


def _file_mtime_iso(path):
    try:
        ts = Path(path).stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _oldest_asset_mtime_iso(slug):
    candidates = []
    try:
        yaml_path = _ad_yaml_path(slug)
        if yaml_path.exists():
            candidates.append(yaml_path.stat().st_mtime)
    except Exception:
        pass
    try:
        img_dir = _ad_images_dir(slug)
        if img_dir.is_dir():
            for child in img_dir.iterdir():
                if child.is_file():
                    candidates.append(child.stat().st_mtime)
    except Exception:
        pass
    if not candidates:
        return None
    try:
        return datetime.fromtimestamp(min(candidates), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _age_reference_iso(slug, ad_data, meta):
    return (
        meta.get("last_published")
        or ad_data.get("created_on_kleinanzeigen")
        or meta.get("created_at")
        or ad_data.get("updated_at")
        or ad_data.get("created_at")
        or _oldest_asset_mtime_iso(slug)
        or _file_mtime_iso(_ad_yaml_path(slug))
    )


def _iso_dt(iso_date):
    try:
        dt = datetime.fromisoformat(iso_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _local_tz():
    return APP_TZ


def _parse_schedule_form(form):
    date_raw = (form.get("publish_date") or "").strip()
    time_raw = (form.get("publish_time") or "").strip()
    if not date_raw and not time_raw:
        return None
    if date_raw and not time_raw:
        time_raw = "09:00"
    if time_raw and not date_raw:
        return None
    try:
        dt = datetime.strptime(f"{date_raw} {time_raw}", "%Y-%m-%d %H:%M")
        local_dt = dt.replace(tzinfo=_local_tz())
        return local_dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _split_schedule_form_value(iso_date):
    dt = _iso_dt(iso_date)
    if not dt:
        return {"date": "", "time": ""}
    local_dt = dt.astimezone(_local_tz())
    return {"date": local_dt.strftime("%Y-%m-%d"), "time": local_dt.strftime("%H:%M")}


def _scheduled_label(iso_date):
    dt = _iso_dt(iso_date)
    if not dt:
        return ""
    return dt.astimezone(_local_tz()).strftime("%d.%m.%Y %H:%M")

# -- Backups --

def _human_size(num):
    size = float(num)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024 or unit == 'GB':
            return f"{size:.0f} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024


def _backup_timestamp():
    return datetime.now().strftime('%Y-%m-%d_%H-%M-%S')


def _backup_state():
    return _load_state().get('backup', {})

def _prune_old_backups(days=BACKUP_RETENTION_DAYS):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - (days * 86400)
    removed = []
    for p in sorted(BACKUP_DIR.glob('*.zip')):
        try:
            if p.stat().st_mtime < cutoff:
                removed.append(p.name)
                p.unlink(missing_ok=True)
        except Exception:
            pass
    return removed


def _record_backup(path, reason, is_daily=False):
    state = _load_state()
    backup_state = state.setdefault('backup', {})
    now_iso = _now()
    backup_state['last_backup'] = {
        'file': path.name,
        'reason': reason,
        'created_at': now_iso,
    }
    if is_daily:
        backup_state['last_daily_backup'] = {
            'file': path.name,
            'created_at': now_iso,
            'date': datetime.now().strftime('%Y-%m-%d'),
        }
    _save_state(state)


def _create_backup(reason='manuell', slug=None, is_daily=False):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_backups()
    reason_slug = _slug(reason)[:40] or 'backup'
    suffix = f'-{_slug(slug)[:30]}' if slug else ''
    backup_path = BACKUP_DIR / f"{_backup_timestamp()}_{reason_slug}{suffix}.zip"
    manifest = {
        'created_at': _now(),
        'reason': reason,
        'slug': slug,
        'data_dir': str(DATA_DIR),
    }
    files = [BOT_CONFIG, APP_STATE]
    with zipfile.ZipFile(backup_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.exists():
                zf.write(f, arcname=f'data/{f.name}')
        # Zusätzliche Account-Configs + kleine API-Token mitsichern; Chromium-Profile bewusst nicht aufblasen.
        main_api_token = _account_api_token_path(MAIN_ACCOUNT_ID)
        if main_api_token.exists():
            zf.write(main_api_token, arcname='data/.kleinanzeigen_api/token.json')
        if ACCOUNTS_DIR.exists():
            for cfg_path in sorted(ACCOUNTS_DIR.glob('*/bot-config.yaml')):
                zf.write(cfg_path, arcname=f'data/accounts/{cfg_path.parent.name}/bot-config.yaml')
            for token_path in sorted(ACCOUNTS_DIR.glob('*/.kleinanzeigen_api/token.json')):
                zf.write(token_path, arcname=f'data/accounts/{token_path.parent.parent.name}/.kleinanzeigen_api/token.json')
        for extra in (WEBPUSH_SUBSCRIPTIONS, WEBPUSH_PRIVATE_KEY, APP_SECRET_FILE, USER_MESSAGE_STATE_FILE):
            if extra.exists():
                zf.write(extra, arcname=f'data/{extra.name}')
        for folder_name, folder in [('ads', ADS_DIR), ('images', IMAGES_DIR), ('logs', LOGS_DIR)]:
            if folder.exists():
                for p in sorted(folder.rglob('*')):
                    if p.is_file():
                        zf.write(p, arcname=f'data/{folder_name}/{p.relative_to(folder).as_posix()}')
        zf.writestr('backup-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    _record_backup(backup_path, reason, is_daily=is_daily)
    return backup_path



def _restore_backup_file(filename):
    safe_name = Path(filename).name
    backup_path = BACKUP_DIR / safe_name
    if not backup_path.exists():
        raise FileNotFoundError('Backup nicht gefunden')

    _create_backup(reason='vor-wiederherstellung')

    tmp_dir = Path(tempfile.mkdtemp(prefix='ka_restore_'))
    try:
        with zipfile.ZipFile(backup_path, 'r') as zf:
            zf.extractall(tmp_dir)

        data_root = tmp_dir / 'data'
        if not data_root.exists():
            raise RuntimeError('Ungueltiges Backup: data-Ordner fehlt')

        for single in ['bot-config.yaml', 'app-state.json', 'webpush-subscriptions.json', 'webpush-vapid-private.pem', 'app-secret.key', 'user-message-state.json']:
            src_file = data_root / single
            if src_file.exists():
                shutil.copy2(src_file, DATA_DIR / single)
        main_api_src = data_root / '.kleinanzeigen_api' / 'token.json'
        if main_api_src.exists():
            main_api_dst = _account_api_token_path(MAIN_ACCOUNT_ID)
            main_api_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(main_api_src, main_api_dst)

        for folder_name in ['ads', 'images', 'logs']:
            src_folder = data_root / folder_name
            dst_folder = DATA_DIR / folder_name
            if src_folder.exists():
                if dst_folder.exists():
                    shutil.rmtree(dst_folder)
                shutil.copytree(src_folder, dst_folder)
            else:
                dst_folder.mkdir(parents=True, exist_ok=True)
        src_accounts = data_root / 'accounts'
        if src_accounts.exists():
            for cfg_path in src_accounts.glob('*/bot-config.yaml'):
                target = ACCOUNTS_DIR / cfg_path.parent.name / 'bot-config.yaml'
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cfg_path, target)
            for token_path in src_accounts.glob('*/.kleinanzeigen_api/token.json'):
                target = ACCOUNTS_DIR / token_path.parent.parent.name / '.kleinanzeigen_api' / 'token.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(token_path, target)
        _migrate_accounts()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _ensure_daily_backup():
    state = _load_state()
    backup_state = state.get('backup', {})
    today = datetime.now().strftime('%Y-%m-%d')
    last_daily = (backup_state.get('last_daily_backup') or {}).get('date')
    if last_daily == today:
        return None
    return _create_backup(reason='taegliches-backup', is_daily=True)


def _list_backups(limit=30):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_backups()
    items = []
    for p in sorted(BACKUP_DIR.glob('*.zip'), reverse=True)[:limit]:
        stat = p.stat()
        try:
            created_label = datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
        except Exception:
            created_label = '—'
        items.append({
            'name': p.name,
            'size_label': _human_size(stat.st_size),
            'created_label': created_label,
        })
    return items


def _backup_overview():
    info = _backup_state()
    last_backup = info.get('last_backup') or {}
    last_daily = info.get('last_daily_backup') or {}
    return {
        'path': str(BACKUP_DIR),
        'count': len(list(BACKUP_DIR.glob('*.zip'))) if BACKUP_DIR.exists() else 0,
        'last_backup_label': datefmt_filter(last_backup.get('created_at')) if last_backup.get('created_at') else 'Noch nicht erstellt',
        'last_daily_label': datefmt_filter(last_daily.get('created_at')) if last_daily.get('created_at') else 'Noch nicht erstellt',
        'last_backup_file': last_backup.get('file', ''),
        'last_daily_file': last_daily.get('file', ''),
    }

# -- App State --

def _load_state():
    with _state_lock:
        if APP_STATE.exists():
            return json.loads(APP_STATE.read_text("utf-8"))
        return {"ads": {}}

def _save_state(state):
    with _state_lock:
        APP_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = APP_STATE.with_suffix(APP_STATE.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, APP_STATE)

def _save_message_monitor_only(message_monitor):
    """Monitorstatus aktualisieren, ohne parallel geänderte Anzeigenmetadaten zurückzuschreiben."""
    with _state_lock:
        latest = json.loads(APP_STATE.read_text("utf-8")) if APP_STATE.exists() else {"ads": {}}
        # Profilprüfungen laufen bewusst in Hintergrund-Threads. Falls ein
        # Nachrichtenpoll währenddessen endet, dürfen dessen ältere lokalen
        # Daten das gerade ermittelte Profil-Ergebnis nicht wieder entfernen.
        latest_monitor = latest.get("message_monitor") if isinstance(latest.get("message_monitor"), dict) else {}
        latest_accounts = latest_monitor.get("accounts") if isinstance(latest_monitor.get("accounts"), dict) else {}
        monitor_accounts = message_monitor.setdefault("accounts", {}) if isinstance(message_monitor, dict) else {}
        for account_id, latest_rec in latest_accounts.items():
            if not isinstance(latest_rec, dict):
                continue
            rec = monitor_accounts.setdefault(account_id, {})
            if not isinstance(rec, dict):
                rec = {}
                monitor_accounts[account_id] = rec
            if isinstance(latest_rec.get("profile_checks"), dict):
                checks = rec.setdefault("profile_checks", {})
                if not isinstance(checks, dict):
                    checks = {}
                    rec["profile_checks"] = checks
                for conversation_id, latest_check in latest_rec["profile_checks"].items():
                    current = checks.get(conversation_id)
                    if (not isinstance(current, dict) or
                            str(latest_check.get("checked_at") or "") >= str(current.get("checked_at") or "")):
                        checks[conversation_id] = copy.deepcopy(latest_check)
            if "own_profile" in latest_rec:
                current = rec.get("own_profile")
                latest_own = latest_rec.get("own_profile")
                if (not isinstance(current, dict) or not isinstance(latest_own, dict) or
                        str(latest_own.get("checked_at") or "") >= str(current.get("checked_at") or "")):
                    rec["own_profile"] = copy.deepcopy(latest_own)
        latest["message_monitor"] = copy.deepcopy(message_monitor or {})
        tmp = APP_STATE.with_suffix(APP_STATE.suffix + ".tmp")
        tmp.write_text(json.dumps(latest, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, APP_STATE)


def _safe_account_id(value):
    value = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return value[:50] or "konto"


def _account_workspace(account_id):
    account_id = str(account_id or MAIN_ACCOUNT_ID)
    return DATA_DIR if account_id == MAIN_ACCOUNT_ID else ACCOUNTS_DIR / account_id


def _account_config_path(account_id):
    account_id = str(account_id or MAIN_ACCOUNT_ID)
    return BOT_CONFIG if account_id == MAIN_ACCOUNT_ID else _account_workspace(account_id) / "bot-config.yaml"


def _account_profile_dir(account_id):
    return _account_workspace(account_id) / ".temp" / "browser-profile"


def _accounts_from_state(state=None):
    state = state if state is not None else _load_state()
    accounts = state.get("accounts") if isinstance(state.get("accounts"), dict) else {}
    return accounts


def _account_record(account_id, state=None):
    accounts = _accounts_from_state(state)
    return accounts.get(str(account_id or MAIN_ACCOUNT_ID)) or accounts.get(MAIN_ACCOUNT_ID) or {
        "id": MAIN_ACCOUNT_ID,
        "name": MAIN_ACCOUNT_NAME,
        "is_main": True,
    }


def _account_name(account_id, state=None):
    rec = _account_record(account_id, state)
    return str(rec.get("name") or MAIN_ACCOUNT_NAME if str(account_id or MAIN_ACCOUNT_ID) == MAIN_ACCOUNT_ID else rec.get("name") or account_id)


def _valid_account_id(account_id, state=None):
    account_id = str(account_id or MAIN_ACCOUNT_ID)
    return account_id if account_id in _accounts_from_state(state) else MAIN_ACCOUNT_ID


def _ad_account_id(slug, meta=None, state=None):
    state = state if state is not None else _load_state()
    if meta is None:
        meta = state.get("ads", {}).get(slug, {})
    return _valid_account_id(meta.get("account_id") or MAIN_ACCOUNT_ID, state)


def _load_account_config(account_id):
    path = _account_config_path(account_id)
    if path.exists():
        try:
            return yaml.safe_load(path.read_text("utf-8")) or {}
        except Exception:
            return {}
    return {}


def _save_account_config(account_id, cfg):
    path = _account_config_path(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")


def _account_login(account_id):
    cfg = _load_account_config(account_id)
    login = cfg.get("login") if isinstance(cfg.get("login"), dict) else {}
    return {
        "email": str(login.get("username") or ""),
        "password": str(login.get("password") or ""),
        "configured": bool(login.get("username")),
    }


def _account_ui_records(state=None):
    state = state if state is not None else _load_state()
    records = []
    accounts = _accounts_from_state(state)
    ordered = sorted(accounts.values(), key=lambda a: (0 if a.get("is_main") else 1, str(a.get("name") or "").lower()))
    for rec in ordered:
        account_id = str(rec.get("id") or MAIN_ACCOUNT_ID)
        login = _account_login(account_id)
        activity = _get_account_activity(account_id, state)
        records.append({
            "id": account_id,
            "name": str(rec.get("name") or account_id),
            "is_main": bool(rec.get("is_main")),
            "email": login["email"],
            "password_saved": bool(login["password"]),
            "configured": login["configured"],
            "activity": activity,
            "profile_dir": str(_account_profile_dir(account_id)),
            "api": _api_account_status(account_id),
        })
    return records


def _account_select_records(state=None):
    """Nur ID/Name für Filter und Selects – ohne Login/API-Initialisierung."""
    state = state if state is not None else _load_state()
    accounts = _accounts_from_state(state)
    ordered = sorted(accounts.values(), key=lambda a: (0 if a.get("is_main") else 1, str(a.get("name") or "").lower()))
    return [
        {
            "id": str(rec.get("id") or MAIN_ACCOUNT_ID),
            "name": str(rec.get("name") or rec.get("id") or MAIN_ACCOUNT_ID),
            "is_main": bool(rec.get("is_main")),
        }
        for rec in ordered
    ]


def _migrate_accounts():
    """Konten verlustfrei migrieren; IDs, Logins und Browserprofile bleiben unverändert."""
    state = _load_state()
    changed = False
    accounts = state.get("accounts") if isinstance(state.get("accounts"), dict) else None
    if not accounts:
        accounts = {
            MAIN_ACCOUNT_ID: {
                "id": MAIN_ACCOUNT_ID,
                "name": MAIN_ACCOUNT_NAME,
                "is_main": True,
                "created_at": _now(),
            }
        }
        state["accounts"] = accounts
        changed = True
    else:
        main = accounts.setdefault(MAIN_ACCOUNT_ID, {"id": MAIN_ACCOUNT_ID, "is_main": True})
        # Alte Bezeichnung nur als Anzeige-Name migrieren. Zugangsdaten, Cookies,
        # Profilpfad und Account-ID werden dabei bewusst nicht angefasst.
        if not main.get("name") or str(main.get("name")).strip() == "Neuhaus Hauptkonto":
            main["name"] = MAIN_ACCOUNT_NAME
            changed = True
        if not main.get("is_main"):
            main["is_main"] = True
            changed = True
        others = [a for aid, a in accounts.items() if aid != MAIN_ACCOUNT_ID and isinstance(a, dict)]
        if len(others) == 1 and str(others[0].get("name") or "").strip() != "Zweitkonto":
            others[0]["name"] = "Zweitkonto"
            changed = True

    legacy_activity = state.get("account_activity")
    by_account = state.setdefault("account_activity_by_account", {})
    if MAIN_ACCOUNT_ID not in by_account and isinstance(legacy_activity, dict) and legacy_activity:
        by_account[MAIN_ACCOUNT_ID] = legacy_activity
        changed = True

    for slug, meta in state.setdefault("ads", {}).items():
        if not isinstance(meta, dict):
            continue
        if not meta.get("account_id") or meta.get("account_id") not in accounts:
            meta["account_id"] = MAIN_ACCOUNT_ID
            changed = True

    if changed:
        _save_state(state)
    return state


def _create_account(name, email, password):
    state = _load_state()
    accounts = state.setdefault("accounts", {})
    base = _safe_account_id(name)
    account_id = base
    suffix = 2
    while account_id in accounts or account_id == MAIN_ACCOUNT_ID:
        account_id = f"{base}-{suffix}"
        suffix += 1
    accounts[account_id] = {
        "id": account_id,
        "name": str(name or account_id).strip(),
        "is_main": False,
        "created_at": _now(),
    }
    _save_state(state)
    _write_account_login_and_defaults(account_id, email, password, preserve_password=False)
    return account_id


def _write_account_login_and_defaults(account_id, email, password, preserve_password=True):
    account_id = _valid_account_id(account_id)
    cfg = _load_account_config(account_id)
    if not cfg and account_id != MAIN_ACCOUNT_ID:
        cfg = copy.deepcopy(_load_bot_config())
    login = cfg.setdefault("login", {})
    old_password = str(login.get("password") or "")
    login["username"] = str(email or "").strip()
    login["password"] = old_password if preserve_password and not str(password or "").strip() else str(password or "").strip()
    browser = cfg.setdefault("browser", {})
    browser.setdefault("binary_location", os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser"))
    browser.setdefault("arguments", [
        "--no-sandbox", "--headless=new", "--disable-gpu", "--disable-dev-shm-usage",
        "--disable-software-rasterizer", "--window-size=1280,1024",
    ])
    browser["use_private_window"] = False
    # Expliziter Profilpfad: Hauptkonto bleibt exakt am bisherigen Ort.
    browser["user_data_dir"] = str(_account_profile_dir(account_id))
    cfg["ad_files"] = [str(ADS_DIR / "*.yaml")] if account_id != MAIN_ACCOUNT_ID else cfg.get("ad_files") or ["ads/*.yaml"]
    _save_account_config(account_id, cfg)


def _update_account_name(account_id, name):
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    rec = state.setdefault("accounts", {}).setdefault(account_id, {"id": account_id})
    rec["name"] = str(name or rec.get("name") or account_id).strip()
    _save_state(state)


def _reset_ad_for_manual_account_move(slug, meta, new_account_id):
    """Nur lokalen Status zurücksetzen. Es wird bewusst NICHT bei Kleinanzeigen gelöscht."""
    ad = _read_ad_yaml(slug) or {}
    for key in ("id", "created_on_kleinanzeigen", "updated_at", "created_at"):
        ad.pop(key, None)
    _write_yaml_file(_ad_yaml_path(slug), ad)
    meta["account_id"] = new_account_id
    meta["last_published"] = None
    meta["scheduled_publish_at"] = None
    meta.pop("republish_postponed_until", None)
    meta.pop("price_reduction_anchor_at", None)
    meta.setdefault("history", []).append({
        "action": f"Konto auf {_account_name(new_account_id)} geändert; extern bereits manuell gelöscht; für Neuveröffentlichung vorbereitet",
        "date": _now(),
    })

def _get_account_activity(account_id=MAIN_ACCOUNT_ID, state=None):
    state = state if state is not None else _load_state()
    account_id = _valid_account_id(account_id, state)
    by_account = state.get("account_activity_by_account") if isinstance(state.get("account_activity_by_account"), dict) else {}
    if account_id in by_account:
        return by_account.get(account_id) or {}
    if account_id == MAIN_ACCOUNT_ID:
        return state.get("account_activity", {}) if isinstance(state.get("account_activity"), dict) else {}
    return {}


def _save_account_activity(data, account_id=MAIN_ACCOUNT_ID):
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    state.setdefault("account_activity_by_account", {})[account_id] = data
    if account_id == MAIN_ACCOUNT_ID:
        state["account_activity"] = data
    _save_state(state)


def _activity_updated_today(activity=None, account_id=MAIN_ACCOUNT_ID, state=None):
    activity = activity if activity is not None else _get_account_activity(account_id, state)
    return _iso_to_local_date(activity.get("updated_at")) == _today_local_date()


def _posted_last_30_count(activity=None, account_id=MAIN_ACCOUNT_ID, state=None):
    activity = activity if activity is not None else _get_account_activity(account_id, state)
    try:
        return int(activity.get("posted_last_30_days"))
    except Exception:
        return None


def _refresh_account_activity_until_today(account_id=MAIN_ACCOUNT_ID, max_attempts=4, delay_seconds=2):
    last_msg = ""
    account_id = _valid_account_id(account_id)
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        ok, result = _fetch_account_activity(account_id)
        if ok:
            _save_account_activity(result, account_id)
            if _activity_updated_today(result, account_id):
                return True, f"Aktivitaet aktualisiert. Versuch {attempt}.", result
            last_msg = "Aktivitaet gelesen, aber kein heutiger Stand erkannt."
        else:
            last_msg = str(result)
        if attempt < max_attempts:
            time.sleep(max(0, delay_seconds))
    return False, last_msg or "Aktivitaet konnte nicht aktualisiert werden.", _get_account_activity(account_id)


def _auto_activity_refresh_due():
    """Nach 00:30 Uhr jedes Konto aktualisieren, bis der heutige Stand gespeichert ist."""
    if _last_log.get("running") or _bot_lock.locked() or _vnc_running():
        return
    now_local = _local_datetime()
    today = now_local.date().isoformat()
    if (now_local.hour, now_local.minute) < (ACTIVITY_AUTO_REFRESH_HOUR, ACTIVITY_AUTO_REFRESH_MINUTE):
        return

    state = _load_state()
    accounts = _accounts_from_state(state)
    auto_root = state.setdefault("activity_auto_refresh_by_account", {})
    changed = False
    for account_id in accounts:
        if not _account_login(account_id).get("configured"):
            continue
        auto_state = auto_root.setdefault(account_id, {})
        activity = _get_account_activity(account_id, state)
        if auto_state.get("success_date") == today and _activity_updated_today(activity, account_id, state):
            continue
        last_attempt_dt = _iso_dt(auto_state.get("last_attempt_at"))
        if last_attempt_dt and (datetime.now(timezone.utc) - last_attempt_dt).total_seconds() < ACTIVITY_RETRY_SECONDS:
            continue
        auto_state["last_attempt_at"] = _now()
        ok, result = _fetch_account_activity(account_id)
        if ok:
            state.setdefault("account_activity_by_account", {})[account_id] = result
            if account_id == MAIN_ACCOUNT_ID:
                state["account_activity"] = result
            if _activity_updated_today(result, account_id, state):
                auto_state["success_date"] = today
                auto_state["last_error"] = ""
            else:
                auto_state["last_error"] = "Kein heutiger Stand erkannt."
        else:
            auto_state["last_error"] = str(result)
        changed = True
    if changed:
        _save_state(state)

def _ha_services():
    """Liest die aktuell registrierten Home-Assistant-Dienste."""
    import urllib.request
    import json as _json

    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt")

    req = urllib.request.Request(
        "http://supervisor/core/api/services",
        headers={"Authorization": "Bearer " + token},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def _available_mobile_notify_services():
    """Gibt alle registrierten notify.mobile_app_* Dienste zurück."""
    services = _ha_services()
    result = []

    for domain_entry in services if isinstance(services, list) else []:
        if str(domain_entry.get("domain") or "") != "notify":
            continue
        raw_services = domain_entry.get("services") or {}
        if isinstance(raw_services, dict):
            service_names = raw_services.keys()
        elif isinstance(raw_services, (list, tuple, set)):
            service_names = raw_services
        else:
            service_names = []
        for service_name in service_names:
            name = str(service_name)
            if name.startswith("mobile_app_"):
                result.append("notify." + name)

    return sorted(set(result))


def _primary_notify_candidates():
    """Genau ein Ziel fuer Systemhinweise, niemals ein Broadcast-Fallback."""
    configured = (primary_NOTIFY_SERVICE or "").strip()
    if not configured.startswith("notify."):
        configured = "notify." + configured
    # Ein alter Eintrag mit notify.notify darf Systemmeldungen nicht wieder an
    # alle Geräte verteilen. Dann gilt wieder das feste iPhone-Ziel.
    if not configured.startswith("notify.mobile_app_"):
        configured = "notify.mobile_app_iphone A"
    return [configured], []


def _call_notify_service(service, title, message, click_url="", image_url="", silent=False, critical=False):
    """Sendet einen normalen Home-Assistant-Push."""
    import urllib.request
    import json as _json

    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return False, "SUPERVISOR_TOKEN fehlt"

    service = str(service or "").strip()
    if not service:
        return False, "Leerer Notify-Service"
    if not service.startswith("notify."):
        service = "notify." + service

    url = "http://supervisor/core/api/services/" + service.replace(".", "/")
    # Normale Companion-App-Benachrichtigung: kein Critical-Flag und keine
    # erzwungene Push-Prioritaet. Ohne Sonderoption nutzt das Geraet seinen
    # normalen Benachrichtigungston und die normalen Fokus-/Lautstaerkeregeln.
    notify_data = {}
    if silent:
        # Sichtbare, aber tonlose iOS/Companion-Benachrichtigung. Kein Critical-Flag.
        notify_data["push"] = {"sound": "none"}
    elif critical:
        notify_data["push"] = {"sound": {"name": "default", "critical": 1, "volume": 0.0}}
    if click_url:
        # iOS nutzt url, Android clickAction. Beides setzen, damit ein Tipp
        # direkt den Kleinanzeigen-Manager öffnet.
        notify_data["url"] = click_url
        notify_data["clickAction"] = click_url
    if image_url:
        # Home Assistant Companion: Bild als Notification-Anhang. iOS entscheidet
        # selbst, ob es direkt in der kompakten oder erst erweiterten Ansicht erscheint.
        notify_data["image"] = image_url
        notify_data["attachment"] = {"url": image_url, "hide-thumbnail": False}
    payload = _json.dumps({
        "title": title,
        "message": message,
        "data": notify_data,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
            return ok, f"{service} · HTTP {resp.status}"
    except Exception as exc:
        return False, f"{service} · {exc}"


def _notify_primary_only_silent(title, message, click_url=""):
    """Nur primarys iPhone benachrichtigen; bewusst ohne Ton und ohne Broadcast."""
    try:
        service = _primary_notify_candidates()[0][0]
        ok, detail = _call_notify_service(service, title, message, click_url=click_url, silent=True)
        print(f"[notify-silent-primary] {detail}", flush=True)
        return ok, detail
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        print(f"[notify-silent-primary] {detail}", flush=True)
        return False, detail


def _notify_primary(title, message, click_url="", image_url=""):
    """Systemhinweise ausschließlich an primarys iPhone senden."""
    try:
        service = _primary_notify_candidates()[0][0]
        ok, status = _call_notify_service(service, title, message, click_url=click_url, image_url=image_url)
        print(f"[notify-primary] {status}", flush=True)
        return ok, status
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        print(f"[notify-primary] Ausnahme: {detail}", flush=True)
        return False, detail


def _notify_primary_critical(title, message, click_url=""):
    """Critical but silent iPhone alert for an explicit cross-platform delete."""
    try:
        service = _primary_notify_candidates()[0][0]
        ok, status = _call_notify_service(service, title, message, click_url=click_url, critical=True)
        print(f"[notify-critical-primary] {status}", flush=True)
        return ok, status
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        print(f"[notify-critical-primary] Ausnahme: {detail}", flush=True)
        return False, detail


def _notify_message_broadcast(title, message, click_url="", image_url=""):
    """Nur tatsächlich eingehende Kleinanzeigen-Nachrichten an alle Geräte."""
    try:
        ok, status = _call_notify_service(
            MESSAGE_NOTIFY_SERVICE, title, message,
            click_url=click_url, image_url=image_url,
        )
        print(f"[notify-message-broadcast] {status}", flush=True)
        return ok, status
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        print(f"[notify-message-broadcast] Ausnahme: {detail}", flush=True)
        return False, detail

def _activity_age_seconds(activity):
    """Alter eines gespeicherten Aktivitätsstands in Sekunden oder None."""
    try:
        updated = _iso_dt((activity or {}).get("updated_at"))
        if not updated:
            return None
        return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())
    except Exception:
        return None


def _ensure_publish_capacity(account_id=MAIN_ACCOUNT_ID, state=None):
    """Vor JEDEM Publish prüfen, ohne den Bot durch einen Mitternachts-Browsercheck zu blockieren.

    Ein erst wenige Stunden alter 30-Tage-Stand ist rund um Mitternacht weiterhin ein
    sicherer Ausgangspunkt: Veröffentlichungen des Managers werden lokal sofort
    hochgezählt, während aus dem 30-Tage-Fenster höchstens ältere Anzeigen herausfallen.
    Ein Browser-Refresh darf deshalb nicht mehr zwingend zwischen Klick und Bot-Start
    stehen. Bei älteren Daten wird weiterhin aktualisiert; schlägt das Lesen fehl, darf
    ein höchstens 36 Stunden alter gespeicherter Stand als konservativer Fallback dienen.
    """
    state = state if state is not None else _load_state()
    account_id = _valid_account_id(account_id, state)
    if not _account_login(account_id).get("configured"):
        return False, None, f"Konto '{_account_name(account_id, state)}' ist noch nicht eingerichtet."

    activity = _get_account_activity(account_id, state)
    cached_count = _posted_last_30_count(activity, account_id, state)
    age = _activity_age_seconds(activity)

    # Bis 6 Stunden: keinen synchronen Selenium-Lauf vor den Publish schieben.
    # Der tägliche Hintergrund-Refresh aktualisiert den Stand separat.
    if cached_count is not None and age is not None and age <= 6 * 3600:
        count = cached_count
    else:
        ok, result = _fetch_account_activity(account_id)
        if ok:
            activity = result
            state.setdefault("account_activity_by_account", {})[account_id] = activity
            if account_id == MAIN_ACCOUNT_ID:
                state["account_activity"] = activity
            _save_state(state)
            count = _posted_last_30_count(activity, account_id, state)
        elif cached_count is not None and age is not None and age <= 36 * 3600:
            # Fallback ist bewusst konservativ: Manager-Publishes wurden lokal bereits
            # addiert; durch das Weiterrollen des 30-Tage-Fensters kann der echte Wert
            # eher sinken. So verhindert ein temporärer Selenium-/Chromiumfehler nicht
            # kommentarlos jede Veröffentlichung.
            count = cached_count
            print(
                f"[activity] Aktualisierung für {account_id} vor Publish fehlgeschlagen; "
                f"verwende gespeicherten Stand {count}/{REPOST_LIMIT_LAST_30_DAYS} "
                f"({int(age // 60)} Min. alt): {result}",
                flush=True,
            )
        else:
            return False, None, (
                f"Aktivitaet von '{_account_name(account_id, state)}' konnte nicht aktuell gelesen werden. "
                "Bitte Aktivitätsstand in den Einstellungen aktualisieren."
            )

    if count is None:
        return False, None, f"30-Tage-Anzeigenzahl von '{_account_name(account_id, state)}' nicht erkannt."
    if count >= REPOST_LIMIT_LAST_30_DAYS:
        return False, count, f"Limit erreicht: {count}/{REPOST_LIMIT_LAST_30_DAYS} bei '{_account_name(account_id, state)}'."
    return True, count, f"{count}/{REPOST_LIMIT_LAST_30_DAYS} bei '{_account_name(account_id, state)}'"


def _capacity_failure_kind(ok, count, message):
    """Classify capacity checks so technical failures are never postponed by 24h.

    Only a confirmed numeric 30-day limit is a real day-level block. Temporary
    activity/browser read failures are short retries; configuration problems stay
    terminal and must not loop every minute forever.
    """
    if ok:
        return "ok"
    try:
        if count is not None and int(count) >= REPOST_LIMIT_LAST_30_DAYS:
            return "limit"
    except Exception:
        pass
    text = str(message or "").lower()
    transient_markers = (
        "konnte nicht aktuell gelesen werden",
        "30-tage-anzeigenzahl",
        "nicht erkannt",
        "aktivitätsstand",
        "aktivitaetsstand",
    )
    if any(marker in text for marker in transient_markers):
        return "technical"
    return "blocked"


def _ensure_republish_activity_count(account_id=MAIN_ACCOUNT_ID, state=None):
    return _ensure_publish_capacity(account_id, state)


def _postpone_republish(state, slug, meta, reason):
    until = datetime.now(timezone.utc) + timedelta(days=1)
    meta["republish_postponed_until"] = until.isoformat()
    meta.setdefault("history", []).append({"action": "Erneuern um 1 Tag verschoben: " + reason, "date": _now()})
    state.setdefault("ads", {})[slug] = meta


def _postpone_scheduled_publish(state, slug, meta, reason):
    now = datetime.now(timezone.utc)
    current = _iso_dt(meta.get("scheduled_publish_at"))
    base = current if current and current > now else now
    meta["scheduled_publish_at"] = (base + timedelta(days=1)).isoformat()
    meta.setdefault("history", []).append({"action": "Veröffentlichung um 1 Tag verschoben: " + reason, "date": _now()})
    state.setdefault("ads", {})[slug] = meta


def _increment_activity_posted_count(account_id=MAIN_ACCOUNT_ID, delta=1, state=None):
    own_state = state is None
    state = state if state is not None else _load_state()
    account_id = _valid_account_id(account_id, state)
    activity = dict(_get_account_activity(account_id, state) or {})
    count = _posted_last_30_count(activity, account_id, state)
    if count is not None:
        activity["posted_last_30_days"] = count + int(delta)
        activity["updated_at"] = activity.get("updated_at") or _now()
        activity["locally_incremented"] = True
        state.setdefault("account_activity_by_account", {})[account_id] = activity
        if account_id == MAIN_ACCOUNT_ID:
            state["account_activity"] = activity
        if own_state:
            _save_state(state)

# -- Bot Config --

def _load_bot_config():
    if BOT_CONFIG.exists():
        return yaml.safe_load(BOT_CONFIG.read_text("utf-8")) or {}
    return {}

def _save_bot_config(cfg):
    BOT_CONFIG.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")


def _enable_run_diagnostics(cfg):
    """Enable bot page/config capture for every single-ad run."""
    cfg = copy.deepcopy(cfg)
    cfg["diagnostics"] = {
        "capture_on": {
            "login_detection": True,
            "publish": True,
        },
        "capture_log_copy": True,
        "output_dir": str(DIAGNOSTICS_DIR),
    }
    return cfg


def _normalize_shipping_price_value(value, default=""):
    value = "" if value is None else str(value).strip()
    if not value:
        value = str(default or "").strip()
    value = value.replace("€", "").replace("EUR", "").replace("eur", "").strip()
    value = value.replace(".", ",")
    value = re.sub(r"[^0-9,]", "", value)
    if value.count(",") > 1:
        first, rest = value.split(",", 1)
        value = first + "," + rest.replace(",", "")
    return value


def _normalize_shipping_prices(values=None):
    values = values or {}
    normalized = {}
    for code, default in DEFAULT_SHIPPING_PRICES.items():
        normalized[code] = _normalize_shipping_price_value(values.get(code), default)
    return normalized


def _get_shipping_prices():
    cfg = _load_bot_config()
    ui = cfg.get("ui", {}) if isinstance(cfg.get("ui", {}), dict) else {}
    return _normalize_shipping_prices(ui.get("shipping_prices") or {})

def _ensure_bot_config(settings):
    """Globale Standardwerte speichern und auf alle Account-Configs anwenden, Logins bleiben erhalten."""
    state = _load_state()
    accounts = _accounts_from_state(state) or {MAIN_ACCOUNT_ID: {"id": MAIN_ACCOUNT_ID, "name": MAIN_ACCOUNT_NAME, "is_main": True}}
    existing_main = _load_bot_config()
    existing_ui = existing_main.get("ui", {}) if isinstance(existing_main.get("ui", {}), dict) else {}
    shipping_prices = _normalize_shipping_prices(settings.get("shipping_prices") or existing_ui.get("shipping_prices") or {})
    for account_id in accounts:
        cfg = _load_account_config(account_id)
        if not cfg:
            cfg = copy.deepcopy(existing_main)
        login = cfg.get("login", {}) if isinstance(cfg.get("login"), dict) else {}
        browser = cfg.get("browser", {}) if isinstance(cfg.get("browser"), dict) else {}
        browser.setdefault("binary_location", os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser"))
        browser.setdefault("arguments", [
            "--no-sandbox", "--headless=new", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-software-rasterizer", "--window-size=1280,1024",
        ])
        browser["use_private_window"] = False
        browser["user_data_dir"] = str(_account_profile_dir(account_id))
        cfg["login"] = login
        cfg["browser"] = browser
        cfg["ad_defaults"] = {
            "active": True,
            "type": "OFFER",
            "republication_interval": settings.get("republish_days", REPUBLISH_INTERVAL),
            "contact": {"name": settings.get("contact_name", "")},
            "location": settings.get("default_location", ""),
            "shipping_type": "SHIPPING",
            "shipping_options": list(DEFAULT_SHIPPING_OPTIONS),
        }
        cfg["ad_files"] = cfg.get("ad_files") or (["ads/*.yaml"] if account_id == MAIN_ACCOUNT_ID else [str(ADS_DIR / "*.yaml")])
        cfg["ui"] = {"shipping_prices": shipping_prices}
        _save_account_config(account_id, cfg)


def _get_settings():
    cfg = _load_bot_config()
    defaults = cfg.get("ad_defaults", {}) if isinstance(cfg.get("ad_defaults"), dict) else {}
    contact = defaults.get("contact", {}) if isinstance(defaults.get("contact"), dict) else {}
    ui = cfg.get("ui", {}) if isinstance(cfg.get("ui", {}), dict) else {}
    state = _load_state()
    accounts = _accounts_from_state(state)
    configured = any(_account_login(account_id).get("configured") for account_id in accounts) if accounts else bool((cfg.get("login") or {}).get("username"))
    main_login = _account_login(MAIN_ACCOUNT_ID)
    return {
        "email": main_login.get("email", ""),
        "password": main_login.get("password", ""),
        "contact_name": contact.get("name", ""),
        "default_location": defaults.get("location", ""),
        "republish_days": defaults.get("republication_interval", REPUBLISH_INTERVAL),
        "price_reduction_days": DEFAULT_PRICE_REDUCTION_DAYS,
        "configured": configured,
        "shipping_prices": _normalize_shipping_prices(ui.get("shipping_prices") or {}),
    }

# -- Ad YAML Management --

def _ad_yaml_path(slug):
    return ADS_DIR / (slug + ".yaml")

def _ad_images_dir(slug):
    return IMAGES_DIR / slug

def _write_ad_yaml(slug, data, image_files=None):
    existing = _read_ad_yaml(slug) or {}
    ad = {
        "active": data.get("active", True),
        "type": data.get("ad_type", "OFFER"),
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "price": data.get("price", 0),
        "price_type": data.get("price_type", "NEGOTIABLE"),
        "category": data.get("category", ""),
        "folder": data.get("folder", "").strip(),
        "shipping_type": data.get("shipping_type", "SHIPPING"),
    }
    shipping_options = data.get("shipping_options") or []
    if ad["shipping_type"] == "SHIPPING" and shipping_options:
        ad["shipping_options"] = shipping_options
    for managed_key in ("id", "created_at", "updated_at", "created_on_kleinanzeigen"):
        if managed_key in existing:
            ad[managed_key] = existing[managed_key]
    cn = data.get("contact_name", "").strip()
    if cn:
        ad["contact"] = {"name": cn}
    loc = data.get("location", "").strip()
    if loc:
        ad["location"] = loc
    sc = data.get("shipping_costs", "").strip() if isinstance(data.get("shipping_costs"), str) else str(data.get("shipping_costs", ""))
    sc = sc.strip()
    if sc:
        try:
            ad["shipping_costs"] = float(sc.replace(",", "."))
        except ValueError:
            pass
    ri = data.get("republish_days")
    if ri:
        ad["republication_interval"] = int(ri)

    price_reduction_enabled = _parse_bool(data.get("republish_price_reduction_enabled"), False)
    if ad["price_type"] == "GIVE_AWAY":
        price_reduction_enabled = False
    ad["republish_price_reduction_enabled"] = price_reduction_enabled

    reduction_days = data.get("republish_price_reduction_days")
    try:
        reduction_days = max(1, int(reduction_days or DEFAULT_PRICE_REDUCTION_DAYS))
    except Exception:
        reduction_days = DEFAULT_PRICE_REDUCTION_DAYS
    ad["republish_price_reduction_days"] = reduction_days

    price_drop = max(0.0, _parse_float(data.get("republish_price_drop"), 0.0))
    ad["republish_price_drop"] = round(price_drop, 2)
    if price_drop <= 0:
        ad["republish_price_reduction_enabled"] = False

    min_price = max(0.0, _parse_float(data.get("republish_min_price"), 0.0))
    ad["republish_min_price"] = round(min_price, 2)

    if image_files:
        ad["images"] = ["../images/" + slug + "/" + f for f in image_files]
    ADS_DIR.mkdir(parents=True, exist_ok=True)
    _write_yaml_file(_ad_yaml_path(slug), ad)

def _read_ad_yaml(slug):
    p = _ad_yaml_path(slug)
    if p.exists():
        return yaml.safe_load(p.read_text("utf-8")) or {}
    return None


def _write_yaml_file(path, data):
    Path(path).write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")


def _parse_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip().replace(",", ".")
        if raw == "":
            return default
        return float(raw)
    except Exception:
        return default


def _parse_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"", "0", "false", "nein", "no", "off"}


def _price_reduction_config(ad):
    ad = ad or {}
    drop = max(0.0, _parse_float(ad.get("republish_price_drop"), 0.0))
    legacy = "republish_price_reduction_enabled" not in ad
    enabled = _parse_bool(ad.get("republish_price_reduction_enabled"), drop > 0 if legacy else False)
    if str(ad.get("price_type") or "").upper() == "GIVE_AWAY":
        enabled = False
    try:
        days_default = int(ad.get("republication_interval") or REPUBLISH_INTERVAL) if legacy and drop > 0 else DEFAULT_PRICE_REDUCTION_DAYS
        days = max(1, int(ad.get("republish_price_reduction_days") or days_default))
    except Exception:
        days = DEFAULT_PRICE_REDUCTION_DAYS
    min_price = max(0.0, _parse_float(ad.get("republish_min_price"), 0.0))
    return {
        "enabled": enabled and drop > 0,
        "days": days,
        "drop": round(drop, 2),
        "min_price": round(min_price, 2),
        "legacy": legacy,
    }


def _ensure_price_reduction_anchor(slug, ad, meta, now_utc=None):
    cfg = _price_reduction_config(ad)
    if not cfg["enabled"]:
        return None
    existing = _iso_dt(meta.get("price_reduction_anchor_at") or meta.get("last_price_reduction_at"))
    if existing:
        return existing
    reference = _iso_dt(meta.get("last_published"))
    if not reference:
        reference = _iso_dt(_age_reference_iso(slug, ad, meta))
    reference = reference or (now_utc or datetime.now(timezone.utc))
    meta["price_reduction_anchor_at"] = reference.isoformat()
    return reference


def _prepare_republish_price_reduction(slug, meta, now_utc=None):
    ad = _read_ad_yaml(slug)
    if not ad:
        return None
    cfg = _price_reduction_config(ad)
    if not cfg["enabled"]:
        return None
    now_utc = now_utc or datetime.now(timezone.utc)
    anchor = _ensure_price_reduction_anchor(slug, ad, meta, now_utc=now_utc)
    if not anchor or now_utc < anchor + timedelta(days=cfg["days"]):
        return None
    current_price = max(0.0, _parse_float(ad.get("price"), 0.0))
    floor = cfg["min_price"]
    if current_price <= floor:
        return None
    new_price = max(floor, round(current_price - cfg["drop"], 2))
    if new_price >= current_price:
        return None
    ad["price"] = new_price
    _write_yaml_file(_ad_yaml_path(slug), ad)
    return {
        "old_price": current_price,
        "new_price": new_price,
        "drop": cfg["drop"],
        "min_price": floor,
        "reduction_at": now_utc.isoformat(),
    }


def _commit_price_reduction(meta, price_change):
    if not price_change:
        return
    reduced_at = price_change.get("reduction_at") or _now()
    meta["last_price_reduction_at"] = reduced_at
    meta["price_reduction_anchor_at"] = reduced_at
    meta["price_reduction_count"] = int(meta.get("price_reduction_count") or 0) + 1


def _migrate_price_reduction_settings():
    state = _load_state()
    migrations = state.setdefault("migrations", {})
    marker = "independent_price_reduction_v1"
    if migrations.get(marker):
        return 0
    changed = 0
    for path in sorted(ADS_DIR.glob("*.yaml")):
        slug = path.stem
        ad = _read_ad_yaml(slug) or {}
        if not ad:
            continue
        cfg = _price_reduction_config(ad)
        ad_changed = False
        if "republish_price_reduction_enabled" not in ad:
            ad["republish_price_reduction_enabled"] = bool(cfg["enabled"])
            ad_changed = True
        if "republish_price_reduction_days" not in ad:
            ad["republish_price_reduction_days"] = int(cfg["days"])
            ad_changed = True
        if "republish_min_price" not in ad:
            ad["republish_min_price"] = float(cfg["min_price"])
            ad_changed = True
        if "republish_price_drop" not in ad:
            ad["republish_price_drop"] = float(cfg["drop"])
            ad_changed = True
        if str(ad.get("price_type") or "").upper() == "GIVE_AWAY" and ad.get("republish_price_reduction_enabled"):
            ad["republish_price_reduction_enabled"] = False
            ad_changed = True
        if ad_changed:
            _write_yaml_file(path, ad)
            changed += 1
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        if cfg["enabled"] and not meta.get("price_reduction_anchor_at"):
            ref = meta.get("last_price_reduction_at") or meta.get("last_published")
            if ref:
                meta["price_reduction_anchor_at"] = ref
    migrations[marker] = _now()
    _save_state(state)
    return changed


def _fmt_money(value):
    try:
        num = float(value)
        if num.is_integer():
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)




def _append_price_history(meta, old_price, new_price, *, source="manual", action="Preis manuell geändert", at=None):
    """Persist one price-change event without touching the automatic price schedule."""
    old_value = round(max(0.0, _parse_float(old_price, 0.0)), 2)
    new_value = round(max(0.0, _parse_float(new_price, 0.0)), 2)
    if abs(old_value - new_value) < 0.005:
        return False
    meta.setdefault("history", []).append({
        "action": str(action or "Preis geändert"),
        "date": str(at or _now()),
        "event": "price_changed",
        "source": str(source or ""),
        "old_price": old_value,
        "new_price": new_value,
    })
    return True


def _history_price_pair(row):
    if not isinstance(row, dict):
        return None
    old_raw = row.get("old_price")
    new_raw = row.get("new_price")
    if old_raw not in (None, "") and new_raw not in (None, ""):
        return (round(max(0.0, _parse_float(old_raw, 0.0)), 2),
                round(max(0.0, _parse_float(new_raw, 0.0)), 2))
    action = str(row.get("action") or "")
    match = re.search(r"(?:Preis(?: automatisch)? gesenkt|Preis manuell geändert)\s*:?\s*([0-9]+(?:[.,][0-9]+)?)\s*€?\s*→\s*([0-9]+(?:[.,][0-9]+)?)\s*€?", action, re.I)
    if not match:
        return None
    return (round(max(0.0, _parse_float(match.group(1), 0.0)), 2),
            round(max(0.0, _parse_float(match.group(2), 0.0)), 2))


def _price_history_summary(ad, rows):
    """Summarize only price values that can actually be proven from stored history."""
    current = round(max(0.0, _parse_float((ad or {}).get("price"), 0.0)), 2)
    events = []
    for index, row in enumerate(rows or []):
        pair = _history_price_pair(row)
        if not pair:
            continue
        events.append((_iso_dt(row.get("date")) or datetime.min.replace(tzinfo=timezone.utc), index, pair))
    events.sort(key=lambda item: (item[0], item[1]))
    first_known = events[0][2][0] if events else current
    delta = round(current - first_known, 2)
    return {
        "current": _fmt_money(current),
        "first_known": _fmt_money(first_known),
        "delta": _fmt_money(abs(delta)),
        "direction": "down" if delta < -0.005 else ("up" if delta > 0.005 else "same"),
        "event_count": len(events),
    }

def _relative_due_detail(dt, now_utc=None):
    if not dt:
        return ""
    now_utc = now_utc or datetime.now(timezone.utc)
    local_due = dt.astimezone(_local_tz())
    local_now = now_utc.astimezone(_local_tz())
    days = (local_due.date() - local_now.date()).days
    if dt <= now_utc:
        return "jetzt fällig"
    if days == 0:
        return f"heute um {local_due.strftime('%H:%M')} Uhr"
    if days == 1:
        return f"morgen um {local_due.strftime('%H:%M')} Uhr"
    return f"in {days} Tagen"


def _price_automation_detail(slug, ad, meta, created_ref, now_utc=None):
    cfg = _price_reduction_config(ad)
    if not cfg.get("enabled"):
        return "", None
    now_utc = now_utc or datetime.now(timezone.utc)
    current_price = max(0.0, _parse_float(ad.get("price"), 0.0))
    floor = max(0.0, _parse_float(cfg.get("min_price"), 0.0))
    pieces = [f"Preisautomatik: −{_fmt_money(cfg.get('drop') or 0)} € alle {int(cfg.get('days') or DEFAULT_PRICE_REDUCTION_DAYS)} Tage"]
    if floor > 0:
        pieces.append(f"Mindestpreis {_fmt_money(floor)} €")
    due_dt = None
    if floor > 0 and current_price <= floor:
        pieces.append("Mindestpreis erreicht")
    else:
        anchor = _iso_dt(meta.get("price_reduction_anchor_at") or meta.get("last_price_reduction_at") or meta.get("last_published") or created_ref)
        if anchor:
            due_dt = anchor + timedelta(days=int(cfg.get("days") or DEFAULT_PRICE_REDUCTION_DAYS))
            due_label = _relative_due_detail(due_dt, now_utc=now_utc)
            if due_label == "jetzt fällig":
                pieces.append("nächste Senkung jetzt fällig")
            elif due_label:
                pieces.append(f"nächste Senkung {due_label}")
    return " · ".join(pieces), due_dt


def _operation_card_labels(operation, meta, now_utc=None):
    operation = operation if isinstance(operation, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    now_utc = now_utc or datetime.now(timezone.utc)
    failure = ""
    retry = ""
    action_label = str(operation.get("action_label") or _operation_label(operation.get("action"))).strip()
    status = str(operation.get("status") or "")
    if status == "failed":
        message = str(operation.get("message") or "Vorgang fehlgeschlagen").strip()
        failure = f"{action_label} fehlgeschlagen: {message}"
    retry_dt = _iso_dt(operation.get("next_retry_at") or meta.get("republish_retry_at") or meta.get("publish_retry_at"))
    if retry_dt:
        detail = _relative_due_detail(retry_dt, now_utc=now_utc)
        if retry_dt <= now_utc:
            retry = "Wiederholungsversuch freigegeben · erfolgt bei der nächsten Automatikprüfung"
        else:
            retry = f"Nächster automatischer Versuch {detail}"
    return failure, retry


def _restore_republish_price(slug, old_price):
    ad = _read_ad_yaml(slug)
    if not ad:
        return
    ad["price"] = old_price
    _write_yaml_file(_ad_yaml_path(slug), ad)

def _image_order_prefix(name):
    m = re.match(r"^(\d+)_", name)
    return int(m.group(1)) if m else None


def _strip_image_order_prefix(name):
    return re.sub(r"^\d+_", "", name)


def _list_ad_images(slug):
    d = _ad_images_dir(slug)
    if not d.is_dir():
        return []
    files = [f.name for f in d.iterdir() if f.is_file()]
    ad = _read_ad_yaml(slug) or {}
    yaml_names = []
    for rel in ad.get("images", []) or []:
        try:
            yaml_names.append(Path(rel).name)
        except Exception:
            pass
    ordered = [name for name in yaml_names if name in files]
    extras = [name for name in files if name not in ordered]
    extras.sort(key=lambda n: ((_image_order_prefix(n) is None), _image_order_prefix(n) or 9999, n.lower()))
    return ordered + extras


def _kaanzeige_export_images(slug):
    """Return existing ad images in display order and safe archive paths."""
    image_dir = _ad_images_dir(slug)
    try:
        resolved_dir = image_dir.resolve()
    except OSError as exc:
        raise ValueError("Der Bildordner der Anzeige ist nicht lesbar.") from exc

    entries = []
    for index, name in enumerate(_list_ad_images(slug), start=1):
        source = image_dir / name
        try:
            resolved = source.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ValueError(f"Bild '{name}' ist nicht mehr vorhanden.") from exc
        if resolved.parent != resolved_dir or source.is_symlink() or not resolved.is_file():
            raise ValueError(f"Bild '{name}' liegt außerhalb des Anzeigenordners.")
        suffix = resolved.suffix.lower()
        if suffix not in IMPORT_IMAGE_EXTENSIONS:
            raise ValueError(f"Nicht unterstütztes Bildformat: {name}")
        entries.append((resolved, f"bilder/{index:02d}{suffix}"))

    if len(entries) > IMPORT_MAX_IMAGES:
        raise ValueError(f"Maximal {IMPORT_MAX_IMAGES} Bilder pro Anzeige sind erlaubt.")
    return entries


def _kaanzeige_export_payload(ad, archive_image_names):
    """Map stored ad YAML back to the import schema without runtime state."""
    ad = ad or {}
    contact = ad.get("contact") if isinstance(ad.get("contact"), dict) else {}
    shipping_options = ad.get("shipping_options") or []
    if isinstance(shipping_options, str):
        shipping_options = [shipping_options]
    else:
        shipping_options = list(shipping_options) if isinstance(shipping_options, (list, tuple)) else []

    reduction = _price_reduction_config(ad)
    try:
        republish_days = max(1, int(ad.get("republication_interval") or REPUBLISH_INTERVAL))
    except (TypeError, ValueError):
        republish_days = REPUBLISH_INTERVAL
    payload = {
        "format": "kleinanzeigen-manager-import",
        "version": 1,
        "title": str(ad.get("title") or ""),
        "description": str(ad.get("description") or ""),
        "price": ad.get("price", 0),
        "price_type": str(ad.get("price_type") or "NEGOTIABLE"),
        "category": str(ad.get("category") or ""),
        "folder": str(ad.get("folder") or ""),
        "ad_type": str(ad.get("type") or "OFFER"),
        "shipping_type": str(ad.get("shipping_type") or "SHIPPING"),
        "shipping_options": shipping_options,
        "contact_name": str(contact.get("name") or ""),
        "location": str(ad.get("location") or ""),
        "republish_days": republish_days,
        "republish_price_reduction_enabled": bool(reduction["enabled"]),
        "republish_price_reduction_days": int(reduction["days"]),
        "republish_price_drop": ad.get("republish_price_drop", 0),
        "republish_min_price": ad.get("republish_min_price", 0),
        "active": _parse_bool(ad.get("active"), True),
        "images": list(archive_image_names),
    }
    if "shipping_costs" in ad:
        payload["shipping_costs"] = ad.get("shipping_costs")
    return payload


def _build_kaanzeige_export(slug):
    """Build one import-compatible .kaanzeige archive fully in memory."""
    ad = _read_ad_yaml(slug)
    if not ad:
        raise FileNotFoundError("Anzeige nicht gefunden.")

    image_entries = _kaanzeige_export_images(slug)
    payload = _kaanzeige_export_payload(ad, [archive_name for _path, archive_name in image_entries])
    # Validate the JSON fields with the same normalization used by imports.
    _normalize_import_data(payload)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr(
            "anzeige.json",
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        for source, archive_name in image_entries:
            # Images are copied byte-for-byte. ZIP_STORED avoids even container-level recompression.
            zf.write(source, arcname=archive_name, compress_type=zipfile.ZIP_STORED)
    output.seek(0)
    return output


def _save_uploaded_images(slug, files):
    img_dir = _ad_images_dir(slug)
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        if f and f.filename:
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", _strip_image_order_prefix(f.filename))
            candidate = safe_name
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            counter = 1
            while (img_dir / candidate).exists():
                candidate = f"{stem}_{counter}{suffix}"
                counter += 1
            f.save(str(img_dir / candidate))
            saved.append(candidate)
    return saved


def _normalize_image_order(slug, ordered_names):
    img_dir = _ad_images_dir(slug)
    img_dir.mkdir(parents=True, exist_ok=True)
    renamed = []
    temp_pairs = []
    for idx, name in enumerate(ordered_names, start=1):
        src = img_dir / name
        if not src.exists():
            continue
        temp_name = f".__tmp__{uuid.uuid4().hex}_{_strip_image_order_prefix(name)}"
        tmp = img_dir / temp_name
        src.rename(tmp)
        temp_pairs.append((tmp, idx, name))
    for tmp, idx, original_name in temp_pairs:
        final_name = f"{idx:02d}_{_strip_image_order_prefix(original_name)}"
        final_path = img_dir / final_name
        counter = 1
        while final_path.exists():
            stem = Path(final_name).stem
            suffix = Path(final_name).suffix
            final_name = f"{stem}_{counter}{suffix}"
            final_path = img_dir / final_name
            counter += 1
        tmp.rename(final_path)
        renamed.append(final_name)
    return renamed


def _sort_existing_images_from_form(existing_names, form):
    raw_names = form.getlist('existing_image_name')
    raw_orders = form.getlist('existing_image_order')
    submitted = []
    for idx, name in enumerate(raw_names):
        try:
            order = int((raw_orders[idx] if idx < len(raw_orders) else '').strip() or idx + 1)
        except Exception:
            order = idx + 1
        submitted.append((name, order, idx))
    order_map = {name: (order, idx) for name, order, idx in submitted}
    return sorted(existing_names, key=lambda name: (order_map.get(name, (9999, 9999))[0], order_map.get(name, (9999, 9999))[1], name.lower()))


# -- Anzeigen-Import aus /media/Import/Kleinanzeigen --

def _import_file_paths():
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        (p for p in IMPORT_DIR.iterdir() if p.is_file() and p.suffix.lower() == IMPORT_EXTENSION),
        key=lambda p: (p.stat().st_mtime, p.name.lower()),
    )


def _count_import_files():
    try:
        return len(_import_file_paths())
    except Exception:
        return 0


def _safe_archive_name(name):
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/"):
        raise ValueError("Ungültiger Dateipfad im Importpaket.")
    path = Path(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Unsicherer Dateipfad im Importpaket.")
    return path.as_posix()


def _clean_import_text(value, maximum=None):
    value = str(value or "").replace("\r\n", "\n").strip()
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"Text ist länger als {maximum} Zeichen.")
    return value


def _normalize_import_data(payload):
    if not isinstance(payload, dict):
        raise ValueError("anzeige.json muss ein JSON-Objekt enthalten.")

    title = _clean_import_text(payload.get("title"), 65)
    description = _clean_import_text(payload.get("description"))
    if not title:
        raise ValueError("Titel fehlt in anzeige.json.")
    if not description:
        raise ValueError("Beschreibung fehlt in anzeige.json.")

    price_type = str(payload.get("price_type") or "NEGOTIABLE").strip().upper()
    valid_price_types = {code for code, _label in PRICE_TYPES}
    if price_type not in valid_price_types:
        price_type = "NEGOTIABLE"

    price = _parse_float(payload.get("price"), 0.0)
    if price < 0:
        raise ValueError("Preis darf nicht negativ sein.")
    if price_type == "GIVE_AWAY":
        price = 0.0

    ad_type = str(payload.get("ad_type") or "OFFER").strip().upper()
    if ad_type not in {code for code, _label in AD_TYPES}:
        ad_type = "OFFER"

    shipping_type = str(payload.get("shipping_type") or "SHIPPING").strip().upper()
    if shipping_type not in {code for code, _label in SHIPPING_TYPES}:
        shipping_type = "SHIPPING"

    shipping_options = []
    requested_options = payload.get("shipping_options") or []
    if isinstance(requested_options, str):
        requested_options = [requested_options]
    if shipping_type == "SHIPPING":
        for option in requested_options:
            option = str(option).strip()
            if option in SHIPPING_OPTION_TO_GROUP and option not in shipping_options:
                shipping_options.append(option)
        if shipping_options:
            first_group = SHIPPING_OPTION_TO_GROUP[shipping_options[0]]
            shipping_options = [o for o in shipping_options if SHIPPING_OPTION_TO_GROUP[o] == first_group]
        else:
            shipping_options = list(DEFAULT_SHIPPING_OPTIONS)

    defaults = _get_settings()
    republish_days = payload.get("republish_days", defaults.get("republish_days") or REPUBLISH_INTERVAL)
    try:
        republish_days = max(1, int(republish_days))
    except Exception:
        republish_days = REPUBLISH_INTERVAL

    active_value = payload.get("active", True)
    if isinstance(active_value, str):
        active = active_value.strip().lower() not in {"0", "false", "nein", "no", "off"}
    else:
        active = bool(active_value)

    imported_drop = str(payload.get("republish_price_drop") or "").strip()
    legacy_price_reduction = "republish_price_reduction_enabled" not in payload
    price_reduction_enabled = _parse_bool(
        payload.get("republish_price_reduction_enabled"),
        _parse_float(imported_drop, 0.0) > 0 if legacy_price_reduction else False,
    )
    if price_type == "GIVE_AWAY":
        price_reduction_enabled = False
    reduction_days_default = republish_days if legacy_price_reduction and _parse_float(imported_drop, 0.0) > 0 else DEFAULT_PRICE_REDUCTION_DAYS

    return {
        "title": title,
        "description": description,
        "price": round(price, 2),
        "price_type": price_type,
        "category": _clean_import_text(payload.get("category")),
        "folder": _clean_import_text(payload.get("folder"), 80),
        "ad_type": ad_type,
        "shipping_type": shipping_type,
        "shipping_costs": str(payload.get("shipping_costs") or "").strip(),
        "shipping_options": shipping_options,
        "contact_name": _clean_import_text(payload.get("contact_name") or defaults.get("contact_name")),
        "location": _clean_import_text(payload.get("location") or defaults.get("default_location")),
        "republish_days": republish_days,
        "republish_price_reduction_enabled": price_reduction_enabled,
        "republish_price_reduction_days": payload.get("republish_price_reduction_days") or reduction_days_default,
        "republish_price_drop": imported_drop,
        "republish_min_price": str(payload.get("republish_min_price") or "").strip(),
        "active": active,
    }


def _archive_image_names(zf, payload):
    archive_files = {}
    total_size = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        safe_name = _safe_archive_name(info.filename)
        if info.file_size < 0:
            raise ValueError("Ungültige Dateigröße im Importpaket.")
        total_size += info.file_size
        if total_size > IMPORT_MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Importpaket ist zu groß.")
        archive_files[safe_name] = info
    if len(archive_files) > IMPORT_MAX_FILES:
        raise ValueError("Importpaket enthält zu viele Dateien.")
    if "anzeige.json" not in archive_files:
        raise ValueError("anzeige.json fehlt im Importpaket.")

    requested = payload.get("images") or []
    if isinstance(requested, str):
        requested = [requested]
    image_names = []
    if requested:
        for raw in requested:
            safe_name = _safe_archive_name(raw)
            if safe_name not in archive_files:
                raise ValueError(f"Bild '{safe_name}' fehlt im Importpaket.")
            if Path(safe_name).suffix.lower() not in IMPORT_IMAGE_EXTENSIONS:
                raise ValueError(f"Nicht unterstütztes Bildformat: {safe_name}")
            if safe_name not in image_names:
                image_names.append(safe_name)
    else:
        image_names = sorted(
            name for name in archive_files
            if name != "anzeige.json" and Path(name).suffix.lower() in IMPORT_IMAGE_EXTENSIONS
        )

    if len(image_names) > IMPORT_MAX_IMAGES:
        raise ValueError(f"Maximal {IMPORT_MAX_IMAGES} Bilder pro Anzeige sind erlaubt.")
    return archive_files, image_names


def _unique_slug_for_title(title):
    base = _slug(title)
    candidate = base
    while _ad_yaml_path(candidate).exists() or _ad_images_dir(candidate).exists():
        candidate = f"{base}-{uuid.uuid4().hex[:4]}"
    return candidate


def _import_single_package(package_path):
    package_path = Path(package_path)
    if package_path.suffix.lower() != IMPORT_EXTENSION:
        raise ValueError(f"Nur {IMPORT_EXTENSION}-Dateien werden importiert.")

    slug = None
    stage_dir = Path(tempfile.mkdtemp(prefix="ka_import_", dir=str(DATA_DIR)))
    stage_images = stage_dir / "images"
    stage_images.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            try:
                payload = json.loads(zf.read("anzeige.json").decode("utf-8-sig"))
            except KeyError as exc:
                raise ValueError("anzeige.json fehlt im Importpaket.") from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("anzeige.json ist keine gültige UTF-8-JSON-Datei.") from exc

            data = _normalize_import_data(payload)
            archive_files, image_names = _archive_image_names(zf, payload)
            slug = _unique_slug_for_title(data["title"])

            staged_names = []
            for index, archive_name in enumerate(image_names, start=1):
                suffix = Path(archive_name).suffix.lower()
                saved_name = f"{index:02d}_import{suffix}"
                target = stage_images / saved_name
                info = archive_files[archive_name]
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                staged_names.append(saved_name)

        final_images = _ad_images_dir(slug)
        if staged_names:
            stage_images.rename(final_images)
        _write_ad_yaml(slug, data, staged_names)

        state = _load_state()
        state.setdefault("ads", {})[slug] = {
            "created_at": _now(),
            "last_published": None,
            "publish_count": 0,
            "scheduled_publish_at": None,
            "account_id": MAIN_ACCOUNT_ID,
            "imported_at": _now(),
            "import_file": package_path.name,
            "history": [{"action": "aus Datei importiert", "date": _now()}],
        }
        folder = data.get("folder", "").strip()
        if folder:
            folders = state.setdefault("folders", [])
            if folder.lower() not in {str(item).strip().lower() for item in folders}:
                folders.append(folder)
                state["folders"] = sorted((str(item).strip() for item in folders if str(item).strip()), key=str.lower)
        _save_state(state)
        try:
            package_path.unlink()
        except Exception as exc:
            raise RuntimeError("Anzeige wurde angelegt, aber die Importdatei konnte nicht gelöscht werden.") from exc
        return {"slug": slug, "title": data["title"], "images": len(staged_names)}
    except Exception:
        if slug:
            try:
                _ad_yaml_path(slug).unlink(missing_ok=True)
            except Exception:
                pass
            shutil.rmtree(_ad_images_dir(slug), ignore_errors=True)
            try:
                state = _load_state()
                state.get("ads", {}).pop(slug, None)
                _save_state(state)
            except Exception:
                pass
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _move_failed_import(package_path, error_message):
    IMPORT_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    package_path = Path(package_path)
    target = IMPORT_ERROR_DIR / package_path.name
    if target.exists():
        target = IMPORT_ERROR_DIR / f"{package_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{package_path.suffix}"
    try:
        shutil.move(str(package_path), str(target))
    except Exception:
        target = package_path
    try:
        error_path = target.with_suffix(target.suffix + ".fehler.txt")
        error_path.write_text(
            f"Import fehlgeschlagen am {_now_local()}\n\n{error_message}\n",
            "utf-8",
        )
    except Exception:
        pass
    return target


def _record_import_run(result, trigger):
    state = _load_state()
    import_state = state.setdefault("imports", {})
    import_state["last_run_at"] = _now()
    import_state["last_trigger"] = trigger
    import_state["last_imported"] = result["imported"]
    import_state["last_failed"] = result["failed"]
    import_state["last_titles"] = [item["title"] for item in result.get("items", [])][-10:]
    import_state["total_imported"] = int(import_state.get("total_imported") or 0) + result["imported"]
    if trigger == "automatic" and result["imported"]:
        import_state["pending_notice"] = int(import_state.get("pending_notice") or 0) + result["imported"]
    elif trigger == "manual":
        import_state["pending_notice"] = 0
    _save_state(state)


def _process_import_files(trigger="manual"):
    result = {"imported": 0, "failed": 0, "items": [], "errors": []}
    if not _import_lock.acquire(blocking=False):
        result["busy"] = True
        return result
    try:
        IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        IMPORT_ERROR_DIR.mkdir(parents=True, exist_ok=True)
        for package_path in _import_file_paths():
            if trigger == "automatic":
                try:
                    if time.time() - package_path.stat().st_mtime < 15:
                        continue
                except Exception:
                    continue
            try:
                imported = _import_single_package(package_path)
                result["imported"] += 1
                result["items"].append(imported)
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                failed_path = _move_failed_import(package_path, message)
                result["failed"] += 1
                result["errors"].append({"file": failed_path.name, "error": message})
        _record_import_run(result, trigger)
        return result
    finally:
        _import_lock.release()



# -- Ereignisgesteuerter Import aus /media/Import/Kleinanzeigen --
#
# Google Drive ist nur Transport. Eine Datei wird zuerst als versteckte .part-Datei
# vollständig geschrieben und anschließend atomar auf *.kaanzeige umbenannt. Erst
# das IN_MOVED_TO-/IN_CLOSE_WRITE-Ereignis im Media-Ordner stößt den echten Import an.
# Dadurch kann der Manager keine halb übertragene ZIP-Datei erwischen.

DRIVE_META_SUFFIX = ".drive-import.json"
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IMPORT_WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF | IN_Q_OVERFLOW


def _drive_meta_path(package_path):
    package_path = Path(package_path)
    return package_path.with_name(f".{package_path.name}{DRIVE_META_SUFFIX}")


def _write_drive_meta(package_path, values):
    path = _drive_meta_path(package_path)
    payload = dict(values or {})
    payload["local_file"] = Path(package_path).name
    payload["updated_at"] = _now()
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)
    return path


def _read_drive_meta(package_path):
    path = _drive_meta_path(package_path)
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _remove_drive_meta(package_path):
    try:
        _drive_meta_path(package_path).unlink(missing_ok=True)
    except Exception:
        pass



DRIVE_PROCESSED_IDS_FILE = Path("/share/Kleinanzeigen/google-drive-processed-ids.json")

def _load_drive_processed_ids():
    ids = set()
    try:
        if DRIVE_PROCESSED_IDS_FILE.is_file():
            data = json.loads(DRIVE_PROCESSED_IDS_FILE.read_text("utf-8"))
            for item in data.get("processed_file_ids", []) or []:
                if item:
                    ids.add(str(item))
    except Exception:
        pass
    return ids

def _save_drive_processed_ids(ids):
    try:
        DRIVE_PROCESSED_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"processed_file_ids": list(ids)[-1000:], "updated_at": _now()}
        DRIVE_PROCESSED_IDS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass

def _mark_drive_processed(file_id):
    if not file_id:
        return
    ids = _load_drive_processed_ids()
    ids.add(str(file_id))
    _save_drive_processed_ids(ids)

def _pending_drive_file_ids():
    result = set(_load_drive_processed_ids())
    try:
        IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        for path in IMPORT_DIR.iterdir():
            if not path.is_file() or not path.name.startswith(".") or not path.name.endswith(DRIVE_META_SUFFIX):
                continue
            try:
                data = json.loads(path.read_text("utf-8"))
                file_id = str((data or {}).get("drive_file_id") or "").strip()
                if file_id:
                    result.add(file_id)
            except Exception:
                continue
    except Exception:
        pass
    # Dauerhafte Sperre: bereits erfolgreich importierte Drive-Dateien werden
    # auch nach Löschen der lokalen Sidecar-Datei nicht erneut importiert.
    try:
        state = _load_state() or {}
        for file_id in (state.get("google_drive_import", {}) or {}).get("processed_file_ids", []) or []:
            if file_id:
                result.add(str(file_id))
    except Exception:
        pass
    return result


def _record_single_import_result(imported=None, error=None, trigger="media_watcher"):
    result = {"imported": 1 if imported else 0, "failed": 1 if error else 0, "items": [], "errors": []}
    if imported:
        result["items"].append(imported)
    if error:
        result["errors"].append(error)
    _record_import_run(result, trigger)
    return result


def _process_single_import_path(package_path, trigger="media_watcher", wait_seconds=120):
    """Importiert genau die Datei, die gerade vollständig im Media-Ordner angekommen ist."""
    package_path = Path(package_path)
    if package_path.suffix.lower() != IMPORT_EXTENSION:
        return {"imported": 0, "failed": 0, "items": [], "errors": [], "ignored": True}
    if not package_path.is_file():
        return {"imported": 0, "failed": 0, "items": [], "errors": [], "missing": True}

    acquired = _import_lock.acquire(timeout=max(0, wait_seconds))
    if not acquired:
        return {"imported": 0, "failed": 0, "items": [], "errors": [], "busy": True}
    try:
        if not package_path.is_file():
            return {"imported": 0, "failed": 0, "items": [], "errors": [], "missing": True}
        try:
            imported = _import_single_package(package_path)
            return _record_single_import_result(imported=imported, trigger=trigger)
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            failed_path = _move_failed_import(package_path, message)
            return _record_single_import_result(
                error={"file": failed_path.name, "error": message},
                trigger=trigger,
            )
    finally:
        _import_lock.release()


def _postprocess_arrived_import(package_path, result, drive_meta=None):
    """Nach erfolgreichem Date/import: Push und bei Drive-Dateien Quellenbereinigung."""
    package_path = Path(package_path)
    drive_meta = dict(drive_meta or {})

    if int(result.get("imported") or 0) <= 0:
        return

    imported = (result.get("items") or [{}])[-1]
    title = str(imported.get("title") or package_path.name)

    # Der Push hängt ausschließlich am erfolgreichen Import einer Datei, die im
    # Media-Importordner angekommen ist. Eine Anzeige, die direkt in der Web-App
    # angelegt wird, durchläuft diesen Dateiwächter nicht und erzeugt keinen Push.
    notify_ok, notify_status = _notify_primary(
        "Kleinanzeigen",
        f"Neue Anzeige im Manager angekommen: {title}",
    )
    if not notify_ok:
        print(f"[media-import] Import erfolgreich, Push fehlgeschlagen: {notify_status}", flush=True)

    file_id = str(drive_meta.get("drive_file_id") or "").strip()
    if not file_id:
        return

    # Metadaten zunächst als 'importiert' persistieren. Falls die Drive-Bereinigung
    # scheitert oder das Add-on neu startet, verhindert diese Sidecar-Datei einen
    # erneuten Download derselben Drive-Datei.
    drive_meta.update({
        "imported": True,
        "imported_at": _now(),
        "imported_title": title,
        "notify_attempted": True,
        "notify_ok": bool(notify_ok),
        "notify_status": notify_status,
    })
    _write_drive_meta(package_path, drive_meta)

    try:
        session = _google_drive_session()
        cleaned, cleanup_mode, cleanup_note = _google_drive_cleanup_source(session, file_id)
    except Exception as exc:
        cleaned, cleanup_mode, cleanup_note = False, "", str(exc)

    processed_ids = []
    try:
        state = _load_state() or {}
        processed_ids = list(((state.get("google_drive_import", {}) or {}).get("processed_file_ids", []) or []))
    except Exception:
        processed_ids = []
    if file_id and file_id not in processed_ids:
        processed_ids.append(file_id)
    processed_ids = processed_ids[-500:]

    _mark_drive_processed(file_id)

    _google_drive_state_update(
        processed_file_ids=processed_ids,
        last_success_at=_now(),
        last_file=package_path.name,
        last_titles=[title],
        last_cleanup_mode=cleanup_mode,
        last_cleanup_note=cleanup_note,
        last_notify_ok=bool(notify_ok),
        last_notify_status=notify_status,
        last_error="" if cleaned else cleanup_note,
    )

    if cleaned:
        # Nach erfolgreichem Drive-Import und erfolgreicher Quellenbereinigung
        # wird die lokale Importdatei entfernt. Dadurch kann ein nachgelagerter
        # Sicherheits-Scan sie nicht erneut anstoßen.
        try:
            package_path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[media-import] Lokale Importdatei konnte nicht entfernt werden: {exc}", flush=True)
        _remove_drive_meta(package_path)
    else:
        print(
            f"[media-import] Anzeige ist im Manager, Drive-Bereinigung wird später erneut versucht: {cleanup_note}",
            flush=True,
        )


def _handle_arrived_import(package_path):
    """Wird ausschließlich durch ein echtes Dateisystem-Ereignis/Fallback-Scan aufgerufen."""
    package_path = Path(package_path)
    if package_path.suffix.lower() != IMPORT_EXTENSION or not package_path.is_file():
        return

    drive_meta = _read_drive_meta(package_path)
    result = _process_single_import_path(package_path, trigger="media_watcher", wait_seconds=120)
    if result.get("busy"):
        # Selten: manueller Import läuft gerade. Datei bleibt liegen und wird vom
        # Sicherheits-Scan des Watchers erneut aufgenommen.
        print(f"[media-import] Import beschäftigt, später erneut: {package_path.name}", flush=True)
        return

    if int(result.get("failed") or 0) > 0:
        message = ((result.get("errors") or [{}])[-1].get("error") or "Import fehlgeschlagen")
        print(f"[media-import] {package_path.name}: {message}", flush=True)
        # Bei einem ungültigen Drive-Paket die Herkunft persistieren und NICHT
        # erneut alle 5 Sekunden herunterladen. Eine korrigierte neu hochgeladene
        # Datei erhält eine neue Drive-ID und kann normal verarbeitet werden.
        if drive_meta:
            drive_meta.update({
                "failed": True,
                "failed_at": _now(),
                "failed_error": message,
            })
            _write_drive_meta(package_path, drive_meta)
        return

    _postprocess_arrived_import(package_path, result, drive_meta=drive_meta)


def _scan_pending_imports_for_watcher():
    """Sicherheitsnetz: verarbeitet liegengebliebene vollständige *.kaanzeige-Dateien."""
    try:
        for package_path in _import_file_paths():
            _handle_arrived_import(package_path)
    except Exception as exc:
        print(f"[media-import] Sicherheits-Scan fehlgeschlagen: {exc}", flush=True)


def _retry_drive_cleanup_sidecars():
    """Retry nur für bereits erfolgreich importierte Drive-Dateien; niemals erneut importieren."""
    try:
        for sidecar in IMPORT_DIR.iterdir():
            if not sidecar.is_file() or not sidecar.name.startswith(".") or not sidecar.name.endswith(DRIVE_META_SUFFIX):
                continue
            try:
                meta = json.loads(sidecar.read_text("utf-8"))
            except Exception:
                continue
            if not isinstance(meta, dict) or not meta.get("imported"):
                continue
            file_id = str(meta.get("drive_file_id") or "").strip()
            if not file_id:
                continue
            try:
                session = _google_drive_session()
                cleaned, cleanup_mode, cleanup_note = _google_drive_cleanup_source(session, file_id)
            except Exception as exc:
                cleaned, cleanup_mode, cleanup_note = False, "", str(exc)
            if cleaned:
                sidecar.unlink(missing_ok=True)
                _google_drive_state_update(
                    last_cleanup_mode=cleanup_mode,
                    last_cleanup_note=cleanup_note,
                    last_error="",
                )
    except Exception as exc:
        print(f"[google-drive-import] Cleanup-Retry fehlgeschlagen: {exc}", flush=True)


def _linux_inotify_fd(path):
    """Erzeugt einen Linux-inotify-Watch ohne zusätzliche Python-Abhängigkeit."""
    libc = ctypes.CDLL(None, use_errno=True)
    init1 = libc.inotify_init1
    init1.argtypes = [ctypes.c_int]
    init1.restype = ctypes.c_int
    add_watch = libc.inotify_add_watch
    add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    add_watch.restype = ctypes.c_int

    flags = os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    fd = init1(flags)
    if fd < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    wd = add_watch(fd, os.fsencode(str(path)), IMPORT_WATCH_MASK)
    if wd < 0:
        err = ctypes.get_errno()
        os.close(fd)
        raise OSError(err, os.strerror(err))
    return fd


def _media_import_watch_loop():
    """Importiert neue .kaanzeige sofort nach vollständig abgeschlossenem Dateitransfer."""
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Direkt beim Start liegengebliebene Dateien übernehmen.
    time.sleep(2)
    _scan_pending_imports_for_watcher()
    _mark_runtime_health("imports", ok=True, message="Dateiwächter aktiv")

    while True:
        fd = None
        try:
            fd = _linux_inotify_fd(IMPORT_DIR)
            print(f"[media-import] Dateiwächter aktiv: {IMPORT_DIR}", flush=True)
            last_safety_scan = time.monotonic()
            while True:
                ready, _, _ = select.select([fd], [], [], 10)
                if ready:
                    raw = os.read(fd, 65536)
                    offset = 0
                    while offset + 16 <= len(raw):
                        _wd, mask, _cookie, name_len = struct.unpack_from("iIII", raw, offset)
                        offset += 16
                        name_raw = raw[offset:offset + name_len]
                        offset += name_len
                        name = name_raw.split(b"\\0", 1)[0].decode("utf-8", "surrogateescape")

                        if mask & IN_Q_OVERFLOW:
                            _scan_pending_imports_for_watcher()
                            continue
                        if mask & (IN_DELETE_SELF | IN_MOVE_SELF):
                            raise RuntimeError("Importordner-Watch wurde ungültig und wird neu aufgebaut.")
                        if not name or not name.lower().endswith(IMPORT_EXTENSION):
                            continue
                        if mask & (IN_MOVED_TO | IN_CLOSE_WRITE):
                            _handle_arrived_import(IMPORT_DIR / name)

                # Sicherheits-Scan alle 5 Sekunden: falls ein Mount einmal kein
                # inotify-Ereignis liefert, bleibt der Import trotzdem schnell.
                if time.monotonic() - last_safety_scan >= 5:
                    _scan_pending_imports_for_watcher()
                    _retry_drive_cleanup_sidecars()
                    _mark_runtime_health("imports", ok=True, message="Dateiwächter aktiv")
                    last_safety_scan = time.monotonic()

        except Exception as exc:
            _mark_runtime_health("imports", ok=False, message=str(exc))
            print(f"[media-import] inotify nicht verfügbar/unterbrochen: {exc}; Fallback-Scan aktiv.", flush=True)
            # Robuster Fallback, falls der Mount keine inotify-Ereignisse liefert.
            for _ in range(5):
                _scan_pending_imports_for_watcher()
                _retry_drive_cleanup_sidecars()
                time.sleep(2)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass

def _import_status_for_ui(state=None):
    state = state or _load_state()
    import_state = state.get("imports", {}) if isinstance(state.get("imports", {}), dict) else {}
    last_run = _iso_dt(import_state.get("last_run_at"))
    return {
        "path": "media/Import/Kleinanzeigen",
        "pending_files": _count_import_files(),
        "last_run_label": last_run.astimezone(_local_tz()).strftime("%d.%m.%Y %H:%M") if last_run else "noch nicht geprüft",
        "last_imported": int(import_state.get("last_imported") or 0),
        "last_failed": int(import_state.get("last_failed") or 0),
        "last_trigger": import_state.get("last_trigger") or "",
    }


def _automatic_import_loop():
    # Nur noch Sicherheitsnetz. Der eigentliche Import erfolgt ereignisgesteuert
    # durch _media_import_watch_loop(), sobald eine vollständige Datei im Media-
    # Importordner auftaucht.
    time.sleep(60)
    while True:
        try:
            _scan_pending_imports_for_watcher()
            _retry_drive_cleanup_sidecars()
        except Exception as exc:
            print(f"[media-import] periodischer Sicherheitslauf fehlgeschlagen: {exc}", flush=True)
        time.sleep(max(300, IMPORT_INTERVAL_SECONDS))


# -- Google Drive -> Importordner -> Push -> Drive loeschen -> Import aktualisieren --

def _google_drive_state_update(**values):
    try:
        state = _load_state()
        drive_state = state.setdefault("google_drive_import", {})
        drive_state.update(values)
        _save_state(state)
    except Exception:
        pass


def _google_drive_session():
    if not GOOGLE_DRIVE_FOLDER_ID:
        raise RuntimeError("Google-Drive-Ordner-ID fehlt.")
    if not GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE.is_file():
        raise RuntimeError(f"Service-Account-Datei fehlt: {GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE}")
    credentials = service_account.Credentials.from_service_account_file(
        str(GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE),
        scopes=[GOOGLE_DRIVE_SCOPE],
    )
    return AuthorizedSession(credentials)


def _google_drive_list_packages(session):
    query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed = false"
    response = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": query,
            "spaces": "drive",
            "orderBy": "createdTime",
            "pageSize": "100",
            "fields": "files(id,name,mimeType,size,createdTime,modifiedTime)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=30,
    )
    response.raise_for_status()
    files = response.json().get("files") or []
    return [
        item for item in files
        if isinstance(item, dict)
        and str(item.get("name") or "").lower().endswith(IMPORT_EXTENSION)
        and item.get("id")
    ]


def _unique_import_target(filename):
    safe_name = Path(str(filename or "import.kaanzeige")).name
    if not safe_name.lower().endswith(IMPORT_EXTENSION):
        safe_name += IMPORT_EXTENSION
    target = IMPORT_DIR / safe_name
    if not target.exists():
        return target
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return IMPORT_DIR / f"{target.stem}-{stamp}{IMPORT_EXTENSION}"


def _google_drive_download_package(session, file_id, filename):
    """Transportiert eine Drive-Datei vollständig in den Media-Importordner.

    Wichtig: Der Import wird hier NICHT gestartet. Download erfolgt als versteckte
    .part-Datei. Erst os.replace(..., *.kaanzeige) erzeugt das Dateiwächter-Ereignis.
    """
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = _unique_import_target(filename)
    tmp = IMPORT_DIR / f".{target.name}.{uuid.uuid4().hex}.part"

    response = session.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        stream=True,
        timeout=120,
    )
    response.raise_for_status()
    try:
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())

        if not tmp.is_file() or tmp.stat().st_size <= 0:
            raise RuntimeError("Google-Drive-Datei wurde leer heruntergeladen.")

        # Sidecar muss VOR dem atomaren Rename existieren, damit der Watcher die
        # Herkunft sicher erkennt, selbst wenn er sofort auf IN_MOVED_TO reagiert.
        _write_drive_meta(target, {
            "drive_file_id": str(file_id),
            "drive_file_name": str(filename),
            "downloaded_at": _now(),
            "imported": False,
        })

        os.replace(tmp, target)
        return target
    except Exception:
        _remove_drive_meta(target)
        raise
    finally:
        try:
            response.close()
        except Exception:
            pass
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _google_drive_cleanup_source(session, file_id):
    """Bereinigt die Drive-Quelldatei nach erfolgreichem Import.

    Ein echtes files.delete bleibt der bevorzugte Weg. Bei Dateien, die einem
    anderen Google-Konto gehören, darf der Service Account sie häufig nicht
    endgültig löschen. In diesem Fall wird zuerst versucht, die Datei in den
    Papierkorb zu legen.

    Wichtig: Der Importordner-Parent wird niemals mehr alleine per
    removeParents entfernt. Bei einer fremdbesessenen My-Drive-Datei würde
    Google sie dadurch in den Hauptordner des Eigentümers verschieben. Falls
    weder Löschen noch Papierkorb erlaubt sind, bleibt die Datei deshalb sicher
    im Importordner. Ihre dauerhaft gespeicherte Drive-ID verhindert einen
    erneuten Import.
    """
    delete_error = ""
    try:
        response = session.delete(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"supportsAllDrives": "true"},
            timeout=30,
        )
        if response.status_code in (200, 204, 404):
            return True, "deleted", ""
        delete_error = f"HTTP {response.status_code}: {response.text[:300]}"
    except Exception as exc:
        delete_error = str(exc)

    trash_error = ""
    try:
        response = session.patch(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={
                "supportsAllDrives": "true",
                "fields": "id,parents,trashed",
            },
            json={"trashed": True},
            timeout=30,
        )
        if response.status_code in (200, 201):
            return True, "trashed", delete_error
        trash_error = f"HTTP {response.status_code}: {response.text[:300]}"
    except Exception as exc:
        trash_error = str(exc)

    # Sicherer letzter Fallback: Datei im überwachten Ordner belassen. Die
    # persistierte processed_file_id sperrt sie dauerhaft gegen Re-Import.
    # Insbesondere KEIN removeParents ohne addParents: das würde die Datei in
    # den My-Drive-Hauptordner des Eigentümers verschieben.
    return True, "retained_in_import_folder", (
        "Drive-Quelle konnte weder endgültig gelöscht noch in den Papierkorb "
        "verschoben werden und bleibt deshalb sicher im Importordner. "
        "Die gespeicherte Drive-ID verhindert einen erneuten Import. "
        f"Delete: {delete_error or 'unbekannt'}; Trash: {trash_error or 'unbekannt'}"
    )


def _google_drive_sync_once():
    """Google Drive ist nur Transportquelle; der Media-Dateiwächter importiert."""
    if not GOOGLE_DRIVE_IMPORT_ENABLED:
        return {"enabled": False, "transferred": 0}

    session = _google_drive_session()
    packages = _google_drive_list_packages(session)
    pending_ids = _pending_drive_file_ids()
    result = {"enabled": True, "found": len(packages), "transferred": 0, "errors": []}
    _google_drive_state_update(last_check_at=_now(), last_error="", found=len(packages))

    for item in packages:
        file_id = str(item.get("id") or "").strip()
        filename = Path(str(item.get("name") or "import.kaanzeige")).name
        if not file_id or file_id in pending_ids:
            continue
        try:
            local_path = _google_drive_download_package(session, file_id, filename)
            pending_ids.add(file_id)
            _google_drive_state_update(
                last_transfer_at=_now(),
                last_transferred_file=local_path.name,
                last_error="",
            )
            print(
                f"[google-drive-import] vollständig übertragen: {local_path.name}; Media-Watcher übernimmt Import.",
                flush=True,
            )
            result["transferred"] += 1
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            result["errors"].append({"file": filename, "error": message})
            _google_drive_state_update(last_error=message, last_error_at=_now())
            print(f"[google-drive-import] {filename}: {message}", flush=True)

    return result

def _google_drive_import_loop():
    # Etwas warten, bis Home Assistant / Netzwerk vollständig bereit sind.
    time.sleep(20)
    while True:
        try:
            _google_drive_sync_once()
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            _google_drive_state_update(last_error=message, last_error_at=_now())
            print(f"[google-drive-import] {message}", flush=True)
        time.sleep(GOOGLE_DRIVE_POLL_SECONDS)

# -- Bot Runner --

_bot_lock = threading.Lock()
_activity_browser_lock = threading.Lock()
_import_lock = threading.Lock()
_runtime_health_lock = threading.Lock()
_runtime_health = {}
_last_log = {"output": "", "running": False, "timestamp": ""}


def _mark_runtime_health(component, *, ok=True, message=""):
    with _runtime_health_lock:
        _runtime_health[str(component)] = {
            "ok": bool(ok),
            "updated_at": _now(),
            "message": str(message or "")[:300],
        }


def _runtime_health_snapshot():
    with _runtime_health_lock:
        return copy.deepcopy(_runtime_health)

def _try_reserve_bot_slot():
    """Reserve the one global bot slot without waiting.

    Publish/republish transactions reserve this *before* any destructive remote
    action.  A busy slot must never make a request silently wait while an old
    live ad has already been deleted.
    """
    if _last_log.get("running"):
        return False
    return _bot_lock.acquire(blocking=False)


def _release_bot_slot():
    try:
        _bot_lock.release()
    except RuntimeError:
        pass


def _retry_time_iso(seconds=BOT_SLOT_RETRY_SECONDS):
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))).isoformat()


def _queue_publish_retry(state, slug, meta, reason="Bot-Slot ist gerade belegt", *, history=True):
    first = not bool(_iso_dt(meta.get("publish_retry_at")))
    meta["publish_retry_at"] = _retry_time_iso()
    if history and first:
        meta.setdefault("history", []).append({
            "action": f"Veröffentlichung vorgemerkt: neuer Versuch in 1 Minute ({reason})",
            "date": _now(),
        })
    state.setdefault("ads", {})[slug] = meta
    return meta["publish_retry_at"]


def _queue_prestart_publish_retry(state, slug, meta, result, *, wait_message, origin_label="Veröffentlichung"):
    """Queue a bounded retry after a bot/login failure that happened before an ad.

    ``safe_retry`` means no publish click was reached.  It does not mean retry
    forever: the same visible operation is stopped after three attempts and its
    manager ZIP is named in the history.  The ZIP is written by ``_run_bot``
    before this helper is reached, so a restart of the scheduler cannot lose it.
    """
    operation = _operation_get(slug)
    attempt = int(operation.get("attempt") or 1)
    debug_zip = str((result or {}).get("debug_zip") or "").strip()
    debug_note = f" Diagnose: {Path(debug_zip).name}" if debug_zip else ""
    if attempt >= PUBLISH_PRESTART_RETRY_MAX:
        _clear_publish_retry(meta)
        meta.setdefault("history", []).append({
            "action": (
                f"{origin_label} sicher gestoppt: Bot/Login-Prüfung scheiterte vor der Anzeigenverarbeitung "
                f"in Versuch {attempt}/{PUBLISH_PRESTART_RETRY_MAX}.{debug_note}"
            ),
            "date": _now(),
        })
        _operation_failed(
            slug,
            f"Bot/Login-Prüfung vor der Anzeigenverarbeitung {attempt}× fehlgeschlagen. "
            "Keine weiteren automatischen Versuche; bitte Debug-ZIP prüfen.",
        )
        return None
    retry_at = _queue_publish_retry(state, slug, meta, "Bot/Login-Prüfung vor Anzeigenverarbeitung fehlgeschlagen")
    meta.setdefault("history", []).append({
        "action": (
            f"Bot/Login-Prüfung fehlgeschlagen; automatischer neuer Versuch {attempt + 1}/"
            f"{PUBLISH_PRESTART_RETRY_MAX} in 1 Minute.{debug_note}"
        ),
        "date": _now(),
    })
    _operation_wait(slug, wait_message, retry_at, retry_mode="publish")
    return retry_at


def _queue_republish_retry(state, slug, meta, reason="Bot-Slot ist gerade belegt", *, history=True):
    first = not bool(_iso_dt(meta.get("republish_retry_at")))
    meta["republish_retry_at"] = _retry_time_iso()
    if history and first:
        meta.setdefault("history", []).append({
            "action": f"Erneuern vorgemerkt: neuer Versuch in 1 Minute ({reason}); Live-Anzeige bleibt unverändert",
            "date": _now(),
        })
    state.setdefault("ads", {})[slug] = meta
    return meta["republish_retry_at"]


def _clear_publish_retry(meta):
    meta.pop("publish_retry_at", None)


def _clear_republish_retry(meta):
    meta.pop("republish_retry_at", None)


def _republish_transaction(meta):
    transaction = meta.get("republish_transaction")
    return transaction if isinstance(transaction, dict) else {}


def _mark_republish_delete_success(meta, old_remote_id):
    """Persist the destructive boundary before attempting the replacement publish."""
    meta["republish_transaction"] = {
        "schema": 1,
        "phase": "publish_pending",
        "old_remote_id": str(old_remote_id or ""),
        "before_live_ids": [str(old_remote_id or "")] if old_remote_id else [],
        "deleted_at": _now(),
        "publish_attempts": 0,
    }
    print(f"[republish] delete confirmed for old ID {old_remote_id}; publish-only transaction recorded.", flush=True)


def _clear_republish_transaction(meta):
    meta.pop("republish_transaction", None)


def _queue_publish_only_after_republish(state, slug, meta, reason):
    """Schedule a bounded, non-destructive retry after a confirmed delete."""
    transaction = _republish_transaction(meta)
    if not transaction:
        transaction = {"schema": 1, "phase": "publish_pending", "publish_attempts": 0}
        meta["republish_transaction"] = transaction
    attempts = max(0, int(transaction.get("publish_attempts") or 0)) + 1
    transaction["publish_attempts"] = attempts
    transaction["last_publish_error"] = str(reason)
    transaction["updated_at"] = _now()
    _clear_republish_retry(meta)
    if attempts > REPUBLISH_PUBLISH_RETRY_MAX:
        transaction["phase"] = "publish_failed"
        print(f"[republish] {slug}: publish-only retry limit reached after confirmed delete.", flush=True)
        return ""
    transaction["phase"] = "publish_retry_pending"
    retry_at = _queue_publish_retry(state, slug, meta, reason, history=False)
    meta.setdefault("history", []).append({
        "action": f"Alte Anzeige bestätigt gelöscht; nur Neuveröffentlichung erneut vorgemerkt ({attempts}/{REPUBLISH_PUBLISH_RETRY_MAX}): {reason}",
        "date": _now(),
    })
    print(f"[republish] {slug}: publish-only retry {attempts}/{REPUBLISH_PUBLISH_RETRY_MAX} at {retry_at}: {reason}", flush=True)
    return retry_at


def _migrate_republish_transactions():
    """Give pre-1.6.35 publish-only retries a durable transaction marker."""
    state = _load_state()
    migrations = state.setdefault("migrations", {})
    marker = "1.6.35-republish-transaction"
    if migrations.get(marker):
        return 0
    changed = 0
    for slug, meta in state.setdefault("ads", {}).items():
        if not isinstance(meta, dict) or _republish_transaction(meta):
            continue
        operation = _operation_get(slug)
        if (
            _iso_dt(meta.get("publish_retry_at"))
            and operation.get("action") == "republish"
            and operation.get("retry_mode") == "publish_only"
            and operation.get("old_live_deleted")
        ):
            meta["republish_transaction"] = {
                "schema": 1,
                "phase": "publish_retry_pending",
                "old_remote_id": "",
                "before_live_ids": [],
                "deleted_at": _now(),
                "publish_attempts": 0,
                "migrated_from": "1.6.34",
            }
            changed += 1
    migrations[marker] = _now()
    _save_state(state)
    if changed:
        print(f"[migration] {changed} bestehende Publish-only-Erneuerung(en) abgesichert.", flush=True)
    return changed


_OPERATION_ACTIVE_STATUSES = {"checking", "reserved", "waiting", "deleting", "publishing", "running"}
_OPERATION_TERMINAL_STATUSES = {"success", "failed", "cancelled"}
_OPERATION_KEEP_SECONDS = 24 * 3600


def _operation_label(action):
    return "Erneuern" if str(action or "") == "republish" else "Veröffentlichen"


def _operation_read_unlocked():
    if OPERATION_STATE_FILE.exists():
        try:
            data = json.loads(OPERATION_STATE_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                data.setdefault("operations", {})
                return data
        except Exception:
            pass
    return {"operations": {}}


def _operation_write_unlocked(data):
    OPERATION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OPERATION_STATE_FILE.with_suffix(OPERATION_STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, OPERATION_STATE_FILE)


def _operation_prune_unlocked(data):
    now = datetime.now(timezone.utc)
    ops = data.setdefault("operations", {})
    remove = []
    for slug, rec in ops.items():
        if not isinstance(rec, dict):
            remove.append(slug)
            continue
        if rec.get("status") not in {"success", "cancelled"}:
            # Fehlgeschlagene Vorgänge bleiben sichtbar, bis ein neuer Versuch
            # für dieselbe Anzeige beginnt und den Datensatz ersetzt.
            continue
        dt = _iso_dt(rec.get("terminal_at") or rec.get("updated_at"))
        if dt and (now - dt).total_seconds() > _OPERATION_KEEP_SECONDS:
            remove.append(slug)
    for slug in remove:
        ops.pop(slug, None)


def _operation_snapshot():
    with _operation_state_lock:
        data = _operation_read_unlocked()
        _operation_prune_unlocked(data)
        return copy.deepcopy(data)


def _operation_get(slug):
    data = _operation_snapshot()
    rec = data.get("operations", {}).get(slug)
    return copy.deepcopy(rec) if isinstance(rec, dict) else {}


def _operation_begin_attempt(slug, action, origin="manual", *, title="", account_id=None, retry_mode=None):
    """Start one visible attempt for publish/republish.

    Every real scheduler/manual retry increments the attempt number exactly once.
    Browser-internal recovery retries remain part of the same visible attempt.
    """
    now = _now()
    with _operation_state_lock:
        data = _operation_read_unlocked()
        _operation_prune_unlocked(data)
        ops = data.setdefault("operations", {})
        current = ops.get(slug) if isinstance(ops.get(slug), dict) else {}
        same_chain = (
            current.get("action") == action
            and current.get("status") in _OPERATION_ACTIVE_STATUSES
        )
        attempt = int(current.get("attempt") or 0) + 1 if same_chain else 1
        started_at = current.get("started_at") if same_chain else now
        rec = {
            "slug": slug,
            "action": action,
            "action_label": _operation_label(action),
            "origin": origin,
            "attempt": attempt,
            "status": "checking",
            "message": "Bot-Slot wird geprüft …",
            "next_retry_at": None,
            "started_at": started_at,
            "updated_at": now,
            "terminal_at": None,
            "title": str(title or current.get("title") or slug),
            "account_id": str(account_id or current.get("account_id") or ""),
            "account_name": str(current.get("account_name") or ""),
            "retry_mode": retry_mode if retry_mode is not None else current.get("retry_mode"),
            "old_live_deleted": bool(current.get("old_live_deleted")),
            "cancel_allowed": False,
        }
        ops[slug] = rec
        _operation_write_unlocked(data)
        return copy.deepcopy(rec)


def _operation_update(slug, **fields):
    now = _now()
    with _operation_state_lock:
        data = _operation_read_unlocked()
        ops = data.setdefault("operations", {})
        rec = ops.get(slug) if isinstance(ops.get(slug), dict) else {
            "slug": slug,
            "action": "publish",
            "action_label": "Veröffentlichen",
            "origin": "unknown",
            "attempt": 1,
            "started_at": now,
        }
        for key, value in fields.items():
            rec[key] = value
        rec["updated_at"] = now
        status = str(rec.get("status") or "")
        if status in _OPERATION_TERMINAL_STATUSES:
            rec["terminal_at"] = rec.get("terminal_at") or now
            rec["next_retry_at"] = None
            rec["cancel_allowed"] = False
        elif status == "waiting":
            if "cancel_allowed" not in fields:
                rec["cancel_allowed"] = True
        else:
            rec["cancel_allowed"] = False
        ops[slug] = rec
        _operation_prune_unlocked(data)
        _operation_write_unlocked(data)
        return copy.deepcopy(rec)


def _operation_wait(slug, message, next_retry_at, *, retry_mode=None, old_live_deleted=None, cancel_allowed=True):
    fields = {
        "status": "waiting",
        "message": str(message),
        "next_retry_at": next_retry_at,
        "cancel_allowed": bool(cancel_allowed),
    }
    if retry_mode is not None:
        fields["retry_mode"] = retry_mode
    if old_live_deleted is not None:
        fields["old_live_deleted"] = bool(old_live_deleted)
    return _operation_update(slug, **fields)


def _operation_success(slug, message):
    return _operation_update(slug, status="success", message=str(message), retry_mode=None)


def _operation_failed(slug, message):
    return _operation_update(slug, status="failed", message=str(message), retry_mode=None)


def _operation_cancelled(slug, message="Vorgang abgebrochen."):
    return _operation_update(slug, status="cancelled", message=str(message), retry_mode=None)


def _operation_existing_action_for_publish_retry(slug):
    rec = _operation_get(slug)
    if (
        rec.get("status") in _OPERATION_ACTIVE_STATUSES
        and rec.get("action") == "republish"
        and rec.get("retry_mode") == "publish_only"
    ):
        return "republish"
    return "publish"




def _cleanup_stale_retry_markers():
    """Remove retry markers that can no longer be valid.

    A queued publish becomes obsolete once the ad is online again; a queued
    republish becomes obsolete once the ad is offline/paused. Without this
    reconciliation a stale browser tab or an external/manual change could leave
    a visible "wartet auf Versuch" status forever although the scheduler will
    correctly no longer pick the ad up.
    """
    state = _load_state()
    changed = False
    cancelled = []
    for slug, meta in list(state.setdefault("ads", {}).items()):
        if not isinstance(meta, dict):
            continue
        ad = _read_ad_yaml(slug) or {}
        exists = bool(ad)
        active = bool(exists and ad.get("active", True))
        online = bool(meta.get("last_published") or ad.get("id"))
        if meta.get("publish_retry_at") and (not active or online):
            _clear_publish_retry(meta)
            changed = True
            cancelled.append((slug, "Veröffentlichungs-Warteschlange beendet: Anzeige ist bereits online oder nicht mehr aktiv."))
        if meta.get("republish_retry_at") and (not active or not online):
            _clear_republish_retry(meta)
            changed = True
            cancelled.append((slug, "Erneuern-Warteschlange beendet: Anzeige ist nicht mehr online oder nicht mehr aktiv."))
        state.setdefault("ads", {})[slug] = meta
    if changed:
        _save_state(state)
    for slug, message in cancelled:
        rec = _operation_get(slug)
        if rec.get("status") in _OPERATION_ACTIVE_STATUSES:
            _operation_cancelled(slug, message)
    return changed

def _operation_status_payload():
    snapshot = _operation_snapshot()
    now = datetime.now(timezone.utc)
    operations = {}
    for slug, rec in snapshot.get("operations", {}).items():
        if not isinstance(rec, dict):
            continue
        item = copy.deepcopy(rec)
        retry_dt = _iso_dt(item.get("next_retry_at"))
        item["retry_seconds"] = max(0, int((retry_dt - now).total_seconds())) if retry_dt else None
        operations[slug] = item

    bot = copy.deepcopy(_last_log)
    bot_slug = str(bot.get("slug") or "")
    if bot.get("running") and bot_slug and bot_slug in operations:
        op = operations[bot_slug]
        bot["operation_action"] = op.get("action")
        bot["operation_label"] = op.get("action_label")
        bot["attempt"] = op.get("attempt")
        bot["title"] = op.get("title") or bot.get("title")
        bot["account_name"] = op.get("account_name") or bot.get("account_name")
    active = [rec for rec in operations.values() if rec.get("status") in _OPERATION_ACTIVE_STATUSES]
    return {
        "bot": bot,
        "operations": operations,
        "active_count": len(active),
        "server_time": now.isoformat(),
    }


def _publish_submission_uncertain_text(raw_output):
    """Erkennt einen Submit, den der Bot nicht mehr abschließend bestätigen konnte.

    In diesem Zustand ist ein zweiter Publish zu riskant, ein endgültiger Fehler
    aber ebenfalls verfrüht, weil Kleinanzeigen die Anzeige bereits angenommen
    haben kann.
    """
    text = str(raw_output or "")
    return bool(
        re.search(r"reached submit boundary but failed", text, flags=re.IGNORECASE)
        or re.search(r"submission may have succeeded", text, flags=re.IGNORECASE)
        or re.search(r"Manual recovery required", text, flags=re.IGNORECASE)
        or "PublishSubmissionUncertainError" in text
        or re.search(r"\b(?:request |connection )?timed?\s*out\b", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:connection reset|connection aborted|network error|socket hang up)\b", text, flags=re.IGNORECASE)
    )


def _publish_result_requires_manual_review(result):
    """True once a submit may have reached Kleinanzeigen but is not confirmed.

    Retrying that state could create a duplicate listing, so callers must stop
    their publish-only retry chains rather than treating it like a login error.
    """
    result = result or {}
    return bool(result.get("no_retry") and result.get("uncertain_submit"))


def _confirmed_publish_remote_id(raw_output):
    """Return Kleinanzeigen' explicit published-ad ID from upstream output.

    Current kleinanzeigen-bot versions can publish an ad successfully and only
    then fail while cleaning up the old page/session. The success line is a
    stronger proof than the subsequent process exit code; it contains the
    remote ID assigned by Kleinanzeigen itself.
    """
    matches = list(re.finditer(
        r"\bSUCCESS:\s*ad\s+published\s+with\s+ID\s+([0-9]+)\b",
        str(raw_output or ""),
        flags=re.IGNORECASE,
    ))
    return matches[-1].group(1) if matches else ""


def _bot_command_result(command, returncode, raw_output):
    """Interpret the bot result semantically, not only via its process exit code.

    kleinanzeigen-bot can exit with code 0 even when an individual publish failed
    after all retries.  In that case the manager must never mark the local ad as
    published.  The final DONE summary is authoritative for a publish run.
    """
    confirmed_remote_id = _confirmed_publish_remote_id(raw_output) if command == "publish" else ""
    if confirmed_remote_id:
        # A navigation timeout after this line is cleanup-only: publishing is
        # already confirmed by Kleinanzeigen and must be linked, not retried.
        if returncode != 0:
            return True, (
                "Kleinanzeigen hat die Anzeige vor dem nachgelagerten Bot-Fehler "
                f"bereits bestätigt (ID {confirmed_remote_id})."
            )
        return True, ""

    if returncode != 0:
        return False, f"Bot-Prozess wurde mit Exit-Code {returncode} beendet."

    if command != "publish":
        return True, ""

    text = str(raw_output or "")
    summaries = list(re.finditer(
        r"DONE:\s*\(Re-\)published\s+(\d+)\s+ads(?:\s*\((\d+)\s+failed after retries\))?",
        text,
        flags=re.IGNORECASE,
    ))
    if summaries:
        match = summaries[-1]
        published = int(match.group(1) or 0)
        failed = int(match.group(2) or 0)
        if published < 1 or failed > 0:
            if _publish_submission_uncertain_text(text):
                return False, (
                    "Der Bot konnte den Absendevorgang nicht abschließend bestätigen. "
                    "Der Manager prüft jetzt den Live-Status, bevor der Vorgang als Fehler gewertet wird."
                )
            return False, (
                "Bot-Prozess endete zwar technisch erfolgreich, aber die "
                f"Veröffentlichungszusammenfassung meldet {published} erfolgreich / {failed} fehlgeschlagen."
            )
        return True, ""

    # Defensive fallback for upstream output variants without a parsable DONE line.
    if re.search(r"\[ERROR\].*All\s+\d+\s+attempts failed", text, flags=re.IGNORECASE):
        return False, "Der Bot meldet, dass alle Veröffentlichungsversuche fehlgeschlagen sind."
    if re.search(r"\b0\s+ads\b.*failed", text, flags=re.IGNORECASE | re.DOTALL):
        return False, "Der Bot meldet keine erfolgreich veröffentlichte Anzeige."

    return True, ""


def _repair_technical_day_postponements():
    """Undo 1.6.24 day-long postponements caused by technical capacity reads.

    1.6.24 treated an unavailable/unknown 30-day activity count exactly like a
    confirmed 100/100 limit and moved automatic work to the next day. On upgrade
    we convert only recent, clearly technical postponements into the normal
    60-second retry. Confirmed numeric limits and user-chosen schedules are left
    untouched.
    """
    state = _load_state()
    migrations = state.setdefault("migrations", {})
    marker = "1.6.25-technical-day-postpone-repair"
    if migrations.get(marker):
        return 0

    now = datetime.now(timezone.utc)
    repairs = []

    def recent_technical_reason(meta, prefix):
        for entry in reversed(list(meta.get("history") or [])[-12:]):
            action = str((entry or {}).get("action") or "")
            if not action.startswith(prefix):
                continue
            reason = action[len(prefix):].strip()
            dt = _iso_dt((entry or {}).get("date"))
            if dt and abs((now - dt).total_seconds()) > 48 * 3600:
                return ""
            if _capacity_failure_kind(False, None, reason) == "technical":
                return reason
            return ""
        return ""

    for slug, meta in list(state.setdefault("ads", {}).items()):
        if not isinstance(meta, dict):
            continue
        ad = _read_ad_yaml(slug) or {}
        if not ad or not ad.get("active", True):
            continue

        republish_until = _iso_dt(meta.get("republish_postponed_until"))
        republish_reason = recent_technical_reason(meta, "Erneuern um 1 Tag verschoben:")
        if (
            republish_until and republish_until > now
            and republish_until <= now + timedelta(hours=26)
            and republish_reason
            and bool(meta.get("last_published") or ad.get("id"))
        ):
            meta.pop("republish_postponed_until", None)
            retry_at = _queue_republish_retry(
                state, slug, meta,
                "technische 24h-Verschiebung aus 1.6.24 korrigiert",
                history=False,
            )
            meta.setdefault("history", []).append({
                "action": "Technische 24h-Verschiebung korrigiert: Erneuern wird in 1 Minute erneut versucht",
                "date": _now(),
            })
            repairs.append((slug, "republish", retry_at, str(ad.get("title") or slug)))
            continue

        scheduled_at = _iso_dt(meta.get("scheduled_publish_at"))
        publish_reason = recent_technical_reason(meta, "Veröffentlichung um 1 Tag verschoben:")
        if (
            scheduled_at and scheduled_at > now
            and scheduled_at <= now + timedelta(hours=26)
            and publish_reason
            and not bool(meta.get("last_published") or ad.get("id"))
        ):
            retry_at = _queue_publish_retry(
                state, slug, meta,
                "technische 24h-Verschiebung aus 1.6.24 korrigiert",
                history=False,
            )
            meta.setdefault("history", []).append({
                "action": "Technische 24h-Verschiebung korrigiert: Veröffentlichung wird in 1 Minute erneut versucht",
                "date": _now(),
            })
            repairs.append((slug, "publish", retry_at, str(ad.get("title") or slug)))

    migrations[marker] = _now()
    _save_state(state)

    for slug, action, retry_at, title in repairs:
        _operation_begin_attempt(
            slug, action, "migration", title=title,
            retry_mode="republish" if action == "republish" else "publish",
        )
        _operation_wait(
            slug,
            (
                "Technische 24h-Verschiebung aus 1.6.24 korrigiert – Live-Anzeige bleibt online; Erneuern in 60 Sekunden."
                if action == "republish"
                else "Technische 24h-Verschiebung aus 1.6.24 korrigiert – Veröffentlichung in 60 Sekunden."
            ),
            retry_at,
            retry_mode="republish" if action == "republish" else "publish",
            old_live_deleted=False,
        )

    if repairs:
        print(f"[retry-repair] {len(repairs)} technische 24h-Verschiebung(en) auf 60-Sekunden-Retry korrigiert.", flush=True)
    return len(repairs)


def _repair_false_publish_markers_from_recent_logs():
    """Repair 1.6.17 false-positive publish markers using persisted bot logs.

    Version 1.6.17 trusted the bot process exit code.  The upstream bot can exit
    with code 0 even when its final summary says that zero ads were published.
    Only recent logs with an explicit failed publish summary are considered, and
    only a local ad with the same title, no remote id and a matching recent
    last_published timestamp is repaired.
    """
    if not LOGS_DIR.is_dir():
        return 0

    state = _load_state()
    repaired = 0
    decrements = {}
    now_epoch = time.time()
    log_paths = sorted(LOGS_DIR.glob("*_publish.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:80]

    for log_path in log_paths:
        try:
            stat = log_path.stat()
            if now_epoch - stat.st_mtime > 24 * 3600:
                continue
            text = log_path.read_text("utf-8", errors="ignore")
        except Exception:
            continue

        failed_summary = bool(re.search(
            r"DONE:\s*\(Re-\)published\s+0\s+ads(?:\s*\([1-9]\d*\s+failed after retries\))?",
            text,
            flags=re.IGNORECASE,
        )) or bool(re.search(r"\[ERROR\].*All\s+\d+\s+attempts failed", text, flags=re.IGNORECASE))
        if not failed_summary:
            continue

        titles = re.findall(r"(?:Processing\s+\d+/\d+:\s+|Publishing ad\s+)\[([^\]]+)\]", text)
        for title in dict.fromkeys(titles):
            title_key = _normalize_link_title(title)
            if not title_key:
                continue
            for ad_path in ADS_DIR.glob("*.yaml"):
                slug = ad_path.stem
                ad = _read_ad_yaml(slug) or {}
                if str(ad.get("id") or "").strip():
                    continue
                if _normalize_link_title(ad.get("title")) != title_key:
                    continue
                meta = state.setdefault("ads", {}).setdefault(slug, {})
                published_dt = _iso_dt(meta.get("last_published"))
                if not published_dt:
                    continue
                try:
                    published_epoch = published_dt.timestamp()
                except Exception:
                    continue
                # The false local success marker is written immediately after this bot run.
                if abs(published_epoch - stat.st_mtime) > 2 * 3600:
                    continue
                history = list(meta.get("history") or [])
                if not history:
                    continue
                latest_action = str(history[-1].get("action") or "").lower()
                if "veröffentlicht" not in latest_action and "veroeffentlicht" not in latest_action:
                    continue

                meta["last_published"] = None
                meta["publish_count"] = max(0, int(meta.get("publish_count") or 0) - 1)
                meta.setdefault("history", []).append({
                    "action": "Fehlmarkierung korrigiert: Bot-Protokoll meldete 0 veröffentlichte Anzeigen",
                    "date": _now(),
                })
                account_id = _ad_account_id(slug, meta, state)
                decrements[account_id] = decrements.get(account_id, 0) + 1
                repaired += 1

    for account_id, count in decrements.items():
        _increment_activity_posted_count(account_id, -count, state)
        activity = state.get("account_activity_by_account", {}).get(account_id)
        if isinstance(activity, dict) and activity.get("posted_last_30_days") is not None:
            activity["posted_last_30_days"] = max(0, int(activity.get("posted_last_30_days") or 0))
        if account_id == MAIN_ACCOUNT_ID and isinstance(state.get("account_activity"), dict):
            state["account_activity"]["posted_last_30_days"] = max(0, int(state["account_activity"].get("posted_last_30_days") or 0))

    if repaired:
        _save_state(state)
        print(f"[publish-repair] {repaired} falsche Veröffentlichungsmarkierung(en) aus Bot-Protokollen korrigiert.", flush=True)
    return repaired


def _repair_recent_safe_orphaned_republish():
    """Resume recent republish jobs that 1.6.24 abandoned after deleting live ads.

    The repair is deliberately narrow: the local ad must be offline, history must
    show that the manager deleted the old live ID and then recorded a republish
    failure, and a recent persisted publish log for the same slug must prove that
    the bot failed *before* ``Processing``/``Publishing ad``. Only then is a
    publish-only retry safe and cannot repeat the remote delete step.
    """
    state = _load_state()
    migrations = state.setdefault("migrations", {})
    marker = "1.6.25-safe-orphaned-republish-repair"
    if migrations.get(marker):
        return 0
    if not LOGS_DIR.is_dir():
        migrations[marker] = _now()
        _save_state(state)
        return 0

    now_epoch = time.time()
    recent_logs = []
    for log_path in sorted(LOGS_DIR.glob("*_publish.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:120]:
        try:
            if now_epoch - log_path.stat().st_mtime > 48 * 3600:
                continue
            recent_logs.append((log_path, log_path.read_text("utf-8", errors="ignore")))
        except Exception:
            continue

    repairs = []
    for slug, meta in list(state.setdefault("ads", {}).items()):
        if not isinstance(meta, dict):
            continue
        ad = _read_ad_yaml(slug) or {}
        if not ad or not ad.get("active", True):
            continue
        if meta.get("last_published") or ad.get("id") or _iso_dt(meta.get("publish_retry_at")):
            continue

        history = list(meta.get("history") or [])
        delete_idx = -1
        failure_idx = -1
        for i, entry in enumerate(history[-20:]):
            action = str((entry or {}).get("action") or "").lower()
            if "alte live-id" in action and "direkt gelöscht" in action:
                delete_idx = i
            if "fehler beim republish" in action or "fehler bei automatischem erneuern" in action or "fehler beim erneuern" in action:
                failure_idx = i
        if delete_idx < 0 or failure_idx <= delete_idx:
            continue

        safe_log = None
        for log_path, text in recent_logs:
            if slug not in text:
                continue
            m = re.search(r"Return code:\s*(-?\d+)", text)
            returncode = int(m.group(1)) if m else 1
            if _is_pre_browser_start_failure(returncode, text):
                safe_log = log_path
                break
        if safe_log is None:
            continue

        meta.pop("republish_postponed_until", None)
        _clear_republish_retry(meta)
        retry_at = _queue_publish_retry(
            state, slug, meta,
            "sicherer Publish-only-Retry nach abgebrochenem Erneuern aus 1.6.24",
            history=False,
        )
        meta.setdefault("history", []).append({
            "action": "Abgebrochenes Erneuern korrigiert: alte Anzeige war bereits gelöscht; nur Neuveröffentlichung wird in 1 Minute erneut versucht",
            "date": _now(),
        })
        repairs.append((slug, retry_at, str(ad.get("title") or slug), safe_log.name))

    migrations[marker] = _now()
    _save_state(state)

    for slug, retry_at, title, log_name in repairs:
        _operation_begin_attempt(
            slug, "republish", "migration", title=title, retry_mode="publish_only"
        )
        _operation_wait(
            slug,
            "Alte Live-Anzeige war bereits gelöscht; sicherer Login/Bot-Fehler aus 1.6.24 erkannt – nur Neuveröffentlichung in 60 Sekunden.",
            retry_at,
            retry_mode="publish_only",
            old_live_deleted=True,
        )
        print(f"[retry-repair] Publish-only für {slug} aus {log_name} vorgemerkt.", flush=True)

    return len(repairs)


def _browser_profile_from_config(config_path):
    """Return the account-specific Chromium profile configured for this bot run.

    The single-ad config is authoritative here because main and secondary accounts
    use different workspaces.  Never guess a profile from the ad itself.
    """
    try:
        cfg = yaml.safe_load(Path(config_path).read_text("utf-8")) or {}
        browser = cfg.get("browser") if isinstance(cfg.get("browser"), dict) else {}
        raw = str(browser.get("user_data_dir") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = Path(config_path).resolve().parent / path
        return path.resolve()
    except Exception:
        return None


def _prepare_browser_profile_for_bot(config_path, wait_seconds=3.0):
    """Make one account profile safe for a new bot process.

    A previous nodriver/Chromium process can outlive the Python bot for a short
    period.  Starting the next bot immediately then fails before any ad is
    processed with "Failed to connect to browser".  We first allow a graceful
    exit, then stop only processes explicitly using this exact profile, and only
    after no such process remains remove Chromium's Singleton* lock artefacts.
    Cookies and all other session data are deliberately untouched.
    """
    profile_dir = _browser_profile_from_config(config_path)
    if profile_dir is None:
        return []

    profile_dir.mkdir(parents=True, exist_ok=True)
    notes = []

    # A manual noVNC login may still own this profile.  Stop that session cleanly
    # instead of killing Chromium behind noVNC and leaving a black screen.
    try:
        if _vnc_account_id is not None and _vnc_running():
            vnc_profile = _account_profile_dir(_vnc_account_id).resolve()
            if vnc_profile == profile_dir:
                _stop_vnc()
                notes.append("aktive Browser-Login-Session beendet")
    except Exception:
        pass

    deadline = time.time() + max(0.0, float(wait_seconds))
    pids = _profile_chromium_pids(profile_dir)
    while pids and time.time() < deadline:
        time.sleep(0.15)
        pids = _profile_chromium_pids(profile_dir)

    if pids:
        stopped = _terminate_profile_chromium(profile_dir)
        if stopped:
            notes.append("hängenden Chromium-Prozess des Kontos beendet")
        # Give SIGTERM/SIGKILL cleanup a short moment before touching locks.
        end = time.time() + 1.0
        while _profile_chromium_pids(profile_dir) and time.time() < end:
            time.sleep(0.1)

    remaining = _profile_chromium_pids(profile_dir)
    if remaining:
        raise RuntimeError(
            "Browserprofil ist weiterhin in Benutzung (PID "
            + ", ".join(str(pid) for pid in remaining)
            + "). Veröffentlichung wurde nicht gestartet."
        )

    removed = _clear_stale_chromium_profile_locks(profile_dir)
    if removed:
        notes.append("verwaisten Browser-Lock entfernt")
    return notes


def _is_pre_browser_start_failure(returncode, raw_output):
    """True for transient browser/login failures before ad processing began.

    A retry is safe only while the bot has not reached ``Processing``/``Publishing ad``.
    This includes the Chromium start/connect errors handled since 1.6.21 and, since
    1.6.25, navigation/login page-load timeouts such as
    ``TimeoutError: Page did not finish loading within ...``. Once ad processing has
    started we never replay automatically because the remote submit may already have
    happened.
    """
    text = str(raw_output or "")
    if int(returncode or 0) == 0:
        return False
    touched_ad = bool(re.search(r"\bProcessing\s+\d+/\d+:|Publishing ad\s+\[", text, flags=re.IGNORECASE))
    if touched_ad:
        return False
    transient_pre_ad = (
        "Failed to start browser" in text
        or "Failed to connect to browser" in text
        or "TimeoutError:" in text
        or "Page did not finish loading" in text
        or "Timeout navigating to SSO login page" in text
    )
    return transient_pre_ad


def _make_bot_retry_profile(config_path):
    """Clone the configured account profile for one safe browser-start retry.

    If Chromium cannot open the persistent profile even after stale-lock cleanup,
    retrying the exact same profile is not useful.  A short-lived clone preserves
    cookies/login state while deliberately omitting process locks, DevTools state
    and caches.  The original account profile is never deleted or rewritten.
    """
    config_path = Path(config_path)
    source_profile = _browser_profile_from_config(config_path)
    if source_profile is None:
        raise RuntimeError("Browserprofil konnte für den sicheren Ersatzstart nicht ermittelt werden.")

    source_profile.mkdir(parents=True, exist_ok=True)
    temp_parent = source_profile.parent
    temp_parent.mkdir(parents=True, exist_ok=True)
    retry_profile = Path(tempfile.mkdtemp(prefix="bot-retry-profile-", dir=str(temp_parent)))
    retry_config = None
    ignore = shutil.ignore_patterns(
        "SingletonLock", "SingletonSocket", "SingletonCookie", "DevToolsActivePort",
        "Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
        "DawnCache", "Crashpad", "BrowserMetrics*",
    )
    try:
        if source_profile.exists():
            shutil.copytree(
                source_profile,
                retry_profile,
                dirs_exist_ok=True,
                symlinks=False,
                ignore=ignore,
            )
        _clear_stale_chromium_profile_locks(retry_profile)

        cfg = yaml.safe_load(config_path.read_text("utf-8")) or {}
        browser = cfg.setdefault("browser", {})
        if not isinstance(browser, dict):
            browser = {}
            cfg["browser"] = browser
        browser["user_data_dir"] = str(retry_profile)

        fd, tmp_name = tempfile.mkstemp(
            prefix=".browser-retry-",
            suffix=".yaml",
            dir=str(config_path.parent),
        )
        os.close(fd)
        retry_config = Path(tmp_name)
        retry_config.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), "utf-8")
        return retry_profile, retry_config
    except Exception:
        if retry_config is not None:
            try:
                retry_config.unlink(missing_ok=True)
            except Exception:
                pass
        shutil.rmtree(retry_profile, ignore_errors=True)
        raise


def _cleanup_bot_profile(config_path, wait_seconds=1.5):
    """Release Chromium leftovers after a bot process has exited.

    nodriver can finish its Python process before every Chromium child is gone.
    Waiting and then terminating only processes tied to the exact configured
    profile prevents the next publish from inheriting a locked profile.
    """
    profile_dir = _browser_profile_from_config(config_path)
    if profile_dir is None:
        return []
    notes = []
    deadline = time.time() + max(0.0, float(wait_seconds))
    while _profile_chromium_pids(profile_dir) and time.time() < deadline:
        time.sleep(0.1)
    if _profile_chromium_pids(profile_dir):
        if _terminate_profile_chromium(profile_dir):
            notes.append("Chromium-Restprozess nach Bot-Ende beendet")
    if not _profile_chromium_pids(profile_dir):
        if _clear_stale_chromium_profile_locks(profile_dir):
            notes.append("Browser-Lock nach Bot-Ende entfernt")
    return notes


def _debug_redact_runtime_text(value):
    """Remove credentials/session-like material from manager-side watchdog output."""
    text = str(value or "")
    # Email addresses are login identifiers and are not needed for publish diagnosis.
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<redacted-email>", text)
    text = re.sub(
        r'''(?i)((?:["']?(?:password|passwort|authorization|cookie|access[_-]?token|refresh[_-]?token|csrf|secret|session[_-]?id)["']?)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''',
        lambda match: match.group(1) + '"<redacted>"',
        text,
    )
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer <redacted>", text)
    return text


def _debug_sanitize_value(value, key=""):
    """Return useful diagnostics without configuration or runtime secrets."""
    key_text = str(key or "")
    if re.search(r"(?i)(password|passwort|email|mail|token|secret|cookie|session|authorization|user_data_dir|profile|storage)", key_text):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(name): _debug_sanitize_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_debug_sanitize_value(item, key_text) for item in value]
    if isinstance(value, tuple):
        return [_debug_sanitize_value(item, key_text) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _debug_redact_runtime_text(value) if isinstance(value, str) else value
    return _debug_redact_runtime_text(repr(value))


def _manager_browser_process_status():
    """Collect process state only; never copy Chromium command lines or profiles."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,stat=,comm="], capture_output=True, text=True, timeout=2,
        )
        rows = []
        for line in str(result.stdout or "").splitlines():
            fields = line.split()
            if len(fields) >= 4 and any("chrom" in part.lower() for part in fields[3:]):
                rows.append({"pid": fields[0], "ppid": fields[1], "state": fields[2], "process": fields[3]})
        return {"available": True, "chromium_processes": rows[:80]}
    except Exception as exc:
        return {"available": False, "error": _debug_redact_runtime_text(exc)}


def _manager_log_tail():
    try:
        paths = sorted(LOGS_DIR.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not paths:
            return ""
        return _debug_redact_runtime_text(paths[0].read_text("utf-8", errors="replace")[-100_000:])
    except Exception as exc:
        return "[manager] Log-Ausschnitt nicht verfügbar: " + _debug_redact_runtime_text(exc)


def _write_manager_failure_debug(command, context=None, *, phase, reason, output="", config_path=None,
                                 returncode=None, timeout_seconds=None, signal_name=""):
    """Atomically create a sanitized manager-level diagnostic ZIP.

    It intentionally does not connect to Chromium or inspect its profile: both may
    be stuck and profiles contain session data.  The process snapshot records what
    the manager can safely observe; URL/DOM/screenshot collection stays reserved
    for the bot's in-process diagnostic hook when a browser session is reachable.
    """
    try:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(APP_TZ).strftime("%Y%m%dT%H%M%S")
        safe_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str((context or {}).get("slug") or "publish")).strip("-._")[:70] or "publish"
        target = DIAGNOSTICS_DIR / f"kleinanzeigen-manager-debug_{stamp}_{safe_slug}_FEHLER.zip"
        temporary = target.with_suffix(".zip.partial")
        if temporary.exists():
            temporary.unlink()
        context = dict(context or {})
        slug = str(context.get("slug") or "")
        ad = _read_ad_yaml(slug) if slug else {}
        state = _load_state()
        operation = _operation_get(slug) if slug else {}
        config = {}
        if config_path:
            try:
                config = yaml.safe_load(Path(config_path).read_text("utf-8")) or {}
            except Exception as exc:
                config = {"read_error": _debug_redact_runtime_text(exc)}
        clean_context = {
            "slug": slug,
            "title": str(context.get("title") or ""),
            "command": str(command or ""),
            "phase": str(phase),
            "reason": _debug_redact_runtime_text(reason),
            "returncode": returncode,
            "timeout_seconds": timeout_seconds,
            "signal": str(signal_name or ""),
            "captured_at": _now(),
        }
        summary = (
            f"Zeit: {_now()}\n"
            f"Befehl: {command}\n"
            f"Anzeige: {clean_context['title']}\n"
            f"Phase: {phase}\n"
            f"Fehler: {clean_context['reason']}\n"
            "Hinweis: Dieses Paket enthält weder Zugangsdaten, E-Mail-Anmeldung, Tokens, Cookies, Browserprofile noch Local Storage.\n"
            "URL/DOM/Screenshot: Nur der Bot kann sie in seiner aktiven Browser-Sitzung erfassen; der Manager greift nicht auf das Browserprofil zu.\n"
        )
        runtime = {
            "app_version": APP_VERSION,
            "python": sys.version,
            "platform": " ".join(os.uname()),
            "pid": os.getpid(),
            "captured_at": _now(),
        }
        manager_state = {
            "operation": operation,
            "ad_state": state.get("ads", {}).get(slug, {}) if slug else {},
            "last_bot_status": _last_log,
        }
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr("00-summary.txt", _debug_redact_runtime_text(summary))
            archive.writestr("01-manager-context.json", json.dumps(clean_context, ensure_ascii=False, indent=2))
            archive.writestr("02-manager-operation-state.json", json.dumps(_debug_sanitize_value(manager_state), ensure_ascii=False, indent=2))
            archive.writestr("03-sanitized-bot-config.json", json.dumps(_debug_sanitize_value(config), ensure_ascii=False, indent=2))
            archive.writestr("04-ad-data.json", json.dumps(_debug_sanitize_value(ad or {}), ensure_ascii=False, indent=2))
            archive.writestr("05-browser-process-status.json", json.dumps(_manager_browser_process_status(), ensure_ascii=False, indent=2))
            archive.writestr("06-runtime.json", json.dumps(runtime, ensure_ascii=False, indent=2))
            tail = _debug_redact_runtime_text((str(output or "") + "\n\n--- LOG TAIL ---\n" + _manager_log_tail())[-250_000:])
            if tail.strip():
                archive.writestr("07-bot-output-and-log-tail.txt", tail)
        os.replace(temporary, target)
        rows = sorted(DIAGNOSTICS_DIR.glob("kleinanzeigen-*-debug_*.zip"), key=lambda row: row.stat().st_mtime, reverse=True)
        rows += sorted(DIAGNOSTICS_DIR.glob("kleinanzeigen-manager-*.zip"), key=lambda row: row.stat().st_mtime, reverse=True)
        seen = set()
        ordered = []
        for row in sorted(rows, key=lambda item: item.stat().st_mtime, reverse=True):
            if row not in seen:
                seen.add(row)
                ordered.append(row)
        for row in ordered[10:]:
            try:
                row.unlink()
            except OSError:
                pass
        return target
    except Exception as error:
        print(f"[diagnostics] manager watchdog ZIP failed: {error}", flush=True)
        return None


def _write_manager_watchdog_debug(command, context, timeout_seconds, timeout_error):
    """Compatibility wrapper for the subprocess watchdog path."""
    output = _timeout_expired_output(timeout_error)
    return _write_manager_failure_debug(
        command, context, phase="subprocess-watchdog",
        reason=f"Bot-Prozess hat den Manager-Watchdog nach {int(timeout_seconds)} Sekunden überschritten.",
        output=output, timeout_seconds=int(timeout_seconds),
        signal_name="timeout-kill",
    )


def _timeout_expired_output(timeout_error):
    """Return partial subprocess output without losing the submit-boundary signal."""
    stdout = getattr(timeout_error, "stdout", "") or ""
    stderr = getattr(timeout_error, "stderr", "") or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    return str(stdout) + "\n" + str(stderr)


def _run_bot(command, ads=None, config_path=None, log_preamble="", slot_reserved=False, context=None):
    global _last_log
    acquired_here = False
    if not slot_reserved:
        acquired_here = _bot_lock.acquire(blocking=False)
        if not acquired_here:
            return {"ok": False, "output": "Bot-Slot ist gerade belegt.", "safe_retry": True}
    try:
        if _last_log.get("running"):
            return {"ok": False, "output": "Bot laeuft bereits.", "safe_retry": True}
        context = dict(context or {})
        _last_log = {
            "output": "",
            "running": True,
            "timestamp": _now_local(),
            "command": command,
            **context,
        }
        effective_config = Path(config_path) if config_path else BOT_CONFIG

        def build_cmd(cfg_path):
            cmd_local = ["python3", "-m", "kleinanzeigen_bot",
                         "--config", str(cfg_path),
                         "--workspace-mode=portable",
                         command]
            if ads:
                cmd_local.append("--ads=" + ads)
            return cmd_local

        cmd = build_cmd(effective_config)
        recovery_notes = []
        retry_profile = None
        retry_config = None
        try:
            recovery_notes.extend(_prepare_browser_profile_for_bot(effective_config))

            bot_timeout = PUBLISH_BOT_PROCESS_TIMEOUT_SECONDS if command == "publish" else 600
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=bot_timeout, cwd=str(effective_config.parent))
            stdout = result.stdout
            stderr = result.stderr
            raw_output = (stdout + "\n" + stderr).strip()
            recovery_notes.extend(_cleanup_bot_profile(effective_config))

            # A second attempt is safe only when the first browser never reached an ad.
            # Crucially, do NOT retry the same profile again.  Use a clean, disposable
            # clone of the logged-in account profile so stale runtime state cannot make
            # the retry identical to the failed first attempt.
            if _is_pre_browser_start_failure(result.returncode, raw_output):
                recovery_notes.append(
                    "Browserstart vor Anzeigenverarbeitung fehlgeschlagen; einmaliger Neustart mit sauberer Profilkopie"
                )
                retry_profile, retry_config = _make_bot_retry_profile(effective_config)
                retry_cmd = build_cmd(retry_config)
                first_output = raw_output
                time.sleep(0.4)
                retry = subprocess.run(
                    retry_cmd,
                    capture_output=True,
                    text=True,
                    timeout=bot_timeout,
                    cwd=str(effective_config.parent),
                )
                stdout = retry.stdout
                stderr = retry.stderr
                result = retry
                retry_raw = (stdout + "\n" + stderr).strip()
                recovery_notes.extend(_cleanup_bot_profile(retry_config, wait_seconds=0.8))
                raw_output = (
                    "[MANAGER] Erster Browserstart scheiterte vor der Anzeigenverarbeitung; "
                    "einmal mit einer sauberen Kopie des eingeloggten Browserprofils neu gestartet.\n"
                    "--- ERSTER BROWSERSTART ---\n" + first_output +
                    "\n--- PROFILKOPIE / EINMALIGER NEUSTART ---\n" + retry_raw
                )

            ok, semantic_error = _bot_command_result(command, result.returncode, raw_output)
            if semantic_error:
                raw_output = raw_output + "\n[MANAGER] " + semantic_error
            recovery_preamble = ""
            if recovery_notes:
                recovery_preamble = "[MANAGER] Browserprofil: " + "; ".join(dict.fromkeys(recovery_notes))
            combined_preamble = "\n".join(x for x in (log_preamble.rstrip(), recovery_preamble) if x)
            output = ((combined_preamble + "\n\n") if combined_preamble else "") + raw_output
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            log_path = LOGS_DIR / (ts + "_" + command + ".log")
            log_path.write_text(
                "Command: " + " ".join(cmd) + "\nReturn code: " + str(result.returncode) +
                (("\n\n--- PUBLISH IMAGE ORDER ---\n" + log_preamble.rstrip()) if log_preamble else "") +
                (("\n\n--- BROWSER PROFILE RECOVERY ---\n" + recovery_preamble) if recovery_preamble else "") +
                "\n\n--- STDOUT/RESULT ---\n" + raw_output +
                (("\n\n--- MANAGER RESULT ---\n" + semantic_error) if semantic_error else ""), "utf-8")
            safe_retry = bool((not ok) and _is_pre_browser_start_failure(result.returncode, raw_output))
            debug_zip = ""
            if not ok:
                debug = _write_manager_failure_debug(
                    command, context, phase="bot-result",
                    reason=semantic_error or "Bot-Prozess meldete einen Fehler.",
                    output=output, config_path=effective_config, returncode=result.returncode,
                    signal_name=(f"signal-{abs(result.returncode)}" if result.returncode < 0 else ""),
                )
                debug_zip = str(debug) if debug else ""
                if debug_zip:
                    output += f"\n[MANAGER] Debug-ZIP: {debug_zip}"
            _last_log = {"output": output, "running": False, "ok": ok, "command": command, "timestamp": _now_local(), **context}
            return {"ok": ok, "output": output, "safe_retry": safe_retry, "log_path": str(log_path), "debug_zip": debug_zip}
        except subprocess.TimeoutExpired as timeout_error:
            timeout_seconds = PUBLISH_BOT_PROCESS_TIMEOUT_SECONDS if command == "publish" else 600
            partial_output = _timeout_expired_output(timeout_error)
            uncertain_submit = command == "publish" and _publish_submission_uncertain_text(partial_output)
            debug_zip = _write_manager_watchdog_debug(command, context, timeout_seconds, timeout_error)
            debug_note = f" Debug-ZIP: {debug_zip}" if debug_zip else ""
            msg = f"Bot-Timeout nach {timeout_seconds} Sekunden; Prozess wurde beendet.{debug_note}"
            if uncertain_submit:
                msg += "\n[MANAGER] Der Bot erreichte vor dem Timeout den Absende-Schritt; Live-Status wird geprüft, kein erneutes Veröffentlichen."
            _last_log = {"output": msg, "running": False, "ok": False, "command": command, "timestamp": _now_local(), **context}
            return {
                "ok": False,
                "output": msg,
                "safe_retry": False,
                "uncertain_submit": uncertain_submit,
                "debug_zip": str(debug_zip) if debug_zip else "",
            }
        except Exception as e:
            msg = "Fehler vor/bei Bot-Start: " + str(e)
            debug = _write_manager_failure_debug(
                command, context, phase="manager-preflight", reason=msg,
                output=msg, config_path=effective_config,
            )
            debug_zip = str(debug) if debug else ""
            if debug_zip:
                msg += f" Debug-ZIP: {debug_zip}"
            try:
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                (LOGS_DIR / (ts + "_" + command + "_manager-preflight.log")).write_text(
                    "Command: " + " ".join(cmd) +
                    "\n\n--- MANAGER/PREFLIGHT ERROR ---\n" + msg +
                    (("\n\n--- PUBLISH IMAGE ORDER ---\n" + log_preamble.rstrip()) if log_preamble else ""),
                    "utf-8",
                )
            except Exception:
                pass
            _last_log = {"output": msg, "running": False, "ok": False, "command": command, "timestamp": _now_local(), **context}
            return {"ok": False, "output": msg, "safe_retry": True, "debug_zip": debug_zip}
        finally:
            # Best-effort cleanup must never hide the real bot result.
            try:
                recovery_notes.extend(_cleanup_bot_profile(effective_config, wait_seconds=0.3))
            except Exception:
                pass
            if retry_config is not None:
                try:
                    retry_config.unlink(missing_ok=True)
                except Exception:
                    pass
            if retry_profile is not None:
                try:
                    _terminate_profile_chromium(retry_profile)
                except Exception:
                    pass
                shutil.rmtree(retry_profile, ignore_errors=True)
    finally:
        if acquired_here:
            _release_bot_slot()


def _write_temp_bot_config_for_ad(slug, ad_path, account_id=MAIN_ACCOUNT_ID):
    account_id = _valid_account_id(account_id)
    cfg = _enable_run_diagnostics(_load_account_config(account_id))
    cfg["ad_files"] = [str(Path(ad_path).resolve())]
    workspace = _account_workspace(account_id)
    workspace.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".single-ad-{slug}-", suffix=".yaml", dir=str(workspace))
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
    return tmp_path


def _make_single_ad_config(slug, account_id=MAIN_ACCOUNT_ID):
    ad_path = _ad_yaml_path(slug)
    if not ad_path.exists():
        raise FileNotFoundError(f"Anzeige nicht gefunden: {slug}")
    return _write_temp_bot_config_for_ad(slug, ad_path, account_id)


def _prepare_publish_image_order_staging(slug, account_id=MAIN_ACCOUNT_ID, force_new=False):
    """Temporäre Anzeige mit harter Bildreihenfolge und Account-spezifischer Bot-Config."""
    ad = _read_ad_yaml(slug)
    if not ad:
        raise FileNotFoundError(f"Anzeige nicht gefunden: {slug}")

    ordered_names = _list_ad_images(slug)
    staging_root = DATA_DIR / "publish_staging" / f"{slug}-{uuid.uuid4().hex[:10]}"
    stage_ads_dir = staging_root / "ads"
    stage_images_dir = staging_root / "images" / slug
    stage_ads_dir.mkdir(parents=True, exist_ok=True)
    stage_images_dir.mkdir(parents=True, exist_ok=True)

    staged_names = []
    order_log = []
    for idx, image_name in enumerate(ordered_names, start=1):
        src = _ad_images_dir(slug) / image_name
        if not src.is_file():
            continue
        suffix = src.suffix.lower() or ".jpg"
        staged_name = f"{idx:02d}{suffix}"
        dst = stage_images_dir / staged_name
        shutil.copy2(src, dst)
        staged_names.append(staged_name)
        order_log.append(f"{idx:02d}: {image_name} -> {staged_name}")

    staged_ad = copy.deepcopy(ad)
    if force_new:
        for managed_key in ("id", "created_on_kleinanzeigen", "updated_at", "created_at"):
            staged_ad.pop(managed_key, None)
        order_log.append("Repost: alte Kleinanzeigen-ID nur in der Publish-Kopie entfernt.")
    if staged_names:
        staged_ad["images"] = [f"../images/{slug}/{name}" for name in staged_names]
    else:
        staged_ad.pop("images", None)
        order_log.append("Keine Bilder gefunden.")

    staged_ad_path = stage_ads_dir / f"{slug}.yaml"
    staged_ad_path.write_text(yaml.dump(staged_ad, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
    cfg_path = _write_temp_bot_config_for_ad(slug, staged_ad_path, account_id)

    preamble = f"Konto: {_account_name(account_id)}\nBildreihenfolge beim Veröffentlichen wurde fixiert:\n" + "\n".join(order_log)
    preamble += "\nDiagnose: Bei einem Fehler wird genau ein bereinigtes ZIP unter /share/Kleinanzeigen/debug erzeugt."
    return cfg_path, staging_root, preamble


def _normalized_live_text(value):
    """Vergleichswert ohne HTML- und Leerraum-Unterschiede der mobilen API."""
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _live_update_proof(before_ad, after_ad):
    """Nur wirklich geänderte und über die API eindeutig prüfbare Werte vormerken."""
    before_ad, after_ad = dict(before_ad or {}), dict(after_ad or {})
    proof = {"fields": []}
    if _normalized_live_text(before_ad.get("title")) != _normalized_live_text(after_ad.get("title")):
        proof["title"] = str(after_ad.get("title") or "")
        proof["fields"].append("Titel")
    if _normalized_live_text(before_ad.get("description")) != _normalized_live_text(after_ad.get("description")):
        proof["description"] = str(after_ad.get("description") or "")
        proof["fields"].append("Beschreibung")
    if _price_key(before_ad.get("price")) != _price_key(after_ad.get("price")):
        proof["price"] = _price_key(after_ad.get("price"))
        proof["fields"].append("Preis")
    if _normalized_live_text(before_ad.get("price_type")) != _normalized_live_text(after_ad.get("price_type")):
        proof["price_type"] = str(after_ad.get("price_type") or "")
        proof["fields"].append("Preisart")
    return proof


def _confirm_uncertain_live_update(slug, account_id, proof=None):
    """Unklare Speicherung nur bei exakt passender bestehender Anzeige bestätigen.

    Es wird niemals anhand der bloßen Existenz der Live-Anzeige Erfolg gemeldet.
    Nicht sicher prüfbare Änderungen (z. B. nur Versand oder nur Bilder) bleiben
    absichtlich unbestätigt und lösen weder einen Retry noch einen Repost aus.
    """
    proof = dict(proof or {})
    fields = list(proof.get("fields") or [])
    if not fields:
        return False, "Keine eindeutig prüfbare Änderung für die Bestätigung vorhanden."
    try:
        ad = _read_ad_yaml(slug) or {}
        remote_id = str(ad.get("id") or "").strip()
        if not remote_id:
            return False, "Der Live-Anzeigen-Link fehlt."
        api, _auth = _api_client(account_id)
        remote = api.get_my_ad(remote_id)
        comparisons = []
        if "title" in proof:
            comparisons.append(_normalized_live_text(getattr(remote, "title", "")) == _normalized_live_text(proof["title"]))
        if "description" in proof:
            expected = _normalized_live_text(proof["description"])
            actual = _normalized_live_text(getattr(remote, "description", ""))
            # Globale Bot-Präfixe/-Suffixe dürfen die inhaltliche Bestätigung nicht verhindern.
            comparisons.append(bool(expected) and expected in actual)
        if "price" in proof:
            comparisons.append(_price_key(getattr(remote, "price", None)) == proof["price"])
        if "price_type" in proof:
            comparisons.append(_normalized_live_text(getattr(remote, "price_type", "")) == _normalized_live_text(proof["price_type"]))
        if comparisons and all(comparisons):
            try:
                _fetch_live_ads_to_cache(account_id)
            except Exception:
                pass
            return True, "Geänderte Werte der bestehenden Live-Anzeige über Kleinanzeigen bestätigt."
        return False, "Die Live-Anzeige enthält noch nicht eindeutig alle geänderten Werte."
    except Exception as exc:
        print(f"[live-update] Bestätigung für {slug} konnte nicht gelesen werden: {exc}", flush=True)
        return False, "Die bestehende Live-Anzeige konnte zur Bestätigung nicht gelesen werden."


def _run_bot_for_slug(command, slug, ads="all", account_id=None, force_new=False, update_proof=None, slot_reserved=False):
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    account_id = _valid_account_id(account_id or _ad_account_id(slug, meta, state), state)
    staging_root = None
    log_preamble = f"Konto: {_account_name(account_id, state)}"
    before_live_ids = set()
    if command == "publish":
        # Für jede Veröffentlichungsart (manuell, geplant, Sammelaktion, Repost)
        # denselben ID-Abgleich verwenden. API-Fehler blockieren den Bot-Publish nicht.
        before_live_ids = _capture_live_ids(account_id)
        cfg_path, staging_root, log_preamble = _prepare_publish_image_order_staging(slug, account_id, force_new=force_new)
    else:
        cfg_path = _make_single_ad_config(slug, account_id)
    try:
        ad_context = _read_ad_yaml(slug) or {}
        result = _run_bot(
            command,
            ads=ads,
            config_path=cfg_path,
            log_preamble=log_preamble,
            slot_reserved=slot_reserved,
            context={
                "slug": slug,
                "title": str(ad_context.get("title") or slug),
                "account_id": account_id,
                "account_name": _account_name(account_id, state),
            },
        )
        if command == "publish" and result.get("ok") and not result.get("remote_id"):
            confirmed_remote_id = _confirmed_publish_remote_id(result.get("output"))
            if confirmed_remote_id and _set_local_remote_link(
                slug,
                account_id,
                confirmed_remote_id,
                posted=_now(),
                reason="Live-ID aus bestätigter Bot-Veröffentlichung gespeichert",
            ):
                result["remote_id"] = confirmed_remote_id
                result["output"] = (
                    str(result.get("output") or "")
                    + f"\n[MANAGER] Live-ID {confirmed_remote_id} direkt aus der bestätigten Bot-Antwort verknüpft."
                )
        if command == "update" and not result.get("ok"):
            output = str(result.get("output") or "")
            if "PublishSubmissionUncertainError" in output or "submission may have succeeded" in output:
                confirmed, confirmation_note = _confirm_uncertain_live_update(slug, account_id, update_proof)
                if confirmed:
                    result["ok"] = True
                    result["output"] = output + "\n[OK] " + confirmation_note
                else:
                    result["output"] = output + "\n[HINWEIS] Speicherung nicht sicher bestätigt: " + confirmation_note + " Kein zweiter Speicherversuch wurde gestartet."
        if command == "publish" and not result.get("ok") and (
            result.get("uncertain_submit") or _publish_submission_uncertain_text(result.get("output"))
        ):
            result["uncertain_submit"] = True
            remote_id, confirmation_note = _confirm_uncertain_publish_after_submit(slug, account_id, before_live_ids)
            if remote_id:
                result["ok"] = True
                result["safe_retry"] = False
                result["remote_id"] = remote_id
                result["confirmed_after_uncertain"] = True
                final_note = (
                    "[MANAGER] Kein endgültiger Veröffentlichungsfehler: Kleinanzeigen hat die Anzeige "
                    f"nach dem unklaren Submit als live bestätigt (ID {remote_id})."
                )
                result["output"] = str(result.get("output") or "") + "\n" + final_note
                log_path = str(result.get("log_path") or "").strip()
                if log_path:
                    try:
                        with Path(log_path).open("a", encoding="utf-8") as fh:
                            fh.write("\n\n--- MANAGER LIVE-BESTÄTIGUNG ---\n" + final_note + "\n")
                    except Exception:
                        pass
                try:
                    _last_log["ok"] = True
                    _last_log["output"] = result["output"]
                except Exception:
                    pass
            else:
                result["safe_retry"] = False
                result["no_retry"] = True
                final_note = (
                    "[MANAGER] Veröffentlichung bleibt unklar: " + confirmation_note +
                    " Es wurde bewusst KEIN zweiter Publish gestartet, um eine Doppelanzeige zu verhindern."
                )
                result["output"] = str(result.get("output") or "") + "\n" + final_note
                log_path = str(result.get("log_path") or "").strip()
                if log_path:
                    try:
                        with Path(log_path).open("a", encoding="utf-8") as fh:
                            fh.write("\n\n--- MANAGER LIVE-BESTÄTIGUNG ---\n" + final_note + "\n")
                    except Exception:
                        pass

        if command == "publish" and result.get("ok") and not result.get("remote_id"):
            try:
                result["remote_id"] = _sync_remote_link_after_publish(
                    slug, account_id, before_live_ids,
                    attempts=8 if force_new else 4,
                    delay_seconds=2.0,
                    require_fresh=bool(force_new),
                )
            except Exception as exc:
                result["remote_id"] = ""
                result["link_warning"] = str(exc)
                print(f"[live-link] Neue ID für {slug} konnte noch nicht gespeichert werden: {exc}", flush=True)
        if command == "publish" and force_new and result.get("ok") and not result.get("remote_id"):
            remote_id, confirmation_note = _confirm_uncertain_publish_after_submit(slug, account_id, before_live_ids)
            if remote_id:
                result["remote_id"] = remote_id
                result["output"] = str(result.get("output") or "") + "\n[MANAGER] Neuer Live-Eintrag nach verzögerter Veröffentlichung bestätigt."
            else:
                result["ok"] = False
                result["safe_retry"] = False
                result["uncertain_submit"] = True
                result["no_retry"] = True
                result["output"] = str(result.get("output") or "") + "\n[MANAGER] Live-Status nach Publish nicht bestätigt: " + confirmation_note + " Kein automatischer Neuversuch wegen möglicher Doppelanzeige."
                print(f"[republish] {slug}: publish exit without remote ID; stopping automatic retry to prevent a duplicate listing.", flush=True)
        return result
    finally:
        try:
            cfg_path.unlink(missing_ok=True)
        except Exception:
            pass
        if staging_root:
            shutil.rmtree(staging_root, ignore_errors=True)

def _collect_due_scheduled_slugs(state=None, now_utc=None):
    state = state or _load_state()
    now_utc = now_utc or datetime.now(timezone.utc)
    due = []
    ads_meta = state.get("ads", {})
    for p in sorted(ADS_DIR.glob("*.yaml")):
        slug = p.stem
        ad = _read_ad_yaml(slug)
        if not ad:
            continue
        meta = ads_meta.get(slug, {})
        scheduled_dt = _iso_dt(meta.get("scheduled_publish_at"))
        retry_dt = _iso_dt(meta.get("publish_retry_at"))
        if retry_dt and retry_dt > now_utc:
            continue
        regular_due = bool(scheduled_dt and scheduled_dt <= now_utc)
        retry_due = bool(retry_dt and retry_dt <= now_utc)
        if ad.get("active", True) and not meta.get("last_published") and not bool(ad.get("id")) and (regular_due or retry_due):
            due.append(slug)
    return due


def _collect_due_republish_slugs(state=None, now_utc=None):
    state = state or _load_state()
    now_utc = now_utc or datetime.now(timezone.utc)
    due = []
    ads_meta = state.get("ads", {})
    for p in sorted(ADS_DIR.glob("*.yaml")):
        slug = p.stem
        ad = _read_ad_yaml(slug)
        if not ad or not ad.get("active", True):
            continue
        meta = ads_meta.get(slug, {})
        postponed_dt = _iso_dt(meta.get("republish_postponed_until"))
        retry_dt = _iso_dt(meta.get("republish_retry_at"))
        if retry_dt and retry_dt > now_utc:
            continue
        if not retry_dt and postponed_dt and postponed_dt > now_utc:
            continue
        scheduled_dt = _iso_dt(meta.get("scheduled_publish_at"))
        is_scheduled_future = bool(scheduled_dt) and not bool(meta.get("last_published")) and scheduled_dt > now_utc
        is_schedule_due = bool(scheduled_dt) and not bool(meta.get("last_published")) and scheduled_dt <= now_utc
        has_id = bool(ad.get("id"))
        is_online = bool(meta.get("last_published")) or (has_id and not is_scheduled_future and not is_schedule_due)
        if not is_online:
            continue
        ref_iso = _age_reference_iso(slug, ad, meta)
        age = _age_days(ref_iso)
        republish_interval = int(ad.get("republication_interval") or REPUBLISH_INTERVAL)
        manual_retry_due = bool(retry_dt and retry_dt <= now_utc)
        if manual_retry_due or (republish_interval > 0 and age >= republish_interval):
            due.append(slug)
    return due


def _publish_scheduled_due_ads(auto=False):
    state = _load_state()
    now_utc = datetime.now(timezone.utc)
    scheduled_slugs = _collect_due_scheduled_slugs(state=state, now_utc=now_utc)
    published_count = 0
    failed_count = 0
    postponed_count = 0
    processed = []

    for slug in scheduled_slugs:
        if _is_cross_platform_terminal(slug):
            _operation_cancelled(slug, "Veröffentlichung beendet: Anzeige wurde plattformübergreifend gelöscht.")
            continue
        ad_preview = _read_ad_yaml(slug) or {}
        state_preview = _load_state()
        meta_preview = state_preview.setdefault("ads", {}).setdefault(slug, {})
        account_preview = _ad_account_id(slug, meta_preview, state_preview)
        op_action = _operation_existing_action_for_publish_retry(slug)
        op = _operation_begin_attempt(
            slug,
            op_action,
            "automatic" if auto else "manual-batch",
            title=str(ad_preview.get("title") or slug),
            account_id=account_preview,
            retry_mode="publish_only" if op_action == "republish" else "publish",
        )

        if not _try_reserve_bot_slot():
            state = _load_state()
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            retry_at = _queue_publish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
            _save_state(state)
            retry_mode = "publish_only" if op_action == "republish" else "publish"
            message = (
                "Bot ist belegt – alte Anzeige ist bereits gelöscht; Neuveröffentlichung in 60 Sekunden."
                if op_action == "republish"
                else "Bot ist belegt – neuer Veröffentlichungsversuch in 60 Sekunden."
            )
            _operation_wait(
                slug,
                message,
                retry_at,
                retry_mode=retry_mode,
                old_live_deleted=(op_action == "republish"),
            )
            postponed_count += 1
            processed.append({"slug": slug, "ok": False, "postponed": True, "retry_at": retry_at, "output": message})
            continue

        try:
            _operation_update(
                slug,
                status="reserved",
                message=(
                    "Bot ist frei – Neuveröffentlichung nach Erneuern wird gestartet."
                    if op_action == "republish"
                    else "Bot ist frei – Veröffentlichung wird gestartet."
                ),
                account_id=account_preview,
                account_name=_account_name(account_preview, state_preview),
            )

            # Erst nach erfolgreicher Reservierung alles noch einmal frisch lesen.
            state = _load_state()
            ad = _read_ad_yaml(slug) or {}
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            # A prior republish already crossed the delete boundary.  Before
            # retrying publish, verify whether Kleinanzeigen completed the old
            # submit late.  This prevents duplicate listings after a timeout.
            if op_action == "republish" and _republish_transaction(meta):
                transaction = _republish_transaction(meta)
                _operation_update(slug, status="checking", message="Vor Publish-only-Retry wird der Live-Status geprüft …", cancel_allowed=False)
                remote_id, confirmation_note = _confirm_uncertain_publish_after_submit(
                    slug, account_preview, transaction.get("before_live_ids") or [],
                )
                if remote_id:
                    state = _load_state()
                    meta = state.setdefault("ads", {}).setdefault(slug, {})
                    meta["last_published"] = _now()
                    meta["publish_count"] = meta.get("publish_count", 0) + 1
                    meta["scheduled_publish_at"] = None
                    _clear_publish_retry(meta)
                    _clear_republish_retry(meta)
                    _clear_republish_transaction(meta)
                    _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                    meta.setdefault("history", []).append({"action": f"neu eingestellt nach verspätigter Live-Bestätigung (ID {remote_id})", "date": _now()})
                    state.setdefault("ads", {})[slug] = meta
                    _save_state(state)
                    _increment_activity_posted_count(account_preview, 1, state)
                    _operation_success(slug, f"Erfolgreich erneuert; Live-ID {remote_id} bestätigt.")
                    _notify_primary("Kleinanzeigen: Anzeige veröffentlicht", f"'{ad.get('title') or slug}' ist nach dem Erneuern wieder live (ID {remote_id}).", click_url=PUBLIC_BASE_URL)
                    published_count += 1
                    processed.append({"slug": slug, "ok": True, "verified_after_delay": True, "output": confirmation_note})
                    continue
                print(f"[republish] {slug}: no late listing before publish-only retry: {confirmation_note}", flush=True)
            if not ad or not ad.get("active", True) or meta.get("last_published") or ad.get("id"):
                _clear_publish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                _operation_cancelled(slug, "Vorgang ist nicht mehr erforderlich.")
                continue

            account_id = _ad_account_id(slug, meta, state)
            _operation_update(
                slug,
                status="checking",
                message="Bot ist frei – 30-Tage-Limit wird geprüft.",
                account_id=account_id,
                account_name=_account_name(account_id, state),
            )
            cap = list(_ensure_publish_capacity(account_id, state))
            cap_kind = _capacity_failure_kind(cap[0], cap[1], cap[2])
            if cap_kind != "ok":
                reason = cap[2]
                if cap_kind == "limit":
                    _clear_publish_retry(meta)
                    _postpone_scheduled_publish(state, slug, meta, reason)
                    _save_state(state)
                    _operation_wait(
                        slug,
                        "30-Tage-Limit erreicht – neuer Versuch morgen.",
                        meta.get("scheduled_publish_at"),
                        retry_mode="publish_only" if op_action == "republish" else "publish",
                        old_live_deleted=(op_action == "republish"),
                        cancel_allowed=False,
                    )
                    postponed_count += 1
                    processed.append({"slug": slug, "ok": False, "postponed": True, "output": reason})
                    continue
                if cap_kind == "technical":
                    retry_at = _queue_publish_retry(state, slug, meta, "30-Tage-Prüfung technisch nicht verfügbar")
                    _save_state(state)
                    message = (
                        "30-Tage-Prüfung technisch nicht verfügbar – alte Anzeige ist bereits gelöscht; Neuveröffentlichung in 60 Sekunden."
                        if op_action == "republish"
                        else "30-Tage-Prüfung technisch nicht verfügbar – neuer Versuch in 60 Sekunden."
                    )
                    _operation_wait(
                        slug,
                        message,
                        retry_at,
                        retry_mode="publish_only" if op_action == "republish" else "publish",
                        old_live_deleted=(op_action == "republish"),
                    )
                    postponed_count += 1
                    processed.append({"slug": slug, "ok": False, "postponed": True, "retry_at": retry_at, "output": reason})
                    continue
                _clear_publish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                failed_count += 1
                _operation_failed(slug, "Veröffentlichung blockiert: " + reason)
                processed.append({"slug": slug, "ok": False, "postponed": False, "output": reason})
                continue

            _operation_update(
                slug,
                status="publishing",
                message=(
                    "Bot läuft – Anzeige wird nach dem Erneuern neu veröffentlicht …"
                    if op_action == "republish"
                    else "Bot läuft – Anzeige wird veröffentlicht …"
                ),
            )
            if _is_cross_platform_terminal(slug):
                _operation_cancelled(slug, "Veröffentlichung beendet: Anzeige wurde plattformübergreifend gelöscht.")
                continue
            result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, force_new=(op_action == "republish"), slot_reserved=True)
            processed.append({"slug": slug, "ok": bool(result.get("ok")), "output": result.get("output", "")})
            if result.get("ok"):
                meta["last_published"] = _now()
                meta["publish_count"] = meta.get("publish_count", 0) + 1
                meta["scheduled_publish_at"] = None
                _clear_publish_retry(meta)
                _clear_republish_retry(meta)
                _clear_republish_transaction(meta)
                _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                action = "automatisch planmaessig veroeffentlicht" if auto else "planmaessig veroeffentlicht"
                if op_action == "republish":
                    action = "automatisch neu eingestellt" if auto else "neu eingestellt"
                meta.setdefault("history", []).append({"action": action, "date": _now()})
                published_count += 1
                _increment_activity_posted_count(account_id, 1, state)
                _operation_success(
                    slug,
                    "Erfolgreich erneuert." if op_action == "republish" else "Erfolgreich veröffentlicht.",
                )
                if op_action == "republish":
                    _notify_primary("Kleinanzeigen: Anzeige veröffentlicht", f"'{ad.get('title') or slug}' wurde erneuert und remote bestätigt (ID {result.get('remote_id')}).", click_url=PUBLIC_BASE_URL)
            else:
                if op_action == "republish" and _publish_result_requires_manual_review(result):
                    failed_count += 1
                    _clear_publish_retry(meta)
                    _clear_republish_retry(meta)
                    meta.setdefault("history", []).append({"action": "Neuveröffentlichung nach Absenden nicht eindeutig bestätigt; kein automatischer weiterer Versuch wegen möglicher Doppelanzeige", "date": _now()})
                    _operation_failed(slug, "Absenden wurde nicht eindeutig bestätigt. Es wurde kein weiterer Veröffentlichungsversuch gestartet, um eine Doppelanzeige zu verhindern.")
                    _notify_primary("Kleinanzeigen: Veröffentlichung prüfen", f"'{ad.get('title') or slug}' wurde möglicherweise bereits veröffentlicht. Es wurde sicher kein zweiter Versuch gestartet.", click_url=PUBLIC_BASE_URL)
                elif result.get("safe_retry"):
                    retry_at = _queue_publish_only_after_republish(
                        state, slug, meta, "Bot/Login-Prüfung oder Live-Bestätigung nach Erneuern fehlgeschlagen"
                    ) if op_action == "republish" else _queue_prestart_publish_retry(
                        state, slug, meta, result,
                        wait_message="Bot/Login-Prüfung fehlgeschlagen – neuer Versuch in 60 Sekunden.",
                        origin_label="Geplante Veröffentlichung",
                    )
                    if not retry_at:
                        failed_count += 1
                        if op_action == "republish":
                            _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                            _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                        state.setdefault("ads", {})[slug] = meta
                        _save_state(state)
                        continue
                    postponed_count += 1
                    processed[-1]["postponed"] = True
                    processed[-1]["retry_at"] = retry_at
                    if op_action == "republish":
                        meta.setdefault("history", []).append({"action": "Bot/Login-Prüfung fehlgeschlagen; automatischer neuer Versuch in 1 Minute", "date": _now()})
                        _operation_wait(
                            slug,
                            "Bot/Login-Prüfung fehlgeschlagen – alte Anzeige ist bereits gelöscht; Neuveröffentlichung in 60 Sekunden.",
                            retry_at, retry_mode="publish_only", old_live_deleted=True,
                        )
                else:
                    action = "Fehler bei automatischer geplanter Veroeffentlichung" if auto else "Fehler bei geplanter Veroeffentlichung"
                    meta.setdefault("history", []).append({"action": action, "date": _now()})
                    if op_action == "republish":
                        retry_at = _queue_publish_only_after_republish(state, slug, meta, str(result.get("output") or "Publish fehlgeschlagen")[:240])
                        if retry_at:
                            postponed_count += 1
                            processed[-1]["postponed"] = True
                            processed[-1]["retry_at"] = retry_at
                            _operation_wait(slug, "Alte Anzeige ist gelöscht; nur Neuveröffentlichung wird erneut versucht.", retry_at, retry_mode="publish_only", old_live_deleted=True)
                        else:
                            failed_count += 1
                            _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                            _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                    else:
                        failed_count += 1
                        _operation_failed(slug, "Veröffentlichung fehlgeschlagen; kein automatischer Retry wegen unklarem Ausgang.")
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
        except Exception as exc:
            _operation_failed(slug, "Fehler im Veröffentlichungsablauf: " + str(exc))
            raise
        finally:
            _release_bot_slot()

    return {"published": published_count, "failed": failed_count, "postponed": postponed_count, "processed": processed}


def _auto_republish_due_ads(auto=True):
    state = _load_state()
    now_utc = datetime.now(timezone.utc)
    due_slugs = _collect_due_republish_slugs(state=state, now_utc=now_utc)
    renewed = failed = postponed = 0
    processed = []

    for slug in due_slugs:
        if _is_cross_platform_terminal(slug):
            _operation_cancelled(slug, "Erneuern beendet: Anzeige wurde plattformübergreifend gelöscht.")
            continue
        ad_preview = _read_ad_yaml(slug) or {}
        state_preview = _load_state()
        meta_preview = state_preview.setdefault("ads", {}).setdefault(slug, {})
        account_preview = _ad_account_id(slug, meta_preview, state_preview)
        _operation_begin_attempt(
            slug,
            "republish",
            "automatic" if auto else "manual-batch",
            title=str(ad_preview.get("title") or slug),
            account_id=account_preview,
            retry_mode="republish",
        )

        # Reservierung VOR jeder destruktiven Remote-Aktion.
        if not _try_reserve_bot_slot():
            state = _load_state()
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            retry_at = _queue_republish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
            _save_state(state)
            _operation_wait(
                slug,
                "Bot ist belegt – Live-Anzeige bleibt online; neuer Versuch in 60 Sekunden.",
                retry_at,
                retry_mode="republish",
                old_live_deleted=False,
            )
            postponed += 1
            processed.append({"slug": slug, "ok": False, "postponed": True, "retry_at": retry_at, "output": "Bot-Slot belegt; Live-Anzeige blieb online; neuer Versuch in 1 Minute."})
            continue

        try:
            _operation_update(
                slug,
                status="reserved",
                message="Bot ist frei – Erneuern wird gestartet.",
                account_id=account_preview,
                account_name=_account_name(account_preview, state_preview),
            )
            state = _load_state()
            ad = _read_ad_yaml(slug) or {}
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            if not ad or not ad.get("active", True):
                _clear_republish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                _operation_cancelled(slug, "Erneuern ist nicht mehr erforderlich.")
                continue

            account_id = _ad_account_id(slug, meta, state)
            _operation_update(
                slug,
                status="checking",
                message="Bot ist frei – 30-Tage-Limit wird geprüft.",
                account_id=account_id,
                account_name=_account_name(account_id, state),
            )
            cap = list(_ensure_publish_capacity(account_id, state))
            cap_kind = _capacity_failure_kind(cap[0], cap[1], cap[2])
            if cap_kind != "ok":
                reason = cap[2] if cap[1] is None else f"{cap[1]}/{REPOST_LIMIT_LAST_30_DAYS} Anzeigen in den letzten 30 Tagen bei '{_account_name(account_id, state)}'"
                if cap_kind == "limit":
                    _clear_republish_retry(meta)
                    _postpone_republish(state, slug, meta, reason)
                    _save_state(state)
                    postponed += 1
                    processed.append({"slug": slug, "ok": False, "postponed": True, "output": reason})
                    _operation_wait(
                        slug,
                        "30-Tage-Limit erreicht – Live-Anzeige bleibt online; neuer Versuch morgen.",
                        meta.get("republish_postponed_until"),
                        retry_mode="republish",
                        old_live_deleted=False,
                        cancel_allowed=False,
                    )
                    title = ad.get("title", slug)
                    _notify_primary("Kleinanzeigen: Erneuern verschoben", f"'{title}' wurde nicht neu eingestellt, weil {reason}. Neuer Versuch morgen.")
                    continue
                if cap_kind == "technical":
                    meta.pop("republish_postponed_until", None)
                    retry_at = _queue_republish_retry(state, slug, meta, "30-Tage-Prüfung technisch nicht verfügbar")
                    _save_state(state)
                    postponed += 1
                    processed.append({"slug": slug, "ok": False, "postponed": True, "retry_at": retry_at, "output": reason})
                    _operation_wait(
                        slug,
                        "30-Tage-Prüfung technisch nicht verfügbar – Live-Anzeige bleibt online; neuer Versuch in 60 Sekunden.",
                        retry_at,
                        retry_mode="republish",
                        old_live_deleted=False,
                    )
                    continue
                _clear_republish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                failed += 1
                processed.append({"slug": slug, "ok": False, "postponed": False, "output": reason})
                _operation_failed(slug, "Erneuern blockiert; Live-Anzeige blieb online: " + reason)
                continue

            old_id = str(ad.get("id") or "").strip()
            is_online = bool(meta.get("last_published") or old_id)
            if not is_online:
                _clear_republish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                _operation_cancelled(slug, "Anzeige ist nicht mehr als online markiert; Erneuern wurde beendet.")
                continue

            # Fehlende ID zuerst sicher rekonstruieren. Ohne bestätigte ID wird
            # keinesfalls blind eine zweite Live-Anzeige erzeugt.
            if not old_id:
                _operation_update(slug, status="checking", message="Live-Verknüpfung wird vor dem Löschen geprüft …")
                try:
                    _listings, items = _fetch_live_ads_raw(account_id)
                    _reconcile_live_links(account_id, items)
                    ad = _read_ad_yaml(slug) or ad
                    old_id = str(ad.get("id") or "").strip()
                except Exception as exc:
                    print(f"[auto-republish] Live-ID-Abgleich für {slug} fehlgeschlagen: {exc}", flush=True)

            if not old_id:
                retry_at = _queue_republish_retry(state, slug, meta, "Live-ID konnte nicht eindeutig ermittelt werden")
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                postponed += 1
                processed.append({"slug": slug, "ok": False, "postponed": True, "retry_at": retry_at, "output": "Live-ID fehlt; nichts gelöscht."})
                _operation_wait(
                    slug,
                    "Live-ID konnte nicht eindeutig ermittelt werden – nichts gelöscht; neuer Versuch in 60 Sekunden.",
                    retry_at,
                    retry_mode="republish",
                    old_live_deleted=False,
                )
                continue

            if _is_cross_platform_terminal(slug):
                _operation_cancelled(slug, "Erneuern beendet: Anzeige wurde plattformübergreifend gelöscht.")
                continue
            _operation_update(slug, status="deleting", message="Alte Live-Anzeige wird gelöscht …")
            try:
                _create_backup(reason="vor-auto-repost-live-loeschen", slug=slug)
                _delete_remote_only(account_id, old_id)
                _clear_local_remote_id_only(slug)
                meta["last_published"] = None
                _mark_republish_delete_success(meta, old_id)
                meta.setdefault("history", []).append({"action": f"alte Live-ID {old_id} direkt gelöscht", "date": _now()})
                _operation_update(slug, old_live_deleted=True, message="Alte Live-Anzeige gelöscht – Neuveröffentlichung wird vorbereitet …")
            except Exception as exc:
                delete_error = str(exc) or exc.__class__.__name__
                meta.setdefault("history", []).append({"action": f"alte Live-ID {old_id} konnte nicht gelöscht werden: {delete_error}", "date": _now()})
                _clear_republish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                failed += 1
                processed.append({"slug": slug, "ok": False, "postponed": False, "output": delete_error})
                _operation_failed(slug, "Löschen der alten Live-Anzeige nicht sicher bestätigt; kein automatischer zweiter Löschversuch.")
                _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': Löschen der alten Anzeige nicht sicher bestätigt. Es wurde kein weiterer Löschversuch gestartet.", click_url=PUBLIC_BASE_URL)
                continue

            price_change = _prepare_republish_price_reduction(slug, meta, now_utc=now_utc)
            _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird neu veröffentlicht …")
            if _is_cross_platform_terminal(slug):
                _operation_cancelled(slug, "Neu-Veröffentlichen beendet: Anzeige wurde plattformübergreifend gelöscht.")
                continue
            result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, force_new=True, slot_reserved=True)
            if not result.get("ok") and price_change:
                _restore_republish_price(slug, price_change["old_price"])
            processed.append({"slug": slug, "ok": bool(result.get("ok")), "delete_ok": True, "output": result.get("output", "")})

            if result.get("ok"):
                meta["last_published"] = _now()
                meta["publish_count"] = meta.get("publish_count", 0) + 1
                meta["scheduled_publish_at"] = None
                meta.pop("republish_postponed_until", None)
                _clear_republish_retry(meta)
                _clear_publish_retry(meta)
                _clear_republish_transaction(meta)
                if price_change:
                    _commit_price_reduction(meta, price_change)
                    _append_price_history(
                        meta,
                        price_change["old_price"],
                        price_change["new_price"],
                        source="automatic",
                        action="Automatische Preissenkung",
                        at=price_change.get("reduction_at") or _now(),
                    )
                else:
                    _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta, now_utc=now_utc)
                meta.setdefault("history", []).append({"action": "automatisch neu eingestellt" if auto else "neu eingestellt", "date": _now()})
                renewed += 1
                _increment_activity_posted_count(account_id, 1, state)
                if not str(result.get("remote_id") or ""):
                    meta.setdefault("history", []).append({"action": "Warnung: neue Live-ID konnte nach Repost noch nicht automatisch ermittelt werden", "date": _now()})
                    _operation_success(slug, "Erfolgreich erneuert; Live-ID-Verknüpfung wird noch nachgezogen.")
                else:
                    _operation_success(slug, "Erfolgreich erneuert.")
                _notify_primary("Kleinanzeigen: Anzeige veröffentlicht", f"'{ad.get('title') or slug}' wurde erneuert und remote bestätigt (ID {result.get('remote_id')}).", click_url=PUBLIC_BASE_URL)
            else:
                _clear_republish_retry(meta)
                if _publish_result_requires_manual_review(result):
                    failed += 1
                    _clear_publish_retry(meta)
                    meta.setdefault("history", []).append({"action": "Neuveröffentlichung nach Absenden nicht eindeutig bestätigt; kein automatischer weiterer Versuch wegen möglicher Doppelanzeige", "date": _now()})
                    _operation_failed(slug, "Absenden wurde nicht eindeutig bestätigt. Es wurde kein weiterer Veröffentlichungsversuch gestartet, um eine Doppelanzeige zu verhindern.")
                    _notify_primary("Kleinanzeigen: Veröffentlichung prüfen", f"'{ad.get('title') or slug}' wurde möglicherweise bereits veröffentlicht. Es wurde sicher kein zweiter Versuch gestartet.", click_url=PUBLIC_BASE_URL)
                elif result.get("safe_retry"):
                    retry_at = _queue_publish_only_after_republish(state, slug, meta, "Neuveröffentlichung nach Erneuern konnte noch nicht starten")
                    if not retry_at:
                        failed += 1
                        _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                        _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                        state.setdefault("ads", {})[slug] = meta
                        _save_state(state)
                        continue
                    processed[-1]["postponed"] = True
                    processed[-1]["retry_at"] = retry_at
                    postponed += 1
                    meta.setdefault("history", []).append({"action": "Alte Anzeige gelöscht; Neuveröffentlichung wird in 1 Minute erneut versucht", "date": _now()})
                    _operation_wait(
                        slug,
                        "Alte Anzeige ist gelöscht; Bot/Login-Prüfung fehlgeschlagen – nur die Neuveröffentlichung wird in 60 Sekunden erneut versucht.",
                        retry_at,
                        retry_mode="publish_only",
                        old_live_deleted=True,
                    )
                else:
                    meta.setdefault("history", []).append({"action": "Fehler bei automatischem Erneuern" if auto else "Fehler beim Erneuern", "date": _now()})
                    retry_at = _queue_publish_only_after_republish(state, slug, meta, str(result.get("output") or "Publish fehlgeschlagen")[:240])
                    if retry_at:
                        postponed += 1
                        processed[-1]["postponed"] = True
                        processed[-1]["retry_at"] = retry_at
                        _operation_wait(slug, "Alte Anzeige ist gelöscht; nur Neuveröffentlichung wird erneut versucht.", retry_at, retry_mode="publish_only", old_live_deleted=True)
                    else:
                        failed += 1
                        _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                        _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)

            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
        except Exception as exc:
            _operation_failed(slug, "Fehler im Erneuern-Ablauf: " + str(exc))
            raise
        finally:
            _release_bot_slot()

    return {"renewed": renewed, "failed": failed, "postponed": postponed, "processed": processed}


def _scheduled_publish_loop():
    while True:
        try:
            _auto_activity_refresh_due()
            _cleanup_stale_retry_markers()
            _publish_scheduled_due_ads(auto=True)
            _auto_republish_due_ads(auto=True)
            _mark_runtime_health("automation", ok=True, message="Automatik prüft Veröffentlichung, Retry und Erneuerung.")
        except Exception as exc:
            _mark_runtime_health("automation", ok=False, message=str(exc))
            # Automatikfehler dürfen nie wieder lautlos verschwinden. Das war bei
            # früheren Publish-Problemen diagnostisch besonders ungünstig.
            detail = traceback.format_exc()
            print(f"[scheduler] Fehler: {exc}\n{detail}", flush=True)
            try:
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                with (LOGS_DIR / "scheduler-errors.log").open("a", encoding="utf-8") as fh:
                    fh.write(f"\n[{_now()}] {exc}\n{detail}\n")
            except Exception:
                pass
        time.sleep(SCHEDULER_POLL_SECONDS)

# -- noVNC Manual Login --

_vnc_procs = []
_vnc_account_id = None
_vnc_browser_proc = None


def _profile_chromium_pids(profile_dir):
    """Return Chromium processes that explicitly use this account profile."""
    profile_text = str(Path(profile_dir).resolve())
    matches = []
    proc_root = Path("/proc")
    try:
        entries = list(proc_root.iterdir())
    except Exception:
        return matches
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
            if not raw:
                continue
            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", "replace")
        except Exception:
            continue
        lowered = cmdline.lower()
        if profile_text in cmdline and ("chromium" in lowered or "chrome" in lowered):
            matches.append(int(entry.name))
    return sorted(set(matches))


def _terminate_profile_chromium(profile_dir):
    """Stop leftover Chromium for one account profile without touching other accounts."""
    pids = _profile_chromium_pids(profile_dir)
    if not pids:
        return []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.time() + 3.0
    remaining = set(pids)
    while remaining and time.time() < deadline:
        for pid in list(remaining):
            if not Path(f"/proc/{pid}").exists():
                remaining.discard(pid)
        if remaining:
            time.sleep(0.1)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return pids


def _clear_stale_chromium_profile_locks(profile_dir):
    """Remove only Chromium's lock artefacts, never cookies/session data."""
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    removed = []
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = profile_dir / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
                removed.append(name)
        except FileNotFoundError:
            pass
    return removed


def _tail_text_file(path, max_chars=3000):
    try:
        text = Path(path).read_text("utf-8", errors="replace")
    except Exception:
        return ""
    return text[-max_chars:].strip()


def _start_vnc_login(account_id=MAIN_ACCOUNT_ID):
    global _vnc_procs, _vnc_account_id, _vnc_browser_proc
    _stop_vnc()
    account_id = _valid_account_id(account_id)
    login = _account_login(account_id)
    if not login.get("email"):
        return False, "Bitte zuerst Login-Daten für dieses Konto eingeben."
    if _last_log.get("running") or _bot_lock.locked():
        return False, "Der Kleinanzeigen-Bot benutzt gerade ein Browserprofil. Bitte kurz warten und Browser-Login danach erneut starten."

    profile_dir = _account_profile_dir(account_id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    leftover_pids = _terminate_profile_chromium(profile_dir)
    removed_locks = _clear_stale_chromium_profile_locks(profile_dir)
    _vnc_account_id = account_id
    browser_log = LOGS_DIR / f"manual-login-{account_id}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-ac"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(xvfb)
        time.sleep(0.8)
        if xvfb.poll() is not None:
            raise RuntimeError("Xvfb konnte nicht gestartet werden (Display :99).")

        vnc = subprocess.Popen(["x11vnc", "-display", ":99", "-forever", "-nopw", "-shared", "-rfbport", "5900"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(vnc)
        time.sleep(0.5)
        if vnc.poll() is not None:
            raise RuntimeError("x11vnc konnte nicht gestartet werden (Port 5900).")

        novnc = subprocess.Popen(["/opt/noVNC/utils/novnc_proxy", "--vnc", "localhost:5900", "--listen", "6080"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(novnc)
        time.sleep(0.7)
        if novnc.poll() is not None:
            raise RuntimeError("noVNC konnte nicht gestartet werden (Port 6080).")

        with browser_log.open("ab", buffering=0) as log_handle:
            chrome = subprocess.Popen([
                os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser"),
                "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--window-size=1280,1024",
                "--user-data-dir=" + str(profile_dir),
                "https://www.kleinanzeigen.de/m-einloggen.html",
            ], env={**os.environ, "DISPLAY": ":99"}, stdout=log_handle, stderr=log_handle)
        _vnc_procs.append(chrome)
        _vnc_browser_proc = chrome
        time.sleep(2.0)
        if chrome.poll() is not None:
            details = _tail_text_file(browser_log)
            raise RuntimeError("Chromium wurde direkt wieder beendet." + ((" Browser-Log: " + details) if details else ""))

        recovery = []
        if leftover_pids:
            recovery.append("hängenden Chromium-Prozess beendet")
        if removed_locks:
            recovery.append("verwaisten Browser-Lock entfernt")
        suffix = (" (" + ", ".join(recovery) + ")") if recovery else ""
        return True, "noVNC gestartet." + suffix
    except Exception as e:
        details = _tail_text_file(browser_log)
        _stop_vnc()
        message = str(e)
        if details and "Browser-Log:" not in message:
            message += " Browser-Log: " + details
        return False, "Browser-Login fehlgeschlagen: " + message


def _stop_vnc():
    global _vnc_procs, _vnc_account_id, _vnc_browser_proc
    for p in reversed(_vnc_procs):
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    _vnc_procs = []
    _vnc_account_id = None
    _vnc_browser_proc = None

def _vnc_running():
    # A live noVNC/Xvfb stack without a browser only produces a black page.
    if _vnc_browser_proc is None or _vnc_browser_proc.poll() is not None:
        return False
    return all(p.poll() is None for p in _vnc_procs)

def _make_activity_profile_snapshot(account_id, source_profile):
    """Erzeuge für Selenium eine kurzlebige Kopie des eingeloggten Profils.

    Die Aktivitätsprüfung darf das persistente Bot-Profil niemals selbst öffnen.
    Dadurch kann sie keine Singleton-Locks mehr hinterlassen, die den direkt
    anschließenden nodriver-Bot blockieren. Cache-Verzeichnisse und Chromium-Locks
    werden nicht kopiert; Cookies/Login-Daten bleiben in der Kopie erhalten.
    """
    source_profile = Path(source_profile)
    temp_parent = _account_workspace(account_id) / ".temp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="activity-profile-", dir=str(temp_parent)))
    ignore = shutil.ignore_patterns(
        "SingletonLock", "SingletonSocket", "SingletonCookie",
        "Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
        "DawnCache", "Crashpad", "BrowserMetrics*",
    )
    try:
        if source_profile.exists():
            shutil.copytree(
                source_profile,
                snapshot,
                dirs_exist_ok=True,
                symlinks=False,
                ignore=ignore,
            )
        _clear_stale_chromium_profile_locks(snapshot)
        return snapshot
    except Exception:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def _fetch_account_activity(account_id=MAIN_ACCOUNT_ID):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
    except Exception as e:
        return False, "Selenium nicht verfuegbar: " + str(e)

    account_id = _valid_account_id(account_id)
    source_profile_dir = _account_profile_dir(account_id)
    source_profile_dir.mkdir(parents=True, exist_ok=True)
    urls = [
        "https://www.kleinanzeigen.de/m-einstellungen.html",
        "https://www.kleinanzeigen.de/m-mein-konto.html",
        "https://www.kleinanzeigen.de/m-meine-anzeigen.html",
    ]

    # Seit 1.6.22 absichtlich NICHT mehr _bot_lock verwenden.
    # Die Aktivitätsprüfung läuft auf einer separaten Profilkopie und darf einen
    # manuellen Publish weder blockieren noch dessen Bot-Status unsichtbar machen.
    with _activity_browser_lock:
        driver = None
        activity_profile_dir = None
        try:
            activity_profile_dir = _make_activity_profile_snapshot(account_id, source_profile_dir)
            options = Options()
            options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser")
            options.add_argument("--no-sandbox")
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--window-size=1280,1024")
            options.add_argument(f"--user-data-dir={activity_profile_dir}")
            service = Service(os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
            driver = webdriver.Chrome(service=service, options=options)
            try:
                driver.set_page_load_timeout(20)
                driver.set_script_timeout(20)
            except Exception:
                pass
            body_text = ""
            for url in urls:
                try:
                    driver.get(url)
                    time.sleep(2)
                    body_text = driver.find_element(By.TAG_NAME, "body").text
                except Exception:
                    continue

                online = re.search(r"Du hast aktuell\s+(\d+)\s+Anzeigen online\.", body_text)
                posted = re.search(r"Du hast in den letzten\s+30\s+Tagen\s+(\d+)\s+Anzeigen aufgegeben\.", body_text)
                if online and posted:
                    return True, {
                        "online_ads": int(online.group(1)),
                        "posted_last_30_days": int(posted.group(1)),
                        "updated_at": _now(),
                        "source_url": url,
                    }

            if "einloggen" in body_text.lower() or "anmelden" in body_text.lower():
                return False, "Nicht eingeloggt. Bitte zuerst den Browser-Login in den Einstellungen durchfuehren."
            return False, "Aktivitaet konnte nicht gelesen werden. Kleinanzeigen-Seite eventuell geaendert."
        except Exception as e:
            return False, "Aktivitaet konnte nicht geladen werden: " + str(e)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            # Nur die kurzlebige Selenium-Kopie aufräumen. Das persistente
            # Konto-/Botprofil wurde von diesem Check zu keinem Zeitpunkt geöffnet.
            if activity_profile_dir is not None:
                try:
                    _terminate_profile_chromium(activity_profile_dir)
                except Exception:
                    pass
                shutil.rmtree(activity_profile_dir, ignore_errors=True)

# -- Template Helpers --

@app.before_request
def _daily_backup_hook():
    # Letzten echten Browser-Zugriff merken. So kann ein HA-Push beim Antippen
    # genau die Adresse öffnen, über die der Manager zuletzt benutzt wurde.
    global _last_access_base_url
    try:
        if request.method == "GET" and request.host and not request.path.startswith("/static/"):
            base = request.host_url.rstrip("/")
            if base.startswith(("http://", "https://")):
                _last_access_base_url = base
    except Exception:
        pass

    # 1.6.0: lokale Haushaltsidentität für getrennten Nachrichten-Lesestatus.
    endpoint = str(request.endpoint or "")
    public_endpoints = {"profile_login", "static", "service_worker", "health"}
    if endpoint not in public_endpoints and not _current_app_user():
        if request.path.startswith("/static/"):
            return None
        return redirect(url_for("profile_login"))
    return None

@app.context_processor
def inject_globals():
    settings = _get_settings()
    return dict(
        app_title=APP_TITLE,
        home_screen_title=HOME_SCREEN_TITLE,
        configured=settings.get("configured", False),
        republish_interval=REPUBLISH_INTERVAL,
        bot_running=_last_log.get("running", False),
        vnc_running=_vnc_running(),
        unread_messages=_cached_unread_total(),
        current_app_user=_app_user_for_display(_current_app_user()),
        app_users=_app_users_for_display(),
        unpublished_count_global=_count_unpublished_ads(),
        public_base_url=PUBLIC_BASE_URL,
        app_version=APP_VERSION,
        direct_push_subscriptions=len(_load_webpush_subscriptions()),
        vnc_account_id=_vnc_account_id,
    )

@app.template_filter("age")
def age_filter(iso_date):
    return _age_days(iso_date)

@app.template_filter("datefmt")
def datefmt_filter(iso_date):
    try:
        dt = _iso_dt(iso_date)
        return dt.astimezone(_local_tz()).strftime("%d.%m.%Y %H:%M") if dt else iso_date
    except Exception:
        return iso_date

@app.template_filter("dateonly")
def dateonly_filter(iso_date):
    try:
        dt = _iso_dt(iso_date)
        return dt.astimezone(_local_tz()).strftime("%d.%m.%Y") if dt else iso_date
    except Exception:
        return iso_date

@app.template_filter("msgdate")
def msgdate_filter(iso_date):
    """Kompaktes Datum für Nachrichten: heute HH:MM, gestern 'Gestern', sonst TT.MM.JJJJ."""
    try:
        dt = _iso_dt(iso_date)
        if not dt:
            return str(iso_date or "")
        local_dt = dt.astimezone(_local_tz())
        today = _local_datetime().date()
        if local_dt.date() == today:
            return local_dt.strftime("%H:%M")
        if local_dt.date() == today - timedelta(days=1):
            return "Gestern"
        return local_dt.strftime("%d.%m.%Y")
    except Exception:
        return str(iso_date or "")

@app.template_filter("liveposted")
def liveposted_filter(iso_date):
    """Live publication time: include clock time for today and yesterday."""
    try:
        dt = _iso_dt(iso_date)
        if not dt:
            return str(iso_date or "")
        local_dt = dt.astimezone(_local_tz())
        today = _local_datetime().date()
        if local_dt.date() == today:
            return f"heute {local_dt.strftime('%H:%M')} Uhr"
        if local_dt.date() == today - timedelta(days=1):
            return f"gestern {local_dt.strftime('%H:%M')} Uhr"
        return local_dt.strftime("%d.%m.%Y")
    except Exception:
        return str(iso_date or "")

@app.template_filter("price_label")
def price_label_filter(code):
    for c, label in PRICE_TYPES:
        if c == code:
            return label
    return code

@app.template_filter("money")
def money_filter(value):
    return _fmt_money(value)

@app.template_filter("shipping_label")
def shipping_label_filter(code):
    for c, label in SHIPPING_TYPES:
        if c == code:
            return label
    return code

# -- Routes: Index --


def _all_folders():
    folders = set()
    try:
        state = _load_state()
        for folder in state.get("folders", []) or []:
            folder = str(folder).strip()
            if folder:
                folders.add(folder)
    except Exception:
        pass
    try:
        for p in ADS_DIR.glob("*.yaml"):
            ad = _read_ad_yaml(p.stem) or {}
            folder = str(ad.get("folder", "")).strip()
            if folder:
                folders.add(folder)
    except Exception:
        pass
    return sorted(folders, key=lambda x: x.lower())


def _add_folder(folder):
    folder = (folder or "").strip()
    if not folder:
        return False
    state = _load_state()
    folders = state.setdefault("folders", [])
    existing = {str(f).strip().lower() for f in folders}
    if folder.lower() not in existing:
        folders.append(folder)
        state["folders"] = sorted([str(f).strip() for f in folders if str(f).strip()], key=lambda x: x.lower())
        _save_state(state)
    return True


def _delete_folder(folder):
    folder = (folder or "").strip()
    if not folder:
        return 0
    state = _load_state()
    state["folders"] = [f for f in (state.get("folders", []) or []) if str(f).strip().lower() != folder.lower()]
    changed_ads = 0
    for p in ADS_DIR.glob("*.yaml"):
        slug = p.stem
        ad = _read_ad_yaml(slug) or {}
        if str(ad.get("folder", "")).strip().lower() == folder.lower():
            ad.pop("folder", None)
            _write_yaml_file(_ad_yaml_path(slug), ad)
            changed_ads += 1
    _save_state(state)
    return changed_ads


def _selected_slugs_from_form(form):
    selected = []
    seen = set()
    for raw in form.getlist("selected_slugs"):
        slug = (raw or "").strip()
        if slug and slug not in seen and _ad_yaml_path(slug).exists():
            seen.add(slug)
            selected.append(slug)
    return selected


def _delete_local_slug(slug):
    p = _ad_yaml_path(slug)
    if p.exists():
        p.unlink()
    img_dir = _ad_images_dir(slug)
    if img_dir.is_dir():
        shutil.rmtree(img_dir)
    state = _load_state()
    state.get("ads", {}).pop(slug, None)
    _save_state(state)


def _mark_cross_platform_terminal(slug: str, reason: str) -> None:
    """Persistently block only explicit sale/'delete everywhere' rows from republish."""
    slug = str(slug or "").strip()
    if not slug:
        return
    with _cross_platform_terminal_lock:
        _cross_platform_terminal_slugs.add(slug)
    state = _load_state()
    meta = state.setdefault("ads", {}).get(slug)
    if isinstance(meta, dict):
        meta["cross_platform_terminal_at"] = _now()
        meta["cross_platform_terminal_reason"] = str(reason)[:180]
        _clear_publish_retry(meta)
        _clear_republish_retry(meta)
        _clear_republish_transaction(meta)
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
    _operation_cancelled(slug, f"Automatik beendet: {reason}")
    print(f"[cross-platform] republish blocked for {slug}: {reason}", flush=True)


def _clear_cross_platform_terminal(slug: str) -> None:
    slug = str(slug or "").strip()
    with _cross_platform_terminal_lock:
        _cross_platform_terminal_slugs.discard(slug)
    state = _load_state()
    meta = state.setdefault("ads", {}).get(slug)
    if isinstance(meta, dict):
        meta.pop("cross_platform_terminal_at", None)
        meta.pop("cross_platform_terminal_reason", None)
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)


def _is_cross_platform_terminal(slug: str) -> bool:
    slug = str(slug or "").strip()
    with _cross_platform_terminal_lock:
        if slug in _cross_platform_terminal_slugs:
            return True
    state = _load_state()
    return bool((state.get("ads", {}).get(slug) or {}).get("cross_platform_terminal_at"))


def _copy_ad(slug):
    ad = _read_ad_yaml(slug)
    if not ad:
        return None
    base_title = str(ad.get("title") or slug).strip()
    copy_title = f"{base_title} Kopie"
    new_slug_base = _slug(copy_title)
    new_slug = new_slug_base
    while _ad_yaml_path(new_slug).exists():
        new_slug = f"{new_slug_base}-{str(uuid.uuid4())[:4]}"
    new_ad = dict(ad)
    new_ad["title"] = copy_title
    for key in ("id", "created_on_kleinanzeigen", "updated_at", "created_at"):
        new_ad.pop(key, None)
    # Bilder kopieren und YAML-Pfade auf neuen Slug umstellen
    old_img_dir = _ad_images_dir(slug)
    new_img_dir = _ad_images_dir(new_slug)
    image_names = []
    if old_img_dir.is_dir():
        new_img_dir.mkdir(parents=True, exist_ok=True)
        for img in _list_ad_images(slug):
            src = old_img_dir / img
            if src.exists():
                shutil.copy2(src, new_img_dir / img)
                image_names.append(img)
    if image_names:
        new_ad["images"] = ["../images/" + new_slug + "/" + f for f in image_names]
    else:
        new_ad.pop("images", None)
    ADS_DIR.mkdir(parents=True, exist_ok=True)
    _write_yaml_file(_ad_yaml_path(new_slug), new_ad)
    state = _load_state()
    source_meta = state.get("ads", {}).get(slug, {})
    state.setdefault("ads", {})[new_slug] = {
        "created_at": _now(),
        "last_published": None,
        "publish_count": 0,
        "scheduled_publish_at": None,
        "account_id": _ad_account_id(slug, source_meta, state),
        "history": [{"action": f"kopiert von {slug}", "date": _now()}],
    }
    _save_state(state)
    return new_slug

def _count_unpublished_ads(state=None):
    state = state or _load_state()
    ads_meta = state.get("ads", {})
    count = 0
    for path in ADS_DIR.glob("*.yaml"):
        ad = _read_ad_yaml(path.stem) or {}
        meta = ads_meta.get(path.stem, {})
        if not ad.get("id") and not meta.get("last_published") and not _republish_transaction(meta):
            count += 1
    return count



def _vinted_transfer_source_id(slug: str) -> str:
    return f"kleinanzeigen:{str(slug or '').strip()}"


def _vinted_transfer_receipt_name(source_id: str) -> str:
    digest = hashlib.sha256(str(source_id or "").encode("utf-8")).hexdigest()[:24]
    return f"{digest}.json"


def _sync_vinted_transfer_receipts(state: dict[str, Any]) -> bool:
    if not VINTED_TRANSFER_RECEIPT_DIR.is_dir():
        return False
    changed = False
    ads_state = state.setdefault("ads", {})
    for receipt in VINTED_TRANSFER_RECEIPT_DIR.glob("*.json"):
        try:
            payload = json.loads(receipt.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or str(payload.get("source_platform") or "") != "kleinanzeigen":
            continue
        slug = str(payload.get("source_slug") or "").strip()
        if not slug or not _ad_yaml_path(slug).exists():
            continue
        meta = ads_state.setdefault(slug, {})
        status = str(payload.get("status") or "").strip()
        draft_id = str(payload.get("draft_id") or "").strip()
        message = str(payload.get("message") or "").strip()
        values = {
            "vinted_transfer_source_id": str(payload.get("source_id") or _vinted_transfer_source_id(slug)),
            "vinted_transfer_status": status,
            "vinted_draft_id": draft_id,
            "vinted_transfer_message": message,
            "vinted_transfer_updated_at": str(payload.get("updated_at") or ""),
        }
        for key, value in values.items():
            if meta.get(key) != value:
                meta[key] = value
                changed = True
        ads_state[slug] = meta
    return changed


def _write_vinted_cross_action(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)


def _vinted_delete_action_for_kleinanzeigen(slug: str, state: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    """Prepare an exact Vinted deletion request without changing either platform."""
    meta = state.setdefault("ads", {}).get(slug, {})
    source_id = str(meta.get("vinted_transfer_source_id") or _vinted_transfer_source_id(slug)).strip()
    draft_id = str(meta.get("vinted_draft_id") or "").strip()
    if not draft_id or str(meta.get("vinted_transfer_status") or "").lower() != "imported":
        return None
    token = hashlib.sha256(f"{source_id}:{draft_id}:delete".encode("utf-8")).hexdigest()[:24]
    target = VINTED_DELETE_ACTION_INBOX_DIR / f"kleinanzeigen-delete-{token}.json"
    payload = {
        "schema": 1,
        "action": "kleinanzeigen_delete_cleanup",
        "source_platform": "kleinanzeigen",
        "source_slug": slug,
        "source_id": source_id,
        "vinted_draft_id": draft_id,
        "created_at": _now(),
    }
    return target, payload, meta


def _queue_vinted_delete_for_kleinanzeigen(slug: str, state: dict[str, Any]) -> bool:
    """Ask Vinted to remove the known transferred sibling, never a title match."""
    prepared = _vinted_delete_action_for_kleinanzeigen(slug, state)
    if not prepared:
        return False
    target, payload, meta = prepared
    if not target.exists():
        _write_vinted_cross_action(target, payload)
    meta["vinted_cross_delete_queued_at"] = _now()
    meta["vinted_cross_delete_status"] = "queued"
    return True


def _mark_vinted_cross_action_failed(path: Path, payload: dict[str, Any], error: Exception | str) -> None:
    """Stop after one uncertain destructive attempt; leave a diagnosable record."""
    failed = dict(payload or {})
    failed["status"] = "failed"
    failed["failed_at"] = _now()
    failed["error"] = str(error)[:500]
    _write_vinted_cross_action(path.with_suffix(".failed.json"), failed)
    path.unlink(missing_ok=True)


def _process_vinted_sold_cleanup(path: Path) -> None:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict) or payload.get("action") != "vinted_sold_cleanup" or payload.get("source_platform") != "vinted":
        raise ValueError("Unbekannte Vinted-Cross-Platform-Aktion")
    slug = str(payload.get("source_slug") or "").strip()
    source_id = str(payload.get("source_id") or "").strip()
    expected_draft_id = str(payload.get("vinted_draft_id") or "").strip()
    if not slug or not source_id or not expected_draft_id:
        raise ValueError("Vinted-Verkaufsaktion enthält keine eindeutige Verknüpfung")
    state = _load_state()
    _sync_vinted_transfer_receipts(state)
    meta = state.setdefault("ads", {}).get(slug, {})
    if not _ad_yaml_path(slug).exists():
        path.unlink(missing_ok=True)
        return
    if (
        str(meta.get("vinted_transfer_source_id") or "") != source_id
        or str(meta.get("vinted_draft_id") or "") != expected_draft_id
    ):
        raise ValueError("Vinted-Verkaufsaktion passt nicht zu der lokalen Kleinanzeigen-Verknüpfung")
    ad = _read_ad_yaml(slug) or {}
    account_id = _ad_account_id(slug, meta, state)
    remote_id = str(ad.get("id") or "").strip()
    title = str(payload.get("title") or ad.get("title") or slug).replace("\n", " ").strip()[:180]
    _mark_cross_platform_terminal(slug, "Vinted-Verkauf bestätigt")
    print(f"[vinted-cross] sold cleanup deleting Kleinanzeigen live/template for {slug}", flush=True)
    if remote_id:
        # This is deliberately one attempt.  A transport error after delete is
        # ambiguous, therefore the action becomes a visible .failed record
        # instead of repeating a destructive request.
        _direct_delete_remote(account_id, remote_id, sold=False)
    else:
        _delete_local_slug(slug)
    path.unlink(missing_ok=True)
    _notify_primary_critical(
        "Vinted · Artikel verkauft",
        f"Artikel: {title}\nDie Anzeige wurde bei Vinted und Kleinanzeigen gelöscht.",
        click_url=PUBLIC_BASE_URL,
    )
    print(f"[vinted-cross] sold cleanup completed for {slug}", flush=True)


def _vinted_sold_cleanup_loop() -> None:
    while True:
        try:
            VINTED_SOLD_ACTION_INBOX_DIR.mkdir(parents=True, exist_ok=True)
            for path in sorted(VINTED_SOLD_ACTION_INBOX_DIR.glob("*.json")):
                try:
                    _process_vinted_sold_cleanup(path)
                except Exception as exc:
                    print(f"[vinted-cross] cleanup failed for {path.name}: {exc}", flush=True)
                    try:
                        payload = json.loads(path.read_text("utf-8"))
                        _mark_vinted_cross_action_failed(path, payload if isinstance(payload, dict) else {}, exc)
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[vinted-cross] action monitor failed: {exc}", flush=True)
        time.sleep(VINTED_CROSS_ACTION_POLL_SECONDS)


def _queue_vinted_transfer(slug: str, state: dict[str, Any]) -> tuple[str, str]:
    ad = _read_ad_yaml(slug)
    if not ad:
        return "error", "Anzeige nicht gefunden"
    meta = state.setdefault("ads", {}).setdefault(slug, {})
    status = str(meta.get("vinted_transfer_status") or "").strip().lower()
    if status in {"queued", "imported"}:
        return "skipped", "bereits an Vinted übergeben"
    source_id = _vinted_transfer_source_id(slug)
    images = _list_ad_images(slug)
    image_members: list[str] = []
    VINTED_TRANSFER_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    package = VINTED_TRANSFER_INBOX_DIR / f"ka-{slug}.ka2vinted"
    temporary = package.with_suffix(".tmp")
    price_cfg = _price_reduction_config(ad)
    manifest = {
        "schema": 1,
        "source_platform": "kleinanzeigen",
        "source_id": source_id,
        "source_slug": slug,
        "source_account": _account_name(_ad_account_id(slug, meta, state), state),
        "created_at": _now(),
        "title": str(ad.get("title") or "").strip(),
        "description": str(ad.get("description") or "").strip(),
        "price": ad.get("price"),
        "price_type": str(ad.get("price_type") or "").strip(),
        "category": str(ad.get("category") or "").strip(),
        "automation": {
            "active": bool(ad.get("active", True)),
            "renew_interval_days": int(ad.get("republication_interval") or REPUBLISH_INTERVAL),
            "price_reduction_enabled": bool(price_cfg.get("enabled")),
            "price_reduction_days": int(price_cfg.get("days") or DEFAULT_PRICE_REDUCTION_DAYS),
            "price_drop": float(price_cfg.get("drop") or 0),
            "min_price": float(price_cfg.get("min_price") or 0),
        },
        "images": image_members,
    }
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, image_name in enumerate(images[:20], 1):
                source = _ad_images_dir(slug) / image_name
                if not source.is_file():
                    continue
                suffix = source.suffix.lower()
                if suffix not in IMPORT_IMAGE_EXTENSIONS:
                    continue
                member = f"images/{index:02d}{suffix}"
                archive.write(source, member)
                image_members.append(member)
            manifest["images"] = image_members
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(temporary, package)
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return "error", str(exc) or exc.__class__.__name__
    meta["vinted_transfer_source_id"] = source_id
    meta["vinted_transfer_status"] = "queued"
    meta["vinted_transfer_queued_at"] = _now()
    meta["vinted_transfer_message"] = "Wartet auf Import durch den Vinted Manager"
    meta.setdefault("history", []).append({"action": "an Vinted übergeben", "date": _now()})
    state.setdefault("ads", {})[slug] = meta
    return "queued", "an Vinted übergeben"


def _index_return_context(values, prefix=""):
    status_filter = str(values.get(prefix + "status", "all") or "all").strip().lower()
    if status_filter not in {"all", "online", "planned", "unpublished"}:
        status_filter = "all"

    sort_by = str(values.get(prefix + "sort", "next_due") or "next_due").strip().lower()
    if sort_by not in {"default", "newest", "oldest", "title", "no_id", "due", "next_due", "account", "paused"}:
        sort_by = "next_due"

    folder_filter = str(values.get(prefix + "folder", "all") or "all").strip()
    folders = _all_folders()
    if folder_filter not in {"all", "__none__"} and folder_filter not in folders:
        folder_filter = "all"

    search_query = str(values.get(prefix + "q", "") or "").strip()[:300]
    state = _load_state()
    account_filter = str(values.get(prefix + "account", "all") or "all").strip()
    if account_filter != "all" and account_filter not in _accounts_from_state(state):
        account_filter = "all"
    return {
        "status": status_filter,
        "q": search_query,
        "sort": sort_by,
        "folder": folder_filter,
        "account": account_filter,
    }


def _index_return_url(values, prefix=""):
    return url_for("index", **_index_return_context(values, prefix=prefix))


@app.route("/profile-login", methods=["GET", "POST"])
def profile_login():
    if request.method == "POST":
        # 1.6.1: Im privaten Haushaltsbetrieb reicht die bewusste Profilauswahl.
        # Die hinterlegten E-Mail-Adressen bleiben die stabile Profilzuordnung,
        # müssen auf neuen Geräten aber nicht mehr eingetippt werden.
        profile_id = str(request.form.get("profile_id") or "").strip().lower()
        user = APP_USERS.get(profile_id)
        # Kompatibilitätsfallback für einen eventuell noch offenen 1.6.0-Tab.
        if not user:
            user = _app_user_by_email(request.form.get("email"))
        if not user:
            flash("Bitte ein Profil auswählen.", "err")
            return render_template("profile_login.html", allowed_users=_app_users_for_display()), 403
        user = dict(user)
        # Gemeinsame Ausgangsbasis anlegen, bevor dieses Profil irgendeinen
        # Chat als gelesen markieren kann. Danach bleiben beide Lesestände
        # vollständig getrennt und geräteübergreifend synchron.
        _ensure_user_message_baseline(user["id"], [])
        session.clear()
        session.permanent = True
        session["app_user_id"] = user["id"]
        session["app_user_email"] = user["email"]
        return redirect(url_for("messages_view", account="all"))
    if _current_app_user():
        return redirect(url_for("messages_view", account="all"))
    return render_template("profile_login.html", allowed_users=_app_users_for_display())


@app.route("/profile-switch", methods=["POST"])
def profile_switch():
    session.clear()
    return redirect(url_for("profile_login"))


@app.route("/")
def home():
    return redirect(url_for("messages_view", account="all"))


@app.route("/anzeigen")
def index():
    state = _load_state()
    operation_snapshot = _operation_snapshot()
    if _sync_vinted_transfer_receipts(state):
        _save_state(state)
    ads_meta = state.get("ads", {})
    status_filter = request.args.get("status", "all").strip().lower()
    if status_filter not in {"all", "online", "planned", "unpublished"}:
        status_filter = "all"
    search_query = request.args.get("q", "").strip()
    sort_by = request.args.get("sort", "next_due").strip().lower()
    if sort_by not in {"default", "newest", "oldest", "title", "no_id", "due", "next_due", "account", "paused"}:
        sort_by = "next_due"
    folder_filter = request.args.get("folder", "all").strip()
    account_filter = request.args.get("account", "all").strip()
    if account_filter != "all" and account_filter not in _accounts_from_state(state):
        account_filter = "all"
    folders = _all_folders()
    if folder_filter != "all" and folder_filter != "__none__" and folder_filter not in folders:
        folder_filter = "all"

    ads = []
    unpublished_count = _count_unpublished_ads(state)
    now_utc = datetime.now(timezone.utc)
    for p in sorted(ADS_DIR.glob("*.yaml")):
        slug = p.stem
        ad_data = _read_ad_yaml(slug)
        if not ad_data:
            continue
        meta = ads_meta.get(slug, {})
        account_id = _ad_account_id(slug, meta, state)
        account_name = _account_name(account_id, state)
        if account_filter != "all" and account_id != account_filter:
            continue
        folder = str(ad_data.get("folder", "")).strip()
        if folder_filter == "__none__" and folder:
            continue
        if folder_filter not in ("all", "__none__") and folder != folder_filter:
            continue
        is_active = ad_data.get("active", True)
        has_id = bool(ad_data.get("id"))
        republish_transaction = _republish_transaction(meta)
        is_republish_pending = bool(republish_transaction) and str(republish_transaction.get("phase") or "") != "publish_failed"
        scheduled_at = meta.get("scheduled_publish_at")
        scheduled_dt = _iso_dt(scheduled_at)
        postponed_dt = _iso_dt(meta.get("republish_postponed_until"))
        is_postponed = bool(postponed_dt) and postponed_dt > now_utc
        is_schedule_due = is_active and not bool(meta.get("last_published")) and bool(scheduled_dt) and scheduled_dt <= now_utc
        is_scheduled_future = is_active and not bool(meta.get("last_published")) and bool(scheduled_dt) and scheduled_dt > now_utc
        is_online = is_active and (bool(meta.get("last_published")) or (has_id and not is_scheduled_future and not is_schedule_due))
        is_planned = is_active and not is_online
        is_unpublished = not bool(meta.get("last_published")) and not has_id and not is_republish_pending

        if status_filter == "online" and not is_online:
            continue
        if status_filter == "planned" and not is_planned:
            continue
        if status_filter == "unpublished" and not is_unpublished:
            continue

        haystack = " ".join([
            str(ad_data.get("title", "")),
            str(ad_data.get("description", "")),
            str(ad_data.get("category", "")),
            str(ad_data.get("folder", "")),
            account_name,
            slug,
        ]).lower()
        created_ref = _age_reference_iso(slug, ad_data, meta) or _now()
        age = _age_days(created_ref)
        republish_interval = int(ad_data.get("republication_interval") or REPUBLISH_INTERVAL)
        schedule_label = _scheduled_label(scheduled_at)
        is_stale = ((is_online and age >= republish_interval) or is_schedule_due) and not is_postponed
        price_cfg = _price_reduction_config(ad_data)
        price_automation_summary = ""
        if price_cfg["enabled"]:
            price_automation_summary = f"↓{_fmt_money(price_cfg['drop'])}€"
            if int(price_cfg["days"]) != int(republish_interval):
                price_automation_summary += f" / {int(price_cfg['days'])}T"
            if price_cfg["min_price"] > 0:
                price_automation_summary += f" · min. {_fmt_money(price_cfg['min_price'])}€"
        price_drop_label = price_automation_summary or "aus"
        renewal_count = max(0, int(meta.get("publish_count") or 0) - 1)
        online_age_detail = "seit heute online" if age == 0 else f"seit {age} {'Tag' if age == 1 else 'Tagen'} online"
        renewal_interval_detail_label = f"Erneuerung: alle {republish_interval} {'Tag' if republish_interval == 1 else 'Tage'} · {online_age_detail}"
        price_automation_detail_label, price_due_dt = _price_automation_detail(slug, ad_data, meta, created_ref, now_utc=now_utc)

        ref_dt = _iso_dt(created_ref)
        if is_postponed:
            next_due_dt = postponed_dt
        elif is_schedule_due or is_scheduled_future:
            next_due_dt = scheduled_dt
        elif is_online and ref_dt:
            next_due_dt = ref_dt + timedelta(days=republish_interval)
        else:
            next_due_dt = None
        next_due_days = None
        next_due_label = ""
        if next_due_dt:
            local_due_dt = next_due_dt.astimezone(_local_tz())
            local_now_dt = now_utc.astimezone(_local_tz())
            next_due_days = (local_due_dt.date() - local_now_dt.date()).days
            due_time_label = local_due_dt.strftime("%H:%M")
            if next_due_days < 0:
                next_due_label = "fällig"
            elif next_due_days == 0:
                next_due_label = f"heute {due_time_label}"
            elif next_due_days == 1:
                next_due_label = f"morgen {due_time_label}"
            else:
                next_due_label = f"in {next_due_days}T fällig"

        renewal_prefix = "Noch nicht erneuert" if renewal_count == 0 else f"{renewal_count}× erneuert"
        renewal_due_detail_label = renewal_prefix
        if next_due_dt:
            due_detail = _relative_due_detail(next_due_dt, now_utc=now_utc)
            if due_detail == "jetzt fällig":
                renewal_due_detail_label += " · nächste Erneuerung jetzt fällig"
            elif due_detail:
                renewal_due_detail_label += f" · nächste Erneuerung {due_detail}"
        operation = copy.deepcopy(operation_snapshot.get("operations", {}).get(slug) or {})
        automation_failure_detail_label, automation_retry_detail_label = _operation_card_labels(operation, meta, now_utc=now_utc)

        paused_due_dt = None
        paused_overdue_days = 0
        paused_overdue_label = ""
        # Auch bei pausierten, zuvor veröffentlichten Anzeigen den normalen
        # Erneuerungstermin weiter berechnen. Die Pause stoppt die Automation,
        # soll aber nicht verbergen, wie lange die Anzeige bereits überfällig ist.
        if not is_active and ref_dt and (bool(meta.get("last_published")) or has_id):
            paused_due_dt = ref_dt + timedelta(days=republish_interval)
            local_paused_due = paused_due_dt.astimezone(_local_tz()).date()
            local_today = now_utc.astimezone(_local_tz()).date()
            paused_overdue_days = max(0, (local_today - local_paused_due).days)
            if paused_overdue_days == 1:
                paused_overdue_label = "seit 1 Tag überfällig"
            elif paused_overdue_days > 1:
                paused_overdue_label = f"seit {paused_overdue_days} Tagen überfällig"

        if not is_active:
            status_label = "Inaktiv"
        elif is_republish_pending:
            status_label = "Erneuerung wird geprüft"
        elif is_postponed:
            status_label = "Verschoben"
        elif is_schedule_due:
            status_label = "Termin fällig"
        elif is_scheduled_future:
            status_label = "Geplant"
        elif is_planned:
            status_label = "Geplant"
        elif is_stale:
            status_label = "Fällig"
        else:
            status_label = "Online"

        if is_scheduled_future or is_schedule_due:
            last_text = f"geplant für {schedule_label}" if schedule_label else "geplant"
        elif meta.get("last_published"):
            last_dt = _iso_dt(meta.get("last_published"))
            last_text = "zuletzt " + last_dt.astimezone(_local_tz()).strftime("%d.%m.%Y %H:%M") if last_dt else "zuletzt veröffentlicht"
        elif is_republish_pending:
            last_text = "alte Anzeige gelöscht · Neuveröffentlichung wird verifiziert"
        elif has_id:
            last_text = f"seit {age} {'Tag' if age == 1 else 'Tagen'} online"
        else:
            last_text = "noch nicht veröffentlicht"

        ads.append({
            "slug": slug,
            "yaml": ad_data,
            "meta": meta,
            "images": _list_ad_images(slug),
            "age": age,
            "has_id": has_id,
            "remote_id": str(ad_data.get("id") or "").strip(),
            "is_online": is_online,
            "is_planned": is_planned,
            "is_unpublished": is_unpublished,
            "is_republish_pending": is_republish_pending,
            "is_stale": is_stale,
            "is_schedule_due": is_schedule_due,
            "is_scheduled_future": is_scheduled_future,
            "is_postponed": is_postponed,
            "schedule_label": schedule_label,
            "created_dt": _iso_dt(created_ref),
            "last_dt": _iso_dt(meta.get("last_published")),
            "scheduled_dt": scheduled_dt,
            "next_due_dt": next_due_dt,
            "next_due_days": next_due_days,
            "next_due_label": next_due_label,
            "paused_due_dt": paused_due_dt,
            "paused_overdue_days": paused_overdue_days,
            "paused_overdue_label": paused_overdue_label,
            "search_text": haystack,
            "price_drop_label": price_drop_label,
            "price_automation_summary": price_automation_summary,
            "price_automation_detail_label": price_automation_detail_label,
            "price_due_dt": price_due_dt,
            "renewal_count": renewal_count,
            "renewal_interval_detail_label": renewal_interval_detail_label,
            "renewal_due_detail_label": renewal_due_detail_label,
            "automation_failure_detail_label": automation_failure_detail_label,
            "automation_retry_detail_label": automation_retry_detail_label,
            "vinted_transfer_status": str(meta.get("vinted_transfer_status") or ""),
            "vinted_draft_id": str(meta.get("vinted_draft_id") or ""),
            "vinted_transfer_message": str(meta.get("vinted_transfer_message") or ""),
            "folder": folder,
            "account_id": account_id,
            "account_name": account_name,
            "operation": operation,
            "sort_title": str(ad_data.get("title", "")).lower(),
            "status_line": f"{status_label} · {'ID vorhanden' if has_id else 'keine ID'} · {last_text}",
        })

    def _sort_tuple(item):
        created_ts = item["created_dt"].timestamp() if item.get("created_dt") else 0
        due_rank = 0 if item.get("is_stale") or item.get("is_schedule_due") else 1
        no_id_rank = 0 if not item.get("has_id") else 1
        next_due_ts = item["next_due_dt"].timestamp() if item.get("next_due_dt") else 9999999999
        if sort_by == "newest":
            return (-created_ts, item["sort_title"])
        if sort_by == "oldest":
            return (created_ts, item["sort_title"])
        if sort_by == "title":
            return (item["sort_title"], -created_ts)
        if sort_by == "no_id":
            return (no_id_rank, item["sort_title"], -created_ts)
        if sort_by == "due":
            return (due_rank, next_due_ts, item["sort_title"], -created_ts)
        if sort_by == "next_due":
            return (next_due_ts, item["sort_title"], -created_ts)
        if sort_by == "account":
            return (item.get("account_name", "").lower(), item["sort_title"], -created_ts)
        if sort_by == "paused":
            paused_rank = 0 if not item["yaml"].get("active", True) else 1
            paused_overdue_rank = -int(item.get("paused_overdue_days") or 0)
            return (paused_rank, paused_overdue_rank, item["sort_title"], -created_ts)
        active = item["yaml"].get("active", True)
        has_pub = bool(item["meta"].get("last_published"))
        if active and has_pub:
            bucket = 0
        elif active:
            bucket = 1
        else:
            bucket = 2
        return (bucket, -item["age"], item["sort_title"])

    ads.sort(key=_sort_tuple)
    due_preview = []
    for item in ads:
        if item.get("is_schedule_due"):
            due_preview.append({"title": item["yaml"].get("title", item["slug"]), "kind": "geplanter Termin erreicht"})
        elif item.get("is_stale"):
            due_preview.append({"title": item["yaml"].get("title", item["slug"]), "kind": "fällig zum Erneuern"})

    import_state = state.get("imports", {}) if isinstance(state.get("imports", {}), dict) else {}
    pending_notice = int(import_state.get("pending_notice") or 0)
    if pending_notice:
        noun = "Anzeige wurde" if pending_notice == 1 else "Anzeigen wurden"
        flash(f"{pending_notice} neue {noun} automatisch aus dem Importordner gespeichert.", "ok")
        import_state["pending_notice"] = 0
        state["imports"] = import_state
        _save_state(state)

    return render_template(
        "index.html",
        ads=ads,
        status_filter=status_filter,
        section="ads",
        q=search_query,
        sort_by=sort_by,
        folder_filter=folder_filter,
        account_filter=account_filter,
        account_records=_account_ui_records(state),
        folders=folders,
        due_preview=due_preview,
        unpublished_count=unpublished_count,
        import_status=_import_status_for_ui(state),
        quota_summary=_live_quota_summary(),
    )

@app.route("/anzeigen/<slug>/history")
def ad_history(slug):
    ad = _read_ad_yaml(slug)
    if not ad:
        abort(404)
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {}) if isinstance(state.get("ads", {}), dict) else {}
    account_id = _ad_account_id(slug, meta, state)
    raw_history = [dict(row) for row in (meta.get("history") or []) if isinstance(row, dict)]
    price_history = _price_history_summary(ad, raw_history)
    history = []
    for row in raw_history:
        item = dict(row)
        action = str(item.get("action") or "Änderung")
        pair = _history_price_pair(item)
        source = str(item.get("source") or "").strip().lower()
        if pair:
            item["old_price_label"] = _fmt_money(pair[0])
            item["new_price_label"] = _fmt_money(pair[1])
            if action.lower().startswith("preis gesenkt:"):
                action = "Automatische Preissenkung"
                source = source or "automatic"
        item["action"] = action
        item["source_label"] = (
            "manuell" if source == "manual" else
            "automatisch" if source == "automatic" else
            "System" if source == "system" else
            source
        )
        item["date_label"] = datefmt_filter(item.get("date")) if item.get("date") else "Zeitpunkt unbekannt"
        item["sort_dt"] = _iso_dt(item.get("date")) or datetime.min.replace(tzinfo=timezone.utc)
        history.append(item)
    history.sort(key=lambda row: row.get("sort_dt"), reverse=True)
    history = history[:100]
    price_cfg = _price_reduction_config(ad)
    return render_template(
        "history.html",
        section="ads",
        slug=slug,
        ad=ad,
        meta=meta,
        history=history,
        account_name=_account_name(account_id, state),
        renewal_count=max(0, int(meta.get("publish_count") or 0) - 1),
        republish_days=int(ad.get("republication_interval") or REPUBLISH_INTERVAL),
        price_cfg=price_cfg,
        price_history=price_history,
        price_summary=(
            f"−{_fmt_money(price_cfg.get('drop') or 0)} € alle {int(price_cfg.get('days') or DEFAULT_PRICE_REDUCTION_DAYS)} Tage"
            + (f" · Mindestpreis {_fmt_money(price_cfg.get('min_price'))} €" if float(price_cfg.get("min_price") or 0) > 0 else "")
            if price_cfg.get("enabled") else "aus"
        ),
    )


@app.route("/imports/refresh", methods=["POST"])
def refresh_imports():
    result = _process_import_files(trigger="manual")
    if result.get("busy"):
        flash("Der Import wird bereits geprüft.", "info")
        return redirect(request.referrer or url_for("index"))

    imported = int(result.get("imported") or 0)
    failed = int(result.get("failed") or 0)
    if imported and not failed:
        if imported == 1:
            flash("1 neue Anzeige wurde gespeichert.", "ok")
        else:
            flash(f"{imported} neue Anzeigen wurden gespeichert.", "ok")
    elif imported and failed:
        flash(f"{imported} neue Anzeigen wurden gespeichert. {failed} Datei(en) wurden in den Fehlerordner verschoben.", "warn")
    elif failed:
        flash(f"Keine Anzeige importiert. {failed} Datei(en) wurden in den Fehlerordner verschoben.", "err")
    else:
        flash("Keine neuen Importdateien gefunden.", "info")

    if imported:
        return redirect(url_for("index", status="unpublished", sort="newest"))
    return redirect(request.referrer or url_for("index"))


# -- Routes: Folders --

@app.route("/folders/create", methods=["POST"])
def create_folder():
    folder = (request.form.get("folder_name") or "").strip()
    if not folder:
        flash("Bitte einen Ordnernamen eingeben.", "warn")
        return redirect(request.referrer or url_for("index"))
    _add_folder(folder)
    flash(f"Ordner '{folder}' angelegt.", "ok")
    return redirect(url_for("index", folder=folder, sort=request.args.get("sort", "next_due")))


@app.route("/folders/delete", methods=["POST"])
def delete_folder_route():
    folder = (request.form.get("folder") or "").strip()
    if not folder:
        flash("Bitte einen Ordner auswählen.", "warn")
        return redirect(request.referrer or url_for("index"))
    _create_backup(reason="vor-ordner-loeschen")
    changed = _delete_folder(folder)
    flash(f"Ordner '{folder}' gelöscht" + (f" und bei {changed} Anzeigen entfernt." if changed else "."), "ok")
    return redirect(url_for("index", folder="all", sort=request.args.get("sort", "next_due")))



# -- Direct Kleinanzeigen Mobile API / Messages / Live Ads / Web Push --

def _account_api_token_path(account_id):
    account_id = _valid_account_id(account_id)
    return _account_workspace(account_id) / API_TOKEN_DIR_NAME / "token.json"


def _api_authenticator(account_id):
    from kleinanzeigen_api import Authenticator
    path = _account_api_token_path(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Authenticator(token_path=str(path))


def _api_account_status(account_id):
    """Schneller Statuscheck ohne curl_cffi/Authenticator aufzubauen.

    Diese Funktion wird bei fast jedem Seitenrender gebraucht. Für die Anzeige
    reichen die bereits lokal gespeicherten Token-Metadaten völlig aus.
    """
    try:
        path = _account_api_token_path(account_id)
        data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return {
            "connected": bool(data.get("refresh_token")),
            "email": str(data.get("email") or ""),
        }
    except Exception as exc:
        return {"connected": False, "email": "", "error": str(exc)}


def _api_client(account_id, require_login=True):
    from kleinanzeigen_api import KleinanzeigenAPI
    account_id = _valid_account_id(account_id)
    auth = _api_authenticator(account_id)
    if require_login and not auth.logged_in:
        raise RuntimeError(f"API von '{_account_name(account_id)}' ist noch nicht verbunden.")
    return KleinanzeigenAPI(authenticator=auth), auth


def _conversation_dict(conv, account_id):
    raw = conv.to_dict() if hasattr(conv, "to_dict") else dict(conv or {})
    raw["account_id"] = account_id
    raw["account_name"] = _account_name(account_id)
    return raw


def _profile_user_id_scalar(value):
    """Numerische Kleinanzeigen-User-ID aus Skalaren oder Profil-URLs lesen."""
    value = _raw_scalar(value)
    if not isinstance(value, (str, int)):
        return ""
    text = str(value).strip()
    match = re.search(r"(?:[?&]userId=|\buserId[=:/_-]?)(\d{3,})", text, re.I)
    if match:
        return match.group(1)
    return text if text.isdigit() and len(text) >= 3 else ""


def _extract_counterparty_user_id(raw, *, role="", own_user_id=""):
    """Best-effort Gegenstellen-ID auch aus verschachtelten Gateway-Daten lesen.

    Die Conversation-Liste liefert je nach Backend-Version nicht dieselbe Form:
    IDs können top-level (buyerId/sellerId), unter buyer/seller/user/participant
    oder erst in einer eingehenden Nachricht als senderUserId auftauchen.
    """
    raw = raw if isinstance(raw, dict) else {}
    role = str(role or raw.get("role") or "").upper()
    own_user_id = str(own_user_id or "").strip()
    target = "seller" if role == "BUYER" else "buyer" if role == "SELLER" else ""
    scores = {}

    def add(value, score):
        uid = _profile_user_id_scalar(value)
        if not uid or uid == own_user_id:
            return
        scores[uid] = max(int(score), scores.get(uid, -1))

    normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in raw.items()}
    # Beide Reihenfolgen kommen in der mobilen Conversation-Antwort vor:
    # buyerId / sellerId ebenso wie userIdBuyer / userIdSeller.
    preferred = (("sellerid", "selleruserid", "useridseller", "accountidseller") if target == "seller" else
                 ("buyerid", "buyeruserid", "useridbuyer", "accountidbuyer") if target == "buyer" else ())
    for key in preferred:
        if key in normalized:
            add(normalized.get(key), 120)

    def walk(node, path=()):
        if isinstance(node, dict):
            for key, value in node.items():
                nk = re.sub(r"[^a-z0-9]", "", str(key).lower())
                new_path = path + (nk,)
                ctx = " ".join(new_path)
                # Rollenbezogene IDs sind am zuverlässigsten, auch wenn nur ein
                # verschachteltes {buyer/seller: {id: ...}} geliefert wird.
                if target and target in ctx:
                    if nk in {"id", "userid", "user", "accountid", "profileid"} or nk.endswith("userid") or (target in nk and nk.endswith("id")):
                        add(value, 110)
                if nk in {"counterpartyid", "counterpartyuserid", "otheruserid", "otheruser", "participantuserid"}:
                    add(value, 100)
                if any(x in ctx for x in ("counterparty", "participant", "otheruser")) and nk in {"id", "userid", "accountid", "profileid"}:
                    add(value, 95)
                # Some gateway responses expose the other participant as
                # {"user": {"id": ...}} without a seller/buyer wrapper.
                # This is still a counterparty ID here: incoming messages are
                # filtered by _counterparty_profile_url_from_thread below.
                if "user" in ctx and nk in {"id", "userid", "accountid", "profileid"}:
                    add(value, 80)
                # Beim vollständigen Thread ist der Absender einer eingehenden
                # Nachricht die Gegenpartei. Eigene IDs werden später verworfen.
                if any(x in ctx for x in ("sender", "from", "fromuser", "author")) and (nk == "id" or nk.endswith("id") or nk == "userid"):
                    add(value, 85)
                if nk in {"senderid", "senderuserid", "fromid", "fromuserid", "authorid", "authoruserid"}:
                    add(value, 90)
                # Einige Gateway-Antworten liefern die Teilnehmer-ID direkt
                # als Skalar unter sender/from/user/participant.
                if nk in {"sender", "from", "user", "participant", "author"}:
                    add(value, 80)
                # Generische userId nur als letzter Fallback; own_user_id wird ausgeschlossen.
                if nk == "userid":
                    add(value, 40)
                walk(value, new_path)
        elif isinstance(node, (list, tuple)):
            for idx, child in enumerate(node):
                walk(child, path + (str(idx),))
    walk(raw)
    if not scores:
        return ""
    best_score = max(scores.values())
    best = sorted(uid for uid, score in scores.items() if score == best_score)
    return best[0] if len(best) == 1 else ""


def _counterparty_profile_url(raw, *, role="", own_user_id=""):
    raw = raw if isinstance(raw, dict) else {}
    role = str(role or raw.get("role") or "").upper()
    target = "seller" if role == "BUYER" else "buyer" if role == "SELLER" else ""

    # Echte Profil-URL aus beliebiger Verschachtelung bevorzugen.
    urls = []
    def walk_urls(node, path=()):
        if isinstance(node, dict):
            for key, value in node.items():
                nk = re.sub(r"[^a-z0-9]", "", str(key).lower())
                new_path = path + (nk,)
                scalar = _raw_scalar(value)
                if isinstance(scalar, str) and "kleinanzeigen.de" in scalar and "userId=" in scalar:
                    score = 100 if target and target in " ".join(new_path) else 70
                    urls.append((score, scalar.strip()))
                walk_urls(value, new_path)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk_urls(child, path)
    walk_urls(raw)
    if urls:
        urls.sort(key=lambda x: x[0], reverse=True)
        return urls[0][1]

    uid = _extract_counterparty_user_id(raw, role=role, own_user_id=own_user_id)
    return f"https://www.kleinanzeigen.de/s-bestandsliste.html?userId={uid}" if uid else ""


def _message_is_received(message):
    """Eingehende Nachricht auch bei alternativen Gateway-Bezeichnungen erkennen."""
    item = message if isinstance(message, dict) else {}
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    values = (
        item.get("direction"), item.get("boundness"),
        raw.get("direction"), raw.get("boundness"),
    )
    for value in values:
        token = str(value or "").strip().lower().replace("-", "_")
        if token in {"received", "receive", "in", "incoming", "inbound", "inbound_message"}:
            return True
        if token.startswith(("received_", "incoming_", "inbound_")):
            return True
    return False


def _counterparty_profile_url_from_thread(messages, *, role="", own_user_id=""):
    """Profil-ID aus eingehenden Nachrichten des vollständigen Threads ableiten."""
    candidates = []
    for message in messages or []:
        if not _message_is_received(message):
            continue
        raw = (message or {}).get("raw") or message
        url = _counterparty_profile_url(raw, role=role, own_user_id=own_user_id)
        if url and url not in candidates:
            candidates.append(url)
    return candidates[0] if len(candidates) == 1 else ""


def _cache_conversation_profile_url(account_id, conversation_id, profile_url):
    if not profile_url:
        return
    cache = _read_api_cache("messages", account_id)
    changed = False
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") == str(conversation_id):
            if item.get("profile_url") != profile_url:
                item["profile_url"] = profile_url
                changed = True
            break
    if changed:
        _write_api_cache("messages", account_id, cache.get("items", []))


def _resolve_conversation_profile_url(account_id, conversation_id, conv=None, allow_network=False):
    """Profil-Link aus Cache-Daten oder beim ausdrücklichen Klick nachladen.

    Die Nachrichtenansicht bleibt ohne Netzwerk-Nachladen sofort verfügbar. Nur
    der explizite Profil-Klick darf den vollständigen Thread nachladen.
    """
    account_id = _valid_account_id(account_id)
    conv = dict(conv or {})
    role = str(conv.get("role") or "").upper()
    existing = str(conv.get("profile_url") or "").strip()
    if existing:
        return existing

    thread = _read_thread_cache(account_id, conversation_id)
    url = _counterparty_profile_url_from_thread(
        thread.get("messages") or [], role=role, own_user_id=""
    )

    if not url:
        url = _counterparty_profile_url(
            thread.get("conversation_raw") or {}, role=role, own_user_id=""
        )

    if not url:
        url = _counterparty_profile_url(conv, role=role, own_user_id="")

    # Der Profil-Button darf beim ersten Klick einen noch nicht fertig
    # aktualisierten Thread-Cache nachladen. Die Nachrichtenansicht selbst
    # bleibt weiterhin nicht blockierend; nur die ausdrückliche Profilaktion
    # wartet auf die bereits ohnehin benötigten Threaddaten.
    if not url and allow_network:
        fresh = _fetch_thread_to_cache(account_id, conversation_id)
        url = _counterparty_profile_url_from_thread(
            fresh.get("messages") or [], role=role, own_user_id=""
        )
        if not url:
            url = _counterparty_profile_url(
                fresh.get("conversation_raw") or {}, role=role, own_user_id=""
            )
        if not url:
            url = _counterparty_profile_url(conv, role=role, own_user_id="")

    if url:
        _cache_conversation_profile_url(account_id, conversation_id, url)
    return url


def _conversation_counterparty_user_id(account_id, conversation_id, conv=None, allow_network=False):
    """Gegenstellen-ID aus den vollständigen Gesprächsdaten ermitteln."""
    account_id = _valid_account_id(account_id)
    conv = dict(conv or {})
    role = str(conv.get("role") or "").upper()
    thread = _read_thread_cache(account_id, conversation_id)
    raw_candidates = [
        thread.get("conversation_raw") or {},
        conv.get("raw") if isinstance(conv.get("raw"), dict) else {},
        conv,
    ]
    for raw in raw_candidates:
        uid = _extract_counterparty_user_id(raw, role=role, own_user_id="")
        if uid:
            return uid

    if allow_network:
        fresh = _fetch_thread_to_cache(account_id, conversation_id)
        for raw in (
            fresh.get("conversation_raw") or {},
            conv.get("raw") if isinstance(conv.get("raw"), dict) else {},
            conv,
        ):
            uid = _extract_counterparty_user_id(raw, role=role, own_user_id="")
            if uid:
                return uid
    return ""


def _profile_diagnostic_shape(value, depth=0):
    """Nur Struktur, niemals Gesprächs- oder Profildaten, für die Fehlersuche."""
    if depth >= 3:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value.keys())[:60]
        return {
            "type": "object",
            "keys": keys,
            "children": {
                key: _profile_diagnostic_shape(value.get(key), depth + 1)
                for key in keys[:20]
            },
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "item": _profile_diagnostic_shape(value[0], depth + 1) if value else None,
        }
    return {"type": type(value).__name__}


def _profile_diagnostic_key_paths(value, path=(), out=None):
    """Nur interessante Feldnamen aus der API-Antwort, ohne Werte, sammeln."""
    if out is None:
        out = []
    if len(out) >= 80 or len(path) >= 5:
        return out
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key)
            child_path = path + (name,)
            lowered = name.lower()
            if any(token in lowered for token in ("user", "buyer", "seller", "profile", "reputation", "participant", "member")):
                dotted = ".".join(child_path)
                if dotted not in out:
                    out.append(dotted)
            _profile_diagnostic_key_paths(child, child_path, out)
    elif isinstance(value, list):
        for child in value[:3]:
            _profile_diagnostic_key_paths(child, path + ("[]",), out)
    return out


def _profile_diagnostics(account_id, conversation_id, conv=None):
    """Diagnose des mobilen Profilwegs ohne personenbezogene Werte preiszugeben."""
    account_id = _valid_account_id(account_id)
    conv = dict(conv or {})
    role = str(conv.get("role") or "").upper()
    report = {
        "status": "started",
        "role": role,
        "profile_id_found": False,
        "profile_request": "not_started",
        "conversation_shape": None,
        "interesting_key_paths": [],
        "reputation_context_shapes": [],
        "message_count": 0,
    }
    try:
        api, _auth = _api_client(account_id)
        conversation = api.conversation(str(conversation_id))
        if not isinstance(conversation, dict):
            report["status"] = "conversation_unknown_format"
            return report
        metadata = _conversation_metadata(conversation)
        messages = _thread_messages_from_conversation(conversation)
        report["status"] = "conversation_loaded"
        report["conversation_shape"] = _profile_diagnostic_shape(metadata)
        report["interesting_key_paths"] = _profile_diagnostic_key_paths(metadata)
        report["message_count"] = len(messages)
        contexts = []
        for message in messages:
            raw = (message or {}).get("raw") or {}
            if "userReputationContext" in raw:
                contexts.append(_profile_diagnostic_shape(raw.get("userReputationContext")))
        report["reputation_context_shapes"] = contexts[:5]

        user_id = _extract_counterparty_user_id(metadata, role=role, own_user_id="")
        report["profile_id_found"] = bool(user_id)
        if not user_id:
            report["status"] = "profile_id_missing"
            return report
        try:
            profile = _fetch_public_profile(account_id, user_id)
            report["profile_request"] = "loaded"
            report["profile_shape"] = _profile_diagnostic_shape(profile)
            report["status"] = "profile_loaded"
        except Exception as exc:
            report["profile_request"] = "failed"
            report["profile_error_type"] = type(exc).__name__
            report["status"] = "profile_request_failed"
        return report
    except Exception as exc:
        report["status"] = "conversation_request_failed"
        report["conversation_error_type"] = type(exc).__name__
        return report


def _fetch_public_profile(account_id, user_id):
    """Öffentliches Profil wie in der mobilen App laden."""
    user_id = _profile_user_id_scalar(user_id)
    if not user_id:
        raise ValueError("Keine gültige Profil-ID vorhanden.")
    try:
        from kleinanzeigen_api.client import API_HOST
    except Exception:
        API_HOST = "https://api.kleinanzeigen.de"
    api, _auth = _api_client(account_id)
    response = api._get(f"{API_HOST}/api/users/public/{user_id}/profile.json")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Das Profil wurde in einem unbekannten Format geliefert.")
    return data


def _profile_find_value(data, aliases):
    """Ersten passenden Profilwert unabhängig von der Schreibweise finden."""
    wanted = {re.sub(r"[^a-z0-9]", "", str(alias).lower()) for alias in aliases}
    if isinstance(data, dict):
        for key, value in data.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in wanted and value not in (None, "", [], {}):
                return value
        for value in data.values():
            found = _profile_find_value(value, aliases)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(data, list):
        for value in data:
            found = _profile_find_value(value, aliases)
            if found not in (None, "", [], {}):
                return found
    return ""


def _profile_badges(value):
    """Badge-/Label-Liste für eine einfache, stabile Darstellung aufbereiten."""
    if isinstance(value, dict):
        for key in ("badges", "labels", "items", "values", "data"):
            if key in value:
                return _profile_badges(value[key])
        for key in ("name", "label", "title", "text"):
            if value.get(key):
                return [_profile_badge_label(value[key])]
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_profile_badges(item))
        return list(dict.fromkeys(out))
    if value not in (None, ""):
        return [_profile_badge_label(value)]
    return []


def _profile_badge_label(value):
    """Technische Badge-Kürzel der mobilen API verständlich darstellen."""
    raw = str(value or "").strip()
    labels = {
        "rating": "TOP Zufriedenheit",
        "friendliness": "Besonders freundlich",
        "reliability": "Besonders zuverlässig",
        "replyspeed": "Antwortet meist innerhalb von 24 Stunden",
        "replyrate": "Antwortet meist innerhalb von 24 Stunden",
        "followers": "Follower",
    }
    return labels.get(re.sub(r"[^a-z0-9]", "", raw.lower()), raw)


def _profile_text(value):
    """Verschachtelte Profilwerte lesbar und ohne Python-Dict-Darstellung ausgeben."""
    if isinstance(value, dict):
        for key in ("label", "name", "title", "text", "value", "average", "score", "count", "total"):
            if value.get(key) not in (None, "", [], {}):
                return _profile_text(value[key])
        parts = []
        for key, item in value.items():
            rendered = _profile_text(item)
            if rendered:
                parts.append(f"{key}: {rendered}")
        return ", ".join(parts)
    if isinstance(value, list):
        return ", ".join(filter(None, (_profile_text(item) for item in value)))
    return str(value).strip() if value not in (None, "") else ""


def _profile_date(value):
    text = _profile_text(value)
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    return f"{match.group(3)}.{match.group(2)}.{match.group(1)}" if match else text


def _profile_rating(value):
    """Bewertung kompakt und menschenlesbar ausgeben statt Rohwerten."""
    score = _profile_rating_score(value)
    if score is not None:
        return f"{score} %"
    text = _profile_text(value)
    normalized = text.replace(",", ".")
    try:
        score = float(normalized)
    except (TypeError, ValueError):
        return text
    if 0 <= score <= 1:
        return f"{round(score * 100)} %"
    if 1 < score <= 5:
        return (f"{score:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " / 5")
    return text


def _profile_rating_score(value):
    """Mobile averageRating (0 bis 1) in einen klaren Prozentwert umrechnen."""
    text = _profile_text(value)
    try:
        score = float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return round(score * 100) if 0 <= score <= 1 else None


def _profile_safety_check(profile):
    """Neutralen Profilhinweis erzeugen, nie eine Betrugsbewertung behaupten."""
    raw_rating = _profile_find_value(
        profile if isinstance(profile, dict) else {},
        ("averageRating", "rating", "ratings", "reputation", "feedback"),
    )
    score = _profile_rating_score(raw_rating)
    if score is None:
        return {
            "level": "unknown",
            "score": None,
            "label": "? Bewertung nicht angegeben",
            "detail": "Öffentliche Profilbewertung nicht vorhanden.",
        }
    if score >= 80:
        level, label = "good", f"✓ Gute Bewertung · {score} %"
    elif score >= 50:
        level, label = "check", f"⚠ Bewertung prüfen · {score} %"
    else:
        level, label = "caution", f"⚠ Vorsicht · {score} %"
    return {
        "level": level,
        "score": score,
        "label": label,
        "detail": f"Öffentliche Zufriedenheit: {score} %.",
    }


def _profile_initials(name):
    parts = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", str(name or ""))
    if not parts:
        return "?"
    if len(parts) == 1:
        compact = parts[0]
        return compact[:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def _profile_summary(profile, fallback_name=""):
    """Mobile-Profilantwort in die für die Ansicht benötigten Felder umwandeln."""
    profile = profile if isinstance(profile, dict) else {}
    badges = _profile_badges(_profile_find_value(profile, ("badges", "labels", "achievements", "reputationBadges")))
    # Antwortzeit steht unten ausführlicher im grünen Informationsstreifen;
    # Follower bleiben als Kennzahl sichtbar, aber nicht als lila Badge.
    badges = [badge for badge in badges if badge not in {
        "Follower", "Antwortet meist innerhalb von 24 Stunden",
    }]
    name = str(_profile_find_value(profile, ("contactName", "name", "displayName", "username", "userName", "nickname")) or fallback_name or "Unbekannt").strip()
    rating_value = _profile_find_value(profile, ("averageRating", "rating", "ratings", "reputation", "feedback"))
    return {
        "name": name,
        "initials": _profile_initials(name),
        "since": _profile_date(_profile_find_value(profile, ("userSince", "user-since", "memberSince", "activeSince", "since"))),
        "account_type": _profile_text(_profile_find_value(profile, ("accountType", "sellerAccountType", "posterType", "type"))).replace("PRIVATE", "Privater Anbieter").replace("COMMERCIAL", "Gewerblicher Anbieter"),
        "response_time": _profile_text(_profile_find_value(profile, ("responseTime", "responseRate", "averageResponseTime", "replyTime", "replySpeed"))),
        "followers": _profile_text(_profile_find_value(profile, ("followers", "followerCount", "numberOfFollowers"))),
        "active_ads": _profile_text(_profile_find_value(profile, ("onlineAds", "activeAds", "activeAdsCount", "adsCount", "numberOfAds"))),
        "total_ads": _profile_text(_profile_find_value(profile, ("historicalAds", "totalAds", "allAds"))),
        "rating": _profile_rating(rating_value),
        "rating_score": _profile_rating_score(rating_value),
        "badges": badges,
    }


def _store_profile_check(account_id, conversation_id, check):
    """Ergebnis einer Hintergrund-Prüfung atomar beim Nachrichtenmonitor ablegen."""
    with _state_lock:
        state = json.loads(APP_STATE.read_text("utf-8")) if APP_STATE.exists() else {"ads": {}}
        monitor = state.setdefault("message_monitor", {})
        accounts = monitor.setdefault("accounts", {})
        record = accounts.setdefault(_valid_account_id(account_id, state), {})
        checks = record.setdefault("profile_checks", {})
        checks[str(conversation_id)] = dict(check or {})
        _save_state(state)


def _store_own_profile(account_id, profile):
    """Eigene öffentliche Profilübersicht eines Kontos atomar speichern."""
    with _state_lock:
        state = json.loads(APP_STATE.read_text("utf-8")) if APP_STATE.exists() else {"ads": {}}
        monitor = state.setdefault("message_monitor", {})
        accounts = monitor.setdefault("accounts", {})
        record = accounts.setdefault(_valid_account_id(account_id, state), {})
        record["own_profile"] = dict(profile or {})
        _save_state(state)


def _counterparty_user_id_for_background_check(account_id, conversation_id, conv):
    """Profil-ID abrufen, ohne den serverseitigen Lesestatus der Unterhaltung zu ändern."""
    user_id = _conversation_counterparty_user_id(account_id, conversation_id, conv, allow_network=False)
    if user_id:
        return user_id
    api, _auth = _api_client(account_id)
    fresh = api.conversation(str(conversation_id))
    metadata = _conversation_metadata(fresh)
    role = str((conv or {}).get("role") or metadata.get("role") or "").upper()
    for raw in (metadata, conv or {}):
        user_id = _extract_counterparty_user_id(raw, role=role, own_user_id="")
        if user_id:
            return user_id
    for message in _thread_messages_from_conversation(fresh):
        if _message_is_received(message):
            user_id = _extract_counterparty_user_id(message.get("raw") or {}, role=role, own_user_id="")
            if user_id:
                return user_id
    return ""


def _profile_check_worker(account_id, conversation_id, conv, event_key):
    """Profil der Gegenpartei außerhalb des 5-Sekunden-Polls abrufen."""
    key = (_valid_account_id(account_id), str(conversation_id))
    try:
        user_id = _counterparty_user_id_for_background_check(
            account_id, conversation_id, dict(conv or {})
        )
        if not user_id:
            check = {
                "level": "unknown", "score": None,
                "label": "? Bewertung nicht auslesbar",
                "detail": "Die öffentliche Profil-ID wurde nicht geliefert.",
            }
        else:
            check = _profile_safety_check(_fetch_public_profile(account_id, user_id))
            check["profile_user_id"] = user_id
        check.update({"checked_at": _now(), "event_key": str(event_key or "")})
        _store_profile_check(account_id, conversation_id, check)
    except Exception as exc:
        print(f"[messages] Profilhinweis für {conversation_id} konnte nicht geladen werden: {exc}", flush=True)
        _store_profile_check(account_id, conversation_id, {
            "level": "unknown", "score": None,
            "label": "? Bewertung nicht auslesbar",
            "detail": "Öffentliche Profilbewertung konnte gerade nicht geprüft werden.",
            "checked_at": _now(), "event_key": str(event_key or ""),
        })
    finally:
        with _profile_check_lock:
            _profile_checks_refreshing.discard(key)


def _schedule_profile_check(account_id, conversation_id, conv, event_key):
    """Pro neuer eingehender Nachricht genau einen nicht-blockierenden Profilcheck starten."""
    key = (_valid_account_id(account_id), str(conversation_id))
    with _profile_check_lock:
        if key in _profile_checks_refreshing:
            return
        _profile_checks_refreshing.add(key)
    threading.Thread(
        target=_profile_check_worker,
        args=(account_id, conversation_id, dict(conv or {}), event_key),
        daemon=True,
    ).start()


def _profile_check_is_fresh(check):
    if not isinstance(check, dict) or not check.get("checked_at"):
        return False
    try:
        checked_at = datetime.fromisoformat(str(check["checked_at"]))
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - checked_at).total_seconds() < PROFILE_CHECK_TTL_SECONDS
    except (TypeError, ValueError):
        return False


def _schedule_visible_profile_checks(conversations, state=None):
    """Beim Öffnen vorhandene Chats vorsichtig vorwärmen – maximal zwölf zugleich."""
    state = state if state is not None else _load_state()
    monitor_accounts = ((state.get("message_monitor") or {}).get("accounts") or {})
    for conv in list(conversations or [])[:12]:
        account_id = _valid_account_id((conv or {}).get("account_id"), state)
        conversation_id = str((conv or {}).get("id") or "")
        if not conversation_id:
            continue
        existing = (monitor_accounts.get(account_id, {}).get("profile_checks") or {}).get(conversation_id)
        if not _profile_check_is_fresh(existing):
            _schedule_profile_check(account_id, conversation_id, conv, _message_incoming_event_key(conv))


def _profile_backfill_worker(account_id):
    """Bereits vorhandene Unterhaltungen eines Kontos langsam nachprüfen.

    Der Abruf läuft einzeln und mit kleiner Pause, damit der erste Besuch der
    Nachrichtenansicht keine API-Spitze erzeugt. Er nutzt ausschließlich den
    lesestatusneutralen Hintergrundweg.
    """
    account_id = _valid_account_id(account_id)
    try:
        items = list((_read_api_cache("messages", account_id).get("items") or []))
        for conv in items:
            conversation_id = str((conv or {}).get("id") or "")
            if not conversation_id:
                continue
            state = _load_state()
            checks = (((state.get("message_monitor") or {}).get("accounts") or {})
                      .get(account_id, {}).get("profile_checks") or {})
            if _profile_check_is_fresh(checks.get(conversation_id)):
                continue
            key = (account_id, conversation_id)
            with _profile_check_lock:
                if key in _profile_checks_refreshing:
                    continue
                _profile_checks_refreshing.add(key)
            _profile_check_worker(account_id, conversation_id, dict(conv or {}), _message_incoming_event_key(conv))
            time.sleep(0.35)
    finally:
        with _profile_check_lock:
            _profile_backfill_refreshing.discard(account_id)


def _schedule_profile_backfill(state=None):
    """Einmalig alle bereits zwischengespeicherten Chats beider Konten einordnen."""
    state = state if state is not None else _load_state()
    for account_id in _accounts_from_state(state):
        if not _api_account_status(account_id).get("connected"):
            continue
        with _profile_check_lock:
            if account_id in _profile_backfill_refreshing:
                continue
            _profile_backfill_refreshing.add(account_id)
        threading.Thread(target=_profile_backfill_worker, args=(account_id,), daemon=True).start()


def _own_profile_worker(account_id):
    """Öffentliche Zufriedenheit des eigenen Kontos abrufen."""
    account_id = _valid_account_id(account_id)
    try:
        api, _auth = _api_client(account_id)
        user_id = _profile_user_id_scalar(getattr(api, "user_id", ""))
        if not user_id:
            raise RuntimeError("eigene Profil-ID wurde nicht geliefert")
        summary = _profile_summary(_fetch_public_profile(account_id, user_id), fallback_name=_account_name(account_id))
        summary.update({"status": "loaded", "checked_at": _now(), "profile_user_id": user_id})
    except Exception as exc:
        print(f"[messages] Eigene Zufriedenheit für {_account_name(account_id)} konnte nicht geladen werden: {exc}", flush=True)
        summary = {
            "status": "unavailable", "name": _account_name(account_id),
            "rating": "", "rating_score": None, "checked_at": _now(),
        }
    finally:
        _store_own_profile(account_id, summary)
        with _profile_check_lock:
            _own_profile_refreshing.discard(account_id)


def _schedule_own_profile_check(account_id, state=None):
    """Eigene Profilwerte höchstens alle sechs Stunden erneut laden."""
    account_id = _valid_account_id(account_id, state)
    if not _api_account_status(account_id).get("connected"):
        return
    state = state if state is not None else _load_state()
    existing = ((state.get("message_monitor") or {}).get("accounts") or {}).get(account_id, {}).get("own_profile") or {}
    checked_at = None
    if isinstance(existing, dict) and existing.get("checked_at"):
        try:
            checked_at = datetime.fromisoformat(str(existing["checked_at"]))
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            checked_at = None
    if checked_at and (datetime.now(timezone.utc) - checked_at).total_seconds() < PROFILE_CHECK_TTL_SECONDS:
        return
    with _profile_check_lock:
        if account_id in _own_profile_refreshing:
            return
        _own_profile_refreshing.add(account_id)
    threading.Thread(target=_own_profile_worker, args=(account_id,), daemon=True).start()


def _following_record(account_id, state=None):
    state = state if state is not None else _load_state()
    root = state.get("following_profiles") if isinstance(state.get("following_profiles"), dict) else {}
    record = root.get(_valid_account_id(account_id, state))
    return dict(record) if isinstance(record, dict) else {"users": [], "status": "idle"}


def _store_following_record(account_id, record):
    """Gefolgten-Übersicht getrennt vom Nachrichtenmonitor atomar speichern."""
    with _state_lock:
        state = json.loads(APP_STATE.read_text("utf-8")) if APP_STATE.exists() else {"ads": {}}
        root = state.setdefault("following_profiles", {})
        root[_valid_account_id(account_id, state)] = dict(record or {})
        _save_state(state)


def _following_entries(value):
    """Die je nach App-Version unterschiedlich verschachtelte Folgen-Liste lesen."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    normalized = {re.sub(r"[^a-z0-9]", "", str(key).lower()): item for key, item in value.items()}
    for key in ("following", "followedusers", "users", "items", "results", "profiles", "data"):
        candidate = normalized.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            nested = _following_entries(candidate)
            if nested:
                return nested
    return []


def _following_user_id(entry):
    if not isinstance(entry, dict):
        return ""
    normalized = {re.sub(r"[^a-z0-9]", "", str(key).lower()): value for key, value in entry.items()}
    for key in ("userid", "followinguserid", "followeduserid", "profileid", "id"):
        user_id = _profile_user_id_scalar(normalized.get(key))
        if user_id:
            return user_id
    nested = normalized.get("user") or normalized.get("profile") or normalized.get("followeduser")
    return _following_user_id(nested) if isinstance(nested, dict) else ""


def _fetch_following_profiles(account_id):
    """Eigene Folgen-Liste und deren öffentliche Profilwerte einmalig abrufen."""
    try:
        from kleinanzeigen_api.client import API_HOST
    except Exception:
        API_HOST = "https://api.kleinanzeigen.de"
    api, _auth = _api_client(account_id)
    own_user_id = _profile_user_id_scalar(getattr(api, "user_id", ""))
    if not own_user_id:
        raise RuntimeError("eigene Profil-ID wurde nicht geliefert")
    response = api._request("GET", f"{API_HOST}/api/users/{own_user_id}/following", authed=True)
    raw_entries = _following_entries(response.json())
    users, seen = [], set()
    for entry in raw_entries[:100]:
        user_id = _following_user_id(entry)
        if not user_id or user_id == own_user_id or user_id in seen:
            continue
        seen.add(user_id)
        try:
            profile = _profile_summary(_fetch_public_profile(account_id, user_id), fallback_name="")
            check = _profile_safety_check({"averageRating": profile.get("rating_score", "") / 100 if profile.get("rating_score") is not None else ""})
            profile.update({"user_id": user_id, "profile_check": check, "status": "loaded"})
        except Exception as exc:
            profile = _profile_summary(entry, fallback_name="")
            profile.update({
                "user_id": user_id,
                "status": "unavailable",
                "profile_check": {"level": "unknown", "score": None, "label": "? Bewertung nicht auslesbar"},
            })
            print(f"[following] Profil {user_id} konnte nicht geladen werden: {exc}", flush=True)
        users.append(profile)
    return users


def _following_refresh_worker(account_id):
    account_id = _valid_account_id(account_id)
    try:
        users = _fetch_following_profiles(account_id)
        _store_following_record(account_id, {"status": "loaded", "checked_at": _now(), "users": users, "error": ""})
    except Exception as exc:
        print(f"[following] Folgen-Liste für {_account_name(account_id)} konnte nicht geladen werden: {exc}", flush=True)
        previous = _following_record(account_id)
        previous.update({"status": "error", "checked_at": _now(), "error": "Folgen-Liste konnte gerade nicht geladen werden."})
        _store_following_record(account_id, previous)
    finally:
        with _profile_check_lock:
            _following_refreshing.discard(account_id)


def _schedule_following_refresh(account_id, state=None, force=False):
    account_id = _valid_account_id(account_id, state)
    if not _api_account_status(account_id).get("connected"):
        return False
    existing = _following_record(account_id, state)
    checked_at = _iso_dt(existing.get("checked_at")) if existing.get("checked_at") else None
    if not force and checked_at and (datetime.now(timezone.utc) - checked_at).total_seconds() < FOLLOWING_CHECK_TTL_SECONDS:
        return False
    with _profile_check_lock:
        if account_id in _following_refreshing:
            return False
        _following_refreshing.add(account_id)
    threading.Thread(target=_following_refresh_worker, args=(account_id,), daemon=True).start()
    return True


def _listing_dict(listing, account_id):
    raw = listing.to_dict() if hasattr(listing, "to_dict") else dict(listing or {})
    raw["account_id"] = account_id
    raw["account_name"] = _account_name(account_id)
    raw["local_slug"] = _find_local_ad_by_remote_id(raw.get("id"), account_id)
    return raw


def _api_cache_path(kind, account_id):
    account_id = _valid_account_id(account_id)
    safe_kind = "messages" if kind == "messages" else "live-ads"
    return API_CACHE_DIR / f"{safe_kind}-{_safe_account_id(account_id)}.json"


def _read_api_cache(kind, account_id):
    path = _api_cache_path(kind, account_id)
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, dict):
            data.setdefault("items", [])
            return data
    except Exception:
        pass
    return {"items": [], "updated_at": None, "error": ""}


def _write_api_cache(kind, account_id, items, error=""):
    API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _api_cache_path(kind, account_id)
    payload = {
        "account_id": _valid_account_id(account_id),
        "updated_at": _now(),
        "error": str(error or ""),
        "items": list(items or []),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)
    return payload


def _set_api_cache_error(kind, account_id, error):
    cache = _read_api_cache(kind, account_id)
    cache["error"] = str(error or "")
    cache["error_at"] = _now()
    API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _api_cache_path(kind, account_id)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def _clear_api_cache(account_id):
    account_id = _valid_account_id(account_id)
    for kind in ("messages", "live-ads"):
        try:
            _api_cache_path(kind, account_id).unlink(missing_ok=True)
        except Exception:
            pass
    # Chat-Inhalte gehören ebenfalls zur Kontositzung und dürfen bei einem
    # API-Loginwechsel nicht unter dem neuen Konto weiter angezeigt werden.
    try:
        prefix = f"thread-{_safe_account_id(account_id)}-"
        for path in API_CACHE_DIR.glob(prefix + "*.json"):
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _allowed_ka_image_host(host):
    host = str(host or "").lower().strip(".")
    return bool(host) and (
        host == "img.kleinanzeigen.de"
        or host == "api.kleinanzeigen.de"
        or host == "gateway.kleinanzeigen.de"
        or host.endswith(".kleinanzeigen.de")
        or host == "ebayimg.com"
        or host.endswith(".ebayimg.com")
    )


def _extract_image_urls(value, limit=6):
    """Bild-URLs aus Anzeigen- oder Chat-Rohdaten lesen.

    Chat-Fotos liegen nicht zwingend unter denselben Schlüsseln wie Anzeigenbilder.
    Deshalb berücksichtigen wir auch attachment/media/photo-Strukturen, bleiben beim
    Proxy aber auf Kleinanzeigen-/eBay-Bildhosts beschränkt.
    """
    found = []
    seen_nodes = set()
    seen_urls = set()

    def add_url(raw):
        text = str(raw or "").strip()
        if text.startswith("//"):
            text = "https:" + text
        elif text.startswith("/"):
            # Chat-Anhänge kommen je nach API-Version auch als relativer
            # Gateway-Pfad zurück. Die Unterhaltung selbst stammt vom Gateway.
            text = "https://gateway.kleinanzeigen.de" + text
        if not text.startswith(("http://", "https://")):
            return
        try:
            parts = urlsplit(text)
            if parts.scheme not in ("http", "https") or not _allowed_ka_image_host(parts.hostname):
                return
        except Exception:
            return
        normalized = _normalize_ka_image_url(text)
        if normalized and normalized not in seen_urls:
            seen_urls.add(normalized)
            found.append(normalized)

    def walk(node, image_hint=False):
        if len(found) >= max(1, int(limit)):
            return
        if isinstance(node, str):
            add_url(node)
            return
        ident = id(node)
        if ident in seen_nodes:
            return
        seen_nodes.add(ident)
        if isinstance(node, dict):
            # Innerhalb eines Attachment-Objekts nur die beste Variante verwenden
            # (Original/Download vor Preview/Thumbnail). Sonst würde ein einziges
            # Foto mehrfach im Chat erscheinen.
            if image_hint:
                normalized_keys = {str(k).lower().replace("-", "").replace("_", ""): k for k in node}
                for wanted in ("originalurl", "downloadurl", "contenturl", "imageurl", "pictureurl", "photourl", "url", "previewurl", "thumbnailurl"):
                    real_key = normalized_keys.get(wanted)
                    if real_key is None:
                        continue
                    before = len(found)
                    walk(node.get(real_key), True)
                    if len(found) > before:
                        return
            # Bild-/Attachment-Felder zuerst ablaufen, damit nicht ein Avatar vor dem
            # eigentlichen Nachrichtenfoto gewinnt.
            preferred = []
            rest = []
            for key, child in node.items():
                lk = str(key).lower().replace("-", "").replace("_", "")
                hinted = any(x in lk for x in (
                    "image", "picture", "photo", "attachment", "media", "thumbnail",
                    "preview", "contenturl", "downloadurl", "originalurl"
                ))
                (preferred if hinted else rest).append((child, hinted))
            for child, hinted in preferred + rest:
                walk(child, image_hint or hinted)
                if len(found) >= max(1, int(limit)):
                    break
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child, image_hint)
                if len(found) >= max(1, int(limit)):
                    break

    walk(value)
    return found


def _extract_first_image_url(value):
    urls = _extract_image_urls(value, limit=1)
    return urls[0] if urls else None


def _normalize_ka_image_url(url):
    """Kleinanzeigen-/eBay-Bild-URL für iOS robust normalisieren."""
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        if not _allowed_ka_image_host(host):
            return ""
        if host == "img.kleinanzeigen.de" and "/prod-ads/images/" in parts.path:
            # Nur Anzeigenbilder dürfen mit einer Bildregel umgeschrieben werden.
            # Chat-Anhänge besitzen teils signierte/anders aufgebaute URLs; deren
            # Query muss unverändert bleiben, sonst entstehen die defekten Bilder.
            return urlunsplit(("https", parts.netloc, parts.path, "rule=$_59.JPG", ""))
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    except Exception:
        return ""

def _raw_scalar(node):
    if isinstance(node, dict) and "value" in node:
        return _raw_scalar(node.get("value"))
    return node


def _raw_ad_node(data, ad_id):
    """Best-effort den Rohdaten-Block einer bestimmten Anzeige finden."""
    target = str(ad_id or "")
    best = None
    best_score = -1
    def walk(node):
        nonlocal best, best_score
        if isinstance(node, dict):
            matched = False
            for key, value in node.items():
                k = str(key).lower().replace("-", "").replace("_", "")
                if k.endswith("id") or k == "id":
                    try:
                        if str(_raw_scalar(value)) == target:
                            matched = True
                            break
                    except Exception:
                        pass
            if matched:
                hints = sum(1 for key in node if any(x in str(key).lower() for x in ("title", "price", "picture", "image", "watch", "fav", "start", "creation")))
                score = len(node) + hints * 10
                if score > best_score:
                    best, best_score = node, score
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
    walk(data)
    return best or {}


def _named_counter(node, names):
    """Nur echte Zählerfelder aus einem Rohobjekt lesen; boolsche Flags ignorieren."""
    if isinstance(node, dict):
        for key, value in node.items():
            lk = str(key).lower().replace("-", "").replace("_", "")
            if any(name in lk for name in names) and any(tag in lk for tag in ("count", "num", "watchers", "favorites", "favourites")):
                raw = _raw_scalar(value)
                if not isinstance(raw, bool):
                    num = _counter_number(raw)
                    if num is not None:
                        return num
        for value in node.values():
            num = _named_counter(value, names)
            if num is not None:
                return num
    elif isinstance(node, (list, tuple)):
        for value in node:
            num = _named_counter(value, names)
            if num is not None:
                return num
    return None


def _watch_counter_from_response(data, ad_id):
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return int(data)
    # Der CAPI-Endpunkt /v2/counters/ads/watchlist?adIds=<id> liefert
    # {"counters":[{"value": N, ...}]}. Bei genau einer angefragten ID ist
    # der erste Zähler der gesuchte Favoritenwert.
    if isinstance(data, dict) and isinstance(data.get("counters"), list):
        counters = [x for x in data.get("counters", []) if isinstance(x, dict)]
        target = str(ad_id or "")
        for item in counters:
            item_id = _raw_scalar(item.get("adId") or item.get("id") or item.get("ad-id"))
            if item_id is not None and str(item_id) == target:
                value = _counter_number(item.get("value"))
                if value is not None:
                    return value
        if len(counters) == 1:
            value = _counter_number(counters[0].get("value"))
            if value is not None:
                return value
    node = _raw_ad_node(data, ad_id)
    if node:
        value = _named_counter(node, ("watch", "fav"))
        if value is not None:
            return value
    if isinstance(data, dict):
        direct = data.get(str(ad_id))
        if direct is not None:
            value = _counter_number(direct)
            if value is not None:
                return value
        # Nur wenn die Antwort offensichtlich genau einen Watch/Favorite-Zähler enthält.
        found = []
        def collect(n):
            if isinstance(n, dict):
                for key, value in n.items():
                    lk = str(key).lower().replace("-", "").replace("_", "")
                    if any(x in lk for x in ("watch", "fav")) and any(x in lk for x in ("count", "num", "watchers", "favorites", "favourites")):
                        raw = _raw_scalar(value)
                        if not isinstance(raw, bool):
                            num = _counter_number(raw)
                            if num is not None:
                                found.append(num)
                    collect(value)
            elif isinstance(n, (list, tuple)):
                for value in n:
                    collect(value)
        collect(data)
        if len(found) == 1:
            return found[0]
    return None


def _extract_live_ad_status(source):
    """Best-effort Status aus dem Rohobjekt der eigenen Anzeige lesen."""
    wanted = ("adstatus", "status", "state")
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                lk = str(key).lower().replace("-", "").replace("_", "")
                if lk in wanted or lk.endswith("adstatus"):
                    raw = _raw_scalar(value)
                    if isinstance(raw, str) and raw.strip():
                        val = raw.strip().upper()
                        if val in {"ACTIVE", "PAUSED", "RESERVED", "SOLD", "DELETED", "EXPIRED", "BLOCKED"}:
                            return val
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return ""
    return walk(source) or ""


def _decorate_thread_message(message):
    item = dict(message or {})
    raw = item.get("raw") or item
    urls = _extract_image_urls(raw, limit=6)
    item["image_urls"] = urls
    # Der API-Client fällt bei Bildnachrichten auf raw.title zurück. Das ist häufig
    # nur der Anzeigentitel und soll nicht als künstliche Chatnachricht erscheinen.
    if urls and isinstance(raw, dict) and not (raw.get("text") or raw.get("textShort") or raw.get("textShortTrimmed")):
        item["text"] = ""
    item["display_date"] = msgdate_filter(item.get("date")) if item.get("date") else ""
    return item


def _live_quota_summary():
    state = _load_state()
    rows = []
    for account in _account_select_records():
        count = _posted_last_30_count(account_id=account.get("id"), state=state)
        rows.append({
            "id": account.get("id"),
            "name": account.get("name"),
            "short": "Haupt" if account.get("id") == MAIN_ACCOUNT_ID else "Zweit",
            "count": count,
            "limit": REPOST_LIMIT_LAST_30_DAYS,
        })
    return rows


def _set_live_ad_reserved(account_id, ad_id, reserved=True):
    cache = _read_api_cache("live-ads", account_id)
    target = str(ad_id)
    changed = False
    for item in cache.get("items", []):
        if str((item or {}).get("id")) == target:
            item["reserved"] = bool(reserved)
            item["status"] = "RESERVED" if reserved else "ACTIVE"
            changed = True
            break
    if changed:
        _write_api_cache("live-ads", account_id, cache.get("items", []))
    # Auch eine bereits gelöschte lokale Anzeige bleibt im Chat als reserviert
    # bzw. wieder aktiv erkennbar.
    _set_cached_conversation_ad_status(account_id, ad_id, "reserved" if reserved else "online")


def _cached_live_image(account_id, ad_id):
    target = str(ad_id or "")
    if not target:
        return ""
    cache = _read_api_cache("live-ads", account_id)
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") == target:
            return _normalize_ka_image_url((item or {}).get("image_url") or "")
    return ""


def _safe_ka_listing_url(value):
    """Accept only direct Kleinanzeigen listing URLs for the article button."""
    text = str(value or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        path = str(parts.path or "")
        if parts.scheme not in {"http", "https"} or not (host == "kleinanzeigen.de" or host.endswith(".kleinanzeigen.de")):
            return ""
        if not path.startswith("/s-anzeige/"):
            return ""
        return urlunsplit(("https", parts.netloc, path, parts.query, ""))
    except Exception:
        return ""


def _listing_url_from_data(value):
    """Find a direct article URL in a conversation or listing API response."""
    candidates = []

    def walk(node, path=()):
        if isinstance(node, dict):
            for key, child in node.items():
                new_path = path + (str(key).lower(),)
                scalar = _raw_scalar(child)
                if isinstance(scalar, str):
                    url = _safe_ka_listing_url(scalar)
                    if url:
                        hint = " ".join(new_path)
                        candidates.append((100 if any(token in hint for token in ("adurl", "listing", "article", "anzeige", "url")) else 50, url))
                walk(child, new_path)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child, path)

    walk(value)
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _cached_live_article_url(account_id, ad_id):
    target = str(ad_id or "").strip()
    if not target:
        return ""
    cache = _read_api_cache("live-ads", account_id)
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") == target:
            return _safe_ka_listing_url((item or {}).get("url"))
    return ""


def _cache_article_url_for_conversations(account_id, ad_id, article_url):
    """Keep an article URL in chats even after the live-ad cache is cleared."""
    article_url = _safe_ka_listing_url(article_url)
    target = str(ad_id or "").strip()
    if not target or not article_url:
        return
    cache = _read_api_cache("messages", account_id)
    changed = False
    for item in cache.get("items", []):
        if str((item or {}).get("ad_id") or "") == target and item.get("article_url") != article_url:
            item["article_url"] = article_url
            changed = True
    if changed:
        _write_api_cache("messages", account_id, cache.get("items", []))


def _resolve_conversation_article_url(account_id, conversation_id, conv=None, allow_network=False):
    """Return the original listing URL, including for chats of deleted ads."""
    account_id = _valid_account_id(account_id)
    conv = dict(conv or {})
    candidates = [
        conv.get("article_url"),
        _listing_url_from_data(conv.get("raw") or {}),
        _listing_url_from_data(conv),
        _listing_url_from_data(_read_thread_cache(account_id, conversation_id).get("conversation_raw") or {}),
        _cached_live_article_url(account_id, conv.get("ad_id")),
    ]
    for candidate in candidates:
        url = _safe_ka_listing_url(candidate)
        if url:
            _cache_article_url_for_conversations(account_id, conv.get("ad_id"), url)
            return url

    # Older cache entries did not retain the URL. The direct article request is
    # only made after a user clicks the button, never while the message list polls.
    ad_id = str(conv.get("ad_id") or "").strip()
    if allow_network and ad_id:
        try:
            api, _auth = _api_client(account_id)
            listing = api.get_ad(ad_id)
            url = _safe_ka_listing_url(getattr(listing, "url", ""))
            if url:
                _cache_article_url_for_conversations(account_id, ad_id, url)
                return url
        except Exception as exc:
            print(f"[messages] Artikel-Link {ad_id} konnte nicht nachgeladen werden: {exc}", flush=True)
    return ""


def _message_live_ad(account_id, ad_id):
    """Die zur Unterhaltung gehoerende Live-Anzeige aus dem lokalen Live-Cache.

    Aktionen in einer Unterhaltung werden nur angeboten, wenn die Anzeigen-ID
    im selben Konto als eigene Live-Anzeige bekannt ist. Das verhindert, dass
    eine unvollstaendige Unterhaltung versehentlich eine andere Anzeige steuert.
    """
    target = str(ad_id or "").strip()
    if not target:
        return None
    cache = _read_api_cache("live-ads", account_id)
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") == target:
            # Der Chat braucht neben den Live-Aktionen auch die lokale
            # Verknüpfung, damit "Bearbeiten" direkt zur eigenen Anzeige
            # führen kann. Der Live-Cache enthält local_slug normalerweise
            # bereits; für ältere/noch nicht reconciliierte Cache-Einträge
            # lösen wir die Remote-ID zusätzlich gegen die lokalen YAMLs auf.
            local_slug = str((item or {}).get("local_slug") or "").strip()
            if not local_slug:
                local_slug = _find_local_ad_by_remote_id(target, account_id) or ""
            return {
                "id": target,
                "reserved": bool((item or {}).get("reserved")),
                "status": str((item or {}).get("status") or ""),
                "local_slug": local_slug,
            }
    return None


def _conversation_is_own_listing(conversation):
    """Nur Verkäufer-Chats gehören zu einer eigenen Live-Anzeige.

    Bei ``BUYER`` hat das angemeldete Konto selbst eine fremde Anzeige
    angefragt. Deren ID darf niemals gegen den eigenen Live-Cache geprüft
    werden, weil ein Fehlen dort sonst fälschlich als „gelöscht“ erscheint.
    Bei unbekannter Rolle wird ebenfalls kein fehlender Artikel geraten.
    """
    return str((conversation or {}).get("role") or "").strip().upper() == "SELLER"


def _cached_live_ad_message_status(account_id, ad_id, *, absent_means_deleted=False):
    """Den sichtbaren Chat-Status aus der eigenen Live-Anzeige ableiten.

    Ein frischer, fehlerfreier Live-Cache enthält alle eigenen Inserate. Fehlt
    eine *eigene* Chat-Anzeige darin, ist sie nicht mehr online und kann für
    Verkäufer-Unterhaltungen als gelöscht dargestellt werden. Bei fremden oder
    nicht eindeutig zuordenbaren Anzeigen bleibt der Status neutral.
    """
    target = str(ad_id or "").strip()
    if not target:
        return ""
    cache = _read_api_cache("live-ads", account_id)
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") != target:
            continue
        status = str((item or {}).get("status") or "").upper()
        if status in {"DELETED", "EXPIRED", "BLOCKED"}:
            return "deleted"
        if status == "SOLD":
            return "sold"
        if bool((item or {}).get("reserved")) or status in {"PAUSED", "RESERVED"}:
            return "reserved"
        return "online"
    if absent_means_deleted and cache.get("updated_at") and not cache.get("error"):
        return "deleted"
    return ""


def _set_cached_conversation_ad_status(account_id, ad_id, ad_status):
    """Status direkt in allen zugehörigen Chats festhalten.

    Der Wert überlebt dadurch das spätere Entfernen aus dem Live-Cache. Ein
    künftiger Live-Abgleich ersetzt ihn automatisch wieder durch online oder
    reserviert, falls die Anzeige erneut aktiv wird.
    """
    target = str(ad_id or "").strip()
    ad_status = str(ad_status or "").strip().lower()
    if not target or ad_status not in {"online", "reserved", "sold", "deleted"}:
        return
    cache = _read_api_cache("messages", account_id)
    changed = False
    for item in cache.get("items", []):
        if str((item or {}).get("ad_id") or "") == target and item.get("ad_status") != ad_status:
            item["ad_status"] = ad_status
            changed = True
    if changed:
        _write_api_cache("messages", account_id, cache.get("items", []))


def _public_listing_message_status(listing, account_id):
    """Status einer fremden Anzeige aus deren eigener API-Antwort lesen."""
    if not listing:
        return ""
    raw = _listing_dict(listing, account_id)
    if not raw.get("id"):
        return ""
    status = _extract_live_ad_status(raw)
    if status in {"DELETED", "EXPIRED", "BLOCKED"}:
        return "deleted"
    if status == "SOLD":
        return "sold"
    if bool(raw.get("reserved")) or status in {"PAUSED", "RESERVED"}:
        return "reserved"
    return "online"


def _is_missing_listing_error(exc):
    """Nur eine eindeutige Nichtfund-Antwort darf „gelöscht“ bedeuten."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    if str(status_code) == "404":
        return True
    text = str(exc or "").lower()
    return " 404" in text or "not found" in text or "nicht gefunden" in text


def _check_external_conversation_ad_status(account_id, conversation):
    """Eine Verkäufer-Anzeige sicher und unabhängig vom eigenen Live-Cache prüfen."""
    if _conversation_is_own_listing(conversation):
        return ""
    ad_id = str((conversation or {}).get("ad_id") or "").strip()
    if not ad_id:
        return ""
    try:
        api, _auth = _api_client(account_id)
        return _public_listing_message_status(api.get_ad(ad_id), account_id)
    except Exception as exc:
        if _is_missing_listing_error(exc):
            return "deleted"
        print(f"[messages] Fremde Anzeige {ad_id} konnte nicht geprüft werden: {exc}", flush=True)
        return ""


def _store_external_conversation_ad_status(account_id, conversation_id, ad_status):
    """Status einer fremden Anzeige samt Prüfzeit im Nachrichten-Cache sichern."""
    cache = _read_api_cache("messages", account_id)
    changed = False
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") != str(conversation_id):
            continue
        if _conversation_is_own_listing(item):
            return False
        if ad_status and item.get("ad_status") != ad_status:
            item["ad_status"] = ad_status
            changed = True
        item["ad_status_checked_at"] = _now()
        changed = True
        break
    if changed:
        _write_api_cache("messages", account_id, cache.get("items", []))
    return changed


def _external_conversation_ad_status_worker(account_id, conversation_id):
    try:
        # Alte Nachrichten können beim ersten Start viele Prüfungen auslösen.
        # Höchstens zwei echte Artikelabrufe gleichzeitig verhindern unnötige
        # Last bzw. Rate-Limits, ohne den Nachrichten-Poll zu blockieren.
        with _external_ad_status_semaphore:
            cache = _read_api_cache("messages", account_id)
            conversation = next((dict(item) for item in cache.get("items", [])
                                 if str((item or {}).get("id") or "") == str(conversation_id)), {})
            status = _check_external_conversation_ad_status(account_id, conversation)
            _store_external_conversation_ad_status(account_id, conversation_id, status)
    finally:
        with _external_ad_status_lock:
            _external_ad_status_refreshing.discard((account_id, str(conversation_id)))


def _schedule_external_conversation_ad_status_check(account_id, conversation, force=False):
    """Fremde Anzeigen höchstens alle fünf Minuten im Hintergrund prüfen."""
    if _conversation_is_own_listing(conversation):
        return False
    conversation_id = str((conversation or {}).get("id") or "").strip()
    ad_id = str((conversation or {}).get("ad_id") or "").strip()
    if not conversation_id or not ad_id:
        return False
    checked_at = _iso_dt((conversation or {}).get("ad_status_checked_at"))
    if not force and checked_at and (datetime.now(timezone.utc) - checked_at).total_seconds() < EXTERNAL_AD_STATUS_TTL_SECONDS:
        return False
    key = (account_id, conversation_id)
    with _external_ad_status_lock:
        if key in _external_ad_status_refreshing:
            return False
        _external_ad_status_refreshing.add(key)
    threading.Thread(target=_external_conversation_ad_status_worker, args=key, daemon=True).start()
    return True


def _refresh_cached_conversation_ad_statuses_from_live(account_id):
    """Nach einem Live-Abgleich alle sichtbaren Chat-Bilder direkt anpassen."""
    cache = _read_api_cache("messages", account_id)
    changed = False
    for item in cache.get("items", []):
        if not _conversation_is_own_listing(item):
            continue
        status = _cached_live_ad_message_status(
            account_id, (item or {}).get("ad_id"), absent_means_deleted=True
        )
        if status and item.get("ad_status") != status:
            item["ad_status"] = status
            changed = True
    if changed:
        _write_api_cache("messages", account_id, cache.get("items", []))
    return changed


def _conversation_cache_item(conv, account_id):
    raw = _conversation_dict(conv, account_id)
    keys = ("id", "ad_id", "ad_title", "role", "counterparty", "unread",
            "unread_count", "last_received", "preview", "account_id", "account_name",
            "ad_status_checked_at")
    item = {k: raw.get(k) for k in keys}
    # Zuerst ein echtes Anzeigenbild aus dem Thread akzeptieren. Wenn die
    # Rohdaten nur Avatar/sonstige URLs enthalten, auf den Live-Anzeigen-Cache
    # derselben Anzeige zurückfallen.
    thread_image = _normalize_ka_image_url(_extract_first_image_url(raw.get("raw") or raw))
    item["image_url"] = thread_image or _cached_live_image(account_id, raw.get("ad_id"))
    item["profile_url"] = _counterparty_profile_url(raw.get("raw") or raw, role=raw.get("role") or "")
    item["article_url"] = _listing_url_from_data(raw.get("raw") or raw) or _cached_live_article_url(account_id, raw.get("ad_id"))
    item["ad_status"] = _cached_live_ad_message_status(
        account_id,
        raw.get("ad_id"),
        absent_means_deleted=_conversation_is_own_listing(raw),
    )
    return item


def _listing_cache_item(listing, account_id, raw_node=None):
    raw = _listing_dict(listing, account_id)
    keys = ("id", "title", "price", "price_type", "url", "city", "zip_code",
            "posted", "account_id", "account_name", "local_slug")
    item = {k: raw.get(k) for k in keys}
    source = raw_node or raw
    item["image_url"] = _normalize_ka_image_url(_extract_first_image_url(raw.get("images") or source) or "")
    item["favorite_count"] = _named_counter(source, ("watch", "fav"))
    item["status"] = _extract_live_ad_status(source)
    item["reserved"] = item["status"] in {"PAUSED", "RESERVED"}
    return item


def _fetch_conversations_to_cache(account_id):
    api, _auth = _api_client(account_id)
    # 30 aktuelle Threads genügen für die iPhone-Übersicht und halten den 5-Sekunden-Poll klein.
    convs = api.conversations(page=0, size=30)
    previous = {
        str((item or {}).get("id") or ""): {
            "article_url": _safe_ka_listing_url((item or {}).get("article_url")),
            "ad_status": str((item or {}).get("ad_status") or "").lower(),
            "ad_status_checked_at": str((item or {}).get("ad_status_checked_at") or ""),
        }
        for item in _read_api_cache("messages", account_id).get("items", [])
    }
    items = [_conversation_cache_item(c, account_id) for c in convs]
    for item in items:
        old = previous.get(str(item.get("id") or ""), {})
        item["article_url"] = item.get("article_url") or old.get("article_url", "")
        if _conversation_is_own_listing(item):
            item["ad_status"] = item.get("ad_status") or old.get("ad_status", "")
        else:
            # Alte, ungeprüfte Cache-Werte stammen aus der früheren falschen
            # Live-Cache-Zuordnung und werden bewusst nicht übernommen.
            item["ad_status"] = old.get("ad_status", "") if old.get("ad_status_checked_at") else ""
            item["ad_status_checked_at"] = old.get("ad_status_checked_at", "")
    _write_api_cache("messages", account_id, items)
    for item in items:
        _schedule_external_conversation_ad_status_check(account_id, item)
    return convs, items


def _normalize_link_title(value):
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())

def _price_key(value):
    try:
        return round(float(value), 2)
    except Exception:
        return None

def _live_link_ignored_ids(account_id, state=None):
    state = state or _load_state()
    account_id = _valid_account_id(account_id, state)
    raw = (state.get("live_link_ignored_by_account") or {}).get(account_id, {})
    if isinstance(raw, dict):
        return {str(x) for x in raw.keys()}
    if isinstance(raw, (list, tuple, set)):
        return {str(x) for x in raw}
    return set()


def _set_live_link_ignore(account_id, remote_id, ignored=True):
    remote_id = str(remote_id or "").strip()
    if not remote_id:
        return
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    root = state.setdefault("live_link_ignored_by_account", {})
    bucket = root.setdefault(account_id, {})
    if not isinstance(bucket, dict):
        bucket = {}
        root[account_id] = bucket
    if ignored:
        bucket[remote_id] = {"at": _now(), "reason": "manuell gelöst"}
    else:
        bucket.pop(remote_id, None)
    _save_state(state)


def _set_local_remote_link(slug, account_id, remote_id, posted=None, reason="Live-Anzeige verknüpft"):
    ad = _read_ad_yaml(slug) or {}
    if not ad:
        return False
    remote_id = str(remote_id or "").strip()
    if not remote_id:
        return False
    ad["id"] = remote_id
    _write_yaml_file(_ad_yaml_path(slug), ad)
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    ignored_root = state.setdefault("live_link_ignored_by_account", {})
    ignored_bucket = ignored_root.get(account_id)
    if isinstance(ignored_bucket, dict):
        ignored_bucket.pop(remote_id, None)
    meta = state.setdefault("ads", {}).setdefault(slug, {})
    meta["account_id"] = account_id
    meta["last_published"] = posted or meta.get("last_published") or _now()
    meta["scheduled_publish_at"] = None
    meta.pop("republish_postponed_until", None)
    hist = meta.setdefault("history", [])
    if not hist or hist[-1].get("action") != reason:
        hist.append({"action": reason + f" · ID {remote_id}", "date": _now()})
    _save_state(state)
    return True

def _unlink_local_remote(slug, reason="Live-Verknüpfung manuell gelöst"):
    ad = _read_ad_yaml(slug) or {}
    if not ad:
        return False
    old = str(ad.pop("id", "") or "")
    ad.pop("created_on_kleinanzeigen", None)
    _write_yaml_file(_ad_yaml_path(slug), ad)
    state = _load_state()
    meta = state.setdefault("ads", {}).setdefault(slug, {})
    meta["last_published"] = None
    meta.setdefault("history", []).append({"action": reason + (f" · alte ID {old}" if old else ""), "date": _now()})
    _save_state(state)
    return True

def _clear_local_remote_id_only(slug):
    """Nur die alte Remote-ID aus der lokalen YAML entfernen; Metadaten steuert der aufrufende Workflow."""
    ad = _read_ad_yaml(slug) or {}
    if not ad:
        return False
    changed = False
    for key in ("id", "created_on_kleinanzeigen"):
        if key in ad:
            ad.pop(key, None)
            changed = True
    if changed:
        _write_yaml_file(_ad_yaml_path(slug), ad)
    return True


def _link_candidates_for_live_account(account_id, live_items=None, state=None):
    """Lokale Anzeigen, die nicht bereits mit einer aktuell vorhandenen Live-ID verbunden sind."""
    state = state or _load_state()
    account_id = _valid_account_id(account_id, state)
    live_ids = {str((x or {}).get("id") or "").strip() for x in (live_items or []) if (x or {}).get("id")}
    result = []
    for path in sorted(ADS_DIR.glob("*.yaml")):
        slug = path.stem
        ad = _read_ad_yaml(slug) or {}
        meta = state.get("ads", {}).get(slug, {})
        if _ad_account_id(slug, meta, state) != account_id:
            continue
        remote_id = str(ad.get("id") or "").strip()
        if remote_id and remote_id in live_ids:
            continue
        result.append({
            "slug": slug,
            "title": str(ad.get("title") or slug),
            "price": ad.get("price"),
            "stale_id": remote_id,
        })
    return result


def _unlinked_local_candidates(account_id, state=None):
    state = state or _load_state()
    account_id = _valid_account_id(account_id, state)
    result = []
    for path in sorted(ADS_DIR.glob("*.yaml")):
        slug = path.stem
        ad = _read_ad_yaml(slug) or {}
        meta = state.get("ads", {}).get(slug, {})
        if _ad_account_id(slug, meta, state) != account_id:
            continue
        if ad.get("id"):
            continue
        # Automatische Verknüpfung nur für Datensätze, die der Manager selbst
        # bereits als veröffentlicht kennt. Unveröffentlichte Entwürfe dürfen
        # niemals versehentlich mit einer gleichnamigen Live-Anzeige verknüpft werden.
        if not meta.get("last_published"):
            continue
        result.append({"slug": slug, "title": str(ad.get("title") or slug), "price": ad.get("price")})
    return result

def _reconcile_live_links(account_id, items):
    """Eindeutige Live-Anzeigen automatisch mit lokalen Datensätzen verbinden."""
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    # Bestehende IDs sind immer führend.
    linked_ids = {}
    for path in ADS_DIR.glob("*.yaml"):
        ad = _read_ad_yaml(path.stem) or {}
        rid = str(ad.get("id") or "").strip()
        if rid and _ad_account_id(path.stem, state.get("ads", {}).get(path.stem, {}), state) == account_id:
            linked_ids[rid] = path.stem
    for item in items:
        rid = str((item or {}).get("id") or "").strip()
        if rid in linked_ids:
            item["local_slug"] = linked_ids[rid]
    # Unverknüpfte Anzeigen nur bei einem eindeutig besten Treffer automatisch zuordnen.
    candidates = _unlinked_local_candidates(account_id, state)
    used = set()
    ignored_ids = _live_link_ignored_ids(account_id, state)
    unmatched = [item for item in items if not item.get("local_slug") and str((item or {}).get("id") or "") not in ignored_ids]
    remote_key_counts = {}
    for item in unmatched:
        title_key = _normalize_link_title(item.get("title"))
        remote_price = _price_key(item.get("price"))
        remote_key = (title_key, remote_price) if remote_price is not None else (title_key, None)
        remote_key_counts[remote_key] = remote_key_counts.get(remote_key, 0) + 1
    for item in unmatched:
        title_key = _normalize_link_title(item.get("title"))
        remote_price = _price_key(item.get("price"))
        remote_key = (title_key, remote_price) if remote_price is not None else (title_key, None)
        # Zwei gleichartige Live-Anzeigen sind nicht eindeutig genug für eine automatische Zuordnung.
        if remote_key_counts.get(remote_key, 0) != 1:
            continue
        scored = []
        for cand in candidates:
            if cand["slug"] in used:
                continue
            if _normalize_link_title(cand.get("title")) != title_key:
                continue
            score = 10
            local_price = _price_key(cand.get("price"))
            if remote_price is not None and local_price is not None:
                if remote_price != local_price:
                    continue
                score += 3
            scored.append((score, cand))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            continue
        best_score = scored[0][0]
        best = [c for score, c in scored if score == best_score]
        if len(best) != 1:
            continue
        cand = best[0]
        if _set_local_remote_link(cand["slug"], account_id, item.get("id"), posted=item.get("posted"), reason="Automatisch mit bestehender Live-Anzeige verknüpft"):
            item["local_slug"] = cand["slug"]
            used.add(cand["slug"])
    return items

def _capture_live_ids(account_id):
    try:
        _listings, items = _fetch_live_ads_raw(account_id)
        return {str((x or {}).get("id") or "") for x in items if (x or {}).get("id")}
    except Exception:
        cache = _read_api_cache("live-ads", account_id)
        return {str((x or {}).get("id") or "") for x in cache.get("items", []) if (x or {}).get("id")}

def _sync_remote_link_after_publish(slug, account_id, before_ids=None, attempts=4, delay_seconds=2.0, require_fresh=False):
    """Neue ID nach Bot-Publish aus den Live-Anzeigen übernehmen."""
    before_ids = set(str(x) for x in (before_ids or set()))
    ad = _read_ad_yaml(slug) or {}
    title_key = _normalize_link_title(ad.get("title"))
    attempts = max(1, int(attempts or 1))
    for attempt in range(attempts):
        try:
            _listings, items = _fetch_live_ads_raw(account_id)
        except Exception:
            items = []
        matches = [x for x in items if _normalize_link_title((x or {}).get("title")) == title_key]
        fresh = [x for x in matches if str((x or {}).get("id") or "") not in before_ids]
        pool = fresh if require_fresh else (fresh or matches)
        if len(pool) == 1:
            item = pool[0]
            _set_local_remote_link(slug, account_id, item.get("id"), posted=item.get("posted") or _now(), reason="Neue Live-ID nach Veröffentlichung gespeichert")
            try:
                _write_api_cache("live-ads", account_id, _reconcile_live_links(account_id, items))
            except Exception:
                pass
            return str(item.get("id"))
        if pool:
            # Bei mehreren gleichnamigen Anzeigen ist eine neue, vorher unbekannte ID trotzdem eindeutig, wenn nur eine frisch ist.
            if len(fresh) == 1:
                item = fresh[0]
                _set_local_remote_link(slug, account_id, item.get("id"), posted=item.get("posted") or _now(), reason="Neue Live-ID nach Veröffentlichung gespeichert")
                return str(item.get("id"))
        if attempt < attempts - 1 and float(delay_seconds or 0) > 0:
            time.sleep(float(delay_seconds))
    return ""


def _confirm_uncertain_publish_after_submit(slug, account_id, before_ids=None):
    """Wartet nach unklarem Submit ausschließlich auf die neue Live-Anzeige.

    Es wird in dieser Phase niemals ein zweiter Publish gestartet. Dadurch kann
    der Manager einen verspäteten Kleinanzeigen-Erfolg nachbestätigen, ohne eine
    Doppelanzeige zu riskieren.
    """
    deadline = time.monotonic() + UNCERTAIN_PUBLISH_CONFIRM_SECONDS
    _operation_update(
        slug,
        status="checking",
        message="Anzeige wurde abgesendet – Kleinanzeigen-Online-Status wird geprüft …",
        cancel_allowed=False,
    )
    last_error = ""
    while True:
        try:
            remote_id = _sync_remote_link_after_publish(
                slug,
                account_id,
                before_ids,
                attempts=1,
                delay_seconds=0,
                require_fresh=True,
            )
            if remote_id:
                return remote_id, "Neue Live-Anzeige nach unklarem Submit eindeutig bestätigt."
        except Exception as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            break
        time.sleep(UNCERTAIN_PUBLISH_CONFIRM_INTERVAL)
    detail = f" Letzter Live-Abgleich: {last_error}" if last_error else ""
    return "", (
        f"Nach {UNCERTAIN_PUBLISH_CONFIRM_SECONDS} Sekunden noch nicht eindeutig in den Live-Anzeigen bestätigt." + detail
    )

def _fetch_live_ads_raw(account_id):
    """Live-Anzeigen abrufen, ohne dabei selbst erneut einen Reconcile auszulösen."""
    api, _auth = _api_client(account_id)
    page_size = 25
    listings_with_raw = []
    try:
        from kleinanzeigen_api.client import API_HOST
    except Exception:
        API_HOST = "https://api.kleinanzeigen.de"
    for page in range(20):
        data = None
        try:
            uid = api.user_id
            response = api._request("GET", f"{API_HOST}/api/users/{uid}/ads.json", params={"page": page, "size": page_size}, authed=True)
            data = response.json()
            batch = api._parse_ads_block(data)[1]
        except AttributeError:
            batch = api.my_ads(page=page, size=page_size)
        for listing in batch:
            raw_node = _raw_ad_node(data, getattr(listing, "id", "")) if data is not None else {}
            listings_with_raw.append((listing, raw_node))
        if len(batch) < page_size:
            break
    listings_with_raw.sort(key=lambda pair: str(getattr(pair[0], "posted", "") or ""), reverse=True)
    listings = [pair[0] for pair in listings_with_raw]
    items = [_listing_cache_item(listing, account_id, raw_node) for listing, raw_node in listings_with_raw]
    return listings, items


def _fetch_live_ads_to_cache(account_id):
    """Eigene Anzeigen laden, eindeutige lokale Verknüpfungen reparieren und cachen."""
    listings, items = _fetch_live_ads_raw(account_id)
    items = _reconcile_live_links(account_id, items)
    _write_api_cache("live-ads", account_id, items)
    _refresh_cached_conversation_ad_statuses_from_live(account_id)
    return listings, items


def _remove_live_ad_from_cache(account_id, ad_id):
    cache = _read_api_cache("live-ads", account_id)
    target = str(ad_id)
    items = [x for x in cache.get("items", []) if str((x or {}).get("id")) != target]
    _write_api_cache("live-ads", account_id, items)


def _mark_cached_conversation_read(account_id, conversation_id):
    cache = _read_api_cache("messages", account_id)
    target = str(conversation_id)
    changed = False
    for item in cache.get("items", []):
        if str((item or {}).get("id")) == target:
            item["unread"] = False
            item["unread_count"] = 0
            changed = True
            break
    if changed:
        _write_api_cache("messages", account_id, cache.get("items", []))


def _safe_cache_token(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))[:160] or "unknown"


def _thread_cache_path(account_id, conversation_id):
    account_id = _valid_account_id(account_id)
    return API_CACHE_DIR / f"thread-{_safe_account_id(account_id)}-{_safe_cache_token(conversation_id)}.json"


def _read_thread_cache(account_id, conversation_id):
    path = _thread_cache_path(account_id, conversation_id)
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, dict):
            data.setdefault("messages", [])
            return data
    except Exception:
        pass
    return {"account_id": account_id, "conversation_id": str(conversation_id), "messages": [], "updated_at": None, "loading": True, "error": ""}


def _write_thread_cache(account_id, conversation_id, messages, error="", conversation_raw=None):
    API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "account_id": _valid_account_id(account_id),
        "conversation_id": str(conversation_id),
        "messages": list(messages or []),
        "updated_at": _now(),
        "loading": False,
        "error": str(error or ""),
    }
    if isinstance(conversation_raw, dict):
        payload["conversation_raw"] = conversation_raw
    path = _thread_cache_path(account_id, conversation_id)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)
    return payload


def _thread_messages_from_conversation(conversation):
    """Vollständige Conversation-Antwort in die bisherigen Thread-Nachrichten umwandeln."""
    if not isinstance(conversation, dict):
        return []
    raw_messages = conversation.get("messages") or (conversation.get("data") or {}).get("messages") or []
    out = []
    for message in raw_messages if isinstance(raw_messages, list) else []:
        if not isinstance(message, dict):
            continue
        bound = (message.get("boundness") or message.get("direction") or "").upper()
        direction = ("received" if "IN" in bound else
                     "sent" if "OUT" in bound else bound.lower())
        out.append({
            "text": message.get("text") or message.get("textShort") or message.get("title") or "",
            "direction": direction,
            "date": message.get("receivedDate") or "",
            "raw": message,
        })
    return out


def _conversation_metadata(conversation):
    """Conversation-Metadaten ohne Nachrichteninhalte für den lokalen Cache behalten."""
    if not isinstance(conversation, dict):
        return {}
    metadata = copy.deepcopy(conversation)
    metadata.pop("messages", None)
    data = metadata.get("data")
    if isinstance(data, dict):
        data.pop("messages", None)
    return metadata


def _fetch_thread_to_cache(account_id, conversation_id):
    try:
        api, _auth = _api_client(account_id)
        conversation = api.conversation(str(conversation_id))
        messages = _thread_messages_from_conversation(conversation)
        payload = _write_thread_cache(
            account_id, conversation_id, messages,
            conversation_raw=_conversation_metadata(conversation),
        )
        try:
            api.mark_read(str(conversation_id))
            _mark_cached_conversation_read(account_id, conversation_id)
        except Exception:
            pass
        return payload
    except Exception as exc:
        old = _read_thread_cache(account_id, conversation_id)
        old["loading"] = False
        old["error"] = str(exc)
        API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _thread_cache_path(account_id, conversation_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(old, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, path)
        return old


def _schedule_thread_refresh(account_id, conversation_id):
    key = (_valid_account_id(account_id), str(conversation_id))
    with _thread_refresh_lock:
        if key in _thread_refreshing:
            return False
        _thread_refreshing.add(key)
    def worker():
        try:
            _fetch_thread_to_cache(*key)
        finally:
            with _thread_refresh_lock:
                _thread_refreshing.discard(key)
    threading.Thread(target=worker, daemon=True).start()
    return True


def _append_optimistic_thread_message(account_id, conversation_id, text):
    cache = _read_thread_cache(account_id, conversation_id)
    messages = list(cache.get("messages") or [])
    messages.append({"text": str(text), "direction": "sent", "date": _now()})
    return _write_thread_cache(
        account_id, conversation_id, messages,
        conversation_raw=cache.get("conversation_raw"),
    )


def _ad_stats_path(ad_id):
    return API_CACHE_DIR / f"ad-stats-{_safe_cache_token(ad_id)}.json"


def _counter_number(data):
    if data is None:
        return None
    if isinstance(data, bool):
        return int(data)
    if isinstance(data, (int, float)):
        return int(data)
    if isinstance(data, str):
        m = re.search(r"-?\d+", data.replace(".", ""))
        return int(m.group(0)) if m else None
    if isinstance(data, dict):
        for key in ("value", "numVisits", "count", "total", "watchers", "favorites", "favourites",
                    "watchlistCount", "watchCount", "numWatchers", "numFavorites"):
            if key in data:
                num = _counter_number(data.get(key))
                if num is not None:
                    return num
        for key, val in data.items():
            if "id" in str(key).lower():
                continue
            num = _counter_number(val)
            if num is not None:
                return num
    if isinstance(data, (list, tuple)):
        for val in data:
            num = _counter_number(val)
            if num is not None:
                return num
    return None


def _read_ad_stats(ad_id, max_age_seconds=900):
    path = _ad_stats_path(ad_id)
    try:
        data = json.loads(path.read_text("utf-8"))
        fetched = float(data.get("fetched_epoch") or 0)
        if time.time() - fetched <= max_age_seconds:
            return data
    except Exception:
        pass
    return None


def _cached_live_favorite_count(account_id, ad_id):
    target = str(ad_id or "")
    cache = _read_api_cache("live-ads", account_id)
    for item in cache.get("items", []):
        if str((item or {}).get("id") or "") == target:
            value = (item or {}).get("favorite_count")
            if value is not None:
                try:
                    return int(value)
                except Exception:
                    return value
    return None


def _fetch_ad_stats(account_id, ad_id):
    cached = _read_ad_stats(ad_id)
    # Alte 0/—-Caches aus 1.5.24.14 nicht 15 Minuten lang festhalten, wenn
    # inzwischen ein Favoritenzähler aus dem Live-Feed vorliegt.
    live_favorites = _cached_live_favorite_count(account_id, ad_id)
    if cached is not None and cached.get("favorites") is not None:
        return cached
    with _ad_stats_lock:
        cached = _read_ad_stats(ad_id)
        if cached is not None and cached.get("favorites") is not None:
            return cached
        views = None
        favorites = live_favorites
        error = ""
        try:
            api, _auth = _api_client(account_id)
            try:
                from kleinanzeigen_api.client import API_HOST
            except Exception:
                API_HOST = "https://api.kleinanzeigen.de"
            try:
                r = api._request("GET", f"{API_HOST}/api/v2/counters/ads/vip/{ad_id}", authed=False)
                views = _counter_number(r.json())
            except Exception as exc:
                error = f"views: {exc}"
            if favorites is None:
                endpoint = f"{API_HOST}/api/v2/counters/ads/watchlist"
                attempts = ({"adIds": str(ad_id)}, {"adId": str(ad_id)}, {"ids": str(ad_id)})
                last_exc = None
                for params in attempts:
                    try:
                        r = api._request("GET", endpoint, params=params, authed=False)
                        favorites = _watch_counter_from_response(r.json(), ad_id)
                        if favorites is not None:
                            break
                    except Exception as exc:
                        last_exc = exc
                if favorites is None and last_exc is not None:
                    error = (error + "; " if error else "") + f"favorites: {last_exc}"
        except Exception as exc:
            error = str(exc)
        payload = {"ad_id": str(ad_id), "views": views, "favorites": favorites,
                   "fetched_at": _now(), "fetched_epoch": time.time(), "error": error}
        API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _ad_stats_path(ad_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, path)
        return payload

def _find_local_ad_by_remote_id(ad_id, account_id=None):
    target = str(ad_id or "").strip()
    if not target:
        return None
    state = _load_state()
    for path in ADS_DIR.glob("*.yaml"):
        slug = path.stem
        ad = _read_ad_yaml(slug) or {}
        if str(ad.get("id") or "").strip() != target:
            continue
        if account_id and _ad_account_id(slug, state=state) != _valid_account_id(account_id, state):
            continue
        return slug
    return None


def _reset_local_after_direct_delete(slug, sold=False):
    ad = _read_ad_yaml(slug) or {}
    if not ad:
        return False
    for key in ("id", "created_on_kleinanzeigen"):
        ad.pop(key, None)
    if sold:
        ad["active"] = False
    _write_yaml_file(_ad_yaml_path(slug), ad)
    state = _load_state()
    meta = state.setdefault("ads", {}).setdefault(slug, {})
    meta["last_published"] = None
    meta["scheduled_publish_at"] = None
    meta.pop("republish_postponed_until", None)
    meta.setdefault("history", []).append({
        "action": "verkauft: direkt per API gelöscht und lokal deaktiviert" if sold else "direkt per API bei Kleinanzeigen gelöscht",
        "date": _now(),
    })
    _save_state(state)
    return True


def _decrement_online_activity(account_id):
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    activity = dict(_get_account_activity(account_id, state) or {})
    try:
        if activity.get("online_ads") is not None:
            activity["online_ads"] = max(0, int(activity.get("online_ads") or 0) - 1)
            activity["updated_at"] = _now()
            state.setdefault("account_activity_by_account", {})[account_id] = activity
            if account_id == MAIN_ACCOUNT_ID:
                state["account_activity"] = activity
            _save_state(state)
    except Exception:
        pass


def _message_incoming_marker(account_id, conversation_id, state=None):
    """Persistenter Marker der letzten sicher als eingehend erkannten Nachricht.

    Der Marker ist bewusst geraeteunabhaengig. Ob er auf einem konkreten iPhone/
    Browser schon gelesen wurde, speichert die Weboberflaeche lokal auf genau
    diesem Geraet. Dadurch kann primary einen Chat lesen, waehrend er auf einem
    anderen Geraet weiterhin als neu markiert bleibt.
    """
    state = state if isinstance(state, dict) else _load_state()
    rec = (state.get("message_monitor") or {}).get("accounts") or {}
    rec = rec.get(_valid_account_id(account_id, state)) or {}
    markers = rec.get("incoming_markers") if isinstance(rec.get("incoming_markers"), dict) else {}
    marker = markers.get(str(conversation_id))
    if isinstance(marker, dict):
        return {"marker": str(marker.get("marker") or ""), "at": str(marker.get("at") or "")}
    return {"marker": "", "at": ""}


def _message_signature(conv):
    c = conv.to_dict() if hasattr(conv, "to_dict") else dict(conv or {})
    return "|".join([
        str(c.get("last_received") or ""), str(c.get("unread_count") or 0), str(c.get("preview") or "")
    ])


def _message_incoming_event_key(conv):
    """Stabiler Schlüssel einer eingehenden Nachricht, unabhängig vom Lesestatus.

    Kleinanzeigen kann den serverseitigen ``unread``-Status nach dem Öffnen
    asynchron ändern. Dieser Status darf deshalb niemals einen neuen
    gerätespezifischen "ungelesen"-Marker erzeugen. Die Gesprächsliste enthält
    bei einer eigenen Antwort ebenfalls eine neue Vorschau und ein neues Datum.
    Das ist ausdrücklich keine eingehende Nachricht: Ohne mindestens eine von
    Kleinanzeigen als ungelesen gemeldete Nachricht darf daher weder der
    "NEU"-Marker noch eine Push-Benachrichtigung erzeugt werden.
    """
    c = conv.to_dict() if hasattr(conv, "to_dict") else dict(conv or {})
    try:
        unread_count = int(c.get("unread_count") or 0)
    except (TypeError, ValueError):
        unread_count = 0
    if unread_count <= 0:
        return ""
    received = str(c.get("last_received") or "").strip()
    preview = str(c.get("preview") or "").strip()
    if not received and not preview:
        return ""
    source = "|".join((str(c.get("id") or ""), received, preview))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def _cached_unread_total():
    user = _current_app_user()
    if not user:
        return 0
    state = _load_state()
    rows = []
    for account_id in _accounts_from_state(state):
        cache = _read_api_cache("messages", account_id)
        for item in cache.get("items", []) or []:
            c = dict(item or {})
            c["account_id"] = c.get("account_id") or account_id
            c["platform_unread"] = bool(c.get("unread"))
            c["platform_unread_count"] = int(c.get("unread_count") or 0)
            marker = _message_incoming_marker(account_id, c.get("id"), state)
            c["incoming_marker"] = marker.get("marker", "")
            c["incoming_at"] = marker.get("at", "")
            rows.append(c)
    rows = _decorate_profile_unread(rows, user.get("id"))
    return sum(1 for c in rows if c.get("unread"))


def _load_webpush_subscriptions():
    with _webpush_lock:
        try:
            data = json.loads(WEBPUSH_SUBSCRIPTIONS.read_text("utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def _save_webpush_subscriptions(items):
    with _webpush_lock:
        WEBPUSH_SUBSCRIPTIONS.parent.mkdir(parents=True, exist_ok=True)
        tmp = WEBPUSH_SUBSCRIPTIONS.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, WEBPUSH_SUBSCRIPTIONS)


def _ensure_vapid_key():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    if not WEBPUSH_PRIVATE_KEY.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        WEBPUSH_PRIVATE_KEY.write_bytes(pem)
        try: os.chmod(WEBPUSH_PRIVATE_KEY, 0o600)
        except OSError: pass
    key = serialization.load_pem_private_key(WEBPUSH_PRIVATE_KEY.read_bytes(), password=None)
    point = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    import base64
    return base64.urlsafe_b64encode(point).decode("ascii").rstrip("=")


def _send_web_push(title, body, url="/messages", tag="kleinanzeigen-message"):
    subscriptions = _load_webpush_subscriptions()
    if not subscriptions:
        return 0
    try:
        _ensure_vapid_key()
        from pywebpush import webpush, WebPushException
    except Exception as exc:
        print(f"[webpush] nicht verfügbar: {exc}", flush=True)
        return 0
    delivered = 0
    keep = []
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag}, ensure_ascii=False)
    for item in subscriptions:
        sub = item.get("subscription") if isinstance(item, dict) else None
        if not isinstance(sub, dict) or not sub.get("endpoint"):
            continue
        expired = False
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=str(WEBPUSH_PRIVATE_KEY),
                vapid_claims={"sub": PUBLIC_BASE_URL or "mailto:user@example.invalid"},
            )
            delivered += 1
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                expired = True
            else:
                print(f"[webpush] Zustellung fehlgeschlagen: {exc}", flush=True)
        if not expired:
            keep.append(item)
    if len(keep) != len(subscriptions):
        _save_webpush_subscriptions(keep)
    return delivered


def _notification_manager_url():
    base = str(_last_access_base_url or "").rstrip("/")
    if not base:
        # Solider LAN-Fallback für iPhone/HA-App, bis der Manager einmal geöffnet wurde.
        base = "http://homeassistant.local:8139"
    return base + "/messages"


def _notify_new_conversation(account_id, conv):
    c = conv.to_dict() if hasattr(conv, "to_dict") else dict(conv or {})
    account_name = _account_name(account_id)
    sender = str(c.get("counterparty") or "Neue Nachricht")
    ad_title = str(c.get("ad_title") or "Anzeige")
    preview = str(c.get("preview") or "").strip()
    title = f"💬 {account_name} · {sender}"
    body = ad_title + (f"\n{preview}" if preview else "")
    image_url = _normalize_ka_image_url(c.get("image_url") or _extract_first_image_url(c.get("raw") or c))
    if not image_url:
        image_url = _cached_live_image(account_id, c.get("ad_id"))
    # Ausschließlich eine tatsächlich neu eingegangene Nachricht wird an alle
    # Home-Assistant-Geräte verteilt. Ein Tipp öffnet die Nachrichtenübersicht.
    _notify_message_broadcast(title, body, click_url=_notification_manager_url(), image_url=image_url)

def _poll_messages_once():
    if not _message_poll_lock.acquire(blocking=False):
        return
    try:
        state = _load_state()
        monitor = state.setdefault("message_monitor", {})
        by_account = monitor.setdefault("accounts", {})
        for account_id in list(_accounts_from_state(state).keys()):
            account_id = _valid_account_id(account_id, state)
            rec = by_account.setdefault(account_id, {})
            incoming_markers = rec.setdefault("incoming_markers", {})
            if not isinstance(incoming_markers, dict):
                incoming_markers = {}
                rec["incoming_markers"] = incoming_markers
            incoming_event_keys = rec.setdefault("incoming_event_keys", {})
            if not isinstance(incoming_event_keys, dict):
                incoming_event_keys = {}
                rec["incoming_event_keys"] = incoming_event_keys
            if not _api_account_status(account_id).get("connected"):
                rec.update({"unread_total": 0, "error": "", "updated_at": _now()})
                continue
            try:
                convs, _items = _fetch_conversations_to_cache(account_id)
                items_by_id = {str((item or {}).get("id")): item for item in (_items or [])}
                current = {str(c.id): _message_signature(c) for c in convs}
                unread_total = sum(int(getattr(c, "unread_count", 0) or 0) for c in convs)
                previous = rec.get("signatures") if isinstance(rec.get("signatures"), dict) else {}
                initialized = bool(rec.get("initialized"))
                marker_version = int(rec.get("incoming_marker_version") or 0)
                if marker_version < 2:
                    # Bestehende Unterhaltungen sind beim Umstieg nur die
                    # Ausgangslage. Sie dürfen nicht auf allen Geräten erneut
                    # als neu erscheinen.
                    incoming_event_keys.clear()
                    incoming_event_keys.update({
                        str(c.id): _message_incoming_event_key(c)
                        for c in convs if _message_incoming_event_key(c)
                    })
                    rec["incoming_marker_version"] = 2
                elif initialized:
                    for c in convs:
                        conversation_id = str(c.id)
                        changed = previous.get(conversation_id) != current.get(conversation_id)
                        if changed:
                            _schedule_thread_refresh(account_id, c.id)
                        event_key = _message_incoming_event_key(c)
                        known_event_key = incoming_event_keys.get(conversation_id)
                        is_new_conversation = conversation_id not in previous
                        if event_key and event_key != known_event_key and (known_event_key is not None or is_new_conversation):
                            # Nur eine andere eingehende Nachricht erhält einen neuen
                            # Marker. Ein wechselnder API-Lesestatus bleibt wirkungslos.
                            incoming_event_keys[conversation_id] = event_key
                            incoming_markers[conversation_id] = {"marker": event_key, "at": _now()}
                            _notify_new_conversation(account_id, items_by_id.get(str(c.id)) or c)
                            # Die öffentliche Profilbewertung darf den Poll nicht
                            # ausbremsen. Sie wird einmalig im Hintergrund geladen
                            # und erscheint anschließend als neutraler Hinweis im Chat.
                            _schedule_profile_check(
                                account_id, conversation_id,
                                items_by_id.get(str(c.id)) or _conversation_cache_item(c, account_id),
                                event_key,
                            )
                        elif event_key and known_event_key is None:
                            # Fehlende Altwerte nach einem Teil-Reset nur als
                            # Ausgangslage übernehmen, nicht als neue Nachricht.
                            incoming_event_keys[conversation_id] = event_key
                else:
                    # Einmalig die neuesten Chats vorwärmen, danach nur geänderte Threads.
                    for c in convs[:5]:
                        _schedule_thread_refresh(account_id, c.id)
                rec.update({
                    "initialized": True,
                    "incoming_marker_version": 2,
                    "signatures": current,
                    "unread_total": unread_total,
                    "updated_at": _now(),
                    "error": "",
                })
            except Exception as exc:
                rec["error"] = str(exc)
                rec["updated_at"] = _now()
                _set_api_cache_error("messages", account_id, exc)
                print(f"[messages] {_account_name(account_id)}: {exc}", flush=True)
        _save_message_monitor_only(monitor)
        errors = [str((rec or {}).get("error") or "") for rec in by_account.values() if isinstance(rec, dict) and (rec or {}).get("error")]
        _mark_runtime_health("messages", ok=not bool(errors), message=(errors[0] if errors else "Nachrichtenmonitor aktiv"))
    finally:
        _message_poll_lock.release()


def _message_monitor_loop():
    time.sleep(2)
    while True:
        started = time.monotonic()
        try:
            _poll_messages_once()
        except Exception as exc:
            _mark_runtime_health("messages", ok=False, message=str(exc))
            print(f"[messages] Monitorfehler: {exc}", flush=True)
        # Start-zu-Start möglichst alle 5 Sekunden; externe API-Laufzeit wird
        # dabei berücksichtigt, ohne parallele identische Polls zu erzeugen.
        elapsed = time.monotonic() - started
        time.sleep(max(0.25, MESSAGE_POLL_SECONDS - elapsed))


def _poll_live_ads_once():
    if not _live_ads_poll_lock.acquire(blocking=False):
        return
    errors = []
    try:
        state = _load_state()
        for account_id in list(_accounts_from_state(state).keys()):
            account_id = _valid_account_id(account_id, state)
            if not _api_account_status(account_id).get("connected"):
                continue
            try:
                _fetch_live_ads_to_cache(account_id)
            except Exception as exc:
                errors.append(str(exc))
                _set_api_cache_error("live-ads", account_id, exc)
                print(f"[live-ads] {_account_name(account_id)}: {exc}", flush=True)
        _mark_runtime_health("live", ok=not bool(errors), message=(errors[0] if errors else "Live-Abgleich aktiv"))
    finally:
        _live_ads_poll_lock.release()


def _live_ads_monitor_loop():
    time.sleep(12)
    while True:
        try:
            _poll_live_ads_once()
        except Exception as exc:
            _mark_runtime_health("live", ok=False, message=str(exc))
            print(f"[live-ads] Monitorfehler: {exc}", flush=True)
        time.sleep(LIVE_ADS_POLL_SECONDS)


def _nav_account_ids(selected="all"):
    state = _load_state()
    if selected != "all" and selected in _accounts_from_state(state):
        return [selected]
    return list(_accounts_from_state(state).keys())


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(str(Path(app.static_folder)), "sw.js", mimetype="application/javascript", max_age=0)
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


def _image_proxy_cache_files(src, account_id=""):
    cache_key = f"{_safe_account_id(account_id) if account_id else 'public'}|{src}"
    digest = hashlib.sha256(cache_key.encode("utf-8", errors="ignore")).hexdigest()
    return IMAGE_PROXY_DIR / f"{digest}.bin", IMAGE_PROXY_DIR / f"{digest}.type"


@app.route("/api/ka-image")
def ka_image_proxy():
    """Kleinanzeigen-Bilder über die eigene WebApp ausliefern.

    Anzeigenbilder sind öffentlich. Chat-Anhänge können dagegen am Gateway/API
    hängen und benötigen den Token des jeweiligen eigenen Kontos.
    """
    src = _normalize_ka_image_url(request.args.get("src", ""))
    account_id = (request.args.get("account") or "").strip()
    if account_id:
        try:
            account_id = _valid_account_id(account_id)
        except Exception:
            account_id = ""
    if not src:
        return ("", 404)
    try:
        parts = urlsplit(src)
    except Exception:
        return ("", 400)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not _allowed_ka_image_host(host):
        return ("", 400)
    IMAGE_PROXY_DIR.mkdir(parents=True, exist_ok=True)
    data_file, type_file = _image_proxy_cache_files(src, account_id if host in {"api.kleinanzeigen.de", "gateway.kleinanzeigen.de"} else "")
    if data_file.exists() and data_file.stat().st_size > 0:
        mimetype = type_file.read_text("utf-8").strip() if type_file.exists() else "image/jpeg"
        response = send_file(data_file, mimetype=mimetype, conditional=True)
        response.headers["Cache-Control"] = "private, max-age=86400" if account_id else "public, max-age=86400"
        return response
    try:
        if host in {"api.kleinanzeigen.de", "gateway.kleinanzeigen.de"}:
            if not account_id:
                return ("", 401)
            api, _auth = _api_client(account_id)
            gateway = host == "gateway.kleinanzeigen.de"
            resp = api._s.get(src, headers=api._headers(authed=True, gateway=gateway), timeout=15)
            status = int(getattr(resp, "status_code", 0) or 0)
            if status >= 400:
                raise RuntimeError(f"Bildabruf HTTP {status}")
            content = bytes(resp.content or b"")
            content_type = (resp.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip().lower()
        else:
            resp = requests.get(
                src, timeout=12,
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
                    "Referer": "https://www.kleinanzeigen.de/",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            resp.raise_for_status()
            content = resp.content
            content_type = (resp.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip().lower()
        if not content or len(content) > 15 * 1024 * 1024 or not content_type.startswith("image/"):
            return ("", 502)
        tmp = data_file.with_suffix(".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, data_file)
        type_file.write_text(content_type, "utf-8")
        response = send_file(data_file, mimetype=content_type, conditional=True)
        response.headers["Cache-Control"] = "private, max-age=86400" if account_id else "public, max-age=86400"
        return response
    except Exception as exc:
        print(f"[image-proxy] {src}: {exc}", flush=True)
        return ("", 502)


@app.route("/api/push/public-key")
def push_public_key():
    try:
        return jsonify({"ok": True, "publicKey": _ensure_vapid_key()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    payload = request.get_json(silent=True) or {}
    sub = payload.get("subscription") or payload
    if not isinstance(sub, dict) or not sub.get("endpoint") or not isinstance(sub.get("keys"), dict):
        return jsonify({"ok": False, "error": "Ungültige Push-Subscription."}), 400
    items = _load_webpush_subscriptions()
    endpoint = str(sub.get("endpoint"))
    items = [x for x in items if isinstance(x, dict) and str((x.get("subscription") or {}).get("endpoint")) != endpoint]
    items.append({"subscription": sub, "created_at": _now(), "user_agent": request.headers.get("User-Agent", "")[:300]})
    _save_webpush_subscriptions(items)
    return jsonify({"ok": True, "subscriptions": len(items)})


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get("endpoint") or "")
    items = _load_webpush_subscriptions()
    keep = [x for x in items if str((x.get("subscription") or {}).get("endpoint") or "") != endpoint]
    _save_webpush_subscriptions(keep)
    return jsonify({"ok": True})


@app.route("/api/push/status")
def push_status():
    return jsonify({
        "ok": True,
        "subscriptions": len(_load_webpush_subscriptions()),
        "public_base_url": PUBLIC_BASE_URL,
        "ha_fallback": True,
    })


@app.route("/api/push/test", methods=["POST"])
def push_test():
    ok, status = _notify_message_broadcast(
        "Kleinanzeigen Manager",
        "Test einer eingehenden Nachricht an alle Home-Assistant-Geräte.",
    )
    return jsonify({"ok": bool(ok), "status": status}), (200 if ok else 503)

@app.route("/settings/api-login/start/<account_id>", methods=["POST"])
def api_login_start(account_id):
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    try:
        auth = _api_authenticator(account_id)
        url, verifier, oauth_state = auth.build_login_url()
        state.setdefault("api_login_pending", {})[account_id] = {
            "url": url, "verifier": verifier, "state": oauth_state, "created_at": _now()
        }
        _save_state(state)
        return redirect(url_for("api_login_page", account_id=account_id))
    except Exception as exc:
        flash("API-Login konnte nicht gestartet werden: " + str(exc), "err")
        return redirect(url_for("settings_form"))


@app.route("/settings/api-login/<account_id>", methods=["GET", "POST"])
def api_login_page(account_id):
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    pending = (state.get("api_login_pending") or {}).get(account_id) or {}
    if request.method == "POST":
        redirect_url = request.form.get("redirect_url", "").strip()
        if not pending.get("verifier") or not pending.get("state"):
            flash("Login-Sitzung abgelaufen. Bitte neu starten.", "err")
            return redirect(url_for("settings_form"))
        try:
            auth = _api_authenticator(account_id)
            auth.complete_login(redirect_url, pending["verifier"], pending["state"])
            state = _load_state()
            state.setdefault("api_login_pending", {}).pop(account_id, None)
            # Baseline und API-Caches neu aufbauen, damit keine Daten eines vorherigen Logins
            # unter dem Konto weiter angezeigt werden.
            state.setdefault("message_monitor", {}).setdefault("accounts", {}).pop(account_id, None)
            _save_state(state)
            _clear_api_cache(account_id)
            flash(f"Nachrichten/API für '{_account_name(account_id)}' verbunden.", "ok")
            return redirect(url_for("settings_form"))
        except Exception as exc:
            flash("API-Login fehlgeschlagen: " + str(exc), "err")
    return render_template("api_login.html", account_id=account_id, account_name=_account_name(account_id), pending=pending)


@app.route("/settings/api-logout/<account_id>", methods=["POST"])
def api_logout(account_id):
    account_id = _valid_account_id(account_id)
    try:
        _api_authenticator(account_id).logout()
        state = _load_state()
        state.setdefault("message_monitor", {}).setdefault("accounts", {}).pop(account_id, None)
        _save_state(state)
        _clear_api_cache(account_id)
        flash(f"API-Verbindung von '{_account_name(account_id)}' getrennt.", "ok")
    except Exception as exc:
        flash("API konnte nicht getrennt werden: " + str(exc), "err")
    return redirect(url_for("settings_form"))


def _messages_cache_payload(selected="all", limit=30):
    selected = (selected or "all").strip() or "all"
    marker_state = _load_state()
    monitor_accounts = ((marker_state.get("message_monitor") or {}).get("accounts") or {})
    conversations = []
    errors = []
    cache_times = []
    cache_loading = False
    should_refresh = False
    for account_id in _nav_account_ids(selected):
        status = _api_account_status(account_id)
        cache = _read_api_cache("messages", account_id)
        if not status.get("connected"):
            errors.append(f"{_account_name(account_id)}: API noch nicht verbunden.")
        elif cache.get("error") and not cache.get("items"):
            errors.append(f"{_account_name(account_id)}: Nachrichten konnten gerade nicht aktualisiert werden.")
        elif not cache.get("items") and not cache.get("updated_at"):
            cache_loading = True
            should_refresh = True
        conversations.extend(cache.get("items") or [])
        if cache.get("updated_at"):
            cache_times.append(cache.get("updated_at"))
    conversations.sort(key=lambda c: str(c.get("last_received") or ""), reverse=True)
    try:
        limit = max(30, min(int(limit), 100))
    except Exception:
        limit = 30
    total = len(conversations)
    conversations = [dict(c or {}) for c in conversations[:limit]]
    for c in conversations:
        c["profile_url"] = c.get("profile_url") or _resolve_conversation_profile_url(
            c.get("account_id"), c.get("id"), c, allow_network=False
        )
        c["display_date"] = msgdate_filter(c.get("last_received")) if c.get("last_received") else ""
        c["image_url"] = _normalize_ka_image_url(c.get("image_url") or _cached_live_image(c.get("account_id"), c.get("ad_id")))
        c["href"] = url_for("message_thread", account_id=c.get("account_id"), conversation_id=c.get("id"), return_account=selected)
        c["account_color"] = "main" if c.get("account_id") == MAIN_ACCOUNT_ID else "second"
        marker = _message_incoming_marker(c.get("account_id"), c.get("id"), marker_state)
        c["incoming_marker"] = marker.get("marker", "")
        c["incoming_at"] = marker.get("at", "")
        check = (monitor_accounts.get(c.get("account_id"), {}).get("profile_checks") or {}).get(str(c.get("id")))
        c["profile_check"] = dict(check) if isinstance(check, dict) else None
    conversations = _decorate_profile_unread(conversations)
    own_profiles = []
    for account in _account_select_records(marker_state):
        account_id = account["id"]
        stored = monitor_accounts.get(account_id, {}).get("own_profile")
        own_profiles.append({
            "account_id": account_id,
            "account_name": account["name"],
            "account_color": "main" if account_id == MAIN_ACCOUNT_ID else "second",
            "connected": bool(_api_account_status(account_id).get("connected")),
            "profile": dict(stored) if isinstance(stored, dict) else None,
        })
    return {
        "conversations": conversations, "errors": errors,
        "cache_updated_at": max(cache_times) if cache_times else None,
        "cache_loading": cache_loading, "should_refresh": should_refresh,
        "account_filter": selected, "message_limit": limit, "total_conversations": total,
        "own_profiles": own_profiles,
    }


@app.route("/messages")
def messages_view():
    selected = request.args.get("account", "all")
    state = _load_state()
    for account_id in _accounts_from_state(state):
        _schedule_own_profile_check(account_id, state)
    payload = _messages_cache_payload(selected, request.args.get("limit", "30"))
    _schedule_visible_profile_checks(payload.get("conversations"), state)
    _schedule_profile_backfill(state)
    if payload.pop("should_refresh"):
        threading.Thread(target=_poll_messages_once, daemon=True).start()
    return render_template("messages.html", account_records=_account_select_records(), **payload)


@app.route("/api/messages/cache")
def messages_cache_api():
    state = _load_state()
    for account_id in _accounts_from_state(state):
        _schedule_own_profile_check(account_id, state)
    payload = _messages_cache_payload(request.args.get("account", "all"), request.args.get("limit", "30"))
    _schedule_visible_profile_checks(payload.get("conversations"), state)
    _schedule_profile_backfill(state)
    should = payload.pop("should_refresh")
    if should:
        threading.Thread(target=_poll_messages_once, daemon=True).start()
    payload["cache_updated_label"] = datefmt_filter(payload.get("cache_updated_at")) if payload.get("cache_updated_at") else ""
    return jsonify(payload)


@app.route("/messages/refresh", methods=["POST"])
def messages_refresh():
    selected = request.form.get("account", "all").strip() or "all"
    # Manuell sofort anstoßen, aber Browser nicht auf den externen API-Abruf warten lassen.
    threading.Thread(target=_poll_messages_once, daemon=True).start()
    flash("Nachrichten-Aktualisierung gestartet.", "ok")
    return redirect(url_for("messages_view", account=selected))


@app.route("/messages/mark-all-read", methods=["POST"])
def messages_mark_all_read():
    selected = request.form.get("account", "all").strip() or "all"
    current_user = _current_app_user() or {}
    marked = _mark_all_user_messages_read(current_user.get("id"))
    if marked:
        flash(f"{marked} Unterhaltung(en) als gelesen markiert.", "ok")
    else:
        flash("Keine ungelesenen Unterhaltungen vorhanden.", "ok")
    return redirect(url_for("messages_view", account=selected))


def _send_chat_reply_with_images(account_id, conversation_id, text, uploads):
    """Eine eigene Kleinanzeigen-Nachricht mit Bildanhängen senden.

    Der Gateway-Endpunkt erwartet multipart/form-data: wiederholte `attachment`
    Teile plus einen JSON-Teil `message`. Kein automatischer Retry, damit ein
    unklarer Netzwerkfehler niemals versehentlich dieselbe Nachricht doppelt sendet.
    """
    account_id = _valid_account_id(account_id)
    api, _auth = _api_client(account_id)
    uploads = list(uploads or [])[:CHAT_IMAGE_MAX_FILES]
    if not uploads:
        api.reply(str(conversation_id), str(text or ""))
        return
    parts = []
    total = 0
    allowed_ext = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
    for index, storage in enumerate(uploads):
        filename = Path(str(storage.filename or f"foto-{index+1}.jpg")).name
        ext = Path(filename).suffix.lower()
        mimetype = str(storage.mimetype or "").lower()
        if ext not in allowed_ext and not mimetype.startswith("image/"):
            raise ValueError(f"{filename}: kein unterstütztes Bildformat")
        blob = storage.read()
        if not blob:
            continue
        if len(blob) > CHAT_IMAGE_MAX_BYTES:
            raise ValueError(f"{filename}: Bild ist größer als 15 MB")
        total += len(blob)
        if total > CHAT_IMAGE_MAX_TOTAL_BYTES:
            raise ValueError("Bilder zusammen sind größer als 30 MB")
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename) or f"foto-{index+1}.jpg"
        parts.append({
            "name": "attachment",
            "filename": safe,
            "content_type": mimetype if mimetype.startswith("image/") else "image/jpeg",
            "data": blob,
        })
    if not parts:
        if text:
            api.reply(str(conversation_id), str(text))
            return
        raise ValueError("Kein Bild ausgewählt")
    parts.append({
        "name": "message",
        "filename": "blob",
        "content_type": "application/json",
        "data": json.dumps({"message": str(text or "")}, ensure_ascii=False).encode("utf-8"),
    })
    try:
        from kleinanzeigen_api.client import GATEWAY_HOST
    except Exception:
        GATEWAY_HOST = "https://gateway.kleinanzeigen.de"
    url = f"{GATEWAY_HOST}/messagebox/api/users/{api.user_id}/conversations/{conversation_id}"
    params = {"warnPhoneNumber": "false", "warnEmail": "false", "warnBankDetails": "false"}
    headers = api._headers(authed=True, gateway=True)

    # curl_cffi 0.16 unterstützt absichtlich kein requests-kompatibles `files=`.
    # Für Bildnachrichten muss ein CurlMime-Objekt über `multipart=` übergeben werden.
    # Der bestehende, authentifizierte API-Session-Client bleibt dabei erhalten.
    import curl_cffi
    multipart = curl_cffi.CurlMime.from_list(parts)
    try:
        response = api._s.request(
            "POST", url, params=params, multipart=multipart, headers=headers, timeout=35
        )
    finally:
        multipart.close()
    status = int(getattr(response, "status_code", 0) or 0)
    if status not in (200, 201, 204):
        body = str(getattr(response, "text", "") or "")[:300]
        raise RuntimeError(f"Bildnachricht konnte nicht gesendet werden (HTTP {status}: {body})")


@app.route("/messages/<account_id>/<conversation_id>/profile")
def message_profile(account_id, conversation_id):
    account_id = _valid_account_id(account_id)
    msg_cache = _read_api_cache("messages", account_id)
    conv = next((dict(c) for c in msg_cache.get("items", []) if str((c or {}).get("id")) == str(conversation_id)), {})
    user_id = _conversation_counterparty_user_id(account_id, conversation_id, conv, allow_network=True)
    if user_id:
        try:
            profile_raw = _fetch_public_profile(account_id, user_id)
            profile = _profile_summary(profile_raw, fallback_name=conv.get("counterparty") or "")
            return render_template(
                "message_profile.html",
                profile=profile,
                profile_user_id=user_id,
                conversation=conv,
                account_id=account_id,
                return_account=(request.args.get("return_account") or "all"),
                profile_back_url=url_for("message_thread", account_id=account_id, conversation_id=conversation_id,
                                         return_account=(request.args.get("return_account") or "all")),
                profile_back_label="← Nachricht",
            )
        except Exception as exc:
            print(f"[messages] Öffentliches Profil {user_id} konnte nicht geladen werden: {exc}", flush=True)

    # Kompatibilitätsfallback: Falls eine ältere API-Version nur eine fertige
    # Web-URL liefert, bleibt der bisherige externe Aufruf möglich.
    url = _resolve_conversation_profile_url(account_id, conversation_id, conv, allow_network=False)
    if url:
        return redirect(url)
    flash("Profil konnte über die mobilen Profildaten nicht geladen werden. Bitte Profil über die Anzeige öffnen.", "info")
    return redirect(url_for("message_thread", account_id=account_id, conversation_id=conversation_id,
                            return_account=(request.args.get("return_account") or "all")))


def _refresh_message_article_status(account_id, conversation_id, conv):
    """Artikelstatus aktualisieren, ohne die Navigation im iPhone-WebView zu blockieren."""
    try:
        if _conversation_is_own_listing(conv):
            _fetch_live_ads_to_cache(account_id)
        else:
            _store_external_conversation_ad_status(
                account_id, conversation_id,
                _check_external_conversation_ad_status(account_id, conv),
            )
    except Exception as exc:
        print(f"[messages] Artikel-Status beim Artikelaufruf nicht aktualisiert: {exc}", flush=True)


@app.route("/messages/<account_id>/<conversation_id>/article-status", methods=["POST"])
def message_article_status_refresh(account_id, conversation_id):
    account_id = _valid_account_id(account_id)
    msg_cache = _read_api_cache("messages", account_id)
    conv = next((dict(c) for c in msg_cache.get("items", [])
                 if str((c or {}).get("id")) == str(conversation_id)), {})
    threading.Thread(target=_refresh_message_article_status,
                     args=(account_id, conversation_id, conv), daemon=True).start()
    return ("", 202)


@app.route("/messages/<account_id>/<conversation_id>/article")
def message_article(account_id, conversation_id):
    account_id = _valid_account_id(account_id)
    return_account = (request.args.get("return_account") or "all").strip()
    msg_cache = _read_api_cache("messages", account_id)
    conv = next((dict(c) for c in msg_cache.get("items", [])
                 if str((c or {}).get("id")) == str(conversation_id)), {})

    # Bekannte Links sofort öffnen. Der vorher synchrone Statusabruf konnte im
    # iOS-WebView mehrere Sekunden zwischen Tap und Redirect liegen.
    url = _resolve_conversation_article_url(account_id, conversation_id, conv, allow_network=False)
    if url:
        threading.Thread(target=_refresh_message_article_status,
                         args=(account_id, conversation_id, conv), daemon=True).start()
        return redirect(url)

    # Nur alte Chats ohne gespeicherte URL müssen den Artikel einmalig nachladen.
    url = _resolve_conversation_article_url(account_id, conversation_id, conv, allow_network=True)
    if url:
        threading.Thread(target=_refresh_message_article_status,
                         args=(account_id, conversation_id, conv), daemon=True).start()
        return redirect(url)
    flash("Artikel-Link ist für diese Unterhaltung nicht mehr verfügbar.", "info")
    return redirect(url_for("message_thread", account_id=account_id, conversation_id=conversation_id,
                            return_account=return_account))


@app.route("/settings/following", methods=["GET"])
def settings_following():
    """Gefolgte Profile je Kleinanzeigen-Konto, bewusst abseits der Hauptnavigation."""
    state = _load_state()
    accounts = _account_select_records(state)
    rows = []
    loading = False
    for account in accounts:
        account_id = account["id"]
        record = _following_record(account_id, state)
        started = _schedule_following_refresh(account_id, state)
        loading = loading or started or account_id in _following_refreshing
        rows.append({
            **account,
            "connected": _api_account_status(account_id).get("connected", False),
            "following": record,
        })
    return render_template("following.html", account_records=rows, cache_loading=loading)


@app.route("/settings/following/refresh", methods=["POST"])
def settings_following_refresh():
    state = _load_state()
    started = False
    for account in _account_select_records(state):
        started = _schedule_following_refresh(account["id"], state, force=True) or started
    flash("Gefolgte Profile werden aktualisiert." if started else "Aktualisierung läuft bereits oder die API ist noch nicht verbunden.", "info")
    return redirect(url_for("settings_following"))


@app.route("/settings/following/<account_id>/<user_id>/profile", methods=["GET"])
def settings_following_profile(account_id, user_id):
    account_id = _valid_account_id(account_id)
    user_id = _profile_user_id_scalar(user_id)
    if not user_id:
        flash("Profil konnte nicht geöffnet werden.", "warn")
        return redirect(url_for("settings_following"))
    try:
        profile = _profile_summary(_fetch_public_profile(account_id, user_id))
        return render_template(
            "message_profile.html",
            profile=profile,
            profile_user_id=user_id,
            conversation={},
            account_id=account_id,
            return_account="all",
            profile_back_url=url_for("settings_following"),
            profile_back_label="← Folge ich",
        )
    except Exception as exc:
        print(f"[following] Öffentliches Profil {user_id} konnte nicht geladen werden: {exc}", flush=True)
        flash("Profil konnte gerade nicht geladen werden.", "warn")
        return redirect(url_for("settings_following"))


@app.route("/api/messages/<account_id>/<conversation_id>/profile-diagnostics")
def message_profile_diagnostics_api(account_id, conversation_id):
    """Einmaliger, bereinigter Diagnoseabruf für den mobilen Profilweg."""
    account_id = _valid_account_id(account_id)
    msg_cache = _read_api_cache("messages", account_id)
    conv = next((dict(c) for c in msg_cache.get("items", [])
                 if str((c or {}).get("id")) == str(conversation_id)), {})
    return jsonify(_profile_diagnostics(account_id, conversation_id, conv))


@app.route("/messages/<account_id>/<conversation_id>", methods=["GET", "POST"])
def message_thread(account_id, conversation_id):
    account_id = _valid_account_id(account_id)
    return_account = (request.values.get("return_account") or "all").strip()
    if return_account not in {"all", MAIN_ACCOUNT_ID, "second"}:
        return_account = "all"
    if request.method == "POST":
        text = request.form.get("message", "").strip()
        uploads = [f for f in request.files.getlist("images") if f and str(f.filename or "").strip()]
        if not text and not uploads:
            flash("Bitte Text oder mindestens ein Bild auswählen.", "warn")
            return redirect(url_for("message_thread", account_id=account_id, conversation_id=conversation_id, return_account=return_account))
        if len(uploads) > CHAT_IMAGE_MAX_FILES:
            flash(f"Maximal {CHAT_IMAGE_MAX_FILES} Bilder pro Nachricht.", "warn")
            return redirect(url_for("message_thread", account_id=account_id, conversation_id=conversation_id, return_account=return_account))
        try:
            if uploads:
                _send_chat_reply_with_images(account_id, conversation_id, text, uploads)
            else:
                api, _auth = _api_client(account_id)
                api.reply(conversation_id, text)
                _append_optimistic_thread_message(account_id, conversation_id, text)
            _schedule_thread_refresh(account_id, conversation_id)
            flash("Nachricht gesendet.", "ok")
        except Exception as exc:
            flash("Nachricht konnte nicht gesendet werden: " + str(exc), "err")
        return redirect(url_for("message_thread", account_id=account_id, conversation_id=conversation_id, return_account=return_account))

    cache = _read_thread_cache(account_id, conversation_id)
    msg_cache = _read_api_cache("messages", account_id)
    conv = next((c for c in msg_cache.get("items", []) if str((c or {}).get("id")) == str(conversation_id)), None)
    if conv is None:
        conv = {"id": conversation_id, "account_id": account_id, "account_name": _account_name(account_id), "counterparty": "Chat", "ad_title": "Anzeige"}
    else:
        conv = dict(conv)
    # Der Profil-Link kann erst im vollständigen Thread auftauchen. Bereits
    # geladene Thread-Rohdaten deshalb vor dem Rendern mit auswerten.
    conv["profile_url"] = conv.get("profile_url") or _resolve_conversation_profile_url(
        account_id, conversation_id, conv, allow_network=False
    )
    conv["article_url"] = _resolve_conversation_article_url(account_id, conversation_id, conv, allow_network=False)
    marker = _message_incoming_marker(account_id, conversation_id)
    conv["incoming_marker"] = marker.get("marker", "")
    conv["incoming_at"] = marker.get("at", "")
    current_user = _current_app_user() or {}
    _mark_user_message_read(current_user.get("id"), account_id, conversation_id, conv.get("incoming_marker"))
    conv["live_ad"] = _message_live_ad(account_id, conv.get("ad_id"))
    # Beim ersten Aufruf einer Unterhaltung kann der Live-Cache noch leer sein.
    # Dann wird er im Hintergrund geholt; beim naechsten Aufruf erscheinen die
    # Aktionen, ohne dass der Chat auf einen externen Abruf warten muss.
    if conv.get("ad_id") and not conv["live_ad"]:
        live_cache = _read_api_cache("live-ads", account_id)
        if not live_cache.get("updated_at") and _api_account_status(account_id).get("connected"):
            threading.Thread(target=_poll_live_ads_once, daemon=True).start()
    _mark_cached_conversation_read(account_id, conversation_id)
    _schedule_thread_refresh(account_id, conversation_id)
    sidebar_payload = _messages_cache_payload(return_account, 100)
    sidebar_payload.pop("should_refresh", None)
    return render_template("message_thread.html", messages=[_decorate_thread_message(m) for m in (cache.get("messages") or [])],
                           thread_cache=cache, conversation=conv, account_id=account_id,
                           return_account=return_account, sidebar_conversations=sidebar_payload.get("conversations", []),
                           account_records=_account_select_records(), account_filter=return_account)


@app.route("/api/messages/<account_id>/<conversation_id>/cache")
def message_thread_cache_api(account_id, conversation_id):
    account_id = _valid_account_id(account_id)
    cache = _read_thread_cache(account_id, conversation_id)
    _schedule_thread_refresh(account_id, conversation_id) if not cache.get("updated_at") else None
    messages = [_decorate_thread_message(m) for m in (cache.get("messages") or [])]
    msg_cache = _read_api_cache("messages", account_id)
    conv = next((dict(c) for c in msg_cache.get("items", [])
                 if str((c or {}).get("id")) == str(conversation_id)), {})
    profile_url = _resolve_conversation_profile_url(
        account_id, conversation_id, conv, allow_network=False
    )
    marker = _message_incoming_marker(account_id, conversation_id)
    current_user = _current_app_user() or {}
    _mark_user_message_read(current_user.get("id"), account_id, conversation_id, marker.get("marker", ""))
    return jsonify({"messages": messages, "updated_at": cache.get("updated_at"),
                    "error": cache.get("error", ""),
                    "loading": not bool(cache.get("updated_at")),
                    "profile_url": profile_url,
                    "incoming_marker": marker.get("marker", "")})


@app.route("/live-ads")
def live_ads_view():
    selected = request.args.get("account", "all").strip() or "all"
    state = _load_state()
    if _sync_vinted_transfer_receipts(state):
        _save_state(state)
    ads_meta = state.get("ads", {})
    listings = []
    errors = []
    cache_times = []
    cache_loading = False
    should_refresh = False
    for account_id in _nav_account_ids(selected):
        status = _api_account_status(account_id)
        cache = _read_api_cache("live-ads", account_id)
        if not status.get("connected"):
            errors.append(f"{_account_name(account_id)}: API noch nicht verbunden.")
        elif cache.get("error") and not cache.get("items"):
            errors.append(f"{_account_name(account_id)}: Live-Anzeigen konnten gerade nicht aktualisiert werden.")
        elif not cache.get("items") and not cache.get("updated_at"):
            # Auch der erste Anzeigenabruf blockiert die Seite nicht. Mehrere 25er-
            # Seiten dürfen in Ruhe im Hintergrund geladen werden.
            cache_loading = True
            should_refresh = True
        listings.extend(cache.get("items") or [])
        if cache.get("updated_at"):
            cache_times.append(cache.get("updated_at"))
    if should_refresh:
        threading.Thread(target=_poll_live_ads_once, daemon=True).start()
    listings = [dict(x or {}) for x in listings]
    for item in listings:
        item["image_url"] = _normalize_ka_image_url(item.get("image_url"))
        slug = str(item.get("local_slug") or "").strip()
        if slug:
            item["vinted_draft_id"] = str(ads_meta.get(slug, {}).get("vinted_draft_id") or "")
    listings.sort(key=lambda x: str(x.get("posted") or ""), reverse=True)
    live_by_account = {}
    for item in listings:
        live_by_account.setdefault(str(item.get("account_id") or MAIN_ACCOUNT_ID), []).append(item)
    link_candidates = {
        aid: _link_candidates_for_live_account(aid, live_by_account.get(aid, []))
        for aid in _nav_account_ids(selected)
    }
    return render_template("live_ads.html", listings=listings, errors=errors,
                           cache_updated_at=max(cache_times) if cache_times else None,
                           cache_loading=cache_loading,
                           account_filter=selected, account_records=_account_select_records(),
                           quota_summary=_live_quota_summary(),
                           link_candidates_by_account=link_candidates)


@app.route("/live-ads/refresh", methods=["POST"])
def live_ads_refresh():
    selected = request.form.get("account", "all").strip() or "all"
    ok = 0
    failed = []
    for account_id in _nav_account_ids(selected):
        try:
            _fetch_live_ads_to_cache(account_id)
            ok += 1
        except Exception as exc:
            _set_api_cache_error("live-ads", account_id, exc)
            failed.append(_account_name(account_id))
            print(f"[live-ads] Manueller Abruf {_account_name(account_id)}: {exc}", flush=True)
    if ok:
        flash("Live-Anzeigen aktualisiert.", "ok")
    if failed:
        flash("Live-Anzeigen konnten für " + ", ".join(failed) + " nicht aktualisiert werden.", "warn")
    return redirect(url_for("live_ads_view", account=selected))


@app.route("/api/live-ads/<account_id>/<ad_id>/stats")
def live_ad_stats_api(account_id, ad_id):
    account_id = _valid_account_id(account_id)
    data = _fetch_ad_stats(account_id, ad_id)
    return jsonify({"views": data.get("views"), "favorites": data.get("favorites"), "updated_at": data.get("fetched_at")})


def _delete_remote_only(account_id, ad_id):
    """Exakt eine Live-ID löschen, ohne die lokale Anzeige/Verknüpfung sofort zurückzusetzen."""
    account_id = _valid_account_id(account_id)
    article_url = _cached_live_article_url(account_id, ad_id)
    _cache_article_url_for_conversations(account_id, ad_id, article_url)
    api, _auth = _api_client(account_id)
    api.delete_ad(str(ad_id))
    _remove_live_ad_from_cache(account_id, ad_id)
    _set_cached_conversation_ad_status(account_id, ad_id, "deleted")
    _decrement_online_activity(account_id)
    return True


def _direct_delete_remote(account_id, ad_id, sold=False):
    account_id = _valid_account_id(account_id)
    local_slug = _find_local_ad_by_remote_id(ad_id, account_id)
    _create_backup(reason='vor-direkt-api-loeschen', slug=local_slug)
    article_url = _cached_live_article_url(account_id, ad_id)
    _cache_article_url_for_conversations(account_id, ad_id, article_url)
    api, auth = _api_client(account_id)
    api.delete_ad(str(ad_id))
    _remove_live_ad_from_cache(account_id, ad_id)
    _set_cached_conversation_ad_status(account_id, ad_id, "sold" if sold else "deleted")
    if local_slug:
        if sold:
            _reset_local_after_direct_delete(local_slug, sold=True)
        else:
            # Die normale Loeschaktion ist ein bewusster Komplettloeschvorgang:
            # erst nach erfolgreicher API-Antwort wird genau die verknuepfte
            # lokale Anzeige inklusive Bilder aus der Verwaltung entfernt.
            _delete_local_slug(local_slug)
    _decrement_online_activity(account_id)
    return local_slug


def _live_ad_action_redirect(account_id):
    """Nach einer Live-Aktion zur Ausgangsseite zurueckkehren.

    Die Nachrichtenansicht uebergibt ihre Unterhaltungs-ID explizit. Andere
    Aufrufer behalten unveraendert die Rueckkehr zu den Live-Anzeigen.
    """
    account_id = _valid_account_id(account_id)
    return_account = (request.form.get("return_account") or account_id).strip()
    if return_account not in {"all", MAIN_ACCOUNT_ID, "second"}:
        return_account = account_id
    conversation_id = (request.form.get("return_conversation_id") or "").strip()
    if request.form.get("return_to") == "message" and conversation_id:
        return redirect(url_for("message_thread", account_id=account_id,
                                conversation_id=conversation_id,
                                return_account=return_account))
    return redirect(url_for("live_ads_view", account=return_account))


@app.route("/live-ads/<account_id>/<ad_id>/link", methods=["POST"])
def live_ad_link(account_id, ad_id):
    account_id = _valid_account_id(account_id)
    slug = (request.form.get("slug") or "").strip()
    return_account = (request.form.get("return_account") or account_id).strip()
    try:
        cache = _read_api_cache("live-ads", account_id)
        live_items = list(cache.get("items", []))
        valid = {x["slug"] for x in _link_candidates_for_live_account(account_id, live_items)}
        if slug not in valid:
            raise ValueError("Lokale Anzeige ist nicht verfügbar, gehört zu einem anderen Konto oder ist bereits mit einer Live-Anzeige verbunden.")
        item = next((x for x in live_items if str((x or {}).get("id")) == str(ad_id)), {})
        _set_local_remote_link(slug, account_id, ad_id, posted=(item or {}).get("posted"), reason="Manuell mit Live-Anzeige verknüpft")
        _fetch_live_ads_to_cache(account_id)
        flash("Live-Anzeige wurde mit dem Anzeigen-Manager verknüpft.", "ok")
    except Exception as exc:
        flash("Verknüpfung fehlgeschlagen: " + str(exc), "err")
    return redirect(url_for("live_ads_view", account=return_account))

@app.route("/live-ads/<account_id>/<ad_id>/unlink", methods=["POST"])
def live_ad_unlink(account_id, ad_id):
    account_id = _valid_account_id(account_id)
    return_account = (request.form.get("return_account") or account_id).strip()
    slug = _find_local_ad_by_remote_id(ad_id, account_id)
    if slug:
        _set_live_link_ignore(account_id, ad_id, True)
    if slug and _unlink_local_remote(slug):
        try:
            _fetch_live_ads_to_cache(account_id)
        except Exception:
            pass
        flash("Verknüpfung gelöst. Die Live-Anzeige selbst wurde nicht verändert.", "ok")
    else:
        flash("Keine lokale Verknüpfung gefunden.", "warn")
    return redirect(url_for("live_ads_view", account=return_account))


@app.route("/live-ads/<account_id>/<ad_id>/reserve", methods=["POST"])
def live_ad_reserve(account_id, ad_id):
    account_id = _valid_account_id(account_id)
    try:
        api, _auth = _api_client(account_id)
        # Kleinanzeigen bildet "Reservieren" im Management als pausierten Zustand ab.
        # Das Inserat wird nicht gelöscht und kann später wieder aktiviert werden.
        api.pause_ad(str(ad_id))
        _set_live_ad_reserved(account_id, ad_id, True)
        flash("Anzeige bei Kleinanzeigen reserviert.", "ok")
    except Exception as exc:
        flash("Anzeige konnte nicht reserviert werden: " + str(exc), "err")
    return _live_ad_action_redirect(account_id)


@app.route("/live-ads/<account_id>/<ad_id>/activate", methods=["POST"])
def live_ad_activate(account_id, ad_id):
    account_id = _valid_account_id(account_id)
    try:
        api, _auth = _api_client(account_id)
        api.activate_ad(str(ad_id))
        _set_live_ad_reserved(account_id, ad_id, False)
        flash("Anzeige bei Kleinanzeigen wieder aktiviert.", "ok")
    except Exception as exc:
        flash("Anzeige konnte nicht aktiviert werden: " + str(exc), "err")
    return _live_ad_action_redirect(account_id)


@app.route("/live-ads/<account_id>/<ad_id>/delete", methods=["POST"])
def live_ad_delete(account_id, ad_id):
    try:
        slug = _direct_delete_remote(account_id, ad_id, sold=False)
        flash("Anzeige direkt bei Kleinanzeigen gelöscht." + (" Die verknüpfte Anzeige wurde auch aus der Verwaltung entfernt." if slug else ""), "ok")
    except Exception as exc:
        flash("Anzeige wurde nicht gelöscht: " + str(exc), "err")
    return _live_ad_action_redirect(account_id)


@app.route("/live-ads/<account_id>/<ad_id>/delete-everywhere", methods=["POST"])
def live_ad_delete_everywhere(account_id, ad_id):
    """Remove a linked live ad in both managers through the shared ID link."""
    try:
        account_id = _valid_account_id(account_id)
        slug = _find_local_ad_by_remote_id(ad_id, account_id)
        state = _load_state()
        _sync_vinted_transfer_receipts(state)
        prepared_vinted_delete = _vinted_delete_action_for_kleinanzeigen(slug, state) if slug else None
        if slug:
            _mark_cross_platform_terminal(slug, "Kleinanzeigen + Vinted löschen gewählt")
        try:
            deleted_slug = _direct_delete_remote(account_id, ad_id, sold=False)
        except Exception:
            if slug:
                _clear_cross_platform_terminal(slug)
            raise
        queued = bool(prepared_vinted_delete)
        if prepared_vinted_delete:
            target, payload, _meta = prepared_vinted_delete
            if not target.exists():
                _write_vinted_cross_action(target, payload)
        if queued:
            flash("Anzeige bei Kleinanzeigen und lokal gelöscht. Die eindeutig verknüpfte Vinted-Anzeige wird ebenfalls entfernt.", "ok")
        else:
            flash("Anzeige bei Kleinanzeigen gelöscht." + (" Die lokale Anzeige wurde entfernt." if deleted_slug else ""), "ok")
    except Exception as exc:
        flash("Anzeige wurde nicht vollständig gelöscht: " + str(exc), "err")
    return _live_ad_action_redirect(account_id)


@app.route("/live-ads/<account_id>/<ad_id>/sold", methods=["POST"])
def live_ad_sold(account_id, ad_id):
    try:
        slug = _direct_delete_remote(account_id, ad_id, sold=True)
        flash("Anzeige bei Kleinanzeigen gelöscht" + (" und lokal deaktiviert." if slug else "."), "ok")
    except Exception as exc:
        flash("Anzeige wurde nicht gelöscht: " + str(exc), "err")
    return redirect(url_for("live_ads_view", account=account_id))

# -- Routes: Settings --

def _status_from_iso(iso_value, *, fresh_seconds, warning_seconds):
    dt = _iso_dt(iso_value)
    if not dt:
        return "warning", "noch kein Lauf"
    age = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if age <= fresh_seconds:
        state = "ok"
    elif age <= warning_seconds:
        state = "warning"
    else:
        state = "error"
    if age < 60:
        label = f"vor {age} Sek."
    elif age < 3600:
        label = f"vor {max(1, age // 60)} Min."
    else:
        label = f"vor {age // 3600} Std."
    return state, label


def _system_status_rows_ka(state=None):
    state = state or _load_state()
    rows = []
    accounts = _account_select_records(state)

    for account in accounts:
        account_id = account.get("id")
        api = _api_account_status(account_id)
        rows.append({
            "title": f"API · {account.get('name')}",
            "state": "ok" if api.get("connected") else "warning",
            "value": "verbunden" if api.get("connected") else "nicht verbunden",
            "detail": "Nachrichten und Live-Anzeigen" if api.get("connected") else "In den Kontoeinstellungen einmal API-Login verbinden.",
        })

    monitor_accounts = ((state.get("message_monitor") or {}).get("accounts") or {}) if isinstance(state.get("message_monitor"), dict) else {}
    message_times = []
    message_errors = []
    for account in accounts:
        rec = monitor_accounts.get(account.get("id"), {}) if isinstance(monitor_accounts, dict) else {}
        if isinstance(rec, dict):
            if rec.get("updated_at"):
                message_times.append(rec.get("updated_at"))
            if rec.get("error"):
                message_errors.append(str(rec.get("error")))
    latest_message = max((_iso_dt(v) for v in message_times if _iso_dt(v)), default=None)
    msg_state, msg_age = _status_from_iso(latest_message.isoformat() if latest_message else None, fresh_seconds=20, warning_seconds=60)
    health = _runtime_health_snapshot()
    if health.get("messages") and not health["messages"].get("ok"):
        msg_state = "error"
    rows.append({
        "title": "Nachrichtenmonitor", "state": "error" if message_errors else msg_state,
        "value": message_errors[0][:80] if message_errors else msg_age,
        "detail": "Prüft beide Konten im Hintergrund auf neue eingehende Nachrichten.",
    })

    live_times = []
    live_errors = []
    for account in accounts:
        cache = _read_api_cache("live-ads", account.get("id"))
        if cache.get("updated_at"):
            live_times.append(cache.get("updated_at"))
        if cache.get("error"):
            live_errors.append(str(cache.get("error")))
    latest_live = max((_iso_dt(v) for v in live_times if _iso_dt(v)), default=None)
    live_state, live_age = _status_from_iso(latest_live.isoformat() if latest_live else None, fresh_seconds=420, warning_seconds=900)
    if health.get("live") and not health["live"].get("ok"):
        live_state = "error"
    rows.append({
        "title": "Live-Abgleich", "state": "error" if live_errors else live_state,
        "value": live_errors[0][:80] if live_errors else live_age,
        "detail": f"Aktualisiert eigene Live-Anzeigen ungefähr alle {max(1, LIVE_ADS_POLL_SECONDS // 60)} Minuten.",
    })

    auto_health = health.get("automation") or {}
    auto_state, auto_age = _status_from_iso(auto_health.get("updated_at"), fresh_seconds=35, warning_seconds=120)
    if auto_health and not auto_health.get("ok"):
        auto_state = "error"
    rows.append({
        "title": "Anzeigen-Automatik", "state": auto_state, "value": auto_age,
        "detail": str(auto_health.get("message") or "Prüft Veröffentlichung, Retry und fällige Erneuerungen.")[:160],
    })

    import_health = health.get("imports") or {}
    import_state, import_age = _status_from_iso(import_health.get("updated_at"), fresh_seconds=30, warning_seconds=120)
    if import_health and not import_health.get("ok"):
        import_state = "error"
    drive_state = state.get("google_drive_import") if isinstance(state.get("google_drive_import"), dict) else {}
    import_detail = f"Dateiwächter · {_count_import_files()} Datei(en) warten"
    if GOOGLE_DRIVE_IMPORT_ENABLED:
        if drive_state.get("last_error"):
            import_detail += f" · Drive: {str(drive_state.get('last_error'))[:90]}"
            import_state = "warning" if import_state != "error" else import_state
        else:
            import_detail += " · Google-Drive-Import aktiv"
    rows.append({"title": "Importüberwachung", "state": import_state, "value": import_age, "detail": import_detail})

    for quota in _live_quota_summary():
        count = quota.get("count")
        if count is None:
            q_state, q_value = "warning", "Stand unbekannt"
        elif int(count) >= int(quota.get("limit") or REPOST_LIMIT_LAST_30_DAYS):
            q_state, q_value = "error", f"{count}/{quota.get('limit')} erreicht"
        elif int(count) >= int((quota.get("limit") or REPOST_LIMIT_LAST_30_DAYS) * 0.85):
            q_state, q_value = "warning", f"{count}/{quota.get('limit')}"
        else:
            q_state, q_value = "ok", f"{count}/{quota.get('limit')}"
        rows.append({
            "title": f"30-Tage-Limit · {quota.get('name')}", "state": q_state, "value": q_value,
            "detail": (f"Noch {max(0, int(quota.get('limit') or 0) - int(count))} Veröffentlichungen möglich." if count is not None else "Aktivitätsstand bitte aktualisieren."),
        })

    retry_count = 0
    for meta in (state.get("ads") or {}).values():
        if not isinstance(meta, dict):
            continue
        if _iso_dt(meta.get("publish_retry_at")) or _iso_dt(meta.get("republish_retry_at")):
            retry_count += 1
    op_snapshot = _operation_snapshot()
    waiting_count = len([rec for rec in (op_snapshot.get("operations") or {}).values() if isinstance(rec, dict) and rec.get("status") == "waiting"])
    bot_running = bool(_last_log.get("running"))
    rows.append({
        "title": "Bot & Warteschlange",
        "state": "warning" if bot_running or retry_count or waiting_count else "ok",
        "value": "Bot läuft" if bot_running else "Bot frei",
        "detail": f"{max(retry_count, waiting_count)} Retry-Vorgang/-Vorgänge vorgemerkt." if (retry_count or waiting_count) else "Keine Retry-Warteschlange.",
    })
    return rows


def _logs_context():
    log_files = sorted(LOGS_DIR.glob("*.log"), reverse=True)[:20] if LOGS_DIR.is_dir() else []
    logs = []
    for lf in log_files:
        try:
            logs.append({"name": lf.name, "content": lf.read_text("utf-8", errors="replace")})
        except Exception:
            pass
    return logs, dict(_last_log)


@app.route("/settings", methods=["GET"])
def settings_form():
    state = _load_state()
    logs, last_log = _logs_context()
    return render_template(
        "settings.html",
        settings=_get_settings(),
        account_records=_account_ui_records(state),
        backup=_backup_overview(),
        backups=_list_backups(),
        shipping_option_groups=SHIPPING_OPTION_GROUPS,
        shipping_price_fields=SHIPPING_PRICE_FIELDS,
        system_status=_system_status_rows_ka(state),
        logs=logs, last_log=last_log,
    )

@app.route("/settings", methods=["POST"])
def settings_save():
    shipping_prices = {}
    for code, field_name in SHIPPING_PRICE_FIELDS.items():
        shipping_prices[code] = request.form.get(field_name, DEFAULT_SHIPPING_PRICES.get(code, "")).strip()
    settings = {
        "contact_name": request.form.get("contact_name", "").strip(),
        "default_location": request.form.get("default_location", "").strip(),
        "republish_days": int(request.form.get("republish_days", REPUBLISH_INTERVAL)),
        "shipping_prices": shipping_prices,
    }
    _ensure_bot_config(settings)
    flash("Standard-Einstellungen gespeichert!", "ok")
    return redirect(url_for("settings_form"))


@app.route("/settings/account/add", methods=["POST"])
def account_add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    if not name or not email or not password:
        flash("Für ein neues Konto werden Name, E-Mail und Passwort benötigt.", "err")
        return redirect(url_for("settings_form"))
    account_id = _create_account(name, email, password)
    flash(f"Konto '{_account_name(account_id)}' angelegt. Bitte einmal den Browser-Login durchführen.", "ok")
    return redirect(url_for("settings_form"))


@app.route("/settings/account/<account_id>", methods=["POST"])
def account_save(account_id):
    state = _load_state()
    account_id = _valid_account_id(account_id, state)
    rec = _account_record(account_id, state)
    name = request.form.get("name", "").strip() or rec.get("name") or account_id
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    _update_account_name(account_id, name)
    _write_account_login_and_defaults(account_id, email, password, preserve_password=True)
    flash(f"Konto '{name}' gespeichert.", "ok")
    return redirect(url_for("settings_form"))


@app.route("/settings/activity-refresh/<account_id>", methods=["POST"])
def refresh_activity(account_id):
    if _last_log.get("running"):
        flash("Bitte warten, bis der Bot fertig ist.", "err")
        return redirect(url_for("settings_form"))
    if _vnc_running():
        flash("Bitte zuerst die noVNC-Browser-Session beenden.", "err")
        return redirect(url_for("settings_form"))
    account_id = _valid_account_id(account_id)
    ok, msg, result = _refresh_account_activity_until_today(account_id, max_attempts=4, delay_seconds=2)
    if ok:
        flash(f"Aktivität von '{_account_name(account_id)}' aktualisiert.", "ok")
    else:
        flash(msg, "err")
    return redirect(url_for("settings_form"))

@app.route("/settings/backup-now", methods=["POST"])
def create_backup_now():
    try:
        path = _create_backup(reason='manuelles-backup')
        flash(f'Backup erstellt: {path.name}', 'ok')
    except Exception as e:
        flash('Backup fehlgeschlagen: ' + str(e), 'err')
    return redirect(url_for('settings_form'))

@app.route('/backups/<path:filename>')
def download_backup(filename):
    safe_name = Path(filename).name
    return send_from_directory(str(BACKUP_DIR), safe_name, as_attachment=True)

@app.route('/backups/import', methods=['POST'])
def import_backup_file():
    file = request.files.get('backup_file')
    if not file or not file.filename:
        flash('Bitte eine Backup-Datei auswaehlen.', 'err')
        return redirect(url_for('settings_form'))
    safe_name = Path(file.filename).name
    if not safe_name.lower().endswith('.zip'):
        flash('Es sind nur ZIP-Backups erlaubt.', 'err')
        return redirect(url_for('settings_form'))
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / safe_name
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        target = BACKUP_DIR / f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"
    file.save(str(target))
    flash(f'Backup importiert: {target.name}', 'ok')
    return redirect(url_for('settings_form'))

@app.route('/backups/restore/<path:filename>', methods=['POST'])
def restore_backup(filename):
    try:
        _restore_backup_file(filename)
        flash(f'Backup wiederhergestellt: {Path(filename).name}', 'ok')
    except Exception as e:
        flash('Wiederherstellen fehlgeschlagen: ' + str(e), 'err')
    return redirect(url_for('settings_form'))

# -- Routes: Manual Login (noVNC) --

@app.route("/manual-login", methods=["POST"])
def manual_login_start():
    account_id = _valid_account_id(request.form.get("account_id") or MAIN_ACCOUNT_ID)
    ok, msg = _start_vnc_login(account_id)
    if ok:
        flash(f"Browser für '{_account_name(account_id)}' gestartet! Öffne den noVNC-Link unten.", "ok")
    else:
        flash(msg, "err")
    return redirect(url_for("settings_form"))

@app.route("/manual-login-stop", methods=["POST"])
def manual_login_stop():
    _stop_vnc()
    flash("Browser-Session beendet. Login gespeichert.", "ok")
    return redirect(url_for("settings_form"))


def _publish_saved_ad(slug):
    ad = _read_ad_yaml(slug)
    if not ad:
        return False, "Anzeige nicht gefunden."
    if not ad.get("active", True):
        return False, "Die Anzeige ist pausiert und wurde deshalb nicht veröffentlicht."

    state_preview = _load_state()
    meta_preview = state_preview.setdefault("ads", {}).setdefault(slug, {})
    if meta_preview.get("last_published") or ad.get("id"):
        _clear_publish_retry(meta_preview)
        state_preview.setdefault("ads", {})[slug] = meta_preview
        _save_state(state_preview)
        return False, "Die Anzeige ist bereits veröffentlicht. Bitte dafür die Funktion „Erneuern“ verwenden."
    account_preview = _ad_account_id(slug, meta_preview, state_preview)
    _operation_begin_attempt(
        slug,
        "publish",
        "save",
        title=str(ad.get("title") or slug),
        account_id=account_preview,
    )

    if not _try_reserve_bot_slot():
        state = _load_state()
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        retry_at = _queue_publish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
        _save_state(state)
        _operation_wait(slug, "Bot ist belegt – neuer Versuch in 60 Sekunden.", retry_at, retry_mode="publish")
        return False, "Bot ist gerade beschäftigt. Veröffentlichung wird automatisch in 1 Minute erneut versucht."

    try:
        _operation_update(
            slug,
            status="reserved",
            message="Bot ist frei – Veröffentlichung wird gestartet.",
            account_id=account_preview,
            account_name=_account_name(account_preview, state_preview),
        )
        ad = _read_ad_yaml(slug)
        state = _load_state()
        existing_meta = state.setdefault("ads", {}).setdefault(slug, {})
        if not ad:
            _operation_failed(slug, "Anzeige wurde vor dem Start nicht mehr gefunden.")
            return False, "Anzeige nicht gefunden."
        if ad.get("id") or existing_meta.get("last_published"):
            _clear_publish_retry(existing_meta)
            state.setdefault("ads", {})[slug] = existing_meta
            _save_state(state)
            _operation_success(slug, "Anzeige ist bereits veröffentlicht – kein neuer Botlauf nötig.")
            return False, "Die Anzeige ist bereits veröffentlicht. Bitte dafür die Funktion „Erneuern“ verwenden."
        account_id = _ad_account_id(slug, existing_meta, state)
        if not _account_login(account_id).get("configured"):
            _operation_failed(slug, f"Kleinanzeigen-Konto '{_account_name(account_id, state)}' ist noch nicht eingerichtet.")
            return False, f"Kleinanzeigen-Konto '{_account_name(account_id, state)}' ist noch nicht eingerichtet."

        _operation_update(slug, status="checking", message="30-Tage-Limit wird geprüft.", account_id=account_id, account_name=_account_name(account_id, state))
        limit_ok, count, limit_msg = _ensure_publish_capacity(account_id, state)
        if not limit_ok:
            _clear_publish_retry(existing_meta)
            state.setdefault("ads", {})[slug] = existing_meta
            _save_state(state)
            _operation_failed(slug, "Nicht veröffentlicht: " + limit_msg)
            return False, limit_msg

        _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird veröffentlicht …")
        result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, slot_reserved=True)
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        if result.get("ok"):
            meta["last_published"] = _now()
            meta["publish_count"] = meta.get("publish_count", 0) + 1
            meta["scheduled_publish_at"] = None
            _clear_publish_retry(meta)
            _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
            _increment_activity_posted_count(account_id, 1, state)
            meta.setdefault("history", []).append({"action": f"beim Speichern veröffentlicht über {_account_name(account_id, state)}", "date": _now()})
            _operation_success(slug, "Erfolgreich veröffentlicht.")
        elif result.get("safe_retry"):
            retry_at = _queue_prestart_publish_retry(
                state, slug, meta, result,
                wait_message="Bot/Login-Prüfung fehlgeschlagen – neuer Versuch in 60 Sekunden.",
                origin_label="Speichern & Veröffentlichen",
            )
        else:
            meta.setdefault("history", []).append({"action": "Fehler bei Speichern & Veröffentlichen", "date": _now()})
            _operation_failed(slug, "Veröffentlichung fehlgeschlagen; kein automatischer Retry wegen unklarem Ausgang.")
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        if result.get("safe_retry") and not result.get("ok"):
            return False, (
                "Bot konnte noch nicht sicher starten. Neuer Versuch automatisch in 1 Minute."
                if retry_at else "Bot/Login-Prüfung wiederholt fehlgeschlagen; Vorgang wurde sicher gestoppt."
            )
        return bool(result.get("ok")), str(result.get("output") or "Unbekannter Fehler")
    except Exception as exc:
        _operation_failed(slug, "Manager-Fehler beim Speichern & Veröffentlichen: " + str(exc))
        raise
    finally:
        _release_bot_slot()


# -- Routes: Create / Edit Ad --

@app.route("/new", methods=["GET"])
def new_form():
    return_context = _index_return_context(request.args)
    return_url = url_for("index", **return_context)
    selected_folder = return_context.get("folder", "")
    default_folder = selected_folder if selected_folder not in {"", "all", "__none__"} else ""
    return render_template("form.html", mode="new", ad=None, slug=None, images=[],
                           price_types=PRICE_TYPES, conditions=CONDITIONS,
                           shipping_types=SHIPPING_TYPES, shipping_option_groups=SHIPPING_OPTION_GROUPS, default_shipping_options=DEFAULT_SHIPPING_OPTIONS, ad_types=AD_TYPES,
                           shipping_prices=_get_shipping_prices(),
                           preset_categories=PRESET_CATEGORIES, folders=_all_folders(), defaults=_get_settings(),
                           schedule={"date": "", "time": ""}, can_publish_after_save=True,
                           return_context=return_context, return_url=return_url,
                           default_folder=default_folder, account_records=_account_ui_records(), ad_account_id=MAIN_ACCOUNT_ID, ad_is_online=False,
                           live_edit=False, live_account="all")

@app.route("/new", methods=["POST"])
def new_save():
    return_context = _index_return_context(request.form, prefix="return_")
    return_url = url_for("index", **return_context)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Titel ist erforderlich!", "err")
        return redirect(url_for("new_form", **return_context))
    slug = _slug(title)
    if _ad_yaml_path(slug).exists():
        slug = slug + "-" + str(uuid.uuid4())[:4]
    _create_backup(reason='vor-neuer-anzeige', slug=slug)
    images = _save_uploaded_images(slug, request.files.getlist("images"))
    images = _normalize_image_order(slug, images)
    form_data = _extract_form_data(request.form)
    schedule_at = _parse_schedule_form(request.form)
    _write_ad_yaml(slug, form_data, images)
    state = _load_state()
    account_id = _valid_account_id(request.form.get("account_id") or MAIN_ACCOUNT_ID, state)
    state["ads"][slug] = {
        "created_at": _now(),
        "last_published": None,
        "publish_count": 0,
        "scheduled_publish_at": schedule_at,
        "account_id": account_id,
        "history": [{"action": f"erstellt · Konto {_account_name(account_id, state)}", "date": _now()}],
    }
    _save_state(state)
    if request.form.get("save_action") == "publish":
        ok, output = _publish_saved_ad(slug)
        if ok:
            flash("Anzeige gespeichert und veröffentlicht!", "ok")
        else:
            flash("Anzeige wurde gespeichert, konnte aber nicht veröffentlicht werden: " + output[:220], "warn")
    else:
        flash("Anzeige gespeichert!", "ok")
    return redirect(return_url)

@app.route("/edit/<slug>", methods=["GET"])
def edit_form(slug):
    return_context = _index_return_context(request.args)
    live_edit = request.args.get("live") == "1"
    live_account = (request.args.get("live_account") or "all").strip()
    live_id = (request.args.get("live_id") or "").strip()
    live_source_account = (request.args.get("live_source_account") or "").strip()
    if live_edit and live_source_account:
        live_source_account = _valid_account_id(live_source_account)
    return_url = url_for("live_ads_view", account=live_account) if live_edit else url_for("index", **return_context)
    ad = _read_ad_yaml(slug)
    if not ad:
        return redirect(return_url)
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    schedule = _split_schedule_form_value(meta.get("scheduled_publish_at"))
    can_publish_after_save = not bool(meta.get("last_published")) and not bool(ad.get("id"))
    return render_template("form.html", mode="edit", ad=ad, slug=slug,
                           images=_list_ad_images(slug), price_types=PRICE_TYPES,
                           conditions=CONDITIONS, shipping_types=SHIPPING_TYPES, shipping_option_groups=SHIPPING_OPTION_GROUPS,
                           default_shipping_options=DEFAULT_SHIPPING_OPTIONS, ad_types=AD_TYPES, shipping_prices=_get_shipping_prices(),
                           preset_categories=PRESET_CATEGORIES, folders=_all_folders(),
                           defaults=_get_settings(), schedule=schedule, can_publish_after_save=can_publish_after_save,
                           account_records=_account_ui_records(state), ad_account_id=_ad_account_id(slug, meta, state),
                           ad_is_online=bool(meta.get("last_published") or ad.get("id")),
                           return_context=return_context, return_url=return_url,
                           live_edit=live_edit, live_account=live_account, live_id=live_id,
                           live_source_account=live_source_account)

@app.route("/edit/<slug>", methods=["POST"])
def edit_save(slug):
    live_return_account = (request.form.get("return_live_account") or "").strip()
    return_url = url_for("live_ads_view", account=live_return_account) if live_return_account else _index_return_url(request.form, prefix="return_")
    ad = _read_ad_yaml(slug)
    if not ad:
        return redirect(return_url)
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    current_account = _ad_account_id(slug, meta, state)
    requested_account = _valid_account_id(request.form.get("account_id") or current_account, state)
    explicit_live_id = (request.form.get("return_live_id") or "").strip()
    explicit_live_account = (request.form.get("return_live_source_account") or "").strip()
    if explicit_live_account:
        requested_account = _valid_account_id(explicit_live_account, state)
    if explicit_live_id and str(ad.get("id") or "").strip() != explicit_live_id:
        # Die Live-Seite ist die autoritative Quelle für genau den Datensatz,
        # dessen Bearbeiten-Button angeklickt wurde. Eine verlorene/stale ID darf
        # die Live-Aktualisierung nicht stillschweigend verhindern.
        _set_local_remote_link(slug, requested_account, explicit_live_id,
                               posted=meta.get("last_published"),
                               reason="Live-ID vor Bearbeitung synchronisiert")
        ad = _read_ad_yaml(slug) or ad
        state = _load_state()
        meta = state.get("ads", {}).get(slug, meta)
        current_account = _ad_account_id(slug, meta, state)
    is_online = bool(meta.get("last_published") or ad.get("id") or explicit_live_id)
    before_live_ad = copy.deepcopy(ad)
    prepare_move = request.form.get("prepare_account_move") == "on"
    if requested_account != current_account and is_online and not prepare_move:
        flash("Die Anzeige ist noch als online gespeichert. Lösche sie zuerst manuell bei Kleinanzeigen und bestätige anschließend 'Alte Live-Anzeige bereits gelöscht'.", "warn")
        return redirect(url_for("edit_form", slug=slug, **_index_return_context(request.form, prefix="return_")))

    new_images = _save_uploaded_images(slug, request.files.getlist("images"))
    existing = _list_ad_images(slug)
    remove_imgs = request.form.getlist("remove_image")
    for img_name in remove_imgs:
        p = _ad_images_dir(slug) / img_name
        if p.exists():
            p.unlink()
    kept = [i for i in existing if i not in remove_imgs]
    kept = _sort_existing_images_from_form(kept, request.form)
    ordered_images = _normalize_image_order(slug, kept + new_images)
    form_data = _extract_form_data(request.form)
    schedule_at = _parse_schedule_form(request.form)
    _write_ad_yaml(slug, form_data, ordered_images)

    if requested_account != current_account and is_online and prepare_move:
        _create_backup(reason="vor-konto-wechsel", slug=slug)
        _reset_ad_for_manual_account_move(slug, meta, requested_account)
        schedule_at = None
    else:
        meta["account_id"] = requested_account
        if requested_account != current_account:
            meta.setdefault("history", []).append({"action": f"Konto geändert: {_account_name(current_account, state)} → {_account_name(requested_account, state)}", "date": _now()})
    meta["scheduled_publish_at"] = schedule_at
    _append_price_history(
        meta,
        before_live_ad.get("price"),
        form_data.get("price"),
        source="manual",
        action="Preis manuell geändert",
    )
    meta.setdefault("history", []).append({"action": "bearbeitet", "date": _now()})
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    save_action = "live_update" if request.args.get("live_update") == "1" else request.form.get("save_action")
    if save_action == "live_update":
        current_live_ad = _read_ad_yaml(slug) or {}
        live_remote_id = str(current_live_ad.get("id") or explicit_live_id or "").strip()
        if not live_remote_id:
            flash("Live-Aktualisierung nicht möglich: Es fehlt die Verknüpfung zur Live-Anzeige.", "err")
        elif not _account_login(requested_account).get("configured"):
            flash(f"Live-Aktualisierung nicht möglich: Kleinanzeigen-Konto '{_account_name(requested_account, state)}' ist nicht eingerichtet.", "err")
        elif _last_log.get("running"):
            flash("Live-Aktualisierung nicht gestartet: Der Kleinanzeigen-Bot läuft bereits.", "warn")
        else:
            # Vor dem Prozessstart ein eigenes Diagnose-Artefakt schreiben. So ist
            # eindeutig erkennbar, dass der Klick den Live-Update-Pfad erreicht hat,
            # selbst wenn Python/Chromium anschließend nicht starten kann.
            try:
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                (LOGS_DIR / f"{ts}_live-update-request.log").write_text(
                    f"slug={slug}\naccount={requested_account}\nremote_id={live_remote_id}\nrequested_at={_now()}\n",
                    "utf-8",
                )
            except Exception:
                pass
            print(f"[live-update] Starte Bot: slug={slug} account={requested_account} remote_id={live_remote_id}", flush=True)
            update_proof = _live_update_proof(before_live_ad, current_live_ad)
            result = _run_bot_for_slug(
                "update", slug, ads=str(live_remote_id), account_id=requested_account, update_proof=update_proof
            )
            if result.get("ok"):
                state2 = _load_state()
                meta2 = state2.setdefault("ads", {}).setdefault(slug, {})
                meta2.setdefault("history", []).append({"action": "bestehende Live-Anzeige aktualisiert", "date": _now()})
                _save_state(state2)
                try:
                    _fetch_live_ads_to_cache(requested_account)
                except Exception:
                    pass
                flash("Änderungen gespeichert und bestehende Live-Anzeige aktualisiert!", "ok")
            else:
                flash("Lokal gespeichert, Live-Aktualisierung fehlgeschlagen: " + str(result.get("output") or "")[:220], "warn")
        live_account = (request.form.get("return_live_account") or requested_account).strip()
        return redirect(url_for("live_ads_view", account=live_account))
    if save_action == "publish":
        ok, output = _publish_saved_ad(slug)
        if ok:
            flash("Änderungen gespeichert und Anzeige veröffentlicht!", "ok")
        else:
            flash("Änderungen wurden gespeichert, die Veröffentlichung ist aber fehlgeschlagen: " + output[:220], "warn")
    else:
        flash("Änderungen gespeichert!", "ok")
    return redirect(return_url)

def _extract_form_data(form):
    price_raw = form.get("price", "0").strip().replace(",", ".")
    try:
        price = float(price_raw) if price_raw else 0
    except ValueError:
        price = 0
    shipping_type = form.get("shipping_type", "SHIPPING")
    shipping_costs = form.get("shipping_costs", "").strip()

    # Neue Kleinanzeigen-Versandlogik: genau eine Paketgröße, darin mehrere Methoden.
    # Wichtig: Die Paketgröße aus dem Select ist führend. Falls der Browser aus irgendeinem
    # Grund noch alte, versteckte Klein-Haken mitsendet, werden sie hier verworfen.
    selected_shipping_options = []
    if shipping_type == "SHIPPING":
        requested_size = str(form.get("shipping_size", "SMALL")).strip() or "SMALL"
        valid_sizes = {group["key"] for group in SHIPPING_OPTION_GROUPS}
        if requested_size not in valid_sizes:
            requested_size = "SMALL"

        seen = set()
        for option in form.getlist("shipping_options"):
            option = str(option).strip()
            if (
                option in SHIPPING_OPTION_TO_GROUP
                and SHIPPING_OPTION_TO_GROUP[option] == requested_size
                and option not in seen
            ):
                selected_shipping_options.append(option)
                seen.add(option)

        # Wenn eine Größe gewählt wurde, aber keine Methode mehr aktiv ist, setzen wir
        # bewusst alle Methoden dieser Größe. Das passt zu deinem Standard-Workflow.
        if not selected_shipping_options:
            selected_shipping_options = [
                code
                for group in SHIPPING_OPTION_GROUPS
                if group["key"] == requested_size
                for code, _label in group["options"]
            ]
    else:
        shipping_costs = "0"

    republish_price_drop = form.get("republish_price_drop", "").strip().replace(",", ".")
    republish_min_price = form.get("republish_min_price", "").strip().replace(",", ".")
    return {
        "title": form.get("title", "").strip(),
        "description": form.get("description", "").strip(),
        "price": price,
        "price_type": form.get("price_type", "NEGOTIABLE"),
        "category": form.get("category", "").strip(),
        "folder": form.get("folder", "").strip(),
        "ad_type": form.get("ad_type", "OFFER"),
        "shipping_type": shipping_type,
        "shipping_costs": shipping_costs,
        "shipping_options": selected_shipping_options,
        "contact_name": form.get("contact_name", "").strip(),
        "location": form.get("location", "").strip(),
        "republish_days": form.get("republish_days", ""),
        "republish_price_reduction_enabled": form.get("republish_price_reduction_enabled") == "on",
        "republish_price_reduction_days": form.get("republish_price_reduction_days", ""),
        "republish_price_drop": republish_price_drop,
        "republish_min_price": republish_min_price,
        "active": form.get("active") == "on",
    }

# -- Routes: Bot Actions --


@app.route("/copy/<slug>", methods=["POST"])
def copy_ad(slug):
    _create_backup(reason='vor-kopie', slug=slug)
    new_slug = _copy_ad(slug)
    if new_slug:
        flash("Anzeige kopiert. Bitte vor dem Veröffentlichen Titel/Details prüfen.", "ok")
        return redirect(url_for("edit_form", slug=new_slug))
    flash("Anzeige konnte nicht kopiert werden.", "err")
    return redirect(url_for("index"))


@app.route("/bulk-action", methods=["POST"])
def bulk_action():
    action = (request.form.get("bulk_action") or "").strip()
    selected = _selected_slugs_from_form(request.form)
    if not selected:
        flash("Bitte mindestens eine Anzeige markieren.", "warn")
        return redirect(request.referrer or url_for("index"))

    # Publish/Republish dürfen bei belegtem Bot nicht mehr vorab abgewiesen
    # werden; ihre Schleifen reservieren pro Anzeige und merken +60 s vor.
    # Nur eine reine Remote-Löschaktion bleibt ohne Warteschlange.
    if action == "ka_delete" and _last_log.get("running"):
        flash("Der Bot läuft bereits. Bitte warten.", "warn")
        return redirect(request.referrer or url_for("index"))

    state = _load_state()
    ok_count = 0
    fail_count = 0

    if action == "activate":
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad:
                continue
            ad["active"] = True
            _write_yaml_file(_ad_yaml_path(slug), ad)
            meta = state.get("ads", {}).get(slug, {})
            meta.setdefault("history", []).append({"action": "aktiviert", "date": _now()})
            state.setdefault("ads", {})[slug] = meta
            ok_count += 1
        _save_state(state)
        flash(f"{ok_count} Anzeigen aktiviert.", "ok")
        return redirect(request.referrer or url_for("index"))

    if action == "pause":
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad:
                continue
            ad["active"] = False
            _write_yaml_file(_ad_yaml_path(slug), ad)
            meta = state.get("ads", {}).get(slug, {})
            meta.setdefault("history", []).append({"action": "pausiert", "date": _now()})
            state.setdefault("ads", {})[slug] = meta
            ok_count += 1
        _save_state(state)
        flash(f"{ok_count} Anzeigen pausiert.", "ok")
        return redirect(request.referrer or url_for("index"))

    if action == "automation":
        raw_republish = str(request.form.get("bulk_republish_days") or "").strip()
        raw_price_days = str(request.form.get("bulk_price_reduction_days") or "").strip()
        raw_drop = str(request.form.get("bulk_price_drop") or "").strip()
        raw_min = str(request.form.get("bulk_min_price") or "").strip()
        price_mode = str(request.form.get("bulk_price_mode") or "unchanged").strip().lower()
        if price_mode not in {"unchanged", "on", "off"}:
            abort(400)
        try:
            republish_days = max(1, min(3650, int(raw_republish))) if raw_republish else None
            price_days = max(1, min(3650, int(raw_price_days))) if raw_price_days else None
        except (TypeError, ValueError):
            flash("Tage müssen als ganze Zahl angegeben werden.", "err")
            return redirect(request.referrer or url_for("index"))
        try:
            drop = round(max(0.0, float(raw_drop.replace(",", "."))), 2) if raw_drop else None
            min_price = round(max(0.0, float(raw_min.replace(",", "."))), 2) if raw_min else None
        except (TypeError, ValueError):
            flash("Preiswerte bitte als Zahl angeben, z. B. 2 oder 35,50.", "err")
            return redirect(request.referrer or url_for("index"))
        if republish_days is None and price_days is None and drop is None and min_price is None and price_mode == "unchanged":
            flash("Bitte mindestens eine Automatik-Einstellung auswählen.", "warn")
            return redirect(request.referrer or url_for("index"))
        if price_mode == "on" and drop is None:
            missing_drop = []
            for slug in selected:
                current = _read_ad_yaml(slug) or {}
                if _parse_float(current.get("republish_price_drop"), 0.0) <= 0:
                    missing_drop.append(slug)
            if missing_drop:
                flash("Zum Einschalten der Preisautomatik bitte auch einen Reduktionsbetrag angeben.", "err")
                return redirect(request.referrer or url_for("index"))

        _create_backup(reason="vor-mehrfach-automatik")
        changed = 0
        giveaway_skipped = 0
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad:
                continue
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            before = {
                "republish_days": int(ad.get("republication_interval") or REPUBLISH_INTERVAL),
                "price": _price_reduction_config(ad),
            }
            if republish_days is not None:
                ad["republication_interval"] = republish_days
            if price_days is not None:
                ad["republish_price_reduction_days"] = price_days
            if drop is not None:
                ad["republish_price_drop"] = drop
            if min_price is not None:
                ad["republish_min_price"] = min_price
            if price_mode == "on":
                if str(ad.get("price_type") or "").upper() == "GIVE_AWAY":
                    ad["republish_price_reduction_enabled"] = False
                    giveaway_skipped += 1
                else:
                    ad["republish_price_reduction_enabled"] = True
            elif price_mode == "off":
                ad["republish_price_reduction_enabled"] = False
            if _parse_float(ad.get("republish_price_drop"), 0.0) <= 0:
                ad["republish_price_reduction_enabled"] = False

            after = {
                "republish_days": int(ad.get("republication_interval") or REPUBLISH_INTERVAL),
                "price": _price_reduction_config(ad),
            }
            if before == after:
                continue
            _write_yaml_file(_ad_yaml_path(slug), ad)
            cfg = _price_reduction_config(ad)
            if cfg.get("enabled") and not meta.get("price_reduction_anchor_at"):
                _ensure_price_reduction_anchor(slug, ad, meta)
            price_text = (
                f"Preis: −{_fmt_money(cfg.get('drop') or 0)} € alle {int(cfg.get('days') or DEFAULT_PRICE_REDUCTION_DAYS)} Tage"
                + (f" · Mindestpreis {_fmt_money(cfg.get('min_price'))} €" if float(cfg.get("min_price") or 0) > 0 else "")
                if cfg.get("enabled") else "Preisautomatik: aus"
            )
            meta.setdefault("history", []).append({
                "action": f"Automatik geändert: Erneuern alle {int(ad.get('republication_interval') or REPUBLISH_INTERVAL)} Tage · {price_text}",
                "date": _now(),
            })
            state.setdefault("ads", {})[slug] = meta
            changed += 1
        _save_state(state)
        if giveaway_skipped:
            flash(f"Automatik für {changed} Anzeige(n) aktualisiert. Bei {giveaway_skipped} Zu-verschenken-Anzeige(n) bleibt die Preisautomatik aus.", "warn")
        else:
            flash(f"Automatik-Einstellungen für {changed} Anzeige(n) aktualisiert.", "ok")
        return redirect(request.referrer or url_for("index"))

    if action == "move_folder":
        folder = (request.form.get("bulk_folder") or "").strip()
        folders = _all_folders()
        if folder and folder != "__none__" and folder not in folders:
            flash("Bitte einen vorhandenen Ordner auswählen. Neue Ordner bitte oben über 'Neuer Ordner' anlegen.", "warn")
            return redirect(request.referrer or url_for("index"))
        _create_backup(reason='vor-mehrfach-ordner-verschieben')
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad:
                continue
            if folder and folder != "__none__":
                ad["folder"] = folder
            else:
                ad.pop("folder", None)
            _write_yaml_file(_ad_yaml_path(slug), ad)
            ok_count += 1
        target_label = folder if folder and folder != "__none__" else "Ohne Ordner"
        flash(f"{ok_count} Anzeigen in '{target_label}' verschoben.", "ok")
        return redirect(url_for("index", folder=folder if folder else "__none__", sort="next_due"))

    if action == "move_account":
        target_account = _valid_account_id(request.form.get("bulk_account") or MAIN_ACCOUNT_ID, state)
        prepare_move = request.form.get("bulk_prepare_account_move") == "on"
        _create_backup(reason="vor-mehrfach-konto-wechsel")
        skipped_online = 0
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad:
                continue
            meta = state.get("ads", {}).get(slug, {})
            current_account = _ad_account_id(slug, meta, state)
            is_online = bool(meta.get("last_published") or ad.get("id"))
            if current_account == target_account and not prepare_move:
                continue
            if is_online and current_account != target_account and not prepare_move:
                skipped_online += 1
                continue
            if is_online and current_account != target_account and prepare_move:
                _reset_ad_for_manual_account_move(slug, meta, target_account)
            else:
                meta["account_id"] = target_account
                meta.setdefault("history", []).append({"action": f"Konto geändert: {_account_name(current_account, state)} → {_account_name(target_account, state)}", "date": _now()})
            state.setdefault("ads", {})[slug] = meta
            ok_count += 1
        _save_state(state)
        if skipped_online:
            flash(f"{ok_count} Anzeigen zugeordnet; {skipped_online} noch online gespeicherte Anzeigen nicht geändert. Dafür zuerst extern löschen und die Bestätigung aktivieren.", "warn")
        else:
            flash(f"{ok_count} Anzeigen '{_account_name(target_account, state)}' zugeordnet.", "ok")
        return redirect(url_for("index", account=target_account, sort="account"))

    if action == "copy":
        _create_backup(reason='vor-mehrfach-kopie')
        for slug in selected:
            if _copy_ad(slug):
                ok_count += 1
            else:
                fail_count += 1
        flash(f"{ok_count} Anzeigen kopiert" + (f", {fail_count} fehlgeschlagen." if fail_count else "."), "ok" if not fail_count else "warn")
        return redirect(request.referrer or url_for("index"))

    if action == "vinted_transfer":
        if _sync_vinted_transfer_receipts(state):
            pass
        queued_count = 0
        skipped_count = 0
        errors: list[str] = []
        for slug in selected:
            transfer_status, message = _queue_vinted_transfer(slug, state)
            if transfer_status == "queued":
                queued_count += 1
            elif transfer_status == "skipped":
                skipped_count += 1
            else:
                errors.append(f"{slug}: {message}")
        _save_state(state)
        parts = []
        if queued_count:
            parts.append(f"{queued_count} Anzeige(n) an Vinted übergeben")
        if skipped_count:
            parts.append(f"{skipped_count} bereits übertragene übersprungen")
        if errors:
            parts.append(f"{len(errors)} fehlgeschlagen")
        flash(" · ".join(parts) + "." if parts else "Keine Anzeige übertragen.", "ok" if not errors else "warn")
        return redirect(request.referrer or url_for("index"))

    if action == "delete_local":
        _create_backup(reason='vor-mehrfach-lokal-loeschen')
        for slug in selected:
            if _ad_yaml_path(slug).exists():
                _delete_local_slug(slug)
                ok_count += 1
        flash(f"{ok_count} Anzeigen lokal gelöscht.", "ok")
        return redirect(request.referrer or url_for("index"))

    if action == "ka_delete":
        _create_backup(reason='vor-mehrfach-ka-loeschen')
        for slug in selected:
            if not _read_ad_yaml(slug):
                continue
            result = _run_bot_for_slug("delete", slug, ads="all")
            meta = state.get("ads", {}).get(slug, {})
            if result.get("ok"):
                meta.setdefault("history", []).append({"action": "von Kleinanzeigen geloescht", "date": _now()})
                ok_count += 1
            else:
                meta.setdefault("history", []).append({"action": "Fehler beim KA-Löschen", "date": _now()})
                fail_count += 1
            state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash(f"{ok_count} Anzeigen bei Kleinanzeigen gelöscht" + (f", {fail_count} fehlgeschlagen." if fail_count else "."), "ok" if not fail_count else "warn")
        return redirect(request.referrer or url_for("index"))

    if action == "publish":
        blocked_count = 0
        queued_count = 0
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad or not ad.get("active", True):
                continue
            state_preview = _load_state()
            meta_preview = state_preview.setdefault("ads", {}).setdefault(slug, {})
            if meta_preview.get("last_published") or ad.get("id"):
                _clear_publish_retry(meta_preview)
                state_preview.setdefault("ads", {})[slug] = meta_preview
                _save_state(state_preview)
                continue
            account_preview = _ad_account_id(slug, meta_preview, state_preview)
            _operation_begin_attempt(
                slug, "publish", "bulk",
                title=str(ad.get("title") or slug),
                account_id=account_preview,
            )
            if not _try_reserve_bot_slot():
                state = _load_state()
                meta = state.setdefault("ads", {}).setdefault(slug, {})
                retry_at = _queue_publish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
                _save_state(state)
                _operation_wait(slug, "Bot ist belegt – neuer Versuch in 60 Sekunden.", retry_at, retry_mode="publish")
                queued_count += 1
                continue
            try:
                _operation_update(
                    slug,
                    status="reserved",
                    message="Bot ist frei – Veröffentlichung wird gestartet.",
                    account_id=account_preview,
                    account_name=_account_name(account_preview, state_preview),
                )
                state = _load_state()
                ad = _read_ad_yaml(slug) or {}
                meta = state.setdefault("ads", {}).setdefault(slug, {})
                if not ad or meta.get("last_published") or ad.get("id"):
                    _operation_cancelled(slug, "Anzeige ist bereits veröffentlicht oder nicht mehr vorhanden.")
                    continue
                account_id = _ad_account_id(slug, meta, state)
                _operation_update(slug, status="checking", message="30-Tage-Limit wird geprüft.", account_id=account_id, account_name=_account_name(account_id, state))
                cap = list(_ensure_publish_capacity(account_id, state))
                if not cap[0] or cap[1] is None or cap[1] >= REPOST_LIMIT_LAST_30_DAYS:
                    _clear_publish_retry(meta)
                    meta.setdefault("history", []).append({"action": "Veröffentlichung blockiert: " + cap[2], "date": _now()})
                    state.setdefault("ads", {})[slug] = meta
                    _save_state(state)
                    _operation_failed(slug, "Nicht veröffentlicht: " + cap[2])
                    blocked_count += 1
                    continue
                _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird veröffentlicht …")
                result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, slot_reserved=True)
                if result.get("ok"):
                    meta["last_published"] = _now()
                    meta["publish_count"] = meta.get("publish_count", 0) + 1
                    meta["scheduled_publish_at"] = None
                    _clear_publish_retry(meta)
                    _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                    meta.setdefault("history", []).append({"action": f"veröffentlicht über {_account_name(account_id, state)}", "date": _now()})
                    ok_count += 1
                    _increment_activity_posted_count(account_id, 1, state)
                    _operation_success(slug, "Erfolgreich veröffentlicht.")
                elif _publish_result_requires_manual_review(result):
                    _clear_republish_retry(meta)
                    _clear_publish_retry(meta)
                    meta.setdefault("history", []).append({"action": "Neuveröffentlichung nach Absenden nicht eindeutig bestätigt; kein automatischer weiterer Versuch wegen möglicher Doppelanzeige", "date": _now()})
                    _operation_failed(slug, "Absenden wurde nicht eindeutig bestätigt. Es wurde kein weiterer Veröffentlichungsversuch gestartet, um eine Doppelanzeige zu verhindern.")
                    _notify_primary("Kleinanzeigen: Veröffentlichung prüfen", f"'{ad.get('title') or slug}' wurde möglicherweise bereits veröffentlicht. Es wurde sicher kein zweiter Versuch gestartet.", click_url=PUBLIC_BASE_URL)
                    fail_count += 1
                elif result.get("safe_retry"):
                    retry_at = _queue_prestart_publish_retry(
                        state, slug, meta, result,
                        wait_message="Bot/Login-Prüfung fehlgeschlagen – neuer Versuch in 60 Sekunden.",
                        origin_label="Sammelveröffentlichung",
                    )
                    if retry_at:
                        queued_count += 1
                    else:
                        fail_count += 1
                else:
                    meta.setdefault("history", []).append({"action": "Fehler beim Veroeffentlichen", "date": _now()})
                    _operation_failed(slug, "Veröffentlichung fehlgeschlagen; kein automatischer Retry wegen unklarem Ausgang.")
                    fail_count += 1
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
            finally:
                _release_bot_slot()
        parts = [f"{ok_count} Anzeigen veröffentlicht"]
        if queued_count: parts.append(f"{queued_count} automatisch in 1 Minute erneut vorgemerkt")
        if blocked_count: parts.append(f"{blocked_count} wegen 30-Tage-Limit blockiert")
        if fail_count: parts.append(f"{fail_count} fehlgeschlagen")
        flash(" · ".join(parts) + ".", "ok" if not fail_count and not blocked_count else "warn")
        return redirect(request.referrer or url_for("index"))

    if action == "republish":
        blocked_count = 0
        queued_count = 0
        safe_stop_count = 0
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad or not ad.get("active", True):
                continue

            state_preview = _load_state()
            meta_preview = state_preview.setdefault("ads", {}).setdefault(slug, {})
            if not (meta_preview.get("last_published") or ad.get("id")):
                _clear_republish_retry(meta_preview)
                state_preview.setdefault("ads", {})[slug] = meta_preview
                _save_state(state_preview)
                safe_stop_count += 1
                continue
            account_preview = _ad_account_id(slug, meta_preview, state_preview)
            _operation_begin_attempt(
                slug, "republish", "bulk",
                title=str(ad.get("title") or slug),
                account_id=account_preview,
                retry_mode="republish",
            )

            if not _try_reserve_bot_slot():
                state = _load_state()
                meta = state.setdefault("ads", {}).setdefault(slug, {})
                retry_at = _queue_republish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
                _save_state(state)
                _operation_wait(
                    slug,
                    "Bot ist belegt – Live-Anzeige bleibt online; neuer Versuch in 60 Sekunden.",
                    retry_at,
                    retry_mode="republish",
                    old_live_deleted=False,
                )
                queued_count += 1
                continue

            try:
                _operation_update(
                    slug,
                    status="reserved",
                    message="Bot ist frei – Erneuern wird gestartet.",
                    account_id=account_preview,
                    account_name=_account_name(account_preview, state_preview),
                )
                state = _load_state()
                ad = _read_ad_yaml(slug) or {}
                meta = state.setdefault("ads", {}).setdefault(slug, {})
                account_id = _ad_account_id(slug, meta, state)

                _operation_update(slug, status="checking", message="30-Tage-Limit wird geprüft.", account_id=account_id, account_name=_account_name(account_id, state))
                cap = list(_ensure_publish_capacity(account_id, state))
                cap_kind = _capacity_failure_kind(cap[0], cap[1], cap[2])
                if cap_kind != "ok":
                    if cap_kind == "technical":
                        meta.pop("republish_postponed_until", None)
                        retry_at = _queue_republish_retry(state, slug, meta, "30-Tage-Prüfung technisch nicht verfügbar")
                        state.setdefault("ads", {})[slug] = meta
                        _save_state(state)
                        _operation_wait(
                            slug,
                            "30-Tage-Prüfung technisch nicht verfügbar – Live-Anzeige bleibt online; neuer Versuch in 60 Sekunden.",
                            retry_at,
                            retry_mode="republish",
                            old_live_deleted=False,
                        )
                        queued_count += 1
                        continue
                    _clear_republish_retry(meta)
                    meta.setdefault("history", []).append({"action": "Erneuern blockiert: " + cap[2], "date": _now()})
                    state.setdefault("ads", {})[slug] = meta
                    _save_state(state)
                    _operation_failed(slug, "Nicht erneuert; Live-Anzeige blieb online: " + cap[2])
                    blocked_count += 1
                    continue

                old_id = str(ad.get("id") or "").strip()
                if not old_id and meta.get("last_published"):
                    _operation_update(slug, status="checking", message="Live-Verknüpfung wird vor dem Löschen geprüft …")
                    try:
                        _listings, items = _fetch_live_ads_raw(account_id)
                        _reconcile_live_links(account_id, items)
                        ad = _read_ad_yaml(slug) or ad
                        old_id = str(ad.get("id") or "").strip()
                    except Exception as exc:
                        print(f"[bulk-republish] Live-ID-Abgleich für {slug} fehlgeschlagen: {exc}", flush=True)

                if not old_id:
                    _clear_republish_retry(meta)
                    state.setdefault("ads", {})[slug] = meta
                    _save_state(state)
                    _operation_failed(slug, "Erneuern gestoppt: Live-ID fehlt; nichts gelöscht und nichts neu veröffentlicht.")
                    safe_stop_count += 1
                    continue

                _operation_update(slug, status="deleting", message="Alte Live-Anzeige wird gelöscht …")
                try:
                    _create_backup(reason="vor-sammel-repost-live-loeschen", slug=slug)
                    _delete_remote_only(account_id, old_id)
                    _clear_local_remote_id_only(slug)
                    meta["last_published"] = None
                    _mark_republish_delete_success(meta, old_id)
                    meta.setdefault("history", []).append({"action": f"alte Live-ID {old_id} direkt gelöscht", "date": _now()})
                    _operation_update(slug, old_live_deleted=True, message="Alte Live-Anzeige gelöscht – Neuveröffentlichung wird vorbereitet …")
                except Exception as exc:
                    delete_error = str(exc) or exc.__class__.__name__
                    meta.setdefault("history", []).append({"action": f"alte Live-ID {old_id} konnte nicht gelöscht werden: {delete_error}", "date": _now()})
                    _clear_republish_retry(meta)
                    state.setdefault("ads", {})[slug] = meta
                    _save_state(state)
                    _operation_failed(slug, "Löschen der alten Live-Anzeige nicht sicher bestätigt; kein automatischer zweiter Löschversuch.")
                    _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': Löschen der alten Anzeige nicht sicher bestätigt. Es wurde kein weiterer Löschversuch gestartet.", click_url=PUBLIC_BASE_URL)
                    fail_count += 1
                    continue

                price_change = _prepare_republish_price_reduction(slug, meta)
                _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird neu veröffentlicht …")
                result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, force_new=True, slot_reserved=True)
                if not result.get("ok") and price_change:
                    _restore_republish_price(slug, price_change["old_price"])

                if result.get("ok"):
                    meta["last_published"] = _now()
                    meta["publish_count"] = meta.get("publish_count", 0) + 1
                    meta["scheduled_publish_at"] = None
                    meta.pop("republish_postponed_until", None)
                    _clear_republish_retry(meta)
                    _clear_publish_retry(meta)
                    _clear_republish_transaction(meta)
                    if price_change:
                        _commit_price_reduction(meta, price_change)
                        meta.setdefault("history", []).append({"action": f"Preis gesenkt: {_fmt_money(price_change['old_price'])} € → {_fmt_money(price_change['new_price'])} €", "date": _now()})
                    else:
                        _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                    meta.setdefault("history", []).append({"action": f"neu eingestellt über {_account_name(account_id, state)}", "date": _now()})
                    ok_count += 1
                    _increment_activity_posted_count(account_id, 1, state)
                    _operation_success(slug, "Erfolgreich erneuert." if result.get("remote_id") else "Erfolgreich erneuert; Live-ID-Verknüpfung wird noch nachgezogen.")
                    _notify_primary("Kleinanzeigen: Anzeige veröffentlicht", f"'{ad.get('title') or slug}' wurde erneuert und remote bestätigt (ID {result.get('remote_id')}).", click_url=PUBLIC_BASE_URL)
                elif _publish_result_requires_manual_review(result):
                    _clear_republish_retry(meta)
                    _clear_publish_retry(meta)
                    meta.setdefault("history", []).append({"action": "Neuveröffentlichung nach Absenden nicht eindeutig bestätigt; kein automatischer weiterer Versuch wegen möglicher Doppelanzeige", "date": _now()})
                    _operation_failed(slug, "Absenden wurde nicht eindeutig bestätigt. Es wurde kein weiterer Veröffentlichungsversuch gestartet, um eine Doppelanzeige zu verhindern.")
                    _notify_primary("Kleinanzeigen: Veröffentlichung prüfen", f"'{ad.get('title') or slug}' wurde möglicherweise bereits veröffentlicht. Es wurde sicher kein zweiter Versuch gestartet.", click_url=PUBLIC_BASE_URL)
                    fail_count += 1
                elif result.get("safe_retry"):
                    _clear_republish_retry(meta)
                    retry_at = _queue_publish_only_after_republish(state, slug, meta, "Neuveröffentlichung nach Erneuern konnte noch nicht starten")
                    if retry_at:
                        _operation_wait(slug, "Alte Anzeige ist gelöscht; nur die Neuveröffentlichung wird in 60 Sekunden erneut versucht.", retry_at, retry_mode="publish_only", old_live_deleted=True)
                        queued_count += 1
                    else:
                        _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                        _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                        fail_count += 1
                else:
                    meta.setdefault("history", []).append({"action": "Fehler beim Republish", "date": _now()})
                    retry_at = _queue_publish_only_after_republish(state, slug, meta, str(result.get("output") or "Publish fehlgeschlagen")[:240])
                    if retry_at:
                        _operation_wait(slug, "Alte Anzeige ist gelöscht; nur Neuveröffentlichung wird erneut versucht.", retry_at, retry_mode="publish_only", old_live_deleted=True)
                        queued_count += 1
                    else:
                        _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                        _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                        fail_count += 1

                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
            finally:
                _release_bot_slot()

        parts = [f"{ok_count} Anzeigen neu eingestellt"]
        if queued_count: parts.append(f"{queued_count} automatisch in 1 Minute erneut vorgemerkt")
        if blocked_count: parts.append(f"{blocked_count} wegen 30-Tage-Limit nicht gelöscht")
        if safe_stop_count: parts.append(f"{safe_stop_count} wegen fehlender Live-ID sicher gestoppt")
        if fail_count: parts.append(f"{fail_count} fehlgeschlagen")
        flash(" · ".join(parts) + ".", "ok" if not fail_count and not blocked_count and not safe_stop_count else "warn")
        return redirect(request.referrer or url_for("index"))

    flash("Unbekannte Sammelaktion.", "err")
    return redirect(request.referrer or url_for("index"))

@app.route("/publish-selected", methods=["POST"])
def publish_selected():
    raw_slugs = request.form.getlist("selected_slugs")
    selected = []
    seen = set()
    state = _load_state()
    ads_meta = state.get("ads", {})
    for slug in raw_slugs:
        slug = (slug or "").strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        ad = _read_ad_yaml(slug)
        if not ad:
            continue
        meta = ads_meta.get(slug, {})
        is_active = ad.get("active", True)
        is_planned = is_active and not bool(meta.get("last_published")) and not bool(ad.get("id"))
        if is_planned:
            selected.append(slug)

    if not selected:
        flash("Bitte mindestens eine unveröffentlichte Anzeige auswählen.", "warn")
        return redirect(url_for("index", status="unpublished"))

    ok_count = fail_count = blocked_count = queued_count = 0
    for slug in selected:
        ad_preview = _read_ad_yaml(slug) or {}
        state_preview = _load_state()
        meta_preview = state_preview.setdefault("ads", {}).setdefault(slug, {})
        if meta_preview.get("last_published") or ad_preview.get("id"):
            _clear_publish_retry(meta_preview)
            state_preview.setdefault("ads", {})[slug] = meta_preview
            _save_state(state_preview)
            continue
        account_preview = _ad_account_id(slug, meta_preview, state_preview)
        _operation_begin_attempt(
            slug, "publish", "selected",
            title=str(ad_preview.get("title") or slug),
            account_id=account_preview,
        )

        if not _try_reserve_bot_slot():
            state = _load_state()
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            retry_at = _queue_publish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
            _save_state(state)
            _operation_wait(slug, "Bot ist belegt – neuer Versuch in 60 Sekunden.", retry_at, retry_mode="publish")
            queued_count += 1
            continue

        try:
            _operation_update(
                slug,
                status="reserved",
                message="Bot ist frei – Veröffentlichung wird gestartet.",
                account_id=account_preview,
                account_name=_account_name(account_preview, state_preview),
            )
            state = _load_state()
            ad = _read_ad_yaml(slug) or {}
            meta = state.setdefault("ads", {}).setdefault(slug, {})
            if not ad or meta.get("last_published") or ad.get("id"):
                _operation_cancelled(slug, "Anzeige ist bereits veröffentlicht oder nicht mehr vorhanden.")
                continue
            account_id = _ad_account_id(slug, meta, state)
            _operation_update(slug, status="checking", message="30-Tage-Limit wird geprüft.", account_id=account_id, account_name=_account_name(account_id, state))
            cap = list(_ensure_publish_capacity(account_id, state))
            if not cap[0] or cap[1] is None or cap[1] >= REPOST_LIMIT_LAST_30_DAYS:
                _clear_publish_retry(meta)
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                _operation_failed(slug, "Nicht veröffentlicht: " + cap[2])
                blocked_count += 1
                continue
            _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird veröffentlicht …")
            result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, slot_reserved=True)
            if result.get("ok"):
                meta["last_published"] = _now()
                meta["publish_count"] = meta.get("publish_count", 0) + 1
                meta["scheduled_publish_at"] = None
                _clear_publish_retry(meta)
                _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                meta.setdefault("history", []).append({"action": f"veröffentlicht über {_account_name(account_id, state)}", "date": _now()})
                ok_count += 1
                _increment_activity_posted_count(account_id, 1, state)
                _operation_success(slug, "Erfolgreich veröffentlicht.")
            elif result.get("safe_retry"):
                retry_at = _queue_prestart_publish_retry(
                    state, slug, meta, result,
                    wait_message="Bot/Login-Prüfung fehlgeschlagen – neuer Versuch in 60 Sekunden.",
                    origin_label="Mehrfachveröffentlichung",
                )
                if retry_at:
                    queued_count += 1
                else:
                    fail_count += 1
            else:
                meta.setdefault("history", []).append({"action": "Fehler beim Veroeffentlichen", "date": _now()})
                _operation_failed(slug, "Veröffentlichung fehlgeschlagen; kein automatischer Retry wegen unklarem Ausgang.")
                fail_count += 1
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
        finally:
            _release_bot_slot()

    parts = [f"{ok_count} Anzeigen veröffentlicht"]
    if queued_count: parts.append(f"{queued_count} automatisch in 1 Minute erneut vorgemerkt")
    if blocked_count: parts.append(f"{blocked_count} wegen Limit blockiert")
    if fail_count: parts.append(f"{fail_count} fehlgeschlagen")
    flash(" · ".join(parts) + ".", "ok" if not blocked_count and not fail_count else "warn")
    return redirect(url_for("index", status="unpublished"))


@app.route("/publish/<slug>", methods=["POST"])
def publish_ad(slug):
    ad = _read_ad_yaml(slug)
    if not ad:
        flash("Anzeige nicht gefunden.", "err")
        return redirect(url_for("index"))

    state = _load_state()
    meta = state.setdefault("ads", {}).setdefault(slug, {})
    if not ad.get("active", True):
        _clear_publish_retry(meta)
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash("Die Anzeige ist pausiert und wurde nicht veröffentlicht.", "warn")
        return redirect(url_for("index"))
    if meta.get("last_published") or ad.get("id"):
        _clear_publish_retry(meta)
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash("Anzeige ist bereits veröffentlicht.", "info")
        return redirect(url_for("index"))
    account_id = _ad_account_id(slug, meta, state)
    op = _operation_begin_attempt(
        slug,
        "publish",
        "manual",
        title=str(ad.get("title") or slug),
        account_id=account_id,
    )

    # Manueller Publish wartet nie still auf einen anderen Botlauf. Der Versuch
    # wird sichtbar vorgemerkt und nach 60 Sekunden erneut durch den Scheduler
    # aufgenommen.
    if not _try_reserve_bot_slot():
        state = _load_state()
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        retry_at = _queue_publish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
        _save_state(state)
        _operation_wait(
            slug,
            "Bot ist belegt – neuer Versuch in 60 Sekunden.",
            retry_at,
            retry_mode="publish",
        )
        flash("Bot ist gerade beschäftigt. Veröffentlichung automatisch in 1 Minute erneut vorgemerkt.", "info")
        return redirect(url_for("index"))

    try:
        _operation_update(
            slug,
            status="reserved",
            message="Bot ist frei – Veröffentlichung wird gestartet.",
            account_id=account_id,
            account_name=_account_name(account_id, state),
        )

        # Nach Reservierung alles neu lesen, damit ein paralleler Vorgang nicht mit
        # einem veralteten Status überschrieben wird.
        ad = _read_ad_yaml(slug)
        state = _load_state()
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        if not ad:
            _operation_failed(slug, "Anzeige wurde vor dem Start nicht mehr gefunden.")
            flash("Anzeige nicht gefunden.", "err")
            return redirect(url_for("index"))
        if meta.get("last_published") or ad.get("id"):
            _clear_publish_retry(meta)
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
            _operation_success(slug, "Anzeige ist bereits veröffentlicht – kein neuer Botlauf nötig.")
            flash("Anzeige ist bereits veröffentlicht.", "info")
            return redirect(url_for("index"))

        account_id = _ad_account_id(slug, meta, state)
        _operation_update(
            slug,
            status="checking",
            message="Bot ist frei – 30-Tage-Limit wird geprüft.",
            account_id=account_id,
            account_name=_account_name(account_id, state),
        )
        ok_limit, count, limit_msg = _ensure_publish_capacity(account_id, state)
        if not ok_limit:
            _clear_publish_retry(meta)
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
            _operation_failed(slug, "Nicht veröffentlicht: " + limit_msg)
            flash("Nicht veröffentlicht: " + limit_msg, "warn")
            return redirect(url_for("index"))

        _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird veröffentlicht …")
        result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, slot_reserved=True)
        if result["ok"]:
            meta["last_published"] = _now()
            meta["publish_count"] = meta.get("publish_count", 0) + 1
            meta["scheduled_publish_at"] = None
            _clear_publish_retry(meta)
            _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
            _increment_activity_posted_count(account_id, 1, state)
            meta.setdefault("history", []).append({"action": f"veröffentlicht über {_account_name(account_id, state)}", "date": _now()})
            _operation_success(slug, "Erfolgreich veröffentlicht.")
            flash("Anzeige veröffentlicht!", "ok")
        elif _publish_result_requires_manual_review(result):
            _clear_republish_retry(meta)
            _clear_publish_retry(meta)
            meta.setdefault("history", []).append({"action": "Neuveröffentlichung nach Absenden nicht eindeutig bestätigt; kein automatischer weiterer Versuch wegen möglicher Doppelanzeige", "date": _now()})
            _operation_failed(slug, "Absenden wurde nicht eindeutig bestätigt. Es wurde kein weiterer Veröffentlichungsversuch gestartet, um eine Doppelanzeige zu verhindern.")
            _notify_primary("Kleinanzeigen: Veröffentlichung prüfen", f"'{ad.get('title') or slug}' wurde möglicherweise bereits veröffentlicht. Es wurde sicher kein zweiter Versuch gestartet.", click_url=PUBLIC_BASE_URL)
            flash("Die Anzeige könnte bereits online sein. Der Live-Status war nicht eindeutig bestätigbar; zur Sicherheit wurde kein zweiter Versuch gestartet.", "warn")
        elif result.get("safe_retry"):
            retry_at = _queue_prestart_publish_retry(
                state, slug, meta, result,
                wait_message="Bot/Login-Prüfung scheiterte vor der Anzeigenverarbeitung – neuer Versuch in 60 Sekunden.",
                origin_label="Veröffentlichung",
            )
            flash(
                "Bot konnte noch nicht sicher starten. Neuer Versuch automatisch in 1 Minute."
                if retry_at else "Bot/Login-Prüfung wiederholt fehlgeschlagen. Vorgang wurde sicher gestoppt; bitte Debug-ZIP prüfen.",
                "warn",
            )
        else:
            meta.setdefault("history", []).append({"action": "Fehler beim Veroeffentlichen", "date": _now()})
            _operation_failed(slug, "Veröffentlichung fehlgeschlagen: " + str(result.get("output") or "Unbekannter Fehler")[:180])
            flash("Fehler: " + result["output"][:200], "err")
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        return redirect(url_for("index"))
    except Exception as exc:
        _operation_failed(slug, "Manager-Fehler beim Veröffentlichen: " + str(exc))
        raise
    finally:
        _release_bot_slot()

@app.route("/export/<slug>.kaanzeige")
def export_ad_package(slug):
    """Download one stored ad in the manager's existing import format."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", slug or ""):
        return "Anzeige nicht gefunden.", 404
    if not _ad_yaml_path(slug).is_file():
        return "Anzeige nicht gefunden.", 404
    try:
        archive = _build_kaanzeige_export(slug)
    except (FileNotFoundError, ValueError) as exc:
        return str(exc), 400
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{slug}.kaanzeige",
        max_age=0,
    )


@app.route("/yaml/<slug>")
def download_ad_yaml(slug):
    """Read-only download of an ad's stored YAML for diagnosis."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", slug or ""):
        return "Anzeige nicht gefunden.", 404
    yaml_path = _ad_yaml_path(slug)
    if not yaml_path.is_file():
        return "Anzeige nicht gefunden.", 404
    return send_file(
        yaml_path,
        mimetype="application/x-yaml",
        as_attachment=True,
        download_name=f"{slug}.yaml",
        max_age=0,
    )

@app.route("/republish/<slug>", methods=["POST"])
def republish_ad(slug):
    ad = _read_ad_yaml(slug)
    if not ad:
        flash("Anzeige nicht gefunden.", "err")
        return redirect(url_for("index"))

    state = _load_state()
    meta = state.setdefault("ads", {}).setdefault(slug, {})
    if not ad.get("active", True):
        _clear_republish_retry(meta)
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash("Die Anzeige ist pausiert und wurde nicht erneuert.", "warn")
        return redirect(url_for("index"))
    if not (meta.get("last_published") or ad.get("id")):
        _clear_republish_retry(meta)
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash("Die Anzeige ist nicht mehr online markiert. Erneuern wurde nicht gestartet.", "warn")
        return redirect(url_for("index"))
    account_id = _ad_account_id(slug, meta, state)
    _operation_begin_attempt(
        slug,
        "republish",
        "manual",
        title=str(ad.get("title") or slug),
        account_id=account_id,
    )

    # Erst den kompletten Erneuern-Vorgang reservieren, DANN die bestehende
    # Live-Anzeige anfassen. Ist der Slot belegt, bleibt sie online.
    if not _try_reserve_bot_slot():
        state = _load_state()
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        retry_at = _queue_republish_retry(state, slug, meta, "Bot-Slot ist gerade belegt")
        _save_state(state)
        _operation_wait(
            slug,
            "Bot ist belegt – Live-Anzeige bleibt online; neuer Versuch in 60 Sekunden.",
            retry_at,
            retry_mode="republish",
            old_live_deleted=False,
        )
        flash("Bot ist gerade beschäftigt. Die Live-Anzeige bleibt online; Erneuern wird automatisch in 1 Minute erneut versucht.", "info")
        return redirect(url_for("index"))

    try:
        _operation_update(
            slug,
            status="reserved",
            message="Bot ist frei – Erneuern wird gestartet.",
            account_id=account_id,
            account_name=_account_name(account_id, state),
        )
        ad = _read_ad_yaml(slug)
        state = _load_state()
        meta = state.setdefault("ads", {}).setdefault(slug, {})
        if not ad:
            _operation_failed(slug, "Anzeige wurde vor dem Erneuern nicht mehr gefunden.")
            flash("Anzeige nicht gefunden.", "err")
            return redirect(url_for("index"))

        account_id = _ad_account_id(slug, meta, state)
        _operation_update(
            slug,
            status="checking",
            message="Bot ist frei – 30-Tage-Limit wird geprüft.",
            account_id=account_id,
            account_name=_account_name(account_id, state),
        )
        ok_limit, count, limit_msg = _ensure_publish_capacity(account_id, state)
        cap_kind = _capacity_failure_kind(ok_limit, count, limit_msg)
        if cap_kind != "ok":
            if cap_kind == "technical":
                meta.pop("republish_postponed_until", None)
                retry_at = _queue_republish_retry(state, slug, meta, "30-Tage-Prüfung technisch nicht verfügbar")
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                _operation_wait(
                    slug,
                    "30-Tage-Prüfung technisch nicht verfügbar – Live-Anzeige bleibt online; neuer Versuch in 60 Sekunden.",
                    retry_at,
                    retry_mode="republish",
                    old_live_deleted=False,
                )
                flash("30-Tage-Prüfung war technisch nicht möglich. Die Live-Anzeige bleibt online; Erneuern wird in 1 Minute erneut versucht.", "warn")
                return redirect(url_for("index"))
            _clear_republish_retry(meta)
            meta.setdefault("history", []).append({"action": "Erneuern blockiert: " + limit_msg, "date": _now()})
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
            _operation_failed(slug, "Nicht erneuert; Live-Anzeige blieb online: " + limit_msg)
            flash("Nicht erneuert und nicht gelöscht: " + limit_msg, "warn")
            return redirect(url_for("index"))

        # Ohne sicher bekannte Live-ID darf Erneuern niemals blind eine zweite
        # Anzeige erzeugen. Vorher einmal die Live-Liste abgleichen.
        old_id = str(ad.get("id") or "").strip()
        if not old_id and meta.get("last_published"):
            _operation_update(slug, status="checking", message="Live-Verknüpfung wird vor dem Löschen geprüft …")
            try:
                _listings, items = _fetch_live_ads_raw(account_id)
                _reconcile_live_links(account_id, items)
                ad = _read_ad_yaml(slug) or ad
                old_id = str(ad.get("id") or "").strip()
            except Exception as exc:
                print(f"[republish] Live-ID-Abgleich für {slug} fehlgeschlagen: {exc}", flush=True)

        if not old_id:
            _clear_republish_retry(meta)
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
            _operation_failed(
                slug,
                "Erneuern gestoppt: Die bestehende Live-Anzeige konnte nicht eindeutig verknüpft werden. Es wurde nichts gelöscht und nichts neu veröffentlicht.",
            )
            flash("Erneuern gestoppt: Live-ID fehlt. Es wurde nichts gelöscht und keine zweite Anzeige erstellt.", "warn")
            return redirect(url_for("index"))

        _operation_update(slug, status="deleting", message="Alte Live-Anzeige wird gelöscht …")
        try:
            _create_backup(reason="vor-manuellem-repost-live-loeschen", slug=slug)
            _delete_remote_only(account_id, old_id)
            _clear_local_remote_id_only(slug)
            meta["last_published"] = None
            _mark_republish_delete_success(meta, old_id)
            meta.setdefault("history", []).append({"action": f"alte Live-ID {old_id} direkt gelöscht", "date": _now()})
            _operation_update(slug, old_live_deleted=True, message="Alte Live-Anzeige gelöscht – Neuveröffentlichung wird vorbereitet …")
        except Exception as exc:
            delete_error = str(exc) or exc.__class__.__name__
            meta.setdefault("history", []).append({"action": f"alte Live-ID {old_id} konnte nicht gelöscht werden: {delete_error}", "date": _now()})
            _clear_republish_retry(meta)
            state.setdefault("ads", {})[slug] = meta
            _save_state(state)
            _operation_failed(slug, "Löschen der alten Live-Anzeige nicht sicher bestätigt; kein automatischer zweiter Löschversuch.")
            _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': Löschen der alten Anzeige nicht sicher bestätigt. Es wurde kein weiterer Löschversuch gestartet.", click_url=PUBLIC_BASE_URL)
            flash("Alte Live-Anzeige konnte nicht sicher gelöscht werden. Es wurde kein weiterer Löschversuch gestartet.", "err")
            return redirect(url_for("index"))

        price_change = _prepare_republish_price_reduction(slug, meta)
        _operation_update(slug, status="publishing", message="Bot läuft – Anzeige wird neu veröffentlicht …")
        result = _run_bot_for_slug("publish", slug, ads="all", account_id=account_id, force_new=True, slot_reserved=True)
        if not result["ok"] and price_change:
            _restore_republish_price(slug, price_change["old_price"])

        if result["ok"]:
            meta["last_published"] = _now()
            meta["publish_count"] = meta.get("publish_count", 0) + 1
            meta["scheduled_publish_at"] = None
            meta.pop("republish_postponed_until", None)
            _clear_republish_retry(meta)
            _clear_publish_retry(meta)
            _clear_republish_transaction(meta)
            if price_change:
                _commit_price_reduction(meta, price_change)
                meta.setdefault("history", []).append({"action": f"Preis gesenkt: {_fmt_money(price_change['old_price'])} € → {_fmt_money(price_change['new_price'])} €", "date": _now()})
            else:
                _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
            _increment_activity_posted_count(account_id, 1, state)
            meta.setdefault("history", []).append({"action": f"neu eingestellt über {_account_name(account_id, state)}", "date": _now()})
            if result.get("remote_id"):
                _operation_success(slug, "Erfolgreich erneuert.")
            else:
                _operation_success(slug, "Erfolgreich erneuert; Live-ID-Verknüpfung wird noch nachgezogen.")
            _notify_primary("Kleinanzeigen: Anzeige veröffentlicht", f"'{ad.get('title') or slug}' wurde erneuert und remote bestätigt (ID {result.get('remote_id')}).", click_url=PUBLIC_BASE_URL)
            flash("Anzeige neu eingestellt!", "ok")
        elif _publish_result_requires_manual_review(result):
            _clear_republish_retry(meta)
            _clear_publish_retry(meta)
            meta.setdefault("history", []).append({"action": "Neuveröffentlichung nach Absenden nicht eindeutig bestätigt; kein automatischer weiterer Versuch wegen möglicher Doppelanzeige", "date": _now()})
            _operation_failed(slug, "Absenden wurde nicht eindeutig bestätigt. Es wurde kein weiterer Veröffentlichungsversuch gestartet, um eine Doppelanzeige zu verhindern.")
            _notify_primary("Kleinanzeigen: Veröffentlichung prüfen", f"'{ad.get('title') or slug}' wurde möglicherweise bereits veröffentlicht. Es wurde sicher kein zweiter Versuch gestartet.", click_url=PUBLIC_BASE_URL)
            flash("Die Anzeige könnte bereits online sein. Der Live-Status war nicht eindeutig bestätigbar; zur Sicherheit wurde kein zweiter Versuch gestartet.", "warn")
        elif result.get("safe_retry"):
            _clear_republish_retry(meta)
            # Alte Anzeige ist bereits weg: beim Retry nur veröffentlichen, nicht
            # ein zweites Mal den Erneuern-/Löschpfad ausführen.
            retry_at = _queue_publish_only_after_republish(state, slug, meta, "Neuveröffentlichung nach Erneuern konnte noch nicht starten")
            if not retry_at:
                _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                flash("Neu veröffentlichen nach Erneuern dauerhaft fehlgeschlagen. Diagnose prüfen.", "err")
                state.setdefault("ads", {})[slug] = meta
                _save_state(state)
                return redirect(url_for("index"))
            meta.setdefault("history", []).append({"action": "Alte Anzeige gelöscht; Neuveröffentlichung wird in 1 Minute erneut versucht", "date": _now()})
            _operation_wait(
                slug,
                "Alte Anzeige ist gelöscht; Bot/Login-Prüfung fehlgeschlagen – nur die Neuveröffentlichung wird in 60 Sekunden erneut versucht.",
                retry_at,
                retry_mode="publish_only",
                old_live_deleted=True,
            )
            flash("Alte Anzeige wurde gelöscht, der Bot konnte noch nicht sicher starten. Neuveröffentlichung erfolgt automatisch in 1 Minute erneut.", "warn")
        else:
            meta.setdefault("history", []).append({"action": "Fehler beim Republish", "date": _now()})
            retry_at = _queue_publish_only_after_republish(state, slug, meta, str(result.get("output") or "Publish fehlgeschlagen")[:240])
            if retry_at:
                _operation_wait(slug, "Alte Anzeige ist gelöscht; nur Neuveröffentlichung wird erneut versucht.", retry_at, retry_mode="publish_only", old_live_deleted=True)
                flash("Alte Anzeige gelöscht; nur die Neuveröffentlichung wird automatisch erneut versucht.", "warn")
            else:
                _operation_failed(slug, "Alte Live-Anzeige wurde gelöscht, Neuveröffentlichung nach begrenzten Publish-only-Versuchen fehlgeschlagen.")
                _notify_primary("Kleinanzeigen: Erneuern fehlgeschlagen", f"'{ad.get('title') or slug}': alte Anzeige gelöscht, Neuveröffentlichung nicht bestätigt. Bitte Diagnose prüfen.", click_url=PUBLIC_BASE_URL)
                flash("Fehler bei der Neuveröffentlichung. Diagnose prüfen.", "err")

        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        return redirect(url_for("index"))
    except Exception as exc:
        _operation_failed(slug, "Manager-Fehler beim Erneuern: " + str(exc))
        raise
    finally:
        _release_bot_slot()

@app.route("/publish-all", methods=["POST"])
def publish_all():
    # Kein globaler Bot-Publish mehr: jede Anzeige muss Account + 30-Tage-Limit einzeln passieren.
    scheduled_result = _publish_scheduled_due_ads(auto=False)
    republish_result = _auto_republish_due_ads(auto=False)
    published = int(scheduled_result.get("published") or 0)
    renewed = int(republish_result.get("renewed") or 0)
    postponed = int(scheduled_result.get("postponed") or 0) + int(republish_result.get("postponed") or 0)
    failed = int(scheduled_result.get("failed") or 0) + int(republish_result.get("failed") or 0)
    if not published and not renewed and not postponed and not failed:
        flash("Aktuell sind keine Anzeigen fällig.", "info")
    else:
        parts = []
        if renewed: parts.append(f"{renewed} erneuert")
        if published: parts.append(f"{published} erstmals veröffentlicht")
        if postponed: parts.append(f"{postponed} wegen Limit/Prüfung verschoben")
        if failed: parts.append(f"{failed} fehlgeschlagen")
        flash(" · ".join(parts) + ".", "ok" if not postponed and not failed else "warn")
    return redirect(url_for("index"))

@app.route("/bot-delete/<slug>", methods=["POST"])
def bot_delete_ad(slug):
    _create_backup(reason='vor-ka-loeschen', slug=slug)
    result = _run_bot_for_slug("delete", slug, ads="all")
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    meta.setdefault("history", []).append({"action": "von Kleinanzeigen geloescht", "date": _now()})
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    if result["ok"]:
        flash("Anzeige von Kleinanzeigen entfernt.", "ok")
    else:
        flash("Fehler: " + result["output"][:200], "err")
    return redirect(url_for("index"))

@app.route("/deactivate/<slug>", methods=["POST"])
def deactivate_ad(slug):
    ad = _read_ad_yaml(slug)
    if ad:
        ad["active"] = False
        _ad_yaml_path(slug).write_text(yaml.dump(ad, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
        state = _load_state()
        meta = state.get("ads", {}).get(slug, {})
        meta.setdefault("history", []).append({"action": "deaktiviert", "date": _now()})
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash("Anzeige deaktiviert.", "ok")
    return redirect(url_for("index"))

@app.route("/activate/<slug>", methods=["POST"])
def activate_ad(slug):
    ad = _read_ad_yaml(slug)
    if ad:
        ad["active"] = True
        _ad_yaml_path(slug).write_text(yaml.dump(ad, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
        state = _load_state()
        meta = state.get("ads", {}).get(slug, {})
        meta.setdefault("history", []).append({"action": "aktiviert", "date": _now()})
        state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash("Anzeige aktiviert.", "ok")
    return redirect(url_for("index"))

@app.route("/delete-local/<slug>", methods=["POST"])
def delete_local(slug):
    _create_backup(reason='vor-lokal-loeschen', slug=slug)
    p = _ad_yaml_path(slug)
    if p.exists():
        p.unlink()
    img_dir = _ad_images_dir(slug)
    if img_dir.is_dir():
        shutil.rmtree(img_dir)
    state = _load_state()
    state.get("ads", {}).pop(slug, None)
    _save_state(state)
    flash("Anzeige geloescht.", "ok")
    return redirect(url_for("index"))

# -- Routes: Logs --

@app.route("/logs")
def logs_view():
    # Alte Links bleiben kompatibel; Logs sind jetzt Teil der Einstellungen.
    return redirect(url_for("settings_form", _anchor="logs"))

@app.route("/bot-status")
def bot_status():
    return jsonify(_last_log)


@app.route("/operation-status")
def operation_status():
    return jsonify(_operation_status_payload())


@app.route("/operation-cancel/<slug>", methods=["POST"])
def cancel_operation(slug):
    rec = _operation_get(slug)
    if not rec:
        flash("Für diese Anzeige gibt es keinen wartenden Vorgang.", "info")
        return redirect(request.referrer or url_for("index"))
    if rec.get("status") != "waiting":
        flash("Der Vorgang läuft bereits oder ist beendet und kann nicht mehr sicher abgebrochen werden.", "warn")
        return redirect(request.referrer or url_for("index"))

    # Retry-Felder atomar aus dem aktuellen State entfernen, damit ein alter
    # Browser-/Scheduler-Snapshot den gerade abgebrochenen Vorgang nicht weiterführt.
    with _state_lock:
        latest = json.loads(APP_STATE.read_text("utf-8")) if APP_STATE.exists() else {"ads": {}}
        meta = latest.setdefault("ads", {}).setdefault(slug, {})
        retry_mode = str(rec.get("retry_mode") or "")
        if rec.get("action") == "republish" and retry_mode != "publish_only":
            _clear_republish_retry(meta)
        else:
            _clear_publish_retry(meta)
        latest.setdefault("ads", {})[slug] = meta
        _save_state(latest)

    old_deleted = bool(rec.get("old_live_deleted"))
    _operation_cancelled(
        slug,
        "Vorgang abgebrochen. Die alte Live-Anzeige war bereits gelöscht; die Anzeige bleibt unveröffentlicht."
        if old_deleted
        else "Vorgang abgebrochen. Es wurden keine weiteren automatischen Versuche gestartet.",
    )
    if old_deleted:
        flash("Vorgang abgebrochen. Achtung: Die alte Live-Anzeige war bereits gelöscht; die Anzeige bleibt unveröffentlicht.", "warn")
    else:
        flash("Wartenden Vorgang abgebrochen.", "ok")
    return redirect(request.referrer or url_for("index"))


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": APP_VERSION, "feature": APP_FEATURE})


def _edited_image_signature_matches(data, suffix):
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


@app.route("/images/<slug>/<filename>/edit", methods=["POST"])
def edit_image_file(slug, filename):
    if slug != Path(slug).name or filename != Path(filename).name:
        return jsonify({"ok": False, "error": "Ungültiger Bildpfad."}), 400
    if not _ad_yaml_path(slug).exists():
        return jsonify({"ok": False, "error": "Anzeige nicht gefunden."}), 404

    target = _ad_images_dir(slug) / filename
    if not target.is_file():
        return jsonify({"ok": False, "error": "Bild nicht gefunden."}), 404

    suffix = target.suffix.lower()
    if suffix == ".gif":
        return jsonify({"ok": False, "error": "Animierte GIF-Bilder können nicht zugeschnitten oder gedreht werden."}), 400
    if suffix not in EDITABLE_IMAGE_EXTENSIONS:
        return jsonify({"ok": False, "error": "Dieses Bildformat kann nicht bearbeitet werden."}), 400
    if request.content_length and request.content_length > EDITED_IMAGE_MAX_BYTES + 1024 * 1024:
        return jsonify({"ok": False, "error": "Das bearbeitete Bild ist zu groß."}), 413

    uploaded = request.files.get("image")
    if not uploaded:
        return jsonify({"ok": False, "error": "Es wurde kein bearbeitetes Bild übertragen."}), 400
    data = uploaded.read(EDITED_IMAGE_MAX_BYTES + 1)
    if not data or len(data) > EDITED_IMAGE_MAX_BYTES:
        return jsonify({"ok": False, "error": "Das bearbeitete Bild ist leer oder zu groß."}), 413
    if not _edited_image_signature_matches(data, suffix):
        return jsonify({"ok": False, "error": "Bildformat und Dateiname stimmen nicht überein."}), 400

    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.edit")
    try:
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    return jsonify({
        "ok": True,
        "image_url": url_for("serve_image", slug=slug, filename=filename, v=int(time.time())),
    })


@app.route("/images/<slug>/<filename>")
def serve_image(slug, filename):
    return send_from_directory(str(_ad_images_dir(slug)), filename)

# -- Main --

if __name__ == "__main__":
    for d in [DATA_DIR, ACCOUNTS_DIR, ADS_DIR, IMAGES_DIR, LOGS_DIR, BACKUP_DIR, IMPORT_DIR, IMPORT_ERROR_DIR, API_CACHE_DIR, IMAGE_PROXY_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    _prune_old_backups()
    _migrate_accounts()
    _migrate_price_reduction_settings()
    _migrate_republish_transactions()
    _repair_false_publish_markers_from_recent_logs()
    _repair_technical_day_postponements()
    _repair_recent_safe_orphaned_republish()
    threading.Thread(target=_scheduled_publish_loop, daemon=True).start()
    threading.Thread(target=_media_import_watch_loop, daemon=True).start()
    threading.Thread(target=_automatic_import_loop, daemon=True).start()
    threading.Thread(target=_message_monitor_loop, daemon=True).start()
    threading.Thread(target=_live_ads_monitor_loop, daemon=True).start()
    threading.Thread(target=_vinted_sold_cleanup_loop, daemon=True).start()
    if GOOGLE_DRIVE_IMPORT_ENABLED:
        threading.Thread(target=_google_drive_import_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
