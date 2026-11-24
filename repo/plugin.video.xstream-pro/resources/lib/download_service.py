"""Standalone download worker for Xstream Pro.

Launched via xbmc.executebuiltin('RunScript(..., download_id, profile_num)').
Runs in its own Python interpreter, independent of the plugin invoker.
Updates the same JSON state file that the UI reads.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xbmc
import xbmcaddon
import xbmcvfs
from datetime import datetime

# ---------------------------------------------------------------------------
# tvOS-safe fsync
# ---------------------------------------------------------------------------
def _is_tvos():
    if not xbmc.getCondVisibility("System.Platform.OSX"):
        return False
    try:
        profile = xbmcvfs.translatePath(xbmcaddon.Addon("plugin.video.xstream-pro").getAddonInfo("profile"))
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


def _max_concurrent_downloads():
    try:
        addon = xbmcaddon.Addon("plugin.video.xstream-pro")
        return max(1, min(5, int(addon.getSetting("max_concurrent_downloads") or "1")))
    except Exception:
        return 1

# ---------------------------------------------------------------------------
# Logging
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
    xbmc.log(f"[Xstream Pro] [DL-SVC] {safe}", xbmc.LOGDEBUG)


# ---------------------------------------------------------------------------
# State helpers (duplicated from downloader.py to avoid imports)
# ---------------------------------------------------------------------------
def _profile_dir(profile_num):
    addon = xbmcaddon.Addon("plugin.video.xstream-pro")
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


def _find_entry(state, entry_id):
    for dl in state.get("downloads", []):
        if dl.get("id") == entry_id:
            return dl
    return None


def _check_status(profile_num, entry_id):
    state = _load_state(profile_num)
    entry = _find_entry(state, entry_id)
    if not entry:
        return "deleted"
    return str(entry.get("status") or "")


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


def _update_entry(profile_num, entry_id, **kwargs):
    def _mutate(state):
        entry = _find_entry(state, entry_id)
        if entry:
            entry.update(kwargs)
            return True
        return False

    return bool(_state_transaction(profile_num, _mutate))


MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024 * 1024


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_connection(url, resume_from=0):
    from iptv import _validate_url
    if not _validate_url(url):
        _log("Blocked unsafe download URL")
        return None
    current = url
    for _ in range(5):
        req = urllib.request.Request(current)
        if resume_from > 0:
            req.add_header("Range", f"bytes={resume_from}-")
        try:
            opener = urllib.request.build_opener(NoRedirectHandler)
            resp = opener.open(req, timeout=30)
            if resume_from > 0 and resp.getcode() != 206:
                _log("Server ignored Range request; refusing unsafe resume")
                try:
                    resp.close()
                except Exception:
                    pass
                return None
            return resp
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                _log(f"Connection error: {e}")
                return None
            loc = e.headers.get("Location", "")
            next_url = urllib.parse.urljoin(current, loc)
            if not _validate_url(next_url):
                _log("Blocked unsafe download redirect")
                return None
            current = next_url
    return None


# ---------------------------------------------------------------------------
# Main worker
# ---------------------------------------------------------------------------
def run_download(entry_id, profile_num):
    _log(f"Service started for {entry_id} profile={profile_num}")

    # Wait briefly for the state entry to be written by start_download()
    entry = None
    for _ in range(10):
        state = _load_state(profile_num)
        entry = _find_entry(state, entry_id)
        if entry:
            break
        xbmc.sleep(200)

    if not entry:
        _log(f"Entry {entry_id} not found in state")
        return

    url = entry["url"]
    tmp_path = entry["tmp_path"]
    final_path = entry["final_path"]
    total = entry.get("total_bytes", 0)
    resumable = entry.get("resumable", False)

    _update_entry(profile_num, entry_id, status="active", started_at=datetime.now().isoformat())

    resume_from = 0
    if os.path.exists(tmp_path):
        resume_from = os.path.getsize(tmp_path)
        if resume_from > 0:
            _log(f"Resuming from {resume_from}")

    resp = _open_connection(url, resume_from)
    if not resp:
        _update_entry(profile_num, entry_id, status="failed", error="Connection failed",
                      completed_at=datetime.now().isoformat())
        return

    # Validate total size
    try:
        cl = resp.headers.get("Content-Length")
        if cl:
            chunk_total = int(cl)
            if resume_from > 0:
                total = resume_from + chunk_total
            else:
                total = chunk_total
            _update_entry(profile_num, entry_id, total_bytes=total)
    except Exception:
        pass

    chunk_size = 1024 * 1024  # 1 MB
    buffer = []
    written = resume_from
    last_state_update = time.time()
    last_speed_check = time.time()
    bytes_since_speed_check = 0
    retry_count = 0
    max_retries = 3

    mode = "ab" if resume_from > 0 else "wb"

    try:
        with open(tmp_path, mode) as f:
            while True:
                status = _check_status(profile_num, entry_id)
                if status == "cancelled":
                    _log("Cancelled by user")
                    break

                if status == "paused":
                    _log("Paused by user")
                    while buffer:
                        f.write(buffer.pop(0))
                    f.flush()
                    _safe_fsync(f)
                    pct = min(100, int(written * 100 / total)) if total else 0
                    _update_entry(
                        profile_num,
                        entry_id,
                        status="paused",
                        downloaded_bytes=written,
                        percent=pct,
                        speed_kbps=0,
                    )
                    return

                if status == "deleted":
                    _log("Entry deleted")
                    break

                try:
                    data = resp.read(chunk_size)
                except Exception as e:
                    _log(f"Read error: {e}")
                    retry_count += 1
                    if retry_count > max_retries:
                        _update_entry(profile_num, entry_id, status="failed",
                                      error=f"Read failed after {max_retries} retries",
                                      completed_at=datetime.now().isoformat())
                        return
                    if resumable:
                        try:
                            resp.close()
                        except Exception:
                            pass
                        xbmc.sleep(2000)
                        resp = _open_connection(url, written)
                        if not resp:
                            _update_entry(profile_num, entry_id, status="failed",
                                          error="Resume connection failed",
                                          completed_at=datetime.now().isoformat())
                            return
                        continue
                    else:
                        _update_entry(profile_num, entry_id, status="failed",
                                      error=str(e),
                                      completed_at=datetime.now().isoformat())
                        return

                if not data:
                    while buffer:
                        f.write(buffer.pop(0))
                    f.flush()
                    break

                retry_count = 0
                buffer.append(data)
                written += len(data)
                bytes_since_speed_check += len(data)
                if written > MAX_DOWNLOAD_BYTES:
                    _update_entry(profile_num, entry_id, status="failed", error="Download size limit exceeded")
                    return

                if len(buffer) >= 5:
                    while buffer:
                        f.write(buffer.pop(0))
                    f.flush()

                now = time.time()
                if now - last_state_update >= 2:
                    pct = min(100, int(written * 100 / total)) if total else 0
                    # Calculate speed (KB/s)
                    elapsed = now - last_speed_check
                    speed_kbps = 0
                    if elapsed > 0:
                        speed_kbps = int(bytes_since_speed_check / 1024 / elapsed)
                    _update_entry(
                        profile_num, entry_id,
                        downloaded_bytes=written,
                        percent=pct,
                        speed_kbps=speed_kbps,
                    )
                    last_state_update = now
                    last_speed_check = now
                    bytes_since_speed_check = 0
    except OSError as e:
        _log(f"File write error: {e}")
        _update_entry(profile_num, entry_id, status="failed",
                      error=f"File write error: {e}",
                      completed_at=datetime.now().isoformat())
        return
    finally:
        try:
            resp.close()
        except Exception:
            pass

    final_status = _check_status(profile_num, entry_id)
    if final_status in ("cancelled", "deleted"):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _update_entry(profile_num, entry_id, status="cancelled",
                      completed_at=datetime.now().isoformat())
        return

    try:
        with open(tmp_path, "ab") as f:
            f.flush()
            _safe_fsync(f)
        os.replace(tmp_path, final_path)
        try:
            from downloader import _write_nfo
            folder = os.path.dirname(final_path)
            name_noext = os.path.splitext(os.path.basename(final_path))[0]
            _write_nfo(folder, name_noext, entry)
        except Exception as e:
            _log(f"NFO write failed: {e}")
    except OSError as e:
        _log(f"Failed to move tmp to final: {e}")
        _update_entry(profile_num, entry_id, status="failed",
                      error=f"File move failed: {e}")
        return

    _update_entry(
        profile_num, entry_id,
        status="completed",
        downloaded_bytes=written,
        percent=100,
        speed_kbps=0,
        completed_at=datetime.now().isoformat(),
    )
    _log("Completed: {0}".format(os.path.basename(final_path)))


def _start_next_queued(profile_num):
    """After this download finishes, start queued items while slots are free."""
    state = _load_state(profile_num)
    max_active = _max_concurrent_downloads()
    active_count = sum(
        1 for dl in state.get("downloads", [])
        if dl.get("status") == "active"
    )
    slots = max(0, max_active - active_count)
    if slots <= 0:
        return

    launch_ids = []
    for dl in reversed(state.get("downloads", [])):
        if slots <= 0:
            break
        if dl.get("status") == "queued":
            dl["status"] = "active"
            launch_ids.append(dl.get("id", ""))
            slots -= 1

    if not launch_ids:
        return

    _save_state(profile_num, state)
    addon = xbmcaddon.Addon("plugin.video.xstream-pro")
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo("path"))
    script_path = os.path.join(addon_path, "resources", "lib", "download_service.py")
    for dl_id in launch_ids:
        if dl_id:
            cmd = f'RunScript("{script_path}",{dl_id},{profile_num})'
            xbmc.executebuiltin(cmd)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # sys.argv[0] = script path
    # sys.argv[1] = download_id
    # sys.argv[2] = profile_num
    if len(sys.argv) >= 3:
        dl_id = sys.argv[1]
        pnum = sys.argv[2]
        try:
            run_download(dl_id, pnum)
        finally:
            _start_next_queued(pnum)
    else:
        _log("Missing download service arguments")
