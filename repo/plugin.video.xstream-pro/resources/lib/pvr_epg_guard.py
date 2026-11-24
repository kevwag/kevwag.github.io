import os
import re
import threading
import time

import xbmc
import xbmcaddon
import xbmcvfs


ADDON_ID = "plugin.video.xstream-pro"
PVR_FILE_SLUG = "xstream_pro"
EMPTY_XMLTV = '<?xml version="1.0" encoding="utf-8"?>\n<tv>\n</tv>\n'
PVR_EPG_RE = re.compile(
    r"^pvr_epg_{0}_p(\d+)\.xml$".format(re.escape(PVR_FILE_SLUG)),
    re.IGNORECASE,
)
SPORTS_PVR_EPG_RE = re.compile(
    r"^pvr_sports_epg_{0}_p(\d+)\.xml$".format(re.escape(PVR_FILE_SLUG)),
    re.IGNORECASE,
)
_RE_PROGRAMME_STOP = re.compile(r'<programme\b[^>]*\bstop="([^"]+)"', re.IGNORECASE)
_EPG_STALE_HOURS = 12


def _log(message, level=xbmc.LOGINFO):
    try:
        xbmc.log("[Xstream Pro] EPG guard: {0}".format(message), level)
    except Exception:
        pass


def _safe_replace(src, dst, retries=5, delay=0.5):
    for attempt in range(1, retries + 1):
        try:
            os.replace(src, dst)
            return
        except (PermissionError, OSError) as exc:
            if attempt < retries:
                _log(
                    "file replace retry {0}/{1} for {2}: {3}".format(
                        attempt, retries, os.path.basename(dst), exc
                    )
                )
                time.sleep(delay * attempt)
            else:
                raise


def _profile_number_from_setting(value):
    match = re.search(r"(\d+)", value or "")
    if not match:
        return None
    try:
        num = int(match.group(1))
    except ValueError:
        return None
    if 1 <= num <= 10:
        return str(num)
    return None


def _candidate_paths(addon, profile_dir):
    paths = set()

    active_raw = addon.getSetting("active_pvr_profile") or "Profile 1"
    active_num = _profile_number_from_setting(active_raw) or "1"
    paths.add(os.path.join(profile_dir, "pvr_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, active_num)))

    sports_raw = addon.getSetting("sports_pvr_profile") or "Active PVR Profile"
    if sports_raw.strip().lower() == "active pvr profile":
        sports_num = active_num
    else:
        sports_num = _profile_number_from_setting(sports_raw)
    if sports_num:
        paths.add(os.path.join(profile_dir, "pvr_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, sports_num)))
        paths.add(os.path.join(profile_dir, "pvr_sports_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, sports_num)))

    try:
        for name in os.listdir(profile_dir):
            if PVR_EPG_RE.match(name) or SPORTS_PVR_EPG_RE.match(name):
                paths.add(os.path.join(profile_dir, name))
    except OSError as exc:
        _log("could not list addon profile directory: {0}".format(exc), xbmc.LOGWARNING)

    return sorted(paths)


def xmltv_header_valid(path):
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return False
        with open(path, "rb") as f:
            head = f.read(512)
        if head.startswith(b"\xef\xbb\xbf"):
            head = head[3:]
        head = head.lstrip()
        if not head:
            return False
        if head.startswith(b"<?xml"):
            close = head.find(b"?>")
            if close < 0:
                return False
            head = head[close + 2 :].lstrip()
        if not (head.startswith(b"<tv>") or head.startswith(b"<tv ")):
            return False
        size = os.path.getsize(path)
        if size < 50:
            return False
        return True
    except Exception:
        return False


def _parse_xmltv_time(raw):
    """Parse XMLTV datetime string like '20260528143000 +0200' to epoch seconds."""
    if not raw:
        return 0
    try:
        cleaned = re.sub(r"[^\d]", "", raw[:14])
        if len(cleaned) < 14:
            return 0
        import calendar
        return calendar.timegm(
            (
                int(cleaned[0:4]),
                int(cleaned[4:6]),
                int(cleaned[6:8]),
                int(cleaned[8:10]),
                int(cleaned[10:12]),
                int(cleaned[12:14]),
            )
        )
    except Exception:
        return 0


def _xmltv_latest_stop_time(path):
    """Scan XMLTV file for the latest programme stop time. Returns epoch seconds or 0."""
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 100:
            return 0
        latest = 0
        carry = ""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                scan = carry + chunk
                carry = scan[-256:]
                for match in _RE_PROGRAMME_STOP.finditer(scan):
                    ts = _parse_xmltv_time(match.group(1))
                    if ts > latest:
                        latest = ts
        return latest
    except Exception:
        return 0


def _lastgood_path(path):
    return path + ".lastgood"


def _save_lastgood(path):
    if not os.path.exists(path):
        return
    try:
        import shutil
        shutil.copy2(path, _lastgood_path(path))
    except Exception:
        pass


def _restore_lastgood(path):
    lg = _lastgood_path(path)
    if not os.path.exists(lg):
        return False
    try:
        import shutil
        shutil.copy2(lg, path)
        _log("restored last-known-good EPG for {0}".format(os.path.basename(path)))
        return True
    except Exception:
        return False


def _write_stub(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp." + str(threading.current_thread().ident)
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(EMPTY_XMLTV)
        try:
            f.flush()
            os.fsync(f.fileno())
        except OSError:
            pass
    _safe_replace(tmp_path, path)


def _backup_invalid(path):
    if not os.path.exists(path):
        return ""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = "{0}.bad_xmltv_{1}".format(path, stamp)
    candidate = base
    index = 1
    while os.path.exists(candidate):
        index += 1
        candidate = "{0}_{1}".format(base, index)
    _safe_replace(path, candidate)
    return candidate


def repair_pvr_epg_files():
    try:
        addon = xbmcaddon.Addon(ADDON_ID)
        if addon is None:
            _log("EPG repair: addon not ready, skipping", xbmc.LOGWARNING)
            return {"repaired": 0, "kept": 0, "failed": 0}
        profile_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    except Exception:
        _log("EPG repair: addon not ready, skipping", xbmc.LOGWARNING)
        return {"repaired": 0, "kept": 0, "failed": 0}
    os.makedirs(profile_dir, exist_ok=True)

    repaired = 0
    kept = 0
    failed = 0

    for path in _candidate_paths(addon, profile_dir):
        name = os.path.basename(path)
        try:
            if xmltv_header_valid(path):
                latest_stop = _xmltv_latest_stop_time(path)
                now = time.time()
                if latest_stop > 0 and latest_stop < now - 3600:
                    _log(
                        "{0} data is stale: latest programme ended {1:.0f}h ago"
                        .format(name, (now - latest_stop) / 3600),
                        xbmc.LOGWARNING,
                    )
                elif latest_stop > 0:
                    _log(
                        "{0} data is fresh: latest programme ends in {1:.0f}h"
                        .format(name, (latest_stop - now) / 3600),
                    )
                _save_lastgood(path)
                kept += 1
                continue

            if os.path.exists(path) and os.path.getsize(path) > 0:
                backup = _backup_invalid(path)
                _log("moved invalid XMLTV {0} to {1}".format(name, os.path.basename(backup)))

            if _restore_lastgood(path) and xmltv_header_valid(path):
                repaired += 1
                _log("restored last-known-good EPG for {0}".format(name))
                continue

            _write_stub(path)
            repaired += 1
            _log("wrote valid XMLTV stub for {0}".format(name))
        except Exception as exc:
            failed += 1
            _log("failed to repair {0}: {1}".format(name, exc), xbmc.LOGWARNING)

    _log("finished; repaired={0} kept={1} failed={2}".format(repaired, kept, failed))
    return {"repaired": repaired, "kept": kept, "failed": failed}


_PREFETCH_MIN_FUTURE_HOURS = 1


def _epg_path_needs_prefetch(path):
    """Return True if EPG data at path is stale enough to warrant synchronous prefetch.

    An EPG file needs prefetch when its latest programme stop time has already
    passed (all data expired) or has less than _PREFETCH_MIN_FUTURE_HOURS of
    future content remaining.
    """
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        return True
    if not xmltv_header_valid(path):
        return True
    latest_stop = _xmltv_latest_stop_time(path)
    if latest_stop <= 0:
        return True
    return latest_stop < time.time() + _PREFETCH_MIN_FUTURE_HOURS * 3600


def prefetch_stale_epg():
    """Synchronously re-export EPG files whose data has expired.

    Called from service.py at Kodi startup after repair_pvr_epg_files().
    Blocks for 10-30 seconds if a network fetch is needed, ensuring fresh
    EPG data is available before the user opens PVR.
    Returns a dict with 'live' and 'sports' keys indicating whether each
    prefetch was attempted and whether it succeeded.
    """
    try:
        addon = xbmcaddon.Addon(ADDON_ID)
        if addon is None:
            _log("EPG prefetch: addon not ready, skipping", xbmc.LOGWARNING)
            return {"live": None, "sports": None}
        profile_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    except Exception:
        _log("EPG prefetch: addon not ready, skipping", xbmc.LOGWARNING)
        return {"live": None, "sports": None}

    active_raw = addon.getSetting("active_pvr_profile") or "Profile 1"
    active_num = _profile_number_from_setting(active_raw) or "1"

    sports_raw = addon.getSetting("sports_pvr_profile") or "Active PVR Profile"
    if sports_raw.strip().lower() == "active pvr profile":
        sports_num = active_num
    else:
        sports_num = _profile_number_from_setting(sports_raw)

    live_epg_path = os.path.join(
        profile_dir, "pvr_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, active_num)
    )
    sports_epg_path = os.path.join(
        profile_dir, "pvr_sports_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, sports_num)
    ) if sports_num else None

    result = {"live": None, "sports": None}

    if _epg_path_needs_prefetch(live_epg_path):
        _log("Live EPG data expired; starting synchronous prefetch")
        try:
            from pvr.export import export_pvr_epg_for_profile, clear_epg_instance_cache
            clear_epg_instance_cache()
            ok = export_pvr_epg_for_profile(active_num, force_fetch=True)
            result["live"] = ok
            _log("Live EPG prefetch {0}".format("completed" if ok else "failed"))
        except Exception as exc:
            _log("Live EPG prefetch error: {0}".format(exc), xbmc.LOGWARNING)
            result["live"] = False
    else:
        _log("Live EPG data has sufficient future coverage; prefetch not needed")
        result["live"] = True

    if sports_num and sports_epg_path and _epg_path_needs_prefetch(sports_epg_path):
        _log("Sports EPG data expired; scheduling background repair")
        try:
            xbmc.executebuiltin(
                "RunPlugin(plugin://plugin.video.xstream-pro/?mode=schedule_sports_epg_repair&profile={0})".format(sports_num)
            )
            result["sports"] = None
        except Exception as exc:
            _log("Sports EPG repair schedule error: {0}".format(exc), xbmc.LOGWARNING)
            result["sports"] = False
    elif sports_epg_path:
        _log("Sports EPG data has sufficient future coverage; prefetch not needed")
        result["sports"] = True

    return result


def _pvr_epg_refresh_seconds():
    """Read the pvr_epg_refresh addon setting and convert to seconds."""
    try:
        addon = xbmcaddon.Addon(ADDON_ID)
        if addon is None:
            return 12 * 3600
        hours = int(addon.getSetting("pvr_epg_refresh") or "12")
    except Exception:
        hours = 12
    return max(1, hours) * 3600


def check_and_schedule_epg_repair():
    """Periodic staleness check for service.py monitor loop.

    Checks each EPG file's modification time; if it exceeds
    pvr_epg_refresh_seconds, schedules a background repair via
    addon module's scheduling functions.
    """
    try:
        addon = xbmcaddon.Addon(ADDON_ID)
        if addon is None:
            _log("EPG periodic check: addon not ready, skipping", xbmc.LOGWARNING)
            return
        profile_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    except Exception:
        _log("EPG periodic check: addon not ready, skipping", xbmc.LOGWARNING)
        return

    active_raw = addon.getSetting("active_pvr_profile") or "Profile 1"
    active_num = _profile_number_from_setting(active_raw) or "1"

    sports_raw = addon.getSetting("sports_pvr_profile") or "Active PVR Profile"
    if sports_raw.strip().lower() == "active pvr profile":
        sports_num = active_num
    else:
        sports_num = _profile_number_from_setting(sports_raw)

    refresh_seconds = _pvr_epg_refresh_seconds()

    live_epg_path = os.path.join(
        profile_dir, "pvr_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, active_num)
    )
    live_stale = (
        not os.path.exists(live_epg_path)
        or os.path.getsize(live_epg_path) == 0
        or time.time() - os.path.getmtime(live_epg_path) > refresh_seconds
    )
    if live_stale:
        _log("Periodic check: Live EPG stale; scheduling background repair")
        try:
            xbmc.executebuiltin(
                "RunPlugin(plugin://plugin.video.xstream-pro/?mode=schedule_live_epg_repair&profile={0})".format(active_num)
            )
        except Exception as exc:
            _log("Periodic check: failed to schedule Live EPG repair: {0}".format(exc), xbmc.LOGWARNING)

    if sports_num:
        sports_epg_path = os.path.join(
            profile_dir, "pvr_sports_epg_{0}_p{1}.xml".format(PVR_FILE_SLUG, sports_num)
        )
        sports_stale = (
            not os.path.exists(sports_epg_path)
            or os.path.getsize(sports_epg_path) == 0
            or time.time() - os.path.getmtime(sports_epg_path) > refresh_seconds
        )
        if sports_stale:
            _log("Periodic check: Sports EPG stale; scheduling background repair")
            try:
                xbmc.executebuiltin(
                    "RunPlugin(plugin://plugin.video.xstream-pro/?mode=schedule_sports_epg_repair&profile={0})".format(sports_num)
                )
            except Exception as exc:
                _log("Periodic check: failed to schedule Sports EPG repair: {0}".format(exc), xbmc.LOGWARNING)
