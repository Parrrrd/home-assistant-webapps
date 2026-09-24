from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

PORT = int(os.environ.get("VINTED_CARSTEN_INTAKE_PORT", "8159"))
DATA_DIR = Path(os.environ.get("VINTED_CARSTEN_INTAKE_DATA_DIR", "/data/carsten-intake"))
OUTBOX_DIR = DATA_DIR / "outbox"
STATE_FILE = DATA_DIR / "submissions.json"
DRIVE_ENABLED = os.environ.get("VINTED_CARSTEN_DRIVE_ENABLED", "false").strip().lower() == "true"
DRIVE_FOLDER_ID = os.environ.get("VINTED_CARSTEN_DRIVE_FOLDER_ID", "").strip()
DRIVE_SERVICE_ACCOUNT_FILE = Path(
    os.environ.get(
        "VINTED_CARSTEN_DRIVE_SERVICE_ACCOUNT_FILE",
        "/share/Vinted/carsten-google-drive-service-account.json",
    )
)
RETRY_SECONDS = max(30, int(os.environ.get("VINTED_CARSTEN_DRIVE_RETRY_SECONDS", "60")))
MAX_IMAGES = 20
MAX_TOTAL_BYTES = 250 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
STATE_LOCK = threading.RLock()

app = Flask(
    __name__,
    template_folder=str(Path(__file__).with_name("intake") / "templates"),
    static_folder=str(Path(__file__).with_name("intake") / "static"),
    static_url_path="/assets",
)
app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_BYTES
app.secret_key = os.environ.get("VINTED_CARSTEN_INTAKE_SECRET") or os.urandom(32)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)


def _load_state() -> list[dict[str, Any]]:
    with STATE_LOCK:
        try:
            payload = json.loads(STATE_FILE.read_text("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]


def _save_state(items: list[dict[str, Any]]) -> None:
    with STATE_LOCK:
        _atomic_write_json(STATE_FILE, items[-500:])


def _update_submission(submission_id: str, **values: Any) -> None:
    with STATE_LOCK:
        items = _load_state()
        for item in items:
            if str(item.get("submission_id") or "") == submission_id:
                item.update(values)
                item["updated_at"] = _now_iso()
                break
        _save_state(items)


def _clean_text(value: Any, maximum: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:maximum]


def _parse_decimal(value: Any, *, minimum: float = 0.0) -> float:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return 0.0
    number = round(float(text), 2)
    if number < minimum:
        raise ValueError
    return number


def _parse_days(value: Any, default: int) -> int:
    text = str(value or "").strip()
    number = int(text) if text else default
    if number < 1 or number > 3650:
        raise ValueError
    return number


def _validate_images(files: list[Any]) -> list[tuple[Any, str, str]]:
    selected = [item for item in files if item and str(item.filename or "").strip()]
    if not selected:
        raise ValueError("Bitte mindestens ein Foto auswählen.")
    if len(selected) > MAX_IMAGES:
        raise ValueError(f"Maximal {MAX_IMAGES} Fotos sind erlaubt.")
    validated: list[tuple[Any, str, str]] = []
    for index, item in enumerate(selected, 1):
        safe_name = secure_filename(str(item.filename or "")) or f"foto-{index}"
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Foto '{safe_name}' hat ein nicht unterstütztes Format.")
        member = f"images/{index:02d}{suffix}"
        validated.append((item, safe_name, member))
    return validated


def _create_submission_package(form: Any, files: list[Any]) -> tuple[dict[str, Any], Path]:
    notes = _clean_text(form.get("notes"), 5000)
    if not notes:
        raise ValueError("Bitte kurz beschreiben, was verkauft werden soll.")
    try:
        price = _parse_decimal(form.get("price"), minimum=0.01)
        renew_days = _parse_days(form.get("renew_interval_days"), 7)
    except (TypeError, ValueError):
        raise ValueError("Preis und Intervall bitte als gültige Zahlen angeben.") from None

    reduction_enabled = form.get("price_reduction_enabled") == "on"
    reduction_days = 21
    price_drop = 0.0
    min_price = 0.0
    if reduction_enabled:
        try:
            reduction_days = _parse_days(form.get("price_reduction_days"), 21)
            price_drop = _parse_decimal(form.get("price_drop"), minimum=0.01)
            min_price = _parse_decimal(form.get("min_price"), minimum=0.01)
        except (TypeError, ValueError):
            raise ValueError("Für die Preissenkung bitte Tage, Reduzierung und Mindestpreis vollständig angeben.") from None
        if min_price >= price:
            raise ValueError("Der Mindestpreis muss unter dem Startpreis liegen.")

    images = _validate_images(files)
    submission_id = uuid.uuid4().hex
    created_at = _now_iso()
    package_name = f"carsten-vinted-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{submission_id[:8]}.vintake.zip"
    package_path = OUTBOX_DIR / package_name
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    temporary = package_path.with_suffix(package_path.suffix + ".part")

    image_manifest: list[dict[str, str]] = []
    request_payload: dict[str, Any] = {
        "format": "vinted-carsten-intake",
        "version": 1,
        "submission_id": submission_id,
        "source": "carsten",
        "status": "unbearbeitet",
        "created_at": created_at,
        "category": "",
        "category_id": "",
        "item": {
            "notes": notes,
            "brand_hint": _clean_text(form.get("brand_hint"), 200),
            "size_hint": _clean_text(form.get("size_hint"), 200),
            "condition_notes": _clean_text(form.get("condition_notes"), 2000),
            "price": price,
        },
        "automation": {
            "active": True,
            "renew_interval_days": renew_days,
            "price_reduction_enabled": reduction_enabled,
            "price_reduction_days": reduction_days if reduction_enabled else None,
            "price_drop": price_drop if reduction_enabled else None,
            "min_price": min_price if reduction_enabled else None,
        },
        "images": image_manifest,
    }

    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            total_bytes = 0
            for item, original_name, member in images:
                blob = item.read()
                total_bytes += len(blob)
                if total_bytes > MAX_TOTAL_BYTES:
                    raise ValueError("Die Fotos sind zusammen zu groß.")
                archive.writestr(member, blob)
                image_manifest.append({"file": member, "original_name": original_name})
            archive.writestr("request.json", json.dumps(request_payload, ensure_ascii=False, indent=2))
        os.replace(temporary, package_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    state_entry = {
        "submission_id": submission_id,
        "created_at": created_at,
        "updated_at": created_at,
        "package_name": package_name,
        "package_path": str(package_path),
        "summary": notes[:120],
        "price": price,
        "status": "unbearbeitet",
        "transport_status": "lokal gespeichert",
        "drive_file_id": "",
        "last_error": "",
    }
    with STATE_LOCK:
        state = _load_state()
        state.append(state_entry)
        _save_state(state)
    return state_entry, package_path


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _drive_access_token() -> str:
    try:
        credentials = json.loads(DRIVE_SERVICE_ACCOUNT_FILE.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("Servicekonto-Datei wurde nicht gefunden.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Servicekonto-Datei konnte nicht gelesen werden.") from exc

    client_email = str(credentials.get("client_email") or "").strip()
    private_key = str(credentials.get("private_key") or "")
    token_uri = str(credentials.get("token_uri") or "https://oauth2.googleapis.com/token").strip()
    if not client_email or not private_key:
        raise RuntimeError("Servicekonto-Datei ist unvollständig.")

    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64url(
        json.dumps(
            {
                "iss": client_email,
                "scope": "https://www.googleapis.com/auth/drive.file",
                "aud": token_uri,
                "iat": now,
                "exp": now + 3600,
            },
            separators=(",", ":"),
        ).encode()
    )
    unsigned = f"{header}.{claims}".encode("ascii")
    key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
    signature = key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256())
    assertion = f"{header}.{claims}.{_b64url(signature)}"
    body = urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode()
    req = Request(token_uri, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(req, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Google-Authentifizierung ist fehlgeschlagen.") from exc
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Google hat kein Zugriffstoken geliefert.")
    return token


def _upload_package_to_drive(package_path: Path) -> str:
    if not DRIVE_ENABLED:
        raise RuntimeError("Google Drive ist noch nicht aktiviert.")
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("Google-Drive-Ordner ist noch nicht konfiguriert.")
    if not package_path.is_file():
        raise RuntimeError("Lokales Übergabepaket fehlt.")

    token = _drive_access_token()
    boundary = f"vinted-intake-{uuid.uuid4().hex}"
    metadata = json.dumps(
        {"name": package_path.name, "parents": [DRIVE_FOLDER_ID]},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    blob = package_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            metadata,
            b"\r\n",
            f"--{boundary}\r\nContent-Type: application/zip\r\n\r\n".encode(),
            blob,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true&fields=id,name"
    req = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        raise RuntimeError(f"Google-Drive-Upload fehlgeschlagen ({exc.code}). {detail}".strip()) from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Google-Drive-Upload fehlgeschlagen.") from exc
    file_id = str(payload.get("id") or "").strip()
    if not file_id:
        raise RuntimeError("Google Drive hat keine Datei-ID geliefert.")
    return file_id


def _try_transport(submission_id: str, package_path: Path, *, quiet: bool = False) -> bool:
    if not DRIVE_ENABLED or not DRIVE_FOLDER_ID:
        _update_submission(
            submission_id,
            transport_status="lokal gespeichert",
            last_error="Google Drive ist noch nicht vollständig konfiguriert.",
        )
        return False
    try:
        drive_file_id = _upload_package_to_drive(package_path)
    except Exception as exc:
        _update_submission(submission_id, transport_status="wartet auf Drive", last_error=str(exc)[:1000])
        if not quiet:
            app.logger.warning("Carsten intake Drive upload failed: %s", exc)
        return False
    _update_submission(
        submission_id,
        transport_status="an Google Drive übertragen",
        drive_file_id=drive_file_id,
        last_error="",
        drive_uploaded_at=_now_iso(),
    )
    return True


def _retry_worker() -> None:
    while True:
        time.sleep(RETRY_SECONDS)
        if not DRIVE_ENABLED or not DRIVE_FOLDER_ID:
            continue
        try:
            for item in _load_state():
                if str(item.get("drive_file_id") or "").strip():
                    continue
                submission_id = str(item.get("submission_id") or "").strip()
                package_path = Path(str(item.get("package_path") or ""))
                if submission_id and package_path.is_file():
                    _try_transport(submission_id, package_path, quiet=True)
        except Exception:
            app.logger.exception("Carsten intake retry worker failed")


@app.get("/")
def index():
    recent = list(reversed(_load_state()))[:8]
    return render_template(
        "index.html",
        recent=recent,
        drive_configured=bool(DRIVE_ENABLED and DRIVE_FOLDER_ID),
        max_images=MAX_IMAGES,
    )


@app.post("/submit")
def submit():
    try:
        state_entry, package_path = _create_submission_package(request.form, request.files.getlist("photos"))
        uploaded = _try_transport(str(state_entry["submission_id"]), package_path)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))
    except Exception as exc:
        app.logger.exception("Carsten intake submission failed")
        flash(f"Die Einreichung konnte nicht gespeichert werden: {exc}", "error")
        return redirect(url_for("index"))
    if uploaded:
        flash("Artikel gespeichert und an Patrick übergeben.", "success")
    else:
        flash("Artikel ist sicher gespeichert und wird automatisch an Patrick übertragen, sobald Google Drive verfügbar ist.", "success")
    return redirect(url_for("index"))


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "vinted-carsten-intake",
        "drive_configured": bool(DRIVE_ENABLED and DRIVE_FOLDER_ID),
    }


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_retry_worker, name="carsten-drive-retry", daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
