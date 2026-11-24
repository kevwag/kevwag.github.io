"""PVR path helpers for Xstream Pro addon.

PVR file path builders, instance profile directory, settings path,
path utility helpers, and group label matching.

All functions depend on addon (xbmcaddon.Addon) and xbmcvfs for
profile path resolution. They receive `addon` as a module-level import
from addon.py during initialization via init().


"""

import os
import re

import xbmcvfs

from pvr.constants import (
    PVR_FILE_SLUG,
    PVR_LEGACY_LIVE_PREFIXES,
    PVR_LEGACY_SPORTS_PREFIXES,
    PVR_FAVS_GROUP_PREFIXES,
    PVR_SPORTS_FAVS_GROUP_PREFIXES,
)

_addon = None


def init(addon):
    global _addon
    _addon = addon


def _pvr_iptvsimple_profile_dir():
    return xbmcvfs.translatePath("special://profile/addon_data/pvr.iptvsimple")


def _pvr_instance_settings_path(instance_id):
    return os.path.join(
        _pvr_iptvsimple_profile_dir(),
        f"instance-settings-{instance_id}.xml",
    )


def _path_basename(path):
    return os.path.basename((path or "").replace("\\", "/"))


def _normalized_path(path):
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return os.path.normcase(str(path or ""))


def _is_own_addon_data_path(path):
    if not path:
        return False
    try:
        target = _normalized_path(path)
        profile = _normalized_path(xbmcvfs.translatePath(_addon.getAddonInfo("profile")))
        return os.path.commonpath([target, profile]) == profile
    except Exception:
        return False


def _pvr_role_group_prefixes(role):
    if role == "sports":
        return PVR_LEGACY_SPORTS_PREFIXES
    if role == "sports_favs":
        return PVR_SPORTS_FAVS_GROUP_PREFIXES
    if role == "favs":
        return PVR_FAVS_GROUP_PREFIXES
    return PVR_LEGACY_LIVE_PREFIXES


def _pvr_group_label_matches_role(role, label):
    label = str(label or "").strip()
    if not label:
        return False
    label_lower = label.lower()
    if label_lower in ("all channels", ""):
        return False

    is_favs = label.startswith("\u2605 Favorites - ")
    is_sports_favs = label.startswith("\u2605 Sports Favorites - ")

    if role == "favs":
        return is_favs and not is_sports_favs

    if role == "sports_favs":
        return is_sports_favs

    if role == "sports":
        return any(
            label == prefix.rstrip(" -") or label.startswith(prefix)
            for prefix in PVR_LEGACY_SPORTS_PREFIXES
        )

    if role == "main":
        if is_favs or is_sports_favs:
            return False
        if any(
            label == prefix.rstrip(" -") or label.startswith(prefix)
            for prefix in PVR_LEGACY_SPORTS_PREFIXES
        ):
            return False
        return any(
            label == prefix.rstrip(" -") or label.startswith(prefix)
            for prefix in PVR_LEGACY_LIVE_PREFIXES
        )

    return False


def _pvr_live_group_label(group):
    group = str(group or "General").strip() or "General"
    for pfx in PVR_LEGACY_LIVE_PREFIXES:
        if group.startswith(pfx):
            return group[len(pfx):].strip() or "General"
    if group == "Xstream Pro":
        return "General"
    return group


def _strip_pvr_live_group_prefix(group):
    group = str(group or "").strip()
    for pfx in PVR_LEGACY_LIVE_PREFIXES:
        if group.startswith(pfx):
            return group[len(pfx):].strip() or "General"
    if group == "Xstream Pro":
        return "General"
    return group


def _pvr_m3u_path_for_profile(profile_num):
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    return os.path.join(profile, f"pvr_live_{PVR_FILE_SLUG}_p{profile_num}.m3u8")


def _pvr_m3u_path():
    return _pvr_m3u_path_for_profile(_get_pvr_profile_num())


def _pvr_epg_path():
    return _pvr_epg_path_for_profile(_get_pvr_profile_num())


def _pvr_epg_path_for_profile(profile_num):
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    return os.path.join(profile, f"pvr_epg_{PVR_FILE_SLUG}_p{profile_num}.xml")


def _pvr_favs_path():
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    pvr_profile = _get_pvr_profile_num()
    return os.path.join(profile, f"pvr_favorites_{pvr_profile}.json")


def _pvr_favs_m3u_path():
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    pvr_profile = _get_pvr_profile_num()
    return os.path.join(profile, f"pvr_favorites_{PVR_FILE_SLUG}_p{pvr_profile}.m3u8")


def _pvr_sync_lock_path():
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    return os.path.join(profile, ".pvr_sync_lock")


def _sports_pvr_m3u_path():
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    sports_profile = _get_sports_pvr_profile_num()
    return os.path.join(profile, f"pvr_sports_{PVR_FILE_SLUG}_p{sports_profile}.m3u8")


def _sports_pvr_epg_path_for_profile(profile_num):
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    return os.path.join(profile, f"pvr_sports_epg_{PVR_FILE_SLUG}_p{profile_num}.xml")


def _sports_pvr_epg_path():
    return _sports_pvr_epg_path_for_profile(_get_sports_pvr_profile_num())


def _sports_pvr_favs_path():
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    sports_profile = _get_sports_pvr_profile_num()
    return os.path.join(profile, f"pvr_sports_favorites_{sports_profile}.json")


def _sports_pvr_favs_m3u_path():
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    sports_profile = _get_sports_pvr_profile_num()
    return os.path.join(profile, f"pvr_sports_favorites_{PVR_FILE_SLUG}_p{sports_profile}.m3u8")


def _get_pvr_profile_num():
    raw = _addon.getSetting("active_pvr_profile") or "Profile 1"
    match = re.search(r"(\d+)$", raw)
    return match.group(1) if match else "1"


def _get_sports_pvr_profile_num():
    raw = _addon.getSetting("sports_pvr_profile") or "Active PVR Profile"
    if raw == "Active PVR Profile":
        return _get_pvr_profile_num()
    match = re.search(r"(\d+)$", raw)
    return match.group(1) if match else _get_pvr_profile_num()


def _pvr_epg_refresh_seconds():
    try:
        hours = int(_addon.getSetting("pvr_epg_refresh") or "12")
    except ValueError:
        hours = 12
    return max(1, hours) * 3600