from __future__ import annotations

import difflib
import gzip
import html
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

APP_VERSION = "0.1.53"
PORT = 8100
DATA_DIR = Path(os.environ.get("AMAZON_PREISWAECHTER_DATA_DIR") or ("/data" if Path("/data").exists() else Path(__file__).resolve().parent / ".data"))
DB_PATH = DATA_DIR / "amazon_preiswaechter.db"
CACHE_DIR = DATA_DIR / "cache"
KEEPa_CACHE_DIR = CACHE_DIR / "keepa"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
LOG_PATH = DATA_DIR / "amazon_preiswaechter.log"
CHECK_INTERVAL_SECONDS = 3600
SCHEDULER_WAKE_SECONDS = 30
KEEPa_CACHE_SECONDS = 4 * 3600
PRODUCT_TIMEOUT_SECONDS = 20
KEEPa_TIMEOUT_SECONDS = 20
IDEALO_STALE_AFTER_SECONDS = 30 * 3600
IDEALO_SCHEDULE_TIMEZONE = ZoneInfo("Europe/Berlin")
IDEALO_STANDARD_HOURS = (12,)
IDEALO_EXTENDED_HOURS = (8, 12, 16, 20)
IDEALO_MATCH_THRESHOLD = 0.55
IDEALO_UNCERTAIN_THRESHOLD = 0.42
IDEALO_SEARCH_URL = "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q="
IDEALO_DDG_SEARCH_URL = "https://html.duckduckgo.com/html/?q="
JINA_READER_PREFIX = "https://r.jina.ai/"
MYDEALZ_CHECK_INTERVAL_SECONDS = 30 * 60
MYDEALZ_SEARCH_INTERVAL_SECONDS = 3600
MYDEALZ_TIMEOUT_SECONDS = 20
MYDEALZ_MATCH_THRESHOLD = 0.43
MYDEALZ_DISCOVERY_FALLBACK_THRESHOLD = 0.58
MYDEALZ_SAFETY_QUERY_BUDGET = 2
MYDEALZ_WATCH_CHECK_INTERVAL_SECONDS = 30 * 60
MYDEALZ_WATCH_SEARCH_INTERVAL_SECONDS = 3600
MYDEALZ_FEED_URLS = ("https://www.mydealz.de/rss", "https://www.mydealz.de/rss/hot")
MYDEALZ_SEARCH_URL = "https://www.mydealz.de/search?q="
OPTIONS_PATH = DATA_DIR / "options.json"
DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"
LEGACY_DEFAULT_GEMINI_MODELS = {"gemini-3.5-flash-lite"}
GOOGLE_SEARCH_FREE_MONTHLY_SHARED = 5000
IDEALO_DISCOVERY_QUERY_BUDGET = 3
AUGUST_2026_GOOGLE_SEARCH_SEED = 489
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
NOTIFY_primary = "mobile_app_iphone_primary"
NOTIFY_secondary = "mobile_app_secondary_iphone"
AMAZON_HOSTS = {"amazon.de", "www.amazon.de", "smile.amazon.de", "m.amazon.de"}
ASIN_RE = re.compile(r"(?i)(?:/dp/|/gp/product/|/gp/aw/d/|/product/)([A-Z0-9]{10})(?:[/?]|$)")
ASIN_QUERY_RE = re.compile(r"(?i)(?:^|[?&])(?:asin|ASIN)=([A-Z0-9]{10})(?:&|$)")
PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:\.\d{3})*,\d{2})\s*€")
DEAL_PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}(?:[.,]\d{1,2})?)\s*€")

DATA_DIR.mkdir(parents=True, exist_ok=True)
KEEPa_CACHE_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("amazon_preiswaechter")

REFRESH_ALL_LOCK = threading.Lock()
PRODUCT_CHECK_LOCK = threading.Lock()
GEMINI_API_LOCK = threading.Lock()
MYDEALZ_THREAD_CACHE_LOCK = threading.Lock()
MYDEALZ_THREAD_CACHE_SECONDS = 5 * 60
MYDEALZ_THREAD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
AMAZON_VARIANT_CACHE_LOCK = threading.Lock()
AMAZON_VARIANT_CACHE_SECONDS = 6 * 3600
AMAZON_VARIANT_CACHE: dict[str, tuple[float, dict[str, set[str]]]] = {}
GEMINI_LAST_CALL_AT = 0.0
GEMINI_MIN_GAP_SECONDS = 2.0
GEMINI_URL_CONTEXT_TIMEOUT_SECONDS = 120
GEMINI_URL_CONTEXT_MAX_ATTEMPTS = 2
REFRESH_ALL_STATE: dict[str, Any] = {
    "running": False,
    "total": 0,
    "done": 0,
    "success": 0,
    "failed": 0,
    "current_id": None,
    "current_title": "",
    "last_error": "",
    "started_at": None,
    "finished_at": None,
}
PRODUCT_CHECK_STATES: dict[int, dict[str, Any]] = {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def seconds_since(value: str | None, now: datetime | None = None) -> float | None:
    parsed = parse_iso(value)
    if parsed is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - parsed).total_seconds())


def timestamp_due(value: str | None, interval_seconds: int, now: datetime | None = None) -> bool:
    age_seconds = seconds_since(value, now=now)
    return age_seconds is None or age_seconds >= interval_seconds


def idealo_price_is_fresh(row_or_dict: sqlite3.Row | dict[str, Any], now: datetime | None = None) -> bool:
    try:
        success = row_or_dict["idealo_last_success"]
    except Exception:
        success = None
    age_seconds = seconds_since(success, now=now)
    return age_seconds is not None and age_seconds <= IDEALO_STALE_AFTER_SECONDS


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL UNIQUE,
                amazon_url TEXT NOT NULL,
                source_url TEXT NOT NULL,
                title TEXT,
                custom_name TEXT,
                image_url TEXT,
                current_price_cents INTEGER,
                current_price_source TEXT,
                current_seller TEXT,
                current_availability TEXT,
                current_condition TEXT,
                wish_price_cents INTEGER,
                notify_wish INTEGER NOT NULL DEFAULT 0,
                notify_drop INTEGER NOT NULL DEFAULT 0,
                notify_low INTEGER NOT NULL DEFAULT 1,
                notify_price_change INTEGER NOT NULL DEFAULT 0,
                price_change_threshold_cents INTEGER NOT NULL DEFAULT 200,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked TEXT,
                last_success TEXT,
                last_error TEXT,
                low_price_cents INTEGER,
                start_price_cents INTEGER,
                notify_primary INTEGER NOT NULL DEFAULT 1,
                notify_secondary INTEGER NOT NULL DEFAULT 0,
                wish_triggered INTEGER NOT NULL DEFAULT 0,
                idealo_enabled INTEGER NOT NULL DEFAULT 1,
                idealo_url TEXT,
                idealo_candidate_url TEXT,
                idealo_candidate_title TEXT,
                idealo_match_title TEXT,
                idealo_match_score REAL,
                idealo_status TEXT NOT NULL DEFAULT 'pending',
                idealo_manual INTEGER NOT NULL DEFAULT 0,
                idealo_current_price_cents INTEGER,
                idealo_current_shop TEXT,
                idealo_current_offer_url TEXT,
                idealo_price_kind TEXT,
                idealo_last_checked TEXT,
                idealo_last_success TEXT,
                idealo_last_error TEXT,
                idealo_low_price_cents INTEGER,
                idealo_start_price_cents INTEGER,
                notify_idealo_cheaper INTEGER NOT NULL DEFAULT 0,
                idealo_cheaper_threshold_cents INTEGER NOT NULL DEFAULT 500,
                idealo_cheaper_triggered INTEGER NOT NULL DEFAULT 0,
                used_current_price_cents INTEGER,
                used_offer_url TEXT,
                used_condition TEXT,
                used_available INTEGER NOT NULL DEFAULT 0,
                used_initialized INTEGER NOT NULL DEFAULT 0,
                used_last_checked TEXT,
                used_last_success TEXT,
                used_last_error TEXT,
                used_low_price_cents INTEGER,
                used_start_price_cents INTEGER,
                notify_used_available INTEGER NOT NULL DEFAULT 1,
                mydealz_enabled INTEGER NOT NULL DEFAULT 1,
                notify_mydealz INTEGER NOT NULL DEFAULT 1,
                mydealz_query TEXT,
                mydealz_last_checked TEXT,
                mydealz_last_success TEXT,
                mydealz_last_error TEXT,
                mydealz_initialized INTEGER NOT NULL DEFAULT 0,
                mydealz_best_price_cents INTEGER,
                mydealz_best_title TEXT,
                mydealz_best_url TEXT,
                mydealz_best_temperature INTEGER,
                mydealz_best_merchant TEXT,
                mydealz_best_published TEXT,
                mydealz_search_last_checked TEXT,
                mydealz_gemini_last_checked TEXT,
                idealo_gemini_last_checked TEXT,
                idealo_reader_failures INTEGER NOT NULL DEFAULT 0,
                idealo_last_verified TEXT,
                idealo_error_notified TEXT
            );

            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                price_source TEXT,
                seller TEXT,
                availability TEXT,
                condition TEXT,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS idealo_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                shop TEXT,
                idealo_url TEXT,
                offer_url TEXT,
                price_kind TEXT,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS used_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                condition TEXT,
                offer_url TEXT,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mydealz_deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                deal_key TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                price_cents INTEGER,
                temperature INTEGER,
                merchant TEXT,
                published_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                match_score REAL,
                active INTEGER NOT NULL DEFAULT 1,
                notified INTEGER NOT NULL DEFAULT 0,
                UNIQUE(product_id, deal_key),
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mydealz_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                query TEXT NOT NULL,
                exclude_terms TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                notify_primary INTEGER NOT NULL DEFAULT 1,
                notify_secondary INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked TEXT,
                last_search_checked TEXT,
                last_success TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS mydealz_watch_deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_id INTEGER NOT NULL,
                deal_key TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                price_cents INTEGER,
                temperature INTEGER,
                merchant TEXT,
                published_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                notified INTEGER NOT NULL DEFAULT 0,
                UNIQUE(watch_id, deal_key),
                FOREIGN KEY(watch_id) REFERENCES mydealz_watches(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_mydealz_watch_seen
            ON mydealz_watch_deals(watch_id, first_seen_at);

            CREATE INDEX IF NOT EXISTS idx_prices_product_time
            ON prices(product_id, checked_at);

            CREATE INDEX IF NOT EXISTS idx_idealo_prices_product_time
            ON idealo_prices(product_id, checked_at);

            CREATE INDEX IF NOT EXISTS idx_used_prices_product_time
            ON used_prices(product_id, checked_at);

            CREATE INDEX IF NOT EXISTS idx_mydealz_product_seen
            ON mydealz_deals(product_id, first_seen_at);
            """
        )

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        migrations = {
            "start_price_cents": "INTEGER",
            "notify_primary": "INTEGER NOT NULL DEFAULT 1",
            "notify_secondary": "INTEGER NOT NULL DEFAULT 0",
            "idealo_enabled": "INTEGER NOT NULL DEFAULT 1",
            "idealo_url": "TEXT",
            "idealo_candidate_url": "TEXT",
            "idealo_candidate_title": "TEXT",
            "idealo_match_title": "TEXT",
            "idealo_match_score": "REAL",
            "idealo_status": "TEXT NOT NULL DEFAULT 'pending'",
            "idealo_manual": "INTEGER NOT NULL DEFAULT 0",
            "idealo_current_price_cents": "INTEGER",
            "idealo_current_shop": "TEXT",
            "idealo_current_offer_url": "TEXT",
            "idealo_price_kind": "TEXT",
            "idealo_last_checked": "TEXT",
            "idealo_last_success": "TEXT",
            "idealo_last_error": "TEXT",
            "idealo_low_price_cents": "INTEGER",
            "idealo_start_price_cents": "INTEGER",
            "notify_idealo_cheaper": "INTEGER NOT NULL DEFAULT 0",
            "idealo_cheaper_threshold_cents": "INTEGER NOT NULL DEFAULT 500",
            "idealo_cheaper_triggered": "INTEGER NOT NULL DEFAULT 0",
            "used_current_price_cents": "INTEGER",
            "used_offer_url": "TEXT",
            "used_condition": "TEXT",
            "used_available": "INTEGER NOT NULL DEFAULT 0",
            "used_initialized": "INTEGER NOT NULL DEFAULT 0",
            "used_last_checked": "TEXT",
            "used_last_success": "TEXT",
            "used_last_error": "TEXT",
            "used_low_price_cents": "INTEGER",
            "used_start_price_cents": "INTEGER",
            "notify_used_available": "INTEGER NOT NULL DEFAULT 1",
            "mydealz_enabled": "INTEGER NOT NULL DEFAULT 1",
            "notify_mydealz": "INTEGER NOT NULL DEFAULT 1",
            "mydealz_query": "TEXT",
            "mydealz_last_checked": "TEXT",
            "mydealz_last_success": "TEXT",
            "mydealz_last_error": "TEXT",
            "mydealz_initialized": "INTEGER NOT NULL DEFAULT 0",
            "mydealz_best_price_cents": "INTEGER",
            "mydealz_best_title": "TEXT",
            "mydealz_best_url": "TEXT",
            "mydealz_best_temperature": "INTEGER",
            "mydealz_best_merchant": "TEXT",
            "mydealz_best_published": "TEXT",
            "mydealz_search_last_checked": "TEXT",
            "mydealz_gemini_last_checked": "TEXT",
            "idealo_gemini_last_checked": "TEXT",
            "idealo_reader_failures": "INTEGER NOT NULL DEFAULT 0",
            "idealo_last_verified": "TEXT",
            "idealo_error_notified": "TEXT",
            "notify_price_change": "INTEGER NOT NULL DEFAULT 0",
            "price_change_threshold_cents": "INTEGER NOT NULL DEFAULT 200",
        }
        migrations.setdefault("custom_name", "TEXT")
        for name, definition in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE products ADD COLUMN {name} {definition}")

        deal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(mydealz_deals)").fetchall()}
        if "merchant" not in deal_columns:
            conn.execute("ALTER TABLE mydealz_deals ADD COLUMN merchant TEXT")
        if "active" not in deal_columns:
            conn.execute("ALTER TABLE mydealz_deals ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "notified" not in deal_columns:
            conn.execute("ALTER TABLE mydealz_deals ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            """
            UPDATE products
            SET start_price_cents = (
                SELECT price_cents FROM prices
                WHERE prices.product_id = products.id
                ORDER BY prices.id ASC LIMIT 1
            )
            WHERE start_price_cents IS NULL
            """
        )
        conn.execute(
            """
            UPDATE products
            SET idealo_start_price_cents = (
                SELECT price_cents FROM idealo_prices
                WHERE idealo_prices.product_id = products.id
                ORDER BY idealo_prices.id ASC LIMIT 1
            )
            WHERE idealo_start_price_cents IS NULL
            """
        )
        conn.execute(
            """
            UPDATE products
            SET used_start_price_cents = (
                SELECT price_cents FROM used_prices
                WHERE used_prices.product_id = products.id
                ORDER BY used_prices.id ASC LIMIT 1
            )
            WHERE used_start_price_cents IS NULL
            """
        )

        conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
        gemini_only_repair = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_48_gemini_only' ").fetchone()
        if gemini_only_repair is None:
            # The former drop-only alarm had no minimum amount and could send
            # small, noisy alerts. It is superseded by the explicit any-change
            # alarm with a per-product threshold below.
            conn.execute("UPDATE products SET notify_drop=0, idealo_reader_failures=0")
            conn.execute(
                "UPDATE products SET idealo_last_error=NULL "
                "WHERE idealo_last_error LIKE '%Reader:%' OR idealo_last_error LIKE '%Browser:%'"
            )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_48_gemini_only', ?)",
                (utc_now_iso(),),
            )
        # 0.1.21 continues persistent accounting of exact Google Search queries
        # reported by Gemini usage metadata. Earlier monthly usage cannot be
        # reconstructed from the local database, so keep the start timestamp.
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES('gemini_usage_tracking_started_at', ?)",
            (utc_now_iso(),),
        )
        repaired = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_8'").fetchone()
        if repaired is None:
            # 0.1.7 could leave valid Gemini Idealo matches in an unresolved state
            # because the old Reader returned only a stub. Allow exactly one fresh
            # automatic discovery after upgrading to 0.1.8.
            conn.execute(
                """
                UPDATE products
                SET idealo_gemini_last_checked=NULL, idealo_last_error=NULL, idealo_status='pending',
                    idealo_reader_failures=0
                WHERE idealo_enabled=1 AND idealo_url IS NULL
                """
            )
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_8', ?)", (utc_now_iso(),))

        repaired_mydealz = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_10_mydealz'").fetchone()
        if repaired_mydealz is None:
            # Remove stale errors from the retired /rss/alle endpoint so the UI
            # reflects only the currently active /rss and /rss/hot feeds. Force
            # one new Gemini safety check on the next scheduled/manual refresh.
            conn.execute(
                """
                UPDATE products
                SET mydealz_last_error=NULL, mydealz_gemini_last_checked=NULL
                WHERE mydealz_enabled=1 AND (
                    mydealz_last_error LIKE '%404%' OR
                    mydealz_last_error LIKE '%rss/alle%' OR
                    mydealz_last_error LIKE '%RSS konnte nicht abgerufen%'
                )
                """
            )
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_10_mydealz', ?)", (utc_now_iso(),))

        repaired_idealo_daily = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_11_idealo_daily'").fetchone()
        if repaired_idealo_daily is None:
            # Reader/URL-Context errors from 0.1.8-0.1.10 are obsolete. Keep
            # existing prices/URLs, clear only technical errors and allow one
            # immediate daily Gemini refresh after updating to 0.1.12.
            conn.execute(
                """
                UPDATE products
                SET idealo_last_error=NULL, idealo_gemini_last_checked=NULL, idealo_reader_failures=0
                WHERE idealo_enabled=1 AND idealo_url IS NOT NULL
                """
            )
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_11_idealo_daily', ?)", (utc_now_iso(),))


        repaired_source_integrity = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_12_source_integrity'").fetchone()
        if repaired_source_integrity is None:
            # Earlier Gemini structured searches could pair a correct price with
            # a wrong model-generated Idealo URL. Automatic mappings are rebuilt
            # once from authoritative Google Search citations. Historical price
            # rows remain untouched; only the unsafe current mapping is cleared.
            conn.execute(
                """
                UPDATE products
                SET idealo_url=NULL, idealo_candidate_url=NULL, idealo_candidate_title=NULL,
                    idealo_match_title=NULL, idealo_match_score=NULL, idealo_status='pending',
                    idealo_current_price_cents=NULL, idealo_current_shop=NULL, idealo_current_offer_url=NULL,
                    idealo_price_kind=NULL, idealo_last_checked=NULL, idealo_last_success=NULL, idealo_last_error=NULL,
                    idealo_gemini_last_checked=NULL, idealo_reader_failures=0
                WHERE idealo_enabled=1 AND COALESCE(idealo_manual, 0)=0
                """
            )
            conn.execute(
                """
                UPDATE products SET mydealz_last_error=NULL, mydealz_gemini_last_checked=NULL
                WHERE mydealz_enabled=1
                """
            )
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_12_source_integrity', ?)", (utc_now_iso(),))

        repaired_citation_identity = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_13_citation_identity'").fetchone()
        if repaired_citation_identity is None:
            # 0.1.12 still allowed model citation prose to influence product
            # identity. That could attach a valid KESPER price to an unrelated
            # Idealo page. Rebuild all automatic mappings once with URL/title-
            # only identity scoring; historical price rows remain untouched.
            conn.execute(
                """
                UPDATE products
                SET idealo_url=NULL, idealo_candidate_url=NULL, idealo_candidate_title=NULL,
                    idealo_match_title=NULL, idealo_match_score=NULL, idealo_status='pending',
                    idealo_current_price_cents=NULL, idealo_current_shop=NULL, idealo_current_offer_url=NULL,
                    idealo_price_kind=NULL, idealo_last_checked=NULL, idealo_last_success=NULL, idealo_last_error=NULL,
                    idealo_gemini_last_checked=NULL, idealo_reader_failures=0
                WHERE idealo_enabled=1 AND COALESCE(idealo_manual, 0)=0
                """
            )
            conn.execute(
                "UPDATE products SET mydealz_last_error=NULL, mydealz_gemini_last_checked=NULL WHERE mydealz_enabled=1"
            )
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_13_citation_identity', ?)", (utc_now_iso(),))


        repaired_efficiency = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_14_efficiency'").fetchone()
        if repaired_efficiency is None:
            # 0.1.12/0.1.13 intentionally cleared automatic Idealo mappings.
            # Recover the last trustworthy *price* from our own history so the
            # overview does not become empty while a fresh daily mapping is
            # rebuilt. A historical URL is restored only if its own slug strongly
            # matches the Amazon product; otherwise it remains pending.
            rows = conn.execute(
                "SELECT id, title FROM products WHERE idealo_enabled=1 AND idealo_current_price_cents IS NULL"
            ).fetchall()
            for product in rows:
                last = conn.execute(
                    "SELECT checked_at, price_cents, shop, idealo_url, offer_url, price_kind FROM idealo_prices WHERE product_id=? ORDER BY id DESC LIMIT 1",
                    (product["id"],),
                ).fetchone()
                if not last:
                    continue
                hist_url = str(last["idealo_url"] or "")
                restored_url = ""
                restored_score = 0.0
                if hist_url:
                    try:
                        valid = _direct_idealo_url(hist_url)
                    except Exception:
                        valid = ""
                    if valid:
                        src = {"url": valid, "title": _url_slug_text(valid), "cited_text": ""}
                        restored_score = _source_match_score(str(product["title"] or ""), src)
                        if restored_score >= 0.40:
                            restored_url = valid
                conn.execute(
                    """
                    UPDATE products SET idealo_current_price_cents=?, idealo_current_shop=?, idealo_current_offer_url=?,
                        idealo_price_kind=?, idealo_last_success=?, idealo_last_error=NULL,
                        idealo_url=CASE WHEN ?<>'' THEN ? ELSE idealo_url END,
                        idealo_status=CASE WHEN ?<>'' THEN 'matched' ELSE 'pending' END,
                        idealo_match_score=CASE WHEN ?<>'' THEN ? ELSE idealo_match_score END,
                        idealo_gemini_last_checked=NULL
                    WHERE id=?
                    """,
                    (last["price_cents"], last["shop"] or "", last["offer_url"] or "",
                     last["price_kind"] or "Letzter sicherer Idealo-Preis", last["checked_at"],
                     restored_url, restored_url, restored_url, restored_url, restored_score, product["id"]),
                )
            # Let the daily scheduler rebuild missing mappings, but do not force
            # all products at once through the bulk-refresh button.
            conn.execute("UPDATE products SET idealo_last_error=NULL WHERE idealo_enabled=1")
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_14_efficiency', ?)", (utc_now_iso(),))

        repaired_015 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_15_source_cleanup'").fetchone()
        if repaired_015 is None:
            # 0.1.14 could restore a historical automatic Idealo URL together
            # with a trustworthy historical price. Keep the price/history, but
            # never carry an old automatic URL forward. A fresh mapping is
            # rebuilt later in the product's own daily Gemini slot. Manual URLs
            # remain untouched.
            conn.execute(
                """
                UPDATE products
                SET idealo_url=NULL, idealo_candidate_url=NULL, idealo_candidate_title=NULL,
                    idealo_match_title=NULL, idealo_match_score=NULL, idealo_status='pending',
                    idealo_current_offer_url=NULL, idealo_last_error=NULL, idealo_last_checked=NULL,
                    idealo_gemini_last_checked=?, idealo_reader_failures=0
                WHERE idealo_enabled=1 AND COALESCE(idealo_manual, 0)=0
                """,
                (utc_now_iso(),),
            )
            # MyDealz daily safety checks now use the public MyDealz search
            # before Gemini. Keep their existing cadence; only remove stale
            # technical errors so the UI reflects the new path.
            conn.execute(
                "UPDATE products SET mydealz_last_error=NULL WHERE mydealz_enabled=1 AND mydealz_last_error IS NOT NULL"
            )
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_15_source_cleanup', ?)", (utc_now_iso(),))

        repaired_016 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_16_identity_guard'").fetchone()
        if repaired_016 is None:
            # Never expose an old automatic Idealo URL unless its URL/title
            # identity fits the Amazon product. Prices/history are preserved.
            rows = conn.execute("SELECT id, title, idealo_url, idealo_match_title, idealo_manual FROM products WHERE idealo_url IS NOT NULL").fetchall()
            for product in rows:
                url = str(product["idealo_url"] or "")
                if not url:
                    continue
                score = idealo_url_identity_score(str(product["title"] or ""), url, str(product["idealo_match_title"] or ""))
                if score < 0.52:
                    conn.execute(
                        """
                        UPDATE products SET idealo_url=NULL, idealo_candidate_url=NULL, idealo_candidate_title=NULL,
                            idealo_match_title=NULL, idealo_match_score=NULL, idealo_status='pending', idealo_manual=0,
                            idealo_current_offer_url=NULL, idealo_last_error=NULL, idealo_last_checked=NULL,
                            idealo_gemini_last_checked=NULL WHERE id=?
                        """,
                        (product["id"],),
                    )
            conn.execute("UPDATE products SET mydealz_last_error=NULL WHERE mydealz_enabled=1")
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_16_identity_guard', ?)", (utc_now_iso(),))


        repaired_017 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_17_grounding_redirect'").fetchone()
        if repaired_017 is None:
            # Earlier versions could store a model-written Idealo OffersOfProduct
            # id even when the Google grounding citation pointed to a different,
            # correct product page. Preserve prices/history but discard every
            # automatic URL once. New automatic URLs are accepted only after the
            # grounding redirect itself resolves to idealo.de.
            reset_stamp = utc_now_iso()
            conn.execute(
                """
                UPDATE products SET idealo_url=NULL, idealo_candidate_url=NULL, idealo_candidate_title=NULL,
                    idealo_match_title=NULL, idealo_match_score=NULL, idealo_status='pending',
                    idealo_current_offer_url=NULL, idealo_last_error=NULL, idealo_last_checked=NULL,
                    idealo_gemini_last_checked=?, idealo_reader_failures=0
                WHERE idealo_enabled=1 AND COALESCE(idealo_manual, 0)=0
                """,
                (reset_stamp,),
            )
            conn.execute("UPDATE products SET mydealz_last_error=NULL WHERE mydealz_enabled=1")
            conn.execute("INSERT INTO app_meta(key, value) VALUES('repair_0_1_17_grounding_redirect', ?)", (utc_now_iso(),))


        repaired_021 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_21_search_budget_url_context'").fetchone()
        if repaired_021 is None:
            # Cloud Billing showed 437 Gemini-3 Google Search queries for the
            # Preissuche project in August 2026 before the final terminal tests.
            # The verified 3.7 tests then used 49 + 3 further searches. Seed the
            # local August counter to the known project total of 489 without
            # ever decreasing a value already tracked by the app.
            usage_key = "gemini_google_search_queries_2026-08"
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (usage_key,)).fetchone()
            try:
                existing_usage = int(row[0]) if row else 0
            except Exception:
                existing_usage = 0
            seeded_usage = max(existing_usage, AUGUST_2026_GOOGLE_SEARCH_SEED)
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (usage_key, str(seeded_usage)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO app_meta(key, value) VALUES('gemini_idealo_mapping_attempts_2026-08', '0')"
            )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('gemini_usage_tracking_started_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("2026-08-01T00:00:00+00:00",),
            )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_21_search_budget_url_context', ?) ",
                (utc_now_iso(),),
            )

        repaired_022 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_22_mydealz_identity_cleanup'").fetchone()
        if repaired_022 is None:
            # Earlier MyDealz matching could accept a same-category product from
            # another manufacturer (for example EMSA for a SIGG bottle). Re-score
            # the local deal history with the strict brand/model identity guard,
            # delete invalid rows, and rebuild each product's best-deal pointer.
            products_022 = conn.execute("SELECT id, title FROM products").fetchall()
            for product_022 in products_022:
                deals_022 = conn.execute(
                    "SELECT id, title FROM mydealz_deals WHERE product_id=?",
                    (product_022["id"],),
                ).fetchall()
                for deal_022 in deals_022:
                    score_022 = mydealz_identity_score(str(product_022["title"] or ""), str(deal_022["title"] or ""))
                    if score_022 < MYDEALZ_MATCH_THRESHOLD:
                        conn.execute("DELETE FROM mydealz_deals WHERE id=?", (deal_022["id"],))
                    else:
                        conn.execute("UPDATE mydealz_deals SET match_score=? WHERE id=?", (score_022, deal_022["id"]))
                best_022 = conn.execute(
                    "SELECT price_cents, title, url, temperature, merchant, published_at "
                    "FROM mydealz_deals WHERE product_id=? AND price_cents IS NOT NULL "
                    "ORDER BY price_cents ASC, id DESC LIMIT 1",
                    (product_022["id"],),
                ).fetchone()
                if best_022 is None:
                    conn.execute(
                        "UPDATE products SET mydealz_best_price_cents=NULL, mydealz_best_title=NULL, mydealz_best_url=NULL, "
                        "mydealz_best_temperature=NULL, mydealz_best_merchant=NULL, mydealz_best_published=NULL, "
                        "mydealz_last_error=NULL WHERE id=?",
                        (product_022["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE products SET mydealz_best_price_cents=?, mydealz_best_title=?, mydealz_best_url=?, "
                        "mydealz_best_temperature=?, mydealz_best_merchant=?, mydealz_best_published=?, mydealz_last_error=NULL WHERE id=?",
                        (best_022["price_cents"], best_022["title"], best_022["url"], best_022["temperature"],
                         best_022["merchant"], best_022["published_at"], product_022["id"]),
                    )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_22_mydealz_identity_cleanup', ?)",
                (utc_now_iso(),),
            )


        repaired_023 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_23_behavior_defaults'").fetchone()
        if repaired_023 is None:
            # 0.1.23 makes Idealo/MyDealz standard sources for every Amazon product,
            # removes the retired notification toggles from the UI, and forces one
            # zero-Search URL-Context refresh of already mapped Idealo pages so
            # Amazon-Prime shipping handling is recalculated promptly.
            conn.execute(
                "UPDATE products SET idealo_enabled=1, mydealz_enabled=1, notify_mydealz=1, notify_low=0, "
                "notify_idealo_cheaper=0, idealo_cheaper_triggered=0, idealo_last_checked=NULL "
                "WHERE active IN (0,1)"
            )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_23_behavior_defaults', ?)",
                (utc_now_iso(),),
            )

        repaired_023_md = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_23_mydealz_variant_cleanup'").fetchone()
        if repaired_023_md is None:
            # Re-score saved deal history with the short-title-friendly matcher
            # plus the new hard variant anchors. This also prevents an inactive
            # deal from remaining the product's current MyDealz pointer.
            products_023 = conn.execute("SELECT id, title FROM products").fetchall()
            for product_023 in products_023:
                deals_023 = conn.execute(
                    "SELECT id, title FROM mydealz_deals WHERE product_id=?",
                    (product_023["id"],),
                ).fetchall()
                for deal_023 in deals_023:
                    score_023 = mydealz_identity_score(str(product_023["title"] or ""), str(deal_023["title"] or ""))
                    if score_023 < MYDEALZ_MATCH_THRESHOLD:
                        conn.execute("DELETE FROM mydealz_deals WHERE id=?", (deal_023["id"],))
                    else:
                        conn.execute("UPDATE mydealz_deals SET match_score=? WHERE id=?", (score_023, deal_023["id"]))
                best_023 = conn.execute(
                    "SELECT price_cents,title,url,temperature,merchant,published_at FROM mydealz_deals "
                    "WHERE product_id=? AND active=1 AND price_cents IS NOT NULL ORDER BY price_cents ASC,id DESC LIMIT 1",
                    (product_023["id"],),
                ).fetchone()
                if best_023 is None:
                    conn.execute(
                        "UPDATE products SET mydealz_best_price_cents=NULL,mydealz_best_title=NULL,mydealz_best_url=NULL,"
                        "mydealz_best_temperature=NULL,mydealz_best_merchant=NULL,mydealz_best_published=NULL WHERE id=?",
                        (product_023["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE products SET mydealz_best_price_cents=?,mydealz_best_title=?,mydealz_best_url=?,"
                        "mydealz_best_temperature=?,mydealz_best_merchant=?,mydealz_best_published=? WHERE id=?",
                        (best_023["price_cents"],best_023["title"],best_023["url"],best_023["temperature"],
                         best_023["merchant"],best_023["published_at"],product_023["id"]),
                    )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_23_mydealz_variant_cleanup', ?)",
                (utc_now_iso(),),
            )

        repaired_024_md = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_24_mydealz_safety_schedule'").fetchone()
        if repaired_024_md is None:
            # 0.1.23 used mydealz_gemini_last_checked for the hourly public MyDealz
            # search although the column name was originally intended for the
            # grounded Gemini safety check. Preserve that hourly timestamp in a
            # dedicated column and free the Gemini timestamp so every product gets
            # one staggered daily safety check after upgrading. Existing deals and
            # historical data remain untouched.
            conn.execute(
                """
                UPDATE products
                SET mydealz_search_last_checked=COALESCE(mydealz_search_last_checked, mydealz_gemini_last_checked),
                    mydealz_gemini_last_checked=NULL, mydealz_last_error=NULL
                WHERE mydealz_enabled=1
                """
            )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_24_mydealz_safety_schedule', ?)",
                (utc_now_iso(),),
            )

        repaired_026_md = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_26_mydealz_active_status'").fetchone()
        if repaired_026_md is None:
            # 0.1.25 could mark a Google/search fallback active when MyDealz
            # blocked the detail page. Keep historical rows, but force every
            # current pointer to be re-proven by the platform's explicit
            # status/isExpired fields.
            conn.execute("UPDATE mydealz_deals SET active=0 WHERE active=1")
            conn.execute("UPDATE mydealz_watch_deals SET active=0 WHERE active=1")
            conn.execute(
                """
                UPDATE products SET
                    mydealz_best_price_cents=NULL, mydealz_best_title=NULL, mydealz_best_url=NULL,
                    mydealz_best_temperature=NULL, mydealz_best_merchant=NULL, mydealz_best_published=NULL,
                    mydealz_last_error=NULL
                WHERE mydealz_enabled=1
                """
            )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_26_mydealz_active_status', ?)",
                (utc_now_iso(),),
            )

        repaired_027_md = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_27_mydealz_targeted_thread_status'").fetchone()
        if repaired_027_md is None:
            # 0.1.26 treated absence from a bounded newest/hottest GraphQL feed
            # as proof of inactivity. 0.1.27 verifies each exact MyDealz thread
            # instead, then checks the Amazon click-out ASIN / variant family.
            # Keep history but force one fresh free MyDealz search after upgrade.
            conn.execute("UPDATE mydealz_deals SET active=0 WHERE active=1")
            conn.execute("UPDATE mydealz_watch_deals SET active=0 WHERE active=1")
            conn.execute(
                """
                UPDATE products SET
                    mydealz_best_price_cents=NULL, mydealz_best_title=NULL, mydealz_best_url=NULL,
                    mydealz_best_temperature=NULL, mydealz_best_merchant=NULL, mydealz_best_published=NULL,
                    mydealz_last_checked=NULL, mydealz_search_last_checked=NULL, mydealz_last_error=NULL
                WHERE mydealz_enabled=1
                """
            )
            conn.execute("UPDATE mydealz_watches SET last_checked=NULL, last_search_checked=NULL WHERE active=1")
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_27_mydealz_targeted_thread_status', ?)",
                (utc_now_iso(),),
            )

        repaired_028 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_28_idealo_shipping_watch_refresh'").fetchone()
        if repaired_028 is None:
            # 0.1.28 treats every Amazon offer on Idealo as Prime for this private
            # comparison: Amazon shipping is excluded, while all other shops keep
            # their shipping costs. Remove only historical Amazon rows that were
            # explicitly stored as an all-in price including shipping and force a
            # zero-Google-Search refresh of mapped Idealo pages. MyDealz watches
            # are also refreshed once so all saved active threads get revalidated.
            affected = conn.execute(
                "SELECT DISTINCT product_id FROM idealo_prices "
                "WHERE lower(COALESCE(shop,'')) LIKE '%amazon%' "
                "AND lower(COALESCE(price_kind,'')) LIKE 'gesamtpreis inkl. versand%'"
            ).fetchall()
            affected_ids = [int(r[0]) for r in affected]
            conn.execute(
                "DELETE FROM idealo_prices WHERE lower(COALESCE(shop,'')) LIKE '%amazon%' "
                "AND lower(COALESCE(price_kind,'')) LIKE 'gesamtpreis inkl. versand%'"
            )
            for product_id_028 in affected_ids:
                first_028 = conn.execute(
                    "SELECT price_cents FROM idealo_prices WHERE product_id=? ORDER BY id ASC LIMIT 1",
                    (product_id_028,),
                ).fetchone()
                low_028 = conn.execute(
                    "SELECT MIN(price_cents) FROM idealo_prices WHERE product_id=?",
                    (product_id_028,),
                ).fetchone()
                conn.execute(
                    "UPDATE products SET idealo_start_price_cents=?, idealo_low_price_cents=? WHERE id=?",
                    (first_028[0] if first_028 else None, low_028[0] if low_028 and low_028[0] is not None else None, product_id_028),
                )
            conn.execute(
                """
                UPDATE products SET
                    idealo_current_price_cents=NULL, idealo_current_shop=NULL, idealo_current_offer_url=NULL,
                    idealo_price_kind=NULL, idealo_last_checked=NULL, idealo_last_success=NULL, idealo_last_error=NULL
                WHERE lower(COALESCE(idealo_current_shop,'')) LIKE '%amazon%'
                  AND lower(COALESCE(idealo_price_kind,'')) LIKE 'gesamtpreis inkl. versand%'
                """
            )
            conn.execute("UPDATE products SET idealo_last_checked=NULL WHERE idealo_enabled=1 AND idealo_url IS NOT NULL")
            conn.execute("UPDATE mydealz_watches SET last_checked=NULL, last_search_checked=NULL WHERE active=1")
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('repair_0_1_28_idealo_shipping_watch_refresh', ?)",
                (utc_now_iso(),),
            )

        repaired_031 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_31_durable_idealo_mydealz_push'").fetchone()
        if repaired_031 is None:
            # Existing MyDealz rows are the baseline. Only deals discovered after
            # this upgrade may generate a new-deal push.
            conn.execute("UPDATE mydealz_deals SET notified=1")

            # 0.1.30 could hide or subsequently clear a previously confirmed
            # Idealo mapping after a transient Reader identity warning. Recover
            # only from our own persisted Idealo price history; never spend a
            # Gemini request for this repair.
            rows_031 = conn.execute(
                "SELECT id,title,idealo_url,idealo_status,idealo_match_score,idealo_current_price_cents "
                "FROM products WHERE idealo_enabled=1"
            ).fetchall()
            for product_031 in rows_031:
                stored_031 = str(product_031["idealo_url"] or "")
                last_031 = conn.execute(
                    "SELECT checked_at,price_cents,shop,idealo_url,offer_url,price_kind "
                    "FROM idealo_prices WHERE product_id=? AND COALESCE(idealo_url,'')<>'' "
                    "ORDER BY id DESC LIMIT 1",
                    (product_031["id"],),
                ).fetchone()
                hist_031 = str(last_031["idealo_url"] or "") if last_031 else ""
                candidate_031 = stored_031 or hist_031
                if not candidate_031:
                    continue
                try:
                    direct_031 = _direct_idealo_url(candidate_031)
                except Exception:
                    direct_031 = ""
                if not direct_031:
                    continue
                identity_031 = idealo_url_identity_score(str(product_031["title"] or ""), direct_031, "")
                # A URL that was already persisted as idealo_url is considered a
                # durable confirmed mapping. A history-only recovery additionally
                # needs a plausible title/slug identity.
                if not stored_031 and identity_031 < IDEALO_UNCERTAIN_THRESHOLD:
                    continue
                restored_price_031 = product_031["idealo_current_price_cents"]
                if restored_price_031 is None and last_031:
                    restored_price_031 = last_031["price_cents"]
                conn.execute(
                    """
                    UPDATE products SET
                        idealo_url=?, idealo_status=CASE WHEN idealo_manual=1 THEN 'manual' ELSE 'matched' END,
                        idealo_match_score=MAX(COALESCE(idealo_match_score,0), ?),
                        idealo_current_price_cents=COALESCE(idealo_current_price_cents, ?),
                        idealo_current_shop=COALESCE(idealo_current_shop, ?),
                        idealo_current_offer_url=COALESCE(idealo_current_offer_url, ?),
                        idealo_price_kind=COALESCE(idealo_price_kind, ?),
                        idealo_last_success=COALESCE(idealo_last_success, ?),
                        idealo_last_error=NULL, idealo_reader_failures=0
                    WHERE id=?
                    """,
                    (direct_031, max(identity_031, float(product_031["idealo_match_score"] or 0.0)),
                     restored_price_031, last_031["shop"] if last_031 else None,
                     last_031["offer_url"] if last_031 else None,
                     last_031["price_kind"] if last_031 else None,
                     last_031["checked_at"] if last_031 else None, product_031["id"]),
                )
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('repair_0_1_31_durable_idealo_mydealz_push', ?)",
                (utc_now_iso(),),
            )

        repaired_038 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_38_idealo_current_from_history'").fetchone()
        if repaired_038 is None:
            rows_038 = conn.execute(
                "SELECT id,idealo_url,idealo_last_success FROM products WHERE idealo_enabled=1"
            ).fetchall()
            for product_038 in rows_038:
                last_038 = conn.execute(
                    """
                    SELECT checked_at,price_cents,shop,idealo_url,offer_url,price_kind
                    FROM idealo_prices
                    WHERE product_id=?
                    ORDER BY checked_at DESC, id DESC LIMIT 1
                    """,
                    (product_038["id"],),
                ).fetchone()
                if not last_038:
                    continue
                current_success_038 = parse_iso(product_038["idealo_last_success"])
                history_success_038 = parse_iso(last_038["checked_at"])
                if current_success_038 is not None and history_success_038 is not None and history_success_038 <= current_success_038:
                    continue
                candidate_url_038 = str(last_038["idealo_url"] or product_038["idealo_url"] or "")
                try:
                    direct_038 = _direct_idealo_url(candidate_url_038)
                except Exception:
                    direct_038 = ""
                conn.execute(
                    """
                    UPDATE products SET idealo_url=COALESCE(NULLIF(?,''),idealo_url),
                        idealo_status=CASE WHEN idealo_manual=1 THEN 'manual' ELSE 'matched' END,
                        idealo_current_price_cents=?, idealo_current_shop=?, idealo_current_offer_url=?,
                        idealo_price_kind=?, idealo_last_success=?, idealo_last_error=NULL,
                        idealo_reader_failures=0, updated_at=? WHERE id=?
                    """,
                    (direct_038, last_038["price_cents"], last_038["shop"], last_038["offer_url"],
                     last_038["price_kind"], last_038["checked_at"], utc_now_iso(), product_038["id"]),
                )
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('repair_0_1_38_idealo_current_from_history', ?)",
                (utc_now_iso(),),
            )

        repaired_039 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_39_idealo_article_price_only'").fetchone()
        if repaired_039 is None:
            # Earlier builds stored Idealo total prices including shipping as
            # the current Idealo price. Clear the live value once so the next
            # Reader/Gemini refresh repopulates it with the article price only.
            # Historical rows stay intact; only the visible live summary is reset.
            conn.execute(
                """
                UPDATE products SET idealo_current_price_cents=NULL, idealo_current_shop=NULL,
                    idealo_current_offer_url=NULL, idealo_price_kind=NULL, idealo_last_checked=NULL,
                    idealo_last_success=NULL, idealo_last_error=NULL, idealo_gemini_last_checked=NULL,
                    idealo_low_price_cents=NULL, idealo_start_price_cents=NULL,
                    idealo_reader_failures=0, updated_at=?
                WHERE idealo_enabled=1 AND idealo_url IS NOT NULL
                """,
                (utc_now_iso(),),
            )
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('repair_0_1_39_idealo_article_price_only', ?)",
                (utc_now_iso(),),
            )

        repaired_040 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_40_idealo_lowest_offer_price'").fetchone()
        if repaired_040 is None:
            # 0.1.39 treated Idealo's header price as authoritative. The real
            # table can contain a lower current offer for the same selected
            # variant, e.g. Amazon at 23,30 € while another shop shows 27,95 €
            # / 33,44 € inkl. Versand. Clear only visible summaries once so
            # the next check stores the lowest visible table price.
            conn.execute(
                """
                UPDATE products SET idealo_current_price_cents=NULL, idealo_current_shop=NULL,
                    idealo_current_offer_url=NULL, idealo_price_kind=NULL, idealo_last_checked=NULL,
                    idealo_last_success=NULL, idealo_last_error=NULL, idealo_gemini_last_checked=NULL,
                    idealo_low_price_cents=NULL, idealo_start_price_cents=NULL,
                    idealo_reader_failures=0, updated_at=?
                WHERE idealo_enabled=1 AND idealo_url IS NOT NULL
                """,
                (utc_now_iso(),),
            )
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('repair_0_1_40_idealo_lowest_offer_price', ?)",
                (utc_now_iso(),),
            )

        repaired_041 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_41_idealo_shop_specific_effective_price'").fetchone()
        if repaired_041 is None:
            # 0.1.40 still used the article-price column for every Idealo shop.
            # Correct rule: Amazon offers use the price column; all other shops
            # use the total price including shipping. Clear visible summaries
            # once so stale non-Amazon article prices disappear immediately.
            conn.execute(
                """
                UPDATE products SET idealo_current_price_cents=NULL, idealo_current_shop=NULL,
                    idealo_current_offer_url=NULL, idealo_price_kind=NULL, idealo_last_checked=NULL,
                    idealo_last_success=NULL, idealo_last_error=NULL, idealo_gemini_last_checked=NULL,
                    idealo_low_price_cents=NULL, idealo_start_price_cents=NULL,
                    idealo_reader_failures=0, updated_at=?
                WHERE idealo_enabled=1 AND idealo_url IS NOT NULL
                """,
                (utc_now_iso(),),
            )
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('repair_0_1_41_idealo_shop_specific_effective_price', ?)",
                (utc_now_iso(),),
            )

        repaired_042 = conn.execute("SELECT value FROM app_meta WHERE key='repair_0_1_42_idealo_gemini_offer_rows'").fetchone()
        if repaired_042 is None:
            # 0.1.41 still allowed Gemini URL Context to return one already
            # selected offer. For Fly Away that could be a non-Amazon total
            # price although an Amazon row was cheaper by the app rule. Clear
            # visible summaries once; 0.1.42 asks Gemini for offer rows and
            # selects deterministically in Python.
            conn.execute(
                """
                UPDATE products SET idealo_current_price_cents=NULL, idealo_current_shop=NULL,
                    idealo_current_offer_url=NULL, idealo_price_kind=NULL, idealo_last_checked=NULL,
                    idealo_last_success=NULL, idealo_last_error=NULL, idealo_gemini_last_checked=NULL,
                    idealo_low_price_cents=NULL, idealo_start_price_cents=NULL,
                    idealo_reader_failures=0, updated_at=?
                WHERE idealo_enabled=1 AND idealo_url IS NOT NULL
                """,
                (utc_now_iso(),),
            )
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('repair_0_1_42_idealo_gemini_offer_rows', ?)",
                (utc_now_iso(),),
            )


class AmazonHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.capture_stack: list[tuple[str, str, list[str]]] = []
        self.title = ""
        self.meta_title = ""
        self.image = ""
        self.meta_image = ""
        self.availability = ""
        self.seller = ""
        self.condition = ""
        self.offscreen_prices: list[tuple[str, str]] = []
        self.known_price_text: list[tuple[str, str]] = []
        self.json_ld_chunks: list[str] = []
        self._script_ld_depth = 0
        self._script_buffer: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {k.lower(): (v or "") for k, v in attrs}

    def _context(self) -> str:
        parts = []
        for item in self.stack[-8:]:
            if item.get("id"):
                parts.append(item["id"])
            if item.get("class"):
                parts.append(item["class"])
        return " ".join(parts).lower()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = self._attrs(attrs)
        entry = {"tag": tag.lower(), "id": a.get("id", ""), "class": a.get("class", "")}
        self.stack.append(entry)
        tag_l = tag.lower()
        id_l = a.get("id", "").lower()
        class_l = a.get("class", "").lower()

        if tag_l == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            content = a.get("content", "").strip()
            if prop == "og:title" and content:
                self.meta_title = content
            elif prop in {"og:image", "twitter:image"} and content and not self.meta_image:
                self.meta_image = content

        if tag_l == "img" and id_l == "landingimage":
            dynamic = a.get("data-a-dynamic-image", "")
            old = a.get("data-old-hires", "")
            src = a.get("src", "")
            if old:
                self.image = old
            elif dynamic:
                try:
                    obj = json.loads(html.unescape(dynamic))
                    if isinstance(obj, dict) and obj:
                        self.image = max(obj.items(), key=lambda kv: (kv[1][0] if isinstance(kv[1], list) and kv[1] else 0))[0]
                except Exception:
                    pass
            if not self.image and src:
                self.image = src

        if tag_l == "script" and "application/ld+json" in a.get("type", "").lower():
            self._script_ld_depth += 1
            self._script_buffer = []

        capture_id_map = {
            "producttitle": "title",
            "availability": "availability",
            "sellerprofiletriggerid": "seller",
            "merchant-info": "seller",
            "condition": "condition",
            "buybox-see-all-buying-choices": "condition",
            "price_inside_buybox": "price",
            "newbuyboxprice": "price",
            "priceblock_ourprice": "price",
            "priceblock_dealprice": "price",
        }
        if id_l in capture_id_map:
            self.capture_stack.append((tag_l, capture_id_map[id_l], []))

        if "a-offscreen" in class_l.split():
            self.capture_stack.append((tag_l, "offscreen", []))

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if self.capture_stack and self.capture_stack[-1][0] == tag_l:
            _, kind, pieces = self.capture_stack.pop()
            text = " ".join(" ".join(pieces).split()).strip()
            if text:
                if kind == "title" and not self.title:
                    self.title = text
                elif kind == "availability" and not self.availability:
                    self.availability = text
                elif kind == "seller" and not self.seller:
                    self.seller = text
                elif kind == "condition" and not self.condition:
                    self.condition = text
                elif kind == "price":
                    self.known_price_text.append((text, self._context()))
                elif kind == "offscreen":
                    self.offscreen_prices.append((text, self._context()))

        if tag_l == "script" and self._script_ld_depth:
            self._script_ld_depth -= 1
            raw = "".join(self._script_buffer).strip()
            if raw:
                self.json_ld_chunks.append(raw)
            self._script_buffer = []

        if self.stack:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i]["tag"] == tag_l:
                    del self.stack[i:]
                    break

    def handle_data(self, data: str) -> None:
        if self._script_ld_depth:
            self._script_buffer.append(data)
        if self.capture_stack:
            self.capture_stack[-1][2].append(data)


def parse_price_to_cents(text: str) -> int | None:
    if not text:
        return None
    m = PRICE_RE.search(text.replace("\xa0", " "))
    if not m:
        alt = re.search(r"(?<!\d)(\d{1,4}[.,]\d{2})(?!\d)", text)
        if not alt:
            return None
        raw = alt.group(1)
        if raw.count(".") == 1 and raw.count(",") == 0:
            raw = raw.replace(".", ",")
    else:
        raw = m.group(1)
    raw = raw.replace(".", "").replace(",", ".")
    try:
        value = float(raw)
        if 0.01 <= value <= 100000:
            return int(round(value * 100))
    except ValueError:
        return None
    return None


def extract_json_ld_product(parser: AmazonHTMLParser) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for raw in parser.json_ld_chunks:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        items: list[Any]
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict) and isinstance(parsed.get("@graph"), list):
            items = parsed["@graph"]
        else:
            items = [parsed]
        for item in items:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "product":
                candidates.append(item)
    return candidates[0] if candidates else {}


def choose_price(parser: AmazonHTMLParser, html_text: str) -> int | None:
    # Prefer price candidates found inside Amazon's primary price/buybox regions.
    priority_terms = (
        "coreprice", "corepricedisplay", "apex", "buybox", "desktop_buybox",
        "price_inside_buybox", "newbuyboxprice", "dealprice", "ourprice",
    )
    reject_terms = ("a-text-price", "basisprice", "listprice", "list-price", "was-price", "strike", "usedbuybox", "usedaccordion")
    candidates = parser.known_price_text + parser.offscreen_prices
    # Strongest signal first: Amazon's price-to-pay / buybox/current price containers.
    strong_terms = ("pricetopay", "price-to-pay", "price_inside_buybox", "newbuyboxprice", "coreprice", "apex", "buybox")
    for text, context in candidates:
        if any(term in context for term in reject_terms):
            continue
        if any(term in context for term in strong_terms):
            cents = parse_price_to_cents(text)
            if cents is not None:
                return cents
    for text, context in candidates:
        if any(term in context for term in reject_terms):
            continue
        if any(term in context for term in priority_terms):
            cents = parse_price_to_cents(text)
            if cents is not None:
                return cents

    # JSON-LD is a useful second source when Amazon includes a current offer.
    product = extract_json_ld_product(parser)
    offers = product.get("offers") if isinstance(product, dict) else None
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        if price is not None:
            try:
                value = float(str(price).replace(",", "."))
                if 0.01 <= value <= 100000:
                    return int(round(value * 100))
            except Exception:
                pass
    elif isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict) and offer.get("price") is not None:
                try:
                    value = float(str(offer["price"]).replace(",", "."))
                    if 0.01 <= value <= 100000:
                        return int(round(value * 100))
                except Exception:
                    pass

    # Known legacy price IDs as HTML fallback.
    for pid in ("price_inside_buybox", "newBuyBoxPrice", "priceblock_ourprice", "priceblock_dealprice"):
        m = re.search(rf'id=["\']{re.escape(pid)}["\'][^>]*>(.*?)<', html_text, re.I | re.S)
        if m:
            cents = parse_price_to_cents(re.sub(r"<[^>]+>", " ", m.group(1)))
            if cents is not None:
                return cents

    return None


def extract_aod_new_price(html_text: str) -> int | None:
    # Amazon can hide the primary price while still exposing an exact "Neu (...) ab" price
    # in the All Offers Display ingress. This is not treated as a Buy Box price.
    m = re.search(
        r'id=["\']aod-ingress-link["\'][^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    )
    if not m:
        return None
    block = m.group(1)
    text = re.sub(r"<[^>]+>", " ", block)
    text = html.unescape(text)
    if "neu" not in text.lower():
        return None
    return parse_price_to_cents(text)


def extract_used_offer(html_text: str, asin: str) -> dict[str, Any]:
    """Extract the lowest price that is explicitly marked as used."""
    text = html_to_text(html_text)
    candidates: list[int] = []

    patterns = [
        r"(?i)Gebraucht(?:\s*kaufen)?(?:\s*[:\-]\s*[^€]{0,90})?[^€]{0,180}?(\d{1,5}(?:[.,]\d{2})?)\s*€",
        r"(?i)Gebrauchte?\s+(?:Angebote?|Artikel)[^€]{0,180}?(\d{1,5}(?:[.,]\d{2})?)\s*€",
        r"(?i)(\d{1,5}(?:[.,]\d{2})?)\s*€[^\n]{0,120}?Gebraucht",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            price = parse_price_to_cents(match.group(1))
            if price is not None:
                candidates.append(price)

    lower = html_text.lower()
    for token in ("gebraucht", "usedbuybox", "condition=used", "condition%3dused"):
        pos = 0
        while True:
            idx = lower.find(token, pos)
            if idx < 0:
                break
            block = html_text[max(0, idx - 1600):idx + 2400]
            block_text = html_to_text(block)
            used_positions = [m.start() for m in re.finditer(r"(?i)gebraucht|used", block_text)]
            for pm in PRICE_RE.finditer(block_text):
                if not used_positions or min(abs(pm.start() - u) for u in used_positions) > 220:
                    continue
                before = block_text[max(0, pm.start() - 45):pm.start()].lower()
                if "versand" in before or "lieferung" in before or "shipping" in before:
                    continue
                price = parse_price_to_cents(pm.group(0))
                if price is not None:
                    candidates.append(price)
            pos = idx + max(1, len(token))

    price_cents = min((p for p in candidates if 1 <= p <= 10_000_000), default=None)

    condition = "Gebraucht"
    cm = re.search(r"(?i)Gebraucht\s*:\s*([^|·€\d]{2,50})", text)
    if cm:
        condition = "Gebraucht: " + " ".join(cm.group(1).split())[:60]

    offer_url = ""
    escaped_asin = re.escape(asin)
    patterns_url = [
        r'''(?is)href=["']([^"']*(?:condition(?:=|%3D)used|offer-listing/''' + escaped_asin + r''')[^"']*)["']''',
        r'''(?is)href=["']([^"']*aod[^"']*(?:used|gebraucht)[^"']*)["']''',
    ]
    for pattern in patterns_url:
        match = re.search(pattern, html_text)
        if match:
            offer_url = urllib.parse.urljoin("https://www.amazon.de", html.unescape(match.group(1)))
            break
    if not offer_url:
        offer_url = f"https://www.amazon.de/dp/{asin}?condition=used"

    return {
        "available": price_cents is not None,
        "price_cents": price_cents,
        "condition": condition,
        "offer_url": offer_url,
    }


def normalize_seller(text: str) -> str:
    clean = " ".join(html.unescape(text or "").split()).strip()
    if not clean:
        return ""
    # Amazon's merchant info can contain shipping boilerplate. Keep useful first sentence/segment.
    for sep in (" Versand", " Rückgabe", " Zahlung", " Details"):
        idx = clean.find(sep)
        if idx > 0:
            clean = clean[:idx].strip()
    clean = re.sub(r"^Verkauf durch\s*", "", clean, flags=re.I)
    return clean[:180]


def fetch_url(url: str, timeout: int = 20, referer: str | None = None) -> tuple[bytes, str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept-Encoding": "gzip, identity",
        "Connection": "close",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            body = gzip.decompress(body)
        return body, resp.geturl(), resp.headers.get("Content-Type", "")


def resolve_asin(input_url: str) -> tuple[str, str]:
    raw = input_url.strip()
    if not raw:
        raise ValueError("Bitte einen Amazon-Link eingeben.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw

    parsed = urllib.parse.urlparse(raw)
    host = parsed.netloc.lower().split(":", 1)[0]
    if not (host.endswith("amazon.de") or host == "amzn.eu"):
        raise ValueError("Aktuell werden nur Amazon.de- und amzn.eu-Links unterstützt.")

    for source in (raw, parsed.query):
        m = ASIN_RE.search(source) or ASIN_QUERY_RE.search(source)
        if m:
            asin = m.group(1).upper()
            return asin, f"https://www.amazon.de/dp/{asin}"

    # Short links require redirect resolution.
    try:
        _, final_url, _ = fetch_url(raw, timeout=15)
    except Exception as exc:
        raise ValueError(f"Amazon-Link konnte nicht aufgelöst werden: {exc}") from exc
    m = ASIN_RE.search(final_url) or ASIN_QUERY_RE.search(final_url)
    if not m:
        raise ValueError("Aus dem Amazon-Link konnte keine ASIN erkannt werden.")
    asin = m.group(1).upper()
    return asin, f"https://www.amazon.de/dp/{asin}"


def fetch_amazon_product(asin: str) -> dict[str, Any]:
    url = f"https://www.amazon.de/dp/{asin}?th=1&psc=1"
    body, final_url, content_type = fetch_url(url, timeout=PRODUCT_TIMEOUT_SECONDS)
    text = body.decode("utf-8", errors="replace")
    lower = text.lower()
    if "user@example.invalid" in lower or "enter the characters you see below" in lower or "robot check" in lower:
        raise RuntimeError("Amazon hat eine CAPTCHA-/Bot-Prüfung ausgeliefert.")
    if len(text) < 5000:
        raise RuntimeError("Amazon hat eine ungewöhnlich kurze Produktseite geliefert.")

    parser = AmazonHTMLParser()
    parser.feed(text)
    product_ld = extract_json_ld_product(parser)

    title = (parser.title or parser.meta_title or str(product_ld.get("name") or "")).strip()
    image = parser.image or parser.meta_image
    if not image and product_ld:
        img = product_ld.get("image")
        if isinstance(img, str):
            image = img
        elif isinstance(img, list) and img:
            image = str(img[0])

    price_cents = choose_price(parser, text)
    price_source = "Buy Box" if price_cents is not None else ""
    if price_cents is None:
        price_cents = extract_aod_new_price(text)
        if price_cents is not None:
            price_source = "Neu ab"
    seller = normalize_seller(parser.seller)
    availability = " ".join(parser.availability.split()).strip()
    condition = " ".join(parser.condition.split()).strip()
    if condition and "gebraucht" in condition.lower() and "neu" not in condition.lower():
        price_cents = None
        price_source = ""
    if not seller:
        merchant_match = re.search(r"Verkauf durch\s*</?[^>]*>\s*([^<]{2,100})", text, re.I)
        if merchant_match:
            seller = normalize_seller(merchant_match.group(1))
    if not seller and re.search(r"Verkauf und Versand durch Amazon", text, re.I):
        seller = "Amazon"
    if price_source == "Neu ab":
        # The page-level seller can refer to a different selected offer than the
        # lowest "Neu ab" price, so do not attach an unverified seller to it.
        seller = ""

    if not availability:
        if "auf lager" in lower:
            availability = "Auf Lager"
        elif "derzeit nicht verfügbar" in lower:
            availability = "Derzeit nicht verfügbar"

    if not title:
        title = f"Amazon-Artikel {asin}"

    used_offer = extract_used_offer(text, asin)

    return {
        "asin": asin,
        "amazon_url": f"https://www.amazon.de/dp/{asin}",
        "final_url": final_url,
        "title": title[:500],
        "image_url": image[:1200] if image else "",
        "price_cents": price_cents,
        "price_source": price_source,
        "seller": seller,
        "availability": availability[:250],
        "condition": condition[:120],
        "used_available": bool(used_offer.get("available")),
        "used_price_cents": used_offer.get("price_cents"),
        "used_condition": str(used_offer.get("condition") or "")[:120],
        "used_offer_url": str(used_offer.get("offer_url") or "")[:1200],
        "content_type": content_type,
    }


class IdealoSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current: dict[str, Any] | None = None
        self.depth = 0
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        tag_l = tag.lower()
        if tag_l == "a":
            href = html.unescape(a.get("href", ""))
            if "/preisvergleich/OffersOfProduct/" in href:
                self.current = {
                    "url": urllib.parse.urljoin("https://www.idealo.de", href),
                    "title": a.get("title", "") or a.get("aria-label", ""),
                    "text": "",
                }
                return
        if self.current is not None and tag_l == "img":
            alt = a.get("alt", "").strip()
            if alt and len(alt) > len(self.current.get("title", "")):
                self.current["title"] = alt

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current["text"] += " " + data

    def handle_endtag(self, tag: str) -> None:
        if self.current is None or tag.lower() != "a":
            return
        title = " ".join((self.current.get("title", "") + " " + self.current.get("text", "")).split()).strip()
        if self.current.get("url"):
            self.results.append({"url": self.current["url"], "title": title})
        self.current = None


def normalize_match_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " und ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def significant_tokens(value: str) -> set[str]:
    stop = {
        "und", "oder", "mit", "fur", "von", "der", "die", "das", "den", "dem", "des", "ein", "eine",
        "bei", "auf", "zum", "zur", "inkl", "amazon", "deutschland", "neu", "original", "geeignet",
    }
    return {t for t in normalize_match_text(value).split() if len(t) >= 2 and t not in stop}


def extract_quantities(value: str) -> set[tuple[str, str]]:
    norm = normalize_match_text(value)
    unit_map = {
        "stuck": "st", "stueck": "st", "st": "st", "tabletten": "st", "tablette": "st", "pcs": "st",
        "ml": "ml", "milliliter": "ml", "l": "l", "liter": "l", "g": "g", "gramm": "g", "kg": "kg",
        "pack": "pack", "packs": "pack", "er": "pack",
    }
    out: set[tuple[str, str]] = set()
    for m in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(stuck|stueck|st|tabletten|tablette|pcs|ml|milliliter|l|liter|g|gramm|kg|pack|packs)\b", norm):
        out.add((m.group(1).replace(",", "."), unit_map.get(m.group(2), m.group(2))))
    return out


def product_match_score(expected: str, candidate: str) -> float:
    a = normalize_match_text(expected)
    b = normalize_match_text(candidate)
    if not a or not b:
        return 0.0
    ta, tb = significant_tokens(a), significant_tokens(b)
    union = ta | tb
    jaccard = len(ta & tb) / len(union) if union else 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    nums_a = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", a))
    nums_b = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", b))
    num_score = 1.0 if not nums_a else len(nums_a & nums_b) / len(nums_a)
    qa = extract_quantities(expected)
    qb = extract_quantities(candidate)
    quantity_score = 1.0 if not qa else len(qa & qb) / len(qa)
    if qa and quantity_score < 1.0:
        return min(0.44, 0.25 * seq + 0.20 * jaccard)
    extra_numeric_penalty = 0.0
    if nums_a and nums_b and (nums_b - nums_a):
        extra_numeric_penalty = min(0.18, 0.06 * len(nums_b - nums_a))
    return max(0.0, min(1.0, 0.42 * seq + 0.30 * jaccard + 0.16 * num_score + 0.12 * quantity_score - extra_numeric_penalty))


def _mydealz_brand_anchor(expected: str) -> str:
    """Return the product brand/manufacturer anchor from an Amazon title.

    Amazon product titles used by this app start with the brand in our observed
    catalogue (KESPER, SIGG, Ninja, Alfavet, ...). For deal matching we prefer a
    false negative over attaching a deal from another manufacturer.
    """
    generic = {
        "amazon", "original", "produkt", "artikel", "neu", "set", "pack", "bundle",
        "isolierte", "kinder", "heissluftfritteuse", "heißluftfritteuse", "schneidebrett",
        "trinkflasche", "erganzungsfuttermittel", "ergänzungsfuttermittel",
    }
    for token in normalize_match_text(expected).split():
        if token in generic or token.isdigit() or len(token) < 3:
            continue
        if any(ch.isalpha() for ch in token):
            return token
    return ""


def _mydealz_model_anchors(expected: str) -> set[str]:
    """Hard model identifiers such as AF200EU or N30516."""
    out: set[str] = set()
    for token in normalize_match_text(expected).split():
        if len(token) >= 4 and any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token):
            out.add(token)
    return out


def _mydealz_variant_anchors(expected: str) -> set[str]:
    """Return a small hard variant anchor for titles that expose one clearly.

    SIGG-style Amazon titles are structured as ``Brand - Category - Variant - ...``.
    The final two words of that variant segment (for example ``fly away`` or
    ``uni stars``) are much safer than generic category words. We intentionally
    use this only when the title has that explicit structure; other products are
    handled by brand/model and concise token coverage instead.
    """
    parts = [normalize_match_text(x) for x in re.split(r"\s+-\s+", expected or "") if normalize_match_text(x)]
    if len(parts) < 3:
        return set()
    tokens = [t for t in parts[2].split() if len(t) >= 2 and not t.isdigit()]
    if len(tokens) < 2:
        return set()
    return set(tokens[-2:])


def _mydealz_numeric_variant_values(value: str, label: str) -> set[str]:
    raw = unicodedata.normalize("NFKD", value or "")
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch)).lower().replace(",", ".")
    raw = re.sub(r"[^a-z0-9.]+", " ", raw)
    patterns = {
        "fach": r"\b(\d{1,3})\s*fach\b",
        "meter": r"\b(\d+(?:\.\d+)?)\s*m\b",
        "liter": r"\b(\d+(?:\.\d+)?)\s*l\b",
        "ml": r"\b(\d+(?:\.\d+)?)\s*ml\b",
    }
    pattern = patterns.get(label)
    if not pattern:
        return set()
    return set(re.findall(pattern, raw, re.I))


def _mydealz_hard_variant_conflict(expected: str, candidate: str) -> bool:
    """Reject explicit contradictory variants while allowing omitted details.

    Missing size/length information is not a conflict. If both sides explicitly
    state a value and those values disagree, the candidate cannot represent the
    watched variant.
    """
    for label in ("fach", "meter", "liter", "ml"):
        a = _mydealz_numeric_variant_values(expected, label)
        b = _mydealz_numeric_variant_values(candidate, label)
        if a and b and a.isdisjoint(b):
            return True

    ea = normalize_match_text(expected)
    ca = normalize_match_text(candidate)
    female_e = bool(re.search(r"\b(damen|frau|frauen|women|woman)\b", ea))
    male_e = bool(re.search(r"\b(herren|herr|mann|manner|men|man)\b", ea))
    female_c = bool(re.search(r"\b(damen|frau|frauen|women|woman)\b", ca))
    male_c = bool(re.search(r"\b(herren|herr|mann|manner|men|man)\b", ca))
    if female_e and not male_e and male_c and not female_c:
        return True
    if male_e and not female_e and female_c and not male_c:
        return True
    return False


def mydealz_identity_score(expected: str, candidate: str) -> float:
    """Strict but short-title-friendly deal identity score.

    Brand and explicit model identifiers are hard constraints. Explicit variant
    anchors (when present in structured Amazon titles) are hard constraints too.
    Afterwards a concise MyDealz title may still score highly when it contains
    the important product words even though it omits Amazon marketing prose.
    This keeps SIGG↔EMSA blocked while allowing titles such as
    ``Kosmos Castle Combo Kartenspiel`` to match the much longer Amazon title.
    """
    a = normalize_match_text(expected)
    b = normalize_match_text(candidate)
    if not a or not b:
        return 0.0
    if _mydealz_hard_variant_conflict(expected, candidate):
        return 0.0
    candidate_tokens = set(b.split())
    brand = _mydealz_brand_anchor(expected)
    if brand and brand not in candidate_tokens:
        return 0.0
    models = _mydealz_model_anchors(expected)
    if models and not models.issubset(candidate_tokens):
        return 0.0
    variants = _mydealz_variant_anchors(expected)
    if variants and not variants.issubset(candidate_tokens):
        return 0.0

    qa = extract_quantities(expected)
    qb = extract_quantities(candidate)
    if qa and qb and not qa.issubset(qb):
        return 0.0

    base = product_match_score(expected, candidate)

    noise = {
        "amazon", "prime", "deal", "angebot", "preis", "eur", "euro",
        "kartenspiel", "produkt", "neu", "inkl", "versand", "bei",
    }
    expected_tokens = significant_tokens(a)
    short_tokens = {
        t for t in significant_tokens(b)
        if t not in noise and t != brand and not re.fullmatch(r"\d+(?:[.,]\d+)?", t)
    }
    overlap = short_tokens & expected_tokens
    candidate_coverage = len(overlap) / len(short_tokens) if short_tokens else 0.0
    if len(overlap) >= 2 and candidate_coverage >= 0.70:
        base = max(base, 0.50 + min(0.20, 0.04 * (len(overlap) - 2)))
    return max(0.0, min(1.0, base))


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script\b.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return " ".join(html.unescape(raw).replace("\xa0", " ").split())


def html_to_line_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script\b.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<tr\b[^>]*>", "\n* ", raw)
    raw = re.sub(r"(?is)</tr\s*>", "\n", raw)
    raw = re.sub(r"(?is)<li\b[^>]*>", "\n* ", raw)
    raw = re.sub(r"(?is)</(?:li|article|section)\s*>", "\n", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</(?:td|th|div|p|h[1-6]|span|a|button)\s*>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    lines = [" ".join(line.split()) for line in html.unescape(raw).replace("\xa0", " ").splitlines()]
    return "\n".join(line for line in lines if line)


def extract_page_h1(raw: str) -> str:
    m = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1>", raw)
    if m:
        return html_to_text(m.group(1))[:500]
    m = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", raw)
    return html_to_text(m.group(1))[:500] if m else ""


def extract_ld_json_products(raw: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in re.finditer(r"(?is)<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", raw):
        try:
            obj = json.loads(html.unescape(m.group(1)).strip())
        except Exception:
            continue
        items: list[Any] = obj if isinstance(obj, list) else ([*obj.get("@graph", [])] if isinstance(obj, dict) and isinstance(obj.get("@graph"), list) else [obj])
        for item in items:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "product":
                out.append(item)
    return out



def load_app_options() -> dict[str, Any]:
    try:
        if OPTIONS_PATH.exists():
            data = json.loads(OPTIONS_PATH.read_text("utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        log.warning("App-Konfiguration konnte nicht gelesen werden.", exc_info=True)
    return {}


def gemini_settings() -> tuple[str, str]:
    options = load_app_options()
    key = str(options.get("gemini_api_key") or "").strip()
    configured = str(options.get("gemini_model") or "").strip()
    # 0.1.19 used Flash-Lite as the default. Existing Home Assistant add-on
    # options survive an update, so transparently upgrade only that former
    # default to the new 3.7 Flash default. Explicit 3.5 Flash/3.6 choices
    # remain respected.
    model = DEFAULT_GEMINI_MODEL if not configured or configured in LEGACY_DEFAULT_GEMINI_MODELS else configured
    return key, model


def gemini_configured() -> bool:
    key, _ = gemini_settings()
    return bool(key)


def idealo_checks_per_day() -> int:
    """Return the supported global Idealo schedule: once or four times daily."""
    try:
        configured = int(load_app_options().get("idealo_checks_per_day", 1))
    except Exception:
        configured = 1
    return 4 if configured >= 4 else 1


def idealo_schedule_hours() -> tuple[int, ...]:
    return IDEALO_EXTENDED_HOURS if idealo_checks_per_day() == 4 else IDEALO_STANDARD_HOURS


def idealo_schedule_label() -> str:
    return "08:00, 12:00, 16:00 und 20:00 Uhr" if idealo_checks_per_day() == 4 else "täglich um 12:00 Uhr"


def _gemini_month_key() -> str:
    return datetime.now().astimezone().strftime("%Y-%m")


def _grounding_google_search_count(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return 0
    counts = usage.get("grounding_tool_count") or []
    if isinstance(counts, dict):
        counts = [counts]
    total = 0
    if isinstance(counts, list):
        for item in counts:
            if not isinstance(item, dict) or str(item.get("type") or "") != "google_search":
                continue
            try:
                total += max(0, int(item.get("count") or 0))
            except Exception:
                continue
    return total


def record_gemini_google_search_usage(payload: dict[str, Any], purpose: str = "") -> int:
    """Persist exact Google Search query usage returned by the Interactions API."""
    queries = _grounding_google_search_count(payload)
    month = _gemini_month_key()
    now = utc_now_iso()
    try:
        with db_connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO app_meta(key, value) VALUES('gemini_usage_tracking_started_at', ?)",
                (now,),
            )
            query_key = f"gemini_google_search_queries_{month}"
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (query_key,)).fetchone()
            try:
                current = int(row[0]) if row else 0
            except Exception:
                current = 0
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (query_key, str(current + queries)),
            )
            if purpose == "idealo_discovery":
                mapping_key = f"gemini_idealo_mapping_attempts_{month}"
                row = conn.execute("SELECT value FROM app_meta WHERE key=?", (mapping_key,)).fetchone()
                try:
                    mappings = int(row[0]) if row else 0
                except Exception:
                    mappings = 0
                conn.execute(
                    "INSERT INTO app_meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (mapping_key, str(mappings + 1)),
                )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('gemini_usage_last_updated_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )
    except Exception:
        log.warning("Gemini-Google-Search-Nutzung konnte nicht gespeichert werden.", exc_info=True)
    return queries


def gemini_usage_stats() -> dict[str, Any]:
    month = _gemini_month_key()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    queries = 0
    mappings = 0
    idealo_url_context_requests = 0
    started = None
    updated = None
    try:
        with db_connect() as conn:
            values = {
                row["key"]: row["value"]
                for row in conn.execute(
                    "SELECT key, value FROM app_meta WHERE key IN (?, ?, ?, 'gemini_usage_tracking_started_at', 'gemini_usage_last_updated_at')",
                    (
                        f"gemini_google_search_queries_{month}",
                        f"gemini_idealo_mapping_attempts_{month}",
                        f"idealo_url_context_checks_{today}",
                    ),
                ).fetchall()
            }
        queries = int(values.get(f"gemini_google_search_queries_{month}", "0") or 0)
        mappings = int(values.get(f"gemini_idealo_mapping_attempts_{month}", "0") or 0)
        idealo_url_context_requests = int(values.get(f"idealo_url_context_checks_{today}", "0") or 0)
        started = values.get("gemini_usage_tracking_started_at")
        updated = values.get("gemini_usage_last_updated_at")
    except Exception:
        log.warning("Gemini-Nutzungsstatistik konnte nicht gelesen werden.", exc_info=True)
    try:
        month_label = datetime.strptime(month, "%Y-%m").strftime("%m/%Y")
    except Exception:
        month_label = month
    return {
        "month": month,
        "month_label": month_label,
        "google_search_queries": queries,
        "idealo_mapping_attempts": mappings,
        "tracking_started_at": started,
        "last_updated_at": updated,
        "shared_free_monthly_limit": GOOGLE_SEARCH_FREE_MONTHLY_SHARED,
        "idealo_url_context_requests_today": idealo_url_context_requests,
        "idealo_schedule_label": idealo_schedule_label(),
        "scope": "Google-Suchen werden aus Geminis usage.grounding_tool_count gezählt. August 2026 startet mit dem bekannten Cloud-Billing-/Terminalwert 489; spätere Monate starten bei 0.",
    }


def record_idealo_url_context_request() -> None:
    """Keep a transparent daily count; schedule slots, not a hidden cap, limit checks."""
    key = f"idealo_url_context_checks_{datetime.now(IDEALO_SCHEDULE_TIMEZONE).strftime('%Y-%m-%d')}"
    try:
        with db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            try:
                current = int(row[0]) if row else 0
            except Exception:
                current = 0
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(current + 1)),
            )
    except Exception:
        log.warning("Idealo-URL-Context-Nutzung konnte nicht gezählt werden.", exc_info=True)

def _interaction_text_and_citations(payload: dict[str, Any]) -> tuple[str, list[str]]:
    texts: list[str] = []
    citations: list[str] = []
    if isinstance(payload.get("output_text"), str):
        texts.append(payload["output_text"])
    steps = payload.get("steps") or payload.get("outputs") or []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            content = step.get("content") or []
            if isinstance(content, dict):
                content = [content]
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if isinstance(block.get("text"), str):
                    texts.append(block["text"])
                for annotation in block.get("annotations") or []:
                    if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                        url = str(annotation.get("url") or "").strip()
                        if url:
                            citations.append(url)
    return "\n".join(t for t in texts if t).strip(), list(dict.fromkeys(citations))


def gemini_search_json(prompt: str, schema: dict[str, Any], timeout: int = 45) -> tuple[dict[str, Any], list[str]]:
    key, model = gemini_settings()
    if not key:
        raise RuntimeError("Gemini API-Key fehlt. Bitte unter App → Konfiguration eintragen.")
    request_body = {
        "model": model,
        "input": prompt,
        "tools": [{"type": "google_search"}],
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        },
    }
    req = urllib.request.Request(
        GEMINI_INTERACTIONS_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "x-goog-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AmazonPreiswatcher/" + APP_VERSION,
        },
    )
    global GEMINI_LAST_CALL_AT
    try:
        with GEMINI_API_LOCK:
            wait = GEMINI_MIN_GAP_SECONDS - (time.monotonic() - GEMINI_LAST_CALL_AT)
            if wait > 0:
                time.sleep(wait)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            GEMINI_LAST_CALL_AT = time.monotonic()
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        if exc.code in {401, 403}:
            raise RuntimeError("Gemini API-Key wurde abgelehnt. Bitte App-Konfiguration prüfen.") from exc
        if exc.code == 429:
            raise RuntimeError("Gemini-Limit ist momentan erreicht. Bitte später erneut versuchen.") from exc
        raise RuntimeError(f"Gemini meldete HTTP {exc.code}: {detail}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Gemini lieferte keine gültige JSON-Antwort.") from exc
    if isinstance(payload, dict):
        record_gemini_google_search_usage(payload)
    text, citations = _interaction_text_and_citations(payload if isinstance(payload, dict) else {})
    if not text:
        raise RuntimeError("Gemini lieferte keinen auswertbaren Inhalt.")
    try:
        data = json.loads(text)
    except Exception as exc:
        raise RuntimeError("Gemini-Ergebnis konnte nicht als strukturierte Daten gelesen werden.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Gemini-Ergebnis hat ein unerwartetes Format.")
    return data, citations



def _interaction_text_and_sources(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    texts: list[str] = []
    sources: list[dict[str, str]] = []
    if isinstance(payload.get("output_text"), str):
        texts.append(payload["output_text"])
    steps = payload.get("steps") or payload.get("outputs") or []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            content = step.get("content") or []
            if isinstance(content, dict):
                content = [content]
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_text = str(block.get("text") or "")
                if block_text:
                    texts.append(block_text)
                for annotation in block.get("annotations") or []:
                    if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                        continue
                    url = str(annotation.get("url") or "").strip()
                    if not url:
                        continue
                    try:
                        start = int(annotation.get("start_index") or 0)
                        finish = int(annotation.get("end_index") or 0)
                    except Exception:
                        start = finish = 0
                    cited = block_text[start:finish].strip() if block_text and finish > start >= 0 else ""
                    sources.append({
                        "url": url,
                        "title": str(annotation.get("title") or "").strip(),
                        "cited_text": cited,
                    })
    # Deduplicate sources by URL while preserving the richest cited text.
    by_url: dict[str, dict[str, str]] = {}
    for src in sources:
        old = by_url.get(src["url"])
        if old is None or len(src.get("cited_text", "")) > len(old.get("cited_text", "")):
            by_url[src["url"]] = src
    return "\n".join(t for t in texts if t).strip(), list(by_url.values())


def _direct_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    for m in re.finditer(r"https?://[^\s<>()\]\[\"']+", text or "", re.I):
        url = m.group(0).rstrip(".,;:!?")
        if url not in urls:
            urls.append(url)
    return urls


def _short_market_query(title: str) -> str:
    norm = normalize_match_text(title)
    stop = {
        "mit", "material", "masse", "maße", "farbe", "natur", "fur", "für", "geeignet",
        "auslaufsicher", "kohlensauregeeignet", "kohlensäuregeeignet", "amazon", "neu", "cm", "mm",
    }
    words = []
    model_tokens = []
    for raw in norm.split():
        if raw in stop or raw in {"x", "l", "b", "d"}:
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?", raw):
            continue
        if any(c.isalpha() for c in raw) and any(c.isdigit() for c in raw):
            model_tokens.append(raw)
            continue
        if len(raw) >= 3 and raw not in words:
            words.append(raw)
    base = words[:6]
    for token in model_tokens[:2]:
        if token not in base:
            base.append(token)
    return " ".join(base[:8]) or " ".join(norm.split()[:6])


def _idealo_discovery_query(title: str) -> str:
    """Build a compact query that keeps model/variant words but drops marketing noise."""
    norm = normalize_match_text(title)
    generic = {
        "isolierte", "kinder", "kohlensauregeeignet", "kohlensäuregeeignet", "auslaufsicher",
        "spulmaschinenfest", "spülmaschinenfest", "bpa", "frei", "recycelter", "recyceltem",
        "edelstahl", "material", "masse", "maße", "farbe", "geeignet", "ohne", "antihaft",
        "korb", "knusperblech", "aufwarmen", "aufwärmen", "braten", "max", "crisp", "schwarz",
        "liter", "fächer", "facher", "90", "mit", "und", "der", "die", "das", "von", "amazon",
    }
    out: list[str] = []
    model_tokens: list[str] = []
    for token in norm.split():
        if any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token):
            if token not in model_tokens:
                model_tokens.append(token)
            continue
        if token in generic or len(token) < 3 or token.isdigit():
            continue
        if token not in out:
            out.append(token)
    concise = out[:7]
    for token in model_tokens[:2]:
        if token not in concise:
            concise.append(token)
    return " ".join(concise[:9]) or _short_market_query(title)


def gemini_search_text(
    prompt: str,
    timeout: int = 45,
    purpose: str = "",
    thinking_level: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Grounded Gemini search; automatic URLs are trusted only via resolved citations."""
    key, model = gemini_settings()
    if not key:
        raise RuntimeError("Gemini API-Key fehlt. Bitte unter App → Konfiguration eintragen.")
    request_body: dict[str, Any] = {
        "model": model,
        "input": prompt,
        "tools": [{"type": "google_search"}],
    }
    if thinking_level:
        request_body["generation_config"] = {"thinking_level": thinking_level}
    req = urllib.request.Request(
        GEMINI_INTERACTIONS_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "x-goog-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AmazonPreiswatcher/" + APP_VERSION,
        },
    )
    global GEMINI_LAST_CALL_AT
    try:
        with GEMINI_API_LOCK:
            wait = GEMINI_MIN_GAP_SECONDS - (time.monotonic() - GEMINI_LAST_CALL_AT)
            if wait > 0:
                time.sleep(wait)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            GEMINI_LAST_CALL_AT = time.monotonic()
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        if exc.code in {401, 403}:
            raise RuntimeError("Gemini API-Key wurde abgelehnt. Bitte App-Konfiguration prüfen.") from exc
        if exc.code == 429:
            raise RuntimeError("Gemini-Limit ist momentan erreicht. Bitte später erneut versuchen.") from exc
        raise RuntimeError(f"Gemini meldete HTTP {exc.code}: {detail}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Gemini lieferte keine gültige JSON-Antwort.") from exc
    if isinstance(payload, dict):
        queries = record_gemini_google_search_usage(payload, purpose=purpose)
        if purpose == "idealo_discovery" and queries > IDEALO_DISCOVERY_QUERY_BUDGET:
            log.warning(
                "Idealo-Zuordnung verbrauchte %s Google-Suchen trotz Prompt-Budget %s.",
                queries, IDEALO_DISCOVERY_QUERY_BUDGET,
            )
    text, sources = _interaction_text_and_sources(payload if isinstance(payload, dict) else {})
    if not text:
        raise RuntimeError("Gemini lieferte keinen auswertbaren Inhalt.")
    return text, sources

def resolve_grounding_citation_url(value: str, timeout: int = 20) -> str:
    """Resolve a Google grounding redirect to the publisher URL.

    Gemini Search citations can be `vertexaisearch.cloud.google.com/grounding-api-redirect/...`.
    The model-visible answer may contain a plausible but wrong URL, while the
    citation redirect points to the real indexed source. We therefore trust only
    the resolved citation target for automatic Idealo identity.
    """
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return ""
    host = parsed.netloc.lower().split(":", 1)[0]
    if host != "vertexaisearch.cloud.google.com" or "/grounding-api-redirect/" not in parsed.path:
        return value

    req = urllib.request.Request(
        value,
        method="GET",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
            "Connection": "close",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str(resp.geturl() or "").strip()
    except urllib.error.HTTPError as exc:
        # A publisher such as Idealo may return 403 after the redirect. HTTPError
        # still exposes the final target URL, which is exactly what we need.
        try:
            final = str(exc.geturl() or "").strip()
        except Exception:
            final = ""
        return final if final and final != value else ""
    except Exception:
        return ""


def _resolved_source(source: dict[str, str]) -> dict[str, str]:
    result = dict(source)
    original = str(source.get("url") or "").strip()
    resolved = resolve_grounding_citation_url(original)
    if resolved:
        result["grounding_url"] = original
        result["url"] = resolved
    return result


def _direct_idealo_url(value: str) -> str:
    try:
        url = validate_idealo_url(value)
    except Exception:
        return ""
    if "/preisvergleich/OffersOfProduct/" not in urllib.parse.urlparse(url).path:
        return ""
    return url


def _idealo_product_id(value: str) -> str:
    m = re.search(r"/OffersOfProduct/(\d+)", value or "", re.I)
    return m.group(1) if m else ""


def _url_slug_text(value: str) -> str:
    try:
        path = urllib.parse.unquote(urllib.parse.urlparse(value).path)
    except Exception:
        path = value or ""
    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"^[0-9]+_?", "", slug)
    return " ".join(re.sub(r"[-_]+", " ", slug).split())


def _market_identity_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    replacements = {
        "schneidebrett": "brett", "schneidbrett": "brett", "tranchierbrett": "brett",
        "akazienholz": "akazie", "heissluftfritteuse": "airfryer", "heißluftfritteuse": "airfryer",
        "fritteuse": "airfryer",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _dimension_sets(value: str) -> list[tuple[float, ...]]:
    text = (value or "").lower().replace("×", "x").replace(",", ".")
    text = re.sub(r"[-_/]+", " ", text)
    found: list[tuple[float, ...]] = []
    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)(?:\s*x\s*(\d+(?:\.\d+)?))?\s*(?:cm|mm)?", text):
        values = [float(match.group(1)), float(match.group(2))]
        if match.group(3):
            values.append(float(match.group(3)))
        found.append(tuple(values))
    return found


def idealo_identity_score(expected: str, candidate: str) -> float:
    """Conservative identity score for Idealo URLs/titles.

    Unlike the generic marketplace matcher, missing height/article numbers do not
    disqualify a result, but conflicting primary dimensions or a missing brand do.
    This accepts e.g. KESPER 32x21 even if Idealo omits the 1.5 cm height while
    rejecting unrelated wallpaper/PC pages.
    """
    a = _market_identity_text(expected)
    b = _market_identity_text(candidate)
    if not a or not b:
        return 0.0
    stop = {"mit", "material", "masse", "farbe", "natur", "fur", "fuer", "geeignet", "cm", "mm",
            "und", "der", "die", "das", "aus", "von", "kinder", "isolierte"}
    ta = {x for x in a.split() if len(x) >= 3 and x not in stop and not x.isdigit()}
    tb = {x for x in b.split() if len(x) >= 3 and x not in stop and not x.isdigit()}
    if not ta or not tb:
        return 0.0
    brand = next((x for x in a.split() if len(x) >= 3 and x not in stop and not x.isdigit()), "")
    if brand and brand not in tb:
        return 0.0
    overlap = ta & tb
    jaccard = len(overlap) / len(ta | tb) if ta | tb else 0.0
    coverage = len(overlap) / len(ta) if ta else 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    score = 0.35 * jaccard + 0.35 * coverage + 0.15 * seq
    expected_dims = _dimension_sets(expected)
    candidate_dims = _dimension_sets(candidate)
    if expected_dims and candidate_dims:
        e = expected_dims[0]
        c = candidate_dims[0]
        if len(e) >= 2 and len(c) >= 2:
            if abs(e[0] - c[0]) > 0.2 or abs(e[1] - c[1]) > 0.2:
                return min(score, 0.18)
            score += 0.22
            if len(e) >= 3 and len(c) >= 3:
                score += 0.04 if abs(e[2] - c[2]) <= 0.2 else -0.12
    return max(0.0, min(1.0, score))


def idealo_url_identity_score(expected: str, url: str, title: str = "") -> float:
    values = [_url_slug_text(url)]
    if title:
        values.append(title)
    return max((idealo_identity_score(expected, value) for value in values if value), default=0.0)


def _source_match_score(expected_title: str, source: dict[str, str]) -> float:
    """Score only source-owned identity fields, never model citation text.

    Google Search annotations can attach a citation URL to a model sentence that
    names the requested product even when the cited page is unrelated. Using
    cited_text for identity therefore allowed a correct KESPER sentence to bless
    an unrelated Idealo wallpaper URL. The URL slug and annotation title belong
    to the cited source itself and are safe identity signals.
    """
    slug = _url_slug_text(source.get("url", ""))
    source_title = " ".join(str(source.get("title") or "").split())
    scores: list[float] = []
    if slug:
        scores.append(product_match_score(expected_title, slug))
    if source_title:
        scores.append(product_match_score(expected_title, source_title))
    return max(scores) if scores else 0.0


def _extract_total_price_from_grounded_text(text: str) -> int | None:
    value = html.unescape(text or "").replace("\xa0", " ")
    patterns = (
        r"(?i)TOTAL_EUR\s*[=:]\s*(\d{1,5}(?:[.,]\d{1,2})?)",
        r"(?i)(?:günstigster\s+)?Gesamtpreis(?:\s+inkl(?:usive)?\.?\s+Versand)?[^0-9]{0,80}(\d{1,5}(?:[.,]\d{1,2})?)\s*€",
        r"(?i)(\d{1,5}(?:[.,]\d{1,2})?)\s*€[^\n]{0,50}inkl(?:usive)?\.?\s+Versand",
    )
    for pattern in patterns:
        m = re.search(pattern, value)
        if not m:
            continue
        cents = parse_deal_price_to_cents(m.group(1) + " €")
        if cents is not None and 1 <= cents <= 10_000_000:
            return cents
    return None


def _extract_shop_from_grounded_text(text: str) -> str:
    value = html.unescape(text or "").replace("\xa0", " ")
    for pattern in (r"(?im)^SHOP\s*[=:]\s*(.+?)\s*$", r"(?i)(?:Shop|Verkauf durch)\s*[:=]\s*([^|\n]{2,100})"):
        m = re.search(pattern, value)
        if m:
            return " ".join(m.group(1).split())[:120]
    return ""


def _idealo_is_amazon_offer(text: str) -> bool:
    norm = normalize_match_text(text or "")
    return bool(re.search(r"(?:^|\s)amazon(?:\s+de|\s+marketplace)?(?:\s|$)", norm))


def _is_timeout_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", None)
    return isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(exc).lower()


def gemini_url_json(
    prompt: str,
    schema: dict[str, Any],
    timeout: int = GEMINI_URL_CONTEXT_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], list[str]]:
    """Use Gemini URL Context only; this does not enable Google Search grounding."""
    key, model = gemini_settings()
    if not key:
        raise RuntimeError("Gemini API-Key fehlt. Bitte unter App → Konfiguration eintragen.")
    request_body = {
        "model": model,
        "input": prompt,
        "tools": [{"type": "url_context"}],
        "generation_config": {"thinking_level": "low"},
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        },
    }
    req = urllib.request.Request(
        GEMINI_INTERACTIONS_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "x-goog-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AmazonPreiswatcher/" + APP_VERSION,
        },
    )
    raw = b""
    last_retryable_error: BaseException | None = None
    retryable_kind = ""
    global GEMINI_LAST_CALL_AT
    for attempt in range(1, GEMINI_URL_CONTEXT_MAX_ATTEMPTS + 1):
        try:
            # URL Context shares the same Gemini quota and connection as Search.
            # Serialising requests avoids competing reads from manual checks,
            # scheduled checks and the "Alle Preise" action.
            with GEMINI_API_LOCK:
                wait = GEMINI_MIN_GAP_SECONDS - (time.monotonic() - GEMINI_LAST_CALL_AT)
                if wait > 0:
                    time.sleep(wait)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                GEMINI_LAST_CALL_AT = time.monotonic()
            break
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = ""
            if exc.code in {401, 403}:
                raise RuntimeError("Gemini API-Key wurde abgelehnt. Bitte App-Konfiguration prüfen.") from exc
            if exc.code == 429:
                raise RuntimeError("Gemini-Limit ist momentan erreicht. Bitte später erneut versuchen.") from exc
            if exc.code in {500, 502, 503, 504}:
                last_retryable_error = exc
                retryable_kind = "overloaded"
                if attempt < GEMINI_URL_CONTEXT_MAX_ATTEMPTS:
                    log.warning("Gemini URL Context ist temporär überlastet – einmaliger Wiederholungsversuch.")
                    time.sleep(4)
                    continue
                break
            raise RuntimeError(f"Gemini URL Context meldete HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if not _is_timeout_error(exc):
                raise RuntimeError(f"Gemini URL Context ist nicht erreichbar: {exc}") from exc
            last_retryable_error = exc
            retryable_kind = "timeout"
            if attempt < GEMINI_URL_CONTEXT_MAX_ATTEMPTS:
                log.warning("Gemini URL Context Zeitüberschreitung – einmaliger Wiederholungsversuch.")
                time.sleep(1)
                continue

    if retryable_kind == "overloaded" and last_retryable_error is not None and not raw:
        raise RuntimeError(
            "Gemini URL Context ist momentan überlastet. Die gespeicherte Idealo-Zuordnung bleibt erhalten; bitte später erneut prüfen."
        ) from last_retryable_error
    if retryable_kind == "timeout" and last_retryable_error is not None and not raw:
        raise RuntimeError(
            "Gemini URL Context hat die gespeicherte Idealo-Seite auch beim zweiten Versuch nicht rechtzeitig gelesen."
        ) from last_retryable_error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Gemini URL Context lieferte keine gültige JSON-Antwort.") from exc
    text, citations = _interaction_text_and_citations(payload if isinstance(payload, dict) else {})
    if not text:
        raise RuntimeError("Gemini URL Context lieferte keinen auswertbaren Inhalt.")
    try:
        data = json.loads(text)
    except Exception as exc:
        raise RuntimeError("Gemini URL-Context-Ergebnis konnte nicht als strukturierte Daten gelesen werden.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Gemini URL-Context-Ergebnis hat ein unerwartetes Format.")
    return data, citations


def fetch_idealo_via_gemini_url_context(
    url: str,
    expected_title: str,
    manual: bool = False,
    known_verified: bool = False,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "accessible": {"type": "boolean"},
            "exact_match": {"type": "boolean"},
            "title": {"type": "string"},
            "effective_price_eur": {"type": ["number", "null"]},
            "shop": {"type": "string"},
            "amazon_prime": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["accessible", "exact_match", "title", "effective_price_eur", "shop", "amazon_prime", "reason"],
    }
    prompt = f"""
Öffne ausschließlich diese bereits gespeicherte Idealo-Produktseite über URL Context:
{url}

Erwartetes Produkt: {expected_title}

Aufgabe:
- Prüfe zuerst, ob die Idealo-Seite exakt zu diesem Produkt bzw. genau dieser Variante passt.
- Die URL ist bei einer laufenden Prüfung bereits eine früher bestätigte, unveränderte Produktzuordnung. Setze exact_match daher nur dann auf false, wenn die Seite ausdrücklich ein anderes Produkt oder eine andere Variante nennt. Ein generischer Seitentitel wie „idealo.de“, ein fehlender Titel oder eine unvollständige Darstellung ist kein Gegenbeweis.
- Preisregel:
  1. Wenn das günstigste passende Angebot von Amazon/amazon.de/Amazon Marketplace stammt, zählt der Wert aus der Spalte "Preis" ohne Versand.
  2. Wenn das günstigste passende Angebot von einem anderen Shop stammt, zählt der "Gesamtpreis" inklusive Versand.
  3. Vergleiche also Amazon-Angebote mit Preis-Spalte und Nicht-Amazon-Angebote mit Gesamtpreis-Spalte.
- Bestimme ausschließlich das nach dieser Regel günstigste passende Angebot und gib nur dessen fertigen Wert in effective_price_eur sowie dessen Shop in shop zurück. Keine Angebotsliste und keine zusätzlichen Einzelpreise ausgeben.
- effective_price_eur ist damit bei Amazon der Artikelpreis ohne Versand und bei allen anderen Shops der Gesamtpreis inklusive Versand.
- amazon_prime=true, wenn dieses gewählte Angebot von Amazon stammt.
- Keine Google-Suche verwenden und keine andere Produktseite heranziehen.
- Wenn die Seite nicht zugänglich ist, die Variante nicht exakt passt oder kein verlässlicher Vergleichspreis nach dieser Regel erkennbar ist, accessible/exact_match entsprechend false bzw. effective_price_eur=null setzen.
""".strip()
    data, citations = gemini_url_json(prompt, schema)
    if not bool(data.get("accessible")):
        raise RuntimeError(str(data.get("reason") or "Idealo-Seite konnte über Gemini URL Context nicht gelesen werden."))
    title = " ".join(str(data.get("title") or "").split())[:500]
    score = product_match_score(expected_title, title) if title else 0.0
    normalized_title = re.sub(r"[^a-z0-9]+", "", title.lower())
    # URL Context sometimes exposes only the generic page title "idealo.de".
    # That is missing evidence, not evidence for a different product. A link
    # which was already confirmed and kept unchanged may then still provide a
    # price, but an explicitly different product title must always be rejected.
    title_is_generic = normalized_title in {"", "idealo", "idealode", "preisvergleich", "idealopreisvergleich"}
    explicitly_different = bool(title and not title_is_generic and score < IDEALO_MATCH_THRESHOLD)
    trusted_existing_link = bool(known_verified and not explicitly_different)
    # Even manually entered links must still match the watched item. A wrong
    # saved link is a reason to alert, never a reason to accept a wrong price.
    # The only exception is a previously verified, unchanged direct product
    # link with no contradictory title: URL Context can omit the page title
    # during temporary partial renders, while still returning the actual offer
    # table. We keep the assignment fixed and accept only that price data.
    if not bool(data.get("exact_match")) and not trusted_existing_link:
        return {
            "status": "uncertain", "url": url, "title": title, "match_score": score,
            "price_cents": None, "shop": "", "offer_url": url, "price_kind": "",
        }
    def _price_float(value: Any) -> float | None:
        try:
            result = float(value) if value is not None else None
        except Exception:
            return None
        if result is None or not (0 <= result <= 100000):
            return None
        return result

    shop = " ".join(str(data.get("shop") or "").split())[:120]
    amazon_shop = bool(data.get("amazon_prime")) or _idealo_is_amazon_offer(shop)
    effective_f = _price_float(data.get("effective_price_eur"))

    if effective_f is None or not (0.01 <= effective_f <= 100000):
        raise RuntimeError("Idealo hat über Gemini URL Context keinen eindeutigen Idealo-Vergleichspreis geliefert.")
    prime = amazon_shop
    price_kind = "Amazon-Preis bei Idealo ohne Versand" if amazon_shop else "Gesamtpreis inkl. Versand"
    return {
        "status": "manual" if manual else "matched",
        "url": url,
        "title": title or expected_title,
        "match_score": max(score, 0.95 if (bool(data.get("exact_match")) or trusted_existing_link) else score),
        "price_cents": int(round(effective_f * 100)),
        "shop": shop,
        "offer_url": url,
        "price_kind": price_kind,
        "amazon_prime": prime,
        "retrieval": "Gemini URL Context",
        "citations": citations,
    }


def discover_idealo_with_gemini(expected_title: str, asin: str = "") -> dict[str, Any]:
    query = _idealo_discovery_query(expected_title)
    prompt = f"""
Du hast ein Budget von maximal {IDEALO_DISCOVERY_QUERY_BUDGET} Google-Suchanfragen.
Nutze sie sehr sparsam und führe möglichst nur die erste Suche aus.

Finde ausschließlich die konkrete deutsche Idealo-Produktseite für:
{query}

Vollständiger Amazon-Titel nur zur Verifikation:
{expected_title}

Regeln:
- Suche zuerst möglichst direkt nach: {query} idealo
- Modellnummer, Produktvariante, Größe, Menge und Ausführung müssen exakt passen.
- Akzeptiere ausschließlich eine konkrete Seite unter idealo.de/preisvergleich/OffersOfProduct/.
- Keine Kategorie-, Such- oder Zubehörseite und keine ähnliche Variante.
- Zitiere die konkrete Idealo-Produktseite unbedingt als Quelle.
- Erfinde niemals eine URL. Die App ignoriert jede URL im Antworttext und verwendet ausschließlich aufgelöste Grounding-Citations.
- Wenn nach wenigen Suchversuchen keine eindeutige konkrete Produktseite als Quelle gefunden wird, antworte NOT_FOUND.
""".strip()
    _text, raw_sources = gemini_search_text(
        prompt, timeout=90, purpose="idealo_discovery", thinking_level="low"
    )

    candidates: list[tuple[float, dict[str, str], str]] = []
    seen: set[str] = set()
    for raw_source in raw_sources:
        source = _resolved_source(raw_source)
        url = _direct_idealo_url(source.get("url", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        source["url"] = url
        score = idealo_url_identity_score(expected_title, url, source.get("title", ""))
        # Do not reject a citation only because Idealo's short URL slug omits
        # Amazon marketing terms. URL Context is the authoritative variant check.
        candidates.append((score, source, url))

    if not candidates:
        return {
            "status": "unavailable",
            "error": "Google Search hat keine konkrete Idealo-Produktseite als auflösbare Citation geliefert.",
        }

    candidates.sort(key=lambda item: item[0], reverse=True)
    verification_errors: list[str] = []
    for source_score, source, url in candidates[:5]:
        try:
            verified = fetch_idealo_via_gemini_url_context(url, expected_title, manual=False)
        except Exception as exc:
            verification_errors.append(str(exc))
            continue
        if verified.get("status") != "matched" or verified.get("price_cents") is None:
            verification_errors.append("Produktvariante über URL Context nicht eindeutig bestätigt.")
            continue
        verified["match_score"] = max(float(verified.get("match_score") or 0.0), 0.95)
        verified["retrieval"] = "Gemini Google Search (low) + aufgelöste Grounding-Citation + URL Context"
        verified["source_kind"] = "resolved_citation_verified_by_url_context"
        verified["citations"] = list(dict.fromkeys(
            [source.get("grounding_url") or source.get("url", "")] + list(verified.get("citations") or [])
        ))
        return verified

    detail = (verification_errors[0] if verification_errors else "Keine Variante bestätigt.")[:260]
    best_score, best_source, best_url = candidates[0]
    return {
        "status": "uncertain",
        "url": best_url,
        "title": " ".join(str(best_source.get("title") or "").split())[:500],
        "match_score": float(best_score or 0.0),
        "error": "Idealo-Citation gefunden und zwischengespeichert; URL Context konnte die exakte Produktvariante noch nicht sicher bestätigen: " + detail,
    }

def _mydealz_deal_key_from_url(value: str) -> str:
    match = re.search(r"-(\d{5,})(?:[/?#]|$)", value or "")
    return match.group(1) if match else ""


def _extract_initial_state(raw: str) -> dict[str, Any] | None:
    """Parse MyDealz' embedded ``window.__INITIAL_STATE__`` JSON safely."""
    marker = "window.__INITIAL_STATE__ ="
    pos = (raw or "").find(marker)
    if pos < 0:
        return None
    payload = raw[pos + len(marker):].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(payload)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _mydealz_thread_detail_from_html(raw: str, expected_key: str = "") -> dict[str, Any] | None:
    state = _extract_initial_state(raw)
    if not state:
        return None
    thread = state.get("threadDetail")
    if not isinstance(thread, dict):
        return None
    key = str(thread.get("threadId") or "").strip()
    if expected_key and key and key != str(expected_key):
        return None
    return thread


def _mydealz_fetch_thread_detail(url: str, force: bool = False) -> dict[str, Any] | None:
    """Fetch one exact MyDealz deal page and return its authoritative thread state.

    This deliberately verifies the requested thread itself. A bounded global feed
    must never be used as proof that a deal is inactive merely because it is not
    present in that feed.
    """
    valid = _valid_mydealz_url(url)
    if not valid:
        return None
    now = time.monotonic()
    if not force:
        cached = MYDEALZ_THREAD_CACHE.get(valid)
        if cached and now - cached[0] < MYDEALZ_THREAD_CACHE_SECONDS:
            return dict(cached[1])

    key = _mydealz_deal_key_from_url(valid)
    try:
        body, final_url, _ = fetch_url(valid, timeout=MYDEALZ_TIMEOUT_SECONDS, referer="https://www.mydealz.de/")
        raw = body.decode("utf-8", errors="replace")
        thread = _mydealz_thread_detail_from_html(raw, key)
        if thread is None:
            return None
        canonical = _valid_mydealz_url(str(thread.get("url") or "")) or _valid_mydealz_url(final_url) or valid
        out = dict(thread)
        out["_canonical_url"] = canonical
        with MYDEALZ_THREAD_CACHE_LOCK:
            MYDEALZ_THREAD_CACHE[valid] = (time.monotonic(), dict(out))
            if canonical != valid:
                MYDEALZ_THREAD_CACHE[canonical] = (time.monotonic(), dict(out))
        return out
    except Exception:
        return None


def _mydealz_thread_active(thread: dict[str, Any] | None) -> bool | None:
    if not isinstance(thread, dict):
        return None
    status = str(thread.get("status") or "").strip().lower()
    expired = thread.get("isExpired")
    if isinstance(expired, bool):
        return status == "activated" and expired is False
    return None


def _thread_price_cents(thread: dict[str, Any]) -> int | None:
    value = thread.get("price")
    if value is None:
        return None
    try:
        cents = int(round(float(value) * 100))
    except Exception:
        return None
    return cents if 1 <= cents <= 10_000_000 else None


def _thread_published_iso(thread: dict[str, Any]) -> str:
    value = thread.get("publishedAt")
    if value is None:
        return ""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return ""


def _mydealz_thread_as_deal(thread: dict[str, Any], fallback_url: str = "") -> dict[str, Any]:
    merchant = thread.get("merchant") or {}
    url = _valid_mydealz_url(str(thread.get("_canonical_url") or thread.get("url") or fallback_url))
    key = str(thread.get("threadId") or "").strip() or _mydealz_deal_key_from_url(url)
    return {
        "deal_key": key[:500],
        "title": str(thread.get("title") or "")[:500],
        "url": url[:1500],
        "price_cents": _thread_price_cents(thread),
        "temperature": thread.get("temperature"),
        "merchant": str(merchant.get("merchantName") or "")[:180] if isinstance(merchant, dict) else "",
        "published_at": _thread_published_iso(thread),
        "status": str(thread.get("status") or ""),
        "is_expired": thread.get("isExpired"),
        "active": _mydealz_thread_active(thread) is True,
        "active_verified": _mydealz_thread_active(thread) is not None,
        "retrieval": "MyDealz-Threadstatus",
    }


def _extract_asins_from_urlish(value: str) -> set[str]:
    found: set[str] = set()
    pending = [str(value or "")]
    seen: set[str] = set()
    while pending and len(seen) < 20:
        text = pending.pop(0)
        if not text or text in seen:
            continue
        seen.add(text)
        for decoded in (text, urllib.parse.unquote(text), urllib.parse.unquote(urllib.parse.unquote(text))):
            for asin in re.findall(r"(?i)(?:/dp/|/gp/product/|/gp/aw/d/|/product/)([A-Z0-9]{10})", decoded):
                found.add(asin.upper())
            try:
                parsed = urllib.parse.urlparse(decoded)
                for key in ("url", "u", "target", "destination"):
                    pending.extend(urllib.parse.parse_qs(parsed.query).get(key, []))
            except Exception:
                pass
    return found


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _mydealz_visit_asins(url: str) -> set[str]:
    """Resolve a MyDealz visit link only far enough to recover Amazon ASINs."""
    if not url:
        return set()
    current = url
    opener = urllib.request.build_opener(_NoRedirectHandler())
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
        "Referer": "https://www.mydealz.de/",
        "Connection": "close",
    }
    found: set[str] = set()
    for _ in range(5):
        found.update(_extract_asins_from_urlish(current))
        req = urllib.request.Request(current, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=MYDEALZ_TIMEOUT_SECONDS) as resp:
                final = resp.geturl()
                found.update(_extract_asins_from_urlish(final))
                break
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                break
            location = exc.headers.get("Location") or ""
            if not location:
                break
            current = urllib.parse.urljoin(current, location)
            continue
        except Exception:
            break
    return found


def _amazon_variant_signature(asin: str) -> dict[str, set[str]]:
    asin = str(asin or "").upper().strip()
    empty = {"parents": set(), "variants": set()}
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        return empty
    now = time.monotonic()
    cached = AMAZON_VARIANT_CACHE.get(asin)
    if cached and now - cached[0] < AMAZON_VARIANT_CACHE_SECONDS:
        return {"parents": set(cached[1]["parents"]), "variants": set(cached[1]["variants"])}
    try:
        body, _, _ = fetch_url(f"https://www.amazon.de/dp/{asin}?th=1&psc=1", timeout=PRODUCT_TIMEOUT_SECONDS)
        raw = body.decode("utf-8", errors="replace")
    except Exception:
        return empty

    parents: set[str] = set()
    for pattern in (
        r'"parentAsin"\s*:\s*"([A-Z0-9]{10})"',
        r'"parentASIN"\s*:\s*"([A-Z0-9]{10})"',
        r'"parent_asin"\s*:\s*"([A-Z0-9]{10})"',
        r'data-csa-c-parent-asin=["\']([A-Z0-9]{10})["\']',
    ):
        parents.update(x.upper() for x in re.findall(pattern, raw, re.I))

    variants: set[str] = {asin}
    # Only inspect windows around Amazon variation/twister structures. Requiring
    # reciprocal linkage later prevents unrelated recommendation ASINs from
    # becoming product-family evidence.
    lower = raw.lower()
    markers = ("twister", "variationvalues", "dimensionvaluesdisplaydata", "asinvariationvalues", "variationdisplaylabels")
    for marker in markers:
        pos = 0
        hits = 0
        while hits < 40:
            idx = lower.find(marker, pos)
            if idx < 0:
                break
            chunk = raw[max(0, idx - 5000): min(len(raw), idx + 25000)]
            variants.update(x.upper() for x in re.findall(r'\bB[A-Z0-9]{9}\b', chunk, re.I))
            pos = idx + len(marker)
            hits += 1
            if len(variants) > 500:
                break
        if len(variants) > 500:
            break

    result = {"parents": parents, "variants": variants}
    with AMAZON_VARIANT_CACHE_LOCK:
        AMAZON_VARIANT_CACHE[asin] = (time.monotonic(), {"parents": set(parents), "variants": set(variants)})
    return result


def _amazon_same_variant_family(expected_asin: str, candidate_asin: str) -> bool:
    a = str(expected_asin or "").upper().strip()
    b = str(candidate_asin or "").upper().strip()
    if not a or not b:
        return False
    if a == b:
        return True
    sig_a = _amazon_variant_signature(a)
    sig_b = _amazon_variant_signature(b)
    if sig_a["parents"] and sig_b["parents"] and sig_a["parents"].intersection(sig_b["parents"]):
        return True
    return b in sig_a["variants"] and a in sig_b["variants"]


def _mydealz_text_identity_confident(expected: str, candidate: str, score: float) -> bool:
    if score < MYDEALZ_MATCH_THRESHOLD:
        return False
    if score >= 0.60:
        return True
    noise = {"amazon", "prime", "deal", "angebot", "preis", "eur", "euro", "aktuell", "versand", "inkl"}
    exp = {t for t in significant_tokens(expected) if t not in noise}
    cand = {t for t in significant_tokens(candidate) if t not in noise}
    if not cand:
        return False
    overlap = exp.intersection(cand)
    coverage = len(overlap) / len(cand)
    return len(overlap) >= 2 and coverage >= 0.50


def _mydealz_verify_thread_product(thread: dict[str, Any], expected_title: str, asin: str = "") -> dict[str, Any] | None:
    active = _mydealz_thread_active(thread)
    if active is not True:
        return None
    deal = _mydealz_thread_as_deal(thread)
    title = str(deal.get("title") or "")
    score = mydealz_identity_score(expected_title, title)
    merchant = str(deal.get("merchant") or "").lower()
    link_host = str(thread.get("linkHost") or "").lower()
    amazon_deal = "amazon" in merchant or "amazon." in link_host

    expected_asin = str(asin or "").upper().strip()
    if expected_asin and amazon_deal:
        main_visit = str(thread.get("linkCloakedItemMainButton") or "").strip()
        if not main_visit and deal.get("deal_key"):
            main_visit = f"https://www.mydealz.de/visit/threadmain/{deal['deal_key']}"
        deal_asins = _mydealz_visit_asins(main_visit)
        if expected_asin in deal_asins:
            score = max(score, 0.99)
        elif deal_asins:
            same_family = any(_amazon_same_variant_family(expected_asin, other) for other in deal_asins)
            if not same_family:
                return None
            if _mydealz_hard_variant_conflict(expected_title, title):
                return None
            score = max(score, 0.92)
        else:
            if _mydealz_hard_variant_conflict(expected_title, title):
                return None
            if not _mydealz_text_identity_confident(expected_title, title, score):
                return None
    else:
        if _mydealz_hard_variant_conflict(expected_title, title):
            return None
        if not _mydealz_text_identity_confident(expected_title, title, score):
            return None

    deal["match_score"] = score
    deal["active"] = True
    deal["active_verified"] = True
    deal["retrieval"] = "MyDealz-Threadstatus + Produktprüfung"
    return deal


def _mydealz_graphql_verify_candidate(deal: dict[str, Any], expected_title: str = "", asin: str = "") -> dict[str, Any] | None:
    """Compatibility wrapper: verify the exact thread, never a bounded snapshot."""
    url = _valid_mydealz_url(str(deal.get("url") or ""))
    if not url:
        return None
    thread = _mydealz_fetch_thread_detail(url)
    if thread is None:
        return None
    if expected_title:
        return _mydealz_verify_thread_product(thread, expected_title, asin=asin)
    if _mydealz_thread_active(thread) is not True:
        return None
    out = _mydealz_thread_as_deal(thread, url)
    out["match_score"] = float(deal.get("match_score") or 0.0)
    return out


def _valid_mydealz_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    if not (host == "mydealz.de" or host.endswith(".mydealz.de")):
        return ""
    if "/deals/" not in parsed.path:
        return ""
    return urllib.parse.urlunparse(("https", parsed.netloc, parsed.path, "", "", ""))


def _mydealz_slug_title(url: str) -> str:
    """Turn a MyDealz deal slug into useful identity text for discovery only."""
    try:
        path = urllib.parse.urlparse(url or "").path.rstrip("/")
    except Exception:
        return ""
    slug = urllib.parse.unquote(path.rsplit("/", 1)[-1]) if path else ""
    slug = re.sub(r"-\d{5,}$", "", slug)
    slug = re.sub(r"[-_]+", " ", slug)
    return " ".join(slug.split())[:500]


def _mydealz_search_variants(expected_title: str, query: str) -> list[str]:
    """Compact grounded-search variants ordered from precise to broad."""
    tokens = [t for t in build_mydealz_query(expected_title).split() if t]
    models = sorted(_mydealz_model_anchors(expected_title))
    brand = _mydealz_brand_anchor(expected_title)
    variants = sorted(_mydealz_variant_anchors(expected_title))
    non_brand = [t for t in tokens if t != brand]
    searches: list[str] = []

    def add(v: str) -> None:
        v = " ".join(v.split()).strip()
        if v and v not in searches:
            searches.append(v)

    if models:
        add(f'site:mydealz.de/deals {brand} {models[0]}')
    if variants and brand:
        add(f'site:mydealz.de/deals {brand} {" ".join(variants)}')
    if brand and len(non_brand) >= 2:
        add(f'site:mydealz.de/deals {brand} {" ".join(non_brand[:2])}')
    if len(non_brand) >= 3:
        add(f'site:mydealz.de/deals {" ".join(non_brand[:3])}')
    if brand and len(non_brand) >= 3:
        add(f'site:mydealz.de/deals {brand} {" ".join(non_brand[:3])}')
    if query:
        add(f'site:mydealz.de/deals {query}')
    add(f'site:mydealz.de/deals {_short_market_query(expected_title)}')
    return searches[:6]


def _mydealz_price_from_url_slug(url: str) -> int | None:
    """Read common MyDealz slug prices such as ``fur-2292eur`` as 22.92 EUR."""
    try:
        slug = urllib.parse.unquote(urllib.parse.urlparse(url or "").path.rsplit("/", 1)[-1]).lower()
    except Exception:
        return None
    # MyDealz commonly writes 12,99 EUR as 1299eur in deal slugs. Require at
    # least three digits so unrelated one-/two-digit product numbers are ignored.
    m = re.search(r"(?:^|[-_])(?:fur|fuer|für)[-_]?(\d{3,7})[-_]?eur(?:[-_]|$)", slug)
    if not m:
        return None
    cents = int(m.group(1))
    return cents if 1 <= cents <= 10_000_000 else None


def _grounded_mydealz_candidate(
    source: dict[str, str], resolved_url: str, expected_title: str, query: str, asin: str = ""
) -> dict[str, Any] | None:
    """Build a conservative fallback from a real Google-grounded MyDealz citation.

    Direct MyDealz detail pages can return 403 to automated clients. In that case
    rejecting a genuine Google-grounded citation caused false negatives (notably
    Brennenstuhl Super-Solid). We only trust source-owned fields here: the resolved
    MyDealz URL, its slug and the citation title. Model prose/cited_text never proves
    product identity. Brand/model/variant hard constraints still live in
    ``mydealz_identity_score``.
    """
    url = _valid_mydealz_url(resolved_url)
    if not url:
        return None
    source_title = " ".join(str(source.get("title") or "").split())[:500]
    source_title = re.sub(r"\s*[|\-–]\s*mydealz.*$", "", source_title, flags=re.I).strip()
    slug_title = _mydealz_slug_title(url)
    title_score = mydealz_identity_score(expected_title, source_title) if source_title else 0.0
    slug_score = mydealz_identity_score(expected_title, slug_title) if slug_title else 0.0
    score = max(title_score, slug_score)
    if score < MYDEALZ_DISCOVERY_FALLBACK_THRESHOLD:
        return None
    title = source_title if title_score >= slug_score and source_title else slug_title
    price = parse_deal_price_to_cents(source_title) or _mydealz_price_from_url_slug(url)
    key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
    deal_key = key_match.group(1) if key_match else url
    return {
        "deal_key": deal_key[:500], "title": title[:500], "url": url[:1500],
        "price_cents": price, "temperature": None, "merchant": "",
        "published_at": "", "match_score": score, "active": True,
        "active_verified": False,
        "retrieval": "Gemini Google Search: aufgelöste MyDealz-Citation",
    }


def _parse_mydealz_reader_deal(raw: str, url: str, expected_title: str, query: str, asin: str = "") -> dict[str, Any] | None:
    """Verify a deal from Jina Reader markdown when MyDealz blocks direct HTML."""
    if not raw or mydealz_page_is_expired(raw):
        return None
    title = ""
    for pattern in (r"(?im)^Title:\s*(.+)$", r"(?im)^#\s+(.+)$"):
        m = re.search(pattern, raw)
        if m:
            title = " ".join(html.unescape(m.group(1)).split())[:500]
            title = re.sub(r"\s*[|\-–]\s*mydealz.*$", "", title, flags=re.I).strip()
            if title:
                break
    slug_title = _mydealz_slug_title(url)
    if not title:
        title = slug_title
    title_score = mydealz_identity_score(expected_title, title)
    slug_score = mydealz_identity_score(expected_title, slug_title)
    score = max(title_score, slug_score)
    if title_score < MYDEALZ_MATCH_THRESHOLD <= slug_score:
        title = slug_title
    if asin and asin.lower() in raw.lower():
        score = max(score, 0.98)
    if score < MYDEALZ_MATCH_THRESHOLD:
        return None
    price = parse_deal_price_to_cents(title) or parse_deal_price_to_cents(raw)
    temp = None
    tm = re.search(r"(-?\d{1,4})\s*°", raw)
    if tm:
        try:
            temp = int(tm.group(1))
        except ValueError:
            pass
    key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
    deal_key = key_match.group(1) if key_match else url
    return {
        "deal_key": deal_key[:500], "title": title[:500], "url": url[:1500],
        "price_cents": price, "temperature": temp, "merchant": "",
        "published_at": "", "match_score": score, "active": True,
        "active_verified": False,
        "retrieval": "Reader-Detailseite",
    }


def _fetch_verified_mydealz_deal(url: str, expected_title: str, query: str, asin: str = "", referer: str = "https://www.mydealz.de/") -> dict[str, Any] | None:
    """Verify one exact MyDealz thread by its embedded live state.

    Discovery may come from RSS, MyDealz search, Reader or Gemini, but no deal is
    allowed to become active until this exact thread reports ``isExpired=false``.
    For Amazon deals the main click-out ASIN is additionally checked against the
    watched ASIN (exactly or via Amazon's variant family).
    """
    valid = _valid_mydealz_url(url)
    if not valid:
        return None
    thread = _mydealz_fetch_thread_detail(valid)
    if thread is None:
        return None
    return _mydealz_verify_thread_product(thread, expected_title, asin=asin)


def fetch_mydealz_gemini_deals(expected_title: str, query: str, asin: str = "") -> list[dict[str, Any]]:
    """Grounded MyDealz safety search with a strict two-query budget.

    Use Google grounding only for discovery. Every discovered citation must still
    pass the explicit MyDealz status/isExpired gate before it can become active.
    """
    variants = _mydealz_search_variants(expected_title, query)
    first = variants[0] if variants else f"site:mydealz.de/deals {_short_market_query(expected_title)}"
    second = next((v for v in variants[1:] if v != first), "")
    second_search_instruction = (
        "Nur falls damit kein passender MyDealz-Deal gefunden wird, nutze als zweite und letzte Suche:\n" + second
        if second else ""
    )
    prompt = f"""
Du hast ein hartes Budget von maximal {MYDEALZ_SAFETY_QUERY_BUDGET} Google-Suchanfragen.
Nutze zuerst genau diese Suche:
{first}
{second_search_instruction}

Finde MyDealz-Deals für genau dieses Produkt:
{expected_title}

Regeln:
- Suche ausschließlich nach Seiten unter mydealz.de/deals.
- Stoppe nach dem ersten eindeutig passenden Treffer; niemals mehr als {MYDEALZ_SAFETY_QUERY_BUDGET} Suchanfragen.
- Marke, Modell, Größe, Anzahl und benannte Variante müssen passen.
- Bevorzuge aktive/aktuelle Deals.
- Zitiere die konkrete MyDealz-Deal-Seite als Quelle.
- Erfinde keine URL.
""".strip()
    text, sources = gemini_search_text(prompt, timeout=45, purpose="mydealz_safety", thinking_level="low")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Grounding citations are the authoritative discovery source. Their redirect
    # target and citation title belong to the indexed source, unlike model prose.
    for source in sources:
        original = str(source.get("url") or "").strip()
        resolved = resolve_grounding_citation_url(original)
        url = _valid_mydealz_url(resolved)
        if not url or url in seen:
            continue
        seen.add(url)
        verified = _fetch_verified_mydealz_deal(url, expected_title, query, asin=asin)
        if verified is not None:
            verified["retrieval"] = "Gemini Google Search + MyDealz-Thread verifiziert"
            out.append(verified)
            continue
        grounded = _grounded_mydealz_candidate(source, url, expected_title, query, asin=asin)
        if grounded is not None:
            confirmed = _mydealz_graphql_verify_candidate(grounded, expected_title, asin=asin)
            if confirmed is not None:
                out.append(confirmed)

    # A direct URL written only in model text is never accepted on its own. It
    # may still be used if the real MyDealz thread can be fetched and verified.
    for raw_url in _direct_urls_from_text(text):
        url = _valid_mydealz_url(raw_url)
        if not url or url in seen:
            continue
        seen.add(url)
        verified = _fetch_verified_mydealz_deal(url, expected_title, query, asin=asin)
        if verified is not None:
            verified["retrieval"] = "Gemini-Antwort-URL + MyDealz-Thread verifiziert"
            out.append(verified)

    # Keep only the strongest entry for each deal id.
    best: dict[str, dict[str, Any]] = {}
    for deal in out:
        key = str(deal.get("deal_key") or deal.get("url") or "")
        old = best.get(key)
        if old is None or float(deal.get("match_score") or 0) > float(old.get("match_score") or 0):
            best[key] = deal
    return list(best.values())


def extract_idealo_result_urls(raw: str) -> list[tuple[str, str]]:
    '''Extract Idealo product URLs from Idealo, DuckDuckGo or Reader results.'''
    found: dict[str, str] = {}
    for m in re.finditer(r'''(?is)<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>''', raw):
        href = html.unescape(m.group(1)).strip()
        label = html_to_text(m.group(2))[:500]
        if "duckduckgo.com/l/" in href:
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = urllib.parse.unquote((q.get("uddg") or [href])[0])
            except Exception:
                pass
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            href = urllib.parse.urljoin("https://www.idealo.de", href)
        if "idealo.de/preisvergleich/OffersOfProduct/" in href:
            href = href.split("#", 1)[0]
            found[href] = label or found.get(href, "")

    for m in re.finditer(r'''https?://(?:www\.)?idealo\.de/preisvergleich/OffersOfProduct/[^\s)\]"'<>]+''', raw, re.I):
        href = html.unescape(m.group(0)).rstrip(".,;:")
        found.setdefault(href, "")
    return list(found.items())


def find_idealo_product(expected_title: str, asin: str = "") -> dict[str, Any]:
    expected_title = " ".join((expected_title or "").split())
    if not expected_title or expected_title.lower().startswith("amazon-artikel "):
        return {"status": "unavailable", "error": "Für die Idealo-Zuordnung fehlt noch ein eindeutiger Produktname."}
    if not gemini_configured():
        return {"status": "unavailable", "error": "Idealo-Zuordnung wartet auf den Gemini API-Key unter App → Konfiguration."}
    return discover_idealo_with_gemini(expected_title, asin=asin)


def validate_idealo_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    if not (host == "idealo.de" or host.endswith(".idealo.de")):
        raise ValueError("Bitte eine idealo.de-Produkt-URL verwenden.")
    if "/preisvergleich/OffersOfProduct/" not in parsed.path:
        raise ValueError("Bitte die konkrete Idealo-Produktseite verwenden.")
    return value


def build_mydealz_query(title: str) -> str:
    norm = normalize_match_text(title)
    stop = {
        "amazon", "de", "fur", "mit", "und", "oder", "geeignet", "original", "produkt",
        "angebot", "neu", "inkl", "versand", "deutschland", "von", "der", "die", "das",
        "aus", "in", "im", "am", "an", "bei", "zum", "zur", "einer", "einem", "einen",
    }
    parts: list[str] = []
    for token in norm.split():
        if token in stop or len(token) < 2:
            continue
        if token not in parts:
            parts.append(token)
        if len(parts) >= 7:
            break
    return " ".join(parts)[:160]


def parse_deal_price_to_cents(text: str) -> int | None:
    if not text:
        return None
    match = DEAL_PRICE_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    if 0.01 <= value <= 100000:
        return int(round(value * 100))
    return None


def _xml_child_text(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        local = child.tag.rsplit("}", 1)[-1].lower()
        if local in names:
            if local == "link" and child.attrib.get("href"):
                return child.attrib.get("href", "").strip()
            return "".join(child.itertext()).strip()
    return ""


def _xml_first_element(node: ET.Element, local_name: str) -> ET.Element | None:
    for child in node.iter():
        if child.tag.rsplit("}", 1)[-1].lower() == local_name.lower():
            return child
    return None


def parse_mydealz_feed(raw: bytes, expected_title: str, query: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError("MyDealz-RSS konnte nicht gelesen werden.") from exc

    nodes = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    deals: list[dict[str, Any]] = []
    for node in nodes:
        title = _xml_child_text(node, {"title"})
        url = _xml_child_text(node, {"link"})
        description = _xml_child_text(node, {"description", "summary", "content", "encoded"})
        published_raw = _xml_child_text(node, {"pubdate", "published", "updated", "date"})
        if not title or not url:
            continue

        score = mydealz_identity_score(expected_title, title)
        if score < MYDEALZ_MATCH_THRESHOLD:
            continue

        plain_description = html_to_text(description)
        merchant = ""
        merchant_node = _xml_first_element(node, "merchant")
        merchant_price = None
        if merchant_node is not None:
            merchant = (merchant_node.attrib.get("name") or "").strip()[:180]
            merchant_price = parse_deal_price_to_cents(merchant_node.attrib.get("price") or "")
        price = merchant_price if merchant_price is not None else parse_deal_price_to_cents(title)
        if price is None:
            price = parse_deal_price_to_cents(plain_description)

        temp = None
        tm = re.search(r"(-?\d{1,4})\s*°", title + " " + plain_description)
        if tm:
            try:
                temp = int(tm.group(1))
            except ValueError:
                temp = None

        published = ""
        if published_raw:
            try:
                dt = parsedate_to_datetime(published_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                published = dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            except Exception:
                try:
                    dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    published = dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
                except Exception:
                    published = ""

        key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
        deal_key = key_match.group(1) if key_match else url.split("#", 1)[0]
        deals.append({
            "deal_key": deal_key[:500],
            "title": title[:500],
            "url": url[:1500],
            "price_cents": price,
            "temperature": temp,
            "merchant": merchant,
            "published_at": published,
            "match_score": score,
            "active": True,
            "active_verified": False,
            "retrieval": "MyDealz-RSS",
        })

    deals.sort(key=lambda d: (d.get("published_at") or "", d.get("temperature") if d.get("temperature") is not None else -9999), reverse=True)
    return deals[:10]


def _mydealz_raw_deal_urls(raw: str) -> list[tuple[str, str]]:
    """Return deal URLs found anywhere in search HTML, including embedded JSON.

    MyDealz sometimes includes a fresh result in card/JSON markup without the
    anchor shape used by the normal parser. Discovery is therefore intentionally
    broad; the exact thread is still verified afterwards before activation.
    """
    normalized = html.unescape(raw or "").replace("\\/", "/")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r'(?:https://(?:www\.)?mydealz\.de)?(/deals/[A-Za-z0-9%._~+\-]+-\d{5,})', re.I)
    for m in pattern.finditer(normalized):
        url = urllib.parse.urljoin("https://www.mydealz.de", m.group(1))
        url = _valid_mydealz_url(url)
        if not url or url in seen:
            continue
        seen.add(url)
        context = normalized[max(0, m.start() - 1200): min(len(normalized), m.end() + 2600)]
        out.append((url, context))
    return out


def parse_mydealz_search_page(raw: str, expected_title: str, query: str, asin: str = "") -> list[dict[str, Any]]:
    """Parse public MyDealz search results for discovery only.

    The parser accepts both normal anchors and deal URLs embedded elsewhere in
    the page. Every returned candidate still has to pass exact thread status and
    product verification before it may become active.
    """
    results: dict[str, dict[str, Any]] = {}
    anchor_pattern = re.compile(r"(?is)<a\b[^>]*href=[\"']([^\"']*/deals/[^\"']+)[\"'][^>]*>(.*?)</a>")
    for m in anchor_pattern.finditer(raw):
        href = html.unescape(m.group(1)).strip()
        if href.startswith("/"):
            href = urllib.parse.urljoin("https://www.mydealz.de", href)
        href = _valid_mydealz_url(href)
        if not href:
            continue
        title = html_to_text(m.group(2))[:500]
        if len(title) < 4:
            title = _mydealz_slug_title(href)
        window = raw[m.start(): min(len(raw), m.end() + 3200)]
        plain = html_to_text(window)
        slug_title = _mydealz_slug_title(href)
        score = max(
            mydealz_identity_score(expected_title, title),
            mydealz_identity_score(expected_title, slug_title),
        )
        if score < MYDEALZ_MATCH_THRESHOLD:
            continue
        price = parse_deal_price_to_cents(title) or parse_deal_price_to_cents(plain)
        temp = None
        tm = re.search(r"(-?\d{1,4})\s*°", plain)
        if tm:
            try:
                temp = int(tm.group(1))
            except ValueError:
                pass
        merchant = ""
        mm = re.search(r"(?i)(?:Händler|Shop|bei)\s*[:\-]?\s*([A-Za-z0-9ÄÖÜäöüß&. _-]{2,80})", plain)
        if mm:
            merchant = " ".join(mm.group(1).split())[:120]
        deal_key = _mydealz_deal_key_from_url(href) or href
        item = {
            "deal_key": deal_key[:500], "title": title[:500], "url": href[:1500],
            "price_cents": price, "temperature": temp, "merchant": merchant,
            "published_at": "", "match_score": score,
            "active_verified": False, "expired_hint": mydealz_page_is_expired(window),
        }
        current = results.get(deal_key)
        if current is None or score > float(current.get("match_score") or 0):
            results[deal_key] = item

    # Fresh deals can be present only in embedded card/JSON markup. Add those
    # URLs using the slug as identity text; live thread verification follows.
    for href, context in _mydealz_raw_deal_urls(raw):
        deal_key = _mydealz_deal_key_from_url(href) or href
        if deal_key in results:
            continue
        slug_title = _mydealz_slug_title(href)
        score = mydealz_identity_score(expected_title, slug_title)
        query_tokens = significant_tokens(query)
        slug_tokens = significant_tokens(slug_title)
        query_match = bool(query_tokens and query_tokens.issubset(slug_tokens))
        if score < MYDEALZ_MATCH_THRESHOLD and not query_match:
            continue
        if query_match:
            score = max(score, 0.35)
        plain = html_to_text(context)
        price = parse_deal_price_to_cents(slug_title) or parse_deal_price_to_cents(plain) or _mydealz_price_from_url_slug(href)
        temp = None
        tm = re.search(r"(-?\d{1,4})\s*°", plain)
        if tm:
            try:
                temp = int(tm.group(1))
            except ValueError:
                pass
        results[deal_key] = {
            "deal_key": deal_key[:500], "title": slug_title[:500], "url": href[:1500],
            "price_cents": price, "temperature": temp, "merchant": "",
            "published_at": "", "match_score": score,
            "active_verified": False, "expired_hint": mydealz_page_is_expired(context),
        }
    return list(results.values())


def parse_mydealz_deal_page(raw: str, url: str, expected_title: str, query: str, asin: str = "") -> dict[str, Any] | None:
    title = extract_page_h1(raw)
    if not title:
        return None
    text = html_to_text(raw)
    score = mydealz_identity_score(expected_title, title)
    if asin and asin.lower() in raw.lower():
        score = max(score, 0.98)
    if score < MYDEALZ_MATCH_THRESHOLD:
        return None
    price = parse_deal_price_to_cents(title)
    if price is None:
        for pattern in (
            r"(?is)(?:Dealpreis|Preis)\s*[:\-]?\s*(\d{1,5}(?:[.,]\d{1,2})?)\s*€",
            r"(?is)(\d{1,5}(?:[.,]\d{1,2})?)\s*€",
        ):
            pm = re.search(pattern, text)
            if pm:
                price = parse_deal_price_to_cents(pm.group(1) + " €")
                if price is not None:
                    break
    temp = None
    tm = re.search(r"(-?\d{1,4})\s*°", text)
    if tm:
        try:
            temp = int(tm.group(1))
        except ValueError:
            pass
    merchant = ""
    for pattern in (
        r"(?is)Händler\s*[:\-]?\s*([^|\n]{2,100})",
        r"(?is)bei\s+([A-Za-z0-9ÄÖÜäöüß&. _-]{2,80})(?:\s|$)",
    ):
        mm = re.search(pattern, text)
        if mm:
            merchant = " ".join(mm.group(1).split())[:120]
            break
    key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
    deal_key = key_match.group(1) if key_match else url
    return {
        "deal_key": deal_key[:500], "title": title[:500], "url": url[:1500],
        "price_cents": price, "temperature": temp, "merchant": merchant,
        "published_at": "", "match_score": score,
    }


def parse_mydealz_reader_search(raw: str, expected_title: str, query: str, asin: str = "") -> list[dict[str, Any]]:
    '''Parse Reader markdown links from a MyDealz search page.'''
    results: dict[str, dict[str, Any]] = {}
    for m in re.finditer(r'''\[([^\]]{4,500})\]\((https?://(?:www\.)?mydealz\.de/deals/[^)\s]+)\)''', raw, re.I):
        title = " ".join(html.unescape(m.group(1)).split())[:500]
        url = html.unescape(m.group(2)).split("?", 1)[0].split("#", 1)[0]
        score = max(
            mydealz_identity_score(expected_title, title),
            mydealz_identity_score(expected_title, _mydealz_slug_title(url)),
        )
        if asin and asin.lower() in raw[max(0, m.start()-500):m.end()+2500].lower():
            score = max(score, 0.98)
        if score < MYDEALZ_MATCH_THRESHOLD:
            continue
        context = raw[max(0, m.start()-1000):m.end()+2500]
        price = parse_deal_price_to_cents(title) or parse_deal_price_to_cents(context)
        temp = None
        tm = re.search(r"(-?\d{1,4})\s*°", context)
        if tm:
            try:
                temp = int(tm.group(1))
            except ValueError:
                pass
        key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
        deal_key = key_match.group(1) if key_match else url
        results[deal_key] = {
            "deal_key": deal_key[:500], "title": title, "url": url[:1500],
            "price_cents": price, "temperature": temp, "merchant": "",
            "published_at": "", "match_score": score,
            "active_verified": False, "expired_hint": mydealz_page_is_expired(context),
        }
    return list(results.values())


def _mydealz_public_queries(expected_title: str, configured_query: str = "") -> list[str]:
    """Short staged queries; product identity is validated only after discovery."""
    tokens = [t for t in build_mydealz_query(expected_title).split() if t]
    models = sorted(_mydealz_model_anchors(expected_title))
    variants = sorted(_mydealz_variant_anchors(expected_title))
    brand = _mydealz_brand_anchor(expected_title)
    non_brand = [t for t in tokens if t != brand]
    queries: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split()).strip()
        if value and value not in queries:
            queries.append(value)

    # Precise brand/model or brand/variant combinations first.
    if models:
        add(" ".join(([brand] if brand else []) + models[:1]))
        add(models[0])
    if variants:
        add(" ".join(([brand] if brand else []) + variants))

    # Product-family combinations handle titles such as Brennenstuhl Super-Solid
    # while remaining short enough for MyDealz's own search.
    if brand and len(non_brand) >= 2:
        add(" ".join([brand] + non_brand[:2]))
    if len(non_brand) >= 2:
        add(" ".join(non_brand[:2]))
    if len(non_brand) >= 3:
        add(" ".join(non_brand[:3]))
    if brand and len(non_brand) >= 3:
        add(" ".join([brand] + non_brand[:3]))

    # Add one category-oriented brand query when a clear noun occurs later in
    # the Amazon title (e.g. Brennenstuhl + Steckdosenleiste).
    descriptor_noise = {
        "super", "solid", "isolierte", "kinder", "deutsche", "ausgabe", "material",
        "farbe", "schwarz", "weiss", "weiß", "natur", "set", "pack", "prime",
    }
    category = next((t for t in non_brand if t not in descriptor_noise and not re.fullmatch(r"\d+(?:[.,]\d+)?", t)), "")
    if brand and category:
        add(f"{brand} {category}")

    add(configured_query)
    add(_short_market_query(expected_title))
    return queries[:8]


def mydealz_page_is_expired(raw: str) -> bool:
    lower = (raw or "").lower()
    signals = (
        '"isexpired":true', '"expired":true', 'thread--expired', 'deal--expired',
        'deal ist abgelaufen', 'dieser deal ist abgelaufen', 'angebot ist abgelaufen',
        'deal wurde beendet', 'dieser deal wurde beendet', '>abgelaufen<',
    )
    return any(sig in lower for sig in signals)


def fetch_mydealz_search_deals(expected_title: str, query: str, asin: str = "") -> list[dict[str, Any]]:
    """Discover candidates across all staged MyDealz searches, then verify them.

    Do not stop after the first query: a newer/better deal can appear only in a
    broader later search (as proven with the Deuter test case).
    """
    last_error: Exception | None = None
    discovered: dict[str, dict[str, Any]] = {}

    for public_query in _mydealz_public_queries(expected_title, query):
        search_url = MYDEALZ_SEARCH_URL + urllib.parse.quote_plus(public_query)
        candidates: list[dict[str, Any]] = []
        try:
            body, _, _ = fetch_url(search_url, timeout=MYDEALZ_TIMEOUT_SECONDS, referer="https://www.mydealz.de/")
            raw = body.decode("utf-8", errors="replace")
            candidates = parse_mydealz_search_page(raw, expected_title, public_query, asin=asin)
        except Exception as exc:
            last_error = exc

        if not candidates:
            try:
                reader_url = JINA_READER_PREFIX + search_url
                body, _, _ = fetch_url(reader_url, timeout=MYDEALZ_TIMEOUT_SECONDS, referer="https://r.jina.ai/")
                candidates = parse_mydealz_reader_search(
                    body.decode("utf-8", errors="replace"), expected_title, public_query, asin=asin
                )
            except Exception as exc:
                if last_error is None:
                    last_error = exc

        for candidate in candidates:
            key = str(candidate.get("deal_key") or _mydealz_deal_key_from_url(str(candidate.get("url") or "")))
            if not key:
                continue
            item = dict(candidate)
            item["_referer"] = search_url
            old = discovered.get(key)
            if old is None or float(item.get("match_score") or 0) > float(old.get("match_score") or 0):
                discovered[key] = item
            elif old.get("price_cents") is None and item.get("price_cents") is not None:
                old.update({k: v for k, v in item.items() if v not in (None, "")})

    if not discovered:
        if last_error is not None:
            raise last_error
        return []

    candidates = sorted(
        discovered.values(),
        key=lambda d: (float(d.get("match_score") or 0), 0 if d.get("expired_hint") else 1),
        reverse=True,
    )
    verified: list[dict[str, Any]] = []
    for candidate in candidates[:24]:
        if candidate.get("expired_hint"):
            continue
        url = _valid_mydealz_url(str(candidate.get("url") or ""))
        if not url:
            continue
        enriched = _fetch_verified_mydealz_deal(
            url, expected_title, query, asin=asin, referer=str(candidate.get("_referer") or "https://www.mydealz.de/")
        )
        if enriched is None:
            continue
        if float(enriched.get("match_score") or 0) < MYDEALZ_MATCH_THRESHOLD:
            continue
        verified.append(enriched)

    verified.sort(
        key=lambda d: (
            float(d.get("match_score") or 0),
            d.get("published_at") or "",
            -(int(d["price_cents"]) if d.get("price_cents") is not None else 10_000_000),
        ),
        reverse=True,
    )
    return verified[:12]


def fetch_mydealz_deals(
    expected_title: str,
    query: str | None = None,
    asin: str = "",
    include_search: bool = False,
    include_gemini: bool = False,
) -> dict[str, Any]:
    search_query = (query or build_mydealz_query(expected_title)).strip()
    if not search_query:
        return {"deals": [], "query": "", "search_url": "https://www.mydealz.de/", "status": "empty",
                "direct_search_used": False, "gemini_search_used": False}

    combined: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    successful_feeds = 0
    for feed_url in MYDEALZ_FEED_URLS:
        try:
            body, _, _ = fetch_url(feed_url, timeout=MYDEALZ_TIMEOUT_SECONDS, referer="https://www.mydealz.de/")
            successful_feeds += 1
            for deal in parse_mydealz_feed(body, expected_title, search_query):
                confirmed = _mydealz_graphql_verify_candidate(deal, expected_title, asin=asin)
                if confirmed is None:
                    continue
                key = confirmed["deal_key"]
                old = combined.get(key)
                if old is None or float(confirmed.get("match_score") or 0) > float(old.get("match_score") or 0):
                    combined[key] = confirmed
                elif old.get("price_cents") is None and confirmed.get("price_cents") is not None:
                    old.update(confirmed)
        except Exception as exc:
            errors.append(f"RSS {feed_url.rsplit('/', 1)[-1] or 'main'}: {exc}")

    # After adding a product and then hourly we query MyDealz's own public search.
    # This path is confirmed on the user's HA host and does not consume Gemini.
    direct_search_used = False
    if include_search:
        direct_search_used = True
        try:
            for deal in fetch_mydealz_search_deals(expected_title, search_query, asin=asin):
                key = deal["deal_key"]
                old = combined.get(key)
                if old is None or float(deal.get("match_score") or 0) > float(old.get("match_score") or 0):
                    combined[key] = deal
                elif old.get("price_cents") is None and deal.get("price_cents") is not None:
                    old.update(deal)
        except Exception as exc:
            errors.append(f"MyDealz-Suche: {exc}")

    # Gemini is used only for the one-time safety search immediately after adding
    # an Amazon product. Normal RSS, public-search, manual refresh and scheduler
    # operation never invoke Gemini. Every URL must
    # still pass MyDealz's explicit activity status gate.
    gemini_search_used = False
    if include_gemini and gemini_configured():
        gemini_search_used = True
        try:
            for deal in fetch_mydealz_gemini_deals(expected_title, search_query, asin=asin):
                key = deal["deal_key"]
                old = combined.get(key)
                if old is None or float(deal.get("match_score") or 0) > float(old.get("match_score") or 0):
                    combined[key] = deal
                elif old.get("price_cents") is None and deal.get("price_cents") is not None:
                    old.update(deal)
        except Exception as exc:
            errors.append(f"Gemini-Sicherheitsprüfung: {exc}")

    deals = list(combined.values())
    deals.sort(
        key=lambda d: (
            float(d.get("match_score") or 0),
            d.get("published_at") or "",
            d.get("temperature") if d.get("temperature") is not None else -9999,
        ),
        reverse=True,
    )
    if not deals and successful_feeds == 0 and not direct_search_used:
        raise RuntimeError("MyDealz-RSS konnte nicht abgerufen werden: " + " | ".join(errors)[:350])
    return {
        "deals": deals[:12],
        "query": search_query,
        "search_url": MYDEALZ_SEARCH_URL + urllib.parse.quote_plus(_short_market_query(expected_title) or search_query),
        "status": "ok",
        "warning": " | ".join(errors)[:500] if errors else "",
        "direct_search_used": direct_search_used,
        "gemini_search_used": gemini_search_used,
    }


def _watch_excludes(value: str) -> list[str]:
    return [normalize_match_text(x) for x in re.split(r"[,;\n]+", value or "") if normalize_match_text(x)]


def mydealz_watch_match(query: str, exclude_terms: str, text: str) -> float:
    hay = normalize_match_text(text)
    if not hay:
        return 0.0
    for excluded in _watch_excludes(exclude_terms):
        if excluded and excluded in hay:
            return 0.0
    qtokens = [t for t in significant_tokens(normalize_match_text(query)) if len(t) >= 2]
    if not qtokens:
        qtokens = [t for t in normalize_match_text(query).split() if len(t) >= 2]
    if not qtokens:
        return 0.0
    htokens = set(hay.split())
    if not all(t in htokens for t in qtokens):
        return 0.0
    return 1.0


def parse_mydealz_watch_feed(raw: bytes, query: str, exclude_terms: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError("MyDealz-RSS konnte nicht gelesen werden.") from exc
    nodes = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    out: list[dict[str, Any]] = []
    for node in nodes:
        title = _xml_child_text(node, {"title"})
        url = _xml_child_text(node, {"link"})
        description = _xml_child_text(node, {"description", "summary", "content", "encoded"})
        if not title or not url:
            continue
        score = mydealz_watch_match(query, exclude_terms, title + " " + html_to_text(description))
        if score <= 0:
            continue
        merchant = ""
        merchant_node = _xml_first_element(node, "merchant")
        merchant_price = None
        if merchant_node is not None:
            merchant = (merchant_node.attrib.get("name") or "").strip()[:180]
            merchant_price = parse_deal_price_to_cents(merchant_node.attrib.get("price") or "")
        price = merchant_price or parse_deal_price_to_cents(title) or parse_deal_price_to_cents(html_to_text(description))
        temp = None
        tm = re.search(r"(-?\d{1,4})\s*°", title + " " + html_to_text(description))
        if tm:
            try:
                temp = int(tm.group(1))
            except ValueError:
                pass
        published = ""
        published_raw = _xml_child_text(node, {"pubdate", "published", "updated", "date"})
        if published_raw:
            try:
                dtx = parsedate_to_datetime(published_raw)
                if dtx.tzinfo is None:
                    dtx = dtx.replace(tzinfo=timezone.utc)
                published = dtx.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            except Exception:
                pass
        key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
        key = key_match.group(1) if key_match else url.split("#", 1)[0]
        out.append({"deal_key": key[:500], "title": title[:500], "url": url[:1500], "price_cents": price,
                    "temperature": temp, "merchant": merchant, "published_at": published, "match_score": score, "active": True})
    return out


def parse_mydealz_watch_search(raw: str, query: str, exclude_terms: str) -> list[dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for m in re.finditer(r'''(?is)<a\b[^>]*href=["']([^"']*/deals/[^"']+)["'][^>]*>(.*?)</a>''', raw):
        href = html.unescape(m.group(1)).strip()
        if href.startswith("/"):
            href = urllib.parse.urljoin("https://www.mydealz.de", href)
        href = _valid_mydealz_url(href)
        if not href:
            continue
        title = html_to_text(m.group(2))[:500]
        window = raw[m.start(): min(len(raw), m.end() + 3200)]
        plain = html_to_text(window)
        score = mydealz_watch_match(query, exclude_terms, title + " " + plain)
        if score <= 0:
            continue
        key_match = re.search(r"-(\d{5,})(?:[/?#]|$)", href)
        key = key_match.group(1) if key_match else href
        price = parse_deal_price_to_cents(title) or parse_deal_price_to_cents(plain)
        temp = None
        tm = re.search(r"(-?\d{1,4})\s*°", plain)
        if tm:
            try:
                temp = int(tm.group(1))
            except ValueError:
                pass
        results[key] = {"deal_key": key[:500], "title": title, "url": href[:1500], "price_cents": price,
                        "temperature": temp, "merchant": "", "published_at": "", "match_score": score, "active": True}
    return list(results.values())


def fetch_mydealz_watch_deals(query: str, exclude_terms: str = "", include_search: bool = False) -> dict[str, Any]:
    query = " ".join((query or "").split()).strip()[:180]
    if not query:
        return {"deals": [], "query": "", "status": "empty", "warning": "", "direct_search_used": False}
    combined: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    def verify_url(url: str, fallback_score: float = 1.0) -> None:
        thread = _mydealz_fetch_thread_detail(url)
        if _mydealz_thread_active(thread) is not True or thread is None:
            return
        metadata = thread.get("metadata") or {}
        text = " ".join(
            str(x or "") for x in (
                thread.get("title"), thread.get("descriptionPurified"),
                metadata.get("title") if isinstance(metadata, dict) else "",
                metadata.get("description") if isinstance(metadata, dict) else "",
            )
        )
        score = mydealz_watch_match(query, exclude_terms, text)
        if score <= 0:
            return
        deal = _mydealz_thread_as_deal(thread, url)
        deal["match_score"] = max(float(fallback_score or 0.0), score)
        combined[deal["deal_key"]] = deal

    feed_ok = 0
    for feed_url in MYDEALZ_FEED_URLS:
        try:
            body, _, _ = fetch_url(feed_url, timeout=MYDEALZ_TIMEOUT_SECONDS, referer="https://www.mydealz.de/")
            feed_ok += 1
            for deal in parse_mydealz_watch_feed(body, query, exclude_terms):
                verify_url(str(deal.get("url") or ""), float(deal.get("match_score") or 1.0))
        except Exception as exc:
            errors.append(f"RSS: {exc}")

    if include_search:
        try:
            search_url = MYDEALZ_SEARCH_URL + urllib.parse.quote_plus(query)
            body, _, _ = fetch_url(search_url, timeout=MYDEALZ_TIMEOUT_SECONDS, referer="https://www.mydealz.de/")
            raw = body.decode("utf-8", errors="replace")
            urls: list[str] = []
            for candidate in parse_mydealz_watch_search(raw, query, exclude_terms):
                url = _valid_mydealz_url(str(candidate.get("url") or ""))
                if url and url not in urls:
                    urls.append(url)
            for url, _ in _mydealz_raw_deal_urls(raw):
                if url not in urls:
                    urls.append(url)
            for url in urls[:30]:
                verify_url(url)
        except Exception as exc:
            errors.append(f"Suche: {exc}")

    if not combined and feed_ok == 0 and not include_search:
        raise RuntimeError("MyDealz-RSS konnte nicht abgerufen werden: " + " | ".join(errors)[:350])
    deals = list(combined.values())
    deals.sort(key=lambda d: (d.get("published_at") or "", d.get("deal_key") or ""), reverse=True)
    return {"deals": deals[:20], "query": query, "status": "ok", "warning": " | ".join(errors)[:500], "direct_search_used": include_search}


def get_mydealz_watch_deals(watch_id: int, limit: int = 20, active: bool | None = None) -> list[dict[str, Any]]:
    where = "watch_id=?"
    params: list[Any] = [watch_id]
    if active is not None:
        where += " AND active=?"
        params.append(1 if active else 0)
    params.append(max(1, min(limit, 50)))
    with db_connect() as conn:
        rows = conn.execute(
            f"SELECT deal_key,title,url,price_cents,temperature,merchant,published_at,first_seen_at,last_seen_at,active "
            f"FROM mydealz_watch_deals WHERE {where} ORDER BY COALESCE(published_at,first_seen_at) DESC, id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [{"deal_key": r["deal_key"], "title": r["title"], "url": r["url"],
             "price": r["price_cents"] / 100 if r["price_cents"] is not None else None,
             "temperature": r["temperature"], "merchant": r["merchant"], "published_at": r["published_at"],
             "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"], "active": bool(r["active"])} for r in rows]


def row_to_watch(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("active", "notify_primary", "notify_secondary"):
        d[k] = bool(d.get(k))
    d["type"] = "mydealz_watch"
    d["notify_targets"] = [name for enabled, name in ((d.get("notify_primary"), "primary"), (d.get("notify_secondary"), "secondary")) if enabled]
    watch_id = int(d["id"])
    d["active_deal_items"] = get_mydealz_watch_deals(watch_id, 20, True)
    d["ended_deal_items"] = get_mydealz_watch_deals(watch_id, 20, False)
    d["deals"] = d["active_deal_items"] + d["ended_deal_items"]
    with db_connect() as conn:
        d["active_deals"] = int(conn.execute(
            "SELECT COUNT(*) FROM mydealz_watch_deals WHERE watch_id=? AND active=1", (watch_id,)
        ).fetchone()[0])
        d["ended_deals"] = int(conn.execute(
            "SELECT COUNT(*) FROM mydealz_watch_deals WHERE watch_id=? AND active=0", (watch_id,)
        ).fetchone()[0])
    d["search_url"] = MYDEALZ_SEARCH_URL + urllib.parse.quote_plus(str(d.get("query") or ""))
    return d


def get_mydealz_watch(watch_id: int) -> sqlite3.Row | None:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM mydealz_watches WHERE id=?", (watch_id,)).fetchone()


def get_mydealz_deals(product_id: int, limit: int = 8) -> list[dict[str, Any]]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT deal_key, title, url, price_cents, temperature, merchant, published_at, first_seen_at, last_seen_at, match_score, active
            FROM mydealz_deals WHERE product_id=?
            ORDER BY COALESCE(published_at, first_seen_at) DESC, id DESC LIMIT ?
            """,
            (product_id, max(1, min(limit, 30))),
        ).fetchall()
    return [
        {
            "deal_key": r["deal_key"],
            "title": r["title"],
            "url": r["url"],
            "price": r["price_cents"] / 100 if r["price_cents"] is not None else None,
            "temperature": r["temperature"],
            "merchant": r["merchant"],
            "published_at": r["published_at"],
            "first_seen_at": r["first_seen_at"],
            "last_seen_at": r["last_seen_at"],
            "match_score": r["match_score"],
            "active": bool(r["active"]),
        }
        for r in rows
    ]


def money(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["type"] = "amazon_product"
    for key in (
        "notify_wish", "notify_drop", "notify_low", "notify_price_change", "notify_primary", "notify_secondary",
        "active", "wish_triggered", "idealo_enabled", "idealo_manual", "notify_idealo_cheaper",
        "idealo_cheaper_triggered", "used_available", "used_initialized", "notify_used_available",
        "mydealz_enabled", "notify_mydealz", "mydealz_initialized",
    ):
        d[key] = bool(d.get(key))

    cents_to_euro = {
        "current_price_cents": "current_price",
        "wish_price_cents": "wish_price",
        "low_price_cents": "low_price",
        "start_price_cents": "start_price",
        "idealo_current_price_cents": "idealo_current_price",
        "idealo_low_price_cents": "idealo_low_price",
        "idealo_start_price_cents": "idealo_start_price",
        "idealo_cheaper_threshold_cents": "idealo_cheaper_threshold",
        "price_change_threshold_cents": "price_change_threshold",
        "used_current_price_cents": "used_current_price",
        "used_low_price_cents": "used_low_price",
        "used_start_price_cents": "used_start_price",
        "mydealz_best_price_cents": "mydealz_best_price",
    }
    for source, target in cents_to_euro.items():
        d[target] = (d[source] / 100) if d.get(source) is not None else None

    amazon = d.get("current_price_cents")
    raw_idealo = d.get("idealo_current_price_cents")
    d["idealo_last_known_price"] = (raw_idealo / 100) if raw_idealo is not None else None
    idealo_fresh = idealo_price_is_fresh(d)
    d["idealo_price_fresh"] = idealo_fresh
    idealo_age = seconds_since(d.get("idealo_last_success"))
    d["idealo_last_success_age_seconds"] = int(idealo_age) if idealo_age is not None else None
    stored_idealo_url = str(d.get("idealo_url") or "")
    try:
        safe_idealo_url = _direct_idealo_url(stored_idealo_url) if stored_idealo_url else ""
    except Exception:
        safe_idealo_url = ""
    # Once a concrete Idealo URL has been confirmed and persisted it stays
    # visible. A temporary Reader warning may stale the price, but must never
    # make the mapping disappear from the UI or normal settings save.
    d["idealo_url"] = safe_idealo_url or None
    idealo_verified = bool(
        safe_idealo_url and raw_idealo is not None and str(d.get("idealo_status") or "") in {"matched", "manual"} and idealo_fresh
    )
    d["idealo_price_verified"] = idealo_verified
    idealo = raw_idealo if idealo_verified else None
    if not idealo_verified:
        # Keep the historical value separately, but never present an unlinked
        # or stale price as a current market price or let it win best-price logic.
        d["idealo_current_price"] = None
        d["idealo_current_offer_url"] = None
    best_candidates = [(amazon, "Amazon", d.get("amazon_url"))] if amazon is not None else []
    if idealo is not None:
        best_candidates.append((idealo, "Idealo", d.get("idealo_current_offer_url") or safe_idealo_url))
    if best_candidates:
        best = min(best_candidates, key=lambda x: x[0])
        d["best_price"] = best[0] / 100
        d["best_source"] = best[1]
        d["best_url"] = best[2]
    else:
        d["best_price"] = None
        d["best_source"] = ""
        d["best_url"] = ""

    d["amazon_change_since_start"] = ((amazon - d["start_price_cents"]) / 100) if amazon is not None and d.get("start_price_cents") is not None else None
    d["change_since_start"] = d["amazon_change_since_start"]
    d["idealo_change_since_start"] = ((idealo - d["idealo_start_price_cents"]) / 100) if idealo is not None and d.get("idealo_start_price_cents") is not None else None
    used = d.get("used_current_price_cents")
    d["used_change_since_start"] = ((used - d["used_start_price_cents"]) / 100) if used is not None and d.get("used_start_price_cents") is not None else None
    lows = [x for x in (d.get("low_price_cents"), d.get("idealo_low_price_cents")) if x is not None]
    d["absolute_low_price"] = min(lows) / 100 if lows else None

    if amazon is not None and idealo is not None:
        diff = idealo - amazon
        d["idealo_vs_amazon"] = diff / 100
        d["cheaper_source"] = "Idealo" if diff < 0 else ("Amazon" if diff > 0 else "Gleich")
        d["savings_vs_amazon"] = (amazon - idealo) / 100 if idealo < amazon else 0.0
    else:
        d["idealo_vs_amazon"] = None
        d["cheaper_source"] = ""
        d["savings_vs_amazon"] = None

    d["notify_targets"] = [name for enabled, name in ((d.get("notify_primary"), "primary"), (d.get("notify_secondary"), "secondary")) if enabled]
    query = (d.get("mydealz_query") or build_mydealz_query(d.get("title") or "")).strip()
    d["mydealz_query_effective"] = query
    d["mydealz_search_url"] = MYDEALZ_SEARCH_URL + urllib.parse.quote_plus(query) if query else "https://www.mydealz.de/"
    idealo_query = _short_market_query(str(d.get("title") or "")).strip()
    d["idealo_search_url"] = IDEALO_SEARCH_URL + urllib.parse.quote_plus(idealo_query) if idealo_query else "https://www.idealo.de/"
    d["mydealz_deals"] = get_mydealz_deals(int(d["id"]), 6)
    best_new = d.get("best_price")
    md = d.get("mydealz_best_price")
    d["mydealz_vs_best"] = (md - best_new) if md is not None and best_new is not None else None
    card_candidates: list[tuple[float, str]] = []
    if d.get("current_price") is not None:
        card_candidates.append((float(d["current_price"]), "amazon"))
    if d.get("idealo_current_price") is not None:
        card_candidates.append((float(d["idealo_current_price"]), "idealo"))
    if d.get("mydealz_best_price") is not None and d.get("mydealz_best_url"):
        card_candidates.append((float(d["mydealz_best_price"]), "mydealz"))
    if card_candidates:
        cp, cs = min(card_candidates, key=lambda x: x[0])
        d["card_best_new_price"] = cp
        d["card_best_new_source"] = cs
    else:
        d["card_best_new_price"] = None
        d["card_best_new_source"] = ""
    key, model = gemini_settings()
    d["gemini_configured"] = bool(key)
    d["gemini_model"] = model
    return d


def get_product(product_id: int) -> sqlite3.Row | None:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()


def get_previous_price(conn: sqlite3.Connection, product_id: int) -> int | None:
    row = conn.execute(
        "SELECT price_cents FROM prices WHERE product_id=? ORDER BY id DESC LIMIT 1",
        (product_id,),
    ).fetchone()
    return row[0] if row else None


def get_previous_idealo_price(conn: sqlite3.Connection, product_id: int) -> int | None:
    row = conn.execute(
        "SELECT price_cents FROM idealo_prices WHERE product_id=? ORDER BY id DESC LIMIT 1",
        (product_id,),
    ).fetchone()
    return row[0] if row else None


def _best_current_from_row(row: sqlite3.Row) -> tuple[int | None, str, str]:
    values: list[tuple[int, str, str]] = []
    if row["current_price_cents"] is not None:
        values.append((row["current_price_cents"], "Amazon", row["amazon_url"]))
    if row["idealo_current_price_cents"] is not None:
        try:
            idealo_url = _direct_idealo_url(str(row["idealo_url"] or "")) if row["idealo_url"] else ""
        except Exception:
            idealo_url = ""
        # A historical Idealo price without a persisted concrete product URL is
        # not a live market price. Temporary Reader failures leave a previously
        # confirmed mapping/status untouched, so the last safe price can remain.
        if idealo_url and str(row["idealo_status"] or "") in {"matched", "manual"} and idealo_price_is_fresh(row):
            values.append((row["idealo_current_price_cents"], "Idealo", idealo_url))
    if not values:
        return None, "", row["amazon_url"]
    return min(values, key=lambda x: x[0])


def price_change_line(source: str, old_cents: int | None, new_cents: int | None) -> str:
    if old_cents is None or new_cents is None or old_cents == new_cents:
        return ""
    diff = new_cents - old_cents
    pct = (diff / old_cents * 100.0) if old_cents else 0.0
    arrow = "↓" if diff < 0 else "↑"
    sign = "−" if diff < 0 else "+"
    pct_text = f"{abs(pct):.1f}".replace(".", ",")
    return f"{source}: {money(old_cents)} → {money(new_cents)} · {arrow} {money(abs(diff))} ({sign}{pct_text} %)"


def _notification_market_snapshot(product: sqlite3.Row) -> str:
    parts: list[str] = []
    if product["current_price_cents"] is not None:
        parts.append(f"Amazon {money(product['current_price_cents'])}")
    idealo_url = str(product["idealo_url"] or "")
    idealo_ok = bool(
        idealo_url and product["idealo_current_price_cents"] is not None
        and str(product["idealo_status"] or "") in {"matched", "manual"}
        and idealo_price_is_fresh(product)
    )
    if idealo_ok:
        parts.append(f"Idealo {money(product['idealo_current_price_cents'])}")
    return " · ".join(parts)


def send_notification(
    product: sqlite3.Row,
    price_cents: int,
    source: str,
    reasons: list[str],
    target_url: str,
    change_lines: list[str] | None = None,
) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        log.warning("SUPERVISOR_TOKEN fehlt; Push wird übersprungen.")
        return
    targets: list[tuple[str, str]] = []
    if bool(product["notify_primary"]):
        targets.append(("primary", NOTIFY_primary))
    if bool(product["notify_secondary"]):
        targets.append(("secondary", NOTIFY_secondary))
    if not targets:
        return
    title = "Preiswächter"
    lines = [str(product["custom_name"] or product["title"] or product["asin"] or "Preisänderung")]
    for line in change_lines or []:
        if line:
            lines.append(line)
    if source in {"Amazon", "Idealo"}:
        snapshot = _notification_market_snapshot(product)
        if snapshot:
            lines.append("Aktuell: " + snapshot)
        lines.append(f"Bester Neu-Preis: {source} {money(price_cents)}")
    else:
        lines.append(f"{source}: {money(price_cents)}")
    hidden = {"Amazon-Preis gesunken", "Idealo-Preis gesunken"}
    visible_reasons = [r for r in reasons if r and r not in hidden]
    if visible_reasons:
        lines.append(" · ".join(visible_reasons))
    message = "\n".join(lines)
    payload = {"title": title, "message": message, "data": {"url": "http://192.168.10.199:8100"}}
    body = json.dumps(payload).encode("utf-8")
    for label, target in targets:
        req = urllib.request.Request(
            f"http://supervisor/core/api/services/notify/{target}", data=body, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 300:
                    log.warning("Push an %s meldete HTTP %s", label, resp.status)
                else:
                    log.info("Push an %s gesendet.", label)
        except Exception:
            log.exception("Push an %s (%s) fehlgeschlagen", label, target)


def send_idealo_link_error_notification(product: sqlite3.Row, error: str) -> bool:
    """Notify primary once for a new failed Gemini check without changing the link."""
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        log.warning("SUPERVISOR_TOKEN fehlt; Idealo-Fehlerhinweis wird später erneut versucht.")
        return False
    label = str(product["custom_name"] or product["title"] or product["asin"] or "Artikel")
    payload = {
        "title": "⚠️ Preiswächter · Idealo prüfen",
        "message": f"{label}\nDie gespeicherte Idealo-Zuordnung konnte nicht geprüft werden. Link bleibt unverändert.\n{error[:280]}",
        "data": {
            "url": "http://192.168.10.199:8100",
            "tag": f"idealo-link-fehler-{product['id']}",
            # iOS critical alerts are always audible. Time-sensitive + sound
            # none is the closest important, explicitly silent notification.
            "push": {"sound": "none", "interruption-level": "time-sensitive"},
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://supervisor/core/api/services/notify/{NOTIFY_primary}",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                log.warning("Idealo-Fehlerhinweis an primary meldete HTTP %s", resp.status)
                return False
        return True
    except Exception:
        log.exception("Idealo-Fehlerhinweis an primary fehlgeschlagen")
        return False


def send_mydealz_product_notification(product: sqlite3.Row, deal: dict[str, Any]) -> bool:
    """Send one push for a newly discovered active MyDealz deal.

    Delivery is independent of whether the deal beats Amazon/Idealo and also
    works when MyDealz did not expose a parseable price. The caller marks the
    deal notified only after at least one configured target accepted the push.
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        log.warning("SUPERVISOR_TOKEN fehlt; MyDealz-Push wird später erneut versucht.")
        return False
    targets: list[tuple[str, str]] = []
    if bool(product["notify_primary"]):
        targets.append(("primary", NOTIFY_primary))
    if bool(product["notify_secondary"]):
        targets.append(("secondary", NOTIFY_secondary))
    if not targets:
        return True
    title = "Preiswächter · MyDealz"
    lines = [str(product["custom_name"] or product["title"] or product["asin"] or "Amazon-Artikel"), str(deal.get("title") or "Neuer aktiver Deal")]
    price = deal.get("price_cents")
    extra: list[str] = []
    if price is not None:
        extra.append(money(int(price)))
    if deal.get("temperature") is not None:
        extra.append(f"{deal['temperature']}°")
    if extra:
        lines.append(" · ".join(extra))
    lines.append("Neuer aktiver MyDealz-Deal")
    payload = {"title": title, "message": "\n".join(lines), "data": {"url": "http://192.168.10.199:8100"}}
    body = json.dumps(payload).encode("utf-8")
    delivered = False
    for label, target in targets:
        req = urllib.request.Request(
            f"http://supervisor/core/api/services/notify/{target}", data=body, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 300:
                    log.warning("MyDealz-Produkt-Push an %s meldete HTTP %s", label, resp.status)
                else:
                    delivered = True
                    log.info("MyDealz-Produkt-Push an %s gesendet.", label)
        except Exception:
            log.exception("MyDealz-Produkt-Push an %s (%s) fehlgeschlagen", label, target)
    return delivered


def fetch_mydealz_deal_active(url: str) -> bool | None:
    """Return activity from the exact MyDealz thread state."""
    valid = _valid_mydealz_url(url)
    if not valid:
        return False
    thread = _mydealz_fetch_thread_detail(valid, force=True)
    return _mydealz_thread_active(thread)


def _stored_mydealz_expired_keys(product_id: int, limit: int = 4) -> list[str]:
    """Validate cheapest stored active deals so an expired deal cannot remain current."""
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT deal_key,url FROM mydealz_deals WHERE product_id=? AND active=1 AND price_cents IS NOT NULL "
            "ORDER BY price_cents ASC, id DESC LIMIT ?",
            (product_id, max(1, min(limit, 8))),
        ).fetchall()
    expired: list[str] = []
    for row in rows:
        state = fetch_mydealz_deal_active(str(row["url"] or ""))
        if state is False:
            expired.append(str(row["deal_key"]))
            continue
        # Fail closed. If activity cannot be positively confirmed, do not keep
        # a historic result active. A still-current deal is re-added from the
        # status-bearing source in the same refresh cycle.
        if state is None:
            expired.append(str(row["deal_key"]))
            continue
        break
    return expired


def check_product(
    product_id: int,
    check_amazon: bool = True,
    check_idealo: bool = True,
    check_mydealz: bool = True,
    force_idealo_rematch: bool = False,
    idealo_gemini_check: bool = False,
    mydealz_search: bool = False,
    mydealz_gemini: bool = False,
) -> dict[str, Any]:
    original = get_product(product_id)
    if not original:
        raise KeyError("Artikel nicht gefunden")

    checked_at = utc_now_iso()
    amazon_info: dict[str, Any] | None = None
    amazon_error: str | None = None
    idealo_info: dict[str, Any] | None = None
    idealo_error: str | None = None
    mydealz_info: dict[str, Any] | None = None
    mydealz_error: str | None = None
    idealo_gemini_attempted = False
    idealo_error_notification: str | None = None
    mydealz_search_attempted = False
    mydealz_gemini_attempted = False
    expired_mydealz_keys: list[str] = []

    if check_amazon:
        try:
            amazon_info = fetch_amazon_product(original["asin"])
        except Exception as exc:
            amazon_error = str(exc)

    expected_title = (amazon_info or {}).get("title") or original["title"] or ""

    if check_idealo and bool(original["idealo_enabled"]):
        try:
            manual = bool(original["idealo_manual"])
            idealo_url = str(original["idealo_url"] or "")
            if force_idealo_rematch:
                # Google Search is an explicit, one-off user action: at creation
                # and on the "Idealo neu zuordnen" button only.
                idealo_gemini_attempted = gemini_configured()
                idealo_info = find_idealo_product(expected_title, asin=str(original["asin"] or ""))
                if idealo_info.get("status") == "unavailable":
                    idealo_error = str(idealo_info.get("error") or "Kein eindeutiger Idealo-Treffer.")
            elif idealo_url and idealo_gemini_check:
                # A confirmed mapping is immutable during normal operation.
                # URL Context reads exactly this page and never uses Google Search.
                idealo_gemini_attempted = True
                record_idealo_url_context_request()
                # Gemini may expose only a generic Idealo page title during a
                # partial render. This is safe to tolerate only for a link that
                # was already independently confirmed and is still unchanged.
                # Explicitly mismatching titles remain a hard rejection.
                known_verified = (
                    str(original["idealo_status"] or "") in {"matched", "manual"}
                    and float(original["idealo_match_score"] or 0.0) >= 0.90
                    and bool(original["idealo_last_verified"])
                )
                idealo_info = fetch_idealo_via_gemini_url_context(
                    idealo_url, expected_title, manual=manual, known_verified=known_verified
                )
            elif not idealo_url:
                idealo_error = "Idealo ist noch nicht zugeordnet. Bitte ‚Idealo neu zuordnen‘ verwenden."
        except Exception as exc:
            idealo_error = str(exc)

    if check_mydealz and bool(original["mydealz_enabled"]):
        try:
            expired_mydealz_keys = _stored_mydealz_expired_keys(product_id)
            mydealz_search_attempted = bool(mydealz_search)
            mydealz_gemini_attempted = bool(mydealz_gemini and gemini_configured())
            mydealz_info = fetch_mydealz_deals(
                expected_title, original["mydealz_query"] or None, asin=str(original["asin"] or ""),
                include_search=mydealz_search_attempted, include_gemini=mydealz_gemini_attempted,
            )
        except Exception as exc:
            mydealz_error = str(exc)

    reasons: list[str] = []
    price_change_lines: list[str] = []
    used_notification: tuple[int, str] | None = None
    mydealz_notifications: list[dict[str, Any]] = []

    with db_connect() as conn:
        current = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        previous_amazon = get_previous_price(conn, product_id)
        previous_idealo = get_previous_idealo_price(conn, product_id)

        if check_amazon:
            if amazon_error:
                conn.execute(
                    "UPDATE products SET last_checked=?, last_error=?, used_last_checked=?, used_last_error=?, updated_at=? WHERE id=?",
                    (checked_at, amazon_error[:500], checked_at, amazon_error[:500], checked_at, product_id),
                )
            elif amazon_info is not None:
                price = amazon_info.get("price_cents")
                if price is None:
                    err = "Produktdaten erkannt, aber kein eindeutiger aktueller Neu-/Buy-Box-Preis gefunden."
                    conn.execute(
                        """
                        UPDATE products SET title=?, image_url=?, current_price_source=?, current_seller=?, current_availability=?,
                            current_condition=?, last_checked=?, last_error=?, updated_at=? WHERE id=?
                        """,
                        (amazon_info["title"], amazon_info["image_url"], amazon_info["price_source"], amazon_info["seller"],
                         amazon_info["availability"], amazon_info["condition"], checked_at, err, checked_at, product_id),
                    )
                    amazon_error = err
                else:
                    price = int(price)
                    change_line = price_change_line("Amazon", previous_amazon, price)
                    if change_line:
                        price_change_lines.append(change_line)
                    old_low = current["low_price_cents"]
                    start_price = current["start_price_cents"] if current["start_price_cents"] is not None else price
                    new_low = price if old_low is None else min(old_low, price)
                    if old_low is not None and price < old_low and current["notify_low"]:
                        reasons.append("🔥 Neuer Amazon-Tiefpreis seit Start")
                    if previous_amazon is not None and price < previous_amazon and current["notify_drop"]:
                        reasons.append("Amazon-Preis gesunken")
                    change_threshold = max(0, int(current["price_change_threshold_cents"] or 0))
                    if (
                        previous_amazon is not None
                        and price != previous_amazon
                        and bool(current["notify_price_change"])
                        and abs(price - previous_amazon) >= change_threshold
                    ):
                        reasons.append(f"Amazon-Preisänderung um {money(abs(price - previous_amazon))}")
                    conn.execute(
                        "INSERT INTO prices(product_id, checked_at, price_cents, price_source, seller, availability, condition) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (product_id, checked_at, price, amazon_info["price_source"], amazon_info["seller"], amazon_info["availability"], amazon_info["condition"]),
                    )
                    conn.execute(
                        """
                        UPDATE products SET title=?, image_url=?, current_price_cents=?, current_price_source=?, current_seller=?,
                            current_availability=?, current_condition=?, last_checked=?, last_success=?, last_error=NULL,
                            low_price_cents=?, start_price_cents=?, updated_at=? WHERE id=?
                        """,
                        (amazon_info["title"], amazon_info["image_url"], price, amazon_info["price_source"], amazon_info["seller"],
                         amazon_info["availability"], amazon_info["condition"], checked_at, checked_at, new_low, start_price, checked_at, product_id),
                    )

                # Used offers are intentionally separate from the normal/new
                # Amazon price. They never influence the wish-price or best-new
                # price calculation.
                used_available = bool(amazon_info.get("used_available"))
                used_price = amazon_info.get("used_price_cents")
                old_used_available = bool(current["used_available"])
                used_initialized = bool(current["used_initialized"])
                if used_available and used_price is not None:
                    used_price = int(used_price)
                    old_used_low = current["used_low_price_cents"]
                    used_start = current["used_start_price_cents"] if current["used_start_price_cents"] is not None else used_price
                    used_low = used_price if old_used_low is None else min(old_used_low, used_price)
                    conn.execute(
                        "INSERT INTO used_prices(product_id, checked_at, price_cents, condition, offer_url) VALUES (?, ?, ?, ?, ?)",
                        (product_id, checked_at, used_price, amazon_info.get("used_condition", ""), amazon_info.get("used_offer_url", "")),
                    )
                    conn.execute(
                        """
                        UPDATE products SET used_current_price_cents=?, used_offer_url=?, used_condition=?, used_available=1,
                            used_initialized=1, used_last_checked=?, used_last_success=?, used_last_error=NULL,
                            used_low_price_cents=?, used_start_price_cents=?, updated_at=? WHERE id=?
                        """,
                        (used_price, amazon_info.get("used_offer_url", ""), amazon_info.get("used_condition", ""),
                         checked_at, checked_at, used_low, used_start, checked_at, product_id),
                    )
                    if used_initialized and not old_used_available and bool(current["notify_used_available"]):
                        used_notification = (used_price, amazon_info.get("used_offer_url", "") or current["amazon_url"])
                else:
                    conn.execute(
                        """
                        UPDATE products SET used_current_price_cents=NULL, used_available=0, used_initialized=1,
                            used_last_checked=?, used_last_error=NULL, updated_at=? WHERE id=?
                        """,
                        (checked_at, checked_at, product_id),
                    )

        if check_idealo and bool(current["idealo_enabled"]):
            gemini_stamp = checked_at if idealo_gemini_attempted else current["idealo_gemini_last_checked"]
            # The legacy database field is retained for migration compatibility;
            # Idealo has no Reader/Browser path anymore.
            reader_failures = 0
            idealo_checked_stamp = checked_at if idealo_gemini_attempted else current["idealo_last_checked"]
            durable_url = str(current["idealo_url"] or "")
            if idealo_error:
                # Never delete/demote a confirmed Idealo mapping on a Gemini
                # failure. Keep its last safe price and URL, but show the issue.
                visible_error = idealo_error[:500]
                conn.execute(
                    "UPDATE products SET idealo_last_checked=?, idealo_last_error=?, idealo_gemini_last_checked=?, idealo_reader_failures=?, updated_at=? WHERE id=?",
                    (idealo_checked_stamp, visible_error, gemini_stamp, reader_failures, checked_at, product_id),
                )
            elif idealo_info is not None:
                status = str(idealo_info.get("status") or "unavailable")
                score = float(idealo_info.get("match_score") or 0.0)
                if status == "uncertain":
                    msg = str(idealo_info.get("error") or "Idealo-Seite konnte diesmal nicht eindeutig bestätigt werden; die gespeicherte Zuordnung bleibt erhalten.")
                    if durable_url:
                        # A known mapping is durable. If this was an explicit
                        # rematch, remember the uncertain new citation separately
                        # but keep the old confirmed URL until replacement succeeds.
                        conn.execute(
                            """
                            UPDATE products SET
                                idealo_candidate_url=CASE WHEN ? THEN ? ELSE idealo_candidate_url END,
                                idealo_candidate_title=CASE WHEN ? THEN ? ELSE idealo_candidate_title END,
                                idealo_last_checked=?, idealo_last_error=?, idealo_gemini_last_checked=?,
                                idealo_reader_failures=?, updated_at=? WHERE id=?
                            """,
                            (1 if force_idealo_rematch else 0, idealo_info.get("url"),
                             1 if force_idealo_rematch else 0, idealo_info.get("title"),
                             idealo_checked_stamp, msg[:500], gemini_stamp, reader_failures, checked_at, product_id),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE products SET idealo_candidate_url=?, idealo_candidate_title=?, idealo_match_score=?, idealo_status='uncertain',
                                idealo_last_checked=?, idealo_last_error=?, idealo_gemini_last_checked=?, idealo_reader_failures=?, updated_at=? WHERE id=?
                            """,
                            (idealo_info.get("url"), idealo_info.get("title"), score, idealo_checked_stamp, msg, gemini_stamp,
                             reader_failures, checked_at, product_id),
                        )
                    idealo_error = msg
                elif status in {"matched", "manual"} and idealo_info.get("price_cents") is None:
                    msg = str(idealo_info.get("warning") or "Idealo-Produktseite sicher zugeordnet; aktueller Vergleichspreis noch nicht bestätigt.")
                    conn.execute(
                        """
                        UPDATE products SET idealo_url=?, idealo_candidate_url=NULL, idealo_candidate_title=NULL, idealo_match_title=?,
                            idealo_match_score=?, idealo_status=?, idealo_last_checked=?, idealo_last_error=?,
                            idealo_gemini_last_checked=?, idealo_reader_failures=0, idealo_last_verified=?, updated_at=? WHERE id=?
                        """,
                        (idealo_info.get("url"), idealo_info.get("title"), score, status, idealo_checked_stamp, msg[:500],
                         gemini_stamp, checked_at, checked_at, product_id),
                    )
                    idealo_error = msg
                elif status in {"matched", "manual"} and idealo_info.get("price_cents") is not None:
                    price = int(idealo_info["price_cents"])
                    change_line = price_change_line("Idealo", previous_idealo, price)
                    if change_line:
                        price_change_lines.append(change_line)
                    old_low = current["idealo_low_price_cents"]
                    start_price = current["idealo_start_price_cents"] if current["idealo_start_price_cents"] is not None else price
                    new_low = price if old_low is None else min(old_low, price)
                    if old_low is not None and price < old_low and current["notify_low"]:
                        reasons.append("🔥 Neuer Idealo-Tiefpreis seit Start")
                    if previous_idealo is not None and price < previous_idealo and current["notify_drop"]:
                        reasons.append("Idealo-Preis gesunken")
                    change_threshold = max(0, int(current["price_change_threshold_cents"] or 0))
                    if (
                        previous_idealo is not None
                        and price != previous_idealo
                        and bool(current["notify_price_change"])
                        and abs(price - previous_idealo) >= change_threshold
                    ):
                        reasons.append(f"Idealo-Preisänderung um {money(abs(price - previous_idealo))}")
                    conn.execute(
                        """
                        INSERT INTO idealo_prices(product_id, checked_at, price_cents, shop, idealo_url, offer_url, price_kind)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (product_id, checked_at, price, idealo_info.get("shop", ""), idealo_info.get("url", ""),
                         idealo_info.get("offer_url", ""), idealo_info.get("price_kind", "")),
                    )
                    conn.execute(
                        """
                        UPDATE products SET idealo_url=?, idealo_candidate_url=NULL, idealo_candidate_title=NULL, idealo_match_title=?,
                            idealo_match_score=?, idealo_status=?, idealo_current_price_cents=?, idealo_current_shop=?,
                            idealo_current_offer_url=?, idealo_price_kind=?, idealo_last_checked=?, idealo_last_success=?,
                            idealo_last_error=NULL, idealo_low_price_cents=?, idealo_start_price_cents=?, idealo_gemini_last_checked=?,
                            idealo_reader_failures=0, idealo_last_verified=?, idealo_error_notified=NULL, updated_at=? WHERE id=?
                        """,
                        (idealo_info.get("url"), idealo_info.get("title"), score, status, price, idealo_info.get("shop", ""),
                         idealo_info.get("offer_url", ""), idealo_info.get("price_kind", ""), idealo_checked_stamp, checked_at,
                         new_low, start_price, gemini_stamp, checked_at, checked_at, product_id),
                    )

            if idealo_error and idealo_gemini_attempted:
                previous_notice = str(current["idealo_error_notified"] or "")
                if previous_notice != idealo_error[:500]:
                    idealo_error_notification = idealo_error[:500]

        if check_mydealz and bool(current["mydealz_enabled"]):
            mydealz_search_stamp = checked_at if mydealz_search_attempted else current["mydealz_search_last_checked"]
            mydealz_gemini_stamp = checked_at if mydealz_gemini_attempted else current["mydealz_gemini_last_checked"]
            for expired_key in expired_mydealz_keys:
                conn.execute("UPDATE mydealz_deals SET active=0 WHERE product_id=? AND deal_key=?", (product_id, expired_key))
            if mydealz_error:
                conn.execute(
                    "UPDATE products SET mydealz_last_checked=?, mydealz_last_error=?, mydealz_search_last_checked=?, mydealz_gemini_last_checked=?, updated_at=? WHERE id=?",
                    (checked_at, mydealz_error[:500], mydealz_search_stamp, mydealz_gemini_stamp, checked_at, product_id),
                )
            elif mydealz_info is not None:
                query = str(mydealz_info.get("query") or build_mydealz_query(expected_title))[:180]
                was_initialized = bool(current["mydealz_initialized"])
                for deal in mydealz_info.get("deals", []):
                    existing = conn.execute(
                        "SELECT id,notified FROM mydealz_deals WHERE product_id=? AND deal_key=?",
                        (product_id, deal["deal_key"]),
                    ).fetchone()
                    initial_notified = 1 if (not was_initialized or not bool(current["notify_mydealz"]) or not deal.get("active", True)) else 0
                    conn.execute(
                        """
                        INSERT INTO mydealz_deals(product_id, deal_key, title, url, price_cents, temperature, merchant, published_at,
                            first_seen_at, last_seen_at, match_score, active, notified)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(product_id, deal_key) DO UPDATE SET
                            title=excluded.title, url=excluded.url, price_cents=excluded.price_cents,
                            temperature=excluded.temperature, merchant=excluded.merchant, published_at=excluded.published_at,
                            last_seen_at=excluded.last_seen_at, match_score=excluded.match_score, active=excluded.active
                        """,
                        (product_id, deal["deal_key"], deal["title"], deal["url"], deal.get("price_cents"),
                         deal.get("temperature"), deal.get("merchant", ""), deal.get("published_at"), checked_at, checked_at,
                         deal.get("match_score"), 1 if deal.get("active", True) else 0, initial_notified),
                    )

                best_deal = conn.execute(
                    "SELECT price_cents,title,url,temperature,merchant,published_at FROM mydealz_deals "
                    "WHERE product_id=? AND active=1 AND price_cents IS NOT NULL ORDER BY price_cents ASC, id DESC LIMIT 1",
                    (product_id,),
                ).fetchone()
                conn.execute(
                    """
                    UPDATE products SET mydealz_query=?, mydealz_last_checked=?, mydealz_last_success=?, mydealz_last_error=?,
                        mydealz_initialized=1, mydealz_best_price_cents=?, mydealz_best_title=?, mydealz_best_url=?,
                        mydealz_best_temperature=?, mydealz_best_merchant=?, mydealz_best_published=?, mydealz_search_last_checked=?,
                        mydealz_gemini_last_checked=?, updated_at=? WHERE id=?
                    """,
                    (query, checked_at, checked_at, str(mydealz_info.get("warning") or "")[:500] or None,
                     best_deal["price_cents"] if best_deal else None,
                     best_deal["title"] if best_deal else None,
                     best_deal["url"] if best_deal else None,
                     best_deal["temperature"] if best_deal else None,
                     best_deal["merchant"] if best_deal else None,
                     best_deal["published_at"] if best_deal else None,
                     mydealz_search_stamp, mydealz_gemini_stamp, checked_at, product_id),
                )

                if was_initialized and bool(current["notify_mydealz"]):
                    pending_rows = conn.execute(
                        "SELECT deal_key,title,url,price_cents,temperature,merchant,published_at "
                        "FROM mydealz_deals WHERE product_id=? AND active=1 AND notified=0 "
                        "ORDER BY first_seen_at ASC,id ASC",
                        (product_id,),
                    ).fetchall()
                    mydealz_notifications = [dict(r) for r in pending_rows]

        updated = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        best_price, best_source, best_url = _best_current_from_row(updated)
        wish_triggered = bool(updated["wish_triggered"])
        wish = updated["wish_price_cents"]
        if wish is not None and best_price is not None and best_price <= wish:
            if updated["notify_wish"] and not wish_triggered:
                reasons.append(f"Wunschpreis {money(wish)} erreicht bei {best_source}")
            wish_triggered = True
        elif wish is None or best_price is None or best_price > wish:
            wish_triggered = False

        idealo_triggered = bool(updated["idealo_cheaper_triggered"])
        amazon_now = updated["current_price_cents"]
        idealo_now = updated["idealo_current_price_cents"]
        threshold = updated["idealo_cheaper_threshold_cents"] or 0
        cheaper_condition = (
            amazon_now is not None and idealo_now is not None and idealo_price_is_fresh(updated)
            and amazon_now - idealo_now >= threshold
        )
        if bool(updated["notify_idealo_cheaper"]) and cheaper_condition and not idealo_triggered:
            reasons.append(f"Idealo ist {money(amazon_now - idealo_now)} günstiger als Amazon")
            idealo_triggered = True
        elif not cheaper_condition:
            idealo_triggered = False

        conn.execute(
            "UPDATE products SET wish_triggered=?, idealo_cheaper_triggered=?, updated_at=? WHERE id=?",
            (1 if wish_triggered else 0, 1 if idealo_triggered else 0, checked_at, product_id),
        )
        final_row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        best_price, best_source, best_url = _best_current_from_row(final_row)

    if reasons and best_price is not None:
        send_notification(final_row, best_price, best_source, reasons, best_url, change_lines=price_change_lines)

    if idealo_error_notification and send_idealo_link_error_notification(final_row, idealo_error_notification):
        with db_connect() as conn:
            conn.execute(
                "UPDATE products SET idealo_error_notified=? WHERE id=?",
                (idealo_error_notification, product_id),
            )

    if used_notification is not None:
        used_price, used_url = used_notification
        send_notification(
            final_row,
            used_price,
            "Amazon Gebraucht",
            ["Neu verfügbar: Ein Gebrauchtangebot ist jetzt vorhanden"],
            used_url,
        )

    for deal in mydealz_notifications:
        if send_mydealz_product_notification(final_row, deal):
            with db_connect() as conn:
                conn.execute(
                    "UPDATE mydealz_deals SET notified=1 WHERE product_id=? AND deal_key=?",
                    (product_id, str(deal.get("deal_key") or "")),
                )

    final_row = get_product(product_id)
    ok = not (check_amazon and amazon_error) and not (check_idealo and idealo_error) and not (check_mydealz and mydealz_error)
    log.info(
        "%s geprüft: Amazon=%s Gebraucht=%s Idealo=%s MyDealz=%s",
        original["asin"], money(final_row["current_price_cents"]), money(final_row["used_current_price_cents"]),
        money(final_row["idealo_current_price_cents"]), money(final_row["mydealz_best_price_cents"]),
    )
    return {
        "ok": ok,
        "amazon_ok": not (check_amazon and amazon_error),
        "idealo_ok": not (check_idealo and idealo_error),
        "mydealz_ok": not (check_mydealz and mydealz_error),
        "amazon_error": amazon_error,
        "idealo_error": idealo_error,
        "mydealz_error": mydealz_error,
        "reasons": reasons,
        "product": row_to_product(final_row),
    }


def send_watch_notification(watch: sqlite3.Row, deal: dict[str, Any]) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        log.warning("SUPERVISOR_TOKEN fehlt; MyDealz-Watch-Push wird übersprungen.")
        return
    targets: list[tuple[str, str]] = []
    if bool(watch["notify_primary"]):
        targets.append(("primary", NOTIFY_primary))
    if bool(watch["notify_secondary"]):
        targets.append(("secondary", NOTIFY_secondary))
    if not targets:
        return
    lines = [f"🔥 Neuer MyDealz-Deal: {watch['name']}", str(deal.get("title") or "Neuer Deal")]
    if deal.get("price_cents") is not None:
        lines.append(f"Preis: {money(int(deal['price_cents']))}")
    meta = []
    if deal.get("merchant"):
        meta.append(str(deal["merchant"]))
    if deal.get("temperature") is not None:
        meta.append(f"{deal['temperature']}°")
    if meta:
        lines.append(" · ".join(meta))
    payload = {"title": "MyDealz-Beobachtung", "message": "\n".join(lines), "data": {"url": str(deal.get("url") or "https://www.mydealz.de/")}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for label, target in targets:
        req = urllib.request.Request(
            f"http://supervisor/core/api/services/notify/{target}", data=body, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                log.info("MyDealz-Watch-Push an %s: HTTP %s", label, resp.status)
        except Exception:
            log.exception("MyDealz-Watch-Push an %s fehlgeschlagen", label)


def _validate_watch_active_deals(watch_id: int) -> None:
    """Revalidate every saved active watch deal against its exact MyDealz thread."""
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT deal_key,url FROM mydealz_watch_deals WHERE watch_id=? AND active=1 "
            "ORDER BY COALESCE(published_at,first_seen_at) DESC, id DESC",
            (watch_id,),
        ).fetchall()
    expired: list[str] = []
    for row in rows:
        state = fetch_mydealz_deal_active(str(row["url"] or ""))
        if state is not True:
            expired.append(str(row["deal_key"]))
    if expired:
        with db_connect() as conn:
            for key in expired:
                conn.execute("UPDATE mydealz_watch_deals SET active=0 WHERE watch_id=? AND deal_key=?", (watch_id, key))


def check_mydealz_watch(watch_id: int, include_search: bool = False) -> dict[str, Any]:
    watch = get_mydealz_watch(watch_id)
    if not watch:
        raise KeyError("MyDealz-Beobachtung nicht gefunden")
    checked_at = utc_now_iso()
    _validate_watch_active_deals(watch_id)
    error: str | None = None
    info: dict[str, Any] | None = None
    try:
        info = fetch_mydealz_watch_deals(str(watch["query"] or ""), str(watch["exclude_terms"] or ""), include_search=include_search)
    except Exception as exc:
        error = str(exc)

    notifications: list[dict[str, Any]] = []
    with db_connect() as conn:
        current = conn.execute("SELECT * FROM mydealz_watches WHERE id=?", (watch_id,)).fetchone()
        existing_count = conn.execute("SELECT COUNT(*) FROM mydealz_watch_deals WHERE watch_id=?", (watch_id,)).fetchone()[0]
        if error:
            conn.execute(
                "UPDATE mydealz_watches SET last_checked=?, last_search_checked=CASE WHEN ? THEN ? ELSE last_search_checked END, "
                "last_error=?, updated_at=? WHERE id=?",
                (checked_at, 1 if include_search else 0, checked_at, error[:500], checked_at, watch_id),
            )
        elif info is not None:
            for deal in info.get("deals", []):
                old = conn.execute("SELECT id,notified FROM mydealz_watch_deals WHERE watch_id=? AND deal_key=?", (watch_id, deal["deal_key"])).fetchone()
                is_new = old is None
                initial_baseline = existing_count == 0
                notified = 1 if initial_baseline else (int(old["notified"]) if old else 0)
                conn.execute(
                    """
                    INSERT INTO mydealz_watch_deals(watch_id,deal_key,title,url,price_cents,temperature,merchant,published_at,
                        first_seen_at,last_seen_at,active,notified)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(watch_id,deal_key) DO UPDATE SET title=excluded.title,url=excluded.url,price_cents=excluded.price_cents,
                        temperature=excluded.temperature,merchant=excluded.merchant,published_at=excluded.published_at,
                        last_seen_at=excluded.last_seen_at,active=excluded.active
                    """,
                    (watch_id, deal["deal_key"], deal["title"], deal["url"], deal.get("price_cents"), deal.get("temperature"),
                     deal.get("merchant", ""), deal.get("published_at"), checked_at, checked_at, 1 if deal.get("active", True) else 0, notified),
                )
                if is_new and not initial_baseline and deal.get("active", True):
                    notifications.append(deal)
            conn.execute(
                "UPDATE mydealz_watches SET last_checked=?, last_search_checked=CASE WHEN ? THEN ? ELSE last_search_checked END, "
                "last_success=?, last_error=?, updated_at=? WHERE id=?",
                (checked_at, 1 if include_search else 0, checked_at, checked_at, str(info.get("warning") or "")[:500] or None, checked_at, watch_id),
            )
        final = conn.execute("SELECT * FROM mydealz_watches WHERE id=?", (watch_id,)).fetchone()

    for deal in notifications:
        send_watch_notification(final, deal)
        with db_connect() as conn:
            conn.execute("UPDATE mydealz_watch_deals SET notified=1 WHERE watch_id=? AND deal_key=?", (watch_id, deal["deal_key"]))
    return {"ok": error is None, "error": error, "watch": row_to_watch(get_mydealz_watch(watch_id))}


def refresh_all_status() -> dict[str, Any]:
    with REFRESH_ALL_LOCK:
        return dict(REFRESH_ALL_STATE)


def refresh_all_worker() -> None:
    try:
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT id, title, asin, idealo_enabled, idealo_url, idealo_candidate_url, idealo_gemini_last_checked FROM products ORDER BY id"
            ).fetchall()
        with REFRESH_ALL_LOCK:
            REFRESH_ALL_STATE.update({
                "running": True,
                "total": len(rows),
                "done": 0,
                "success": 0,
                "failed": 0,
                "current_id": None,
                "current_title": "",
                "last_error": "",
                "started_at": utc_now_iso(),
                "finished_at": None,
            })
        for row in rows:
            with REFRESH_ALL_LOCK:
                REFRESH_ALL_STATE["current_id"] = int(row["id"])
                REFRESH_ALL_STATE["current_title"] = str(row["title"] or row["asin"] or "Artikel")[:160]
            ok = False
            err = ""
            try:
                # Manual refresh reads every existing Idealo assignment through
                # Gemini URL Context. It never starts a Google Search or remaps.
                due_idealo_gemini = bool(row["idealo_url"] and gemini_configured())
                result = check_product(
                    int(row["id"]),
                    check_amazon=True,
                    check_idealo=bool(row["idealo_url"] or row["idealo_candidate_url"] or due_idealo_gemini),
                    check_mydealz=True,
                    force_idealo_rematch=False,
                    idealo_gemini_check=due_idealo_gemini,
                    mydealz_search=True,
                    mydealz_gemini=False,
                )
                ok = bool(result.get("ok"))
                if not ok:
                    err = " | ".join(
                        str(x) for x in (
                            result.get("amazon_error"),
                            result.get("idealo_error"),
                            result.get("mydealz_error"),
                        ) if x
                    )[:500]
            except Exception as exc:
                err = str(exc)[:500]
                log.error("Alle-aktualisieren: Produkt %s fehlgeschlagen:\n%s", row["id"], traceback.format_exc())
            with REFRESH_ALL_LOCK:
                REFRESH_ALL_STATE["done"] += 1
                if ok:
                    REFRESH_ALL_STATE["success"] += 1
                else:
                    REFRESH_ALL_STATE["failed"] += 1
                    if err:
                        REFRESH_ALL_STATE["last_error"] = err
            time.sleep(1)
    finally:
        with REFRESH_ALL_LOCK:
            REFRESH_ALL_STATE["running"] = False
            REFRESH_ALL_STATE["current_id"] = None
            REFRESH_ALL_STATE["current_title"] = ""
            REFRESH_ALL_STATE["finished_at"] = utc_now_iso()


def start_refresh_all() -> tuple[bool, dict[str, Any]]:
    with REFRESH_ALL_LOCK:
        if REFRESH_ALL_STATE.get("running"):
            return False, dict(REFRESH_ALL_STATE)
        REFRESH_ALL_STATE.update({
            "running": True,
            "total": 0,
            "done": 0,
            "success": 0,
            "failed": 0,
            "current_id": None,
            "current_title": "",
            "last_error": "",
            "started_at": utc_now_iso(),
            "finished_at": None,
        })
    threading.Thread(target=refresh_all_worker, name="refresh-all", daemon=True).start()
    return True, refresh_all_status()


def product_check_status(product_id: int) -> dict[str, Any]:
    with PRODUCT_CHECK_LOCK:
        state = PRODUCT_CHECK_STATES.get(product_id)
        return dict(state) if state else {
            "running": False,
            "mode": "",
            "started_at": None,
            "finished_at": None,
            "ok": None,
            "error": "",
        }


def _product_check_worker(product_id: int, mode: str) -> None:
    result: dict[str, Any] | None = None
    error = ""
    try:
        row = get_product(product_id)
        if not row:
            raise KeyError("Artikel nicht gefunden")
        if mode == "rematch":
            # This is the only manual action which may use Google Search.
            result = check_product(
                product_id, check_amazon=False, check_idealo=True, check_mydealz=False,
                force_idealo_rematch=True,
            )
        else:
            # Existing mappings are read with URL Context only: no search and
            # no automatic reassignment, even for a manual "Alles jetzt prüfen".
            use_url_context = bool(row["idealo_enabled"] and row["idealo_url"] and gemini_configured())
            result = check_product(
                product_id, check_amazon=True,
                check_idealo=bool(row["idealo_url"] or row["idealo_candidate_url"] or use_url_context),
                check_mydealz=True, force_idealo_rematch=False,
                idealo_gemini_check=use_url_context, mydealz_search=True, mydealz_gemini=False,
            )
        error = " | ".join(
            str(item) for item in (
                result.get("amazon_error"), result.get("idealo_error"), result.get("mydealz_error"),
            ) if item
        )[:500]
        ok = bool(result.get("ok"))
    except Exception as exc:
        ok = False
        error = str(exc)[:500]
        log.error("Einzelprüfung für Produkt %s fehlgeschlagen:\n%s", product_id, traceback.format_exc())
    with PRODUCT_CHECK_LOCK:
        PRODUCT_CHECK_STATES[product_id] = {
            "running": False,
            "mode": mode,
            "started_at": PRODUCT_CHECK_STATES.get(product_id, {}).get("started_at"),
            "finished_at": utc_now_iso(),
            "ok": ok,
            "error": error,
        }


def start_product_check(product_id: int, mode: str = "full") -> tuple[bool, dict[str, Any]]:
    if mode not in {"full", "rematch"}:
        raise ValueError("Ungültige Prüfart")
    with PRODUCT_CHECK_LOCK:
        existing = PRODUCT_CHECK_STATES.get(product_id)
        if existing and existing.get("running"):
            return False, dict(existing)
        PRODUCT_CHECK_STATES[product_id] = {
            "running": True,
            "mode": mode,
            "started_at": utc_now_iso(),
            "finished_at": None,
            "ok": None,
            "error": "",
        }
    threading.Thread(
        target=_product_check_worker, args=(product_id, mode),
        name=f"product-check-{product_id}", daemon=True,
    ).start()
    return True, product_check_status(product_id)


def claim_idealo_schedule_slot(now: datetime) -> bool:
    """Claim the current local schedule slot once across restarts."""
    local_now = now.astimezone(IDEALO_SCHEDULE_TIMEZONE)
    if local_now.hour not in idealo_schedule_hours() or local_now.minute >= 10:
        return False
    key = f"idealo_gemini_schedule_{local_now.strftime('%Y-%m-%d-%H')}"
    try:
        with db_connect() as conn:
            cur = conn.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES(?, ?)", (key, utc_now_iso()))
        return cur.rowcount == 1
    except Exception:
        log.warning("Idealo-Zeitfenster konnte nicht reserviert werden.", exc_info=True)
        return False


def scheduler_loop() -> None:
    time.sleep(8)
    while True:
        try:
            now = datetime.now(timezone.utc)
            scheduled_idealo_check = claim_idealo_schedule_slot(now) and gemini_configured()
            with db_connect() as conn:
                rows = conn.execute(
                    "SELECT id,last_checked,idealo_last_checked,idealo_gemini_last_checked,idealo_enabled,idealo_url,idealo_candidate_url,"
                    "mydealz_last_checked,mydealz_search_last_checked,mydealz_enabled "
                    "FROM products WHERE active=1 ORDER BY id"
                ).fetchall()
                watches = conn.execute(
                    "SELECT id,last_checked,last_search_checked FROM mydealz_watches WHERE active=1 ORDER BY id"
                ).fetchall()

            for row in rows:
                last_amazon = parse_iso(row["last_checked"])
                last_mydealz = parse_iso(row["mydealz_last_checked"])
                last_mydealz_search = parse_iso(row["mydealz_search_last_checked"])
                due_amazon = last_amazon is None or (now - last_amazon).total_seconds() >= CHECK_INTERVAL_SECONDS
                # Idealo uses only Gemini URL Context at fixed local times.
                # Missing mappings are never searched or replaced automatically.
                due_idealo_gemini = bool(
                    scheduled_idealo_check and row["idealo_enabled"] and row["idealo_url"]
                )
                due_mydealz_rss = bool(row["mydealz_enabled"]) and (
                    last_mydealz is None or (now - last_mydealz).total_seconds() >= MYDEALZ_CHECK_INTERVAL_SECONDS
                )
                due_mydealz_search = bool(row["mydealz_enabled"]) and (
                    last_mydealz_search is None or (now - last_mydealz_search).total_seconds() >= MYDEALZ_SEARCH_INTERVAL_SECONDS
                )
                slot = (int(row["id"]) * 7) % 30
                run_in_slot = due_idealo_gemini or (now.minute % 30) >= slot
                if (due_amazon or due_idealo_gemini or due_mydealz_rss or due_mydealz_search) and run_in_slot:
                    check_product(
                        int(row["id"]),
                        check_amazon=due_amazon,
                        check_idealo=due_idealo_gemini,
                        check_mydealz=due_mydealz_rss or due_mydealz_search,
                        force_idealo_rematch=False,
                        idealo_gemini_check=due_idealo_gemini,
                        mydealz_search=due_mydealz_search,
                        mydealz_gemini=False,
                    )
                    time.sleep(2)

            for watch in watches:
                last_rss = parse_iso(watch["last_checked"])
                last_search = parse_iso(watch["last_search_checked"])
                due_rss = last_rss is None or (now - last_rss).total_seconds() >= MYDEALZ_WATCH_CHECK_INTERVAL_SECONDS
                due_search = last_search is None or (now - last_search).total_seconds() >= MYDEALZ_WATCH_SEARCH_INTERVAL_SECONDS
                slot = (int(watch["id"]) * 11) % 30
                if (due_rss or due_search) and (now.minute % 30) >= slot:
                    check_mydealz_watch(int(watch["id"]), include_search=due_search)
                    time.sleep(2)
        except Exception:
            log.error("Scheduler-Fehler\n%s", traceback.format_exc())
        time.sleep(SCHEDULER_WAKE_SECONDS)


def keepa_cache_path(asin: str, days: int) -> Path:
    return KEEPa_CACHE_DIR / f"{asin}_{days}.png"


def get_keepa_png(asin: str, days: int) -> tuple[bytes, bool]:
    if days not in {31, 90, 365, 9999}:
        days = 365
    path = keepa_cache_path(asin, days)
    now = time.time()
    if path.exists() and now - path.stat().st_mtime < KEEPa_CACHE_SECONDS:
        return path.read_bytes(), True

    params = urllib.parse.urlencode(
        {
            "asin": asin,
            "domain": "de",
            "amazon": "1",
            "new": "1",
            "used": "1",
            "range": str(days),
            "width": "1000",
            "height": "500",
        }
    )
    url = f"https://graph.keepa.com/pricehistory.png?{params}"
    try:
        body, _, ctype = fetch_url(url, timeout=KEEPa_TIMEOUT_SECONDS, referer="https://keepa.com/")
        if not body.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"Keepa lieferte kein PNG ({ctype}).")
        path.write_bytes(body)
        return body, False
    except Exception:
        if path.exists():
            log.warning("Keepa-Abruf fehlgeschlagen; alter Cache wird verwendet.")
            return path.read_bytes(), True
        raise


def get_product_image(product: sqlite3.Row) -> tuple[bytes, str] | None:
    image_url = product["image_url"]
    if not image_url:
        return None
    suffix = ".img"
    path = IMAGE_CACHE_DIR / f"{product['asin']}{suffix}"
    meta_path = IMAGE_CACHE_DIR / f"{product['asin']}.json"
    if path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            if time.time() - path.stat().st_mtime < 7 * 86400 and meta.get("url") == image_url:
                return path.read_bytes(), meta.get("content_type", "image/jpeg")
        except Exception:
            pass
    try:
        body, _, ctype = fetch_url(image_url, timeout=15, referer=product["amazon_url"])
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"
        if body:
            path.write_bytes(body)
            meta_path.write_text(json.dumps({"url": image_url, "content_type": ctype}), "utf-8")
            return body, ctype
    except Exception:
        log.exception("Produktbild konnte nicht geladen werden: %s", product["asin"])
    if path.exists():
        return path.read_bytes(), "image/jpeg"
    return None


INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f172a">
<title>Amazon Preiswächter</title>
<style>
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#6b7280;--line:#e5eaf1;--amazon:#ff8a00;--used:#c026d3;--idealo:#0077ff;--mydealz:#df0045;--accent:#2563eb;--good:#059669;--bad:#dc2626;--warn:#d97706;--shadow:0 7px 22px rgba(15,23,42,.07)}
@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--card:#111a2b;--text:#edf2f7;--muted:#9ba8bb;--line:#23304a;--amazon:#ffb020;--used:#f472d0;--idealo:#22b8ff;--mydealz:#fb7185;--accent:#60a5fa;--good:#34d399;--bad:#fb7185;--warn:#fbbf24;--shadow:0 10px 28px rgba(0,0,0,.25)}}
*{box-sizing:border-box}html,body{margin:0;width:100%;max-width:100%;overflow-x:hidden}body{background:var(--bg);color:var(--text);font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}button,input,select{font:inherit;max-width:100%}a{color:inherit}.wrap{width:100%;max-width:1260px;margin:auto;padding:14px}.top{display:flex;align-items:center;gap:11px;margin-bottom:11px}.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(145deg,var(--amazon),#ffc266);display:grid;place-items:center;color:#111;font-size:22px;box-shadow:var(--shadow)}h1{font-size:23px;margin:0}.sub{color:var(--muted);font-size:11px}.addbox{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:9px;box-shadow:var(--shadow);margin-bottom:9px}.modebar{display:flex;gap:6px;margin-bottom:7px}.modebtn{flex:1;border:1px solid var(--line);border-radius:9px;background:transparent;color:var(--muted);padding:7px;font-weight:800;cursor:pointer}.modebtn.active{background:var(--line);color:var(--text)}.addbar{display:flex;gap:8px}.addbar input{flex:1;min-width:0;background:transparent;border:1px solid var(--line);border-radius:10px;padding:10px 12px;color:var(--text);outline:none}.btn{border:0;border-radius:10px;padding:9px 13px;font-weight:750;cursor:pointer}.btn:disabled{opacity:.55}.btn.primary{background:var(--amazon);color:#201404}.btn.secondary{background:var(--line);color:var(--text)}.btn.idealo{background:color-mix(in srgb,var(--idealo) 15%,var(--card));color:var(--idealo);border:1px solid color-mix(in srgb,var(--idealo) 25%,var(--line))}.btn.mydealz{background:color-mix(in srgb,var(--mydealz) 12%,var(--card));color:var(--mydealz);border:1px solid color-mix(in srgb,var(--mydealz) 22%,var(--line))}.btn.danger{background:#fee2e2;color:#991b1b}.controls{display:flex;align-items:center;justify-content:flex-end;gap:7px;margin:0 0 9px;flex-wrap:wrap}.refresh-status{display:none;color:var(--muted);font-size:10px;margin:-3px 0 9px}.refresh-status.show{display:block}.gemini-usage{color:var(--muted);font-size:10px;margin:-2px 0 9px}.gemini-usage b{color:var(--text)}.sort{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:7px 9px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:9px}.card{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:9px;box-shadow:var(--shadow);cursor:pointer;transition:.14s transform,.14s border-color}.card:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--accent) 38%,var(--line))}.product-head{display:grid;grid-template-columns:50px minmax(0,1fr) auto;gap:8px;align-items:start}.product-img,.watch-icon{width:50px;height:50px;border-radius:9px;border:1px solid var(--line);background:#fff;object-fit:contain}.watch-icon{display:grid;place-items:center;background:color-mix(in srgb,var(--mydealz) 12%,var(--card));font-size:25px}.title{font-weight:780;line-height:1.22;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.asin{color:var(--muted);font-size:10px;margin-top:2px}.status{display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:750;white-space:nowrap}.dot{width:7px;height:7px;border-radius:50%;background:var(--good)}.dot.pause{background:var(--muted)}
.prices{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;margin-top:7px}.sourcebox{border:1px solid var(--line);border-radius:10px;padding:6px 6px;min-width:0}.sourcebox.amazon{border-top:3px solid var(--amazon)}.sourcebox.used{border-top:3px solid var(--used)}.sourcebox.idealo{border-top:3px solid var(--idealo)}.sourcebox.mydealz{border-top:3px solid var(--mydealz)}.sourcebox.best{background:color-mix(in srgb,var(--good) 13%,var(--card));border-color:color-mix(in srgb,var(--good) 42%,var(--line))}.sourcebox.linked{cursor:pointer}.source-label{font-size:7px;text-transform:uppercase;letter-spacing:.02em;color:var(--muted);font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.source-price{font-size:14px;font-weight:900;line-height:1.12;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.source-meta{font-size:7px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin-top:6px}.mini{min-width:0;border-top:1px solid var(--line);padding-top:5px}.mini-label{font-size:7px;color:var(--muted);line-height:1.1}.mini-value{font-size:9px;font-weight:750;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.delta.good{color:var(--good)}.delta.bad{color:var(--bad)}.delta.flat{color:var(--muted)}.error{color:var(--bad);font-size:9px;margin-top:4px}.empty{background:var(--card);border:1px dashed var(--line);border-radius:15px;padding:30px;text-align:center;color:var(--muted)}
.watch-deals{display:grid;gap:5px;margin-top:8px}.watch-deal{border:1px solid color-mix(in srgb,var(--mydealz) 25%,var(--line));border-radius:9px;padding:7px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;background:color-mix(in srgb,var(--mydealz) 5%,var(--card))}.watch-deal.ended{opacity:.52}.watch-deal-title{font-size:10px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.watch-deal-meta{font-size:8px;color:var(--muted)}.watch-deal-price{color:var(--mydealz);font-weight:900;white-space:nowrap}.watch-search-link{display:inline-flex;align-items:center;gap:4px;margin-top:7px;color:var(--mydealz);font-size:9px;font-weight:800;text-decoration:none}.watch-search-link:hover{text-decoration:underline}.watch-foot{display:flex;justify-content:space-between;color:var(--muted);font-size:8px;margin-top:7px;gap:8px}
.overlay{position:fixed;inset:0;background:rgba(4,9,20,.68);display:none;z-index:100;padding:14px;overflow:auto}.overlay.show{display:block}.panel{width:100%;max-width:980px;margin:0 auto;background:var(--bg);border-radius:20px;min-height:min(92vh,820px);overflow:hidden}.panelbar{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--card) 95%,transparent);backdrop-filter:blur(16px);padding:12px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}.panelbody{padding:14px}.close{width:36px;height:36px;border:0;border-radius:11px;background:var(--line);color:var(--text);font-size:21px}.hero{display:grid;grid-template-columns:100px minmax(0,1fr);gap:14px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px}.hero img{width:100px;height:100px;object-fit:contain;background:#fff;border-radius:12px}.hero h2{margin:0 0 5px;font-size:20px}.section{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:13px;margin-top:10px}.section h3{margin:0 0 10px;font-size:14px}.settings{display:grid;grid-template-columns:1fr 1fr;gap:8px}.setting-caption{grid-column:1/-1;color:var(--muted);font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.04em;margin-top:3px}.field,.switchrow{border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-width:0}.field{display:grid;gap:5px}.field span,.switchrow span{font-size:10px}.field input{width:100%;border:0;background:transparent;color:var(--text);outline:none}.switchrow{display:flex;align-items:center;justify-content:space-between;gap:10px}.detail-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:10px}.detail-actions .btn{width:100%;height:42px;padding:6px;font-size:10px;line-height:1.15}.note{color:var(--muted);font-size:9px;margin-top:8px}.warning{color:var(--warn);font-size:10px;margin-top:8px}.stats4{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.stat{border:1px solid var(--line);border-radius:10px;padding:8px}.stat .l{font-size:8px;color:var(--muted)}.stat .v{font-size:15px;font-weight:900}.toolbar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.pill{border:1px solid var(--line);background:transparent;color:var(--text);border-radius:999px;padding:6px 9px;font-size:9px;cursor:pointer}.pill.active{background:var(--line);font-weight:800}.pill.amazon.active{border-color:var(--amazon)}.pill.used.active{border-color:var(--used)}.pill.idealo.active{border-color:var(--idealo)}.graphwrap{position:relative;height:300px;border:1px solid var(--line);border-radius:12px;overflow:hidden}.graphwrap svg{width:100%;height:100%}.tooltip{position:absolute;display:none;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:9px;padding:7px;font-size:9px;box-shadow:var(--shadow);transform:translate(-50%,-110%);z-index:3}.keepa{width:100%;border:1px solid var(--line);border-radius:12px;background:#fff;cursor:zoom-in}.deals{display:grid;gap:6px}.deal{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;border:1px solid var(--line);border-radius:10px;padding:8px}.deal.ended{opacity:.5}.deal-title{font-weight:800;font-size:11px}.deal-meta{font-size:9px;color:var(--muted)}.deal-price{color:var(--mydealz);font-weight:900;text-decoration:none}.fullimg{position:fixed;inset:0;background:rgba(0,0,0,.86);display:none;z-index:200;align-items:center;justify-content:center;padding:10px}.fullimg.show{display:flex}.fullimg img{max-width:98vw;max-height:94vh}.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(20px);background:#111827;color:#fff;padding:10px 14px;border-radius:11px;opacity:0;pointer-events:none;transition:.2s;z-index:300;max-width:90vw}.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@media(max-width:760px){.wrap{padding:8px}.top{align-items:flex-start}.top h1{font-size:20px}.addbar{flex-direction:column}.controls{display:grid;grid-template-columns:1fr}.controls>*{width:100%}.grid{grid-template-columns:minmax(0,1fr)}.card{padding:8px}.product-head{grid-template-columns:44px minmax(0,1fr) auto}.product-img,.watch-icon{width:44px;height:44px}.prices{gap:3px}.sourcebox{padding:5px 3px}.source-price{font-size:12px}.source-label,.source-meta{font-size:6.5px}.card-stats{gap:3px}.mini-label{font-size:6.5px}.mini-value{font-size:8.5px}.overlay{padding:0}.panel{min-height:100vh;border-radius:0}.panelbody{padding:8px}.hero{grid-template-columns:70px minmax(0,1fr);padding:10px}.hero img{width:70px;height:70px}.hero h2{font-size:16px}.settings{grid-template-columns:1fr}.setting-caption{grid-column:1}.detail-actions{grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}.detail-actions .btn{font-size:9px;height:46px}.stats4{grid-template-columns:1fr 1fr}.graphwrap{height:245px}.watch-foot{display:grid;grid-template-columns:1fr;gap:2px}}

/* 0.1.32: eigenständige Produkt-/Preisradar-Optik */
:root{
  --bg:#f6f2eb;--card:#fffdfa;--text:#241c17;--muted:#786b61;--line:#ded5ca;
  --shadow:0 8px 24px rgba(74,52,35,.08)
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#15110e;--card:#211a15;--text:#fff7ed;--muted:#b7a596;--line:#3b2f27;
    --shadow:0 10px 28px rgba(0,0,0,.30)
  }
}
body{
  background:
    radial-gradient(circle at 8% -8%,color-mix(in srgb,var(--amazon) 12%,transparent),transparent 27%),
    var(--bg)
}
.wrap{max-width:1380px;padding:18px 16px 36px}
.top{padding:2px 2px 12px;border-bottom:2px dashed color-mix(in srgb,var(--amazon) 30%,var(--line));margin-bottom:13px}
.logo{width:48px;height:48px;border-radius:50%;background:var(--amazon);box-shadow:none;font-size:24px;font-weight:950;color:#241300}
.top h1{font-size:26px;letter-spacing:-.55px}
.addbox{border:2px solid color-mix(in srgb,var(--amazon) 28%,var(--line));border-radius:11px;padding:10px;box-shadow:none;background:color-mix(in srgb,var(--amazon) 3%,var(--card))}
.modebar{max-width:520px}.modebtn{border-radius:6px}.modebtn.active{background:color-mix(in srgb,var(--amazon) 14%,var(--card));border-color:color-mix(in srgb,var(--amazon) 45%,var(--line));color:var(--text)}
.addbar input{border-radius:6px;background:var(--card);border-width:1px}.btn{border-radius:6px}.sort{border-radius:6px}
.controls{padding:2px 0 1px;border-bottom:1px solid color-mix(in srgb,var(--line) 76%,transparent);padding-bottom:9px}
.grid{grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px}
.card{position:relative;border-radius:10px;padding:12px 12px 10px;box-shadow:var(--shadow);overflow:hidden;border-color:var(--line);transition:.14s transform,.14s box-shadow,.14s border-color}
.card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,var(--amazon),var(--idealo),var(--mydealz));opacity:.78}
.card:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(0,0,0,.14)}
.product-head{grid-template-columns:72px minmax(0,1fr) auto;gap:11px;align-items:center}
.product-img,.watch-icon{width:72px;height:72px;border-radius:8px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.04)}
.watch-icon{font-size:32px}
.title{font-size:14px;line-height:1.28}.asin{font-size:9px}.status{font-size:9px}
.prices{gap:6px;margin-top:11px}.sourcebox{border-radius:7px;padding:8px 7px;border:0!important;background:color-mix(in srgb,var(--line) 23%,var(--card));box-shadow:inset 0 0 0 1px var(--line)}
.sourcebox.amazon{box-shadow:inset 3px 0 0 var(--amazon),inset 0 0 0 1px var(--line)}
.sourcebox.used{box-shadow:inset 3px 0 0 var(--used),inset 0 0 0 1px var(--line)}
.sourcebox.idealo{box-shadow:inset 3px 0 0 var(--idealo),inset 0 0 0 1px var(--line)}
.sourcebox.mydealz{box-shadow:inset 3px 0 0 var(--mydealz),inset 0 0 0 1px var(--line)}
.sourcebox.best{background:color-mix(in srgb,var(--good) 12%,var(--card));box-shadow:inset 3px 0 0 var(--good),inset 0 0 0 1px color-mix(in srgb,var(--good) 38%,var(--line))}
.source-label{font-size:7.5px}.source-price{font-size:16px;letter-spacing:-.25px}.source-meta{font-size:7.5px}
.card-stats{gap:7px;margin-top:9px;padding-top:8px;border-top:1px dashed var(--line)}.mini{border-top:0;padding-top:0}.mini-label{font-size:7.5px}.mini-value{font-size:9.5px}
.watch-deals{border-top:1px dashed var(--line);padding-top:8px}.watch-deal{border-radius:6px}
.panel{border-radius:12px}.panelbar{background:color-mix(in srgb,var(--card) 96%,transparent)}.hero,.section{border-radius:9px}.field,.switchrow,.stat,.deal{border-radius:6px}.close{border-radius:6px}.pill{border-radius:999px}
@media(max-width:760px){
  .wrap{padding:10px 8px 28px}.top{padding-bottom:9px}.logo{width:42px;height:42px}.top h1{font-size:21px}
  .grid{grid-template-columns:1fr;gap:9px}.card{padding:9px 9px 8px}.card:before{width:3px}
  .product-head{grid-template-columns:56px minmax(0,1fr) auto;gap:8px}.product-img,.watch-icon{width:56px;height:56px}
  .prices{grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.sourcebox{padding:7px 7px}.source-price{font-size:15px}
  .card-stats{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:6px}.mini{min-width:0}
  .modebar{max-width:none}.controls{display:grid;grid-template-columns:1fr}.controls>*{width:100%}
}

</style>
</head>
<body>
<div class="wrap">
  <div class="top"><div class="logo">€</div><div><h1>Amazon Preiswächter</h1><div class="sub">Amazon · Gebraucht · Idealo · MyDealz · Version 0.1.53 · Port 8100</div></div></div>
  <div class="addbox">
    <div class="modebar"><button id="modeAmazon" class="modebtn active" type="button" onclick="setAddMode('amazon')">Amazon-Artikel</button><button id="modeWatch" class="modebtn" type="button" onclick="setAddMode('watch')">MyDealz-Beobachtung</button></div>
    <form class="addbar" id="addForm"><input id="addInput" autocomplete="off" placeholder="Amazon-Link einfügen, z. B. https://amzn.eu/..."><button id="addBtn" class="btn primary" type="submit">Artikel hinzufügen</button></form>
  </div>
  <div class="controls"><button id="rematchMissingBtn" class="btn idealo" type="button" onclick="rematchMissingIdealo()" style="display:none">Idealo-Zuordnungen suchen</button><button id="refreshAllBtn" class="btn secondary" type="button" onclick="refreshAll()">↻ Alle Preise aktualisieren</button><select id="sortSelect" class="sort" onchange="renderGrid()"><option value="new">Sortierung: zuletzt hinzugefügt</option><option value="saving">größte Idealo-Ersparnis</option><option value="drop">stärkste Preissenkung</option><option value="wish">Wunschpreis fast erreicht</option></select></div>
  <div id="refreshStatus" class="refresh-status"></div>
  <div id="geminiUsage" class="gemini-usage">Google-Suchen: lade …</div>
  <div id="grid" class="grid"></div>
</div>
<div id="overlay" class="overlay"><div class="panel"><div class="panelbar"><strong id="panelTitle">Details</strong><button class="close" onclick="closeDetail()">×</button></div><div id="detail" class="panelbody"></div></div></div>
<div id="fullimg" class="fullimg" onclick="this.classList.remove('show')"><img id="fullimgEl" alt="Keepa Preisverlauf"></div>
<div id="toast" class="toast"></div>
<script>
let products=[],watches=[],geminiUsage=null,graphData=null,graphShow={amazon:true,used:true,idealo:true},addMode="amazon";
const money=v=>v==null?"—":new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR"}).format(v);
const signedMoney=v=>v==null?"—":((v>0?"+":v<0?"−":"±")+money(Math.abs(v)));
const dt=v=>v?new Intl.DateTimeFormat("de-DE",{dateStyle:"short",timeStyle:"short"}).format(new Date(v)):"—";
const shortDate=v=>v?new Intl.DateTimeFormat("de-DE",{dateStyle:"short"}).format(new Date(v)):"—";
const age=v=>{if(!v)return"—";const s=Math.max(0,(Date.now()-new Date(v).getTime())/1000);if(s<90)return"gerade";if(s<3600)return`vor ${Math.round(s/60)} Min.`;if(s<86400)return`vor ${Math.round(s/3600)} Std.`;return`vor ${Math.round(s/86400)} Tg.`};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
function toast(msg){const e=document.getElementById("toast");e.textContent=msg;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),3500)}
async function api(path,opts={}){const r=await fetch(path,{headers:{"Content-Type":"application/json",...(opts.headers||{})},...opts});let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);return j}
function openLink(url,e){if(e){e.preventDefault();e.stopPropagation()}if(url)window.open(url,"_blank","noopener")}
function notifyText(p){return p.notify_targets?.length?p.notify_targets.join(" + "):"keine"}
function deltaClass(v){return v==null||v===0?"flat":v<0?"good":"bad"}
function setAddMode(mode){addMode=mode;document.getElementById("modeAmazon").classList.toggle("active",mode==="amazon");document.getElementById("modeWatch").classList.toggle("active",mode==="watch");const i=document.getElementById("addInput"),b=document.getElementById("addBtn");if(mode==="amazon"){i.placeholder="Amazon-Link einfügen, z. B. https://amzn.eu/...";b.textContent="Artikel hinzufügen";b.className="btn primary"}else{i.placeholder="MyDealz-Suchbegriff, z. B. Zewa Smart oder EDEKA PAYBACK";b.textContent="Beobachtung hinzufügen";b.className="btn mydealz"}i.focus()}
function sourceBox(label,price,url,meta,kind,best=false){const linked=!!url;return`<div class="sourcebox ${kind}${best?" best":""}${linked?" linked":""}"${linked?` role="link" tabindex="0" onclick="openLink('${esc(url)}',event)"`:""}><div class="source-label">${label}</div><div class="source-price">${money(price)}</div><div class="source-meta">${esc(meta||"—")}</div></div>`}
function idealoStatusText(p){if(!p.idealo_url)return"Zuordnung fehlt";const state=p.idealo_current_price!=null?"aktuell":(p.idealo_last_known_price!=null?"veraltet":"Preis fehlt");const success=p.idealo_last_success?`Erfolg ${age(p.idealo_last_success)}`:"kein Erfolg";const checked=p.idealo_last_checked?`Linkprüfung ${age(p.idealo_last_checked)}`:"noch keine Linkprüfung";return`${state} · ${success} · ${checked}${p.idealo_last_error?" · Fehler":""}`}
function marketPriceBoxes(p){const best=p.card_best_new_source||"";const usedMeta=p.used_available?age(p.used_last_success):"nicht verfügbar";const mdMeta=p.mydealz_best_url?age(p.mydealz_last_success):"kein Deal";return`<div class="prices">${sourceBox("Amazon Neu",p.current_price,p.amazon_url,age(p.last_success),"amazon",best==="amazon")}${sourceBox("Amazon Gebr.",p.used_current_price,p.used_offer_url,usedMeta,"used",false)}${sourceBox("Idealo",p.idealo_current_price,p.idealo_url,idealoStatusText(p),"idealo",best==="idealo")}${sourceBox("MyDealz",p.mydealz_best_price,p.mydealz_best_url,mdMeta,"mydealz",best==="mydealz")}</div>`}
function renderProductCard(p){return`<article class="card" onclick="openProductDetail(${p.id})"><div class="product-head"><img class="product-img" src="api/products/${p.id}/image" onerror="this.style.visibility='hidden'"><div><div class="title">${esc(p.custom_name||p.title||p.asin)}</div><div class="asin">ASIN ${esc(p.asin)} · seit ${shortDate(p.created_at)}</div></div><div class="status"><span class="dot ${p.active?"":"pause"}"></span>${p.active?"aktiv":"pausiert"}</div></div>${marketPriceBoxes(p)}<div class="card-stats"><div class="mini"><div class="mini-label">Seit Start Amazon</div><div class="mini-value delta ${deltaClass(p.amazon_change_since_start)}">${signedMoney(p.amazon_change_since_start)}</div></div><div class="mini"><div class="mini-label">Seit Start Idealo</div><div class="mini-value delta ${deltaClass(p.idealo_change_since_start)}">${signedMoney(p.idealo_change_since_start)}</div></div><div class="mini"><div class="mini-label">Wunschpreis</div><div class="mini-value">${money(p.wish_price)}</div></div><div class="mini"><div class="mini-label">Benachrichtigung</div><div class="mini-value">🔔 ${esc(notifyText(p))}</div></div></div>${p.last_error?`<div class="error">Amazon: ${esc(p.last_error)}</div>`:""}${p.idealo_last_error?`<div class="error">Idealo: ${esc(p.idealo_last_error)}</div>`:""}</article>`}
function renderWatchCard(w){const deals=(w.active_deal_items||w.deals||[]).filter(d=>d.active).slice(0,3);const list=deals.length?`<div class="watch-deals">${deals.map(d=>`<div class="watch-deal" onclick="openLink('${esc(d.url)}',event)"><div><div class="watch-deal-title">${esc(d.title)}</div><div class="watch-deal-meta">aktiv${d.merchant?" · "+esc(d.merchant):""}${d.published_at?" · "+dt(d.published_at):""}</div></div><div class="watch-deal-price">${money(d.price)}</div></div>`).join("")}</div>`:`<div class="empty" style="padding:12px;margin-top:8px">Noch kein aktiver passender Deal</div>`;const search=w.search_url?`<a class="watch-search-link" href="${esc(w.search_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">↗ Alle Treffer auf MyDealz anzeigen</a>`:"";return`<article class="card" onclick="openWatchDetail(${w.id})"><div class="product-head"><div class="watch-icon">🔥</div><div><div class="title">${esc(w.name)}</div><div class="asin">MyDealz-Beobachtung · ${esc(w.query)}</div></div><div class="status"><span class="dot ${w.active?"":"pause"}"></span>${w.active?"aktiv":"pausiert"}</div></div>${list}${search}<div class="watch-foot"><span>🔔 ${esc(notifyText(w))}</span><span>${w.active_deals||0} aktiv · RSS ${age(w.last_checked)} · Suche ${age(w.last_search_checked)}</span></div>${w.last_error?`<div class="error">${esc(w.last_error)}</div>`:""}</article>`}
function sortedItems(){const mode=document.getElementById("sortSelect").value;const ps=[...products];const num=(v,f=999999)=>v==null?f:v;if(mode==="saving")ps.sort((a,b)=>num(b.savings_vs_amazon,-999999)-num(a.savings_vs_amazon,-999999));else if(mode==="drop")ps.sort((a,b)=>Math.min(num(a.amazon_change_since_start,999999),num(a.idealo_change_since_start,999999))-Math.min(num(b.amazon_change_since_start,999999),num(b.idealo_change_since_start,999999)));else if(mode==="wish")ps.sort((a,b)=>Math.abs(num(a.best_price,999999)-num(a.wish_price,0))-Math.abs(num(b.best_price,999999)-num(b.wish_price,0)));if(mode!=="new")return[...ps,...watches];return[...ps,...watches].sort((a,b)=>new Date(b.created_at)-new Date(a.created_at))}
function renderGrid(){const g=document.getElementById("grid"),items=sortedItems();if(!items.length){g.innerHTML=`<div class="empty">Noch keine Beobachtungen. Oben kannst du einen Amazon-Link oder eine reine MyDealz-Suche anlegen.</div>`;return}g.innerHTML=items.map(x=>x.type==="mydealz_watch"?renderWatchCard(x):renderProductCard(x)).join("")}
function renderGeminiUsage(){const e=document.getElementById("geminiUsage");if(!geminiUsage){e.textContent="Google-Suchen: keine Statistik";return}const q=geminiUsage.google_search_queries||0,m=geminiUsage.idealo_mapping_attempts||0,l=geminiUsage.shared_free_monthly_limit||5000,r=geminiUsage.idealo_url_context_requests_today||0,s=geminiUsage.idealo_schedule_label||"täglich um 12:00 Uhr";e.innerHTML=`Google-Suchen diesen Monat: <b>${q.toLocaleString("de-DE")} / ${l.toLocaleString("de-DE")}</b> · Gemini-Idealo-Zuordnungen: <b>${m}</b> · Linkprüfungen heute: <b>${r}</b> · Automatik: <b>${esc(s)}</b> <span title="Gespeicherte Idealo-Links werden ausschließlich per Gemini URL Context geprüft. Google-Suche läuft nur beim Anlegen oder über „Idealo neu zuordnen“.">ⓘ</span>`}
function updateMissingIdealoButton(){const b=document.getElementById("rematchMissingBtn"),missing=products.filter(p=>p.active&&!p.idealo_url&&!p.idealo_manual);if(!missing.length){b.style.display="none";return}b.style.display="";b.textContent=`Idealo-Zuordnungen suchen (${missing.length})`}
async function load(){const d=await api("api/products");products=d.products||[];watches=d.mydealz_watches||[];geminiUsage=d.gemini_usage||null;renderGeminiUsage();updateMissingIdealoButton();renderGrid()}
async function rematchMissingIdealo(){const missing=products.filter(p=>p.active&&!p.idealo_url&&!p.idealo_manual);if(!missing.length)return toast("Keine fehlenden Idealo-Zuordnungen");if(!confirm(`Für ${missing.length} Artikel werden nacheinander Idealo-Zuordnungen mit Gemini Google Search gesucht. Fortfahren?`))return;const b=document.getElementById("rematchMissingBtn");b.disabled=true;let ok=0,fail=0;for(let i=0;i<missing.length;i++){b.textContent=`Idealo ${i+1}/${missing.length}`;try{const j=await api(`api/products/${missing[i].id}/idealo-rematch`,{method:"POST",body:"{}"});if(j.result?.idealo_ok)ok++;else fail++}catch{fail++}}b.disabled=false;await load();toast(`Idealo-Zuordnung: ${missing.length} geprüft · ${ok} erfolgreich${fail?` · ${fail} ohne Treffer`:""}`)}
let refreshPoll=null,productCheckPolls={};function showRefreshStatus(s){const b=document.getElementById("refreshAllBtn"),e=document.getElementById("refreshStatus");if(s.running){b.disabled=true;b.textContent=`↻ ${s.done||0}/${s.total||"…"} aktualisiert`;e.textContent=s.current_title?`Aktuell: ${s.current_title}`:"Prüfung wird vorbereitet …";e.classList.add("show")}else{b.disabled=false;b.textContent="↻ Alle Preise aktualisieren";if(s.finished_at){e.textContent=`Fertig: ${s.success||0} erfolgreich${s.failed?` · ${s.failed} mit Hinweis/Fehler`:""}`;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),6000)}}}
async function pollRefreshAll(){try{const s=await api("api/products/check-all/status");showRefreshStatus(s);if(s.running)refreshPoll=setTimeout(pollRefreshAll,1200);else{refreshPoll=null;await load()}}catch(e){refreshPoll=null;toast(e.message)}}
async function refreshAll(){const b=document.getElementById("refreshAllBtn");b.disabled=true;b.textContent="↻ Starte …";try{const r=await api("api/products/check-all",{method:"POST",body:"{}"});showRefreshStatus(r.status||{});toast("Amazon, gespeicherte Idealo-Links per Gemini und MyDealz werden aktualisiert");refreshPoll=setTimeout(pollRefreshAll,500)}catch(e){b.disabled=false;toast(e.message)}}
document.getElementById("addForm").addEventListener("submit",async e=>{e.preventDefault();const i=document.getElementById("addInput"),b=document.getElementById("addBtn"),value=i.value.trim();if(!value)return;b.disabled=true;const old=b.textContent;b.textContent="Wird angelegt…";try{if(addMode==="amazon"){const j=await api("api/products",{method:"POST",body:JSON.stringify({url:value})});i.value="";toast(j.existing?"Artikel bereits vorhanden":"Artikel hinzugefügt");await load();openProductDetail(j.product.id)}else{const j=await api("api/mydealz-watches",{method:"POST",body:JSON.stringify({query:value,name:value})});i.value="";toast("MyDealz-Beobachtung angelegt");await load();openWatchDetail(j.watch.id)}}catch(err){toast(err.message)}finally{b.disabled=false;b.textContent=old}});
function closeDetail(){document.getElementById("overlay").classList.remove("show")}
async function openProductDetail(id){document.getElementById("overlay").classList.add("show");document.getElementById("panelTitle").textContent="Artikeldetails";document.getElementById("detail").innerHTML=`<div class="empty">Lade…</div>`;try{const j=await api(`api/products/${id}`);renderProductDetail(j.product)}catch(e){toast(e.message)}}
async function openWatchDetail(id){document.getElementById("overlay").classList.add("show");document.getElementById("panelTitle").textContent="MyDealz-Beobachtung";document.getElementById("detail").innerHTML=`<div class="empty">Lade…</div>`;try{const j=await api(`api/mydealz-watches/${id}`);renderWatchDetail(j.watch)}catch(e){toast(e.message)}}
function renderProductDetail(p){const d=document.getElementById("detail"),iu=p.idealo_url||"";d.innerHTML=`<div class="hero"><img src="api/products/${p.id}/image" onerror="this.style.visibility='hidden'"><div><h2>${esc(p.custom_name||p.title||p.asin)}</h2><div class="asin">ASIN ${esc(p.asin)} · seit ${shortDate(p.created_at)}</div></div></div><div class="section"><h3>Aktuelle Preise</h3>${marketPriceBoxes(p)}</div><div class="section"><h3>Überwachung & Benachrichtigungen</h3><div class="settings"><div class="setting-caption">Allgemein</div><label class="field"><span>Benachrichtigungsname</span><input id="customName" type="text" value="${esc(p.custom_name||"")}" placeholder="z. B. Emils Trinkflasche"></label><label class="field"><span>Wunschpreis in €</span><input id="wish" type="number" min="0" step="0.01" value="${p.wish_price??""}"></label><div class="switchrow"><span>Überwachung aktiv</span><input id="active" type="checkbox" ${p.active?"checked":""}></div><div class="setting-caption">Empfänger</div><div class="switchrow"><span>primary</span><input id="np" type="checkbox" ${p.notify_primary?"checked":""}></div><div class="switchrow"><span>secondary</span><input id="nk" type="checkbox" ${p.notify_secondary?"checked":""}></div><div class="setting-caption">Preisalarme</div><div class="switchrow"><span>Push bei Wunschpreis</span><input id="nw" type="checkbox" ${p.notify_wish?"checked":""}></div><div class="switchrow"><span>Push bei jeder Preisänderung</span><input id="npc" type="checkbox" ${p.notify_price_change?"checked":""}></div><label class="field"><span>Mindeständerung in €</span><input id="pct" type="number" min="0" step="0.01" value="${p.price_change_threshold??2}"></label><div class="switchrow"><span>Push, wenn Gebraucht neu verfügbar</span><input id="nua" type="checkbox" ${p.notify_used_available?"checked":""}></div><div class="setting-caption">Idealo</div><div class="hint">Status: ${esc(idealoStatusText(p))}<br>Letzte Idealo-Prüfung: ${esc(p.idealo_last_checked||"noch nie")}<br>Letzter Erfolg: ${esc(p.idealo_last_success||"noch nie")}<br>Gemini-Prüfung: ${esc(p.idealo_gemini_last_checked||"noch nie")}</div><label class="field" style="grid-column:1/-1"><span>Idealo-Produktlink</span><input id="iurl" type="url" value="${esc(iu)}" placeholder="https://www.idealo.de/preisvergleich/OffersOfProduct/..."></label><div class="setting-caption">MyDealz</div><label class="field" style="grid-column:1/-1"><span>MyDealz-Suchbegriffe (leer = automatisch)</span><input id="mq" type="text" value="${esc(p.mydealz_query||"")}" placeholder="${esc(p.mydealz_query_effective||"")}"></label></div>${!p.idealo_url?`<div class="warning">Idealo-Zuordnung fehlt. Eine Suche erfolgt nur beim Anlegen oder über „Idealo neu zuordnen“.</div>`:""}<div class="detail-actions"><button class="btn secondary" onclick="checkNow(${p.id},this)">Alles jetzt prüfen</button><button class="btn primary" onclick="saveProductSettings(${p.id})">Speichern & schließen</button><button class="btn idealo" onclick="rematchIdealo(${p.id},this)">Idealo neu zuordnen</button></div></div><div class="section"><h3>Tiefpreise seit Beginn der Überwachung</h3><div class="stats4"><div class="stat"><div class="l">Amazon Neu</div><div class="v">${money(p.low_price)}</div></div><div class="stat"><div class="l">Amazon Gebraucht</div><div class="v">${money(p.used_low_price)}</div></div><div class="stat"><div class="l">Idealo</div><div class="v">${money(p.idealo_low_price)}</div></div><div class="stat"><div class="l">Bester Neu-Preis</div><div class="v">${money(p.absolute_low_price)}</div></div></div></div><div class="section"><h3>Eigene Preisaufzeichnung</h3><div class="toolbar" id="histBtns">${[["7","1 Woche"],["31","1 Monat"],["90","3 Monate"],["365","1 Jahr"],["9999","Gesamt"]].map((x,i)=>`<button class="pill ${i===1?"active":""}" onclick="historyRange(${p.id},${x[0]},this)">${x[1]}</button>`).join("")}</div><div class="toolbar"><button class="pill amazon active" onclick="toggleGraph('amazon',this)">Amazon Neu ✓</button><button class="pill used active" onclick="toggleGraph('used',this)">Gebraucht ✓</button><button class="pill idealo active" onclick="toggleGraph('idealo',this)">Idealo ✓</button></div><div class="graphwrap"><svg id="graph" viewBox="0 0 900 300" preserveAspectRatio="none"></svg><div id="tip" class="tooltip"></div></div></div><div class="section"><h3>Historischer Keepa-Preisverlauf</h3><div class="toolbar" id="keepaBtns">${[["31","1 Monat"],["90","3 Monate"],["365","1 Jahr"],["9999","Gesamt"]].map((x,i)=>`<button class="pill ${i===2?"active":""}" onclick="keepaRange(${p.id},${x[0]},this)">${x[1]}</button>`).join("")}</div><img id="keepa" class="keepa" src="api/products/${p.id}/keepa/365?t=${Date.now()}" onclick="zoomKeepa(this.src)"></div><div class="section"><button class="btn danger" onclick="deleteProduct(${p.id})">Artikel und gesamte Historie löschen</button></div>`;graphShow={amazon:true,used:true,idealo:true};historyRange(p.id,31,null)}
function renderWatchDetail(w){const d=document.getElementById("detail"),active=w.active_deal_items||[],ended=w.ended_deal_items||[];const renderDeals=(items,empty)=>items.length?`<div class="deals">${items.map(x=>`<div class="deal ${x.active?"":"ended"}"><div><div class="deal-title">${esc(x.title)}</div><div class="deal-meta">${x.active?"aktiv":"beendet"}${x.merchant?" · "+esc(x.merchant):""}${x.published_at?" · "+dt(x.published_at):""}</div></div><a class="deal-price" href="${esc(x.url)}" target="_blank" rel="noopener">${money(x.price)}</a></div>`).join("")}</div>`:`<div class="note">${empty}</div>`;d.innerHTML=`<div class="hero"><div class="watch-icon" style="width:100px;height:100px;font-size:45px">🔥</div><div><h2>${esc(w.name)}</h2><div class="asin">Reine MyDealz-Beobachtung · seit ${shortDate(w.created_at)}</div></div></div><div class="section"><h3>Beobachtung</h3><div class="settings"><label class="field"><span>Name</span><input id="wname" value="${esc(w.name)}"></label><label class="field"><span>Suchbegriffe</span><input id="wquery" value="${esc(w.query)}"></label><label class="field" style="grid-column:1/-1"><span>Ausschließen (optional, Komma getrennt)</span><input id="wexclude" value="${esc(w.exclude_terms||"")}" placeholder="z. B. Kreditkarte, Gutschein"></label><div class="switchrow"><span>Überwachung aktiv</span><input id="wactive" type="checkbox" ${w.active?"checked":""}></div><div></div><div class="setting-caption">Empfänger</div><div class="switchrow"><span>primary</span><input id="wnp" type="checkbox" ${w.notify_primary?"checked":""}></div><div class="switchrow"><span>secondary</span><input id="wnk" type="checkbox" ${w.notify_secondary?"checked":""}></div></div><div class="detail-actions" style="grid-template-columns:1fr 1fr"><button class="btn mydealz" onclick="checkWatch(${w.id},this)">MyDealz jetzt prüfen</button><button class="btn primary" onclick="saveWatch(${w.id})">Speichern & schließen</button></div>${w.search_url?`<a class="watch-search-link" href="${esc(w.search_url)}" target="_blank" rel="noopener">↗ MyDealz-Suche „${esc(w.query)}“ öffnen</a>`:""}<div class="note">RSS wird etwa alle 30 Minuten geprüft, die öffentliche MyDealz-Suche stündlich. Alle gespeicherten aktiven Deals werden bei der Prüfung direkt auf ihren aktuellen MyDealz-Status kontrolliert. Neue Deal-IDs lösen genau einmal eine Push-Benachrichtigung aus.</div></div><div class="section"><h3>Aktuelle Deals (${w.active_deals||0})</h3>${renderDeals(active,"Noch kein aktiver passender Deal gespeichert.")}</div><div class="section"><h3>Beendete Deals (${w.ended_deals||0})</h3>${renderDeals(ended,"Noch keine beendeten Deals gespeichert.")}</div><div class="section"><button class="btn danger" onclick="deleteWatch(${w.id})">MyDealz-Beobachtung löschen</button></div>`}
async function saveProductSettings(id){let wish=document.getElementById("wish").value;wish=wish===""?null:Number(wish);try{await api(`api/products/${id}`,{method:"PATCH",body:JSON.stringify({custom_name:document.getElementById("customName")?.value.trim()||"",wish_price:wish,active:document.getElementById("active").checked,notify_primary:document.getElementById("np").checked,notify_secondary:document.getElementById("nk").checked,notify_wish:document.getElementById("nw").checked,notify_price_change:document.getElementById("npc").checked,price_change_threshold:Number(document.getElementById("pct").value||0),notify_used_available:document.getElementById("nua").checked,idealo_url:document.getElementById("iurl").value.trim(),mydealz_query:document.getElementById("mq").value.trim()})});toast("Einstellungen gespeichert");closeDetail();await load()}catch(e){toast(e.message)}}
async function saveWatch(id){try{await api(`api/mydealz-watches/${id}`,{method:"PATCH",body:JSON.stringify({name:document.getElementById("wname").value,query:document.getElementById("wquery").value,exclude_terms:document.getElementById("wexclude").value,active:document.getElementById("wactive").checked,notify_primary:document.getElementById("wnp").checked,notify_secondary:document.getElementById("wnk").checked})});toast("Beobachtung gespeichert");closeDetail();await load()}catch(e){toast(e.message)}}
async function pollProductCheck(id){const job=productCheckPolls[id];if(!job)return;try{const j=await api(`api/products/${id}/check/status`),s=j.status||{};if(s.running){job.btn.textContent=job.mode==="rematch"?"Suche läuft…":"Prüfung läuft…";setTimeout(()=>pollProductCheck(id),1000);return}job.btn.disabled=false;job.btn.textContent=job.old;delete productCheckPolls[id];const p=(await api(`api/products/${id}`)).product;renderProductDetail(p);await load();toast(s.ok?(job.mode==="rematch"?"Idealo neu zugeordnet":"Amazon, gespeicherter Idealo-Link per Gemini und MyDealz aktualisiert"):(s.error||"Prüfung mit Hinweis beendet"))}catch(e){job.btn.disabled=false;job.btn.textContent=job.old;delete productCheckPolls[id];toast(e.message)}}
async function startProductCheck(id,btn,mode){if(productCheckPolls[id])return;const old=btn.textContent;btn.disabled=true;btn.textContent=mode==="rematch"?"Suche startet…":"Prüfung startet…";try{const endpoint=mode==="rematch"?`api/products/${id}/idealo-rematch`:`api/products/${id}/check`;const j=await api(endpoint,{method:"POST",body:"{}"});productCheckPolls[id]={btn,old,mode};if(j.status?.running)setTimeout(()=>pollProductCheck(id),500);else pollProductCheck(id)}catch(e){btn.disabled=false;btn.textContent=old;toast(e.message)}}
function checkNow(id,btn){startProductCheck(id,btn,"full")}
function rematchIdealo(id,btn){startProductCheck(id,btn,"rematch")}
async function checkWatch(id,btn){btn.disabled=true;const old=btn.textContent;btn.textContent="Prüfe…";try{const j=await api(`api/mydealz-watches/${id}/check`,{method:"POST",body:"{}"});toast(j.result.ok?"MyDealz-Beobachtung aktualisiert":(j.result.error||"Prüfung fehlgeschlagen"));renderWatchDetail(j.result.watch);await load()}catch(e){toast(e.message)}finally{btn.disabled=false;btn.textContent=old}}
async function deleteProduct(id){if(!confirm("Artikel und gesamte Historie wirklich löschen?"))return;await api(`api/products/${id}`,{method:"DELETE"});closeDetail();await load();toast("Artikel gelöscht")}
async function deleteWatch(id){if(!confirm("MyDealz-Beobachtung und Deal-Historie wirklich löschen?"))return;await api(`api/mydealz-watches/${id}`,{method:"DELETE"});closeDetail();await load();toast("Beobachtung gelöscht")}
async function historyRange(id,days,btn){if(btn){document.querySelectorAll("#histBtns .pill").forEach(x=>x.classList.remove("active"));btn.classList.add("active")}try{graphData=await api(`api/products/${id}/history?days=${days}`);drawGraph()}catch(e){toast(e.message)}}
function toggleGraph(source,btn){graphShow[source]=!graphShow[source];btn.classList.toggle("active",graphShow[source]);const label=source==="amazon"?"Amazon Neu":source==="used"?"Gebraucht":"Idealo";btn.textContent=label+(graphShow[source]?" ✓":"");drawGraph()}
function graphSeries(){if(!graphData)return[];const s=[];if(graphShow.amazon)s.push({name:"Amazon Neu",color:"var(--amazon)",points:graphData.amazon_points||[]});if(graphShow.used)s.push({name:"Amazon Gebraucht",color:"var(--used)",points:graphData.used_points||[]});if(graphShow.idealo)s.push({name:"Idealo",color:"var(--idealo)",points:graphData.idealo_points||[]});return s}
function drawGraph(){const svg=document.getElementById("graph");if(!svg||!graphData)return;svg.innerHTML="";const series=graphSeries(),all=series.flatMap(s=>s.points.map(p=>({...p,name:s.name,color:s.color})));if(!all.length){svg.innerHTML=`<text x="450" y="150" text-anchor="middle" fill="currentColor" opacity=".55" font-size="16">Noch keine Daten</text>`;return}const W=900,H=300,pad={l:58,r:20,t:18,b:38};const vals=all.map(p=>p.price);if(graphData.wish_price!=null)vals.push(graphData.wish_price);let min=Math.min(...vals),max=Math.max(...vals);if(max===min){max+=1;min=Math.max(0,min-1)}const extra=(max-min)*.12;max+=extra;min=Math.max(0,min-extra);let t0=Math.min(...all.map(p=>new Date(p.at).getTime())),t1=Math.max(...all.map(p=>new Date(p.at).getTime()));if(t1===t0)t1=t0+1;const xs=t=>pad.l+(new Date(t).getTime()-t0)*(W-pad.l-pad.r)/(t1-t0),ys=v=>pad.t+(max-v)*(H-pad.t-pad.b)/(max-min);for(let i=0;i<4;i++){const y=pad.t+i*(H-pad.t-pad.b)/3,val=max-i*(max-min)/3;svg.insertAdjacentHTML("beforeend",`<line x1="${pad.l}" y1="${y}" x2="${W-pad.r}" y2="${y}" stroke="currentColor" opacity=".12"/><text x="${pad.l-8}" y="${y+4}" text-anchor="end" fill="currentColor" opacity=".55" font-size="12">${money(val)}</text>`)}if(graphData.wish_price!=null){const y=ys(graphData.wish_price);svg.insertAdjacentHTML("beforeend",`<line x1="${pad.l}" y1="${y}" x2="${W-pad.r}" y2="${y}" stroke="currentColor" opacity=".4" stroke-dasharray="8 7"/>`)}for(const s of series){if(!s.points.length)continue;const path=s.points.map((p,i)=>`${i?"L":"M"} ${xs(p.at)} ${ys(p.price)}`).join(" ");svg.insertAdjacentHTML("beforeend",`<path d="${path}" fill="none" stroke="${s.color}" stroke-width="3" vector-effect="non-scaling-stroke"/>`)}svg.insertAdjacentHTML("beforeend",`<text x="${pad.l}" y="${H-10}" fill="currentColor" opacity=".55" font-size="11">${new Date(t0).toLocaleDateString("de-DE")}</text><text x="${W-pad.r}" y="${H-10}" text-anchor="end" fill="currentColor" opacity=".55" font-size="11">${new Date(t1).toLocaleDateString("de-DE")}</text><rect id="hoverRect" x="${pad.l}" y="${pad.t}" width="${W-pad.l-pad.r}" height="${H-pad.t-pad.b}" fill="transparent"/>`);const r=document.getElementById("hoverRect");r.addEventListener("pointermove",showNearestTip);r.addEventListener("pointerleave",hideTip)}
function showNearestTip(e){const t=document.getElementById("tip"),wrap=t.parentElement,rect=wrap.getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width)),all=graphSeries().flatMap(s=>s.points.map(p=>({...p,name:s.name})));if(!all.length)return;const times=all.map(p=>new Date(p.at).getTime()),minT=Math.min(...times),maxT=Math.max(...times),target=minT+ratio*(maxT-minT);let best=all[0],dist=Math.abs(new Date(best.at)-target);for(const p of all){const x=Math.abs(new Date(p.at)-target);if(x<dist){best=p;dist=x}}t.innerHTML=`<b>${esc(best.name)} · ${money(best.price)}</b><br>${dt(best.at)}${best.shop?`<br>${esc(best.shop)}`:""}`;t.style.left=(e.clientX-rect.left)+"px";t.style.top=(e.clientY-rect.top)+"px";t.style.display="block"}
function hideTip(){const t=document.getElementById("tip");if(t)t.style.display="none"}
function keepaRange(id,days,btn){document.querySelectorAll("#keepaBtns .pill").forEach(x=>x.classList.remove("active"));btn.classList.add("active");document.getElementById("keepa").src=`api/products/${id}/keepa/${days}?t=${Date.now()}`}
function zoomKeepa(src){document.getElementById("fullimgEl").src=src;document.getElementById("fullimg").classList.add("show")}
document.getElementById("overlay").addEventListener("click",e=>{if(e.target.id==="overlay")closeDetail()});load().catch(e=>toast(e.message));
</script>
</body>
</html>
'''


class Handler(BaseHTTPRequestHandler):
    server_version = "AmazonPreiswatcher/0.1.47"

    def log_message(self, format: str, *args: Any) -> None:
        log.info("HTTP %s - %s", self.address_string(), format % args)

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8", extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: Any) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 1024 * 1024:
            raise ValueError("Anfrage ist zu groß.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("Ungültige JSON-Anfrage.") from exc
        if not isinstance(obj, dict):
            raise ValueError("JSON-Objekt erwartet.")
        return obj

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/health":
                self._json(200, {"ok": True, "version": APP_VERSION, "port": PORT, "gemini_model": gemini_settings()[1], "gemini_usage": gemini_usage_stats()})
                return
            if path == "/api/products/check-all/status":
                self._json(200, refresh_all_status())
                return

            if path == "/api/products":
                with db_connect() as conn:
                    rows = conn.execute("SELECT * FROM products ORDER BY active DESC, created_at DESC").fetchall()
                    watch_rows = conn.execute("SELECT * FROM mydealz_watches ORDER BY active DESC, created_at DESC").fetchall()
                self._json(200, {"products": [row_to_product(r) for r in rows], "mydealz_watches": [row_to_watch(r) for r in watch_rows], "gemini_usage": gemini_usage_stats()})
                return

            m = re.fullmatch(r"/api/mydealz-watches/(\d+)", path)
            if m:
                row = get_mydealz_watch(int(m.group(1)))
                if not row:
                    self._error(404, "MyDealz-Beobachtung nicht gefunden.")
                    return
                self._json(200, {"watch": row_to_watch(row)})
                return

            m = re.fullmatch(r"/api/products/(\d+)/check/status", path)
            if m:
                pid = int(m.group(1))
                if not get_product(pid):
                    self._error(404, "Artikel nicht gefunden.")
                    return
                self._json(200, {"status": product_check_status(pid)})
                return

            m = re.fullmatch(r"/api/products/(\d+)", path)
            if m:
                row = get_product(int(m.group(1)))
                if not row:
                    self._error(404, "Artikel nicht gefunden.")
                    return
                self._json(200, {"product": row_to_product(row)})
                return

            m = re.fullmatch(r"/api/products/(\d+)/history", path)
            if m:
                pid = int(m.group(1))
                row = get_product(pid)
                if not row:
                    self._error(404, "Artikel nicht gefunden.")
                    return
                try:
                    days = int(query.get("days", ["31"])[0])
                except ValueError:
                    days = 31
                params_a: list[Any] = [pid]
                params_i: list[Any] = [pid]
                params_u: list[Any] = [pid]
                sql_a = "SELECT checked_at, price_cents, price_source FROM prices WHERE product_id=?"
                sql_i = "SELECT checked_at, price_cents, shop, price_kind FROM idealo_prices WHERE product_id=?"
                sql_u = "SELECT checked_at, price_cents, condition FROM used_prices WHERE product_id=?"
                if days < 9999:
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
                    sql_a += " AND checked_at>=?"
                    sql_i += " AND checked_at>=?"
                    sql_u += " AND checked_at>=?"
                    params_a.append(cutoff)
                    params_i.append(cutoff)
                    params_u.append(cutoff)
                sql_a += " ORDER BY checked_at ASC"
                sql_i += " ORDER BY checked_at ASC"
                sql_u += " ORDER BY checked_at ASC"
                with db_connect() as conn:
                    ap = conn.execute(sql_a, params_a).fetchall()
                    ip = conn.execute(sql_i, params_i).fetchall()
                    up = conn.execute(sql_u, params_u).fetchall()
                self._json(200, {
                    "amazon_points": [{"at": p["checked_at"], "price": p["price_cents"] / 100, "source": p["price_source"] or "Amazon"} for p in ap],
                    "idealo_points": [{"at": p["checked_at"], "price": p["price_cents"] / 100, "source": p["price_kind"] or "Idealo", "shop": p["shop"] or ""} for p in ip],
                    "used_points": [{"at": p["checked_at"], "price": p["price_cents"] / 100, "source": p["condition"] or "Amazon Gebraucht"} for p in up],
                    "wish_price": row["wish_price_cents"] / 100 if row["wish_price_cents"] is not None else None,
                })
                return

            m = re.fullmatch(r"/api/products/(\d+)/keepa/(31|90|365|9999)", path)
            if m:
                row = get_product(int(m.group(1)))
                if not row:
                    self._error(404, "Artikel nicht gefunden.")
                    return
                try:
                    png, cached = get_keepa_png(row["asin"], int(m.group(2)))
                except Exception as exc:
                    self._error(502, f"Keepa-Graph konnte nicht geladen werden: {exc}")
                    return
                self._send(200, png, "image/png", {"X-Keepa-Cache": "hit" if cached else "miss"})
                return

            m = re.fullmatch(r"/api/products/(\d+)/image", path)
            if m:
                row = get_product(int(m.group(1)))
                if not row:
                    self._error(404, "Artikel nicht gefunden.")
                    return
                img = get_product_image(row)
                if not img:
                    gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
                    self._send(200, gif, "image/gif")
                    return
                self._send(200, img[0], img[1], {"Cache-Control": "private, max-age=3600"})
                return

            self._error(404, "Nicht gefunden.")
        except BrokenPipeError:
            pass
        except Exception:
            log.error("GET-Fehler:\n%s", traceback.format_exc())
            self._error(500, "Interner Fehler.")

    def do_POST(self) -> None:
        try:
            path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            if path == "/api/products/check-all":
                started, status = start_refresh_all()
                self._json(202 if started else 200, {"started": started, "status": status})
                return

            if path == "/api/products":
                data = self._read_json()
                input_url = str(data.get("url") or "").strip()
                asin, amazon_url = resolve_asin(input_url)
                with db_connect() as conn:
                    existing = conn.execute("SELECT * FROM products WHERE asin=?", (asin,)).fetchone()
                    if existing:
                        self._json(200, {"existing": True, "product": row_to_product(existing)})
                        return
                    now = utc_now_iso()
                    cur = conn.execute(
                        """
                        INSERT INTO products(asin, amazon_url, source_url, title, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (asin, amazon_url, input_url, f"Amazon-Artikel {asin}", now, now),
                    )
                    pid = int(cur.lastrowid)
                amazon_result = check_product(pid, check_amazon=True, check_idealo=False, check_mydealz=False)
                discovery_result = check_product(
                    pid,
                    check_amazon=False,
                    check_idealo=True,
                    check_mydealz=True,
                    force_idealo_rematch=True,
                    mydealz_search=True,
                    mydealz_gemini=True,
                )
                self._json(201, {
                    "existing": False,
                    "product": discovery_result["product"],
                    "initial_check": {
                        "amazon": amazon_result,
                        "discovery": discovery_result,
                    },
                })
                return

            m = re.fullmatch(r"/api/products/(\d+)/check", path)
            if m:
                pid = int(m.group(1))
                if not get_product(pid):
                    self._error(404, "Artikel nicht gefunden.")
                    return
                # Do not keep the ingress request open while Amazon, MyDealz and
                # URL Context run. Safari otherwise reports a read timeout even
                # though the actual price check is still valid.
                started, status = start_product_check(pid, mode="full")
                self._json(202 if started else 200, {"started": started, "status": status})
                return

            m = re.fullmatch(r"/api/products/(\d+)/idealo-rematch", path)
            if m:
                pid = int(m.group(1))
                if not get_product(pid):
                    self._error(404, "Artikel nicht gefunden.")
                    return
                # Transactional rematch: keep the old confirmed URL/price until
                # Gemini actually finds and verifies a replacement. Run it in
                # the background because Search plus verification can take time.
                started, status = start_product_check(pid, mode="rematch")
                self._json(202 if started else 200, {"started": started, "status": status})
                return

            m = re.fullmatch(r"/api/products/(\d+)/mydealz-check", path)
            if m:
                pid = int(m.group(1))
                if not get_product(pid):
                    self._error(404, "Artikel nicht gefunden.")
                    return
                self._json(200, {"result": check_product(
                    pid, check_amazon=False, check_idealo=False, check_mydealz=True,
                    mydealz_search=True, mydealz_gemini=False
                )})
                return

            if path == "/api/mydealz-watches":
                data = self._read_json()
                query = " ".join(str(data.get("query") or "").split()).strip()[:180]
                if len(query) < 2:
                    raise ValueError("Bitte einen MyDealz-Suchbegriff eingeben.")
                name = " ".join(str(data.get("name") or query).split()).strip()[:180] or query
                exclude_terms = str(data.get("exclude_terms") or "").strip()[:300]
                now = utc_now_iso()
                with db_connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO mydealz_watches(name,query,exclude_terms,active,notify_primary,notify_secondary,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (name, query, exclude_terms, 1, 1, 0, now, now),
                    )
                    wid = int(cur.lastrowid)
                result = check_mydealz_watch(wid, include_search=True)
                self._json(201, {"watch": result["watch"], "initial_check": result})
                return

            m = re.fullmatch(r"/api/mydealz-watches/(\d+)/check", path)
            if m:
                wid = int(m.group(1))
                if not get_mydealz_watch(wid):
                    self._error(404, "MyDealz-Beobachtung nicht gefunden.")
                    return
                self._json(200, {"result": check_mydealz_watch(wid, include_search=True)})
                return

            self._error(404, "Nicht gefunden.")
        except ValueError as exc:
            self._error(400, str(exc))
        except urllib.error.HTTPError as exc:
            self._error(502, f"Externer Abruf meldete HTTP {exc.code}.")
        except Exception:
            log.error("POST-Fehler:\n%s", traceback.format_exc())
            self._error(500, "Interner Fehler beim Verarbeiten der Anfrage.")

    def do_PATCH(self) -> None:
        try:
            path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            wm = re.fullmatch(r"/api/mydealz-watches/(\d+)", path)
            if wm:
                wid = int(wm.group(1))
                row = get_mydealz_watch(wid)
                if not row:
                    self._error(404, "MyDealz-Beobachtung nicht gefunden.")
                    return
                data = self._read_json()
                name = " ".join(str(data.get("name", row["name"]) or "").split()).strip()[:180]
                query = " ".join(str(data.get("query", row["query"]) or "").split()).strip()[:180]
                if not name or len(query) < 2:
                    raise ValueError("Name und Suchbegriff dürfen nicht leer sein.")
                excludes = str(data.get("exclude_terms", row["exclude_terms"] or "")).strip()[:300]
                active = 1 if bool(data.get("active", row["active"])) else 0
                np = 1 if bool(data.get("notify_primary", row["notify_primary"])) else 0
                nk = 1 if bool(data.get("notify_secondary", row["notify_secondary"])) else 0
                reset = query != str(row["query"] or "") or excludes != str(row["exclude_terms"] or "")
                with db_connect() as conn:
                    conn.execute(
                        "UPDATE mydealz_watches SET name=?,query=?,exclude_terms=?,active=?,notify_primary=?,notify_secondary=?,updated_at=?, "
                        "last_checked=CASE WHEN ? THEN NULL ELSE last_checked END,last_search_checked=CASE WHEN ? THEN NULL ELSE last_search_checked END WHERE id=?",
                        (name, query, excludes or None, active, np, nk, utc_now_iso(), 1 if reset else 0, 1 if reset else 0, wid),
                    )
                    if reset:
                        conn.execute("DELETE FROM mydealz_watch_deals WHERE watch_id=?", (wid,))
                self._json(200, {"watch": row_to_watch(get_mydealz_watch(wid))})
                return

            m = re.fullmatch(r"/api/products/(\d+)", path)
            if not m:
                self._error(404, "Nicht gefunden.")
                return
            pid = int(m.group(1))
            row = get_product(pid)
            if not row:
                self._error(404, "Artikel nicht gefunden.")
                return
            data = self._read_json()

            wish = data.get("wish_price")
            if wish is None or wish == "":
                wish_cents = None
            else:
                try:
                    wish_val = float(wish)
                except Exception as exc:
                    raise ValueError("Wunschpreis ist ungültig.") from exc
                if wish_val < 0 or wish_val > 100000:
                    raise ValueError("Wunschpreis ist ungültig.")
                wish_cents = int(round(wish_val * 100))

            try:
                threshold_val = float(data.get("idealo_cheaper_threshold", row["idealo_cheaper_threshold_cents"] / 100 if row["idealo_cheaper_threshold_cents"] is not None else 5))
            except Exception as exc:
                raise ValueError("Idealo-Mindest-Ersparnis ist ungültig.") from exc
            if threshold_val < 0 or threshold_val > 100000:
                raise ValueError("Idealo-Mindest-Ersparnis ist ungültig.")
            threshold_cents = int(round(threshold_val * 100))

            try:
                change_threshold_val = float(
                    data.get(
                        "price_change_threshold",
                        row["price_change_threshold_cents"] / 100 if row["price_change_threshold_cents"] is not None else 2,
                    )
                )
            except Exception as exc:
                raise ValueError("Mindeständerung für Preisalarme ist ungültig.") from exc
            if change_threshold_val < 0 or change_threshold_val > 100000:
                raise ValueError("Mindeständerung für Preisalarme ist ungültig.")
            change_threshold_cents = int(round(change_threshold_val * 100))

            active = 1 if bool(data.get("active", row["active"])) else 0
            nw = 1 if bool(data.get("notify_wish", row["notify_wish"])) else 0
            nd = 1 if bool(data.get("notify_drop", row["notify_drop"])) else 0
            nl = 1 if bool(data.get("notify_low", row["notify_low"])) else 0
            npc = 1 if bool(data.get("notify_price_change", row["notify_price_change"])) else 0
            np = 1 if bool(data.get("notify_primary", row["notify_primary"])) else 0
            nk = 1 if bool(data.get("notify_secondary", row["notify_secondary"])) else 0
            ie = 1 if bool(data.get("idealo_enabled", row["idealo_enabled"])) else 0
            nic = 1 if bool(data.get("notify_idealo_cheaper", row["notify_idealo_cheaper"])) else 0
            nua = 1 if bool(data.get("notify_used_available", row["notify_used_available"])) else 0
            me = 1 if bool(data.get("mydealz_enabled", row["mydealz_enabled"])) else 0
            nm = 1 if bool(data.get("notify_mydealz", row["notify_mydealz"])) else 0
            mydealz_query = str(data.get("mydealz_query", row["mydealz_query"] or "")).strip()[:180]
            old_mydealz_query = (row["mydealz_query"] or "").strip()
            reset_mydealz = mydealz_query != old_mydealz_query
            wish_triggered = row["wish_triggered"]
            if wish_cents is None:
                nw = 0
                wish_triggered = 0

            idealo_url = row["idealo_url"] or ""
            idealo_manual = row["idealo_manual"]
            idealo_status = row["idealo_status"]
            clear_idealo_current = False
            if "idealo_url" in data:
                raw_entered = str(data.get("idealo_url") or "").strip()
                # Empty form values are ignored when a durable mapping already
                # exists. This prevents an unrelated settings save from deleting
                # the Idealo link after a transient UI/Reader issue.
                if raw_entered or not idealo_url:
                    entered = validate_idealo_url(raw_entered)
                    if entered != idealo_url:
                        idealo_url = entered
                        idealo_manual = 1 if entered else 0
                        idealo_status = "manual" if entered else "pending"
                        clear_idealo_current = True

            reset_idealo_cheaper = (nic != int(bool(row["notify_idealo_cheaper"]))) or (threshold_cents != (row["idealo_cheaper_threshold_cents"] or 0))
            idealo_cheaper_triggered = 0 if reset_idealo_cheaper else int(bool(row["idealo_cheaper_triggered"]))
            with db_connect() as conn:
                conn.execute(
                    """
                    UPDATE products SET custom_name=?, wish_price_cents=?, active=?, notify_wish=?, notify_drop=?, notify_low=?, notify_price_change=?,
                        price_change_threshold_cents=?,
                        notify_primary=?, notify_secondary=?, idealo_enabled=?, notify_idealo_cheaper=?,
                        idealo_cheaper_threshold_cents=?, notify_used_available=?, mydealz_enabled=?, notify_mydealz=?,
                        mydealz_query=?, mydealz_initialized=?, wish_triggered=?, idealo_url=?, idealo_manual=?, idealo_status=?,
                        idealo_cheaper_triggered=?, updated_at=? WHERE id=?
                    """,
                    (str(data.get("custom_name") or "").strip() or None, wish_cents, active, nw, nd, nl, npc, change_threshold_cents,
                     np, nk, ie, nic, threshold_cents, nua, me, nm,
                     mydealz_query or None, 0 if reset_mydealz else int(bool(row["mydealz_initialized"])), wish_triggered,
                     idealo_url or None, idealo_manual, idealo_status, idealo_cheaper_triggered, utc_now_iso(), pid),
                )
                if clear_idealo_current:
                    conn.execute(
                        """
                        UPDATE products SET idealo_candidate_url=NULL, idealo_candidate_title=NULL, idealo_match_title=NULL,
                            idealo_match_score=NULL, idealo_current_price_cents=NULL, idealo_current_shop=NULL,
                            idealo_current_offer_url=NULL, idealo_price_kind=NULL, idealo_last_checked=NULL, idealo_last_error=NULL,
                            idealo_reader_failures=0, idealo_gemini_last_checked=NULL
                        WHERE id=?
                        """,
                        (pid,),
                    )
                if reset_mydealz:
                    conn.execute("DELETE FROM mydealz_deals WHERE product_id=?", (pid,))
                    conn.execute(
                        """
                        UPDATE products SET mydealz_last_checked=NULL, mydealz_last_success=NULL, mydealz_last_error=NULL,
                            mydealz_best_price_cents=NULL, mydealz_best_title=NULL, mydealz_best_url=NULL,
                            mydealz_best_temperature=NULL, mydealz_best_merchant=NULL, mydealz_best_published=NULL,
                            mydealz_search_last_checked=NULL, mydealz_gemini_last_checked=NULL WHERE id=?
                        """,
                        (pid,),
                    )
                updated = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                best, _, _ = _best_current_from_row(updated)
                if wish_cents is not None and (best is None or best > wish_cents):
                    conn.execute("UPDATE products SET wish_triggered=0 WHERE id=?", (pid,))
            self._json(200, {"product": row_to_product(get_product(pid))})
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception:
            log.error("PATCH-Fehler:\n%s", traceback.format_exc())
            self._error(500, "Interner Fehler.")

    def do_DELETE(self) -> None:
        try:
            path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            wm = re.fullmatch(r"/api/mydealz-watches/(\d+)", path)
            if wm:
                wid = int(wm.group(1))
                if not get_mydealz_watch(wid):
                    self._error(404, "MyDealz-Beobachtung nicht gefunden.")
                    return
                with db_connect() as conn:
                    conn.execute("DELETE FROM mydealz_watches WHERE id=?", (wid,))
                self._json(200, {"ok": True})
                return
            m = re.fullmatch(r"/api/products/(\d+)", path)
            if not m:
                self._error(404, "Nicht gefunden.")
                return
            pid = int(m.group(1))
            row = get_product(pid)
            if not row:
                self._error(404, "Artikel nicht gefunden.")
                return
            with db_connect() as conn:
                conn.execute("DELETE FROM products WHERE id=?", (pid,))
            for cache_file in IMAGE_CACHE_DIR.glob(f"{row['asin']}.*"):
                try:
                    cache_file.unlink()
                except OSError:
                    pass
            self._json(200, {"ok": True})
        except Exception:
            log.error("DELETE-Fehler:\n%s", traceback.format_exc())
            self._error(500, "Interner Fehler.")

def main() -> None:
    init_db()
    threading.Thread(target=scheduler_loop, name="price-scheduler", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Amazon Preiswächter %s startet auf Port %s; DB=%s", APP_VERSION, PORT, DB_PATH)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
