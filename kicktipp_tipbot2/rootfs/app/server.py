from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/data") if Path("/data").exists() else APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OPTIONS_FILE = Path("/data/options.json")
STATE_FILE = DATA_DIR / "kicktipp_browser_state.json"
LAST_SCREENSHOT = DATA_DIR / "last_kicktipp_result.png"
LAST_LOG = DATA_DIR / "last_run.json"

app = FastAPI(title="Kicktipp Bot für secondary", version="0.1.6")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def load_options() -> dict[str, Any]:
    defaults = {
        "tipprunde": "",
        "username": "",
        "password": "",
        "auto_save_default": True,
        "kicktipp_url": "",
    }
    if OPTIONS_FILE.exists():
        try:
            data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
            defaults.update({k: v for k, v in data.items() if v is not None})
        except Exception:
            pass
    return defaults


def normalize_team(value: str) -> str:
    value = value.lower().strip()
    repl = {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        ".": "", ",": "", "-": " ", "–": " ", "—": " ", ":": "",
    }
    for old, new in repl.items():
        value = value.replace(old, new)
    value = re.sub(r"\b(1|fc|sc|sv|vfl|vfb|tsv|sg|spvgg|ksc|fck|hsv)\b", " ", value)
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
    .replace(/\b(1|fc|sc|sv|vfl|vfb|tsv|sg|spvgg|ksc|fck|hsv)\b/g, ' ')
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
      results.push({line: tip.line, status: 'not_found', detail: 'Zeile nicht gefunden'});
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
            """
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

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    opts = load_options()
    html = html.replace("__OPTIONS__", json.dumps(opts, ensure_ascii=False))
    return html


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "app": "Kicktipp Bot für secondary", "version": "0.1.6", "port": 8149}


@app.get("/api/config")
async def config() -> dict[str, Any]:
    opts = load_options()
    opts["password"] = "" if opts.get("password") else ""
    opts["has_saved_session"] = STATE_FILE.exists()
    opts["port"] = 8149
    return opts


@app.post("/api/parse")
async def parse(req: ParseRequest) -> dict[str, Any]:
    tips = parse_tips(req.text)
    return {
        "count": len(tips),
        "violations": [],
        "tips": [t.__dict__ for t in tips],
    }


@app.post("/api/run")
async def run(req: RunRequest) -> JSONResponse:
    options = load_options()
    tipprunde = req.tipprunde.strip() or options.get("tipprunde", "")
    kicktipp_url = req.kicktipp_url.strip() or options.get("kicktipp_url", "")
    username = req.username.strip() or options.get("username", "")
    password = req.password or options.get("password", "")
    # secondary-Version: keine Osnabrück-Sperre / keine VfL-Schutzregel.

    tips = parse_tips(req.text)
    if not tips:
        raise HTTPException(status_code=400, detail="Keine gültigen Tipps gefunden. Format: Team A – Team B: 2:1")
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


@app.post("/api/logout")
async def logout() -> dict[str, Any]:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"ok": True, "message": "Gespeicherte Kicktipp-Session gelöscht."}
