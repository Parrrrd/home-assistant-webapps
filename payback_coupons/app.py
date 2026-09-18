
import json
import os
import re
import shutil
import uuid
from datetime import datetime, date
from io import BytesIO
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, send_from_directory, url_for
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from werkzeug.utils import secure_filename

try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:
    zbar_decode = None

try:
    import barcode
    from barcode.writer import ImageWriter
except Exception:
    barcode = None
    ImageWriter = None


APP_PORT = int(os.environ.get("PORT", "8141"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_FILE = DATA_DIR / "coupons.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
BACKUP_DIR = DATA_DIR / "backups"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "heic", "heif"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "payback-coupons-local-secret")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

DEFAULT_SETTINGS = {
    "account_a": "Hauptprofil PAYBACK",
    "account_b": "Zweitprofil PAYBACK",
    "current_edeka_account": "a",
    "auto_delete_finished": True,
    "default_sort": "expires_first",
}


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        save_coupons([])
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS.copy())


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


def backup_file(path: Path):
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(path, BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}")
    except Exception:
        pass


def load_settings():
    settings = DEFAULT_SETTINGS.copy()
    stored = load_json(SETTINGS_FILE, {})
    if isinstance(stored, dict):
        settings.update(stored)
    if settings.get("account_a") in {"Mein PAYBACK", "Mein Payback"}:
        settings["account_a"] = "Hauptprofil PAYBACK"
    if settings.get("account_b") in {"Frau PAYBACK", "Frau Payback"}:
        settings["account_b"] = "Zweitprofil PAYBACK"
    if settings.get("current_edeka_account") not in {"a", "b"}:
        settings["current_edeka_account"] = "a"
    settings["auto_delete_finished"] = bool(settings.get("auto_delete_finished", True))
    return settings


def save_settings(settings):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_barcode_text(value: str) -> str:
    value = (value or "").strip()
    digits = re.sub(r"\D+", "", value)
    return digits or value


def normalize_start_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    # Alte Einträge aus v0.1.10 können noch datetime-local Werte enthalten.
    # Für den Start reicht ab jetzt immer nur das Datum.
    return value[:10]


def parse_date_value(value: str):
    value = normalize_start_date(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def normalize_coupon(coupon):
    redeemed = coupon.get("redeemed") or {}
    redeemed_at = coupon.get("redeemed_at") or {}
    return {
        "id": coupon.get("id") or str(uuid.uuid4()),
        "title": coupon.get("title") or "PAYBACK Coupon",
        "description": coupon.get("description") or "",
        "partner": coupon.get("partner") or "",
        "value": coupon.get("value") or "",
        "starts_at": normalize_start_date(coupon.get("starts_at") or ""),
        "expires_at": coupon.get("expires_at") or "",
        "image": coupon.get("image") or "",
        "barcode_number": normalize_barcode_text(coupon.get("barcode_number") or ""),
        "barcode_scan_attempted": bool(coupon.get("barcode_scan_attempted", False)),
        "created_at": coupon.get("created_at") or now_iso(),
        "updated_at": coupon.get("updated_at") or now_iso(),
        "notes": coupon.get("notes") or "",
        "redeemed": {
            "a": bool(redeemed.get("a", False)),
            "b": bool(redeemed.get("b", False)),
        },
        "redeemed_at": {
            "a": redeemed_at.get("a") or "",
            "b": redeemed_at.get("b") or "",
        },
    }


def load_coupons():
    # Beim normalen Seitenaufruf nicht mehr automatisch alle Bilder scannen.
    # Ein einzelnes problematisches Foto konnte sonst die komplette Webapp blockieren.
    raw = load_json(DATA_FILE, [])
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(normalize_coupon(item))
    return result


def save_coupons(coupons):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(coupons, ensure_ascii=False, indent=2), encoding="utf-8")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return ""
    if not allowed_file(file_storage.filename):
        raise ValueError("Dateityp nicht unterstützt. Bitte PNG, JPG, WEBP oder HEIC verwenden.")
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[1].lower()
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.{ext}"
    file_storage.save(UPLOAD_DIR / filename)
    return filename


def delete_image(filename):
    if not filename:
        return
    path = UPLOAD_DIR / filename
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass


def get_font(size, bold=False):
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def image_variants(img):
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    # Große iPhone-Fotos vor dem Barcode-Scan verkleinern.
    max_side = 1600
    if max(rgb.size) > max_side:
        rgb.thumbnail((max_side, max_side))
    gray = ImageOps.grayscale(rgb)
    w, h = gray.size
    crops = [
        rgb,
        rgb.rotate(90, expand=True),
        rgb.rotate(270, expand=True),
        gray,
        ImageOps.autocontrast(gray),
        gray.filter(ImageFilter.SHARPEN),
        gray.crop((0, int(h * 0.35), w, h)),
        gray.crop((0, int(h * 0.45), w, h)),
        gray.crop((int(w * 0.05), int(h * 0.35), int(w * 0.95), h)),
        gray.crop((int(w * 0.10), int(h * 0.45), int(w * 0.90), int(h * 0.95))),
    ]
    for item in crops:
        yield item
        try:
            yield ImageOps.autocontrast(item)
        except Exception:
            pass
        try:
            if item.mode != "L":
                item_gray = ImageOps.grayscale(item)
            else:
                item_gray = item
            yield ImageOps.invert(ImageOps.autocontrast(item_gray))
        except Exception:
            pass


def extract_barcode_number(filename):
    if not filename or zbar_decode is None:
        return ""
    path = UPLOAD_DIR / filename
    if not path.exists():
        return ""
    try:
        img = Image.open(path)
    except Exception:
        return ""

    found = []
    for idx, variant in enumerate(image_variants(img)):
        if idx >= 12:
            break
        try:
            decoded = zbar_decode(variant)
        except Exception:
            decoded = []
        for result in decoded:
            try:
                raw = result.data.decode("utf-8", errors="ignore").strip()
            except Exception:
                raw = ""
            clean = normalize_barcode_text(raw)
            if clean:
                found.append(clean)
        if found:
            break

    if not found:
        return ""
    found.sort(key=lambda x: (len(re.sub(r"\D+", "", x)), len(x)), reverse=True)
    return found[0]


def ensure_barcode_for_coupon(coupon):
    if coupon.get("image") and not coupon.get("barcode_number") and not coupon.get("barcode_scan_attempted"):
        coupon["barcode_scan_attempted"] = True
        try:
            detected = extract_barcode_number(coupon.get("image"))
        except Exception:
            detected = ""
        if detected:
            coupon["barcode_number"] = detected
        return coupon, True
    return coupon, False


def generate_barcode_image(code_value):
    code_value = normalize_barcode_text(code_value)
    if not code_value or barcode is None or ImageWriter is None:
        return None
    try:
        code128 = barcode.get("code128", code_value, writer=ImageWriter())
        buffer = BytesIO()
        code128.write(buffer, options={
            "module_width": 0.32,
            "module_height": 36.0,
            "quiet_zone": 3.0,
            "font_size": 0,
            "text_distance": 1,
            "dpi": 300,
            "write_text": False,
            "background": "white",
            "foreground": "black",
        })
        buffer.seek(0)
        return Image.open(buffer).convert("RGB")
    except Exception:
        return None


def fit_image(image, max_w, max_h):
    image = image.copy()
    image.thumbnail((max_w, max_h))
    return image


def fallback_barcode_crop(filename):
    if not filename:
        return None
    path = UPLOAD_DIR / filename
    if not path.exists():
        return None
    try:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        w, h = img.size
        crop = img.crop((0, int(h * 0.40), w, h))
        crop = ImageOps.autocontrast(crop)
        return crop
    except Exception:
        return None


def trim_white_borders(image, padding=0):
    try:
        gray = ImageOps.grayscale(image)
        inv = ImageOps.invert(gray)
        bbox = inv.getbbox()
        if not bbox:
            return image
        left, top, right, bottom = bbox
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(image.width, right + padding)
        bottom = min(image.height, bottom + padding)
        return image.crop((left, top, right, bottom))
    except Exception:
        return image


def render_barcode_card(coupon):
    width, height = 1400, 620
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    border = "#d7e3f3"
    dark = "#10243e"
    muted = "#62748a"
    light = "#f4f8ff"

    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=34, fill="white", outline=border, width=4)
    draw.rounded_rectangle((72, 88, width - 72, height - 88), radius=28, fill=light, outline=border, width=3)

    code = normalize_barcode_text(coupon.get("barcode_number") or "")
    if code:
        barcode_img = generate_barcode_image(code)
        if barcode_img is not None:
            barcode_img = trim_white_borders(barcode_img, padding=4)
            target_w = width - 210
            scale = target_w / max(1, barcode_img.width)
            target_h = max(120, int(barcode_img.height * scale))
            barcode_img = barcode_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            bx = int((width - barcode_img.width) / 2)
            by = 140
            canvas.paste(barcode_img, (bx, by))
            font_code = get_font(40, bold=False)
            bbox = draw.textbbox((0, 0), code, font=font_code)
            draw.text(((width - (bbox[2] - bbox[0])) / 2, by + barcode_img.height + 18), code, fill=dark, font=font_code)
        else:
            draw.text((220, 290), "Barcode konnte nicht erzeugt werden", fill=muted, font=get_font(44, bold=True))
    else:
        crop = fallback_barcode_crop(coupon.get("image") or "")
        if crop is not None:
            crop = trim_white_borders(crop, padding=2)
            crop = fit_image(crop, width - 210, 300)
            canvas.paste(crop, (int((width - crop.width) / 2), 160))
            draw.text((150, 118), "Barcode noch nicht erkannt – bitte Nummer unten eintragen.", fill=muted, font=get_font(30))
        else:
            draw.text((390, 286), "Kein Barcode vorhanden", fill=muted, font=get_font(48, bold=True))

    return canvas

def find_coupon(coupons, coupon_id):
    for idx, coupon in enumerate(coupons):
        if coupon.get("id") == coupon_id:
            return idx, coupon
    return None, None


def completion_state(coupon):
    a = coupon.get("redeemed", {}).get("a", False)
    b = coupon.get("redeemed", {}).get("b", False)
    if a and b:
        return "done"
    if a or b:
        return "partial"
    return "open"


def is_expired(coupon):
    value = coupon.get("expires_at") or ""
    if not value:
        return False
    try:
        return date.fromisoformat(value) < date.today()
    except Exception:
        return False


def days_left(coupon):
    value = coupon.get("expires_at") or ""
    if not value:
        return None
    try:
        return (date.fromisoformat(value) - date.today()).days
    except Exception:
        return None


def is_future_start(coupon):
    start = parse_date_value(coupon.get("starts_at") or "")
    return bool(start and start > date.today())


def sort_coupons(coupons, sort_key):
    # Noch nicht gestartete Coupons bleiben sichtbar, kommen aber ans Ende.
    def future_bucket(c):
        return 1 if is_future_start(c) else 0

    if sort_key == "newest":
        return sorted(coupons, key=lambda c: (future_bucket(c), c.get("created_at", "")), reverse=False)
    if sort_key == "partner":
        return sorted(coupons, key=lambda c: (future_bucket(c), (c.get("partner") or "zzzz").lower(), c.get("title", "").lower()))
    def key(c):
        return (future_bucket(c), c.get("expires_at") or "9999-12-31", c.get("created_at", ""))
    return sorted(coupons, key=key)


def filter_coupons(coupons, q, status, account_filter):
    q = (q or "").strip().lower()
    status = (status or "active").strip().lower()
    result = []
    for coupon in coupons:
        expired = is_expired(coupon)
        text = " ".join([
            coupon.get("title", ""),
            coupon.get("description", ""),
            coupon.get("partner", ""),
            coupon.get("value", ""),
            coupon.get("starts_at", ""),
            coupon.get("notes", ""),
            coupon.get("barcode_number", ""),
        ]).lower()
        if q and q not in text:
            continue

        state = completion_state(coupon)
        if status == "active":
            if expired:
                continue
        elif status == "expired":
            if not expired:
                continue
        elif status == "all":
            pass
        else:
            if expired or state != status:
                continue

        redeemed = coupon.get("redeemed", {})
        if account_filter == "a_open" and redeemed.get("a"):
            continue
        if account_filter == "b_open" and redeemed.get("b"):
            continue
        if account_filter == "a_done" and not redeemed.get("a"):
            continue
        if account_filter == "b_done" and not redeemed.get("b"):
            continue
        result.append(coupon)
    return result


def stats_for(coupons):
    active_coupons = [c for c in coupons if not is_expired(c)]
    return {
        "active": len(active_coupons),
        "total": len(coupons),
        "open": sum(1 for c in active_coupons if completion_state(c) == "open"),
        "partial": sum(1 for c in active_coupons if completion_state(c) == "partial"),
        "done": sum(1 for c in active_coupons if completion_state(c) == "done"),
        "expired": sum(1 for c in coupons if is_expired(c)),
    }


@app.template_filter("date_de")
def date_de(value):
    if not value:
        return "—"
    try:
        return date.fromisoformat(value[:10]).strftime("%d.%m.%Y")
    except Exception:
        return value


@app.template_filter("short_date_de")
def short_date_de(value):
    if not value:
        return "—"
    try:
        return date.fromisoformat(value[:10]).strftime("%d.%m.")
    except Exception:
        return value


@app.template_filter("datetime_de")
def datetime_de(value):
    if not value:
        return "—"
    try:
        return date.fromisoformat(normalize_start_date(value)).strftime("%d.%m.%Y")
    except Exception:
        return value


@app.template_filter("start_short_de")
def start_short_de(value):
    if not value:
        return "—"
    try:
        return date.fromisoformat(normalize_start_date(value)).strftime("%d.%m.")
    except Exception:
        return value


@app.context_processor
def inject_helpers():
    return {
        "settings": load_settings(),
        "completion_state": completion_state,
        "is_expired": is_expired,
        "days_left": days_left,
        "is_future_start": is_future_start,
    }


@app.route("/")
def index():
    ensure_dirs()
    settings = load_settings()
    coupons = load_coupons()
    q = request.args.get("q", "")
    status = request.args.get("status", "active")
    account_filter = request.args.get("account", "all")
    sort_key = request.args.get("sort", settings.get("default_sort", "expires_first"))
    visible = sort_coupons(filter_coupons(coupons, q, status, account_filter), sort_key)
    return render_template("index.html", coupons=visible, stats=stats_for(coupons), q=q, status=status, account_filter=account_filter, sort_key=sort_key)


@app.route("/current-account", methods=["POST"])
def set_current_account():
    ensure_dirs()
    settings = load_settings()
    account = request.form.get("account")
    if account in {"a", "b"}:
        settings["current_edeka_account"] = account
        save_settings(settings)
    else:
        flash("Unbekannter PAYBACK Account.", "error")
    return redirect(request.referrer or url_for("index"))


@app.route("/coupons", methods=["POST"])
def create_coupon():
    ensure_dirs()
    coupons = load_coupons()
    try:
        image = save_upload(request.files.get("image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))

    coupon = normalize_coupon({
        "id": str(uuid.uuid4()),
        "title": (request.form.get("title") or "").strip() or "PAYBACK Coupon",
        "description": (request.form.get("description") or "").strip(),
        "partner": (request.form.get("partner") or "").strip(),
        "value": (request.form.get("value") or "").strip(),
        "starts_at": (request.form.get("starts_at") or "").strip(),
        "expires_at": (request.form.get("expires_at") or "").strip(),
        "image": image,
        "barcode_number": (request.form.get("barcode_number") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    coupon, _ = ensure_barcode_for_coupon(coupon)
    coupons.append(coupon)
    backup_file(DATA_FILE)
    save_coupons(coupons)
    if image and not coupon.get("barcode_number"):
        flash("Coupon gespeichert. Barcode konnte nicht automatisch gelesen werden, bitte Nummer manuell ergänzen.", "warning")
    else:
        flash("Coupon gespeichert.", "success")
    return redirect(url_for("coupon_detail", coupon_id=coupon["id"]))


@app.route("/coupons/<coupon_id>")
def coupon_detail(coupon_id):
    ensure_dirs()
    coupons = load_coupons()
    _, coupon = find_coupon(coupons, coupon_id)
    if not coupon:
        flash("Coupon wurde nicht gefunden.", "error")
        return redirect(url_for("index"))
    return render_template("detail.html", coupon=coupon)


@app.route("/coupons/<coupon_id>/barcode.png")
def barcode_card(coupon_id):
    ensure_dirs()
    coupons = load_coupons()
    _, coupon = find_coupon(coupons, coupon_id)
    if not coupon:
        return redirect(url_for("index"))
    try:
        img = render_barcode_card(coupon)
    except Exception:
        img = Image.new("RGB", (1200, 520), "white")
        draw = ImageDraw.Draw(img)
        draw.text((120, 230), "Barcode konnte nicht angezeigt werden", fill="#667085", font=get_font(44, bold=True))
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png", download_name=f"coupon-{coupon_id}.png")


@app.route("/coupons/<coupon_id>/update", methods=["POST"])
def update_coupon(coupon_id):
    ensure_dirs()
    coupons = load_coupons()
    idx, coupon = find_coupon(coupons, coupon_id)
    if coupon is None:
        flash("Coupon wurde nicht gefunden.", "error")
        return redirect(url_for("index"))

    try:
        new_image = save_upload(request.files.get("image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("coupon_detail", coupon_id=coupon_id))

    if new_image:
        delete_image(coupon.get("image"))
        coupon["image"] = new_image
        coupon["barcode_number"] = ""
        coupon["barcode_scan_attempted"] = False

    coupon["title"] = (request.form.get("title") or "").strip() or "PAYBACK Coupon"
    coupon["description"] = (request.form.get("description") or "").strip()
    coupon["partner"] = (request.form.get("partner") or "").strip()
    coupon["value"] = (request.form.get("value") or "").strip()
    coupon["starts_at"] = (request.form.get("starts_at") or "").strip()
    coupon["expires_at"] = (request.form.get("expires_at") or "").strip()
    coupon["notes"] = (request.form.get("notes") or "").strip()
    manual = normalize_barcode_text((request.form.get("barcode_number") or "").strip())
    if manual:
        coupon["barcode_number"] = manual
    coupon["updated_at"] = now_iso()

    coupon, _ = ensure_barcode_for_coupon(coupon)
    coupons[idx] = normalize_coupon(coupon)
    backup_file(DATA_FILE)
    save_coupons(coupons)
    if coupon.get("image") and not coupon.get("barcode_number"):
        flash("Änderungen gespeichert. Barcode konnte nicht gelesen werden, bitte Nummer manuell ergänzen.", "warning")
    else:
        flash("Änderungen gespeichert.", "success")
    return redirect(url_for("coupon_detail", coupon_id=coupon_id))


@app.route("/coupons/<coupon_id>/redeem", methods=["POST"])
def redeem_coupon(coupon_id):
    ensure_dirs()
    settings = load_settings()
    coupons = load_coupons()
    idx, coupon = find_coupon(coupons, coupon_id)
    if coupon is None:
        flash("Coupon wurde nicht gefunden.", "error")
        return redirect(url_for("index"))

    account = request.form.get("account")
    if account not in {"a", "b"}:
        flash("Unbekannter Account.", "error")
        return redirect(url_for("index"))

    action = request.form.get("action", "redeem")
    coupon = normalize_coupon(coupon)
    if action == "undo":
        coupon["redeemed"][account] = False
        coupon["redeemed_at"][account] = ""
        flash("Einlösung zurückgesetzt.", "success")
    else:
        coupon["redeemed"][account] = True
        coupon["redeemed_at"][account] = now_iso()
        flash("Einlösung markiert.", "success")
    coupon["updated_at"] = now_iso()

    if settings.get("auto_delete_finished", True) and coupon["redeemed"]["a"] and coupon["redeemed"]["b"]:
        delete_image(coupon.get("image"))
        coupons.pop(idx)
        backup_file(DATA_FILE)
        save_coupons(coupons)
        flash("Coupon war mit beiden Accounts eingelöst und wurde gelöscht.", "success")
        return redirect(url_for("index"))

    coupons[idx] = coupon
    backup_file(DATA_FILE)
    save_coupons(coupons)
    return redirect(request.referrer or url_for("index"))


@app.route("/coupons/<coupon_id>/delete", methods=["POST"])
def delete_coupon_route(coupon_id):
    ensure_dirs()
    coupons = load_coupons()
    idx, coupon = find_coupon(coupons, coupon_id)
    if coupon is None:
        flash("Coupon wurde nicht gefunden.", "error")
        return redirect(url_for("index"))
    delete_image(coupon.get("image"))
    coupons.pop(idx)
    backup_file(DATA_FILE)
    save_coupons(coupons)
    flash("Coupon gelöscht.", "success")
    return redirect(url_for("index"))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    ensure_dirs()
    settings = load_settings()
    if request.method == "POST":
        settings["account_a"] = (request.form.get("account_a") or "Hauptprofil PAYBACK").strip()
        settings["account_b"] = (request.form.get("account_b") or "Zweitprofil PAYBACK").strip()
        settings["current_edeka_account"] = request.form.get("current_edeka_account") or settings.get("current_edeka_account", "a")
        if settings["current_edeka_account"] not in {"a", "b"}:
            settings["current_edeka_account"] = "a"
        settings["auto_delete_finished"] = request.form.get("auto_delete_finished") == "on"
        settings["default_sort"] = request.form.get("default_sort") or "expires_first"
        save_settings(settings)
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings_page"))
    return render_template("settings.html")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/health")
def health():
    return {"status": "ok", "version": "0.1.12"}


if __name__ == "__main__":
    ensure_dirs()
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)
