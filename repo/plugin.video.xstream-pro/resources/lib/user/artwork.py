"""Artwork and custom background helpers for Xstream Pro."""

import os

import xbmc
import xbmcgui
import xbmcvfs


addon = None
_log = None
_ICON_CACHE = {}
_FANART_CACHE = {}


def init(addon_obj, log_fn):
    global addon, _log
    addon = addon_obj
    _log = log_fn


def local_icon(name):
    cached = _ICON_CACHE.get(name)
    if cached:
        return cached
    win_prop = xbmcgui.Window(10000).getProperty(f"xstream_pro.icon.{name}")
    if win_prop:
        _ICON_CACHE[name] = win_prop
        return win_prop
    try:
        icon_path = os.path.join(addon.getAddonInfo("path"), "resources", "icons", f"{name}.png")
        if os.path.exists(icon_path):
            _ICON_CACHE[name] = icon_path
            xbmcgui.Window(10000).setProperty(f"xstream_pro.icon.{name}", icon_path)
            return icon_path
    except Exception:
        pass
    fallback = "DefaultFolder.png"
    _ICON_CACHE[name] = fallback
    try:
        xbmcgui.Window(10000).setProperty(f"xstream_pro.icon.{name}", fallback)
    except Exception:
        pass
    return fallback


def menu_art(icon, fanart=None):
    icon = icon or "DefaultFolder.png"
    art = {
        "icon": icon,
    }
    fanart = fanart if fanart is not None else addon_fanart()
    if fanart:
        art["fanart"] = fanart
    return art


def addon_fanart():
    try:
        custom = addon.getSetting("custom_background")
        if _FANART_CACHE.get("setting") == custom:
            return _FANART_CACHE.get("path", "")
        fanart = ""
        if custom == "__none__":
            fanart = ""
        elif custom == "__default__" or not custom:
            fanart_path = os.path.join(
                addon.getAddonInfo("path"),
                "resources",
                "background",
                "background.png",
            )
            if os.path.exists(fanart_path):
                fanart = fanart_path
        else:
            custom_path = xbmcvfs.translatePath(custom)
            if os.path.exists(custom_path):
                fanart = custom_path
            else:
                fanart_path = os.path.join(
                    addon.getAddonInfo("path"),
                    "resources",
                    "background",
                    "background.png",
                )
                if os.path.exists(fanart_path):
                    fanart = fanart_path
        _FANART_CACHE["setting"] = custom
        _FANART_CACHE["path"] = fanart
        return fanart
    except Exception:
        return ""


def clear_background():
    """Clear custom background so Kodi theme shows through."""
    try:
        addon.setSetting("custom_background", "__none__")
        _FANART_CACHE.clear()
        xbmc.executebuiltin("Container.Refresh")
        return True
    except Exception as e:
        _log("_clear_background error: {0}".format(e))
        return False


def restore_background():
    """Restore addon default background."""
    try:
        addon.setSetting("custom_background", "__default__")
        _FANART_CACHE.clear()
        xbmc.executebuiltin("Container.Refresh")
        return True
    except Exception as e:
        _log("_restore_background error: {0}".format(e))
        return False
