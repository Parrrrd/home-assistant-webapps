import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
try:
    from PIL import Image
except Exception:
    Image = None
from flask import Flask, Response, jsonify, redirect, request, send_file

APP_NAME = "MOVA Protokoll"
DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data")) / "mova_protokoll"
IMAGES_DIR = DATA_ROOT / "images"
LOG_PATH = DATA_ROOT / "log.json"
SETTINGS_PATH = DATA_ROOT / "settings.json"
OPTIONS_PATH = Path("/data/options.json")

DEFAULTS = {
    "camera_entity": "camera.v50_ultra_complete_map",
    "mower_entity": "sensor.v50_ultra_complete_task_status",
    "duration_entity": "",
    "mode_entity": "sensor.v50_ultra_complete_task_status",
    "retain_count": 20,
    "poll_seconds": 5,
    "end_debounce_seconds": 10,
    "min_auto_duration_seconds": 120,
    "active_states": "room_cleaning,cleaning,sweeping,mopping,segment_cleaning,zone_cleaning",
    "port": 8144,
    "min_auto_path_points": 0,
    "min_auto_green_ratio": 0,
}



AREA_LABEL_OPTIONS = [
    "Saugen",
    "Wischen",
]


def normalize_area_label(label: Optional[str]) -> Optional[str]:
    label = (label or "").strip()
    if not label:
        return None
    # Nur die festen Werte zulassen, damit das Protokoll sauber und lernbar bleibt.
    return label if label in AREA_LABEL_OPTIONS else None


def green_area_signature(image_bytes: Optional[bytes]) -> Optional[Dict[str, Any]]:
    """Create a compact signature from the green highlighted mowing area.

    The MOVA base map is mostly stable; the changing green overlay marks
    what was mowed. We threshold green pixels and compress them into a small grid.
    This keeps learning local and does not require external AI services.
    """
    if not image_bytes or Image is None:
        return None
    try:
        import io
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        # Normalize size so signatures are comparable even if HA serves a slightly different image size.
        img = img.resize((48, 48))
        pix = list(img.getdata())
        bits = []
        count = 0
        for r, g, b in pix:
            # Robust green overlay heuristic: green must dominate red/blue clearly.
            is_green = g >= 70 and g > (r * 1.18 + 8) and g > (b * 1.18 + 8)
            bits.append(1 if is_green else 0)
            if is_green:
                count += 1
        ratio = count / max(1, len(bits))
        return {"w": 48, "h": 48, "bits": bits, "green_ratio": round(ratio, 5)}
    except Exception:
        return None


def signature_similarity(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> float:
    """Ähnlichkeit der grünen Mähfläche.

    v0.1.6: Die reine Jaccard-Ähnlichkeit war zu streng. Wenn derselbe Bereich
    an zwei Tagen minimal anders übermalt ist, sinkt Jaccard schnell, obwohl die
    Fläche für den Nutzer identisch ist. Deshalb wird zusätzlich die Abdeckung
    in beide Richtungen bewertet und der beste Wert genutzt.
    """
    if not a or not b:
        return 0.0
    ba = a.get("bits") or []
    bb = b.get("bits") or []
    if not ba or not bb or len(ba) != len(bb):
        return 0.0

    inter = union = count_a = count_b = 0
    for x, y in zip(ba, bb):
        if x:
            count_a += 1
        if y:
            count_b += 1
        if x or y:
            union += 1
            if x and y:
                inter += 1

    if union == 0:
        return 0.0

    jaccard = inter / union
    cover_a = inter / count_a if count_a else 0.0
    cover_b = inter / count_b if count_b else 0.0

    # Mischwert: sehr ähnliche Teilflächen sollen trotzdem erkannt werden.
    return max(jaccard, min(cover_a, cover_b), (jaccard * 0.55 + min(cover_a, cover_b) * 0.45))


def infer_area_label_from_history(signature: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[float]]:
    if not signature:
        return None, None
    best_label = None
    best_score = 0.0
    for item in history():
        label = normalize_area_label(item.get("area_label"))
        sig = item.get("area_signature")
        if not label or not sig or item.get("area_source") not in ("manual", "manual-training", "auto-image"):
            continue
        score = signature_similarity(signature, sig)
        if score > best_score:
            best_score = score
            best_label = label

    # v0.1.6: etwas weniger streng, damit identische Bereiche am Folgetag
    # automatisch wieder erkannt werden.
    if best_label and best_score >= 0.72:
        return best_label, round(best_score, 4)
    return None, round(best_score, 4) if best_score else None

DATA_ROOT.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
lock = threading.RLock()
monitor_thread: Optional[threading.Thread] = None
stop_event = threading.Event()

runtime_status: Dict[str, Any] = {
    "started_at": None,
    "last_poll_at": None,
    "last_error": None,
    "last_snapshot_error": None,
    "mower_state": None,
    "duration_seconds": None,
    "mode": None,
    "active_session": None,
    "last_saved_at": None,
    "last_saved_id": None,
    "last_seen_duration": None,
    "duration_last_changed": None,
    "duration_last_updated": None,
    "last_auto_reason": None,
    "last_skipped_at": None,
    "last_skipped_reason": None,
}


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def parse_ha_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Home Assistant returns RFC3339 with +00:00. fromisoformat handles it.
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
    except Exception:
        return None


def safe_id(dt: Optional[datetime] = None) -> str:
    dt = dt or now_local()
    return dt.strftime("%Y%m%d-%H%M%S")


def load_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return fallback


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_options() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    if OPTIONS_PATH.exists():
        try:
            opts = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(opts, dict):
                cfg.update({k: v for k, v in opts.items() if v is not None})
        except Exception:
            pass
    user = load_json(SETTINGS_PATH, {})
    if isinstance(user, dict):
        cfg.update({k: v for k, v in user.items() if v is not None})
    for key in ("retain_count", "poll_seconds", "end_debounce_seconds", "min_auto_duration_seconds", "port"):
        try:
            cfg[key] = int(cfg.get(key, DEFAULTS[key]))
        except Exception:
            cfg[key] = DEFAULTS[key]
    return cfg


def save_settings(cfg: Dict[str, Any]) -> None:
    allowed = set(DEFAULTS.keys())
    filtered = {k: cfg[k] for k in allowed if k in cfg}
    save_json(SETTINGS_PATH, filtered)


def active_states(cfg: Dict[str, Any]) -> List[str]:
    raw = str(cfg.get("active_states", ""))
    states = [x.strip().lower() for x in re.split(r"[,;\n]+", raw) if x.strip()]
    return states or ["mowing"]


def history() -> List[Dict[str, Any]]:
    data = load_json(LOG_PATH, [])
    return data if isinstance(data, list) else []


def write_history(items: List[Dict[str, Any]]) -> None:
    save_json(LOG_PATH, items)


def duration_text(seconds: Optional[float]) -> str:
    try:
        seconds = int(round(float(seconds or 0)))
    except Exception:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d} h"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


def fmt_dt(value: Optional[str]) -> str:
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return value


def fmt_date(value: Optional[str]) -> str:
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return value


def mode_label(mode: Optional[str]) -> str:
    mapping = {
        "room_cleaning": "Saugen",
        "cleaning": "Saugen",
        "sweeping": "Saugen",
        "mopping": "Wischen",
        "segment_cleaning": "Saugen",
        "zone_cleaning": "Saugen",
        "completed": "Erledigt",
        "returning": "Rückkehr",
        "returning_to_dock": "Rückkehr",
        "docked": "Angedockt",
        "paused": "Pausiert",
    }
    if not mode:
        return "–"
    return mapping.get(str(mode), str(mode))


def state_label(state: Optional[str]) -> str:
    mapping = {
        "room_cleaning": "Raumreinigung",
        "cleaning": "Reinigt",
        "sweeping": "Saugt",
        "mopping": "Wischt",
        "segment_cleaning": "Segmentreinigung",
        "zone_cleaning": "Zonenreinigung",
        "completed": "Erledigt",
        "returning": "Rückkehr",
        "returning_to_dock": "Rückkehr zur Ladestation",
        "docked": "Angedockt",
        "paused": "Pausiert",
        "error": "Fehler",
        "idle": "Bereit",
        "unknown": "Unbekannt",
        "unavailable": "Nicht verfügbar",
    }
    if not state:
        return "–"
    return mapping.get(str(state), str(state))


def api_base() -> str:
    return os.environ.get("HASS_API", "http://supervisor/core/api").rstrip("/")


def core_base() -> str:
    # Same host, without trailing /api, used for entity_picture paths.
    base = api_base()
    if base.endswith("/api"):
        return base[:-4]
    return base.replace("/api", "")


def auth_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def ha_get_state(entity_id: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    if not entity_id:
        return None
    url = f"{api_base()}/states/{entity_id}"
    r = requests.get(url, headers=auth_headers(), timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def parse_duration(value: Any, unit: Optional[str] = None) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
            if value in ("", "unknown", "unavailable", "none", "None"):
                return None
        num = float(value)
        unit = (unit or "s").lower()
        if unit in ("min", "minute", "minutes"):
            return num * 60
        if unit in ("h", "hr", "hour", "hours"):
            return num * 3600
        return num
    except Exception:
        return None


def collect_states(cfg: Dict[str, Any]) -> Dict[str, Any]:
    mower = ha_get_state(str(cfg.get("mower_entity")))
    duration_entity = str(cfg.get("duration_entity") or "").strip()
    duration = ha_get_state(duration_entity) if duration_entity else None
    mode = ha_get_state(str(cfg.get("mode_entity")))
    camera = ha_get_state(str(cfg.get("camera_entity")))

    duration_seconds = None
    if duration:
        duration_seconds = parse_duration(
            duration.get("state"),
            (duration.get("attributes") or {}).get("unit_of_measurement"),
        )

    return {
        "mower": mower,
        "duration": duration,
        "mode": mode,
        "camera": camera,
        "mower_state": mower.get("state") if mower else None,
        "duration_seconds": duration_seconds,
        "duration_state_raw": duration.get("state") if duration else None,
        "duration_last_changed": duration.get("last_changed") if duration else None,
        "duration_last_updated": duration.get("last_updated") if duration else None,
        "mode_state": mode.get("state") if mode else None,
        "camera_state": camera.get("state") if camera else None,
    }


def camera_snapshot_bytes(cfg: Dict[str, Any], camera_state: Optional[Dict[str, Any]] = None) -> Tuple[bytes, str]:
    camera_entity = str(cfg.get("camera_entity"))
    urls = [f"{api_base()}/camera_proxy/{camera_entity}?time={int(time.time())}"]
    try:
        if not camera_state:
            camera_state = ha_get_state(camera_entity)
        entity_picture = ((camera_state or {}).get("attributes") or {}).get("entity_picture")
        if entity_picture:
            urls.append(f"{core_base()}{entity_picture}")
    except Exception:
        pass

    last_error = None
    for url in urls:
        try:
            r = requests.get(url, headers=auth_headers(), timeout=20)
            if r.ok and r.content:
                ctype = r.headers.get("content-type", "image/jpeg")
                return r.content, ctype
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_error = str(e)
    raise RuntimeError(last_error or "Kamera-Snapshot konnte nicht geladen werden")


def extract_camera_summary(camera_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    attrs = (camera_state or {}).get("attributes") or {}
    wanted = [
        "scene_counts",
        "clean_info_summary",
        "mow_param_summary",
        "path_summary",
        "current_path_summary",
        "history_path_summary",
        "combined_path_summary",
        "map_state",
        "map_name",
        "robot_pose_source",
        "live_pose_valid",
        "display_pose",
        "current_pose",
        "rotation_angle",
    ]
    return {k: attrs.get(k) for k in wanted if k in attrs}


def prune_history(cfg: Dict[str, Any]) -> None:
    retain = max(1, int(cfg.get("retain_count", 10)))
    items = history()
    items = sorted(items, key=lambda x: x.get("end") or x.get("created_at") or "", reverse=True)
    keep = items[:retain]
    drop = items[retain:]
    keep_images = {x.get("image") for x in keep if x.get("image")}
    for item in drop:
        img = item.get("image")
        if img and img not in keep_images:
            path = IMAGES_DIR / Path(img).name
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
    write_history(keep)



def camera_path_point_count(camera_summary: Optional[Dict[str, Any]]) -> Optional[int]:
    summary = camera_summary or {}
    candidates = []

    scene = summary.get("scene_counts") or {}
    for key in ("current_path_points", "path_points", "filtered_non_cleaning_path_points"):
        try:
            candidates.append(int(scene.get(key)))
        except Exception:
            pass

    for block_name in ("combined_path_summary", "current_path_summary", "path_summary"):
        block = summary.get(block_name) or {}
        try:
            candidates.append(int(block.get("point_count")))
        except Exception:
            pass

    return max(candidates) if candidates else None


def mowing_evidence_ok(
    cfg: Dict[str, Any],
    duration_seconds: Optional[float],
    camera_summary: Optional[Dict[str, Any]],
    area_signature: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Verhindert automatische Protokolle ohne echten Vorgang.

    v0.1.5: nicht mehr beide Kriterien hart verlangen.
    Bei MOVA kann die Karte nach dem Docken schon teilweise zurückgesetzt sein.
    Deshalb reicht jetzt: Mindestdauer + entweder ausreichend Pfadpunkte ODER
    sichtbare grüne Markierung. Nur wenn beides fehlt bzw. beides klar zu klein ist,
    wird nicht gespeichert.
    """
    try:
        min_duration = int(cfg.get("min_auto_duration_seconds", 60))
    except Exception:
        min_duration = 60
    try:
        duration = float(duration_seconds or 0)
    except Exception:
        duration = 0
    if duration < min_duration:
        return False, f"Dauer zu kurz ({duration_text(duration)} < {duration_text(min_duration)})"

    try:
        min_path_points = int(cfg.get("min_auto_path_points", 10))
    except Exception:
        min_path_points = 10
    try:
        min_green_ratio = float(cfg.get("min_auto_green_ratio", 0.002))
    except Exception:
        min_green_ratio = 0.002

    path_points = camera_path_point_count(camera_summary)
    green_ratio = None
    try:
        green_ratio = float((area_signature or {}).get("green_ratio"))
    except Exception:
        green_ratio = None

    has_path = path_points is not None and path_points >= min_path_points
    has_green = green_ratio is not None and green_ratio >= min_green_ratio

    if has_path or has_green:
        details = []
        if path_points is not None:
            details.append(f"Pfadpunkte {path_points}")
        if green_ratio is not None:
            details.append(f"Grünanteil {green_ratio:.4f}")
        return True, "Reinigungsspuren erkannt: " + ", ".join(details)

    if path_points is None and green_ratio is None:
        return False, "Keine auswertbaren Reinigungsspuren in Kamera/Map gefunden"

    reasons = []
    if path_points is not None:
        reasons.append(f"Pfadpunkte {path_points} < {min_path_points}")
    if green_ratio is not None:
        reasons.append(f"Grünanteil {green_ratio:.4f} < {min_green_ratio:.4f}")
    return False, "Zu wenig Reinigungsspuren: " + ", ".join(reasons)


def save_session_entry(
    cfg: Dict[str, Any],
    start: Optional[datetime],
    end: datetime,
    duration_seconds: Optional[float],
    mode: Optional[str],
    mower_state_start: Optional[str],
    mower_state_end: Optional[str],
    camera_state: Optional[Dict[str, Any]],
    source: str,
    require_mowing_evidence: bool = False,
) -> Dict[str, Any]:
    if duration_seconds is None:
        duration_seconds = 0
    if start and float(duration_seconds or 0) <= 0:
        duration_seconds = max(0, (end - start).total_seconds())
    if not start:
        start = end - timedelta(seconds=float(duration_seconds or 0))
    entry_id = safe_id(end)
    filename = f"{entry_id}.jpg"
    image_rel = f"images/{filename}"
    image_path = IMAGES_DIR / filename

    snapshot_error = None
    snapshot_content = None
    try:
        content, _ctype = camera_snapshot_bytes(cfg, camera_state=camera_state)
        snapshot_content = content
        image_path.write_bytes(content)
    except Exception as e:
        snapshot_error = str(e)

    camera_summary = extract_camera_summary(camera_state)
    area_signature = green_area_signature(snapshot_content)

    if require_mowing_evidence:
        ok, reason = mowing_evidence_ok(cfg, duration_seconds, camera_summary, area_signature)
        if not ok:
            try:
                image_path.unlink(missing_ok=True)
            except Exception:
                pass
            with lock:
                runtime_status["last_skipped_at"] = iso(now_local())
                runtime_status["last_skipped_reason"] = reason
                runtime_status["last_auto_reason"] = f"skip: {reason}"
            return {
                "skipped": True,
                "reason": reason,
                "duration_seconds": int(round(float(duration_seconds or 0))),
                "duration_text": duration_text(duration_seconds),
                "source": source,
            }

    inferred_label, inferred_score = infer_area_label_from_history(area_signature)

    entry = {
        "id": entry_id,
        "created_at": iso(now_local()),
        "source": source,
        "start": iso(start),
        "end": iso(end),
        "duration_seconds": int(round(float(duration_seconds or 0))),
        "duration_text": duration_text(duration_seconds),
        "mode": mode,
        "mode_label": mode_label(mode),
        "area_label": inferred_label or ("Wischen" if str(mode).lower() in ("mopping", "wischen") else "Saugen"),
        "area_source": "auto-image" if inferred_label else "auto-state",
        "area_confidence": inferred_score,
        "area_signature": area_signature,
        "mower_state_start": mower_state_start,
        "mower_state_end": mower_state_end,
        "mower_state_end_label": state_label(mower_state_end),
        "camera_entity": cfg.get("camera_entity"),
        "image": image_rel if image_path.exists() else None,
        "snapshot_error": snapshot_error,
        "camera_summary": camera_summary,
    }

    with lock:
        items = history()
        # Avoid exact duplicates if the monitor saves twice in the same final state.
        if items:
            newest = items[0]
            if newest.get("duration_seconds") == entry["duration_seconds"] and newest.get("end") == entry["end"]:
                return newest
        items.insert(0, entry)
        write_history(items)
        prune_history(cfg)
        runtime_status["last_saved_at"] = entry["created_at"]
        runtime_status["last_saved_id"] = entry["id"]
        runtime_status["last_snapshot_error"] = snapshot_error
    return entry


class MowerMonitor:
    def __init__(self) -> None:
        self.current_session: Optional[Dict[str, Any]] = None
        self.last_duration: Optional[float] = None
        self.last_state: Optional[str] = None
        self.last_saved_duration: Optional[int] = None
        self.last_saved_time: Optional[datetime] = None
        self.last_duration_token: Optional[str] = None

    def poll_once(self) -> None:
        cfg = load_options()
        states = collect_states(cfg)
        now = now_local()
        mower_state = states.get("mower_state")
        duration_seconds = states.get("duration_seconds")
        mode = states.get("mode_state")
        camera_state = states.get("camera")
        duration_token = states.get("duration_last_changed") or states.get("duration_last_updated")
        duration_changed = (duration_seconds is not None and self.last_duration is not None and abs(duration_seconds - self.last_duration) > 5)
        duration_token_changed = bool(duration_token and self.last_duration_token and duration_token != self.last_duration_token)
        min_auto_duration = max(1, int(cfg.get("min_auto_duration_seconds", 60)))
        actives = active_states(cfg)
        is_active = (str(mower_state).lower() in actives) if mower_state is not None else False
        duration_increasing = False
        if duration_seconds is not None and self.last_duration is not None:
            duration_increasing = duration_seconds > (self.last_duration + 5)

        with lock:
            runtime_status.update({
                "last_poll_at": iso(now),
                "last_error": None,
                "mower_state": mower_state,
                "duration_seconds": duration_seconds,
                "duration_text": duration_text(duration_seconds),
                "duration_last_changed": states.get("duration_last_changed"),
                "duration_last_updated": states.get("duration_last_updated"),
                "duration_changed_since_last_poll": duration_changed,
                "duration_token_changed_since_last_poll": duration_token_changed,
                "mode": mode,
                "mode_label": mode_label(mode),
                "active_session": self.current_session,
                "last_seen_duration": self.last_duration,
            })

        # Start session when mower reports active, or when duration clearly increases.
        if self.current_session is None:
            recent_duplicate = False
            if self.last_saved_time and duration_seconds is not None and self.last_saved_duration is not None:
                if int(duration_seconds) == int(self.last_saved_duration) and (now - self.last_saved_time).total_seconds() < 1800:
                    recent_duplicate = True
            if not recent_duplicate and (is_active or duration_increasing):
                estimated_start = now - timedelta(seconds=float(duration_seconds or 0)) if duration_seconds else now
                self.current_session = {
                    "start": iso(estimated_start),
                    "started_at_detected": iso(now),
                    "mower_state_start": mower_state,
                    "mode_start": mode,
                    "last_active": iso(now),
                    "last_duration": duration_seconds or 0,
                    "end_candidate_since": None,
                }
        else:
            # Update running session.
            self.current_session["last_duration"] = duration_seconds if duration_seconds is not None else self.current_session.get("last_duration")
            self.current_session["mode_latest"] = mode
            if is_active or duration_increasing:
                self.current_session["last_active"] = iso(now)
                self.current_session["end_candidate_since"] = None
            else:
                if not self.current_session.get("end_candidate_since"):
                    self.current_session["end_candidate_since"] = iso(now)
                try:
                    candidate = datetime.fromisoformat(self.current_session["end_candidate_since"])
                except Exception:
                    candidate = now
                if (now - candidate).total_seconds() >= int(cfg.get("end_debounce_seconds", 90)):
                    start = datetime.fromisoformat(self.current_session["start"])
                    dur = self.current_session.get("last_duration")
                    if duration_seconds and duration_seconds > (dur or 0):
                        dur = duration_seconds
                    saved = save_session_entry(
                        cfg=cfg,
                        start=start,
                        end=now,
                        duration_seconds=dur,
                        mode=mode or self.current_session.get("mode_latest") or self.current_session.get("mode_start"),
                        mower_state_start=self.current_session.get("mower_state_start"),
                        mower_state_end=mower_state,
                        camera_state=camera_state,
                        source="automatic",
                        require_mowing_evidence=False,
                    )
                    if not saved.get("skipped"):
                        self.last_saved_duration = int(saved.get("duration_seconds") or 0)
                        self.last_saved_time = now
                    self.current_session = None

        # Fallback: Some MOVA/HA versions only update the duration sensor at the end
        # and the lawn_mower state may never be one of the configured active states.
        # In that case no running session is detected. When the duration value changes
        # to a meaningful value while the mower is not active, save one completed entry.
        if self.current_session is None and duration_seconds is not None and duration_seconds >= min_auto_duration:
            fallback_event = (duration_changed or duration_token_changed) and not is_active
            if fallback_event:
                recent_duplicate = False
                if self.last_saved_time and self.last_saved_duration is not None:
                    if int(duration_seconds) == int(self.last_saved_duration) and (now - self.last_saved_time).total_seconds() < 7200:
                        recent_duplicate = True
                if not recent_duplicate:
                    end_dt = parse_ha_datetime(duration_token) or now
                    start_dt = end_dt - timedelta(seconds=float(duration_seconds or 0))
                    saved = save_session_entry(
                        cfg=cfg,
                        start=start_dt,
                        end=end_dt,
                        duration_seconds=duration_seconds,
                        mode=mode,
                        mower_state_start=self.last_state,
                        mower_state_end=mower_state,
                        camera_state=camera_state,
                        source="automatic-duration-fallback",
                        require_mowing_evidence=False,
                    )
                    if not saved.get("skipped"):
                        self.last_saved_duration = int(saved.get("duration_seconds") or 0)
                        self.last_saved_time = now
                    with lock:
                        runtime_status["last_auto_reason"] = "duration-fallback-skipped" if saved.get("skipped") else "duration-fallback"

        self.last_duration = duration_seconds
        self.last_duration_token = duration_token
        self.last_state = mower_state
        with lock:
            runtime_status["active_session"] = self.current_session

    def run(self) -> None:
        runtime_status["started_at"] = iso(now_local())
        while not stop_event.is_set():
            cfg = load_options()
            try:
                self.poll_once()
            except Exception as e:
                with lock:
                    runtime_status["last_error"] = str(e)
                    runtime_status["last_poll_at"] = iso(now_local())
            stop_event.wait(max(5, int(cfg.get("poll_seconds", 15))))


monitor = MowerMonitor()


def html_page(title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#f4f6f8; --card:#ffffff; --text:#182026; --muted:#62717d; --line:#d9e0e6; --accent:#2e7d32; --danger:#b00020; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101418; --card:#192026; --text:#eef3f5; --muted:#a9b4bb; --line:#2d3a43; --accent:#72c279; --danger:#ff7b8a; }} }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; background:var(--bg); color:var(--text); }}
    header {{ position:sticky; top:0; z-index:10; background:rgba(244,246,248,.92); backdrop-filter:blur(12px); border-bottom:1px solid var(--line); padding:12px 14px; }}
    @media (prefers-color-scheme: dark) {{ header {{ background:rgba(16,20,24,.92); }} }}
    h1 {{ margin:0; font-size:20px; }}
    main {{ max-width:980px; margin:0 auto; padding:14px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; box-shadow:0 2px 10px rgba(0,0,0,.04); }}
    .small {{ color:var(--muted); font-size:13px; }}
    .metric {{ font-size:22px; font-weight:700; margin-top:4px; }}
    .toolbar {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 14px; }}
    button, .btn {{ appearance:none; border:1px solid var(--line); background:var(--card); color:var(--text); padding:10px 12px; border-radius:12px; font-weight:650; text-decoration:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:6px; }}
    button.primary, .btn.primary {{ background:var(--accent); color:white; border-color:var(--accent); }}
    button.danger {{ color:var(--danger); }}
    img.map {{ width:100%; border-radius:14px; border:1px solid var(--line); background:#111; display:block; }}
    .entry {{ display:grid; grid-template-columns:110px 1fr; gap:12px; align-items:start; }}
    .thumb {{ width:110px; min-height:80px; object-fit:cover; border-radius:12px; border:1px solid var(--line); background:#111; }}
    .entry-title {{ font-weight:750; margin-bottom:4px; }}
    .label-form {{ display:grid; grid-template-columns:1fr auto; gap:8px; margin-top:10px; }}
    .entry-actions {{ margin-top:8px; display:flex; gap:8px; }}
    .small-button {{ padding:7px 10px; font-size:13px; border-radius:10px; }}
    .pill {{ display:inline-block; padding:3px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); font-size:12px; margin:2px 3px 2px 0; }}
    details {{ margin-top:8px; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:rgba(0,0,0,.06); padding:10px; border-radius:10px; font-size:12px; }}
    .formrow {{ display:grid; grid-template-columns:210px 1fr; gap:10px; align-items:center; margin:8px 0; }}
    input, select {{ width:100%; padding:9px 10px; border-radius:10px; border:1px solid var(--line); background:var(--bg); color:var(--text); }}
    @media (max-width:640px) {{ .entry {{ grid-template-columns:1fr; }} .thumb {{ width:100%; max-height:240px; }} .formrow {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<header><h1>{title}</h1></header>
<main>{body}</main>
{script}
</body>
</html>"""


def render_index() -> str:
    items = history()
    cards = []
    for item in items:
        img = item.get("image")
        img_html = (
            f'<a href="/image/{Path(img).name}" target="_blank"><img class="thumb" src="/image/{Path(img).name}" loading="lazy"></a>'
            if img else '<div class="thumb small" style="display:flex;align-items:center;justify-content:center;">Kein Bild</div>'
        )

        try:
            start_time = datetime.fromisoformat(item.get("start")).strftime("%H:%M") if item.get("start") else "–"
        except Exception:
            start_time = "–"
        try:
            end_time = datetime.fromisoformat(item.get("end")).strftime("%H:%M") if item.get("end") else "–"
        except Exception:
            end_time = "–"

        title = f"{fmt_date(item.get('start'))} · {start_time} – {end_time}"

        snapshot_hint = ""
        if item.get("snapshot_error"):
            snapshot_hint = f'<div class="small" style="color:var(--danger);margin-top:6px;">Snapshot-Fehler: {item.get("snapshot_error")}</div>'

        cards.append(f"""
        <section class="card entry">
          {img_html}
          <div>
            <div class="entry-title">{title}</div>
            <div class="small">Dauer: <b>{item.get('duration_text') or duration_text(item.get('duration_seconds'))}</b></div>
            <div class="entry-actions" style="margin-top:12px;">
              <button class="danger small-button" onclick="deleteEntry('{item.get('id')}')">Karte löschen</button>
            </div>
            {snapshot_hint}
          </div>
        </section>""")

    history_html = "\n".join(cards) if cards else '<section class="card small">Noch kein gespeicherter Vorgang vorhanden.</section>'
    body = f"""
    <h2>Letzte Vorgänge</h2>
    <div id="history">{history_html}</div>
    """
    script = """
<script>
async function deleteEntry(id){
  if(!confirm('Diese Karte wirklich aus dem Protokoll löschen?')) return;
  const r = await fetch('/api/delete/' + encodeURIComponent(id), {method:'POST'});
  const data = await r.json();
  if(!r.ok || !data.deleted) { alert('Karte konnte nicht gelöscht werden.'); return; }
  location.reload();
}
</script>
"""
    return html_page(APP_NAME, body, script)


@app.route("/")
def index() -> str:
    return render_index()


@app.route("/live")
def live() -> str:
    body = """
    <div class="toolbar"><a class="btn" href="/">Zurück</a><button onclick="reloadImage()">Live-Karte aktualisieren</button></div>
    <section class="card"><img class="map" id="liveMap" src="/live.jpg"></section>
    """
    script = """
<script>
function reloadImage(){ document.getElementById('liveMap').src = '/live.jpg?t=' + Date.now(); }
setInterval(reloadImage, 30000);
</script>
"""
    return html_page("MOVA Live-Karte", body, script)


@app.route("/settings", methods=["GET", "POST"])
def settings() -> Any:
    cfg = load_options()
    if request.method == "POST":
        form = request.form
        new_cfg = dict(cfg)
        for key in DEFAULTS:
            if key in form:
                value: Any = form.get(key)
                if key in ("retain_count", "poll_seconds", "end_debounce_seconds", "min_auto_duration_seconds", "min_auto_path_points", "port"):
                    try:
                        value = int(value)
                    except Exception:
                        value = DEFAULTS[key]
                new_cfg[key] = value
        save_settings(new_cfg)
        return redirect("/settings")
    rows = []
    labels = {
        "camera_entity": "Kamera-Entity",
        "mower_entity": "Status-Entity",
        "duration_entity": "Dauer-Sensor optional",
        "mode_entity": "Modus-Sensor optional",
        "retain_count": "Anzahl behalten",
        "poll_seconds": "Abfrage alle Sekunden",
        "end_debounce_seconds": "Ende-Verzögerung Sekunden",
        "min_auto_duration_seconds": "Mindestdauer für Auto-Fallback",
        "min_auto_path_points": "Mindest-Pfadpunkte für automatische Protokolle",
        "min_auto_green_ratio": "Mindest-Grünanteil für automatische Protokolle",
        "active_states": "Aktive Zustände",
        "port": "Port",
    }
    for key in DEFAULTS:
        rows.append(f"""
        <div class="formrow">
          <label for="{key}">{labels.get(key,key)}</label>
          <input id="{key}" name="{key}" value="{cfg.get(key,'')}">
        </div>""")
    body = f"""
    <div class="toolbar"><a class="btn" href="/">Zurück</a></div>
    <form method="post" class="card">
      {''.join(rows)}
      <p class="small">Aktive Zustände sind komma-getrennt. Automatische Protokolle werden nur gespeichert, wenn zusätzlich echte Reinigungsspuren in der Karte erkannt werden.</p>
      <button class="primary" type="submit">Speichern</button>
    </form>
    <section class="card"><h3>Status/Debug</h3><pre id="debug">Lade…</pre></section>
    """
    script = """
<script>
fetch('/api/status').then(r=>r.json()).then(j=>document.getElementById('debug').textContent=JSON.stringify(j,null,2));
</script>
"""
    return html_page("MOVA Einstellungen", body, script)


@app.route("/api/status")
def api_status() -> Response:
    with lock:
        data = dict(runtime_status)
    data["mower_state_label"] = state_label(data.get("mower_state"))
    data["mode_label"] = mode_label(data.get("mode"))
    data["settings"] = load_options()
    data["history_count"] = len(history())
    data["area_label_options"] = AREA_LABEL_OPTIONS
    return jsonify(data)


@app.route("/api/history")
def api_history() -> Response:
    return jsonify(history())


@app.route("/api/capture_now", methods=["POST"])
def api_capture_now() -> Response:
    cfg = load_options()
    try:
        states = collect_states(cfg)
        end = now_local()
        dur = states.get("duration_seconds") or 0
        start = end - timedelta(seconds=float(dur or 0))
        entry = save_session_entry(
            cfg=cfg,
            start=start,
            end=end,
            duration_seconds=dur,
            mode=states.get("mode_state"),
            mower_state_start=states.get("mower_state"),
            mower_state_end=states.get("mower_state"),
            camera_state=states.get("camera"),
            source="manual",
        )
        return jsonify(entry)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/live.jpg")
def live_jpg() -> Any:
    cfg = load_options()
    try:
        camera = ha_get_state(str(cfg.get("camera_entity")))
        content, ctype = camera_snapshot_bytes(cfg, camera_state=camera)
        return Response(content, mimetype=ctype or "image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception as e:
        # Return a small SVG error instead of a broken image.
        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='900' height='500'><rect width='100%' height='100%' fill='#111'/><text x='30' y='60' fill='#fff' font-family='Arial' font-size='26'>MOVA Live-Karte nicht verfügbar</text><text x='30' y='110' fill='#aaa' font-family='Arial' font-size='18'>{str(e)[:180]}</text></svg>"""
        return Response(svg, mimetype="image/svg+xml")


@app.route("/image/<filename>")
def image(filename: str) -> Any:
    name = Path(filename).name
    path = IMAGES_DIR / name
    if not path.exists():
        return "Bild nicht gefunden", 404
    return send_file(path, mimetype="image/jpeg", max_age=0)


@app.route("/api/label/<entry_id>", methods=["POST"])
def api_label(entry_id: str) -> Response:
    raw_label = (request.form.get("area_label") or "").strip()
    label = normalize_area_label(raw_label)
    if raw_label and not label:
        return jsonify({"error": "Unbekannte Zuordnung"}), 400
    items = history()
    changed = False
    for item in items:
        if item.get("id") == entry_id:
            item["area_label"] = label or None
            item["area_source"] = "manual-training" if label else None
            item["area_confidence"] = 1.0 if label else None
            changed = True
            break
    if changed:
        write_history(items)
    return jsonify({"ok": changed, "area_label": label or None})


@app.route("/api/delete/<entry_id>", methods=["POST"])
def api_delete(entry_id: str) -> Response:
    items = history()
    keep = []
    deleted = None
    for item in items:
        if item.get("id") == entry_id:
            deleted = item
        else:
            keep.append(item)
    if deleted and deleted.get("image"):
        try:
            (IMAGES_DIR / Path(deleted["image"]).name).unlink(missing_ok=True)
        except Exception:
            pass
    write_history(keep)
    return jsonify({"deleted": bool(deleted)})


def start_monitor() -> None:
    global monitor_thread
    if monitor_thread and monitor_thread.is_alive():
        return
    monitor_thread = threading.Thread(target=monitor.run, name="mova-monitor", daemon=True)
    monitor_thread.start()


if __name__ == "__main__":
    start_monitor()
    cfg = load_options()
    port = int(cfg.get("port", 8144))
    app.run(host="0.0.0.0", port=port, threaded=True)
