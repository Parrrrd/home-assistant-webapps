#!/usr/bin/env python3
import copy
import hmac
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", "8147"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "webapp_uebersicht.json"
OPTIONS_FILE = DATA_DIR / "options.json"
INDEX_FILE = Path(__file__).with_name("index.html")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor").rstrip("/")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SETTINGS_LOCK = threading.Lock()

DEFAULT_ACCESS_PIN = "0000"
PROTECTED_SLUGS = {
    "local_inventurmanager",
    "inventurmanager",
    "local_finanzplanung",
    "finanzplanung",
}

DEFAULT_CATEGORIES = [
    {"id": "einkauf", "name": "Einkauf & Haushalt", "icon": "🛒"},
    {"id": "finanzen", "name": "Finanzen", "icon": "💶"},
    {"id": "arbeit", "name": "Arbeit & Vermietung", "icon": "🗂️"},
    {"id": "familie", "name": "Familie & Gesundheit", "icon": "👨‍👩‍👧‍👦"},
    {"id": "haus", "name": "Haus & Geräte", "icon": "🏠"},
    {"id": "freizeit", "name": "Freizeit & Reisen", "icon": "🌴"},
    {"id": "dienste", "name": "Dienste", "icon": "⚙️"},
]

DEFAULT_ASSIGNMENTS = {
    "local_amazon_preiswaechter": "einkauf",
    "local_drogerie_bestandsvergleich": "einkauf",
    "local_payback_coupons": "einkauf",
    "local_inventurmanager": "einkauf",
    "local_hellofresh_rezepte": "einkauf",
    "local_barf_portionsrechner": "einkauf",
    "local_finanzplanung": "finanzen",
    "local_kinderbudget": "finanzen",
    "local_stundenplanung": "arbeit",
    "local_kleinanzeigen_manager": "arbeit",
    "local_mietbewerber_manager": "arbeit",
    "local_mounjaro_tracker": "familie",
    "local_stayinformed_speiseplan": "familie",
    "local_terramow_protokoll": "haus",
    "local_mova_protokoll": "haus",
    "local_mova_og_protokoll": "haus",
    "local_center_parcs_preisueberwachung": "freizeit",
    "local_kicktipp_tipbot": "freizeit",
    "local_kicktipp_tipbot2": "freizeit",
    "local_jarvis_ai": "dienste",
    "local_webapp_uebersicht": "dienste",
}

DEFAULT_SETTINGS = {
    "schema_version": 1,
    "categories": DEFAULT_CATEGORIES,
    "assignments": DEFAULT_ASSIGNMENTS,
    "custom_items": [],
}


def get_access_pin():
    """Read the numeric dashboard PIN from Home Assistant app options."""
    try:
        raw = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    pin = str(raw.get("zugangs_pin", DEFAULT_ACCESS_PIN)).strip()
    if not re.fullmatch(r"[0-9]{1,12}", pin):
        print("Ungültiger zugangs_pin in /data/options.json; verwende Standard-PIN 0000", flush=True)
        return DEFAULT_ACCESS_PIN
    return pin


def is_protected_app(slug, name):
    """Return whether this dashboard card requires the configured PIN."""
    slug_key = str(slug or "").strip().casefold()
    name_key = str(name or "").strip().casefold()
    if slug_key in PROTECTED_SLUGS:
        return True
    if name_key.startswith("inventur"):
        return True
    return name_key in {"finanzen & budget", "finanzen und budget"}


def _safe_copy_default():
    return copy.deepcopy(DEFAULT_SETTINGS)


def _normalize_settings(raw):
    result = _safe_copy_default()
    if not isinstance(raw, dict):
        return result

    categories = raw.get("categories")
    if isinstance(categories, list):
        cleaned = []
        seen = set()
        for category in categories[:40]:
            if not isinstance(category, dict):
                continue
            cid = str(category.get("id", "")).strip()
            name = str(category.get("name", "")).strip()
            icon = str(category.get("icon", "📁")).strip()[:8] or "📁"
            if not cid or not name or cid in seen:
                continue
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid):
                continue
            seen.add(cid)
            cleaned.append({"id": cid, "name": name[:80], "icon": icon})
        if cleaned:
            result["categories"] = cleaned

    valid_category_ids = {x["id"] for x in result["categories"]}

    assignments = raw.get("assignments")
    if isinstance(assignments, dict):
        merged = {slug: cid for slug, cid in DEFAULT_ASSIGNMENTS.items() if cid in valid_category_ids}
        for slug, category_id in assignments.items():
            slug = str(slug).strip()[:160]
            category_id = str(category_id).strip()[:64]
            if slug and category_id in valid_category_ids:
                merged[slug] = category_id
            elif slug and category_id == "":
                merged.pop(slug, None)
        result["assignments"] = merged

    custom_items = raw.get("custom_items")
    if isinstance(custom_items, list):
        cleaned = []
        seen = set()
        for item in custom_items[:100]:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            category_id = str(item.get("category_id", "")).strip()
            description = str(item.get("description", "")).strip()
            icon = str(item.get("icon", "🔗")).strip()[:8] or "🔗"
            if not iid or iid in seen or not name or not url:
                continue
            if not re.fullmatch(r"custom_[A-Za-z0-9_-]{1,72}", iid):
                continue
            if category_id and category_id not in valid_category_ids:
                category_id = ""
            if not (url.startswith("http://") or url.startswith("https://")):
                continue
            seen.add(iid)
            cleaned.append({
                "id": iid,
                "name": name[:120],
                "url": url[:1000],
                "description": description[:300],
                "icon": icon,
                "category_id": category_id,
            })
        result["custom_items"] = cleaned

    return result


def load_settings():
    with SETTINGS_LOCK:
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = None
        settings = _normalize_settings(raw)
        if raw is None:
            save_settings_unlocked(settings)
        return settings


def save_settings_unlocked(settings):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_settings(settings)
    fd, tmp_name = tempfile.mkstemp(prefix="webapp_uebersicht_", suffix=".json", dir=str(DATA_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, SETTINGS_FILE)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return normalized


def save_settings(settings):
    with SETTINGS_LOCK:
        return save_settings_unlocked(settings)


def supervisor_get(path, timeout=4):
    if not TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt")
    request = urllib.request.Request(
        SUPERVISOR_URL + path,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            "User-Agent": "webapp-uebersicht/0.1.3",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Supervisor HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Supervisor nicht erreichbar: {exc}") from exc

    if isinstance(payload, dict) and payload.get("result") == "error":
        raise RuntimeError(str(payload.get("message") or "Supervisor-Fehler"))
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _extract_addon_list(data):
    if isinstance(data, dict):
        addons = data.get("addons")
        if isinstance(addons, list):
            return addons
    if isinstance(data, list):
        return data
    return []


def _effective_port(network):
    if not isinstance(network, dict):
        return None
    for _container_port, host_port in network.items():
        if host_port in (None, "", 0, "0"):
            continue
        try:
            return int(host_port)
        except (TypeError, ValueError):
            continue
    return None


def _fetch_info(slug):
    try:
        info = supervisor_get(f"/addons/{urllib.parse.quote(slug, safe='')}/info", timeout=3)
        return slug, info if isinstance(info, dict) else {}, None
    except Exception as exc:  # noqa: BLE001 - one failed app must not break the dashboard
        return slug, {}, str(exc)


def get_local_apps():
    data = supervisor_get("/addons", timeout=5)
    addons = _extract_addon_list(data)
    local = []
    for addon in addons:
        if not isinstance(addon, dict):
            continue
        if addon.get("repository") != "local":
            continue
        if addon.get("version") is None and addon.get("installed") is False:
            continue
        local.append(dict(addon))

    info_by_slug = {}
    errors = {}
    if local:
        workers = min(8, len(local))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_fetch_info, str(addon.get("slug", ""))) for addon in local]
            for future in as_completed(futures):
                slug, info, error = future.result()
                info_by_slug[slug] = info
                if error:
                    errors[slug] = error

    result = []
    for addon in local:
        slug = str(addon.get("slug", ""))
        info = info_by_slug.get(slug, {})
        network = info.get("network") if isinstance(info, dict) else None
        host_port = _effective_port(network)
        webui = info.get("webui") if isinstance(info, dict) else None
        app_name = str(addon.get("name") or slug)
        result.append({
            "slug": slug,
            "name": app_name,
            "description": str(addon.get("description") or ""),
            "version": addon.get("version"),
            "version_latest": addon.get("version_latest"),
            "update_available": bool(addon.get("update_available")),
            "state": str(addon.get("state") or "unknown"),
            "repository": addon.get("repository"),
            "webui": webui if isinstance(webui, str) else None,
            "host_port": host_port,
            "ingress": bool(info.get("ingress")) if isinstance(info, dict) else False,
            "ingress_url": info.get("ingress_url") if isinstance(info, dict) and isinstance(info.get("ingress_url"), str) else None,
            "protected": is_protected_app(slug, app_name),
            "info_error": errors.get(slug),
        })

    result.sort(key=lambda x: x["name"].casefold())
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "WebAppUebersicht/0.1.3"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _send(self, status, body, content_type="application/json; charset=utf-8", extra_headers=None):
        if isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _path(self):
        path = urllib.parse.urlsplit(self.path).path
        return path.rstrip("/") or "/"

    def do_GET(self):
        path = self._path()
        if path == "/health":
            self._json(200, {"ok": True, "version": "0.1.3"})
            return
        if path == "/api/settings":
            self._json(200, {"ok": True, "settings": load_settings()})
            return
        if path == "/api/apps":
            try:
                apps = get_local_apps()
                self._json(200, {"ok": True, "apps": apps})
            except Exception as exc:  # noqa: BLE001
                self._json(503, {"ok": False, "error": str(exc), "apps": []})
            return
        if path == "/api/overview":
            settings = load_settings()
            try:
                apps = get_local_apps()
                self._json(200, {"ok": True, "apps": apps, "settings": settings})
            except Exception as exc:  # noqa: BLE001
                self._json(503, {"ok": False, "error": str(exc), "apps": [], "settings": settings})
            return
        if path == "/":
            try:
                html = INDEX_FILE.read_bytes()
            except OSError as exc:
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._send(200, html, "text/html; charset=utf-8")
            return
        self._json(404, {"ok": False, "error": "Nicht gefunden"})

    def do_POST(self):
        path = self._path()
        if path != "/api/unlock":
            self._json(404, {"ok": False, "error": "Nicht gefunden"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 10_000:
            self._json(400, {"ok": False, "error": "Ungültige Datenmenge"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "Ungültiges JSON"})
            return
        pin = str(payload.get("pin", "")) if isinstance(payload, dict) else ""
        if not re.fullmatch(r"[0-9]{1,12}", pin):
            self._json(401, {"ok": False, "error": "PIN falsch"})
            return
        if not hmac.compare_digest(pin, get_access_pin()):
            self._json(401, {"ok": False, "error": "PIN falsch"})
            return
        self._json(200, {"ok": True})

    def do_PUT(self):
        path = self._path()
        if path != "/api/settings":
            self._json(404, {"ok": False, "error": "Nicht gefunden"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 200_000:
            self._json(400, {"ok": False, "error": "Ungültige Datenmenge"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "Ungültiges JSON"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "Objekt erwartet"})
            return
        settings = save_settings(payload)
        self._json(200, {"ok": True, "settings": settings})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_settings()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"WebApp Übersicht 0.1.3 läuft auf 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
