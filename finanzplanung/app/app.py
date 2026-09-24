from __future__ import annotations

import copy
import html
import io
import json
import os
import secrets
import tempfile
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PORT = int(os.environ.get("PORT", "8133"))
DATA_DIR = Path(os.environ.get("FINANZ_DATA_DIR", "/data"))
SHARE_DIR = Path("/share/Finanzen")
DATA_PATH = DATA_DIR / "finanzplanung-data.json"
SHARE_PATH = SHARE_DIR / "finanzplanung-data.json"
DEFAULT_PATH = Path(__file__).with_name("default_data.json")
CATEGORY_FILTER_NO_FIXED = "__no_fixkosten__"
CATEGORY_FILTER_NO_FIXED_LABEL = "Ohne Fixkosten"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FINANZ_SESSION_SECRET") or os.environ.get("FINANZ_WEB_PASSWORD") or "finanzplanung-secret-key"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def configured_web_password() -> str:
    value = str(os.environ.get("FINANZ_WEB_PASSWORD") or "").strip()
    if value.lower() in {"null", "none"}:
        return ""
    return value


WEB_PASSWORD = configured_web_password()


def auth_enabled() -> bool:
    return bool(WEB_PASSWORD)


def is_authenticated() -> bool:
    return bool(session.get("finanz_authenticated"))


def is_manually_locked() -> bool:
    return bool(session.get("finanz_locked"))


@app.context_processor
def inject_auth_state() -> dict[str, Any]:
    return {"auth_enabled": auth_enabled(), "is_authenticated": is_authenticated()}


@app.before_request
def require_login() -> Any:
    if not auth_enabled():
        return None
    if is_authenticated():
        return None
    # Standard: Die App öffnet ohne Passwort. Erst nach manuellem Sperren
    # wird wieder die Passwortseite verlangt.
    if not is_manually_locked():
        return None
    if request.endpoint in {"login", "static"}:
        return None
    target = request.full_path if request.query_string else request.path
    if target.endswith("?"):
        target = target[:-1]
    return redirect(url_for("login", next=target))


def read_default_data() -> dict[str, Any]:
    with DEFAULT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def deep_default_data() -> dict[str, Any]:
    return copy.deepcopy(read_default_data())


def backup_dir() -> Path:
    # This directory is part of the add-on backup. /share is deliberately not used
    # here: it is shared between add-ons and must not be the only copy of user data.
    return DATA_DIR / "backups"


def _read_data_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return normalize_data(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Persist a full JSON document without ever exposing a partial file."""
    ensure_parent(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _legacy_share_data() -> dict[str, Any] | None:
    """Read an old share copy once so it can be moved into protected add-on data."""
    if not SHARE_PATH.exists():
        return None
    return _read_data_file(SHARE_PATH)


def _sync_share_copy(payload: dict[str, Any]) -> None:
    """Keep the former share file as a convenience copy, never as the source of truth."""
    if not SHARE_DIR.exists():
        return
    try:
        _write_json_atomic(SHARE_PATH, payload)
    except OSError:
        # A full, protected /data copy was written first. A missing optional mirror
        # must not make a successful user save look like a data-loss failure.
        return


def should_write_backup_snapshot(root: Path, max_age_seconds: int = 3600) -> bool:
    latest: Path | None = None
    latest_mtime = 0.0
    for path in root.glob("finanzplanung-backup-*.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest = path
            latest_mtime = mtime
    if latest is None:
        return True
    return (datetime.now().timestamp() - latest_mtime) >= max_age_seconds


def write_backup_snapshot(payload: dict[str, Any], force: bool = False) -> None:
    try:
        root = backup_dir()
        root.mkdir(parents=True, exist_ok=True)
        if not force and not should_write_backup_snapshot(root):
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = root / f"finanzplanung-backup-{stamp}-{uuid.uuid4().hex[:6]}.json"
        _write_json_atomic(backup_path, payload)
        backups = sorted(root.glob("finanzplanung-backup-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for extra in backups[25:]:
            try:
                extra.unlink()
            except OSError:
                continue
    except OSError:
        return


def list_backups() -> list[dict[str, Any]]:
    root = backup_dir()
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("finanzplanung-backup-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": path.name,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M"),
                "size_kb": max(1, int(round(stat.st_size / 1024))),
            }
        )
    return rows


def safe_backup_path(name: str) -> Path | None:
    filename = Path(str(name or "").strip()).name
    if not filename.startswith("finanzplanung-backup-") or not filename.endswith(".json"):
        return None
    path = backup_dir() / filename
    if not path.exists() or not path.is_file():
        return None
    return path


def canonical_trash_item(item: dict[str, Any]) -> dict[str, Any]:
    deleted_at = str(item.get("deleted_at") or datetime.now().isoformat(timespec="seconds"))[:19]
    return {
        "id": str(item.get("id") or new_id("trash")),
        "kind": str(item.get("kind") or "record").strip() or "record",
        "label": str(item.get("label") or "Eintrag").strip() or "Eintrag",
        "deleted_at": deleted_at,
        "record": copy.deepcopy(item.get("record") or {}),
        "meta": copy.deepcopy(item.get("meta") or {}),
    }


def upsert_record(records: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    record_id = str(payload.get("id") or "")
    if not record_id:
        records.append(payload)
        return
    for index, record in enumerate(records):
        if str(record.get("id") or "") == record_id:
            records[index] = payload
            return
    records.append(payload)


def push_to_trash(data: dict[str, Any], kind: str, label: str, record: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
    trash_item = canonical_trash_item({"kind": kind, "label": label, "record": record, "meta": meta or {}})
    data.setdefault("trash", []).insert(0, trash_item)
    data["trash"] = data["trash"][:100]


def restore_trash_item(data: dict[str, Any], trash_id: str) -> str | None:
    trash_entries = data.get("trash", [])
    for index, item in enumerate(trash_entries):
        if item.get("id") != trash_id:
            continue
        kind = str(item.get("kind") or "")
        record = copy.deepcopy(item.get("record") or {})
        meta = copy.deepcopy(item.get("meta") or {})
        label = str(item.get("label") or "Eintrag")
        if kind in {"transaction", "pot_payment"}:
            restored = canonical_transaction(record)
            upsert_record(data.setdefault("transactions", []), restored)
            deleted_source = str(meta.get("deleted_source") or "").strip()
            if deleted_source:
                data["deleted_recurring_sources"] = [source for source in data.get("deleted_recurring_sources", []) if source != deleted_source]
            data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
        elif kind == "pot":
            restored_pot = canonical_pot(record)
            upsert_record(data.setdefault("pots", []), restored_pot)
            for plan in meta.get("pot_plans", []):
                upsert_record(data.setdefault("pot_plans", []), canonical_pot_plan(plan))
            for tx in meta.get("transactions", []):
                upsert_record(data.setdefault("transactions", []), canonical_transaction(tx))
            data["pots"].sort(key=lambda pot: pot["name"].lower())
            data["pot_plans"].sort(key=lambda plan: (plan["month"], plan["pot_id"], plan["id"]))
            data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
        elif kind == "recurring":
            restored_template = canonical_recurring(record)
            upsert_record(data.setdefault("recurring_templates", []), restored_template)
            for tx in meta.get("transactions", []):
                upsert_record(data.setdefault("transactions", []), canonical_transaction(tx))
            data["recurring_templates"].sort(key=lambda item: (item["day"], item["title"], item["id"]))
            data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
        elif kind == "annual":
            restored_item = canonical_annual(record)
            upsert_record(data.setdefault("annual_items", []), restored_item)
            data["annual_items"].sort(key=lambda item: (item["year"], item["month"], item["title"], item["id"]))
        elif kind == "inventory":
            restored_item = canonical_inventory_item(record)
            upsert_record(data.setdefault("inventory_items", []), restored_item)
            for count in meta.get("inventory_counts", []):
                upsert_record(data.setdefault("inventory_counts", []), canonical_inventory_count(count))
            for purchase in meta.get("inventory_purchases", []):
                upsert_record(data.setdefault("inventory_purchases", []), canonical_inventory_purchase(purchase))
            for tx in meta.get("transactions", []):
                upsert_record(data.setdefault("transactions", []), canonical_transaction(tx))
            data["inventory_items"].sort(key=lambda item: item.get("title", "").lower())
            ensure_inventory_variant_references(data)
            data["inventory_counts"].sort(key=lambda row: (row["month"], row["item_id"], row.get("variant_id", ""), row["id"]))
            data["inventory_purchases"].sort(key=lambda row: (row["month"], row["item_id"], row.get("variant_id", ""), row["id"]))
            data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
        else:
            return None
        del trash_entries[index]
        return label
    return None


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def parse_amount(raw: Any, default: float = 0.0) -> float:
    text = str(raw or "").strip()
    if not text:
        return default
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def parse_month(raw: str | None, fallback: str) -> str:
    text = str(raw or "").strip()
    if len(text) == 7 and text[4] == "-":
        try:
            datetime.strptime(text + "-01", "%Y-%m-%d")
            return text
        except ValueError:
            return fallback
    return fallback


def month_first_day(month_key: str) -> date:
    return datetime.strptime(month_key + "-01", "%Y-%m-%d").date()


def shift_month(month_key: str, delta: int) -> str:
    current = month_first_day(month_key)
    month_index = current.year * 12 + current.month - 1 + delta
    year = month_index // 12
    month = month_index % 12 + 1
    return f"{year:04d}-{month:02d}"


def format_month_label(month_key: str) -> str:
    months = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
    d = month_first_day(month_key)
    return f"{months[d.month - 1]} {d.year}"


def safe_next_target(raw: Any) -> str:
    target = str(raw or "").strip()
    if not target.startswith("/") or target.startswith("//"):
        return url_for("dashboard")
    return target


@app.template_filter("money")
def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    val = abs(value)
    txt = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if txt.endswith(",00"):
        txt = txt[:-3]
    return f"{sign}{txt} €"


@app.template_filter("month_label")
def month_label_filter(value: str) -> str:
    return format_month_label(value)


def month_of(date_text: str) -> str:
    return str(date_text)[:7]


def normalize_search_query(raw: Any) -> str:
    return " ".join(str(raw or "").strip().split())


def query_tokens(raw: Any) -> list[str]:
    return [token for token in normalize_search_query(raw).casefold().split(" ") if token]


def matches_search(query: str, *values: Any) -> bool:
    tokens = query_tokens(query)
    if not tokens:
        return True
    haystack = " ".join(str(value or "") for value in values).casefold()
    return all(token in haystack for token in tokens)


def canonical_transaction(tx: dict[str, Any]) -> dict[str, Any]:
    source = str(tx.get("source") or "manual")
    show_in_month_raw = tx.get("show_in_month")
    show_in_month = bool(show_in_month_raw) if show_in_month_raw is not None else True
    category = str(tx.get("category") or "Ohne Kategorie").strip() or "Ohne Kategorie"
    kind = str(tx.get("kind") or "manual")
    default_payment = default_payment_method_for_transaction({**tx, "source": source, "kind": kind, "category": category})
    return {
        "id": str(tx.get("id") or new_id("tx")),
        "date": str(tx.get("date") or date.today().isoformat())[:10],
        "title": str(tx.get("title") or "").strip() or "Ohne Titel",
        "amount": float(tx.get("amount") or 0.0),
        "category": category,
        "paid": bool(tx.get("paid", False)),
        "payment_method": normalize_payment_method(tx.get("payment_method"), default_payment),
        "pot_id": str(tx.get("pot_id") or "").strip(),
        "notes": str(tx.get("notes") or "").strip(),
        "source": source,
        "kind": kind,
        "show_in_month": show_in_month,
    }


def canonical_recurring(template: dict[str, Any]) -> dict[str, Any]:
    start_month = str(template.get("start_month") or date.today().strftime("%m")).zfill(2)
    if start_month not in {f"{i:02d}" for i in range(1, 13)}:
        start_month = date.today().strftime("%m")
    interval = 3 if int(template.get("interval_months") or 1) == 3 else 1
    valid_from = parse_month(str(template.get("valid_from") or template.get("effective_from") or "").strip(), "1900-01")
    raw_valid_until = str(template.get("valid_until") or template.get("effective_until") or "").strip()
    valid_until = parse_month(raw_valid_until, "") if raw_valid_until else ""
    if valid_until and valid_until < valid_from:
        valid_until = valid_from
    return {
        "id": str(template.get("id") or new_id("rec")),
        "title": str(template.get("title") or "").strip() or "Neue Vorlage",
        "amount": float(template.get("amount") or 0.0),
        "category": str(template.get("category") or "Fixkosten").strip() or "Fixkosten",
        "day": max(1, min(int(template.get("day") or 1), 28)),
        "paid_default": bool(template.get("paid_default", False)),
        "payment_method": normalize_payment_method(template.get("payment_method"), "account"),
        "pot_id": str(template.get("pot_id") or "").strip(),
        "notes": str(template.get("notes") or "").strip(),
        "active": bool(template.get("active", True)),
        "interval_months": interval,
        "start_month": start_month,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }


def canonical_pot(pot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(pot.get("id") or new_id("pot")),
        "name": str(pot.get("name") or "").strip() or "Neuer Topf",
        "color": str(pot.get("color") or "#0f766e"),
    }


def canonical_pot_plan(item: dict[str, Any]) -> dict[str, Any]:
    month = str(item.get("month") or date.today().strftime("%Y-%m"))
    return {
        "id": str(item.get("id") or new_id("plan")),
        "pot_id": str(item.get("pot_id") or "").strip(),
        "month": parse_month(month, date.today().strftime("%Y-%m")),
        "amount": float(item.get("amount") or 0.0),
    }


def canonical_annual(item: dict[str, Any]) -> dict[str, Any]:
    year = int(item.get("year") or date.today().year)
    month = str(item.get("month") or "01").zfill(2)
    if month not in {f"{i:02d}" for i in range(1, 13)}:
        month = "01"
    return {
        "id": str(item.get("id") or new_id("annual")),
        "year": year,
        "month": month,
        "title": str(item.get("title") or "").strip() or "Neuer Planungsposten",
        "amount": float(item.get("amount") or 0.0),
        "group": str(item.get("group") or "Planung").strip() or "Planung",
        "notes": str(item.get("notes") or "").strip(),
        "paid": bool(item.get("paid", False)),
        "is_cash": bool(item.get("is_cash", False)),
    }





def parse_optional_amount(raw: Any) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return max(0.0, parse_amount(text))


def canonical_inventory_variant(item: dict[str, Any], fallback_name: str = "Standard") -> dict[str, Any]:
    quantity = max(0.0, float(item.get("quantity") or item.get("initial_quantity") or 0.0))
    total_price = max(0.0, float(item.get("total_price") or item.get("price") or 0.0))
    empty_weight = parse_optional_amount(item.get("empty_weight"))
    return {
        "id": str(item.get("id") or new_id("stockvar")),
        "name": str(item.get("name") or item.get("title") or item.get("variant") or fallback_name or "Standard").strip() or "Standard",
        "quantity": quantity,
        "unit": str(item.get("unit") or "Stück").strip() or "Stück",
        "total_price": total_price,
        "empty_weight": empty_weight,
        "notes": str(item.get("notes") or "").strip(),
    }


def canonical_inventory_item(item: dict[str, Any]) -> dict[str, Any]:
    raw_variants = item.get("variants")
    variants: list[dict[str, Any]] = []
    if isinstance(raw_variants, list):
        for index, variant in enumerate(raw_variants, start=1):
            if not isinstance(variant, dict):
                continue
            variants.append(canonical_inventory_variant(variant, f"Variante {index}"))
    if not variants:
        variants.append(
            canonical_inventory_variant(
                {
                    "id": item.get("variant_id") or item.get("default_variant_id") or new_id("stockvar"),
                    "name": item.get("variant_name") or "Standard",
                    "quantity": item.get("quantity") or item.get("initial_quantity") or 0.0,
                    "unit": item.get("unit") or "Stück",
                    "total_price": item.get("total_price") or 0.0,
                    "empty_weight": item.get("empty_weight"),
                    "notes": item.get("variant_notes") or "",
                },
                "Standard",
            )
        )

    # IDs innerhalb einer Vorratsposition eindeutig halten.
    seen_ids: set[str] = set()
    for variant in variants:
        if variant["id"] in seen_ids:
            variant["id"] = new_id("stockvar")
        seen_ids.add(variant["id"])

    first_variant = variants[0]
    return {
        "id": str(item.get("id") or new_id("stock")),
        "title": str(item.get("title") or item.get("name") or "").strip() or "Neuer Vorrat",
        "category": str(item.get("category") or "Lebensmittel").strip() or "Lebensmittel",
        "quantity": sum(float(variant.get("quantity") or 0.0) for variant in variants),
        "unit": str(first_variant.get("unit") or "Stück"),
        "total_price": sum(float(variant.get("total_price") or 0.0) for variant in variants),
        "variants": variants,
        "start_month": parse_month(str(item.get("start_month") or "").strip(), date.today().strftime("%Y-%m")),
        "notes": str(item.get("notes") or "").strip(),
        "active": bool(item.get("active", True)),
    }


def inventory_item_variants(item: dict[str, Any]) -> list[dict[str, Any]]:
    variants = item.get("variants")
    if isinstance(variants, list) and variants:
        return [canonical_inventory_variant(variant) for variant in variants if isinstance(variant, dict)] or [canonical_inventory_variant({})]
    return [
        canonical_inventory_variant(
            {
                "id": item.get("variant_id") or item.get("default_variant_id") or new_id("stockvar"),
                "name": item.get("variant_name") or "Standard",
                "quantity": item.get("quantity") or item.get("initial_quantity") or 0.0,
                "unit": item.get("unit") or "Stück",
                "total_price": item.get("total_price") or 0.0,
                "empty_weight": item.get("empty_weight"),
                "notes": item.get("variant_notes") or "",
            }
        )
    ]


def inventory_first_variant_id(item: dict[str, Any]) -> str:
    variants = inventory_item_variants(item)
    return str(variants[0].get("id") or "") if variants else ""


def inventory_variant_by_id(item: dict[str, Any], variant_id: str) -> dict[str, Any] | None:
    wanted = str(variant_id or "").strip()
    return next((variant for variant in inventory_item_variants(item) if str(variant.get("id") or "") == wanted), None)


def canonical_inventory_count(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or new_id("stockcnt")),
        "item_id": str(item.get("item_id") or "").strip(),
        "variant_id": str(item.get("variant_id") or "").strip(),
        "month": parse_month(str(item.get("month") or "").strip(), date.today().strftime("%Y-%m")),
        "end_quantity": max(0.0, float(item.get("end_quantity") or 0.0)),
    }


def canonical_inventory_purchase(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or new_id("stockbuy")),
        "item_id": str(item.get("item_id") or "").strip(),
        "variant_id": str(item.get("variant_id") or "").strip(),
        "month": parse_month(str(item.get("month") or "").strip(), date.today().strftime("%Y-%m")),
        "quantity": max(0.0, float(item.get("quantity") or 0.0)),
        "total_price": max(0.0, float(item.get("total_price") or 0.0)),
        "notes": str(item.get("notes") or "").strip(),
    }


def ensure_inventory_variant_references(data: dict[str, Any]) -> None:
    items_by_id = {str(item.get("id") or ""): item for item in data.get("inventory_items", [])}
    for collection_name in ("inventory_counts", "inventory_purchases"):
        cleaned: list[dict[str, Any]] = []
        for row in data.get(collection_name, []):
            item = items_by_id.get(str(row.get("item_id") or ""))
            if item is None:
                continue
            variant_id = str(row.get("variant_id") or "").strip()
            if not variant_id or inventory_variant_by_id(item, variant_id) is None:
                row["variant_id"] = inventory_first_variant_id(item)
            cleaned.append(row)
        data[collection_name] = cleaned


def inventory_purchases_for_month(data: dict[str, Any], item_id: str, month_key: str, variant_id: str | None = None) -> list[dict[str, Any]]:
    wanted_variant = str(variant_id or "").strip()
    return [
        entry
        for entry in data.get("inventory_purchases", [])
        if entry.get("item_id") == item_id
        and entry.get("month") == month_key
        and (not wanted_variant or entry.get("variant_id") == wanted_variant)
    ]


def inventory_purchase_totals(data: dict[str, Any], item_id: str, month_key: str, variant_id: str | None = None) -> tuple[float, float]:
    purchases = inventory_purchases_for_month(data, item_id, month_key, variant_id)
    return (
        sum(float(entry.get("quantity") or 0.0) for entry in purchases),
        sum(float(entry.get("total_price") or 0.0) for entry in purchases),
    )


def inventory_unit_price(variant: dict[str, Any]) -> float:
    quantity = float(variant.get("quantity") or 0.0)
    if quantity <= 0:
        return 0.0
    return float(variant.get("total_price") or 0.0) / quantity


def inventory_count_for_month(data: dict[str, Any], item_id: str, month_key: str, variant_id: str | None = None) -> dict[str, Any] | None:
    wanted_variant = str(variant_id or "").strip()
    return next(
        (
            entry
            for entry in data.get("inventory_counts", [])
            if entry.get("item_id") == item_id
            and entry.get("month") == month_key
            and (not wanted_variant or entry.get("variant_id") == wanted_variant)
        ),
        None,
    )


def inventory_previous_month_with_count(data: dict[str, Any], item_id: str, month_key: str, variant_id: str | None = None) -> dict[str, Any] | None:
    wanted_variant = str(variant_id or "").strip()
    entries = [
        entry
        for entry in data.get("inventory_counts", [])
        if entry.get("item_id") == item_id
        and (not wanted_variant or entry.get("variant_id") == wanted_variant)
        and str(entry.get("month") or "") < month_key
    ]
    if not entries:
        return None
    return sorted(entries, key=lambda entry: entry.get("month", ""))[-1]


def inventory_months_between(start_month: str, end_month: str) -> list[str]:
    months: list[str] = []
    current = start_month
    while current < end_month:
        months.append(current)
        current = shift_month(current, 1)
    return months


def inventory_state_before_month(data: dict[str, Any], item: dict[str, Any], variant: dict[str, Any], month_key: str) -> tuple[float, float]:
    start_month = str(item.get("start_month") or month_key)
    if month_key < start_month:
        return 0.0, 0.0

    quantity = max(0.0, float(variant.get("quantity") or 0.0))
    value = max(0.0, float(variant.get("total_price") or 0.0))
    item_id = str(item.get("id") or "")
    variant_id = str(variant.get("id") or "")

    for current_month in inventory_months_between(start_month, month_key):
        purchase_qty, purchase_value = inventory_purchase_totals(data, item_id, current_month, variant_id)
        available_qty = max(0.0, quantity + purchase_qty)
        available_value = max(0.0, value + purchase_value)
        count = inventory_count_for_month(data, item_id, current_month, variant_id)
        if count is None:
            quantity, value = available_qty, available_value
            continue
        end_quantity = min(max(0.0, float(count.get("end_quantity") or 0.0)), available_qty)
        month_unit_price = available_value / available_qty if available_qty > 0 else 0.0
        quantity = end_quantity
        value = end_quantity * month_unit_price

    return quantity, value


def inventory_variant_month_calculation(data: dict[str, Any], item: dict[str, Any], variant: dict[str, Any], month_key: str, end_quantity: float | None = None) -> dict[str, float]:
    item_id = str(item.get("id") or "")
    variant_id = str(variant.get("id") or "")
    start_quantity, start_value = inventory_state_before_month(data, item, variant, month_key)
    purchase_quantity, purchase_value = inventory_purchase_totals(data, item_id, month_key, variant_id)
    available_quantity = max(0.0, start_quantity + purchase_quantity)
    available_value = max(0.0, start_value + purchase_value)
    if end_quantity is None:
        count = inventory_count_for_month(data, item_id, month_key, variant_id)
        end_quantity = float(count.get("end_quantity") or 0.0) if count else available_quantity
    end_quantity = min(max(0.0, float(end_quantity or 0.0)), available_quantity)
    unit_price = available_value / available_quantity if available_quantity > 0 else 0.0
    consumed_quantity = max(0.0, available_quantity - end_quantity)
    consumed_amount = round(consumed_quantity * unit_price, 2)
    return {
        "start_quantity": start_quantity,
        "start_value": round(start_value, 2),
        "purchase_quantity": purchase_quantity,
        "purchase_value": round(purchase_value, 2),
        "available_quantity": available_quantity,
        "available_value": round(available_value, 2),
        "end_quantity": end_quantity,
        "consumed_quantity": consumed_quantity,
        "consumed_amount": consumed_amount,
        "unit_price": unit_price,
        "rest_value": round(end_quantity * unit_price, 2),
    }


def inventory_item_month_calculation(data: dict[str, Any], item: dict[str, Any], month_key: str) -> dict[str, Any]:
    variant_rows: list[dict[str, Any]] = []
    totals = {
        "start_value": 0.0,
        "purchase_value": 0.0,
        "available_value": 0.0,
        "consumed_amount": 0.0,
        "rest_value": 0.0,
    }
    for variant in inventory_item_variants(item):
        count = inventory_count_for_month(data, item["id"], month_key, variant.get("id"))
        calc = inventory_variant_month_calculation(data, item, variant, month_key)
        row = {
            **variant,
            "count_id": count.get("id") if count else "",
            "end_entered": count is not None,
            **calc,
        }
        variant_rows.append(row)
        for key in totals:
            totals[key] += float(calc.get(key) or 0.0)
    return {
        "variants": variant_rows,
        "start_value": round(totals["start_value"], 2),
        "purchase_value": round(totals["purchase_value"], 2),
        "available_value": round(totals["available_value"], 2),
        "consumed_amount": round(totals["consumed_amount"], 2),
        "rest_value": round(totals["rest_value"], 2),
    }


def inventory_start_quantity(data: dict[str, Any], item: dict[str, Any], month_key: str) -> float:
    variants = inventory_item_variants(item)
    if not variants:
        return 0.0
    return sum(inventory_state_before_month(data, item, variant, month_key)[0] for variant in variants)


def inventory_sync_month_transaction(data: dict[str, Any], item: dict[str, Any], month_key: str) -> None:
    calc = inventory_item_month_calculation(data, item, month_key)
    consumed_amount = float(calc["consumed_amount"] or 0.0)
    source = f"inventory:{item['id']}:{month_key}"
    data["transactions"] = [tx for tx in data.get("transactions", []) if str(tx.get("source") or "") != source]
    if consumed_amount <= 0:
        return

    note_parts: list[str] = []
    for variant in calc["variants"]:
        consumed_quantity = float(variant.get("consumed_quantity") or 0.0)
        if consumed_quantity <= 0:
            continue
        note_parts.append(
            f"{variant.get('name')}: {consumed_quantity:g} {variant.get('unit') or 'Stück'} verbraucht · "
            f"Endbestand {float(variant.get('end_quantity') or 0.0):g} {variant.get('unit') or 'Stück'} · "
            f"Restwert {float(variant.get('rest_value') or 0.0):.2f} €"
        )
    notes = "; ".join(note_parts) or "Vorratsverbrauch"
    tx = canonical_transaction(
        {
            "id": new_id("tx"),
            "date": f"{month_key}-28",
            "title": f"Vorratsverbrauch: {item.get('title')}",
            "amount": -consumed_amount,
            "category": item.get("category") or "Lebensmittel",
            "paid": True,
            "payment_method": "account",
            "pot_id": "",
            "notes": notes,
            "source": source,
            "kind": "inventory_consumption",
            "show_in_month": True,
        }
    )
    data.setdefault("transactions", []).append(tx)
    data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))


def inventory_resync_item_from_month(data: dict[str, Any], item: dict[str, Any], start_month: str) -> None:
    item_id = str(item.get("id") or "")
    if not item_id:
        return
    start_month = parse_month(start_month, str(item.get("start_month") or date.today().strftime("%Y-%m")))
    source_prefix = f"inventory:{item_id}:"
    transaction_months: set[str] = set()
    kept_transactions: list[dict[str, Any]] = []
    for tx in data.get("transactions", []):
        source = str(tx.get("source") or "")
        if source.startswith(source_prefix):
            tx_month = source[len(source_prefix):]
            if tx_month >= start_month:
                transaction_months.add(tx_month)
                continue
        kept_transactions.append(tx)
    data["transactions"] = kept_transactions
    count_months = {
        str(row.get("month") or "")
        for row in data.get("inventory_counts", [])
        if row.get("item_id") == item_id and str(row.get("month") or "") >= start_month
    }
    for month_key in sorted(count_months | transaction_months):
        inventory_sync_month_transaction(data, item, month_key)


def inventory_summaries(data: dict[str, Any], month_key: str) -> list[dict[str, Any]]:
    ensure_inventory_variant_references(data)
    rows: list[dict[str, Any]] = []
    for item in sorted(data.get("inventory_items", []), key=lambda row: (str(row.get("active", True)), row.get("title", "").lower())):
        if month_key < str(item.get("start_month") or ""):
            continue
        calc = inventory_item_month_calculation(data, item, month_key)
        rows.append({
            **item,
            "variants": calc["variants"],
            "start_value": calc["start_value"],
            "purchase_value": calc["purchase_value"],
            "available_value": calc["available_value"],
            "consumed_amount": calc["consumed_amount"],
            "rest_value": calc["rest_value"],
        })
    return rows

def canonical_year_balance(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "year": int(item.get("year") or date.today().year),
        "starting_balance": float(item.get("starting_balance") or 0.0),
        "cash_balance": float(item.get("cash_balance") or 0.0),
    }


def category_sort_key(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    return (text.lower(), text)


def collect_categories(data: dict[str, Any]) -> list[str]:
    seen: dict[str, str] = {}

    def add(raw: Any) -> None:
        value = str(raw or "").strip()
        if not value:
            return
        key = value.casefold()
        if key not in seen:
            seen[key] = value

    for value in data.get("categories", []):
        add(value)
    for tx in data.get("transactions", []):
        add(tx.get("category"))
    for template in data.get("recurring_templates", []):
        add(template.get("category"))
    for item in data.get("annual_items", []):
        add(item.get("group"))
    for item in data.get("inventory_items", []):
        add(item.get("category"))

    return sorted(seen.values(), key=category_sort_key)


def ensure_category(data: dict[str, Any], raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    categories = collect_categories(data)
    if value.casefold() not in {item.casefold() for item in categories}:
        categories.append(value)
        categories.sort(key=category_sort_key)
    data["categories"] = categories
    for existing in categories:
        if existing.casefold() == value.casefold():
            return existing
    return value


def resolved_category(form_key: str, *, default: str = "Ohne Kategorie") -> str:
    new_value = str(request.form.get(f"{form_key}_new") or "").strip()
    selected = str(request.form.get(f"{form_key}_select") or "").strip()
    return new_value or selected or default


def normalize_data(raw: Any) -> dict[str, Any]:
    base = deep_default_data()
    base.setdefault("inventory_items", [])
    base.setdefault("inventory_counts", [])
    base.setdefault("inventory_purchases", [])
    if not isinstance(raw, dict):
        base["categories"] = collect_categories(base)
        return base

    settings = raw.get("settings", {})
    if isinstance(settings, dict):
        base["settings"]["monthly_budget_target"] = float(settings.get("monthly_budget_target", base["settings"]["monthly_budget_target"]))
        base["settings"]["starting_balance"] = float(settings.get("starting_balance", base["settings"]["starting_balance"]))
        base["settings"]["cash_balance"] = float(settings.get("cash_balance", base["settings"].get("cash_balance", 0.0)))
        base["settings"]["app_title"] = str(settings.get("app_title") or base["settings"]["app_title"])

    if isinstance(raw.get("categories"), list):
        base["categories"] = [str(item).strip() for item in raw["categories"] if str(item).strip()]

    if isinstance(raw.get("transactions"), list):
        base["transactions"] = [canonical_transaction(tx) for tx in raw["transactions"] if isinstance(tx, dict)]

    if isinstance(raw.get("recurring_templates"), list):
        base["recurring_templates"] = [canonical_recurring(tx) for tx in raw["recurring_templates"] if isinstance(tx, dict)]

    if isinstance(raw.get("pots"), list):
        base["pots"] = [canonical_pot(pot) for pot in raw["pots"] if isinstance(pot, dict)]

    if isinstance(raw.get("pot_plans"), list):
        base["pot_plans"] = [canonical_pot_plan(item) for item in raw["pot_plans"] if isinstance(item, dict)]

    if isinstance(raw.get("annual_items"), list):
        base["annual_items"] = [canonical_annual(item) for item in raw["annual_items"] if isinstance(item, dict)]

    if isinstance(raw.get("inventory_items"), list):
        base["inventory_items"] = [canonical_inventory_item(item) for item in raw["inventory_items"] if isinstance(item, dict)]
    else:
        base["inventory_items"] = []

    if isinstance(raw.get("inventory_counts"), list):
        base["inventory_counts"] = [canonical_inventory_count(item) for item in raw["inventory_counts"] if isinstance(item, dict) and str(item.get("item_id") or "").strip()]
    else:
        base["inventory_counts"] = []

    if isinstance(raw.get("inventory_purchases"), list):
        base["inventory_purchases"] = [canonical_inventory_purchase(item) for item in raw["inventory_purchases"] if isinstance(item, dict) and str(item.get("item_id") or "").strip()]
    else:
        base["inventory_purchases"] = []

    ensure_inventory_variant_references(base)
    base["inventory_counts"].sort(key=lambda row: (row["month"], row["item_id"], row.get("variant_id", ""), row["id"]))
    base["inventory_purchases"].sort(key=lambda row: (row["month"], row["item_id"], row.get("variant_id", ""), row["id"]))

    if isinstance(raw.get("year_start_balances"), list):
        base["year_start_balances"] = [canonical_year_balance(item) for item in raw["year_start_balances"] if isinstance(item, dict)]
    else:
        base["year_start_balances"] = []

    if isinstance(raw.get("deleted_recurring_sources"), list):
        base["deleted_recurring_sources"] = sorted({str(item).strip() for item in raw["deleted_recurring_sources"] if str(item).strip()})
    else:
        base["deleted_recurring_sources"] = []

    dismissals = raw.get("annual_rollover_dismissals", {})
    base["annual_rollover_dismissals"] = {}
    if isinstance(dismissals, dict):
        for raw_year, raw_keys in dismissals.items():
            try:
                year_key = str(int(raw_year))
            except (TypeError, ValueError):
                continue
            if not isinstance(raw_keys, list):
                continue
            cleaned = sorted({str(value).strip() for value in raw_keys if str(value).strip()})
            if cleaned:
                base["annual_rollover_dismissals"][year_key] = cleaned

    if isinstance(raw.get("trash"), list):
        base["trash"] = [canonical_trash_item(item) for item in raw["trash"] if isinstance(item, dict)]
    else:
        base["trash"] = []

    base["categories"] = collect_categories(base)
    return base


def load_data() -> dict[str, Any]:
    stored = _read_data_file(DATA_PATH)
    if stored is not None:
        return stored

    legacy = _legacy_share_data()
    if legacy is not None:
        # Existing installations used /share as their primary location. Migrate
        # before returning so every following Supervisor checkpoint contains it.
        _write_json_atomic(DATA_PATH, legacy)
        return legacy

    defaults = normalize_data(deep_default_data())
    _write_json_atomic(DATA_PATH, defaults)
    return defaults


def save_data(data: dict[str, Any]) -> None:
    payload = normalize_data(data)
    _write_json_atomic(DATA_PATH, payload)
    write_backup_snapshot(payload)
    _sync_share_copy(payload)


def latest_known_month(data: dict[str, Any]) -> str:
    months: list[str] = [date.today().strftime("%Y-%m")]
    months.extend(month_of(tx["date"]) for tx in data.get("transactions", []))
    months.extend(item["month"] for item in data.get("pot_plans", []))
    months.extend(f"{item['year']:04d}-{item['month']}" for item in data.get("annual_items", []))
    return max(months)


def find_pot(data: dict[str, Any], pot_id: str) -> dict[str, Any] | None:
    for pot in data.get("pots", []):
        if pot["id"] == pot_id:
            return pot
    return None


def pot_name(data: dict[str, Any], pot_id: str) -> str:
    pot = find_pot(data, pot_id)
    return pot["name"] if pot else ""


def normalize_payment_method(raw: Any, default: str = "credit_card") -> str:
    value = str(raw or default).strip().casefold().replace("-", "_").replace(" ", "_")
    if value in {"account", "konto", "bank", "bankkonto", "giro", "girokonto", "ec", "debit", "lastschrift"}:
        return "account"
    if value in {"credit_card", "kreditkarte", "karte", "card", "visa", "mastercard"}:
        return "credit_card"
    return "account" if default == "account" else "credit_card"


def payment_method_label_value(value: Any) -> str:
    return "Konto" if normalize_payment_method(value, "credit_card") == "account" else "Kreditkarte"


@app.template_filter("payment_method_label")
def payment_method_label_filter(value: Any) -> str:
    return payment_method_label_value(value)


def default_payment_method_for_transaction(tx: dict[str, Any]) -> str:
    source = str(tx.get("source") or "")
    kind = str(tx.get("kind") or "")
    category = str(tx.get("category") or "")
    if source.startswith("recurring:") or source == "pot_payment" or kind == "recurring" or category.casefold() == "fixkosten":
        return "account"
    return "credit_card"


def month_visibility_label(tx: dict[str, Any]) -> str:
    if str(tx.get("source") or "") == "pot_payment":
        return "mit Monat" if bool(tx.get("show_in_month", True)) else "nur Topf"
    return "mit Monat"


def recurring_valid_from(template: dict[str, Any]) -> str:
    return parse_month(str(template.get("valid_from") or "").strip(), "1900-01")


def recurring_valid_until(template: dict[str, Any]) -> str:
    raw = str(template.get("valid_until") or "").strip()
    return parse_month(raw, "") if raw else ""


def recurring_applies_to_month(template: dict[str, Any], month_key: str) -> bool:
    valid_from = recurring_valid_from(template)
    valid_until = recurring_valid_until(template)
    if month_key < valid_from:
        return False
    if valid_until and month_key > valid_until:
        return False
    month_num = int(month_key[5:7])
    start_month = int(str(template.get("start_month") or "01"))
    interval = 3 if int(template.get("interval_months") or 1) == 3 else 1
    return (month_num - start_month) % interval == 0


def recurring_exists_for_month(data: dict[str, Any], template: dict[str, Any], month_key: str) -> bool:
    day_text = f"{template['day']:02d}"
    for tx in data.get("transactions", []):
        if month_of(tx["date"]) != month_key:
            continue
        if tx.get("source") == f"recurring:{template['id']}:{month_key}":
            return True
        if tx["title"] == template["title"] and abs(tx["amount"] - template["amount"]) < 0.0001 and tx["date"][8:10] == day_text:
            return True
    return False


def recurring_source_month_key(tx: dict[str, Any], template_id: str) -> str | None:
    source = str(tx.get("source") or "")
    prefix = f"recurring:{template_id}:"
    if not source.startswith(prefix):
        return None
    month_key = source[len(prefix):]
    try:
        return parse_month(month_key, month_key)
    except Exception:
        return None


def recurring_source_key(template_id: str, month_key: str) -> str:
    return f"recurring:{template_id}:{month_key}"


def is_recurring_source_deleted(data: dict[str, Any], source: str) -> bool:
    return source in set(data.get("deleted_recurring_sources", []))


def transaction_matches_search(data: dict[str, Any], tx: dict[str, Any], query: str) -> bool:
    return matches_search(query, tx.get("title"), tx.get("category"), tx.get("notes"), tx.get("date"), tx.get("amount"), money(float(tx.get("amount") or 0.0)), payment_method_label_value(tx.get("payment_method")), pot_name(data, tx.get("pot_id") or ""))


def recurring_matches_search(data: dict[str, Any], template: dict[str, Any], query: str) -> bool:
    return matches_search(query, template.get("title"), template.get("category"), template.get("notes"), template.get("start_month"), template.get("valid_from"), template.get("valid_until"), template.get("day"), template.get("amount"), money(float(template.get("amount") or 0.0)), payment_method_label_value(template.get("payment_method")), pot_name(data, template.get("pot_id") or ""))


def normalize_recurring_status_filter(value: str | None) -> str:
    value = str(value or "active").strip().lower()
    if value in {"active", "ended", "all"}:
        return value
    return "active"


def recurring_is_ended_for_month(template: dict[str, Any], month_key: str) -> bool:
    valid_until = recurring_valid_until(template)
    return bool(valid_until and valid_until < month_key)


def recurring_matches_status_filter(template: dict[str, Any], month_key: str, status_filter: str) -> bool:
    status_filter = normalize_recurring_status_filter(status_filter)
    ended = recurring_is_ended_for_month(template, month_key)
    if status_filter == "all":
        return True
    if status_filter == "ended":
        return ended
    return bool(template.get("active", True)) and not ended


def annual_matches_search(item: dict[str, Any], query: str) -> bool:
    return matches_search(query, item.get("title"), item.get("group"), item.get("notes"), item.get("month"), item.get("year"), item.get("amount"), money(float(item.get("amount") or 0.0)))


def sync_recurring_template_changes(data: dict[str, Any], template: dict[str, Any], effective_from: str) -> tuple[int, int]:
    updated = 0
    removed = 0
    kept: list[dict[str, Any]] = []
    for tx in data.get("transactions", []):
        source_month_key = recurring_source_month_key(tx, template["id"])
        if not source_month_key or source_month_key < effective_from:
            kept.append(tx)
            continue
        if template.get("active", True) and recurring_applies_to_month(template, source_month_key):
            tx["date"] = f"{source_month_key}-{template['day']:02d}"
            tx["title"] = template["title"]
            tx["amount"] = template["amount"]
            tx["category"] = template["category"]
            tx["paid"] = template.get("paid_default", False)
            tx["payment_method"] = normalize_payment_method(template.get("payment_method"), "account")
            tx["pot_id"] = template.get("pot_id", "")
            tx["notes"] = template.get("notes", "")
            tx["kind"] = "recurring"
            kept.append(canonical_transaction(tx))
            updated += 1
        else:
            removed += 1
    if updated or removed:
        data["transactions"] = kept
        data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
    return updated, removed


def remove_recurring_transactions_from(data: dict[str, Any], template_id: str, from_month: str) -> int:
    removed = 0
    kept: list[dict[str, Any]] = []
    for tx in data.get("transactions", []):
        source_month_key = recurring_source_month_key(tx, template_id)
        if source_month_key and source_month_key >= from_month:
            removed += 1
            continue
        kept.append(tx)
    if removed:
        data["transactions"] = kept
        data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
    return removed


def remove_deleted_recurring_markers_from(data: dict[str, Any], template_id: str, from_month: str) -> int:
    removed = 0
    kept: list[str] = []
    prefix = f"recurring:{template_id}:"
    for source in data.get("deleted_recurring_sources", []):
        source_text = str(source)
        if source_text.startswith(prefix):
            month_key = source_text[len(prefix):]
            if parse_month(month_key, "") and month_key >= from_month:
                removed += 1
                continue
        kept.append(source_text)
    if removed:
        data["deleted_recurring_sources"] = sorted(kept)
    return removed


def close_recurring_template_at(template: dict[str, Any], delete_from_month: str) -> bool:
    valid_from = recurring_valid_from(template)
    if delete_from_month <= valid_from:
        return False
    new_until = shift_month(delete_from_month, -1)
    existing_until = recurring_valid_until(template)
    if existing_until and existing_until < new_until:
        return True
    template["valid_until"] = new_until
    return True


def ensure_month_generated(data: dict[str, Any], month_key: str) -> bool:
    changed = False
    for template in data.get("recurring_templates", []):
        if not template.get("active", True):
            continue
        if not recurring_applies_to_month(template, month_key):
            continue
        if recurring_exists_for_month(data, template, month_key):
            continue
        source_key = recurring_source_key(template["id"], month_key)
        if is_recurring_source_deleted(data, source_key):
            continue
        tx = canonical_transaction(
            {
                "id": new_id("tx"),
                "date": f"{month_key}-{template['day']:02d}",
                "title": template["title"],
                "amount": template["amount"],
                "category": template["category"],
                "paid": template.get("paid_default", False),
                "payment_method": normalize_payment_method(template.get("payment_method"), "account"),
                "pot_id": template.get("pot_id", ""),
                "notes": template.get("notes", ""),
                "source": source_key,
                "kind": "recurring",
            }
        )
        data["transactions"].append(tx)
        changed = True
    if changed:
        data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
    return changed


def transactions_for_month(data: dict[str, Any], month_key: str) -> list[dict[str, Any]]:
    return sorted(
        [
            tx
            for tx in data.get("transactions", [])
            if month_of(tx["date"]) == month_key and (str(tx.get("source") or "") != "pot_payment" or bool(tx.get("show_in_month", True)))
        ],
        key=lambda tx: (tx["date"], tx["amount"], tx["title"], tx["id"]),
    )


def summarize_month(transactions: list[dict[str, Any]], budget_target: float) -> dict[str, Any]:
    income = sum(tx["amount"] for tx in transactions if tx["amount"] > 0)
    expenses = -sum(tx["amount"] for tx in transactions if tx["amount"] < 0)
    fixed_expenses = -sum(tx["amount"] for tx in transactions if tx["amount"] < 0 and tx["category"].lower() == "fixkosten")
    variable_expenses = expenses - fixed_expenses

    # "Offen" und "Konto offen" zeigen den echten offenen Saldo.
    # Ausgaben bleiben negativ, Einnahmen positiv. Dadurch werden offene Eingänge
    # korrekt gegengerechnet und reine offene Ausgaben nicht mehr als Plus angezeigt.
    unpaid = [tx for tx in transactions if not tx["paid"]]
    unpaid_amount = sum(float(tx.get("amount") or 0.0) for tx in unpaid)

    account_unpaid = [
        tx
        for tx in unpaid
        if normalize_payment_method(tx.get("payment_method"), default_payment_method_for_transaction(tx)) == "account"
    ]
    account_unpaid_amount = sum(float(tx.get("amount") or 0.0) for tx in account_unpaid)

    credit_card_unpaid = [
        tx
        for tx in unpaid
        if normalize_payment_method(tx.get("payment_method"), default_payment_method_for_transaction(tx)) == "credit_card"
    ]
    credit_card_unpaid_amount = sum(float(tx.get("amount") or 0.0) for tx in credit_card_unpaid)

    paid_expenses = -sum(tx["amount"] for tx in transactions if tx["amount"] < 0 and tx["paid"])
    monthly_result = income - expenses
    transfer_to_year = 0.0
    gap_to_budget = budget_target - income if income < budget_target else 0.0
    return {
        "income": income,
        "expenses": expenses,
        "fixed_expenses": fixed_expenses,
        "variable_expenses": variable_expenses,
        "monthly_result": monthly_result,
        "transfer_to_year": transfer_to_year,
        "gap_to_budget": gap_to_budget,
        "unpaid_count": len(unpaid),
        "unpaid_amount": unpaid_amount,
        "account_unpaid_count": len(account_unpaid),
        "account_unpaid_amount": account_unpaid_amount,
        "credit_card_unpaid_count": len(credit_card_unpaid),
        "credit_card_unpaid_amount": credit_card_unpaid_amount,
        "paid_expenses": paid_expenses,
    }


def category_totals(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    for tx in transactions:
        if tx["amount"] < 0:
            totals[tx["category"]] += -tx["amount"]
    rows = [{"category": cat, "amount": amount} for cat, amount in totals.items()]
    rows.sort(key=lambda row: row["amount"], reverse=True)
    return rows


def resolve_category_name(data: dict[str, Any], raw_value: str | None) -> str:
    target = str(raw_value or "").strip()
    if not target:
        return ""
    for existing in collect_categories(data):
        if existing.casefold() == target.casefold():
            return existing
    return target


def pot_effect_amount(tx: dict[str, Any]) -> float:
    amount = float(tx.get("amount") or 0.0)
    if not str(tx.get("pot_id") or "").strip():
        return 0.0
    if str(tx.get("source") or "") == "pot_payment":
        return amount
    return -amount


def pot_summaries(data: dict[str, Any], month_key: str) -> list[dict[str, Any]]:
    result = []
    all_transactions = data.get("transactions", [])
    for pot in data.get("pots", []):
        legacy_planned = sum(item["amount"] for item in data.get("pot_plans", []) if item["pot_id"] == pot["id"] and item["month"] <= month_key)
        pot_amounts = [
            pot_effect_amount(tx)
            for tx in all_transactions
            if tx["pot_id"] == pot["id"] and tx["paid"] and month_of(tx["date"]) <= month_key
        ]
        deposits = sum(amount for amount in pot_amounts if amount > 0)
        spent = sum(-amount for amount in pot_amounts if amount < 0)
        actual_balance = deposits - spent
        result.append(
            {
                "id": pot["id"],
                "name": pot["name"],
                "color": pot.get("color", "#0f766e"),
                "planned": legacy_planned,
                "deposits": deposits,
                "funded": deposits,
                "spent": spent,
                "balance": actual_balance,
                "payment_count": sum(
                    1
                    for tx in all_transactions
                    if tx["pot_id"] == pot["id"] and tx["paid"] and month_of(tx["date"]) <= month_key and pot_effect_amount(tx) < 0
                ),
            }
        )
    result.sort(key=lambda item: item["name"].lower())
    return result


def pot_movements(data: dict[str, Any], pot_id: str, month_key: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tx in data.get("transactions", []):
        if tx.get("pot_id") != pot_id:
            continue
        if month_key and month_of(tx["date"]) > month_key:
            continue
        source = str(tx.get("source") or "manual")
        movement = copy.deepcopy(tx)
        movement["account_amount"] = float(tx.get("amount") or 0.0)
        movement["amount"] = pot_effect_amount(tx)
        if source == "pot_payment":
            movement["movement_source"] = "manual"
            movement["movement_source_label"] = "Topf-Bewegung"
            movement["month_visible"] = bool(tx.get("show_in_month", True))
        else:
            movement["movement_source"] = "monthly"
            movement["movement_source_label"] = "Monatsbuchung"
            movement["month_visible"] = True
        items.append(movement)
    return sorted(items, key=lambda tx: (tx["date"], tx["title"], tx["id"]), reverse=True)


def default_payment_date(month_key: str) -> str:
    current_month = date.today().strftime("%Y-%m")
    if month_key == current_month:
        return date.today().isoformat()
    return f"{month_key}-01"


def default_year_account_balance(data: dict[str, Any]) -> float:
    settings = data.get("settings", {})
    return float(settings.get("starting_balance", 0.0))


def default_year_cash_balance(data: dict[str, Any]) -> float:
    settings = data.get("settings", {})
    return float(settings.get("cash_balance", 0.0))


def default_year_start_balance(data: dict[str, Any]) -> float:
    return default_year_account_balance(data) + default_year_cash_balance(data)


def get_year_start_balance_entry(data: dict[str, Any], year: int) -> dict[str, Any] | None:
    for item in data.get("year_start_balances", []):
        if int(item.get("year") or 0) == int(year):
            return item
    return None


def get_year_start_balance(data: dict[str, Any], year: int) -> float:
    entry = get_year_start_balance_entry(data, year)
    if entry is not None:
        return float(entry.get("starting_balance", 0.0))
    return default_year_account_balance(data)


def get_year_cash_balance(data: dict[str, Any], year: int) -> float:
    entry = get_year_start_balance_entry(data, year)
    if entry is not None:
        return float(entry.get("cash_balance", 0.0))
    return default_year_cash_balance(data)


def set_year_balances(data: dict[str, Any], year: int, amount: float, cash_amount: float | None = None) -> None:
    entry = get_year_start_balance_entry(data, year)
    if entry is None:
        payload = {"year": year, "starting_balance": amount, "cash_balance": cash_amount if cash_amount is not None else default_year_cash_balance(data)}
        data.setdefault("year_start_balances", []).append(canonical_year_balance(payload))
    else:
        entry["starting_balance"] = float(amount)
        if cash_amount is not None:
            entry["cash_balance"] = float(cash_amount)
        elif "cash_balance" not in entry:
            entry["cash_balance"] = default_year_cash_balance(data)
    data["year_start_balances"].sort(key=lambda item: int(item["year"]))


def set_year_start_balance(data: dict[str, Any], year: int, amount: float) -> None:
    set_year_balances(data, year, amount)


def annual_group_is_followup(group: str) -> bool:
    return str(group or "").strip().casefold() in {"planung", "jahreskosten"}


def annual_followup_items_for_year(data: dict[str, Any], year: int) -> list[dict[str, Any]]:
    return [item for item in data.get("annual_items", []) if int(item["year"]) == year and annual_group_is_followup(item.get("group", ""))]


def annual_opening_balance(data: dict[str, Any], year: int) -> float:
    return get_year_start_balance(data, year) + get_year_cash_balance(data, year)


def annual_timeline(data: dict[str, Any], year: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cumulative_without_cash = get_year_start_balance(data, year)
    cumulative_cash = get_year_cash_balance(data, year)
    year_items = [item for item in data.get("annual_items", []) if int(item["year"]) == year]
    for month_num in range(1, 13):
        month_code = f"{month_num:02d}"
        month_key = f"{year:04d}-{month_code}"
        planned_items = [item for item in year_items if item["month"] == month_code]
        non_cash_items = [item for item in planned_items if not bool(item.get("is_cash", False))]
        cash_items = [item for item in planned_items if bool(item.get("is_cash", False))]
        planned_income = sum(item["amount"] for item in planned_items if item["amount"] > 0)
        planned_expenses = -sum(item["amount"] for item in planned_items if item["amount"] < 0)
        planned_total = planned_income - planned_expenses
        planned_non_cash_total = sum(item["amount"] for item in non_cash_items)
        planned_cash_total = sum(item["amount"] for item in cash_items)
        cumulative_without_cash += planned_non_cash_total
        cumulative_cash += planned_cash_total
        cumulative_with_cash = cumulative_without_cash + cumulative_cash
        rows.append(
            {
                "month_num": month_num,
                "month": month_code,
                "month_key": month_key,
                "label": format_month_label(month_key).split()[0],
                "planned_income": planned_income,
                "planned_expenses": planned_expenses,
                "planned_total": planned_total,
                "planned_non_cash_total": planned_non_cash_total,
                "planned_cash_total": planned_cash_total,
                "surplus": 0.0,
                "month_total": planned_total,
                "cumulative_without_cash": cumulative_without_cash,
                "cumulative_cash": cumulative_cash,
                "cumulative_with_cash": cumulative_with_cash,
                "cumulative_end": cumulative_with_cash,
            }
        )
    return rows


def annual_summary(data: dict[str, Any], year: int, selected_month: str) -> dict[str, Any]:
    items = [item for item in data.get("annual_items", []) if int(item["year"]) == year]
    income = sum(item["amount"] for item in items if item["amount"] > 0)
    expenses = -sum(item["amount"] for item in items if item["amount"] < 0)
    timeline = annual_timeline(data, year)
    opening_balance_without_cash = get_year_start_balance(data, year)
    opening_cash_balance = get_year_cash_balance(data, year)
    opening_balance = opening_balance_without_cash + opening_cash_balance
    if selected_month.startswith(f"{year:04d}-"):
        selected_month_num = int(selected_month[5:7])
    else:
        selected_month_num = 12
    current_rows = [row for row in timeline if row["month_num"] <= selected_month_num]
    current_income = sum(row["planned_income"] for row in current_rows)
    current_expenses = sum(row["planned_expenses"] for row in current_rows)
    current_surplus = 0.0
    current_balance_without_cash = current_rows[-1]["cumulative_without_cash"] if current_rows else opening_balance_without_cash
    current_cash_balance = current_rows[-1]["cumulative_cash"] if current_rows else opening_cash_balance
    current_balance = current_rows[-1]["cumulative_with_cash"] if current_rows else opening_balance
    forecast_balance_without_cash = timeline[-1]["cumulative_without_cash"] if timeline else opening_balance_without_cash
    forecast_cash_balance = timeline[-1]["cumulative_cash"] if timeline else opening_cash_balance
    forecast_balance = timeline[-1]["cumulative_with_cash"] if timeline else opening_balance
    total_surplus = 0.0
    return {
        "income": income,
        "expenses": expenses,
        "net": income - expenses,
        "month_surplus": total_surplus,
        "with_surplus": income - expenses,
        "count": len(items),
        "current_income": current_income,
        "current_expenses": current_expenses,
        "current_surplus": current_surplus,
        "current_net": current_income - current_expenses,
        "current_balance": current_balance,
        "current_balance_without_cash": current_balance_without_cash,
        "current_cash_balance": current_cash_balance,
        "forecast_balance": forecast_balance,
        "forecast_balance_without_cash": forecast_balance_without_cash,
        "forecast_cash_balance": forecast_cash_balance,
        "current_label": format_month_label(f"{year:04d}-{selected_month_num:02d}"),
        "opening_balance": opening_balance,
        "opening_balance_without_cash": opening_balance_without_cash,
        "opening_cash_balance": opening_cash_balance,
    }


def annual_items_for_year(data: dict[str, Any], year: int, month: str | None = None) -> list[dict[str, Any]]:
    items = [item for item in data.get("annual_items", []) if int(item["year"]) == year]
    if month:
        items = [item for item in items if item["month"] == month]
    return sorted(items, key=lambda item: (item["month"], item["title"], item["id"]))


def annual_comparison_key(item: dict[str, Any]) -> tuple[str, str, str, bool]:
    return (
        str(item.get("month") or "01").zfill(2),
        str(item.get("title") or "").strip().casefold(),
        str(item.get("group") or "").strip().casefold(),
        bool(item.get("is_cash", False)),
    )


def annual_rollover_suggestion_id(kind: str, target_year: int, source_id: str, target_id: str = "") -> str:
    return f"{kind}:{int(target_year)}:{source_id}:{target_id}"


def annual_rollover_dismissed_keys(data: dict[str, Any], year: int) -> set[str]:
    raw = data.get("annual_rollover_dismissals", {})
    if not isinstance(raw, dict):
        return set()
    values = raw.get(str(int(year)), [])
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def set_annual_rollover_dismissed_keys(data: dict[str, Any], year: int, keys: set[str]) -> None:
    raw = data.setdefault("annual_rollover_dismissals", {})
    if not isinstance(raw, dict):
        raw = {}
        data["annual_rollover_dismissals"] = raw
    year_key = str(int(year))
    cleaned = sorted({str(value).strip() for value in keys if str(value).strip()})
    if cleaned:
        raw[year_key] = cleaned
    else:
        raw.pop(year_key, None)


def annual_rollover_suggestions(data: dict[str, Any], year: int, *, include_dismissed: bool = False) -> dict[str, Any]:
    previous_year = year - 1
    previous_groups: dict[tuple[str, str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    current_groups: dict[tuple[str, str, str, bool], list[dict[str, Any]]] = defaultdict(list)

    for item in annual_items_for_year(data, previous_year):
        previous_groups[annual_comparison_key(item)].append(item)
    for item in annual_items_for_year(data, year):
        current_groups[annual_comparison_key(item)].append(item)

    missing_all: list[dict[str, Any]] = []
    amount_changes_all: list[dict[str, Any]] = []
    skipped_ambiguous = 0

    for key, previous_items in previous_groups.items():
        current_items = current_groups.get(key, [])
        if len(previous_items) != 1 or len(current_items) > 1:
            skipped_ambiguous += 1
            continue
        previous_item = previous_items[0]
        if not current_items:
            row = dict(previous_item)
            row["suggestion_id"] = annual_rollover_suggestion_id("missing", year, previous_item["id"])
            missing_all.append(row)
            continue
        current_item = current_items[0]
        previous_amount = round(float(previous_item.get("amount") or 0.0), 2)
        current_amount = round(float(current_item.get("amount") or 0.0), 2)
        if previous_amount != current_amount:
            amount_changes_all.append(
                {
                    "source": previous_item,
                    "target": current_item,
                    "difference": previous_amount - current_amount,
                    "suggestion_id": annual_rollover_suggestion_id("amount", year, previous_item["id"], current_item["id"]),
                }
            )

    missing_all.sort(key=lambda item: (item["month"], item["title"].casefold(), item["id"]))
    amount_changes_all.sort(key=lambda row: (row["target"]["month"], row["target"]["title"].casefold(), row["target"]["id"]))
    dismissed = annual_rollover_dismissed_keys(data, year)
    if include_dismissed:
        missing = missing_all
        amount_changes = amount_changes_all
    else:
        missing = [item for item in missing_all if item["suggestion_id"] not in dismissed]
        amount_changes = [row for row in amount_changes_all if row["suggestion_id"] not in dismissed]
    active_ids = {item["suggestion_id"] for item in missing_all} | {row["suggestion_id"] for row in amount_changes_all}
    hidden_count = len(active_ids & dismissed)
    return {
        "previous_year": previous_year,
        "missing": missing,
        "amount_changes": amount_changes,
        "count": len(missing) + len(amount_changes),
        "total_count": len(missing_all) + len(amount_changes_all),
        "hidden_count": hidden_count,
        "skipped_ambiguous": skipped_ambiguous,
    }


def annual_rollover_suggestion_map(data: dict[str, Any], year: int, *, include_dismissed: bool = False) -> dict[str, dict[str, Any]]:
    suggestions = annual_rollover_suggestions(data, year, include_dismissed=include_dismissed)
    rows: dict[str, dict[str, Any]] = {}
    for item in suggestions["missing"]:
        rows[item["suggestion_id"]] = {"kind": "missing", "source": item}
    for row in suggestions["amount_changes"]:
        rows[row["suggestion_id"]] = {"kind": "amount", **row}
    return rows


def apply_annual_rollover_suggestion(data: dict[str, Any], year: int, suggestion: dict[str, Any]) -> tuple[bool, str]:
    kind = str(suggestion.get("kind") or "")
    if kind == "missing":
        source_item = suggestion.get("source")
        if not isinstance(source_item, dict) or int(source_item.get("year") or 0) != year - 1:
            return False, ""
        source_key = annual_comparison_key(source_item)
        if any(
            int(item.get("year") or 0) == year and annual_comparison_key(item) == source_key
            for item in data.get("annual_items", [])
        ):
            return False, str(source_item.get("title") or "")
        clone = canonical_annual(
            {
                "id": new_id("annual"),
                "year": year,
                "month": source_item["month"],
                "title": source_item["title"],
                "amount": source_item["amount"],
                "group": source_item["group"],
                "notes": source_item.get("notes", ""),
                "paid": False,
                "is_cash": source_item.get("is_cash", False),
            }
        )
        data.setdefault("annual_items", []).append(clone)
        return True, clone["title"]

    if kind == "amount":
        source_item = suggestion.get("source")
        target_item = suggestion.get("target")
        if not isinstance(source_item, dict) or not isinstance(target_item, dict):
            return False, ""
        if int(source_item.get("year") or 0) != year - 1 or int(target_item.get("year") or 0) != year:
            return False, ""
        live_target = next((item for item in data.get("annual_items", []) if item.get("id") == target_item.get("id")), None)
        live_source = next((item for item in data.get("annual_items", []) if item.get("id") == source_item.get("id")), None)
        if live_target is None or live_source is None or annual_comparison_key(live_source) != annual_comparison_key(live_target):
            return False, str(target_item.get("title") or "")
        new_amount = float(live_source.get("amount") or 0.0)
        if round(float(live_target.get("amount") or 0.0), 2) == round(new_amount, 2):
            return False, str(live_target.get("title") or "")
        live_target["amount"] = new_amount
        return True, str(live_target.get("title") or "")

    return False, ""


def replace_followup_items(data: dict[str, Any], source_year: int, end_year: int) -> tuple[int, int]:
    source_items = annual_followup_items_for_year(data, source_year)
    removed = 0
    created = 0
    for target_year in range(source_year + 1, end_year + 1):
        before = len(data["annual_items"])
        data["annual_items"] = [
            item
            for item in data["annual_items"]
            if not (int(item["year"]) == target_year and annual_group_is_followup(item.get("group", "")))
        ]
        removed += before - len(data["annual_items"])
        for item in source_items:
            clone = canonical_annual(
                {
                    "id": new_id("annual"),
                    "year": target_year,
                    "month": item["month"],
                    "title": item["title"],
                    "amount": item["amount"],
                    "group": item["group"],
                    "notes": item.get("notes", ""),
                    "paid": False,
                    "is_cash": bool(item.get("is_cash", False)),
                }
            )
            data["annual_items"].append(clone)
            created += 1
    data["annual_items"].sort(key=lambda item: (item["year"], item["month"], item["title"], item["id"]))
    return removed, created


def refresh_followup_year_start_balances(data: dict[str, Any], source_year: int, end_year: int) -> int:
    updated = 0
    for target_year in range(source_year + 1, end_year + 1):
        previous_year = target_year - 1
        previous_timeline = annual_timeline(data, previous_year)
        if previous_timeline:
            previous_without_cash = previous_timeline[-1]["cumulative_without_cash"]
            previous_cash = previous_timeline[-1]["cumulative_cash"]
        else:
            previous_without_cash = get_year_start_balance(data, previous_year)
            previous_cash = get_year_cash_balance(data, previous_year)
        set_year_balances(data, target_year, previous_without_cash, previous_cash)
        updated += 1
    return updated


def month_options(data: dict[str, Any]) -> list[str]:
    months = {month_of(tx["date"]) for tx in data.get("transactions", [])}
    months.update(item["month"] for item in data.get("pot_plans", []))
    months.update(f"{item['year']:04d}-{item['month']}" for item in data.get("annual_items", []))
    if not months:
        months.add(date.today().strftime("%Y-%m"))
    return sorted(months)


def is_no_fixed_category_filter(category_name: str) -> bool:
    return str(category_name or "").strip() == CATEGORY_FILTER_NO_FIXED


def category_filter_label(category_name: str) -> str:
    if is_no_fixed_category_filter(category_name):
        return CATEGORY_FILTER_NO_FIXED_LABEL
    return str(category_name or "").strip()


def normalize_category_filter(data: dict[str, Any], raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {
        CATEGORY_FILTER_NO_FIXED.casefold(),
        "ohne_fixkosten",
        "nicht_fixkosten",
        "keine_fixkosten",
        "no_fixed",
        "not_fixed",
    }:
        return CATEGORY_FILTER_NO_FIXED
    return resolve_category_name(data, value)


def filtered_transactions(transactions: list[dict[str, Any]], category_name: str) -> list[dict[str, Any]]:
    if not category_name:
        return transactions
    if is_no_fixed_category_filter(category_name):
        return [tx for tx in transactions if str(tx.get("category") or "").casefold() != "fixkosten"]
    return [tx for tx in transactions if tx["category"].casefold() == category_name.casefold()]


def resolve_paid_filter(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    if value in {"open", "paid"}:
        return value
    return "all"




def resolve_payment_filter(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    if value in {"account", "konto"}:
        return "account"
    if value in {"credit_card", "credit-card", "card", "kreditkarte"}:
        return "credit_card"
    return "all"


def filter_transactions_by_payment_method(transactions: list[dict[str, Any]], payment_filter: str) -> list[dict[str, Any]]:
    if payment_filter not in {"account", "credit_card"}:
        return transactions
    return [
        tx
        for tx in transactions
        if normalize_payment_method(tx.get("payment_method"), default_payment_method_for_transaction(tx)) == payment_filter
    ]

def filter_transactions_by_paid_status(transactions: list[dict[str, Any]], paid_filter: str) -> list[dict[str, Any]]:
    if paid_filter == "open":
        return [tx for tx in transactions if not tx["paid"]]
    if paid_filter == "paid":
        return [tx for tx in transactions if tx["paid"]]
    return transactions


def filter_transactions_by_amount_range(transactions: list[dict[str, Any]], amount_min: float | None, amount_max: float | None) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for tx in transactions:
        amount = float(tx.get("amount") or 0.0)
        if amount_min is not None and amount < amount_min:
            continue
        if amount_max is not None and amount > amount_max:
            continue
        filtered.append(tx)
    return filtered


def parse_optional_amount(raw: Any) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return parse_amount(text)


def amount_mode_from_amount(amount: Any, default: str = "expense") -> str:
    try:
        numeric = float(amount)
    except (TypeError, ValueError):
        return default
    if numeric > 0:
        return "income"
    if numeric < 0:
        return "expense"
    return default


def signed_amount_from_form(raw_amount: Any, raw_mode: Any, default_mode: str = "expense") -> float:
    mode = str(raw_mode or default_mode).strip().lower()
    if mode not in {"expense", "income"}:
        mode = default_mode
    amount = abs(parse_amount(raw_amount))
    return amount if mode == "income" else -amount


def handle_transaction_post(data: dict[str, Any], month_key: str) -> None:
    action = (request.form.get("action") or "").strip()
    if action == "save_transaction":
        tx_id = (request.form.get("tx_id") or "").strip()
        existing_tx = next((item for item in data.get("transactions", []) if item["id"] == tx_id), None) if tx_id else None
        payload = canonical_transaction(
            {
                "id": tx_id or new_id("tx"),
                "date": request.form.get("date") or date.today().isoformat(),
                "title": request.form.get("title"),
                "amount": signed_amount_from_form(request.form.get("amount"), request.form.get("amount_mode"), default_mode="expense"),
                "category": ensure_category(data, resolved_category("category", default="Ohne Kategorie")) or "Ohne Kategorie",
                "paid": request.form.get("paid") == "on",
                "payment_method": normalize_payment_method(request.form.get("payment_method"), existing_tx.get("payment_method", "credit_card") if existing_tx else "credit_card"),
                "pot_id": request.form.get("pot_id") or "",
                "notes": request.form.get("notes") or "",
                "source": existing_tx.get("source", "manual") if existing_tx else "manual",
                "kind": existing_tx.get("kind", "manual") if existing_tx else "manual",
                "show_in_month": existing_tx.get("show_in_month", True) if existing_tx else True,
            }
        )
        replaced = False
        for index, tx in enumerate(data["transactions"]):
            if tx["id"] == payload["id"]:
                data["transactions"][index] = payload
                replaced = True
                break
        if not replaced:
            data["transactions"].append(payload)
        data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
        save_data(data)
        flash("Buchung gespeichert.")
    elif action.startswith("toggle_paid:"):
        tx_id = action.split(":", 1)[1]
        for tx in data["transactions"]:
            if tx["id"] == tx_id:
                tx["paid"] = not tx["paid"]
                break
        save_data(data)
        flash("Zahlungsstatus aktualisiert.")
    elif action == "mark_selected_paid":
        selected_ids = {(value or "").strip() for value in request.form.getlist("selected_tx_ids") if (value or "").strip()}
        updated_count = 0
        for tx in data["transactions"]:
            if tx["id"] in selected_ids and not tx["paid"]:
                tx["paid"] = True
                updated_count += 1
        if updated_count:
            save_data(data)
            flash(f"{updated_count} Buchung{'en' if updated_count != 1 else ''} als bezahlt markiert.")
        elif selected_ids:
            flash("Die ausgewählten Buchungen waren bereits bezahlt.")
        else:
            flash("Bitte zuerst mindestens eine Buchung auswählen.")
    elif action.startswith("delete_transaction:"):
        tx_id = action.split(":", 1)[1]
        existing_tx = next((tx for tx in data.get("transactions", []) if tx["id"] == tx_id), None)
        if existing_tx is None:
            flash("Buchung nicht gefunden.")
            return
        source = str(existing_tx.get("source") or "")
        push_to_trash(
            data,
            "transaction",
            existing_tx.get("title") or "Buchung",
            existing_tx,
            {"deleted_source": source if source.startswith("recurring:") else ""},
        )
        data["transactions"] = [tx for tx in data["transactions"] if tx["id"] != tx_id]
        if source.startswith("recurring:"):
            deleted_sources = set(data.get("deleted_recurring_sources", []))
            deleted_sources.add(source)
            data["deleted_recurring_sources"] = sorted(deleted_sources)
        save_data(data)
        flash("Buchung in den Papierkorb verschoben.")


def handle_recurring_post(data: dict[str, Any], month_key: str) -> None:
    action = (request.form.get("action") or "").strip()
    if action == "save_recurring":
        rec_id = (request.form.get("rec_id") or "").strip()
        existing_template = next((item for item in data.get("recurring_templates", []) if item["id"] == rec_id), None) if rec_id else None
        effective_from = parse_month(request.form.get("valid_from"), month_key)
        raw_amount_mode = request.form.get("amount_mode")
        if raw_amount_mode is None and existing_template is not None:
            raw_amount_mode = amount_mode_from_amount(existing_template.get("amount"), default="expense")
        payload = canonical_recurring(
            {
                "id": rec_id or new_id("rec"),
                "title": request.form.get("title"),
                "amount": signed_amount_from_form(request.form.get("amount"), raw_amount_mode, default_mode="expense"),
                "category": ensure_category(data, resolved_category("category", default="Fixkosten")) or "Fixkosten",
                "day": int(request.form.get("day") or "1"),
                "paid_default": request.form.get("paid_default") == "on",
                "payment_method": normalize_payment_method(request.form.get("payment_method"), "account"),
                "pot_id": request.form.get("pot_id") or "",
                "notes": request.form.get("notes") or "",
                "active": request.form.get("active") == "on" or not rec_id,
                "interval_months": int(request.form.get("interval_months") or "1"),
                "start_month": request.form.get("start_month") or date.today().strftime("%m"),
                "valid_from": effective_from,
                "valid_until": "",
            }
        )

        if existing_template is not None:
            old_valid_from = recurring_valid_from(existing_template)
            old_valid_until = recurring_valid_until(existing_template)
            if effective_from > old_valid_from:
                old_id = existing_template["id"]
                old_title = existing_template.get("title") or "Fixkosten-Vorlage"
                close_recurring_template_at(existing_template, effective_from)
                payload["id"] = new_id("rec")
                payload["valid_from"] = effective_from
                if old_valid_until and old_valid_until >= effective_from:
                    payload["valid_until"] = old_valid_until
                data.setdefault("recurring_templates", []).append(payload)
                removed_count = remove_recurring_transactions_from(data, old_id, effective_from)
                remove_deleted_recurring_markers_from(data, old_id, effective_from)
                data["recurring_templates"] = [canonical_recurring(item) for item in data.get("recurring_templates", [])]
                data["recurring_templates"].sort(key=lambda item: (item.get("valid_from", "1900-01"), item["day"], item["title"], item["id"]))
                ensure_month_generated(data, month_key)
                save_data(data)
                flash(f"Fixkosten-Vorlage ab {effective_from} als neue Version gespeichert. Alte Version „{old_title}“ bleibt bis {shift_month(effective_from, -1)} erhalten. {removed_count} zukünftige alte Monatsbuchungen entfernt.")
                return

            payload["id"] = existing_template["id"]
            payload["valid_from"] = old_valid_from
            payload["valid_until"] = old_valid_until
            replaced = False
            for index, item in enumerate(data["recurring_templates"]):
                if item["id"] == payload["id"]:
                    data["recurring_templates"][index] = payload
                    replaced = True
                    break
            changed_count, removed_count = sync_recurring_template_changes(data, payload, old_valid_from)
            data["recurring_templates"].sort(key=lambda item: (item.get("valid_from", "1900-01"), item["day"], item["title"], item["id"]))
            save_data(data)
            if changed_count or removed_count:
                flash(f"Fixkosten-Vorlage gespeichert. {changed_count} vorhandene Monatsbuchungen aktualisiert, {removed_count} nicht mehr passende entfernt.")
            else:
                flash("Fixkosten-Vorlage gespeichert.")
            return

        data.setdefault("recurring_templates", []).append(payload)
        data["recurring_templates"].sort(key=lambda item: (item.get("valid_from", "1900-01"), item["day"], item["title"], item["id"]))
        ensure_month_generated(data, month_key)
        save_data(data)
        flash(f"Fixkosten-Vorlage ab {effective_from} gespeichert.")
    elif action.startswith("toggle_recurring:"):
        rec_id = action.split(":", 1)[1]
        for item in data["recurring_templates"]:
            if item["id"] == rec_id:
                item["active"] = not item.get("active", True)
                break
        save_data(data)
        flash("Vorlage aktualisiert.")
    elif action.startswith("delete_recurring:"):
        rec_id = action.split(":", 1)[1]
        delete_from_month = parse_month(request.form.get("delete_from_month"), month_key)
        existing_template = next((item for item in data.get("recurring_templates", []) if item["id"] == rec_id), None)
        if existing_template is None:
            flash("Vorlage nicht gefunden.")
            return
        valid_from = recurring_valid_from(existing_template)
        valid_until = recurring_valid_until(existing_template)
        title = existing_template.get("title") or "Fixkosten-Vorlage"
        if valid_until and valid_until < delete_from_month:
            push_to_trash(data, "recurring", title, existing_template, {"removed_from_management_only": True})
            data["recurring_templates"] = [item for item in data.get("recurring_templates", []) if item["id"] != rec_id]
            save_data(data)
            flash(f"Beendete Fixkosten-Vorlage „{title}“ nur aus der Verwaltung entfernt. Alte Buchungen bleiben erhalten.")
            return
        removed_count = remove_recurring_transactions_from(data, rec_id, delete_from_month)
        remove_deleted_recurring_markers_from(data, rec_id, delete_from_month)
        if delete_from_month <= valid_from:
            prefix = f"recurring:{rec_id}:"
            related_transactions = [tx for tx in data.get("transactions", []) if str(tx.get("source") or "").startswith(prefix)]
            push_to_trash(
                data,
                "recurring",
                title,
                existing_template,
                {"transactions": related_transactions, "deleted_from_month": delete_from_month},
            )
            data["recurring_templates"] = [item for item in data["recurring_templates"] if item["id"] != rec_id]
            data["transactions"] = [tx for tx in data.get("transactions", []) if not str(tx.get("source") or "").startswith(prefix)]
            data["deleted_recurring_sources"] = [source for source in data.get("deleted_recurring_sources", []) if not str(source).startswith(prefix)]
            save_data(data)
            flash(f"Fixkosten-Vorlage ab {delete_from_month} gelöscht. {removed_count} Monatsbuchungen entfernt.")
            return

        close_recurring_template_at(existing_template, delete_from_month)
        data["recurring_templates"] = [canonical_recurring(item) for item in data.get("recurring_templates", [])]
        data["recurring_templates"].sort(key=lambda item: (item.get("valid_from", "1900-01"), item["day"], item["title"], item["id"]))
        save_data(data)
        flash(f"Fixkosten-Vorlage „{title}“ endet ab {delete_from_month}. Alte Monate bleiben erhalten. {removed_count} zukünftige Monatsbuchungen entfernt.")


def handle_pot_post(data: dict[str, Any]) -> None:
    action = (request.form.get("action") or "").strip()
    if action == "save_pot":
        pot_id = (request.form.get("pot_id") or "").strip()
        payload = canonical_pot({"id": pot_id or new_id("pot"), "name": request.form.get("name"), "color": request.form.get("color") or "#0f766e"})
        replaced = False
        for index, item in enumerate(data["pots"]):
            if item["id"] == payload["id"]:
                data["pots"][index] = payload
                replaced = True
                break
        if not replaced:
            data["pots"].append(payload)
        data["pots"].sort(key=lambda item: item["name"].lower())
        save_data(data)
        flash("Topf gespeichert.")
    elif action.startswith("delete_pot:"):
        pot_id = action.split(":", 1)[1]
        existing_pot = next((item for item in data.get("pots", []) if item["id"] == pot_id), None)
        if existing_pot is None:
            flash("Topf nicht gefunden.")
            return
        related_plans = [item for item in data.get("pot_plans", []) if item["pot_id"] == pot_id]
        related_transactions = [tx for tx in data.get("transactions", []) if tx.get("pot_id") == pot_id]
        push_to_trash(
            data,
            "pot",
            existing_pot.get("name") or "Topf",
            existing_pot,
            {"pot_plans": related_plans, "transactions": related_transactions},
        )
        data["pots"] = [item for item in data["pots"] if item["id"] != pot_id]
        for tx in data.get("transactions", []):
            if tx.get("pot_id") == pot_id:
                tx["pot_id"] = ""
        data["pot_plans"] = [item for item in data["pot_plans"] if item["pot_id"] != pot_id]
        save_data(data)
        flash("Topf in den Papierkorb verschoben.")
    elif action == "save_pot_plan":
        plan_id = (request.form.get("plan_id") or "").strip()
        payload = canonical_pot_plan(
            {
                "id": plan_id or new_id("plan"),
                "pot_id": request.form.get("pot_id_plan"),
                "month": request.form.get("month"),
                "amount": parse_amount(request.form.get("amount")),
            }
        )
        replaced = False
        for index, item in enumerate(data["pot_plans"]):
            if item["id"] == payload["id"]:
                data["pot_plans"][index] = payload
                replaced = True
                break
        if not replaced:
            data["pot_plans"].append(payload)
        data["pot_plans"].sort(key=lambda item: (item["month"], item["pot_id"]))
        save_data(data)
        flash("Zuweisung gespeichert.")
    elif action.startswith("delete_pot_plan:"):
        plan_id = action.split(":", 1)[1]
        data["pot_plans"] = [item for item in data["pot_plans"] if item["id"] != plan_id]
        save_data(data)
        flash("Zuweisung gelöscht.")
    elif action == "save_pot_payment":
        tx_id = (request.form.get("tx_id") or "").strip()
        pot_id = (request.form.get("pot_id_payment") or "").strip()
        amount = abs(parse_amount(request.form.get("amount")))
        direction = (request.form.get("direction") or "out").strip()
        show_in_month = request.form.get("show_in_month") == "on"
        payment_date = str(request.form.get("date") or default_payment_date(date.today().strftime("%Y-%m")))[:10]
        try:
            datetime.strptime(payment_date, "%Y-%m-%d")
        except ValueError:
            payment_date = date.today().isoformat()

        if not pot_id or find_pot(data, pot_id) is None:
            flash("Bitte einen gültigen Topf auswählen.")
            return
        if amount <= 0:
            flash("Bitte einen Betrag größer 0 eingeben.")
            return

        signed_amount = amount if direction == "in" else -amount
        default_title = f"Einzahlung {pot_name(data, pot_id)}" if signed_amount > 0 else f"Zahlung {pot_name(data, pot_id)}"
        default_category = "Topfeinzahlung" if signed_amount > 0 else "Topfzahlung"
        title = str(request.form.get("title") or "").strip() or default_title
        category = ensure_category(data, resolved_category("payment_category", default=default_category)) or default_category
        payload = canonical_transaction(
            {
                "id": tx_id or new_id("tx"),
                "date": payment_date,
                "title": title,
                "amount": signed_amount,
                "category": category,
                "paid": True,
                "pot_id": pot_id,
                "notes": request.form.get("notes") or "",
                "source": "pot_payment",
                "kind": "pot_payment" if signed_amount < 0 else "pot_deposit",
                "show_in_month": show_in_month,
            }
        )
        replaced = False
        for index, tx in enumerate(data["transactions"]):
            if tx["id"] == payload["id"] and str(tx.get("source") or "") == "pot_payment":
                data["transactions"][index] = payload
                replaced = True
                break
        if not replaced:
            data["transactions"].append(payload)
        data["transactions"].sort(key=lambda tx: (tx["date"], tx["title"], tx["id"]))
        save_data(data)
        flash("Topf-Bewegung gespeichert." if not replaced else "Topf-Bewegung aktualisiert.")
    elif action.startswith("delete_pot_payment:"):
        tx_id = action.split(":", 1)[1]
        existing_payment = next((tx for tx in data.get("transactions", []) if tx["id"] == tx_id and str(tx.get("source") or "") == "pot_payment"), None)
        if existing_payment is None:
            flash("Topf-Bewegung nicht gefunden.")
            return
        push_to_trash(data, "pot_payment", existing_payment.get("title") or "Topf-Bewegung", existing_payment)
        data["transactions"] = [
            tx
            for tx in data["transactions"]
            if not (tx["id"] == tx_id and str(tx.get("source") or "") == "pot_payment")
        ]
        save_data(data)
        flash("Topf-Bewegung in den Papierkorb verschoben.")




def inventory_variants_from_form(existing_item: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    existing_by_id = {
        str(variant.get("id") or ""): variant
        for variant in inventory_item_variants(existing_item or {})
        if str(variant.get("id") or "")
    }
    ids = request.form.getlist("variant_id")
    names = request.form.getlist("variant_name")
    quantities = request.form.getlist("variant_quantity")
    units = request.form.getlist("variant_unit")
    prices = request.form.getlist("variant_total_price")
    empty_weights = request.form.getlist("variant_empty_weight")
    notes = request.form.getlist("variant_notes")
    count = max(len(ids), len(names), len(quantities), len(units), len(prices), len(empty_weights), len(notes))
    variants: list[dict[str, Any]] = []

    def get(values: list[str], index: int, default: str = "") -> str:
        return str(values[index] if index < len(values) else default).strip()

    for index in range(count):
        variant_id = get(ids, index)
        existing = existing_by_id.get(variant_id, {})
        name_text = get(names, index)
        quantity_text = get(quantities, index)
        unit_text = get(units, index)
        price_text = get(prices, index)
        empty_weight_text = get(empty_weights, index)
        notes_text = get(notes, index)
        has_content = bool(variant_id or name_text or quantity_text or price_text or empty_weight_text or notes_text)
        if not has_content:
            continue
        variants.append(
            canonical_inventory_variant(
                {
                    "id": variant_id or new_id("stockvar"),
                    "name": name_text or existing.get("name") or f"Variante {len(variants) + 1}",
                    "quantity": parse_amount(quantity_text),
                    "unit": unit_text or existing.get("unit") or "Stück",
                    "total_price": parse_amount(price_text),
                    "empty_weight": empty_weight_text,
                    "notes": notes_text,
                },
                f"Variante {len(variants) + 1}",
            )
        )
    return variants


def handle_inventory_post(data: dict[str, Any], month_key: str) -> None:
    action = (request.form.get("delete_action") or request.form.get("action") or "").strip()
    if action == "save_inventory_item":
        item_id = (request.form.get("item_id") or "").strip()
        existing_item = next((row for row in data.get("inventory_items", []) if row["id"] == item_id), None)
        variants = inventory_variants_from_form(existing_item)
        if not variants:
            flash("Bitte mindestens eine Variante mit Menge und Preis eintragen.")
            return
        if any(float(variant.get("quantity") or 0.0) <= 0 or float(variant.get("total_price") or 0.0) <= 0 for variant in variants):
            flash("Bitte bei jeder Variante eine Menge und einen Gesamtpreis größer 0 eintragen.")
            return
        payload = canonical_inventory_item(
            {
                "id": item_id or new_id("stock"),
                "title": request.form.get("title"),
                "category": ensure_category(data, resolved_category("category", default="Lebensmittel")) or "Lebensmittel",
                "variants": variants,
                "start_month": request.form.get("start_month") or month_key,
                "notes": request.form.get("notes") or "",
                "active": request.form.get("active") == "on" or not item_id,
            }
        )
        replaced = False
        for index, item in enumerate(data.setdefault("inventory_items", [])):
            if item["id"] == payload["id"]:
                data["inventory_items"][index] = payload
                replaced = True
                break
        if not replaced:
            data.setdefault("inventory_items", []).append(payload)
        data["inventory_items"].sort(key=lambda item: item.get("title", "").lower())
        ensure_inventory_variant_references(data)
        inventory_resync_item_from_month(data, payload, payload.get("start_month") or month_key)
        save_data(data)
        flash("Vorratsposition gespeichert.")
    elif action == "add_inventory_purchase":
        item_id = (request.form.get("item_id") or "").strip()
        item = next((row for row in data.get("inventory_items", []) if row["id"] == item_id), None)
        if item is None:
            flash("Vorratsposition nicht gefunden.")
            return
        variant_id = (request.form.get("variant_id") or inventory_first_variant_id(item)).strip()
        variant = inventory_variant_by_id(item, variant_id)
        if variant is None:
            flash("Variante nicht gefunden.")
            return
        purchase_month = parse_month(request.form.get("purchase_month"), month_key)
        quantity = max(0.0, parse_amount(request.form.get("purchase_quantity")))
        total_price = max(0.0, parse_amount(request.form.get("purchase_total_price")))
        if quantity <= 0 or total_price <= 0:
            flash("Bitte Menge und Betrag für den Einkauf eintragen.")
            return
        purchase = canonical_inventory_purchase({
            "item_id": item_id,
            "variant_id": variant_id,
            "month": purchase_month,
            "quantity": quantity,
            "total_price": total_price,
            "notes": request.form.get("purchase_notes") or "",
        })
        data.setdefault("inventory_purchases", []).append(purchase)
        data["inventory_purchases"].sort(key=lambda row: (row["month"], row["item_id"], row.get("variant_id", ""), row["id"]))
        inventory_resync_item_from_month(data, item, purchase_month)
        save_data(data)
        flash("Weiterer Einkauf zum Vorrat hinzugefügt.")
    elif action.startswith("delete_inventory_purchase:"):
        purchase_id = action.split(":", 1)[1]
        purchase = next((row for row in data.get("inventory_purchases", []) if row.get("id") == purchase_id), None)
        if purchase is None:
            flash("Einkauf nicht gefunden.")
            return
        item = next((row for row in data.get("inventory_items", []) if row["id"] == purchase.get("item_id")), None)
        data["inventory_purchases"] = [row for row in data.get("inventory_purchases", []) if row.get("id") != purchase_id]
        if item is not None:
            inventory_resync_item_from_month(data, item, purchase.get("month") or month_key)
        save_data(data)
        flash("Einkauf aus dem Vorrat entfernt.")
    elif action == "save_inventory_count":
        item_id = (request.form.get("item_id") or "").strip()
        item = next((row for row in data.get("inventory_items", []) if row["id"] == item_id), None)
        if item is None:
            flash("Vorratsposition nicht gefunden.")
            return
        count_month = parse_month(request.form.get("count_month"), month_key)
        variant_ids = request.form.getlist("variant_id") or [inventory_first_variant_id(item)]
        end_quantities = request.form.getlist("end_quantity") or [request.form.get("end_quantity") or "0"]
        saved = 0
        for index, variant_id in enumerate(variant_ids):
            variant_id = str(variant_id or "").strip() or inventory_first_variant_id(item)
            if inventory_variant_by_id(item, variant_id) is None:
                continue
            raw_end_quantity = end_quantities[index] if index < len(end_quantities) else "0"
            end_quantity = max(0.0, parse_amount(raw_end_quantity))
            existing = inventory_count_for_month(data, item_id, count_month, variant_id)
            if existing is None:
                data.setdefault("inventory_counts", []).append(canonical_inventory_count({"item_id": item_id, "variant_id": variant_id, "month": count_month, "end_quantity": end_quantity}))
            else:
                existing["end_quantity"] = end_quantity
            saved += 1
        if saved <= 0:
            flash("Keine gültige Variante für den Endbestand gefunden.")
            return
        data["inventory_counts"].sort(key=lambda row: (row["month"], row["item_id"], row.get("variant_id", ""), row["id"]))
        inventory_sync_month_transaction(data, item, count_month)
        save_data(data)
        flash("Endbestand gespeichert und Monatsverbrauch aktualisiert.")

    elif action.startswith("delete_inventory_variant:"):
        parts = action.split(":", 2)
        if len(parts) != 3:
            flash("Variante nicht gefunden.")
            return
        item_id, variant_id = parts[1], parts[2]
        item = next((row for row in data.get("inventory_items", []) if row.get("id") == item_id), None)
        if item is None:
            flash("Vorratsposition nicht gefunden.")
            return
        variants = inventory_item_variants(item)
        variant = next((row for row in variants if str(row.get("id") or "") == variant_id), None)
        if variant is None:
            flash("Variante nicht gefunden.")
            return
        if len(variants) <= 1:
            flash("Die letzte Variante kann nicht einzeln gelöscht werden. Lösche stattdessen die ganze Vorratsposition.")
            return
        related_counts = [row for row in data.get("inventory_counts", []) if row.get("item_id") == item_id and row.get("variant_id") == variant_id]
        related_purchases = [row for row in data.get("inventory_purchases", []) if row.get("item_id") == item_id and row.get("variant_id") == variant_id]
        affected_months = [str(row.get("month") or "") for row in related_counts + related_purchases if str(row.get("month") or "")]
        transaction_months = [
            str(tx.get("source") or "").removeprefix(f"inventory:{item_id}:")
            for tx in data.get("transactions", [])
            if str(tx.get("source") or "").startswith(f"inventory:{item_id}:")
        ]
        affected_start = min([month for month in affected_months + transaction_months if month] or [str(item.get("start_month") or month_key)])
        item["variants"] = [row for row in variants if str(row.get("id") or "") != variant_id]
        updated_item = canonical_inventory_item(item)
        for index, existing_item in enumerate(data.get("inventory_items", [])):
            if existing_item.get("id") == item_id:
                data["inventory_items"][index] = updated_item
                break
        data["inventory_counts"] = [row for row in data.get("inventory_counts", []) if not (row.get("item_id") == item_id and row.get("variant_id") == variant_id)]
        data["inventory_purchases"] = [row for row in data.get("inventory_purchases", []) if not (row.get("item_id") == item_id and row.get("variant_id") == variant_id)]
        inventory_resync_item_from_month(data, updated_item, affected_start)
        save_data(data)
        flash(f"Variante {variant.get('name') or ''} gelöscht und Verbrauch neu berechnet.")
    elif action.startswith("toggle_inventory:"):
        item_id = action.split(":", 1)[1]
        for item in data.get("inventory_items", []):
            if item["id"] == item_id:
                item["active"] = not item.get("active", True)
                break
        save_data(data)
        flash("Vorratsposition aktualisiert.")
    elif action.startswith("delete_inventory:"):
        item_id = action.split(":", 1)[1]
        existing = next((row for row in data.get("inventory_items", []) if row["id"] == item_id), None)
        if existing is None:
            flash("Vorratsposition nicht gefunden.")
            return
        related_counts = [row for row in data.get("inventory_counts", []) if row.get("item_id") == item_id]
        related_purchases = [row for row in data.get("inventory_purchases", []) if row.get("item_id") == item_id]
        related_transactions = [tx for tx in data.get("transactions", []) if str(tx.get("source") or "").startswith(f"inventory:{item_id}:")]
        push_to_trash(data, "inventory", existing.get("title") or "Vorrat", existing, {"inventory_counts": related_counts, "inventory_purchases": related_purchases, "transactions": related_transactions})
        data["inventory_items"] = [row for row in data.get("inventory_items", []) if row["id"] != item_id]
        data["inventory_counts"] = [row for row in data.get("inventory_counts", []) if row.get("item_id") != item_id]
        data["inventory_purchases"] = [row for row in data.get("inventory_purchases", []) if row.get("item_id") != item_id]
        data["transactions"] = [tx for tx in data.get("transactions", []) if not str(tx.get("source") or "").startswith(f"inventory:{item_id}:")]
        save_data(data)
        flash("Vorratsposition in den Papierkorb verschoben.")


def category_usage_count(data: dict[str, Any], category: str) -> int:
    key = str(category or "").strip().casefold()
    if not key:
        return 0
    count = 0
    count += sum(1 for tx in data.get("transactions", []) if str(tx.get("category") or "").strip().casefold() == key)
    count += sum(1 for row in data.get("recurring_templates", []) if str(row.get("category") or "").strip().casefold() == key)
    count += sum(1 for row in data.get("annual_items", []) if str(row.get("group") or "").strip().casefold() == key)
    count += sum(1 for row in data.get("inventory_items", []) if str(row.get("category") or "").strip().casefold() == key)
    return count


def rename_category_everywhere(data: dict[str, Any], old: str, new: str) -> int:
    old_key = str(old or "").strip().casefold()
    new_value = str(new or "").strip()
    if not old_key or not new_value:
        return 0
    changed = 0
    for tx in data.get("transactions", []):
        if str(tx.get("category") or "").strip().casefold() == old_key:
            tx["category"] = new_value
            changed += 1
    for row in data.get("recurring_templates", []):
        if str(row.get("category") or "").strip().casefold() == old_key:
            row["category"] = new_value
            changed += 1
    for row in data.get("annual_items", []):
        if str(row.get("group") or "").strip().casefold() == old_key:
            row["group"] = new_value
            changed += 1
    for row in data.get("inventory_items", []):
        if str(row.get("category") or "").strip().casefold() == old_key:
            row["category"] = new_value
            changed += 1
    data["categories"] = [new_value if str(item).strip().casefold() == old_key else item for item in data.get("categories", [])]
    data["categories"] = collect_categories(data)
    return changed


def handle_admin_post(data: dict[str, Any], year: int) -> None:
    action = (request.form.get("action") or "").strip()
    if action in {"save_settings", "save_year_start_balance", "refresh_followup_years", "import_data", "restore_trash", "empty_trash"} or action.startswith("restore_trash:"):
        handle_annual_post(data, year)
    elif action == "rename_category":
        old = str(request.form.get("category_old") or "").strip()
        new = str(request.form.get("category_new") or "").strip()
        if not old or not new:
            flash("Bitte alte und neue Kategorie angeben.")
            return
        changed = rename_category_everywhere(data, old, new)
        save_data(data)
        flash(f"Kategorie umbenannt: {changed} Zuordnungen aktualisiert.")
    elif action.startswith("delete_category:"):
        category = action.split(":", 1)[1]
        usage = category_usage_count(data, category)
        if usage:
            flash(f"Kategorie „{category}“ wird noch {usage}× verwendet und wurde nicht gelöscht. Bitte erst umbenennen oder Zuordnungen ändern.")
            return
        key = category.casefold()
        data["categories"] = [item for item in data.get("categories", []) if str(item).strip().casefold() != key]
        save_data(data)
        flash("Kategorie gelöscht.")


def handle_annual_post(data: dict[str, Any], year: int) -> None:
    action = (request.form.get("action") or "").strip()
    if action == "save_settings":
        data["settings"]["monthly_budget_target"] = parse_amount(request.form.get("monthly_budget_target"), data["settings"]["monthly_budget_target"])
        data["settings"]["starting_balance"] = parse_amount(request.form.get("starting_balance"), data["settings"]["starting_balance"])
        data["settings"]["cash_balance"] = parse_amount(request.form.get("cash_balance"), data["settings"].get("cash_balance", 0.0))
        data["settings"]["app_title"] = str(request.form.get("app_title") or data["settings"]["app_title"]).strip() or data["settings"]["app_title"]
        save_data(data)
        flash("Einstellungen gespeichert.")
    elif action == "save_year_start_balance":
        target_year = int(request.form.get("year") or year)
        amount = parse_amount(request.form.get("year_start_balance"), get_year_start_balance(data, target_year))
        cash_amount = parse_amount(request.form.get("year_cash_balance"), get_year_cash_balance(data, target_year))
        set_year_balances(data, target_year, amount, cash_amount)
        save_data(data)
        flash(f"Startsaldo und Barbestand für {target_year} gespeichert.")
    elif action == "refresh_followup_years":
        source_year = int(request.form.get("year") or year)
        end_year = max(source_year + 1, int(request.form.get("end_year") or (source_year + 1)))
        source_start = parse_amount(request.form.get("year_start_balance"), get_year_start_balance(data, source_year))
        source_cash = parse_amount(request.form.get("year_cash_balance"), get_year_cash_balance(data, source_year))
        set_year_balances(data, source_year, source_start, source_cash)
        removed, created = replace_followup_items(data, source_year, end_year)
        updated_balances = refresh_followup_year_start_balances(data, source_year, end_year)
        save_data(data)
        flash(f"Folgejahre {source_year + 1} bis {end_year} aktualisiert: {created} Posten neu übernommen, {removed} alte Folgeposten ersetzt, {updated_balances} Jahresstarts inkl. Barbestand fortgeschrieben.")
    elif action == "save_annual":
        annual_id = (request.form.get("annual_id") or "").strip()
        repeat_mode = (request.form.get("repeat") or "none").strip()
        payload = canonical_annual(
            {
                "id": annual_id or new_id("annual"),
                "year": int(request.form.get("year") or year),
                "month": request.form.get("month"),
                "title": request.form.get("title"),
                "amount": signed_amount_from_form(request.form.get("amount"), request.form.get("amount_mode"), default_mode="expense"),
                "group": ensure_category(data, resolved_category("group", default="Planung")) or "Planung",
                "notes": request.form.get("notes"),
                "paid": request.form.get("paid") == "on",
                "is_cash": request.form.get("is_cash") == "on",
            }
        )
        replaced = False
        for index, item in enumerate(data["annual_items"]):
            if item["id"] == payload["id"]:
                data["annual_items"][index] = payload
                replaced = True
                break
        if not replaced:
            data["annual_items"].append(payload)

        created = 0
        copied_to_years = 0
        repeated_items = [payload]
        step = 1 if repeat_mode == "monthly" else 3 if repeat_mode == "quarterly" else 0
        if step:
            existing_keys = {
                (int(item["year"]), item["month"], item["title"].strip().lower(), round(float(item["amount"]), 2), item["group"].strip().lower())
                for item in data["annual_items"]
            }
            start_month = int(payload["month"])
            for month_num in range(start_month + step, 13, step):
                month_code = f"{month_num:02d}"
                key = (
                    int(payload["year"]),
                    month_code,
                    payload["title"].strip().lower(),
                    round(float(payload["amount"]), 2),
                    payload["group"].strip().lower(),
                )
                if key in existing_keys:
                    continue
                clone = canonical_annual(
                    {
                        "id": new_id("annual"),
                        "year": payload["year"],
                        "month": month_code,
                        "title": payload["title"],
                        "amount": payload["amount"],
                        "group": payload["group"],
                        "notes": payload.get("notes", ""),
                        "paid": False,
                        "is_cash": payload.get("is_cash", False),
                    }
                )
                data["annual_items"].append(clone)
                repeated_items.append(clone)
                existing_keys.add(key)
                created += 1

        target_years = []
        for raw_target_year in request.form.getlist("copy_to_years"):
            try:
                target_year = int(raw_target_year)
            except (TypeError, ValueError):
                continue
            if target_year != int(payload["year"]):
                target_years.append(target_year)
        target_years = sorted(set(target_years))
        if target_years:
            existing_keys = {
                (int(item["year"]), item["month"], item["title"].strip().lower(), round(float(item["amount"]), 2), item["group"].strip().lower())
                for item in data["annual_items"]
            }
            for target_year in target_years:
                for source_item in repeated_items:
                    key = (
                        target_year,
                        source_item["month"],
                        source_item["title"].strip().lower(),
                        round(float(source_item["amount"]), 2),
                        source_item["group"].strip().lower(),
                    )
                    if key in existing_keys:
                        continue
                    clone = canonical_annual(
                        {
                            "id": new_id("annual"),
                            "year": target_year,
                            "month": source_item["month"],
                            "title": source_item["title"],
                            "amount": source_item["amount"],
                            "group": source_item["group"],
                            "notes": source_item.get("notes", ""),
                            "paid": False,
                            "is_cash": source_item.get("is_cash", False),
                        }
                    )
                    data["annual_items"].append(clone)
                    existing_keys.add(key)
                    copied_to_years += 1

        data["annual_items"].sort(key=lambda item: (item["year"], item["month"], item["title"]))
        save_data(data)
        details = []
        if created:
            details.append(f"{created} Wiederholungen")
        if copied_to_years:
            details.append(f"{copied_to_years} Kopien in Zieljahren")
        if details:
            flash("Jahresposten gespeichert und " + ", ".join(details) + " angelegt.")
        else:
            flash("Jahresposten gespeichert.")
    elif action == "bulk_apply_annual_rollover":
        target_year = int(request.form.get("target_year") or year)
        selected_ids = list(dict.fromkeys(str(value).strip() for value in request.form.getlist("suggestion_ids") if str(value).strip()))
        if not selected_ids:
            flash("Bitte mindestens einen Hinweis auswählen.")
            return
        suggestion_map = annual_rollover_suggestion_map(data, target_year)
        updated = 0
        for suggestion_id in selected_ids:
            suggestion = suggestion_map.get(suggestion_id)
            if suggestion is None:
                continue
            changed, _ = apply_annual_rollover_suggestion(data, target_year, suggestion)
            if changed:
                updated += 1
        if updated:
            data["annual_items"].sort(key=lambda item: (item["year"], item["month"], item["title"], item["id"]))
            save_data(data)
            flash(f"{updated} ausgewählte Vorjahreshinweise wurden übernommen oder aktualisiert.")
        else:
            flash("Die ausgewählten Hinweise waren nicht mehr aktuell oder konnten nicht übernommen werden.")
    elif action in {"dismiss_annual_rollover", "bulk_dismiss_annual_rollover"}:
        target_year = int(request.form.get("target_year") or year)
        selected_ids = list(dict.fromkeys(str(value).strip() for value in request.form.getlist("suggestion_ids") if str(value).strip()))
        single_id = str(request.form.get("suggestion_id") or "").strip()
        if single_id:
            selected_ids.append(single_id)
        if not selected_ids:
            flash("Bitte mindestens einen Hinweis auswählen.")
            return
        active_map = annual_rollover_suggestion_map(data, target_year, include_dismissed=True)
        valid_ids = {suggestion_id for suggestion_id in selected_ids if suggestion_id in active_map}
        if not valid_ids:
            flash("Die ausgewählten Hinweise sind nicht mehr aktuell.")
            return
        dismissed = annual_rollover_dismissed_keys(data, target_year)
        before = len(dismissed)
        dismissed.update(valid_ids)
        set_annual_rollover_dismissed_keys(data, target_year, dismissed)
        save_data(data)
        added = len(dismissed) - before
        flash(f"{added} Hinweis{'e' if added != 1 else ''} wurde{'n' if added != 1 else ''} für {target_year} gelöscht. Die Jahresposten selbst bleiben unverändert.")
    elif action == "reset_annual_rollover_dismissals":
        target_year = int(request.form.get("target_year") or year)
        restored = len(annual_rollover_dismissed_keys(data, target_year))
        set_annual_rollover_dismissed_keys(data, target_year, set())
        save_data(data)
        if restored == 1:
            flash(f"Vorjahresabgleich für {target_year} neu geprüft. 1 gelöschter Hinweis wurde wieder zugelassen.")
        elif restored > 1:
            flash(f"Vorjahresabgleich für {target_year} neu geprüft. {restored} gelöschte Hinweise wurden wieder zugelassen.")
        else:
            flash(f"Vorjahresabgleich für {target_year} neu geprüft. Es waren keine gelöschten Hinweise gespeichert.")
    elif action == "copy_annual_from_previous":
        source_id = str(request.form.get("source_id") or "").strip()
        target_year = int(request.form.get("target_year") or year)
        source_item = next((item for item in data.get("annual_items", []) if item.get("id") == source_id), None)
        if source_item is None or int(source_item.get("year") or 0) != target_year - 1:
            flash("Vorjahresposten wurde nicht gefunden.")
            return
        source_key = annual_comparison_key(source_item)
        already_exists = any(
            int(item.get("year") or 0) == target_year and annual_comparison_key(item) == source_key
            for item in data.get("annual_items", [])
        )
        if already_exists:
            flash("Dieser Jahresposten ist im Zieljahr bereits vorhanden.")
            return
        clone = canonical_annual(
            {
                "id": new_id("annual"),
                "year": target_year,
                "month": source_item["month"],
                "title": source_item["title"],
                "amount": source_item["amount"],
                "group": source_item["group"],
                "notes": source_item.get("notes", ""),
                "paid": False,
                "is_cash": source_item.get("is_cash", False),
            }
        )
        data.setdefault("annual_items", []).append(clone)
        data["annual_items"].sort(key=lambda item: (item["year"], item["month"], item["title"], item["id"]))
        save_data(data)
        flash(f"„{clone['title']}“ wurde aus {target_year - 1} nach {target_year} übernommen.")
    elif action == "update_annual_amount_from_previous":
        source_id = str(request.form.get("source_id") or "").strip()
        target_id = str(request.form.get("target_id") or "").strip()
        target_year = int(request.form.get("target_year") or year)
        source_item = next((item for item in data.get("annual_items", []) if item.get("id") == source_id), None)
        target_item = next((item for item in data.get("annual_items", []) if item.get("id") == target_id), None)
        if source_item is None or target_item is None:
            flash("Der Vorjahresabgleich konnte nicht durchgeführt werden.")
            return
        if int(source_item.get("year") or 0) != target_year - 1 or int(target_item.get("year") or 0) != target_year:
            flash("Die ausgewählten Jahresposten passen nicht zum Vorjahresabgleich.")
            return
        if annual_comparison_key(source_item) != annual_comparison_key(target_item):
            flash("Die ausgewählten Jahresposten gehören nicht zur gleichen Position.")
            return
        target_item["amount"] = float(source_item.get("amount") or 0.0)
        save_data(data)
        flash(f"Betrag von „{target_item['title']}“ wurde auf den Wert aus {target_year - 1} aktualisiert.")
    elif action.startswith("toggle_annual:"):
        annual_id = action.split(":", 1)[1]
        for item in data["annual_items"]:
            if item["id"] == annual_id:
                item["paid"] = not item["paid"]
                break
        save_data(data)
        flash("Jahresposten aktualisiert.")
    elif action == "import_data":
        upload = request.files.get("import_file")
        if upload is None or not getattr(upload, "filename", ""):
            flash("Bitte zuerst eine JSON-Datei auswählen.")
            return
        try:
            imported_raw = json.load(upload.stream)
            imported_data = normalize_data(imported_raw)
        except Exception:
            flash("Die Import-Datei konnte nicht gelesen werden.")
            return
        write_backup_snapshot(normalize_data(data), force=True)
        save_data(imported_data)
        flash("Daten erfolgreich importiert.")
    elif action.startswith("restore_trash:"):
        trash_id = action.split(":", 1)[1]
        restored_label = restore_trash_item(data, trash_id)
        if restored_label is None:
            flash("Papierkorb-Eintrag nicht gefunden.")
            return
        save_data(data)
        flash(f"{restored_label} wiederhergestellt.")
    elif action == "empty_trash":
        deleted_count = len(data.get("trash", []))
        data["trash"] = []
        save_data(data)
        flash(f"Papierkorb geleert ({deleted_count} Einträge).")
    elif action.startswith("delete_annual:"):
        annual_id = action.split(":", 1)[1]
        existing_item = next((item for item in data.get("annual_items", []) if item["id"] == annual_id), None)
        if existing_item is None:
            flash("Jahresposten nicht gefunden.")
            return
        push_to_trash(data, "annual", existing_item.get("title") or "Jahresposten", existing_item)
        data["annual_items"] = [item for item in data["annual_items"] if item["id"] != annual_id]
        save_data(data)
        flash("Jahresposten in den Papierkorb verschoben.")


def edit_record(records: list[dict[str, Any]], rec_id: str) -> dict[str, Any] | None:
    for record in records:
        if record["id"] == rec_id:
            return copy.deepcopy(record)
    return None


def render_context(data: dict[str, Any], month_key: str, year: int) -> dict[str, Any]:
    generated = ensure_month_generated(data, month_key)
    if generated:
        save_data(data)
    txs = transactions_for_month(data, month_key)
    summary = summarize_month(txs, data["settings"]["monthly_budget_target"])
    recurring_sorted = sorted(data["recurring_templates"], key=lambda item: (item["day"], item["title"]))
    categories = category_totals(txs)
    category_options = collect_categories(data)
    pots = pot_summaries(data, month_key)
    annual_all = annual_items_for_year(data, year)
    annual = annual_items_for_year(data, year, month_key[5:7])
    annual_sum = annual_summary(data, year, month_key)
    annual_rows = annual_timeline(data, year)
    month_plans = sorted([item for item in data["pot_plans"] if item["month"] == month_key], key=lambda item: pot_name(data, item["pot_id"]).lower())
    open_unpaid = [tx for tx in txs if not tx["paid"]]
    selected_pot_id = (request.values.get("pot") or request.args.get("pot") or "").strip()
    selected_pot = find_pot(data, selected_pot_id) if selected_pot_id else None
    selected_pot_payments = pot_movements(data, selected_pot_id, month_key) if selected_pot else []
    selected_pot_summary = next((pot for pot in pots if pot["id"] == selected_pot_id), None)
    selected_category = normalize_category_filter(data, request.values.get("category") or request.args.get("category") or "")
    filtered_txs = filtered_transactions(txs, selected_category)
    inventory_rows = inventory_summaries(data, month_key)
    return {
        "app_title": data["settings"]["app_title"],
        "settings": data["settings"],
        "selected_month": month_key,
        "prev_month": shift_month(month_key, -1),
        "next_month": shift_month(month_key, 1),
        "month_transactions": txs,
        "filtered_transactions": filtered_txs,
        "selected_category": selected_category,
        "selected_category_label": category_filter_label(selected_category),
        "selected_category_is_no_fixed": is_no_fixed_category_filter(selected_category),
        "category_filter_no_fixed": CATEGORY_FILTER_NO_FIXED,
        "month_summary": summary,
        "category_rows": categories,
        "category_options": category_options,
        "pots": pots,
        "month_plans": month_plans,
        "year": year,
        "year_items": annual,
        "year_items_all": annual_all,
        "year_summary": annual_sum,
        "annual_timeline": annual_rows,
        "year_start_balance": get_year_start_balance(data, year),
        "year_cash_balance": get_year_cash_balance(data, year),
        "year_start_balance_custom": get_year_start_balance_entry(data, year) is not None,
        "default_year_start_balance": default_year_start_balance(data),
        "default_year_account_balance": default_year_account_balance(data),
        "default_year_cash_balance": default_year_cash_balance(data),
        "followup_target_year": year + 3,
        "recurring_templates": recurring_sorted,
        "months_available": month_options(data),
        "open_unpaid": open_unpaid,
        "pot_lookup": {pot["id"]: pot["name"] for pot in data["pots"]},
        "pots_raw": sorted(data["pots"], key=lambda item: item["name"].lower()),
        "inventory_items": sorted(data.get("inventory_items", []), key=lambda item: item.get("title", "").lower()),
        "inventory_counts": data.get("inventory_counts", []),
        "inventory_purchases": sorted(data.get("inventory_purchases", []), key=lambda row: (row.get("month", ""), row.get("item_id", ""), row.get("id", ""))),
        "inventory_rows": inventory_rows,
        "inventory_active_count": sum(1 for item in data.get("inventory_items", []) if item.get("active", True)),
        "inventory_rest_value": sum(row.get("rest_value", 0.0) for row in inventory_rows),
        "inventory_month_consumption": sum(row.get("consumed_amount", 0.0) for row in inventory_rows),
        "selected_pot": selected_pot,
        "selected_pot_summary": selected_pot_summary,
        "selected_pot_payments": selected_pot_payments,
        "backups": list_backups()[:8],
        "backup_count": len(list_backups()),
        "trash_items": data.get("trash", [])[:12],
        "trash_count": len(data.get("trash", [])),
        "current_year": date.today().year,
        "current_month": date.today().strftime("%Y-%m"),
    }


def pdf_styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("FinTitle", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#1f4f9f"), spaceAfter=8),
        "heading": ParagraphStyle("FinHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#17212f"), spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("FinBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=colors.HexColor("#17212f"), alignment=TA_LEFT),
        "small": ParagraphStyle("FinSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.3, leading=10.5, textColor=colors.HexColor("#66758a")),
    }


def pdf_table(rows: list[list[Any]], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f4f9f")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.6),
                ("LEADING", (0, 0), (-1, -1), 10.5),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#dde4ec")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde4ec")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    return table


def build_month_pdf(data: dict[str, Any], month_key: str) -> io.BytesIO:
    ensure_month_generated(data, month_key)
    txs = transactions_for_month(data, month_key)
    summary = summarize_month(txs, data["settings"]["monthly_budget_target"])
    category_rows = category_totals(txs)
    styles = pdf_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    story: list[Any] = []
    story.append(Paragraph(f"Finanzplanung - Monatsauswertung {format_month_label(month_key)}", styles["title"]))
    story.append(Paragraph(f"Erstellt für {data['settings']['app_title']}.", styles["small"]))
    story.append(Spacer(1, 8))

    summary_rows = [
        ["Kennzahl", "Wert"],
        ["Einnahmen", money(summary["income"])],
        ["Ausgaben", money(summary["expenses"])],
        ["Monatsergebnis", money(summary["monthly_result"])],
        ["Fixkosten", money(summary["fixed_expenses"])],
        ["Variable Ausgaben", money(summary["variable_expenses"])],
        ["Offene Buchungen", str(summary["unpaid_count"])],
        ["Offener Betrag", money(summary.get("unpaid_amount", 0.0))],
        ["Konto offen", money(summary.get("account_unpaid_amount", 0.0))],
    ]
    story.append(Paragraph("Monat im Überblick", styles["heading"]))
    story.append(pdf_table(summary_rows, [80 * mm, 85 * mm]))
    story.append(Spacer(1, 10))

    if category_rows:
        cat_rows = [["Kategorie", "Ausgaben"]] + [[row["category"], money(row["amount"])] for row in category_rows]
        story.append(Paragraph("Ausgaben nach Kategorie", styles["heading"]))
        story.append(pdf_table(cat_rows, [110 * mm, 55 * mm]))
        story.append(Spacer(1, 10))

    tx_rows: list[list[Any]] = [["Datum", "Titel", "Kategorie", "Status", "Zahlweg", "Betrag"]]
    for tx in txs:
        tx_rows.append([
            tx["date"],
            Paragraph(tx["title"], styles["body"]),
            tx["category"],
            "bezahlt" if tx["paid"] else "offen",
            payment_method_label_value(tx.get("payment_method")),
            money(tx["amount"]),
        ])
    if len(tx_rows) == 1:
        tx_rows.append([month_key + "-01", "Keine Buchungen", "-", "-", "-", money(0)])
    story.append(Paragraph("Buchungen", styles["heading"]))
    story.append(pdf_table(tx_rows, [22 * mm, 58 * mm, 30 * mm, 20 * mm, 28 * mm, 26 * mm]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def build_year_pdf(data: dict[str, Any], year: int, selected_month: str) -> io.BytesIO:
    timeline = annual_timeline(data, year)
    summary = annual_summary(data, year, selected_month)
    items = annual_items_for_year(data, year)
    styles = pdf_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    story: list[Any] = []
    story.append(Paragraph(f"Finanzplanung - Jahresauswertung {year}", styles["title"]))
    story.append(Paragraph(f"Stand bis {summary['current_label']} · Prognose bis Dezember.", styles["small"]))
    story.append(Spacer(1, 8))

    summary_rows = [
        ["Kennzahl", "Wert"],
        ["Startsaldo Jahr ohne Bar", money(get_year_start_balance(data, year))],
        ["Barbestand Jahr", money(get_year_cash_balance(data, year))],
        ["Start gesamt mit Bar", money(summary["opening_balance"])],
        [f"Stand bis {summary['current_label']} ohne Bar", money(summary["current_balance_without_cash"])],
        [f"Stand bis {summary['current_label']} mit Bar", money(summary["current_balance"])],
        ["Stand Ende Dezember ohne Bar", money(summary["forecast_balance_without_cash"])],
        ["Stand Ende Dezember mit Bar", money(summary["forecast_balance"])],
        ["Plan-Einnahmen", money(summary["income"])],
        ["Plan-Ausgaben", money(summary["expenses"])],
            ]
    story.append(Paragraph("Jahr im Überblick", styles["heading"]))
    story.append(pdf_table(summary_rows, [82 * mm, 83 * mm]))
    story.append(Spacer(1, 10))

    timeline_rows: list[list[Any]] = [["Monat", "Planung", "Stand o. Bar", "Stand m. Bar"]]
    for row in timeline:
        timeline_rows.append([row["label"], money(row["planned_total"]), money(row["cumulative_without_cash"]), money(row["cumulative_with_cash"])])
    story.append(Paragraph("Jahresverlauf", styles["heading"]))
    story.append(pdf_table(timeline_rows, [38 * mm, 40 * mm, 40 * mm, 47 * mm]))
    story.append(Spacer(1, 10))

    item_rows: list[list[Any]] = [["Monat", "Titel / Notiz", "Kategorie", "Bar", "Status", "Betrag"]]
    for item in items:
        title_text = f"<b>{html.escape(str(item['title']))}</b>"
        if item.get("notes"):
            title_text += f"<br/><font color='#66758a'>{html.escape(str(item['notes']))}</font>"
        item_rows.append([
            item["month"],
            Paragraph(title_text, styles["body"]),
            item["group"],
            "ja" if item.get("is_cash") else "nein",
            "erledigt" if item["paid"] else "offen",
            money(item["amount"]),
        ])
    if len(item_rows) == 1:
        item_rows.append([str(year), "Keine Jahresposten", "-", "-", "-", money(0)])
    story.append(Paragraph("Jahresposten", styles["heading"]))
    story.append(pdf_table(item_rows, [14 * mm, 62 * mm, 28 * mm, 14 * mm, 21 * mm, 26 * mm]))

    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route("/login", methods=["GET", "POST"])
def login() -> str:
    if not auth_enabled():
        return redirect(url_for("dashboard"))

    next_target = safe_next_target(request.values.get("next"))
    if request.method == "GET" and (is_authenticated() or not is_manually_locked()):
        return redirect(next_target)

    if request.method == "POST":
        submitted_password = str(request.form.get("password") or "")
        if secrets.compare_digest(submitted_password, WEB_PASSWORD):
            session.clear()
            session["finanz_authenticated"] = True
            session["finanz_locked"] = False
            flash("Webapp entsperrt.")
            return redirect(next_target)
        flash("Passwort falsch.")

    try:
        app_title = load_data()["settings"]["app_title"]
    except Exception:
        app_title = "Finanzen & Budget"
    return render_template("login.html", app_title=app_title, next_target=next_target, page="login")


@app.route("/logout", methods=["POST"])
def logout() -> Any:
    session.clear()
    if auth_enabled():
        session["finanz_locked"] = True
    flash("Webapp gesperrt.")
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def dashboard() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])
    if request.method == "POST":
        handle_transaction_post(data, month_key)
        return redirect(url_for("dashboard", month=month_key, year=year))
    context = render_context(data, month_key, year)
    due_this_month = [item for item in context["year_items"] if item["month"] == month_key[5:7]]
    return render_template("dashboard.html", page="dashboard", due_this_month=due_this_month, **context)


@app.route("/planning")
def planning_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.args.get("month"), fallback)
    year = int(request.args.get("year") or month_key[:4])
    context = render_context(data, month_key, year)
    return render_template("planning.html", page="planning", **context)


@app.route("/transactions", methods=["GET", "POST"])
def transactions_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])
    selected_category = normalize_category_filter(data, request.values.get("category") or request.args.get("category") or "")
    search_query = normalize_search_query(request.values.get("q") or request.args.get("q") or "")
    paid_filter = resolve_paid_filter(request.values.get("status") or request.args.get("status") or "")
    payment_filter = resolve_payment_filter(request.values.get("payment") or request.args.get("payment") or "")
    amount_min = parse_optional_amount(request.values.get("amount_min") or request.args.get("amount_min") or "")
    amount_max = parse_optional_amount(request.values.get("amount_max") or request.args.get("amount_max") or "")

    if request.method == "POST":
        handle_transaction_post(data, month_key)
        redirect_kwargs = {"month": month_key}
        if selected_category:
            redirect_kwargs["category"] = selected_category
        if search_query:
            redirect_kwargs["q"] = search_query
        if paid_filter != "all":
            redirect_kwargs["status"] = paid_filter
        if payment_filter != "all":
            redirect_kwargs["payment"] = payment_filter
        if amount_min is not None:
            redirect_kwargs["amount_min"] = amount_min
        if amount_max is not None:
            redirect_kwargs["amount_max"] = amount_max
        return redirect(url_for("transactions_page", **redirect_kwargs))

    context = render_context(data, month_key, year)
    edit_tx = edit_record(context["month_transactions"], request.args.get("edit_tx", ""))
    if edit_tx is None:
        edit_tx = {
            "id": "",
            "date": date.today().isoformat(),
            "title": "",
            "amount": "",
            "amount_mode": "expense",
            "category": "" if is_no_fixed_category_filter(selected_category) else selected_category,
            "paid": True,
            "payment_method": "credit_card",
            "pot_id": "",
            "notes": "",
        }
    else:
        edit_tx["amount_mode"] = amount_mode_from_amount(edit_tx.get("amount"), default="expense")
        edit_tx["amount"] = f"{abs(float(edit_tx.get('amount') or 0.0)):.2f}".replace(".", ",")
    filtered_transactions_list = [tx for tx in context["filtered_transactions"] if transaction_matches_search(data, tx, search_query)]
    filtered_transactions_list = filter_transactions_by_paid_status(filtered_transactions_list, paid_filter)
    filtered_transactions_list = filter_transactions_by_payment_method(filtered_transactions_list, payment_filter)
    filtered_transactions_list = filter_transactions_by_amount_range(filtered_transactions_list, amount_min, amount_max)
    context["filtered_transactions"] = filtered_transactions_list
    context["paid_filter"] = paid_filter
    context["payment_filter"] = payment_filter
    context["amount_min"] = "" if amount_min is None else str(amount_min).replace(".", ",")
    context["amount_max"] = "" if amount_max is None else str(amount_max).replace(".", ",")
    return render_template("transactions.html", page="transactions", edit_tx=edit_tx, search_query=search_query, **context)


@app.route("/recurring", methods=["GET", "POST"])
def recurring_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])
    search_query = normalize_search_query(request.values.get("q") or request.args.get("q") or "")
    recurring_status_filter = normalize_recurring_status_filter(request.values.get("status") or request.args.get("status"))

    if request.method == "POST":
        handle_recurring_post(data, month_key)
        redirect_kwargs = {"month": month_key, "status": recurring_status_filter}
        if search_query:
            redirect_kwargs["q"] = search_query
        return redirect(url_for("recurring_page", **redirect_kwargs))

    context = render_context(data, month_key, year)
    edit_recurring = edit_record(context["recurring_templates"], request.args.get("edit_rec", ""))
    if edit_recurring is None:
        edit_recurring = {
            "id": "",
            "title": "",
            "amount": "",
            "amount_mode": "expense",
            "category": "Fixkosten",
            "day": 1,
            "paid_default": False,
            "payment_method": "account",
            "pot_id": "",
            "notes": "",
            "active": True,
            "interval_months": 1,
            "start_month": month_key[5:7],
            "valid_from": month_key,
            "valid_until": "",
        }
    else:
        edit_recurring["amount_mode"] = amount_mode_from_amount(edit_recurring.get("amount"), default="expense")
        edit_recurring["amount"] = f"{abs(float(edit_recurring.get('amount') or 0.0)):.2f}".replace(".", ",")
        edit_recurring["valid_from"] = month_key
    filtered_recurring_templates = [
        item
        for item in context["recurring_templates"]
        if recurring_matches_search(data, item, search_query)
        and recurring_matches_status_filter(item, month_key, recurring_status_filter)
    ]
    recurring_status_counts = {
        "active": sum(1 for item in context["recurring_templates"] if recurring_matches_search(data, item, search_query) and recurring_matches_status_filter(item, month_key, "active")),
        "ended": sum(1 for item in context["recurring_templates"] if recurring_matches_search(data, item, search_query) and recurring_matches_status_filter(item, month_key, "ended")),
        "all": sum(1 for item in context["recurring_templates"] if recurring_matches_search(data, item, search_query)),
    }
    return render_template(
        "recurring.html",
        page="recurring",
        edit_recurring=edit_recurring,
        search_query=search_query,
        recurring_status_filter=recurring_status_filter,
        recurring_status_counts=recurring_status_counts,
        filtered_recurring_templates=filtered_recurring_templates,
        **context,
    )


@app.route("/pots", methods=["GET", "POST"])
def pots_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        handle_pot_post(data)
        if action == "save_pot_payment":
            target_pot = (request.form.get("pot_id_payment") or request.form.get("pot") or "").strip()
        else:
            target_pot = (request.form.get("pot") or request.form.get("pot_id_payment") or "").strip()
        return redirect(url_for("pots_page", month=month_key, pot=target_pot))

    context = render_context(data, month_key, year)
    edit_pot = edit_record(context["pots_raw"], request.args.get("edit_pot", ""))
    if edit_pot is None:
        edit_pot = {"id": "", "name": "", "color": "#0f766e"}
    payment_pot_id = context["selected_pot"]["id"] if context["selected_pot"] else (context["pots_raw"][0]["id"] if context["pots_raw"] else "")
    edit_payment = edit_record(context["selected_pot_payments"], request.args.get("edit_payment", ""))
    if edit_payment is None:
        payment_form = {
            "id": "",
            "date": default_payment_date(month_key),
            "title": "",
            "amount": "",
            "category": "Topfzahlung",
            "pot_id": payment_pot_id,
            "notes": "",
            "direction": "out",
            "show_in_month": True,
        }
    else:
        payment_form = {
            "id": edit_payment["id"],
            "date": edit_payment["date"],
            "title": edit_payment["title"],
            "amount": abs(float(edit_payment["amount"])),
            "category": edit_payment["category"],
            "pot_id": edit_payment["pot_id"],
            "notes": edit_payment.get("notes", ""),
            "direction": "in" if float(edit_payment["amount"]) > 0 else "out",
            "show_in_month": bool(edit_payment.get("show_in_month", True)),
        }
    return render_template("pots.html", page="pots", edit_pot=edit_pot, payment_form=payment_form, **context)


@app.route("/inventory", methods=["GET", "POST"])
def inventory_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])
    if request.method == "POST":
        handle_inventory_post(data, month_key)
        return redirect(url_for("inventory_page", month=month_key, year=year))
    context = render_context(data, month_key, year)
    edit_inventory = edit_record(context["inventory_items"], request.args.get("edit_inventory", ""))
    if edit_inventory is None:
        edit_inventory = {"id": "", "title": "", "category": "Lebensmittel", "quantity": "", "unit": "Stück", "total_price": "", "variants": [{"id": "", "name": "Standard", "quantity": "", "unit": "Stück", "total_price": "", "empty_weight": None, "notes": ""}], "start_month": month_key, "notes": "", "active": True}
    edit_inventory_variants = edit_inventory.get("variants") or [{"id": "", "name": "Standard", "quantity": "", "unit": "Stück", "total_price": "", "empty_weight": None, "notes": ""}]
    edit_inventory_purchases = [row for row in context["inventory_purchases"] if row.get("item_id") == edit_inventory.get("id")]
    return render_template("inventory.html", page="inventory", edit_inventory=edit_inventory, edit_inventory_variants=edit_inventory_variants, edit_inventory_purchases=edit_inventory_purchases, **context)


@app.route("/pot-movements")
def pot_movements_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.args.get("month"), fallback)
    year = int(request.args.get("year") or month_key[:4])
    context = render_context(data, month_key, year)
    if not context["selected_pot"] or not context["selected_pot_summary"]:
        flash("Bitte zuerst einen Topf auswählen.")
        return redirect(url_for("planning_page", month=month_key))
    return render_template("pot_movements.html", page="pot_movements", **context)


@app.route("/annual", methods=["GET", "POST"])
def annual_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])
    search_query = normalize_search_query(request.values.get("q") or request.args.get("q") or "")
    requested_scope = str(request.values.get("scope") or request.args.get("scope") or "").strip()
    annual_scope = "month" if requested_scope == "month" else "year"

    if request.method == "POST":
        handle_annual_post(data, year)
        redirect_kwargs = {"month": month_key, "year": year, "scope": annual_scope}
        if search_query:
            redirect_kwargs["q"] = search_query
        return redirect(url_for("annual_page", **redirect_kwargs))

    context = render_context(data, month_key, year)
    edit_annual = edit_record(context["year_items_all"], request.args.get("edit_annual", ""))
    if edit_annual is None:
        edit_annual = {"id": "", "year": year, "month": month_key[5:7], "title": "", "amount": "", "amount_mode": "expense", "group": "Planung", "notes": "", "paid": False, "is_cash": False}
    else:
        edit_annual["amount_mode"] = amount_mode_from_amount(edit_annual.get("amount"), default="expense")
        edit_annual["amount"] = f"{abs(float(edit_annual.get('amount') or 0.0)):.2f}".replace(".", ",")
    years = sorted(
        {item["year"] for item in data["annual_items"]}
        | {item["year"] for item in data.get("year_start_balances", [])}
        | set(range(date.today().year, date.today().year + 6))
        | {year, int(month_key[:4]), date.today().year}
    )
    base_year_items = context["year_items_all"] if annual_scope == "year" else context["year_items"]
    filtered_year_items = [item for item in base_year_items if annual_matches_search(item, search_query)]
    annual_list_label = f"gesamtes Jahr {year}" if annual_scope == "year" else format_month_label(month_key)
    rollover_suggestions = annual_rollover_suggestions(data, year)
    return render_template(
        "annual.html",
        page="annual",
        edit_annual=edit_annual,
        years=years,
        search_query=search_query,
        annual_scope=annual_scope,
        annual_list_label=annual_list_label,
        filtered_year_items=filtered_year_items,
        rollover_suggestions=rollover_suggestions,
        **context,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin_page() -> str:
    data = load_data()
    fallback = date.today().strftime("%Y-%m")
    month_key = parse_month(request.values.get("view_month") or request.values.get("month"), fallback)
    year = int(request.values.get("year") or month_key[:4])
    if request.method == "POST":
        handle_admin_post(data, year)
        return redirect(url_for("admin_page", month=month_key, year=year))
    context = render_context(data, month_key, year)
    years = sorted(
        {item["year"] for item in data["annual_items"]}
        | {item["year"] for item in data.get("year_start_balances", [])}
        | set(range(date.today().year, date.today().year + 6))
        | {year, int(month_key[:4]), date.today().year}
    )
    admin_category_rows = [{"name": cat, "usage": category_usage_count(data, cat)} for cat in collect_categories(data)]
    return render_template("admin.html", page="admin", years=years, admin_category_rows=admin_category_rows, **context)


@app.route("/health")
def health() -> Any:
    return {"status": "ok", "version": "0.1.49", "feature": "annual-rollover-bulk-review"}


@app.route("/export/month.pdf")
def export_month_pdf() -> Any:
    data = load_data()
    fallback = latest_known_month(data)
    month_key = parse_month(request.args.get("month"), fallback)
    pdf = build_month_pdf(data, month_key)
    filename = f"finanzplanung-monat-{month_key}.pdf"
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/export/year.pdf")
def export_year_pdf() -> Any:
    data = load_data()
    fallback = latest_known_month(data)
    month_key = parse_month(request.args.get("month"), fallback)
    year = int(request.args.get("year") or month_key[:4])
    pdf = build_year_pdf(data, year, month_key)
    filename = f"finanzplanung-jahr-{year}.pdf"
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/export/data.json")
def export_data_json() -> Any:
    data = normalize_data(load_data())
    buffer = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buffer.seek(0)
    filename = f"finanzplanung-daten-{datetime.now().strftime('%Y-%m-%d-%H%M')}.json"
    return send_file(buffer, mimetype="application/json", as_attachment=True, download_name=filename)


@app.route("/export/backup/<path:name>")
def export_backup_file(name: str) -> Any:
    backup_path = safe_backup_path(name)
    if backup_path is None:
        return redirect(url_for("admin_page"))
    return send_file(backup_path, mimetype="application/json", as_attachment=True, download_name=backup_path.name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
