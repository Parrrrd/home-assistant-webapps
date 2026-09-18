from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from difflib import SequenceMatcher

import requests
from zoneinfo import ZoneInfo

from kicktipp_live import fetch_livebox, fetch_public_detail, resolve_public_detail_url

BERLIN_TZ = ZoneInfo("Europe/Berlin")
OPENLIGA_BASE = "https://api.openligadb.de"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
KICKTIPP_LIVEBOX_REFRESH_SECONDS = 60
UEFA_COMPETITIONS_URL = "https://comp.uefa.com/v2/competitions"
UEFA_MATCHES_URL = "https://match.uefa.com/v5/matches"
UEFA_LIVESCORE_URL = "https://match.uefa.com/v5/livescore"
UEFA_SCHEDULE_REFRESH = timedelta(minutes=30)
UEFA_COMPETITION_REFRESH = timedelta(hours=24)
UEFA_RETRY_AFTER_ERROR = timedelta(minutes=10)

# Discovery is the primary path. The fallback IDs only keep the monitor usable if
# UEFA's competition catalogue is temporarily unavailable during an add-on start.
UEFA_COMPETITION_FALLBACKS = {
    "ucl": "1",
    "uel": "14",
    "uecl": "2019",
}

COMPETITIONS = {
    "bl1": {
        "label": "1. Bundesliga",
        "title": "⚽ 1. Bundesliga · Endergebnisse",
        "enabled_option": "football_bl1_enabled",
        "source": "openliga",
    },
    "bl2": {
        "label": "2. Bundesliga",
        "title": "⚽ 2. Bundesliga · Endergebnisse",
        "enabled_option": "football_bl2_enabled",
        "source": "openliga",
    },
    "dfb": {
        "label": "DFB-Pokal",
        "title": "🏆 DFB-Pokal · Endergebnisse",
        "enabled_option": "football_dfb_enabled",
        "source": "openliga",
    },
    "supercup": {
        "label": "DFB-Supercup",
        "title": "🏆 DFB-Supercup · Endergebnis",
        "enabled_option": "football_supercup_enabled",
        "source": "openliga",
    },
    "dfb_men": {
        "label": "Deutschland Herren",
        "title": "🇩🇪 Deutschland · Endergebnis",
        "enabled_option": "football_germany_enabled",
        "source": "openliga",
    },
    "ucl": {
        "label": "Champions League",
        "title": "🏆 Champions League · Endergebnisse",
        "enabled_option": "football_ucl_enabled",
        "source": "uefa",
    },
    "uel": {
        "label": "Europa League",
        "title": "🟠 Europa League · Endergebnisse",
        "enabled_option": "football_uel_enabled",
        "source": "uefa",
    },
    "uecl": {
        "label": "Conference League",
        "title": "🟢 Conference League · Endergebnisse",
        "enabled_option": "football_uecl_enabled",
        "source": "uefa",
    },
}

FAVORITE_DEFAULTS = ("VfL Osnabrück", "Bayer 04 Leverkusen")
UEFA_COMP_KEYS = {"ucl", "uel", "uecl"}


def _request_json(url: str, *, params: dict[str, Any] | None = None, timeout: int = 15) -> Any:
    last_error: Exception | None = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "Kicktipp-TipBot/football-results",
    }
    for attempt in range(2):
        try:
            response = requests.get(url, params=params or {}, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.5)
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last_error}")


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BERLIN_TZ)
    return parsed.astimezone(timezone.utc)


def _season_start_year(now: datetime) -> int:
    local = now.astimezone(BERLIN_TZ)
    return local.year if local.month >= 7 else local.year - 1


def _translated_value(node: Any, *, preferred: tuple[str, ...] = ("de", "en")) -> str:
    if isinstance(node, str):
        return node.strip()
    if not isinstance(node, dict):
        return ""
    lowered = {str(k).lower(): v for k, v in node.items()}
    for key in preferred:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in node.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _uefa_team_name(team: dict[str, Any]) -> str:
    translations = team.get("translations") if isinstance(team.get("translations"), dict) else {}
    for key in ("displayName", "displayOfficialName"):
        name = _translated_value(translations.get(key))
        if name:
            return name
    return str(team.get("internationalName") or team.get("teamCode") or "").strip()


def _openliga_team_name(team: Any) -> str:
    if not isinstance(team, dict):
        return ""
    return str(team.get("teamName") or team.get("shortName") or team.get("teamNameShort") or "").strip()


def _openliga_final_score(match: dict[str, Any]) -> str:
    results = match.get("matchResults") or []
    if not isinstance(results, list):
        return ""
    candidates: list[tuple[int, str]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        p1 = result.get("pointsTeam1")
        p2 = result.get("pointsTeam2")
        if p1 is None or p2 is None:
            continue
        try:
            score = f"{int(p1)}:{int(p2)}"
        except Exception:
            continue
        result_type = int(result.get("resultTypeID") or 0)
        name = str(result.get("resultName") or "").lower()
        priority = result_type
        if "end" in name or "final" in name:
            priority += 100
        candidates.append((priority, score))
    return max(candidates, default=(0, ""), key=lambda item: item[0])[1]


def _openliga_score_by_kind(match: dict[str, Any], kind: str) -> str:
    results = match.get("matchResults") or []
    if not isinstance(results, list):
        return ""
    kind = kind.casefold()
    for result in results:
        if not isinstance(result, dict):
            continue
        name = str(result.get("resultName") or "").casefold()
        info = str(result.get("resultDescription") or result.get("description") or "").casefold()
        # OpenLigaDB exposes result types with machine meaning HalfTime / After90Minutes.
        # The regular match payload usually carries localized names, therefore we
        # accept the common labels as well.
        text = f"{name} {info}"
        if kind == "halftime" and not any(token in text for token in ("halbzeit", "half time", "halftime", "pause")):
            continue
        if kind == "final" and not any(token in text for token in ("endstand", "end ergebnis", "final", "90 minuten", "after90")):
            continue
        p1 = result.get("pointsTeam1")
        p2 = result.get("pointsTeam2")
        if p1 is None or p2 is None:
            continue
        try:
            return f"{int(p1)}:{int(p2)}"
        except Exception:
            continue
    return ""


def _openliga_live_score(match: dict[str, Any], *, started: bool = False) -> str:
    # During live play OpenLigaDB may keep matchResults empty until halftime/end.
    # The goals array, however, carries the running score after each goal.
    final_or_phase = _openliga_final_score(match)
    goals = match.get("goals") or []
    if isinstance(goals, list) and goals:
        for goal in reversed(goals):
            if not isinstance(goal, dict):
                continue
            p1, p2 = goal.get("scoreTeam1"), goal.get("scoreTeam2")
            if p1 is None or p2 is None:
                continue
            try:
                return f"{int(p1)}:{int(p2)}"
            except Exception:
                continue
    if final_or_phase:
        return final_or_phase
    # A started match with no goal events is 0:0. This is a score, not an estimate.
    return "0:0" if started else ""


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
    return max(SequenceMatcher(None, left, right).ratio(), token_score)


def _api_football_get_day(api_key: str, local_date: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    response = requests.get(
        API_FOOTBALL_BASE + "/fixtures",
        params={"date": local_date, "timezone": "Europe/Berlin"},
        headers={
            "x-apisports-key": api_key,
            "Accept": "application/json",
            "User-Agent": "Kicktipp-TipBot/0.1.27",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("API-Football lieferte ein unerwartetes Format")
    errors = payload.get("errors")
    if errors and errors not in ([], {}):
        raise RuntimeError(f"API-Football: {errors}")
    items = payload.get("response") if isinstance(payload.get("response"), list) else []
    rate = {
        "remaining": str(response.headers.get("x-ratelimit-requests-remaining") or ""),
        "limit": str(response.headers.get("x-ratelimit-requests-limit") or ""),
    }
    return items, rate


def _choose_api_fixture(fixtures: list[dict[str, Any]], game: dict[str, Any]) -> tuple[dict[str, Any] | None, float]:
    wanted_kickoff = _parse_dt(game.get("kickoff"))
    home = str(game.get("home") or "")
    away = str(game.get("away") or "")
    best_score = 0.0
    best_item: dict[str, Any] | None = None
    for item in fixtures:
        if not isinstance(item, dict):
            continue
        teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
        h = teams.get("home") if isinstance(teams.get("home"), dict) else {}
        a = teams.get("away") if isinstance(teams.get("away"), dict) else {}
        direct = (_team_similarity(home, str(h.get("name") or "")) + _team_similarity(away, str(a.get("name") or ""))) / 2
        swapped = (_team_similarity(home, str(a.get("name") or "")) + _team_similarity(away, str(h.get("name") or ""))) / 2
        score = max(direct, swapped * 0.70)
        fixture = item.get("fixture") if isinstance(item.get("fixture"), dict) else {}
        candidate_kickoff = _parse_dt(fixture.get("date"))
        if wanted_kickoff and candidate_kickoff:
            delta = abs((candidate_kickoff - wanted_kickoff).total_seconds()) / 3600
            if delta <= 0.25:
                score += 0.30
            elif delta <= 1.5:
                score += 0.12
            elif delta > 4:
                score -= 0.40
        if score > best_score:
            best_score, best_item = score, item
    return (best_item, best_score) if best_score >= 0.72 else (None, best_score)


def _score_pair(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    home, away = node.get("home"), node.get("away")
    if home is None or away is None:
        return ""
    try:
        return f"{int(home)}:{int(away)}"
    except Exception:
        return ""


def _normalize_api_fixture(item: dict[str, Any]) -> dict[str, Any]:
    fixture = item.get("fixture") if isinstance(item.get("fixture"), dict) else {}
    status = fixture.get("status") if isinstance(fixture.get("status"), dict) else {}
    teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
    home_team = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away_team = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    goals = item.get("goals") if isinstance(item.get("goals"), dict) else {}
    scores = item.get("score") if isinstance(item.get("score"), dict) else {}
    short = str(status.get("short") or "").upper()
    finished_codes = {"FT", "AET", "PEN", "AWD", "WO"}
    live_codes = {"1H", "HT", "2H", "ET", "BT", "P", "INT", "LIVE"}
    current_score = _score_pair(goals)
    if not current_score and short in finished_codes:
        current_score = _score_pair(scores.get("fulltime"))
    halftime_score = _score_pair(scores.get("halftime"))
    elapsed = status.get("elapsed")
    extra = status.get("extra")
    minute = ""
    if elapsed is not None:
        try:
            minute = str(int(elapsed))
        except Exception:
            minute = str(elapsed)
        if extra:
            try:
                minute += f"+{int(extra)}"
            except Exception:
                pass
        minute += "′"
    return {
        "fixture_id": str(fixture.get("id") or ""),
        "kickoff": (_parse_dt(fixture.get("date")) or datetime.now(timezone.utc)).isoformat(),
        "home": str(home_team.get("name") or ""),
        "away": str(away_team.get("name") or ""),
        "score": current_score,
        "halftime_score": halftime_score,
        "halftime": short == "HT",
        "finished": short in finished_codes,
        "started": short in live_codes or short in finished_codes,
        "status": short or str(status.get("long") or "").upper(),
        "minute": minute,
        "home_logo": str(home_team.get("logo") or ""),
        "away_logo": str(away_team.get("logo") or ""),
        "source": "API-Football",
    }


def _api_overlay_key(game: dict[str, Any]) -> str:
    return "|".join([
        str(game.get("kickoff") or "")[:16],
        _norm_team(str(game.get("home") or "")),
        _norm_team(str(game.get("away") or "")),
    ])


HALFTIME_CONFIRMED_API_STATUSES = {"HT", "2H", "ET", "BT", "P", "FT", "AET", "PEN", "AWD", "WO"}


def _api_status_confirms_halftime(status: Any) -> bool:
    return str(status or "").strip().upper() in HALFTIME_CONFIRMED_API_STATUSES


def _recompute_block_flags(blocks: list[dict[str, Any]]) -> None:
    for block in blocks:
        games = block.get("games") or []
        block["complete"] = bool(games) and all(bool(g.get("finished")) and bool(g.get("score")) for g in games)
        # A score in score.halftime is NOT proof that the referee has blown for
        # halftime. API-Football can expose that field while status is still 1H.
        # Only a previously confirmed HT/2H/FT state counts for the push.
        block["halftime"] = bool(games) and all(
            bool(g.get("halftime_score")) and bool(g.get("halftime_confirmed"))
            for g in games
        )


def _choose_kicktipp_livebox_row(rows: list[dict[str, Any]], game: dict[str, Any]) -> tuple[dict[str, Any] | None, float]:
    wanted_kickoff = _parse_dt(game.get("kickoff"))
    best: dict[str, Any] | None = None
    best_score = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_kickoff = _parse_dt(row.get("kickoff"))
        direct = (_team_similarity(str(game.get("home") or ""), str(row.get("home") or "")) +
                  _team_similarity(str(game.get("away") or ""), str(row.get("away") or ""))) / 2
        swapped = (_team_similarity(str(game.get("home") or ""), str(row.get("away") or "")) +
                   _team_similarity(str(game.get("away") or ""), str(row.get("home") or ""))) / 2
        score = max(direct, swapped * 0.65)
        if wanted_kickoff and row_kickoff:
            delta_minutes = abs((wanted_kickoff - row_kickoff).total_seconds()) / 60
            if delta_minutes <= 2:
                score += 0.35
            elif delta_minutes <= 15:
                score += 0.18
            elif delta_minutes > 30:
                score -= 0.50
        if score > best_score:
            best_score, best = score, row
    return (best, best_score) if best_score >= 0.78 else (None, best_score)


def _apply_kicktipp_livebox_rows(blocks: list[dict[str, Any]], rows_by_date: dict[str, list[dict[str, Any]]]) -> None:
    for block in blocks:
        for game in block.get("games") or []:
            kickoff = _parse_dt(game.get("kickoff"))
            if kickoff is None:
                continue
            local_date = kickoff.astimezone(BERLIN_TZ).strftime("%Y-%m-%d")
            row, confidence = _choose_kicktipp_livebox_row(rows_by_date.get(local_date) or [], game)
            if row is None:
                continue
            score = str(row.get("score") or "")
            status = str(row.get("status") or "").upper()
            # Always use Kicktipp's running score when available. For state changes
            # only explicit Livebox signals are used: red=LIVE, black=FINISHED.
            if score:
                game["score"] = score
                game["started"] = True
            if status == "LIVE":
                game["started"] = True
                game["finished"] = False
                game["status"] = "LIVE"
            elif status == "FINISHED":
                game["started"] = True
                game["finished"] = True
                game["status"] = "FINISHED"
            elif status == "SCHEDULED" and not game.get("started"):
                game["status"] = "SCHEDULED"
            elif status == "UNKNOWN":
                # Never keep OpenLigaDB's wall-clock based LIVE assumption when
                # Kicktipp itself could not prove red/live or black/finished.
                game["status"] = "UNKNOWN"
                game["finished"] = False
            game["kicktipp_detail_url"] = str(row.get("detail_url") or "")
            game["kicktipp_confidence"] = round(confidence, 3)
            game["livebox_style_tokens"] = row.get("style_tokens") or []
            game["schedule_source"] = game.get("schedule_source") or game.get("source") or ""
            game["source"] = "Kicktipp Livebox"
    _recompute_block_flags(blocks)


def _refresh_kicktipp_livebox(
    state: dict[str, Any],
    blocks: list[dict[str, Any]],
    now: datetime,
    *,
    allow_refresh: bool,
) -> tuple[dict[str, Any], list[str]]:
    cache = state.get("kicktipp_livebox") if isinstance(state.get("kicktipp_livebox"), dict) else {}
    dates_cache = cache.get("dates") if isinstance(cache.get("dates"), dict) else {}
    errors: list[str] = []

    rows_by_date: dict[str, list[dict[str, Any]]] = {}
    for date_key, entry in dates_cache.items():
        if isinstance(entry, dict) and isinstance(entry.get("rows"), list):
            rows_by_date[str(date_key)] = entry["rows"]
    _apply_kicktipp_livebox_rows(blocks, rows_by_date)
    if not allow_refresh:
        return cache, errors

    relevant_dates: set[str] = set()
    for block in blocks:
        kickoff = _parse_dt(block.get("kickoff"))
        if kickoff is None:
            continue
        # We only need the livebox around an actual match: ten minutes before
        # kickoff until four hours afterwards covers ET/penalties as well.
        if kickoff - timedelta(minutes=10) <= now <= kickoff + timedelta(hours=4):
            relevant_dates.add(kickoff.astimezone(BERLIN_TZ).strftime("%Y-%m-%d"))
    if not relevant_dates:
        return cache, errors

    changed = False
    for local_date in sorted(relevant_dates):
        entry = dates_cache.get(local_date) if isinstance(dates_cache.get(local_date), dict) else {}
        updated_at = _parse_dt(entry.get("updated_at"))
        if updated_at is not None and (now - updated_at).total_seconds() < KICKTIPP_LIVEBOX_REFRESH_SECONDS:
            continue
        try:
            rows, url = fetch_livebox(local_date)
            dates_cache[local_date] = {"updated_at": now.isoformat(), "rows": rows, "url": url}
            rows_by_date[local_date] = rows
            changed = True
        except Exception as exc:
            errors.append(f"Kicktipp Livebox {local_date}: {exc}")
    if changed:
        _apply_kicktipp_livebox_rows(blocks, rows_by_date)
    cache = {"updated_at": now.isoformat(), "dates": dates_cache, "source": "Kicktipp Livebox"}
    return cache, errors


def _apply_halftime_cache(blocks: list[dict[str, Any]], cache: dict[str, Any]) -> None:
    # Ignore pre-0.1.27 cache entries. Older versions treated a populated
    # halftime-score field as confirmation even when API status was still 1H.
    if int(cache.get("schema_version") or 0) != 2:
        _recompute_block_flags(blocks)
        return
    block_cache = cache.get("blocks") if isinstance(cache.get("blocks"), dict) else {}
    for block in blocks:
        entry = block_cache.get(str(block.get("key") or ""))
        if not isinstance(entry, dict):
            continue
        scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
        statuses = entry.get("statuses") if isinstance(entry.get("statuses"), dict) else {}
        fixture_ids = entry.get("fixture_ids") if isinstance(entry.get("fixture_ids"), dict) else {}
        for game in block.get("games") or []:
            game_key = _api_overlay_key(game)
            score = str(scores.get(game_key) or "")
            status = str(statuses.get(game_key) or "").upper()
            confirmed = bool(score) and _api_status_confirms_halftime(status)
            if confirmed:
                game["halftime_score"] = score
                game["halftime_confirmed"] = True
            else:
                # OpenLigaDB may already expose a phase score. Keep it from
                # accidentally driving the push until API-Football confirms HT.
                game["halftime_confirmed"] = False
            if fixture_ids.get(game_key):
                game["api_fixture_id"] = str(fixture_ids[game_key])
    _recompute_block_flags(blocks)

def _refresh_api_halftime_sensor(
    options: dict[str, Any],
    state: dict[str, Any],
    blocks: list[dict[str, Any]],
    now: datetime,
    *,
    allow_refresh: bool,
) -> tuple[dict[str, Any], list[str]]:
    api_key = str(options.get("api_football_key") or "").strip()
    cache = state.get("api_football_halftime") if isinstance(state.get("api_football_halftime"), dict) else {}
    if int(cache.get("schema_version") or 0) != 2:
        cache = {"schema_version": 2, "blocks": {}, "source": "API-Football (nur Halbzeit, bestätigt)"}
    block_cache = cache.get("blocks") if isinstance(cache.get("blocks"), dict) else {}
    errors: list[str] = []
    _apply_halftime_cache(blocks, cache)
    if not api_key or not allow_refresh:
        return cache, errors

    due_blocks: list[dict[str, Any]] = []
    for block in blocks:
        kickoff = _parse_dt(block.get("kickoff"))
        block_key = str(block.get("key") or "")
        cached_entry = block_cache.get(block_key) if isinstance(block_cache.get(block_key), dict) else {}
        if kickoff is None or bool(block.get("complete")) or bool(block.get("halftime")) or bool(cached_entry.get("completed")):
            continue
        # API-Football is *only* a halftime sensor. Start at planned +45 minutes
        # and query once per minute until every game in the kickoff block has a
        # halftime score. No API-Football polling happens before or after this.
        if kickoff + timedelta(minutes=45) <= now <= kickoff + timedelta(hours=2, minutes=15):
            due_blocks.append(block)
    if not due_blocks:
        return cache, errors

    try:
        poll_seconds = max(60, int(options.get("api_football_halftime_poll_seconds", 60) or 60))
    except Exception:
        poll_seconds = 60
    last_query = _parse_dt(cache.get("last_query"))
    if last_query is not None and (now - last_query).total_seconds() < poll_seconds:
        return cache, errors

    local_dates = sorted({(_parse_dt(b.get("kickoff")) or now).astimezone(BERLIN_TZ).strftime("%Y-%m-%d") for b in due_blocks})
    rate = dict(cache.get("rate") or {}) if isinstance(cache.get("rate"), dict) else {}
    try:
        fixtures_by_date: dict[str, list[dict[str, Any]]] = {}
        for local_date in local_dates:
            fixtures, current_rate = _api_football_get_day(api_key, local_date)
            fixtures_by_date[local_date] = fixtures
            if current_rate:
                rate = current_rate
        for block in due_blocks:
            key = str(block.get("key") or "")
            entry = block_cache.get(key) if isinstance(block_cache.get(key), dict) else {}
            scores = dict(entry.get("scores") or {}) if isinstance(entry.get("scores"), dict) else {}
            statuses = dict(entry.get("statuses") or {}) if isinstance(entry.get("statuses"), dict) else {}
            fixture_ids = dict(entry.get("fixture_ids") or {}) if isinstance(entry.get("fixture_ids"), dict) else {}
            local_date = (_parse_dt(block.get("kickoff")) or now).astimezone(BERLIN_TZ).strftime("%Y-%m-%d")
            fixtures = fixtures_by_date.get(local_date) or []
            sensor_games = _push_games_for_block(block)
            for game in sensor_games:
                game_key = _api_overlay_key(game)
                if scores.get(game_key):
                    continue
                fixture, confidence = _choose_api_fixture(fixtures, game)
                if fixture is None:
                    continue
                normalized = _normalize_api_fixture(fixture)
                api_status = str(normalized.get("status") or "").upper()
                statuses[game_key] = api_status
                # Crucial: do not capture/complete a halftime result while status
                # is still 1H, even if score.halftime is already populated.
                if normalized.get("halftime_score") and _api_status_confirms_halftime(api_status):
                    scores[game_key] = normalized["halftime_score"]
                if normalized.get("fixture_id"):
                    fixture_ids[game_key] = normalized["fixture_id"]
            completed = bool(sensor_games) and all(
                bool(scores.get(_api_overlay_key(g)))
                and _api_status_confirms_halftime(statuses.get(_api_overlay_key(g)))
                for g in sensor_games
            )
            block_cache[key] = {
                "kickoff": block.get("kickoff"),
                "scores": scores,
                "statuses": statuses,
                "fixture_ids": fixture_ids,
                "completed": completed,
                "updated_at": now.isoformat(),
            }
        cache = {
            "schema_version": 2,
            "last_query": now.isoformat(),
            "blocks": block_cache,
            "rate": rate,
            "source": "API-Football (nur Halbzeit, bestätigt)",
        }
        _apply_halftime_cache(blocks, cache)
    except Exception as exc:
        errors.append(f"API-Football Halbzeit: {exc}")
    return cache, errors

def _uefa_status_text(raw: dict[str, Any]) -> str:
    status = str(raw.get("status") or raw.get("matchStatus") or "").strip().upper()
    phase = str(raw.get("phase") or raw.get("period") or raw.get("matchPhase") or "").strip().upper()
    return " ".join(x for x in (status, phase) if x)


def _uefa_is_halftime(raw: dict[str, Any]) -> bool:
    text = _uefa_status_text(raw).replace("-", "_").replace(" ", "_")
    return any(token in text for token in ("HALF_TIME", "HALFTIME", "HALF__TIME")) or text == "HT"


def _uefa_minute(raw: dict[str, Any]) -> str:
    candidates = [
        raw.get("minute"), raw.get("matchMinute"), raw.get("currentMinute"),
        raw.get("clock"), raw.get("matchClock"), raw.get("timeElapsed"),
    ]
    for value in candidates:
        if isinstance(value, dict):
            value = value.get("minute") or value.get("display") or value.get("value")
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        m = re.search(r"(\d{1,3})(?:['’])?", text)
        if m:
            return m.group(1) + "′"
    return ""


def _uefa_final_score(match: dict[str, Any]) -> str:
    score = match.get("score")
    if not isinstance(score, dict):
        return ""
    total = score.get("total") if isinstance(score.get("total"), dict) else None
    regular = score.get("regular") if isinstance(score.get("regular"), dict) else None
    chosen = total or regular
    if not isinstance(chosen, dict):
        return ""
    home = chosen.get("home")
    away = chosen.get("away")
    if home is None or away is None:
        return ""
    try:
        text = f"{int(home)}:{int(away)}"
    except Exception:
        return ""
    penalty = score.get("penalty") if isinstance(score.get("penalty"), dict) else None
    if penalty and penalty.get("home") is not None and penalty.get("away") is not None:
        try:
            text += f" ({int(penalty['home'])}:{int(penalty['away'])} i.E.)"
        except Exception:
            pass
    return text


def _match_in_window(kickoff: datetime | None, now: datetime) -> bool:
    if kickoff is None:
        return False
    return now - timedelta(days=7) <= kickoff <= now + timedelta(days=7)


def _normalize_openliga_matches(payload: Any, shortcut: str, season: int, now: datetime) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    matches: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        kickoff = _parse_dt(raw.get("matchDateTimeUTC") or raw.get("matchDateTime"))
        if not _match_in_window(kickoff, now):
            continue
        home = _openliga_team_name(raw.get("team1"))
        away = _openliga_team_name(raw.get("team2"))
        if not home or not away:
            continue
        match_id = str(raw.get("matchID") or raw.get("matchId") or "").strip()
        if not match_id:
            continue
        actual_season = str(raw.get("leagueSeason") or season)
        halftime_score = _openliga_score_by_kind(raw, "halftime")
        final_score = _openliga_final_score(raw)
        kickoff_passed = bool(kickoff and now >= kickoff)
        finished = bool(raw.get("matchIsFinished"))
        running_score = final_score if finished else _openliga_live_score(raw, started=kickoff_passed)
        team1 = raw.get("team1") if isinstance(raw.get("team1"), dict) else {}
        team2 = raw.get("team2") if isinstance(raw.get("team2"), dict) else {}
        matches.append({
            "id": f"openliga:{shortcut}:{actual_season}:{match_id}",
            "provider_id": match_id,
            "kickoff": kickoff.isoformat() if kickoff else "",
            "home": home,
            "away": away,
            "score": running_score or halftime_score,
            "halftime_score": halftime_score,
            "halftime_confirmed": False,
            "halftime": False,
            "finished": finished,
            "started": kickoff_passed,
            "status": "FINISHED" if finished else ("LIVE" if kickoff_passed else "SCHEDULED"),
            "minute": "",
            "home_logo": str(team1.get("teamIconUrl") or ""),
            "away_logo": str(team2.get("teamIconUrl") or ""),
            "source": "OpenLigaDB",
        })
    return matches


def _fetch_openliga_current_matchday(shortcut: str, season: int, now: datetime) -> list[dict[str, Any]]:
    # OpenLigaDB offers the current matchday without a season/group parameter.
    # This keeps the 60-second Bundesliga check small instead of downloading all
    # 306 season matches every time.
    payload = _request_json(f"{OPENLIGA_BASE}/getmatchdata/{shortcut}")
    return _normalize_openliga_matches(payload, shortcut, season, now)


def _fetch_openliga_season(shortcut: str, season: int, now: datetime) -> list[dict[str, Any]]:
    payload = _request_json(f"{OPENLIGA_BASE}/getmatchdata/{shortcut}/{season}")
    return _normalize_openliga_matches(payload, shortcut, season, now)


def _competition_name_text(comp: dict[str, Any]) -> str:
    values: list[str] = []
    meta = comp.get("metaData") if isinstance(comp.get("metaData"), dict) else {}
    if meta.get("name"):
        values.append(str(meta.get("name")))
    translations = comp.get("translations") if isinstance(comp.get("translations"), dict) else {}
    for key in ("name", "tournamentName", "qualifyingName"):
        node = translations.get(key)
        if isinstance(node, dict):
            values.extend(str(v) for v in node.values() if isinstance(v, str))
        elif isinstance(node, str):
            values.append(node)
    return " | ".join(values).lower()


def _discover_uefa_competition_ids() -> dict[str, str]:
    payload = _request_json(UEFA_COMPETITIONS_URL)
    if not isinstance(payload, list):
        raise RuntimeError("UEFA-Wettbewerbsliste hat ein unerwartetes Format")
    found: dict[str, str] = {}
    for comp in payload:
        if not isinstance(comp, dict):
            continue
        if str(comp.get("sportsType") or "FOOTBALL").upper() != "FOOTBALL":
            continue
        if str(comp.get("teamCategory") or "CLUB").upper() != "CLUB":
            continue
        if str(comp.get("sex") or "MALE").upper() != "MALE":
            continue
        if str(comp.get("age") or "ADULT").upper() != "ADULT":
            continue
        comp_id = str(comp.get("id") or "").strip()
        if not comp_id:
            continue
        text = _competition_name_text(comp)
        if "conference league" in text:
            found.setdefault("uecl", comp_id)
        elif "europa league" in text:
            found.setdefault("uel", comp_id)
        elif "champions league" in text and "youth" not in text and "women" not in text and "frauen" not in text:
            found.setdefault("ucl", comp_id)
    return found


def _resolve_uefa_ids(state: dict[str, Any], now: datetime) -> tuple[dict[str, str], dict[str, Any]]:
    cache = state.get("uefa_competitions") if isinstance(state.get("uefa_competitions"), dict) else {}
    ids = {str(k): str(v) for k, v in (cache.get("ids") or {}).items() if v}
    # The previous release could persist the obsolete Europa-League fallback id "3".
    # Force one rediscovery/fallback so upgraded installations do not keep
    # using that stale ID for another 24 hours.
    if ids.get("uel") == "3":
        ids.pop("uel", None)
    refreshed_at = _parse_dt(cache.get("updated_at"))
    last_attempt_at = _parse_dt(cache.get("last_attempt_at"))
    stale_or_incomplete = (
        refreshed_at is None
        or now - refreshed_at > UEFA_COMPETITION_REFRESH
        or any(k not in ids for k in UEFA_COMPETITION_FALLBACKS)
    )
    retry_allowed = last_attempt_at is None or now - last_attempt_at >= UEFA_RETRY_AFTER_ERROR
    needs_refresh = stale_or_incomplete and retry_allowed
    if needs_refresh:
        try:
            discovered = _discover_uefa_competition_ids()
            ids.update(discovered)
            cache = {
                "ids": ids,
                "updated_at": now.isoformat(),
                "last_attempt_at": now.isoformat(),
                "source": "uefa-discovery",
            }
        except Exception as exc:
            cache = {
                "ids": ids,
                "updated_at": cache.get("updated_at"),
                "last_attempt_at": now.isoformat(),
                "error": str(exc),
            }
    for key, value in UEFA_COMPETITION_FALLBACKS.items():
        ids.setdefault(key, value)
    cache["ids"] = ids
    return ids, cache


def _fetch_uefa_schedule_matches(comp_key: str, competition_id: str, season: int) -> list[dict[str, Any]]:
    # Full competition fixtures are only refreshed every 30 minutes. After that,
    # the much smaller livescore endpoint supplies minute-by-minute status/score
    # updates. This avoids downloading complete UEFA seasons every 60 seconds.
    offset = 0
    limit = 100
    payload_all: list[dict[str, Any]] = []
    while True:
        payload = _request_json(
            UEFA_MATCHES_URL,
            params={
                "competitionId": competition_id,
                "seasonYear": season,
                "order": "ASC",
                "limit": limit,
                "offset": offset,
            },
        )
        if not isinstance(payload, list):
            break
        payload_all.extend(x for x in payload if isinstance(x, dict))
        if len(payload) < limit or offset >= 1900:
            break
        offset += limit

    matches: list[dict[str, Any]] = []
    for raw in payload_all:
        kickoff_info = raw.get("kickOffTime") if isinstance(raw.get("kickOffTime"), dict) else {}
        kickoff = _parse_dt(kickoff_info.get("dateTime") or kickoff_info.get("date"))
        if kickoff is None:
            continue
        home_team = raw.get("homeTeam") if isinstance(raw.get("homeTeam"), dict) else {}
        away_team = raw.get("awayTeam") if isinstance(raw.get("awayTeam"), dict) else {}
        home_country = str(home_team.get("countryCode") or "").upper()
        away_country = str(away_team.get("countryCode") or "").upper()
        home = _uefa_team_name(home_team)
        away = _uefa_team_name(away_team)
        match_id = str(raw.get("id") or "").strip()
        if not home or not away or not match_id:
            continue
        matches.append({
            "id": f"uefa:{comp_key}:{season}:{match_id}",
            "provider_id": match_id,
            "kickoff": kickoff.isoformat(),
            "home": home,
            "away": away,
            "score": _uefa_final_score(raw),
            "halftime_score": "",
            "halftime": _uefa_is_halftime(raw),
            "finished": str(raw.get("status") or "").upper() == "FINISHED",
            "started": str(raw.get("status") or "").upper() not in ("", "SCHEDULED", "UPCOMING"),
            "status": str(raw.get("status") or "SCHEDULED").upper(),
            "minute": _uefa_minute(raw),
            "home_logo": str(home_team.get("logoUrl") or home_team.get("logo") or ""),
            "away_logo": str(away_team.get("logoUrl") or away_team.get("logo") or ""),
            "home_country": home_country,
            "away_country": away_country,
            "source": "UEFA",
        })
    return matches


def _uefa_schedule_cache_entry_needs_refresh(
    entry: dict[str, Any], competition_id: str, season: int, now: datetime
) -> bool:
    if int(entry.get("schema_version") or 0) != 4:
        return True
    if str(entry.get("competition_id") or "") != str(competition_id):
        return True
    if int(entry.get("season") or -1) != int(season):
        return True
    refreshed_at = _parse_dt(entry.get("updated_at"))
    if refreshed_at is not None and now - refreshed_at <= UEFA_SCHEDULE_REFRESH:
        return False
    last_attempt = _parse_dt(entry.get("last_attempt_at"))
    if refreshed_at is None and last_attempt is not None and now - last_attempt < UEFA_RETRY_AFTER_ERROR:
        return False
    return True


def _refresh_uefa_schedule_cache(
    state: dict[str, Any],
    enabled_keys: list[str],
    competition_ids: dict[str, str],
    season: int,
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    root = state.get("uefa_schedule_cache") if isinstance(state.get("uefa_schedule_cache"), dict) else {}
    competitions = root.get("competitions") if isinstance(root.get("competitions"), dict) else {}
    errors: list[str] = []

    for comp_key in enabled_keys:
        competition_id = str(competition_ids.get(comp_key) or "")
        if not competition_id:
            continue
        entry = competitions.get(comp_key) if isinstance(competitions.get(comp_key), dict) else {}
        if not _uefa_schedule_cache_entry_needs_refresh(entry, competition_id, season, now):
            continue
        previous_matches = entry.get("matches") if isinstance(entry.get("matches"), list) else []
        try:
            matches = _fetch_uefa_schedule_matches(comp_key, competition_id, season)
            competitions[comp_key] = {
                "schema_version": 4,
                "competition_id": competition_id,
                "season": season,
                "updated_at": now.isoformat(),
                "last_attempt_at": now.isoformat(),
                "matches": matches,
            }
        except Exception as exc:
            competitions[comp_key] = {
                "schema_version": 4,
                "competition_id": competition_id,
                "season": season,
                "updated_at": entry.get("updated_at"),
                "last_attempt_at": now.isoformat(),
                "matches": previous_matches,
                "error": str(exc),
            }
            errors.append(f"{COMPETITIONS[comp_key]['label']}/UEFA-Spielplan: {exc}")

    root = {"competitions": competitions}
    state["uefa_schedule_cache"] = root
    return root, errors


def _openliga_uefa_fallback(comp_key: str, season: int, now: datetime) -> tuple[list[dict[str, Any]], str]:
    """Fallback for current UEFA matchdays when the UEFA schedule feed is empty.

    OpenLigaDB mirrors the complete current matchday for Champions League and
    Europa League. It is deliberately only used when UEFA returned no cached
    fixtures, so normal UEFA IDs/logos/live status remain the primary source.
    """
    candidates: tuple[tuple[str, bool], ...]
    if comp_key == "ucl":
        candidates = (("ucl", False), (f"ucl{season}", True))
    elif comp_key == "uel":
        candidates = ((f"uel{season}", True), ("uel", False))
    else:
        return [], ""
    last_error = ""
    for shortcut, use_season in candidates:
        try:
            matches = _fetch_openliga_season(shortcut, season, now) if use_season else _fetch_openliga_current_matchday(shortcut, season, now)
            if matches:
                return matches, shortcut
        except Exception as exc:
            last_error = str(exc)
    return [], last_error


def _same_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_kickoff = _parse_dt(left.get("kickoff"))
    right_kickoff = _parse_dt(right.get("kickoff"))
    if left_kickoff is not None and right_kickoff is not None:
        if abs((left_kickoff - right_kickoff).total_seconds()) > 6 * 3600:
            return False
    home_score = _team_similarity(str(left.get("home") or ""), str(right.get("home") or ""))
    away_score = _team_similarity(str(left.get("away") or ""), str(right.get("away") or ""))
    return home_score >= 0.72 and away_score >= 0.72


def _merge_schedule_matches(primary: list[dict[str, Any]], supplement: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge independent fixture sources without creating duplicate games.

    UEFA stays the preferred source for IDs/status/logos. OpenLigaDB is used as
    a cross-check for complete current matchdays. This is intentionally a merge,
    not a fallback-only path: a partially stale UEFA cache must never hide games
    that are already present in OpenLigaDB.
    """
    merged = [dict(match) for match in primary if isinstance(match, dict)]
    for extra in supplement:
        if not isinstance(extra, dict):
            continue
        existing = next((match for match in merged if _same_match(match, extra)), None)
        if existing is None:
            merged.append(dict(extra))
            continue

        # Preserve UEFA's stable provider id/logo when available, but let the
        # second source fill gaps and advance a clearly newer live/final state.
        for key in ("home_logo", "away_logo", "home_country", "away_country", "halftime_score", "minute"):
            if not existing.get(key) and extra.get(key):
                existing[key] = extra.get(key)
        if not existing.get("score") and extra.get("score"):
            existing["score"] = extra.get("score")
        if bool(extra.get("finished")) and not bool(existing.get("finished")):
            existing["finished"] = True
            existing["started"] = True
            existing["status"] = "FINISHED"
            if extra.get("score"):
                existing["score"] = extra.get("score")
        elif bool(extra.get("started")) and not bool(existing.get("started")):
            existing["started"] = True
            existing["status"] = str(extra.get("status") or "LIVE")
            if extra.get("score"):
                existing["score"] = extra.get("score")
        sources = [s for s in (str(existing.get("source") or ""), str(extra.get("source") or "")) if s]
        if sources:
            existing["source"] = " + ".join(dict.fromkeys(sources))
    merged.sort(key=lambda match: str(match.get("kickoff") or ""))
    return merged


def _fetch_uefa_livescore() -> dict[str, dict[str, Any]]:
    payload = _request_json(UEFA_LIVESCORE_URL)
    # Current UEFA response is a list; tolerate an items wrapper should the feed
    # adopt the same envelope as another UEFA endpoint in the future.
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("matches") or []
    if not isinstance(payload, list):
        raise RuntimeError("UEFA-Livescore hat ein unerwartetes Format")
    result: dict[str, dict[str, Any]] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        match_id = str(raw.get("id") or "").strip()
        if match_id:
            result[match_id] = raw
    return result


def _apply_uefa_livescore(matches: list[dict[str, Any]], live_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for cached in matches:
        match = dict(cached)
        provider_id = str(match.get("provider_id") or "")
        live = live_by_id.get(provider_id)
        if live:
            score = _uefa_final_score(live)
            if score:
                match["score"] = score
            status = str(live.get("status") or live.get("matchStatus") or "").upper()
            match["status"] = status or match.get("status") or "LIVE"
            match["finished"] = status == "FINISHED"
            match["halftime"] = _uefa_is_halftime(live)
            match["halftime_confirmed"] = bool(match["halftime"])
            match["started"] = status not in ("", "SCHEDULED", "UPCOMING")
            match["minute"] = _uefa_minute(live)
            if match["halftime"] and match.get("score"):
                match["halftime_score"] = match["score"]
        updated.append(match)
    return updated


def _group_blocks(comp_key: str, matches: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        kickoff = _parse_dt(match.get("kickoff"))
        if kickoff is None or not _match_in_window(kickoff, now):
            continue
        minute = kickoff.replace(second=0, microsecond=0).isoformat()
        grouped[minute].append(match)

    blocks: list[dict[str, Any]] = []
    meta = COMPETITIONS[comp_key]
    for kickoff, games in sorted(grouped.items()):
        games = sorted(games, key=lambda x: (str(x.get("home")), str(x.get("away"))))
        finished = bool(games) and all(bool(game.get("finished")) and bool(game.get("score")) for game in games)
        # A halftime score alone is insufficient. The source must also have
        # confirmed that halftime was actually reached for each game.
        halftime = bool(games) and all(
            bool(game.get("halftime_score")) and bool(game.get("halftime_confirmed"))
            for game in games
        )
        block_key = f"{comp_key}:{kickoff}"
        blocks.append({
            "key": block_key,
            "competition": comp_key,
            "competition_label": meta["label"],
            "title": meta["title"],
            "kickoff": kickoff,
            "games": games,
            "halftime": halftime,
            "complete": finished,
        })
    return blocks


def _kickoff_label(value: str) -> str:
    kickoff = _parse_dt(value)
    if kickoff is None:
        return "Spielblock beendet"
    local = kickoff.astimezone(BERLIN_TZ)
    weekdays = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    return f"{weekdays[local.weekday()]}, {local.strftime('%d.%m. · %H:%M')} Uhr"


def _favorite_names(options: dict[str, Any]) -> list[str]:
    raw = str(options.get("football_favorite_teams") or "").strip()
    values = [part.strip() for part in re.split(r"[|;\n]+", raw) if part.strip()]
    return values or list(FAVORITE_DEFAULTS)


def _favorite_name_for_game(game: dict[str, Any], options: dict[str, Any]) -> str:
    home = str(game.get("home") or "")
    away = str(game.get("away") or "")
    for favorite in _favorite_names(options):
        if _team_similarity(favorite, home) >= 0.92 or _team_similarity(favorite, away) >= 0.92:
            return favorite
    return ""


def _is_german_uefa_game(game: dict[str, Any]) -> bool:
    if str(game.get("home_country") or "").upper() == "GER" or str(game.get("away_country") or "").upper() == "GER":
        return True
    # Fallback for older/cached rows and known German club names.
    german_markers = (
        "bayern", "dortmund", "leverkusen", "leipzig", "frankfurt", "stuttgart",
        "freiburg", "union berlin", "hoffenheim", "mainz", "gladbach", "wolfsburg",
        "werder", "hamburg", "augsburg", "koln", "köln", "schalke", "heidenheim",
    )
    text = _norm_team(f"{game.get('home','')} {game.get('away','')}")
    return any(_norm_team(marker) in text for marker in german_markers)


def _push_games_for_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    games = [g for g in (block.get("games") or []) if isinstance(g, dict)]
    comp = str(block.get("competition") or "")
    if comp in UEFA_COMP_KEYS:
        return [g for g in games if _is_german_uefa_game(g)]
    if comp == "dfb_men":
        return [g for g in games if re.search(r"deutschland|germany", f"{g.get('home','')} {g.get('away','')}", re.I)]
    return games


def _phase_ready_for_games(games: list[dict[str, Any]], phase: str) -> bool:
    if not games:
        return False
    if phase == "halftime":
        return all(bool(g.get("halftime_score")) and bool(g.get("halftime_confirmed")) for g in games)
    return all(bool(g.get("finished")) and bool(g.get("score")) for g in games)


def _with_games(block: dict[str, Any], games: list[dict[str, Any]]) -> dict[str, Any]:
    clone = dict(block)
    clone["games"] = games
    clone["halftime"] = _phase_ready_for_games(games, "halftime")
    clone["complete"] = _phase_ready_for_games(games, "final")
    return clone


def _score_tuple(value: Any) -> tuple[int, int] | None:
    match = re.search(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", str(value or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _game_state_key(game: dict[str, Any]) -> str:
    return str(game.get("id") or _api_overlay_key(game))


def _build_deep_link(base_url: str, game: dict[str, Any] | None = None) -> str:
    raw = str(base_url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["view"] = "football"
        if game:
            kickoff = _parse_dt(game.get("kickoff"))
            if kickoff:
                query["date"] = kickoff.astimezone(BERLIN_TZ).strftime("%Y-%m-%d")
            game_id = _game_state_key(game)
            if game_id:
                query["match"] = game_id
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return raw


def _is_vfl_osnabrueck_game(game: dict[str, Any]) -> bool:
    home = str(game.get("home") or "")
    away = str(game.get("away") or "")
    return _team_similarity("VfL Osnabrück", home) >= 0.92 or _team_similarity("VfL Osnabrück", away) >= 0.92


def _event_push_volume(game: dict[str, Any] | None, phase: str = "") -> float:
    if not game or not _is_vfl_osnabrueck_game(game):
        return 0.0
    # Only goals and the final whistle should be audible on the VfL channel.
    # Cards and halftime stay critical but silent, just like every other match.
    return 1.0 if phase in {"goal", "final"} else 0.0


def _send_push_with_url(
    send_push: Callable[..., tuple[bool, str]],
    title: str,
    message: str,
    url: str,
    volume: float = 0.0,
) -> tuple[bool, str]:
    try:
        return send_push(title, message, url, volume)
    except TypeError:
        try:
            return send_push(title, message, url)
        except TypeError:
            return send_push(title, message)


def _goal_event_matches_expected_score(event: dict[str, Any], expected_score: str) -> bool:
    expected = _score_tuple(expected_score)
    if expected is None:
        return True
    return _score_tuple(event.get("score_after")) == expected


def _api_goal_from_events(raw_events: list[Any], game: dict[str, Any], expected_score: str = "") -> tuple[str, str]:
    expected = _score_tuple(expected_score)
    goals: list[tuple[int, int, str, str, str]] = []
    for event in raw_events:
        if not isinstance(event, dict) or str(event.get("type") or "").casefold() != "goal":
            continue
        detail = str(event.get("detail") or "").casefold()
        if "missed" in detail or "cancel" in detail:
            continue
        time_node = event.get("time") if isinstance(event.get("time"), dict) else {}
        try:
            elapsed = int(time_node.get("elapsed") or 0)
        except Exception:
            elapsed = 0
        try:
            extra = int(time_node.get("extra") or 0)
        except Exception:
            extra = 0
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        team = event.get("team") if isinstance(event.get("team"), dict) else {}
        goals.append((elapsed, extra, str(player.get("name") or "").strip(), str(team.get("name") or "").strip(), detail))
    if not goals:
        return "", ""
    goals.sort(key=lambda row: (row[0], row[1]))
    if expected is None:
        _elapsed, _extra, scorer, team, _detail = goals[-1]
        return scorer, team

    home = str(game.get("home") or "")
    away = str(game.get("away") or "")
    running_home = 0
    running_away = 0
    for _elapsed, _extra, scorer, team, detail in goals:
        home_similarity = _team_similarity(team, home)
        away_similarity = _team_similarity(team, away)
        own_goal = "own goal" in detail or "eigentor" in detail
        if home_similarity >= away_similarity and home_similarity >= 0.55:
            if own_goal:
                running_away += 1
            else:
                running_home += 1
        elif away_similarity > home_similarity and away_similarity >= 0.55:
            if own_goal:
                running_home += 1
            else:
                running_away += 1
        else:
            # An event whose team cannot be mapped reliably must not be used to
            # invent a scorer for a score transition.
            continue
        if (running_home, running_away) == expected:
            return scorer, team
    # Fallback: if the provider currently exposes exactly as many valid goal
    # events as the observed score contains, the newest goal event is the scorer
    # for this score transition even when provider team naming could not be mapped.
    expected_total = sum(expected)
    usable = [row for row in goals if row[2]]
    if expected_total > 0 and len(usable) == expected_total:
        _elapsed, _extra, scorer, team, _detail = usable[-1]
        return scorer, team
    return "", ""


def _api_goal_context(
    options: dict[str, Any],
    game: dict[str, Any],
    fixture_id: str = "",
    expected_score: str = "",
) -> tuple[str, str, str, dict[str, str]]:
    # Prefer Kicktipp because it does not consume API-Football quota. Crucially,
    # select the event whose score_after equals the newly observed score. Using
    # simply the last available event caused the scorer to lag one goal behind.
    detail_url = str(game.get("kicktipp_detail_url") or "").strip()
    if detail_url:
        try:
            detail = fetch_public_detail(
                detail_url,
                timeout=10,
                home=str(game.get("home") or ""),
                away=str(game.get("away") or ""),
            )
            goals = detail.get("events", {}).get("goals", []) if isinstance(detail, dict) else []
            named = [
                g for g in goals
                if isinstance(g, dict)
                and str(g.get("player") or "").strip()
                and "nicht erkannt" not in str(g.get("player") or "").casefold()
            ]
            exact = [g for g in named if _goal_event_matches_expected_score(g, expected_score)]
            if exact:
                goal = exact[-1]
                return str(goal.get("player") or "").strip(), str(goal.get("team") or "").strip(), fixture_id, {}
            expected = _score_tuple(expected_score)
            # Some Kicktipp layouts expose scorer/minute but omit a score_after
            # field. If the number of named goal events equals the current goal
            # total, the last event is unambiguously the newest scorer.
            if expected and len(named) == sum(expected) and named:
                goal = named[-1]
                return str(goal.get("player") or "").strip(), str(goal.get("team") or "").strip(), fixture_id, {}
        except Exception:
            pass

    api_key = str(options.get("api_football_key") or "").strip()
    if not api_key:
        return "", "", fixture_id, {}
    rate: dict[str, str] = {}
    selected_fixture: dict[str, Any] | None = None
    if not fixture_id:
        kickoff = _parse_dt(game.get("kickoff"))
        local_date = (kickoff or datetime.now(timezone.utc)).astimezone(BERLIN_TZ).strftime("%Y-%m-%d")
        fixtures, rate = _api_football_get_day(api_key, local_date)
        selected_fixture, _confidence = _choose_api_fixture(fixtures, game)
        if selected_fixture:
            fixture = selected_fixture.get("fixture") if isinstance(selected_fixture.get("fixture"), dict) else {}
            fixture_id = str(fixture.get("id") or "")
    if not fixture_id:
        return "", "", "", rate
    raw_events: list[Any] = []
    if selected_fixture and isinstance(selected_fixture.get("events"), list):
        raw_events = selected_fixture.get("events") or []
    if not raw_events:
        response = requests.get(
            API_FOOTBALL_BASE + "/fixtures/events",
            params={"fixture": fixture_id},
            headers={"x-apisports-key": api_key, "Accept": "application/json", "User-Agent": "Kicktipp-TipBot/0.1.42"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        raw_events = payload.get("response") if isinstance(payload, dict) and isinstance(payload.get("response"), list) else []
        current_rate = {
            "remaining": str(response.headers.get("x-ratelimit-requests-remaining") or ""),
            "limit": str(response.headers.get("x-ratelimit-requests-limit") or ""),
        }
        if any(current_rate.values()):
            rate = current_rate
    scorer, team = _api_goal_from_events(raw_events, game, expected_score)
    return scorer, team, fixture_id, rate


def _watch_team_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        return ""
    exact = {
        "VfL Osnabrück": "VfL Osnabrück",
        "Bayer 04 Leverkusen": "Leverkusen",
        "FC Bayern München": "Bayern",
        "Bayern München": "Bayern",
        "Borussia Dortmund": "Dortmund",
        "Eintracht Frankfurt": "Frankfurt",
        "VfB Stuttgart": "Stuttgart",
        "RB Leipzig": "Leipzig",
        "1. FC Nürnberg": "Nürnberg",
        "FC Schalke 04": "Schalke",
        "SC Paderborn 07": "Paderborn",
    }
    if name in exact:
        return exact[name]
    # Common international suffixes add little information on a watch display.
    short = re.sub(r"\s+(FC|CF|AFC|FK|SK|SC)$", "", name, flags=re.IGNORECASE).strip()
    if len(short) <= 18:
        return short
    words = short.split()
    if len(words) >= 2:
        candidate = " ".join(words[:2])
        if len(candidate) <= 18:
            return candidate
    return short[:17].rstrip() + "…"


def _push_game_chunks(games: list[dict[str, Any]], max_games: int = 4) -> list[list[dict[str, Any]]]:
    clean = [game for game in games if isinstance(game, dict)]
    size = max(1, int(max_games or 4))
    return [clean[index:index + size] for index in range(0, len(clean), size)]


def _format_push(
    block: dict[str, Any],
    phase: str = "final",
    *,
    part: int = 1,
    total_parts: int = 1,
) -> tuple[str, str]:
    phase = "halftime" if phase == "halftime" else "final"
    games = [game for game in (block.get("games") or []) if isinstance(game, dict)]
    competition = str(block.get("competition_label") or block.get("competition") or "Fußball").strip()
    count = len(games)
    icon = "⏸" if phase == "halftime" else "🏁"
    phase_word = "Halbzeit" if phase == "halftime" else "Abpfiff"
    if count == 1:
        title = f"{icon} {phase_word} · {competition}"
    else:
        title = f"{icon} {competition} · {count} Spiele"
    if total_parts > 1:
        title += f" · {part}/{total_parts}"

    lines: list[str] = []
    for game in games:
        home = _watch_team_name(game.get("home"))
        away = _watch_team_name(game.get("away"))
        score = str(game.get("halftime_score") if phase == "halftime" else game.get("score") or "").strip()
        if home and away and score:
            # One compact line per match is substantially easier to scan on Apple Watch.
            lines.append(f"{home} {score} {away}")
    if not lines:
        lines.append(_kickoff_label(str(block.get("kickoff") or "")))
    return title, "\n".join(lines)

def _read_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(state_file: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_blocks(
    options: dict[str, Any], state: dict[str, Any], now: datetime | None = None, *, allow_api_refresh: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    blocks: list[dict[str, Any]] = []
    errors: list[str] = []

    season = _season_start_year(now)
    if bool(options.get("football_bl1_enabled", True)):
        try:
            matches = _fetch_openliga_current_matchday("bl1", season, now)
            blocks.extend(_group_blocks("bl1", matches, now))
        except Exception as exc:
            errors.append(f"1. Bundesliga/OpenLigaDB: {exc}")

    if bool(options.get("football_bl2_enabled", True)):
        try:
            matches = _fetch_openliga_current_matchday("bl2", season, now)
            blocks.extend(_group_blocks("bl2", matches, now))
        except Exception as exc:
            errors.append(f"2. Bundesliga/OpenLigaDB: {exc}")

    if bool(options.get("football_dfb_enabled", True)):
        try:
            matches = _fetch_openliga_season("dfb", season, now)
            blocks.extend(_group_blocks("dfb", matches, now))
        except Exception as exc:
            errors.append(f"DFB-Pokal/OpenLigaDB: {exc}")

    if bool(options.get("football_supercup_enabled", True)):
        try:
            matches = _fetch_openliga_season("BLSupercup", now.astimezone(BERLIN_TZ).year, now)
            blocks.extend(_group_blocks("supercup", matches, now))
        except Exception as exc:
            errors.append(f"DFB-Supercup/OpenLigaDB: {exc}")

    if bool(options.get("football_germany_enabled", True)):
        try:
            # DFB-Nationalspiele are maintained as a calendar-year competition and
            # contain only a small number of fixtures, so the yearly query is cheap.
            dfb_matches = _fetch_openliga_season("DFBN", now.astimezone(BERLIN_TZ).year, now)
            dfb_matches = [
                m
                for m in dfb_matches
                if re.search(r"deutschland|germany", f"{m.get('home')} {m.get('away')}", re.I)
            ]
            blocks.extend(_group_blocks("dfb_men", dfb_matches, now))
        except Exception as exc:
            errors.append(f"Deutschland/OpenLigaDB: {exc}")

    uefa_enabled = [
        key
        for key in ("ucl", "uel", "uecl")
        if bool(options.get(COMPETITIONS[key]["enabled_option"], True))
    ]
    if uefa_enabled:
        ids, competition_cache = _resolve_uefa_ids(state, now)
        state["uefa_competitions"] = competition_cache
        schedule_cache, schedule_errors = _refresh_uefa_schedule_cache(
            state, uefa_enabled, ids, season, now
        )
        errors.extend(schedule_errors)

        try:
            live_by_id = _fetch_uefa_livescore()
        except Exception as exc:
            live_by_id = {}
            errors.append(f"UEFA-Livescore: {exc}")

        cached_competitions = (
            schedule_cache.get("competitions")
            if isinstance(schedule_cache.get("competitions"), dict)
            else {}
        )
        for comp_key in uefa_enabled:
            entry = (
                cached_competitions.get(comp_key)
                if isinstance(cached_competitions.get(comp_key), dict)
                else {}
            )
            cached_matches = entry.get("matches") if isinstance(entry.get("matches"), list) else []
            matches = _apply_uefa_livescore(cached_matches, live_by_id)

            # UCL/UEL are also maintained in OpenLigaDB at quality 100. Always
            # cross-check the current matchday, even when the UEFA cache is not
            # empty. The previous fallback-only behavior allowed a partial/stale
            # UEFA cache to hide today's fixtures completely.
            supplement_matches, supplement_info = _openliga_uefa_fallback(comp_key, season, now)
            if supplement_matches:
                matches = _merge_schedule_matches(matches, supplement_matches)
            elif not matches and supplement_info:
                errors.append(f"{COMPETITIONS[comp_key]['label']}/OpenLigaDB-Fallback: {supplement_info}")

            blocks.extend(_group_blocks(comp_key, matches, now))

    # Kicktipp's public Livebox is the primary running-score and final-status
    # source. API-Football is intentionally *not* used for continuous live data.
    livebox_cache, livebox_errors = _refresh_kicktipp_livebox(
        state, blocks, now, allow_refresh=allow_api_refresh
    )
    if livebox_cache:
        state["kicktipp_livebox"] = livebox_cache
    errors.extend(livebox_errors)

    halftime_cache, halftime_errors = _refresh_api_halftime_sensor(
        options, state, blocks, now, allow_refresh=allow_api_refresh
    )
    if halftime_cache:
        state["api_football_halftime"] = halftime_cache
    errors.extend(halftime_errors)

    _recompute_block_flags(blocks)
    blocks.sort(key=lambda block: str(block.get("kickoff") or ""))
    return blocks, state, errors


def _match_push_prefs(options: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = options.get("football_match_push_prefs")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _pref_game_stub(pref: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(pref.get("game_id") or ""),
        "home": str(pref.get("home") or ""),
        "away": str(pref.get("away") or ""),
        "kickoff": str(pref.get("kickoff") or ""),
    }


def _find_game_for_pref(blocks: list[dict[str, Any]], pref: dict[str, Any]) -> dict[str, Any] | None:
    wanted_id = str(pref.get("game_id") or "")
    wanted_home = str(pref.get("home") or "")
    wanted_away = str(pref.get("away") or "")
    wanted_kickoff = _parse_dt(pref.get("kickoff"))
    best: tuple[float, dict[str, Any]] | None = None
    for block in blocks:
        for game in block.get("games") or []:
            if wanted_id and str(game.get("id") or "") == wanted_id:
                return game
            score = (_team_similarity(wanted_home, str(game.get("home") or "")) + _team_similarity(wanted_away, str(game.get("away") or ""))) / 2
            candidate = _parse_dt(game.get("kickoff"))
            if wanted_kickoff and candidate:
                delta = abs((candidate - wanted_kickoff).total_seconds()) / 3600
                if delta <= 0.25:
                    score += 0.25
                elif delta > 2:
                    score -= 0.4
            if best is None or score > best[0]:
                best = (score, game)
    return best[1] if best and best[0] >= 0.80 else None


def _stored_pref_for_game(game: dict[str, Any], prefs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    game_id = _game_state_key(game)
    direct = prefs.get(game_id)
    if isinstance(direct, dict):
        return direct
    home = str(game.get("home") or "")
    away = str(game.get("away") or "")
    kickoff = _parse_dt(game.get("kickoff"))
    best: tuple[float, dict[str, Any]] | None = None
    for pref in prefs.values():
        if not isinstance(pref, dict):
            continue
        score = (_team_similarity(home, str(pref.get("home") or "")) + _team_similarity(away, str(pref.get("away") or ""))) / 2
        pref_kickoff = _parse_dt(pref.get("kickoff"))
        if kickoff and pref_kickoff:
            delta = abs((kickoff - pref_kickoff).total_seconds()) / 3600
            if delta <= 0.25:
                score += 0.25
            elif delta > 2:
                score -= 0.4
        if best is None or score > best[0]:
            best = (score, pref)
    return best[1] if best and best[0] >= 0.80 else {}


def _explicit_pref_value(game: dict[str, Any], prefs: dict[str, dict[str, Any]], field: str, default: bool) -> bool:
    pref = _stored_pref_for_game(game, prefs)
    if not pref or not bool(pref.get("override_defaults")):
        return default
    if bool(pref.get("mute_all")):
        return False
    return bool(pref.get(field, default))


def _phase_push_games(block: dict[str, Any], prefs: dict[str, dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    base = _push_games_for_block(block)
    return [g for g in base if _explicit_pref_value(g, prefs, phase, True)]


def _event_signature(kind: str, event: dict[str, Any]) -> str:
    fields = [
        kind,
        str(event.get("time") or ""),
        str(event.get("team") or ""),
        str(event.get("player") or event.get("player_in") or ""),
        str(event.get("player_out") or ""),
        str(event.get("card") or ""),
        str(event.get("detail") or ""),
        str(event.get("score_after") or ""),
    ]
    return "|".join(x.strip().casefold() for x in fields)


def _custom_event_message(kind: str, event: dict[str, Any], game: dict[str, Any]) -> tuple[str, str]:
    home = str(game.get("home") or "")
    away = str(game.get("away") or "")
    minute = str(event.get("time") or "").strip()
    team = str(event.get("team") or "").strip()
    player = str(event.get("player") or "").strip()
    if kind == "goal":
        score = str(event.get("score_after") or game.get("score") or "").strip()
        title = f"⚽ Tor · {score}" if score else "⚽ Tor"
        detail = str(event.get("detail") or "").strip().casefold()
        detail_de = {"normal goal": "Tor", "own goal": "Eigentor", "penalty": "Elfmeter"}.get(detail, "")
        parts = [f"{home} – {away}"]
        if player:
            parts.append(player)
        if team:
            parts.append(team)
        if detail_de and detail_de != "Tor":
            parts.append(detail_de)
        if minute:
            parts.append(minute)
        return title, " · ".join(parts)
    card = str(event.get("card") or "").casefold()
    icon = "🟥" if card == "red" else "🟨🟥" if card == "second_yellow" else "🟨"
    title = f"{icon} Karte · {home} – {away}"
    parts = [x for x in (player, team, minute) if x]
    return title, " · ".join(parts) or f"{home} – {away}"


def monitor_once(
    options: dict[str, Any],
    state_file: Path,
    send_push: Callable[..., tuple[bool, str]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not bool(options.get("football_push_enabled", True)):
        return {"enabled": False, "notifications": []}

    state = _read_state(state_file)
    blocks, state, errors = collect_blocks(options, state, now=now)
    initialized = bool(state.get("initialized"))
    observed: dict[str, Any] = dict(state.get("observed") or {})
    halftime_pushed = set(str(x) for x in (state.get("halftime_pushed") or []) if x)
    final_pushed = set(str(x) for x in (state.get("pushed") or []) if x)
    halftime_chunk_pushed = set(str(x) for x in (state.get("halftime_chunk_pushed") or []) if x)
    final_chunk_pushed = set(str(x) for x in (state.get("final_chunk_pushed") or []) if x)
    goal_observed: dict[str, Any] = dict(state.get("favorite_goal_observed") or {})
    custom_event_observed: dict[str, list[str]] = {str(k): [str(x) for x in v] for k, v in (state.get("custom_event_observed") or {}).items() if isinstance(v, list)}
    reminder_pushed = set(str(x) for x in (state.get("match_reminder_pushed") or []) if x)
    match_push_prefs = _match_push_prefs(options)
    transitions = list(state.get("recent_transitions") or []) if isinstance(state.get("recent_transitions"), list) else []
    notifications: list[dict[str, Any]] = []
    current_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base_push_url = str(options.get("football_push_url") or "")

    # Initialize without replaying old goals/HT/FT after an update or restart.
    if not initialized:
        for block in blocks:
            key = str(block.get("key") or "")
            push_games = _push_games_for_block(block)
            phase_block = _with_games(block, push_games)
            if key:
                observed[key] = {
                    "halftime": bool(phase_block.get("halftime")),
                    "complete": bool(phase_block.get("complete")),
                    "kickoff": block.get("kickoff"),
                    "competition": block.get("competition"),
                }
                if phase_block.get("halftime") or phase_block.get("complete"):
                    halftime_pushed.add(key)
                if phase_block.get("complete"):
                    final_pushed.add(key)
            for game in block.get("games") or []:
                if _favorite_name_for_game(game, options):
                    goal_observed[_game_state_key(game)] = {
                        "score": str(game.get("score") or ""),
                        "fixture_id": str(game.get("api_fixture_id") or ""),
                    }
        for pref_id, pref in match_push_prefs.items():
            kickoff_dt = _parse_dt(pref.get("kickoff"))
            if kickoff_dt and kickoff_dt > current_now:
                custom_event_observed.setdefault(pref_id, [])
        state.update({
            "initialized": True,
            "observed": observed,
            "favorite_goal_observed": goal_observed,
            "custom_event_observed": custom_event_observed,
            "match_reminder_pushed": sorted(reminder_pushed)[-500:],
            "halftime_pushed": sorted(halftime_pushed)[-500:],
            "pushed": sorted(final_pushed)[-500:],
            "halftime_chunk_pushed": sorted(halftime_chunk_pushed)[-1000:],
            "final_chunk_pushed": sorted(final_chunk_pushed)[-1000:],
            "last_errors": errors[-20:],
        })
        _write_state(state_file, state)
        return {"enabled": True, "initialized": True, "blocks": len(blocks), "notifications": [], "errors": errors}

    # Favorite matches get a 30-minute reminder by default. A per-match
    # override (including the master mute) can explicitly disable it.
    for block in blocks:
        for game in block.get("games") or []:
            favorite = _favorite_name_for_game(game, options)
            if not favorite:
                continue
            game_key = _game_state_key(game)
            if not _explicit_pref_value(game, match_push_prefs, "reminder_30", True):
                continue
            kickoff_dt = _parse_dt(game.get("kickoff"))
            if not kickoff_dt:
                continue
            minutes_until = (kickoff_dt - current_now).total_seconds() / 60.0
            if game_key in reminder_pushed or not (24.0 <= minutes_until <= 31.0):
                continue
            title = "⏰ Anpfiff in 30 Minuten"
            message = f"{game.get('home')} – {game.get('away')} · {kickoff_dt.astimezone(BERLIN_TZ).strftime('%H:%M')} Uhr"
            url = _build_deep_link(base_push_url, game)
            ok, status = _send_push_with_url(send_push, title, message, url)
            notifications.append({"key": game_key, "phase": "reminder30", "ok": ok, "status": status, "title": title, "message": message})
            if ok:
                reminder_pushed.add(game_key)
                transitions.append({"at": current_now.isoformat(), "phase": "reminder30", "game": f"{game.get('home')} – {game.get('away')}"})

    # Per-match opt-in pushes configured from the match center.
    for pref_id, pref in match_push_prefs.items():
        kickoff_dt = _parse_dt(pref.get("kickoff"))
        if not kickoff_dt or bool(pref.get("mute_all")):
            continue
        minutes_until = (kickoff_dt - current_now).total_seconds() / 60.0
        stub = _pref_game_stub(pref)
        # Reminder window is deliberately a little wider than one polling interval
        # so a busy Home Assistant host cannot miss the 30-minute notification.
        if bool(pref.get("reminder_30")) and pref_id not in reminder_pushed and 24.0 <= minutes_until <= 31.0:
            title = "⏰ Anpfiff in 30 Minuten"
            message = f"{pref.get('home')} – {pref.get('away')} · {kickoff_dt.astimezone(BERLIN_TZ).strftime('%H:%M')} Uhr"
            url = _build_deep_link(base_push_url, stub)
            ok, status = _send_push_with_url(send_push, title, message, url)
            notifications.append({"key": pref_id, "phase": "reminder30", "ok": ok, "status": status, "title": title, "message": message})
            if ok:
                reminder_pushed.add(pref_id)
                transitions.append({"at": current_now.isoformat(), "phase": "reminder30", "game": f"{pref.get('home')} – {pref.get('away')}"})

        if not (bool(pref.get("goals")) or bool(pref.get("cards"))):
            continue
        # Poll events only while a selected game can actually be running.
        if current_now < kickoff_dt - timedelta(minutes=2) or current_now > kickoff_dt + timedelta(hours=4):
            continue
        game = _find_game_for_pref(blocks, pref) or stub
        if bool(game.get("finished")):
            continue
        detail_url = str(game.get("kicktipp_detail_url") or pref.get("detail_url") or "").strip()
        if not detail_url:
            try:
                detail_url = resolve_public_detail_url(
                    str(pref.get("competition_label") or ""),
                    str(pref.get("home") or ""),
                    str(pref.get("away") or ""),
                    str(pref.get("kickoff") or ""),
                    timeout=10,
                )
            except Exception as exc:
                errors.append(f"Spiel-Push Detail-Link {pref.get('home')} – {pref.get('away')}: {exc}")
                detail_url = ""
        if not detail_url:
            continue
        try:
            detail = fetch_public_detail(
                detail_url,
                timeout=10,
                home=str(pref.get("home") or game.get("home") or ""),
                away=str(pref.get("away") or game.get("away") or ""),
            )
        except Exception as exc:
            errors.append(f"Spiel-Push Events {pref.get('home')} – {pref.get('away')}: {exc}")
            continue
        events = detail.get("events") if isinstance(detail, dict) and isinstance(detail.get("events"), dict) else {}
        candidates: list[tuple[str, dict[str, Any]]] = []
        if bool(pref.get("goals")):
            candidates.extend(("goal", e) for e in (events.get("goals") or []) if isinstance(e, dict))
        if bool(pref.get("cards")):
            candidates.extend(("card", e) for e in (events.get("cards") or []) if isinstance(e, dict))
        signatures = [_event_signature(kind, event) for kind, event in candidates]
        prior = set(custom_event_observed.get(pref_id) or [])
        enabled_at = _parse_dt(pref.get("enabled_at"))
        # If the user only enabled notifications after kickoff, do not replay all
        # earlier events on the first poll; establish them as the baseline instead.
        if pref_id not in custom_event_observed and enabled_at and enabled_at > kickoff_dt + timedelta(minutes=1):
            custom_event_observed[pref_id] = signatures[-100:]
            continue
        for (kind, event), signature in zip(candidates, signatures):
            if signature in prior:
                continue
            # Favorite matches already have their dedicated score-change goal push.
            # Avoid duplicate goal notifications while still allowing card opt-ins.
            if kind == "goal" and _favorite_name_for_game(game, options):
                prior.add(signature)
                continue
            title, message = _custom_event_message(kind, event, game)
            url = _build_deep_link(base_push_url, game)
            ok, status = _send_push_with_url(send_push, title, message, url, _event_push_volume(game, kind))
            notifications.append({"key": pref_id, "phase": kind, "ok": ok, "status": status, "title": title, "message": message})
            if ok:
                prior.add(signature)
                transitions.append({"at": current_now.isoformat(), "phase": f"custom_{kind}", "game": f"{game.get('home')} – {game.get('away')}"})
        custom_event_observed[pref_id] = list(prior)[-100:]

    # Favorite goal pushes are independent from block HT/FT pushes.
    for block in blocks:
        for game in block.get("games") or []:
            favorite = _favorite_name_for_game(game, options)
            if not favorite:
                continue
            if not _explicit_pref_value(game, match_push_prefs, "goals", True):
                # Keep the observation baseline current so re-enabling later does
                # not replay goals that happened while this match was muted.
                goal_observed[_game_state_key(game)] = {
                    "score": str(game.get("score") or ""),
                    "fixture_id": str(game.get("api_fixture_id") or ""),
                }
                continue
            kickoff_dt = _parse_dt(game.get("kickoff"))
            push_relevant = bool(kickoff_dt and current_now - timedelta(hours=5) <= kickoff_dt <= current_now + timedelta(minutes=30))
            game_key = _game_state_key(game)
            previous = goal_observed.get(game_key) if isinstance(goal_observed.get(game_key), dict) else {}
            previous_score = str(previous.get("score") or "")
            current_score = str(game.get("score") or "")
            previous_tuple = _score_tuple(previous_score)
            current_tuple = _score_tuple(current_score)
            fixture_id = str(previous.get("fixture_id") or game.get("api_fixture_id") or "")
            if previous_tuple and current_tuple and previous_tuple != current_tuple and push_relevant:
                scorer = ""
                scorer_team = ""
                rate: dict[str, str] = {}
                # Only look up a scorer for an actual goal increase. Score corrections
                # still notify immediately but do not pretend to know a scorer.
                if sum(current_tuple) > sum(previous_tuple):
                    try:
                        scorer, scorer_team, fixture_id, rate = _api_goal_context(options, game, fixture_id, current_score)
                        # Live score feeds can precede the event feed by a few seconds.
                        # Wait briefly for the exact score_after event rather than
                        # announcing the previous goal scorer again.
                        if not scorer and game.get("kicktipp_detail_url"):
                            for _attempt in range(2):
                                time.sleep(2)
                                scorer, scorer_team, fixture_id, retry_rate = _api_goal_context(options, game, fixture_id, current_score)
                                if retry_rate:
                                    rate = retry_rate
                                if scorer:
                                    break
                    except Exception as exc:
                        errors.append(f"Favoriten-Torschütze {favorite}: {exc}")
                if rate:
                    state["api_football_goal_rate"] = {**rate, "updated_at": current_now.isoformat()}
                home_name = str(game.get("home") or "")
                away_name = str(game.get("away") or "")
                title = f"⚽ TOR · {_watch_team_name(favorite)} · {current_score}"
                compact_home = _watch_team_name(home_name)
                compact_away = _watch_team_name(away_name)
                if sum(current_tuple) < sum(previous_tuple):
                    title = f"↩️ Korrektur · {_watch_team_name(favorite)} · {current_score}"
                    message = f"{compact_home} {current_score} {compact_away}"
                else:
                    first_line = scorer or "Neuer Spielstand"
                    if scorer_team and scorer and _team_similarity(scorer_team, favorite) < 0.75:
                        first_line = f"{scorer} ({_watch_team_name(scorer_team)})"
                    message = f"{first_line}\n{compact_home} {current_score} {compact_away}"
                url = _build_deep_link(base_push_url, game)
                ok, status = _send_push_with_url(send_push, title, message, url, _event_push_volume(game, "goal"))
                notifications.append({"key": game_key, "phase": "goal", "competition": block.get("competition"), "ok": ok, "status": status, "title": title, "message": message})
                if ok:
                    transitions.append({"at": current_now.isoformat(), "phase": "goal", "competition": block.get("competition"), "game": f"{game.get('home')} – {game.get('away')}", "score": current_score})
            goal_observed[game_key] = {"score": current_score, "fixture_id": fixture_id}

    for block in blocks:
        key = str(block.get("key") or "")
        if not key:
            continue
        base_push_games = _push_games_for_block(block)
        if not base_push_games:
            continue
        halftime_games = _phase_push_games(block, match_push_prefs, "halftime")
        final_games = _phase_push_games(block, match_push_prefs, "final")
        halftime_block = _with_games(block, halftime_games) if halftime_games else {**block, "games": [], "halftime": False, "complete": False}
        final_block = _with_games(block, final_games) if final_games else {**block, "games": [], "halftime": False, "complete": False}
        previous = observed.get(key) if isinstance(observed.get(key), dict) else {}
        is_halftime = bool(halftime_games) and bool(halftime_block.get("halftime"))
        is_complete = bool(final_games) and bool(final_block.get("complete"))
        kickoff_dt = _parse_dt(block.get("kickoff"))
        push_relevant = bool(kickoff_dt and current_now - timedelta(hours=12) <= kickoff_dt <= current_now + timedelta(hours=4))

        if is_halftime and push_relevant and key not in halftime_pushed:
            chunks = _push_game_chunks(halftime_games, 4)
            all_sent = True
            for index, chunk in enumerate(chunks, start=1):
                chunk_key = f"{key}:halftime:{index}/{len(chunks)}"
                if chunk_key in halftime_chunk_pushed:
                    continue
                chunk_block = _with_games(block, chunk)
                title, message = _format_push(chunk_block, "halftime", part=index, total_parts=len(chunks))
                url = _build_deep_link(base_push_url, chunk[0] if len(chunk) == 1 else None)
                volume = 1.0 if any(_event_push_volume(game, "halftime") >= 1.0 for game in chunk) else 0.0
                ok, status = _send_push_with_url(send_push, title, message, url, volume)
                notifications.append({"key": chunk_key, "phase": "halftime", "competition": block.get("competition"), "ok": ok, "status": status, "title": title, "message": message})
                if ok:
                    halftime_chunk_pushed.add(chunk_key)
                else:
                    all_sent = False
            expected_chunks = {f"{key}:halftime:{index}/{len(chunks)}" for index in range(1, len(chunks) + 1)}
            if all_sent and expected_chunks.issubset(halftime_chunk_pushed):
                halftime_pushed.add(key)
                transitions.append({"at": current_now.isoformat(), "phase": "halftime", "competition": block.get("competition"), "games": [f"{g.get('home')} – {g.get('away')}" for g in halftime_games]})

        just_completed = is_complete and not bool(previous.get("complete"))
        if just_completed and push_relevant and key not in final_pushed:
            chunks = _push_game_chunks(final_games, 4)
            all_sent = True
            for index, chunk in enumerate(chunks, start=1):
                chunk_key = f"{key}:final:{index}/{len(chunks)}"
                if chunk_key in final_chunk_pushed:
                    continue
                chunk_block = _with_games(block, chunk)
                title, message = _format_push(chunk_block, "final", part=index, total_parts=len(chunks))
                url = _build_deep_link(base_push_url, chunk[0] if len(chunk) == 1 else None)
                volume = 1.0 if any(_event_push_volume(game, "final") >= 1.0 for game in chunk) else 0.0
                ok, status = _send_push_with_url(send_push, title, message, url, volume)
                notifications.append({"key": chunk_key, "phase": "final", "competition": block.get("competition"), "ok": ok, "status": status, "title": title, "message": message})
                if ok:
                    final_chunk_pushed.add(chunk_key)
                else:
                    all_sent = False
            expected_chunks = {f"{key}:final:{index}/{len(chunks)}" for index in range(1, len(chunks) + 1)}
            if all_sent and expected_chunks.issubset(final_chunk_pushed):
                final_pushed.add(key)
                transitions.append({"at": current_now.isoformat(), "phase": "final", "competition": block.get("competition"), "games": [f"{g.get('home')} – {g.get('away')}" for g in final_games]})

        observed[key] = {
            "halftime": is_halftime,
            "complete": is_complete if key in final_pushed or not is_complete else False,
            "kickoff": block.get("kickoff"),
            "competition": block.get("competition"),
        }

    ordered_keys = list(observed.keys())[-500:]
    goal_keys = list(goal_observed.keys())[-500:]
    state.update({
        "initialized": True,
        "observed": {key: observed[key] for key in ordered_keys},
        "favorite_goal_observed": {key: goal_observed[key] for key in goal_keys},
        "custom_event_observed": {key: value[-100:] for key, value in list(custom_event_observed.items())[-500:]},
        "match_reminder_pushed": sorted(reminder_pushed)[-500:],
        "halftime_pushed": sorted(halftime_pushed)[-500:],
        "pushed": sorted(final_pushed)[-500:],
        "halftime_chunk_pushed": sorted(halftime_chunk_pushed)[-1000:],
        "final_chunk_pushed": sorted(final_chunk_pushed)[-1000:],
        "last_errors": errors[-20:],
        "last_block_count": len(blocks),
        "recent_transitions": transitions[-30:],
    })
    _write_state(state_file, state)
    return {"enabled": True, "blocks": len(blocks), "notifications": notifications, "errors": errors}
