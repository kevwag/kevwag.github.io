"""Live, movie, series, and M3U browse routes for Xstream Pro."""

_OWNED = {'_m3u_simple_menu', '_show_all_m3u_channels', 'live_menu', 'm3u_group', 'xtream_categories', 'xtream_streams', 'xtream_series', 'xtream_season'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _history_class(name):
    getter = globals().get("_get_history_classes")
    if callable(getter):
        return getter()[name]
    return globals()[name]


def _m3u_simple_menu(profile_num):
    pnum = profile_num
    creds = _get_credentials_for_profile(pnum)
    channels = _get_cached_m3u_channels(creds.get("m3u_url", ""))
    counts = {"live": 0, "movie": 0, "series": 0}
    for ch in channels:
        counts[_classify_m3u_channel(ch)] += 1
    items = [
        (_t(30002), "live", "DefaultAddonPVRClient.png"),
        (_t(30004), "movie", "DefaultMovies.png"),
        (_t(30005), "series", "DefaultTVShows.png"),
        (_t(30771), "", "DefaultVideo.png"),
    ]
    directory_items = []
    for label, stype, icon in items:
        count = len(channels) if not stype else counts.get(stype, 0)
        if count <= 0:
            continue
        li = _new_listitem(f"{label} ({count})")
        li.setArt({"icon": icon})
        q = {
            "mode": "m3u_simple_section",
            "pnum": pnum,
            "stype": stype,
            "page": 1,
        }
        directory_items.append((build_url(q), li, True))
    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _show_all_m3u_channels(profile_num, page=1, stype_filter=""):
    """Show all M3U channels directly without categories (for simple M3U without creds), with pagination."""
    pnum = profile_num
    creds = _get_credentials_for_profile(pnum)
    m3u_url = creds.get("m3u_url", "")

    if not m3u_url:
        return

    channels = _get_cached_m3u_channels(m3u_url)

    hidden_subcats = _get_hidden_subcats("live", pnum)
    hidden_items = _get_hidden_items("live", pnum)
    channels = [
        ch
        for ch in channels
        if (ch.get("group") or "General") not in hidden_subcats
        and str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
        not in hidden_items
    ]

    if stype_filter:
        channels = [
            ch for ch in channels
            if _classify_m3u_channel(ch) == stype_filter
        ]

    per_page = _get_pagination_limit("m3u_classic")
    if per_page == 0:
        per_page = len(channels)
    total = len(channels)
    start = (page - 1) * per_page
    end = start + per_page
    page_channels = channels[start:end]

    if stype_filter == "movie":
        xbmcplugin.setContent(addon_handle, "movies")
    elif stype_filter == "series":
        xbmcplugin.setContent(addon_handle, "episodes")
    else:
        xbmcplugin.setContent(addon_handle, "livetv")

    directory_items = []
    for ch in page_channels:
        name = ch.get("name", "Unknown")
        url = ch.get("url", "")
        icon = ch.get("logo", "") or "DefaultVideo.png"
        tvg_id = ch.get("tvg_id") or name
        item_id = str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))

        li = _new_listitem(name)
        li.setArt({"icon": icon})
        li.setInfo("video", {"title": name})
        li.setProperty("IsPlayable", "true")
        item_stype = stype_filter or _classify_m3u_channel(ch)
        if item_stype == "live":
            li.setProperty("IsLiveTV", "1")
        _prepare_playback_item(li)
        ctx = _build_favorite_ctx(
            item_id, name, item_stype, icon, url,
            epg_id=tvg_id, profile_num=pnum
        )
        li.addContextMenuItems(ctx)

        q = {
            "mode": "play_stream",
            "url": url,
            "name": name,
            "icon": icon,
            "profile_num": pnum,
            "stype": item_stype,
        }
        kodi_props = ch.get("kodi_props") or {}
        stream_ua = ch.get("user_agent", "")
        stream_ref = ch.get("referrer", "")
        if kodi_props:
            import json as _json
            q["kodi_props"] = _json.dumps(kodi_props)
        if stream_ua:
            q["stream_ua"] = stream_ua
        if stream_ref:
            q["stream_ref"] = stream_ref
        directory_items.append((build_url(q), li, False))

    if end < total:
        li = _new_listitem(
            "[COLOR yellow]{0} ({1})[/COLOR]".format(_t(30232), page + 1)
        )
        art = {"icon": "DefaultFolder.png"}
        _fanart = _addon_fanart()
        if _fanart:
            art["fanart"] = _fanart
        li.setArt(art)
        q = {
            "mode": "m3u_simple_section" if stype_filter else "m3u_all_channels",
            "pnum": pnum,
            "stype": stype_filter,
            "page": page + 1,
        }
        directory_items.append((build_url(q), li, True))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def live_menu(profile_num=None):
    original_active = pm.active
    if profile_num:
        pm.active = str(profile_num)
    if profile_num and not _prompt_profile_credentials(profile_num):
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    try:
        creds = _get_credentials()
        xtream_url = creds.get("xtream_url", "")
        m3u_url = creds.get("m3u_url", "")
        has_m3u_with_creds = bool(m3u_url) and _m3u_has_credentials(m3u_url)
        _log(
            f"live_menu: profile={pm.active}, xtream_url={bool(xtream_url)}, m3u_url={bool(m3u_url)}, m3u_with_creds={has_m3u_with_creds}"
        )

        if not xtream_url and not m3u_url:
            li = _new_listitem(_t(30240))
            xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)], 1)
            xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
            return

        # M3U with credentials OR Xtream - treat as Xtream (show category folders)
        if xtream_url or has_m3u_with_creds:
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
            xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
            xtream_categories("live", profile_num)
            return

        # M3U without credentials - show flat paginated list of all channels
        if m3u_url:
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
            xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
            _show_all_m3u_channels(profile_num)
            return

        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    finally:
        if profile_num:
            pm.active = original_active


def m3u_group(group, profile_num=None, page=1):
    xbmcplugin.setContent(addon_handle, "livetv")
    pnum = profile_num or pm.active
    show_epg = _epg_enabled()
    epg = None
    if show_epg:
        epg = EPG(addon, profile_num=pnum)
        epg.load()
        if epg.is_refreshing:
            _log("EPG background refresh in progress - showing cached/stale data")
    creds = _get_credentials_for_profile(pnum)
    channels = _get_cached_m3u_channels(creds.get("m3u_url", ""))
    if show_epg and epg and channels:
        fallback_targets = [
            {
                "tvg_id": ch.get("tvg_id") or ch.get("url") or ch.get("name", ""),
                "name": ch.get("name", ""),
                "group": ch.get("group") or "General",
            }
            for ch in channels
        ]
        _apply_epg_fallback_from_other_profiles(
            epg,
            pnum,
            fallback_targets,
            target_id_key="tvg_id",
            target_name_key="name",
            log_prefix="M3U Live TV EPG",
        )
    hidden_items = _get_hidden_items("live", pnum)
    group_channels = []
    for ch in channels:
        if (ch.get("group") or "General") != group:
            continue
        item_id = str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
        if item_id in hidden_items:
            continue
        group_channels.append(ch)

    per_page = _get_pagination_limit("live")
    if per_page == 0:
        per_page = len(group_channels)
    total = len(group_channels)
    start = (page - 1) * per_page
    end = start + per_page
    page_channels = group_channels[start:end]
    epg_aliases = _build_same_group_epg_aliases(group_channels, epg, group) if show_epg else {}

    for ch in page_channels:
        name = ch.get("name", "Unknown")
        tvg_id = ch.get("tvg_id") or name
        url = ch.get("url")
        plot, display_name, current_title = (
            _make_epg_info(epg, tvg_id, name, epg_aliases=epg_aliases) if show_epg else ("", name, "")
        )
        li = _new_listitem(display_name)
        info_tag = li.getVideoInfoTag()
        info_tag.setMediaType("video")
        info_tag.setTitle(current_title or name)
        info_tag.setPlot(plot)
        if ch.get("logo"):
            li.setArt({"icon": ch["logo"], "thumb": ch["logo"]})
        li.setProperty("IsPlayable", "true")
        li.setProperty("IsLiveTV", "1")
        li.setProperty("previewpath", url)
        _prepare_playback_item(li)
        _set_live_props(li)
        live_play_url = url
        q = {
            "mode": "play_stream",
            "url": live_play_url,
            "name": name,
            "title": current_title or name,
            "plot": plot,
            "icon": ch.get("logo", ""),
            "profile_num": pnum,
        }
        directory_items.append((build_url(q), li, False))

    if end < total:
        li = _new_listitem(
            "[COLOR yellow]{0} ({1})[/COLOR]".format(_t(30232), page + 1)
        )
        art = {"icon": "DefaultFolder.png"}
        _fanart = _addon_fanart()
        if _fanart:
            art["fanart"] = _fanart
        li.setArt(art)
        q = {
            "mode": "m3u_group",
            "group": group,
            "pnum": pnum,
            "page": page + 1,
        }
        directory_items.append((build_url(q), li, True))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    _apply_sort("live")
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def xtream_categories(stype, profile_num=None):
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    cats = _get_cached_xtream_categories(url, user, pwd, stype)
    show_counts = addon.getSetting("show_content_counts").lower() == "true"
    hide_empty = addon.getSetting("hide_empty_categories").lower() == "true"
    cat_counts = {}
    if show_counts or hide_empty:
        cat_counts = _cache_load(f"xtream_counts_{stype}") or {}
        if not cat_counts:
            # Fallback: compute once from streams, then cache for next time.
            all_streams = _get_cached_xtream_streams(url, user, pwd, stype, None)
            cat_counts = {}
            for s in all_streams:
                cid = str(s.get("category_id", ""))
                cat_counts[cid] = cat_counts.get(cid, 0) + 1
            _cache_save(f"xtream_counts_{stype}", cat_counts)
    hide_adult = addon.getSetting("hide_adult_categories").lower() == "true"
    adult_locked = _is_adult_locked(stype)
    hidden_subcats = _get_hidden_subcats(stype, pnum)
    directory_items = []
    for c in cats:
        name = c.get("category_name", "Unknown")
        cat_id = str(c.get("category_id", ""))
        if cat_id in hidden_subcats:
            continue
        if hide_adult and _is_adult_category(name):
            continue
        is_adult = _is_adult_category(name)
        count = cat_counts.get(cat_id, 0)
        if hide_empty and count <= 0:
            continue
        if show_counts:
            display = f"{name}  [COLOR gray]({count})[/COLOR]"
        else:
            display = name
        if is_adult and adult_locked:
            display = f"[COLOR red]🔒[/COLOR] {display}"
        li = _new_listitem(display)
        li.setArt({"icon": "DefaultFolder.png"})
        q = {
            "mode": "xtream_streams",
            "type": stype,
            "cat_id": c.get("category_id", ""),
            "adult": "1" if is_adult else "0",
            "profile_num": profile_num,
        }
        cat_url = build_url(q)
        ctx = _folder_favorite_ctx(name, cat_url, "DefaultFolder.png")
        li.addContextMenuItems(ctx)
        directory_items.append((cat_url, li, True))
    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    # _apply_sort is intentionally skipped — category folders stay in provider order
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def xtream_streams(stype, cat_id, page=1, adult="0", profile_num=None):
    if adult == "1" and _is_adult_locked(stype):
        if not _check_pin("Adult Content"):
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum) if profile_num else _get_credentials()
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    recent_only = str(cat_id) == "__recent__"
    streams = _get_cached_xtream_streams(url, user, pwd, stype, None if recent_only else cat_id)
    hidden_items = _get_hidden_items(stype, profile_num)
    if hidden_items:
        streams = [
            s for s in streams if str(s.get("stream_id", "")) not in hidden_items
        ]

    if stype == "movie" and addon.getSetting("show_watched_items").lower() == "false":
        watched_filter = _history_class("WatchedMovies")(addon, profile_num=pnum)
        streams = [
            s for s in streams
            if not watched_filter.is_watched(str(s.get("stream_id", "")))
        ]

    # Pre-sort by "added" timestamp when user selects "Newest first"
    if recent_only and stype in ("movie", "series"):
        try:
            streams.sort(key=_provider_added_sort_key, reverse=True)
        except Exception:
            pass
        streams = streams[:100]
    elif stype in ("movie", "series"):
        sort_key = f"sort_order_{stype}"
        if addon.getSetting(sort_key) == "Newest first":
            try:
                streams.sort(
                    key=lambda s: int(s.get("added", 0) or 0), reverse=True
                )
            except Exception:
                pass  # Malformed "added" field — keep provider order

    # Pagination from settings
    per_page = 100 if recent_only else _get_pagination_limit(stype)
    if per_page == 0:
        per_page = len(streams)
    total = len(streams)
    start = (page - 1) * per_page
    end = start + per_page
    page_streams = streams[start:end]

    if stype == "movie" and url and user and pwd:
        if addon.getSetting("provider_movie_enabled").lower() == "true":
            _prefetch_vod_info_batch(page_streams, url, user, pwd)

    if stype == "live":
        xbmcplugin.setContent(addon_handle, "livetv")
    elif stype == "movie":
        xbmcplugin.setContent(addon_handle, "movies")
    elif stype == "series":
        xbmcplugin.setContent(addon_handle, "tvshows")
    show_epg = _epg_enabled() if stype == "live" else False
    epg = None
    if show_epg:
        epg = EPG(addon, profile_num=pnum)
        epg.load()
        if epg.is_refreshing:
            _log("EPG background refresh in progress - showing cached/stale data")
        fallback_cat_name = ""
        if cat_id and url and user and pwd:
            for c in _get_cached_xtream_categories(url, user, pwd, stype):
                if str(c.get("category_id", "")) == str(cat_id):
                    fallback_cat_name = c.get("category_name", "")
                    break
        fallback_targets = [
            {
                "epg_channel_id": s.get("epg_channel_id") or str(s.get("stream_id", "")),
                "tvg_id": s.get("epg_channel_id") or str(s.get("stream_id", "")),
                "name": s.get("name", ""),
                "group": fallback_cat_name,
            }
            for s in streams
            if s.get("epg_channel_id") or s.get("stream_id")
        ]
        _apply_epg_fallback_from_other_profiles(
            epg,
            pnum,
            fallback_targets,
            target_id_key="epg_channel_id",
            target_name_key="name",
            log_prefix="Live TV EPG",
        )
    epg_aliases = _build_same_group_epg_aliases(streams, epg, str(cat_id or "")) if show_epg else {}
    provider_meta_map = {}
    movie_watched = None
    if stype in ("movie", "series"):
        use_prov = addon.getSetting("provider_movie_enabled" if stype == "movie" else "provider_series_enabled").lower() == "true"
        if use_prov:
            provider_meta_map = _provider_tmdb_meta_map(page_streams, stype)
            _queue_provider_tmdb_meta_prefetch(page_streams, stype)
    if stype == "movie":
        movie_watched = _history_class("WatchedMovies")(addon, profile_num=pnum)
    directory_items = []
    for s in page_streams:
        name = s.get("name", "Unknown")
        if stype == "live":
            sid = str(s.get("stream_id", ""))
            epg_id = s.get("epg_channel_id") or sid
            play_url = IPTV.build_xtream_stream_url(url, user, pwd, s, "live")
            plot, display_name, current_title = (
                _make_epg_info(epg, epg_id, name, epg_aliases=epg_aliases) if show_epg else ("", name, "")
            )
            li = _new_listitem(display_name)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(current_title or name)
            info_tag.setPlot(plot)
            if s.get("stream_icon"):
                li.setArt({"icon": s["stream_icon"], "thumb": s["stream_icon"]})
            li.setProperty("IsPlayable", "true")
            li.setProperty("IsLiveTV", "1")
            li.setProperty("previewpath", play_url)
            _prepare_playback_item(li)
            _set_live_props(li)
            catchup = "default" if _truthy_catchup(s.get("tv_archive")) or _truthy_catchup(s.get("catchup")) else ""
            catchup_source = (
                _xtream_timeshift_catchup_source(url, user, pwd, sid)
                if (_truthy_catchup(s.get("tv_archive")) or _truthy_catchup(s.get("catchup")))
                else ""
            )
            catchup_days = (
                str(s.get("tv_archive_duration", "") or "7")
                if (_truthy_catchup(s.get("tv_archive")) or _truthy_catchup(s.get("catchup")))
                else ""
            )
            ctx = _build_favorite_ctx(
                sid, name, "live", s.get("stream_icon", ""), play_url,
                epg_id=epg_id, catchup=catchup,
                catchup_source=catchup_source, catchup_days=catchup_days,
                profile_num=pnum
            )
            li.addContextMenuItems(ctx)
            q = {
                "mode": "play_stream",
                "url": play_url,
                "name": name,
                "title": current_title or name,
                "plot": plot,
                "icon": s.get("stream_icon", ""),
                "profile_num": pnum,
            }
            directory_items.append((build_url(q), li, False))
        elif stype == "movie":
            sid = str(s.get("stream_id", ""))
            play_url = IPTV.build_xtream_stream_url(url, user, pwd, s, "movie")
            info = _merge_provider_tmdb_meta(
                _enrich_movie_info(s, url, user, pwd),
                provider_meta_map.get(id(s)),
            )
            li = _new_listitem(name)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("movie")
            info_tag.setTitle(info.get("title") or name)
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
                cast_names = ", ".join([a["name"] for a in info["cast"][:5]])
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
                except Exception as e:
                    _log(f"setRating warning: {e}")
            if info.get("year"):
                try:
                    info_tag.setYear(int(info["year"]))
                except Exception as e:
                    _log(f"setYear warning: {e}")
            if info.get("duration"):
                try:
                    info_tag.setDuration(int(info["duration"]))
                except Exception as e:
                    _log(f"setDuration warning: {e}")
            _set_provider_tmdb_info_fields(info_tag, info)
            art = _provider_art("DefaultMovies.png", info)
            li.setArt(art)
            is_watched = movie_watched.is_watched(sid) if movie_watched else False
            try:
                info_tag.setPlaycount(1 if is_watched else 0)
            except Exception:
                pass
            if is_watched:
                li.setProperty("Watched", "true")
                li.setProperty("Overlay", "5")
            if info.get("cast"):
                cast_list = []
                for idx, actor in enumerate(info["cast"][:10]):
                    name = actor.get("name", "")
                    role = actor.get("role", "")
                    thumbnail = actor.get("thumbnail", "")
                    cast_list.append(xbmc.Actor(name, role, idx, thumbnail))
                if cast_list:
                    info_tag.setCast(cast_list)
            li.setArt(_provider_art("DefaultMovies.png", info))
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            ctx = [
                (
                    (_t(30806) + " - Xstream") if is_watched else (_t(30805) + " - Xstream"),
                    "RunPlugin({0})".format(build_url({
                        "mode": "toggle_provider_movie_watched",
                        "stream_id": sid,
                        "profile_num": pnum,
                    })),
                )
            ]
            ctx.extend(_build_favorite_ctx(
                sid, name, "movie", s.get("stream_icon", ""), play_url,
                profile_num=pnum, year=info.get("year", "")
            ))
            li.addContextMenuItems(ctx)
            q = {
                "mode": "source_select",
                "title": name,
                "year": info.get("year", ""),
                "tmdb_type": "movie",
            }
            directory_items.append((build_url(q), li, False))
        elif stype == "series":
            sid = str(s.get("series_id", ""))
            info = _merge_provider_tmdb_meta(
                _enrich_series_info(s, url, user, pwd),
                provider_meta_map.get(id(s)),
                "series",
            )
            q = {"mode": "xtream_series", "series_id": sid, "profile_num": pnum}
            series_url = build_url(q)
            li = _new_listitem(name)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("tvshow")
            info_tag.setTitle(info.get("title") or name)
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
                cast_names = ", ".join([a["name"] for a in info["cast"][:5]])
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
                except Exception as e:
                    _log(f"setRating warning: {e}")
            if info.get("year"):
                try:
                    info_tag.setYear(int(info["year"]))
                except Exception as e:
                    _log(f"setYear warning: {e}")
            if info.get("duration"):
                try:
                    info_tag.setDuration(int(info["duration"]))
                except Exception as e:
                    _log(f"setDuration warning: {e}")
            _set_provider_tmdb_info_fields(info_tag, info)
            if info.get("cast"):
                cast_list = []
                for idx, actor in enumerate(info["cast"][:10]):
                    name = actor.get("name", "")
                    role = actor.get("role", "")
                    thumbnail = actor.get("thumbnail", "")
                    cast_list.append(xbmc.Actor(name, role, idx, thumbnail))
                if cast_list:
                    info_tag.setCast(cast_list)
            li.setArt(_provider_art("DefaultTVShows.png", info))
            ctx = _build_favorite_ctx(
                sid, name, "series", s.get("stream_icon", ""), series_url,
                profile_num=pnum
            )
            li.addContextMenuItems(ctx)
            directory_items.append((series_url, li, True))

    if end < total:
        li = _new_listitem(
            "[COLOR yellow]{0} ({1})[/COLOR]".format(_t(30232), page + 1)
        )
        art = {"icon": "DefaultFolder.png"}
        _fanart = _addon_fanart()
        if _fanart:
            art["fanart"] = _fanart
        li.setArt(art)
        q = {
            "mode": "xtream_streams",
            "type": stype,
            "cat_id": cat_id,
            "page": page + 1,
        }
        if adult:
            q["adult"] = adult
        if profile_num is not None:
            q["profile_num"] = profile_num
        directory_items.append((build_url(q), li, True))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    _apply_sort(stype)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def xtream_series(series_id, profile_num=None):
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    info = IPTV.get_xtream_series_info(url, user, pwd, series_id)
    episodes = info.get("episodes", {})
    xbmcplugin.setContent(addon_handle, "tvshows")

    # Provider metadata toggles for series
    use_prov = addon.getSetting("provider_series_enabled").lower() == "true"
    use_prov_plot = use_prov and (addon.getSetting("provider_series_plot").lower() == "true")
    use_prov_posters = use_prov and (addon.getSetting("provider_series_posters").lower() == "true")
    use_prov_ratings = use_prov and (addon.getSetting("provider_series_ratings").lower() == "true")
    use_prov_cast = use_prov and (addon.getSetting("provider_series_cast").lower() == "true")
    use_prov_genre = use_prov and (addon.getSetting("provider_series_genre").lower() == "true")
    use_prov_duration = use_prov and (addon.getSetting("provider_series_duration").lower() == "true")

    # Look up series metadata from API response or series list cache
    series_meta = info.get("info", {}) or {}
    if not series_meta.get("plot") and not series_meta.get("cover"):
        # Fall back to series list cache
        try:
            all_series = _cache_load("xtream_streams_series") or []
            for s in all_series:
                if str(s.get("series_id", "")) == str(series_id):
                    series_meta = s
                    break
        except Exception:
            pass  # Cache may be missing or corrupt; will be re-fetched

    # Extract metadata fields (respecting toggles)
    series_plot = ""
    if use_prov_plot:
        series_plot = (
            series_meta.get("plot", "")
            or series_meta.get("description", "")
            or info.get("plot", "")
            or ""
        )

    series_cover = ""
    if use_prov_posters:
        series_cover = (
            series_meta.get("cover", "")
            or series_meta.get("stream_icon", "")
            or series_meta.get("poster_url", "")
            or ""
        )

    series_backdrop = ""
    if use_prov_posters:
        bp = series_meta.get("backdrop_path", []) or info.get("backdrop_path", [])
        if bp and isinstance(bp, list) and bp[0]:
            series_backdrop = bp[0]

    series_rating = ""
    if use_prov_ratings:
        series_rating = str(
            series_meta.get("rating", "") or series_meta.get("rating_5based", "") or ""
        )

    series_year = ""
    if use_prov_ratings:
        release_raw = (
            series_meta.get("releaseDate", "")
            or series_meta.get("release_date", "")
            or series_meta.get("releasedate", "")
            or ""
        )
        if release_raw:
            series_year = str(release_raw)[:4]

    series_genre = ""
    if use_prov_genre:
        series_genre = series_meta.get("genre", "") or ""

    series_cast_str = ""
    if use_prov_cast:
        series_cast_str = series_meta.get("cast", "") or ""

    # episode_run_time may be string "60" or integer
    ep_run_time = 0
    if use_prov_duration:
        ep_run_time_raw = series_meta.get("episode_run_time", "") or ""
        try:
            ep_run_time = int(ep_run_time_raw) if ep_run_time_raw else 0
        except (ValueError, TypeError):
            ep_run_time = 0

    watched_eps = _history_class("WatchedEpisodes")(addon, profile_num=pnum)
    ctx = []
    directory_items = []
    for season_num in sorted(
        episodes.keys(), key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x))
    ):
        eps = episodes.get(season_num, [])
        total_eps = _season_episode_total(eps)
        watched_count = watched_eps.get_watched_count(series_id, season_num)
        if total_eps and watched_count > total_eps:
            watched_count = total_eps
        if (
            addon.getSetting("show_watched_items").lower() == "false"
            and total_eps
            and watched_count >= total_eps
        ):
            continue
        label = "{0} - {1}/{2}".format(_t(30541, season_num), total_eps, watched_count)
        li = _new_listitem(label)
        info_tag = li.getVideoInfoTag()
        info_tag.setMediaType("season")
        info_tag.setTitle(label)

        # Plot
        if use_prov_plot and series_plot:
            info_tag.setPlot(series_plot)

        # Season / Episode count
        try:
            info_tag.setSeason(int(season_num))
        except (ValueError, TypeError):
            pass
        if total_eps:
            info_tag.setEpisode(total_eps)

        # Year
        if use_prov_ratings and series_year:
            try:
                info_tag.setYear(int(series_year))
            except (ValueError, TypeError):
                pass

        # Rating
        if use_prov_ratings and series_rating:
            try:
                info_tag.setRating(float(series_rating))
            except (ValueError, TypeError):
                pass

        # Cast
        if use_prov_cast and series_cast_str:
            cast_list = []
            for idx, actor_name in enumerate(series_cast_str.split(",")[:10]):
                name = actor_name.strip()
                if name:
                    cast_list.append(xbmc.Actor(name, "", idx, ""))
            if cast_list:
                info_tag.setCast(cast_list)

        # Duration: episode_run_time (minutes) * episode count, or sum of episode durations
        if use_prov_duration:
            season_duration = 0
            if ep_run_time and total_eps:
                season_duration = ep_run_time * total_eps * 60
            else:
                for ep in eps:
                    d = int(ep.get("info", {}).get("duration_secs", 0) or 0)
                    season_duration += d
            if season_duration:
                try:
                    info_tag.setDuration(int(season_duration))
                except Exception as e:
                    _log(f"setDuration warning (season): {e}")

        # Art
        art = {}
        if use_prov_posters and series_cover:
            art["icon"] = series_cover
            art["thumb"] = series_cover
            art["poster"] = series_cover
        else:
            art["icon"] = "DefaultFolder.png"
        if use_prov_posters and series_backdrop:
            art["fanart"] = series_backdrop
        li.setArt(art)

        li.addContextMenuItems(ctx)
        q = {
            "mode": "xtream_season",
            "series_id": series_id,
            "season_num": season_num,
            "profile_num": pnum,
        }
        directory_items.append((build_url(q), li, True))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=True, cacheToDisc=False)


def xtream_season(series_id, season_num, profile_num=None):
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    info = IPTV.get_xtream_series_info(url, user, pwd, series_id)
    eps = info.get("episodes", {}).get(season_num, [])
    xbmcplugin.setContent(addon_handle, "episodes")

    # Provider metadata toggles for series
    use_prov = addon.getSetting("provider_series_enabled").lower() == "true"
    use_prov_plot = use_prov and (addon.getSetting("provider_series_plot").lower() == "true")
    use_prov_posters = use_prov and (addon.getSetting("provider_series_posters").lower() == "true")
    use_prov_duration = use_prov and (addon.getSetting("provider_series_duration").lower() == "true")
    watched_eps = _history_class("WatchedEpisodes")(addon, profile_num=pnum)
    directory_items = []
    for ep in eps:
        ep_id = str(ep.get("id", ""))
        title = ep.get("title") or _t(30542, ep.get("episode_num", "?"))
        ep_duration = 0
        if use_prov_duration:
            ep_duration = int(ep.get("info", {}).get("duration_secs", 0) or 0)
        if not ep_duration and use_prov_duration and ep_id:
            pb_dur = _load_playback_duration(ep_id)
            if pb_dur:
                ep_duration = pb_dur
        is_watched = watched_eps.is_watched(series_id, season_num, ep_id) if ep_id else False
        if is_watched and addon.getSetting("show_watched_items").lower() == "false":
            continue
        li = _new_listitem(title)
        info_tag = li.getVideoInfoTag()
        info_tag.setMediaType("episode")
        info_tag.setTitle(title)
        try:
            info_tag.setPlaycount(1 if is_watched else 0)
        except Exception:
            pass
        if is_watched:
            li.setProperty("Watched", "true")
            li.setProperty("Overlay", "5")
        # Plot
        if use_prov_plot:
            info_tag.setPlot(ep.get("info", {}).get("plot", ""))

        if ep_duration:
            try:
                info_tag.setDuration(ep_duration)
            except Exception as e:
                _log(f"setDuration warning: {e}")

        movie_image = ep.get("info", {}).get("movie_image")
        if use_prov_posters and movie_image:
            li.setArt({"icon": movie_image, "thumb": movie_image})
        li.setProperty("IsPlayable", "true")
        _prepare_playback_item(li)
        play_url = IPTV.build_xtream_stream_url(url, user, pwd, ep, "series")
        ctx = [
            (
                (_t(30806) + " - Xstream") if is_watched else (_t(30805) + " - Xstream"),
                "RunPlugin({0})".format(build_url({
                    "mode": "toggle_provider_episode_watched",
                    "series_id": series_id,
                    "season_num": season_num,
                    "ep_id": ep_id,
                    "profile_num": pnum,
                })),
            )
        ]
        ctx.extend(_build_favorite_ctx(
            ep_id, title, "series", movie_image or "", play_url,
            profile_num=profile_num,
            showname=info.get("info", {}).get("name", ""),
            season=season_num,
            episode=ep.get("episode_num", "")
        ))
        li.addContextMenuItems(ctx)
        series_name = info.get("info", {}).get("name", "")
        q = {
            "mode": "play_stream",
            "url": play_url,
            "name": title,
            "title": series_name or title,
            "plot": ep.get("info", {}).get("plot", ""),
            "icon": movie_image or "",
            "stype": "series",
            "tmdb_id": str(info.get("info", {}).get("tmdb_id") or info.get("info", {}).get("tmdb") or ""),
            "series_id": series_id,
            "season_num": season_num,
            "ep_id": ep_id,
            "profile_num": pnum,
        }
        directory_items.append((build_url(q), li, False))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
