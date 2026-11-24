"""Background download manager for Xstream Pro.

Uses urllib.request (no extra deps), RunScript standalone workers, JSON state file,
and supports resume via HTTP Range headers.
"""

import json
import os
import re
import sys
import random
import time
import urllib.parse
import urllib.request
import hashlib

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
import xbmcplugin

from lang import _t
from iptv import _validate_url


def _is_tvos():
    if not xbmc.getCondVisibility("System.Platform.OSX"):
        return False
    try:
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
        return "Containers" in profile or "Library/Caches/Kodi" in profile
    except Exception:
        return False


def _safe_fsync(f):
    if _is_tvos():
        return
    try:
        os.fsync(f.fileno())
    except OSError:
        pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen_head_safe(url, timeout=15):
    """HEAD probe with manual redirect loop (max 5 hops)."""
    current = url
    opener = urllib.request.build_opener(_NoRedirectHandler())
    for _ in range(5):
        req = urllib.request.Request(current, method="HEAD")
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.request.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location", "")
                if not loc:
                    raise
                current = urllib.parse.urljoin(current, loc)
                continue
            raise
        return resp
    raise ValueError("HEAD probe redirect loop exceeded 5 hops")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_default_profile_num(addon):
    raw = addon.getSetting("active_pvr_profile") or "Profile 1"
    match = re.search(r"(\d+)$", raw)
    return match.group(1) if match else "1"


def _max_concurrent_downloads(addon=None):
    addon = addon or xbmcaddon.Addon()
    try:
        return max(1, min(5, int(addon.getSetting("max_concurrent_downloads") or "1")))
    except Exception:
        return 1


# ---------------------------------------------------------------------------
# Logging — credential redaction matching addon.py / iptv.py patterns
# ---------------------------------------------------------------------------
_LOG_MAX_LEN = 4000
_LOG_REDACT_PATH_RE = re.compile(
    r"(/(?:live|movie|series)/)([^/?\s]+)(/?)([^/?\s]*)", re.IGNORECASE
)
_LOG_REDACT_QUERY_RE = re.compile(r"(?i)\b(password|pwd|pass|username|user|token|key|apikey|api_key|auth)=([^&\s]+)")


def _log(msg):
    safe = str(msg)
    safe = _LOG_REDACT_PATH_RE.sub(
        lambda m: (
            m.group(1)
            + "***REDACTED***"
            + m.group(3)
            + ("***REDACTED***" if m.group(4) else "")
        ),
        safe,
    )
    safe = _LOG_REDACT_QUERY_RE.sub(r"\1=***REDACTED***", safe)
    if len(safe) > _LOG_MAX_LEN:
        safe = safe[:_LOG_MAX_LEN] + "...[truncated]"
    xbmc.log(f"[Xstream Pro] [DL] {safe}", xbmc.LOGDEBUG)


def _safe_url_for_log(url):
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        if not parsed.scheme:
            return "<url>"
        path = parsed.path or "/"
        if len(path) > 80:
            path = path[:80] + "...[truncated]"
        return "{0}://<redacted-host>{1}".format(parsed.scheme, path)
    except Exception:
        return "<url>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _profile_dir(profile_num):
    addon = xbmcaddon.Addon()
    return xbmcvfs.translatePath(addon.getAddonInfo("profile"))


def _state_path(profile_num):
    return os.path.join(_profile_dir(profile_num), "downloads_state.json")


def _load_state(profile_num):
    path = _state_path(profile_num)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": 1, "downloads": []}


def _save_state(profile_num, state):
    path = _state_path(profile_num)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.flush()
            _safe_fsync(f)
        os.replace(tmp, path)
    except Exception as e:
        _log(f"Failed to save state: {e}")


def _state_lock_path(profile_num):
    return _state_path(profile_num) + ".lock"


def _acquire_state_lock(profile_num, timeout=10.0, stale_after=120.0):
    lock_path = _state_lock_path(profile_num)
    start = time.time()

    while True:
        try:
            os.mkdir(lock_path)
            try:
                with open(os.path.join(lock_path, "owner.txt"), "w", encoding="utf-8") as f:
                    f.write(str(os.getpid()) + "|" + str(time.time()))
            except Exception:
                pass
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path)
                if age > stale_after:
                    try:
                        owner = os.path.join(lock_path, "owner.txt")
                        if os.path.exists(owner):
                            os.remove(owner)
                    except OSError:
                        pass
                    try:
                        os.rmdir(lock_path)
                    except OSError:
                        pass
                    continue
            except Exception:
                pass

            if time.time() - start >= timeout:
                _log("Download state lock timeout for profile {0}".format(profile_num))
                return False

            xbmc.sleep(100)
        except Exception as e:
            _log("Download state lock error: {0}".format(e))
            return False


def _release_state_lock(profile_num):
    lock_path = _state_lock_path(profile_num)
    try:
        owner = os.path.join(lock_path, "owner.txt")
        if os.path.exists(owner):
            os.remove(owner)
    except OSError:
        pass
    try:
        os.rmdir(lock_path)
    except OSError:
        pass


def _state_transaction(profile_num, mutator, save=True):
    if not _acquire_state_lock(profile_num):
        return None

    try:
        state = _load_state(profile_num)
        result = mutator(state)
        if save:
            _save_state(profile_num, state)
        return result
    finally:
        _release_state_lock(profile_num)


def _delete_paths(paths):
    seen = set()
    for path in paths or []:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _sanitize_filename(name):
    """Remove filesystem-illegal chars and collapse whitespace."""
    name = str(name)
    accents = {
        "á": "a", "à": "a", "ä": "a", "â": "a", "ã": "a", "å": "a", "ā": "a",
        "é": "e", "è": "e", "ë": "e", "ê": "e", "ē": "e",
        "í": "i", "ì": "i", "ï": "i", "î": "i", "ī": "i",
        "ó": "o", "ò": "o", "ö": "o", "ô": "o", "õ": "o", "ø": "o", "ō": "o",
        "ú": "u", "ù": "u", "ü": "u", "û": "u", "ū": "u",
        "ý": "y", "ÿ": "y", "ñ": "n", "ç": "c", "č": "c", "ć": "c",
        "š": "s", "ž": "z", "ř": "r", "đ": "d",
        "Á": "A", "À": "A", "Ä": "A", "Â": "A", "Ã": "A", "Å": "A", "Ā": "A",
        "É": "E", "È": "E", "Ë": "E", "Ê": "E", "Ē": "E",
        "Í": "I", "Ì": "I", "Ï": "I", "Î": "I", "Ī": "I",
        "Ó": "O", "Ò": "O", "Ö": "O", "Ô": "O", "Õ": "O", "Ø": "O", "Ō": "O",
        "Ú": "U", "Ù": "U", "Ü": "U", "Û": "U", "Ū": "U",
        "Ý": "Y", "Ÿ": "Y", "Ñ": "N", "Ç": "C", "Č": "C", "Ć": "C",
        "Š": "S", "Ž": "Z", "Ř": "R", "Đ": "D",
    }
    for src, dst in accents.items():
        name = name.replace(src, dst)
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip(". ")
    return name or "download"


def _get_extension(url):
    """Derive file extension from URL path, fallback to mp4."""
    try:
        path = urllib.parse.urlparse(url).path
        ext = os.path.splitext(path)[1][1:].lower()
        if ext in ("mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "ts"):
            return ext
    except Exception:
        pass
    return "mp4"


def _is_hls(url):
    """Returns True if URL is an m3u8 playlist (not supported for download)."""
    try:
        return urllib.parse.urlparse(url).path.endswith(".m3u8")
    except Exception:
        return False


def _get_download_base_dir():
    """Return user-configured or default download folder."""
    addon = xbmcaddon.Addon()
    custom = addon.getSetting("download_folder")
    if custom and os.path.isdir(custom):
        return custom
    if xbmc.getCondVisibility("System.Platform.Android"):
        return "/storage/emulated/0/Download/Xstream Pro"
    return xbmcvfs.translatePath("special://profile/downloads/Xstream Pro")


def _ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass


def _build_folder_path(profile_num, media_type, title, year, season):
    """Build final download folder path."""
    base = _get_download_base_dir()
    prof = f"p{profile_num}"
    if media_type == "episode":
        folder = _sanitize_filename(f"{title} ({year})") if year else _sanitize_filename(title)
        return os.path.join(base, prof, "TV", folder, f"Season {int(season or 1):02d}")
    return os.path.join(base, prof, "Movies")


def _generate_id(url):
    """Simple deterministic ID from URL + current time."""
    raw = f"{url}::{time.time()}::{random.randint(0, 999999)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _write_nfo(folder, filename_noext, metadata):
    """Write a minimal Kodi NFO sidecar so the file is scrapeable."""
    from xml.sax.saxutils import escape
    nfo_path = os.path.join(folder, filename_noext + ".nfo")
    root_tag = "<movie>" if metadata.get("media_type") == "movie" else "<episodedetails>"
    close_tag = "</movie>" if metadata.get("media_type") == "movie" else "</episodedetails>"
    lines = ["<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>", root_tag]
    if metadata.get("title"):
        lines.append(f"  <title>{escape(str(metadata['title']))}</title>")
    if metadata.get("year"):
        lines.append(f"  <year>{escape(str(metadata['year']))}</year>")
    if metadata.get("season"):
        lines.append(f"  <season>{escape(str(metadata['season']))}</season>")
    if metadata.get("episode"):
        lines.append(f"  <episode>{escape(str(metadata['episode']))}</episode>")
    if metadata.get("plot"):
        lines.append(f"  <plot>{escape(str(metadata['plot']))}</plot>")
    lines.append(close_tag)
    try:
        with open(nfo_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def start_download(url, title, year="", media_type="movie", season="", episode="",
                   poster="", plot="", profile_num=None):
    """Queue or start a new download. Returns download ID."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")

    if not _validate_url(url):
        xbmcgui.Dialog().notification("Xstream Pro", _t(30700))
        return None
    if _is_hls(url):
        xbmcgui.Dialog().notification("Xstream Pro", _t(31074))
        return None

    ext = _get_extension(url)
    folder = _build_folder_path(pnum, media_type, title, year, season)
    _ensure_dir(folder)

    base_name = _sanitize_filename(f"{title} ({year})") if year else _sanitize_filename(title)
    if media_type == "episode":
        base_name = f"{base_name} S{int(season or 1):02d}E{int(episode or 1):02d}"

    final_name = base_name + "." + ext
    final_path = os.path.join(folder, final_name)
    tmp_path = final_path + ".xstream.tmp"

    # If file already exists, append a number
    counter = 1
    original_final = final_path
    while os.path.exists(final_path):
        final_name = f"{base_name} ({counter}).{ext}"
        final_path = os.path.join(folder, final_name)
        tmp_path = final_path + ".xstream.tmp"
        counter += 1

    entry_id = _generate_id(url)

    total_bytes = 0
    resumable = False
    try:
        resp = _urlopen_head_safe(url, timeout=15)
        cl = resp.headers.get("Content-Length")
        if cl:
            total_bytes = int(cl)
        ar = resp.headers.get("Accept-Ranges", "").lower()
        resumable = (ar == "bytes")
        resp.close()
    except Exception as e:
        _log("HEAD probe failed for {0}: {1}".format(_safe_url_for_log(url), e))
    # Active range probe: many servers don't advertise Accept-Ranges but still support it
    if not resumable:
        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("Range", "bytes=0-0")
            opener = urllib.request.build_opener(_NoRedirectHandler())
            resp = opener.open(req, timeout=15)
            if resp.getcode() == 206:
                resumable = True
                _log("Range probe confirmed resumable: {0}".format(_safe_url_for_log(url)))
            resp.close()
        except Exception:
            pass

    entry = {
        "id": entry_id,
        "url": url,
        "filename": os.path.basename(final_path),
        "tmp_path": tmp_path,
        "final_path": final_path,
        "status": "queued",
        "total_bytes": total_bytes,
        "downloaded_bytes": 0,
        "percent": 0,
        "speed_kbps": 0,
        "profile_num": pnum,
        "title": title,
        "year": year,
        "media_type": media_type,
        "season": season,
        "episode": episode,
        "poster": poster,
        "plot": plot,
        "resumable": resumable,
        "started_at": "",
        "completed_at": "",
        "error": "",
    }

    def _add_entry(state):
        state.setdefault("downloads", [])
        state["downloads"].insert(0, entry)
        state["downloads"] = state["downloads"][:50]
        return True

    _state_transaction(pnum, _add_entry)

    _maybe_start_next(pnum)
    return entry_id


def _launch_via_runscript(entry_id, profile_num):
    """Launch the standalone download service via RunScript.

    RunScript gets its own Python interpreter that survives
    plugin navigation / invoker shutdown.
    """
    addon = xbmcaddon.Addon("plugin.video.xstream-pro")
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo("path"))
    script_path = os.path.join(addon_path, "resources", "lib", "download_service.py")
    # Kodi's RunScript takes comma-separated args
    cmd = f'RunScript("{script_path}",{entry_id},{profile_num})'
    xbmc.executebuiltin(cmd)
    _log(f"Launched RunScript for {entry_id}")


def _maybe_start_next(profile_num):
    entries_to_launch = []
    max_active = _max_concurrent_downloads()

    def _claim_next(state):
        active_count = sum(
            1 for dl in state.get("downloads", [])
            if dl.get("status") == "active"
        )
        slots = max(0, max_active - active_count)
        if slots <= 0:
            return False

        for dl in reversed(state.get("downloads", [])):
            if slots <= 0:
                break
            if dl.get("status") == "queued":
                dl["status"] = "active"
                entries_to_launch.append(dl.get("id", ""))
                slots -= 1

        return bool(entries_to_launch)

    claimed = _state_transaction(profile_num, _claim_next)

    if claimed:
        for entry_id in entries_to_launch:
            if entry_id:
                _launch_via_runscript(entry_id, profile_num)


def pause_download(download_id, profile_num=None):
    """Mark an active download as paused."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"ok": False}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("id") == download_id:
                if dl.get("status") == "active":
                    dl["status"] = "paused"
                    dl["speed_kbps"] = 0
                    result["ok"] = True
                break
        return result["ok"]

    _state_transaction(pnum, _mutate)
    return result["ok"]


def resume_download(download_id, profile_num=None):
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"ok": False}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("id") == download_id and dl.get("status") == "paused":
                dl["status"] = "queued"
                dl["error"] = ""
                dl["speed_kbps"] = 0
                result["ok"] = True
                break
        return result["ok"]

    _state_transaction(pnum, _mutate)

    if result["ok"]:
        _maybe_start_next(pnum)

    return result["ok"]


def cancel_download(download_id, profile_num=None):
    """Mark a download as cancelled; worker will clean up."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"ok": False, "tmp_path": ""}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("id") == download_id:
                dl["status"] = "cancelled"
                dl["speed_kbps"] = 0
                result["tmp_path"] = dl.get("tmp_path", "")
                result["ok"] = True
                break
        return result["ok"]

    _state_transaction(pnum, _mutate)

    if result["ok"]:
        _delete_paths([result["tmp_path"]])
        _maybe_start_next(pnum)

    return result["ok"]


def retry_download(download_id, profile_num=None):
    """Retry a failed download."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"ok": False}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("id") == download_id:
                if dl.get("status") in ("failed", "cancelled"):
                    dl["status"] = "queued"
                    dl["downloaded_bytes"] = 0
                    dl["percent"] = 0
                    dl["speed_kbps"] = 0
                    dl["error"] = ""
                    dl["started_at"] = ""
                    dl["completed_at"] = ""
                    result["ok"] = True
                break
        return result["ok"]

    _state_transaction(pnum, _mutate)

    if result["ok"]:
        _maybe_start_next(pnum)

    return result["ok"]


def remove_download_from_list(download_id, profile_num=None):
    """Remove a download entry from state without deleting the actual file."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"removed": False}

    def _mutate(state):
        new_list = []
        for dl in state.get("downloads", []):
            if dl.get("id") == download_id:
                result["removed"] = True
                continue
            new_list.append(dl)

        if result["removed"]:
            state["downloads"] = new_list

        return result["removed"]

    _state_transaction(pnum, _mutate)

    if result["removed"]:
        _log("Removed download {0} from list (file kept)".format(download_id))

    return result["removed"]


def delete_download(download_id, profile_num=None):
    """Remove a completed/failed download entry and its file."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"removed": False, "paths": []}

    def _mutate(state):
        new_list = []

        for dl in state.get("downloads", []):
            if dl.get("id") == download_id:
                result["removed"] = True

                tmp_path = dl.get("tmp_path", "")
                final_path = dl.get("final_path", "")

                result["paths"].append(tmp_path)
                result["paths"].append(final_path)

                if final_path:
                    result["paths"].append(os.path.splitext(final_path)[0] + ".nfo")

                continue

            new_list.append(dl)

        if result["removed"]:
            state["downloads"] = new_list

        return result["removed"]

    _state_transaction(pnum, _mutate)

    if result["removed"]:
        _delete_paths(result["paths"])
        _maybe_start_next(pnum)

    return result["removed"]


def get_downloads_list(profile_num=None):
    """Return downloads list for a profile, newest first."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    state = _load_state(pnum)
    return state.get("downloads", [])


def is_url_downloadable(url):
    """Quick check for UI gating."""
    return not _is_hls(url)


def mark_zombie_downloads_failed(profile_num=None):
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"count": 0}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("status") == "active":
                dl["status"] = "paused"
                dl["speed_kbps"] = 0
                dl["error"] = "Paused after Kodi exit"
                result["count"] += 1
        return result["count"] > 0

    _state_transaction(pnum, _mutate)

    if result["count"]:
        _log("Paused zombie downloads for profile {0}".format(pnum))

    return bool(result["count"])


def pause_all_downloads(profile_num=None):
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"count": 0}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("status") in ("active", "queued"):
                dl["status"] = "paused"
                dl["speed_kbps"] = 0
                result["count"] += 1
        return result["count"] > 0

    _state_transaction(pnum, _mutate)
    return result["count"]


def start_all_downloads(profile_num=None):
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"count": 0}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("status") == "paused":
                dl["status"] = "queued"
                dl["error"] = ""
                dl["speed_kbps"] = 0
                result["count"] += 1
            elif dl.get("status") in ("failed", "cancelled"):
                dl["status"] = "queued"
                dl["downloaded_bytes"] = 0
                dl["percent"] = 0
                dl["speed_kbps"] = 0
                dl["error"] = ""
                dl["started_at"] = ""
                dl["completed_at"] = ""
                result["count"] += 1
        return result["count"] > 0

    _state_transaction(pnum, _mutate)

    if result["count"]:
        _maybe_start_next(pnum)

    return result["count"]


def cancel_all_downloads(profile_num=None):
    """Cancel all active, queued, and paused downloads. Returns count cancelled."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"count": 0, "paths": []}

    def _mutate(state):
        for dl in state.get("downloads", []):
            if dl.get("status") in ("active", "queued", "paused"):
                dl["status"] = "cancelled"
                dl["speed_kbps"] = 0
                result["paths"].append(dl.get("tmp_path", ""))
                result["count"] += 1
        return result["count"] > 0

    _state_transaction(pnum, _mutate)

    if result["count"]:
        _delete_paths(result["paths"])
        _maybe_start_next(pnum)

    return result["count"]


def delete_all_downloads(profile_num=None):
    """Delete all completed, failed, and cancelled downloads. Returns count deleted."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"count": 0, "paths": []}

    def _mutate(state):
        new_list = []

        for dl in state.get("downloads", []):
            if dl.get("status") in ("completed", "failed", "cancelled"):
                result["count"] += 1

                tmp_path = dl.get("tmp_path", "")
                final_path = dl.get("final_path", "")

                result["paths"].append(tmp_path)
                result["paths"].append(final_path)

                if final_path:
                    result["paths"].append(os.path.splitext(final_path)[0] + ".nfo")

                continue

            new_list.append(dl)

        if result["count"]:
            state["downloads"] = new_list

        return result["count"] > 0

    _state_transaction(pnum, _mutate)

    if result["count"]:
        _delete_paths(result["paths"])
        _maybe_start_next(pnum)

    return result["count"]


def clean_missing_downloads(profile_num=None):
    """Remove completed downloads whose final file is missing. Returns count removed."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    result = {"count": 0, "paths": []}

    def _mutate(state):
        new_list = []

        for dl in state.get("downloads", []):
            if dl.get("status") == "completed":
                final_path = dl.get("final_path", "")
                if final_path and not os.path.exists(final_path):
                    result["count"] += 1
                    result["paths"].append(dl.get("tmp_path", ""))
                    result["paths"].append(final_path)
                    result["paths"].append(os.path.splitext(final_path)[0] + ".nfo")
                    continue

            new_list.append(dl)

        if result["count"]:
            state["downloads"] = new_list

        return result["count"] > 0

    _state_transaction(pnum, _mutate)

    if result["count"]:
        _delete_paths(result["paths"])

    return result["count"]


def count_missing_downloads(profile_num=None):
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    state = _load_state(pnum)
    count = 0
    for dl in state.get("downloads", []):
        if dl.get("status") == "completed":
            final = dl.get("final_path", "")
            if final and not os.path.exists(final):
                count += 1
    return count


# ---------------------------------------------------------------------------
# Kodi UI helpers
# ---------------------------------------------------------------------------
def _build_url(params):
    addon = xbmcaddon.Addon()
    base = sys.argv[0]
    return base + "?" + urllib.parse.urlencode(params)


def downloads_menu(addon_handle, profile_num=None):
    """Render the Downloads manager as a Kodi directory."""
    addon = xbmcaddon.Addon()
    pnum = str(profile_num or _get_default_profile_num(addon) or "1")
    downloads = get_downloads_list(pnum)

    xbmcplugin.setContent(addon_handle, "videos")

    # Fanart
    try:
        _addon_path = addon.getAddonInfo("path")
        _fanart_path = os.path.join(_addon_path, "resources", "background", "background.png")
        _fanart = _fanart_path if os.path.exists(_fanart_path) else ""
    except Exception:
        _fanart = ""

    # Header: Select Download Folder
    curr_folder = _get_download_base_dir()
    folder_label = _t(31409, _t(31351), curr_folder)
    folder_li = xbmcgui.ListItem(offscreen=True, label=folder_label)
    folder_art = {"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"}
    folder_li.setArt(folder_art)
    folder_url = _build_url({"mode": "change_download_folder"})
    xbmcplugin.addDirectoryItem(
        handle=addon_handle,
        url=folder_url,
        listitem=folder_li,
        isFolder=False,
    )

    # Header: Tools
    tools_li = xbmcgui.ListItem(offscreen=True, label="[B][COLOR yellow]{0}[/COLOR][/B]".format(_t(30010)))
    tools_art = {"icon": "DefaultAddonProgram.png", "thumb": "DefaultAddonProgram.png"}
    tools_li.setArt(tools_art)
    tools_url = _build_url({"mode": "downloads_tools", "pnum": pnum})
    xbmcplugin.addDirectoryItem(
        handle=addon_handle,
        url=tools_url,
        listitem=tools_li,
        isFolder=False,
    )

    # Header: Refresh
    refresh_li = xbmcgui.ListItem(offscreen=True, label="[B][COLOR blue]{0}[/COLOR][/B]".format(_t(30962)))
    refresh_art = {"icon": "DefaultAddonsUpdated.png", "thumb": "DefaultAddonsUpdated.png"}
    refresh_li.setArt(refresh_art)
    refresh_url = _build_url({"mode": "downloads_refresh"})
    xbmcplugin.addDirectoryItem(
        handle=addon_handle,
        url=refresh_url,
        listitem=refresh_li,
        isFolder=False,
    )

    # Count queued items for queue position display
    queue_items = [d for d in downloads if d.get("status") == "queued"]
    queue_positions = {d["id"]: i + 1 for i, d in enumerate(reversed(queue_items))}

    missing_completed_count = 0

    for dl in downloads:
        dl_id = dl.get("id")
        if not dl_id:
            continue
        status = dl.get("status", "queued")
        fname = dl.get("filename", "Unknown")
        pct = dl.get("percent", 0)
        total = dl.get("total_bytes", 0)
        title = dl.get("title", fname)

        # Build label with status indicator
        status_icon = {
            "queued": "[COLOR gray][{0}][/COLOR]".format(_t(31352)),
            "active": "[COLOR blue][{0}][/COLOR]".format(_t(31353, pct)),
            "paused": "[COLOR orange][{0}][/COLOR]".format(_t(31354)),
            "completed": "[COLOR green][{0}][/COLOR]".format(_t(31355)),
            "failed": "[COLOR red][{0}][/COLOR]".format(_t(31356)),
            "cancelled": "[COLOR red][{0}][/COLOR]".format(_t(31357)),
        }.get(status, "")

        def _fmt_size(bytes_val):
            if bytes_val >= 1024 * 1024 * 1024:
                return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"
            elif bytes_val >= 1024 * 1024:
                return f"{bytes_val / (1024 * 1024):.0f} MB"
            elif bytes_val > 0:
                return f"{bytes_val / 1024:.0f} KB"
            return ""

        display_title = title
        if dl.get("media_type") == "episode" and (dl.get("season") or dl.get("episode")):
            s = str(dl.get("season", "") or "")
            e = str(dl.get("episode", "") or "")
            if s and e:
                display_title += f" - S{int(s):02d}E{int(e):02d}"
            elif s:
                display_title += f" - S{int(s):02d}"
            elif e:
                display_title += f" - E{int(e):02d}"

        downloaded = dl.get("downloaded_bytes", 0)
        size_parts = []
        if downloaded > 0 and total > 0:
            size_parts.append(f"{_fmt_size(downloaded)} / {_fmt_size(total)}")
        elif downloaded > 0:
            size_parts.append(_fmt_size(downloaded))
        elif total > 0:
            size_parts.append(_fmt_size(total))
        size_str = " | ".join(size_parts)

        speed = dl.get("speed_kbps", 0)
        speed_str = f"{speed} KB/s" if speed > 0 else ""
        label = f"{status_icon} {display_title}"
        if status == "active":
            if size_str and speed_str:
                label += f"  ({size_str} - {speed_str})"
            elif size_str:
                label += f"  ({size_str})"
            elif speed_str:
                label += f"  ({speed_str})"
        elif status == "paused":
            if size_str:
                label += f"  ({pct}% - {size_str})"
            else:
                label += f"  ({pct}%)"
        elif status == "queued":
            qpos = queue_positions.get(dl_id, "?")
            label += "  [{0}]".format(_t(31358, qpos))
        elif status == "completed":
            final = dl.get("final_path", "")
            if final and not os.path.exists(final):
                label += "  {0}".format(_t(31102))
                missing_completed_count += 1
            else:
                label += "  [{0}]".format(_t(31355))
        elif status == "failed":
            label += "  [{0}]".format(_t(31359, dl.get("error", "")))

        li = xbmcgui.ListItem(offscreen=True, label=label)
        overlay_map = {
            "active": "8",
            "paused": "6",
            "queued": "5",
            "completed": "4",
            "failed": "7",
        }
        if status in overlay_map:
            li.setProperty("Overlay", overlay_map[status])

        cm = []
        if status == "completed":
            li.setProperty("IsPlayable", "true")
            final = dl.get("final_path", "")
            if final and os.path.exists(final):
                url = final
            else:
                url = _build_url({"mode": "downloads_manager"})
            remove_url = _build_url({"mode": "download_remove_from_list", "id": dl_id, "pnum": pnum})
            del_url = _build_url({"mode": "download_delete", "id": dl_id, "pnum": pnum})
            cm.append((_t(31360), f"RunPlugin({remove_url})"))
            cm.append((_t(31361), f"RunPlugin({del_url})"))
        elif status == "active":
            pause_url = _build_url({"mode": "download_pause", "id": dl_id, "pnum": pnum})
            cancel_url = _build_url({"mode": "download_cancel", "id": dl_id, "pnum": pnum})
            cm.append((_t(30955), f"RunPlugin({pause_url})"))
            cm.append((_t(30957), f"RunPlugin({cancel_url})"))
            url = _build_url({"mode": "downloads_manager"})
        elif status == "paused":
            resume_url = _build_url({"mode": "download_resume", "id": dl_id, "pnum": pnum})
            cancel_url = _build_url({"mode": "download_cancel", "id": dl_id, "pnum": pnum})
            cm.append((_t(30956), f"RunPlugin({resume_url})"))
            cm.append((_t(30957), f"RunPlugin({cancel_url})"))
            url = _build_url({"mode": "downloads_manager"})
        elif status in ("failed", "cancelled"):
            retry_url = _build_url({"mode": "download_retry", "id": dl_id, "pnum": pnum})
            del_url = _build_url({"mode": "download_delete", "id": dl_id, "pnum": pnum})
            cm.append((_t(30948), f"RunPlugin({retry_url})"))
            cm.append((_t(30947), f"RunPlugin({del_url})"))
            url = _build_url({"mode": "downloads_manager"})
        elif status == "queued":
            cancel_url = _build_url({"mode": "download_cancel", "id": dl_id, "pnum": pnum})
            cm.append((_t(30957), f"RunPlugin({cancel_url})"))
            url = _build_url({"mode": "downloads_manager"})
        else:
            url = _build_url({"mode": "downloads_manager"})

        if cm:
            li.addContextMenuItems(cm)

        poster = dl.get("poster") or "DefaultVideo.png"
        art = {"thumb": poster, "poster": poster}
        if _fanart:
            art["fanart"] = _fanart
        li.setArt(art)

        try:
            info = li.getVideoInfoTag()
            info.setTitle(title)
            info.setPlot(dl.get("plot", ""))
            if dl.get("year"):
                info.setYear(int(dl["year"]))
        except Exception:
            li.setInfo("video", {"title": title})

        xbmcplugin.addDirectoryItem(
            handle=addon_handle,
            url=url,
            listitem=li,
            isFolder=True,
        )

    if missing_completed_count > 0:
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            _t(31103, missing_completed_count),
        )

    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
