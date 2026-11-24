"""Live menu entry routes for Xstream Pro."""

_OWNED = {'recently_added_menu', 'movies_menu', 'series_menu'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value



def _current_tmdb_routes():
    """Fetch the current TMDB routes module from addon.py after lazy setup."""
    getter = globals().get("_get_tmdb_routes_module")
    if callable(getter):
        return getter()
    return globals().get("_tmdb_routes")


def _browse_categories(stype, profile_num=None):
    browse = globals().get("_live_browse")
    if browse:
        browse.xtream_categories(stype, profile_num)
        return True
    getter = globals().get("get_live_browse_module")
    if getter:
        getter().xtream_categories(stype, profile_num)
        return True
    elif "xtream_categories" in globals():
        globals()["xtream_categories"](stype, profile_num)
        return True
    return False


def _history_class(name):
    getter = globals().get("_get_history_classes")
    if callable(getter):
        return getter()[name]
    return globals()[name]


def recently_added_menu(stype, profile_num=None):
    stype = "series" if stype in ("series", "tv") else "movie"
    media_type = "tv" if stype == "series" else "movie"
    content_type = "tvshows" if stype == "series" else "movies"
    profiles = _enabled_profiles_with_credentials()
    if not profiles:
        label = "No provider movies" if stype == "movie" else "No provider TV shows"
        li = _new_listitem(label)
        xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)], 1)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return
    all_streams = []
    seen_names = set()
    for pnum, pname in profiles:
        creds = _get_credentials_for_profile(pnum)
        url = creds.get("xtream_url", "")
        user = creds.get("xtream_username", "")
        pwd = creds.get("xtream_password", "")
        if not url:
            continue
        streams = _get_cached_xtream_streams(url, user, pwd, stype, None)
        try:
            streams.sort(key=_provider_added_sort_key, reverse=True)
        except Exception:
            pass
        for s in streams:
            name = s.get("name", "")
            key = _provider_title_key(name)
            if key in seen_names:
                continue
            seen_names.add(key)
            s["_profile_num"] = pnum
            all_streams.append(s)
    try:
        all_streams.sort(key=_provider_added_sort_key, reverse=True)
    except Exception:
        pass
    all_streams = all_streams[:100]
    if not all_streams:
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return
    provider_meta_map = {}
    if stype in ("movie", "series"):
        provider_meta_map = _provider_tmdb_meta_map(all_streams, stype)
        _queue_provider_tmdb_meta_prefetch(all_streams, stype)
    all_wm = []
    for pnum, pname in profiles:
        try:
            all_wm.append(_history_class("WatchedMovies")(addon, profile_num=pnum))
        except Exception:
            pass
    if not _setup_tmdb_routes():
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    tmdb_routes_module = _current_tmdb_routes()
    if tmdb_routes_module is None:
        try:
            _log("Recently Added: TMDB routes module unavailable after setup")
        except Exception:
            pass
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    xbmcplugin.setContent(addon_handle, content_type)
    items = []
    for s in all_streams:
        s_pnum = s.pop("_profile_num", profiles[0][0])
        if stype == "movie":
            info = _merge_provider_tmdb_meta(
                {},
                provider_meta_map.get(id(s)),
            )
        else:
            info = _merge_provider_tmdb_meta(
                {},
                provider_meta_map.get(id(s)),
                "series",
            )
        tmdb_id = str(info.get("tmdb_id") or _provider_stream_tmdb_id(s) or "").strip()
        if not tmdb_id:
            continue
        title = info.get("title") or s.get("name", "Unknown")
        year = str(info.get("year") or "")[:4]
        poster = info.get("poster_url") or s.get("stream_icon") or s.get("cover") or ""
        fanart = info.get("fanart") or ""
        plot = info.get("plot", "")
        rating = str(info.get("rating") or "")
        runtime = info.get("duration", "")
        if isinstance(runtime, int):
            runtime = str(runtime)
        genre_val = info.get("genre", "")
        if isinstance(genre_val, list):
            genre_val = ", ".join(str(g) for g in genre_val)
        cast_val = info.get("cast", [])
        mpaa_val = info.get("mpaa", "")
        tagline_val = info.get("tagline", "")
        director_val = info.get("director", "")
        writer_val = info.get("writer", "")
        studio_val = info.get("studio", "")
        votes_val = info.get("votes", "")
        premiered_val = info.get("premiered", "")
        item = {
            "tmdb_type": media_type,
            "tmdb_id": tmdb_id,
            "title": title,
            "year": year,
            "poster": poster,
            "fanart": fanart,
            "plot": plot,
            "rating": rating,
            "runtime": runtime,
            "cast": cast_val,
            "genre": genre_val,
            "mpaa": mpaa_val,
            "tagline": tagline_val,
            "director": director_val,
            "writer": writer_val,
            "studio": studio_val,
            "votes": votes_val,
            "premiered": premiered_val,
        }
        if stype == "series":
            item["kind"] = "tvshow"
        url, li, is_folder = tmdb_routes_module._media_item(item, all_wm[0] if all_wm else None, None)
        provider_watched = False
        if stype == "movie":
            sid = str(s.get("stream_id", ""))
            for wm in all_wm:
                if sid and wm.is_watched(sid):
                    provider_watched = True
                    break
                if wm.is_watched(tmdb_id):
                    provider_watched = True
                    break
        else:
            for wm in all_wm:
                if wm.is_watched("tvshow:{0}".format(tmdb_id)):
                    provider_watched = True
                    break
        if provider_watched:
            try:
                li.getVideoInfoTag().setPlaycount(1)
            except Exception:
                pass
            li.setProperty("Watched", "true")
            li.setProperty("Overlay", "5")
        items.append((url, li, is_folder))
    xbmcplugin.addDirectoryItems(addon_handle, items)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def movies_menu(profile_num=None):
    original_active = pm.active
    if profile_num:
        pm.active = str(profile_num)
    if profile_num and not _prompt_profile_credentials(profile_num):
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    try:
        creds = _get_credentials()
        xtream_url = creds.get("xtream_url", "")
        if xtream_url:
            directory_items = []
            li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30007)))
            li.setArt({"icon": "DefaultAddonsSearch.png"})
            directory_items.append((
                build_url(
                    {
                        "mode": "search_global",
                        "profile_num": profile_num,
                        "stype": "live",
                    }
                ),
                li,
                True,
            ))
            li = _new_listitem("Recently Added")
            li.setArt({"icon": _local_icon("recent")})
            directory_items.append((
                build_url(
                    {
                        "mode": "xtream_streams",
                        "type": "movie",
                        "cat_id": "__recent__",
                        "profile_num": profile_num,
                    }
                ),
                li,
                True,
            ))
            xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
            handled = _browse_categories("movie", profile_num)
            if not handled:
                xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        else:
            li = _new_listitem(_t(30241))
            xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)], 1)
            xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    finally:
        if profile_num:
            pm.active = original_active


def series_menu(profile_num=None):
    original_active = pm.active
    if profile_num:
        pm.active = str(profile_num)
    if profile_num and not _prompt_profile_credentials(profile_num):
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    try:
        creds = _get_credentials()
        xtream_url = creds.get("xtream_url", "")
        if xtream_url:
            directory_items = []
            li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30007)))
            li.setArt({"icon": "DefaultAddonsSearch.png"})
            directory_items.append((
                build_url(
                    {
                        "mode": "search_global",
                        "profile_num": profile_num,
                        "stype": "live",
                    }
                ),
                li,
                True,
            ))
            li = _new_listitem("Recently Added")
            li.setArt({"icon": _local_icon("recent")})
            directory_items.append((
                build_url(
                    {
                        "mode": "xtream_streams",
                        "type": "series",
                        "cat_id": "__recent__",
                        "profile_num": profile_num,
                    }
                ),
                li,
                True,
            ))
            xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
            handled = _browse_categories("series", profile_num)
            if not handled:
                xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        else:
            li = _new_listitem(_t(30242))
            xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)], 1)
            xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    finally:
        if profile_num:
            pm.active = original_active
