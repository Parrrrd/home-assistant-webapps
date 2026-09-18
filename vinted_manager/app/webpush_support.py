from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAX_WEBPUSH_PLAINTEXT = 3900
DEFAULT_RECORD_SIZE = 4096


class WebPushDeliveryError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, expired: bool = False) -> None:
        super().__init__(message)
        self.status = int(status or 0)
        self.expired = bool(expired)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    text = str(value or "").strip()
    if not text:
        return b""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hmac_sha256(key: bytes, value: bytes) -> bytes:
    return hmac.new(key, value, hashlib.sha256).digest()


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def load_or_create_vapid_private_key(path: Path) -> ec.EllipticCurvePrivateKey:
    path = Path(path)
    try:
        raw = path.read_bytes()
        loaded = serialization.load_pem_private_key(raw, password=None)
        if isinstance(loaded, ec.EllipticCurvePrivateKey) and isinstance(loaded.curve, ec.SECP256R1):
            return loaded
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def vapid_public_key_b64(path: Path) -> str:
    key = load_or_create_vapid_private_key(path)
    return _b64url_encode(_public_bytes(key.public_key()))


def encrypt_webpush_payload(
    subscription: dict[str, Any],
    plaintext: bytes,
    *,
    sender_private_key: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
    record_size: int = DEFAULT_RECORD_SIZE,
) -> bytes:
    """Encrypt one RFC 8291 Web Push payload using aes128gcm.

    ``sender_private_key`` and ``salt`` are injectable only to verify the
    implementation against the deterministic RFC 8291 test vector.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("Web-Push-Nutzdaten müssen Bytes sein.")
    plaintext = bytes(plaintext)
    if len(plaintext) > MAX_WEBPUSH_PLAINTEXT:
        raise ValueError("Web-Push-Nutzdaten sind zu groß.")

    keys = subscription.get("keys") if isinstance(subscription, dict) else None
    if not isinstance(keys, dict):
        raise ValueError("Push-Subscription enthält keine Schlüssel.")
    ua_public_raw = _b64url_decode(str(keys.get("p256dh") or ""))
    auth_secret = _b64url_decode(str(keys.get("auth") or ""))
    if len(ua_public_raw) != 65 or not ua_public_raw.startswith(b"\x04"):
        raise ValueError("Ungültiger p256dh-Schlüssel der Push-Subscription.")
    if len(auth_secret) < 16:
        raise ValueError("Ungültiges Auth-Secret der Push-Subscription.")

    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_raw)
    as_private = sender_private_key or ec.generate_private_key(ec.SECP256R1())
    as_public_raw = _public_bytes(as_private.public_key())
    shared_secret = as_private.exchange(ec.ECDH(), ua_public)

    # RFC 8291 §3.3/3.4.  The 32-byte output fits into one HKDF expand block.
    prk_key = _hmac_sha256(auth_secret, shared_secret)
    key_info = b"WebPush: info\x00" + ua_public_raw + as_public_raw
    ikm = _hmac_sha256(prk_key, key_info + b"\x01")

    salt = bytes(salt) if salt is not None else os.urandom(16)
    if len(salt) != 16:
        raise ValueError("Web-Push-Salt muss 16 Bytes lang sein.")
    prk = _hmac_sha256(salt, ikm)
    cek = _hmac_sha256(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac_sha256(prk, b"Content-Encoding: nonce\x00\x01")[:12]

    # Push messages use exactly one RFC 8188 record.  0x02 is the required
    # final-record padding delimiter; no additional padding is needed here.
    clear_record = plaintext + b"\x02"
    if record_size <= len(clear_record) + 16:
        raise ValueError("Web-Push-Record-Size ist zu klein.")
    ciphertext = AESGCM(cek).encrypt(nonce, clear_record, None)
    header = salt + int(record_size).to_bytes(4, "big") + bytes([len(as_public_raw)]) + as_public_raw
    return header + ciphertext


def _vapid_jwt(private_key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str) -> tuple[str, str]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Push-Endpunkt muss eine HTTPS-Adresse sein.")
    audience = f"{parsed.scheme}://{parsed.netloc}"
    now = int(time.time())
    header = {"typ": "JWT", "alg": "ES256"}
    claims = {"aud": audience, "exp": now + 12 * 60 * 60, "sub": str(subject or "")}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    claims_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
    der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = f"{header_b64}.{claims_b64}.{_b64url_encode(raw_signature)}"
    public_key = _b64url_encode(_public_bytes(private_key.public_key()))
    return token, public_key


def send_webpush(
    subscription: dict[str, Any],
    payload: dict[str, Any],
    *,
    vapid_private_key_path: Path,
    subject: str,
    ttl: int = 86400,
    timeout: float = 15.0,
) -> int:
    endpoint = str((subscription or {}).get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise WebPushDeliveryError("Ungültiger Web-Push-Endpunkt.")

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = encrypt_webpush_payload(subscription, data)
    private_key = load_or_create_vapid_private_key(Path(vapid_private_key_path))
    token, public_key = _vapid_jwt(private_key, endpoint, subject)
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"vapid t={token}, k={public_key}",
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(max(0, int(ttl))),
            "Urgency": "normal",
            "User-Agent": "Vinted-Manager-WebPush/1.0",
        },
    )
    try:
        with urlopen(request, timeout=max(3.0, float(timeout))) as response:
            status = int(getattr(response, "status", 201) or 201)
            if 200 <= status < 300:
                return status
            raise WebPushDeliveryError(f"Push-Dienst antwortete mit HTTP {status}.", status=status)
    except HTTPError as error:
        status = int(getattr(error, "code", 0) or 0)
        try:
            detail = error.read(500).decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        message = f"Push-Dienst antwortete mit HTTP {status}."
        if detail:
            message += f" {detail[:240]}"
        raise WebPushDeliveryError(message, status=status, expired=status in {404, 410}) from error
    except URLError as error:
        raise WebPushDeliveryError(f"Push-Dienst nicht erreichbar: {getattr(error, 'reason', error)}") from error
    except TimeoutError as error:
        raise WebPushDeliveryError("Zeitüberschreitung beim Push-Dienst.") from error
