"""PVR instance management for Xstream Pro addon.

Instance scanning, XML configuration, ownership checks, scope switching,
and health verification for pvr.iptvsimple instances.

Functions depend on addon (xbmcaddon.Addon) and several helpers from
addon.py (passed via init and lazy imports). Call init() after addon
module globals are available.


"""

import json
import os
import re
import threading
import time
import traceback
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from pvr.constants import (
    PVR_MAIN_INSTANCE_ID,
    PVR_INSTANCE_NAME,
    PVR_FAVS_INSTANCE_NAME,
    PVR_SPORTS_INSTANCE_NAME,
    PVR_SPORTS_FAVS_INSTANCE_NAME,
    PVR_LEGACY_LIVE_PREFIXES,
    PVR_LEGACY_MAIN_NAMES,
    PVR_INSTANCE_SETTINGS,
    PVR_INSTANCE_FALLBACKS,
    PVR_MAIN_INSTANCE_SETTING,
    PVR_FAVS_INSTANCE_SETTING,
)
from pvr.paths import (
    _pvr_iptvsimple_profile_dir,
    _pvr_instance_settings_path,
    _normalized_path,
    _get_pvr_profile_num,
    _get_sports_pvr_profile_num,
    _pvr_m3u_path,
    _pvr_epg_path,
    _pvr_favs_m3u_path,
    _sports_pvr_m3u_path,
    _sports_pvr_epg_path,
    _sports_pvr_favs_m3u_path,
    _pvr_epg_refresh_seconds,
    init as paths_init,
)

_addon = None
_log_fn = None
_m3u_file_has_channels_fn = None
_safe_fsync_fn = None
_epg_file_has_data_fn = None
_t_fn = None

_PVR_SCAN_CACHE = None
_PVR_SCAN_CACHE_TIME = 0.0
_PVR_SCAN_CACHE_TTL = 5.0
_PVR_SCAN_CACHE_LOCK = threading.Lock()


def init(addon, log_fn, m3u_file_has_channels_fn, safe_fsync_fn, epg_file_has_data_fn, t_fn):
    global _addon, _log_fn, _m3u_file_has_channels_fn, _safe_fsync_fn, _epg_file_has_data_fn, _t_fn
    _addon = addon
    _log_fn = log_fn
    _m3u_file_has_channels_fn = m3u_file_has_channels_fn
    _safe_fsync_fn = safe_fsync_fn
    _epg_file_has_data_fn = epg_file_has_data_fn
    _t_fn = t_fn
    paths_init(addon)


def _log(msg):
    return _log_fn(msg)


def _m3u_file_has_channels(path):
    return _m3u_file_has_channels_fn(path)


def _request_pvr_scan(label="PVR"):
    _log(f"{label}: PVR reload skipped; IPTV Simple will reload on next refresh interval. Restart Kodi for immediate effect.")
    return False


def _scan_pvr_instances():
    profile = _pvr_iptvsimple_profile_dir()
    found = {}
    foreign = set()
    try:
        for fname in os.listdir(profile):
            m = re.match(r"instance-settings-(\d+)\.xml$", fname)
            if not m:
                continue
            iid = int(m.group(1))
            role = _pvr_instance_role(os.path.join(profile, fname))
            if role in PVR_INSTANCE_SETTINGS and role not in found:
                found[role] = iid
            else:
                foreign.add(iid)
    except Exception as e:
        _log(f"PVR instance scan warning: {e}")
    return found, foreign


def _scan_pvr_instances_cached():
    global _PVR_SCAN_CACHE, _PVR_SCAN_CACHE_TIME
    with _PVR_SCAN_CACHE_LOCK:
        now = time.monotonic()
        if _PVR_SCAN_CACHE is not None and (now - _PVR_SCAN_CACHE_TIME) < _PVR_SCAN_CACHE_TTL:
            return _PVR_SCAN_CACHE
    result = _scan_pvr_instances()
    with _PVR_SCAN_CACHE_LOCK:
        _PVR_SCAN_CACHE = result
        _PVR_SCAN_CACHE_TIME = time.monotonic()
    return result


def _invalidate_pvr_scan_cache():
    global _PVR_SCAN_CACHE, _PVR_SCAN_CACHE_TIME
    with _PVR_SCAN_CACHE_LOCK:
        _PVR_SCAN_CACHE = None
        _PVR_SCAN_CACHE_TIME = 0.0


def _pvr_instance_role(settings_path):
    try:
        tree = ET.parse(settings_path)
        root = tree.getroot()
        name_el = root.find(".//setting[@id='kodi_addon_instance_name']")
        m3u_el = root.find(".//setting[@id='m3uPath']")
        epg_el = root.find(".//setting[@id='epgPath']")

        name_raw = (name_el.text or "") if name_el is not None else ""
        m3u_raw = (m3u_el.text or "") if m3u_el is not None else ""
        epg_raw = (epg_el.text or "") if epg_el is not None else ""

        name = name_raw.strip().lower()
        m3u = m3u_raw.replace("\\", "/").lower()
        epg = epg_raw.replace("\\", "/").lower()

        own_addon_data = _is_own_addon_data_path(m3u) or _is_own_addon_data_path(epg)

        if name == PVR_INSTANCE_NAME.lower() or name.lower() == "xstream pro - live tv":
            return "main"
        if name == PVR_FAVS_INSTANCE_NAME.lower() or name.lower() == "xstream pro - favorites":
            return "favs"
        if name == PVR_SPORTS_INSTANCE_NAME.lower() or name.lower() == "xstream pro - sports tv":
            return "sports"
        if name == PVR_SPORTS_FAVS_INSTANCE_NAME.lower() or name.lower() == "xstream pro - sports favorites":
            return "sports_favs"

        legacy_main_names = tuple(n.lower() for n in PVR_LEGACY_MAIN_NAMES)
        if name in legacy_main_names and own_addon_data:
            return "main"

        legacy_favs_names = ("xstream pro favorites",)
        if name in legacy_favs_names and own_addon_data:
            return "favs"

        if m3u and own_addon_data:
            if "pvr_sports_" in m3u:
                if "favorites" in m3u or "favs" in m3u:
                    return "sports_favs"
                return "sports"
            if "pvr_favorites_" in m3u or "pvr_favs_" in m3u:
                return "favs"
            if "pvr_live_" in m3u:
                return "main"

        return "foreign"
    except Exception:
        return "foreign"


def _is_own_addon_data_path(path):
    if not path:
        return False
    try:
        from pvr.paths import _normalized_path as _np
        target = _np(path)
        profile = _np(xbmcvfs.translatePath(_addon.getAddonInfo("profile")))
        return os.path.commonpath([target, profile]) == profile
    except Exception:
        return False


def _pvr_instance_is_legacy_xstream(settings_path):
    try:
        tree = ET.parse(settings_path)
        root = tree.getroot()
        name_el = root.find(".//setting[@id='kodi_addon_instance_name']")
        m3u_el = root.find(".//setting[@id='m3uPath']")
        epg_el = root.find(".//setting[@id='epgPath']")

        name_raw = (name_el.text or "") if name_el is not None else ""
        m3u_raw = (m3u_el.text or "") if m3u_el is not None else ""
        epg_raw = (epg_el.text or "") if epg_el is not None else ""

        name = name_raw.strip().lower()
        m3u = m3u_raw.replace("\\", "/").lower()
        epg = epg_raw.replace("\\", "/").lower()
        text = f"{name} {m3u} {epg}"

        current_pro_markers = (
            "addon_data/plugin.video.xstream-pro/",
            "pvr_live_xstream_pro_p",
            "pvr_favorites_xstream_pro_p",
            "pvr_sports_xstream_pro_p",
            "pvr_sports_favorites_xstream_pro_p",
        )
        if any(marker in text for marker in current_pro_markers):
            return False

        old_player_markers = (
            "addon_data/plugin.video.xstream-player/",
            "pvr_live_xstream_player_p",
            "pvr_favorites_xstream_player_p",
            "pvr_sports_xstream_player_p",
            "pvr_sports_favorites_xstream_player_p",
        )
        old_player_pro_markers = (
            "addon_data/plugin.video.xstream-player-pro/",
            "pvr_live_xstream_player_pro",
            "pvr_favorites_xstream_player_pro",
            "pvr_sports_xstream_player_pro",
            "pvr_sports_favorites_xstream_player_pro",
        )

        is_old_xstream = (
            any(marker in text for marker in old_player_markers)
            or any(marker in text for marker in old_player_pro_markers)
            or name.startswith("xstream player")
        )
        if not is_old_xstream:
            return False

        def _missing_local_file(path_value):
            path_value = (path_value or "").strip()
            if not path_value:
                return False
            lower = path_value.lower()
            if lower.startswith(("http://", "https://", "plugin://")):
                return False
            try:
                translated = xbmcvfs.translatePath(path_value) if path_value.startswith("special://") else path_value
            except Exception:
                translated = path_value
            try:
                return not os.path.exists(translated)
            except Exception:
                return False

        return _missing_local_file(m3u_raw) or _missing_local_file(epg_raw)
    except Exception:
        return False


def _cleanup_legacy_xstream_pvr_instances(log_prefix="PVR legacy cleanup"):
    pvr_profile = _pvr_iptvsimple_profile_dir()
    if not os.path.exists(pvr_profile):
        return 0
    removed = 0
    try:
        for fname in os.listdir(pvr_profile):
            if not re.match(r"instance-settings-\d+\.xml$", fname):
                continue
            path = os.path.join(pvr_profile, fname)
            if _pvr_instance_role(path) != "foreign":
                continue
            if not _pvr_instance_is_legacy_xstream(path):
                continue
            try:
                os.remove(path)
                removed += 1
                _log(f"{log_prefix}: removed stale old Xstream IPTV Simple instance {fname}")
            except Exception as exc:
                _log(f"{log_prefix}: failed removing stale old Xstream instance {fname}: {exc}")
    except Exception as exc:
        _log(f"{log_prefix}: scan failed: {exc}")
    if removed:
        _log(f"{log_prefix}: removed {removed} stale old Xstream IPTV Simple instance(s)")
    return removed


def _get_pvr_instance_id(role):
    setting = PVR_INSTANCE_SETTINGS.get(role, PVR_MAIN_INSTANCE_SETTING)
    fallback = PVR_INSTANCE_FALLBACKS.get(role, PVR_MAIN_INSTANCE_ID)
    saved = _addon.getSetting(setting)
    owned, foreign = _scan_pvr_instances_cached()
    if role in owned:
        _addon.setSetting(setting, str(owned[role]))
        return owned[role]
    used = foreign | set(owned.values())
    if saved and saved.isdigit():
        saved_iid = int(saved)
        if saved_iid not in used:
            return saved_iid
    iid = fallback
    while iid in used:
        iid += 1
    _addon.setSetting(setting, str(iid))
    return iid


def _set_owned_pvr_instance_enabled(role, enabled, log_prefix="PVR"):
    settings_path = _pvr_instance_settings_path(_get_pvr_instance_id(role))
    if not os.path.exists(settings_path):
        _log(f"{log_prefix}: {role} instance missing, cannot set enabled={enabled}")
        return False
    if _pvr_instance_role(settings_path) != role:
        _log(f"{log_prefix}: refusing to modify non-owned/non-{role} instance {os.path.basename(settings_path)}")
        return False
    try:
        tree = ET.parse(settings_path)
        root = tree.getroot()
        el = root.find(".//setting[@id='kodi_addon_instance_enabled']")
        if el is None:
            el = ET.SubElement(root, "setting", {"id": "kodi_addon_instance_enabled"})
        desired = "true" if enabled else "false"
        if (el.text or "") == desired and "default" not in el.attrib:
            return True
        el.text = desired
        if "default" in el.attrib:
            del el.attrib["default"]
        tmp_path = settings_path + ".tmp"
        tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
        with open(tmp_path, "r+b") as f:
            try:
                _safe_fsync_fn(f)
            except OSError:
                pass
        os.replace(tmp_path, settings_path)
        _log(f"{log_prefix}: set {role} instance enabled={enabled}")
        return True
    except Exception as e:
        _log(f"{log_prefix}: failed to set {role} instance enabled={enabled}: {e}")
        return False


def _role_has_instance(role):
    path = _pvr_instance_settings_path(_get_pvr_instance_id(role))
    return os.path.exists(path) and _pvr_instance_role(path) == role


def _owned_pvr_instance_enabled(role):
    path = _pvr_instance_settings_path(_get_pvr_instance_id(role))
    if not os.path.exists(path) or _pvr_instance_role(path) != role:
        return None
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        el = root.find(".//setting[@id='kodi_addon_instance_enabled']")
        if el is None:
            return True
        return (el.text or "").strip().lower() != "false"
    except Exception as e:
        _log(f"PVR scope: failed reading {role} enabled state: {e}")
        return None


def _current_pvr_instance_scope():
    main_on = bool(_owned_pvr_instance_enabled("main")) and _m3u_file_has_channels(_pvr_m3u_path())
    favs_on = bool(_owned_pvr_instance_enabled("favs")) and _m3u_file_has_channels(_pvr_favs_m3u_path())
    sports_on = bool(_owned_pvr_instance_enabled("sports")) and _m3u_file_has_channels(_sports_pvr_m3u_path())
    sports_favs_on = bool(_owned_pvr_instance_enabled("sports_favs")) and _m3u_file_has_channels(_sports_pvr_favs_m3u_path())

    main_visible = main_on or favs_on
    sports_visible = sports_on or sports_favs_on
    if main_visible and not sports_visible:
        return "main"
    if sports_visible and not main_visible:
        return "sports"
    if main_visible and sports_visible:
        return "mixed"
    return "none"


def _pvr_scope_dot(scope):
    current = _current_pvr_instance_scope()
    if current == scope:
        color = "green"
    elif current == "mixed":
        color = "yellow"
    else:
        color = "red"
    return "[COLOR {0}]\u25cf[/COLOR]".format(color)


def _pvr_instance_setting_value(role, setting_id):
    path = _pvr_instance_settings_path(_get_pvr_instance_id(role))
    if not os.path.exists(path) or _pvr_instance_role(path) != role:
        return ""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        el = root.find(f".//setting[@id='{setting_id}']")
        return (el.text or "").strip() if el is not None else ""
    except Exception as exc:
        _log(f"PVR scope: failed reading {role} {setting_id}: {exc}")
        return ""


def _pvr_instance_matches_paths(role, expected_m3u, expected_epg=""):
    from pvr.paths import _normalized_path as _np
    actual_m3u = _pvr_instance_setting_value(role, "m3uPath")
    if not actual_m3u or _np(actual_m3u) != _np(expected_m3u):
        return False
    if expected_epg:
        actual_epg = _pvr_instance_setting_value(role, "epgPath")
        if not actual_epg or _np(actual_epg) != _np(expected_epg):
            return False
    return True


def _sports_pvr_instance_matches_current_profile():
    return _pvr_instance_matches_paths(
        "sports",
        _sports_pvr_m3u_path(),
        _sports_pvr_epg_path(),
    )


def _sports_pvr_ready():
    return (
        _role_has_instance("sports")
        and _sports_pvr_instance_matches_current_profile()
        and _m3u_file_has_channels(_sports_pvr_m3u_path())
    )


def _write_pvr_instance_settings(role, instance_name, m3u_path, epg_path, log_prefix="PVR", enabled=True):
    try:
        pvr_profile = _pvr_iptvsimple_profile_dir()
        os.makedirs(pvr_profile, exist_ok=True)
        settings_path = _pvr_instance_settings_path(_get_pvr_instance_id(role))
        try:
            pvr_epg_hours = int(_addon.getSetting("pvr_epg_refresh") or "12")
        except ValueError:
            pvr_epg_hours = 12
        pvr_refresh_mins = min(max(pvr_epg_hours * 60, 10), 120)
        catchup_enabled = _addon.getSetting("pvr_catchup_enabled").lower() == "true"
        updates = {
            "kodi_addon_instance_name": instance_name,
            "kodi_addon_instance_enabled": "true" if enabled else "false",
            "m3uPathType": "0",
            "m3uPath": m3u_path,
            "m3uUrl": "",
            "epgPathType": "0",
            "epgPath": epg_path,
            "epgUrl": "",
            "m3uRefreshMode": "1",
            "m3uRefreshIntervalMins": str(pvr_refresh_mins),
            "logoPathType": "0",
            "logoPath": "",
            "logoBaseUrl": "",
            "catchupEnabled": "true" if catchup_enabled else "false",
            "catchupPlayEpgAsLive": "false",
            "allChannelsCatchupMode": "0",
            "catchupOverrideMode": "0",
            "catchupDays": _addon.getSetting("pvr_catchup_days") or "7",
            "catchupOnlyOnFinishedProgrammes": "false",
            "catchupWatchEpgBeginBufferMins": "0",
            "catchupWatchEpgEndBufferMins": "5",
        }
        if os.path.exists(settings_path):
            tree = ET.parse(settings_path)
            root = tree.getroot()
            changed = False
            stale_keys = {"defaultInputstream", "defaultMimeType", "epgRefreshInterval"}
            for stale in stale_keys:
                el = root.find(f".//setting[@id='{stale}']")
                if el is not None:
                    root.remove(el)
                    changed = True
                    _log(f"{log_prefix}: Removed stale setting '{stale}'")
            for key, val in updates.items():
                el = root.find(f".//setting[@id='{key}']")
                if el is not None:
                    if (el.text or "") != val:
                        el.text = val
                        if "default" in el.attrib:
                            del el.attrib["default"]
                        changed = True
                else:
                    new_el = ET.SubElement(root, "setting", {"id": key})
                    new_el.text = val
                    changed = True
            if changed:
                tmp_path = settings_path + ".tmp"
                tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
                with open(tmp_path, "r+b") as f:
                    try:
                        _safe_fsync_fn(f)
                    except OSError:
                        pass
                os.replace(tmp_path, settings_path)
        else:
            root = ET.Element("settings", {"version": "2"})
            for key, val in updates.items():
                el = ET.SubElement(root, "setting", {"id": key})
                el.text = val
            tmp_path = settings_path + ".tmp"
            ET.ElementTree(root).write(tmp_path, encoding="utf-8", xml_declaration=True)
            with open(tmp_path, "r+b") as f:
                try:
                    _safe_fsync_fn(f)
                except OSError:
                    pass
            os.replace(tmp_path, settings_path)
        _log(f"{log_prefix}: Configured IPTV Simple instance ({os.path.basename(settings_path)})")
        _invalidate_pvr_scan_cache()
        return True
    except Exception as e:
        _log(f"{log_prefix}: Configure IPTV Simple instance failed: {e}")
        _log(f"Traceback: {traceback.format_exc()}")
        return False


def _remove_pvr_instance_config(role, log_prefix, force=False, m3u_path=None):
    if not force and m3u_path and _m3u_file_has_channels(m3u_path):
        _log(f"{log_prefix}: keeping instance because M3U has channels")
        return False
    settings_path = _pvr_instance_settings_path(_get_pvr_instance_id(role))
    try:
        if os.path.exists(settings_path):
            os.remove(settings_path)
            _log(f"{log_prefix}: Removed empty instance {os.path.basename(settings_path)}")
            _invalidate_pvr_scan_cache()
    except Exception as e:
        _log(f"{log_prefix}: instance remove warning: {e}")
        return False
    return True


def _remove_duplicate_pvr_instances(role, keep_id, log_prefix):
    profile = _pvr_iptvsimple_profile_dir()
    keep_name = f"instance-settings-{keep_id}.xml"
    try:
        if not os.path.exists(profile):
            return
        for fname in os.listdir(profile):
            if not fname.startswith("instance-settings-") or not fname.endswith(".xml"):
                continue
            if fname == keep_name:
                continue
            path = os.path.join(profile, fname)
            if _pvr_instance_role(path) == role:
                try:
                    os.remove(path)
                    _log(f"{log_prefix}: Removed duplicate owned instance {fname}")
                    _invalidate_pvr_scan_cache()
                except Exception as e:
                    _log(f"{log_prefix}: duplicate instance remove warning ({fname}): {e}")
    except Exception as e:
        _log(f"{log_prefix}: duplicate instance scan warning: {e}")


def _configure_pvr_iptvsimple():
    m3u_path = _pvr_m3u_path()
    epg_path = _pvr_epg_path()
    return _write_pvr_instance_settings("main", PVR_INSTANCE_NAME, m3u_path, epg_path, "PVR", enabled=True)


def _configure_pvr_favs_instance(enabled=True):
    m3u_path = _pvr_favs_m3u_path()
    if not _m3u_file_has_channels(m3u_path):
        _log("PVR Favorites: no favorite channels, removing PVR Favorites instance")
        _remove_pvr_favs_instance_config()
        return False
    epg_path = _pvr_epg_path()
    return _write_pvr_instance_settings("favs", PVR_FAVS_INSTANCE_NAME, m3u_path, epg_path, "PVR Favorites", enabled=enabled)


def _configure_sports_pvr_instance(enabled=False):
    m3u_path = _sports_pvr_m3u_path()
    if not _m3u_file_has_channels(m3u_path):
        _log("Sports PVR: no channels, removing Sports PVR instance")
        _remove_pvr_instance_config("sports", "Sports PVR", force=True)
        return False
    return _write_pvr_instance_settings(
        "sports",
        PVR_SPORTS_INSTANCE_NAME,
        m3u_path,
        _sports_pvr_epg_path(),
        "Sports PVR",
        enabled=enabled,
    )


def _configure_sports_pvr_favs_instance(enabled=False):
    m3u_path = _sports_pvr_favs_m3u_path()
    if not _m3u_file_has_channels(m3u_path):
        _log("Sports PVR Favorites: no channels, removing instance")
        _remove_pvr_instance_config("sports_favs", "Sports PVR Favorites", force=True)
        return False
    return _write_pvr_instance_settings(
        "sports_favs",
        PVR_SPORTS_FAVS_INSTANCE_NAME,
        m3u_path,
        _sports_pvr_epg_path(),
        "Sports PVR Favorites",
        enabled=enabled,
    )


def _remove_pvr_favs_instance_config(force=False):
    if not force and _m3u_file_has_channels(_pvr_favs_m3u_path()):
        _log("PVR Favorites: keeping instance because favorites M3U has channels")
        return False
    settings_path = _pvr_instance_settings_path(_get_pvr_instance_id("favs"))
    try:
        if os.path.exists(settings_path):
            os.remove(settings_path)
            _log(f"PVR Favorites: Removed empty instance {os.path.basename(settings_path)}")
    except Exception as e:
        _log(f"PVR Favorites: instance remove warning: {e}")
    if _addon.getSetting(PVR_FAVS_INSTANCE_SETTING):
        _addon.setSetting(PVR_FAVS_INSTANCE_SETTING, "")
    try:
        sidecar = os.path.join(
            xbmcvfs.translatePath(_addon.getAddonInfo("profile")),
            ".pvr_fav_verified",
        )
        if os.path.exists(sidecar):
            os.remove(sidecar)
    except Exception:
        pass
    return True


def _is_pvr_iptvsimple_installed_or_disabled():
    try:
        resp = json.loads(
            xbmc.executeJSONRPC(
                '{"jsonrpc":"2.0","method":"Addons.GetAddonDetails","params":{"addonid":"pvr.iptvsimple","properties":["enabled"]},"id":1}'
            )
        )
        if "error" in resp:
            _log(f"PVR: IPTV Simple not installed (JSONRPC error)")
            return False
        enabled = resp.get("result", {}).get("addon", {}).get("enabled", False)
        _log(f"PVR: IPTV Simple found via JSONRPC, enabled={enabled}")
        return True
    except Exception as e:
        _log(f"PVR: IPTV Simple check failed: {e}")
        return False


def _reload_iptv_simple_addon(label="PVR", progress=None, start_percent=80, stop_manager=True):
    _log(f"{label}: PVR reload skipped; IPTV Simple will reload on next refresh interval. Restart Kodi for immediate effect.")
    return False


def _pvr_progress(progress, percent, message):
    if progress is None:
        return
    try:
        progress.update(percent, message)
    except Exception:
        pass
