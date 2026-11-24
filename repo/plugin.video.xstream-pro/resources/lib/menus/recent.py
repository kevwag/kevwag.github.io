"""Recently watched, recently added, and watched toggle actions.

Call init() after addon module globals are available.
"""

import datetime

import xbmc
import xbmcgui
import xbmcplugin

from core.ui import build_url, _new_listitem

_addon = None
_addon_handle = None
_log_fn = None
_pm = None
_t_fn = None
_prepare_playback_item_fn = None


def init(addon, addon_handle, log_fn, pm, t_fn, prepare_playback_item_fn):
    global _addon, _addon_handle, _log_fn, _pm, _t_fn
    global _prepare_playback_item_fn
    _addon = addon
    _addon_handle = addon_handle
    _log_fn = log_fn
    _pm = pm
    _t_fn = t_fn
    _prepare_playback_item_fn = prepare_playback_item_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _t(string_id, *args):
    return _t_fn(string_id, *args) if _t_fn else str(string_id)


def _render_recent_items(items, stype, profile_num=None):
    pnum = profile_num or _pm.active

    if stype == "series":
        seen_groups = {}
        for entry in items:
            series_id = entry.get("series_id")
            season_num = entry.get("season_num")
            if series_id and season_num:
                key = (series_id, season_num)
                if key not in seen_groups or entry.get("timestamp", 0) > seen_groups[
                    key
                ].get("timestamp", 0):
                    seen_groups[key] = entry
        directory_items = []
        for (series_id, season_num), entry in seen_groups.items():
            name = entry.get("name", "")
            icon = entry.get("icon", "")
            ts = entry.get("timestamp", 0)
            when = (
                datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")
                if ts
                else ""
            )
            series_name = name
            if " S" in name and "E" in name:
                parts = name.rsplit(" S", 1)
                if parts:
                    series_name = parts[0]
            label = _t(30540, series_name, season_num)
            if when:
                label += f"  [COLOR gray]({when})[/COLOR]"
            li = _new_listitem(label)
            if icon:
                li.setArt({"icon": icon, "thumb": icon, "poster": icon})
            info_tag = li.getVideoInfoTag()
            info_tag.setTitle(entry.get("title", series_name))
            info_tag.setPlot(entry.get("plot", ""))
            _prepare_playback_item_fn(li)
            q = {
                "mode": "xtream_season",
                "series_id": series_id,
                "season_num": season_num,
            }
            directory_items.append((build_url(q), li, True))
        if directory_items:
            xbmcplugin.addDirectoryItems(_addon_handle, directory_items, len(directory_items))
        return

    directory_items = []
    for entry in items:
        name = entry.get("name", "")
        url = entry.get("url", "")
        icon = entry.get("icon", "")
        ts = entry.get("timestamp", 0)
        when = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M") if ts else ""
        label = f"{name}  [COLOR gray]({when})[/COLOR]" if when else name
        li = _new_listitem(label)
        if icon:
            li.setArt({"icon": icon, "thumb": icon, "poster": icon})
        li.setProperty("IsPlayable", "true")
        info_tag = li.getVideoInfoTag()
        info_tag.setTitle(entry.get("title", name))
        info_tag.setPlot(entry.get("plot", ""))
        _prepare_playback_item_fn(li)
        q = {
            "mode": "play_stream",
            "url": url,
            "name": name,
            "icon": icon,
            "stype": stype,
            "profile_num": pnum,
        }
        directory_items.append((build_url(q), li, False))
    if directory_items:
        xbmcplugin.addDirectoryItems(_addon_handle, directory_items, len(directory_items))


def tmdb_local_recent(tmdb_type, WatchHistory):
    pnum = int(_pm.active) if _pm.active and str(_pm.active).isdigit() else 1
    stype = "series" if tmdb_type == "tv" else "movie"
    items = WatchHistory(_addon, profile_num=pnum).get_all(stype)
    if not items:
        li = _new_listitem(_t(31124))
        xbmcplugin.addDirectoryItems(_addon_handle, [("", li, False)], 1)
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return
    _render_recent_items(items, stype, pnum)
    xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def tmdb_local_in_progress(tmdb_type, ResumePoints):
    pnum = int(_pm.active) if _pm.active and str(_pm.active).isdigit() else 1
    stype = "series" if tmdb_type == "tv" else "movie"
    items = [
        i for i in ResumePoints(_addon, profile_num=pnum).get_all()
        if i.get("stype") == stype
    ]
    if not items:
        li = _new_listitem(_t(31125))
        xbmcplugin.addDirectoryItems(_addon_handle, [("", li, False)], 1)
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return
    directory_items = []
    for entry in items:
        name = entry.get("name", "")
        url = entry.get("url", "")
        icon = entry.get("icon", "")
        pos = int(entry.get("position", 0) or 0)
        dur = int(entry.get("duration", 0) or 0)
        pct = int((pos / dur) * 100) if dur else 0
        label = f"{name}  [COLOR gray]({pct}%)[/COLOR]"
        li = _new_listitem(label)
        if icon:
            li.setArt({"icon": icon, "thumb": icon, "poster": icon})
        info_tag = li.getVideoInfoTag()
        info_tag.setTitle(entry.get("title", name))
        info_tag.setPlot(entry.get("plot", ""))
        li.setProperty("IsPlayable", "true")
        li.setProperty("ResumeTime", str(pos))
        li.setProperty("TotalTime", str(dur))
        q = {
            "mode": "play_stream",
            "url": url,
            "name": name,
            "icon": icon,
            "stype": stype,
            "profile_num": pnum,
            "resume_pos": pos,
            "resume_total": dur,
        }
        if stype == "series":
            q["series_id"] = entry.get("series_id", "")
            q["season_num"] = entry.get("season_num", "")
            q["ep_id"] = entry.get("ep_id", "")
        directory_items.append((build_url(q), li, False))
    if directory_items:
        xbmcplugin.addDirectoryItems(_addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def toggle_provider_episode_watched(series_id, season_num, ep_id, WatchedEpisodes, profile_num=None):
    pnum = profile_num if profile_num is not None else (int(_pm.active) if _pm.active and str(_pm.active).isdigit() else 1)
    watched_eps = WatchedEpisodes(_addon, profile_num=pnum)
    if watched_eps.is_watched(series_id, season_num, ep_id):
        watched_eps.mark_unwatched(series_id, season_num, ep_id)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30087))
    else:
        watched_eps.mark_watched(series_id, season_num, ep_id)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30086))
    xbmc.executebuiltin("Container.Refresh")
    xbmc.executebuiltin("Container.Update(plugin://plugin.video.xstream-pro/?mode=xtream_series&series_id={0},replace)".format(series_id))


def toggle_provider_movie_watched(stream_id, WatchedMovies, profile_num=None):
    pnum = profile_num if profile_num is not None else (int(_pm.active) if _pm.active and str(_pm.active).isdigit() else 1)
    watched = WatchedMovies(_addon, profile_num=pnum)
    if watched.is_watched(stream_id):
        watched.mark_unwatched(stream_id)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30087))
    else:
        watched.mark_watched(stream_id)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30086))
    xbmc.executebuiltin("Container.Refresh")
