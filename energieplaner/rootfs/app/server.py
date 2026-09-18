#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import math
import os
import re
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "0.1.58"
PORT = int(os.environ.get("PORT", "8150"))
# In Home Assistant bleibt dies /data. Die Umgebungsvariable macht die App
# zusätzlich lokal prüfbar, ohne dabei die produktiven Dateien anzufassen.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OPTIONS_FILE = DATA_DIR / "options.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "energieplaner.log"

HA_BASE = "http://supervisor/core/api"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

PV_TOTAL_KWP = 12.8
PV_EAST_KWP = 7.4
PV_WEST_KWP = 5.4
BATTERY_CAPACITY_KWH = 7.5
BATTERY_SAFE_CHARGE_KW = 1.7

ENTITIES = {
    "pv_day": "sensor.pverzeugungtag",
    "pv_power": "sensor.senec_solar_generated_power",
    # Für die historische Morgen-Lernlogik ist dieser Template-Sensor die
    # belastbare Gesamt-PV-Leistung in kW. Die MPP-Einzelsensoren sind teils
    # unavailable und dürfen dafür nicht automatisch gewählt werden.
    "pv_power_kw": "sensor.aktuell_pv_in_kw",
    "house_power": "sensor.senec_house_power",
    "power_balance": "sensor.senec_power_balance",
    "battery_power": "sensor.senec_battery_state_power",
    "grid_power": "sensor.senec_grid_state_power",
    "wallbox_power": "sensor.senec_wallbox_1_power",
    "net_import_day": "sensor.netztagneu",
    "grid_export_day": "sensor.einspeisung_tag",
    "wallbox_day": "sensor.wallbox_verbrauch_tag",
    # Neue einzeln messbare Verbraucher für Live-/Tagesanzeige und Standby-Lernen.
    "dishwasher_power": "sensor.pool_switch_0_power",
    "climate_office_day": "sensor.klima_buro_strom_heute",
    "climate_kids_day": "sensor.klima_kinderzimmer_strom_heute",
    # Wohnzimmer/Schlafzimmer haben derzeit keinen Verbrauchssensor. Solange
    # sie eingeschaltet sind, werden diese Zeitfenster nicht fürs Standby-Lernen genutzt.
    "climate_living": "climate.klimaanlage_wohnzimmer",
    "climate_bedroom": "climate.klimaanlage_schlafzimmer",
    "wp_power": "sensor.wp_verbrauch_pro_stunde",
    "wp_day": "sensor.wp_verbrauch_tag",
    "battery_charge_day": "sensor.speicherbeladentag",
    "battery_discharge_day": "sensor.speicherentladentag",
    "battery_soc": "sensor.senec_battery_charge_percent",
    "battery_safe_charge": "switch.senec_safe_charge",
    "wallbox_mode": "select.senec_webapi_wallbox_1_mode_2",
    "phase1": "switch.wallbox_switch_2",
    "phase2": "switch.wallbox_switch_1",
    "phase3": "switch.wallbox_switch_0",
    "warmwater_switch": "input_boolean.warmwasser_2",
    "warmwater_temp": "sensor.boschcom_icom_080361776_dhw1_sensor",
    "id7_soc": "sensor.id_7_ladezustand",
    "egolf_soc": "sensor.e_golf_ladezustand",
    "id7_cable": "binary_sensor.wvwzzzed4se044943_charging_cable_connected",
    # Optional analoger Kabelsensor des e-Golf. Falls die Entität nicht existiert,
    # fällt die Erkennung automatisch auf Session/SOC zurück.
    "egolf_cable": "binary_sensor.wvwzzzauzlw913717_charging_cable_connected",
}

# 30-Tage-Blindtest + 18.08.2026. Diese Daten dienen nur als Startkalibrierung.
SEED_HISTORY = [
    ("2026-07-19", 4.35, 33.2, 38.40),
    ("2026-07-20", 3.42, 25.8, 38.60),
    ("2026-07-21", 6.11, 47.8, 57.23),
    ("2026-07-22", 3.14, 23.5, 37.94),
    ("2026-07-23", 5.08, 39.5, 41.28),
    ("2026-07-24", 5.30, 41.2, 56.81),
    ("2026-07-25", 6.32, 49.8, 64.09),
    ("2026-07-26", 2.03, 14.8, 23.58),
    ("2026-07-27", 3.75, 28.8, 46.17),
    ("2026-07-28", 5.74, 45.2, 66.38),
    ("2026-07-29", 7.09, 55.8, 65.60),
    ("2026-07-30", 5.40, 41.8, 42.31),
    ("2026-07-31", 4.93, 38.2, 51.17),
    ("2026-08-01", 6.47, 51.2, 56.64),
    ("2026-08-02", 7.08, 56.0, 66.63),
    ("2026-08-03", 6.74, 53.1, 63.91),
    ("2026-08-04", 3.60, 27.2, 47.46),
    ("2026-08-05", 5.78, 45.3, 55.11),
    ("2026-08-06", 5.49, 42.8, 52.08),
    ("2026-08-07", 3.37, 25.5, 31.50),
    ("2026-08-08", 6.97, 55.4, 67.20),
    ("2026-08-09", 6.64, 52.0, 62.75),
    ("2026-08-10", 4.88, 38.0, 42.47),
    ("2026-08-11", 6.62, 52.8, 67.34),
    ("2026-08-12", 6.64, 53.0, 66.24),
    ("2026-08-13", 6.66, 52.8, 64.63),
    ("2026-08-14", 6.61, 51.5, 62.48),
    ("2026-08-15", 3.83, 29.2, 29.69),
    ("2026-08-16", 4.67, 36.2, 52.10),
    ("2026-08-17", 2.36, 17.5, 21.65),
    ("2026-08-18", 1.51, 13.8, 14.74),
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "master_automation_enabled": True,
    "notifications_enabled": True,
    "notify_service": "notify.mobile_app_iphone A",
    # Vereinfachter Energieplan für secondary. Gleiche Zeitpunkte wie der
    # Hauptplan, aber nur alltagsrelevante Hinweise und ausschließlich e-Golf.
    "partner_notifications_enabled": True,
    "partner_notify_service": "notify.mobile_app_secondary_iphone",
    "forecast_main_time": "20:00",
    "forecast_morning_time": "07:00",
    "night_end_time": "05:00",
    # Gemini-Sparmodus: feste Prognosen fünf Minuten vor 07:00 und 20:00.
    # Beide Pushes werden unabhängig von einer Planänderung gesendet.
    "gemini_daily_limit": 3,
    "gemini_manual_cooldown_minutes": 30,
    "gemini_late_ghi_change_percent": 15.0,
    "gemini_late_cloud_change_points": 20.0,

    "pv_surplus_auto_enabled": True,
    # Dynamische PV-Phasensteuerung bei 6 A Mindeststrom je Phase.
    "pv_phase1_start_w": 1600,
    "pv_phase1_stop_w": 1400,
    "pv_phase2_start_w": 3600,
    "pv_phase2_stop_w": 3000,
    "pv_phase3_start_w": 5200,
    "pv_phase3_stop_w": 4500,
    # Abschalten darf bei Wolken zügig reagieren; für jede Zuschaltung muss der
    # Überschuss dagegen lange genug stabil sein.
    "pv_surplus_delay_seconds": 120,
    "pv_phase_hold_seconds": 1800,
    # PV-Budget: Haus/Speicher/Warmwasser haben vor dem Auto Vorrang.
    "evening_reserve_start_kwh": 2.5,
    "evening_reserve_margin_kwh": 0.5,
    "day_house_base_kw": 0.85,
    "warmwater_estimated_kwh": 1.8,
    "pv_budget_safety_kwh": 0.8,
    "car_budget_min_kwh": 1.5,

    "wallbox_night_auto_enabled": True,
    "battery_auto_enabled": True,
    "warmwater_auto_enabled": True,

    # Dynamisches Speicherziel um 05:00: 5 % absolute Mindestreserve plus
    # gelernter Netto-Morgenbedarf und – falls nötig – Resttag-Puffer.
    "morning_min_soc": 5,
    # Manuelle Feinjustierung des automatisch berechneten 05:00-Ziels.
    # Die absolute Untergrenze von 5 % bleibt immer wirksam.
    "battery_soc_manual_offset": 0.0,
    "morning_base_target_start_soc": 35,
    "morning_base_target_min_soc": 30,
    "morning_base_target_max_soc": 50,
    "morning_learning_good_day_kwh": 35.0,


    "id7_target_soc": 80,
    "id7_min_morning_soc": 40,
    "egolf_target_soc": 80,
    "egolf_min_morning_soc": 40,
    # Eine Wallbox, ein Nachtziel – welches Fahrzeug tatsächlich lädt, wird
    # automatisch daran erkannt, welcher SOC während der Sitzung ansteigt.
    "car_night_target_soc": 50,

    "battery_target_under_20": 100,
    "battery_target_20_30": 60,
    "battery_target_30_40": 40,
    "battery_target_over_40": 20,

    "warmwater_duration_minutes": 120,
    "warmwater_night_threshold_kwh": 20.0,
    "warmwater_day_start_hour": 9,
    "warmwater_day_end_hour": 16,
}

DEFAULT_STATE: dict[str, Any] = {
    "version": VERSION,
    "forecast": {},
    "forecast_archive": {},
    "last_forecast_run": None,
    "last_forecast_source": None,
    "last_error": None,
    "last_weather_refresh": None,
    "gemini_control": {
        "date": None,
        "successful_calls": 0,
        "last_success_at": None,
        "last_attempt_at": None,
        "cached_model": None,
    },
    "live_pv_samples": [],
    "night_override": "auto",
    # An der gemeinsamen Wallbox hängt höchstens ein Auto. Es wird nur Ja/Nein
    # gewählt; die App erkennt das tatsächlich ladende Fahrzeug anhand des SOC-Anstiegs.
    "car_at_wallbox": True,
    # Manuelle Freigabe für die automatische Fahrzeugladung. Direktsteuerung
    # bleibt unabhängig davon möglich.
    "car_auto_charging_enabled": True,
    "night_target_override_soc": None,
    "wallbox_session": {
        "active": False,
        "started_at": None,
        "baseline_id7": None,
        "baseline_egolf": None,
        "active_vehicle": None,
        "target_soc": None,
    },
    "night_actions": {
        "wallbox_fast": False,
        "battery_safe_charge": False,
        "warmwater": False,
    },
    "last_notifications": {},
    "history": [],
    "battery_learning": {
        "effective_charge_kw": BATTERY_SAFE_CHARGE_KW,
        "night_date": None,
        "last_night_check_date": None,
        "last_night_check_at": None,
        "night_start_soc": None,
        "first_started_at": None,
        "active_started_at": None,
        "active_seconds": 0.0,
        # Sicherheitsvorlauf für die Nachtladung. Er startet mit 10 Minuten und
        # lernt bei verfehltem 05:00-Ziel bis maximal 30 Minuten nach oben.
        "start_buffer_minutes": 10,
        "last_buffer_adjustment": "Startpuffer 10 min",
        "last_target_soc": None,
        "planned_0500_date": None,
        "planned_0500_target_soc": None,
        "planned_cover_time": None,
        "planned_adjusted_cover_time": None,
        "planned_morning_predicted_need_kwh": None,
        "planned_morning_energy_buffer_soc": None,
        "soc_0500": None,
        "soc_0500_date": None,
        "last_measured_charge_kw": None,
        "last_adjustment": "Startwert 1,70 kW",
    },
    "morning_learning": {
        "base_target_soc": 35.0,
        "desired_cover_soc": 5.0,
        "learned_net_need_kwh": 1.55,
        "samples": 0,
        "last_sample_date": None,
        "last_cover_time": None,
        "last_cover_date": None,
        "last_net_need_kwh": None,
        "last_soc_0500": None,
        "last_soc_0500_date": None,
        "last_soc_cover": None,
        "last_forecast_kwh": None,
        # Prognose-Lernen: Gemini liefert den erwarteten Zeitpunkt der stabilen
        # PV-Übernahme. Die App lernt getrennt einen Zeitoffset sowie einen
        # kleinen Energie-/SOC-Puffer aus Prognose-vs.-Realität.
        "cover_time_offset_minutes": 0.0,
        "energy_buffer_soc": 0.0,
        "last_predicted_cover_time": None,
        "last_adjusted_cover_time": None,
        "last_predicted_net_need_kwh": None,
        "last_cover_time_error_minutes": None,
        "last_energy_error_kwh": None,
        "last_adjustment": "Mindestreserve 5 % · Morgenbedarf wird aus echten Verläufen gelernt",
        "recent_samples": [],
    },
    "day_load_learning": {
        "base_kw": 0.85,
        "samples": 0,
        "last_sample_date": None,
        "last_observed_kwh": None,
        "last_grid_import_kwh": None,
        "last_battery_max_soc": None,
        "last_adjustment": "Startwert 0,85 kW",
        "recent_samples": [],
    },
    "consumer_tracking": {
        "counter_rates": {},
        "power_integrators": {},
    },
    "standby_learning": {
        "estimate_w": None,
        "samples": 0,
        "last_sample_bucket": None,
        "last_reason": "Noch keine saubere Standby-Messung",
        "recent_samples": [],
    },
    "warmwater_session": {},
    "pv_surplus": {
        "candidate_phases": None,
        "candidate_since": None,
        "status_key": None,
        "status_since": None,
        "charging_since": None,
        "charging_pause_since": None,
        "phase_since": None,
        "phase_count": 0,
        "observed_wallbox_state": None,
        "last_phase_change": None,
        "last_action": None,
        "current_phases": 0,
    },
    "battery_soc_guard": {
        "accepted_soc": None,
        "accepted_at": None,
        "pending_soc": None,
        "pending_count": 0,
        "last_rejection": None,
    },
    "battery_night_control": {
        "date": None,
        "target_soc": None,
        "planned_start_minute": None,
        "charge_latched": False,
        "completed": False,
        "started_at": None,
        "last_check_at": None,
        "last_action": None,
        "last_error": None,
        "last_verified_at": None,
    },
    "wallbox_watchdog": {
        "low_since": None,
        "sensor_missing_since": None,
        "last_check_at": None,
        "last_ok_at": None,
        "last_action": None,
        "last_lock_attempt_at": None,
        "lock_attempts": 0,
        "safety_stops": 0,
        "alerted": False,
    },
    "evening_learning": {
        "reserve_kwh": 2.5,
        "sample_date": None,
        "start_soc": None,
        "start_time": None,
        "last_usage_kwh": None,
        "samples": 0,
        "last_adjustment": "Startwert 2,5 kWh",
    },
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


ensure_data_dir()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
)
LOG = logging.getLogger("energieplaner")


class JsonStore:
    def __init__(self, path: Path, default: dict[str, Any]):
        self.path = path
        self.default = default
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return self._merge(self.default, loaded)
            except Exception:
                LOG.exception("Konnte %s nicht laden", self.path)
        return json.loads(json.dumps(self.default))

    def _merge(self, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        result = json.loads(json.dumps(base))
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            else:
                result[key] = value
        return result

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)


settings_store = JsonStore(SETTINGS_FILE, DEFAULT_SETTINGS)
state_store = JsonStore(STATE_FILE, DEFAULT_STATE)
STARTUP_STATE_VERSION = str(state_store.data.get("version") or "")


def migrate_011() -> None:
    """0.1.0 war absichtlich passiv; 0.1.1 übernimmt nach Nutzerfreigabe produktiv."""
    old_version = str(state_store.data.get("version") or "")
    if old_version == "0.1.0":
        with settings_store.lock:
            for key in (
                "master_automation_enabled",
                "pv_surplus_auto_enabled",
                "wallbox_night_auto_enabled",
                "battery_auto_enabled",
                "warmwater_auto_enabled",
            ):
                settings_store.data[key] = True
            settings_store.save()
        with state_store.lock:
            state_store.data["version"] = VERSION
            state_store.save()


migrate_011()


def migrate_017() -> None:
    """0.1.7: realistischere Hausgrundlast als Ausgangswert übernehmen.

    Nur der alte 0.1.6-Standardwert 0,55 kW wird automatisch auf 0,70 kW
    angehoben. Individuell geänderte Werte bleiben unangetastet.
    """
    old_version = str(state_store.data.get("version") or "")
    if old_version in {"0.1.0", "0.1.1", "0.1.2", "0.1.3", "0.1.4", "0.1.5", "0.1.6"}:
        with settings_store.lock:
            try:
                current_base = float(settings_store.data.get("day_house_base_kw", 0.55))
            except (TypeError, ValueError):
                current_base = 0.55
            if abs(current_base - 0.55) < 0.001:
                settings_store.data["day_house_base_kw"] = 0.70
                settings_store.save()
        with state_store.lock:
            state_store.data["version"] = VERSION
            state_store.save()


migrate_017()


def migrate_018() -> None:
    """0.1.8: dynamisches, selbstlernendes 05:00-Speicherziel einführen."""
    old_version = str(state_store.data.get("version") or "")
    if old_version != VERSION:
        with state_store.lock:
            learning = state_store.data.setdefault("morning_learning", {})
            learning.setdefault("base_target_soc", 35.0)
            learning.setdefault("desired_cover_soc", 16.0)
            learning.setdefault("learned_net_need_kwh", 1.55)
            learning.setdefault("samples", 0)
            learning.setdefault("last_sample_date", None)
            learning.setdefault("last_cover_time", None)
            learning.setdefault("last_net_need_kwh", None)
            learning.setdefault("last_soc_0500", None)
            learning.setdefault("last_soc_cover", None)
            learning.setdefault("last_forecast_kwh", None)
            learning.setdefault("last_adjustment", "Startwert 35 % · Ziel bei PV-Deckung ca. 16 %")
            learning.setdefault("recent_samples", [])
            state_store.data["version"] = VERSION
            state_store.save()


migrate_018()


def migrate_0110() -> None:
    """0.1.10: Nachtziel und Wallbox-Modus sauber voneinander trennen.

    0.1.9 setzte beim Antippen eines Prozentziels versehentlich den Modus auf
    ``fast``. Beim Upgrade von genau 0.1.9 wird deshalb der Modus einmalig auf
    ``auto`` zurückgesetzt, das gewählte Prozentziel aber beibehalten.
    """
    if STARTUP_STATE_VERSION == "0.1.9":
        with state_store.lock:
            state_store.data["night_override"] = "auto"
            state_store.data["version"] = VERSION
            state_store.save()


migrate_0110()


def migrate_023() -> None:
    """0.1.23: bisherige Standardzeiten sinnvoll für Wolkenstaffelung setzen.

    Nur die unveränderten 0.1.22-Standardwerte werden migriert. Eigene Werte
    bleiben immer erhalten und können anschließend in den Einstellungen
    angepasst werden.
    """
    if STARTUP_STATE_VERSION == VERSION:
        return
    changed = False
    with settings_store.lock:
        if settings_store.data.get("pv_surplus_delay_seconds") == 180:
            settings_store.data["pv_surplus_delay_seconds"] = 120
            changed = True
        if settings_store.data.get("pv_phase_hold_seconds") == 300:
            settings_store.data["pv_phase_hold_seconds"] = 600
            changed = True
        if changed:
            settings_store.save()
    with state_store.lock:
        state_store.data["version"] = VERSION
        state_store.save()


migrate_023()


def migrate_0129() -> None:
    """0.1.29: neue 05:00-Speicherplanung und ruhigere PV-Hochstufung.

    Nur die bisherigen Standardwerte werden automatisch migriert. Individuell
    geänderte Werte bleiben erhalten. Die bisherige 16-%-Morgenreserve wird auf
    die neue absolute Untergrenze 5 % umgestellt; anschließend lernt sie in
    1-Prozentpunkt-Schritten aus den realen Morgenverläufen.
    """
    if STARTUP_STATE_VERSION == VERSION:
        return
    changed = False
    with settings_store.lock:
        try:
            base = float(settings_store.data.get("day_house_base_kw", 0.70))
        except (TypeError, ValueError):
            base = 0.70
        if abs(base - 0.70) < 0.001:
            settings_store.data["day_house_base_kw"] = 0.85
            changed = True
        try:
            hold = int(settings_store.data.get("pv_phase_hold_seconds", 600))
        except (TypeError, ValueError):
            hold = 600
        if hold == 600:
            settings_store.data["pv_phase_hold_seconds"] = 1800
            changed = True
        try:
            minimum = float(settings_store.data.get("morning_min_soc", 16))
        except (TypeError, ValueError):
            minimum = 16.0
        if abs(minimum - 16.0) < 0.001:
            settings_store.data["morning_min_soc"] = 5
            changed = True
        settings_store.data.setdefault("battery_soc_manual_offset", 0.0)
        if changed:
            settings_store.save()

    with state_store.lock:
        morning = state_store.data.setdefault("morning_learning", {})
        try:
            desired = float(morning.get("desired_cover_soc", 16) or 16)
        except (TypeError, ValueError):
            desired = 16.0
        if abs(desired - 16.0) < 0.001:
            morning["desired_cover_soc"] = 5.0
            morning["last_adjustment"] = "Mindestreserve auf 5 % gesetzt; Lernen startet ab dort"
        load = state_store.data.setdefault("day_load_learning", {})
        load.setdefault("base_kw", float(settings_store.data.get("day_house_base_kw", 0.85) or 0.85))
        load.setdefault("samples", 0)
        load.setdefault("last_sample_date", None)
        load.setdefault("last_observed_kwh", None)
        load.setdefault("last_grid_import_kwh", None)
        load.setdefault("last_battery_max_soc", None)
        load.setdefault("last_adjustment", "Startwert 0,85 kW")
        load.setdefault("recent_samples", [])
        state_store.data.setdefault("scheduled_runs", {"main_date": None, "morning_date": None, "cutoff_date": None, "actual_date": None})
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0129()


def migrate_0131() -> None:
    """0.1.31: adaptiven Startpuffer für die Speicher-Nachtladung ergänzen."""
    if STARTUP_STATE_VERSION == VERSION:
        return
    with state_store.lock:
        learning = state_store.data.setdefault("battery_learning", {})
        learning.setdefault("start_buffer_minutes", 10)
        learning.setdefault("last_buffer_adjustment", "Startpuffer 10 min")
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0131()


def migrate_0132() -> None:
    """0.1.32: 07:00-Gemini aktivieren und alte Mitternachtszeit bereinigen."""
    if STARTUP_STATE_VERSION == VERSION:
        return
    changed = False
    with settings_store.lock:
        morning = str(settings_store.data.get("forecast_morning_time", "07:00") or "").strip()
        if morning in {"0", "00", "0:00", "00:00"}:
            settings_store.data["forecast_morning_time"] = "07:00"
            changed = True
        try:
            limit = int(settings_store.data.get("gemini_daily_limit", 3))
        except (TypeError, ValueError):
            limit = 3
        if limit < 2:
            settings_store.data["gemini_daily_limit"] = 2
            changed = True
        if changed:
            settings_store.save()
    with state_store.lock:
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0132()


def migrate_0133() -> None:
    """0.1.33: getrennte Gemini-Vorläufe, Verbrauchertracking und Standby-Lernen."""
    with state_store.lock:
        state_store.data.setdefault("consumer_tracking", {"counter_rates": {}, "power_integrators": {}})
        standby = state_store.data.setdefault("standby_learning", {})
        standby.setdefault("estimate_w", None)
        standby.setdefault("samples", 0)
        standby.setdefault("last_sample_bucket", None)
        standby.setdefault("last_reason", "Noch keine saubere Standby-Messung")
        standby.setdefault("recent_samples", [])
        scheduled = state_store.data.setdefault("scheduled_runs", {})
        scheduled.setdefault("morning_gemini_date", None)
        scheduled.setdefault("morning_date", None)
        scheduled.setdefault("main_gemini_date", None)
        scheduled.setdefault("main_date", None)
        scheduled.setdefault("cutoff_date", None)
        scheduled.setdefault("actual_date", None)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0133()


def migrate_0135() -> None:
    """0.1.35: robuste Wallbox-Automatik und unabhängiger PV-Sicherheitswächter."""
    with state_store.lock:
        wd = state_store.data.setdefault("wallbox_watchdog", {})
        wd.setdefault("low_since", None)
        wd.setdefault("sensor_missing_since", None)
        wd.setdefault("last_check_at", None)
        wd.setdefault("last_ok_at", None)
        wd.setdefault("last_action", None)
        wd.setdefault("last_lock_attempt_at", None)
        wd.setdefault("lock_attempts", 0)
        wd.setdefault("safety_stops", 0)
        wd.setdefault("alerted", False)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0135()


def migrate_0137() -> None:
    """0.1.37: stabile Nachtladung und nachvollziehbare PV-Zustände."""
    with state_store.lock:
        pv = state_store.data.setdefault("pv_surplus", {})
        pv.setdefault("status_key", None)
        pv.setdefault("status_since", None)
        pv.setdefault("charging_since", None)
        pv.setdefault("charging_pause_since", None)
        pv.setdefault("phase_since", None)
        pv.setdefault("phase_count", 0)
        pv.setdefault("observed_wallbox_state", None)
        guard = state_store.data.setdefault("battery_soc_guard", {})
        guard.setdefault("accepted_soc", None)
        guard.setdefault("accepted_at", None)
        guard.setdefault("pending_soc", None)
        guard.setdefault("pending_count", 0)
        guard.setdefault("last_rejection", None)
        night = state_store.data.setdefault("battery_night_control", {})
        night.setdefault("date", None)
        night.setdefault("target_soc", None)
        night.setdefault("planned_start_minute", None)
        night.setdefault("charge_latched", False)
        night.setdefault("completed", False)
        night.setdefault("started_at", None)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0137()


def migrate_0138() -> None:
    """0.1.38: PV-Laden und Wächter bereits unter 1.400 W beenden."""
    with settings_store.lock:
        try:
            stop_w = float(settings_store.data.get("pv_phase1_stop_w", 1400))
        except (TypeError, ValueError):
            stop_w = 1400.0
        if abs(stop_w - 900.0) < 0.1:
            settings_store.data["pv_phase1_stop_w"] = 1400
            settings_store.save()
    with state_store.lock:
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0138()


def migrate_0143() -> None:
    """0.1.43: PV-Zeiten als echte, neustartfeste Zeitstempel speichern."""
    # Frühere Versionen speicherten time.monotonic()-Werte. Diese sind nach
    # einem Add-on-Neustart nicht mehr aussagekräftig und dürfen nicht als
    # Quelle für die sichtbare Laufzeit weiterverwendet werden.
    fallback_stamp = datetime.now(timezone.utc).isoformat()
    with state_store.lock:
        pv = state_store.data.setdefault("pv_surplus", {})
        for key in ("candidate_since", "status_since", "charging_since"):
            value = pv.get(key)
            if value in (None, ""):
                pv.setdefault(key, None)
                continue
            try:
                datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                pv[key] = fallback_stamp
        pv.setdefault("charging_since", None)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0143()


def migrate_0144() -> None:
    """0.1.44: Phasen- und Gesamtdauer einer PV-Ladesitzung trennen."""
    with state_store.lock:
        pv = state_store.data.setdefault("pv_surplus", {})
        pv.setdefault("charging_pause_since", None)
        pv.setdefault("phase_since", pv.get("charging_since"))
        pv.setdefault("phase_count", int(pv.get("current_phases") or 0))
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0144()


def migrate_0145() -> None:
    """0.1.45: Nachtladung wieder in den Scheduler einhängen und Diagnose datieren."""
    with state_store.lock:
        battery = state_store.data.setdefault("battery_learning", {})
        battery.setdefault("last_night_check_date", None)
        battery.setdefault("last_night_check_at", None)

        morning = state_store.data.setdefault("morning_learning", {})
        morning.setdefault("last_cover_date", None)
        morning.setdefault("last_soc_0500_date", None)

        night = state_store.data.setdefault("battery_night_control", {})
        night.setdefault("last_check_at", None)
        night.setdefault("last_action", None)
        night.setdefault("last_error", None)
        night.setdefault("last_verified_at", None)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0145()


def migrate_0147() -> None:
    """0.1.47: prognosebasierte Morgenbrücke mit getrenntem Zeit-/Energielernen."""
    with state_store.lock:
        morning = state_store.data.setdefault("morning_learning", {})
        morning.setdefault("cover_time_offset_minutes", 0.0)
        morning.setdefault("energy_buffer_soc", 0.0)
        morning.setdefault("last_predicted_cover_time", None)
        morning.setdefault("last_adjusted_cover_time", None)
        morning.setdefault("last_predicted_net_need_kwh", None)
        morning.setdefault("last_cover_time_error_minutes", None)
        morning.setdefault("last_energy_error_kwh", None)
        battery = state_store.data.setdefault("battery_learning", {})
        battery.setdefault("planned_cover_time", None)
        battery.setdefault("planned_adjusted_cover_time", None)
        battery.setdefault("planned_morning_predicted_need_kwh", None)
        battery.setdefault("planned_morning_energy_buffer_soc", None)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0147()


def migrate_0158() -> None:
    """0.1.58: manuelle Auto-Ladepause und speicherpriorisierte PV-Wallbox."""
    with state_store.lock:
        state_store.data.setdefault("car_auto_charging_enabled", True)
        state_store.data["version"] = VERSION
        state_store.save()


migrate_0158()


def seed_history_if_needed() -> None:
    with state_store.lock:
        hist = state_store.data.setdefault("history", [])
        existing = {x.get("date") for x in hist if isinstance(x, dict)}
        changed = False
        for ds, ghi, raw, actual in SEED_HISTORY:
            if ds in existing:
                continue
            hist.append(
                {
                    "date": ds,
                    "ghi": ghi,
                    "raw_expected": raw,
                    "actual": actual,
                    "ratio": round(actual / raw, 6) if raw > 0 else None,
                    "source": "seed_blindtest",
                }
            )
            changed = True
        hist.sort(key=lambda x: x.get("date", ""))
        if changed:
            state_store.save()


seed_history_if_needed()


def load_options() -> dict[str, Any]:
    if not OPTIONS_FILE.exists():
        return {}
    try:
        data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        LOG.exception("options.json konnte nicht gelesen werden")
        return {}


def ha_request(path: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        HA_BASE + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


_HA_STATES_CACHE_LOCK = threading.RLock()
_HA_STATES_CACHE_TS = 0.0
_HA_STATES_CACHE: dict[str, dict[str, Any]] = {}


def invalidate_ha_state_cache() -> None:
    global _HA_STATES_CACHE_TS, _HA_STATES_CACHE
    with _HA_STATES_CACHE_LOCK:
        _HA_STATES_CACHE_TS = 0.0
        _HA_STATES_CACHE = {}


def _ha_states_map(max_age_seconds: float = 1.2) -> dict[str, dict[str, Any]]:
    """Read all HA states once and reuse the coherent snapshot briefly."""
    global _HA_STATES_CACHE_TS, _HA_STATES_CACHE
    now_mono = time.monotonic()
    with _HA_STATES_CACHE_LOCK:
        if _HA_STATES_CACHE and now_mono - _HA_STATES_CACHE_TS <= max_age_seconds:
            return _HA_STATES_CACHE
        try:
            rows = ha_request("/states", timeout=12)
            if isinstance(rows, list):
                _HA_STATES_CACHE = {
                    str(x.get("entity_id")): x
                    for x in rows
                    if isinstance(x, dict) and x.get("entity_id")
                }
                _HA_STATES_CACHE_TS = time.monotonic()
                return _HA_STATES_CACHE
        except Exception:
            LOG.exception("Gebündelter HA-State-Abruf fehlgeschlagen")
        return _HA_STATES_CACHE


def ha_state(entity_id: str) -> dict[str, Any] | None:
    try:
        cached = _ha_states_map().get(entity_id)
        if cached is not None:
            return cached
        return ha_request("/states/" + urllib.parse.quote(entity_id, safe="._"), timeout=8)
    except Exception:
        return None


def state_value(entity_id: str, default: float | None = None) -> float | None:
    s = ha_state(entity_id)
    if not s:
        return default
    value = s.get("state")
    if value in (None, "unknown", "unavailable", "none", ""):
        return default
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def state_text(entity_id: str, default: str = "unavailable") -> str:
    s = ha_state(entity_id)
    return str(s.get("state", default)) if s else default


def state_unit(entity_id: str, default: str = "") -> str:
    s = ha_state(entity_id)
    if not s:
        return default
    attrs = s.get("attributes") or {}
    return str(attrs.get("unit_of_measurement") or default)


def current_pv_surplus_w() -> float | None:
    """Nach Haus *und Speicher* wirklich für die Wallbox nutzbarer Überschuss.

    Entscheidend ist nicht mehr nur ``PV - Haus``. Das konnte die Wallbox
    starten, obwohl der Hausspeicher denselben Überschuss gerade noch zum
    Laden brauchte. Bevorzugt wird deshalb die reale Netzbilanz zusammen mit
    der aktuell laufenden Wallboxleistung:

    ``Wallboxleistung - Netzbezug`` bzw. ``Wallboxleistung + Einspeisung``.

    Ist die Wallbox aus, entspricht das der tatsächlichen Einspeisung *nach*
    Haus und Speicher. Lädt sie bereits, wird ihre eigene Leistung addiert,
    damit die Regelung nicht durch die reduzierte Einspeisung oszilliert.
    """
    grid_power_w = state_value(ENTITIES["grid_power"])
    wallbox_power_w = state_value(ENTITIES["wallbox_power"])
    if grid_power_w is not None and wallbox_power_w is not None:
        return float(wallbox_power_w) - float(grid_power_w)

    # Sichere Rückfallebene nur dann, wenn der Speicher praktisch voll ist.
    # Bei niedrigerem SOC würde ``PV - Haus`` den noch ladenden Speicher
    # übergehen und genau das unerwünschte Verhalten wieder zulassen.
    battery_soc = state_value(ENTITIES["battery_soc"])
    if battery_soc is not None and float(battery_soc) >= 98.0:
        pv_power_w = state_value(ENTITIES["pv_power"])
        house_power_w = state_value(ENTITIES["house_power"])
        if pv_power_w is not None and house_power_w is not None:
            return float(pv_power_w) - float(house_power_w)
        return state_value(ENTITIES["power_balance"])
    return None


def call_service(domain: str, service: str, entity_id: str | None = None, data: dict[str, Any] | None = None) -> Any:
    payload = dict(data or {})
    if entity_id:
        payload["entity_id"] = entity_id
    result = ha_request(f"/services/{domain}/{service}", method="POST", payload=payload)
    invalidate_ha_state_cache()
    return result


def ensure_phase1_on() -> None:
    if state_text(ENTITIES["phase1"]) != "on":
        LOG.warning("Phase 1 war aus und wird eingeschaltet")
        call_service("switch", "turn_on", ENTITIES["phase1"])


def reset_pv_tracking(action: str, mode: str) -> None:
    """Neuen realen Wallbox-Zustand als frischen PV-Lauf festhalten."""
    stamp = now_local().isoformat()
    with state_store.lock:
        pv = state_store.data.setdefault("pv_surplus", {})
        pv.update({
            "candidate_phases": None,
            "candidate_since": None,
            "status_key": None,
            "status_since": stamp,
            "charging_since": stamp if mode.startswith("optimized") else None,
            "charging_pause_since": None,
            "phase_since": stamp if mode.startswith("optimized") else None,
            "phase_count": 1 if mode.startswith("optimized") else 0,
            "observed_wallbox_state": mode,
            "current_phases": 1 if mode.startswith("optimized") else 0,
            "last_action": action,
        })
        state_store.save()


def wallbox_set_locked(track_night: bool = False, reset_tracking: bool = True) -> None:
    ensure_phase1_on()
    call_service("select", "select_option", ENTITIES["wallbox_mode"], {"option": "locked"})
    call_service("switch", "turn_off", ENTITIES["phase2"])
    call_service("switch", "turn_off", ENTITIES["phase3"])
    ensure_phase1_on()
    if reset_tracking:
        reset_pv_tracking("Wallbox gesperrt", "locked")
    if track_night:
        with state_store.lock:
            state_store.data["night_actions"]["wallbox_fast"] = False
            state_store.save()


def wallbox_set_pv() -> None:
    ensure_phase1_on()
    call_service("switch", "turn_off", ENTITIES["phase2"])
    call_service("switch", "turn_off", ENTITIES["phase3"])
    call_service("select", "select_option", ENTITIES["wallbox_mode"], {"option": "optimized"})
    ensure_phase1_on()
    reset_pv_tracking("PV-Laden manuell freigegeben", "optimized_1")


def wallbox_set_fast(track_night: bool = False) -> None:
    ensure_phase1_on()
    call_service("switch", "turn_on", ENTITIES["phase2"])
    call_service("switch", "turn_on", ENTITIES["phase3"])
    call_service("select", "select_option", ENTITIES["wallbox_mode"], {"option": "fast"})
    ensure_phase1_on()
    if track_night:
        with state_store.lock:
            state_store.data["night_actions"]["wallbox_fast"] = True
            state_store.save()


def battery_safe_charge(on: bool, track_night: bool = False) -> bool:
    previous = state_text(ENTITIES["battery_safe_charge"]) == "on"
    error = None
    try:
        call_service("switch", "turn_on" if on else "turn_off", ENTITIES["battery_safe_charge"])
    except Exception as exc:
        error = f"Servicefehler: {exc}"
        LOG.exception("Speicher-Netzladung konnte nicht %s geschaltet werden", "eingeschaltet" if on else "ausgeschaltet")
    expected = "on" if on else "off"
    confirmed = error is None and state_text(ENTITIES["battery_safe_charge"]) == expected
    if not confirmed and error is None:
        error = f"Schaltzustand nicht bestätigt (erwartet {expected}, gelesen {state_text(ENTITIES['battery_safe_charge'])})"
        LOG.warning("Speicher-Netzladung: %s", error)
    if track_night:
        now = now_local()
        with state_store.lock:
            state_store.data.setdefault("night_actions", {})["battery_safe_charge"] = bool(on)
            control = state_store.data.setdefault("battery_night_control", {})
            control["last_check_at"] = now.isoformat()
            control["last_action"] = (
                "Einschalten bestätigt" if on and confirmed else
                "Ausschalten bestätigt" if not on and confirmed else
                f"{'Einschalten' if on else 'Ausschalten'} nicht bestätigt"
            )
            control["last_error"] = error
            if confirmed:
                control["last_verified_at"] = now.isoformat()
            learning = state_store.data.setdefault("battery_learning", {})
            night_date = now.date().isoformat()
            learning["last_night_check_date"] = night_date
            learning["last_night_check_at"] = now.isoformat()
            if on and not previous and confirmed:
                if learning.get("night_date") != night_date:
                    learning["night_date"] = night_date
                    learning["night_start_soc"] = state_value(ENTITIES["battery_soc"])
                    learning["first_started_at"] = now.isoformat()
                    learning["active_seconds"] = 0.0
                learning["active_started_at"] = now.isoformat()
                learning["last_target_soc"] = state_store.data.get("plan", {}).get("battery", {}).get("target_soc")
            elif not on and previous and confirmed:
                active_started = learning.get("active_started_at")
                if active_started:
                    try:
                        started = datetime.fromisoformat(str(active_started))
                        learning["active_seconds"] = float(learning.get("active_seconds") or 0.0) + max(
                            0.0, (now - started).total_seconds()
                        )
                    except Exception:
                        pass
                learning["active_started_at"] = None
            state_store.save()
    return confirmed


def warmwater_set(on: bool, track_night: bool = False) -> None:
    call_service("input_boolean", "turn_on" if on else "turn_off", ENTITIES["warmwater_switch"])
    if track_night:
        with state_store.lock:
            state_store.data["night_actions"]["warmwater"] = bool(on)
            state_store.save()


def parse_number_from_state(entity_id: str) -> float | None:
    s = ha_state(entity_id)
    if not s:
        return None
    value = str(s.get("state", ""))
    cleaned = "".join(ch for ch in value.replace(",", ".") if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except Exception:
        return None


_NOTIFY_SERVICES_CACHE_LOCK = threading.RLock()
_NOTIFY_SERVICES_CACHE_TS = 0.0
_NOTIFY_SERVICES_CACHE: set[str] = set()


def _available_notify_services(max_age_seconds: float = 60.0) -> set[str]:
    """Liest die aktuell in Home Assistant vorhandenen Notify-Dienste."""
    global _NOTIFY_SERVICES_CACHE_TS, _NOTIFY_SERVICES_CACHE
    now_mono = time.monotonic()
    with _NOTIFY_SERVICES_CACHE_LOCK:
        if _NOTIFY_SERVICES_CACHE and now_mono - _NOTIFY_SERVICES_CACHE_TS <= max_age_seconds:
            return set(_NOTIFY_SERVICES_CACHE)
        services: set[str] = set()
        try:
            rows = ha_request("/services", timeout=12)
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict) or str(row.get("domain")) != "notify":
                        continue
                    raw = row.get("services") or {}
                    if isinstance(raw, dict):
                        services.update(f"notify.{name}" for name in raw.keys())
        except Exception:
            LOG.exception("Notify-Dienste konnten nicht aus Home Assistant gelesen werden")
        _NOTIFY_SERVICES_CACHE = services
        _NOTIFY_SERVICES_CACHE_TS = now_mono
        return set(services)


def _notify_name(value: str) -> str:
    text = str(value or "").lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def resolve_notify_service(service_full: str, owner_hint: str | None = None) -> tuple[str, bool]:
    """Korrigiert einen veralteten Mobile-App-Service nur bei eindeutigem Treffer."""
    configured = str(service_full or "").strip()
    services = _available_notify_services()
    if not services or configured in services:
        return configured, False
    hint = _notify_name(owner_hint or "")
    mobile = sorted(x for x in services if x.startswith("notify.mobile_app_"))
    hinted = [x for x in mobile if hint and hint in _notify_name(x)]
    if len(hinted) == 1:
        return hinted[0], hinted[0] != configured
    if len(hinted) > 1:
        iphone = [x for x in hinted if "iphone" in _notify_name(x)]
        if len(iphone) == 1:
            return iphone[0], iphone[0] != configured
    return configured, False


def _matching_notify_entities(owner_hint: str, configured_service: str = "") -> list[str]:
    """Findet aktuelle Notify-Entities für ein Gerät, falls HA sie bereitstellt.

    Home Assistant bevorzugt inzwischen ``notify.send_message`` mit Notify-Entity,
    während ältere Mobile-App-Registrierungen weiterhin einen gerätespezifischen
    ``notify.mobile_app_*``-Dienst anbieten. Wir unterstützen beides.
    """
    hint = _notify_name(owner_hint)
    configured_tail = _notify_name(str(configured_service or "").split(".", 1)[-1])
    matches: list[tuple[int, str]] = []
    try:
        for entity_id, row in _ha_states_map(max_age_seconds=5.0).items():
            if not str(entity_id).startswith("notify."):
                continue
            attrs = row.get("attributes") or {} if isinstance(row, dict) else {}
            hay = _notify_name(" ".join((str(entity_id), str(attrs.get("friendly_name") or ""))))
            score = 0
            if hint and hint in hay:
                score += 10
            if "iphone" in hay:
                score += 3
            if configured_tail and configured_tail in hay:
                score += 6
            if score > 0:
                matches.append((score, str(entity_id)))
    except Exception:
        LOG.exception("Notify-Entities konnten nicht ausgewertet werden")
    matches.sort(key=lambda x: (-x[0], x[1]))
    return [entity_id for _, entity_id in matches]


def _primary_notify_entity(configured_service: str) -> str | None:
    candidates = _matching_notify_entities("primary", configured_service)
    if not candidates:
        return None
    # Nur einen klaren Top-Treffer automatisch verwenden. Bei Gleichstand bleibt
    # der bewährte mobile_app-Dienst die sichere Rückfallebene.
    if len(candidates) == 1:
        return candidates[0]
    top = candidates[0]
    top_key = _notify_name(top)
    second_key = _notify_name(candidates[1])
    if "primary" in top_key and "primary" not in second_key:
        return top
    if "iphone" in top_key and "iphone" not in second_key and "primary" in top_key:
        return top
    return None


def send_notification(
    title: str,
    message: str,
    critical_silent: bool = False,
    service_full: str | None = None,
) -> bool:
    settings = settings_store.data
    if not settings.get("notifications_enabled", True):
        return False
    configured_service = str(service_full or settings.get("notify_service", "notify.mobile_app_iphone A"))
    owner_hint = "secondary" if service_full is not None and configured_service == str(settings.get("partner_notify_service", "")) else "primary"

    # primary: zuerst den aktuellen Notify-Entity-Weg von Home Assistant nutzen,
    # sofern ein eindeutiges Gerät gefunden wird. Das umgeht alte/stale
    # mobile_app-Service-Registrierungen, die von HA noch akzeptiert werden, aber
    # auf dem aktuellen iPhone nichts mehr zustellen. secondary funktionierenden
    # Legacy-Weg lassen wir bewusst unverändert.
    if owner_hint == "primary":
        notify_entity = _primary_notify_entity(configured_service)
        if notify_entity:
            entity_payload: dict[str, Any] = {"title": title, "message": message}
            try:
                call_service("notify", "send_message", entity_id=notify_entity, data=entity_payload)
                LOG.info("primary-Push über notify.send_message -> %s", notify_entity)
                return True
            except Exception:
                LOG.exception("primary-Push über Notify-Entity %s fehlgeschlagen; Legacy-Fallback", notify_entity)

    service_full, auto_resolved = resolve_notify_service(configured_service, owner_hint=owner_hint)
    if "." not in service_full:
        LOG.error("Ungültiger Notify-Service: %s", service_full)
        return False
    if auto_resolved:
        LOG.warning("Notify-Service für %s automatisch korrigiert: %s -> %s", owner_hint, configured_service, service_full)
        setting_key = "partner_notify_service" if owner_hint == "secondary" else "notify_service"
        with settings_store.lock:
            settings_store.data[setting_key] = service_full
            settings_store.save()
    domain, service = service_full.split(".", 1)
    payload: dict[str, Any] = {"title": title, "message": message}
    if critical_silent:
        payload["data"] = {
            "push": {
                "interruption-level": "critical",
                "sound": {"name": "default", "critical": 1, "volume": 0},
            }
        }
    try:
        call_service(domain, service, data=payload)
        LOG.info("Push über Legacy-Service %s", service_full)
        return True
    except Exception:
        LOG.exception("Benachrichtigung über %s fehlgeschlagen", service_full)
        return False


def http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 45) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {"User-Agent": "Energieplaner/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_ha_config() -> dict[str, Any]:
    return ha_request("/config")


def local_tz() -> ZoneInfo:
    try:
        tz_name = str(get_ha_config().get("time_zone") or "Europe/Berlin")
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Europe/Berlin")


def now_local() -> datetime:
    return datetime.now(local_tz())


def planning_start_date(now: datetime | None = None) -> date:
    """Bis 04:59 gehört die laufende Nacht noch zum heutigen PV-Tag.

    Ab 05:00 wird wieder für morgen + übermorgen geplant.
    """
    current = now or now_local()
    if current.hour < 5:
        return current.date()
    return current.date() + timedelta(days=1)


def planning_labels(now: datetime | None = None) -> tuple[str, str]:
    current = now or now_local()
    return ("Heute", "Morgen") if current.hour < 5 else ("Morgen", "Übermorgen")


def relative_day_label(ds: str, now: datetime | None = None) -> str:
    current = (now or now_local()).date()
    try:
        target = date.fromisoformat(ds)
    except Exception:
        return ds
    delta = (target - current).days
    return {0: "Heute", 1: "Morgen", 2: "Übermorgen"}.get(delta, target.strftime("%d.%m."))


def open_meteo_forecast() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Aktuelle Wetterprognose für heute, morgen und übermorgen.

    Die Nachtplanung verwendet separat planning_start_date(); die Oberfläche soll
    trotzdem immer alle drei Tage zeigen.
    """
    cfg = get_ha_config()
    lat = float(cfg["latitude"])
    lon = float(cfg["longitude"])
    tz_name = str(cfg.get("time_zone") or "Europe/Berlin")
    start = now_local().date()
    end = start + timedelta(days=2)
    hourly_vars = [
        "shortwave_radiation",
        "direct_radiation",
        "diffuse_radiation",
        "cloud_cover",
        "precipitation",
        "temperature_2m",
    ]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(hourly_vars),
        "timezone": tz_name,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    weather = http_json(url)
    hourly = weather.get("hourly", {})
    times = hourly.get("time", [])

    def series(name: str, indices: list[int]) -> list[float]:
        values = hourly.get(name, [])
        result = []
        for i in indices:
            if i < len(values) and values[i] is not None:
                result.append(float(values[i]))
        return result

    daily_metrics: list[dict[str, Any]] = []
    hourly_by_day: dict[str, list[dict[str, Any]]] = {}
    for offset in range(3):
        day = start + timedelta(days=offset)
        ds = day.isoformat()
        idx = [i for i, stamp in enumerate(times) if str(stamp).startswith(ds)]
        if not idx:
            continue
        ghi = series("shortwave_radiation", idx)
        direct = series("direct_radiation", idx)
        diffuse = series("diffuse_radiation", idx)
        precipitation = series("precipitation", idx)
        temperatures = series("temperature_2m", idx)
        morning: list[float] = []
        afternoon: list[float] = []
        clouds: list[float] = []
        hourly_rows: list[dict[str, Any]] = []
        for i in idx:
            stamp = str(times[i])
            hour = int(stamp[11:13])
            rad = hourly.get("shortwave_radiation", [None] * len(times))[i]
            cloud = hourly.get("cloud_cover", [None] * len(times))[i]
            row = {
                "time": stamp,
                "radiation_wm2": float(rad or 0),
                "cloud_percent": float(cloud or 0),
                "precip_mm": float(hourly.get("precipitation", [0] * len(times))[i] or 0),
                "temp_c": float(hourly.get("temperature_2m", [0] * len(times))[i] or 0),
            }
            hourly_rows.append(row)
            if rad is not None:
                rad_f = float(rad)
                if 5 <= hour < 12:
                    morning.append(rad_f)
                if 12 <= hour < 21:
                    afternoon.append(rad_f)
                if rad_f > 5 and cloud is not None:
                    clouds.append(float(cloud))
        metrics = {
            "date": ds,
            "ghi_kwh_m2": round(sum(ghi) / 1000.0, 2),
            "direct_kwh_m2": round(sum(direct) / 1000.0, 2),
            "diffuse_kwh_m2": round(sum(diffuse) / 1000.0, 2),
            "morning_ghi_kwh_m2": round(sum(morning) / 1000.0, 2),
            "afternoon_ghi_kwh_m2": round(sum(afternoon) / 1000.0, 2),
            "cloud_day_percent": round(sum(clouds) / len(clouds), 1) if clouds else None,
            "precipitation_mm": round(sum(precipitation), 2),
            "mean_temp_c": round(sum(temperatures) / len(temperatures), 1) if temperatures else None,
        }
        daily_metrics.append(metrics)
        hourly_by_day[ds] = hourly_rows
    return daily_metrics, hourly_by_day


def _gemini_control_for_today() -> dict[str, Any]:
    today_ds = now_local().date().isoformat()
    with state_store.lock:
        control = state_store.data.setdefault("gemini_control", {})
        if control.get("date") != today_ds:
            cached = control.get("cached_model")
            control.clear()
            control.update({
                "date": today_ds,
                "successful_calls": 0,
                # Der sichtbare Gemini-Status gilt strikt für den heutigen Tag.
                # Ein Erfolg von gestern darf heute kein Häkchen erzeugen.
                "last_success_at": None,
                "last_attempt_at": None,
                "cached_model": cached,
            })
            state_store.save()
        return dict(control)


def _remaining_scheduled_gemini_slots_today(now: datetime | None = None) -> int:
    """Reserviert Gemini-Kontingent für 07:00 und 20:00.

    Manuelle oder Startup-Läufe dürfen die beiden fest gewünschten Prognosen
    nicht aus dem Tageslimit verdrängen. Bereits verstrichene Termine brauchen
    keine Reservierung mehr.
    """
    current = now or now_local()
    remaining = 0
    for key, default in (("forecast_morning_time", "07:00"), ("forecast_main_time", "20:00")):
        run_dt = _time_today(str(settings_store.data.get(key, default)), current.date())
        if run_dt is not None and current < run_dt:
            remaining += 1
    return remaining


def gemini_gate(reason: str) -> tuple[bool, str]:
    """Kostenbremse für Gemini mit Vorrang für 07:00 und 20:00.

    Die geplanten Morgen- und Abendläufe verwenden jeweils Gemini direkt vor
    der Benachrichtigung. Nicht geplante Läufe dürfen nur das Kontingent nutzen,
    das nach Reservierung der noch ausstehenden festen Termine übrig bleibt.
    """
    control = _gemini_control_for_today()
    # Zwei feste Gemini-Prognosen pro Tag sind Bestandteil der Planung.
    limit = max(2, int(settings_store.data.get("gemini_daily_limit", 3)))
    used = int(control.get("successful_calls") or 0)
    scheduled_reason = reason in {"morning", "main"}
    if scheduled_reason:
        if used >= limit:
            return False, f"Gemini-Tageslimit {used}/{limit} erreicht"
    else:
        reserved = _remaining_scheduled_gemini_slots_today()
        free_for_extra = max(0, limit - reserved)
        if used >= free_for_extra:
            return False, f"Gemini-Kontingent für 07:00/20:00 reserviert ({used}/{limit})"
    if reason == "manual":
        cooldown = max(1, int(settings_store.data.get("gemini_manual_cooldown_minutes", 30)))
        stamp = control.get("last_attempt_at")
        if stamp:
            try:
                last = datetime.fromisoformat(str(stamp))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=local_tz())
                remaining = cooldown * 60 - (now_local() - last.astimezone(local_tz())).total_seconds()
                if remaining > 0:
                    return False, f"Gemini-Cooldown noch {math.ceil(remaining / 60)} min"
            except Exception:
                pass
    return True, "ok"


def gemini_mark_attempt() -> None:
    _gemini_control_for_today()
    with state_store.lock:
        state_store.data["gemini_control"]["last_attempt_at"] = now_local().isoformat()
        state_store.save()


def gemini_mark_success(model: str) -> None:
    _gemini_control_for_today()
    with state_store.lock:
        control = state_store.data["gemini_control"]
        control["successful_calls"] = int(control.get("successful_calls") or 0) + 1
        control["last_success_at"] = now_local().isoformat()
        control["cached_model"] = model if str(model).startswith("models/") else f"models/{model}"
        state_store.save()


def choose_gemini_model(api_key: str) -> str:
    control = _gemini_control_for_today()
    cached = str(control.get("cached_model") or "").strip()
    if cached:
        return cached
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
    response = http_json(url, headers={"x-goog-api-key": api_key})
    usable: dict[str, str] = {}
    for model in response.get("models", []):
        if "generateContent" in model.get("supportedGenerationMethods", []):
            full = str(model.get("name", ""))
            usable[full.replace("models/", "", 1)] = full
    # 3.6 Flash bleibt wegen des validierten Blindtests bevorzugt. Die Kosten
    # werden über die Aufrufzahl begrenzt, nicht durch häufige Modellwechsel.
    for candidate in [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]:
        if candidate in usable:
            full = usable[candidate]
            with state_store.lock:
                state_store.data.setdefault("gemini_control", {})["cached_model"] = full
                state_store.save()
            return full
    raise RuntimeError("Kein geeignetes Gemini-Flash-Modell verfügbar")


def physics_fallback(metrics: dict[str, Any]) -> dict[str, Any]:
    ghi = float(metrics.get("ghi_kwh_m2") or 0)
    morning = float(metrics.get("morning_ghi_kwh_m2") or 0)
    afternoon = float(metrics.get("afternoon_ghi_kwh_m2") or 0)
    # Konservativer physikalischer Näherungswert, bewusst ohne individuelle Kalibrierung.
    orientation_balance = 1.0
    if morning + afternoon > 0:
        orientation_balance = (
            (morning / (morning + afternoon)) * (PV_EAST_KWP / PV_TOTAL_KWP)
            + (afternoon / (morning + afternoon)) * (PV_WEST_KWP / PV_TOTAL_KWP)
        ) * 2.0
        orientation_balance = max(0.82, min(1.08, orientation_balance))
    expected = max(0.0, ghi * PV_TOTAL_KWP * 0.72 * orientation_balance)
    return {
        "conservative_kwh": round(expected * 0.78, 1),
        "expected_kwh": round(expected, 1),
        "optimistic_kwh": round(expected * 1.23, 1),
        "confidence_percent": 55,
        "reason": "Fallback aus Einstrahlung, da Gemini nicht verfügbar war.",
    }


def gemini_forecast(
    api_key: str,
    daily_metrics: list[dict[str, Any]],
    hourly_by_day: dict[str, list[dict[str, Any]]] | None = None,
    standby_w: float | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not api_key:
        return [dict({"date": m["date"]}, **physics_fallback(m)) for m in daily_metrics], "fallback"
    model = choose_gemini_model(api_key)
    # Für das morgendliche Speicherziel bekommt Gemini zusätzlich nur den
    # relevanten Wetterverlauf 05:00–13:00. Gemini entscheidet dabei NICHT über
    # die zu ladende Energiemenge, sondern schätzt lediglich, ab wann die PV die
    # gelernte Standby-/Restlast stabil tragen kann. Die Energiemenge berechnet
    # die App anschließend deterministisch selbst.
    morning_profiles: dict[str, list[dict[str, Any]]] = {}
    for ds, rows in (hourly_by_day or {}).items():
        compact = []
        for row in rows or []:
            try:
                hour = int(str(row.get("time", ""))[11:13])
            except Exception:
                continue
            if 5 <= hour <= 13:
                compact.append({
                    "time": str(row.get("time") or ""),
                    "radiation_wm2": round(float(row.get("radiation_wm2", 0) or 0), 1),
                    "cloud_percent": round(float(row.get("cloud_percent", 0) or 0), 1),
                    "precip_mm": round(float(row.get("precip_mm", 0) or 0), 2),
                })
        morning_profiles[ds] = compact
    restload_w = round(float(standby_w), 0) if standby_w is not None else 700.0
    prompt = f"""
Du prognostizierst den Tagesertrag einer privaten Photovoltaikanlage in Deutschland.
Die Prognose wird anschließend separat anhand realer Anlagenhistorie kalibriert. Nimm deshalb KEINE pauschale individuelle Korrektur vor.

ANLAGE:
- Gesamtleistung: {PV_TOTAL_KWP} kWp
- Ostseite: {PV_EAST_KWP} kWp
- Westseite: {PV_WEST_KWP} kWp

AKTUELLE WETTERPROGNOSE FÜR DIE NÄCHSTEN TAGE:
{json.dumps(daily_metrics, ensure_ascii=False, indent=2)}

STÜNDLICHER MORGENVERLAUF 05:00–13:00:
{json.dumps(morning_profiles, ensure_ascii=False, indent=2)}

GELERNTE STANDBY-/RESTLAST DES HAUSES: ca. {restload_w:.0f} W

Berücksichtige insbesondere Globalstrahlung, direkte und diffuse Einstrahlung, Vormittag/Nachmittag, Bewölkung, Niederschlag, typische Anlagenverluste und Teillastverhalten. Erfinde keine unbekannten Dachparameter.

Zusätzlich zum Tagesertrag schätze für jedes Datum den Zeitpunkt, ab dem die PV-Erzeugung die genannte Standby-/Restlast voraussichtlich STABIL trägt. Ein kurzer einzelner Ausschlag über die Last reicht nicht; die Übernahme soll anschließend voraussichtlich anhalten. Gib die lokale Uhrzeit als HH:MM an. Falls bis 13:00 keine stabile Übernahme zu erwarten ist, gib null zurück. Berechne KEIN Speicherziel und KEINEN Strombedarf; das macht die App selbst.

Gib ausschließlich valides JSON zurück, exakt als Liste mit einem Objekt je Datum:
[
  {{
    "date": "YYYY-MM-DD",
    "conservative_kwh": 0.0,
    "expected_kwh": 0.0,
    "optimistic_kwh": 0.0,
    "confidence_percent": 0,
    "stable_pv_cover_time": "HH:MM oder null",
    "stable_pv_cover_confidence_percent": 0,
    "reason": "kurze Begründung"
  }}
]
"""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            # PV-Prognose ist eine klar strukturierte Analyse; niedriger Denkaufwand
            # spart Kosten, ohne die validierte Anlagenkalibrierung anzutasten.
            "thinkingConfig": {"thinkingLevel": "low"},
            "maxOutputTokens": 1800,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"
    response = http_json(
        url,
        method="POST",
        payload=body,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        timeout=90,
    )
    texts: list[str] = []
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                texts.append(str(part["text"]))
    parsed = json.loads("\n".join(texts).strip())
    if not isinstance(parsed, list):
        raise RuntimeError("Gemini-Antwort war keine Liste")
    return parsed, model.replace("models/", "")


def weighted_median(values: list[tuple[float, float]]) -> float:
    if not values:
        return 1.226
    ordered = sorted(values, key=lambda x: x[0])
    total = sum(max(0.0, w) for _, w in ordered)
    if total <= 0:
        return statistics.median(v for v, _ in ordered)
    acc = 0.0
    for value, weight in ordered:
        acc += max(0.0, weight)
        if acc >= total / 2.0:
            return value
    return ordered[-1][0]


def calibration_for_ghi(ghi: float) -> dict[str, Any]:
    history = [x for x in state_store.data.get("history", []) if isinstance(x, dict)]
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for record in history:
        ratio = record.get("ratio")
        rghi = record.get("ghi")
        if ratio is None or rghi is None:
            continue
        try:
            ratio_f = max(0.75, min(1.80, float(ratio)))
            rghi_f = float(rghi)
        except Exception:
            continue
        distance = abs(rghi_f - ghi)
        candidates.append((distance, ratio_f, record))
    candidates.sort(key=lambda x: x[0])
    nearest = candidates[:8]
    weighted: list[tuple[float, float]] = []
    for distance, ratio, record in nearest:
        recency_bonus = 1.0
        try:
            age_days = max(0, (now_local().date() - date.fromisoformat(str(record.get("date")))).days)
            recency_bonus = max(0.55, math.exp(-age_days / 120.0))
        except Exception:
            pass
        weight = recency_bonus / (0.35 + distance)
        weighted.append((ratio, weight))
    factor = weighted_median(weighted) if weighted else 1.226
    all_ghis = [float(x.get("ghi")) for x in history if x.get("ghi") is not None]
    min_ghi = min(all_ghis) if all_ghis else 2.03
    max_ghi = max(all_ghis) if all_ghis else 7.09
    out_of_range = ghi < min_ghi or ghi > max_ghi
    return {
        "factor": round(factor, 3),
        "nearest_count": len(nearest),
        "training_min_ghi": round(min_ghi, 2),
        "training_max_ghi": round(max_ghi, 2),
        "out_of_range": out_of_range,
    }


def plan_value(raw: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any]:
    factor = float(calibration["factor"])
    conservative = float(raw.get("conservative_kwh", 0)) * factor
    expected = float(raw.get("expected_kwh", 0)) * factor
    optimistic = float(raw.get("optimistic_kwh", 0)) * factor
    if calibration.get("out_of_range"):
        safe_plan = conservative * 0.85
    else:
        safe_plan = conservative
    return {
        "conservative_kwh": round(conservative, 1),
        "expected_kwh": round(expected, 1),
        "optimistic_kwh": round(optimistic, 1),
        "plan_kwh": round(max(0.0, safe_plan), 1),
    }


def forecast_cache_usable(max_age_hours: float = 36.0) -> bool:
    forecasts = state_store.data.get("forecast", {})
    if not isinstance(forecasts, dict) or not forecasts:
        return False
    stamp = state_store.data.get("last_forecast_run")
    if not stamp:
        return False
    try:
        dt = datetime.fromisoformat(str(stamp))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz())
        age = (now_local() - dt.astimezone(local_tz())).total_seconds() / 3600.0
        return 0 <= age <= max_age_hours
    except Exception:
        return False


def weather_changed_materially(daily_metrics: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Vergleicht aktualisierte Wetterdaten mit der gespeicherten Prognose.

    Nur bei einer echten Änderung wird Gemini erneut aufgerufen. Open-Meteo selbst
    bleibt kostenlos und darf zur Entscheidung aktualisiert werden.
    """
    saved = state_store.data.get("forecast", {})
    if not isinstance(saved, dict) or not saved:
        return True, ["keine gespeicherte Prognose"]
    start = planning_start_date(now_local())
    relevant = {start.isoformat(), (start + timedelta(days=1)).isoformat()}
    ghi_threshold = max(5.0, float(settings_store.data.get("gemini_late_ghi_change_percent", 15.0)))
    cloud_threshold = max(5.0, float(settings_store.data.get("gemini_late_cloud_change_points", 20.0)))
    reasons: list[str] = []
    for metrics in daily_metrics:
        ds = str(metrics.get("date") or "")
        if ds not in relevant:
            continue
        old = saved.get(ds, {}) if isinstance(saved.get(ds), dict) else {}
        old_w = old.get("weather", {}) if isinstance(old.get("weather"), dict) else {}
        if not old_w:
            reasons.append(f"{ds}: neuer Horizont")
            continue
        old_ghi = float(old_w.get("ghi_kwh_m2") or 0)
        new_ghi = float(metrics.get("ghi_kwh_m2") or 0)
        if old_ghi > 0.15:
            diff_pct = abs(new_ghi - old_ghi) / old_ghi * 100.0
            if diff_pct >= ghi_threshold:
                reasons.append(f"{ds}: GHI {diff_pct:.0f}%")
        elif abs(new_ghi - old_ghi) >= 0.5:
            reasons.append(f"{ds}: GHI deutlich geändert")
        old_cloud = old_w.get("cloud_day_percent")
        new_cloud = metrics.get("cloud_day_percent")
        if old_cloud is not None and new_cloud is not None:
            if abs(float(new_cloud) - float(old_cloud)) >= cloud_threshold:
                reasons.append(f"{ds}: Wolken {abs(float(new_cloud)-float(old_cloud)):.0f} Punkte")
        old_rain = float(old_w.get("precipitation_mm") or 0)
        new_rain = float(metrics.get("precipitation_mm") or 0)
        if abs(new_rain - old_rain) >= 5.0 and max(old_rain, new_rain) >= 5.0:
            reasons.append(f"{ds}: Regen {abs(new_rain-old_rain):.1f} mm")
    return bool(reasons), reasons


def forecasts_from_saved_weather(
    daily_metrics: list[dict[str, Any]],
    hourly_by_day: dict[str, list[dict[str, Any]]],
    reason: str,
) -> dict[str, Any]:
    """Aktualisiert Wetter/Hourly ohne einen neuen Gemini-Aufruf.

    Vorhandene Gemini-Rohwerte werden nur proportional zur veränderten GHI skaliert.
    Für neu in den 3-Tage-Horizont gerückte Tage wird der kostenlose Physik-Fallback
    verwendet, bis der nächste reguläre 20:00-Gemini-Lauf erfolgt.
    """
    saved = state_store.data.get("forecast", {})
    archive = state_store.data.get("forecast_archive", {})
    current = now_local()
    forecasts: dict[str, Any] = {}
    for metrics in daily_metrics:
        ds = str(metrics.get("date") or "")
        previous = None
        if isinstance(saved, dict):
            previous = saved.get(ds)
        if not previous and isinstance(archive, dict):
            previous = archive.get(ds)
        # 00:00–04:59 bleibt die Vorabendprognose für HEUTE vollständig maßgeblich.
        if current.hour < 5 and ds == current.date().isoformat() and isinstance(previous, dict):
            forecasts[ds] = previous
            continue
        raw: dict[str, Any]
        if isinstance(previous, dict) and isinstance(previous.get("raw"), dict):
            raw = dict(previous["raw"])
            old_weather = previous.get("weather", {}) if isinstance(previous.get("weather"), dict) else {}
            old_ghi = float(old_weather.get("ghi_kwh_m2") or 0)
            new_ghi = float(metrics.get("ghi_kwh_m2") or 0)
            scale = new_ghi / old_ghi if old_ghi > 0.15 else 1.0
            scale = max(0.60, min(1.50, scale))
            for key in ("conservative_kwh", "expected_kwh", "optimistic_kwh"):
                try:
                    raw[key] = round(max(0.0, float(raw.get(key, 0)) * scale), 1)
                except Exception:
                    pass
            raw["reason"] = f"Wetter-Update ohne neuen Gemini-Aufruf ({reason})."
            try:
                raw["confidence_percent"] = max(45, int(raw.get("confidence_percent", 60)) - 3)
            except Exception:
                pass
        else:
            raw = dict({"date": ds}, **physics_fallback(metrics))
            raw["reason"] = f"Neuer Horizont ohne Gemini ({reason}); Physik-Fallback bis 20:00."
        raw["date"] = ds
        calibration = calibration_for_ghi(float(metrics.get("ghi_kwh_m2") or 0))
        forecasts[ds] = {
            "weather": metrics,
            "hourly": hourly_by_day.get(ds, []),
            "raw": raw,
            "calibration": calibration,
            "calibrated": plan_value(raw, calibration),
        }
    return forecasts


def _remember_battery_plan(plan: dict[str, Any]) -> None:
    """Merkt das geplante 05:00-Ziel datumsfest für die spätere Lernkontrolle.

    Nach 05:00 darf ein 07:00-/Startup-Neuplan für denselben Kalendertag das
    Ziel der bereits vergangenen Nacht nicht überschreiben. Für morgen bzw. vor
    05:00 bleibt das zuletzt berechnete Ziel dagegen maßgeblich.
    """
    if not isinstance(plan, dict):
        return
    day = str(plan.get("primary_date") or "")
    target = (plan.get("battery") or {}).get("target_soc")
    if not day or target is None:
        return
    try:
        plan_day = date.fromisoformat(day)
    except Exception:
        return
    now = now_local()
    if plan_day < now.date() or (plan_day == now.date() and now.hour >= 5):
        return
    learning = state_store.data.setdefault("battery_learning", {})
    battery = plan.get("battery") or {}
    learning["planned_0500_date"] = day
    learning["planned_0500_target_soc"] = target
    learning["planned_cover_time"] = battery.get("predicted_cover_time")
    learning["planned_adjusted_cover_time"] = battery.get("adjusted_cover_time")
    learning["planned_morning_predicted_need_kwh"] = battery.get("predicted_morning_need_kwh")
    learning["planned_morning_energy_buffer_soc"] = battery.get("morning_energy_buffer_soc")


def _remember_daily_action_plan(plan: dict[str, Any], reason: str) -> None:
    """Friert die 20-Uhr-Entscheidung Nacht-vs.-Tag für den Folgetag ein."""
    if not str(reason or "").startswith("main") or not isinstance(plan, dict):
        return
    day = str(plan.get("primary_date") or "")
    if not day:
        return
    dishwasher = plan.get("dishwasher") if isinstance(plan.get("dishwasher"), dict) else {}
    warmwater = plan.get("warmwater") if isinstance(plan.get("warmwater"), dict) else {}
    snapshots = state_store.data.setdefault("daily_action_plans", {})
    snapshots[day] = {
        "date": day,
        "captured_at": now_local().isoformat(),
        "dishwasher": dict(dishwasher),
        "warmwater": dict(warmwater),
    }
    cutoff = now_local().date() - timedelta(days=14)
    for ds in list(snapshots.keys()):
        try:
            if date.fromisoformat(ds) < cutoff:
                snapshots.pop(ds, None)
        except Exception:
            pass


def _daily_action_plan(day: str) -> dict[str, Any]:
    value = state_store.data.get("daily_action_plans", {}).get(str(day), {})
    return value if isinstance(value, dict) else {}


def _warmwater_ended_in_night(day: str) -> bool:
    session = state_store.data.get("warmwater_session", {})
    if not isinstance(session, dict) or not session.get("ended"):
        return False
    try:
        ended = datetime.fromisoformat(str(session.get("ended"))).astimezone(local_tz())
        return ended.date().isoformat() == str(day) and (ended.hour * 60 + ended.minute) <= 5 * 60 + 10
    except Exception:
        return False


def refresh_weather_only(
    reason: str = "weather",
    notify: bool = False,
    supplied: tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    daily_metrics, hourly_by_day = supplied if supplied is not None else open_meteo_forecast()
    forecasts = forecasts_from_saved_weather(daily_metrics, hourly_by_day, reason)
    previous_plan = state_store.data.get("plan", {})
    plan = build_plan(forecasts, {ds: v.get("hourly", []) for ds, v in forecasts.items()})
    with state_store.lock:
        state_store.data["forecast"] = forecasts
        state_store.data["plan"] = plan
        _remember_battery_plan(plan)
        _remember_daily_action_plan(plan, reason)
        state_store.data["last_weather_refresh"] = now_local().isoformat()
        if "Gemini-Fehler" not in reason:
            state_store.data["last_error"] = None
        # last_forecast_run bleibt der Zeitpunkt des letzten echten Gemini-Laufs.
        state_store.data["version"] = VERSION
        state_store.save()
    if notify:
        send_plan_notification(reason, previous_plan, plan, forecasts)
    return {"forecast": forecasts, "plan": plan, "source": "weather-only"}


def best_warmwater_window(hourly_rows: list[dict[str, Any]]) -> tuple[str, str]:
    settings = settings_store.data
    start_hour = int(settings.get("warmwater_day_start_hour", 9))
    end_hour = int(settings.get("warmwater_day_end_hour", 16))
    duration_hours = max(1, int(settings.get("warmwater_duration_minutes", 120)) // 60)
    filtered = [r for r in hourly_rows if start_hour <= int(str(r["time"])[11:13]) < end_hour]
    if len(filtered) < duration_hours:
        return "10:00", "12:00"
    best_idx = 0
    best_sum = -1.0
    for i in range(0, len(filtered) - duration_hours + 1):
        score = sum(float(filtered[j].get("radiation_wm2", 0)) for j in range(i, i + duration_hours))
        if score > best_sum:
            best_sum = score
            best_idx = i
    first = filtered[best_idx]["time"]
    start_dt = datetime.fromisoformat(first)
    end_dt = start_dt + timedelta(hours=duration_hours)
    return start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")


def _learned_morning_reserve_soc() -> float:
    """Aktuelle gelernte Mindestreserve bei stabiler PV-Übernahme."""
    minimum = max(5.0, float(settings_store.data.get("morning_min_soc", 5) or 5))
    learning = state_store.data.setdefault("morning_learning", {})
    try:
        value = float(learning.get("desired_cover_soc", minimum) or minimum)
    except (TypeError, ValueError):
        value = minimum
    return max(5.0, min(35.0, value))


def _forecast_hourly_energy(expected_kwh: float, hourly_rows: list[dict[str, Any]]) -> list[tuple[int, float]]:
    """Verteilt die kalibrierte Tagesprognose auf Stunden nach Open-Meteo-GHI."""
    rows: list[tuple[int, float]] = []
    total_radiation = 0.0
    for row in hourly_rows or []:
        try:
            hour = int(str(row.get("time", ""))[11:13])
            radiation = max(0.0, float(row.get("radiation_wm2", 0) or 0))
        except Exception:
            continue
        total_radiation += radiation
        if 5 <= hour < 24:
            rows.append((hour, radiation))
    if total_radiation <= 0 or not rows:
        return []
    return [(hour, max(0.0, float(expected_kwh or 0.0)) * radiation / total_radiation) for hour, radiation in rows]


def _time_to_minutes(value: Any) -> int | None:
    match = re.match(r"^(\d{1,2}):(\d{2})$", str(value or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _minutes_to_time(minutes: float | int | None) -> str | None:
    if minutes is None:
        return None
    value = max(0, min(23 * 60 + 59, int(round(float(minutes)))))
    return f"{value // 60:02d}:{value % 60:02d}"


def _standby_restload_kw() -> tuple[float, float | None]:
    """Planungswert für die ruhige Morgenlast, getrennt von der Tagesgrundlast."""
    standby = state_store.data.get("standby_learning", {})
    estimate = standby.get("estimate_w") if isinstance(standby, dict) else None
    try:
        estimate_w = float(estimate) if estimate is not None else None
    except (TypeError, ValueError):
        estimate_w = None
    if estimate_w is not None and 40.0 <= estimate_w <= 1800.0:
        return estimate_w / 1000.0, estimate_w
    # Solange noch keine sauberen 5-Minuten-Fenster vorliegen, bewusst unterhalb
    # der Tagesgrundlast bleiben. Dieser Fallback wird automatisch ersetzt,
    # sobald Standby-Lernen Daten liefert.
    day_base = max(0.0, float(settings_store.data.get("day_house_base_kw", 0.85) or 0.85))
    fallback_kw = min(day_base, 0.70)
    return fallback_kw, None


def _forecast_cover_minutes(
    expected_kwh: float,
    hourly_rows: list[dict[str, Any]],
    forecast_meta: dict[str, Any] | None,
    restload_kw: float,
) -> tuple[int | None, str]:
    """Gemini-Übernahmepunkt bevorzugen, sonst konservativ aus Stundenprofil ableiten."""
    raw = forecast_meta.get("raw", {}) if isinstance(forecast_meta, dict) else {}
    gemini_time = raw.get("stable_pv_cover_time") if isinstance(raw, dict) else None
    gemini_minutes = _time_to_minutes(gemini_time)
    if gemini_minutes is not None and 5 * 60 <= gemini_minutes <= 13 * 60:
        return gemini_minutes, "Gemini"

    profile = _forecast_hourly_energy(expected_kwh, hourly_rows)
    by_hour = {hour: pv_kwh for hour, pv_kwh in profile}
    # Fallback: mindestens zwei aufeinanderfolgende Stunden oberhalb der Restlast.
    for hour in range(5, 13):
        if by_hour.get(hour, 0.0) >= restload_kw and by_hour.get(hour + 1, 0.0) >= restload_kw:
            return hour * 60, "Stundenprofil-Fallback"
    return None, "keine stabile Morgen-PV prognostiziert"


def _predicted_morning_breakdown(
    expected_kwh: float,
    hourly_rows: list[dict[str, Any]],
    end_minutes: int | None,
    restload_kw: float,
) -> list[dict[str, Any]]:
    """Nachvollziehbare Teilrechnung 05:00→PV-Übernahme je Stundenanteil."""
    if end_minutes is None:
        return []
    start_minutes = 5 * 60
    end_minutes = max(start_minutes, min(13 * 60, int(end_minutes)))
    if end_minutes <= start_minutes:
        return []
    profile = dict(_forecast_hourly_energy(expected_kwh, hourly_rows))
    rows: list[dict[str, Any]] = []
    for hour in range(5, 13):
        hour_start = hour * 60
        hour_end = hour_start + 60
        overlap_start = max(start_minutes, hour_start)
        overlap_end = min(end_minutes, hour_end)
        overlap = max(0, overlap_end - overlap_start)
        if overlap <= 0:
            continue
        fraction = overlap / 60.0
        # pv_kwh ist die prognostizierte Energie der vollen Stunde; für den
        # anteiligen Zeitraum wird dieselbe mittlere Leistung verwendet.
        full_hour_pv_kwh = max(0.0, float(profile.get(hour, 0.0) or 0.0))
        pv_kwh = full_hour_pv_kwh * fraction
        load_kwh = max(0.0, restload_kw) * fraction
        net_need_kwh = max(0.0, load_kwh - pv_kwh)
        rows.append({
            "from": _minutes_to_time(overlap_start),
            "to": _minutes_to_time(overlap_end),
            "minutes": int(overlap),
            "fraction": round(fraction, 3),
            "restload_w": round(max(0.0, restload_kw) * 1000.0),
            "load_kwh": round(load_kwh, 3),
            "pv_full_hour_kwh": round(full_hour_pv_kwh, 3),
            "pv_kwh": round(pv_kwh, 3),
            "net_need_kwh": round(net_need_kwh, 3),
        })
    return rows


def _predicted_morning_net_need(
    expected_kwh: float,
    hourly_rows: list[dict[str, Any]],
    end_minutes: int | None,
    restload_kw: float,
) -> float | None:
    """Nettoenergie 05:00→PV-Übernahme, stundenanteilig Restlast minus PV."""
    if end_minutes is None:
        return None
    rows = _predicted_morning_breakdown(expected_kwh, hourly_rows, end_minutes, restload_kw)
    return max(0.0, sum(float(row.get("net_need_kwh", 0.0) or 0.0) for row in rows))


def _required_extra_soc_after_morning_bridge(
    expected_kwh: float,
    hourly_rows: list[dict[str, Any]],
    base_kw: float,
    reserve_soc: float,
    bridge_end_minutes: int | None = None,
) -> tuple[float, str]:
    """Zusätzlicher 05:00-Puffer für den Zeitraum nach der Morgenbrücke.

    Die Morgenbrücke selbst wird mit der gelernten Standby-/Restlast gerechnet.
    Ab der prognostizierten PV-Übernahme gilt wieder die planungsrelevante
    Tagesgrundlast. So bleiben die beiden Lernwerte sauber getrennt.
    """
    profile = _forecast_hourly_energy(expected_kwh, hourly_rows)
    reserve_kwh = BATTERY_CAPACITY_KWH * reserve_soc / 100.0
    base_kw = max(0.0, float(base_kw or 0.0))

    if not profile:
        remaining_need = max(0.0, base_kw * 19.0 - max(0.0, float(expected_kwh or 0.0)))
        return min(100.0 - reserve_soc, remaining_need / BATTERY_CAPACITY_KWH * 100.0), "Tagesenergiebilanz"

    by_hour = dict(profile)
    start_min = bridge_end_minutes
    if start_min is None:
        for hour in range(5, 24):
            if by_hour.get(hour, 0.0) >= base_kw:
                start_min = hour * 60
                break
    if start_min is None:
        start_min = 5 * 60
    start_min = max(5 * 60, min(24 * 60, int(start_min)))

    def survives(extra_soc: float) -> bool:
        energy = reserve_kwh + BATTERY_CAPACITY_KWH * max(0.0, extra_soc) / 100.0
        energy = min(BATTERY_CAPACITY_KWH, energy)
        for hour in range(5, 24):
            hour_start = hour * 60
            hour_end = hour_start + 60
            overlap = max(0, hour_end - max(start_min, hour_start))
            if overlap <= 0:
                continue
            fraction = overlap / 60.0
            pv_kwh = max(0.0, float(by_hour.get(hour, 0.0) or 0.0)) * fraction
            energy = min(BATTERY_CAPACITY_KWH, energy + pv_kwh - base_kw * fraction)
            if energy < reserve_kwh - 1e-6:
                return False
        return True

    label = _minutes_to_time(start_min) or "05:00"
    if survives(0.0):
        return 0.0, f"PV/Grundlast-Resttag ab {label} ohne Zusatzpuffer"

    max_extra = 100.0 - reserve_soc
    if not survives(max_extra):
        return max_extra, "Resttag benötigt maximalen Speicherpuffer"

    lo, hi = 0.0, max_extra
    for _ in range(20):
        mid = (lo + hi) / 2.0
        if survives(mid):
            hi = mid
        else:
            lo = mid
    return hi, f"Resttag ab {label}"


def battery_target_details(
    expected_kwh: float,
    hourly_rows: list[dict[str, Any]] | None = None,
    forecast_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Selbstlernendes 05:00-Ziel aus prognostizierter Morgenbrücke und Resttag."""
    s = settings_store.data
    morning = state_store.data.setdefault("morning_learning", {})
    reserve_soc = _learned_morning_reserve_soc()
    base_kw = max(0.0, float(s.get("day_house_base_kw", 0.85) or 0.85))
    day_basis_kwh = base_kw * 19.0
    restload_kw, learned_standby_w = _standby_restload_kw()
    calibrated_meta = forecast_meta.get("calibrated", {}) if isinstance(forecast_meta, dict) else {}
    try:
        conservative_plan_kwh = float(calibrated_meta.get("plan_kwh", 0) or 0)
    except (TypeError, ValueError):
        conservative_plan_kwh = 0.0
    # Für die kurze Morgenbrücke wird bewusst der konservative Planwert genutzt,
    # sofern er vorhanden ist. So wird ein schwacher Morgen nicht dadurch
    # kleingerechnet, dass die erwartete Tagesmenge später noch aufgeholt wird.
    morning_forecast_kwh = conservative_plan_kwh if conservative_plan_kwh > 0 else float(expected_kwh or 0.0)

    try:
        learned_need = max(0.0, float(morning.get("learned_net_need_kwh", 1.55) or 1.55))
    except (TypeError, ValueError):
        learned_need = 1.55
    try:
        time_offset = float(morning.get("cover_time_offset_minutes", 0.0) or 0.0)
    except (TypeError, ValueError):
        time_offset = 0.0
    time_offset = max(-30.0, min(120.0, time_offset))
    try:
        energy_buffer_soc = float(morning.get("energy_buffer_soc", 0.0) or 0.0)
    except (TypeError, ValueError):
        energy_buffer_soc = 0.0
    energy_buffer_soc = max(0.0, min(15.0, energy_buffer_soc))

    forecast_cover_min, cover_source = _forecast_cover_minutes(
        morning_forecast_kwh, hourly_rows or [], forecast_meta, restload_kw
    )
    adjusted_cover_min = None
    if forecast_cover_min is not None:
        adjusted_cover_min = int(round(max(5 * 60, min(13 * 60, forecast_cover_min + time_offset))))
    predicted_need = _predicted_morning_net_need(
        morning_forecast_kwh, hourly_rows or [], adjusted_cover_min, restload_kw
    )
    morning_breakdown = _predicted_morning_breakdown(
        morning_forecast_kwh, hourly_rows or [], adjusted_cover_min, restload_kw
    )

    # Mit neuer Prognosedatenbasis ist der konkret berechnete Morgenbedarf
    # maßgeblich. Historischer Bedarf bleibt nur als Fallback erhalten.
    bridge_need = learned_need if predicted_need is None else predicted_need
    bridge_need_with_buffer = bridge_need + BATTERY_CAPACITY_KWH * energy_buffer_soc / 100.0
    morning_bridge_target = reserve_soc + bridge_need_with_buffer / BATTERY_CAPACITY_KWH * 100.0

    extra_after_bridge_soc, profile_reason = _required_extra_soc_after_morning_bridge(
        expected_kwh, hourly_rows or [], base_kw, reserve_soc, adjusted_cover_min
    )
    automatic_target = min(100.0, morning_bridge_target + extra_after_bridge_soc)

    try:
        manual_offset = float(s.get("battery_soc_manual_offset", 0.0) or 0.0)
    except (TypeError, ValueError):
        manual_offset = 0.0
    manual_offset = max(-10.0, min(10.0, manual_offset))
    target = max(5.0, min(100.0, automatic_target + manual_offset))

    if target >= 99.5:
        mode = "100 % wegen schwacher bzw. ungünstig verteilter PV"
    elif extra_after_bridge_soc >= 1.0:
        mode = "prognostizierte Morgenbrücke + Resttag-Puffer"
    elif predicted_need is not None:
        mode = "prognostizierte Morgenbrücke bis stabile PV-Deckung"
    else:
        mode = "gelernte Morgenbrücke (Forecast-Fallback)"
    return {
        "target_soc": int(round(target)),
        "automatic_target_soc": round(automatic_target, 1),
        "manual_offset_soc": round(manual_offset, 1),
        "minimum_reserve_soc": round(reserve_soc, 1),
        "profile_target_soc": round(min(100.0, morning_bridge_target + extra_after_bridge_soc), 1),
        "post_bridge_extra_soc": round(extra_after_bridge_soc, 1),
        "profile_reason": profile_reason,
        "morning_bridge_target_soc": round(min(100.0, morning_bridge_target), 1),
        "learned_morning_need_kwh": round(learned_need, 2),
        "predicted_morning_need_kwh": None if predicted_need is None else round(predicted_need, 2),
        "predicted_cover_time": _minutes_to_time(forecast_cover_min),
        "adjusted_cover_time": _minutes_to_time(adjusted_cover_min),
        "cover_time_source": cover_source,
        "cover_time_offset_minutes": round(time_offset, 1),
        "morning_energy_buffer_soc": round(energy_buffer_soc, 1),
        "standby_restload_w": round(restload_kw * 1000.0),
        "standby_learned": learned_standby_w is not None,
        "house_base_kw": round(base_kw, 2),
        "day_basis_kwh": round(day_basis_kwh, 2),
        "forecast_basis_kwh": round(float(expected_kwh or 0.0), 1),
        "morning_forecast_basis_kwh": round(float(morning_forecast_kwh or 0.0), 1),
        "morning_breakdown": morning_breakdown,
        "bridge_need_before_buffer_kwh": round(float(bridge_need), 2),
        "bridge_energy_buffer_kwh": round(BATTERY_CAPACITY_KWH * energy_buffer_soc / 100.0, 2),
        "bridge_need_with_buffer_kwh": round(float(bridge_need_with_buffer), 2),
        "mode": mode,
    }

def battery_target_for_plan(plan_kwh: float, hourly_rows: list[dict[str, Any]] | None = None) -> int:
    return int(battery_target_details(plan_kwh, hourly_rows)["target_soc"])

def battery_schedule(current_soc: float | None, target_soc: float) -> dict[str, Any]:
    """Spätester Start mit gelerntem Vorlauf, damit das 05:00-Ziel sicher erreicht wird."""
    learning = state_store.data.get("battery_learning", {})
    effective_kw = float(learning.get("effective_charge_kw") or BATTERY_SAFE_CHARGE_KW)
    effective_kw = max(0.5, min(2.2, effective_kw))
    try:
        start_buffer = int(round(float(learning.get("start_buffer_minutes", 10) or 10)))
    except (TypeError, ValueError):
        start_buffer = 10
    start_buffer = max(0, min(30, start_buffer))
    if current_soc is None:
        return {
            "start_time": "–",
            "needed_minutes": None,
            "start_buffer_minutes": start_buffer,
            "effective_charge_kw": round(effective_kw, 2),
            "reachable": False,
            "needed_kwh": None,
        }
    needed_pct = max(0.0, float(target_soc) - float(current_soc))
    needed_kwh = BATTERY_CAPACITY_KWH * needed_pct / 100.0
    if needed_kwh <= 0.001:
        return {
            "start_time": "nicht nötig",
            "needed_minutes": 0,
            "start_buffer_minutes": start_buffer,
            "effective_charge_kw": round(effective_kw, 2),
            "reachable": True,
            "needed_kwh": 0.0,
        }
    needed_minutes = int(math.ceil(needed_kwh / effective_kw * 60.0))
    # Der Vorlauf wird nur für den Start verwendet. Am Ziel-SOC wird weiterhin
    # sofort abgeschaltet, sodass der Puffer nicht zu einer Überladung führt.
    start_minute = max(0, 300 - needed_minutes - start_buffer)
    return {
        "start_time": f"{start_minute // 60:02d}:{start_minute % 60:02d}",
        "needed_minutes": needed_minutes,
        "start_buffer_minutes": start_buffer,
        "effective_charge_kw": round(effective_kw, 2),
        "reachable": needed_minutes <= 300,
        "needed_kwh": round(needed_kwh, 2),
    }


def car_recommendation(
    soc: float | None,
    target: int,
    min_morning: int,
    primary_plan: float,
    secondary_plan: float,
) -> dict[str, Any]:
    if soc is None:
        return {"action": "unknown", "label": "Ladezustand nicht verfügbar", "reason": "Kein gültiger SOC."}
    if soc >= target:
        return {"action": "none", "label": "Kein Laden nötig", "reason": f"SOC {soc:.0f}% liegt am Ziel von {target}%."}
    if soc < min_morning:
        return {"action": "fast", "label": "Nachts schnellladen", "reason": f"SOC {soc:.0f}% liegt unter Mindestwert {min_morning}%."}
    # Ein sehr schwacher unmittelbar bevorstehender PV-Tag soll nicht durch einen
    # guten zweiten Tag schöngerechnet werden. Ist das Auto noch unter seinem
    # Nachtziel, wird deshalb bei <20 kWh für diese Nacht Schnellladen empfohlen.
    if primary_plan < 20 and soc < target:
        return {"action": "fast", "label": "Nachts schnellladen", "reason": f"Der unmittelbar bevorstehende PV-Tag ist mit {primary_plan:.1f} kWh sehr schwach."}
    if primary_plan >= 30:
        return {"action": "pv", "label": "Auf PV warten", "reason": f"Der unmittelbar bevorstehende Tag bietet {primary_plan:.1f} kWh planbares PV-Potenzial."}
    if primary_plan + secondary_plan >= 50 and soc >= target - 15:
        return {"action": "pv", "label": "PV abwarten", "reason": "SOC ist ausreichend und in den nächsten zwei Tagen ist genügend PV-Potenzial vorhanden."}
    if soc < target - 10 and primary_plan < 30:
        return {"action": "fast", "label": "Nachts schnellladen", "reason": "SOC liegt unter dem Nachtziel und der nächste PV-Tag ist eher schwach."}
    return {"action": "wait", "label": "Noch warten", "reason": "Kein zwingender Nachtladebedarf; PV-Chance bleibt bestehen."}


def car_at_wallbox() -> bool:
    return bool(state_store.data.get("car_at_wallbox", True))


def current_night_target() -> int:
    override = state_store.data.get("night_target_override_soc")
    try:
        if override is not None:
            value = int(override)
            if 20 <= value <= 100:
                return value
    except Exception:
        pass
    return int(settings_store.data.get("car_night_target_soc", 50))


def _cable_is_connected(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"on", "connected", "true", "1", "yes"}


def connected_car_hint() -> dict[str, Any]:
    """Bestmögliche Erkennung des tatsächlich angeschlossenen Autos.

    Vorrang haben die Kabelsensoren. Danach wird eine bereits erkannte
    Ladesitzung verwendet. Fehlt beides, wird bei ``Auto da`` der niedrigere
    bekannte SOC als konservativer Startwert genommen; sobald das Laden beginnt,
    übernimmt die bestehende SOC-Anstiegserkennung.
    """
    id7 = state_value(ENTITIES["id7_soc"])
    egolf = state_value(ENTITIES["egolf_soc"])
    id7_cable = state_text(ENTITIES["id7_cable"])
    egolf_cable = state_text(ENTITIES.get("egolf_cable", "")) if ENTITIES.get("egolf_cable") else "unknown"

    if _cable_is_connected(id7_cable):
        return {"vehicle": "id7", "label": "ID.7", "soc": id7, "source": "Kabelsensor"}
    if _cable_is_connected(egolf_cable):
        return {"vehicle": "egolf", "label": "e-Golf", "soc": egolf, "source": "Kabelsensor"}

    session = state_store.data.get("wallbox_session", {})
    active = session.get("active_vehicle") if isinstance(session, dict) else None
    if active == "id7":
        return {"vehicle": "id7", "label": "ID.7", "soc": id7, "source": "Ladesitzung"}
    if active == "egolf":
        return {"vehicle": "egolf", "label": "e-Golf", "soc": egolf, "source": "Ladesitzung"}

    known = [("id7", "ID.7", id7), ("egolf", "e-Golf", egolf)]
    known = [(key, label, float(soc)) for key, label, soc in known if soc is not None]
    if known:
        key, label, soc = min(known, key=lambda item: item[2])
        return {"vehicle": key, "label": label, "soc": soc, "source": "niedrigerer SOC (Fallback)"}
    return {"vehicle": None, "label": None, "soc": None, "source": "unbekannt"}


def night_wallbox_decision() -> dict[str, Any]:
    """Aktuelle Nachtentscheidung ohne Einfluss der PV-Prognose.

    * auto: bis zum gewählten Mindest-SOC schnellladen, falls nötig
    * fast: Schnellladen bis Ziel erzwingen
    * pv_wait: nachts immer aus; tagsüber bleibt PV-Überschuss möglich
    """
    target = current_night_target()
    mode = str(state_store.data.get("night_override", "auto") or "auto")
    if not bool(state_store.data.get("car_auto_charging_enabled", True)):
        return {"action": "paused", "mode": mode, "target": target, "soc": None, "vehicle": None, "reason": "Automatische Autoladung ist manuell pausiert."}
    if not car_at_wallbox():
        return {"action": "none", "mode": mode, "target": target, "soc": None, "vehicle": None, "reason": "Kein Auto an der Wallbox."}
    hint = connected_car_hint()
    soc = hint.get("soc")
    if mode == "pv_wait":
        return {"action": "pv_wait", "mode": mode, "target": target, **hint, "reason": "Nur PV: nachts kein Schnellladen."}
    if mode == "fast":
        reached = soc is not None and float(soc) >= target
        return {"action": "done" if reached else "fast", "mode": mode, "target": target, **hint, "reason": f"Nacht schnell bis {target} %."}
    # Automatik: Das Ziel ist ausschließlich das Mindest-SOC für 05:00 Uhr.
    # Die PV-Prognose darf das Nachladen bis zu diesem Mindestwert nicht verhindern.
    if soc is None:
        return {"action": "fast", "mode": "auto", "target": target, **hint, "reason": f"Automatik: Fahrzeug-SOC noch nicht eindeutig; Mindestziel {target} % wird abgesichert."}
    if float(soc) < target:
        return {"action": "fast", "mode": "auto", "target": target, **hint, "reason": f"Automatik: {hint.get('label') or 'Auto'} liegt bei {float(soc):.0f} % und damit unter dem Mindestziel {target} %."}
    return {"action": "done", "mode": "auto", "target": target, **hint, "reason": f"Automatik: Mindestziel {target} % bereits erreicht."}


def combined_car_recommendation(
    id7: float | None,
    egolf: float | None,
    primary_plan: float,
    secondary_plan: float,
) -> dict[str, Any]:
    """Nacht/PV-Entscheidung aus beiden Fahrzeug-SOCs und zwei PV-Tagen.

    Die Entscheidung wählt bewusst kein Fahrzeug aus. Physisch steckt der Nutzer
    selbst das gewünschte Auto an die einzige Wallbox.
    """
    s = settings_store.data
    values = [("ID.7", id7), ("e-Golf", egolf)]
    available = [(name, float(soc)) for name, soc in values if soc is not None]
    if not available:
        return {"action": "unknown", "label": "Auto-SOC nicht verfügbar", "reason": "Kein gültiger Fahrzeug-SOC."}
    lowest_name, lowest_soc = min(available, key=lambda x: x[1])
    id7_min = float(s.get("id7_min_morning_soc", 40))
    egolf_min = float(s.get("egolf_min_morning_soc", 40))
    urgent = (id7 is not None and id7 < id7_min) or (egolf is not None and egolf < egolf_min)
    target = current_night_target()
    two_day = max(0.0, primary_plan) + max(0.0, secondary_plan)
    if urgent and primary_plan < 40:
        return {"action": "fast", "label": "Schnellladen empfohlen", "reason": f"{lowest_name} steht nur bei {lowest_soc:.0f}% und der nächste PV-Tag ist nicht stark genug."}
    if lowest_soc < target and (primary_plan < 20 or two_day < 50):
        return {"action": "fast", "label": "Schnellladen empfohlen", "reason": f"Mindestens ein Auto liegt unter {target}% und die nächsten zwei PV-Tage bieten nur begrenzte Reserve."}
    if primary_plan >= 30 or two_day >= 60:
        return {"action": "pv", "label": "PV abwarten", "reason": f"In den nächsten zwei Tagen stehen rund {two_day:.0f} kWh planbares PV-Potenzial an."}
    if lowest_soc < target:
        return {"action": "fast", "label": "Schnellladen empfohlen", "reason": f"{lowest_name} liegt unter dem Nachtziel {target}% und die PV-Reserve ist knapp."}
    return {"action": "pv", "label": "PV abwarten", "reason": "Beide Fahrzeuge haben ausreichend Reserve; PV hat Vorrang."}


def start_wallbox_session_if_needed(target_soc: int) -> None:
    with state_store.lock:
        session = state_store.data.setdefault("wallbox_session", {})
        if session.get("active"):
            session["target_soc"] = target_soc
            state_store.save()
            return
        session.update({
            "active": True,
            "started_at": now_local().isoformat(),
            "baseline_id7": state_value(ENTITIES["id7_soc"]),
            "baseline_egolf": state_value(ENTITIES["egolf_soc"]),
            "active_vehicle": None,
            "target_soc": target_soc,
        })
        state_store.save()


def stop_wallbox_session() -> None:
    with state_store.lock:
        session = state_store.data.setdefault("wallbox_session", {})
        session["active"] = False
        session["ended_at"] = now_local().isoformat()
        state_store.save()


def wallbox_session_status(target_soc: int) -> dict[str, Any]:
    """Erkennt das tatsächlich ladende Auto am SOC-Anstieg.

    Ein bereits höherer SOC des nicht angeschlossenen Autos darf die Ladung nicht
    sofort stoppen. Erst wenn ein SOC gegenüber dem Sitzungsstart sichtbar steigt,
    wird genau dieses Fahrzeug als aktiv gewertet.
    """
    start_wallbox_session_if_needed(target_soc)
    with state_store.lock:
        session = state_store.data.setdefault("wallbox_session", {})
        id7 = state_value(ENTITIES["id7_soc"])
        egolf = state_value(ENTITIES["egolf_soc"])
        active = session.get("active_vehicle")
        if active not in {"id7", "egolf"}:
            diffs = {}
            for key, current, baseline in (
                ("id7", id7, session.get("baseline_id7")),
                ("egolf", egolf, session.get("baseline_egolf")),
            ):
                if current is not None and baseline is not None:
                    diffs[key] = float(current) - float(baseline)
            if diffs:
                winner, delta = max(diffs.items(), key=lambda x: x[1])
                if delta >= 1.0:
                    active = winner
                    session["active_vehicle"] = winner
        current_soc = id7 if active == "id7" else egolf if active == "egolf" else None
        session["target_soc"] = target_soc
        state_store.save()
    return {
        "active_vehicle": active,
        "active_vehicle_label": "ID.7" if active == "id7" else "e-Golf" if active == "egolf" else None,
        "current_soc": current_soc,
        "target_soc": target_soc,
        "reached": current_soc is not None and current_soc >= target_soc,
    }


def wallbox_set_pv_phases(phases: int, reset_tracking: bool = True) -> None:
    """PV-Laden sicher auf eine zusammenhängende Phasenzahl umschalten.

    Die SENEC-Wallbox darf ihre Phasen nicht während einer laufenden Ladung
    wechseln. Daher lautet die feste Reihenfolge: Laden sperren, kurz zur Ruhe
    kommen lassen, Phasen setzen, PV-Laden wieder freigeben. Phase 1 bleibt
    aus Sicherheitsgründen immer eingeschaltet.
    """
    phases = max(1, min(3, int(phases)))
    current = (
        1
        + int(state_text(ENTITIES["phase2"]) == "on")
        + int(state_text(ENTITIES["phase3"]) == "on")
    )
    already_set = state_text(ENTITIES["wallbox_mode"]) == "optimized" and current == phases
    if already_set:
        ensure_phase1_on()
        if reset_tracking:
            reset_pv_tracking(f"PV-Laden manuell auf {phases} Phasen", f"optimized_{phases}")
        return

    # Erst die Wallbox sicher stoppen. Der kurze Abstand stellt sicher, dass
    # die Service-Aufrufe in Home Assistant in der gewünschten Reihenfolge bei
    # der Wallbox ankommen, ohne die Direktsteuerung unnötig auszubremsen.
    call_service("select", "select_option", ENTITIES["wallbox_mode"], {"option": "locked"})
    time.sleep(1)
    ensure_phase1_on()
    call_service("switch", "turn_on" if phases >= 2 else "turn_off", ENTITIES["phase2"])
    call_service("switch", "turn_on" if phases >= 3 else "turn_off", ENTITIES["phase3"])
    call_service("select", "select_option", ENTITIES["wallbox_mode"], {"option": "optimized"})
    ensure_phase1_on()
    if reset_tracking:
        reset_pv_tracking(f"PV-Laden manuell auf {phases} Phasen", f"optimized_{phases}")


def best_pv_charge_window(hourly_rows: list[dict[str, Any]], duration_hours: int = 4) -> dict[str, Any]:
    """Bestes zusammenhängendes Tagesfenster für PV-Laden der Wallbox.

    Das ist bewusst ein Strahlungsfenster und keine erfundene kWh-Überschussmenge.
    Erst echte Überschuss-Historie kann später belastbar sagen, wie viele kWh fürs Auto
    übrig bleiben.
    """
    usable = [
        r for r in hourly_rows
        if 7 <= int(str(r.get("time", "00:00"))[11:13]) < 20
    ]
    if not usable:
        return {"start_time": "–", "end_time": "–", "avg_radiation_wm2": 0, "peak_radiation_wm2": 0}
    duration_hours = max(2, min(duration_hours, len(usable)))
    best = usable[:duration_hours]
    best_sum = sum(float(r.get("radiation_wm2", 0) or 0) for r in best)
    for i in range(1, len(usable) - duration_hours + 1):
        window = usable[i:i + duration_hours]
        score = sum(float(r.get("radiation_wm2", 0) or 0) for r in window)
        if score > best_sum:
            best, best_sum = window, score
    start_dt = datetime.fromisoformat(str(best[0]["time"]))
    end_dt = start_dt + timedelta(hours=duration_hours)
    values = [float(r.get("radiation_wm2", 0) or 0) for r in best]
    return {
        "start_time": start_dt.strftime("%H:%M"),
        "end_time": end_dt.strftime("%H:%M"),
        "avg_radiation_wm2": round(sum(values) / len(values), 0),
        "peak_radiation_wm2": round(max(values), 0),
    }


def record_live_pv_sample(now: datetime | None = None) -> None:
    current = now or now_local()
    power = state_value(ENTITIES["pv_power"])
    day_energy = state_value(ENTITIES["pv_day"])
    if power is None and day_energy is None:
        return
    sample = {
        "time": current.isoformat(),
        "power_w": round(float(power or 0), 1),
        "day_kwh": round(float(day_energy or 0), 3),
    }
    keep_after = current - timedelta(hours=30)
    with state_store.lock:
        samples = state_store.data.setdefault("live_pv_samples", [])
        samples.append(sample)
        cleaned: list[dict[str, Any]] = []
        for item in samples[-2400:]:
            try:
                stamp = datetime.fromisoformat(str(item.get("time")))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=local_tz())
                if stamp.astimezone(local_tz()) >= keep_after:
                    cleaned.append(item)
            except Exception:
                continue
        state_store.data["live_pv_samples"] = cleaned
        state_store.save()


def seed_live_pv_samples_from_history() -> None:
    """Füllt nach einem Neustart den heutigen Live-Verlauf aus HA-History.

    Nur einmal beim Start; der Dashboard-Refresh erzeugt dadurch keine zusätzliche
    Recorder-Last. Es wird auf ungefähr 5-Minuten-Punkte ausgedünnt.
    """
    current = now_local()
    today_ds = current.date().isoformat()
    existing = state_store.data.get("live_pv_samples", [])
    if any(str(x.get("time", "")).startswith(today_ds) for x in existing if isinstance(x, dict)):
        return
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    path = (
        "/history/period/"
        + urllib.parse.quote(start.isoformat(), safe="")
        + "?"
        + urllib.parse.urlencode({
            "filter_entity_id": ENTITIES["pv_power"],
            "end_time": current.isoformat(),
            "no_attributes": "1",
        })
    )
    try:
        history = ha_request(path, timeout=45)
    except Exception as exc:
        LOG.info("Live-PV-History konnte nicht vorgeladen werden: %s", exc)
        return
    if not history or not isinstance(history, list) or not history[0]:
        return
    buckets: dict[str, list[float]] = {}
    for row in history[0]:
        try:
            stamp_raw = row.get("last_updated") or row.get("last_changed")
            stamp = datetime.fromisoformat(str(stamp_raw).replace("Z", "+00:00")).astimezone(local_tz())
            if stamp.date() != current.date():
                continue
            power = float(str(row.get("state", 0)).replace(",", "."))
            minute5 = (stamp.minute // 5) * 5
            key = stamp.replace(minute=minute5, second=0, microsecond=0).isoformat()
            buckets.setdefault(key, []).append(power)
        except Exception:
            continue
    if not buckets:
        return
    samples = [
        {"time": key, "power_w": round(sum(vals) / len(vals), 1), "day_kwh": None}
        for key, vals in sorted(buckets.items())
        if vals
    ]
    with state_store.lock:
        state_store.data["live_pv_samples"] = samples
        state_store.save()


def live_pv_analysis(
    forecast: dict[str, Any] | None = None,
    hourly_rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Laufende PV-Tageskorrektur – vollständig lokal, ohne Gemini.

    Die gespeicherte Tagesprognose wird über das prognostizierte Stundenprofil auf
    den bisherigen Tag verteilt. Erst wenn genügend prognostizierte Energie
    vergangen ist, wird der Resttag vorsichtig anhand Ist/Soll nachgeführt.
    """
    current = now or now_local()
    if forecast is None:
        forecast = state_store.data.get("forecast", {}).get(current.date().isoformat(), {})
    if not isinstance(forecast, dict) or not forecast:
        return {}
    rows = hourly_rows if hourly_rows is not None else forecast.get("hourly", [])
    if not isinstance(rows, list):
        rows = []
    expected_total = float(forecast.get("calibrated", {}).get("expected_kwh", 0) or 0)
    actual_so_far = max(0.0, float(state_value(ENTITIES["pv_day"], 0.0) or 0.0))
    total_rad = sum(max(0.0, float(r.get("radiation_wm2", 0) or 0)) for r in rows)
    expected_hour: dict[int, float] = {}
    if total_rad > 0 and expected_total > 0:
        for r in rows:
            try:
                hour = int(str(r.get("time"))[11:13])
                expected_hour[hour] = expected_total * max(0.0, float(r.get("radiation_wm2", 0) or 0)) / total_rad
            except Exception:
                continue
    expected_so_far = 0.0
    for hour, value in expected_hour.items():
        if hour < current.hour:
            expected_so_far += value
        elif hour == current.hour:
            expected_so_far += value * max(0.0, min(1.0, current.minute / 60.0))
    original_remaining = max(0.0, expected_total - expected_so_far)
    enough_data = expected_so_far >= max(0.45, expected_total * 0.06)
    correction = 1.0
    ratio = None
    if enough_data and expected_so_far > 0.05:
        ratio = actual_so_far / expected_so_far
        clipped = max(0.45, min(1.55, ratio))
        progress = min(1.0, expected_so_far / max(1.0, expected_total * 0.35))
        strength = 0.30 + 0.40 * progress
        correction = 1.0 + (clipped - 1.0) * strength
    adjusted_remaining = max(0.0, original_remaining * correction)
    adjusted_total = max(actual_so_far, actual_so_far + adjusted_remaining)
    # Keine extreme Tageskorrektur durch einzelne Wolken-/Sensorpunkte.
    if expected_total > 0:
        adjusted_total = max(actual_so_far, min(expected_total * 1.50, max(expected_total * 0.50, adjusted_total)))
        adjusted_remaining = max(0.0, adjusted_total - actual_so_far)
    delta = actual_so_far - expected_so_far
    delta_pct = (delta / expected_so_far * 100.0) if expected_so_far >= 0.2 else None
    if not enough_data:
        status = "noch zu früh für Tageskorrektur"
        tone = "neutral"
    elif delta_pct is not None and delta_pct <= -15:
        status = "hinter Prognose"
        tone = "low"
    elif delta_pct is not None and delta_pct >= 15:
        status = "vor Prognose"
        tone = "high"
    else:
        status = "im Plan"
        tone = "good"

    # Gemischtes Profil: vergangene Stunden = echte gemittelte PV-Leistung,
    # Zukunft = aus der Tagesprognose abgeleitete mittlere Stundenleistung.
    samples = state_store.data.get("live_pv_samples", [])
    actual_by_hour: dict[int, list[float]] = {}
    today_ds = current.date().isoformat()
    for item in samples if isinstance(samples, list) else []:
        try:
            stamp = datetime.fromisoformat(str(item.get("time")))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=local_tz())
            stamp = stamp.astimezone(local_tz())
            if stamp.date().isoformat() != today_ds:
                continue
            actual_by_hour.setdefault(stamp.hour, []).append(float(item.get("power_w") or 0) / 1000.0)
        except Exception:
            continue
    graph: list[dict[str, Any]] = []
    for hour in range(6, 22):
        if hour < current.hour and actual_by_hour.get(hour):
            vals = actual_by_hour[hour]
            graph.append({"hour": hour, "kw": round(sum(vals) / len(vals), 2), "kind": "actual"})
        elif hour == current.hour:
            current_power = float(state_value(ENTITIES["pv_power"], 0.0) or 0.0) / 1000.0
            graph.append({"hour": hour, "kw": round(current_power, 2), "kind": "actual"})
        else:
            graph.append({"hour": hour, "kw": round(max(0.0, expected_hour.get(hour, 0.0) * correction), 2), "kind": "forecast"})
    return {
        "actual_kwh": round(actual_so_far, 2),
        "original_expected_kwh": round(expected_total, 1),
        "expected_so_far_kwh": round(expected_so_far, 2),
        "delta_kwh": round(delta, 2),
        "delta_percent": round(delta_pct, 1) if delta_pct is not None else None,
        "adjusted_expected_kwh": round(adjusted_total, 1),
        "remaining_adjusted_kwh": round(adjusted_remaining, 1),
        "correction_factor": round(correction, 3),
        "status": status,
        "tone": tone,
        "enough_data": enough_data,
        "graph": graph,
    }


def estimate_pv_budget(
    forecast: dict[str, Any],
    hourly_rows: list[dict[str, Any]],
    battery_target_soc: float,
    warmwater_mode: str,
    now: datetime | None = None,
    battery_soc_override: float | None = None,
) -> dict[str, Any]:
    """Konservatives Rest-PV-Budget für die Wallbox.

    Priorität: Rest-PV -> Haus bis PV-Ende -> Speicher bis 100 % ->
    ggf. Warmwasser -> Sicherheitsreserve -> Auto. Damit erhält das Auto nur
    dann ein Tagesbudget, wenn die aktuelle Restprognose den Hausspeicher
    voraussichtlich trotzdem noch vollständig füllen kann. Die separat
    gelernte Abendreserve bleibt für das Netzrisiko/Abendziel erhalten.
    """
    current = now or now_local()
    s = settings_store.data
    expected = float(forecast.get("calibrated", {}).get("expected_kwh", 0) or 0)
    ds = str(forecast.get("weather", {}).get("date") or "")
    total_rad = sum(float(r.get("radiation_wm2", 0) or 0) for r in hourly_rows)
    if ds == current.date().isoformat():
        remaining_rows = [r for r in hourly_rows if int(str(r.get("time", "00:00"))[11:13]) >= current.hour]
    else:
        remaining_rows = list(hourly_rows)
    remaining_rad = sum(float(r.get("radiation_wm2", 0) or 0) for r in remaining_rows)
    remaining_pv = expected * (remaining_rad / total_rad) if total_rad > 0 else expected
    live_adjustment: dict[str, Any] = {}
    if ds == current.date().isoformat():
        live_adjustment = live_pv_analysis(forecast, hourly_rows, current)
        if live_adjustment:
            remaining_pv = float(live_adjustment.get("remaining_adjusted_kwh", remaining_pv) or 0)

    # PV-Ende aus dem letzten Stundenpunkt mit nennenswerter Einstrahlung.
    # Der Hausverbrauch wird nicht mehr nur anhand der Anzahl verbleibender
    # Solarstunden geschätzt, sondern über die reale Restzeit bis PV-Ende.
    active_times: list[datetime] = []
    for row in hourly_rows:
        if float(row.get("radiation_wm2", 0) or 0) < 50:
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get("time")))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=local_tz())
            else:
                stamp = stamp.astimezone(local_tz())
            active_times.append(stamp)
        except Exception:
            continue
    pv_start = min(active_times) if active_times else None
    pv_end = max(active_times) if active_times else None
    house_base_kw = max(0.0, float(s.get("day_house_base_kw", 0.85)))
    if pv_end is None:
        house_hours = 0.0
    elif ds == current.date().isoformat():
        house_hours = max(0.0, (pv_end - current).total_seconds() / 3600.0)
    elif pv_start is not None:
        house_hours = max(0.0, (pv_end - pv_start).total_seconds() / 3600.0)
    else:
        house_hours = 0.0
    house_reserve = house_hours * house_base_kw

    # Zielenergie im Speicher für die Zeit ab PV-Ende bis 00:00. Der gelernte
    # Abendbedarf bleibt maßgeblich; solange er niedriger ist, schützt eine
    # aus Grundlast + Sicherheitsaufschlag berechnete Mindestreserve.
    evening = state_store.data.get("evening_learning", {})
    learned_evening = float(evening.get("reserve_kwh") or s.get("evening_reserve_start_kwh", 2.5))
    evening_margin = max(0.0, float(s.get("evening_reserve_margin_kwh", 0.5)))
    if pv_end is not None:
        midnight = datetime.combine(pv_end.date() + timedelta(days=1), datetime.min.time(), tzinfo=local_tz())
        evening_hours = max(0.0, (midnight - pv_end).total_seconds() / 3600.0)
    else:
        evening_hours = 0.0
    calculated_evening = house_base_kw * evening_hours + evening_margin
    evening_target = min(BATTERY_CAPACITY_KWH, max(learned_evening, calculated_evening))

    battery_soc = state_value(ENTITIES["battery_soc"])
    # Für eine Zukunfts-Tagesplanung kann ein erwarteter Start-SOC vorgegeben werden.
    # So verwendet der 20-Uhr-Push nicht den aktuell noch hohen Speicherstand als
    # vermeintliche morgendliche Ausgangslage für das Auto-PV-Budget.
    if battery_soc_override is not None:
        effective_battery_soc = float(battery_soc_override)
    elif ds == current.date().isoformat() and current.hour < 5:
        effective_battery_soc = max(float(battery_soc or 0), float(battery_target_soc))
    else:
        effective_battery_soc = float(battery_soc or 0)
    battery_energy = BATTERY_CAPACITY_KWH * effective_battery_soc / 100.0
    # Für die Fahrzeugfreigabe wird ab 0.1.58 bewusst bis 100 % Speicher-SOC
    # reserviert. Ein kurzer realer Export reicht damit nicht mehr, wenn die
    # Rest-PV des Tages voraussichtlich nicht einmal den Hausspeicher füllt.
    battery_full_need = max(0.0, BATTERY_CAPACITY_KWH - battery_energy)
    battery_evening_need = max(0.0, evening_target - battery_energy)

    ww_need = float(s.get("warmwater_estimated_kwh", 1.8)) if warmwater_mode == "pv" else 0.0
    safety = float(s.get("pv_budget_safety_kwh", 0.8))
    car_margin_before_safety = remaining_pv - house_reserve - battery_full_need - ww_need
    available = max(0.0, car_margin_before_safety - safety)
    evening_margin_before_safety = remaining_pv - house_reserve - battery_evening_need - ww_need
    protected_soc = min(100.0, evening_target / BATTERY_CAPACITY_KWH * 100.0)
    if evening_margin_before_safety >= safety:
        evening_grid_risk = "gering"
    elif evening_margin_before_safety >= 0:
        evening_grid_risk = "mittel"
    else:
        evening_grid_risk = "erhöht"
    return {
        "remaining_pv_kwh": round(remaining_pv, 1),
        "house_reserve_kwh": round(house_reserve, 1),
        "house_base_kw": round(house_base_kw, 2),
        "house_hours_remaining": round(house_hours, 2),
        "pv_end_time": pv_end.strftime("%H:%M") if pv_end else None,
        "battery_current_soc_percent": round(effective_battery_soc, 0),
        "battery_current_energy_kwh": round(battery_energy, 1),
        "battery_reserve_kwh": round(battery_full_need, 1),
        "battery_full_reserve_kwh": round(battery_full_need, 1),
        "battery_evening_need_kwh": round(battery_evening_need, 1),
        "battery_target_kwh": round(evening_target, 1),
        "battery_target_soc_percent": round(protected_soc, 0),
        "evening_reserve_kwh": round(evening_target, 1),
        "evening_learned_kwh": round(learned_evening, 1),
        "evening_calculated_kwh": round(calculated_evening, 1),
        "evening_protected_soc_percent": round(protected_soc, 0),
        "evening_grid_risk": evening_grid_risk,
        "margin_before_safety_kwh": round(car_margin_before_safety, 1),
        "evening_margin_before_safety_kwh": round(evening_margin_before_safety, 1),
        "warmwater_reserve_kwh": round(ww_need, 1),
        "safety_kwh": round(safety, 1),
        "available_car_kwh": round(available, 1),
        "live_adjusted": bool(live_adjustment.get("enough_data")),
        "live_adjusted_expected_kwh": live_adjustment.get("adjusted_expected_kwh"),
        "live_status": live_adjustment.get("status"),
    }


def build_plan(forecasts: dict[str, Any], hourly_by_day: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not forecasts:
        return {}
    now = now_local()
    sorted_days = sorted(forecasts.keys())

    # Nachtplanung: bis 04:59 für heute, danach für morgen.
    primary_ds = planning_start_date(now).isoformat()
    if primary_ds not in forecasts:
        primary_ds = sorted_days[0]
    primary_index = sorted_days.index(primary_ds) if primary_ds in sorted_days else 0
    secondary_ds = sorted_days[min(primary_index + 1, len(sorted_days) - 1)]
    tertiary_ds = sorted_days[min(primary_index + 2, len(sorted_days) - 1)]
    primary = forecasts[primary_ds]
    secondary = forecasts[secondary_ds]
    primary_plan = float(primary.get("calibrated", {}).get("plan_kwh", 0) or 0)
    secondary_plan = float(secondary.get("calibrated", {}).get("plan_kwh", 0) or 0)
    primary_expected = float(primary.get("calibrated", {}).get("expected_kwh", 0) or 0)
    secondary_expected = float(secondary.get("calibrated", {}).get("expected_kwh", 0) or 0)

    id7 = state_value(ENTITIES["id7_soc"])
    egolf = state_value(ENTITIES["egolf_soc"])
    s = settings_store.data
    car_rec = combined_car_recommendation(id7, egolf, primary_plan, secondary_plan)
    present = car_at_wallbox()
    night_target = current_night_target()
    night_decision = night_wallbox_decision()
    fast_recommended = present and night_decision.get("action") == "fast"

    primary_hourly = hourly_by_day.get(primary_ds, [])
    battery_target_info = battery_target_details(primary_expected, primary_hourly, primary)
    battery_target = int(battery_target_info["target_soc"])
    battery_soc = state_value(ENTITIES["battery_soc"])
    schedule = battery_schedule(battery_soc, battery_target)

    # Warmwasser für die kommende/aktuelle Nacht richtet sich nach dem
    # Nacht-Planungstag. Bei ausreichender PV wird es für diesen Tag ins beste
    # Tagesfenster gelegt.
    ww_threshold = float(s.get("warmwater_night_threshold_kwh", 20.0))
    duration_minutes = max(30, min(300, int(s.get("warmwater_duration_minutes", 120))))
    if primary_plan < ww_threshold:
        ww_start = "00:00"
        ww_end_minute = min(300, duration_minutes)
        ww_end = f"{ww_end_minute // 60:02d}:{ww_end_minute % 60:02d}"
        ww_mode = "night"
    else:
        ww_start, ww_end = best_warmwater_window(primary_hourly)
        ww_mode = "pv"

    # Verschiebbarer Verbraucher: keine direkte Steuerung, nur klare Empfehlung.
    # Bei schwachem Folgetag wird die Spülmaschine ins günstige 00–05-Uhr-Fenster
    # gelegt; bei ausreichend PV bewusst auf den Folgetag verschoben.
    primary_dw_window = best_pv_charge_window(primary_hourly, 3)
    if primary_expected < 25.0 or battery_target >= 65:
        dishwasher = {
            "mode": "night",
            "label": "in der Nacht",
            "time": "00:00–03:00",
            "reason": f"{primary_expected:.1f} kWh erwartet bzw. hohe Speicherreserve nötig.",
        }
    else:
        dishwasher = {
            "mode": "pv",
            "label": "im PV-Fenster",
            "time": f"{primary_dw_window.get('start_time', '–')}–{primary_dw_window.get('end_time', '–')}",
            "reason": f"{primary_expected:.1f} kWh erwartet; Netz-Nachtstrom kann vermieden werden.",
        }

    # Tages-PV/Wallbox-Steuerung muss IMMER mit dem heutigen Forecast arbeiten,
    # nicht mit dem morgigen Nacht-Planungstag.
    today_ds = now.date().isoformat()
    pv_ds = today_ds if today_ds in forecasts else primary_ds
    pv_forecast = forecasts[pv_ds]
    pv_hourly = hourly_by_day.get(pv_ds, [])
    pv_expected = float(pv_forecast.get("calibrated", {}).get("expected_kwh", 0) or 0)
    pv_plan = float(pv_forecast.get("calibrated", {}).get("plan_kwh", 0) or 0)
    pv_window = best_pv_charge_window(pv_hourly, 4)

    # Ab 05:00 ist Nacht-vs.-Tag für HEUTE durch die 20-Uhr-Planung fest.
    # Der Morgenlauf darf nur ein bereits als PV geplantes Tagesfenster zeitlich
    # verfeinern, niemals rückwirkend eine Nachtaktion erzeugen.
    locked_today = _daily_action_plan(today_ds)
    locked_ww = locked_today.get("warmwater", {}) if isinstance(locked_today.get("warmwater"), dict) else {}
    locked_dw = locked_today.get("dishwasher", {}) if isinstance(locked_today.get("dishwasher"), dict) else {}

    today_ww_start, today_ww_end = best_warmwater_window(pv_hourly)
    locked_ww_mode = str(locked_ww.get("mode") or "")
    ww_ended_night = _warmwater_ended_in_night(today_ds)
    if locked_ww_mode == "night":
        today_ww = {
            "date": pv_ds,
            "mode": "done" if ww_ended_night else "night_past",
            "start_time": None,
            "end_time": None,
            "label": "in der vergangenen Nacht erledigt" if ww_ended_night else "Nachtfenster vorbei · nicht nachholen",
        }
    else:
        today_ww = {
            "date": pv_ds,
            "mode": "pv",
            "start_time": today_ww_start,
            "end_time": today_ww_end,
            "label": "heutiges bestes PV-Fenster",
        }

    budget_ww_mode = "night" if locked_ww_mode == "night" else "pv"
    budget = estimate_pv_budget(pv_forecast, pv_hourly, battery_target, budget_ww_mode, now=now)

    primary_budget_clock = datetime.fromisoformat(primary_ds + "T05:00:00").replace(tzinfo=local_tz())
    primary_budget = estimate_pv_budget(
        primary, primary_hourly, battery_target, ww_mode,
        now=primary_budget_clock, battery_soc_override=float(battery_target),
    )
    primary_pv_window = best_pv_charge_window(primary_hourly, 4)

    # Auch die Spülmaschinen-Grundentscheidung wird vom Vorabend übernommen.
    today_dw_window = best_pv_charge_window(pv_hourly, 3)
    locked_dw_mode = str(locked_dw.get("mode") or "")
    if locked_dw_mode == "night":
        today_dishwasher = {
            "mode": "night_past",
            "label": "für die vergangene Nacht eingeplant",
            "time": str(locked_dw.get("time") or "00:00–03:00"),
        }
    else:
        # Bei PV-Planung darf der 07-Uhr-Lauf die konkrete Tageszeit nachführen.
        # Für Altbestand ohne Snapshot gilt nach 05:00 ebenfalls ausschließlich Tag.
        today_dishwasher = {
            "mode": "pv",
            "label": "im PV-Fenster",
            "time": f"{today_dw_window.get('start_time', '–')}–{today_dw_window.get('end_time', '–')}",
        }

    available_car = float(budget.get("available_car_kwh", 0) or 0)
    if not present:
        pv_level, pv_label = "none", "Kein Auto an der Wallbox"
        pv_reason = "Automatisches PV-Laden bleibt gesperrt, bis Auto = Ja gewählt ist."
    elif available_car < float(s.get("car_budget_min_kwh", 1.5)):
        pv_level, pv_label = "low", "Haus und Speicher haben Vorrang"
        pv_reason = f"Nach Abendreserve, Haus und Warmwasser bleiben nur etwa {available_car:.1f} kWh fürs Auto."
    elif available_car >= 12:
        pv_level, pv_label = "high", "Viel PV fürs Auto verfügbar"
        pv_reason = f"Voraussichtlich rund {available_car:.1f} kWh echtes PV-Budget fürs Auto."
    elif available_car >= 6:
        pv_level, pv_label = "good", "PV-Laden gut möglich"
        pv_reason = f"Voraussichtlich rund {available_car:.1f} kWh nach Haus- und Speicherreserve verfügbar."
    else:
        pv_level, pv_label = "limited", "PV-Laden begrenzt"
        pv_reason = f"Nur rund {available_car:.1f} kWh sind nach den wichtigeren Hauslasten frei."

    next_available_car = float(primary_budget.get("available_car_kwh", 0) or 0)
    if not present:
        next_pv_level, next_pv_label = "none", "Kein Auto an der Wallbox"
        next_pv_reason = "Morgen wird erst geladen, wenn ein Auto an der Wallbox ist."
    elif next_available_car < float(s.get("car_budget_min_kwh", 1.5)):
        next_pv_level, next_pv_label = "low", "Morgen kaum PV fürs Auto"
        next_pv_reason = f"Nach Haus, Speicher, Warmwasser und Reserve bleiben rund {next_available_car:.1f} kWh fürs Auto."
    elif next_available_car >= 12:
        next_pv_level, next_pv_label = "high", "Morgen viel PV fürs Auto"
        next_pv_reason = f"Voraussichtlich rund {next_available_car:.1f} kWh echtes PV-Budget fürs Auto."
    elif next_available_car >= 6:
        next_pv_level, next_pv_label = "good", "Morgen PV-Laden gut möglich"
        next_pv_reason = f"Voraussichtlich rund {next_available_car:.1f} kWh nach Haus- und Speicherreserve verfügbar."
    else:
        next_pv_level, next_pv_label = "limited", "Morgen PV-Laden begrenzt"
        next_pv_reason = f"Rund {next_available_car:.1f} kWh sind nach den wichtigeren Hauslasten frei."

    label1, label2 = planning_labels(now)
    return {
        "primary_date": primary_ds,
        "secondary_date": secondary_ds,
        "tertiary_date": tertiary_ds,
        "primary_label": label1,
        "secondary_label": label2,
        "planning_day_is_today": primary_ds == now.date().isoformat(),
        "tomorrow_date": primary_ds,
        "day_after_date": secondary_ds,
        "tomorrow_expected_kwh": primary_expected,
        "tomorrow_plan_kwh": primary_plan,
        "day_after_expected_kwh": secondary_expected,
        "day_after_plan_kwh": secondary_plan,
        "id7": {
            "soc": id7,
            "normal_target_soc": int(s.get("id7_target_soc", 80)),
            "min_morning_soc": int(s.get("id7_min_morning_soc", 40)),
        },
        "egolf": {
            "soc": egolf,
            "normal_target_soc": int(s.get("egolf_target_soc", 80)),
            "min_morning_soc": int(s.get("egolf_min_morning_soc", 40)),
        },
        "wallbox": {
            "recommended": "none" if not present else ("fast" if fast_recommended else "pv_wait"),
            "label": "Kein Auto an der Wallbox" if not present else ("Schnellladen bis Mindest-SOC" if fast_recommended else ("Nur PV" if state_store.data.get("night_override") == "pv_wait" else "Mindest-SOC erreicht")),
            "reason": night_decision.get("reason", ""),
            "car_present": present,
            "night_mode": state_store.data.get("night_override", "auto"),
            "connected_vehicle": night_decision.get("label"),
            "connected_soc": night_decision.get("soc"),
            "night_target_soc": night_target,
            "night_target_is_override": state_store.data.get("night_target_override_soc") is not None,
            "session": state_store.data.get("wallbox_session", {}),
        },
        "pv_charging": {
            "date": pv_ds,
            "day_label": relative_day_label(pv_ds, now),
            "level": pv_level,
            "label": pv_label,
            "reason": pv_reason,
            "car_present": present,
            "expected_kwh": round(pv_expected, 1),
            "plan_kwh": round(pv_plan, 1),
            "budget": budget,
            **pv_window,
        },
        "next_pv_charging": {
            "date": primary_ds,
            "day_label": label1,
            "level": next_pv_level,
            "label": next_pv_label,
            "reason": next_pv_reason,
            "car_present": present,
            "expected_kwh": round(primary_expected, 1),
            "plan_kwh": round(primary_plan, 1),
            "budget": primary_budget,
            **primary_pv_window,
        },
        "battery": {
            "soc": battery_soc,
            "target_soc": battery_target,
            "automatic_target_soc": battery_target_info.get("automatic_target_soc"),
            "manual_offset_soc": battery_target_info.get("manual_offset_soc"),
            "minimum_reserve_soc": battery_target_info.get("minimum_reserve_soc"),
            "profile_target_soc": battery_target_info.get("profile_target_soc"),
            "morning_bridge_target_soc": battery_target_info.get("morning_bridge_target_soc"),
            "learned_morning_need_kwh": battery_target_info.get("learned_morning_need_kwh"),
            "predicted_morning_need_kwh": battery_target_info.get("predicted_morning_need_kwh"),
            "predicted_cover_time": battery_target_info.get("predicted_cover_time"),
            "adjusted_cover_time": battery_target_info.get("adjusted_cover_time"),
            "cover_time_offset_minutes": battery_target_info.get("cover_time_offset_minutes"),
            "morning_energy_buffer_soc": battery_target_info.get("morning_energy_buffer_soc"),
            "standby_restload_w": battery_target_info.get("standby_restload_w"),
            "morning_forecast_basis_kwh": battery_target_info.get("morning_forecast_basis_kwh"),
            "house_base_kw": battery_target_info.get("house_base_kw"),
            "day_basis_kwh": battery_target_info.get("day_basis_kwh"),
            "target_mode": battery_target_info.get("mode"),
            "target_basis_kwh": round(primary_expected, 1),
            "start_time": schedule["start_time"],
            "end_time": "05:00",
            "charge_power_kw": BATTERY_SAFE_CHARGE_KW,
            "effective_charge_kw": schedule["effective_charge_kw"],
            "start_buffer_minutes": schedule.get("start_buffer_minutes", 10),
            "needed_minutes": schedule["needed_minutes"],
            "needed_kwh": schedule["needed_kwh"],
            "reachable": schedule["reachable"],
        },
        "warmwater": {
            "date": primary_ds,
            "mode": ww_mode,
            "start_time": ww_start,
            "end_time": ww_end,
            "label": "günstig nachts" if ww_mode == "night" else "im besten PV-Fenster",
            "temperature": parse_number_from_state(ENTITIES["warmwater_temp"]),
        },
        "today_warmwater": today_ww,
        "dishwasher": dishwasher,
        "today_dishwasher": today_dishwasher,
    }


def rebuild_plan_from_saved_forecast() -> dict[str, Any]:
    forecasts = state_store.data.get("forecast", {})
    if not isinstance(forecasts, dict):
        forecasts = {}
    hourly_by_day = {
        ds: value.get("hourly", [])
        for ds, value in forecasts.items()
        if isinstance(value, dict)
    }
    plan = build_plan(forecasts, hourly_by_day)
    with state_store.lock:
        state_store.data["plan"] = plan
        _remember_battery_plan(plan)
        state_store.save()
    return plan

def forecast_run(reason: str = "manual", notify: bool = False) -> dict[str, Any]:
    """Vollständige Prognose mit optional genau einem Gemini-Aufruf (+ 1 Retry).

    Die Funktion respektiert Cooldown und Tageslimit. Ist Gemini gesperrt oder
    vorübergehend nicht erreichbar, bleibt eine vorhandene Prognose erhalten und
    wird nur mit den aktuellen kostenlosen Wetterdaten nachgeführt.
    """
    LOG.info("Forecast gestartet: %s", reason)
    options = load_options()
    api_key = str(options.get("gemini_api_key") or "").strip()
    daily_metrics, hourly_by_day = open_meteo_forecast()

    if api_key:
        allowed, gate_reason = gemini_gate(reason)
        if not allowed:
            LOG.info("Gemini übersprungen: %s", gate_reason)
            result = refresh_weather_only(reason=f"{reason}: {gate_reason}", notify=notify, supplied=(daily_metrics, hourly_by_day))
            with state_store.lock:
                state_store.data["last_error"] = None
                state_store.save()
            result["gemini_skipped"] = gate_reason
            return result
        gemini_mark_attempt()

    last_exc: Exception | None = None
    raw_predictions: list[dict[str, Any]] | None = None
    source = "fallback"
    max_attempts = 2 if api_key else 1
    for attempt in range(1, max_attempts + 1):
        try:
            standby = state_store.data.get("standby_learning", {})
            standby_estimate = standby.get("estimate_w") if isinstance(standby, dict) else None
            raw_predictions, source = gemini_forecast(api_key, daily_metrics, hourly_by_day, standby_estimate)
            if api_key and source != "fallback":
                gemini_mark_success(source)
            with state_store.lock:
                state_store.data["last_error"] = None
            break
        except Exception as exc:
            last_exc = exc
            LOG.warning("Gemini-Prognose Versuch %s/%s fehlgeschlagen: %s", attempt, max_attempts, exc)
            # Bei einem veralteten/entfernten Modell beim einzigen Retry die
            # Modellliste neu ermitteln; keine zusätzlichen Generate-Aufrufe.
            if "404" in str(exc):
                with state_store.lock:
                    state_store.data.setdefault("gemini_control", {})["cached_model"] = None
                    state_store.save()
            if attempt < max_attempts:
                time.sleep(4)

    if raw_predictions is None:
        LOG.error("Gemini fehlgeschlagen; gespeicherte Prognose/Wetter-Fallback wird verwendet")
        result = refresh_weather_only(reason=f"{reason}: Gemini-Fehler", notify=notify, supplied=(daily_metrics, hourly_by_day))
        with state_store.lock:
            state_store.data["last_error"] = f"Gemini: {last_exc}"
            state_store.save()
        return result

    raw_by_date = {str(x.get("date")): x for x in raw_predictions}
    forecasts: dict[str, Any] = {}
    for metrics in daily_metrics:
        ds = metrics["date"]
        raw = raw_by_date.get(ds) or dict({"date": ds}, **physics_fallback(metrics))
        calibration = calibration_for_ghi(float(metrics.get("ghi_kwh_m2") or 0))
        calibrated = plan_value(raw, calibration)
        forecasts[ds] = {
            "weather": metrics,
            "hourly": hourly_by_day.get(ds, []),
            "raw": raw,
            "calibration": calibration,
            "calibrated": calibrated,
        }

    current_now = now_local()
    if current_now.hour < 5:
        today_ds = current_now.date().isoformat()
        preserved = state_store.data.get("forecast", {}).get(today_ds)
        if not preserved:
            preserved = state_store.data.get("forecast_archive", {}).get(today_ds)
        if preserved:
            forecasts[today_ds] = preserved

    previous_plan = state_store.data.get("plan", {})
    plan = build_plan(forecasts, {ds: v.get("hourly", []) for ds, v in forecasts.items()})
    stamp = now_local().isoformat()
    with state_store.lock:
        state_store.data["forecast"] = forecasts
        state_store.data["plan"] = plan
        _remember_battery_plan(plan)
        _remember_daily_action_plan(plan, reason)
        state_store.data["last_forecast_run"] = stamp
        state_store.data["last_weather_refresh"] = stamp
        state_store.data["last_forecast_source"] = source
        state_store.data["version"] = VERSION
        state_store.save()
    if notify:
        send_plan_notification(reason, previous_plan, plan, forecasts)
    return {"forecast": forecasts, "plan": plan, "source": source}

def _round1(value: Any) -> float | None:
    try:
        return round(float(value), 1)
    except Exception:
        return None


def _overnight_charge_summary() -> dict[str, Any] | None:
    """Ermittelt rückblickend ein tatsächlich nachts geladenes Fahrzeug per SOC-Anstieg."""
    session = state_store.data.get("wallbox_session", {})
    if not isinstance(session, dict):
        return None
    started = session.get("started_at")
    ended = session.get("ended_at")
    if not started or not ended:
        return None
    try:
        started_dt = datetime.fromisoformat(str(started)).astimezone(local_tz())
        ended_dt = datetime.fromisoformat(str(ended)).astimezone(local_tz())
    except Exception:
        return None
    today = now_local().date()
    if ended_dt.date() != today or started_dt.date() != today:
        return None
    current = {
        "id7": state_value(ENTITIES["id7_soc"]),
        "egolf": state_value(ENTITIES["egolf_soc"]),
    }
    baseline = {
        "id7": session.get("baseline_id7"),
        "egolf": session.get("baseline_egolf"),
    }
    active = session.get("active_vehicle")
    candidates: list[tuple[str, float]] = []
    for key in ("id7", "egolf"):
        try:
            delta = float(current[key]) - float(baseline[key])
        except Exception:
            continue
        if delta >= 1.0:
            candidates.append((key, delta))
    if active not in {"id7", "egolf"} and candidates:
        active = max(candidates, key=lambda item: item[1])[0]
    if active not in {"id7", "egolf"}:
        return None
    try:
        start_soc = float(baseline[active])
        end_soc = float(current[active])
    except Exception:
        return None
    if end_soc - start_soc < 1.0:
        return None
    return {
        "vehicle": active,
        "label": "ID.7" if active == "id7" else "eGolf",
        "start_soc": round(start_soc),
        "end_soc": round(end_soc),
        "target_soc": int(session.get("target_soc") or current_night_target()),
    }


def _start_hhmm(value: Any) -> str:
    text = str(value or "–").strip()
    first = text.split("–", 1)[0].strip()
    return first if re.match(r"^\d{1,2}:\d{2}$", first) else "–"


def _notification_context(plan: dict[str, Any], forecasts: dict[str, Any], reason: str) -> dict[str, Any]:
    """Datenbasis für den 20:00-Plan und den 07:00-Änderungspush."""
    now = now_local()
    morning = reason == "morning"
    today_ds = now.date().isoformat()
    tomorrow_ds = (now.date() + timedelta(days=1)).isoformat()

    if morning:
        primary_ds, secondary_ds = today_ds, tomorrow_ds
        primary_label, secondary_label = "Heute", "Morgen"
        pvc = plan.get("pv_charging", {})
        dw = plan.get("today_dishwasher", {})
        ww = plan.get("today_warmwater", {})
    else:
        primary_ds = str(plan.get("primary_date") or plan.get("tomorrow_date") or tomorrow_ds)
        secondary_ds = str(plan.get("secondary_date") or plan.get("day_after_date") or "")
        primary_label = str(plan.get("primary_label") or "Morgen")
        secondary_label = str(plan.get("secondary_label") or "Übermorgen")
        pvc = plan.get("next_pv_charging", {}) or plan.get("pv_charging", {})
        dw = plan.get("dishwasher", {})
        ww = plan.get("warmwater", {})

    primary_forecast = forecasts.get(primary_ds, {}).get("calibrated", {})
    secondary_forecast = forecasts.get(secondary_ds, {}).get("calibrated", {}) if secondary_ds else {}
    battery = plan.get("battery", {})
    wallbox = plan.get("wallbox", {})
    id7_soc = state_value(ENTITIES["id7_soc"])
    egolf_soc = state_value(ENTITIES["egolf_soc"])
    battery_soc = state_value(ENTITIES["battery_soc"])
    target = int(wallbox.get("night_target_soc") or current_night_target())
    override = str(state_store.data.get("night_override", "auto") or "auto")

    fast_needed = bool(
        wallbox.get("car_present")
        and override != "pv_wait"
        and (
            override == "fast"
            or wallbox.get("recommended") == "fast"
            or (wallbox.get("connected_soc") is not None and float(wallbox.get("connected_soc")) < target)
        )
    )
    battery_charge_needed = battery.get("start_time") not in {None, "", "–", "nicht nötig"}
    budget = pvc.get("budget", {}) if isinstance(pvc, dict) else {}
    overnight = _overnight_charge_summary() if morning else None
    if morning:
        locked = _daily_action_plan(today_ds)
        if locked:
            previous_snapshot = {
                "dishwasher_mode": str((locked.get("dishwasher") or {}).get("mode") or ""),
                "warmwater_mode": str((locked.get("warmwater") or {}).get("mode") or ""),
            }
        else:
            previous_snapshot = state_store.data.get("last_notifications", {}).get("plan_snapshot", {})
    else:
        previous_snapshot = {}
    warmwater_session = state_store.data.get("warmwater_session", {}) if morning else {}
    warmwater_ended_today = False
    if isinstance(warmwater_session, dict) and warmwater_session.get("ended"):
        try:
            warmwater_ended_today = datetime.fromisoformat(str(warmwater_session.get("ended"))).astimezone(local_tz()).date() == now.date()
        except Exception:
            warmwater_ended_today = False
    warmwater_ended_night = _warmwater_ended_in_night(today_ds) if morning else False
    return {
        "primary_label": primary_label,
        "primary_kwh": _round1(primary_forecast.get("expected_kwh")),
        "secondary_label": secondary_label,
        "secondary_kwh": _round1(secondary_forecast.get("expected_kwh")),
        "battery_soc": _round1(battery_soc),
        "battery_night_soc": int(battery.get("target_soc") or 0) if battery.get("target_soc") is not None else None,
        "battery_charge_needed": battery_charge_needed,
        "id7_soc": _round1(id7_soc),
        "egolf_soc": _round1(egolf_soc),
        "egolf_connected": _cable_is_connected(
            state_text(ENTITIES.get("egolf_cable", "")) if ENTITIES.get("egolf_cable") else "unknown"
        ),
        "fast_needed": fast_needed,
        "fast_target": target,
        "car_present": bool(wallbox.get("car_present")),
        "surplus_kwh": _round1(budget.get("available_car_kwh")),
        "dishwasher_mode": str(dw.get("mode") or ""),
        "dishwasher_time": str(dw.get("time") or "–"),
        "warmwater_mode": str(ww.get("mode") or ""),
        "warmwater_start": str(ww.get("start_time") or "–"),
        "warmwater_end": str(ww.get("end_time") or "–"),
        "overnight_charge": overnight,
        "previous_dishwasher_mode": str(previous_snapshot.get("dishwasher_mode") or ""),
        "previous_warmwater_mode": str(previous_snapshot.get("warmwater_mode") or ""),
        "warmwater_ended_today": warmwater_ended_today,
        "warmwater_ended_night": warmwater_ended_night,
        "battery_automatic_soc": _round1(battery.get("automatic_target_soc")),
        "battery_manual_offset": _round1(battery.get("manual_offset_soc")),
    }


def notification_materially_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if not old:
        return True
    keys = (
        "primary_kwh", "secondary_kwh",
        "battery_charge_needed", "battery_night_soc",
        "id7_soc", "egolf_soc", "fast_needed", "fast_target", "car_present",
        "surplus_kwh",
        "dishwasher_mode", "dishwasher_time",
        "warmwater_mode", "warmwater_start", "warmwater_end",
        "overnight_charge", "warmwater_ended_today",
    )
    return any(old.get(k) != new.get(k) for k in keys)


def plan_message(plan: dict[str, Any], forecasts: dict[str, Any], reason: str = "main") -> str:
    ctx = _notification_context(plan, forecasts, reason)
    de1 = lambda v: "–" if v is None else f"{float(v):.1f}".replace(".", ",")
    p1 = de1(ctx["primary_kwh"])
    p2 = de1(ctx["secondary_kwh"])
    id7 = "–" if ctx["id7_soc"] is None else f'{ctx["id7_soc"]:.0f}'
    egolf = "–" if ctx["egolf_soc"] is None else f'{ctx["egolf_soc"]:.0f}'
    surplus_value = float(ctx.get("surplus_kwh") or 0.0)
    surplus = de1(surplus_value)

    lines = [f'☀️ {ctx["primary_label"]} {p1} kWh · {ctx["secondary_label"]} {p2} kWh']
    if reason == "main":
        target = "–" if ctx.get("battery_night_soc") is None else f'{ctx["battery_night_soc"]:.0f}'
        lines.append(f"🔋 05:00 Uhr {target} % · 🚗 ID.7 {id7} % · eGolf {egolf} % 🔌 PV ca. {surplus} kWh")
        if ctx.get("fast_needed"):
            lines.append(f'⚠️ Auto wird diese Nacht auf {int(ctx.get("fast_target") or current_night_target())} % geladen')
        if ctx.get("dishwasher_mode") == "night":
            lines.append("🍽️ Spülmaschine: heute Nacht")
        else:
            t = _start_hhmm(ctx.get("dishwasher_time"))
            lines.append(f"🍽️ Spülmaschine: morgen {t} Uhr")
        if ctx.get("warmwater_mode") == "night":
            lines.append("🚿 Warmwasser: heute Nacht")
        else:
            t = _start_hhmm(ctx.get("warmwater_start"))
            lines.append(f"🚿 Warmwasser: morgen {t} Uhr")
        return "\n".join(lines)

    overnight = ctx.get("overnight_charge") or {}
    if overnight:
        charge = f"🔌 {overnight.get('label')} {overnight.get('start_soc')}→{overnight.get('end_soc')} % nachts"
        lines.append(f"🚗 ID.7 {id7} % · eGolf {egolf} % · {charge}")
    elif surplus_value >= 5.0:
        lines.append(f"🚗 ID.7 {id7} % · eGolf {egolf} % 🔌 PV ca. {surplus} kWh")
    else:
        lines.append(f"🚗 ID.7 {id7} % · eGolf {egolf} %")

    if ctx.get("previous_dishwasher_mode") == "night":
        # Ohne eigene Spülmaschinen-Entität kann nur der Nachtplan bestätigt,
        # nicht ein tatsächlicher Programmlauf behauptet werden.
        lines.append("🍽️ Spülmaschine: wie gestern geplant für die vergangene Nacht eingeplant")
    elif ctx.get("dishwasher_mode") in {"night", "night_past"}:
        lines.append("🍽️ Spülmaschine: vergangene Nacht eingeplant")
    else:
        t = _start_hhmm(ctx.get("dishwasher_time"))
        lines.append(f"🍽️ Spülmaschine: heute {t} Uhr")

    if ctx.get("previous_warmwater_mode") == "night":
        if ctx.get("warmwater_ended_night"):
            lines.append("🚿 Warmwasser: wie gestern geplant in der Nacht erledigt")
        else:
            lines.append("🚿 Warmwasser: Nachtfenster war eingeplant · morgens keine rückwirkende Änderung")
    elif ctx.get("warmwater_ended_today") and ctx.get("warmwater_mode") == "done":
        lines.append("🚿 Warmwasser: heute bereits erledigt")
    else:
        t = _start_hhmm(ctx.get("warmwater_start"))
        lines.append(f"🚿 Warmwasser: heute {t} Uhr")
    return "\n".join(lines)


def _sun_words(kwh: Any) -> str:
    try:
        value = float(kwh)
    except Exception:
        return "Prognose offen"
    if value < 10:
        return "kaum Sonne"
    if value < 28:
        return "etwas Sonne"
    if value < 42:
        return "viel Sonne"
    return "sehr viel Sonne"


def _hour_only(value: str) -> str:
    text = str(value or "–")
    first = text.split("–", 1)[0].strip()
    if first in {"", "–"}:
        return "–"
    return f"{first} Uhr"


def partner_plan_message(plan: dict[str, Any], forecasts: dict[str, Any], reason: str = "main") -> str:
    """Kompakter, handlungsorientierter Energieplan für secondary."""
    ctx = _notification_context(plan, forecasts, reason)
    egolf_soc = ctx.get("egolf_soc")
    target = int(ctx.get("fast_target") or current_night_target())
    primary_sun = _sun_words(ctx.get("primary_kwh"))
    secondary_sun = _sun_words(ctx.get("secondary_kwh"))
    soc = None if egolf_soc is None else int(round(float(egolf_soc)))

    if reason == "main":
        lines = [f'☀️ {ctx["primary_label"]} {primary_sun}', f'☀️ {ctx["secondary_label"]} {secondary_sun}']
    else:
        lines = [f'☀️ {ctx["primary_label"]} {primary_sun} · {ctx["secondary_label"]} {secondary_sun}']
    lines.append("🚗 eGolf: Ladezustand unbekannt" if soc is None else f"🚗 eGolf {soc} %")

    if reason == "main":
        if soc is not None and soc < 20:
            lines.append("⚠️ eGolf-Akku unter 20 %")
        if ctx.get("fast_needed"):
            lines.append(f"🔌 ID.7 oder eGolf wird diese Nacht auf {target} % geladen")
        if ctx.get("dishwasher_mode") == "night":
            lines.append("🍽️ Spülmaschine: heute Nacht")
        else:
            lines.append(f"🍽️ Spülmaschine: morgen {_start_hhmm(ctx.get('dishwasher_time'))} Uhr")
        if ctx.get("warmwater_mode") == "night":
            lines.append("🚿 Warmwasser: heute Nacht")
        else:
            lines.append(f"🚿 Warmwasser: morgen {_start_hhmm(ctx.get('warmwater_start'))} Uhr")
        return "\n".join(lines)

    overnight = ctx.get("overnight_charge") or {}
    if overnight.get("vehicle") == "egolf":
        lines[-1] += f" · 🔌 {overnight.get('start_soc')}→{overnight.get('end_soc')} % nachts"
    if ctx.get("previous_dishwasher_mode") == "night":
        lines.append("🍽️ Spülmaschine: wie gestern geplant für die vergangene Nacht eingeplant")
    elif ctx.get("dishwasher_mode") in {"night", "night_past"}:
        lines.append("🍽️ Spülmaschine: vergangene Nacht eingeplant")
    else:
        lines.append(f"🍽️ Spülmaschine: heute {_start_hhmm(ctx.get('dishwasher_time'))} Uhr")
    if ctx.get("previous_warmwater_mode") == "night":
        if ctx.get("warmwater_ended_night"):
            lines.append("🚿 Warmwasser: wie gestern geplant in der Nacht erledigt")
        else:
            lines.append("🚿 Warmwasser: Nachtfenster war eingeplant · morgens keine rückwirkende Änderung")
    elif ctx.get("warmwater_ended_today") and ctx.get("warmwater_mode") == "done":
        lines.append("🚿 Warmwasser: heute bereits erledigt")
    else:
        lines.append(f"🚿 Warmwasser: heute {_start_hhmm(ctx.get('warmwater_start'))} Uhr")
    return "\n".join(lines)

def partner_message_materially_changed(old_message: str | None, new_message: str) -> bool:
    return not old_message or str(old_message) != str(new_message)


def fmt_soc(value: Any) -> str:
    try:
        return f"{float(value):.0f}%"
    except Exception:
        return "?"


def send_plan_notification(reason: str, previous_plan: dict[str, Any], plan: dict[str, Any], forecasts: dict[str, Any]) -> None:
    now = now_local()
    today_key = now.date().isoformat()
    last = state_store.data.setdefault("last_notifications", {})
    current_snapshot = _notification_context(plan, forecasts, reason)

    main_should_send = True
    main_title = "Energieplan für morgen" if reason == "main" else "Energieplan · Morgen"
    if reason == "main" and last.get("main") == today_key:
        main_should_send = False
    if reason == "morning" and last.get("morning") == today_key:
        main_should_send = False

    main_sent = False
    if main_should_send:
        # primary bewusst als normale Mobile-App-Mitteilung senden. Der frühere
        # critical+volume=0-Payload kann auf einzelnen iPhones trotz akzeptiertem
        # HA-Serviceaufruf nicht zugestellt werden.
        main_sent = send_notification(main_title, plan_message(plan, forecasts, reason=reason), critical_silent=False)

    # Zweiter, bewusst vereinfachter Plan für secondary. Wie beim Hauptgerät
    # gibt es nun feste Pushes um 07:00 und 20:00, unabhängig von Änderungen.
    partner_sent = False
    partner_message = partner_plan_message(plan, forecasts, reason=reason)
    partner_enabled = bool(settings_store.data.get("partner_notifications_enabled", True))
    partner_service = str(settings_store.data.get("partner_notify_service", "notify.mobile_app_secondary_iphone") or "")
    partner_should_send = partner_enabled and bool(partner_service)
    if reason == "main" and last.get("partner_main") == today_key:
        partner_should_send = False
    if reason == "morning" and last.get("partner_morning") == today_key:
        partner_should_send = False
    if partner_should_send:
        partner_title = "Energieplan für morgen" if reason == "main" else "Energieplan · Morgen"
        partner_sent = send_notification(
            partner_title,
            partner_message,
            critical_silent=True,
            service_full=partner_service,
        )

    if main_sent or partner_sent:
        with state_store.lock:
            notices = state_store.data.setdefault("last_notifications", {})
            if main_sent:
                notices[reason] = today_key
            if reason == "main":
                # Für den Morgenlauf verbindlich, auch wenn nur secondary Push ankam.
                notices["plan_snapshot"] = current_snapshot
                notices["plan_snapshot_at"] = now.isoformat()
            if partner_sent:
                notices["partner_" + reason] = today_key
                notices["partner_plan_message"] = partner_message
                notices["partner_plan_message_at"] = now.isoformat()
            state_store.save()

def record_actual_today() -> None:
    today_ds = now_local().date().isoformat()
    actual = state_value(ENTITIES["pv_day"])
    if actual is None or actual < 0:
        return
    forecast = state_store.data.get("forecast", {}).get(today_ds)
    # Der aktuelle Forecast enthält normalerweise nur morgen/übermorgen. Suche deshalb ggf. im Archiv.
    archived = state_store.data.get("forecast_archive", {}).get(today_ds)
    source = forecast or archived
    if not source:
        return
    raw_expected = source.get("raw", {}).get("expected_kwh")
    ghi = source.get("weather", {}).get("ghi_kwh_m2")
    if raw_expected is None or ghi is None or float(raw_expected) <= 0:
        return
    with state_store.lock:
        history = state_store.data.setdefault("history", [])
        existing = next((x for x in history if x.get("date") == today_ds and x.get("source") == "live"), None)
        record = {
            "date": today_ds,
            "ghi": float(ghi),
            "raw_expected": float(raw_expected),
            "actual": float(actual),
            "ratio": float(actual) / float(raw_expected),
            "source": "live",
        }
        if existing:
            existing.update(record)
        else:
            history.append(record)
        history.sort(key=lambda x: x.get("date", ""))
        if len(history) > 180:
            state_store.data["history"] = history[-180:]
        state_store.save()


def archive_current_forecasts() -> None:
    with state_store.lock:
        archive = state_store.data.setdefault("forecast_archive", {})
        for ds, value in state_store.data.get("forecast", {}).items():
            archive[ds] = value
        cutoff = now_local().date() - timedelta(days=120)
        for ds in list(archive.keys()):
            try:
                if date.fromisoformat(ds) < cutoff:
                    archive.pop(ds, None)
            except Exception:
                pass
        state_store.save()


def enforce_0500_cutoff() -> None:
    """Harte 05:00-Grenze für automatisch gestartete Nachtverbraucher."""
    actions = state_store.data.get("night_actions", {})
    errors: list[str] = []
    try:
        if actions.get("battery_safe_charge") or state_text(ENTITIES["battery_safe_charge"]) == "on":
            battery_safe_charge(False, track_night=True)
    except Exception as exc:
        errors.append(f"Speicher: {exc}")
    try:
        session = state_store.data.get("warmwater_session", {})
        if actions.get("warmwater") or (session.get("night") and session.get("started") and not session.get("ended")):
            stop_warmwater_session(track_night=True)
    except Exception as exc:
        errors.append(f"Warmwasser: {exc}")
    try:
        if (
            actions.get("wallbox_fast")
            or state_text(ENTITIES["wallbox_mode"]) == "fast"
            or state_text(ENTITIES["phase2"]) == "on"
            or state_text(ENTITIES["phase3"]) == "on"
        ):
            wallbox_set_locked(track_night=True)
    except Exception as exc:
        errors.append(f"Wallbox: {exc}")
    try:
        stop_wallbox_session()
        ensure_phase1_on()
    except Exception as exc:
        errors.append(f"Phase 1: {exc}")
    if errors:
        send_notification(
            "Energieplaner · 05:00 Fehler",
            "Automatischer Nachtabschluss nicht vollständig: " + " | ".join(errors),
            critical_silent=True,
        )


def automatic_night_wallbox(now: datetime) -> None:
    settings = settings_store.data
    if not settings.get("master_automation_enabled") or not (0 <= now.hour < 5):
        return
    mode = str(state_store.data.get("night_override", "auto") or "auto")
    if not bool(state_store.data.get("car_auto_charging_enabled", True)):
        return
    if mode == "auto" and not settings.get("wallbox_night_auto_enabled"):
        return

    decision = night_wallbox_decision()
    target = int(decision.get("target") or current_night_target())

    if not car_at_wallbox():
        if state_text(ENTITIES["wallbox_mode"]) == "fast" or state_text(ENTITIES["phase2"]) == "on" or state_text(ENTITIES["phase3"]) == "on":
            wallbox_set_locked(track_night=True)
        stop_wallbox_session()
        return

    # Nur-PV ist absolut: Zwischen 00:00 und 05:00 bleibt Schnellladen aus,
    # selbst wenn der Mindest-SOC noch nicht erreicht ist.
    if decision.get("action") == "pv_wait":
        if state_text(ENTITIES["wallbox_mode"]) != "locked" or state_text(ENTITIES["phase2"]) == "on" or state_text(ENTITIES["phase3"]) == "on":
            wallbox_set_locked(track_night=True)
        stop_wallbox_session()
        return

    if decision.get("action") == "fast":
        session = wallbox_session_status(target)
        # Sobald die Sitzung das wirklich ladende Fahrzeug erkannt hat, ist dessen
        # SOC maßgeblich. So stoppt die Ladung exakt am Mindestziel.
        if session.get("reached"):
            if state_text(ENTITIES["wallbox_mode"]) == "fast" or state_text(ENTITIES["phase2"]) == "on" or state_text(ENTITIES["phase3"]) == "on":
                wallbox_set_locked(track_night=True)
            stop_wallbox_session()
            return
        if state_text(ENTITIES["wallbox_mode"]) != "fast" or state_text(ENTITIES["phase2"]) != "on" or state_text(ENTITIES["phase3"]) != "on":
            wallbox_set_fast(track_night=True)
        return

    # Ziel bereits erreicht bzw. keine Nachtladung notwendig.
    if state_text(ENTITIES["wallbox_mode"]) == "fast" or state_text(ENTITIES["phase2"]) == "on" or state_text(ENTITIES["phase3"]) == "on":
        wallbox_set_locked(track_night=True)
    stop_wallbox_session()


def trusted_battery_soc(now: datetime) -> float | None:
    """Lässt einzelne unrealistische SOC-Sprünge nicht zur Steuerung durch."""
    raw = state_value(ENTITIES["battery_soc"])
    if raw is None:
        return None
    raw = max(0.0, min(100.0, float(raw)))
    with state_store.lock:
        guard = state_store.data.setdefault("battery_soc_guard", {})
        accepted = guard.get("accepted_soc")
        try:
            accepted_value = float(accepted) if accepted is not None else None
        except (TypeError, ValueError):
            accepted_value = None

        implausible = accepted_value is not None and (
            (raw <= 0.1 and accepted_value >= 5.0)
            or abs(raw - accepted_value) > 3.0
        )
        if not implausible:
            guard.update({
                "accepted_soc": raw,
                "accepted_at": now.isoformat(),
                "pending_soc": None,
                "pending_count": 0,
                "last_rejection": None,
            })
            state_store.save()
            return raw

        pending = guard.get("pending_soc")
        try:
            matches_pending = pending is not None and abs(raw - float(pending)) <= 1.0
        except (TypeError, ValueError):
            matches_pending = False
        count = int(guard.get("pending_count") or 0) + 1 if matches_pending else 1
        guard.update({
            "pending_soc": raw,
            "pending_count": count,
            "last_rejection": f"SOC-Sprung {accepted_value:.1f}% → {raw:.1f}% abgewiesen ({count}/3)",
        })
        if count >= 3:
            guard.update({
                "accepted_soc": raw,
                "accepted_at": now.isoformat(),
                "pending_soc": None,
                "pending_count": 0,
                "last_rejection": None,
            })
            state_store.save()
            return raw
        state_store.save()
        LOG.warning("Unplausiblen Akku-SOC ignoriert: %.1f%% statt %.1f%% (%s/3)", raw, accepted_value, count)
        return accepted_value


def automatic_battery(now: datetime) -> None:
    """Steuert die Nachtladung als einen stabilen, bis zum Ziel gelatchten Lauf."""
    settings = settings_store.data
    if not (settings.get("master_automation_enabled") and settings.get("battery_auto_enabled")):
        return
    if not (0 <= now.hour < 5):
        return
    plan = state_store.data.get("plan", {}).get("battery", {}) or {}
    soc = trusted_battery_soc(now)
    if soc is None:
        LOG.warning("Nachtladung %s übersprungen: kein verlässlicher Akku-SOC", now.date().isoformat())
        return

    today = now.date().isoformat()
    actual_on = state_text(ENTITIES["battery_safe_charge"]) == "on"
    with state_store.lock:
        control = state_store.data.setdefault("battery_night_control", {})
        if control.get("date") != today:
            try:
                plan_target = float(plan.get("target_soc"))
            except (TypeError, ValueError):
                plan_target = 25.0
            control.update({
                "date": today,
                # Die Mindestladung darf niemals durch einen fehlenden oder
                # veralteten Plan auf 0 %/20 % fallen. Der Plan kann ein
                # höheres Ziel vorgeben, aber nachts gilt immer mindestens 25 %.
                "target_soc": max(25.0, plan_target),
                "planned_start_minute": None,
                "charge_latched": False,
                "completed": False,
                "started_at": None,
                "last_error": None,
            })
        try:
            target = max(25.0, float(control.get("target_soc") or plan.get("target_soc") or 25.0))
        except (TypeError, ValueError):
            target = 25.0
        control["target_soc"] = target
        schedule = battery_schedule(soc, target)
        needed_minutes = int(schedule.get("needed_minutes") or 0)
        buffer = int(schedule.get("start_buffer_minutes") or 0)
        calculated_start = max(0, 300 - needed_minutes - buffer)
        stored_start = control.get("planned_start_minute")
        planned_start = int(stored_start) if stored_start is not None else calculated_start
        # Eine neue Messung darf den Start nur vorziehen, nie nach hinten schieben.
        control["planned_start_minute"] = min(planned_start, calculated_start)
        control["last_check_at"] = now.isoformat()
        if actual_on:
            control["charge_latched"] = True
            control["started_at"] = control.get("started_at") or now.isoformat()
        completed = bool(control.get("completed"))
        # Ein alter Abschluss darf eine neue Unterladung nicht blockieren.
        # Das ist besonders wichtig nach einem manuellen Eingriff oder einem
        # Neustart, wenn der Schalterzustand nicht zum gespeicherten Abschluss passt.
        if completed and soc < target - 1.0:
            completed = False
            control["completed"] = False
            control["charge_latched"] = False
            control["started_at"] = None
            control["last_error"] = f"Alten Abschluss verworfen: SOC {soc:.1f}% unter Ziel {target:.1f}%"
        target_reached = soc >= target or needed_minutes == 0
        if target_reached:
            control["completed"] = True
            control["charge_latched"] = False
        should_start = (
            not completed
            and not target_reached
            and (bool(control.get("charge_latched")) or now.hour * 60 + now.minute >= int(control["planned_start_minute"]))
        )
        if should_start:
            control["charge_latched"] = True
            control["started_at"] = control.get("started_at") or now.isoformat()
        state_store.save()

    if target_reached or completed:
        if actual_on:
            battery_safe_charge(False, track_night=True)
    elif should_start and not actual_on:
        confirmed = battery_safe_charge(True, track_night=True)
        if confirmed:
            LOG.info("Nachtladung %s gestartet: SOC %.1f%% → Ziel %.1f%%", today, soc, target)
        else:
            LOG.error("Nachtladung %s konnte nicht bestätigt eingeschaltet werden", today)


def start_warmwater_session(track_night: bool) -> None:
    before = parse_number_from_state(ENTITIES["warmwater_temp"])
    warmwater_set(True, track_night=track_night)
    with state_store.lock:
        state_store.data["warmwater_session"] = {
            "started": now_local().isoformat(),
            "before": before,
            "night": track_night,
        }
        state_store.save()


def stop_warmwater_session(track_night: bool) -> None:
    warmwater_set(False, track_night=track_night)
    time.sleep(2)
    after = parse_number_from_state(ENTITIES["warmwater_temp"])
    with state_store.lock:
        session = state_store.data.get("warmwater_session", {})
        before = session.get("before")
        state_store.data["warmwater_session"] = {"last_before": before, "last_after": after, "ended": now_local().isoformat()}
        state_store.save()
    if before is not None and after is not None and after <= before:
        send_notification(
            "Achtung!",
            f"Warmwasseraufbereitung war nicht erfolgreich! Vorher: {before:.1f}°C, Nachher: {after:.1f}°C",
            critical_silent=True,
        )


def automatic_warmwater(now: datetime) -> None:
    settings = settings_store.data
    if not (settings.get("master_automation_enabled") and settings.get("warmwater_auto_enabled")):
        return
    forecasts = state_store.data.get("forecast", {})
    if not isinstance(forecasts, dict):
        return
    hourly = {ds: v.get("hourly", []) for ds, v in forecasts.items() if isinstance(v, dict)}
    plan_all = build_plan(forecasts, hourly)
    # 00:00–04:59: Nachtplan. Ab 05:00: ausschließlich heutiges PV-Fenster;
    # eine verpasste Nachtaktion wird nicht tagsüber als Nachtaktion nachgeholt.
    plan = plan_all.get("warmwater", {}) if now.hour < 5 else plan_all.get("today_warmwater", {})
    if not plan:
        return
    if plan.get("date") and str(plan.get("date")) != now.date().isoformat():
        return
    try:
        sh, sm = [int(x) for x in str(plan.get("start_time", "10:00")).split(":")]
        eh, em = [int(x) for x in str(plan.get("end_time", "12:00")).split(":")]
    except Exception:
        return
    current = now.hour * 60 + now.minute
    start = sh * 60 + sm
    end = eh * 60 + em
    active = state_text(ENTITIES["warmwater_switch"]) == "on"
    session = state_store.data.get("warmwater_session", {})
    started_by_app = bool(session.get("started") and not session.get("ended"))
    track_night = now.hour < 5 and plan.get("mode") == "night"
    if start <= current < end and not active and not started_by_app:
        start_warmwater_session(track_night=track_night)
    elif current >= end and started_by_app:
        stop_warmwater_session(track_night=track_night)


def set_pv_status(status_key: str, action: str, power: float | None = None) -> None:
    """Speichert auch bei einer bewusst unterdrückten PV-Aktion den Grund."""
    changed = False
    with state_store.lock:
        pv = state_store.data.setdefault("pv_surplus", {})
        stamp = now_local().isoformat()
        if pv.get("status_key") != status_key:
            pv["status_since"] = stamp
            changed = True
        if pv.get("candidate_phases") is not None or pv.get("candidate_since") is not None:
            changed = True
        if pv.get("last_action") != action:
            changed = True
        pv.update({
            "status_key": status_key,
            "candidate_phases": None,
            "candidate_since": None,
            "last_action": action,
        })
        if power is not None:
            pv["status_power_w"] = round(power)
        if changed:
            state_store.save()
    if changed:
        _kick_dashboard_refresh()


def pv_available_car_budget(now: datetime, forecasts: dict[str, Any]) -> float:
    """Hält das PV-Budget höchstens eine Minute lang vor.

    Die Überschussregelung läuft im Sekundenbereich. Die aufwendigere
    Tagesplanung muss dafür nicht bei jedem Kontrolltakt erneut alle
    Home-Assistant-Zustände berechnen. Ein fehlendes oder nicht berechenbares
    Budget bleibt absichtlich ein Fehler statt die Wallbox blind freizugeben.
    """
    with state_store.lock:
        cache = state_store.data.setdefault("pv_budget_cache", {})
        checked_at = cache.get("checked_at")
        cached_date = str(cache.get("date") or "")
        cached_value = cache.get("available_car_kwh")
    try:
        age_seconds = _seconds_since_iso(checked_at, now)
        available = float(cached_value)
    except (TypeError, ValueError):
        age_seconds = float("inf")
        available = None
    if cached_date == now.date().isoformat() and available is not None and age_seconds < 60:
        return available

    hourly_by_day = {ds: value.get("hourly", []) for ds, value in forecasts.items() if isinstance(value, dict)}
    live_plan = build_plan(forecasts, hourly_by_day)
    budget = live_plan.get("pv_charging", {}).get("budget", {})
    available = float(budget.get("available_car_kwh", 0) or 0)
    with state_store.lock:
        state_store.data["pv_budget_cache"] = {
            "date": now.date().isoformat(),
            "checked_at": now.isoformat(),
            "available_car_kwh": available,
        }
        state_store.save()
    return available


def pv_battery_priority_guard(now: datetime, forecasts: dict[str, Any]) -> tuple[bool, str]:
    """Zusätzlicher schwacher-Tag-/Spät-Tag-Schutz vor Auto-PV-Laden.

    Die eigentliche Leistungsregel nutzt bereits nur noch den realen
    Überschuss *nach* Speicherladung. Dieser Guard verhindert zusätzlich,
    dass ein einzelner kurzer Export-Peak an einem deutlich hinter der
    Prognose liegenden Tag oder kurz vor PV-Ende die Auto-Automatik startet,
    obwohl der Speicher noch nicht nahezu voll ist.
    """
    soc = trusted_battery_soc(now)
    if soc is None:
        soc = state_value(ENTITIES["battery_soc"])
    if soc is None:
        return False, "Speicher-SOC fehlt"
    soc = max(0.0, min(100.0, float(soc)))
    if soc >= 95.0:
        return True, f"Speicher {soc:.0f}%"

    today = forecasts.get(now.date().isoformat(), {}) if isinstance(forecasts, dict) else {}
    if not isinstance(today, dict) or not today:
        return False, "Heutige PV-Prognose fehlt"
    rows = today.get("hourly", []) if isinstance(today.get("hourly", []), list) else []
    live = live_pv_analysis(today, rows, now)
    delta_pct = live.get("delta_percent") if isinstance(live, dict) else None
    enough = bool(live.get("enough_data")) if isinstance(live, dict) else False
    if enough and delta_pct is not None and float(delta_pct) <= -15.0:
        return False, f"PV {abs(float(delta_pct)):.0f}% hinter Soll · Speicher erst {soc:.0f}%"

    active_times: list[datetime] = []
    for row in rows:
        try:
            if float(row.get("radiation_wm2", 0) or 0) < 50:
                continue
            stamp = datetime.fromisoformat(str(row.get("time")))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=local_tz())
            else:
                stamp = stamp.astimezone(local_tz())
            active_times.append(stamp)
        except Exception:
            continue
    if active_times:
        pv_end = max(active_times)
        remaining_hours = (pv_end - now).total_seconds() / 3600.0
        if 0 <= remaining_hours <= 2.0 and soc < 95.0:
            return False, f"nur noch {remaining_hours:.1f} h PV-Fenster · Speicher erst {soc:.0f}%"
    return True, f"Speicherpriorität erfüllt ({soc:.0f}%)"


def pv_surplus_tick(now: datetime) -> None:
    settings = settings_store.data
    if not settings.get("master_automation_enabled"):
        set_pv_status("master_disabled", "Gesamtautomatik aus")
        return
    if not settings.get("pv_surplus_auto_enabled"):
        set_pv_status("automation_disabled", "PV-Wallbox-Automatik aus")
        return
    mode = state_text(ENTITIES["wallbox_mode"])
    if not bool(state_store.data.get("car_auto_charging_enabled", True)):
        if mode == "optimized":
            wallbox_set_locked(reset_tracking=False)
        set_pv_status("manual_car_block", "Automatische Autoladung manuell pausiert")
        return
    if now.hour < 5 or now.hour >= 22:
        # PV-Laden hat außerhalb des Tagesfensters keinen Zweck. Nacht-Schnellladen
        # verwendet den separaten Modus "fast" und bleibt davon unberührt.
        if mode == "optimized":
            wallbox_set_locked(reset_tracking=False)
        set_pv_status("outside_pv_window", "PV-Laden außerhalb des Tagesfensters gesperrt")
        return

    # Ein bewusst gesetztes Schnellladen hat Vorrang vor der PV-Automatik.
    # Dadurch kann tagsüber jederzeit ``fast`` verwendet werden, ohne dass ein
    # guter PV-Wert den Modus nachträglich wieder auf ``optimized`` umstellt.
    if mode == "fast":
        set_pv_status("fast_manual", "Schnellladen hat Vorrang")
        return

    # Live-Leistung vor der aufwendigeren Tagesplanung lesen. So bleibt die
    # Statuszeile inklusive Zeitangabe auch dann korrekt, wenn die Prognose
    # oder die Budgetberechnung gerade einmal fehlschlägt.
    power = current_pv_surplus_w()
    if power is None:
        set_pv_status("power_missing", "Sicherer Überschuss nach Haus/Speicher fehlt")
        return

    if not car_at_wallbox():
        if mode == "optimized":
            wallbox_set_locked(reset_tracking=False)
        set_pv_status("no_car", "Kein Auto an der Wallbox", power)
        return

    forecasts = state_store.data.get("forecast", {})
    if not isinstance(forecasts, dict) or not forecasts:
        set_pv_status("forecast_missing", "PV-Prognose fehlt", power)
        return
    try:
        available_car = pv_available_car_budget(now, forecasts)
        min_budget = float(settings.get("car_budget_min_kwh", 1.5))
        battery_ok, battery_reason = pv_battery_priority_guard(now, forecasts)
    except Exception:
        LOG.exception("PV-Status: Tagesplanung konnte nicht berechnet werden")
        set_pv_status("planning_error", "PV-Tagesplanung fehlgeschlagen", power)
        return

    if not battery_ok:
        if mode == "optimized":
            wallbox_set_locked(reset_tracking=False)
        set_pv_status("battery_priority", f"Speicher hat Vorrang: {battery_reason}", power)
        return

    p1_start = float(settings.get("pv_phase1_start_w", 1600))
    p1_stop = float(settings.get("pv_phase1_stop_w", 1400))
    p2_start = float(settings.get("pv_phase2_start_w", 3600))
    p2_stop = float(settings.get("pv_phase2_stop_w", 3000))
    p3_start = float(settings.get("pv_phase3_start_w", 5200))
    p3_stop = float(settings.get("pv_phase3_stop_w", 4500))
    # Das Ein- und Ausschalten der Wallbox darf zügig reagieren. Nur jede
    # *zusätzliche* Phase muss den höheren Überschuss lange genug sehen, damit
    # Wolken nicht zu einer ständigen Umschaltung führen.
    down_delay = max(30, int(settings.get("pv_surplus_delay_seconds", 120)))
    up_delay = max(30, int(settings.get("pv_phase_hold_seconds", 1800)))

    current_phases = 0
    if mode == "optimized":
        current_phases = 1 + int(state_text(ENTITIES["phase2"]) == "on") + int(state_text(ENTITIES["phase3"]) == "on")

    # Ein begrenztes Tagesbudget deckelt die maximalen Phasen, damit ein kurzer
    # Leistungsspitzen-Peak nicht die für Haus/Abend benötigte Energie auffrisst.
    if available_car < min_budget:
        max_phases = 0
    elif available_car < 6:
        max_phases = 1
    elif available_car < 12:
        max_phases = 2
    else:
        max_phases = 3

    desired = current_phases
    if current_phases <= 0:
        desired = 1 if power >= p1_start and max_phases >= 1 else 0
    elif current_phases == 1:
        if power < p1_stop or max_phases == 0:
            desired = 0
        elif power >= p2_start and max_phases >= 2:
            desired = 2
    elif current_phases == 2:
        if power < p2_stop or max_phases < 2:
            desired = 1 if max_phases >= 1 and power >= p1_stop else 0
        elif power >= p3_start and max_phases >= 3:
            desired = 3
    else:
        if power < p3_stop or max_phases < 3:
            desired = 2 if max_phases >= 2 and power >= p2_stop else 1 if max_phases >= 1 and power >= p1_stop else 0

    # Für die Oberfläche halten wir den *aktuellen* Zustand getrennt von der
    # eigentlichen Schaltwartezeit fest. So kann sie verständlich sagen,
    # seit wann Überschuss fehlt bzw. wie lange die Wallbox schon lädt.
    if current_phases <= 0:
        if max_phases == 0:
            status_key = "budget_low"
        else:
            status_key = "locked_waiting_start" if power >= p1_start else "locked_low"
    elif current_phases == 1:
        if power < p1_stop or max_phases == 0:
            status_key = "phase1_low"
        elif power >= p2_start and max_phases >= 2:
            status_key = "phase1_waiting_phase2"
        else:
            status_key = "phase1_normal"
    elif current_phases == 2:
        if power < p2_stop or max_phases < 2:
            status_key = "phase2_low"
        elif power >= p3_start and max_phases >= 3:
            status_key = "phase2_waiting_phase3"
        else:
            status_key = "phase2_normal"
    else:
        status_key = "phase3_low" if power < p3_stop or max_phases < 3 else "phase3_normal"

    stamp = now.isoformat()
    changed = False
    with state_store.lock:
        pv = state_store.data.setdefault("pv_surplus", {})
        observed_state = f"{mode}_{current_phases}" if mode == "optimized" else mode
        if pv.get("observed_wallbox_state") != observed_state:
            pv["observed_wallbox_state"] = observed_state
            pv["status_since"] = stamp
            changed = True
        if pv.get("status_key") != status_key:
            pv["status_key"] = status_key
            pv["status_since"] = stamp
            changed = True
        # „Lädt seit“ gehört zur gesamten PV-Ladesitzung, die Phasendauer
        # dagegen nur zur gerade aktiven Phasenzahl. Ein kurzer Lock während
        # des Umschaltens zählt weiter zur Sitzung; erst ab fünf Minuten ist
        # die Ladesitzung wirklich beendet.
        if mode == "optimized":
            paused_for = _seconds_since_iso(pv.get("charging_pause_since"), now)
            if not pv.get("charging_since") or paused_for >= 300:
                pv["charging_since"] = stamp
                pv["phase_since"] = stamp
                pv["phase_count"] = current_phases
                changed = True
            elif int(pv.get("phase_count") or 0) != current_phases:
                pv["phase_since"] = stamp
                pv["phase_count"] = current_phases
                changed = True
            if pv.get("charging_pause_since") is not None:
                pv["charging_pause_since"] = None
                changed = True
        elif pv.get("charging_since"):
            if not pv.get("charging_pause_since"):
                pv["charging_pause_since"] = stamp
                changed = True
            elif _seconds_since_iso(pv.get("charging_pause_since"), now) >= 300:
                pv["charging_since"] = None
                pv["charging_pause_since"] = None
                pv["phase_since"] = None
                pv["phase_count"] = 0
                changed = True
        pv["status_power_w"] = round(power)
        candidate = pv.get("candidate_phases")
        if desired == current_phases:
            if candidate is not None or pv.get("candidate_since") is not None:
                changed = True
            pv["candidate_phases"] = None
            pv["candidate_since"] = None
        else:
            if candidate != desired:
                pv["candidate_phases"] = desired
                pv["candidate_since"] = stamp
                changed = True
            else:
                elapsed = _seconds_since_iso(pv.get("candidate_since"), now)
                is_extra_phase = desired > current_phases and current_phases > 0
                wait_needed = up_delay if is_extra_phase else down_delay
                if elapsed >= wait_needed:
                    if desired <= 0:
                        wallbox_set_locked(reset_tracking=False)
                        pv["last_action"] = "locked"
                    else:
                        wallbox_set_pv_phases(desired, reset_tracking=False)
                        pv["last_action"] = f"optimized_{desired}p"
                    pv["current_phases"] = desired
                    pv["observed_wallbox_state"] = f"optimized_{desired}" if desired > 0 else "locked"
                    pv["status_key"] = f"phase{desired}_normal" if desired > 0 else "locked_low"
                    pv["status_since"] = stamp
                    pv["last_phase_change"] = stamp
                    if desired > 0:
                        pv["phase_since"] = stamp
                        pv["phase_count"] = desired
                    pv["candidate_phases"] = None
                    pv["candidate_since"] = None
                    changed = True
        if changed:
            state_store.save()
    if changed:
        _kick_dashboard_refresh()


def pv_control_loop() -> None:
    """Unabhängige, zügige PV-Freigabe und Phasensteuerung.

    Der Minuten-Scheduler ist für Prognosen, Lernen und Nachtplanung richtig.
    Die Wallbox muss dagegen ihre 120-Sekunden-Fristen unabhängig davon
    einhalten, auch wenn eine Wetterabfrage oder ein anderer Planlauf hängt.
    """
    LOG.info("PV-Wallbox-Steuerung gestartet (5-Sekunden-Takt)")
    while True:
        try:
            pv_surplus_tick(now_local())
        except Exception:
            LOG.exception("PV-Wallbox-Steuerung fehlgeschlagen")
        time.sleep(5)


def _seconds_since_iso(stamp: Any, now: datetime) -> float:
    if not stamp:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(stamp))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        else:
            dt = dt.astimezone(now.tzinfo)
        return max(0.0, (now - dt).total_seconds())
    except Exception:
        return 0.0


def _watchdog_reset_transient(now: datetime, ok: bool = True) -> None:
    with state_store.lock:
        wd = state_store.data.setdefault("wallbox_watchdog", {})
        wd["low_since"] = None
        wd["sensor_missing_since"] = None
        wd["lock_attempts"] = 0
        wd["last_lock_attempt_at"] = None
        wd["alerted"] = False
        wd["last_check_at"] = now.isoformat()
        if ok:
            wd["last_ok_at"] = now.isoformat()
        state_store.save()


def _watchdog_force_lock(now: datetime, reason: str) -> None:
    """Wallbox sperren, Zustand verifizieren und bei Bedarf genau einmal wiederholen."""
    with state_store.lock:
        wd = state_store.data.setdefault("wallbox_watchdog", {})
        attempts = int(wd.get("lock_attempts") or 0)
        last_attempt = wd.get("last_lock_attempt_at")
        if attempts >= 2:
            should_alert = not bool(wd.get("alerted"))
        else:
            should_alert = False
            if last_attempt and _seconds_since_iso(last_attempt, now) < 5:
                return
            wd["lock_attempts"] = attempts + 1
            wd["last_lock_attempt_at"] = now.isoformat()
            wd["last_action"] = f"Sperrversuch {attempts + 1}: {reason}"
            wd["last_check_at"] = now.isoformat()
            state_store.save()

    if attempts < 2:
        try:
            wallbox_set_locked()
        except Exception:
            LOG.exception("Wallbox-Sicherheitswächter: Sperrbefehl fehlgeschlagen (%s)", reason)

        # Durch call_service() wurde der HA-State-Cache invalidiert. Direkt neu
        # lesen; falls der Select-Zustand verzögert kommt, übernimmt der nächste
        # 10-Sekunden-Watchdog-Tick den zweiten und letzten Versuch.
        locked = state_text(ENTITIES["wallbox_mode"]) == "locked"
        phases_safe = state_text(ENTITIES["phase2"]) != "on" and state_text(ENTITIES["phase3"]) != "on"
        if locked and phases_safe:
            with state_store.lock:
                wd = state_store.data.setdefault("wallbox_watchdog", {})
                wd["safety_stops"] = int(wd.get("safety_stops") or 0) + 1
                wd["last_action"] = f"Sicher gesperrt: {reason}"
                wd["last_ok_at"] = now.isoformat()
                wd["low_since"] = None
                wd["sensor_missing_since"] = None
                wd["lock_attempts"] = 0
                wd["last_lock_attempt_at"] = None
                wd["alerted"] = False
                state_store.save()
            LOG.warning("Wallbox-Sicherheitswächter hat gesperrt: %s", reason)
            return

        with state_store.lock:
            wd = state_store.data.setdefault("wallbox_watchdog", {})
            attempts_now = int(wd.get("lock_attempts") or 0)
            should_alert = attempts_now >= 2 and not bool(wd.get("alerted"))

    if should_alert:
        message = f"PV-Ladung konnte trotz Sicherheitswächter nicht sicher gesperrt werden ({reason}). Bitte Wallbox prüfen."
        send_notification("⚠️ Energieplaner · Wallbox", message, critical_silent=False)
        with state_store.lock:
            wd = state_store.data.setdefault("wallbox_watchdog", {})
            wd["alerted"] = True
            wd["last_action"] = f"FEHLER: Sperren nicht bestätigt ({reason})"
            wd["last_check_at"] = now.isoformat()
            state_store.save()
        LOG.error("Wallbox-Sicherheitswächter: Sperren nach zwei Versuchen nicht bestätigt (%s)", reason)


def wallbox_watchdog_tick(now: datetime) -> None:
    """Unabhängige Fail-Safe-Prüfung für das automatische PV-Laden.

    Sie verwendet exakt dieselbe Phase-1-Abschaltschwelle und Stabilitätszeit
    wie die normale PV-Regelung. Damit entsteht keine zweite, aggressivere
    Regel: der Watchdog greift nur ein, wenn die reguläre Automatik versagt.
    """
    settings = settings_store.data
    enabled = bool(settings.get("master_automation_enabled") and settings.get("pv_surplus_auto_enabled"))
    if not enabled:
        _watchdog_reset_transient(now, ok=True)
        return

    # Der Watchdog ist absichtlich zeitunabhängig: Er schützt immer dann,
    # wenn die Wallbox tatsächlich im PV-/Überschussmodus ``optimized`` läuft.
    # Schnellladen (``fast``) bleibt davon vollständig unberührt – egal zu
    # welcher Uhrzeit, damit auch ein bewusst gestartetes Tages-Schnellladen
    # nicht wegen fehlendem PV-Überschuss beendet wird.
    mode = state_text(ENTITIES["wallbox_mode"])
    if mode != "optimized":
        _watchdog_reset_transient(now, ok=True)
        return

    stop_w = float(settings.get("pv_phase1_stop_w", 1400))
    delay_s = max(30, int(settings.get("pv_surplus_delay_seconds", 120)))
    sensor_timeout_s = max(180, delay_s)
    power = current_pv_surplus_w()

    with state_store.lock:
        wd = state_store.data.setdefault("wallbox_watchdog", {})
        wd["last_check_at"] = now.isoformat()
        if power is None:
            wd["low_since"] = None
            if not wd.get("sensor_missing_since"):
                wd["sensor_missing_since"] = now.isoformat()
            missing_since = wd.get("sensor_missing_since")
            state_store.save()
        else:
            wd["sensor_missing_since"] = None
            if power < stop_w:
                if not wd.get("low_since"):
                    wd["low_since"] = now.isoformat()
                low_since = wd.get("low_since")
                wd["last_action"] = f"Überwacht: {round(power)} W unter {round(stop_w)} W"
                state_store.save()
            else:
                wd["low_since"] = None
                wd["lock_attempts"] = 0
                wd["last_lock_attempt_at"] = None
                wd["alerted"] = False
                wd["last_ok_at"] = now.isoformat()
                wd["last_action"] = f"OK: {round(power)} W Überschuss"
                state_store.save()
                return

    if power is None:
        if _seconds_since_iso(missing_since, now) >= sensor_timeout_s:
            _watchdog_force_lock(now, f"Leistungssensoren seit {sensor_timeout_s} s nicht verfügbar")
        return

    if _seconds_since_iso(low_since, now) >= delay_s:
        _watchdog_force_lock(now, f"{round(power)} W seit mindestens {delay_s} s unter {round(stop_w)} W")


def wallbox_watchdog_loop() -> None:
    LOG.info("Wallbox-Sicherheitswächter gestartet (10-Sekunden-Takt)")
    while True:
        try:
            wallbox_watchdog_tick(now_local())
        except Exception:
            LOG.exception("Wallbox-Sicherheitswächter fehlgeschlagen")
        time.sleep(10)


def _history_numeric_series(entity_id: str, start: datetime, end: datetime, multiplier: float = 1.0) -> list[tuple[datetime, float]]:
    start_encoded = urllib.parse.quote(start.isoformat(timespec="seconds"), safe="")
    query = urllib.parse.urlencode({
        "end_time": end.isoformat(timespec="seconds"),
        "filter_entity_id": entity_id,
    })
    path = f"/history/period/{start_encoded}?{query}&minimal_response&no_attributes"
    try:
        raw = ha_request(path, timeout=60)
    except Exception:
        LOG.exception("History-Abfrage fehlgeschlagen: %s", entity_id)
        return []
    rows = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], list) else (raw if isinstance(raw, list) else [])
    result: list[tuple[datetime, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = row.get("last_changed") or row.get("last_updated")
        try:
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz())
            else:
                dt = dt.astimezone(local_tz())
            value = float(str(row.get("state")).replace(",", ".")) * multiplier
        except Exception:
            continue
        result.append((dt, value))
    result.sort(key=lambda item: item[0])
    return result


def _series_value_at(series: list[tuple[datetime, float]], when: datetime) -> float | None:
    value: float | None = None
    for stamp, current in series:
        if stamp <= when:
            value = current
        else:
            break
    return value


def _find_morning_pv_cover(
    pv_series: list[tuple[datetime, float]],
    house_series: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> datetime | None:
    # Erst wenn PV 20 Minuten am Stück mindestens die Hauslast trägt, gilt der
    # Morgen als von der PV übernommen. Kurze Wolkenlücken lösen keinen Treffer aus.
    t = start
    consecutive = 0
    while t <= end:
        pv = _series_value_at(pv_series, t)
        house = _series_value_at(house_series, t)
        if pv is not None and house is not None and pv >= house:
            consecutive += 1
            if consecutive >= 4:
                return t - timedelta(minutes=15)
        else:
            consecutive = 0
        t += timedelta(minutes=5)
    return None


def _integrate_morning_net_need(
    pv_series: list[tuple[datetime, float]],
    house_series: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> float | None:
    if end <= start:
        return 0.0
    t = start
    total_wh = 0.0
    samples = 0
    while t < end:
        pv = _series_value_at(pv_series, t)
        house = _series_value_at(house_series, t)
        if pv is not None and house is not None:
            total_wh += max(0.0, house - pv) * (5.0 / 60.0)
            samples += 1
        t += timedelta(minutes=5)
    return total_wh / 1000.0 if samples else None


def morning_learning_tick(now: datetime) -> None:
    """Vergleicht Morgenprognose und Realität und lernt drei getrennte Größen.

    1. Mindestreserve: SOC, der bei realer stabiler PV-Übernahme übrig bleiben soll.
    2. Zeitoffset: systematische Abweichung zwischen prognostizierter und realer
       PV-Übernahme; maximal etwa fünf Minuten Anpassung pro Lerntag.
    3. Energiepuffer: Abweichung zwischen prognostiziertem und realem Netto-
       Morgenbedarf; wächst höchstens zwei Prozentpunkte pro Tag und sinkt
       bewusst langsamer.
    """
    # Nicht bis 13:10 warten: Sobald die reale PV mindestens 20 Minuten stabil
    # die Hauslast trägt, ist der heutige Morgen vollständig auswertbar und soll
    # sofort in der Oberfläche erscheinen. Nur wenn bis 13:00 keine stabile
    # Übernahme gefunden wurde, schließen wir den Lerntag ab 13:10 ohne Treffer.
    start = datetime.combine(now.date(), datetime.min.time(), tzinfo=local_tz()) + timedelta(hours=5)
    hard_end = datetime.combine(now.date(), datetime.min.time(), tzinfo=local_tz()) + timedelta(hours=13)
    if now < start + timedelta(minutes=20):
        return
    learning = state_store.data.setdefault("morning_learning", {})
    today_ds = now.date().isoformat()
    if learning.get("last_sample_date") == today_ds:
        return

    end = min(now, hard_end)
    pv_series = _history_numeric_series(ENTITIES["pv_power_kw"], start, end, 1000.0)
    house_series = _history_numeric_series(ENTITIES["house_power"], start, end, 1.0)
    soc_series = _history_numeric_series(ENTITIES["battery_soc"], start, end, 1.0)
    if not pv_series or not house_series or not soc_series:
        LOG.warning("Morgenlernen %s übersprungen: Historie unvollständig", today_ds)
        return

    battery_learning = state_store.data.get("battery_learning", {})
    target_date = str(battery_learning.get("soc_0500_date") or "")
    target_0500 = battery_learning.get("target_soc_0500")
    if target_date != today_ds or target_0500 is None:
        learning["last_sample_date"] = today_ds
        learning["last_adjustment"] = "Kein passendes 05:00-Ziel gespeichert; Morgenlernen unverändert"
        state_store.save()
        return

    cover = _find_morning_pv_cover(pv_series, house_series, start, end)
    if cover is None:
        if now >= hard_end + timedelta(minutes=10):
            learning["last_sample_date"] = today_ds
            learning["last_adjustment"] = "Bis 13:00 keine stabile PV-Deckung; Morgenlernen unverändert"
            state_store.save()
        return
    net_need = _integrate_morning_net_need(pv_series, house_series, start, cover)
    soc_0500 = _series_value_at(soc_series, start)
    soc_cover = _series_value_at(soc_series, cover)
    if net_need is None or soc_0500 is None or soc_cover is None:
        return

    forecasts = state_store.data.get("forecast", {})
    today_fc = forecasts.get(today_ds, {}) if isinstance(forecasts, dict) else {}
    calibrated = today_fc.get("calibrated", {}) if isinstance(today_fc, dict) else {}
    expected = float(calibrated.get("expected_kwh", 0) or 0)

    # --- Mindestreserve langsam aus dem realen SOC bei PV-Übernahme lernen.
    old_reserve = _learned_morning_reserve_soc()
    new_reserve = old_reserve
    target_reached_close = abs(float(soc_0500) - float(target_0500)) <= 5.0
    if target_reached_close:
        if float(soc_cover) < old_reserve - 0.5:
            new_reserve = min(35.0, old_reserve + 1.0)
            reserve_reason = f"Reserve +1 %-Pkt: bei PV-Deckung nur {soc_cover:.0f}%"
        elif float(soc_cover) > old_reserve + 4.0 and old_reserve > 5.0:
            new_reserve = max(5.0, old_reserve - 1.0)
            reserve_reason = f"Reserve -1 %-Pkt: bei PV-Deckung noch {soc_cover:.0f}%"
        else:
            reserve_reason = f"Reserve passt ({soc_cover:.0f}% bei PV-Deckung)"
    else:
        reserve_reason = f"Reserve nicht bewertet: 05:00-SOC {soc_0500:.0f}% statt Ziel {float(target_0500):.0f}%"

    # --- Zeitpunkt getrennt lernen. Grundlage ist der zur Nacht gespeicherte Plan.
    predicted_cover = battery_learning.get("planned_cover_time")
    adjusted_cover = battery_learning.get("planned_adjusted_cover_time")
    predicted_min = _time_to_minutes(predicted_cover)
    adjusted_min = _time_to_minutes(adjusted_cover)
    actual_min = cover.hour * 60 + cover.minute
    try:
        old_time_offset = float(learning.get("cover_time_offset_minutes", 0.0) or 0.0)
    except (TypeError, ValueError):
        old_time_offset = 0.0
    old_time_offset = max(-30.0, min(120.0, old_time_offset))
    new_time_offset = old_time_offset
    time_error = None
    if adjusted_min is not None:
        time_error = float(actual_min - adjusted_min)
        # Einzelne Ausreißer dürfen den Plan nicht sprunghaft verändern.
        step = max(-5.0, min(5.0, time_error * 0.25))
        if abs(time_error) < 4.0:
            step = 0.0
        new_time_offset = max(-30.0, min(120.0, old_time_offset + step))
        if abs(step) >= 0.1:
            time_reason = f"PV-Zeitpuffer {new_time_offset:+.0f} min ({step:+.1f} min gelernt)"
        else:
            time_reason = f"PV-Zeitpuffer bleibt {old_time_offset:+.0f} min"
    else:
        time_reason = "kein geplanter PV-Übernahmepunkt zum Zeitlernen"

    # --- Energiefehler getrennt lernen. Die geplante Energiemenge ist OHNE
    # den bestehenden Sicherheitsaufschlag gespeichert, damit der Puffer nicht
    # gegen sich selbst lernt.
    planned_need = battery_learning.get("planned_morning_predicted_need_kwh")
    try:
        planned_need_f = float(planned_need) if planned_need is not None else None
    except (TypeError, ValueError):
        planned_need_f = None
    try:
        old_energy_buffer = float(learning.get("energy_buffer_soc", 0.0) or 0.0)
    except (TypeError, ValueError):
        old_energy_buffer = 0.0
    old_energy_buffer = max(0.0, min(15.0, old_energy_buffer))
    new_energy_buffer = old_energy_buffer
    energy_error = None
    if planned_need_f is not None:
        energy_error = float(net_need) - planned_need_f
        if energy_error > 0.08:
            error_soc = energy_error / BATTERY_CAPACITY_KWH * 100.0
            increase = min(2.0, max(0.5, error_soc * 0.5))
            new_energy_buffer = min(15.0, old_energy_buffer + increase)
            energy_reason = f"Energiepuffer +{increase:.1f} auf {new_energy_buffer:.1f}%"
        elif energy_error < -0.20 and old_energy_buffer > 0.0:
            decrease = min(0.5, old_energy_buffer)
            new_energy_buffer = max(0.0, old_energy_buffer - decrease)
            energy_reason = f"Energiepuffer -{decrease:.1f} auf {new_energy_buffer:.1f}%"
        else:
            energy_reason = f"Energiepuffer bleibt {old_energy_buffer:.1f}%"
    else:
        energy_reason = "kein prognostizierter Morgenbedarf zum Energielernen"

    old_need = float(learning.get("learned_net_need_kwh", 1.55) or 1.55)
    learned_need = 0.75 * old_need + 0.25 * float(net_need)
    reason = f"{reserve_reason} · {time_reason} · {energy_reason}"
    sample = {
        "date": today_ds,
        "cover_time": cover.strftime("%H:%M"),
        "predicted_cover_time": predicted_cover,
        "adjusted_cover_time": adjusted_cover,
        "cover_time_error_minutes": None if time_error is None else round(time_error, 1),
        "net_need_kwh": round(float(net_need), 2),
        "predicted_net_need_kwh": None if planned_need_f is None else round(planned_need_f, 2),
        "energy_error_kwh": None if energy_error is None else round(energy_error, 2),
        "soc_0500": round(float(soc_0500), 1),
        "target_0500": round(float(target_0500), 1),
        "soc_cover": round(float(soc_cover), 1),
        "forecast_kwh": round(expected, 1),
        "reserve_before": round(old_reserve, 1),
        "reserve_after": round(new_reserve, 1),
        "time_offset_before_minutes": round(old_time_offset, 1),
        "time_offset_after_minutes": round(new_time_offset, 1),
        "energy_buffer_before_soc": round(old_energy_buffer, 1),
        "energy_buffer_after_soc": round(new_energy_buffer, 1),
    }
    recent = list(learning.get("recent_samples") or [])
    recent.append(sample)
    recent = recent[-21:]

    learning["desired_cover_soc"] = round(new_reserve, 1)
    learning["learned_net_need_kwh"] = round(learned_need, 2)
    learning["cover_time_offset_minutes"] = round(new_time_offset, 1)
    learning["energy_buffer_soc"] = round(new_energy_buffer, 1)
    learning["samples"] = int(learning.get("samples") or 0) + 1
    learning["last_sample_date"] = today_ds
    learning["last_cover_time"] = cover.strftime("%H:%M")
    learning["last_cover_date"] = today_ds
    learning["last_predicted_cover_time"] = predicted_cover
    learning["last_adjusted_cover_time"] = adjusted_cover
    learning["last_cover_time_error_minutes"] = None if time_error is None else round(time_error, 1)
    learning["last_net_need_kwh"] = round(float(net_need), 2)
    learning["last_predicted_net_need_kwh"] = None if planned_need_f is None else round(planned_need_f, 2)
    learning["last_energy_error_kwh"] = None if energy_error is None else round(energy_error, 2)
    learning["last_soc_0500"] = round(float(soc_0500), 1)
    learning["last_soc_0500_date"] = today_ds
    learning["last_soc_cover"] = round(float(soc_cover), 1)
    learning["last_forecast_kwh"] = round(expected, 1)
    learning["last_adjustment"] = reason
    learning["recent_samples"] = recent
    state_store.save()
    LOG.info(
        "Morgenlernen %s: %s · Netto %.2f kWh · Reserve %.1f -> %.1f%% · Zeitoffset %.1f -> %.1f min · Energiepuffer %.1f -> %.1f%%",
        today_ds, reason, net_need, old_reserve, new_reserve, old_time_offset, new_time_offset, old_energy_buffer, new_energy_buffer,
    )

def _counter_delta_from_history(entity_id: str, start: datetime, end: datetime) -> float | None:
    series = _history_numeric_series(entity_id, start, end, 1.0)
    if not series:
        return None
    a = _series_value_at(series, start)
    b = _series_value_at(series, end)
    if a is None or b is None:
        return None
    delta = float(b) - float(a)
    if delta < -0.1:
        return None
    return max(0.0, delta)


def _power_value_w(entity_id: str) -> float | None:
    value = state_value(entity_id)
    if value is None:
        return None
    unit = str(state_unit(entity_id) or "").strip().lower()
    if unit == "kw":
        return float(value) * 1000.0
    if unit in {"w", "watt", ""}:
        return float(value)
    return None


def _parse_local_stamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=local_tz())
        return dt.astimezone(local_tz())
    except Exception:
        return None


def _counter_live_power_w(key: str, current_kwh: float | None, now: datetime, stale_minutes: int = 8) -> float | None:
    """Schätzt die aktuelle Leistung aus einem kumulativen Tages-kWh-Zähler.

    Die Klima-Sensoren liefern keinen Watt-Wert. Aus den realen Zähleranstiegen
    wird deshalb die mittlere Leistung zwischen zwei Änderungen berechnet. Bleibt
    der Zähler länger als die Recorder-/Sensor-Taktung unverändert, fällt der
    Live-Wert auf 0 W zurück.
    """
    if current_kwh is None:
        return None
    current = max(0.0, float(current_kwh))
    changed = False
    with state_store.lock:
        tracking = state_store.data.setdefault("consumer_tracking", {}).setdefault("counter_rates", {})
        item = tracking.setdefault(key, {})
        today_ds = now.date().isoformat()
        last_value = item.get("last_value")
        last_change = _parse_local_stamp(item.get("last_change_at"))
        if item.get("date") != today_ds or last_value is None or current < float(last_value) - 0.01:
            item.update({"date": today_ds, "last_value": current, "last_change_at": now.isoformat(), "live_w": 0.0})
            changed = True
        elif current > float(last_value) + 0.00005:
            reference = last_change or now
            seconds = max(1.0, (now - reference).total_seconds())
            estimate = (current - float(last_value)) * 3_600_000.0 / seconds
            # Plausibilitätsgrenze für die kleinen Split-Klimageräte.
            item["live_w"] = round(max(0.0, min(5000.0, estimate)), 1)
            item["last_value"] = current
            item["last_change_at"] = now.isoformat()
            changed = True
        else:
            if last_change and (now - last_change).total_seconds() > stale_minutes * 60 and float(item.get("live_w") or 0.0) != 0.0:
                item["live_w"] = 0.0
                changed = True
        live_w = float(item.get("live_w") or 0.0)
        if changed:
            state_store.save()
    return live_w


def _integrate_power_series_kwh(series: list[tuple[datetime, float]], start: datetime, end: datetime) -> float | None:
    if not series or end <= start:
        return None
    points = [(t, max(0.0, float(v))) for t, v in series if t <= end]
    if not points:
        return None
    current = _series_value_at(points, start)
    if current is None:
        current = points[0][1]
        cursor = max(start, points[0][0])
    else:
        cursor = start
    wh = 0.0
    for stamp, value in points:
        if stamp <= cursor:
            current = value
            continue
        if stamp > end:
            break
        wh += max(0.0, current) * (stamp - cursor).total_seconds() / 3600.0
        cursor = stamp
        current = value
    if cursor < end:
        wh += max(0.0, current) * (end - cursor).total_seconds() / 3600.0
    return wh / 1000.0


def _power_energy_today_kwh(key: str, entity_id: str, current_w: float | None, now: datetime) -> float | None:
    """Integriert einen reinen Watt-Sensor zu einem persistenten Tageswert."""
    if current_w is None:
        return None
    today_ds = now.date().isoformat()
    with state_store.lock:
        integrators = state_store.data.setdefault("consumer_tracking", {}).setdefault("power_integrators", {})
        item = integrators.setdefault(key, {})
        item_date = item.get("date")
        last_at = _parse_local_stamp(item.get("last_at"))
        last_w = item.get("last_w")
        need_bootstrap = item_date != today_ds or last_at is None or last_w is None or (now - last_at).total_seconds() > 300

    if need_bootstrap:
        start = datetime.combine(now.date(), datetime.min.time(), tzinfo=local_tz())
        series = _history_numeric_series(entity_id, start, now, 1.0)
        history_kwh = _integrate_power_series_kwh(series, start, now)
        with state_store.lock:
            integrators = state_store.data.setdefault("consumer_tracking", {}).setdefault("power_integrators", {})
            item = integrators.setdefault(key, {})
            item.update({
                "date": today_ds,
                "day_kwh": round(max(0.0, float(history_kwh or 0.0)), 4),
                "last_at": now.isoformat(),
                "last_w": max(0.0, float(current_w)),
            })
            state_store.save()
            return float(item["day_kwh"])

    with state_store.lock:
        integrators = state_store.data.setdefault("consumer_tracking", {}).setdefault("power_integrators", {})
        item = integrators.setdefault(key, {})
        previous_at = _parse_local_stamp(item.get("last_at")) or now
        previous_w = max(0.0, float(item.get("last_w") or 0.0))
        seconds = max(0.0, min(300.0, (now - previous_at).total_seconds()))
        day_kwh = max(0.0, float(item.get("day_kwh") or 0.0))
        day_kwh += ((previous_w + max(0.0, float(current_w))) / 2.0) * seconds / 3_600_000.0
        item.update({"date": today_ds, "day_kwh": round(day_kwh, 4), "last_at": now.isoformat(), "last_w": max(0.0, float(current_w))})
        state_store.save()
        return float(item["day_kwh"])


def _climate_unknown_is_active(entity_id: str) -> bool:
    value = str(state_text(entity_id) or "").strip().lower()
    return value not in {"", "off", "unknown", "unavailable", "none"}


def _update_standby_learning(now: datetime, live: dict[str, Any]) -> None:
    """Lernt einen separaten Standby-/Restlastwert aus sauberen 5-Minuten-Fenstern.

    Messbare Großverbraucher werden abgezogen. Wohnzimmer- und Schlafzimmerklima
    besitzen keinen Energiezähler; solange eine davon eingeschaltet ist, wird das
    aktuelle Zeitfenster bewusst nicht gelernt. Hohe Restlasten werden ebenfalls
    verworfen, damit z. B. Waschmaschine/Trockner den Standbywert nicht aufblasen.
    """
    bucket_minute = (now.minute // 5) * 5
    bucket = now.replace(minute=bucket_minute, second=0, microsecond=0).isoformat()
    with state_store.lock:
        standby = state_store.data.setdefault("standby_learning", {})
        if standby.get("last_sample_bucket") == bucket:
            return
        standby["last_sample_bucket"] = bucket

    if _climate_unknown_is_active(ENTITIES["climate_living"]) or _climate_unknown_is_active(ENTITIES["climate_bedroom"]):
        with state_store.lock:
            state_store.data.setdefault("standby_learning", {})["last_reason"] = "Messfenster ausgelassen: Klima Wohn-/Schlafzimmer an"
            state_store.save()
        return

    house = live.get("house_power_w")
    if house is None:
        return
    wp_unit = str(live.get("wp_power_unit") or "").strip().lower()
    wp_value = live.get("wp_power_value")
    if wp_unit not in {"w", "kw"} and wp_value is not None and float(wp_value or 0.0) > 0.02:
        with state_store.lock:
            state_store.data.setdefault("standby_learning", {})["last_reason"] = "Messfenster ausgelassen: Wärmepumpe aktiv"
            state_store.save()
        return
    wp_w = 0.0
    if wp_unit == "w":
        wp_w = max(0.0, float(wp_value or 0.0))
    elif wp_unit == "kw":
        wp_w = max(0.0, float(wp_value or 0.0) * 1000.0)

    known = sum(max(0.0, float(live.get(k) or 0.0)) for k in (
        "wallbox_power_w", "dishwasher_power_w", "climate_office_live_w", "climate_kids_live_w"
    )) + wp_w
    residual = max(0.0, float(house) - known)
    if residual < 40.0 or residual > 1800.0:
        with state_store.lock:
            state_store.data.setdefault("standby_learning", {})["last_reason"] = f"Messfenster ausgelassen: Restlast {residual:.0f} W nicht typisch"
            state_store.save()
        return

    with state_store.lock:
        standby = state_store.data.setdefault("standby_learning", {})
        recent = list(standby.get("recent_samples") or [])
        recent.append({"at": now.isoformat(), "w": round(residual, 1)})
        cutoff = now - timedelta(days=7)
        clean = []
        for row in recent[-2200:]:
            stamp = _parse_local_stamp(row.get("at")) if isinstance(row, dict) else None
            if stamp and stamp >= cutoff:
                clean.append(row)
        values = sorted(float(row.get("w") or 0.0) for row in clean if float(row.get("w") or 0.0) > 0)
        estimate = None
        if values:
            index = min(len(values) - 1, max(0, int(round((len(values) - 1) * 0.20))))
            estimate = values[index]
        standby["recent_samples"] = clean
        standby["samples"] = len(clean)
        standby["estimate_w"] = None if estimate is None else round(estimate)
        standby["last_reason"] = f"Sauberes Messfenster: {residual:.0f} W Restlast"
        state_store.save()


def day_load_learning_tick(now: datetime) -> None:
    """Lernt die planungsrelevante Grundlast sehr langsam aus dem Tagesergebnis.

    Sonderlasten wie Klima, Waschmaschine/Trockner und die nicht messbare
    Spülmaschine dürfen den Wert nicht abrupt hochziehen. Deshalb wird nicht der
    rohe Tagesverbrauch übernommen. Wenn der Speicher tagsüber 100 % erreicht
    hat, gilt eine spätere Netzspitze ausdrücklich NICHT als Beleg für zu wenig
    Nachtladung. Nur an Tagen ohne Voll-SOC und mit deutlichem Netzbezug steigt
    die Grundlast um 0,01 kW. Sie kann ebenso langsam wieder sinken.
    """
    if now.hour != 23 or now.minute < 50:
        return
    learning = state_store.data.setdefault("day_load_learning", {})
    today_ds = now.date().isoformat()
    if learning.get("last_sample_date") == today_ds:
        return
    start = datetime.combine(now.date(), datetime.min.time(), tzinfo=local_tz()) + timedelta(hours=5)
    end = now

    pv = _counter_delta_from_history(ENTITIES["pv_day"], start, end)
    net = _counter_delta_from_history(ENTITIES["net_import_day"], start, end)
    export = _counter_delta_from_history(ENTITIES["grid_export_day"], start, end)
    bat_in = _counter_delta_from_history(ENTITIES["battery_charge_day"], start, end)
    bat_out = _counter_delta_from_history(ENTITIES["battery_discharge_day"], start, end)
    wallbox = _counter_delta_from_history(ENTITIES["wallbox_day"], start, end)
    wp = _counter_delta_from_history(ENTITIES["wp_day"], start, end)
    soc_series = _history_numeric_series(ENTITIES["battery_soc"], start, end, 1.0)
    if any(v is None for v in (pv, net, export, bat_in, bat_out, wallbox, wp)) or not soc_series:
        learning["last_sample_date"] = today_ds
        learning["last_adjustment"] = "Tageslernen übersprungen: Energiedaten unvollständig"
        state_store.save()
        return

    house = max(0.0, float(pv) + float(net) + float(bat_out) - float(export) - float(bat_in))
    observed = max(0.0, house - float(wallbox) - float(wp))
    battery_max = max(v for _, v in soc_series)
    battery_end = _series_value_at(soc_series, end)
    reached_full = battery_max >= 99.0
    old_base = max(0.55, min(1.30, float(settings_store.data.get("day_house_base_kw", 0.85) or 0.85)))
    new_base = old_base
    reserve = _learned_morning_reserve_soc()

    if reached_full:
        reason = f"Grundlast bleibt {old_base:.2f} kW: Speicher wurde tagsüber voll"
    elif float(net) >= 1.0:
        new_base = min(1.30, old_base + 0.01)
        reason = f"Grundlast +0,01 kW: {float(net):.2f} kWh Netzbezug ohne Voll-SOC"
    elif float(net) <= 0.20 and battery_end is not None and float(battery_end) >= reserve + 8.0:
        new_base = max(0.55, old_base - 0.01)
        reason = f"Grundlast -0,01 kW: kaum Netzbezug und ausreichend Rest-SOC"
    else:
        reason = f"Grundlast bleibt {old_base:.2f} kW: Tagesergebnis im Toleranzbereich"

    sample = {
        "date": today_ds,
        "observed_kwh": round(observed, 2),
        "grid_import_kwh": round(float(net), 2),
        "battery_max_soc": round(float(battery_max), 1),
        "base_before_kw": round(old_base, 2),
        "base_after_kw": round(new_base, 2),
    }
    recent = list(learning.get("recent_samples") or [])
    recent.append(sample)
    recent = recent[-21:]
    learning.update({
        "base_kw": round(new_base, 2),
        "samples": int(learning.get("samples") or 0) + 1,
        "last_sample_date": today_ds,
        "last_observed_kwh": round(observed, 2),
        "last_grid_import_kwh": round(float(net), 2),
        "last_battery_max_soc": round(float(battery_max), 1),
        "last_adjustment": reason,
        "recent_samples": recent,
    })
    if abs(new_base - old_base) >= 0.001:
        with settings_store.lock:
            settings_store.data["day_house_base_kw"] = round(new_base, 2)
            settings_store.save()
    state_store.save()
    LOG.info("Tages-Grundlastlernen %s: %s · beobachtet %.2f kWh", today_ds, reason, observed)

def evening_learning_tick(now: datetime) -> None:
    """Lernt, wie viel Speicherenergie typischerweise vom PV-Ende bis 00:00 gebraucht wird."""
    learning = state_store.data.setdefault("evening_learning", {})
    today_ds = now.date().isoformat()
    pv_power = state_value(ENTITIES["pv_power"], 0.0) or 0.0
    soc = state_value(ENTITIES["battery_soc"])
    if soc is None:
        return
    # Sobald nach 17 Uhr praktisch keine PV mehr kommt, Start-SOC merken.
    if now.hour >= 17 and pv_power < 200 and learning.get("sample_date") != today_ds:
        learning["sample_date"] = today_ds
        learning["start_soc"] = soc
        learning["start_time"] = now.isoformat()
        state_store.save()
        return
    # Kurz vor Mitternacht aus dem SOC-Abfall die benötigte Abendenergie ableiten.
    if now.hour == 23 and now.minute >= 55 and learning.get("sample_date") == today_ds and learning.get("start_soc") is not None:
        if learning.get("completed_date") == today_ds:
            return
        used = max(0.0, (float(learning["start_soc"]) - float(soc)) * BATTERY_CAPACITY_KWH / 100.0)
        old = float(learning.get("reserve_kwh") or settings_store.data.get("evening_reserve_start_kwh", 2.5))
        margin = float(settings_store.data.get("evening_reserve_margin_kwh", 0.5))
        empty_penalty = 0.75 if float(soc) <= 1.0 else 0.0
        target = max(1.0, min(5.5, used + margin + empty_penalty))
        smoothed = 0.75 * old + 0.25 * target
        learning["reserve_kwh"] = round(smoothed, 2)
        learning["last_usage_kwh"] = round(used, 2)
        learning["samples"] = int(learning.get("samples") or 0) + 1
        learning["completed_date"] = today_ds
        learning["last_adjustment"] = f"Abendreserve {smoothed:.2f} kWh · zuletzt {used:.2f} kWh Verbrauch"
        state_store.save()


def battery_learning_tick(now: datetime) -> None:
    """Speichert den echten 05:00-SOC auch dann, wenn die exakte Minute verpasst wurde."""
    if now.hour < 5:
        return
    learning = state_store.data.setdefault("battery_learning", {})
    today_ds = now.date().isoformat()
    if learning.get("soc_0500_date") == today_ds:
        return

    point = datetime.combine(now.date(), datetime.min.time(), tzinfo=local_tz()) + timedelta(hours=5)
    soc = None
    # Innerhalb der 05:00-Minute ist der Live-Wert passend. Bei einem späteren
    # Catch-up wird der historische Wert exakt um 05:00 rekonstruiert.
    if now.hour == 5 and now.minute == 0:
        soc = state_value(ENTITIES["battery_soc"])
    else:
        hist_start = point - timedelta(minutes=10)
        hist_end = min(now, point + timedelta(minutes=15))
        series = _history_numeric_series(ENTITIES["battery_soc"], hist_start, hist_end, 1.0)
        soc = _series_value_at(series, point) if series else None
        if soc is None and now.hour == 5:
            soc = state_value(ENTITIES["battery_soc"])

    learning["soc_0500"] = soc
    learning["soc_0500_date"] = today_ds
    learning["last_soc_0500_date"] = today_ds
    if str(learning.get("planned_0500_date") or "") == today_ds:
        learning["target_soc_0500"] = learning.get("planned_0500_target_soc")
    else:
        learning["target_soc_0500"] = learning.get("last_target_soc")

    start_soc = learning.get("night_start_soc")
    active_seconds = float(learning.get("active_seconds") or 0.0)
    old_kw = float(learning.get("effective_charge_kw") or BATTERY_SAFE_CHARGE_KW)

    if soc is not None and start_soc is not None and active_seconds >= 300:
        gained_pct = max(0.0, float(soc) - float(start_soc))
        gained_kwh = BATTERY_CAPACITY_KWH * gained_pct / 100.0
        if gained_kwh > 0.02:
            measured_kw = gained_kwh / (active_seconds / 3600.0)
            measured_kw = max(0.5, min(2.2, measured_kw))
            smoothed = 0.70 * old_kw + 0.30 * measured_kw
            learning["effective_charge_kw"] = round(smoothed, 3)
            learning["last_measured_charge_kw"] = round(measured_kw, 3)
            learning["last_adjustment"] = f"Netto-Laderate {smoothed:.2f} kW · letzte Nacht {measured_kw:.2f} kW"

        # Zusätzlich lernt die Planung, ob sie schlicht zu spät angefangen hat.
        # Bei einem verfehlten Ziel kommen 5 Minuten Vorlauf hinzu (max. 30).
        # Ist das Ziel wieder erreicht, wird ein zuvor erhöhter Puffer nur sehr
        # langsam bis zum Basiswert von 10 Minuten zurückgenommen.
        try:
            old_buffer = int(round(float(learning.get("start_buffer_minutes", 10) or 10)))
        except (TypeError, ValueError):
            old_buffer = 10
        old_buffer = max(10, min(30, old_buffer))
        new_buffer = old_buffer
        try:
            target_value = float(learning.get("target_soc_0500"))
        except (TypeError, ValueError):
            target_value = None
        if target_value is not None:
            miss = target_value - float(soc)
            if miss >= 1.0:
                new_buffer = min(30, old_buffer + 5)
                buffer_reason = f"Ladepuffer +5 min: 05:00-Ziel um {miss:.0f} %-Pkt verfehlt"
            elif float(soc) >= target_value and old_buffer > 10:
                new_buffer = max(10, old_buffer - 1)
                buffer_reason = f"Ladepuffer -1 min: 05:00-Ziel erreicht"
            else:
                buffer_reason = f"Ladepuffer bleibt {old_buffer} min"
            learning["start_buffer_minutes"] = new_buffer
            learning["last_buffer_adjustment"] = buffer_reason

    learning["active_started_at"] = None
    learning["active_seconds"] = 0.0
    state_store.save()


def _time_today(hhmm: str, day: date) -> datetime | None:
    try:
        hh, mm = [int(x) for x in str(hhmm).split(":", 1)]
        return datetime.combine(day, datetime.min.time(), tzinfo=local_tz()).replace(hour=hh, minute=mm)
    except Exception:
        return None


def _scheduled_notification_complete(reason: str, today_key: str) -> bool:
    """Bestätigt die Zustellung aller aktivierten geplanten Push-Ziele."""
    if not bool(settings_store.data.get("notifications_enabled", True)):
        return True
    notices = state_store.data.get("last_notifications", {})
    if notices.get(reason) != today_key:
        return False
    if bool(settings_store.data.get("partner_notifications_enabled", True)):
        partner_service = str(settings_store.data.get("partner_notify_service", "") or "").strip()
        if partner_service and notices.get("partner_" + reason) != today_key:
            return False
    return True


def scheduler_loop() -> None:
    LOG.info("Scheduler gestartet")
    startup_forecast_done = False
    history_seeded = False
    last_minute_key = None
    while True:
        try:
            now = now_local()
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            if not history_seeded:
                try:
                    seed_live_pv_samples_from_history()
                except Exception:
                    LOG.exception("Live-PV-History Seed fehlgeschlagen")
                history_seeded = True
            if not startup_forecast_done:
                try:
                    if now.hour >= 5:
                        actions = state_store.data.get("night_actions", {})
                        if any(bool(actions.get(k)) for k in ("battery_safe_charge", "warmwater", "wallbox_fast")):
                            enforce_0500_cutoff()
                    archive_current_forecasts()
                    if forecast_cache_usable():
                        refresh_weather_only(reason="startup", notify=False)
                    else:
                        forecast_run(reason="startup", notify=False)
                except Exception as exc:
                    LOG.exception("Startup-Prognose fehlgeschlagen")
                    with state_store.lock:
                        state_store.data["last_error"] = str(exc)
                        state_store.save()
                startup_forecast_done = True
            if minute_key != last_minute_key:
                last_minute_key = minute_key
                ensure_phase1_on()
                record_live_pv_sample(now)
                today_key = now.date().isoformat()
                main_time = str(settings_store.data.get("forecast_main_time", "20:00"))
                morning_time = str(settings_store.data.get("forecast_morning_time", "07:00"))
                main_dt = _time_today(main_time, now.date())
                morning_dt = _time_today(morning_time, now.date())
                main_gemini_dt = main_dt - timedelta(minutes=5) if main_dt else None
                morning_gemini_dt = morning_dt - timedelta(minutes=5) if morning_dt else None
                scheduled = state_store.data.setdefault("scheduled_runs", {})
                for key in ("morning_gemini_date", "morning_date", "main_gemini_date", "main_date", "cutoff_date", "actual_date"):
                    scheduled.setdefault(key, None)
                notices = state_store.data.get("last_notifications", {})
                if notices.get("main") == today_key:
                    scheduled["main_date"] = today_key
                if notices.get("morning") == today_key:
                    scheduled["morning_date"] = today_key

                # Gemini läuft fünf Minuten vor den sichtbaren Push-Terminen. Der
                # Morgenlauf wird nur bis 09:00 nachgeholt, damit ein späteres Update
                # nicht am Nachmittag noch einen 07:00-Push erzeugt.
                morning_catchup_end = morning_dt + timedelta(hours=2) if morning_dt else None
                if (
                    morning_gemini_dt is not None and morning_catchup_end is not None
                    and morning_gemini_dt <= now < morning_catchup_end
                    and scheduled.get("morning_gemini_date") != today_key
                ):
                    try:
                        forecast_run(reason="morning", notify=False)
                        with state_store.lock:
                            state_store.data.setdefault("scheduled_runs", {})["morning_gemini_date"] = today_key
                            state_store.save()
                        LOG.info("Gemini-Morgenprognose ausgeführt: %s", now.strftime("%H:%M"))
                    except Exception:
                        LOG.exception("Gemini-Morgenprognose fehlgeschlagen")

                if (
                    morning_dt is not None and morning_catchup_end is not None
                    and morning_dt <= now < morning_catchup_end
                    and scheduled.get("morning_date") != today_key
                ):
                    try:
                        forecasts = state_store.data.get("forecast", {})
                        plan = state_store.data.get("plan") or rebuild_plan_from_saved_forecast()
                        send_plan_notification("morning", {}, plan, forecasts if isinstance(forecasts, dict) else {})
                        if not _scheduled_notification_complete("morning", today_key):
                            raise RuntimeError("07:00-Push noch nicht an alle aktivierten Geräte zugestellt")
                        with state_store.lock:
                            state_store.data.setdefault("scheduled_runs", {})["morning_date"] = today_key
                            state_store.save()
                        LOG.info("Geplanter 07:00-Push ausgeführt/nachgeholt: %s", now.strftime("%H:%M"))
                    except Exception:
                        LOG.exception("07:00 Energieplan-Push fehlgeschlagen")

                # Abends gleicher Ablauf: 19:55 Gemini, 20:00 Push. Ein verpasster
                # Abendtermin wird bis Mitternacht nachgeholt, aber nie doppelt.
                if main_gemini_dt is not None and now >= main_gemini_dt and scheduled.get("main_gemini_date") != today_key:
                    try:
                        archive_current_forecasts()
                        forecast_run(reason="main", notify=False)
                        with state_store.lock:
                            state_store.data.setdefault("scheduled_runs", {})["main_gemini_date"] = today_key
                            state_store.save()
                        LOG.info("Gemini-Abendprognose ausgeführt: %s", now.strftime("%H:%M"))
                    except Exception:
                        LOG.exception("Gemini-Abendprognose fehlgeschlagen")

                if main_dt is not None and now >= main_dt and scheduled.get("main_date") != today_key:
                    try:
                        forecasts = state_store.data.get("forecast", {})
                        plan = state_store.data.get("plan") or rebuild_plan_from_saved_forecast()
                        send_plan_notification("main", {}, plan, forecasts if isinstance(forecasts, dict) else {})
                        if not _scheduled_notification_complete("main", today_key):
                            raise RuntimeError("20:00-Push noch nicht an alle aktivierten Geräte zugestellt")
                        with state_store.lock:
                            state_store.data.setdefault("scheduled_runs", {})["main_date"] = today_key
                            state_store.save()
                        LOG.info("Geplanter 20:00-Push ausgeführt/nachgeholt: %s", now.strftime("%H:%M"))
                    except Exception:
                        LOG.exception("20:00 Energieplan-Push fehlgeschlagen")

                # 05:00 ist eine harte Sicherheitsgrenze. Auch ein Neustart oder
                # eine blockierte Scheduler-Minute darf Nachtverbraucher nicht
                # über 05:00 hinaus laufen lassen.
                cutoff_dt = _time_today("05:00", now.date())
                if cutoff_dt is not None and cutoff_dt <= now < cutoff_dt + timedelta(hours=1) and scheduled.get("cutoff_date") != today_key:
                    enforce_0500_cutoff()
                    with state_store.lock:
                        state_store.data["night_override"] = "auto"
                        state_store.data["night_target_override_soc"] = None
                        state_store.data.setdefault("scheduled_runs", {})["cutoff_date"] = today_key
                        state_store.save()

                actual_dt = _time_today("23:45", now.date())
                if actual_dt is not None and now >= actual_dt and scheduled.get("actual_date") != today_key:
                    try:
                        record_actual_today()
                        with state_store.lock:
                            state_store.data.setdefault("scheduled_runs", {})["actual_date"] = today_key
                            state_store.save()
                    except Exception:
                        LOG.exception("PV-Istwert konnte nicht archiviert werden")

                # Jede Automatik läuft bewusst in einem eigenen Fehlerraum. Ein
                # Defekt in Nachtladen oder Lernen darf die PV-Wallbox bzw.
                # Warmwasser nicht erneut unbemerkt mitreißen.
                automation_ticks = (
                    ("Abendlernen", evening_learning_tick),
                    # Die Nachtladung muss im echten Scheduler laufen. Sie darf
                    # nicht nur als Funktion vorhanden sein, sonst bleibt der
                    # Akku trotz 0 % und aktivierter Automatik unangetastet.
                    ("Nacht-Speicher", automatic_battery),
                    ("Speicherlernen", battery_learning_tick),
                    ("Morgenlernen", morning_learning_tick),
                    ("Hauslastlernen", day_load_learning_tick),
                    ("Nacht-Wallbox", automatic_night_wallbox),
                    ("Warmwasser", automatic_warmwater),
                )
                for tick_name, tick_fn in automation_ticks:
                    try:
                        tick_fn(now)
                    except Exception:
                        LOG.exception("%s-Tick fehlgeschlagen", tick_name)
        except Exception:
            LOG.exception("Scheduler-Fehler")
        time.sleep(1)


def next_action_summary(plan: dict[str, Any], live: dict[str, Any], live_pv: dict[str, Any]) -> dict[str, Any]:
    now = now_local()
    if live.get("safe_charge") == "on":
        return {"icon": "🔋", "label": "Speicher lädt", "detail": "Ziel bis 05:00"}
    if live.get("wallbox_mode") == "fast":
        target = plan.get("wallbox", {}).get("night_target_soc", "–")
        return {"icon": "🚗", "label": "Schnellladen läuft", "detail": f"Nachtziel {target}% · spätestens 05:00"}
    if live.get("warmwater") == "on":
        ww = plan.get("warmwater", {})
        return {"icon": "🚿", "label": "Warmwasser läuft", "detail": f"bis {ww.get('end_time', '–')}"}

    candidates: list[tuple[datetime, dict[str, Any]]] = []
    today_ds = now.date().isoformat()
    # Geplantes Warmwasser heute.
    ww = plan.get("today_warmwater", {}) if now.hour >= 5 else plan.get("warmwater", {})
    try:
        if str(ww.get("date") or today_ds) == today_ds and ww.get("start_time"):
            hh, mm = map(int, str(ww["start_time"]).split(":"))
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt > now:
                candidates.append((dt, {"icon": "🚿", "label": f"Warmwasser {ww['start_time']}", "detail": f"bis {ww.get('end_time','–')}"}))
    except Exception:
        pass
    # Speicherstart ist nur in der Nacht relevant.
    b = plan.get("battery", {})
    try:
        if now.hour < 5 and b.get("start_time") not in {None, "–", "nicht nötig"}:
            hh, mm = map(int, str(b["start_time"]).split(":"))
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt > now:
                candidates.append((dt, {"icon": "🔋", "label": f"Speicherstart {b['start_time']}", "detail": f"Ziel {b.get('target_soc','–')}% um 05:00"}))
    except Exception:
        pass
    pvc = plan.get("pv_charging", {})
    try:
        if plan.get("pv_charging", {}).get("car_present") and float(pvc.get("budget", {}).get("available_car_kwh", 0) or 0) > 0 and pvc.get("start_time"):
            hh, mm = map(int, str(pvc["start_time"]).split(":"))
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt > now:
                candidates.append((dt, {"icon": "☀️", "label": f"PV-Ladefenster {pvc['start_time']}", "detail": f"ca. {pvc.get('budget',{}).get('available_car_kwh','–')} kWh fürs Auto"}))
    except Exception:
        pass
    if candidates:
        return sorted(candidates, key=lambda x: x[0])[0][1]
    if live_pv:
        return {"icon": "☀️", "label": "PV-Verlauf beobachten", "detail": f"Rest heute ca. {live_pv.get('remaining_adjusted_kwh','–')} kWh"}
    return {"icon": "✓", "label": "Keine Aktion geplant", "detail": "Automatik überwacht weiter"}


def pv_status_payload() -> dict[str, Any]:
    """Kleine, ungecachte Statusantwort für den laufenden PV-Timer."""
    with state_store.lock:
        pv_control_raw = dict(state_store.data.get("pv_surplus", {}))
    candidate_since = pv_control_raw.get("candidate_since")
    status_since = pv_control_raw.get("status_since")
    charging_since = pv_control_raw.get("charging_since")
    phase_since = pv_control_raw.get("phase_since")
    now = now_local()
    candidate_elapsed = _seconds_since_iso(candidate_since, now)
    status_elapsed = _seconds_since_iso(status_since, now)
    charging_elapsed = _seconds_since_iso(charging_since, now)
    phase_elapsed = _seconds_since_iso(phase_since, now)
    return {
        "time": now_local().isoformat(),
        "pv_surplus_control": {
            "candidate_phases": pv_control_raw.get("candidate_phases"),
            "candidate_elapsed_seconds": round(candidate_elapsed),
            # Echte Zeitstempel sind auch nach Browser- oder Add-on-Neustart
            # dieselbe Kennung und somit eine belastbare Timerbasis.
            "candidate_token": str(candidate_since or ""),
            "status_key": pv_control_raw.get("status_key"),
            "status_elapsed_seconds": round(status_elapsed),
            "status_token": str(status_since or ""),
            "charging_elapsed_seconds": round(charging_elapsed),
            "charging_token": str(charging_since or ""),
            "phase_elapsed_seconds": round(phase_elapsed),
            "phase_token": str(phase_since or ""),
            "current_phases": pv_control_raw.get("current_phases"),
            "power_w": pv_control_raw.get("status_power_w"),
            "last_action": pv_control_raw.get("last_action"),
        },
    }


def dashboard_payload() -> dict[str, Any]:
    pv_power_w = state_value(ENTITIES["pv_power"])
    house_power_w = state_value(ENTITIES["house_power"])
    live = {
        "battery_soc": state_value(ENTITIES["battery_soc"]),
        "pv_power_w": pv_power_w,
        "power_balance_w": state_value(ENTITIES["power_balance"]),
        "house_power_w": house_power_w,
        # Für UI/Kompatibilität bleibt der Feldname erhalten; der Wert ist ab 0.1.58
        # der tatsächlich nach Haus und Speicher für die Wallbox nutzbare Überschuss.
        "pv_minus_house_w": current_pv_surplus_w(),
        "battery_power_w": state_value(ENTITIES["battery_power"]),
        "grid_power_w": state_value(ENTITIES["grid_power"]),
        "wallbox_power_w": state_value(ENTITIES["wallbox_power"]),
        "wp_power_value": state_value(ENTITIES["wp_power"]),
        "wp_power_unit": state_unit(ENTITIES["wp_power"]),
        "pv_today_kwh": state_value(ENTITIES["pv_day"]),
        "net_import_today_kwh": state_value(ENTITIES["net_import_day"]),
        "grid_export_today_kwh": state_value(ENTITIES["grid_export_day"]),
        "wallbox_today_kwh": state_value(ENTITIES["wallbox_day"]),
        "wp_today_kwh": state_value(ENTITIES["wp_day"]),
        "dishwasher_power_w": _power_value_w(ENTITIES["dishwasher_power"]),
        "climate_office_today_kwh": state_value(ENTITIES["climate_office_day"]),
        "climate_kids_today_kwh": state_value(ENTITIES["climate_kids_day"]),
        "climate_living_state": state_text(ENTITIES["climate_living"]),
        "climate_bedroom_state": state_text(ENTITIES["climate_bedroom"]),
        "battery_charge_today_kwh": state_value(ENTITIES["battery_charge_day"]),
        "battery_discharge_today_kwh": state_value(ENTITIES["battery_discharge_day"]),
        "id7_soc": state_value(ENTITIES["id7_soc"]),
        "egolf_soc": state_value(ENTITIES["egolf_soc"]),
        "id7_cable": state_text(ENTITIES["id7_cable"]),
        "egolf_cable": state_text(ENTITIES.get("egolf_cable", "")) if ENTITIES.get("egolf_cable") else "unknown",
        "wallbox_mode": state_text(ENTITIES["wallbox_mode"]),
        "phase1": state_text(ENTITIES["phase1"]),
        "phase2": state_text(ENTITIES["phase2"]),
        "phase3": state_text(ENTITIES["phase3"]),
        "safe_charge": state_text(ENTITIES["battery_safe_charge"]),
        "warmwater": state_text(ENTITIES["warmwater_switch"]),
        "warmwater_temp": parse_number_from_state(ENTITIES["warmwater_temp"]),
    }
    now_for_consumers = now_local()
    live["dishwasher_today_kwh"] = _power_energy_today_kwh(
        "dishwasher", ENTITIES["dishwasher_power"], live.get("dishwasher_power_w"), now_for_consumers
    )
    live["climate_office_live_w"] = _counter_live_power_w(
        "climate_office", live.get("climate_office_today_kwh"), now_for_consumers
    )
    live["climate_kids_live_w"] = _counter_live_power_w(
        "climate_kids", live.get("climate_kids_today_kwh"), now_for_consumers
    )
    _update_standby_learning(now_for_consumers, live)

    history = [x for x in state_store.data.get("history", []) if isinstance(x, dict)]
    pv_surplus_control = pv_status_payload()["pv_surplus_control"]
    recent = history[-30:]
    live_records = [x for x in recent if x.get("raw_expected") and x.get("actual")]
    mae = None
    mape = None
    if live_records:
        errors = [abs(float(x["raw_expected"]) * float(calibration_for_ghi(float(x["ghi"]))["factor"]) - float(x["actual"])) for x in live_records]
        pcts = [e / float(x["actual"]) * 100 for e, x in zip(errors, live_records) if float(x["actual"]) > 1]
        mae = round(sum(errors) / len(errors), 2) if errors else None
        mape = round(sum(pcts) / len(pcts), 1) if pcts else None
    saved_forecasts = state_store.data.get("forecast", {})
    hourly_live = {ds: value.get("hourly", []) for ds, value in saved_forecasts.items() if isinstance(value, dict)}
    plan = build_plan(saved_forecasts, hourly_live) if isinstance(saved_forecasts, dict) else {}
    if isinstance(plan, dict) and isinstance(plan.get("battery"), dict):
        # Anzeige und Automatik verwenden denselben aktuellen SOC. Damit bleibt
        # die Restladezeit nicht auf dem Stand der letzten Forecast-Berechnung stehen.
        plan = json.loads(json.dumps(plan))
        current_ds = now_local().date().isoformat()
        primary_ds = str(plan.get("primary_date") or plan.get("tomorrow_date") or "")
        if primary_ds == current_ds and now_local().hour < 5:
            plan["primary_label"], plan["secondary_label"] = "Heute", "Morgen"
            plan["planning_day_is_today"] = True
        elif now_local().hour >= 5:
            plan["primary_label"], plan["secondary_label"] = "Morgen", "Übermorgen"
            plan["planning_day_is_today"] = False
        live_target = float(plan["battery"].get("target_soc", 20))
        live_schedule = battery_schedule(live["battery_soc"], live_target)
        plan["battery"].update({
            "soc": live["battery_soc"],
            "start_time": live_schedule.get("start_time"),
            "needed_minutes": live_schedule.get("needed_minutes"),
            "needed_kwh": live_schedule.get("needed_kwh"),
            "effective_charge_kw": live_schedule.get("effective_charge_kw"),
            "start_buffer_minutes": live_schedule.get("start_buffer_minutes"),
            "reachable": live_schedule.get("reachable"),
        })

    today_forecast = saved_forecasts.get(now_local().date().isoformat(), {}) if isinstance(saved_forecasts, dict) else {}
    live_pv = live_pv_analysis(today_forecast, today_forecast.get("hourly", []) if isinstance(today_forecast, dict) else []) if today_forecast else {}
    next_action = next_action_summary(plan if isinstance(plan, dict) else {}, live, live_pv)

    return {
        "version": VERSION,
        "time": now_local().isoformat(),
        "live": live,
        "forecast": state_store.data.get("forecast", {}),
        "plan": plan,
        "night_override": state_store.data.get("night_override", "auto"),
        "last_forecast_run": state_store.data.get("last_forecast_run"),
        "last_weather_refresh": state_store.data.get("last_weather_refresh"),
        "last_forecast_source": state_store.data.get("last_forecast_source"),
        "gemini_control": _gemini_control_for_today(),
        "live_pv": live_pv,
        "next_action": next_action,
        "last_error": state_store.data.get("last_error"),
        "settings": settings_store.data,
        "pv_surplus_control": pv_surplus_control,
        "wallbox_watchdog": dict(state_store.data.get("wallbox_watchdog", {})),
        "learning": {
            "today": now_local().date().isoformat(),
            "history_count": len(history),
            "recent_mae_kwh": mae,
            "recent_mape_percent": mape,
            "baseline_test_mae_kwh": 2.45,
            "baseline_test_mape_percent": 5.6,
            "battery": state_store.data.get("battery_learning", {}),
            "battery_night_control": dict(state_store.data.get("battery_night_control", {})),
            "morning": state_store.data.get("morning_learning", {}),
            "day_load": state_store.data.get("day_load_learning", {}),
            "standby": state_store.data.get("standby_learning", {}),
            "evening": state_store.data.get("evening_learning", {}),
        },
        "car_at_wallbox": car_at_wallbox(),
        "car_auto_charging_enabled": bool(state_store.data.get("car_auto_charging_enabled", True)),
        "wallbox_session": state_store.data.get("wallbox_session", {}),
        "pv_surplus_state": state_store.data.get("pv_surplus", {}),
    }


# 0.1.12: Dashboard-Cache für sofortiges Öffnen der WebApp.
# Die Anzeige bekommt immer den zuletzt fertig berechneten Stand sofort zurück;
# die Aktualisierung läuft parallel und blockiert den Browser nicht.
_DASHBOARD_CACHE_LOCK = threading.RLock()
_DASHBOARD_CACHE: dict[str, Any] | None = None
_DASHBOARD_CACHE_TS = 0.0
_DASHBOARD_REFRESHING = False


def _refresh_dashboard_cache() -> None:
    global _DASHBOARD_CACHE, _DASHBOARD_CACHE_TS, _DASHBOARD_REFRESHING
    with _DASHBOARD_CACHE_LOCK:
        if _DASHBOARD_REFRESHING:
            return
        _DASHBOARD_REFRESHING = True
    try:
        payload = dashboard_payload()
        with _DASHBOARD_CACHE_LOCK:
            _DASHBOARD_CACHE = payload
            _DASHBOARD_CACHE_TS = time.monotonic()
    except Exception:
        LOG.exception("Dashboard-Cache konnte nicht aktualisiert werden")
    finally:
        with _DASHBOARD_CACHE_LOCK:
            _DASHBOARD_REFRESHING = False


def _kick_dashboard_refresh() -> None:
    with _DASHBOARD_CACHE_LOCK:
        if _DASHBOARD_REFRESHING:
            return
    threading.Thread(target=_refresh_dashboard_cache, name="dashboard-refresh", daemon=True).start()


def dashboard_cached(max_age_seconds: float = 8.0) -> dict[str, Any]:
    with _DASHBOARD_CACHE_LOCK:
        cached = _DASHBOARD_CACHE
        age = time.monotonic() - _DASHBOARD_CACHE_TS if _DASHBOARD_CACHE_TS else 10**9
    if cached is None:
        # Nur beim allerersten Start synchron; main() wärmt den Cache bereits vor
        # dem HTTP-Server vor, daher ist dieser Pfad im Normalbetrieb praktisch nie nötig.
        _refresh_dashboard_cache()
        with _DASHBOARD_CACHE_LOCK:
            cached = _DASHBOARD_CACHE
    elif age > max_age_seconds:
        _kick_dashboard_refresh()
    if cached is None:
        return {"version": VERSION, "time": now_local().isoformat(), "live": {}, "forecast": {}, "plan": {}, "settings": settings_store.data}
    return cached


def dashboard_cache_loop() -> None:
    while True:
        _refresh_dashboard_cache()
        # Die Steuerung liefert ihre Kandidaten alle fünf Sekunden. Die Anzeige
        # soll den gestarteten 120-Sekunden-Countdown ohne spürbare Lücke sehen.
        time.sleep(5)


MANIFEST_JSON = '{"name":"Energieplaner","short_name":"Energieplaner","start_url":"./","scope":"./","display":"standalone","background_color":"#071015","theme_color":"#071116","icons":[{"src":"icon-192.png","sizes":"192x192","type":"image/png","purpose":"any maskable"},{"src":"icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}]}'

INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f3f6f4">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Energieplaner">
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="favicon.png">
<link rel="manifest" href="manifest.webmanifest">
<title>Energieplaner</title>
<style>
:root{--bg:#071015;--panel:#0f1d23;--panel2:#0a161b;--line:#22383f;--text:#f4f9f7;--muted:#91a8a4;--mint:#61e4b1;--cyan:#67c9ef;--sun:#ffca61;--red:#ff8179;--violet:#ad91ff;--shadow:0 18px 50px rgba(0,0,0,.26)}*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 88% -10%,rgba(103,201,239,.12),transparent 30%),radial-gradient(circle at -8% 38%,rgba(97,228,177,.07),transparent 28%),var(--bg)}button,input,select{font:inherit}.shell{max-width:1040px;margin:auto;padding:18px 14px 64px}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.brand{display:flex;align-items:center;gap:11px}.mark{width:45px;height:45px;border-radius:15px;background:linear-gradient(145deg,#61e4b1 0 42%,#67c9ef 42% 72%,#ffca61 72%);box-shadow:0 0 0 6px rgba(97,228,177,.05),0 12px 24px rgba(0,0,0,.22)}h1{margin:0;font-size:24px;letter-spacing:-.6px}.sub{margin-top:2px;color:var(--muted);font-size:11px;line-height:1.3}.nav{display:flex;gap:5px;padding:4px;border:1px solid var(--line);border-radius:14px;background:#0a151a}.nav button,.button{border:0;color:var(--text);background:transparent;border-radius:10px;padding:9px 11px;font-weight:850;cursor:pointer}.nav button.active{background:#1a2a31;box-shadow:inset 0 0 0 1px #2b444c}.statusline{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:13px 0 8px}.statusitem{min-width:0;padding:8px 10px;border-radius:12px;background:#0d191e;border:1px solid var(--line);color:var(--muted);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.statusitem b{color:var(--text);font-size:11px}.statusitem.ok{border-color:rgba(97,228,177,.35);color:#bdf6df}.alert{padding:8px 10px;border-radius:11px;border:1px solid rgba(255,202,97,.35);background:rgba(255,202,97,.07);color:#ffe0a1;font-size:10px;margin-bottom:8px}.view{display:none}.view.show{display:block}.section{background:linear-gradient(180deg,rgba(16,30,36,.99),rgba(10,23,28,.99));border:1px solid var(--line);border-radius:22px;padding:15px;margin-top:12px;box-shadow:var(--shadow)}.eyebrow{font-size:11px;font-weight:950;letter-spacing:.15em;color:var(--muted);text-transform:uppercase}.nowStrip{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}.nowChip{padding:10px;border:1px solid var(--line);border-radius:14px;background:rgba(4,14,18,.45);min-width:0}.nowChip strong{display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nowChip span{display:block;color:var(--muted);font-size:10px;margin-top:2px;line-height:1.25}.nowChip small{display:block;color:var(--muted);font-size:9px;margin-top:2px;line-height:1.2;white-space:normal}.forecastRail{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory;padding:1px 1px 6px;margin-top:10px;scrollbar-width:none}.forecastRail::-webkit-scrollbar{display:none}.forecastCard{flex:0 0 min(330px,88vw);scroll-snap-align:start;padding:14px;border:1px solid var(--line);border-radius:18px;background:rgba(7,18,23,.72)}.forecastTop{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.forecastDay{font-size:11px;font-weight:950;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}.forecastKwh{font-size:31px;font-weight:950;letter-spacing:-1.2px;margin-top:3px}.forecastKwh small{font-size:13px;color:var(--muted)}.planMini{padding:6px 8px;border-radius:999px;background:rgba(255,202,97,.10);border:1px solid rgba(255,202,97,.22);color:#ffdc91;font-size:10px;font-weight:900;white-space:nowrap}.range{color:var(--muted);font-size:10px}.spark{height:58px;display:flex;align-items:flex-end;gap:2px;margin-top:9px;border-bottom:1px dashed rgba(103,201,239,.32)}.bar{flex:1;min-width:2px;border-radius:4px 4px 1px 1px;background:linear-gradient(to top,rgba(103,201,239,.14),var(--cyan))}.hours{display:grid;grid-template-columns:repeat(6,1fr);font-size:8px;color:#668187;margin-top:4px;text-align:center}.meta3{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:8px}.mini{padding:7px;border-radius:10px;background:rgba(0,0,0,.13)}.mini b{display:block;font-size:12px}.mini span{display:block;color:var(--muted);font-size:8px;margin-top:1px}.swipeHint{font-size:9px;color:#617a80;text-align:right;margin-top:2px}.pvBox{margin-top:10px;border:1px solid rgba(97,228,177,.30);border-radius:18px;background:radial-gradient(circle at 90% 0,rgba(97,228,177,.12),transparent 38%),rgba(5,17,20,.52);padding:14px}.pvHeadline{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}.pvHeadline h2{font-size:22px;margin:3px 0 0;letter-spacing:-.5px}.budgetBig{font-size:26px;font-weight:950;text-align:right;color:#aaf1d2}.budgetBig small{display:block;font-size:9px;color:var(--muted);font-weight:700}.pvInfo{font-size:11px;color:var(--muted);line-height:1.45;margin-top:5px}.budgetGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:10px}.budgetItem{padding:8px 6px;border:1px solid var(--line);border-radius:11px;background:rgba(0,0,0,.12);text-align:center}.budgetItem b{display:block;font-size:12px}.budgetItem span{display:block;color:var(--muted);font-size:8px;margin-top:1px}.carline{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid rgba(34,56,63,.75)}.socPair{display:flex;gap:6px;min-width:0}.soc{padding:7px 9px;border-radius:10px;background:#102028;border:1px solid #294149;font-size:10px}.soc b{font-size:12px}.presence{display:flex;gap:4px;padding:3px;border:1px solid var(--line);border-radius:11px;background:#0a151a}.presence button{border:0;border-radius:8px;padding:7px 9px;background:transparent;color:var(--muted);font-weight:850;font-size:10px}.presence button.active{background:var(--mint);color:#06120d}.nightSummary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin-top:8px;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--line)}.planrow{display:grid;grid-template-columns:24px 1fr;align-items:center;gap:7px;padding:8px 9px;background:rgba(5,15,19,.96);min-width:0}.planrow:last-child{border-bottom:0}.planico{font-size:18px}.planrow strong{display:block;font-size:13px}.planrow span{display:block;color:var(--muted);font-size:10px;margin-top:2px}.planvalue{text-align:right;font-weight:950;font-size:13px}.nightControls{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:9px}.nightControls .button{padding:9px 4px;font-size:10px;background:#16262c;border:1px solid #2b4149}.nightControls .button.active{background:var(--sun);color:#1c1304;border-color:transparent}.targetline{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:9px}.targetline label{font-size:10px;color:var(--muted)}select,input{background:#102028;color:var(--text);border:1px solid #294149;border-radius:10px;padding:8px 9px;font-weight:800}.directSummary{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.stateMini{padding:9px;border-radius:12px;border:1px solid var(--line);background:rgba(5,15,19,.46)}.stateMini b{display:block;font-size:11px}.stateMini span{display:block;font-size:9px;color:var(--muted);margin-top:2px}details.controlDetails{margin-top:9px;border:1px solid var(--line);border-radius:15px;background:#09151a}details.controlDetails summary{cursor:pointer;list-style:none;padding:11px 12px;font-weight:900;font-size:11px;color:#c8d8d5}details.controlDetails summary::-webkit-details-marker{display:none}.controlInner{padding:0 11px 11px}.modeSwitch{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.modeBtn{border:1px solid #294149;background:#111f25;color:var(--muted);padding:10px 5px;border-radius:13px;font-weight:900;cursor:pointer;min-height:58px;font-size:10px}.modeBtn span{display:block;font-size:18px;margin-bottom:3px}.modeBtn.active{color:var(--text);border-color:rgba(255,202,97,.55);background:rgba(255,202,97,.10)}.phaseRow{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:7px}.phase{padding:7px;border:1px solid #294149;border-radius:10px;text-align:center;color:var(--muted);font-size:9px}.phase.on{border-color:rgba(97,228,177,.45);color:#9cf0cf;background:rgba(97,228,177,.06)}.bigToggle{width:100%;border:1px solid #294149;background:#112128;color:var(--text);padding:10px;border-radius:12px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;text-align:left;margin-top:6px}.bigToggle.on{border-color:rgba(97,228,177,.55);background:rgba(97,228,177,.08)}.bigToggle b{font-size:11px}.bigToggle span{font-size:9px;color:var(--muted)}.energyGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.energyTile{padding:9px;border-radius:12px;border:1px solid var(--line);background:rgba(5,15,19,.44)}.energyTile span{display:block;color:var(--muted);font-size:9px}.energyTile b{display:block;font-size:13px;margin-top:2px}.qualityLine{margin-top:9px;padding:9px 10px;border:1px solid var(--line);border-radius:12px;background:rgba(5,15,19,.45);font-size:10px;color:var(--muted)}.qualityLine b{color:var(--text)}.settingsGrid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:10px}.settingCard{border:1px solid var(--line);border-radius:17px;background:#0a171c;padding:13px}.settingCard h3{margin:0 0 9px;font-size:14px}.field{margin:8px 0}.field label{display:block;font-size:9px;color:var(--muted);margin-bottom:4px}.field input,.field select{width:100%}.switchline{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1b3037;font-size:10px}.switchline:last-child{border-bottom:0}.toggle{width:41px;height:23px;border-radius:999px;border:0;background:#24363d;position:relative}.toggle:after{content:"";position:absolute;width:17px;height:17px;left:3px;top:3px;border-radius:50%;background:#81999b;transition:.18s}.toggle.on{background:rgba(97,228,177,.28)}.toggle.on:after{left:21px;background:var(--mint)}.save{width:100%;margin-top:11px;background:var(--mint);color:#06120d;border:0;border-radius:12px;padding:11px;font-weight:950}.modelGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.modelStat{padding:8px;border:1px solid var(--line);border-radius:11px;background:rgba(0,0,0,.12)}.modelStat b{display:block;font-size:12px}.modelStat span{display:block;font-size:8px;color:var(--muted)}.footer{text-align:center;color:#61777b;font-size:9px;margin-top:18px}.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);padding:9px 13px;border-radius:999px;background:#ecfff8;color:#071411;font-weight:850;font-size:10px;opacity:0;pointer-events:none;transition:.2s;z-index:20}.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

.forecastDots{display:flex;justify-content:center;gap:5px;margin-top:1px}.forecastDot{width:6px;height:6px;border-radius:50%;background:#294048;transition:.18s}.forecastDot.active{width:16px;border-radius:999px;background:var(--cyan)}
.nowChip{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start}.nowIcon{font-size:18px;line-height:1.1}.nowLabel{display:block;color:var(--muted);font-size:9px;font-weight:850;text-transform:uppercase;letter-spacing:.08em}.nowChip strong{font-size:14px;white-space:normal;overflow:visible;text-overflow:clip;line-height:1.15;margin-top:1px}.nowChip small{display:block;color:var(--muted);font-size:9px;margin-top:3px;line-height:1.25}
.eveningBox{margin-top:10px;padding-top:10px;border-top:1px solid rgba(34,56,63,.75)}.eveningTitle{font-size:9px;color:var(--muted);font-weight:950;letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px}.eveningGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.eveningItem{padding:8px 6px;border-radius:11px;background:rgba(97,228,177,.055);border:1px solid rgba(97,228,177,.16);text-align:center}.eveningItem b{display:block;font-size:12px}.eveningItem span{display:block;color:var(--muted);font-size:8px;margin-top:1px}
.targetline{align-items:flex-start}.targetQuick{display:flex;gap:5px;overflow-x:auto;scrollbar-width:none;max-width:100%;padding-bottom:1px}.targetQuick::-webkit-scrollbar{display:none}.targetBtn{border:1px solid var(--line);background:#0b181d;color:var(--text);border-radius:10px;padding:8px 10px;font-weight:900;white-space:nowrap;cursor:pointer}.targetBtn.active{background:rgba(255,202,97,.15);border-color:rgba(255,202,97,.45);color:#ffda89}
.statusitem.geminiok{border-color:rgba(97,228,177,.28);color:#bdf6df}.statusitem.geminifallback{border-color:rgba(255,202,97,.30);color:#ffe0a1}
.livePvBox{margin-top:10px;border:1px solid rgba(103,201,239,.28);border-radius:17px;background:linear-gradient(135deg,rgba(103,201,239,.07),rgba(97,228,177,.035));padding:12px}.livePvTop{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}.livePower{font-size:28px;font-weight:950;letter-spacing:-.8px}.livePower small{font-size:11px;color:var(--muted);font-weight:800}.liveStatus{text-align:right}.liveStatus b{display:block;font-size:12px}.liveStatus span{display:block;color:var(--muted);font-size:9px;margin-top:2px}.liveStats{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:9px}.liveStat{padding:7px 6px;border-radius:10px;background:rgba(0,0,0,.13);text-align:center}.liveStat b{display:block;font-size:11px}.liveStat span{display:block;font-size:8px;color:var(--muted);margin-top:1px}.liveGraph{height:58px;display:flex;align-items:flex-end;gap:2px;margin-top:10px;border-bottom:1px dashed rgba(103,201,239,.28)}.liveBar{flex:1;min-width:2px;border-radius:4px 4px 1px 1px}.liveBar.actual{background:linear-gradient(to top,rgba(97,228,177,.18),var(--mint))}.liveBar.forecast{background:linear-gradient(to top,rgba(103,201,239,.08),rgba(103,201,239,.65))}.liveHours{display:grid;grid-template-columns:repeat(6,1fr);font-size:8px;color:#668187;margin-top:4px;text-align:center}.nextAction{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:center;margin-top:9px;padding:9px 10px;border:1px solid rgba(255,202,97,.20);background:rgba(255,202,97,.055);border-radius:12px}.nextActionIcon{font-size:18px}.nextAction b{display:block;font-size:11px}.nextAction span{display:block;font-size:9px;color:var(--muted);margin-top:1px}.costNote{font-size:9px;color:var(--muted);line-height:1.35;margin-top:7px}.costNote b{color:#c9f8e5}
@media(max-width:760px){.shell{padding:14px 12px 58px}.liveStats{grid-template-columns:repeat(2,1fr)}.top{align-items:center}.mark{width:42px;height:42px}.sub{max-width:210px}.nav button{padding:8px 9px;font-size:10px}.statusitem{padding:7px 6px}.settingsGrid{grid-template-columns:1fr}.forecastCard{flex-basis:87vw}.budgetGrid{grid-template-columns:repeat(2,1fr)}.carline{align-items:flex-start;flex-direction:column}.presence{align-self:stretch}.presence button{flex:1}.energyGrid{grid-template-columns:repeat(2,1fr)}.modelGrid{grid-template-columns:repeat(2,1fr)}.nowChip{padding:9px 8px;gap:6px}.nowIcon{font-size:16px}.nowChip strong{font-size:12px}.nowChip small{font-size:8px}.eveningGrid{grid-template-columns:repeat(3,1fr)}.targetline{display:block}.targetline label{display:block;margin-bottom:7px}.targetQuick{width:100%}}

/* 0.1.12: kompakte Leistungsbilanz statt großem Flussdiagramm */
.balanceGrid{display:flex;gap:6px;margin-top:10px;overflow-x:auto;scroll-snap-type:x proximity;scrollbar-width:none;padding-bottom:1px}.balanceGrid::-webkit-scrollbar{display:none}.balanceTile{flex:1 0 145px;scroll-snap-align:start;padding:9px 8px;border:1px solid var(--line);border-radius:13px;background:rgba(5,15,19,.46);min-width:0}.balanceTile .blabel{display:block;color:var(--muted);font-size:9px}.balanceTile b{display:block;font-size:16px;margin-top:2px;white-space:nowrap}.balanceTile small{display:block;color:var(--muted);font-size:8px;margin-top:2px;line-height:1.28;min-height:20px}.balanceTile.source b{color:#bdf6df}.balanceTile.sink b{color:#ffd994}.balanceTile.neutral b{color:var(--text)}.balanceEquation{margin-top:8px;padding:8px 10px;border-radius:11px;border:1px solid var(--line);background:rgba(5,15,19,.35);font-size:10px;color:var(--muted);line-height:1.35}.balanceEquation b{color:var(--text)}
.targetQuick{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;min-width:min(520px,100%)}.targetBtn{border:1px solid #294149;background:#111f25;color:var(--text);padding:8px 4px;border-radius:10px;font-weight:900;cursor:pointer;font-size:10px;transition:transform .06s ease,background .08s ease}.targetBtn:active,.button:active,.modeBtn:active,.presence button:active,.bigToggle:active{transform:scale(.97)}.targetBtn.active{background:rgba(97,228,177,.18);border-color:rgba(97,228,177,.65);color:#c8fae5}.nightControls .button.active{background:rgba(97,228,177,.18);color:#c8fae5;border-color:rgba(97,228,177,.65)}
.loadingHint{font-size:9px;color:var(--muted);margin-top:6px}.staleNote{opacity:.7}
.netTile small{white-space:nowrap;font-size:7px!important;letter-spacing:-.22px}.actionFeedbackBtn{transition:transform .08s ease,filter .12s ease,opacity .12s ease,background .18s ease,color .18s ease}.actionFeedbackBtn:active{transform:scale(.985);filter:brightness(1.18)}.actionFeedbackBtn.busy{opacity:.72;cursor:wait}.actionFeedbackBtn.done{background:rgba(97,228,177,.22)!important;color:#cffff0!important;border-color:rgba(97,228,177,.65)!important}.actionFeedbackBtn.fail{background:rgba(255,129,121,.16)!important;color:#ffd0cc!important;border-color:rgba(255,129,121,.62)!important}.testPushBtn{width:100%;margin-top:8px;border:1px solid rgba(103,201,239,.45);background:rgba(103,201,239,.08);color:var(--text);border-radius:11px;padding:9px;font-weight:900;cursor:pointer}.pushButtonGrid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.pushButtonGrid .testPushBtn{margin-top:8px}@media(max-width:520px){.pushButtonGrid{grid-template-columns:1fr}}.planrow .planvalue{grid-column:2;text-align:left;margin-top:1px}.nowChip{min-height:0}.balanceTile{padding:7px 9px!important;min-height:62px!important}.balanceTile small{margin-top:3px!important}.energySection{padding-bottom:10px!important}@media(max-width:720px){.shell{padding:12px 10px 48px}.section{padding:12px;border-radius:18px;margin-top:9px}.statusline{margin-top:9px}.nowStrip{grid-template-columns:repeat(3,1fr)}.balanceGrid{margin-left:-2px;margin-right:-2px;padding-left:2px;padding-right:2px}.balanceTile{flex-basis:138px}.targetline{display:block}.targetQuick{margin-top:6px;grid-template-columns:repeat(4,1fr);min-width:0}.nightControls{grid-template-columns:repeat(3,1fr)}.forecastCard{flex-basis:86vw}.budgetGrid{grid-template-columns:repeat(3,1fr)}.energyGrid{grid-template-columns:repeat(3,1fr)}}

/* 0.1.15: Flussrichtung pro Live-Karte auf einen Blick sichtbar */
.tileHead{display:flex;align-items:center;justify-content:space-between;gap:5px;min-width:0}.tileHead .blabel{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.flowState{flex:none;padding:2px 5px;border-radius:999px;border:1px solid currentColor;font-size:6.5px;font-weight:950;letter-spacing:.07em;line-height:1.15;opacity:.9}.balanceTile.source .flowState{color:#8cebc4;background:rgba(97,228,177,.07)}.balanceTile.sink .flowState{color:#ffd994;background:rgba(255,202,97,.06)}.balanceTile.neutral .flowState{color:#b9c8c5;background:rgba(185,200,197,.05)}

/* 0.1.14: Live-Energie in einer Zeile, Tageswerte direkt integriert */
.todayTotals{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}.todayTotal{padding:8px 9px;border:1px solid var(--line);border-radius:12px;background:rgba(5,15,19,.36);min-width:0}.todayTotal span{display:block;color:var(--muted);font-size:8px}.todayTotal b{display:block;font-size:12px;margin-top:2px;white-space:nowrap}.pvSwipeCard.today{border-color:rgba(97,228,177,.32);background:radial-gradient(circle at 90% 0,rgba(97,228,177,.10),transparent 40%),rgba(7,18,23,.72)}.pvSwipeLiveTop{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.pvSwipeNow{font-size:28px;font-weight:950;letter-spacing:-1px}.pvSwipeNow small{font-size:10px;color:var(--muted);font-weight:700}.pvSwipeStats{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:8px}.pvSwipeStats div{padding:6px;border-radius:9px;background:rgba(0,0,0,.13)}.pvSwipeStats b{display:block;font-size:11px}.pvSwipeStats span{display:block;color:var(--muted);font-size:8px;margin-top:1px}
@media(max-width:720px){.todayTotals{grid-template-columns:repeat(2,1fr)}.pvSwipeStats{grid-template-columns:repeat(3,1fr)}}

/* 0.1.16: klare Vorzeichen im Live-Energieblock + kompaktere Übersicht */
.energySection{padding-bottom:11px}.energySection .balanceGrid{margin-top:8px}.balanceTile{padding:8px 9px;min-height:74px}.balanceTile .blabel{font-size:9px}.balanceTile b{font-size:18px;line-height:1.05;margin-top:4px}.balanceTile small{font-size:8px;min-height:0;margin-top:5px;line-height:1.25}.balanceTile.pvTile b{color:var(--sun)}.balanceTile.houseTile b{color:var(--text)}.balanceTile.flowMinus b{color:var(--red)}.balanceTile.flowPlus b{color:var(--mint)}.balanceTile.flowZero b{color:var(--text)}.balanceTile.consumerTile b{color:#ffd994}.balanceEquation{display:none}
/* Weniger verschenkter Platz in den oberen Planungsbereichen */
.statusline{margin:9px 0 6px;gap:5px}.statusitem{padding:6px 9px;border-radius:11px}.section{padding:12px 14px;margin-top:9px;border-radius:19px}.eyebrow{font-size:10px}.nowStrip{gap:6px;margin-top:7px}.nowChip{padding:8px 9px;border-radius:12px}.nowChip strong{font-size:12px}.nowChip span{font-size:9px}.nextAction{margin-top:6px;padding:7px 9px;border-radius:10px}.nextActionIcon{font-size:16px}.nextAction b{font-size:10px}.nextAction span{font-size:8px}.nightSummary{margin-top:7px;border-radius:14px}.planrow{grid-template-columns:24px 1fr;gap:7px;padding:8px 10px}.planico{font-size:16px}.planrow strong{font-size:12px}.planrow span{font-size:9px;margin-top:1px}.planvalue{font-size:12px}.targetline{margin-top:7px}.targetline label{font-size:9px}.targetBtn{padding:6px 4px}.nightControls{margin-top:6px;gap:5px}.nightControls .button{padding:7px 4px}.forecastRail{margin-top:8px}.pvBox{margin-top:8px;padding:11px}.directSummary{margin-top:8px}.qualityLine{margin-top:7px;padding:7px 9px}
@media(max-width:720px){.section{padding:9px 10px;margin-top:7px}.nowStrip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}.nowChip{padding:6px 5px}.nowChip strong{font-size:11px}.nowChip small{font-size:8px}.nightSummary{grid-template-columns:repeat(2,minmax(0,1fr))}.planrow{padding:7px 8px}.balanceTile{flex-basis:125px;min-height:62px}.balanceTile b{font-size:17px}.targetBtn{padding:6px 3px}.nightControls .button{padding:7px 3px}}

/* 0.1.18: responsive Karten-Teiler und klarere Sofort-/Nachtinformationen */
.planExtra{display:block!important;color:#7fcfb5!important;font-size:9px!important;margin-top:3px!important}.compactPrimary strong{font-size:16px}.nowChip{align-items:center}.nowChip>div:last-child{min-width:0}.planrow>div:last-child{min-width:0}.planrow .planvalue{white-space:normal}.planCars .planvalue{margin-top:2px}
@media(min-width:1180px){.shell{max-width:1280px}.nowStrip{grid-template-columns:repeat(4,minmax(0,1fr))}.nightSummary{grid-template-columns:repeat(2,minmax(0,1fr))}.balanceTile{flex-basis:0}}
@media(min-width:721px) and (max-width:1179px){.shell{max-width:980px}.nowStrip{grid-template-columns:repeat(2,minmax(0,1fr))}.nightSummary{grid-template-columns:repeat(2,minmax(0,1fr))}.nowChip{min-height:66px}}
@media(max-width:720px){.top{gap:8px}.brand{gap:8px}.mark{width:38px;height:38px;border-radius:12px}h1{font-size:20px}.sub{font-size:9px}.nav{gap:3px;padding:3px}.nav button{padding:7px 8px;font-size:9px}.statusline{grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}.statusitem{padding:6px 5px;font-size:8px}.statusitem b{font-size:9px}.nowStrip{grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.nowChip{padding:8px;min-height:68px}.nowChip strong{font-size:13px}.compactPrimary strong{font-size:16px}.nowChip small{font-size:8px}.nightSummary{grid-template-columns:1fr;gap:1px}.planrow{padding:8px 9px;grid-template-columns:24px minmax(0,1fr)}.planrow strong{font-size:12px}.planrow span{font-size:9px}.planrow .planvalue{font-size:12px}.planExtra{font-size:8.5px!important}.targetQuick{grid-template-columns:repeat(4,1fr)}.nightControls{grid-template-columns:repeat(3,1fr)}.balanceTile{flex:0 0 132px}.forecastCard{flex-basis:88vw}}
@media(max-width:420px){.shell{padding-left:8px;padding-right:8px}.section{padding:9px 8px}.eyebrow{font-size:9px;letter-spacing:.12em}.nowStrip{grid-template-columns:repeat(2,minmax(0,1fr))}.nowChip{padding:7px 6px}.nowIcon{font-size:15px}.nowLabel{font-size:8px}.nowChip strong{font-size:12px}.compactPrimary strong{font-size:15px}.nowChip small{font-size:7.5px}.statusitem{font-size:7.5px}.statusitem b{font-size:8.5px}.targetBtn{font-size:9px}.nightControls .button{font-size:9px}.balanceTile{flex-basis:126px}}


/* 0.1.22: eigenständige Energie-Cockpit-Optik */
body{
  background:
    linear-gradient(rgba(103,201,239,.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(97,228,177,.02) 1px,transparent 1px),
    radial-gradient(circle at 88% -10%,rgba(103,201,239,.12),transparent 30%),
    radial-gradient(circle at -8% 38%,rgba(97,228,177,.07),transparent 28%),
    var(--bg);
  background-size:32px 32px,32px 32px,auto,auto,auto;
}
.mark{position:relative;display:grid;place-items:center;overflow:hidden}
.mark:after{content:"⚡";font-size:21px;line-height:1;filter:drop-shadow(0 1px 0 rgba(255,255,255,.22))}
.section{position:relative;overflow:hidden;border-radius:16px;box-shadow:0 10px 32px rgba(0,0,0,.19)}
.section:before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:2px;border-radius:2px;background:linear-gradient(var(--mint),var(--cyan));opacity:.42}
.energySection:before{background:linear-gradient(var(--sun),var(--mint));opacity:.72}
.eyebrow{color:#b6c9c5;letter-spacing:.13em}
.statusline{border-bottom:1px solid rgba(103,201,239,.09);padding-bottom:4px}
.nav{box-shadow:inset 0 0 0 1px rgba(255,255,255,.015)}
@media(max-width:720px){
  body{background-size:24px 24px,24px 24px,auto,auto,auto}
  .section{border-radius:13px;box-shadow:0 7px 20px rgba(0,0,0,.16)}
  .section:before{top:8px;bottom:8px}
}

.phase{cursor:pointer;font:inherit}.phase:hover{border-color:rgba(103,201,239,.65);color:#d8f5ff}.phase:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}.phaseHint{grid-column:1/-1;margin:8px 1px 0;color:var(--muted);font-size:9px;line-height:1.35}.surplusChip{border-color:rgba(97,228,177,.42);background:rgba(97,228,177,.07)}.surplusChip.negative{border-color:rgba(255,129,121,.40);background:rgba(255,129,121,.06)}
.phaseRule{margin-top:10px;padding:10px;border:1px solid rgba(103,201,239,.26);border-radius:13px;background:rgba(103,201,239,.045)}.phaseRuleTop{display:flex;align-items:baseline;justify-content:space-between;gap:8px}.phaseRuleTop b{font-size:14px;color:#baf2ff}.phaseRuleTop span{font-size:9px;color:var(--muted)}.phaseRuleSteps{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:8px}.phaseRuleStep{padding:7px 5px;border:1px solid var(--line);border-radius:9px;text-align:center;background:rgba(0,0,0,.10)}.phaseRuleStep b{display:block;font-size:10px}.phaseRuleStep span{display:block;font-size:8px;color:var(--muted);margin-top:2px}.phaseRuleStep.active{border-color:rgba(97,228,177,.55);background:rgba(97,228,177,.08);color:#bdf5dc}
@media(min-width:1180px){.nowStrip{grid-template-columns:repeat(5,minmax(0,1fr))}}@media(min-width:721px) and (max-width:1179px){.nowStrip{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:420px){.phaseRuleSteps{grid-template-columns:1fr}.phaseRuleTop{display:block}.phaseRuleTop span{display:block;margin-top:3px}}

/* 0.1.25: Die Übersicht ist das ruhige Cockpit aus dem Entwurf – nicht nur
   eine Liste bereits vorhandener Karten. */
.overviewTop{margin-top:18px}.overviewTop>.eyebrow{margin-bottom:12px}.overviewGrid{display:grid;grid-template-columns:1.45fr .9fr;grid-template-areas:"pv direct" "plan phases";gap:16px;margin-top:16px}.overviewGrid .section{margin:0;box-shadow:none;background:rgba(8,24,29,.72);border-radius:22px;padding:22px}.overviewGrid .sectionHead{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.overviewGrid .sectionHead h2{font-size:22px;letter-spacing:-.45px;margin:5px 0 0}.overviewGrid .sectionHint{font-size:11px;color:var(--muted);line-height:1.35;text-align:right;max-width:112px}.pvControlBlock{grid-area:pv}.directControlBlock{grid-area:direct}.planControlBlock{grid-area:plan}.phaseControlBlock{grid-area:phases}.overviewTop .nowStrip{grid-template-columns:1.22fr .9fr .9fr;gap:16px;margin:0}.overviewTop .nowChip{min-height:166px;padding:25px 27px;border-radius:22px;display:block;background:rgba(10,29,35,.9);border-color:#294a55}.overviewTop .nowChip:nth-child(3){order:-1;border-color:rgba(97,228,177,.45);background:linear-gradient(135deg,rgba(20,71,62,.64),rgba(10,29,35,.92))}.overviewTop .nowChip:nth-child(n+4){display:none}.overviewTop .nowIcon{font-size:19px;margin-bottom:7px}.overviewTop .nowLabel{font-size:13px;letter-spacing:0;text-transform:none}.overviewTop .nowChip strong{font-size:32px;letter-spacing:-1px;margin-top:13px}.overviewTop .nowChip small{font-size:13px;line-height:1.35;margin-top:6px;color:#dbe7e5}.overviewTop .surplusChip strong{color:#a5f2d3}.pvControlBlock .pvBox{margin-top:17px;padding:0;border:0;background:none}.pvControlBlock .pvHeadline{display:none}.pvControlBlock .budgetGrid,.pvControlBlock .carline{display:none}.pvControlBlock .pvInfo:first-of-type{font-size:16px;color:var(--text);margin:0 0 16px}.pvControlBlock .phaseRule{margin:0;padding:0;border:0;background:none}.pvControlBlock .phaseRuleTop{display:none}.pvControlBlock .phaseRuleSteps{gap:12px;margin:0}.pvControlBlock .phaseRuleStep{min-height:126px;padding:26px 10px;border-radius:20px;display:flex;flex-direction:column;justify-content:center;background:rgba(5,17,21,.72)}.pvControlBlock .phaseRuleStep b{font-size:23px;font-weight:850}.pvControlBlock .phaseRuleStep span{font-size:12px;margin-top:9px}.pvControlBlock .phaseRuleStep.active{border-color:var(--mint);background:rgba(27,94,78,.58);box-shadow:inset 0 0 0 1px rgba(97,228,177,.15)}.pvControlBlock .pvInfo:last-of-type{font-size:12px;margin:18px 0 0}.directControlBlock .directSummary{grid-template-columns:1fr;margin-top:15px}.directControlBlock .stateMini{display:none}.directControlBlock .stateMini:first-child{display:block;padding:13px;border-radius:15px}.directControlBlock .stateMini b{font-size:18px}.directControlBlock .stateMini span{font-size:12px;margin-top:5px}.directControlBlock details.controlDetails{margin-top:12px;border-color:#294a55;background:rgba(5,17,21,.52)}.directControlBlock details.controlDetails summary{padding:14px;font-size:12px}.directControlBlock details[open] summary{border-bottom:1px solid var(--line)}.planControlBlock .nightSummary{margin-top:17px;border-radius:16px}.planControlBlock .planrow{padding:13px 14px}.planControlBlock .planrow strong{font-size:15px}.planControlBlock .planrow span{font-size:11px}.planControlBlock .targetline{display:block;margin-top:16px}.planControlBlock .targetline label{display:block;font-size:11px;margin-bottom:9px}.planControlBlock .nightControls{margin-top:11px}.phaseControlBlock{display:flex;flex-direction:column}.phaseControlBlock #phaseRules{margin-top:17px}.phaseStatus{font-size:12px;color:var(--muted);line-height:1.45;margin-top:auto;padding-top:15px}.phaseSetting{padding:16px;border:1px solid #294a55;border-radius:17px;background:rgba(10,29,35,.65);margin-top:12px}.phaseSetting span{display:block;color:var(--muted);font-size:11px}.phaseSetting b{display:flex;justify-content:space-between;gap:8px;align-items:baseline;font-size:17px;margin-top:8px}.phaseSetting b em{font-style:normal;color:#a5f2d3}.phaseProgress{height:9px;border-radius:999px;background:#1b343c;overflow:hidden;margin-top:16px}.phaseProgress i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--mint),var(--cyan))}.overviewBelow{margin-top:16px}.overviewBelow .section{box-shadow:none}
@media(max-width:760px){.overviewGrid{grid-template-columns:1fr;grid-template-areas:"pv" "direct" "plan" "phases";gap:10px;margin-top:10px}.overviewGrid .section{border-radius:18px;padding:17px}.overviewTop{margin-top:14px}.overviewTop>.eyebrow{margin-bottom:9px}.overviewTop .nowStrip{grid-template-columns:1fr;gap:9px}.overviewTop .nowChip{min-height:0;padding:18px 19px}.overviewTop .nowChip strong{font-size:27px;margin-top:8px}.overviewTop .nowIcon{float:left;margin:1px 8px 0 0}.overviewTop .nowLabel{padding-top:2px}.overviewTop .nowChip small{clear:both}.overviewGrid .sectionHead h2{font-size:20px}.pvControlBlock .phaseRuleSteps{gap:7px}.pvControlBlock .phaseRuleStep{min-height:99px;padding:15px 6px;border-radius:16px}.pvControlBlock .phaseRuleStep b{font-size:17px}.pvControlBlock .phaseRuleStep span{font-size:10px;margin-top:6px}.planControlBlock .nightSummary{grid-template-columns:1fr}.overviewBelow{margin-top:10px}}
.overviewTop .nowChip:nth-child(1){order:1}.overviewTop .nowChip:nth-child(2){order:0}.directControlBlock .directSummary{grid-template-columns:repeat(3,1fr)}.directControlBlock .stateMini{display:block;padding:12px 9px;border-radius:15px}.directControlBlock .stateMini b{font-size:12px}.directControlBlock .stateMini span{font-size:10px;margin-top:5px}

/* 0.1.26: kompakter Phasenstatus dort, wo die Energiewerte ohnehin gelesen werden. */
.nowStrip .nowChip:nth-child(3){display:none}.pvPhaseStatus{margin-top:10px;padding:10px;border:1px solid rgba(103,201,239,.32);border-radius:13px;background:linear-gradient(90deg,rgba(103,201,239,.08),rgba(97,228,177,.045))}.pvPhaseStatusTop{display:flex;align-items:baseline;justify-content:space-between;gap:8px}.pvPhaseStatusTop b{font-size:14px;color:#baf2ff}.pvPhaseStatusTop span{font-size:10px;color:var(--muted)}.pvPhaseSteps{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:8px}.pvPhaseStep{padding:7px 6px;border:1px solid var(--line);border-radius:10px;background:rgba(0,0,0,.11);text-align:center}.pvPhaseStep b{display:block;font-size:10px}.pvPhaseStep span{display:block;font-size:8px;color:var(--muted);margin-top:2px}.pvPhaseStep.active{border-color:rgba(97,228,177,.65);background:rgba(97,228,177,.10);color:#bdf5dc}.pvPhaseStep.waiting{border-color:rgba(103,201,239,.62);background:rgba(103,201,239,.08);color:#d3f5ff}.pvPhaseProgress{height:8px;border-radius:999px;background:#1a343c;overflow:hidden;margin-top:9px}.pvPhaseProgress i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--mint),var(--cyan))}.pvPhaseText{font-size:10px;color:var(--muted);line-height:1.35;margin-top:7px}@media(max-width:720px){.nightSummary{grid-template-columns:repeat(2,minmax(0,1fr))}.pvPhaseSteps{gap:4px}.pvPhaseStep{padding:7px 3px}.pvPhaseStep b{font-size:9px}.pvPhaseStep span{font-size:7.5px}.pvPhaseStatus{padding:8px}.pvPhaseStatusTop b{font-size:12px}}
/* 0.1.27: ein Satz, eine Zeit, eine nächste Aktion. */
.pvPhaseStatus{padding:12px 14px!important;background:linear-gradient(100deg,rgba(13,42,48,.82),rgba(10,25,30,.7))!important;border-color:rgba(103,201,239,.38)!important}.pvPhaseMain{display:flex;justify-content:space-between;align-items:center;gap:14px}.pvPhaseMain>div:first-child{min-width:0}.pvPhaseMain>div:first-child>span{display:block;text-transform:uppercase;letter-spacing:.12em;font-size:8px;font-weight:950;color:var(--muted)}.pvPhaseMain>div:first-child>b{display:block;font-size:16px;line-height:1.2;margin-top:4px}.pvPhaseMain>div:first-child>small{display:block;font-size:10px;color:var(--muted);margin-top:5px;line-height:1.3}.pvPhaseClock{flex:0 0 auto;text-align:right;border-left:1px solid rgba(103,201,239,.26);padding-left:14px}.pvPhaseClock>b{display:block;font-size:24px;line-height:1;letter-spacing:-.8px;color:#baf2ff}.pvPhaseClock>span{display:block;font-size:8px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-top:4px}.pvPhaseStatus.active{border-color:rgba(97,228,177,.42)!important}.pvPhaseStatus.active .pvPhaseClock>b{color:#a9f1d0}.pvPhaseStatus.waiting{border-color:rgba(103,201,239,.58)!important}.pvPhaseStatus.stop{border-color:rgba(255,129,121,.58)!important;background:linear-gradient(100deg,rgba(74,28,31,.56),rgba(10,25,30,.72))!important}.pvPhaseStatus.stop .pvPhaseClock>b{color:#ffc1bc}.pvPhaseStatus.low{border-color:rgba(255,202,97,.48)!important;background:linear-gradient(100deg,rgba(66,49,25,.45),rgba(10,25,30,.72))!important}.pvPhaseStatus.low .pvPhaseClock>b{color:#ffe0a1}@media(max-width:520px){.pvPhaseStatus{padding:10px!important}.pvPhaseMain{gap:9px}.pvPhaseMain>div:first-child>b{font-size:13px}.pvPhaseMain>div:first-child>small{font-size:9px}.pvPhaseClock{padding-left:9px}.pvPhaseClock>b{font-size:18px}}

/* 0.1.30: Lernwerte direkt unten im Dashboard sichtbar. */
.learningSummary{margin-top:10px;padding-top:10px;border-top:1px solid var(--line);display:grid;gap:7px}.learnRow{padding:9px 10px;border:1px solid var(--line);border-radius:12px;background:rgba(0,0,0,.11);font-size:10px;line-height:1.45;color:var(--muted)}.learnRow b{color:var(--text);font-size:11px}.learnRow .mint{color:#a9f1d0}.learnRow .cyan{color:#baf2ff}@media(max-width:520px){.learningSummary{gap:6px}.learnRow{padding:8px 9px;font-size:9.5px}.learnRow b{font-size:10.5px}}

/* 0.1.33 · kompakter Hauptscreen */
.nowSection .pvPhaseStatus{margin-top:8px!important;padding:8px 10px!important}.nowSection .pvPhaseMain{gap:8px}.nowSection .pvPhaseMain>div:first-child>b{font-size:13px;margin-top:2px}.nowSection .pvPhaseMain>div:first-child>small{font-size:8px;margin-top:2px;line-height:1.2}.nowSection .pvPhaseClock{padding-left:9px}.nowSection .pvPhaseClock>b{font-size:18px}.nowSection .pvPhaseClock>span{font-size:7px;margin-top:2px}
.nightControlRow{display:grid;grid-template-columns:minmax(0,3fr) minmax(88px,1fr);gap:6px;margin-top:8px}.nightControlRow .nightControls{margin-top:0}.nightControls .button{padding:9px 3px;white-space:nowrap}.socMenuButton{border:1px solid rgba(97,228,177,.55);background:rgba(97,228,177,.12);color:#c8fae5;border-radius:10px;padding:9px 5px;font-weight:900;cursor:pointer;white-space:nowrap}.socDropdown{display:none;margin-top:6px;padding:6px;border:1px solid var(--line);border-radius:12px;background:#09151a}.socDropdown.show{display:block}.socDropdown .targetQuick{grid-template-columns:repeat(7,1fr);min-width:0;margin:0}.socDropdown .targetBtn{padding:8px 3px}
.balanceGrid{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px!important;overflow:visible!important;scroll-snap-type:none!important;margin-top:8px!important}.balanceTile{min-width:0!important;min-height:70px!important;padding:7px 7px!important}.balanceTile .blabel{font-size:8px!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.balanceTile b{font-size:15px!important;margin-top:3px!important}.balanceTile small{font-size:7.5px!important;margin-top:4px!important;line-height:1.22!important;min-height:0!important}.netTile small{white-space:normal!important;font-size:7.2px!important;letter-spacing:0!important}
@media(max-width:520px){.nightControlRow{grid-template-columns:minmax(0,3fr) 84px;gap:4px}.nightControls{gap:4px}.nightControls .button{font-size:9px;padding:8px 2px}.socMenuButton{font-size:9px;padding:8px 3px}.socDropdown .targetQuick{grid-template-columns:repeat(4,1fr)}.balanceGrid{gap:4px!important}.balanceTile{min-height:68px!important;padding:6px!important}.balanceTile b{font-size:14px!important}.balanceTile small{font-size:7px!important}}

/* 0.1.34 · kompaktere Bereiche und visuelle Hierarchie */
.nowSection{padding:11px 12px 10px;background:linear-gradient(180deg,rgba(12,34,34,.98),rgba(8,25,28,.98));border-color:rgba(97,228,177,.24)}
.nowSection:before{background:linear-gradient(var(--mint),var(--cyan));opacity:.82}
.nowSection .nowStrip{grid-template-columns:repeat(2,minmax(0,1fr));gap:5px;margin-top:7px}
.nowSection .nowChip{padding:7px 8px;border-radius:11px;gap:6px;background:rgba(4,15,18,.48)}
.nowSection .nowIcon{font-size:15px}.nowSection .nowLabel{font-size:7.5px}.nowSection .nowChip strong{font-size:12px;line-height:1.08}.nowSection .nowChip small{font-size:7.5px;margin-top:2px;line-height:1.16}
.nowSection .pvPhaseStatus{margin-top:6px!important;padding:6px 8px!important;border-radius:11px}.nowSection .pvPhaseMain>div:first-child>span{font-size:7px}.nowSection .pvPhaseMain>div:first-child>b{font-size:11.5px;margin-top:1px}.nowSection .pvPhaseMain>div:first-child>small{font-size:7px;margin-top:1px;line-height:1.15}.nowSection .pvPhaseClock>b{font-size:16px}.nowSection .pvPhaseClock>span{font-size:6.5px}

.nightSection{padding:11px 12px 10px;background:linear-gradient(180deg,rgba(20,27,43,.97),rgba(11,24,34,.98));border-color:rgba(173,145,255,.24)}
.nightSection:before{background:linear-gradient(var(--violet),var(--cyan));opacity:.78}
.nightSection .nightSummary{margin-top:7px;border-color:rgba(173,145,255,.22);background:rgba(173,145,255,.16);border-radius:12px}
.nightSection .planrow{grid-template-columns:21px 1fr;gap:5px;padding:6px 8px;background:rgba(6,15,23,.92)}
.nightSection .planico{font-size:15px}.nightSection .planrow strong{font-size:11.5px;line-height:1.08}.nightSection .planrow span{font-size:8px;margin-top:1px;line-height:1.15}.nightSection .planvalue{font-size:11px;margin-top:1px}.nightSection .planExtra{font-size:7.5px!important;color:#9cd8c6!important}
.nightSection .nightControlRow{margin-top:6px;gap:4px}.nightSection .nightControls{gap:4px}.nightSection .nightControls .button{min-height:34px;padding:6px 2px;font-size:8.5px;border-radius:10px;background:rgba(30,45,58,.88);border-color:rgba(173,145,255,.24)}
.nightSection .nightControls .button.active{background:rgba(173,145,255,.18);color:#e6ddff;border-color:rgba(173,145,255,.6)}
.nightSection .socMenuButton{min-height:34px;padding:6px 4px;font-size:8.5px;border-color:rgba(103,201,239,.5);background:rgba(103,201,239,.10);color:#ccefff}
.nightSection .socDropdown{margin-top:5px;padding:5px;border-color:rgba(173,145,255,.24)}

.energySection{padding:11px 12px 10px;background:linear-gradient(180deg,rgba(24,30,28,.98),rgba(10,24,27,.98));border-color:rgba(255,202,97,.24)}
.energySection:before{background:linear-gradient(var(--sun),var(--mint));opacity:.88}
.energySection .balanceGrid{gap:4px!important;margin-top:7px!important}.energySection .balanceTile{position:relative;min-height:60px!important;padding:6px 7px!important;border-radius:11px!important;overflow:hidden}.energySection .balanceTile:before{content:"";position:absolute;left:0;right:0;top:0;height:2px;opacity:.7}
.energySection .balanceTile.flowGroup{background:linear-gradient(180deg,rgba(255,202,97,.055),rgba(5,15,19,.42));border-color:rgba(255,202,97,.20)}.energySection .balanceTile.flowGroup:before{background:linear-gradient(90deg,var(--sun),var(--cyan))}
.energySection .balanceTile.systemGroup{background:linear-gradient(180deg,rgba(97,228,177,.055),rgba(5,15,19,.42));border-color:rgba(97,228,177,.20)}.energySection .balanceTile.systemGroup:before{background:linear-gradient(90deg,var(--mint),var(--cyan))}
.energySection .balanceTile.consumerGroup{background:linear-gradient(180deg,rgba(103,201,239,.055),rgba(5,15,19,.42));border-color:rgba(103,201,239,.20)}.energySection .balanceTile.consumerGroup:before{background:linear-gradient(90deg,var(--cyan),var(--violet))}
.energySection .balanceTile .blabel{font-size:7.5px!important}.energySection .balanceTile b{font-size:13.5px!important;margin-top:2px!important;line-height:1.08}.energySection .balanceTile small{font-size:6.8px!important;margin-top:3px!important;line-height:1.14!important}.energySection .netTile small{font-size:6.6px!important}

.pvPlanSection{padding:11px 12px 10px;background:linear-gradient(180deg,rgba(10,32,29,.98),rgba(7,24,27,.98));border-color:rgba(97,228,177,.26)}
.pvPlanSection:before{background:linear-gradient(var(--mint),var(--sun));opacity:.82}
.pvPlanSection .pvBox{margin-top:7px;padding:10px;border-radius:14px;background:radial-gradient(circle at 94% 0,rgba(97,228,177,.10),transparent 35%),rgba(5,17,20,.48)}
.pvPlanSection .pvHeadline{gap:7px}.pvPlanSection .pvHeadline .eyebrow{font-size:8.5px;letter-spacing:.11em}.pvPlanSection .pvHeadline h2{font-size:18px;margin-top:2px;line-height:1.05}.pvPlanSection .budgetBig{font-size:23px;line-height:1}.pvPlanSection .budgetBig small{font-size:7.5px;margin-top:2px}.pvPlanSection .pvInfo{font-size:8.5px;line-height:1.28;margin-top:4px}
.pvQuickStatus{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px;padding:7px 8px;border:1px solid rgba(103,201,239,.22);border-radius:10px;background:rgba(103,201,239,.045)}.pvQuickStatus b{font-size:11px;color:#c9f5ff}.pvQuickStatus span{font-size:8px;color:var(--muted);text-align:right}
.pvPlanSection .phaseRule{margin-top:6px;padding:0;border:0;background:none}.pvPlanSection .phaseRuleTop{display:none}.pvPlanSection .phaseRuleSteps{gap:4px;margin-top:0}.pvPlanSection .phaseRuleStep{padding:6px 4px;border-radius:9px}.pvPlanSection .phaseRuleStep b{font-size:9px}.pvPlanSection .phaseRuleStep span{font-size:6.8px;margin-top:1px}.pvPlanSection .budgetGrid{gap:4px;margin-top:7px}.pvPlanSection .budgetItem{padding:5px 4px;border-radius:9px}.pvPlanSection .budgetItem b{font-size:10.5px}.pvPlanSection .budgetItem span{font-size:6.7px;margin-top:1px}.pvPlanSection .carline{margin-top:7px;padding-top:7px;gap:5px}.pvPlanSection .socPair{gap:4px}.pvPlanSection .soc{padding:5px 7px;border-radius:9px}.pvPlanSection .soc b{font-size:9.5px}.presenceSingle{border:1px solid rgba(97,228,177,.42);background:rgba(97,228,177,.08);color:#d7ffed;border-radius:9px;padding:6px 8px;font-size:8.5px;font-weight:900;cursor:pointer;white-space:nowrap}.presenceSingle.off{border-color:rgba(145,168,164,.30);background:rgba(145,168,164,.06);color:#b8c9c6}
.pvTechDetails{margin-top:6px;border-top:1px solid rgba(34,56,63,.68);padding-top:5px}.pvTechDetails summary{cursor:pointer;list-style:none;color:#71898d;font-size:7.5px;font-weight:850}.pvTechDetails summary::-webkit-details-marker{display:none}.pvTechBody{color:#748c90;font-size:7.2px;line-height:1.28;margin-top:4px}

@media(min-width:721px){.nowSection .nowStrip{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:520px){
  .nowSection,.nightSection,.energySection,.pvPlanSection{padding:10px 10px 9px}
  .nowSection .nowChip{padding:6px 7px}.nowSection .nowChip strong{font-size:11.5px}
  .nightSection .planrow{padding:5px 6px}.nightSection .nightControlRow{grid-template-columns:minmax(0,3fr) 80px}
  .energySection .balanceTile{min-height:57px!important;padding:5px 6px!important}.energySection .balanceTile b{font-size:12.5px!important}.energySection .balanceTile small{font-size:6.4px!important}
  .pvPlanSection .pvHeadline h2{font-size:17px}.pvPlanSection .budgetBig{font-size:21px}.pvPlanSection .budgetGrid{grid-template-columns:repeat(3,1fr)}.pvPlanSection .phaseRuleSteps{grid-template-columns:repeat(3,minmax(0,1fr))!important}.pvPlanSection .carline{flex-direction:row!important;align-items:center!important}.pvPlanSection .soc{padding:5px 6px}.presenceSingle{padding:6px 7px}
}


/* 0.1.48 · eigenständiges helles Desktop-/iPhone-Design */
:root{--bg:#f3f6f4;--panel:#ffffff;--panel2:#f8faf9;--line:#dce6e1;--text:#15211d;--muted:#71817b;--mint:#2f9a65;--cyan:#247eb4;--sun:#c88712;--red:#c95b54;--violet:#7159b8;--shadow:0 10px 30px rgba(26,55,43,.07)}
html{background:var(--bg)}body{background:linear-gradient(135deg,#f6f8f7 0,#eef4f1 100%);color:var(--text)}
.appShell{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr)}.sideNav{position:sticky;top:0;height:100vh;padding:22px 16px 18px;background:rgba(255,255,255,.92);border-right:1px solid var(--line);backdrop-filter:blur(18px);display:flex;flex-direction:column;z-index:20}.sideBrand{display:flex;align-items:center;gap:11px;padding:4px 6px 22px}.sideBrand strong{display:block;font-size:17px;letter-spacing:-.35px}.sideBrand span{display:block;color:var(--muted);font-size:9px;margin-top:2px}.mark{width:42px;height:42px;border-radius:14px;background:linear-gradient(145deg,#62dfb1 0 42%,#6ec8ef 42% 72%,#ffd26c 72%);box-shadow:0 5px 16px rgba(43,99,77,.14)}.sideLinks{display:grid;gap:5px}.sideLinks button,.sideSettings{border:0;background:transparent;color:#40504a;border-radius:12px;padding:11px 12px;font-weight:800;text-align:left;cursor:pointer;display:flex;align-items:center;gap:10px}.sideLinks button span{width:22px;text-align:center;font-size:16px}.sideLinks button.active{background:#e4f1e9;color:#20764d}.sideSettings{margin-top:auto;border:1px solid var(--line);background:#f8faf9}.sideVersion{padding:12px 5px 0;color:#94a19c;font-size:9px}.contentShell{min-width:0;padding:0 24px 60px}.mobileTop{display:none}.statusline{max-width:1500px;margin:18px auto 8px;grid-template-columns:repeat(3,minmax(0,1fr))}.statusitem{background:rgba(255,255,255,.8);border-color:var(--line);color:var(--muted);box-shadow:0 2px 12px rgba(26,55,43,.03)}.statusitem b{color:var(--text)}.statusitem.ok{border-color:#b8dfca;color:#26714d;background:#f7fcf9}.view{max-width:1500px;margin:0 auto}.appPage{display:none}.appPage.show{display:block}.pageHead{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:22px 2px 5px}.pageKicker{font-size:10px;text-transform:uppercase;letter-spacing:.16em;font-weight:900;color:#5b8b73}.pageHead h2{font-size:28px;margin:3px 0 2px;letter-spacing:-.7px}.pageHead p{margin:0;color:var(--muted);font-size:11px}.section{background:rgba(255,255,255,.94);border-color:var(--line);box-shadow:var(--shadow);border-radius:18px}.eyebrow{color:#657b71}.nowChip,.stateMini,.energyTile,.balanceTile,.forecastCard,.budgetItem,.qualityLine,.learnRow,.settingCard{background:#fbfcfb!important;border-color:var(--line)!important;color:var(--text)}.nowChip span,.nowChip small,.stateMini span,.energyTile span,.balanceTile small,.forecastDay,.range,.mini span,.pvInfo,.qualityLine,.learnRow{color:var(--muted)}.forecastCard{box-shadow:0 4px 18px rgba(31,67,51,.04)}.forecastRail{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));overflow:visible}.forecastCard{width:auto!important;max-width:none!important;flex:none!important}.forecastDots,.swipeHint{display:none}.spark{border-bottom-color:#d8e7e0}.bar{background:linear-gradient(to top,#d9eef7,#51afd9)}.planMini{background:#fff7df;border-color:#ead79b;color:#8b650c}.pvBox{background:linear-gradient(135deg,#f4fbf7,#fbfdfc);border-color:#bfe4d1}.budgetBig{color:#277b52}.soc,.presence,details.controlDetails,select,input{background:#f8faf9;color:var(--text);border-color:var(--line)}.presence button{color:var(--muted)}.presence button.active{background:#d9f1e4;color:#1d7048}.nightSummary{border-color:var(--line);background:var(--line)}.planrow{background:#fff}.nightControls .button{background:#f3f6f4;color:#40504a;border-color:var(--line)}.nightControls .button.active{background:#dff1e7;color:#1d6c47;border-color:#add6bf}.socMenuButton{background:#fff!important;color:var(--text)!important;border-color:var(--line)!important}.socDropdown{background:#fff!important;border-color:var(--line)!important}.targetBtn{background:#f5f7f6!important;color:#40504a!important;border-color:var(--line)!important}.targetBtn.active{background:#e4f1e9!important;color:#20764d!important}.modeBtn{background:#f7f9f8;color:var(--muted);border-color:var(--line)}.modeBtn.active{color:#7d5c08;border-color:#e7d18f;background:#fff8e3}.phase{border-color:var(--line);color:var(--muted)}.phase.on{border-color:#b3dec5;color:#26744e;background:#f1fbf5}.bigToggle{background:#f8faf9;color:var(--text);border-color:var(--line)}.bigToggle.on{border-color:#b2ddc5;background:#f1fbf5}.footer{color:#9ba7a2}.backButton,.iconButton{border:1px solid var(--line);background:#fff;color:#3c4c46;border-radius:12px;padding:9px 12px;font-weight:800;cursor:pointer}.learningSummary{display:grid;gap:8px;margin-top:12px}.learnRow{border:1px solid var(--line);border-radius:13px;padding:11px 12px}.calculationDetails{margin-top:12px;border:1px solid var(--line);border-radius:15px;background:#fbfcfb;overflow:hidden}.calculationDetails summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;padding:13px 14px}.calculationDetails summary::-webkit-details-marker{display:none}.calculationDetails summary b{display:block;font-size:12px}.calculationDetails summary small{display:block;color:var(--muted);font-size:9px;margin-top:2px}.calculationDetails .chevron{font-size:23px;color:#83918b;transition:.2s}.calculationDetails[open] .chevron{transform:rotate(90deg)}.calculationInner{padding:0 14px 14px}.calcIntro{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:10px}.calcStat{padding:10px;border:1px solid var(--line);border-radius:12px;background:#fff}.calcStat span{display:block;color:var(--muted);font-size:8px}.calcStat b{display:block;font-size:13px;margin-top:2px}.calcRows{border:1px solid var(--line);border-radius:12px;overflow:hidden}.calcRow{display:grid;grid-template-columns:1.2fr repeat(3,1fr);gap:6px;align-items:center;padding:9px 10px;border-bottom:1px solid var(--line);font-size:10px}.calcRow:last-child{border-bottom:0}.calcRow.head{font-weight:900;background:#f3f7f5;color:#66766f;font-size:8px;text-transform:uppercase}.calcRow b{font-size:11px}.calcFormula{margin-top:10px;padding:11px;border-radius:12px;background:#f3f7f5;font-size:10px;line-height:1.55}.calcFormula strong{font-size:12px}.settingsGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.settingCard{box-shadow:none}.save{background:#2e8f61!important;color:#fff!important}.mobileTabs{display:none}.pvPhaseStatus{background:#fbfcfb!important;border-color:var(--line)!important}.eveningBox,.phaseSetting,.phaseStatus{background:#f8faf9!important;border-color:var(--line)!important;color:var(--text)!important}
@media(max-width:980px){.appShell{grid-template-columns:190px minmax(0,1fr)}.contentShell{padding-left:16px;padding-right:16px}.forecastRail{grid-template-columns:1fr}.forecastDots,.swipeHint{display:block}.forecastRail{display:flex;overflow-x:auto}.forecastCard{flex:0 0 min(380px,88vw)!important}.calcIntro{grid-template-columns:repeat(2,1fr)}}
@media(max-width:720px){body{padding-bottom:74px}.appShell{display:block}.sideNav{display:none}.contentShell{padding:0 11px 20px}.mobileTop{display:flex;align-items:center;justify-content:space-between;padding:12px 2px 4px}.mobileTop .mark{width:38px;height:38px}.mobileTop h1{font-size:20px}.mobileTop .sub{font-size:9px}.statusline{margin:8px 0 3px;grid-template-columns:1fr 1fr 1fr;gap:4px}.statusitem{font-size:8px;padding:7px}.statusitem b{font-size:9px}.pageHead{padding:13px 2px 1px}.pageHead h2{font-size:23px}.pageHead p{font-size:10px;line-height:1.35}.section{padding:12px;margin-top:9px;border-radius:16px;box-shadow:0 5px 18px rgba(26,55,43,.055)}.nowStrip{grid-template-columns:repeat(2,1fr)}.nightSummary{grid-template-columns:1fr}.balanceGrid,.energyGrid{grid-template-columns:repeat(2,1fr)!important}.directSummary{grid-template-columns:1fr}.forecastCard{flex-basis:92vw!important}.forecastKwh{font-size:27px}.budgetGrid{grid-template-columns:repeat(2,1fr)}.pvHeadline h2{font-size:18px}.budgetBig{font-size:21px}.settingsGrid{grid-template-columns:1fr}.calcIntro{grid-template-columns:1fr 1fr}.calcRow{grid-template-columns:1.2fr 1fr 1fr}.calcRow .pvcol{display:none}.mobileTabs{position:fixed;left:0;right:0;bottom:0;z-index:50;display:grid;grid-template-columns:repeat(5,1fr);padding:5px 7px calc(5px + env(safe-area-inset-bottom));background:rgba(255,255,255,.94);border-top:1px solid var(--line);backdrop-filter:blur(20px)}.mobileTabs button{border:0;background:transparent;color:#7e8e87;padding:5px 1px;border-radius:11px;font-weight:800}.mobileTabs button span{display:block;font-size:19px;line-height:1}.mobileTabs button small{display:block;font-size:8px;margin-top:3px}.mobileTabs button.active{background:#e6f2eb;color:#21774e}.footer{padding-bottom:8px}.settingsHead{align-items:flex-end}.backButton{font-size:10px;padding:8px}.nightControlRow{grid-template-columns:1fr auto!important}.learningSummary{gap:6px}.learnRow{font-size:9px}.calculationDetails summary{padding:11px}.calcFormula{font-size:9px}}


/* 0.1.49 · Light-Design Feinschliff und vollständige Entdunkelung alter Komponenten */
:root{
  --bg:#f2f6f4;--panel:#ffffff;--panel2:#f7faf8;--line:#d8e4de;--line-strong:#c9d9d1;
  --text:#14231d;--muted:#6f8078;--mint:#2f9a65;--mint-soft:#e7f5ed;--cyan:#2588bd;
  --cyan-soft:#e8f5fb;--sun:#c88a16;--sun-soft:#fff6df;--red:#c85852;--violet:#7058b6;
  --shadow:0 12px 32px rgba(30,67,51,.075);--shadow-soft:0 5px 16px rgba(30,67,51,.045)
}
body{background:radial-gradient(circle at 84% 2%,rgba(87,190,147,.08),transparent 28%),linear-gradient(135deg,#f7faf8 0%,#eef4f1 58%,#f5f8f6 100%)}
.sideNav{background:rgba(255,255,255,.965);box-shadow:8px 0 30px rgba(40,75,59,.035)}
.sideBrand{padding-bottom:25px}.sideBrand strong{font-size:18px}.sideBrand span{font-size:9.5px}
.sideLinks{gap:7px}.sideLinks button,.sideSettings{min-height:46px;border-radius:14px;font-size:14px;transition:background .16s ease,color .16s ease,transform .16s ease}
.sideLinks button:hover,.sideSettings:hover{background:#f1f7f4;transform:translateX(1px)}
.sideLinks button.active{background:linear-gradient(135deg,#e8f5ed,#dff0e7);box-shadow:inset 0 0 0 1px rgba(47,154,101,.08);color:#1f774d}
.contentShell{padding-top:1px}.statusline{gap:8px}.statusitem{min-height:30px;border-radius:11px;padding:6px 10px;box-shadow:var(--shadow-soft)}
.pageHead{padding-top:30px;padding-bottom:10px}.pageKicker{color:#55856e}.pageHead h2{font-size:30px}.pageHead p{font-size:11.5px}
.section{border:1px solid var(--line);box-shadow:var(--shadow);overflow:hidden}.section>.eyebrow:first-child{font-size:9.5px;letter-spacing:.16em;color:#5b786a}

/* Alte Dark-Komponenten vollständig in das helle Theme überführen. */
.nowSection,.nightSection,.energySection,.pvPlanSection{
  background:rgba(255,255,255,.96)!important;border-color:var(--line)!important;color:var(--text)!important
}
.nowSection:before,.nightSection:before,.energySection:before,.pvPlanSection:before{opacity:.9!important}
.nowSection .nowChip{background:#fbfdfc!important;border:1px solid var(--line)!important;color:var(--text)!important}
.nowSection .pvPhaseStatus{background:linear-gradient(90deg,#fff9ea,#fffdf7)!important;border-color:#ead8a9!important;color:var(--text)!important}
.nowSection .pvPhaseMain>div:first-child>b{color:#51421d!important}.nowSection .pvPhaseMain>div:first-child>small{color:#8a7a53!important}
.nowSection .pvPhaseClock{border-left-color:#e7d7aa!important}.nowSection .pvPhaseClock>b{color:#8a680f!important}

.nightSection .nightSummary{background:var(--line)!important;border-color:var(--line)!important;box-shadow:none!important}
.nightSection .planrow{background:#fbfdfc!important;color:var(--text)!important}
.nightSection .planrow strong,.nightSection .planvalue{color:var(--text)!important}.nightSection .planrow span{color:var(--muted)!important}.nightSection .planExtra{color:#4c8c70!important}
.nightSection .nightControls .button{background:#f5f8f6!important;color:#4a5a53!important;border-color:var(--line)!important;box-shadow:none!important}
.nightSection .nightControls .button:hover{background:#edf4f0!important}
.nightSection .nightControls .button.active{background:linear-gradient(135deg,#eee9ff,#e6efff)!important;color:#5e4c9c!important;border-color:#c6b9ef!important}
.nightSection .socMenuButton{background:#f8fbfa!important;color:#285f4a!important;border-color:#bdd8ca!important}
.nightSection .socDropdown{background:#fff!important;border-color:var(--line)!important}

.energySection .balanceTile{background:#fbfdfc!important;color:var(--text)!important;border-color:var(--line)!important;box-shadow:0 2px 8px rgba(30,67,51,.025)!important}
.energySection .balanceTile.flowGroup{background:linear-gradient(180deg,#fffdf7,#fbfdfc)!important}
.energySection .balanceTile.systemGroup{background:linear-gradient(180deg,#f7fdf9,#fbfdfc)!important}
.energySection .balanceTile.consumerGroup{background:linear-gradient(180deg,#f7fbfe,#fbfdfc)!important}
.energySection .balanceTile .blabel,.energySection .balanceTile small{color:var(--muted)!important}

.pvPlanSection .pvBox{background:linear-gradient(135deg,#f3fbf7 0%,#fbfdfc 60%,#f4faf8 100%)!important;border:1px solid #cfe3d9!important;color:var(--text)!important;box-shadow:var(--shadow-soft)}
.pvPlanSection .pvHeadline h2{color:var(--text)!important}.pvPlanSection .pvInfo{color:var(--muted)!important}.pvPlanSection .budgetBig{color:#278357!important}
.pvQuickStatus{background:#f3f9fc!important;border-color:#d4e9f2!important}.pvQuickStatus b{color:#276b8d!important}.pvQuickStatus span{color:var(--muted)!important}
.pvPlanSection .phaseRuleStep,.pvPlanSection .budgetItem{background:#fff!important;border:1px solid var(--line)!important;color:var(--text)!important}
.pvPlanSection .phaseRuleStep span,.pvPlanSection .budgetItem span{color:var(--muted)!important}
.pvPlanSection .soc{background:#f8faf9!important;color:var(--text)!important;border-color:var(--line)!important}
.presenceSingle{background:#edf8f2!important;color:#24764e!important;border-color:#b9dbc8!important}.presenceSingle.off{background:#f6f8f7!important;color:#77867f!important;border-color:var(--line)!important}
.pvTechDetails{border-top-color:var(--line)!important}.pvTechDetails summary,.pvTechBody{color:#71817a!important}

/* Karten ruhiger und stärker hierarchisiert. */
.forecastCard{border-radius:17px!important;background:linear-gradient(180deg,#fff,#fbfdfc)!important}.forecastCard:hover{box-shadow:0 8px 22px rgba(31,67,51,.07)}
.planMini{box-shadow:inset 0 0 0 1px rgba(200,136,18,.04)}
.learnRow{background:linear-gradient(90deg,#fbfdfc,#f8fbf9)!important}.calculationDetails{background:#fff!important;box-shadow:var(--shadow-soft)}
.calculationDetails summary:hover{background:#f7faf8}.calcStat{background:#fbfdfc}.calcFormula{background:linear-gradient(135deg,#f2f8f5,#f7faf8)}
.directSummary>div{background:linear-gradient(180deg,#fff,#f8fbf9)!important;border-color:var(--line)!important;box-shadow:var(--shadow-soft)}
.controlDetails{background:#fff!important;box-shadow:var(--shadow-soft)}

/* Planung: vier Karten sollen wie echte Light-Cards wirken. */
.nightSection .planrow:nth-child(1){box-shadow:inset 3px 0 0 #48ae77}
.nightSection .planrow:nth-child(2){box-shadow:inset 3px 0 0 #4b9dca}
.nightSection .planrow:nth-child(3){box-shadow:inset 3px 0 0 #c7a246}
.nightSection .planrow:nth-child(4){box-shadow:inset 3px 0 0 #72a9b8}

/* Lernseite: Ziel und Morgenprognose etwas sichtbarer. */
.learningSummary .learnRow:nth-child(2){border-color:#cde3d8!important;background:linear-gradient(90deg,#f2faf6,#fbfdfc)!important}
.learningSummary .learnRow:nth-child(4){border-color:#cfe5ef!important;background:linear-gradient(90deg,#f2f9fc,#fbfdfc)!important}

@media(min-width:1100px){
  .pageHead{min-height:88px}.overviewPage .nowSection,.overviewPage .energySection{margin-top:10px}
}
@media(max-width:720px){
  body{background:#f4f7f5}.contentShell{padding-left:10px;padding-right:10px}.mobileTop{position:sticky;top:0;z-index:35;background:rgba(244,247,245,.9);backdrop-filter:blur(16px);margin:0 -10px;padding:9px 12px;border-bottom:1px solid rgba(216,228,222,.72)}
  .statusline{margin-top:7px}.pageHead{padding-top:14px}.pageHead h2{font-size:25px}.section{border-radius:17px;padding:11px!important}.nowSection .nowChip{border-radius:12px}.nightSection .nightSummary{border-radius:13px}.nightSection .planrow{padding:9px 9px!important}.nightSection .nightControls .button,.nightSection .socMenuButton{min-height:40px!important;font-size:9px!important}
  .forecastCard{border-radius:16px!important}.mobileTabs{box-shadow:0 -8px 24px rgba(30,67,51,.08);padding-top:6px}.mobileTabs button{min-height:48px}.mobileTabs button.active{box-shadow:inset 0 0 0 1px rgba(47,154,101,.07)}
  .calculationDetails{border-radius:14px}.calcRow{padding:10px 8px}.footer{opacity:.75}
}



/* 0.1.50 · Modernes Light-Cockpit mit konsequenter Lesbarkeit */
:root{
  --text:#101714;--muted:#4f5f58;--soft:#6b7973;--line:#d7e1dc;--line-strong:#c8d6cf;
  --mint:#23845a;--mint-soft:#e7f4ed;--cyan:#1779ad;--cyan-soft:#e9f4fa;
  --sun:#b87808;--sun-soft:#fff4d9;--red:#bd4742;--violet:#654ca6;
  --shadow:0 14px 36px rgba(24,55,41,.075);--shadow-soft:0 4px 16px rgba(24,55,41,.05)
}
body{color:var(--text)!important;background:linear-gradient(135deg,#f7faf8 0%,#eef4f1 62%,#f8faf9 100%)!important}
body,button,input,select,summary,.section,.statusitem,.learnRow,.qualityLine,.settingCard,.pvBox,.forecastCard,.planrow,.balanceTile,.stateMini{color:var(--text)}
.sideNav{width:auto}.sideBrand strong,.pageHead h2,.section b,.section strong,.sideLinks button,.sideSettings{color:var(--text)}
.sideLinks button{font-weight:780}.sideLinks button.active{color:#176d47}.pageKicker{color:#466f5c}.pageHead p,.sub,.sideBrand span,.sideVersion,.eyebrow,.range,.forecastDay,.pvInfo,.qualityLine,.learnRow span,.stateMini span,.balanceTile small,.balanceTile .blabel,.mini span,.budgetItem span,.planrow span,.calcStat span,.calcRow.head,.field label,.switchline,.footer{color:var(--muted)!important}
.statusitem{color:#485850!important}.statusitem b{color:#111814!important}.statusitem.ok,.statusitem.geminiok{color:#246b49!important}.statusitem.geminifallback{color:#76560a!important}
.statusitem.geminiok b,.statusitem.geminifallback b{color:#111814!important}

/* Übersichtsseite wie im freigegebenen Entwurf: Live-Karten + Zielkarte. */
.overviewEnergyGrid{display:grid;grid-template-columns:minmax(0,2.25fr) minmax(260px,.75fr);gap:12px;align-items:stretch}
.overviewEnergyGrid .energySection{margin-top:12px}.overviewGoalCard{margin-top:12px!important;display:flex;flex-direction:column;justify-content:space-between;padding:16px!important}
.goalTop{display:grid;grid-template-columns:150px 1fr;gap:14px;align-items:center}.goalRing{--goal:0deg;width:124px;height:124px;margin-top:10px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--mint) var(--goal),#e9efec 0);position:relative}.goalRing:before{content:"";position:absolute;inset:12px;background:#fff;border-radius:50%;box-shadow:inset 0 0 0 1px #e1e9e5}.goalRing>div{position:relative;z-index:1;text-align:center}.goalRing strong{display:block;font-size:28px;line-height:1;letter-spacing:-1px;color:#176d47!important}.goalRing span{display:block;font-size:9px;margin-top:5px;color:var(--muted)}.goalFacts{display:grid;gap:2px}.goalFacts>div{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #edf1ef}.goalFacts>div:last-child{border-bottom:0}.goalFacts span{font-size:9px;color:var(--muted)}.goalFacts b{font-size:11px;color:#111814!important;text-align:right}.goalLink{margin-top:10px;border:0;border-radius:11px;background:linear-gradient(135deg,#278b60,#1f774f);color:#fff;padding:10px 12px;font-weight:850;cursor:pointer;display:flex;align-items:center;justify-content:space-between}.goalLink span{font-size:18px;line-height:1}

/* Karten optisch leichter, moderne Abstände, schwarze Informationshierarchie. */
.section{background:rgba(255,255,255,.97)!important;border-color:var(--line)!important;box-shadow:var(--shadow)!important}.section:before{width:3px!important;top:12px!important;bottom:12px!important;border-radius:999px!important}
.nowSection .nowStrip{gap:8px!important}.nowSection .nowChip{padding:11px 12px!important;border-radius:14px!important;background:#fff!important;box-shadow:var(--shadow-soft)!important}.nowSection .nowLabel{color:var(--muted)!important}.nowSection .nowChip strong{font-size:17px!important;color:#111814!important}.nowSection .nowChip small{font-size:9px!important;color:var(--muted)!important}.nowSection .nowChip:first-child strong{color:#176d47!important}.nowSection .nowChip:last-child strong{color:#9b6606!important}
.energySection .balanceGrid{gap:8px!important}.energySection .balanceTile{min-height:74px!important;padding:10px 11px!important;border-radius:14px!important;background:#fff!important;box-shadow:var(--shadow-soft)!important}.energySection .balanceTile b{font-size:17px!important;color:#111814!important}.energySection .pvTile b{color:#a86f08!important}.energySection .flowPlus b{color:#18734b!important}.energySection .flowMinus b{color:#b54440!important}

/* Planung: keine dunklen Flächen, alle Texte dunkel; Akzent nur am Rand/Icon. */
.nightSection .nightSummary{gap:8px!important;background:transparent!important;border:0!important;overflow:visible!important}.nightSection .planrow{border:1px solid var(--line)!important;border-radius:14px!important;background:#fff!important;box-shadow:var(--shadow-soft)!important;padding:13px 14px!important}.nightSection .planrow strong,.nightSection .planvalue{color:#111814!important}.nightSection .planrow span{color:var(--muted)!important}.nightSection .planExtra{color:#2b7052!important}.nightSection .nightControls{gap:8px!important}.nightSection .nightControls .button,.nightSection .socMenuButton{background:#fff!important;color:#111814!important;border:1px solid var(--line)!important;box-shadow:var(--shadow-soft)!important}.nightSection .nightControls .button.active{background:var(--mint-soft)!important;color:#176d47!important;border-color:#b8dac8!important}

/* PV & Laden: schwarze Texte, farbliche Akzente nur bei Energiezahlen und Graphen. */
.forecastCard{padding:16px!important;box-shadow:var(--shadow-soft)!important}.forecastKwh,.pvSwipeNow{color:#111814!important}.forecastKwh small,.pvSwipeNow small{color:var(--muted)!important}.planMini{color:#815b05!important}.pvSwipeStats>div,.meta3 .mini{background:#f2f4f3!important}.pvSwipeStats b,.meta3 b{color:#111814!important}.pvPlanSection .pvHeadline h2,.pvPlanSection .budgetItem b,.pvPlanSection .phaseRuleStep b,.pvPlanSection .soc b,.eveningItem b{color:#111814!important}.pvPlanSection .budgetBig{color:#176d47!important}.pvQuickStatus b{color:#135f84!important}.pvPlanSection .phaseRuleStep.active{background:var(--mint-soft)!important;border-color:#b7dcca!important}.presenceSingle{color:#176d47!important}.pvTechDetails summary,.pvTechBody{color:var(--muted)!important}

/* Lernen: besonders hohe Lesbarkeit, keine blassen farbigen Texte. */
.learningSection .qualityLine,.learningSummary .learnRow,.calculationDetails{background:#fff!important;color:#111814!important}.qualityLine b,.learnRow b,.calcStat b,.calcRow b,.calcFormula strong{color:#111814!important}.learnRow .mint{color:#176d47!important}.learnRow .cyan{color:#126b98!important}.calculationDetails summary b{color:#111814!important}.calculationDetails summary small,.calculationDetails .chevron{color:var(--muted)!important}.calcRow{color:#111814!important}.calcFormula{color:#111814!important}

/* Steuerung/Einstellungen ebenfalls konsequent schwarz und kontrastreich. */
.directSummary>div,.controlDetails,.settingCard{background:#fff!important;color:#111814!important}.controlDetails summary{color:#111814!important}.modeBtn,.bigToggle,.testPushBtn,input,select{color:#111814!important;background:#fff!important}.modeBtn.active,.bigToggle.on{color:#176d47!important;background:var(--mint-soft)!important}.field input,.field select{border-color:var(--line-strong)!important}.switchline{color:#111814!important}

@media(max-width:980px){.overviewEnergyGrid{grid-template-columns:1fr}.overviewGoalCard{margin-top:0!important}.goalTop{grid-template-columns:150px 1fr}}
@media(max-width:720px){
  .pageHead{padding-top:12px!important}.pageHead h2{font-size:24px!important}.pageHead p{font-size:10px!important;color:var(--muted)!important}
  .overviewEnergyGrid{display:block}.overviewGoalCard{margin-top:9px!important}.goalTop{grid-template-columns:112px 1fr;gap:10px}.goalRing{width:96px;height:96px;margin-top:8px}.goalRing:before{inset:10px}.goalRing strong{font-size:22px}.goalFacts>div{padding:7px 0}.goalLink{min-height:42px}
  .nowSection .nowChip strong{font-size:15px!important}.energySection .balanceTile b{font-size:15px!important}
  .nightSection .nightSummary{grid-template-columns:1fr!important}.nightSection .planrow{padding:11px!important}
  .mobileTabs button{color:#4f5f58!important}.mobileTabs button.active{color:#176d47!important;background:#e8f4ed!important}
}


/* 0.1.51 · Freigegebenes Modern-Light-Design + maximale Textlesbarkeit */
:root{
  --ink:#0b0f0d;--ink-2:#222a26;--ink-3:#505b56;--surface:#ffffff;--surface-2:#f5f7f6;
  --border:#d8dfdb;--green:#1f8557;--green-soft:#eaf5ee;--blue:#1979aa;--blue-soft:#edf6fa;
  --yellow:#b67908;--yellow-soft:#fff5db;--red-strong:#b33f3b;--card-shadow:0 8px 24px rgba(18,43,31,.065)
}
html,body{color:var(--ink)!important}
body,.contentShell{background:#f4f7f5!important}
/* Grundregel: Texte sind schwarz/dunkel. Farbe kennzeichnet Status, nicht Lesetext. */
body :where(p,span,small,label,summary,button,div){text-shadow:none}
.pageHead h2,.section h2,.section h3,.section b,.section strong,.forecastKwh,.pvSwipeNow,.budgetBig,.planvalue,
.statusitem,.statusitem b,.statusitem.ok,.statusitem.geminiok,.statusitem.geminifallback,
.qualityLine,.learnRow,.learnRow b,.learnRow .mint,.learnRow .cyan,.calcRow,.calcRow b,.calcFormula,.calcFormula strong,
.pvQuickStatus b,.presenceSingle,.presenceSingle.off,.phaseRuleStep,.phaseRuleStep.active,.phaseRuleStep b,.phase.on,
.modeBtn,.modeBtn.active,.bigToggle,.bigToggle.on,.nightControls .button,.nightControls .button.active,.socMenuButton,
.targetBtn,.targetBtn.active,.controlDetails summary,.pvTechDetails summary,.pvTechBody{color:var(--ink)!important}
.pageHead p,.sub,.sideBrand span,.sideVersion,.eyebrow,.range,.forecastDay,.pvInfo,.balanceTile small,.balanceTile .blabel,
.mini span,.budgetItem span,.planrow span,.calcStat span,.calcRow.head,.field label,.footer,.goalFacts span,.learnMeta{color:var(--ink-3)!important}

/* Statusleiste: schwarze Beschriftung + Statuspunkt statt blasser Farbschrift. */
.statusline{gap:9px!important;margin-top:16px!important}.statusitem{position:relative;padding:10px 13px 10px 30px!important;background:#fff!important;border:1px solid var(--border)!important;border-radius:13px!important;box-shadow:0 3px 12px rgba(18,43,31,.035)!important;font-size:10px!important}
.statusitem:before{content:"";position:absolute;left:12px;top:50%;width:8px;height:8px;border-radius:50%;background:#8b9691;transform:translateY(-50%)}
.statusitem.ok:before,.statusitem.geminiok:before{background:var(--green)}.statusitem.geminifallback:before{background:var(--yellow)}
.statusitem b{font-size:11px!important}.statusitem.ok,.statusitem.geminiok{background:#fff!important}

/* Seitenkopf und Navigation näher am freigegebenen Mock-up. */
.contentShell{padding-left:28px!important;padding-right:28px!important}.pageHead{padding:25px 2px 10px!important}.pageKicker{color:var(--ink-3)!important;font-size:9px!important;letter-spacing:.18em!important}.pageHead h2{font-size:30px!important;letter-spacing:-1px!important}.pageHead p{font-size:11px!important}
.sideNav{background:#fff!important;border-right:1px solid var(--border)!important}.sideLinks button,.sideSettings{color:var(--ink-2)!important}.sideLinks button.active{background:var(--green-soft)!important;color:var(--ink)!important;box-shadow:inset 3px 0 0 var(--green)}
.sideLinks button.active span{color:var(--green)!important}.sideSettings{background:#fff!important}.section{border:1px solid var(--border)!important;border-radius:20px!important;box-shadow:var(--card-shadow)!important;padding:16px!important}.section:before{display:none!important}

/* Übersicht */
.nowSection{padding:17px!important}.nowSection .nowStrip{gap:10px!important}.nowSection .nowChip{min-height:92px!important;padding:14px 15px!important;border:1px solid var(--border)!important;border-radius:16px!important;background:#fff!important;box-shadow:none!important;display:grid!important;grid-template-columns:34px 1fr!important;align-items:center!important;column-gap:10px!important}.nowSection .nowIcon{font-size:24px!important;margin:0!important}.nowSection .nowLabel{font-size:9px!important;color:var(--ink-3)!important}.nowSection .nowChip strong{font-size:19px!important;color:var(--ink)!important;margin-top:2px!important}.nowSection .nowChip small{font-size:8px!important;color:var(--ink-3)!important}.nowSection .nowChip:first-child strong{color:var(--green)!important}.nowSection .nowChip:last-child strong{color:var(--yellow)!important}
.pvPhaseStatus{margin-top:10px!important;border-radius:14px!important;background:var(--yellow-soft)!important;border:1px solid #ead7a8!important}.pvPhaseMain>div:first-child>span,.pvPhaseMain>div:first-child>small,.pvPhaseClock span{color:var(--ink-3)!important}.pvPhaseMain>div:first-child>b,.pvPhaseClock>b{color:var(--ink)!important}
.overviewEnergyGrid{gap:12px!important}.energySection .balanceGrid{gap:9px!important}.energySection .balanceTile{min-height:82px!important;padding:12px!important;border:1px solid var(--border)!important;border-radius:15px!important;background:#fff!important;box-shadow:none!important}.energySection .balanceTile b{font-size:18px!important;color:var(--ink)!important}.energySection .pvTile b{color:var(--yellow)!important}.energySection .flowPlus b{color:var(--green)!important}.energySection .flowMinus b{color:var(--red-strong)!important}.overviewGoalCard{background:#fff!important}.goalRing strong{color:var(--ink)!important}.goalLink{background:var(--green)!important;color:#fff!important}

/* Planung: moderne 2x2-Karten und ruhige Segmentsteuerung. */
.nightSection{padding:17px!important}.nightSection .nightSummary{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:10px!important;background:transparent!important;border:0!important}.nightSection .planrow{min-height:100px!important;padding:15px 16px!important;border:1px solid var(--border)!important;border-radius:16px!important;background:#fff!important;box-shadow:none!important;grid-template-columns:36px 1fr!important}.nightSection .planico{font-size:25px!important}.nightSection .planrow strong{font-size:13px!important;color:var(--ink)!important}.nightSection .planrow span{font-size:9px!important;color:var(--ink-3)!important}.nightSection .planvalue{font-size:15px!important;color:var(--ink)!important;margin-top:5px!important}.nightSection .planExtra{color:var(--ink-3)!important}.nightControlRow{margin-top:12px!important}.nightSection .nightControls .button,.nightSection .socMenuButton{min-height:44px!important;border-radius:13px!important;background:#fff!important;color:var(--ink)!important;border:1px solid var(--border)!important;box-shadow:none!important}.nightSection .nightControls .button.active{background:var(--green-soft)!important;border-color:#b9d9c7!important;color:var(--ink)!important;box-shadow:inset 0 0 0 1px rgba(31,133,87,.08)!important}

/* PV: Tageskarten klarer, Zahlen schwarz; nur Graph/Planbadge als Akzent. */
.forecastRail{gap:12px!important}.forecastCard{border:1px solid var(--border)!important;border-radius:18px!important;background:#fff!important;box-shadow:none!important;padding:17px!important}.forecastKwh,.pvSwipeNow{color:var(--ink)!important}.forecastDay,.range,.liveHours,.hours{color:var(--ink-3)!important}.planMini{background:var(--yellow-soft)!important;border-color:#ead7a4!important;color:var(--ink)!important}.pvSwipeStats>div,.meta3 .mini{background:var(--surface-2)!important;border-radius:11px!important}.pvSwipeStats b,.meta3 b{color:var(--ink)!important}.pvPlanSection .pvBox{background:#fff!important;border:1px solid var(--border)!important;border-radius:16px!important;padding:14px!important}.pvPlanSection .pvHeadline h2,.pvPlanSection .budgetBig,.pvPlanSection .budgetItem b,.pvPlanSection .phaseRuleStep b,.pvPlanSection .soc b{color:var(--ink)!important}.pvQuickStatus{background:var(--blue-soft)!important;border-color:#cfe4ee!important}.pvQuickStatus b{color:var(--ink)!important}.pvPlanSection .phaseRuleStep.active{background:var(--green-soft)!important}.presenceSingle{background:var(--green-soft)!important;color:var(--ink)!important}

/* Lernen: Dashboard statt farbiger Textzeilen. */
.learningSection{padding:17px!important}.qualityLine{margin-top:10px!important;border:0!important;background:var(--surface-2)!important;padding:11px 13px!important;border-radius:13px!important;color:var(--ink)!important}.learningHero{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.learnMetric{border:1px solid var(--border);border-radius:16px;background:#fff;padding:14px;min-height:100px}.learnMetric .learnIcon{font-size:21px}.learnMetric span{display:block;color:var(--ink-3)!important;font-size:9px;margin-top:9px}.learnMetric b{display:block;color:var(--ink)!important;font-size:22px;letter-spacing:-.4px;margin-top:3px}.learnMetric small{display:block;color:var(--ink-3)!important;font-size:8px;margin-top:4px;line-height:1.3}.learningDetailGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:10px}.learnDetail{border:1px solid var(--border);border-radius:15px;background:var(--surface-2);padding:13px}.learnDetail strong{display:block;color:var(--ink)!important;font-size:11px}.learnDetail p{margin:7px 0 0;color:var(--ink-3)!important;font-size:9px;line-height:1.45}.calculationDetails{margin-top:10px!important;border:1px solid var(--border)!important;border-radius:16px!important;background:#fff!important}.calculationDetails summary{min-height:58px}.calcStat,.calcRows,.calcFormula{border-color:var(--border)!important}.calcRow.head{background:var(--surface-2)!important;color:var(--ink-3)!important}.calcFormula{background:var(--surface-2)!important;color:var(--ink)!important}

/* Steuerung */
.directSummary{gap:10px!important}.stateMini{min-height:80px!important;padding:14px!important;border:1px solid var(--border)!important;border-radius:16px!important;background:#fff!important}.stateMini b{font-size:14px!important;color:var(--ink)!important}.stateMini span{font-size:9px!important;color:var(--ink-3)!important}.controlDetails{margin-top:10px!important;border:1px solid var(--border)!important;border-radius:16px!important;background:#fff!important}.controlDetails summary{padding:14px 15px!important;color:var(--ink)!important}.modeBtn,.bigToggle,.phase{background:#fff!important;color:var(--ink)!important;border-color:var(--border)!important}.modeBtn.active,.bigToggle.on,.phase.on{background:var(--green-soft)!important;color:var(--ink)!important;border-color:#b9d9c7!important}

/* Einstellungen */
.settingCard{border:1px solid var(--border)!important;border-radius:16px!important;background:#fff!important;padding:15px!important}.settingCard h3{color:var(--ink)!important}.costNote,.modelStat,.modelStat span{color:var(--ink-3)!important}.modelStat b{color:var(--ink)!important}.switchline{color:var(--ink)!important}.save{background:var(--green)!important}

@media(max-width:980px){.learningHero{grid-template-columns:repeat(2,1fr)}.learningDetailGrid{grid-template-columns:1fr}.contentShell{padding-left:18px!important;padding-right:18px!important}}
@media(max-width:720px){
  .contentShell{padding-left:10px!important;padding-right:10px!important}.statusline{gap:4px!important;margin-top:7px!important}.statusitem{padding:8px 6px 8px 18px!important;font-size:8px!important}.statusitem:before{left:7px;width:6px;height:6px}.statusitem b{font-size:8.5px!important}
  .pageHead{padding-top:14px!important}.pageHead h2{font-size:25px!important}.section{padding:12px!important;border-radius:17px!important}.nowSection .nowStrip{grid-template-columns:repeat(2,1fr)!important}.nowSection .nowChip{min-height:84px!important;padding:11px!important;grid-template-columns:28px 1fr!important}.nowSection .nowIcon{font-size:21px!important}.nightSection .nightSummary{grid-template-columns:1fr!important}.nightSection .planrow{min-height:90px!important}.learningHero{grid-template-columns:repeat(2,1fr)}.learnMetric{min-height:94px;padding:12px}.learnMetric b{font-size:19px}.learningDetailGrid{grid-template-columns:1fr}.mobileTabs button{color:var(--ink-3)!important}.mobileTabs button.active{color:var(--ink)!important;background:var(--green-soft)!important}.mobileTabs button.active span{color:var(--green)!important}
}



/* 0.1.57 · Push-Transport + sofortiges Morgenlernen */
.nowSection .nowStrip{grid-template-columns:repeat(4,minmax(0,1fr))!important}
.nowSection .surplusChip{display:none!important}
.overviewEnergyGrid{grid-template-columns:minmax(0,1fr) 286px!important;gap:14px!important;align-items:stretch!important}
.energySection{min-width:0!important}.energyFlowHost{margin-top:10px;min-width:0}
.energyFlowStage{position:relative;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(3,minmax(94px,1fr));gap:18px 22px;min-height:354px;padding:8px;isolation:isolate}
.energyFlowSvg{position:absolute;inset:8px;width:calc(100% - 16px);height:calc(100% - 16px);z-index:0;overflow:visible;pointer-events:none}
.energyFlowSvg .flowBase{fill:none;stroke:#dbe4df;stroke-width:1.15;vector-effect:non-scaling-stroke}
.energyFlowSvg .flowPulse{fill:none;stroke-width:3;stroke-linecap:round;stroke-dasharray:.1 7;vector-effect:non-scaling-stroke;animation:energyFlowDots 1.15s linear infinite}
.energyFlowSvg .flowPulse.inactive{display:none}.energyFlowSvg .flowPulse.pv{stroke:#d99a21}.energyFlowSvg .flowPulse.battery{stroke:#299266}.energyFlowSvg .flowPulse.gridImport{stroke:#c94f49}.energyFlowSvg .flowPulse.gridExport{stroke:#299266}.energyFlowSvg .flowPulse.consumer{stroke:#4d8faf}
@keyframes energyFlowDots{to{stroke-dashoffset:-14}}
.flowNode{position:relative;z-index:1;min-width:0;border:1px solid var(--border);border-radius:16px;background:rgba(255,255,255,.98);box-shadow:0 5px 16px rgba(18,43,31,.045);padding:11px 12px;display:flex;align-items:center;gap:9px;overflow:hidden}
.flowNode .flowIcon{flex:0 0 32px;width:32px;height:32px;border-radius:11px;display:grid;place-items:center;background:var(--surface-2);font-size:20px}
.flowNode .flowText{min-width:0}.flowNode span{display:block;color:var(--ink-3)!important;font-size:8.5px;font-weight:800;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.flowNode b{display:block;color:var(--ink)!important;font-size:17px;line-height:1.08;margin-top:2px;white-space:nowrap}.flowNode small{display:block;color:var(--ink-3)!important;font-size:7.5px;line-height:1.2;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.flowNode.pv .flowIcon{background:var(--yellow-soft)}.flowNode.pv b{color:#9b6606!important}.flowNode.battery .flowIcon{background:var(--green-soft)}.flowNode.battery.isDischarging b{color:#176d47!important}.flowNode.battery.isCharging b{color:#176d47!important}.flowNode.grid .flowIcon{background:#f9efee}.flowNode.grid.importing b{color:var(--red-strong)!important}.flowNode.grid.exporting b{color:#176d47!important}.flowNode.house{border-color:#b8d7c7;background:linear-gradient(180deg,#fbfffc,#f2faf6);box-shadow:0 8px 24px rgba(31,133,87,.09);padding:13px}.flowNode.house .flowIcon{background:var(--green);color:#fff;width:38px;height:38px;flex-basis:38px;font-size:22px}.flowNode.house b{font-size:21px}.flowNode.consumer .flowIcon{background:var(--blue-soft)}
.flowSlot-battery{grid-column:1;grid-row:1}.flowSlot-pv{grid-column:2;grid-row:1}.flowSlot-grid{grid-column:3;grid-row:1}.flowSlot-wallbox{grid-column:1;grid-row:2}.flowSlot-house{grid-column:2;grid-row:2}.flowSlot-heatpump{grid-column:3;grid-row:2}.flowSlot-dishwasher{grid-column:1;grid-row:3}.flowSlot-office{grid-column:2;grid-row:3}.flowSlot-kids{grid-column:3;grid-row:3}
.energyFlowLegend{margin:8px 8px 0;display:flex;flex-wrap:wrap;gap:7px 13px;color:var(--ink-3);font-size:8px}.energyFlowLegend span{display:flex;align-items:center;gap:5px}.energyFlowLegend i{width:7px;height:7px;border-radius:50%;display:inline-block}.energyFlowLegend .lPv{background:#d99a21}.energyFlowLegend .lSource{background:#299266}.energyFlowLegend .lGrid{background:#c94f49}.energyFlowLegend .lLoad{background:#4d8faf}

.overviewGoalCard{min-width:0!important;padding:16px!important;display:flex!important;flex-direction:column!important;justify-content:space-between!important}.overviewGoalCard .goalTop{display:block!important}.overviewGoalCard .eyebrow{text-align:center!important}.overviewGoalCard .goalRing{width:112px!important;height:112px!important;margin:10px auto 12px!important}.overviewGoalCard .goalRing:before{inset:11px!important}.overviewGoalCard .goalRing strong{font-size:26px!important}.overviewGoalCard .goalFacts{gap:0!important}.overviewGoalCard .goalFacts>div{padding:8px 0!important}.overviewGoalCard .goalFacts span{font-size:8px!important}.overviewGoalCard .goalFacts b{font-size:10px!important;max-width:120px}.overviewGoalCard .goalLink{margin-top:12px!important;font-size:9px!important;padding:10px!important}

.nextActionsSection{padding:0!important;overflow:hidden!important}.nextActionsButton{width:100%;border:0;background:#fff;color:var(--ink);display:grid;grid-template-columns:170px minmax(0,1fr) 26px;align-items:center;gap:14px;padding:13px 16px;cursor:pointer;text-align:left}.nextActionsButton:hover{background:#fbfdfc}.nextActionsTitle strong{display:block;font-size:11px;color:var(--ink)!important}.nextActionsTitle small{display:block;font-size:8px;color:var(--ink-3)!important;margin-top:2px}.nextActionItems{display:flex;align-items:center;min-width:0;gap:7px 16px;flex-wrap:wrap}.nextActionItem{display:inline-flex;align-items:center;gap:6px;min-width:0;color:var(--ink-2)!important;font-size:9px;white-space:nowrap}.nextActionItem .naIcon{font-size:15px}.nextActionItem b{font-size:9px;color:var(--ink)!important}.nextActionArrow{font-size:24px;color:#77847e!important;text-align:right}

/* Berechnung: jede Morgenstunde als gut lesbarer Rechenschritt. */
.calcTimeline{display:grid;gap:7px}.calcHour{border:1px solid var(--border);border-radius:13px;background:#fff;padding:10px 11px}.calcHourHead{display:flex;justify-content:space-between;align-items:baseline;gap:10px}.calcHourHead b{font-size:11px;color:var(--ink)!important}.calcHourHead strong{font-size:11px;color:var(--ink)!important}.calcHourFormula{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:7px}.calcPart{background:var(--surface-2);border-radius:9px;padding:7px 8px}.calcPart span{display:block;font-size:7.5px;color:var(--ink-3)!important}.calcPart b{display:block;font-size:9px;color:var(--ink)!important;margin-top:2px}.calcTotal{margin-top:10px;border:1px solid #cfe0d7;border-radius:13px;background:#f7fbf8;padding:11px}.calcTotal h4{margin:0 0 7px;font-size:11px;color:var(--ink)}.calcEquationLine{display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-bottom:1px solid #e5ece8;font-size:9px}.calcEquationLine:last-child{border-bottom:0}.calcEquationLine span{color:var(--ink-3)!important}.calcEquationLine b{color:var(--ink)!important;text-align:right}.calcEquationLine.result{margin-top:4px;padding-top:8px;border-top:1px solid #cfe0d7;border-bottom:0}.calcEquationLine.result span,.calcEquationLine.result b{font-size:11px;font-weight:900;color:var(--ink)!important}

/* Eigene Steuerungsseite ist sofort offen. */
.controlDetails[open]>summary{border-bottom:1px solid var(--border);background:var(--surface-2)}

@media(max-width:1050px){.overviewEnergyGrid{grid-template-columns:1fr!important}.overviewGoalCard{margin-top:0!important}.overviewGoalCard .goalTop{display:grid!important;grid-template-columns:132px 1fr!important;align-items:center!important;gap:12px!important}.overviewGoalCard .eyebrow{text-align:left!important}.overviewGoalCard .goalRing{margin:8px 0!important}.nextActionsButton{grid-template-columns:150px minmax(0,1fr) 24px}}
@media(max-width:720px){
  .nowSection .nowStrip{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .overviewEnergyGrid{display:block!important}.energySection{padding:10px!important}.energyFlowStage{grid-template-rows:repeat(3,82px);gap:10px 8px;min-height:276px;padding:3px}.energyFlowSvg{inset:3px;width:calc(100% - 6px);height:calc(100% - 6px)}.flowNode{border-radius:13px;padding:7px 7px;gap:5px;box-shadow:none}.flowNode .flowIcon{width:25px;height:25px;flex-basis:25px;border-radius:8px;font-size:16px}.flowNode span{font-size:7px}.flowNode b{font-size:12.5px}.flowNode small{display:none}.flowNode.house{padding:7px}.flowNode.house .flowIcon{width:28px;height:28px;flex-basis:28px;font-size:17px}.flowNode.house b{font-size:14px}.energyFlowLegend{font-size:7px;margin-top:6px;gap:5px 9px}.overviewGoalCard{margin-top:9px!important}.overviewGoalCard .goalTop{display:grid!important;grid-template-columns:104px 1fr!important;gap:10px!important}.overviewGoalCard .eyebrow{text-align:left!important}.overviewGoalCard .goalRing{width:88px!important;height:88px!important;margin:7px 0!important}.overviewGoalCard .goalRing:before{inset:9px!important}.overviewGoalCard .goalRing strong{font-size:21px!important}.overviewGoalCard .goalFacts>div{padding:6px 0!important}.overviewGoalCard .goalLink{min-height:40px!important}
  .nextActionsSection{margin-top:9px!important}.nextActionsButton{grid-template-columns:1fr 22px;gap:8px;padding:11px 12px}.nextActionsTitle{grid-column:1}.nextActionItems{grid-column:1;gap:6px 12px}.nextActionArrow{grid-column:2;grid-row:1/3;align-self:center}.nextActionItem{font-size:8px}.nextActionItem b{font-size:8px}.nextActionItem .naIcon{font-size:13px}
  .calcIntro{grid-template-columns:repeat(2,1fr)!important}.calcHour{padding:9px}.calcHourFormula{grid-template-columns:1fr 1fr 1fr;gap:4px}.calcPart{padding:6px}.calcPart span{font-size:6.8px}.calcPart b{font-size:8px}.calcEquationLine{font-size:8px}
}



/* 0.1.55 · Energiefluss als Ebenenmodell: Quellen oben, Haus Mitte, Verbraucher unten. */
.energyFlowStage{position:relative;display:grid;grid-template-columns:repeat(15,minmax(0,1fr));grid-template-rows:104px 100px 104px;gap:20px 10px;min-height:360px;padding:10px 6px 4px;isolation:isolate}
.energyFlowSvgDesktop,.energyFlowSvgMobile{position:absolute;z-index:0;pointer-events:none;overflow:visible}.energyFlowSvgDesktop{inset:7px 6px 2px;width:calc(100% - 12px);height:calc(100% - 9px)}.energyFlowSvgMobile{display:none}
.energyFlowSvgDesktop .flowBase,.energyFlowSvgMobile .flowBase{fill:none;stroke:#dbe4df;stroke-width:1.2;vector-effect:non-scaling-stroke}
.energyFlowSvgDesktop .flowBus,.energyFlowSvgMobile .flowBus{fill:none;stroke:#cfdbd5;stroke-width:1.8;vector-effect:non-scaling-stroke}
.energyFlowSvgDesktop .flowPulse,.energyFlowSvgMobile .flowPulse{fill:none;stroke-width:3.2;stroke-linecap:round;stroke-dasharray:.1 7;vector-effect:non-scaling-stroke;animation:energyFlowDots 1.15s linear infinite}
.energyFlowStage .flowPulse.pv{stroke:#d99a21}.energyFlowStage .flowPulse.battery{stroke:#299266}.energyFlowStage .flowPulse.gridImport{stroke:#c94f49}.energyFlowStage .flowPulse.gridExport{stroke:#299266}.energyFlowStage .flowPulse.consumer{stroke:#4d8faf}
.flowNode{z-index:2}.flowSlot-pv{grid-column:1/6;grid-row:1}.flowSlot-grid{grid-column:6/11;grid-row:1}.flowSlot-battery{grid-column:11/16;grid-row:1}.flowSlot-house{grid-column:6/11;grid-row:2}.flowSlot-wallbox{grid-column:1/4;grid-row:3}.flowSlot-heatpump{grid-column:4/7;grid-row:3}.flowSlot-dishwasher{grid-column:7/10;grid-row:3}.flowSlot-office{grid-column:10/13;grid-row:3}.flowSlot-kids{grid-column:13/16;grid-row:3}
.flowNode.source{min-height:100px}.flowNode.consumer{min-height:100px}.flowNode.house{min-height:96px;justify-content:center}
.flowAmount{position:absolute;z-index:3;transform:translate(-50%,-50%);padding:3px 7px;border:1px solid #dbe4df;border-radius:999px;background:rgba(255,255,255,.97);box-shadow:0 2px 8px rgba(18,43,31,.05);font-size:7.5px;font-weight:900;color:var(--ink)!important;white-space:nowrap;line-height:1}.flowAmount.pv{left:32%;top:36%;color:#9b6606!important}.flowAmount.grid{left:50%;top:35%;}.flowAmount.battery{left:68%;top:36%;color:#176d47!important}.flowAmount.wallbox{left:10%;top:70%}.flowAmount.heatpump{left:30%;top:70%}.flowAmount.dishwasher{left:50%;top:70%}.flowAmount.office{left:70%;top:70%}.flowAmount.kids{left:90%;top:70%}
.energyFlowLegend{display:none!important}
.energyFlowHint{margin:7px 8px 0;color:var(--ink-3)!important;font-size:8px;line-height:1.35}.energyFlowHint b{color:var(--ink)!important}
.nextActionItems{justify-content:flex-start}.nextActionItem.storageAction{display:none!important}
@media(max-width:720px){
  /* 0.1.55 · Mobile Energiefluss: kompaktere Knoten, sichtbare Leitungswege und Tageswerte. */
  .energyFlowStage{grid-template-columns:repeat(6,minmax(0,1fr));grid-template-rows:64px 76px 58px 58px 58px;gap:16px 8px;min-height:382px;padding:2px 2px 0}
  .energyFlowSvgDesktop{display:none}.energyFlowSvgMobile{display:block;inset:2px;width:calc(100% - 4px);height:calc(100% - 4px)}
  .flowSlot-pv{grid-column:1/3;grid-row:1}.flowSlot-grid{grid-column:3/5;grid-row:1}.flowSlot-battery{grid-column:5/7;grid-row:1}.flowSlot-house{grid-column:2/6;grid-row:2}.flowSlot-wallbox{grid-column:1/4;grid-row:3}.flowSlot-heatpump{grid-column:4/7;grid-row:3}.flowSlot-dishwasher{grid-column:1/4;grid-row:4}.flowSlot-office{grid-column:4/7;grid-row:4}.flowSlot-kids{grid-column:2/6;grid-row:5}
  .flowNode.source,.flowNode.consumer,.flowNode.house{min-height:0}.flowNode{border-radius:11px!important;padding:5px 6px!important;gap:4px!important;box-shadow:0 2px 8px rgba(18,43,31,.035)!important}.flowNode .flowIcon{width:21px!important;height:21px!important;flex-basis:21px!important;border-radius:7px!important;font-size:13px!important}.flowNode .flowText{line-height:1.02}.flowNode span{font-size:6.1px!important}.flowNode b{font-size:10.2px!important;margin-top:1px!important}.flowNode small{display:block!important;color:var(--ink-3)!important;font-size:5.7px!important;line-height:1.08!important;margin-top:2px!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important}.flowNode.house{padding:6px 8px!important}.flowNode.house .flowIcon{width:26px!important;height:26px!important;flex-basis:26px!important;font-size:15px!important}.flowNode.house b{font-size:13px!important}.flowNode.house small{font-size:6px!important}
  .energyFlowSvgMobile .flowBase,.energyFlowSvgMobile .flowBus{stroke-width:1.45}.energyFlowSvgMobile .flowPulse{stroke-width:2.8;stroke-dasharray:.1 6}
  .flowAmount{display:none!important}.energyFlowHint{font-size:7.2px;margin:7px 4px 0}
}


/* 0.1.55 · Energiefluss Feinschliff: kompaktere Knoten, vollständig zentrierter Inhalt */
.energyFlowStage{
  grid-template-rows:88px 76px 84px!important;
  gap:22px 10px!important;
  min-height:322px!important;
  padding:8px 6px 4px!important;
}
.flowNode{
  flex-direction:column!important;
  justify-content:center!important;
  align-items:center!important;
  text-align:center!important;
  gap:4px!important;
  padding:8px 10px!important;
}
.flowNode .flowIcon{margin:0 auto!important;width:28px!important;height:28px!important;flex-basis:28px!important;border-radius:9px!important;font-size:17px!important}
.flowNode .flowText{width:100%!important;min-width:0!important;text-align:center!important}
.flowNode span,.flowNode b,.flowNode small{text-align:center!important;margin-left:auto!important;margin-right:auto!important}
.flowNode span{font-size:7.8px!important}
.flowNode b{font-size:15px!important;margin-top:1px!important}
.flowNode small{font-size:7px!important;margin-top:2px!important;max-width:100%!important}
.flowNode.source{min-height:82px!important;align-self:center!important}
.flowNode.consumer{min-height:72px!important;width:88%!important;justify-self:center!important;align-self:center!important}
.flowSlot-house{grid-column:7/10!important}
.flowNode.house{min-height:62px!important;width:86%!important;justify-self:center!important;align-self:center!important;padding:7px 9px!important}
.flowNode.house .flowIcon{width:30px!important;height:30px!important;flex-basis:30px!important;font-size:18px!important}
.flowNode.house b{font-size:17px!important}
.flowNode.house small{font-size:6.8px!important}

@media(max-width:720px){
  .energyFlowStage{
    grid-template-rows:60px 54px 48px 48px 46px!important;
    gap:18px 8px!important;
    min-height:328px!important;
    padding:2px!important;
  }
  .flowNode{
    flex-direction:column!important;
    justify-content:center!important;
    align-items:center!important;
    text-align:center!important;
    padding:4px 5px!important;
    gap:2px!important;
  }
  .flowNode .flowText{width:100%!important;text-align:center!important;line-height:1.02!important}
  .flowNode span,.flowNode b,.flowNode small{text-align:center!important;margin-left:auto!important;margin-right:auto!important}
  .flowNode .flowIcon{width:18px!important;height:18px!important;flex-basis:18px!important;border-radius:6px!important;font-size:11px!important}
  .flowNode span{font-size:5.8px!important}
  .flowNode b{font-size:9.5px!important;margin-top:0!important}
  .flowNode small{display:block!important;font-size:5.2px!important;line-height:1.05!important;margin-top:1px!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important}
  .flowNode.source{width:96%!important;justify-self:center!important;min-height:0!important}
  .flowSlot-house{grid-column:2/6!important}
  .flowNode.house{width:68%!important;min-height:0!important;padding:4px 6px!important}
  .flowNode.house .flowIcon{width:21px!important;height:21px!important;flex-basis:21px!important;font-size:12px!important}
  .flowNode.house b{font-size:11.5px!important}
  .flowNode.house small{font-size:5.3px!important}
  .flowNode.consumer{width:82%!important;min-height:0!important;justify-self:center!important}
}

/* 0.1.58 · iPhone-Safe-Area, Speicherpriorität und kompakte PV-Tageszeile */
.pvDayProgressSection{margin-top:9px!important;padding:9px 12px!important;display:grid;grid-template-columns:auto repeat(3,minmax(0,1fr));align-items:center;gap:10px;border-radius:14px!important;box-shadow:var(--card-shadow)!important}.pvProgressTitle{font-size:8px;font-weight:950;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3)}.pvProgressMetric{min-width:0;padding-left:10px;border-left:1px solid var(--border)}.pvProgressMetric span{display:block;font-size:7px;color:var(--ink-3)}.pvProgressMetric b{display:block;font-size:12px;color:var(--ink)!important;margin-top:1px;white-space:nowrap}.pvProgressMetric.good b{color:var(--green)!important}.pvProgressMetric.low b{color:var(--red-strong)!important}.pvAutoPauseBtn{flex:0 0 auto;border:1px solid #bdd8ca;background:#fff;color:#176d47;border-radius:9px;padding:6px 8px;font-size:8px;font-weight:900;cursor:pointer;white-space:nowrap}.pvAutoPauseBtn.paused{border-color:#e2c89b;background:#fff8e8;color:#8b620a}.pvPhaseMain{width:100%}.pvPhaseStatus.withAutoControl{display:flex;align-items:center;gap:8px}.pvPhaseStatus.withAutoControl>.pvPhaseMain{min-width:0}.nowSection .nowChip:nth-child(2) small{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;line-height:1.15!important}.carMiniState{display:block;margin-top:2px;font-size:7px!important;color:var(--ink-3)!important}
@media(max-width:720px){
  .mobileTop{padding-top:calc(10px + max(env(safe-area-inset-top),22px))!important;min-height:calc(68px + env(safe-area-inset-top));align-items:flex-end!important}.mobileTop .iconButton{margin-bottom:2px}.pvDayProgressSection{grid-template-columns:1fr 1fr 1fr!important;gap:0!important;padding:8px 7px!important}.pvProgressTitle{display:none}.pvProgressMetric{padding:0 6px;border-left:1px solid var(--border)}.pvProgressMetric:first-of-type{border-left:0}.pvProgressMetric span{font-size:6px}.pvProgressMetric b{font-size:10px}.pvPhaseStatus.withAutoControl{align-items:stretch;gap:6px}.pvAutoPauseBtn{padding:5px 6px;font-size:7px;align-self:stretch}.nowSection .nowChip:nth-child(2) .carMiniState{font-size:6.3px!important}.contentShell{padding-top:0!important}
}
</style>
</head>
<body>
<div class="appShell">
  <aside class="sideNav">
    <div class="sideBrand"><div class="mark"></div><div><strong>Energieplaner</strong><span>PV · Speicher · Wallbox</span></div></div>
    <nav class="sideLinks">
      <button class="appNav active" data-page="overview"><span>⌂</span>Übersicht</button>
      <button class="appNav" data-page="planning"><span>◷</span>Planung</button>
      <button class="appNav" data-page="pv"><span>☀</span>PV & Laden</button>
      <button class="appNav" data-page="learning"><span>◎</span>Prognose & Lernen</button>
      <button class="appNav" data-page="control"><span>⚙</span>Steuerung</button>
    </nav>
    <button type="button" class="sideSettings" data-page="settings" onclick="showPage('settings');return false;">⚙ Einstellungen</button>
    <div class="sideVersion">v<span id="sideVersion">0.1.58</span> · Port 8150</div>
  </aside>

  <div class="contentShell">
    <header class="mobileTop">
      <div class="brand"><div class="mark"></div><div><h1>Energieplaner</h1><div class="sub">PV · Speicher · Wallbox · Warmwasser</div></div></div>
      <button type="button" class="iconButton" data-page="settings" onclick="showPage('settings');return false;" aria-label="Einstellungen">⚙</button>
    </header>
    <div class="statusline" id="statusbar"></div><div id="statusAlert"></div>

    <main id="dashboard" class="view show">
      <section class="appPage show" data-page-panel="overview">
        <div class="pageHead"><div><div class="pageKicker">Energieplaner</div><h2>Übersicht</h2><p>Aktueller Zustand und die wichtigsten Entscheidungen auf einen Blick.</p></div></div>
        <section class="section nowSection"><div class="eyebrow">Was passiert gerade?</div><div class="nowStrip" id="nowStrip"></div><div id="pvPhaseStatus" class="pvPhaseStatus"></div></section>
        <div class="overviewEnergyGrid"><section class="section energySection"><div class="eyebrow">Energiefluss · jetzt</div><div class="energyFlowHost" id="balanceGrid"></div></section><aside class="section overviewGoalCard" id="overviewGoalCard"></aside></div>
        <section class="section pvDayProgressSection" id="pvDayProgress"></section>
        <section class="section nextActionsSection" id="nextActionsSection"><button class="nextActionsButton" id="nextActionsButton" onclick="showPage('planning')"></button></section>
      </section>

      <section class="appPage" data-page-panel="planning">
        <div class="pageHead"><div><div class="pageKicker">Nacht & Morgen</div><h2>Planung</h2><p>Speicher, Fahrzeuge, Spülmaschine und Warmwasser für die nächste Nacht.</p></div></div>
        <section class="section nightSection"><div class="eyebrow">Was passiert heute Nacht / morgen?</div><div class="nightSummary" id="nightSummary"></div><div class="nightControlRow"><div class="nightControls" id="nightChoices"></div><button class="socMenuButton" id="socMenuButton" onclick="toggleSocMenu()">🎯 SOC</button></div><div class="socDropdown" id="socDropdown"><div class="targetQuick" id="nightTarget"></div></div></section>
      </section>

      <section class="appPage" data-page-panel="pv">
        <div class="pageHead"><div><div class="pageKicker">Erzeugung & Fahrzeuge</div><h2>PV & Laden</h2><p>PV-Prognosen, Tagesbudget und gemeinsame Wallbox in einem Bereich.</p></div></div>
        <section class="section"><div class="eyebrow">PV · Heute / Morgen / Übermorgen</div><div class="forecastRail" id="forecastRail"></div><div class="forecastDots" id="forecastDots"></div><div class="swipeHint">↔ Tageskarten wischen</div></section>
        <section class="section pvPlanSection"><div class="eyebrow">PV-Laden · gemeinsame Wallbox</div><div id="pvBox" class="pvBox"></div></section>
      </section>

      <section class="appPage" data-page-panel="learning">
        <div class="pageHead"><div><div class="pageKicker">Transparenz & Lernwerte</div><h2>Prognose & Lernen</h2><p>Warum die App so plant – inklusive nachvollziehbarer Morgenberechnung.</p></div></div>
        <section class="section learningSection"><div class="eyebrow">Prognose & Lernen</div><div class="qualityLine" id="qualityLine"></div><div class="learningSummary" id="learningSummary"></div>
          <details class="calculationDetails" id="calculationDetails"><summary><span><b>Berechnung öffnen</b><small>05:00-Ziel Schritt für Schritt nachvollziehen</small></span><span class="chevron">›</span></summary><div class="calculationInner" id="morningCalculation"></div></details>
        </section>
      </section>

      <section class="appPage" data-page-panel="control">
        <div class="pageHead"><div><div class="pageKicker">Manuell eingreifen</div><h2>Steuerung</h2><p>Wallbox, Phasen, Speicher und Warmwasser direkt schalten.</p></div></div>
        <section class="section"><div class="eyebrow">Direktsteuerung</div><div class="directSummary" id="directSummary"></div><details class="controlDetails" open><summary>Sofort steuern · Wallbox, Phasen, Speicher und Warmwasser</summary><div class="controlInner"><div class="modeSwitch" id="wallboxModes"></div><div class="phaseRow" id="phaseRow"></div><button id="batteryControl" class="bigToggle" onclick="toggleBatteryNow()"></button><button id="warmwaterControl" class="bigToggle" onclick="toggleWarmwaterNow()"></button></div></details></section>
      </section>

      <section class="appPage" data-page-panel="settings">
        <div class="pageHead settingsHead"><div><div class="pageKicker">Konfiguration</div><h2>Einstellungen</h2><p>Automatik, Fahrzeuge, Speicherlernen, PV-Phasen und Benachrichtigungen.</p></div><button class="backButton" onclick="goBackFromSettings()">← Zurück</button></div>

    <section class="section"><div class="eyebrow">Einstellungen</div><div id="settingsAlert"></div><div class="settingsGrid">
      <div class="settingCard"><h3>Automatik</h3><div id="masterToggles"></div></div>
      <div class="settingCard"><h3>Fahrzeuge</h3><div class="field"><label>ID.7 Normalziel (%)</label><input type="number" id="id7_target_soc" min="20" max="100"></div><div class="field"><label>ID.7 Mindest-SOC (%)</label><input type="number" id="id7_min_morning_soc" min="10" max="100"></div><div class="field"><label>e-Golf Normalziel (%)</label><input type="number" id="egolf_target_soc" min="20" max="100"></div><div class="field"><label>e-Golf Mindest-SOC (%)</label><input type="number" id="egolf_min_morning_soc" min="10" max="100"></div><div class="field"><label>Gemeinsames Nachtziel (%)</label><input type="number" id="car_night_target_soc" min="20" max="100"></div></div>
      <div class="settingCard"><h3>Speicher · dynamisches 05:00-Ziel</h3><div id="morningLearningCard" class="pvInfo">Start-Grundlast 0,85 kW · Mindestreserve 5 %. Die App lernt Grundlast, Morgenbedarf und Reserve aus echten Verläufen weiter.</div></div>
      <div class="settingCard"><h3>PV-Phasen</h3><div class="pvInfo">Jede Entscheidung nutzt den wirklich für die Wallbox verfügbaren Überschuss nach Haus und Speicher. Aus „gesperrt“ startet Phase 1 nur oberhalb ihres Startwerts; unter ihrem Stoppwert wird wieder gesperrt. Phase 2 und 3 werden nur bei dauerhaft stabilem Mehrüberschuss ergänzt.</div><div class="pvInfo" id="wallboxWatchdogInfo">🛡️ Sicherheitswächter aktiv · eigener 10-Sekunden-Takt</div><div class="field"><label>Phase 1 an ab (W)</label><input type="number" min="0" step="50" id="pv_phase1_start_w"></div><div class="field"><label>Phase 1 aus unter (W)</label><input type="number" min="0" step="50" id="pv_phase1_stop_w"></div><div class="field"><label>Phase 2 dazu ab (W)</label><input type="number" min="0" step="50" id="pv_phase2_start_w"></div><div class="field"><label>Phase 2 raus unter (W)</label><input type="number" min="0" step="50" id="pv_phase2_stop_w"></div><div class="field"><label>Phase 3 dazu ab (W)</label><input type="number" min="0" step="50" id="pv_phase3_start_w"></div><div class="field"><label>Phase 3 raus unter (W)</label><input type="number" min="0" step="50" id="pv_phase3_stop_w"></div><div class="field"><label>Start Phase 1 / Sperren: stabil (Sekunden)</label><input type="number" min="30" step="30" id="pv_surplus_delay_seconds"></div><div class="field"><label>Phase 2 / 3 dazu: stabil über Schwelle (Sekunden)</label><input type="number" min="30" step="30" id="pv_phase_hold_seconds"></div></div>
      <div class="settingCard"><h3>PV-Budget & Speicherlernen</h3><div class="field"><label>Gelernte Grundlast 05:00–24:00 (kW)</label><input type="number" step="0.01" min="0.55" max="1.30" id="day_house_base_kw"></div><div class="field"><label>Manuelle 05:00-SOC-Korrektur (%)</label><input type="number" step="1" min="-10" max="10" id="battery_soc_manual_offset"></div><button class="testPushBtn actionFeedbackBtn" onclick="resetSocOffset(this)">↺ SOC-Korrektur auf 0</button><div class="field"><label>Startwert Abendreserve Speicher (kWh)</label><input type="number" step="0.1" id="evening_reserve_start_kwh"></div><div class="field"><label>Sicherheitsaufschlag Abendreserve (kWh)</label><input type="number" step="0.1" id="evening_reserve_margin_kwh"></div><div class="field"><label>Warmwasser geschätzt (kWh)</label><input type="number" step="0.1" id="warmwater_estimated_kwh"></div><div class="field"><label>PV-Budget Sicherheitsreserve (kWh)</label><input type="number" step="0.1" id="pv_budget_safety_kwh"></div><div class="field"><label>Mindestens fürs Auto verfügbar (kWh)</label><input type="number" step="0.1" id="car_budget_min_kwh"></div></div>
      <div class="settingCard"><h3>Warmwasser</h3><div class="field"><label>Nachts bei Planwert unter (kWh)</label><input type="number" step="0.5" id="warmwater_night_threshold_kwh"></div><div class="field"><label>Dauer (Minuten)</label><input type="number" id="warmwater_duration_minutes"></div></div>
      <div class="settingCard"><h3>Benachrichtigungen</h3><div class="field"><label>primary · Notify-Service</label><input id="notify_service"></div><div class="field"><label>secondary · Notify-Service</label><input id="partner_notify_service"></div><div class="field"><label>Abend-Push (Gemini 5 Min. vorher)</label><input type="time" id="forecast_main_time"></div><div class="field"><label>Morgen-Push (Gemini 5 Min. vorher)</label><input type="time" id="forecast_morning_time"></div><div class="pushButtonGrid"><button id="testPushBtn" class="testPushBtn actionFeedbackBtn" onclick="testPush(this)">🔔 Test primary</button><button id="testPartnerPushBtn" class="testPushBtn actionFeedbackBtn" onclick="testPartnerPush(this)">🔔 Test secondary</button></div></div>
      <div class="settingCard"><h3>Gemini · Sparmodus</h3><div class="field"><label>Max. erfolgreiche Gemini-Prognosen pro Tag</label><input type="number" id="gemini_daily_limit" min="2" max="6"></div><div class="field"><label>Manueller Cooldown (Minuten)</label><input type="number" id="gemini_manual_cooldown_minutes" min="5" max="180"></div><div class="costNote">Normalfall: <b>2 feste Gemini-Läufe pro Tag</b> – jeweils 5 Minuten vor dem 07:00- und dem 20:00-Push. Diese beiden Termine haben Vorrang vor manuellen oder Startup-Aufrufen; Live-PV selbst nutzt kein Gemini.</div></div>
      <div class="settingCard"><h3>Modellstatus</h3><div class="modelGrid" id="learningDetails"></div></div>
    </div><button id="saveSettingsBtn" class="save actionFeedbackBtn" onclick="saveSettings(this)">Einstellungen speichern</button></section>

      </section>
      <div class="footer">Energieplaner v<span id="version"></span> · Port 8150</div>
    </main>
  </div>
</div>

<nav class="mobileTabs" aria-label="Hauptnavigation">
  <button class="appNav active" data-page="overview"><span>⌂</span><small>Übersicht</small></button>
  <button class="appNav" data-page="planning"><span>◷</span><small>Planung</small></button>
  <button class="appNav" data-page="pv"><span>☀</span><small>PV</small></button>
  <button class="appNav" data-page="learning"><span>◎</span><small>Lernen</small></button>
  <button class="appNav" data-page="control"><span>⚙</span><small>Steuerung</small></button>
</nav>
<div class="toast" id="toast"></div>
<script>
let DATA=null,refreshTimer=null,DASHBOARD_SYNC_MS=Date.now(),PV_TIMER={signature:null,candidate:0,status:0,charging:0,phase:0,syncedAt:Date.now()};const UI_PENDING={nightOverride:null,nightTarget:null,carPresence:null};const q=s=>document.querySelector(s);const api=p=>{const base=(location.pathname||'/').replace(/\/$/,'');return (base||'')+'/api/'+p};function fmt(v,d=1){const n=Number(v);return Number.isFinite(n)?n.toFixed(d).replace('.',','):'–'}function toast(t){const e=q('#toast');e.textContent=t;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),1800)}function pvTimer(c,key){const now=Date.now(),candidateToken=String(c.candidate_token||''),statusToken=String(c.status_token||''),chargingToken=String(c.charging_token||''),phaseToken=String(c.phase_token||''),signature=candidateToken?`candidate|${candidateToken}`:`status|${key}|${statusToken}`,serverCandidate=Math.max(0,Number(c.candidate_elapsed_seconds||0)),serverStatus=Math.max(0,Number(c.status_elapsed_seconds||0)),serverCharging=Math.max(0,Number(c.charging_elapsed_seconds||0)),serverPhase=Math.max(0,Number(c.phase_elapsed_seconds||0));if(PV_TIMER.signature!==signature){PV_TIMER={signature,candidate:serverCandidate,status:serverStatus,charging:serverCharging,phase:serverPhase,syncedAt:now}}else{const elapsed=Math.max(0,(now-PV_TIMER.syncedAt)/1000);PV_TIMER.candidate=Math.max(PV_TIMER.candidate+elapsed,serverCandidate);PV_TIMER.status=Math.max(PV_TIMER.status+elapsed,serverStatus);PV_TIMER.charging=chargingToken?Math.max(PV_TIMER.charging+elapsed,serverCharging):0;PV_TIMER.phase=phaseToken?Math.max(PV_TIMER.phase+elapsed,serverPhase):0;PV_TIMER.syncedAt=now}return{candidate:PV_TIMER.candidate,status:PV_TIMER.status,charging:PV_TIMER.charging,phase:PV_TIMER.phase}}
async function getData(silent=false){try{const r=await fetch(api('dashboard'),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const j=await r.json();if(UI_PENDING.nightOverride!==null){if(j.night_override===UI_PENDING.nightOverride)UI_PENDING.nightOverride=null;else j.night_override=UI_PENDING.nightOverride}if(UI_PENDING.nightTarget!==null){const got=Number(j.plan?.wallbox?.night_target_soc);if(got===Number(UI_PENDING.nightTarget))UI_PENDING.nightTarget=null;else{j.plan=j.plan||{};j.plan.wallbox=j.plan.wallbox||{};j.plan.wallbox.night_target_soc=Number(UI_PENDING.nightTarget);j.plan.wallbox.night_target_is_override=true}}if(UI_PENDING.carPresence!==null){if(Boolean(j.car_at_wallbox)===Boolean(UI_PENDING.carPresence))UI_PENDING.carPresence=null;else j.car_at_wallbox=Boolean(UI_PENDING.carPresence)}DATA=j;DASHBOARD_SYNC_MS=Date.now();render()}catch(e){if(!silent)toast('Verbindung fehlgeschlagen')}}
async function getPvStatus(){if(!DATA)return;try{const r=await fetch(api('pv-status'),{cache:'no-store'});if(!r.ok)return;const j=await r.json(),c=j.pv_surplus_control||{};DATA.pv_surplus_control=c;DATA.live=DATA.live||{};if(c.power_w!==null&&c.power_w!==undefined)DATA.live.pv_minus_house_w=Number(c.power_w);renderPvPhaseStatus()}catch(e){}}
function refreshSoon(ms=1400){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>getData(true),ms)}
async function post(path,body){const r=await fetch(api(path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j}
function relativeLabel(ds){if(!ds)return'–';const d=new Date(ds+'T12:00:00'),n=new Date(DATA.time);const a=new Date(n.getFullYear(),n.getMonth(),n.getDate()),b=new Date(d.getFullYear(),d.getMonth(),d.getDate());const x=Math.round((b-a)/86400000);return x===0?'Heute':x===1?'Morgen':x===2?'Übermorgen':d.toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit'})}
function forecastCard(item){if(!item)return'';const c=item.calibrated||{},w=item.weather||{},rows=(item.hourly||[]).filter(r=>{const h=Number(String(r.time).slice(11,13));return h>=6&&h<=21});const max=Math.max(1,...rows.map(r=>Number(r.radiation_wm2||0)));const bars=rows.map(r=>`<div class="bar" style="height:${Math.max(2,Number(r.radiation_wm2||0)/max*100)}%"></div>`).join('');return `<article class="forecastCard"><div class="forecastTop"><div><div class="forecastDay">${relativeLabel(w.date)} · ${w.date||''}</div><div class="forecastKwh">${fmt(c.expected_kwh)} <small>kWh</small></div><div class="range">${fmt(c.conservative_kwh)}–${fmt(c.optimistic_kwh)} kWh</div></div><div class="planMini">Plan ${fmt(c.plan_kwh)}</div></div><div class="spark">${bars}</div><div class="hours"><span>06</span><span>09</span><span>12</span><span>15</span><span>18</span><span>21</span></div><div class="meta3"><div class="mini"><b>${fmt(w.ghi_kwh_m2,2)}</b><span>GHI kWh/m²</span></div><div class="mini"><b>${fmt(w.cloud_day_percent,0)}%</b><span>Wolken</span></div><div class="mini"><b>${fmt(w.precipitation_mm,1)} mm</b><span>Regen</span></div></div></article>`}
function renderStatus(){const s=DATA.settings||{},src=String(DATA.last_forecast_source||''),gc=DATA.gemini_control||{},today=new Date(DATA.time).toLocaleDateString('sv-SE'),successDate=gc.last_success_at?new Date(gc.last_success_at).toLocaleDateString('sv-SE'):'';const gemini=!!gc.last_success_at&&successDate===today,fallback=!gemini&&src==='fallback';const used=Number(gc.successful_calls||0),limit=Number(s.gemini_daily_limit||3);const last=gemini?gc.last_success_at:DATA.last_forecast_run;q('#statusbar').innerHTML=`<div class="statusitem ${s.master_automation_enabled?'ok':''}"><b>Automatik</b> · ${s.master_automation_enabled?'aktiv':'aus'}</div><div class="statusitem ${gemini?'geminiok':fallback?'geminifallback':''}"><b>Gemini</b> · ${gemini?'✓ heute':fallback?'Fallback':'heute –'} · ${used}/${limit}</div><div class="statusitem"><b>Update</b> · ${last?new Date(last).toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}):'–'}</div>`;q('#statusAlert').innerHTML=DATA.last_error?`<div class="alert">Hinweis: ${DATA.last_error}</div>`:''}
function renderNow(){const l=DATA.live||{},p=DATA.plan||{},ww=p.warmwater||{},lp=DATA.live_pv||{};const wbMode=l.wallbox_mode||'–',wbPower=Math.max(0,Number(l.wallbox_power_w||0));let autoState=wbMode==='fast'?'Schnellladen':wbMode==='optimized'?'PV-Laden':wbMode==='locked'?'Gesperrt':wbMode;const enabledPhases=(l.phase1==='on'?1:0)+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0),powerText=wbPower>=1000?`${fmt(wbPower/1000,1)} kW`:`${fmt(wbPower,0)} W`;const phaseText=wbPower>50?`${enabledPhases} ${enabledPhases===1?'Phase':'Phasen'} aktiv`:`${enabledPhases}/3 Phasen freigegeben`;const autoDetail=`${powerText} · ${phaseText}`;const currentHour=new Date(DATA.time).getHours(),wwNow=currentHour>=5?(p.today_warmwater||{}):ww;let wDetail='';if(wwNow.mode==='done')wDetail='Heute erledigt';else if(wwNow.start_time||wwNow.end_time)wDetail=`${wwNow.start_time||'–'}–${wwNow.end_time||'–'} Uhr`;else wDetail='Heute noch offen';const pvRest=lp.remaining_adjusted_kwh??null,pvExpected=lp.adjusted_expected_kwh??lp.original_expected_kwh??null;const pvState=pvRest==null?'–':`${fmt(pvRest,1)} kWh`;const pvDetail=pvExpected==null?'Rest heute':`von ca. ${fmt(pvExpected,1)} kWh heute`;q('#nowStrip').innerHTML=`<div class="nowChip compactPrimary"><div class="nowIcon">🔋</div><div><span class="nowLabel">Speicher</span><strong>${fmt(l.battery_soc,0)}%</strong></div></div><div class="nowChip"><div class="nowIcon">🚗</div><div><span class="nowLabel">Wallbox</span><strong>${autoState}</strong><small>${autoDetail}</small></div></div><div class="nowChip"><div class="nowIcon">🚿</div><div><span class="nowLabel">Warmwasser</span><strong>${fmt(l.warmwater_temp,1)} °C</strong><small>${wDetail}</small></div></div><div class="nowChip"><div class="nowIcon">☀️</div><div><span class="nowLabel">PV noch</span><strong>${pvState}</strong><small>${pvDetail}</small></div></div>`}
function renderForecasts(){const f=DATA.forecast||{},today=String(DATA.time||'').slice(0,10),lp=DATA.live_pv||{},l=DATA.live||{},rail=q('#forecastRail'),dots=q('#forecastDots');const graph=lp.graph||[],max=Math.max(.2,...graph.map(x=>Number(x.kw||0))),bars=graph.map(x=>`<div class="liveBar ${x.kind||'forecast'}" style="height:${Math.max(2,Math.round(Number(x.kw||0)/max*100))}%" title="${String(x.hour).padStart(2,'0')}:00 · ${fmt(x.kw,2)} kW"></div>`).join('');const delta=Number(lp.delta_kwh||0),deltaText=(delta>=0?'+':'')+fmt(delta,2)+' kWh';const todayCard=`<div class="forecastCard pvSwipeCard today"><div class="forecastTop"><div><div class="forecastDay">Heute · Live</div><div class="pvSwipeNow">${fmt(l.pv_power_w,0)} W <small>jetzt</small></div></div><div class="planMini">Ist ${fmt(lp.actual_kwh??l.pv_today_kwh,1)} kWh</div></div><div class="range">${lp.status||'Live'} · ${lp.enough_data?deltaText+' zum Soll':'Tageskorrektur läuft automatisch'}</div><div class="pvSwipeStats"><div><b>${fmt(lp.adjusted_expected_kwh??lp.original_expected_kwh,1)} kWh</b><span>heute erwartet</span></div><div><b>${fmt(lp.remaining_adjusted_kwh,1)} kWh</b><span>Rest erwartet</span></div><div><b>${fmt(lp.expected_so_far_kwh,1)} kWh</b><span>Soll bis jetzt</span></div></div><div class="liveGraph">${bars}</div><div class="liveHours"><span>06</span><span>09</span><span>12</span><span>15</span><span>18</span><span>21</span></div></div>`;const futureKeys=Object.keys(f).sort().filter(k=>k>today).slice(0,2);rail.innerHTML=todayCard+futureKeys.map(k=>forecastCard(f[k])).join('');const count=1+futureKeys.length;dots.innerHTML=Array.from({length:count},(_,i)=>`<span class="forecastDot ${i===0?'active':''}"></span>`).join('');const update=()=>{const cards=[...rail.querySelectorAll('.forecastCard')];if(!cards.length)return;let best=0,dist=Infinity;cards.forEach((c,i)=>{const d=Math.abs(c.offsetLeft-rail.scrollLeft);if(d<dist){dist=d;best=i}});[...dots.children].forEach((d,i)=>d.classList.toggle('active',i===best))};rail.onscroll=()=>requestAnimationFrame(update);update()}
function renderPV(){const p=DATA.plan||{},l=DATA.live||{},today=p.pv_charging||{},next=p.next_pv_charging||{};let pv=today,bud=today.budget||{};const now=new Date(DATA.time),toMin=x=>{const m=String(x||'').match(/^(\d{1,2}):(\d{2})/);return m?Number(m[1])*60+Number(m[2]):null},nowMin=now.getHours()*60+now.getMinutes(),endMin=toMin(bud.pv_end_time||today.end_time),pvNow=Number(l.pv_w||0),pastToday=(endMin!==null&&nowMin>=endMin)||(now.getHours()>=18&&pvNow<100);if(next&&next.budget&&pastToday){pv=next;bud=next.budget||{}}const phases=l.wallbox_mode==='optimized'?1+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0):0;const reserveSoc=bud.battery_target_soc_percent??bud.evening_protected_soc_percent??((Number(bud.evening_reserve_kwh||0)/7.5)*100);const risk=bud.evening_grid_risk||'–';const ww=Number(bud.warmwater_reserve_kwh||0)>0?fmt(bud.warmwater_reserve_kwh)+' kWh':'erledigt';const pvEnd=bud.pv_end_time||'–';const timingLabel=pv===next?'Voraussichtlich morgen Abend':'Voraussichtlich heute Abend';q('#pvBox').innerHTML=`<div class="pvHeadline"><div><div class="eyebrow">${pv.day_label||'Heute'} · bestes Fenster ${pv.start_time||'–'}–${pv.end_time||'–'}</div><h2>${pv.label||'–'}</h2></div><div class="budgetBig">${fmt(bud.available_car_kwh)} kWh<small>sicher fürs Auto</small></div></div><div class="pvInfo">${pv.reason||''}</div><div class="budgetGrid"><div class="budgetItem"><b>${fmt(bud.remaining_pv_kwh)}</b><span>PV noch</span></div><div class="budgetItem"><b>${fmt(bud.house_reserve_kwh)}</b><span>Haus bis ${pvEnd}</span></div><div class="budgetItem"><b>${fmt(bud.battery_reserve_kwh)}</b><span>für Speicher nötig</span></div><div class="budgetItem"><b>${ww}</b><span>Warmwasser</span></div><div class="budgetItem"><b>${fmt(bud.safety_kwh)}</b><span>Sicherheit</span></div><div class="budgetItem"><b>${fmt(bud.available_car_kwh)}</b><span>sicher fürs Auto</span></div></div><div class="eveningBox"><div class="eveningTitle">${timingLabel}</div><div class="eveningGrid"><div class="eveningItem"><b>≥ ${fmt(reserveSoc,0)}%</b><span>Speicher-Ziel bis PV-Ende</span></div><div class="eveningItem"><b>${fmt(bud.battery_target_kwh)} kWh</b><span>für PV-Ende–00:00</span></div><div class="eveningItem"><b>${risk}</b><span>Netzrisiko vor 00:00</span></div></div></div><div class="pvInfo">Grundlast ${fmt(bud.house_base_kw,2)} kW · Mindestreserve ${fmt(bud.battery_current_soc_percent,0)}% · PV-Phasen aktiv ${phases||'–'}</div><div class="carline"><div class="socPair"><div class="soc"><b>ID.7 ${fmt(l.id7_soc,0)}%</b></div><div class="soc"><b>e-Golf ${fmt(l.egolf_soc,0)}%</b></div></div><div class="presence"><button class="${DATA.car_at_wallbox?'active':''}" onclick="setCarPresence(true)">Auto: Ja</button><button class="${!DATA.car_at_wallbox?'active':''}" onclick="setCarPresence(false)">Nein</button></div></div>`}

function renderNight(){const p=DATA.plan||{},b=p.battery||{},wb=p.wallbox||{},ww=p.warmwater||{},dw=p.dishwasher||{},pv=p.next_pv_charging||p.pv_charging||{},bud=pv.budget||{},l=DATA.live||{},target=Number(wb.night_target_soc||50),ov=DATA.night_override||'auto';const batMin=b.target_soc??'–',id7=Number(l.id7_soc??0),egolf=Number(l.egolf_soc??0),connectedSoc=wb.connected_soc!=null?Number(wb.connected_soc):Math.min(id7||100,egolf||100);let autoVal='Keine Schnellladung notwendig';if(ov==='pv_wait')autoVal='Nachts keine Netzladung';else if(!DATA.car_at_wallbox)autoVal='Kein Auto an Wallbox';else if(l.wallbox_mode==='fast'&&new Date(DATA.time).getHours()<5)autoVal=`Nachts Ladung bis ${target}%`;else if(ov==='fast'||wb.recommended==='fast'||connectedSoc<target)autoVal=`Nachts Ladung bis ${target}%`;if(DATA.car_auto_charging_enabled===false)autoVal='Auto-Ladeautomatik pausiert';const autoSub=`ID.7 ${fmt(l.id7_soc,0)}% · e-Golf ${fmt(l.egolf_soc,0)}%`,pvPlan=DATA.car_auto_charging_enabled===false?'PV-Automatik pausiert':`PV-Laden ca. ${fmt(bud.available_car_kwh,1)} kWh geplant`;const wwWhen=ww.mode==='night'?'in der Nacht':'im PV-Fenster',dwWhen=dw.mode==='night'?'in der Nacht':'im PV-Fenster';q('#nightSummary').innerHTML=`<div class="planrow"><div class="planico">🔋</div><div><strong>Speicher</strong><span>Aktuell ${fmt(l.battery_soc,0)}%</span><div class="planvalue">Nachts min. ${batMin}%</div></div></div><div class="planrow planCars"><div class="planico">🚗</div><div><strong>Autos</strong><span>${autoSub}</span><div class="planvalue">${autoVal}</div><span class="planExtra">${pvPlan}</span></div></div><div class="planrow"><div class="planico">🍽️</div><div><strong>Spülmaschine</strong><span>${dwWhen}</span><div class="planvalue">${dw.time||'–'}</div></div></div><div class="planrow"><div class="planico">🚿</div><div><strong>Warmwasser</strong><span>${wwWhen}</span><div class="planvalue">${ww.start_time||'–'}–${ww.end_time||'–'}</div></div></div>`;q('#nightTarget').innerHTML=[40,50,60,70,80,90,100].map(v=>`<button class="targetBtn ${target===v?'active':''}" onclick="setNightTarget(${v})">${v}%</button>`).join('');q('#nightChoices').innerHTML=[['auto','⚙️ Automatik'],['fast','⚡ Nacht schnell'],['pv_wait','☀️ Nur PV']].map(x=>`<button class="button ${ov===x[0]?'active':''}" onclick="nightOverride('${x[0]}')">${x[1]}</button>`).join('');const socBtn=q('#socMenuButton');if(socBtn)socBtn.innerHTML=`🎯 SOC ${target}%`}
function toggleSocMenu(){const box=q('#socDropdown');if(box)box.classList.toggle('show')}

function renderControls(){const l=DATA.live||{},mode=l.wallbox_mode||'–';q('#directSummary').innerHTML=`<div class="stateMini"><b>Wallbox · ${mode}</b><span>Phasen ${l.phase1==='on'?'1':''}${l.phase2==='on'?'+2':''}${l.phase3==='on'?'+3':''}</span></div><div class="stateMini"><b>Speicher · ${l.safe_charge==='on'?'AN':'AUS'}</b><span>${fmt(l.battery_soc,0)}% SOC</span></div><div class="stateMini"><b>Warmwasser · ${l.warmwater==='on'?'AN':'AUS'}</b><span>${fmt(l.warmwater_temp,1)}°C</span></div>`;q('#wallboxModes').innerHTML=[['wallbox_pv','optimized','☀️','PV'],['wallbox_fast','fast','⚡','Schnell'],['wallbox_locked','locked','🔒','Gesperrt']].map(([a,m,i,t])=>`<button class="modeBtn ${mode===m?'active':''}" onclick="action('${a}')"><span>${i}</span>${t}</button>`).join('');q('#phaseRow').innerHTML=[[1,l.phase1,true],[2,l.phase2,false],[3,l.phase3,false]].map(([n,v,f])=>`<div class="phase ${v==='on'?'on':''}">Phase ${n}${f?' · fix':''}</div>`).join('');const bon=l.safe_charge==='on';q('#batteryControl').className='bigToggle '+(bon?'on':'');q('#batteryControl').innerHTML=`<div><b>${bon?'Netzladung beenden':'Netzladung einschalten'}</b><span>${fmt(l.battery_soc,0)}% SOC · 05:00-Schutz aktiv</span></div><b>${bon?'✓':'⏻'}</b>`;const won=l.warmwater==='on';q('#warmwaterControl').className='bigToggle '+(won?'on':'');q('#warmwaterControl').innerHTML=`<div><b>${won?'Warmwasser beenden':'Warmwasser starten'}</b><span>${fmt(l.warmwater_temp,1)}°C</span></div><b>${won?'✓':'♨'}</b>`}
function renderEnergy(){const l=DATA.live||{},pv=Math.max(0,Number(l.pv_power_w||0)),house=Math.max(0,Number(l.house_power_w||0)),bat=Number(l.battery_power_w||0),grid=Number(l.grid_power_w||0),wp=Number(l.wp_power_value||0),wpUnit=String(l.wp_power_unit||'').trim(),wallbox=Math.max(0,Number(l.wallbox_power_w||0)),dish=Math.max(0,Number(l.dishwasher_power_w||0)),office=l.climate_office_live_w,kids=l.climate_kids_live_w;const kwh=(v,d=2)=>v==null?'–':fmt(v,d)+' kWh',watt=v=>v==null?'–':fmt(v,0)+' W',tile=(label,value,sub,cls)=>`<div class="balanceTile ${cls||''}"><span class="blabel">${label}</span><b>${value}</b>${sub?`<small>${sub}</small>`:''}</div>`;const wpValue=wpUnit?`${fmt(wp,wpUnit.toLowerCase()==='w'?0:2)} ${wpUnit}`:`${fmt(wp,0)}`;const finiteRaw=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v)),haveHouseDay=[l.pv_today_kwh,l.net_import_today_kwh,l.grid_export_today_kwh,l.battery_charge_today_kwh,l.battery_discharge_today_kwh].every(finiteRaw),pvDay=Number(l.pv_today_kwh),netIn=Number(l.net_import_today_kwh),netOut=Number(l.grid_export_today_kwh),batIn=Number(l.battery_charge_today_kwh),batOut=Number(l.battery_discharge_today_kwh),houseDay=haveHouseDay?Math.max(0,pvDay+netIn+batOut-netOut-batIn):null;const batSigned=bat<-20?`−${fmt(Math.abs(bat),0)} W`:bat>20?`+${fmt(Math.abs(bat),0)} W`:'0 W',gridSigned=grid>20?`−${fmt(Math.abs(grid),0)} W`:grid< -20?`+${fmt(Math.abs(grid),0)} W`:'0 W',officeLive=office==null?'–':`≈${fmt(office,0)} W`,kidsLive=kids==null?'–':`≈${fmt(kids,0)} W`;q('#balanceGrid').innerHTML=
  tile('☀️ PV',`${fmt(pv,0)} W`,`Heute ${kwh(l.pv_today_kwh)}`,'flowGroup pvTile')+
  tile('🏠 Haus',`${fmt(house,0)} W`,houseDay==null?'Heute –':`Heute ${kwh(houseDay)}`,'flowGroup houseTile')+
  tile('⚡ Netz',gridSigned,`Bezug ${kwh(l.net_import_today_kwh,1)}<br>Einspeis. ${kwh(l.grid_export_today_kwh,1)}`,`flowGroup netTile ${grid>20?'flowMinus':grid< -20?'flowPlus':'flowZero'}`)+
  tile('🔋 Speicher',batSigned,`↑ ${kwh(l.battery_charge_today_kwh,1)} · ↓ ${kwh(l.battery_discharge_today_kwh,1)}`,`systemGroup ${bat<-20?'flowMinus':bat>20?'flowPlus':'flowZero'}`)+
  tile('🚗 Wallbox',watt(wallbox),`Heute ${kwh(l.wallbox_today_kwh)}`,'systemGroup')+
  tile('🔥 Wärmepumpe',wpValue,`Heute ${kwh(l.wp_today_kwh)}`,'systemGroup')+
  tile('🍽️ Spülmaschine',watt(dish),`Heute ${kwh(l.dishwasher_today_kwh)}`,'consumerGroup')+
  tile('❄️ Klima Büro',officeLive,`Heute ${kwh(l.climate_office_today_kwh)}`,'consumerGroup')+
  tile('❄️ Klima KiZi',kidsLive,`Heute ${kwh(l.climate_kids_today_kwh)}`,'consumerGroup');const learn=DATA.learning||{},m=learn.recent_mape_percent??learn.baseline_test_mape_percent;q('#qualityLine').innerHTML=`Prognosequalität <b>${fmt(m,1)}% MAPE</b> · ${learn.history_count||0} Vergleichstage · Abendreserve <b>${fmt(learn.evening?.reserve_kwh||2.5)} kWh</b>`}

function renderMorningCalculation(){const box=q('#morningCalculation');if(!box)return;const pb=DATA.plan?.battery||{},rows=Array.isArray(pb.morning_breakdown)?pb.morning_breakdown:[],rest=pb.standby_restload_w,pred=pb.predicted_cover_time||'–',adj=pb.adjusted_cover_time||pred,plan=pb.morning_forecast_basis_kwh,need=pb.bridge_need_before_buffer_kwh??pb.predicted_morning_need_kwh,bufSoc=Number(pb.morning_energy_buffer_soc||0),bufKwh=pb.bridge_energy_buffer_kwh??(7.5*bufSoc/100),needBuf=pb.bridge_need_with_buffer_kwh??((Number(need)||0)+(Number(bufKwh)||0)),reserve=Number(pb.minimum_reserve_soc||0),restExtra=Number(pb.post_bridge_extra_soc||0),auto=pb.automatic_target_soc,target=pb.target_soc,source=pb.cover_time_source||'–';const intro=`<div class="calcIntro"><div class="calcStat"><span>Restlast für Morgenbrücke</span><b>${rest==null?'–':fmt(rest,0)+' W'}</b></div><div class="calcStat"><span>PV stabil prognostiziert</span><b>${pred}</b></div><div class="calcStat"><span>inkl. Lern-Zeitpuffer</span><b>${adj}</b></div><div class="calcStat"><span>konservative PV-Basis</span><b>${plan==null?'–':fmt(plan,1)+' kWh'}</b></div></div>`;let table='';if(rows.length){table=`<div class="calcRows"><div class="calcRow head"><span>Zeit</span><span>Restlast</span><span class="pvcol">PV</span><span>Speicherbedarf</span></div>${rows.map(r=>`<div class="calcRow"><b>${r.from||'–'}–${r.to||'–'}</b><span>${fmt(r.load_kwh,3)} kWh</span><span class="pvcol">− ${fmt(r.pv_kwh,3)} kWh</span><strong>${fmt(r.net_need_kwh,3)} kWh</strong></div>`).join('')}</div>`}else table='<div class="calcFormula">Für die aktuelle Prognose liegt noch keine stundenweise Morgenrechnung vor.</div>';const formula=`<div class="calcFormula"><strong>So entsteht das 05:00-Ziel</strong><br>Netto-Morgenbedarf <b>${need==null?'–':fmt(need,2)+' kWh'}</b> + Energie-Lernpuffer <b>${fmt(bufSoc,1)}% = ${fmt(bufKwh,2)} kWh</b> + Mindestreserve <b>${fmt(reserve,0)}%</b>${restExtra>0?` + Resttag-Puffer <b>${fmt(restExtra,1)}%</b>`:''}.<br>Automatisches Ziel: <b>${auto==null?'–':fmt(auto,1)+'%'}</b> → gerundetes 05:00-Ziel: <b>${target==null?'–':fmt(target,0)+'%'}</b>.<br><span style="color:var(--muted)">PV-Übernahmequelle: ${source}. Die 0,85-kW-Grundlast wird erst für die Resttag-Bilanz verwendet; die Morgenbrücke nutzt die gelernte Restlast.</span></div>`;box.innerHTML=intro+table+formula}
function renderLearning(){const l=DATA.learning||{},b=l.battery||{},m=l.morning||{},d=l.day_load||{},st=l.standby||{},e=l.evening||{},pb=DATA.plan?.battery||{},base=Number(DATA.settings?.day_house_base_kw??d.base_kw??0.85),dayKwh=base*19,reserve=Number(m.desired_cover_soc??DATA.settings?.morning_min_soc??5),offset=Number(DATA.settings?.battery_soc_manual_offset??0),startBuffer=Number(pb.start_buffer_minutes??b.start_buffer_minutes??10),predCover=pb.predicted_cover_time||'–',adjCover=pb.adjusted_cover_time||predCover,predNeed=pb.predicted_morning_need_kwh,timeOffset=Number(pb.cover_time_offset_minutes??m.cover_time_offset_minutes??0),energyBuffer=Number(pb.morning_energy_buffer_soc??m.energy_buffer_soc??0),restload=pb.standby_restload_w??st.estimate_w;const target=pb.target_soc??b.planned_0500_target_soc;const autoTarget=pb.automatic_target_soc??target;const sampleDate=m.last_sample_date||'–';q('#learningDetails').innerHTML=`<div class="modelStat"><b>${fmt(l.recent_mape_percent??l.baseline_test_mape_percent,1)}%</b><span>MAPE</span></div><div class="modelStat"><b>${fmt(l.recent_mae_kwh??l.baseline_test_mae_kwh,2)} kWh</b><span>MAE</span></div><div class="modelStat"><b>${l.history_count||0}</b><span>PV-Tage</span></div><div class="modelStat"><b>${fmt(b.effective_charge_kw||1.7,2)} kW</b><span>Speicher-Laderate</span></div><div class="modelStat"><b>${fmt(startBuffer,0)} min</b><span>Lade-Startpuffer</span></div><div class="modelStat"><b>${fmt(base,2)} kW</b><span>gelernte Grundlast</span></div><div class="modelStat"><b>${restload==null?'–':fmt(restload,0)+' W'}</b><span>Standby / Restlast</span></div><div class="modelStat"><b>${predCover}</b><span>PV-Übernahme prognostiziert</span></div><div class="modelStat"><b>${adjCover}</b><span>PV-Übernahme inkl. Lernpuffer</span></div><div class="modelStat"><b>${predNeed==null?'–':fmt(predNeed,2)+' kWh'}</b><span>progn. Bedarf 05→PV</span></div><div class="modelStat"><b>${timeOffset>=0?'+':''}${fmt(timeOffset,0)} min</b><span>gelernter Zeitpuffer</span></div><div class="modelStat"><b>${fmt(energyBuffer,1)}%</b><span>gelernter Energiepuffer</span></div><div class="modelStat"><b>${fmt(dayKwh,2)} kWh</b><span>Tagesbasis 05–24</span></div><div class="modelStat"><b>${fmt(reserve,0)}%</b><span>Mindestreserve</span></div><div class="modelStat"><b>${fmt(target,0)}%</b><span>aktuelles 05:00-Ziel</span></div><div class="modelStat"><b>${fmt(m.last_soc_0500,0)}%</b><span>letzter SOC 05:00</span></div><div class="modelStat"><b>${m.last_cover_time||'–'}</b><span>PV übernimmt stabil</span></div><div class="modelStat"><b>${fmt(m.last_soc_cover,0)}%</b><span>SOC bei PV-Übernahme</span></div><div class="modelStat"><b>${fmt(m.last_net_need_kwh,2)} kWh</b><span>Bedarf 05:00→PV</span></div><div class="modelStat"><b>${offset>0?'+':''}${fmt(offset,0)}%</b><span>manuelle Korrektur</span></div><div class="modelStat"><b>${m.samples||0}</b><span>Morgen-Lerntage</span></div><div class="modelStat"><b>${d.samples||0}</b><span>Grundlast-Lerntage</span></div><div class="modelStat"><b>${DATA.last_forecast_source||'–'}</b><span>Forecast-Modell</span></div>`;const card=q('#morningLearningCard');if(card)card.innerHTML=`Grundlast <b>${fmt(base,2)} kW</b> · Restlast <b>${restload==null?'–':fmt(restload,0)+' W'}</b> · Tagesbasis <b>${fmt(dayKwh,2)} kWh</b> · Ladepuffer <b>${fmt(startBuffer,0)} min</b> · Mindestreserve <b>${fmt(reserve,0)}%</b> · 05:00-Ziel <b>${fmt(target,0)}%</b>${Math.abs(offset)>=0.1?` (automatisch ${fmt(autoTarget,0)}% · manuell ${offset>0?'+':''}${fmt(offset,0)}%)`:''}.<br>Nächster Morgen: PV prognostiziert <b>${predCover}</b> · mit Lernpuffer <b>${adjCover}</b> · Bedarf <b>${predNeed==null?'–':fmt(predNeed,2)+' kWh'}</b> · Zeitpuffer <b>${timeOffset>=0?'+':''}${fmt(timeOffset,0)} min</b> · Energiepuffer <b>${fmt(energyBuffer,1)}%</b>.<br>Letzter Morgen: 05:00 <b>${fmt(m.last_soc_0500,0)}%</b> · PV übernimmt <b>${m.last_cover_time||'–'}</b> · dabei <b>${fmt(m.last_soc_cover,0)}%</b> · Bedarf <b>${fmt(m.last_net_need_kwh,2)} kWh</b>.<br><span style="color:var(--muted)">${m.last_adjustment||'Morgenreserve wird aus echten Verläufen angepasst.'} · ${d.last_adjustment||'Grundlast startet mit 0,85 kW.'}</span>`;const summary=q('#learningSummary');if(summary){const offsetText=Math.abs(offset)>=0.1?` · manuell <b>${offset>0?'+':''}${fmt(offset,0)}%</b>`:'';summary.innerHTML=`<div class="learningHero"><div class="learnMetric"><div class="learnIcon">💤</div><span>Standby / Restlast</span><b>${restload==null?'–':fmt(restload,0)+' W'}</b><small>${st.samples||0} saubere 5-Min.-Fenster</small></div><div class="learnMetric"><div class="learnIcon">🌤️</div><span>PV übernimmt stabil</span><b>${adjCover}</b><small>Prognose ${predCover} · Lernpuffer ${timeOffset>=0?'+':''}${fmt(timeOffset,0)} min</small></div><div class="learnMetric"><div class="learnIcon">⚡</div><span>Morgenbedarf 05:00→PV</span><b>${predNeed==null?'–':fmt(predNeed,2)+' kWh'}</b><small>Energie-Lernpuffer ${fmt(energyBuffer,1)}%</small></div><div class="learnMetric"><div class="learnIcon">🔋</div><span>Nächstes 05:00-Ziel</span><b>${fmt(target,0)}%</b><small>Mindestreserve ${fmt(reserve,0)}%${Math.abs(offset)>=0.1?` · manuell ${offset>0?'+':''}${fmt(offset,0)}%`:''}</small></div></div><div class="learningDetailGrid"><div class="learnDetail"><strong>Grundlast & Tagesbasis</strong><p>${fmt(base,2)} kW Grundlast · ${fmt(dayKwh,2)} kWh von 05:00–24:00 · Ladepuffer ${fmt(startBuffer,0)} min.</p></div><div class="learnDetail"><strong>Lernkorrekturen</strong><p>Zeitpuffer ${timeOffset>=0?'+':''}${fmt(timeOffset,0)} min · Energiepuffer ${fmt(energyBuffer,1)}%. Zeit- und Bedarfsfehler werden getrennt gelernt.</p></div><div class="learnDetail"><strong>Letzter Morgen${sampleDate!=='–'?` · ${sampleDate}`:''}</strong><p>05:00 ${fmt(m.last_soc_0500,0)}% · PV-Übernahme ${m.last_cover_time||'–'} · SOC dabei ${fmt(m.last_soc_cover,0)}% · Bedarf ${fmt(m.last_net_need_kwh,2)} kWh.</p></div></div>`}}
function renderOverviewGoal(){const p=DATA.plan||{},b=p.battery||{},l=DATA.learning||{},m=l.morning||{};const target=Number(b.target_soc??b.planned_0500_target_soc??0),need=b.predicted_morning_need_kwh,cover=b.adjusted_cover_time||b.predicted_cover_time||'–',reserve=Number(m.desired_cover_soc??DATA.settings?.morning_min_soc??0),last=Number(m.last_soc_0500??0);const deg=Math.max(0,Math.min(100,target))*3.6;q('#overviewGoalCard').innerHTML=`<div class="goalTop"><div><div class="eyebrow">Nächstes 05:00-Ziel</div><div class="goalRing" style="--goal:${deg}deg"><div><strong>${fmt(target,0)}%</strong><span>Speicher</span></div></div></div><div class="goalFacts"><div><span>Bedarf morgen früh</span><b>${need==null?'–':fmt(need,2)+' kWh'}</b></div><div><span>PV übernimmt</span><b>${cover}</b></div><div><span>Mindestreserve</span><b>${fmt(reserve,0)}%</b></div><div><span>Letzter Morgen</span><b>${fmt(last,0)}%</b></div></div></div><button class="goalLink" onclick="showPage('learning')">Details & Berechnung ansehen <span>›</span></button>`}
function render(){if(!DATA)return;q('#version').textContent=DATA.version;const sv=q('#sideVersion');if(sv)sv.textContent=DATA.version;renderStatus();renderNow();renderNight();renderEnergy();renderOverviewGoal();renderPvDayProgress();renderPvPhaseStatus();renderForecasts();renderPV();renderControls();renderLearning();fillSettings()}
function toggleSetting(el){const k=el.dataset.key;DATA.settings[k]=!DATA.settings[k];el.classList.toggle('on',DATA.settings[k])}
function buttonFeedback(btn,state,text,restore){if(!btn)return;const original=btn.dataset.originalText||btn.textContent;if(!btn.dataset.originalText)btn.dataset.originalText=original;btn.classList.remove('busy','done','fail');if(state)btn.classList.add(state);btn.disabled=state==='busy';btn.textContent=text||original;if(restore){setTimeout(()=>{btn.classList.remove('busy','done','fail');btn.disabled=false;btn.textContent=btn.dataset.originalText||original},restore)}}
async function saveSettings(btn){const keys=['notify_service','partner_notify_service','forecast_main_time','forecast_morning_time','gemini_daily_limit','gemini_manual_cooldown_minutes','id7_target_soc','id7_min_morning_soc','egolf_target_soc','egolf_min_morning_soc','car_night_target_soc','pv_phase1_start_w','pv_phase1_stop_w','pv_phase2_start_w','pv_phase2_stop_w','pv_phase3_start_w','pv_phase3_stop_w','pv_surplus_delay_seconds','pv_phase_hold_seconds','day_house_base_kw','battery_soc_manual_offset','evening_reserve_start_kwh','evening_reserve_margin_kwh','warmwater_estimated_kwh','pv_budget_safety_kwh','car_budget_min_kwh','warmwater_night_threshold_kwh','warmwater_duration_minutes'];for(const k of keys){const e=q('#'+k);if(e)DATA.settings[k]=e.type==='number'?Number(e.value):e.value}buttonFeedback(btn,'busy','⏳ Wird gespeichert…');try{const r=await fetch(api('settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(DATA.settings)});if(!r.ok)throw new Error('Speichern fehlgeschlagen');buttonFeedback(btn,'done','✓ Einstellungen gespeichert',1800);toast('Gespeichert · ohne Gemini-Aufruf');refreshSoon()}catch(e){buttonFeedback(btn,'fail','⚠ Speichern fehlgeschlagen',2200);toast(e.message||'Speichern fehlgeschlagen')}}
async function resetSocOffset(btn){const e=q('#battery_soc_manual_offset');if(e)e.value=0;DATA.settings.battery_soc_manual_offset=0;await saveSettings(btn)}
async function testPush(btn){buttonFeedback(btn,'busy','⏳ Test-Push wird gesendet…');try{const j=await post('test-push',{});buttonFeedback(btn,'done','✓ Test primary gesendet',1800);toast(j.message||'Test-Push gesendet')}catch(e){buttonFeedback(btn,'fail','⚠ Test fehlgeschlagen',2200);toast(e.message)}}
async function testPartnerPush(btn){buttonFeedback(btn,'busy','⏳ Test secondary wird gesendet…');try{const j=await post('test-partner-push',{});buttonFeedback(btn,'done','✓ Test secondary gesendet',1800);toast(j.message||'Test-Push secondary gesendet')}catch(e){buttonFeedback(btn,'fail','⚠ Test fehlgeschlagen',2200);toast(e.message)}}
async function action(name){try{const j=await post('action',{action:name});toast(j.message||'Erledigt');refreshSoon()}catch(e){toast(e.message)}}
async function nightOverride(mode){if(!DATA)return;UI_PENDING.nightOverride=mode;DATA.night_override=mode;renderNight();try{const j=await post('night-override',{mode});toast(j.message||'Gespeichert');refreshSoon()}catch(e){UI_PENDING.nightOverride=null;toast(e.message);getData(true)}}
async function setCarPresence(present){if(!DATA)return;UI_PENDING.carPresence=Boolean(present);DATA.car_at_wallbox=Boolean(present);renderNow();renderNight();renderPV();try{const j=await post('car-presence',{present});toast(j.message||'Gespeichert');refreshSoon()}catch(e){UI_PENDING.carPresence=null;toast(e.message);getData(true)}}
async function setNightTarget(target){if(!DATA)return;UI_PENDING.nightTarget=Number(target);q('#socDropdown')?.classList.remove('show');const wb=DATA.plan?.wallbox||(DATA.plan.wallbox={});wb.night_target_soc=Number(target);wb.night_target_is_override=true;renderNight();try{const j=await post('night-target',{target});toast(j.message||'Gespeichert');refreshSoon()}catch(e){UI_PENDING.nightTarget=null;toast(e.message);getData(true)}}
// Die Einstellungen werden im Hintergrund regelmäßig aktualisiert. Während
// der Eingabe darf ein solcher Refresh aber niemals den gerade getippten Wert
// wieder überschreiben.
let SETTINGS_DIRTY=false,SETTINGS_READY=false;
function renderNow(){const l=DATA.live||{},p=DATA.plan||{},ww=p.warmwater||{},lp=DATA.live_pv||{};const wbMode=l.wallbox_mode||'–',wbPower=Math.max(0,Number(l.wallbox_power_w||0));let autoState=wbMode==='fast'?'Schnellladen':wbMode==='optimized'?'PV-Laden':wbMode==='locked'?'Gesperrt':wbMode;const enabledPhases=(l.phase1==='on'?1:0)+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0),powerText=wbPower>=1000?`${fmt(wbPower/1000,1)} kW`:`${fmt(wbPower,0)} W`;const phaseText=wbPower>50?`${enabledPhases} ${enabledPhases===1?'Phase':'Phasen'} aktiv`:`${enabledPhases}/3 Phasen freigegeben`;const autoDetail=`${powerText} · ${phaseText}`;const currentHour=new Date(DATA.time).getHours(),wwNow=currentHour>=5?(p.today_warmwater||{}):ww;let wDetail='';if(wwNow.mode==='done')wDetail='Heute erledigt';else if(wwNow.start_time||wwNow.end_time)wDetail=`${wwNow.start_time||'–'}–${wwNow.end_time||'–'} Uhr`;else wDetail='Heute noch offen';const pvRest=lp.remaining_adjusted_kwh??null,pvExpected=lp.adjusted_expected_kwh??lp.original_expected_kwh??null;const pvState=pvRest==null?'–':`${fmt(pvRest,1)} kWh`;const pvDetail=pvExpected==null?'Rest heute':`von ca. ${fmt(pvExpected,1)} kWh heute`;const surplus=Number(l.pv_minus_house_w),surplusKnown=l.pv_minus_house_w!==null&&l.pv_minus_house_w!==undefined&&Number.isFinite(surplus),surplusText=surplusKnown?`${surplus>=0?'+':'−'}${fmt(Math.abs(surplus),0)} W`:'–',surplusDetail=surplusKnown?(surplus>=0?'PV nach Hauslast':'Hauslast über PV'):'PV − Haus';q('#nowStrip').innerHTML=`<div class="nowChip compactPrimary"><div class="nowIcon">🔋</div><div><span class="nowLabel">Speicher</span><strong>${fmt(l.battery_soc,0)}%</strong></div></div><div class="nowChip"><div class="nowIcon">🚗</div><div><span class="nowLabel">Wallbox</span><strong>${autoState}</strong><small>${autoDetail}</small></div></div><div class="nowChip ${surplusKnown&&surplus<0?'surplusChip negative':'surplusChip'}"><div class="nowIcon">⚡</div><div><span class="nowLabel">PV-Überschuss</span><strong>${surplusText}</strong><small>${surplusDetail}</small></div></div><div class="nowChip"><div class="nowIcon">🚿</div><div><span class="nowLabel">Warmwasser</span><strong>${fmt(l.warmwater_temp,1)} °C</strong><small>${wDetail}</small></div></div><div class="nowChip"><div class="nowIcon">☀️</div><div><span class="nowLabel">PV noch</span><strong>${pvState}</strong><small>${pvDetail}</small></div></div>`}
function renderControls(){const l=DATA.live||{},mode=l.wallbox_mode||'–';const activePhases=1+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0);q('#directSummary').innerHTML=`<div class="stateMini"><b>Wallbox · ${mode}</b><span>Phasen ${l.phase1==='on'?'1':''}${l.phase2==='on'?'+2':''}${l.phase3==='on'?'+3':''}</span></div><div class="stateMini"><b>Speicher · ${l.safe_charge==='on'?'AN':'AUS'}</b><span>${fmt(l.battery_soc,0)}% SOC</span></div><div class="stateMini"><b>Warmwasser · ${l.warmwater==='on'?'AN':'AUS'}</b><span>${fmt(l.warmwater_temp,1)}°C</span></div>`;q('#wallboxModes').innerHTML=[['wallbox_pv','optimized','☀️','PV'],['wallbox_fast','fast','⚡','Schnell'],['wallbox_locked','locked','🔒','Gesperrt']].map(([a,m,i,t])=>`<button class="modeBtn ${mode===m?'active':''}" onclick="action('${a}')"><span>${i}</span>${t}</button>`).join('');q('#phaseRow').innerHTML=[1,2,3].map(n=>`<button class="phase ${mode==='optimized'&&activePhases===n?'on':''}" onclick="selectPvPhases(${n})">${n} ${n===1?'Phase':'Phasen'}</button>`).join('')+`<div class="phaseHint">Tippen schaltet sicher: Wallbox sperren → Phasen setzen → PV-Laden fortsetzen.</div>`;const bon=l.safe_charge==='on';q('#batteryControl').className='bigToggle '+(bon?'on':'');q('#batteryControl').innerHTML=`<div><b>${bon?'Netzladung beenden':'Netzladung einschalten'}</b><span>${fmt(l.battery_soc,0)}% SOC · 05:00-Schutz aktiv</span></div><b>${bon?'✓':'⏻'}</b>`;const won=l.warmwater==='on';q('#warmwaterControl').className='bigToggle '+(won?'on':'');q('#warmwaterControl').innerHTML=`<div><b>${won?'Warmwasser beenden':'Warmwasser starten'}</b><span>${fmt(l.warmwater_temp,1)}°C</span></div><b>${won?'✓':'♨'}</b>`}
function fillSettings(force=false){if(SETTINGS_DIRTY&&!force)return;const s=DATA.settings||{};const keys=['notify_service','partner_notify_service','forecast_main_time','forecast_morning_time','gemini_daily_limit','gemini_manual_cooldown_minutes','id7_target_soc','id7_min_morning_soc','egolf_target_soc','egolf_min_morning_soc','car_night_target_soc','pv_phase1_start_w','pv_phase1_stop_w','pv_phase2_start_w','pv_phase2_stop_w','pv_phase3_start_w','pv_phase3_stop_w','pv_surplus_delay_seconds','pv_phase_hold_seconds','day_house_base_kw','battery_soc_manual_offset','evening_reserve_start_kwh','evening_reserve_margin_kwh','warmwater_estimated_kwh','pv_budget_safety_kwh','car_budget_min_kwh','warmwater_night_threshold_kwh','warmwater_duration_minutes'];keys.forEach(k=>{const e=q('#'+k);if(e)e.value=s[k]??''});const toggles=[['master_automation_enabled','Gesamtautomatik'],['notifications_enabled','Benachrichtigungen'],['partner_notifications_enabled','secondary-Energieplan'],['pv_surplus_auto_enabled','PV-Wallbox automatisch'],['wallbox_night_auto_enabled','Nacht-Schnellladen automatisch'],['battery_auto_enabled','Speicher automatisch'],['warmwater_auto_enabled','Warmwasser automatisch']];q('#masterToggles').innerHTML=toggles.map(([k,l])=>`<div class="switchline"><span>${l}</span><button class="toggle ${s[k]?'on':''}" data-key="${k}" onclick="toggleSetting(this)"></button></div>`).join('');q('#settingsAlert').innerHTML=s.master_automation_enabled?'':`<div class="alert">Gesamtautomatik ist ausgeschaltet. Direktsteuerung bleibt möglich.</div>`}
function toggleSetting(el){const k=el.dataset.key;DATA.settings[k]=!DATA.settings[k];SETTINGS_DIRTY=true;el.classList.toggle('on',DATA.settings[k])}
async function saveSettings(btn){const keys=['notify_service','partner_notify_service','forecast_main_time','forecast_morning_time','gemini_daily_limit','gemini_manual_cooldown_minutes','id7_target_soc','id7_min_morning_soc','egolf_target_soc','egolf_min_morning_soc','car_night_target_soc','pv_phase1_start_w','pv_phase1_stop_w','pv_phase2_start_w','pv_phase2_stop_w','pv_phase3_start_w','pv_phase3_stop_w','pv_surplus_delay_seconds','pv_phase_hold_seconds','day_house_base_kw','battery_soc_manual_offset','evening_reserve_start_kwh','evening_reserve_margin_kwh','warmwater_estimated_kwh','pv_budget_safety_kwh','car_budget_min_kwh','warmwater_night_threshold_kwh','warmwater_duration_minutes'];try{for(const k of keys){const e=q('#'+k);if(!e)continue;if(e.type==='number'){if(!e.value.trim())throw new Error('Bitte alle Zahlenfelder ausfüllen');const value=Number(e.value);if(!Number.isFinite(value))throw new Error('Bitte nur gültige Zahlen eingeben');DATA.settings[k]=value}else DATA.settings[k]=e.value}buttonFeedback(btn,'busy','⏳ Wird gespeichert…');const j=await post('settings',DATA.settings);DATA.settings=j.settings||DATA.settings;SETTINGS_DIRTY=false;fillSettings(true);buttonFeedback(btn,'done','✓ Einstellungen gespeichert',1800);toast(j.message||'Gespeichert');refreshSoon(350)}catch(e){buttonFeedback(btn,'fail','⚠ Speichern fehlgeschlagen',2200);toast(e.message||'Speichern fehlgeschlagen')}}
async function action(name){try{const j=await post('action',{action:name});toast(j.message||'Erledigt');refreshSoon(350)}catch(e){toast(e.message)}}
async function selectPvPhases(phases){if(!DATA)return;const l=DATA.live||(DATA.live={});l.wallbox_mode='optimized';l.phase1='on';l.phase2=phases>=2?'on':'off';l.phase3=phases>=3?'on':'off';renderControls();try{const j=await post('action',{action:`wallbox_phase_${phases}`});toast(j.message||`${phases} Phasen aktiviert`);refreshSoon(350)}catch(e){toast(e.message);getData(true)}}
function fillSettings(force=false){const s=DATA.settings||{},keys=['notify_service','partner_notify_service','forecast_main_time','forecast_morning_time','gemini_daily_limit','gemini_manual_cooldown_minutes','id7_target_soc','id7_min_morning_soc','egolf_target_soc','egolf_min_morning_soc','car_night_target_soc','pv_phase1_start_w','pv_phase1_stop_w','pv_phase2_start_w','pv_phase2_stop_w','pv_phase3_start_w','pv_phase3_stop_w','pv_surplus_delay_seconds','pv_phase_hold_seconds','day_house_base_kw','battery_soc_manual_offset','evening_reserve_start_kwh','evening_reserve_margin_kwh','warmwater_estimated_kwh','pv_budget_safety_kwh','car_budget_min_kwh','warmwater_night_threshold_kwh','warmwater_duration_minutes'];const unsavedInput=keys.some(k=>{const e=q('#'+k);return e&&String(e.value)!==String(s[k]??'')});if(!force&&(SETTINGS_DIRTY||unsavedInput)){SETTINGS_DIRTY=true;return}keys.forEach(k=>{const e=q('#'+k);if(e)e.value=s[k]??''});const toggles=[['master_automation_enabled','Gesamtautomatik'],['notifications_enabled','Benachrichtigungen'],['partner_notifications_enabled','secondary-Energieplan'],['pv_surplus_auto_enabled','PV-Wallbox automatisch'],['wallbox_night_auto_enabled','Nacht-Schnellladen automatisch'],['battery_auto_enabled','Speicher automatisch'],['warmwater_auto_enabled','Warmwasser automatisch']];q('#masterToggles').innerHTML=toggles.map(([k,l])=>`<div class="switchline"><span>${l}</span><button class="toggle ${s[k]?'on':''}" data-key="${k}" onclick="toggleSetting(this)"></button></div>`).join('');q('#settingsAlert').innerHTML=s.master_automation_enabled?'':`<div class="alert">Gesamtautomatik ist ausgeschaltet. Direktsteuerung bleibt möglich.</div>`}
document.addEventListener('input',event=>{if(event.target.closest('#settings'))SETTINGS_DIRTY=true});
function fillSettings(force=false){const s=DATA.settings||{},keys=['notify_service','partner_notify_service','forecast_main_time','forecast_morning_time','gemini_daily_limit','gemini_manual_cooldown_minutes','id7_target_soc','id7_min_morning_soc','egolf_target_soc','egolf_min_morning_soc','car_night_target_soc','pv_phase1_start_w','pv_phase1_stop_w','pv_phase2_start_w','pv_phase2_stop_w','pv_phase3_start_w','pv_phase3_stop_w','pv_surplus_delay_seconds','pv_phase_hold_seconds','day_house_base_kw','battery_soc_manual_offset','evening_reserve_start_kwh','evening_reserve_margin_kwh','warmwater_estimated_kwh','pv_budget_safety_kwh','car_budget_min_kwh','warmwater_night_threshold_kwh','warmwater_duration_minutes'];const unsavedInput=SETTINGS_READY&&keys.some(k=>{const e=q('#'+k);return e&&String(e.value)!==String(s[k]??'')});if(!force&&(SETTINGS_DIRTY||unsavedInput)){SETTINGS_DIRTY=true;return}keys.forEach(k=>{const e=q('#'+k);if(e)e.value=s[k]??''});SETTINGS_READY=true;const toggles=[['master_automation_enabled','Gesamtautomatik'],['notifications_enabled','Benachrichtigungen'],['partner_notifications_enabled','secondary-Energieplan'],['pv_surplus_auto_enabled','PV-Wallbox automatisch'],['wallbox_night_auto_enabled','Nacht-Schnellladen automatisch'],['battery_auto_enabled','Speicher automatisch'],['warmwater_auto_enabled','Warmwasser automatisch']];q('#masterToggles').innerHTML=toggles.map(([k,l])=>`<div class="switchline"><span>${l}</span><button class="toggle ${s[k]?'on':''}" data-key="${k}" onclick="toggleSetting(this)"></button></div>`).join('');q('#settingsAlert').innerHTML=s.master_automation_enabled?'':`<div class="alert">Gesamtautomatik ist ausgeschaltet. Direktsteuerung bleibt möglich.</div>`;const wd=DATA.wallbox_watchdog||{},wi=q('#wallboxWatchdogInfo');if(wi){const stops=Number(wd.safety_stops||0),action=String(wd.last_action||'bereit');wi.textContent=`🛡️ Sicherheitswächter aktiv · 10-Sek.-Takt · Abschaltungen ${stops} · ${action}`}}
function renderPV(){const p=DATA.plan||{},l=DATA.live||{},s=DATA.settings||{},today=p.pv_charging||{},next=p.next_pv_charging||{};let pv=today,bud=today.budget||{};const now=new Date(DATA.time),toMin=x=>{const m=String(x||'').match(/^(\d{1,2}):(\d{2})/);return m?Number(m[1])*60+Number(m[2]):null},endMin=toMin(bud.pv_end_time||today.end_time),nowMin=now.getHours()*60+now.getMinutes(),pastToday=(endMin!==null&&nowMin>=endMin)||(now.getHours()>=18&&Number(l.pv_power_w||0)<100);if(next&&next.budget&&pastToday){pv=next;bud=next.budget||{}}const phases=l.wallbox_mode==='optimized'?1+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0):0,surplus=Number(l.pv_minus_house_w),known=l.pv_minus_house_w!==null&&l.pv_minus_house_w!==undefined&&Number.isFinite(surplus),surplusText=known?`${surplus>=0?'+':'−'}${fmt(Math.abs(surplus),0)} W`:'–',phaseCards=[[1,s.pv_phase1_start_w,s.pv_surplus_delay_seconds],[2,s.pv_phase2_start_w,s.pv_phase_hold_seconds],[3,s.pv_phase3_start_w,s.pv_phase_hold_seconds]].map(([n,w,wait])=>`<div class="phaseRuleStep ${phases===n?'active':''}"><b>${n} ${n===1?'Phase':'Phasen'}</b><span>ab ${fmt(w,0)} W${wait?` · ${Number(wait)>=60?fmt(Number(wait)/60,0)+' Min.':fmt(wait,0)+' s'}`:''}</span></div>`).join(''),ww=Number(bud.warmwater_reserve_kwh||0)>0?fmt(bud.warmwater_reserve_kwh)+' kWh':'erledigt',pvEnd=bud.pv_end_time||'–',autoText=DATA.car_at_wallbox?'🚗 Auto: Ja':'🚗 Auto: Nein';q('#pvBox').innerHTML=`<div class="pvHeadline"><div><div class="eyebrow">${pv.day_label||'Heute'} · bestes Fenster ${pv.start_time||'–'}–${pv.end_time||'–'}</div><h2>${pv.label||'PV-Laden'}</h2></div><div class="budgetBig">${fmt(bud.available_car_kwh)} kWh<small>sicher fürs Auto</small></div></div><div class="pvInfo">${pv.reason||''}</div><div class="pvQuickStatus"><b>Überschuss jetzt: ${surplusText}</b><span>${phases?`${phases} ${phases===1?'Phase':'Phasen'} aktiv`:'Wallbox aktuell nicht im PV-Laden'}</span></div><div class="phaseRule"><div class="phaseRuleSteps">${phaseCards}</div></div><div class="budgetGrid"><div class="budgetItem"><b>${fmt(bud.remaining_pv_kwh)}</b><span>PV noch</span></div><div class="budgetItem"><b>${fmt(bud.house_reserve_kwh)}</b><span>Haus bis ${pvEnd}</span></div><div class="budgetItem"><b>${fmt(bud.battery_reserve_kwh)}</b><span>Speicher bis voll</span></div><div class="budgetItem"><b>${ww}</b><span>Warmwasser</span></div><div class="budgetItem"><b>${fmt(bud.safety_kwh)}</b><span>Sicherheit</span></div><div class="budgetItem"><b>${fmt(bud.available_car_kwh)}</b><span>für Auto</span></div></div><details class="pvTechDetails"><summary>Technische Schaltschwellen anzeigen ›</summary><div class="pvTechBody">Phase 1 ab ${fmt(s.pv_phase1_start_w,0)} W für ${fmt(s.pv_surplus_delay_seconds,0)} s · zurück gesperrt unter ${fmt(s.pv_phase1_stop_w,0)} W für ${fmt(s.pv_surplus_delay_seconds,0)} s · Phase 2/3 erst nach ${fmt(s.pv_phase_hold_seconds,0)} s stabilem Mehrüberschuss.</div></details><div class="carline"><div class="socPair"><div class="soc"><b>ID.7 ${fmt(l.id7_soc,0)}%</b></div><div class="soc"><b>e-Golf ${fmt(l.egolf_soc,0)}%</b></div></div><button class="presenceSingle ${DATA.car_at_wallbox?'':'off'}" onclick="setCarPresence(${DATA.car_at_wallbox?'false':'true'})">${autoText}</button></div>`}
function renderPvPhaseStatus(){const box=q('#pvPhaseStatus');if(!box)return;const s=DATA.settings||{},l=DATA.live||{},c=DATA.pv_surplus_control||{},surplus=Number(l.pv_minus_house_w),known=l.pv_minus_house_w!==null&&l.pv_minus_house_w!==undefined&&Number.isFinite(surplus),current=l.wallbox_mode==='optimized'?1+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0):0,p1=Number(s.pv_phase1_start_w||1600),p1stop=Number(s.pv_phase1_stop_w||900),p2=Number(s.pv_phase2_start_w||3600),p2stop=Number(s.pv_phase2_stop_w||3000),p3=Number(s.pv_phase3_start_w||5200),p3stop=Number(s.pv_phase3_stop_w||4500),fast=Number(s.pv_surplus_delay_seconds||120),slow=Number(s.pv_phase_hold_seconds||1800),key=String(c.status_key||''),timer=pvTimer(c,key),candidateElapsed=timer.candidate,statusElapsed=timer.status,chargingElapsed=timer.charging,phaseElapsed=timer.phase,phaseWord=n=>`${n} ${n===1?'Phase':'Phasen'}`,timeText=(seconds)=>{const total=Math.max(0,Math.round(seconds));if(total<60)return `${total} Sek.`;const minutes=Math.floor(total/60);if(minutes<60)return `${minutes} Min.`;const hours=Math.floor(minutes/60);if(hours<24)return `${hours} Std.`;const days=Math.floor(hours/24);if(days<7)return `${days} Tag${days===1?'':'e'}`;const weeks=Math.floor(days/7);if(weeks<5)return `${weeks} Woche${weeks===1?'':'n'}`;const months=Math.floor(days/30);return `${months} Monat${months===1?'':'e'}`;},countdownText=(seconds)=>{const total=Math.max(0,Math.ceil(seconds)),m=Math.floor(total/60),sec=total%60;return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`},surplusText=known?`${surplus>=0?'+':'−'}${fmt(Math.abs(surplus),0)} W Überschuss`:'Sicherer Überschuss nach Haus/Speicher nicht verfügbar';let title='PV-Überschuss wird geprüft',clock='–',clockLabel='',detail=surplusText,tone='neutral';if(key==='locked_low'){title='Zu wenig Überschuss für Phase 1';clock=timeText(statusElapsed);clockLabel='zu wenig seit';detail=`${surplusText} · noch ${fmt(Math.max(0,p1-surplus),0)} W bis ${fmt(p1,0)} W`;tone='low'}else if(key==='locked_waiting_start'){const remaining=Math.max(0,fast-candidateElapsed);title=`Wallbox wird in ${countdownText(remaining)} eingeschaltet`;clock=countdownText(remaining);clockLabel='noch';detail=`${surplusText} · seit ${timeText(candidateElapsed)} über ${fmt(p1,0)} W`;tone='waiting'}else if(key==='phase1_low'){const remaining=Math.max(0,fast-candidateElapsed);title=`Ladung wird in ${countdownText(remaining)} beendet`;clock=countdownText(remaining);clockLabel='noch';detail=`${surplusText} · unter ${fmt(p1stop,0)} W`;tone='stop'}else if(key==='phase1_waiting_phase2'){const remaining=Math.max(0,slow-candidateElapsed);title=`Phase 2 wird in ${countdownText(remaining)} dazugeschaltet`;clock=countdownText(remaining);clockLabel='noch';detail=`${surplusText} · seit ${timeText(candidateElapsed)} über ${fmt(p2,0)} W`;tone='waiting'}else if(key==='phase2_low'){const remaining=Math.max(0,fast-candidateElapsed);title=`Phase 2 wird in ${countdownText(remaining)} abgeschaltet`;clock=countdownText(remaining);clockLabel='noch';detail=`${surplusText} · unter ${fmt(p2stop,0)} W`;tone='stop'}else if(key==='phase2_waiting_phase3'){const remaining=Math.max(0,slow-candidateElapsed);title=`Phase 3 wird in ${countdownText(remaining)} dazugeschaltet`;clock=countdownText(remaining);clockLabel='noch';detail=`${surplusText} · seit ${timeText(candidateElapsed)} über ${fmt(p3,0)} W`;tone='waiting'}else if(key==='phase3_low'){const remaining=Math.max(0,fast-candidateElapsed);title=`Phase 3 wird in ${countdownText(remaining)} abgeschaltet`;clock=countdownText(remaining);clockLabel='noch';detail=`${surplusText} · unter ${fmt(p3stop,0)} W`;tone='stop'}else if(current>0){title=`Lädt mit ${phaseWord(current)} seit ${timeText(phaseElapsed)}`;clock=timeText(chargingElapsed);clockLabel='Ladung gesamt';detail=`${surplusText} · ${current===1?`bis ${fmt(p2,0)} W für Phase 2`:current===2?`bis ${fmt(p3,0)} W für Phase 3`:'höchste Phase aktiv'}`;tone='active'}box.className=`pvPhaseStatus ${tone}`;box.innerHTML=`<div class="pvPhaseMain"><div><span>PV-Ladeautomatik</span><b>${title}</b><small>${detail}</small></div><div class="pvPhaseClock"><b>${clock}</b><span>${clockLabel}</span></div></div>`}
const renderPvPhaseStatus137=renderPvPhaseStatus;
renderPvPhaseStatus=function(){const box=q('#pvPhaseStatus'),c=DATA.pv_surplus_control||{},key=String(c.status_key||'');const messages={master_disabled:['Gesamtautomatik ist aus','Die PV-Wallbox bleibt unverändert, bis die Gesamtautomatik aktiviert wird.'],automation_disabled:['PV-Wallbox-Automatik ist aus','Unter Einstellungen „PV-Wallbox automatisch“ einschalten.'],manual_car_block:['Auto-Ladeautomatik pausiert','Manuell auf der Übersicht pausiert. Direktsteuerung bleibt möglich.'],battery_priority:['Speicher hat Vorrang',String(c.last_action||'Der Hausspeicher wird vor dem Auto geladen.')],no_car:['Kein Auto an der Wallbox gewählt','Für PV-Laden muss „Auto: Ja“ aktiv sein.'],forecast_missing:['PV-Prognose fehlt','Ohne aktuellen Plan startet die Wallbox nicht automatisch.'],planning_error:['PV-Tagesplanung wird erneut berechnet','Die Statusanzeige bleibt aktiv; der nächste Lauf prüft den Start wieder.'],budget_low:['Speicher und Resttag haben Vorrang','Die Rest-PV reicht nach Haus, Speicher bis 100 %, Warmwasser und Sicherheitsreserve noch nicht fürs Auto.'],power_missing:['Netz-/Wallboxleistung fehlt','Ohne sicheren Überschuss nach Haus und Speicher bleibt die Wallbox gesperrt.'],outside_pv_window:['PV-Tagesfenster beendet','PV-Laden ist nachts gesperrt; Nachtladen läuft ausschließlich im Schnellladen-Modus.'],fast_manual:['Schnellladen hat Vorrang','Der manuell gesetzte Schnellladen-Modus wird nicht von der PV-Automatik verändert.']}[key];if(!box||!messages)return renderPvPhaseStatus137();box.className='pvPhaseStatus low';box.innerHTML=`<div class="pvPhaseMain"><div><span>PV-Ladeautomatik</span><b>${messages[0]}</b><small>${messages[1]}</small></div><div class="pvPhaseClock"><b>–</b></div></div>`}
const renderPvPhaseStatus139=renderPvPhaseStatus;
renderPvPhaseStatus=function(){const box=q('#pvPhaseStatus'),c=DATA.pv_surplus_control||{},key=String(c.status_key||'');if(!box||key)return renderPvPhaseStatus139();const s=DATA.settings||{},l=DATA.live||{},surplus=Number(l.pv_minus_house_w),known=l.pv_minus_house_w!==null&&l.pv_minus_house_w!==undefined&&Number.isFinite(surplus),p1=Number(s.pv_phase1_start_w||1600),current=l.wallbox_mode==='optimized'?1+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0):0;if(!known)return renderPvPhaseStatus139();const detail=`${surplus>=0?'+':'−'}${fmt(Math.abs(surplus),0)} W Überschuss`;if(current===0&&surplus<p1){box.className='pvPhaseStatus low';box.innerHTML=`<div class="pvPhaseMain"><div><span>PV-Ladeautomatik</span><b>Zu wenig Überschuss für Phase 1</b><small>${detail} · noch ${fmt(Math.max(0,p1-surplus),0)} W bis ${fmt(p1,0)} W</small></div><div class="pvPhaseClock"><b>–</b><span>Status wird innerhalb von 5 Sek. abgeglichen</span></div></div>`;return}if(current===0&&surplus>=p1){box.className='pvPhaseStatus waiting';box.innerHTML=`<div class="pvPhaseMain"><div><span>PV-Ladeautomatik</span><b>Überschuss erkannt · Startzeit wird synchronisiert</b><small>${detail} · die Wallbox wird nach 120 Sek. stabilem Überschuss freigegeben.</small></div><div class="pvPhaseClock"><b>…</b><span>max. 5 Sek.</span></div></div>`;return}return renderPvPhaseStatus139()}
function renderPhaseRules(){const s=DATA.settings||{},c=DATA.pv_surplus_control||{},target=Number(c.candidate_phases),elapsed=Math.max(0,Number(c.candidate_elapsed_seconds||0)),current=(DATA.live||{}).wallbox_mode==='optimized'?1+((DATA.live||{}).phase2==='on'?1:0)+((DATA.live||{}).phase3==='on'?1:0):0,adding=target>current&&current>0,wait=adding?Number(s.pv_phase_hold_seconds||1800):Number(s.pv_surplus_delay_seconds||120),progress=target?Math.min(100,Math.round(elapsed/Math.max(1,wait)*100)):0,minutes=x=>x>=60?`${fmt(x/60,1)} Min.`:`${fmt(x,0)} s`,status=target?`Überschuss für ${target} ${target===1?'Phase':'Phasen'} seit ${minutes(elapsed)} stabil.`:`Automatik überwacht den Überschuss kontinuierlich.`;q('#phaseRules').innerHTML=`<div class="phaseSetting"><span>Wallbox ein / aus</span><b>stabil <em>${minutes(s.pv_surplus_delay_seconds||120)}</em></b></div><div class="phaseSetting"><span>Phase 2 / 3 dazu</span><b>stabil über Schwelle <em>${minutes(s.pv_phase_hold_seconds||1800)}</em></b></div>${target?`<div class="phaseProgress"><i style="width:${progress}%"></i></div>`:''}<div class="phaseStatus">${status}</div>`}
function toggleBatteryNow(){action(DATA.live?.safe_charge==='on'?'safe_charge_off':'safe_charge_on')}function toggleWarmwaterNow(){action(DATA.live?.warmwater==='on'?'warmwater_off':'warmwater_on')}
const _renderLearningBase=renderLearning;renderLearning=function(){_renderLearningBase();renderMorningCalculation();const l=DATA.learning||{},m=l.morning||{},today=String(l.today||DATA.time||'').slice(0,10),last=String(m.last_sample_date||'');if(last!==today){const summary=q('#learningSummary'),row=summary?.querySelector('.learnRow:last-child');if(row)row.innerHTML=`🌅 Morgenlauf heute (${today}): <b>noch nicht vollständig erfasst</b> · letzter vollständiger Lauf ${last||'–'} · PV-Übernahme zuletzt ${m.last_cover_date||last||'–'} ${m.last_cover_time||'–'}`;const card=q('#morningLearningCard');if(card)card.innerHTML=`Heute (${today}): Morgenwerte werden nach dem vollständigen Messfenster eingetragen. Letzter vollständiger Lauf: <b>${last||'–'}</b> · PV-Übernahme zuletzt <b>${m.last_cover_date||last||'–'} ${m.last_cover_time||'–'}</b> · dabei <b>${fmt(m.last_soc_cover,0)}%</b> · Bedarf <b>${fmt(m.last_net_need_kwh,2)} kWh</b>.`;}};


// 0.1.58 · Auto-Ladepause, PV-Tagesfortschritt und Speicherpriorität.
async function setCarAutoCharging(enabled){try{const j=await post('car-auto-charging',{enabled});DATA.car_auto_charging_enabled=Boolean(j.enabled);renderPvPhaseStatus();renderNow();toast(j.message||'Auto-Ladeautomatik aktualisiert');refreshSoon(350)}catch(e){toast(e.message||'Auto-Ladeautomatik konnte nicht geändert werden')}}
function renderPvDayProgress(){const box=q('#pvDayProgress');if(!box)return;const lp=DATA.live_pv||{},l=DATA.live||{},actual=lp.actual_kwh??l.pv_today_kwh,expected=lp.expected_so_far_kwh,remaining=lp.remaining_adjusted_kwh,delta=Number(lp.delta_percent),tone=Number.isFinite(delta)?(delta<=-15?'low':delta>=15?'good':''):'';box.innerHTML=`<div class="pvProgressTitle">PV heute</div><div class="pvProgressMetric ${tone}"><span>erzeugt</span><b>${actual==null?'–':fmt(actual,1)+' kWh'}</b></div><div class="pvProgressMetric"><span>Soll bis jetzt</span><b>${expected==null?'–':fmt(expected,1)+' kWh'}</b></div><div class="pvProgressMetric"><span>noch erwartet</span><b>${remaining==null?'–':fmt(remaining,1)+' kWh'}</b></div>`}
const _renderPvPhaseStatusAutoBase=renderPvPhaseStatus;renderPvPhaseStatus=function(){_renderPvPhaseStatusAutoBase();const box=q('#pvPhaseStatus');if(!box)return;box.classList.add('withAutoControl');box.querySelectorAll('.pvAutoPauseBtn').forEach(x=>x.remove());const enabled=DATA.car_auto_charging_enabled!==false,btn=document.createElement('button');btn.className='pvAutoPauseBtn'+(enabled?'':' paused');btn.textContent=enabled?'Auto laden: AN':'Auto laden: PAUSE';btn.onclick=()=>setCarAutoCharging(!enabled);box.appendChild(btn)}

// 0.1.58 · Push-Transport, iPhone-Safe-Area und speicherpriorisierte Wallbox.
renderNow=function(){
  const l=DATA.live||{},p=DATA.plan||{},ww=p.warmwater||{},lp=DATA.live_pv||{};
  const wbMode=l.wallbox_mode||'–',wbPower=Math.max(0,Number(l.wallbox_power_w||0));
  let autoState=wbMode==='fast'?'Schnellladen':DATA.car_auto_charging_enabled===false?'Auto pausiert':wbMode==='optimized'?'PV-Laden':wbMode==='locked'?'Gesperrt':wbMode;
  const enabledPhases=(l.phase1==='on'?1:0)+(l.phase2==='on'?1:0)+(l.phase3==='on'?1:0),powerText=wbPower>=1000?`${fmt(wbPower/1000,1)} kW`:`${fmt(wbPower,0)} W`;
  const phaseText=wbPower>50?`${enabledPhases} ${enabledPhases===1?'Phase':'Phasen'} aktiv`:`${enabledPhases}/3 Phasen freigegeben`;
  const currentHour=new Date(DATA.time).getHours(),wwNow=currentHour>=5?(p.today_warmwater||{}):ww;
  let wDetail='Heute noch offen';if(wwNow.mode==='done')wDetail='Heute erledigt';else if(wwNow.start_time||wwNow.end_time)wDetail=`${wwNow.start_time||'–'}–${wwNow.end_time||'–'} Uhr`;
  const pvRest=lp.remaining_adjusted_kwh??null,pvExpected=lp.adjusted_expected_kwh??lp.original_expected_kwh??null;
  const cableState=v=>v==='on'?'🔌':v==='off'?'':'?';const cars=`ID.7 ${fmt(l.id7_soc,0)}%${cableState(l.id7_cable)} · e-Golf ${fmt(l.egolf_soc,0)}%${cableState(l.egolf_cable)}`;
  q('#nowStrip').innerHTML=`<div class="nowChip compactPrimary"><div class="nowIcon">🔋</div><div><span class="nowLabel">Speicher</span><strong>${fmt(l.battery_soc,0)}%</strong><small>${l.safe_charge==='on'?'Netzladung aktiv':'Automatik aktiv'}</small></div></div><div class="nowChip"><div class="nowIcon">🚗</div><div><span class="nowLabel">Wallbox</span><strong>${autoState}</strong><small>${powerText} · ${phaseText}</small><small class="carMiniState">${cars}</small></div></div><div class="nowChip"><div class="nowIcon">🚿</div><div><span class="nowLabel">Warmwasser</span><strong>${fmt(l.warmwater_temp,1)} °C</strong><small>${wDetail}</small></div></div><div class="nowChip"><div class="nowIcon">☀️</div><div><span class="nowLabel">PV noch</span><strong>${pvRest==null?'–':fmt(pvRest,1)+' kWh'}</strong><small>${pvExpected==null?'Rest heute':`von ca. ${fmt(pvExpected,1)} kWh heute`}</small></div></div>`;
};

renderEnergy=function(){
  const l=DATA.live||{},pv=Math.max(0,Number(l.pv_power_w||0)),house=Math.max(0,Number(l.house_power_w||0)),bat=Number(l.battery_power_w||0),grid=Number(l.grid_power_w||0),wallbox=Math.max(0,Number(l.wallbox_power_w||0)),dish=Math.max(0,Number(l.dishwasher_power_w||0)),office=l.climate_office_live_w,kids=l.climate_kids_live_w,wp=Number(l.wp_power_value||0),wpUnit=String(l.wp_power_unit||'').trim();
  const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v)),kwh=(v,d=1)=>finite(v)?`${fmt(v,d)} kWh`:'–',watt=v=>finite(v)?`${fmt(v,0)} W`:'–';
  const haveHouseDay=[l.pv_today_kwh,l.net_import_today_kwh,l.grid_export_today_kwh,l.battery_charge_today_kwh,l.battery_discharge_today_kwh].every(finite),pvDay=Number(l.pv_today_kwh),netIn=Number(l.net_import_today_kwh),netOut=Number(l.grid_export_today_kwh),batIn=Number(l.battery_charge_today_kwh),batOut=Number(l.battery_discharge_today_kwh),houseDay=haveHouseDay?Math.max(0,pvDay+netIn+batOut-netOut-batIn):null;
  const batteryValue=Math.abs(bat)<20?'0 W':`${bat<0?'−':'+'}${fmt(Math.abs(bat),0)} W`,batteryState=bat< -20?'isDischarging':bat>20?'isCharging':'';
  const gridValue=Math.abs(grid)<20?'0 W':`${grid<0?'+':'−'}${fmt(Math.abs(grid),0)} W`,gridState=grid>20?'importing':grid< -20?'exporting':'';
  const wpValue=wpUnit?`${fmt(wp,wpUnit.toLowerCase()==='w'?0:2)} ${wpUnit}`:watt(wp),officeValue=office==null?'≈0 W':`≈${fmt(office,0)} W`,kidsValue=kids==null?'≈0 W':`≈${fmt(kids,0)} W`;
  const node=(slot,cls,icon,label,value,sub)=>`<div class="flowNode flowSlot-${slot} ${cls||''}"><div class="flowIcon">${icon}</div><div class="flowText"><span>${label}</span><b>${value}</b><small>${sub||''}</small></div></div>`;
  const path=(d,cls,active,bus=false)=>`${bus?`<path class="flowBus" d="${d}"/>`:`<path class="flowBase" d="${d}"/>`}${active?`<path class="flowPulse ${cls}" d="${d}"/>`:''}`;
  const pvPath='M 16.7 22 L 16.7 35 L 50 35 L 50 43';
  const gridPath=grid>20?'M 50 22 L 50 43':'M 50 43 L 50 22';
  const batteryPath=bat< -20?'M 83.3 22 L 83.3 35 L 50 35 L 50 43':'M 50 43 L 50 35 L 83.3 35 L 83.3 22';
  const consumerBase='M 50 57 L 50 66';
  const loadPaths={wallbox:'M 50 66 L 10 66 L 10 78',heatpump:'M 50 66 L 30 66 L 30 78',dishwasher:'M 50 66 L 50 78',office:'M 50 66 L 70 66 L 70 78',kids:'M 50 66 L 90 66 L 90 78'};
  const desktopSvg=`<svg class="energyFlowSvgDesktop" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${path('M 16.7 35 L 83.3 35','',false,true)}${path('M 10 66 L 90 66','',false,true)}${path(pvPath,'pv',pv>20)}${path(gridPath,grid>20?'gridImport':'gridExport',Math.abs(grid)>20)}${path(batteryPath,'battery',Math.abs(bat)>20)}${path(consumerBase,'',false)}${path(loadPaths.wallbox,'consumer',wallbox>20)}${path(loadPaths.heatpump,'consumer',Math.abs(wp)>0.01)}${path(loadPaths.dishwasher,'consumer',dish>10)}${path(loadPaths.office,'consumer',Number(office||0)>10)}${path(loadPaths.kids,'consumer',Number(kids||0)>10)}</svg>`;
  const mobilePv='M 17 8.5 L 17 19 L 50 19 L 50 21.5',mobileGrid=grid>20?'M 50 8.5 L 50 21.5':'M 50 21.5 L 50 8.5',mobileBat=bat< -20?'M 83 8.5 L 83 19 L 50 19 L 50 21.5':'M 50 21.5 L 50 19 L 83 19 L 83 8.5';
  const mobileSvg=`<svg class="energyFlowSvgMobile" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${path('M 17 19 L 83 19','',false,true)}${path(mobilePv,'pv',pv>20)}${path(mobileGrid,grid>20?'gridImport':'gridExport',Math.abs(grid)>20)}${path(mobileBat,'battery',Math.abs(bat)>20)}${path('M 50 41 L 50 42.7','',false)}${path('M 50 42.7 L 25 42.7 L 25 45','consumer',wallbox>20)}${path('M 50 42.7 L 75 42.7 L 75 45','consumer',Math.abs(wp)>0.01)}${path('M 50 41 L 50 61.8 L 25 61.8 L 25 64.1','consumer',dish>10)}${path('M 50 61.8 L 75 61.8 L 75 64.1','consumer',Number(office||0)>10)}${path('M 50 41 L 50 80.8 L 50 83.1','consumer',Number(kids||0)>10)}</svg>`;
  const amount=(cls,text)=>`<span class="flowAmount ${cls}">${text}</span>`;
  q('#balanceGrid').innerHTML=`<div class="energyFlowStage">${desktopSvg}${mobileSvg}${node('pv','source pv','☀️','PV',`${fmt(pv,0)} W`,`Heute ${kwh(l.pv_today_kwh)}`)}${node('grid',`source grid ${gridState}`,'⚡','Netz',gridValue,`Bezug ${kwh(l.net_import_today_kwh)} · Einspeisung ${kwh(l.grid_export_today_kwh)}`)}${node('battery',`source battery ${batteryState}`,'🔋','Speicher',batteryValue,`SOC ${fmt(l.battery_soc,0)}% · heute ↑ ${kwh(l.battery_charge_today_kwh)} ↓ ${kwh(l.battery_discharge_today_kwh)}`)}${node('house','house','🏠','Haus',`${fmt(house,0)} W`,houseDay==null?'Tageswert –':`Heute ${kwh(houseDay)}`)}${node('wallbox','consumer','🚗','Wallbox',watt(wallbox),`Heute ${kwh(l.wallbox_today_kwh)}`)}${node('heatpump','consumer','🔥','Wärmepumpe',wpValue,`Heute ${kwh(l.wp_today_kwh)}`)}${node('dishwasher','consumer','🍽️','Spülmaschine',watt(dish),`Heute ${kwh(l.dishwasher_today_kwh)}`)}${node('office','consumer','❄️','Klima Büro',officeValue,`Heute ${kwh(l.climate_office_today_kwh)}`)}${node('kids','consumer','❄️','Klima KiZi',kidsValue,`Heute ${kwh(l.climate_kids_today_kwh)}`)}${amount('pv',`${fmt(pv,0)} W`)}${amount('grid',gridValue)}${amount('battery',batteryValue)}${amount('wallbox',watt(wallbox))}${amount('heatpump',wpValue)}${amount('dishwasher',watt(dish))}${amount('office',officeValue)}${amount('kids',kidsValue)}</div><div class="energyFlowHint"><b>Oben Quellen & Speicher</b> · Haus als zentraler Verteiler · darunter alle direkt erfassten Verbraucher. Bewegte Punkte zeigen aktive Flussrichtung.</div>`;
  const learn=DATA.learning||{},m=learn.recent_mape_percent??learn.baseline_test_mape_percent;q('#qualityLine').innerHTML=`Prognosequalität <b>${fmt(m,1)}% MAPE</b> · ${learn.history_count||0} Vergleichstage · Abendreserve <b>${fmt(learn.evening?.reserve_kwh||2.5)} kWh</b>`;
};

function renderNextActions(){
  const p=DATA.plan||{},b=p.battery||{},wb=p.wallbox||{},dw=p.dishwasher||{},ww=p.warmwater||{},l=DATA.live||{},target=Number(wb.night_target_soc||50),ov=DATA.night_override||'auto';
  let carText='Keine Nachtladung nötig';
  if(DATA.car_auto_charging_enabled===false)carText='Automatik pausiert';else if(!DATA.car_at_wallbox)carText='Kein Auto an Wallbox';else if(ov==='pv_wait')carText='nachts nur PV';else if(ov==='fast'||wb.recommended==='fast'||Number(wb.connected_soc??0)<target)carText=`nachts bis ${target}%`;
  const dishText=dw.mode==='night'?(dw.time||'nachts'):(dw.time?`PV ${dw.time}`:'im PV-Fenster');
  const wwText=ww.mode==='night'?`${ww.start_time||'–'}–${ww.end_time||'–'}`:(ww.mode==='done'?'erledigt':ww.start_time?`PV ${ww.start_time}–${ww.end_time||'–'}`:'im PV-Fenster');
  q('#nextActionsButton').innerHTML=`<div class="nextActionsTitle"><strong>Nächste Aktionen</strong><small>Heute Nacht & morgen früh · Details in Planung</small></div><div class="nextActionItems"><span class="nextActionItem"><span class="naIcon">🚗</span><b>Auto ${carText}</b></span><span class="nextActionItem"><span class="naIcon">🍽️</span><b>Spülmaschine ${dishText}</b></span><span class="nextActionItem"><span class="naIcon">🚿</span><b>Warmwasser ${wwText}</b></span></div><span class="nextActionArrow">›</span>`;
}

renderOverviewGoal=function(){
  const p=DATA.plan||{},b=p.battery||{},l=DATA.learning||{},m=l.morning||{};const target=Number(b.target_soc??b.planned_0500_target_soc??0),need=b.predicted_morning_need_kwh,cover=b.adjusted_cover_time||b.predicted_cover_time||'–',reserve=Number(m.desired_cover_soc??DATA.settings?.morning_min_soc??0),last=Number(m.last_soc_0500??0),deg=Math.max(0,Math.min(100,target))*3.6;
  q('#overviewGoalCard').innerHTML=`<div class="goalTop"><div><div class="eyebrow">Nächstes 05:00-Ziel</div><div class="goalRing" style="--goal:${deg}deg"><div><strong>${fmt(target,0)}%</strong><span>Speicher</span></div></div></div><div class="goalFacts"><div><span>Bedarf morgen früh</span><b>${need==null?'–':fmt(need,2)+' kWh'}</b></div><div><span>PV übernimmt</span><b>${cover}</b></div><div><span>Mindestreserve</span><b>${fmt(reserve,0)}%</b></div><div><span>Letzter Morgen</span><b>${fmt(last,0)}%</b></div></div></div><button class="goalLink" onclick="showPage('learning')">Details & Berechnung <span>›</span></button>`;
};

renderMorningCalculation=function(){
  const box=q('#morningCalculation');if(!box)return;const pb=DATA.plan?.battery||{},rows=Array.isArray(pb.morning_breakdown)?pb.morning_breakdown:[],rest=pb.standby_restload_w,pred=pb.predicted_cover_time||'–',adj=pb.adjusted_cover_time||pred,plan=pb.morning_forecast_basis_kwh,need=pb.bridge_need_before_buffer_kwh??pb.predicted_morning_need_kwh,bufSoc=Number(pb.morning_energy_buffer_soc||0),bufKwh=pb.bridge_energy_buffer_kwh??(7.5*bufSoc/100),reserve=Number(pb.minimum_reserve_soc||0),reserveKwh=7.5*reserve/100,restExtra=Number(pb.post_bridge_extra_soc||0),restExtraKwh=7.5*restExtra/100,auto=pb.automatic_target_soc,target=pb.target_soc,source=pb.cover_time_source||'–';
  const intro=`<div class="calcIntro"><div class="calcStat"><span>Restlast Morgenbrücke</span><b>${rest==null?'–':fmt(rest,0)+' W'}</b></div><div class="calcStat"><span>PV stabil prognostiziert</span><b>${pred}</b></div><div class="calcStat"><span>mit Lern-Zeitpuffer</span><b>${adj}</b></div><div class="calcStat"><span>konservative PV-Basis</span><b>${plan==null?'–':fmt(plan,1)+' kWh'}</b></div></div>`;
  const timeline=rows.length?`<div class="calcTimeline">${rows.map(r=>`<div class="calcHour"><div class="calcHourHead"><b>${r.from||'–'}–${r.to||'–'}</b><strong>Speicher ${fmt(r.net_need_kwh,3)} kWh</strong></div><div class="calcHourFormula"><div class="calcPart"><span>erwartete Restlast</span><b>${fmt(r.load_kwh,3)} kWh</b></div><div class="calcPart"><span>PV in diesem Abschnitt</span><b>− ${fmt(r.pv_kwh,3)} kWh</b></div><div class="calcPart"><span>Netto aus Speicher</span><b>${fmt(r.net_need_kwh,3)} kWh</b></div></div></div>`).join('')}</div>`:`<div class="calcFormula">Für die aktuelle Prognose liegt noch keine stundenweise Morgenrechnung vor.</div>`;
  const total=`<div class="calcTotal"><h4>So entsteht das 05:00-Ziel</h4><div class="calcEquationLine"><span>Netto-Morgenbedarf 05:00 → PV-Übernahme</span><b>${need==null?'–':fmt(need,2)+' kWh'}</b></div><div class="calcEquationLine"><span>+ gelernter Energiepuffer</span><b>${fmt(bufSoc,1)}% = ${fmt(bufKwh,2)} kWh</b></div><div class="calcEquationLine"><span>+ dynamische Mindestreserve</span><b>${fmt(reserve,0)}% = ${fmt(reserveKwh,2)} kWh</b></div>${restExtra>0?`<div class="calcEquationLine"><span>+ Resttag-Puffer</span><b>${fmt(restExtra,1)}% = ${fmt(restExtraKwh,2)} kWh</b></div>`:''}<div class="calcEquationLine"><span>Automatisches Rechenergebnis</span><b>${auto==null?'–':fmt(auto,1)+'%'}</b></div><div class="calcEquationLine result"><span>Gerundetes 05:00-Ziel</span><b>${target==null?'–':fmt(target,0)+'%'}</b></div><div class="calcEquationLine"><span>PV-Übernahmequelle</span><b>${source}</b></div><div class="calcEquationLine"><span>Hinweis</span><b>Morgenbrücke mit gelernter Restlast; 0,85-kW-Grundlast erst für Resttag</b></div></div>`;
  box.innerHTML=intro+timeline+total;
};

const render_0151=render;
render=function(){if(!DATA)return;q('#version').textContent=DATA.version;const sv=q('#sideVersion');if(sv)sv.textContent=DATA.version;renderStatus();renderNow();renderNight();renderEnergy();renderOverviewGoal();renderPvDayProgress();renderNextActions();renderPvPhaseStatus();renderForecasts();renderPV();renderControls();renderLearning();fillSettings()};

let ACTIVE_PAGE='overview',PRE_SETTINGS_PAGE='overview',TOUCH_START_X=null,TOUCH_START_Y=null;
function showPage(page,fromSwipe=false){const valid=['overview','planning','pv','learning','control','settings'];if(!valid.includes(page))page='overview';if(page==='settings'&&ACTIVE_PAGE!=='settings')PRE_SETTINGS_PAGE=ACTIVE_PAGE;if(page!=='settings')ACTIVE_PAGE=page;document.querySelectorAll('[data-page-panel]').forEach(el=>el.classList.toggle('show',el.dataset.pagePanel===page));document.querySelectorAll('.appNav').forEach(el=>el.classList.toggle('active',el.dataset.page===page));if(page==='settings')document.querySelectorAll('.appNav').forEach(el=>el.classList.remove('active'));if(!fromSwipe)window.scrollTo({top:0,behavior:'smooth'});try{sessionStorage.setItem('energieplanerPage',page==='settings'?PRE_SETTINGS_PAGE:page)}catch(e){}}
function goBackFromSettings(){showPage(PRE_SETTINGS_PAGE||'overview')}
document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',()=>showPage(el.dataset.page)));
document.addEventListener('touchstart',e=>{if(innerWidth>720||e.touches.length!==1||e.target.closest('.forecastRail,.targetQuick,.presence,.nightControls,.controlDetails,.calculationDetails,input,select,button'))return;const t=e.touches[0];TOUCH_START_X=t.clientX;TOUCH_START_Y=t.clientY},{passive:true});document.addEventListener('touchend',e=>{if(innerWidth>720||TOUCH_START_X===null||ACTIVE_PAGE==='settings')return;const t=e.changedTouches[0],dx=t.clientX-TOUCH_START_X,dy=t.clientY-TOUCH_START_Y;TOUCH_START_X=TOUCH_START_Y=null;if(Math.abs(dx)<70||Math.abs(dx)<Math.abs(dy)*1.35)return;const pages=['overview','planning','pv','learning','control'],i=pages.indexOf(ACTIVE_PAGE);if(i<0)return;const next=dx<0?Math.min(pages.length-1,i+1):Math.max(0,i-1);if(next!==i)showPage(pages[next],true)},{passive:true});
try{showPage(sessionStorage.getItem('energieplanerPage')||'overview',true)}catch(e){showPage('overview',true)}
getData();setInterval(()=>{if(DATA)renderPvPhaseStatus()},1000);setInterval(()=>getPvStatus(),5000);setInterval(()=>getData(true),15000);
</script>
</body>
</html>'''

ALLOWED_SETTING_KEYS = set(DEFAULT_SETTINGS.keys())
NUMERIC_SETTING_KEYS = {
    key for key, value in DEFAULT_SETTINGS.items()
    if isinstance(value, (int, float)) and not isinstance(value, bool)
}
SIGNED_SETTING_KEYS = {"battery_soc_manual_offset"}


def clean_settings_update(body: dict[str, Any]) -> dict[str, Any]:
    """Typgesicherte Einstellungen speichern statt still ungültige Werte zu übernehmen."""
    cleaned: dict[str, Any] = {}
    for key, value in body.items():
        if key not in ALLOWED_SETTING_KEYS:
            continue
        default = DEFAULT_SETTINGS[key]
        if key in NUMERIC_SETTING_KEYS:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"Ungültiger Zahlenwert für {key}")
            if not math.isfinite(number):
                raise ValueError(f"Ungültiger Zahlenwert für {key}")
            if key in SIGNED_SETTING_KEYS:
                if number < -10 or number > 10:
                    raise ValueError(f"{key} muss zwischen -10 und +10 liegen")
            elif number < 0:
                raise ValueError(f"{key} muss eine positive Zahl sein")
            if key == "gemini_daily_limit" and number < 2:
                raise ValueError("Für die festen Gemini-Läufe um 07:00 und 20:00 sind mindestens 2 Aufrufe nötig")
            cleaned[key] = int(number) if isinstance(default, int) else number
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"Ungültiger Schalterwert für {key}")
            cleaned[key] = value
        elif isinstance(default, str):
            cleaned[key] = str(value)
    return cleaned


class Handler(BaseHTTPRequestHandler):
    server_version = "Energieplaner/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("HTTP %s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self) -> None:
        raw = INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_bytes(self, raw: bytes, content_type: str, cache_control: str = "public, max-age=86400") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_asset(self, filename: str, content_type: str) -> None:
        path = Path(__file__).resolve().parent / filename
        if not path.is_file():
            self._send_json({"error": "Asset nicht gefunden"}, 404)
            return
        self._send_bytes(path.read_bytes(), content_type)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if path.endswith("/manifest.webmanifest") or path == "/manifest.webmanifest":
            self._send_bytes(MANIFEST_JSON.encode("utf-8"), "application/manifest+json; charset=utf-8", "no-cache")
            return
        for asset_name, asset_type in (("apple-touch-icon.png", "image/png"), ("icon-192.png", "image/png"), ("icon-512.png", "image/png"), ("favicon.png", "image/png")):
            if path.endswith("/" + asset_name) or path == "/" + asset_name:
                self._send_asset(asset_name, asset_type)
                return
        if path.endswith("/api/health") or path == "/api/health":
            self._send_json({"ok": True, "version": VERSION})
            return
        if path.endswith("/api/dashboard") or path == "/api/dashboard":
            try:
                self._send_json(dashboard_cached())
            except Exception as exc:
                LOG.exception("Dashboard-API fehlgeschlagen")
                self._send_json({"error": str(exc)}, 500)
            return
        if path.endswith("/api/pv-status") or path == "/api/pv-status":
            self._send_json(pv_status_payload())
            return
        if path.endswith("/api/settings") or path == "/api/settings":
            self._send_json(settings_store.data)
            return
        self._send_html()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        try:
            body = self._body()
            if path.endswith("/api/settings") or path == "/api/settings":
                cleaned = clean_settings_update(body)
                if not cleaned:
                    self._send_json({"error": "Keine gültigen Einstellungen erhalten"}, 400)
                    return
                with settings_store.lock:
                    settings_store.data.update(cleaned)
                    settings_store.save()
                rebuild_plan_from_saved_forecast()
                _kick_dashboard_refresh()
                self._send_json({"ok": True, "message": "Gespeichert ohne Gemini-Aufruf", "settings": settings_store.data})
                return
            if path.endswith("/api/car-presence") or path == "/api/car-presence":
                present = bool(body.get("present"))
                with state_store.lock:
                    state_store.data["car_at_wallbox"] = present
                    if not present:
                        state_store.data["night_target_override_soc"] = None
                    state_store.save()
                _kick_dashboard_refresh()
                if not present and state_text(ENTITIES["wallbox_mode"]) in {"fast", "optimized"}:
                    wallbox_set_locked(track_night=0 <= now_local().hour < 5)
                self._send_json({"ok": True, "message": "Auto an Wallbox: Ja" if present else "Auto an Wallbox: Nein"})
                return
            if path.endswith("/api/car-auto-charging") or path == "/api/car-auto-charging":
                enabled = bool(body.get("enabled"))
                with state_store.lock:
                    state_store.data["car_auto_charging_enabled"] = enabled
                    state_store.save()
                if not enabled and state_text(ENTITIES["wallbox_mode"]) in {"fast", "optimized"}:
                    wallbox_set_locked(track_night=0 <= now_local().hour < 5)
                _kick_dashboard_refresh()
                self._send_json({
                    "ok": True,
                    "enabled": enabled,
                    "message": "Auto-Ladeautomatik aktiv" if enabled else "Auto-Ladeautomatik pausiert",
                })
                return
            if path.endswith("/api/night-target") or path == "/api/night-target":
                raw_target = body.get("target")
                if raw_target in {None, "", "default"}:
                    target = None
                else:
                    try:
                        target = int(raw_target)
                    except Exception:
                        self._send_json({"error": "Ungültiges Nachtziel"}, 400)
                        return
                    if not 20 <= target <= 100:
                        self._send_json({"error": "Nachtziel muss zwischen 20 und 100 % liegen"}, 400)
                        return
                with state_store.lock:
                    state_store.data["night_target_override_soc"] = target
                    state_store.save()
                _kick_dashboard_refresh()
                self._send_json({
                    "ok": True,
                    "message": "Standard-Mindest-SOC aktiv" if target is None else f"Mindest-SOC bis 05:00 auf {target}% gesetzt",
                    "night_override": state_store.data.get("night_override", "auto"),
                    "target": target,
                })
                return
            if path.endswith("/api/night-override") or path == "/api/night-override":
                mode = str(body.get("mode", "auto"))
                if mode not in {"auto", "fast", "pv_wait"}:
                    self._send_json({"error": "Ungültiger Modus"}, 400)
                    return
                if mode == "fast" and not car_at_wallbox():
                    self._send_json({"error": "Bitte zuerst Auto an Wallbox = Ja setzen"}, 400)
                    return
                with state_store.lock:
                    state_store.data["night_override"] = mode
                    state_store.save()
                _kick_dashboard_refresh()
                labels = {"auto": "Automatik aktiv · tagsüber PV, nachts Mindest-SOC absichern", "fast": "Nacht schnell aktiv", "pv_wait": "Nur PV aktiv · nachts kein Schnellladen"}
                self._send_json({"ok": True, "message": labels.get(mode, mode)})
                return
            if path.endswith("/api/test-push") or path == "/api/test-push":
                configured = str(settings_store.data.get("notify_service", "notify.mobile_app_iphone A") or "")
                notify_entity = _primary_notify_entity(configured)
                effective, _ = resolve_notify_service(configured, owner_hint="primary")
                ok = send_notification(
                    "Energieplaner · Test",
                    "Test-Push an primary. Wenn du diese Nachricht siehst, funktioniert die Zustellung wieder.",
                    critical_silent=False,
                )
                if not ok:
                    candidates = sorted(x for x in _available_notify_services(max_age_seconds=0) if x.startswith("notify.mobile_app_") and "primary" in _notify_name(x))
                    self._send_json({
                        "error": "Test-Push konnte von Home Assistant nicht gesendet werden.",
                        "configured": configured,
                        "notify_entity": notify_entity,
                        "primary_services": candidates,
                    }, 500)
                    return
                route = f"notify.send_message → {notify_entity}" if notify_entity else effective
                self._send_json({"ok": True, "message": f"Test-Push von Home Assistant angenommen · {route}"})
                return
            if path.endswith("/api/test-partner-push") or path == "/api/test-partner-push":
                forecasts = state_store.data.get("forecast", {})
                hourly = {ds: v.get("hourly", []) for ds, v in forecasts.items() if isinstance(v, dict)} if isinstance(forecasts, dict) else {}
                plan = build_plan(forecasts, hourly) if isinstance(forecasts, dict) else {}
                if not plan or not forecasts:
                    self._send_json({"error": "Noch keine Prognose vorhanden"}, 409)
                    return
                partner_service = str(settings_store.data.get("partner_notify_service", "notify.mobile_app_secondary_iphone") or "")
                ok = send_notification(
                    "Energieplan für morgen",
                    partner_plan_message(plan, forecasts, reason="main"),
                    critical_silent=True,
                    service_full=partner_service,
                )
                if not ok:
                    self._send_json({"error": "Test-Push secondary konnte nicht gesendet werden. Notify-Service prüfen."}, 500)
                    return
                self._send_json({"ok": True, "message": "Test-Push secondary gesendet · kritisch, Lautstärke 0"})
                return
            if path.endswith("/api/action") or path == "/api/action":
                action = str(body.get("action", ""))
                message = self._run_action(action)
                _kick_dashboard_refresh()
                self._send_json({"ok": True, "message": message})
                return
            self._send_json({"error": "Nicht gefunden"}, 404)
        except Exception as exc:
            LOG.exception("POST fehlgeschlagen")
            self._send_json({"error": str(exc)}, 500)

    def _run_action(self, action: str) -> str:
        if action == "forecast_now":
            threading.Thread(target=lambda: forecast_run(reason="manual", notify=False), daemon=True).start()
            return "Prognose wird neu berechnet"
        if action == "wallbox_pv":
            wallbox_set_pv_phases(1)
            return "Wallbox auf PV / optimized, Phase 1"
        if action.startswith("wallbox_phase_"):
            try:
                phases = int(action.rsplit("_", 1)[1])
            except (TypeError, ValueError):
                raise ValueError("Ungültige Phasenwahl")
            if phases not in {1, 2, 3}:
                raise ValueError("Bitte 1, 2 oder 3 Phasen wählen")
            wallbox_set_pv_phases(phases)
            return f"PV-Laden auf {phases} {'Phase' if phases == 1 else 'Phasen'} gesetzt"
        if action == "wallbox_fast":
            wallbox_set_fast(track_night=0 <= now_local().hour < 5)
            return "Wallbox auf fast, Phasen 1–3 an"
        if action == "wallbox_locked":
            wallbox_set_locked(track_night=0 <= now_local().hour < 5)
            return "Wallbox gesperrt, Phase 1 bleibt an"
        if action == "safe_charge_on":
            battery_safe_charge(True, track_night=0 <= now_local().hour < 5)
            return "Speicher-Netzladung an"
        if action == "safe_charge_off":
            battery_safe_charge(False, track_night=0 <= now_local().hour < 5)
            return "Speicher-Netzladung aus"
        if action == "warmwater_on":
            if 0 <= now_local().hour < 5:
                start_warmwater_session(track_night=True)
            else:
                warmwater_set(True, track_night=False)
            return "Warmwasser an"
        if action == "warmwater_off":
            if 0 <= now_local().hour < 5:
                stop_warmwater_session(track_night=True)
            else:
                warmwater_set(False, track_night=False)
            return "Warmwasser aus"
        raise ValueError("Unbekannte Aktion")


def main() -> None:
    LOG.info("Energieplaner %s startet auf 0.0.0.0:%s", VERSION, PORT)
    # Vor dem Öffnen des HTTP-Ports einmal berechnen. Dadurch ist der erste
    # Browseraufruf bereits ein reiner Cache-Lesezugriff.
    _refresh_dashboard_cache()
    scheduler = threading.Thread(target=scheduler_loop, name="scheduler", daemon=True)
    scheduler.start()
    pv_control = threading.Thread(target=pv_control_loop, name="pv-control", daemon=True)
    pv_control.start()
    watchdog = threading.Thread(target=wallbox_watchdog_loop, name="wallbox-watchdog", daemon=True)
    watchdog.start()
    dash_cache = threading.Thread(target=dashboard_cache_loop, name="dashboard-cache", daemon=True)
    dash_cache.start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
