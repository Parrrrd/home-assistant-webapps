from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests
from zoneinfo import ZoneInfo

API_BASE = "https://v3.football.api-sports.io"
BERLIN_TZ = ZoneInfo("Europe/Berlin")


def _norm_team(value: str) -> str:
    value = str(value or "").casefold()
    repl = {
        "ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e", "á": "a", "à": "a",
        "ó": "o", "ò": "o", "í": "i", "ì": "i", "ç": "c", "ñ": "n",
    }
    for old, new in repl.items():
        value = value.replace(old, new)
    value = re.sub(r"\b(1\.?|fc|sc|sv|vfl|vfb|tsg|rb|bsc|borussia|spvgg)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _team_similarity(a: str, b: str) -> float:
    left, right = _norm_team(a), _norm_team(b)
    if not left or not right:
        return 0.0
    if left == right or left in right or right in left:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    token_score = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    seq = SequenceMatcher(None, left, right).ratio()
    return max(seq, token_score)


def _cache_path(cache_dir: Path, prefix: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"{prefix}_{digest}.json"


def _read_cache(path: Path, max_age: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = float(data.get("_fetched_epoch") or 0)
        if fetched and time.time() - fetched <= max_age:
            return data
    except Exception:
        return None
    return None


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["_fetched_epoch"] = time.time()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _api_get(api_key: str, endpoint: str, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    response = requests.get(
        API_BASE + endpoint,
        params=params,
        headers={"x-apisports-key": api_key, "Accept": "application/json", "User-Agent": "Kicktipp-TipBot/0.1.19"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("API-Football lieferte ein unerwartetes Format")
    errors = data.get("errors")
    if errors and errors != [] and errors != {}:
        raise RuntimeError(f"API-Football: {errors}")
    rate = {
        "remaining": str(response.headers.get("x-ratelimit-requests-remaining") or ""),
        "limit": str(response.headers.get("x-ratelimit-requests-limit") or ""),
    }
    return data, rate


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _choose_fixture(fixtures: list[dict[str, Any]], home: str, away: str, kickoff: str) -> tuple[dict[str, Any] | None, float]:
    wanted_kickoff = _parse_iso(kickoff)
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for item in fixtures:
        teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
        h = teams.get("home") if isinstance(teams.get("home"), dict) else {}
        a = teams.get("away") if isinstance(teams.get("away"), dict) else {}
        direct = (_team_similarity(home, str(h.get("name") or "")) + _team_similarity(away, str(a.get("name") or ""))) / 2
        swapped = (_team_similarity(home, str(a.get("name") or "")) + _team_similarity(away, str(h.get("name") or ""))) / 2
        score = max(direct, swapped * 0.75)
        fixture = item.get("fixture") if isinstance(item.get("fixture"), dict) else {}
        candidate_kickoff = _parse_iso(str(fixture.get("date") or ""))
        if wanted_kickoff and candidate_kickoff:
            delta_hours = abs((candidate_kickoff - wanted_kickoff).total_seconds()) / 3600
            if delta_hours <= 0.25:
                score += 0.25
            elif delta_hours <= 2:
                score += 0.12
            elif delta_hours > 8:
                score -= 0.25
        if score > best[0]:
            best = (score, item)
    return best[1] if best[0] >= 0.60 else None, best[0]


def _event_time(event: dict[str, Any]) -> str:
    t = event.get("time") if isinstance(event.get("time"), dict) else {}
    elapsed = t.get("elapsed")
    extra = t.get("extra")
    if elapsed is None:
        return ""
    try:
        base = str(int(elapsed))
    except Exception:
        base = str(elapsed)
    if extra:
        try:
            return f"{base}+{int(extra)}′"
        except Exception:
            pass
    return base + "′"


def _normalize_events(events: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"goals": [], "cards": [], "substitutions": []}
    if not isinstance(events, list):
        return out
    for event in events:
        if not isinstance(event, dict):
            continue
        typ = str(event.get("type") or "").casefold()
        detail = str(event.get("detail") or "")
        team = event.get("team") if isinstance(event.get("team"), dict) else {}
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        assist = event.get("assist") if isinstance(event.get("assist"), dict) else {}
        base = {
            "time": _event_time(event),
            "team": str(team.get("name") or ""),
            "player": str(player.get("name") or ""),
            "detail": detail,
        }
        if typ == "goal":
            base["assist"] = str(assist.get("name") or "")
            out["goals"].append(base)
        elif typ == "card":
            base["card"] = "red" if "red" in detail.casefold() else "yellow"
            out["cards"].append(base)
        elif typ in ("subst", "substitution"):
            base["player_out"] = str(player.get("name") or "")
            base["player_in"] = str(assist.get("name") or "")
            out["substitutions"].append(base)
    return out


def _normalize_lineups(lineups: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(lineups, list):
        return result
    for lineup in lineups:
        if not isinstance(lineup, dict):
            continue
        team = lineup.get("team") if isinstance(lineup.get("team"), dict) else {}
        coach = lineup.get("coach") if isinstance(lineup.get("coach"), dict) else {}
        def players(key: str) -> list[dict[str, str]]:
            raw = lineup.get(key) or []
            out: list[dict[str, str]] = []
            if isinstance(raw, list):
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    p = entry.get("player") if isinstance(entry.get("player"), dict) else entry
                    out.append({
                        "name": str(p.get("name") or ""),
                        "number": str(p.get("number") or ""),
                        "pos": str(p.get("pos") or ""),
                    })
            return out
        result.append({
            "team": str(team.get("name") or ""),
            "logo": str(team.get("logo") or ""),
            "formation": str(lineup.get("formation") or ""),
            "coach": str(coach.get("name") or ""),
            "start_xi": players("startXI"),
            "substitutes": players("substitutes"),
        })
    return result


def get_match_details(
    *,
    api_key: str,
    cache_dir: Path,
    home: str,
    away: str,
    kickoff: str,
    status: str = "",
) -> dict[str, Any]:
    api_key = str(api_key or "").strip()
    if not api_key:
        return {
            "ok": True,
            "configured": False,
            "message": "API-Football-Key ist noch nicht hinterlegt.",
            "events": {"goals": [], "cards": [], "substitutions": []},
            "lineups": [],
        }

    kickoff_dt = _parse_iso(kickoff)
    local_date = (kickoff_dt or datetime.now(timezone.utc)).astimezone(BERLIN_TZ).strftime("%Y-%m-%d")
    date_cache = _cache_path(cache_dir, "fixtures", local_date)
    date_payload = _read_cache(date_cache, 600)
    rate: dict[str, str] = {}
    if date_payload is None:
        date_payload, rate = _api_get(api_key, "/fixtures", {"date": local_date, "timezone": "Europe/Berlin"})
        _write_cache(date_cache, date_payload)
    fixtures = date_payload.get("response") if isinstance(date_payload.get("response"), list) else []
    fixture, confidence = _choose_fixture(fixtures, home, away, kickoff)
    if not fixture:
        return {
            "ok": False,
            "configured": True,
            "message": "Das Spiel wurde bei API-Football für diesen Tag nicht eindeutig gefunden.",
            "match_confidence": round(confidence, 3),
            "rate": rate,
            "events": {"goals": [], "cards": [], "substitutions": []},
            "lineups": [],
        }

    fixture_meta = fixture.get("fixture") if isinstance(fixture.get("fixture"), dict) else {}
    fixture_id = fixture_meta.get("id")
    if fixture_id is None:
        raise RuntimeError("API-Football-Spiel ohne Fixture-ID")

    status_lower = str(status or "").casefold()
    detail_ttl = 43200 if status_lower == "finished" else (60 if status_lower in ("live", "halftime") else 300)
    detail_cache = _cache_path(cache_dir, "detail", str(fixture_id))
    detail_payload = _read_cache(detail_cache, detail_ttl)
    if detail_payload is None:
        detail_payload, rate2 = _api_get(api_key, "/fixtures", {"id": fixture_id})
        rate = rate2 or rate
        _write_cache(detail_cache, detail_payload)

    response_items = detail_payload.get("response") if isinstance(detail_payload.get("response"), list) else []
    detail = response_items[0] if response_items else fixture
    fixture_node = detail.get("fixture") if isinstance(detail.get("fixture"), dict) else {}
    status_node = fixture_node.get("status") if isinstance(fixture_node.get("status"), dict) else {}
    teams_node = detail.get("teams") if isinstance(detail.get("teams"), dict) else {}
    goals_node = detail.get("goals") if isinstance(detail.get("goals"), dict) else {}

    return {
        "ok": True,
        "configured": True,
        "fixture_id": fixture_id,
        "match_confidence": round(confidence, 3),
        "status": str(status_node.get("long") or ""),
        "minute": status_node.get("elapsed"),
        "home": str((teams_node.get("home") or {}).get("name") or home) if isinstance(teams_node.get("home"), dict) else home,
        "away": str((teams_node.get("away") or {}).get("name") or away) if isinstance(teams_node.get("away"), dict) else away,
        "home_logo": str((teams_node.get("home") or {}).get("logo") or "") if isinstance(teams_node.get("home"), dict) else "",
        "away_logo": str((teams_node.get("away") or {}).get("logo") or "") if isinstance(teams_node.get("away"), dict) else "",
        "home_goals": goals_node.get("home"),
        "away_goals": goals_node.get("away"),
        "events": _normalize_events(detail.get("events")),
        "lineups": _normalize_lineups(detail.get("lineups")),
        "rate": rate,
        "source": "API-Football",
    }
