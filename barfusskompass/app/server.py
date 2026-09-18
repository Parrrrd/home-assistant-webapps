#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import io
import json
import math
import mimetypes
import os
import re
import shutil
import sqlite3
import statistics
import threading
import uuid
from datetime import date, datetime, timedelta
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen

APP_NAME = "BarfußKompass"
APP_VERSION = "0.1.2"
PORT = 8157
DATA_DIR = Path(os.environ.get("BARFUSSKOMPASS_DATA", "/data"))
DB_PATH = DATA_DIR / "barfusskompass.db"
UPLOAD_DIR = DATA_DIR / "uploads"
BACKUP_DIR = DATA_DIR / "backups"
STATIC_DIR = Path(__file__).parent / "static"
OPTIONS_PATH = DATA_DIR / "options.json"

DB_LOCK = threading.RLock()


def ensure_dirs():
    for p in (DATA_DIR, UPLOAD_DIR, BACKUP_DIR):
        p.mkdir(parents=True, exist_ok=True)


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    ensure_dirs()
    with DB_LOCK, db_connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              person_type TEXT NOT NULL DEFAULT 'adult',
              growth_enabled INTEGER NOT NULL DEFAULT 0,
              closed_min_allowance REAL NOT NULL DEFAULT 1.2,
              closed_max_allowance REAL NOT NULL DEFAULT 1.7,
              width_allowance REAL NOT NULL DEFAULT 0.4,
              sandal_min_allowance REAL NOT NULL DEFAULT 0.7,
              sandal_max_allowance REAL NOT NULL DEFAULT 1.0,
              measurement_interval_days INTEGER,
              notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS measurements (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
              measured_on TEXT NOT NULL,
              length_cm REAL NOT NULL,
              width_cm REAL,
              left_length_cm REAL,
              right_length_cm REAL,
              left_width_cm REAL,
              right_width_cm REAL,
              quality TEXT NOT NULL DEFAULT 'exact',
              method TEXT NOT NULL DEFAULT 'manuell',
              historical_target_min_cm REAL,
              historical_target_max_cm REAL,
              historical_target_width_cm REAL,
              notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(person_id, measured_on, length_cm)
            );

            CREATE TABLE IF NOT EXISTS shoes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              brand TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL DEFAULT '',
              color TEXT NOT NULL DEFAULT '',
              eu_size TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT 'geschlossen',
              season TEXT NOT NULL DEFAULT 'ganzjährig',
              barefoot INTEGER NOT NULL DEFAULT 1,
              person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
              status TEXT NOT NULL DEFAULT 'aktiv',
              order_status TEXT NOT NULL DEFAULT 'behalten',
              purchase_date TEXT,
              purchase_price REAL,
              purchase_store TEXT NOT NULL DEFAULT '',
              product_url TEXT NOT NULL DEFAULT '',
              product_image_url TEXT NOT NULL DEFAULT '',
              photo_path TEXT NOT NULL DEFAULT '',
              inner_length_cm REAL,
              inner_width_cm REAL,
              measurement_method TEXT NOT NULL DEFAULT 'selbst gemessen',
              usable_surface INTEGER NOT NULL DEFAULT 0,
              condition TEXT NOT NULL DEFAULT 'gut',
              experience_note TEXT NOT NULL DEFAULT '',
              purchase_reason TEXT NOT NULL DEFAULT '',
              wear_context TEXT NOT NULL DEFAULT '',
              favorite INTEGER NOT NULL DEFAULT 0,
              fit_override TEXT NOT NULL DEFAULT '',
              fit_override_reason TEXT NOT NULL DEFAULT '',
              sold_date TEXT,
              sold_price REAL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS model_notes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              brand TEXT NOT NULL,
              model TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              fit_tags TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(brand, model)
            );

            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        # Lightweight schema migrations for future-proof updates.
        shoe_cols = {r["name"] for r in db.execute("PRAGMA table_info(shoes)")}
        for col, ddl in {
            "purchase_reason":"TEXT NOT NULL DEFAULT ''",
            "wear_context":"TEXT NOT NULL DEFAULT ''",
            "favorite":"INTEGER NOT NULL DEFAULT 0"
        }.items():
            if col not in shoe_cols:
                db.execute(f"ALTER TABLE shoes ADD COLUMN {col} {ddl}")
        cnt = db.execute("SELECT COUNT(*) AS c FROM people").fetchone()["c"]
        if cnt == 0:
            seed_initial_data(db)
        db.commit()


def seed_initial_data(db):
    people = [
        ("Emil", "child", 1, 1.2, 1.7, 0.4, 0.7, 1.0, 60, "Historische Größen-Notiz 19.04.2026: EU 33/34"),
        ("Luna", "child", 1, 1.2, 1.7, 0.4, 0.7, 1.0, 60, "Historische Größen-Notiz 19.04.2026: EU 26/27"),
        ("secondary", "adult", 0, 1.2, 1.2, 0.4, 0.7, 1.0, None, "Zugabe geschlossen 1,2 cm"),
        ("primary", "adult", 0, 1.2, 1.2, 0.4, 0.7, 1.0, None, "Zugabe geschlossen 1,2 cm"),
    ]
    db.executemany(
        """INSERT INTO people
        (name,person_type,growth_enabled,closed_min_allowance,closed_max_allowance,width_allowance,sandal_min_allowance,sandal_max_allowance,measurement_interval_days,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        people,
    )
    ids = {r["name"]: r["id"] for r in db.execute("SELECT id,name FROM people")}

    # date, length, width, target_min, target_max, target_width, quality, notes
    emil = [
        ("2022-05-26",15.7,6.6,17.4,17.4,7.0,"exact",""),
        ("2022-06-27",15.8,6.7,17.5,17.5,7.1,"exact",""),
        ("2022-11-03",16.4,6.9,18.1,18.1,7.3,"exact",""),
        ("2023-02-14",16.6,6.9,18.3,18.3,7.3,"exact",""),
        ("2023-03-05",16.9,7.1,18.6,18.6,7.5,"exact",""),
        ("2023-04-16",16.9,7.1,18.6,18.6,7.5,"exact",""),
        ("2023-05-13",17.0,7.1,18.7,18.7,7.5,"exact",""),
        ("2023-07-15",17.2,7.2,18.9,18.9,7.6,"exact",""),
        ("2023-08-03",17.4,7.2,19.1,19.1,7.6,"exact",""),
        ("2023-10-09",17.4,7.1,None,None,None,"exact",""),
        ("2023-11-08",17.4,7.1,19.1,19.1,7.5,"exact",""),
        ("2024-01-17",17.9,7.2,19.6,19.6,7.7,"exact",""),
        ("2024-04-14",17.9,7.2,None,None,None,"exact",""),
        ("2024-07-10",18.2,7.4,19.9,19.9,None,"exact",""),
        ("2024-09-21",18.7,7.4,20.4,20.4,7.8,"exact",""),
        ("2025-03-14",18.7,7.4,20.4,20.4,7.8,"exact",""),
        ("2025-04-13",18.7,None,None,None,None,"exact",""),
        ("2025-04-26",19.1,None,20.8,20.8,None,"exact",""),
        ("2025-08-02",19.1,7.8,20.8,20.8,8.2,"exact",""),
        ("2025-09-01",19.2,None,20.9,20.9,None,"exact",""),
        ("2026-04-19",19.8,8.1,21.5,21.5,8.5,"exact","EU 33/34 notiert"),
        ("2026-08-14",20.3,8.2,21.5,22.0,8.6,"exact","Mind. 21,5 / max. 22,0 cm"),
    ]
    luna = [
        ("2022-11-03",10.5,None,None,None,None,"approx","ca. 10,5 cm"),
        ("2023-02-14",10.5,None,None,None,None,"exact",""),
        ("2023-04-16",11.3,None,None,None,None,"exact",""),
        ("2023-05-04",11.6,None,13.1,13.1,None,"exact",""),
        ("2023-05-13",11.7,5.2,13.2,13.2,5.6,"exact",""),
        ("2023-07-15",12.5,5.5,14.0,14.0,5.9,"exact",""),
        ("2023-08-03",12.5,5.5,14.0,14.0,5.9,"exact",""),
        ("2023-10-09",12.8,5.6,14.3,14.3,6.0,"exact",""),
        ("2023-11-08",13.0,5.8,14.5,14.5,6.2,"exact",""),
        ("2024-01-17",13.0,5.8,None,None,None,"exact","Vom Nutzer auf 17.01.2024 korrigiert"),
        ("2024-04-14",13.6,6.0,15.0,15.3,6.4,"exact",""),
        ("2024-07-10",14.0,6.0,15.7,15.7,6.4,"exact",""),
        ("2024-09-21",14.3,6.0,16.0,16.0,6.4,"exact",""),
        ("2025-03-14",14.5,6.1,16.2,16.2,6.5,"exact",""),
        ("2025-04-13",14.9,None,16.6,16.6,None,"exact",""),
        ("2025-09-05",15.1,None,16.8,16.8,None,"exact",""),
        ("2026-04-19",15.6,6.5,17.3,17.3,6.9,"exact","EU 26/27 notiert"),
        ("2026-08-14",16.1,6.6,17.3,17.8,7.0,"exact","Mind. 17,3 / max. 17,8 cm"),
    ]
    secondary = [
        ("2022-06-27",25.4,9.9,26.6,26.6,10.3,"exact",""),
        ("2023-05-19",25.1,10.3,26.3,26.3,10.7,"exact",""),
        ("2024-03-25",25.2,10.0,26.4,26.4,10.4,"exact",""),
    ]
    primary = [
        ("2024-03-25",28.2,11.2,29.4,29.4,11.6,"exact",""),
    ]
    rows = []
    for name, dataset in (("Emil",emil),("Luna",luna),("secondary",secondary),("primary",primary)):
        for d,l,w,tmin,tmax,tw,q,n in dataset:
            rows.append((ids[name],d,l,w,q,"manuell",tmin,tmax,tw,n))
    db.executemany(
        """INSERT INTO measurements
        (person_id,measured_on,length_cm,width_cm,quality,method,historical_target_min_cm,historical_target_max_cm,historical_target_width_cm,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )


def rowdict(r):
    return dict(r) if r else None


def parse_iso(d):
    return datetime.strptime(d, "%Y-%m-%d").date()


def month_diff(a: date, b: date) -> float:
    return (b - a).days / 30.4375


def latest_measurement(db, person_id):
    return db.execute(
        "SELECT * FROM measurements WHERE person_id=? ORDER BY measured_on DESC,id DESC LIMIT 1",
        (person_id,),
    ).fetchone()


def person_with_latest(db, person):
    p = rowdict(person)
    m = latest_measurement(db, person["id"])
    p["latest_measurement"] = rowdict(m)
    return p


def fit_for_shoe(person, measurement, shoe, length_override=None, width_override=None):
    if not measurement or shoe["inner_length_cm"] is None:
        return {"status":"unbekannt","label":"Maße fehlen","length_allowance_cm":None,"width_allowance_cm":None}
    foot_len = float(length_override if length_override is not None else measurement["length_cm"])
    foot_width = width_override if width_override is not None else measurement["width_cm"]
    inner_len = float(shoe["inner_length_cm"])
    allowance = round(inner_len - foot_len, 2)
    is_sandal = shoe["category"] in ("sandale_offen", "sandale")
    min_a = float(person["sandal_min_allowance"] if is_sandal else person["closed_min_allowance"])
    max_a = float(person["sandal_max_allowance"] if is_sandal else person["closed_max_allowance"])
    width_allowance = None
    width_state = "unknown"
    if foot_width is not None and shoe["inner_width_cm"] is not None:
        width_allowance = round(float(shoe["inner_width_cm"]) - float(foot_width), 2)
        if width_allowance < 0:
            width_state = "too_small"
        elif width_allowance < float(person["width_allowance"]):
            width_state = "tight"
        else:
            width_state = "ok"
    if allowance <= 0 or width_state == "too_small":
        status, label = "zu_klein", "Zu klein"
    elif allowance < min_a or width_state == "tight":
        status, label = "knapp", "Wird knapp"
    elif allowance <= max_a:
        status, label = "passt", "Passt"
    else:
        status, label = "zu_gross", "Noch zu groß"
    if shoe["fit_override"]:
        status = shoe["fit_override"]
        label = {"passt":"Passt (manuell)","knapp":"Knapp (manuell)","zu_klein":"Zu klein (manuell)","zu_gross":"Zu groß (manuell)"}.get(status,status)
    return {
        "status":status,"label":label,"length_allowance_cm":allowance,"length_allowance_mm":round(allowance*10),
        "width_allowance_cm":width_allowance,"width_allowance_mm":None if width_allowance is None else round(width_allowance*10),
        "min_cm":min_a,"max_cm":max_a,
        "reason":shoe["fit_override_reason"] if shoe["fit_override"] else "",
    }


def measurements_for_person(db, person_id):
    return list(db.execute("SELECT * FROM measurements WHERE person_id=? ORDER BY measured_on", (person_id,)))


def weighted_growth_model(rows):
    valid = [r for r in rows if r["length_cm"] is not None]
    if len(valid) < 2:
        return None
    last_date = parse_iso(valid[-1]["measured_on"])
    recent = [r for r in valid if (last_date - parse_iso(r["measured_on"])).days <= 550]
    if len(recent) < 3:
        recent = valid[-6:]
    else:
        recent = recent[-7:]
    base = parse_iso(recent[0]["measured_on"])
    xs = [month_diff(base, parse_iso(r["measured_on"])) for r in recent]
    ys = [float(r["length_cm"]) for r in recent]
    weights = [i+1 for i in range(len(recent))]
    sw = sum(weights)
    mx = sum(w*x for w,x in zip(weights,xs))/sw
    my = sum(w*y for w,y in zip(weights,ys))/sw
    den = sum(w*(x-mx)**2 for w,x in zip(weights,xs))
    slope = 0.0 if den == 0 else sum(w*(x-mx)*(y-my) for w,x,y in zip(weights,xs,ys))/den
    slope = max(0.0, min(slope, 0.35))
    intercept = my - slope*mx
    residuals = [y-(intercept+slope*x) for x,y in zip(xs,ys)]
    residual = statistics.pstdev(residuals) if len(residuals)>1 else 0.0
    return {"slope_cm_per_month":slope,"residual_cm":residual,"base":base,"rows":recent,"intercept":intercept}


def growth_delta(rows, months):
    if len(rows) < 2:
        return None
    latest = rows[-1]
    end = parse_iso(latest["measured_on"])
    target = end - timedelta(days=round(months*30.4375))
    # Use the historical measurement nearest to the requested look-back date.
    # A measurement a few days after the exact cutoff is more representative than
    # falling back many months just because it is on the "wrong" side of the date.
    candidates = rows[:-1]
    before = min(candidates, key=lambda r: abs((parse_iso(r["measured_on"])-target).days))
    actual_months = month_diff(parse_iso(before["measured_on"]), end)
    delta = float(latest["length_cm"]) - float(before["length_cm"])
    return {"from_date":before["measured_on"],"to_date":latest["measured_on"],"from_cm":before["length_cm"],"to_cm":latest["length_cm"],"delta_cm":round(delta,2),"delta_mm":round(delta*10),"actual_months":round(actual_months,1),"per_month_mm":round((delta/actual_months)*10,2) if actual_months else 0}


def forecast_person(db, person_id, months=6, target_date=None):
    rows = measurements_for_person(db, person_id)
    if len(rows) < 2:
        return None
    model = weighted_growth_model(rows)
    if not model:
        return None
    latest = rows[-1]
    last_date = parse_iso(latest["measured_on"])
    if target_date:
        tdate = parse_iso(target_date)
        months = max(0.0, month_diff(last_date, tdate))
    else:
        tdate = last_date + timedelta(days=round(months*30.4375))
    center = float(latest["length_cm"]) + model["slope_cm_per_month"]*months
    uncertainty = max(0.15, min(0.45, model["residual_cm"]*1.8 + 0.08 + 0.015*months))
    return {
        "last_date": latest["measured_on"], "target_date": tdate.isoformat(), "months": round(months,1),
        "current_cm": latest["length_cm"], "forecast_cm": round(center,2),
        "min_cm": round(max(float(latest["length_cm"]),center-uncertainty),2), "max_cm": round(center+uncertainty,2),
        "growth_mm_per_month": round(model["slope_cm_per_month"]*10,2),
        "basis_count": len(model["rows"]), "basis_from": model["rows"][0]["measured_on"], "basis_to": model["rows"][-1]["measured_on"]
    }


def fit_timing(db, person, measurement, shoe, fit):
    if not person or not measurement or not person["growth_enabled"] or shoe["inner_length_cm"] is None:
        return {"remaining_months":None,"starts_fitting_months":None}
    model = weighted_growth_model(measurements_for_person(db, person["id"]))
    if not model or model["slope_cm_per_month"] <= 0.005:
        return {"remaining_months":None,"starts_fitting_months":None}
    slope=model["slope_cm_per_month"]
    current=float(measurement["length_cm"]); inner=float(shoe["inner_length_cm"])
    is_sandal=shoe["category"] in ("sandale_offen","sandale")
    min_a=float(person["sandal_min_allowance"] if is_sandal else person["closed_min_allowance"]); max_a=float(person["sandal_max_allowance"] if is_sandal else person["closed_max_allowance"] )
    max_foot=inner-min_a; min_foot=inner-max_a
    remaining=max(0.0,(max_foot-current)/slope) if max_foot>current else 0.0
    starts=max(0.0,(min_foot-current)/slope) if min_foot>current else 0.0
    return {"remaining_months":round(remaining,1),"starts_fitting_months":round(starts,1)}


def analysis_for_person(db, person_id):
    person = db.execute("SELECT * FROM people WHERE id=?",(person_id,)).fetchone()
    if not person:
        return None
    rows = measurements_for_person(db, person_id)
    result = person_with_latest(db,person)
    result["measurements"] = [rowdict(r) for r in rows]
    result["growth"] = {str(m): growth_delta(rows,m) for m in (4,6,12,24)} if person["growth_enabled"] else {}
    result["forecast_3"] = forecast_person(db,person_id,3) if person["growth_enabled"] else None
    result["forecast_6"] = forecast_person(db,person_id,6) if person["growth_enabled"] else None
    latest = latest_measurement(db,person_id)
    shoes = list(db.execute("SELECT * FROM shoes WHERE status NOT IN ('verkauft','aussortiert','retourniert') AND (person_id=? OR person_id IS NULL) ORDER BY brand,model",(person_id,)))
    result["shoes"] = []
    for s in shoes:
        d = rowdict(s); d["fit"] = fit_for_shoe(person,latest,s)
        d["fit"].update(fit_timing(db,person,latest,s,d["fit"]))
        result["shoes"].append(d)
    return result


def get_options():
    options = {"gemini_enabled":False,"gemini_api_key":"","gemini_model":"gemini-2.5-flash"}
    try:
        if OPTIONS_PATH.exists():
            options.update(json.loads(OPTIONS_PATH.read_text()))
    except Exception:
        pass
    return options


def strip_html(txt):
    txt = re.sub(r"<script\b[^>]*>.*?</script>"," ",txt,flags=re.I|re.S)
    txt = re.sub(r"<style\b[^>]*>.*?</style>"," ",txt,flags=re.I|re.S)
    txt = re.sub(r"<[^>]+>"," ",txt)
    return re.sub(r"\s+"," ",unescape(txt)).strip()


def fetch_url(url, timeout=12):
    req = Request(url,headers={"User-Agent":"Mozilla/5.0 (BarfussKompass/0.1; Home Assistant)","Accept-Language":"de-DE,de;q=0.9,en;q=0.5"})
    with urlopen(req,timeout=timeout) as r:
        return r.read().decode("utf-8","replace"),r.headers.get_content_type()


def parse_wildling(url):
    parsed=urlparse(url)
    host=parsed.hostname or ""
    if not (host=="wildling.shoes" or host.endswith(".wildling.shoes")):
        raise ValueError("Bitte eine Produkt-URL von wildling.shoes verwenden.")
    clean=f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path}".rstrip("/")
    result={"brand":"Wildling","model":"","color":"","current_price":None,"sizes":[],"image_url":"","product_url":url,"source":"Wildling"}
    # Shopify product JSON is preferred because it is structured and independent of visible layout.
    for js_url in (clean+".js", clean+".json"):
        try:
            raw,_=fetch_url(js_url,8)
            obj=json.loads(raw)
            if "product" in obj and isinstance(obj["product"],dict): obj=obj["product"]
            title=obj.get("title") or ""
            if title:
                result["model"]=title.split("|")[0].strip()
            variants=obj.get("variants") or []
            sizes=[]; prices=[]
            for v in variants:
                title_v=str(v.get("title") or "")
                m=re.search(r"(?:EU\s*)?(\d{2})\b",title_v)
                if m: sizes.append(m.group(1))
                p=v.get("price")
                try:
                    pv=float(p)/100 if isinstance(p,int) and p>1000 else float(p)
                    prices.append(pv)
                except Exception: pass
            result["sizes"]=sorted(set(sizes),key=lambda x:int(x))
            if prices: result["current_price"]=round(min(prices),2)
            imgs=obj.get("images") or []
            if imgs:
                first=imgs[0]
                result["image_url"]=first.get("src","") if isinstance(first,dict) else str(first)
            opts=obj.get("options") or []
            for op in opts:
                if isinstance(op,dict) and str(op.get("name","")).lower() in ("farbe","color"):
                    vals=op.get("values") or []
                    if vals: result["color"]=str(vals[0])
            if result["model"]: return result
        except Exception:
            pass
    html,_=fetch_url(clean,12)
    ld_scripts=re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S)
    for block in ld_scripts:
        try:
            obj=json.loads(unescape(block).strip())
            items=obj if isinstance(obj,list) else [obj]
            for item in items:
                if isinstance(item,dict) and item.get("@type") in ("Product",["Product"]):
                    result["model"]=item.get("name") or result["model"]
                    img=item.get("image")
                    if isinstance(img,list) and img: result["image_url"]=img[0]
                    elif isinstance(img,str): result["image_url"]=img
                    offers=item.get("offers")
                    if isinstance(offers,dict): offers=[offers]
                    if isinstance(offers,list):
                        prices=[]
                        for offer in offers:
                            try: prices.append(float(offer.get("price")))
                            except Exception: pass
                        if prices: result["current_price"]=min(prices)
        except Exception: pass
    if not result["model"]:
        m=re.search(r"<h1[^>]*>(.*?)</h1>",html,re.I|re.S)
        if m: result["model"]=strip_html(m.group(1))
    text=strip_html(html)
    cm=re.search(r"(?:Farbe|Color):\s*([^|€]{1,40}?)(?=\s+(?:EU|Adults|Kids|Toddlers|Product|Produkt|\d{2,3}[,.]\d{2}\s*€))",text,re.I)
    if cm: result["color"]=cm.group(1).strip()
    result["sizes"]=sorted(set(re.findall(r"\bEU\s*(\d{2})\b",text,re.I)),key=lambda x:int(x))
    pm=re.search(r"(\d{1,3}[,.]\d{2})\s*€",text)
    if pm: result["current_price"]=float(pm.group(1).replace(".","").replace(",","."))
    if not result["image_url"]:
        im=re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',html,re.I)
        if im: result["image_url"]=unescape(im.group(1))
    if not result["model"]:
        raise ValueError("Produktdaten konnten auf der Wildling-Seite nicht erkannt werden.")
    return result


def gemini_parse_question(question, people_names):
    opts=get_options()
    if not opts.get("gemini_enabled") or not opts.get("gemini_api_key"):
        return None
    schema={
      "type":"OBJECT",
      "properties":{
        "intent":{"type":"STRING","enum":["growth_period","forecast","fit_now","fit_future","shopping_needs","search_shoes","shoe_remaining","unknown"]},
        "person":{"type":"STRING"},"months":{"type":"INTEGER"},"date":{"type":"STRING"},"category":{"type":"STRING"},"status":{"type":"STRING"},"query":{"type":"STRING"},"min_allowance_mm":{"type":"INTEGER"},"max_allowance_mm":{"type":"INTEGER"}
      },"required":["intent"]
    }
    today=date.today().isoformat()
    prompt=("Du interpretierst ausschließlich Fragen an eine lokale Schuh-/Fußdatenbank. "
            "Keine Berechnungen durchführen und keine Fakten erfinden. Extrahiere nur Parameter. "
            f"Heute ist {today}. Personen: {', '.join(people_names)}. "
            "Kategorien: geschlossen, sandale_offen, winter, gummistiefel, sonstige. "
            f"Frage: {question}")
    model=quote(str(opts.get("gemini_model") or "gemini-2.5-flash"),safe="")
    endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body=json.dumps({"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema}},ensure_ascii=False).encode()
    req=Request(endpoint,data=body,method="POST",headers={"Content-Type":"application/json","x-goog-api-key":str(opts["gemini_api_key"])})
    try:
        with urlopen(req,timeout=20) as r:
            obj=json.loads(r.read())
        txt=obj["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(txt)
    except Exception:
        return None


def local_parse_question(question, people_names):
    q=question.lower()
    person=next((n for n in people_names if n.lower() in q),"")
    mm=re.search(r"(?:letzten|in den letzten|in)\s+(\d+)\s+monat",q)
    months=int(mm.group(1)) if mm else None
    category=""
    if "sandale" in q: category="sandale_offen"
    elif "winter" in q: category="winter"
    elif "gumm" in q: category="gummistiefel"
    elif "geschlossen" in q: category="geschlossen"
    amin=re.search(r"(?:mindestens|min\.)\s*(\d+)\s*mm",q); amax=re.search(r"(?:maximal|höchstens|max\.)\s*(\d+)\s*mm",q)
    if any(w in q for w in ("gewachsen","wachstum","zugenommen")):
        return {"intent":"growth_period","person":person,"months":months or 4}
    if any(w in q for w in ("wie groß","wie lang","prognose","in 6 monaten","in 3 monaten")) and any(w in q for w in ("fuß","füß","fues")):
        return {"intent":"forecast","person":person,"months":months or (6 if "6 monat" in q else 3 if "3 monat" in q else 6)}
    if any(w in q for w in ("wie lange", "noch passen", "wann zu klein")) and any(w in q for w in ("schuh","stiefel","sandale")):
        return {"intent":"shoe_remaining","person":person,"query":question}
    if "passen" in q or "passt" in q:
        future=any(w in q for w in MONTHS_DE) or bool(months)
        return {"intent":"fit_future" if future else "fit_now","person":person,"months":months,"category":category,"min_allowance_mm":int(amin.group(1)) if amin else None,"max_allowance_mm":int(amax.group(1)) if amax else None}
    if any(w in q for w in ("kaufen","brauche","neu kaufen")):
        return {"intent":"shopping_needs","person":person,"months":months or 6,"category":category}
    return {"intent":"search_shoes","person":person,"query":question,"category":category,"min_allowance_mm":int(amin.group(1)) if amin else None,"max_allowance_mm":int(amax.group(1)) if amax else None}

MONTHS_DE={"januar":1,"februar":2,"märz":3,"maerz":3,"april":4,"mai":5,"juni":6,"juli":7,"august":8,"september":9,"oktober":10,"november":11,"dezember":12}

def infer_target_date(question):
    q=question.lower(); today=date.today()
    for name,m in MONTHS_DE.items():
        if name in q:
            year=today.year if m>=today.month else today.year+1
            return date(year,m,15).isoformat()
    return None


def answer_question(db, question):
    people=list(db.execute("SELECT * FROM people ORDER BY name")); names=[p["name"] for p in people]
    parsed=gemini_parse_question(question,names) or local_parse_question(question,names)
    person=None
    if parsed.get("person"):
        person=next((p for p in people if p["name"].lower()==str(parsed["person"]).lower()),None)
    if not person:
        # tolerate partial names
        q=question.lower(); person=next((p for p in people if p["name"].lower() in q),None)
    intent=parsed.get("intent","unknown")
    if intent=="growth_period":
        if not person: return {"answer":"Welche Person meinst du?","intent":parsed}
        months=int(parsed.get("months") or 4); rows=measurements_for_person(db,person["id"]); g=growth_delta(rows,months)
        if not g: return {"answer":f"Für {person['name']} liegen dafür noch nicht genügend Messungen vor.","intent":parsed}
        return {"answer":f"{person['name']}s Fußlänge ist im betrachteten Zeitraum um {g['delta_mm']} mm gewachsen: von {g['from_cm']:.1f} cm am {format_date(g['from_date'])} auf {g['to_cm']:.1f} cm am {format_date(g['to_date'])}. Das entspricht über {g['actual_months']:.1f} Monate etwa {g['per_month_mm']:.1f} mm pro Monat.","intent":parsed,"data":g}
    if intent=="forecast":
        if not person: return {"answer":"Welche Person meinst du?","intent":parsed}
        months=int(parsed.get("months") or 6); f=forecast_person(db,person["id"],months)
        if not f: return {"answer":f"Für {person['name']} reichen die Messdaten noch nicht für eine Prognose.","intent":parsed}
        return {"answer":f"Für {person['name']} ergibt die lokale Prognose in etwa {months} Monaten rund {f['forecast_cm']:.1f} cm Fußlänge; sinnvoll ist ein Korridor von ca. {f['min_cm']:.1f}–{f['max_cm']:.1f} cm. Grundlage sind {f['basis_count']} jüngere Messungen von {format_date(f['basis_from'])} bis {format_date(f['basis_to'])}. Gemini berechnet diese Werte nicht.","intent":parsed,"data":f}
    if intent in ("fit_now","fit_future"):
        if not person: return {"answer":"Welche Person meinst du?","intent":parsed}
        latest=latest_measurement(db,person["id"])
        target_date=parsed.get("date") or infer_target_date(question)
        future_len=None; forecast=None
        if intent=="fit_future" and person["growth_enabled"]:
            if target_date: forecast=forecast_person(db,person["id"],target_date=target_date)
            else: forecast=forecast_person(db,person["id"],int(parsed.get("months") or 6))
            if forecast: future_len=forecast["forecast_cm"]
        shoes=list(db.execute("SELECT * FROM shoes WHERE status NOT IN ('verkauft','aussortiert','retourniert') AND (person_id=? OR person_id IS NULL)",(person["id"],)))
        category=parsed.get("category") or ""
        if category:
            shoes=[s for s in shoes if s["category"]==category or (category=="geschlossen" and s["category"] in ("geschlossen","winter","gummistiefel"))]
        results=[]
        for s in shoes:
            fit=fit_for_shoe(person,latest,s,length_override=future_len)
            if fit["status"] in ("passt","knapp"):
                results.append((s,fit))
        if not shoes: return {"answer":f"Für {person['name']} sind noch keine passenden Schuhdatensätze mit Innenmaßen hinterlegt.","intent":parsed}
        if not results:
            when=f" zum {format_date(forecast['target_date'])}" if forecast else " aktuell"
            return {"answer":f"Ich finde für {person['name']}{when} kein vorhandenes Paar innerhalb bzw. knapp unter deinem hinterlegten Zielbereich.","intent":parsed}
        bits=[f"{s['brand']} {s['model']} (EU {s['eu_size']}, {fit['length_allowance_mm']} mm Längenspielraum)" for s,fit in results[:6]]
        when=f"für {format_date(forecast['target_date'])}" if forecast else "aktuell"
        return {"answer":f"Für {person['name']} kommen {when} infrage: "+"; ".join(bits)+".","intent":parsed,"data":{"count":len(results)}}
    if intent=="shoe_remaining":
        if not person: return {"answer":"Welche Person und welches Paar meinst du?","intent":parsed}
        latest=latest_measurement(db,person["id"]); q=question.lower()
        shoes=list(db.execute("SELECT * FROM shoes WHERE status NOT IN ('verkauft','aussortiert','retourniert') AND person_id=?",(person["id"],)))
        if not shoes: return {"answer":f"Für {person['name']} sind noch keine aktiven Schuhe hinterlegt.","intent":parsed}
        matches=[s for s in shoes if s["model"].lower() in q or s["brand"].lower() in q]
        if len(matches)!=1:
            return {"answer":"Nenne bitte das Modell des konkreten Paars, damit ich die Resttragedauer eindeutig berechnen kann.","intent":parsed}
        s=matches[0]; ft=fit_for_shoe(person,latest,s); timing=fit_timing(db,person,latest,s,ft)
        if timing["remaining_months"] is None: return {"answer":f"Für {s['brand']} {s['model']} kann ich ohne aktive Wachstumsprognose keine Restdauer berechnen.","intent":parsed}
        return {"answer":f"{s['brand']} {s['model']} hat aktuell {ft['length_allowance_mm']} mm Längenspielraum. Bei der lokalen Wachstumsschätzung bleibt das Paar voraussichtlich noch etwa {timing['remaining_months']:.1f} Monate oberhalb deines Mindestspielraums. Das ist eine Prognose, keine Garantie.","intent":parsed,"data":timing}
    if intent=="search_shoes":
        shoes=list(db.execute("SELECT * FROM shoes WHERE status NOT IN ('verkauft','aussortiert','retourniert')"))
        if person: shoes=[s for s in shoes if s["person_id"] in (None,person["id"])]
        cat=parsed.get("category") or ""
        if cat: shoes=[s for s in shoes if s["category"]==cat or (cat=="geschlossen" and s["category"] in ("geschlossen","winter","gummistiefel"))]
        found=[]
        latest=latest_measurement(db,person["id"]) if person else None
        for s in shoes:
            ft=fit_for_shoe(person,latest,s) if person else None
            amin=parsed.get("min_allowance_mm"); amax=parsed.get("max_allowance_mm")
            if ft and amin is not None and (ft.get("length_allowance_mm") is None or ft["length_allowance_mm"]<int(amin)): continue
            if ft and amax is not None and (ft.get("length_allowance_mm") is None or ft["length_allowance_mm"]>int(amax)): continue
            found.append((s,ft))
        if not found:return {"answer":"Dazu finde ich im aktuellen Bestand kein passendes Paar.","intent":parsed}
        bits=[f"{s['brand']} {s['model']} (EU {s['eu_size']}"+(f", {ft['length_allowance_mm']} mm" if ft and ft.get('length_allowance_mm') is not None else "")+")" for s,ft in found[:8]]
        return {"answer":"Gefunden: "+"; ".join(bits)+".","intent":parsed,"data":{"count":len(found)}}
    if intent=="shopping_needs":
        if not person: return {"answer":"Welche Person meinst du?","intent":parsed}
        months=int(parsed.get("months") or 6); f=forecast_person(db,person["id"],months) if person["growth_enabled"] else None
        if not f: return {"answer":f"Für {person['name']} ist aktuell keine belastbare Wachstumsprognose aktiv.","intent":parsed}
        latest=latest_measurement(db,person["id"]); shoes=list(db.execute("SELECT * FROM shoes WHERE status NOT IN ('verkauft','aussortiert','retourniert') AND (person_id=? OR person_id IS NULL)",(person["id"],)))
        category=parsed.get("category") or ""
        if category: shoes=[s for s in shoes if s["category"]==category or (category=="geschlossen" and s["category"] in ("geschlossen","winter","gummistiefel"))]
        future_ok=[]
        for s in shoes:
            ft=fit_for_shoe(person,latest,s,length_override=f["forecast_cm"])
            if ft["status"] in ("passt","knapp"): future_ok.append(s)
        if future_ok:
            return {"answer":f"Für {person['name']} gibt es auf Basis der Prognose in {months} Monaten noch {len(future_ok)} vorhandene Paar, die voraussichtlich passen oder knapp werden. Für eine konkrete Saison kannst du z. B. nach Winterstiefeln im November fragen.","intent":parsed}
        return {"answer":f"Für {person['name']} ist für etwa {months} Monate im Voraus aktuell kein vorhandenes Paar mit passenden Innenmaßen hinterlegt. Ein Neukauf dürfte daher wahrscheinlich werden.","intent":parsed}
    return {"answer":"Ich kann Fragen zu Wachstum, Prognosen, aktueller oder zukünftiger Passform und voraussichtlichem Kaufbedarf beantworten. Nenne am besten Person und Zeitraum.","intent":parsed}


def format_date(s):
    try: return parse_iso(s).strftime("%d.%m.%Y")
    except Exception: return s


def dashboard(db):
    people=[]
    for p in db.execute("SELECT * FROM people ORDER BY CASE name WHEN 'Emil' THEN 1 WHEN 'Luna' THEN 2 WHEN 'secondary' THEN 3 WHEN 'primary' THEN 4 ELSE 9 END,name"):
        pd=person_with_latest(db,p)
        latest=latest_measurement(db,p["id"])
        counts={"passt":0,"knapp":0,"zu_klein":0,"zu_gross":0,"unbekannt":0}
        for s in db.execute("SELECT * FROM shoes WHERE status NOT IN ('verkauft','aussortiert','retourniert') AND person_id=?",(p["id"],)):
            ft=fit_for_shoe(p,latest,s); counts[ft["status"]]=counts.get(ft["status"],0)+1
        pd["fit_counts"]=counts
        if latest and p["measurement_interval_days"]:
            due=parse_iso(latest["measured_on"])+timedelta(days=p["measurement_interval_days"])
            pd["next_measurement_due"]=due.isoformat(); pd["measurement_due_days"]=(due-date.today()).days
        else:
            pd["next_measurement_due"]=None; pd["measurement_due_days"]=None
        people.append(pd)
    stats={}
    stats["total_shoes"]=db.execute("SELECT COUNT(*) c FROM shoes").fetchone()["c"]
    for st in ("aktiv","reserve","zum_verkauf","verkauft","aussortiert"):
        stats[st]=db.execute("SELECT COUNT(*) c FROM shoes WHERE status=?",(st,)).fetchone()["c"]
    return {"app":{"name":APP_NAME,"version":APP_VERSION},"people":people,"stats":stats,"gemini":gemini_status()}


def gemini_status():
    o=get_options(); return {"enabled":bool(o.get("gemini_enabled")),"configured":bool(o.get("gemini_api_key")),"model":o.get("gemini_model") or ""}


def json_bytes(obj):
    return json.dumps(obj,ensure_ascii=False,separators=(",",":"),default=str).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version="BarfussKompass/0.1"
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {self.client_address[0]} {fmt%args}")

    def _send(self,status=200,body=b"",ctype="application/json; charset=utf-8",headers=None):
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Referrer-Policy","same-origin")
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

    def send_json(self,obj,status=200): self._send(status,json_bytes(obj))

    def read_json(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        if n>8_000_000: raise ValueError("Anfrage zu groß")
        raw=self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        try: self.handle_get()
        except Exception as e: self.send_json({"error":str(e)},500)

    def do_POST(self):
        try: self.handle_post()
        except ValueError as e: self.send_json({"error":str(e)},400)
        except Exception as e: self.send_json({"error":str(e)},500)

    def do_PUT(self):
        try: self.handle_put()
        except ValueError as e: self.send_json({"error":str(e)},400)
        except Exception as e: self.send_json({"error":str(e)},500)

    def do_DELETE(self):
        try: self.handle_delete()
        except Exception as e: self.send_json({"error":str(e)},500)

    def handle_get(self):
        u=urlparse(self.path); path=u.path; qs=parse_qs(u.query)
        if path in ("/api/health","/health"):
            return self.send_json({"status":"ok","name":APP_NAME,"version":APP_VERSION,"port":PORT})
        with DB_LOCK, db_connect() as db:
            if path=="/api/dashboard": return self.send_json(dashboard(db))
            if path=="/api/people":
                return self.send_json([person_with_latest(db,p) for p in db.execute("SELECT * FROM people ORDER BY name")])
            if path=="/api/measurements":
                where=""; args=[]
                if qs.get("person_id"): where=" WHERE person_id=?"; args=[int(qs["person_id"][0])]
                rows=[rowdict(r) for r in db.execute("SELECT * FROM measurements"+where+" ORDER BY measured_on DESC",args)]
                return self.send_json(rows)
            if path=="/api/shoes":
                clauses=[];args=[]
                if qs.get("person_id") and qs["person_id"][0]: clauses.append("person_id=?");args.append(int(qs["person_id"][0]))
                if qs.get("status") and qs["status"][0]: clauses.append("status=?");args.append(qs["status"][0])
                if qs.get("category") and qs["category"][0]: clauses.append("category=?");args.append(qs["category"][0])
                if qs.get("search") and qs["search"][0]:
                    q="%"+qs["search"][0]+"%"; clauses.append("(brand LIKE ? OR model LIKE ? OR color LIKE ? OR eu_size LIKE ?)");args += [q,q,q,q]
                sql="SELECT s.*,p.name person_name,mn.note model_note,mn.fit_tags model_fit_tags FROM shoes s LEFT JOIN people p ON p.id=s.person_id LEFT JOIN model_notes mn ON lower(mn.brand)=lower(s.brand) AND lower(mn.model)=lower(s.model)"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY s.updated_at DESC,s.id DESC"
                rows=[]
                for s in db.execute(sql,args):
                    d=rowdict(s)
                    if s["person_id"]:
                        p=db.execute("SELECT * FROM people WHERE id=?",(s["person_id"],)).fetchone(); m=latest_measurement(db,s["person_id"]); d["fit"]=fit_for_shoe(p,m,s); d["fit"].update(fit_timing(db,p,m,s,d["fit"]))
                    else: d["fit"]={"status":"unbekannt","label":"Nicht zugeordnet"}
                    rows.append(d)
                return self.send_json(rows)
            m=re.fullmatch(r"/api/analysis/person/(\d+)",path)
            if m:
                a=analysis_for_person(db,int(m.group(1)))
                return self.send_json(a if a else {"error":"Person nicht gefunden"},200 if a else 404)
            if path=="/api/settings": return self.send_json({"gemini":gemini_status(),"rules":{"closed_default_cm":[1.2,1.7],"sandal_open_cm":[0.7,1.0],"width_allowance_cm":0.4},"port":PORT})
            if path=="/api/export/json":
                payload={"exported_at":datetime.now().isoformat(),"version":APP_VERSION,"people":[rowdict(r) for r in db.execute("SELECT * FROM people")],"measurements":[rowdict(r) for r in db.execute("SELECT * FROM measurements")],"shoes":[rowdict(r) for r in db.execute("SELECT * FROM shoes")],"model_notes":[rowdict(r) for r in db.execute("SELECT * FROM model_notes")]}
                b=json.dumps(payload,ensure_ascii=False,indent=2).encode(); return self._send(200,b,"application/json; charset=utf-8",{"Content-Disposition":"attachment; filename=barfusskompass-export.json"})
            if path=="/api/export/csv":
                typ=qs.get("type",["shoes"])[0]
                table="measurements" if typ=="measurements" else "shoes"
                rows=list(db.execute(f"SELECT * FROM {table}")); out=io.StringIO()
                if rows:
                    w=csv.DictWriter(out,fieldnames=rows[0].keys());w.writeheader();[w.writerow(dict(r)) for r in rows]
                b=out.getvalue().encode("utf-8-sig"); return self._send(200,b,"text/csv; charset=utf-8",{"Content-Disposition":f"attachment; filename=barfusskompass-{table}.csv"})
        if path.startswith("/uploads/"):
            file=(UPLOAD_DIR / path.split("/uploads/",1)[1]).resolve()
            if not str(file).startswith(str(UPLOAD_DIR.resolve())) or not file.exists(): return self._send(404,b"not found","text/plain")
            return self.serve_file(file,cache=True)
        if path=="/manifest.webmanifest": return self.serve_file(STATIC_DIR/"manifest.webmanifest",cache=False)
        if path.startswith("/static/"): return self.serve_file(STATIC_DIR/path.split("/static/",1)[1],cache=True)
        if path in ("/","/index.html") or not path.startswith("/api/"): return self.serve_file(STATIC_DIR/"index.html",cache=False)
        return self.send_json({"error":"Nicht gefunden"},404)

    def serve_file(self,file,cache=False):
        file=Path(file)
        if not file.exists() or not file.is_file(): return self._send(404,b"not found","text/plain")
        ctype=mimetypes.guess_type(str(file))[0] or "application/octet-stream"; data=file.read_bytes()
        headers={"Cache-Control":"public, max-age=86400" if cache else "no-store"}
        return self._send(200,data,ctype,headers)

    def handle_post(self):
        u=urlparse(self.path); path=u.path; data=self.read_json()
        with DB_LOCK, db_connect() as db:
            if path=="/api/people":
                cur=db.execute("""INSERT INTO people(name,person_type,growth_enabled,closed_min_allowance,closed_max_allowance,width_allowance,sandal_min_allowance,sandal_max_allowance,measurement_interval_days,notes) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
                    str(data.get("name","")).strip(),data.get("person_type","adult"),1 if data.get("growth_enabled") else 0,float(data.get("closed_min_allowance",1.2)),float(data.get("closed_max_allowance",1.7)),float(data.get("width_allowance",0.4)),float(data.get("sandal_min_allowance",0.7)),float(data.get("sandal_max_allowance",1.0)),data.get("measurement_interval_days") or None,data.get("notes","")
                )); db.commit(); return self.send_json({"id":cur.lastrowid},201)
            if path=="/api/measurements":
                cur=db.execute("""INSERT INTO measurements(person_id,measured_on,length_cm,width_cm,left_length_cm,right_length_cm,left_width_cm,right_width_cm,quality,method,historical_target_min_cm,historical_target_max_cm,historical_target_width_cm,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    int(data["person_id"]),data.get("measured_on") or date.today().isoformat(),float(data["length_cm"]),to_float(data.get("width_cm")),to_float(data.get("left_length_cm")),to_float(data.get("right_length_cm")),to_float(data.get("left_width_cm")),to_float(data.get("right_width_cm")),data.get("quality","exact"),data.get("method","manuell"),to_float(data.get("historical_target_min_cm")),to_float(data.get("historical_target_max_cm")),to_float(data.get("historical_target_width_cm")),data.get("notes","")
                ));db.commit();return self.send_json({"id":cur.lastrowid},201)
            if path=="/api/shoes":
                photo=save_photo_data(data.get("photo_data")) if data.get("photo_data") else ""
                cur=db.execute("""INSERT INTO shoes(brand,model,color,eu_size,category,season,barefoot,person_id,status,order_status,purchase_date,purchase_price,purchase_store,product_url,product_image_url,photo_path,inner_length_cm,inner_width_cm,measurement_method,usable_surface,condition,experience_note,purchase_reason,wear_context,favorite,fit_override,fit_override_reason,sold_date,sold_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",shoe_values(data,photo)); upsert_model_note(db,data); db.commit();return self.send_json({"id":cur.lastrowid},201)
            if path=="/api/import/wildling":
                result=parse_wildling(str(data.get("url","")).strip());return self.send_json(result)
            if path=="/api/ask":
                q=str(data.get("question","")).strip()
                if not q: raise ValueError("Bitte eine Frage eingeben.")
                return self.send_json(answer_question(db,q))
            if path=="/api/backup":
                db.commit(); stamp=datetime.now().strftime("%Y%m%d-%H%M%S"); target=BACKUP_DIR/f"barfusskompass-{stamp}.db"; shutil.copy2(DB_PATH,target)
                return self.send_json({"ok":True,"file":target.name,"created_at":datetime.now().isoformat()})
        return self.send_json({"error":"Nicht gefunden"},404)

    def handle_put(self):
        path=urlparse(self.path).path;data=self.read_json()
        with DB_LOCK, db_connect() as db:
            m=re.fullmatch(r"/api/people/(\d+)",path)
            if m:
                pid=int(m.group(1)); old=db.execute("SELECT * FROM people WHERE id=?",(pid,)).fetchone()
                if not old:return self.send_json({"error":"Nicht gefunden"},404)
                vals={**dict(old),**data}
                db.execute("""UPDATE people SET name=?,person_type=?,growth_enabled=?,closed_min_allowance=?,closed_max_allowance=?,width_allowance=?,sandal_min_allowance=?,sandal_max_allowance=?,measurement_interval_days=?,notes=? WHERE id=?""",(vals["name"],vals["person_type"],1 if vals["growth_enabled"] else 0,float(vals["closed_min_allowance"]),float(vals["closed_max_allowance"]),float(vals["width_allowance"]),float(vals["sandal_min_allowance"]),float(vals["sandal_max_allowance"]),vals.get("measurement_interval_days") or None,vals.get("notes","") ,pid));db.commit();return self.send_json({"ok":True})
            m=re.fullmatch(r"/api/shoes/(\d+)",path)
            if m:
                sid=int(m.group(1)); old=db.execute("SELECT * FROM shoes WHERE id=?",(sid,)).fetchone()
                if not old:return self.send_json({"error":"Nicht gefunden"},404)
                vals={**dict(old),**data};photo=old["photo_path"]
                if data.get("photo_data"): photo=save_photo_data(data["photo_data"])
                db.execute("""UPDATE shoes SET brand=?,model=?,color=?,eu_size=?,category=?,season=?,barefoot=?,person_id=?,status=?,order_status=?,purchase_date=?,purchase_price=?,purchase_store=?,product_url=?,product_image_url=?,photo_path=?,inner_length_cm=?,inner_width_cm=?,measurement_method=?,usable_surface=?,condition=?,experience_note=?,purchase_reason=?,wear_context=?,favorite=?,fit_override=?,fit_override_reason=?,sold_date=?,sold_price=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",shoe_values(vals,photo)+(sid,)); upsert_model_note(db,vals); db.commit();return self.send_json({"ok":True})
        return self.send_json({"error":"Nicht gefunden"},404)

    def handle_delete(self):
        path=urlparse(self.path).path
        with DB_LOCK, db_connect() as db:
            m=re.fullmatch(r"/api/measurements/(\d+)",path)
            if m: db.execute("DELETE FROM measurements WHERE id=?",(int(m.group(1)),));db.commit();return self.send_json({"ok":True})
            m=re.fullmatch(r"/api/shoes/(\d+)",path)
            if m: db.execute("UPDATE shoes SET status='aussortiert',updated_at=CURRENT_TIMESTAMP WHERE id=?",(int(m.group(1)),));db.commit();return self.send_json({"ok":True})
        return self.send_json({"error":"Nicht gefunden"},404)


def to_float(v):
    if v in (None,""): return None
    return float(str(v).replace(",","."))


def shoe_values(data,photo):
    return (
        str(data.get("brand","")).strip(),str(data.get("model","")).strip(),str(data.get("color","")).strip(),str(data.get("eu_size","")).strip(),data.get("category","geschlossen"),data.get("season","ganzjährig"),1 if data.get("barefoot",True) else 0,int(data["person_id"]) if data.get("person_id") else None,data.get("status","aktiv"),data.get("order_status","behalten"),data.get("purchase_date") or None,to_float(data.get("purchase_price")),str(data.get("purchase_store","")).strip(),str(data.get("product_url","")).strip(),str(data.get("product_image_url","")).strip(),photo,to_float(data.get("inner_length_cm")),to_float(data.get("inner_width_cm")),data.get("measurement_method","selbst gemessen"),1 if data.get("usable_surface") else 0,data.get("condition","gut"),data.get("experience_note","") or "",data.get("purchase_reason","") or "",data.get("wear_context","") or "",1 if data.get("favorite") else 0,data.get("fit_override","") or "",data.get("fit_override_reason","") or "",data.get("sold_date") or None,to_float(data.get("sold_price"))
    )


def upsert_model_note(db,data):
    note=str(data.get("model_note","") or "").strip(); tags=str(data.get("model_fit_tags","") or "").strip()
    brand=str(data.get("brand","") or "").strip(); model=str(data.get("model","") or "").strip()
    if brand and model and (note or tags):
        db.execute("""INSERT INTO model_notes(brand,model,note,fit_tags) VALUES(?,?,?,?) ON CONFLICT(brand,model) DO UPDATE SET note=excluded.note,fit_tags=excluded.fit_tags""",(brand,model,note,tags))


def save_photo_data(data_url):
    m=re.match(r"data:(image/(?:png|jpeg|webp));base64,(.+)",data_url,re.S)
    if not m: raise ValueError("Fotoformat nicht unterstützt")
    ext={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}[m.group(1)]
    raw=base64.b64decode(m.group(2),validate=True)
    if len(raw)>5_000_000: raise ValueError("Foto ist größer als 5 MB")
    name=f"{uuid.uuid4().hex}.{ext}";(UPLOAD_DIR/name).write_bytes(raw);return name


def main():
    init_db()
    server=ThreadingHTTPServer(("0.0.0.0",PORT),Handler)
    print(f"{APP_NAME} {APP_VERSION} lauscht auf 0.0.0.0:{PORT}")
    server.serve_forever()

if __name__=="__main__": main()
