from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import shutil
import hashlib
import requests
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from watchfiles import awatch
from football_monitor import monitor_once as football_monitor_once, collect_blocks as football_collect_blocks
from football_monitor import API_FOOTBALL_BASE, OPENLIGA_BASE, _api_football_get_day, _choose_api_fixture, _normalize_api_fixture
from kicktipp_live import cached_public_detail as kicktipp_cached_public_detail
from kicktipp_live import resolve_public_detail_url as kicktipp_resolve_public_detail_url

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/data") if Path("/data").exists() else APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OPTIONS_FILE = Path("/data/options.json")
STATE_FILE = DATA_DIR / "kicktipp_browser_state.json"
LAST_SCREENSHOT = DATA_DIR / "last_kicktipp_result.png"
LAST_LOG = DATA_DIR / "last_run.json"
AUTO_STATE_FILE = DATA_DIR / "auto_import_state.json"
FAILED_DRIVE_IDS_FILE = DATA_DIR / "failed_drive_ids.json"
PROCESSED_DRIVE_IDS_FILE = DATA_DIR / "processed_drive_ids.json"
PROCESSED_TIP_HASHES_FILE = DATA_DIR / "processed_tip_hashes.json"
AUTO_IMPORT_LOCK = asyncio.Lock()
BACKGROUND_TASKS: list[asyncio.Task] = []
TABLE_PUSH_STATE_FILE = DATA_DIR / "table_push_state.json"
FOOTBALL_PUSH_STATE_FILE = DATA_DIR / "football_push_state.json"
FOOTBALL_MATCH_PUSH_PREFS_FILE = DATA_DIR / "football_match_push_prefs.json"
API_FOOTBALL_USAGE_FILE = DATA_DIR / "api_football_usage.json"
TABLE_BROWSER_LOCK = asyncio.Lock()
TABLE_PUSH_IMAGE_DIR = Path("/config/www/kicktipp_tipbot") if Path("/config").exists() else DATA_DIR / "kicktipp_tipbot_www"
BERLIN_TZ = ZoneInfo("Europe/Berlin")

app = FastAPI(title="Kicktipp TipBot", version="0.1.42")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def load_options() -> dict[str, Any]:
    defaults = {
        "tipprunde": "",
        "username": "",
        "password": "",
        "vfl_team": "VfL Osnabrück",
        "auto_save_default": True,
        "kicktipp_url": "",
        "google_drive_import_enabled": True,
        "google_drive_folder_id": "14k24aZyGt2wu88xGEREvYumuhxMtnbUt",
        "google_drive_service_account_file": "/share/Kleinanzeigen/google-drive-service-account.json",
        "google_drive_poll_seconds": 5,
        "media_import_dir": "/media/Import/Kicktippprimary",
        "notify_service": "",
        "table_push_enabled": True,
        "table_include_all_players": True,
        "table_user_name": "primary",
        "table_push_poll_seconds": 120,
        "football_push_enabled": True,
        "football_push_poll_seconds": 60,
        "football_push_url": "http://192.168.10.199:8148/?view=football",
        "football_favorite_teams": "VfL Osnabrück|Bayer 04 Leverkusen",
        "football_bl1_enabled": True,
        "football_bl2_enabled": True,
        "football_dfb_enabled": True,
        "football_supercup_enabled": True,
        "football_germany_enabled": True,
        "football_ucl_enabled": True,
        "football_uel_enabled": True,
        "football_uecl_enabled": True,
        "api_football_key": "",
        "api_football_halftime_poll_seconds": 60,
    }
    if OPTIONS_FILE.exists():
        try:
            data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
            defaults.update({k: v for k, v in data.items() if v is not None})
        except Exception:
            pass
    return defaults


def _read_match_push_prefs() -> dict[str, Any]:
    if not FOOTBALL_MATCH_PUSH_PREFS_FILE.exists():
        return {}
    try:
        data = json.loads(FOOTBALL_MATCH_PUSH_PREFS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_match_push_prefs(data: dict[str, Any]) -> None:
    FOOTBALL_MATCH_PUSH_PREFS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_team(value: str) -> str:
    value = value.lower().strip()
    repl = {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        ".": "", ",": "", "-": " ", "–": " ", "—": " ", ":": "",
    }
    for old, new in repl.items():
        value = value.replace(old, new)
    value = re.sub(r"\b(1|fc|sc|sv|vfl|vfb|tsv|sg|spvgg|ksc|fck|hsv|dsc)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    aliases = {
        "osnabrueck": "osnabrueck",
        "st pauli": "pauli",
        "sankt pauli": "pauli",
        "greuther fuerth": "fuerth",
        "fuerth": "fuerth",
        "hannover 96": "hannover",
        "hannover": "hannover",
        "hertha bsc": "hertha",
        "hertha": "hertha",
        "kaiserslautern": "kaiserslautern",
        "lautern": "kaiserslautern",
        "arminia bielefeld": "bielefeld",
        "bielefeld": "bielefeld",
        "holstein kiel": "kiel",
        "kiel": "kiel",
        "energie cottbus": "cottbus",
        "cottbus": "cottbus",
        "dynamo dresden": "dresden",
        "dresden": "dresden",
        "eintracht braunschweig": "braunschweig",
        "braunschweig": "braunschweig",
        "karlsruher": "karlsruhe",
        "karlsruhe": "karlsruhe",
        "magdeburg": "magdeburg",
        "darmstadt 98": "darmstadt",
        "darmstadt": "darmstadt",
        "heidenheim": "heidenheim",
        "wolfsburg": "wolfsburg",
        "bochum": "bochum",
        "nuernberg": "nuernberg",
        "nürnberg": "nuernberg",
        "fc nuernberg": "nuernberg",
        "1 fc nuernberg": "nuernberg",
    }
    return aliases.get(value, value)


@dataclass
class Tip:
    home: str
    away: str
    home_goals: int
    away_goals: int
    line: str


LINE_RE = re.compile(
    r"^\s*(?P<home>.+?)\s*(?:-|–|—|gegen|vs\.?|:)\s*(?P<away>.+?)\s*[: ]\s*(?P<h>\d{1,2})\s*[:\-]\s*(?P<a>\d{1,2})\s*$",
    re.IGNORECASE,
)


def parse_tips(text: str) -> list[Tip]:
    tips: list[Tip] = []
    ignored_prefixes = ("freitag", "samstag", "sonntag", "montag", "dienstag", "mittwoch", "donnerstag", "spieltag")
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        if not line or line.lower().startswith(ignored_prefixes):
            continue
        line = re.sub(r"^[-*•\d.)\s]+", "", line).strip()
        match = LINE_RE.match(line)
        if not match:
            continue
        tips.append(
            Tip(
                home=match.group("home").strip(),
                away=match.group("away").strip(),
                home_goals=int(match.group("h")),
                away_goals=int(match.group("a")),
                line=line,
            )
        )
    return tips


def vfl_violation(tip: Tip, vfl_team: str) -> Optional[str]:
    vfl_norm = normalize_team(vfl_team)
    home_norm = normalize_team(tip.home)
    away_norm = normalize_team(tip.away)
    if vfl_norm and vfl_norm in home_norm and tip.home_goals < tip.away_goals:
        return f"Blockiert: {tip.line} tippt gegen {vfl_team}."
    if vfl_norm and vfl_norm in away_norm and tip.away_goals < tip.home_goals:
        return f"Blockiert: {tip.line} tippt gegen {vfl_team}."
    return None


class ParseRequest(BaseModel):
    text: str
    vfl_team: str = "VfL Osnabrück"


class RunRequest(BaseModel):
    text: str
    tipprunde: str = ""
    kicktipp_url: str = ""
    username: str = ""
    password: str = ""
    vfl_team: str = "VfL Osnabrück"
    save: bool = False
    overwrite_existing: bool = False


class AutoRetryRequest(BaseModel):
    file_id: str = ""


class MatchPushPreferenceRequest(BaseModel):
    game_id: str
    home: str
    away: str
    kickoff: str
    competition: str = ""
    competition_label: str = ""
    detail_url: str = ""
    goals: bool = False
    cards: bool = False
    reminder_30: bool = False
    halftime: bool = True
    final: bool = True
    mute_all: bool = False


def build_target_url(tipprunde: str, kicktipp_url: str) -> str:
    url = (kicktipp_url or "").strip()
    if url:
        if not url.startswith("http"):
            url = "https://" + url
        return url
    name = tipprunde.strip().strip("/")
    if not name:
        raise HTTPException(status_code=400, detail="Bitte Tipprunde oder direkte Kicktipp-URL angeben.")
    return f"https://www.kicktipp.de/{name}/tippabgabe"


async def click_cookie_if_present(page: Page) -> None:
    for pattern in ["Akzeptieren", "Alle akzeptieren", "Zustimmen", "Einverstanden", "Accept"]:
        try:
            await page.get_by_role("button", name=re.compile(pattern, re.I)).click(timeout=1200)
            await page.wait_for_timeout(500)
            return
        except Exception:
            pass


async def ensure_login(page: Page, target_url: str, username: str, password: str) -> bool:
    await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    await click_cookie_if_present(page)
    content = (await page.content()).lower()
    if "passwort" not in content and "password" not in content and "login" not in page.url.lower():
        return False

    if not username or not password:
        raise HTTPException(status_code=400, detail="Kicktipp möchte einen Login. Bitte Benutzername und Passwort in der Add-on-Konfiguration oder im Formular eintragen.")

    user_selectors = [
        'input[name="kennung"]', 'input[name="username"]', 'input[name="user"]',
        'input[name="email"]', 'input[type="email"]', '#kennung', '#username', '#email'
    ]
    pass_selectors = ['input[name="passwort"]', 'input[name="password"]', 'input[type="password"]', '#passwort', '#password']

    filled_user = False
    for sel in user_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=500):
                await loc.fill(username)
                filled_user = True
                break
        except Exception:
            continue
    filled_pass = False
    for sel in pass_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=500):
                await loc.fill(password)
                filled_pass = True
                break
        except Exception:
            continue
    if not filled_user or not filled_pass:
        raise HTTPException(status_code=500, detail="Login-Felder wurden nicht gefunden. Kicktipp-Seite hat sich evtl. geändert.")

    clicked = False
    for pattern in ["Einloggen", "Anmelden", "Login"]:
        try:
            await page.get_by_role("button", name=re.compile(pattern, re.I)).click(timeout=2000)
            clicked = True
            break
        except Exception:
            pass
    if not clicked:
        try:
            await page.locator('input[type="submit"], button[type="submit"]').first.click(timeout=2000)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Login-Button wurde nicht gefunden: {exc}")

    await page.wait_for_load_state("domcontentloaded", timeout=60000)
    await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    return True


FILL_SCRIPT = r"""
({tips, overwriteExisting}) => {
  const norm = (s) => (s || '')
    .toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/ß/g, 'ss')
    .replace(/[.,:;()\[\]{}]/g, ' ')
    .replace(/[–—-]/g, ' ')
    .replace(/\b(1|fc|sc|sv|vfl|vfb|tsv|sg|spvgg|ksc|fck|hsv|dsc|bsc|tsg|rb)\b/g, ' ')
    // Gründungsjahre sind in Datenquellen/Kicktipp uneinheitlich enthalten
    // (z. B. "VfL Bochum 1848" vs. "VfL Bochum", "1. FC Heidenheim 1846" vs. "Heidenheim").
    // Vierstellige Vereinsjahre daher für das Matching generell ignorieren.
    .replace(/\b(?:18|19|20)\d{2}\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const alias = (s) => {
    const n = norm(s);
    const map = {
      'osnabruck':'osnabruck','osnabrueck':'osnabruck','st pauli':'pauli','sankt pauli':'pauli',
      'greuther furth':'furth','greuther fuerth':'furth','furth':'furth','fuerth':'furth',
      'hannover 96':'hannover','hannover':'hannover','hertha bsc':'hertha','hertha':'hertha',
      'kaiserslautern':'kaiserslautern','lautern':'kaiserslautern','arminia bielefeld':'bielefeld',
      'bielefeld':'bielefeld','holstein kiel':'kiel','kiel':'kiel','energie cottbus':'cottbus',
      'cottbus':'cottbus','dynamo dresden':'dresden','dresden':'dresden','eintracht braunschweig':'braunschweig',
      'braunschweig':'braunschweig','karlsruher':'karlsruhe','karlsruhe':'karlsruhe',
      'magdeburg':'magdeburg','darmstadt 98':'darmstadt','darmstadt':'darmstadt','heidenheim':'heidenheim',
      'wolfsburg':'wolfsburg','bochum':'bochum','nurnberg':'nurnberg','nuernberg':'nurnberg'
    };
    return map[n] || n;
  };
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const inputSelector = 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([disabled])';
  const allContainers = Array.from(document.querySelectorAll('tr, li, .row, .spiel, .game, .match, .panel, .card, div'))
    .filter(el => visible(el) && el.querySelectorAll(inputSelector).length >= 2);

  const results = [];
  for (const tip of tips) {
    const h = alias(tip.home);
    const a = alias(tip.away);
    let candidates = allContainers.filter(el => {
      const text = alias(el.innerText || el.textContent || '');
      return text.includes(h) && text.includes(a);
    }).sort((x, y) => (x.innerText || '').length - (y.innerText || '').length);

    let row = candidates[0];
    if (!row) {
      results.push({line: tip.line, status: 'not_found', detail: 'Zeile nicht gefunden. Kicktipp-Namen prüfen oder Alias ergänzen'});
      continue;
    }
    let inputs = Array.from(row.querySelectorAll(inputSelector)).filter(visible);
    if (inputs.length < 2) {
      results.push({line: tip.line, status: 'not_found', detail: 'Torfelder nicht gefunden'});
      continue;
    }
    const alreadyFilled = inputs.slice(0, 2).some(inp => (inp.value || '').trim() !== '');
    if (alreadyFilled && !overwriteExisting) {
      results.push({line: tip.line, status: 'skipped', detail: 'bereits gefüllt'});
      continue;
    }
    const values = [String(tip.home_goals), String(tip.away_goals)];
    for (let i = 0; i < 2; i++) {
      const inp = inputs[i];
      inp.focus();
      inp.value = values[i];
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      inp.blur();
    }
    results.push({line: tip.line, status: 'filled', detail: `${tip.home_goals}:${tip.away_goals}`});
  }
  return results;
}
"""


async def save_page(page: Page) -> str:
    """Speichert die Tippabgabe robust auch dann, wenn Kicktipps Submit-Button
    außerhalb des Playwright-Viewports liegt. Playwrights normaler click() kann
    in diesem Fall fehlschlagen, obwohl der Button im DOM sichtbar und aktiv ist.
    Deshalb wird zuerst direkt im DOM der passende Submitter/Formular-Submit
    ausgelöst. Erst danach kommen normale Klick-Fallbacks.
    """

    async def wait_after_submit() -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
        await page.wait_for_timeout(1800)

    # 1) Robuster DOM-Submit: funktioniert auch, wenn der Button außerhalb des Viewports liegt.
    try:
        submit_result = await page.evaluate(
            r"""
            () => {
              const textOf = (el) => [
                el.innerText,
                el.textContent,
                el.value,
                el.getAttribute('aria-label'),
                el.getAttribute('title'),
                el.name,
                el.id
              ].filter(Boolean).join(' ').trim();

              const wanted = /tipps?\s*speichern|speichern|abgeben|submitbutton/i;
              const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'));
              let button = buttons.find((b) => wanted.test(textOf(b))) ||
                document.querySelector('button[name="submitbutton"], input[name="submitbutton"], button[type="submit"], input[type="submit"]');

              const forms = Array.from(document.querySelectorAll('form'));
              let form = button && button.form ? button.form : null;
              if (!form) {
                form = forms.find((f) => f.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])').length >= 2) || forms[0] || null;
              }

              if (button) {
                try {
                  button.click();
                  return {ok: true, method: 'DOM button.click', label: textOf(button)};
                } catch (e) {}
              }

              if (form && button && typeof form.requestSubmit === 'function') {
                form.requestSubmit(button);
                return {ok: true, method: 'DOM requestSubmit(button)', label: textOf(button)};
              }

              if (form && typeof form.requestSubmit === 'function') {
                form.requestSubmit();
                return {ok: true, method: 'DOM requestSubmit(form)', label: ''};
              }

              if (form) {
                form.submit();
                return {ok: true, method: 'DOM form.submit', label: ''};
              }

              return {ok: false, method: '', label: '', reason: 'Kein Formular oder Submit-Button gefunden'};
            }
            """
        )
        if submit_result and submit_result.get("ok"):
            await wait_after_submit()
            method = submit_result.get("method", "DOM-Submit")
            label = submit_result.get("label") or "Speichern"
            return f"Gespeichert über: {method} ({label})"
        last_error = str(submit_result)
    except Exception as exc:
        last_error = str(exc)

    # 2) Fallback: normaler Playwright-Klick mit größerem Viewport und Force-Klick.
    try:
        await page.set_viewport_size({"width": 1440, "height": 2400})
    except Exception:
        pass

    candidates = [
        ("role", "Tipps speichern"),
        ("role", "Speichern"),
        ("role", "Tipp speichern"),
        ("role", "Abgeben"),
        ("css", 'button[name="submitbutton"]'),
        ("css", 'input[name="submitbutton"]'),
        ("css", 'button:has-text("Speichern")'),
        ("css", 'input[type="submit"][value*="Speichern"]'),
        ("css", 'input[type="submit"]'),
        ("css", 'button[type="submit"]'),
    ]

    for kind, selector in candidates:
        try:
            if kind == "role":
                target = page.get_by_role("button", name=re.compile(selector, re.I)).first
            else:
                target = page.locator(selector).first

            await target.scroll_into_view_if_needed(timeout=3000)
            await page.wait_for_timeout(300)
            await target.click(timeout=5000, force=True)
            await wait_after_submit()
            return f"Gespeichert über: {selector}"
        except Exception as exc:
            last_error = str(exc)

    raise HTTPException(status_code=500, detail=f"Speichern nicht möglich: Button/Formular nicht gefunden oder nicht auslösbar ({last_error})")


CLEAR_TIPS_SCRIPT = r"""
() => {
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const scoreSelector = [
    'input[type="number"]',
    'input[type="text"]',
    'input[type="tel"]',
    'input:not([type])'
  ].join(',');

  const scoreInputs = Array.from(document.querySelectorAll(scoreSelector))
    .filter(el => visible(el) && !el.disabled && !el.readOnly)
    .filter(el => {
      const value = (el.value || '').trim();
      return value === '' || /^\d{1,2}$/.test(value);
    });

  const containers = Array.from(document.querySelectorAll('tr, li, .row, .spiel, .game, .match, .panel, .card, div'))
    .filter(visible)
    .map(el => {
      const inputs = Array.from(el.querySelectorAll(scoreSelector)).filter(inp => scoreInputs.includes(inp));
      return {el, inputs, text: (el.innerText || el.textContent || '').trim()};
    })
    .filter(x => x.inputs.length >= 2 && x.text.length > 1 && x.text.length < 600)
    .sort((a, b) => a.text.length - b.text.length);

  const used = new Set();
  const rows = [];
  for (const c of containers) {
    const free = c.inputs.filter(inp => !used.has(inp));
    if (free.length < 2) continue;
    const pair = free.slice(0, 2);
    const values = pair.map(inp => (inp.value || '').trim());
    if (!values.every(v => v === '' || /^\d{1,2}$/.test(v))) continue;
    pair.forEach(inp => used.add(inp));
    rows.push(pair);
  }

  let clearedRows = 0;
  let clearedFields = 0;
  for (const pair of rows) {
    const hadValue = pair.some(inp => (inp.value || '').trim() !== '');
    if (!hadValue) continue;
    for (const inp of pair) {
      inp.focus();
      inp.value = '';
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      inp.dispatchEvent(new Event('change', {bubbles: true}));
      inp.blur();
      clearedFields += 1;
    }
    clearedRows += 1;
  }

  return {ok:true, rowsDetected:rows.length, clearedRows, clearedFields};
}
"""


async def clear_current_matchday_internal() -> dict[str, Any]:
    options = load_options()
    target_url = build_target_url(
        str(options.get("tipprunde", "")),
        str(options.get("kicktipp_url", "")),
    )
    username = str(options.get("username", ""))
    password = str(options.get("password", ""))
    started = int(time.time())

    async with AUTO_IMPORT_LOCK:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context_args: dict[str, Any] = {"viewport": {"width": 1440, "height": 1400}}
            if STATE_FILE.exists():
                context_args["storage_state"] = str(STATE_FILE)
            context = await browser.new_context(**context_args)
            page = await context.new_page()
            try:
                logged_in = await ensure_login(page, target_url, username, password)
                await context.storage_state(path=str(STATE_FILE))
                await page.wait_for_timeout(1000)
                result = await page.evaluate(CLEAR_TIPS_SCRIPT)
                cleared = int((result or {}).get("clearedRows") or 0)

                if cleared <= 0:
                    await page.screenshot(path=str(LAST_SCREENSHOT), full_page=True)
                    return {
                        "ok": True,
                        "saved": False,
                        "cleared_rows": 0,
                        "message": "Keine eingetragenen Tipps im aktuellen Spieltag gefunden.",
                        "logged_in_this_run": logged_in,
                    }

                save_status = await save_page(page)
                await page.wait_for_timeout(1800)
                await page.screenshot(path=str(LAST_SCREENSHOT), full_page=True)

                payload = {
                    "ok": True,
                    "saved": True,
                    "cleared_rows": cleared,
                    "cleared_fields": int((result or {}).get("clearedFields") or 0),
                    "save_status": save_status,
                    "logged_in_this_run": logged_in,
                    "timestamp": started,
                    "message": f"{cleared} Spiel-Tipps wurden geleert und gespeichert.",
                }
                LAST_LOG.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return payload
            finally:
                try:
                    await context.close()
                finally:
                    await browser.close()


def _public_options() -> dict[str, Any]:
    opts = load_options()
    # Never expose credentials in rendered HTML or the config endpoint.
    opts["password"] = ""
    configured = bool(str(opts.get("api_football_key") or "").strip())
    opts["api_football_key"] = ""
    opts["api_football_configured"] = configured
    return opts


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("__OPTIONS__", json.dumps(_public_options(), ensure_ascii=False))
    return html


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "app": "Kicktipp TipBot", "version": "0.1.42", "port": 8148}


@app.get("/api/config")
async def config() -> dict[str, Any]:
    opts = _public_options()
    opts["has_saved_session"] = STATE_FILE.exists()
    opts["port"] = 8148
    return opts


@app.post("/api/parse")
async def parse(req: ParseRequest) -> dict[str, Any]:
    tips = parse_tips(req.text)
    violations = [v for t in tips if (v := vfl_violation(t, req.vfl_team))]
    return {
        "count": len(tips),
        "violations": violations,
        "tips": [t.__dict__ for t in tips],
    }


@app.post("/api/run")
async def run(req: RunRequest) -> JSONResponse:
    options = load_options()
    tipprunde = req.tipprunde.strip() or options.get("tipprunde", "")
    kicktipp_url = req.kicktipp_url.strip() or options.get("kicktipp_url", "")
    username = req.username.strip() or options.get("username", "")
    password = req.password or options.get("password", "")
    vfl_team = req.vfl_team.strip() or options.get("vfl_team", "VfL Osnabrück")

    tips = parse_tips(req.text)
    if not tips:
        raise HTTPException(status_code=400, detail="Keine gültigen Tipps gefunden. Format: Team A – Team B: 2:1")
    violations = [v for t in tips if (v := vfl_violation(t, vfl_team))]
    if violations:
        raise HTTPException(status_code=400, detail="\n".join(violations))

    target_url = build_target_url(tipprunde, kicktipp_url)
    tip_payload = [t.__dict__ for t in tips]
    started = int(time.time())

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context_args: dict[str, Any] = {"viewport": {"width": 1440, "height": 1400}}
        if STATE_FILE.exists():
            context_args["storage_state"] = str(STATE_FILE)
        context = await browser.new_context(**context_args)
        page = await context.new_page()
        try:
            logged_in = await ensure_login(page, target_url, username, password)
            await context.storage_state(path=str(STATE_FILE))
            await page.wait_for_timeout(1000)
            results = await page.evaluate(FILL_SCRIPT, {"tips": tip_payload, "overwriteExisting": req.overwrite_existing})
            await page.wait_for_timeout(800)
            save_status = "Überprüfung: nicht gespeichert"
            if req.save:
                save_status = await save_page(page)
                await page.wait_for_timeout(1500)
            await page.screenshot(path=str(LAST_SCREENSHOT), full_page=True)
            payload = {
                "ok": True,
                "target_url": target_url,
                "saved": req.save,
                "save_status": save_status,
                "logged_in_this_run": logged_in,
                "results": results,
                "screenshot": "/api/screenshot?ts=" + str(started),
                "timestamp": started,
            }
            LAST_LOG.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return JSONResponse(payload)
        except PlaywrightTimeoutError as exc:
            await page.screenshot(path=str(LAST_SCREENSHOT), full_page=True)
            raise HTTPException(status_code=504, detail=f"Timeout bei Kicktipp: {exc}")
        except HTTPException:
            await page.screenshot(path=str(LAST_SCREENSHOT), full_page=True)
            raise
        except Exception as exc:
            await page.screenshot(path=str(LAST_SCREENSHOT), full_page=True)
            raise HTTPException(status_code=500, detail=f"Fehler beim Ausführen: {type(exc).__name__}: {exc}")
        finally:
            await context.close()
            await browser.close()


@app.get("/api/screenshot")
async def screenshot() -> Any:
    if not LAST_SCREENSHOT.exists():
        raise HTTPException(status_code=404, detail="Noch kein Screenshot vorhanden.")
    from fastapi.responses import FileResponse
    return FileResponse(str(LAST_SCREENSHOT), media_type="image/png")


@app.get("/api/last")
async def last() -> dict[str, Any]:
    if not LAST_LOG.exists():
        return {"ok": False, "message": "Noch kein Lauf vorhanden."}
    return json.loads(LAST_LOG.read_text(encoding="utf-8"))



@app.post("/api/clear-current-matchday")
async def clear_current_matchday() -> JSONResponse:
    try:
        return JSONResponse(await clear_current_matchday_internal())
    except HTTPException:
        raise
    except PlaywrightTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Timeout bei Kicktipp: {exc}")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Spieltag konnte nicht geleert werden: {type(exc).__name__}: {exc}",
        )

@app.post("/api/logout")
async def logout() -> dict[str, Any]:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"ok": True, "message": "Gespeicherte Kicktipp-Session gelöscht."}


def _write_auto_state(**updates: Any) -> None:
    state: dict[str, Any] = {}
    if AUTO_STATE_FILE.exists():
        try:
            state = json.loads(AUTO_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state.update(updates)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    AUTO_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_failed_drive_ids() -> set[str]:
    if not FAILED_DRIVE_IDS_FILE.exists():
        return set()
    try:
        data = json.loads(FAILED_DRIVE_IDS_FILE.read_text(encoding="utf-8"))
        return {str(x) for x in data if x}
    except Exception:
        return set()


def _write_failed_drive_ids(ids: set[str]) -> None:
    FAILED_DRIVE_IDS_FILE.write_text(
        json.dumps(sorted({str(x) for x in ids if x}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _add_failed_drive_id(file_id: str) -> None:
    ids = _read_failed_drive_ids()
    ids.add(str(file_id))
    _write_failed_drive_ids(ids)


def _remove_failed_drive_id(file_id: str) -> bool:
    file_id = str(file_id or "").strip()
    if not file_id:
        return False
    ids = _read_failed_drive_ids()
    existed = file_id in ids
    if existed:
        ids.discard(file_id)
        _write_failed_drive_ids(ids)
    return existed


def _read_processed_drive_ids() -> set[str]:
    if not PROCESSED_DRIVE_IDS_FILE.exists():
        return set()
    try:
        data = json.loads(PROCESSED_DRIVE_IDS_FILE.read_text(encoding="utf-8"))
        return {str(x) for x in data if x}
    except Exception:
        return set()


def _add_processed_drive_id(file_id: str) -> None:
    if not file_id:
        return
    ids = _read_processed_drive_ids()
    ids.add(str(file_id))
    # Begrenzen, damit die Datei dauerhaft klein bleibt.
    trimmed = sorted(ids)[-1000:]
    PROCESSED_DRIVE_IDS_FILE.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_processed_tip_hashes() -> dict[str, dict[str, Any]]:
    if not PROCESSED_TIP_HASHES_FILE.exists():
        return {}
    try:
        data = json.loads(PROCESSED_TIP_HASHES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if k and isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _write_processed_tip_hashes(data: dict[str, dict[str, Any]]) -> None:
    items = list(data.items())[-500:]
    PROCESSED_TIP_HASHES_FILE.write_text(
        json.dumps(dict(items), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _tip_fingerprint(tips_text: str, file_data: dict[str, Any]) -> str:
    parsed = parse_tips(tips_text)
    canonical = {
        "competition": str(file_data.get("competition") or "").strip().casefold(),
        "season": str(file_data.get("season") or "").strip(),
        "matchday": str(file_data.get("matchday") or "").strip(),
        "tips": [
            [normalize_team(t.home), normalize_team(t.away), int(t.home_goals), int(t.away_goals)]
            for t in parsed
        ],
    }
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _add_processed_tip_hash(fingerprint: str, *, file_id: str = "", file_data: dict[str, Any] | None = None) -> None:
    if not fingerprint:
        return
    data = _read_processed_tip_hashes()
    meta = file_data if isinstance(file_data, dict) else {}
    data[fingerprint] = {
        "drive_file_id": str(file_id or ""),
        "competition": str(meta.get("competition") or ""),
        "season": str(meta.get("season") or ""),
        "matchday": meta.get("matchday"),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_processed_tip_hashes(data)


def _drive_settings() -> dict[str, Any]:
    o = load_options()
    return {
        "enabled": bool(o.get("google_drive_import_enabled", True)),
        "folder_id": str(o.get("google_drive_folder_id", "")).strip(),
        "service_account_file": str(
            o.get(
                "google_drive_service_account_file",
                "/share/Kleinanzeigen/google-drive-service-account.json",
            )
        ).strip(),
        "poll_seconds": max(5, int(o.get("google_drive_poll_seconds", 5) or 5)),
        "media_dir": Path(str(o.get("media_import_dir", "/media/Import/Kicktippprimary"))),
    }


def _drive_session() -> AuthorizedSession:
    s = _drive_settings()
    key_file = Path(s["service_account_file"])
    if not key_file.exists():
        raise RuntimeError(f"Google-Service-Account-Datei fehlt: {key_file}")
    credentials = service_account.Credentials.from_service_account_file(
        str(key_file),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return AuthorizedSession(credentials)


def _drive_list_tip_files(session: AuthorizedSession) -> list[dict[str, Any]]:
    s = _drive_settings()
    if not s["folder_id"]:
        return []
    q = (
        f"'{s['folder_id']}' in parents and trashed = false "
        "and mimeType != 'application/vnd.google-apps.folder'"
    )
    response = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": q,
            "fields": "files(id,name,mimeType,size,modifiedTime,createdTime)",
            "orderBy": "createdTime",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=30,
    )
    response.raise_for_status()
    return [
        f for f in response.json().get("files", [])
        if str(f.get("name") or "").lower().endswith(".json")
    ]


def _safe_local_name(name: str) -> str:
    clean = Path(str(name or "kicktipp.json")).name
    clean = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", "_", clean).strip()
    if not clean.lower().endswith(".json"):
        clean += ".json"
    return clean or "kicktipp.json"


def _drive_download_to_media(session: AuthorizedSession, item: dict[str, Any]) -> Path:
    s = _drive_settings()
    media_dir: Path = s["media_dir"]
    media_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(item["id"])
    filename = _safe_local_name(str(item.get("name") or "kicktipp.json"))
    dest = media_dir / filename
    if dest.exists() or dest.with_name(dest.name + ".drive.json").exists():
        dest = media_dir / f"{dest.stem}_{file_id[:8]}{dest.suffix}"

    tmp = media_dir / f".{dest.name}.{file_id[:8]}.part"
    sidecar = dest.with_name(dest.name + ".drive.json")

    response = session.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        stream=True,
        timeout=60,
    )
    response.raise_for_status()

    with tmp.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)
        fh.flush()
        os.fsync(fh.fileno())

    sidecar.write_text(
        json.dumps(
            {
                "drive_file_id": file_id,
                "drive_name": item.get("name"),
                "drive_folder_id": s["folder_id"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, dest)
    return dest


def _cleanup_drive_source(session: AuthorizedSession, file_id: str) -> tuple[bool, str]:
    s = _drive_settings()
    try:
        r = session.delete(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"supportsAllDrives": "true"},
            timeout=30,
        )
        if r.status_code in (200, 204, 404):
            return True, "deleted"
    except Exception:
        pass

    try:
        r = session.patch(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={
                "removeParents": s["folder_id"],
                "supportsAllDrives": "true",
                "fields": "id,parents",
            },
            json={},
            timeout=30,
        )
        if r.status_code in (200, 201, 204):
            return True, "removed_from_folder"
        return False, f"Drive cleanup HTTP {r.status_code}: {r.text[:300]}"
    except Exception as exc:
        return False, str(exc)


def _ha_services() -> list[dict[str, Any]]:
    import urllib.request
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt")
    req = urllib.request.Request(
        "http://supervisor/core/api/services",
        headers={"Authorization": "Bearer " + token},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _notify_candidates() -> list[str]:
    options = load_options()
    configured = str(options.get("notify_service", "") or "").strip()
    services: list[str] = []
    for domain in _ha_services():
        if str(domain.get("domain") or "") != "notify":
            continue
        for name in (domain.get("services") or {}).keys():
            name = str(name)
            if name.startswith("mobile_app_"):
                services.append("notify." + name)

    result: list[str] = []
    if configured:
        if not configured.startswith("notify."):
            configured = "notify." + configured
        result.append(configured)

    def add(predicate):
        for s in services:
            if predicate(s.lower()) and s not in result:
                result.append(s)

    add(lambda s: "primary" in s and "iphone" in s)
    add(lambda s: "primary" in s)
    add(lambda s: "iphone" in s)
    for s in services:
        if s not in result:
            result.append(s)
    return result


def _send_critical_push(title: str, message: str, open_url: str = "", volume: float = 0.0) -> tuple[bool, str]:
    import urllib.request

    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return False, "SUPERVISOR_TOKEN fehlt"

    errors: list[str] = []
    for service in _notify_candidates():
        url = "http://supervisor/core/api/services/" + service.replace(".", "/")
        payload = json.dumps(
            {
                "title": title,
                "message": message,
                "data": {
                    **({"url": open_url, "clickAction": open_url} if open_url else {}),
                    "push": {
                        "interruption-level": "critical",
                        "sound": {
                            "name": "default",
                            "critical": 1,
                            "volume": max(0.0, min(1.0, float(volume))),
                        }
                    }
                },
            }
        ).encode("utf-8")
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
                if 200 <= resp.status < 300:
                    return True, f"{service} HTTP {resp.status}"
                errors.append(f"{service}: HTTP {resp.status}")
        except Exception as exc:
            errors.append(f"{service}: {exc}")

    return False, " | ".join(errors[-10:]) or "Kein Notify-Service verfügbar"


def _send_football_critical_push(title: str, message: str, open_url: str = "", volume: float = 0.0) -> tuple[bool, str]:
    target = str(open_url or load_options().get("football_push_url") or "").strip()
    return _send_critical_push(title, message, target, volume)


def _read_tip_file(path: Path) -> tuple[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Tippdatei muss ein JSON-Objekt enthalten.")

    fmt = str(data.get("format") or "").strip()
    if fmt and fmt != "kicktipp-primary":
        raise ValueError(f"Unbekanntes Dateiformat: {fmt}")

    tips_text = str(data.get("tips_text") or "").strip()
    if not tips_text and isinstance(data.get("tips"), list):
        lines = []
        for tip in data["tips"]:
            if not isinstance(tip, dict):
                continue
            home = str(tip.get("home") or "").strip()
            away = str(tip.get("away") or "").strip()
            hg = tip.get("home_goals")
            ag = tip.get("away_goals")
            if home and away and hg is not None and ag is not None:
                lines.append(f"{home} – {away}: {int(hg)}:{int(ag)}")
        tips_text = "\n".join(lines)

    if not tips_text:
        raise ValueError("Keine Tipps in tips_text oder tips gefunden.")
    return tips_text, data


async def _process_tip_file(path: Path) -> None:
    if not path.exists() or path.name.endswith(".drive.json"):
        return

    sidecar = path.with_name(path.name + ".drive.json")
    drive_meta: dict[str, Any] = {}
    if sidecar.exists():
        try:
            drive_meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            drive_meta = {}

    file_id = str(drive_meta.get("drive_file_id") or "")
    options = load_options()

    async with AUTO_IMPORT_LOCK:
        try:
            tips_text, file_data = _read_tip_file(path)
            fingerprint = _tip_fingerprint(tips_text, file_data)
            processed_hashes = _read_processed_tip_hashes()
            if fingerprint and fingerprint in processed_hashes:
                if file_id:
                    _add_processed_drive_id(file_id)
                cleanup_ok = True
                cleanup_mode = "local_only"
                cleanup_warning = ""
                if file_id:
                    try:
                        session = _drive_session()
                        cleanup_ok, cleanup_mode = _cleanup_drive_source(session, file_id)
                        if not cleanup_ok:
                            cleanup_warning = str(cleanup_mode)
                    except Exception as cleanup_exc:
                        cleanup_ok = False
                        cleanup_warning = str(cleanup_exc) or cleanup_exc.__class__.__name__
                        cleanup_mode = "cleanup_exception"
                _write_auto_state(
                    status="duplicate_skipped",
                    file=path.name,
                    drive_file_id=file_id,
                    tip_fingerprint=fingerprint,
                    cleanup_ok=cleanup_ok,
                    cleanup_mode=cleanup_mode,
                    cleanup_warning=cleanup_warning,
                    duplicate_of=processed_hashes.get(fingerprint, {}),
                )
                path.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
                return

            req = RunRequest(
                text=tips_text,
                tipprunde=str(options.get("tipprunde", "")),
                kicktipp_url=str(options.get("kicktipp_url", "")),
                username=str(options.get("username", "")),
                password="",
                vfl_team=str(options.get("vfl_team", "VfL Osnabrück")),
                save=True,
                overwrite_existing=True,
            )

            response = await run(req)
            payload = json.loads(response.body.decode("utf-8"))
            results = payload.get("results") or []
            bad = [r for r in results if str(r.get("status") or "") != "filled"]

            if not payload.get("saved") or bad:
                raise RuntimeError(
                    "Kicktipp-Übertragung nicht vollständig erfolgreich"
                    + (f": {bad}" if bad else "")
                )

            # Ab hier ist die entscheidende Aktion erfolgreich:
            # Kicktipp hat die Tipps gespeichert. Diese Drive-ID wird deshalb
            # sofort als verarbeitet markiert. Ein späteres Cleanup-Problem darf
            # niemals dieselben Tipps erneut übertragen oder einen falschen
            # "Tippübertragung fehlgeschlagen"-Push auslösen.
            if file_id:
                _add_processed_drive_id(file_id)
            _add_processed_tip_hash(fingerprint, file_id=file_id, file_data=file_data)

            cleanup_ok = True
            cleanup_mode = "local_only"
            cleanup_warning = ""
            if file_id:
                try:
                    session = _drive_session()
                    cleanup_ok, cleanup_mode = _cleanup_drive_source(session, file_id)
                    if not cleanup_ok:
                        cleanup_warning = str(cleanup_mode)
                        print(
                            f"[kicktipp-drive] Übertragung erfolgreich, "
                            f"Drive-Cleanup fehlgeschlagen: {cleanup_warning}",
                            flush=True,
                        )
                except Exception as cleanup_exc:
                    cleanup_ok = False
                    cleanup_warning = str(cleanup_exc) or cleanup_exc.__class__.__name__
                    cleanup_mode = "cleanup_exception"
                    print(
                        f"[kicktipp-drive] Übertragung erfolgreich, "
                        f"Drive-Cleanup Ausnahme: {cleanup_warning}",
                        flush=True,
                    )

            competition = str(file_data.get("competition") or "Kicktipp")
            matchday = file_data.get("matchday")
            suffix = f" – Spieltag {matchday}" if matchday not in (None, "") else ""
            notify_ok, notify_status = _send_critical_push(
                "Kicktipp Tipps übertragen",
                (
                    f"Neue Tipps wurden an {competition}{suffix} übertragen. "
                    "Bitte überprüfe und bearbeite gegebenenfalls die Tipps."
                ),
            )

            _write_auto_state(
                status="success",
                file=path.name,
                drive_file_id=file_id,
                cleanup_ok=cleanup_ok,
                cleanup_mode=cleanup_mode,
                cleanup_warning=cleanup_warning,
                notify_ok=notify_ok,
                notify_status=notify_status,
                result_count=len(results),
            )

            # Lokale Importdatei nach erfolgreicher Kicktipp-Übertragung immer
            # entfernen. Die persistierte Drive-ID verhindert Wiederholung,
            # selbst falls Google Drive temporär nicht bereinigt werden konnte.
            path.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)

        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            _write_auto_state(
                status="failed",
                file=path.name,
                drive_file_id=file_id,
                error=message,
            )
            if file_id:
                _add_failed_drive_id(file_id)

            try:
                failed_dir = Path(_drive_settings()["media_dir"]) / "Fehler"
                failed_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = failed_dir / f"{path.stem}_{stamp}{path.suffix}"
                shutil.move(str(path), str(target))
                if sidecar.exists():
                    shutil.move(
                        str(sidecar),
                        str(failed_dir / (target.name + ".drive.json")),
                    )
            except Exception:
                pass

            push_ok, push_status = _send_critical_push(
                "Kicktipp Übertragung fehlgeschlagen",
                (
                    "Die automatische Tippübertragung ist fehlgeschlagen. "
                    f"Bitte Kicktipp TipBot prüfen. Fehler: {message}"
                ),
            )
            _write_auto_state(
                status="failed",
                file=path.name,
                drive_file_id=file_id,
                error=message,
                notify_ok=push_ok,
                notify_status=push_status,
            )


async def _process_existing_media_files() -> None:
    media_dir = Path(_drive_settings()["media_dir"])
    media_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(media_dir.glob("*.json")):
        if not path.name.endswith(".drive.json"):
            await _process_tip_file(path)


async def _media_watch_loop() -> None:
    media_dir = Path(_drive_settings()["media_dir"])
    media_dir.mkdir(parents=True, exist_ok=True)
    await _process_existing_media_files()

    async for changes in awatch(str(media_dir), recursive=False):
        if any(
            Path(changed_path).parent == media_dir
            and Path(changed_path).suffix.lower() == ".json"
            and not Path(changed_path).name.endswith(".drive.json")
            for _change, changed_path in changes
        ):
            await _process_existing_media_files()


def _drive_sync_once_blocking() -> dict[str, Any]:
    settings = _drive_settings()
    if not settings["enabled"]:
        return {"enabled": False, "downloaded": 0}
    if not settings["folder_id"]:
        return {"enabled": True, "downloaded": 0, "error": "Drive folder id fehlt"}

    session = _drive_session()
    files = _drive_list_tip_files(session)
    failed_ids = _read_failed_drive_ids()
    processed_ids = _read_processed_drive_ids()
    media_dir: Path = settings["media_dir"]
    media_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for item in files:
        file_id = str(item.get("id") or "")
        if not file_id or file_id in failed_ids or file_id in processed_ids:
            continue

        already_local = False
        for sidecar in media_dir.glob("*.drive.json"):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                if str(meta.get("drive_file_id") or "") == file_id:
                    already_local = True
                    break
            except Exception:
                continue
        if already_local:
            continue

        _drive_download_to_media(session, item)
        downloaded += 1

    _write_auto_state(
        drive_last_check=datetime.now(timezone.utc).isoformat(),
        drive_found=len(files),
        drive_downloaded=downloaded,
        drive_error="",
    )
    return {"enabled": True, "found": len(files), "downloaded": downloaded}


async def _drive_poll_loop() -> None:
    while True:
        settings = _drive_settings()
        try:
            await asyncio.to_thread(_drive_sync_once_blocking)
        except Exception as exc:
            _write_auto_state(
                drive_error=str(exc) or exc.__class__.__name__,
                drive_error_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"[kicktipp-drive] {exc}", flush=True)
        await asyncio.sleep(max(5, int(settings["poll_seconds"])))


@app.get("/api/auto-status")
async def auto_status() -> dict[str, Any]:
    state: dict[str, Any] = {}
    if AUTO_STATE_FILE.exists():
        try:
            state = json.loads(AUTO_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    settings = _drive_settings()
    failed_ids = sorted(_read_failed_drive_ids())
    processed_ids = _read_processed_drive_ids()
    return {
        "ok": True,
        "state": state,
        "drive_enabled": settings["enabled"],
        "drive_folder_id": settings["folder_id"],
        "media_import_dir": str(settings["media_dir"]),
        "failed_drive_ids": failed_ids,
        "failed_count": len(failed_ids),
        "processed_count": len(processed_ids),
        "processed_tip_hash_count": len(_read_processed_tip_hashes()),
    }


@app.post("/api/auto-retry")
async def auto_retry(req: AutoRetryRequest) -> dict[str, Any]:
    failed_ids = _read_failed_drive_ids()
    processed_ids = _read_processed_drive_ids()

    file_id = str(req.file_id or "").strip()
    if not file_id:
        # Bevorzugt die zuletzt fehlgeschlagene Drive-ID aus dem Auto-State.
        if AUTO_STATE_FILE.exists():
            try:
                state = json.loads(AUTO_STATE_FILE.read_text(encoding="utf-8"))
                candidate = str(state.get("drive_file_id") or "").strip()
                if candidate in failed_ids:
                    file_id = candidate
            except Exception:
                pass
        if not file_id and failed_ids:
            file_id = sorted(failed_ids)[-1]

    if not file_id:
        raise HTTPException(status_code=404, detail="Keine fehlgeschlagene Drive-ID zum erneuten Versuch vorhanden.")
    if file_id in processed_ids:
        raise HTTPException(status_code=409, detail="Diese Drive-ID ist bereits erfolgreich verarbeitet und wird nicht erneut übertragen.")
    if file_id not in failed_ids:
        raise HTTPException(status_code=404, detail="Die angegebene Drive-ID steht nicht in der Fehlerliste.")

    # Prüfen, ob die Quelldatei im konfigurierten Drive-Ordner noch existiert.
    try:
        session = await asyncio.to_thread(_drive_session)
        files = await asyncio.to_thread(_drive_list_tip_files, session)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Drive konnte nicht geprüft werden: {exc}")

    source = next((item for item in files if str(item.get("id") or "") == file_id), None)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Die fehlgeschlagene Drive-Datei liegt nicht mehr im TipBot-Eingangsordner. Bitte neu hochladen.",
        )

    _remove_failed_drive_id(file_id)
    _write_auto_state(
        status="retry_queued",
        drive_file_id=file_id,
        file=str(source.get("name") or ""),
        error="",
        retry_requested_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        sync_result = await asyncio.to_thread(_drive_sync_once_blocking)
        # Nicht nur auf den Watcher warten: direkt vorhandene neue Importdateien verarbeiten.
        await _process_existing_media_files()
    except Exception as exc:
        # Falls der Retry schon vor der eigentlichen Verarbeitung scheitert, die ID wieder sperren.
        _add_failed_drive_id(file_id)
        _write_auto_state(
            status="failed",
            drive_file_id=file_id,
            file=str(source.get("name") or ""),
            error=str(exc) or exc.__class__.__name__,
        )
        raise HTTPException(status_code=500, detail=f"Erneuter Versuch fehlgeschlagen: {exc}")

    return {
        "ok": True,
        "message": "Erneuter Importversuch wurde gestartet.",
        "drive_file_id": file_id,
        "file": str(source.get("name") or ""),
        "sync": sync_result,
    }


@app.on_event("startup")
async def startup_background_import() -> None:
    settings = _drive_settings()
    Path(settings["media_dir"]).mkdir(parents=True, exist_ok=True)
    BACKGROUND_TASKS.append(asyncio.create_task(_media_watch_loop()))
    BACKGROUND_TASKS.append(asyncio.create_task(_drive_poll_loop()))
    BACKGROUND_TASKS.append(asyncio.create_task(_table_push_monitor_loop()))
    BACKGROUND_TASKS.append(asyncio.create_task(_football_push_monitor_loop()))


@app.on_event("shutdown")
async def shutdown_background_import() -> None:
    for task in BACKGROUND_TASKS:
        task.cancel()
    for task in BACKGROUND_TASKS:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    BACKGROUND_TASKS.clear()

TABLE_EXTRACT_SCRIPT = r"""
() => {
  const clean = (value) => (value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const directCells = (row) => Array.from(row.querySelectorAll(':scope > th, :scope > td'));
  const getCells = (row) => directCells(row)
    .map((cell) => clean(cell.innerText || cell.textContent || ''));
  const getCellMeta = (row) => directCells(row).map((cell) => {
    const nodes = [cell, ...Array.from(cell.querySelectorAll('*'))];
    const colors = nodes.map((node) => {
      try { return getComputedStyle(node).color || ''; } catch (_) { return ''; }
    }).filter(Boolean);
    const classText = nodes.map((node) => String(node.className || '')).join(' ');
    const styleText = nodes.map((node) => String(node.getAttribute?.('style') || '')).join(' ');
    const markerText = `${classText} ${styleText}`.toLowerCase();
    const redish = colors.some((color) => {
      const m = String(color).match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
      if (!m) return false;
      const r = Number(m[1]), g = Number(m[2]), b = Number(m[3]);
      return r >= 145 && r >= g * 1.35 && r >= b * 1.25;
    });
    return {
      colors,
      classText,
      styleText,
      liveMarker: redish || /(?:^|[-_\s])(live|liveticker|zwischenstand|danger|text-danger|red)(?:$|[-_\s])/.test(markerText)
    };
  });

  const tables = Array.from(document.querySelectorAll('table')).map((table, tableIndex) => {
    let headers = [];
    const headRows = Array.from(table.querySelectorAll('thead tr'));
    if (headRows.length) {
      headers = getCells(headRows[headRows.length - 1]);
    }

    let rowNodes = Array.from(table.querySelectorAll('tbody tr'));
    if (!rowNodes.length) {
      rowNodes = Array.from(table.querySelectorAll('tr'));
      if (!headers.length && rowNodes.length) {
        headers = getCells(rowNodes[0]);
        rowNodes = rowNodes.slice(1);
      }
    }

    const rowEntries = rowNodes
      .map((row) => ({
        cells: getCells(row),
        meta: getCellMeta(row),
        flags: {
          classText: String(row.className || ''),
          ariaCurrent: String(row.getAttribute('aria-current') || ''),
          dataUser: String(row.getAttribute('data-user') || row.getAttribute('data-username') || ''),
        }
      }))
      .filter((entry) => entry.cells.some(Boolean));
    const rows = rowEntries.map((entry) => entry.cells);
    const rowMeta = rowEntries.map((entry) => entry.meta);
    const rowFlags = rowEntries.map((entry) => entry.flags);
    return {tableIndex, headers, rows, rowMeta, rowFlags};
  });

  const headings = Array.from(document.querySelectorAll('h1,h2,h3,.panel-heading,.page-header'))
    .map((el) => clean(el.innerText || el.textContent || ''))
    .filter(Boolean)
    .slice(0, 30);
  const selfCandidates = Array.from(document.querySelectorAll(
    'a[href*="profil"],a[href*="profile"],a[href*="teilnehmer"],.dropdown-toggle,.navbar .user,.navbar .username'
  )).map((el) => clean(el.innerText || el.textContent || '')).filter(Boolean).slice(0, 30);

  return {
    title: document.title || '',
    url: location.href,
    headings,
    selfCandidates,
    tables
  };
}
"""


def _norm_header(value: str) -> str:
    value = str(value or "").strip().lower()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9+/-]+", "", value)
    return value


def _header_index(headers: list[str], exact: tuple[str, ...] = (), contains: tuple[str, ...] = ()) -> Optional[int]:
    normalized = [_norm_header(h) for h in headers]
    for wanted in exact:
        try:
            return normalized.index(wanted)
        except ValueError:
            pass
    for idx, value in enumerate(normalized):
        if any(token in value for token in contains):
            return idx
    return None


def _parse_kicktipp_datetime(text: str) -> Optional[datetime]:
    text = str(text or "").strip()
    if not text:
        return None
    match = re.search(r"(\d{1,2}\.\d{1,2}\.(?:\d{2}|\d{4}))\s+(\d{1,2}:\d{2})", text)
    if not match:
        return None
    raw = f"{match.group(1)} {match.group(2)}"
    for fmt in ("%d.%m.%y %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=BERLIN_TZ)
        except ValueError:
            continue
    return None


def _matchday_label(raw: dict[str, Any]) -> str:
    candidates = [str(x) for x in (raw.get("headings") or [])] + [str(raw.get("title") or "")]
    for text in candidates:
        match = re.search(r"Tippübersicht\s*[•\-:]\s*([^•|\n]+)", text, re.I)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    for text in candidates:
        match = re.search(r"(\d+\.\s*Spieltag|Halbfinale|Viertelfinale|Achtelfinale|Finale|Relegation|Bonus)", text, re.I)
        if match:
            return match.group(1).strip()
    return "Aktueller Spieltag"


def _extract_ranking(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    best: Optional[tuple[int, dict[str, Any]]] = None
    for table in raw.get("tables") or []:
        headers = [str(x) for x in table.get("headers") or []]
        norms = [_norm_header(x) for x in headers]
        score = 0
        if any(x in norms for x in ("pos", "platz", "rang")):
            score += 5
        if "name" in norms:
            score += 5
        if "g" in norms:
            score += 6
        if any("gesamt" in x for x in norms):
            score += 4
        if any(x in norms for x in ("termin", "heim", "gast")):
            score -= 8
        score += min(len(table.get("rows") or []), 25) // 5
        if best is None or score > best[0]:
            best = (score, table)

    if not best or best[0] < 8:
        raise RuntimeError("Kicktipp-Ranglistentabelle wurde nicht gefunden.")

    table = best[1]
    headers = [str(x) for x in table.get("headers") or []]
    pos_idx = _header_index(headers, exact=("pos", "platz", "rang"))
    name_idx = _header_index(headers, exact=("name",))
    total_idx = _header_index(headers, exact=("g",), contains=("gesamt", "gesamtpunkte", "punkte", "pkte"))
    day_idx = _header_index(headers, exact=("p",))
    bonus_idx = _header_index(headers, exact=("b",))
    wins_idx = _header_index(headers, exact=("s",), contains=("spieltagsiege", "siege"))
    movement_idx = _header_index(headers, exact=("+/-", "+-"), contains=("differenz",))

    if pos_idx is None or name_idx is None or total_idx is None:
        raise RuntimeError(f"Kicktipp-Rangliste hat unerwartete Spalten: {headers}")

    ranking: list[dict[str, Any]] = []
    row_flags = table.get("rowFlags") if isinstance(table.get("rowFlags"), list) else []
    for row_index, cells in enumerate(table.get("rows") or []):
        cells = [str(x).strip() for x in cells]
        if max(pos_idx, name_idx, total_idx) >= len(cells):
            continue
        pos_match = re.search(r"\d+", cells[pos_idx])
        name = cells[name_idx].strip()
        if not pos_match or not name:
            continue
        # Kicktipp uses generic classes/aria markers on multiple rows. They are
        # not a reliable identity signal, so own-row marking is resolved later
        # exclusively against the configured table_user_name.
        is_me_hint = False
        ranking.append({
            "position": int(pos_match.group(0)),
            "name": name,
            "is_me_hint": is_me_hint,
            "points": cells[total_idx].strip(),
            "matchday_points": cells[day_idx].strip() if day_idx is not None and day_idx < len(cells) else "",
            "bonus_points": cells[bonus_idx].strip() if bonus_idx is not None and bonus_idx < len(cells) else "",
            "wins": cells[wins_idx].strip() if wins_idx is not None and wins_idx < len(cells) else "",
            "movement": cells[movement_idx].strip() if movement_idx is not None and movement_idx < len(cells) else "",
        })

    if not ranking:
        raise RuntimeError("Kicktipp-Rangliste ist leer oder konnte nicht gelesen werden.")
    return ranking, headers


def _extract_schedule(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    best: Optional[tuple[int, dict[str, Any]]] = None
    for table in raw.get("tables") or []:
        headers = [str(x) for x in table.get("headers") or []]
        norms = [_norm_header(x) for x in headers]
        score = 0
        if "termin" in norms:
            score += 5
        if "heim" in norms:
            score += 5
        if "gast" in norms:
            score += 5
        if "ergebnis" in norms:
            score += 5
        if "name" in norms and any(x in norms for x in ("pos", "platz", "rang")):
            score -= 8
        if best is None or score > best[0]:
            best = (score, table)

    if not best or best[0] < 15:
        return [], []

    table = best[1]
    headers = [str(x) for x in table.get("headers") or []]
    term_idx = _header_index(headers, exact=("termin",), contains=("termin", "datum"))
    home_idx = _header_index(headers, exact=("heim",), contains=("heim",))
    away_idx = _header_index(headers, exact=("gast",), contains=("gast", "auswaerts"))
    result_idx = _header_index(headers, exact=("ergebnis",), contains=("ergebnis",))
    if None in (term_idx, home_idx, away_idx, result_idx):
        return [], headers

    matches: list[dict[str, Any]] = []
    previous_term = ""
    row_meta = table.get("rowMeta") or []
    for row_index, cells in enumerate(table.get("rows") or []):
        cells = [str(x).strip() for x in cells]
        if max(term_idx, home_idx, away_idx, result_idx) >= len(cells):
            continue
        term = cells[term_idx].strip() or previous_term
        if cells[term_idx].strip():
            previous_term = cells[term_idx].strip()
        home = cells[home_idx].strip()
        away = cells[away_idx].strip()
        result = cells[result_idx].strip()
        if not home or not away:
            continue
        kickoff = _parse_kicktipp_datetime(term)
        result_match = re.search(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", result)
        result_meta: dict[str, Any] = {}
        if row_index < len(row_meta) and isinstance(row_meta[row_index], list) and result_idx < len(row_meta[row_index]):
            candidate_meta = row_meta[row_index][result_idx]
            if isinstance(candidate_meta, dict):
                result_meta = candidate_meta
        live_result = bool(result_meta.get("liveMarker"))
        matches.append({
            "term": term,
            "kickoff": kickoff.isoformat() if kickoff else "",
            "home": home,
            "away": away,
            "result": result,
            # Kicktipp zeigt ab Anpfiff Live-Zwischenstände in der Tippübersicht.
            # Ein vorhandenes 0:0/1:0/... bedeutet daher NICHT automatisch Abpfiff.
            "score_detected": bool(result_match),
            "live_result": live_result,
            "result_meta": result_meta,
            "finished": False,
        })
    return matches, headers


def _build_blocks(matches: list[dict[str, Any]], matchday: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        kickoff = str(match.get("kickoff") or "")
        if not kickoff:
            continue
        grouped.setdefault(kickoff, []).append(match)

    blocks: list[dict[str, Any]] = []
    for kickoff, games in sorted(grouped.items()):
        teams = "|".join(sorted(f"{g.get('home')}--{g.get('away')}" for g in games))
        key = f"{matchday}|{kickoff}|{teams}"
        try:
            kickoff_dt = datetime.fromisoformat(kickoff).astimezone(BERLIN_TZ)
            now_local = datetime.now(BERLIN_TZ)
            kickoff_passed = now_local >= kickoff_dt
            elapsed_minutes = max(0.0, (now_local - kickoff_dt).total_seconds() / 60.0)
        except Exception:
            kickoff_passed = False
            elapsed_minutes = 0.0

        # Kicktipp kennzeichnet Live-Zwischenstände in der Tippübersicht rot.
        # Endergebnisse erscheinen schwarz. Genau diese Statusinformation ist die
        # Quelle der Wahrheit: KEIN künstliches Zeitfenster mehr. Ein Spiel gilt
        # erst dann als beendet, wenn nach dem Anpfiff ein Ergebnis vorhanden ist
        # und Kicktipp dieses Ergebnis nicht mehr als Live (rot) markiert.
        # Dadurch kommt der Tabellen-Push unmittelbar nach dem tatsächlichen Ende
        # des kompletten Anstoßblocks, unabhängig von Nachspielzeit/Verlängerungen.
        for game in games:
            game["finished"] = bool(
                kickoff_passed
                and game.get("score_detected")
                and not game.get("live_result")
            )

        blocks.append({
            "key": key,
            "matchday": matchday,
            "kickoff": kickoff,
            "elapsed_minutes": round(elapsed_minutes, 1),
            "has_live_result": any(bool(g.get("live_result")) for g in games),
            "complete": bool(games) and all(bool(g.get("finished")) for g in games),
            "games": games,
        })
    return blocks


def _tipprunde_base_url(tipprunde: str, kicktipp_url: str) -> str:
    name = str(tipprunde or "").strip().strip("/")
    if name:
        return f"https://www.kicktipp.de/{name}"

    url = str(kicktipp_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Bitte Tipprunde oder direkte Kicktipp-URL in der App-Konfiguration hinterlegen.")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if not parts.netloc or not segments:
        raise HTTPException(status_code=400, detail="Kicktipp-URL konnte nicht der Tipprunde zugeordnet werden.")
    return f"{parts.scheme or 'https'}://{parts.netloc}/{segments[0]}"


async def _fetch_table_snapshot() -> dict[str, Any]:
    options = load_options()
    base = _tipprunde_base_url(str(options.get("tipprunde", "")), str(options.get("kicktipp_url", "")))
    target_url = base.rstrip("/") + "/tippuebersicht"
    username = str(options.get("username", "") or "").strip()
    password = str(options.get("password", "") or "")

    async with TABLE_BROWSER_LOCK:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context_args: dict[str, Any] = {"viewport": {"width": 1440, "height": 1600}}
            if STATE_FILE.exists():
                context_args["storage_state"] = str(STATE_FILE)
            context = await browser.new_context(**context_args)
            page = await context.new_page()
            try:
                logged_in = await ensure_login(page, target_url, username, password)
                await context.storage_state(path=str(STATE_FILE))
                await page.wait_for_timeout(1200)
                raw = await page.evaluate(TABLE_EXTRACT_SCRIPT)
            finally:
                try:
                    await context.close()
                finally:
                    await browser.close()

    ranking, ranking_headers = _extract_ranking(raw)
    # Mark exactly one own row from the explicit table_user_name. Navigation
    # candidates are intentionally ignored because Kicktipp can expose generic
    # participant links that caused every row to be treated as "Du".
    configured_name = _configured_user_name(options)
    exact_matches = [
        row for row in ranking
        if _name_matches_user(str(row.get("name") or ""), configured_name)
    ]
    for row in ranking:
        row["is_me_hint"] = bool(len(exact_matches) == 1 and row is exact_matches[0])
    matches, schedule_headers = _extract_schedule(raw)
    matchday = _matchday_label(raw)
    blocks = _build_blocks(matches, matchday)
    return {
        "ok": True,
        "tipprunde": base.rstrip("/").split("/")[-1],
        "matchday": matchday,
        "source_url": target_url,
        "logged_in_this_run": logged_in,
        "updated_at": datetime.now(BERLIN_TZ).isoformat(),
        "ranking_headers": ranking_headers,
        "ranking": ranking,
        "schedule_headers": schedule_headers,
        "matches": matches,
        "blocks": blocks,
    }


def _configured_user_name(options: Optional[dict[str, Any]] = None) -> str:
    opts = options or load_options()
    # The Kicktipp login can be an e-mail address and therefore is not a reliable
    # display-name identifier for the ranking. Keep the table identity separate.
    raw = str(opts.get("table_user_name") or "").strip()
    if raw:
        return raw
    login = str(opts.get("username") or "").strip()
    if login and "@" not in login:
        return login
    return "primary"


def _normalize_person_name(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _name_matches_user(name: str, username: str) -> bool:
    # The configured table_user_name is the authoritative identity.  Do not use
    # prefix matching here: it can accidentally mark a different participant.
    left = _normalize_person_name(name)
    right = _normalize_person_name(username)
    return bool(left and right and left == right)


def _parse_number(value: Any) -> float:
    # State snapshots already contain real numbers. Converting 26.0 to text and
    # stripping the dot used to turn it into 260, which caused values such as
    # 26 - 260 = -234 points in the table push.
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return 0.0
    raw = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return 0.0
    if "," in raw and "." in raw:
        # German display format such as 1.234,5.
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", raw):
        # Unambiguous thousands separators. A single 26.0 stays decimal.
        raw = raw.replace(".", "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except Exception:
        return 0.0


def _ranking_snapshot_map(ranking: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    snap: dict[str, dict[str, Any]] = {}
    for row in ranking:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        snap[_normalize_person_name(name)] = {
            "position": int(row.get("position") or 0),
            "points": _parse_number(row.get("points")),
            "matchday_points": _parse_number(row.get("matchday_points")),
            "wins": _parse_number(row.get("wins")),
            "name": name,
        }
    return snap


def _format_signed_int(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def _format_compact_points(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}".replace(".", ",")


def _table_user_summary(
    snapshot: dict[str, Any],
    previous_ranking: Optional[dict[str, Any]] = None,
    username: Optional[str] = None,
) -> dict[str, Any]:
    ranking = list(snapshot.get("ranking") or [])
    user = (username or _configured_user_name()).strip()
    matches = [row for row in ranking if _name_matches_user(str(row.get("name") or ""), user)]
    current_row: Optional[dict[str, Any]] = matches[0] if len(matches) == 1 else None
    if current_row is None:
        return {
            "available": False,
            "username": user,
            "title": "Tabelle aktualisiert",
            "short": "Tabelle aktualisiert",
            "detail": "Eigene Tabellenzeile wurde nicht eindeutig gefunden.",
            "points_delta": 0,
            "place_delta": 0,
            "current_position": None,
            "current_points": None,
        }

    current_position = int(current_row.get("position") or 0)
    current_points = _parse_number(current_row.get("points"))
    raw_day_points = current_row.get("matchday_points")
    current_day_points = _parse_number(raw_day_points)
    day_points_available = str(raw_day_points if raw_day_points is not None else "").strip() != ""
    previous_row = None
    if isinstance(previous_ranking, dict):
        previous_row = previous_ranking.get(_normalize_person_name(str(current_row.get("name") or user)))

    comparison_available = isinstance(previous_row, dict)
    previous_position = int(previous_row.get("position") or 0) if comparison_available else 0
    previous_points = _parse_number(previous_row.get("points")) if comparison_available else current_points

    # Spieltagspunkte stammen direkt aus der Kicktipp-Spalte "Spieltag". Der
    # vorherige Code verglich nur den Gesamtpunktestand mit dem letzten Poll und
    # zeigte deshalb nach einem abgeschlossenen Block oft 0 Punkte, obwohl am
    # Spieltag bereits Punkte erzielt wurden.
    if day_points_available:
        points_delta = int(round(current_day_points))
        points_source = "matchday"
    elif comparison_available:
        points_delta = int(round(current_points - previous_points))
        points_source = "ranking_delta"
    else:
        points_delta = 0
        points_source = "unavailable"

    # Die Platzveränderung wird gegen den zu Beginn des Spieltags gespeicherten
    # Tabellenstand berechnet, nicht gegen den unmittelbar vorherigen Poll.
    place_delta = int(previous_position - current_position) if comparison_available and previous_position else 0

    points_text = f"+{_format_compact_points(points_delta)}" if points_delta > 0 else _format_compact_points(points_delta)
    if place_delta > 0:
        place_text = f"↑ {place_delta} Plätze"
        place_short = f"+{place_delta} Plätze"
    elif place_delta < 0:
        place_text = f"↓ {abs(place_delta)} Plätze"
        place_short = f"-{abs(place_delta)} Plätze"
    else:
        place_text = "↔ Platz gehalten"
        place_short = "±0 Plätze"

    if points_delta > 0:
        points_detail = f"+{_format_compact_points(points_delta)} Punkte"
    elif points_delta < 0:
        points_detail = f"{_format_compact_points(points_delta)} Punkte"
    else:
        points_detail = "±0 Punkte"

    if not comparison_available:
        place_text = "Noch kein Vergleich"
        place_short = "kein Vergleich"

    if comparison_available:
        short = f"⚽ {points_detail} · 📈 {place_short}"
        detail = (
            f"{points_detail} an diesem Spieltag · {place_text} seit Spieltagstart · "
            f"jetzt Platz {current_position} mit {_format_compact_points(current_points)} Gesamtpunkten"
        )
    else:
        short = f"⚽ {points_detail} · 🏁 Platz {current_position}"
        detail = (
            f"{points_detail} an diesem Spieltag · noch kein Startplatz zum Vergleichen · "
            f"aktuell Platz {current_position} mit {_format_compact_points(current_points)} Gesamtpunkten"
        )
    title = short

    return {
        "available": True,
        "username": str(current_row.get("name") or user),
        "title": title,
        "short": short,
        "detail": detail,
        "points_delta": points_delta,
        "points_delta_text": points_detail,
        "place_delta": place_delta,
        "place_delta_text": place_text,
        "current_position": current_position,
        "current_points": current_points,
        "current_day_points": current_day_points,
        "points_source": points_source,
        "comparison_available": comparison_available,
    }


def _format_table_push_title(
    snapshot: dict[str, Any],
    test: bool = False,
    summary: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    matchday = str(snapshot.get("matchday") or "Aktueller Spieltag")
    prefix = "TEST · " if test else ""
    data = summary or {}
    if data.get("available"):
        points = str(data.get("points_delta_text") or "±0 Punkte").replace(" Punkte", " Pkt.")
        place_delta = int(data.get("place_delta") or 0)
        if data.get("comparison_available"):
            if place_delta > 0:
                place = f"↑{place_delta} Plätze"
            elif place_delta < 0:
                place = f"↓{abs(place_delta)} Plätze"
            else:
                place = "↔ Platz"
            body = f"⚽ {points} · {place} · 🏁 Platz {data.get('current_position') or '–'}"
        else:
            body = f"⚽ {points} · 🏁 Platz {data.get('current_position') or '–'}"
    else:
        body = "Tabelle aktualisiert"
    return f"{prefix}Kicktipp · {matchday}", body


def _display_updated_at(snapshot: dict[str, Any]) -> str:
    raw = str(snapshot.get("updated_at") or "")
    try:
        value = datetime.fromisoformat(raw).astimezone(BERLIN_TZ)
    except Exception:
        value = datetime.now(BERLIN_TZ)
    return value.strftime("%d.%m.%Y, %H:%M")


def _standings_card_html(
    snapshot: dict[str, Any],
    block: Optional[dict[str, Any]] = None,
    test: bool = False,
    previous_ranking: Optional[dict[str, Any]] = None,
) -> str:
    ranking = list(snapshot.get("ranking") or [])
    options = load_options()
    user_name = _configured_user_name(options)
    summary = _table_user_summary(snapshot, previous_ranking=previous_ranking, username=user_name)
    matchday = html.escape(str(snapshot.get("matchday") or "Aktueller Spieltag"))
    tipprunde = html.escape(str(snapshot.get("tipprunde") or "Kicktipp").upper())
    updated = html.escape(_display_updated_at(snapshot))

    if test:
        banner = "Tabellen-Test-Push · aktuelle vollständige Tabelle."
    elif block:
        banner = "Alle Spiele dieses Anstoßblocks sind beendet."
    else:
        banner = "Aktuelle vollständige Tipprunden-Tabelle."

    rows: list[str] = []
    for row in ranking:
        position = str(row.get("position") or "")
        name_raw = str(row.get("name") or "").strip()
        name = html.escape(name_raw)
        points = html.escape(str(row.get("points") or ""))
        day_points = html.escape(str(row.get("matchday_points") or ""))
        is_me = _name_matches_user(name_raw, user_name)
        row_class = "me" if is_me else ""
        shown_name = name

        if position == "1":
            place_markup = '<span class="medal gold">1</span>'
        elif position == "2":
            place_markup = '<span class="medal silver">2</span>'
        elif position == "3":
            place_markup = '<span class="medal bronze">3</span>'
        else:
            place_markup = f'<span class="place-number">{html.escape(position)}</span>'

        marker = '<span class="me-marker">▶</span>' if is_me else '<span class="me-marker empty">▶</span>'
        rows.append(
            f'<tr class="{row_class}">'
            f'<td class="place-cell">{marker}{place_markup}</td>'
            f'<td class="name-cell">{shown_name}</td>'
            f'<td class="day-cell">{day_points}</td>'
            f'<td class="points-cell">{points}</td>'
            '</tr>'
        )

    summary_html = ''
    if summary.get("available"):
        if summary.get("comparison_available"):
            points_label = html.escape(str(summary.get("points_delta_text") or "±0 Punkte"))
            place_label = html.escape(str(summary.get("place_delta_text") or "↔ Platz gehalten"))
        else:
            points_label = "Noch kein Vergleich"
            place_label = "Noch kein Vergleich"
        current_position = html.escape(str(summary.get("current_position") or "–"))
        current_points = html.escape(_format_compact_points(float(summary.get("current_points") or 0)))
        summary_html = (
            f'<div class="summary-strip">'
            f'<div class="summary-kpi"><span class="kpi-icon">⚽</span><span><strong>{points_label}</strong><small>Spieltagspunkte</small></span></div>'
            f'<div class="summary-kpi"><span class="kpi-icon">📈</span><span><strong>{place_label}</strong><small>seit Spieltagstart</small></span></div>'
            f'<div class="summary-kpi"><span class="kpi-icon">🏁</span><span><strong>Platz {current_position}</strong><small>{current_points} Gesamtpunkte</small></span></div>'
            f'</div>'
        )

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #06111f; }}
  body {{ font-family: Arial, "Liberation Sans", sans-serif; color: #f5f8fc; }}
  #card {{
    width: 1100px;
    padding: 38px;
    background: linear-gradient(145deg, #06101d 0%, #071a2f 55%, #06111f 100%);
    border: 2px solid rgba(255,255,255,.16);
    border-radius: 30px;
  }}
  .header {{ display: flex; align-items: center; gap: 22px; }}
  .ball {{
    width: 84px; height: 84px; border-radius: 50%; background: #f6f6f6; color: #08111d;
    display: grid; place-items: center; font-size: 52px; box-shadow: 0 4px 18px rgba(0,0,0,.35);
  }}
  .title {{ font-size: 44px; font-weight: 800; letter-spacing: .4px; }}
  .meta {{ margin: 12px 0 0 106px; font-size: 29px; color: #c7d1df; }}
  .summary-strip {{
    margin-top: 26px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px;
  }}
  .summary-kpi {{
    min-height: 94px; padding: 16px 18px; border-radius: 22px; display: flex; align-items: center; gap: 16px;
    background: linear-gradient(180deg, rgba(12,44,76,.96), rgba(10,31,55,.96));
    border: 1px solid rgba(68,166,255,.35); box-shadow: inset 0 0 0 1px rgba(255,255,255,.03);
  }}
  .kpi-icon {{
    flex: 0 0 auto; width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center;
    background: rgba(36,169,255,.18); color: #48b7ff; font-size: 27px;
  }}
  .summary-kpi strong {{ display: block; font-size: 27px; line-height: 1.15; }}
  .summary-kpi small {{ display: block; margin-top: 4px; font-size: 18px; color: #b7c6d9; }}
  .banner {{
    margin-top: 24px; min-height: 78px; display: flex; align-items: center; gap: 18px;
    padding: 15px 24px; border-radius: 24px; background: linear-gradient(90deg,#0e6037,#145f39);
    border: 1px solid rgba(94,240,149,.55); font-size: 28px; font-weight: 700;
  }}
  .check {{
    flex: 0 0 auto; width: 48px; height: 48px; border-radius: 50%; display: grid; place-items: center;
    background: #43df78; color: #063418; font-size: 30px; font-weight: 900;
  }}
  .table-wrap {{ margin-top: 28px; border: 1px solid rgba(255,255,255,.09); border-radius: 20px; overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  thead {{ background: rgba(8,25,44,.92); }}
  th {{ color: #aebbd0; font-size: 23px; font-weight: 800; text-align: left; padding: 19px 18px; letter-spacing: .4px; }}
  th:nth-child(1) {{ width: 170px; }}
  th:nth-child(3) {{ width: 195px; text-align: center; }}
  th:nth-child(4) {{ width: 190px; text-align: center; }}
  td {{ border-top: 1px solid rgba(255,255,255,.10); padding: 14px 18px; font-size: 27px; height: 72px; }}
  .place-cell {{ display: flex; align-items: center; gap: 10px; }}
  .name-cell {{ font-weight: 600; }}
  .points-cell, .day-cell {{ text-align: center; font-weight: 800; }}
  .me td {{
    background: linear-gradient(90deg, rgba(0,126,214,.96), rgba(0,157,255,.88));
    color: #ffffff;
    border-top: 2px solid #65c8ff;
    border-bottom: 2px solid #65c8ff;
  }}
  .me td:first-child {{ box-shadow: inset 3px 0 0 #b8e8ff; }}
  .me td:last-child {{ box-shadow: inset -3px 0 0 #b8e8ff; }}
  .me-marker {{ width: 24px; color: #ffffff; font-size: 22px; }}
  .me-marker.empty {{ visibility: hidden; }}
  .place-number {{ min-width: 46px; text-align: center; font-size: 29px; }}
  .medal {{
    width: 54px; height: 54px; border-radius: 50%; display: grid; place-items: center;
    color: #121212; font-size: 27px; font-weight: 900; border: 3px solid rgba(255,255,255,.45);
    box-shadow: 0 3px 10px rgba(0,0,0,.25);
  }}
  .gold {{ background: #f7c73b; }}
  .silver {{ background: #d9dce2; }}
  .bronze {{ background: #d77a3d; }}
  .footer {{
    margin-top: 24px; padding: 18px 24px; border-radius: 18px; background: rgba(16,38,63,.78);
    border: 1px solid rgba(255,255,255,.10); color: #cbd5e2; font-size: 23px;
    display: flex; align-items: center; justify-content: space-between; gap: 20px;
  }}
  .footer strong {{ color: #f2f6fb; }}
</style>
</head>
<body>
<div id="card">
  <div class="header">
    <div class="ball">⚽</div>
    <div class="title">KICKTIPP · {tipprunde}</div>
  </div>
  <div class="meta">▣ {matchday} &nbsp;&nbsp;|&nbsp;&nbsp; ◷ Stand: {updated}</div>
  {summary_html}
  <div class="banner"><span class="check">✓</span><span>{html.escape(banner)}</span></div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>PLATZ</th><th>NAME</th><th>SPIELTAG</th><th>GESAMT</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
  <div class="footer"><span>📊 Nächster Tabellen-Push nach dem nächsten abgeschlossenen Spielblock.</span><strong>🏆</strong></div>
</div>
</body>
</html>"""

async def _render_table_push_image(
    snapshot: dict[str, Any],
    block: Optional[dict[str, Any]] = None,
    test: bool = False,
    previous_ranking: Optional[dict[str, Any]] = None,
) -> tuple[Path, str]:
    ranking = list(snapshot.get("ranking") or [])
    if not ranking:
        raise RuntimeError("Keine Ranglistendaten für das Push-Bild vorhanden.")

    TABLE_PUSH_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(BERLIN_TZ).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"table_{stamp}.png"
    target = TABLE_PUSH_IMAGE_DIR / filename
    markup = _standings_card_html(snapshot, block=block, test=test, previous_ranking=previous_ranking)
    viewport_height = min(32000, max(1200, 430 + len(ranking) * 84))

    async with TABLE_BROWSER_LOCK:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = await browser.new_page(viewport={"width": 1180, "height": viewport_height}, device_scale_factor=1)
            try:
                await page.set_content(markup, wait_until="load")
                await page.locator("#card").screenshot(path=str(target), type="png")
            finally:
                await browser.close()

    try:
        files = sorted(TABLE_PUSH_IMAGE_DIR.glob("table_*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in files[8:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass

    if str(target).startswith("/config/www/"):
        relative = target.relative_to("/config/www").as_posix()
        image_url = "/local/" + relative
    else:
        image_url = ""
    return target, image_url


def _send_table_image_push(title: str, message: str, image_url: str) -> tuple[bool, str]:
    import urllib.request

    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return False, "SUPERVISOR_TOKEN fehlt"
    if not image_url:
        return False, "Push-Bild liegt nicht unter /config/www und kann nicht über /local bereitgestellt werden"

    errors: list[str] = []
    for service in _notify_candidates():
        url = "http://supervisor/core/api/services/" + service.replace(".", "/")
        payload = json.dumps({
            "title": title,
            "message": message,
            "data": {
                "image": image_url,
                "push": {
                    "interruption-level": "critical",
                    "sound": {
                        "name": "default",
                        "critical": 1,
                        "volume": 0,
                    },
                },
            },
        }).encode("utf-8")
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return True, f"{service} HTTP {resp.status} · Bild {image_url}"
                errors.append(f"{service}: HTTP {resp.status}")
        except Exception as exc:
            errors.append(f"{service}: {exc}")
    return False, " | ".join(errors[-10:]) or "Kein Notify-Service verfügbar"


def _final_score_text(result: Any) -> str:
    match = re.search(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", str(result or ""))
    return f"{match.group(1)}:{match.group(2)}" if match else str(result or "").strip()


def _format_kicktipp_result_push(block: dict[str, Any]) -> tuple[str, str]:
    games = list(block.get("games") or [])
    kickoff_raw = str(block.get("kickoff") or "")
    kickoff_label = ""
    try:
        kickoff = datetime.fromisoformat(kickoff_raw).astimezone(BERLIN_TZ)
        weekdays = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
        kickoff_label = f"{weekdays[kickoff.weekday()]}, {kickoff.strftime('%d.%m. · %H:%M')} Uhr"
    except Exception:
        kickoff_label = "Spielblock beendet"

    lines: list[str] = []
    for game in games:
        home = str(game.get("home") or "").strip()
        away = str(game.get("away") or "").strip()
        score = _final_score_text(game.get("result"))
        if home and away and score:
            lines.append(f"{home} {score} {away}")

    title = "⚽ 2. Bundesliga · Endergebnisse"
    message = kickoff_label
    if lines:
        message += "\n" + "\n".join(lines)
    return title, message


def _read_table_push_state() -> dict[str, Any]:
    if not TABLE_PUSH_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(TABLE_PUSH_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_table_push_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    TABLE_PUSH_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def _table_push_monitor_once() -> dict[str, Any]:
    options = load_options()
    if not bool(options.get("table_push_enabled", True)):
        return {"enabled": False}

    snapshot = await _fetch_table_snapshot()
    blocks = snapshot.get("blocks") or []
    state = _read_table_push_state()
    initialized = bool(state.get("initialized"))
    observed: dict[str, Any] = dict(state.get("observed") or {})
    pushed = set(str(x) for x in (state.get("pushed") or []) if x)
    result_pushed = set(str(x) for x in (state.get("result_pushed") or []) if x)
    previous_ranking = state.get("last_ranking") if isinstance(state.get("last_ranking"), dict) else {}
    current_matchday = str(snapshot.get("matchday") or "").strip()
    stored_matchday = str(state.get("ranking_matchday") or "").strip()
    baseline_ranking = state.get("matchday_baseline_ranking") if isinstance(state.get("matchday_baseline_ranking"), dict) else {}

    # Beim Wechsel auf einen neuen Spieltag bleibt der letzte Tabellenstand des
    # vorherigen Spieltags als Vergleichsbasis erhalten. Dadurch wird die
    # Platzveränderung über den ganzen Spieltag hinweg korrekt berechnet, selbst
    # wenn der Monitor während laufender Spiele mehrfach pollt.
    if initialized and current_matchday and current_matchday != stored_matchday:
        baseline_ranking = previous_ranking or _ranking_snapshot_map(list(snapshot.get("ranking") or []))
        stored_matchday = current_matchday
    elif initialized and not baseline_ranking:
        baseline_ranking = previous_ranking or _ranking_snapshot_map(list(snapshot.get("ranking") or []))
        stored_matchday = current_matchday or stored_matchday

    notifications: list[dict[str, Any]] = []

    if not initialized:
        # Erster Lauf ist nur die Ausgangsbasis. Bereits vor Installation beendete
        # Spielblöcke dürfen nicht nachträglich als neue Pushs erscheinen.
        for block in blocks:
            key = str(block.get("key") or "")
            if not key:
                continue
            observed[key] = {
                "complete": bool(block.get("complete")),
                "kickoff": block.get("kickoff"),
                "matchday": block.get("matchday"),
            }
            if block.get("complete"):
                pushed.add(key)
                result_pushed.add(key)
        state = {
            "initialized": True,
            "observed": observed,
            "pushed": sorted(pushed)[-200:],
            "result_pushed": sorted(result_pushed)[-200:],
            "last_ranking": _ranking_snapshot_map(list(snapshot.get("ranking") or [])),
            "ranking_matchday": current_matchday,
            "matchday_baseline_ranking": _ranking_snapshot_map(list(snapshot.get("ranking") or [])),
        }
        _write_table_push_state(state)
        return {"enabled": True, "initialized": True, "notifications": []}

    for block in blocks:
        key = str(block.get("key") or "")
        if not key:
            continue
        previous = observed.get(key)
        is_complete = bool(block.get("complete"))

        # Migration von <=0.1.13: Ein damals fälschlich direkt nach Anpfiff
        # gepushter Block wird wieder freigegeben, solange Kicktipp noch einen roten
        # Live-Zwischenstand meldet. Nach dem Umschalten aller Ergebnisse auf schwarz
        # kann dadurch genau ein korrekter Abschluss-Push erfolgen.
        if not is_complete and bool(block.get("has_live_result")):
            if key in pushed:
                pushed.discard(key)
            if key in result_pushed:
                result_pushed.discard(key)
            if isinstance(previous, dict):
                previous["complete"] = False

        push_failed = False
        just_completed = is_complete and previous is not None and not bool(previous.get("complete"))

        # Ergebnis-Pushs der 2. Bundesliga kommen zentral über
        # OpenLigaDB im Fußballmonitor (Halbzeit + Ende). Kicktipp bleibt hier nur
        # der zuverlässige Trigger für den separaten Tipprunden-Tabellen-Push.
        if just_completed:
            result_pushed.add(key)

        # Der Tabellen-Push bleibt eine separate Meldung nach abgeschlossenem Block.
        if just_completed and key not in pushed:
            summary = _table_user_summary(snapshot, previous_ranking=baseline_ranking, username=_configured_user_name(options))
            _image_path, image_url = await _render_table_push_image(
                snapshot,
                block=block,
                test=False,
                previous_ranking=baseline_ranking,
            )
            title, message = _format_table_push_title(snapshot, test=False, summary=summary)
            ok, status = await asyncio.to_thread(_send_table_image_push, title, message, image_url)
            notifications.append({"key": key, "type": "table", "ok": ok, "status": status, "message": message})
            if ok:
                pushed.add(key)
            else:
                push_failed = True
        observed[key] = {
            "complete": False if push_failed else is_complete,
            "kickoff": block.get("kickoff"),
            "matchday": block.get("matchday"),
        }

    ordered_keys = list(observed.keys())[-200:]
    observed = {key: observed[key] for key in ordered_keys}
    state = {
        "initialized": True,
        "observed": observed,
        "pushed": sorted(pushed)[-200:],
        "result_pushed": sorted(result_pushed)[-200:],
        "last_ranking": _ranking_snapshot_map(list(snapshot.get("ranking") or [])),
        "ranking_matchday": stored_matchday or current_matchday,
        "matchday_baseline_ranking": baseline_ranking or _ranking_snapshot_map(list(snapshot.get("ranking") or [])),
    }
    _write_table_push_state(state)
    return {"enabled": True, "notifications": notifications}


async def _table_push_monitor_loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            result = await _table_push_monitor_once()
            if result.get("notifications"):
                print(f"[kicktipp-table] {result['notifications']}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[kicktipp-table] Monitorfehler: {type(exc).__name__}: {exc}", flush=True)
        options = load_options()
        wait_seconds = max(60, int(options.get("table_push_poll_seconds", 120) or 120))
        await asyncio.sleep(wait_seconds)


async def _football_push_monitor_loop() -> None:
    # Start slightly after the Kicktipp monitor so both do not perform their first
    # network-heavy pass at exactly the same second after add-on startup.
    await asyncio.sleep(30)
    while True:
        try:
            options = load_options()
            options["football_match_push_prefs"] = _read_match_push_prefs()
            result = await asyncio.to_thread(
                football_monitor_once,
                options,
                FOOTBALL_PUSH_STATE_FILE,
                _send_football_critical_push,
            )
            if result.get("notifications"):
                print(f"[football-results] {result['notifications']}", flush=True)
            if result.get("errors"):
                print(f"[football-results] Quellenhinweise: {result['errors']}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[football-results] Monitorfehler: {type(exc).__name__}: {exc}", flush=True)
        options = load_options()
        wait_seconds = max(60, int(options.get("football_push_poll_seconds", 60) or 60))
        await asyncio.sleep(wait_seconds)


def _is_favorite_match_names(home: str, away: str) -> bool:
    options = load_options()
    favorites = [x.strip() for x in re.split(r"[|;\n]+", str(options.get("football_favorite_teams") or "")) if x.strip()]
    home_norm = normalize_team(home)
    away_norm = normalize_team(away)
    for favorite in favorites:
        fav = normalize_team(favorite)
        if fav and (fav == home_norm or fav == away_norm or fav in home_norm or fav in away_norm or home_norm in fav or away_norm in fav):
            return True
    return False


@app.get("/api/football/match-push")
async def football_match_push_get(game_id: str, home: str = "", away: str = "") -> JSONResponse:
    prefs = _read_match_push_prefs()
    entry = prefs.get(str(game_id)) if isinstance(prefs.get(str(game_id)), dict) else {}
    configured = bool(entry.get("override_defaults", False))
    effective_home = str(home or entry.get("home") or "")
    effective_away = str(away or entry.get("away") or "")
    favorite = _is_favorite_match_names(effective_home, effective_away)
    defaults = {
        "goals": favorite,
        "cards": False,
        "reminder_30": favorite,
        "halftime": True,
        "final": True,
        "mute_all": False,
    }
    if configured:
        values = {key: bool(entry.get(key, defaults[key])) for key in defaults}
    else:
        values = defaults
    return JSONResponse({
        "ok": True,
        "game_id": str(game_id),
        "configured": configured,
        "favorite": favorite,
        **values,
        "enabled_at": str(entry.get("enabled_at") or ""),
    }, headers={"Cache-Control": "no-store"})


@app.post("/api/football/match-push")
async def football_match_push_set(req: MatchPushPreferenceRequest) -> JSONResponse:
    game_id = str(req.game_id or "").strip()
    if not game_id:
        raise HTTPException(status_code=400, detail="Spiel-ID fehlt.")
    prefs = _read_match_push_prefs()
    previous = prefs.get(game_id) if isinstance(prefs.get(game_id), dict) else {}
    favorite = _is_favorite_match_names(str(req.home or ""), str(req.away or ""))
    mute_all = bool(req.mute_all)
    enabled = bool((req.goals or req.cards or req.reminder_30 or req.halftime or req.final) and not mute_all)
    newly_enabled = not bool(previous.get("override_defaults")) or bool(previous.get("mute_all"))
    prefs[game_id] = {
        "game_id": game_id,
        "home": str(req.home or "").strip(),
        "away": str(req.away or "").strip(),
        "kickoff": str(req.kickoff or "").strip(),
        "competition": str(req.competition or "").strip(),
        "competition_label": str(req.competition_label or "").strip(),
        "detail_url": str(req.detail_url or "").strip(),
        "goals": bool(req.goals) and not mute_all,
        "cards": bool(req.cards) and not mute_all,
        "reminder_30": bool(req.reminder_30) and not mute_all,
        "halftime": bool(req.halftime) and not mute_all,
        "final": bool(req.final) and not mute_all,
        "mute_all": mute_all,
        "favorite": favorite,
        "override_defaults": True,
        "enabled_at": datetime.now(timezone.utc).isoformat() if newly_enabled else str(previous.get("enabled_at") or datetime.now(timezone.utc).isoformat()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cutoff = datetime.now(timezone.utc).timestamp() - 3 * 24 * 3600
    for key, entry in list(prefs.items()):
        if not isinstance(entry, dict):
            prefs.pop(key, None)
            continue
        try:
            ts = datetime.fromisoformat(str(entry.get("kickoff") or "").replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts < cutoff:
            prefs.pop(key, None)
    _write_match_push_prefs(prefs)
    return JSONResponse({
        "ok": True,
        "game_id": game_id,
        "enabled": enabled,
        "favorite": favorite,
        "goals": bool(req.goals) and not mute_all,
        "cards": bool(req.cards) and not mute_all,
        "reminder_30": bool(req.reminder_30) and not mute_all,
        "halftime": bool(req.halftime) and not mute_all,
        "final": bool(req.final) and not mute_all,
        "mute_all": mute_all,
    }, headers={"Cache-Control": "no-store"})


@app.get("/api/football/status")
async def football_status() -> JSONResponse:
    options = load_options()
    state: dict[str, Any] = {}
    if FOOTBALL_PUSH_STATE_FILE.exists():
        try:
            data = json.loads(FOOTBALL_PUSH_STATE_FILE.read_text(encoding="utf-8"))
            state = data if isinstance(data, dict) else {}
        except Exception:
            state = {}
    return JSONResponse({
        "ok": True,
        "enabled": bool(options.get("football_push_enabled", True)),
        "poll_seconds": max(60, int(options.get("football_push_poll_seconds", 60) or 60)),
        "competitions": {
            "bundesliga": bool(options.get("football_bl1_enabled", True)),
            "bundesliga2": bool(options.get("football_bl2_enabled", True)),
            "dfb_pokal": bool(options.get("football_dfb_enabled", True)),
            "supercup": bool(options.get("football_supercup_enabled", True)),
            "germany_men": bool(options.get("football_germany_enabled", True)),
            "champions_league_german_clubs": bool(options.get("football_ucl_enabled", True)),
            "europa_league_german_clubs": bool(options.get("football_uel_enabled", True)),
            "conference_league_german_clubs": bool(options.get("football_uecl_enabled", True)),
        },
        "api_football_configured": bool(str(options.get("api_football_key") or "").strip()),
        "api_football_mode": "halftime_and_match_details",
        "api_football_halftime_poll_seconds": max(60, int(options.get("api_football_halftime_poll_seconds", 60) or 60)),
        "push_url": str(options.get("football_push_url") or ""),
        "favorite_teams": str(options.get("football_favorite_teams") or "VfL Osnabrück|Bayer 04 Leverkusen"),
        "state": state,
    }, headers={"Cache-Control": "no-store"})


def _estimate_live_minute(game: dict[str, Any], now: datetime) -> str:
    kickoff_raw = str(game.get("kickoff") or "")
    try:
        kickoff = datetime.fromisoformat(kickoff_raw).astimezone(timezone.utc)
    except Exception:
        return ""
    elapsed = max(0.0, (now - kickoff).total_seconds() / 60.0)
    if elapsed < 0.5:
        return "1′"
    if elapsed <= 45:
        return f"{max(1, int(elapsed))}′"
    if elapsed <= 60:
        overtime = max(1, min(15, int(elapsed - 44)))
        return f"45+{overtime}′"
    second_half = max(46, int(elapsed - 15))
    if second_half <= 90:
        return f"{second_half}′"
    return f"90+{max(1, min(30, int(elapsed - 105)))}′"


def _football_ui_status(game: dict[str, Any], now: datetime) -> tuple[str, str]:
    if bool(game.get("finished")):
        return "finished", "Beendet"
    if bool(game.get("halftime")):
        score = str(game.get("halftime_score") or "").strip()
        return "halftime", f"Halbzeit · {score}" if score else "Halbzeit"
    kickoff_raw = str(game.get("kickoff") or "")
    try:
        kickoff = datetime.fromisoformat(kickoff_raw).astimezone(timezone.utc)
    except Exception:
        kickoff = None
    raw_status = str(game.get("status") or "").strip().upper()
    source = str(game.get("source") or "")
    if raw_status == "UNKNOWN" and source == "Kicktipp Livebox":
        return "unknown", "Status offen"
    if raw_status == "LIVE" or bool(game.get("started")) or (kickoff is not None and now >= kickoff):
        minute = str(game.get("minute") or "").strip() or _estimate_live_minute(game, now)
        game["minute"] = minute
        return "live", f"Live · {minute}" if minute else "Live"
    return "scheduled", "Geplant"


@app.get("/api/football/live")
async def football_live() -> JSONResponse:
    options = load_options()
    state: dict[str, Any] = {}
    if FOOTBALL_PUSH_STATE_FILE.exists():
        try:
            raw = json.loads(FOOTBALL_PUSH_STATE_FILE.read_text(encoding="utf-8"))
            state = raw if isinstance(raw, dict) else {}
        except Exception:
            state = {}

    now = datetime.now(timezone.utc)
    try:
        blocks, updated_state, errors = await asyncio.to_thread(football_collect_blocks, options, state, now, allow_api_refresh=False)
        # Keep UEFA schedule/discovery caches warm, but preserve push-state fields.
        merged = dict(state)
        for cache_key in ("uefa_competitions", "uefa_schedule_cache", "kicktipp_livebox", "api_football_halftime"):
            if cache_key in updated_state:
                merged[cache_key] = updated_state[cache_key]
        if merged != state:
            merged["updated_at"] = datetime.now(timezone.utc).isoformat()
            FOOTBALL_PUSH_STATE_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Live-Spiele konnten nicht geladen werden: {type(exc).__name__}: {exc}")

    games: list[dict[str, Any]] = []
    for block in blocks:
        for game in block.get("games") or []:
            status_key, status_label = _football_ui_status(game, now)
            kickoff_raw = str(game.get("kickoff") or block.get("kickoff") or "")
            games.append({
                "id": game.get("id"),
                "competition": block.get("competition"),
                "competition_label": block.get("competition_label"),
                "kickoff": kickoff_raw,
                "home": game.get("home"),
                "away": game.get("away"),
                "score": game.get("score") or "",
                "halftime_score": game.get("halftime_score") or "",
                "status": status_key,
                "status_label": status_label,
                "minute": game.get("minute") or "",
                "home_logo": game.get("home_logo") or "",
                "away_logo": game.get("away_logo") or "",
                "home_country": game.get("home_country") or "",
                "away_country": game.get("away_country") or "",
                "source": game.get("source") or "",
                "kicktipp_detail_url": game.get("kicktipp_detail_url") or "",
                "api_fixture_id": game.get("api_fixture_id") or "",
            })
    games.sort(key=lambda g: str(g.get("kickoff") or ""))
    return JSONResponse({
        "ok": True,
        "updated_at": datetime.now(BERLIN_TZ).isoformat(),
        "games": games,
        "errors": errors,
    }, headers={"Cache-Control": "no-store"})


def _detail_cache_read(path: Path, ttl_seconds: int) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > ttl_seconds:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _detail_cache_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_api_rate(rate_or_response: Any, source: str) -> None:
    try:
        if isinstance(rate_or_response, dict):
            remaining = str(rate_or_response.get("remaining") or "")
            limit = str(rate_or_response.get("limit") or "")
        else:
            headers = getattr(rate_or_response, "headers", {}) or {}
            remaining = str(headers.get("x-ratelimit-requests-remaining") or "")
            limit = str(headers.get("x-ratelimit-requests-limit") or "")
        existing: dict[str, Any] = {}
        if API_FOOTBALL_USAGE_FILE.exists():
            try:
                raw = json.loads(API_FOOTBALL_USAGE_FILE.read_text(encoding="utf-8"))
                existing = raw if isinstance(raw, dict) else {}
            except Exception:
                existing = {}
        if remaining or limit:
            existing.update({"remaining": remaining, "limit": limit})
        existing.update({"updated_at": datetime.now(timezone.utc).isoformat(), "source": source})
        API_FOOTBALL_USAGE_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _api_headers(api_key: str) -> dict[str, str]:
    return {
        "x-apisports-key": api_key,
        "Accept": "application/json",
        "User-Agent": "Kicktipp-TipBot/0.1.42",
    }


def _api_fixture_cache_path(home: str, away: str, kickoff: str) -> Path:
    raw = f"fixture|{home}|{away}|{kickoff}"
    return DATA_DIR / "api_football_detail_cache_v3" / f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}_fixture.json"


def _api_lineup_cache_path(fixture_id: str) -> Path:
    return DATA_DIR / "api_football_detail_cache_v3" / f"fixture_{fixture_id}_lineups.json"


def _resolve_api_fixture_id_for_game(api_key: str, home: str, away: str, kickoff: str) -> dict[str, Any]:
    cache_path = _api_fixture_cache_path(home, away, kickoff)
    cached = _detail_cache_read(cache_path, 7 * 24 * 3600)
    if cached and str(cached.get("fixture_id") or "").strip():
        return cached
    try:
        local_date = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00")).astimezone(BERLIN_TZ).date().isoformat()
    except Exception:
        local_date = datetime.now(BERLIN_TZ).date().isoformat()
    fixtures, _rate = _api_football_get_day(api_key, local_date)
    if _rate:
        _record_api_rate(_rate, "fixture lookup")
    item, confidence = _choose_api_fixture(fixtures, {"home": home, "away": away, "kickoff": kickoff})
    if not item:
        return {}
    normalized = _normalize_api_fixture(item)
    result = {
        "fixture_id": str(normalized.get("fixture_id") or ""),
        "home_logo": str(normalized.get("home_logo") or ""),
        "away_logo": str(normalized.get("away_logo") or ""),
        "api_score": str(normalized.get("score") or ""),
        "api_status": str(normalized.get("status") or ""),
        "confidence": round(float(confidence), 3),
        "kickoff": str(normalized.get("kickoff") or kickoff),
    }
    if result.get("fixture_id"):
        _detail_cache_write(cache_path, result)
    return result


def _player_sort_key(player: dict[str, Any]) -> tuple[int, int, int, str]:
    grid = str(player.get("grid") or "")
    m = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", grid)
    if m:
        return (0, int(m.group(1)), int(m.group(2)), str(player.get("name") or ""))
    number_text = str(player.get("number") or "")
    try:
        number_value = int(number_text)
    except Exception:
        number_value = 999
    return (1, 999, number_value, str(player.get("name") or ""))


def _normalize_api_lineups(
    response_items: list[dict[str, Any]],
    *,
    home_team: dict[str, Any] | None = None,
    away_team: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    lineups: list[dict[str, Any]] = []
    home_team = home_team or {}
    away_team = away_team or {}
    home_id = str(home_team.get("id") or "")
    away_id = str(away_team.get("id") or "")
    for item in response_items:
        if not isinstance(item, dict):
            continue
        team = item.get("team") if isinstance(item.get("team"), dict) else {}
        coach = item.get("coach") if isinstance(item.get("coach"), dict) else {}
        def convert_player_row(row: Any) -> dict[str, Any] | None:
            player = row.get("player") if isinstance(row, dict) and isinstance(row.get("player"), dict) else None
            if not player:
                return None
            return {
                "name": str(player.get("name") or "").strip(),
                "number": str(player.get("number") or "").strip(),
                "pos": str(player.get("pos") or "").strip(),
                "grid": str(player.get("grid") or "").strip(),
            }
        start_xi = [p for p in (convert_player_row(row) for row in (item.get("startXI") or [])) if p]
        substitutes = [p for p in (convert_player_row(row) for row in (item.get("substitutes") or [])) if p]
        start_xi.sort(key=_player_sort_key)
        substitutes.sort(key=_player_sort_key)
        team_id = str(team.get("id") or "")
        side = "home" if team_id and team_id == home_id else "away" if team_id and team_id == away_id else ""
        lineups.append({
            "team": str(team.get("name") or "").strip(),
            "logo": str(team.get("logo") or "").strip(),
            "side": side,
            "formation": str(item.get("formation") or "").strip(),
            "coach": str(coach.get("name") or "").strip(),
            "start_xi": start_xi,
            "substitutes": substitutes,
            "source": "api_football",
        })
    return lineups


def _api_event_time(event: dict[str, Any]) -> str:
    time_node = event.get("time") if isinstance(event.get("time"), dict) else {}
    elapsed = time_node.get("elapsed")
    extra = time_node.get("extra")
    if elapsed is None:
        return ""
    try:
        label = str(int(elapsed))
    except Exception:
        label = str(elapsed)
    if extra not in (None, "", 0, "0"):
        try:
            label += f"+{int(extra)}"
        except Exception:
            label += f"+{extra}"
    return label + "′"


def _api_event_sort_key(event: dict[str, Any]) -> tuple[int, int]:
    node = event.get("time") if isinstance(event.get("time"), dict) else {}
    try:
        elapsed = int(node.get("elapsed") or 0)
    except Exception:
        elapsed = 0
    try:
        extra = int(node.get("extra") or 0)
    except Exception:
        extra = 0
    return elapsed, extra


def _translate_api_event_detail(detail: str, event_type: str) -> str:
    raw = str(detail or "").strip()
    key = raw.casefold()
    translations = {
        "normal goal": "Tor",
        "own goal": "Eigentor",
        "penalty": "Elfmeter",
        "missed penalty": "Elfmeter verschossen",
        "yellow card": "",
        "red card": "",
        "second yellow card": "",
    }
    if key in translations:
        return translations[key]
    if event_type in {"subst", "substitution", "card"}:
        return ""
    return raw


def _normalize_api_events(
    raw_events: list[dict[str, Any]],
    *,
    home_team: dict[str, Any] | None = None,
    away_team: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    substitutions: list[dict[str, Any]] = []
    home_team = home_team or {}
    away_team = away_team or {}
    home_id = str(home_team.get("id") or "")
    away_id = str(away_team.get("id") or "")
    home_score = 0
    away_score = 0
    for event in sorted((e for e in raw_events if isinstance(e, dict)), key=_api_event_sort_key):
        team = event.get("team") if isinstance(event.get("team"), dict) else {}
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        assist = event.get("assist") if isinstance(event.get("assist"), dict) else {}
        event_type = str(event.get("type") or "").strip().casefold()
        detail_raw = str(event.get("detail") or "").strip()
        detail = _translate_api_event_detail(detail_raw, event_type)
        comments = str(event.get("comments") or "").strip()
        team_id = str(team.get("id") or "")
        side = "home" if team_id and team_id == home_id else "away" if team_id and team_id == away_id else ""
        common = {
            "time": _api_event_time(event),
            "team": str(team.get("name") or "").strip(),
            "team_logo": str(team.get("logo") or "").strip(),
            "side": side,
            "detail": detail,
            "comments": comments,
        }
        if event_type == "goal":
            missed = "missed" in detail_raw.casefold()
            if not missed:
                if side == "home":
                    home_score += 1
                elif side == "away":
                    away_score += 1
            goals.append({
                **common,
                "player": str(player.get("name") or "").strip(),
                "assist": str(assist.get("name") or "").strip(),
                "score_after": f"{home_score}:{away_score}",
                "scored": not missed,
            })
        elif event_type == "card":
            detail_key = detail_raw.casefold()
            if "second yellow" in detail_key:
                card = "second_yellow"
            elif "red" in detail_key:
                card = "red"
            else:
                card = "yellow"
            cards.append({**common, "player": str(player.get("name") or "").strip(), "card": card})
        elif event_type in {"subst", "substitution"}:
            substitutions.append({**common, "player_out": str(player.get("name") or "").strip(), "player_in": str(assist.get("name") or "").strip()})
    return {"goals": goals, "cards": cards, "substitutions": substitutions}


def _api_fixture_detail_cache_path(fixture_id: str) -> Path:
    return DATA_DIR / "api_football_detail_cache_v3" / f"fixture_{fixture_id}_detail.json"


def _fetch_api_fixture_detail(api_key: str, fixture_id: str, status: str) -> dict[str, Any]:
    fixture_id = str(fixture_id or "").strip()
    if not fixture_id:
        return {}
    cache_path = _api_fixture_detail_cache_path(fixture_id)
    ttl = 365 * 24 * 3600 if str(status).casefold() == "finished" else 300
    cached = _detail_cache_read(cache_path, ttl)
    if cached:
        return cached
    response = requests.get(
        API_FOOTBALL_BASE + "/fixtures",
        params={"id": fixture_id},
        headers=_api_headers(api_key),
        timeout=20,
    )
    response.raise_for_status()
    _record_api_rate(response, "fixture detail")
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    errors = payload.get("errors")
    if errors and errors not in ([], {}):
        raise RuntimeError(f"API-Football: {errors}")
    items = payload.get("response") if isinstance(payload.get("response"), list) else []
    item = items[0] if items and isinstance(items[0], dict) else {}
    if not item:
        return {}
    lineups_raw = item.get("lineups") if isinstance(item.get("lineups"), list) else []
    events_raw = item.get("events") if isinstance(item.get("events"), list) else []
    # API-Football normally embeds both collections in /fixtures?id=. Some
    # competitions/plans may omit one of them there; only then use the specific
    # endpoint. This keeps the normal tap to one detail request while still
    # making substitutions/lineups reliable when the compact payload is sparse.
    if not lineups_raw:
        lineup_response = requests.get(
            API_FOOTBALL_BASE + "/fixtures/lineups",
            params={"fixture": fixture_id},
            headers=_api_headers(api_key),
            timeout=20,
        )
        lineup_response.raise_for_status()
        _record_api_rate(lineup_response, "fixture lineups")
        lineup_payload = lineup_response.json()
        if isinstance(lineup_payload, dict) and isinstance(lineup_payload.get("response"), list):
            lineups_raw = lineup_payload.get("response") or []
    if not events_raw:
        event_response = requests.get(
            API_FOOTBALL_BASE + "/fixtures/events",
            params={"fixture": fixture_id},
            headers=_api_headers(api_key),
            timeout=20,
        )
        event_response.raise_for_status()
        _record_api_rate(event_response, "fixture events")
        event_payload = event_response.json()
        if isinstance(event_payload, dict) and isinstance(event_payload.get("response"), list):
            events_raw = event_payload.get("response") or []
    teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
    home_team = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away_team = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    result = {
        "fixture_id": fixture_id,
        "home_logo": str(home_team.get("logo") or ""),
        "away_logo": str(away_team.get("logo") or ""),
        "lineups": _normalize_api_lineups(lineups_raw, home_team=home_team, away_team=away_team),
        "events": _normalize_api_events(events_raw, home_team=home_team, away_team=away_team),
        "source": "API-Football",
    }
    _detail_cache_write(cache_path, result)
    return result


def _fetch_api_lineups_for_game(api_key: str, home: str, away: str, kickoff: str, status: str) -> dict[str, Any]:
    fixture_info = _resolve_api_fixture_id_for_game(api_key, home, away, kickoff)
    fixture_id = str(fixture_info.get("fixture_id") or "").strip()
    if not fixture_id:
        return {}
    cache_path = _api_lineup_cache_path(fixture_id)
    cached = _detail_cache_read(cache_path, 365 * 24 * 3600)
    if cached and isinstance(cached.get("lineups"), list) and cached.get("lineups"):
        return cached
    response = requests.get(
        API_FOOTBALL_BASE + "/fixtures/lineups",
        params={"fixture": fixture_id},
        headers=_api_headers(api_key),
        timeout=20,
    )
    response.raise_for_status()
    _record_api_rate(response, "fixture lineups")
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    errors = payload.get("errors")
    if errors and errors not in ([], {}):
        raise RuntimeError(f"API-Football: {errors}")
    items = payload.get("response") if isinstance(payload.get("response"), list) else []
    lineups = _normalize_api_lineups(items)
    result = {
        "fixture_id": fixture_id,
        "home_logo": str(fixture_info.get("home_logo") or ""),
        "away_logo": str(fixture_info.get("away_logo") or ""),
        "lineups": lineups,
        "source": "API-Football",
    }
    if lineups or str(status).casefold() == "finished":
        _detail_cache_write(cache_path, result)
    return result


@app.get("/api/football/diagnostics")
async def football_diagnostics() -> JSONResponse:
    options = load_options()
    state: dict[str, Any] = {}
    if FOOTBALL_PUSH_STATE_FILE.exists():
        try:
            raw = json.loads(FOOTBALL_PUSH_STATE_FILE.read_text(encoding="utf-8"))
            state = raw if isinstance(raw, dict) else {}
        except Exception:
            state = {}
    livebox = state.get("kicktipp_livebox") if isinstance(state.get("kicktipp_livebox"), dict) else {}
    dates = livebox.get("dates") if isinstance(livebox.get("dates"), dict) else {}
    kicktipp_updates = []
    for date_key, entry in dates.items():
        if isinstance(entry, dict) and entry.get("updated_at"):
            kicktipp_updates.append({"date": str(date_key), "updated_at": str(entry.get("updated_at")), "url": str(entry.get("url") or "")})
    halftime = state.get("api_football_halftime") if isinstance(state.get("api_football_halftime"), dict) else {}
    rate = halftime.get("rate") if isinstance(halftime.get("rate"), dict) else {}
    goal_rate = state.get("api_football_goal_rate") if isinstance(state.get("api_football_goal_rate"), dict) else {}
    detail_rate: dict[str, Any] = {}
    if API_FOOTBALL_USAGE_FILE.exists():
        try:
            raw = json.loads(API_FOOTBALL_USAGE_FILE.read_text(encoding="utf-8"))
            detail_rate = raw if isinstance(raw, dict) else {}
        except Exception:
            detail_rate = {}
    candidates = []
    if rate:
        candidates.append({**rate, "updated_at": halftime.get("last_query"), "source": "Halbzeit-Monitor"})
    if goal_rate:
        candidates.append(dict(goal_rate))
    if detail_rate:
        candidates.append(dict(detail_rate))
    usage = max(candidates, key=lambda x: str(x.get("updated_at") or ""), default={})
    usage_is_today = False
    try:
        usage_dt = datetime.fromisoformat(str(usage.get("updated_at") or "").replace("Z", "+00:00")).astimezone(BERLIN_TZ)
        usage_is_today = usage_dt.date() == datetime.now(BERLIN_TZ).date()
    except Exception:
        usage_is_today = False
    try:
        limit_value = int(str(usage.get("limit") or "0"))
        remaining_value = int(str(usage.get("remaining") or "0"))
        used_value = max(0, limit_value - remaining_value) if limit_value and usage_is_today else None
    except Exception:
        used_value = None
    return JSONResponse({
        "ok": True,
        "favorites": [x.strip() for x in re.split(r"[|;\n]+", str(options.get("football_favorite_teams") or "")) if x.strip()],
        "last_monitor_update": state.get("updated_at"),
        "last_kicktipp": max(kicktipp_updates, key=lambda x: x.get("updated_at") or "", default={}),
        "api_football": {**usage, "used": used_value, "is_today": usage_is_today},
        "last_halftime_query": halftime.get("last_query"),
        "recent_transitions": (state.get("recent_transitions") or [])[-12:],
        "errors": (state.get("last_errors") or [])[-10:],
        "blocks": state.get("last_block_count"),
    }, headers={"Cache-Control": "no-store"})


@app.get("/api/football/table/{competition}")
async def football_league_table(competition: str) -> JSONResponse:
    shortcut_map = {"bl1": "bl1", "bl2": "bl2"}
    shortcut = shortcut_map.get(str(competition or "").strip().lower())
    if not shortcut:
        raise HTTPException(status_code=404, detail="Für diesen Wettbewerb ist keine Tabelle hinterlegt.")
    local_now = datetime.now(BERLIN_TZ)
    season = local_now.year if local_now.month >= 7 else local_now.year - 1
    try:
        response = await asyncio.to_thread(
            requests.get,
            f"{OPENLIGA_BASE}/getbltable/{shortcut}/{season}",
            headers={"Accept": "application/json", "User-Agent": "Kicktipp-TipBot/0.1.42"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("OpenLigaDB lieferte ein unerwartetes Tabellenformat")
        rows: list[dict[str, Any]] = []
        for idx, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            goals = item.get("goals")
            opponent_goals = item.get("opponentGoals")
            goal_diff = item.get("goalDiff")
            if goal_diff is None and goals is not None and opponent_goals is not None:
                try:
                    goal_diff = int(goals) - int(opponent_goals)
                except Exception:
                    goal_diff = ""
            rows.append({
                "position": idx,
                "team": str(item.get("teamName") or item.get("shortName") or "").strip(),
                "short_name": str(item.get("shortName") or "").strip(),
                "logo": str(item.get("teamIconUrl") or "").strip(),
                "matches": item.get("matches") if item.get("matches") is not None else "",
                "won": item.get("won") if item.get("won") is not None else "",
                "draw": item.get("draw") if item.get("draw") is not None else "",
                "lost": item.get("lost") if item.get("lost") is not None else "",
                "goals": goals if goals is not None else "",
                "opponent_goals": opponent_goals if opponent_goals is not None else "",
                "goal_diff": goal_diff if goal_diff is not None else "",
                "points": item.get("points") if item.get("points") is not None else "",
            })
        return JSONResponse({
            "ok": True,
            "competition": competition,
            "label": "1. Bundesliga" if shortcut == "bl1" else "2. Bundesliga",
            "season": f"{season}/{str(season + 1)[-2:]}",
            "rows": rows,
        }, headers={"Cache-Control": "no-store"})
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(status_code=502, detail=f"OpenLigaDB HTTP {code}: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tabelle konnte nicht geladen werden: {type(exc).__name__}: {exc}")


@app.get("/api/football/details")
async def football_details(home: str, away: str, kickoff: str, status: str = "", detail_url: str = "", competition_label: str = "", fixture_id: str = "") -> JSONResponse:
    kicktipp_data: dict[str, Any] = {}
    kicktipp_error = ""
    try:
        ttl = 43200 if str(status or "").casefold() == "finished" else 300
        resolved_url = str(detail_url or "").strip()
        if not resolved_url:
            resolved_url = await asyncio.to_thread(kicktipp_resolve_public_detail_url, competition_label, home, away, kickoff)
        kicktipp_data = await asyncio.to_thread(
            kicktipp_cached_public_detail, resolved_url, DATA_DIR / "kicktipp_detail_cache_v3", ttl, home, away
        )
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        kicktipp_error = f"Kicktipp HTTP {code}: {exc}"
    except Exception as exc:
        kicktipp_error = f"{type(exc).__name__}: {exc}"

    data = dict(kicktipp_data) if isinstance(kicktipp_data, dict) else {}
    data.setdefault("home", home)
    data.setdefault("away", away)
    data.setdefault("lineups", [])
    data.setdefault("events", {"goals": [], "cards": [], "substitutions": []})

    api_key = str(load_options().get("api_football_key") or "").strip()
    api_result: dict[str, Any] = {}
    api_error = ""
    if api_key:
        try:
            resolved_fixture_id = str(fixture_id or "").strip()
            fixture_info: dict[str, Any] = {}
            if not resolved_fixture_id:
                fixture_info = await asyncio.to_thread(_resolve_api_fixture_id_for_game, api_key, home, away, kickoff)
                resolved_fixture_id = str(fixture_info.get("fixture_id") or "").strip()
            if resolved_fixture_id:
                api_result = await asyncio.to_thread(_fetch_api_fixture_detail, api_key, resolved_fixture_id, status)
                if fixture_info:
                    api_result.setdefault("home_logo", fixture_info.get("home_logo") or "")
                    api_result.setdefault("away_logo", fixture_info.get("away_logo") or "")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 502
            api_error = f"API-Football HTTP {code}: {exc}"
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"

    if api_result.get("home_logo"):
        data["home_logo"] = api_result.get("home_logo")
    if api_result.get("away_logo"):
        data["away_logo"] = api_result.get("away_logo")
    if isinstance(api_result.get("lineups"), list) and api_result.get("lineups"):
        data["lineups"] = api_result.get("lineups")
        data["lineup_source"] = "API-Football"
    elif data.get("lineups"):
        data["lineup_source"] = "Kicktipp (Fallback)"

    api_events = api_result.get("events") if isinstance(api_result.get("events"), dict) else {}
    if any(api_events.get(key) for key in ("goals", "cards", "substitutions")):
        data["events"] = {
            "goals": api_events.get("goals") or [],
            "cards": api_events.get("cards") or [],
            "substitutions": api_events.get("substitutions") or [],
        }
        data["event_source"] = "API-Football"
    else:
        data["event_source"] = "Kicktipp"

    if api_result.get("lineups") or any(data.get("events", {}).get(key) for key in ("goals", "cards", "substitutions")):
        data["ok"] = True
        data["configured"] = True
    if api_error:
        data["api_lineup_notice"] = f"API-Football-Details aktuell nicht verfügbar: {api_error}"
    if kicktipp_error:
        data["kicktipp_notice"] = f"Kicktipp-Details aktuell eingeschränkt: {kicktipp_error}"
    if not data.get("ok") and not data.get("lineups") and not any(data.get("events", {}).get(k) for k in ("goals","cards","substitutions")):
        raise HTTPException(status_code=502, detail="Für dieses Spiel konnten aktuell keine Detaildaten geladen werden.")
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.get("/api/table")
async def get_table() -> JSONResponse:
    try:
        return JSONResponse(await _fetch_table_snapshot(), headers={"Cache-Control": "no-store"})
    except HTTPException:
        raise
    except PlaywrightTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Timeout beim Tabellenabruf: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tabelle konnte nicht geladen werden: {type(exc).__name__}: {exc}")


@app.post("/api/table/test-push")
async def table_test_push() -> JSONResponse:
    try:
        snapshot = await _fetch_table_snapshot()
        state = _read_table_push_state()
        previous_ranking = state.get("matchday_baseline_ranking") if isinstance(state.get("matchday_baseline_ranking"), dict) else {}
        if not previous_ranking:
            previous_ranking = state.get("last_ranking") if isinstance(state.get("last_ranking"), dict) else {}
        summary = _table_user_summary(snapshot, previous_ranking=previous_ranking, username=_configured_user_name())
        _image_path, image_url = await _render_table_push_image(snapshot, test=True, previous_ranking=previous_ranking)
        title, message = _format_table_push_title(snapshot, test=True, summary=summary)
        ok, status = await asyncio.to_thread(_send_table_image_push, title, message, image_url)
        if not ok:
            raise HTTPException(status_code=502, detail=f"Tabellen-Push fehlgeschlagen: {status}")
        return JSONResponse({
            "ok": True,
            "message": "Tabellen-Test-Push wurde als Bild mit der vollständigen aktuellen Tabelle gesendet.",
            "push_message": message,
            "push_status": status,
            "image_url": image_url,
            "matchday": snapshot.get("matchday"),
            "ranking": snapshot.get("ranking"),
            "summary": summary,
            "updated_at": snapshot.get("updated_at"),
        })
    except HTTPException:
        raise
    except PlaywrightTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Timeout beim Tabellen-Test-Push: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tabellen-Test-Push fehlgeschlagen: {type(exc).__name__}: {exc}")
