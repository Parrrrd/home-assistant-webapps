import os
import re
import time
import threading
from typing import Any, Dict, Tuple

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_request_lock = threading.Lock()
_cooldown_until = 0.0
_last_error = ""

SENTENCE_END_RE = re.compile(r"[.!?]$|[.!?][\"'»)]$")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "ja"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _config() -> Dict[str, Any]:
    return {
        "api_key": os.environ.get("JARVIS_GEMINI_API_KEY", "").strip(),
        "model": os.environ.get("JARVIS_GEMINI_MODEL", "gemini-2.5-flash").strip(),
        "enable_google_search": _env_bool("JARVIS_ENABLE_GOOGLE_SEARCH", True),
        "temperature": _env_float("JARVIS_TEMPERATURE", 0.3),
        "max_output_tokens": _env_int("JARVIS_MAX_OUTPUT_TOKENS", 350),
        "timeout": _env_int("JARVIS_REQUEST_TIMEOUT_SECONDS", 45),
        "cooldown_seconds": _env_int("JARVIS_COOLDOWN_SECONDS_AFTER_ERROR", 30),
        "max_answer_chars": _env_int("JARVIS_MAX_ANSWER_CHARS", 750),
        "retry_incomplete_answers": _env_bool("JARVIS_RETRY_INCOMPLETE_ANSWERS", True),
        "default_location": os.environ.get("JARVIS_DEFAULT_LOCATION", "Ostercappeln, Niedersachsen, Deutschland").strip(),
        "system_prompt": os.environ.get("JARVIS_SYSTEM_PROMPT", "").strip(),
    }


def _normalize_text(text: Any) -> str:
    if text is None:
        return ""
    cleaned = str(text).replace("\r", " ").replace("\n", " ").strip()
    cleaned = cleaned.replace("*", "").replace("#", "").replace('"', "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _clean_for_speech(text: Any) -> str:
    """Remove Gemini grounding/citation leftovers before Home Assistant TTS reads them."""
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""

    # Gemini with Google Search grounding can occasionally leak citation markers into
    # the text, for example: "... trocken. [cite: 2, Morgen ...".
    # For voice output this should never be spoken. In practice the part after
    # [cite: often contains a duplicate of the answer, so we cut it completely.
    cleaned = re.sub(r"\s*\[\s*cite\s*:[^\]]*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*\[\s*cite\s*:[^\]]*\]", "", cleaned, flags=re.IGNORECASE).strip()

    # Remove other common bracketed source markers if a model emits them.
    cleaned = re.sub(r"\s*\[(?:source|quelle|quellen|citation|citations)\s*:[^\]]*\]", "", cleaned, flags=re.IGNORECASE).strip()

    # If a broken citation marker left a trailing comma/colon, clean it up.
    cleaned = cleaned.rstrip(" ,;:")

    if cleaned and not _has_sentence_end(cleaned) and not _looks_incomplete(cleaned):
        cleaned += "."

    return cleaned


def _shorten(text: Any, limit: int) -> str:
    cleaned = _normalize_text(text)
    return cleaned[:limit]


def _has_sentence_end(text: str) -> bool:
    return bool(SENTENCE_END_RE.search(text.strip()))


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _looks_incomplete(answer: str) -> bool:
    """Detects clearly broken model responses like 'Die WM 2026 wird in'."""
    a = _normalize_text(answer)
    if not a:
        return True

    words = _word_count(a)
    if _has_sentence_end(a):
        return False

    # Suspiciously short and no sentence end: probably a partial Gemini response.
    if words <= 14 or len(a) < 120:
        return True

    # Ends with a connector / preposition: likely cut mid-sentence.
    last_word_match = re.search(r"([A-Za-zÄÖÜäöüß]+)$", a)
    if last_word_match:
        last_word = last_word_match.group(1).lower()
        if last_word in {
            "in", "mit", "von", "nach", "auf", "für", "fuer", "bei", "zu", "zum", "zur",
            "und", "oder", "aber", "weil", "dass", "das", "die", "der", "den", "dem", "des",
            "ein", "eine", "einer", "einem", "einen", "als", "wie", "sowie", "durch", "gegen",
            "ohne", "über", "ueber", "unter", "zwischen", "während", "waehrend"
        }:
            return True

    return False


def _limit_to_complete_sentence(text: str, max_chars: int) -> tuple[str, bool]:
    """Returns text within max_chars, preferably ending at a full sentence."""
    cleaned = _normalize_text(text)
    if not cleaned:
        return "", False

    max_chars = max(120, int(max_chars or 750))

    if len(cleaned) <= max_chars:
        if _has_sentence_end(cleaned):
            return cleaned, False
        # Do not invent content, only add a period for otherwise reasonable full answers.
        if not _looks_incomplete(cleaned):
            return cleaned.rstrip(" ,;:") + ".", False
        return cleaned, False

    prefix = cleaned[:max_chars].rstrip()

    # Find the last sentence boundary inside the limit.
    matches = list(re.finditer(r"[.!?](?:[\"'»)])?(?=\s|$)", prefix))
    if matches:
        cut = matches[-1].end()
        candidate = prefix[:cut].strip()
        if len(candidate) >= 80:
            return candidate, True

    # Fallback: cut at the last word boundary and close the sentence.
    candidate = prefix.rsplit(" ", 1)[0].strip().rstrip(" ,;:")
    if not candidate:
        candidate = prefix.strip().rstrip(" ,;:")
    if not _has_sentence_end(candidate):
        candidate += "."
    return candidate, True


def _render_prompt_template(prompt: str, max_chars: int, default_location: str) -> str:
    """Allow simple placeholders in the Home Assistant add-on configuration."""
    return (
        _normalize_text(prompt)
        .replace("{max_chars}", str(max_chars))
        .replace("{default_location}", default_location or "")
    )


def _build_system_text(
    max_chars: int,
    default_location: str,
    system_prompt: str = "",
    retry_instruction: str | None = None,
) -> str:
    retry_text = ""
    if retry_instruction:
        retry_text = f" Wichtig: {retry_instruction} "

    system_text = _render_prompt_template(system_prompt, max_chars, default_location)
    return f"{system_text} {retry_text}".strip()


def _build_payload(
    question: str,
    last_question: str,
    last_answer: str,
    cfg: Dict[str, Any],
    retry_instruction: str | None = None,
) -> Dict[str, Any]:
    max_chars = cfg["max_answer_chars"]
    system_text = _build_system_text(
        max_chars,
        cfg.get("default_location", ""),
        cfg.get("system_prompt", ""),
        retry_instruction,
    )

    prompt_text = (
        f"Vorherige Frage:\n{last_question}\n\n"
        f"Vorherige Antwort:\n{last_answer}\n\n"
        f"Aktuelle Frage:\n{question}\n\n"
        f"Antworte mit maximal {max_chars} Zeichen und beende die Antwort vollständig."
    )

    payload: Dict[str, Any] = {
        "system_instruction": {
            "parts": [{"text": system_text}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt_text}],
            }
        ],
        "generationConfig": {
            "temperature": cfg["temperature"],
            "maxOutputTokens": cfg["max_output_tokens"],
        },
    }

    if cfg["enable_google_search"]:
        payload["tools"] = [{"google_search": {}}]

    return payload


def _extract_answer(data: Dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return "Ich habe leider keine passende Antwort bekommen."

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for part in parts:
        text = part.get("text")
        if text:
            texts.append(text)

    answer = _normalize_text(" ".join(texts))
    if not answer:
        return "Ich habe leider keine passende Antwort bekommen."
    return answer


def _used_search(data: Dict[str, Any]) -> bool:
    candidates = data.get("candidates") or []
    if not candidates:
        return False

    meta = candidates[0].get("groundingMetadata") or candidates[0].get("grounding_metadata") or {}
    if not meta:
        return False

    if meta.get("webSearchQueries") or meta.get("web_search_queries"):
        return True
    if meta.get("groundingChunks") or meta.get("grounding_chunks"):
        return True
    return False


def _extract_sources(data: Dict[str, Any]) -> list[dict[str, str]]:
    candidates = data.get("candidates") or []
    if not candidates:
        return []

    meta = candidates[0].get("groundingMetadata") or candidates[0].get("grounding_metadata") or {}
    chunks = meta.get("groundingChunks") or meta.get("grounding_chunks") or []
    sources = []
    for chunk in chunks[:5]:
        web = chunk.get("web") or {}
        uri = web.get("uri") or ""
        title = web.get("title") or ""
        if uri or title:
            sources.append({"title": title, "uri": uri})
    return sources


def _post_to_gemini(
    question: str,
    last_question: str,
    last_answer: str,
    cfg: Dict[str, Any],
    retry_instruction: str | None = None,
) -> Tuple[Dict[str, Any], int]:
    url = f"{API_BASE}/models/{cfg['model']}:generateContent"
    payload = _build_payload(question, last_question, last_answer, cfg, retry_instruction=retry_instruction)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": cfg["api_key"],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=cfg["timeout"])
    except requests.Timeout:
        return {"transport_error": "timeout"}, 504
    except requests.RequestException as exc:
        return {"transport_error": "request_exception", "details": str(exc)}, 502

    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text[:1000]}

    return data, response.status_code


def _call_gemini(question: str, last_question: str, last_answer: str) -> Tuple[Dict[str, Any], int]:
    global _cooldown_until, _last_error

    cfg = _config()
    max_chars = cfg["max_answer_chars"]

    if not cfg["api_key"]:
        return {
            "ok": False,
            "answer": "Es ist noch kein Gemini API-Key im Jarvis-AI-Add-on eingetragen.",
            "error": "missing_api_key",
            "model": cfg["model"],
            "used_search": False,
        }, 400

    now = time.time()
    if now < _cooldown_until:
        remaining = int(_cooldown_until - now)
        return {
            "ok": False,
            "answer": f"Gemini ist nach einem Fehler kurz pausiert. Bitte in etwa {remaining} Sekunden erneut versuchen.",
            "error": "cooldown_active",
            "last_error": _last_error,
            "retry_after_seconds": remaining,
            "model": cfg["model"],
            "used_search": False,
        }, 429

    with _request_lock:
        data, status_code = _post_to_gemini(question, last_question, last_answer, cfg)

        if status_code != 200:
            if data.get("transport_error") == "timeout":
                _last_error = "timeout"
                _cooldown_until = time.time() + cfg["cooldown_seconds"]
                return {
                    "ok": False,
                    "answer": "Gemini hat zu lange gebraucht und wurde abgebrochen.",
                    "error": "timeout",
                    "model": cfg["model"],
                    "used_search": False,
                }, 504
            if data.get("transport_error") == "request_exception":
                _last_error = data.get("details", "request_exception")
                _cooldown_until = time.time() + cfg["cooldown_seconds"]
                return {
                    "ok": False,
                    "answer": "Gemini ist gerade nicht erreichbar.",
                    "error": "request_exception",
                    "details": data.get("details", ""),
                    "model": cfg["model"],
                    "used_search": False,
                }, 502

            if status_code in (429, 500, 502, 503, 504):
                _cooldown_until = time.time() + cfg["cooldown_seconds"]
            _last_error = f"HTTP {status_code}: {str(data)[:500]}"
            return {
                "ok": False,
                "answer": "Gemini hat einen Fehler zurückgegeben.",
                "error": "gemini_http_error",
                "status_code": status_code,
                "details": data,
                "model": cfg["model"],
                "used_search": False,
            }, 502

        raw_answer = _clean_for_speech(_extract_answer(data))
        retried = False
        first_answer_incomplete = _looks_incomplete(raw_answer)
        used_search = _used_search(data)
        sources = _extract_sources(data)

        if cfg["retry_incomplete_answers"] and first_answer_incomplete:
            retry_instruction = (
                "Die vorherige Antwort war unvollständig. Antworte jetzt erneut, vollständig, "
                f"maximal {max_chars} Zeichen, und beende die Antwort mit Punkt, Fragezeichen oder Ausrufezeichen."
            )
            retry_data, retry_status_code = _post_to_gemini(
                question,
                last_question,
                last_answer,
                cfg,
                retry_instruction=retry_instruction,
            )
            if retry_status_code == 200:
                retry_answer = _clean_for_speech(_extract_answer(retry_data))
                if retry_answer and not _looks_incomplete(retry_answer):
                    raw_answer = retry_answer
                    data = retry_data
                    used_search = used_search or _used_search(retry_data)
                    retry_sources = _extract_sources(retry_data)
                    sources = retry_sources or sources
                    retried = True
                else:
                    retried = True
            else:
                retried = True

    answer, cropped = _limit_to_complete_sentence(raw_answer, max_chars)

    if _looks_incomplete(answer):
        answer = "Ich habe gerade nur eine unvollständige Antwort bekommen. Bitte frag mich noch einmal."
        cropped = False

    return {
        "ok": True,
        "answer": answer,
        "model": cfg["model"],
        "used_search": used_search,
        "sources": sources,
        "answer_chars": len(answer),
        "raw_answer_chars": len(_normalize_text(raw_answer)),
        "max_answer_chars": max_chars,
        "retried_incomplete_answer": retried,
        "first_answer_incomplete": first_answer_incomplete,
        "cropped_to_sentence": cropped,
    }, 200


@app.get("/health")
def health():
    cfg = _config()
    return jsonify(
        {
            "ok": True,
            "service": "jarvis-ai",
            "version": "0.1.5",
            "model": cfg["model"],
            "enable_google_search": cfg["enable_google_search"],
            "api_key_configured": bool(cfg["api_key"]),
            "max_answer_chars": cfg["max_answer_chars"],
            "retry_incomplete_answers": cfg["retry_incomplete_answers"],
            "default_location": cfg["default_location"],
            "system_prompt_configured": bool(cfg["system_prompt"]),
        }
    )


@app.post("/ask")
def ask():
    body = request.get_json(silent=True) or {}
    question = _shorten(body.get("question"), 1000)
    last_question = _shorten(body.get("last_question"), 1000)
    last_answer = _shorten(body.get("last_answer"), 1000)

    if not question:
        return jsonify(
            {
                "ok": False,
                "answer": "Was möchtest du wissen?",
                "error": "empty_question",
                "used_search": False,
            }
        ), 400

    result, status = _call_gemini(question, last_question, last_answer)
    return jsonify(result), status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
