#!/usr/bin/env python3
"""Small local-only-control UI for the WebApp-Updater.

The web process never receives the Supervisor token and cannot start an app
operation itself. It only validates a user selection against the catalog that
the updater produced from reachable Git history and atomically places a request
in /data.  The main updater process performs every privileged operation in its
normal, persistent Supervisor-job cycle.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import hmac
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DATA = Path("/data")
CATALOG = DATA / "version-catalog.json"
STATUS = DATA / "version-status.json"
BACKUPS = DATA / "pre-update-backups.json"
REQUESTS = DATA / "rollback-requests"
ACCESS_FILE = DATA / "version-ui-access-code"
ACCESS_CODE = ""
REQUEST_LOCK = threading.Lock()
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SLUG = re.compile(r"^(?:local_)?[a-z0-9][a-z0-9_-]*$")


def read_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, ValueError, TypeError):
        return default


def load_access_code():
    """Keep one private access code across updater restarts."""
    try:
        code = ACCESS_FILE.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{16,64}", code):
            return code
    except OSError:
        pass
    DATA.mkdir(mode=0o700, exist_ok=True)
    code = secrets.token_urlsafe(18)
    temporary = ACCESS_FILE.with_name(f".{ACCESS_FILE.name}.{os.getpid()}.new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(code + "\n")
        os.replace(temporary, ACCESS_FILE)
    finally:
        temporary.unlink(missing_ok=True)
    return code


def state():
    catalog = read_json(CATALOG, {"apps": []})
    status = read_json(STATUS, {"apps": []})
    backups = read_json(BACKUPS, [])
    by_slug = {item.get("local_slug"): item for item in status.get("apps", [])}
    backups_by_slug = {}
    for backup in backups if isinstance(backups, list) else []:
        slug = backup.get("addon")
        if isinstance(slug, str):
            backups_by_slug.setdefault(slug, []).append(backup)

    apps = []
    for app in catalog.get("apps", []) if isinstance(catalog, dict) else []:
        if not isinstance(app, dict):
            continue
        slug = app.get("local_slug")
        if not isinstance(slug, str):
            continue
        merged = dict(app)
        merged["status"] = by_slug.get(slug, {})
        merged["backups"] = backups_by_slug.get(slug, [])
        merged["request_pending"] = (REQUESTS / f"{slug}.json").exists()
        apps.append(merged)
    return {"generated_at": catalog.get("generated_at", ""), "apps": apps}


PAGE = r"""<!doctype html>
<html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WebApp-Versionen</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--card:#141b30;--muted:#9eabc8;--line:#293553;--good:#38d39f;--warn:#f8c762;--bad:#ff798b;--blue:#71a7ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#0b1020,#101a31);font:15px system-ui,sans-serif;color:#f4f7ff}main{max-width:1100px;margin:auto;padding:34px 18px 60px}h1{margin:0;font-size:28px}header{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:22px}.hint,.meta{color:var(--muted)}.app{background:rgba(20,27,48,.94);border:1px solid var(--line);border-radius:14px;margin:14px 0;overflow:hidden}.app-head{padding:18px;display:flex;gap:12px;justify-content:space-between;align-items:start}.app-head h2{font-size:18px;margin:0 0 5px}.badge{border:1px solid var(--line);border-radius:999px;padding:4px 9px;font-size:12px;white-space:nowrap}.ok{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}details{border-top:1px solid var(--line)}summary{padding:13px 18px;cursor:pointer;color:var(--blue)}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px 18px;border-top:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}.notes{max-width:420px;white-space:pre-wrap;color:#d3dbed}button{border:0;border-radius:8px;padding:8px 10px;background:#3978e6;color:#fff;font-weight:650;cursor:pointer}button.secondary{background:#263452}button:disabled{opacity:.45;cursor:not-allowed}.notice{margin:16px 0;padding:11px 13px;border-radius:9px;background:#223354;color:#dce9ff}.empty{padding:28px;color:var(--muted)}.login{max-width:470px;margin:50px auto;background:var(--card);border:1px solid var(--line);padding:24px;border-radius:14px}.login input{width:100%;padding:11px;margin:14px 0;background:#0b1020;border:1px solid var(--line);border-radius:8px;color:#fff;font:inherit}@media(max-width:700px){header,.app-head{display:block}.badge{display:inline-block;margin-top:8px}th,td{padding:9px}.notes{max-width:170px}}
</style><body><main><header><div><h1>WebApp-Versionen</h1><div class="hint">Wiederherstellungen sichern zuerst den aktuellen App- und Datenstand.</div></div><button class="secondary" onclick="load()">Aktualisieren</button></header><div id="login" class="login"><h2>Zugangscode</h2><p class="hint">Den Code findest du im Protokoll des WebApp-Updaters in Home Assistant.</p><input id="access" type="password" autocomplete="off" placeholder="Zugangscode"><button onclick="login()">Öffnen</button></div><div id="notice" class="notice" hidden></div><section id="apps"></section></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let access=sessionStorage.getItem('webapp-access')||'';
function login(){access=document.querySelector('#access').value.trim();sessionStorage.setItem('webapp-access',access);load()}
function dataBackup(app,version){return (app.backups||[]).filter(b=>b.from_version===version).at(-1)}
function versionRow(app,v){const st=app.status||{}, installed=st.version===v.version; const backup=dataBackup(app,v.version); const current=st.version||''; const can=v.version!==current && !app.request_pending && !st.job_status && app.local_slug!=='webapp_updater';const action=app.local_slug==='webapp_updater'?'In Home Assistant verwalten':can?`<button onclick='rollback(${JSON.stringify(app.local_slug)},${JSON.stringify(v.version)},false)'>Nur Code</button> ${backup?`<button class="secondary" onclick='rollback(${JSON.stringify(app.local_slug)},${JSON.stringify(v.version)},true)'>Code + Daten</button>`:''}`:'—';return `<tr><td><strong>${esc(v.version)}</strong>${installed?' <span class="ok">installiert</span>':''}</td><td class="notes">${esc(v.notes||'—')}</td><td>${backup?`Gesichert ${esc(backup.created_at||'')}`:'kein passender Datenstand'}</td><td>${action}</td></tr>`}
function appCard(app){const st=app.status||{}, state=st.operation||'bereit';const progress=st.job_stage?` · ${esc(st.job_stage)}${st.job_progress==null?'':` ${esc(st.job_progress)}%`}`:'';const status=st.error?`<span class="bad">${esc(st.error)}</span>`:esc(state)+progress;const versions=(app.versions||[]).map(v=>versionRow(app,v)).join('')||'<tr><td colspan="4">Noch kein Versionsverlauf verfügbar.</td></tr>';const pin=st.pinned_version?`<div class="meta">Angeheftet auf ${esc(st.pinned_version)}. <button class="secondary" onclick='followLatest(${JSON.stringify(app.local_slug)})'>Neueste Version verfolgen</button></div>`:'';return `<article class="app"><div class="app-head"><div><h2>${esc(app.name||app.source||app.local_slug)}</h2><div class="meta">Installiert: ${esc(st.version||'nicht installiert')} · Verfügbar: ${esc(st.latest_version||'—')} · ${status}</div>${pin}</div><span class="badge">${app.request_pending?'Auswahl vorgemerkt':esc(app.local_slug)}</span></div><details><summary>Versionsverlauf und Wiederherstellung</summary><table><thead><tr><th>Version</th><th>Änderungen</th><th>Datenstand</th><th>Aktion</th></tr></thead><tbody>${versions}</tbody></table></details></article>`}
async function request(path,body){const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json','X-WebApp-Access':access},body:JSON.stringify(body)});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||'Aktion konnte nicht vorgemerkt werden.');return d}
async function rollback(slug,version,restore){const detail=restore?'Code und den zugehörigen Datenstand':'nur den App-Code (aktuelle Daten bleiben erhalten; ältere Versionen können mit neueren Daten inkompatibel sein)';if(!confirm(`Version ${version} wiederherstellen: ${detail}? Zuerst wird automatisch ein neuer Wiederherstellungspunkt erstellt.`))return;try{await request('/api/rollback',{slug,version,restore_data:restore});await load()}catch(e){alert(e.message)}}
async function followLatest(slug){if(!confirm('Die App wieder der automatischen Aktualisierung auf die neueste Version folgen lassen?'))return;try{await request('/api/follow-latest',{slug});await load()}catch(e){alert(e.message)}}
async function load(){if(!access)return;try{const r=await fetch('/api/state',{cache:'no-store',headers:{'X-WebApp-Access':access}});if(r.status===401){access='';sessionStorage.removeItem('webapp-access');document.querySelector('#login').hidden=false;document.querySelector('#notice').hidden=true;return}if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();document.querySelector('#login').hidden=true;document.querySelector('#notice').hidden=false;document.querySelector('#notice').textContent=d.generated_at?`Stand: ${d.generated_at}`:'Versionskatalog wird beim nächsten GitHub-Abgleich aufgebaut.';document.querySelector('#apps').innerHTML=(d.apps||[]).map(appCard).join('')||'<div class="empty">Noch keine verwalteten Apps gefunden.</div>'}catch(e){document.querySelector('#notice').textContent='Status konnte nicht geladen werden: '+e.message}}
load();setInterval(load,15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "WebAppUpdater/1"

    def log_message(self, *_args):
        return

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        provided = self.headers.get("X-WebApp-Access", "")
        return bool(ACCESS_CODE) and hmac.compare_digest(provided, ACCESS_CODE)

    def do_GET(self):
        if self.path == "/api/state":
            if not self.authorized():
                return self.send_json({"error": "Zugangscode erforderlich."}, HTTPStatus.UNAUTHORIZED)
            return self.send_json(state())
        if self.path not in ("/", "/index.html"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        body = PAGE.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ("/api/rollback", "/api/follow-latest"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not self.authorized():
            return self.send_json({"error": "Zugangscode erforderlich."}, HTTPStatus.UNAUTHORIZED)
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self.send_json({"error": "JSON erforderlich."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 2 <= length <= 2048:
                raise ValueError
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            return self.send_json({"error": "Ungültige Anfrage."}, HTTPStatus.BAD_REQUEST)
        if not isinstance(request, dict):
            return self.send_json({"error": "Ungültige Anfrage."}, HTTPStatus.BAD_REQUEST)
        slug = request.get("slug")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            return self.send_json({"error": "Ungültige App."}, HTTPStatus.BAD_REQUEST)
        catalog = state()
        app = next((item for item in catalog["apps"] if item.get("local_slug") == slug), None)
        if app is None:
            return self.send_json({"error": "Die App gehört nicht zum verwalteten Versionskatalog."}, HTTPStatus.BAD_REQUEST)
        if app.get("status", {}).get("job_status"):
            return self.send_json({"error": "Für diese App läuft bereits ein Supervisor-Vorgang."}, HTTPStatus.CONFLICT)
        if self.path == "/api/rollback":
            if slug == "webapp_updater":
                return self.send_json({"error": "Der Updater kann seine eigene Version nicht über den Supervisor ändern. Diese App bitte in Home Assistant verwalten."}, HTTPStatus.UNPROCESSABLE_ENTITY)
            version = request.get("version")
            if not isinstance(version, str) or not VERSION.fullmatch(version):
                return self.send_json({"error": "Ungültige Zielversion."}, HTTPStatus.BAD_REQUEST)
            versions = {item.get("version") for item in app.get("versions", [])}
            if version not in versions:
                return self.send_json({"error": "Diese Version ist nicht im geprüften Git-Verlauf vorhanden."}, HTTPStatus.BAD_REQUEST)
            payload = {"action": "rollback", "local_slug": slug, "version": version, "restore_data": request.get("restore_data") is True}
        else:
            payload = {"action": "follow-latest", "local_slug": slug}
        REQUESTS.mkdir(mode=0o700, exist_ok=True)
        request_file = REQUESTS / f"{slug}.json"
        with REQUEST_LOCK:
            if request_file.exists():
                return self.send_json({"error": "Für diese App ist bereits eine Aktion vorgemerkt."}, HTTPStatus.CONFLICT)
            temporary = request_file.with_name(f".{request_file.name}.{secrets.token_hex(8)}.new")
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                os.replace(temporary, request_file)
            finally:
                temporary.unlink(missing_ok=True)
        return self.send_json({"accepted": True}, HTTPStatus.ACCEPTED)


if __name__ == "__main__":
    ACCESS_CODE = load_access_code()
    print(f"[WebApp-Updater] Zugangscode für die Versionsoberfläche: {ACCESS_CODE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8160), Handler).serve_forever()
