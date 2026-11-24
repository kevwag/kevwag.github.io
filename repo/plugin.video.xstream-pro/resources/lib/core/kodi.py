"""Low-level Kodi helpers: JSON-RPC, logging, platform detection, file sync.

No dependency on addon.py globals — all state passed via init() or args.
"""

import json
import os
import time
import urllib.parse

import xbmc
import xbmcvfs

_addon = None
_log_fn = None


def init(addon, log_fn):
    global _addon, _log_fn
    _addon = addon
    _log_fn = log_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _jsonrpc_call(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    try:
        response = xbmc.executeJSONRPC(json.dumps(payload))
        data = json.loads(response or "{}")
        if data.get("error"):
            _log(f"JSON-RPC {method} error: {data.get('error')}")
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log(f"JSON-RPC {method} failed: {exc}")
        return {}


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


def _is_tvos():
    """Detect tvOS (Apple TV).

    Kodi reports tvOS as System.Platform.OSX (same as macOS).
    We disambiguate by checking the profile path:
    tvOS uses sandboxed Containers/.../Library/Caches/Kodi,
    macOS uses ~/Library/Application Support/Kodi.
    """
    if not xbmc.getCondVisibility("System.Platform.OSX"):
        return False
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    return "Containers" in profile or "Library/Caches/Kodi" in profile


def _tvos_sleep(ms):
    """Reduce sleep duration on tvOS to avoid SpringBoard watchdog kills."""
    if _is_tvos() and ms > 500:
        return max(ms // 3, 500)
    return ms


def _safe_fsync(f):
    """Skip fsync on tvOS — can cause EINVAL or hard crashes on APFS sandbox."""
    if _is_tvos():
        return
    try:
        os.fsync(f.fileno())
    except OSError:
        pass