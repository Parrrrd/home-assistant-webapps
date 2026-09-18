import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

VERSION = "0.3.7"
TARGET_ROOT = Path("/share")
STATE_FILE = Path("/data/webapp_sync_manager_state.json")
DRIVE_ROOT_FOLDER_ID = os.environ.get("WEBAPP_DRIVE_FOLDER_ID", "").strip()
SERVICE_ACCOUNT_FILE = os.environ.get(
    "WEBAPP_SERVICE_ACCOUNT",
    "/share/Kleinanzeigen/google-drive-service-account.json",
).strip()
POLL_SECONDS = max(1, int(os.environ.get("WEBAPP_POLL", "60")))

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."

HA_NOTIFY_URL = (
    "http://supervisor/core/api/services/"
    "notify/mobile_app_iphone_primary"
)

app = Flask(__name__)
state_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    print(f"[webapp-sync] {message}", flush=True)


def safe_component(name):
    # Drive-Namen dürfen niemals aus /share ausbrechen.
    cleaned = str(name).replace("/", "_").replace("\\", "_").strip()
    if cleaned in {"", ".", ".."}:
        cleaned = "_"
    return cleaned


def default_state():
    return {
        "version": VERSION,
        "last_check": None,
        "status": "starting",
        "drive_root_folder_id": DRIVE_ROOT_FOLDER_ID,
        "target_root": str(TARGET_ROOT),
        "poll_seconds": POLL_SECONDS,
        "downloaded": [],
        "unchanged": [],
        "skipped": [],
        "errors": [],
        "files": {},
    }


def load_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_state()
        data["version"] = VERSION
        data.setdefault("files", {})
        return data
    except Exception:
        return default_state()


def save_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def drive_session():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return AuthorizedSession(creds)


def list_children(session, folder_id):
    files = []
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "spaces": "drive",
            "orderBy": "name",
            "pageSize": 1000,
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,md5Checksum)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        files.extend(payload.get("files", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return files


def walk_drive(session):
    """Yield only the newest ZIP directly inside each first-level topic folder.

    The configured Drive root itself is only a container and is not mirrored.
    For every direct first-level topic folder, only ZIP files that are direct
    children of that topic are considered. Of those, the file with the newest
    Google Drive ``modifiedTime`` is selected.

    Example:
      Drive/WebApp/Amazon/old.zip
      Drive/WebApp/Amazon/new.zip   -> /share/Amazon/new.zip

    Root-level files, non-ZIP files and deeper subfolders are ignored.
    """
    root_items = list_children(session, DRIVE_ROOT_FOLDER_ID)

    for topic in root_items:
        if topic.get("mimeType") != DRIVE_FOLDER_MIME:
            continue

        topic_name = safe_component(topic.get("name", "_"))
        candidates = []
        for item in list_children(session, topic["id"]):
            name = safe_component(item.get("name", "_"))
            mime = item.get("mimeType", "")

            # Never recurse below the first topic level.
            if mime == DRIVE_FOLDER_MIME:
                continue

            # This sync manager is intentionally ZIP-only.
            if not name.lower().endswith(".zip"):
                continue

            candidates.append((item, name))

        if not candidates:
            continue

        # Drive modifiedTime is RFC3339. Lexicographic ordering is safe for the
        # canonical timestamps returned by the Drive API. Add name/id as stable
        # tie-breakers so the selected file is deterministic.
        item, name = max(
            candidates,
            key=lambda pair: (
                pair[0].get("modifiedTime") or "",
                pair[1].lower(),
                pair[0].get("id") or "",
            ),
        )
        yield item, Path(topic_name) / name


def download_file(session, item, relative_path):
    target = TARGET_ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)

    response = session.get(
        f"{DRIVE_FILES_URL}/{item['id']}",
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=120,
        stream=True,
    )
    response.raise_for_status()

    temp = target.with_name(f".{target.name}.webapp-sync-{os.getpid()}.part")
    sha256 = hashlib.sha256()
    size = 0
    try:
        with temp.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                sha256.update(chunk)
                size += len(chunk)
        os.replace(temp, target)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except Exception:
            pass

    return target, size, sha256.hexdigest()


def local_md5(path):
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def notify_transfer(target):
    """Push erst nach erfolgreichem Schreiben unter /share auslösen."""
    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HASSIO_TOKEN")

    if not token:
        log("Push nicht möglich: Kein Home-Assistant-Token vorhanden.")
        return False

    try:
        relative = target.relative_to(TARGET_ROOT)
        parent = relative.parent.as_posix()
        destination = "/share" if parent == "." else f"/share/{parent}"

        payload = json.dumps(
            {
                "title": "WebApp Sync Manager",
                "message": f"{target.name} wurde nach {destination} übertragen.",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            HA_NOTIFY_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status

        if 200 <= status < 300:
            log(f"Push gesendet: {target.name}")
            return True

        log(f"Push fehlgeschlagen: HTTP {status}")
        return False

    except urllib.error.HTTPError as exc:
        log(f"Push fehlgeschlagen: HTTP {exc.code}")
        return False
    except Exception as exc:
        log(f"Push fehlgeschlagen: {exc}")
        return False


def should_download(item, relative_path, previous):
    target = TARGET_ROOT / relative_path
    old = previous.get(item["id"], {})

    if not target.exists():
        return True

    try:
        drive_size = int(item.get("size", -1))
        local_size = target.stat().st_size
    except Exception:
        return True

    metadata_unchanged = (
        old.get("relative_path") == relative_path.as_posix()
        and old.get("modifiedTime") == item.get("modifiedTime")
        and old.get("md5Checksum") == item.get("md5Checksum")
        and (drive_size < 0 or local_size == drive_size)
    )

    if metadata_unchanged:
        return False

    drive_md5 = item.get("md5Checksum")
    if drive_md5 and drive_size >= 0 and local_size == drive_size:
        try:
            if local_md5(target).lower() == drive_md5.lower():
                return False
        except Exception as exc:
            log(f"Lokaler MD5-Vergleich fehlgeschlagen: {exc}")

    return True


def sync_drive_once():
    with state_lock:
        state = load_state()
        state.update(
            {
                "version": VERSION,
                "last_check": now_iso(),
                "drive_root_folder_id": DRIVE_ROOT_FOLDER_ID,
                "target_root": str(TARGET_ROOT),
                "poll_seconds": POLL_SECONDS,
                "downloaded": [],
                "unchanged": [],
                "skipped": [],
                "errors": [],
            }
        )

        if not DRIVE_ROOT_FOLDER_ID:
            state["status"] = "waiting_for_drive_folder_id"
            save_state(state)
            log("Warte auf google_drive_folder_id.")
            return

        if not SERVICE_ACCOUNT_FILE or not Path(SERVICE_ACCOUNT_FILE).exists():
            state["status"] = "waiting_for_service_account"
            state["errors"].append(f"Datei fehlt: {SERVICE_ACCOUNT_FILE}")
            save_state(state)
            log(f"Service-Account-Datei fehlt: {SERVICE_ACCOUNT_FILE}")
            return

        previous = state.get("files", {})
        current = {}

        try:
            session = drive_session()
            seen_count = 0
            for item, relative_path in walk_drive(session):
                seen_count += 1
                mime = item.get("mimeType", "")
                rel = relative_path.as_posix()

                # walk_drive liefert ausschließlich direkte ZIP-Dateien aus
                # den Themenordnern. Google-native Dateien gelangen hier nicht hinein.
                if mime.startswith(GOOGLE_NATIVE_PREFIX):
                    state["skipped"].append(
                        {"path": rel, "reason": "google_native_file"}
                    )
                    continue

                try:
                    if should_download(item, relative_path, previous):
                        target, size, sha256 = download_file(session, item, relative_path)
                        state["downloaded"].append(rel)
                        log(f"Übertragen: Drive/{rel} -> {target}")
                        notify_transfer(target)
                    else:
                        target = TARGET_ROOT / relative_path
                        size = target.stat().st_size
                        sha256 = previous.get(item["id"], {}).get("sha256")
                        state["unchanged"].append(rel)

                    current[item["id"]] = {
                        "name": item.get("name"),
                        "relative_path": rel,
                        "modifiedTime": item.get("modifiedTime"),
                        "md5Checksum": item.get("md5Checksum"),
                        "size": size,
                        "sha256": sha256,
                        "last_seen": now_iso(),
                    }
                except Exception as exc:
                    msg = f"{rel}: {exc}"
                    state["errors"].append(msg)
                    log(f"Fehler bei {msg}")

            state["files"] = current
            if state["errors"]:
                state["status"] = "completed_with_errors"
            elif state["downloaded"]:
                state["status"] = "synced"
            elif seen_count:
                state["status"] = "up_to_date"
            else:
                state["status"] = "no_files_in_topic_folders"

        except Exception as exc:
            state["status"] = "error"
            state["errors"].append(str(exc))
            log(f"Sync fehlgeschlagen: {exc}")

        save_state(state)


def worker():
    while True:
        sync_drive_once()
        time.sleep(POLL_SECONDS)


@app.route("/")
def index():
    with state_lock:
        return jsonify(load_state())


@app.route("/sync", methods=["POST", "GET"])
def sync_now():
    # Manuelles Anstoßen ist nur ein Komfort-Endpunkt; der Poller läuft weiterhin.
    sync_drive_once()
    with state_lock:
        return jsonify(load_state())


threading.Thread(target=worker, daemon=True).start()
app.run(host="0.0.0.0", port=8155)
