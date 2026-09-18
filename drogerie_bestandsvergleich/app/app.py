from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

from playwright.sync_api import sync_playwright

APP_VERSION = "0.1.3"
APP_NAME = "Drogerie Bestandsvergleich"
PORT = 8146
DB_PATH = Path(os.environ.get("DROGERIE_DB", "/data/drogerie_bestandsvergleich.sqlite3"))
USER_AGENT = f"HomeAssistant-DrogerieBestandsvergleich/{APP_VERSION}"
DM_MCP_URL = "https://mcp.dm.de/mcp"
DM_MCP_PROTOCOL = "2025-06-18"
DM_SEARCH_FALLBACK_URL = "https://product-search.services.dmtech.com/de/search?query={query}"
DM_STOCK_URL = "https://products.dm.de/availability/api/v2/map/basic/DE/{dan}/{stores}"
DM_DETAIL_URL = "https://products.dm.de/product/products/detail/DE/dan/{dan}"
ROSSMANN_HOME_URL = "https://www.rossmann.de/de/"
ROSSMANN_STOCK_URL = "https://www.rossmann.de/storefinder/.rest/store?dan={dan}&q={query}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("drogerie")
DB_LOCK = threading.RLock()

DM_STORES = [
    ("Hannoversche Straße", "Hannoversche Straße 90, 49084 Osnabrück", "D3HK", "https://www.dm.de/store/d3hk/osnabrueck"),
    ("Carl-Fischer-Straße", "Carl-Fischer-Straße 1, 49084 Osnabrück", "D5EJ", "https://www.dm.de/store/d5ej/osnabrueck/carl-fischer-strasse-1"),
    ("Pagenstecherstraße", "Pagenstecherstraße 133, 49090 Osnabrück", "D386", "https://www.dm.de/store/d386/osnabrueck"),
    ("Bramscher Straße", "Bramscher Straße 159, 49088 Osnabrück", "D2KA", "https://www.dm.de/store/d2ka/osnabrueck/bramscher-strasse-159"),
    ("Weidencarrée", "Weidenstraße 20, 49080 Osnabrück", "D3CH", "https://www.dm.de/store/d3ch/osnabrueck"),
    ("Hellern", "Lengericher Landstraße 2, 49078 Osnabrück", "D4JG", "https://www.dm.de/store/d4jg/osnabrueck"),
]

ROSSMANN_STORES = [
    ("Bad Essen", "Lerchenstraße 16, 49152 Bad Essen", "2242", "https://www.rossmann.de/de/filialen/niedersachsen/bad-essen/lerchenstr--16.html"),
    ("Bohmte", "Osnabrücker Straße 4 A, 49163 Bohmte", "3998", "https://www.rossmann.de/de/filialen/niedersachsen/bohmte/osnabruecker-str--4-a.html"),
    ("Belm", "Marktring 18-22, 49191 Belm", "3211", "https://www.rossmann.de/de/filialen/niedersachsen/belm/marktring-18-22.html"),
    ("Mindener Straße", "Mindener Straße 114, 49084 Osnabrück", "3515", "https://www.rossmann.de/de/filialen/niedersachsen/osnabrueck/mindener-str--114.html"),
    ("Georgsmarienhütte", "Am Rathaus 16, 49124 Georgsmarienhütte", "3212", "https://www.rossmann.de/de/filialen/niedersachsen/georgsmarienhuette/am-rathaus-16.html"),
]

DM_PRODUCTS = [
    ("Zewa", "Toilettenpapier Ultra Smart 4-lagig (4x280 Blatt), 4 St", "Zewa Toilettenpapier Ultra Smart 4 lagig 4x280 Blatt", "", "", 3.95),
    ("dmBio", "Trockenfrüchte, Pflaumen entsteint, 200 g", "dmBio Pflaumen entsteint 200 g", "", "", 2.65),
    ("alverde NATURKOSMETIK", "Rasiergel sensitiv Aloe Vera & Kamille, 150 ml", "alverde Rasiergel sensitiv Aloe Vera Kamille 150 ml", "", "", 2.25),
    ("Outdoor Freakz", "Wattestäbchen Bambus, 100 St", "Outdoor Freakz Wattestäbchen Bambus 100", "", "", 1.25),
    ("Denkmit", "Colorwaschmittel Pulver Ultra Sensitiv, 20 WL", "Denkmit Colorwaschmittel Pulver Ultra Sensitiv 20 WL", "", "", 3.45),
    ("dmBio", "Trockenfrüchte, Feigen, 350 g", "dmBio Trockenfrüchte Feigen 350 g", "", "", 3.75),
    ("Denkmit", "Vollwaschmittel Pulver Ultra Sensitive, 20 WL", "Denkmit Vollwaschmittel Pulver Ultra Sensitive 20 WL", "", "", 3.45),
    ("SUNDANCE", "Sonnenspray Kids MED ultra sensitiv, LSF 50+, 200 ml", "SUNDANCE Sonnenspray Kids MED ultra sensitiv LSF 50 200 ml", "", "", None),
]

ROSSMANN_PRODUCTS = [
    ("enerBiO", "Haferdrinkpulver, 300 g", "enerBiO Haferdrinkpulver 300 g", "145536", "4305615996370", "https://www.rossmann.de/de/lebensmittel-enerbio-haferdrinkpulver/p/4305615996370", 4.99),
    ("Zewa", "Toilettenpapier Ultra Smart, 4 Rollen à 280 Blatt", "Zewa Toilettenpapier Ultra Smart 4 Rollen 280 Blatt", "117409", "7322541411828", "https://www.rossmann.de/de/haushalt-zewa-toilettenpapier-ultra-smart/p/7322541411828", 3.99),
    ("Hidrofugal", "SENSITIV Anti-Transpirant Roll-on, 50 ml", "Hidrofugal SENSITIV Anti-Transpirant Roll-on 50 ml", "215872", "0000042495581", "https://www.rossmann.de/de/pflege-und-duft-hidrofugal-sensitiv-anti-transpirant-roll-on/p/0000042495581", 4.49),
    ("everdrop", "Spülmaschinen-Tabs classic, 54 St", "everdrop Spülmaschinen Tabs classic", "160405", "4262459711609", "https://www.rossmann.de/de/haushalt-everdrop-spuelmaschinen-tabs-classic/p/4262459711609", 9.49),
    ("Alterra", "Mundspülung Bio-Minze, 450 ml", "Alterra Mundspülung Bio-Minze", "031552", "4305615607665", "https://www.rossmann.de/de/gesundheit-alterra-mundspuelung-bio-minze/p/4305615607665", 2.99),
    ("Inlead", "Squeeze Syrup Waldmeister, 65 ml", "Inlead Squeeze Syrup Waldmeister", "213910", "4262424462352", "https://www.rossmann.de/de/lebensmittel-inlead-squeeze-syrup-waldmeister/p/4262424462352", 4.99),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with DB_LOCK, connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL CHECK(chain IN ('dm','rossmann')),
                name TEXT NOT NULL,
                address TEXT NOT NULL DEFAULT '',
                external_id TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(chain, name)
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL CHECK(chain IN ('dm','rossmann')),
                brand TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                search_query TEXT NOT NULL DEFAULT '',
                external_id TEXT NOT NULL DEFAULT '',
                ean TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                reference_price REAL,
                active INTEGER NOT NULL DEFAULT 1,
                last_resolved_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(chain, name)
            );
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL,
                created_at TEXT NOT NULL,
                product_count INTEGER NOT NULL,
                store_count INTEGER NOT NULL,
                ok INTEGER NOT NULL,
                message TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        seeded = conn.execute("SELECT value FROM meta WHERE key='seed_v1'").fetchone()
        if not seeded:
            for idx, (name, address, ext, url) in enumerate(DM_STORES):
                conn.execute(
                    "INSERT OR IGNORE INTO stores(chain,name,address,external_id,url,sort_order,created_at) VALUES(?,?,?,?,?,?,?)",
                    ("dm", name, address, ext, url, idx, utc_now()),
                )
            for idx, (name, address, ext, url) in enumerate(ROSSMANN_STORES):
                conn.execute(
                    "INSERT OR IGNORE INTO stores(chain,name,address,external_id,url,sort_order,created_at) VALUES(?,?,?,?,?,?,?)",
                    ("rossmann", name, address, ext, url, idx, utc_now()),
                )
            for brand, name, query, ean, url, price in DM_PRODUCTS:
                conn.execute(
                    "INSERT OR IGNORE INTO products(chain,brand,name,search_query,ean,url,reference_price,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("dm", brand, name, query, ean, url, price, utc_now()),
                )
            for brand, name, query, dan, ean, url, price in ROSSMANN_PRODUCTS:
                conn.execute(
                    "INSERT OR IGNORE INTO products(chain,brand,name,search_query,external_id,ean,url,reference_price,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    ("rossmann", brand, name, query, dan, ean, url, price, utc_now()),
                )
            conn.execute("INSERT INTO meta(key,value) VALUES('seed_v1','1')")

        migrated = conn.execute("SELECT value FROM meta WHERE key='rossmann_live_v1'").fetchone()
        if not migrated:
            store_ids = {name: ext for name, _address, ext, _url in ROSSMANN_STORES}
            for name, ext in store_ids.items():
                conn.execute(
                    "UPDATE stores SET external_id=? WHERE chain='rossmann' AND name=? AND (external_id='' OR external_id NOT GLOB '[0-9]*')",
                    (ext, name),
                )
            product_ids = {ean: dan for _brand, _name, _query, dan, ean, _url, _price in ROSSMANN_PRODUCTS}
            for ean, dan in product_ids.items():
                conn.execute(
                    "UPDATE products SET external_id=? WHERE chain='rossmann' AND ean=? AND (external_id='' OR external_id IS NULL)",
                    (dan, ean),
                )
            conn.execute("INSERT INTO meta(key,value) VALUES('rossmann_live_v1','1')")

        # 0.1.3: der ursprünglich nur per Suchtext angelegte SUNDANCE-Artikel wird
        # mit der eindeutigen aktuellen dm-DAN/GTIN/Produkt-URL ergänzt. Bereits
        # manuell sauber zugeordnete Einträge werden nicht überschrieben.
        sundance_fix = conn.execute("SELECT value FROM meta WHERE key='dm_sundance_013'").fetchone()
        if not sundance_fix:
            conn.execute(
                """
                UPDATE products
                   SET external_id=CASE WHEN external_id IS NULL OR external_id='' THEN '1336429' ELSE external_id END,
                       ean=CASE WHEN ean IS NULL OR ean='' THEN '4066447786514' ELSE ean END,
                       url=CASE WHEN url IS NULL OR url='' THEN 'https://www.dm.de/p/d/1336429/sundance-sundance-med-kids-ultra-sensitiv-sonnenspray-lsf-50' ELSE url END,
                       reference_price=CASE WHEN reference_price IS NULL THEN 7.25 ELSE reference_price END,
                       last_error=NULL
                 WHERE chain='dm'
                   AND brand='SUNDANCE'
                   AND name LIKE '%Kids%MED%ultra%sensitiv%LSF%50%'
                """
            )
            conn.execute("INSERT INTO meta(key,value) VALUES('dm_sundance_013','1')")
        conn.commit()


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def get_stores(chain: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return [rowdict(r) for r in conn.execute("SELECT * FROM stores WHERE chain=? ORDER BY sort_order,id", (chain,)).fetchall()]


def get_products(chain: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return [rowdict(r) for r in conn.execute("SELECT * FROM products WHERE chain=? ORDER BY brand COLLATE NOCASE,name COLLATE NOCASE,id", (chain,)).fetchall()]


def http_json(url: str, timeout: int = 15, retries: int = 1) -> Any:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8", errors="replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(str(last) if last else "HTTP-Fehler")


def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_dicts(value)


def norm(text: str) -> str:
    text = html.unescape(str(text or "")).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def overlap_score(query: str, title: str) -> float:
    q = [x for x in norm(query).split() if len(x) > 1]
    if not q:
        return 0.0
    t = set(norm(title).split())
    return sum(1 for token in q if token in t) / len(q)


def pick_first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    lower = {str(k).lower(): v for k, v in d.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value not in (None, "", [], {}):
            return value
    return None


def parse_mcp_http_body(raw: bytes, content_type: str = "") -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    if "text/event-stream" not in str(content_type).lower():
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise RuntimeError("dm MCP lieferte keine JSON-RPC-Antwort.")
        return obj

    data_lines: list[str] = []
    messages: list[dict[str, Any]] = []

    def flush() -> None:
        if not data_lines:
            return
        payload = "\n".join(data_lines).strip()
        data_lines.clear()
        if not payload or payload == "[DONE]":
            return
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return
        if isinstance(obj, dict):
            messages.append(obj)

    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip():
            flush()
    flush()
    if not messages:
        raise RuntimeError("dm MCP lieferte keine auswertbare SSE-Antwort.")
    for message in reversed(messages):
        if "result" in message or "error" in message:
            return message
    return messages[-1]


def dm_mcp_post(message: dict[str, Any], session_id: str = "", expect_response: bool = True) -> tuple[dict[str, Any], str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
        headers["MCP-Protocol-Version"] = DM_MCP_PROTOCOL
    request = urllib.request.Request(
        DM_MCP_URL,
        data=json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            next_session = response.headers.get("Mcp-Session-Id") or session_id
            raw = response.read()
            if not expect_response and not raw:
                return {}, next_session
            return parse_mcp_http_body(raw, response.headers.get("Content-Type") or ""), next_session
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"dm MCP HTTP {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"dm MCP nicht erreichbar: {exc}") from exc


def dm_mcp_close(session_id: str) -> None:
    if not session_id:
        return
    try:
        request = urllib.request.Request(
            DM_MCP_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
                "MCP-Protocol-Version": DM_MCP_PROTOCOL,
            },
            method="DELETE",
        )
        urllib.request.urlopen(request, timeout=5).close()
    except Exception:
        pass


def dm_price_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "amount", "price", "current"):
            if key in value:
                result = dm_price_value(value.get(key))
                if result is not None:
                    return result
    if isinstance(value, str):
        match = re.search(r"\d+(?:[.,]\d+)?", value.replace(" ", ""))
        if match:
            try:
                return float(match.group(0).replace(",", "."))
            except ValueError:
                return None
    return None


def dm_candidate_from_obj(obj: dict[str, Any]) -> dict[str, Any] | None:
    dan = pick_first(obj, ("dan", "productDan", "product_dan", "productId", "product_id"))
    title = pick_first(obj, ("title", "name", "productName", "displayName", "product_name"))
    if dan is None or not title:
        return None
    dan_text = re.sub(r"\D", "", str(dan))
    if not re.fullmatch(r"\d{3,12}", dan_text):
        return None
    brand_raw = pick_first(obj, ("brand", "brandName", "manufacturer")) or ""
    if isinstance(brand_raw, dict):
        brand_raw = pick_first(brand_raw, ("name", "title", "label")) or ""
    gtin = pick_first(obj, ("gtin", "ean", "gtin13", "barcode")) or ""
    url = pick_first(obj, ("appLink", "url", "productUrl", "canonicalUrl", "webUrl")) or ""
    price = dm_price_value(pick_first(obj, ("price", "currentPrice", "salesPrice")))
    return {
        "dan": dan_text,
        "title": str(title),
        "brand": str(brand_raw),
        "gtin": re.sub(r"\D", "", str(gtin)),
        "url": str(url),
        "price": price,
        "raw": obj,
    }


def dm_candidates_from_mcp_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("error"):
        error = response.get("error")
        if isinstance(error, dict):
            raise RuntimeError(str(error.get("message") or error))
        raise RuntimeError(str(error))
    result = response.get("result")
    if not isinstance(result, dict):
        return []

    roots: list[Any] = [result]
    for item in result.get("content", []) if isinstance(result.get("content"), list) else []:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        stripped = text.strip()
        if stripped[:1] in ("{", "["):
            try:
                roots.append(json.loads(stripped))
            except json.JSONDecodeError:
                pass

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for obj in walk_dicts(root):
            candidate = dm_candidate_from_obj(obj)
            if not candidate or candidate["dan"] in seen:
                continue
            seen.add(candidate["dan"])
            candidates.append(candidate)
    return candidates


def dm_mcp_search(query: str) -> list[dict[str, Any]]:
    session_id = ""
    try:
        init_response, session_id = dm_mcp_post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": DM_MCP_PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "home-assistant-drogerie-bestandsvergleich", "version": APP_VERSION},
                },
            }
        )
        if init_response.get("error"):
            raise RuntimeError(str((init_response.get("error") or {}).get("message") or init_response.get("error")))
        if not session_id:
            raise RuntimeError("dm MCP hat keine Session-ID geliefert.")
        dm_mcp_post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            session_id=session_id,
            expect_response=False,
        )
        call_response, _ = dm_mcp_post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "searchProducts", "arguments": {"query": query}},
            },
            session_id=session_id,
        )
        return dm_candidates_from_mcp_response(call_response)
    finally:
        dm_mcp_close(session_id)


def dm_fallback_search(query: str) -> list[dict[str, Any]]:
    payload = http_json(DM_SEARCH_FALLBACK_URL.format(query=urllib.parse.quote(query)), retries=1)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for obj in walk_dicts(payload):
        candidate = dm_candidate_from_obj(obj)
        if not candidate or candidate["dan"] in seen:
            continue
        seen.add(candidate["dan"])
        candidates.append(candidate)
    return candidates


def resolve_dm_product(product: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    existing = re.sub(r"\D", "", str(product.get("external_id") or ""))
    if re.fullmatch(r"\d{3,12}", existing):
        return existing, {}

    query = str(product.get("search_query") or f"{product.get('brand','')} {product.get('name','')}").strip()
    if not query:
        raise RuntimeError("Für das dm-Produkt fehlt ein Suchbegriff.")

    source = "dm MCP"
    try:
        candidates = dm_mcp_search(query)
        if not candidates:
            raise RuntimeError("keine auswertbaren Produkttreffer")
    except Exception as exc:
        LOG.warning("dm MCP Produktsuche fehlgeschlagen, direkter Suchdienst als Fallback: %s", exc)
        source = "dm Produktsuche (Fallback)"
        candidates = dm_fallback_search(query)

    if not candidates:
        raise RuntimeError("dm-Produktsuche lieferte keine passende DAN.")

    wanted_ean = re.sub(r"\D", "", str(product.get("ean") or ""))
    wanted_brand = norm(str(product.get("brand") or ""))
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        score = overlap_score(query, str(candidate.get("title") or ""))
        if wanted_ean and candidate.get("gtin") == wanted_ean:
            score += 2.0
        candidate_brand = norm(str(candidate.get("brand") or ""))
        if wanted_brand and candidate_brand and (wanted_brand in candidate_brand or candidate_brand in wanted_brand):
            score += 0.2
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    score, candidate = scored[0]
    title = str(candidate.get("title") or "")
    if score < 0.34:
        raise RuntimeError(f"dm-Produkt konnte nicht sicher zugeordnet werden (Treffer: {title}).")

    extra: dict[str, Any] = {
        "resolved_title": title,
        "score": score,
        "source": source,
    }
    if candidate.get("url"):
        extra["url"] = str(candidate["url"])
    if candidate.get("gtin"):
        extra["ean"] = str(candidate["gtin"])
    if candidate.get("price") is not None:
        extra["price"] = float(candidate["price"])
    return str(candidate["dan"]), extra



def detect_product_chain(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception as exc:
        raise ValueError("Produkt-URL ist ungültig.") from exc
    host = (parsed.hostname or "").lower().strip(".")
    if host == "dm.de" or host.endswith(".dm.de"):
        return "dm"
    if host == "rossmann.de" or host.endswith(".rossmann.de"):
        return "rossmann"
    raise ValueError("Bitte eine Produkt-URL von dm.de oder rossmann.de verwenden.")


def strip_brand_prefix(name: str, brand: str) -> str:
    name = str(name or "").strip()
    brand = str(brand or "").strip()
    if not brand or not name:
        return name
    if norm(name).startswith(norm(brand) + " "):
        raw = re.sub(r"^\s*" + re.escape(brand) + r"\s*[-–—:]?\s*", "", name, flags=re.IGNORECASE)
        return raw.strip() or name
    return name


def find_jsonld_product(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        typ = obj.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if any(str(x).lower() == "product" for x in types if x is not None):
            return obj
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in obj:
                found = find_jsonld_product(obj.get(key))
                if found:
                    return found
        for value in obj.values():
            found = find_jsonld_product(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_jsonld_product(item)
            if found:
                return found
    return None


def dm_product_from_url(url: str) -> dict[str, Any]:
    original_url = url.strip()
    parsed = urllib.parse.urlparse(original_url)
    match = re.search(r"/p/d/(\d{3,12})(?:/|$)", parsed.path)
    dan = match.group(1) if match else ""

    if not dan:
        # Manche geteilten Links enthalten nur die GTIN. In diesem Fall wird
        # der offizielle dm MCP für die eindeutige Zuordnung verwendet.
        params = urllib.parse.parse_qs(parsed.query)
        gtin = re.sub(r"\D", "", (params.get("appProductId") or [""])[0])
        if gtin:
            candidates = dm_mcp_search(gtin)
            exact = next((c for c in candidates if str(c.get("gtin") or "") == gtin), None)
            if exact:
                dan = str(exact["dan"])
        if not dan:
            raise ValueError("Die dm-Produkt-URL enthält keine eindeutige dm-Artikelnummer (DAN). Bitte die normale dm-Produktseite öffnen und deren URL einfügen.")

    payload = http_json(DM_DETAIL_URL.format(dan=urllib.parse.quote(dan, safe="")), retries=1)
    if not isinstance(payload, dict):
        raise RuntimeError("dm lieferte keine auswertbaren Produktdetails.")

    candidate = None
    for obj in walk_dicts(payload):
        cand = dm_candidate_from_obj(obj)
        if cand and cand.get("dan") == dan:
            candidate = cand
            break

    a11y = str(payload.get("a11yLabel") or "")
    brand = ""
    name = ""
    price: float | None = None
    if candidate:
        brand = str(candidate.get("brand") or "").strip()
        name = str(candidate.get("title") or "").strip()
        price = candidate.get("price")

    if not brand:
        brand_obj = payload.get("brand")
        if isinstance(brand_obj, dict):
            brand = str(brand_obj.get("name") or "").strip()
    if a11y:
        if not brand:
            m = re.search(r"Marke:\s*([^;]+)", a11y, flags=re.IGNORECASE)
            if m:
                brand = m.group(1).strip()
        if not name:
            m = re.search(r"Produktname:\s*([^;]+)", a11y, flags=re.IGNORECASE)
            if m:
                name = m.group(1).strip()
        if price is None:
            m = re.search(r"Preis:\s*([0-9]+(?:[.,][0-9]+)?)\s*€", a11y, flags=re.IGNORECASE)
            if m:
                price = float(m.group(1).replace(",", "."))

    if not name:
        raise RuntimeError("dm-Produktname konnte aus der Produktseite nicht gelesen werden.")

    raw_text = json.dumps(payload, ensure_ascii=False)
    ean = str(candidate.get("gtin") or "") if candidate else ""
    if not ean:
        m = re.search(r"GTIN:\s*(\d{8,14})", raw_text)
        if m:
            ean = m.group(1)

    canonical = str(candidate.get("url") or "") if candidate else ""
    if not canonical:
        canonical = original_url.split("#", 1)[0]

    return {
        "chain": "dm",
        "brand": brand,
        "name": strip_brand_prefix(name, brand),
        "search_query": " ".join(x for x in (brand, strip_brand_prefix(name, brand)) if x).strip(),
        "external_id": dan,
        "ean": re.sub(r"\D", "", ean),
        "url": canonical,
        "reference_price": price,
    }


def parse_dm_stock_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {"stock": None, "in_stock": None, "status": "NO_DATA"}
    text = html.unescape(str(entry.get("text") or "")).strip()
    icon = str(entry.get("icon") or "").upper()
    match = re.search(r"(\d+)\s*St(?:ü|ue)ck", text, flags=re.IGNORECASE)
    stock: int | str | None
    if match:
        stock = int(match.group(1))
    elif "nicht verfügbar" in text.lower() or icon in ("RED", "GRAY", "GREY"):
        stock = 0
    elif text:
        stock = text
    else:
        stock = None

    if match:
        in_stock: bool | None = int(match.group(1)) > 0
    elif "nicht verfügbar" in text.lower() or icon in ("RED", "GRAY", "GREY"):
        in_stock = False
    elif icon == "GREEN" or "verfügbar" in text.lower():
        in_stock = True
    else:
        in_stock = None
    return {
        "stock": stock,
        "in_stock": in_stock,
        "status": icon or "OK",
        "label": text,
    }


def dm_check(product_rows: list[dict[str, Any]], stores: list[dict[str, Any]]) -> dict[str, Any]:
    errors: dict[int, str] = {}
    resolved: dict[int, str] = {}
    for product in product_rows:
        try:
            dan, extra = resolve_dm_product(product)
            resolved[int(product["id"])] = dan
            discovered_price = extra.get("price")
            with DB_LOCK, connect() as conn:
                conn.execute(
                    "UPDATE products SET external_id=?, ean=CASE WHEN ?<>'' THEN ? ELSE ean END, url=CASE WHEN ?<>'' THEN ? ELSE url END, reference_price=CASE WHEN reference_price IS NULL AND ? IS NOT NULL THEN ? ELSE reference_price END, last_resolved_at=?, last_error=NULL WHERE id=?",
                    (
                        dan,
                        str(extra.get("ean", "")), str(extra.get("ean", "")),
                        str(extra.get("url", "")), str(extra.get("url", "")),
                        discovered_price, discovered_price,
                        utc_now(), product["id"],
                    ),
                )
                conn.commit()
        except Exception as exc:
            errors[int(product["id"])] = str(exc)
            with DB_LOCK, connect() as conn:
                conn.execute("UPDATE products SET last_error=? WHERE id=?", (str(exc), product["id"]))
                conn.commit()

    if not resolved:
        return {"provider": "dm", "numeric": True, "cells": {}, "errors": errors, "message": "Keine dm-Produkte konnten aufgelöst werden."}

    store_ids = [str(s["external_id"]).strip().upper() for s in stores if s.get("external_id")]
    if not store_ids:
        raise RuntimeError("Keine dm-Filialkennungen hinterlegt.")
    invalid_stores = [sid for sid in store_ids if not re.fullmatch(r"[A-Z][0-9A-Z]{3}", sid)]
    if invalid_stores:
        raise RuntimeError("Ungültige dm-Filialkennung(en): " + ", ".join(invalid_stores))

    cells: dict[str, dict[str, Any]] = {}
    for pid, dan in resolved.items():
        combined_payload: dict[str, Any] = {}
        product_errors: list[str] = []
        for offset in range(0, len(store_ids), 5):
            batch = store_ids[offset:offset + 5]
            try:
                url = DM_STOCK_URL.format(
                    dan=urllib.parse.quote(dan, safe=""),
                    stores=urllib.parse.quote(",".join(batch), safe=","),
                )
                payload = http_json(url, retries=1)
                if not isinstance(payload, dict):
                    raise RuntimeError("dm-Bestandsantwort ist kein JSON-Objekt.")
                combined_payload.update(payload)
            except Exception as exc:
                product_errors.append(str(exc))
                for sid in batch:
                    cells[f"{pid}:{sid}"] = {"stock": None, "in_stock": None, "status": "ERROR", "error": str(exc)}

        if product_errors:
            errors[pid] = "; ".join(dict.fromkeys(product_errors))

        for store in stores:
            sid = str(store.get("external_id") or "").strip().upper()
            key = f"{pid}:{sid}"
            if key in cells and cells[key].get("status") == "ERROR":
                continue
            entry = combined_payload.get(sid)
            cell = parse_dm_stock_entry(entry)
            if cell.get("stock") is None:
                cell.setdefault("error", "dm lieferte für diese Filiale keinen Bestand.")
            cells[key] = cell

    return {
        "provider": "dm",
        "numeric": True,
        "cells": cells,
        "errors": errors,
        "message": "dm-Livebestand über den aktuellen availability-Endpunkt; Produktzuordnung bei Bedarf über den offiziellen dm MCP.",
    }


class RossmannBrowser:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def close(self) -> None:
        with self.lock:
            self._close_locked()

    def _close_locked(self) -> None:
        for obj, method in ((self._context, "close"), (self._browser, "close")):
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
        self._page = None
        self._context = None
        self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = None

    def _wait_ready_locked(self, timeout_s: int = 25) -> None:
        if self._page is None:
            raise RuntimeError("ROSSMANN-Browser ist nicht initialisiert.")
        deadline = time.monotonic() + timeout_s
        last_title = ""
        while time.monotonic() < deadline:
            try:
                last_title = self._page.title()
                if "Client Challenge" not in last_title:
                    return
            except Exception:
                pass
            self._page.wait_for_timeout(750)
        raise RuntimeError(f"ROSSMANN Client Challenge wurde nicht freigegeben (Titel: {last_title or 'unbekannt'}).")

    def _start_locked(self) -> None:
        self._close_locked()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        self._context = self._browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000})
        self._page = self._context.new_page()
        try:
            self._page.goto(ROSSMANN_HOME_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            LOG.warning("ROSSMANN Startnavigation meldete: %s", exc)
        self._wait_ready_locked()
        LOG.info("ROSSMANN Browser-Sitzung bereit: %s", self._page.title())

    def _ensure_locked(self) -> None:
        if self._page is None or self._browser is None or not self._browser.is_connected():
            self._start_locked()

    def fetch_store_payload(self, dan: str, query: str) -> dict[str, Any]:
        with self.lock:
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    self._ensure_locked()
                    result = self._page.evaluate(
                        """
                        async ({dan, query}) => {
                          const url = '/storefinder/.rest/store?dan=' + encodeURIComponent(dan) + '&q=' + encodeURIComponent(query);
                          const response = await fetch(url, {
                            credentials: 'include',
                            headers: {
                              'Accept': 'application/json, text/javascript, */*; q=0.01',
                              'X-Requested-With': 'XMLHttpRequest'
                            }
                          });
                          return {
                            status: response.status,
                            contentType: response.headers.get('content-type') || '',
                            text: await response.text()
                          };
                        }
                        """,
                        {"dan": dan, "query": query},
                    )
                    ctype = str(result.get("contentType") or "").lower()
                    if "json" not in ctype:
                        raise RuntimeError(f"ROSSMANN lieferte keine JSON-Antwort (HTTP {result.get('status')}, {ctype or 'ohne Content-Type'}).")
                    payload = json.loads(str(result.get("text") or "{}"))
                    if not isinstance(payload, dict):
                        raise RuntimeError("ROSSMANN-Antwort ist kein JSON-Objekt.")
                    return payload
                except Exception as exc:
                    last_error = exc
                    LOG.warning("ROSSMANN Browser-Abfrage fehlgeschlagen (Versuch %s/2): %s", attempt + 1, exc)
                    self._close_locked()
            raise RuntimeError(str(last_error) if last_error else "ROSSMANN Browser-Abfrage fehlgeschlagen.")

    def resolve_dan(self, product: dict[str, Any]) -> str:
        existing = str(product.get("external_id") or "").strip()
        if re.fullmatch(r"\d{4,9}", existing):
            return existing
        with self.lock:
            self._ensure_locked()
            target_url = str(product.get("url") or "").strip()
            ean = re.sub(r"\D", "", str(product.get("ean") or ""))
            query = str(product.get("search_query") or product.get("name") or "").strip()
            if target_url:
                return self._resolve_dan_from_url_locked(target_url)
            search_term = ean or query
            if not search_term:
                raise RuntimeError("Für ROSSMANN fehlen DAN, Produkt-URL und Suchbegriff.")
            search_url = "https://www.rossmann.de/de/search?text=" + urllib.parse.quote(search_term)
            try:
                self._page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                LOG.warning("ROSSMANN Produktsuche meldete: %s", exc)
            self._wait_ready_locked()
            body = self._page.locator("body").inner_text(timeout=15000)
            direct = re.search(r"Artikelnummer:\s*(\d+)", body)
            if direct:
                return direct.group(1)
            links = self._page.eval_on_selector_all(
                'a[href*="/p/"]',
                "els => els.map(e => ({href:e.href, text:(e.innerText||e.textContent||'').trim()}))",
            )
            candidates: list[tuple[float, str]] = []
            for item in links or []:
                href = str(item.get("href") or "")
                text = str(item.get("text") or "")
                if not href:
                    continue
                score = 1.0 if ean and ean in href else overlap_score(query or search_term, text or href)
                candidates.append((score, href))
            if not candidates:
                raise RuntimeError("ROSSMANN-Produktsuche lieferte keinen Produktlink.")
            candidates.sort(key=lambda x: x[0], reverse=True)
            if candidates[0][0] < 0.34 and not ean:
                raise RuntimeError("ROSSMANN-Produkt konnte nicht sicher zugeordnet werden. Bitte Produkt-URL oder DAN hinterlegen.")
            return self._resolve_dan_from_url_locked(candidates[0][1])

    def _resolve_dan_from_url_locked(self, url: str) -> str:
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            LOG.warning("ROSSMANN Produktnavigation meldete: %s", exc)
        self._wait_ready_locked()
        text = self._page.locator("body").inner_text(timeout=15000)
        match = re.search(r"Artikelnummer:\s*(\d+)", text)
        if not match:
            raise RuntimeError("ROSSMANN-DAN konnte auf der Produktseite nicht gefunden werden.")
        return match.group(1)


    def product_from_url(self, url: str) -> dict[str, Any]:
        with self.lock:
            self._ensure_locked()
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                LOG.warning("ROSSMANN Produktnavigation meldete: %s", exc)
            self._wait_ready_locked()
            snapshot = self._page.evaluate(
                """
                () => ({
                  url: location.href,
                  canonical: document.querySelector('link[rel="canonical"]')?.href || '',
                  h1: document.querySelector('h1')?.innerText?.trim() || '',
                  title: document.title || '',
                  body: document.body?.innerText || '',
                  jsonld: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(x => x.textContent || '')
                })
                """
            )

        body = str(snapshot.get("body") or "")
        dan_match = re.search(r"Artikelnummer:\s*(\d+)", body)
        if not dan_match:
            raise RuntimeError("ROSSMANN-DAN konnte auf der Produktseite nicht gefunden werden.")
        dan = dan_match.group(1)

        product_obj: dict[str, Any] | None = None
        for raw in snapshot.get("jsonld") or []:
            try:
                parsed = json.loads(str(raw))
            except json.JSONDecodeError:
                continue
            product_obj = find_jsonld_product(parsed)
            if product_obj:
                break

        brand = ""
        name = ""
        ean = ""
        price: float | None = None
        if product_obj:
            brand_obj = product_obj.get("brand")
            if isinstance(brand_obj, dict):
                brand = str(brand_obj.get("name") or "").strip()
            elif brand_obj:
                brand = str(brand_obj).strip()
            name = str(product_obj.get("name") or "").strip()
            for key in ("gtin13", "gtin", "gtin14", "sku"):
                candidate = re.sub(r"\D", "", str(product_obj.get(key) or ""))
                if 8 <= len(candidate) <= 14:
                    ean = candidate
                    break
            offers = product_obj.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict):
                price = dm_price_value(offer.get("price") or offer.get("lowPrice") or offer.get("highPrice"))

        if not name:
            name = str(snapshot.get("h1") or "").strip()
        if not name:
            title = str(snapshot.get("title") or "").strip()
            name = re.sub(r"\s+online kaufen\s*\|\s*rossmann\.de.*$", "", title, flags=re.IGNORECASE).strip()
        if not name:
            raise RuntimeError("ROSSMANN-Produktname konnte aus der Produktseite nicht gelesen werden.")

        canonical = str(snapshot.get("canonical") or snapshot.get("url") or url).strip()
        if not ean:
            m = re.search(r"/p/(\d{8,14})(?:[/?#]|$)", canonical)
            if m:
                ean = m.group(1)
        if price is None:
            # Als Fallback nur klar als Preis formatierte Zeilen auswerten.
            m = re.search(r"(?:^|\n)\s*([0-9]+,[0-9]{2})\s*€\s*(?:\n|$)", body)
            if m:
                price = float(m.group(1).replace(",", "."))

        clean_name = strip_brand_prefix(name, brand)
        return {
            "chain": "rossmann",
            "brand": brand,
            "name": clean_name,
            "search_query": " ".join(x for x in (brand, clean_name) if x).strip(),
            "external_id": dan,
            "ean": ean,
            "url": canonical,
            "reference_price": price,
        }


def rossmann_query_for_store(store: dict[str, Any]) -> str:
    address = str(store.get("address") or "").strip()
    if address:
        return address
    return str(store.get("name") or "").strip()


def rossmann_check(product_rows: list[dict[str, Any]], stores: list[dict[str, Any]]) -> dict[str, Any]:
    errors: dict[int, str] = {}
    resolved: dict[int, str] = {}
    cells: dict[str, dict[str, Any]] = {}
    browser = RossmannBrowser()
    try:
        for product in product_rows:
            pid = int(product["id"])
            try:
                dan = browser.resolve_dan(product)
                resolved[pid] = dan
                with DB_LOCK, connect() as conn:
                    conn.execute(
                        "UPDATE products SET external_id=?, last_resolved_at=?, last_error=NULL WHERE id=?",
                        (dan, utc_now(), pid),
                    )
                    conn.commit()
            except Exception as exc:
                errors[pid] = str(exc)
                with DB_LOCK, connect() as conn:
                    conn.execute("UPDATE products SET last_error=? WHERE id=?", (str(exc), pid))
                    conn.commit()

        for pid, dan in resolved.items():
            for store in stores:
                sid = str(store.get("external_id") or "").strip()
                key = f"{pid}:{sid.upper()}"
                if not re.fullmatch(r"\d+", sid):
                    cells[key] = {"stock": None, "in_stock": None, "status": "NO_STORE_ID", "error": "ROSSMANN-Filial-ID fehlt."}
                    errors.setdefault(pid, "Mindestens einer ROSSMANN-Filiale fehlt eine numerische Filial-ID.")
                    continue
                query = rossmann_query_for_store(store)
                try:
                    payload = browser.fetch_store_payload(dan, query)
                    target = next(
                        (x for x in payload.get("store", []) if str(x.get("id")) == sid),
                        None,
                    )
                    if target is None and query != str(store.get("name") or ""):
                        payload = browser.fetch_store_payload(dan, str(store.get("name") or ""))
                        target = next((x for x in payload.get("store", []) if str(x.get("id")) == sid), None)
                    if target is None:
                        raise RuntimeError("Filiale wurde in der ROSSMANN-Antwort nicht gefunden.")
                    infos = target.get("productInfo") if isinstance(target.get("productInfo"), list) else []
                    info = next((x for x in infos if str(x.get("dan")) == dan), infos[0] if infos else {})
                    stock = info.get("stock")
                    if stock is not None:
                        stock = str(stock)
                    available = info.get("available")
                    cells[key] = {
                        "stock": stock,
                        "in_stock": bool(available) if available is not None else None,
                        "status": "OK",
                    }
                except Exception as exc:
                    cells[key] = {"stock": None, "in_stock": None, "status": "ERROR", "error": str(exc)}
                    errors.setdefault(pid, str(exc))
    finally:
        browser.close()

    for product in product_rows:
        pid = int(product["id"])
        for store in stores:
            sid = str(store.get("external_id") or "").strip().upper()
            cells.setdefault(f"{pid}:{sid}", {"stock": None, "in_stock": None, "status": "NO_DATA"})

    return {
        "provider": "rossmann",
        "numeric": True,
        "cells": cells,
        "errors": errors,
        "message": "ROSSMANN-Livebestand über Browser-Sitzung. Angaben wie 5+ werden unverändert übernommen.",
    }


def load_selected_products(chain: str, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM products WHERE chain=? AND active=1 AND id IN ({marks}) ORDER BY id", (chain, *ids)).fetchall()
    return [rowdict(r) for r in rows]


def do_check(chain: str, product_ids: list[int]) -> dict[str, Any]:
    products = load_selected_products(chain, product_ids)
    stores = [s for s in get_stores(chain) if s.get("active")]
    if not products:
        raise ValueError("Bitte mindestens einen Artikel auswählen.")
    if not stores:
        raise ValueError("Keine aktiven Filialen hinterlegt.")
    if chain == "dm":
        result = dm_check(products, stores)
    elif chain == "rossmann":
        result = rossmann_check(products, stores)
    else:
        raise ValueError("Unbekannte Kette.")
    result.update({"chain": chain, "products": products, "stores": stores, "checked_at": utc_now()})
    ok = 1 if not result.get("errors") else 0
    with DB_LOCK, connect() as conn:
        conn.execute("INSERT INTO checks(chain,created_at,product_count,store_count,ok,message) VALUES(?,?,?,?,?,?)", (chain, result["checked_at"], len(products), len(stores), ok, result.get("message", "")))
        conn.commit()
    return result


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("JSON-Objekt erwartet.")
    return obj


def save_product(data: dict[str, Any], product_id: int | None = None) -> dict[str, Any]:
    chain = str(data.get("chain") or "").lower()
    if chain not in ("dm", "rossmann"):
        raise ValueError("Kette muss dm oder rossmann sein.")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Artikelname fehlt.")
    brand = str(data.get("brand") or "").strip()
    query = str(data.get("search_query") or "").strip() or " ".join(x for x in (brand, name) if x)
    ext = str(data.get("external_id") or "").strip()
    ean = re.sub(r"\D", "", str(data.get("ean") or ""))[:20]
    url = str(data.get("url") or "").strip()
    price = data.get("reference_price")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("Preis ist ungültig.")
    active = 1 if bool(data.get("active", True)) else 0
    with DB_LOCK, connect() as conn:
        if product_id is None:
            cur = conn.execute(
                "INSERT INTO products(chain,brand,name,search_query,external_id,ean,url,reference_price,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (chain, brand, name, query, ext, ean, url, price, active, utc_now()),
            )
            product_id = int(cur.lastrowid)
        else:
            conn.execute(
                "UPDATE products SET chain=?,brand=?,name=?,search_query=?,external_id=?,ean=?,url=?,reference_price=?,active=?,last_error=NULL WHERE id=?",
                (chain, brand, name, query, ext, ean, url, price, active, product_id),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    return rowdict(row)



def import_product_url(data: dict[str, Any]) -> dict[str, Any]:
    url = str(data.get("url") or "").strip()
    if not url:
        raise ValueError("Bitte die Produkt-URL einfügen.")
    chain = detect_product_chain(url)
    expected_chain = str(data.get("expected_chain") or "").strip().lower()
    if expected_chain in ("dm", "rossmann") and expected_chain != chain:
        wanted = "dm" if expected_chain == "dm" else "ROSSMANN"
        actual = "dm" if chain == "dm" else "ROSSMANN"
        raise ValueError(f"Die URL gehört zu {actual}, geöffnet ist aber {wanted}. Bitte zur passenden Kette wechseln.")

    if chain == "dm":
        product = dm_product_from_url(url)
    else:
        browser = RossmannBrowser()
        try:
            product = browser.product_from_url(url)
        finally:
            browser.close()

    ext = str(product.get("external_id") or "").strip()
    ean = re.sub(r"\D", "", str(product.get("ean") or ""))
    canonical = str(product.get("url") or url).strip()
    created = True

    with DB_LOCK, connect() as conn:
        existing = None
        if ext:
            existing = conn.execute(
                "SELECT * FROM products WHERE chain=? AND external_id=? ORDER BY id LIMIT 1",
                (chain, ext),
            ).fetchone()
        if existing is None and ean:
            existing = conn.execute(
                "SELECT * FROM products WHERE chain=? AND ean=? ORDER BY id LIMIT 1",
                (chain, ean),
            ).fetchone()
        if existing is None and canonical:
            existing = conn.execute(
                "SELECT * FROM products WHERE chain=? AND url=? ORDER BY id LIMIT 1",
                (chain, canonical),
            ).fetchone()

        price = product.get("reference_price")
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO products(
                    chain,brand,name,search_query,external_id,ean,url,reference_price,
                    active,last_resolved_at,last_error,created_at
                ) VALUES(?,?,?,?,?,?,?,?,1,?,NULL,?)
                """,
                (
                    chain,
                    str(product.get("brand") or "").strip(),
                    str(product.get("name") or "").strip(),
                    str(product.get("search_query") or "").strip(),
                    ext,
                    ean,
                    canonical,
                    price,
                    utc_now(),
                    utc_now(),
                ),
            )
            product_id = int(cur.lastrowid)
        else:
            created = False
            product_id = int(existing["id"])
            conn.execute(
                """
                UPDATE products
                   SET brand=?, name=?, search_query=?, external_id=?, ean=?, url=?,
                       reference_price=?, active=1, last_resolved_at=?, last_error=NULL
                 WHERE id=?
                """,
                (
                    str(product.get("brand") or "").strip(),
                    str(product.get("name") or "").strip(),
                    str(product.get("search_query") or "").strip(),
                    ext,
                    ean,
                    canonical,
                    price if price is not None else existing["reference_price"],
                    utc_now(),
                    product_id,
                ),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    return {"created": created, "product": rowdict(row), "chain": chain}


def save_store(data: dict[str, Any], store_id: int | None = None) -> dict[str, Any]:
    chain = str(data.get("chain") or "").lower()
    if chain not in ("dm", "rossmann"):
        raise ValueError("Kette muss dm oder rossmann sein.")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Filialname fehlt.")
    address = str(data.get("address") or "").strip()
    external_id = str(data.get("external_id") or "").strip()
    url = str(data.get("url") or "").strip()
    active = 1 if bool(data.get("active", True)) else 0
    sort_order = int(data.get("sort_order") or 0)
    with DB_LOCK, connect() as conn:
        if store_id is None:
            cur = conn.execute(
                "INSERT INTO stores(chain,name,address,external_id,url,active,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (chain, name, address, external_id, url, active, sort_order, utc_now()),
            )
            store_id = int(cur.lastrowid)
        else:
            conn.execute(
                "UPDATE stores SET chain=?,name=?,address=?,external_id=?,url=?,active=?,sort_order=? WHERE id=?",
                (chain, name, address, external_id, url, active, sort_order, store_id),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
    return rowdict(row)


INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Drogerie Bestandsvergleich</title>
<style>
:root{--bg:#f4f6f8;--card:#fff;--text:#182230;--muted:#667085;--line:#e5e7eb;--dm:#0f5a9e;--ross:#c9002b;--ok:#098658;--warn:#b54708;--bad:#c01048;--shadow:0 8px 24px rgba(16,24,40,.07)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text)}
a{color:inherit}.wrap{max-width:1500px;margin:auto;padding:18px}.top{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:14px}.title h1{font-size:25px;margin:0}.title small{color:var(--muted)}.topright{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.tabs,.viewtabs{display:flex;background:#e8edf2;border-radius:14px;padding:4px;gap:4px}.tab,.viewtab{border:0;border-radius:10px;padding:10px 18px;font-weight:800;background:transparent;color:#596579;cursor:pointer}.tab.active.dm{background:var(--dm);color:white}.tab.active.rossmann{background:var(--ross);color:white}.viewtab.active{background:#182230;color:#fff}.panel{background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:16px;margin-bottom:14px}.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.actions h2,.actions h3{margin:0}.btn{border:1px solid var(--line);background:white;padding:9px 13px;border-radius:10px;font-weight:750;cursor:pointer}.btn:disabled{opacity:.55;cursor:wait}.btn.primary{background:#182230;color:white;border-color:#182230}.btn.danger{color:#b42318}.btn.soft{background:#f8fafc}.products{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:9px;margin-top:12px}.product{display:flex;gap:10px;align-items:flex-start;padding:11px;border:1px solid var(--line);border-radius:12px;cursor:pointer;background:#fff}.product.selected{border-color:#94a3b8;background:#f8fafc}.product input{margin-top:4px;transform:scale(1.15)}.product .producttext{min-width:0}.product strong,.titlelink,.titletext{display:block;font-size:14px;font-weight:750}.titlelink{text-decoration:none;color:#182230}.titlelink:hover{text-decoration:underline}.external{font-size:11px;margin-left:5px;color:#667085}.product .meta{display:block;font-size:12px;color:var(--muted);margin-top:3px}.notice{font-size:13px;color:var(--muted);margin-top:10px}.notice.warn{color:#8a3b00;background:#fff7ed;border:1px solid #fed7aa;padding:10px;border-radius:10px}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:14px;margin-top:12px;max-height:65vh}.stock{border-collapse:separate;border-spacing:0;width:100%;min-width:800px;background:white}.stock th,.stock td{padding:10px;border-bottom:1px solid var(--line);border-right:1px solid var(--line);text-align:center;font-size:13px}.stock th{position:sticky;top:0;background:#f8fafc;z-index:2}.stock th:first-child,.stock td:first-child{text-align:left;position:sticky;left:0;background:white;z-index:1;min-width:265px}.stock th:first-child{background:#f8fafc;z-index:3}.pill{display:inline-flex;min-width:44px;justify-content:center;padding:5px 8px;border-radius:999px;font-weight:800}.pill.high{background:#dcfae6;color:#067647}.pill.low{background:#fef0c7;color:#93370d}.pill.zero{background:#fee4e2;color:#b42318}.pill.unknown{background:#f2f4f7;color:#667085}.manage{display:grid;grid-template-columns:1fr 1fr;gap:14px}.manage h3{margin:0}.list{display:flex;flex-direction:column;gap:7px;margin-top:10px}.row{display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:9px}.row.inactive{opacity:.58;background:#fafafa}.row .grow{flex:1;min-width:0}.row strong,.row small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row small{color:var(--muted);margin-top:2px}.iconbtn{border:0;background:#f2f4f7;border-radius:8px;padding:7px;cursor:pointer;min-width:34px}.statebtn{border:1px solid var(--line);background:white;border-radius:8px;padding:6px 8px;font-size:12px;font-weight:700;cursor:pointer}.badge{display:inline-flex;border-radius:999px;padding:3px 7px;font-size:11px;font-weight:800;margin-left:5px}.badge.on{background:#dcfae6;color:#067647}.badge.off{background:#f2f4f7;color:#667085}.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:20;align-items:center;justify-content:center;padding:18px}.modal.show{display:flex}.box{background:white;border-radius:16px;padding:18px;width:min(620px,100%);max-height:90vh;overflow:auto}.box h2{margin-top:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.field{display:flex;flex-direction:column;gap:5px}.field.full{grid-column:1/-1}.field label{font-size:12px;font-weight:700;color:#475467}.field input,.field select{border:1px solid #d0d5dd;border-radius:9px;padding:10px;font-size:14px}.checkfield{display:flex;align-items:center;gap:8px;padding-top:20px}.checkfield input{transform:scale(1.15)}.status{margin-left:auto;font-size:12px;color:var(--muted)}.adminintro{margin:6px 0 0;color:var(--muted);font-size:13px}.empty{color:var(--muted);padding:12px 2px}.toast{display:none;position:fixed;right:18px;bottom:18px;z-index:30;background:#182230;color:#fff;border-radius:11px;padding:10px 14px;box-shadow:var(--shadow);font-weight:700}.toast.show{display:block}
@media(max-width:760px){.wrap{padding:10px}.top{align-items:flex-start;flex-direction:column}.topright{width:100%;justify-content:flex-start}.tabs,.viewtabs{flex:1}.tab,.viewtab{flex:1;padding:9px 10px}.manage{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.field.full{grid-column:auto}.products{grid-template-columns:1fr}.title h1{font-size:21px}.stock th:first-child,.stock td:first-child{min-width:220px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="title">
      <h1>Drogerie Bestandsvergleich</h1>
      <small>dm &amp; ROSSMANN · Version <span id="ver"></span> · Port 8146</small>
    </div>
    <div class="topright">
      <div class="viewtabs">
        <button class="viewtab active" id="compareViewBtn">Vergleich</button>
        <button class="viewtab" id="manageViewBtn">Verwaltung</button>
      </div>
      <div class="tabs">
        <button class="tab dm active" data-chain="dm">dm</button>
        <button class="tab rossmann" data-chain="rossmann">ROSSMANN</button>
      </div>
    </div>
  </div>

  <div id="compareView">
    <div class="panel">
      <div class="actions">
        <strong id="chooseTitle">dm-Artikel auswählen</strong>
        <span class="status" id="providerStatus"></span>
        <button class="btn" id="allBtn">Alle</button>
        <button class="btn" id="noneBtn">Keine</button>
        <button class="btn" id="addProductBtn">+ Artikel</button>
        <button class="btn primary" id="checkBtn">Filialbestand prüfen</button>
      </div>
      <div id="products" class="products"></div>
      <div id="providerNote" class="notice"></div>
    </div>

    <div class="panel" id="resultPanel" style="display:none">
      <div class="actions"><strong>Filialvergleich</strong><span class="status" id="checkedAt"></span></div>
      <div id="resultMessage" class="notice"></div>
      <div id="result"></div>
    </div>
  </div>

  <div id="manageView" style="display:none">
    <div class="panel">
      <div class="actions">
        <h2>Verwaltung · <span id="manageChain">dm</span></h2>
        <span class="status">Stammdaten getrennt je Drogeriekette</span>
      </div>
      <p class="adminintro">Neue Artikel werden ausschließlich über ihre Produkt-URL angelegt. Marke, Artikelname, Größe, Preis und Produktkennung werden automatisch aus der offiziellen Produktseite übernommen.</p>
    </div>
    <div class="panel">
      <div class="manage">
        <div>
          <div class="actions"><h3>Artikel</h3><span class="status"></span><button class="btn" id="adminAddProductBtn">+ Artikel</button></div>
          <div id="productList" class="list"></div>
        </div>
        <div>
          <div class="actions"><h3>Favoriten-Filialen</h3><span class="status"></span><button class="btn" id="addStoreBtn">+ Filiale</button></div>
          <div id="storeList" class="list"></div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="modal" id="modal">
  <div class="box">
    <h2 id="modalTitle"></h2>
    <div id="modalBody"></div>
    <div class="actions" style="margin-top:15px;justify-content:flex-end">
      <button class="btn" id="cancelModal">Abbrechen</button>
      <button class="btn primary" id="saveModal">Speichern</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
let state={chain:'dm',products:[],stores:[],version:'',view:'compare'}, modalMode=null, modalId=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function safeUrl(value){try{const u=new URL(String(value||''));return (u.protocol==='https:'||u.protocol==='http:')?u.href:''}catch{return ''}}
function productName(p){return [p.brand,p.name].filter(Boolean).join(' ').trim()}
function productTitleHtml(p){const text=esc(productName(p));const href=safeUrl(p.url);return href?`<a class="titlelink" href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="Produktseite öffnen">${text}<span class="external">↗</span></a>`:`<span class="titletext">${text}</span>`}
function showToast(text){const t=$('#toast');t.textContent=text;t.classList.add('show');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>t.classList.remove('show'),2600)}
async function api(path,opt={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opt});const x=await r.json().catch(()=>({}));if(!r.ok)throw new Error(x.error||('HTTP '+r.status));return x}
async function load(){const x=await api('api/bootstrap?chain='+state.chain);state={...state,...x};render()}
function setView(view){state.view=view;render();if(view==='manage')window.scrollTo({top:0,behavior:'smooth'})}

function render(){
  $('#ver').textContent=state.version;
  $('.tab.dm').classList.toggle('active',state.chain==='dm');
  $('.tab.rossmann').classList.toggle('active',state.chain==='rossmann');
  $('#compareViewBtn').classList.toggle('active',state.view==='compare');
  $('#manageViewBtn').classList.toggle('active',state.view==='manage');
  $('#compareView').style.display=state.view==='compare'?'block':'none';
  $('#manageView').style.display=state.view==='manage'?'block':'none';
  $('#manageChain').textContent=state.chain==='dm'?'dm':'ROSSMANN';
  $('#chooseTitle').textContent=(state.chain==='dm'?'dm':'ROSSMANN')+'-Artikel auswählen';
  $('#providerStatus').textContent='Live-Stückzahlen';
  $('#providerNote').className='notice';
  $('#providerNote').textContent=state.chain==='dm'
    ?'Beim ersten Abruf wird ein dm-Artikel bei Bedarf über den offiziellen dm MCP einer DAN zugeordnet. Danach werden die aktuellen Stückbestände über den dm-Availability-Endpunkt direkt je Favoriten-Markt abgefragt.'
    :'ROSSMANN wird über eine echte Browser-Sitzung abgefragt. Die erste Abfrage nach App-Start kann durch die Client-Prüfung einige Sekunden länger dauern; Werte wie 5+ werden unverändert angezeigt.';

  const activeProducts=state.products.filter(p=>p.active);
  $('#products').innerHTML=activeProducts.map(p=>`<div class="product" data-product-id="${p.id}"><input class="pick" type="checkbox" value="${p.id}"><div class="producttext">${productTitleHtml(p)}<span class="meta">${p.reference_price!=null?Number(p.reference_price).toFixed(2).replace('.',',')+' €':''}${p.last_error?' · ⚠ '+esc(p.last_error):''}</span></div></div>`).join('') || '<div class="empty">Keine aktiven Artikel hinterlegt.</div>';
  document.querySelectorAll('.product').forEach(card=>{
    const cb=card.querySelector('.pick');
    cb.addEventListener('change',()=>card.classList.toggle('selected',cb.checked));
    card.addEventListener('click',e=>{if(e.target.closest('a,input,button'))return;cb.checked=!cb.checked;card.classList.toggle('selected',cb.checked)});
  });

  $('#productList').innerHTML=state.products.map(p=>`<div class="row ${p.active?'':'inactive'}"><div class="grow">${productTitleHtml(p)}<small>${p.external_id?'ID '+esc(p.external_id):'keine ID'}${p.ean?' · GTIN '+esc(p.ean):''}${p.reference_price!=null?' · '+Number(p.reference_price).toFixed(2).replace('.',',')+' €':''}<span class="badge ${p.active?'on':'off'}">${p.active?'aktiv':'inaktiv'}</span></small></div><button class="statebtn" onclick="toggleProduct(${p.id})">${p.active?'Deaktivieren':'Aktivieren'}</button><button class="iconbtn" title="Bearbeiten" onclick="editProduct(${p.id})">✎</button><button class="iconbtn" title="Löschen" onclick="delProduct(${p.id})">🗑</button></div>`).join('') || '<div class="empty">Noch keine Artikel angelegt.</div>';

  $('#storeList').innerHTML=state.stores.map(s=>`<div class="row ${s.active?'':'inactive'}"><div class="grow"><strong>${esc(s.name)}</strong><small>${esc(s.address)}${s.external_id?' · '+esc(s.external_id):''}<span class="badge ${s.active?'on':'off'}">${s.active?'aktiv':'inaktiv'}</span></small></div><button class="statebtn" onclick="toggleStore(${s.id})">${s.active?'Deaktivieren':'Aktivieren'}</button><button class="iconbtn" title="Bearbeiten" onclick="editStore(${s.id})">✎</button><button class="iconbtn" title="Löschen" onclick="delStore(${s.id})">🗑</button></div>`).join('') || '<div class="empty">Noch keine Filialen angelegt.</div>';
}

$('.tabs').addEventListener('click',e=>{const b=e.target.closest('[data-chain]');if(!b)return;state.chain=b.dataset.chain;$('#resultPanel').style.display='none';load().catch(e=>alert(e.message))});
$('#compareViewBtn').onclick=()=>setView('compare');
$('#manageViewBtn').onclick=()=>setView('manage');
$('#allBtn').onclick=()=>document.querySelectorAll('#products .pick').forEach(x=>{x.checked=true;x.closest('.product').classList.add('selected')});
$('#noneBtn').onclick=()=>document.querySelectorAll('#products .pick').forEach(x=>{x.checked=false;x.closest('.product').classList.remove('selected')});
$('#checkBtn').onclick=async()=>{const ids=[...document.querySelectorAll('#products .pick:checked')].map(x=>+x.value);if(!ids.length)return alert('Bitte mindestens einen Artikel auswählen.');const b=$('#checkBtn');b.disabled=true;b.textContent='Prüfe …';try{const x=await api('api/check',{method:'POST',body:JSON.stringify({chain:state.chain,product_ids:ids})});renderResult(x);await load()}catch(e){alert(e.message)}finally{b.disabled=false;b.textContent='Filialbestand prüfen'}};
function renderResult(x){
  $('#resultPanel').style.display='block';
  $('#checkedAt').textContent=new Date(x.checked_at).toLocaleString('de-DE');
  $('#resultMessage').textContent=x.message||'';
  const heads=x.stores.map(s=>`<th>${esc(s.name)}</th>`).join('');
  const rows=x.products.map(p=>{
    const cells=x.stores.map(s=>{const k=p.id+':'+String(s.external_id||'').toUpperCase(),c=x.cells[k]||{};if(x.numeric){if(c.stock===null||c.stock===undefined)return `<td title="${esc(c.error||c.status||'Keine Daten')}"><span class="pill unknown">?</span></td>`;const txt=String(c.stock),m=txt.match(/\d+/),n=m?Number(m[0]):null;const cl=c.in_stock===false||n===0?'zero':n!==null&&n<=3?'low':'high';return `<td><span class="pill ${cl}">${esc(txt)}</span></td>`}return '<td><span class="pill unknown">?</span></td>'}).join('');
    return `<tr><td>${productTitleHtml(p)}</td>${cells}</tr>`;
  }).join('');
  $('#result').innerHTML=`<div class="tablewrap"><table class="stock"><thead><tr><th>Artikel</th>${heads}</tr></thead><tbody>${rows}</tbody></table></div>`;
  $('#resultPanel').scrollIntoView({behavior:'smooth',block:'start'});
}

function openModal(title,body,mode,id=null,saveLabel='Speichern'){modalMode=mode;modalId=id;$('#modalTitle').textContent=title;$('#modalBody').innerHTML=body;$('#saveModal').textContent=saveLabel;$('#saveModal').disabled=false;$('#modal').classList.add('show')}
$('#cancelModal').onclick=()=>$('#modal').classList.remove('show');
$('#modal').addEventListener('click',e=>{if(e.target===$('#modal'))$('#modal').classList.remove('show')});
function importForm(){return `<div class="grid"><div class="field full"><label>Produkt-URL von ${state.chain==='dm'?'dm':'ROSSMANN'}</label><input id="fImportUrl" type="url" inputmode="url" autocomplete="off" placeholder="https://…"></div><div class="field full"><div class="notice">Nur die Produkt-URL einfügen. Die App liest Händler, offiziellen Artikelnamen, Marke, Packungsgröße, aktuellen Preis, GTIN und die interne Produkt-ID automatisch aus.</div></div></div>`}
function openProductImport(){openModal('Artikel hinzufügen',importForm(),'product-import',null,'Artikel übernehmen');setTimeout(()=>$('#fImportUrl')?.focus(),50)}
$('#addProductBtn').onclick=openProductImport;
$('#adminAddProductBtn').onclick=openProductImport;
function productForm(p={}){return `<div class="grid"><div class="field"><label>Marke</label><input id="fBrand" value="${esc(p.brand||'')}"></div><div class="field"><label>Preis (€)</label><input id="fPrice" inputmode="decimal" value="${p.reference_price??''}"></div><div class="field full"><label>Artikelname</label><input id="fName" value="${esc(p.name||'')}"></div><div class="field full"><label>Suchbegriff</label><input id="fQuery" value="${esc(p.search_query||'')}"></div><div class="field"><label>EAN/GTIN</label><input id="fEan" value="${esc(p.ean||'')}"></div><div class="field"><label>${state.chain==='rossmann'?'ROSSMANN-DAN':'dm-DAN'}</label><input id="fExt" value="${esc(p.external_id||'')}"></div><div class="field full"><label>Produkt-URL</label><input id="fUrl" value="${esc(p.url||'')}"></div><div class="checkfield"><input id="fActive" type="checkbox" ${p.active!==0?'checked':''}><label for="fActive">Artikel aktiv</label></div></div>`}
window.editProduct=id=>{const p=state.products.find(x=>x.id===id);openModal('Artikel bearbeiten',productForm(p),'product',id)};
function storeForm(s={}){return `<div class="grid"><div class="field"><label>Kurzname</label><input id="fName" value="${esc(s.name||'')}"></div><div class="field"><label>${state.chain==='rossmann'?'ROSSMANN-Filial-ID':'Filialkennung'}</label><input id="fExt" value="${esc(s.external_id||'')}"></div><div class="field full"><label>Adresse</label><input id="fAddress" value="${esc(s.address||'')}"></div><div class="field full"><label>Filial-URL optional</label><input id="fUrl" value="${esc(s.url||'')}"></div><div class="field"><label>Reihenfolge</label><input id="fSort" type="number" value="${s.sort_order??0}"></div><div class="checkfield"><input id="fActive" type="checkbox" ${s.active!==0?'checked':''}><label for="fActive">Filiale aktiv</label></div></div>`}
$('#addStoreBtn').onclick=()=>openModal('Filiale hinzufügen',storeForm(),'store');
window.editStore=id=>{const s=state.stores.find(x=>x.id===id);openModal('Filiale bearbeiten',storeForm(s),'store',id)};

$('#saveModal').onclick=async()=>{
  const b=$('#saveModal');
  try{
    if(modalMode==='product-import'){
      const url=$('#fImportUrl').value.trim();
      if(!url)throw new Error('Bitte die Produkt-URL einfügen.');
      b.disabled=true;b.textContent='Lese Produktdaten …';
      const x=await api('api/products/import',{method:'POST',body:JSON.stringify({url,expected_chain:state.chain})});
      $('#modal').classList.remove('show');await load();showToast(x.created?'Artikel hinzugefügt':'Artikel war bereits vorhanden – Daten aktualisiert');return;
    }
    if(modalMode==='product'){
      const body={chain:state.chain,brand:$('#fBrand').value,name:$('#fName').value,search_query:$('#fQuery').value,ean:$('#fEan').value,external_id:$('#fExt').value,url:$('#fUrl').value,reference_price:$('#fPrice').value,active:$('#fActive').checked};
      await api('api/products/'+modalId,{method:'PUT',body:JSON.stringify(body)});
    }else if(modalMode==='store'){
      const body={chain:state.chain,name:$('#fName').value,address:$('#fAddress').value,external_id:$('#fExt').value,url:$('#fUrl').value,sort_order:Number($('#fSort').value||0),active:$('#fActive').checked};
      await api('api/stores'+(modalId?'/'+modalId:''),{method:modalId?'PUT':'POST',body:JSON.stringify(body)});
    }
    $('#modal').classList.remove('show');await load();showToast('Gespeichert');
  }catch(e){alert(e.message)}finally{b.disabled=false;if(modalMode==='product-import')b.textContent='Artikel übernehmen';else b.textContent='Speichern'}
};
window.toggleProduct=async id=>{const p=state.products.find(x=>x.id===id);if(!p)return;const body={chain:p.chain,brand:p.brand,name:p.name,search_query:p.search_query,ean:p.ean,external_id:p.external_id,url:p.url,reference_price:p.reference_price,active:!p.active};await api('api/products/'+id,{method:'PUT',body:JSON.stringify(body)});await load()};
window.toggleStore=async id=>{const s=state.stores.find(x=>x.id===id);if(!s)return;const body={chain:s.chain,name:s.name,address:s.address,external_id:s.external_id,url:s.url,sort_order:s.sort_order,active:!s.active};await api('api/stores/'+id,{method:'PUT',body:JSON.stringify(body)});await load()};
window.delProduct=async id=>{if(confirm('Artikel wirklich löschen?')){await api('api/products/'+id,{method:'DELETE'});await load();showToast('Artikel gelöscht')}};
window.delStore=async id=>{if(confirm('Filiale wirklich löschen?')){await api('api/stores/'+id,{method:'DELETE'});await load();showToast('Filiale gelöscht')}};
load().catch(e=>alert(e.message));
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "DrogerieBestandsvergleich/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    def send_json(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def route(self) -> tuple[str, urllib.parse.ParseResult]:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # Ingress kann einen Prefix voranstellen. Alles ab /api/ beziehungsweise das letzte Segment wird akzeptiert.
        marker = path.rfind("/api/")
        if marker > 0:
            suffix = path[marker:]
            if suffix.startswith(("/api/bootstrap", "/api/health", "/api/check", "/api/products", "/api/stores")):
                path = suffix
            elif "/api/hassio_ingress/" in path:
                path = "/"
        return path, parsed

    def do_GET(self) -> None:
        try:
            path, parsed = self.route()
            if path in ("/", "", "/index.html") or not path.startswith("/api/"):
                self.send_html(INDEX_HTML)
                return
            if path == "/api/health":
                self.send_json({"ok": True, "version": APP_VERSION})
                return
            if path == "/api/bootstrap":
                chain = urllib.parse.parse_qs(parsed.query).get("chain", ["dm"])[0]
                if chain not in ("dm", "rossmann"):
                    raise ValueError("Ungültige Kette.")
                self.send_json({"version": APP_VERSION, "chain": chain, "products": get_products(chain), "stores": get_stores(chain)})
                return
            self.send_json({"error": "Nicht gefunden"}, 404)
        except Exception as exc:
            LOG.exception("GET failed")
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        self._write("POST")

    def do_PUT(self) -> None:
        self._write("PUT")

    def do_DELETE(self) -> None:
        self._write("DELETE")

    def _write(self, method: str) -> None:
        try:
            path, _ = self.route()
            data = parse_json_body(self) if method in ("POST", "PUT") else {}
            if path == "/api/check" and method == "POST":
                chain = str(data.get("chain") or "")
                ids = [int(x) for x in data.get("product_ids", [])]
                self.send_json(do_check(chain, ids))
                return
            if path == "/api/products/import" and method == "POST":
                result = import_product_url(data)
                self.send_json(result, 201 if result.get("created") else 200)
                return
            m = re.fullmatch(r"/api/products(?:/(\d+))?", path)
            if m:
                pid = int(m.group(1)) if m.group(1) else None
                if method == "POST" and pid is None:
                    self.send_json(save_product(data), 201); return
                if method == "PUT" and pid is not None:
                    self.send_json(save_product(data, pid)); return
                if method == "DELETE" and pid is not None:
                    with DB_LOCK, connect() as conn:
                        conn.execute("DELETE FROM products WHERE id=?", (pid,)); conn.commit()
                    self.send_json({"ok": True}); return
            m = re.fullmatch(r"/api/stores(?:/(\d+))?", path)
            if m:
                sid = int(m.group(1)) if m.group(1) else None
                if method == "POST" and sid is None:
                    self.send_json(save_store(data), 201); return
                if method == "PUT" and sid is not None:
                    self.send_json(save_store(data, sid)); return
                if method == "DELETE" and sid is not None:
                    with DB_LOCK, connect() as conn:
                        conn.execute("DELETE FROM stores WHERE id=?", (sid,)); conn.commit()
                    self.send_json({"ok": True}); return
            self.send_json({"error": "Nicht gefunden oder Methode nicht erlaubt"}, 404)
        except (ValueError, sqlite3.IntegrityError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            LOG.exception("write failed")
            self.send_json({"error": str(exc)}, 500)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    LOG.info("%s %s läuft auf 0.0.0.0:%s", APP_NAME, APP_VERSION, PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
