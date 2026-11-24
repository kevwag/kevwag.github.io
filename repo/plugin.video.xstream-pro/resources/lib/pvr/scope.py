"""PVR scope switching, open guard, and runtime channel helpers.

Call init() after addon module globals are available.
"""

import json
import os
import time

import xbmc
import xbmcgui

from core import kodi as _core_kodi

from pvr.constants import (
    PVR_INSTANCE_NAME,
    PVR_FAVS_INSTANCE_NAME,
    PVR_SPORTS_INSTANCE_NAME,
    PVR_SPORTS_FAVS_INSTANCE_NAME,
)
from pvr.paths import (
    _pvr_m3u_path,
    _pvr_epg_path,
    _pvr_m3u_path_for_profile,
    _pvr_epg_path_for_profile,
    _sports_pvr_m3u_path,
    _sports_pvr_epg_path,
    _sports_pvr_epg_path_for_profile,
    _sports_pvr_favs_m3u_path,
    _pvr_favs_m3u_path,
    _get_pvr_profile_num,
    _get_sports_pvr_profile_num,
    _pvr_epg_refresh_seconds,
    _pvr_role_group_prefixes,
    _pvr_group_label_matches_role,
)

_addon = None
_log_fn = None
_tvos_sleep_fn = None
_is_pvr_iptvsimple_installed_or_disabled_fn = None
_prompt_install_pvr_fn = None
_m3u_file_has_channels_fn = None
_role_has_instance_fn = None
_pvr_instance_matches_paths_fn = None
_configure_pvr_iptvsimple_fn = None
_configure_sports_pvr_instance_fn = None
_configure_pvr_favs_instance_fn = None
_configure_sports_pvr_favs_instance_fn = None
_set_owned_pvr_instance_enabled_fn = None
_owned_pvr_instance_enabled_fn = None
_schedule_sports_epg_repair_fn = None
_schedule_live_epg_repair_fn = None
_epg_file_has_data_fn = None
_prompt_restart_once_fn = None


def init(
    addon,
    log_fn,
    tvos_sleep_fn,
    is_pvr_iptvsimple_installed_or_disabled_fn,
    prompt_install_pvr_fn,
    m3u_file_has_channels_fn,
    role_has_instance_fn,
    pvr_instance_matches_paths_fn,
    configure_pvr_iptvsimple_fn,
    configure_sports_pvr_instance_fn,
    configure_pvr_favs_instance_fn,
    configure_sports_pvr_favs_instance_fn,
    set_owned_pvr_instance_enabled_fn,
    owned_pvr_instance_enabled_fn,
    schedule_sports_epg_repair_fn,
    schedule_live_epg_repair_fn,
    epg_file_has_data_fn,
    prompt_restart_once_fn=None,
):
    global _addon, _log_fn, _tvos_sleep_fn
    global _is_pvr_iptvsimple_installed_or_disabled_fn, _prompt_install_pvr_fn
    global _m3u_file_has_channels_fn, _role_has_instance_fn
    global _pvr_instance_matches_paths_fn
    global _configure_pvr_iptvsimple_fn, _configure_sports_pvr_instance_fn
    global _configure_pvr_favs_instance_fn, _configure_sports_pvr_favs_instance_fn
    global _set_owned_pvr_instance_enabled_fn, _owned_pvr_instance_enabled_fn
    global _schedule_sports_epg_repair_fn, _schedule_live_epg_repair_fn, _epg_file_has_data_fn
    global _prompt_restart_once_fn
    _addon = addon
    _log_fn = log_fn
    _tvos_sleep_fn = tvos_sleep_fn
    _is_pvr_iptvsimple_installed_or_disabled_fn = is_pvr_iptvsimple_installed_or_disabled_fn
    _prompt_install_pvr_fn = prompt_install_pvr_fn
    _m3u_file_has_channels_fn = m3u_file_has_channels_fn
    _role_has_instance_fn = role_has_instance_fn
    _pvr_instance_matches_paths_fn = pvr_instance_matches_paths_fn
    _configure_pvr_iptvsimple_fn = configure_pvr_iptvsimple_fn
    _configure_sports_pvr_instance_fn = configure_sports_pvr_instance_fn
    _configure_pvr_favs_instance_fn = configure_pvr_favs_instance_fn
    _configure_sports_pvr_favs_instance_fn = configure_sports_pvr_favs_instance_fn
    _set_owned_pvr_instance_enabled_fn = set_owned_pvr_instance_enabled_fn
    _owned_pvr_instance_enabled_fn = owned_pvr_instance_enabled_fn
    _schedule_sports_epg_repair_fn = schedule_sports_epg_repair_fn
    _schedule_live_epg_repair_fn = schedule_live_epg_repair_fn
    _epg_file_has_data_fn = epg_file_has_data_fn
    _prompt_restart_once_fn = prompt_restart_once_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _m3u_channel_count(path):
    try:
        count = 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("#EXTINF"):
                    count += 1
        return count
    except Exception as e:
        _log(f"PVR: channel count warning for {os.path.basename(path)}: {e}")
        return 0


def _jsonrpc_call(method, params=None):
    return _core_kodi._jsonrpc_call(method, params=params)


def _pvr_loaded_channel_count():
    try:
        resp = xbmc.executeJSONRPC(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "PVR.GetChannels",
                    "params": {
                        "channelgroupid": "alltv",
                        "properties": ["channelnumber"],
                    },
                    "id": 1,
                }
            )
        )
        result = json.loads(resp).get("result", {})
        return len(result.get("channels", []) or [])
    except Exception as e:
        _log(f"PVR loaded channel count error: {e}")
        return 0


def _pvr_tv_groups():
    data = _jsonrpc_call("PVR.GetChannelGroups", {"channeltype": "tv"})
    groups = data.get("result", {}).get("channelgroups", [])
    return groups if isinstance(groups, list) else []


def _pvr_channels_for_group(group_id):
    params = {
        "channelgroupid": int(group_id) if str(group_id).isdigit() else group_id,
        "properties": ["channelnumber"],
    }
    data = _jsonrpc_call("PVR.GetChannels", params)
    channels = data.get("result", {}).get("channels", [])
    return channels if isinstance(channels, list) else []


def _pvr_group_has_channels(group_id):
    return len(_pvr_channels_for_group(group_id)) > 0


def _pvr_role_loaded_channel_count(role="main"):
    try:
        groups = _pvr_tv_groups()
        seen_channels = set()
        for group in groups:
            label = (group.get("label") or group.get("name") or "").strip()
            group_id = group.get("channelgroupid")
            if group_id is None or not _pvr_group_label_matches_role(role, label):
                continue
            for channel in _pvr_channels_for_group(group_id):
                cid = channel.get("channelid")
                if cid is not None:
                    seen_channels.add(str(cid))
                else:
                    seen_channels.add("{0}:{1}".format(group_id, channel.get("label") or channel.get("channel")))
        return len(seen_channels)
    except Exception as exc:
        _log(f"PVR role channel count warning for {role}: {exc}")
        return 0


def _pvr_runtime_target_count(m3u_path="", min_channels=1):
    expected = _m3u_channel_count(m3u_path) if m3u_path else 0
    if expected > 0:
        return max(min_channels, int(expected * 0.8))
    return min_channels


def _wait_for_pvr_channel_count(
    label="PVR",
    timeout_seconds=25,
    min_channels=1,
    role="main",
    m3u_path="",
):
    start = time.time()
    last_count = 0
    target_count = _pvr_runtime_target_count(m3u_path, min_channels)
    while time.time() - start < timeout_seconds:
        last_count = _pvr_role_loaded_channel_count(role) if role else _pvr_loaded_channel_count()
        if last_count >= target_count:
            _log(f"{label}: Xstream Pro {role} PVR client exposes {last_count} channels")
            return True
        xbmc.sleep(_tvos_sleep_fn(500))
    _log(
        f"{label}: Xstream Pro {role} PVR client still exposes only {last_count} "
        f"channels after {timeout_seconds}s; target={target_count}"
    )
    return False


def _pvr_group_exists_in_kodi(label, retries=8, delay_ms=500):
    try:
        for attempt in range(retries):
            resp = xbmc.executeJSONRPC(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "PVR.GetChannelGroups",
                        "params": {"channeltype": "tv"},
                        "id": 1,
                    }
                )
            )
            result = json.loads(resp).get("result", {})
            groups = result.get("channelgroups", []) or []
            for g in groups:
                glabel = (g.get("label") or g.get("name") or "").strip()
                if glabel == label:
                    return True
            if attempt < retries - 1:
                xbmc.sleep(delay_ms)
    except Exception:
        pass
    return False


def _pvr_group_prefix_exists_in_kodi(prefix, retries=8, delay_ms=500):
    prefix = (prefix or "").strip()
    if not prefix:
        return False
    try:
        for attempt in range(retries):
            resp = xbmc.executeJSONRPC(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "PVR.GetChannelGroups",
                        "params": {"channeltype": "tv"},
                        "id": 1,
                    }
                )
            )
            result = json.loads(resp).get("result", {})
            groups = result.get("channelgroups", []) or []
            for group in groups:
                label = (group.get("label") or group.get("name") or "").strip()
                if label == prefix or label.startswith(prefix + " - "):
                    return True
            if attempt < retries - 1:
                xbmc.sleep(_tvos_sleep_fn(delay_ms))
    except Exception:
        pass
    return False


def _ensure_pvr_instance_paths(scope, label=None, repair=False):
    """Verify PVR instance paths are correct. Never enable/disable instances.

    If repair=True and paths are stale, rewrite owned instance XML.
    Does NOT toggle opposite-scope instances. Does NOT call PVR reload.
    Returns True if paths are valid, False if invalid and unrepairable.
    """
    label = label or ("Sports PVR" if scope == "sports" else "Live TV PVR")

    if scope not in ("main", "sports"):
        _log(f"PVR instance path check: invalid scope {scope}")
        return False

    if not _is_pvr_iptvsimple_installed_or_disabled_fn():
        _prompt_install_pvr_fn()
        return False

    role = "sports" if scope == "sports" else "main"
    required_m3u = _sports_pvr_m3u_path() if scope == "sports" else _pvr_m3u_path()
    expected_epg = _sports_pvr_epg_path() if scope == "sports" else _pvr_epg_path()

    if not _role_has_instance_fn(role):
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Run PVR sync first." if scope == "main" else "Reload Sports PVR first.",
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
        return False

    if not _m3u_file_has_channels_fn(required_m3u):
        _log(f"PVR instance path check: {scope} generated playlist has no channels")
        xbmcgui.Dialog().notification(
            "Xstream Pro", "Run PVR sync first.",
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
        return False

    paths_match = _pvr_instance_matches_paths_fn(role, required_m3u, expected_epg)

    if not paths_match:
        if repair:
            _log(f"PVR instance path check: {scope} paths stale; rewriting owned instance")
            if scope == "sports":
                _configure_sports_pvr_instance_fn(enabled=True)
            else:
                _configure_pvr_iptvsimple_fn()
            paths_now = _pvr_instance_matches_paths_fn(role, required_m3u, expected_epg)
            if not paths_now:
                _log(f"PVR instance path check: {scope} paths still wrong after repair")
                return False
        else:
            _log(f"PVR instance path check: {scope} paths stale; run PVR sync or restart Kodi")
    else:
        _log(f"PVR instance path check: {label} paths valid")

    if _addon.getSetting("pvr_favorites_enabled").lower() != "false":
        if scope == "sports":
            favs_role = "sports_favs"
            favs_m3u = _sports_pvr_favs_m3u_path()
        else:
            favs_role = "favs"
            favs_m3u = _pvr_favs_m3u_path()
        if _m3u_file_has_channels_fn(favs_m3u) and _role_has_instance_fn(favs_role):
            favs_paths_match = _pvr_instance_matches_paths_fn(favs_role, favs_m3u, expected_epg)
            if not favs_paths_match and repair:
                if scope == "sports":
                    _configure_sports_pvr_favs_instance_fn(enabled=True)
                else:
                    _configure_pvr_favs_instance_fn(enabled=True)
            elif not favs_paths_match:
                _log(f"PVR instance path check: {scope} favs paths stale")

    if scope == "sports":
        sports_epg_path = _sports_pvr_epg_path()
        sports_pnum = _get_sports_pvr_profile_num()
        epg_stale = (
            not os.path.exists(sports_epg_path)
            or os.path.getsize(sports_epg_path) == 0
            or not _epg_file_has_data_fn(sports_epg_path)
            or (
                os.path.exists(sports_epg_path)
                and time.time() - os.path.getmtime(sports_epg_path) > _pvr_epg_refresh_seconds()
            )
        )
        if epg_stale:
            _log("Sports PVR: EPG is stale or missing; scheduling background repair")
            _schedule_sports_epg_repair_fn(sports_pnum)

    if scope == "main":
        live_epg_path = _pvr_epg_path()
        live_pnum = _get_pvr_profile_num()
        epg_stale = (
            not os.path.exists(live_epg_path)
            or os.path.getsize(live_epg_path) == 0
            or not _epg_file_has_data_fn(live_epg_path)
            or (
                os.path.exists(live_epg_path)
                and time.time() - os.path.getmtime(live_epg_path) > _pvr_epg_refresh_seconds()
            )
        )
        if epg_stale:
            _log("Live TV PVR: EPG is stale or missing; scheduling background repair")
            _schedule_live_epg_repair_fn(live_pnum)

    return True


def _switch_pvr_instance_scope(scope, label=None, force=False, reload_epg=False):
    """Select Live/Sports PVR scope by updating Xstream-owned instance XML.

    XML changes are restart-required. If any enabled state changes, return
    False so callers do not wait for channels or open Kodi PVR in the same
    session.
    """
    label = label or ("Sports PVR" if scope == "sports" else "Live TV PVR")
    if scope not in ("main", "sports"):
        _log(f"PVR scope switch: invalid scope {scope}")
        return False

    want_role = "sports" if scope == "sports" else "main"
    other_role = "main" if scope == "sports" else "sports"

    want_favs = "sports_favs" if scope == "sports" else "favs"
    other_favs = "favs" if scope == "sports" else "sports_favs"

    want_has = _role_has_instance_fn(want_role)
    other_has = _role_has_instance_fn(other_role)
    want_favs_has = _role_has_instance_fn(want_favs)
    other_favs_has = _role_has_instance_fn(other_favs)

    want_on = bool(_owned_pvr_instance_enabled_fn(want_role)) if want_has else False
    other_on = bool(_owned_pvr_instance_enabled_fn(other_role)) if other_has else False
    want_favs_on = bool(_owned_pvr_instance_enabled_fn(want_favs)) if want_favs_has else False
    other_favs_on = bool(_owned_pvr_instance_enabled_fn(other_favs)) if other_favs_has else False

    want_favs_m3u = _sports_pvr_favs_m3u_path() if scope == "sports" else _pvr_favs_m3u_path()
    want_favs_should_on = want_favs_has and _m3u_file_has_channels_fn(want_favs_m3u)

    if (
        want_on == bool(want_has)
        and other_on is False
        and want_favs_on == bool(want_favs_should_on)
        and other_favs_on is False
    ):
        _log(f"PVR scope switch: already on {scope}, no change needed")
        return _ensure_pvr_instance_paths(scope, label=label, repair=True)

    changed = False
    if want_has and not want_on:
        _set_owned_pvr_instance_enabled_fn(want_role, True, label)
        changed = True
    if other_has and other_on:
        _set_owned_pvr_instance_enabled_fn(other_role, False, label)
        changed = True
    if want_favs_has:
        if want_favs_should_on and not want_favs_on:
            _set_owned_pvr_instance_enabled_fn(want_favs, True, label)
            changed = True
        elif not want_favs_should_on and want_favs_on:
            _set_owned_pvr_instance_enabled_fn(want_favs, False, label)
            changed = True
    if other_favs_has and other_favs_on:
        _set_owned_pvr_instance_enabled_fn(other_favs, False, label)
        changed = True

    if changed:
        _log(f"PVR scope switch: switched to {scope}; restart Kodi before opening PVR")
        _ensure_pvr_instance_paths(scope, label=label, repair=True)
        message = "PVR switched to " + ("Sports" if scope == "sports" else "Live TV") + ". Restart Kodi, then open PVR again."
        if _prompt_restart_once_fn:
            _prompt_restart_once_fn(message, notification=True)
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                message,
                xbmcgui.NOTIFICATION_INFO,
                7000,
            )
        return False

    _log(f"PVR scope switch: already on {scope}, no XML changes needed")
    return _ensure_pvr_instance_paths(scope, label=label, repair=True)


_PVR_OPEN_LOCK_PROP = "xstream_pro.pvr_opening"
_PVR_OPEN_LOCK_STALE_SECONDS = 120


def _pvr_open_guard(scope_label):
    win = xbmcgui.Window(10000)
    raw = win.getProperty(_PVR_OPEN_LOCK_PROP)
    if raw:
        parts = raw.split("|", 1)
        existing_label = parts[0] if parts else raw
        try:
            lock_time = float(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            lock_time = 0
        if lock_time and (time.time() - lock_time) > _PVR_OPEN_LOCK_STALE_SECONDS:
            _log(f"PVR open guard: stale lock from {existing_label}, reclaiming")
        else:
            _log(f"PVR open guard: {scope_label} blocked - {existing_label} already in progress")
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                f"{existing_label} is loading, please wait.",
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
            return False
    win.setProperty(_PVR_OPEN_LOCK_PROP, f"{scope_label}|{time.time()}")
    _log(f"PVR open guard: {scope_label} claimed lock")
    return True


def _pvr_open_release():
    try:
        xbmcgui.Window(10000).clearProperty(_PVR_OPEN_LOCK_PROP)
        _log("PVR open guard: lock released")
    except Exception as exc:
        _log(f"PVR open guard: release failed: {exc}")


def _ensure_pvr_runtime_channels(
    label,
    m3u_path,
    min_channels=1,
    required_group_prefix="",
    role="main",
):
    target_count = _pvr_runtime_target_count(m3u_path, min_channels)
    count = _pvr_role_loaded_channel_count(role)
    group_ready = True
    if required_group_prefix:
        group_ready = _pvr_group_prefix_exists_in_kodi(
            required_group_prefix,
            retries=1,
            delay_ms=0,
        )
    if count >= target_count and group_ready:
        return True
    if not _m3u_file_has_channels_fn(m3u_path):
        _log(f"{label}: generated playlist has no channels; cannot prepare PVR runtime")
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Run PVR sync first.",
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )
        return False

    _log(
        f"{label}: Xstream Pro {role} runtime has count={count}, "
        f"target={target_count}, group_ready={group_ready}; waiting for channels"
    )
    waited_ok = _wait_for_pvr_channel_count(
        label, timeout_seconds=15, min_channels=target_count, role=role, m3u_path=m3u_path,
    )
    if waited_ok:
        return True

    _log(
        f"{label}: Xstream Pro {role} channels are not visible in Kodi PVR; "
        "restart required before opening PVR"
    )
    xbmcgui.Dialog().notification(
        "Xstream Pro",
        "Restart Kodi, then open PVR again.",
        xbmcgui.NOTIFICATION_WARNING,
        7000,
    )
    return False


def _ensure_pvr_runtime_channels_with_count(
    label,
    m3u_path,
    min_channels=1,
    required_group_prefix="",
    role="main",
):
    target_count = _pvr_runtime_target_count(m3u_path, min_channels)
    count = _pvr_role_loaded_channel_count(role)
    group_ready = True
    if required_group_prefix:
        group_ready = _pvr_group_prefix_exists_in_kodi(
            required_group_prefix,
            retries=1,
            delay_ms=0,
        )
    if count >= target_count and group_ready:
        return True, count
    if not _m3u_file_has_channels_fn(m3u_path):
        _log(f"{label}: generated playlist has no channels; cannot prepare PVR runtime")
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Run PVR sync first.",
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )
        return False, 0

    _log(
        f"{label}: Xstream Pro {role} runtime has count={count}, "
        f"target={target_count}, group_ready={group_ready}; waiting for channels"
    )
    waited_ok = _wait_for_pvr_channel_count(
        label, timeout_seconds=15, min_channels=target_count, role=role, m3u_path=m3u_path,
    )
    count = _pvr_role_loaded_channel_count(role)
    if not waited_ok:
        _log(
            f"{label}: Xstream Pro {role} channels are not visible in Kodi PVR; "
            "restart required before opening PVR"
        )
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Restart Kodi, then open PVR again.",
            xbmcgui.NOTIFICATION_WARNING,
            7000,
        )
    return waited_ok, count


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
    """Wait until Kodi exposes channels/groups. Do not wait for EPG."""

    target_count = _pvr_runtime_target_count(m3u_path, min_channels)

    def ready_now():
        if preloaded_count is not None and preloaded_count >= target_count:
            if required_group_label and not _pvr_group_exists_in_kodi(required_group_label, retries=1, delay_ms=0):
                return False, preloaded_count
            if required_group_prefix and not _pvr_group_prefix_exists_in_kodi(required_group_prefix, retries=1, delay_ms=0):
                return False, preloaded_count
            return True, preloaded_count
        count = _pvr_role_loaded_channel_count(role) if role else _pvr_loaded_channel_count()
        if count < target_count:
            return False, count
        if required_group_label and not _pvr_group_exists_in_kodi(required_group_label, retries=1, delay_ms=0):
            return False, count
        if required_group_prefix and not _pvr_group_prefix_exists_in_kodi(required_group_prefix, retries=1, delay_ms=0):
            return False, count
        return True, count

    ready, count = ready_now()
    if ready:
        _log(f"{label}: Xstream Pro {role} PVR channel list already ready with {count} channels (no wait needed)")
        return True

    progress = None
    if show_progress:
        try:
            progress = xbmcgui.DialogProgress()
            progress.create("Xstream Pro", f"{label} is loading channels...")
        except Exception:
            progress = None

    try:
        start = time.time()
        while time.time() - start < timeout_seconds:
            if progress and progress.iscanceled():
                _log(f"{label}: user cancelled wait for PVR channels")
                return False

            ready, count = ready_now()
            if ready:
                _log(f"{label}: Xstream Pro {role} PVR channel list ready with {count} channels")
                if progress:
                    progress.update(100, f"{label} is ready. Opening channels...")
                    xbmc.sleep(_tvos_sleep_fn(200))
                return True

            if progress:
                elapsed = int(time.time() - start)
                pct = min(95, max(5, int((elapsed / float(timeout_seconds)) * 95)))
                progress.update(pct, f"{label} loading channels... ({elapsed}s)")

            xbmc.sleep(_tvos_sleep_fn(500))

        ready, count = ready_now()
        if ready:
            return True

        if show_progress:
            _log(
                f"{label}: wait timed out; Xstream Pro {role} count={count}, "
                f"target={target_count}; restart required before opening PVR"
            )
            if notify_on_timeout:
                xbmcgui.Dialog().notification(
                    "Xstream Pro",
                    "Restart Kodi, then open PVR again.",
                    xbmcgui.NOTIFICATION_WARNING,
                    7000,
                )
            return False

        _log(
            f"{label}: short wait timed out; Xstream Pro {role} count={count}, "
            f"target={target_count}; restart required before opening PVR"
        )
        if notify_on_timeout:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Restart Kodi, then open PVR again.",
                xbmcgui.NOTIFICATION_WARNING,
                7000,
            )
        return False
    finally:
        if progress:
            try:
                progress.close()
            except Exception:
                pass


def _activate_pvr_window_with_last_group(window_name, scope="live", fallback_label="", role="main"):
    """Open Kodi PVR window at root.

    Group-specific pvr:// paths are unreliable because Kodi group ids can become
    invalid across restarts, PVR reloads, and Live/Sports scope changes.
    """
    try:
        _log(f"PVR group memory: opening {window_name} root for {role}")
    except Exception:
        pass
    xbmc.executebuiltin(f"ActivateWindow({window_name})")
