from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


APP_SLUG = "vinted_carsten_erfassung"
APP_NAME = "Carstens Vinted Importeur"
DATA_DIR = Path(os.environ.get("VINTED_CARSTEN_DATA_DIR", "/data"))
CONFIG_DIR = Path(os.environ.get("VINTED_CARSTEN_CONFIG_DIR", "/config"))
OUTBOX_DIR = DATA_DIR / "outbox"
OPTIONS_FILE = DATA_DIR / "options.json"
DEFAULT_CREDENTIAL_FILE = CONFIG_DIR / "drive-service-account.json"
LEGACY_CREDENTIAL_PATH = "/data/drive-service-account.json"
MAX_PHOTOS = 12
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", uuid.uuid4().hex)
app.config.update(MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES, SESSION_COOKIE_SAMESITE="Lax")
_delivery_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def package_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def atomic_json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def runtime_options() -> dict[str, Any]:
    options = read_json(OPTIONS_FILE, {})
    return options if isinstance(options, dict) else {}


def text_value(name: str, limit: int = 500) -> str:
    return " ".join(request.form.get(name, "").strip().split())[:limit]


def optional_number(name: str, minimum: float = 0) -> float | None:
    raw = request.form.get(name, "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} muss eine Zahl sein.") from error
    if value < minimum:
        raise ValueError(f"{name} ist zu klein.")
    return round(value, 2)


def optional_days(name: str, default: int) -> int | None:
    raw = request.form.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} muss eine ganze Zahl sein.") from error
    if not 1 <= value <= 365:
        raise ValueError(f"{name} muss zwischen 1 und 365 liegen.")
    return value


def photo_files() -> list[FileStorage]:
    files = [photo for photo in request.files.getlist("photos") if photo and photo.filename]
    if not files:
        raise ValueError("Bitte mindestens ein Foto auswählen.")
    if len(files) > MAX_PHOTOS:
        raise ValueError(f"Bitte höchstens {MAX_PHOTOS} Fotos auswählen.")

    order = request.form.getlist("photo_order")
    if order:
        try:
            positions = [int(value) for value in order]
        except ValueError as error:
            raise ValueError("Die Foto-Reihenfolge ist ungültig.") from error
        if sorted(positions) != list(range(len(files))):
            raise ValueError("Die Foto-Reihenfolge ist unvollständig.")
        files = [files[position] for position in positions]

    for photo in files:
        extension = Path(secure_filename(photo.filename)).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS or not (photo.mimetype or "").startswith("image/"):
            raise ValueError("Erlaubt sind nur JPG, PNG, WebP, HEIC und HEIF-Fotos.")
    return files


def build_request(item_id: str, photos: list[dict[str, Any]]) -> dict[str, Any]:
    relist_enabled = request.form.get("relist_enabled") == "on"
    reduction_enabled = request.form.get("reduction_enabled") == "on"
    reduction_amount = optional_number("reduction_amount", 0.01) if reduction_enabled else None
    reduction_minimum = optional_number("reduction_minimum", 0) if reduction_enabled else None
    if reduction_enabled and reduction_amount is None:
        reduction_amount = 2.0

    return {
        "format": "vintake",
        "version": "1.0",
        "source": {
            "app": APP_SLUG,
            "submission_id": item_id,
            "created_at": utc_now(),
        },
        "status": {
            "state": "ready_for_transfer",
            "updated_at": utc_now(),
        },
        "item": {
            "description": text_value("description", 600),
            "brand": text_value("brand", 120),
            "size": text_value("size", 80),
            "condition_notes": text_value("condition_notes", 240),
            "desired_price": optional_number("desired_price", 0),
            "category": "",
            "category_id": "",
            "photos": photos,
        },
        "automation": {
            "relist_interval_days": optional_days("relist_interval_days", 7) if relist_enabled else None,
            "price_reduction": {
                "enabled": reduction_enabled,
                "after_days": optional_days("reduction_after_days", 14) if reduction_enabled else None,
                "amount": reduction_amount,
                "minimum_price": reduction_minimum,
            },
        },
    }


def state_path(submission_dir: Path) -> Path:
    return submission_dir / "state.json"


def create_archive(submission_dir: Path, archive_name: str) -> Path:
    archive = submission_dir / archive_name
    temporary = archive.with_suffix(".zip.new")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(submission_dir / "request.json", "request.json")
        for photo in sorted((submission_dir / "images").iterdir()):
            if photo.is_file():
                bundle.write(photo, f"images/{photo.name}")
    temporary.replace(archive)
    return archive


def store_submission() -> tuple[Path, dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    submission_id = uuid.uuid4().hex[:12]
    submission_dir = OUTBOX_DIR / submission_id
    images_dir = submission_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=False)
    try:
        photos: list[dict[str, Any]] = []
        for position, photo in enumerate(photo_files(), start=1):
            extension = Path(secure_filename(photo.filename)).suffix.lower()
            filename = f"photo-{position:02d}{extension}"
            target = images_dir / filename
            photo.save(target)
            if not target.exists() or target.stat().st_size == 0:
                raise ValueError("Ein Foto konnte nicht sicher gespeichert werden.")
            photos.append({"filename": filename, "position": position})

        payload = build_request(submission_id, photos)
        atomic_json_write(submission_dir / "request.json", payload)
        archive_name = f"carsten-vinted-{package_timestamp()}-{submission_id}.vintake.zip"
        archive = create_archive(submission_dir, archive_name)
        state = {
            "state": "waiting",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "archive": archive.name,
            "attempts": 0,
            "last_error": "",
            "drive_file_id": "",
        }
        atomic_json_write(state_path(submission_dir), state)
        return submission_dir, state
    except Exception:
        shutil.rmtree(submission_dir, ignore_errors=True)
        raise


def drive_configuration() -> tuple[str, Path]:
    options = runtime_options()
    folder_id = str(options.get("drive_folder_id", "")).strip()
    credential_name = str(options.get("drive_service_account_file", DEFAULT_CREDENTIAL_FILE)).strip()

    if not folder_id or not re.fullmatch(r"[A-Za-z0-9_-]+", folder_id):
        raise RuntimeError("Google-Drive-Ordner-ID fehlt oder ist ungültig.")

    if not credential_name or credential_name == LEGACY_CREDENTIAL_PATH:
        credentials = DEFAULT_CREDENTIAL_FILE
    else:
        credentials = Path(credential_name)

    try:
        credentials.resolve().relative_to(CONFIG_DIR.resolve())
    except (OSError, ValueError) as error:
        raise RuntimeError("Die Credential-Datei muss sicher unter /config liegen.") from error

    if not credentials.is_file():
        raise RuntimeError("Die lokale Google-Drive-Credential-Datei fehlt.")

    return folder_id, credentials


def google_drive_service(credentials_file: Path) -> Any:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=[DRIVE_SCOPE]
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def deliver_submission(submission_dir: Path) -> bool:
    state = read_json(state_path(submission_dir), {})
    if not isinstance(state, dict) or state.get("state") == "delivered":
        return True
    archive = submission_dir / str(state.get("archive", ""))
    if not archive.is_file():
        return False
    state["attempts"] = int(state.get("attempts", 0)) + 1
    state["updated_at"] = utc_now()
    try:
        folder_id, credentials_file = drive_configuration()
        drive = google_drive_service(credentials_file)
        escaped_name = archive.name.replace("'", "\\'")
        existing = drive.files().list(
            q=f"'{folder_id}' in parents and name = '{escaped_name}' and trashed = false",
            spaces="drive",
            fields="files(id,name)",
        ).execute().get("files", [])
        if existing:
            drive_file_id = existing[0]["id"]
        else:
            from googleapiclient.http import MediaFileUpload

            uploaded = drive.files().create(
                body={"name": archive.name, "parents": [folder_id], "mimeType": "application/zip"},
                media_body=MediaFileUpload(str(archive), mimetype="application/zip", resumable=True),
                fields="id",
            ).execute()
            drive_file_id = uploaded["id"]
        state.update({"state": "delivered", "updated_at": utc_now(), "last_error": "", "drive_file_id": drive_file_id})
        atomic_json_write(state_path(submission_dir), state)
        return True
    except Exception as error:  # Kept locally; the worker retries without losing the package.
        state.update({"state": "waiting", "updated_at": utc_now(), "last_error": str(error)[:300]})
        atomic_json_write(state_path(submission_dir), state)
        return False


def pending_submissions() -> list[Path]:
    if not OUTBOX_DIR.is_dir():
        return []
    return sorted((path for path in OUTBOX_DIR.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)


def retry_pending() -> None:
    if not _delivery_lock.acquire(blocking=False):
        return
    try:
        for submission_dir in pending_submissions():
            state = read_json(state_path(submission_dir), {})
            if isinstance(state, dict) and state.get("state") != "delivered":
                deliver_submission(submission_dir)
    finally:
        _delivery_lock.release()


def retry_worker() -> None:
    while True:
        retry_pending()
        try:
            minutes = int(runtime_options().get("retry_interval_minutes", 5))
        except (TypeError, ValueError):
            minutes = 5
        time.sleep(max(60, min(minutes, 60) * 60))


def recent_submissions(limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for submission_dir in reversed(pending_submissions()):
        payload = read_json(submission_dir / "request.json", {})
        state = read_json(state_path(submission_dir), {})
        if not isinstance(payload, dict) or not isinstance(state, dict):
            continue
        item = payload.get("item", {})
        source = payload.get("source", {})
        rows.append({
            "created_at": source.get("created_at", ""),
            "description": item.get("description", "") or "Fotos ohne Beschreibung",
            "price": item.get("desired_price"),
            "photos": len(item.get("photos", [])),
            "status": state.get("state", "waiting"),
            "error": state.get("last_error", ""),
        })
        if len(rows) >= limit:
            break
    return rows


@app.get("/")
def index() -> str:
    return render_template("index.html", recent=recent_submissions(), max_photos=MAX_PHOTOS)


@app.post("/submit")
def submit() -> Any:
    try:
        submission_dir, _state = store_submission()
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("index"))
    except Exception:
        app.logger.exception("Lokales Übergabepaket konnte nicht gespeichert werden")
        flash("Die Abgabe konnte nicht sicher lokal gespeichert werden.", "error")
        return redirect(url_for("index"))

    delivered = deliver_submission(submission_dir)
    flash("Übergeben." if delivered else "Gespeichert – Übergabe wartet.", "success" if delivered else "waiting")
    return redirect(url_for("index"))


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=retry_worker, name="drive-retry", daemon=True).start()
    app.run(host="0.0.0.0", port=8159, debug=False)
