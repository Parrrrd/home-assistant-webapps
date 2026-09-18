"""Serienplaner – bewusst schlanke Home-Assistant-App ohne externe Abhängigkeiten."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

VERSION = "0.1.32"
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "serienplaner.json"
OPTIONS_FILE = DATA_DIR / "options.json"
PORT = int(os.getenv("PORT", "8152"))
GEMINI_HTTP_TIMEOUT_SECONDS = 120
POSTER_TIMEOUT_SECONDS = 4
CHECK_TOTAL_SECONDS = 1800
MAX_SERIES_PER_CHECK = 12
AUTO_CHECK_WEEKDAYS = {1, 4}  # Dienstag, Freitag


# Belastbare deutsche Episodenplaene fuer zwei aktuell problematische Faelle.
# Diese Guardrails ersetzen keine Gemini-Recherche; sie verhindern nur, dass ein
# bekannter deutscher Ausstrahlungsplan durch US-/Originaldaten ueberschrieben wird.
KNOWN_911_S9_DE_RELEASES = (
    date(2026, 3, 18), date(2026, 3, 25), date(2026, 4, 1), date(2026, 4, 8),
    date(2026, 4, 15), date(2026, 4, 22), date(2026, 4, 29), date(2026, 5, 6),
    date(2026, 5, 13), date(2026, 7, 22), date(2026, 7, 29), date(2026, 8, 5),
    date(2026, 8, 12), date(2026, 8, 19), date(2026, 8, 26), date(2026, 9, 2),
    date(2026, 9, 9), date(2026, 9, 16),
)
KNOWN_CHICAGO_MED_S11_TOTAL = 21
KNOWN_CHICAGO_MED_S11_DE_FINALE = date(2026, 10, 12)
KNOWN_CHICAGO_FIRE_S14_TOTAL = 21
KNOWN_CHICAGO_FIRE_S14_DE_FINALE = date(2026, 10, 12)
KNOWN_CHICAGO_PD_S12_TOTAL = 22
KNOWN_CHICAGO_PD_S13_DE_START = date(2026, 9, 2)
KNOWN_FIRE_COUNTRY_S4_TOTAL = 20
KNOWN_FIRE_COUNTRY_S4_DE_FINALE = date(2026, 10, 20)
HA_BASE = "http://supervisor/core/api"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
DEFAULT_NOTIFY_SERVICE = "notify.mobile_app_iphone A"

SEED_SERIES = [
    {"id": "chicago-pd", "name": "Chicago P.D.", "status": "watching", "season": 8, "episode": 0,
     "note": "Staffel 9 und 10 sind noch offen."},
    {"id": "911", "name": "9-1-1", "status": "watching", "season": 8, "episode": 0, "note": "Bis Staffel 8 gesehen."},
    {"id": "the-rookie", "name": "The Rookie", "status": "watching", "season": 7, "episode": 0, "note": "Bis Staffel 7 gesehen."},
    {"id": "greys-anatomy", "name": "Grey's Anatomy", "status": "watching", "season": 21, "episode": 0, "note": "Bis Staffel 21 gesehen."},
    {"id": "chicago-med", "name": "Chicago Med", "status": "watching", "season": 10, "episode": 0, "note": "Bis Staffel 10 gesehen."},
    {"id": "chicago-fire", "name": "Chicago Fire", "status": "watching", "season": 12, "episode": 0, "note": "Bis Staffel 12 gesehen."},
    {"id": "fire-country", "name": "Fire Country", "status": "watching", "season": 3, "episode": 0, "note": "Bis Staffel 3 gesehen."},
    {"id": "family-law", "name": "Family Law", "status": "watching", "season": 4, "episode": 0, "note": "Bis Staffel 4 gesehen."},
    {"id": "new-amsterdam", "name": "New Amsterdam", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie beendet."},
    {"id": "the-resident", "name": "The Resident", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie beendet."},
    {"id": "the-rookie-feds", "name": "The Rookie: Feds", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie eingestellt."},
    {"id": "station-19", "name": "Station 19", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie beendet."},
    {"id": "blue-bloods", "name": "Blue Bloods", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie beendet."},
    {"id": "911-lone-star", "name": "9-1-1: Lone Star", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie beendet."},
    {"id": "swat", "name": "S.W.A.T.", "status": "cancelled", "season": 0, "episode": 0, "note": "Komplett gesehen · Serie beendet."},
    {"id": "will-trent", "name": "Will Trent", "status": "watching", "season": 4, "episode": 0, "note": "Bis Staffel 4 gesehen."},
]


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.data: dict[str, Any] = self._load()
        self._migrate_defaults()

    def _migrate_defaults(self) -> None:
        """Ergänzt neue Startserien, ohne eine gepflegte Liste zu überschreiben."""
        series = self.data.setdefault("series", [])
        known_ids = {str(item.get("id", "")) for item in series if isinstance(item, dict)}
        changed = False
        for entry in SEED_SERIES:
            if entry["id"] not in known_ids:
                series.append(dict(entry))
                changed = True
        daily = self.data.setdefault("daily_check", {})
        # Ein laufender Netzwerkabruf kann einen App-Neustart nicht überleben.
        # Ohne diese Korrektur bliebe die Oberfläche fälschlich bei „prüft gerade“.
        if daily.get("check_running"):
            daily.update({"check_running": False, "request_id": None,
                          "error": "Prüfung durch Neustart beendet"})
            changed = True
        migrations = self.data.setdefault("migrations", {})
        # Korrektur der ersten Serienliste: Will Trent läuft weiter und gehört
        # deshalb samt Fortschritt in die tägliche Prüfung.
        if not migrations.get("will_trent_active_v1"):
            for item in series:
                if isinstance(item, dict) and item.get("id") == "will-trent":
                    item.update({"status": "watching", "season": 4, "episode": 0,
                                 "note": "Bis Staffel 4 gesehen."})
                    changed = True
                    break
            migrations["will_trent_active_v1"] = True
            changed = True
        if changed:
            self.save()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {
                "series": SEED_SERIES,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "daily_check": {
                    "last_run_date": None,
                    "last_checked_at": None,
                    "series_status": [],
                    "error": None,
                    "check_running": False,
                    "last_check_kind": None,
                    "last_auto_run_date": None,
                },
            }

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = DATA_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(DATA_FILE)


store = Store()


def ensure_v025_state() -> None:
    """Bereinigt Statusdarstellung und erweitert Staffelfinale-Daten."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v025_status_cleanup"):
            for item in store.data.setdefault("series", []):
                if isinstance(item, dict):
                    item["status_note_version"] = "0.1.25"
            migrations["v025_status_cleanup"] = True
            changed = True
        if changed:
            store.save()


def ensure_v019_state() -> None:
    """Migriert 0.1.19, repariert 0.1.18-Altstände und setzt Pushs sicher neu auf."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        notifications = store.data.setdefault("notification_settings", {})
        defaults = {
            "enabled": True,
            "season_complete": True,
            "new_season_confirmed": True,
            "season_started": True,
            "series_ended": True,
            "start_date_known": False,
            "notify_service": DEFAULT_NOTIFY_SERVICE,
        }
        for key, value in defaults.items():
            if key not in notifications:
                notifications[key] = value
                changed = True
        store.data.setdefault("notified_event_keys", [])
        store.data.setdefault("notification_history", [])
        if "notification_baseline_ready" not in store.data:
            store.data["notification_baseline_ready"] = False
            changed = True
        for item in store.data.setdefault("series", []):
            if isinstance(item, dict) and "wait_until_complete" not in item:
                item["wait_until_complete"] = False
                changed = True
        if not migrations.get("v018_remove_recommendations"):
            store.data.pop("recommendation_feedback", None)
            daily = store.data.setdefault("daily_check", {})
            daily.pop("recommendations", None)
            migrations["v018_remove_recommendations"] = True
            changed = True

        # 0.1.18 konnte Family Law nach einer einzelnen falschen Gemini-Aussage
        # automatisch als beendet archivieren. Nur genau diesen automatisch
        # erzeugten Zustand zurückholen.
        if not migrations.get("v019_restore_family_law"):
            for item in store.data.setdefault("series", []):
                if not isinstance(item, dict) or str(item.get("name", "")).lower() != "family law":
                    continue
                note = str(item.get("note", ""))
                if item.get("status") == "cancelled" and re.search(r"offiziell beendet|serie beendet|4\. staffel.*beendet", note, re.I):
                    item["status"] = "watching"

                    try:
                        current_season = int(item.get("season") or 4)
                    except (TypeError, ValueError):
                        current_season = 4
                    item["season"] = max(4, current_season)
                    item["episode"] = 0
                    item["note"] = "Bis Staffel 4 gesehen."
                    changed = True
                break
            migrations["v019_restore_family_law"] = True
            changed = True

        # Falsche 0.1.18-Ereignisse dürfen spätere echte Pushs nicht blockieren.
        if not migrations.get("v019_rebuild_notification_baseline"):
            store.data["notified_event_keys"] = []
            store.data["notification_baseline_ready"] = False
            store.data.setdefault("series_end_confirmations", {})
            store.data.setdefault("daily_check", {})["needs_refresh"] = True
            migrations["v019_rebuild_notification_baseline"] = True
            changed = True

        if changed:
            store.save()


ensure_v025_state()
ensure_v019_state()


def ensure_v020_state() -> None:
    """Markiert den deutschen Faktenstand nach 0.1.19 einmalig zur Neuberechnung."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v020_german_release_scope"):
            daily = store.data.setdefault("daily_check", {})
            daily["needs_refresh"] = True
            store.data["notified_event_keys"] = []
            store.data["notification_baseline_ready"] = False
            migrations["v020_german_release_scope"] = True
            changed = True
        if changed:
            store.save()


ensure_v020_state()

def ensure_v021_state() -> None:
    """Setzt die Push-Baseline nach den gezielten 9-1-1/Chicago-Med-Korrekturen neu."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v021_episode_guardrails"):
            daily = store.data.setdefault("daily_check", {})
            daily["needs_refresh"] = True
            store.data["notified_event_keys"] = []
            store.data["notification_baseline_ready"] = False
            migrations["v021_episode_guardrails"] = True
            changed = True
        if changed:
            store.save()


ensure_v021_state()


def ensure_v022_state() -> None:
    """Aktualisiert die Faktenwächter, ohne alte Fehlereignisse zu pushen."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v022_monotonic_german_facts"):
            daily = store.data.setdefault("daily_check", {})
            daily["needs_refresh"] = True
            # 0.1.21 konnte Chicago P.D. S12 fälschlich wieder als laufend sehen.
            # Die Push-Baseline wird deshalb einmal still aus dem korrigierten Stand aufgebaut.
            store.data["notified_event_keys"] = []
            store.data["notification_baseline_ready"] = False
            migrations["v022_monotonic_german_facts"] = True
            changed = True
        if changed:
            store.save()


ensure_v022_state()


def ensure_v027_state() -> None:
    """Verlangt nach den neuen Staffelfinal-Daten einen frischen Faktencheck."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v027_finale_cleanup"):
            daily = store.data.setdefault("daily_check", {})
            daily["needs_refresh"] = True
            migrations["v027_finale_cleanup"] = True
            changed = True
        if changed:
            store.save()


ensure_v027_state()


def ensure_v028_state() -> None:
    """Fordert nach der Einzelrecherche einmal neue, belastbare Finaltermine an."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v028_targeted_finale_check"):
            store.data.setdefault("daily_check", {})["needs_refresh"] = True
            migrations["v028_targeted_finale_check"] = True
            changed = True
        if changed:
            store.save()


ensure_v028_state()


def ensure_v029_state() -> None:
    """Aktiviert die festen, belegten deutschen Staffelfinal-Termine sofort."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v029_known_de_finales"):
            store.data.setdefault("daily_check", {})["needs_refresh"] = True
            migrations["v029_known_de_finales"] = True
            changed = True
        if changed:
            store.save()


ensure_v029_state()


def ensure_v030_state() -> None:
    """Aktiviert die allgemeine Endtermin-Berechnung für jede laufende Serie."""
    changed = False
    with store.lock:
        migrations = store.data.setdefault("migrations", {})
        if not migrations.get("v030_general_finale_forecast"):
            store.data.setdefault("daily_check", {})["needs_refresh"] = True
            migrations["v030_general_finale_forecast"] = True
            changed = True
        if changed:
            store.save()


ensure_v030_state()


def next_auto_check_date(last_auto_run_date: str | None = None) -> date:
    today = datetime.now().date()
    if today.weekday() in AUTO_CHECK_WEEKDAYS and last_auto_run_date != today.isoformat():
        return today
    for offset in range(1, 8):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() in AUTO_CHECK_WEEKDAYS:
            return candidate
    return today + timedelta(days=7)


def dashboard() -> dict[str, Any]:
    expire_stale_check()
    with store.lock:
        entries = [dict(item) for item in store.data.get("series", [])]
        daily = json.loads(json.dumps(store.data.get("daily_check", {})))
        notifications = dict(store.data.get("notification_settings", {}))
        notification_history = list(store.data.get("notification_history", []))[-12:]
    active = [item for item in entries if item.get("status") == "watching"]
    cancelled = [item for item in entries if item.get("status") == "cancelled"]
    paused = [item for item in entries if item.get("status") == "paused"]
    dashboard_result = {"series_status": daily.get("series_status", [])}
    normalize_for_watch_progress(dashboard_result, active)
    if not daily.get("check_running"):
        ensure_active_placeholders(dashboard_result, active)
    daily["series_status"] = dashboard_result["series_status"]
    today = datetime.now().date()
    automatic_done_today = daily.get("last_auto_run_date", daily.get("last_run_date")) == today.isoformat()
    scheduled_today = today.weekday() in AUTO_CHECK_WEEKDAYS
    if daily.get("check_running"):
        check_state = "Gemini prüft gerade"
        progress_done = int(daily.get("progress_done") or 0)
        progress_total = int(daily.get("progress_total") or 0)
        progress_current = str(daily.get("progress_current") or "").strip()
        if progress_total and progress_current:
            check_detail = f"Prüfe {min(progress_done + 1, progress_total)}/{progress_total}: {progress_current}. Fertige Ergebnisse erscheinen sofort."
        elif progress_total:
            check_detail = f"Prüfung läuft Serie für Serie: {progress_done}/{progress_total} erledigt."
        else:
            check_detail = "Die Ergebnisse erscheinen gleich hier. Manuell kann jederzeit erneut geprüft werden."
    elif daily.get("needs_refresh") and gemini_api_key():
        check_state = "Nach Update neu prüfen"
        check_detail = "Die Plausibilitätsregeln wurden verbessert. Einmal Jetzt prüfen starten; alternativ erfolgt der Neucheck automatisch am nächsten Dienstag/Freitag."
    elif automatic_done_today and scheduled_today:
        check_state = "Automatisch geprüft"
        check_detail = f"Letzte Prüfung: {daily.get('last_checked_at') or 'heute'} · manuell jederzeit erneut möglich."
    elif not gemini_api_key():
        check_state = "Gemini-Schlüssel fehlt"
        check_detail = "In den Add-on-Einstellungen einen Gemini API-Schlüssel eintragen. Automatisch wird dienstags und freitags geprüft."
    else:
        upcoming = next_auto_check_date(daily.get("last_auto_run_date"))
        weekday = {1: "Dienstag", 4: "Freitag"}.get(upcoming.weekday(), upcoming.strftime("%A"))
        check_state = "Nächster Auto-Check"
        check_detail = f"{weekday}, {upcoming.strftime('%d.%m.')} · automatisch Dienstag & Freitag · manuell jederzeit."
    if daily.get("error") and not daily.get("check_running"):
        check_detail = "Die letzte Prüfung hatte keine verwertbare Antwort. Manuell kann sie sofort neu gestartet werden; automatisch wieder Dienstag/Freitag."
    return {
        "version": VERSION,
        "series": entries,
        "counts": {"watching": len(active), "paused": len(paused), "cancelled": len(cancelled)},
        "daily_check": {
            "state": check_state, "detail": check_detail,
            "series_status": daily.get("series_status", []), "archived": daily.get("archived", []),
            "last_checked_at": daily.get("last_checked_at"), "last_check_kind": daily.get("last_check_kind"),
            "is_running": bool(daily.get("check_running")),
            "progress_done": int(daily.get("progress_done") or 0),
            "progress_total": int(daily.get("progress_total") or 0),
            "progress_current": str(daily.get("progress_current") or ""),
        },
        "notification_settings": notifications,
        "notification_history": notification_history,
    }


def gemini_api_key() -> str:
    """Liest den Schlüssel nur aus den geschützten Add-on-Optionen."""
    try:
        options = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        return str(options.get("gemini_api_key", "")).strip() if isinstance(options, dict) else ""
    except (OSError, ValueError):
        return ""


def gemini_log(message: str) -> None:
    """Diagnose ohne Schlüssel oder Zugangsdaten in die Add-on-Protokolle schreiben."""
    print(f"[Serienplaner · Gemini] {message}", flush=True)


def expire_stale_check() -> bool:
    """Beendet eine Prüfung in der Oberfläche, wenn der Hintergrundlauf zu lange braucht."""
    with store.lock:
        daily = store.data.setdefault("daily_check", {})
        if not daily.get("check_running"):
            return False
        started_at = float(daily.get("started_at") or 0)
        if not started_at or time.time() - started_at <= CHECK_TOTAL_SECONDS:
            return False
        daily.update({"check_running": False, "request_id": None, "started_at": None,
                      "error": "Zeitlimit überschritten"})
        store.save()
    gemini_log(f"Prüfung nach {CHECK_TOTAL_SECONDS} Sekunden beendet.")
    return True


def extract_interaction_output(response: dict[str, Any]) -> tuple[str, list[str]]:
    """Liest den Text und die Quellen aus der aktuellen Gemini-Interactions-Antwort."""
    texts: list[str] = []
    sources: list[str] = []
    # Neues Interactions-Schema: strukturierte Schritte.
    for step in response.get("steps", []):
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for block in step.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = str(block.get("text", "")).strip()
            if text:
                texts.append(text)
            for annotation in block.get("annotations", []):
                if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                    continue
                url = str(annotation.get("url", "")).strip()
                if url and url not in sources:
                    sources.append(url)
    # Fallback für ältere/andere Antwortformen. Damit wird ein Schemawechsel
    # nicht sofort zu „keine Antwort“, obwohl Text vorhanden ist.
    for block in response.get("outputs", []):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = str(block.get("text", "")).strip()
            if text:
                texts.append(text)
    for candidate in response.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        parts = candidate.get("content", {}).get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                texts.append(str(part.get("text", "")).strip())
    # Interactions kann Text auch direkt unter "output" liefern.
    def collect_output_text(value: Any) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                texts.append(stripped)
            return
        if isinstance(value, list):
            for entry in value:
                collect_output_text(entry)
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "text" and value.get("text"):
            texts.append(str(value.get("text", "")).strip())
        for key in ("content", "parts", "items"):
            if key in value:
                collect_output_text(value[key])

    if "output" in response:
        collect_output_text(response["output"])
    return "\n".join(texts).strip(), sources


def call_gemini_interaction(key: str, payload: dict[str, Any]) -> tuple[str, list[str], str]:
    """Ruft Gemini genau einmal auf. Kein automatischer Zweitversuch."""
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=GEMINI_HTTP_TIMEOUT_SECONDS) as raw:
        response = json.loads(raw.read().decode("utf-8"))
    response_text, response_sources = extract_interaction_output(response)
    meta = str(response.get("status") or response.get("id") or "normale-antwort")
    return response_text, response_sources, meta


def poster_url(title: str) -> str:
    """Lädt ein Poster über TVmaze nach; ein fehlendes Bild darf den Check nie verhindern."""
    safe_title = quote(title, safe="")
    request = urllib.request.Request(
        f"https://api.tvmaze.com/singlesearch/shows?q={safe_title}",
        headers={"Accept": "application/json", "User-Agent": f"Serienplaner/{VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=POSTER_TIMEOUT_SECONDS) as raw:
            result = json.loads(raw.read().decode("utf-8"))
        image = result.get("image", {}) if isinstance(result, dict) else {}
        if isinstance(image, dict):
            return str(image.get("medium") or image.get("original") or "").strip()[:500]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        pass
    return ""


def parse_episode_counts(value: Any) -> tuple[int | None, int | None]:
    """Liest Episodenzahlen. Unbekannt bleibt None und wird nie zu 0 erfunden."""
    text = str(value or "").strip()
    if not text:
        return None, None
    patterns = [
        r"(?:folgen?|episoden?)\s*1\s*[–—-]\s*(\d+)\s*(?:von|/)\s*(\d+)",
        r"(?:folgen?|episoden?)?\s*(\d+)\s*/\s*(\d+)",
        r"(?:folgen?|episoden?)\s*1\s*[–—-]\s*(\d+)",
    ]
    for idx, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        available = int(match.group(1))
        total = int(match.group(2)) if idx < 2 else None
        return (available if available > 0 else None, total if total and total > 0 else None)
    return None, None


def optional_episode_count(value: Any, fallback: int | None = None) -> int | None:
    """Positive Folgenzahl oder None; 0/null/leer bedeuten ausdrücklich unbekannt."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(fallback) if fallback else 0
    return number if 0 < number <= 1000 else None


def parse_known_date(value: Any) -> date | None:
    text = str(value or "")
    for pattern, order in [
        (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "dmy"),
        (r"(\d{4})-(\d{2})-(\d{2})", "ymd"),
    ]:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if order == "dmy":
                return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return None


def season_number(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    number = int(match.group(0))
    return number if 0 < number <= 100 else None


def clean_seasons(value: Any) -> list[dict[str, Any]]:
    seasons: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return seasons
    for row in value[:12]:
        if not isinstance(row, dict):
            continue
        season = season_number(row.get("season"))
        if not season:
            continue
        state = str(row.get("state", "unknown")).strip().lower()
        aliases = {"available": "streamable", "complete": "streamable", "running": "ongoing"}
        state = aliases.get(state, state)
        if state not in {"streamable", "ongoing", "not_streamable", "upcoming", "unknown", "seen"}:
            state = "unknown"
        episodes = str(row.get("episodes", "")).strip()[:160]
        parsed_available, parsed_total = parse_episode_counts(episodes)
        # Deutsche Veröffentlichungszahlen haben Vorrang; alte Feldnamen bleiben
        # als Fallback kompatibel.
        available_raw = row.get("german_available_episodes", row.get("available_episodes"))
        total_raw = row.get("german_total_episodes", row.get("total_episodes"))
        available_episodes = optional_episode_count(available_raw, parsed_available)
        total_episodes = optional_episode_count(total_raw, parsed_total)
        cadence_days = optional_episode_count(row.get("german_release_cadence_days", row.get("release_cadence_days")))
        episodes_per_release = optional_episode_count(row.get("german_episodes_per_release", row.get("episodes_per_release")))
        complete = bool(available_episodes and total_episodes and available_episodes == total_episodes)
        seasons.append({
            "season": str(season), "state": state, "episodes": episodes,
            "available_episodes": available_episodes, "total_episodes": total_episodes,
            "complete": complete, "gemini_complete_hint": row.get("complete") is True,
            "provider": str(row.get("provider", "")).strip()[:120],
            "availability": str(row.get("availability", "")).strip()[:180],
            "next_episode_date": str(row.get("german_next_episode_date", row.get("next_episode_date", ""))).strip()[:80],
            "season_finale_date": str(row.get("german_season_finale_date", row.get("season_finale_date", ""))).strip()[:80],
            "release_cadence_days": cadence_days if cadence_days and cadence_days <= 31 else None,
            "episodes_per_release": episodes_per_release if episodes_per_release and episodes_per_release <= 20 else None,
            "complete_available_date": str(row.get("german_complete_available_date", row.get("complete_available_date", ""))).strip()[:80],
            "start_date": str(row.get("german_start_date", row.get("start_date", ""))).strip()[:80],
        })
    return seasons


def parse_daily_result(text: str, fallback_sources: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Liest Fakten ein; Kategorie und Restfolgen bestimmt danach ausschließlich Python."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except ValueError:
        return {"series_status": []}
    rows = payload.get("series_status", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    fallback_source = (fallback_sources or [""])[0]
    series_status: list[dict[str, Any]] = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()[:120]
        if not title:
            continue
        provider = str(row.get("provider", "")).strip()[:120]
        availability = str(row.get("availability", "")).strip()[:180]
        detail = str(row.get("detail", "")).strip()[:360]
        source_url = str(row.get("source_url", "")).strip()[:500] or fallback_source
        series_ended = row.get("series_ended") is True
        end_officially_confirmed = row.get("end_officially_confirmed") is True
        final_season = clean_number(row.get("final_season"), 0)
        if not 0 < final_season <= 100:
            final_season = 0
        end_reason = str(row.get("end_reason", "")).strip()[:180]
        next_season_number = clean_number(row.get("next_season_number"), 0)
        if not next_season_number:
            match = re.search(r"staffel\s*(\d+)", str(row.get("next_season_expected", "")), re.IGNORECASE)
            next_season_number = int(match.group(1)) if match else 0
        next_season_confirmed = row.get("next_season_confirmed") is True or bool(re.search(
            r"bestätigt|angekündigt|renewed|ordered", str(row.get("next_season_expected", "")), re.IGNORECASE
        ))
        next_season_start = str(row.get("next_season_start", "")).strip()[:100]
        if not next_season_start:
            expected = str(row.get("next_season_expected", "")).strip()[:180]
            if parse_known_date(expected) or re.search(r"\b20\d{2}\b", expected):
                next_season_start = expected
        series_status.append({
            "title": title, "provider": provider, "availability": availability, "detail": detail,
            "source_url": source_url, "series_ended": series_ended,
            "end_officially_confirmed": end_officially_confirmed, "final_season": final_season,
            "end_reason": end_reason, "next_season_number": next_season_number,
            "next_season_confirmed": next_season_confirmed, "next_season_start": next_season_start,
            "next_season_expected": str(row.get("next_season_expected", "")).strip()[:180],
            "next_episode": str(row.get("next_episode", "")).strip()[:180],
            "estimated_complete": str(row.get("estimated_complete", "")).strip()[:180],
            "seasons": clean_seasons(row.get("seasons")), "poster_url": "",
            "legacy_release_status": str(row.get("release_status", "")).strip(),
            "legacy_available": str(row.get("available", "")).strip()[:180],
            "legacy_remaining": str(row.get("remaining", "")).strip()[:180],
        })
    return {"series_status": series_status}


def _season_counts(row: dict[str, Any]) -> tuple[int | None, int | None]:
    parsed_available, parsed_total = parse_episode_counts(row.get("episodes"))
    return (optional_episode_count(row.get("available_episodes"), parsed_available),
            optional_episode_count(row.get("total_episodes"), parsed_total))


def _is_unseen_available(season: dict[str, Any], watched_season: int, watched_episode: int) -> bool:
    number = season_number(season.get("season")) or 0
    available, _total = _season_counts(season)
    if watched_episode > 0 and number == watched_season:
        if available is not None:
            return available > watched_episode
        return str(season.get("state", "unknown")) in {"streamable", "ongoing"}
    return number > watched_season


def estimate_season_finale_date(season: dict[str, Any]) -> date | None:
    """Ermittelt transparent ein Enddatum, wenn ein Episodenplan noch kein Finale nennt.

    Ein bestätigtes Finale wird immer bevorzugt. Diese Schätzung greift nur bei
    laufenden deutschen Staffeln mit bekannter Restfolgenzahl und nächstem Termin.
    Ohne Rhythmus liefert Gemini ihn mit; als klar gekennzeichneter Fallback gilt
    der übliche wöchentliche Veröffentlichungsrhythmus.
    """
    available, total = _season_counts(season)
    next_episode = parse_known_date(season.get("next_episode_date"))
    if available is None or total is None or total <= available or not next_episode:
        return None
    cadence = optional_episode_count(season.get("release_cadence_days")) or 7
    batch_size = optional_episode_count(season.get("episodes_per_release")) or 1
    if cadence > 31 or batch_size > 20:
        return None
    remaining = total - available
    releases_left = (remaining + batch_size - 1) // batch_size
    return next_episode + timedelta(days=cadence * max(0, releases_left - 1))




def _format_de_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _season_by_number(row: dict[str, Any], number: int) -> dict[str, Any] | None:
    for season in row.get("seasons", []):
        if isinstance(season, dict) and season_number(season.get("season")) == number:
            return season
    return None


def _apply_known_episode_guardrails(row: dict[str, Any], today: date) -> list[str]:
    """Korrigiert nur belastbar bekannte deutsche Episodenplaene.

    Gemini bleibt die primaere Recherche. Fuer 9-1-1 S9 ist der komplette
    deutsche Disney+-Terminplan bereits veroeffentlicht; fuer Chicago Med S11
    ist die Staffelorder mit 21 Folgen belastbar. Dadurch koennen US-Release
    bzw. fehlende Gesamtzahlen die App nicht erneut falsch einsortieren.
    """
    warnings: list[str] = []
    title = str(row.get("title", "")).strip().lower()

    if title == "9-1-1":
        season = _season_by_number(row, 9)
        if season is None:
            season = {
                "season": "9", "state": "unknown", "episodes": "",
                "available_episodes": None, "total_episodes": 18,
                "complete": False, "gemini_complete_hint": False,
                "provider": "Disney+", "availability": "",
                "next_episode_date": "", "start_date": _format_de_date(KNOWN_911_S9_DE_RELEASES[0]),
            }
            row.setdefault("seasons", []).append(season)
            warnings.append("Staffel 9: deutscher Episodenplan ergaenzt")

        old_available, old_total = _season_counts(season)
        old_next = str(season.get("next_episode_date") or "")
        released = sum(1 for release_date in KNOWN_911_S9_DE_RELEASES if release_date <= today)
        next_release = next((release_date for release_date in KNOWN_911_S9_DE_RELEASES if release_date > today), None)
        season["total_episodes"] = len(KNOWN_911_S9_DE_RELEASES)
        season["start_date"] = _format_de_date(KNOWN_911_S9_DE_RELEASES[0])
        season["season_finale_date"] = _format_de_date(KNOWN_911_S9_DE_RELEASES[-1])
        season["provider"] = "Disney+"

        if released <= 0:
            season["available_episodes"] = None
            season["complete"] = False
            season["state"] = "upcoming"
            season["next_episode_date"] = _format_de_date(KNOWN_911_S9_DE_RELEASES[0])
            season["episodes"] = "Deutsch: Staffel 9 startet am 18.03.2026"
            row["detail"] = "Staffel 9 startet am 18.03.2026 auf Deutsch bei Disney+."
        elif released < len(KNOWN_911_S9_DE_RELEASES):
            season["available_episodes"] = released
            season["complete"] = False
            season["state"] = "ongoing"
            season["next_episode_date"] = _format_de_date(next_release) if next_release else ""
            season["episodes"] = f"Deutsch: Folgen 1–{released} von {len(KNOWN_911_S9_DE_RELEASES)}"
            row["detail"] = (f"Staffel 9 laeuft auf Deutsch bei Disney+; bis einschliesslich heute "
                             f"sind {released} von {len(KNOWN_911_S9_DE_RELEASES)} Folgen veroeffentlicht.")
        else:
            season["available_episodes"] = len(KNOWN_911_S9_DE_RELEASES)
            season["complete"] = True
            season["state"] = "streamable"
            season["next_episode_date"] = ""
            season["episodes"] = "Deutsch: Folgen 1–18 von 18"
            row["detail"] = "Staffel 9 ist auf Deutsch bei Disney+ vollstaendig verfuegbar."

        row["provider"] = "Disney+"
        row["source_url"] = "https://www.fernsehserien.de/9-1-1-notruf-l-a/episodenguide/staffel-9/38522"
        new_available, new_total = _season_counts(season)
        new_next = str(season.get("next_episode_date") or "")
        if (old_available, old_total, old_next) != (new_available, new_total, new_next):
            warnings.append("Staffel 9: deutscher Disney+-Episodenplan hat abweichende Gemini-Daten korrigiert")

    elif title == "chicago p.d.":
        # Staffel 12 ist in Deutschland abgeschlossen (22/22; Finale 01.07.2026).
        # Staffel 13 beginnt erst am 02.09.2026. Damit können Wiederholungsdaten
        # oder US-Termine S12 nicht erneut fälschlich zu "laufend" machen.
        season12 = _season_by_number(row, 12)
        if season12 is None:
            season12 = {
                "season": "12", "state": "streamable", "episodes": "Deutsch: Folgen 1–22 von 22",
                "available_episodes": KNOWN_CHICAGO_PD_S12_TOTAL,
                "total_episodes": KNOWN_CHICAGO_PD_S12_TOTAL, "complete": True,
                "gemini_complete_hint": False, "provider": "AXN Black", "availability": "",
                "next_episode_date": "", "start_date": "",
            }
            row.setdefault("seasons", []).append(season12)
            warnings.append("Staffel 12: abgeschlossener deutscher Staffelstand ergänzt")
        old12 = (_season_counts(season12), str(season12.get("next_episode_date") or ""), str(season12.get("state") or ""))
        season12["available_episodes"] = KNOWN_CHICAGO_PD_S12_TOTAL
        season12["total_episodes"] = KNOWN_CHICAGO_PD_S12_TOTAL
        season12["complete"] = True
        season12["state"] = "streamable"
        season12["next_episode_date"] = ""
        season12["episodes"] = "Deutsch: Folgen 1–22 von 22"
        season12["provider"] = "AXN Black"
        if old12 != ((_season_counts(season12)), "", "streamable"):
            warnings.append("Staffel 12: deutscher Abschluss 22/22 hat abweichende Gemini-Daten korrigiert")

        season13 = _season_by_number(row, 13)
        if today < KNOWN_CHICAGO_PD_S13_DE_START:
            if season13 is None:
                season13 = {
                    "season": "13", "state": "upcoming", "episodes": "Deutsch: Start 02.09.2026",
                    "available_episodes": None, "total_episodes": None, "complete": False,
                    "gemini_complete_hint": False, "provider": "AXN Black", "availability": "",
                    "next_episode_date": "", "start_date": _format_de_date(KNOWN_CHICAGO_PD_S13_DE_START),
                }
                row.setdefault("seasons", []).append(season13)
            season13["available_episodes"] = None
            season13["complete"] = False
            season13["state"] = "upcoming"
            season13["start_date"] = _format_de_date(KNOWN_CHICAGO_PD_S13_DE_START)
            season13["next_episode_date"] = ""
            season13["provider"] = "AXN Black"
        row["next_season_confirmed"] = True
        row["next_season_number"] = 13
        row["next_season_start"] = _format_de_date(KNOWN_CHICAGO_PD_S13_DE_START)
        row["provider"] = "AXN Black"
        row["source_url"] = "https://www.fernsehserien.de/chicago-pd/episodenguide/staffel-12/22161"

    elif title == "fire country":
        season = _season_by_number(row, 4)
        if season is not None:
            _available, old_total = _season_counts(season)
            if old_total != KNOWN_FIRE_COUNTRY_S4_TOTAL:
                season["total_episodes"] = KNOWN_FIRE_COUNTRY_S4_TOTAL
                available, _ = _season_counts(season)
                if available is not None:
                    season["episodes"] = f"Deutsch: Folgen 1–{available} von {KNOWN_FIRE_COUNTRY_S4_TOTAL}"
                warnings.append("Staffel 4: belastbare Gesamtfolgenzahl 20 ergänzt")
            season["season_finale_date"] = _format_de_date(KNOWN_FIRE_COUNTRY_S4_DE_FINALE)
            if not row.get("source_url"):
                row["source_url"] = "https://www.fernsehserien.de/fire-country/episodenguide/staffel-4/52804"

    elif title == "chicago med":
        season = _season_by_number(row, 11)
        if season is not None:
            _available, old_total = _season_counts(season)
            if old_total != KNOWN_CHICAGO_MED_S11_TOTAL:
                season["total_episodes"] = KNOWN_CHICAGO_MED_S11_TOTAL
                available, _ = _season_counts(season)
                if available is not None:
                    season["episodes"] = f"Deutsch: Folgen 1–{available} von {KNOWN_CHICAGO_MED_S11_TOTAL}"
                warnings.append("Staffel 11: belastbare Gesamtfolgenzahl 21 ergaenzt")
            season["season_finale_date"] = _format_de_date(KNOWN_CHICAGO_MED_S11_DE_FINALE)
            if not row.get("source_url"):
                row["source_url"] = "https://www.fernsehserien.de/chicago-med/episodenguide/staffel-11/30857"

    elif title == "chicago fire":
        season = _season_by_number(row, 14)
        if season is not None:
            _available, old_total = _season_counts(season)
            if old_total != KNOWN_CHICAGO_FIRE_S14_TOTAL:
                season["total_episodes"] = KNOWN_CHICAGO_FIRE_S14_TOTAL
                available, _ = _season_counts(season)
                if available is not None:
                    season["episodes"] = f"Deutsch: Folgen 1–{available} von {KNOWN_CHICAGO_FIRE_S14_TOTAL}"
                warnings.append("Staffel 14: belastbare Gesamtfolgenzahl 21 ergänzt")
            season["season_finale_date"] = _format_de_date(KNOWN_CHICAGO_FIRE_S14_DE_FINALE)
            if not row.get("source_url"):
                row["source_url"] = "https://www.fernsehserien.de/chicago-fire/episodenguide/staffel-14/18788"

    return warnings


def _validate_facts(row: dict[str, Any], today: date) -> list[str]:
    warnings: list[str] = _apply_known_episode_guardrails(row, today)
    for season in row.get("seasons", []):
        if not isinstance(season, dict):
            continue
        available, total = _season_counts(season)
        start = parse_known_date(season.get("start_date"))
        next_date = parse_known_date(season.get("next_episode_date"))
        future_start = bool(start and start > today)
        if future_start:
            if available is not None or season.get("gemini_complete_hint") or season.get("state") == "ongoing":
                warnings.append(f"Staffel {season.get('season')}: Start liegt in der Zukunft – als angekündigt korrigiert")
            season["available_episodes"] = None
            season["complete"] = False
            season["state"] = "upcoming"
            continue
        if available is not None and total is not None and available > total:
            warnings.append(f"Staffel {season.get('season')}: Folgenzahl widersprüchlich – begrenzt")
            available = total
            season["available_episodes"] = total
        future_next = bool(next_date and next_date > today)
        # Ein zukünftiger deutscher Folgentermin widerspricht einem vollständigen
        # deutschen Staffelstand. In diesem Konflikt verwerfen wir lieber die
        # behauptete verfügbare Folgenzahl als fälschlich "komplett" zu melden.
        if future_next and available is not None and total is not None and available >= total:
            warnings.append(f"Staffel {season.get('season')}: deutscher Folgetermin liegt noch in der Zukunft – Vollständigkeit verworfen")
            season["available_episodes"] = None
            available = None
        strict_complete = bool(available is not None and total is not None and available == total and total > 0 and not future_next)
        if strict_complete:
            season["complete"] = True
            if season.get("state") != "seen":
                season["state"] = "streamable"
        else:
            if season.get("gemini_complete_hint"):
                if available is None or total is None:
                    warnings.append(f"Staffel {season.get('season')}: 'komplett' ohne belegte Folgenzahlen verworfen")
                elif available < total:
                    warnings.append(f"Staffel {season.get('season')}: 'komplett' widersprach {available}/{total} – korrigiert")
            season["complete"] = False
        if not strict_complete:
            if future_next:
                season["state"] = "ongoing"
            elif available is not None and total is not None and 0 < available < total:
                season["state"] = "ongoing"
            elif season.get("state") == "ongoing" and available is None:
                warnings.append(f"Staffel {season.get('season')}: läuft laut Quelle, verfügbare Folgenzahl aber unbekannt")
        if season.get("state") == "upcoming" and available is not None:
            warnings.append(f"Staffel {season.get('season')}: bereits Folgen verfügbar – nicht mehr nur angekündigt")
            season["state"] = "streamable" if strict_complete else "ongoing"
    if row.get("series_ended") and row.get("next_season_confirmed"):
        warnings.append("Serienende widersprach einer bestätigten Folgestaffel – Serienende verworfen")
        row["series_ended"] = False
        row["end_officially_confirmed"] = False
        row["final_season"] = 0
    if row.get("series_ended") and not row.get("end_officially_confirmed"):
        warnings.append("Serienende war nicht offiziell belegt – nicht archiviert")
    return warnings


def _placeholder_for_active(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("name", "")), "provider": "", "availability": "",
        "detail": "Für diese Serie liegt aus der letzten Prüfung noch kein belastbarer neuer Faktenstand vor.",
        "source_url": "", "series_ended": False, "end_officially_confirmed": False,
        "final_season": 0, "end_reason": "", "next_season_number": 0,
        "next_season_confirmed": False, "next_season_start": "",
        "next_season_expected": "Noch nicht neu geprüft", "next_episode": "",
        "estimated_complete": "", "seasons": [], "poster_url": "",
        "available": "Noch nicht neu geprüft", "remaining": "",
        "release_status": "nothing_new", "state": "nothing_new",
        "warnings": ["Keine aktuelle Gemini-Antwort"], "checked_at": "",
    }


def ensure_active_placeholders(result: dict[str, Any], active: list[dict[str, Any]]) -> None:
    if not result.get("series_status"):
        return
    present = {str(row.get("title", "")) for row in result.get("series_status", []) if isinstance(row, dict)}
    for item in active:
        title = str(item.get("name", ""))
        if title and title not in present:
            result.setdefault("series_status", []).append(_placeholder_for_active(item))


def merge_previous_verified_facts(new_row: dict[str, Any], old_row: dict[str, Any] | None) -> None:
    """Bewahrt stabile deutsche Fakten und verhindert rückwärts laufende Staffeln.

    Ein deutscher Staffelstand ist monoton: Wurde eine Staffel bereits mit
    belegten x/x Folgen als vollständig ausgestrahlt erkannt, kann ein späterer
    Gemini-Lauf dieselbe Staffel nicht wieder auf weniger Folgen oder "laufend"
    zurücksetzen. Eine *neuere* Staffel darf natürlich weiterhin ongoing sein.
    """
    if not isinstance(old_row, dict):
        return
    today = datetime.now().date()
    old_seasons = {season_number(x.get("season")): x for x in old_row.get("seasons", [])
                   if isinstance(x, dict) and season_number(x.get("season"))}
    new_seasons = {season_number(x.get("season")): x for x in new_row.get("seasons", [])
                   if isinstance(x, dict) and season_number(x.get("season"))}

    def old_is_verified_complete(old: dict[str, Any]) -> bool:
        old_available, old_total = _season_counts(old)
        old_next = parse_known_date(old.get("next_episode_date"))
        return bool(old_available is not None and old_total is not None and old_total > 0
                    and old_available == old_total
                    and not (old_next and old_next > today)
                    and (old.get("complete") is True or str(old.get("state", "")) in {"streamable", "seen"}))

    # Fehlt eine früher bereits vollständig belegte Staffel in einer schwächeren
    # Antwort ganz, bleibt sie erhalten. Das betrifft nur Fakten, nie den Sehstand.
    for number, old in old_seasons.items():
        if number not in new_seasons and old_is_verified_complete(old):
            copied = json.loads(json.dumps(old))
            copied["complete"] = True
            if copied.get("state") != "seen":
                copied["state"] = "streamable"
            copied["next_episode_date"] = ""
            new_row.setdefault("seasons", []).append(copied)
            new_seasons[number] = copied

    for season in new_row.get("seasons", []):
        if not isinstance(season, dict):
            continue
        number = season_number(season.get("season"))
        old = old_seasons.get(number)
        if not old:
            continue
        available, total = _season_counts(season)
        old_available, old_total = _season_counts(old)
        if total is None and old_total is not None:
            season["total_episodes"] = old_total
            total = old_total
        if not season.get("start_date") and old.get("start_date"):
            season["start_date"] = old.get("start_date")
        if not season.get("provider") and old.get("provider"):
            season["provider"] = old.get("provider")

        # Bereits vollständig auf Deutsch ausgestrahlt darf nicht wieder schrumpfen.
        if old_is_verified_complete(old) and old_total is not None:
            if available is None or available < old_total or total != old_total or str(season.get("state")) == "ongoing":
                season["available_episodes"] = old_total
                season["total_episodes"] = old_total
                season["complete"] = True
                if season.get("state") != "seen":
                    season["state"] = "streamable"
                season["next_episode_date"] = ""
                season["episodes"] = f"Deutsch: Folgen 1–{old_total} von {old_total}"

    if not new_row.get("next_season_confirmed") and old_row.get("next_season_confirmed"):
        old_number = clean_number(old_row.get("next_season_number"), 0)
        if old_number:
            new_row["next_season_confirmed"] = True
            new_row["next_season_number"] = old_number
            new_row["next_season_start"] = str(old_row.get("next_season_start") or "")
            new_row["next_season_expected"] = str(old_row.get("next_season_expected") or "")


def normalize_for_watch_progress(result: dict[str, Any], active: list[dict[str, Any]]) -> None:
    """Gemini liefert Fakten; Python entscheidet Kategorie, Restzahl und Darstellung."""
    by_title = {str(item.get("name", "")): item for item in active}
    today = datetime.now().date()
    for row in result.get("series_status", []):
        if not isinstance(row, dict):
            continue
        own = by_title.get(str(row.get("title", "")))
        if not own:
            continue
        warnings = _validate_facts(row, today)
        watched_season = clean_number(own.get("season"), 0)
        watched_episode = clean_number(own.get("episode"), 0)
        open_seasons = [x for x in row.get("seasons", []) if isinstance(x, dict) and _is_unseen_available(x, watched_season, watched_episode)]
        complete_rows, ongoing_rows, upcoming_rows, uncertain_rows = [], [], [], []
        for season in open_seasons:
            available, total = _season_counts(season)
            state = str(season.get("state", "unknown"))
            start = parse_known_date(season.get("start_date"))
            next_date = parse_known_date(season.get("next_episode_date"))
            is_complete = bool(available is not None and total is not None and available == total and total > 0 and not (next_date and next_date > today))
            if is_complete:
                complete_rows.append(season)
            elif start and start > today or state == "upcoming":
                upcoming_rows.append(season)
            elif state == "ongoing" or (available is not None and total is not None and 0 < available < total) or (available is not None and next_date and next_date > today):
                ongoing_rows.append(season)
            elif state == "streamable" and available is not None:
                uncertain_rows.append(season)
        # Eine belegte zukünftige Staffel bleibt als Zusatzinformation erhalten,
        # auch wenn aktuell ältere Staffeln komplett zum Nachholen bereitstehen.
        if upcoming_rows:
            future = max(upcoming_rows, key=lambda x: season_number(x.get("season")) or 0)
            future_number = season_number(future.get("season")) or 0
            if future_number and (not row.get("next_season_confirmed") or future_number >= clean_number(row.get("next_season_number"), 0)):
                row["next_season_confirmed"] = True
                row["next_season_number"] = future_number
                if future.get("start_date"):
                    row["next_season_start"] = str(future.get("start_date"))
        if ongoing_rows:
            primary = max(ongoing_rows, key=lambda x: season_number(x.get("season")) or 0); status = "ongoing"
        elif complete_rows:
            primary = min(complete_rows, key=lambda x: season_number(x.get("season")) or 999); status = "complete"
        elif upcoming_rows or row.get("next_season_confirmed"):
            primary = min(upcoming_rows, key=lambda x: season_number(x.get("season")) or 999) if upcoming_rows else None; status = "upcoming"
        elif uncertain_rows:
            primary = min(uncertain_rows, key=lambda x: season_number(x.get("season")) or 999); status = "nothing_new"
            warnings.append("Neue Folgen sind verfügbar, aber die Vollständigkeit ist noch nicht belastbar bestätigt")
        elif row.get("series_ended") and row.get("end_officially_confirmed") and row.get("final_season") and (watched_season < int(row.get("final_season") or 0) or watched_episode > 0):
            primary = None; status = "complete"
        else:
            primary = None; status = "nothing_new"
        parts = []
        for season in sorted(complete_rows, key=lambda x: season_number(x.get("season")) or 999):
            number = season_number(season.get("season"))
            if not number: continue
            parts.append(f"Staffel {number} ab Folge {watched_episode + 1} verfügbar" if number == watched_season and watched_episode > 0 else f"Staffel {number} komplett")
        if status == "ongoing" and primary:
            number = season_number(primary.get("season")) or "?"
            available, total = _season_counts(primary)
            if available is not None and total is not None: parts.append(f"Staffel {number} · {available}/{total} Folgen verfügbar")
            elif available is not None: parts.append(f"Staffel {number} · {available} Folgen verfügbar")
            else: parts.append(f"Staffel {number} läuft gerade")
        elif uncertain_rows and status == "nothing_new":
            number = season_number(primary.get("season")) if primary else None
            available, _ = _season_counts(primary or {})
            if number and available is not None: parts.append(f"Staffel {number} · {available} Folgen verfügbar · Vollständigkeit unklar")
        row["available"] = " · ".join(dict.fromkeys(parts)) if parts else ("Aktuell nichts Neues verfügbar" if status in {"upcoming", "nothing_new"} else str(row.get("legacy_available") or "Offene Folgen verfügbar"))
        row["release_status"] = status
        row["state"] = "new" if status in {"complete", "ongoing"} else status
        if primary:
            if primary.get("provider"): row["provider"] = primary.get("provider")
            if primary.get("availability"): row["availability"] = primary.get("availability")
        if status == "ongoing" and primary:
            available, total = _season_counts(primary)
            row["remaining"] = f"noch {max(0, total - available)} Folgen" if available is not None and total is not None and available <= total else "Anzahl noch nicht belastbar bekannt"
            next_text = str(primary.get("next_episode_date") or "").strip()
            if next_text: row["next_episode"] = f"Nächste Folge am {next_text}" if not re.search(r"folge", next_text, re.I) else next_text
            finale_text = str(primary.get("season_finale_date") or "").strip()
            finale_date = parse_known_date(finale_text)
            if finale_date and finale_date >= today:
                row["estimated_complete"] = f"Staffel fertig am {finale_text}"
                row["completion_type"] = "confirmed"
            else:
                predicted_finale = estimate_season_finale_date(primary)
                if predicted_finale and predicted_finale >= today:
                    row["estimated_complete"] = f"Staffel fertig am {_format_de_date(predicted_finale)}"
                    row["completion_type"] = "estimated"
                else:
                    # Freie alte Schätztexte dürfen kein neues Staffelfinale vortäuschen.
                    row["estimated_complete"] = ""
                    row["completion_type"] = ""
        elif status == "complete":
            row["remaining"] = "Komplette Staffel verfügbar" if len(complete_rows) <= 1 else "Komplette Staffeln verfügbar"
        else:
            row["remaining"] = "keine neue Folge"
        if row.get("next_season_confirmed") and row.get("next_season_number"):
            suffix = f" · {row.get('next_season_start')}" if row.get("next_season_start") else ""
            row["next_season_expected"] = f"Staffel {row.get('next_season_number')} bestätigt{suffix}"
        elif not row.get("next_season_expected"):
            row["next_season_expected"] = "Noch keine neue Staffel angekündigt"
        if status != "ongoing":
            row["next_episode"] = ""
            row["estimated_complete"] = ""
            row["completion_type"] = ""
        if warnings or not row.get("detail"):
            row["detail"] = {"ongoing":"Die aktuell relevante deutsche Staffel läuft weiter; Folgenzahl und Termine werden aus den belegten Episodendaten berechnet.","complete":"Mindestens eine von euch noch offene Staffel ist vollständig auf Deutsch verfügbar.","upcoming":"Ihr seid aktuell auf Stand; eine weitere Staffel ist bestätigt oder angekündigt.","nothing_new":"Ihr seid aktuell auf Stand; derzeit ist keine weitere deutsche Staffel belastbar vollständig verfügbar."}[status]
        row["warnings"] = list(dict.fromkeys(warnings))[:5]
        row["checked_at"] = datetime.now().strftime("%d.%m. %H:%M")


def add_posters(result: dict[str, list[dict[str, Any]]]) -> None:
    """Poster nur für Serienkarten nachladen; Empfehlungen gibt es nicht mehr."""
    for row in result.get("series_status", []):
        if isinstance(row, dict) and row.get("title") and row.get("release_status") in {"complete", "ongoing"}:
            row["poster_url"] = poster_url(str(row["title"]))


def check_is_active(request_id: str) -> bool:
    expire_stale_check()
    with store.lock:
        daily = store.data.get("daily_check", {})
        return bool(daily.get("check_running") and daily.get("request_id") == request_id)


def cancel_daily_check() -> bool:
    """Blendet eine laufende Prüfung sofort aus; ein späteres Ergebnis wird verworfen."""
    with store.lock:
        daily = store.data.setdefault("daily_check", {})
        if not daily.get("check_running"):
            return False
        daily.update({"check_running": False, "request_id": None,
                      "started_at": None, "error": "Prüfung abgebrochen",
                      "last_check_kind": "abgebrochen"})
        store.save()
    gemini_log("Prüfung wurde über die Oberfläche abgebrochen.")
    return True


def archive_finished_series(result: dict[str, Any]) -> list[str]:
    """Archiviert erst nach zwei getrennten Checks mit offiziell belegtem Serienende."""
    archived = []
    candidates = {str(r.get("title", "")): r for r in result.get("series_status", []) if isinstance(r, dict) and r.get("series_ended") and r.get("end_officially_confirmed") and r.get("final_season") and str(r.get("source_url", "")).startswith("https://")}
    today_key = datetime.now().date().isoformat()
    with store.lock:
        confirmations = store.data.setdefault("series_end_confirmations", {})
        for title in list(confirmations):
            if title not in candidates: confirmations.pop(title, None)
        for title, update in candidates.items():
            final_season = int(update.get("final_season") or 0)
            existing = confirmations.get(title) if isinstance(confirmations.get(title), dict) else {}
            count = int(existing.get("count") or 0) if int(existing.get("final_season") or 0) == final_season else 0
            if str(existing.get("last_date") or "") != today_key: count += 1
            confirmations[title] = {"final_season": final_season, "count": count, "last_date": today_key}
        for series in store.data.get("series", []):
            if not isinstance(series, dict) or series.get("status") != "watching": continue
            title = str(series.get("name", "")); update = candidates.get(title); confirmation = confirmations.get(title, {}) if update else {}
            if not update or int(confirmation.get("count") or 0) < 2: continue
            if int(series.get("episode", 0) or 0) != 0: continue
            if int(series.get("season", 0) or 0) < int(update["final_season"]): continue
            series["status"] = "cancelled"
            existing_note = str(series.get("note", "")).strip(); ending = str(update.get("end_reason", "")).strip() or "Serie offiziell beendet."
            if "Serie offiziell beendet" not in existing_note: series["note"] = f"{existing_note} · {ending}".strip(" ·")
            archived.append(title)
        store.save()
    return archived


def watched_label(item: dict[str, Any]) -> str:
    episode = int(item.get("episode", 0) or 0)
    if episode:
        return f"{item.get('name')} (gesehen bis Staffel {item.get('season')} Folge {episode})"
    return f"{item.get('name')} (gesehen bis Staffel {item.get('season')} komplett)"


def build_single_series_prompt(today: str, item: dict[str, Any], focus_finale: bool = False) -> str:
    """Eine Serie pro Interaction; strikt auf deutsche Veröffentlichung fokussiert."""
    title = str(item.get("name", "")).strip()
    special = ""
    lower = title.lower()
    if lower == "family law":
        special = ("Family Law meint die kanadische Serie von 2021 mit Jewel Staite auf Global. "
                   "Nicht als beendet markieren, solange kein belastbarer offizieller End-/Absetzungsbeleg von Sender/Produktion oder einer seriösen Branchenquelle vorliegt.")
    elif lower == "will trent":
        special = "Eine bestätigte zukünftige Staffel darf niemals als bereits streambar oder vollständig bezeichnet werden."
    elif lower == "9-1-1":
        special = ("Besonders wichtig bei 9-1-1: Ein bereits abgeschlossenes US/ABC/Hulu-Release ist KEIN Beleg für vollständige deutsche Verfügbarkeit. "
                   "Zähle ausschließlich deutsche Veröffentlichungen bis heute; ein zukünftiger deutscher Folgentermin bedeutet zwingend ongoing und german_available_episodes < german_total_episodes.")
    elif lower == "chicago med":
        special = ("Bei der aktuell laufenden deutschen Staffel die Gesamtfolgenzahl ausdrücklich aus einem Episodenguide/Staffelorder belegen. "
                   "Wenn german_available_episodes bekannt ist, german_total_episodes nicht vorschnell null lassen, solange die zweite Suche eine belastbare Gesamtzahl liefern kann.")
    elif lower == "chicago p.d.":
        special = ("Chicago P.D. Staffel 12 ist in Deutschland bereits vollständig ausgestrahlt; das deutsche Staffelfinale Folge 22 lief am 01.07.2026 bei AXN Black. "
                   "Nicht mit Wiederholungen oder einer anderen Staffel verwechseln. Staffel 13 startet erst am 02.09.2026 und ist bis dahin upcoming. Diese Zukunftsstaffel als next_season_* mitliefern.")
    elif lower == "fire country":
        special = ("Fire Country Staffel 4 hat insgesamt 20 Folgen. Für german_available_episodes ausschließlich die bis heute auf Deutsch ausgestrahlten/gestreamten Folgen zählen; "
                   "die US-Gesamtzahl 20 darf nicht auf 16 verkürzt werden.")
    elif lower == "the rookie":
        special = "Eine bestätigte zukünftige Folgestaffel samt Startdatum/Zeitraum als next_season_* unbedingt mitliefern; sie darf durch ältere komplett verfügbare Staffeln nicht verloren gehen."
    finale_focus = """
EINZELPRÜFUNG ZUM STAFFELFINALE: Diese Prüfung wurde ausdrücklich für diese eine Serienkarte gestartet.
Nutze zuerst einen deutschen Episodenguide oder einen Sender-/Anbieterplan für die aktuell laufende offene Staffel und ermittle den Sendetermin der LETZTEN Episode. Suche danach gezielt nach genau diesem Staffelfinale bei einer zweiten unabhängigen deutschen Quelle. Wenn ein Datum bestätigt ist, MUSS es als german_season_finale_date im Format TT.MM.JJJJ zurückkommen. Ist kein exakter deutscher Termin veröffentlicht, bleibt das Feld leer – niemals aus Restfolgen oder einem Wochenrhythmus hochrechnen.
""" if focus_finale else ""
    max_searches = 3 if focus_finale else 2
    return f'''Heute ist {today}. Prüfe mit Google Search spoilerfrei genau diese eine Serie: {watched_label(item)}.
Nutze maximal {max_searches} Google-Suchen und trenne DEUTSCHEN Veröffentlichungsstand strikt von US/Originalausstrahlung:
1. ZUERST deutscher Episodenguide/Streamingstand ab dem persönlichen Sehstand. Bevorzuge konkrete deutsche Episoden- und Sendetermine (Anbieter, fernsehserien.de, Wunschliste). Ermittle für jede relevante Staffel german_total_episodes und german_available_episodes = Anzahl der Folgen, die BIS EINSCHLIESSLICH HEUTE tatsächlich auf Deutsch veröffentlicht/ausgestrahlt wurden. Original-/US-Verfügbarkeit darf hierfür niemals gezählt werden. Ermittle german_start_date, den nächsten bestätigten german_next_episode_date > heute und bei einer laufenden Staffel auch das bestätigte deutsche german_season_finale_date der letzten Folge, sofern veröffentlicht. Liefere bei einer laufenden Staffel ZUSÄTZLICH german_release_cadence_days und german_episodes_per_release aus dem deutschen Plan (z. B. 7 und 1 für wöchentlich eine Folge, 7 und 2 für wöchentlich zwei Folgen). Diese beiden Werte sind nötig, damit die App bei einem noch nicht veröffentlichten letzten Einzeltermin einen transparenten voraussichtlichen Endtermin berechnen kann.
2. Nutze die zweite Suche PRIORISIERT, falls bei einer laufenden Staffel german_total_episodes noch fehlt. Wenn die Folgenzahlen schon belastbar sind, nutze sie für bestätigte Folgestaffel/deren Start bzw. ein offiziell belegtes Serienende.
{finale_focus}
Keine Empfehlungen. Keine Spoiler. Lieber null/unknown als raten oder eine weitere Suche.
Der persönliche Sehstand ist verbindlich und darf nie verändert werden.
WICHTIG: Liefere Fakten, NICHT die endgültige App-Kategorie. Python entscheidet danach selbst.
Plausibilität:
- german_available_episodes, german_total_episodes, german_release_cadence_days und german_episodes_per_release sind positive Zahlen oder null. Niemals 0 als Ersatz für unbekannt.
- complete=true NUR wenn german_available_episodes und german_total_episodes beide belastbar bekannt und exakt gleich sind UND es keinen zukünftigen deutschen Folgentermin gibt.
- Existiert german_next_episode_date > heute, ist die Staffel NICHT komplett; state=ongoing.
- Staffelstart in der Zukunft => state=upcoming, german_available_episodes=null, complete=false.
- state=ongoing nur wenn die deutsche Staffel bereits begonnen hat und noch Folgen fehlen.
- next_season_confirmed=true nur bei belastbar bestätigter Folgestaffel; bestätigte Zukunftsstaffeln auch dann liefern, wenn ältere Staffeln noch ungesehen sind.
- series_ended=true nur bei belastbar bestätigtem Ende/Absetzung ohne bestätigte weitere Staffel.
- end_officially_confirmed=true nur wenn der Endstatus ausdrücklich durch Sender/Produktion oder eine seriöse Branchenquelle belegt ist; bloß fehlende Verlängerung reicht NICHT.
- Eine ältere komplett verfügbare Staffel und eine neuere laufende/angekündigte Staffel dürfen gleichzeitig in seasons stehen.
{special}
Antworte ausschließlich als valides JSON, ohne Markdown:
{{"series_status":[{{"title":"{title}","provider":"deutscher Hauptanbieter oder unbekannt","availability":"bestätigtes Ablaufdatum oder Kein Ablaufdatum vom Anbieter veröffentlicht","detail":"ein kurzer spoilerfreier Faktensatz zum deutschen Stand","source_url":"https://beste-Hauptquelle","series_ended":false,"end_officially_confirmed":false,"final_season":0,"end_reason":"","next_season_number":null,"next_season_confirmed":false,"next_season_start":"TT.MM.JJJJ, Jahr/Zeitraum oder leer","seasons":[{{"season":13,"state":"streamable|ongoing|upcoming|not_streamable|unknown","german_available_episodes":13,"german_total_episodes":21,"german_release_cadence_days":7,"german_episodes_per_release":1,"complete":false,"episodes":"Deutsch: Folgen 1–13 von 21","provider":"deutscher Anbieter oder leer","availability":"Ablaufdatum oder leer","german_next_episode_date":"TT.MM.JJJJ oder leer","german_season_finale_date":"TT.MM.JJJJ oder leer","german_start_date":"TT.MM.JJJJ oder leer"}}]}}]}}.'''


def query_single_series(key: str, today: str, item: dict[str, Any], focus_finale: bool = False) -> list[dict[str, Any]]:
    payload = {
        "model": "gemini-3.6-flash",
        "input": build_single_series_prompt(today, item, focus_finale=focus_finale),
        "tools": [{"type": "google_search"}],
    }
    response_text, sources, meta = call_gemini_interaction(key, payload)
    gemini_log(f"{item.get('name')}: Gemini-Antwort ({meta}): {response_text[:1200] or 'kein Text'}")
    result = parse_daily_result(response_text, sources)
    return result.get("series_status", [])[:1]


def ha_request(path: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 20) -> Any:
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        HA_BASE + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def send_series_notification(title: str, message: str) -> bool:
    with store.lock:
        settings = dict(store.data.get("notification_settings", {}))
    if not settings.get("enabled", True):
        return False
    service_full = str(settings.get("notify_service") or DEFAULT_NOTIFY_SERVICE)
    if "." not in service_full:
        return False
    domain, service = service_full.split(".", 1)
    try:
        ha_request(f"/services/{domain}/{service}", method="POST", payload={"title": title, "message": message})
        return True
    except Exception as err:
        gemini_log(f"Push fehlgeschlagen: {type(err).__name__}: {err}")
        return False


def _event_facts(row: dict[str, Any], own: dict[str, Any] | None) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    title = str(row.get("title", "")).strip()
    if not title:
        return events
    watched_season = clean_number((own or {}).get("season"), 0)
    watched_episode = clean_number((own or {}).get("episode"), 0)
    complete_seasons: set[int] = set()
    started_seasons: set[int] = set()
    for season in row.get("seasons", []):
        if not isinstance(season, dict):
            continue
        number = season_number(season.get("season")) or 0
        if not number or not _is_unseen_available(season, watched_season, watched_episode):
            continue
        available, total = _season_counts(season)
        complete = bool(available is not None and total is not None and available == total and total > 0)
        start = parse_known_date(season.get("start_date"))
        if complete:
            complete_seasons.add(number)
        elif not (start and start > datetime.now().date()) and (available is not None or season.get("state") == "ongoing"):
            started_seasons.add(number)
    for number in sorted(complete_seasons):
        events.append({"key": f"{title}:season:{number}:complete", "type": "season_complete",
                       "title": f"✅ {title}", "message": f"Staffel {number} ist jetzt vollständig auf Deutsch verfügbar."})
    for number in sorted(started_seasons - complete_seasons):
        events.append({"key": f"{title}:season:{number}:started", "type": "season_started",
                       "title": f"▶️ {title}", "message": f"Staffel {number} ist auf Deutsch gestartet."})
    next_number = clean_number(row.get("next_season_number"), 0)
    if row.get("next_season_confirmed") and next_number:
        events.append({"key": f"{title}:season:{next_number}:confirmed", "type": "new_season_confirmed",
                       "title": f"🆕 {title}", "message": f"Staffel {next_number} wurde bestätigt."})
        if row.get("next_season_start"):
            start = str(row.get("next_season_start"))
            events.append({"key": f"{title}:season:{next_number}:start:{start}", "type": "start_date_known",
                           "title": f"📅 {title}", "message": f"Für Staffel {next_number} ist ein Start bekannt: {start}."})
    if row.get("series_ended") and row.get("end_officially_confirmed"):
        with store.lock:
            end_count = int((store.data.get("series_end_confirmations", {}).get(title) or {}).get("count") or 0)
        if end_count >= 2:
            events.append({"key": f"{title}:series-ended", "type": "series_ended",
                           "title": f"⛔ {title}", "message": str(row.get("end_reason") or "Die Serie ist offiziell beendet; es ist keine weitere Staffel bestätigt.")})
    return events


def process_notification_events(result: dict[str, Any], active: list[dict[str, Any]]) -> None:
    by_title = {str(item.get("name", "")): item for item in active}
    all_events: list[dict[str, str]] = []
    for row in result.get("series_status", []):
        if isinstance(row, dict):
            all_events.extend(_event_facts(row, by_title.get(str(row.get("title", "")))))
    with store.lock:
        seen = set(str(key) for key in store.data.setdefault("notified_event_keys", []))
        baseline_ready = bool(store.data.get("notification_baseline_ready"))
        settings = dict(store.data.get("notification_settings", {}))
        if not baseline_ready:
            seen.update(event["key"] for event in all_events)
            store.data["notified_event_keys"] = sorted(seen)[-1000:]
            store.data["notification_baseline_ready"] = True
            store.save()
            gemini_log(f"Push-Baseline gesetzt: {len(all_events)} bekannte Ereignisse, keine Alt-Pushs.")
            return
    with store.lock:
        end_confirmations = dict(store.data.get("series_end_confirmations", {}))
    filtered_events = []
    for event in all_events:
        if event.get("type") == "series_ended":
            raw_title = str(event.get("title", "")).replace("⛔ ", "", 1)
            if int((end_confirmations.get(raw_title) or {}).get("count") or 0) < 2:
                continue
        filtered_events.append(event)
    new_events = [event for event in filtered_events if event["key"] not in seen]
    history_rows: list[dict[str, str]] = []
    for event in new_events:
        enabled = bool(settings.get(event["type"], event["type"] != "start_date_known"))
        sent = send_series_notification(event["title"], event["message"]) if enabled else False
        history_rows.append({
            "at": datetime.now().isoformat(timespec="seconds"), "type": event["type"],
            "title": event["title"], "message": event["message"],
            "sent": "yes" if sent else ("disabled" if not enabled else "failed"),
        })
        seen.add(event["key"])
    if new_events:
        with store.lock:
            store.data["notified_event_keys"] = sorted(seen)[-1000:]
            history = store.data.setdefault("notification_history", [])
            history.extend(history_rows)
            store.data["notification_history"] = history[-100:]
            store.save()


def run_daily_check(manual: bool = False) -> bool:
    """Serie für Serie. Automatisch ausschließlich Dienstag und Freitag; manuell jederzeit."""
    today_date = datetime.now().date()
    today = today_date.isoformat()
    key = gemini_api_key()
    with store.lock:
        daily = store.data.setdefault("daily_check", {})
        last_automatic = daily.get("last_auto_run_date", daily.get("last_run_date"))
        if not key:
            gemini_log("Prüfung nicht gestartet: Gemini-Schlüssel fehlt.")
            return False
        if not manual and today_date.weekday() not in AUTO_CHECK_WEEKDAYS:
            return False
        if daily.get("check_running") or (not manual and last_automatic == today):
            return False
        request_id = uuid.uuid4().hex
        active = [item for item in store.data.get("series", []) if item.get("status") == "watching"][:MAX_SERIES_PER_CHECK]
        previous_status_by_title = {str(row.get("title", "")): json.loads(json.dumps(row))
                                    for row in daily.get("series_status", [])
                                    if isinstance(row, dict) and row.get("title")}
        daily.update({
            "check_running": True, "request_id": request_id, "started_at": time.time(),
            "last_checked_at": datetime.now().strftime("%d.%m. %H:%M"),
            "last_check_kind": "manuell" if manual else "automatisch", "error": None,
            "series_status": [], "archived": [], "progress_done": 0,
            "progress_total": len(active), "progress_current": "",
        })
        if not manual:
            daily.update({"last_auto_run_date": today, "last_run_date": today})
        store.save()
    gemini_log(f"{'Manuelle' if manual else 'Automatische'} Einzelprüfung gestartet: {len(active)} Serien, maximal {MAX_SERIES_PER_CHECK}.")
    collected: list[dict[str, Any]] = []
    last_error = ""
    failures = 0
    processed = 0
    for index, item in enumerate(active, start=1):
        title = str(item.get("name", "")).strip()
        stop_after_current = False
        if not check_is_active(request_id):
            gemini_log("Einzelprüfung nach Abbruch beendet.")
            return True
        with store.lock:
            daily = store.data.setdefault("daily_check", {})
            daily.update({"progress_done": index - 1, "progress_current": title})
            store.save()
        try:
            rows = query_single_series(key, today, item)
            if not rows:
                failures += 1
                last_error = f"{title}: keine verwertbare Antwort"
                stop_after_current = failures >= 3
            else:
                failures = 0
            for fresh in rows:
                if isinstance(fresh, dict):
                    merge_previous_verified_facts(fresh, previous_status_by_title.get(str(fresh.get("title", ""))))
            small_result = {"series_status": rows}
            normalize_for_watch_progress(small_result, [item])
            add_posters(small_result)
            rows = small_result["series_status"]
            failures = 0
        except urllib.error.HTTPError as err:
            try:
                detail = err.read().decode("utf-8", errors="replace")[:2000]
            except OSError:
                detail = "HTTP-Fehler ohne lesbaren Antworttext"
            last_error = f"{title}: HTTP {err.code}"
            gemini_log(f"{last_error} {err.reason}: {detail}")
            rows = []
            failures += 1
            stop_after_current = err.code in {401, 403, 429} or failures >= 3
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as err:
            last_error = f"{title}: {type(err).__name__}"
            gemini_log(f"{last_error}: {err}")
            rows = []
            failures += 1
            stop_after_current = failures >= 3
            if stop_after_current:
                gemini_log("Einzelprüfung nach drei Fehlern in Folge beendet, um weitere Anfragen zu sparen.")
        if not rows:
            previous = previous_status_by_title.get(title)
            if isinstance(previous, dict):
                previous = json.loads(json.dumps(previous))
                warnings = list(previous.get("warnings") or [])
                warnings.insert(0, "Aktualisierung fehlgeschlagen – letzter bestätigter Stand wird angezeigt")
                previous["warnings"] = list(dict.fromkeys(warnings))[:5]
                rows = [previous]
        if not check_is_active(request_id):
            gemini_log("Einzelprüfung nach Abbruch verworfen.")
            return True
        collected.extend(rows)
        processed = index
        with store.lock:
            daily = store.data.setdefault("daily_check", {})
            daily.update({"series_status": collected, "progress_done": index,
                          "progress_current": "" if index == len(active) else title})
            store.save()
        if stop_after_current:
            break
    result = {"series_status": collected}
    normalize_for_watch_progress(result, active)
    if check_is_active(request_id):
        archived = archive_finished_series(result)
        with store.lock:
            if check_is_active(request_id):
                daily = store.data.setdefault("daily_check", {})
                daily.update({
                    "series_status": result["series_status"], "archived": archived,
                    "check_running": False, "request_id": None, "started_at": None,
                    "progress_done": processed, "progress_total": len(active), "progress_current": "",
                    "error": None if collected else (last_error or "Keine verwertbare Gemini-Antwort"),
                    "needs_refresh": False if collected else bool(daily.get("needs_refresh")),
                })
                store.save()
        if collected:
            process_notification_events(result, active)
            if manual and today_date.weekday() in AUTO_CHECK_WEEKDAYS:
                # Ein erfolgreicher manueller Lauf am Dienstag/Freitag ersetzt den
                # noch ausstehenden Automatiklauf dieses Tages und verhindert Doppel-Kosten.
                with store.lock:
                    daily = store.data.setdefault("daily_check", {})
                    daily.update({"last_auto_run_date": today, "last_run_date": today})
                    store.save()
    gemini_log(f"Einzelprüfung beendet: {processed}/{len(active)} geprüft, {len(collected)} Ergebnisse gespeichert.")
    return True


def run_targeted_series_check(identifier: str) -> bool:
    """Prüft eine einzige aktive Serie mit zusätzlichem Fokus auf das deutsche Staffelfinale."""
    today = datetime.now().date().isoformat()
    key = gemini_api_key()
    with store.lock:
        daily = store.data.setdefault("daily_check", {})
        item = find_series(identifier)
        if not key or not item or item.get("status") != "watching" or daily.get("check_running"):
            return False
        request_id = uuid.uuid4().hex
        title = str(item.get("name", "")).strip()
        previous_rows = [json.loads(json.dumps(row)) for row in daily.get("series_status", []) if isinstance(row, dict)]
        previous_by_title = {str(row.get("title", "")): row for row in previous_rows if row.get("title")}
        daily.update({
            "check_running": True, "request_id": request_id, "started_at": time.time(),
            "last_checked_at": datetime.now().strftime("%d.%m. %H:%M"),
            "last_check_kind": "einzeln · Staffelfinale", "error": None,
            "progress_done": 0, "progress_total": 1, "progress_current": title,
        })
        store.save()
    gemini_log(f"Gezielte Staffelfinal-Prüfung gestartet: {title}.")
    rows: list[dict[str, Any]] = []
    error = ""
    try:
        rows = query_single_series(key, today, item, focus_finale=True)
        for fresh in rows:
            if isinstance(fresh, dict):
                merge_previous_verified_facts(fresh, previous_by_title.get(str(fresh.get("title", ""))))
        result = {"series_status": rows}
        normalize_for_watch_progress(result, [item])
        add_posters(result)
        rows = result["series_status"]
        if not rows:
            error = "keine verwertbare Antwort"
    except urllib.error.HTTPError as err:
        error = f"HTTP {err.code}"
        gemini_log(f"Gezielte Prüfung {title}: {error}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as err:
        error = type(err).__name__
        gemini_log(f"Gezielte Prüfung {title}: {error}: {err}")
    if not rows and isinstance(previous_by_title.get(title), dict):
        preserved = json.loads(json.dumps(previous_by_title[title]))
        warnings = list(preserved.get("warnings") or [])
        warnings.insert(0, "Einzelprüfung fehlgeschlagen – letzter bestätigter Stand wird angezeigt")
        preserved["warnings"] = list(dict.fromkeys(warnings))[:5]
        rows = [preserved]
    if not check_is_active(request_id):
        gemini_log(f"Gezielte Prüfung verworfen: {title}.")
        return True
    with store.lock:
        if not check_is_active(request_id):
            return True
        daily = store.data.setdefault("daily_check", {})
        remaining = [row for row in previous_rows if str(row.get("title", "")) != title]
        daily.update({
            "series_status": remaining + rows,
            "check_running": False, "request_id": None, "started_at": None,
            "progress_done": 1, "progress_total": 1, "progress_current": "",
            "error": error or None,
            "needs_refresh": False if not error else bool(daily.get("needs_refresh")),
        })
        store.save()
    if rows and not error:
        process_notification_events({"series_status": rows}, [item])
    gemini_log(f"Gezielte Staffelfinal-Prüfung beendet: {title} ({'aktualisiert' if not error else error}).")
    return True


def daily_scheduler() -> None:
    while True:
        try:
            run_daily_check()
        except Exception as err:
            gemini_log(f"Scheduler-Fehler: {type(err).__name__}: {err}")
        time.sleep(60)


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    size = int(handler.headers.get("Content-Length", "0"))
    if size <= 0 or size > 100_000:
        return {}
    try:
        value = json.loads(handler.rfile.read(size).decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, ValueError):
        return {}


def find_series(identifier: str) -> dict[str, Any] | None:
    for item in store.data.get("series", []):
        if item.get("id") == identifier:
            return item
    return None


def clean_number(value: Any, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return minimum


def make_identifier(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "serie"
    return f"{base}-{uuid.uuid4().hex[:6]}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/health":
            return json_response(self, {"status": "ok", "version": VERSION})
        if route == "/api/dashboard":
            return json_response(self, dashboard())
        if route == "/" or route == "/index.html":
            raw = PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        json_response(self, {"error": "Nicht gefunden"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        body = read_json(self)
        if route == "/api/check-now":
            if not gemini_api_key():
                return json_response(self, {"error": "Gemini-Schlüssel fehlt"}, 400)
            threading.Thread(target=run_daily_check, kwargs={"manual": True}, daemon=True).start()
            return json_response(self, dashboard(), 202)
        if route == "/api/cancel-check":
            cancel_daily_check()
            return json_response(self, dashboard())
        if route.startswith("/api/series/") and route.endswith("/check"):
            parts = route.strip("/").split("/")
            if len(parts) != 4:
                return json_response(self, {"error": "Nicht gefunden"}, 404)
            if not gemini_api_key():
                return json_response(self, {"error": "Gemini-Schlüssel fehlt"}, 400)
            with store.lock:
                item = find_series(parts[2])
                running = bool(store.data.setdefault("daily_check", {}).get("check_running"))
            if not item or item.get("status") != "watching":
                return json_response(self, {"error": "Serie nicht gefunden"}, 404)
            if running:
                return json_response(self, {"error": "Eine Gemini-Prüfung läuft bereits"}, 409)
            threading.Thread(target=run_targeted_series_check, args=(parts[2],), daemon=True).start()
            return json_response(self, dashboard(), 202)
        if route == "/api/notification-settings":
            allowed = {"enabled", "season_complete", "new_season_confirmed", "season_started", "series_ended", "start_date_known"}
            with store.lock:
                settings = store.data.setdefault("notification_settings", {})
                for key in allowed:
                    if key in body:
                        settings[key] = bool(body.get(key))
                store.save()
            return json_response(self, dashboard())
        if route == "/api/notification-test":
            ok = send_series_notification("📺 Serienplaner", "Test-Benachrichtigung erfolgreich eingerichtet.")
            if not ok:
                return json_response(self, {"error": "Test-Push konnte nicht gesendet werden."}, 500)
            return json_response(self, dashboard())
        if route.startswith("/api/series/") and route.endswith("/preferences"):
            parts = route.strip("/").split("/")
            if len(parts) != 4:
                return json_response(self, {"error": "Nicht gefunden"}, 404)
            with store.lock:
                item = find_series(parts[2])
                if not item:
                    return json_response(self, {"error": "Serie nicht gefunden"}, 404)
                if "wait_until_complete" in body:
                    item["wait_until_complete"] = bool(body.get("wait_until_complete"))
                store.save()
            return json_response(self, dashboard())
        with store.lock:
            if route == "/api/series":
                name = str(body.get("name", "")).strip()
                if not name:
                    return json_response(self, {"error": "Name fehlt"}, 400)
                status = str(body.get("status", "watching"))
                if status not in {"watching", "paused", "cancelled"}:
                    status = "watching"
                store.data.setdefault("series", []).append({
                    "id": make_identifier(name), "name": name, "status": status,
                    "season": clean_number(body.get("season"), 1),
                    "episode": clean_number(body.get("episode")),
                    "note": str(body.get("note", "")).strip(),
                    "wait_until_complete": False,
                })
            else:
                parts = route.strip("/").split("/")
                if len(parts) != 4 or parts[:2] != ["api", "series"]:
                    return json_response(self, {"error": "Nicht gefunden"}, 404)
                item = find_series(parts[2])
                if not item:
                    return json_response(self, {"error": "Serie nicht gefunden"}, 404)
                action = parts[3]
                if action == "advance":
                    # 0 bedeutet: die gespeicherte Staffel wurde komplett gesehen.
                    # Der nächste Klick beginnt daher sinnvollerweise mit Folge 1
                    # der darauffolgenden Staffel.
                    if clean_number(item.get("episode")) == 0:
                        item["season"] = clean_number(item.get("season"), 1) + 1
                        item["episode"] = 1
                    else:
                        item["episode"] = clean_number(item.get("episode")) + 1
                    item["status"] = "watching"
                elif action == "update":
                    item["season"] = clean_number(body.get("season"), 1)
                    item["episode"] = clean_number(body.get("episode"))
                    item["note"] = str(body.get("note", item.get("note", ""))).strip()
                elif action == "status":
                    status = str(body.get("status", ""))
                    if status not in {"watching", "paused", "cancelled"}:
                        return json_response(self, {"error": "Ungültiger Status"}, 400)
                    item["status"] = status
                elif action == "delete":
                    # Eine absichtlich gelöschte Serie soll nicht bis zum
                    # nächsten Check weiter als alte Karte sichtbar bleiben.
                    title = str(item.get("name", ""))
                    store.data["series"] = [entry for entry in store.data.get("series", [])
                                            if entry.get("id") != item.get("id")]
                    daily = store.data.setdefault("daily_check", {})
                    daily["series_status"] = [row for row in daily.get("series_status", [])
                                              if not isinstance(row, dict) or row.get("title") != title]
                    store.data.setdefault("series_end_confirmations", {}).pop(title, None)
                else:
                    return json_response(self, {"error": "Unbekannte Aktion"}, 404)
            store.save()
        json_response(self, dashboard())


PAGE = r'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Serienplaner</title><style>
:root{--bg:#071116;--card:#0d2028;--card2:#102931;--line:#244652;--text:#f2f8f8;--muted:#a6bdc0;--mint:#63e2b5;--yellow:#ffd166;--red:#ff8e8b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#123642,transparent 35%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1280px;margin:auto;padding:28px 20px 48px}.hero{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:20px}.hero h1{font-size:34px;margin:0}.hero p{color:var(--muted);margin:6px 0 0}.logo{font-size:42px;border-radius:18px;background:linear-gradient(135deg,#61dfb5,#72c8ef 57%,#ffd166 57%);padding:10px 14px}.chips{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:18px 0}.chip,.daily,.section{border:1px solid var(--line);background:rgba(9,27,34,.9);border-radius:18px}.chip{padding:12px 16px}.chip b{display:block;font-size:22px;color:var(--mint)}.chip span,.daily p,.meta,.note{color:var(--muted);font-size:13px}.daily{display:flex;justify-content:space-between;gap:16px;padding:15px 17px;margin-bottom:22px}.daily b{color:var(--yellow)}.section{padding:18px;margin-top:16px}.sectionHead{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}.section h2{margin:0;font-size:20px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.card{border:1px solid var(--line);background:var(--card);border-radius:15px;padding:15px;min-height:182px;display:flex;flex-direction:column}.card h3{margin:0 0 7px;font-size:19px}.meta{margin-bottom:9px}.note{line-height:1.35;margin:0 0 auto}.card.cancelled{opacity:.78;min-height:140px}.actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}button{border:1px solid #315765;background:#122b34;color:var(--text);border-radius:10px;padding:9px 11px;font-weight:750;font-size:13px;cursor:pointer}button.primary{background:linear-gradient(135deg,#58dcb0,#58bddd);border-color:#66dfba;color:#061317}button.warn{color:#ffd6d3;border-color:#8d4e4e}.add{display:none;margin-top:12px;padding:14px;border:1px dashed #477080;border-radius:14px}.add.show{display:grid;grid-template-columns:2fr 80px 80px 1fr auto;gap:8px}input,select{min-width:0;background:#08191f;color:var(--text);border:1px solid #315765;border-radius:9px;padding:9px;font:inherit}.empty{color:var(--muted);padding:8px 0}@media(max-width:800px){main{padding:18px 12px}.hero h1{font-size:27px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.add.show{grid-template-columns:1fr 70px 70px}.add.show input:last-of-type{grid-column:1/-1}.hero{align-items:flex-start}.daily{display:block}.daily p{margin-bottom:0}}@media(max-width:480px){.grid{grid-template-columns:1fr}.chips{gap:7px}.chip{padding:10px}.chip b{font-size:18px}.logo{font-size:30px}.add.show{grid-template-columns:1fr 1fr}.add.show input:first-child,.add.show input:last-of-type{grid-column:1/-1}}
</style><style>
/* Eigenständige Serienoptik: ein helles, warmes Serienregal statt Technik-Dashboard. */
:root{--bg:#f6f1eb;--card:#fffdfa;--card2:#fff6f4;--line:#e5d8d6;--text:#2d2331;--muted:#796d77;--mint:#7456c7;--yellow:#ff8565;--red:#c73f68}body{background:linear-gradient(135deg,#f7eee5 0%,#f8f4ef 44%,#eee9ff 100%);color:var(--text)}main{max-width:1180px;padding:42px 22px 56px}.hero{padding:28px 30px 30px;border-radius:28px;background:linear-gradient(125deg,#3e276e 0%,#6950b7 58%,#f37576 150%);box-shadow:0 18px 40px rgba(75,46,108,.22);color:#fff;margin-bottom:18px}.hero h1{font-family:Georgia,"Times New Roman",serif;font-size:44px;letter-spacing:-1.5px}.hero p{color:#eee8ff;font-size:16px}.logo{font-size:38px;background:#ffca73;border-radius:18px;box-shadow:inset 0 -4px 0 rgba(82,52,96,.12);padding:12px 16px}.chips{grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}.chip{position:relative;overflow:hidden;background:rgba(255,253,250,.86);border:0;border-radius:18px;padding:16px 19px;box-shadow:0 7px 20px rgba(96,69,83,.08)}.chip:before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--mint)}.chip:nth-child(2):before{background:#f2aa58}.chip:nth-child(3):before{background:#db6385}.chip b{font-family:Georgia,"Times New Roman",serif;font-size:28px;color:#4b367d}.chip span{color:var(--muted)}.daily{position:relative;display:flex;background:linear-gradient(95deg,#fff8e9,#fff0ed);border:1px solid #f0d8bd;border-radius:20px;padding:17px 21px;box-shadow:none}.daily:before{content:"Heute im Serienregal";position:absolute;top:-10px;left:17px;background:#f6f1eb;padding:0 7px;color:#8d6874;font-size:10px;font-weight:900;letter-spacing:.13em;text-transform:uppercase}.daily b{color:#b34863;font-size:15px}.daily p,.meta,.note{color:var(--muted)}.section{border:0;background:transparent;border-radius:0;padding:7px 0 20px;margin-top:22px}.sectionHead{border-bottom:2px solid #e6d7d2;padding-bottom:11px;margin-bottom:16px}.section h2{font-family:Georgia,"Times New Roman",serif;font-size:28px;color:#3a2c46;letter-spacing:-.5px}.grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.card{position:relative;border:1px solid #eadeda;background:linear-gradient(145deg,#fffefa,#fff7f2);border-radius:16px;padding:19px 18px 17px;min-height:194px;box-shadow:0 9px 18px rgba(93,67,73,.07)}.card:before{content:"";position:absolute;left:0;top:18px;bottom:18px;width:4px;border-radius:0 4px 4px 0;background:#8b6bce}.card:nth-child(3n+2):before{background:#ef8a68}.card:nth-child(3n):before{background:#d96188}.card h3{font-family:Georgia,"Times New Roman",serif;font-size:22px;color:#3a2b46;margin-left:4px}.card.cancelled{background:#f1ece8;border-style:dashed;box-shadow:none;min-height:142px}.card.cancelled:before{background:#9f9395}.actions{gap:7px;margin-top:16px}.actions button{font-size:12px;padding:8px 9px}button{border:1px solid #d8c5ca;background:#fffaf7;color:#594553;border-radius:999px;padding:10px 14px;box-shadow:0 2px 0 rgba(121,90,101,.08)}button.primary{background:linear-gradient(110deg,#7355c7,#b154ae);border-color:#7355c7;color:#fff}.add{background:#fffaf7;border:1px dashed #b8a2ca;border-radius:16px}.add.show{grid-template-columns:2fr 80px 80px 1fr auto}.empty{font-style:italic;color:#a3959a}@media(max-width:800px){main{padding:22px 14px 44px}.hero{padding:23px 20px}.hero h1{font-size:34px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:480px){.hero{border-radius:22px}.hero h1{font-size:31px}.chips{gap:8px}.chip{padding:12px 13px}.chip b{font-size:23px}.daily{padding:18px 15px 14px}.section h2{font-size:25px}.grid{grid-template-columns:1fr}.card{min-height:0}.add.show{grid-template-columns:1fr 1fr}.add.show input:first-child,.add.show input:last-of-type{grid-column:1/-1}}
</style></head><body><main><header class="hero"><div><h1>Serienplaner</h1><p>Gemeinsam schauen · mit einem Klick aktuell halten</p></div><div class="logo">📺</div></header><div id="chips" class="chips"></div><section class="daily"><div><b>✦ Serien-Check · <span id="dailyState"></span></b><p id="dailyDetail"></p></div><span class="meta">Automatisch Dienstag & Freitag</span></section><section class="section"><div class="sectionHead"><h2>Gerade offen</h2><button class="primary" onclick="toggleAdd()">＋ Serie eintragen</button></div><form id="addForm" class="add" onsubmit="addSeries(event)"><input name="name" placeholder="Name der Serie" required><input name="season" type="number" min="1" placeholder="Staffel"><input name="episode" type="number" min="0" placeholder="Folge"><input name="note" placeholder="Optionaler Hinweis"><button class="primary">Speichern</button></form><div id="watching" class="grid"></div></section><section class="section"><div class="sectionHead"><h2>Pausiert</h2></div><div id="paused" class="grid"></div></section><section class="section"><div class="sectionHead"><h2>Abgeschlossen · Serie eingestellt</h2><span class="meta">Komplett gesehen – keine neuen Folgen erwartet</span></div><div id="cancelled" class="grid"></div></section></main><script>
let DATA={};const q=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});DATA=await r.json();render()}async function load(){await api('/api/dashboard')}function progress(s){return s.episode?`Staffel ${s.season} · bis Folge ${s.episode} gesehen`:`Bis Staffel ${s.season} gesehen`}function card(s){const action=s.status==='watching'?`<button class="primary" onclick="advance('${s.id}')">✓ Nächste Folge gesehen</button><button onclick="editSeries('${s.id}')">Stand ändern</button><button onclick="setStatus('${s.id}','paused')">Pausieren</button>`:s.status==='paused'?`<button class="primary" onclick="setStatus('${s.id}','watching')">Weiter schauen</button>`:'';return `<article class="card ${s.status==='cancelled'?'cancelled':''}"><h3>${esc(s.name)}</h3>${s.status!=='cancelled'?`<div class="meta">${progress(s)}</div>`:''}<p class="note">${esc(s.note||'Kein Hinweis hinterlegt.')}</p>${s.status==='cancelled'?'<div class="meta">✓ Komplett gesehen · eingestellt</div>':`<div class="actions">${action}</div>`}</article>`}function section(name,status){const items=DATA.series.filter(s=>s.status===status);q('#'+name).innerHTML=items.length?items.map(card).join(''):'<p class="empty">Noch keine Serien hier.</p>'}function render(){q('#chips').innerHTML=`<div class="chip"><b>${DATA.counts.watching}</b><span>Gerade offen</span></div><div class="chip"><b>${DATA.counts.paused}</b><span>Pausiert</span></div><div class="chip"><b>${DATA.counts.cancelled}</b><span>Abgeschlossen</span></div>`;q('#dailyState').textContent=DATA.daily_check.state;q('#dailyDetail').textContent=DATA.daily_check.detail;section('watching','watching');section('paused','paused');section('cancelled','cancelled')}function toggleAdd(){q('#addForm').classList.toggle('show');q('[name=name]').focus()}async function advance(id){await api('/api/series/'+id+'/advance',{})}async function setStatus(id,status){await api('/api/series/'+id+'/status',{status})}async function editSeries(id){const s=DATA.series.find(x=>x.id===id),season=prompt('Staffel:',s.season),episode=prompt('Bis zu welcher Folge gesehen? (0 = ganze Staffel)',s.episode),note=prompt('Hinweis:',s.note||'');if(season===null||episode===null||note===null)return;await api('/api/series/'+id+'/update',{season,episode,note})}async function addSeries(e){e.preventDefault();const f=new FormData(e.target);await api('/api/series',{name:f.get('name'),season:f.get('season'),episode:f.get('episode'),note:f.get('note')});e.target.reset();q('#addForm').classList.remove('show')}load();</script></body></html>'''

EXTRA_SERIES_UI = r'''<style>
.daily .meta{font-weight:750}.dailyActions{display:flex;flex-direction:column;align-items:flex-end;gap:7px;text-align:right}.dailyActions button{white-space:nowrap}.dailyActions button:disabled{cursor:wait;opacity:.68}.dailyUpdates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:14px 0 4px}.dailyUpdate{position:relative;display:grid;grid-template-columns:74px 1fr;gap:12px;width:100%;border:1px solid #eadeda;background:#fffdfa;border-radius:16px;padding:11px;box-shadow:0 6px 14px rgba(93,67,73,.06);text-align:left}.dailyUpdate:before{content:"";position:absolute;left:0;top:13px;bottom:13px;width:4px;border-radius:0 4px 4px 0;background:#ad9aa9}.dailyUpdate.new:before{background:#7b5bcc}.dailyUpdate.upcoming:before{background:#e98b61}.seriesPoster,.recPoster{width:74px;min-height:106px;object-fit:cover;border-radius:10px;background:linear-gradient(145deg,#473174,#885dc0 48%,#f27a76 49%,#ffc76e);color:#fff;font-family:Georgia,"Times New Roman",serif;font-size:16px;font-weight:800;line-height:.92;display:flex;align-items:flex-end;padding:8px;text-shadow:0 1px 2px #372744}.dailyBody{min-width:0}.dailyUpdate b{display:block;color:#46314f;font-size:15px;margin:1px 2px 0}.dailyUpdate p{font-size:12px;line-height:1.35;color:#796d77;margin:6px 2px}.dailyFacts{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.dailyFacts span{font-size:11px;background:#f5efff;color:#604c8f;border-radius:999px;padding:4px 7px}.dailyFacts span.provider{background:#fff0e9;color:#a25b4c}.dailyFacts span.streamable{background:#e6f6ed;color:#287050}.dailyFacts span.not_streamable{background:#fff0df;color:#955f32}.dailyUpdate a{display:inline-block;margin:8px 2px 0;color:#9050ae;font-size:12px;font-weight:800}.recommendations{grid-column:1/-1;border:1px solid #e7cdd4;background:linear-gradient(100deg,#fff8ef,#fff0f6);border-radius:18px;padding:16px}.recommendations h3{margin:0 0 10px;font-family:Georgia,"Times New Roman",serif;color:#623d68;font-size:23px}.recommendations .hint{margin:-5px 0 12px;color:#7e6e78;font-size:13px}.recList{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.rec{display:grid;grid-template-columns:60px 1fr;gap:9px;background:#fffdfb;border:1px solid #eadeda;border-radius:12px;padding:8px;min-width:0}.recPoster{width:60px;min-height:86px;font-size:13px}.rec b{display:block;color:#51365c;font-family:Georgia,"Times New Roman",serif;font-size:16px}.rec p{margin:3px 0 7px;color:#71616c;font-size:12px;line-height:1.3}.rec small{display:block;color:#9258a3;font-size:11px;font-weight:800}.recActions{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.recActions button{font-size:10px;padding:6px 7px}.recActions button.selected{background:#8058c8;border-color:#8058c8;color:#fff}.modalShade{position:fixed;inset:0;z-index:20;background:rgba(45,30,45,.44);display:flex;align-items:center;justify-content:center;padding:16px}.seriesModal{width:min(680px,100%);max-height:min(760px,calc(100vh - 32px));overflow:auto;border-radius:22px;background:#fffaf7;border:1px solid #e5d7d4;box-shadow:0 24px 70px rgba(45,25,45,.35);padding:22px}.modalTop{display:flex;align-items:start;justify-content:space-between;gap:16px}.modalTop h2{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:31px;color:#382a45}.modalTop button{padding:7px 10px}.modalIntro{color:#776873;margin:6px 0 15px;font-size:14px}.modalShow{display:grid;grid-template-columns:102px 1fr;gap:14px;margin-bottom:15px}.modalShow .seriesPoster{width:102px;min-height:145px;font-size:22px}.seasonRows{display:grid;gap:9px}.seasonRow{border:1px solid #eadeda;background:#fffdfa;border-radius:13px;padding:11px 13px;display:grid;grid-template-columns:85px 1fr;gap:10px}.seasonRow strong{font-family:Georgia,"Times New Roman",serif;color:#47334d}.seasonStatus{font-size:13px;font-weight:850}.seasonStatus.streamable{color:#287050}.seasonStatus.not_streamable{color:#985f31}.seasonStatus.upcoming{color:#9258a3}.seasonStatus.unknown{color:#7c6e76}.seasonInfo{font-size:12px;color:#766772;line-height:1.35}.modalSource{display:inline-block;margin-top:13px;color:#8750a7;font-weight:800;font-size:13px}@media(max-width:800px){.dailyActions{align-items:flex-start;text-align:left;margin-top:12px}.recList{grid-template-columns:1fr}}@media(max-width:600px){.dailyUpdates{grid-template-columns:1fr}.recommendations{grid-column:auto}.modalShade{align-items:end;padding:0}.seriesModal{max-height:88vh;border-radius:22px 22px 0 0;padding:18px}.modalTop h2{font-size:27px}}
</style><script>
function safeUrl(value){try{const url=new URL(String(value||''));return url.protocol==='https:'?url.href:''}catch(_){return ''}}function poster(item,className){const image=safeUrl(item.poster_url);const label=esc(String(item.title||'Serie'));return image?`<img class="${className}" src="${esc(image)}" alt="Poster zu ${esc(item.title)}">`:`<div class="${className}">${label}</div>`}function feedbackFor(title){const item=(DATA.recommendation_feedback||[]).find(row=>row.title===title);return item?item.reaction:''}function seasonLabel(state){return({streamable:'✓ Deutsch streambar',not_streamable:'◷ Zurzeit nicht streambar',upcoming:'◷ Angekündigt',seen:'✓ Gesehen',unknown:'? Noch unklar'})[state]||'? Noch unklar'}async function sendFeedback(button){const response=await fetch('/api/recommendation-feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:button.dataset.title,reaction:button.dataset.reaction})});if(!response.ok){alert('Die Rückmeldung konnte nicht gespeichert werden.');return}DATA=await response.json();render()}function openSeriesDetail(title){const item=(DATA.daily_check.series_status||[]).find(row=>row.title===title);if(!item)return;const own=DATA.series.find(row=>row.name===title);const seasons=(item.seasons||[]).map(row=>`<article class="seasonRow"><strong>Staffel ${esc(row.season)}</strong><div><div class="seasonStatus ${esc(row.state)}">${seasonLabel(row.state)}</div><div class="seasonInfo">${esc([row.episodes,row.provider&&'Bei '+row.provider,row.availability].filter(Boolean).join(' · ')||'Wird weiter geprüft.')}</div></div></article>`).join('')||'<p class="modalIntro">Noch keine einzelnen Staffelinfos gefunden.</p>';const source=safeUrl(item.source_url);const layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal" role="dialog" aria-modal="true" aria-label="Details zu ${esc(title)}"><div class="modalTop"><div><h2>${esc(title)}</h2><p class="modalIntro">${own?esc(progress(own)):'Persönlicher Stand noch nicht hinterlegt.'}</p></div><button type="button" data-close>Schließen</button></div><div class="modalShow">${poster(item,'seriesPoster')}<div><b>${esc(item.available||'Aktueller Verfügbarkeitsstand')}</b><p class="modalIntro">${esc(item.detail)}</p><span class="dailyFacts"><span class="${(item.seasons||[]).some(row=>row.state==='streamable')?'streamable':'not_streamable'}">Nur Deutsch</span></span></div></div><div class="seasonRows">${seasons}</div>${source?`<a class="modalSource" target="_blank" rel="noreferrer" href="${esc(source)}">Quelle öffnen ↗</a>`:''}</section>`;layer.addEventListener('click',event=>{if(event.target===layer||event.target.closest('[data-close]'))layer.remove()});document.body.append(layer)}function renderDailyDetails(){const daily=DATA.daily_check||{},anchor=document.querySelector('.daily');if(!anchor)return;let outlet=document.querySelector('#dailyUpdates');if(!outlet){outlet=document.createElement('div');outlet.id='dailyUpdates';outlet.className='dailyUpdates';anchor.insertAdjacentElement('afterend',outlet)}const stateText={new:'Neu verfügbar',upcoming:'Angekündigt',nothing_new:'Nichts neu'};const rows=(daily.series_status||[]).map(item=>{const seasons=item.seasons||[];const stream=seasons.find(row=>row.state==='streamable'),noStream=seasons.find(row=>row.state==='not_streamable');const facts=[item.available,item.remaining,item.provider&&'Bei '+item.provider,item.availability].filter(Boolean);if(stream)facts.unshift(`Staffel ${stream.season}: deutsch streambar`);if(noStream)facts.push(`Staffel ${noStream.season}: nicht streambar`);return `<button type="button" class="dailyUpdate ${esc(item.state)}" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}<div class="dailyBody"><b>${stateText[item.state]||'Stand'} · ${esc(item.title)}</b><p>${esc(item.detail)}</p>${facts.length?`<div class="dailyFacts">${facts.map(fact=>`<span class="${/nicht streambar/.test(fact)?'not_streamable':/streambar/.test(fact)?'streamable':''}">${esc(fact)}</span>`).join('')}</div>`:''}</div></button>`}).join('');const recommendations=(daily.recommendations||[]).map(item=>{const reaction=feedbackFor(item.title);return `<article class="rec">${poster(item,'recPoster')}<div><b>${esc(item.title)}</b><p>${esc(item.detail)}</p>${item.provider?`<small>Deutsch bei ${esc(item.provider)}</small>`:''}<div class="recActions"><button data-feedback data-title="${esc(item.title)}" data-reaction="merken" class="${reaction==='merken'?'selected':''}">♡ Merken</button><button data-feedback data-title="${esc(item.title)}" data-reaction="nicht_interessant" class="${reaction==='nicht_interessant'?'selected':''}">Nicht interessant</button><button data-feedback data-title="${esc(item.title)}" data-reaction="gesehen" class="${reaction==='gesehen'?'selected':''}">Schon gesehen</button></div></div></article>`}).join('');outlet.innerHTML=rows+(recommendations?`<section class="recommendations"><h3>Für euch ausgesucht</h3><p class="hint">Deine Antworten werden bei künftigen Empfehlungen berücksichtigt.</p><div class="recList">${recommendations}</div></section>`:'');outlet.querySelectorAll('[data-open-series]').forEach(button=>button.addEventListener('click',()=>openSeriesDetail(button.dataset.openSeries)));outlet.querySelectorAll('[data-feedback]').forEach(button=>button.addEventListener('click',()=>sendFeedback(button)));const meta=anchor.querySelector('.meta');if(meta)meta.textContent='Automatisch Dienstag & Freitag · manuell beliebig oft.';const button=q('#checkNow');if(button){button.disabled=!!daily.is_running||daily.state==='Gemini-Schlüssel fehlt';button.textContent=daily.is_running?'Gemini prüft …':'Jetzt prüfen'}}const originalRender=render;render=function(){originalRender();renderDailyDetails()};
</script>'''

PROGRESS_SERIES_UI = r'''<style>
.dailyUpdate{display:block;padding:11px}.dailyTop{display:grid;grid-template-columns:74px 1fr;gap:12px;width:100%;text-align:left;cursor:pointer}.dailyTop:hover .dailyBody b{text-decoration:underline}.dailyProgress{margin:5px 2px 0;color:#513d55;font-size:13px;font-weight:850}.dailyProgress span{color:#877681;font-weight:650}.dailyControls{display:flex;align-items:center;gap:7px;flex-wrap:wrap;border-top:1px solid #eee2df;margin-top:10px;padding:10px 2px 0}.dailyControls button{font-size:11px;padding:7px 9px}.dailyControls .nextHint{font-size:11px;color:#806f79;margin-left:auto}.dailyExpiry{margin:7px 2px 0;color:#9a5e39;font-size:11px;font-weight:800}.personalStatus{border:1px solid #e7d8d4;background:#fff4f2;border-radius:13px;padding:11px 13px;margin:0 0 14px;color:#634a59;font-size:13px}.personalStatus b{display:block;color:#42304d;font-size:15px;margin-bottom:3px}.modalControls{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.modalControls button{font-size:12px;padding:8px 10px}@media(max-width:600px){.dailyTop{grid-template-columns:62px 1fr}.dailyTop .seriesPoster{width:62px;min-height:90px}.dailyControls .nextHint{width:100%;margin:0}.dailyControls button{font-size:10px}}
</style><script>
function nextEntry(series){if(!series)return '';return Number(series.episode||0)>0?`Als Nächstes: Staffel ${series.season} · Folge ${Number(series.episode)+1}`:`Als Nächstes: Staffel ${Number(series.season)+1} · Folge 1`}function expiryHint(item){const values=[item.availability,...(item.seasons||[]).map(row=>row.availability)].filter(Boolean);return values.find(value=>/endet|ablauf|bis\s+\d/i.test(value))||''}function actionsForOwnSeries(series){if(!series)return '';return `<div class="dailyControls"><button class="primary" data-advance="${esc(series.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(series.id)}">Stand ändern</button><span class="nextHint">${esc(nextEntry(series))}</span></div>`}function openSeriesDetail(title){const item=(DATA.daily_check.series_status||[]).find(row=>row.title===title);if(!item)return;const own=DATA.series.find(row=>row.name===title);const seasons=(item.seasons||[]).map(row=>`<article class="seasonRow"><strong>Staffel ${esc(row.season)}</strong><div><div class="seasonStatus ${esc(row.state)}">${seasonLabel(row.state)}</div><div class="seasonInfo">${esc([row.episodes,row.provider&&'Bei '+row.provider,row.availability].filter(Boolean).join(' · ')||'Wird weiter geprüft.')}</div></div></article>`).join('')||'<p class="modalIntro">Noch keine einzelnen Staffelinfos gefunden.</p>';const source=safeUrl(item.source_url),expiry=expiryHint(item);const layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal" role="dialog" aria-modal="true" aria-label="Details zu ${esc(title)}"><div class="modalTop"><div><h2>${esc(title)}</h2><p class="modalIntro">Deutschsprachige Streamingangebote in Deutschland</p></div><button type="button" data-close>Schließen</button></div>${own?`<div class="personalStatus"><b>Euer Stand: ${esc(progress(own))}</b><span>${esc(nextEntry(own))}</span><div class="modalControls"><button class="primary" data-advance="${esc(own.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(own.id)}">Stand ändern</button></div></div>`:''}<div class="modalShow">${poster(item,'seriesPoster')}<div><b>${esc(item.available||'Aktueller Verfügbarkeitsstand')}</b><p class="modalIntro">${esc(item.detail)}</p>${expiry?`<div class="dailyExpiry">${esc(expiry)}</div>`:''}</div></div><div class="seasonRows">${seasons}</div>${source?`<a class="modalSource" target="_blank" rel="noreferrer" href="${esc(source)}">Quelle öffnen ↗</a>`:''}</section>`;layer.addEventListener('click',event=>{if(event.target===layer||event.target.closest('[data-close]'))layer.remove()});layer.querySelectorAll('[data-advance]').forEach(button=>button.addEventListener('click',async()=>{await advance(button.dataset.advance);layer.remove()}));layer.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',async()=>{layer.remove();await editSeries(button.dataset.edit)}));document.body.append(layer)}function renderDailyDetails(){const daily=DATA.daily_check||{},anchor=document.querySelector('.daily');if(!anchor)return;let outlet=document.querySelector('#dailyUpdates');if(!outlet){outlet=document.createElement('div');outlet.id='dailyUpdates';outlet.className='dailyUpdates';anchor.insertAdjacentElement('afterend',outlet)}const stateText={new:'Neu verfügbar',upcoming:'Angekündigt',nothing_new:'Nichts neu'};const rows=(daily.series_status||[]).map(item=>{const own=DATA.series.find(row=>row.name===item.title),seasons=item.seasons||[];const stream=seasons.find(row=>row.state==='streamable'),noStream=seasons.find(row=>row.state==='not_streamable'),expiry=expiryHint(item);const facts=[item.available,item.remaining,item.provider&&'Bei '+item.provider].filter(Boolean);if(stream)facts.unshift(`Staffel ${stream.season}: deutsch streambar`);if(noStream)facts.push(`Staffel ${noStream.season}: nicht streambar`);return `<article class="dailyUpdate ${esc(item.state)}"><div class="dailyTop" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}<div class="dailyBody"><b>${stateText[item.state]||'Stand'} · ${esc(item.title)}</b>${own?`<div class="dailyProgress">Euer Stand: ${esc(progress(own))} <span>· ${esc(nextEntry(own))}</span></div>`:''}<p>${esc(item.detail)}</p>${facts.length?`<div class="dailyFacts">${facts.map(fact=>`<span class="${/nicht streambar/.test(fact)?'not_streamable':/streambar/.test(fact)?'streamable':''}">${esc(fact)}</span>`).join('')}</div>`:''}${expiry?`<div class="dailyExpiry">${esc(expiry)}</div>`:''}</div></div>${actionsForOwnSeries(own)}</article>`}).join('');const recommendations=(daily.recommendations||[]).map(item=>{const reaction=feedbackFor(item.title);return `<article class="rec">${poster(item,'recPoster')}<div><b>${esc(item.title)}</b><p>${esc(item.detail)}</p>${item.provider?`<small>Deutsch bei ${esc(item.provider)}</small>`:''}<div class="recActions"><button data-feedback data-title="${esc(item.title)}" data-reaction="merken" class="${reaction==='merken'?'selected':''}">♡ Merken</button><button data-feedback data-title="${esc(item.title)}" data-reaction="nicht_interessant" class="${reaction==='nicht_interessant'?'selected':''}">Nicht interessant</button><button data-feedback data-title="${esc(item.title)}" data-reaction="gesehen" class="${reaction==='gesehen'?'selected':''}">Schon gesehen</button></div></div></article>`}).join('');outlet.innerHTML=rows+(recommendations?`<section class="recommendations"><h3>Für euch ausgesucht</h3><p class="hint">Deine Antworten werden bei künftigen Empfehlungen berücksichtigt.</p><div class="recList">${recommendations}</div></section>`:'');outlet.querySelectorAll('[data-open-series]').forEach(element=>element.addEventListener('click',()=>openSeriesDetail(element.dataset.openSeries)));outlet.querySelectorAll('[data-advance]').forEach(button=>button.addEventListener('click',()=>advance(button.dataset.advance)));outlet.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>editSeries(button.dataset.edit)));outlet.querySelectorAll('[data-feedback]').forEach(button=>button.addEventListener('click',()=>sendFeedback(button)));const meta=anchor.querySelector('.meta');if(meta)meta.textContent='Automatisch Dienstag & Freitag · manuell beliebig oft.';const button=q('#checkNow');if(button){button.disabled=!!daily.is_running||daily.state==='Gemini-Schlüssel fehlt';button.textContent=daily.is_running?'Gemini prüft …':'Jetzt prüfen'}}
</script>'''

OVERVIEW_SERIES_UI = r'''<style>
/* Die Tagesprüfung ist ein Regal mit drei Lesezuständen statt einer langen Einheitsliste. */
.dailyUpdates{display:block;margin:18px 0 4px}.releaseSummary{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}.releaseSummary span{border:1px solid #eadeda;border-radius:999px;background:#fffaf7;padding:7px 10px;color:#684e62;font-size:12px;font-weight:850}.releaseSummary span strong{font-family:Georgia,"Times New Roman",serif;font-size:16px;color:#49365a;margin-right:3px}.releaseGroup{border:1px solid #e8ddd9;border-radius:20px;background:rgba(255,253,250,.72);padding:16px;margin:14px 0}.releaseGroup.ready{border-color:#cfdfd5;background:linear-gradient(105deg,#fbfffb,#f4fbf5)}.releaseGroup.running{border-color:#ecd7c7;background:linear-gradient(105deg,#fffaf6,#fff4ef)}.releaseGroup.quiet{background:linear-gradient(105deg,#fdfafd,#f9f5fb)}.releaseHead{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 2px 13px}.releaseHead h3{font-family:Georgia,"Times New Roman",serif;font-size:24px;letter-spacing:-.35px;margin:0;color:#402d4b}.releaseHead p{margin:0;color:#806f79;font-size:12px;text-align:right}.releaseGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.releaseCard{position:relative;display:grid;grid-template-columns:74px minmax(0,1fr);gap:12px;border:1px solid #eadeda;border-radius:16px;background:#fffdfa;padding:11px;box-shadow:0 5px 13px rgba(93,67,73,.055)}.releaseCard.ready:before,.releaseCard.running:before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:4px;border-radius:0 4px 4px 0}.releaseCard.ready:before{background:#55a879}.releaseCard.running:before{background:#e0805f}.releaseCard .seriesPoster{width:74px;min-height:108px}.releaseBody{min-width:0}.releaseOpen{cursor:pointer}.releaseOpen:hover h4{text-decoration:underline}.releaseBody h4{font-family:Georgia,"Times New Roman",serif;color:#46314f;font-size:19px;line-height:1.1;margin:2px 2px 4px}.releaseOwn{color:#593f58;font-size:12px;font-weight:850;margin:0 2px 7px}.releaseOwn span{color:#8b7b83;font-weight:650}.releaseText{font-size:12px;line-height:1.35;color:#796d77;margin:5px 2px}.releaseTimeline{border-left:2px solid #d9b58e;margin:9px 2px 0;padding:3px 0 3px 8px;color:#725c62;font-size:11px;line-height:1.45}.releaseTimeline strong{color:#5a3d55}.releaseCard .dailyFacts{margin-top:8px}.releaseCard .dailyControls{grid-column:1/-1;margin-top:0;padding-top:9px}.releaseCard .dailyExpiry{grid-column:1/-1;margin:0 2px}.quietList{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.quietRow{display:flex;justify-content:space-between;align-items:center;gap:10px;border:1px solid #eadeda;border-radius:13px;background:#fffdfa;padding:11px 12px;cursor:pointer}.quietRow:hover{border-color:#c9b4d2;background:#fffaff}.quietRow b{font-family:Georgia,"Times New Roman",serif;color:#4a3655;font-size:16px}.quietRow span{display:block;color:#887983;font-size:11px;margin-top:3px}.quietBadge{flex:0 0 auto;border-radius:999px;background:#f2ebfa;color:#705392;padding:5px 7px;font-size:10px;font-weight:850;white-space:nowrap}.quietBadge.upcoming{background:#fff0e5;color:#a36345}.releaseEmpty{color:#857680;font-size:13px;font-style:italic;padding:4px 2px}.recommendations{margin-top:16px}.recommendations h3{font-size:24px}.detailTimeline{border:1px solid #eaded8;border-radius:13px;background:#fff7ef;padding:10px 12px;margin:0 0 13px;color:#6d5660;font-size:12px;line-height:1.5}.detailTimeline strong{color:#4c354b}@media(max-width:760px){.releaseGrid,.quietList{grid-template-columns:1fr}.releaseHead{align-items:flex-start}.releaseHead p{text-align:left;max-width:215px}}@media(max-width:430px){.releaseGroup{padding:13px}.releaseHead h3{font-size:21px}.releaseCard{grid-template-columns:62px minmax(0,1fr)}.releaseCard .seriesPoster{width:62px;min-height:91px}.releaseCard .dailyControls .nextHint{width:100%;margin-left:0}}
</style><script>
function releaseGroupFor(item){const direct=String(item.release_status||'');if(['complete','ongoing','nothing_new','upcoming'].includes(direct))return direct;const text=[item.available,item.remaining,item.detail,...(item.seasons||[]).map(row=>row.episodes)].filter(Boolean).join(' ').toLowerCase();if(item.state==='upcoming')return 'upcoming';if(/noch\s+\d+\s+folgen|folgen\s*1\s*[–-]\s*\d+\s*(?:von|\/)|läuft.*(?:folge|staffel)|aktuell.*(?:folge|abrufbar)/.test(text))return 'ongoing';if(/komplette\s+staffel|vollständig|staffel\s+\d+\s+komplett/.test(text))return 'complete';return 'nothing_new'}
function groupLabel(group){return({complete:'Komplett für euch verfügbar',ongoing:'Läuft noch · weitere Folgen kommen',nothing_new:'Noch nichts Neues',upcoming:'Angekündigt · noch nicht da'})[group]||'Aktueller Stand'}
function groupSubtitle(group){return({complete:'Diese Staffeln könnt ihr direkt vollständig starten.',ongoing:'Hier sieht man auf einen Blick, wann es weitergeht.',nothing_new:'Keine neue deutsche Staffel seit eurem persönlichen Stand.',upcoming:'Es gibt einen Termin, aber noch keine streambare Folge.'})[group]||''}
function scheduleFor(item){const rows=[];if(item.next_episode)rows.push(`<div><strong>Nächste Folge:</strong> ${esc(item.next_episode)}</div>`);if(item.estimated_complete){const label=item.completion_type==='confirmed'?'Staffel vollständig:':'Voraussichtlich vollständig:';rows.push(`<div><strong>${label}</strong> ${esc(item.estimated_complete)}</div>`)}return rows.join('')}
function factsFor(item){const seasons=item.seasons||[],stream=seasons.find(row=>row.state==='streamable'),noStream=seasons.find(row=>row.state==='not_streamable');const facts=[item.available,item.remaining,item.provider&&'Bei '+item.provider].filter(Boolean);if(stream)facts.unshift(`Staffel ${stream.season}: deutsch streambar`);if(noStream)facts.push(`Staffel ${noStream.season}: nicht streambar`);return facts}
function openSeriesDetail(title){const item=(DATA.daily_check.series_status||[]).find(row=>row.title===title);if(!item)return;const own=DATA.series.find(row=>row.name===title);const seasons=(item.seasons||[]).map(row=>`<article class="seasonRow"><strong>Staffel ${esc(row.season)}</strong><div><div class="seasonStatus ${esc(row.state)}">${seasonLabel(row.state)}</div><div class="seasonInfo">${esc([row.episodes,row.provider&&'Bei '+row.provider,row.availability].filter(Boolean).join(' · ')||'Wird weiter geprüft.')}</div></div></article>`).join('')||'<p class="modalIntro">Noch keine einzelnen Staffelinfos gefunden.</p>';const source=safeUrl(item.source_url),expiry=expiryHint(item),schedule=scheduleFor(item);const layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal" role="dialog" aria-modal="true" aria-label="Details zu ${esc(title)}"><div class="modalTop"><div><h2>${esc(title)}</h2><p class="modalIntro">Deutschsprachige Streamingangebote in Deutschland</p></div><button type="button" data-close>Schließen</button></div>${own?`<div class="personalStatus"><b>Euer Stand: ${esc(progress(own))}</b><span>${esc(nextEntry(own))}</span><div class="modalControls"><button class="primary" data-advance="${esc(own.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(own.id)}">Stand ändern</button></div></div>`:''}<div class="modalShow">${poster(item,'seriesPoster')}<div><b>${esc(item.available||'Aktueller Verfügbarkeitsstand')}</b><p class="modalIntro">${esc(item.detail)}</p>${expiry?`<div class="dailyExpiry">${esc(expiry)}</div>`:''}</div></div>${schedule?`<div class="detailTimeline">${schedule}</div>`:''}<div class="seasonRows">${seasons}</div>${source?`<a class="modalSource" target="_blank" rel="noreferrer" href="${esc(source)}">Quelle öffnen ↗</a>`:''}</section>`;layer.addEventListener('click',event=>{if(event.target===layer||event.target.closest('[data-close]'))layer.remove()});layer.querySelectorAll('[data-advance]').forEach(button=>button.addEventListener('click',async()=>{await advance(button.dataset.advance);layer.remove()}));layer.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',async()=>{layer.remove();await editSeries(button.dataset.edit)}));document.body.append(layer)}
function readyOrRunningCard(item,group){const own=DATA.series.find(row=>row.name===item.title),facts=factsFor(item),expiry=expiryHint(item),schedule=scheduleFor(item);return `<article class="releaseCard ${group}"><div class="releaseOpen" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}</div><div class="releaseBody releaseOpen" data-open-series="${esc(item.title)}"><h4>${esc(item.title)}</h4>${own?`<div class="releaseOwn">Euer Stand: ${esc(progress(own))} <span>· ${esc(nextEntry(own))}</span></div>`:''}<p class="releaseText">${esc(item.detail)}</p>${facts.length?`<div class="dailyFacts">${facts.map(fact=>`<span class="${/nicht streambar/.test(fact)?'not_streamable':/streambar/.test(fact)?'streamable':''}">${esc(fact)}</span>`).join('')}</div>`:''}${schedule?`<div class="releaseTimeline">${schedule}</div>`:''}</div>${actionsForOwnSeries(own)}${expiry?`<div class="dailyExpiry">${esc(expiry)}</div>`:''}</article>`}
function quietCard(item){const own=DATA.series.find(row=>row.name===item.title),group=releaseGroupFor(item),label=group==='upcoming'?'Angekündigt':'Kein neuer Stand';return `<article class="quietRow" data-open-series="${esc(item.title)}"><div><b>${esc(item.title)}</b><span>${own?`Euer Stand: ${esc(progress(own))}`:esc(item.detail)}</span></div><span class="quietBadge ${group}">${label}</span></article>`}
function recommendationBlock(daily){const cards=(daily.recommendations||[]).map(item=>{const reaction=feedbackFor(item.title);return `<article class="rec">${poster(item,'recPoster')}<div><b>${esc(item.title)}</b><p>${esc(item.detail)}</p>${item.provider?`<small>Deutsch bei ${esc(item.provider)}</small>`:''}<div class="recActions"><button data-feedback data-title="${esc(item.title)}" data-reaction="merken" class="${reaction==='merken'?'selected':''}">♡ Merken</button><button data-feedback data-title="${esc(item.title)}" data-reaction="nicht_interessant" class="${reaction==='nicht_interessant'?'selected':''}">Nicht interessant</button><button data-feedback data-title="${esc(item.title)}" data-reaction="gesehen" class="${reaction==='gesehen'?'selected':''}">Schon gesehen</button></div></div></article>`}).join('');return cards?`<section class="recommendations"><h3>Für euch ausgesucht</h3><p class="hint">Deine Antworten werden bei künftigen Empfehlungen berücksichtigt.</p><div class="recList">${cards}</div></section>`:''}
function renderReleaseGroup(group,items){if(!items.length)return '';const isQuiet=group==='nothing_new'||group==='upcoming';const content=isQuiet?`<div class="quietList">${items.map(quietCard).join('')}</div>`:`<div class="releaseGrid">${items.map(item=>readyOrRunningCard(item,group)).join('')}</div>`;return `<section class="releaseGroup ${isQuiet?'quiet':group}"><div class="releaseHead"><h3>${groupLabel(group)}</h3><p>${groupSubtitle(group)}</p></div>${content}</section>`}
function renderDailyDetails(){const daily=DATA.daily_check||{},anchor=document.querySelector('.daily');if(!anchor)return;let outlet=document.querySelector('#dailyUpdates');if(!outlet){outlet=document.createElement('div');outlet.id='dailyUpdates';outlet.className='dailyUpdates';anchor.insertAdjacentElement('afterend',outlet)}const groups={complete:[],ongoing:[],nothing_new:[],upcoming:[]};(daily.series_status||[]).forEach(item=>groups[releaseGroupFor(item)].push(item));const total=(daily.series_status||[]).length;if(!total){outlet.innerHTML='';return}const summary=`<div class="releaseSummary"><span><strong>${groups.complete.length}</strong> komplett bereit</span><span><strong>${groups.ongoing.length}</strong> läuft noch</span><span><strong>${groups.nothing_new.length+groups.upcoming.length}</strong> noch nicht vollständig neu</span></div>`;outlet.innerHTML=summary+renderReleaseGroup('complete',groups.complete)+renderReleaseGroup('ongoing',groups.ongoing)+renderReleaseGroup('upcoming',groups.upcoming)+renderReleaseGroup('nothing_new',groups.nothing_new)+recommendationBlock(daily);outlet.querySelectorAll('[data-open-series]').forEach(element=>element.addEventListener('click',()=>openSeriesDetail(element.dataset.openSeries)));outlet.querySelectorAll('[data-advance]').forEach(button=>button.addEventListener('click',()=>advance(button.dataset.advance)));outlet.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>editSeries(button.dataset.edit)));outlet.querySelectorAll('[data-feedback]').forEach(button=>button.addEventListener('click',()=>sendFeedback(button)));const meta=anchor.querySelector('.meta');if(meta)meta.textContent='Automatisch Dienstag & Freitag · manuell beliebig oft.';const button=q('#checkNow');if(button){button.disabled=!!daily.is_running||daily.state==='Gemini-Schlüssel fehlt';button.textContent=daily.is_running?'Gemini prüft …':'Jetzt prüfen'}}
</script>'''

CLARIFIED_OVERVIEW_UI = r'''<style>
/* Fachlich eindeutige Staffelzustände: grün nur für vollständig, orange nur für laufend. */
.releaseGroup.quiet{border-color:#e7dce3;background:linear-gradient(105deg,#fdfafd,#f9f4f7)}.releaseGroup.quiet .releaseHead h3{color:#5c425c}.releaseCard .dailyFacts span.complete{background:#e4f5e9;color:#286d4d}.releaseCard .dailyFacts span.running{background:#fff0e6;color:#a05b3e}.releaseCard .dailyFacts span.provider{background:#f1ebfb;color:#654c91}.releaseCard .dailyFacts span.episodes{background:#f5efff;color:#604c8f}.releaseCard.running .releaseTimeline{border-left-color:#e6a279;background:#fffaf6}.releaseCard.ready .releaseTimeline{border-left-color:#82bd96;background:#f8fdf9}.releaseAvailability{grid-column:1/-1;border-top:1px solid #eee2df;margin:0 2px;padding:8px 0 0;color:#7b6670;font-size:11px;line-height:1.35}.releaseAvailability strong{color:#573f55}.quietRow{align-items:flex-start}.quietRow .quietText{max-width:76%}.quietRow .quietExpected{margin-top:5px;color:#78646f;font-size:12px;line-height:1.32}.quietRow .quietExpected strong{color:#583d56}.quietBadge.nothing_new{background:#f1ebf4;color:#735a78}.releaseSummary span:nth-child(3){background:#f6eef4}.releaseSummary span:nth-child(3) strong{color:#68485f}@media(max-width:430px){.quietRow .quietText{max-width:70%}.releaseAvailability{font-size:10px}}
</style><script>
function releaseGroupFor(item){const expected=String(item.next_season_expected||'').toLowerCase(),direct=String(item.release_status||'');if(['complete','ongoing'].includes(direct))return direct;if(item.state==='upcoming'||direct==='upcoming'||/(staffel|season)\s*\d+.*(bestätigt|erneuert|angekündigt)|renewed|ordered/.test(expected))return 'upcoming';if(item.state==='nothing_new'||direct==='nothing_new')return 'nothing_new';const text=[item.available,item.remaining,item.detail,...(item.seasons||[]).map(row=>row.episodes)].filter(Boolean).join(' ').toLowerCase();if(/noch\s+\d+\s+folgen|folgen\s*1\s*[–-]\s*\d+\s*(?:von|\/)|läuft.*(?:folge|staffel)|aktuell.*(?:folge|abrufbar)|noch in ausstrahlung/.test(text))return 'ongoing';return 'complete'}
function displaySeason(item){const first=(item.seasons||[]).find(row=>row.state==='streamable'||row.state==='upcoming'||row.state==='not_streamable');const found=first&&String(first.season||'').trim();const match=String(item.available||'').match(/staffel\s*(\d+)/i);return found||((match||[])[1]||'')}
function availabilityFor(item){const values=[item.availability,...(item.seasons||[]).map(row=>row.availability)].filter(Boolean);const value=values.find(value=>/endet\s+am/i.test(value))||values.find(value=>/ablaufdatum|online|verfügbar.*bis/i.test(value));return value?`Online-Dauer: ${value}`:'Online-Dauer: Kein Ablaufdatum vom Anbieter veröffentlicht.'}
function scheduleFor(item){const rows=[];const next=String(item.next_episode||'').trim();const completion=String(item.estimated_complete||'').trim();if(next)rows.push(`<div><strong>Weiter geht es:</strong> ${esc(next)}</div>`);else rows.push('<div><strong>Weiter geht es:</strong> Kein deutscher Folgentermin veröffentlicht.</div>');if(completion)rows.push(`<div><strong>${item.completion_type==='confirmed'?'Staffel vollständig:':'Vollständigkeit:'}</strong> ${esc(completion)}</div>`);else rows.push('<div><strong>Vollständigkeit:</strong> Noch nicht einschätzbar.</div>');return rows.join('')}
function factsFor(item,group){const season=displaySeason(item),facts=[];if(group==='complete')facts.push({text:`Staffel ${season||'neu'} vollständig verfügbar`,kind:'complete'});if(group==='ongoing')facts.push({text:`Staffel ${season||'neu'} läuft gerade`,kind:'running'});if(item.available)facts.push({text:item.available,kind:'episodes'});if(item.remaining)facts.push({text:item.remaining,kind:'episodes'});if(item.provider)facts.push({text:`Deutsch bei ${item.provider}`,kind:'provider'});return facts.filter((fact,index,array)=>array.findIndex(other=>other.text===fact.text)===index)}
function openSeriesDetail(title){const item=(DATA.daily_check.series_status||[]).find(row=>row.title===title);if(!item)return;const own=DATA.series.find(row=>row.name===title);const group=releaseGroupFor(item),seasons=(item.seasons||[]).map(row=>`<article class="seasonRow"><strong>Staffel ${esc(row.season)}</strong><div><div class="seasonStatus ${esc(row.state)}">${seasonLabel(row.state)}</div><div class="seasonInfo">${esc([row.episodes,row.provider&&'Bei '+row.provider,row.availability||'Kein Ablaufdatum vom Anbieter veröffentlicht'].filter(Boolean).join(' · '))}</div></div></article>`).join('')||'<p class="modalIntro">Noch keine einzelnen Staffelinfos gefunden.</p>';const source=safeUrl(item.source_url),timeline=group==='ongoing'?scheduleFor(item):'',availability=availabilityFor(item),expected=item.next_season_expected?`<div class="detailTimeline"><strong>Nächste Staffel:</strong> ${esc(item.next_season_expected)}</div>`:'';const layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal" role="dialog" aria-modal="true" aria-label="Details zu ${esc(title)}"><div class="modalTop"><div><h2>${esc(title)}</h2><p class="modalIntro">Deutschsprachige Streamingangebote in Deutschland</p></div><button type="button" data-close>Schließen</button></div>${own?`<div class="personalStatus"><b>Euer Stand: ${esc(progress(own))}</b><span>${esc(nextEntry(own))}</span><div class="modalControls"><button class="primary" data-advance="${esc(own.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(own.id)}">Stand ändern</button></div></div>`:''}<div class="modalShow">${poster(item,'seriesPoster')}<div><b>${esc(item.available||'Aktueller Verfügbarkeitsstand')}</b><p class="modalIntro">${esc(item.detail)}</p><div class="dailyExpiry">${esc(availability)}</div></div></div>${timeline?`<div class="detailTimeline">${timeline}</div>`:''}${expected}<div class="seasonRows">${seasons}</div>${source?`<a class="modalSource" target="_blank" rel="noreferrer" href="${esc(source)}">Quelle öffnen ↗</a>`:''}</section>`;layer.addEventListener('click',event=>{if(event.target===layer||event.target.closest('[data-close]'))layer.remove()});layer.querySelectorAll('[data-advance]').forEach(button=>button.addEventListener('click',async()=>{await advance(button.dataset.advance);layer.remove()}));layer.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',async()=>{layer.remove();await editSeries(button.dataset.edit)}));document.body.append(layer)}
function readyOrRunningCard(item,group){const own=DATA.series.find(row=>row.name===item.title),facts=factsFor(item,group),timeline=group==='ongoing'?scheduleFor(item):'';return `<article class="releaseCard ${group}"><div class="releaseOpen" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}</div><div class="releaseBody releaseOpen" data-open-series="${esc(item.title)}"><h4>${esc(item.title)}</h4>${own?`<div class="releaseOwn">Euer Stand: ${esc(progress(own))} <span>· ${esc(nextEntry(own))}</span></div>`:''}<p class="releaseText">${esc(item.detail)}</p>${facts.length?`<div class="dailyFacts">${facts.map(fact=>`<span class="${fact.kind}">${esc(fact.text)}</span>`).join('')}</div>`:''}${timeline?`<div class="releaseTimeline">${timeline}</div>`:''}</div>${actionsForOwnSeries(own)}<div class="releaseAvailability"><strong>${esc(availabilityFor(item))}</strong></div></article>`}
function quietCard(item){const own=DATA.series.find(row=>row.name===item.title),group=releaseGroupFor(item),isUpcoming=group==='upcoming',expected=item.next_season_expected||(isUpcoming?'Angekündigter Start wird geprüft.':'Noch keine neue Staffel angekündigt.');return `<article class="quietRow" data-open-series="${esc(item.title)}"><div class="quietText"><b>${esc(item.title)}</b><span>${own?`Euer Stand: ${esc(progress(own))}`:esc(item.detail)}</span><div class="quietExpected"><strong>${isUpcoming?'Bestätigt:':'Nächste Staffel:'}</strong> ${esc(expected)}</div></div><span class="quietBadge ${group}">${isUpcoming?'angekündigt':'nichts neu'}</span></article>`}
function renderDailyDetails(){const daily=DATA.daily_check||{},anchor=document.querySelector('.daily'),openSection=document.querySelector('#watching')?.closest('.section');if(!anchor)return;let outlet=document.querySelector('#dailyUpdates');if(!outlet){outlet=document.createElement('div');outlet.id='dailyUpdates';outlet.className='dailyUpdates';anchor.insertAdjacentElement('afterend',outlet)}const groups={complete:[],ongoing:[],nothing_new:[],upcoming:[]};(daily.series_status||[]).forEach(item=>groups[releaseGroupFor(item)].push(item));const total=(daily.series_status||[]).length;if(openSection)openSection.style.display=total?'none':'';if(!total){outlet.innerHTML='';return}const quiet=groups.nothing_new.concat(groups.upcoming);const summary=`<div class="releaseSummary"><span><strong>${groups.complete.length}</strong> offen und komplett verfügbar</span><span><strong>${groups.ongoing.length}</strong> laufen gerade</span><span><strong>${quiet.length}</strong> angekündigt oder nichts neu</span></div>`;const full=groups.complete.length?`<section class="releaseGroup ready"><div class="releaseHead"><h3>Noch offen · komplett verfügbar</h3><p>Diese Staffeln könnt ihr jetzt vollständig nachholen.</p></div><div class="releaseGrid">${groups.complete.map(item=>readyOrRunningCard(item,'complete')).join('')}</div></section>`:'';const running=groups.ongoing.length?`<section class="releaseGroup running"><div class="releaseHead"><h3>Läuft gerade · weitere Folgen kommen</h3><p>Nächster Termin und wann die laufende Staffel fertig ist.</p></div><div class="releaseGrid">${groups.ongoing.map(item=>readyOrRunningCard(item,'ongoing')).join('')}</div></section>`:'';const noNew=quiet.length?`<section class="releaseGroup quiet"><div class="releaseHead"><h3>Angekündigt oder noch nichts Neues</h3><p>Hier steht, was später kommt, ohne eure offenen Staffeln zu verdrängen.</p></div><div class="quietList">${quiet.map(quietCard).join('')}</div></section>`:'';outlet.innerHTML=summary+full+running+noNew+recommendationBlock(daily);outlet.querySelectorAll('[data-open-series]').forEach(element=>element.addEventListener('click',()=>openSeriesDetail(element.dataset.openSeries)));outlet.querySelectorAll('[data-advance]').forEach(button=>button.addEventListener('click',()=>advance(button.dataset.advance)));outlet.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>editSeries(button.dataset.edit)));outlet.querySelectorAll('[data-feedback]').forEach(button=>button.addEventListener('click',()=>sendFeedback(button)));const meta=anchor.querySelector('.meta');if(meta)meta.textContent='Automatisch Dienstag & Freitag · manuell beliebig oft.';const button=q('#checkNow');if(button){button.disabled=!!daily.is_running||daily.state==='Gemini-Schlüssel fehlt';button.textContent=daily.is_running?'Gemini prüft …':'Jetzt prüfen'}}
</script>'''

RECOMMENDATION_DETAILS_UI = r'''<style>
.recOpen{cursor:pointer}.recOpen:hover b{text-decoration:underline}.trailerLink{display:inline-block;margin:8px 8px 0 0;border:1px solid #d8c5ca;background:#fffaf7;color:#594553;border-radius:999px;padding:9px 12px;font-weight:850;text-decoration:none;font-size:12px}.trailerLink.primary{background:linear-gradient(110deg,#7355c7,#b154ae);border-color:#7355c7;color:#fff}
</style><script>
function trailerSearchUrl(title){return `https://www.youtube.com/results?search_query=${encodeURIComponent(title+' Trailer deutsch')}`}
function openRecommendationDetailByTitle(title){const item=(DATA.daily_check.recommendations||[]).find(row=>row.title===title);if(!item)return;const reaction=feedbackFor(item.title),source=safeUrl(item.source_url),layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal" role="dialog" aria-modal="true" aria-label="Empfehlung ${esc(item.title)}"><div class="modalTop"><div><h2>${esc(item.title)}</h2><p class="modalIntro">Empfehlung auf Basis eurer Serienliste</p></div><button type="button" data-close>Schließen</button></div><div class="modalShow">${poster(item,'seriesPoster')}<div><b>${item.provider?`Deutsch bei ${esc(item.provider)}`:'Anbieter wird geprüft'}</b><p class="modalIntro">${esc(item.detail)}</p><a class="trailerLink primary" target="_blank" rel="noreferrer" href="${esc(trailerSearchUrl(item.title))}">Trailer suchen</a>${source?`<a class="trailerLink" target="_blank" rel="noreferrer" href="${esc(source)}">Quelle öffnen</a>`:''}</div></div><div class="recActions"><button data-feedback data-title="${esc(item.title)}" data-reaction="merken" class="${reaction==='merken'?'selected':''}">♡ Merken</button><button data-feedback data-title="${esc(item.title)}" data-reaction="nicht_interessant" class="${reaction==='nicht_interessant'?'selected':''}">Nicht interessant</button><button data-feedback data-title="${esc(item.title)}" data-reaction="gesehen" class="${reaction==='gesehen'?'selected':''}">Schon gesehen</button></div></section>`;layer.addEventListener('click',event=>{if(event.target===layer||event.target.closest('[data-close]'))layer.remove()});layer.querySelectorAll('[data-feedback]').forEach(button=>button.addEventListener('click',async()=>{await sendFeedback(button);layer.remove()}));document.body.append(layer)}
recommendationBlock=function(daily){const cards=(daily.recommendations||[]).map(item=>{const reaction=feedbackFor(item.title);return `<article class="rec"><div class="recOpen" data-rec-title="${esc(item.title)}">${poster(item,'recPoster')}</div><div><b class="recOpen" data-rec-title="${esc(item.title)}">${esc(item.title)}</b><p class="recOpen" data-rec-title="${esc(item.title)}">${esc(item.detail)}</p>${item.provider?`<small>Deutsch bei ${esc(item.provider)}</small>`:''}<div class="recActions"><button data-feedback data-title="${esc(item.title)}" data-reaction="merken" class="${reaction==='merken'?'selected':''}">♡ Merken</button><button data-feedback data-title="${esc(item.title)}" data-reaction="nicht_interessant" class="${reaction==='nicht_interessant'?'selected':''}">Nicht interessant</button><button data-feedback data-title="${esc(item.title)}" data-reaction="gesehen" class="${reaction==='gesehen'?'selected':''}">Schon gesehen</button></div></div></article>`}).join('');return cards?`<section class="recommendations"><h3>Für euch ausgesucht</h3><p class="hint">Klick auf eine Empfehlung zeigt Details und Trailer-Suche.</p><div class="recList">${cards}</div></section>`:''}
const renderDailyDetailsBeforeRecommendationDetails=renderDailyDetails;
renderDailyDetails=function(){renderDailyDetailsBeforeRecommendationDetails();document.querySelectorAll('[data-rec-title]').forEach(element=>element.addEventListener('click',event=>{event.stopPropagation();openRecommendationDetailByTitle(element.dataset.recTitle)}))}
</script>'''

ARCHIVE_SERIES_UI = r'''<script>
/* Bereits automatisch abgelegte Serien verschwinden sofort aus dem Tagesregal. */
const renderDailyDetailsBeforeArchiveFilter=renderDailyDetails;
renderDailyDetails=function(){const daily=DATA.daily_check||{},originalRows=daily.series_status;if(Array.isArray(originalRows)){const activeNames=new Set((DATA.series||[]).filter(row=>row.status==='watching').map(row=>row.name));daily.series_status=originalRows.filter(row=>activeNames.has(row.title));renderDailyDetailsBeforeArchiveFilter();daily.series_status=originalRows}else{renderDailyDetailsBeforeArchiveFilter()}const archived=(daily.archived||[]).filter(Boolean);const summary=document.querySelector('.releaseSummary');if(summary&&archived.length)summary.insertAdjacentHTML('beforeend',`<span>✓ Abgelegt: ${esc(archived.join(', '))}</span>`)};
</script>'''

CANCEL_CHECK_UI = r'''<style>.dailyActions .cancelCheck{color:#9d3f52;border-color:#d8adb7;background:#fff8f8}</style><script>
const renderDailyDetailsBeforeCancelButton=renderDailyDetails;
renderDailyDetails=function(){renderDailyDetailsBeforeCancelButton();const running=!!(DATA.daily_check||{}).is_running,checkButton=q('#checkNow');let cancelButton=q('#cancelCheck');if(running&&checkButton&&!cancelButton){cancelButton=document.createElement('button');cancelButton.type='button';cancelButton.id='cancelCheck';cancelButton.className='cancelCheck';cancelButton.textContent='Prüfung abbrechen';cancelButton.onclick=cancelCheck;checkButton.insertAdjacentElement('afterend',cancelButton)}if(!running&&cancelButton)cancelButton.remove()};
</script>'''

PROGRESS_CHECK_UI = r'''<script>
const renderDailyDetailsBeforeProgressLabel=renderDailyDetails;
renderDailyDetails=function(){renderDailyDetailsBeforeProgressLabel();const daily=DATA.daily_check||{},button=q('#checkNow');if(button&&daily.is_running&&daily.progress_total){button.textContent=`Gemini prüft ${daily.progress_done}/${daily.progress_total} …`}}
</script>'''

CONSISTENT_RUNNING_UI = r'''<style>
.releaseAvailability{display:grid;gap:4px}.seasonAnnouncement{color:#5f4660;font-size:11px;line-height:1.35}.seasonAnnouncement strong{color:#473047}.releaseTimeline .unknown{color:#9a7c87}.releaseCard .dailyFacts span.missing{background:#f7edf1;color:#8b6876}
</style><script>
function cleanExpectedSeason(value){const text=String(value||'').trim();return text&&!/noch\s+keine\s+neue\s+staffel|keine\s+folgestaffel|nicht\s+angekündigt/i.test(text)?text:''}
function seasonAnnouncementFor(item){const text=cleanExpectedSeason(item.next_season_expected);return text?`Nächste Staffel: ${text}`:''}
function remainingLineFor(item,group){const remaining=String(item.remaining||'').trim();const text=[remaining,item.available,item.detail,...(item.seasons||[]).map(row=>row.episodes)].filter(Boolean).join(' ');const match=text.match(/noch\s+\d+\s+(?:folgen|episoden)(?:\s+von\s+staffel\s+\d+)?/i);if(match)return match[0].replace(/^n/,'N');const countMatch=text.match(/folgen?\s*1\s*[–-]\s*(\d+)\s*(?:von|\/)\s*(\d+)/i);if(countMatch){const shown=Number(countMatch[1]),total=Number(countMatch[2]);if(Number.isFinite(shown)&&Number.isFinite(total)&&total>shown)return `Noch ${total-shown} Folgen`}if(/anzahl\s+noch\s+nicht\s+veröffentlicht|folgenzahl\s+unklar/i.test(remaining))return 'Anzahl noch nicht veröffentlicht';if(group==='ongoing')return 'Folgenzahl wird neu geprüft';if(group==='complete')return remaining&&/komplett|vollständig/i.test(remaining)?remaining:'Komplett verfügbar';return remaining||'keine neue Folge'}
function availabilityBlockFor(item){const announcement=seasonAnnouncementFor(item);return `<div class="releaseAvailability"><strong>${esc(availabilityFor(item))}</strong>${announcement?`<div class="seasonAnnouncement"><strong>${esc(announcement)}</strong></div>`:''}</div>`}
function factsFor(item,group){const season=displaySeason(item),facts=[];if(group==='complete')facts.push({text:`Staffel ${season||'neu'} vollständig verfügbar`,kind:'complete'});if(group==='ongoing')facts.push({text:`Staffel ${season||'neu'} läuft gerade`,kind:'running'});if(item.available)facts.push({text:item.available,kind:'episodes'});if(group!=='ongoing'&&item.remaining)facts.push({text:item.remaining,kind:'episodes'});if(item.provider)facts.push({text:`Deutsch bei ${item.provider}`,kind:'provider'});return facts.filter((fact,index,array)=>array.findIndex(other=>other.text===fact.text)===index)}
function scheduleFor(item){const group=releaseGroupFor(item),rows=[];const next=String(item.next_episode||'').trim();const completion=String(item.estimated_complete||'').trim();if(group==='ongoing'){rows.push(next?`<div><strong>Weiter geht es:</strong> ${esc(next)}</div>`:'<div><strong>Weiter geht es:</strong> <span class="unknown">Kein deutscher Folgentermin veröffentlicht</span></div>');rows.push(`<div><strong>Noch offen:</strong> ${esc(remainingLineFor(item,group))}</div>`);rows.push(completion?`<div><strong>Staffel fertig:</strong> ${esc(completion.replace(/^Staffel voraussichtlich vollständig/i,'Staffel voraussichtlich fertig'))}</div>`:'<div><strong>Staffel fertig:</strong> <span class="unknown">wird neu geprüft</span></div>')}else if(group==='complete'){rows.push(`<div><strong>Noch offen:</strong> ${esc(remainingLineFor(item,group))}</div>`)}return rows.join('')}
function readyOrRunningCard(item,group){const own=DATA.series.find(row=>row.name===item.title),facts=factsFor(item,group),timeline=scheduleFor(item);return `<article class="releaseCard ${group}"><div class="releaseOpen" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}</div><div class="releaseBody releaseOpen" data-open-series="${esc(item.title)}"><h4>${esc(item.title)}</h4>${own?`<div class="releaseOwn">Euer Stand: ${esc(progress(own))} <span>· ${esc(nextEntry(own))}</span></div>`:''}<p class="releaseText">${esc(item.detail)}</p>${facts.length?`<div class="dailyFacts">${facts.map(fact=>`<span class="${fact.kind}">${esc(fact.text)}</span>`).join('')}</div>`:''}${timeline?`<div class="releaseTimeline">${timeline}</div>`:''}</div>${actionsForOwnSeries(own)}${availabilityBlockFor(item)}</article>`}
</script>'''

PAGE = PAGE.replace('<span class="meta">Automatisch Dienstag & Freitag</span>', '<div class="dailyActions"><button id="checkNow" onclick="checkNow()">Jetzt prüfen</button><span class="meta">Automatisch Dienstag & Freitag</span></div>')
PAGE = PAGE.replace("</body>", EXTRA_SERIES_UI + "</body>")
PAGE = PAGE.replace("</body>", PROGRESS_SERIES_UI + "</body>")
PAGE = PAGE.replace("</body>", OVERVIEW_SERIES_UI + "</body>")
PAGE = PAGE.replace("</body>", CLARIFIED_OVERVIEW_UI + "</body>")
# Empfehlungen entfernt in 0.1.18
PAGE = PAGE.replace("</body>", ARCHIVE_SERIES_UI + "</body>")
PAGE = PAGE.replace("</body>", CANCEL_CHECK_UI + "</body>")
PAGE = PAGE.replace("</body>", PROGRESS_CHECK_UI + "</body>")
PAGE = PAGE.replace("</body>", CONSISTENT_RUNNING_UI + "</body>")
SERIES_018_UI = r'''<style>
.recommendations,.recList,.rec{display:none!important}.dailyActions{flex-direction:row!important;align-items:center!important;flex-wrap:wrap}.notifyButton{background:#fff8ef!important;border-color:#e9c9a9!important;color:#7b4a36!important}.settingsGrid{display:grid;gap:10px;margin:14px 0}.settingRow{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:11px 12px;border:1px solid #eadeda;border-radius:12px;background:#fffdfa}.settingRow b{display:block;color:#4a334e}.settingRow span{display:block;color:#786b75;font-size:12px;margin-top:3px}.settingRow input{width:22px;height:22px;accent-color:#7456c7}.waitBadge{display:inline-flex;margin-top:7px;padding:5px 8px;border-radius:999px;background:#fff1d9;color:#8b5b20;font-size:11px;font-weight:850}.waitBadge.ready{background:#e6f6ed;color:#287050}.warningBadge{display:inline-flex;margin-top:7px;padding:5px 8px;border-radius:999px;background:#fff0df;color:#955f32;font-size:11px;font-weight:800}.checkedLine{font-size:11px;color:#9a8993;margin-top:9px}.quietExpected{margin-top:5px}.quietBadge.upcoming{background:#f5efff!important;color:#674a96!important}.quietBadge.nothing_new{background:#f1efed!important;color:#736c70!important}.releaseGroup.complete .releaseHead h3{color:#347355}.releaseGroup.ongoing .releaseHead h3{color:#9b583c}.releaseGroup.quiet .releaseHead h3{color:#6a5296}.releaseSummary span:first-child{background:#edf8f1}.releaseSummary span:nth-child(2){background:#fff2e9}.releaseSummary span:nth-child(3){background:#f5f0fb}.waitToggle{font-size:11px!important}.modalNote{padding:10px 12px;border-radius:12px;background:#f7f1ff;color:#5e4a78;font-size:12px;margin:10px 0}.notificationHint{color:#7e6f78;font-size:12px;line-height:1.4}.settingsActions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.daily .meta{white-space:nowrap}@media(max-width:700px){.dailyActions{align-items:flex-start!important}.daily .meta{white-space:normal}}
</style><script>
function waitLabel(own,group){if(!own||!own.wait_until_complete)return '';return group==='complete'?'<span class="waitBadge ready">✅ Wartemodus erfüllt · Staffel komplett</span>':'<span class="waitBadge">⏳ Warten bis Staffel komplett</span>'}
async function toggleWait(id,current){await api('/api/series/'+id+'/preferences',{wait_until_complete:!current})}
async function saveNotificationSettings(layer){const payload={};layer.querySelectorAll('[data-notify-key]').forEach(input=>payload[input.dataset.notifyKey]=input.checked);const response=await fetch('/api/notification-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!response.ok){alert('Einstellungen konnten nicht gespeichert werden.');return}DATA=await response.json();layer.remove();render()}
async function testNotification(){const response=await fetch('/api/notification-test',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok){const data=await response.json().catch(()=>({}));alert(data.error||'Test-Push fehlgeschlagen.');return}alert('Test-Push wurde gesendet.')}
function openNotificationSettings(){const s=DATA.notification_settings||{};const rows=[['enabled','Benachrichtigungen insgesamt','Hauptschalter für Serien-Pushs.'],['season_complete','Staffel vollständig','Melden, wenn eine offene Staffel komplett auf Deutsch verfügbar ist.'],['new_season_confirmed','Neue Staffel bestätigt','Einmalig melden, wenn eine Folgestaffel belastbar bestätigt wurde.'],['season_started','Staffel gestartet','Einmalig melden, wenn die erste deutsche Folge einer neuen Staffel verfügbar ist.'],['series_ended','Serie beendet','Melden, wenn offiziell feststeht, dass keine weitere Staffel folgt.'],['start_date_known','Starttermin erstmals bekannt','Optional: auch einen neu bekannt gewordenen Starttermin melden.']];const layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal"><div class="modalTop"><div><h2>Benachrichtigungen</h2><p class="modalIntro">Neue einzelne Folgen lösen bewusst keinen Push aus.</p></div><button data-close>Schließen</button></div><div class="settingsGrid">${rows.map(([key,title,desc])=>`<label class="settingRow"><div><b>${esc(title)}</b><span>${esc(desc)}</span></div><input type="checkbox" data-notify-key="${key}" ${s[key]?'checked':''}></label>`).join('')}</div><p class="notificationHint">Beim ersten vollständigen Check nach diesem Update wird nur eine Ausgangslage gespeichert. Bereits bekannte Staffeln erzeugen dadurch keine Push-Flut.</p><div class="settingsActions"><button class="primary" data-save>Speichern</button><button data-test>Test-Push</button></div></section>`;layer.addEventListener('click',e=>{if(e.target===layer||e.target.closest('[data-close]'))layer.remove()});layer.querySelector('[data-save]').onclick=()=>saveNotificationSettings(layer);layer.querySelector('[data-test]').onclick=testNotification;document.body.append(layer)}
function seasonStatus018(row){if(row.complete)return '✓ vollständig';if(row.state==='ongoing')return '▶ läuft gerade';return seasonLabel(row.state)}
function openSeriesDetail(title){const item=(DATA.daily_check.series_status||[]).find(row=>row.title===title);if(!item)return;const own=DATA.series.find(row=>row.name===title),group=releaseGroupFor(item);const seasons=(item.seasons||[]).map(row=>{const counts=(row.available_episodes!=null&&row.total_episodes!=null)?`${row.available_episodes}/${row.total_episodes} Folgen`:(row.available_episodes!=null?`${row.available_episodes} Folgen verfügbar`:row.episodes);return `<article class="seasonRow"><strong>Staffel ${esc(row.season)}</strong><div><div class="seasonStatus ${esc(row.state)}">${esc(seasonStatus018(row))}</div><div class="seasonInfo">${esc([counts,row.provider&&'Bei '+row.provider,row.next_episode_date&&'Nächste Folge '+row.next_episode_date,row.season_finale_date&&'Staffelfinale '+row.season_finale_date,row.complete_available_date&&'Komplett verfügbar ab '+row.complete_available_date,row.start_date&&'Start '+row.start_date,row.availability].filter(Boolean).join(' · ')||'Wird weiter geprüft.')}</div></div></article>`}).join('')||'<p class="modalIntro">Noch keine einzelnen Staffelinfos gefunden.</p>';const source=safeUrl(item.source_url),warnings=item.warnings||[],layer=document.createElement('div');layer.className='modalShade';layer.innerHTML=`<section class="seriesModal"><div class="modalTop"><div><h2>${esc(title)}</h2><p class="modalIntro">${esc(groupLabel(group))}</p></div><button data-close>Schließen</button></div>${own?`<div class="personalStatus"><b>Euer Stand: ${esc(progress(own))}</b><span>Dieser Sehstand wird niemals von Gemini verändert.</span><div class="modalControls"><button class="primary" data-advance="${esc(own.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(own.id)}">Stand ändern</button>${group==='ongoing'?`<button class="waitToggle" data-wait="${esc(own.id)}">${own.wait_until_complete?'✓ Warten bis komplett':'⏳ Warten bis komplett'}</button>`:''}</div></div>`:''}<div class="modalShow">${poster(item,'seriesPoster')}<div><b>${esc(item.available||'Aktueller Stand')}</b><p class="modalIntro">${esc(item.detail||'')}</p>${item.next_season_expected?`<div class="modalNote">${esc(item.next_season_expected)}</div>`:''}${warnings.length?`<div class="warningBadge">⚠️ ${esc(warnings[0])}</div>`:''}<div class="checkedLine">Zuletzt geprüft: ${esc(DATA.daily_check.last_checked_at||item.checked_at||'unbekannt')}</div></div></div><div class="seasonRows">${seasons}</div>${source?`<a class="modalSource" target="_blank" rel="noreferrer" href="${esc(source)}">Quelle öffnen ↗</a>`:''}</section>`;layer.addEventListener('click',e=>{if(e.target===layer||e.target.closest('[data-close]'))layer.remove()});layer.querySelectorAll('[data-advance]').forEach(b=>b.onclick=async()=>{await advance(b.dataset.advance);layer.remove()});layer.querySelectorAll('[data-edit]').forEach(b=>b.onclick=async()=>{layer.remove();await editSeries(b.dataset.edit)});layer.querySelectorAll('[data-wait]').forEach(b=>b.onclick=async()=>{await toggleWait(b.dataset.wait,!!own.wait_until_complete);layer.remove()});document.body.append(layer)}
function releaseGroupFor(item){return ['complete','ongoing','upcoming','nothing_new'].includes(String(item.release_status||''))?item.release_status:'nothing_new'}
function groupLabel(group){return({complete:'Bereit zum Schauen · komplett verfügbar',ongoing:'Läuft gerade',upcoming:'Aktuell auf Stand · neue Staffel angekündigt',nothing_new:'Aktuell auf Stand'})[group]||'Aktueller Stand'}
function groupSubtitle(group){return({complete:'Von euch noch offene Staffeln, die vollständig auf Deutsch verfügbar sind.',ongoing:'Hier erscheinen aktuell laufende deutsche Staffeln und ihre verbleibenden Folgen.',upcoming:'Alles derzeit Verfügbare ist gesehen; die nächste Staffel ist bestätigt oder angekündigt.',nothing_new:'Alles derzeit Verfügbare ist gesehen; aktuell gibt es keine neue deutsche Staffel.'})[group]||''}
function factsFor018(item,group){const facts=[];if(item.available)facts.push(item.available);if(group==='ongoing'&&item.remaining)facts.push(item.remaining);if(item.provider)facts.push(`Deutsch bei ${item.provider}`);if(item.next_season_expected&&!/noch keine/i.test(item.next_season_expected))facts.push(item.next_season_expected);return [...new Set(facts)]}
function seasonFinale018(item){const rows=item.seasons||[],ongoing=rows.find(row=>row.state==='ongoing'&&row.season_finale_date),dated=rows.find(row=>row.season_finale_date);return String((ongoing||dated||{}).season_finale_date||'').trim()}
function schedule018(item,group){if(group!=='ongoing')return '';const rows=[];if(item.next_episode)rows.push(`<div><strong>Weiter geht es:</strong> ${esc(item.next_episode.replace(/^Nächste Folge am\s*/i,''))}</div>`);rows.push(`<div><strong>Noch offen:</strong> ${esc(item.remaining||'Anzahl noch nicht veröffentlicht')}</div>`);const completion=String(item.estimated_complete||'').trim()||(seasonFinale018(item)?`Staffel fertig am ${seasonFinale018(item)}`:'');const finaleLabel=item.completion_type==='estimated'?'Voraussichtlich vollständig ausgestrahlt':'Staffel vollständig ausgestrahlt';rows.push(`<div><strong>${finaleLabel}:</strong> ${esc(completion||'Datum der letzten Folge noch nicht verlässlich veröffentlicht')}</div>`);return rows.join('')}
function readyOrRunningCard(item,group){const own=DATA.series.find(row=>row.name===item.title),facts=factsFor018(item,group),timeline=schedule018(item,group),warnings=item.warnings||[];return `<article class="releaseCard ${group}"><div class="releaseOpen" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}</div><div class="releaseBody releaseOpen" data-open-series="${esc(item.title)}"><h4>${esc(item.title)}</h4>${own?`<div class="releaseOwn">Euer Stand: ${esc(progress(own))}</div>`:''}<p class="releaseText">${esc(item.detail||'')}</p>${facts.length?`<div class="dailyFacts">${facts.map(f=>`<span>${esc(f)}</span>`).join('')}</div>`:''}${waitLabel(own,group)}${warnings.length?`<div class="warningBadge">⚠️ Angabe geprüft/korrigiert</div>`:''}${timeline?`<div class="releaseTimeline">${timeline}</div>`:''}<div class="checkedLine">${item.checked_at?'Geprüft: '+esc(item.checked_at):'Noch nicht neu geprüft'}</div></div>${own?`<div class="dailyControls"><button class="primary" data-advance="${esc(own.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(own.id)}">Stand ändern</button>${group==='ongoing'?`<button class="waitToggle" data-wait="${esc(own.id)}">${own.wait_until_complete?'✓ Warten':'⏳ Warten'}</button>`:''}</div>`:''}</article>`}
function quietCard(item){const own=DATA.series.find(row=>row.name===item.title),group=releaseGroupFor(item),expected=item.next_season_expected||'Noch keine neue Staffel angekündigt';return `<article class="quietRow" data-open-series="${esc(item.title)}"><div class="quietText"><b>${esc(item.title)}</b><span>${own?`Euer Stand: ${esc(progress(own))}`:esc(item.detail||'')}</span><div class="quietExpected"><strong>${group==='upcoming'?'Bestätigt:':'Stand:'}</strong> ${esc(expected)}</div>${item.warnings&&item.warnings.length?'<div class="warningBadge">⚠️ Plausibilitätskorrektur</div>':''}</div><span class="quietBadge ${group}">${group==='upcoming'?'angekündigt':'auf Stand'}</span></article>`}
function renderDailyDetails(){const daily=DATA.daily_check||{},anchor=document.querySelector('.daily'),openSection=document.querySelector('#watching')?.closest('.section');if(!anchor)return;let outlet=document.querySelector('#dailyUpdates');if(!outlet){outlet=document.createElement('div');outlet.id='dailyUpdates';outlet.className='dailyUpdates';anchor.insertAdjacentElement('afterend',outlet)}const groups={complete:[],ongoing:[],upcoming:[],nothing_new:[]};(daily.series_status||[]).forEach(item=>groups[releaseGroupFor(item)].push(item));groups.complete.sort((a,b)=>{const aw=DATA.series.find(s=>s.name===a.title)?.wait_until_complete?0:1,bw=DATA.series.find(s=>s.name===b.title)?.wait_until_complete?0:1;return aw-bw||a.title.localeCompare(b.title)});const total=(daily.series_status||[]).length;if(openSection)openSection.style.display=total?'none':'';if(!total){outlet.innerHTML='';return}const quiet=groups.upcoming.concat(groups.nothing_new);const summary=`<div class="releaseSummary"><span><strong>${groups.complete.length}</strong> bereit zum Schauen</span><span><strong>${groups.ongoing.length}</strong> laufen gerade</span><span><strong>${quiet.length}</strong> auf Stand / angekündigt</span></div>`;const complete=groups.complete.length?`<section class="releaseGroup complete"><div class="releaseHead"><h3>${groupLabel('complete')}</h3><p>${groupSubtitle('complete')}</p></div><div class="releaseGrid">${groups.complete.map(i=>readyOrRunningCard(i,'complete')).join('')}</div></section>`:'';const ongoing=groups.ongoing.length?`<section class="releaseGroup ongoing"><div class="releaseHead"><h3>${groupLabel('ongoing')}</h3><p>${groupSubtitle('ongoing')}</p></div><div class="releaseGrid">${groups.ongoing.map(i=>readyOrRunningCard(i,'ongoing')).join('')}</div></section>`:'';const upcoming=groups.upcoming.length?`<section class="releaseGroup quiet"><div class="releaseHead"><h3>${groupLabel('upcoming')}</h3><p>${groupSubtitle('upcoming')}</p></div><div class="quietList">${groups.upcoming.map(quietCard).join('')}</div></section>`:'';const nothing=groups.nothing_new.length?`<section class="releaseGroup quiet"><div class="releaseHead"><h3>${groupLabel('nothing_new')}</h3><p>${groupSubtitle('nothing_new')}</p></div><div class="quietList">${groups.nothing_new.map(quietCard).join('')}</div></section>`:'';outlet.innerHTML=summary+complete+ongoing+upcoming+nothing;outlet.querySelectorAll('[data-open-series]').forEach(el=>el.onclick=()=>openSeriesDetail(el.dataset.openSeries));outlet.querySelectorAll('[data-advance]').forEach(b=>b.onclick=()=>advance(b.dataset.advance));outlet.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>editSeries(b.dataset.edit));outlet.querySelectorAll('[data-wait]').forEach(b=>b.onclick=()=>{const own=DATA.series.find(s=>s.id===b.dataset.wait);toggleWait(b.dataset.wait,!!own?.wait_until_complete)});let actions=anchor.querySelector('.dailyActions');if(actions&&!actions.querySelector('.notifyButton')){const nb=document.createElement('button');nb.type='button';nb.className='notifyButton';nb.textContent='🔔 Benachrichtigungen';nb.onclick=openNotificationSettings;actions.append(nb)}const meta=anchor.querySelector('.meta');if(meta)meta.textContent='Automatisch Dienstag & Freitag · manuell beliebig oft.';const button=q('#checkNow');if(button){button.disabled=!!daily.is_running||daily.state==='Gemini-Schlüssel fehlt';button.textContent=daily.is_running&&daily.progress_total?`Gemini prüft ${daily.progress_done}/${daily.progress_total} …`:daily.is_running?'Gemini prüft …':'Jetzt prüfen'}}
</script>'''
PAGE = PAGE.replace("</body>", SERIES_018_UI + "</body>")

SERIES_028_UI = r'''<style>
.geminiSeriesButton{background:#f4edff!important;border-color:#cdbce9!important;color:#5a3e8f!important}.geminiSeriesButton:disabled{opacity:.58;cursor:wait}.dailyControls{display:flex;gap:8px;flex-wrap:wrap}
</style><script>
async function checkSingleSeries(id){const button=document.querySelector(`[data-check-series="${id}"]`);if(button)button.disabled=true;const response=await fetch('/api/series/'+encodeURIComponent(id)+'/check',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const result=await response.json().catch(()=>({}));if(!response.ok){alert(result.error||'Die Einzelprüfung konnte nicht gestartet werden.');if(button)button.disabled=false;return}DATA=result;render();waitForCheck()}
function targetedCheckButton(own){return own?`<button class="geminiSeriesButton" data-check-series="${esc(own.id)}" ${DATA.daily_check&&DATA.daily_check.is_running?'disabled':''}>✨ Bei Gemini prüfen</button>`:''}
function readyOrRunningCard(item,group){const own=DATA.series.find(row=>row.name===item.title),facts=factsFor018(item,group),timeline=schedule018(item,group),warnings=item.warnings||[];return `<article class="releaseCard ${group}"><div class="releaseOpen" data-open-series="${esc(item.title)}">${poster(item,'seriesPoster')}</div><div class="releaseBody releaseOpen" data-open-series="${esc(item.title)}"><h4>${esc(item.title)}</h4>${own?`<div class="releaseOwn">Euer Stand: ${esc(progress(own))}</div>`:''}<p class="releaseText">${esc(item.detail||'')}</p>${facts.length?`<div class="dailyFacts">${facts.map(f=>`<span>${esc(f)}</span>`).join('')}</div>`:''}${waitLabel(own,group)}${warnings.length?`<div class="warningBadge">⚠️ Angabe geprüft/korrigiert</div>`:''}${timeline?`<div class="releaseTimeline">${timeline}</div>`:''}<div class="checkedLine">${item.checked_at?'Geprüft: '+esc(item.checked_at):'Noch nicht neu geprüft'}</div></div>${own?`<div class="dailyControls"><button class="primary" data-advance="${esc(own.id)}">✓ Nächste Folge gesehen</button><button data-edit="${esc(own.id)}">Stand ändern</button>${targetedCheckButton(own)}${group==='ongoing'?`<button class="waitToggle" data-wait="${esc(own.id)}">${own.wait_until_complete?'✓ Warten':'⏳ Warten'}</button>`:''}</div>`:''}</article>`}
function quietCard(item){const own=DATA.series.find(row=>row.name===item.title),group=releaseGroupFor(item),expected=item.next_season_expected||'Noch keine neue Staffel angekündigt';return `<article class="quietRow"><div class="quietText releaseOpen" data-open-series="${esc(item.title)}"><b>${esc(item.title)}</b><span>${own?`Euer Stand: ${esc(progress(own))}`:esc(item.detail||'')}</span><div class="quietExpected"><strong>${group==='upcoming'?'Bestätigt:':'Stand:'}</strong> ${esc(expected)}</div>${item.warnings&&item.warnings.length?'<div class="warningBadge">⚠️ Plausibilitätskorrektur</div>':''}</div><div class="dailyControls">${targetedCheckButton(own)}</div><span class="quietBadge ${group}">${group==='upcoming'?'angekündigt':'auf Stand'}</span></article>`}
const renderDailyDetails028=renderDailyDetails;renderDailyDetails=function(){renderDailyDetails028();document.querySelectorAll('[data-check-series]').forEach(button=>button.onclick=event=>{event.stopPropagation();checkSingleSeries(button.dataset.checkSeries)})}
</script>'''
PAGE = PAGE.replace("</body>", SERIES_028_UI + "</body>")

SERIES_031_UI = r'''<style>
/* Die Rohkarten erscheinen bereits oben als Serienkarten; unten bleibt nur das Eingabeformular. */
#watching{display:none!important}.dailyActions .addSeriesShortcut{background:#edf8f1!important;border-color:#b8dec7!important;color:#2d6c4c!important}
.section.seriesEntry{margin-top:20px}
</style><script>
function openAddSeries(){const section=document.querySelector('#watching')?.closest('.section'),form=q('#addForm');if(!section||!form)return;section.style.display='';section.classList.add('seriesEntry');const heading=section.querySelector('.sectionHead h2');if(heading)heading.textContent='Neue Serie eintragen';form.classList.add('show');section.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>q('[name=name]')?.focus(),180)}
toggleAdd=openAddSeries;
const renderDailyDetails031=renderDailyDetails;renderDailyDetails=function(){renderDailyDetails031();const actions=document.querySelector('.dailyActions');if(actions&&!actions.querySelector('.addSeriesShortcut')){const button=document.createElement('button');button.type='button';button.className='addSeriesShortcut';button.textContent='＋ Serie eintragen';button.onclick=openAddSeries;actions.insertBefore(button,actions.firstChild)}}
</script>'''
PAGE = PAGE.replace("</body>", SERIES_031_UI + "</body>")

SERIES_032_UI = r'''<style>
/* Das Eingabeformular muss auf allen Geräten lesbar bleiben. */
#addForm input{background:#fffdfa!important;color:#3a2b46!important;border-color:#cdbcc5!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}
#addForm input::placeholder{color:#8b7d86!important;opacity:1}
#addForm input:focus{outline:3px solid rgba(116,86,199,.18);border-color:#7456c7!important}
.deleteSeriesButton{background:#fff3f2!important;border-color:#e4aaa8!important;color:#9b4847!important}
.seriesManagement{margin-top:14px;border-top:1px solid #eadeda;padding-top:14px}.seriesManagement h3{margin:0 0 8px;font-family:Georgia,"Times New Roman",serif;color:#503953;font-size:19px}.seriesManagement p{margin:0 0 10px;color:#7b6d76;font-size:12px}.seriesManagerList{display:flex;flex-wrap:wrap;gap:7px}.seriesManagerItem{display:flex;align-items:center;gap:7px;border:1px solid #eadeda;border-radius:999px;background:#fffdfa;padding:5px 6px 5px 10px;color:#503953;font-size:12px;font-weight:750}.seriesManagerItem button{padding:5px 8px;font-size:11px}
</style><script>
async function deleteSeries(id){const series=DATA.series.find(row=>row.id===id);if(!series)return;if(!confirm(`„${series.name}“ wirklich aus dem Serienplaner löschen?`))return;const response=await fetch('/api/series/'+encodeURIComponent(id)+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const result=await response.json().catch(()=>({}));if(!response.ok){alert(result.error||'Die Serie konnte nicht gelöscht werden.');return}DATA=result;render()}
function deleteButton032(id){const button=document.createElement('button');button.type='button';button.className='deleteSeriesButton';button.textContent='Löschen';button.onclick=event=>{event.stopPropagation();deleteSeries(id)};return button}
function renderSeriesManager(){const section=document.querySelector('#watching')?.closest('.section'),form=q('#addForm');if(!section||!form)return;let panel=document.querySelector('#seriesManagement');if(!panel){panel=document.createElement('div');panel.id='seriesManagement';panel.className='seriesManagement';form.insertAdjacentElement('afterend',panel)}panel.innerHTML=`<h3>Serien verwalten</h3><p>Hier kannst du auch eine gerade neu eingetragene Serie sofort wieder löschen.</p><div class="seriesManagerList">${(DATA.series||[]).map(series=>`<div class="seriesManagerItem"><span>${esc(series.name)}</span><button type="button" class="deleteSeriesButton" data-manage-delete="${esc(series.id)}">Löschen</button></div>`).join('')||'<span class="empty">Noch keine Serien eingetragen.</span>'}</div>`;panel.querySelectorAll('[data-manage-delete]').forEach(button=>button.onclick=()=>deleteSeries(button.dataset.manageDelete))}
function addDeleteButtons032(){document.querySelectorAll('.releaseCard').forEach(card=>{const title=card.querySelector('.releaseBody h4')?.textContent||'';const own=DATA.series.find(series=>series.name===title);const controls=card.querySelector('.dailyControls');if(own&&controls&&!controls.querySelector('.deleteSeriesButton'))controls.append(deleteButton032(own.id))});document.querySelectorAll('.quietRow').forEach(card=>{const title=card.querySelector('.quietText b')?.textContent||'';const own=DATA.series.find(series=>series.name===title);let controls=card.querySelector('.dailyControls');if(own&&!controls){controls=document.createElement('div');controls.className='dailyControls';card.insertBefore(controls,card.querySelector('.quietBadge'))}if(own&&controls&&!controls.querySelector('.deleteSeriesButton'))controls.append(deleteButton032(own.id))})}
function card(s){const normal=s.status==='watching'?`<button class="primary" onclick="advance('${s.id}')">✓ Nächste Folge gesehen</button><button onclick="editSeries('${s.id}')">Stand ändern</button><button onclick="setStatus('${s.id}','paused')">Pausieren</button>`:s.status==='paused'?`<button class="primary" onclick="setStatus('${s.id}','watching')">Weiter schauen</button>`:'';const actions=`<div class="actions">${normal}<button class="deleteSeriesButton" onclick="deleteSeries('${s.id}')">Löschen</button></div>`;return `<article class="card ${s.status==='cancelled'?'cancelled':''}"><h3>${esc(s.name)}</h3>${s.status!=='cancelled'?`<div class="meta">${progress(s)}</div>`:''}<p class="note">${esc(s.note||'Kein Hinweis hinterlegt.')}</p>${s.status==='cancelled'?'<div class="meta">✓ Komplett gesehen · eingestellt</div>':''}${actions}</article>`}
const openAddSeries032=openAddSeries;openAddSeries=function(){openAddSeries032();renderSeriesManager()};
const renderDailyDetails032=renderDailyDetails;renderDailyDetails=function(){renderDailyDetails032();renderSeriesManager();addDeleteButtons032()}
</script>'''
PAGE = PAGE.replace("</body>", SERIES_032_UI + "</body>")

PAGE = PAGE.replace("</body>", '''<script>
async function waitForCheck(){await new Promise(resolve=>setTimeout(resolve,2000));await load();if((DATA.daily_check||{}).is_running)waitForCheck()}checkNow=async function(){const button=q('#checkNow');if(!button||button.disabled)return;button.disabled=true;button.textContent='Gemini prüft …';const response=await fetch('/api/check-now',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok){const result=await response.json();alert(result.error||'Prüfung konnte nicht gestartet werden.');button.disabled=false;button.textContent='Jetzt prüfen';return}DATA=await response.json();render();waitForCheck()};cancelCheck=async function(){const response=await fetch('/api/cancel-check',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok){alert('Die Prüfung konnte nicht abgebrochen werden.');return}DATA=await response.json();render()}
</script></body>''')


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serienplaner {VERSION} startet auf 0.0.0.0:{PORT}")
    threading.Thread(target=daily_scheduler, name="daily-series-check", daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
