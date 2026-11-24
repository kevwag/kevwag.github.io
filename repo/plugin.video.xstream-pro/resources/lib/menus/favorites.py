"""Regular favorites menu and actions.

Call init() after addon module globals are available.
"""

import os
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from core.ui import build_url

_addon = None
_addon_handle = None
_log_fn = None
_pm = None
_t_fn = None
_fav = None
_get_profile_fav_fn = None
_invalidate_profile_fav_fn = None
_addon_fanart_fn = None
_menu_art_fn = None
_new_listitem_fn = None
_is_adult_category_fn = None
_epg_enabled_fn = None
_epg_class = None
_set_live_props_fn = None
_make_epg_info_fn = None
_prepare_playback_item_fn = None


def init(addon, addon_handle, log_fn, pm, t_fn, fav,
         get_profile_fav_fn, invalidate_profile_fav_fn,
         addon_fanart_fn, menu_art_fn, new_listitem_fn,
         is_adult_category_fn, epg_enabled_fn, epg_class,
         set_live_props_fn, make_epg_info_fn, prepare_playback_item_fn):
    global _addon, _addon_handle, _log_fn, _pm, _t_fn, _fav
    global _get_profile_fav_fn, _invalidate_profile_fav_fn
    global _addon_fanart_fn, _menu_art_fn, _new_listitem_fn
    global _is_adult_category_fn, _epg_enabled_fn, _epg_class
    global _set_live_props_fn, _make_epg_info_fn, _prepare_playback_item_fn
    _addon = addon
    _addon_handle = addon_handle
    _log_fn = log_fn
    _pm = pm
    _t_fn = t_fn
    _fav = fav
    _get_profile_fav_fn = get_profile_fav_fn
    _invalidate_profile_fav_fn = invalidate_profile_fav_fn
    _addon_fanart_fn = addon_fanart_fn
    _menu_art_fn = menu_art_fn
    _new_listitem_fn = new_listitem_fn
    _is_adult_category_fn = is_adult_category_fn
    _epg_enabled_fn = epg_enabled_fn
    _epg_class = epg_class
    _set_live_props_fn = set_live_props_fn
    _make_epg_info_fn = make_epg_info_fn
    _prepare_playback_item_fn = prepare_playback_item_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _t(string_id, *args):
    return _t_fn(string_id, *args) if _t_fn else str(string_id)


def _new_listitem(label=""):
    return _new_listitem_fn(label)


def _tmdb_route_url_from_source_url(url, mode, intent=None):
    try:
        parsed = urllib.parse.urlparse(url or "")
        values = urllib.parse.parse_qs(parsed.query)
        source_mode = values.get("mode", [""])[0]
        if source_mode not in ("source_select", "source_autoplay", "tmdb_source_action"):
            return ""
        query = {
            key: vals[0]
            for key, vals in values.items()
            if vals and vals[0] and key not in ("mode", "intent")
        }
        query["mode"] = mode
        if intent:
            query["intent"] = intent
        return build_url(query)
    except Exception as exc:
        _log("Favorites: TMDB route URL conversion warning: {0}".format(exc))
        return ""


def _tmdb_autoplay_url_from_source_select(url):
    return _tmdb_route_url_from_source_url(url, "source_autoplay")


def _tmdb_browse_sources_url(url):
    return _tmdb_route_url_from_source_url(url, "source_select", intent="browse")


def _tmdb_download_url(url):
    return _tmdb_route_url_from_source_url(url, "tmdb_source_action", intent="download")


def favorites_menu(folder=None, stype_filter=None):
    stype_labels = {
        "live": _t(30002),
        "movie": _t(30004),
        "series": _t(30005),
        "tmdb": "TMDB",
        "folder": _t(30808),
    }
    stype_icons = {
        "live": "DefaultAddonPVRClient.png",
        "movie": "DefaultMovies.png",
        "series": "DefaultTVShows.png",
        "tmdb": "DefaultVideo.png",
        "folder": "DefaultFolder.png",
    }
    folders = _fav.get_folders()
    protected_folders = {"Favorites", _t(30009) or "Favorites"}
    custom_folders = [f for f in folders if f not in protected_folders]

    show_counts = _addon.getSetting("show_content_counts").lower() == "true"
    if folder is None and stype_filter is None:
        fanart = _addon_fanart_fn()
        directory_items = []
        for gname in custom_folders:
            count = len(_fav.get_all(gname))
            if show_counts:
                label = f"{gname}  [COLOR gray]({count})[/COLOR]"
            else:
                label = gname
            li = _new_listitem(label)
            li.setArt(_menu_art_fn("DefaultFavourites.png", fanart))
            ctx_items = [
                (
                    _t(30320),
                    f"RunPlugin({build_url({'mode': 'fav_rename_folder', 'folder': gname})})",
                ),
                (
                    _t(30325),
                    f"RunPlugin({build_url({'mode': 'export_favorites', 'folder': gname})})",
                ),
                (
                    _t(30321),
                    f"RunPlugin({build_url({'mode': 'fav_delete_folder', 'folder': gname})})",
                ),
            ]
            li.addContextMenuItems(ctx_items)
            q = {"mode": "favorites_menu", "folder": gname}
            directory_items.append((build_url(q), li, True))
        li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30210)))
        directory_items.append((build_url({"mode": "fav_new_folder"}), li, False))
        if directory_items:
            xbmcplugin.addDirectoryItems(_addon_handle, directory_items)
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    if folder and stype_filter is None:
        items = _fav.get_all(folder)
        if not items:
            li = _new_listitem("[COLOR gray]{0}[/COLOR]".format(_t(30211)))
            xbmcplugin.addDirectoryItems(_addon_handle, [("", li, False)], 1)
            xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
            return

        type_order = ["live", "movie", "series", "tmdb", "folder"]
        items_by_type = {}
        for item in items:
            st = item.get("stype", "live")
            items_by_type.setdefault(st, []).append(item)

        show_separators = len(items_by_type) > 1
        for st in type_order:
            if st not in items_by_type:
                continue
            if show_separators:
                label = stype_labels.get(st, st)
                sep = _new_listitem(
                    f"[COLOR gray]────── {label} ──────[/COLOR]"
                )
                sep.setArt({"icon": stype_icons.get(st, "DefaultFolder.png")})
                sep.setProperty("IsPlayable", "false")
                ctx = [
                    (
                        _t(30813).format(label),
                        f"RunPlugin({build_url({'mode': 'fav_remove_by_type', 'folder': folder, 'stype': st})})",
                    )
                ]
                sep.addContextMenuItems(ctx)
                xbmcplugin.addDirectoryItems(_addon_handle, [("", sep, False)], 1)
            _fav_render_items(items_by_type[st], source_folder=folder)

        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    if folder and stype_filter:
        items = [i for i in _fav.get_all(folder) if i.get("stype") == stype_filter]
        if not items:
            li = _new_listitem("[COLOR gray]{0}[/COLOR]".format(_t(30212)))
            xbmcplugin.addDirectoryItems(_addon_handle, [("", li, False)], 1)
            xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
            return
        _fav_render_items(items, source_folder=folder)
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _fav_render_items(items, source_folder=None, profile_num=None):
    """Render a list of favorite items with context menus."""
    if profile_num:
        fav_instance = _get_profile_fav_fn(profile_num)
        remove_mode = "profile_fav_remove"
    else:
        fav_instance = _fav
        remove_mode = "fav_remove"

    hide_adult = _addon.getSetting("hide_adult_categories").lower() == "true"
    if hide_adult:
        items = [
            i
            for i in items
            if not _is_adult_category_fn(
                i.get("name", "") + " " + i.get("category_name", "")
            )
        ]
    has_live = any(i.get("stype", "live") == "live" for i in items)
    epg = None
    if has_live and _epg_enabled_fn():
        epg = _epg_class(_addon, profile_num=profile_num or _pm.active)
        epg.load()
    directory_items = []
    for item in items:
        stype = item.get("stype", "live")
        name = item.get("name", "Unknown")
        li = _new_listitem(name)
        info_tag = li.getVideoInfoTag()
        info_tag.setMediaType("video")
        info_tag.setTitle(name)
        if item.get("icon"):
            li.setArt({"icon": item["icon"], "thumb": item["icon"]})
        tmdb_autoplay_url = ""
        if stype == "tmdb" and (_addon.getSetting("source_auto_play_first") or "true").lower() == "true":
            tmdb_autoplay_url = _tmdb_autoplay_url_from_source_select(item.get("url", ""))
        if stype not in ("folder", "tmdb") or tmdb_autoplay_url:
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item_fn(li)
        plot = ""
        current_title = ""
        if stype == "live":
            _set_live_props_fn(li)
            plot, display_name, current_title = (
                _make_epg_info_fn(epg, item.get("epg_id", ""), name)
                if epg
                else ("", name, "")
            )
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(current_title or name)
            info_tag.setPlot(plot)
        remove_folder = source_folder or "__all__"
        if profile_num:
            ctx = [
                (
                    _t(30545),
                    f"RunPlugin({build_url({'mode': remove_mode, 'id': item.get('id'), 'folder': remove_folder, 'pnum': profile_num})})",
                ),
            ]
        else:
            ctx = [
                (
                    _t(30545),
                    f"RunPlugin({build_url({'mode': remove_mode, 'id': item.get('id'), 'folder': remove_folder})})",
                ),
            ]
        if not profile_num:
            protected_folders = {"Favorites", _t(30009) or "Favorites"}
            for gname in fav_instance.get_folders():
                if gname in protected_folders or (source_folder and gname == source_folder):
                    continue
                ctx.append(
                    (
                        _t(30215).format(gname),
                        f"RunPlugin({build_url({'mode': 'toggle_fav', 'id': item.get('id'), 'name': name, 'stype': stype, 'icon': item.get('icon', ''), 'url': item.get('url', ''), 'epg_id': item.get('epg_id', ''), 'folder': gname})})",
                    )
                )
        if stype == "tmdb":
            browse_url = _tmdb_browse_sources_url(item.get("url", ""))
            if browse_url:
                ctx.append(("Browse Sources", "ActivateWindow(Videos,{0},return)".format(browse_url)))
            download_url = _tmdb_download_url(item.get("url", ""))
            if download_url:
                ctx.append((_t(30941), "RunPlugin({0})".format(download_url)))
        li.addContextMenuItems(ctx)
        if stype == "live":
            q = {
                "mode": "play_stream",
                "url": item.get("url"),
                "name": name,
                "title": current_title or name,
                "plot": plot,
                "icon": item.get("icon", ""),
                "profile_num": profile_num or _pm.active,
            }
            item_url = build_url(q)
        elif stype == "tmdb":
            item_url = tmdb_autoplay_url or item.get("url")
        else:
            item_url = item.get("url")
        directory_items.append((
            item_url,
            li,
            stype in ("series", "folder") or (stype == "tmdb" and not tmdb_autoplay_url),
        ))
    if directory_items:
        xbmcplugin.addDirectoryItems(_addon_handle, directory_items, len(directory_items))


def toggle_favorite(
    item_id,
    name,
    stype,
    icon,
    url,
    epg_id="",
    folder=None,
    catchup="",
    catchup_source="",
    catchup_days="",
):
    if folder is None:
        folder = _t(30009) or "Favorites"
    item = {
        "id": item_id,
        "name": name,
        "stype": stype,
        "icon": icon,
        "url": url,
        "epg_id": epg_id,
        "catchup": catchup,
        "catchup_source": catchup_source,
        "catchup_days": catchup_days,
    }
    if _fav.is_favorite(item_id, folder):
        _fav.remove(item_id, folder)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30085).format(folder))
        xbmc.executebuiltin("Container.Refresh")
        return
    _fav.add(item, folder)
    xbmcgui.Dialog().notification("Xstream Pro", _t(30084).format(folder))
    xbmc.executebuiltin("Container.Refresh")


def toggle_profile_favorite(item_id, name, stype, icon, url, epg_id="", profile_num=1):
    pnum = int(profile_num)
    profile_fav = _get_profile_fav_fn(pnum)
    item = {
        "id": item_id,
        "name": name,
        "stype": stype,
        "icon": icon,
        "url": url,
        "epg_id": epg_id,
    }
    if profile_fav.is_favorite(item["id"]):
        profile_fav.remove(item["id"])
        xbmcgui.Dialog().notification("Xstream Pro", _t(30747))
    else:
        profile_fav.add(item)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30746))
    _invalidate_profile_fav_fn(pnum)
    xbmc.executebuiltin("Container.Refresh")


def fav_new_folder():
    name = xbmcgui.Dialog().input(_t(30143))
    if name:
        _fav.create_folder(name)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30094).format(name))
        xbmc.executebuiltin("Container.Refresh")


def fav_rename_folder(fname):
    if fname:
        new_name = xbmcgui.Dialog().input(_t(30144), defaultt=fname)
        if new_name and new_name != fname:
            _fav.rename_folder(fname, new_name)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30095).format(new_name))
            xbmc.executebuiltin("Container.Refresh")


def fav_delete_folder(fname):
    protected_folders = {"Favorites", _t(30009) or "Favorites"}
    if fname and fname not in protected_folders:
        if xbmcgui.Dialog().yesno(_t(30038), _t(30066).format(fname)):
            _fav.delete_folder(fname)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30096).format(fname))
            xbmc.executebuiltin("Container.Refresh")


def fav_move(item_id, from_folder):
    folders = [f for f in _fav.get_folders() if f != from_folder]
    if not folders:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30124))
    else:
        idx = xbmcgui.Dialog().select(_t(30145), folders)
        if idx >= 0:
            source_items = _fav.get_all(from_folder)
            item_data = next((i for i in source_items if i.get("id") == item_id), None)
            if item_data:
                _fav.remove(item_id, from_folder)
                _fav.add(item_data, folders[idx])
                xbmcgui.Dialog().notification(
                    "Xstream Pro", _t(30097).format(folders[idx])
                )
                xbmc.executebuiltin("Container.Refresh")


def export_favorites(folder=None):
    path = xbmcgui.Dialog().browseSingle(3, _t(30338), "files")
    if path:
        export_name = f"favorites_{folder}.m3u" if folder else "favorites.m3u"
        full_path = os.path.join(path, export_name)
        count = _fav.export_m3u(full_path, folder)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30116).format(count))


def fav_remove(item_id, folder="__all__"):
    if folder == "__all__":
        _fav.remove(item_id)
    else:
        _fav.remove(item_id, folder)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30085).format(folder))
    xbmc.executebuiltin("Container.Refresh")


def fav_remove_by_type(folder, stype):
    if folder and stype:
        stype_labels = {
            "live": _t(30002),
            "movie": _t(30004),
            "series": _t(30005),
            "tmdb": "TMDB",
            "folder": _t(30808),
        }
        label = stype_labels.get(stype, stype)
        if xbmcgui.Dialog().yesno(_t(30813).format(label), _t(30815)):
            removed = _fav.remove_by_type(folder, stype)
            if removed:
                xbmcgui.Dialog().notification("Xstream Pro", _t(30814))
            xbmc.executebuiltin("Container.Refresh")
