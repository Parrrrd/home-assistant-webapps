from __future__ import annotations

import copy
import ctypes
import json
import os
import re
import shutil
import signal
import select
import struct
import subprocess
import threading
import time
import uuid
import tempfile
import zipfile
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

# v1.5.24.10-drive-cleanup

import yaml
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify, flash,
    send_file, send_from_directory,
)

APP_TITLE = "WebApp Sync Manager"
HOME_SCREEN_TITLE = "WebApp Sync Manager"
PORT = int(os.environ.get("PORT", "8155"))
DATA_DIR = Path(os.environ.get("WEBAPP_DATA_DIR", "/data"))
ADS_DIR = DATA_DIR / "ads"
IMAGES_DIR = DATA_DIR / "images"
LOGS_DIR = DATA_DIR / "logs"
BOT_CONFIG = DATA_DIR / "bot-config.yaml"
APP_STATE = DATA_DIR / "app-state.json"
SHARE_DIR = Path(os.environ.get("WEBAPP_SHARE_DIR", "/share/Webapp"))
DIAGNOSTICS_DIR = SHARE_DIR / "debug"
BACKUP_DIR = SHARE_DIR / "Backup"
MEDIA_DIR = Path(os.environ.get("WEBAPP_MEDIA_DIR", "/media"))
IMPORT_DIR = MEDIA_DIR / "Import" / "Webapp"
IMPORT_ERROR_DIR = IMPORT_DIR / "Fehler"
IMPORT_EXTENSION = ".kaanzeige"
IMPORT_INTERVAL_SECONDS = int(os.environ.get("WEBAPP_IMPORT_INTERVAL_SECONDS", "3600"))
GOOGLE_DRIVE_IMPORT_ENABLED = os.environ.get("WEBAPP_GOOGLE_DRIVE_IMPORT_ENABLED", "false").lower() == "true"
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("WEBAPP_GOOGLE_DRIVE_FOLDER_ID", "").strip()
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE = Path(os.environ.get("WEBAPP_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", "/share/Webapp/google-drive-service-account.json"))
GOOGLE_DRIVE_POLL_SECONDS = max(5, int(os.environ.get("WEBAPP_GOOGLE_DRIVE_POLL_SECONDS", "5")))
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
IMPORT_MAX_FILES = 100
IMPORT_MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
IMPORT_MAX_IMAGES = 20
IMPORT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EDITABLE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EDITED_IMAGE_MAX_BYTES = 60 * 1024 * 1024
BACKUP_RETENTION_DAYS = 7
APP_VERSION = "1.5.24.6"
APP_FEATURE = "media-import-watcher-google-drive-transport-push-save-publish-yaml-staging-diagnostics-image-editor-workflow-comfort-independent-price-reduction"

REPUBLISH_INTERVAL = int(os.environ.get("REPUBLISH_INTERVAL", "3"))
DEFAULT_PRICE_REDUCTION_DAYS = int(os.environ.get("WEBAPP_PRICE_REDUCTION_DAYS", "14"))
AUTO_REPUBLISH = os.environ.get("AUTO_REPUBLISH", "false").lower() == "true"
APP_TZ = ZoneInfo(os.environ.get("WEBAPP_TIMEZONE", "Europe/Berlin"))
REPOST_LIMIT_LAST_30_DAYS = int(os.environ.get("WEBAPP_REPOST_LIMIT_LAST_30_DAYS", "100"))
ACTIVITY_AUTO_REFRESH_HOUR = int(os.environ.get("WEBAPP_ACTIVITY_AUTO_REFRESH_HOUR", "0"))
ACTIVITY_AUTO_REFRESH_MINUTE = int(os.environ.get("WEBAPP_ACTIVITY_AUTO_REFRESH_MINUTE", "30"))
ACTIVITY_RETRY_SECONDS = int(os.environ.get("WEBAPP_ACTIVITY_RETRY_SECONDS", "300"))
Hauptprofil_NOTIFY_SERVICE = os.environ.get("WEBAPP_NOTIFY_SERVICE", "").strip()

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
# oder an Webapp uebergeben; sie dienen nur als Richtwert beim Bearbeiten.
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

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "ka-mgr-" + str(uuid.uuid4())[:8]

# -- Helpers --

def _now():
    return datetime.now(timezone.utc).isoformat()

def _now_local():
    return datetime.now(APP_TZ).strftime("%d.%m.%Y %H:%M")


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
        or ad_data.get("created_on_webapp")
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

        for single in ['bot-config.yaml', 'app-state.json']:
            src_file = data_root / single
            if src_file.exists():
                shutil.copy2(src_file, DATA_DIR / single)

        for folder_name in ['ads', 'images', 'logs']:
            src_folder = data_root / folder_name
            dst_folder = DATA_DIR / folder_name
            if src_folder.exists():
                if dst_folder.exists():
                    shutil.rmtree(dst_folder)
                shutil.copytree(src_folder, dst_folder)
            else:
                dst_folder.mkdir(parents=True, exist_ok=True)
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
    if APP_STATE.exists():
        return json.loads(APP_STATE.read_text("utf-8"))
    return {"ads": {}}

def _save_state(state):
    APP_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")

def _get_account_activity():
    state = _load_state()
    return state.get("account_activity", {})

def _save_account_activity(data):
    state = _load_state()
    state["account_activity"] = data
    _save_state(state)


def _activity_updated_today(activity=None):
    activity = activity if activity is not None else _get_account_activity()
    return _iso_to_local_date(activity.get("updated_at")) == _today_local_date()


def _posted_last_30_count(activity=None):
    activity = activity if activity is not None else _get_account_activity()
    try:
        return int(activity.get("posted_last_30_days"))
    except Exception:
        return None


def _refresh_account_activity_until_today(max_attempts=4, delay_seconds=2):
    last_msg = ""
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        ok, result = _fetch_account_activity()
        if ok:
            _save_account_activity(result)
            if _activity_updated_today(result):
                return True, f"Aktivitaet aktualisiert. Versuch {attempt}.", result
            last_msg = "Aktivitaet gelesen, aber kein heutiger Stand erkannt."
        else:
            last_msg = str(result)
        if attempt < max_attempts:
            time.sleep(max(0, delay_seconds))
    return False, last_msg or "Aktivitaet konnte nicht aktualisiert werden.", _get_account_activity()


def _auto_activity_refresh_due():
    """Nach 00:30 Uhr automatisch solange retryen, bis der heutige Stand gespeichert ist."""
    if _last_log.get("running") or _vnc_running():
        return
    now_local = _local_datetime()
    today = now_local.date().isoformat()
    if (now_local.hour, now_local.minute) < (ACTIVITY_AUTO_REFRESH_HOUR, ACTIVITY_AUTO_REFRESH_MINUTE):
        return

    state = _load_state()
    auto_state = state.setdefault("activity_auto_refresh", {})
    activity = state.get("account_activity", {})
    if auto_state.get("success_date") == today and _activity_updated_today(activity):
        return

    last_attempt_dt = _iso_dt(auto_state.get("last_attempt_at"))
    if last_attempt_dt and (datetime.now(timezone.utc) - last_attempt_dt).total_seconds() < ACTIVITY_RETRY_SECONDS:
        return

    auto_state["last_attempt_at"] = _now()
    ok, result = _fetch_account_activity()
    if ok:
        state["account_activity"] = result
        if _activity_updated_today(result):
            auto_state["success_date"] = today
            auto_state["last_error"] = ""
        else:
            auto_state["last_error"] = "Kein heutiger Stand erkannt."
    else:
        auto_state["last_error"] = str(result)
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


def _Hauptprofil_notify_candidates():
    """Priorisierte Ziele: konfiguriert -> Hauptprofil+iPhone -> Hauptprofil -> iPhone."""
    available = _available_mobile_notify_services()
    candidates = []

    configured = (Hauptprofil_NOTIFY_SERVICE or "").strip()
    if configured:
        if not configured.startswith("notify."):
            configured = "notify." + configured
        candidates.append(configured)

    def add_matches(predicate):
        for service in available:
            if predicate(service.lower()) and service not in candidates:
                candidates.append(service)

    add_matches(lambda s: "Hauptprofil" in s and "iphone" in s)
    add_matches(lambda s: "Hauptprofil" in s)
    add_matches(lambda s: "iphone" in s)

    return candidates, available


def _call_notify_service(service, title, message):
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
    payload = _json.dumps({"title": title, "message": message}).encode("utf-8")
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


def _notify_Hauptprofil(title, message):
    """Sendet genau eine Benachrichtigung an Hauptprofils iPhone.

    Falls kein passender Hauptprofil/iPhone-Dienst zuverlässig ermittelt werden
    kann, wird als Fallback an alle vorhandenen mobile_app-Notify-Dienste
    gesendet. So geht die Meldung nicht verloren, wenn ein Gerätename in
    Home Assistant anders lautet.
    """
    try:
        candidates, available = _Hauptprofil_notify_candidates()
        errors = []

        # Zuerst nur die sinnvollsten Hauptprofil-/iPhone-Kandidaten probieren.
        for service in candidates:
            ok, status = _call_notify_service(service, title, message)
            if ok:
                print(f"[notify] erfolgreich: {status}", flush=True)
                return True, status
            errors.append(status)

        # Fallback/Broadcast: alle mobile_app-Dienste genau einmal probieren.
        delivered = []
        for service in available:
            if service in candidates:
                continue
            ok, status = _call_notify_service(service, title, message)
            if ok:
                delivered.append(status)
            else:
                errors.append(status)

        if delivered:
            status = "Broadcast erfolgreich: " + " | ".join(delivered)
            print(f"[notify] {status}", flush=True)
            return True, status

        detail = " | ".join(errors[-10:]) if errors else "Keine mobile_app Notify-Dienste gefunden"
        print(f"[notify] fehlgeschlagen: {detail}", flush=True)
        return False, detail

    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        print(f"[notify] Ausnahme: {detail}", flush=True)
        return False, detail


def _ensure_republish_activity_count():
    activity = _get_account_activity()
    if not _activity_updated_today(activity) or _posted_last_30_count(activity) is None:
        ok, _msg, activity = _refresh_account_activity_until_today(max_attempts=4, delay_seconds=2)
        if not ok:
            return False, None, "Aktivitaet konnte nicht aktuell gelesen werden."
    count = _posted_last_30_count(activity)
    if count is None:
        return False, None, "Anzeigenzahl der letzten 30 Tage nicht erkannt."
    if count >= REPOST_LIMIT_LAST_30_DAYS:
        return False, count, f"Limit erreicht: {count}/{REPOST_LIMIT_LAST_30_DAYS} Anzeigen in den letzten 30 Tagen."
    return True, count, f"{count}/{REPOST_LIMIT_LAST_30_DAYS}"


def _postpone_republish(state, slug, meta, reason):
    until = datetime.now(timezone.utc) + timedelta(days=1)
    meta["republish_postponed_until"] = until.isoformat()
    meta.setdefault("history", []).append({"action": "Erneuern um 1 Tag verschoben: " + reason, "date": _now()})
    state.setdefault("ads", {})[slug] = meta


def _increment_activity_posted_count(delta=1):
    state = _load_state()
    activity = state.get("account_activity") or {}
    count = _posted_last_30_count(activity)
    if count is not None:
        activity["posted_last_30_days"] = count + int(delta)
        activity["updated_at"] = activity.get("updated_at") or _now()
        state["account_activity"] = activity
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
    existing_cfg = _load_bot_config()
    existing_ui = existing_cfg.get("ui", {}) if isinstance(existing_cfg.get("ui", {}), dict) else {}
    shipping_prices = _normalize_shipping_prices(settings.get("shipping_prices") or existing_ui.get("shipping_prices") or {})
    cfg = {
        "login": {
            "username": settings.get("email", ""),
            "password": settings.get("password", ""),
        },
        "browser": {
            "binary_location": os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser"),
            "arguments": [
                "--no-sandbox",
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--window-size=1280,1024",
            ],
            "use_private_window": False,
        },
        "ad_defaults": {
            "active": True,
            "type": "OFFER",
            "republication_interval": settings.get("republish_days", REPUBLISH_INTERVAL),
            "contact": {"name": settings.get("contact_name", "")},
            "location": settings.get("default_location", ""),
            "shipping_type": "SHIPPING",
            "shipping_options": list(DEFAULT_SHIPPING_OPTIONS),
        },
        "ad_files": ["ads/*.yaml"],
        "ui": {
            "shipping_prices": shipping_prices,
        },
    }
    _save_bot_config(cfg)

def _get_settings():
    cfg = _load_bot_config()
    login = cfg.get("login", {})
    defaults = cfg.get("ad_defaults", {})
    contact = defaults.get("contact", {})
    ui = cfg.get("ui", {}) if isinstance(cfg.get("ui", {}), dict) else {}
    return {
        "email": login.get("username", ""),
        "password": login.get("password", ""),
        "contact_name": contact.get("name", ""),
        "default_location": defaults.get("location", ""),
        "republish_days": defaults.get("republication_interval", REPUBLISH_INTERVAL),
        "price_reduction_days": DEFAULT_PRICE_REDUCTION_DAYS,
        "configured": bool(login.get("username")),
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
    for managed_key in ("id", "created_at", "updated_at", "created_on_webapp"):
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


# -- Anzeigen-Import aus /media/Import/Webapp --

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


# v1.5.24.10-drive-cleanup: Google-Drive-Quelle wird nach erfolgreichem Import bereinigt.
# Die dauerhafte processed-ID-Logik aus v1.5.24.9 bleibt unverändert.

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



# -- Ereignisgesteuerter Import aus /media/Import/Webapp --
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



DRIVE_PROCESSED_IDS_FILE = Path("/share/Webapp/google-drive-processed-ids.json")

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
    notify_ok, notify_status = _notify_Hauptprofil(
        "Webapp",
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
                    last_safety_scan = time.monotonic()

        except Exception as exc:
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
        "path": "media/Import/Webapp",
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
    """Entfernt die Quelldatei nach erfolgreichem Import aus dem überwachten Ordner.

    Zuerst wird ein echtes files.delete versucht. Dateien, die über ChatGPT bzw.
    Hauptprofils Google-Konto hochgeladen wurden, gehören aber Hauptprofil. Ein Service
    Account mit Editor-Recht darf solche Dateien in My Drive nicht endgültig
    löschen. In diesem Fall wird die Datei aus dem überwachten Importordner
    entfernt. Dadurch wird sie nicht erneut erkannt. Die endgültige Löschung
    kann anschließend durch Hauptprofils Google-Drive-Verbindung erfolgen.
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

    # Fallback für fremde Eigentümerschaft: aus dem überwachten Ordner entfernen.
    try:
        response = session.patch(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={
                "removeParents": GOOGLE_DRIVE_FOLDER_ID,
                "supportsAllDrives": "true",
                "fields": "id,parents",
            },
            json={},
            timeout=30,
        )
        if response.status_code in (200, 201):
            return True, "removed_from_folder", delete_error
        fallback_error = f"HTTP {response.status_code}: {response.text[:300]}"
    except Exception as exc:
        fallback_error = str(exc)

    return False, "", (
        "Drive-Quelle konnte weder gelöscht noch aus dem Importordner entfernt werden. "
        f"Delete: {delete_error or 'unbekannt'}; RemoveParents: {fallback_error or 'unbekannt'}"
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
_import_lock = threading.Lock()
_last_log = {"output": "", "running": False, "timestamp": ""}

def _run_bot(command, ads=None, config_path=None, log_preamble=""):
    global _last_log
    if _last_log.get("running"):
        return {"ok": False, "output": "Bot laeuft bereits."}
    with _bot_lock:
        _last_log = {"output": "", "running": True, "timestamp": _now_local()}
        effective_config = Path(config_path) if config_path else BOT_CONFIG
        cmd = ["python3", "-m", "webapp_bot",
               "--config", str(effective_config),
               "--workspace-mode=portable",
               command]
        if ads:
            cmd.append("--ads=" + ads)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(DATA_DIR))
            raw_output = (result.stdout + "\n" + result.stderr).strip()
            output = ((log_preamble.rstrip() + "\n\n") if log_preamble else "") + raw_output
            ok = result.returncode == 0
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            (LOGS_DIR / (ts + "_" + command + ".log")).write_text(
                "Command: " + " ".join(cmd) + "\nReturn code: " + str(result.returncode) +
                (("\n\n--- PUBLISH IMAGE ORDER ---\n" + log_preamble.rstrip()) if log_preamble else "") +
                "\n\n--- STDOUT ---\n" + result.stdout + "\n\n--- STDERR ---\n" + result.stderr, "utf-8")
            _last_log = {"output": output, "running": False, "ok": ok, "command": command, "timestamp": _now_local()}
            return {"ok": ok, "output": output}
        except subprocess.TimeoutExpired:
            msg = "Bot-Timeout (>10 Min)."
            _last_log = {"output": msg, "running": False, "ok": False, "timestamp": _now_local()}
            return {"ok": False, "output": msg}
        except Exception as e:
            msg = "Fehler: " + str(e)
            _last_log = {"output": msg, "running": False, "ok": False, "timestamp": _now_local()}
            return {"ok": False, "output": msg}


def _make_single_ad_config(slug):
    ad_path = _ad_yaml_path(slug)
    if not ad_path.exists():
        raise FileNotFoundError(f"Anzeige nicht gefunden: {slug}")
    cfg = _enable_run_diagnostics(_load_bot_config())
    try:
        rel_ad_path = ad_path.relative_to(DATA_DIR)
        pattern = rel_ad_path.as_posix()
    except ValueError:
        pattern = str(ad_path)
    cfg["ad_files"] = [pattern]
    # Wichtig: Die temporäre Config muss im gleichen Workspace wie /data liegen.
    # Bei workspace-mode=portable bestimmt der Config-Pfad den Workspace.
    # Liegt die Config in /data/.tmp, sucht der Bot relativ zu /data/.tmp und
    # findet ads/*.yaml nicht mehr. Deshalb direkt in /data anlegen.
    fd, tmp_name = tempfile.mkstemp(prefix=f".single-ad-{slug}-", suffix=".yaml", dir=str(DATA_DIR))
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
    return tmp_path


def _write_temp_bot_config_for_ad(slug, ad_path):
    cfg = _enable_run_diagnostics(_load_bot_config())
    try:
        pattern = Path(ad_path).relative_to(DATA_DIR).as_posix()
    except ValueError:
        pattern = str(ad_path)
    cfg["ad_files"] = [pattern]
    fd, tmp_name = tempfile.mkstemp(prefix=f".single-ad-{slug}-", suffix=".yaml", dir=str(DATA_DIR))
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
    return tmp_path


def _prepare_publish_image_order_staging(slug):
    """
    Erstellt für den Bot eine temporäre Anzeige mit eindeutig nummerierten Bildern.

    Warum: Die Bearbeitungsmaske speichert die Reihenfolge zwar in der YAML,
    beim Veröffentlichen soll die Reihenfolge aber zusätzlich hart erzwungen
    werden. Deshalb bekommt der Bot temporär nur noch Dateien wie 01.jpg,
    02.jpg, 03.jpg ... in exakt der gespeicherten Reihenfolge.
    """
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
    if staged_names:
        staged_ad["images"] = [f"../images/{slug}/{name}" for name in staged_names]
    else:
        staged_ad.pop("images", None)
        order_log.append("Keine Bilder gefunden.")

    staged_ad_path = stage_ads_dir / f"{slug}.yaml"
    staged_ad_path.write_text(yaml.dump(staged_ad, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
    cfg_path = _write_temp_bot_config_for_ad(slug, staged_ad_path)

    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_id = f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    source_path = DIAGNOSTICS_DIR / f"{snapshot_id}.source.yaml"
    staged_path = DIAGNOSTICS_DIR / f"{snapshot_id}.staged.yaml"
    bot_config_path = DIAGNOSTICS_DIR / f"{snapshot_id}.bot-config.yaml"
    source_path.write_text(yaml.dump(ad, allow_unicode=True, default_flow_style=False, sort_keys=False), "utf-8")
    shutil.copy2(staged_ad_path, staged_path)
    shutil.copy2(cfg_path, bot_config_path)

    preamble = "Bildreihenfolge beim Veröffentlichen wurde fixiert:\n" + "\n".join(order_log)
    preamble += f"\nDiagnose-Dateien: {source_path.name}, {staged_path.name}, {bot_config_path.name}"
    return cfg_path, staging_root, preamble


def _run_bot_for_slug(command, slug, ads="all"):
    staging_root = None
    log_preamble = ""
    if command == "publish":
        cfg_path, staging_root, log_preamble = _prepare_publish_image_order_staging(slug)
    else:
        cfg_path = _make_single_ad_config(slug)
    try:
        return _run_bot(command, ads=ads, config_path=cfg_path, log_preamble=log_preamble)
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
        if ad.get("active", True) and not meta.get("last_published") and scheduled_dt and scheduled_dt <= now_utc:
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
        if postponed_dt and postponed_dt > now_utc:
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
        if republish_interval > 0 and age >= republish_interval:
            due.append(slug)
    return due


def _publish_scheduled_due_ads(auto=False):
    if _last_log.get("running"):
        return {"published": 0, "failed": 0, "processed": []}
    state = _load_state()
    now_utc = datetime.now(timezone.utc)
    scheduled_slugs = _collect_due_scheduled_slugs(state=state, now_utc=now_utc)
    published_count = 0
    failed_count = 0
    processed = []
    for slug in scheduled_slugs:
        result = _run_bot_for_slug("publish", slug, ads="all")
        meta = state.get("ads", {}).get(slug, {})
        processed.append({"slug": slug, "ok": bool(result.get("ok")), "output": result.get("output", "")})
        if result.get("ok"):
            meta["last_published"] = _now()
            meta["publish_count"] = meta.get("publish_count", 0) + 1
            meta["scheduled_publish_at"] = None
            _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
            action = "automatisch planmaessig veroeffentlicht" if auto else "planmaessig veroeffentlicht"
            meta.setdefault("history", []).append({"action": action, "date": _now()})
            published_count += 1
        else:
            action = "Fehler bei automatischer geplanter Veroeffentlichung" if auto else "Fehler bei geplanter Veroeffentlichung"
            meta.setdefault("history", []).append({"action": action, "date": _now()})
            failed_count += 1
        state.setdefault("ads", {})[slug] = meta
    if scheduled_slugs:
        _save_state(state)
    return {"published": published_count, "failed": failed_count, "processed": processed}


def _auto_republish_due_ads(auto=True):
    if _last_log.get("running"):
        return {"renewed": 0, "failed": 0, "postponed": 0, "processed": []}
    state = _load_state()
    now_utc = datetime.now(timezone.utc)
    due_slugs = _collect_due_republish_slugs(state=state, now_utc=now_utc)
    renewed = 0
    failed = 0
    postponed = 0
    processed = []

    limit_ok, activity_count, limit_msg = _ensure_republish_activity_count() if due_slugs else (True, None, "")
    local_count = activity_count

    for slug in due_slugs:
        meta = state.get("ads", {}).get(slug, {})
        if not limit_ok or local_count is None or local_count >= REPOST_LIMIT_LAST_30_DAYS:
            reason = limit_msg if local_count is None else f"{local_count}/{REPOST_LIMIT_LAST_30_DAYS} Anzeigen in den letzten 30 Tagen"
            _postpone_republish(state, slug, meta, reason)
            postponed += 1
            processed.append({"slug": slug, "ok": False, "postponed": True, "output": reason})
            title = (_read_ad_yaml(slug) or {}).get("title", slug)
            _notify_Hauptprofil(
                "Webapp: Erneuern verschoben",
                f"'{title}' wurde nicht neu eingestellt, weil {reason}. Neuer Versuch morgen.",
            )
            continue

        delete_result = _run_bot_for_slug("delete", slug, ads="all")
        price_change = None
        if delete_result.get("ok"):
            price_change = _prepare_republish_price_reduction(slug, meta, now_utc=now_utc)
            result = _run_bot_for_slug("publish", slug, ads="all")
            if not result.get("ok") and price_change:
                _restore_republish_price(slug, price_change["old_price"])
        else:
            result = delete_result
        processed.append({"slug": slug, "ok": bool(result.get("ok")), "output": result.get("output", "")})
        if result.get("ok"):
            meta["last_published"] = _now()
            meta["publish_count"] = meta.get("publish_count", 0) + 1
            meta.pop("republish_postponed_until", None)
            if price_change:
                _commit_price_reduction(meta, price_change)
                meta.setdefault("history", []).append({"action": f"Preis gesenkt: {_fmt_money(price_change['old_price'])} € → {_fmt_money(price_change['new_price'])} €", "date": _now()})
            else:
                _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta, now_utc=now_utc)
            meta.setdefault("history", []).append({"action": "automatisch neu eingestellt" if auto else "neu eingestellt", "date": _now()})
            renewed += 1
            if local_count is not None:
                local_count += 1
                state.setdefault("account_activity", {})["posted_last_30_days"] = local_count
                state.setdefault("account_activity", {})["updated_at"] = state.setdefault("account_activity", {}).get("updated_at") or _now()
        else:
            meta.setdefault("history", []).append({"action": "Fehler bei automatischem Erneuern" if auto else "Fehler beim Erneuern", "date": _now()})
            failed += 1
        state.setdefault("ads", {})[slug] = meta
    if due_slugs:
        _save_state(state)
    return {"renewed": renewed, "failed": failed, "postponed": postponed, "processed": processed}

def _scheduled_publish_loop():
    while True:
        try:
            _auto_activity_refresh_due()
            _publish_scheduled_due_ads(auto=True)
            _auto_republish_due_ads(auto=True)
        except Exception:
            pass
        time.sleep(30)

# -- noVNC Manual Login --

_vnc_procs = []

def _start_vnc_login():
    global _vnc_procs
    _stop_vnc()
    settings = _get_settings()
    if not settings.get("email"):
        return False, "Bitte zuerst Login-Daten in Einstellungen eingeben."
    try:
        xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-ac"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(xvfb)
        time.sleep(1)
        vnc = subprocess.Popen(["x11vnc", "-display", ":99", "-forever", "-nopw", "-shared", "-rfbport", "5900"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(vnc)
        time.sleep(0.5)
        novnc = subprocess.Popen(["/opt/noVNC/utils/novnc_proxy", "--vnc", "localhost:5900", "--listen", "6080"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(novnc)
        time.sleep(1)
        chrome = subprocess.Popen([
            os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser"),
            "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            "--window-size=1280,1024",
            "--user-data-dir=" + str(DATA_DIR / ".temp" / "browser-profile"),
            "https://www.webapp.de/m-einloggen.html",
        ], env={**os.environ, "DISPLAY": ":99"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _vnc_procs.append(chrome)
        return True, "noVNC gestartet."
    except Exception as e:
        _stop_vnc()
        return False, "Fehler: " + str(e)

def _stop_vnc():
    global _vnc_procs
    for p in _vnc_procs:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    _vnc_procs = []

def _vnc_running():
    return any(p.poll() is None for p in _vnc_procs)

def _fetch_account_activity():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
    except Exception as e:
        return False, "Selenium nicht verfuegbar: " + str(e)

    profile_dir = DATA_DIR / ".temp" / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    urls = [
        "https://www.webapp.de/m-einstellungen.html",
        "https://www.webapp.de/m-mein-konto.html",
        "https://www.webapp.de/m-meine-anzeigen.html",
    ]

    with _bot_lock:
        driver = None
        try:
            options = Options()
            options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/chromium-browser")
            options.add_argument("--no-sandbox")
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--window-size=1280,1024")
            options.add_argument(f"--user-data-dir={profile_dir}")
            service = Service(os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
            driver = webdriver.Chrome(service=service, options=options)
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
            return False, "Aktivitaet konnte nicht gelesen werden. Webapp-Seite eventuell geaendert."
        except Exception as e:
            return False, "Aktivitaet konnte nicht geladen werden: " + str(e)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

# -- Template Helpers --

@app.before_request
def _daily_backup_hook():
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
    for key in ("id", "created_on_webapp", "updated_at", "created_at"):
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
    state.setdefault("ads", {})[new_slug] = {
        "created_at": _now(),
        "last_published": None,
        "publish_count": 0,
        "scheduled_publish_at": None,
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
        if not ad.get("id") and not meta.get("last_published"):
            count += 1
    return count


def _index_return_context(values, prefix=""):
    status_filter = str(values.get(prefix + "status", "all") or "all").strip().lower()
    if status_filter not in {"all", "online", "planned", "unpublished"}:
        status_filter = "all"

    sort_by = str(values.get(prefix + "sort", "next_due") or "next_due").strip().lower()
    if sort_by not in {"default", "newest", "oldest", "title", "no_id", "due", "next_due"}:
        sort_by = "next_due"

    folder_filter = str(values.get(prefix + "folder", "all") or "all").strip()
    folders = _all_folders()
    if folder_filter not in {"all", "__none__"} and folder_filter not in folders:
        folder_filter = "all"

    search_query = str(values.get(prefix + "q", "") or "").strip()[:300]
    return {
        "status": status_filter,
        "q": search_query,
        "sort": sort_by,
        "folder": folder_filter,
    }


def _index_return_url(values, prefix=""):
    return url_for("index", **_index_return_context(values, prefix=prefix))


@app.route("/")
def index():
    state = _load_state()
    ads_meta = state.get("ads", {})
    status_filter = request.args.get("status", "all").strip().lower()
    if status_filter not in {"all", "online", "planned", "unpublished"}:
        status_filter = "all"
    search_query = request.args.get("q", "").strip()
    search_lc = search_query.lower()
    sort_by = request.args.get("sort", "next_due").strip().lower()
    if sort_by not in {"default", "newest", "oldest", "title", "no_id", "due", "next_due"}:
        sort_by = "next_due"
    folder_filter = request.args.get("folder", "all").strip()
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
        folder = str(ad_data.get("folder", "")).strip()
        if folder_filter == "__none__" and folder:
            continue
        if folder_filter not in ("all", "__none__") and folder != folder_filter:
            continue
        is_active = ad_data.get("active", True)
        has_id = bool(ad_data.get("id"))
        scheduled_at = meta.get("scheduled_publish_at")
        scheduled_dt = _iso_dt(scheduled_at)
        postponed_dt = _iso_dt(meta.get("republish_postponed_until"))
        is_postponed = bool(postponed_dt) and postponed_dt > now_utc
        is_schedule_due = is_active and not bool(meta.get("last_published")) and bool(scheduled_dt) and scheduled_dt <= now_utc
        is_scheduled_future = is_active and not bool(meta.get("last_published")) and bool(scheduled_dt) and scheduled_dt > now_utc
        is_online = is_active and (bool(meta.get("last_published")) or (has_id and not is_scheduled_future and not is_schedule_due))
        is_planned = is_active and not is_online
        is_unpublished = not bool(meta.get("last_published")) and not has_id

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
            slug,
        ]).lower()
        if search_lc and search_lc not in haystack:
            continue

        created_ref = _age_reference_iso(slug, ad_data, meta) or _now()
        age = _age_days(created_ref)
        republish_interval = int(ad_data.get("republication_interval") or REPUBLISH_INTERVAL)
        schedule_label = _scheduled_label(scheduled_at)
        is_stale = ((is_online and age >= republish_interval) or is_schedule_due) and not is_postponed
        price_cfg = _price_reduction_config(ad_data)
        if price_cfg["enabled"]:
            price_drop_label = f"-{_fmt_money(price_cfg['drop'])} € / {price_cfg['days']}T"
            if price_cfg["min_price"] > 0:
                price_drop_label += f" · min {_fmt_money(price_cfg['min_price'])} €"
        else:
            price_drop_label = "aus"

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
            next_due_days = (next_due_dt.date() - now_utc.date()).days
            if next_due_days <= 0:
                next_due_label = "heute fällig"
            elif next_due_days == 1:
                next_due_label = "morgen fällig"
            else:
                next_due_label = f"in {next_due_days} Tagen"

        if not is_active:
            status_label = "Inaktiv"
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
            "is_online": is_online,
            "is_planned": is_planned,
            "is_unpublished": is_unpublished,
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
            "price_drop_label": price_drop_label,
            "folder": folder,
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
        folders=folders,
        due_preview=due_preview,
        unpublished_count=unpublished_count,
        import_status=_import_status_for_ui(state),
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


# -- Routes: Settings --

@app.route("/settings", methods=["GET"])
def settings_form():
    return render_template(
        "settings.html",
        settings=_get_settings(),
        activity=_get_account_activity(),
        backup=_backup_overview(),
        backups=_list_backups(),
        shipping_option_groups=SHIPPING_OPTION_GROUPS,
        shipping_price_fields=SHIPPING_PRICE_FIELDS,
    )

@app.route("/settings", methods=["POST"])
def settings_save():
    current_settings = _get_settings()
    shipping_prices = {}
    for code, field_name in SHIPPING_PRICE_FIELDS.items():
        shipping_prices[code] = request.form.get(field_name, DEFAULT_SHIPPING_PRICES.get(code, "")).strip()
    settings = {
        "email": request.form.get("email", "").strip(),
        "password": request.form.get("password", "").strip() or current_settings.get("password", ""),
        "contact_name": request.form.get("contact_name", "").strip(),
        "default_location": request.form.get("default_location", "").strip(),
        "republish_days": int(request.form.get("republish_days", REPUBLISH_INTERVAL)),
        "shipping_prices": shipping_prices,
    }
    _ensure_bot_config(settings)
    flash("Einstellungen gespeichert!", "ok")
    return redirect(url_for("settings_form"))

@app.route("/settings/activity-refresh", methods=["POST"])
def refresh_activity():
    if _last_log.get("running"):
        flash("Bitte warten, bis der Bot fertig ist.", "err")
        return redirect(url_for("settings_form"))
    if _vnc_running():
        flash("Bitte zuerst die noVNC-Browser-Session beenden.", "err")
        return redirect(url_for("settings_form"))
    ok, msg, result = _refresh_account_activity_until_today(max_attempts=4, delay_seconds=2)
    if ok:
        flash("Aktivitaet aktualisiert.", "ok")
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
    ok, msg = _start_vnc_login()
    if ok:
        flash("Browser gestartet! Oeffne den noVNC-Link unten.", "ok")
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
    existing_meta = _load_state().get("ads", {}).get(slug, {})
    if ad.get("id") or existing_meta.get("last_published"):
        return False, "Die Anzeige ist bereits veröffentlicht. Bitte dafür die Funktion „Erneuern“ verwenden."
    if not _get_settings().get("configured"):
        return False, "Webapp-Login ist noch nicht eingerichtet."
    if _last_log.get("running"):
        return False, "Der Webapp-Bot läuft bereits."

    result = _run_bot_for_slug("publish", slug, ads="all")
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    if result.get("ok"):
        meta["last_published"] = _now()
        meta["publish_count"] = meta.get("publish_count", 0) + 1
        meta["scheduled_publish_at"] = None
        meta.setdefault("history", []).append({"action": "beim Speichern veröffentlicht", "date": _now()})
    else:
        meta.setdefault("history", []).append({"action": "Fehler bei Speichern & Veröffentlichen", "date": _now()})
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    return bool(result.get("ok")), str(result.get("output") or "Unbekannter Fehler")

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
                           default_folder=default_folder)

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
    state["ads"][slug] = {
        "created_at": _now(),
        "last_published": None,
        "publish_count": 0,
        "scheduled_publish_at": schedule_at,
        "history": [{"action": "erstellt", "date": _now()}],
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
    return_url = url_for("index", **return_context)
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
                           return_context=return_context, return_url=return_url)

@app.route("/edit/<slug>", methods=["POST"])
def edit_save(slug):
    return_url = _index_return_url(request.form, prefix="return_")
    ad = _read_ad_yaml(slug)
    if not ad:
        return redirect(return_url)
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
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    meta["scheduled_publish_at"] = schedule_at
    meta.setdefault("history", []).append({"action": "bearbeitet", "date": _now()})
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    if request.form.get("save_action") == "publish":
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

    # Neue Webapp-Versandlogik: genau eine Paketgröße, darin mehrere Methoden.
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

    if action in {"publish", "republish", "ka_delete"} and _last_log.get("running"):
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

    if action == "copy":
        _create_backup(reason='vor-mehrfach-kopie')
        for slug in selected:
            if _copy_ad(slug):
                ok_count += 1
            else:
                fail_count += 1
        flash(f"{ok_count} Anzeigen kopiert" + (f", {fail_count} fehlgeschlagen." if fail_count else "."), "ok" if not fail_count else "warn")
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
                meta.setdefault("history", []).append({"action": "von Webapp geloescht", "date": _now()})
                ok_count += 1
            else:
                meta.setdefault("history", []).append({"action": "Fehler beim KA-Löschen", "date": _now()})
                fail_count += 1
            state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash(f"{ok_count} Anzeigen bei Webapp gelöscht" + (f", {fail_count} fehlgeschlagen." if fail_count else "."), "ok" if not fail_count else "warn")
        return redirect(request.referrer or url_for("index"))

    if action == "publish":
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad or not ad.get("active", True):
                continue
            meta = state.get("ads", {}).get(slug, {})
            if meta.get("last_published"):
                continue
            result = _run_bot_for_slug("publish", slug, ads="all")
            if result.get("ok"):
                meta["last_published"] = _now()
                meta["publish_count"] = meta.get("publish_count", 0) + 1
                meta["scheduled_publish_at"] = None
                _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                meta.setdefault("history", []).append({"action": "veroeffentlicht", "date": _now()})
                ok_count += 1
            else:
                meta.setdefault("history", []).append({"action": "Fehler beim Veroeffentlichen", "date": _now()})
                fail_count += 1
            state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash(f"{ok_count} Anzeigen veröffentlicht" + (f", {fail_count} fehlgeschlagen." if fail_count else "."), "ok" if not fail_count else "warn")
        return redirect(request.referrer or url_for("index"))

    if action == "republish":
        for slug in selected:
            ad = _read_ad_yaml(slug)
            if not ad or not ad.get("active", True):
                continue
            meta = state.get("ads", {}).get(slug, {})
            delete_result = _run_bot_for_slug("delete", slug, ads="all")
            price_change = None
            if not delete_result.get("ok"):
                result = delete_result
            else:
                price_change = _prepare_republish_price_reduction(slug, meta)
                result = _run_bot_for_slug("publish", slug, ads="all")
                if not result.get("ok") and price_change:
                    _restore_republish_price(slug, price_change["old_price"])
            if result.get("ok"):
                meta["last_published"] = _now()
                meta["publish_count"] = meta.get("publish_count", 0) + 1
                meta["scheduled_publish_at"] = None
                if price_change:
                    _commit_price_reduction(meta, price_change)
                    meta.setdefault("history", []).append({"action": f"Preis gesenkt: {_fmt_money(price_change['old_price'])} € → {_fmt_money(price_change['new_price'])} €", "date": _now()})
                else:
                    _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
                meta.setdefault("history", []).append({"action": "neu eingestellt", "date": _now()})
                ok_count += 1
            else:
                meta.setdefault("history", []).append({"action": "Fehler beim Republish", "date": _now()})
                fail_count += 1
            state.setdefault("ads", {})[slug] = meta
        _save_state(state)
        flash(f"{ok_count} Anzeigen neu eingestellt" + (f", {fail_count} fehlgeschlagen." if fail_count else "."), "ok" if not fail_count else "warn")
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
        is_planned = is_active and not bool(meta.get("last_published"))
        if is_planned:
            selected.append(slug)

    if not selected:
        flash("Bitte mindestens eine geplante Anzeige auswählen.", "warn")
        return redirect(url_for("index", status="planned"))

    ok_count = 0
    fail_count = 0
    for slug in selected:
        result = _run_bot_for_slug("publish", slug, ads="all")
        meta = state.get("ads", {}).get(slug, {})
        if result.get("ok"):
            meta["last_published"] = _now()
            meta["publish_count"] = meta.get("publish_count", 0) + 1
            meta["scheduled_publish_at"] = None
            _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
            meta.setdefault("history", []).append({"action": "veroeffentlicht", "date": _now()})
            ok_count += 1
        else:
            meta.setdefault("history", []).append({"action": "Fehler beim Veroeffentlichen", "date": _now()})
            fail_count += 1
        state.setdefault("ads", {})[slug] = meta

    _save_state(state)

    if ok_count and not fail_count:
        flash(f"{ok_count} geplante Anzeigen veröffentlicht!", "ok")
    elif ok_count and fail_count:
        flash(f"{ok_count} Anzeigen veröffentlicht, {fail_count} fehlgeschlagen.", "warn")
    else:
        flash("Keine der ausgewählten Anzeigen konnte veröffentlicht werden.", "err")
    return redirect(url_for("index", status="planned"))

@app.route("/publish/<slug>", methods=["POST"])
def publish_ad(slug):
    ad = _read_ad_yaml(slug)
    if not ad:
        flash("Anzeige nicht gefunden.", "err")
        return redirect(url_for("index"))
    result = _run_bot_for_slug("publish", slug, ads="all")
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    if result["ok"]:
        meta["last_published"] = _now()
        meta["publish_count"] = meta.get("publish_count", 0) + 1
        _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
        meta.setdefault("history", []).append({"action": "veroeffentlicht", "date": _now()})
        flash("Anzeige veroeffentlicht!", "ok")
    else:
        meta.setdefault("history", []).append({"action": "Fehler beim Veroeffentlichen", "date": _now()})
        flash("Fehler: " + result["output"][:200], "err")
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    return redirect(url_for("index"))

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
    meta = state.get("ads", {}).get(slug, {})
    delete_result = _run_bot_for_slug("delete", slug, ads="all")
    price_change = None
    if not delete_result["ok"]:
        result = delete_result
    else:
        price_change = _prepare_republish_price_reduction(slug, meta)
        result = _run_bot_for_slug("publish", slug, ads="all")
        if not result["ok"] and price_change:
            _restore_republish_price(slug, price_change["old_price"])
    if result["ok"]:
        meta["last_published"] = _now()
        meta["publish_count"] = meta.get("publish_count", 0) + 1
        meta["scheduled_publish_at"] = None
        if price_change:
            _commit_price_reduction(meta, price_change)
            meta.setdefault("history", []).append({"action": f"Preis gesenkt: {_fmt_money(price_change['old_price'])} € → {_fmt_money(price_change['new_price'])} €", "date": _now()})
        else:
            _ensure_price_reduction_anchor(slug, _read_ad_yaml(slug) or {}, meta)
        meta.setdefault("history", []).append({"action": "neu eingestellt", "date": _now()})
        flash("Anzeige neu eingestellt!", "ok")
    else:
        meta.setdefault("history", []).append({"action": "Fehler beim Republish", "date": _now()})
        flash("Fehler: " + result["output"][:200], "err")
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    return redirect(url_for("index"))

@app.route("/publish-all", methods=["POST"])
def publish_all():
    scheduled_due = _collect_due_scheduled_slugs()
    result = _run_bot("publish", ads="due")
    scheduled_result = {"published": 0, "failed": 0, "processed": []}
    if scheduled_due:
        scheduled_result = _publish_scheduled_due_ads(auto=False)

    published_count = scheduled_result["published"]
    failed_count = scheduled_result["failed"]
    output = result.get("output", "")
    nothing_due = ("No new/outdated ads found" in output) and not scheduled_due

    if nothing_due:
        flash("Aktuell sind keine Anzeigen fällig.", "info")
    elif result["ok"] and not scheduled_due:
        flash("Alle fälligen Anzeigen erneuert!", "ok")
    elif result["ok"]:
        msg = "Fällige Anzeigen erneuert"
        if published_count:
            msg += f" · {published_count} geplante veröffentlicht"
        if failed_count:
            msg += f" · {failed_count} geplante fehlgeschlagen"
        flash(msg + "!", "ok" if not failed_count else "warn")
    else:
        if published_count or failed_count:
            msg = "Fehler beim Erneuern"
            if published_count:
                msg += f" · {published_count} geplante veröffentlicht"
            if failed_count:
                msg += f" · {failed_count} geplante fehlgeschlagen"
            flash(msg, "warn")
        else:
            flash("Fehler: " + result["output"][:200], "err")
    return redirect(url_for("index"))

@app.route("/bot-delete/<slug>", methods=["POST"])
def bot_delete_ad(slug):
    _create_backup(reason='vor-ka-loeschen', slug=slug)
    result = _run_bot_for_slug("delete", slug, ads="all")
    state = _load_state()
    meta = state.get("ads", {}).get(slug, {})
    meta.setdefault("history", []).append({"action": "von Webapp geloescht", "date": _now()})
    state.setdefault("ads", {})[slug] = meta
    _save_state(state)
    if result["ok"]:
        flash("Anzeige von Webapp entfernt.", "ok")
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
    log_files = sorted(LOGS_DIR.glob("*.log"), reverse=True)[:20] if LOGS_DIR.is_dir() else []
    logs = [{"name": lf.name, "content": lf.read_text("utf-8", errors="replace")} for lf in log_files]
    return render_template("logs.html", logs=logs, last_log=_last_log)

@app.route("/bot-status")
def bot_status():
    return jsonify(_last_log)

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
    for d in [DATA_DIR, ADS_DIR, IMAGES_DIR, LOGS_DIR, BACKUP_DIR, IMPORT_DIR, IMPORT_ERROR_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    _prune_old_backups()
    _migrate_price_reduction_settings()
    threading.Thread(target=_scheduled_publish_loop, daemon=True).start()
    threading.Thread(target=_media_import_watch_loop, daemon=True).start()
    threading.Thread(target=_automatic_import_loop, daemon=True).start()
    if GOOGLE_DRIVE_IMPORT_ENABLED:
        threading.Thread(target=_google_drive_import_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
