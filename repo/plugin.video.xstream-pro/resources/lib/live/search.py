"""Search routes for Xstream Pro."""

_OWNED = {'_search_history_path', '_load_search_history', '_save_search_history', 'search_global', 'unified_search', 'search_m3u', 'search_all_profiles', 'search_all_profiles_combined'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _search_history_path(profile_num=None):
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    if profile_num is None:
        return os.path.join(profile, "search_history.json")
    return os.path.join(profile, f"search_history_p{profile_num}.json")


def _load_search_history(profile_num=None):
    path = _search_history_path(profile_num)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_search_history(history, profile_num=None):
    history_path = _search_history_path(profile_num)
    tmp_file = history_path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(history[:10], f, ensure_ascii=False)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp_file, history_path)


def _route_arg(name, default=""):
    try:
        values = globals().get("args", {}).get(name, [default])
        return values[0] if isinstance(values, list) else values
    except Exception:
        return default


def _route_bool(name):
    return str(_route_arg(name, "false")).strip().lower() in ("1", "true", "yes", "on")


def _search_history_menu(mode, title, profile_num=None, stype=None):
    history = _load_search_history(profile_num)
    items = []
    base = {"mode": mode, "new_search": "true"}
    if profile_num is not None:
        base["profile_num"] = str(profile_num)
    if stype:
        base["stype"] = stype
    li = _new_listitem(_t(31252))
    li.setArt({"icon": _local_icon("search")})
    items.append((build_url(base), li, True))
    for entry in history:
        q = {"mode": mode, "query": entry}
        if profile_num is not None:
            q["profile_num"] = str(profile_num)
        if stype:
            q["stype"] = stype
        li = _new_listitem(entry)
        li.setArt({"icon": _local_icon("search")})
        items.append((build_url(q), li, True))
    xbmcplugin.setContent(addon_handle, "files")
    xbmcplugin.addDirectoryItems(addon_handle, items, len(items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _new_search_query(title):
    query = xbmcgui.Dialog().input(title, type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return ""
    return query


def search_global(query=None, profile_num=None, stype=None):
    try:
        if query is None and _route_bool("new_search"):
            query = _new_search_query(_t(30140))
            if not query:
                return
        elif query is None:
            _search_history_menu("search_global", _t(30140), profile_num=profile_num, stype=stype)
            return
        # If profile not specified, ask user which profile to search
        if profile_num is None:
            profiles = []
            for i in range(1, 11):
                if addon.getSetting(f"profile_{i}_enabled") == "true":
                    name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
                    profiles.append((i, name))
            if not profiles:
                xbmcgui.Dialog().notification(_t(30770), _t(30074))
                xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                return
            options = [_t(30771)]  # All Profiles
            options.extend([p[1] for p in profiles])
            idx = xbmcgui.Dialog().select(_t(30140), options)
            if idx < 0:
                xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                return
            if idx == 0:
                # All Profiles
                if query is None:
                    history = _load_search_history()
                    if history:
                        hist_options = [_t(30544)] + history
                        idx2 = xbmcgui.Dialog().select(_t(30140), hist_options)
                        if idx2 < 0:
                            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                            return
                        if idx2 == 0:
                            kb = xbmcgui.Dialog().input(
                                _t(30140), type=xbmcgui.INPUT_ALPHANUM
                            )
                            if not kb:
                                xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                                return
                            query = kb
                        else:
                            query = history[idx2 - 1]
                    else:
                        kb = xbmcgui.Dialog().input(
                            _t(30140), type=xbmcgui.INPUT_ALPHANUM
                        )
                        if not kb:
                            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                            return
                        query = kb
                history = _load_search_history()
                if query in history:
                    history.remove(query)
                history.insert(0, query)
                _save_search_history(history)
                search_all_profiles(query)
                return
            else:
                profile_num = profiles[idx - 1][0]

        original_active = pm.active
        pm.active = str(profile_num)
        try:
            if query is None:
                history = _load_search_history()
                if history:
                    options = [_t(30544)] + history
                    idx = xbmcgui.Dialog().select(_t(30140), options)
                    if idx < 0:
                        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                        return
                    if idx == 0:
                        kb = xbmcgui.Dialog().input(
                            _t(30140), type=xbmcgui.INPUT_ALPHANUM
                        )
                        if not kb:
                            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                            return
                        query = kb
                    else:
                        query = history[idx - 1]
                else:
                    kb = xbmcgui.Dialog().input(_t(30140), type=xbmcgui.INPUT_ALPHANUM)
                    if not kb:
                        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
                        return
                    query = kb
            history = _load_search_history()
            if query in history:
                history.remove(query)
            history.insert(0, query)
            _save_search_history(history)

            creds = _get_credentials()
            has_xtream = bool(creds.get("xtream_url"))
            has_m3u = bool(creds.get("m3u_url"))

            if has_xtream:
                unified_search(query, stype=stype)
            elif has_m3u:
                search_m3u(query, stype=stype)
            else:
                xbmcgui.Dialog().notification(_t(30770), _t(30223))
        finally:
            pm.active = original_active
    except Exception as e:
        _log(f"search_global error: {e}")

        _log(f"Traceback: {traceback.format_exc()}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)


def unified_search(query, stype=None):
    creds = _get_credentials()
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    qlower = query.lower()
    show_epg = False
    hide_adult = addon.getSetting("hide_adult_categories").lower() == "true"

    stype_labels = {
        "live": _t(30220),
        "movie": _t(30004),
        "series": _t(30005),
    }
    stype_icons = {
        "live": "DefaultAddonPVRClient.png",
        "movie": "DefaultMovies.png",
        "series": "DefaultTVShows.png",
    }

    results = {}

    if stype is None or stype == "live":
        live_streams = _get_cached_xtream_streams(url, user, pwd, "live")
        live_results = [s for s in live_streams if qlower in s.get("name", "").lower()]
        if hide_adult:
            live_results = [
                s
                for s in live_results
                if not _is_adult_category(
                    s.get("name", "") + " " + s.get("category_name", "")
                )
            ]
        results["live"] = live_results

    if stype is None or stype == "movie":
        movie_streams = _get_cached_xtream_streams(url, user, pwd, "movie")
        movie_results = [
            s for s in movie_streams if qlower in s.get("name", "").lower()
        ]
        if hide_adult:
            movie_results = [
                s
                for s in movie_results
                if not _is_adult_category(
                    s.get("name", "") + " " + s.get("category_name", "")
                )
            ]
        results["movie"] = movie_results

    if stype is None or stype == "series":
        series_streams = _get_cached_xtream_streams(url, user, pwd, "series")
        series_results = [
            s for s in series_streams if qlower in s.get("name", "").lower()
        ]
        if hide_adult:
            series_results = [
                s
                for s in series_results
                if not _is_adult_category(
                    s.get("name", "") + " " + s.get("category_name", "")
                )
            ]
        results["series"] = series_results

    has_any = any(results.values())
    if not has_any:
        li = _new_listitem(_t(30223))
        xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)])
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    show_separators = len([v for v in results.values() if v]) > 1 and stype is None
    type_order = ["live", "movie", "series"]
    directory_items = []

    for t in type_order:
        if t not in results or not results[t]:
            continue
        if show_separators:
            sep = _new_listitem(
                f"[COLOR gray]────── {stype_labels.get(t, t)} ──────[/COLOR]"
            )
            sep.setArt({"icon": stype_icons.get(t, "DefaultFolder.png")})
            sep.setProperty("IsPlayable", "false")
            directory_items.append(("", sep, False))
        for s in results[t]:
            name = s.get("name", "Unknown")
            sid = str(s.get("stream_id", ""))
            if t == "live":
                epg_id = s.get("epg_channel_id") or sid
                play_url = IPTV.build_xtream_stream_url(url, user, pwd, s, "live")
                plot, display_name, current_title = (
                    _make_epg_info(epg, epg_id, name) if show_epg else ("", name, "")
                )
                li = _new_listitem(display_name)
                info_tag = li.getVideoInfoTag()
                info_tag.setMediaType("video")
                info_tag.setTitle(current_title or name)
                info_tag.setPlot(plot)
                if s.get("stream_icon"):
                    li.setArt(
                        {
                            "icon": s["stream_icon"],
                            "thumb": s["stream_icon"],
                            "poster": s["stream_icon"],
                        }
                    )
                li.setProperty("IsPlayable", "true")
                _prepare_playback_item(li)
                _set_live_props(li)
                q = {
                    "mode": "play_stream",
                    "url": play_url,
                    "name": name,
                    "title": current_title or name,
                    "plot": plot,
                    "icon": s.get("stream_icon", ""),
                    "profile_num": pm.active,
                }
                directory_items.append((build_url(q), li, False))
            elif t == "movie":
                play_url = IPTV.build_xtream_stream_url(url, user, pwd, s, "movie")
                info = _enrich_movie_info(s, url, user, pwd)
                li = _new_listitem(name)
                info_tag = li.getVideoInfoTag()
                info_tag.setMediaType("movie")
                info_tag.setTitle(name)
                plot = info.get("plot", "")
                info_tag.setPlot(plot)
                art = {}
                if info.get("poster_url"):
                    art["icon"] = info["poster_url"]
                    art["thumb"] = info["poster_url"]
                    art["poster"] = info["poster_url"]
                else:
                    art["icon"] = "DefaultMovies.png"
                li.setArt(art)
                li.setProperty("IsPlayable", "true")
                _prepare_playback_item(li)
                q = {
                    "mode": "play_stream",
                    "url": play_url,
                    "name": name,
                    "title": name,
                    "plot": plot,
                    "icon": s.get("stream_icon", ""),
                    "stype": "movie",
                    "profile_num": pm.active,
                }
                directory_items.append((build_url(q), li, False))
            elif t == "series":
                q_series = {
                    "mode": "xtream_series",
                    "series_id": sid,
                    "profile_num": pm.active,
                }
                li = _new_listitem(name)
                info_tag = li.getVideoInfoTag()
                info_tag.setMediaType("tvshow")
                info_tag.setTitle(name)
                if s.get("cover"):
                    li.setArt(
                        {"icon": s["cover"], "thumb": s["cover"], "poster": s["cover"]}
                    )
                directory_items.append((build_url(q_series), li, True))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def search_m3u(query=None, stype=None):
    try:
        if query is None and _route_bool("new_search"):
            query = _new_search_query(_t(30141))
            if not query:
                return
        elif query is None:
            _search_history_menu("search_m3u", _t(30141), stype=stype)
            return
        if stype in ("movie", "series"):
            li = _new_listitem(_t(30223))
            xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)], 1)
            xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
            return
        show_epg = False
        creds = _get_credentials()
        channels = _get_cached_m3u_channels(creds.get("m3u_url", ""))
        qlower = query.lower()
        directory_items = []
        for ch in channels:
            if (
                qlower not in ch.get("name", "").lower()
                and qlower not in ch.get("group", "").lower()
            ):
                continue
            name = ch.get("name", "Unknown")
            tvg_id = ch.get("tvg_id") or name
            url = ch.get("url")
            item_id = ch.get("tvg_id") or url
            plot, display_name, current_title = (
                _make_epg_info(epg, tvg_id, name) if show_epg else ("", name, "")
            )
            li = _new_listitem(display_name)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(current_title or name)
            info_tag.setPlot(plot)
            if ch.get("logo"):
                li.setArt({"icon": ch["logo"], "thumb": ch["logo"]})
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            _set_live_props(li)
            q = {
                "mode": "play_stream",
                "url": url,
                "name": name,
                "title": current_title or name,
                "plot": plot,
                "icon": ch.get("logo", ""),
                "profile_num": pm.active,
            }
            directory_items.append((build_url(q), li, False))
        if directory_items:
            xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
        _apply_sort("live")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    except Exception as e:
        _log(f"search_m3u error: {e}")

        _log(f"Traceback: {traceback.format_exc()}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)


def search_all_profiles(query):
    """Search across all enabled profiles and show results grouped by profile."""
    try:
        hide_adult = addon.getSetting("hide_adult_categories").lower() == "true"

        profiles = []
        for i in range(1, 11):
            if addon.getSetting(f"profile_{i}_enabled") == "true":
                name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
                profiles.append((i, name))

        if not profiles:
            xbmcgui.Dialog().notification(_t(30770), _t(30074))
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return

        li = _new_listitem("[COLOR gold]{0}[/COLOR]".format(_t(30771)))
        li.setArt({"icon": "DefaultFolder.png"})
        directory_items = [(
            build_url(
                {
                    "mode": "search_all_combined",
                    "query": query,
                }
            ),
            li,
            True,
        )]

        any_results = False
        for profile_num, profile_name in profiles:
            original_active = pm.active
            pm.active = str(profile_num)
            try:
                creds = _get_credentials()
                has_xtream = bool(creds.get("xtream_url"))
                has_m3u = bool(creds.get("m3u_url"))

                if not has_xtream and not has_m3u:
                    continue

                has_results = False
                qlower = query.lower()

                if has_xtream:
                    url = creds.get("xtream_url", "")
                    user = creds.get("xtream_username", "")
                    pwd = creds.get("xtream_password", "")

                    live_streams = _get_cached_xtream_streams(url, user, pwd, "live")
                    live_results = [
                        s for s in live_streams if qlower in s.get("name", "").lower()
                    ]
                    if hide_adult:
                        live_results = [
                            s
                            for s in live_results
                            if not _is_adult_category(
                                s.get("name", "") + " " + s.get("category_name", "")
                            )
                        ]

                    movie_streams = _get_cached_xtream_streams(url, user, pwd, "movie")
                    movie_results = [
                        s for s in movie_streams if qlower in s.get("name", "").lower()
                    ]
                    if hide_adult:
                        movie_results = [
                            s
                            for s in movie_results
                            if not _is_adult_category(
                                s.get("name", "") + " " + s.get("category_name", "")
                            )
                        ]

                    series_streams = _get_cached_xtream_streams(
                        url, user, pwd, "series"
                    )
                    series_results = [
                        s for s in series_streams if qlower in s.get("name", "").lower()
                    ]
                    if hide_adult:
                        series_results = [
                            s
                            for s in series_results
                            if not _is_adult_category(
                                s.get("name", "") + " " + s.get("category_name", "")
                            )
                        ]

                    if live_results or movie_results or series_results:
                        has_results = True

                elif has_m3u:
                    channels = _get_cached_m3u_channels(creds.get("m3u_url", ""))
                    for ch in channels:
                        if (
                            qlower in ch.get("name", "").lower()
                            or qlower in ch.get("group", "").lower()
                        ):
                            has_results = True
                            break

                if has_results:
                    any_results = True
                    li = _new_listitem(profile_name)
                    li.setArt({"icon": "DefaultAddonPVRClient.png"})
                    directory_items.append((
                        build_url(
                            {
                                "mode": "search_global",
                                "profile_num": profile_num,
                                "query": query,
                            }
                        ),
                        li,
                        True,
                    ))
            finally:
                pm.active = original_active

        if not any_results:
            li = _new_listitem(_t(30223))
            directory_items.append(("", li, False))

        if directory_items:
            xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    except Exception as e:
        _log(f"search_all_profiles error: {e}")

        _log(f"Traceback: {traceback.format_exc()}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)


def search_all_profiles_combined(query):
    """Show combined search results from all enabled profiles."""
    try:
        hide_adult = addon.getSetting("hide_adult_categories").lower() == "true"
        show_epg = False

        qlower = query.lower()
        has_any = False
        directory_items = []

        profiles = []
        for i in range(1, 11):
            if addon.getSetting(f"profile_{i}_enabled") == "true":
                name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
                profiles.append((i, name))

        for profile_num, profile_name in profiles:
            original_active = pm.active
            pm.active = str(profile_num)
            try:
                creds = _get_credentials()
                has_xtream = bool(creds.get("xtream_url"))
                has_m3u = bool(creds.get("m3u_url"))

                if not has_xtream and not has_m3u:
                    continue

                if has_xtream:
                    url = creds.get("xtream_url", "")
                    user = creds.get("xtream_username", "")
                    pwd = creds.get("xtream_password", "")

                    live_streams = _get_cached_xtream_streams(url, user, pwd, "live")
                    live_results = [
                        s for s in live_streams if qlower in s.get("name", "").lower()
                    ]
                    if hide_adult:
                        live_results = [
                            s
                            for s in live_results
                            if not _is_adult_category(
                                s.get("name", "") + " " + s.get("category_name", "")
                            )
                        ]

                    movie_streams = _get_cached_xtream_streams(url, user, pwd, "movie")
                    movie_results = [
                        s for s in movie_streams if qlower in s.get("name", "").lower()
                    ]
                    if hide_adult:
                        movie_results = [
                            s
                            for s in movie_results
                            if not _is_adult_category(
                                s.get("name", "") + " " + s.get("category_name", "")
                            )
                        ]

                    series_streams = _get_cached_xtream_streams(
                        url, user, pwd, "series"
                    )
                    series_results = [
                        s for s in series_streams if qlower in s.get("name", "").lower()
                    ]
                    if hide_adult:
                        series_results = [
                            s
                            for s in series_results
                            if not _is_adult_category(
                                s.get("name", "") + " " + s.get("category_name", "")
                            )
                        ]

                    profile_header_added = False
                    if live_results:
                        has_any = True
                        if not profile_header_added:
                            profile_header_added = True
                            header = _new_listitem(
                                "[COLOR yellow]{0}[/COLOR]".format(profile_name)
                            )
                            header.setArt({"icon": "DefaultAddonPVRClient.png"})
                            header.setProperty("IsPlayable", "false")
                            directory_items.append(("", header, False))
                        sep = _new_listitem(
                            "[COLOR gray]────── {0} ──────[/COLOR]".format(
                                _t(30220)
                            )
                        )
                        sep.setArt({"icon": "DefaultAddonPVRClient.png"})
                        sep.setProperty("IsPlayable", "false")
                        directory_items.append(("", sep, False))
                        for s in live_results:
                            name = s.get("name", "Unknown")
                            sid = str(s.get("stream_id", ""))
                            epg_id = s.get("epg_channel_id") or sid
                            play_url = IPTV.build_xtream_stream_url(
                                url, user, pwd, s, "live"
                            )
                            plot, display_name, current_title = (
                                _make_epg_info(epg, epg_id, name)
                                if show_epg
                                else ("", name, "")
                            )
                            li = _new_listitem(display_name)
                            info_tag = li.getVideoInfoTag()
                            info_tag.setMediaType("video")
                            info_tag.setTitle(current_title or name)
                            info_tag.setPlot(plot)
                            if s.get("stream_icon"):
                                li.setArt(
                                    {
                                        "icon": s["stream_icon"],
                                        "thumb": s["stream_icon"],
                                        "poster": s["stream_icon"],
                                    }
                                )
                            li.setProperty("IsPlayable", "true")
                            _prepare_playback_item(li)
                            _set_live_props(li)
                            q = {
                                "mode": "play_stream",
                                "url": play_url,
                                "name": name,
                                "title": current_title or name,
                                "plot": plot,
                                "icon": s.get("stream_icon", ""),
                                "profile_num": profile_num,
                            }
                            directory_items.append((build_url(q), li, False))

                    if movie_results:
                        has_any = True
                        if not profile_header_added:
                            profile_header_added = True
                            header = _new_listitem(
                                "[COLOR yellow]{0}[/COLOR]".format(profile_name)
                            )
                            header.setArt({"icon": "DefaultAddonPVRClient.png"})
                            header.setProperty("IsPlayable", "false")
                            directory_items.append(("", header, False))
                        sep = _new_listitem(
                            "[COLOR gray]────── {0} ──────[/COLOR]".format(
                                _t(30221)
                            )
                        )
                        sep.setArt({"icon": "DefaultMovies.png"})
                        sep.setProperty("IsPlayable", "false")
                        directory_items.append(("", sep, False))
                        for s in movie_results:
                            name = s.get("name", "Unknown")
                            sid = str(s.get("stream_id", ""))
                            play_url = IPTV.build_xtream_stream_url(
                                url, user, pwd, s, "movie"
                            )
                            info = _enrich_movie_info(s, url, user, pwd)
                            li = _new_listitem(name)
                            info_tag = li.getVideoInfoTag()
                            info_tag.setMediaType("movie")
                            info_tag.setTitle(name)
                            header_parts = []
                            if info.get("year"):
                                header_parts.append(str(info.get("year", "")))
                            genre_val = info.get("genre", "")
                            if isinstance(genre_val, list):
                                genre_val = ", ".join(str(g) for g in genre_val)
                            if genre_val:
                                header_parts.append(genre_val)
                            header = " | ".join(header_parts)
                            plot = info.get("plot", "")
                            if info.get("cast"):
                                cast_names = ", ".join(
                                    [a["name"] for a in info["cast"][:5]]
                                )
                                if header:
                                    plot = f"{header}\n[COLOR gray]Cast: {cast_names}[/COLOR]\n\n{plot}"
                                else:
                                    plot = f"[COLOR gray]Cast: {cast_names}[/COLOR]\n\n{plot}"
                            elif header:
                                plot = f"{header}\n\n{plot}"
                            info_tag.setPlot(plot)
                            if info.get("rating"):
                                try:
                                    info_tag.setRating(float(info["rating"]))
                                except (ValueError, TypeError):
                                    pass
                            if info.get("year"):
                                try:
                                    info_tag.setYear(int(info["year"]))
                                except (ValueError, TypeError):
                                    pass
                            if info.get("cast"):
                                cast_list = []
                                for idx, actor in enumerate(info["cast"][:10]):
                                    cast_list.append(
                                        xbmc.Actor(
                                            actor.get("name", ""),
                                            actor.get("role", ""),
                                            idx,
                                            actor.get("thumbnail", ""),
                                        )
                                    )
                                if cast_list:
                                    info_tag.setCast(cast_list)
                            art = {}
                            if info.get("poster_url"):
                                art = {
                                    "icon": info["poster_url"],
                                    "thumb": info["poster_url"],
                                    "poster": info["poster_url"],
                                }
                            li.setArt(art)
                            li.setProperty("IsPlayable", "true")
                            _prepare_playback_item(li)
                            q = {
                                "mode": "play_stream",
                                "url": play_url,
                                "name": name,
                                "icon": info.get("poster_url", ""),
                                "stype": "movie",
                                "profile_num": profile_num,
                            }
                            directory_items.append((build_url(q), li, False))

                    if series_results:
                        has_any = True
                        if not profile_header_added:
                            profile_header_added = True
                            header = _new_listitem(
                                "[COLOR yellow]{0}[/COLOR]".format(profile_name)
                            )
                            header.setArt({"icon": "DefaultAddonPVRClient.png"})
                            header.setProperty("IsPlayable", "false")
                            directory_items.append(("", header, False))
                        sep = _new_listitem(
                            "[COLOR gray]────── {0} ──────[/COLOR]".format(
                                _t(30222)
                            )
                        )
                        sep.setArt({"icon": "DefaultTVShows.png"})
                        sep.setProperty("IsPlayable", "false")
                        directory_items.append(("", sep, False))
                        for s in series_results:
                            name = s.get("name", "Unknown")
                            sid = str(s.get("series_id", ""))
                            series_url = build_url(
                                {"mode": "xtream_series", "series_id": sid}
                            )
                            li = _new_listitem(name)
                            info_tag = li.getVideoInfoTag()
                            info_tag.setMediaType("tvshow")
                            info_tag.setTitle(name)
                            info_tag.setPlot(s.get("plot", ""))
                            if s.get("cover"):
                                li.setArt({"icon": s["cover"], "thumb": s["cover"]})
                            directory_items.append((series_url, li, True))

                elif has_m3u:
                    channels = _get_cached_m3u_channels(creds.get("m3u_url", ""))
                    m3u_results = [
                        ch
                        for ch in channels
                        if qlower in ch.get("name", "").lower()
                        or qlower in ch.get("group", "").lower()
                    ]
                    if m3u_results:
                        has_any = True
                        header = _new_listitem(
                            "[COLOR yellow]{0}[/COLOR]".format(profile_name)
                        )
                        header.setArt({"icon": "DefaultAddonPVRClient.png"})
                        header.setProperty("IsPlayable", "false")
                        directory_items.append(("", header, False))
                        sep = _new_listitem(
                            "[COLOR gray]────── {0} ──────[/COLOR]".format(
                                _t(30220)
                            )
                        )
                        sep.setArt({"icon": "DefaultAddonPVRClient.png"})
                        sep.setProperty("IsPlayable", "false")
                        directory_items.append(("", sep, False))
                        for ch in m3u_results:
                            name = ch.get("name", "Unknown")
                            tvg_id = ch.get("tvg_id") or name
                            url = ch.get("url")
                            item_id = ch.get("tvg_id") or url
                            plot, display_name, current_title = (
                                _make_epg_info(epg, tvg_id, name)
                                if show_epg
                                else ("", name, "")
                            )
                            li = _new_listitem(display_name)
                            info_tag = li.getVideoInfoTag()
                            info_tag.setMediaType("video")
                            info_tag.setTitle(current_title or name)
                            info_tag.setPlot(plot)
                            if ch.get("logo"):
                                li.setArt({"icon": ch["logo"], "thumb": ch["logo"]})
                            li.setProperty("IsPlayable", "true")
                            _prepare_playback_item(li)
                            _set_live_props(li)
                            q = {
                                "mode": "play_stream",
                                "url": url,
                                "name": name,
                                "title": current_title or name,
                                "plot": plot,
                                "icon": ch.get("logo", ""),
                                "profile_num": profile_num,
                            }
                            directory_items.append((build_url(q), li, False))
            finally:
                pm.active = original_active

        if not has_any:
            li = _new_listitem(_t(30223))
            directory_items.append(("", li, False))

        if directory_items:
            xbmcplugin.addDirectoryItems(addon_handle, directory_items)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    except Exception as e:
        _log(f"search_all_profiles_combined error: {e}")

        _log(f"Traceback: {traceback.format_exc()}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)

