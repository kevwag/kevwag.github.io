"""Fast settings cache and direct settings reader.

Module-level caches persist across addon calls (reuselanguageinvoker=true).
Call init() after addon and log_fn are available.
"""

import os
import threading

import xbmc
import xbmcvfs

_addon = None
_log_fn = None

_FAST_SETTING_CACHE = None
_FAST_DEFAULT_CACHE = None
_FAST_SETTING_MTIME = 0
_SETTINGS_CACHE_LOCK = threading.Lock()

_settings_xml_cache = {"path": None, "mtime": 0, "values": None}


def init(addon, log_fn):
    global _addon, _log_fn
    _addon = addon
    _log_fn = log_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _load_setting_xml_values(path, defaults=False):
    import xml.etree.ElementTree as ET
    values = {}
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        for node in root.findall(".//setting"):
            sid = node.get("id")
            if not sid:
                continue
            if defaults:
                values[sid] = node.get("default", "")
            else:
                values[sid] = node.text if node.text is not None else node.get("value", "")
    except Exception:
        pass
    return values


def _invalidate_fast_setting_cache():
    global _FAST_SETTING_CACHE, _FAST_SETTING_MTIME
    with _SETTINGS_CACHE_LOCK:
        _FAST_SETTING_CACHE = None
        _FAST_SETTING_MTIME = 0


def _get_setting_fast(setting_id, default=""):
    global _FAST_SETTING_CACHE, _FAST_DEFAULT_CACHE, _FAST_SETTING_MTIME
    try:
        with _SETTINGS_CACHE_LOCK:
            try:
                profile_settings = os.path.join(
                    xbmcvfs.translatePath(_addon.getAddonInfo("profile")),
                    "settings.xml",
                )
                current_mtime = os.path.getmtime(profile_settings)
            except OSError:
                current_mtime = 0
            if _FAST_SETTING_CACHE is None or current_mtime != _FAST_SETTING_MTIME:
                _FAST_SETTING_CACHE = _load_setting_xml_values(profile_settings, defaults=False)
                _FAST_SETTING_MTIME = current_mtime
            if _FAST_DEFAULT_CACHE is None:
                default_settings = os.path.join(
                    xbmcvfs.translatePath(_addon.getAddonInfo("path")),
                    "resources",
                    "settings.xml",
                )
                _FAST_DEFAULT_CACHE = _load_setting_xml_values(default_settings, defaults=True)
            if setting_id in _FAST_SETTING_CACHE:
                return _FAST_SETTING_CACHE.get(setting_id, default)
            if setting_id in _FAST_DEFAULT_CACHE:
                return _FAST_DEFAULT_CACHE.get(setting_id, default)
    except Exception:
        pass
    try:
        return _addon.getSetting(setting_id) or default
    except Exception:
        return default


def _get_setting_direct(setting_id, default=""):
    """Read setting directly from settings.xml to bypass Kodi's cache."""
    try:
        profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
        settings_path = os.path.join(profile, "settings.xml")
        if os.path.exists(settings_path):
            mtime = os.path.getmtime(settings_path)
            cache = _settings_xml_cache
            if (
                cache["path"] != settings_path
                or cache["mtime"] != mtime
                or cache["values"] is None
            ):
                import xml.etree.ElementTree as ET

                tree = ET.parse(settings_path)
                root = tree.getroot()
                values = {}
                for setting in root.findall("setting"):
                    sid = setting.get("id")
                    if sid:
                        values[sid] = setting.text or ""
                cache["path"] = settings_path
                cache["mtime"] = mtime
                cache["values"] = values
            if setting_id in cache["values"]:
                return cache["values"][setting_id] or default
    except Exception as e:
        xbmc.log(f"[Xstream Pro] Settings XML read error: {e}", xbmc.LOGWARNING)
    return _addon.getSetting(setting_id) or default


def _invalidate_settings_xml_cache():
    """Force the direct-settings cache to re-read on next call."""
    _settings_xml_cache["path"] = None
    _settings_xml_cache["mtime"] = 0
    _settings_xml_cache["values"] = None

def route_settings_snapshot(defaults):
    """Return a per-route snapshot of non-sensitive setting values.

    defaults must be a dict of setting_id -> default string.
    This helper must not be used for credentials or provider URLs.
    """
    snapshot = {}
    for setting_id, default in (defaults or {}).items():
        snapshot[setting_id] = _get_setting_fast(setting_id, default)
    return snapshot


def route_bool_snapshot(defaults):
    values = route_settings_snapshot(defaults)
    return {
        key: str(value if value is not None else defaults.get(key, "")).lower() == "true"
        for key, value in values.items()
    }

