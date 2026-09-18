#!/usr/bin/env python3
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.1.40"
PORT = int(os.environ.get("PORT", "8151"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OPTIONS_PATH = Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
STATE_PATH = DATA_DIR / "post_dhl.json"
INTERNETMARKE_BASE = "https://api-eu.dhl.com/post/de/shipping/im/v1"
# DHL documents this path for the INTERNETMARKE partner profile.  The first
# endpoint is retained as an alternate only, because a HTTP 200 response alone
# does not guarantee it contains usable product codes and prices.
INTERNETMARKE_PRODUCTS_URL_DOCUMENTED = (
    "https://api-eu.dhl.com/post/de/information/products/v1/products?profile=IM-PARTNER&shortVersion=true"
)
INTERNETMARKE_PRODUCTS_URL_ALTERNATE = (
    "https://api-eu.dhl.com/post/de/information/v1/products?profile=IM-PARTNER&shortVersion=true"
)
INTERNETMARKE_PRODUCTS_URLS = [
    INTERNETMARKE_PRODUCTS_URL_DOCUMENTED,
    INTERNETMARKE_PRODUCTS_URL_ALTERNATE,
]

# Feste Schutzgrenzen für die sechs bewusst angebotenen Inlandsprodukte.
# Sie dienen *nicht* als Preisreserve: Fehlt oder weicht der DHL-Livepreis ab,
# wird das Produkt gar nicht angezeigt und kann folglich nicht gekauft werden.
INTERNETMARKE_NATIONAL_SPECS = {
    "Standardbrief": {"price": 0.95, "max_weight": 20},
    "Kompaktbrief": {"price": 1.10, "max_weight": 50},
    "Großbrief": {"price": 1.80, "max_weight": 500},
    "Maxibrief": {"price": 2.90, "max_weight": 1000},
    "Warensendung 1 kg": {"price": 2.70, "max_weight": 1000},
    "Warensendung 2 kg": {"price": 3.55, "max_weight": 2000},
}

# Official production server from the DHL Parcel DE Private Shipping OpenAPI spec.
PRIVATE_BASE = "https://api-eu.dhl.com/parcel/de/shipping/of/v1/public"
PRIVATE_CATALOG_VERSION = "current"

# Bewusst schlanke Produktauswahl für den privaten/kleinen Versand.
PRIVATE_PRODUCT_ORDER = ["PAECKS", "PAECK", "PAK02", "PAK05", "PAK10", "PAK20"]
PRIVATE_PRODUCT_NAMES = {
    "PAECKS": "Päckchen S",
    "PAECK": "Päckchen M",
    "PAK02": "DHL Paket 2 kg",
    "PAK05": "DHL Paket 5 kg",
    "PAK10": "DHL Paket 10 kg",
    "PAK20": "DHL Paket 20 kg",
}

STATE_LOCK = threading.RLock()
CATALOG_LOCK = threading.RLock()

DEFAULT_STATE = {
    "version": VERSION,
    "sender": {
        "name1": "",
        "name2": "",
        "name3": "",
        "street": "",
        "streetNumber": "",
        "plz": "",
        "city": "",
        "country": "DEU",
        "email": "",
        "phone": "",
    },
    "addresses": [],
    "senders": [],
    "recent_carts": [],
    "recent_internetmarke": [],
    "dhl": {
        "detected_base": "",
        "catalog_version": "",
        "catalog_cached_at": 0,
        "catalog": None,
        "last_error": "",
    },
}


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def deep_copy(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else deep_copy(default)
    except Exception:
        return deep_copy(default)


def merge_defaults(data, default):
    if not isinstance(data, dict):
        return deep_copy(default)
    out = deep_copy(default)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load_state():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_LOCK:
        state = merge_defaults(load_json(STATE_PATH, DEFAULT_STATE), DEFAULT_STATE)
        state["version"] = VERSION
        save_state(state)
        return state


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def load_options():
    data = load_json(OPTIONS_PATH, {})
    return {
        "dhl_private_api_key": str(data.get("dhl_private_api_key") or "").strip(),
        "internetmarke_api_key": str(data.get("internetmarke_api_key") or "").strip(),
        "internetmarke_api_secret": str(data.get("internetmarke_api_secret") or "").strip(),
        "portokasse_username": str(data.get("portokasse_username") or "").strip(),
        "portokasse_password": str(data.get("portokasse_password") or "").strip(),
        "dhl_private_api_base": str(data.get("dhl_private_api_base") or "").strip().rstrip("/"),
    }


def public_state():
    with STATE_LOCK:
        st = load_state()
    opts = load_options()
    dhl_configured = bool(opts["dhl_private_api_key"])
    im_configured = all([
        opts["internetmarke_api_key"],
        opts["internetmarke_api_secret"],
        opts["portokasse_username"],
        opts["portokasse_password"],
    ])
    return {
        "version": VERSION,
        "sender": st.get("sender", {}),
        "senders": st.get("senders", []),
        "addresses": st.get("addresses", []),
        "recent_carts": st.get("recent_carts", [])[:20],
        "recent_internetmarke": st.get("recent_internetmarke", [])[:20],
        "dhl": {
            "configured": dhl_configured,
            "detected_base": st.get("dhl", {}).get("detected_base", ""),
            "catalog_version": st.get("dhl", {}).get("catalog_version", ""),
            "catalog_cached_at": st.get("dhl", {}).get("catalog_cached_at", 0),
            "last_error": st.get("dhl", {}).get("last_error", ""),
            "base_override": bool(opts["dhl_private_api_base"]),
        },
        "internetmarke": {
            "configured": im_configured,
            "api_credentials": bool(opts["internetmarke_api_key"] and opts["internetmarke_api_secret"]),
            "portokasse_credentials": bool(opts["portokasse_username"] and opts["portokasse_password"]),
        },
    }


def latin1_clean(value):
    s = str(value or "").strip()
    forbidden = "?*^!#%$:{}[]"
    for ch in forbidden:
        s = s.replace(ch, "")
    try:
        s.encode("iso-8859-1")
    except UnicodeEncodeError:
        # Keep common Latin text; replace unsupported characters explicitly.
        s = s.encode("iso-8859-1", "replace").decode("iso-8859-1")
    return re.sub(r"\s+", " ", s).strip()


def normalize_address(addr, sender=False):
    addr = addr if isinstance(addr, dict) else {}
    result = {
        "name1": latin1_clean(addr.get("name1")),
        "name2": latin1_clean(addr.get("name2")),
        "name3": latin1_clean(addr.get("name3")),
        "street": latin1_clean(addr.get("street")),
        "streetNumber": latin1_clean(addr.get("streetNumber")),
        "plz": latin1_clean(addr.get("plz")),
        "city": latin1_clean(addr.get("city")),
        "country": latin1_clean(addr.get("country") or "DEU").upper(),
        "email": latin1_clean(addr.get("email")),
        "phone": latin1_clean(addr.get("phone")),
        "addressAddition1": latin1_clean(addr.get("addressAddition1")),
        "addressAddition2": latin1_clean(addr.get("addressAddition2")),
        "address_type": latin1_clean(addr.get("address_type") or "street").lower(),
        "deliveryLine": latin1_clean(addr.get("deliveryLine")),
    }
    return {k: v for k, v in result.items() if v != ""}


def validate_german_address(addr, sender=False):
    if not sender and addr.get("address_type") == "postbox":
        required = ["name2", "deliveryLine", "plz", "city", "country"]
        missing = [k for k in required if not addr.get(k)]
        if missing:
            raise ValueError("Für Postfach / Zustellzeile fehlen Angaben: " + ", ".join(missing))
        if addr.get("country") == "DEU" and not re.fullmatch(r"\d{5}", addr.get("plz", "")):
            raise ValueError("Für Deutschland muss die PLZ fünfstellig sein.")
        return
    required = ["name2", "street", "streetNumber", "plz", "city", "country"]
    missing = [k for k in required if not addr.get(k)]
    if missing:
        raise ValueError("Fehlende Adressfelder: " + ", ".join(missing))
    if addr.get("country") == "DEU" and not re.fullmatch(r"\d{5}", addr.get("plz", "")):
        raise ValueError("Für Deutschland muss die PLZ fünfstellig sein.")


def api_request(url, api_key="", method="GET", payload=None, headers=None, timeout=25):
    hdr = {
        "Accept": "application/json",
        "User-Agent": f"HomeAssistant-PostDHL/{VERSION}",
    }
    if api_key:
        hdr["dhl-api-key"] = api_key
    if headers:
        hdr.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdr["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            content_type = r.headers.get("Content-Type", "")
            return r.status, dict(r.headers), raw, content_type
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), raw, e.headers.get("Content-Type", "")


def form_request(url, fields, headers=None, timeout=25):
    hdr = {
        "Accept": "application/json",
        "User-Agent": f"HomeAssistant-PostDHL/{VERSION}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if headers:
        hdr.update(headers)
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, dict(r.headers), raw, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), raw, e.headers.get("Content-Type", "")


def decode_body(raw, content_type=""):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        try:
            return json.loads(raw.decode("iso-8859-1"))
        except Exception:
            return raw.decode("utf-8", "replace")[:4000]


def extract_products(catalog):
    """Return product dicts with their catalog key injected as id.

    DHL Private Shipping returns `products` as an associative object whose keys are
    the actual product ids (for example PAK05). Older app code expected a list.
    """
    if not isinstance(catalog, dict):
        return []
    products = catalog.get("products")
    if isinstance(products, dict):
        out = []
        for pid, value in products.items():
            if not isinstance(value, dict):
                continue
            item = dict(value)
            item.setdefault("id", str(pid))
            out.append(item)
        return out
    if isinstance(products, list):
        return products
    return []


def _label_text(value):
    if isinstance(value, dict):
        return str(value.get("text") or value.get("label") or value.get("name") or "")
    return str(value or "")


def product_summary(p):
    if not isinstance(p, dict):
        return None
    pid = p.get("id") or p.get("productId") or p.get("key") or p.get("code")
    if not pid:
        return None

    attrs = p.get("attributes") if isinstance(p.get("attributes"), dict) else {}
    name = (
        _label_text(attrs.get("displayName"))
        or _label_text(p.get("displayName"))
        or str(p.get("name") or p.get("title") or pid)
    )
    description = _label_text(attrs.get("displayDescription"))

    # For the domestic UI prefer the price region containing DEU, then the first
    # available region. ProductCatalogPrice.amount is the gross amount in EUR.
    regions = p.get("regions") if isinstance(p.get("regions"), list) else []
    chosen_region = None
    for region in regions:
        if not isinstance(region, dict) or region.get("unavailable") is True:
            continue
        countries = region.get("countries") or []
        if "DEU" in countries:
            chosen_region = region
            break
        if chosen_region is None:
            chosen_region = region
    price_obj = chosen_region.get("price") if isinstance(chosen_region, dict) else None
    price = price_obj.get("amount") if isinstance(price_obj, dict) else None
    currency = "EUR"

    dimensions = {
        "minLength": attrs.get("minLength"),
        "maxLength": attrs.get("maxLength"),
        "minWidth": attrs.get("minWidth"),
        "maxWidth": attrs.get("maxWidth"),
        "minDepth": attrs.get("minDepth"),
        "maxDepth": attrs.get("maxDepth"),
    }
    dimensions = {k: v for k, v in dimensions.items() if v is not None}
    weight = attrs.get("maxWeight")

    return {
        "id": str(pid),
        "name": name,
        "description": description,
        "price": price,
        "currency": currency,
        "weight": weight,
        "dimensions": dimensions,
        "tracking": attrs.get("tracking"),
        "availableServices": p.get("availableServices") if isinstance(p.get("availableServices"), list) else [],
    }


def filter_private_products(products):
    """Nur die sechs im Alltag gewünschten nationalen Produkte ausgeben."""
    by_id = {str(p.get("id")): dict(p) for p in products if isinstance(p, dict) and p.get("id")}
    out = []
    for pid in PRIVATE_PRODUCT_ORDER:
        p = by_id.get(pid)
        if not p:
            continue
        p["name"] = PRIVATE_PRODUCT_NAMES.get(pid, p.get("name") or pid)
        out.append(p)
    return out


def set_dhl_error(message):
    with STATE_LOCK:
        st = load_state()
        st["dhl"]["last_error"] = str(message)[:3000]
        save_state(st)


def discover_dhl_catalog(force=False):
    opts = load_options()
    key = opts["dhl_private_api_key"]
    if not key:
        raise ValueError("DHL Paket API-Key fehlt in der App-Konfiguration.")

    with CATALOG_LOCK:
        st = load_state()
        dhl = st["dhl"]
        if not force and dhl.get("catalog") and (time.time() - float(dhl.get("catalog_cached_at", 0))) < 86400:
            products = filter_private_products([x for x in (product_summary(p) for p in extract_products(dhl["catalog"])) if x])
            return {
                "base": dhl.get("detected_base") or PRIVATE_BASE,
                "catalog_version": dhl.get("catalog_version") or PRIVATE_CATALOG_VERSION,
                "products": products,
                "cached": True,
            }

        base = (opts["dhl_private_api_base"] or PRIVATE_BASE).rstrip("/")
        ver = PRIVATE_CATALOG_VERSION
        url = f"{base}/catalog/{ver}/products"
        status, hdrs, raw, ctype = api_request(url, api_key=key, timeout=20)
        body = decode_body(raw, ctype)
        if not (200 <= status < 300):
            message = f"DHL Product Catalog HTTP {status}: {json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}"
            dhl["detected_base"] = base
            dhl["catalog_version"] = ver
            dhl["last_error"] = message[:3000]
            save_state(st)
            raise RuntimeError(message)

        products = filter_private_products([x for x in (product_summary(p) for p in extract_products(body)) if x])
        dhl["detected_base"] = base
        dhl["catalog_version"] = ver
        dhl["catalog_cached_at"] = time.time()
        dhl["catalog"] = body
        dhl["last_error"] = ""
        save_state(st)
        return {"base": base, "catalog_version": ver, "products": products, "cached": False}


def dhl_base_required():
    opts = load_options()
    return (opts["dhl_private_api_base"] or PRIVATE_BASE).rstrip("/")


def extract_entry_url(body):
    if not isinstance(body, dict):
        return ""
    download = body.get("download")
    if isinstance(download, dict) and download.get("entryUrl"):
        return str(download["entryUrl"])
    for key in ("shoppingcart", "shoppingCart", "data"):
        val = body.get(key)
        if isinstance(val, dict):
            got = extract_entry_url(val)
            if got:
                return got
    return str(body.get("entryUrl") or "")


def extract_cart_id(body):
    if not isinstance(body, dict):
        return ""
    for key in ("shoppingCartId", "shoppingcartId", "id", "shoppingCartID"):
        if body.get(key):
            return str(body[key])
    for key in ("shoppingcart", "shoppingCart", "data", "download"):
        val = body.get(key)
        if isinstance(val, dict):
            got = extract_cart_id(val)
            if got:
                return got
    return ""


def build_receiver(data):
    kind = str(data.get("address_type") or "street")
    receiver = normalize_address(data.get("receiver", {}), sender=False)
    if kind == "packstation":
        name = receiver.get("name2") or receiver.get("name1", "")
        postnummer = latin1_clean(data.get("postnummer") or receiver.get("postnummer"))
        station = latin1_clean(data.get("station_number") or receiver.get("streetNumber"))
        receiver = {
            "type": "PackstationAddress",
            "name1": name,
            "name2": postnummer,
            "street": "Packstation",
            "streetNumber": station,
            "plz": receiver.get("plz", ""),
            "city": receiver.get("city", ""),
            "country": receiver.get("country", "DEU"),
        }
        if data.get("receiver_email"):
            receiver["email"] = latin1_clean(data.get("receiver_email"))
        for field in ("name1", "name2", "street", "streetNumber", "plz", "city", "country"):
            if not receiver.get(field):
                raise ValueError("Packstation: fehlendes Feld " + field)
    elif kind == "postfiliale":
        name = receiver.get("name2") or receiver.get("name1", "")
        postnummer = latin1_clean(data.get("postnummer") or receiver.get("postnummer"))
        station = latin1_clean(data.get("station_number") or receiver.get("streetNumber"))
        receiver = {
            "type": "ShopAddress",
            "name1": name,
            "name2": postnummer,
            "street": "Postfiliale",
            "streetNumber": station,
            "plz": receiver.get("plz", ""),
            "city": receiver.get("city", ""),
            "country": receiver.get("country", "DEU"),
        }
        if data.get("receiver_email"):
            receiver["email"] = latin1_clean(data.get("receiver_email"))
        for field in ("name1", "name2", "street", "streetNumber", "plz", "city", "country"):
            if not receiver.get(field):
                raise ValueError("Postfiliale: fehlendes Feld " + field)
    else:
        validate_german_address(receiver, sender=False)
    return receiver


def build_cart_payload(data):
    st = load_state()
    sender = normalize_address(data.get("sender") or st.get("sender", {}), sender=True)
    validate_german_address(sender, sender=True)
    receiver = build_receiver(data)
    product_id = latin1_clean(data.get("product_id"))
    if not product_id:
        raise ValueError("Bitte ein DHL-Produkt auswählen.")

    confirmation_email = latin1_clean(data.get("confirmation_email") or sender.get("email"))

    # Shape corresponds to the documented ShoppingCart business object: confirmation,
    # items, address.receiver/sender, product and services. Payment happens later in DHL frontend.
    item = {
        "address": {"receiver": receiver, "sender": sender},
        "product": {"id": product_id},
        "services": data.get("services") if isinstance(data.get("services"), dict) else {},
        "type": "ShipmentItem",
    }
    shoppingcart = {
        "confirmation": ({"email": confirmation_email} if confirmation_email else {}),
        "items": [item],
    }
    # notifyUrl intentionally omitted in 0.1.0: a LAN-only Home Assistant URL is not a valid
    # public HTTPS callback. The app polls cart status after returning from DHL instead.
    return {"shoppingcart": shoppingcart}


def create_dhl_cart(data):
    opts = load_options()
    key = opts["dhl_private_api_key"]
    if not key:
        raise ValueError("DHL Paket API-Key fehlt.")
    base = dhl_base_required()
    payload = build_cart_payload(data)
    url = f"{base}/shopping-carts/pre-paid"
    status, hdrs, raw, ctype = api_request(url, api_key=key, method="POST", payload=payload, timeout=30)
    body = decode_body(raw, ctype)
    if not (200 <= status < 300):
        raise RuntimeError(f"DHL HTTP {status}: {json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}")
    cart_id = extract_cart_id(body)
    entry_url = extract_entry_url(body)
    record = {
        "created_at": now_iso(),
        "shoppingCartId": cart_id,
        "entryUrl": entry_url,
        "product_id": str(data.get("product_id") or ""),
        "receiver_name": str((data.get("receiver") or {}).get("name2") or ""),
        "status": "prepared",
    }
    with STATE_LOCK:
        st = load_state()
        st["recent_carts"].insert(0, record)
        st["recent_carts"] = st["recent_carts"][:50]
        st["dhl"]["last_error"] = ""
        save_state(st)
    return {"shoppingCartId": cart_id, "entryUrl": entry_url, "response": body}


def load_dhl_cart(cart_id):
    opts = load_options()
    if not opts["dhl_private_api_key"]:
        raise ValueError("DHL Paket API-Key fehlt.")
    base = dhl_base_required()
    cid = urllib.parse.quote(str(cart_id), safe="")
    status, hdrs, raw, ctype = api_request(f"{base}/shopping-carts/{cid}", api_key=opts["dhl_private_api_key"], timeout=25)
    body = decode_body(raw, ctype)
    if not (200 <= status < 300):
        raise RuntimeError(f"DHL HTTP {status}: {json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}")
    with STATE_LOCK:
        st = load_state()
        for rec in st.get("recent_carts", []):
            if str(rec.get("shoppingCartId")) == str(cart_id):
                rec["last_checked_at"] = now_iso()
                rec["api_response"] = body
        save_state(st)
    return body


def find_pak_ids(obj):
    found = []
    def walk(v):
        if isinstance(v, dict):
            for k, val in v.items():
                if str(k).lower() in ("pakid", "pak_id") and val:
                    found.append(str(val))
                else:
                    walk(val)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(obj)
    return list(dict.fromkeys(found))


def fetch_dhl_document(identifier, qr=False):
    opts = load_options()
    if not opts["dhl_private_api_key"]:
        raise ValueError("DHL Paket API-Key fehlt.")
    base = dhl_base_required()
    ident = urllib.parse.quote(str(identifier), safe="")
    suffix = "/qr-code" if qr else ""
    url = f"{base}/labels/{ident}{suffix}"
    accept = "image/png" if qr else "application/pdf"
    status, hdrs, raw, ctype = api_request(url, api_key=opts["dhl_private_api_key"], headers={"Accept": accept}, timeout=30)
    if not (200 <= status < 300):
        body = decode_body(raw, ctype)
        raise RuntimeError(f"DHL HTTP {status}: {body}")
    return raw, ctype or ("image/png" if qr else "application/pdf")


def _safe_response_headers(headers):
    if not isinstance(headers, dict):
        return {}
    wanted = {
        "date", "content-type", "server", "x-request-id", "x-correlation-id",
        "x-correlationid", "x-apigee-message-id", "x-envoy-upstream-service-time",
        "via", "traceparent",
    }
    out = {}
    for key, value in headers.items():
        if str(key).lower() in wanted and value:
            out[str(key)] = str(value)[:300]
    return out


def internetmarke_diagnostics():
    """Read-only diagnostics. Does not create a cart, voucher or charge the wallet."""
    opts = load_options()
    result = {
        "cost_free": True,
        "server": {},
        "products": {},
        "authorization": {},
        "profile": {},
    }

    # Official ApiVersionResource / healthcheck. The DHL Postman collection sends this without auth.
    try:
        status, hdrs, raw, ctype = api_request(INTERNETMARKE_BASE + "/", timeout=20)
        body = decode_body(raw, ctype)
        result["server"] = {
            "ok": 200 <= status < 300,
            "status": status,
            "headers": _safe_response_headers(hdrs),
            "body": body if isinstance(body, (dict, list)) else str(body or "")[:1000],
        }
    except Exception as exc:
        result["server"] = {"ok": False, "error": str(exc)}

    # Compare both known Products API paths, each once without and once with API key.
    # These requests are GET-only and do not create any chargeable object.
    key = opts.get("internetmarke_api_key") or ""
    product_tests = []
    path_defs = [
        ("Dokumentierter Pfad", INTERNETMARKE_PRODUCTS_URL_DOCUMENTED),
        ("Alternativpfad", INTERNETMARKE_PRODUCTS_URL_ALTERNATE),
    ]
    for path_label, url in path_defs:
        for auth_label, api_key in (("ohne API-Key", ""), ("mit API-Key", key)):
            if auth_label == "mit API-Key" and not key:
                product_tests.append({
                    "label": f"{path_label} · {auth_label}",
                    "url": url,
                    "skipped": True,
                    "error": "INTERNETMARKE API-Key fehlt.",
                })
                continue
            try:
                status, hdrs, raw, ctype = api_request(url, api_key=api_key, timeout=20)
                body = decode_body(raw, ctype)
                safe_headers = _safe_response_headers(hdrs)
                rows = _im_catalog_rows(body)
                product_tests.append({
                    "label": f"{path_label} · {auth_label}",
                    "url": url,
                    "status": status,
                    "ok": 200 <= status < 300,
                "count": len(rows),
                    "request_id": safe_headers.get("x-request-id") or safe_headers.get("X-Request-Id"),
                    "headers": safe_headers,
                    "body": body if isinstance(body, (dict, list)) else str(body or "")[:1000],
                })
            except Exception as exc:
                product_tests.append({
                    "label": f"{path_label} · {auth_label}",
                    "url": url,
                    "ok": False,
                    "error": str(exc),
                })

    keyed = [x for x in product_tests if "mit API-Key" in x.get("label", "") and not x.get("skipped")]
    result["products"] = {
        "ok": any(x.get("ok") for x in keyed),
        "tests": product_tests,
        "summary": "Vier reine GET-Tests: beide Pfade jeweils ohne und mit API-Key.",
    }

    # Token request exactly follows the official DHL Postman collection. No purchase is performed.
    required = [
        opts.get("internetmarke_api_key"), opts.get("internetmarke_api_secret"),
        opts.get("portokasse_username"), opts.get("portokasse_password"),
    ]
    if not all(required):
        result["authorization"] = {"ok": False, "error": "INTERNETMARKE/Portokasse-Zugangsdaten unvollständig."}
        return result

    try:
        status, hdrs, raw, ctype = form_request(
            INTERNETMARKE_BASE + "/user",
            {
                "client_id": opts["internetmarke_api_key"],
                "client_secret": opts["internetmarke_api_secret"],
                "username": opts["portokasse_username"],
                "password": opts["portokasse_password"],
                "grant_type": "client_credentials",
            },
            timeout=25,
        )
        body = decode_body(raw, ctype)
        token = ""
        if isinstance(body, dict):
            token = str(body.get("access_token") or body.get("userToken") or "")
        safe_headers = _safe_response_headers(hdrs)
        result["authorization"] = {
            "ok": 200 <= status < 300 and bool(token),
            "status": status,
            "token_received": bool(token),
            "request_id": safe_headers.get("x-request-id") or safe_headers.get("X-Request-Id"),
            "headers": safe_headers,
            "body": None if token else (body if isinstance(body, (dict, list)) else str(body or "")[:1000]),
        }
        if token:
            pstatus, phdrs, praw, pctype = api_request(
                INTERNETMARKE_BASE + "/user/profile",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=20,
            )
            pbody = decode_body(praw, pctype)
            psafe = _safe_response_headers(phdrs)
            result["profile"] = {
                "ok": 200 <= pstatus < 300,
                "status": pstatus,
                "balance": _find_balance(pbody),
                "request_id": psafe.get("x-request-id") or psafe.get("X-Request-Id"),
                "headers": psafe,
                "body_type": type(pbody).__name__,
            }
    except Exception as exc:
        result["authorization"] = {"ok": False, "error": str(exc)}
    return result


def internetmarke_authorize(include_response=False):
    opts = load_options()
    missing = [
        name for name, value in (
            ("INTERNETMARKE API-Key", opts["internetmarke_api_key"]),
            ("INTERNETMARKE API-Secret", opts["internetmarke_api_secret"]),
            ("Portokasse Benutzername", opts["portokasse_username"]),
            ("Portokasse Passwort", opts["portokasse_password"]),
        ) if not value
    ]
    if missing:
        raise ValueError("Fehlende Zugangsdaten: " + ", ".join(missing))

    status, hdrs, raw, ctype = form_request(
        INTERNETMARKE_BASE + "/user",
        {
            "client_id": opts["internetmarke_api_key"],
            "client_secret": opts["internetmarke_api_secret"],
            "username": opts["portokasse_username"],
            "password": opts["portokasse_password"],
            "grant_type": "client_credentials",
        },
        timeout=25,
    )
    body = decode_body(raw, ctype)
    if not (200 <= status < 300):
        if status == 401:
            raise RuntimeError(
                "INTERNETMARKE HTTP 401: Zugangsdaten wurden abgelehnt. Bei der ersten "
                "Portokassen-Nutzung muss die Geschäftsanwendung zusätzlich in der Portokasse "
                "unter Meine Daten → Geschäftsanwendungen freigegeben werden."
            )
        safe_headers = _safe_response_headers(hdrs)
        suffix = f" · Diagnose-Header: {safe_headers}" if safe_headers else ""
        raise RuntimeError(
            f"INTERNETMARKE HTTP {status}: "
            f"{json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}{suffix}"
        )
    if not isinstance(body, dict):
        raise RuntimeError("INTERNETMARKE: unerwartete Token-Antwort.")
    token = str(body.get("access_token") or body.get("userToken") or "")
    if not token:
        raise RuntimeError("INTERNETMARKE: Token fehlt in der Antwort.")
    return (token, body) if include_response else token


def _find_balance(obj):
    wanted = {"walletballance", "walletbalance", "balance", "wallet_balance", "credit", "creditbalance"}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in wanted and isinstance(value, (int, float, str)):
                return value
        for value in obj.values():
            found = _find_balance(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_balance(value)
            if found is not None:
                return found
    return None


def _balance_cents(balance):
    """The INTERNETMARKE profile reports wallet balances in eurocents."""
    if balance is None:
        return None
    try:
        value = Decimal(str(balance).strip().replace(",", "."))
        if value != value.to_integral_value():
            return None
        return int(value)
    except (InvalidOperation, ValueError):
        return None


def internetmarke_health():
    opts = load_options()
    api_ready = bool(opts["internetmarke_api_key"] and opts["internetmarke_api_secret"])
    wallet_ready = bool(opts["portokasse_username"] and opts["portokasse_password"])
    if not api_ready:
        return {"ok": False, "configured": False, "message": "INTERNETMARKE API-Key/Secret noch nicht vollständig hinterlegt."}
    if not wallet_ready:
        return {"ok": False, "configured": False, "message": "Portokassen-Benutzername/Passwort fehlen noch."}

    try:
        # The official 1.30 workflow authenticates the Portokasse via POST /user
        # using client_id/client_secret + Portokasse credentials and then uses the
        # returned Bearer token for /user/profile.
        token, auth_body = internetmarke_authorize(include_response=True)
        status, hdrs, raw, ctype = api_request(
            INTERNETMARKE_BASE + "/user/profile",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=20,
        )
        body = decode_body(raw, ctype)
        if not (200 <= status < 300):
            raise RuntimeError(
                f"INTERNETMARKE Profil HTTP {status}: "
                f"{json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}"
            )
        # Depending on the currently active INTERNETMARKE API version, the
        # balance appears either in the sign-in response or in the profile.
        profile_balance = _find_balance(body)
        authorization_balance = _find_balance(auth_body)
        balance = profile_balance if profile_balance is not None else authorization_balance
        balance_cents = _balance_cents(balance)
        msg = ""
        if balance is not None:
            msg += f" Guthaben: {balance}"
        return {
            "ok": True,
            "configured": True,
            "status": status,
            "message": msg,
            "balance": balance,
            "balance_cents": balance_cents,
            "balance_source": "profile" if profile_balance is not None else ("authorization" if authorization_balance is not None else ""),
        }
    except Exception as exc:
        return {"ok": False, "configured": True, "message": str(exc)}


def internetmarke_api_request(path, token, method="GET", payload=None, query=None, timeout=35):
    url = INTERNETMARKE_BASE + path
    if query:
        items = []
        if isinstance(query, dict):
            for key, value in query.items():
                if isinstance(value, (list, tuple)):
                    for v in value:
                        items.append((key, v))
                else:
                    items.append((key, value))
        else:
            items = list(query)
        qs = urllib.parse.urlencode(items, doseq=True)
        if qs:
            url += ("?" if "?" not in url else "&") + qs
    return api_request(
        url,
        method=method,
        payload=payload,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=timeout,
    )


def _im_pick_page_format(catalog, preferred_id=5):
    formats = catalog.get("pageFormats") if isinstance(catalog, dict) else None
    if not isinstance(formats, list):
        return preferred_id
    preferred = None
    first_addressable = None
    first_any = None
    for item in formats:
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        if pid is None:
            continue
        if first_any is None:
            first_any = pid
        if item.get("isAddressPossible") and first_addressable is None:
            first_addressable = pid
        if str(pid) == str(preferred_id):
            preferred = pid
    return preferred or first_addressable or first_any or preferred_id


def _im_find_first_image_id(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            lk = str(key).lower()
            if lk in ("imageid", "image_id") and isinstance(value, (int, float, str)):
                try:
                    return int(value)
                except Exception:
                    pass
        for key, value in obj.items():
            lk = str(key).lower()
            if any(tok in lk for tok in ("image", "motive", "public", "catalog", "items", "motives")):
                found = _im_find_first_image_id(value)
                if found is not None:
                    return found
        for value in obj.values():
            found = _im_find_first_image_id(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _im_find_first_image_id(value)
            if found is not None:
                return found
    return None


def internetmarke_catalog(token=None):
    own_token = token or internetmarke_authorize()
    status, hdrs, raw, ctype = internetmarke_api_request(
        "/app/catalog",
        own_token,
        query=[("types", "PUBLIC"), ("types", "PAGE_FORMATS")],
        timeout=25,
    )
    body = decode_body(raw, ctype)
    if not (200 <= status < 300):
        raise RuntimeError(
            f"INTERNETMARKE Katalog HTTP {status}: "
            f"{json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}"
        )
    return body if isinstance(body, dict) else {}


def _internetmarke_name_for_product(name, max_weight=None):
    # Produktnummern sind nicht dauerhaft einer Briefart zugeordnet. Die
    # vorherige Zuordnung (z. B. Code 21 = Maxibrief) war falsch: Im aktuellen
    # Katalog konnte derselbe Code einen Großbrief mit anderem Preis meinen.
    # Deshalb wird eine Briefart ausschließlich aus der DHL-Produktbezeichnung
    # plus Preis und Gewicht geprüft.
    text = str(name or "").strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold().replace("ß", "ss")).strip()
    # Nur die nackten Basisprodukte dürfen als normale Briefmarken erscheinen.
    # Varianten mit Einschreiben, Rückschein oder anderen Zusatzleistungen
    # bleiben bewusst ausgeschlossen, auch wenn sie dasselbe Format haben.
    if normalized == "standardbrief":
        return "Standardbrief"
    if normalized == "kompaktbrief":
        return "Kompaktbrief"
    if normalized in {"grossbrief", "gro brief"}:
        return "Großbrief"
    if normalized == "maxibrief":
        return "Maxibrief"
    # DHL liefert aktuell die beiden eindeutigen Bezeichnungen unten. Der
    # zweite Eintrag enthält den Gewichtszuschlag bereits im Gesamtpreis.
    if normalized in {"warensendung", "bucher und warensendung", "b cher und warensendung"}:
        if _im_weight_value(max_weight) == 1000:
            return "Warensendung 1 kg"
    if normalized in {
        "warensendung 2 000 gewichtszuschlag",
        "bucher und warensendung 2 000 gewichtszuschlag",
        "b cher und warensendung 2 000 gewichtszuschlag",
    } and _im_weight_value(max_weight) == 2000:
        return "Warensendung 2 kg"
    return ""


def _im_value(row, *names):
    """Read a catalog field independent of DHL's attribute casing."""
    if not isinstance(row, dict):
        return None
    wanted = {str(name).lower() for name in names}
    for key, value in row.items():
        if str(key).lower() in wanted:
            return value
    return None


def _im_price_value(value):
    """Normalize the documented grossprice or a compatible money object."""
    if isinstance(value, dict):
        value = _im_value(value, "amount", "value", "grossprice", "grossPrice", "price")
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "").replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        amount = Decimal(match.group(0)) if match else None
        if amount is None or amount <= 0:
            return None
        return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def _im_weight_value(value):
    if value in (None, ""):
        return None
    try:
        match = re.search(r"\d+(?:[.,]\d+)?", str(value))
        return float(match.group(0).replace(",", ".")) if match else None
    except (TypeError, ValueError):
        return None


def _im_matches_national_spec(name, price, max_weight):
    """Only accept an exact, current DHL match for a visible product tile."""
    spec = INTERNETMARKE_NATIONAL_SPECS.get(name)
    if not spec or price is None:
        return False
    weight = _im_weight_value(max_weight)
    return abs(float(price) - spec["price"]) < 0.001 and weight == spec["max_weight"]


def _im_catalog_rows(body):
    if not isinstance(body, dict):
        return []
    for name in ("shortSalesProducts", "salesProducts", "products"):
        rows = _im_value(body, name)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _im_products_from_catalog(body):
    products = []
    for row in _im_catalog_rows(body):
        code = _im_value(row, "extProductid", "extProductId")
        raw_name = _im_value(row, "extProductname", "extProductName", "productname", "productName")
        transport = str(_im_value(row, "transport", "region") or "").casefold()
        # Diese Oberfläche ist ausschließlich für deutsche Empfänger gedacht.
        # Bei gleichem Namen stehen internationale Produkte im Katalog häufig
        # vor den nationalen; sie dürfen die Inlandspreise nicht überlagern.
        # Kein Teilstring-Vergleich: "national" steckt auch in
        # "international". Das war der Grund, warum die im Screenshot
        # sichtbaren internationalen Preise trotz Filter durchkamen.
        transport_words = set(re.findall(r"[a-zäöüß]+", transport))
        if not transport_words.intersection({"national", "inland", "domestic", "deutschland"}):
            continue
        max_weight = _im_value(row, "maxWeight")
        name = _internetmarke_name_for_product(raw_name, max_weight)
        if code in (None, "") or not name:
            continue
        try:
            int(str(code))
        except (TypeError, ValueError):
            # Nur ein von INTERNETMARKE tatsächlich akzeptierbarer Produktcode
            # darf als kaufbare Kachel auftauchen.
            continue
        price = _im_price_value(_im_value(row, "grossprice", "grossPrice", "price", "salesPrice"))
        # Keine Preisreserve und keine Näherung: Bei einer Katalogänderung
        # wird lieber nichts angeboten als ein falsches Porto bestellt.
        if not _im_matches_national_spec(name, price, max_weight):
            continue
        products.append({
            "productCode": str(code),
            "name": name,
            "price": price,
            "currency": _im_value(row, "currency") or "EUR",
            "transport": _im_value(row, "transport") or "national",
            "minWeight": _im_value(row, "minWeight"),
            "maxWeight": max_weight,
            "maxLength": _im_value(row, "maxLength"),
            "maxWidth": _im_value(row, "maxWidth"),
            "maxHeight": _im_value(row, "maxHeight"),
            "price_source": "DHL Products API, national geprüft",
        })
    order_rank = {
        "Standardbrief": 1,
        "Kompaktbrief": 2,
        "Großbrief": 3,
        "Maxibrief": 4,
        "Warensendung 1 kg": 5,
        "Warensendung 2 kg": 6,
    }
    dedup = {}
    for product in products:
        # Bei doppelt gelieferten, identisch geprüften Produkten hat der erste
        # (dokumentierte) DHL-Endpunkt Vorrang.
        old = dedup.get(product["name"])
        if old is None:
            dedup[product["name"]] = product
    return sorted(dedup.values(), key=lambda x: (order_rank.get(x.get("name"), 999), x.get("price", 99999)))


def internetmarke_products():
    opts = load_options()
    key = opts["internetmarke_api_key"]
    if not key:
        raise ValueError("INTERNETMARKE API-Key fehlt.")
    attempts = []
    status = None
    hdrs = {}
    raw = b""
    ctype = ""
    body = None
    used_url = ""
    found_products = {}
    response_dates = []
    used_urls = []
    for url in INTERNETMARKE_PRODUCTS_URLS:
        status, hdrs, raw, ctype = api_request(url, api_key=key, timeout=25)
        body = decode_body(raw, ctype)
        products = _im_products_from_catalog(body) if 200 <= status < 300 else []
        attempts.append({"url": url, "status": status, "verified_products": len(products)})
        if 200 <= status < 300:
            used_urls.append(url)
            if isinstance(body, dict) and body.get("date"):
                response_dates.append(body.get("date"))
            # Manche DHL-Antworten enthalten nur einen Teil der Produkte. Die
            # geprüften Treffer beider offiziellen Katalogpfade werden daher
            # nach Briefart zusammengeführt, nie durch den bloß längsten Teil
            # ersetzt.
            for product in products:
                found_products.setdefault(product["name"], product)
            if len(found_products) >= len(INTERNETMARKE_NATIONAL_SPECS):
                break
    if not found_products:
        safe_headers = _safe_response_headers(hdrs)
        raise RuntimeError(
            f"Products API liefert keine kaufbaren Briefprodukte (letzter HTTP {status}): "
            f"{json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}"
            f" · Versuche: {json.dumps(attempts, ensure_ascii=False)}"
            f" · Diagnose-Header: {json.dumps(safe_headers, ensure_ascii=False)}"
        )
    order_rank = {name: index for index, name in enumerate(INTERNETMARKE_NATIONAL_SPECS, start=1)}
    products = sorted(found_products.values(), key=lambda product: order_rank.get(product.get("name"), 999))
    return {
        "products": products,
        "date": response_dates[0] if response_dates else None,
        "endpoint": ", ".join(used_urls),
        "attempts": attempts,
    }


def _build_internetmarke_address(addr, sender=False):
    clean = normalize_address(addr, sender=sender)
    validate_german_address(clean, sender=sender)
    if not sender and clean.get("address_type") == "postbox":
        line1 = clean.get("deliveryLine", "").strip()
    else:
        line1 = " ".join([x for x in [clean.get("street", "").strip(), clean.get("streetNumber", "").strip()] if x]).strip()
    if not line1:
        raise ValueError("Eine Zustellzeile wird für die INTERNETMARKE benötigt.")
    display_name = clean.get("name2") or clean.get("name1") or ""
    display_addition = clean.get("addressAddition1") or clean.get("name3") or ""
    # INTERNETMARKE prints additionalName above name.  Swap the two optional
    # display lines so the app's "Name / Firma" remains on the first line and
    # its "Adresszusatz" appears directly below it on the printed stamp.
    result = {
        "name": display_addition or display_name,
        "addressLine1": line1,
        "postalCode": clean.get("plz") or "",
        "city": clean.get("city") or "",
        "country": clean.get("country") or "DEU",
    }
    if display_addition:
        result["additionalName"] = display_name
    if clean.get("addressAddition2"):
        result["addressLine2"] = clean["addressAddition2"]
    if not result["name"]:
        raise ValueError("Name/Firma fehlt für die INTERNETMARKE.")
    return result


def _im_select_product_meta(product_code):
    products = internetmarke_products().get("products", [])
    for p in products:
        if (
            str(p.get("productCode")) == str(product_code)
            and _im_matches_national_spec(p.get("name"), p.get("price"), p.get("maxWeight"))
        ):
            return p
    raise ValueError(
        "Das gewählte Produkt wurde vor dem Kauf nicht als passender nationaler "
        "Briefpreis bestätigt. Bitte Produkte neu laden und erneut auswählen."
    )


def _im_total_cents(price):
    """Convert the Products API's gross EUR price to the integer cents DHL expects."""
    if isinstance(price, dict):
        price = price.get("amount") if price.get("amount") is not None else price.get("value")
    if price in (None, ""):
        raise ValueError("Der Preis des gewählten Briefprodukts konnte nicht geladen werden.")
    try:
        amount = Decimal(str(price).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("Der Preis des gewählten Briefprodukts ist ungültig.")
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents <= 0:
        raise ValueError("Der Preis des gewählten Briefprodukts ist ungültig.")
    return cents


def create_internetmarke_order(data):
    token = internetmarke_authorize()
    product_code = str(data.get("product_code") or data.get("productCode") or "").strip()
    if not product_code:
        raise ValueError("Bitte zuerst ein Briefprodukt auswählen.")
    product_meta = _im_select_product_meta(product_code)
    total = _im_total_cents(product_meta.get("price"))
    with STATE_LOCK:
        st = load_state()
    sender = _build_internetmarke_address(data.get("sender") or st.get("sender", {}), sender=True)
    receiver = _build_internetmarke_address(data.get("receiver", {}), sender=False)
    catalog = {}
    page_format_id = data.get("page_format_id") or data.get("pageFormatId") or 5
    image_id = data.get("image_id") or data.get("imageId")
    try:
        catalog = internetmarke_catalog(token=token)
    except Exception:
        catalog = {}
    page_format_id = _im_pick_page_format(catalog, preferred_id=page_format_id)
    if image_id in (None, ""):
        image_id = _im_find_first_image_id(catalog)
    payload = {
        "type": "AppShoppingCartPDFRequest",
        "dpi": str(data.get("dpi") or "DPI300"),
        "pageFormatId": int(page_format_id),
        "createManifest": False,
        "createShippingList": "2",
        "total": total,
        "positions": [
            {
                # The PDF checkout endpoint requires its PDF-specific position
                # type and a placement on the selected PDF page. The generic
                # AppShoppingCartPosition is rejected with PCF-A1034.
                "positionType": "AppShoppingCartPDFPosition",
                "productCode": int(product_code),
                "voucherLayout": str(data.get("voucher_layout") or data.get("voucherLayout") or "ADDRESS_ZONE"),
                "position": {"labelX": 1, "labelY": 1, "page": 1},
                "address": {"sender": sender, "receiver": receiver},
            }
        ],
    }
    if image_id not in (None, ""):
        try:
            payload["positions"][0]["imageID"] = int(image_id)
        except Exception:
            pass
    status, hdrs, raw, ctype = internetmarke_api_request(
        "/app/shoppingcart/pdf",
        token,
        method="POST",
        payload=payload,
        # `validate` is exclusively for preview requests. A direct checkout is
        # the actual purchase and must only carry directCheckout=true.
        query={"directCheckout": "true"},
        timeout=45,
    )
    body = decode_body(raw, ctype)
    if not (200 <= status < 300):
        raise RuntimeError(
            f"INTERNETMARKE HTTP {status}: "
            f"{json.dumps(body, ensure_ascii=False) if isinstance(body,(dict,list)) else body}"
        )
    if not isinstance(body, dict):
        raise RuntimeError("INTERNETMARKE: unerwartete Antwort beim Erstellen der Briefmarke.")
    shopping_cart = body.get("shoppingCart") if isinstance(body.get("shoppingCart"), dict) else {}
    record = {
        "created_at": now_iso(),
        "shopOrderId": shopping_cart.get("shopOrderId") or body.get("shopOrderId") or "",
        "link": body.get("link") or "",
        "manifestLink": body.get("manifestLink") or "",
        "product_code": product_code,
        "product_name": product_meta.get("name") or product_code,
        "receiver_name": receiver.get("additionalName") or receiver.get("name") or "",
        "voucher_ids": [v.get("voucherId") for v in shopping_cart.get("voucherList", []) if isinstance(v, dict) and v.get("voucherId")],
    }
    with STATE_LOCK:
        st = load_state()
        st["recent_internetmarke"].insert(0, record)
        st["recent_internetmarke"] = st.get("recent_internetmarke", [])[:50]
        save_state(st)
    return {"order": {**record, "response": body}, "payload": payload}


def _internetmarke_order_link(index):
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise ValueError("Ungültige Internetmarke.")
    with STATE_LOCK:
        orders = load_state().get("recent_internetmarke", [])
    if index < 0 or index >= len(orders) or not isinstance(orders[index], dict):
        raise ValueError("Internetmarke nicht gefunden.")
    link = str(orders[index].get("link") or "").strip()
    parsed = urllib.parse.urlparse(link)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Für diese Internetmarke ist kein druckbares PDF vorhanden.")
    return index, link


def fetch_internetmarke_document(index):
    """Fetch a saved, DHL-provided PDF link for the app's same-origin print view."""
    _, link = _internetmarke_order_link(index)
    status, _headers, raw, ctype = api_request(
        link,
        headers={"Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1"},
        timeout=45,
    )
    if not (200 <= status < 300):
        raise RuntimeError(f"Internetmarken-PDF HTTP {status}.")
    if not raw:
        raise RuntimeError("Das Internetmarken-PDF ist leer.")
    return raw, ctype or "application/pdf"


def internetmarke_print_html(index):
    index, _link = _internetmarke_order_link(index)
    document_url = f"/api/internetmarke/document/{index}"
    return '''<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Internetmarke drucken</title><style>
html,body{margin:0;width:100%;height:100%;background:#f5f6f7;font-family:system-ui,sans-serif}
.hint{position:fixed;z-index:2;left:12px;top:10px;padding:8px 11px;border-radius:7px;background:#fff;border:1px solid #d5d8dc;color:#30343a;font-size:13px}
iframe{width:100%;height:100%;border:0;background:#fff}
@media print{.hint{display:none}}
</style></head><body><div class="hint">Druckdialog wird geöffnet …</div>
<iframe id="pdf" src="__DOCUMENT_URL__" title="Internetmarke PDF"></iframe>
<script>
let printed=false;
function startPrint(){if(printed)return;printed=true;window.focus();window.print();}
document.getElementById('pdf').addEventListener('load',()=>setTimeout(startPrint,350),{once:true});
setTimeout(startPrint,2600);
</script></body></html>'''.replace("__DOCUMENT_URL__", document_url)


INDEX_HTML = r'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Post & DHL Frankierung</title>
<style>
:root{color-scheme:dark;--bg:#07151b;--panel:#0d2028;--panel2:#0a1a21;--line:#24414a;--txt:#eef7f8;--muted:#9bb0b5;--yellow:#ffcc00;--red:#d40511;--green:#45d49c;--blue:#4fb7db}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#061218,#08191f);color:var(--txt);font:15px/1.4 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1120px;margin:0 auto;padding:22px}.head{display:flex;gap:14px;align-items:center;margin-bottom:16px}.logo{width:54px;height:54px;border-radius:16px;background:linear-gradient(135deg,var(--yellow) 0 55%,var(--red) 55%);box-shadow:0 0 0 4px #102c34}.title{font-size:28px;font-weight:800}.sub{color:var(--muted);font-size:13px}.statusrow{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:14px 0}.pill{border:1px solid var(--line);border-radius:12px;padding:9px 12px;background:#0a1920}.pill b{margin-right:5px}.ok{border-color:#24684e}.warn{border-color:#6a5a20}.bad{border-color:#6d2730}.tabs{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0 18px}.tab{border:1px solid var(--line);background:#0a1920;color:var(--txt);padding:10px 15px;border-radius:11px;font-weight:700;cursor:pointer}.tab.active{background:#17333e;border-color:#3b6775}.panel{display:none}.panel.active{display:block}.card{background:rgba(13,32,40,.95);border:1px solid var(--line);border-radius:18px;padding:18px;margin-bottom:14px}.card h2,.card h3{margin:0 0 12px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.field label{display:block;color:var(--muted);font-size:12px;margin:0 0 5px}.field input,.field select,.field textarea{width:100%;background:#07161c;border:1px solid #31505a;color:var(--txt);border-radius:10px;padding:11px 12px;font:inherit}.field input:focus,.field select:focus,.field textarea:focus{outline:2px solid #376a79;border-color:transparent}.btn{border:0;border-radius:11px;padding:11px 16px;font-weight:800;cursor:pointer}.primary{background:var(--yellow);color:#161616}.secondary{background:#15313b;color:var(--txt);border:1px solid #31505a}.danger{background:#4b1b20;color:#fff}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.spacer{flex:1}.muted{color:var(--muted)}.notice{border-left:4px solid var(--yellow);background:#272512;padding:12px;border-radius:8px;margin:10px 0}.success{border-left-color:var(--green);background:#10281f}.error{border-left-color:#ff6370;background:#2c1519}.products{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.product{padding:13px;border:1px solid var(--line);border-radius:13px;background:#091a21;cursor:pointer}.product.selected{border:2px solid var(--yellow);background:#25230e}.product .name{font-weight:800}.product .meta{font-size:12px;color:var(--muted);margin-top:4px}.addressitem,.cartitem{border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:8px;background:#09191f}.tag{display:inline-block;padding:3px 8px;border-radius:99px;background:#16343e;color:#bce8f5;font-size:11px}.hidden{display:none!important}.small{font-size:12px}.right{text-align:right}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:normal;overflow-wrap:anywhere}pre{white-space:pre-wrap;word-break:break-word;background:#061217;border:1px solid var(--line);padding:10px;border-radius:10px;max-height:260px;overflow:auto}.footer{text-align:center;color:#668087;font-size:12px;padding:20px}
@media(max-width:760px){.wrap{padding:12px}.statusrow,.grid2,.grid3,.products{grid-template-columns:1fr}.title{font-size:23px}.head{align-items:flex-start}}

/* 0.1.3: eigenständige Versand-/Frankieroberfläche im DHL-/Post-Schalterstil */
:root{
  color-scheme:light;
  --bg:#f2f3f4;--panel:#ffffff;--panel2:#fafafa;--line:#d8dadd;--txt:#1d1d1b;--muted:#666a70;
  --yellow:#ffcc00;--red:#d40511;--green:#168353;--blue:#156a8a
}
body{background:#f2f3f4;color:var(--txt)}
.wrap{max-width:1180px;padding:0 18px 42px}
.head{position:relative;gap:15px;margin:0 -18px 16px;padding:18px 22px 16px;background:var(--yellow);border-bottom:5px solid var(--red);box-shadow:0 4px 14px rgba(0,0,0,.10)}
.logo{width:68px;height:42px;border-radius:4px;background:#fff;border:2px solid rgba(0,0,0,.08);box-shadow:none;display:grid;place-items:center;transform:skew(-6deg)}
.logo:after{content:"DHL";color:var(--red);font-size:20px;font-weight:950;font-style:italic;letter-spacing:-1.2px;transform:skew(6deg)}
.title{font-size:27px;color:#1d1d1b;letter-spacing:-.45px}.sub{color:#3d3d3b;font-size:12px}
.statusrow{grid-template-columns:1fr 1fr auto;gap:7px;margin:12px 0}.pill{background:#fff;border-color:#d9d9d9;border-radius:6px;padding:8px 10px;box-shadow:0 1px 3px rgba(0,0,0,.04);color:#343434}.pill.ok{border-left:4px solid var(--green)}.pill.warn{border-left:4px solid #b88b00}.pill.bad{border-left:4px solid var(--red)}
.tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin:12px 0 16px;padding:5px;background:#fff;border:1px solid var(--line);border-radius:7px;box-shadow:0 2px 9px rgba(0,0,0,.05)}
.tab{border:0;border-right:1px solid #ececec;background:transparent;color:#4a4a48;padding:11px 9px;border-radius:3px;font-weight:800}.tab:last-child{border-right:0}.tab.active{background:#fff6c9;color:#1d1d1b;box-shadow:inset 0 -3px 0 var(--red)}
.card{position:relative;background:#fff;border:1px solid var(--line);border-left:4px solid var(--yellow);border-radius:7px;padding:17px 18px;margin-bottom:12px;box-shadow:0 3px 12px rgba(0,0,0,.055)}
.card h2,.card h3{color:#252525}.muted{color:var(--muted)}
.field input,.field select,.field textarea{background:#fafafa;border:1px solid #cfd2d5;color:#1f2022;border-radius:5px;padding:10px 11px}.field input:focus,.field select:focus,.field textarea:focus{outline:2px solid rgba(212,5,17,.18);border-color:var(--red)}
#addressType{background:#fafafa!important;color:#1f2022!important;border:1px solid #cfd2d5!important;border-radius:5px!important;padding:10px!important}
.btn{border-radius:5px;padding:10px 14px;box-shadow:none}.primary{background:var(--yellow);color:#1d1d1b;border:1px solid #d5aa00}.primary:hover{filter:brightness(.97)}.secondary{background:#fff;color:#2b2b2b;border:1px solid #cdd0d3}.danger{background:var(--red);color:#fff}
.products{gap:9px}.product{background:#fff;border:2px solid #e2e3e5;border-radius:6px;padding:12px}.product:hover{border-color:#bfc2c5}.product.selected{border-color:var(--red);background:#fff8d9;box-shadow:inset 0 0 0 1px var(--yellow)}
.addressitem,.cartitem{background:#fbfbfb;border-color:#dedfe1;border-radius:6px}.tag{background:#eef6f8;color:#155b70;border-radius:3px}.notice{border-left:4px solid var(--yellow);background:#fff8d7;border-radius:4px;color:#343434}.success{border-left-color:var(--green);background:#eef9f3}.error{border-left-color:var(--red);background:#fff0f1}.mono,pre{color:#202124}pre{background:#f8f8f8;border-color:#dedede;border-radius:5px}.footer{color:#7b7d80;padding:18px}
.diagrow{display:grid;grid-template-columns:minmax(0,1fr) minmax(190px,auto);gap:6px 12px;padding:8px 0;border-bottom:1px solid #e5e5e5;align-items:start}.diagmain,.diagstatus{min-width:0}.diagstatus{text-align:right}.diagurl{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:normal;overflow-wrap:anywhere;white-space:normal;line-height:1.35}.diagrid{min-width:0}
@media(max-width:900px){.statusrow{grid-template-columns:1fr 1fr}.statusrow .pill:last-child{grid-column:1/-1}.products{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){
  .wrap{padding:0 10px 30px}.head{margin:0 -10px 12px;padding:14px 13px 12px;border-bottom-width:4px}.logo{width:58px;height:36px}.logo:after{font-size:17px}.title{font-size:22px}.sub{font-size:10px}
  .statusrow{grid-template-columns:1fr 1fr;gap:5px;margin:9px 0}.statusrow .pill:last-child{grid-column:1/-1}.pill{padding:7px 8px;font-size:11px}
  .tabs{grid-template-columns:repeat(2,minmax(0,1fr));gap:3px;padding:4px}.tab{border:0;padding:10px 6px}.tab.active{box-shadow:inset 0 -3px 0 var(--red)}
  .card{padding:13px 12px;border-left-width:3px}.grid2,.grid3{grid-template-columns:1fr}.products{grid-template-columns:1fr}.row{gap:6px}.btn{padding:10px 11px}
  .diagrow{grid-template-columns:1fr;gap:3px;padding:10px 0}.diagstatus{text-align:left}.diagurl{font-size:11px}.diagstatus .mono{font-size:11px}
}

</style>
<style>
/* 0.1.30: ruhiger Arbeitsablauf statt einer Folge gleich gewichteter Formulare */
body{background:#f5f6f7}.wrap{max-width:1240px;padding:0 24px 48px}.head{margin:0 -24px 18px;padding:16px 24px 14px}.head+.card{display:none}.title{font-size:25px}.sub{font-size:13px}
.tabs{position:sticky;top:0;z-index:2;margin:0 0 20px;padding:4px;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);border-radius:9px;box-shadow:0 3px 14px rgba(0,0,0,.07)}.tab{padding:12px 10px;font-size:14px}.tab.active{background:#fff2b3;box-shadow:inset 0 -3px 0 var(--red)}
.card{border-left:1px solid var(--line);border-radius:10px;padding:20px;box-shadow:0 2px 9px rgba(0,0,0,.045)}.card h2,.card h3{font-size:18px;margin-bottom:14px}.card h2{font-size:22px}.field label{font-size:12px;font-weight:750;color:#555a60}.field input,.field select,.field textarea{min-height:44px;background:#fff;border-color:#d7dade;border-radius:7px}.field textarea{min-height:112px}.btn{min-height:42px;border-radius:7px}.primary{box-shadow:0 1px 0 rgba(0,0,0,.15)}.secondary{background:#fff}.muted{font-size:13px}
#paket.panel.active{display:grid;grid-template-columns:minmax(0,1fr) 330px;grid-template-areas:"product product" "recipient sender" "history history" "message message";gap:0 16px;align-items:start}#paket>.card:nth-of-type(1){grid-area:product}#paket>.card:nth-of-type(2){grid-area:sender}#paket>.card:nth-of-type(3){grid-area:recipient}#paket>.card:nth-of-type(4){grid-area:history}
#brief.panel.active{display:grid;grid-template-columns:330px minmax(0,1fr);grid-template-areas:"product product" "sender recipient" "message message" "history history";gap:0 16px;align-items:start}#brief>.card:nth-of-type(1){grid-area:product}#brief>.card:nth-of-type(2){grid-area:sender}#brief>.card:nth-of-type(3){grid-area:recipient}#brief>.card:nth-of-type(4){grid-area:history}#imRecipientMsg{grid-area:message;margin:-2px 0 12px}
#paket>.card:nth-of-type(1) h2:before,#brief>.card:nth-of-type(1) h3:before,#paket>.card:nth-of-type(2) h3:before,#brief>.card:nth-of-type(2) h3:before,#paket>.card:nth-of-type(3) h3:before,#brief>.card:nth-of-type(3) h3:before{display:inline-grid;place-items:center;width:24px;height:24px;margin-right:8px;border-radius:50%;background:#1d1d1b;color:#fff;font-size:12px}#paket>.card:nth-of-type(1) h2:before,#brief>.card:nth-of-type(1) h3:before{content:"1"}#paket>.card:nth-of-type(2) h3:before,#brief>.card:nth-of-type(2) h3:before{content:"2"}#paket>.card:nth-of-type(3) h3:before,#brief>.card:nth-of-type(3) h3:before{content:"3"}
#dhlSenderSelect,#imSenderSelect{width:100%;min-height:46px;padding:0 12px;background:#fff;border:1px solid #cfd2d5;border-radius:7px;color:#202124;font:inherit;font-weight:750}#dhlSenderPreview,#imSenderPreview{min-height:92px;margin-top:10px!important;padding:14px!important;border:1px solid #e2e4e6;border-left:4px solid var(--yellow)!important;border-radius:7px!important;background:#fffdf0!important;line-height:1.55}#dhlSenderPreview b,#imSenderPreview b{display:block;margin-bottom:4px;font-size:12px;color:#555a60;text-transform:uppercase;letter-spacing:.04em}
.products{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.product{min-height:88px;padding:14px;border-radius:8px;background:#fff}.product.selected{border-color:var(--red);background:#fff8d9}.product .name{font-size:15px}.product .meta{font-size:12px}
.delivery-mode{display:flex;align-items:end;gap:12px;padding:12px 14px;margin:0 0 14px;background:#f7f8f9;border:1px solid #e0e2e4;border-radius:8px}.delivery-mode .field{min-width:210px}.delivery-mode p{margin:0;color:#60646a;font-size:12px}.delivery-line-field{margin:0 0 14px}.delivery-line-field input{font-weight:650}.notice{margin:0;border-radius:7px}.error{background:#fff0f1}.success{background:#effaf3}
#einstellungen.panel.active{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(330px,.75fr);gap:16px;align-items:start}#einstellungen .card{margin:0}#einstellungen h2:after{content:"Gespeicherte Absender für Paket und Brief";display:block;margin-top:4px;color:#666a70;font-size:13px;font-weight:400}#senderList{display:grid;gap:8px}.sender-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;padding:13px 14px;background:#fff;border:1px solid #dee1e4;border-radius:8px}.sender-card .sender-name{font-weight:800}.sender-card .sender-address{margin-top:3px;color:#62666c;font-size:13px}.sender-card .sender-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.sender-card .btn{min-height:34px;padding:7px 10px;font-size:12px}.default-badge{display:inline-block;margin-left:6px;padding:2px 6px;border-radius:99px;background:#fff0b0;color:#5c4700;font-size:11px;font-weight:800}
#einstellungen>.card:nth-of-type(2){background:#fbfbfb}#einstellungen>.card:nth-of-type(2) p{color:#5f6368;font-size:13px}.footer{padding-top:28px}
@media(max-width:900px){#paket.panel.active,#brief.panel.active{display:block}#einstellungen.panel.active{display:block}#einstellungen .card{margin-bottom:14px}.sender-card{grid-template-columns:1fr}.sender-card .sender-actions{justify-content:flex-start}}
@media(max-width:640px){.wrap{padding:0 12px 34px}.head{margin:0 -12px 14px;padding:13px 14px 12px}.title{font-size:21px}.sub{display:none}.tabs{margin-bottom:14px}.card{padding:15px}.products{grid-template-columns:1fr}.delivery-mode{display:block}.delivery-mode .field{margin-bottom:8px}.grid2{grid-template-columns:1fr}.row .primary{width:100%}.spacer{display:none}}
.empty-state{padding:8px 0;color:#62666c;font-size:14px}
</style></head><body><div class="wrap">
<div class="head"><div class="logo"></div><div><div class="title">Post & DHL Frankierung</div><div class="sub">Briefmarken · Pakete · Adressen · direkt aus Home Assistant</div></div></div>
<div class="card"><div class="pill"><b>Version</b> __APP_VERSION__ · Port 8151</div></div>
<div class="tabs"><button class="tab active" data-tab="paket">📦 Paket</button><button class="tab" data-tab="brief">✉️ Briefmarke</button><button class="tab" data-tab="adressen">👤 Adressen</button><button class="tab" data-tab="einstellungen">⚙️ Einstellungen</button></div>

<section id="paket" class="panel active">
<div class="card"><div class="row"><div><h2>DHL Paket</h2></div><div class="spacer"></div></div><div id="products" class="products" style="margin-top:12px"></div></div>
<div class="card"><h3>Absender</h3><select id="dhlSenderSelect" onchange="renderSelectedSenderPreview('dhlSenderSelect','dhlSenderPreview')"></select><div id="dhlSenderPreview" class="notice" style="margin-top:12px"></div></div><div class="card"><h3>Empfänger</h3><div class="field" style="margin-bottom:12px"><label>Schnell einfügen · bis 4 Zeilen</label><textarea id="r_quick" rows="4" placeholder="Max Mustermann&#10;Adresszusatz optional&#10;Musterstraße 12&#10;12345 Musterstadt"></textarea><div class="row" style="margin-top:8px"><button class="btn secondary" onclick="applyQuickAddress('r')">Name / Adresse / PLZ übernehmen</button></div></div><div class="row" style="margin-bottom:12px"><button class="btn secondary" onclick="fillFromAddressBook('paket')">Aus Adressbuch</button><select id="addressType" onchange="toggleAddressType()" style="background:#07161c;color:white;border:1px solid #31505a;border-radius:10px;padding:10px"><option value="street">Normale Adresse</option><option value="packstation">Packstation</option><option value="postfiliale">Postfiliale</option></select></div>
<div class="grid2"><div class="field"><label>Name / Firma</label><input id="r_name2" autocomplete="name"></div><div class="field"><label>E-Mail optional</label><input id="r_email" type="email"></div><div class="field"><label>Adresszusatz optional</label><input id="r_add1"></div><div class="field hidden" aria-hidden="true"></div><div id="streetField" class="field"><label>Straße</label><input id="r_street"></div><div id="numberField" class="field"><label>Hausnummer</label><input id="r_number"></div><div id="stationFields" class="grid2 hidden" style="grid-column:1/-1"><div class="field"><label>Postnummer</label><input id="r_postnummer"></div><div class="field"><label id="stationLabel">Packstationsnummer</label><input id="r_station"></div></div><div class="field"><label>PLZ</label><input id="r_plz" inputmode="numeric"></div><div class="field"><label>Ort</label><input id="r_city"></div></div>
<div class="row" style="margin-top:14px"><button class="btn secondary" onclick="saveRecipient()">Empfänger merken</button><div class="spacer"></div><button id="cartBtn" class="btn primary" onclick="createCart()">DHL-Warenkorb öffnen</button></div><div id="cartMsg"></div></div>
<div class="card"><h3>Letzte Paketvorgänge</h3><div id="recentCarts" class="muted">Noch keine.</div></div>
</section>

<section id="brief" class="panel">

<div class="card"><h3>Briefmarken</h3><div class="row" style="margin:0 0 12px;padding:10px 12px;background:#fffdf0;border:1px solid #e4e0c8;border-radius:7px"><div><b>Portokassen-Guthaben</b><div id="imBalance" class="muted small" role="status" aria-live="polite">Wird nach dem Laden abgefragt …</div></div><div class="spacer"></div><button class="btn secondary" onclick="loadIMBalance()">Guthaben aktualisieren</button></div><div id="imProducts" class="products" style="margin-top:12px"></div><div id="imProductsMsg" role="status" aria-live="polite"></div></div>
<div class="card"><h3>Absender</h3><select id="imSenderSelect" onchange="renderSelectedSenderPreview('imSenderSelect','imSenderPreview')"></select><div id="imSenderPreview" class="notice" style="margin-top:12px"></div></div><div class="card"><h3>Empfänger für Briefmarke</h3><div class="field" style="margin-bottom:12px"><label>Schnell einfügen · bis 4 Zeilen</label><textarea id="im_r_quick" rows="4" placeholder="AOK Hessen&#10;Die Gesundheitskasse in Hessen&#10;Musterstraße 12&#10;12345 Musterstadt"></textarea><div class="row" style="margin-top:8px"><button class="btn secondary" onclick="applyQuickAddress('im_r')">Adresse übernehmen</button><button class="btn secondary" onclick="fillFromAddressBook('brief')">Aus Adressbuch</button></div></div><div class="grid2"><div class="field"><label>Name / Firma</label><input id="im_r_name2"></div><div class="field"><label>Adresszusatz optional</label><input id="im_r_add1"></div><div class="field"><label>Straße</label><input id="im_r_street"></div><div class="field"><label>Hausnummer</label><input id="im_r_number"></div><div class="field"><label>PLZ</label><input id="im_r_plz" inputmode="numeric"></div><div class="field"><label>Ort</label><input id="im_r_city"></div></div><div class="row" style="margin-top:14px"><button class="btn secondary" onclick="saveRecipient('brief')">Empfänger merken</button><div class="spacer"></div><button id="imCreateBtn" class="btn primary" onclick="createInternetmarke()">Internetmarke erstellen</button></div></div><div class="card"><h3>Letzte Internetmarken</h3><div id="recentInternetmarke" class="muted">Noch keine.</div></div>
<div id="imRecipientMsg" role="status" aria-live="polite"></div>
</section>

<section id="adressen" class="panel">
<div class="card"><div class="row"><div><h2>Adressbuch</h2><div class="muted">Wiederkehrende Empfänger mit einem Klick übernehmen.</div></div><div class="spacer"></div><button class="btn secondary" onclick="newAddress()">Neue Adresse</button></div><div id="addressList"></div></div>
</section>

<section id="einstellungen" class="panel">
<div class="card"><h2>Absenderverwaltung</h2><div class="grid2"><div class="field"><label>Bezeichnung</label><input id="s_label" placeholder="z. B. Privat"></div><div class="field"><label>Name / Firma</label><input id="s_name2"></div><div class="field"><label>Adresszusatz optional</label><input id="s_name3"></div><div class="field"><label>Straße</label><input id="s_street"></div><div class="field"><label>Hausnummer</label><input id="s_number"></div><div class="field"><label>PLZ</label><input id="s_plz"></div><div class="field"><label>Ort</label><input id="s_city"></div><div class="field"><label>E-Mail optional</label><input id="s_email" type="email"></div><div class="field"><label>Telefon optional</label><input id="s_phone"></div></div><div class="row" style="margin-top:14px"><button class="btn primary" onclick="saveSender()">Absender speichern</button></div><div id="senderMsg"></div><div style="margin-top:14px"><h3>Gespeicherte Absender</h3><div id="senderList"></div></div></div>
<div class="card"><h3>API-Zugangsdaten</h3><p>Die Schlüssel werden in <b>Home Assistant → Einstellungen → Apps → Post & DHL Frankierung → Konfiguration</b> hinterlegt. Diese Weboberfläche zeigt Geheimnisse absichtlich niemals an.</p><div id="apiConfig"></div><div class="row"><button class="btn secondary" onclick="loadCatalog(true)">DHL Verbindung testen</button></div><div id="diag"></div></div>
</section>
<div class="footer">Post & DHL Frankierung v__APP_VERSION__ · Port 8151</div></div>
<script>
let DATA=null, PRODUCTS=[], IM_PRODUCTS=[], SELECTED_PRODUCT='', SELECTED_IM_PRODUCT='', ADDR_PICK='';
const $=id=>document.getElementById(id);
async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});let j;try{j=await r.json()}catch(e){j={ok:false,error:'Ungültige Serverantwort'}}if(!r.ok||j.ok===false)throw new Error(j.error||('HTTP '+r.status));return j}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function notice(id,msg,type=''){const e=$(id);if(!e)return;e.innerHTML=msg?`<div class="notice ${type}">${msg}</div>`:''}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(b.dataset.tab).classList.add('active')});
async function loadState(){const j=await api('api/state');DATA=j.data;renderState();if(!DATA.internetmarke.api_credentials)notice('imProductsMsg','INTERNETMARKE API-Key und API-Secret müssen zuerst in der App-Konfiguration hinterlegt werden.','error')}
function renderState(){const d=DATA.dhl,i=DATA.internetmarke;
const s=DATA.sender||{};['name2','name3','street','plz','city','email','phone'].forEach(k=>{const e=$('s_'+k);if(e)e.value=s[k]||''});$('s_number').value=s.streetNumber||'';
$('apiConfig').innerHTML=`<p>DHL Paket: <b>${d.configured?'konfiguriert':'nicht konfiguriert'}</b>${d.detected_base?` · erkannt: <span class="mono">${esc(d.detected_base)}</span>`:''}</p><p>INTERNETMARKE: <b>${i.configured?'vollständig konfiguriert':'noch nicht vollständig'}</b></p>${d.last_error?`<details><summary>Letzte DHL-Diagnose</summary><pre>${esc(d.last_error)}</pre></details>`:''}`;renderAddresses();renderCarts();renderIMOrders();renderSenders();renderSenderManagement();}
async function loadCatalog(force=false){notice('catalogMsg','DHL-Produktkatalog wird geladen …');try{const j=await api('api/dhl/catalog'+(force?'?force=1':''));PRODUCTS=j.products||[];renderProducts();notice('catalogMsg',`${PRODUCTS.length} Produkte geladen · API ${esc(j.base||'')} · Katalog ${esc(j.catalog_version||'')}`,'success');await loadState()}catch(e){notice('catalogMsg',esc(e.message),'error');await loadState()}}
function valueText(v){if(v==null)return'';if(typeof v==='object'){if(v.value!=null)return v.value+(v.currency?' '+v.currency:'');return''}return String(v)}
function renderProducts(){if(!PRODUCTS.length){$('products').innerHTML='<div class="muted">Noch keine Produkte geladen.</div>';return}$('products').innerHTML=PRODUCTS.map(p=>{let price=valueText(p.price);return `<div class="product ${SELECTED_PRODUCT===p.id?'selected':''}" onclick="selectProduct('${esc(p.id)}')"><div class="name">${esc(p.name)}</div><div class="meta">${esc(p.id)}${price?' · '+esc(price):''}</div></div>`}).join('')}
function selectProduct(id){SELECTED_PRODUCT=id;renderProducts()}
function parseQuickAddress(text){
  const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  if(lines.length<2)throw new Error('Bitte mindestens Empfänger und Ort eingeben.');
  const zipIndex=lines.findIndex(x=>/^\d{5}\s+/.test(x));
  if(zipIndex<0)throw new Error('PLZ/Ort konnte nicht erkannt werden.');
  const zm=lines[zipIndex].match(/^(\d{5})\s+(.+)$/);
  const before=lines.slice(0,zipIndex);
  if(!before.length)throw new Error('Name konnte nicht erkannt werden.');

  // Straße nur erkennen, wenn die Zeile wirklich wie eine Straße mit Hausnummer aussieht.
  // Zusätzliche Zeilen wie Abteilungen, c/o oder Kassenkennungen bleiben Adresszusatz.
  let streetIndex=-1;
  for(let i=before.length-1;i>=0;i--){
    if(/^(.*?)[\s]+(\d+[A-Za-z]?(?:[-\/]\d+)?)$/.test(before[i])){
      streetIndex=i;
      break;
    }
  }

  let name=before[0];
  let addition='';
  let street='';
  let number='';

  if(streetIndex>0){
    const sm=before[streetIndex].match(/^(.*?)[\s]+(\d+[A-Za-z]?(?:[-\/]\d+)?)$/);
    street=sm[1];
    number=sm[2];
    addition=before.slice(1,streetIndex).join('\n');
  }else{
    addition=before.slice(1).join('\n');
  }

  return {name2:name,addressAddition1:addition,street,streetNumber:number,plz:zm[1],city:zm[2]};
}
function applyQuickAddress(prefix){
  try{
    const a=parseQuickAddress($(prefix+'_quick').value);
    $(prefix+'_name2').value=a.name2;if($(prefix+'_add1'))$(prefix+'_add1').value=a.addressAddition1||'';$(prefix+'_street').value=a.street;$(prefix+'_number').value=a.streetNumber;$(prefix+'_plz').value=a.plz;$(prefix+'_city').value=a.city;
    if(prefix==='r'){$('addressType').value='street';toggleAddressType();notice('cartMsg','Adresse übernommen.','success')}
    else notice('imRecipientMsg','Adresse übernommen.','success');
  }catch(e){notice(prefix==='r'?'cartMsg':'imRecipientMsg',esc(e.message),'error')}
}
function toggleAddressType(){let special=$('addressType').value!=='street';$('streetField').classList.toggle('hidden',special);$('numberField').classList.toggle('hidden',special);$('stationFields').classList.toggle('hidden',!special);$('stationLabel').textContent=$('addressType').value==='packstation'?'Packstationsnummer':'Postfilialennummer'}
function receiverData(){return {address_type:$('addressType').value,receiver:{name2:$('r_name2').value,email:$('r_email').value,addressAddition1:$('r_add1').value,street:$('r_street').value,streetNumber:$('r_number').value,plz:$('r_plz').value,city:$('r_city').value,country:'DEU'},postnummer:$('r_postnummer').value,station_number:$('r_station').value,receiver_email:$('r_email').value}}
async function deleteCart(i){
  if(!confirm('Paketvorgang löschen?'))return;
  try{
    await api('api/dhl/cart/delete',{method:'POST',body:JSON.stringify({index:Number(i)})});
    DATA=await api('api/state').then(x=>x.data);
    renderState();
  }catch(e){alert('Löschen fehlgeschlagen: '+e.message)}
}
async function deleteInternetmarke(i){
  if(!confirm('Internetmarke löschen?'))return;
  try{
    await api('api/internetmarke/delete',{method:'POST',body:JSON.stringify({index:Number(i)})});
    DATA=await api('api/state').then(x=>x.data);
    renderState();
  }catch(e){alert('Löschen fehlgeschlagen: '+e.message)}
}
async function createCart(){if(!SELECTED_PRODUCT){notice('cartMsg','Bitte zuerst ein DHL-Produkt auswählen.','error');return}const data={...receiverData(),product_id:SELECTED_PRODUCT,sender:selectedDhlSender()};notice('cartMsg','DHL-Warenkorb wird vorbereitet …');$('cartBtn').disabled=true;try{const j=await api('api/dhl/cart',{method:'POST',body:JSON.stringify(data)});notice('cartMsg','Warenkorb erstellt. DHL-Zahlung wird geöffnet.','success');await loadState();if(j.entryUrl)window.open(j.entryUrl,'_blank','noopener');else notice('cartMsg','DHL hat keinen entryUrl zurückgegeben. Bitte Diagnose ansehen.','error')}catch(e){notice('cartMsg',esc(e.message),'error')}finally{$('cartBtn').disabled=false}}
function renderCarts(){let rows=DATA.recent_carts||[];if(!rows.length){$('recentCarts').innerHTML='<div class="muted">Noch keine Paketvorgänge.</div>';return}$('recentCarts').innerHTML=rows.map((r,i)=>`<div class="cartitem"><div class="row"><b>${esc(r.receiver_name||'Empfänger')}</b><span class="tag">${esc(r.product_id||'')}</span><span class="muted small">${esc(r.created_at||'')}</span><div class="spacer"></div>${r.entryUrl?`<button class="btn secondary" onclick="window.open('${esc(r.entryUrl)}','_blank','noopener')">DHL-Warenkorb öffnen</button>`:''}${r.shoppingCartId?`<button class="btn secondary" onclick="checkCart('${esc(r.shoppingCartId)}')">Status prüfen</button>`:''}<button class="btn danger" onclick="deleteCart(${i})">Löschen</button></div><div class="mono small muted">${esc(r.shoppingCartId||'noch keine ID')}</div><div id="cart_${i}"></div></div>`).join('')}
async function checkCart(id){notice('diag','Paketstatus wird bei DHL geprüft …');try{const j=await api('api/dhl/cart/'+encodeURIComponent(id));let paks=findPakIdsJS(j.data);let buttons=paks.map(p=>`<button class="btn secondary" onclick="openDoc('${esc(p)}',false)">Label</button> <button class="btn secondary" onclick="openDoc('${esc(p)}',true)">QR-Code</button>`).join(' ');notice('diag','Status erfolgreich geladen.'+(buttons?'<div style="margin-top:8px">'+buttons+'</div>':'<div class="small muted">Noch keine PAKID im Warenkorb gefunden – möglicherweise Zahlung noch offen.</div>'),'success');await loadState()}catch(e){notice('diag',esc(e.message),'error')}}
function findPakIdsJS(o){let a=[];function w(v){if(Array.isArray(v))v.forEach(w);else if(v&&typeof v==='object')Object.entries(v).forEach(([k,x])=>{if(['pakid','pak_id'].includes(k.toLowerCase())&&x)a.push(String(x));else w(x)})}w(o);return [...new Set(a)]}
function openDoc(id,qr){window.open('api/dhl/document/'+encodeURIComponent(id)+(qr?'?qr=1':''),'_blank')}
function renderSelectedSenderPreview(id,target){
 const e=$(target); if(!e)return; const s=selectedSender(id);
 const lines=[s.name1||s.name2,s.addressAddition1||s.name3,s.street&&((s.street||"")+" "+(s.streetNumber||"")),(s.plz||"")+" "+(s.city||"")].filter(x=>x&&x.trim());
 e.innerHTML=lines.length?"<b>Vorschau</b><br>"+lines.map(esc).join("<br>"):"Keine Absenderdaten";
}
function renderSenders(){
 const list=DATA.senders||[];
 const opts=list.length?list:[DATA.sender||{}];
 ['dhlSenderSelect','imSenderSelect'].forEach(id=>{
  const e=$(id); if(!e)return;
  e.innerHTML=opts.map((x,i)=>`<option value="${i}" ${x.default?'selected':''}>${esc(x.label||x.name2||'Absender')}</option>`).join('');
 });
 renderSelectedSenderPreview('dhlSenderSelect','dhlSenderPreview');
 renderSelectedSenderPreview('imSenderSelect','imSenderPreview');
}
function selectedSender(id='dhlSenderSelect'){
 const el=$(id);
 const i=Number(el?.value ?? 0);
 return (DATA.senders&&DATA.senders[i]) || DATA.sender || {};
}
function selectedDhlSender(){return selectedSender('dhlSenderSelect')}
function selectedImSender(){return selectedSender('imSenderSelect')}
async function saveSender(){const sender={name2:$('s_name2').value,name3:$('s_name3').value,addressAddition1:$('s_name3').value,street:$('s_street').value,streetNumber:$('s_number').value,plz:$('s_plz').value,city:$('s_city').value,country:'DEU',email:$('s_email').value,phone:$('s_phone').value,label:$('s_label').value||$('s_name2').value};try{await api('api/senders',{method:'POST',body:JSON.stringify(sender)});notice('senderMsg','Absender gespeichert.','success');await loadState()}catch(e){notice('senderMsg',esc(e.message),'error')}}
function renderSenderManagement(){const e=$('senderList');if(!e)return;const list=DATA.senders||[];e.innerHTML=list.length?list.map((x,i)=>`<div class="addressitem"><b>${esc(x.label||x.name2||'Absender')}</b> ${x.default?'⭐ Hauptabsender':''}<button class="btn secondary" onclick="setDefaultSender(${i})">Als Hauptabsender</button><button class="btn secondary" onclick="editSender(${i})">Bearbeiten</button><button class="btn danger" onclick="deleteSender(${i})">Löschen</button></div>`).join(''):'<div class="muted">Noch keine mehreren Absender angelegt.</div>'}
function editSender(i){
 const x=(DATA.senders||[])[i]; if(!x)return;
 $('s_label').value=x.label||'';
 $('s_name2').value=x.name2||'';
 $('s_name3').value=x.name3||'';
 $('s_street').value=x.street||'';
 $('s_number').value=x.streetNumber||'';
 $('s_plz').value=x.plz||'';
 $('s_city').value=x.city||'';
 $('s_email').value=x.email||'';
 $('s_phone').value=x.phone||'';
 document.querySelector('[data-tab="einstellungen"]').click();
}
async function deleteSender(i){if(!confirm('Absender wirklich löschen?'))return;await api('api/senders/delete',{method:'POST',body:JSON.stringify({index:i})});await loadState()}
async function setDefaultSender(i){await api('api/senders/default',{method:'POST',body:JSON.stringify({index:i})});await loadState()}
function renderAddresses(){let a=DATA.addresses||[];$('addressList').innerHTML=a.length?a.map((x,i)=>`<div class="addressitem"><div class="row"><div><b>${esc(x.name2||x.name1||'')}</b><div class="muted">${esc(x.addressAddition1||'')?esc(x.addressAddition1)+' · ':''}${esc(x.street||'')} ${esc(x.streetNumber||'')} · ${esc(x.plz||'')} ${esc(x.city||'')}</div></div><div class="spacer"></div><button class="btn secondary" onclick="useAddress(${i},'paket')">Paket</button><button class="btn secondary" onclick="useAddress(${i},'brief')">Brief</button><button class="btn danger" onclick="deleteAddress(${i})">Löschen</button></div></div>`).join(''):'<div class="muted">Noch keine Empfänger gespeichert.</div>'}
function newAddress(){document.querySelector('[data-tab="paket"]').click();['r_name2','r_email','r_add1','r_street','r_number','r_plz','r_city','r_postnummer','r_station','r_quick'].forEach(id=>$(id).value='')}
function useAddress(i,target='paket'){const a=DATA.addresses[i];if(!a)return;if(target==='brief'){document.querySelector('[data-tab="brief"]').click();$('im_r_name2').value=a.name2||a.name1||'';$('im_r_add1').value=a.addressAddition1||'';$('im_r_street').value=a.street||'';$('im_r_number').value=a.streetNumber||'';$('im_r_plz').value=a.plz||'';$('im_r_city').value=a.city||'';return}document.querySelector('[data-tab="paket"]').click();$('addressType').value=a.address_type||'street';toggleAddressType();$('r_name2').value=a.name2||a.name1||'';$('r_email').value=a.email||'';$('r_add1').value=a.addressAddition1||'';$('r_street').value=a.street||'';$('r_number').value=a.streetNumber||'';$('r_plz').value=a.plz||'';$('r_city').value=a.city||'';$('r_postnummer').value=a.postnummer||'';$('r_station').value=a.station_number||''}
function fillFromAddressBook(target='paket'){if((DATA.addresses||[]).length)useAddress(0,target);else alert('Noch keine Adresse gespeichert.')}
function briefReceiverData(){return {address_type:'street',receiver:{name2:$('im_r_name2').value,addressAddition1:$('im_r_add1').value,street:$('im_r_street').value,streetNumber:$('im_r_number').value,plz:$('im_r_plz').value,city:$('im_r_city').value,country:'DEU'}}}
async function saveRecipient(target='paket'){let d=target==='brief'?briefReceiverData():receiverData(),a={...d.receiver,address_type:d.address_type,postnummer:d.postnummer,station_number:d.station_number};try{await api('api/address',{method:'POST',body:JSON.stringify(a)});await loadState();notice(target==='brief'?'imRecipientMsg':'cartMsg','Empfänger im Adressbuch gespeichert.','success')}catch(e){notice(target==='brief'?'imRecipientMsg':'cartMsg',esc(e.message),'error')}}
async function deleteAddress(i){if(!confirm('Adresse wirklich löschen?'))return;await api('api/address/delete',{method:'POST',body:JSON.stringify({index:i})});await loadState()}
async function checkIM(){notice('imBox','INTERNETMARKE-Verbindung und Portokasse werden geprüft …');try{const j=await api('api/internetmarke/health');const h=j.health||{};notice('imBox',esc(h.message||'Keine Statusmeldung'),h.ok?'success':'error');}catch(e){notice('imBox',esc(e.message),'error')}}
async function runIMDiagnostics(){
  notice('imDiag','Diagnose läuft – es wird nichts gekauft oder abgebucht …');
  try{
    const j=await api('api/internetmarke/diagnostics');
    const d=j.diagnostics||{};
    const line=(label,x)=>{
      if(!x)return `<div><b>${label}</b>: keine Antwort</div>`;
      const ok=x.ok===true?'✅':(x.ok===false?'❌':'ℹ️');
      let detail=x.status!=null?`HTTP ${esc(x.status)}`:(x.error?esc(x.error):'');
      if(x.count!=null)detail+=` · ${esc(x.count)} Produkte`;
      if(x.token_received)detail+=' · Token erhalten';
      if(x.balance!=null)detail+=` · Guthaben ${esc(x.balance)}`;
      if(x.request_id)detail+=` · Request-ID <span class="mono">${esc(x.request_id)}</span>`;
      if(x.url)detail+=`<div class="small mono muted">${esc(x.url)}</div>`;
      if(x.body&&!x.token_received)detail+=`<details><summary>Antwort</summary><pre>${esc(JSON.stringify(x.body,null,2))}</pre></details>`;
      if(x.attempts)detail+=`<details><summary>Versuche</summary><pre>${esc(JSON.stringify(x.attempts,null,2))}</pre></details>`;
      if(x.headers&&Object.keys(x.headers).length)detail+=`<details><summary>Diagnose-Header</summary><pre>${esc(JSON.stringify(x.headers,null,2))}</pre></details>`;
      return `<div style="padding:8px 0;border-bottom:1px solid #e5e5e5"><b>${ok} ${label}</b><div>${detail}</div></div>`;
    };
    const productBlock=(p)=>{
      const tests=(p&&p.tests)||[];
      let rows=tests.map(x=>{
        const icon=x.skipped?'ℹ️':(x.ok?'✅':'❌');
        const st=x.skipped?'nicht ausgeführt':(x.status!=null?'HTTP '+esc(x.status):(x.error?esc(x.error):'keine Antwort'));
        const rid=x.request_id?`<span class="mono small">${esc(x.request_id)}</span>`:'–';
        const count=x.count!=null?` · ${esc(x.count)} Produkte`:'';
        return `<div class="diagrow"><div class="diagmain"><b>${icon} ${esc(x.label||'Products API')}</b><div class="small muted diagurl">${esc(x.url||'')}</div></div><div class="diagstatus"><b>${st}${count}</b><div class="small muted">Request-ID: ${rid}</div></div></div>`;
      }).join('');
      return `<div style="padding:8px 0;border-bottom:1px solid #e5e5e5"><b>${p&&p.ok?'✅':'❌'} Products API – Vergleich</b><div class="small muted">Dokumentierter und alternativer Pfad, jeweils ohne und mit API-Key.</div>${rows}</div>`;
    };
    const html=line('INTERNETMARKE Server',d.server)+productBlock(d.products)+line('Portokassen-Token',d.authorization)+line('user',d.profile)+`<div class="small muted" style="margin-top:8px">Nur Lese-/Login-Tests. Keine Marke, kein Warenkorb, keine Abbuchung. Geheimnisse und Token werden nicht angezeigt.</div>`;
    notice('imDiag',html,(d.server&&d.server.ok&&d.products&&d.products.ok&&d.authorization&&d.authorization.ok)?'success':'');
  }catch(e){notice('imDiag',esc(e.message),'error')}
}
function renderIMProducts(){if(!IM_PRODUCTS.length){$('imProducts').innerHTML='<div class="muted">Keine Produkte geliefert.</div>';return}$('imProducts').innerHTML=IM_PRODUCTS.map(p=>`<div class="product ${SELECTED_IM_PRODUCT===String(p.productCode)?'selected':''}" onclick="selectIMProduct('${esc(p.productCode)}')"><div class="name">${esc(p.name)}</div><div class="meta">Code ${esc(p.productCode)} · ${p.price!=null?esc(Number(p.price).toFixed(2).replace('.',','))+' '+esc(p.currency||'EUR'):''}${p.transport?' · '+esc(p.transport):''}${p.maxWeight!=null?' · bis '+esc(p.maxWeight)+' g':''}</div></div>`).join('')}
function selectIMProduct(id){SELECTED_IM_PRODUCT=String(id);renderIMProducts()}
async function loadIMProducts(){notice('imProductsMsg','Briefprodukte werden geladen …');try{const j=await api('api/internetmarke/products');IM_PRODUCTS=j.products||[];
renderIMProducts();const expected=6,missing=Math.max(0,expected-IM_PRODUCTS.length);notice('imProductsMsg',missing?`DHL hat aktuell ${IM_PRODUCTS.length} von ${expected} streng geprüften Briefprodukten geliefert. Nicht gelieferte oder nicht eindeutig geprüfte Produkte werden bewusst nicht als kaufbare Auswahl angezeigt.`:'Alle 6 Briefprodukte wurden live auf DHL-Name, Preis, Gewicht und Inland geprüft.','success')}catch(e){notice('imProductsMsg',esc(e.message),'error')}}
function formatWalletCents(cents){return new Intl.NumberFormat('de-DE',{style:'currency',currency:'EUR'}).format(Number(cents)/100)}
async function loadIMBalance(){const e=$('imBalance');if(!e)return;e.textContent='Guthaben wird abgefragt …';try{const j=await api('api/internetmarke/health');const h=j.health||{};if(!h.ok)throw new Error(h.message||'Guthaben konnte nicht abgerufen werden.');if(h.balance_cents!=null){e.textContent=formatWalletCents(h.balance_cents)+' verfügbar';}else{e.textContent='Guthaben wurde von der Portokasse nicht geliefert.'}}catch(err){e.textContent='Guthaben nicht verfügbar: '+err.message}}
function printPdf(url){const index=(DATA?.recent_internetmarke||[]).findIndex(row=>row.link===url);if(index<0){notice('imRecipientMsg','Die gespeicherte Internetmarke konnte nicht zum Drucken gefunden werden.','error');return}const w=window.open('api/internetmarke/print/'+index,'_blank','noopener');if(!w)notice('imRecipientMsg','Bitte Pop-ups für Home Assistant erlauben, um den Druckdialog zu öffnen.','error')}
function showIMTestInfo(){
  notice('imRecipientMsg','Der Testbetrieb läuft über die von Deutsche Post bereitgestellte Entwickler-/Test-Portokasse. Dafür müssen die Test-Zugangsdaten in der Home-Assistant-App-Konfiguration hinterlegt werden. Eine produktive Portokasse wird nicht belastet.','success');
}
function renderIMOrders(){let rows=DATA.recent_internetmarke||[];if(!$('recentInternetmarke'))return;if(!rows.length){$('recentInternetmarke').innerHTML='<div class="muted">Noch keine Internetmarken.</div>';return}$('recentInternetmarke').innerHTML=rows.map((r,i)=>`<div class="cartitem"><div class="row"><b>${esc(r.receiver_name||'Empfänger')}</b><span class="tag">${esc(r.product_name||r.product_code||'')}</span><span class="muted small">${esc(r.created_at||'')}</span><div class="spacer"></div>${r.link?`<button class="btn secondary" onclick="window.open('${esc(r.link)}','_blank','noopener')">PDF öffnen</button><button class="btn secondary" onclick="printPdf('${esc(r.link)}')">Drucken</button>`:''}<button class="btn danger" onclick="deleteInternetmarke(${i})">Löschen</button></div><div class="mono small muted">${esc(r.shopOrderId||'')}</div></div>`).join('')}
async function createInternetmarke(){if(!SELECTED_IM_PRODUCT){notice('imRecipientMsg','Bitte zuerst ein Briefprodukt auswählen.','error');return}const data={product_code:SELECTED_IM_PRODUCT,page_format_id:5,voucher_layout:'ADDRESS_ZONE',sender:selectedImSender(),receiver:briefReceiverData().receiver};notice('imRecipientMsg','Internetmarke wird erstellt …');$('imCreateBtn').disabled=true;try{const j=await api('api/internetmarke/create',{method:'POST',body:JSON.stringify(data)});let extra='';if(j.order&&j.order.link)extra+=` <button class="btn secondary" onclick="window.open('${esc(j.order.link)}','_blank','noopener')">PDF öffnen</button> <button class="btn secondary" onclick="printPdf('${esc(j.order.link)}')">Drucken</button>`;if(j.order&&j.order.shopOrderId)extra+=` <span class="mono">${esc(j.order.shopOrderId)}</span>`;notice('imRecipientMsg','Internetmarke erfolgreich erstellt.'+extra,'success');await loadState();if(j.order&&j.order.link)window.open(j.order.link,'_blank','noopener')}catch(e){notice('imRecipientMsg',esc(e.message),'error')}finally{$('imCreateBtn').disabled=false}}
window.addEventListener('load',async()=>{try{await loadState();if(DATA.dhl.configured)loadCatalog(false);if(DATA.internetmarke.api_credentials){loadIMProducts();loadIMBalance()}}catch(e){console.error(e)}});
function setupIMAddressType(){
  if($('im_address_type'))return;
  const grid=$('im_r_name2').closest('.grid2');
  grid.insertAdjacentHTML('beforebegin',`<div class="delivery-mode"><div class="field"><label for="im_address_type">Adressart</label><select id="im_address_type" onchange="toggleIMAddressType()"><option value="street">Straßenadresse</option><option value="postbox">Postfach / Zustellzeile</option></select></div><p>Für Postfach- und Großempfängeradressen ist keine künstliche Straße nötig.</p></div><div class="field delivery-line-field hidden" id="im_delivery_line_field"><label for="im_r_deliveryLine">Postfach / Zustellzeile</label><input id="im_r_deliveryLine" placeholder="z. B. Postfach 1234 oder PFLE-252"></div>`);
  toggleIMAddressType();
}
function toggleIMAddressType(){
  const postbox=$('im_address_type')?.value==='postbox';
  ['im_r_street','im_r_number'].forEach(id=>$(id)?.closest('.field').classList.toggle('hidden',postbox));
  $('im_delivery_line_field')?.classList.toggle('hidden',!postbox);
}
function parseQuickAddress(text){
  const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  if(lines.length<2)throw new Error('Bitte mindestens Empfänger und PLZ/Ort eingeben.');
  const zipIndex=lines.findIndex(x=>/^\d{5}\s+/.test(x));
  if(zipIndex<0)throw new Error('PLZ/Ort konnte nicht erkannt werden.');
  const zm=lines[zipIndex].match(/^(\d{5})\s+(.+)$/);
  const before=lines.slice(0,zipIndex);
  if(!before.length)throw new Error('Name konnte nicht erkannt werden.');
  const deliveryIndex=before.findIndex((line,i)=>i>0&&(/^(?:postfach\s+.+)$/i.test(line)||/^\(?PFLE[-\s]?\d+\)?$/i.test(line)));
  if(deliveryIndex>=0){
    return {name2:before[0],addressAddition1:before.filter((_,i)=>i>0&&i!==deliveryIndex).join(' · '),deliveryLine:before[deliveryIndex],address_type:'postbox',street:'',streetNumber:'',plz:zm[1],city:zm[2]};
  }
  let streetIndex=-1;
  for(let i=before.length-1;i>=0;i--){if(/^(.*?)[\s]+(\d+[A-Za-z]?(?:[-\/]\d+)?)$/.test(before[i])){streetIndex=i;break}}
  let street='',number='',addition='';
  if(streetIndex>0){const sm=before[streetIndex].match(/^(.*?)[\s]+(\d+[A-Za-z]?(?:[-\/]\d+)?)$/);street=sm[1];number=sm[2];addition=before.slice(1,streetIndex).join(' · ')}
  else addition=before.slice(1).join(' · ');
  return {name2:before[0],addressAddition1:addition,address_type:'street',deliveryLine:'',street,streetNumber:number,plz:zm[1],city:zm[2]};
}
function applyQuickAddress(prefix){
  try{
    const a=parseQuickAddress($(prefix+'_quick').value);
    $(prefix+'_name2').value=a.name2;if($(prefix+'_add1'))$(prefix+'_add1').value=a.addressAddition1||'';$(prefix+'_street').value=a.street||'';$(prefix+'_number').value=a.streetNumber||'';$(prefix+'_plz').value=a.plz;$(prefix+'_city').value=a.city;
    if(prefix==='r'){ $('addressType').value='street';toggleAddressType();notice('cartMsg','Adresse übernommen.','success') }
    else {setupIMAddressType();$('im_address_type').value=a.address_type||'street';$('im_r_deliveryLine').value=a.deliveryLine||'';toggleIMAddressType();notice('imRecipientMsg','Adresse übernommen. Bitte kurz prüfen.','success')}
  }catch(e){notice(prefix==='r'?'cartMsg':'imRecipientMsg',esc(e.message),'error')}
}
function briefReceiverData(){
  const address_type=$('im_address_type')?.value||'street';
  return {address_type,receiver:{name2:$('im_r_name2').value,addressAddition1:$('im_r_add1').value,street:$('im_r_street').value,streetNumber:$('im_r_number').value,deliveryLine:$('im_r_deliveryLine')?.value||'',address_type,plz:$('im_r_plz').value,city:$('im_r_city').value,country:'DEU'}};
}
function useAddress(i,target='paket'){
  const a=DATA.addresses[i];if(!a)return;
  if(target==='brief'){
    document.querySelector('[data-tab="brief"]').click();setupIMAddressType();
    $('im_r_name2').value=a.name2||a.name1||'';$('im_r_add1').value=a.addressAddition1||'';$('im_r_street').value=a.street||'';$('im_r_number').value=a.streetNumber||'';$('im_r_deliveryLine').value=a.deliveryLine||'';$('im_r_plz').value=a.plz||'';$('im_r_city').value=a.city||'';$('im_address_type').value=a.address_type==='postbox'?'postbox':'street';toggleIMAddressType();return;
  }
  document.querySelector('[data-tab="paket"]').click();$('addressType').value=a.address_type||'street';toggleAddressType();$('r_name2').value=a.name2||a.name1||'';$('r_email').value=a.email||'';$('r_add1').value=a.addressAddition1||'';$('r_street').value=a.street||'';$('r_number').value=a.streetNumber||'';$('r_plz').value=a.plz||'';$('r_city').value=a.city||'';$('r_postnummer').value=a.postnummer||'';$('r_station').value=a.station_number||'';
}
function renderAddresses(){
  const list=DATA.addresses||[];
  $('addressList').innerHTML=list.length?list.map((x,i)=>{const delivery=x.address_type==='postbox'?x.deliveryLine:[x.street,x.streetNumber].filter(Boolean).join(' ');return `<div class="addressitem"><div class="row"><div><b>${esc(x.name2||x.name1||'')}</b><div class="muted">${esc(x.addressAddition1||'')?esc(x.addressAddition1)+' · ':''}${esc(delivery||'')} · ${esc(x.plz||'')} ${esc(x.city||'')}</div></div><div class="spacer"></div><button class="btn secondary" onclick="useAddress(${i},'paket')">Paket</button><button class="btn secondary" onclick="useAddress(${i},'brief')">Brief</button><button class="btn danger" onclick="deleteAddress(${i})">Löschen</button></div></div>`}).join(''):'<div class="muted">Noch keine Empfänger gespeichert.</div>';
}
function renderSenderManagement(){
  const e=$('senderList');if(!e)return;const list=DATA.senders||[];
  e.innerHTML=list.length?list.map((x,i)=>{const address=[x.addressAddition1||x.name3,[x.street,x.streetNumber].filter(Boolean).join(' '),[x.plz,x.city].filter(Boolean).join(' ')].filter(Boolean).map(esc).join(' · ');return `<div class="sender-card"><div><span class="sender-name">${esc(x.label||x.name2||'Absender')}</span>${x.default?'<span class="default-badge">Hauptabsender</span>':''}<div class="sender-address">${esc(x.name2||'')}<br>${address}</div></div><div class="sender-actions"><button class="btn secondary" onclick="setDefaultSender(${i})">Als Standard</button><button class="btn secondary" onclick="editSender(${i})">Bearbeiten</button><button class="btn danger" onclick="deleteSender(${i})">Löschen</button></div></div>`}).join(''):'<div class="muted">Noch keine Absender angelegt.</div>';
}
function renderEmptyCatalogStates(){
  if(!$('products').children.length)$('products').innerHTML='<div class="empty-state">Hinterlege den DHL-API-Key in den Einstellungen der Home-Assistant-App, um verfügbare Produkte zu laden.</div>';
  if(!$('imProducts').children.length&&!DATA?.internetmarke?.api_credentials)$('imProducts').innerHTML='<div class="empty-state">Die Briefprodukte erscheinen nach dem Hinterlegen von INTERNETMARKE API-Key und API-Secret.</div>';
}
window.addEventListener('load',setupIMAddressType);
window.addEventListener('load',renderEmptyCatalogStates);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "PostDHL/0.1.36"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, obj, status=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, html, status=200):
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 1024 * 1024:
            raise ValueError("Request zu groß.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/":
                return self._html(INDEX_HTML.replace("__APP_VERSION__", VERSION))
            if path == "/api/health":
                return self._json({"ok": True, "version": VERSION})
            if path == "/api/state":
                return self._json({"ok": True, "data": public_state()})
            if path == "/api/dhl/catalog":
                force = q.get("force", ["0"])[0] == "1"
                result = discover_dhl_catalog(force=force)
                return self._json({"ok": True, **result})
            if path.startswith("/api/dhl/cart/"):
                cart_id = urllib.parse.unquote(path.split("/api/dhl/cart/", 1)[1])
                body = load_dhl_cart(cart_id)
                return self._json({"ok": True, "data": body, "pak_ids": find_pak_ids(body)})
            if path.startswith("/api/dhl/document/"):
                ident = urllib.parse.unquote(path.split("/api/dhl/document/", 1)[1])
                qr = q.get("qr", ["0"])[0] == "1"
                raw, ctype = fetch_dhl_document(ident, qr=qr)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Content-Disposition", ("inline" if qr else "attachment") + f'; filename="dhl-{ident}.{"png" if qr else "pdf"}"')
                self.end_headers()
                self.wfile.write(raw)
                return
            if path.startswith("/api/internetmarke/print/"):
                index = urllib.parse.unquote(path.split("/api/internetmarke/print/", 1)[1])
                return self._html(internetmarke_print_html(index))
            if path.startswith("/api/internetmarke/document/"):
                index = urllib.parse.unquote(path.split("/api/internetmarke/document/", 1)[1])
                raw, ctype = fetch_internetmarke_document(index)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Content-Disposition", 'inline; filename="internetmarke.pdf"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            if path == "/api/internetmarke/health":
                return self._json({"ok": True, "health": internetmarke_health()})
            if path == "/api/internetmarke/diagnostics":
                return self._json({"ok": True, "diagnostics": internetmarke_diagnostics()})
            if path == "/api/internetmarke/products":
                return self._json({"ok": True, **internetmarke_products()})
            return self._json({"ok": False, "error": "Nicht gefunden"}, 404)
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            set_dhl_error(str(exc))
            return self._json({"ok": False, "error": str(exc)}, 502)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            data = self._read_json()
            if path == "/api/sender":
                sender = normalize_address(data, sender=True)
                validate_german_address(sender, sender=True)
                with STATE_LOCK:
                    st = load_state()
                    st["sender"] = {**DEFAULT_STATE["sender"], **sender}
                    save_state(st)
                return self._json({"ok": True})
            if path == "/api/senders":
                sender = normalize_address(data, sender=True)
                validate_german_address(sender, sender=True)
                with STATE_LOCK:
                    st = load_state()
                    entry = {**DEFAULT_STATE["sender"], **sender}
                    entry["label"] = str(data.get("label") or entry.get("name2") or "Absender")
                    st["senders"] = [x for x in st.get("senders", []) if x.get("label") != entry["label"]]
                    st["senders"].append(entry)
                    if data.get("default", False) or not st.get("sender", {}).get("name2"):
                        st["sender"] = entry
                    save_state(st)
                return self._json({"ok": True})
            if path == "/api/senders/delete":
                idx = int(data.get("index", -1))
                with STATE_LOCK:
                    st = load_state()
                    if 0 <= idx < len(st.get("senders", [])):
                        removed = st["senders"].pop(idx)
                        if removed.get("default") and st["senders"]:
                            st["senders"][0]["default"] = True
                            st["sender"] = st["senders"][0]
                        save_state(st)
                return self._json({"ok": True})
            if path == "/api/senders/default":
                idx = int(data.get("index", -1))
                with STATE_LOCK:
                    st = load_state()
                    for i, item in enumerate(st.get("senders", [])):
                        item["default"] = (i == idx)
                    if 0 <= idx < len(st.get("senders", [])):
                        st["sender"] = st["senders"][idx]
                    save_state(st)
                return self._json({"ok": True})
            if path == "/api/address":
                addr = normalize_address(data, sender=False)
                addr["address_type"] = str(data.get("address_type") or "street")
                if addr["address_type"] not in {"street", "postbox", "packstation", "postfiliale"}:
                    raise ValueError("Unbekannte Adressart.")
                if data.get("postnummer"):
                    addr["postnummer"] = latin1_clean(data.get("postnummer"))
                if data.get("station_number"):
                    addr["station_number"] = latin1_clean(data.get("station_number"))
                if addr["address_type"] in {"street", "postbox"}:
                    validate_german_address(addr, sender=False)
                elif not (addr.get("name2") and addr.get("plz") and addr.get("city") and addr.get("postnummer") and addr.get("station_number")):
                    raise ValueError("Für Packstation/Postfiliale fehlen Angaben.")
                with STATE_LOCK:
                    st = load_state()
                    st["addresses"].insert(0, addr)
                    # Deduplicate by normalized important fields.
                    seen, unique = set(), []
                    for x in st["addresses"]:
                        key = (x.get("name2"), x.get("address_type"), x.get("street"), x.get("streetNumber"), x.get("deliveryLine"), x.get("plz"), x.get("city"), x.get("postnummer"), x.get("station_number"))
                        if key not in seen:
                            seen.add(key); unique.append(x)
                    st["addresses"] = unique[:100]
                    save_state(st)
                return self._json({"ok": True})
            if path == "/api/address/delete":
                idx = int(data.get("index", -1))
                with STATE_LOCK:
                    st = load_state()
                    if 0 <= idx < len(st["addresses"]):
                        st["addresses"].pop(idx)
                    save_state(st)
                return self._json({"ok": True})
            if path == "/api/dhl/cart/delete":
                data = data or {}
                st = load_state()
                idx = int(data.get('index', -1))
                if 0 <= idx < len(st.get('recent_carts', [])):
                    st['recent_carts'].pop(idx)
                    save_state(st)
                return self._json({'ok': True})
            if path == "/api/internetmarke/delete":
                data = data or {}
                st = load_state()
                idx = int(data.get('index', -1))
                if 0 <= idx < len(st.get('recent_internetmarke', [])):
                    st['recent_internetmarke'].pop(idx)
                    save_state(st)
                return self._json({'ok': True})
            if path == "/api/dhl/cart":
                result = create_dhl_cart(data)
                return self._json({"ok": True, **result})
            if path == "/api/internetmarke/create":
                result = create_internetmarke_order(data)
                return self._json({"ok": True, **result})
            return self._json({"ok": False, "error": "Nicht gefunden"}, 404)
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            set_dhl_error(str(exc))
            return self._json({"ok": False, "error": str(exc)}, 502)


def main():
    load_state()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Post & DHL Frankierung v{VERSION} listening on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
