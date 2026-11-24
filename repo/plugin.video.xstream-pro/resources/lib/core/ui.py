"""UI helpers: URL building, list items, directory items.

Call init() after addon, base_url, and log_fn are available.
"""

import urllib.parse

import xbmcgui
import xbmcplugin

_base_url = None
_addon = None
_log_fn = None


def init(addon, base_url, log_fn):
    global _base_url, _addon, _log_fn
    _base_url = base_url
    _addon = addon
    _log_fn = log_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def build_url(query):
    return _base_url + "?" + urllib.parse.urlencode(query, doseq=True)


def _new_listitem(label=""):
    try:
        li = xbmcgui.ListItem(offscreen=True)
        if label:
            li.setLabel(label)
        return li
    except TypeError:
        return xbmcgui.ListItem(label=label)

def add_directory_items(addon_handle, directory_items, update_listing=False, cache_to_disc=False):
    """Add already-built directory items in one Kodi call."""
    items = directory_items or []
    if items:
        xbmcplugin.addDirectoryItems(addon_handle, items, len(items))
    xbmcplugin.endOfDirectory(
        addon_handle,
        succeeded=True,
        updateListing=update_listing,
        cacheToDisc=cache_to_disc,
    )

