# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
import atexit, asyncio, enum, json, os, re, shutil, signal, sys, tempfile, textwrap, zipfile  # isort: skip
import getopt  # pylint: disable=deprecated-module
import urllib.parse as urllib_parse
from dataclasses import dataclass
from datetime import datetime
from gettext import gettext as _
from pathlib import Path
from typing import Any, Final, NamedTuple, Sequence, cast

import certifi, colorama, nodriver  # isort: skip
from nodriver.core.connection import ProtocolException
from ruamel.yaml import YAML
from wcmatch import glob

from . import extract, resources
from ._version import __version__
from .model.ad_model import MAX_DESCRIPTION_LENGTH, Ad, AdPartial, Contact, calculate_auto_price, calculate_auto_price_with_trace
from .model.config_model import DEFAULT_DOWNLOAD_DIR, Config
from .update_checker import UpdateChecker
from .utils import diagnostics, dicts, error_handlers, loggers, misc, xdg_paths
from .utils.exceptions import CaptchaEncountered, PublishedAdsFetchIncompleteError, PublishSubmissionUncertainError
from .utils.files import abspath
from .utils.i18n import Locale, get_current_locale, pluralize, set_current_locale
from .utils.misc import ainput, ensure, is_frozen
from .utils.timing_collector import TimingCollector
from .utils.web_scraping_mixin import By, Element, Is, WebScrapingMixin

# W0406: possibly a bug, see https://github.com/PyCQA/pylint/issues/3933

LOG:Final[loggers.Logger] = loggers.get_logger(__name__)
LOG.setLevel(loggers.INFO)

PUBLISH_MAX_RETRIES:Final[int] = 3
# Kleinanzeigen' current Astro/legacy hand-off can take more than two minutes
# while still making real progress (login → form → category → form).  Keep a
# hard upper bound for genuine hangs, but do not abort a valid slow publish.
PUBLISH_ATTEMPT_WATCHDOG_SECONDS:Final[float] = 480.0
PUBLISH_DEBUG_CAPTURE_TIMEOUT_SECONDS:Final[float] = 35.0
PUBLISH_DEBUG_PAGE_TIMEOUT_SECONDS:Final[float] = 8.0
PUBLISH_DEBUG_SCREENSHOT_TIMEOUT_SECONDS:Final[float] = 12.0
PUBLISH_DEBUG_KEEP:Final[int] = 10
_NUMERIC_IDS_RE:Final[re.Pattern[str]] = re.compile(r"^\d+(,\d+)*$")
_LOGIN_DETECTION_SELECTORS:Final[list[tuple["By", str]]] = [
    (By.CLASS_NAME, "mr-medium"),
    (By.ID, "user-email"),
]
_LOGGED_OUT_CTA_SELECTORS:Final[list[tuple["By", str]]] = [
    (By.CSS_SELECTOR, 'a[href*="einloggen"]'),
    (By.CSS_SELECTOR, 'a[href*="/m-einloggen"]'),
]

colorama.just_fix_windows_console()


def _format_login_detection_selectors(selectors:Sequence[tuple["By", str]]) -> str:
    return ", ".join(f"{selector_type.name}={selector_value}" for selector_type, selector_value in selectors)


class AdUpdateStrategy(enum.Enum):
    REPLACE = enum.auto()
    MODIFY = enum.auto()


class LoginDetectionReason(enum.Enum):
    USER_INFO_MATCH = enum.auto()
    CTA_MATCH = enum.auto()
    SELECTOR_TIMEOUT = enum.auto()


class PublishAttemptWatchdogError(RuntimeError):
    """A complete publish attempt exceeded the manager-safe runtime boundary."""


@dataclass(frozen = True)
class LoginDetectionResult:
    """Login detection result.

    Invariants:
    - is_logged_in=True only with USER_INFO_MATCH
    - is_logged_in=False with CTA_MATCH or SELECTOR_TIMEOUT
    """

    is_logged_in:bool
    reason:LoginDetectionReason

    def __post_init__(self) -> None:
        if not isinstance(self.is_logged_in, bool):
            raise TypeError("is_logged_in must be a bool")
        if not isinstance(self.reason, LoginDetectionReason):
            raise TypeError("reason must be a LoginDetectionReason")
        if self.is_logged_in and self.reason != LoginDetectionReason.USER_INFO_MATCH:
            raise ValueError("is_logged_in=True requires reason=USER_INFO_MATCH")
        if not self.is_logged_in and self.reason == LoginDetectionReason.USER_INFO_MATCH:
            raise ValueError("is_logged_in=False requires reason=CTA_MATCH or SELECTOR_TIMEOUT")


class ResolvedAdState(NamedTuple):
    """Resolution result for ad download state.

    Used by _resolve_download_ad_activity to return both the activity state
    and ownership status of an ad being downloaded.

    Attributes:
        active: Whether the ad should be saved as active (True) or inactive (False).
            Only ads with state="active" in the published profile are marked as active.
        owned: Whether the ad belongs to the current user (True) or is foreign (False).
            For "all"/"new" selectors this is typically True; for numeric IDs it may be False.
    """
    active:bool
    owned:bool


def _repost_cycle_ready(
    ad_cfg:Ad,
    ad_file_relative:str,
    repost_state:tuple[int, int, int, int] | None = None,
) -> bool:
    """
    Check if the repost cycle delay has been satisfied.

    :param ad_cfg: The ad configuration
    :param ad_file_relative: Relative path to the ad file for logging
    :param repost_state: Optional precomputed repost-delay state tuple
    :return: True if ready to apply price reduction, False otherwise
    """
    total_reposts, delay_reposts, applied_cycles, eligible_cycles = repost_state or _repost_delay_state(ad_cfg)

    if total_reposts <= delay_reposts:
        remaining = (delay_reposts + 1) - total_reposts
        LOG.info(
            "Auto price reduction delayed for [%s]: waiting %s more reposts (completed %s, applied %s reductions)",
            ad_file_relative,
            max(remaining, 1),  # Clamp to 1 to avoid showing "0 more reposts" when at threshold
            total_reposts,
            applied_cycles,
        )
        return False

    if eligible_cycles <= applied_cycles:
        LOG.info("Auto price reduction already applied for [%s]: %s reductions match %s eligible reposts", ad_file_relative, applied_cycles, eligible_cycles)
        return False

    return True


def _day_delay_elapsed(
    ad_cfg:Ad,
    ad_file_relative:str,
    day_delay_state:tuple[bool, int | None, datetime | None] | None = None,
) -> bool:
    """
    Check if the day delay has elapsed since the ad was last published.

    :param ad_cfg: The ad configuration
    :param ad_file_relative: Relative path to the ad file for logging
    :param day_delay_state: Optional precomputed day-delay state tuple
    :return: True if the delay has elapsed, False otherwise
    """
    delay_days = ad_cfg.auto_price_reduction.delay_days
    ready, elapsed_days, reference = day_delay_state or _day_delay_state(ad_cfg)

    if delay_days == 0:
        return True

    if not reference:
        LOG.info("Auto price reduction delayed for [%s]: waiting %s days but publish timestamp missing", ad_file_relative, delay_days)
        return False

    if not ready and elapsed_days is not None:
        LOG.info("Auto price reduction delayed for [%s]: waiting %s days (elapsed %s)", ad_file_relative, delay_days, elapsed_days)
        return False

    return True


def _repost_delay_state(ad_cfg:Ad) -> tuple[int, int, int, int]:
    """Return repost-delay state tuple.

    Returns:
        tuple[int, int, int, int]:
            (total_reposts, delay_reposts, applied_cycles, eligible_cycles)
    """
    total_reposts = ad_cfg.repost_count or 0
    delay_reposts = ad_cfg.auto_price_reduction.delay_reposts
    applied_cycles = ad_cfg.price_reduction_count or 0
    eligible_cycles = max(total_reposts - delay_reposts, 0)
    return total_reposts, delay_reposts, applied_cycles, eligible_cycles


def _day_delay_state(ad_cfg:Ad) -> tuple[bool, int | None, datetime | None]:
    """Return day-delay state tuple.

    Returns:
        tuple[bool, int | None, datetime | None]:
            (ready_flag, elapsed_days_or_none, reference_timestamp_or_none)
    """
    delay_days = ad_cfg.auto_price_reduction.delay_days
    # Use getattr to support lightweight test doubles without these attributes.
    reference = getattr(ad_cfg, "updated_on", None) or getattr(ad_cfg, "created_on", None)
    if delay_days == 0:
        return True, 0, reference

    if not reference:
        return False, None, None

    # Note: .days truncates to whole days (e.g., 1.9 days -> 1 day)
    # This is intentional: delays count complete 24-hour periods since publish
    # Both misc.now() and stored timestamps use UTC (via misc.now()), ensuring consistent calculations
    elapsed_days = (misc.now() - reference).days
    return elapsed_days >= delay_days, elapsed_days, reference


def _relative_ad_path(ad_file:str, config_file_path:str) -> str:
    """Compute an ad file path relative to the config directory, falling back to the absolute path."""
    try:
        return str(Path(ad_file).relative_to(Path(config_file_path).parent))
    except ValueError:
        return ad_file


def apply_auto_price_reduction(ad_cfg:Ad, _ad_cfg_orig:dict[str, Any], ad_file_relative:str) -> None:
    """
    Apply automatic price reduction to an ad based on repost count and configuration.

    This function modifies ad_cfg in-place, updating the price and price_reduction_count
    fields when a reduction is applicable.

    :param ad_cfg: The ad configuration to potentially modify
    :param _ad_cfg_orig: The original ad configuration (unused, kept for compatibility)
    :param ad_file_relative: Relative path to the ad file for logging
    """
    if not ad_cfg.auto_price_reduction.enabled:
        LOG.debug("Auto price reduction: not configured for [%s]", ad_file_relative)
        return

    base_price = ad_cfg.price
    if base_price is None:
        LOG.warning("Auto price reduction is enabled for [%s] but no price is configured.", ad_file_relative)
        return

    if ad_cfg.auto_price_reduction.min_price is not None and ad_cfg.auto_price_reduction.min_price == base_price:
        LOG.warning("Auto price reduction is enabled for [%s] but min_price equals price (%s) - no reductions will occur.", ad_file_relative, base_price)
        return

    repost_state = _repost_delay_state(ad_cfg)
    day_delay_state = _day_delay_state(ad_cfg)
    total_reposts, delay_reposts, applied_cycles, eligible_cycles = repost_state
    _, elapsed_days, reference = day_delay_state
    delay_days = ad_cfg.auto_price_reduction.delay_days
    elapsed_display = "missing" if elapsed_days is None else str(elapsed_days)
    reference_display = "missing" if reference is None else reference.isoformat(timespec = "seconds")

    if not _repost_cycle_ready(ad_cfg, ad_file_relative, repost_state = repost_state):
        next_repost = delay_reposts + 1 if total_reposts <= delay_reposts else delay_reposts + applied_cycles + 1
        LOG.debug(
            "Auto price reduction decision for [%s]: skipped (repost delay). next reduction earliest at repost >= %s and day delay %s/%s days."
            " repost_count=%s eligible_cycles=%s applied_cycles=%s reference=%s",
            ad_file_relative,
            next_repost,
            elapsed_display,
            delay_days,
            total_reposts,
            eligible_cycles,
            applied_cycles,
            reference_display,
        )
        return

    if not _day_delay_elapsed(ad_cfg, ad_file_relative, day_delay_state = day_delay_state):
        LOG.debug(
            "Auto price reduction decision for [%s]: skipped (day delay). next reduction earliest when elapsed_days >= %s."
            " elapsed_days=%s repost_count=%s eligible_cycles=%s applied_cycles=%s reference=%s",
            ad_file_relative,
            delay_days,
            elapsed_display,
            total_reposts,
            eligible_cycles,
            applied_cycles,
            reference_display,
        )
        return

    LOG.debug(
        "Auto price reduction decision for [%s]: applying now (eligible_cycles=%s, applied_cycles=%s, elapsed_days=%s/%s).",
        ad_file_relative,
        eligible_cycles,
        applied_cycles,
        elapsed_display,
        delay_days,
    )

    next_cycle = applied_cycles + 1

    if loggers.is_debug(LOG):
        effective_price, reduction_steps, price_floor = calculate_auto_price_with_trace(
            base_price = base_price,
            auto_price_reduction = ad_cfg.auto_price_reduction,
            target_reduction_cycle = next_cycle,
        )
        LOG.debug(
            "Auto price reduction trace for [%s]: strategy=%s amount=%s floor=%s target_cycle=%s base_price=%s",
            ad_file_relative,
            ad_cfg.auto_price_reduction.strategy,
            ad_cfg.auto_price_reduction.amount,
            price_floor,
            next_cycle,
            base_price,
        )
        for step in reduction_steps:
            LOG.debug(
                " -> cycle=%s before=%s reduction=%s after_rounding=%s floor_applied=%s",
                step.cycle,
                step.price_before,
                step.reduction_value,
                step.price_after_rounding,
                step.floor_applied,
            )
    else:
        effective_price = calculate_auto_price(base_price = base_price, auto_price_reduction = ad_cfg.auto_price_reduction, target_reduction_cycle = next_cycle)

    if effective_price is None:
        return

    if effective_price == base_price:
        # Still increment counter so small fractional reductions can accumulate over multiple cycles
        ad_cfg.price_reduction_count = next_cycle
        LOG.info("Auto price reduction kept price %s after attempting %s reduction cycles", effective_price, next_cycle)
        return

    LOG.info("Auto price reduction applied: %s -> %s after %s reduction cycles", base_price, effective_price, next_cycle)
    ad_cfg.price = effective_price
    ad_cfg.price_reduction_count = next_cycle
    # Note: price_reduction_count is persisted to ad_cfg_orig only after successful publish


class KleinanzeigenBot(WebScrapingMixin):  # noqa: PLR0904
    def __init__(self) -> None:
        # workaround for https://github.com/Second-Hand-Friends/kleinanzeigen-bot/issues/295
        # see https://github.com/pyinstaller/pyinstaller/issues/7229#issuecomment-1309383026
        os.environ["SSL_CERT_FILE"] = certifi.where()

        super().__init__()

        self.root_url = "https://www.kleinanzeigen.de"

        self.config:Config
        self.config_file_path = abspath("config.yaml")
        self.workspace:xdg_paths.Workspace | None = None
        self._config_arg:str | None = None
        self._workspace_mode_arg:xdg_paths.InstallationMode | None = None

        self.categories:dict[str, str] = {}

        self.file_log:loggers.LogFileHandle | None = None
        self._log_basename = os.path.splitext(os.path.basename(sys.executable))[0] if is_frozen() else self.__module__
        self.log_file_path:str | None = abspath(f"{self._log_basename}.log")
        self._logfile_arg:str | None = None
        self._logfile_explicitly_provided:bool = False

        self.command = "help"
        self.ads_selector = "due"
        self._ads_selector_explicit:bool = False
        self.keep_old_ads = False

        self._login_detection_diagnostics_captured:bool = False
        self._timing_collector:TimingCollector | None = None

    def __del__(self) -> None:
        if self.file_log:
            self.file_log.close()
            self.file_log = None
        self.close_browser_session()

    def get_version(self) -> str:
        return __version__

    def _workspace_or_raise(self) -> xdg_paths.Workspace:
        if self.workspace is None:
            raise AssertionError(_("Workspace must be resolved before command execution"))
        return self.workspace

    @property
    def _update_check_state_path(self) -> Path:
        return self._workspace_or_raise().state_dir / "update_check_state.json"

    def _resolve_download_dir(self) -> Path:
        workspace = self._workspace_or_raise()
        trimmed_dir = self.config.download.dir.strip()
        if trimmed_dir == DEFAULT_DOWNLOAD_DIR:
            return workspace.download_dir
        return Path(abspath(trimmed_dir, relative_to = str(Path(self.config_file_path).parent))).resolve()

    def _resolve_download_ad_activity(self, ad_id:int, published_ads_by_id:dict[int, dict[str, Any]]) -> ResolvedAdState:
        """Resolve downloaded ad activity and ownership for download selectors.

        Looks up the ad in the published profile and determines its activity state
        and ownership status. Used by "all", "new", and numeric ID selectors.

        Args:
            ad_id: The ad ID to look up in the published profile.
            published_ads_by_id: Dict mapping ad IDs to published ad data from the
                Kleinanzeigen API. Contains only the current user's own ads.

        Returns:
            ResolvedAdState with:
            - active=True if ad exists and state=="active", otherwise False
            - owned=True if ad exists in published_ads_by_id, otherwise False
        """
        published_ad = published_ads_by_id.get(ad_id)
        if published_ad is None:
            return ResolvedAdState(active = False, owned = False)

        return ResolvedAdState(
            active = published_ad.get("state") == "active",
            owned = True
        )

    async def _download_ad_with_resolved_state(
        self,
        ad_extractor:extract.AdExtractor,
        ad_id:int,
        published_ads_by_id:dict[int, dict[str, Any]]
    ) -> None:
        """Download an ad with proper active state resolution and logging.

        Resolves the ad's activity state from the published profile, logs appropriately
        based on the resolution result, and initiates the download with the resolved state.

        This method centralizes the resolution + logging + download logic used by
        the "all" and "new" selectors.

        Args:
            ad_extractor: The AdExtractor instance to use for downloading.
            ad_id: The ad ID to download.
            published_ads_by_id: Dict mapping ad IDs to published ad data from API.

        Note:
            The numeric selector does NOT use this helper because it has different
            warning message semantics (foreign ads are expected, not anomalies).
        """
        resolved = self._resolve_download_ad_activity(ad_id, published_ads_by_id)

        if not resolved.owned:
            # Ad not in user's published profile - unexpected for "all"/"new" selectors
            # since these only list the user's own ads from the overview page
            LOG.warning(
                "Ad %d found in overview but not in published profile. Saving as inactive.",
                ad_id
            )
        elif not resolved.active:
            # Ad is in published profile but not in active state (paused, inactive, etc.)
            published_ad = published_ads_by_id.get(ad_id, {})
            LOG.debug(
                "Ad %d has state '%s'. Saving as inactive.",
                ad_id,
                published_ad.get("state", "unknown")
            )

        await ad_extractor.download_ad(ad_id, active = resolved.active)

    def _resolve_workspace(self) -> None:
        """
        Resolve workspace paths after CLI args are parsed.
        """
        if self.command in {"help", "version", "create-config"}:
            return
        effective_config_arg = self._config_arg
        effective_workspace_mode = self._workspace_mode_arg
        if not effective_config_arg:
            default_config = (Path.cwd() / "config.yaml").resolve()
            if self.config_file_path and Path(self.config_file_path).resolve() != default_config:
                effective_config_arg = self.config_file_path
                if effective_workspace_mode is None:
                    # Backward compatibility for tests/programmatic assignment of config_file_path:
                    # infer a stable default from the configured path location.
                    config_path = Path(self.config_file_path).resolve()
                    xdg_config_dir = xdg_paths.get_xdg_base_dir("config").resolve()
                    effective_workspace_mode = "xdg" if config_path.is_relative_to(xdg_config_dir) else "portable"

        try:
            self.workspace = xdg_paths.resolve_workspace(
                config_arg = effective_config_arg,
                logfile_arg = self._logfile_arg,
                workspace_mode = effective_workspace_mode,
                logfile_explicitly_provided = self._logfile_explicitly_provided,
                log_basename = self._log_basename,
            )
        except ValueError as exc:
            LOG.error(str(exc))
            sys.exit(2)

        xdg_paths.ensure_directory(self.workspace.config_file.parent, "config directory")

        self.config_file_path = str(self.workspace.config_file)
        self.log_file_path = str(self.workspace.log_file) if self.workspace.log_file else None

        LOG.info("Config:    %s", self.workspace.config_file)
        LOG.info("Workspace mode: %s", self.workspace.mode)
        LOG.info("Workspace: %s", self.workspace.config_dir)
        if loggers.is_debug(LOG):
            LOG.debug("Log file:        %s", self.workspace.log_file)
            LOG.debug("State dir:       %s", self.workspace.state_dir)
            LOG.debug("Download dir:    %s", self.workspace.download_dir)
            LOG.debug("Browser profile: %s", self.workspace.browser_profile_dir)
            LOG.debug("Diagnostics dir: %s", self.workspace.diagnostics_dir)

    async def run(self, args:list[str]) -> None:
        self.parse_args(args)
        self._resolve_workspace()
        try:
            match self.command:
                case "help":
                    self.show_help()
                    return
                case "version":
                    print(self.get_version())
                case "create-config":
                    self.create_default_config()
                    return
                case "diagnose":
                    self.configure_file_logging()
                    self.load_config()
                    self.diagnose_browser_issues()
                    return
                case "verify":
                    self.configure_file_logging()
                    self.load_config()
                    # Check for updates on startup
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates()
                    self.ads_selector = "all"
                    if ads := self.load_ads(exclude_ads_with_id = False):
                        for ad_file, ad_cfg, ad_cfg_orig in ads:
                            ad_file_relative = _relative_ad_path(ad_file, self.config_file_path)
                            apply_auto_price_reduction(ad_cfg, ad_cfg_orig, ad_file_relative)
                    LOG.info("############################################")
                    LOG.info("DONE: No configuration errors found.")
                    LOG.info("############################################")
                case "update-check":
                    self.configure_file_logging()
                    self.load_config()
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates(skip_interval_check = True)
                case "update-content-hash":
                    self.configure_file_logging()
                    self.load_config()
                    # Check for updates on startup
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates()
                    self.ads_selector = "all"
                    if ads := self.load_ads(exclude_ads_with_id = False):
                        self.update_content_hashes(ads)
                    else:
                        LOG.info("############################################")
                        LOG.info("DONE: No active ads found.")
                        LOG.info("############################################")
                case "publish":
                    self.configure_file_logging()
                    self.load_config()
                    # Check for updates on startup
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates()

                    if not self._is_valid_ads_selector({"all", "new", "due", "changed"}):
                        if self._ads_selector_explicit:
                            LOG.error(
                                'Invalid --ads selector: "%s". Valid values: comma-separated keywords (all, new, due, changed) or numeric IDs.',
                                self.ads_selector,
                            )
                            sys.exit(2)
                        self.ads_selector = "due"

                    if ads := self.load_ads():
                        await self.create_browser_session()
                        await self.login()
                        await self.publish_ads(ads)
                    else:
                        LOG.info("############################################")
                        LOG.info("DONE: No new/outdated ads found.")
                        LOG.info("############################################")
                case "update":
                    self.configure_file_logging()
                    self.load_config()

                    if not self._is_valid_ads_selector({"all", "changed"}):
                        if self._ads_selector_explicit:
                            LOG.error('Invalid --ads selector: "%s". Valid values: comma-separated keywords (all, changed) or numeric IDs.', self.ads_selector)
                            sys.exit(2)
                        self.ads_selector = "changed"

                    # Ein expliziter Update-Aufruf mit konkreter Anzeigen-ID kommt
                    # aus dem Manager ("Speichern & Live aktualisieren"). In diesem
                    # Fall darf der lokale Automatik-Status active=false die Live-
                    # Bearbeitung nicht blockieren: Die Anzeige ist bereits online
                    # und wurde vom Benutzer bewusst zum Aktualisieren ausgewählt.
                    # Bei den normalen Selektoren (all/changed) bleiben inaktive
                    # Anzeigen weiterhin wie bisher ausgeschlossen.
                    explicit_numeric_ids = bool(_NUMERIC_IDS_RE.match(self.ads_selector))
                    if ads := self.load_ads(ignore_inactive=not explicit_numeric_ids):
                        await self.create_browser_session()
                        await self.login()
                        await self.update_ads(ads)
                    else:
                        LOG.info("############################################")
                        LOG.info("DONE: No changed ads found.")
                        LOG.info("############################################")
                case "delete":
                    self.configure_file_logging()
                    self.load_config()
                    # Check for updates on startup
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates()
                    if ads := self.load_ads():
                        await self.create_browser_session()
                        await self.login()
                        await self.delete_ads(ads)
                    else:
                        LOG.info("############################################")
                        LOG.info("DONE: No ads to delete found.")
                        LOG.info("############################################")
                case "extend":
                    self.configure_file_logging()
                    self.load_config()
                    # Check for updates on startup
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates()

                    # Default to all ads if no selector provided, but reject invalid values
                    if not self._is_valid_ads_selector({"all"}):
                        if self._ads_selector_explicit:
                            LOG.error('Invalid --ads selector: "%s". Valid values: all or comma-separated numeric IDs.', self.ads_selector)
                            sys.exit(2)
                        LOG.info("Extending all ads within 8-day window...")
                        self.ads_selector = "all"

                    if ads := self.load_ads():
                        await self.create_browser_session()
                        await self.login()
                        await self.extend_ads(ads)
                    else:
                        LOG.info("############################################")
                        LOG.info("DONE: No ads found to extend.")
                        LOG.info("############################################")
                case "download":
                    self.configure_file_logging()
                    # ad IDs depends on selector
                    if not self._is_valid_ads_selector({"all", "new"}):
                        if self._ads_selector_explicit:
                            LOG.error('Invalid --ads selector: "%s". Valid values: comma-separated keywords (all, new) or numeric IDs.', self.ads_selector)
                            sys.exit(2)
                        self.ads_selector = "new"
                    self.load_config()
                    # Check for updates on startup
                    checker = UpdateChecker(self.config, self._update_check_state_path)
                    checker.check_for_updates()
                    await self.create_browser_session()
                    await self.login()
                    await self.download_ads()

                case _:
                    LOG.error("Unknown command: %s", self.command)
                    sys.exit(2)
        finally:
            self.close_browser_session()
            if self._timing_collector is not None:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._timing_collector.flush)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("Timing collector flush failed: %s", exc)

    def show_help(self) -> None:
        if is_frozen():
            exe = sys.argv[0]
        elif os.getenv("PDM_PROJECT_ROOT", ""):
            exe = "pdm run app"
        else:
            exe = "python -m kleinanzeigen_bot"

        if get_current_locale().language == "de":
            print(
                textwrap.dedent(
                    f"""\
            Verwendung: {colorama.Fore.LIGHTMAGENTA_EX}{exe} BEFEHL [OPTIONEN]{colorama.Style.RESET_ALL}

            Befehle:
              publish  - (Wieder-)Veröffentlicht Anzeigen
              verify   - Überprüft die Konfigurationsdateien
              delete   - Löscht Anzeigen
              update   - Aktualisiert bestehende Anzeigen
              extend   - Verlängert Anzeigen innerhalb des 8-Tage-Zeitfensters
              download - Lädt eine oder mehrere Anzeigen herunter
              update-check - Prüft auf verfügbare Updates
              update-content-hash - Berechnet den content_hash aller Anzeigen anhand der aktuellen ad_defaults neu;
                                    nach Änderungen an den config.yaml/ad_defaults verhindert es, dass alle Anzeigen als
                                    "geändert" gelten und neu veröffentlicht werden.
              create-config - Erstellt eine neue Standard-Konfigurationsdatei, falls noch nicht vorhanden
              diagnose - Diagnostiziert Browser-Verbindungsprobleme und zeigt Troubleshooting-Informationen
              --
              help     - Zeigt diese Hilfe an (Standardbefehl)
              version  - Zeigt die Version der Anwendung an

            Optionen:
              --ads=all|due|new|changed|<id(s)> (publish) - Gibt an, welche Anzeigen (erneut) veröffentlicht werden sollen (STANDARD: due)
                    Mögliche Werte:
                    * all: Veröffentlicht alle Anzeigen erneut, ignoriert republication_interval
                    * due: Veröffentlicht alle neuen Anzeigen und erneut entsprechend dem republication_interval
                    * new: Veröffentlicht nur neue Anzeigen (d.h. Anzeigen ohne ID in der Konfigurationsdatei)
                    * changed: Veröffentlicht nur Anzeigen, die seit der letzten Veröffentlichung geändert wurden
                    * <id(s)>: Gibt eine oder mehrere Anzeigen-IDs an, die veröffentlicht werden sollen, z. B. "--ads=1,2,3", ignoriert republication_interval
                    * Kombinationen: Sie können mehrere Selektoren mit Kommas kombinieren, z. B. "--ads=changed,due" um sowohl geänderte als auch
                      fällige Anzeigen zu veröffentlichen
              --ads=all|new|<id(s)> (download) - Gibt an, welche Anzeigen heruntergeladen werden sollen (STANDARD: new)
                    Mögliche Werte:
                    * all: Lädt alle Anzeigen aus Ihrem Profil herunter
                    * new: Lädt Anzeigen aus Ihrem Profil herunter, die lokal noch nicht gespeichert sind
                    * <id(s)>: Gibt eine oder mehrere Anzeigen-IDs zum Herunterladen an, z. B. "--ads=1,2,3"
              --ads=all|changed|<id(s)> (update) - Gibt an, welche Anzeigen aktualisiert werden sollen (STANDARD: changed)
                    Mögliche Werte:
                    * all: Aktualisiert alle Anzeigen
                    * changed: Aktualisiert nur Anzeigen, die seit der letzten Veröffentlichung geändert wurden
                    * <id(s)>: Gibt eine oder mehrere Anzeigen-IDs zum Aktualisieren an, z. B. "--ads=1,2,3"
              --ads=all|<id(s)> (extend) - Gibt an, welche Anzeigen verlängert werden sollen
                    Mögliche Werte:
                    * all: Verlängert alle Anzeigen, die innerhalb von 8 Tagen ablaufen
                    * <id(s)>: Gibt bestimmte Anzeigen-IDs an, z. B. "--ads=1,2,3"
              --force           - Alias für '--ads=all'
              --keep-old        - Verhindert das Löschen alter Anzeigen bei erneuter Veröffentlichung
              --config=<PATH>   - Pfad zur YAML- oder JSON-Konfigurationsdatei (ändert den Workspace-Modus nicht implizit)
              --workspace-mode=portable|xdg - Überschreibt den Workspace-Modus für diesen Lauf
              --logfile=<PATH>  - Pfad zur Protokolldatei (STANDARD: vom aktiven Workspace-Modus abhängig)
              --lang=en|de      - Anzeigesprache (STANDARD: Systemsprache, wenn unterstützt, sonst Englisch)
              -v, --verbose     - Aktiviert detaillierte Ausgabe – nur nützlich zur Fehlerbehebung
            """.rstrip()
                )
            )
        else:
            print(
                textwrap.dedent(
                    f"""\
            Usage: {colorama.Fore.LIGHTMAGENTA_EX}{exe} COMMAND [OPTIONS]{colorama.Style.RESET_ALL}

            Commands:
              publish  - (re-)publishes ads
              verify   - verifies the configuration files
              delete   - deletes ads
              update   - updates published ads
              extend   - extends ads within the 8-day window before expiry
              download - downloads one or multiple ads
              update-check - checks for available updates
              update-content-hash – recalculates each ad's content_hash based on the current ad_defaults;
                                    use this after changing config.yaml/ad_defaults to avoid every ad being marked "changed" and republished
              create-config - creates a new default configuration file if one does not exist
              diagnose - diagnoses browser connection issues and shows troubleshooting information
              --
              help     - displays this help (default command)
              version  - displays the application version

            Options:
              --ads=all|due|new|changed|<id(s)> (publish) - specifies which ads to (re-)publish (DEFAULT: due)
                    Possible values:
                    * all: (re-)publish all ads ignoring republication_interval
                    * due: publish all new ads and republish ads according the republication_interval
                    * new: only publish new ads (i.e. ads that have no id in the config file)
                    * changed: only publish ads that have been modified since last publication
                    * <id(s)>: provide one or several ads by ID to (re-)publish, like e.g. "--ads=1,2,3" ignoring republication_interval
                    * Combinations: You can combine multiple selectors with commas, e.g. "--ads=changed,due" to publish both changed and due ads
              --ads=all|new|<id(s)> (download) - specifies which ads to download (DEFAULT: new)
                    Possible values:
                    * all: downloads all ads from your profile
                    * new: downloads ads from your profile that are not locally saved yet
                    * <id(s)>: provide one or several ads by ID to download, like e.g. "--ads=1,2,3"
              --ads=all|changed|<id(s)> (update) - specifies which ads to update (DEFAULT: changed)
                    Possible values:
                    * all: update all ads
                    * changed: only update ads that have been modified since last publication
                    * <id(s)>: provide one or several ads by ID to update, like e.g. "--ads=1,2,3"
              --ads=all|<id(s)> (extend) - specifies which ads to extend
                    Possible values:
                    * all: extend all ads expiring within 8 days
                    * <id(s)>: specify ad IDs to extend, e.g. "--ads=1,2,3"
              --force           - alias for '--ads=all'
              --keep-old        - don't delete old ads on republication
              --config=<PATH>   - path to the config YAML or JSON file (does not implicitly change workspace mode)
              --workspace-mode=portable|xdg - overrides workspace mode for this run
              --logfile=<PATH>  - path to the logfile (DEFAULT: depends on active workspace mode)
              --lang=en|de      - display language (STANDARD: system language if supported, otherwise English)
              -v, --verbose     - enables verbose output - only useful when troubleshooting issues
            """.rstrip()
                )
            )

    def _is_valid_ads_selector(self, valid_keywords:set[str]) -> bool:
        """Check if the current ads_selector is valid for the given set of keyword selectors.

        Accepts a single keyword, a comma-separated list of keywords, or a comma-separated
        list of numeric IDs. Mixed keyword+numeric selectors are not supported.
        """
        return (
            self.ads_selector in valid_keywords
            or all(s.strip() in valid_keywords for s in self.ads_selector.split(","))
            or bool(_NUMERIC_IDS_RE.match(self.ads_selector))
        )

    def parse_args(self, args:list[str]) -> None:
        try:
            options, arguments = getopt.gnu_getopt(
                args[1:],
                "hv",
                ["ads=", "config=", "force", "help", "keep-old", "logfile=", "lang=", "verbose", "workspace-mode="],
            )
        except getopt.error as ex:
            LOG.error(ex.msg)
            LOG.error("Use --help to display available options.")
            sys.exit(2)

        for option, value in options:
            match option:
                case "-h" | "--help":
                    self.show_help()
                    sys.exit(0)
                case "--config":
                    self.config_file_path = abspath(value)
                    self._config_arg = value
                case "--logfile":
                    if value:
                        self.log_file_path = abspath(value)
                    else:
                        self.log_file_path = None
                    self._logfile_arg = value
                    self._logfile_explicitly_provided = True
                case "--workspace-mode":
                    mode = value.strip().lower()
                    if mode not in {"portable", "xdg"}:
                        LOG.error("Invalid --workspace-mode '%s'. Use 'portable' or 'xdg'.", value)
                        sys.exit(2)
                    self._workspace_mode_arg = cast(xdg_paths.InstallationMode, mode)
                case "--ads":
                    self.ads_selector = value.strip().lower()
                    self._ads_selector_explicit = True
                case "--force":
                    self.ads_selector = "all"
                    self._ads_selector_explicit = True
                case "--keep-old":
                    self.keep_old_ads = True
                case "--lang":
                    set_current_locale(Locale.of(value))
                case "-v" | "--verbose":
                    LOG.setLevel(loggers.DEBUG)
                    loggers.get_logger("nodriver").setLevel(loggers.INFO)

        match len(arguments):
            case 0:
                self.command = "help"
            case 1:
                self.command = arguments[0]
            case _:
                LOG.error("More than one command given: %s", arguments)
                sys.exit(2)

    def configure_file_logging(self) -> None:
        if not self.log_file_path:
            return
        if self.file_log:
            return

        if self.workspace and self.workspace.log_file:
            xdg_paths.ensure_directory(self.workspace.log_file.parent, "log directory")

        LOG.info("Logging to [%s]...", self.log_file_path)
        self.file_log = loggers.configure_file_logging(self.log_file_path)

        LOG.info("App version: %s", self.get_version())
        LOG.info("Python version: %s", sys.version)

    def create_default_config(self) -> None:
        """
        Create a default config.yaml in the project root if it does not exist.
        If it exists, log an error and inform the user.
        """
        if os.path.exists(self.config_file_path):
            LOG.error("Config file %s already exists. Aborting creation.", self.config_file_path)
            return
        config_parent = self.workspace.config_file.parent if self.workspace else Path(self.config_file_path).parent
        xdg_paths.ensure_directory(config_parent, "config directory")
        default_config = Config.model_construct()
        default_config.login.username = "changeme"  # noqa: S105 placeholder for default config, not a real username
        default_config.login.password = "changeme"  # noqa: S105 placeholder for default config, not a real password
        dicts.save_commented_model(
            self.config_file_path,
            default_config,
            header = "# yaml-language-server: $schema=https://raw.githubusercontent.com/Second-Hand-Friends/kleinanzeigen-bot/main/schemas/config.schema.json",
            exclude = {
                "ad_defaults": {"description"},
            },
        )

    def load_config(self) -> None:
        # write default config.yaml if config file does not exist
        if not os.path.exists(self.config_file_path):
            self.create_default_config()

        config_yaml = dicts.load_dict_if_exists(self.config_file_path, _("config"))
        self.config = Config.model_validate(config_yaml, strict = True, context = self.config_file_path)

        timing_enabled = self.config.diagnostics.timing_collection
        if timing_enabled and self.workspace:
            timing_dir = self.workspace.diagnostics_dir.parent / "timing"
            self._timing_collector = TimingCollector(timing_dir, self.command)
        else:
            self._timing_collector = None

        # load built-in category mappings
        self.categories = dicts.load_dict_from_module(resources, "categories.yaml", "")
        LOG.debug("Loaded %s categories from categories.yaml", len(self.categories))
        deprecated_categories = dicts.load_dict_from_module(resources, "categories_old.yaml", "")
        LOG.debug("Loaded %s categories from categories_old.yaml", len(deprecated_categories))
        self.categories.update(deprecated_categories)
        custom_count = 0
        if self.config.categories:
            custom_count = len(self.config.categories)
            self.categories.update(self.config.categories)
            LOG.debug("Loaded %s categories from config.yaml (custom)", custom_count)
        total_count = len(self.categories)
        if total_count == 0:
            LOG.warning("No categories loaded - category files may be missing or empty")
        LOG.debug("Loaded %s categories in total", total_count)

        # populate browser_config object used by WebScrapingMixin
        self.browser_config.arguments = self.config.browser.arguments
        self.browser_config.binary_location = self.config.browser.binary_location
        self.browser_config.extensions = [abspath(item, relative_to = self.config_file_path) for item in self.config.browser.extensions]
        self.browser_config.use_private_window = self.config.browser.use_private_window
        if self.config.browser.user_data_dir:
            self.browser_config.user_data_dir = abspath(self.config.browser.user_data_dir, relative_to = self.config_file_path)
        elif self.workspace:
            self.browser_config.user_data_dir = str(self.workspace.browser_profile_dir)
        self.browser_config.profile_name = self.config.browser.profile_name

    def __check_ad_republication(self, ad_cfg:Ad, ad_file_relative:str) -> bool:
        """
        Check if an ad needs to be republished based on republication interval.
        Note:  This method does not check for content changes. Use __check_ad_changed for that.

        Returns:
            True if the ad should be republished based on the interval.
        """
        if ad_cfg.updated_on:
            last_updated_on = ad_cfg.updated_on
        elif ad_cfg.created_on:
            last_updated_on = ad_cfg.created_on
        else:
            return True

        if not last_updated_on:
            return True

        # Check republication interval
        ad_age = misc.now() - last_updated_on
        if ad_age.days <= ad_cfg.republication_interval:
            LOG.info(
                " -> SKIPPED: ad [%s] was last published %d days ago. republication is only required every %s days",
                ad_file_relative,
                ad_age.days,
                ad_cfg.republication_interval,
            )
            return False

        return True

    def __check_ad_changed(self, ad_cfg:Ad, ad_cfg_orig:dict[str, Any], ad_file_relative:str) -> bool:
        """
        Check if an ad has been changed since last publication.

        Returns:
            True if the ad has been changed.
        """
        if not ad_cfg.id:
            # New ads are not considered "changed"
            return False

        # Calculate hash on original config to match what was stored
        current_hash = AdPartial.model_validate(ad_cfg_orig).update_content_hash().content_hash
        stored_hash = ad_cfg_orig.get("content_hash")

        LOG.debug("Hash comparison for [%s]:", ad_file_relative)
        LOG.debug("    Stored hash: %s", stored_hash)
        LOG.debug("    Current hash: %s", current_hash)

        if stored_hash and current_hash != stored_hash:
            LOG.info("Changes detected in ad [%s], will republish", ad_file_relative)
            # Update hash in original configuration
            ad_cfg_orig["content_hash"] = current_hash
            return True

        return False

    def load_ads(self, *, ignore_inactive:bool = True, exclude_ads_with_id:bool = True) -> list[tuple[str, Ad, dict[str, Any]]]:
        """
        Load and validate all ad config files, optionally filtering out inactive or already-published ads.

        Args:
            ignore_inactive (bool):
                Skip ads with `active=False`.
            exclude_ads_with_id (bool):
                Skip ads whose raw data already contains an `id`, i.e. was published before.

        Returns:
            list[tuple[str, Ad, dict[str, Any]]]:
            Tuples of (file_path, validated Ad model, original raw data).
        """
        LOG.info("Searching for ad config files...")

        ad_files:dict[str, str] = {}
        data_root_dir = os.path.dirname(self.config_file_path)
        for file_pattern in self.config.ad_files:
            for ad_file in glob.glob(file_pattern, root_dir = data_root_dir, flags = glob.GLOBSTAR | glob.BRACE | glob.EXTGLOB):
                if not str(ad_file).endswith("ad_fields.yaml"):
                    ad_files[abspath(ad_file, relative_to = data_root_dir)] = ad_file
        LOG.info(" -> found %s", pluralize("ad config file", ad_files))
        if not ad_files:
            return []

        ids = []
        use_specific_ads = False
        selectors = self.ads_selector.split(",")

        if _NUMERIC_IDS_RE.match(self.ads_selector):
            ids = [int(n) for n in self.ads_selector.split(",")]
            use_specific_ads = True
            LOG.info("Start fetch task for the ad(s) with id(s):")
            LOG.info(" | ".join([str(id_) for id_ in ids]))

        ads = []
        for ad_file, ad_file_relative in sorted(ad_files.items()):
            ad_cfg_orig:dict[str, Any] = dicts.load_dict(ad_file, "ad")
            ad_cfg:Ad = self.load_ad(ad_cfg_orig)

            if ignore_inactive and not ad_cfg.active:
                LOG.info(" -> SKIPPED: inactive ad [%s]", ad_file_relative)
                continue

            if use_specific_ads:
                if ad_cfg.id not in ids:
                    LOG.info(" -> SKIPPED: ad [%s] is not in list of given ids.", ad_file_relative)
                    continue
            else:
                # Check if ad should be included based on selectors
                should_include = False

                # Check for 'changed' selector
                if "changed" in selectors and self.__check_ad_changed(ad_cfg, ad_cfg_orig, ad_file_relative):
                    should_include = True

                # Check for 'new' selector
                if "new" in selectors and (not ad_cfg.id or not exclude_ads_with_id):
                    should_include = True
                elif "new" in selectors and ad_cfg.id and exclude_ads_with_id:
                    LOG.info(" -> SKIPPED: ad [%s] is not new. already has an id assigned.", ad_file_relative)

                # Check for 'due' selector
                if "due" in selectors:
                    # For 'due' selector, check if the ad is due for republication based on interval
                    if self.__check_ad_republication(ad_cfg, ad_file_relative):
                        should_include = True

                # Check for 'all' selector (always include)
                if "all" in selectors:
                    should_include = True

                if not should_include:
                    continue

            ensure(self.__get_description(ad_cfg, with_affixes = False), f"-> property [description] not specified @ [{ad_file}]")
            self.__get_description(ad_cfg, with_affixes = True)  # validates complete description

            if ad_cfg.category:
                resolved_category_id = self.categories.get(ad_cfg.category)
                if not resolved_category_id and ">" in ad_cfg.category:
                    # this maps actually to the sonstiges/weiteres sub-category
                    parent_category = ad_cfg.category.rpartition(">")[0].strip()
                    resolved_category_id = self.categories.get(parent_category)
                    if resolved_category_id:
                        LOG.warning("Category [%s] unknown. Using category [%s] with ID [%s] instead.", ad_cfg.category, parent_category, resolved_category_id)

                if resolved_category_id:
                    ad_cfg.category = resolved_category_id

            if ad_cfg.images:
                images = []
                ad_dir = os.path.dirname(ad_file)
                for image_pattern in ad_cfg.images:
                    pattern_images = set()
                    for image_file in glob.glob(image_pattern, root_dir = ad_dir, flags = glob.GLOBSTAR | glob.BRACE | glob.EXTGLOB):
                        _, image_file_ext = os.path.splitext(image_file)
                        ensure(image_file_ext.lower() in {".gif", ".jpg", ".jpeg", ".png"}, f"Unsupported image file type [{image_file}]")
                        if os.path.isabs(image_file):
                            pattern_images.add(image_file)
                        else:
                            pattern_images.add(abspath(image_file, relative_to = ad_file))
                    images.extend(sorted(pattern_images))
                ensure(images or not ad_cfg.images, f"No images found for given file patterns {ad_cfg.images} at {ad_dir}")
                ad_cfg.images = list(dict.fromkeys(images))

            LOG.info(" -> LOADED: ad [%s]", ad_file_relative)
            ads.append((ad_file, ad_cfg, ad_cfg_orig))

        LOG.info("Loaded %s", pluralize("ad", ads))
        return ads

    def load_ad(self, ad_cfg_orig:dict[str, Any]) -> Ad:
        return AdPartial.model_validate(ad_cfg_orig).to_ad(self.config.ad_defaults)

    async def check_and_wait_for_captcha(self, *, is_login_page:bool = True) -> None:
        try:
            captcha_timeout = self._timeout("captcha_detection")
            await self.web_find(By.CSS_SELECTOR, "iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']", timeout = captcha_timeout)

            if not is_login_page and self.config.captcha.auto_restart:
                LOG.warning("Captcha recognized - auto-restart enabled, abort run...")
                raise CaptchaEncountered(misc.parse_duration(self.config.captcha.restart_delay))

            LOG.warning("############################################")
            LOG.warning("# Captcha present! Please solve the captcha.")
            LOG.warning("############################################")

            if not is_login_page:
                await self.web_scroll_page_down()

            await ainput(_("Press a key to continue..."))
        except TimeoutError:
            page_context = "login page" if is_login_page else "publish flow"
            LOG.debug("No captcha detected within timeout on %s", page_context)

    async def login(self) -> None:
        self._login_detection_diagnostics_captured = False
        # Kleinanzeigen/Chromium can occasionally need more than the upstream
        # default 15s before the initial logged-in check finishes. A premature
        # timeout here happens before any ad is touched, so give navigation a
        # stable 30s window; manager-side recovery may then retry safely.
        sso_navigation_timeout = max(float(self._timeout("page_load")), 30.0)
        pre_login_gdpr_timeout = self._timeout("quick_dom")

        LOG.info("Checking if already logged in...")
        landing_url = f"{self.root_url}"
        try:
            await self.web_open(landing_url, timeout = sso_navigation_timeout)
        except (TimeoutError, ProtocolException) as navigation_error:
            landing_state = await self.__wait_for_usable_page_after_navigation(landing_url, timeout = 12.0)
            if not landing_state:
                raise
            LOG.warning(
                "Initial Kleinanzeigen page reported %s, but its DOM is already usable at %s (readyState=%s); continuing login detection.",
                type(navigation_error).__name__, landing_state.get("path"), landing_state.get("readyState"),
            )
        try:
            await self._click_gdpr_banner(timeout = pre_login_gdpr_timeout)
        except TimeoutError:
            LOG.debug("No GDPR banner detected before login")

        detection_result = await self.get_login_state(capture_diagnostics = False)
        if detection_result.is_logged_in:
            LOG.info("Already logged in. Skipping login.")
            return

        LOG.debug("Navigating to SSO login page (Auth0)...")
        # m-einloggen-sso.html triggers immediate server-side redirect to Auth0
        # This avoids waiting for JS on m-einloggen.html which may not execute in headless mode
        try:
            await self.web_open(f"{self.root_url}/m-einloggen-sso.html", timeout = sso_navigation_timeout)
        except TimeoutError:
            LOG.warning("Timeout navigating to SSO login page after %.1fs", sso_navigation_timeout)
            await self._capture_login_detection_diagnostics_if_enabled(
                base_prefix = "login_detection_sso_navigation_timeout",
                pause_banner_message = "# SSO navigation timed out. Browser is paused for manual inspection.",
            )
            raise

        try:
            await self.fill_login_data_and_send()
            await self.handle_after_login_logic()
        except (AssertionError, TimeoutError):
            # AssertionError is intentionally part of auth-boundary control flow so
            # diagnostics are captured before the original error is re-raised.
            await self._capture_login_detection_diagnostics_if_enabled(
                base_prefix = "login_detection_auth0_flow_failure",
                pause_banner_message = "# Auth0 login flow failed. Browser is paused for manual inspection.",
            )
            raise

        await self._dismiss_consent_banner()

        detection_result = await self.get_login_state(capture_diagnostics = False)
        if detection_result.is_logged_in:
            LOG.info("Login confirmed.")
            return

        current_url = self._current_page_url()
        LOG.debug("Login detection reason after attempt is %s", detection_result.reason.name)
        LOG.warning("Login could not be confirmed after Auth0 flow (url=%s)", current_url)
        await self._capture_login_detection_diagnostics_if_enabled(
            base_prefix = f"login_detection_{detection_result.reason.name.lower()}",
            pause_banner_message = "# Login confirmation failed after Auth0 flow. Browser is paused for manual inspection.",
        )
        raise AssertionError(_("Login could not be confirmed after Auth0 flow (reason=%s, url=%s)") % (detection_result.reason.name, current_url))

    def _current_page_url(self) -> str:
        page = getattr(self, "page", None)
        if page is None:
            return "unknown"
        url = getattr(page, "url", None)
        if not isinstance(url, str) or not url:
            return "unknown"

        parsed = urllib_parse.urlparse(url)
        host = parsed.hostname or parsed.netloc.split("@")[-1]
        netloc = f"{host}:{parsed.port}" if parsed.port is not None and host else host
        sanitized = urllib_parse.urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
        return sanitized or "unknown"

    async def _wait_for_auth0_login_context(self) -> None:
        redirect_timeout = self._timeout("login_detection")
        try:
            await self.web_await(
                lambda: "login.kleinanzeigen.de" in self._current_page_url() or "/u/login" in self._current_page_url(),
                timeout = redirect_timeout,
                timeout_error_message = f"Auth0 redirect did not start within {redirect_timeout} seconds",
                apply_multiplier = False,
            )
        except TimeoutError as ex:
            current_url = self._current_page_url()
            raise AssertionError(_("Auth0 redirect not detected (url=%s)") % current_url) from ex

    async def _wait_for_auth0_password_step(self) -> None:
        password_step_timeout = self._timeout("login_detection")
        try:
            await self.web_await(
                lambda: "/u/login/password" in self._current_page_url(),
                timeout = password_step_timeout,
                timeout_error_message = f"Auth0 password page not reached within {password_step_timeout} seconds",
                apply_multiplier = False,
            )
        except TimeoutError as ex:
            current_url = self._current_page_url()
            raise AssertionError(_("Auth0 password step not reached (url=%s)") % current_url) from ex

    async def _wait_for_post_auth0_submit_transition(self) -> None:
        post_submit_timeout = self._timeout("login_detection")
        quick_dom_timeout = self._timeout("quick_dom")
        fallback_max_ms = max(700, int(quick_dom_timeout * 1_000))
        fallback_min_ms = max(300, fallback_max_ms // 2)

        try:
            await self.web_await(
                lambda: self._is_valid_post_auth0_destination(self._current_page_url()),
                timeout = post_submit_timeout,
                timeout_error_message = f"Auth0 post-submit transition did not complete within {post_submit_timeout} seconds",
                apply_multiplier = False,
            )
            return
        except TimeoutError:
            LOG.debug("Post-submit transition not detected via URL, checking logged-in selectors")

        login_confirmed = False
        try:
            login_confirmed = await asyncio.wait_for(self.is_logged_in(), timeout = post_submit_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            LOG.debug("Post-submit login verification did not complete within %.1fs", post_submit_timeout)

        if login_confirmed:
            return

        LOG.debug("Auth0 post-submit verification remained inconclusive; applying bounded fallback pause")
        await self.web_sleep(min_ms = fallback_min_ms, max_ms = fallback_max_ms)

        try:
            if await asyncio.wait_for(self.is_logged_in(), timeout = quick_dom_timeout):
                return
        except (TimeoutError, asyncio.TimeoutError):
            LOG.debug("Final post-submit login confirmation did not complete within %.1fs", quick_dom_timeout)

        current_url = self._current_page_url()
        raise TimeoutError(_("Auth0 post-submit verification remained inconclusive (url=%s)") % current_url)

    def _is_valid_post_auth0_destination(self, url:str) -> bool:
        if not url or url in {"unknown", "about:blank"}:
            return False

        parsed = urllib_parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()

        if host != "kleinanzeigen.de" and not host.endswith(".kleinanzeigen.de"):
            return False
        if host == "login.kleinanzeigen.de":
            return False
        if path.startswith("/u/login"):
            return False

        return "error" not in path

    async def fill_login_data_and_send(self) -> None:
        """Auth0 2-step login via m-einloggen-sso.html (server-side redirect, no JS needed).

        Step 1: /u/login/identifier - email
        Step 2: /u/login/password   - password
        """
        LOG.info("Logging in...")

        await self._wait_for_auth0_login_context()

        # Step 1: email identifier
        LOG.debug("Auth0 Step 1: entering email...")
        await self.web_input(By.ID, "username", self.config.login.username)
        await self.web_click(By.CSS_SELECTOR, "button[type='submit']")

        # Step 2: wait for password page then enter password
        LOG.debug("Waiting for Auth0 password page...")
        await self._wait_for_auth0_password_step()

        LOG.debug("Auth0 Step 2: entering password...")
        await self.web_input(By.CSS_SELECTOR, "input[type='password']", self.config.login.password)
        await self.check_and_wait_for_captcha(is_login_page = True)
        await self.web_click(By.CSS_SELECTOR, "button[type='submit']")
        await self._wait_for_post_auth0_submit_transition()
        LOG.debug("Auth0 login submitted.")

    async def handle_after_login_logic(self) -> None:
        try:
            await self._check_sms_verification()
        except TimeoutError:
            LOG.debug("No SMS verification prompt detected after login")

        try:
            await self._check_email_verification()
        except TimeoutError:
            LOG.debug("No email verification prompt detected after login")

        try:
            LOG.debug("Handling GDPR disclaimer...")
            await self._click_gdpr_banner()
        except TimeoutError:
            LOG.debug("GDPR banner not found or timed out")

    async def _check_sms_verification(self) -> None:
        sms_timeout = self._timeout("sms_verification")
        await self.web_find(By.TEXT, "Wir haben dir gerade einen 6-stelligen Code für die Telefonnummer", timeout = sms_timeout)
        LOG.warning("############################################")
        LOG.warning("# Device verification message detected. Please follow the instruction displayed in the Browser.")
        LOG.warning("############################################")
        await ainput(_("Press ENTER when done..."))

    async def _dismiss_consent_banner(self) -> None:
        """Dismiss the GDPR/TCF consent banner if it is present.

        This banner can appear on any page navigation (not just after login) and blocks
        all form interaction until dismissed. Uses a short timeout to avoid slowing down
        the flow when the banner is already gone.
        """
        try:
            banner_timeout = self._timeout("quick_dom")
            await self.web_find(By.ID, "gdpr-banner-accept", timeout = banner_timeout)
            LOG.debug("Consent banner detected, clicking 'Alle akzeptieren'...")
            await self.web_click(By.ID, "gdpr-banner-accept")
        except TimeoutError:
            LOG.debug("Consent banner not present; continuing without dismissal")

    async def _check_email_verification(self) -> None:
        email_timeout = self._timeout("email_verification")
        await self.web_find(By.TEXT, "Um dein Konto zu schützen haben wir dir eine E-Mail geschickt", timeout = email_timeout)
        LOG.warning("############################################")
        LOG.warning("# Device verification message detected. Please follow the instruction displayed in the Browser.")
        LOG.warning("############################################")
        await ainput(_("Press ENTER when done..."))

    async def _click_gdpr_banner(self, *, timeout:float | None = None) -> None:
        gdpr_timeout = self._timeout("quick_dom") if timeout is None else timeout
        await self.web_find(By.ID, "gdpr-banner-accept", timeout = gdpr_timeout)
        await self.web_click(By.ID, "gdpr-banner-accept", timeout = gdpr_timeout)

    async def get_login_state(self, *, capture_diagnostics:bool = True) -> LoginDetectionResult:
        """Determine login status using DOM-first detection and return result with reason.

        Order:
        1) DOM-based logged-in marker check
        2) Logged-out CTA check
        3) If inconclusive, optionally capture diagnostics and return a timeout reason
        """
        # Prefer DOM-based checks first to minimize bot-like behavior and avoid
        # fragile API probing side effects. Server-side auth probing was removed.
        if await self._has_logged_in_marker():
            return LoginDetectionResult(is_logged_in = True, reason = LoginDetectionReason.USER_INFO_MATCH)

        if await self._has_logged_out_cta(log_timeout = False):
            return LoginDetectionResult(is_logged_in = False, reason = LoginDetectionReason.CTA_MATCH)

        if capture_diagnostics:
            await self._capture_login_detection_diagnostics_if_enabled(
                base_prefix = "login_detection_selector_timeout",
                pause_banner_message = "# Login detection remained inconclusive. Browser is paused for manual inspection.",
            )
        return LoginDetectionResult(is_logged_in = False, reason = LoginDetectionReason.SELECTOR_TIMEOUT)

    def _diagnostics_output_dir(self) -> Path:
        diagnostics = getattr(self.config, "diagnostics", None)
        if diagnostics is not None and diagnostics.output_dir and diagnostics.output_dir.strip():
            return Path(abspath(diagnostics.output_dir, relative_to = self.config_file_path)).resolve()

        workspace = self._workspace_or_raise()
        xdg_paths.ensure_directory(workspace.diagnostics_dir, "diagnostics directory")
        return workspace.diagnostics_dir

    async def _capture_login_detection_diagnostics_if_enabled(
        self,
        *,
        base_prefix:str = "login_detection_inconclusive",
        pause_banner_message:str = "# Login detection remained inconclusive. Browser is paused for manual inspection.",
    ) -> None:
        cfg = getattr(self.config, "diagnostics", None)
        if cfg is None or not cfg.capture_on.login_detection:
            return
        if self._login_detection_diagnostics_captured:
            return
        archive = await self._capture_login_debug_zip(base_prefix)
        if archive is None:
            return
        self._login_detection_diagnostics_captured = True
        if cfg.pause_on_login_detection_failure and getattr(sys.stdin, "isatty", lambda: False)():
            LOG.warning("############################################")
            LOG.warning(pause_banner_message)
            LOG.warning("############################################")
            await ainput(_("Press a key to continue..."))

    @staticmethod
    def _debug_redact_text(value:str) -> str:
        """Remove credentials/session material while preserving useful diagnostics."""
        text = str(value or "")
        text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<redacted-email>", text)
        text = re.sub(
            r"(?i)((?:authorization|cookie|set-cookie|password|passwd|access[_-]?token|refresh[_-]?token|csrf|secret|session[_-]?id|upload[_-]?session[_-]?id)\s*[:=]\s*)([^\s,;]+)",
            lambda match: match.group(1) + "<redacted>",
            text,
        )
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1<redacted>", text)
        return text

    @classmethod
    def _debug_redact_value(cls, value:Any, key:str = "") -> Any:
        lowered = str(key or "").casefold()
        sensitive_parts = (
            "authorization", "cookie", "password", "passwd", "access_token", "refresh_token",
            "csrf", "secret", "session_id", "upload_session_id", "username", "email",
        )
        if any(part in lowered for part in sensitive_parts):
            return "<redacted>"
        if isinstance(value, dict):
            return {str(k): cls._debug_redact_value(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._debug_redact_value(v, key) for v in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str):
            return cls._debug_redact_text(value)
        return value

    @classmethod
    def _debug_write_json(cls, directory:Path, filename:str, payload:Any) -> None:
        directory.mkdir(parents = True, exist_ok = True)
        (directory / filename).write_text(
            json.dumps(cls._debug_redact_value(payload), ensure_ascii = False, indent = 2, default = str),
            "utf-8",
        )

    @classmethod
    def _debug_write_text(cls, directory:Path, filename:str, value:str) -> None:
        directory.mkdir(parents = True, exist_ok = True)
        (directory / filename).write_text(cls._debug_redact_text(value), "utf-8")

    @staticmethod
    def _debug_cleanup_archives(output_dir:Path) -> None:
        try:
            rows = sorted(
                output_dir.glob("kleinanzeigen-*-debug_*.zip"),
                key = lambda row: row.stat().st_mtime,
                reverse = True,
            )
            for row in rows[PUBLISH_DEBUG_KEEP:]:
                try:
                    row.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    async def _capture_safe_page_debug_state(self) -> dict[str, Any]:
        """Capture useful DOM state without cookies, localStorage, headers or raw page scripts."""
        try:
            result = await asyncio.wait_for(self.web_execute(r"""(() => {
                const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                };
                const safeControl = el => {
                    const name = String(el.getAttribute('name') || '');
                    const id = String(el.id || '');
                    const sensitive = /csrf|password|token|secret|session|tracking|email|phone|contactName|locationId|zipCode/i.test(name + ' ' + id);
                    const usefulValue = /category|parentCategoryId|adType|shipping|price|condition|attributeMap/i.test(name + ' ' + id);
                    return {
                        tag: el.tagName.toLowerCase(), id, name,
                        type: String(el.getAttribute('type') || ''),
                        visible: visible(el), disabled: Boolean(el.disabled), checked: Boolean(el.checked),
                        text: normalize(el.innerText || el.textContent || '').slice(0, 300),
                        value: sensitive ? '<redacted>' : (usefulValue ? String(el.value || '').slice(0, 500) : '')
                    };
                };
                const categoryLinks = Array.from(document.querySelectorAll('[id^="cat_"]')).slice(0, 500).map(el => ({
                    id: String(el.id || ''), text: normalize(el.textContent), href: String(el.getAttribute('href') || ''), visible: visible(el)
                }));
                const categoryForm = document.getElementById('postad-step1-frm');
                const categoryValues = categoryForm ? Array.from(categoryForm.querySelectorAll('input,textarea,select'))
                    .filter(el => /^(?:parentCategoryId|categoryId)$/.test(String(el.name || '')) || /attributeMap/.test(String(el.name || '')))
                    .map(safeControl) : [];
                const experiments = window.__KA_EXPERIMENTS__ || {};
                return {
                    path: location.pathname,
                    hash: location.hash,
                    title: document.title,
                    readyState: document.readyState,
                    pageType: String(window.pageType || window.kaGaConfig?.pageType || ''),
                    postAdExperiment: String(experiments['prpl-831_postad_extraction'] || ''),
                    bodyText: normalize(document.body?.innerText || '').slice(0, 16000),
                    publishForm: {
                        titlePresent: Boolean(document.getElementById('ad-title')),
                        descriptionPresent: Boolean(document.getElementById('ad-description')),
                        categoryPath: normalize(document.getElementById('ad-category-path')?.textContent || ''),
                        categoryPickerPresent: Boolean(document.getElementById('ad-category-picker'))
                    },
                    categoryPage: {
                        linkCount: categoryLinks.length,
                        links: categoryLinks,
                        formPresent: Boolean(categoryForm),
                        formClass: categoryForm ? String(categoryForm.className || '') : '',
                        formVisible: Boolean(categoryForm && visible(categoryForm)),
                        values: categoryValues,
                        buttons: Array.from(document.querySelectorAll('button')).filter(visible).slice(0, 80).map(safeControl)
                    },
                    controls: Array.from(document.querySelectorAll('input,textarea,select,button,a')).filter(visible).slice(0, 250).map(safeControl)
                };
            })()"""), timeout = PUBLISH_DEBUG_PAGE_TIMEOUT_SECONDS)
            return result if isinstance(result, dict) else {"capture_error": f"unexpected result: {result!r}"}
        except Exception as error:  # noqa: BLE001
            return {
                "capture_error": f"{type(error).__name__}: {error}",
                "page_url": self._current_page_url(),
            }

    async def _capture_login_debug_zip(self, base_prefix:str) -> Path | None:
        """Create one sanitized ZIP for login/navigation diagnostics."""
        try:
            output_dir = self._diagnostics_output_dir()
            output_dir.mkdir(parents = True, exist_ok = True)
        except Exception as error:  # noqa: BLE001
            LOG.warning("Login diagnostics ZIP directory unavailable: %s", error)
            return None

        stamp = misc.now().strftime("%Y%m%dT%H%M%S")
        safe_prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", base_prefix).strip("-._")[:60] or "login"
        final_zip = output_dir / f"kleinanzeigen-login-debug_{stamp}_{safe_prefix}_FEHLER.zip"
        work_dir = Path(tempfile.mkdtemp(prefix = "ka-login-debug-"))
        raw_capture_dir = work_dir / "raw-capture"
        raw_capture_dir.mkdir(parents = True, exist_ok = True)
        try:
            page_state = await self._capture_safe_page_debug_state()
            self._debug_write_text(
                work_dir,
                "00-summary.txt",
                f"Zeit: {misc.now().isoformat(timespec='seconds')}\nTyp: {base_prefix}\n"
                "Hinweis: Zugangsdaten, Tokens, Cookies, Browserprofil und Local Storage sind nicht Bestandteil dieses Pakets.\n",
            )
            self._debug_write_json(work_dir, "01-page-state.json", page_state)
            try:
                config_payload = self.config.model_dump(mode = "json")
            except Exception:  # noqa: BLE001
                config_payload = {"config_file": str(self.config_file_path)}
            self._debug_write_json(work_dir, "02-bot-config-sanitized.json", config_payload)
            self._debug_write_json(work_dir, "03-runtime.json", {
                "kleinanzeigen_bot_version": __version__,
                "python": sys.version,
                "page": urllib_parse.urlparse(self._current_page_url()).path,
            })
            if self.log_file_path:
                try:
                    log_text = Path(self.log_file_path).read_text("utf-8", errors = "replace")
                    self._debug_write_text(work_dir, "04-log-tail.txt", log_text[-300_000:])
                except OSError as error:
                    self._debug_write_text(work_dir, "04-log-tail-error.txt", str(error))
            page = getattr(self, "page", None)
            if page is not None:
                try:
                    await diagnostics.capture_diagnostics(
                        output_dir = raw_capture_dir, base_prefix = "page", page = page, copy_log = False
                    )
                    screenshots = sorted(raw_capture_dir.glob("*.png"))
                    if screenshots:
                        shutil.copy2(screenshots[-1], work_dir / "05-screenshot.png")
                except Exception as capture_error:  # noqa: BLE001
                    self._debug_write_text(work_dir, "05-screenshot-error.txt", str(capture_error))
            with zipfile.ZipFile(final_zip, "w", compression = zipfile.ZIP_DEFLATED, allowZip64 = True) as archive:
                for path in sorted(work_dir.iterdir()):
                    if path.is_file():
                        archive.write(path, path.name)
            self._debug_cleanup_archives(output_dir)
            LOG.warning("Login diagnostics ZIP saved: %s", final_zip)
            return final_zip
        except Exception as error:  # noqa: BLE001
            LOG.warning("Login diagnostics ZIP capture failed: %s", error)
            return None
        finally:
            shutil.rmtree(work_dir, ignore_errors = True)

    async def _capture_publish_debug_zip(
        self,
        ad_cfg:Ad,
        ad_cfg_orig:dict[str, Any],
        ad_file:str,
        attempt:int,
        exc:Exception,
    ) -> Path | None:
        """Write one shareable ZIP per publish failure, modelled after Vinted diagnostics."""
        try:
            output_dir = self._diagnostics_output_dir()
            output_dir.mkdir(parents = True, exist_ok = True)
        except Exception as error:  # noqa: BLE001
            LOG.warning("Diagnostics ZIP directory unavailable: %s", error)
            return None

        stamp = misc.now().strftime("%Y%m%dT%H%M%S")
        safe_subject = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(ad_file).stem).strip("-._")[:70] or "anzeige"
        final_zip = output_dir / f"kleinanzeigen-publish-debug_{stamp}_attempt{attempt}_{safe_subject}_FEHLER.zip"
        work_dir = Path(tempfile.mkdtemp(prefix = "ka-publish-debug-"))
        raw_capture_dir = work_dir / "raw-capture"
        raw_capture_dir.mkdir(parents = True, exist_ok = True)
        try:
            page_url = self._current_page_url()
            try:
                parsed_url = urllib_parse.urlparse(page_url)
                page_location = parsed_url.path + (("#" + parsed_url.fragment) if parsed_url.fragment else "")
            except Exception:  # noqa: BLE001
                page_location = page_url

            summary = (
                f"Zeit: {misc.now().isoformat(timespec='seconds')}\n"
                f"Versuch: {attempt}/{PUBLISH_MAX_RETRIES}\n"
                f"Anzeige: {ad_cfg.title}\n"
                f"Seite: {page_location}\n"
                f"Fehler: {type(exc).__name__}: {exc}\n"
                "Hinweis: Zugangsdaten, Tokens, Cookies, Browserprofil und Local Storage sind nicht Bestandteil dieses Pakets.\n"
            )
            self._debug_write_text(work_dir, "00-summary.txt", summary)
            self._debug_write_json(work_dir, "01-exception.json", {
                "timestamp": misc.now().isoformat(timespec = "seconds"),
                "attempt": attempt,
                "page": page_location,
                "exception": {"type": type(exc).__name__, "message": str(exc), "repr": repr(exc)},
            })

            # Create a minimal ZIP immediately. Even if the browser itself is so stuck
            # that page/screenshot capture cannot complete, the user still gets one
            # concrete diagnostic artifact instead of an empty debug directory.
            with zipfile.ZipFile(final_zip, "w", compression = zipfile.ZIP_DEFLATED, allowZip64 = True) as archive:
                archive.write(work_dir / "00-summary.txt", "00-summary.txt")
                archive.write(work_dir / "01-exception.json", "01-exception.json")

            page_state = await self._capture_safe_page_debug_state()
            self._debug_write_json(work_dir, "02-page-state.json", page_state)
            self._debug_write_json(work_dir, "03-ad-effective.json", ad_cfg.model_dump(mode = "json"))
            self._debug_write_json(work_dir, "04-ad-original.json", ad_cfg_orig)
            try:
                config_payload = self.config.model_dump(mode = "json")
            except Exception:  # noqa: BLE001
                config_payload = {"config_file": str(self.config_file_path)}
            self._debug_write_json(work_dir, "05-bot-config-sanitized.json", config_payload)
            self._debug_write_json(work_dir, "06-runtime.json", {
                "kleinanzeigen_bot_version": __version__,
                "python": sys.version,
                "page": page_location,
                "ad_file_name": Path(ad_file).name,
            })

            if self.log_file_path:
                try:
                    log_path = Path(self.log_file_path)
                    log_text = log_path.read_text("utf-8", errors = "replace")
                    self._debug_write_text(work_dir, "07-log-tail.txt", log_text[-300_000:])
                except OSError as error:
                    self._debug_write_text(work_dir, "07-log-tail-error.txt", str(error))

            # Reuse the upstream screenshot implementation, but bound it strictly: diagnostics
            # must never become the next place where a stuck browser can block forever. Raw
            # HTML/JSON stays in /tmp and is never copied into the shareable ZIP.
            page = getattr(self, "page", None)
            if page is not None:
                capture_error:Exception | None = None
                try:
                    await asyncio.wait_for(
                        diagnostics.capture_diagnostics(
                            output_dir = raw_capture_dir,
                            base_prefix = "page",
                            attempt = attempt,
                            subject = safe_subject,
                            page = page,
                            copy_log = False,
                        ),
                        timeout = PUBLISH_DEBUG_SCREENSHOT_TIMEOUT_SECONDS,
                    )
                except Exception as error:  # noqa: BLE001
                    capture_error = error
                screenshots = sorted(raw_capture_dir.glob("*.png"))
                if screenshots:
                    try:
                        shutil.copy2(screenshots[-1], work_dir / "08-screenshot.png")
                    except OSError as error:
                        capture_error = capture_error or error
                if capture_error is not None:
                    self._debug_write_text(work_dir, "08-screenshot-error.txt", f"{type(capture_error).__name__}: {capture_error}")

            with zipfile.ZipFile(final_zip, "w", compression = zipfile.ZIP_DEFLATED, allowZip64 = True) as archive:
                for path in sorted(work_dir.iterdir()):
                    if path.is_file():
                        archive.write(path, path.name)
            self._debug_cleanup_archives(output_dir)
            LOG.warning("Publish diagnostics ZIP saved: %s", final_zip)
            return final_zip
        except Exception as error:  # noqa: BLE001
            LOG.warning("Diagnostics ZIP capture failed during publish error handling: %s", error)
            return None
        finally:
            shutil.rmtree(work_dir, ignore_errors = True)

    async def _capture_publish_error_diagnostics_if_enabled(
        self,
        ad_cfg:Ad,
        ad_cfg_orig:dict[str, Any],
        ad_file:str,
        attempt:int,
        exc:Exception,
    ) -> None:
        """Capture one sanitized ZIP for a publish failure when diagnostics are enabled."""
        cfg = getattr(self.config, "diagnostics", None)
        if cfg is None or not cfg.capture_on.publish:
            return
        try:
            await asyncio.wait_for(
                self._capture_publish_debug_zip(ad_cfg, ad_cfg_orig, ad_file, attempt, exc),
                timeout = PUBLISH_DEBUG_CAPTURE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOG.warning(
                "Publish diagnostics capture exceeded %.0fs; continuing failure handling without blocking.",
                PUBLISH_DEBUG_CAPTURE_TIMEOUT_SECONDS,
            )
        except Exception as capture_error:  # noqa: BLE001
            LOG.warning("Publish diagnostics capture failed: %s", capture_error)

    async def _has_logged_in_marker(self) -> bool:
        # Use login_detection timeout (10s default) instead of default (5s)
        # to allow sufficient time for client-side JavaScript rendering after page load.
        # This is especially important for older sessions (20+ days) that require
        # additional server-side validation time.
        login_check_timeout = self._timeout("login_detection")
        effective_timeout = self._effective_timeout("login_detection")
        username = self.config.login.username.lower()
        LOG.debug(
            "Starting login detection (timeout: %.1fs base, %.1fs effective with multiplier/backoff)",
            login_check_timeout,
            effective_timeout,
        )
        quick_dom_timeout = self._timeout("quick_dom")
        tried_login_selectors = _format_login_detection_selectors(_LOGIN_DETECTION_SELECTORS)

        try:
            user_info, matched_selector = await self.web_text_first_available(
                _LOGIN_DETECTION_SELECTORS,
                timeout = quick_dom_timeout,
                key = "quick_dom",
                description = "login_detection(quick_logged_in)",
            )
            if username in user_info.lower():
                matched_selector_display = (
                    f"{_LOGIN_DETECTION_SELECTORS[matched_selector][0].name}={_LOGIN_DETECTION_SELECTORS[matched_selector][1]}"
                    if 0 <= matched_selector < len(_LOGIN_DETECTION_SELECTORS)
                    else f"selector_index_{matched_selector}"
                )
                LOG.debug("Login detected via login detection selector '%s'", matched_selector_display)
                return True
        except TimeoutError:
            LOG.debug("No login detected via configured login detection selectors (%s)", tried_login_selectors)

        try:
            user_info, matched_selector = await self.web_text_first_available(
                _LOGIN_DETECTION_SELECTORS,
                timeout = login_check_timeout,
                key = "login_detection",
                description = "login_detection(selector_group)",
            )
            if username in user_info.lower():
                matched_selector_display = (
                    f"{_LOGIN_DETECTION_SELECTORS[matched_selector][0].name}={_LOGIN_DETECTION_SELECTORS[matched_selector][1]}"
                    if 0 <= matched_selector < len(_LOGIN_DETECTION_SELECTORS)
                    else f"selector_index_{matched_selector}"
                )
                LOG.debug("Login detected via login detection selector '%s'", matched_selector_display)
                return True
        except TimeoutError:
            LOG.debug("Timeout waiting for login detection selector group after %.1fs", effective_timeout)

        return False

    async def is_logged_in(self) -> bool:
        if await self._has_logged_in_marker():
            return True

        tried_login_selectors = _format_login_detection_selectors(_LOGIN_DETECTION_SELECTORS)

        LOG.debug("No login detected via configured login detection selectors (%s)", tried_login_selectors)
        return False

    # NOTE: Treats any matched CTA selector with non-empty text as logged-out evidence.
    # Does NOT verify visibility (hidden/footer/off-canvas links could theoretically match).
    # PR #870 verified these selectors work correctly in practice.
    # If false positives occur, harden by adding web_check(Is.DISPLAYED) on cta_element.
    # See issue #876.
    async def _has_logged_out_cta(self, *, log_timeout:bool = True) -> bool:
        quick_dom_timeout = self._timeout("quick_dom")
        tried_logged_out_selectors = _format_login_detection_selectors(_LOGGED_OUT_CTA_SELECTORS)

        try:
            cta_element, cta_index = await self.web_find_first_available(
                _LOGGED_OUT_CTA_SELECTORS,
                timeout = quick_dom_timeout,
                key = "quick_dom",
                description = "login_detection(logged_out_cta)",
            )
            cta_text = await self._extract_visible_text(cta_element)
            if cta_text.strip():
                matched_selector_display = (
                    f"{_LOGGED_OUT_CTA_SELECTORS[cta_index][0].name}={_LOGGED_OUT_CTA_SELECTORS[cta_index][1]}"
                    if 0 <= cta_index < len(_LOGGED_OUT_CTA_SELECTORS)
                    else f"selector_index_{cta_index}"
                )
                if 0 <= cta_index < len(_LOGGED_OUT_CTA_SELECTORS):
                    LOG.debug("Fast logged-out pre-check matched selector '%s'", matched_selector_display)
                    return True
                LOG.debug("Fast logged-out pre-check got unexpected selector index '%s'; failing closed", cta_index)
                return False
        except TimeoutError:
            if log_timeout:
                LOG.debug(
                    "Fast logged-out pre-check found no login CTA (%s) within %.1fs",
                    tried_logged_out_selectors,
                    quick_dom_timeout,
                )

        return False

    async def _fetch_published_ads(self, *, strict:bool = False) -> list[dict[str, Any]]:
        """Fetch all published ads, handling API pagination.

        Args:
            strict: If True, raise PublishedAdsFetchIncompleteError when pagination data is incomplete.

        Returns:
            List of all published ads across all pages.
        """
        ads:list[dict[str, Any]] = []
        page = 1
        MAX_PAGE_LIMIT:Final[int] = 100
        SNIPPET_LIMIT:Final[int] = 500

        def _handle_incomplete_fetch(template:str, *args:Any, cause:Exception | None = None) -> None:
            if strict:
                raise PublishedAdsFetchIncompleteError(_(template) % args) from cause

        while True:
            # Safety check: don't paginate beyond reasonable limit
            if page > MAX_PAGE_LIMIT:
                LOG.warning("Stopping pagination after %s pages to avoid infinite loop", MAX_PAGE_LIMIT)
                _handle_incomplete_fetch("Stopping pagination after %s pages to avoid infinite loop", MAX_PAGE_LIMIT)
                break

            # Robustness fix: nodriver/web_request can occasionally return or raise an
            # ExceptionDetails object while fetching the management JSON endpoint. Older
            # code let that bubble up as TypeError: 'ExceptionDetails' object is not
            # subscriptable from web_scraping_mixin.py, aborting before we even reach
            # the shipping dialog. Retry once and then handle it like an incomplete
            # pagination response instead of crashing the whole publish run.
            response:Any | None = None
            for request_attempt in range(1, 3):
                try:
                    response = await self.web_request(f"{self.root_url}/m-meine-anzeigen-verwalten.json?sort=DEFAULT&pageNum={page}")
                    break
                except TimeoutError as ex:
                    LOG.warning("Pagination request failed on page %s attempt %s/2: %s", page, request_attempt, ex)
                    if request_attempt < 2:
                        await self.web_sleep(800, 1400)
                        continue
                    _handle_incomplete_fetch("Pagination request failed on page %s: %s", page, ex, cause = ex)
                    break
                except Exception as ex:
                    LOG.warning(
                        "Pagination request raised unexpected exception on page %s attempt %s/2: %s: %s",
                        page, request_attempt, type(ex).__name__, ex,
                    )
                    if request_attempt < 2:
                        await self.web_sleep(800, 1400)
                        continue
                    _handle_incomplete_fetch("Pagination request raised unexpected exception on page %s: %s", page, ex, cause = ex)
                    break

            if response is None:
                LOG.warning("No pagination response available on page %s after retries", page)
                break

            if not isinstance(response, dict):
                LOG.warning("Unexpected pagination response type on page %s: %s", page, type(response).__name__)
                _handle_incomplete_fetch("Unexpected pagination response type on page %s: %s", page, type(response).__name__)
                break

            content = response.get("content", "")
            if isinstance(content, bytearray):
                content = bytes(content)
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors = "replace")
            if not isinstance(content, str):
                LOG.warning("Unexpected response content type on page %s: %s", page, type(content).__name__)
                _handle_incomplete_fetch("Unexpected response content type on page %s: %s", page, type(content).__name__)
                break

            try:
                json_data = json.loads(content)
            except (json.JSONDecodeError, TypeError) as ex:
                if not content:
                    LOG.warning("Empty JSON response content on page %s", page)
                    _handle_incomplete_fetch("Empty JSON response content on page %s", page, cause = ex)
                    break
                snippet = content[:SNIPPET_LIMIT] + ("..." if len(content) > SNIPPET_LIMIT else "")
                LOG.warning("Failed to parse JSON response on page %s: %s (content: %s)", page, ex, snippet)
                _handle_incomplete_fetch("Failed to parse JSON response on page %s: %s (content: %s)", page, ex, snippet, cause = ex)
                break

            if not isinstance(json_data, dict):
                snippet = content[:SNIPPET_LIMIT] + ("..." if len(content) > SNIPPET_LIMIT else "")
                LOG.warning("Unexpected JSON payload on page %s (content: %s)", page, snippet)
                _handle_incomplete_fetch("Unexpected JSON payload on page %s (content: %s)", page, snippet)
                break

            page_ads = json_data.get("ads", [])
            if not isinstance(page_ads, list):
                preview = str(page_ads)
                if len(preview) > SNIPPET_LIMIT:
                    preview = preview[:SNIPPET_LIMIT] + "..."
                LOG.warning("Unexpected 'ads' type on page %s: %s value: %s", page, type(page_ads).__name__, preview)
                _handle_incomplete_fetch("Unexpected 'ads' type on page %s: %s value: %s", page, type(page_ads).__name__, preview)
                break

            filtered_page_ads:list[dict[str, Any]] = []
            rejected_count = 0
            rejected_preview:str | None = None
            for entry in page_ads:
                if isinstance(entry, dict) and "id" in entry and "state" in entry:
                    filtered_page_ads.append(entry)
                    continue
                rejected_count += 1
                if rejected_preview is None:
                    rejected_preview = repr(entry)

            if rejected_count > 0:
                preview = rejected_preview or "<none>"
                if len(preview) > SNIPPET_LIMIT:
                    preview = preview[:SNIPPET_LIMIT] + "..."
                LOG.warning("Filtered %s malformed ad entries on page %s (sample: %s)", rejected_count, page, preview)
                _handle_incomplete_fetch("Filtered %s malformed ad entries on page %s (sample: %s)", rejected_count, page, preview)

            ads.extend(filtered_page_ads)

            paging = json_data.get("paging")
            if not isinstance(paging, dict):
                LOG.debug("No paging dict found on page %s, assuming single page", page)
                break

            # Use only real API fields (confirmed from production data)
            current_page_num = misc.coerce_page_number(paging.get("pageNum"))
            total_pages = misc.coerce_page_number(paging.get("last"))

            if current_page_num is None:
                LOG.warning("Invalid 'pageNum' in paging info: %s, stopping pagination", paging.get("pageNum"))
                _handle_incomplete_fetch("Invalid 'pageNum' in paging info: %s, stopping pagination", paging.get("pageNum"))
                break

            # Stop if reached last page (only when API provides 'last')
            if total_pages is not None and current_page_num >= total_pages:
                LOG.info("Reached last page %s of %s, stopping pagination", current_page_num, total_pages)
                break

            # Safety: stop if no ads returned
            if len(page_ads) == 0:
                LOG.info("No ads found on page %s, stopping pagination", page)
                break

            LOG.debug("Page %s: fetched %s ads (numFound=%s)", page, len(page_ads), paging.get("numFound"))

            # Use API's next field for navigation (more robust than our counter)
            next_page = misc.coerce_page_number(paging.get("next"))
            if next_page is None:
                if total_pages is not None:
                    LOG.warning("Invalid 'next' page value in paging info: %s, stopping pagination", paging.get("next"))
                    _handle_incomplete_fetch("Invalid 'next' page value in paging info: %s, stopping pagination", paging.get("next"))
                else:
                    LOG.debug("No 'next' in paging on page %s, assuming last page", page)
                    _handle_incomplete_fetch("No 'next' in paging on page %s, assuming last page", page)
                break
            page = next_page

        return ads

    async def delete_ads(self, ad_cfgs:list[tuple[str, Ad, dict[str, Any]]]) -> None:
        count = 0

        published_ads = await self._fetch_published_ads()

        for ad_file, ad_cfg, _ad_cfg_orig in ad_cfgs:
            count += 1
            LOG.info("Processing %s/%s: '%s' from [%s]...", count, len(ad_cfgs), ad_cfg.title, ad_file)
            await self.delete_ad(ad_cfg, published_ads, delete_old_ads_by_title = self.config.publishing.delete_old_ads_by_title)
            await self.web_sleep()

        LOG.info("############################################")
        LOG.info("DONE: Deleted %s", pluralize("ad", count))
        LOG.info("############################################")

    async def delete_ad(self, ad_cfg:Ad, published_ads:list[dict[str, Any]], *, delete_old_ads_by_title:bool) -> bool:
        LOG.info("Deleting ad '%s' if already present...", ad_cfg.title)

        await self.web_open(f"{self.root_url}/m-meine-anzeigen.html")
        csrf_token_elem = await self.web_find(By.CSS_SELECTOR, "meta[name=_csrf]")
        csrf_token = csrf_token_elem.attrs["content"]
        ensure(csrf_token is not None, "Expected CSRF Token not found in HTML content!")

        if delete_old_ads_by_title:
            for published_ad in published_ads:
                published_ad_id = int(published_ad.get("id", -1))
                published_ad_title = published_ad.get("title", "")
                if ad_cfg.id == published_ad_id or ad_cfg.title == published_ad_title:
                    LOG.info(" -> deleting %s '%s'...", published_ad_id, published_ad_title)
                    await self.web_request(
                        url = f"{self.root_url}/m-anzeigen-loeschen.json?ids={published_ad_id}", method = "POST", headers = {"x-csrf-token": str(csrf_token)}
                    )
        elif ad_cfg.id:
            await self.web_request(
                url = f"{self.root_url}/m-anzeigen-loeschen.json?ids={ad_cfg.id}",
                method = "POST",
                headers = {"x-csrf-token": str(csrf_token)},
                valid_response_codes = [200, 404],
            )

        await self.web_sleep()
        ad_cfg.id = None
        return True

    async def extend_ads(self, ad_cfgs:list[tuple[str, Ad, dict[str, Any]]]) -> None:
        """Extends ads that are close to expiry."""
        # Fetch currently published ads from API
        published_ads = await self._fetch_published_ads()

        # Filter ads that need extension
        ads_to_extend = []
        for ad_file, ad_cfg, ad_cfg_orig in ad_cfgs:
            # Skip unpublished ads (no ID)
            if not ad_cfg.id:
                LOG.info(" -> SKIPPED: ad '%s' is not published yet", ad_cfg.title)
                continue

            # Find ad in published list
            published_ad = next((ad for ad in published_ads if ad["id"] == ad_cfg.id), None)
            if not published_ad:
                LOG.warning(" -> SKIPPED: ad '%s' (ID: %s) not found in published ads", ad_cfg.title, ad_cfg.id)
                continue

            # Skip non-active ads
            if published_ad.get("state") != "active":
                LOG.info(" -> SKIPPED: ad '%s' is not active (state: %s)", ad_cfg.title, published_ad.get("state"))
                continue

            # Check if ad is within 8-day extension window using API's endDate
            end_date_str = published_ad.get("endDate")
            if not end_date_str:
                LOG.warning(" -> SKIPPED: ad '%s' has no endDate in API response", ad_cfg.title)
                continue

            # Intentionally parsing naive datetime from kleinanzeigen API's German date format, timezone not relevant for date-only comparison
            end_date = datetime.strptime(end_date_str, "%d.%m.%Y")  # noqa: DTZ007
            days_until_expiry = (end_date.date() - misc.now().date()).days

            # Magic value 8 is kleinanzeigen.de's platform policy: extensions only possible within 8 days of expiry
            if days_until_expiry <= 8:  # noqa: PLR2004
                LOG.info(" -> ad '%s' expires in %d days, will extend", ad_cfg.title, days_until_expiry)
                ads_to_extend.append((ad_file, ad_cfg, ad_cfg_orig, published_ad))
            else:
                LOG.info(" -> SKIPPED: ad '%s' expires in %d days (can only extend within 8 days)", ad_cfg.title, days_until_expiry)

        if not ads_to_extend:
            LOG.info("No ads need extension at this time.")
            LOG.info("############################################")
            LOG.info("DONE: No ads extended.")
            LOG.info("############################################")
            return

        # Process extensions
        success_count = 0
        for idx, (ad_file, ad_cfg, ad_cfg_orig, _published_ad) in enumerate(ads_to_extend, start = 1):
            LOG.info("Processing %s/%s: '%s' from [%s]...", idx, len(ads_to_extend), ad_cfg.title, ad_file)
            if await self.extend_ad(ad_file, ad_cfg, ad_cfg_orig):
                success_count += 1
            await self.web_sleep()

        LOG.info("############################################")
        LOG.info("DONE: Extended %s", pluralize("ad", success_count))
        LOG.info("############################################")

    async def extend_ad(self, ad_file:str, ad_cfg:Ad, ad_cfg_orig:dict[str, Any]) -> bool:
        """Extends a single ad listing."""
        LOG.info("Extending ad '%s' (ID: %s)...", ad_cfg.title, ad_cfg.id)

        try:
            # Navigate to ad management page and find extend button across all pages
            extend_button_xpath = f'//li[@data-adid="{ad_cfg.id}"]//button[contains(., "Verlängern")]'

            async def find_and_click_extend_button(page_num:int) -> bool:
                """Try to find and click extend button on current page."""
                try:
                    extend_button = await self.web_find(By.XPATH, extend_button_xpath, timeout = self._timeout("quick_dom"))
                    LOG.info("Found extend button on page %s", page_num)
                    await extend_button.click()
                    return True  # Success - stop pagination
                except TimeoutError:
                    LOG.debug("Extend button not found on page %s", page_num)
                    return False  # Continue to next page

            success = await self._navigate_paginated_ad_overview(find_and_click_extend_button, page_url = f"{self.root_url}/m-meine-anzeigen.html")

            if not success:
                LOG.error(" -> FAILED: Could not find extend button for ad ID %s", ad_cfg.id)
                return False

            # Handle confirmation dialog
            # After clicking "Verlängern", a dialog appears with:
            # - Title: "Vielen Dank!"
            # - Message: "Deine Anzeige ... wurde erfolgreich verlängert."
            # - Paid bump-up option (skipped by closing dialog)
            # Simply close the dialog with the X button (aria-label="Schließen")
            try:
                dialog_close_timeout = self._timeout("quick_dom")
                await self.web_click(By.CSS_SELECTOR, 'button[aria-label="Schließen"]', timeout = dialog_close_timeout)
                LOG.debug(" -> Closed confirmation dialog")
            except TimeoutError:
                LOG.warning(" -> No confirmation dialog found, extension may have completed directly")

            # Update metadata in YAML file
            # Update updated_on to track when ad was extended
            ad_cfg_orig["updated_on"] = misc.now().isoformat(timespec = "seconds")
            dicts.save_dict(ad_file, ad_cfg_orig)

            LOG.info(" -> SUCCESS: ad extended with ID %s", ad_cfg.id)
            return True

        except TimeoutError as ex:
            LOG.error(" -> FAILED: Timeout while extending ad '%s': %s", ad_cfg.title, ex)
            return False
        except OSError as ex:
            LOG.error(" -> FAILED: Could not persist extension for ad '%s': %s", ad_cfg.title, ex)
            return False

    async def __check_publishing_result(self) -> bool:
        # Check for success messages
        return await self.web_check(By.ID, "checking-done", Is.DISPLAYED) or await self.web_check(By.ID, "not-completed", Is.DISPLAYED)

    async def _log_update_confirmation_probe(self) -> None:
        """Log the non-private markers of the page after an unclear live update.

        Kleinanzeigen changes its confirmation page regularly. This probe records
        only page metadata, headings, alerts and visible controls; the regular
        diagnostics capture additionally writes the screenshot and HTML to the
        private Home-Assistant debug directory. No additional submit click occurs.
        """
        try:
            result = await self.web_execute(r"""
(() => {
  const norm = value => (value || '').replace(/\s+/g, ' ').trim();
  const visible = element => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const texts = selector => [...document.querySelectorAll(selector)]
    .filter(visible)
    .map(element => norm(element.innerText || element.textContent || element.getAttribute('aria-label')))
    .filter(Boolean)
    .slice(0, 30);
  const pageText = norm(document.body?.innerText || '').toLocaleLowerCase('de-DE');
  return {
    url: window.location.href,
    title: document.title,
    successTerms: ['geschafft', 'erfolgreich', 'gespeichert', 'aktualisiert'].filter(term => pageText.includes(term)),
    headings: texts('h1,h2,h3,[role="heading"]'),
    alerts: texts('[role="alert"],[aria-live]'),
    controls: texts('button,a')
  };
})()
""")
            LOG.warning("Update confirmation probe after submit: %s", result)
        except Exception as error:  # noqa: BLE001
            LOG.warning("Could not inspect update confirmation page: %s", error)

    async def _publish_ad_with_watchdog(
        self, ad_file:str, ad_cfg:Ad, ad_cfg_orig:dict[str, Any], published_ads:list[dict[str, Any]]
    ) -> None:
        """Run one publish attempt with a hard wall-clock watchdog.

        asyncio.wait() is intentional here: unlike wait_for(), it does not wait
        indefinitely for a misbehaving coroutine to acknowledge cancellation.
        """
        task = asyncio.create_task(
            self.publish_ad(ad_file, ad_cfg, ad_cfg_orig, published_ads, AdUpdateStrategy.REPLACE),
            name = f"kleinanzeigen-publish-{Path(ad_file).stem}",
        )
        done, _pending = await asyncio.wait({task}, timeout = PUBLISH_ATTEMPT_WATCHDOG_SECONDS)
        if task in done:
            # Preserve normal TimeoutError / ProtocolException semantics from publish_ad.
            return task.result()

        task.cancel()
        # Give nodriver one event-loop turn to observe cancellation, but never wait
        # indefinitely for it. The run is terminated after diagnostics are written.
        await asyncio.sleep(0)
        if bool(getattr(self, "_publish_submit_boundary_active", False)):
            raise PublishSubmissionUncertainError(
                f"Publish watchdog exceeded {int(PUBLISH_ATTEMPT_WATCHDOG_SECONDS)} seconds after the submit boundary; "
                "the listing may already be online."
            )
        raise PublishAttemptWatchdogError(
            f"Publish attempt watchdog exceeded {int(PUBLISH_ATTEMPT_WATCHDOG_SECONDS)} seconds before submit."
        )

    async def publish_ads(self, ad_cfgs:list[tuple[str, Ad, dict[str, Any]]]) -> None:
        count = 0
        failed_count = 0
        max_retries = PUBLISH_MAX_RETRIES

        try:
            published_ads = await asyncio.wait_for(self._fetch_published_ads(), timeout = 60.0)
        except asyncio.TimeoutError as error:
            watchdog_error = TimeoutError("Publish preflight watchdog: published-ad lookup exceeded 60 seconds.")
            if ad_cfgs:
                first_file, first_cfg, first_orig = ad_cfgs[0]
                await self._capture_publish_error_diagnostics_if_enabled(first_cfg, first_orig, first_file, 1, watchdog_error)
            raise watchdog_error from error

        for ad_file, ad_cfg, ad_cfg_orig in ad_cfgs:
            LOG.info("Processing %s/%s: '%s' from [%s]...", count + 1, len(ad_cfgs), ad_cfg.title, ad_file)

            if [x for x in published_ads if x["id"] == ad_cfg.id and x["state"] == "paused"]:
                LOG.info("Skipping because ad is reserved")
                continue

            count += 1
            success = False

            for attempt in range(1, max_retries + 1):
                try:
                    await self._publish_ad_with_watchdog(ad_file, ad_cfg, ad_cfg_orig, published_ads)
                    success = True
                    break  # Publish succeeded, exit retry loop
                except asyncio.CancelledError:
                    raise  # Respect task cancellation
                except PublishAttemptWatchdogError as ex:
                    # A browser attempt that remains stuck for eight minutes is no longer retried
                    # blindly. Capture its current page once, fail fast and let the manager/user
                    # decide whether a fresh run is appropriate. This keeps a hard diagnostic
                    # boundary without aborting Kleinanzeigen' currently slow category hand-off.
                    await self._capture_publish_error_diagnostics_if_enabled(ad_cfg, ad_cfg_orig, ad_file, attempt, ex)
                    LOG.error(
                        "Attempt %s/%s for '%s' exceeded the %.0fs publish watchdog. Not retrying this run.",
                        attempt, max_retries, ad_cfg.title, PUBLISH_ATTEMPT_WATCHDOG_SECONDS,
                    )
                    failed_count += 1
                    break
                except PublishSubmissionUncertainError as ex:
                    await self._capture_publish_error_diagnostics_if_enabled(ad_cfg, ad_cfg_orig, ad_file, attempt, ex)
                    LOG.warning(
                        "Attempt %s/%s for '%s' reached submit boundary but failed: %s. Not retrying to prevent duplicate listings.",
                        attempt,
                        max_retries,
                        ad_cfg.title,
                        ex,
                    )
                    LOG.warning("Manual recovery required for '%s'. Check 'Meine Anzeigen' to confirm whether the ad was posted.", ad_cfg.title)
                    LOG.warning(
                        "If posted, sync local state with 'kleinanzeigen-bot download --ads=new' or 'kleinanzeigen-bot download --ads=<id>'; "
                        "otherwise rerun publish for this ad."
                    )
                    failed_count += 1
                    break
                except (TimeoutError, ProtocolException) as ex:
                    await self._capture_publish_error_diagnostics_if_enabled(ad_cfg, ad_cfg_orig, ad_file, attempt, ex)
                    if attempt >= max_retries:
                        LOG.error("All %s attempts failed for '%s': %s. Skipping ad.", max_retries, ad_cfg.title, ex)
                        failed_count += 1
                        continue

                    LOG.warning("Attempt %s/%s failed for '%s': %s. Retrying...", attempt, max_retries, ad_cfg.title, ex)
                    await self.web_sleep(2_000)  # Wait before retry

            # Check publishing result separately (no retry - ad is already submitted)
            if success:
                try:
                    publish_timeout = self._timeout("publishing_result")
                    await self.web_await(self.__check_publishing_result, timeout = publish_timeout)
                except TimeoutError:
                    LOG.warning(" -> Could not confirm publishing for '%s', but ad may be online", ad_cfg.title)

            if success and self.config.publishing.delete_old_ads == "AFTER_PUBLISH" and not self.keep_old_ads:
                await self.delete_ad(ad_cfg, published_ads, delete_old_ads_by_title = False)

        LOG.info("############################################")
        if failed_count > 0:
            LOG.info("DONE: (Re-)published %s (%s failed after retries)", pluralize("ad", count - failed_count), failed_count)
        else:
            LOG.info("DONE: (Re-)published %s", pluralize("ad", count))
        LOG.info("############################################")

    async def publish_ad(
        self, ad_file:str, ad_cfg:Ad, ad_cfg_orig:dict[str, Any], published_ads:list[dict[str, Any]], mode:AdUpdateStrategy = AdUpdateStrategy.REPLACE
    ) -> None:
        """Publish or update an ad on Kleinanzeigen.

        Args:
            ad_file: Path to the ad configuration YAML file.
            ad_cfg: The effective ad configuration with default values applied.
            ad_cfg_orig: The original ad configuration as present in the YAML file.
            published_ads: List of published ads from the API, used for deduplication
                and old ad deletion.
            mode: The ad editing strategy. REPLACE creates a new ad (full republish),
                MODIFY updates an existing ad in-place.

        Returns:
            None
        """

        self._publish_submit_boundary_active = False

        if mode == AdUpdateStrategy.REPLACE:
            if self.config.publishing.delete_old_ads == "BEFORE_PUBLISH" and not self.keep_old_ads:
                await self.delete_ad(ad_cfg, published_ads, delete_old_ads_by_title = self.config.publishing.delete_old_ads_by_title)

            # Apply auto price reduction only for REPLACE operations (actual reposts)
            # This ensures price reductions only happen on republish, not on UPDATE
            apply_auto_price_reduction(ad_cfg, ad_cfg_orig, _relative_ad_path(ad_file, self.config_file_path))

            LOG.info("Publishing ad '%s'...", ad_cfg.title)
            await self.__open_publish_form_resilient(f"{self.root_url}/p-anzeige-aufgeben-schritt2.html")
        else:
            LOG.info("Updating ad '%s'...", ad_cfg.title)
            await self.__open_publish_form_resilient(f"{self.root_url}/p-anzeige-bearbeiten.html?adId={ad_cfg.id}")

        await self._dismiss_consent_banner()

        if loggers.is_debug(LOG):
            LOG.debug(" -> effective ad meta:")
            YAML().dump(ad_cfg.model_dump(), sys.stdout)

        if ad_cfg.type == "WANTED":
            await self.web_click(By.ID, "ad-type-WANTED")

        #############################
        # set category (before title to avoid form reset clearing title)
        #############################
        await self.__set_category(ad_cfg.category, ad_file)
        await self.web_sleep()  # wait for category-dependent fields to render before setting attributes

        #############################
        # set special attributes
        #############################
        await self.__set_special_attributes(ad_cfg)

        #############################
        # set shipping type/options/costs
        #############################
        shipping_type = ad_cfg.shipping_type
        if shipping_type != "NOT_APPLICABLE":
            if ad_cfg.type == "WANTED":
                # special handling for ads of type WANTED since shipping is a special attribute for these
                if shipping_type in {"PICKUP", "SHIPPING"}:
                    shipping_value = "ja" if shipping_type == "SHIPPING" else "nein"
                    try:
                        await self.web_select(By.XPATH, "//select[contains(@id, '.versand_s')]", shipping_value)
                    except TimeoutError:
                        LOG.warning("Failed to set shipping attribute for type '%s'!", shipping_type)
            else:
                await self.__set_shipping(ad_cfg, mode)
        else:
            LOG.debug("Shipping step skipped - reason: NOT_APPLICABLE")

        #############################
        # set price
        #############################
        price_type = ad_cfg.price_type
        if price_type != "NOT_APPLICABLE":
            price_type_options = {"FIXED": 0, "NEGOTIABLE": 1, "GIVE_AWAY": 2}
            option_idx = price_type_options.get(price_type)
            if option_idx is not None:
                try:
                    await self.web_click(By.ID, "ad-price-type")
                    await self.web_click(By.ID, f"ad-price-type-menu-option-{option_idx}")
                except TimeoutError as ex:
                    raise TimeoutError(_("Failed to set price type '%s'") % price_type) from ex
            if ad_cfg.price is not None:
                await self.__react_input("ad-price-amount", str(ad_cfg.price))

        #############################
        # set sell_directly
        #############################
        sell_directly = ad_cfg.sell_directly
        try:
            if ad_cfg.shipping_type == "SHIPPING":
                if sell_directly and ad_cfg.shipping_options and price_type in {"FIXED", "NEGOTIABLE"}:
                    if not await self.web_check(By.ID, "ad-buy-now-true", Is.SELECTED):
                        await self.web_click(By.ID, "ad-buy-now-true")
                elif not await self.web_check(By.ID, "ad-buy-now-false", Is.SELECTED):
                    await self.web_click(By.ID, "ad-buy-now-false")
            else:
                # For PICKUP/other types: always opt out of buy-now if the radio exists
                try:
                    short_check = self._timeout("quick_dom")
                    if not await self.web_check(By.ID, "ad-buy-now-false", Is.SELECTED, timeout = short_check):
                        await self.web_click(By.ID, "ad-buy-now-false", timeout = short_check)
                except TimeoutError:
                    pass  # nosec
        except TimeoutError as ex:
            LOG.debug(ex, exc_info = True)

        #############################
        # set description
        #############################
        description = self.__get_description(ad_cfg, with_affixes = True)
        await self.__react_description_input(description)

        await self.__set_contact_fields(ad_cfg.contact)

        #############################
        # delete previous images to ensure a clean slate
        # (needed for MODIFY because we don't know which changed,
        #  and for REPLACE retries where stale thumbnails may remain)
        #
        # Kleinanzeigen replaced the former j-pictureupload-thumbnails list with
        # React image cards. Keep this operation DOM-fresh: never hold a nodriver
        # Element across a React re-render. Click the current first remove button,
        # wait for both the visible card and adImages hidden input count to shrink,
        # and repeat until the form contains no previous images.
        #############################
        async def current_image_state() -> dict[str, int]:
            try:
                result = await self.web_execute("""(function() {
                    const removeButtons = Array.from(document.querySelectorAll('button[aria-label="Bild entfernen"]'))
                        // Kleinanzeigen renders these controls with Tailwind `scale-0` until hover.
                        // They are still the live React buttons and can be clicked programmatically,
                        // so do not discard them based on getBoundingClientRect().
                        .filter((button) => !button.disabled && button.isConnected);
                    const markers = Array.from(document.querySelectorAll('input[name^="adImages"][name$=".url"]'))
                        .filter((input) => String(input.value || '').trim());
                    return {removeButtons: removeButtons.length, markers: markers.length};
                })()""")
                if isinstance(result, dict):
                    return {
                        "removeButtons": int(result.get("removeButtons", 0) or 0),
                        "markers": int(result.get("markers", 0) or 0),
                    }
            except Exception as ex:
                LOG.debug(" -> unable to inspect current image state: %s", ex, exc_info = True)
            return {"removeButtons": 0, "markers": 0}

        initial_image_state = await current_image_state()
        existing_image_count = max(initial_image_state["removeButtons"], initial_image_state["markers"])

        if existing_image_count:
            LOG.info(
                " -> removing %d existing image(s) before upload using fresh React DOM controls...",
                existing_image_count,
            )

            # Safety cap is above Kleinanzeigen's current maximum of 20 images.
            for image_remove_attempt in range(25):
                before = await current_image_state()
                before_count = max(before["removeButtons"], before["markers"])
                if before_count <= 0:
                    break

                click_result = await self.web_execute("""(function() {
                    const buttons = Array.from(document.querySelectorAll('button[aria-label="Bild entfernen"]'))
                        .filter((button) => !button.disabled && button.isConnected);
                    const button = buttons[0];
                    if (!button) {
                        return {ok: false, reason: 'no-current-remove-button', total: buttons.length};
                    }
                    try { button.scrollIntoView({block: 'center', inline: 'center'}); } catch (e) {}
                    // The remove control is visually scale-0 until hover, but React's click handler
                    // is attached to this actual button. Dispatch a real click sequence and finish
                    // with HTMLElement.click() so the handler runs even while it is visually hidden.
                    const opts = {bubbles: true, cancelable: true, view: window};
                    try { button.dispatchEvent(new PointerEvent('pointerdown', opts)); } catch (e) {}
                    try { button.dispatchEvent(new MouseEvent('mousedown', opts)); } catch (e) {}
                    try { button.dispatchEvent(new MouseEvent('mouseup', opts)); } catch (e) {}
                    try { button.dispatchEvent(new PointerEvent('pointerup', opts)); } catch (e) {}
                    try { button.dispatchEvent(new MouseEvent('click', opts)); } catch (e) {}
                    try { button.click(); } catch (e) {}
                    return {ok: true, ariaLabel: button.getAttribute('aria-label') || '', remainingButtonsAtClick: buttons.length};
                })()""")
                LOG.info(" -> fresh image remove click: %s", click_result)
                await self.web_sleep(250, 450)

                async def image_count_decreased(previous_count:int = before_count) -> bool:
                    now = await current_image_state()
                    return max(now["removeButtons"], now["markers"]) < previous_count

                try:
                    await self.web_await(
                        image_count_decreased,
                        timeout = self._timeout("quick_dom"),
                        timeout_error_message = _("Existing image did not disappear after remove click"),
                    )
                except TimeoutError:
                    # One short re-check is enough; do not continue and upload on top
                    # of stale images because that would silently re-publish deleted photos.
                    now = await current_image_state()
                    if max(now["removeButtons"], now["markers"]) >= before_count:
                        raise TimeoutError(
                            _("Unable to remove existing Kleinanzeigen image before upload")
                        )

            remaining_image_state = await current_image_state()
            remaining_image_count = max(remaining_image_state["removeButtons"], remaining_image_state["markers"])
            if remaining_image_count:
                raise TimeoutError(
                    _("Unable to clear existing Kleinanzeigen images before upload; %(count)d remain")
                    % {"count": remaining_image_count}
                )

            LOG.info(" -> all existing images removed; uploading configured image set from scratch")

        #############################
        # upload images
        #############################
        await self.__upload_images(ad_cfg)

        #############################
        # wait for captcha
        #############################
        await self.check_and_wait_for_captcha(is_login_page = False)

        #############################
        # set title (right before submit to prevent React re-render clearing it)
        #############################
        await self.__react_input("ad-title", ad_cfg.title)

        #############################
        # submit
        #############################
        # Find the real React button without XPath/CDP search.  If the JS context
        # disappears during the click, treat the outcome as uncertain rather than
        # restarting the whole publish flow and risking a duplicate listing.
        self._publish_submit_boundary_active = True
        await self.__click_submit_button_robust()

        # Everything after the first click is uncertain: the ad may already have been submitted.
        try:
            try:
                await self.web_click(By.ID, "imprint-guidance-submit", timeout = self._timeout("quick_dom"))
            except TimeoutError:
                pass  # nosec — imprint overlay not shown

            # check for no image question
            try:
                image_hint_xpath = '//button[contains(., "Ohne Bild veröffentlichen")]'
                if not ad_cfg.images and await self.web_check(By.XPATH, image_hint_xpath, Is.DISPLAYED):
                    await self.web_click(By.XPATH, image_hint_xpath)
            except TimeoutError:
                pass  # nosec — image hint not shown

            #############################
            # wait for payment form if commercial account is used
            #############################
            try:
                short_timeout = self._timeout("quick_dom")
                await self.web_find(By.ID, "myftr-shppngcrt-frm", timeout = short_timeout)

                LOG.warning("############################################")
                LOG.warning("# Payment form detected! Please proceed with payment.")
                LOG.warning("############################################")
                await self.web_scroll_page_down()
                await ainput(_("Press a key to continue..."))
            except TimeoutError:
                # Payment form not present.
                pass

            confirmation_timeout = self._timeout("publishing_confirmation")
            idless_confirmation_success = False
            paid_upsell_declined = False
            final_save_clicked = False

            async def _check_confirmation_state() -> bool:
                nonlocal idless_confirmation_success, paid_upsell_declined, final_save_clicked
                # Nach dem Speichern zeigt Kleinanzeigen bei einigen bestehenden
                # Anzeigen zuerst ein kostenpflichtiges Upsell-Modal. Nur der
                # explizite Verzicht ist hier zulässig: Er übernimmt die bereits
                # gespeicherten Änderungen und startet weder einen Repost noch
                # einen kostenpflichtigen Vorgang.
                try:
                    skipped_upsell = await self.web_execute(r"""
(() => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const visible = element => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const button = [...document.querySelectorAll('button')].find(element =>
    visible(element) && normalize(element.innerText || element.textContent) === 'Ohne Hochschieben weiter'
  );
  if (!button) return false;
  button.click();
  return true;
})()
""")
                    if skipped_upsell is True:
                        paid_upsell_declined = True
                        LOG.info("Declined optional paid 'Hochschieben' offer; continuing to final save")
                        return False
                except Exception as error:  # noqa: BLE001
                    LOG.debug("Could not inspect optional 'Hochschieben' offer: %s", error)

                url = str(await self.web_execute("window.location.href"))

                # Current Kleinanzeigen MODIFY flow is two-step: after the edit
                # form's first "Anzeige speichern" click it can open
                # /p-anzeige-aufgeben-schritt2.html ("Kostenpflichtige Optionen").
                # Declining "Hochschieben" only removes the paid offer; the
                # page still requires one final "Anzeige speichern" click.
                # Without this click the bot waits until timeout and raises
                # PublishSubmissionUncertainError although no confirmation was
                # ever submitted.
                if mode == AdUpdateStrategy.MODIFY and not final_save_clicked and "p-anzeige-aufgeben-schritt2.html" in url:
                    try:
                        final_save_result = await self.web_execute(r"""
(() => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const visible = element => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const headingText = [...document.querySelectorAll('h1,h2,h3')]
    .map(element => normalize(element.innerText || element.textContent))
    .join(' | ');
  const button = [...document.querySelectorAll('button')].find(element =>
    visible(element) && normalize(element.innerText || element.textContent) === 'Anzeige speichern'
  );
  if (!button) return {ok: false, reason: 'button-missing', headingText};
  button.click();
  return {ok: true, text: normalize(button.innerText || button.textContent), headingText};
})()
""")
                        if isinstance(final_save_result, dict) and final_save_result.get("ok") is True:
                            final_save_clicked = True
                            LOG.info(
                                "Submitted final Kleinanzeigen save step after paid offer%s: %s",
                                " decline" if paid_upsell_declined else "",
                                final_save_result,
                            )
                            return False
                    except Exception as error:  # noqa: BLE001
                        LOG.debug("Could not submit final Kleinanzeigen save step: %s", error)

                if "p-anzeige-aufgeben-bestaetigung.html?adId=" in url:
                    return True
                # Kleinanzeigen now also serves the confirmation page without
                # ``adId`` for a newly created ad.  The page is authoritative
                # only together with its visible success/manage affordance; the
                # manager obtains the fresh remote ID from the live API after
                # this temporary staged config has completed.
                if "p-anzeige-aufgeben-bestaetigung.html" in url:
                    try:
                        result = await self.web_execute(r"""
(() => {
  const text=(document.body?.innerText||'').replace(/\s+/g,' ').trim();
  const manage=[...document.querySelectorAll('a,button')].some(el =>
    (el.innerText||'').replace(/\s+/g,' ').trim().includes('Zu meinen Anzeigen'));
  const successText = /geschafft!|anzeige ist (jetzt )?online|anzeige wurde (erfolgreich )?veröffentlicht/i.test(text);
  return manage && successText;
})()
""")
                        if result is True:
                            idless_confirmation_success = True
                            LOG.warning("Confirmation page exposed no adId; manager will confirm the live ad after publish")
                            return True
                    except Exception:
                        pass
                return False

            await self.web_await(_check_confirmation_state, timeout = confirmation_timeout)
        except (TimeoutError, ProtocolException) as ex:
            if mode == AdUpdateStrategy.MODIFY:
                await self._log_update_confirmation_probe()
            raise PublishSubmissionUncertainError("submission may have succeeded before failure") from ex

        if idless_confirmation_success:
            if mode == AdUpdateStrategy.MODIFY:
                if not ad_cfg.id:
                    raise PublishSubmissionUncertainError("update succeeded but configured ad ID is missing")
                ad_id = int(ad_cfg.id)
                LOG.warning("Update confirmation page exposed no ad ID; using configured ad ID %s", ad_id)
            else:
                ad_id = None
                # This file belongs to the manager's disposable staging area.
                # Do not retain the deleted predecessor's ID when the current
                # confirmation page intentionally omits the new one.
                ad_cfg_orig.pop("id", None)
        else:
            # extract the ad id from the URL's query parameter (use JS for fresh URL, not stale self.page.url)
            current_url = str(await self.web_execute("window.location.href"))
            current_url_query_params = urllib_parse.parse_qs(urllib_parse.urlparse(current_url).query)
            ad_id = int(current_url_query_params.get("adId", [])[0])
        if ad_id is not None:
            ad_cfg_orig["id"] = ad_id

        # Update content hash after successful publication
        # Calculate hash on original config to ensure consistent comparison on restart
        ad_cfg_orig["content_hash"] = AdPartial.model_validate(ad_cfg_orig).update_content_hash().content_hash
        ad_cfg_orig["updated_on"] = misc.now().isoformat(timespec = "seconds")
        if not ad_cfg.created_on and not ad_cfg.id:
            ad_cfg_orig["created_on"] = ad_cfg_orig["updated_on"]

        # Increment repost_count and persist price_reduction_count only for REPLACE operations (actual reposts)
        # This ensures counters only advance on republish, not on UPDATE
        if mode == AdUpdateStrategy.REPLACE:
            # Increment repost_count after successful publish
            # Note: This happens AFTER publish, so price reduction logic (which runs before publish)
            # sees the count from the PREVIOUS run. This is intentional: the first publish uses
            # repost_count=0 (no reduction), the second publish uses repost_count=1 (first reduction), etc.
            current_reposts = int(ad_cfg_orig.get("repost_count", ad_cfg.repost_count or 0))
            ad_cfg_orig["repost_count"] = current_reposts + 1
            ad_cfg.repost_count = ad_cfg_orig["repost_count"]

            # Persist price_reduction_count after successful publish
            # This ensures failed publishes don't incorrectly increment the reduction counter
            if ad_cfg.price_reduction_count is not None and ad_cfg.price_reduction_count > 0:
                ad_cfg_orig["price_reduction_count"] = ad_cfg.price_reduction_count

        if mode == AdUpdateStrategy.REPLACE:
            LOG.info(" -> SUCCESS: ad published%s", f" with ID {ad_id}" if ad_id is not None else "; confirmation page omitted ID")
        else:
            LOG.info(" -> SUCCESS: ad updated with ID %s", ad_id)

        dicts.save_dict(ad_file, ad_cfg_orig)

    async def __react_input(self, element_id:str, value:str) -> None:
        """Sets a React-controlled input value using the native setter to trigger onChange."""
        await self.web_find(By.ID, element_id)  # raises TimeoutError if element is absent
        js_element_id = json.dumps(element_id)
        js_value = json.dumps(value)
        await self.web_execute(
            f"(function(id,v){{"
            "var el=document.getElementById(id);"
            "if(!el)return;"
            "var tag=el.tagName.toLowerCase();"
            "var proto=tag==='textarea'?window.HTMLTextAreaElement:window.HTMLInputElement;"
            "var setter=Object.getOwnPropertyDescriptor(proto.prototype,'value').set;"
            "setter.call(el,v);"
            "el.dispatchEvent(new Event('input',{bubbles:true}));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));"
            f"}})({js_element_id},{js_value})"
        )

    async def __wait_for_usable_page_after_navigation(
        self,
        url:str,
        *,
        required_ids:Sequence[str] = (),
        timeout:float = 10.0,
    ) -> dict[str, Any] | None:
        """Accept Kleinanzeigen pages once their useful DOM exists, even if trackers keep readyState incomplete."""
        expected_path = urllib_parse.urlparse(url).path or "/"
        deadline = asyncio.get_running_loop().time() + max(0.5, float(timeout))
        js_required_ids = json.dumps(list(required_ids))
        last_state:dict[str, Any] | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                state = await self.web_execute(f"""(() => {{
                    const required = {js_required_ids};
                    const path = location.pathname || '/';
                    const bodyPresent = Boolean(document.body && document.body.childElementCount);
                    const ids = Object.fromEntries(required.map(id => [id, Boolean(document.getElementById(id))]));
                    return {{path, readyState: document.readyState, bodyPresent, ids}};
                }})()""")
                if isinstance(state, dict):
                    last_state = state
                    ids = state.get("ids") if isinstance(state.get("ids"), dict) else {}
                    if (
                        str(state.get("path") or "") == expected_path
                        and bool(state.get("bodyPresent"))
                        and all(bool(ids.get(element_id)) for element_id in required_ids)
                    ):
                        return state
            except (TimeoutError, ProtocolException):
                pass
            await asyncio.sleep(0.35)
        LOG.debug("Usable-page probe timed out for %s; last state=%s", expected_path, last_state)
        return None

    async def __open_publish_form_resilient(self, url:str) -> None:
        """Open publish/edit form and ignore tracker-only navigation timeouts once the form is usable."""
        try:
            await self.web_open(url)
            return
        except (TimeoutError, ProtocolException) as open_error:
            state = await self.__wait_for_usable_page_after_navigation(
                url, required_ids = ("ad-title", "ad-description"), timeout = 12.0
            )
            if state:
                LOG.warning(
                    "Page load reported %s, but the Kleinanzeigen form is already interactive at %s (readyState=%s); continuing without a full retry.",
                    type(open_error).__name__, state.get("path"), state.get("readyState"),
                )
                return
            raise

    async def __resolve_category_suggestions_robust(self, category:str) -> None:
        """Resolve the redesigned React suggestion picker without XPath/CDP search."""
        segments = [segment.strip() for segment in category.split("/") if segment.strip()]
        js_segments = json.dumps(list(reversed(segments)))
        for attempt in range(2):
            result = await self.web_execute(f"""(() => {{
                const segments = {js_segments};
                const picker = document.getElementById('ad-category-picker');
                if (!picker) return {{state:'none'}};
                const radios = Array.from(picker.querySelectorAll("input[type='radio'][name='category-suggestions']"));
                if (!radios.length) return {{state:'empty'}};
                const byValue = new Map(radios.map(radio => [String(radio.value || '').trim(), radio]));
                for (const segment of segments) {{
                    const radio = byValue.get(segment);
                    if (!radio) continue;
                    const label = radio.id ? picker.querySelector(`label[for="${{CSS.escape(radio.id)}}"]`) : null;
                    const target = label || radio;
                    try {{ target.scrollIntoView({{block:'center', inline:'center'}}); }} catch (e) {{}}
                    try {{ target.click(); }} catch (e) {{ return {{state:'click-failed', value:segment}}; }}
                    return {{state:'selected', value:segment}};
                }}
                return {{state:'unmatched', offered:Array.from(byValue.keys()).sort()}};
            }})()""")
            if isinstance(result, dict):
                state = str(result.get("state") or "")
                if state == "none":
                    return
                if state == "selected":
                    LOG.info("Category suggestion picker selected value=%s.", result.get("value"))
                    await self.web_sleep(350, 650)
                    return
                if state == "unmatched":
                    raise TimeoutError(
                        "Category suggestion picker did not contain a configured category segment: "
                        + ", ".join(str(item) for item in (result.get("offered") or []))
                    )
                if state == "click-failed":
                    raise TimeoutError("Unable to click matching category suggestion.")
            if attempt == 0:
                await self.web_sleep(250, 450)
        raise TimeoutError("Category suggestion picker was present but did not render any choices.")

    async def __click_submit_button_robust(self) -> None:
        """Click the real React submit button without XPath's transient CDP search session."""
        labels = ["Anzeige aufgeben", "Änderungen speichern", "Anzeige speichern"]
        js_labels = json.dumps(labels, ensure_ascii=False)
        found = await self.web_execute(rf"""(() => {{
            const labels = {js_labels};
            const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
            const visible = el => {{
                if (!el || el.disabled) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const button = Array.from(document.querySelectorAll('button')).find(btn =>
                visible(btn) && labels.some(label => normalize(btn.textContent).includes(label))
            );
            return button ? normalize(button.textContent) : '';
        }})()""")
        if not str(found or "").strip():
            raise TimeoutError(_("Could not find submit button"))

        try:
            clicked = await self.web_execute(rf"""(() => {{
                const labels = {js_labels};
                const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                const visible = el => {{
                    if (!el || el.disabled) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                }};
                const button = Array.from(document.querySelectorAll('button')).find(btn =>
                    visible(btn) && labels.some(label => normalize(btn.textContent).includes(label))
                );
                if (!button) return false;
                try {{ button.scrollIntoView({{block:'center', inline:'center'}}); }} catch (e) {{}}
                button.click();
                return true;
            }})()""")
        except ProtocolException as ex:
            # The click itself can tear down the JS context immediately. At this
            # boundary a retry could create a duplicate listing, so mark it uncertain.
            raise PublishSubmissionUncertainError("submission may have started during submit click") from ex
        if not clicked:
            raise TimeoutError(_("Could not find submit button"))
        await self.web_sleep()

    async def __focus_description(self) -> bool:
        """Aktuelles Beschreibungsfeld fokussieren, ohne von einer festen ID abzuhängen."""
        result = await self.web_execute(r"""(() => {
            const visible = (el) => {
                if (!el) return false;
                const box = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const score = (el) => {
                const attrs = ['id','name','aria-label','placeholder','data-testid','data-test-id']
                    .map(key => String(el.getAttribute(key) || '')).join(' ').toLowerCase();
                let value = /beschreibung|description/.test(attrs) ? 100 : 0;
                if (el.id === 'ad-description') value += 200;
                if (el.tagName === 'TEXTAREA') value += 20;
                if (el.isContentEditable) value += 10;
                return value;
            };
            const candidates = Array.from(document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]'))
                .filter(visible).sort((a,b) => score(b) - score(a));
            const el = candidates[0];
            if (!el || score(el) <= 0) return {ok:false, candidates:candidates.slice(0,8).map(x => ({tag:x.tagName,id:x.id||'',name:x.getAttribute('name')||'',aria:x.getAttribute('aria-label')||'',placeholder:x.getAttribute('placeholder')||''}))};
            try { el.scrollIntoView({block:'center'}); el.focus({preventScroll:true}); el.click(); } catch (e) {}
            return {ok:true, tag:el.tagName, id:el.id||'', name:el.getAttribute('name')||'', contenteditable:!!el.isContentEditable};
        })()""")
        if not isinstance(result, dict) or not result.get("ok"):
            LOG.warning("Description focus fallback found no known description field: %s", result)
            return False
        LOG.info("Description field focus fallback: %s", result)
        return True

    async def __react_description_input(self, value:str) -> None:
        """Beschreibung im alten oder neuen Kleinanzeigen-React-Feld setzen.

        Kleinanzeigen hat die feste ID `ad-description` in Teilen der aktuellen
        Bearbeitungsseite entfernt. Deshalb wird die sichtbare Textarea bzw. ein
        beschriftetes contenteditable-Feld gesucht und über den nativen Setter
        gesetzt, damit React die Änderung zuverlässig übernimmt.
        """
        js_value = json.dumps(value)
        result = await self.web_execute(f"""(() => {{
            const value = {js_value};
            const visible = (el) => {{
                if (!el) return false;
                const box = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const score = (el) => {{
                const attrs = ['id','name','aria-label','placeholder','data-testid','data-test-id']
                    .map(key => String(el.getAttribute(key) || '')).join(' ').toLowerCase();
                let points = /beschreibung|description/.test(attrs) ? 100 : 0;
                if (el.id === 'ad-description') points += 200;
                if (el.tagName === 'TEXTAREA') points += 20;
                if (el.isContentEditable) points += 10;
                return points;
            }};
            const candidates = Array.from(document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]'))
                .filter(visible).sort((a,b) => score(b) - score(a));
            const el = candidates[0];
            const diagnostic = candidates.slice(0,8).map(x => ({{tag:x.tagName,id:x.id||'',name:x.getAttribute('name')||'',aria:x.getAttribute('aria-label')||'',placeholder:x.getAttribute('placeholder')||'',contenteditable:!!x.isContentEditable,score:score(x)}}));
            if (!el || score(el) <= 0) return {{ok:false, candidates:diagnostic}};
            try {{ el.scrollIntoView({{block:'center'}}); el.focus({{preventScroll:true}}); }} catch (e) {{}}
            if (el.isContentEditable) {{
                el.textContent = value;
            }} else {{
                const proto = el.tagName.toLowerCase() === 'textarea' ? window.HTMLTextAreaElement : window.HTMLInputElement;
                const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
                setter.call(el, value);
            }}
            try {{ el.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}})); }}
            catch (e) {{ el.dispatchEvent(new Event('input', {{bubbles:true}})); }}
            el.dispatchEvent(new Event('change', {{bubbles:true}}));
            try {{ el.blur(); }} catch (e) {{}}
            return {{ok:true, tag:el.tagName, id:el.id||'', name:el.getAttribute('name')||'', contenteditable:!!el.isContentEditable}};
        }})()""")
        if not isinstance(result, dict) or not result.get("ok"):
            raise TimeoutError(f"No current description input found: {result}")
        LOG.info("Description set using adaptive field selector: %s", result)

    async def __set_contact_fields(self, contact:Contact) -> None:
        #############################
        # set contact zipcode
        #############################
        if contact.zipcode:
            try:
                await self.__react_input("ad-zip-code", str(contact.zipcode))
            except TimeoutError as ex:
                LOG.warning("Could not set contact zipcode: %s (%s)", contact.zipcode, ex)
        if contact.location:
            try:
                await self.__react_input("ad-city", contact.location)
            except TimeoutError as ex:
                LOG.warning("Could not set contact location: %s (%s)", contact.location, ex)

        #############################
        # set contact street
        #############################
        if contact.street:
            try:
                if await self.web_check(By.ID, "ad-street", Is.DISABLED):
                    await self.web_click(By.ID, "ad-address-visibility")
                    await self.web_sleep()
                await self.__react_input("ad-street", contact.street)
            except TimeoutError:
                LOG.warning("Could not set contact street.")

        #############################
        # set contact name
        #############################
        if contact.name:
            try:
                if not await self.web_check(By.ID, "ad-name", Is.READONLY):
                    await self.__react_input("ad-name", contact.name)
            except TimeoutError:
                LOG.warning("Could not set contact name.")

        #############################
        # set contact phone
        #############################
        if contact.phone:
            try:
                if await self.web_check(By.ID, "ad-phone", Is.DISPLAYED):
                    try:
                        if await self.web_check(By.ID, "ad-phone", Is.DISABLED):
                            await self.web_click(By.ID, "ad-phone-visibility")
                            await self.web_sleep()
                    except TimeoutError:
                        # ignore
                        pass
                    await self.__react_input("ad-phone", contact.phone)
            except TimeoutError:
                LOG.warning(
                    _(
                        "Phone number field not present on page. This is expected for many private accounts; "
                        "commercial accounts may still support phone numbers."
                    )
                )

    async def update_ads(self, ad_cfgs:list[tuple[str, Ad, dict[str, Any]]]) -> None:
        """
        Updates a list of ads.
        The list gets filtered, so that only already published ads will be updated.
        Calls publish_ad in MODIFY mode.

        Args:
            ad_cfgs: List of ad configurations

        Returns:
            None
        """
        count = 0

        published_ads = await self._fetch_published_ads()

        for ad_file, ad_cfg, ad_cfg_orig in ad_cfgs:
            ad = next((ad for ad in published_ads if str(ad.get("id", "")) == str(ad_cfg.id or "")), None)

            if not ad:
                LOG.warning(" -> SKIPPED: ad '%s' (ID: %s) not found in published ads", ad_cfg.title, ad_cfg.id)
                continue

            LOG.info("Processing %s/%s: '%s' from [%s]...", count + 1, len(ad_cfgs), ad_cfg.title, ad_file)
            if ad["state"] == "paused":
                LOG.info("Skipping because ad is reserved")
                continue

            count += 1

            # A ProtocolException at this level occurs before ``publish_ad`` has
            # reached the save button. Kleinanzeigen re-renders parts of the edit
            # form while it loads; nodriver can then hold a stale node reference.
            # Reopening the edit form once is safe here: no save was submitted and
            # the existing ad cannot be duplicated or republished by this retry.
            for attempt in range(1, 3):
                try:
                    await self.publish_ad(ad_file, ad_cfg, ad_cfg_orig, published_ads, AdUpdateStrategy.MODIFY)
                    break
                except PublishSubmissionUncertainError as ex:
                    # Once the save button was pressed, never retry automatically.
                    # Capture the final page state for a safe manual assessment.
                    await self._capture_publish_error_diagnostics_if_enabled(ad_cfg, ad_cfg_orig, ad_file, attempt, ex)
                    raise
                except (TimeoutError, ProtocolException) as ex:
                    # The save click has not been reached: capture the transient
                    # browser state and make one clean, safe attempt from the edit URL.
                    await self._capture_publish_error_diagnostics_if_enabled(ad_cfg, ad_cfg_orig, ad_file, attempt, ex)
                    if attempt >= 2:
                        raise
                    LOG.warning(
                        "Edit form became unstable before saving '%s': %s. Reopening it once.",
                        ad_cfg.title,
                        ex,
                    )
                    await self.web_sleep(1_000, 1_500)

            publish_timeout = self._timeout("publishing_result")
            try:
                await self.web_await(self.__check_publishing_result, timeout = publish_timeout)
            except (TimeoutError, ProtocolException) as ex:
                # ``publish_ad`` already observed the save confirmation. This
                # optional extra check must not turn a successful edit into a
                # failed operation merely because the management page re-rendered.
                LOG.warning("Updated ad '%s', but post-save list refresh was not available: %s", ad_cfg.title, ex)

        LOG.info("############################################")
        LOG.info("DONE: updated %s", pluralize("ad", count))
        LOG.info("############################################")

    async def __set_condition(self, condition_value:str) -> None:
        try:
            # Open condition dialog
            await self.web_click(By.XPATH, '//*[@id="j-post-listing-frontend-conditions"]//button[@aria-haspopup="true"]')
        except TimeoutError:
            LOG.debug("Unable to open condition dialog and select condition [%s]", condition_value, exc_info = True)
            return

        try:
            # Click radio button
            await self.web_click(By.ID, f"radio-button-{condition_value}")
        except TimeoutError:
            LOG.debug("Unable to select condition [%s]", condition_value, exc_info = True)

        try:
            # Click accept button
            await self.web_click(By.XPATH, '//*[self::dialog or @role="dialog"]//button[.//span[text()="Bestätigen"]]')
        except TimeoutError as ex:
            raise TimeoutError(_("Unable to close condition dialog!")) from ex

    async def __category_runtime_state(self, current_segment:str = "", next_segment:str = "") -> dict[str, Any]:
        js_current = json.dumps(current_segment)
        js_next = json.dumps(next_segment)
        result = await self.web_execute(fr"""(() => {{
            const current = {js_current};
            const next = {js_next};
            const visible = el => {{
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const form = document.getElementById('postad-step1-frm');
            const fieldValues = form ? Array.from(form.querySelectorAll('input,textarea,select'))
                .filter(el => el.name === 'parentCategoryId' || el.name === 'categoryId')
                .map(el => ({{name:String(el.name || ''), value:String(el.value || '')}})) : [];
            const currentEl = current ? document.getElementById(`cat_${{current}}`) : null;
            const nextEl = next ? document.getElementById(`cat_${{next}}`) : null;
            const buttons = Array.from(document.querySelectorAll('button')).filter(visible).map(btn => ({{
                text:String(btn.innerText || btn.textContent || '').replace(/\s+/g, ' ').trim(), disabled:Boolean(btn.disabled)
            }})).slice(0, 30);
            return {{
                path: location.pathname,
                hash: location.hash,
                readyState: document.readyState,
                currentPresent: Boolean(currentEl),
                currentVisible: Boolean(currentEl && visible(currentEl)),
                nextPresent: Boolean(nextEl),
                nextVisible: Boolean(nextEl && visible(nextEl)),
                formPresent: Boolean(form),
                formVisible: Boolean(form && visible(form)),
                formClass: form ? String(form.className || '') : '',
                fieldValues,
                buttons,
                publishFormPresent: Boolean(document.getElementById('ad-title')),
                categoryPickerPresent: Boolean(document.getElementById('ad-category-picker')),
            }};
        }})()""")
        return result if isinstance(result, dict) else {"unexpected": result}

    @staticmethod
    def __category_leaf_is_selected(state:dict[str, Any], segment:str) -> bool:
        fields = state.get("fieldValues") if isinstance(state.get("fieldValues"), list) else []
        return any(
            isinstance(row, dict)
            and str(row.get("name") or "") == "categoryId"
            and str(row.get("value") or "") == str(segment)
            for row in fields
        )

    async def __wait_for_category_progress(
        self,
        segment:str,
        next_segment:str,
        *,
        is_last:bool,
        timeout:float = 10.0,
    ) -> tuple[str, dict[str, Any] | None]:
        deadline = asyncio.get_running_loop().time() + max(0.5, timeout)
        last_state:dict[str, Any] | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                state = await self.__category_runtime_state(segment, next_segment)
                last_state = state
                path = str(state.get("path") or "")
                if path.endswith("/p-anzeige-aufgeben-schritt2.html") and bool(state.get("publishFormPresent")):
                    return "publish-form", state
                if next_segment and bool(state.get("nextPresent")):
                    return "next-segment", state
                if is_last:
                    enabled_continue = any(
                        isinstance(button, dict)
                        and "Weiter" in str(button.get("text") or "")
                        and not bool(button.get("disabled"))
                        for button in (state.get("buttons") or [])
                    )
                    if self.__category_leaf_is_selected(state, segment) or (state.get("formVisible") and enabled_continue):
                        return "leaf-selected", state
            except (TimeoutError, ProtocolException):
                pass
            await asyncio.sleep(0.30)
        return "", last_state

    async def __select_category_segment_resilient(
        self,
        segment:str,
        next_segment:str,
        *,
        is_last:bool,
    ) -> str:
        """Click one category segment and prove that the category page actually advanced."""
        ready_deadline = asyncio.get_running_loop().time() + 25.0
        last_state:dict[str, Any] | None = None
        while asyncio.get_running_loop().time() < ready_deadline:
            try:
                state = await self.__category_runtime_state(segment, next_segment)
                last_state = state
                if str(state.get("path") or "").endswith("/p-anzeige-aufgeben-schritt2.html") and state.get("publishFormPresent"):
                    return "publish-form"
                if state.get("currentPresent"):
                    break
            except (TimeoutError, ProtocolException):
                pass
            await asyncio.sleep(0.35)
        else:
            raise TimeoutError(f"Category segment {segment} did not appear; state={last_state}")

        last_error:Exception | None = None
        for click_attempt in range(1, 4):
            try:
                await self.__fresh_click_id(f"cat_{segment}")
            except (TimeoutError, ProtocolException) as error:
                # The click can already have triggered the hash-driven re-render.
                last_error = error
                LOG.debug("Category click #%s attempt %s became uncertain: %s", segment, click_attempt, error)

            progress, state = await self.__wait_for_category_progress(
                segment, next_segment, is_last = is_last, timeout = 8.0
            )
            if progress:
                LOG.info("Category segment %s advanced via %s: %s", segment, progress, state)
                return progress
            last_state = state
            if click_attempt < 3:
                await asyncio.sleep(0.5)

        raise TimeoutError(f"Category segment {segment} did not advance; state={last_state}") from last_error

    async def __continue_after_category_resilient(self, category:str) -> None:
        """Press the category page's Weiter button and tolerate the expected navigation context switch."""
        last_state:dict[str, Any] | None = None
        for attempt in range(1, 4):
            try:
                state = await self.__category_runtime_state()
                last_state = state
                if str(state.get("path") or "").endswith("/p-anzeige-aufgeben-schritt2.html") and state.get("publishFormPresent"):
                    await self.__resolve_category_suggestions_robust(category)
                    return
                result = await self.web_execute(r"""(() => {
                    const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                    const visible = el => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const buttons = Array.from(document.querySelectorAll('button')).filter(visible);
                    const button = buttons.find(btn => !btn.disabled && normalize(btn.textContent) === 'Weiter')
                        || buttons.find(btn => !btn.disabled && normalize(btn.textContent).includes('Weiter'));
                    if (!button) return {ok:false, buttons:buttons.map(btn => normalize(btn.textContent)).filter(Boolean).slice(0,20)};
                    try { button.scrollIntoView({block:'center', inline:'center'}); } catch (e) {}
                    button.click();
                    return {ok:true, text:normalize(button.textContent)};
                })()""")
                if isinstance(result, dict) and result.get("ok"):
                    LOG.info("Category selection continued with button: %s", result.get("text"))
            except ProtocolException as error:
                LOG.debug("Category continue click changed browser context: %s", error)

            usable = await self.__wait_for_usable_page_after_navigation(
                f"{self.root_url}/p-anzeige-aufgeben-schritt2.html",
                required_ids = ("ad-title", "ad-description"),
                timeout = 12.0,
            )
            if usable:
                await self.web_sleep(350, 650)
                await self.__resolve_category_suggestions_robust(category)
                return
            if attempt < 3:
                await asyncio.sleep(0.6)
        raise TimeoutError(f"Could not return to publish form after category selection; state={last_state}")

    async def __set_category(self, category:str | None, ad_file:str) -> None:
        """Set category using Kleinanzeigen' own in-session selector with transition-aware clicks."""
        if category and not category.split("/", 1)[0].isdigit():
            raise TimeoutError(_("Unknown category alias '%s'; expected a numeric category path") % category)

        await self.__focus_description()
        try:
            category_path = await self.web_execute("""(() => {
                const el = document.getElementById('ad-category-path');
                return el ? String(el.innerText || el.textContent || '').trim() : '';
            })()""")
        except ProtocolException:
            category_path = ""
        is_category_auto_selected = bool(str(category_path or "").strip())

        if not category:
            ensure(is_category_auto_selected, f"No category specified in [{ad_file}] and automatic category detection failed")
            return

        await self.web_sleep(350, 650)
        try:
            click_result = await self.web_execute(r"""(() => {
            const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
            const visible = el => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const described = document.querySelector('a[aria-describedby="ad-category-path"]');
            const candidates = Array.from(document.querySelectorAll('a,button')).filter(visible);
            const target = described
                || candidates.find(el => normalize(el.textContent) === 'Wähle deine Kategorie')
                || candidates.find(el => /Kategorie/.test(normalize(el.textContent)));
            if (!target) return {ok:false};
            const text = normalize(target.textContent);
            try { target.scrollIntoView({block:'center', inline:'center'}); } catch (e) {}
            target.click();
            return {ok:true, text};
        })()""")
        except ProtocolException as error:
            # The category link itself navigates from Astro to the legacy page and may
            # destroy the current execution context after the click already succeeded.
            LOG.debug("Opening category selection changed browser context: %s", error)
            click_result = {"ok": True, "text": "context transition"}
        if not isinstance(click_result, dict) or not click_result.get("ok"):
            raise TimeoutError("Could not open Kleinanzeigen category selection from the publish form.")
        LOG.info("Opened category selection using current form link: %s", click_result.get("text"))

        category_page_url = f"{self.root_url}/p-kategorie-aendern.html"
        category_page = await self.__wait_for_usable_page_after_navigation(category_page_url, timeout = 25.0)
        if not category_page:
            publish_page = await self.__wait_for_usable_page_after_navigation(
                f"{self.root_url}/p-anzeige-aufgeben-schritt2.html",
                required_ids = ("ad-title",), timeout = 2.0,
            )
            if publish_page:
                await self.__resolve_category_suggestions_robust(category)
                return
            raise TimeoutError("Kleinanzeigen category page did not become usable after opening it.")

        segments = [segment.strip() for segment in category.split("/") if segment.strip()]
        for index, segment in enumerate(segments):
            next_segment = segments[index + 1] if index + 1 < len(segments) else ""
            progress = await self.__select_category_segment_resilient(
                segment, next_segment, is_last = index == len(segments) - 1
            )
            LOG.info("Category path segment %s/%s selected: %s", index + 1, len(segments), segment)
            if progress == "publish-form":
                await self.__resolve_category_suggestions_robust(category)
                return

        await self.__continue_after_category_resilient(category)

    async def __set_special_attributes(self, ad_cfg:Ad) -> None:
        if not ad_cfg.special_attributes:
            return

        LOG.debug("Found %i special attributes", len(ad_cfg.special_attributes))
        for special_attribute_key, special_attribute_value in ad_cfg.special_attributes.items():
            # Ensure special_attribute_value is treated as a string
            special_attribute_value_str = str(special_attribute_value)

            if special_attribute_key == "condition_s":
                await self.__set_condition(special_attribute_value_str)
                continue

            LOG.debug("Setting special attribute [%s] to [%s]...", special_attribute_key, special_attribute_value_str)
            try:
                # if the <select> element exists but is inside an invisible container, make the container visible
                select_container_xpath = f"//div[@class='l-row' and descendant::select[@id='{special_attribute_key}']]"
                if not await self.web_check(By.XPATH, select_container_xpath, Is.DISPLAYED):
                    await (await self.web_find(By.XPATH, select_container_xpath)).apply("elem => elem.singleNodeValue.style.display = 'block'")
            except TimeoutError:
                # Skip visibility adjustment when container cannot be located in time.
                pass  # nosec

            try:
                # finding element by name cause id are composed sometimes eg. autos.marke_s+autos.model_s for Modell by cars
                special_attr_elem = await self.web_find(By.XPATH, f"//*[contains(@name, '{special_attribute_key}')]")
            except TimeoutError:
                # Trying to find element by ID instead cause sometimes there is NO name attribute...
                try:
                    special_attr_elem = await self.web_find(By.ID, special_attribute_key)
                except TimeoutError:
                    # New site dropped Solr type suffixes (_s, _i, _b, etc.) from element IDs — try without suffix
                    stripped_key = re.sub(r"_[a-z]+$", "", special_attribute_key)
                    if stripped_key == special_attribute_key:
                        LOG.debug("Attribute field '%s' could not be found.", special_attribute_key)
                        raise TimeoutError(_("Failed to set attribute '%s'") % special_attribute_key) from None
                    try:
                        special_attr_elem = await self.web_find(By.ID, stripped_key)
                    except TimeoutError as ex:
                        LOG.debug("Attribute field '%s' could not be found.", special_attribute_key)
                        raise TimeoutError(_("Failed to set attribute '%s'") % special_attribute_key) from ex

            try:
                elem_id:str = str(special_attr_elem.attrs.id)
                if special_attr_elem.local_name == "select":
                    LOG.debug("Attribute field '%s' seems to be a select...", special_attribute_key)
                    await self.web_select(By.ID, elem_id, special_attribute_value_str)
                elif special_attr_elem.attrs.type == "checkbox":
                    LOG.debug("Attribute field '%s' seems to be a checkbox...", special_attribute_key)
                    await self.web_click(By.ID, elem_id)
                elif special_attr_elem.local_name == "button" and special_attr_elem.attrs.get("role") == "combobox":
                    LOG.debug("Attribute field '%s' seems to be a button combobox (click-to-open dropdown)...", special_attribute_key)
                    await self.__select_button_combobox(elem_id, special_attribute_value_str)
                elif special_attr_elem.attrs.type == "text" and special_attr_elem.attrs.get("role") == "combobox":
                    LOG.debug("Attribute field '%s' seems to be a Combobox (i.e. text input with filtering dropdown)...", special_attribute_key)
                    await self.web_select_combobox(By.ID, elem_id, special_attribute_value_str)
                else:
                    LOG.debug("Attribute field '%s' seems to be a text input...", special_attribute_key)
                    await self.web_input(By.ID, elem_id, special_attribute_value_str)
            except TimeoutError as ex:
                LOG.debug("Failed to set attribute field '%s' via known input types.", special_attribute_key)
                raise TimeoutError(_("Failed to set attribute '%s'") % special_attribute_key) from ex
            LOG.debug("Successfully set attribute field [%s] to [%s]...", special_attribute_key, special_attribute_value_str)

    async def __select_button_combobox(self, elem_id:str, value:str) -> None:
        """Select an option from a <button role="combobox"> dropdown by its API value.

        Clicks the button to open the listbox, reads the options data from the React fiber
        (which maps API values to display labels), and clicks the matching option.
        """
        await self.web_click(By.ID, elem_id)
        listbox_id = f"{elem_id}-menu"
        await self.web_find(By.ID, listbox_id)
        js_btn_id = json.dumps(elem_id)
        js_listbox_id = json.dumps(listbox_id)
        js_value = json.dumps(value)
        ok = await self.web_execute(f"""(function() {{
            const listbox = document.getElementById({js_listbox_id});
            if (!listbox) return false;
            const liOptions = Array.from(listbox.querySelectorAll('[role="option"]'));
            const btnEl = document.getElementById({js_btn_id});
            if (!btnEl) return false;
            const fiberKey = Object.keys(btnEl).find(k => k.startsWith('__reactFiber'));
            let fiber = fiberKey ? btnEl[fiberKey] : null;
            for (let i = 0; i < 20 && fiber; i++, fiber = fiber.return) {{
                if (fiber.memoizedProps && fiber.memoizedProps.options) {{
                    const optionsData = fiber.memoizedProps.options;
                    for (let j = 0; j < optionsData.length; j++) {{
                        if (optionsData[j].value === {js_value} && liOptions[j]) {{
                            liOptions[j].click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            }}
            return false;
        }})()""")
        if not ok:
            raise TimeoutError(_("Option '%(value)s' not found in button combobox '%(id)s'") % {"value": value, "id": elem_id})


    async def __debug_shipping_dialog_dump(self, label: str = "shipping_dialog") -> None:
        """Best-effort dump of the current shipping dialog/page before failing."""
        try:
            from pathlib import Path
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            out = Path("/data") / f"debug_{label}_{ts}.json"

            js = r"""
(() => {
  const simple = el => ({
    tag: el.tagName,
    id: el.id || null,
    name: el.getAttribute("name"),
    type: el.getAttribute("type"),
    text: (el.innerText || el.textContent || "").trim().slice(0, 1500),
    value: el.value,
    checked: el.checked,
    disabled: el.disabled,
    aria: el.getAttribute("aria-label"),
    role: el.getAttribute("role"),
    cls: String(el.className || "").slice(0, 800),
    testid: el.getAttribute("data-testid")
  });

  const visible = el => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.display !== "none" && st.visibility !== "hidden";
  };

  return JSON.stringify({
    href: location.href,
    title: document.title,
    readyState: document.readyState,
    bodyText: document.body ? document.body.innerText.slice(0, 20000) : null,

    dialogs: Array.from(document.querySelectorAll("dialog,[role=dialog]")).map(simple),

    visibleButtonsAndLinks: Array.from(document.querySelectorAll("button,a"))
      .filter(visible)
      .map(simple),

    allButtons: Array.from(document.querySelectorAll("button")).map(simple),

    inputs: Array.from(document.querySelectorAll("input,textarea,select")).map(simple),

    radios: Array.from(document.querySelectorAll("input[type=radio]")).map(simple),

    checkboxes: Array.from(document.querySelectorAll("input[type=checkbox]")).map(simple),

    selects: Array.from(document.querySelectorAll("select")).map(el => ({
      ...simple(el),
      options: Array.from(el.options || []).map(o => ({
        text: o.text,
        value: o.value,
        selected: o.selected
      }))
    })),

    shippingRelated: Array.from(document.querySelectorAll("input,button,a,label,span,div,select"))
      .filter(el => /versand|shipping|abholung|fertig|weiter|andere|dhl|hermes|individuell|paket/i.test((el.innerText || el.textContent || "") + " " + (el.id || "") + " " + (el.name || "") + " " + (el.getAttribute("data-testid") || "")))
      .slice(0, 200)
      .map(simple),

    iframes: Array.from(document.querySelectorAll("iframe")).map(f => ({
      src: f.src,
      title: f.title,
      width: f.width,
      height: f.height
    }))
  }, null, 2);
})()
"""
            value = await self.web_execute(js)
            out.write_text(str(value), "utf-8")
            LOG.warning("DEBUG shipping dialog dump written to %s", out)
        except Exception as e:
            try:
                LOG.warning("DEBUG shipping dialog dump failed: %s", e)
            except Exception:
                pass


    async def __wait_for_shipping_form_ready_fresh(self) -> None:
        """Wait until the freshly re-rendered shipping controls are usable.

        Kleinanzeigen re-renders the edit form after a category change. nodriver
        element objects captured during that transition can become stale and then
        fail with CDP ``Could not find node with given id``. Poll the current DOM
        through JavaScript instead of retaining any node reference.
        """
        last_state:dict[str, Any] | None = None
        for _attempt in range(20):
            state = await self.web_execute(r"""(() => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none' && style.visibility !== 'hidden';
                };
                const yes = document.getElementById('ad-shipping-enabled-yes');
                const no = document.getElementById('ad-shipping-enabled-no');
                const options = document.getElementById('ad-shipping-options');
                const description = document.getElementById('ad-description');
                const price = document.getElementById('ad-price-amount');
                return {
                    ready: Boolean(yes && no && options && visible(options) && description && price),
                    yesPresent: Boolean(yes),
                    yesChecked: Boolean(yes && yes.checked),
                    noPresent: Boolean(no),
                    optionsPresent: Boolean(options),
                    optionsVisible: Boolean(options && visible(options)),
                    descriptionPresent: Boolean(description),
                    pricePresent: Boolean(price),
                };
            })()""")
            if isinstance(state, dict):
                last_state = state
                if state.get("ready"):
                    return
            await self.web_sleep(200, 350)
        raise TimeoutError(f"Shipping form did not stabilize after category render: {last_state}")

    async def __fresh_click_id(self, element_id:str, *, skip_if_checked:bool = False) -> dict[str, Any]:
        """Click the current DOM element by ID without creating a nodriver node."""
        js_element_id = json.dumps(element_id)
        js_skip_if_checked = "true" if skip_if_checked else "false"
        result = await self.web_execute(f"""(() => {{
            const id = {js_element_id};
            const skipIfChecked = {js_skip_if_checked};
            const el = document.getElementById(id);
            if (!el) return {{ok:false, reason:'missing', id}};
            if (skipIfChecked && Boolean(el.checked)) return {{ok:true, already:true, id}};
            const visible = (node) => {{
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.width > 0 && rect.height > 0
                    && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            let target = el;
            if (!visible(target) && el.id) {{
                const label = document.querySelector(`label[for="${{CSS.escape(el.id)}}"]`);
                if (label) target = label;
            }}
            if (!visible(target)) return {{ok:false, reason:'not-visible', id, tag:target.tagName}};
            if (target.disabled || target.getAttribute('aria-disabled') === 'true')
                return {{ok:false, reason:'disabled', id}};
            try {{ target.scrollIntoView({{block:'center', inline:'center'}}); }} catch (e) {{}}
            const opts = {{bubbles:true, cancelable:true, view:window}};
            try {{ target.focus({{preventScroll:true}}); }} catch (e) {{}}
            try {{ target.dispatchEvent(new PointerEvent('pointerdown', opts)); }} catch (e) {{}}
            try {{ target.dispatchEvent(new MouseEvent('mousedown', opts)); }} catch (e) {{}}
            try {{ target.dispatchEvent(new MouseEvent('mouseup', opts)); }} catch (e) {{}}
            try {{ target.dispatchEvent(new PointerEvent('pointerup', opts)); }} catch (e) {{}}
            try {{ target.click(); }} catch (e) {{}}
            return {{ok:true, already:false, id, tag:target.tagName}};
        }})()""")
        if not isinstance(result, dict) or not result.get("ok"):
            raise TimeoutError(f"Fresh DOM click failed for #{element_id}: {result}")
        LOG.info("Fresh DOM click #%s: %s", element_id, result)
        return result

    async def __fresh_visible_dialog_button(self, text:str, *, required:bool = False) -> bool:
        """Click a visible button in the active dialog by its current text."""
        js_text = json.dumps(text, ensure_ascii=False)
        result = await self.web_execute(f"""(() => {{
            const wanted = {js_text};
            const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
            const visible = (el) => {{
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0
                    && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]')).filter(visible);
            const root = dialogs.length ? dialogs[dialogs.length - 1] : document;
            const button = Array.from(root.querySelectorAll('button')).find(el =>
                visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true'
                && normalize(el.innerText || el.textContent).includes(wanted)
            );
            if (!button) return {{ok:false, wanted, dialogCount:dialogs.length}};
            try {{ button.scrollIntoView({{block:'center', inline:'center'}}); }} catch (e) {{}}
            const opts = {{bubbles:true, cancelable:true, view:window}};
            try {{ button.focus({{preventScroll:true}}); }} catch (e) {{}}
            try {{ button.dispatchEvent(new PointerEvent('pointerdown', opts)); }} catch (e) {{}}
            try {{ button.dispatchEvent(new MouseEvent('mousedown', opts)); }} catch (e) {{}}
            try {{ button.dispatchEvent(new MouseEvent('mouseup', opts)); }} catch (e) {{}}
            try {{ button.dispatchEvent(new PointerEvent('pointerup', opts)); }} catch (e) {{}}
            try {{ button.click(); }} catch (e) {{}}
            return {{ok:true, text:normalize(button.innerText || button.textContent)}};
        }})()""")
        ok = isinstance(result, dict) and bool(result.get("ok"))
        if ok:
            LOG.info("Fresh shipping dialog click '%s': %s", text, result)
            return True
        if required:
            raise TimeoutError(f"Visible shipping dialog button '{text}' not found: {result}")
        return False

    async def __fresh_shipping_dialog_has_button(self, text:str) -> bool:
        js_text = json.dumps(text, ensure_ascii=False)
        result = await self.web_execute(f"""(() => {{
            const wanted = {js_text};
            const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
            const visible = (el) => {{
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0
                    && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]')).filter(visible);
            const root = dialogs.length ? dialogs[dialogs.length - 1] : document;
            return Array.from(root.querySelectorAll('button')).some(el =>
                visible(el) && normalize(el.innerText || el.textContent).includes(wanted)
            );
        }})()""")
        return result is True

    async def __set_shipping(self, ad_cfg:Ad, mode:AdUpdateStrategy = AdUpdateStrategy.REPLACE) -> None:
        short_timeout = self._timeout("quick_dom")
        if ad_cfg.shipping_type == "PICKUP":
            try:
                await self.__wait_for_shipping_form_ready_fresh()
                await self.__fresh_click_id("ad-shipping-enabled-no", skip_if_checked = True)
            except TimeoutError as ex:
                LOG.debug(ex, exc_info = True)
        elif ad_cfg.shipping_options:
            # A category change can replace the complete shipping subtree. Using a
            # nodriver element found before/during that render is what produced the
            # Chromium -32000 "Could not find node with given id" failure. From here
            # on, lookup+click happens atomically in the current DOM via JavaScript.
            await self.__wait_for_shipping_form_ready_fresh()

            # Current Astro/React publish form can already contain the exact requested
            # package methods in the main form (for example Hermes M + DHL 5 kg).
            # In that state no shipping dialog needs to be opened at all.  Requiring
            # the old "Andere Versandmethoden" button would turn an already correct
            # form into a false publish failure.  This applies to fresh publishes as
            # well as edits.
            if await self.__requested_shipping_options_visible_in_main_form(ad_cfg):
                LOG.info("Shipping methods already match requested configuration in main form; skipping shipping dialog.")
                return

            await self.__fresh_click_id("ad-shipping-enabled-yes", skip_if_checked = True)
            await self.web_sleep(450, 700)
            await self.__fresh_click_id("ad-shipping-options")
            await self.web_sleep(450, 750)

            if mode == AdUpdateStrategy.MODIFY:
                if not await self.__fresh_shipping_dialog_has_button("Andere Versandmethoden"):
                    if await self.__fresh_visible_dialog_button("Zurück"):
                        await self.web_sleep(350, 600)
                if not await self.__fresh_shipping_dialog_has_button("Andere Versandmethoden"):
                    if await self.__fresh_visible_dialog_button("Zurück"):
                        await self.web_sleep(350, 600)

            if not await self.__fresh_shipping_dialog_has_button("Andere Versandmethoden"):
                # A 2026 Astro form may keep the selected shipping options directly
                # in hidden shippingOptions[].id fields and not render the legacy
                # dialog at all.  Accept that state only when every requested method
                # is visibly present in the main form; otherwise preserve the hard
                # failure so a wrong shipping configuration is never published.
                if await self.__requested_shipping_options_visible_in_main_form(ad_cfg):
                    LOG.info("Requested shipping methods are present after options click; legacy shipping dialog is not required.")
                    return

            await self.__fresh_visible_dialog_button("Andere Versandmethoden", required = True)
            await self.web_sleep(350, 650)
            await self.__set_shipping_options(ad_cfg, mode)
        else:
            special_shipping_selector = '//select[contains(@id, ".versand_s")]'
            is_commercial_shipping = False
            try:
                has_commercial_selector = await self.web_check(By.XPATH, special_shipping_selector, Is.DISPLAYED, timeout = short_timeout)
            except TimeoutError:
                # Element does not exist in DOM (non-commercial account or UI change); fall through to dialog-based shipping.
                has_commercial_selector = False
            if has_commercial_selector:
                shipping_value = "ja" if ad_cfg.shipping_type == "SHIPPING" else "nein"
                await self.web_select(By.XPATH, special_shipping_selector, shipping_value)
                is_commercial_shipping = True
            if not is_commercial_shipping:
                try:
                    # Ensure shipping is enabled before opening the dialog (may already be selected)
                    try:
                        await self.web_click(By.ID, "ad-shipping-enabled-yes", timeout = short_timeout)
                        await self.web_sleep(500, 800)
                    except TimeoutError as ex:
                        LOG.debug("Shipping enabled toggle not found before options dialog: %s", ex)
                    # no options. only costs. Set custom shipping cost
                    await self.web_click(By.ID, "ad-shipping-options")
                    try:
                        # when "Andere Versandmethoden" is not available, then we are already on the individual page
                        await self.web_click(By.XPATH, '//button[contains(., "Andere Versandmethoden")]')
                    except TimeoutError:
                        # Dialog option not present; already on the individual shipping page.
                        pass

                    individual_shipping_available = True
                    try:
                        # old UI: individual shipping price input is available
                        await self.web_find(By.ID, "ad-individual-shipping-price", timeout = short_timeout)
                    except TimeoutError:
                        individual_shipping_available = False

                    if individual_shipping_available:
                        if ad_cfg.shipping_costs is not None:
                            await self.web_input(
                                By.ID, "ad-individual-shipping-price", str.replace(str(ad_cfg.shipping_costs), ".", ",")
                            )
                        await self.web_click(By.XPATH, '//button[contains(., "Fertig")]')
                    else:
                        # new private-account shipping UI:
                        # Kleinanzeigen removed the old "Individueller Versand" input.
                        # The page may already have selected package shipping methods.
                        # Close/advance the package-size dialog instead of failing.
                        LOG.warning("Individual shipping input not available; using package-shipping dialog fallback.")

                        try:
                            await self.web_click(By.ID, "ad-individual-shipping-checkbox-control", timeout = short_timeout)
                            if ad_cfg.shipping_costs is not None:
                                await self.web_input(
                                    By.ID, "ad-individual-shipping-price", str.replace(str(ad_cfg.shipping_costs), ".", ",")
                                )
                            await self.web_click(By.XPATH, '//button[contains(., "Fertig")]')
                        except TimeoutError:
                            # Fallback for the current 2026 dialog: Paketgröße dialog with Weiter/Schließen.
                            try:
                                await self.web_click(By.XPATH, '//*[self::dialog or @role="dialog"]//button[contains(., "Weiter")]', timeout = short_timeout)
                                await self.web_sleep(500, 800)
                            except TimeoutError as ex:
                                LOG.debug("No Weiter button in shipping dialog fallback: %s", ex)

                            try:
                                await self.web_click(By.XPATH, '//*[self::dialog or @role="dialog"]//button[contains(., "Fertig")]', timeout = short_timeout)
                                await self.web_sleep(500, 800)
                            except TimeoutError:
                                try:
                                    await self.web_click(By.XPATH, '//*[self::dialog or @role="dialog"]//button[@aria-label="Schließen" or contains(., "Schließen")]', timeout = short_timeout)
                                    await self.web_sleep(500, 800)
                                except TimeoutError as ex:
                                    LOG.debug("No Fertig/Schließen button in shipping dialog fallback: %s", ex)

                            # If the shipping options button in the main form already shows selected methods,
                            # the dialog has done its job. Continue publishing.
                            try:
                                shipping_button_text = await self.web_text(By.ID, "ad-shipping-options", timeout = short_timeout)
                                LOG.warning("Shipping dialog fallback result: %s", shipping_button_text)
                            except TimeoutError:
                                pass
                except TimeoutError as ex:
                    LOG.debug(ex, exc_info = True)
                    await self.__debug_shipping_dialog_dump("shipping_dialog_unable_to_close")
                    if await self.__accept_visible_shipping_options_robust(ad_cfg):
                        return
                    raise TimeoutError(_("Unable to close shipping dialog!")) from ex


    async def __requested_shipping_options_visible_in_main_form(self, ad_cfg:Ad) -> bool:
        """Return True only when every requested shipping option is visible in the main shipping button."""
        if not getattr(ad_cfg, "shipping_options", None):
            return False

        option_labels = {
            "DHL_2": ["DHL Paket 2 kg", "Paket 2 kg"],
            "Hermes_Päckchen": ["Hermes Päckchen", "Päckchen"],
            "Hermes_S": ["Hermes S-Paket", "S-Paket"],
            "DHL_5": ["DHL Paket 5 kg", "Paket 5 kg"],
            "Hermes_M": ["Hermes M-Paket", "M-Paket"],
            "DHL_10": ["DHL Paket 10 kg", "Paket 10 kg"],
            "DHL_20": ["DHL Paket 20 kg", "Paket 20 kg"],
            "DHL_31,5": ["DHL Paket 31,5 kg", "Paket 31,5 kg", "DHL Paket 31.5 kg", "Paket 31.5 kg"],
            "Hermes_L": ["Hermes L-Paket", "L-Paket"],
        }

        try:
            shipping_button_text = await self.web_text(By.ID, "ad-shipping-options", timeout = self._timeout("quick_dom"))
        except (TimeoutError, ProtocolException):
            shipping_button_text = ""

        normalized = " ".join(str(shipping_button_text).split())
        wanted_options = list(ad_cfg.shipping_options or [])
        missing_options = []

        for option in wanted_options:
            labels = option_labels.get(option, [str(option)])
            if not any(label in normalized for label in labels):
                missing_options.append(option)

        if missing_options:
            LOG.warning(
                "Visible shipping options do not match requested options; not accepting dialog state. wanted=%s missing=%s text=%s",
                wanted_options,
                missing_options,
                normalized,
            )
            return False

        LOG.warning(
            "Requested shipping options visible in main form; accepting shipping dialog state. wanted=%s text=%s",
            wanted_options,
            normalized,
        )
        return True

    async def __accept_visible_shipping_options_robust(self, ad_cfg:Ad) -> bool:
        """Accept the dialog only if the requested package labels are actually visible."""
        if not await self.__requested_shipping_options_visible_in_main_form(ad_cfg):
            return False

        close_selectors = [
            '//*[self::dialog or @role="dialog"]//button[@aria-label="Schließen" or contains(., "Schließen")]',
            '//button[@aria-label="Schließen" or contains(., "Schließen")]',
            '//*[self::dialog or @role="dialog"]//button[contains(., "Weiter")]',
        ]

        for selector in close_selectors:
            try:
                await self.web_click(By.XPATH, selector, timeout = self._timeout("quick_dom"))
                await self.web_sleep(300, 700)
                break
            except (TimeoutError, ProtocolException):
                pass

        return True

    async def __set_shipping_options(self, ad_cfg:Ad, mode:AdUpdateStrategy = AdUpdateStrategy.REPLACE) -> None:
        if not ad_cfg.shipping_options:
            return

        shipping_options_mapping = {
            "DHL_2": ("Klein", "SMALL", "Paket 2 kg"),
            "Hermes_Päckchen": ("Klein", "SMALL", "Päckchen"),
            "Hermes_S": ("Klein", "SMALL", "S-Paket"),
            "DHL_5": ("Mittel", "MEDIUM", "Paket 5 kg"),
            "Hermes_M": ("Mittel", "MEDIUM", "M-Paket"),
            "DHL_10": ("Groß", "LARGE", "Paket 10 kg"),
            "DHL_20": ("Groß", "LARGE", "Paket 20 kg"),
            "DHL_31,5": ("Groß", "LARGE", "Paket 31,5 kg"),
            "Hermes_L": ("Groß", "LARGE", "L-Paket"),
        }
        shipping_package_variants = {
            "Paket 31,5 kg": ["Paket 31,5 kg", "Paket 31.5 kg", "31,5 kg", "31.5 kg"],
        }
        # Current Kleinanzeigen provider IDs. Keep these separate from the manager labels so
        # neighbouring Hermes methods cannot collapse onto the same React control.
        shipping_internal_id_by_option = {
            "Hermes_Päckchen": "HERMES_001",
            "Hermes_S": "HERMES_002",
            "DHL_2": "DHL_001",
            "Hermes_M": "HERMES_003",
            "DHL_5": "DHL_002",
            "DHL_10": "DHL_003",
            "DHL_31,5": "DHL_004",
            "DHL_20": "DHL_005",
            "Hermes_L": "HERMES_004",
        }
        try:
            requested_shipping_options = list(dict.fromkeys(ad_cfg.shipping_options))
            mapped_shipping_options = [shipping_options_mapping[option] for option in requested_shipping_options]
        except KeyError as ex:
            raise KeyError(f"Unknown shipping option(s), please refer to the documentation/README: {ad_cfg.shipping_options}") from ex

        shipping_sizes, shipping_selector, shipping_packages = zip(*mapped_shipping_options, strict = False)

        try:
            (shipping_size,) = set(shipping_sizes)
        except ValueError as ex:
            raise ValueError("You can only specify shipping options for one package size!") from ex

        try:
            shipping_radio_selector = shipping_selector[0]

            # Select the requested package size first. The Kleinanzeigen UI uses custom radio cards;
            # the real radio input can be hidden, so clicking the raw input by ID is not reliable.
            js_shipping_size = json.dumps(shipping_size, ensure_ascii=False)
            js_shipping_selector = json.dumps(shipping_radio_selector, ensure_ascii=False)
            size_result = await self.web_execute(f"""(function() {{
                const targetLabel = {js_shipping_size};
                const targetSelector = {js_shipping_selector};
                const normalize = (value) => String(value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const visible = (el) => {{
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
                }};
                const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]'));
                const root = dialogs.find(d => d.open || d.offsetParent !== null) || document;

                function fireMouse(el) {{
                    if (!el) return false;
                    try {{ el.scrollIntoView({{block: 'center', inline: 'center'}}); }} catch (e) {{}}
                    const opts = {{bubbles: true, cancelable: true, view: window}};
                    try {{ el.dispatchEvent(new PointerEvent('pointerdown', opts)); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new MouseEvent('mousedown', opts)); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new MouseEvent('mouseup', opts)); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new MouseEvent('click', opts)); }} catch (e) {{}}
                    try {{ el.click(); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new Event('input', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new Event('change', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    return true;
                }}

                function addCandidate(list, el) {{
                    if (!el || list.includes(el)) return;
                    list.push(el);
                }}

                const labelNorm = normalize(targetLabel);
                const selectorNorm = normalize(targetSelector);
                const candidates = [];

                const inputs = Array.from(root.querySelectorAll('input[type="radio"]'));
                const inputByValue = inputs.find(i => normalize(i.value) === selectorNorm || normalize(i.value) === labelNorm)
                    || root.querySelector(`#radio-button-${{CSS.escape(targetSelector)}}`)
                    || root.querySelector(`#radio-button-${{CSS.escape(targetLabel)}}`);
                if (inputByValue) {{
                    if (inputByValue.id) {{
                        const label = root.querySelector(`label[for="${{CSS.escape(inputByValue.id)}}"]`);
                        if (label) {{
                            addCandidate(candidates, label);
                            let p = label.parentElement;
                            for (let i = 0; i < 6 && p && p !== root; i++, p = p.parentElement) {{
                                const t = normalize(p.innerText || p.textContent || '');
                                if (t.includes(labelNorm)) addCandidate(candidates, p);
                            }}
                        }}
                    }}
                    addCandidate(candidates, inputByValue);
                }}

                for (const el of Array.from(root.querySelectorAll('label, button, [role="radio"], [aria-checked], div, span'))) {{
                    const text = normalize(el.innerText || el.textContent || '');
                    const id = normalize(el.id || '');
                    const data = normalize(el.getAttribute('data-testid') || '');
                    if (text === labelNorm || text.startsWith(labelNorm + ' ') || id.includes(selectorNorm) || data.includes(selectorNorm)) {{
                        addCandidate(candidates, el);
                        let p = el.parentElement;
                        for (let i = 0; i < 6 && p && p !== root; i++, p = p.parentElement) {{
                            const ptxt = normalize(p.innerText || p.textContent || '');
                            if (ptxt.includes(labelNorm)) addCandidate(candidates, p);
                        }}
                    }}
                }}

                const clicked = [];
                // Prefer visible cards/labels before direct inputs. Direct inputs are often not what React listens to.
                for (const el of candidates) {{
                    if (el.matches && el.matches('input[type="radio"]')) continue;
                    if (!visible(el)) continue;
                    fireMouse(el);
                    clicked.push({{tag: el.tagName, id: el.id || null, text: normalize(el.innerText || el.textContent || '').slice(0,160), visible: true}});
                    if (clicked.length >= 3) break;
                }}
                if (clicked.length === 0 && inputByValue) {{
                    fireMouse(inputByValue);
                    clicked.push({{tag: inputByValue.tagName, id: inputByValue.id || null, text: normalize(inputByValue.value || inputByValue.name || '').slice(0,80), visible: visible(inputByValue)}});
                }}

                const radios = Array.from(root.querySelectorAll('input[type="radio"], [role="radio"], [aria-checked]')).map(el => ({{
                    tag: el.tagName,
                    id: el.id || null,
                    value: el.value || null,
                    text: normalize(el.innerText || el.textContent || '').slice(0,120),
                    checked: !!el.checked || el.getAttribute('aria-checked') === 'true'
                }}));

                return {{ok: clicked.length > 0, targetLabel, targetSelector, clicked, radios, dialogText: normalize(root.innerText || root.textContent || '').slice(0,500)}};
            }})()""")
            LOG.warning("Shipping size selection result: size=%s selector=%s result=%s", shipping_size, shipping_radio_selector, size_result)
            if not isinstance(size_result, dict) or not size_result.get("ok"):
                await self.__debug_shipping_dialog_dump("shipping_dialog_size_selection_failed")
                raise TimeoutError(_("Unable to select requested shipping package size!"))

            await self.web_sleep(700, 1200)

            next_result = await self.web_execute("""(function() {
                const normalize = (value) => String(value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && !el.disabled;
                };
                const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]'));
                const root = dialogs.find(d => d.open || d.offsetParent !== null) || document;
                const buttons = Array.from(root.querySelectorAll('button')).filter(visible);
                const btn = buttons.find(b => normalize(b.innerText || b.textContent || '') === 'weiter')
                    || buttons.find(b => normalize(b.innerText || b.textContent || '').includes('weiter'));
                if (!btn) return {ok:false, reason:'Weiter button not found', buttons: buttons.map(b => normalize(b.innerText || b.textContent || '').slice(0,80))};
                try { btn.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
                try { btn.click(); } catch(e) {}
                btn.dispatchEvent(new Event('click', {bubbles:true, cancelable:true}));
                return {ok:true, text: normalize(btn.innerText || btn.textContent || '')};
            })()""")
            LOG.warning("Shipping size Weiter click result: %s", next_result)
            if not isinstance(next_result, dict) or not next_result.get("ok"):
                await self.__debug_shipping_dialog_dump("shipping_dialog_size_continue_failed")
                raise TimeoutError(_("Unable to continue after selecting requested shipping package size!"))

            await self.web_sleep(900, 1600)

            selected_size_shipping_packages = [
                package for size, selector, package in shipping_options_mapping.values() if size == shipping_size
            ]
            wanted_shipping_packages = list(shipping_packages)

            js_all_packages = json.dumps(selected_size_shipping_packages, ensure_ascii=False)
            js_wanted_packages = json.dumps(wanted_shipping_packages, ensure_ascii=False)
            js_package_variants = json.dumps(shipping_package_variants, ensure_ascii=False)
            package_internal_id_by_label = {
                package_label: shipping_internal_id_by_option.get(option, "")
                for option, package_label in zip(requested_shipping_options, shipping_packages, strict = False)
            }
            js_package_internal_ids = json.dumps(package_internal_id_by_label, ensure_ascii=False)

            result = await self.web_execute(f"""(async function() {{
                const allPackages = {js_all_packages};
                const wantedPackages = new Set({js_wanted_packages});
                const packageVariants = {js_package_variants};
                const packageInternalIds = {js_package_internal_ids};
                const normalize = (value) => String(value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                const visible = (el) => {{
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && !el.disabled;
                }};
                const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]'));
                const root = dialogs.find(d => d.open || d.offsetParent !== null) || document;

                function fireMouse(el) {{
                    if (!el) return false;
                    try {{ el.scrollIntoView({{block: 'center', inline: 'center'}}); }} catch (e) {{}}
                    const opts = {{bubbles: true, cancelable: true, view: window}};
                    try {{ el.dispatchEvent(new PointerEvent('pointerdown', opts)); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new MouseEvent('mousedown', opts)); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new MouseEvent('mouseup', opts)); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new MouseEvent('click', opts)); }} catch (e) {{}}
                    try {{ el.click(); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new Event('input', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new Event('change', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    return true;
                }}

                function variantsFor(label) {{
                    return (packageVariants[label] || [label]).map(normalize);
                }}

                function ownText(el) {{
                    if (!el) return '';
                    const parts = [];
                    for (const attr of ['data-testid', 'id', 'name', 'value', 'aria-label']) {{
                        parts.push(el.getAttribute && (el.getAttribute(attr) || '') || '');
                    }}
                    parts.push(el.innerText || el.textContent || '');
                    return normalize(parts.join(' '));
                }}

                function textForControl(el) {{
                    if (!el) return '';
                    const parts = [];
                    for (const attr of ['data-testid', 'id', 'name', 'value', 'aria-label']) {{
                        parts.push(el.getAttribute && (el.getAttribute(attr) || '') || '');
                    }}
                    parts.push(el.innerText || el.textContent || '');
                    if (el.id) {{
                        const label = root.querySelector(`label[for="${{CSS.escape(el.id)}}"]`);
                        if (label) parts.push(label.innerText || label.textContent || '');
                    }}
                    // Only inspect very small local containers. Do not climb into the whole dialog,
                    // otherwise every button (e.g. "Schließen") appears to contain every package label.
                    let cur = el.parentElement;
                    for (let i = 0; i < 3 && cur && cur !== root; i++, cur = cur.parentElement) {{
                        const txt = normalize(cur.innerText || cur.textContent || '');
                        if (txt && txt.length <= 450) parts.push(txt);
                    }}
                    return normalize(parts.join(' '));
                }}

                // native wanted label click fix: after JS/React state checks, the Python layer also clicks the exact visible wanted label via browser automation.
                // label associated input click fix: Kleinanzeigen may expose a DHL package as
                // a visible label/card while the real radio/checkbox is hidden or visually detached.
                // Clicking only the label can look successful but leave the underlying input unchanged.
                function associatedInput(el) {{
                    if (!el) return null;
                    try {{
                        if (el.matches && el.matches('input[type="checkbox"], input[type="radio"]')) return el;
                    }} catch (e) {{}}
                    const forId = el.getAttribute && el.getAttribute('for');
                    if (forId) {{
                        try {{
                            const byFor = root.querySelector(`#${{CSS.escape(forId)}}`);
                            if (byFor && byFor.matches && byFor.matches('input[type="checkbox"], input[type="radio"]')) return byFor;
                        }} catch (e) {{}}
                    }}
                    try {{
                        if (el.querySelector) {{
                            const inner = el.querySelector('input[type="checkbox"], input[type="radio"]');
                            if (inner) return inner;
                        }}
                    }} catch (e) {{}}
                    let cur = el.parentElement;
                    for (let i = 0; i < 5 && cur && cur !== root; i++, cur = cur.parentElement) {{
                        const txt = normalize(cur.innerText || cur.textContent || '');
                        if (txt.length > 850) break;
                        try {{
                            const inputs = Array.from(cur.querySelectorAll('input[type="checkbox"], input[type="radio"]'));
                            if (inputs.length === 1) return inputs[0];
                            const visibleInputs = inputs.filter(inp => carrierMatches(inp, el.innerText || el.textContent || ''));
                            if (visibleInputs.length === 1) return visibleInputs[0];
                        }} catch (e) {{}}
                    }}
                    return null;
                }}

                function checkedLike(el) {{
                    if (!el) return false;
                    const input = associatedInput(el);
                    if (input && input !== el) return checkedLike(input);
                    return !!el.checked || el.getAttribute('aria-checked') === 'true' || el.hasAttribute('checked') ||
                           el.className && String(el.className).toLowerCase().includes('checked');
                }}

                function expectedCarrier(label) {{
                    const l = normalize(label);
                    if (l.includes('päckchen') || l.includes('s-paket') || l.includes('m-paket') || l.includes('l-paket')) return 'hermes';
                    if (l.includes('paket')) return 'dhl';
                    return '';
                }}

                function carrierInfo(el) {{
                    if (!el) return '';
                    const parts = [];
                    for (const attr of ['data-testid', 'id', 'name', 'value', 'aria-label', 'class']) {{
                        parts.push(el.getAttribute && (el.getAttribute(attr) || '') || '');
                    }}
                    try {{ parts.push(String(el.className || '')); }} catch (e) {{}}
                    if (el.id) {{
                        const label = root.querySelector(`label[for="${{CSS.escape(el.id)}}"]`);
                        if (label) {{
                            parts.push(label.getAttribute('class') || '');
                            parts.push(label.getAttribute('data-testid') || '');
                        }}
                    }}
                    return normalize(parts.join(' '));
                }}

                function carrierMatches(el, label) {{
                    const expected = expectedCarrier(label);
                    if (!expected) return true;
                    const info = carrierInfo(el); // medium DHL/Hermes carrier filter fix
                    if (!info) return true;
                    const mentionsDhl = info.includes('dhl');
                    const mentionsHermes = info.includes('hermes');
                    if (!mentionsDhl && !mentionsHermes) return true;
                    return info.includes(expected);
                }}

                function bestClickableForControl(el, label) {{
                    if (!el) return el;
                    let target = el;
                    if (el.id) {{
                        const labelEl = root.querySelector(`label[for="${{CSS.escape(el.id)}}"]`);
                        if (labelEl && visible(labelEl) && carrierMatches(labelEl, label)) target = labelEl;
                    }}
                    if (target === el) {{
                        const ownLabel = el.closest && el.closest('label');
                        if (ownLabel && root.contains(ownLabel) && visible(ownLabel) && carrierMatches(ownLabel, label)) target = ownLabel;
                    }}
                    return target;
                }}

                function setNativeChecked(input, value) {{
                    if (!input || !('checked' in input)) return false;
                    try {{
                        const proto = Object.getPrototypeOf(input);
                        const desc = Object.getOwnPropertyDescriptor(proto, 'checked') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'checked');
                        if (desc && desc.set) desc.set.call(input, value);
                        else input.checked = value;
                    }} catch (e) {{
                        try {{ input.checked = value; }} catch (e2) {{}}
                    }}
                    try {{ input.dispatchEvent(new Event('input', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    try {{ input.dispatchEvent(new Event('change', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    return checkedLike(input);
                }}

                async function activateControl(control, wanted) {{
                    const input = associatedInput(control);
                    // Click both the visible card/label and the underlying input. Some Kleinanzeigen
                    // React controls ignore a label-only click in headless Chromium.
                    fireMouse(control);
                    await sleep(120);
                    if (input) {{
                        fireMouse(input);
                        await sleep(120);
                        if (wanted && !checkedLike(input)) setNativeChecked(input, true);
                        if (!wanted && checkedLike(input)) setNativeChecked(input, false);
                    }}
                    await sleep(120);
                    return {{inputText: input ? normalize([input.getAttribute('id') || '', input.getAttribute('name') || '', input.getAttribute('value') || '', input.getAttribute('aria-label') || ''].join(' ')) : '', checked: input ? checkedLike(input) : checkedLike(control)}};
                }}

                function findControl(label) {{
                    const variants = variantsFor(label);
                    const actionWords = ['schließen', 'zurück', 'weiter', 'fertig'];

                    // 0) Provider-ID first. The fuzzy text matcher may see both Hermes Päckchen and
                    // Hermes S-Paket in one compact React container. Resolve the exact input value
                    // first so S-Paket cannot accidentally point to HERMES_001.
                    const expectedId = String(packageInternalIds[label] || '').toUpperCase();
                    if (expectedId) {{
                        const exactInputs = Array.from(root.querySelectorAll('input[type="checkbox"], input[type="radio"]')).filter(inp =>
                            String(inp.getAttribute('value') || inp.value || '').toUpperCase() === expectedId
                        );
                        if (exactInputs.length) return bestClickableForControl(exactInputs[0], label);
                    }}

                    // 1) Prefer real form controls, but avoid confusing Hermes and DHL controls when
                    // their compact parent contains both texts (e.g. Mittel: Hermes M + DHL 5 kg).
                    const controls = Array.from(root.querySelectorAll('input[type="checkbox"], input[type="radio"], [role="checkbox"], [role="radio"], [aria-checked], label'));
                    for (const el of controls) {{
                        if (!visible(el)) continue;
                        const t = textForControl(el);
                        if (variants.some(v => t.includes(v)) && carrierMatches(el, label)) return bestClickableForControl(el, label);
                    }}

                    // 2) New Kleinanzeigen UI: package methods are cards/buttons. Find a compact visible card
                    // containing the desired method, but never treat dialog action buttons as package cards.
                    const candidates = Array.from(root.querySelectorAll('button, label, div, span, li, p, article, section'));
                    let best = null;
                    let bestLen = 999999;
                    for (const el of candidates) {{
                        if (!visible(el)) continue;
                        const tOwn = ownText(el);
                        if (!variants.some(v => tOwn.includes(v))) continue;
                        if (actionWords.some(w => tOwn === w || tOwn.startsWith(w + ' '))) continue;

                        let card = el;
                        let cardText = tOwn;
                        for (let i = 0; i < 6 && card.parentElement && card.parentElement !== root; i++) {{
                            const parent = card.parentElement;
                            const pt = normalize(parent.innerText || parent.textContent || '');
                            const hasVariant = variants.some(v => pt.includes(v));
                            const tooBig = pt.length > 700;
                            if (!hasVariant || tooBig) break;
                            card = parent;
                            cardText = pt;
                        }}
                        // Prefer clickable ancestor if available, but keep it compact.
                        let clickable = card.closest && card.closest('button, label, [role="button"], [role="checkbox"], [role="radio"]');
                        if (clickable && root.contains(clickable)) {{
                            const ct = normalize(clickable.innerText || clickable.textContent || '');
                            if (ct && ct.length <= 700 && variants.some(v => ct.includes(v)) && !actionWords.some(w => ct === w || ct.startsWith(w + ' '))) {{
                                card = clickable;
                                cardText = ct;
                            }}
                        }}
                        const score = cardText.length;
                        if (score < bestLen) {{
                            best = card;
                            bestLen = score;
                        }}
                    }}
                    return best;
                }}

                const missing = [];
                const changed = [];
                const states = [];

                for (const label of allPackages) {{
                    const control = findControl(label);
                    if (!control) {{
                        missing.push(label);
                        continue;
                    }}
                    const wanted = wantedPackages.has(label);
                    const before = checkedLike(control);
                    // If there are no reliable checkbox states in this new UI, clicking only wanted cards is safer.
                    let activation = null;
                    if (wanted) {{
                        activation = await activateControl(control, true);
                        changed.push(label);
                        await sleep(150);
                    }} else {{
                        const realControl = associatedInput(control) || control;
                        if ((realControl.matches && realControl.matches('input[type="checkbox"]')) || realControl.getAttribute('role') === 'checkbox' || control.getAttribute('role') === 'checkbox') {{
                            if (before) {{
                                activation = await activateControl(control, false);
                                changed.push(label);
                                await sleep(100);
                            }}
                        }}
                    }}
                    const input = associatedInput(control);
                    states.push({{label, wanted, before, after: checkedLike(control), tag: control.tagName, text: normalize(control.innerText || control.textContent || control.value || '').slice(0,180), inputText: activation && activation.inputText || (input ? normalize([input.getAttribute('id') || '', input.getAttribute('name') || '', input.getAttribute('value') || '', input.getAttribute('aria-label') || ''].join(' ')) : ''), inputChecked: input ? checkedLike(input) : null}});
                }}

                const rootText = normalize(root.innerText || root.textContent || '');
                // clicked wanted card accept fix: In the new card UI a successful click can collapse/remove
                // the card text immediately, so findControl(label) may become false even though the wanted
                // DHL/Hermes option was clicked. Treat a clicked wanted label as provisional success and let
                // the later main-form visibility check verify the final selection after pressing Fertig.
                const wantedClicked = new Set(changed.filter(label => wantedPackages.has(label)));
                const wantedMissing = allPackages.filter(label => wantedPackages.has(label) && !wantedClicked.has(label) && !findControl(label));
                return {{ok: wantedMissing.length === 0, missing, wantedMissing, wantedClicked: Array.from(wantedClicked), changed, states, dialogText: rootText.slice(0,900)}};
            }})()""")
            LOG.warning(
                "Exact shipping option selection result: size=%s wanted=%s result=%s",
                shipping_size,
                wanted_shipping_packages,
                result,
            )

            if not isinstance(result, dict) or not result.get("ok"):
                # shipping direct set after exact selection fallback: do not abort here when
                # the dialog card matching missed one wanted option (e.g. Hermes M + DHL 5).
                # The following direct hidden-input setter can still publish the exact requested
                # options when their internal IDs are known or parsed from the dialog.
                await self.__debug_shipping_dialog_dump("shipping_dialog_exact_option_selection_failed")
                LOG.warning(
                    "Exact shipping option selection incomplete; continuing with direct hidden input fallback when possible. requested=%s packages=%s result=%s",
                    requested_shipping_options,
                    wanted_shipping_packages,
                    result,
                )

        except TimeoutError as ex:
            LOG.debug(ex, exc_info = True)
            await self.__debug_shipping_dialog_dump("shipping_dialog_exact_option_selection_timeout")
            raise TimeoutError(_("Unable to select requested shipping options exactly!")) from ex

        # shipping hidden inputs direct set fix: the current Kleinanzeigen React dialog can show
        # DHL_002 as checked, while the real form still contains the old small shippingOptions[].id
        # values (HERMES_001/HERMES_002/DHL_001). Publishing uses those hidden form fields, so set
        # them directly after resolving the internal values from the selected dialog controls.
        hidden_id_fallback_by_option = dict(shipping_internal_id_by_option)

        # large shipping scroll scan fix: Groß can be scrollable and the initially visible
        # dialog portion may only expose DHL 10/20. Scroll through the dialog and collect
        # the hidden DHL/Hermes input IDs for options such as DHL 31,5 kg before direct-set.
        shipping_dialog_scroll_scan_result = None
        if shipping_size == "Groß":
            js_scroll_all_packages = json.dumps(selected_size_shipping_packages, ensure_ascii=False)
            js_scroll_wanted_packages = json.dumps(wanted_shipping_packages, ensure_ascii=False)
            js_scroll_package_variants = json.dumps(shipping_package_variants, ensure_ascii=False)
            shipping_dialog_scroll_scan_result = await self.web_execute(f"""(async function() {{
                const allPackages = {js_scroll_all_packages};
                const wantedPackages = new Set({js_scroll_wanted_packages});
                const packageVariants = {js_scroll_package_variants};
                const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                const normalize = (value) => String(value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const visible = (el) => {{
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
                }};
                const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]'));
                const root = dialogs.find(d => d.open || d.offsetParent !== null) || document;

                function variantsFor(label) {{
                    return (packageVariants[label] || [label]).map(normalize);
                }}
                function expectedCarrier(label) {{
                    const l = normalize(label);
                    if (l.includes('päckchen') || l.includes('s-paket') || l.includes('m-paket') || l.includes('l-paket')) return 'hermes';
                    if (l.includes('paket')) return 'dhl';
                    return '';
                }}
                function carrierInfo(el) {{
                    if (!el) return '';
                    const parts = [];
                    for (const attr of ['data-testid', 'id', 'name', 'value', 'aria-label', 'class']) {{
                        parts.push(el.getAttribute && (el.getAttribute(attr) || '') || '');
                    }}
                    try {{ parts.push(String(el.className || '')); }} catch (e) {{}}
                    if (el.id) {{
                        try {{
                            const label = root.querySelector(`label[for="${{CSS.escape(el.id)}}"]`);
                            if (label) parts.push(label.innerText || label.textContent || '', label.getAttribute('class') || '');
                        }} catch (e) {{}}
                    }}
                    return normalize(parts.join(' '));
                }}
                function carrierMatches(el, label) {{
                    const expected = expectedCarrier(label);
                    if (!expected) return true;
                    const info = carrierInfo(el);
                    if (!info) return true;
                    const mentionsDhl = info.includes('dhl');
                    const mentionsHermes = info.includes('hermes');
                    if (!mentionsDhl && !mentionsHermes) return true;
                    return info.includes(expected);
                }}
                function textFor(el) {{
                    const parts = [];
                    if (!el) return '';
                    for (const attr of ['data-testid', 'id', 'name', 'value', 'aria-label']) {{
                        parts.push(el.getAttribute && (el.getAttribute(attr) || '') || '');
                    }}
                    parts.push(el.innerText || el.textContent || '');
                    if (el.id) {{
                        try {{
                            const label = root.querySelector(`label[for="${{CSS.escape(el.id)}}"]`);
                            if (label) parts.push(label.innerText || label.textContent || '');
                        }} catch (e) {{}}
                    }}
                    let cur = el.parentElement;
                    for (let i = 0; i < 4 && cur && cur !== root; i++, cur = cur.parentElement) {{
                        const txt = normalize(cur.innerText || cur.textContent || '');
                        if (txt && txt.length <= 900) parts.push(txt);
                    }}
                    return normalize(parts.join(' '));
                }}
                function associatedInput(el, label) {{
                    if (!el) return null;
                    try {{
                        if (el.matches && el.matches('input[type="checkbox"], input[type="radio"]') && carrierMatches(el, label)) return el;
                    }} catch (e) {{}}
                    const forId = el.getAttribute && el.getAttribute('for');
                    if (forId) {{
                        try {{
                            const byFor = root.querySelector(`#${{CSS.escape(forId)}}`);
                            if (byFor && byFor.matches && byFor.matches('input[type="checkbox"], input[type="radio"]') && carrierMatches(byFor, label)) return byFor;
                        }} catch (e) {{}}
                    }}
                    try {{
                        if (el.querySelector) {{
                            const inputs = Array.from(el.querySelectorAll('input[type="checkbox"], input[type="radio"]')).filter(inp => carrierMatches(inp, label));
                            if (inputs.length) return inputs[0];
                        }}
                    }} catch (e) {{}}
                    let cur = el.parentElement;
                    for (let i = 0; i < 6 && cur && cur !== root; i++, cur = cur.parentElement) {{
                        const txt = normalize(cur.innerText || cur.textContent || '');
                        if (txt.length > 1000) break;
                        try {{
                            const inputs = Array.from(cur.querySelectorAll('input[type="checkbox"], input[type="radio"]')).filter(inp => carrierMatches(inp, label));
                            if (inputs.length === 1) return inputs[0];
                            if (inputs.length > 1) {{
                                const labelCarrier = expectedCarrier(label);
                                const exact = inputs.find(inp => carrierInfo(inp).includes(labelCarrier));
                                if (exact) return exact;
                            }}
                        }} catch (e) {{}}
                    }}
                    return null;
                }}
                function parseHiddenId(el) {{
                    if (!el) return '';
                    const parts = [];
                    for (const attr of ['id', 'name', 'value', 'aria-label', 'data-testid']) {{
                        parts.push(el.getAttribute && (el.getAttribute(attr) || '') || '');
                    }}
                    try {{ parts.push(String(el.className || '')); }} catch (e) {{}}
                    const match = parts.join(' ').match(/\b(?:dhl|hermes)[_-]\d+\b/i);
                    return match ? match[0].replace('-', '_').toUpperCase() : '';
                }}
                function scrollables() {{
                    const items = [];
                    const add = (el) => {{ if (el && !items.includes(el)) items.push(el); }};
                    add(root);
                    try {{ add(document.scrollingElement || document.documentElement); }} catch (e) {{}}
                    for (const el of Array.from(root.querySelectorAll('*'))) {{
                        try {{
                            const st = getComputedStyle(el);
                            if (el.scrollHeight > el.clientHeight + 20 && ['auto', 'scroll', 'overlay'].some(v => (st.overflowY || '').includes(v) || (st.overflow || '').includes(v))) add(el);
                            else if (el.scrollHeight > el.clientHeight + 80) add(el);
                        }} catch (e) {{}}
                    }}
                    return items;
                }}
                function collect() {{
                    const parsedByLabel = {{}};
                    const seen = [];
                    const candidates = Array.from(root.querySelectorAll('input[type="checkbox"], input[type="radio"], label, [role="checkbox"], [role="radio"], [aria-checked], button, div, span, li, article, section'));
                    for (const el of candidates) {{
                        if (!visible(el)) continue;
                        const t = textFor(el);
                        for (const label of allPackages) {{
                            if (!variantsFor(label).some(v => t.includes(v))) continue;
                            if (!carrierMatches(el, label)) continue;
                            const input = associatedInput(el, label);
                            const hiddenId = parseHiddenId(input) || parseHiddenId(el);
                            seen.push({{label, tag: el.tagName, text: t.slice(0, 220), inputInfo: input ? carrierInfo(input).slice(0, 180) : '', hiddenId}});
                            if (hiddenId && !parsedByLabel[label]) parsedByLabel[label] = hiddenId;
                        }}
                    }}
                    return {{parsedByLabel, seen}};
                }}
                let parsedByLabel = {{}};
                const seen = [];
                const scrollLog = [];
                for (const scroller of scrollables()) {{
                    let max = 0;
                    try {{ max = Math.max(0, scroller.scrollHeight - scroller.clientHeight); }} catch (e) {{}}
                    const positions = max > 0 ? [0, Math.round(max * 0.25), Math.round(max * 0.5), Math.round(max * 0.75), max] : [0];
                    for (const pos of positions) {{
                        try {{ scroller.scrollTop = pos; scroller.dispatchEvent(new Event('scroll', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                        await sleep(180);
                        const c = collect();
                        Object.assign(parsedByLabel, c.parsedByLabel || {{}});
                        seen.push(...(c.seen || []));
                        scrollLog.push({{tag: scroller.tagName || 'DOCUMENT', id: scroller.id || '', pos, max, parsed: Object.assign({{}}, parsedByLabel)}});
                    }}
                }}
                try {{ root.scrollTop = 0; }} catch (e) {{}}
                const wantedMissing = Array.from(wantedPackages).filter(label => !parsedByLabel[label]);
                return {{ok: wantedMissing.length === 0, parsedByLabel, wantedMissing, seen: seen.slice(-80), scrollLog: scrollLog.slice(-30), dialogText: normalize(root.innerText || root.textContent || '').slice(0, 1000)}};
            }})()""")
            LOG.warning(
                "Shipping large dialog scroll scan result: wanted=%s result=%s",
                wanted_shipping_packages,
                shipping_dialog_scroll_scan_result,
            )

        hidden_id_by_label = {}
        if isinstance(result, dict):
            for state in result.get("states", []) or []:
                if not isinstance(state, dict) or not state.get("wanted"):
                    continue
                label = str(state.get("label", "") or "")
                input_text = str(state.get("inputText", "") or "")
                match = re.search(r"\b(?:dhl|hermes)[_-]\d+\b", input_text, flags=re.IGNORECASE)
                if match:
                    hidden_id_by_label[label] = match.group(0).replace("-", "_").upper()
        if isinstance(shipping_dialog_scroll_scan_result, dict):
            parsed_by_label = shipping_dialog_scroll_scan_result.get("parsedByLabel") or {}
            if isinstance(parsed_by_label, dict):
                for label, hidden_id in parsed_by_label.items():
                    if label and hidden_id:
                        hidden_id_by_label[str(label)] = str(hidden_id).replace("-", "_").upper()

        desired_hidden_ids = []
        missing_hidden_ids = []
        for option, package_label in zip(requested_shipping_options, shipping_packages, strict = False):
            # Canonical provider mapping wins over fuzzy label parsing. The 1.6.13 live log showed
            # S-Paket being parsed from the neighbouring Päckchen input (HERMES_001).
            hidden_id = hidden_id_fallback_by_option.get(option) or hidden_id_by_label.get(package_label)
            if hidden_id:
                desired_hidden_ids.append(hidden_id)
            else:
                missing_hidden_ids.append({"option": option, "label": package_label})

        if desired_hidden_ids and not missing_hidden_ids:
            desired_hidden_ids_json = json.dumps(desired_hidden_ids, ensure_ascii=False)
            requested_options_json = json.dumps(requested_shipping_options, ensure_ascii=False)
            direct_set_result = await self.web_execute(f"""(async function() {{
                const desired = {desired_hidden_ids_json};
                const requestedOptions = {requested_options_json};
                const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                const normalize = (value) => String(value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim();
                const visible = (el) => {{
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
                }};
                function readHidden() {{
                    return Array.from(document.querySelectorAll('input[name^="shippingOptions"]')).map(input => ({{
                        name: input.getAttribute('name') || '',
                        value: input.getAttribute('value') || input.value || '',
                        type: input.getAttribute('type') || '',
                    }}));
                }}
                function fire(el) {{
                    if (!el) return;
                    try {{ el.dispatchEvent(new Event('input', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                    try {{ el.dispatchEvent(new Event('change', {{bubbles: true, cancelable: true}})); }} catch (e) {{}}
                }}
                function setHiddenInputs() {{
                    const before = readHidden();
                    const mainButton = document.querySelector('#ad-shipping-options');
                    const form = (mainButton && mainButton.closest('form')) || document.querySelector('form') || document.body;
                    for (const input of Array.from(document.querySelectorAll('input[name^="shippingOptions"]'))) {{
                        try {{ input.remove(); }} catch (e) {{}}
                    }}
                    desired.forEach((value, index) => {{
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = `shippingOptions[${{index}}].id`;
                        input.value = value;
                        input.setAttribute('value', value);
                        input.setAttribute('data-chatgpt-direct-shipping', 'true');
                        form.appendChild(input);
                        fire(input);
                    }});
                    fire(form);
                    if (mainButton) fire(mainButton);
                    const after = readHidden();
                    return {{before, after}};
                }}
                function clickDialogClose() {{
                    const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]')).filter(visible);
                    const root = dialogs.length ? dialogs[dialogs.length - 1] : document;
                    const buttons = Array.from(root.querySelectorAll('button')).filter(visible);
                    const candidates = buttons.filter(b => ['schließen', 'fertig'].includes(normalize(b.innerText || b.textContent || '').toLowerCase()));
                    const btn = candidates.find(b => normalize(b.innerText || b.textContent || '').toLowerCase() === 'schließen') || candidates[0];
                    if (!btn) return {{clicked: false, buttons: buttons.map(b => normalize(b.innerText || b.textContent || '').slice(0, 80))}};
                    try {{ btn.scrollIntoView({{block: 'center', inline: 'center'}}); }} catch (e) {{}}
                    const opts = {{bubbles: true, cancelable: true, view: window}};
                    try {{ btn.dispatchEvent(new PointerEvent('pointerdown', opts)); }} catch (e) {{}}
                    try {{ btn.dispatchEvent(new MouseEvent('mousedown', opts)); }} catch (e) {{}}
                    try {{ btn.dispatchEvent(new MouseEvent('mouseup', opts)); }} catch (e) {{}}
                    try {{ btn.dispatchEvent(new PointerEvent('pointerup', opts)); }} catch (e) {{}}
                    try {{ btn.dispatchEvent(new MouseEvent('click', opts)); }} catch (e) {{}}
                    try {{ btn.click(); }} catch (e) {{}}
                    return {{clicked: true, text: normalize(btn.innerText || btn.textContent || ''), buttons: buttons.map(b => normalize(b.innerText || b.textContent || '').slice(0, 80))}};
                }}
                const firstSet = setHiddenInputs();
                const closeResult = clickDialogClose();
                await sleep(700);
                const secondSet = setHiddenInputs();
                await sleep(200);
                const current = readHidden();
                const currentIds = current.map(x => String(x.value || '').toUpperCase());
                const wantedIds = desired.map(x => String(x || '').toUpperCase());
                const ok = wantedIds.length === currentIds.length && wantedIds.every((id, index) => currentIds[index] === id);
                const shippingMain = document.querySelector('#ad-shipping-options');
                return {{
                    ok,
                    requestedOptions,
                    desired,
                    firstSet,
                    closeResult,
                    secondSet,
                    current,
                    mainText: normalize(shippingMain ? (shippingMain.innerText || shippingMain.textContent || '') : '').slice(0, 500),
                    openDialogsAfter: Array.from(document.querySelectorAll('dialog, [role="dialog"]')).filter(visible).map(d => normalize(d.innerText || d.textContent || '').slice(0, 250)),
                }};
            }})()""")
            LOG.warning(
                "Direct shipping hidden inputs set result: requested=%s desired=%s result=%s",
                requested_shipping_options,
                desired_hidden_ids,
                direct_set_result,
            )
            if isinstance(direct_set_result, dict) and direct_set_result.get("ok"):
                return
        else:
            LOG.warning(
                "Direct shipping hidden inputs skipped: desired=%s missing=%s parsed_by_label=%s requested=%s packages=%s",
                desired_hidden_ids,
                missing_hidden_ids,
                hidden_id_by_label,
                requested_shipping_options,
                list(shipping_packages),
            )

        # native wanted label click fix: The JS routine can set the hidden input to checked,
        # but Kleinanzeigen/React may still not commit it. Use the bot's normal browser click
        # on the exact visible wanted method label/card before pressing "Fertig".
        native_label_map = {
            "DHL_2": ["DHL Paket 2 kg", "Paket 2 kg"],
            "Hermes_Päckchen": ["Hermes Päckchen", "Päckchen"],
            "Hermes_S": ["Hermes S-Paket", "S-Paket"],
            "DHL_5": ["DHL Paket 5 kg", "Paket 5 kg"],
            "Hermes_M": ["Hermes M-Paket", "M-Paket"],
            "DHL_10": ["DHL Paket 10 kg", "Paket 10 kg"],
            "DHL_20": ["DHL Paket 20 kg", "Paket 20 kg"],
            "DHL_31,5": ["DHL Paket 31,5 kg", "Paket 31,5 kg", "DHL Paket 31.5 kg", "Paket 31.5 kg"],
            "Hermes_L": ["Hermes L-Paket", "L-Paket"],
        }
        for wanted_option in list(getattr(ad_cfg, "shipping_options", None) or []):
            clicked_native = False
            for native_label in native_label_map.get(wanted_option, [str(wanted_option)]):
                # Prefer labels; they are the visual controls Kleinanzeigen uses in the new shipping UI.
                native_xpaths = [
                    f'//*[self::dialog or @role="dialog"]//label[contains(normalize-space(.), "{native_label}")]',
                    f'//*[self::dialog or @role="dialog"]//*[@role="radio" or @role="checkbox" or @aria-checked][contains(normalize-space(.), "{native_label}")]',
                    f'//*[self::dialog or @role="dialog"]//button[not(contains(normalize-space(.), "Fertig")) and not(contains(normalize-space(.), "Zurück")) and not(contains(normalize-space(.), "Weiter")) and not(contains(normalize-space(.), "Schließen")) and contains(normalize-space(.), "{native_label}")]',
                    f'//*[self::dialog or @role="dialog"]//div[contains(normalize-space(.), "{native_label}") and string-length(normalize-space(.)) < 320]',
                ]
                for native_xpath in native_xpaths:
                    try:
                        await self.web_click(By.XPATH, native_xpath, timeout = self._timeout("quick_dom"))
                        await self.web_sleep(250, 450)
                        LOG.warning(
                            "Native wanted shipping option click result: option=%s label=%s xpath=%s",
                            wanted_option,
                            native_label,
                            native_xpath,
                        )
                        clicked_native = True
                        break
                    except TimeoutError:
                        continue
                if clicked_native:
                    break
            if not clicked_native:
                LOG.warning("Native wanted shipping option click did not find visible label/card for option=%s", wanted_option)

        try:
            # visible Fertig button click fix: the DOM can contain stale/hidden shipping dialogs.
            # Click the currently visible Fertig button inside the active dialog with full
            # pointer/mouse/click events, then verify only after the dialog had time to apply.
            apply_result = await self.web_execute("""(async function() {
                const normalize = (value) => String(value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
                };
                const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                function fireMouse(el) {
                    if (!el) return false;
                    try { el.scrollIntoView({block: 'center', inline: 'center'}); } catch (e) {}
                    const opts = {bubbles: true, cancelable: true, view: window};
                    try { el.focus({preventScroll: true}); } catch (e) {}
                    try { el.dispatchEvent(new PointerEvent('pointerover', opts)); } catch (e) {}
                    try { el.dispatchEvent(new PointerEvent('pointerenter', opts)); } catch (e) {}
                    try { el.dispatchEvent(new PointerEvent('pointerdown', opts)); } catch (e) {}
                    try { el.dispatchEvent(new MouseEvent('mouseover', opts)); } catch (e) {}
                    try { el.dispatchEvent(new MouseEvent('mouseenter', opts)); } catch (e) {}
                    try { el.dispatchEvent(new MouseEvent('mousedown', opts)); } catch (e) {}
                    try { el.dispatchEvent(new MouseEvent('mouseup', opts)); } catch (e) {}
                    try { el.dispatchEvent(new PointerEvent('pointerup', opts)); } catch (e) {}
                    try { el.dispatchEvent(new MouseEvent('click', opts)); } catch (e) {}
                    try { el.click(); } catch (e) {}
                    return true;
                }
                const dialogs = Array.from(document.querySelectorAll('dialog, [role="dialog"]')).filter(visible);
                const root = dialogs.length ? dialogs[dialogs.length - 1] : document;
                const buttons = Array.from(root.querySelectorAll('button')).filter(b => visible(b) && !b.disabled && b.getAttribute('aria-disabled') !== 'true');
                const btn = buttons.find(b => normalize(b.innerText || b.textContent || '') === 'fertig')
                    || buttons.find(b => normalize(b.innerText || b.textContent || '').includes('fertig'));
                const rootTextBefore = normalize(root.innerText || root.textContent || '').slice(0, 700);
                const buttonTexts = buttons.map(b => normalize(b.innerText || b.textContent || '').slice(0, 80));
                if (!btn) {
                    return {ok: false, reason: 'visible Fertig button not found', buttonTexts, rootTextBefore};
                }
                fireMouse(btn);
                await sleep(900);
                const shippingMain = document.querySelector('#ad-shipping-options');
                const mainText = normalize(shippingMain ? (shippingMain.innerText || shippingMain.textContent || '') : '').slice(0, 500);
                const openDialogsAfter = Array.from(document.querySelectorAll('dialog, [role="dialog"]'))
                    .filter(visible)
                    .map(d => normalize(d.innerText || d.textContent || '').slice(0, 250));
                return {
                    ok: true,
                    clickedText: normalize(btn.innerText || btn.textContent || ''),
                    buttonTexts,
                    rootTextBefore,
                    mainText,
                    openDialogsAfter
                };
            })()""")
            LOG.warning("Visible Fertig button click result: %s", apply_result)
            await self.web_sleep(1600, 2400)

            # Fallback: if the dialog is still visible, try the classic web_click once, but only after
            # logging the visible-button result above.
            if isinstance(apply_result, dict) and apply_result.get("openDialogsAfter"):
                try:
                    await self.web_click(By.XPATH, '//*[self::dialog or @role="dialog"]//button[contains(., "Fertig")]', timeout = self._timeout("quick_dom"))
                    LOG.warning("Fallback XPath Fertig button clicked after visible Fertig click")
                    await self.web_sleep(1200, 1800)
                except (TimeoutError, ProtocolException):
                    LOG.debug("Fallback XPath Fertig button not available after visible Fertig click", exc_info=True)

            if not await self.__requested_shipping_options_visible_in_main_form(ad_cfg):
                await self.__debug_shipping_dialog_dump("shipping_dialog_requested_options_not_visible_after_apply")
                raise TimeoutError(_("Requested shipping options are not visible after applying shipping dialog!"))
        except TimeoutError as ex:
            await self.__debug_shipping_dialog_dump("shipping_dialog_unable_to_close")
            if await self.__accept_visible_shipping_options_robust(ad_cfg):
                return
            raise TimeoutError(_("Unable to close shipping dialog!")) from ex

    async def __upload_images(self, ad_cfg:Ad) -> None:
        if not ad_cfg.images:
            return

        # Duplicate-title-image upload fix:
        # The staged/web-app image list is already ordered with the title image at index 0.
        # Do not ever add/upload that file a second time. Also clear the file input before
        # every single-file upload; Chromium/Kleinanzeigen may otherwise keep the previous
        # selection in the multiple-file input and re-submit the first/title image again.
        upload_images:list[Any] = []
        seen_upload_images:set[str] = set()
        for image in ad_cfg.images:
            try:
                image_key = str(Path(str(image)).resolve())
            except Exception:
                image_key = str(image)
            if image_key in seen_upload_images:
                LOG.warning(" -> skipping duplicate image before upload [%s]", image)
                continue
            seen_upload_images.add(image_key)
            upload_images.append(image)

        if not upload_images:
            return

        if len(upload_images) != len(ad_cfg.images):
            LOG.warning(" -> image upload list deduplicated: %d -> %d", len(ad_cfg.images), len(upload_images))

        LOG.info(" -> found %s", pluralize("image", upload_images))

        thumbnail_selector = "ul#j-pictureupload-thumbnails > li:not(.is-placeholder)"
        hidden_marker_selector = "input[name^='adImages'][name$='.url']"

        async def count_processed_images() -> int:
            thumbnail_count = 0
            marker_count = 0

            try:
                thumbnails = await self.web_find_all(By.CSS_SELECTOR, thumbnail_selector, timeout = self._timeout("quick_dom"))
                thumbnail_count = len(thumbnails)
            except TimeoutError:
                thumbnail_count = 0

            try:
                markers = await self.web_find_all(By.CSS_SELECTOR, hidden_marker_selector, timeout = self._timeout("quick_dom"))
                marker_count = sum(1 for marker in markers if str(getattr(marker.attrs, "value", "") or "").strip())
            except TimeoutError:
                marker_count = 0

            return max(thumbnail_count, marker_count)

        # Reihenfolge-Fix: Bilder nicht nur in sortierter Reihenfolge auswählen,
        # sondern jeweils warten, bis das gerade hochgeladene Bild verarbeitet ist.
        # Kleinanzeigen sortiert Thumbnails sonst gelegentlich nach Upload-/Verarbeitungsabschluss.
        for idx, image in enumerate(upload_images, start = 1):
            LOG.info(" -> uploading image [%s]", image)
            image_upload:Element = await self.web_find(By.CSS_SELECTOR, "input[type=file]")
            try:
                await self.web_execute("""(function() {
                    const input = document.querySelector('input[type=file]');
                    if (input) {
                        input.value = '';
                        try { input.dispatchEvent(new Event('input', {bubbles: true, cancelable: true})); } catch (e) {}
                        try { input.dispatchEvent(new Event('change', {bubbles: true, cancelable: true})); } catch (e) {}
                    }
                    return true;
                })()""")
                await self.web_sleep(120, 240)
            except Exception as ex:
                LOG.debug(" -> unable to clear file input before image upload: %s", ex, exc_info = True)
            await image_upload.send_file(image)
            await self.web_sleep()

            async def check_current_image_uploaded(expected_count:int = idx) -> bool:
                current_count = await count_processed_images()
                if current_count < expected_count:
                    LOG.debug(" -> %d of %d images processed", current_count, expected_count)
                return current_count >= expected_count

            await self.web_await(
                check_current_image_uploaded,
                timeout = self._timeout("image_upload"),
                timeout_error_message = _("Image upload timeout exceeded"),
            )

        # Wait for all images to be processed and thumbnails to appear
        expected_count = len(upload_images)
        LOG.info(" -> waiting for %s to be processed...", pluralize("image", upload_images))

        async def check_thumbnails_uploaded() -> bool:
            current_count = await count_processed_images()
            if current_count < expected_count:
                LOG.debug(" -> %d of %d images processed", current_count, expected_count)
            return current_count >= expected_count

        try:
            await self.web_await(check_thumbnails_uploaded, timeout = self._timeout("image_upload"), timeout_error_message = _("Image upload timeout exceeded"))
            final_count = await count_processed_images()
            if final_count > expected_count:
                LOG.warning(" -> more uploaded image markers/thumbnails than expected: expected=%d found=%d", expected_count, final_count)
        except TimeoutError as ex:
            # Get current count for better error message
            current_count = await count_processed_images()
            raise TimeoutError(
                _("Not all images were uploaded within timeout. Expected %(expected)d, found %(found)d processed images.")
                % {"expected": expected_count, "found": current_count}
            ) from ex

        LOG.info(" -> all images uploaded successfully")

    async def download_ads(self) -> None:
        """
        Determines which download mode was chosen with the arguments, and calls the specified download routine.
        This downloads either all, only unsaved(new), or specific ads given by ID.
        """
        # Normalize comma-separated keyword selectors; set deduplication collapses "new,new" → {"new"}
        selector_tokens = {s.strip() for s in self.ads_selector.split(",")}
        if "all" in selector_tokens:
            effective_selector = "all"
        elif len(selector_tokens) == 1:
            effective_selector = next(iter(selector_tokens))  # e.g. "new,new" → "new"
        else:
            effective_selector = self.ads_selector  # numeric IDs: "123,456" — unchanged

        # Fetch published ads once from manage-ads JSON to avoid repetitive API calls during extraction
        # Build lookup dict inline and pass directly to extractor (no cache abstraction needed)
        LOG.info("Fetching ad metadata (status, expiry dates)...")
        published_ads = await self._fetch_published_ads(strict = bool(_NUMERIC_IDS_RE.match(effective_selector)))
        published_ads_by_id:dict[int, dict[str, Any]] = {}
        for published_ad in published_ads:
            try:
                ad_id = published_ad.get("id")
                if ad_id is not None:
                    published_ads_by_id[int(ad_id)] = published_ad
            except (ValueError, TypeError):
                LOG.warning("Skipping ad with non-numeric id: %s", published_ad.get("id"))
        LOG.info("Loaded metadata for %s published ads.", len(published_ads_by_id))

        download_dir = self._resolve_download_dir()
        xdg_paths.ensure_directory(download_dir, "downloaded ads directory")
        LOG.info("Ads download directory: %s", download_dir)
        ad_extractor = extract.AdExtractor(self.browser, self.config, download_dir, published_ads_by_id = published_ads_by_id)

        if effective_selector in {"all", "new"}:  # explore ads overview for these two modes
            LOG.info("Scanning ad overview for navigation URLs...")
            own_ad_urls = await ad_extractor.extract_own_ads_urls()
            LOG.info("Found %s.", pluralize("ad URL", len(own_ad_urls)))

            if effective_selector == "all":  # download all of your ads
                LOG.info("Starting download of all ads...")

                success_count = 0
                # call download function for each ad page
                for ad_url in own_ad_urls:
                    ad_id = ad_extractor.extract_ad_id_from_ad_url(ad_url)
                    if ad_id == -1:
                        # Skip ads with invalid URLs (warning already logged by extract_ad_id_from_ad_url)
                        continue

                    if await ad_extractor.navigate_to_ad_page(ad_url):
                        await self._download_ad_with_resolved_state(ad_extractor, ad_id, published_ads_by_id)
                        success_count += 1
                LOG.info("%d of %d ads were downloaded from your profile.", success_count, len(own_ad_urls))

            elif effective_selector == "new":  # download only unsaved ads
                # check which ads already saved
                saved_ad_ids = []
                ads = self.load_ads(ignore_inactive = False, exclude_ads_with_id = False)  # do not skip because of existing IDs
                for ad in ads:
                    saved_ad_id = ad[1].id
                    if saved_ad_id is None:
                        LOG.debug("Skipping saved ad without id (likely unpublished or manually created): %s", ad[0])
                        continue
                    saved_ad_ids.append(int(saved_ad_id))

                # determine ad IDs from links
                ad_id_by_url = {url: ad_extractor.extract_ad_id_from_ad_url(url) for url in own_ad_urls}

                LOG.info("Starting download of not yet downloaded ads...")
                new_count = 0
                for ad_url, ad_id in ad_id_by_url.items():
                    # Skip ads with invalid URLs (warning already logged by extract_ad_id_from_ad_url)
                    if ad_id == -1:
                        continue

                    # check if ad with ID already saved
                    if ad_id in saved_ad_ids:
                        LOG.info("The ad with id %d has already been saved.", ad_id)
                        continue

                    if await ad_extractor.navigate_to_ad_page(ad_url):
                        await self._download_ad_with_resolved_state(ad_extractor, ad_id, published_ads_by_id)
                        new_count += 1
                LOG.info("%s were downloaded from your profile.", pluralize("new ad", new_count))

        elif _NUMERIC_IDS_RE.match(effective_selector):  # download ad(s) with specific id(s)
            ids = [int(n) for n in effective_selector.split(",")]
            LOG.info("Starting download of ad(s) with the id(s):")
            LOG.info(" | ".join([str(ad_id) for ad_id in ids]))

            for ad_id in ids:  # call download routine for every id
                exists = await ad_extractor.navigate_to_ad_page(ad_id)
                if exists:
                    resolved = self._resolve_download_ad_activity(ad_id, published_ads_by_id)
                    if not resolved.owned:
                        # Foreign ad - expected for numeric IDs (can download any public ad)
                        LOG.warning("Ad id %d is not in your published profile ads. Saving downloaded ad as inactive.", ad_id)

                    await ad_extractor.download_ad(ad_id, active = resolved.active)
                    LOG.info("Downloaded ad with id %d", ad_id)
                else:
                    LOG.error("The page with the id %d does not exist!", ad_id)

    def __get_description(self, ad_cfg:Ad, *, with_affixes:bool) -> str:
        """Get the ad description optionally with prefix and suffix applied.

        Precedence(highest to lowest):
        1. Direct ad - level affixes(description_prefix / suffix)
        2. Global flattened affixes(ad_defaults.description_prefix / suffix)
        3. Legacy global nested affixes(ad_defaults.description.prefix / suffix)

        Args:
            ad_cfg: The ad configuration dictionary

        Returns:
            The raw or complete description with prefix and suffix applied
        """
        # Get the main description text
        description_text = ""
        if ad_cfg.description:
            description_text = ad_cfg.description

        if with_affixes:
            # Get prefix with precedence
            prefix = (
                # 1. Direct ad-level prefix
                ad_cfg.description_prefix
                if ad_cfg.description_prefix is not None
                # 2. Global prefix from config
                else self.config.ad_defaults.description_prefix or ""  # Default to empty string if all sources are None
            )

            # Get suffix with precedence
            suffix = (
                # 1. Direct ad-level suffix
                ad_cfg.description_suffix
                if ad_cfg.description_suffix is not None
                # 2. Global suffix from config
                else self.config.ad_defaults.description_suffix or ""  # Default to empty string if all sources are None
            )

            # Combine the parts and replace @ with (at)
            final_description = str(prefix) + str(description_text) + str(suffix)
            final_description = final_description.replace("@", "(at)")
        else:
            final_description = description_text

        # Validate length
        ensure(
            len(final_description) <= MAX_DESCRIPTION_LENGTH,
            f"Length of ad description including prefix and suffix exceeds {MAX_DESCRIPTION_LENGTH} chars. Description length: {len(final_description)} chars.",
        )

        return final_description

    def update_content_hashes(self, ads:list[tuple[str, Ad, dict[str, Any]]]) -> None:
        count = 0

        for ad_file, ad_cfg, ad_cfg_orig in ads:
            LOG.info("Processing %s/%s: '%s' from [%s]...", count + 1, len(ads), ad_cfg.title, ad_file)
            ad_cfg.update_content_hash()
            if ad_cfg.content_hash != ad_cfg_orig["content_hash"]:
                count += 1
                ad_cfg_orig["content_hash"] = ad_cfg.content_hash
                dicts.save_dict(ad_file, ad_cfg_orig)

        LOG.info("############################################")
        LOG.info("DONE: Updated [content_hash] in %s", pluralize("ad", count))
        LOG.info("############################################")


#############################
# main entry point
#############################


def main(args:list[str]) -> None:
    if "version" not in args:
        print(
            textwrap.dedent(rf"""
         _    _      _                           _                       _           _
        | | _ | | ___(_)_ __   __ _ _ __  _______(_) __ _  ___ _ __ | |__   ___ | |_
        | | / / | / _ \ | '_ \ / _` | '_ \|_  / _ \ |/ _` |/ _ \ '_ \ ____| '_ \ / _ \| __|
        |   <| |  __/ | | | | (_| | | | |/ /  __/ | (_| |  __/ | | |____| |_) | (_) | |_
        |_|\_\_|\___|_|_| |_|\__,_|_| |_/___\___|_|\__, |\___|_| |_|    |_.__/ \___/ \__|
                                                   |___/
                                 https://github.com/Second-Hand-Friends/kleinanzeigen-bot
                                 Version: {__version__}
        """)[1:],
            flush = True,
        )  # [1:] removes the first empty blank line

    loggers.configure_console_logging()

    signal.signal(signal.SIGINT, error_handlers.on_sigint)  # capture CTRL+C

    # sys.excepthook = error_handlers.on_exception
    # -> commented out because it causes PyInstaller to log "[PYI-28040:ERROR] Failed to execute script '__main__' due to unhandled exception!",
    #    despite the exceptions being properly processed by our custom error_handlers.on_exception callback.
    #    We now handle exceptions explicitly using a top-level try/except block.

    atexit.register(loggers.flush_all_handlers)

    try:
        bot = KleinanzeigenBot()
        atexit.register(bot.close_browser_session)
        nodriver.loop().run_until_complete(bot.run(args))  # type: ignore[attr-defined]
    except CaptchaEncountered as ex:
        raise ex
    except Exception:
        error_handlers.on_exception(*sys.exc_info())


if __name__ == "__main__":
    loggers.configure_console_logging()
    LOG.error("Direct execution not supported. Use 'pdm run app'")
    sys.exit(1)
