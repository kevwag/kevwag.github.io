"""Lazy TMDB route setup bridge.

This keeps addon.py as a route facade while preserving the existing
tmdb_routes.setup(context) contract.
"""

import traceback

import xbmcgui
import xbmcplugin


_CTX = {}
_tmdb_routes = None
_tmdb_routes_setup = None


def init(context):
    _CTX.clear()
    _CTX.update(context or {})


def _c(name, default=None):
    return _CTX.get(name, default)


def setup_tmdb_routes():
    global _tmdb_routes, _tmdb_routes_setup

    log = _c("_log")
    translate = _c("_t")
    new_listitem = _c("_new_listitem")
    menu_art = _c("_menu_art")
    local_icon = _c("_local_icon")
    addon_handle = _c("addon_handle")

    if not _tmdb_routes_setup or not _tmdb_routes:
        try:
            import tmdb_routes as tmdb_routes_module

            _tmdb_routes = tmdb_routes_module
            _tmdb_routes_setup = tmdb_routes_module.setup
        except Exception as exc:
            if log:
                log("TMDB routes import failed: {0}".format(exc))
                log("Traceback: {0}".format(traceback.format_exc()))
            if translate:
                xbmcgui.Dialog().notification("Xstream Pro", translate(31146))
            if new_listitem and addon_handle is not None:
                label = translate(31146) if translate else "TMDB failed to load"
                li = new_listitem(label)
                if menu_art and local_icon:
                    li.setArt(menu_art(local_icon("themoviedb")))
                xbmcplugin.addDirectoryItem(addon_handle, "", li, False)
                xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return False

    if not _tmdb_routes_setup or not _tmdb_routes:
        if translate:
            xbmcgui.Dialog().notification("Xstream Pro", translate(31146))
        if new_listitem and addon_handle is not None:
            label = translate(31146) if translate else "TMDB failed to load"
            li = new_listitem(label)
            if menu_art and local_icon:
                li.setArt(menu_art(local_icon("themoviedb")))
            xbmcplugin.addDirectoryItem(addon_handle, "", li, False)
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return False

    history_classes = _c("_get_history_classes")()
    _tmdb_routes_setup(
        {
            "addon": _c("addon"),
            "addon_handle": addon_handle,
            "build_url": _c("build_url"),
            "_t": translate,
            "_local_icon": local_icon,
            "_addon_fanart": _c("_addon_fanart"),
            "_menu_art": menu_art,
            "_new_listitem": new_listitem,
            "_set_tmdb_item_info": _c("_set_tmdb_item_info"),
            "_set_tmdb_content": _c("_set_tmdb_content"),
            "_tmdb_source_select_url": _c("_tmdb_source_select_url"),
            "_tmdb_item_ctx": _c("_tmdb_item_ctx"),
            "_filter_provider_available_items": _c("_filter_provider_available_items"),
            "_filter_provider_available_items_strict": _c("_filter_provider_available_items_strict"),
            "_provider_item_available_for_tmdb": _c("_provider_item_available_for_tmdb"),
            "_filter_provider_seasons": _c("_filter_provider_seasons"),
            "_filter_provider_episodes": _c("_filter_provider_episodes"),
            "_folder_favorite_ctx": _c("_folder_favorite_ctx"),
            "WatchedMovies": history_classes["WatchedMovies"],
            "WatchedEpisodes": history_classes["WatchedEpisodes"],
            "WatchHistory": history_classes["WatchHistory"],
            "ResumePoints": history_classes["ResumePoints"],
            "pm": _c("pm"),
            "_log": log,
            "_addon_profile": _c("_addon_profile"),
            "_log_route_timing": _c("_log_route_timing"),
            "_get_setting_fast": _c("_get_setting_fast"),
        }
    )
    return True


def get_tmdb_routes_module():
    return _tmdb_routes
