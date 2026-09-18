from __future__ import annotations

import copy
import json
import math
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request

APP_TITLE = "BARF-Portionsrechner"
APP_VERSION = "0.1.11"
PORT = int(os.environ.get("PORT", "8132"))

app = Flask(__name__, template_folder="templates", static_folder="static")

RAW_RICE_RATIO = 550.0 / 2300.0
RAW_RICE_NOTE = "Rohgewicht für Kalorienberechnung und Einkauf"

DEFAULT_DOGS: dict[str, dict[str, Any]] = {
    "dog_one": {
        "name": "dog_one",
        "subtitle": "Leberschonend · mit rohem weißem Reis · kein Zusatzfett",
        "default_days": 30,
        "items": [
            {"name": "Mageres Rind", "per_day": 35.0, "unit": "g", "group": "Rind"},
            {"name": "Geflügel (ohne Haut)", "per_day": 70.0, "unit": "g", "group": "Geflügel"},
            {"name": "Pansen", "per_day": 30.0, "unit": "g", "group": "Pansen"},
            {"name": "Innereienmix", "per_day": 25.0, "unit": "g", "group": "Innereien"},
            {"name": "Gemüse", "per_day": 30.0, "unit": "g", "group": "Gemüse"},
            {"name": "Obst", "per_day": 10.0, "unit": "g", "group": "Obst"},
            {
                "name": "Roher weißer Reis",
                "per_day": 70.0 * RAW_RICE_RATIO,
                "unit": "g",
                "group": "Reis roh",
                "note": RAW_RICE_NOTE,
            },
            {"name": "Knochenmehl", "per_day": 2.3, "unit": "g", "group": "Knochenmehl"},
            {"name": "Seealgenmehl", "per_day": 0.16, "unit": "g", "group": "Seealgenmehl"},
            {"name": "Grünlippmuschel", "per_day": 0.63, "unit": "g", "group": "Grünlippmuschel"},
            {
                "name": "Omega-3 Kapseln",
                "per_week": 9.0,
                "unit": "Stk.",
                "group": "Omega-3 Kapseln",
                "note": "laut Plan 9 pro Woche",
            },
        ],
    },
    "dog_two": {
        "name": "dog_two",
        "subtitle": "Mit Zusatzfett · Leberwerte unauffällig",
        "default_days": 30,
        "items": [
            {"name": "Rind", "per_day": 42.0, "unit": "g", "group": "Rind"},
            {"name": "Geflügel", "per_day": 20.0, "unit": "g", "group": "Geflügel"},
            {"name": "Zusatzfett", "per_day": 13.0, "unit": "g", "group": "Zusatzfett"},
            {"name": "Pansen", "per_day": 25.0, "unit": "g", "group": "Pansen"},
            {"name": "Innereien", "per_day": 20.0, "unit": "g", "group": "Innereien"},
            {"name": "Gemüse", "per_day": 25.0, "unit": "g", "group": "Gemüse"},
            {"name": "Obst", "per_day": 8.0, "unit": "g", "group": "Obst"},
            {"name": "Knochenmehl", "per_day": 2.0, "unit": "g", "group": "Knochenmehl"},
            {"name": "Seealgenmehl", "per_day": 0.14, "unit": "g", "group": "Seealgenmehl"},
            {"name": "Grünlippmuschel", "per_day": 0.55, "unit": "g", "group": "Grünlippmuschel"},
            {
                "name": "Omega-3 Kapseln",
                "per_week": 5.0,
                "unit": "Stk.",
                "group": "Omega-3 Kapseln",
                "note": "laut Plan 5 pro Woche",
            },
        ],
    },
}

BASE_GROUP_ORDER = [
    ("Hähnchen", "Hähnchen"),
    ("Rind", "Rind"),
    ("Geflügel", "Geflügel"),
    ("Zusatzfett", "Zusatzfett"),
    ("Pansen", "Pansen"),
    ("Innereien", "Innereien"),
    ("Gemüse", "Gemüse"),
    ("Obst", "Obst"),
    ("Reis roh", "Roher weißer Reis"),
    ("Knochenmehl", "Knochenmehl"),
    ("Seealgenmehl", "Seealgenmehl"),
    ("Grünlippmuschel", "Grünlippmuschel"),
    ("Omega-3 Kapseln", "Omega-3 Kapseln"),
]

DATA_DIR = Path(os.environ.get("BARF_DATA_DIR", "/data"))
SHARE_DIR = Path("/share/Barf")
SHARE_CONFIG_PATH = SHARE_DIR / "barf-portionsrechner-config.json"
DATA_CONFIG_PATH = DATA_DIR / "barf-portionsrechner-config.json"
SHARE_VACATION_CONFIG_PATH = SHARE_DIR / "barf-portionsrechner-urlaubsmodus-config.json"
DATA_VACATION_CONFIG_PATH = DATA_DIR / "barf-portionsrechner-urlaubsmodus-config.json"


VACATION_KEEP_GROUPS = {
    "Zusatzfett",
    "Gemüse",
    "Obst",
    "Knochenmehl",
    "Seealgenmehl",
    "Grünlippmuschel",
    "Omega-3 Kapseln",
}
VACATION_CHICKEN_GROUPS = {"Rind", "Geflügel", "Pansen", "Innereien"}


def build_vacation_dogs_config(dogs_cfg: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Create the holiday variant from the currently stored normal plan.

    Vacation mode keeps the current plan as source, but simplifies supermarket shopping:
    beef, rumen and organs are omitted and replaced by chicken. Supplements remain the
    same. Rice is stored and edited only as raw rice because the calorie/shopping
    calculation uses the raw weight.
    """
    vacation = deep_default_dogs()

    for dog_key in ("dog_one", "dog_two"):
        base = dogs_cfg[dog_key]
        chicken_per_day = 0.0
        kept_items: list[dict[str, Any]] = []
        raw_rice_per_day: float | None = None

        for item in base.get("items", []):
            group = str(item.get("group") or item.get("name") or "").strip()
            name = str(item.get("name") or "").strip()
            unit = str(item.get("unit") or "g").strip()

            if group in VACATION_CHICKEN_GROUPS and "per_day" in item and unit == "g":
                chicken_per_day += float(item.get("per_day") or 0.0)
                continue

            if group == "Reis gekocht" and "per_day" in item:
                raw_rice_per_day = float(item.get("per_day") or 0.0) * RAW_RICE_RATIO
                continue

            if group == "Reis roh" and "per_day" in item:
                raw_rice_per_day = float(item.get("per_day") or 0.0)
                continue

            if group in VACATION_KEEP_GROUPS:
                if group == "Omega-3 Kapseln" and "per_week" in item:
                    kept_items.append(copy.deepcopy(item))
                elif "per_day" in item:
                    kept_items.append(copy.deepcopy(item))
                continue

            # Keep only the known current-plan supplements if they were saved with a
            # different group name but a recognizable label.
            lower_name = name.lower()
            if any(token in lower_name for token in ("knochenmehl", "seealgen", "grünlipp", "gruenlipp", "omega")):
                kept_items.append(copy.deepcopy(item))

        items: list[dict[str, Any]] = []
        if chicken_per_day > 0:
            items.append({"name": "Hähnchen", "per_day": chicken_per_day, "unit": "g", "group": "Hähnchen"})
        for item in kept_items:
            items.append(item)
        if raw_rice_per_day and raw_rice_per_day > 0:
            items.append(
                {
                    "name": "Roher weißer Reis",
                    "per_day": raw_rice_per_day,
                    "unit": "g",
                    "group": "Reis roh",
                    "note": RAW_RICE_NOTE,
                    "derived_only": False,
                }
            )

        vacation[dog_key] = {
            "name": base.get("name") or DEFAULT_DOGS[dog_key]["name"],
            "subtitle": (
                "Urlaub · Rind/Pansen/Innereien durch Hähnchen ersetzt"
                + (" · mit Zusatzfett" if dog_key == "dog_two" else " · mit rohem Reis")
            ),
            "default_days": base.get("default_days") or DEFAULT_DOGS[dog_key]["default_days"],
            "items": items,
        }

    return refresh_derived_rice(vacation)

def _candidate_config_paths(mode: str = "normal") -> list[Path]:
    if mode == "urlaub":
        share_path = SHARE_VACATION_CONFIG_PATH
        data_path = DATA_VACATION_CONFIG_PATH
    else:
        share_path = SHARE_CONFIG_PATH
        data_path = DATA_CONFIG_PATH

    paths: list[Path] = []
    if SHARE_DIR.exists():
        paths.append(share_path)
    paths.append(data_path)
    return paths


def _preferred_save_path(mode: str = "normal") -> Path:
    if mode == "urlaub":
        return SHARE_VACATION_CONFIG_PATH if SHARE_DIR.exists() else DATA_VACATION_CONFIG_PATH
    return SHARE_CONFIG_PATH if SHARE_DIR.exists() else DATA_CONFIG_PATH


@app.template_filter("format_amount")
def format_amount(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


@app.template_filter("format_days")
def format_days(value: float) -> str:
    try:
        days = float(value)
    except (TypeError, ValueError):
        days = 0.0
    label = format_amount(days).replace(".", ",")
    return "1 Tag" if abs(days - 1.0) < 1e-9 else f"{label} Tage"


@app.template_filter("capsule_round")
def capsule_round(value: float) -> int:
    return int(math.ceil(value))


@app.template_filter("item_period_value")
def item_period_value(item: dict[str, Any]) -> float:
    return item.get("per_week", item.get("per_day", 0.0))


@app.template_filter("sort_items")
def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item.get("derived_only", False), str(item.get("name", "")).lower()))


def deep_default_dogs() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(DEFAULT_DOGS)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def sanitize_day_count(raw: Any, default: float, minimum: float = 0.5, maximum: float = 365.0) -> float:
    text = str(raw or "").strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return float(default)
    return max(minimum, min(value, maximum))


def sanitize_float(raw: Any, default: float = 0.0, minimum: float = 0.0) -> float:
    text = str(raw or "").strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return default
    return max(minimum, value)


def normalize_item_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None

    unit = str(item.get("unit") or "g").strip() or "g"
    group = str(item.get("group") or name).strip() or name
    note = str(item.get("note") or "").strip()
    derived_only = bool(item.get("derived_only", False))

    if "per_week" in item and item.get("per_week") not in (None, ""):
        amount = sanitize_float(item.get("per_week"))
        return {
            "name": name,
            "per_week": amount,
            "unit": unit,
            "group": group,
            "note": note,
            "derived_only": derived_only,
        }

    amount = sanitize_float(item.get("per_day"))
    return {
        "name": name,
        "per_day": amount,
        "unit": unit,
        "group": group,
        "note": note,
        "derived_only": derived_only,
    }


def refresh_derived_rice(dogs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalize rice rows.

    Older versions stored cooked rice and calculated a read-only raw-rice helper row.
    From v0.1.11 onward only raw rice is kept, because shopping and calories use the
    raw weight. If old saved data contains cooked rice, it is converted once using the
    stored ratio. Raw rice is always editable.
    """
    for dog in dogs.values():
        items = dog.get("items", [])
        if not isinstance(items, list):
            continue

        raw_rice_per_day: float | None = None
        cleaned_items: list[dict[str, Any]] = []

        for item in items:
            group = str(item.get("group") or item.get("name") or "").strip()

            if group == "Reis gekocht" and "per_day" in item:
                if raw_rice_per_day is None:
                    raw_rice_per_day = float(item.get("per_day") or 0.0) * RAW_RICE_RATIO
                continue

            if group == "Reis roh":
                if "per_day" in item:
                    raw_rice_per_day = float(item.get("per_day") or 0.0)
                elif "per_week" in item:
                    raw_rice_per_day = float(item.get("per_week") or 0.0) / 7.0
                continue

            cleaned_items.append(item)

        if raw_rice_per_day and raw_rice_per_day > 0:
            cleaned_items.append(
                {
                    "name": "Roher weißer Reis",
                    "per_day": raw_rice_per_day,
                    "unit": "g",
                    "group": "Reis roh",
                    "note": RAW_RICE_NOTE,
                    "derived_only": False,
                }
            )

        dog["items"] = cleaned_items
    return dogs

def _normalize_loaded_dogs(raw: Any) -> dict[str, dict[str, Any]]:
    dogs = deep_default_dogs()
    if not isinstance(raw, dict):
        return refresh_derived_rice(dogs)

    for dog_key in ("dog_one", "dog_two"):
        loaded = raw.get(dog_key)
        if not isinstance(loaded, dict):
            continue
        dogs[dog_key]["name"] = str(loaded.get("name") or dogs[dog_key]["name"])
        dogs[dog_key]["subtitle"] = str(loaded.get("subtitle") or dogs[dog_key]["subtitle"])
        dogs[dog_key]["default_days"] = sanitize_day_count(loaded.get("default_days"), dogs[dog_key]["default_days"], minimum=0.5, maximum=365.0)
        items = loaded.get("items")
        if isinstance(items, list):
            normalized_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = normalize_item_dict(item)
                if normalized:
                    normalized_items.append(normalized)
            if normalized_items:
                dogs[dog_key]["items"] = normalized_items
    return refresh_derived_rice(dogs)


def load_dogs_config() -> tuple[dict[str, dict[str, Any]], str]:
    for path in _candidate_config_paths("normal"):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return _normalize_loaded_dogs(raw), ""
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            continue
    return refresh_derived_rice(deep_default_dogs()), ""


def load_vacation_dogs_config(normal_dogs: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], bool]:
    for path in _candidate_config_paths("urlaub"):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return _normalize_loaded_dogs(raw), True
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            continue
    return refresh_derived_rice(build_vacation_dogs_config(normal_dogs)), False


def save_dogs_config(dogs: dict[str, dict[str, Any]], mode: str = "normal") -> tuple[bool, str]:
    save_errors: list[str] = []
    fallback_path = DATA_VACATION_CONFIG_PATH if mode == "urlaub" else DATA_CONFIG_PATH
    for path in (_preferred_save_path(mode), fallback_path):
        try:
            ensure_parent_dir(path)
            with path.open("w", encoding="utf-8") as f:
                json.dump(refresh_derived_rice(dogs), f, ensure_ascii=False, indent=2)
            return True, ""
        except OSError as exc:
            save_errors.append(f"{path}: {exc}")
    return False, "; ".join(save_errors)


def parse_days(key: str, default: float) -> float:
    # Bei POST muss das Formular Vorrang vor alten URL-Parametern haben.
    # Sonst bleibt z. B. im Urlaubsmodus der Link-Wert days_dog_one=30 aktiv
    # und überschreibt die neu eingegebene Tagesanzahl aus dem Formular.
    if request.method == "POST" and key in request.form:
        raw_value = request.form.get(key)
    elif key in request.args:
        raw_value = request.args.get(key)
    else:
        raw_value = request.values.get(key)

    raw = str(raw_value or "").strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return max(0.5, min(value, 365.0))


def parse_dogs_from_form(current: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    dogs = deep_default_dogs()

    for dog_key in ("dog_one", "dog_two"):
        dogs[dog_key]["name"] = str(request.form.get(f"{dog_key}_name") or current[dog_key]["name"]).strip() or current[dog_key]["name"]
        dogs[dog_key]["subtitle"] = str(request.form.get(f"{dog_key}_subtitle") or current[dog_key]["subtitle"]).strip()
        dogs[dog_key]["default_days"] = parse_days(f"default_days_{dog_key}", current[dog_key]["default_days"])

        names = request.form.getlist(f"{dog_key}_item_name[]")
        amounts = request.form.getlist(f"{dog_key}_item_amount[]")
        periods = request.form.getlist(f"{dog_key}_item_period[]")
        units = request.form.getlist(f"{dog_key}_item_unit[]")
        groups = request.form.getlist(f"{dog_key}_item_group[]")
        notes = request.form.getlist(f"{dog_key}_item_note[]")
        derived_flags = request.form.getlist(f"{dog_key}_item_derived[]")

        max_len = max(len(names), len(amounts), len(periods), len(units), len(groups), len(notes), len(derived_flags), 0)
        items: list[dict[str, Any]] = []

        for index in range(max_len):
            name = names[index].strip() if index < len(names) else ""
            if not name:
                continue
            amount = amounts[index] if index < len(amounts) else "0"
            period = periods[index] if index < len(periods) else "day"
            unit = units[index].strip() if index < len(units) else "g"
            group = groups[index].strip() if index < len(groups) else ""
            note = notes[index].strip() if index < len(notes) else ""
            derived_only = (derived_flags[index].strip() if index < len(derived_flags) else "0") == "1"

            base: dict[str, Any] = {
                "name": name,
                "unit": unit or "g",
                "group": group or name,
                "note": note,
                "derived_only": derived_only,
            }
            if period == "week":
                base["per_week"] = sanitize_float(amount)
            else:
                base["per_day"] = sanitize_float(amount)
            normalized = normalize_item_dict(base)
            if normalized:
                items.append(normalized)

        if items:
            dogs[dog_key]["items"] = items
        else:
            dogs[dog_key]["items"] = copy.deepcopy(current[dog_key]["items"])

    return refresh_derived_rice(dogs)




def add_blank_item(dogs: dict[str, dict[str, Any]], dog_key: str) -> None:
    if dog_key not in dogs:
        return
    dogs[dog_key]["items"].append(
        {
            "name": "",
            "per_day": 0.0,
            "unit": "g",
            "group": "",
            "note": "",
            "derived_only": False,
        }
    )


def remove_item_at(dogs: dict[str, dict[str, Any]], dog_key: str, index: int) -> None:
    if dog_key not in dogs:
        return
    items = dogs[dog_key].get("items", [])
    if not isinstance(items, list):
        return
    if 0 <= index < len(items):
        item = items[index]
        if not item.get("derived_only", False):
            del items[index]


def build_group_labels(dogs: dict[str, dict[str, Any]]) -> OrderedDict[str, str]:
    labels = OrderedDict(BASE_GROUP_ORDER)
    for dog in dogs.values():
        for item in dog["items"]:
            group = str(item.get("group") or item["name"])
            labels.setdefault(group, group)
    return labels


def is_omega_capsule_item(item_or_row: dict[str, Any]) -> bool:
    name = str(item_or_row.get("name") or "").lower()
    group = str(item_or_row.get("group") or "").lower()
    unit = str(item_or_row.get("unit") or "").strip()
    return unit == "Stk." or "omega" in name or "omega" in group or "kapsel" in name or "kapsel" in group


def calculate_dog(dog_key: str, days: float, dogs_cfg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dog = dogs_cfg[dog_key]
    rows: list[dict[str, Any]] = []
    totals = {"grams": 0.0, "capsules": 0.0}

    for item in dog["items"]:
        if "per_day" in item:
            total = item["per_day"] * days
            rows.append(
                {
                    "name": item["name"],
                    "per_amount": item["per_day"],
                    "per_label": "pro Tag",
                    "total": total,
                    "unit": item["unit"],
                    "group": item["group"],
                    "note": item.get("note", ""),
                    "derived_only": item.get("derived_only", False),
                }
            )
        else:
            total = item["per_week"] * days / 7.0
            rows.append(
                {
                    "name": item["name"],
                    "per_amount": item["per_week"],
                    "per_label": "pro Woche",
                    "total": total,
                    "unit": item["unit"],
                    "group": item["group"],
                    "note": item.get("note", ""),
                    "derived_only": item.get("derived_only", False),
                }
            )

        if item.get("derived_only", False):
            continue
        if is_omega_capsule_item(item):
            totals["capsules"] += total
            continue
        if str(item.get("unit") or "").strip() == "g":
            totals["grams"] += total

    daily_grams = totals["grams"] / days if days > 0 else 0.0
    return {
        "key": dog_key,
        "name": dog["name"],
        "subtitle": dog["subtitle"],
        "days": days,
        "rows": rows,
        "totals": totals,
        "daily_grams": daily_grams,
        "items": dog["items"],
        "default_days": dog["default_days"],
    }


def calculate_combined(dogs: list[dict[str, Any]], group_labels: OrderedDict[str, str]) -> list[dict[str, Any]]:
    combined: OrderedDict[str, dict[str, Any]] = OrderedDict(
        (
            key,
            {
                "label": label,
                "unit": "g" if key != "Omega-3 Kapseln" else "Stk.",
                "dog_one": 0.0,
                "dog_two": 0.0,
            },
        )
        for key, label in group_labels.items()
    )
    for dog in dogs:
        for row in dog["rows"]:
            target = combined.setdefault(
                row["group"],
                {
                    "label": row["group"],
                    "unit": row["unit"],
                    "dog_one": 0.0,
                    "dog_two": 0.0,
                },
            )
            target[dog["key"]] += row["total"]
            target["unit"] = row["unit"]
    result = []
    for key, entry in combined.items():
        if entry["dog_one"] == 0 and entry["dog_two"] == 0:
            continue
        result.append(
            {
                "label": entry["label"],
                "unit": entry["unit"],
                "dog_one": entry["dog_one"],
                "dog_two": entry["dog_two"],
                "total": entry["dog_one"] + entry["dog_two"],
                "is_capsules": entry["unit"] == "Stk.",
                "derived_only": False,
                "note": RAW_RICE_NOTE if key == "Reis roh" else "",
            }
        )
    return result


def render_index(source_dogs_cfg: dict[str, dict[str, Any]], message: str = "", edit_open: bool = False, mode: str = "normal", vacation_customized: bool = False) -> str:
    days_dog_one = parse_days("days_dog_one", source_dogs_cfg["dog_one"]["default_days"])
    days_dog_two = parse_days("days_dog_two", source_dogs_cfg["dog_two"]["default_days"])

    dog_one = calculate_dog("dog_one", days_dog_one, source_dogs_cfg)
    dog_two = calculate_dog("dog_two", days_dog_two, source_dogs_cfg)
    group_labels = build_group_labels(source_dogs_cfg)
    combined = calculate_combined([dog_one, dog_two], group_labels)

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        title=APP_TITLE,
        dogs=[dog_one, dog_two],
        combined=combined,
        message=message,
        edit_open=edit_open,
        mode=mode,
        is_vacation=(mode == "urlaub"),
        vacation_customized=vacation_customized,
    )


@app.route("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION, "feature": "rohreis_editierbar"}


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    message = ""
    edit_open = request.args.get("edit") == "1"
    mode = "urlaub" if request.values.get("mode") == "urlaub" else "normal"

    normal_dogs_cfg, load_message = load_dogs_config()
    vacation_customized = False
    if mode == "urlaub":
        active_dogs_cfg, vacation_customized = load_vacation_dogs_config(normal_dogs_cfg)
    else:
        active_dogs_cfg = normal_dogs_cfg

    if load_message:
        message = load_message

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if action == "save_config":
                active_dogs_cfg = parse_dogs_from_form(active_dogs_cfg)
                ok, save_error = save_dogs_config(active_dogs_cfg, mode=mode)
                if ok:
                    message = "Änderungen gespeichert." if mode == "normal" else "Urlaubsmodus-Änderungen gespeichert."
                    vacation_customized = vacation_customized or mode == "urlaub"
                else:
                    message = "Änderungen konnten nicht dauerhaft gespeichert werden. Bitte prüfe den Zugriff auf /share/Barf."
                edit_open = True
            elif action.startswith("add_item:"):
                active_dogs_cfg = parse_dogs_from_form(active_dogs_cfg)
                dog_key = action.split(":", 1)[1]
                add_blank_item(active_dogs_cfg, dog_key)
                edit_open = True
                message = "Neue Zeile eingefügt."
            elif action.startswith("remove_item:"):
                active_dogs_cfg = parse_dogs_from_form(active_dogs_cfg)
                _, dog_key, raw_index = action.split(":", 2)
                remove_item_at(active_dogs_cfg, dog_key, int(raw_index))
                edit_open = True
                message = "Zeile entfernt. Noch nicht gespeichert."
        except Exception:
            message = "Beim Verarbeiten der Bearbeitung ist ein Fehler aufgetreten. Die Standardwerte wurden geladen, damit die App erreichbar bleibt."
            active_dogs_cfg = refresh_derived_rice(build_vacation_dogs_config(normal_dogs_cfg)) if mode == "urlaub" else refresh_derived_rice(deep_default_dogs())
            edit_open = True

    try:
        return render_index(active_dogs_cfg, message=message, edit_open=edit_open, mode=mode, vacation_customized=vacation_customized)
    except Exception:
        fallback_message = "Die gespeicherten Daten konnten nicht verarbeitet werden. Die App zeigt deshalb die Standardwerte an."
        fallback_dogs = refresh_derived_rice(build_vacation_dogs_config(deep_default_dogs())) if mode == "urlaub" else refresh_derived_rice(deep_default_dogs())
        return render_index(fallback_dogs, message=fallback_message, edit_open=False, mode=mode, vacation_customized=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
