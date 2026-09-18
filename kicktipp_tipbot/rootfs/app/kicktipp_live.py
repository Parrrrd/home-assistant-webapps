from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import requests
from zoneinfo import ZoneInfo

BERLIN_TZ = ZoneInfo("Europe/Berlin")
LIVEBOX_BASE = "https://www.kicktipp.de/info/service/livebox"
DETAIL_CACHE_VERSION = 2
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Kicktipp-TipBot/0.1.22"
_CSS_RED_SELECTOR_CACHE: dict[str, tuple[float, list[frozenset[str]]]] = {}
_DETAIL_URL_CACHE: dict[str, tuple[float, str]] = {}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _attr_tokens(attrs: dict[str, str]) -> set[str]:
    tokens: set[str] = set()
    for key in ("class", "id", "data-status", "data-state", "data-live", "aria-label"):
        value = str(attrs.get(key) or "")
        tokens.update(x.casefold() for x in re.findall(r"[A-Za-z0-9_-]+", value))
    return tokens


def _looks_live_attr(attrs: dict[str, str]) -> bool:
    # Do not use a substring test for "live" here. The page itself contains
    # classes/ids such as "livebox" which must never mark every score as live.
    tokens = _attr_tokens(attrs)
    exact_markers = {
        "live", "running", "laufend", "liveticker", "inplay", "in-play",
        "live-result", "result-live", "live-score", "score-live", "text-danger",
    }
    if tokens & exact_markers:
        return True
    for key in ("data-status", "data-state", "data-live"):
        value = str(attrs.get(key) or "").strip().casefold()
        if value in {"live", "running", "laufend", "inplay", "in-play", "true", "1"}:
            return True
    style = re.sub(r"\s+", "", str(attrs.get("style") or "").casefold())
    return bool(
        "color:red" in style
        or re.search(r"color:#(?:f00|ff0000|d00|dd0000|e00|ee0000)\b", style)
        or re.search(r"color:rgb\((?:1[8-9]\d|2[0-5]\d),(?:0|[1-6]?\d),(?:0|[1-6]?\d)\)", style)
    )


def _extract_link_values(attrs: dict[str, str]) -> list[str]:
    out: list[str] = []
    for key, raw in attrs.items():
        value = str(raw or "").strip()
        if not value:
            continue
        if key.casefold() in {"href", "data-href", "data-url", "data-link"}:
            out.append(value)
        # Clickable Kicktipp rows often carry the target in onclick/data attrs.
        for match in re.findall(r"(?:https?://[^\s'\"]+|/[^\s'\"]*(?:/spiel(?:\?|/)|tippuebersicht/spiel)[^\s'\"]*)", value, flags=re.I):
            out.append(match)
    # preserve order, discard javascript pseudo links
    seen: set[str] = set()
    clean: list[str] = []
    for item in out:
        item = item.strip().strip("'\"")
        if not item or item.casefold().startswith("javascript:") or item in seen:
            continue
        seen.add(item)
        clean.append(item)
    return clean


def _extract_game_ids(attrs: dict[str, str]) -> list[str]:
    ids: list[str] = []
    for key, raw in attrs.items():
        k = key.casefold().replace("_", "-")
        if any(marker in k for marker in ("spiel-id", "spielid", "match-id", "matchid", "game-id", "gameid")):
            m = re.search(r"\d{4,}", str(raw or ""))
            if m:
                ids.append(m.group(0))
    return ids


def _competition_slug(label: str) -> str:
    value = _clean(label).casefold()
    aliases = {
        "dfb supercup": "dfb-supercup",
        "dfb-supercup": "dfb-supercup",
        "champions league": "champions league",
        "europa league": "europa league",
        "conference league": "conference league",
    }
    value = aliases.get(value, value)
    return quote(value, safe=".-_")


class _LiveboxParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self.current_heading = ""
        self._heading_tag: str | None = None
        self._heading_text: list[str] = []
        self._row: dict[str, Any] | None = None
        self._cell: dict[str, Any] | None = None
        self._depth_live_flags: list[bool] = []
        self.stylesheets: list[str] = []
        self.inline_styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {str(k): str(v or "") for k, v in attrs_list}
        tag = tag.lower()
        inherited_live = self._depth_live_flags[-1] if self._depth_live_flags else False
        node_live = inherited_live or _looks_live_attr(attrs)
        self._depth_live_flags.append(node_live)

        if tag == "link" and "stylesheet" in attrs.get("rel", "").casefold() and attrs.get("href"):
            self.stylesheets.append(attrs["href"])
        if tag == "style":
            self._in_style = True
        if tag in ("h1", "h2", "h3", "h4"):
            self._heading_tag = tag
            self._heading_text = []
        if tag == "tr":
            self._row = {"cells": [], "heading": self.current_heading, "attrs": attrs, "live_hint": node_live, "links": [], "game_ids": [], "tokens": set()}
            self._row["tokens"].update(re.findall(r"[A-Za-z0-9_-]+", " ".join(attrs.values())))
        if tag in ("td", "th") and self._row is not None:
            self._cell = {"text": [], "attrs": attrs, "live_hint": node_live, "links": [], "game_ids": [], "tokens": set(re.findall(r"[A-Za-z0-9_-]+", " ".join(attrs.values())))}
        if self._row is not None:
            toks = set(re.findall(r"[A-Za-z0-9_-]+", " ".join(attrs.values())))
            self._row["tokens"].update(toks)
            if self._cell is not None:
                self._cell["tokens"].update(toks)
        if self._row is not None:
            for link in _extract_link_values(attrs):
                self._row["links"].append(link)
                if self._cell is not None:
                    self._cell["links"].append(link)
            for game_id in _extract_game_ids(attrs):
                self._row["game_ids"].append(game_id)
                if self._cell is not None:
                    self._cell["game_ids"].append(game_id)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "style":
            self._in_style = False
        if tag in ("h1", "h2", "h3", "h4") and self._heading_tag == tag:
            text = _clean("".join(self._heading_text))
            if text and text.casefold() not in ("livebox",):
                self.current_heading = text
            self._heading_tag = None
            self._heading_text = []
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._cell["text"] = _clean("".join(self._cell["text"]))
            self._row["cells"].append(self._cell)
            self._cell = None
        if tag == "tr" and self._row is not None:
            cells = self._row.get("cells") or []
            # Some Kicktipp layouts put competition labels into a one-cell table row.
            if len(cells) == 1:
                text = _clean(cells[0].get("text") or "")
                if text and not re.match(r"^\d{1,2}:\d{2}\b", text):
                    self.current_heading = text
                    self._row["heading"] = text
            self.rows.append(self._row)
            self._row = None
            self._cell = None
        if self._depth_live_flags:
            self._depth_live_flags.pop()

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.inline_styles.append(data)
        if self._heading_tag:
            self._heading_text.append(data)
        if self._cell is not None:
            self._cell["text"].append(data)
            if self._depth_live_flags and self._depth_live_flags[-1]:
                self._cell["live_hint"] = True
        if self._row is not None and self._depth_live_flags and self._depth_live_flags[-1]:
            self._row["live_hint"] = True


def _red_selector_tokens_from_css(css: str) -> list[frozenset[str]]:
    selectors: list[frozenset[str]] = []
    # Important: keep compound selectors intact. For `.result.live {color:red}`
    # both classes are required. Treating them independently would make every
    # `.result` cell look live and was the cause of stale LIVE labels in 0.1.21.
    for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css, flags=re.S):
        low = body.casefold().replace(" ", "")
        red = (
            "color:red" in low
            or bool(re.search(r"color:#(?:f00|ff0000|d00|dd0000|e00|ee0000|[bcdef][0-9a-f]{4,5})\b", low))
            or bool(re.search(r"color:rgb\((?:1[8-9]\d|2[0-5]\d),(?:0|[1-6]?\d),(?:0|[1-6]?\d)\)", low))
        )
        if not red:
            continue
        for selector in selector_group.split(","):
            # Keep classes on the painted element plus explicit live-state classes
            # on ancestors. Example: `.livebox tr.live td.result {color:red}` must
            # require BOTH `live` and `result`; requiring only `result` marks every
            # finished score red, while requiring `livebox` can never match a row.
            selector = selector.strip()
            final = re.split(r"\s+|>|\+|~", selector)[-1]
            final_classes = {x.casefold() for x in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", final)}
            all_classes = {x.casefold() for x in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector)}
            live_classes = {x for x in all_classes if x in {"live","running","laufend","inplay","in-play","live-result","result-live","live-score","score-live"}}
            classes = frozenset(final_classes | live_classes)
            if classes and classes not in selectors:
                selectors.append(classes)
    return selectors


def _load_red_selectors(base_url: str, parser: _LiveboxParser, timeout: int) -> list[frozenset[str]]:
    red: list[frozenset[str]] = []
    if parser.inline_styles:
        red.extend(_red_selector_tokens_from_css("\n".join(parser.inline_styles)))
    now = time.time()
    for href in parser.stylesheets[:12]:
        css_url = urljoin(base_url, href)
        cached = _CSS_RED_SELECTOR_CACHE.get(css_url)
        if cached and now - cached[0] < 86400:
            red.extend(x for x in cached[1] if x not in red)
            continue
        try:
            response = requests.get(css_url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            selectors = _red_selector_tokens_from_css(response.text)
            _CSS_RED_SELECTOR_CACHE[css_url] = (now, selectors)
            red.extend(x for x in selectors if x not in red)
        except Exception:
            continue
    return red


def _matches_red_selector(tokens: set[str], selectors: list[frozenset[str]]) -> bool:
    lowered = {str(x).casefold() for x in tokens}
    return any(bool(required) and required.issubset(lowered) for required in selectors)


def _score_text(value: str) -> str:
    value = _clean(value)
    if value in ("-:-", "–:–", "—:—"):
        return ""
    match = re.search(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", value)
    if not match:
        return ""
    return f"{int(match.group(1))}:{int(match.group(2))}"


def parse_livebox_html(html: str, local_date: str, *, red_selectors: list[frozenset[str]] | None = None) -> list[dict[str, Any]]:
    parser = _LiveboxParser()
    parser.feed(html)
    parsed: list[dict[str, Any]] = []
    red_selectors = red_selectors or []
    # If the stylesheet could not be interpreted and no row carries an explicit
    # live marker, absence of red is not enough evidence for a final whistle.
    # In that case keep scored rows UNKNOWN instead of risking a false FT push.
    reliable_style_signal = bool(red_selectors) or any(bool(r.get("live_hint")) for r in parser.rows)
    for row in parser.rows:
        cells = row.get("cells") or []
        texts = [_clean(c.get("text") or "") for c in cells]
        if len(texts) < 4 or not re.fullmatch(r"\d{1,2}:\d{2}", texts[0]):
            continue
        time_text, home, away = texts[0], texts[1], texts[2]
        result_text = texts[3]
        if not home or not away:
            continue
        score = _score_text(result_text)
        scheduled = not score and result_text in ("-:-", "–:–", "—:—")
        result_cell = cells[3] if len(cells) > 3 else {}
        result_tokens = set(result_cell.get("tokens") or [])
        row_tokens = set(row.get("tokens") or [])
        live_hint = bool(result_cell.get("live_hint") or row.get("live_hint") or _matches_red_selector(result_tokens | row_tokens, red_selectors))
        # Kicktipp's public Livebox marks running results red. Finished results are
        # black. The parser deliberately uses the style/class signal and never
        # guesses "finished" from elapsed wall-clock time.
        finished = bool(score) and not live_hint and reliable_style_signal
        started = bool(score)
        status = "SCHEDULED" if scheduled else ("LIVE" if live_hint else ("FINISHED" if finished else "UNKNOWN"))
        hrefs = []
        for c in cells[1:4]:
            hrefs.extend(c.get("links") or [])
        hrefs.extend(row.get("links") or [])
        detail_url = ""
        for href in hrefs:
            full = urljoin("https://www.kicktipp.de/", href)
            if "kicktipp" in full and ("/spiel/" in full or "/spiel?" in full):
                detail_url = full
                break
        if not detail_url:
            game_ids: list[str] = []
            for c in cells[1:4]:
                game_ids.extend(c.get("game_ids") or [])
            game_ids.extend(row.get("game_ids") or [])
            if game_ids and row.get("heading"):
                detail_url = f"https://www.kicktipp.de/info/service/wettbewerbe/{_competition_slug(str(row.get('heading') or ''))}/spiel/{game_ids[0]}"
        try:
            kickoff_local = datetime.fromisoformat(f"{local_date}T{time_text}:00").replace(tzinfo=BERLIN_TZ)
            kickoff = kickoff_local.astimezone(timezone.utc).isoformat()
        except Exception:
            kickoff = ""
        parsed.append({
            "competition_label": _clean(row.get("heading") or ""),
            "kickoff": kickoff,
            "home": home,
            "away": away,
            "score": score,
            "started": started,
            "finished": finished,
            "live_hint": live_hint,
            "status": status,
            "detail_url": detail_url,
            "source": "Kicktipp Livebox",
            "result_text": result_text,
            "style_tokens": sorted(result_tokens | row_tokens)[:40],
        })
    return parsed


def fetch_livebox(local_date: str, *, timeout: int = 15) -> tuple[list[dict[str, Any]], str]:
    url = f"{LIVEBOX_BASE}/{local_date}"
    response = requests.get(
        url,
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    probe = _LiveboxParser()
    probe.feed(response.text)
    red_selectors = _load_red_selectors(response.url, probe, timeout)
    return parse_livebox_html(response.text, local_date, red_selectors=red_selectors), url



def _norm_team_name(value: str) -> str:
    text = _clean(value).casefold()
    for old, new in (("ä","a"),("ö","o"),("ü","u"),("ß","ss"),("é","e"),("á","a"),("ó","o")):
        text = text.replace(old, new)
    text = re.sub(r"\b(1\.?|fc|sc|sv|vfl|vfb|tsv|sg|dsc|tsg|rb|bsc|borussia|bor\.?|spvgg)\b", " ", text)
    text = re.sub(r"\b(?:18|19|20)\d{2}\b", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _row_detail_url(row: dict[str, Any], competition_label: str) -> str:
    links = list(row.get("links") or [])
    for cell in row.get("cells") or []:
        links.extend(cell.get("links") or [])
    for href in links:
        full = urljoin("https://www.kicktipp.de/", str(href or ""))
        if "kicktipp" in full and ("/spiel/" in full or "/spiel?" in full):
            return full
    ids = list(row.get("game_ids") or [])
    for cell in row.get("cells") or []:
        ids.extend(cell.get("game_ids") or [])
    if ids and competition_label:
        return f"https://www.kicktipp.de/info/service/wettbewerbe/{_competition_slug(competition_label)}/spiel/{ids[0]}"
    return ""


def resolve_public_detail_url(
    competition_label: str,
    home: str,
    away: str,
    kickoff: str = "",
    *,
    timeout: int = 15,
) -> str:
    """Resolve Kicktipp's public match URL only when a user opens a match.

    Livebox rows can be clickable through data/onclick attributes instead of a
    plain anchor. If the monitor did not capture a URL, inspect the public
    Livebox and competition schedule once and cache the result for five minutes.
    """
    cache_key = "|".join((competition_label, home, away, kickoff))
    now = time.time()
    cached = _DETAIL_URL_CACHE.get(cache_key)
    if cached and now - cached[0] < 300:
        return cached[1]

    local_date = ""
    if kickoff:
        try:
            dt = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BERLIN_TZ)
            local_date = dt.astimezone(BERLIN_TZ).strftime("%Y-%m-%d")
        except Exception:
            pass

    urls: list[str] = []
    if local_date:
        urls.append(f"{LIVEBOX_BASE}/{local_date}")
    if competition_label:
        slug = _competition_slug(competition_label)
        urls.append(f"https://www.kicktipp.de/info/service/wettbewerbe/{slug}/spielplan")

    wanted_home = _norm_team_name(home)
    wanted_away = _norm_team_name(away)
    found = ""
    for url in urls:
        try:
            response = requests.get(url, headers={"Accept":"text/html,application/xhtml+xml","User-Agent":USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            parser = _LiveboxParser()
            parser.feed(response.text)
            for row in parser.rows:
                cells = row.get("cells") or []
                texts = [_clean(c.get("text") or "") for c in cells]
                joined = " | ".join(texts)
                norm_joined = _norm_team_name(joined)
                if wanted_home and wanted_home not in norm_joined:
                    continue
                if wanted_away and wanted_away not in norm_joined:
                    continue
                candidate = _row_detail_url(row, competition_label or str(row.get("heading") or ""))
                if candidate:
                    found = candidate
                    break
            if found:
                break
        except Exception:
            continue
    _DETAIL_URL_CACHE[cache_key] = (now, found)
    return found

def _cache_file(cache_dir: Path, key: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"{digest}.json"


def cached_public_detail(url: str, cache_dir: Path, ttl_seconds: int = 300, home: str = "", away: str = "") -> dict[str, Any]:
    cache = _cache_file(cache_dir, f"v{DETAIL_CACHE_VERSION}|{url}")
    now = time.time()
    if cache.exists():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            saved = float(payload.get("saved_at") or 0)
            if int(payload.get("parser_version") or 0) == DETAIL_CACHE_VERSION and now - saved < ttl_seconds and isinstance(payload.get("data"), dict):
                data = dict(payload["data"])
                data["cached"] = True
                return data
        except Exception:
            pass
    data = fetch_public_detail(url, home=home, away=away)
    cache.write_text(json.dumps({"saved_at": now, "parser_version": DETAIL_CACHE_VERSION, "data": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    data["cached"] = False
    return data


class _DetailParser(HTMLParser):
    BLOCK_TAGS = {"div", "p", "li", "tr", "td", "th", "section", "article", "h1", "h2", "h3", "h4", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag.lower() == "a":
            attrs = {str(k): str(v or "") for k, v in attrs_list}
            if attrs.get("href"):
                self.links.append(attrs["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _section_lines(lines: list[str], heading_re: str, stop_re: str) -> list[str]:
    out: list[str] = []
    active = False
    for line in lines:
        if re.search(heading_re, line, re.I):
            active = True
            continue
        if active and re.search(stop_re, line, re.I):
            break
        if active:
            out.append(line)
    return out


def _minute(line: str) -> str:
    m = re.search(r"\b(\d{1,3}(?:\+\d{1,2})?)\s*[.'′’]", line)
    return (m.group(1) + "′") if m else ""


def _player_entry(number: str, name: str, pos: str = "") -> dict[str, Any]:
    return {"number": str(number or "").strip(), "name": _clean(name), "pos": str(pos or "").strip()}


def _is_shirt_number(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}", _clean(value)))


def _is_nameish(value: str) -> bool:
    cleaned = _clean(value)
    if not cleaned or _is_shirt_number(cleaned):
        return False
    if re.fullmatch(r"\d(?:-\d){1,4}", cleaned):
        return False
    if cleaned.casefold() in {"aufstellung", "aufstellungen", "startelf", "ersatzbank"}:
        return False
    return True


def _extract_formation(lines: list[str]) -> str:
    for line in lines:
        m = re.search(r"\b(\d(?:-\d){1,4})\b", _clean(line))
        if m:
            return m.group(1)
    return ""


def _parse_lineup_pairs(lines: list[str], home: str, away: str, title: str) -> list[dict[str, Any]]:
    cleaned = [_clean(x) for x in lines if _clean(x)]
    while cleaned and cleaned[0].casefold() in {"aufstellung", "aufstellungen", "startelf", "ersatzbank"}:
        cleaned.pop(0)
    formation = _extract_formation(cleaned)
    home_players: list[dict[str, Any]] = []
    away_players: list[dict[str, Any]] = []
    i = 0
    parsed_rows = 0
    while i + 3 < len(cleaned):
        a, b, c, d = cleaned[i:i+4]
        # Kicktipp currently serializes the lineup table as
        # Heimspieler | Heim-Nr. | Gast-Nr. | Gastspieler.
        if _is_nameish(a) and _is_shirt_number(b) and _is_shirt_number(c) and _is_nameish(d):
            home_players.append(_player_entry(b, a))
            away_players.append(_player_entry(c, d))
            parsed_rows += 1
            i += 4
            continue
        # Keep support for the inverse layout should Kicktipp switch columns.
        if _is_shirt_number(a) and _is_nameish(b) and _is_nameish(c) and _is_shirt_number(d):
            home_players.append(_player_entry(a, b))
            away_players.append(_player_entry(d, c))
            parsed_rows += 1
            i += 4
            continue
        i += 1
    if parsed_rows >= 4:
        is_bench = title == "ersatzbank"
        return [
            {
                "team": home or "Heim",
                "formation": formation if not is_bench else "",
                "coach": "",
                "start_xi": [] if is_bench else home_players[:11],
                "substitutes": home_players if is_bench else home_players[11:],
            },
            {
                "team": away or "Gast",
                "formation": formation if not is_bench else "",
                "coach": "",
                "start_xi": [] if is_bench else away_players[:11],
                "substitutes": away_players if is_bench else away_players[11:],
            },
        ]
    # Never turn an unstructured mixture of names/numbers into a fake formation.
    # Keep it as a neutral fallback list instead of assigning players to the wrong team.
    players = []
    idx = 0
    while idx < len(cleaned):
        if _is_nameish(cleaned[idx]):
            number = cleaned[idx + 1] if idx + 1 < len(cleaned) and _is_shirt_number(cleaned[idx + 1]) else ""
            players.append(_player_entry(number, cleaned[idx]))
            idx += 2 if number else 1
        else:
            idx += 1
    if players:
        return [{"team": "Kicktipp-Aufstellung", "formation": formation, "coach": "", "start_xi": players[:11], "substitutes": players[11:], "schematic": True}]
    return []


def _merge_lineups(sections: list[dict[str, Any]], home: str, away: str) -> list[dict[str, Any]]:
    by_team: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for section in sections:
        title = str(section.get("title") or "").casefold()
        parsed_sets = _parse_lineup_pairs(section.get("lines") or [], home, away, title)
        for entry in parsed_sets:
            team = str(entry.get("team") or f"Team {len(order) + 1}")
            if team not in by_team:
                by_team[team] = {"team": team, "formation": str(entry.get("formation") or ""), "coach": str(entry.get("coach") or ""), "start_xi": [], "substitutes": []}
                order.append(team)
            dest = by_team[team]
            if entry.get("formation") and not dest["formation"]:
                dest["formation"] = str(entry.get("formation") or "")
            if entry.get("coach") and not dest["coach"]:
                dest["coach"] = str(entry.get("coach") or "")
            for field in ("start_xi", "substitutes"):
                if entry.get(field):
                    seen = {(p.get("number"), p.get("name")) for p in dest[field]}
                    for player in entry.get(field) or []:
                        key = (player.get("number"), player.get("name"))
                        if key not in seen:
                            dest[field].append(player)
                            seen.add(key)
    return [by_team[name] for name in order if by_team.get(name)]


def _event_groups(lines: list[str]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    minute = ""
    bucket: list[str] = []
    for raw in lines:
        line = _clean(raw)
        found = _minute(line)
        if found:
            if minute:
                groups.append((minute, bucket))
            minute = found
            remainder = re.sub(r"\b\d{1,3}(?:\+\d{1,2})?\s*[.'′’]\s*", "", line).strip(" -·")
            bucket = [remainder] if remainder else []
        elif minute:
            bucket.append(line)
    if minute:
        groups.append((minute, bucket))
    return groups


def _event_text_candidates(parts: list[str]) -> list[str]:
    out: list[str] = []
    for raw in parts:
        value = _clean(raw).strip(" -·")
        if not value:
            continue
        stripped = re.sub(r"[⚽🟨🟥⬆⬇↔🔄]+", "", value).strip()
        stripped = re.sub(r"(?<!\d)\d{1,2}\s*:\s*\d{1,2}(?!\d)", "", stripped).strip(" -·")
        if not stripped or re.fullmatch(r"\+?\d{1,2}", stripped) or re.fullmatch(r"\d{1,2}:\d{1,2}", stripped):
            continue
        if stripped.casefold() in {"gelb", "gelbe karte", "rot", "rote karte", "tor", "wechsel"}:
            continue
        if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", stripped):
            out.append(stripped)
    return out


def _parse_event_sections(sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    substitutions: list[dict[str, Any]] = []
    for section in sections:
        title = str(section.get("title") or "").casefold()
        if title not in {"tore", "karten", "auswechslungen"}:
            continue
        for minute, parts in _event_groups(section.get("lines") or []):
            candidates = _event_text_candidates(parts)
            joined = " · ".join(candidates)
            if title == "tore":
                player = candidates[0] if candidates else "Torschütze nicht erkannt"
                detail = " · ".join(candidates[1:]) if len(candidates) > 1 else ""
                raw_text = " ".join(parts)
                score_match = re.search(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", raw_text)
                score_after = f"{score_match.group(1)}:{score_match.group(2)}" if score_match else ""
                goals.append({"time": minute, "player": player, "team": "", "assist": "", "detail": detail, "score_after": score_after})
            elif title == "karten":
                raw_text = " ".join(parts)
                card = "red" if re.search(r"rot|rote|red|🟥", raw_text, re.I) else "yellow"
                player = candidates[0] if candidates else "Spieler nicht erkannt"
                detail = " · ".join(candidates[1:]) if len(candidates) > 1 else ""
                cards.append({"time": minute, "player": player, "team": "", "card": card, "detail": detail})
            else:
                player_out = candidates[0] if candidates else ""
                player_in = candidates[1] if len(candidates) > 1 else ""
                substitutions.append({"time": minute, "player_out": player_out, "player_in": player_in, "team": "", "detail": joined})
    return goals, cards, substitutions


def fetch_public_detail(url: str, *, timeout: int = 15, home: str = "", away: str = "") -> dict[str, Any]:
    if not url:
        return {"ok": False, "configured": True, "message": "Kicktipp hat für dieses Spiel keinen Detail-Link geliefert.", "source": "Kicktipp"}
    response = requests.get(url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    parser = _DetailParser()
    parser.feed(response.text)
    lines = [_clean(x) for x in "".join(parser.parts).splitlines()]
    lines = [x for x in lines if x]

    section_names = ["Tore", "Karten", "Auswechslungen", "Aufstellung", "Aufstellungen", "Startelf", "Ersatzbank"]
    sections: list[dict[str, Any]] = []
    for name in section_names:
        pattern = rf"^{re.escape(name)}\b"
        content = _section_lines(lines, pattern, r"^(Tore|Karten|Auswechslungen|Aufstellung(?:en)?|Startelf|Ersatzbank|Statistik|Tipps|Spielverlauf)\b")
        if content:
            sections.append({"title": name, "lines": content[:80]})

    goals, cards, substitutions = _parse_event_sections(sections)

    lineup_sections = [s for s in sections if str(s.get("title") or "").casefold() in ("aufstellung", "aufstellungen", "startelf", "ersatzbank")]
    lineups = _merge_lineups(lineup_sections, home, away)

    return {
        "ok": True,
        "configured": True,
        "source": "Kicktipp",
        "url": response.url,
        "message": "",
        "events": {"goals": goals, "cards": cards, "substitutions": substitutions},
        "lineups": lineups,
        "sections": sections,
    }
