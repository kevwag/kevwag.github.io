"""Self-update system for Xstream Pro"""

import json
import os
import re
import sys
import time
import traceback
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from lang import _t

ADDON_ID = "plugin.video.xstream-pro"


def _is_tvos():
    if not xbmc.getCondVisibility("System.Platform.OSX"):
        return False
    profile = xbmcvfs.translatePath("special://masterprofile/")
    return "Containers" in profile or "Library/Caches/Kodi" in profile


_LOG_REDACT_PATH_RE = re.compile(
    r"(/(?:live|movie|series)/)([^/?\s]+)(/?)([^/?\s]*)", re.IGNORECASE
)
_LOG_REDACT_QUERY_RE = re.compile(r"(?i)\b(password|pwd|pass|username|user|token|key|apikey|api_key|auth)=([^&\s]+)")
_LOG_MAX_LEN = 4000


def _log(msg, level=xbmc.LOGINFO):
    """Unified logging for updater — prefixes all messages consistently."""
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
    xbmc.log(f"[Xstream Pro] {safe_msg}", level)


# Security: HTTPS enforced URLs for update sources
RELEASES_API = (
    "https://api.github.com/repos/Pesicp/XStreamPro/contents/releases"
)
RELEASES_BASE = "https://pesicp.github.io/XStreamPro/releases"
BETA_RELEASES_API = (
    "https://api.github.com/repos/Pesicp/XStreamPro/contents/releases/beta"
)
BETA_RELEASES_BASE = "https://pesicp.github.io/XStreamPro/releases/beta"


def get_addon():
    """Get addon instance"""
    return xbmcaddon.Addon(id=ADDON_ID)


def get_current_version():
    """Get currently installed version"""
    return get_addon().getAddonInfo("version")


def _version_key(v):
    """Parse a version string into a comparable tuple. Tolerates suffixes like '1.0.6-rc1'."""
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def _release_url(filename, channel="stable"):
    base = BETA_RELEASES_BASE if channel == "beta" else RELEASES_BASE
    url = f"{base}/{filename}"
    # Security: validate filename to prevent path traversal in URL construction
    import re

    if not re.match(r"^[\w\-.]+$", filename):
        raise ValueError(f"Invalid filename: {filename}")
    return url


import urllib.request
import zipfile
import shutil


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen_safe(req, timeout=10):
    """Open URL with manual same-host redirect loop (max 5 hops).
    Rejects cross-host redirects to prevent credential leakage.
    """
    initial_host = urllib.parse.urlparse(req.full_url).netloc.lower()
    current_url = req.full_url
    opener = urllib.request.build_opener(_NoRedirectHandler())
    for _ in range(5):
        new_req = urllib.request.Request(
            current_url,
            headers=req.headers,
            method=req.get_method(),
        )
        try:
            resp = opener.open(new_req, timeout=timeout)
        except urllib.request.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location", "")
                if not loc:
                    raise
                next_url = urllib.parse.urljoin(current_url, loc)
                next_host = urllib.parse.urlparse(next_url).netloc.lower()
                if next_host != initial_host:
                    _log(
                        "Cross-host redirect blocked: {0} -> {1}".format(
                            initial_host, next_host
                        ),
                        xbmc.LOGWARNING,
                    )
                    raise ValueError(
                        "Cross-host redirect blocked: {0}".format(next_host)
                    )
                current_url = next_url
                continue
            raise
        return resp
    raise ValueError("Redirect loop exceeded 5 hops")


# Memoize GitHub API responses (60 req/h unauthenticated limit).
_VERSIONS_CACHE_TTL = 300  # seconds
_versions_cache = {
    "stable": {"ts": 0.0, "data": None},
    "beta": {"ts": 0.0, "data": None},
}


def _beta_updates_enabled():
    try:
        return get_addon().getSetting("update_beta_enabled").lower() == "true"
    except Exception:
        return False


def _fetch_versions_for_channel(channel="stable", force=False):
    """Fetch one update channel from GitHub API."""
    cache = _versions_cache.get(channel) or _versions_cache["stable"]
    now = time.time()
    if (
        not force
        and cache["data"] is not None
        and (now - cache["ts"]) < _VERSIONS_CACHE_TTL
    ):
        return cache["data"]
    try:
        api_url = BETA_RELEASES_API if channel == "beta" else RELEASES_API
        req = urllib.request.Request(
            api_url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with _urlopen_safe(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        versions = []
        for item in data:
            name = item.get("name", "")
            match = re.match(r"plugin\.video\.xstream-pro-([\d.]+)\.zip", name)
            if match:
                versions.append(
                    {
                        "version": match.group(1),
                        "filename": name,
                        "url": _release_url(name, channel),
                        "channel": channel,
                    }
                )

        versions.sort(key=lambda v: _version_key(v["version"]), reverse=True)
        cache["ts"] = now
        cache["data"] = versions
        return versions
    except Exception as e:
        _log(f"Failed to fetch {channel} versions: {str(e)}")
        # Don't poison the cache with a failure — keep serving the previous
        # successful result if we have one, otherwise return empty.
        return cache["data"] or []


def fetch_all_versions(force=False, include_beta=None):
    """Fetch available versions from stable, and beta when enabled."""
    if include_beta is None:
        include_beta = _beta_updates_enabled()
    versions = list(_fetch_versions_for_channel("stable", force=force))
    if include_beta:
        versions.extend(_fetch_versions_for_channel("beta", force=force))

    by_version = {}
    for item in versions:
        version = item.get("version", "")
        existing = by_version.get(version)
        if existing is None or (
            existing.get("channel") == "beta" and item.get("channel") == "stable"
        ):
            by_version[version] = item
    versions = list(by_version.values())
    versions.sort(key=lambda v: _version_key(v["version"]), reverse=True)
    return versions


def check_for_update(allow_stable_downgrade=False):
    """Check if update is available.
    Returns: (update_available, latest_version, download_url, channel)
    """
    beta_enabled = _beta_updates_enabled()
    versions = fetch_all_versions(include_beta=beta_enabled)
    if not versions:
        return False, None, None, "stable"

    latest = versions[0]
    if _version_key(latest["version"]) > _version_key(get_current_version()):
        return True, latest["version"], latest["url"], latest.get("channel", "stable")

    if allow_stable_downgrade and not beta_enabled:
        installed_channel = get_addon().getSetting("installed_update_channel") or "stable"
        if installed_channel == "beta":
            stable_versions = fetch_all_versions(include_beta=False)
            if stable_versions:
                stable = stable_versions[0]
                if stable.get("version") != get_current_version():
                    return True, stable["version"], stable["url"], "stable"

    return False, latest["version"], None, latest.get("channel", "stable")


def _verify_zip(target_path):
    """Verify downloaded file is a valid ZIP and contains expected addon structure."""

    try:
        with zipfile.ZipFile(target_path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file:
                _log(
                    f"ZIP verification failed: {bad_file}",
                    xbmc.LOGERROR,
                )
                return False
            # Security: validate all entries are safe
            for name in zf.namelist():
                normalized = name.replace("\\", "/")
                parts = [p for p in normalized.split("/") if p]
                if not parts or any(p == ".." for p in parts):
                    _log(f"ZIP contains unsafe path: {name}", xbmc.LOGERROR)
                    return False
                if normalized.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", normalized):
                    _log(f"ZIP contains unsafe absolute path: {name}", xbmc.LOGERROR)
                    return False
                if not normalized.startswith("plugin.video.xstream-pro/"):
                    _log(f"ZIP contains unexpected path: {name}", xbmc.LOGERROR)
                    return False
            total_size = 0
            infos = zf.infolist()
            if len(infos) > 2000:
                _log("ZIP contains too many entries", xbmc.LOGERROR)
                return False
            for info in infos:
                total_size += info.file_size
                if info.file_size > 50 * 1024 * 1024:
                    _log(f"ZIP entry too large: {info.filename}", xbmc.LOGERROR)
                    return False
            if total_size > 250 * 1024 * 1024:
                _log("ZIP total size exceeds limit", xbmc.LOGERROR)
                return False
            if "plugin.video.xstream-pro/addon.xml" not in [
                n.replace("\\", "/") for n in zf.namelist()
            ]:
                _log("ZIP missing addon.xml")
                return False
        return True
    except zipfile.BadZipFile:
        _log("Invalid ZIP file")
        return False
    except Exception as e:
        _log(f"ZIP verification error: {str(e)}")
        return False


def download_update(url, target_path):
    """Download update zip to temp location with HTTPS enforcement and verification."""
    try:
        # Security: enforce HTTPS for downloads
        if not url.startswith("https://"):
            _log(
                f"Update download rejected: non-HTTPS URL",
                xbmc.LOGERROR,
            )
            return False

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _urlopen_safe(req, timeout=30) as response:
            max_size = 50 * 1024 * 1024
            data = response.read(max_size + 1)
            if len(data) > max_size:
                _log(
                    "Update download rejected: file too large",
                    xbmc.LOGERROR,
                )
                return False
            with open(target_path, "wb") as f:
                f.write(data)

        if not _verify_zip(target_path):
            os.remove(target_path)
            return False

        return True
    except Exception as e:
        _log(f"Download failed: {str(e)}")
        _log(f"Traceback: {traceback.format_exc()}")
        return False


def _perform_install(new_version, url, dialog, completion_title_id=30811, channel="stable"):
    """Download, extract, and prompt-restart for a given version. Returns True on success."""

    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", _t(30762, new_version))

    # Download to packages/ folder (Kodi standard location)
    packages_dir = xbmcvfs.translatePath("special://home/addons/packages/")
    if not xbmcvfs.exists(packages_dir):
        xbmcvfs.mkdirs(packages_dir)
    zip_path = os.path.join(packages_dir, f"{ADDON_ID}-{new_version}.zip")

    success = download_update(url, zip_path)
    progress.close()

    if not success:
        dialog.notification("Xstream Pro", _t(30400), xbmcgui.NOTIFICATION_ERROR)
        return False

    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", _t(30401))

    addon_path = xbmcvfs.translatePath("special://home/addons/")
    try:
        # Security: validate addon_path is within expected location
        expected_base = os.path.normpath(xbmcvfs.translatePath("special://home/"))
        if not os.path.normpath(addon_path).startswith(expected_base):
            raise ValueError("Invalid addon installation path")

        # Security: verify ZIP structure before extraction
        addon_real = os.path.abspath(os.path.normpath(addon_path))
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                target = os.path.abspath(os.path.normpath(os.path.join(addon_path, member)))
                if os.path.commonpath([addon_real, target]) != addon_real:
                    raise ValueError(f"ZIP traversal attempt: {member}")

        # Release-safe install: extract to temp, verify, then swap folders.
        addon_folder = os.path.join(addon_path, ADDON_ID)
        addon_new = addon_folder + ".new"
        addon_bak = addon_folder + ".bak"

        for stale in (addon_new, addon_bak):
            if os.path.exists(stale):
                try:
                    shutil.rmtree(stale)
                except Exception as e:
                    _log(f"Failed to remove stale update folder {stale}: {e}")

        _log(f"Extracting to: {addon_new}")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for name in zip_ref.namelist():
                basename = os.path.basename(name)
                # Strip top-level folder prefix from zip entries.
                parts = name.replace("\\", "/").split("/")
                if len(parts) > 1 and parts[0] == ADDON_ID:
                    relative = "/".join(parts[1:])
                else:
                    relative = name
                if not relative:
                    continue
                target = os.path.abspath(os.path.normpath(os.path.join(addon_new, relative)))
                if os.path.commonpath([addon_real, target]) != addon_real:
                    _log(
                        f"Skipped unsafe update entry: {name}",
                        xbmc.LOGWARNING,
                    )
                    continue
                if basename.startswith(".") or not basename:
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(zip_ref.read(name))

        if not os.path.exists(os.path.join(addon_new, "addon.xml")):
            _log("Extracted update missing addon.xml", xbmc.LOGERROR)
            try:
                shutil.rmtree(addon_new)
            except Exception:
                pass
            progress.close()
            dialog.notification("Xstream Pro", _t(30710), xbmcgui.NOTIFICATION_ERROR)
            return False

        # Swap: current -> .bak, .new -> current
        if os.path.exists(addon_folder):
            try:
                os.rename(addon_folder, addon_bak)
            except Exception as e:
                _log(f"Backup rename failed: {e}", xbmc.LOGERROR)
                try:
                    shutil.rmtree(addon_new)
                except Exception:
                    pass
                progress.close()
                dialog.notification("Xstream Pro", _t(30710), xbmcgui.NOTIFICATION_ERROR)
                return False

        try:
            os.rename(addon_new, addon_folder)
        except Exception as e:
            _log(f"Final rename failed: {e}", xbmc.LOGERROR)
            if os.path.exists(addon_bak):
                try:
                    os.rename(addon_bak, addon_folder)
                except Exception as restore_err:
                    _log(f"Restore from backup also failed: {restore_err}", xbmc.LOGERROR)
            progress.close()
            dialog.notification("Xstream Pro", _t(30710), xbmcgui.NOTIFICATION_ERROR)
            return False

        if os.path.exists(addon_bak):
            try:
                shutil.rmtree(addon_bak)
            except Exception as e:
                _log(f"Failed to remove backup folder: {e}")

        xbmc.sleep(1000)

        # Refresh addon database (disable/enable removed - was causing "remove from recents" popup)
        xbmc.executebuiltin("UpdateLocalAddons")
    except Exception as e:
        _log(f"Extract failed: {str(e)}")
        progress.close()
        dialog.notification("Xstream Pro", _t(30710), xbmcgui.NOTIFICATION_ERROR)
        return False

    progress.close()

    # Update version setting so user sees new version in settings
    get_addon().setSetting("current_version_display", new_version)
    get_addon().setSetting("installed_update_channel", channel)

    restart = dialog.yesno(
        _t(completion_title_id),
        _t(30402, new_version),
        nolabel=_t(30403),
        yeslabel=_t(30404),
    )

    if restart:
        if xbmc.getCondVisibility("System.Platform.Android") or _is_tvos():
            # RestartApp is a no-op on Android and crashes on tvOS.
            # Ask the user to fully close and reopen Kodi.
            xbmcgui.Dialog().ok(
                "Xstream Pro",
                _t(30763),
            )
        else:
            xbmc.executebuiltin("RestartApp")
    return True


def do_direct_update_install(new_version, url, channel="stable"):
    """Direct install without check - used from startup prompt"""
    dialog = xbmcgui.Dialog()
    try:
        _perform_install(new_version, url, dialog, channel=channel)
    except Exception as e:
        _log(f"Direct update ERROR: {str(e)}")
        dialog.ok("Xstream Pro", _t(30405))


def check_and_install_update():
    """Main entry point: Check for update and prompt user (for Tools menu)"""
    _log("Check update started")
    dialog = xbmcgui.Dialog()

    try:
        progress = xbmcgui.DialogProgress()
        progress.create("Xstream Pro", _t(30406))

        update_available, new_version, url, channel = check_for_update(
            allow_stable_downgrade=True
        )
        _log(
            f"Update check: available={update_available}, version={new_version}, channel={channel}",
            xbmc.LOGDEBUG,
        )

        progress.close()

        if not update_available:
            if new_version is None:
                dialog.ok("Xstream Pro", _t(30407))
            else:
                dialog.ok("Xstream Pro", _t(30408))
            return

        current = get_current_version()
        if channel == "stable" and _version_key(new_version) < _version_key(current):
            prompt = "Return from beta to stable version {0}?".format(new_version)
        else:
            prompt = _t(30410, current, new_version)
        result = dialog.yesno(_t(30409), prompt)
        if not result:
            return

        _perform_install(new_version, url, dialog, channel=channel)

    except Exception as e:
        _log(f"Update ERROR: {str(e)}")

        _log(f"Traceback: {traceback.format_exc()}")
        dialog.ok("Xstream Pro", _t(30411))


def silent_check_on_startup():
    """Background check on startup (if enabled in settings)"""
    addon = get_addon()
    check_interval = addon.getSetting("update_check_interval")
    if check_interval == "On Startup":
        win = xbmcgui.Window(10000)
        prop = "xstream_pro.update_checked_this_session"
        if win.getProperty(prop):
            return
        win.setProperty(prop, "1")

    # settings.xml stores the raw English value from values="Never|On Startup|Daily|Weekly|Monthly"
    if check_interval == "Never":
        return

    last_check = addon.getSetting("last_update_check")
    today = time.strftime("%Y-%m-%d")

    if check_interval == "Daily":
        if last_check == today:
            return
    elif check_interval == "Weekly":
        if last_check:
            last_time = time.mktime(time.strptime(last_check, "%Y-%m-%d"))
            now_time = time.mktime(time.strptime(today, "%Y-%m-%d"))
            if (now_time - last_time) < (7 * 24 * 60 * 60):
                return
    elif check_interval == "Monthly":
        if last_check:
            last_time = time.mktime(time.strptime(last_check, "%Y-%m-%d"))
            now_time = time.mktime(time.strptime(today, "%Y-%m-%d"))
            if (now_time - last_time) < (30 * 24 * 60 * 60):
                return
    # "On Startup" always proceeds here

    update_available, new_version, url, channel = check_for_update(
        allow_stable_downgrade=False
    )

    if update_available:
        current = get_current_version()
        result = xbmcgui.Dialog().yesno(
            _t(30706),
            _t(30707, current, new_version),
            nolabel=_t(30708),
            yeslabel=_t(30709),
        )

        if result:
            # Update timestamp before install so failures don't cause immediate recheck
            addon.setSetting("last_update_check", today)
            do_direct_update_install(new_version, url, channel=channel)
            return
        else:
            addon.setSetting("update_available", "true")
            addon.setSetting("update_version", new_version)

    addon.setSetting("last_update_check", today)


def get_available_versions(include_beta=None):
    """Get list of all available version strings (newest first), for revert UI."""
    return fetch_all_versions(force=True, include_beta=include_beta)


def revert_to_version(version, url=None, channel="stable"):
    """Revert to a specific older version."""
    if url is None:
        filename = f"plugin.video.xstream-pro-{version}.zip"
        url = _release_url(filename, channel)

    dialog = xbmcgui.Dialog()
    result = dialog.yesno(
        _t(30764),
        _t(30765, version),
    )
    if not result:
        return False

    return _perform_install(version, url, dialog, completion_title_id=30812, channel=channel)


def revert_version_menu():
    """Show menu to select version to revert to"""
    dialog = xbmcgui.Dialog()

    include_beta = _beta_updates_enabled()
    versions = get_available_versions(include_beta=include_beta)
    current = get_current_version()
    current_channel = get_addon().getSetting("installed_update_channel") or "stable"

    if not versions:
        dialog.notification("Xstream Pro", _t(30766), xbmcgui.NOTIFICATION_ERROR)
        return

    older_versions = [
        v
        for v in versions
        if v.get("version") != current or v.get("channel", "stable") != current_channel
    ]

    if not older_versions:
        dialog.ok("Xstream Pro", _t(30767))
        return

    labels = [
        "{0} [{1}]".format(v.get("version"), v.get("channel", "stable"))
        for v in older_versions
    ]
    selected = dialog.select(_t(30768, current), labels)
    if selected == -1:
        return

    selected_version = older_versions[selected]
    revert_to_version(
        selected_version["version"],
        selected_version["url"],
        selected_version.get("channel", "stable"),
    )


# Entry point for RunScript calls
if __name__ == "__main__":
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "check":
            check_and_install_update()
        elif action == "silent":
            silent_check_on_startup()
