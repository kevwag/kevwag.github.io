import time
_BOOTSTRAP_START = time.monotonic()
import importlib
import json
import os
import re
import sys
import threading
import urllib.parse
import datetime
import hashlib
import html
import shutil
import traceback
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
import xbmc

from iptv import IPTV, build_m3u_content, ProviderFetchError, _m3u_safe
from epg import EPG, _parse_xmltv_time, epg_file_has_data
from profiles import ProfileManager, RefreshTracker
from lang import _t
from core.runtime import AddonRuntime
import pvr.paths as _pvr_paths
import pvr.instances as _pvr_instances
import core.kodi as _core_kodi
import core.settings as _core_settings
import core.ui as _core_ui
import menus.main as _menus_main

_sports_routes = None
_sports_routes_setup = None
_downloader_module = None
_favorites_class = None
_history_classes = None
_tmdb_module = None

addon = xbmcaddon.Addon()
addon_handle = int(sys.argv[1])
base_url = sys.argv[0]
args = urllib.parse.parse_qs(sys.argv[2][1:])
mode = args.get("mode", [None])[0]
pm = ProfileManager(addon)
runtime = AddonRuntime(addon, addon_handle, base_url, args, mode, pm)
_BOOTSTRAP_READY = time.monotonic()
_ROUTE_START = _BOOTSTRAP_READY


def _get_downloader_module():
    global _downloader_module
    if _downloader_module is None:
        import downloader as _dl
        _downloader_module = _dl
    return _downloader_module


def is_url_downloadable(url):
    return _get_downloader_module().is_url_downloadable(url)


def mark_zombie_downloads_failed():
    return _get_downloader_module().mark_zombie_downloads_failed()


def _get_favorites_class():
    global _favorites_class
    if _favorites_class is None:
        from favorites import Favorites as _Favorites
        _favorites_class = _Favorites
    return _favorites_class


def _get_history_classes():
    """Lazy-load history classes so moved menu/TMDB routes keep working after refactor."""
    global _history_classes
    if _history_classes is None:
        from history import WatchedMovies, WatchedEpisodes, WatchHistory, ResumePoints
        _history_classes = {
            "WatchedMovies": WatchedMovies,
            "WatchedEpisodes": WatchedEpisodes,
            "WatchHistory": WatchHistory,
            "ResumePoints": ResumePoints,
        }
    return _history_classes


def _get_tmdb_module():
    global _tmdb_module
    if _tmdb_module is None:
        import tmdb as _tmdb_loaded
        _tmdb_module = _tmdb_loaded
    return _tmdb_module


class _LazyModule:
    """Import and initialize a moved module only when a route actually uses it."""

    def __init__(self, module_name, init_callback=None):
        self._module_name = module_name
        self._init_callback = init_callback
        self._module = None
        self._init_done = False
        self._lock = threading.Lock()

    def _load(self):
        if self._module is not None and self._init_done:
            return self._module
        with self._lock:
            if self._module is None:
                self._module = importlib.import_module(self._module_name)
            if not self._init_done and self._init_callback:
                self._init_callback(self._module)
            self._init_done = True
            return self._module

    def __getattr__(self, name):
        return getattr(self._load(), name)


_provider_availability = _LazyModule("metadata.provider_availability", lambda module: module.init(globals()))
_tmdb_bridge = _LazyModule("metadata.tmdb_bridge", lambda module: module.init(globals()))
_user_settings = _LazyModule("user.settings_routes", lambda module: module.init(globals()))
_startup = _LazyModule("startup", lambda module: module.init(globals()))
_user_profile_refresh = _LazyModule("user.profile_refresh", lambda module: module.init(globals()))
_live_menus = _LazyModule("live.menus", lambda module: module.init(globals()))
_live_playback = _LazyModule("live.playback", lambda module: module.init(globals()))
_live_sources = _LazyModule("live.sources", lambda module: module.init(globals()))
_live_search = _LazyModule("live.search", lambda module: module.init(globals()))
_live_browse = _LazyModule("live.browse", lambda module: module.init(globals()))
_live_replay = _LazyModule("live.replay", lambda module: module.init(globals()))
_user_artwork = _LazyModule("user.artwork", lambda module: module.init(addon, _log))
_user_backup = _LazyModule("user.backup", lambda module: module.init(addon, _log, _t, _safe_fsync, _cache_clear_all))
_menus_hidden = _LazyModule("menus.hidden", lambda module: _init_menus_hidden_module(module))
_menus_recent = _LazyModule("menus.recent", lambda module: _init_menus_recent_module(module))
_menus_favorites = _LazyModule("menus.favorites", lambda module: _init_menus_favorites_module(module))
_user_tools = _LazyModule("user.tools", lambda module: _init_user_tools_module(module))
_user_profiles = _LazyModule("user.profiles", lambda module: _init_user_profiles_module(module))
_pvr_scope = _LazyModule("pvr.scope", lambda module: _init_pvr_scope_module(module))
_pvr_health = _LazyModule("pvr.health", lambda module: _init_pvr_health_module(module))
_pvr_favorites = _LazyModule("pvr.favorites", lambda module: module.init(globals()))
_pvr_sync = _LazyModule("pvr.sync", lambda module: module.init(globals()))
_pvr_export = _LazyModule("pvr.export", lambda module: _init_pvr_export_module(module))
_router = _LazyModule("router", lambda module: _init_router_module(module))


PVR_LIVE_GROUP_PREFIX = "Live TV - "
PVR_SPORTS_GROUP_PREFIX = "Sports TV - "
PVR_FILE_SLUG = "xstream_pro"



def _pvr_live_group_label(group):
    return _pvr_paths._pvr_live_group_label(group)


def _strip_pvr_live_group_prefix(group):
    return _pvr_paths._strip_pvr_live_group_prefix(group)


def _request_pvr_scan(label="PVR"):
    return _pvr_instances._request_pvr_scan(label)


def _pvr_iptvsimple_profile_dir():
    return _pvr_paths._pvr_iptvsimple_profile_dir()


def _pvr_instance_settings_path(instance_id):
    return _pvr_paths._pvr_instance_settings_path(instance_id)


def _pvr_instance_role(settings_path):
    return _pvr_instances._pvr_instance_role(settings_path)


def _cleanup_legacy_xstream_pvr_instances(log_prefix="PVR legacy cleanup"):
    return _pvr_instances._cleanup_legacy_xstream_pvr_instances(log_prefix)


def _get_pvr_instance_id(role):
    return _pvr_instances._get_pvr_instance_id(role)


def _set_owned_pvr_instance_enabled(role, enabled, log_prefix="PVR"):
    return _pvr_instances._set_owned_pvr_instance_enabled(role, enabled, log_prefix)


def _role_has_instance(role):
    return _pvr_instances._role_has_instance(role)


def _owned_pvr_instance_enabled(role):
    return _pvr_instances._owned_pvr_instance_enabled(role)


def _current_pvr_instance_scope():
    return _pvr_instances._current_pvr_instance_scope()


def _pvr_scope_dot(scope):
    return _pvr_instances._pvr_scope_dot(scope)


def _pvr_instance_matches_paths(role, expected_m3u, expected_epg=""):
    return _pvr_instances._pvr_instance_matches_paths(role, expected_m3u, expected_epg)


def _sports_pvr_ready():
    return _pvr_instances._sports_pvr_ready()


def _reload_iptv_simple_addon(label="PVR", progress=None, start_percent=80, stop_manager=True):
    return _pvr_instances._reload_iptv_simple_addon(label, progress, start_percent, stop_manager)


def _ensure_pvr_instance_paths(scope, label=None, repair=False):
    return _pvr_scope._ensure_pvr_instance_paths(scope, label=label, repair=repair)


def _switch_pvr_instance_scope(scope, label=None, force=False, reload_epg=False):
    return _pvr_scope._switch_pvr_instance_scope(scope, label=label, force=force, reload_epg=reload_epg)


_PVR_OPEN_LOCK_PROP = "xstream_pro.pvr_opening"
_PVR_OPEN_LOCK_STALE_SECONDS = 120


def _pvr_open_guard(scope_label):
    return _pvr_scope._pvr_open_guard(scope_label)


def _pvr_open_release():
    return _pvr_scope._pvr_open_release()


def _session_should_run(key, ttl_seconds=0):
    try:
        win = xbmcgui.Window(10000)
        prop = f"xstream_pro.{key}"
        now = time.time()
        raw = win.getProperty(prop)
        if raw:
            if not ttl_seconds:
                return False
            try:
                if now - float(raw) < ttl_seconds:
                    return False
            except ValueError:
                pass
        win.setProperty(prop, str(now))
    except Exception:
        return True
    return True


def _invalidate_fast_setting_cache():
    return _core_settings._invalidate_fast_setting_cache()


def _get_setting_fast(setting_id, default=""):
    return _core_settings._get_setting_fast(setting_id, default=default)


def _new_listitem(label=""):
    return _core_ui._new_listitem(label=label)


def _configure_kodi_pvr_osd():
    """Configure Kodi's PVR OSD navigation settings"""
    try:
        if (_get_setting_direct("pvr_osd_navigation", "true") or "").lower() != "true":
            return

        settings = {
            "pvrplayback.confirmchannelswitch": "false",
            "pvrplayback.channelentrytimeout": "0",
        }

        for setting, value in settings.items():
            xbmc.executeJSONRPC(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "Settings.SetSettingValue",
                        "params": {"setting": setting, "value": value},
                        "id": 1,
                    }
                )
            )

        xbmc.log("[Xstream Pro] Configured Kodi PVR OSD settings", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[Xstream Pro] PVR OSD config failed: {e}", xbmc.LOGWARNING)


def _install_pvr_keymap():
    """Install PVR keymap for fullscreen and channel-list shortcuts."""
    try:
        keymaps_dir = xbmcvfs.translatePath("special://profile/keymaps/")
        keymap_path = os.path.join(keymaps_dir, "xstream_pvr.xml")

        fullscreen_enabled = (_get_setting_direct("pvr_osd_navigation", "true") or "").lower() == "true"
        left_enabled = fullscreen_enabled and (
            (_get_setting_direct("pvr_left_channels", "true") or "").lower() == "true"
        )
        right_enabled = fullscreen_enabled and (
            (_get_setting_direct("pvr_right_guide", "true") or "").lower() == "true"
        )
        channel_left_groups_enabled = (
            (_get_setting_direct("pvr_channel_list_left_groups", "true") or "").lower() == "true"
        )
        channel_right_search_enabled = (
            (_get_setting_direct("pvr_channel_list_right_search", "true") or "").lower() == "true"
        )

        if (
            not left_enabled
            and not right_enabled
            and not channel_left_groups_enabled
            and not channel_right_search_enabled
        ):
            if os.path.exists(keymap_path):
                try:
                    os.remove(keymap_path)
                except Exception as e:
                    xbmc.log(
                        f"[Xstream Pro] PVR keymap remove failed: {e}",
                        xbmc.LOGWARNING,
                    )
                if not os.path.exists(keymap_path):
                    try:
                        xbmc.executebuiltin("Action(ReloadKeymaps)")
                    except Exception:
                        pass
            return

        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<keymap>"]
        if left_enabled or right_enabled:
            lines.append("  <FullscreenLiveTV>")
            for device in ("keyboard", "remote"):
                lines.append(f"    <{device}>")
                if left_enabled:
                    lines.append("      <left>ActivateWindow(PVROSDChannels)</left>")
                if right_enabled:
                    lines.append("      <right>ActivateWindow(PVROSDGuide)</right>")
                lines.append(f"    </{device}>")
            lines.append("  </FullscreenLiveTV>")
        if channel_left_groups_enabled or channel_right_search_enabled:
            lines.append("  <TVChannels>")
            for device in ("keyboard", "remote"):
                lines.append(f"    <{device}>")
                if channel_left_groups_enabled:
                    lines.append("      <left>SendClick(28)</left>")
                if channel_right_search_enabled:
                    lines.append("      <right>ActivateWindow(TVSearch)</right>")
                lines.append(f"    </{device}>")
            lines.append("  </TVChannels>")
        lines.append("</keymap>")
        keymap_xml = "\n".join(lines) + "\n"

        # Rewrite only if content changed (or file missing)
        if os.path.exists(keymap_path):
            try:
                with open(keymap_path, "r", encoding="utf-8") as f:
                    if f.read() == keymap_xml:
                        return
            except Exception as e:
                xbmc.log(f"[Xstream Pro] keymap read warning: {e}", xbmc.LOGWARNING)

        os.makedirs(keymaps_dir, exist_ok=True)
        with open(keymap_path, "w", encoding="utf-8") as f:
            f.write(keymap_xml)
        xbmc.log("[Xstream Pro] Installed PVR keymap", xbmc.LOGINFO)
        try:
            xbmc.executebuiltin("Action(ReloadKeymaps)")
        except Exception:
            pass
    except Exception as e:
        xbmc.log(f"[Xstream Pro] PVR keymap install failed: {e}", xbmc.LOGWARNING)


_LOG_REDACT_PATH_RE = re.compile(
    r"(/(?:live|movie|series)/)([^/?\s]+)(/?)([^/?\s]*)", re.IGNORECASE
)
_LOG_REDACT_QUERY_RE = re.compile(r"(?i)\b(password|pwd|pass|username|user|token|key|apikey|api_key|auth)=([^&\s]+)")
_LOG_MAX_LEN = 4000


def _log(msg):
    safe_msg = str(msg)
    safe_msg = _LOG_REDACT_PATH_RE.sub(
        lambda m: (
            m.group(1)
            + "***REDACTED***"
            + m.group(3)
            + ("***REDACTED***" if m.group(4) else "")
        ),
        safe_msg,
    )
    safe_msg = _LOG_REDACT_QUERY_RE.sub(r"\1=***REDACTED***", safe_msg)
    if len(safe_msg) > _LOG_MAX_LEN:
        safe_msg = safe_msg[:_LOG_MAX_LEN] + "...[truncated]"
    xbmc.log(f"[Xstream Pro] {safe_msg}", xbmc.LOGINFO)


def _safe_url_for_log(url):
    return _core_kodi._safe_url_for_log(url)


def _log_route_timing(route_label=None):
    try:
        route_ms = int((time.monotonic() - _ROUTE_START) * 1000)
        bootstrap_ms = int((_BOOTSTRAP_READY - _BOOTSTRAP_START) * 1000)
        label = route_label or mode or "root"
        _log(
            "Route timing: {0} bootstrap_ms={1} route_ms={2}".format(
                label,
                bootstrap_ms,
                route_ms,
            )
        )
    except Exception:
        pass


def _is_tvos():
    return _core_kodi._is_tvos()


def _tvos_sleep(ms):
    return _core_kodi._tvos_sleep(ms)


def _safe_fsync(f):
    return _core_kodi._safe_fsync(f)


def _atomic_write_text(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp, path)


def _m3u_file_has_channels(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return any(line.startswith("#EXTINF:") for line in f)
    except OSError:
        return False


PVR_LARGE_LIST_WARN_CHANNELS = 10000

_pvr_paths.init(addon)
_core_kodi.init(addon, _log)
_core_settings.init(addon, _log)
_core_ui.init(addon, base_url, _log)
_pvr_instances.init(addon, _log, _m3u_file_has_channels, _safe_fsync, epg_file_has_data, _t)
def _m3u_channel_count(path):
    return _pvr_scope._m3u_channel_count(path)


def _confirm_large_pvr_list(path, label):
    count = _m3u_channel_count(path)
    if count <= PVR_LARGE_LIST_WARN_CHANNELS:
        return True
    msg = (
        f"{label} has {count} channels. Very large native PVR lists can make "
        "Kodi or IPTV Simple slow or unstable on startup. Continue loading this "
        "full list into native PVR?"
    )
    try:
        return xbmcgui.Dialog().yesno("Xstream Pro", msg)
    except Exception as e:
        _log(f"PVR: large list confirmation warning: {e}")
        return True


RESTART_PROMPT_PROP = "xstream_pro.restart_prompted"


def _prompt_restart_once(message, title="Xstream Pro", notification=False):
    win = xbmcgui.Window(10000)
    if win.getProperty(RESTART_PROMPT_PROP) == "true":
        _log("Restart already prompted this session; suppressing duplicate")
        return
    win.setProperty(RESTART_PROMPT_PROP, "true")
    _log("Prompting restart: {0}".format(message))
    if notification:
        xbmcgui.Dialog().notification(title, message, xbmcgui.NOTIFICATION_INFO, 7000)
    elif xbmc.getCondVisibility("System.Platform.Android") or _is_tvos():
        xbmcgui.Dialog().ok(title, message)
    else:
        xbmc.executebuiltin("RestartApp")


def _restart_or_prompt():
    """RestartApp is a no-op on Android and crashes on tvOS; prompt manual restart on both."""
    _prompt_restart_once(_t(30569), title=_t(30042))


def build_url(query):
    return _core_ui.build_url(query)


def _apply_sort(stype):
    """Apply Kodi sort method based on per-type user preference.
    'Newest first' is handled via Python pre-sort before pagination,
    so this only registers Kodi-level sort when 'A-Z' is selected.
    """
    setting_key = f"sort_order_{stype}"
    order = addon.getSetting(setting_key) or "Provider order"
    if order == "A-Z":
        xbmcplugin.addSortMethod(addon_handle, xbmcplugin.SORT_METHOD_LABEL)


def _get_pagination_limit(stype):
    """Return per-page limit from settings. Unlimited returns 0 (show all)."""
    val = addon.getSetting(f"pagination_{stype}") or "Unlimited"
    if val == "Unlimited":
        return 0
    try:
        return int(val)
    except ValueError:
        return 0


def _m3u_has_credentials(m3u_url):
    """Return True if the M3U URL contains embedded credentials in any supported format.

    M3U URLs with credentials are treated like Xtream Codes for UI purposes,
    showing separate Live TV, Movies, and Series categories.
    """
    from profiles import parse_m3u_credentials
    base, user, pwd = parse_m3u_credentials(m3u_url)
    return bool(base and user and pwd)


def _get_credentials():
    """Get credentials for current profile (pm.active).

    ProfileManager already extracts Xtream credentials from M3U URLs,
    so we return its result directly.
    """
    return pm.get_credentials()


class _LazyFavorites:
    """Proxy that defers Favorites(addon, 'global') load until first attribute access."""
    _real = None

    def _instance(self):
        if self._real is None:
            _LazyFavorites._real = _get_favorites_class()(addon, "global")
        return _LazyFavorites._real

    def __getattr__(self, name):
        return getattr(self._instance(), name)


fav = _LazyFavorites()

_profile_fav_instances = {}


def _get_profile_fav(profile_num):
    key = str(profile_num)
    if key not in _profile_fav_instances:
        _profile_fav_instances[key] = _get_favorites_class()(addon, key)
    return _profile_fav_instances[key]


def _invalidate_profile_fav(profile_num):
    _profile_fav_instances.pop(str(profile_num), None)


def _build_favorite_ctx(
    item_id,
    name,
    stype,
    icon,
    url,
    epg_id="",
    catchup="",
    catchup_source="",
    catchup_days="",
    profile_num=None,
    year="",
    showname="",
    season="",
    episode="",
    include_download=True,
):
    """Build context-menu tuples for toggling an item in addon favorites.

    Returns a list of (label, action) tuples.
    """
    ctx = []
    if profile_num:
        profile_fav = _get_profile_fav(profile_num)
        if profile_fav.is_favorite(item_id):
            ctx.append(
                (
                    _t(30747),
                    f"RunPlugin({build_url({'mode': 'toggle_profile_fav', 'id': item_id, 'name': name, 'stype': stype, 'icon': icon, 'url': url, 'epg_id': epg_id, 'pnum': profile_num})})",
                )
            )
        else:
            ctx.append(
                (
                    _t(30746),
                    f"RunPlugin({build_url({'mode': 'toggle_profile_fav', 'id': item_id, 'name': name, 'stype': stype, 'icon': icon, 'url': url, 'epg_id': epg_id, 'pnum': profile_num})})",
                )
            )

    protected_folders = {"Favorites", _t(30009) or "Favorites"}
    for gname in fav.get_folders():
        if gname in protected_folders:
            continue
        ctx.append(
            (
                _t(30219, gname),
                f"RunPlugin({build_url({'mode': 'toggle_fav', 'id': item_id, 'name': name, 'stype': stype, 'icon': icon, 'url': url, 'epg_id': epg_id, 'folder': gname, 'catchup': catchup, 'catchup_source': catchup_source, 'catchup_days': catchup_days})})",
            )
        )

    if include_download and is_url_downloadable(url):
        download_url = build_url({
            "mode": "download",
            "url": url,
            "title": name,
            "stype": stype,
            "profile_num": profile_num or pm.active,
        })
        ctx.append((_t(30941), f"RunPlugin({download_url})"))

    return ctx


def _folder_favorite_ctx(name, url, icon):
    """Build context-menu tuples for a folder-type favorite."""
    return _build_favorite_ctx(url, name, "folder", icon, url, include_download=False)


def _tmdb_content_type(tmdb_type, season="", episode=""):
    if tmdb_type == "tv" and (season or episode):
        return "episodes"
    if tmdb_type == "tv":
        return "tvshows"
    return "movies"


def _set_tmdb_content(tmdb_type, season="", episode=""):
    xbmcplugin.setContent(addon_handle, _tmdb_content_type(tmdb_type, season, episode))


def _tmdb_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in re.split(r"\s*,\s*|\s*/\s*", str(value)) if v.strip()]


def _safe_set(callable, field_name=""):
    """Run a metadata setter, logging failures lightly."""
    try:
        callable()
    except Exception:
        if field_name:
            _log(f"TMDB info: failed to set {field_name}")


def _safe_int_value(value, default=0):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _season_episode_total(eps):
    total = len(eps or [])
    max_ep = 0
    for ep in eps or []:
        num = _safe_int_value(ep.get("episode_num") or ep.get("num"))
        if num > max_ep:
            max_ep = num
    return max(total, max_ep)


def _provider_stream_tmdb_id(item):
    for key in ("tmdb_id", "tmdb", "tmdbid"):
        value = str((item or {}).get(key) or "").strip()
        if value:
            return value
    info = (item or {}).get("info")
    if isinstance(info, dict):
        for key in ("tmdb_id", "tmdb", "tmdbid"):
            value = str(info.get(key) or "").strip()
            if value:
                return value
    return ""


def _provider_tmdb_meta_map(streams, stype):
    media_type = "tv" if stype == "series" else "movie"
    pairs = []
    for item in streams or []:
        tmdb_id = _provider_stream_tmdb_id(item)
        if tmdb_id:
            pairs.append((media_type, tmdb_id))
    if not pairs:
        return {}
    try:
        cached = _get_tmdb_module().meta_cache_get_many(pairs)
    except Exception as exc:
        _log("Provider TMDB cache read warning: {0}".format(exc))
        return {}
    out = {}
    for item in streams or []:
        tmdb_id = _provider_stream_tmdb_id(item)
        if not tmdb_id:
            continue
        meta = cached.get((media_type, tmdb_id))
        if meta:
            out[id(item)] = meta
    return out


def _queue_provider_tmdb_meta_prefetch(streams, stype, limit=20):
    media_type = "tv" if stype == "series" else "movie"
    missing = []
    for item in streams or []:
        tmdb_id = _provider_stream_tmdb_id(item)
        if not tmdb_id:
            continue
        try:
            if not _get_tmdb_module().meta_cache_get(media_type, tmdb_id):
                missing.append(tmdb_id)
        except Exception:
            continue
        if len(missing) >= limit:
            break
    if not missing:
        return

    def _worker():
        for tmdb_id in missing:
            try:
                _get_tmdb_module().meta_summary_cached(media_type, tmdb_id)
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()


def _merge_provider_tmdb_meta(info, meta, stype="movie"):
    info = dict(info or {})
    media_type = "tv" if stype == "series" else "movie"
    if not meta:
        if not info.get("duration") and info.get("tmdb_id"):
            try:
                fallback = _get_tmdb_module().meta_cache_get(media_type, info["tmdb_id"])
                if fallback and fallback.get("runtime"):
                    info["duration"] = fallback["runtime"]
                if fallback and not info.get("genre") and fallback.get("genre"):
                    info["genre"] = fallback["genre"]
                if fallback and not info.get("cast") and fallback.get("cast"):
                    info["cast"] = fallback["cast"]
            except Exception:
                pass
        return info
    field_map = {
        "plot": "plot",
        "poster": "poster_url",
        "fanart": "fanart",
        "rating": "rating",
        "votes": "votes",
        "premiered": "premiered",
        "title": "title",
        "year": "year",
        "runtime": "duration",
        "cast": "cast",
        "genre": "genre",
        "director": "director",
        "writer": "writer",
        "studio": "studio",
        "mpaa": "mpaa",
        "tagline": "tagline",
    }
    for src, dst in field_map.items():
        value = meta.get(src)
        if value:
            info[dst] = value
    return info


def _set_provider_tmdb_info_fields(info_tag, info):
    if not info:
        return
    if info.get("premiered"):
        _safe_set(lambda: info_tag.setPremiered(str(info["premiered"])), "premiered")
    if info.get("rating"):
        _safe_set(
            lambda: info_tag.setRating(
                float(info["rating"]),
                _safe_int_value(info.get("votes")),
            ),
            "rating",
        )
    genres = _tmdb_list(info.get("genre"))
    if genres:
        _safe_set(lambda: info_tag.setGenres(genres), "genres")
    directors = _tmdb_list(info.get("director"))
    if directors:
        _safe_set(lambda: info_tag.setDirectors(directors), "directors")
    writers = _tmdb_list(info.get("writer"))
    if writers:
        _safe_set(lambda: info_tag.setWriters(writers), "writers")
    studios = _tmdb_list(info.get("studio"))
    if studios:
        _safe_set(lambda: info_tag.setStudios(studios), "studios")
    if info.get("mpaa"):
        _safe_set(lambda: info_tag.setMpaa(str(info["mpaa"])), "mpaa")
    if info.get("tagline"):
        _safe_set(lambda: info_tag.setTagLine(str(info["tagline"])), "tagline")
    cast = info.get("cast")
    if cast and isinstance(cast, list):
        def _set_cast():
            cast_list = []
            for idx, actor in enumerate(cast[:10]):
                name = actor.get("name", "") if isinstance(actor, dict) else str(actor)
                role = actor.get("role", "") if isinstance(actor, dict) else ""
                thumbnail = actor.get("thumbnail", "") if isinstance(actor, dict) else ""
                if name:
                    cast_list.append(xbmc.Actor(name, role, idx, thumbnail))
            if cast_list:
                info_tag.setCast(cast_list)
        _safe_set(_set_cast, "cast")


def _provider_art(default_icon, info):
    art = {"icon": default_icon}
    poster = (info or {}).get("poster_url") or ""
    fanart = (info or {}).get("fanart") or ""
    if poster:
        art.update({"icon": poster, "thumb": poster, "poster": poster})
    if fanart:
        art["fanart"] = fanart
    return art


def _provider_added_sort_key(item):
    return _safe_int_value((item or {}).get("added"))


def _set_tmdb_item_info(li, label, icon, art, tmdb_type, year="", plot="", season="", episode="", playcount=0, runtime="", cast=None, genre=None, director=None, writer=None, studio=None, mpaa="", tagline="", rating="", votes="", premiered="", background_fanart=""):
    media_type = "episode" if tmdb_type == "tv" and (season or episode) else ("tvshow" if tmdb_type == "tv" else "movie")
    li.setArt({
        "icon": icon,
        "thumb": icon,
        "poster": art.get("poster") or icon,
        "fanart": background_fanart or art.get("fanart", ""),
        "banner": art.get("banner", ""),
        "clearlogo": art.get("clearlogo", ""),
        "landscape": art.get("landscape", ""),
    })
    info = li.getVideoInfoTag()
    info.setMediaType(media_type)
    info.setTitle(label)
    header_parts = []
    if year:
        header_parts.append(str(year))
    genre_val = genre
    if isinstance(genre_val, list):
        genre_val = ", ".join(str(g) for g in genre_val)
    if genre_val:
        header_parts.append(str(genre_val))
    header = " | ".join(header_parts)
    enriched_plot = plot
    if cast and isinstance(cast, list):
        cast_names = ", ".join([
            (actor.get("name", "") if isinstance(actor, dict) else str(actor))
            for actor in cast[:5]
            if (actor.get("name", "") if isinstance(actor, dict) else str(actor))
        ])
        if cast_names:
            if header:
                enriched_plot = "{0}\n[COLOR gray]Cast: {1}[/COLOR]\n\n{2}".format(header, cast_names, plot)
            else:
                enriched_plot = "[COLOR gray]Cast: {0}[/COLOR]\n\n{1}".format(cast_names, plot)
        elif header:
            enriched_plot = "{0}\n\n{1}".format(header, plot)
    elif header:
        enriched_plot = "{0}\n\n{1}".format(header, plot)
    if enriched_plot:
        info.setPlot(enriched_plot)
    else:
        info.setPlot(label)
    if year:
        _safe_set(lambda: info.setYear(int(year)), "year")
    if season:
        _safe_set(lambda: info.setSeason(int(season)), "season")
    if episode:
        _safe_set(lambda: info.setEpisode(int(episode)), "episode")
    _safe_set(lambda: info.setPlaycount(int(playcount or 0)), "playcount")
    if runtime:
        _safe_set(lambda: info.setDuration(int(runtime)), "duration")
    if cast and isinstance(cast, list):
        def _set_cast():
            cast_list = []
            for idx, actor in enumerate(cast[:10]):
                name = actor.get("name", "") if isinstance(actor, dict) else str(actor)
                role = actor.get("role", "") if isinstance(actor, dict) else ""
                thumbnail = actor.get("thumbnail", "") if isinstance(actor, dict) else ""
                if name:
                    cast_list.append(xbmc.Actor(name, role, idx, thumbnail))
            if cast_list:
                info.setCast(cast_list)
        _safe_set(_set_cast, "cast")
    genres = _tmdb_list(genre)
    if genres:
        _safe_set(lambda: info.setGenres(genres), "genres")
    directors = _tmdb_list(director)
    if directors:
        _safe_set(lambda: info.setDirectors(directors), "directors")
    writers = _tmdb_list(writer)
    if writers:
        _safe_set(lambda: info.setWriters(writers), "writers")
    studios = _tmdb_list(studio)
    if studios:
        _safe_set(lambda: info.setStudios(studios), "studios")
    if mpaa:
        _safe_set(lambda: info.setMpaa(str(mpaa)), "mpaa")
    if tagline:
        _safe_set(lambda: info.setTagLine(str(tagline)), "tagline")
    if rating:
        _safe_set(lambda: info.setRating(float(rating), int(votes) if votes else 0), "rating")
    if premiered:
        _safe_set(lambda: info.setPremiered(str(premiered)), "premiered")


def _profile_setting_direct(profile_num, key, default=""):
    return _get_setting_direct(
        f"profile_{profile_num}_{key}",
        addon.getSetting(f"profile_{profile_num}_{key}") or default,
    )

def _profile_has_configured_credentials(profile_num):
    if (_profile_setting_direct(profile_num, "enabled", "false") or "").lower() != "true":
        return False
    m3u_url = (_profile_setting_direct(profile_num, "m3u") or "").strip()
    xtream_url = (_profile_setting_direct(profile_num, "xtream_url") or "").strip()
    xtream_user = (_profile_setting_direct(profile_num, "xtream_username") or "").strip()
    xtream_pwd = (_profile_setting_direct(profile_num, "xtream_password") or "").strip()
    return bool(m3u_url or (xtream_url and xtream_user and xtream_pwd))

def _any_profile_has_credentials():
    for n in range(1, 11):
        if _profile_has_configured_credentials(n):
            return True
    return False


def _get_credentials_for_profile(profile_num):
    """Get credentials for a specific profile number (1-10).

    Temporarily switches pm.active to get correct credentials,
    then restores original active profile.
    """
    original_active = pm.active
    try:
        pm.active = str(profile_num)
        return _get_credentials()
    finally:
        pm.active = original_active


def _call_with_active_profile(profile_num, fn, *args, **kwargs):
    """Run a callable with pm.active temporarily set to profile_num.

    Sports uses explicit profile credentials, but the shared raw cache helpers
    key their files by pm.active. This wrapper lets Sports use the same cache
    system without cache churn between profiles.
    """
    original_active = pm.active
    try:
        pm.active = str(profile_num)
        return fn(*args, **kwargs)
    finally:
        pm.active = original_active


def _prompt_profile_credentials(profile_num):
    """Show a dialog if profile is enabled but has no credentials.
    Returns True if credentials exist, False if user cancelled.
    """
    creds = _get_credentials_for_profile(profile_num)
    if creds.get("xtream_url") or creds.get("m3u_url"):
        return True
    profile_name = (
        creds.get("name")
        or addon.getSetting(f"profile_{profile_num}_name")
        or _t(30390, profile_num)
    )
    choice = xbmcgui.Dialog().yesno(
        profile_name,
        _t(31145),
        yeslabel="Settings",
        nolabel="Cancel",
    )
    if choice:
        xbmc.executebuiltin("RunPlugin(plugin://plugin.video.xstream-pro/?mode=settings)")
    return False


def _get_pvr_credentials():
    """Get credentials for the PVR profile (active_pvr_profile setting)."""
    pvr_profile = addon.getSetting("active_pvr_profile") or "Profile 1"
    match = re.search(r"(\d+)$", pvr_profile)
    pnum = match.group(1) if match else "1"

    # Temporarily set pm.active to get credentials for PVR profile
    original = pm.active
    try:
        pm.active = pnum
        return _get_credentials()
    finally:
        pm.active = original


def _select_profile_or_all(allow_all=True):
    """Show a dialog to select an enabled profile. Returns profile number string,
    'all' if allow_all is True and user picks All Profiles, or None on cancel."""
    profiles = []
    for i in range(1, 11):
        if addon.getSetting(f"profile_{i}_enabled") == "true":
            name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
            label = _t(31400, i, name) if name != _t(30390, i) else _t(30390, i)
            profiles.append((str(i), label))
    if not profiles:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30056))
        return None
    labels = [p[1] for p in profiles]
    if allow_all:
        labels.insert(0, _t(30018))  # All Profiles
    idx = xbmcgui.Dialog().select(_t(30017), labels)
    if idx < 0:
        return None
    if allow_all:
        if idx == 0:
            return "all"
        return profiles[idx - 1][0]
    return profiles[idx][0]


def _prefetch_vod_info_batch(streams, base_url, user, pwd):
    """Fetch vod_info for a batch of movies in parallel threads."""
    profile_snapshot = pm.active

    def _fetch_one(s):
        original_active = pm.active
        try:
            pm.active = profile_snapshot
            sid = str(s.get("stream_id", ""))
            if not sid:
                return
            cname = f"vod_info_{sid}"
            cached = _cache_load(cname)
            if cached:
                return
            try:
                info = IPTV.get_vod_info(base_url, user, pwd, sid)
                if info:
                    _cache_save(cname, info)
            except Exception as e:
                _log(f"VOD info prefetch error for {sid}: {e}")
        finally:
            pm.active = original_active

    # Throttled prefetch: max 4 concurrent threads with 200ms gap between batches
    # to avoid overwhelming the Xtream provider.
    batch_size = 4
    delay_ms = 200
    all_threads = []
    for i in range(0, len(streams), batch_size):
        batch = streams[i:i + batch_size]
        threads = []
        for s in batch:
            t = threading.Thread(target=_fetch_one, args=(s,))
            t.daemon = True
            threads.append(t)
            t.start()
        all_threads.extend(threads)
        if i + batch_size < len(streams):
            xbmc.sleep(delay_ms)
    # Single 15s deadline for the whole batch
    deadline = time.monotonic() + 15
    for t in all_threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        t.join(timeout=remaining)


def _enrich_movie_info(s, base_url=None, user=None, pwd=None):
    # Provider metadata toggles for movies
    use_prov = addon.getSetting("provider_movie_enabled").lower() == "true"
    use_prov_plot = use_prov and (addon.getSetting("provider_movie_plot").lower() == "true")
    use_prov_posters = use_prov and (addon.getSetting("provider_movie_posters").lower() == "true")
    use_prov_ratings = use_prov and (addon.getSetting("provider_movie_ratings").lower() == "true")
    use_prov_cast = use_prov and (addon.getSetting("provider_movie_cast").lower() == "true")
    use_prov_genre = use_prov and (addon.getSetting("provider_movie_genre").lower() == "true")
    use_prov_duration = use_prov and (addon.getSetting("provider_movie_duration").lower() == "true")

    result = {
        "plot": "",
        "poster_url": "",
        "rating": "",
        "year": "",
        "cast": [],
        "genre": "",
        "duration": 0,
        "tmdb_id": "",
        "imdb_id": "",
    }

    # Apply provider data from stream list item based on toggles
    if use_prov_plot:
        result["plot"] = (
            s.get("plot") or s.get("description") or s.get("info", {}).get("plot") or ""
        )
    if use_prov_posters:
        result["poster_url"] = s.get("stream_icon") or ""
    if use_prov_ratings:
        result["rating"] = str(s.get("rating", "") or s.get("rating_5based", "") or "")

    # Provider vod_info enrichment (only if provider metadata is enabled)
    if use_prov and s.get("stream_id"):
        sid = str(s.get("stream_id"))
        cname = f"vod_info_{sid}"
        info = _cache_load(cname)
        if not info and base_url and user and pwd:
            # On-demand fallback: prefetch missed this movie or cache is empty, fetch it now
            try:
                info = IPTV.get_vod_info(base_url, user, pwd, sid)
                if info:
                    _cache_save(cname, info)
                else:
                    info = {}
            except Exception as e:
                _log(f"VOD info on-demand fetch error for {sid}: {e}")
                info = {}
        if info:
            if use_prov_plot:
                result["plot"] = (
                    info.get("info", {}).get("plot") or info.get("plot") or result["plot"]
                )
            if use_prov_posters:
                result["poster_url"] = (
                    info.get("info", {}).get("movie_image")
                    or info.get("stream_icon")
                    or result["poster_url"]
                )
            if use_prov_ratings:
                result["year"] = str(
                    info.get("info", {}).get("releasedate", "")
                    or info.get("info", {}).get("release_date", "")
                    or ""
                )[:4]
            if use_prov_duration:
                result["duration"] = int(info.get("info", {}).get("duration_secs", 0) or 0)
            if use_prov_cast and info.get("info", {}).get("cast"):
                cast_list = []
                for idx, actor_name in enumerate(info["info"]["cast"].split(",")[:10]):
                    name = actor_name.strip()
                    if name:
                        cast_list.append({"name": name, "role": "", "thumbnail": ""})
                result["cast"] = cast_list
            if use_prov_genre and info.get("info", {}).get("genre"):
                result["genre"] = info["info"]["genre"]
            tmdb_from_info = info.get("info", {}).get("tmdb_id") or info.get("info", {}).get("tmdb") or ""
            imdb_from_info = info.get("info", {}).get("imdb_id") or info.get("info", {}).get("imdb") or ""
            if tmdb_from_info:
                result["tmdb_id"] = str(tmdb_from_info)
            if imdb_from_info:
                result["imdb_id"] = str(imdb_from_info)

    # Playback-discovered duration fallback
    if use_prov_duration and not result["duration"] and s.get("stream_id"):
        pb_dur = _load_playback_duration(str(s.get("stream_id")))
        if pb_dur:
            result["duration"] = pb_dur

    return result

def _enrich_series_info(s, base_url=None, user=None, pwd=None):
    # Provider metadata toggles for series
    use_prov = addon.getSetting("provider_series_enabled").lower() == "true"
    use_prov_plot = use_prov and (addon.getSetting("provider_series_plot").lower() == "true")
    use_prov_posters = use_prov and (addon.getSetting("provider_series_posters").lower() == "true")
    use_prov_ratings = use_prov and (addon.getSetting("provider_series_ratings").lower() == "true")
    use_prov_cast = use_prov and (addon.getSetting("provider_series_cast").lower() == "true")
    use_prov_genre = use_prov and (addon.getSetting("provider_series_genre").lower() == "true")
    use_prov_duration = use_prov and (addon.getSetting("provider_series_duration").lower() == "true")

    result = {
        "plot": "",
        "poster_url": "",
        "rating": "",
        "year": "",
        "cast": [],
        "genre": "",
        "duration": 0,
    }

    # Apply provider data from stream list item based on toggles
    if use_prov_plot:
        result["plot"] = s.get("plot", "")
    if use_prov_posters:
        result["poster_url"] = s.get("cover", "")
    if use_prov_ratings:
        result["rating"] = str(s.get("rating", "") or s.get("rating_5based", "") or "")
    if use_prov_genre and s.get("genre"):
        result["genre"] = s.get("genre")
    elif use_prov_genre and not s.get("genre"):
        series_id = s.get("series_id", "")
        if series_id and base_url and user and pwd:
            try:
                cname = f"series_info_{series_id}"
                info = _cache_load(cname)
                if not info:
                    info = IPTV.get_xtream_series_info(base_url, user, pwd, series_id)
                    if info:
                        _cache_save(cname, info)
                if info and isinstance(info, dict):
                    genre_str = info.get("info", {}).get("genre", "")
                    if genre_str:
                        result["genre"] = genre_str
            except Exception:
                pass
    if use_prov_cast and s.get("cast"):
        cast_list = []
        for idx, actor_name in enumerate(s.get("cast").split(",")[:10]):
            name = actor_name.strip()
            if name:
                cast_list.append({"name": name, "role": "", "thumbnail": ""})
        result["cast"] = cast_list
    if use_prov_duration and s.get("episode_run_time"):
        try:
            ep_run_time = int(s.get("episode_run_time"))
            result["duration"] = ep_run_time * 60
        except (ValueError, TypeError):
            pass

    return result


def _cache_path(name):
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    # Sanitize name to prevent path traversal - only allow alphanumeric, hyphen, underscore
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", str(name))
    return os.path.join(profile, f"data_cache_p{pm.active}_{safe_name}.json")


def _playback_duration_path(stream_id):
    return _live_playback._playback_duration_path(stream_id)



def _save_playback_duration(stream_id, duration):
    return _live_playback._save_playback_duration(stream_id, duration)



def _load_playback_duration(stream_id):
    return _live_playback._load_playback_duration(stream_id)



def _cache_load(name):
    try:
        with open(_cache_path(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_save(name, data):
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    cache_file = _cache_path(name)
    tmp_file = cache_file + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
        # fsync avoids zero-byte cache on crash (Android/TV devices)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp_file, cache_file)


SOURCE_RESULT_CACHE_VERSION = 1
SOURCE_RESULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
SOURCE_SIZE_CACHE_VERSION = 1
SOURCE_SIZE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


def _source_cache_dir():
    return _live_sources._source_cache_dir()



def _source_cache_key(payload):
    return _live_sources._source_cache_key(payload)



def _source_cache_path(prefix, key):
    return _live_sources._source_cache_path(prefix, key)



def _source_cache_load(prefix, key, ttl_seconds):
    return _live_sources._source_cache_load(prefix, key, ttl_seconds)



def _source_cache_save(prefix, key, data):
    return _live_sources._source_cache_save(prefix, key, data)



def _source_profile_data_signature(profile_nums):
    return _live_sources._source_profile_data_signature(profile_nums)



def _source_result_cache_key(title, year, tmdb_type, season, episode, tmdb_id, profile_nums):
    return _live_sources._source_result_cache_key(title, year, tmdb_type, season, episode, tmdb_id, profile_nums)



def _source_size_cache_key(url):
    return _live_sources._source_size_cache_key(url)



def _load_source_size_cache(url):
    return _live_sources._load_source_size_cache(url)



def _save_source_size_cache(url, size_bytes):
    return _live_sources._save_source_size_cache(url, size_bytes)



def _cache_valid(name, hours=None):
    if hours is not None:
        pass
    elif name.startswith("vod_info_"):
        hours = 30 * 24  # 30 days for static metadata
    else:
        try:
            hours = float(addon.getSetting("auto_refresh_interval") or "24")
        except ValueError:
            hours = 24
    path = _cache_path(name)
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < (hours * 3600)


def _cache_clear_all():
    """Clear cache for all profiles."""
    count = 0
    for pnum in range(1, 11):
        count += _cache_clear_profile(pnum)
    return count


def _cache_clear_profile(pnum):
    """Clear cache for a specific profile number (navigation + EPG only)."""
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    prefix = f"data_cache_p{pnum}_"
    count = 0
    try:
        for fname in os.listdir(profile):
            if fname.startswith(prefix):
                # Boundary check: p1 must not match p10, p11, etc.
                rest = fname[len(prefix) :]
                if rest and rest[0].isdigit():
                    continue
                os.remove(os.path.join(profile, fname))
                count += 1
            elif fname == f"epg_cache_profile_{pnum}.json":
                os.remove(os.path.join(profile, fname))
                count += 1
    except Exception as e:
        _log(f"Cache clear error: {e}")
    return count


def _purge_profile_data(pnum):
    """Clear ALL profile data except PVR and favorites (for profile unload/refresh)."""
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    count = _cache_clear_profile(pnum)
    try:
        for fname in os.listdir(profile):
            if fname in (
                f"watch_history_p{pnum}.json",
                f"resume_points_p{pnum}.json",
                f"watched_movies_p{pnum}.json",
                f"watched_episodes_p{pnum}.json",
                f"search_history_p{pnum}.json",
                f"main_menu_order_p{pnum}.json",
            ):
                os.remove(os.path.join(profile, fname))
                count += 1
            elif fname.startswith("hidden_subcats_") and fname.endswith(f"_p{pnum}.json"):
                os.remove(os.path.join(profile, fname))
                count += 1
            elif fname.startswith("hidden_items_") and fname.endswith(f"_p{pnum}.json"):
                os.remove(os.path.join(profile, fname))
                count += 1
    except Exception as e:
        _log(f"Purge profile error: {e}")
    return count


def _cache_clear_all_profiles():
    """Clear cache for all profiles."""
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    count = 0
    try:
        for fname in os.listdir(profile):
            if (
                fname.startswith("data_cache_")
                or fname.startswith("epg_cache_profile_")
                or fname.startswith("vod_info_")

                or fname.startswith("playback_duration_")
            ):
                os.remove(os.path.join(profile, fname))
                count += 1
    except Exception as e:
        _log(f"Cache clear error: {e}")
    return count


def _get_cached_m3u_channels(m3u_url, force=False):
    if not m3u_url:
        return []
    if not force:
        cached = _cache_load("m3u")
        if isinstance(cached, dict) and cached.get("_url") == m3u_url and _cache_valid("m3u"):
            return cached.get("_data") or []
    data = IPTV.get_m3u_channels(m3u_url)
    _log(f"M3U channels: fetched {len(data)} channels{', forced' if force else ''}")
    _cache_save("m3u", {"_url": m3u_url, "_data": data})
    return data


def _get_cached_xtream_categories(url, user, pwd, stype, force=False):
    if not url or not user or not pwd:
        return []
    key = f"xtream_cats_{stype}"
    source = f"{url}|{user}|{pwd}"
    if not force:
        cached = _cache_load(key)
        if isinstance(cached, dict) and cached.get("_src") == source and _cache_valid(key):
            cached_data = cached.get("_data") or []
            if not isinstance(cached_data, list):
                _log("Xtream categories ({0}): cached data is not a list, re-fetching".format(stype))
            else:
                return cached_data
    else:
        cached = _cache_load(key)
    try:
        data = IPTV.get_xtream_categories(url, user, pwd, stype)
    except ProviderFetchError as e:
        if isinstance(cached, dict) and cached.get("_src") == source:
            stale = cached.get("_data") or []
            if isinstance(stale, list):
                _log(f"Xtream categories ({stype}) fetch failed; using stale cache: {e}")
                return stale
        raise
    _cache_save(key, {"_src": source, "_data": data})
    return data


def _get_cached_xtream_streams(url, user, pwd, stype, category_id=None, force=False):
    if not url or not user or not pwd:
        return []
    key = f"xtream_streams_{stype}"
    source = f"{url}|{user}|{pwd}"
    cache_hit = False
    if not force:
        cached = _cache_load(key)
        if isinstance(cached, dict) and cached.get("_src") == source and _cache_valid(key):
            data = cached.get("_data") or []
            if not isinstance(data, list):
                _log("Xtream streams ({0}): cached data is not a list, re-fetching".format(stype))
            else:
                cache_hit = True
    else:
        cached = _cache_load(key)
    if not cache_hit:
        try:
            data = IPTV.get_xtream_streams(url, user, pwd, stype, None)
        except ProviderFetchError as e:
            if isinstance(cached, dict) and cached.get("_src") == source:
                stale = cached.get("_data") or []
                if isinstance(stale, list):
                    _log(f"Xtream streams ({stype}) fetch failed; using stale cache: {e}")
                    data = stale
                else:
                    raise
            else:
                raise
        else:
            _cache_save(key, {"_src": source, "_data": data})
            counts = {}
            for s in data:
                cid = str(s.get("category_id", ""))
                counts[cid] = counts.get(cid, 0) + 1
            _cache_save(f"xtream_counts_{stype}", counts)
    if category_id:
        return [s for s in data if str(s.get("category_id", "")) == str(category_id)]
    return data


def _enabled_profiles_with_credentials():
    profiles = []
    for n in range(1, 11):
        if not _profile_has_configured_credentials(n):
            continue
        name = _profile_setting_direct(n, "name") or _t(30390, n)
        profiles.append((n, name))
    return profiles


def _provider_only_tmdb_enabled():
    return _provider_availability._provider_only_tmdb_enabled()



def _provider_availability_path():
    return _provider_availability._provider_availability_path()



def _provider_title_key(value):
    return _provider_availability._provider_title_key(value)



def _provider_year(*values):
    return _provider_availability._provider_year(*values)



def _provider_availability_add(index, media_type, name, item=None):
    return _provider_availability._provider_availability_add(index, media_type, name, item)



_PROVIDER_AVAILABILITY_MEM = {
    "path": "",
    "mtime": None,
    "data": None,
    "sets": {},
}


def _load_provider_availability_cache():
    return _provider_availability._load_provider_availability_cache()



def _save_provider_availability_cache(index):
    return _provider_availability._save_provider_availability_cache(index)



def _clear_provider_availability_cache():
    return _provider_availability._clear_provider_availability_cache()



def _provider_tmdb_id_set(cache, tmdb_type):
    return _provider_availability._provider_tmdb_id_set(cache, tmdb_type)



def _provider_availability_item_available(item, cache, strict_title_year=False):
    return _provider_availability._provider_availability_item_available(item, cache, strict_title_year)



def _filter_provider_available_items(items):
    return _provider_availability._filter_provider_available_items(items)



def _filter_provider_available_items_strict(items):
    return _provider_availability._filter_provider_available_items_strict(items)



def _find_provider_series_id_for_show(tmdb_id, title):
    return _provider_availability._find_provider_series_id_for_show(tmdb_id, title)



def _xtream_series_seasons_available(url, user, pwd, series_id):
    return _provider_availability._xtream_series_seasons_available(url, user, pwd, series_id)



def _xtream_episodes_available(url, user, pwd, series_id, season_num):
    return _provider_availability._xtream_episodes_available(url, user, pwd, series_id, season_num)



def _filter_provider_seasons(tmdb_id, showtitle, seasons):
    return _provider_availability._filter_provider_seasons(tmdb_id, showtitle, seasons)



def _filter_provider_episodes(tmdb_id, showtitle, season, episodes):
    return _provider_availability._filter_provider_episodes(tmdb_id, showtitle, season, episodes)



def _pvr_m3u_path_for_profile(profile_num):
    return _pvr_paths._pvr_m3u_path_for_profile(profile_num)


def _pvr_m3u_path():
    return _pvr_paths._pvr_m3u_path()


def _pvr_epg_path():
    return _pvr_paths._pvr_epg_path()


def _validate_pvr_epg_m3u_match(m3u_path, epg_path, log_prefix="PVR", notify=True):
    """Warn if M3U tvg-ids and XMLTV programme rows have no overlap.

    Kodi guide data depends on <programme channel="..."> rows. Matching only
    <channel id="..."> declarations can pass while the visible guide is empty.

    Returns True if at least one M3U tvg-id has a matching <programme> row.
    Logs diagnostic summary of matched/unmatched channels.
    """
    try:
        m3u_ids = set()
        with open(m3u_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#EXTINF"):
                    match = re.search(r"\btvg-id=([\"'])(.*?)\1", line)
                    if match and match.group(2):
                        m3u_ids.add(match.group(2))
        if not m3u_ids or not os.path.exists(epg_path):
            return False

        epg_channel_ids = set()
        matched_programme_ids = set()
        carry = ""
        with open(epg_path, "r", encoding="utf-8", errors="ignore") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                scan = carry + chunk
                carry = scan[-512:]
                for match in re.finditer(r"<channel\b[^>]*\bid=([\"'])(.*?)\1", scan):
                    epg_channel_ids.add(html.unescape(match.group(2)))
                for match in re.finditer(r"<programme\b[^>]*\bchannel=([\"'])(.*?)\1", scan):
                    cid = html.unescape(match.group(2))
                    if cid in m3u_ids:
                        matched_programme_ids.add(cid)

        m3u_only = m3u_ids - matched_programme_ids
        epg_only = epg_channel_ids - m3u_ids
        channel_overlap = m3u_ids & epg_channel_ids
        has_match = bool(matched_programme_ids)

        _log(
            "{0}: M3U={1} tvg-ids, EPG={2} channels, {3} programme matches, "
            "{4} M3U-only, {5} EPG-only".format(
                log_prefix,
                len(m3u_ids),
                len(epg_channel_ids),
                len(matched_programme_ids),
                len(m3u_only),
                len(epg_only),
            )
        )
        if m3u_only:
            sample = sorted(m3u_only)[:10]
            _log("{0}: M3U-only (no EPG programmes): {1}".format(log_prefix, sample))
        if epg_only:
            sample = sorted(epg_only)[:10]
            _log("{0}: EPG-only (no M3U tvg-id): {1}".format(log_prefix, sample))
        if m3u_only or epg_only:
            _log("{0}: Some unmatched channels are expected when the provider has no EPG data for those channels".format(log_prefix))

        if not has_match:
            if channel_overlap:
                warning = (
                    "{0} WARNING: {1} M3U tvg-ids match XMLTV "
                    "channel declarations, but zero programme rows match. EPG guide may be empty."
                ).format(log_prefix, len(channel_overlap))
            elif epg_channel_ids:
                warning = (
                    "{0} WARNING: M3U tvg-ids and XMLTV channel declarations have "
                    "zero overlap. EPG guide may be empty."
                ).format(log_prefix)
            else:
                warning = "{0} WARNING: XMLTV has no channel or programme rows. EPG guide may be empty.".format(log_prefix)
            _log(warning)
            if notify:
                try:
                    xbmcgui.Dialog().notification("Xstream Pro", _t(30892), xbmcgui.NOTIFICATION_WARNING, 5000)
                except Exception:
                    pass
        return has_match
    except Exception as e:
        _log(f"{log_prefix} EPG/M3U validation warning: {e}")
        return False


def _m3u_extinf_attr(line, attr):
    try:
        match = re.search(r'\b{0}="([^"]*)"'.format(re.escape(attr)), line)
        return match.group(1).strip() if match else ""
    except Exception:
        return ""


def _normalize_epg_fallback_name(name):
    return _pvr_export._normalize_epg_fallback_name(name)


def _epg_fallback_unique(values):
    return _pvr_export._epg_fallback_unique(values)


def _epg_fallback_group_key(group):
    return _pvr_export._epg_fallback_group_key(group)


def _epg_fallback_strict_share_key(name):
    return _pvr_export._epg_fallback_strict_share_key(name)


def _epg_target_id_from_channel(ch):
    return str(
        ch.get("epg_channel_id")
        or ch.get("tvg_id")
        or ch.get("stream_id")
        or ""
    ).strip()


def _epg_group_from_channel(ch, fallback_group=""):
    return str(
        ch.get("group")
        or ch.get("provider_group")
        or ch.get("category_name")
        or fallback_group
        or ""
    ).strip()


def _epg_exact_program_id(epg, channel_id, channel_name=""):
    channel_id = str(channel_id or "").strip()
    if channel_id and (getattr(epg, "programs", {}) or {}).get(channel_id):
        return channel_id

    name_lower = str(channel_name or "").strip().casefold()
    if not name_lower:
        return ""

    for cid, display_name in (getattr(epg, "channel_names", {}) or {}).items():
        if str(display_name or "").strip().casefold() == name_lower:
            if (getattr(epg, "programs", {}) or {}).get(cid):
                return cid
    return ""


def _build_same_group_epg_aliases(channels, epg, fallback_group=""):
    if not channels or epg is None:
        return {}

    buckets = {}
    targets = []

    for ch in channels:
        target_id = _epg_target_id_from_channel(ch)
        if not target_id:
            continue

        name = str(ch.get("name") or target_id).strip()
        group_key = _epg_fallback_group_key(_epg_group_from_channel(ch, fallback_group))
        strict_key = _epg_fallback_strict_share_key(name)
        if not group_key or not strict_key:
            continue

        real_program_id = _epg_exact_program_id(epg, target_id, name)
        bucket_key = (group_key, strict_key)
        if real_program_id:
            buckets.setdefault(bucket_key, set()).add(real_program_id)
        else:
            targets.append((target_id, bucket_key))

    aliases = {}
    for target_id, bucket_key in targets:
        source_ids = buckets.get(bucket_key) or set()
        if len(source_ids) != 1:
            continue
        source_id = next(iter(source_ids))
        if source_id and source_id != target_id:
            aliases[target_id] = source_id

    if aliases:
        _log("EPG same-group aliases prepared: {0}".format(len(aliases)))
    return aliases


def _epg_fallback_match_keys(name, group=""):
    return _pvr_export._epg_fallback_match_keys(name, group)


def _parse_pvr_m3u_epg_targets(m3u_path):
    return _pvr_export._parse_pvr_m3u_epg_targets(m3u_path)


def _profile_has_epg_fallback_source(profile_num):
    pnum = str(profile_num)
    if addon.getSetting(f"profile_{pnum}_enabled") != "true":
        return False
    if addon.getSetting(f"profile_{pnum}_xtream_url"):
        return True
    if addon.getSetting(f"profile_{pnum}_m3u"):
        return True
    return False


def _build_epg_fallback_name_index(epg):
    return _pvr_export._build_epg_fallback_name_index(epg)


def _epg_fallback_source_targets_for_profile(profile_num):
    targets = _parse_pvr_m3u_epg_targets(_pvr_m3u_path_for_profile(profile_num))
    if targets:
        return targets

    pnum = str(profile_num)
    try:
        creds = _get_credentials_for_profile(pnum)
        xt_url = creds.get("xtream_url", "")
        xt_user = creds.get("xtream_username", "")
        xt_pwd = creds.get("xtream_password", "")
        if xt_url and xt_user and xt_pwd:
            cats = _get_cached_xtream_categories(xt_url, xt_user, xt_pwd, "live")
            cat_map = {
                str(c.get("category_id", "")): c.get("category_name", "Live TV")
                for c in cats or []
            }
            streams = _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "live", None)
            return [
                {
                    "tvg_id": str(s.get("epg_channel_id") or s.get("stream_id") or ""),
                    "source_tvg_id": str(s.get("epg_channel_id") or s.get("stream_id") or ""),
                    "name": s.get("name", ""),
                    "display_name": s.get("name", ""),
                    "group": cat_map.get(str(s.get("category_id", "")), "Live TV"),
                }
                for s in streams or []
                if str(s.get("epg_channel_id") or s.get("stream_id") or "").strip()
            ]

        m3u_url = creds.get("m3u_url", "")
        if m3u_url:
            channels = _get_cached_m3u_channels(m3u_url)
            return [
                {
                    "tvg_id": str(ch.get("tvg_id") or ch.get("url") or ch.get("name") or ""),
                    "source_tvg_id": str(ch.get("tvg_id") or ch.get("url") or ch.get("name") or ""),
                    "name": ch.get("name", ""),
                    "display_name": ch.get("name", ""),
                    "group": ch.get("group", "General"),
                }
                for ch in channels or []
                if str(ch.get("tvg_id") or ch.get("url") or ch.get("name") or "").strip()
            ]
    except Exception as exc:
        _log("PVR EPG fallback: source target load warning for profile {0}: {1}".format(profile_num, exc))
    return []


def _build_epg_fallback_group_strict_index(profile_num, epg):
    return _pvr_export._build_epg_fallback_group_strict_index(profile_num, epg)


def _load_epg_for_fallback_profile(profile_num, log_prefix):
    fallback_epg = EPG(addon, profile_num=str(profile_num))
    cache_file = getattr(fallback_epg, "cache_file", "")
    if cache_file and os.path.exists(cache_file):
        fallback_epg.load()
    else:
        _log(f"{log_prefix}: fallback profile {profile_num} cache missing, fetching complete provider EPG")
        fallback_epg.fetch()

    if not getattr(fallback_epg, "programs", None):
        _log(f"{log_prefix}: fallback profile {profile_num} EPG empty after load/fetch")

    return fallback_epg


def _pvr_epg_fallback_stamp_path(profile_num, scope="live"):
    return _pvr_export._pvr_epg_fallback_stamp_path(profile_num, scope)


def _file_signature(path):
    try:
        if path and os.path.exists(path):
            stat = os.stat(path)
            return "{0}:{1}".format(int(stat.st_mtime), int(stat.st_size))
    except Exception:
        pass
    return "missing"


def _pvr_epg_refresh_seconds():
    return _pvr_paths._pvr_epg_refresh_seconds()


_PVR_STARTUP_RETRY_THREAD = None
_PVR_STARTUP_RETRY_THREAD_LOCK = threading.Lock()
# Module-level state: reuselanguageinvoker=true keeps this module loaded; lock prevents duplicate repair threads.
_SPORTS_EPG_REPAIR_THREAD = None
_SPORTS_EPG_REPAIR_THREAD_LOCK = threading.Lock()
_LIVE_EPG_REPAIR_THREAD = None
_LIVE_EPG_REPAIR_THREAD_LOCK = threading.Lock()


def _live_pvr_epg_health(profile_num):
    return _pvr_health._live_pvr_epg_health(profile_num)


def _pvr_health_report():
    return _pvr_health._pvr_health_report()


def _schedule_sports_epg_repair(profile_num):
    """Schedule sports EPG export in background. Never blocks PVR open.

    Throttled: will not start a new repair if one is already running or if
    a recent attempt failed within the last 20 minutes.
    """
    global _SPORTS_EPG_REPAIR_THREAD
    with _SPORTS_EPG_REPAIR_THREAD_LOCK:
        if _SPORTS_EPG_REPAIR_THREAD is not None and _SPORTS_EPG_REPAIR_THREAD.is_alive():
            _log("Sports EPG repair: already in progress")
            return False
        attempt_stamp = os.path.join(
            xbmcvfs.translatePath(addon.getAddonInfo("profile")),
            ".sports_epg_repair_attempt"
        )
        if os.path.exists(attempt_stamp):
            try:
                if time.time() - os.path.getmtime(attempt_stamp) < 20 * 60:
                    _log("Sports EPG repair: recent attempt throttled, skipping")
                    return False
            except OSError:
                pass

        def _worker():
            try:
                with open(attempt_stamp, "w") as sf:
                    sf.write("1")
                channels = _sports_pvr_source_channels()
                if channels:
                    channels = _apply_pvr_catchup_corrections(channels, str(profile_num), "Sports EPG repair")
                    channels = _prepare_sports_pvr_channels_for_export(channels, str(profile_num))
                    lock_path = _pvr_sync_lock_path()
                    if os.path.exists(lock_path):
                        try:
                            if time.time() - os.path.getmtime(lock_path) < 120:
                                _log("Sports EPG repair: PVR sync in progress, skipping")
                                return
                        except OSError:
                            pass
                    ok = _export_sports_pvr_epg_for_profile(str(profile_num), channels, force_fetch=True)
                    _log(f"Sports EPG repair: {'completed' if ok else 'failed'}")
                    if ok:
                        try:
                            if os.path.exists(attempt_stamp):
                                os.remove(attempt_stamp)
                        except OSError:
                            pass
                        scope = _current_pvr_instance_scope()
                        if scope in ("sports", "mixed"):
                            xbmc.executebuiltin('Notification("Xstream Pro","Sports EPG updated. Restart Kodi to see changes.",8000,"DefaultTV.png")')
                else:
                    _log("Sports EPG repair: no sports channels available")
            except Exception as exc:
                _log(f"Sports EPG repair warning: {exc}")
                _log(f"Traceback: {traceback.format_exc()}")

        _SPORTS_EPG_REPAIR_THREAD = threading.Thread(
            target=_worker, name="XstreamProSportsEpgRepair", daemon=True
        )
        _SPORTS_EPG_REPAIR_THREAD.start()
        _log("Sports EPG repair: scheduled in background")
        return True


def _schedule_live_epg_repair(profile_num):
    """Schedule Live TV EPG re-export in background. Never blocks PVR open.

    Throttled: will not start a new repair if one is already running or if
    a recent attempt failed within the last 20 minutes.
    """
    global _LIVE_EPG_REPAIR_THREAD
    with _LIVE_EPG_REPAIR_THREAD_LOCK:
        if _LIVE_EPG_REPAIR_THREAD is not None and _LIVE_EPG_REPAIR_THREAD.is_alive():
            _log("Live EPG repair: already in progress")
            return False
        attempt_stamp = os.path.join(
            xbmcvfs.translatePath(addon.getAddonInfo("profile")),
            ".live_epg_repair_attempt"
        )
        if os.path.exists(attempt_stamp):
            try:
                if time.time() - os.path.getmtime(attempt_stamp) < 20 * 60:
                    _log("Live EPG repair: recent attempt throttled, skipping")
                    return False
            except OSError:
                pass

        def _worker():
            try:
                with open(attempt_stamp, "w") as sf:
                    sf.write("1")
                lock_path = _pvr_sync_lock_path()
                if os.path.exists(lock_path):
                    try:
                        if time.time() - os.path.getmtime(lock_path) < 120:
                            _log("Live EPG repair: PVR sync in progress, skipping")
                            return
                    except OSError:
                        pass
                _pvr_export.clear_epg_instance_cache()
                ok = _pvr_export.export_pvr_epg_for_profile(str(profile_num), force_fetch=True)
                _log(f"Live EPG repair: {'completed' if ok else 'failed'}")
                if ok:
                    try:
                        if os.path.exists(attempt_stamp):
                            os.remove(attempt_stamp)
                    except OSError:
                        pass
                    scope = _current_pvr_instance_scope()
                    if scope in ("main", "mixed"):
                        xbmc.executebuiltin('Notification("Xstream Pro","EPG updated. Restart Kodi to see changes.",8000,"DefaultTV.png")')
            except Exception as exc:
                _log(f"Live EPG repair warning: {exc}")
                _log(f"Traceback: {traceback.format_exc()}")

        _LIVE_EPG_REPAIR_THREAD = threading.Thread(
            target=_worker, name="XstreamProLiveEpgRepair", daemon=True
        )
        _LIVE_EPG_REPAIR_THREAD.start()
        _log("Live EPG repair: scheduled in background")
        return True


def _profile_source_signature(profile_num):
    pnum = str(profile_num)
    keys = [
        f"profile_{pnum}_enabled",
        f"profile_{pnum}_source_type",
        f"profile_{pnum}_m3u",
        f"profile_{pnum}_xtream_url",
        f"profile_{pnum}_xtream_username",
        f"profile_{pnum}_xtream_password",
        f"profile_{pnum}_epg_m3u",
        f"profile_{pnum}_epg_xtream",
    ]
    values = [addon.getSetting(key) or "" for key in keys]
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8", "ignore")).hexdigest()[:20]


def _epg_fallback_profile_state_signature(profile_num):
    pnum = str(profile_num)
    profile_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    epg_cache = os.path.join(profile_dir, f"epg_cache_profile_{pnum}.json")
    sports_m3u = os.path.join(profile_dir, f"pvr_sports_{PVR_FILE_SLUG}_p{pnum}.m3u8")
    return "p{0}:src={1}:epg={2}:pvr={3}:sports={4}".format(
        pnum,
        _profile_source_signature(pnum),
        _file_signature(epg_cache),
        _file_signature(_pvr_m3u_path_for_profile(pnum)),
        _file_signature(sports_m3u),
    )


def _pvr_epg_fallback_signature(profile_num, scope="live"):
    return _pvr_export._pvr_epg_fallback_signature(profile_num, scope)


def _pvr_epg_fallback_needs_rebuild(profile_num, scope="live"):
    return _pvr_export._pvr_epg_fallback_needs_rebuild(profile_num, scope)


def _pvr_epg_fallback_mark_built(profile_num, scope="live"):
    _pvr_export._pvr_epg_fallback_mark_built(profile_num, scope)


def _apply_epg_fallback_from_other_profiles(
    epg,
    profile_num,
    targets,
    target_id_key="tvg_id",
    target_name_key="name",
    log_prefix="PVR EPG",
):
    return _pvr_export._apply_epg_fallback_from_other_profiles(epg, profile_num, targets, target_id_key=target_id_key, target_name_key=target_name_key, log_prefix=log_prefix)



def _export_pvr_m3u():
    return _pvr_export.export_pvr_m3u()




def _export_pvr_epg_for_profile(profile_num, force_fetch=False):
    return _pvr_export.export_pvr_epg_for_profile(profile_num, force_fetch=force_fetch)

def _export_pvr_epg(force_fetch=False):
    return _pvr_export.export_pvr_epg(force_fetch=force_fetch)


def _trigger_pvr_epg_reload():
    """No-op: PVR.Scan does not work for IPTV Simple.

    After EPG files are written atomically, IPTV Simple will pick up changes
    on its configured refresh interval. Restart Kodi for immediate effect.
    """
    _log("PVR EPG: reload skipped; IPTV Simple will reload on next refresh interval. Restart Kodi for immediate effect.")

def _configure_pvr_iptvsimple():
    return _pvr_instances._configure_pvr_iptvsimple()


def is_pvr_iptvsimple_installed():
    return _pvr_sync.is_pvr_iptvsimple_installed()



def _is_pvr_iptvsimple_installed_or_disabled():
    return _pvr_sync._is_pvr_iptvsimple_installed_or_disabled()



def prompt_install_pvr():
    return _pvr_sync.prompt_install_pvr()



def _pvr_sync_lock_path():
    return _pvr_sync._pvr_sync_lock_path()



def _acquire_pvr_sync_lock():
    return _pvr_sync._acquire_pvr_sync_lock()



def _release_pvr_sync_lock():
    return _pvr_sync._release_pvr_sync_lock()



def _truthy_catchup(value):
    return str(value or "").strip().lower() in ("1", "yes", "true", "default")


def _get_pvr_catchup_correction_mode():
    mode = (
        _get_setting_direct("pvr_catchup_correction_mode", "Auto (device timezone)")
        or "Auto (device timezone)"
    )
    legacy_modes = {
        "Auto from EPG timezone": "Provider metadata",
        "Manual": "Manual replay timezone",
    }
    return legacy_modes.get(mode, mode)


def _parse_utc_timezone_label(value):
    value = str(value or "").strip().upper().replace(" ", "")
    if value in ("UTC", "UTC+0", "UTC-0", "GMT", "GMT+0", "GMT-0"):
        return 0.0
    m = re.match(r"^(?:UTC|GMT)([+-])(\d{1,2})(?::?(\d{2}))?$", value)
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3) or "0")
    if hours > 14 or minutes >= 60:
        return None
    return sign * (hours + (minutes / 60.0))


def _device_utc_offset_hours():
    try:
        if time.daylight and time.localtime().tm_isdst > 0:
            offset_seconds = -time.altzone
        else:
            offset_seconds = -time.timezone
        return round(offset_seconds / 60.0) / 60.0
    except Exception:
        try:
            delta = datetime.datetime.now() - datetime.datetime.utcnow()
            return round(delta.total_seconds() / 60.0) / 60.0
        except Exception:
            return 0.0


def _get_manual_pvr_catchup_correction():
    value = _get_setting_direct("pvr_catchup_correction", "UTC") or "UTC"
    offset = _parse_utc_timezone_label(value)
    if offset is not None:
        return _format_catchup_correction(-offset)
    # Legacy raw correction value, for existing users with values like -2.
    try:
        return _format_catchup_correction(float(value))
    except ValueError:
        return "0"


def _xtream_timeshift_catchup_source(base_url, username, password, stream_id):
    base = (base_url or "").rstrip("/")
    return (
        f"{base}/live/{urllib.parse.quote(str(username))}/"
        f"{urllib.parse.quote(str(password))}/"
        f"{urllib.parse.quote(str(stream_id))}.ts?"
        "utc={utc}&lutc=${end}"
    )


def _xmltv_timezone_hours(ts):
    if not ts or " " not in ts:
        return None
    tz = ts.rsplit(" ", 1)[1].strip()
    if len(tz) != 5 or tz[0] not in "+-":
        return None
    try:
        sign = 1 if tz[0] == "+" else -1
        return sign * (int(tz[1:3]) + (int(tz[3:5]) / 60.0))
    except ValueError:
        return None


def _format_catchup_correction(value):
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _provider_catchup_correction_for_channel(epg_programs, epg_id):
    programs = epg_programs.get(epg_id) or []
    for prog in programs:
        offset = _xmltv_timezone_hours(prog.get("start", ""))
        if offset is not None:
            return _format_catchup_correction(-offset)
    return ""


def _catchup_correction_for_channel(epg_programs, epg_id, provider_correction=""):
    mode = _get_pvr_catchup_correction_mode()
    if mode == "Off":
        return ""
    if mode == "Manual replay timezone":
        return _get_manual_pvr_catchup_correction()
    if mode == "Provider metadata":
        return provider_correction or _provider_catchup_correction_for_channel(
            epg_programs, epg_id
        )
    # Auto mode uses the Kodi device timezone.
    return _format_catchup_correction(-_device_utc_offset_hours())


def _sync_pvr_force():
    return _pvr_sync._sync_pvr_force()



def _sync_pvr_epg_only(offer_reload=True):
    return _pvr_sync._sync_pvr_epg_only(offer_reload)



def _remove_owned_pvr_instances():
    return _pvr_sync._remove_owned_pvr_instances()



def _unload_pvr(progress=None):
    return _pvr_sync._unload_pvr(progress)



def reset_pvr_epg_db_action():
    return _pvr_sync.reset_pvr_epg_db_action()



def _maybe_show_pvr_first_run():
    return _pvr_sync._maybe_show_pvr_first_run()



def _build_fetch_steps(xt_url, xt_user, xt_pwd, m3u_url, force=False):
    return _user_profile_refresh._build_fetch_steps(xt_url, xt_user, xt_pwd, m3u_url, force)



def _run_profile_refresh_steps(profile_num, progress=None, start_percent=20, end_percent=95, log_prefix='Refresh', force=False):
    return _user_profile_refresh._run_profile_refresh_steps(profile_num, progress, start_percent, end_percent, log_prefix, force)



def _prefetch_all_data():
    return _user_profile_refresh._prefetch_all_data()



def _epg_enabled():
    return _live_playback._epg_enabled()



def _set_live_props(li):
    return _live_playback._set_live_props(li)



def play_stream(play_url, name, title='', plot='', icon='', stype='live', series_id='', season_num='', ep_id='', profile_num=None, kodi_props=None, stream_ua='', stream_ref='', resume_pos=0, resume_total=0, tmdb_id=''):
    return _live_playback.play_stream(play_url, name, title, plot, icon, stype, series_id, season_num, ep_id, profile_num, kodi_props, stream_ua, stream_ref, resume_pos, resume_total, tmdb_id)



_PLAYBACK_MAX_RETRIES = 5
_PLAYBACK_RETRY_DELAY = 3000
_PLAYBACK_STARTUP_TIMEOUT = 120
_PLAYBACK_STARTUP_POLL = 500


def _monitor_playback(name, url, stype='live', profile_num=None, upnext_data=None, stream_id='', icon='', extra=None, tmdb_id='', title='', plot=''):
    return _live_playback._monitor_playback(name, url, stype, profile_num, upnext_data, stream_id, icon, extra, tmdb_id, title, plot)



def _prepare_playback_item(li):
    return _live_playback._prepare_playback_item(li)



def _is_adult_category(name):
    # Adult keywords with word boundaries to reduce false positives
    adult_patterns = [
        r"\bxxx\b",
        r"\badult\b",
        r"\bmature\b",
        r"\bporn\b",
        r"\berotic\b",
        r"\berotica\b",
        r"\bnsfw\b",
        r"\bx-rated\b",
        r"\bxrated\b",
        r"\bplayboy\b",
        r"\bhustler\b",
        r"\bpenthouse\b",
        r"\bbrazzers\b",
        r"\bnaughty\b",
        r"\bsexy\b",
        r"\bsex\b",
        r"\bhentai\b",
        r"\bstriptease\b",
        r"\bfetish\b",
        r"\bnude\b",
        r"\bnaked\b",
        r"\borgasm\b",
        r"\bkamasutra\b",
        r"\bmilf\b",
        r"\blesbian\b",
        r"\bgay\b",
        r"\bhardcore\b",
        r"\bsoftcore\b",
        r"\btopless\b",
        r"\buncensored\b",
        r"\buncut\b",
        r"\bvoyeur\b",
        r"\bswinger\b",
        r"\bredlight\b",
        r"\bred light\b",
        r"\bblue film\b",
        r"\bhot club\b",
        r"\bnight show\b",
        r"\bfor adults\b",
        r"\b18\+",
        r"\(\s*18\+\s*\)",
        r"\[\s*18\+\s*\]",
    ]
    lower = name.lower()
    return any(re.search(p, lower) for p in adult_patterns)


def _hash_pin(pin):
    """Hash PIN with SHA-256 and addon-id salt for secure storage."""

    salt = addon.getAddonInfo("id") or "plugin.video.xstream-pro"
    return hashlib.sha256((pin + salt).encode("utf-8")).hexdigest()


_PIN_HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def _normalize_parental_pin():
    pin = addon.getSetting("parental_pin") or "0000"
    if not _PIN_HASH_RE.match(pin):
        hashed = _hash_pin(pin)
        addon.setSetting("parental_pin", hashed)
        return hashed
    return pin


def _check_pin(required_for=""):
    if addon.getSetting("enable_parental_control").lower() != "true":
        return True
    # Check per-area toggles
    area_map = {
        "Settings": "parental_lock_settings",
        "Tools": "parental_lock_tools",
    }
    setting_key = area_map.get(required_for)
    if setting_key and addon.getSetting(setting_key).lower() != "true":
        return True
    stored_pin = _normalize_parental_pin()
    kb = xbmcgui.Dialog().input(
        _t(30032).format(required_for),
        type=xbmcgui.INPUT_ALPHANUM,
        option=xbmcgui.ALPHANUM_HIDE_INPUT,
    )
    if _hash_pin(kb) != stored_pin:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30061))
        return False
    return True


def _ensure_pvr_runtime_channels(
    label,
    m3u_path,
    min_channels=1,
    required_group_prefix="",
    role="main",
):
    return _pvr_scope._ensure_pvr_runtime_channels(
        label, m3u_path, min_channels=min_channels,
        required_group_prefix=required_group_prefix, role=role,
    )


def _ensure_pvr_runtime_channels_with_count(
    label,
    m3u_path,
    min_channels=1,
    required_group_prefix="",
    role="main",
):
    return _pvr_scope._ensure_pvr_runtime_channels_with_count(
        label, m3u_path, min_channels=min_channels,
        required_group_prefix=required_group_prefix, role=role,
    )


def _wait_for_pvr_ready_before_window(
    label="PVR",
    timeout_seconds=8,
    min_channels=1,
    required_group_label="",
    required_group_prefix="",
    notify_on_timeout=True,
    show_progress=False,
    role="main",
    m3u_path="",
    preloaded_count=None,
):
    return _pvr_scope._wait_for_pvr_ready_before_window(
        label, timeout_seconds=timeout_seconds,
        min_channels=min_channels,
        required_group_label=required_group_label,
        required_group_prefix=required_group_prefix,
        notify_on_timeout=notify_on_timeout,
        show_progress=show_progress,
        role=role, m3u_path=m3u_path,
        preloaded_count=preloaded_count,
    )


def _activate_pvr_window_with_last_group(window_name, scope="live", fallback_label="", role="main"):
    return _pvr_scope._activate_pvr_window_with_last_group(window_name, scope=scope, fallback_label=fallback_label, role=role)


def _profiles_refresh_stamp_path():
    return _startup._profiles_refresh_stamp_path()



def _get_profiles_last_refresh():
    return _startup._get_profiles_last_refresh()



def _set_profiles_last_refresh():
    return _startup._set_profiles_last_refresh()



def _profiles_auto_refresh_due():
    return _startup._profiles_auto_refresh_due()



def _check_profiles_auto_refresh():
    return _startup._check_profiles_auto_refresh()



def _check_credentials_refresh_prompt():
    return _startup._check_credentials_refresh_prompt()



def _check_pvr_startup_retry():
    return _startup._check_pvr_startup_retry()



def _schedule_pvr_startup_retry_sync(retry_flag):
    return _startup._schedule_pvr_startup_retry_sync(retry_flag)



def _is_first_refresh():
    return _startup._is_first_refresh()



def _mark_first_refresh_done():
    return _startup._mark_first_refresh_done()



def sports_refresh_profile_menu():
    return _user_profile_refresh.sports_refresh_profile_menu()



def refresh_profile_menu():
    return _user_profile_refresh.refresh_profile_menu()



def _refresh_all_profiles_with_progress(profiles):
    return _user_profile_refresh._refresh_all_profiles_with_progress(profiles)



def _refresh_single_profile_silent(profile_num, force=False):
    return _user_profile_refresh._refresh_single_profile_silent(profile_num, force)



def _refresh_profile_data(profile_num):
    return _user_profile_refresh._refresh_profile_data(profile_num)



def _refresh_profiles_batch(profile_nums):
    return _user_profile_refresh._refresh_profiles_batch(profile_nums)



def refresh_data():
    return _user_profile_refresh.refresh_data()



def open_pvr():
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
    if not _pvr_open_guard("Live TV PVR"):
        return
    try:
        pvr_pnum = _get_pvr_profile_num()
        if not _prompt_profile_credentials(pvr_pnum):
            return
        if not _switch_pvr_instance_scope("main", "Live TV PVR"):
            return
        ok, channel_count = _ensure_pvr_runtime_channels_with_count(
            "Live TV PVR", _pvr_m3u_path(), role="main"
        )
        if not ok:
            return
        if not _wait_for_pvr_ready_before_window(
            "Live TV PVR",
            timeout_seconds=35,
            show_progress=True,
            role="main",
            m3u_path=_pvr_m3u_path(),
            preloaded_count=channel_count,
        ):
            return
        xbmc.sleep(_tvos_sleep(500))
        _activate_pvr_window_with_last_group("TVChannels", scope="live", role="main")
    finally:
        _pvr_open_release()


def open_pvr_guide():
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
    if not _owned_pvr_instance_enabled("main"):
        xbmcgui.Dialog().notification("Xstream Pro", _t(30787), xbmcgui.NOTIFICATION_WARNING, 3000)
        return
    if not _pvr_open_guard("Live TV PVR Guide"):
        return
    try:
        pvr_pnum = _get_pvr_profile_num()
        if not _prompt_profile_credentials(pvr_pnum):
            return
        if not _switch_pvr_instance_scope("main", "Live TV PVR Guide"):
            return
        ok, channel_count = _ensure_pvr_runtime_channels_with_count(
            "Live TV PVR Guide", _pvr_m3u_path(), role="main"
        )
        if not ok:
            return
        if not _wait_for_pvr_ready_before_window(
            "Live TV PVR Guide",
            timeout_seconds=35,
            show_progress=True,
            role="main",
            m3u_path=_pvr_m3u_path(),
            preloaded_count=channel_count,
        ):
            return
        xbmc.sleep(_tvos_sleep(500))
        _activate_pvr_window_with_last_group("TVGuide", scope="live", role="main")
    finally:
        _pvr_open_release()


def _get_pvr_profile_num():
    return _pvr_paths._get_pvr_profile_num()


def _get_sports_pvr_profile_num():
    return _pvr_paths._get_sports_pvr_profile_num()


def _pvr_numbered_label(label, profile_num=None):
    profile_num = profile_num or _get_pvr_profile_num()
    return "{0} {1} ({2})".format(_pvr_scope_dot("main"), label, profile_num)


def _sports_pvr_numbered_label(label, profile_num=None):
    profile_num = profile_num or _get_sports_pvr_profile_num()
    return "{0} {1} ({2})".format(_pvr_scope_dot("sports"), label, profile_num)


def _pvr_epg_path_for_profile(profile_num):
    return _pvr_paths._pvr_epg_path_for_profile(profile_num)


def _pvr_favs_path():
    return _pvr_favorites._pvr_favs_path()



def _sports_pvr_m3u_path():
    return _pvr_paths._sports_pvr_m3u_path()


def _sports_pvr_epg_path_for_profile(profile_num):
    return _pvr_paths._sports_pvr_epg_path_for_profile(profile_num)


def _sports_pvr_epg_path():
    return _pvr_paths._sports_pvr_epg_path()


def _sports_pvr_favs_path():
    return _pvr_favorites._sports_pvr_favs_path()



def _sports_pvr_favs_m3u_path():
    return _pvr_favorites._sports_pvr_favs_m3u_path()



def _pvr_favs_load_all():
    return _pvr_favorites._pvr_favs_load_all()



def _pvr_favs_save_all(groups):
    return _pvr_favorites._pvr_favs_save_all(groups)



def _pvr_favs_load(group=None):
    return _pvr_favorites._pvr_favs_load(group)



def _pvr_favs_save(items, group=None):
    return _pvr_favorites._pvr_favs_save(items, group)



def _pvr_favs_add(channel, group=None):
    return _pvr_favorites._pvr_favs_add(channel, group)



def _pvr_favs_remove(stream_id, group=None):
    return _pvr_favorites._pvr_favs_remove(stream_id, group)



def _pvr_favs_m3u_path():
    return _pvr_favorites._pvr_favs_m3u_path()



def _export_pvr_favs_m3u():
    return _pvr_favorites._export_pvr_favs_m3u()



def _sports_pvr_group_mode():
    mode = addon.getSetting("sports_pvr_group_mode") or "Countries / Regions"
    legacy = {
        "By Country": "Countries / Regions",
        "By Sport": "Countries / Regions",
        "By Provider Group": "Provider Groups",
    }
    mapped = legacy.get(mode, mode)
    if mapped != mode:
        try:
            addon.setSetting("sports_pvr_group_mode", mapped)
        except Exception:
            pass
    return mapped


def _sports_pvr_source_channels():
    if not _setup_sports_routes():
        return []
    pnum = _get_sports_pvr_profile_num()
    group_mode = _sports_pvr_group_mode()
    try:
        return _sports_routes.sports_pvr_channels_for_profile(pnum, group_mode) or []
    except Exception as e:
        _log(f"Sports PVR: source channel build failed: {e}")
        return []


def _apply_pvr_catchup_corrections(channels, profile_num, log_prefix):
    if not channels:
        return channels
    epg_programs = {}
    if _get_pvr_catchup_correction_mode() == "Provider metadata":
        try:
            epg = EPG(addon, profile_num=profile_num)
            epg.load()
            epg_programs = epg.programs or {}
        except Exception as e:
            _log(f"{log_prefix}: Catchup correction EPG load warning: {e}")
    for ch in channels:
        if ch.get("catchup"):
            ch["catchup_correction"] = _catchup_correction_for_channel(
                epg_programs, ch.get("tvg_id", ""), ch.get("catchup_correction", "")
            )
    return channels


def _live_pvr_alias_id(ch, profile_num, salt=""):
    stable = (
        ch.get("stream_id")
        or ch.get("url")
        or ch.get("source_tvg_id")
        or ch.get("tvg_id")
        or ch.get("name")
        or ""
    )
    raw = "live|{0}|{1}|{2}".format(profile_num, stable, salt)
    digest = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return "xstream-live-p{0}-{1}".format(profile_num, digest)


def _prepare_live_pvr_channels_for_export(channels, profile_num):
    seen_tvg_ids = {}
    prepared = []
    for index, ch in enumerate(channels or [], 1):
        item = dict(ch)
        item["group"] = PVR_LIVE_GROUP_PREFIX + _pvr_live_group_label(item.get("group") or "General")
        source_tvg_id = item.get("tvg_id") or ""
        item["source_tvg_id"] = source_tvg_id
        if source_tvg_id and source_tvg_id in seen_tvg_ids:
            item["tvg_id"] = _live_pvr_alias_id(item, profile_num, str(index))
        elif source_tvg_id:
            seen_tvg_ids[source_tvg_id] = index
        prepared.append(item)
    return prepared


def _sports_pvr_alias_id(ch, profile_num, salt=""):
    stable = (
        ch.get("stream_id")
        or ch.get("url")
        or ch.get("source_tvg_id")
        or ch.get("tvg_id")
        or ch.get("name")
        or ""
    )
    raw = "sports|{0}|{1}|{2}".format(profile_num, stable, salt)
    digest = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return "xstream-sports-p{0}-{1}".format(profile_num, digest)


def _prepare_sports_pvr_channels_for_export(channels, profile_num):
    seen_source_ids = {}
    prepared = []
    for index, ch in enumerate(channels or [], 1):
        item = dict(ch)
        source_tvg_id = (
            item.get("source_tvg_id")
            or item.get("epg_channel_id")
            or item.get("tvg_id")
            or ""
        )
        item["source_tvg_id"] = source_tvg_id
        if source_tvg_id and source_tvg_id in seen_source_ids:
            item["tvg_id"] = _sports_pvr_alias_id(item, profile_num, salt=str(index))
        elif source_tvg_id:
            seen_source_ids[source_tvg_id] = index
        group = item.get("group") or "Sports TV"
        if not group.startswith(("★ ", "Sports TV - ", "Xstream Pro ", "Live TV - ")):
            group = PVR_SPORTS_GROUP_PREFIX + group
        item["group"] = group
        prepared.append(item)
    return prepared


def _export_sports_pvr_epg_for_profile(profile_num, channels, force_fetch=False):
    return _pvr_export.export_sports_pvr_epg_for_profile(profile_num, channels, force_fetch=force_fetch)



def _export_sports_pvr_m3u():
    return _pvr_export.export_sports_pvr_m3u()



def _sports_pvr_favs_load_all():
    return _pvr_favorites._sports_pvr_favs_load_all()



def _sports_pvr_favs_save_all(groups):
    return _pvr_favorites._sports_pvr_favs_save_all(groups)



def _sports_pvr_favs_load(group=None):
    return _pvr_favorites._sports_pvr_favs_load(group)



def _sports_pvr_favs_save(items, group=None):
    return _pvr_favorites._sports_pvr_favs_save(items, group)



def _export_sports_pvr_favs_m3u():
    return _pvr_favorites._export_sports_pvr_favs_m3u()



def _remove_pvr_instance_config(role, log_prefix, force=False, m3u_path=None):
    return _pvr_instances._remove_pvr_instance_config(role, log_prefix, force, m3u_path)


def _remove_duplicate_pvr_instances(role, keep_id, log_prefix):
    return _pvr_instances._remove_duplicate_pvr_instances(role, keep_id, log_prefix)


def _configure_sports_pvr_instance(enabled=False):
    return _pvr_instances._configure_sports_pvr_instance(enabled)


def _configure_sports_pvr_favs_instance(enabled=False):
    return _pvr_instances._configure_sports_pvr_favs_instance(enabled)


def _pvr_progress(progress, percent, message):
    return _pvr_sync._pvr_progress(progress, percent, message)



def _sync_sports_pvr_during_pvr_sync(progress=None):
    return _pvr_sync._sync_sports_pvr_during_pvr_sync(progress)



def _sync_sports_pvr_safe():
    return _pvr_sync._sync_sports_pvr_safe()


def _remove_pvr_favs_instance_config(force=False):
    return _pvr_instances._remove_pvr_favs_instance_config(force)


def _configure_pvr_favs_instance(enabled=True):
    return _pvr_instances._configure_pvr_favs_instance(enabled)


def _sync_pvr_favorites():
    return _pvr_favorites._sync_pvr_favorites()



def _safe_sync_pvr_favorites_startup():
    return _pvr_favorites._safe_sync_pvr_favorites_startup()



def _sync_pvr_favorites_safe():
    return _pvr_favorites._sync_pvr_favorites_safe()



def pvr_favorites_manager(group=None):
    return _pvr_favorites.pvr_favorites_manager(group)



def pvr_favs_manage_group(group):
    return _pvr_favorites.pvr_favs_manage_group(group)



def pvr_favs_group_current(group):
    return _pvr_favorites.pvr_favs_group_current(group)



def pvr_favs_group_search(group):
    return _pvr_favorites.pvr_favs_group_search(group)



def pvr_favs_manage_cat(cat_id, cat_name, group):
    return _pvr_favorites.pvr_favs_manage_cat(cat_id, cat_name, group)



def _pvr_favs_multiselect(filtered, dialog, group=None):
    return _pvr_favorites._pvr_favs_multiselect(filtered, dialog, group)



def _sports_pvr_item_key(ch):
    return _pvr_favorites._sports_pvr_item_key(ch)



def _sports_pvr_source_country_groups():
    return _pvr_favorites._sports_pvr_source_country_groups()



def sports_pvr_favorites_manager(group=None):
    return _pvr_favorites.sports_pvr_favorites_manager(group)



def sports_pvr_favs_manage(group=None):
    return _pvr_favorites.sports_pvr_favs_manage(group)



def sports_pvr_favs_manage_group(group):
    return _pvr_favorites.sports_pvr_favs_manage_group(group)



def sports_pvr_favs_group_current(group):
    return _pvr_favorites.sports_pvr_favs_group_current(group)



def sports_pvr_favs_group_search(group):
    return _pvr_favorites.sports_pvr_favs_group_search(group)



def sports_pvr_favs_manage_country(country, group):
    return _pvr_favorites.sports_pvr_favs_manage_country(country, group)



def _sports_pvr_favs_multiselect(filtered, dialog, group=None):
    return _pvr_favorites._sports_pvr_favs_multiselect(filtered, dialog, group)



def sports_pvr_favs_new_group():
    return _pvr_favorites.sports_pvr_favs_new_group()



def sports_pvr_favs_rename_group():
    return _pvr_favorites.sports_pvr_favs_rename_group()



def sports_pvr_favs_delete_group():
    return _pvr_favorites.sports_pvr_favs_delete_group()



def sports_pvr_fav_remove(stream_id, group=None):
    return _pvr_favorites.sports_pvr_fav_remove(stream_id, group)



def _check_account_expiry():
    return _startup._check_account_expiry()



def _get_setting_direct(setting_id, default=""):
    return _core_settings._get_setting_direct(setting_id, default=default)


def _invalidate_settings_xml_cache():
    return _core_settings._invalidate_settings_xml_cache()


def _run_startup_checks():
    return _startup._run_startup_checks()


_M3U_MOVIE_WORDS = (
    "movie", "movies", "film", "films", "vod", "cinema", "4k movies",
)
_M3U_SERIES_WORDS = (
    "series", "tv show", "tv shows", "show", "shows", "episode", "episodes", "season",
)
_M3U_LIVE_WORDS = (
    "live", "tv", "channel", "channels", "news", "sport", "sports", "radio",
)


def _classify_m3u_channel(ch):
    group = (ch.get("group") or "").lower()
    name = (ch.get("name") or "").lower()
    url = (ch.get("url") or "").lower()
    haystack = " ".join((group, name, url))
    if re.search(r"\bS\d{1,2}E\d{1,2}\b", name, re.IGNORECASE):
        return "series"
    if re.search(r"\b\d{1,2}x\d{1,2}\b", name, re.IGNORECASE):
        return "series"
    if re.search(r"\bseason\s*\d+\b|\bepisode\s*\d+\b", name, re.IGNORECASE):
        return "series"
    if any(word in haystack for word in _M3U_SERIES_WORDS):
        return "series"
    if any(word in haystack for word in _M3U_MOVIE_WORDS):
        return "movie"
    if any(word in haystack for word in _M3U_LIVE_WORDS):
        return "live"
    return "live"


def _m3u_simple_menu(profile_num):
    return _live_browse._m3u_simple_menu(profile_num)



def _show_all_m3u_channels(profile_num, page=1, stype_filter=""):
    return _live_browse._show_all_m3u_channels(profile_num, page, stype_filter)



_MAIN_MENU_CUSTOMIZED_KEY = "main_menu_customized"
_MAIN_MENU_MANAGED_KEYS = [
    "live_pvr",
    "pvr_replay",
    "guide",
    "sports",
    "tmdb_movies",
    "tmdb_tvshows",
    "tmdb_animations",
    "tmdb_people",
    "tmdb_lists",
    "tmdb_randomised",
    "tmdb_discover",
    "tmdb_trakt",
    "tmdb_search",
    "search_global",
    "favorites",
    "downloads",
] + ["profile_{0}".format(n) for n in range(1, 11)]

def _main_menu_item_visible(visible, key):
    return _menus_main.main_menu_item_visible(visible, key)

def _main_menu_available_item_labels():
    return _menus_main.main_menu_available_item_labels()


def main_menu():
    return _menus_main.main_menu()



def _local_icon(name):
    return _user_artwork.local_icon(name)


def _menu_art(icon, fanart=None):
    return _user_artwork.menu_art(icon, fanart)


def _addon_fanart():
    return _user_artwork.addon_fanart()


def _clear_background():
    return _user_artwork.clear_background()


def _restore_background():
    return _user_artwork.restore_background()
















def _normalize_tmdb_type(tmdb_type):
    raw = str(tmdb_type or "").lower()
    if raw in ("tv", "tvshow", "show", "season", "episode"):
        return "tv"
    if raw in ("movie", "movies"):
        return "movie"
    return ""












def _tmdb_source_select_url(title, year, tmdb_type, tmdb_id="", season="", episode="", intent="", showname=""):
    q = {
        "mode": "source_select",
        "title": title,
        "year": year,
        "tmdb_type": tmdb_type,
        "tmdb_id": tmdb_id,
    }
    if tmdb_type == "tv":
        q["showname"] = showname or title
    if season:
        q["season"] = season
    if episode:
        q["episode"] = episode
    if intent:
        q["intent"] = intent
    return build_url(q)


def _tmdb_source_action_url(title, year, tmdb_type, tmdb_id="", season="", episode="", intent="play", showname=""):
    q = {
        "mode": "tmdb_source_action",
        "title": title,
        "year": year,
        "tmdb_type": tmdb_type,
        "tmdb_id": tmdb_id,
        "intent": intent,
    }
    if showname:
        q["showname"] = showname
    if season:
        q["season"] = season
    if episode:
        q["episode"] = episode
    return build_url(q)


def _tmdb_series_action_url(showname, year, intent, tmdb_id="", season=""):
    q = {
        "mode": "tmdb_series_action",
        "showname": showname,
        "year": year,
        "intent": intent,
        "tmdb_id": tmdb_id,
    }
    if season:
        q["season"] = season
    return build_url(q)


def _tmdb_item_ctx(label, icon, year, tmdb_type, tmdb_id="", season="", episode="", showname="", kind="", collection_id="", is_watched=False):
    real_showname = showname or label
    is_tv_show_or_season = tmdb_type == "tv" and kind in ("tvshow", "season")
    fav_url = _tmdb_source_select_url(label, year, tmdb_type, tmdb_id, season, episode, showname=showname)
    fav_id = "tmdb:{0}:{1}:{2}:{3}".format(tmdb_type, tmdb_id or label, season, episode)
    ctx = []
    if is_tv_show_or_season:
        ctx.append((_t(31073), "RunPlugin({0})".format(_tmdb_series_action_url(real_showname, year, "play", tmdb_id, season if kind == "season" else ""))))
        ctx.append((_t(30941), "RunPlugin({0})".format(_tmdb_series_action_url(real_showname, year, "download", tmdb_id, season if kind == "season" else ""))))
    else:
        ctx.append((_t(31073), "RunPlugin({0})".format(_tmdb_source_action_url(label, year, tmdb_type, tmdb_id, season, episode, "play", showname))))
        ctx.append((_t(30941), "RunPlugin({0})".format(_tmdb_source_action_url(label, year, tmdb_type, tmdb_id, season, episode, "download", showname))))
    # Mark watched / unwatched
    _tw_url = build_url({
        "mode": "toggle_tmdb_watched",
        "tmdb_id": tmdb_id,
        "tmdb_type": tmdb_type,
        "season": season,
        "episode": episode,
    })
    _tw_label = (_t(31082) + " - Xstream") if is_watched else (_t(31081) + " - Xstream")
    ctx.append((_tw_label, "RunPlugin({0})".format(_tw_url)))
    # Trailer
    if tmdb_id:
        _trailer_url = build_url({
            "mode": "xstream_tmdb_trailer",
            "tmdb_type": tmdb_type,
            "tmdb_id": tmdb_id,
        })
        ctx.append((_t(31078), "RunPlugin({0})".format(_trailer_url)))
    # Similar
    if tmdb_id:
        _similar_url = build_url({
            "mode": "xstream_tmdb_similar",
            "tmdb_type": tmdb_type,
            "tmdb_id": tmdb_id,
            "relation": "similar",
        })
        ctx.append((_t(31079), "ActivateWindow(Videos,{0},return)".format(_similar_url)))
    # Seasons (TV shows)
    if tmdb_type == "tv" and tmdb_id and kind in ("tvshow", "season", ""):
        _fs_url = build_url({
            "mode": "xstream_tmdb_seasons",
            "tmdb_id": tmdb_id,
            "title": real_showname or label,
            "year": year,
        })
        ctx.append((_t(31110), "ActivateWindow(Videos,{0},return)".format(_fs_url)))    # Recommendations
    if tmdb_id:
        _rec_url = build_url({
            "mode": "xstream_tmdb_recommendations",
            "tmdb_type": tmdb_type,
            "tmdb_id": tmdb_id,
            "relation": "recommendations",
        })
        ctx.append((_t(31116), "ActivateWindow(Videos,{0},return)".format(_rec_url)))
    # Trakt Options
    if tmdb_id:
        _trakt_url = build_url({
            "mode": "xstream_trakt_item_action",
            "tmdb_type": tmdb_type,
            "tmdb_id": tmdb_id,
            "season": season,
            "episode": episode,
        })
        ctx.append((_t(31080), "RunPlugin({0})".format(_trakt_url)))
    # View Collection
    if tmdb_type == "movie" and tmdb_id:
        _coll_url = build_url({
            "mode": "xstream_tmdb_collection_from_movie",
            "tmdb_id": tmdb_id,
        })
        ctx.append((_t(31108), "ActivateWindow(Videos,{0},return)".format(_coll_url)))
    ctx.extend(_build_favorite_ctx(
        fav_id,
        label,
        "tmdb",
        icon,
        fav_url,
        include_download=False,
    ))
    return ctx


def _rebuild_provider_availability_cache(show_progress=False):
    return _provider_availability._rebuild_provider_availability_cache(show_progress)



def _provider_item_available_for_tmdb(item, strict_title_year=False):
    return _provider_availability._provider_item_available_for_tmdb(item, strict_title_year)



def _refresh_provider_availability_cache_after_profile_load(show_progress=False):
    provider_marking_enabled = (
        _provider_only_tmdb_enabled()
        or addon.getSetting("tmdb_mark_unavailable").lower() == "true"
    )
    if not provider_marking_enabled:
        return
    try:
        return _rebuild_provider_availability_cache(show_progress=show_progress)
    except Exception as e:
        _log("Provider availability cache rebuild warning: {0}".format(e))
        _log("Traceback: {0}".format(traceback.format_exc()))


def _setup_tmdb_routes():
    return _tmdb_bridge.setup_tmdb_routes()


def _get_tmdb_routes_module():
    return _tmdb_bridge.get_tmdb_routes_module()


_sports_results_routes = None
_sports_results_routes_setup = None

def _setup_sports_results_routes():
    global _sports_results_routes, _sports_results_routes_setup

    if not _sports_results_routes_setup or not _sports_results_routes:
        try:
            import sports_results as _sports_results_routes_module
            _sports_results_routes = _sports_results_routes_module
            _sports_results_routes_setup = _sports_results_routes_module.setup
        except Exception as e:
            _log("Sports results routes import failed: {0}".format(e))
            _log("Traceback: {0}".format(traceback.format_exc()))
            xbmcgui.Dialog().notification("Xstream Pro", "Sports results failed to load")
            li = _new_listitem("Sports results failed to load")
            xbmcplugin.addDirectoryItem(addon_handle, "", li, False)
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return False

    _sports_results_routes_setup({
        "addon": addon,
        "addon_handle": addon_handle,
        "build_url": build_url,
        "_t": _t,
        "_new_listitem": _new_listitem,
        "_local_icon": _local_icon,
        "_addon_fanart": _addon_fanart,
        "_menu_art": _menu_art,
        "_log": _log,
        "_log_route_timing": _log_route_timing,
        "_tvos_sleep": _tvos_sleep,
    })
    return True


def _setup_sports_routes():
    global _sports_routes, _sports_routes_setup
    if _sports_routes_setup:
        return True
    try:
        import sports as routes
        routes.setup({
            "addon": addon,
            "addon_handle": addon_handle,
            "build_url": build_url,
            "_t": _t,
            "_log": _log,
            "_log_route_timing": _log_route_timing,
            "_new_listitem": _new_listitem,
            "_local_icon": _local_icon,
            "_menu_art": _menu_art,
            "_addon_fanart": _addon_fanart,
            "_get_pvr_profile_num": _get_pvr_profile_num,
            "_pvr_numbered_label": _pvr_numbered_label,
            "_get_sports_pvr_profile_num": _get_sports_pvr_profile_num,
            "_sports_pvr_numbered_label": _sports_pvr_numbered_label,
            "_prompt_profile_credentials": _prompt_profile_credentials,
            "_enabled_profiles_with_credentials": _enabled_profiles_with_credentials,
            "_get_credentials_for_profile": _get_credentials_for_profile,
            "_call_with_active_profile": _call_with_active_profile,
            "_get_cached_xtream_categories": _get_cached_xtream_categories,
            "_get_cached_xtream_streams": _get_cached_xtream_streams,
            "_get_cached_m3u_channels": _get_cached_m3u_channels,
            "refresh_profile_menu": refresh_profile_menu,
            "_get_hidden_subcats": _get_hidden_subcats,
            "_get_hidden_items": _get_hidden_items,
            "_is_adult_category": _is_adult_category,
            "_truthy_catchup": _truthy_catchup,
            "_xtream_timeshift_catchup_source": _xtream_timeshift_catchup_source,
            "EPG": EPG,
            "_make_epg_info": _make_epg_info,
            "_build_same_group_epg_aliases": _build_same_group_epg_aliases,
            "_apply_epg_fallback_from_other_profiles": _apply_epg_fallback_from_other_profiles,
            "_prepare_playback_item": _prepare_playback_item,
            "_set_live_props": _set_live_props,
            "_build_favorite_ctx": _build_favorite_ctx,
            "_switch_pvr_instance_scope": _switch_pvr_instance_scope,
            "_ensure_pvr_instance_paths": _ensure_pvr_instance_paths,
            "_sports_pvr_ready": _sports_pvr_ready,
            "_wait_for_pvr_ready_before_window": _wait_for_pvr_ready_before_window,
            "_ensure_pvr_runtime_channels": _ensure_pvr_runtime_channels,
            "_activate_pvr_window_with_last_group": _activate_pvr_window_with_last_group,
            "_sync_sports_pvr_safe": _sync_sports_pvr_safe,
            "_pvr_open_guard": _pvr_open_guard,
            "_pvr_open_release": _pvr_open_release,
            "_tvos_sleep": _tvos_sleep,
            "_sports_pvr_m3u_path": _sports_pvr_m3u_path,
            "_sports_pvr_favs_m3u_path": _sports_pvr_favs_m3u_path,
            "_m3u_file_has_channels": _m3u_file_has_channels,
            "_profile_has_data": _profile_has_data,
            "_owned_pvr_instance_enabled": _owned_pvr_instance_enabled,
            "_current_pvr_instance_scope": _current_pvr_instance_scope,
        })
        _sports_routes = routes
        _sports_routes_setup = True
        return True
    except Exception as exc:
        _log("Sports route setup failed: {0}".format(exc))
        return False




def user_playlists_menu():
    """Submenu containing profiles, search, PVR favorites, and tools."""
    _log("Opening user playlists menu")
    visible = set(pm.get_visible_categories())
    # Safety: tools must always be visible so users can't lock themselves out
    visible.add("tools")

    active_profiles = []
    enabled_profiles = []
    profile_names = {}
    for n in range(1, 11):
        if addon.getSetting(f"profile_{n}_enabled") == "true":
            enabled_profiles.append(n)
            profile_names[n] = addon.getSetting(f"profile_{n}_name") or _t(30390, n)
            has_xtream = bool(addon.getSetting(f"profile_{n}_xtream_url"))
            has_m3u = bool(addon.getSetting(f"profile_{n}_m3u"))
            if has_xtream or has_m3u:
                active_profiles.append(n)

    has_search = len(active_profiles) > 0

    pvr_creds = _get_pvr_credentials()
    pvr_has_live = bool(pvr_creds.get("xtream_url") or pvr_creds.get("m3u_url"))

    items = []

    # Enabled profiles as folders
    for n in enabled_profiles:
        section_keys = {
            f"profile_{n}_live",
            f"profile_{n}_movies",
            f"profile_{n}_series",
            f"profile_{n}_replay",
            f"profile_{n}_favs",
            f"profile_{n}_recent",
            f"profile_{n}_search",
        }
        any_section_visible = bool(section_keys & visible)
        if f"profile_{n}" in visible or any_section_visible:
            items.append(
                (
                    profile_names[n],
                    {"mode": "profile_menu", "pnum": n},
                    _local_icon("profiles"),
                    True,
                )
            )

    if "pvr_favs" in visible and pvr_has_live:
        items.append(
            (
                _t(30008),
                {"mode": "pvr_favorites_manager"},
                "DefaultFavourites.png",
                True,
            )
        )

    if "search" in visible and has_search:
        items.append(
            (
                _t(30889),
                {"mode": "search_global"},
                "DefaultAddonsSearch.png",
                True,
            )
        )

    if "tools" in visible:
        items.append(
            (
                _t(30010),
                {"mode": "tools_menu"},
                "DefaultAddonProgram.png",
                True,
            )
        )

    _fanart = _addon_fanart()
    directory_items = []
    for item in items:
        label, q, icon, is_folder = item
        li = _new_listitem(label)
        art = {"icon": icon, "thumb": icon, "poster": icon}
        if _fanart:
            art["fanart"] = _fanart
        li.setArt(art)
        directory_items.append((build_url(q), li, is_folder))
    xbmcplugin.addDirectoryItems(addon_handle, directory_items)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _profile_section_visible(visible, pnum, section):
    return _menus_hidden._profile_section_visible(visible, pnum, section)


def _get_hidden_subcats(stype, profile_num=None):
    return _menus_hidden._get_hidden_subcats(stype, profile_num=profile_num)


def _get_hidden_items(stype, profile_num=None):
    return _menus_hidden._get_hidden_items(stype, profile_num=profile_num)


def _profile_has_data(profile_num):
    return _menus_hidden._profile_has_data(profile_num)


def manage_content_dialog(stype, profile_num):
    return _menus_hidden.manage_content_dialog(stype, profile_num)


def manage_hidden_subcats(stype, profile_num=None):
    return _menus_hidden.manage_hidden_subcats(stype, profile_num=profile_num)


def hide_m3u_item_action(stype, item_id, item_name, profile_num=None):
    return _menus_hidden.hide_m3u_item_action(stype, item_id, item_name, profile_num=profile_num)


def hide_subcat_action(stype, cat_id, cat_name, profile_num=None):
    return _menus_hidden.hide_subcat_action(stype, cat_id, cat_name, profile_num=profile_num)


def hide_all_subcats(stype, action, profile_num=None):
    return _menus_hidden.hide_all_subcats(stype, action, profile_num=profile_num)


def tmdb_local_recent(tmdb_type):
    return _menus_recent.tmdb_local_recent(tmdb_type, _get_history_classes()["WatchHistory"])

def tmdb_local_in_progress(tmdb_type):
    return _menus_recent.tmdb_local_in_progress(tmdb_type, _get_history_classes()["ResumePoints"])

def _is_adult_locked(stype):
    """Check if adult content for this type requires PIN."""
    if addon.getSetting("enable_parental_control").lower() != "true":
        return False
    lock_map = {
        "live": "parental_lock_adult_live",
        "movie": "parental_lock_adult_movies",
        "series": "parental_lock_adult_series",
    }
    key = lock_map.get(stype, "")
    return key and addon.getSetting(key).lower() == "true"


def toggle_provider_episode_watched(series_id, season_num, ep_id, profile_num=None):
    return _menus_recent.toggle_provider_episode_watched(
        series_id,
        season_num,
        ep_id,
        _get_history_classes()["WatchedEpisodes"],
        profile_num=profile_num,
    )


def toggle_provider_movie_watched(stream_id, profile_num=None):
    return _menus_recent.toggle_provider_movie_watched(
        stream_id,
        _get_history_classes()["WatchedMovies"],
        profile_num=profile_num,
    )



def _search_history_path(profile_num=None):
    return _live_search._search_history_path(profile_num)



def _load_search_history(profile_num=None):
    return _live_search._load_search_history(profile_num)



def _save_search_history(history, profile_num=None):
    return _live_search._save_search_history(history, profile_num)



def search_global(query=None, profile_num=None, stype=None):
    return _live_search.search_global(query, profile_num, stype)



def unified_search(query, stype=None):
    return _live_search.unified_search(query, stype)



def search_m3u(query=None, stype=None):
    return _live_search.search_m3u(query, stype)



def search_all_profiles(query):
    return _live_search.search_all_profiles(query)



def search_all_profiles_combined(query):
    return _live_search.search_all_profiles_combined(query)



def test_connection():
    results = []
    checked = 0
    pd = xbmcgui.DialogProgress()
    pd.create("Xstream Pro", _t(30288))
    for i in range(1, 11):
        if pd.iscanceled():
            break
        if addon.getSetting(f"profile_{i}_enabled") != "true":
            continue
        profile_name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
        pd.update(int((i - 1) * 10), f"{_t(30288)}: {profile_name}")
        creds = _get_credentials_for_profile(i)
        url = creds.get("xtream_url", "")
        user = creds.get("xtream_username", "")
        pwd = creds.get("xtream_password", "")
        if not url or not user or not pwd:
            continue
        checked += 1
        info = IPTV.validate_xtream(url, user, pwd)
        if info is None:
            results.append(f"[COLOR red]{profile_name}[/COLOR]: {_t(30054)}")
            continue

        exp = info.get("exp_date", "")
        exp_str = _t(30546)
        if exp:
            try:
                exp_dt = datetime.datetime.fromtimestamp(int(exp))
                exp_str = exp_dt.strftime("%Y-%m-%d %H:%M")
                days_left = (exp_dt - datetime.datetime.now()).days
                exp_str += _t(30420, days_left)
            except (ValueError, TypeError):
                exp_str = str(exp)
        status = info.get("status", _t(30428))
        max_conn = info.get("max_connections", "N/A")
        active_cons = info.get("active_cons", "0")
        results.append(
            f"[COLOR green]{profile_name}[/COLOR]: {_t(30421)} {status} | {_t(30422)} {exp_str} | {_t(30423)} {max_conn} | {_t(30424)} {active_cons}"
        )
        results.append("[COLOR gray]────────────────────[/COLOR]")
    pd.close()
    if checked == 0:
        xbmcgui.Dialog().ok("Xstream Pro", _t(30056))
        return
    if not results:
        xbmcgui.Dialog().ok(_t(30031), _t(30054) + "\n" + _t(30055))
        return
    xbmcgui.Dialog().textviewer(_t(30033), "\n".join(results).rstrip())


def account_info():
    lines = []
    has_any = False
    for i in range(1, 11):
        if addon.getSetting(f"profile_{i}_enabled") != "true":
            continue
        profile_name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
        creds = _get_credentials_for_profile(i)
        url = creds.get("xtream_url", "")
        user = creds.get("xtream_username", "")
        pwd = creds.get("xtream_password", "")
        if not url or not user or not pwd:
            continue
        has_any = True
        info = IPTV.validate_xtream(url, user, pwd)
        if info is None:
            lines.append(f"[B]{profile_name}[/B]: {_t(30123)}")
            lines.append("")
            continue

        exp = info.get("exp_date", "")
        exp_str = _t(30546)
        if exp:
            try:
                exp_dt = datetime.datetime.fromtimestamp(int(exp))
                exp_str = exp_dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                exp_str = str(exp)
        lines.append(f"[B]{profile_name}[/B]")
        lines.append(f"{_t(30421)}: {info.get('status', _t(30429))}")
        lines.append(f"{_t(30422)}: {exp_str}")
        lines.append(f"{_t(30423)}: {info.get('max_connections', 'N/A')}")
        lines.append(f"{_t(30425)}: {info.get('active_cons', '0')}")
        lines.append(
            f"{_t(30426)}: {_t(30430) if info.get('is_trial') == '1' else _t(30431)}"
        )
        lines.append(f"{_t(30427)}: {info.get('server_url', 'N/A')}")
        lines.append("[COLOR gray]────────────────────[/COLOR]")
    if not has_any:
        xbmcgui.Dialog().ok("Xstream Pro", _t(30056))
        return
    xbmcgui.Dialog().textviewer(_t(30019), "\n".join(lines).rstrip())


def _validate_settings():
    return _user_settings._validate_settings()



def _snapshot_credentials():
    return _user_settings._snapshot_credentials()



def _detect_credential_changes(snapshot):
    return _user_settings._detect_credential_changes(snapshot)



def _is_pvr_profile(pnum):
    return _user_settings._is_pvr_profile(pnum)



def _prompt_load_single_profile(pnum):
    return _user_settings._prompt_load_single_profile(pnum)



def _prompt_load_multiple_profiles(changed_profiles):
    return _user_settings._prompt_load_multiple_profiles(changed_profiles)



def _prompt_sync_pvr_if_needed(loaded_profiles):
    return _user_settings._prompt_sync_pvr_if_needed(loaded_profiles)



def _snapshot_pvr_replay_settings():
    return _user_settings._snapshot_pvr_replay_settings()



def settings():
    return _user_settings.settings()



def _prompt_load_profiles_after_restore():
    return _user_settings._prompt_load_profiles_after_restore()



def _make_epg_info(epg, channel_id, channel_name, epg_aliases=None):
    lookup_id = str(channel_id or "").strip()
    if epg_aliases:
        lookup_id = epg_aliases.get(lookup_id, lookup_id)
    matched_id = epg._find_channel_id(lookup_id, channel_name)
    if not matched_id:
        return "", channel_name, ""
    now = time.time()
    upcoming = []
    current_title = ""
    current_desc = ""
    # Fast O(log m) lookup using bisect on pre-sorted timestamps
    starts = epg._program_starts.get(matched_id, [])
    prog_list = epg.programs.get(matched_id, [])
    if starts and prog_list:
        import bisect
        # Reverse the offset so we can search raw timestamps directly
        offset_now = now - (epg.offset_hours * 3600)
        idx = bisect.bisect_right(starts, offset_now) - 1
        if 0 <= idx < len(prog_list):
            current_prog = prog_list[idx]
            stop = epg._apply_offset(_parse_xmltv_time(current_prog["stop"]))
            if stop > now:
                upcoming.append(current_prog)
                current_title = current_prog["title"]
                current_desc = current_prog.get("desc", "")
        # Append future programs (up to 7 more, or 8 if no current)
        future_start = idx + 1 if idx >= 0 else 0
        upcoming.extend(prog_list[future_start:future_start + 8])
        upcoming = upcoming[:8]
    else:
        # Fallback to linear scan if bisect data is unavailable
        for prog in epg.programs.get(matched_id, []):
            start = epg._apply_offset(_parse_xmltv_time(prog["start"]))
            stop = epg._apply_offset(_parse_xmltv_time(prog["stop"]))
            if start and start > now:
                upcoming.append(prog)
            elif start and start <= now < stop:
                upcoming.insert(0, prog)
                current_title = prog["title"]
                current_desc = prog.get("desc", "")
        upcoming = upcoming[:8]
    if current_title:
        if current_desc:
            clean_desc = current_desc.replace("\n", " ").replace("\r", " ").strip()
            if len(clean_desc) > 150:
                clean_desc = clean_desc[:147] + "..."
            display_name = f"[B]{channel_name}[/B]  -  {current_title}: {clean_desc}"
        else:
            display_name = f"[B]{channel_name}[/B]  -  {current_title}"
    else:
        display_name = f"[B]{channel_name}[/B]"
    plot_lines = []
    for idx, prog in enumerate(upcoming):
        t = _parse_xmltv_time(prog["start"])
        stop_t = _parse_xmltv_time(prog["stop"])
        is_current = idx == 0 and t and stop_t and t <= now < stop_t
        if t:
            time_str = time.strftime("%H:%M", time.localtime(t))
            line = f"{time_str} - {prog['title']}"
        else:
            line = prog["title"]
        if is_current:
            line = f"[B][COLOR yellow]> {line}[/COLOR][/B]"
        plot_lines.append(line)
    plot = "\n".join(plot_lines)
    return plot, display_name, current_title


def _read_backup_folder():
    return _user_backup.read_backup_folder()


def view_backup_path():
    return _user_backup.view_backup_path()


def change_backup_folder():
    return _user_backup.change_backup_folder()


def change_download_folder():
    dialog = xbmcgui.Dialog()
    chosen = dialog.browseSingle(3, _t(30960), "", "", False, False, "")
    if not chosen:
        return
    try:
        os.makedirs(chosen, exist_ok=True)
        test_path = os.path.join(chosen, ".xstream_write_test")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
            f.flush()
            _safe_fsync(f)
        os.remove(test_path)
    except Exception as e:
        _log(f"Download folder is not writable: {e}")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30082), xbmcgui.NOTIFICATION_ERROR)
        return
    addon.setSetting("download_folder", chosen)
    addon.setSetting("download_folder_display", chosen)
    xbmcgui.Dialog().notification("Xstream Pro", _t(31075))


def backup_settings():
    return _user_backup.backup_settings()



def _finalize_restore(profile_path, manifest=None):
    return _user_backup.finalize_restore(profile_path, manifest=manifest)


def restore_settings():
    return _user_backup.restore_settings()


def clear_provider_metadata_cache():
    """Clear provider metadata caches: vod_info and playback_duration only.
    Navigation caches (data_cache_*) are handled by Profiles cache."""
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    count = 0
    for fname in os.listdir(profile_path):
        if (
            fname.startswith("vod_info_")
            or fname.startswith("playback_duration_")
        ):
            try:
                os.remove(os.path.join(profile_path, fname))
                count += 1
            except Exception as e:
                _log(f"clear_provider_metadata_cache remove warning: {e}")
    xbmcgui.Dialog().notification("Xstream Pro", _t(30890, count))


def clear_cache_menu():
    options = [
        _t(30500),  # Profiles cache
        _t(30501),  # EPG cache
        _t(30891),  # Provider metadata cache
        _t(30772),  # Search history
        _t(30506),  # Kodi cache
        "Clear Trakt cache",
    ]
    dialog = xbmcgui.Dialog()
    choice = dialog.select(_t(30153), options)
    if choice < 0:
        return
    if choice == 0:
        options = [_t(30771)]  # All Profiles
        for i in range(1, 11):
            name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
            options.append(name)
        idx = dialog.select(_t(30500), options)
        if idx < 0:
            return
        if dialog.yesno(_t(30042), _t(30500)):
            if idx == 0:
                clear_all_caches()
            else:
                count = _cache_clear_profile(idx)
                xbmcgui.Dialog().notification("Xstream Pro", _t(30258, count))
    elif choice == 1:
        options = [_t(30771)]  # All Profiles
        for i in range(1, 11):
            name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
            options.append(name)
        idx = dialog.select(_t(30501), options)
        if idx < 0:
            return
        if dialog.yesno(_t(30042), _t(30501)):
            clear_epg_cache(idx)
    elif choice == 2:
        if dialog.yesno(_t(30042), _t(31133)):
            clear_provider_metadata_cache()
    elif choice == 3:
        _clear_search_history_menu()
    elif choice == 4:
        if dialog.yesno(_t(30042), _t(30506)):
            clear_kodi_cache()
    elif choice == 5:
        _user_tools.trakt_clear_cache_action()


def _clear_search_history_menu():
    """Submenu for clearing search history."""
    dialog = xbmcgui.Dialog()
    options = [
        _t(30773),  # Clear global search history
        _t(30774),  # Clear all profiles search history
    ]
    choice = dialog.select(_t(30772), options)
    if choice < 0:
        return
    if choice == 0:
        if dialog.yesno(_t(30770), _t(30773)):
            try:
                history_path = _search_history_path()
                if os.path.exists(history_path):
                    os.remove(history_path)
                    dialog.notification(_t(30770), _t(30093, _t(31401)))
                else:
                    dialog.notification(_t(30770), _t(30093, _t(31401)))
            except Exception as e:
                _log(f"Error clearing global search history: {e}")
                dialog.notification(_t(30770), _t(30091), xbmcgui.NOTIFICATION_ERROR)
    elif choice == 1:
        if dialog.yesno(_t(30770), _t(30774)):
            try:
                count = 0
                for i in range(1, 11):
                    history_path = _search_history_path(i)
                    if os.path.exists(history_path):
                        os.remove(history_path)
                        count += 1
                profile_count_label = _t(31415 if count == 1 else 31416, count)
                dialog.notification(_t(30770), _t(30093, profile_count_label))
            except Exception as e:
                _log(f"Error clearing profiles search history: {e}")
                dialog.notification(_t(30770), _t(30091), xbmcgui.NOTIFICATION_ERROR)


def clear_all_caches():
    count = _cache_clear_all_profiles()
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    for fname in os.listdir(profile_path):
        if (
            fname.startswith("epg_cache_profile_")
            or fname == "epg_cache.json"
            or fname == "view_prefs.json"
        ):
            try:
                os.remove(os.path.join(profile_path, fname))
                count += 1
            except Exception as e:
                _log(f"clear_all_caches remove warning: {e}")
    xbmcgui.Dialog().notification("Xstream Pro", _t(30258, count))


def clear_epg_cache(pnum=None):
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    count = 0
    for fname in os.listdir(profile_path):
        if fname == "epg_cache.json" or fname.startswith("data_cache_epg"):
            try:
                os.remove(os.path.join(profile_path, fname))
                count += 1
            except Exception as e:
                _log(f"clear_epg_cache remove warning: {e}")
        elif pnum is not None and fname == f"epg_cache_profile_{pnum}.json":
            try:
                os.remove(os.path.join(profile_path, fname))
                count += 1
            except Exception as e:
                _log(f"clear_epg_cache remove warning: {e}")
        elif pnum is None and fname.startswith("epg_cache_profile_"):
            try:
                os.remove(os.path.join(profile_path, fname))
                count += 1
            except Exception as e:
                _log(f"clear_epg_cache remove warning: {e}")
    xbmcgui.Dialog().notification("Xstream Pro", _t(30303, count))


def clear_kodi_cache():
    """Clear Kodi's system cache (thumbnails, temp files, etc.)"""
    dialog = xbmcgui.Dialog()
    if not dialog.yesno(_t(30044), _t(30283)):
        return

    count = 0
    thumbs_path = xbmcvfs.translatePath("special://thumbnails/")
    if os.path.exists(thumbs_path):
        for root, dirs, files in os.walk(thumbs_path):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                    count += 1
                except Exception as e:
                    _log(f"clear_kodi_cache thumbs warning: {e}")

    temp_path = xbmcvfs.translatePath("special://temp/")
    if os.path.exists(temp_path):
        for fname in os.listdir(temp_path):
            fpath = os.path.join(temp_path, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    count += 1
                elif os.path.isdir(fpath):
                    shutil.rmtree(fpath)
                    count += 1
            except Exception as e:
                _log(f"clear_kodi_cache temp warning: {e}")

    cache_path = xbmcvfs.translatePath("special://cache/")
    if os.path.exists(cache_path):
        for fname in os.listdir(cache_path):
            fpath = os.path.join(cache_path, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    count += 1
            except Exception as e:
                _log(f"clear_kodi_cache cache warning: {e}")

    dialog.notification("Xstream Pro", _t(30177, count))


def _extract_quality(name):
    return _live_sources._extract_quality(name)


def _extract_size_bytes(text):
    return _live_sources._extract_size_bytes(text)


def _format_source_size(size_bytes):
    return _live_sources._format_source_size(size_bytes)


def _source_probe_timeout():
    return _live_sources._source_probe_timeout()


def _is_bad_source_name(text):
    return _live_sources._is_bad_source_name(text)


def _safe_probe_redirect(current_url, location):
    return _live_sources._safe_probe_redirect(current_url, location)


def _source_size_from_headers(headers, ranged=False, status_code=0):
    return _live_sources._source_size_from_headers(headers, ranged, status_code)


SOURCE_PROBE_LIMIT = 12
SOURCE_PROBE_DEADLINE_SECONDS = 2.0
SOURCE_PROBE_PER_QUALITY_LIMIT = 6

def _probe_source_size_bytes(url, timeout=None, max_redirects=4):
    return _live_sources._probe_source_size_bytes(url, timeout, max_redirects)


def _probe_source_sizes(results, progress=None):
    return _live_sources._probe_source_sizes(results, progress)



def _sort_source_results(results):
    return _live_sources._sort_source_results(results)


def _prepare_source_results(results, progress=None):
    return _live_sources._prepare_source_results(results, progress)


def _source_result_label(pname, r):
    return _live_sources._source_result_label(pname, r)



_STOP_WORDS = {"the", "a", "an", "and", "of", "in", "on", "at", "to", "for", "with", "from", "by", "is", "it", "or"}


def _normalize_title(title):
    return _live_sources._normalize_title(title)



def _filter_stop_words(word_set):
    return _live_sources._filter_stop_words(word_set)



def _title_match_score(search_title, candidate_name):
    return _live_sources._title_match_score(search_title, candidate_name)



def _search_xtream_vod(creds, title, year=None, tmdb_type='movie', season='', episode='', tmdb_id=''):
    return _live_sources._search_xtream_vod(creds, title, year, tmdb_type, season, episode, tmdb_id)



def _search_live_channels(creds, title, year=None):
    return _live_sources._search_live_channels(creds, title, year)



def _search_m3u_vod(creds, title, year=None):
    return _live_sources._search_m3u_vod(creds, title, year)



def _season_eps_from_info(info, season):
    return _live_sources._season_eps_from_info(info, season)



def _all_eps_from_info(info):
    return _live_sources._all_eps_from_info(info)



def _find_xtream_series_sources(showname, year='', season=''):
    return _live_sources._find_xtream_series_sources(showname, year, season)



def _search_all_profiles_vod(title, year=None, tmdb_type='movie', season='', episode='', tmdb_id='', progress=None):
    return _live_sources._search_all_profiles_vod(title, year, tmdb_type, season, episode, tmdb_id, progress)



def _tmdb_return_url(tmdb_type):
    return _live_sources._tmdb_return_url(tmdb_type)



def _return_to_xstream_tmdb_menu(tmdb_type):
    return _live_sources._return_to_xstream_tmdb_menu(tmdb_type)



def _select_source_result(results):
    return _live_sources._select_source_result(results)



def _source_progress_update(progress, heading, found_count=0, percent=0):
    return _live_sources._source_progress_update(progress, heading, found_count, percent)



def _source_progress_close(progress):
    return _live_sources._source_progress_close(progress)



def _source_auto_play_first_enabled():
    return _live_sources._source_auto_play_first_enabled()



def _source_result_exact_tmdb_match(result, tmdb_id):
    return _live_sources._source_result_exact_tmdb_match(result, tmdb_id)



def _pick_autoplay_source(results, tmdb_id):
    return _live_sources._pick_autoplay_source(results, tmdb_id)



def _source_result_play_url(pnum, r, title, tmdb_type, tmdb_id):
    return _live_sources._source_result_play_url(pnum, r, title, tmdb_type, tmdb_id)



def _play_source_result(selected, title, tmdb_type, tmdb_id):
    return _live_sources._play_source_result(selected, title, tmdb_type, tmdb_id)



def tmdb_source_action():
    return _live_sources.tmdb_source_action()



def source_select():
    return _live_sources.source_select()



def resolve_source():
    return _live_sources.resolve_source()



def tmdb_series_action():
    return _live_sources.tmdb_series_action()


def _init_menus_hidden_module(module):
    module.init(addon, addon_handle, _log, pm, _t,
                _get_credentials_for_profile,
                _get_cached_m3u_channels,
                _get_cached_xtream_categories,
                _get_cached_xtream_streams,
                _m3u_has_credentials,
                _refresh_profile_data,
                _is_pvr_profile,
                _is_pvr_iptvsimple_installed_or_disabled,
                _sync_pvr_force,
                _tvos_sleep)


def _init_menus_recent_module(module):
    module.init(addon, addon_handle, _log, pm, _t, _prepare_playback_item)


def _init_menus_favorites_module(module):
    module.init(
        addon, addon_handle, _log, pm, _t, fav,
        _get_profile_fav, _invalidate_profile_fav,
        _addon_fanart, _menu_art, _new_listitem,
        _is_adult_category, _epg_enabled, EPG,
        _set_live_props, _make_epg_info, _prepare_playback_item,
    )


def _init_user_tools_module(module):
    module.init(
        addon, addon_handle, _log, _t, _new_listitem,
        _addon_fanart, _local_icon, build_url, _check_pin,
        _get_pvr_profile_num, _get_sports_pvr_profile_num,
        _pvr_m3u_path, _sports_pvr_m3u_path, _m3u_file_has_channels,
        _profile_has_data, _pvr_health_report, _tvos_sleep, _restart_or_prompt,
    )


def _init_user_profiles_module(module):
    module.init(
        addon, addon_handle, pm, _log, _t, _new_listitem,
        _local_icon, _addon_fanart,
        _refresh_all_profiles_with_progress, _refresh_profile_data,
        _prompt_profile_credentials, _m3u_has_credentials, _m3u_simple_menu,
        _profile_section_visible, _pvr_m3u_path, _m3u_file_has_channels,
        _get_pvr_profile_num, _unload_pvr, _sync_pvr_force, _purge_profile_data,
        _main_menu_available_item_labels, _main_menu_item_visible,
        _MAIN_MENU_MANAGED_KEYS, _MAIN_MENU_CUSTOMIZED_KEY,
    )


def _init_pvr_scope_module(module):
    module.init(
        addon, _log, _tvos_sleep,
        _is_pvr_iptvsimple_installed_or_disabled, prompt_install_pvr,
        _m3u_file_has_channels, _role_has_instance,
        _pvr_instance_matches_paths,
        _configure_pvr_iptvsimple, _configure_sports_pvr_instance,
        _configure_pvr_favs_instance, _configure_sports_pvr_favs_instance,
        _set_owned_pvr_instance_enabled, _owned_pvr_instance_enabled,
        _schedule_sports_epg_repair, _schedule_live_epg_repair,
        epg_file_has_data, _prompt_restart_once,
    )


def _init_pvr_health_module(module):
    module.init(
        addon, _log, _parse_xmltv_time,
        _m3u_file_has_channels, epg_file_has_data,
        _role_has_instance, _pvr_instance_matches_paths,
        _get_pvr_instance_id, _owned_pvr_instance_enabled,
    )


def _init_pvr_export_module(module):
    module.init(
        addon, _log, pm, _safe_fsync, _atomic_write_text,
        epg_file_has_data, EPG, _parse_xmltv_time,
        IPTV.build_xtream_stream_url, _m3u_safe, build_m3u_content,
        _get_hidden_subcats, _get_hidden_items, _is_adult_category,
        _get_pvr_credentials, _m3u_has_credentials,
        _get_cached_m3u_channels, _get_cached_xtream_streams, _get_cached_xtream_categories,
        _m3u_extinf_attr,
        _get_pvr_catchup_correction_mode, _catchup_correction_for_channel,
        _sports_pvr_source_channels, _apply_pvr_catchup_corrections,
        _profile_has_epg_fallback_source, _load_epg_for_fallback_profile,
        _setup_sports_routes, _sports_routes,
        _epg_exact_program_id, _epg_fallback_source_targets_for_profile,
        _epg_fallback_profile_state_signature, _get_setting_direct,
    )


def _init_router_module(module):
    module.init({
        "setup_tmdb_routes": _setup_tmdb_routes,
        "get_tmdb_routes": _get_tmdb_routes_module,
        "setup_sports_routes": _setup_sports_routes,
        "get_sports_routes": lambda: _sports_routes,
        "setup_sports_results_routes": _setup_sports_results_routes,
        "get_sports_results_routes": lambda: _sports_results_routes,
        "get_downloader_module": _get_downloader_module,
        "get_user_tools_module": lambda: _user_tools,
        "get_user_profiles_module": lambda: _user_profiles,
        "get_pvr_favorites_module": lambda: _pvr_favorites,
        "get_user_profile_refresh_module": lambda: _user_profile_refresh,
        "get_pvr_sync_module": lambda: _pvr_sync,
        "get_user_settings_module": lambda: _user_settings,
        "get_provider_availability_module": lambda: _provider_availability,
        "get_user_artwork_module": lambda: _user_artwork,
        "get_user_backup_module": lambda: _user_backup,
        "get_live_browse_module": lambda: _live_browse,
        "get_live_menus_module": lambda: _live_menus,
        "get_live_playback_module": lambda: _live_playback,
        "get_live_replay_module": lambda: _live_replay,
        "get_live_search_module": lambda: _live_search,
        "get_live_sources_module": lambda: _live_sources,
        "get_menus_favorites_module": lambda: _menus_favorites,
        "get_menus_hidden_module": lambda: _menus_hidden,
        "get_menus_recent_module": lambda: _menus_recent,
        "normalize_tmdb_type": _normalize_tmdb_type,
        "change_download_folder": change_download_folder,
        "build_url": build_url,
        "_log": _log,
        "open_pvr": open_pvr,
        "open_pvr_guide": open_pvr_guide,
        "_pvr_favs_load_all": _pvr_favs_load_all,
        "_pvr_favs_save_all": _pvr_favs_save_all,
        "_pvr_favs_add": _pvr_favs_add,
        "_pvr_favs_remove": _pvr_favs_remove,
        "_sync_pvr_favorites_safe": _sync_pvr_favorites_safe,
        "_get_pvr_credentials": _get_pvr_credentials,
        "_get_cached_xtream_streams": _get_cached_xtream_streams,
        "_tvos_sleep": _tvos_sleep,
        "_restart_or_prompt": _restart_or_prompt,
        "user_playlists_menu": user_playlists_menu,
        "test_connection": test_connection,
        "account_info": account_info,
        "clear_cache_menu": clear_cache_menu,
        "clear_epg_cache": clear_epg_cache,
        "reset_pvr_epg_db_action": reset_pvr_epg_db_action,
        "_sync_pvr_epg_only": _sync_pvr_epg_only,
        "_sync_pvr_force": _sync_pvr_force,
        "_cache_clear_all": _cache_clear_all,
        "_select_profile_or_all": _select_profile_or_all,
        "_current_pvr_instance_scope": _current_pvr_instance_scope,
        "_get_pvr_profile_num": _get_pvr_profile_num,
        "_get_sports_pvr_profile_num": _get_sports_pvr_profile_num,
        "EPG": EPG,
        "_export_pvr_epg": _export_pvr_epg,
        "_export_sports_pvr_m3u": _export_sports_pvr_m3u,
        "_export_sports_pvr_epg_for_profile": _export_sports_pvr_epg_for_profile,
        "_trigger_pvr_epg_reload": _trigger_pvr_epg_reload,
    })


_menus_main.init(
    addon, addon_handle, pm, _log, _t,
    _new_listitem, _local_icon, _menu_art, _addon_fanart,
    build_url, _log_route_timing, _session_should_run,
    _safe_sync_pvr_favorites_startup, _run_startup_checks,
    mark_zombie_downloads_failed, _get_setting_direct,
    _restart_or_prompt, _get_pvr_credentials, _get_pvr_profile_num,
    _m3u_has_credentials, _pvr_numbered_label,
    _owned_pvr_instance_enabled, _any_profile_has_credentials,
    _MAIN_MENU_CUSTOMIZED_KEY,
)

if mode is None:
    main_menu()
else:
    _router_handled = _router.dispatch(runtime)
    if not _router_handled:
        _log("Unknown route mode: {0}".format(mode))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
