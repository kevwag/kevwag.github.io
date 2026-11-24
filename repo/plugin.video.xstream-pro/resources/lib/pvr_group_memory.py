import json
import os
import re
import time
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


ADDON_ID = "plugin.video.xstream-pro"
MEMORY_FILE = "pvr_group_memory.json"
SPORTS_PVR_GROUP_PREFIX = "Sports TV - "
SPORTS_LEGACY_PREFIXES = ("Sports TV - ", "Xstream Pro Sports TV - ", "Xstream Pro Sports TV", "Sports TV")
PVR_TV_GROUP_RE = re.compile(r"^pvr://channels/tv/(.+?)@([^/]+)/?$", re.IGNORECASE)
_WIN = xbmcgui.Window(10000)
_WP_LIVE = "xsp_pvr_group_live"
_WP_SPORTS = "xsp_pvr_group_sports"


def _log(message, level=xbmc.LOGINFO):
    try:
        xbmc.log("[Xstream Pro] PVR group memory: {0}".format(message), level)
    except Exception:
        pass


def _profile_dir():
    addon = xbmcaddon.Addon(ADDON_ID)
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    return profile


def _memory_path():
    return os.path.join(_profile_dir(), MEMORY_FILE)


def _read_memory():
    path = _memory_path()
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log("could not read memory file: {0}".format(exc), xbmc.LOGWARNING)
        return {}


def _write_memory(data):
    path = _memory_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            f.flush()
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _parse_tv_group_path(path):
    path = (path or "").strip()
    match = PVR_TV_GROUP_RE.match(path)
    if not match:
        return None
    raw_label = match.group(1)
    group_id = match.group(2)
    label = urllib.parse.unquote(raw_label).strip()
    if not label:
        return None
    return {
        "label": label,
        "group_id": str(group_id),
        "path": path,
    }


def _is_real_group(group):
    if not group:
        return False
    label = (group.get("label") or "").strip().lower()
    group_id = str(group.get("group_id") or "").strip()
    if not label:
        return False
    if label == "all channels" or group_id == "-1" or group_id.lower() == "alltv":
        return False
    return True


def _scope_for_label(label):
    label = (label or "").strip()
    for prefix in SPORTS_LEGACY_PREFIXES:
        if label == prefix.rstrip(" -") or label.startswith(prefix):
            return "sports"
    return "live"

def _wp_key(scope):
    return _WP_SPORTS if str(scope).lower() == "sports" else _WP_LIVE


def _set_group_wp(scope, data):
    try:
        _WIN.setProperty(_wp_key(scope), json.dumps(data) if data else "")
    except Exception:
        pass


def _get_group_wp(scope):
    try:
        raw = _WIN.getProperty(_wp_key(scope))
        if raw:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _memory_key(scope):
    return "last_sports_group" if str(scope).lower() == "sports" else "last_live_group"


def remember_current_pvr_group():
    """Remember the current native TV PVR group, if Kodi exposes one."""
    try:
        path = xbmc.getInfoLabel("Container.FolderPath") or ""
    except Exception:
        return False

    group = _parse_tv_group_path(path)
    if not _is_real_group(group):
        return False

    scope = _scope_for_label(group["label"])
    key = _memory_key(scope)
    current = _get_group_wp(scope)
    if current.get("label") == group["label"] and current.get("path") == group["path"]:
        return False

    entry = {
        "label": group["label"],
        "group_id": group["group_id"],
        "path": group["path"],
        "updated": int(time.time()),
    }

    _set_group_wp(scope, entry)

    try:
        data = _read_memory()
        data[key] = entry
        data["last_tv_group"] = entry
        _write_memory(data)
        _log("remembered {0} group: {1}".format(scope, group["label"]))
        return True
    except Exception as exc:
        _log("could not write memory file: {0}".format(exc), xbmc.LOGWARNING)
        return False


def _jsonrpc(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
    except Exception:
        return {}


def _resolve_group_path(label, retries=12, delay_ms=500):
    label = (label or "").strip()
    if not label:
        return ""
    for attempt in range(retries):
        response = _jsonrpc("PVR.GetChannelGroups", {"channeltype": "tv"})
        groups = (
            response.get("result", {}).get("channelgroups", [])
            if isinstance(response, dict)
            else []
        )
        if groups:
            for group in groups:
                current_label = (group.get("label") or group.get("name") or "").strip()
                if current_label != label:
                    continue
                group_id = group.get("channelgroupid")
                if group_id is None:
                    continue
                encoded = urllib.parse.quote(current_label, safe="")
                return "pvr://channels/tv/{0}@{1}/".format(encoded, group_id)
        if attempt < retries - 1:
            xbmc.sleep(delay_ms)
    return ""

def _stored_group(scope):
    group = _get_group_wp(scope)
    if group:
        return group
    data = _read_memory()
    key = _memory_key(scope)
    group = data.get(key) if isinstance(data.get(key), dict) else {}

    if not group:
        legacy = data.get("last_tv_group") if isinstance(data.get("last_tv_group"), dict) else {}
        if legacy and _scope_for_label(legacy.get("label")) == str(scope).lower():
            group = legacy
    if group:
        _set_group_wp(scope, group)
    return group if isinstance(group, dict) else {}


def get_last_pvr_group_path(scope="live", fallback_label=""):
    """Compatibility only. Never return Kodi PVR group paths for ActivateWindow.

    Group paths contain Kodi runtime IDs and can become invalid after PVR reloads,
    scope switches, instance changes, or foreign PVR clients. The addon may still
    remember the last label for future display, but code must not open Kodi using
    pvr://channels/tv/<group>@<id>/ paths.
    """
    return ""

def _update_group_path(scope, label, resolved_path):
    parsed = _parse_tv_group_path(resolved_path)
    if not parsed:
        return
    key = _memory_key(scope)
    entry = {
        "label": label,
        "group_id": parsed["group_id"],
        "path": resolved_path,
        "updated": int(time.time()),
    }
    _set_group_wp(scope, entry)
    try:
        data = _read_memory()
        data[key] = entry
        _write_memory(data)
        _log("updated {0} group path: {1}".format(scope, label))
    except Exception as exc:
        _log("could not update group path: {0}".format(exc), xbmc.LOGWARNING)


def get_last_pvr_group_label(scope="live"):
    scope = "sports" if str(scope).lower() == "sports" else "live"
    group = _stored_group(scope)
    return group.get("label") or ""
