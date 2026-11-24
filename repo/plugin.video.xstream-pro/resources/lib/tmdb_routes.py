"""Native route builders for direct TMDB and Trakt menus.

All routes use the xstream_tmdb_* or xstream_trakt_* prefix and are
dispatched from addon.py via _setup_tmdb_routes().
"""
import datetime
import json
import os
import random
import threading

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

import tmdb
import trakt
import cache

MERGE_PAGES_DEFAULT = 1
MERGE_PAGES_TRAKT = 1
MERGE_PAGES_PROVIDER = 8
PROVIDER_PAGE_SIZE = 20
PROVIDER_SCAN_MAX_PAGES = 80
PROVIDER_FILTER_CACHE_TTL = 21600


def _is_tvos():
    if not xbmc.getCondVisibility("System.Platform.OSX"):
        return False
    try:
        profile = xbmcvfs.translatePath("special://masterprofile/")
        return "Containers" in profile or "Library/Caches/Kodi" in profile
    except Exception:
        return False


def _tvos_sleep(ms):
    if _is_tvos() and ms > 500:
        return max(ms // 3, 500)
    return ms


def _safe_fsync(fh):
    try:
        fh.flush()
    except Exception:
        pass
    try:
        if _is_tvos():
            return
        os.fsync(fh.fileno())
    except OSError:
        pass


_CTX = {}


def setup(context):
    global _CTX
    _CTX = dict(context or {})


def c(name):
    return _CTX[name]

def _t(string_id, *args):
    return c("_t")(string_id, *args)


def _addon_profile_dir():
    profile_fn = _CTX.get("_addon_profile")
    if callable(profile_fn):
        return profile_fn()
    return xbmcvfs.translatePath(c("addon").getAddonInfo("profile"))

_UI_LABEL_IDS = {
    "Search": 30007,
    "Animations": 31238,
    "No studios found": 31174,

    "Advanced Discover": 31177,
    "High Rating": 31179,
    "Most Voted": 31180,
    "Released This Year": 31181,
    "First Aired This Year": 31182,
    "Sort By": 31184,
    "Search Collection": 31235,
    "Search Company": 31236,
    "Search Keyword": 31237,
    "Add Rule": 31247,
    "Save Discover": 31248,
    "Search Network": 31249,
    "No certifications available": 31250,
    "No filters to save": 31253,
    "Save Discover As": 31254,
    "Failed to save discover": 31255,
    "Saved discover not found": 31256,
    "Trakt authorization cancelled or expired": 31258,
    "Trakt authorization failed": 31259,
    "Disconnect Trakt account?": 31260,
    "Trakt disconnected": 31261,
    "Authorize Trakt": 31262,
    "Authorize Trakt first": 31263,
    "Search Trakt Lists": 31264,
    "Advanced Discover TV": 31421,
    "High Rating TV": 31422,
    "Most Voted TV": 31423,
    "Random Watched TV": 31424,
    "No Trakt list selected": 31265,
    "No TMDB ID for Trakt action": 31266,
    "Trakt action failed": 31267,
    "Random Watched": 31268,
    "Random Watched Combined": 31269,
    "No genres found": 31270,
    "No Trakt lists found": 31271,
    "Award Winners Search": 31272,
    "Search Award Keyword": 31273,
    "No keyword match found": 31274,
    "No keyword ID found": 31275,
    "Trending Collections": 31276,
    "Popular Collections": 31277,
    "Top Rated Collections": 31278,
    "Box Office Collections": 31279,
    "Most Voted Collections": 31280,
    "Saved Collections": 31281,
    "Universes": 31282,
    "TV collection not found": 31283,
    "No trailer found": 31284,
    "No TMDB movie selected": 31285,
    "No collection found": 31286,
    "Movie Credits": 31287,
    "TV Credits": 31288,
    "High vote threshold — results may be empty": 31289,
    "Sort Order": 31301,
    "Person": 31302,
    "Network": 31303,
    "Company": 31304,
    "Certification Country": 31305,
    "Genre": 31306,
    "Watch Provider": 31308,
    "Keyword": 31309,
    "Language": 31325,
    "No saved discovers": 31330,
    "Trakt Authorization": 31331,
    "Trakt Options": 31349,
    "No collections found": 31362,
    "No saved collections": 31363,
    "No people found": 31364,
    "Search Collections": 31375,
    "Unknown Collection": 31376,
    "Save Collection": 31377,
    "Remove from Saved Collections": 31378,
    "Search Companies": 31379,
    "Unknown Company": 31380,
    "Search Keywords": 31381,
    "Unknown Keyword": 31382,
    "Search People": 31383,
    "Add to Favorites": 31384,
    "Remove from Favorites": 31385,
}
def _label(value):
    if isinstance(value, int):
        return _t(value)
    if isinstance(value, str):
        string_id = _UI_LABEL_IDS.get(value)
        if string_id:
            return _t(string_id)
    return value

def _gray(text):
    return "[COLOR gray]{0}[/COLOR]".format(text)

def _bold(text):
    return "[B]{0}[/B]".format(text)


def _param(params, name, default=""):
    value = (params or {}).get(name, [default])
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def _int_param(params, name, default=1):
    try:
        return max(1, int(_param(params, name, default) or default))
    except Exception:
        return default


def _bool_param(params, name):
    return str(_param(params, name, "")).lower() == "true"


def _query(params):
    out = {}
    for key, value in (params or {}).items():
        if isinstance(value, (list, tuple)):
            out[key] = value[0] if value else ""
        else:
            out[key] = value
    return out


def _enabled():
    return c("addon").getSetting("tmdb_enabled").lower() != "false"


def _api_ready():
    return bool(tmdb.api_key())


def _notify_missing_key():
    xbmcgui.Dialog().notification("Xstream Pro", _t(31149))


def _end_empty(label=31149):
    label = _label(label)
    li = c("_new_listitem")(label)
    li.setArt(c("_menu_art")(c("_local_icon")("themoviedb"), c("_addon_fanart")()))
    xbmcplugin.addDirectoryItem(c("addon_handle"), "", li, False)
    xbmcplugin.endOfDirectory(c("addon_handle"))


def _guard():
    if not _enabled():
        _end_empty(31226)
        return False
    if not _api_ready():
        _notify_missing_key()
        _end_empty()
        return False
    return True


def _handle_error(exc):
    c("_log")("Direct TMDB route error: {0}".format(exc))
    _end_empty(_t(31299, exc))


def _trakt_guard(auth=False):
    if not trakt.enabled():
        _end_empty(31227)
        return False
    if auth:
        if not trakt.auth_configured():
            _end_empty("Trakt account authorization requires a client ID and client secret in settings.")
            return False
    else:
        if not trakt.public_configured():
            _end_empty("Trakt client ID is required. Add it in settings.")
            return False
    return True


def _trakt_handle_error(exc):
    c("_log")("Direct Trakt route error: {0}".format(exc))
    _end_empty(_t(31300, exc))


def _add_items(items, content=""):
    if content:
        xbmcplugin.setContent(c("addon_handle"), content)
    xbmcplugin.addDirectoryItems(c("addon_handle"), items)
    xbmcplugin.endOfDirectory(c("addon_handle"))
    timing = _CTX.get("_log_route_timing")
    if timing:
        timing()


def _folder_item(label, params, icon_name="themoviedb"):
    label = _label(label)
    icon = c("_local_icon")(icon_name)
    fanart = c("_addon_fanart")()
    li = c("_new_listitem")(label)
    li.setArt(c("_menu_art")(icon, fanart))
    url = c("build_url")(params)
    li.addContextMenuItems(c("_folder_favorite_ctx")(label, url, icon))
    return url, li, True


def _resolve_menu_value(value):
    return value() if callable(value) else value


def _menu_item(spec):
    query = {}
    for key, value in (spec.get("query") or {}).items():
        query[key] = _resolve_menu_value(value)
    label = _resolve_menu_value(spec.get("label"))
    return _folder_item(label, query, spec.get("icon", "themoviedb"))


def _menu_items(specs):
    return [_menu_item(spec) for spec in specs]


_MOVIES_MENU_MODEL = (
    {"label": lambda: "Recently Added", "query": {"mode": "recently_added_menu", "type": "movie"}, "icon": "recent"},
    {"label": 30925, "query": {"mode": "xstream_trakt_public", "section": "trending", "tmdb_type": "movie"}, "icon": "trending"},
    {"label": 30996, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "trending_day"}, "icon": "trending"},
    {"label": 30999, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "trending_week"}, "icon": "trending"},
    {"label": 30994, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "popular"}, "icon": "popular"},
    {"label": 30911, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "top_rated"}, "icon": "top_rated"},
    {"label": 30914, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "upcoming", "filter_provider": "false", "mark_unavailable": "true"}, "icon": "upcoming"},
    {"label": 30915, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "now_playing", "filter_provider": "false", "mark_unavailable": "true"}, "icon": "in_theatres"},
    {"label": 30929, "query": {"mode": "xstream_trakt_public", "section": "boxoffice", "tmdb_type": "movie"}, "icon": "top_10_box_office"},
    {"label": 30963, "query": {"mode": "xstream_tmdb_collections_menu"}, "icon": "collections"},
    {"label": 30927, "query": {"mode": "xstream_trakt_public", "section": "watched", "tmdb_type": "movie", "period": "weekly"}, "icon": "most_watched"},
    {"label": 30928, "query": {"mode": "xstream_trakt_public", "section": "anticipated", "tmdb_type": "movie", "filter_provider": "false", "mark_unavailable": "true"}, "icon": "anticipated"},
    {"label": 30918, "query": {"mode": "xstream_tmdb_genres", "tmdb_type": "movie"}, "icon": "genres"},
    {"label": 30920, "query": {"mode": "xstream_tmdb_watch_providers", "tmdb_type": "movie"}, "icon": "providers"},
    {"label": 30921, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "revenue"}, "icon": "highest_revenue"},
    {"label": 30922, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "movie", "list_name": "most_voted"}, "icon": "most_voted"},
    {"label": 31040, "query": {"mode": "xstream_tmdb_discover", "tmdb_type": "movie", "sort_by": "vote_average.desc", "vote_count_gte": "250"}, "icon": "recommended"},
    {"label": 31042, "query": {"mode": "xstream_tmdb_because_watched", "tmdb_type": "movie"}, "icon": "because_you_watched"},
    {"label": 31126, "query": {"mode": "xstream_tmdb_years_menu", "tmdb_type": "movie"}, "icon": "years"},
    {"label": 31127, "query": {"mode": "xstream_tmdb_decades_menu", "tmdb_type": "movie"}, "icon": "decades"},
    {"label": 31122, "query": {"mode": "tmdb_local_recent", "tmdb_type": "movie"}, "icon": "recent"},
    {"label": 31034, "query": {"mode": "tmdb_local_in_progress", "tmdb_type": "movie"}, "icon": "in_progress"},
    {"label": 30990, "query": {"mode": "xstream_tmdb_search", "tmdb_type": "movie", "prompt": "true"}, "icon": "search"},
)
_TV_MENU_MODEL = (
    {"label": lambda: "Recently Added", "query": {"mode": "recently_added_menu", "type": "series"}, "icon": "recent"},
    {"label": 30925, "query": {"mode": "xstream_trakt_public", "section": "trending", "tmdb_type": "tv"}, "icon": "trending"},
    {"label": 30997, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "trending_day"}, "icon": "trending"},
    {"label": 31000, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "trending_week"}, "icon": "trending"},
    {"label": 30995, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "popular"}, "icon": "popular"},
    {"label": 30911, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "top_rated"}, "icon": "top_rated"},
    {"label": 30916, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "airing_today", "filter_provider": "false", "mark_unavailable": "true"}, "icon": "airing_today"},
    {"label": 30917, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "on_the_air", "filter_provider": "false", "mark_unavailable": "true"}, "icon": "currently_airing"},
    {"label": 30927, "query": {"mode": "xstream_trakt_public", "section": "watched", "tmdb_type": "tv", "period": "weekly"}, "icon": "most_watched"},
    {"label": 30963, "query": {"mode": "xstream_tmdb_tv_collections_menu"}, "icon": "collections"},
    {"label": 30928, "query": {"mode": "xstream_trakt_public", "section": "anticipated", "tmdb_type": "tv", "filter_provider": "false", "mark_unavailable": "true"}, "icon": "anticipated"},
    {"label": 30918, "query": {"mode": "xstream_tmdb_genres", "tmdb_type": "tv"}, "icon": "genres"},
    {"label": 30920, "query": {"mode": "xstream_tmdb_watch_providers", "tmdb_type": "tv"}, "icon": "providers"},
    {"label": 30922, "query": {"mode": "xstream_tmdb_list", "tmdb_type": "tv", "list_name": "most_voted"}, "icon": "most_voted"},
    {"label": 31041, "query": {"mode": "xstream_tmdb_discover", "tmdb_type": "tv", "sort_by": "vote_average.desc", "vote_count_gte": "250"}, "icon": "recommended"},
    {"label": 31043, "query": {"mode": "xstream_tmdb_because_watched", "tmdb_type": "tv"}, "icon": "because_you_watched"},
    {"label": 31130, "query": {"mode": "xstream_tmdb_discover", "tmdb_type": "tv", "sort_by": "first_air_date.desc", "date_gte": lambda: _date_days_ago(365), "date_lte": lambda: _today()}, "icon": "calendar"},
    {"label": lambda: "{0} {1}".format(_t(31126), _t(31372)), "query": {"mode": "xstream_tmdb_years_menu", "tmdb_type": "tv"}, "icon": "years"},
    {"label": lambda: "{0} {1}".format(_t(31127), _t(31372)), "query": {"mode": "xstream_tmdb_decades_menu", "tmdb_type": "tv"}, "icon": "decades"},
    {"label": 31123, "query": {"mode": "tmdb_local_recent", "tmdb_type": "tv"}, "icon": "recent"},
    {"label": 31035, "query": {"mode": "tmdb_local_in_progress", "tmdb_type": "tv"}, "icon": "in_progress"},
    {"label": 30991, "query": {"mode": "xstream_tmdb_search", "tmdb_type": "tv", "prompt": "true"}, "icon": "search"},
)


def _watchers():
    pnum = 1
    active = getattr(c("pm"), "active", "1")
    if str(active).isdigit():
        pnum = int(active)
    return c("WatchedMovies")(c("addon"), profile_num=pnum), c("WatchedEpisodes")(c("addon"), profile_num=pnum)


def _hide_watched_enabled():
    try:
        return (c("addon").getSetting("show_watched_items") or "true").lower() == "false"
    except Exception:
        return False


def _is_watched(item, wm, we):
    tmdb_type = item.get("tmdb_type") or "movie"
    tmdb_id = str(item.get("tmdb_id") or "")
    season = str(item.get("season") or "")
    episode = str(item.get("episode") or "")
    kind = item.get("kind") or ("episode" if episode else ("season" if season else ("tvshow" if tmdb_type == "tv" else "movie")))
    if not tmdb_id:
        return False
    if tmdb_type == "movie":
        return wm.is_watched(tmdb_id)
    if episode and season:
        return (
            we.is_watched(tmdb_id, season, episode)
            or wm.is_watched("tvshow:{0}".format(tmdb_id))
            or wm.is_watched("season:{0}:{1}".format(tmdb_id, season))
        )
    if kind == "season" and season:
        return wm.is_watched("season:{0}:{1}".format(tmdb_id, season))
    return wm.is_watched("tvshow:{0}".format(tmdb_id))


def _source_auto_play_first_enabled():
    try:
        getter = c("_get_setting_fast")
        if getter:
            return getter("source_auto_play_first", "true").lower() == "true"
        return c("addon").getSetting("source_auto_play_first").lower() == "true"
    except Exception:
        return False


def _maybe_rpdb_poster(item):
    addon = _CTX.get("addon")
    if not addon:
        return item.get("poster") or ""
    get_setting = _CTX.get("_get_setting_fast") or addon.getSetting
    enabled = get_setting("rpdb_enabled") or "None"
    if enabled == "None":
        return item.get("poster") or ""
    tmdb_type = item.get("tmdb_type") or "movie"
    if tmdb_type == "movie" and enabled not in ("Movies", "Both"):
        return item.get("poster") or ""
    if tmdb_type == "tv" and enabled not in ("TV Shows", "Both"):
        return item.get("poster") or ""
    tmdb_id = item.get("tmdb_id")
    if not tmdb_id:
        return item.get("poster") or ""
    api_key = (get_setting("rpdb_api_key") or "t0-free-rpdb").strip()
    if not api_key:
        return item.get("poster") or ""
    if tmdb_type == "movie":
        url = "https://api.ratingposterdb.com/{0}/tmdb/poster-default/movie-{1}.jpg?fallback=true".format(api_key, tmdb_id)
    else:
        url = "https://api.ratingposterdb.com/{0}/tmdb/poster-default/series-{1}.jpg?fallback=true".format(api_key, tmdb_id)
    style = get_setting("rpdb_format") or "Default"
    style_map = {
        "Blocks": "&theme=blocks",
        "Rounded Blocks": "&theme=rounded-blocks",
    }
    if style in style_map:
        url += style_map[style]
    return url


def _media_item(item, wm=None, we=None, mark_unavailable=False):
    tmdb_type = item.get("tmdb_type") or "movie"
    tmdb_id = str(item.get("tmdb_id") or "")
    title = item.get("title") or "Unknown"
    year = str(item.get("year") or "")
    season = str(item.get("season") or "")
    episode = str(item.get("episode") or "")
    showtitle = item.get("showtitle") or item.get("tvshowtitle") or ""
    kind = item.get("kind") or ("episode" if episode else ("season" if season else ("tvshow" if tmdb_type == "tv" else "movie")))
    display_title = title
    if mark_unavailable and not _provider_item_available(item, strict_title_year=True):
        display_title = "[COLOR red]●[/COLOR] {0}".format(title)
    icon = item.get("poster") or item.get("fanart") or c("_local_icon")("themoviedb")
    poster = _maybe_rpdb_poster(item) or item.get("poster") or icon
    fanart = item.get("fanart") or ""
    art = {
        "poster": poster,
        "thumb": poster,
        "icon": icon,
        "fanart": fanart,
    }
    watched = _is_watched(item, wm, we) if wm and we else False
    playcount = 1 if watched else 0
    li = c("_new_listitem")(display_title)
    c("_set_tmdb_item_info")(
        li,
        title,
        icon,
        art,
        tmdb_type,
        year,
        item.get("plot", ""),
        season,
        episode,
        playcount,
        item.get("runtime", ""),
        item.get("cast"),
        item.get("genre"),
        item.get("director"),
        item.get("writer"),
        item.get("studio"),
        item.get("mpaa", ""),
        item.get("tagline", ""),
        item.get("rating", ""),
        item.get("votes", ""),
        item.get("premiered", ""),
        item.get("fanart", ""),
    )
    if watched:
        li.setProperty("Watched", "true")
        li.setProperty("Overlay", "5")
    li.setArt({
        "icon": icon,
        "thumb": poster,
        "poster": poster,
        "fanart": fanart,
    })
    li.addContextMenuItems(c("_tmdb_item_ctx")(title, icon, year, tmdb_type, tmdb_id, season, episode, showtitle, kind, is_watched=watched))
    if tmdb_type:
        li.setProperty("tmdb_type", tmdb_type)
    if tmdb_id:
        li.setProperty("tmdb_id", tmdb_id)
    if tmdb_type == "tv" and kind == "tvshow" and not season and not episode:
        url = c("build_url")({"mode": "xstream_tmdb_seasons", "tmdb_id": tmdb_id, "title": title, "year": year})
        return url, li, True
    if tmdb_type == "tv" and kind == "season":
        url = c("build_url")({"mode": "xstream_tmdb_episodes", "tmdb_id": tmdb_id, "title": showtitle or title, "year": year, "season": season})
        return url, li, True
    if not tmdb_id:
        li.setProperty("IsPlayable", "false")
        return "", li, False
    url = c("_tmdb_source_select_url")(title, year, tmdb_type, tmdb_id, season, episode, showname=showtitle)
    if _source_auto_play_first_enabled():
        url = c("build_url")({
            "mode": "source_autoplay",
            "title": title,
            "year": year,
            "tmdb_type": tmdb_type,
            "tmdb_id": tmdb_id,
            "showname": showtitle,
            "season": season,
            "episode": episode,
        })
        li.setProperty("IsPlayable", "true")
        return url, li, False
    return url, li, True


def _next_page_item(params, page, total_pages):
    if page >= min(total_pages, 500):
        return None
    query = _query(params)
    query.pop("prompt", None)
    query.pop("new_search", None)
    query["page"] = str(page + 1)
    return _folder_item(_t(31240, page + 1), query, "next")


def _page_results_data(results, params, per_page=PROVIDER_PAGE_SIZE):
    page = max(1, _int_param(params, "page") or 1)
    per_page = max(1, int(per_page or PROVIDER_PAGE_SIZE))
    results = list(results or [])

    total = len(results)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    start = (page - 1) * per_page
    end = start + per_page

    return {
        "page": page,
        "total_pages": total_pages,
        "results": results[start:end],
        "raw": {},
        "exact_page_size": per_page,
    }


def _unique_movie_collections():
    seen_ids = set()
    seen_names = set()
    out = []

    for name, collection_id in _COLLECTIONS:
        cid = str(collection_id or "").strip()
        label = str(name or "").strip()
        key_name = label.lower()

        if not cid or not label:
            continue
        if cid in seen_ids or key_name in seen_names:
            continue

        seen_ids.add(cid)
        seen_names.add(key_name)
        out.append((label, cid))

    return out


def _unique_tv_collections():
    seen_slugs = set()
    seen_labels = set()
    out = []

    for item in list(_TV_COLLECTIONS) + list(_TV_COLLECTIONS_EXTRA):
        try:
            slug, label, refs, poster_path, backdrop_path = item
        except Exception:
            continue

        slug = str(slug or "").strip()
        label = str(label or "").strip()
        key_label = label.lower()

        if not slug or not label:
            continue
        if slug in seen_slugs or key_label in seen_labels:
            continue

        seen_slugs.add(slug)
        seen_labels.add(key_label)
        out.append((slug, label, refs, poster_path, backdrop_path))

    return out


def _visible_random_count(results):
    results = list(results or [])
    if not results:
        return 0
    if _provider_only_enabled():
        return len(_filter_provider_available_results(results))
    return len(results)


def _merge_tmdb_meta(item, meta):
    if not meta:
        return item
    merged = dict(item)
    for key in ("poster", "fanart", "plot", "rating", "votes", "premiered", "title", "year"):
        if not merged.get(key) and meta.get(key):
            merged[key] = meta[key]
    if not merged.get("runtime") and meta.get("runtime"):
        merged["runtime"] = meta["runtime"]
    if not merged.get("genre") and meta.get("genre"):
        merged["genre"] = meta["genre"]
    if not merged.get("cast") and meta.get("cast"):
        merged["cast"] = meta["cast"]
    if not merged.get("director") and meta.get("director"):
        merged["director"] = meta["director"]
    if not merged.get("writer") and meta.get("writer"):
        merged["writer"] = meta["writer"]
    if not merged.get("studio") and meta.get("studio"):
        merged["studio"] = meta["studio"]
    if not merged.get("mpaa") and meta.get("mpaa"):
        merged["mpaa"] = meta["mpaa"]
    if not merged.get("tagline") and meta.get("tagline"):
        merged["tagline"] = meta["tagline"]
    return merged


def _needs_meta_enrichment(item):
    if not item.get("tmdb_id"):
        return False
    if not item.get("poster"):
        return True
    if not item.get("runtime") and not item.get("genre") and not item.get("cast"):
        return True
    return False


def _hydrate_from_tmdb_meta_cache(items, sync_limit=20, prefetch_limit=40):
    pairs = []
    for item in items or []:
        if _needs_meta_enrichment(item):
            pairs.append((item.get("tmdb_type") or "movie", item.get("tmdb_id")))
    cached = tmdb.meta_cache_get_many(pairs) if pairs else {}
    out = []
    missing = []
    for item in items or []:
        if not _needs_meta_enrichment(item):
            out.append(item)
            continue
        tmdb_type = tmdb.normalize_media_type(item.get("tmdb_type") or "movie")
        tmdb_id = str(item.get("tmdb_id") or "")
        data = cached.get((tmdb_type, tmdb_id))
        if data:
            out.append(_merge_tmdb_meta(item, data))
        else:
            missing.append((tmdb_type, tmdb_id))
            out.append(item)
    if missing:
        c("_log")("TMDB meta cache misses: {0}".format(len(missing)))
        sync_count = max(0, int(sync_limit or 0))
        _bg = None
        if sync_count and len(missing) > 0:
            _bg = xbmcgui.DialogProgressBG()
            _bg.create("Xstream Pro", "Loading metadata...")
        fetched = {}
        for idx, (tmdb_type, tmdb_id) in enumerate(missing[:sync_count]):
            if _bg:
                pct = int((idx + 1) / min(sync_count, len(missing)) * 100)
                _bg.update(pct, "Xstream Pro", "Loading {0} metadata...".format(tmdb_type.capitalize()))
            try:
                fetched[(tmdb_type, tmdb_id)] = tmdb.meta_summary_cached(tmdb_type, tmdb_id)
            except Exception:
                pass
        if _bg:
            _bg.close()
        if fetched:
            out = [
                _merge_tmdb_meta(
                    item,
                    fetched.get((tmdb.normalize_media_type(item.get("tmdb_type") or "movie"), str(item.get("tmdb_id") or ""))),
                )
                for item in out
            ]
        remaining = missing[sync_count:]
        if remaining and prefetch_limit:
            _queue_missing_tmdb_art_prefetch(
                [{"tmdb_type": t, "tmdb_id": i} for t, i in remaining[:prefetch_limit]],
                limit=max(0, int(prefetch_limit or 0)),
            )
    return out


def _hydrate_trakt_items(items, sync_limit=0, prefetch_limit=0):
    pairs = []
    for item in items or []:
        if _needs_meta_enrichment(item):
            pairs.append((item.get("tmdb_type") or "movie", item.get("tmdb_id")))
    cached = tmdb.meta_cache_get_many(pairs) if pairs else {}
    out = []
    missing = []
    for item in items or []:
        tmdb_id = str(item.get("tmdb_id") or "")
        tmdb_type = tmdb.normalize_media_type(item.get("tmdb_type") or "movie")
        if not _needs_meta_enrichment(item):
            out.append(item)
            continue
        data = cached.get((tmdb_type, tmdb_id))
        if data:
            out.append(_merge_tmdb_meta(item, data))
        else:
            missing.append((tmdb_type, tmdb_id))
            out.append(item)
    if missing:
        c("_log")("TMDB metadata cache misses: {0}".format(len(missing)))
    sync_count = max(0, int(sync_limit or 0))
    if missing and sync_count:
        _bg = xbmcgui.DialogProgressBG()
        _bg.create("Xstream Pro", "Loading metadata...")
        fetched = {}
        for idx, (tmdb_type, tmdb_id) in enumerate(missing[:sync_count]):
            pct = int((idx + 1) / min(sync_count, len(missing)) * 100)
            _bg.update(pct, "Xstream Pro", "Loading {0} metadata...".format(tmdb_type.capitalize()))
            try:
                fetched[(tmdb_type, tmdb_id)] = tmdb.meta_summary_cached(tmdb_type, tmdb_id)
            except Exception:
                pass
        _bg.close()
        if fetched:
            out = [
                _merge_tmdb_meta(
                    item,
                    fetched.get((tmdb.normalize_media_type(item.get("tmdb_type") or "movie"), str(item.get("tmdb_id") or ""))),
                )
                for item in out
            ]
    if missing and prefetch_limit:
        _queue_missing_tmdb_art_prefetch(
            [{"tmdb_type": t, "tmdb_id": i} for t, i in missing[sync_count:]],
            limit=max(0, int(prefetch_limit or 0)),
        )
    return out


def _queue_missing_tmdb_art_prefetch(items, limit=20):
    global _PREFETCH_IN_FLIGHT
    missing = []
    with _PREFETCH_IN_FLIGHT_LOCK:
        for item in items or []:
            if item.get("poster") or not item.get("tmdb_id"):
                continue
            key = (item.get("tmdb_type") or "movie", str(item.get("tmdb_id") or ""))
            if key in _PREFETCH_IN_FLIGHT:
                continue
            _PREFETCH_IN_FLIGHT.add(key)
            missing.append(key)
            if len(missing) >= limit:
                break
    if not missing:
        return

    def worker():
        for tmdb_type, tmdb_id in missing:
            try:
                if not tmdb.meta_cache_get(tmdb_type, tmdb_id):
                    tmdb.meta_summary_cached(tmdb_type, tmdb_id)
            except Exception:
                pass
            finally:
                with _PREFETCH_IN_FLIGHT_LOCK:
                    _PREFETCH_IN_FLIGHT.discard((tmdb_type, tmdb_id))

    threading.Thread(target=worker, daemon=True).start()


_WARMED = set()
_PREFETCH_IN_FLIGHT = set()
_PREFETCH_IN_FLIGHT_LOCK = threading.Lock()


def _filter_provider_available_results(results):
    try:
        fn = _CTX.get("_filter_provider_available_items")
        if fn:
            return fn(results)
    except Exception as exc:
        c("_log")("Provider-only TMDB filter failed: {0}".format(exc))
    return results


def _provider_only_route_enabled(filter_provider=True):
    if not filter_provider:
        return False
    try:
        return c("addon").getSetting("tmdb_provider_only_available").lower() == "true"
    except Exception:
        return False


def _provider_only_enabled():
    try:
        return c("addon").getSetting("tmdb_provider_only_available").lower() == "true"
    except Exception:
        return False


def _mark_unavailable_enabled(params=None):
    try:
        return c("addon").getSetting("tmdb_mark_unavailable").lower() == "true"
    except Exception:
        return True


def _provider_item_available(item, strict_title_year=False):
    try:
        if item.get("provider_unavailable"):
            return False
        fn = _CTX.get("_provider_item_available_for_tmdb")
        if fn:
            return bool(fn(item, strict_title_year=strict_title_year))
    except Exception as exc:
        c("_log")("Provider availability marker check failed: {0}".format(exc))
    return True


def _provider_result_key(item):
    tmdb_type = item.get("tmdb_type") or item.get("media_type") or ""
    tmdb_id = str(item.get("tmdb_id") or item.get("id") or "").strip()
    if tmdb_id:
        return "{0}:{1}".format(tmdb_type, tmdb_id)
    title = item.get("showtitle") or item.get("tvshowtitle") or item.get("title") or item.get("name") or ""
    year = item.get("year") or item.get("premiered") or ""
    return "{0}:{1}:{2}".format(tmdb_type, title, year)


def _provider_filter_cache_mtime():
    try:
        profile = xbmcvfs.translatePath(c("addon").getAddonInfo("profile"))
        path = os.path.join(profile, "tmdb_provider_availability.json")
        return int(os.path.getmtime(path)) if os.path.exists(path) else 0
    except Exception:
        return 0


def _provider_exact_page_cache_key(fetch_key):
    try:
        active_profile = str(getattr(c("pm"), "active", "1"))
    except Exception:
        active_profile = "1"

    return cache.make_key(
        "provider_exact_page_v1",
        active_profile,
        tmdb.language(),
        tmdb.region(),
        _provider_filter_cache_mtime(),
        fetch_key,
    )


def _fetch_provider_exact_page(fetch_page, user_page, fetch_key, page_size=PROVIDER_PAGE_SIZE, filter_watched=False):
    user_page = max(1, int(user_page or 1))
    page_size = max(1, int(page_size or 20))

    target_start = (user_page - 1) * page_size
    target_end = target_start + page_size

    cache_key = _provider_exact_page_cache_key(fetch_key)
    cached = cache.get("provider_exact_pages", cache_key) or {}

    matched = cached.get("matched") or []
    seen_ids = set(cached.get("seen_ids") or [])
    source_page = int(cached.get("source_page") or 1)
    source_total = int(cached.get("source_total") or 1)
    complete = bool(cached.get("complete"))

    wm = None
    we = None
    if filter_watched:
        wm, we = _watchers()

    def _visible_count():
        if not wm and not we:
            return len(matched)
        return sum(1 for item in matched if not _is_watched(item, wm, we))

    need_visible = target_end + 1

    while not complete and _visible_count() < need_visible and source_page <= min(source_total, PROVIDER_SCAN_MAX_PAGES):
        try:
            data = fetch_page(source_page) or {}
        except Exception:
            data = {}

        try:
            source_total = max(source_total, int(data.get("total_pages") or 1))
        except Exception:
            source_total = max(source_total, 1)

        raw_items = data.get("results", []) or []
        filtered_items = _filter_provider_available_results(raw_items)

        for item in filtered_items:
            key = _provider_result_key(item)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            matched.append(item)

        source_page += 1

        if source_page > source_total:
            complete = True
            break

    if source_page > min(source_total, PROVIDER_SCAN_MAX_PAGES):
        complete = source_page > source_total

    cache.set(
        "provider_exact_pages",
        cache_key,
        {
            "matched": matched,
            "seen_ids": list(seen_ids),
            "source_page": source_page,
            "source_total": source_total,
            "complete": complete,
        },
        PROVIDER_FILTER_CACHE_TTL,
    )

    if wm or we:
        matched = [item for item in matched if not _is_watched(item, wm, we)]

    page_results = matched[target_start:target_end]
    has_more = len(matched) > target_end or not complete

    return {
        "page": user_page,
        "total_pages": user_page + 1 if has_more else user_page,
        "results": page_results[:page_size],
        "raw": {},
        "exact_page_size": page_size,
    }


def _fetch_exact_unfiltered_page(fetch_page, user_page, fetch_key, page_size=PROVIDER_PAGE_SIZE, filter_watched=False):
    user_page = max(1, int(user_page or 1))
    page_size = max(1, int(page_size or PROVIDER_PAGE_SIZE))

    target_start = (user_page - 1) * page_size
    target_end = target_start + page_size

    cache_key = _provider_exact_page_cache_key(fetch_key)
    cached = cache.get("tmdb_exact_pages", cache_key) or {}

    matched = cached.get("matched") or []
    seen_ids = set(cached.get("seen_ids") or [])
    source_page = int(cached.get("source_page") or 1)
    source_total = int(cached.get("source_total") or 1)
    complete = bool(cached.get("complete"))

    wm = None
    we = None
    if filter_watched:
        wm, we = _watchers()

    def _visible_count():
        if not wm and not we:
            return len(matched)
        return sum(1 for item in matched if not _is_watched(item, wm, we))

    need_visible = target_end + 1

    while not complete and _visible_count() < need_visible and source_page <= min(source_total, PROVIDER_SCAN_MAX_PAGES):
        try:
            data = fetch_page(source_page) or {}
        except Exception:
            data = {}

        try:
            source_total = max(source_total, int(data.get("total_pages") or 1))
        except Exception:
            source_total = max(source_total, 1)

        raw_items = data.get("results", []) or []
        for item in raw_items:
            key = _provider_result_key(item)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            matched.append(item)

        source_page += 1
        if source_page > source_total:
            complete = True
            break

    if source_page > min(source_total, PROVIDER_SCAN_MAX_PAGES):
        complete = source_page > source_total

    cache.set(
        "tmdb_exact_pages",
        cache_key,
        {
            "matched": matched,
            "seen_ids": list(seen_ids),
            "source_page": source_page,
            "source_total": source_total,
            "complete": complete,
        },
        PROVIDER_FILTER_CACHE_TTL,
    )

    if wm or we:
        matched = [item for item in matched if not _is_watched(item, wm, we)]

    page_results = matched[target_start:target_end]
    has_more = len(matched) > target_end or not complete

    return {
        "page": user_page,
        "total_pages": user_page + 1 if has_more else user_page,
        "results": page_results[:page_size],
        "raw": {},
        "exact_page_size": page_size,
    }


def _fetch_merged_page(fetch_page, user_page, merge_pages=MERGE_PAGES_DEFAULT, filter_provider=True, fetch_key=None, filter_watched=False):
    user_page = max(1, int(user_page or 1))
    provider_mode = filter_provider and _provider_only_enabled()
    watched_mode = filter_watched and _hide_watched_enabled()

    if provider_mode:
        if fetch_key is not None:
            return _fetch_provider_exact_page(
                fetch_page, user_page, fetch_key,
                filter_watched=watched_mode,
            )
        try:
            c("_log")("Provider exact pagination missing fetch_key; using one raw page fallback")
        except Exception:
            pass
        actual_merge = 1
    elif watched_mode and fetch_key is not None:
        return _fetch_exact_unfiltered_page(
            fetch_page, user_page, fetch_key,
            page_size=PROVIDER_PAGE_SIZE,
            filter_watched=True,
        )
    else:
        actual_merge = merge_pages

    source_start = 1 + MERGE_PAGES_PROVIDER * user_page * (user_page - 1) // 2 if provider_mode else (user_page - 1) * actual_merge + 1
    merged = []
    seen_ids = set()
    source_total = 1
    raw = {}

    for offset in range(actual_merge):
        src_page = source_start + offset
        try:
            data = fetch_page(src_page) or {}
        except Exception:
            data = {}

        try:
            source_total = max(source_total, int(data.get("total_pages") or 1))
        except Exception:
            source_total = max(source_total, 1)

        raw = data.get("raw") or raw

        for item in data.get("results", []) or []:
            key = _provider_result_key(item)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            merged.append(item)

    if provider_mode:
        merged = _filter_provider_available_results(merged)

    display_total = max(1, -(-source_total // actual_merge))

    return {
        "page": user_page,
        "total_pages": display_total,
        "results": merged,
        "raw": raw,
    }


def _render_media_page(page_data, params, tmdb_type=None, content=None, filter_provider=True):
    wm, we = _watchers()

    results = page_data.get("results", []) or []
    results = _hydrate_from_tmdb_meta_cache(results)
    _queue_missing_tmdb_art_prefetch(results, limit=20)
    results = tmdb.apply_english_titles(results)

    if filter_provider:
        results = _filter_provider_available_results(results)

    if _hide_watched_enabled() and (wm or we):
        results = [item for item in results if not _is_watched(item, wm, we)]

    # Only exact-page routes are allowed to be hard-limited here.
    # Do NOT globally slice seasons, episodes, collections, or special routes.
    exact_page_size = int(page_data.get("exact_page_size") or 0)
    if exact_page_size > 0:
        results = results[:exact_page_size]

    mark_unavailable = _mark_unavailable_enabled(params)

    items = [
        _media_item(item, wm, we, mark_unavailable=mark_unavailable)
        for item in results
    ]

    page = int(page_data.get("page") or _int_param(params, "page"))
    total_pages = int(page_data.get("total_pages") or 1)

    next_item = _next_page_item(params, page, total_pages)
    if next_item:
        items.append(next_item)

    if not items:
        li = c("_new_listitem")(_t(31229))
        items.append(("", li, False))

    if content:
        xbmcplugin.setContent(c("addon_handle"), content)
    elif tmdb_type:
        c("_set_tmdb_content")(tmdb_type)

    xbmcplugin.addDirectoryItems(c("addon_handle"), items)
    xbmcplugin.endOfDirectory(c("addon_handle"))

    timing = _CTX.get("_log_route_timing")
    if timing:
        timing()


def movies_menu():
    if not _guard():
        return
    _add_items(_menu_items(_MOVIES_MENU_MODEL))


def tvshows_menu():
    if not _guard():
        return
    _add_items(_menu_items(_TV_MENU_MODEL))




# ---------------------------------------------------------------------------
# Animation / Anime / Kids - clean Discover-first implementation
# ---------------------------------------------------------------------------

ANIMATION_GENRE_ID = "16"
FAMILY_GENRE_ID = "10751"
KIDS_TV_GENRE_ID = "10762"
ANIMATION_PAGE_SIZE = PROVIDER_PAGE_SIZE
ANIMATION_EXCLUDED_ASIAN_LANGS = {"ja", "zh", "ko"}

_ANIMATION_MOVIE_COLLECTION_QUERIES = (
    "Toy Story",
    "Shrek",
    "Ice Age",
    "Despicable Me",
    "Minions",
    "How to Train Your Dragon",
    "Kung Fu Panda",
    "Madagascar",
    "Cars",
    "Monsters, Inc.",
    "Finding Nemo",
    "The Incredibles",
    "The Lego Movie",
    "Hotel Transylvania",
    "Spider-Man: Spider-Verse",
    "SpongeBob SquarePants",
    "Scooby-Doo",
    "The Secret Life of Pets",
    "Sing",
    "Rio",
    "Cloudy with a Chance of Meatballs",
    "The Croods",
    "The Boss Baby",
    "Happy Feet",
    "Open Season",
    "Trolls",
    "Wreck-It Ralph",
    "Frozen",
    "Moana",
    "Zootopia",
    "Lilo & Stitch",
    "The Lion King",
    "Aladdin",
    "Beauty and the Beast",
    "The Little Mermaid",
    "Mulan",
    "Peter Pan",
    "Cinderella",
    "Bambi",
    "Dumbo",
    "Dragon Ball",
    "Naruto",
    "One Piece",
    "Pokémon",
    "Demon Slayer",
    "My Hero Academia",
    "Sailor Moon",
)

_ANIMATION_STUDIO_QUERIES = (
    "Pixar",
    "Walt Disney Animation Studios",
    "DreamWorks Animation",
    "Illumination",
    "Sony Pictures Animation",
    "Blue Sky Studios",
    "Warner Bros. Animation",
    "Laika",
    "Aardman",
    "Cartoon Network Studios",
    "Nickelodeon Animation Studio",
    "Studio Ghibli",
    "Toei Animation",
    "Madhouse",
    "MAPPA",
    "Kyoto Animation",
    "Production I.G",
    "Bones",
)

_ANIMATION_NETWORK_QUERIES = (
    "Cartoon Network",
    "Nickelodeon",
    "Disney Channel",
    "Disney Junior",
    "Adult Swim",
    "Crunchyroll",
    "Netflix",
    "Hulu",
    "Max",
    "Apple TV+",
)

def _animation_today():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def _animation_days_from_now(days):
    return (datetime.datetime.now() + datetime.timedelta(days=int(days))).strftime("%Y-%m-%d")

def _animation_raw(item):
    return item.get("raw") or {}

def _animation_original_language(item):
    return str(_animation_raw(item).get("original_language") or "").lower().strip()

def _animation_genre_ids(item):
    raw = _animation_raw(item)
    ids = raw.get("genre_ids") or raw.get("genres") or []
    out = set()
    for value in ids:
        if isinstance(value, dict):
            value = value.get("id")
        value = str(value or "").strip()
        if value:
            out.add(value)
    return out

def _animation_item_is_animation(item):
    ids = _animation_genre_ids(item)
    if not ids:
        return False
    return ANIMATION_GENRE_ID in ids

def _animation_group_accepts_item(item, group, tmdb_type):
    group = str(group or "animated").lower()
    lang = _animation_original_language(item)
    if group == "anime":
        return lang == "ja"
    if group == "donghua":
        return lang == "zh"
    if group == "korean":
        return lang == "ko"
    if group == "animated":
        return lang not in ANIMATION_EXCLUDED_ASIAN_LANGS
    if group == "kids":
        return True
    if group == "family_tv":
        return True
    return True

def _animation_search_accepts_item(item, group, tmdb_type):
    if not _animation_item_is_animation(item):
        return False
    group = str(group or "animated").lower()
    ids = _animation_genre_ids(item)
    if group == "kids":
        if tmdb_type == "movie":
            return FAMILY_GENRE_ID in ids
        return KIDS_TV_GENRE_ID in ids or FAMILY_GENRE_ID in ids
    if group == "family_tv":
        return FAMILY_GENRE_ID in ids
    return _animation_group_accepts_item(item, group, tmdb_type)

def _animation_list_sort_params(list_name, tmdb_type):
    list_name = str(list_name or "popular").lower()
    today = _animation_today()
    if list_name == "top_rated":
        return {
            "sort_by": "vote_average.desc",
            "vote_count.gte": "100",
        }
    if list_name == "kids_top_rated":
        return {
            "sort_by": "vote_average.desc",
            "vote_count.gte": "50",
        }
    if list_name == "new":
        if tmdb_type == "tv":
            return {
                "sort_by": "first_air_date.desc",
                "first_air_date.lte": today,
            }
        return {
            "sort_by": "primary_release_date.desc",
            "primary_release_date.lte": today,
        }
    if list_name == "airing":
        return {
            "sort_by": "popularity.desc",
            "air_date.gte": _animation_days_from_now(-7),
            "air_date.lte": _animation_days_from_now(7),
        }
    if list_name == "classic":
        if tmdb_type == "tv":
            return {
                "sort_by": "popularity.desc",
                "first_air_date.lte": "2000-12-31",
            }
        return {
            "sort_by": "popularity.desc",
            "primary_release_date.lte": "2000-12-31",
        }
    if list_name == "most_voted":
        return {
            "sort_by": "vote_count.desc",
            "vote_count.gte": "100",
        }
    if list_name == "revenue" and tmdb_type == "movie":
        return {
            "sort_by": "revenue.desc",
        }
    return {
        "sort_by": "popularity.desc",
    }

def _animation_discover_params(group, tmdb_type, list_name="popular", company_id="", network_id=""):
    group = str(group or "animated").lower()
    tmdb_type = "tv" if tmdb_type == "tv" else "movie"
    params = _animation_list_sort_params(list_name, tmdb_type)
    genres = [ANIMATION_GENRE_ID]
    if group == "kids" and tmdb_type == "movie":
        genres.append(FAMILY_GENRE_ID)
    elif group == "kids" and tmdb_type == "tv":
        genres.append(KIDS_TV_GENRE_ID)
    elif group == "family_tv" and tmdb_type == "tv":
        genres.append(FAMILY_GENRE_ID)
    params["with_genres"] = ",".join(genres)
    if group == "anime":
        params["with_original_language"] = "ja"
    elif group == "donghua":
        params["with_original_language"] = "zh"
    elif group == "korean":
        params["with_original_language"] = "ko"
    if company_id:
        params["with_companies"] = str(company_id)
    if network_id and tmdb_type == "tv":
        params["with_networks"] = str(network_id)
    return params

def _animation_exact_cache_key(fetch_key, provider_mode=False):
    try:
        active_profile = str(getattr(c("pm"), "active", "1"))
    except Exception:
        active_profile = "1"
    return cache.make_key(
        "animation_exact_page_v2",
        active_profile,
        tmdb.language(),
        tmdb.region(),
        _provider_filter_cache_mtime(),
        "provider_on" if provider_mode else "provider_off",
        fetch_key,
    )

def _fetch_animation_exact_page(fetch_page, user_page, fetch_key, post_filter=None, filter_provider=True, page_size=ANIMATION_PAGE_SIZE, max_scan_pages=None):
    user_page = max(1, int(user_page or 1))
    page_size = max(1, int(page_size or ANIMATION_PAGE_SIZE))
    scan_cap = PROVIDER_SCAN_MAX_PAGES
    if max_scan_pages is not None:
        try:
            scan_cap = max(1, min(PROVIDER_SCAN_MAX_PAGES, int(max_scan_pages)))
        except Exception:
            scan_cap = PROVIDER_SCAN_MAX_PAGES

    target_start = (user_page - 1) * page_size
    target_end = target_start + page_size
    need_count = target_end + 1

    cache_key = _animation_exact_cache_key(fetch_key)
    cached = cache.get("animation_exact_pages", cache_key) or {}

    matched = cached.get("matched") or []
    seen_ids = set(cached.get("seen_ids") or [])
    source_page = int(cached.get("source_page") or 1)
    source_total = int(cached.get("source_total") or 1)
    complete = bool(cached.get("complete"))

    scan_limit = min(max(1, source_total), scan_cap)
    found_before_scan = len(matched)

    while not complete and len(matched) < need_count and source_page <= scan_limit:
        try:
            if xbmc.Monitor().abortRequested():
                complete = True
                break
        except Exception:
            pass
        try:
            data = fetch_page(source_page) or {}
        except Exception:
            data = {}

        try:
            source_total = max(source_total, int(data.get("total_pages") or 1))
        except Exception:
            source_total = max(source_total, 1)

        scan_limit = min(max(1, source_total), scan_cap)
        raw_items = data.get("results", []) or []

        if post_filter:
            try:
                raw_items = [item for item in raw_items if post_filter(item)]
            except Exception as exc:
                c("_log")("Animation post-filter failed: {0}".format(exc))
                raw_items = []

        if _provider_only_route_enabled(filter_provider):
            raw_items = _filter_provider_available_results(raw_items)

        for item in raw_items:
            key = _provider_result_key(item)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            matched.append(item)

        source_page += 1

        if source_page > source_total:
            complete = True
            break

        if source_page > scan_cap:
            complete = True
            break

    if source_page > source_total:
        complete = True

    if source_page > scan_cap:
        complete = True

    page_results = matched[target_start:target_end]

    has_more = len(matched) > target_end
    if not has_more and not complete:
        has_more = source_page <= min(max(1, source_total), scan_cap)

    if user_page > 1 and not page_results and len(matched) == found_before_scan:
        complete = True
        has_more = False

    cache.set(
        "animation_exact_pages",
        cache_key,
        {
            "matched": matched,
            "seen_ids": list(seen_ids),
            "source_page": source_page,
            "source_total": source_total,
            "complete": complete,
        },
        PROVIDER_FILTER_CACHE_TTL,
    )

    return {
        "page": user_page,
        "total_pages": user_page + 1 if has_more else user_page,
        "results": page_results[:page_size],
        "raw": {},
        "exact_page_size": page_size,
    }

def _animation_static_exact_page(results, params, filter_provider=False, page_size=ANIMATION_PAGE_SIZE):
    page = max(1, _int_param(params, "page") or 1)
    page_size = max(1, int(page_size or ANIMATION_PAGE_SIZE))

    items = list(results or [])

    if filter_provider and _provider_only_enabled():
        items = _filter_provider_available_results(items)

    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)

    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    end = start + page_size

    return {
        "page": page,
        "total_pages": total_pages,
        "results": items[start:end],
        "raw": {},
        "exact_page_size": page_size,
    }

def _animation_content(tmdb_type):
    return "tvshows" if tmdb_type == "tv" else "movies"

def _animation_list_folder(label, group, tmdb_type, list_name="popular", icon="animation", **extra):
    query = {
        "mode": "xstream_tmdb_animation_list",
        "group": group,
        "tmdb_type": tmdb_type,
        "list_name": list_name,
        "page": "1",
    }
    for key, value in extra.items():
        if value not in ("", None):
            query[key] = str(value)
    return _folder_item(label, query, icon)

def animation_menu():
    if not _guard():
        return
    items = [
        _folder_item("Anime", {"mode": "xstream_tmdb_animation_anime_menu"}, "animation"),
        _folder_item("Animated Movies", {"mode": "xstream_tmdb_animation_movies_menu"}, "movies"),
        _folder_item("Animated TV Shows", {"mode": "xstream_tmdb_animation_tv_menu"}, "tv_shows"),
        _folder_item("Kids & Family", {"mode": "xstream_tmdb_animation_kids_menu"}, "kids"),
        _folder_item("Studios & Networks", {"mode": "xstream_tmdb_animation_studios_menu"}, "providers"),
        _folder_item("Collections & Universes", {"mode": "xstream_tmdb_animation_collections_menu"}, "collections"),
        _folder_item("Search Animation", {"mode": "xstream_tmdb_animation_search_root"}, "search"),
        _folder_item("Random Animation", {"mode": "xstream_tmdb_animation_random_menu"}, "randomised"),
    ]
    _add_items(items)

def animation_anime_menu():
    if not _guard():
        return
    items = [
        _animation_list_folder("Popular Anime Movies", "anime", "movie", "popular", "popular"),
        _animation_list_folder("Top Rated Anime Movies", "anime", "movie", "top_rated", "top_rated"),
        _animation_list_folder("New Anime Movies", "anime", "movie", "new", "calendar"),
        _animation_list_folder("Popular Anime TV Shows", "anime", "tv", "popular", "popular"),
        _animation_list_folder("Top Rated Anime TV Shows", "anime", "tv", "top_rated", "top_rated"),
        _animation_list_folder("Airing Anime TV Shows", "anime", "tv", "airing", "airing_today"),
        _animation_list_folder("Donghua Movies", "donghua", "movie", "popular", "animation"),
        _animation_list_folder("Donghua TV Shows", "donghua", "tv", "popular", "animation"),
        _animation_list_folder("Korean Animation Movies", "korean", "movie", "popular", "animation"),
        _animation_list_folder("Korean Animation TV Shows", "korean", "tv", "popular", "animation"),
        _folder_item("Search Anime Movies", {"mode": "xstream_tmdb_animation_search", "group": "anime", "tmdb_type": "movie", "prompt": "true"}, "search"),
        _folder_item("Search Anime TV Shows", {"mode": "xstream_tmdb_animation_search", "group": "anime", "tmdb_type": "tv", "prompt": "true"}, "search"),
    ]
    _add_items(items)

def animation_movies_menu():
    if not _guard():
        return
    items = [
        _animation_list_folder("Popular Animated Movies", "animated", "movie", "popular", "popular"),
        _animation_list_folder("Top Rated Animated Movies", "animated", "movie", "top_rated", "top_rated"),
        _animation_list_folder("New Animated Movies", "animated", "movie", "new", "calendar"),
        _animation_list_folder("Classic Animated Movies", "animated", "movie", "classic", "years"),
        _animation_list_folder("Most Voted Animated Movies", "animated", "movie", "most_voted", "most_voted"),
        _animation_list_folder("Highest Revenue Animated Movies", "animated", "movie", "revenue", "highest_revenue"),
        _folder_item("Animated Movie Collections", {"mode": "xstream_tmdb_animation_movie_collections", "page": "1"}, "collections"),
    ]
    _add_items(items)

def animation_tv_menu():
    if not _guard():
        return
    items = [
        _animation_list_folder("Popular Animated TV Shows", "animated", "tv", "popular", "popular"),
        _animation_list_folder("Top Rated Animated TV Shows", "animated", "tv", "top_rated", "top_rated"),
        _animation_list_folder("New Animated TV Shows", "animated", "tv", "new", "calendar"),
        _animation_list_folder("Airing Animated TV Shows", "animated", "tv", "airing", "airing_today"),
        _animation_list_folder("Classic Animated TV Shows", "animated", "tv", "classic", "years"),
    ]
    _add_items(items)

def animation_kids_menu():
    if not _guard():
        return
    items = [
        _animation_list_folder("Kids Animated Movies", "kids", "movie", "popular", "kids"),
        _animation_list_folder("Top Rated Kids Animated Movies", "kids", "movie", "kids_top_rated", "top_rated"),
        _animation_list_folder("New Kids Animated Movies", "kids", "movie", "new", "calendar"),
        _animation_list_folder("Kids Animated TV Shows", "kids", "tv", "popular", "kids"),
        _animation_list_folder("Top Rated Kids Animated TV Shows", "kids", "tv", "kids_top_rated", "top_rated"),
        _animation_list_folder("New Kids Animated TV Shows", "kids", "tv", "new", "calendar"),
        _animation_list_folder("Family Animated TV Shows", "family_tv", "tv", "popular", "kids"),
    ]
    _add_items(items)

def animation_studios_menu(params=None):
    if not _guard():
        return
    params = params or {}
    page = max(1, _int_param(params, "page") or 1)
    per_page = ANIMATION_PAGE_SIZE
    entries = [("studio", name) for name in _ANIMATION_STUDIO_QUERIES]
    entries += [("network", name) for name in _ANIMATION_NETWORK_QUERIES]
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page
    items = []
    for kind, name in entries[start:end]:
        if kind == "studio":
            items.append(_folder_item(name, {"mode": "xstream_tmdb_animation_company", "company": name, "tmdb_type": "movie", "page": "1"}, "providers"))
        else:
            items.append(_folder_item(name, {"mode": "xstream_tmdb_animation_network", "network": name, "page": "1"}, "providers"))
    next_item = _next_page_item({"mode": "xstream_tmdb_animation_studios_menu", "page": str(page)}, page, total_pages)
    if next_item:
        items.append(next_item)
    _add_items(items)

def animation_collections_menu():
    if not _guard():
        return
    items = [
        _folder_item("Animated Movie Collections", {"mode": "xstream_tmdb_animation_movie_collections", "page": "1"}, "collections"),
        _folder_item("Search Animation Collections", {"mode": "xstream_tmdb_animation_collection_search", "prompt": "true"}, "search"),
    ]
    _add_items(items)

def animation_search_root():
    if not _guard():
        return
    items = [
        _folder_item("Search Anime Movies", {"mode": "xstream_tmdb_animation_search", "group": "anime", "tmdb_type": "movie", "prompt": "true"}, "search"),
        _folder_item("Search Anime TV Shows", {"mode": "xstream_tmdb_animation_search", "group": "anime", "tmdb_type": "tv", "prompt": "true"}, "search"),
        _folder_item("Search Animated Movies", {"mode": "xstream_tmdb_animation_search", "group": "animated", "tmdb_type": "movie", "prompt": "true"}, "search"),
        _folder_item("Search Animated TV Shows", {"mode": "xstream_tmdb_animation_search", "group": "animated", "tmdb_type": "tv", "prompt": "true"}, "search"),
        _folder_item("Search Kids Movies", {"mode": "xstream_tmdb_animation_search", "group": "kids", "tmdb_type": "movie", "prompt": "true"}, "search"),
        _folder_item("Search Kids TV Shows", {"mode": "xstream_tmdb_animation_search", "group": "kids", "tmdb_type": "tv", "prompt": "true"}, "search"),
    ]
    _add_items(items)

def animation_random_menu():
    if not _guard():
        return
    items = [
        _folder_item("Random Anime Movie", {"mode": "xstream_tmdb_animation_random", "group": "anime", "tmdb_type": "movie"}, "randomised"),
        _folder_item("Random Anime TV Show", {"mode": "xstream_tmdb_animation_random", "group": "anime", "tmdb_type": "tv"}, "randomised"),
        _folder_item("Random Animated Movie", {"mode": "xstream_tmdb_animation_random", "group": "animated", "tmdb_type": "movie"}, "randomised"),
        _folder_item("Random Animated TV Show", {"mode": "xstream_tmdb_animation_random", "group": "animated", "tmdb_type": "tv"}, "randomised"),
        _folder_item("Random Kids Movie", {"mode": "xstream_tmdb_animation_random", "group": "kids", "tmdb_type": "movie"}, "randomised"),
        _folder_item("Random Kids TV Show", {"mode": "xstream_tmdb_animation_random", "group": "kids", "tmdb_type": "tv"}, "randomised"),
    ]
    _add_items(items)

def animation_list_route(params):
    if not _guard():
        return
    try:
        group = _param(params, "group", "animated")
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        list_name = _param(params, "list_name", "popular")
        page = _int_param(params, "page")
        company_id = _param(params, "company_id", "")
        network_id = _param(params, "network_id", "")
        discover_params = _animation_discover_params(
            group, tmdb_type, list_name, company_id=company_id, network_id=network_id,
        )
        route_params = _query(params)
        route_params.update({
            "mode": "xstream_tmdb_animation_list",
            "group": group,
            "tmdb_type": tmdb_type,
            "list_name": list_name,
        })
        if company_id:
            route_params["company_id"] = company_id
        if network_id:
            route_params["network_id"] = network_id
        def _fetch_page(src_page):
            return tmdb.discover(tmdb_type, discover_params, page=src_page)
        def _post_filter(item):
            return _animation_group_accepts_item(item, group, tmdb_type)
        data = _fetch_animation_exact_page(
            _fetch_page, page,
            fetch_key=("animation_list", group, tmdb_type, list_name, sorted(discover_params.items())),
            post_filter=_post_filter,
            filter_provider=True,
        )
        _render_media_page(data, route_params, tmdb_type, _animation_content(tmdb_type), filter_provider=False)
    except Exception as exc:
        _handle_error(exc)

def _first_named_result(results, wanted):
    wanted_norm = "".join(ch.lower() for ch in str(wanted or "") if ch.isalnum())
    fallback = None
    for item in results or []:
        name = item.get("name") or item.get("title") or ""
        name_norm = "".join(ch.lower() for ch in name if ch.isalnum())
        if not fallback:
            fallback = item
        if wanted_norm and name_norm == wanted_norm:
            return item
    return fallback

def animation_company_route(params):
    if not _guard():
        return
    try:
        company_name = _param(params, "company", "")
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        data = tmdb.search_companies(company_name, page=1)
        selected = _first_named_result(data.get("results", []) or [], company_name)
        company_id = str((selected or {}).get("id") or "")
        if not company_id:
            _end_empty("No studios found")
            return
        route_params = {
            "mode": "xstream_tmdb_animation_list",
            "group": "animated",
            "tmdb_type": tmdb_type,
            "list_name": "popular",
            "company_id": company_id,
            "page": _param(params, "page", "1"),
        }
        animation_list_route(route_params)
    except Exception as exc:
        _handle_error(exc)

def animation_network_route(params):
    if not _guard():
        return
    try:
        network_name = _param(params, "network", "")
        data = tmdb.search_networks(network_name, page=1)
        selected = _first_named_result(data.get("results", []) or [], network_name)
        network_id = str((selected or {}).get("id") or "")
        if not network_id:
            _end_empty("No animation network found")
            return
        route_params = {
            "mode": "xstream_tmdb_animation_list",
            "group": "animated",
            "tmdb_type": "tv",
            "list_name": "popular",
            "network_id": network_id,
            "page": _param(params, "page", "1"),
        }
        animation_list_route(route_params)
    except Exception as exc:
        _handle_error(exc)

def animation_movie_collections_menu(params):
    if not _guard():
        return
    page = max(1, _int_param(params, "page") or 1)
    per_page = ANIMATION_PAGE_SIZE
    entries = list(_ANIMATION_MOVIE_COLLECTION_QUERIES)
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page
    items = [
        _folder_item(
            name,
            {
                "mode": "xstream_tmdb_animation_collection",
                "query": name,
                "page": "1",
            },
            "collections",
        )
        for name in entries[start:end]
    ]
    next_item = _next_page_item({"mode": "xstream_tmdb_animation_movie_collections", "page": str(page)}, page, total_pages)
    if next_item:
        items.append(next_item)
    _add_items(items, "sets")

def animation_collection_search_route(params):
    if not _guard():
        return
    try:
        query, should_return = _handle_search_prompt(params, "collection", "Search Animation Collections")
        if should_return:
            return
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        route_params = {
            "mode": "xstream_tmdb_animation_collection",
            "query": query,
            "page": _param(params, "page", "1"),
        }
        animation_collection_route(route_params)
    except Exception as exc:
        _handle_error(exc)

def animation_collection_route(params):
    if not _guard():
        return
    try:
        query = _param(params, "query", "")
        page = _int_param(params, "page")
        if not query:
            _end_empty("No collection found")
            return
        data = tmdb.search_collections(query, page=1)
        selected = _first_named_result(data.get("results", []) or [], query)
        collection_id = str(
            (selected or {}).get("collection_id")
            or (selected or {}).get("tmdb_id")
            or (selected or {}).get("id")
            or ""
        )
        if not collection_id:
            _end_empty("No collection found")
            return
        collection_data = tmdb.collection(collection_id)
        page_data = _animation_static_exact_page(collection_data.get("results", []) or [], {"page": str(page)}, filter_provider=False, page_size=ANIMATION_PAGE_SIZE)
        route_params = {
            "mode": "xstream_tmdb_animation_collection",
            "query": query,
            "page": str(page),
        }
        _render_media_page(page_data, route_params, "movie", "movies", filter_provider=False)
    except Exception as exc:
        _handle_error(exc)

def animation_search_route(params):
    if not _guard():
        return
    try:
        group = _param(params, "group", "animated")
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        history_key = "animation_{0}_{1}".format(group, tmdb_type)
        query, should_return = _handle_search_prompt(params, history_key, "Search Animation")
        if should_return:
            return
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        page = _int_param(params, "page")
        route_params = _query(params)
        route_params.update({
            "mode": "xstream_tmdb_animation_search",
            "group": group,
            "tmdb_type": tmdb_type,
            "query": query,
            "prompt": "false",
        })
        def _fetch_page(src_page):
            return tmdb.search(tmdb_type, query, page=src_page)
        def _post_filter(item):
            return _animation_search_accepts_item(item, group, tmdb_type)
        data = _fetch_animation_exact_page(
            _fetch_page, page,
            fetch_key=("animation_search", group, tmdb_type, query),
            post_filter=_post_filter,
            filter_provider=True,
            max_scan_pages=3,
        )
        _render_media_page(data, route_params, tmdb_type, _animation_content(tmdb_type), filter_provider=False)
    except Exception as exc:
        _handle_error(exc)

def animation_random_route(params):
    if not _guard():
        return
    try:
        group = _param(params, "group", "animated")
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        discover_params = _animation_discover_params(group, tmdb_type, "popular")
        first = tmdb.discover(tmdb_type, discover_params, page=1)
        total_pages = max(1, int(first.get("total_pages") or 1))
        best_data = None
        best_count = 0
        for _attempt in range(8):
            src_page = random.randint(1, min(total_pages, 25))
            data = tmdb.discover(tmdb_type, discover_params, page=src_page)
            results = [
                item for item in (data.get("results", []) or [])
                if _animation_group_accepts_item(item, group, tmdb_type)
            ]
            if _provider_only_enabled():
                results = _filter_provider_available_results(results)
            count = len(results)
            if count > best_count:
                best_count = count
                best_data = {
                    "page": 1,
                    "total_pages": 1,
                    "results": results[:ANIMATION_PAGE_SIZE],
                    "raw": {},
                    "exact_page_size": ANIMATION_PAGE_SIZE,
                }
            if count >= 8:
                break
        if best_data and best_data.get("results"):
            route_params = {
                "mode": "xstream_tmdb_animation_random",
                "group": group,
                "tmdb_type": tmdb_type,
            }
            _render_media_page(best_data, route_params, tmdb_type, _animation_content(tmdb_type), filter_provider=False)
            return
        _end_empty(31229)
    except Exception as exc:
        _handle_error(exc)


def search_menu():
    if not _guard():
        return
    items = [
        _folder_item(c("_t")(31109), {"mode": "xstream_tmdb_search", "tmdb_type": "both", "prompt": "true"}, "search"),
        _folder_item(c("_t")(30990), {"mode": "xstream_tmdb_search", "tmdb_type": "movie", "prompt": "true"}, "search"),
        _folder_item(c("_t")(30991), {"mode": "xstream_tmdb_search", "tmdb_type": "tv", "prompt": "true"}, "search"),

        _folder_item(c("_t")(30992), {"mode": "xstream_tmdb_people", "action": "search", "prompt": "true"}, "search"),
        _folder_item(_label("Search Collection"), {"mode": "xstream_tmdb_collection_search", "prompt": "true"}, "search"),
        _folder_item(_label("Search Company"), {"mode": "xstream_tmdb_company_search", "prompt": "true"}, "search"),
        _folder_item(_label("Search Keyword"), {"mode": "xstream_tmdb_keyword_search", "prompt": "true"}, "search"),
    ]
    _add_items(items)


def discover_menu():
    if not _guard():
        return
    current_year = str(datetime.datetime.now().year)
    year_start = "{0}-01-01".format(current_year)
    today = _today()
    has_saved = bool(_discover_history_load())
    history_label = _t(31403) if has_saved else _gray(_t(31403))
    items = [
        _folder_item(_label("Advanced Discover"), {"mode": "xstream_tmdb_discover_builder", "tmdb_type": "movie"}, "discover"),
        _folder_item(_label("Advanced Discover TV"), {"mode": "xstream_tmdb_discover_builder", "tmdb_type": "tv"}, "discover"),
        _folder_item(history_label, {"mode": "xstream_tmdb_discover_history"}, "discover"),
    ]
    _add_items(items)


_DISCOVER_SORT_OPTIONS = [
    ("Popularity Descending", "popularity.desc", {}),
    ("Popularity Ascending", "popularity.asc", {}),
    ("Rating Descending", "vote_average.desc", {}),
    ("Rating Ascending", "vote_average.asc", {}),
    ("Best Rated (250+ votes)", "vote_average.desc", {"vote_count.gte": "250"}),
    ("Popular Quality (100+ votes)", "popularity.desc", {"vote_count.gte": "100"}),
    ("Vote Count Descending", "vote_count.desc", {}),
    ("Vote Count Ascending", "vote_count.asc", {}),
    ("Release Date Descending", "primary_release_date.desc", {}),
    ("Release Date Ascending", "primary_release_date.asc", {}),
    ("Revenue Descending", "revenue.desc", {}),
    ("Revenue Ascending", "revenue.asc", {}),
]


_DISCOVER_RULES_MOVIE = [
    ("with_cast", "Cast", "person_search"),
    ("with_crew", "Crew", "person_search"),
    ("with_people", "People", "person_search"),
    ("primary_release_year", "Release Year", "year_input"),
    ("primary_release_date.gte", "Release Date From", "date_input"),
    ("primary_release_date.lte", "Release Date To", "date_input"),
    ("release_date.gte", "Theatrical Date From", "date_input"),
    ("release_date.lte", "Theatrical Date To", "date_input"),
    ("with_release_type", "Release Type", "release_type_select"),
    ("region", "Region", "region_select"),
    ("certification", "Certification", "cert_select"),
    ("certification.gte", "Certification Min", "cert_select"),
    ("certification.lte", "Certification Max", "cert_select"),
]

_DISCOVER_RULES_TV = [
    ("with_networks", "Networks", "network_search"),
    ("air_date.gte", "Air Date From", "date_input"),
    ("air_date.lte", "Air Date To", "date_input"),
    ("first_air_date.gte", "First Air Date From", "date_input"),
    ("first_air_date.lte", "First Air Date To", "date_input"),
    ("first_air_date_year", "First Air Year", "year_input"),
]

_DISCOVER_RULES_COMMON = [
    ("with_genres", "Genre", "genre_select"),
    ("without_genres", "Exclude Genre", "genre_select"),
    ("with_companies", "Company", "company_search"),
    ("with_watch_providers", "Watch Provider", "provider_select"),
    ("with_keywords", "Keyword", "keyword_search"),
    ("without_keywords", "Exclude Keyword", "keyword_search"),
    ("with_original_language", "Original Language", "language_select"),
    ("vote_count.gte", "Min Vote Count", "number_input"),
    ("vote_count.lte", "Max Vote Count", "number_input"),
    ("vote_average.gte", "Min Rating", "number_input"),
    ("vote_average.lte", "Max Rating", "number_input"),
    ("with_runtime.gte", "Min Runtime (min)", "number_input"),
    ("with_runtime.lte", "Max Runtime (min)", "number_input"),
]


_RELEASE_TYPE_OPTIONS = [
    ("Premiere", "1"),
    ("Theatrical (limited)", "2"),
    ("Theatrical", "3"),
    ("Digital", "4"),
    ("Physical", "5"),
    ("TV", "6"),
]


def _discover_rules(tmdb_type):
    rules = list(_DISCOVER_RULES_COMMON)
    rules += _DISCOVER_RULES_MOVIE if tmdb_type == "movie" else _DISCOVER_RULES_TV
    return rules


def _discover_rule_label(method):
    for m, label, _ in _discover_rules("movie") + _discover_rules("tv"):
        if m == method:
            return label
    return method


def _discover_active_rules(params):
    out = []
    tmdb_type = _param(params, "tmdb_type", "movie")
    for method, label, rtype in _discover_rules(tmdb_type):
        value = _param(params, method, "")
        if not value:
            continue
        parts = [p.strip() for p in str(value).replace("|", ",").split(",") if p.strip()]
        displays = []
        for part in parts:
            display = part
            if method == "with_genres" or method == "without_genres":
                try:
                    for g in tmdb.genres(tmdb_type):
                        if str(g.get("id") or "") == part:
                            display = g.get("name") or part
                            break
                except Exception:
                    pass
            elif method == "with_watch_providers":
                try:
                    for p in tmdb.watch_providers(tmdb_type):
                        if str(p.get("provider_id") or "") == part:
                            display = p.get("provider_name") or part
                            break
                except Exception:
                    pass
            elif method == "region":
                for code, name in tmdb._COMMON_REGIONS:
                    if code == part:
                        display = name
                        break
            elif method == "with_original_language":
                for code, name in tmdb._COMMON_LANGUAGES:
                    if code == part:
                        display = name
                        break
            elif method == "with_release_type":
                for name, val in _RELEASE_TYPE_OPTIONS:
                    if val == part:
                        display = name
                        break
            displays.append(display)
        out.append((method, label, ", ".join(displays)))
    return out


def discover_builder_menu(params):
    if not _guard():
        return
    tmdb_type = _param(params, "tmdb_type", "movie")
    current_sort = _param(params, "sort_by", "popularity.desc")
    active = _discover_active_rules(params)
    base = _query(params)
    base.pop("field", None)
    filter_count = len(active)
    discover_label = _bold(_t(31404))
    if filter_count:
        filter_text = _t(31386 if filter_count == 1 else 31387, filter_count)
        discover_label = f"{_bold(_t(31404))}  [COLOR gray]({filter_text})[/COLOR]"
    show_label = _t(31405) if filter_count else _gray(_t(31405))
    clear_label = _t(31406) if filter_count else _gray(_t(31406))
    items = [
        _folder_item(discover_label, dict(base, mode="xstream_tmdb_discover_builder_run", tmdb_type=tmdb_type, sort_by=current_sort), "discover"),
        _folder_item(_label("Add Rule"), dict(base, mode="xstream_tmdb_discover_builder_add", tmdb_type=tmdb_type, sort_by=current_sort), "discover"),
        _folder_item(_label("Sort By"), dict(base, mode="xstream_tmdb_discover_builder_set", field="sort_by", tmdb_type=tmdb_type, sort_by=current_sort), "discover"),
    ]
    items += [
        _folder_item(show_label, dict(base, mode="xstream_tmdb_discover_builder_show", tmdb_type=tmdb_type, sort_by=current_sort), "discover"),
        _folder_item(_label("Save Discover"), dict(base, mode="xstream_tmdb_discover_builder_save", tmdb_type=tmdb_type, sort_by=current_sort), "discover"),
        _folder_item(clear_label, {"mode": "xstream_tmdb_discover_builder", "tmdb_type": tmdb_type}, "discover"),
    ]
    _add_items(items)


def discover_builder_add_route(params):
    if not _guard():
        return
    tmdb_type = _param(params, "tmdb_type", "movie")
    rules = _discover_rules(tmdb_type)
    # Add sort_by as a pseudo-rule
    all_rules = [("sort_by", "Sort Order", "sort_select")] + rules
    labels = [label for _, label, _ in all_rules]
    values = [method for method, _, _ in all_rules]
    idx = xbmcgui.Dialog().select(_label("Add Rule"), labels)
    if idx < 0:
        discover_builder_menu(params)
        return
    method = values[idx]
    updated = _query(params)
    if method == "sort_by":
        labels = [label for label, _, _ in _DISCOVER_SORT_OPTIONS]
        vals = [value for _, value, _ in _DISCOVER_SORT_OPTIONS]
        extras = [extra for _, _, extra in _DISCOVER_SORT_OPTIONS]
        sidx = xbmcgui.Dialog().select(_label("Sort Order"), labels)
        if sidx >= 0:
            updated["sort_by"] = vals[sidx]
            for key, val in extras[sidx].items():
                if key == "vote_count.gte":
                    existing = int(updated.get(key) or 0)
                    preset = int(val or 0)
                    updated[key] = str(max(existing, preset))
                else:
                    updated[key] = val
    elif method == "with_genres" or method == "without_genres":
        genres = tmdb.genres(tmdb_type)
        glbls = [g.get("name") or "Unknown" for g in genres]
        gvals = [str(g.get("id") or "") for g in genres]
        gsel = xbmcgui.Dialog().multiselect(_label("Genre"), glbls)
        if gsel:
            updated[method] = ",".join([gvals[i] for i in gsel])
    elif method in ("with_cast", "with_crew", "with_people"):
        query = xbmcgui.Dialog().input(_t(30992))
        if query:
            results = tmdb.search_person(query, page=1).get("results", []) or []
            if results:
                plbls = [r.get("name") or "Unknown" for r in results]
                pvals = [r.get("id") or "" for r in results]
                pidx = xbmcgui.Dialog().select(_label("Person"), plbls)
                if pidx >= 0:
                    updated[method] = pvals[pidx]
    elif method == "with_networks":
        query = xbmcgui.Dialog().input(_label("Search Network"))
        if query:
            results = tmdb.search_networks(query, page=1).get("results", []) or []
            if results:
                nlbls = [r.get("name") or "Unknown" for r in results]
                nvals = [r.get("id") or "" for r in results]
                nidx = xbmcgui.Dialog().select(_label("Network"), nlbls)
                if nidx >= 0:
                    updated[method] = nvals[nidx]
    elif method == "with_companies":
        query = xbmcgui.Dialog().input(_label("Search Company"))
        if query:
            results = tmdb.search_companies(query, page=1).get("results", []) or []
            if results:
                clbls = [r.get("name") or "Unknown" for r in results]
                cvals = [r.get("id") or "" for r in results]
                cidx = xbmcgui.Dialog().select(_label("Company"), clbls)
                if cidx >= 0:
                    updated[method] = cvals[cidx]
    elif method == "with_keywords" or method == "without_keywords":
        query = xbmcgui.Dialog().input(_label("Search Keyword"))
        if query:
            results = tmdb.search_keywords(query, page=1).get("results", []) or []
            if results:
                klbls = [r.get("name") or "Unknown" for r in results]
                kvals = [r.get("id") or "" for r in results]
                ksel = xbmcgui.Dialog().multiselect(_label("Keyword"), klbls)
                if ksel:
                    updated[method] = "|".join([kvals[i] for i in ksel])
    elif method == "with_watch_providers":
        providers = tmdb.watch_providers(tmdb_type)
        prlbls = [p.get("provider_name") or "Unknown" for p in providers]
        prvals = [str(p.get("provider_id") or "") for p in providers]
        prsel = xbmcgui.Dialog().multiselect(_label("Watch Provider"), prlbls)
        if prsel:
            updated[method] = ",".join([prvals[i] for i in prsel])
    elif method == "region":
        rlbls = [name for _, name in tmdb._COMMON_REGIONS]
        rvals = [code for code, _ in tmdb._COMMON_REGIONS]
        rsel = xbmcgui.Dialog().multiselect(_t(31219), rlbls)
        if rsel:
            updated[method] = ",".join([rvals[i] for i in rsel])
    elif method == "with_original_language":
        llbls = [name for _, name in tmdb._COMMON_LANGUAGES]
        lvals = [code for code, _ in tmdb._COMMON_LANGUAGES]
        lsel = xbmcgui.Dialog().multiselect(_label("Language"), llbls)
        if lsel:
            updated[method] = "|".join([lvals[i] for i in lsel])
    elif method == "with_release_type":
        rtlbls = [name for name, _ in _RELEASE_TYPE_OPTIONS]
        rtvals = [val for _, val in _RELEASE_TYPE_OPTIONS]
        rtsel = xbmcgui.Dialog().multiselect(_t(31218), rtlbls)
        if rtsel:
            updated[method] = ",".join([rtvals[i] for i in rtsel])
    elif method in ("certification", "certification.gte", "certification.lte"):
        certs = tmdb.certifications(tmdb_type)
        if not certs:
            xbmcgui.Dialog().notification("Xstream Pro", _label("No certifications available"))
            discover_builder_menu(params)
            return
        countries = sorted(certs.keys())
        cidx = xbmcgui.Dialog().select(_label("Certification Country"), countries)
        if cidx < 0:
            discover_builder_menu(params)
            return
        country = countries[cidx]
        cert_list = sorted([c for c in certs.get(country, []) if c])
        if not cert_list:
            xbmcgui.Dialog().notification("Xstream Pro", _t(31296, country))
            discover_builder_menu(params)
            return
        cert_idx = xbmcgui.Dialog().select(_t(31194), cert_list)
        if cert_idx >= 0:
            updated["certification_country"] = country
            updated[method] = cert_list[cert_idx]
    elif "year" in method or "date_year" in method:
        val = xbmcgui.Dialog().input(_discover_rule_label(method), type=xbmcgui.INPUT_NUMERIC)
        if val:
            updated[method] = val
    elif ".gte" in method or ".lte" in method:
        val = xbmcgui.Dialog().input(_discover_rule_label(method), type=xbmcgui.INPUT_NUMERIC)
        if val:
            updated[method] = val
    else:
        val = xbmcgui.Dialog().input(_discover_rule_label(method))
        if val:
            updated[method] = val
    updated["mode"] = "xstream_tmdb_discover_builder"
    discover_builder_menu(updated)
    return


def discover_builder_set_route(params):
    if not _guard():
        return
    field = _param(params, "field", "")
    tmdb_type = _param(params, "tmdb_type", "movie")
    updated = _query(params)
    if field == "sort_by":
        labels = [label for label, _, _ in _DISCOVER_SORT_OPTIONS]
        values = [value for _, value, _ in _DISCOVER_SORT_OPTIONS]
        extras = [extra for _, _, extra in _DISCOVER_SORT_OPTIONS]
        idx = xbmcgui.Dialog().select(_label("Sort Order"), labels)
        if idx >= 0:
            updated["sort_by"] = values[idx]
            for key, val in extras[idx].items():
                if key == "vote_count.gte":
                    existing = int(updated.get(key) or 0)
                    preset = int(val or 0)
                    updated[key] = str(max(existing, preset))
                else:
                    updated[key] = val
    elif field in updated:
        # Clicking an active rule removes it (toggle off)
        updated.pop(field, None)
    updated["mode"] = "xstream_tmdb_discover_builder"
    discover_builder_menu(updated)
    return


def discover_builder_quick_route(params):
    if not _guard():
        return
    field = _param(params, "field", "")
    value = _param(params, "value", "")
    if not field or not value:
        discover_builder_menu(params)
        return
    updated = _query(params)
    current = updated.get(field, "")
    if current == value:
        # Toggle off if already set to same value
        updated.pop(field, None)
    else:
        updated[field] = value
    updated["mode"] = "xstream_tmdb_discover_builder"
    discover_builder_menu(updated)
    return


def _warn_high_vote_threshold(params):
    try:
        vote_gte = int(_param(params, "vote_count.gte", "") or 0)
    except ValueError:
        vote_gte = 0
    if vote_gte > 5000:
        xbmcgui.Dialog().notification("Xstream Pro", _label("High vote threshold — results may be empty"))


def discover_builder_run_route(params):
    if not _guard():
        return
    try:
        tmdb_type = _param(params, "tmdb_type", "movie")
        discover_params = _discover_params(params, tmdb_type)
        _warn_high_vote_threshold(params)
        page = _int_param(params, "page")

        def _fetch_discover_builder_page(src_page):
            return tmdb.discover(tmdb_type, discover_params, page=src_page)

        data = _fetch_merged_page(
            _fetch_discover_builder_page,
            page,
            fetch_key=("tmdb_discover_builder", tmdb_type, sorted(discover_params.items())),
            filter_watched=True,
        )
        _render_media_page(data, params, tmdb_type, "tvshows" if tmdb_type == "tv" else "movies", filter_provider=False)
    except Exception as exc:
        _handle_error(exc)


def _discover_history_path():
    cache_dir = os.path.join(_addon_profile_dir(), "tmdb_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(cache_dir, "discover_history.json")


def _discover_history_load():
    path = _discover_history_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _discover_history_save(entries):
    path = _discover_history_path()
    cache_dir = os.path.dirname(path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception as exc:
        c("_log")("Discover history directory creation failed: {0}".format(exc))
        return False
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
            f.flush()
            _safe_fsync(f)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        c("_log")("Discover history save failed: {0}".format(exc))
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def _search_history_path(history_type):
    cache_dir = os.path.join(_addon_profile_dir(), "tmdb_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(cache_dir, "search_history_{0}.json".format(history_type))


def _load_search_history(history_type):
    path = _search_history_path(history_type)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_search_history(history_type, history):
    path = _search_history_path(history_type)
    cache_dir = os.path.dirname(path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history[:10], f, ensure_ascii=False)
            f.flush()
            _safe_fsync(f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _update_search_history(history_type, query):
    if not query:
        return
    history = _load_search_history(history_type)
    if query in history:
        history.remove(query)
    history.insert(0, query)
    _save_search_history(history_type, history)


def _handle_search_prompt(params, history_type, input_title):
    query = _param(params, "query", "")
    if _bool_param(params, "new_search"):
        query = xbmcgui.Dialog().input(input_title)
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return None, True
        _update_search_history(history_type, query)
        return query, False
    if _bool_param(params, "prompt") and not query:
        history = _load_search_history(history_type)
        items = []
        new_params = dict(_query(params))
        new_params["new_search"] = "true"
        new_params.pop("prompt", None)
        items.append(_folder_item(_t(31252), new_params, "search"))
        for entry in history:
            entry_params = dict(_query(params))
            entry_params["query"] = entry
            entry_params["prompt"] = "false"
            items.append(_folder_item(entry, entry_params, "search"))
        _add_items(items)
        return None, True
    if query:
        _update_search_history(history_type, query)
    return query, False


def discover_builder_show_route(params):
    if not _guard():
        return
    tmdb_type = _param(params, "tmdb_type", "movie")
    active = _discover_active_rules(params)
    current_sort = _param(params, "sort_by", "popularity.desc")
    lines = []
    lines.append("Type: {0}".format(tmdb_type.upper()))
    if current_sort and current_sort != "popularity.desc":
        lines.append("Sort: {0}".format(current_sort))
    if active:
        lines.append("")
        for method, label, display in active:
            lines.append("{0}: {1}".format(label, display))
    else:
        lines.append("")
        lines.append("No filters applied.")
    xbmcgui.Dialog().textviewer("Current Filters", "\n".join(lines))
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)


def discover_builder_save_route(params):
    if not _guard():
        return
    tmdb_type = _param(params, "tmdb_type", "movie")
    active = _discover_active_rules(params)
    if not active:
        xbmcgui.Dialog().notification("Xstream Pro", _label("No filters to save"))
        discover_builder_menu(params)
        return
    name = xbmcgui.Dialog().input(_label("Save Discover As"))
    if not name:
        discover_builder_menu(params)
        return
    entries = _discover_history_load()
    entry = {
        "name": name,
        "tmdb_type": tmdb_type,
        "params": dict(_query(params)),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    entry["params"].pop("mode", None)
    entries.append(entry)
    if len(entries) > 20:
        entries = entries[-20:]
    if _discover_history_save(entries):
        filter_count = len(active)
        xbmcgui.Dialog().ok(
            "Saved: {0}".format(name),
            "{0} filter{1} saved for {2}.".format(filter_count, "s" if filter_count != 1 else "", tmdb_type.upper())
        )
    else:
        xbmcgui.Dialog().notification("Xstream Pro", _label("Failed to save discover"))
    discover_builder_menu(params)


def discover_history_menu():
    if not _guard():
        return
    entries = _discover_history_load()
    items = []
    for idx, entry in enumerate(entries):
        name = entry.get("name") or "Unnamed"
        tmdb_type = entry.get("tmdb_type", "movie")
        label = "{0} ({1})".format(name, tmdb_type.upper())
        load_url = c("build_url")({"mode": "xstream_tmdb_discover_history_load", "idx": str(idx)})
        delete_url = c("build_url")({"mode": "xstream_tmdb_discover_history_delete", "idx": str(idx)})
        icon = c("_local_icon")("discover")
        fanart = c("_addon_fanart")()
        li = c("_new_listitem")(label)
        li.setArt(c("_menu_art")(icon, fanart))
        info = li.getVideoInfoTag()
        info.setMediaType("folder")
        info.setTitle(label)
        info.setPlot("{0} {1}".format(tmdb_type.upper(), _label("saved discover")))
        li.addContextMenuItems([("Delete", "RunPlugin({0})".format(delete_url))])
        items.append((load_url, li))
    if not items:
        li = c("_new_listitem")(_label("No saved discovers"))
        items.append(("", li, False))
    _add_items(items)


def discover_history_load_route(params):
    if not _guard():
        return
    try:
        idx = int(_param(params, "idx", "-1"))
    except Exception:
        idx = -1
    entries = _discover_history_load()
    if idx < 0 or idx >= len(entries):
        _end_empty("Saved discover not found")
        return
    entry = entries[idx]
    tmdb_type = entry.get("tmdb_type", "movie")
    saved_params = dict(entry.get("params") or {})
    saved_params["mode"] = "xstream_tmdb_discover_builder"
    saved_params["tmdb_type"] = tmdb_type
    discover_builder_menu(saved_params)
    return


def discover_history_delete_route(params):
    if not _guard():
        return
    try:
        idx = int(_param(params, "idx", "-1"))
    except Exception:
        idx = -1
    entries = _discover_history_load()
    if 0 <= idx < len(entries):
        name = entries[idx].get("name") or "Unnamed"
        entries.pop(idx)
        _discover_history_save(entries)
        xbmcgui.Dialog().notification("Xstream Pro", _t(31297, name))
    discover_history_menu()


def people_menu():
    if not _guard():
        return
    items = [
        _folder_item(c("_t")(30992), {"mode": "xstream_tmdb_people", "action": "search", "prompt": "true"}, "search"),
        _folder_item(c("_t")(30993), {"mode": "xstream_tmdb_people", "action": "popular"}, "people"),
        _folder_item(c("_t")(30998), {"mode": "xstream_tmdb_people", "action": "trending_day"}, "trending"),
        _folder_item(c("_t")(31001), {"mode": "xstream_tmdb_people", "action": "trending_week"}, "trending"),
    ]
    _add_items(items)


def lists_menu():
    if not _guard():
        return
    items = [
        _folder_item(c("_t")(31053), {"mode": "xstream_trakt_lists", "section": "trending"}, "trakt"),
        _folder_item(c("_t")(31054), {"mode": "xstream_trakt_lists", "section": "popular"}, "trakt"),
        _folder_item(c("_t")(31057), {"mode": "xstream_trakt_lists", "section": "search", "prompt": "true"}, "trakt"),
    ]
    if trakt.auth_configured() and trakt.authorized():
        items.extend([
            _folder_item(c("_t")(31055), {"mode": "xstream_trakt_lists", "section": "liked"}, "trakt"),
            _folder_item(c("_t")(31056), {"mode": "xstream_trakt_lists", "section": "my"}, "trakt"),
        ])
    _add_items(items)


def trakt_authorize_route(params):
    if not trakt.enabled() or not trakt.auth_configured():
        xbmcgui.Dialog().notification("Xstream Pro", _t(31228))
        xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
        return
    try:
        code = trakt.device_code()
        user_code = code.get("user_code", "")
        verification_url = code.get("verification_url", "https://trakt.tv/activate")
        device_code_value = code.get("device_code", "")
        expires_in = int(code.get("expires_in") or 600)
        interval = int(code.get("interval") or 5)
        progress = xbmcgui.DialogProgress()
        progress.create(
            "Trakt Authorization",
            "Go to {0} and enter code {1}".format(verification_url, user_code),
        )
        try:
            elapsed = 0
            while elapsed < expires_in:
                if progress.iscanceled():
                    break
                progress.update(
                    int((elapsed / float(expires_in)) * 100),
                    "Go to {0} and enter code {1}".format(verification_url, user_code),
                )
                token = trakt.poll_device_token(device_code_value)
                if token:
                    xbmcgui.Dialog().notification("Xstream Pro", _t(31257))
                    xbmc.executebuiltin("Container.Refresh")
                    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
                    return
                xbmc.sleep(_tvos_sleep(interval * 1000))
                elapsed += interval
        finally:
            progress.close()
        xbmcgui.Dialog().notification("Xstream Pro", _label("Trakt authorization cancelled or expired"))
    except Exception as exc:
        c("_log")("Trakt authorize error: {0}".format(exc))
        xbmcgui.Dialog().notification("Xstream Pro", _label("Trakt authorization failed"))
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)


def trakt_revoke_route(params):
    if not xbmcgui.Dialog().yesno("Xstream Pro", _t(31260)):
        xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
        return
    trakt.clear_tokens()
    xbmcgui.Dialog().notification("Xstream Pro", _label("Trakt disconnected"))
    xbmc.executebuiltin("Container.Refresh")
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)


def trakt_menu():
    if not _trakt_guard():
        return
    if not trakt.enabled():
        li = c("_new_listitem")("Direct Trakt menus are disabled")
        _add_items([("", li, False)])
        return

    items = [
        _folder_item("Trending Movies", {"mode": "xstream_trakt_public", "section": "trending", "tmdb_type": "movie"}, "trakt"),
        _folder_item("Trending TV", {"mode": "xstream_trakt_public", "section": "trending", "tmdb_type": "tv"}, "trakt"),
        _folder_item("Popular Movies", {"mode": "xstream_trakt_public", "section": "popular", "tmdb_type": "movie"}, "trakt"),
        _folder_item("Popular TV", {"mode": "xstream_trakt_public", "section": "popular", "tmdb_type": "tv"}, "trakt"),
        _folder_item("Box Office", {"mode": "xstream_trakt_public", "section": "boxoffice", "tmdb_type": "movie"}, "trakt"),
        _folder_item("Anticipated Movies", {"mode": "xstream_trakt_public", "section": "anticipated", "tmdb_type": "movie", "filter_provider": "false", "mark_unavailable": "true"}, "trakt"),
        _folder_item("Anticipated TV", {"mode": "xstream_trakt_public", "section": "anticipated", "tmdb_type": "tv", "filter_provider": "false", "mark_unavailable": "true"}, "trakt"),
        _folder_item(c("_t")(31053), {"mode": "xstream_trakt_lists", "section": "trending"}, "trakt"),
        _folder_item(c("_t")(31054), {"mode": "xstream_trakt_lists", "section": "popular"}, "trakt"),
        _folder_item(c("_t")(31057), {"mode": "xstream_trakt_lists", "section": "search", "prompt": "true"}, "trakt"),
    ]

    if trakt.auth_configured():
        if trakt.authorized():
            items.extend([
                _folder_item(c("_t")(31008), {"mode": "xstream_trakt_list", "section": "collection", "tmdb_type": "movie"}, "trakt"),
                _folder_item(c("_t")(31009), {"mode": "xstream_trakt_list", "section": "collection", "tmdb_type": "tv"}, "trakt"),
                _folder_item(c("_t")(31010), {"mode": "xstream_trakt_list", "section": "collection", "tmdb_type": "both"}, "trakt"),
                _folder_item(c("_t")(31011), {"mode": "xstream_trakt_list", "section": "favorites", "tmdb_type": "movie"}, "trakt"),
                _folder_item(c("_t")(31012), {"mode": "xstream_trakt_list", "section": "favorites", "tmdb_type": "tv"}, "trakt"),
                _folder_item(c("_t")(31013), {"mode": "xstream_trakt_list", "section": "favorites", "tmdb_type": "both"}, "trakt"),
                _folder_item(c("_t")(31014), {"mode": "xstream_trakt_list", "section": "watchlist", "tmdb_type": "movie"}, "trakt"),
                _folder_item(c("_t")(31015), {"mode": "xstream_trakt_list", "section": "watchlist", "tmdb_type": "tv"}, "trakt"),
                _folder_item(c("_t")(31018), {"mode": "xstream_trakt_list", "section": "watchlist", "tmdb_type": "both"}, "trakt"),
                _folder_item(c("_t")(31029), {"mode": "xstream_trakt_list", "section": "history", "tmdb_type": "movie"}, "trakt"),
                _folder_item(c("_t")(31030), {"mode": "xstream_trakt_list", "section": "history", "tmdb_type": "tv"}, "trakt"),
                _folder_item(c("_t")(31031), {"mode": "xstream_trakt_list", "section": "history", "tmdb_type": "both"}, "trakt"),
                _folder_item(c("_t")(31032), {"mode": "xstream_trakt_list", "section": "watched", "tmdb_type": "movie"}, "trakt"),
                _folder_item(c("_t")(31033), {"mode": "xstream_trakt_list", "section": "watched", "tmdb_type": "tv"}, "trakt"),
                _folder_item("{0} {1}".format(c("_t")(31034), c("_t")(30902)), {"mode": "xstream_trakt_playback", "media_kind": "movies"}, "trakt"),
                _folder_item("{0} {1}".format(c("_t")(31035), c("_t")(30903)), {"mode": "xstream_trakt_playback", "media_kind": "episodes"}, "trakt"),
                _folder_item(c("_t")(31016), {"mode": "xstream_trakt_list", "section": "watchlist", "tmdb_type": "season"}, "trakt"),
                _folder_item(c("_t")(31017), {"mode": "xstream_trakt_list", "section": "watchlist", "tmdb_type": "episode"}, "trakt"),
                _folder_item(c("_t")(31117), {"mode": "xstream_trakt_calendar_endpoint", "endpoint": "all", "days": "14"}, "trakt"),
                _folder_item(c("_t")(31118), {"mode": "xstream_trakt_calendar_endpoint", "endpoint": "movies", "days": "14"}, "trakt"),
                _folder_item(c("_t")(31119), {"mode": "xstream_trakt_calendar_endpoint", "endpoint": "shows", "days": "14"}, "trakt"),
                _folder_item(c("_t")(31036), {"mode": "xstream_trakt_next_episodes"}, "trakt"),
                _folder_item(c("_t")(31039), {"mode": "xstream_trakt_calendar_endpoint", "endpoint": "premieres", "days": "14"}, "trakt"),
                _folder_item(c("_t")(31046), {"mode": "xstream_trakt_calendar_endpoint", "endpoint": "new", "days": "14"}, "trakt"),
                _folder_item("{0} {1}".format(c("_t")(31040), c("_t")(30902)), {"mode": "xstream_trakt_list", "section": "recommendations", "tmdb_type": "movie"}, "trakt"),
                _folder_item("{0} {1}".format(c("_t")(31041), c("_t")(30903)), {"mode": "xstream_trakt_list", "section": "recommendations", "tmdb_type": "tv"}, "trakt"),
            ])
        else:
            items.append(_folder_item(_label("Authorize Trakt"), {"mode": "xstream_trakt_authorize"}, "trakt"))
    else:
        items.append(_folder_item("Add Trakt client secret for account features", {"mode": "settings"}, "settings"))

    _add_items(items)


def trakt_list_route(params):
    if not _trakt_guard(auth=True):
        return
    try:
        if not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        section = _param(params, "section", "watchlist")
        tmdb_type = _param(params, "tmdb_type", "movie")
        page = _int_param(params, "page")
        data = trakt.media_list(section, tmdb_type, page=page)
        content = "videos" if tmdb_type == "both" else ("tvshows" if tmdb_type == "tv" else "movies")
        data["results"] = _hydrate_trakt_items(data.get("results", []), sync_limit=20)
        _render_media_page(data, params, None if tmdb_type == "both" else tmdb_type, content)
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_playback_route(params):
    if not _trakt_guard(auth=True):
        return
    try:
        if not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        media_kind = _param(params, "media_kind", "movies")
        page = _int_param(params, "page")
        data = trakt.playback(media_kind, page=page)
        tmdb_type = "tv" if media_kind == "episodes" else "movie"
        data["results"] = _hydrate_trakt_items(data.get("results", []), sync_limit=20)
        _render_media_page(data, params, tmdb_type, "episodes" if tmdb_type == "tv" else "movies")
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_lists_route(params):
    section = _param(params, "section", "trending")
    needs_auth = section in ("my", "liked")
    if not _trakt_guard(auth=needs_auth):
        return
    try:
        query = _param(params, "query", "")
        if needs_auth and not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        if _bool_param(params, "prompt") and not query:
            query, should_return = _handle_search_prompt(
                params,
                "trakt_lists_{0}".format(section),
                "Search Trakt Lists",
            )
            if should_return:
                return
            if not query:
                xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
                return
        page = _int_param(params, "page")
        route_params = _query(params)
        route_params["query"] = query
        route_params["prompt"] = "false"
        data = trakt.trakt_lists(section, page=page, query=query)
        items = []
        for item in data.get("results", []):
            user_slug = item.get("user_slug") or "me"
            list_slug = item.get("list_slug") or ""
            if not list_slug:
                continue
            label = item.get("name") or "Untitled List"
            if user_slug and user_slug != "me":
                label = "{0} - {1}".format(label, user_slug)
            items.append(_folder_item(label, {
                "mode": "xstream_trakt_list_items",
                "user_slug": user_slug,
                "list_slug": list_slug,
                "title": label,
            }, "lists"))
        next_item = _next_page_item(route_params, int(data.get("page") or page), int(data.get("total_pages") or 1))
        if next_item:
            items.append(next_item)
        _add_items(items)
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_list_items_route(params):
    user_slug = _param(params, "user_slug", "me")
    needs_auth = str(user_slug or "").lower() == "me"
    if not _trakt_guard(auth=needs_auth):
        return
    try:
        list_slug = _param(params, "list_slug", "")
        item_type = _param(params, "item_type", "")
        page = _int_param(params, "page")
        if not list_slug:
            _end_empty("No Trakt list selected")
            return
        data = trakt.list_items(user_slug, list_slug, item_type=item_type, page=page, auth=needs_auth)
        data["results"] = _hydrate_trakt_items(data.get("results", []), sync_limit=20)
        _render_media_page(data, params, content="videos")
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_calendar_route(params):
    if not _trakt_guard(auth=True):
        return
    try:
        if not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        tmdb_type = _param(params, "tmdb_type", "tv")
        days = _int_param(params, "days", 14)
        data = trakt.calendar(tmdb_type, days=days)
        content = "videos" if tmdb_type == "both" else ("tvshows" if tmdb_type == "tv" else "movies")
        data["results"] = _hydrate_trakt_items(data.get("results", []), sync_limit=20)
        _render_media_page(data, params, None if tmdb_type == "both" else tmdb_type, content)
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_calendar_endpoint_route(params):
    if not _trakt_guard(auth=True):
        return
    try:
        if not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        endpoint = _param(params, "endpoint", "shows")
        days = _int_param(params, "days", 14)
        data = trakt.calendar_endpoint(endpoint, days=days)
        content = "videos" if endpoint == "all" else ("tvshows" if endpoint != "movies" else "movies")
        data["results"] = _hydrate_trakt_items(data.get("results", []), sync_limit=20)
        _render_media_page(data, params, content=content)
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_next_episodes_route(params):
    if not _trakt_guard(auth=True):
        return
    try:
        if not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        data = trakt.next_episodes()
        data["results"] = _hydrate_trakt_items(data.get("results", []), sync_limit=20)
        _render_media_page(data, params, content="episodes")
    except Exception as exc:
        _trakt_handle_error(exc)


def _provider_boxoffice_top10(page=1):
    if int(page or 1) != 1:
        return {"page": page, "total_pages": 1, "results": [], "raw": {}}
    results = []
    seen = set()

    def add_items(items):
        for item in items or []:
            key = _provider_result_key(item)
            if key in seen:
                continue
            if not _filter_provider_available_results([item]):
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= 10:
                return True
        return False

    try:
        trakt_data = trakt.public_list("boxoffice", tmdb_type="movie", page=1)
        trakt_data["results"] = _hydrate_trakt_items(trakt_data.get("results", []), sync_limit=20, prefetch_limit=40)
        add_items(trakt_data.get("results", []))
    except Exception:
        pass

    src_page = 1
    while len(results) < 10 and src_page <= 10:
        try:
            data = tmdb.movie_list("revenue", page=src_page)
        except Exception:
            break
        if add_items(data.get("results", [])):
            break
        if src_page >= int(data.get("total_pages") or 1):
            break
        src_page += 1

    return {"page": 1, "total_pages": 1, "results": results[:10], "raw": {}}


def trakt_public_route(params):
    if not _trakt_guard():
        return
    try:
        section = _param(params, "section", "trending")
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        period = _param(params, "period", "weekly")
        page = _int_param(params, "page")
        genre = _param(params, "genre", "")
        years = _param(params, "years", "")
        filter_provider = _param(params, "filter_provider", "true").lower() != "false"

        if section == "boxoffice" and tmdb_type == "movie" and _provider_only_route_enabled(filter_provider):
            page_data = _provider_boxoffice_top10(page)
            _render_media_page(page_data, params, "movie", "movies", filter_provider=False)
            return
        def _fetch_trakt_page(src_page):
            return trakt.public_list(
                section,
                tmdb_type=tmdb_type,
                page=src_page,
                period=period,
                genre=genre,
                years=years,
            )

        page_data = _fetch_merged_page(
            _fetch_trakt_page,
            page,
            merge_pages=MERGE_PAGES_TRAKT,
            filter_provider=filter_provider,
            fetch_key=("trakt_public", section, tmdb_type, period, genre, years),
            filter_watched=True,
        )
        page_data["results"] = _hydrate_trakt_items(page_data.get("results", []), sync_limit=20, prefetch_limit=40)
        _render_media_page(page_data, params, tmdb_type, "tvshows" if tmdb_type == "tv" else "movies", filter_provider=False)
    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_item_action_route(params):
    if not _trakt_guard(auth=True):
        return
    try:
        if not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        tmdb_type = _param(params, "tmdb_type", "movie")
        tmdb_id = _param(params, "tmdb_id", "")
        season = _param(params, "season", "")
        episode = _param(params, "episode", "")
        if not tmdb_id:
            xbmcgui.Dialog().notification("Xstream Pro", _label("No TMDB ID for Trakt action"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        actions = [
            ("Mark Watched on Trakt", "mark_watched", None),
            ("Mark Unwatched on Trakt", "mark_unwatched", None),
            ("Check In on Trakt", "checkin", None),
            ("Add to Watchlist", "watchlist", "add"),
            ("Remove from Watchlist", "watchlist", "remove"),
            ("Add to Collection", "collection", "add"),
            ("Remove from Collection", "collection", "remove"),
            ("Add to Favorites", "favorites", "add"),
            ("Remove from Favorites", "favorites", "remove"),
        ]
        choice = xbmcgui.Dialog().select(_label("Trakt Options"), [item[0] for item in actions])
        if choice < 0:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        label, action_type, action = actions[choice]
        if action_type == "mark_watched":
            trakt.mark_watched(tmdb_type, tmdb_id, season, episode)
        elif action_type == "mark_unwatched":
            trakt.mark_unwatched(tmdb_type, tmdb_id, season, episode)
        elif action_type == "checkin":
            trakt.checkin_item(tmdb_type, tmdb_id, season, episode)
        else:
            trakt.sync_item(action_type, action, tmdb_type, tmdb_id, season, episode)
        xbmcgui.Dialog().notification("Xstream Pro", label)
        xbmc.executebuiltin("Container.Refresh")
    except Exception as exc:
        c("_log")("Trakt item action error: {0}".format(exc))
        xbmcgui.Dialog().notification("Xstream Pro", _label("Trakt action failed"))
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)


def randomised_menu():
    if not _guard():
        return
    items = [
        _folder_item(c("_t")(30964), {"mode": "xstream_tmdb_random_genre", "tmdb_type": "movie"}, "themoviedb"),
        _folder_item(c("_t")(30965), {"mode": "xstream_tmdb_random_genre", "tmdb_type": "tv"}, "themoviedb"),
        _folder_item(c("_t")(30966), {"mode": "xstream_tmdb_random_keyword"}, "themoviedb"),
        _folder_item(_t(31042), {"mode": "xstream_trakt_recommendations", "tmdb_type": "movie"}, "trakt"),
        _folder_item(_t(31042), {"mode": "xstream_trakt_recommendations", "tmdb_type": "tv"}, "trakt"),
        _folder_item(c("_t")(30971), {"mode": "xstream_trakt_random_public", "section": "trending", "tmdb_type": "movie"}, "trakt"),
        _folder_item(c("_t")(30972), {"mode": "xstream_trakt_random_public", "section": "trending", "tmdb_type": "tv"}, "trakt"),
        _folder_item(c("_t")(30973), {"mode": "xstream_trakt_random_public", "section": "trending", "tmdb_type": "both"}, "trakt"),
        _folder_item(c("_t")(30974), {"mode": "xstream_trakt_random_public", "section": "popular", "tmdb_type": "movie"}, "trakt"),
        _folder_item(c("_t")(30975), {"mode": "xstream_trakt_random_public", "section": "popular", "tmdb_type": "tv"}, "trakt"),
        _folder_item(c("_t")(30976), {"mode": "xstream_trakt_random_public", "section": "popular", "tmdb_type": "both"}, "trakt"),
        _folder_item(c("_t")(30977), {"mode": "xstream_trakt_random_public", "section": "played", "tmdb_type": "movie"}, "trakt"),
        _folder_item(c("_t")(30978), {"mode": "xstream_trakt_random_public", "section": "played", "tmdb_type": "tv"}, "trakt"),
        _folder_item(c("_t")(30979), {"mode": "xstream_trakt_random_public", "section": "played", "tmdb_type": "both"}, "trakt"),
        _folder_item(_label("Random Watched"), {"mode": "xstream_trakt_random_public", "section": "watched", "tmdb_type": "movie"}, "trakt"),
        _folder_item(_label("Random Watched TV"), {"mode": "xstream_trakt_random_public", "section": "watched", "tmdb_type": "tv"}, "trakt"),
        _folder_item(_label("Random Watched Combined"), {"mode": "xstream_trakt_random_public", "section": "watched", "tmdb_type": "both"}, "trakt"),
        _folder_item(c("_t")(30980), {"mode": "xstream_trakt_random_public", "section": "collected", "tmdb_type": "movie"}, "trakt"),
        _folder_item(c("_t")(30981), {"mode": "xstream_trakt_random_public", "section": "collected", "tmdb_type": "tv"}, "trakt"),
        _folder_item(c("_t")(30982), {"mode": "xstream_trakt_random_public", "section": "collected", "tmdb_type": "both"}, "trakt"),
        _folder_item(c("_t")(30983), {"mode": "xstream_trakt_random_public", "section": "anticipated", "tmdb_type": "movie"}, "trakt"),
        _folder_item(c("_t")(30984), {"mode": "xstream_trakt_random_public", "section": "anticipated", "tmdb_type": "tv"}, "trakt"),
        _folder_item(c("_t")(30985), {"mode": "xstream_trakt_random_public", "section": "anticipated", "tmdb_type": "both"}, "trakt"),
        _folder_item(c("_t")(30986), {"mode": "xstream_trakt_random_list", "section": "trending"}, "trakt"),
        _folder_item(c("_t")(30987), {"mode": "xstream_trakt_random_list", "section": "popular"}, "trakt"),
        _folder_item(c("_t")(30988), {"mode": "xstream_trakt_random_list", "section": "liked"}, "trakt"),
        _folder_item(c("_t")(30989), {"mode": "xstream_trakt_random_list", "section": "my"}, "trakt"),
    ]
    _add_items(items)


def random_genre_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        genres = tmdb.genres(tmdb_type)

        if not genres:
            _end_empty("No genres found")
            return

        best_data = None
        best_params = None
        best_count = 0

        random.shuffle(genres)

        for genre in genres[:8]:
            genre_id = str(genre.get("id") or "")
            if not genre_id:
                continue

            route_params = {
                "mode": "xstream_tmdb_discover",
                "tmdb_type": tmdb_type,
                "genre_id": genre_id,
                "sort_by": "popularity.desc",
                "page": "1",
            }

            first = tmdb.discover(tmdb_type, _discover_params(route_params, tmdb_type), page=1)
            total_pages = max(1, int(first.get("total_pages") or 1))

            page = random.randint(1, min(total_pages, 10))
            route_params["page"] = str(page)

            data = tmdb.discover(tmdb_type, _discover_params(route_params, tmdb_type), page=page)
            count = _visible_random_count(data.get("results", []) or [])

            if count > best_count:
                best_data = data
                best_params = dict(route_params)
                best_count = count

            if count >= 8:
                break

        if best_data and best_params:
            _render_media_page(
                best_data,
                best_params,
                tmdb_type,
                "tvshows" if tmdb_type == "tv" else "movies",
            )
            return

        _end_empty("No genres found")

    except Exception as exc:
        _handle_error(exc)


def random_keyword_route(params):
    if not _guard():
        return
    try:
        letters = list("abcdefghijklmnopqrstuvwxyz")
        random.shuffle(letters)

        best_data = None
        best_params = None
        best_count = 0

        for letter in letters[:8]:
            kw_page1 = tmdb.search_keywords(letter, page=1)
            kw_total = max(1, int(kw_page1.get("total_pages") or 1))

            kw_data = tmdb.search_keywords(letter, page=random.randint(1, min(kw_total, 5)))
            keywords = kw_data.get("results", []) or []
            random.shuffle(keywords)

            for keyword in keywords[:5]:
                keyword_id = str(keyword.get("id") or "")
                if not keyword_id:
                    continue

                first = tmdb.discover(
                    "movie",
                    {"with_keywords": keyword_id, "sort_by": "popularity.desc"},
                    page=1,
                )

                disc_total = max(1, int(first.get("total_pages") or 1))
                page = random.randint(1, min(disc_total, 10))

                route_params = {
                    "mode": "xstream_tmdb_discover",
                    "tmdb_type": "movie",
                    "with_keywords": keyword_id,
                    "sort_by": "popularity.desc",
                    "page": str(page),
                }

                data = tmdb.discover("movie", _discover_params(route_params, "movie"), page=page)
                count = _visible_random_count(data.get("results", []) or [])

                if count > best_count:
                    best_data = data
                    best_params = dict(route_params)
                    best_count = count

                if count >= 8:
                    _render_media_page(best_data, best_params, "movie", "movies")
                    return

        if best_data and best_params and best_count > 0:
            _render_media_page(best_data, best_params, "movie", "movies")
            return

        random_genre_route({"tmdb_type": "movie"})

    except Exception as exc:
        _handle_error(exc)


def trakt_random_public_route(params):
    if not _trakt_guard():
        return
    try:
        section = _param(params, "section", "trending")
        tmdb_type = _param(params, "tmdb_type", "movie")

        lookup_type = "movie" if tmdb_type == "both" else tmdb_type
        page1_data = trakt.public_list(section, lookup_type, page=1)
        total_pages = max(1, int(page1_data.get("total_pages") or 1))

        best_data = None
        best_count = 0

        for _attempt in range(8):
            page = random.randint(1, min(total_pages, 10))

            if tmdb_type == "both":
                movie_data = trakt.public_list(section, "movie", page=page)
                tv_data = trakt.public_list(section, "tv", page=page)

                results = _hydrate_trakt_items(
                    (movie_data.get("results", []) or []) + (tv_data.get("results", []) or []),
                    sync_limit=20,
                    prefetch_limit=40,
                )

                data = {
                    "page": 1,
                    "total_pages": 1,
                    "results": results,
                    "raw": {},
                }

                count = _visible_random_count(results)
                content = "videos"
                media_type = None

            else:
                data = trakt.public_list(section, tmdb_type, page=page)
                data["results"] = _hydrate_trakt_items(
                    data.get("results", []) or [],
                    sync_limit=20,
                    prefetch_limit=40,
                )

                count = _visible_random_count(data.get("results", []) or [])
                content = "tvshows" if tmdb_type == "tv" else "movies"
                media_type = tmdb_type

            if count > best_count:
                best_data = data
                best_count = count

            if count >= 8:
                break

        if best_data and best_data.get("results"):
            _render_media_page(
                best_data,
                params,
                None if tmdb_type == "both" else media_type,
                content,
            )
            return

        _end_empty(31229)

    except Exception as exc:
        _trakt_handle_error(exc)


def trakt_random_list_route(params):
    section = _param(params, "section", "trending")
    needs_auth = section in ("liked", "my")
    if not _trakt_guard(auth=needs_auth):
        return
    try:
        if needs_auth and not trakt.authorized():
            xbmcgui.Dialog().notification("Xstream Pro", _label("Authorize Trakt first"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return

        page1_data = trakt.trakt_lists(section, page=1)
        total_pages = max(1, int(page1_data.get("total_pages") or 1))

        best_data = None
        best_count = 0

        for _attempt in range(8):
            lists_page = random.randint(1, min(total_pages, 5))
            data = trakt.trakt_lists(section, page=lists_page)
            lists = data.get("results", []) or []

            if not lists:
                continue

            random.shuffle(lists)

            for item in lists[:5]:
                list_slug = item.get("list_slug") or ""
                user_slug = item.get("user_slug") or "me"

                if not list_slug:
                    continue

                list_data = trakt.list_items(user_slug, list_slug, page=1)
                list_data["results"] = _hydrate_trakt_items(
                    list_data.get("results", []) or [],
                    sync_limit=20,
                    prefetch_limit=40,
                )

                count = _visible_random_count(list_data.get("results", []) or [])

                if count > best_count:
                    best_data = list_data
                    best_count = count

                if count >= 8:
                    _render_media_page(best_data, params, content="videos")
                    return

        if best_data and best_data.get("results"):
            _render_media_page(best_data, params, content="videos")
            return

        _end_empty("No Trakt lists found")

    except Exception as exc:
        _trakt_handle_error(exc)


def _decade_label(start, end):
    return "{0}-{1}".format(start, end)


def years_menu(tmdb_type):
    if not _guard():
        return
    current_year = datetime.datetime.now().year
    items = []
    for year in range(current_year, 1969, -1):
        items.append(_folder_item(str(year), {"mode": "xstream_tmdb_discover", "tmdb_type": tmdb_type, "year": str(year), "sort_by": "popularity.desc"}, "years"))
    _add_items(items)


def decades_menu(tmdb_type):
    if not _guard():
        return
    decades = [(2020, 2029), (2010, 2019), (2000, 2009), (1990, 1999), (1980, 1989), (1970, 1979), (1960, 1969), (1950, 1959), (1940, 1949), (1930, 1939)]
    items = []
    for start, end in decades:
        items.append(_folder_item(_decade_label(start, end), {"mode": "xstream_tmdb_discover", "tmdb_type": tmdb_type, "date_gte": "{0}-01-01".format(start), "date_lte": "{0}-12-31".format(end), "sort_by": "popularity.desc"}, "decades"))
    _add_items(items)


def list_route(params):
    if not _guard():
        return
    try:
        tmdb_type = _param(params, "tmdb_type", "movie")
        list_name = _param(params, "list_name", "popular")
        page = _int_param(params, "page")
        filter_provider = _param(params, "filter_provider", "true").lower() != "false"

        def _fetch_list_page(src_page):
            if tmdb_type == "tv":
                return tmdb.tv_list(list_name, page=src_page)
            return tmdb.movie_list(list_name, page=src_page)

        page_data = _fetch_merged_page(
            _fetch_list_page,
            page,
            filter_provider=filter_provider,
            fetch_key=("tmdb_list", tmdb_type, list_name),
            filter_watched=True,
        )
        content = "tvshows" if tmdb_type == "tv" else "movies"
        _render_media_page(page_data, params, tmdb_type, content, filter_provider=False)
    except Exception as exc:
        _handle_error(exc)


def search_route(params):
    if not _guard():
        return
    try:
        tmdb_type = _param(params, "tmdb_type", "movie")
        query, should_return = _handle_search_prompt(params, tmdb_type, "Search TMDB")
        if should_return:
            return
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        page = _int_param(params, "page")
        route_params = _query(params)
        route_params["query"] = query
        route_params["prompt"] = "false"
        def _fetch_search_page(src_page):
            if tmdb_type == "both":
                return tmdb.multi_search(query, page=src_page)
            return tmdb.search(tmdb_type, query, page=src_page)
        if tmdb_type == "both":
            data = _fetch_exact_unfiltered_page(
                _fetch_search_page,
                page,
                fetch_key=("tmdb_search", tmdb_type, query),
                page_size=PROVIDER_PAGE_SIZE,
                filter_watched=_hide_watched_enabled(),
            )
            _render_media_page(data, route_params, content="videos", filter_provider=False)
        else:
            data = _fetch_exact_unfiltered_page(
                _fetch_search_page,
                page,
                fetch_key=("tmdb_search", tmdb_type, query),
                page_size=PROVIDER_PAGE_SIZE,
                filter_watched=_hide_watched_enabled(),
            )
            _render_media_page(
                data,
                route_params,
                tmdb_type,
                "tvshows" if tmdb_type == "tv" else "movies",
                filter_provider=False,
            )
    except Exception as exc:
        _handle_error(exc)


_COLLECTIONS = [
    # 0-25: Absolute giants
    ("Star Wars", "10"),
    ("Marvel: The Avengers", "86311"),
    ("Marvel: Iron Man", "131292"),
    ("Marvel: Spider-Man", "556"),
    ("Marvel: Spider-Man (MCU)", "531241"),
    ("Marvel: Spider-Man (The Amazing)", "125574"),
    ("Marvel: Captain America", "131295"),
    ("Marvel: Thor", "131296"),
    ("Marvel: Guardians of the Galaxy", "284433"),
    ("Marvel: Black Panther", "529892"),
    ("Marvel: Doctor Strange", "618529"),
    ("Marvel: Ant-Man", "422834"),
    ("Marvel: Captain Marvel", "623911"),
    ("Marvel: Venom", "558216"),
    ("Marvel: Deadpool", "448150"),
    ("Marvel: Wolverine", "453993"),
    ("Marvel: X-Men", "748"),
    ("Marvel: Fantastic Four", "9744"),
    ("Harry Potter", "1241"),
    ("The Lord of the Rings", "119"),
    ("The Hobbit", "121938"),
    ("James Bond", "645"),
    ("Fast & Furious", "9485"),
    ("Jurassic Park", "328"),
    ("Pirates of the Caribbean", "295"),
    ("Transformers", "8650"),

    # 26-50: Major franchises
    ("Batman", "120794"),
    ("The Batman", "948485"),
    ("Superman", "8537"),
    ("Mission: Impossible", "87359"),
    ("John Wick", "404609"),
    ("The Matrix", "2344"),
    ("Terminator", "528"),
    ("Alien", "8091"),
    ("Predator", "399"),
    ("Indiana Jones", "84"),
    ("Back to the Future", "264"),
    ("Ghostbusters", "2980"),
    ("Jaws", "2366"),
    ("Men in Black", "86055"),
    ("Star Trek", "115575"),
    ("Rocky", "1575"),
    ("Rambo", "5039"),
    ("Mad Max", "8945"),
    ("Die Hard", "1570"),
    ("Lethal Weapon", "945"),
    ("Bad Boys", "14890"),
    ("Blade", "735"),
    ("RoboCop", "5547"),
    ("Beverly Hills Cop", "85861"),
    ("Rush Hour", "90863"),

    # 51-75: Popular animation + strong action
    ("Toy Story", "10194"),
    ("Shrek", "2150"),
    ("Despicable Me", "86066"),
    ("Minions", "544669"),
    ("Frozen", "386382"),
    ("Finding Nemo", "137697"),
    ("The Incredibles", "468222"),
    ("Cars", "87118"),
    ("Ice Age", "8354"),
    ("Kung Fu Panda", "77816"),
    ("How to Train Your Dragon", "89137"),
    ("Hotel Transylvania", "185103"),
    ("Monsters, Inc.", "306926"),
    ("Coco", "1451578"),
    ("Moana", "1241984"),
    ("Zootopia", "1084247"),
    ("Tangled", "1268789"),
    ("Madagascar", "14740"),
    ("The Lego Movie", "325470"),
    ("The Transporter", "9518"),
    ("Kingsman", "391860"),
    ("Taken", "135483"),
    ("Equalizer", "523855"),
    ("Jason Bourne", "31562"),
    ("Planet of the Apes", "1709"),

    # 76-100: Sci-fi/fantasy + horror legends
    ("Dune", "726871"),
    ("Godzilla", "535313"),
    ("King Kong", "135498"),
    ("Blade Runner", "422837"),
    ("Independence Day", "304378"),
    ("Pacific Rim", "363369"),
    ("Tron", "63043"),
    ("The Hunger Games", "131635"),
    ("The Maze Runner", "295130"),
    ("Percy Jackson", "179919"),
    ("The Chronicles of Narnia", "420"),
    ("Starship Troopers", "10522"),
    ("The Thing", "479888"),
    ("Halloween", "91361"),
    ("A Nightmare on Elm Street", "8581"),
    ("Friday the 13th", "9735"),
    ("Texas Chainsaw Massacre", "111751"),
    ("Saw", "656"),
    ("Scream", "2602"),
    ("The Conjuring", "313086"),
    ("Child's Play", "10455"),
    ("Evil Dead", "1960"),
    ("It", "477962"),
    ("The Purge", "256322"),
    ("A Quiet Place", "521226"),

    # 101-125: Continue horror + some fantasy
    ("Annabelle", "402074"),
    ("The Nun", "968052"),
    ("Insidious", "228446"),
    ("Sinister", "357173"),
    ("Final Destination", "8864"),
    ("The Exorcist", "12263"),
    ("The Shining", "530064"),
    ("Poltergeist", "10453"),
    ("Beetlejuice", "945475"),
    ("Gremlins", "89151"),
    ("Resident Evil", "17255"),
    ("Silent Hill", "64748"),
    ("Mortal Kombat", "9818"),
    ("Teenage Mutant Ninja Turtles", "1195879"),
    ("Sonic the Hedgehog", "720879"),
    ("G.I. Joe", "135467"),
    ("Twilight", "33514"),
    ("Fifty Shades", "344830"),
    ("Divergent", "283579"),
    ("Uncharted", "1216426"),
    ("Tomb Raider", "2467"),
    ("Hitman", "737031"),
    ("Doom", "634390"),
    ("Wonder Woman", "468552"),
    ("Aquaman", "573693"),

    # 126-150: DC standalone + B-tier action
    ("Suicide Squad", "531242"),
    ("Shazam!", "724848"),
    ("Joker", "987044"),
    ("Ghost Rider", "90306"),
    ("The Punisher", "635362"),
    ("Constantine", "1025281"),
    ("Watchmen", "1304326"),
    ("Kick-Ass", "179892"),
    ("300", "125570"),
    ("Sin City", "135179"),
    ("Mothra", "171732"),
    ("Crank", "64751"),
    ("Mechanic", "280504"),
    ("Jack Reacher", "403374"),
    ("Jack Ryan", "192492"),
    ("Nobody", "1129084"),
    ("Gunpowder Milkshake", "848375"),
    ("Extraction", "735127"),
    ("The Old Guard", "847029"),
    ("The Expendables", "126125"),
    ("Commando", "606601"),
    ("Face/Off", "1110736"),
    ("Gone in 60 Seconds", "391040"),
    ("National Treasure", "52984"),
    ("Speed", "43064"),

    # 151-171: Bottom tier
    ("Twister", "1062948"),
    ("Olympus Has Fallen", "386534"),
    ("The Incredible Hulk", "114431"),
    ("Terrifier", "727761"),
    ("M3GAN", "1071588"),
    ("Smile", "1100788"),
    ("Happy Death Day", "526380"),
    ("The Omen", "10919"),
    ("Don't Breathe", "748919"),
    ("I Know What You Did Last Summer", "3601"),
    ("Urban Legend", "1106118"),
    ("Candyman", "98580"),
    ("Hellraiser", "8917"),
    ("Phantasm", "47770"),
    ("Wrong Turn", "52985"),
    ("Carrie", "257053"),
    ("Pet Sematary", "10789"),
    ("La Llorona", "1533646"),
    ("Us", "784039"),
    ("Cloudy with a Chance of Meatballs", "177467"),
]

_TV_COLLECTIONS = [
    ("marvel-tv", "Marvel TV Universe", [
        ("2164", "The Marvel Super Heroes"),
        ("1482", "Spider-Man"),
        ("3973", "Spider-Man"),
        ("888", "Spider-Man"),
        ("10079", "Spider-Man Unlimited"),
        ("1664", "Spider-Man: The New Animated Series"),
        ("3854", "The Spectacular Spider-Man"),
        ("34391", "Marvel's Ultimate Spider-Man"),
        ("72705", "Marvel's Spider-Man"),
        ("127635", "Spidey and His Amazing Friends"),
        ("138503", "Your Friendly Neighborhood Spider-Man"),
        ("4784", "Spider-Woman"),
        ("648", "The Incredible Hulk"),
        ("11328", "The Incredible Hulk"),
        ("6332", "The Incredible Hulk"),
        ("1651", "The Fantastic Four"),
        ("2373", "The Fantastic Four"),
        ("2901", "Fantastic Four"),
        ("132", "Fantastic Four: World's Greatest Heroes"),
        ("3097", "Iron Man"),
        ("7330", "Iron Man: Armored Adventures"),
        ("45418", "Iron Man"),
        ("274388", "Iron Man and His Awesome Friends"),
        ("1130", "Silver Surfer"),
        ("4574", "X-Men"),
        ("668", "X-Men: Evolution"),
        ("6549", "Wolverine and the X-Men"),
        ("43146", "X-Men"),
        ("138502", "X-Men '97"),
        ("1300", "The Avengers: United They Stand"),
        ("33623", "The Avengers: Earth's Mightiest Heroes"),
        ("59427", "Marvel's Avengers"),
        ("21781", "The Super Hero Squad Show"),
        ("70801", "Marvel Disk Wars: The Avengers"),
        ("91278", "Marvel's Future Avengers"),
        ("63181", "Marvel's Guardians of the Galaxy"),
        ("40044", "Marvel's Hulk and the Agents of S.M.A.S.H."),
        ("70784", "Marvel's Rocket & Groot"),
        ("83043", "Marvel Rising: Initiation"),
        ("93508", "Marvel Super Hero Adventures"),
        ("92788", "Marvel's Moon Girl and Devil Dinosaur"),
        ("4619", "Blade: The Series"),
        ("62798", "Blade"),
        ("61550", "Marvel's Agent Carter"),
        ("1403", "Marvel's Agents of S.H.I.E.L.D."),
        ("61889", "Marvel's Daredevil"),
        ("38472", "Marvel's Jessica Jones"),
        ("62126", "Marvel's Luke Cage"),
        ("62127", "Marvel's Iron Fist"),
        ("62285", "Marvel's The Defenders"),
        ("67178", "Marvel's The Punisher"),
        ("66190", "Marvel's Cloak & Dagger"),
        ("67466", "Marvel's Runaways"),
        ("68716", "Marvel's Inhumans"),
        ("88987", "Helstrom"),
        ("85271", "WandaVision"),
        ("88396", "The Falcon and the Winter Soldier"),
        ("84958", "Loki"),
        ("91363", "What If...?"),
        ("88329", "Hawkeye"),
        ("92749", "Moon Knight"),
        ("92782", "Ms. Marvel"),
        ("92783", "She-Hulk: Attorney at Law"),
        ("114472", "Secret Invasion"),
        ("122226", "Echo"),
        ("138501", "Agatha All Along"),
        ("202555", "Daredevil: Born Again"),
        ("114471", "Ironheart"),
        ("232125", "I Am Groot"),
        ("138505", "Marvel Zombies"),
        ("241388", "Eyes of Wakanda"),
        ("133903", "Marvel's Hit-Monkey"),
        ("111312", "Marvel's M.O.D.O.K."),
    ], "/EpDuYIK81YtCUT3gH2JDpyj8Qk.jpg", "/2jPv3B0ikeGjEYZKDX8vJGXJrvh.jpg"),
    ("dc-tv", "DC TV Universe", [
        ("12662", "Adventures of Superman"),
        ("10786", "The New Adventures of Superman"),
        ("3014", "The Superman/Aquaman Hour of Adventure"),
        ("31749", "The Adventures of Batman"),
        ("936", "Super Friends"),
        ("10159", "The All-New Super Friends Hour"),
        ("10610", "Challenge of the Super Friends"),
        ("10502", "The New Adventures of Batman"),
        ("236", "The Flash"),
        ("4515", "Lois & Clark: The New Adventures of Superman"),
        ("4532", "Superboy"),
        ("4604", "Smallville"),
        ("1469", "Birds of Prey"),
        ("2098", "Batman: The Animated Series"),
        ("4625", "The New Batman Adventures"),
        ("513", "Batman Beyond"),
        ("4303", "Superman: The Animated Series"),
        ("1618", "Justice League"),
        ("84200", "Justice League Unlimited"),
        ("1487", "Static Shock"),
        ("4508", "The Zeta Project"),
        ("604", "Teen Titans"),
        ("45140", "Teen Titans Go!"),
        ("33217", "Young Justice"),
        ("40351", "Green Lantern: The Animated Series"),
        ("41676", "Beware the Batman"),
        ("2022", "The Batman"),
        ("68837", "Justice League Action"),
        ("63266", "Justice League: Gods and Monsters Chronicles"),
        ("64365", "DC Super Hero Girls"),
        ("87491", "DC Super Hero Girls"),
        ("74440", "Harley Quinn"),
        ("200753", "Kite Man: Hell Yeah!"),
        ("98137", "Aquaman: King of Atlantis"),
        ("125928", "My Adventures with Superman"),
        ("155780", "Batwheels"),
        ("125909", "Batman: Caped Crusader"),
        ("1412", "Arrow"),
        ("60735", "The Flash"),
        ("62688", "Supergirl"),
        ("62643", "DC's Legends of Tomorrow"),
        ("71663", "Black Lightning"),
        ("89247", "Batwoman"),
        ("95057", "Superman & Lois"),
        ("195868", "Gotham Knights"),
        ("60708", "Gotham"),
        ("79588", "Pennyworth: The Origin of Batman's Butler"),
        ("194764", "The Penguin"),
        ("75450", "Titans"),
        ("79501", "Doom Patrol"),
        ("110492", "Peacemaker"),
        ("219543", "Creature Commandos"),
        ("80986", "DC's Stargirl"),
        ("60743", "Constantine"),
        ("71340", "Krypton"),
        ("79240", "Swamp Thing"),
        ("79788", "Watchmen"),
        ("90802", "The Sandman"),
        ("132750", "Dead Boy Detectives"),
        ("125474", "Naomi"),
        ("63174", "Lucifer"),
        ("103768", "Sweet Tooth"),
        ("64230", "Preacher"),
        ("113566", "DMZ"),
        ("86550", "Y: The Last Man"),
    ], "/oNLAgnP1fKAA1jLWvzAoJFd1kNe.jpg", "/9B1rZX1xzEMARwC7kJ5Fb0ahAF7.jpg"),
    ("star-wars-tv", "Star Wars TV Universe", [
        ("25", "Star Wars: Droids"),
        ("3478", "Ewoks"),
        ("4194", "Star Wars: The Clone Wars"),
        ("60554", "Star Wars Rebels"),
        ("79093", "Star Wars Resistance"),
        ("82856", "The Mandalorian"),
        ("115036", "The Book of Boba Fett"),
        ("105971", "Star Wars: The Bad Batch"),
        ("83867", "Andor"),
        ("92830", "Obi-Wan Kenobi"),
        ("114461", "Ahsoka"),
        ("202879", "Star Wars: Skeleton Crew"),
        ("203085", "Star Wars: Tales of the Jedi"),
        ("251091", "Star Wars: Tales of the Empire"),
        ("114478", "Star Wars: Visions"),
        ("114479", "The Acolyte"),
        ("63722", "LEGO Star Wars: Droid Tales"),
        ("66837", "LEGO Star Wars: The Freemaker Adventures"),
        ("83558", "LEGO Star Wars: All-Stars"),
        ("71412", "Star Wars: Forces of Destiny"),
        ("202998", "Star Wars: Young Jedi Adventures"),
        ("85536", "Star Wars Galaxy of Adventures"),
        ("105106", "Star Wars Blips"),
        ("124868", "Star Wars Roll Out"),
    ], "/gNbdjDi1HamTCrfvM9JeA94bNi2.jpg", "/oMWnpUUCeIqvTdP3IYZ0JnPdrmU.jpg"),
    ("game-of-thrones", "Game of Thrones Universe", [
        ("1399", "Game of Thrones"),
        ("94997", "House of the Dragon"),
        ("224372", "A Knight of the Seven Kingdoms"),
    ], "", ""),
    ("star-trek", "Star Trek Universe", [
        ("253", "Star Trek"),
        ("1992", "Star Trek"),
        ("655", "Star Trek: The Next Generation"),
        ("580", "Star Trek: Deep Space Nine"),
        ("1855", "Star Trek: Voyager"),
        ("314", "Star Trek: Enterprise"),
        ("67198", "Star Trek: Discovery"),
        ("82491", "Star Trek: Short Treks"),
        ("85949", "Star Trek: Picard"),
        ("103516", "Star Trek: Strange New Worlds"),
        ("85948", "Star Trek: Lower Decks"),
        ("106393", "Star Trek: Prodigy"),
        ("223530", "Star Trek: Starfleet Academy"),
    ], "", ""),
    ("walking-dead", "The Walking Dead Universe", [
        ("1402", "The Walking Dead"),
        ("62286", "Fear the Walking Dead"),
        ("94305", "The Walking Dead: World Beyond"),
        ("136248", "Tales of the Walking Dead"),
        ("194583", "The Walking Dead: Dead City"),
        ("211684", "The Walking Dead: Daryl Dixon"),
        ("206586", "The Walking Dead: The Ones Who Live"),
        ("272594", "The Walking Dead: Torn Apart"),
        ("274853", "The Walking Dead: Cold Storage"),
        ("275503", "The Walking Dead: The Oath"),
        ("233436", "The Walking Dead: Red Machete"),
    ], "/rqeYMLryjcawh2JeRpCVUDXYM5b.jpg", "/w7zzw7Lt0j9rQjbzbTjm9ZImX6H.jpg"),
    ("breaking-bad", "Breaking Bad Universe", [
        ("1396", "Breaking Bad"),
        ("60059", "Better Call Saul"),
        ("158704", "Better Call Saul Presents: Slippin' Jimmy"),
    ], "", ""),
    ("the-boys", "The Boys Universe", [
        ("76479", "The Boys"),
        ("152483", "The Boys Presents: Diabolical"),
        ("205715", "Gen V"),
        ("259878", "Vought Rising"),
        ("318945", "The Boys: Mexico"),
    ], "", ""),
    ("doctor-who", "Doctor Who Universe", [
        ("121", "Doctor Who"),
        ("57243", "Doctor Who"),
        ("424", "Torchwood"),
        ("203", "The Sarah Jane Adventures"),
        ("1057", "K-9 and Company"),
        ("25831", "K-9"),
        ("64073", "Class"),
        ("129387", "Doctor Who: Dreamland"),
        ("1056", "Doctor Who Confidential"),
        ("203946", "Doctor Who: Unleashed"),
        ("238486", "Tales of the Tardis"),
    ], "", ""),
    ("yellowstone", "Yellowstone Universe", [
        ("73586", "Yellowstone"),
        ("118357", "1883"),
        ("157744", "1923"),
        ("225891", "The Madison"),
        ("290856", "Marshals"),
    ], "", ""),
    ("vampire-diaries", "The Vampire Diaries Universe", [
        ("18165", "The Vampire Diaries"),
        ("46896", "The Originals"),
        ("79460", "Legacies"),
    ], "", ""),
    ("stargate", "Stargate Universe", [
        ("4629", "Stargate SG-1"),
        ("2290", "Stargate Atlantis"),
        ("5148", "Stargate Universe"),
        ("2580", "Stargate Infinity"),
        ("72925", "Stargate Origins"),
    ], "", ""),
    ("ncis", "NCIS Universe", [
        ("4376", "JAG"),
        ("4614", "NCIS"),
        ("17610", "NCIS: Los Angeles"),
        ("61387", "NCIS: New Orleans"),
        ("124271", "NCIS: Hawai\u02bbi"),
        ("157950", "NCIS: Sydney"),
        ("243006", "NCIS: Origins"),
        ("247732", "NCIS: Tony & Ziva"),
    ], "", ""),
    ("law-and-order", "Law & Order Universe", [
        ("549", "Law & Order"),
        ("2734", "Law & Order: Special Victims Unit"),
        ("4601", "Law & Order: Criminal Intent"),
        ("3357", "Law & Order: Trial by Jury"),
        ("32632", "Law & Order: LA"),
        ("72496", "Law & Order True Crime"),
        ("106158", "Law & Order: Organized Crime"),
        ("228026", "Law & Order Toronto: Criminal Intent"),
        ("7098", "Law & Order: UK"),
        ("14773", "Paris enqu\u00eates criminelles"),
    ], "", ""),
    ("chicago", "One Chicago Universe", [
        ("44006", "Chicago Fire"),
        ("58841", "Chicago P.D."),
        ("62650", "Chicago Med"),
        ("67993", "Chicago Justice"),
    ], "", ""),
    ("csi", "CSI Universe", [
        ("1431", "CSI: Crime Scene Investigation"),
        ("1620", "CSI: Miami"),
        ("2458", "CSI: NY"),
        ("61811", "CSI: Cyber"),
        ("122194", "CSI: Vegas"),
    ], "", ""),
    ("fbi", "FBI Universe", [
        ("80748", "FBI"),
        ("94372", "FBI: Most Wanted"),
        ("121658", "FBI: International"),
        ("289560", "CIA"),
    ], "", ""),
    ("911", "9-1-1 Universe", [
        ("75219", "9-1-1"),
        ("89393", "9-1-1: Lone Star"),
        ("284838", "9-1-1: Nashville"),
    ], "", ""),
    ("rookie", "The Rookie Universe", [
        ("79744", "The Rookie"),
        ("201992", "The Rookie: Feds"),
    ], "", ""),
    ("criminal-minds", "Criminal Minds Universe", [
        ("4057", "Criminal Minds"),
        ("32200", "Criminal Minds: Suspect Behavior"),
        ("64481", "Criminal Minds: Beyond Borders"),
    ], "", ""),
    ("pretty-little-liars", "Pretty Little Liars Universe", [
        ("31917", "Pretty Little Liars"),
        ("46958", "Ravenswood"),
        ("79863", "Pretty Little Liars: The Perfectionists"),
        ("110531", "Pretty Little Liars: Original Sin"),
    ], "", ""),
    ("power", "Power Universe", [
        ("54650", "Power"),
        ("97890", "Power Book II: Ghost"),
        ("124394", "Power Book III: Raising Kanan"),
        ("119845", "Power Book IV: Force"),
    ], "", ""),
    ("vikings", "Vikings Universe", [
        ("44217", "Vikings"),
        ("116135", "Vikings: Valhalla"),
    ], "", ""),
    ("suits", "Suits Universe", [
        ("37680", "Suits"),
        ("85950", "Pearson"),
        ("259453", "Suits LA"),
    ], "", ""),
    ("black-ish", "Black-ish Universe", [
        ("61381", "black-ish"),
        ("71885", "grown-ish"),
        ("89563", "mixed-ish"),
    ], "", ""),
    ("good-wife", "The Good Wife Universe", [
        ("1435", "The Good Wife"),
        ("69158", "The Good Fight"),
        ("226285", "Elsbeth"),
    ], "", ""),
    ("x-files", "The X-Files Universe", [
        ("4087", "The X-Files"),
        ("5715", "The Lone Gunmen"),
        ("4330", "Millennium"),
    ], "", ""),
    ("buffyverse", "Buffyverse", [
        ("95", "Buffy the Vampire Slayer"),
        ("2426", "Angel"),
    ], "", ""),
    ("dexter", "Dexter Universe", [
        ("1405", "Dexter"),
        ("219937", "Dexter: Original Sin"),
        ("131927", "Dexter: New Blood"),
        ("259909", "Dexter: Resurrection"),
    ], "", ""),
    ("narcos", "Narcos Universe", [
        ("63351", "Narcos"),
        ("80968", "Narcos: Mexico"),
    ], "", ""),
    ("money-heist", "Money Heist Universe", [
        ("71446", "Money Heist"),
        ("112836", "Money Heist: Korea - Joint Economic Area"),
        ("146176", "Berlin"),
    ], "", ""),
    ("greys-anatomy", "Grey's Anatomy Universe", [
        ("1416", "Grey's Anatomy"),
        ("3172", "Private Practice"),
        ("76773", "Station 19"),
        ("79897", "Grey's Anatomy: B-Team"),
    ], "", ""),
    ("anne-rice", "Anne Rice Immortal Universe", [
        ("128098", "Interview with the Vampire"),
        ("207863", "Mayfair Witches"),
        ("256624", "Talamasca: The Secret Order"),
    ], "", ""),
    ("big-bang", "The Big Bang Theory Universe", [
        ("1418", "The Big Bang Theory"),
        ("71728", "Young Sheldon"),
        ("243875", "Georgie & Mandy's First Marriage"),
    ], "/an3uTx1P0XgHPylgfPV6W7yxKAo.jpg", "/gMqQY6SwuhKg1LvmiTxKX6YrINr.jpg"),
    ("supernatural", "Supernatural Universe", [
        ("1622", "Supernatural"),
        ("32871", "Supernatural: The Anime Series"),
        ("128113", "The Winchesters"),
    ], "/u40gJarLPlIkwouKlzGdobQOV9k.jpg", "/ro0tlgnsco4SwbdAgmscLkSlMSL.jpg"),
    ("archieverse", "Archieverse", [
        ("69050", "Riverdale"),
        ("79242", "Chilling Adventures of Sabrina"),
        ("87539", "Katy Keene"),
    ], "/d8mmn9thQ5dBk2qbv6BCqGUXWK3.jpg", "/kb9XvtEnDhBVVit4eeKygqll4EA.jpg"),
    ("bridgerton", "Bridgerton Universe", [
        ("91239", "Bridgerton"),
        ("196454", "Queen Charlotte: A Bridgerton Story"),
    ], "/uXTg565ahu9RwonCX1V2Hex1NU6.jpg", "/6umsRLI7t0ydFwCl0JNEIO0q2LH.jpg"),
    ("avatar", "Avatar Universe", [
        ("246", "Avatar: The Last Airbender"),
        ("33880", "The Legend of Korra"),
        ("82452", "Avatar the Last Airbender"),
        ("284833", "Avatar: Seven Havens"),
    ], "/9RQhVb3r3mCMqYVhLoCu4EvuipP.jpg", "/kU98MbVVgi72wzceyrEbClZmMFe.jpg"),
    ("sons-of-anarchy", "Sons of Anarchy Universe", [
        ("1409", "Sons of Anarchy"),
        ("76231", "Mayans M.C."),
    ], "/kiy8BHtIHAslh81rvFcZ4wbNGdY.jpg", "/mcgZDwhMlrFsfpbvCeg5RY5mhiu.jpg"),
    ("bosch", "Bosch Universe", [
        ("60585", "Bosch"),
        ("153657", "Bosch: Legacy"),
        ("239826", "Ballard"),
    ], "/vVwyo9fwHp5zhX96CzpuRBFl2SJ.jpg", "/23S5oKZjlXehjNLEhMQuxjwbyuA.jpg"),
    ("orphan-black", "Orphan Black Universe", [
        ("56296", "Orphan Black"),
        ("206916", "Orphan Black: Echoes"),
    ], "/tjFYkWMafg71sihs1aa7IDx17aS.jpg", "/cBmVnbc9KKhsdHCDJU2pibU5Pjs.jpg"),
    ("leverage", "Leverage Universe", [
        ("7482", "Leverage"),
        ("106502", "Leverage: Redemption"),
    ], "/t5KJXooBqJLKUClpvYuSKNrcYGy.jpg", "/giluKEg4kEG9QlM2E2lJ4ZjMXVo.jpg"),
    ("cheers-frasier", "Cheers / Frasier Universe", [
        ("141", "Cheers"),
        ("10337", "The Tortellis"),
        ("2506", "Wings"),
        ("3452", "Frasier"),
        ("195241", "Frasier"),
    ], "/nD1ZQBKbgKSmKcrAkWTofohsScj.jpg", "/5U7NIuRK836GutAlo7TLPfmVtGW.jpg"),
    ("himym", "How I Met Your Mother Universe", [
        ("1100", "How I Met Your Mother"),
        ("124010", "How I Met Your Father"),
    ], "/b34jPzmB0wZy7EjUZoleXOl2RRI.jpg", "/3f8aW6vcYRP6mTZdgXm83BiuB9t.jpg"),
    ("sex-and-city", "Sex and the City Universe", [
        ("105", "Sex and the City"),
        ("46157", "The Carrie Diaries"),
        ("116450", "And Just Like That..."),
    ], "/jfLp8gTfdi9d8onEFJ60kp1Bl1e.jpg", "/jvHw1zF20kYA9gbF2VprXD6uJpq.jpg"),
    ("full-house", "Full House Universe", [
        ("4313", "Full House"),
        ("63623", "Fuller House"),
    ], "/7g0EyKsIaYjYw3gCIBKMHHE0Kcu.jpg", "/btUwsz9ttVBVyqtEyZvFBQFyJgv.jpg"),
    ("boy-meets-world", "Boy Meets World Universe", [
        ("1777", "Boy Meets World"),
        ("46028", "Girl Meets World"),
    ], "/Dk5702N6dlB3Mjr4w4bR6PFPln.jpg", "/7mgf8w8xPyLnIln0kFo6qH2OEGh.jpg"),
    ("roseanne", "Roseanne Universe", [
        ("2706", "Roseanne"),
        ("80550", "The Conners"),
    ], "/4UARHgxTm7xwhcEHiVDwF0Gv4j0.jpg", "/hwCKVqEAoPQK91I3ewx64N1zLhS.jpg"),
    ("spongebob", "SpongeBob Universe", [
        ("387", "SpongeBob SquarePants"),
        ("99588", "Kamp Koral: SpongeBob's Under Years"),
        ("126824", "The Patrick Star Show"),
    ], "/5h0EU2lqBb03dp5vtRuUHJwqzem.jpg", "/aasp5EmwclAQbwfGABWLTNLhjwB.jpg"),
    ("ben-10", "Ben 10 Universe", [
        ("4686", "Ben 10"),
        ("6040", "Ben 10: Alien Force"),
        ("31109", "Ben 10: Ultimate Alien"),
        ("46922", "Ben 10: Omniverse"),
        ("68295", "Ben 10"),
    ], "/7r8QhyqYu2Ini3BlOtjl7jKRiuG.jpg", "/eIRe2cNOhvwPPtGDjFVEXGaMkVg.jpg"),
    ("american-story", "American Story Universe", [
        ("1413", "American Horror Story"),
        ("113036", "American Horror Stories"),
        ("64513", "American Crime Story"),
        ("69851", "FEUD"),
        ("131141", "American Sports Story: Aaron Hernandez"),
    ], "/x2c3AvZeTyNehRZXabTojAxfDuR.jpg", "/a4doyPOabvQor0RGkWdhVENAR3G.jpg"),
    ("hawaii-five-0", "Hawaii Five-0 Universe", [
        ("32798", "Hawaii Five-0"),
        ("67133", "MacGyver"),
        ("79593", "Magnum P.I."),
    ], "/sIdCKlmM2nU4akIvFQaAIiU8YES.jpg", "/tLccUh3uazZ9TkLhe53UwprJhI4.jpg"),
    ("librarians", "The Librarians Universe", [
        ("61599", "The Librarians"),
        ("226749", "The Librarians: The Next Chapter"),
    ], "/jnEzRcKFqaSXLAP87gVKTXawwGg.jpg", "/1EBMUCxPjGQneeyshurFBpqXVL9.jpg"),
    ("l-word", "The L Word Universe", [
        ("3475", "The L Word"),
        ("89630", "The L Word: Generation Q"),
    ], "/nuBhtv4P5nY9loJ6kXb1hsyc9EA.jpg", "/nbZhU0vZI7mBo0BsvpFvD0OPdWi.jpg"),
    ("letterkenny", "Letterkenny Universe", [
        ("65798", "Letterkenny"),
        ("158756", "Shoresy"),
    ], "/zrB0Viy72GYKiLrtSs7SQVz5QWl.jpg", "/wdHK7RZNIGfskbGCIusSKN3vto6.jpg"),
    ("below-deck", "Below Deck Universe", [
        ("50042", "Below Deck"),
        ("66902", "Below Deck Mediterranean"),
        ("97872", "Below Deck Sailing Yacht"),
        ("125506", "Below Deck Down Under"),
        ("132762", "Below Deck Adventure"),
    ], "/xMkYEWMGB7F7YfzJ24DPXoDj8vo.jpg", "/myyTmasSFIhLVIxtgjAE2bch70M.jpg"),
    ("90-day-fiance", "90 Day Fiance Universe", [
        ("61575", "90 Day Fianc\u00e9"),
        ("67757", "90 Day Fianc\u00e9: Happily Ever After?"),
        ("73319", "90 Day Fianc\u00e9: Before the 90 Days"),
        ("90046", "90 Day Fianc\u00e9: The Other Way"),
        ("205154", "90 Day Fianc\u00e9 UK"),
        ("128495", "90 Day Fianc\u00e9: Love in Paradise"),
        ("118422", "90 Day: The Single Life"),
        ("230272", "90 Day: The Last Resort"),
        ("107128", "Darcey & Stacey"),
        ("91169", "The Family Chantel"),
        ("74920", "90 Day Fianc\u00e9: What Now?"),
        ("96613", "90 Day Fianc\u00e9: Just Landed"),
        ("101451", "90 Day Fianc\u00e9: Self-Quarantined"),
        ("114659", "90 Day Diaries"),
        ("94009", "90 Day Fianc\u00e9: Pillow Talk"),
        ("115029", "90 Day Bares All"),
        ("115595", "90 Day Journey"),
    ], "/wJVDf4ZysdxhoREQIHlOM4phRNp.jpg", "/kiD4RDvt9kppAjvBy2LE4k86PDJ.jpg"),
    ("drag-race", "RuPaul's Drag Race Universe", [
        ("8514", "RuPaul's Drag Race"),
        ("38409", "RuPaul's Drag Race: Untucked"),
        ("67482", "RuPaul's Drag Race All Stars"),
        ("67564", "RuPaul's Drag Race All Stars: UNTUCKED"),
        ("92611", "RuPaul's Drag Race UK"),
        ("155431", "RuPaul's Drag Race UK vs The World"),
        ("122692", "Drag Race Down Under"),
        ("232821", "RuPaul's Drag Race Global All Stars"),
    ], "/ySs9xkTfPgQCUNB2ctOzcMWP14n.jpg", "/hEtBwhqAzHKihQ1H9QD2kj8bJ5.jpg"),
    ("battlestar", "Battlestar Galactica Universe", [
        ("501", "Battlestar Galactica"),
        ("1972", "Battlestar Galactica"),
        ("877", "Caprica"),
        ("4621", "Galactica 1980"),
    ], "/27jl4H9PauenZlmVBbOO1pr1lGf.jpg", "/88sdvwvX91VOYqGJUY1XQO84XIb.jpg"),
    ("witcher", "The Witcher Universe", [
        ("71912", "The Witcher"),
        ("106541", "The Witcher: Blood Origin"),
    ], "/AoGsDM02UVt0npBA8OvpDcZbaMi.jpg", "/foGkPxpw9h8zln81j63mix5B7m8.jpg"),
    ("friends", "Friends Universe", [
        ("1668", "Friends"),
        ("1466", "Joey"),
    ], "/2koX1xLkpTQM4IZebYvKysFW1Nh.jpg", "/m3Jev59mJLyUp5bXhY5SVfIBZI0.jpg"),
    ("sabrina", "Sabrina Universe", [
        ("25641", "Sabrina, the Teenage Witch"),
        ("605", "Sabrina, the Teenage Witch"),
        ("733", "Sabrina: The Animated Series"),
        ("46432", "Sabrina: Secrets of a Teenage Witch"),
    ], "/nNhj3coHNVVJPVM7fm5PEYVTCMO.jpg", "/4PhaaA593zHfAyYUIXVWTih3qcD.jpg"),
    ("all-in-family", "All in the Family Universe", [
        ("1922", "All in the Family"),
        ("2184", "Maude"),
        ("1964", "The Jeffersons"),
        ("154", "Good Times"),
        ("4277", "Archie Bunker's Place"),
        ("6572", "Gloria"),
        ("4561", "704 Hauser"),
    ], "/s2Y9QWyuyjRP78DZsatknEjn0iN.jpg", "/qP6w5T2aMTTkIW5qFqziWhgYlPu.jpg"),
    ("happy-days", "Happy Days Universe", [
        ("3845", "Happy Days"),
        ("3033", "Laverne & Shirley"),
        ("2552", "Mork & Mindy"),
        ("527", "Joanie Loves Chachi"),
        ("920", "The Fonz and the Happy Days Gang"),
    ], "/sepIwNPCEhkKvFOQSjXK6tekkjR.jpg", "/lyAx1XlcrPaenfwvSYnOl4h4WMk.jpg"),
    ("power-rangers", "Power Rangers Universe", [
        ("2328", "Power Rangers"),
        ("321123", "Mighty Morphin Alien Rangers"),
        ("128554", "Power Rangers Dino Force Brave"),
        ("210832", "Power Rangers HyperForce"),
    ], "/qx3SJlAp2RK656TusqKx1qEqVMW.jpg", "/i01wnWz0Z3rMATqbkAVLHEaGbNP.jpg"),
    ("taylor-sheridan", "Taylor Sheridan TV Collection", [
        ("73586", "Yellowstone"),
        ("118357", "1883"),
        ("157744", "1923"),
        ("157732", "Lawmen: Bass Reeves"),
        ("97951", "Mayor of Kingstown"),
        ("153312", "Tulsa King"),
        ("113962", "Lioness"),
        ("157741", "Landman"),
    ], "/rqeYMLryjcawh2JeRpCVUDXYM5b.jpg", "/w7zzw7Lt0j9rQjbzbTjm9ZImX6H.jpg"),
]

# Add future TV universes here.
# `_unique_tv_collections()` de-duplicates against `_TV_COLLECTIONS`, so adding
# an already-existing slug/label will not create duplicate menu entries.
#
# Keep this list for real connected universes/spin-off families only.
# Do not add random actor/creator/studio groupings here.
_TV_COLLECTIONS_EXTRA = [
    # Current catalog already includes the major TV universes:
    # Marvel TV, DC TV, Star Wars TV, Star Trek, Doctor Who, Stargate,
    # Walking Dead, Yellowstone, NCIS, Law & Order, CSI, One Chicago,
    # FBI, 9-1-1, The Rookie, Criminal Minds, Grey's Anatomy, Avatar,
    # The Boys, Power, Supernatural, Dexter, Bosch, and more.
]


def _collection_folder_item(item, include_save_ctx=True):
    collection_id = str(item.get("collection_id") or item.get("tmdb_id") or "")
    if not collection_id:
        return None
    label = item.get("title") or "Unknown Collection"
    poster = item.get("poster") or ""
    fanart = item.get("fanart") or ""
    overview = item.get("plot") or ""
    if not overview:
        raw = item.get("raw") or {}
        overview = raw.get("overview") or ""
    parts = item.get("parts") or (item.get("raw") or {}).get("parts") or []
    part_count = len(parts) if parts else 0
    fallback = poster or fanart or c("_local_icon")("collections")
    li = c("_new_listitem")(label)
    art = {
        "icon": fallback,
        "thumb": fallback,
        "poster": poster or fallback,
        "fanart": fanart or poster or c("_addon_fanart")(),
    }
    li.setArt(art)
    info = li.getVideoInfoTag()
    info.setMediaType("set")
    info.setTitle(label)
    plot_parts = []
    if overview:
        plot_parts.append(overview)
    if part_count:
        plot_parts.append("{0} movie{1}".format(part_count, "s" if part_count != 1 else ""))
    if plot_parts:
        info.setPlot("\n\n".join(plot_parts))
    else:
        info.setPlot(label)
    url = c("build_url")({"mode": "xstream_tmdb_collection", "collection_id": collection_id})
    ctx = []
    if include_save_ctx:
        if tmdb.is_collection_saved(collection_id):
            unsave_url = c("build_url")({
                "mode": "xstream_tmdb_unsave_collection",
                "collection_id": collection_id,
                "title": label,
                "poster": poster,
                "fanart": fanart,
            })
            ctx.append(("Remove from Saved Collections", f"RunPlugin({unsave_url})"))
        else:
            save_url = c("build_url")({
                "mode": "xstream_tmdb_save_collection",
                "collection_id": collection_id,
                "title": label,
                "poster": poster,
                "fanart": fanart,
            })
            ctx.append(("Save Collection", f"RunPlugin({save_url})"))
    ctx.extend(c("_folder_favorite_ctx")(label, url, fallback))
    li.addContextMenuItems(ctx)
    return url, li, True


def _render_collection_folder_page(page_data, params):
    items = []
    for item in page_data.get("results", []) or []:
        folder_item = _collection_folder_item(item)
        if folder_item:
            items.append(folder_item)
    page = int(page_data.get("page") or _int_param(params, "page"))
    total_pages = int(page_data.get("total_pages") or 1)
    next_item = _next_page_item(params, page, total_pages)
    if next_item:
        items.append(next_item)
    if not items:
        li = c("_new_listitem")(_label("No collections found"))
        items.append(("", li, False))
    _add_items(items, "sets")


def collections_menu():
    if not _guard():
        return
    items = [
        _folder_item(_label("Trending Collections"), {"mode": "xstream_tmdb_collection_list", "list_name": "trending_week"}, "trending"),
        _folder_item(_label("Popular Collections"), {"mode": "xstream_tmdb_collection_list", "list_name": "popular"}, "popular"),
        _folder_item(_label("Top Rated Collections"), {"mode": "xstream_tmdb_collection_list", "list_name": "top_rated"}, "top_rated"),
        _folder_item(_label("Box Office Collections"), {"mode": "xstream_tmdb_collection_list", "list_name": "revenue"}, "top_10_box_office"),
        _folder_item(_label("Most Voted Collections"), {"mode": "xstream_tmdb_collection_list", "list_name": "most_voted"}, "most_voted"),
        _folder_item(31430, {"mode": "xstream_tmdb_collection_browse", "page": "1"}, "collections"),
        _folder_item(_label("Saved Collections"), {"mode": "xstream_tmdb_saved_collections"}, "favorites"),
        _folder_item(c("_t")(31375), {"mode": "xstream_tmdb_collection_search", "prompt": "true"}, "search"),
    ]
    _add_items(items)


def collection_list_route(params):
    if not _guard():
        return
    try:
        list_name = _param(params, "list_name", "popular")
        page = _int_param(params, "page")

        _bg = xbmcgui.DialogProgressBG()
        _bg.create("Xstream Pro", "Loading {0} collections...".format(list_name.replace("_", " ").title()))

        data = tmdb.collections_from_movie_list(
            list_name,
            page=page,
            per_page=PROVIDER_PAGE_SIZE,
            max_scan_pages=15,
        )

        _bg.update(90, "Xstream Pro", "Rendering collections...")
        _render_collection_folder_page(data, params)
        _bg.close()
    except Exception as exc:
        try:
            _bg.close()
        except Exception:
            pass
        _handle_error(exc)


def collection_browse_route(params):
    if not _guard():
        return

    page = max(1, _int_param(params, "page") or 1)
    per_page = PROVIDER_PAGE_SIZE

    sorted_collections = sorted(_unique_movie_collections(), key=lambda x: x[0].lower())

    total = len(sorted_collections)
    total_pages = max(1, (total + per_page - 1) // per_page)

    page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page

    page_items = sorted_collections[start:end]
    items = []

    _bg = xbmcgui.DialogProgressBG()
    _bg.create("Xstream Pro", "Loading collections...")
    for idx, (name, cid) in enumerate(page_items):
        pct = int((idx + 1) / len(page_items) * 100) if page_items else 100
        _bg.update(pct, "Xstream Pro", "Loading {0}...".format(name))
        summary = tmdb.collection_summary({"id": cid, "name": name})
        if summary:
            folder = _collection_folder_item(summary, include_save_ctx=False)
        else:
            folder = _collection_folder_item({"collection_id": cid, "title": name}, include_save_ctx=False)
        if folder:
            items.append(folder)
    _bg.close()

    next_item = _next_page_item(params, page, total_pages)
    if next_item:
        items.append(next_item)

    if not items:
        li = c("_new_listitem")(_label("No collections found"))
        li.setArt(c("_menu_art")(c("_local_icon")("collections"), c("_addon_fanart")()))
        items.append(("", li, False))

    _add_items(items, "sets")


def _tv_universe_sort_label(item):
    label = item[1] or ""
    lowered = label.lower()
    if lowered.startswith("the "):
        return lowered[4:]
    return lowered


def tv_universes_menu(params=None):
    if not _guard():
        return

    params = params or {}
    page = max(1, _int_param(params, "page") or 1)
    per_page = PROVIDER_PAGE_SIZE

    icon = c("_local_icon")("collections")
    fanart = c("_addon_fanart")()

    universes = sorted(_unique_tv_collections(), key=_tv_universe_sort_label)

    total = len(universes)
    total_pages = max(1, (total + per_page - 1) // per_page)

    page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page

    items = []

    for slug, label, refs, poster_path, backdrop_path in universes[start:end]:
        universe_poster = tmdb.image_url(poster_path) if poster_path else icon
        universe_fanart = tmdb.fanart_url(backdrop_path) if backdrop_path else fanart
        li = c("_new_listitem")(label)
        li.setArt({
            "icon": universe_poster,
            "thumb": universe_poster,
            "poster": universe_poster,
            "fanart": universe_fanart,
        })
        info = li.getVideoInfoTag()
        info.setMediaType("set")
        info.setTitle(label)
        show_count = len(refs) if refs else 0
        if show_count:
            info.setPlot("{0} show{1}".format(show_count, "s" if show_count != 1 else ""))

        url = c("build_url")({
            "mode": "xstream_tmdb_tv_collection",
            "slug": slug,
        })

        li.addContextMenuItems(c("_folder_favorite_ctx")(label, url, icon))
        items.append((url, li))

    next_item = _next_page_item(
        {"mode": "xstream_tmdb_tv_universes_menu", "page": str(page)},
        page,
        total_pages,
    )
    if next_item:
        items.append(next_item)

    if not items:
        li = c("_new_listitem")(_label("TV collection not found"))
        li.setArt(c("_menu_art")(icon, fanart))
        items.append(("", li, False))

    _add_items(items)


def tv_collections_menu():
    if not _guard():
        return
    items = [
        _folder_item(_label("Universes"), {"mode": "xstream_tmdb_tv_universes_menu", "page": "1"}, "providers"),
        _folder_item(_label("Saved Collections"), {"mode": "xstream_tmdb_saved_collections"}, "favorites"),
        _folder_item(c("_t")(31375), {"mode": "xstream_tmdb_search", "tmdb_type": "tv", "prompt": "true"}, "search"),
    ]
    _add_items(items)


def tv_collection_route(params):
    if not _guard():
        return
    try:
        slug = _param(params, "slug", "")
        selected = None

        for item in _unique_tv_collections():
            if item[0] == slug:
                selected = item
                break

        if not selected:
            _end_empty("TV collection not found")
            return

        data = tmdb.tv_collection(selected[2])
        data = _page_results_data(data.get("results", []) or [], params, PROVIDER_PAGE_SIZE)

        route_params = _query(params)
        route_params["mode"] = "xstream_tmdb_tv_collection"
        route_params["slug"] = slug

        _render_media_page(data, route_params, "tv", "tvshows", filter_provider=False)

    except Exception as exc:
        _handle_error(exc)


def collection_search_route(params):
    if not _guard():
        return
    try:
        query, should_return = _handle_search_prompt(params, "collection", "Search Collections")
        if should_return:
            return
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        page = _int_param(params, "page")
        route_params = _query(params)
        route_params["query"] = query
        route_params["prompt"] = "false"
        data = tmdb.search_collections(query, page=page)
        items = []
        for item in data.get("results", []):
            folder_item = _collection_folder_item(item)
            if folder_item:
                items.append(folder_item)
        next_item = _next_page_item(route_params, int(data.get("page") or page), int(data.get("total_pages") or 1))
        if next_item:
            items.append(next_item)
        _add_items(items, "sets")
    except Exception as exc:
        _handle_error(exc)


def saved_collections_menu():
    if not _guard():
        return
    saved = tmdb.get_saved_collections()
    items = []
    _bg = xbmcgui.DialogProgressBG()
    _bg.create("Xstream Pro", "Loading saved collections...")
    for idx, item in enumerate(saved):
        cid = str(item.get("collection_id") or "")
        if not cid:
            continue
        pct = int((idx + 1) / len(saved) * 100) if saved else 100
        _bg.update(pct, "Xstream Pro", "Loading {0}...".format(item.get("title") or "Collection"))
        summary = tmdb.collection_summary({"id": cid, "name": item.get("title") or "Unknown Collection",
                                            "poster_path": item.get("poster", ""),
                                            "backdrop_path": item.get("fanart", ""),
                                            "overview": item.get("plot", "")}) or item
        folder = _collection_folder_item(summary)
        if folder:
            items.append(folder)
    _bg.close()
    if not items:
        li = c("_new_listitem")(_label("No saved collections"))
        items.append(("", li, False))
    _add_items(items, "sets")


def save_collection_action(params):
    cid = _param(params, "collection_id", "")
    title = _param(params, "title", "")
    poster = _param(params, "poster", "")
    fanart = _param(params, "fanart", "")
    if not cid:
        return
    tmdb.save_collection(cid, title, poster, fanart)
    xbmcgui.Dialog().notification("Xstream Pro", _t(31197), time=3000)
    xbmc.executebuiltin("Container.Refresh")


def unsave_collection_action(params):
    cid = _param(params, "collection_id", "")
    if not cid:
        return
    tmdb.unsave_collection(cid)
    xbmc.executebuiltin("Container.Refresh")


def company_search_route(params):
    if not _guard():
        return
    try:
        query, should_return = _handle_search_prompt(params, "company", "Search Companies")
        if should_return:
            return
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        page = _int_param(params, "page")
        route_params = _query(params)
        route_params["query"] = query
        route_params["prompt"] = "false"
        data = tmdb.search_companies(query, page=page)
        items = []
        for company in data.get("results", []):
            company_id = str(company.get("id") or "")
            label = company.get("name") or "Unknown Company"
            if not company_id:
                continue
            logo = tmdb.image_url(company.get("logo_path")) or ""
            fallback_icon = c("_local_icon")("themoviedb")
            fanart = c("_addon_fanart")()
            art = {"icon": logo or fallback_icon, "thumb": logo or fallback_icon, "poster": logo or fallback_icon, "fanart": fanart}
            for suffix, tmdb_type in ((" - Movies", "movie"), (" - TV", "tv")):
                full_label = label + suffix
                li = c("_new_listitem")(full_label)
                li.setArt(art)
                info = li.getVideoInfoTag()
                info.setMediaType("folder")
                info.setTitle(full_label)
                info.setPlot("{0} {1}".format(tmdb_type.capitalize() + "s from", label))
                url = c("build_url")({"mode": "xstream_tmdb_discover", "tmdb_type": tmdb_type, "with_companies": company_id, "sort_by": "popularity.desc"})
                li.addContextMenuItems(c("_folder_favorite_ctx")(label + suffix, url, logo or fallback_icon))
                items.append((url, li))
        next_item = _next_page_item(route_params, int(data.get("page") or page), int(data.get("total_pages") or 1))
        if next_item:
            items.append(next_item)
        _add_items(items)
    except Exception as exc:
        _handle_error(exc)


def keyword_search_route(params):
    if not _guard():
        return
    try:
        query, should_return = _handle_search_prompt(params, "keyword", "Search Keywords")
        if should_return:
            return
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        page = _int_param(params, "page")
        route_params = _query(params)
        route_params["query"] = query
        route_params["prompt"] = "false"
        data = tmdb.search_keywords(query, page=page)
        items = []
        for keyword in data.get("results", []):
            keyword_id = str(keyword.get("id") or "")
            label = keyword.get("name") or "Unknown Keyword"
            if not keyword_id:
                continue
            items.append(_folder_item(label + " - Movies", {"mode": "xstream_tmdb_discover", "tmdb_type": "movie", "with_keywords": keyword_id, "sort_by": "popularity.desc"}, "themoviedb"))
            items.append(_folder_item(label + " - TV", {"mode": "xstream_tmdb_discover", "tmdb_type": "tv", "with_keywords": keyword_id, "sort_by": "popularity.desc"}, "themoviedb"))
        next_item = _next_page_item(route_params, int(data.get("page") or page), int(data.get("total_pages") or 1))
        if next_item:
            items.append(next_item)
        _add_items(items)
    except Exception as exc:
        _handle_error(exc)


def _discover_params(params, tmdb_type):
    out = {"sort_by": _param(params, "sort_by", "popularity.desc") or "popularity.desc"}
    # Year filters
    year = _param(params, "year", "")
    if year:
        out["first_air_date_year" if tmdb_type == "tv" else "primary_release_year"] = year
    first_air_year = _param(params, "first_air_date_year", "")
    if first_air_year:
        out["first_air_date_year"] = first_air_year
    primary_release_year = _param(params, "primary_release_year", "")
    if primary_release_year:
        out["primary_release_year"] = primary_release_year
    # Date range filters
    date_gte = _param(params, "date_gte", "")
    date_lte = _param(params, "date_lte", "")
    if date_gte:
        out["first_air_date.gte" if tmdb_type == "tv" else "primary_release_date.gte"] = date_gte
    if date_lte:
        out["first_air_date.lte" if tmdb_type == "tv" else "primary_release_date.lte"] = date_lte
    # Direct date filters from rules
    for key in ("primary_release_date.gte", "primary_release_date.lte",
                "release_date.gte", "release_date.lte",
                "first_air_date.gte", "first_air_date.lte", "air_date.gte", "air_date.lte"):
        val = _param(params, key, "")
        if val:
            out[key] = val
    # Standard mapping
    mapping = {
        "with_genres": "with_genres",
        "without_genres": "without_genres",
        "with_cast": "with_cast",
        "with_crew": "with_crew",
        "with_people": "with_people",
        "with_companies": "with_companies",
        "with_keywords": "with_keywords",
        "without_keywords": "without_keywords",
        "with_networks": "with_networks",
        "with_original_language": "with_original_language",
        "with_release_type": "with_release_type",
        "vote_count.gte": "vote_count.gte",
        "vote_count_gte": "vote_count.gte",
        "vote_count.lte": "vote_count.lte",
        "vote_average.gte": "vote_average.gte",
        "vote_average.lte": "vote_average.lte",
        "with_runtime.gte": "with_runtime.gte",
        "with_runtime.lte": "with_runtime.lte",
        "certification": "certification",
        "certification.gte": "certification.gte",
        "certification.lte": "certification.lte",
        "region": "region",
        "with_watch_providers": "with_watch_providers",
        "watch_region": "watch_region",
        "certification_country": "certification_country",
    }
    for key, tmdb_key in mapping.items():
        value = _param(params, key, "")
        if value:
            out[tmdb_key] = value
    if out.get("with_watch_providers") and not out.get("watch_region"):
        out["watch_region"] = tmdb.region()
    genre_id = _param(params, "genre_id", "")
    if genre_id and not out.get("with_genres"):
        out["with_genres"] = genre_id
    c("_log")("Discover params for {0}: {1}".format(tmdb_type, out))
    return out


def discover_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        page = _int_param(params, "page")
        if page == 1:
            _warn_high_vote_threshold(params)
        discover_params = _discover_params(params, tmdb_type)
        filter_provider = _param(params, "filter_provider", "true").lower() != "false"

        def _fetch_discover_page(src_page):
            return tmdb.discover(tmdb_type, discover_params, page=src_page)

        data = _fetch_merged_page(
            _fetch_discover_page,
            page,
            filter_provider=filter_provider,
            fetch_key=("tmdb_discover", tmdb_type, sorted(discover_params.items())),
            filter_watched=True,
        )
        _render_media_page(data, params, tmdb_type, "tvshows" if tmdb_type == "tv" else "movies", filter_provider=False)
    except Exception as exc:
        _handle_error(exc)


def genres_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        items = []
        for genre in tmdb.genres(tmdb_type):
            label = genre.get("name") or "Unknown"
            items.append(_folder_item(label, {"mode": "xstream_tmdb_discover", "tmdb_type": tmdb_type, "genre_id": str(genre.get("id") or ""), "sort_by": "popularity.desc"}, "genres"))
        _add_items(items)
    except Exception as exc:
        _handle_error(exc)


def _provider_folder_cache_key(tmdb_type, provider_id):
    return "{0}:{1}:{2}".format(tmdb_type, provider_id, tmdb.region())


def _provider_folder_has_available_results(tmdb_type, provider_id, max_pages=3):
    cache_key = _provider_folder_cache_key(tmdb_type, provider_id)
    cached = cache.get("tmdb_provider_folder", cache_key)
    if cached is not None:
        return bool(cached.get("ok"))
    ok = False
    params = {
        "with_watch_providers": str(provider_id),
        "watch_region": tmdb.region(),
        "sort_by": "popularity.desc",
    }
    for page in range(1, max_pages + 1):
        try:
            data = tmdb.discover(tmdb_type, params, page=page)
            if _filter_provider_available_results(data.get("results", []) or []):
                ok = True
                break
            if page >= int(data.get("total_pages") or 1):
                break
        except Exception:
            break
    cache.set("tmdb_provider_folder", cache_key, {"ok": ok}, 604800 if ok else 86400)
    return ok


def watch_providers_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        all_providers = tmdb.watch_providers(tmdb_type) or []
        page = max(1, _int_param(params, "page"))
        per_page = 100
        start = (page - 1) * per_page
        end = start + per_page
        providers = all_providers[start:end]
        items = []
        fanart = c("_addon_fanart")()
        for provider in providers:
            provider_id = str(provider.get("provider_id") or "")
            label = provider.get("provider_name") or "Unknown"
            logo = tmdb.image_url(provider.get("logo_path"))
            if not provider_id:
                continue
            if _provider_only_enabled() and not _provider_folder_has_available_results(tmdb_type, provider_id):
                continue
            li = c("_new_listitem")(label)
            art = {
                "icon": logo or c("_local_icon")("providers"),
                "thumb": logo or c("_local_icon")("providers"),
                "poster": logo or c("_local_icon")("providers"),
            }
            if fanart:
                art["fanart"] = fanart
            li.setArt(art)
            info = li.getVideoInfoTag()
            info.setMediaType("folder")
            info.setTitle(label)
            info.setPlot("Browse {0} available on {1}".format(tmdb_type.capitalize() + "s", label))
            url = c("build_url")({
                "mode": "xstream_tmdb_discover",
                "tmdb_type": tmdb_type,
                "with_watch_providers": provider_id,
                "watch_region": tmdb.region(),
                "sort_by": "popularity.desc",
            })
            li.addContextMenuItems(c("_folder_favorite_ctx")(label, url, logo or c("_local_icon")("providers")))
            items.append((url, li))
        total_pages = (len(all_providers) + per_page - 1) // per_page
        if total_pages < 1:
            total_pages = 1
        next_item = _next_page_item(params, page, total_pages)
        if next_item:
            items.append(next_item)
        _add_items(items)
    except Exception as exc:
        _handle_error(exc)


def _filter_provider_seasons(tmdb_id, showtitle, seasons):
    try:
        fn = _CTX.get("_filter_provider_seasons")
        if fn:
            return fn(tmdb_id, showtitle, seasons)
    except Exception as exc:
        c("_log")("Provider-only seasons filter failed: {0}".format(exc))
    return seasons


def seasons_route(params):
    if not _guard():
        return
    try:
        tmdb_id = _param(params, "tmdb_id", "")
        showtitle = _param(params, "title", "")
        seasons = tmdb.seasons(tmdb_id)
        seasons = _filter_provider_available_results(seasons)
        seasons = _filter_provider_seasons(tmdb_id, showtitle, seasons)
        seasons = _filter_season_visibility(seasons)
        wm, we = _watchers()
        if not seasons:
            li = c("_new_listitem")(_t(31229))
            items = [("", li, False)]
        else:
            mark_unavailable = _mark_unavailable_enabled(params)
            items = [_media_item(item, wm, we, mark_unavailable=mark_unavailable) for item in seasons]
            if we and tmdb_id:
                for i, item in enumerate(seasons):
                    try:
                        sn = int(item.get("season", 0))
                    except (ValueError, TypeError):
                        continue
                    watched_count = we.get_watched_count(tmdb_id, sn)
                    ep_count = item.get("episode_count", 0)
                    if ep_count or watched_count:
                        url, li, is_folder = items[i]
                        orig_label = li.getLabel()
                        li.setLabel("{0} - {1}/{2}".format(orig_label, ep_count, watched_count))
        _add_items(items, "seasons")
    except Exception as exc:
        _handle_error(exc)


def _filter_provider_episodes(tmdb_id, showtitle, season, episodes):
    try:
        fn = _CTX.get("_filter_provider_episodes")
        if fn:
            return fn(tmdb_id, showtitle, season, episodes)
    except Exception as exc:
        c("_log")("Provider-only episodes filter failed: {0}".format(exc))
    return episodes


def _filter_episode_visibility(episodes):
    """Hide unaired episodes and/or specials based on user settings."""
    addon = _CTX.get("addon")
    if not addon:
        return episodes
    hide_unaired = addon.getSetting("tmdb_hide_unaired_episodes") == "true"
    hide_specials = addon.getSetting("tmdb_hide_specials") == "true"
    if not hide_unaired and not hide_specials:
        return episodes

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out = []
    for ep in episodes:
        if hide_specials and ep.get("season") == "0":
            continue
        if hide_unaired:
            premiered = ep.get("premiered", "")
            if premiered and premiered > today:
                continue
        out.append(ep)
    c("_log")("Episode visibility filter: {0} -> {1} (hide_unaired={2}, hide_specials={3})".format(
        len(episodes), len(out), hide_unaired, hide_specials))
    return out


def _filter_season_visibility(seasons):
    """Hide specials season (season 0) based on user settings."""
    addon = _CTX.get("addon")
    if not addon or addon.getSetting("tmdb_hide_specials") != "true":
        return seasons
    out = [s for s in seasons if s.get("season") != "0"]
    c("_log")("Season visibility filter: {0} -> {1}".format(len(seasons), len(out)))
    return out


def episodes_route(params):
    if not _guard():
        return
    try:
        tmdb_id = _param(params, "tmdb_id", "")
        showtitle = _param(params, "title", "")
        season = _param(params, "season", "1")
        episodes = tmdb.episodes(tmdb_id, season)
        episodes = _filter_provider_available_results(episodes)
        episodes = _filter_provider_episodes(tmdb_id, showtitle, season, episodes)
        episodes = _filter_episode_visibility(episodes)
        wm, we = _watchers()
        if not episodes:
            li = c("_new_listitem")(_t(31229))
            items = [("", li, False)]
        else:
            mark_unavailable = _mark_unavailable_enabled(params)
            items = [_media_item(item, wm, we, mark_unavailable=mark_unavailable) for item in episodes]
        _add_items(items, "episodes")
    except Exception as exc:
        _handle_error(exc)


def related_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        tmdb_id = _param(params, "tmdb_id", "")
        relation = "recommendations" if _param(params, "mode", "") == "xstream_tmdb_recommendations" or _param(params, "relation", "") == "recommendations" else "similar"
        page = _int_param(params, "page")

        def _fetch_related_page(src_page):
            return tmdb.related(tmdb_type, tmdb_id, relation, page=src_page)

        filter_provider = _param(params, "filter_provider", "true").lower() != "false"

        data = _fetch_merged_page(
            _fetch_related_page,
            page,
            filter_provider=filter_provider,
            fetch_key=("tmdb_related", tmdb_type, tmdb_id, relation),
            filter_watched=True,
        )
        _render_media_page(
            data,
            params,
            tmdb_type,
            "tvshows" if tmdb_type == "tv" else "movies",
            filter_provider=False,
        )
    except Exception as exc:
        _handle_error(exc)


def because_watched_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        page = max(1, _int_param(params, "page") or 1)
        per_page = PROVIDER_PAGE_SIZE

        pnum = 1
        active = getattr(c("pm"), "active", "1")
        if str(active).isdigit():
            pnum = int(active)

        stype = "series" if tmdb_type == "tv" else "movie"
        history = c("WatchHistory")(c("addon"), profile_num=pnum).get_all(stype)
        watched = []
        seen_tmdb_ids = set()
        for item in history:
            tmdb_id = str(item.get("tmdb_id") or "").strip()
            if not tmdb_id or tmdb_id in seen_tmdb_ids:
                continue
            seen_tmdb_ids.add(tmdb_id)
            watched.append(item)

        total = len(watched)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)

        start = (page - 1) * per_page
        end = start + per_page
        page_entries = watched[start:end]

        items = []

        meta_pairs = []
        for entry in page_entries:
            tid = str(entry.get("tmdb_id") or "")
            if tid:
                meta_pairs.append((tmdb_type, tid))
        meta_cache = tmdb.meta_cache_get_many(meta_pairs) if meta_pairs else {}

        for entry in page_entries:
            tmdb_id = str(entry.get("tmdb_id") or "")
            if not tmdb_id:
                continue

            if tmdb_type == "tv":
                label = (
                    entry.get("title")
                    or entry.get("showname")
                    or entry.get("tvshowtitle")
                    or entry.get("name")
                    or "Unknown"
                )
            else:
                label = entry.get("title") or entry.get("name") or "Unknown"

            year = str(entry.get("year") or "").strip()
            meta = meta_cache.get((tmdb.normalize_media_type(tmdb_type), tmdb_id))
            if not meta:
                try:
                    meta = tmdb.meta_summary_cached(tmdb_type, tmdb_id)
                except Exception:
                    meta = None
            if meta:
                if not year:
                    year = str(meta.get("year") or "").strip()
            if year:
                label = "{0} ({1})".format(label, year)

            entry_icon = entry.get("icon") or c("_local_icon")("because_you_watched")
            poster = (meta or {}).get("poster") or entry_icon
            fanart = (meta or {}).get("fanart") or c("_addon_fanart")()

            url = c("build_url")({
                "mode": "xstream_tmdb_recommendations",
                "tmdb_type": tmdb_type,
                "tmdb_id": tmdb_id,
                "relation": "recommendations",
            })

            li = c("_new_listitem")(label)
            li.setArt({
                "icon": poster,
                "thumb": poster,
                "poster": poster,
                "fanart": fanart,
            })
            li.setProperty("IsPlayable", "false")

            c("_set_tmdb_item_info")(
                li, label, poster,
                {"poster": poster, "fanart": fanart},
                tmdb_type, year,
                (meta or {}).get("plot", ""),
                "", "",
                0,
                (meta or {}).get("runtime", ""),
                (meta or {}).get("cast"),
                (meta or {}).get("genre"),
                (meta or {}).get("director"),
                (meta or {}).get("writer"),
                (meta or {}).get("studio"),
                (meta or {}).get("mpaa", ""),
                (meta or {}).get("tagline", ""),
                (meta or {}).get("rating", ""),
                (meta or {}).get("votes", ""),
                (meta or {}).get("premiered", ""),
                fanart,
            )

            li.addContextMenuItems(c("_folder_favorite_ctx")(label, url, poster))
            items.append((url, li, True))

        if not items:
            li = c("_new_listitem")(c("_t")(31124))
            li.setArt(c("_menu_art")(c("_local_icon")("because_you_watched"), c("_addon_fanart")()))
            items.append(("", li, False))

        next_item = _next_page_item(params, page, total_pages)
        if next_item:
            items.append(next_item)

        _add_items(items, "tvshows" if tmdb_type == "tv" else "movies")

    except Exception as exc:
        _handle_error(exc)


def trailer_route(params):
    if not _guard():
        return
    try:
        tmdb_type = "tv" if _param(params, "tmdb_type", "movie") == "tv" else "movie"
        tmdb_id = _param(params, "tmdb_id", "")
        videos = tmdb.videos(tmdb_type, tmdb_id)
        candidates = []
        for video in videos:
            if str(video.get("site") or "").lower() != "youtube":
                continue
            key = video.get("key") or ""
            if not key:
                continue
            video_type = str(video.get("type") or "").lower()
            official = bool(video.get("official"))
            score = 0
            if video_type == "trailer":
                score += 4
            elif video_type == "teaser":
                score += 2
            if official:
                score += 1
            candidates.append((score, key))
        if not candidates:
            xbmcgui.Dialog().notification("Xstream Pro", _label("No trailer found"))
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        candidates.sort(reverse=True)
        xbmc.executebuiltin("PlayMedia(plugin://plugin.video.youtube/play/?video_id={0})".format(candidates[0][1]))
        xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
    except Exception as exc:
        _handle_error(exc)


def collection_route(params):
    if not _guard():
        return
    try:
        collection_id = _param(params, "collection_id", "") or _param(params, "tmdb_id", "")
        if not collection_id:
            _end_empty("No collection found")
            return

        data = tmdb.collection(collection_id)
        data = _page_results_data(data.get("results", []) or [], params, PROVIDER_PAGE_SIZE)

        route_params = _query(params)
        route_params["mode"] = "xstream_tmdb_collection"
        route_params["collection_id"] = collection_id

        _render_media_page(data, route_params, "movie", "movies", filter_provider=False)

    except Exception as exc:
        _handle_error(exc)


def collection_from_movie_route(params):
    if not _guard():
        return
    try:
        tmdb_id = _param(params, "tmdb_id", "")
        if not tmdb_id:
            _end_empty("No TMDB movie selected")
            return

        payload = tmdb.details("movie", tmdb_id)
        collection = payload.get("belongs_to_collection") or {}
        collection_id = str(collection.get("id") or "")

        if not collection_id:
            _end_empty("No collection found")
            return

        data = tmdb.collection(collection_id)
        data = _page_results_data(data.get("results", []) or [], params, PROVIDER_PAGE_SIZE)

        # Next should continue through the normal collection route.
        route_params = {
            "mode": "xstream_tmdb_collection",
            "collection_id": collection_id,
            "page": str(_int_param(params, "page")),
        }

        _render_media_page(data, route_params, "movie", "movies", filter_provider=False)

    except Exception as exc:
        _handle_error(exc)


def _person_item(person):
    label = person.get("name") or "Unknown"
    icon = tmdb.image_url(person.get("profile_path")) or c("_local_icon")("people")
    fanart = c("_addon_fanart")()
    li = c("_new_listitem")(label)
    li.setArt({
        "icon": icon,
        "thumb": icon,
        "poster": icon,
        "fanart": fanart,
    })
    info = li.getVideoInfoTag()
    info.setMediaType("person")
    info.setTitle(label)
    plot_parts = []
    raw = person.get("raw") or {}
    department = raw.get("known_for_department") or ""
    if department:
        plot_parts.append("Known for: {0}".format(department))
    known_for = person.get("known_for") or []
    if known_for:
        titles = []
        for kf in known_for[:5]:
            kf_title = kf.get("title") or kf.get("name") or ""
            if kf_title:
                titles.append(kf_title)
        if titles:
            plot_parts.append("Credits: {0}".format(", ".join(titles)))
    bio = raw.get("biography") or ""
    if bio:
        len_limit = 300
        if len(bio) > len_limit:
            bio = bio[:bio.rfind(" ", 0, len_limit)] + "..."
        plot_parts.append(bio)
    if plot_parts:
        info.setPlot("\n\n".join(plot_parts))
    url = c("build_url")({
        "mode": "xstream_tmdb_person_credits",
        "person_id": str(person.get("id") or ""),
        "title": label,
    })
    li.addContextMenuItems(c("_folder_favorite_ctx")(label, url, icon))
    return url, li, True


def people_route(params):
    if not _guard():
        return
    try:
        if _param(params, "person_id", ""):
            person_credits_route(params)
            return
        action = _param(params, "action", "popular")
        page = _int_param(params, "page")
        if action == "search":
            query, should_return = _handle_search_prompt(params, "people", "Search People")
            if should_return:
                return
            if not query:
                xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
                return
            data = tmdb.people_search(query, page=page)
            route_params = _query(params)
            route_params["query"] = query
            route_params["prompt"] = "false"
        elif action == "trending_day":
            data = tmdb.people_trending("day", page=page)
            route_params = params
        elif action == "trending_week":
            data = tmdb.people_trending("week", page=page)
            route_params = params
        else:
            data = tmdb.people_popular(page=page)
            route_params = params
        items = [_person_item(person) for person in data.get("results", []) if person.get("id") and person.get("name")]
        if not items:
            li = c("_new_listitem")(_label("No people found"))
            li.setArt(c("_menu_art")(c("_local_icon")("people"), c("_addon_fanart")()))
            items.append(("", li, False))
        next_item = _next_page_item(route_params, int(data.get("page") or page), int(data.get("total_pages") or 1))
        if next_item:
            items.append(next_item)
        _add_items(items)
    except Exception as exc:
        _handle_error(exc)


def person_credits_route(params):
    if not _guard():
        return
    try:
        person_id = _param(params, "person_id", "")
        title = _param(params, "title", "Person")
        credit_type = _param(params, "credit_type", "")
        if not credit_type:
            items = [
                _folder_item(_label("Movie Credits"), {"mode": "xstream_tmdb_person_credits", "person_id": person_id, "title": title, "credit_type": "movie"}, "movies"),
                _folder_item(_label("TV Credits"), {"mode": "xstream_tmdb_person_credits", "person_id": person_id, "title": title, "credit_type": "tv"}, "tv_shows"),
            ]
            _add_items(items)
            return
        if credit_type == "tv":
            payload = tmdb.person_tv_credits(person_id)
            media = "tv"
            content = "tvshows"
        else:
            payload = tmdb.person_movie_credits(person_id)
            media = "movie"
            content = "movies"
        seen = set()
        results = []
        for item in (payload.get("cast", []) or []) + (payload.get("crew", []) or []):
            item_id = item.get("id")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            results.append(tmdb.normalize_item(item, media))
        results.sort(key=lambda x: float((x.get("raw") or {}).get("popularity") or 0), reverse=True)
        _render_media_page({"page": 1, "total_pages": 1, "results": results}, params, media, content)
    except Exception as exc:
        _handle_error(exc)


def _today():
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _date_days_ago(days):
    return (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
