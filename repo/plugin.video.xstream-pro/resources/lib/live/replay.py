"""Replay/catchup browse and playback routes for Xstream Pro."""

_OWNED = {'replay_xtream_categories', 'replay_menu', 'replay_channels', 'replay_channel', 'replay_play', 'replay_channel_m3u', 'replay_play_m3u'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def replay_xtream_categories(profile_num=None):
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    cats = _get_cached_xtream_categories(url, user, pwd, "live")

    # Load all live streams once to compute catchup-enabled category sets/counts
    all_streams = _get_cached_xtream_streams(url, user, pwd, "live", None)
    catchup_cat_ids = set()
    cat_counts = {}
    for s in all_streams:
        if not _truthy_catchup(s.get("tv_archive")) and not _truthy_catchup(s.get("catchup")):
            continue
        cid = str(s.get("category_id", ""))
        if not cid:
            continue
        catchup_cat_ids.add(cid)
        cat_counts[cid] = cat_counts.get(cid, 0) + 1

    show_counts = addon.getSetting("show_content_counts").lower() == "true"
    hide_adult = addon.getSetting("hide_adult_categories").lower() == "true"
    adult_locked = _is_adult_locked("live")
    hidden_subcats = _get_hidden_subcats("live", pnum)

    directory_items = []
    for c in cats:
        name = c.get("category_name", "Unknown")
        cat_id = str(c.get("category_id", ""))
        if cat_id not in catchup_cat_ids:
            continue
        if cat_id in hidden_subcats:
            continue
        if hide_adult and _is_adult_category(name):
            continue
        is_adult = _is_adult_category(name)
        count = cat_counts.get(cat_id, 0)
        if show_counts:
            display = f"{name}  [COLOR gray]({count})[/COLOR]"
        else:
            display = name
        if is_adult and adult_locked:
            display = f"[COLOR red]🔒[/COLOR] {display}"
        li = _new_listitem(display)
        li.setArt({"icon": "DefaultFolder.png"})
        q = {
            "mode": "replay_channels",
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


def replay_menu(profile_num=None):
    pnum = profile_num or pm.active
    if profile_num and not _prompt_profile_credentials(profile_num):
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    original_active = pm.active
    if profile_num:
        pm.active = str(profile_num)
    try:
        creds = _get_credentials()
        xtream_url = creds.get("xtream_url", "")
        m3u_url = creds.get("m3u_url", "")
        has_m3u_with_creds = bool(m3u_url) and _m3u_has_credentials(m3u_url)

        if xtream_url or has_m3u_with_creds:
            replay_xtream_categories(profile_num)
            return

        # M3U-simple fallback (currently unreachable from profile_menu for replay)
        if m3u_url:
            m3u_channels = _get_cached_m3u_channels(m3u_url)
            directory_items = []
            for ch in m3u_channels:
                if not _truthy_catchup(ch.get("catchup")) and not ch.get("catchup_source"):
                    continue
                name = ch.get("name", "Unknown")
                li = _new_listitem(f"[M3U] {name}")
                if ch.get("logo"):
                    li.setArt({"icon": ch["logo"], "thumb": ch["logo"]})
                q = {
                    "mode": "replay_channel_m3u",
                    "channel_name": name,
                    "epg_id": ch.get("tvg_id", ""),
                    "channel_url": ch.get("url", ""),
                    "catchup": ch.get("catchup", ""),
                    "catchup_source": ch.get("catchup_source", ""),
                    "logo": ch.get("logo", ""),
                    "profile_num": pnum,
                }
                directory_items.append((build_url(q), li, True))
            if directory_items:
                xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))

        _apply_sort("replay")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    finally:
        if profile_num:
            pm.active = original_active


def replay_channels(cat_id, page=1, adult="0", profile_num=None):
    if adult == "1" and _is_adult_locked("live"):
        if not _check_pin("Adult Content"):
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    streams = _get_cached_xtream_streams(url, user, pwd, "live", cat_id)

    # Filter catchup-enabled only
    streams = [
        s for s in streams
        if _truthy_catchup(s.get("tv_archive")) or _truthy_catchup(s.get("catchup"))
    ]

    hidden_items = _get_hidden_items("live", profile_num)
    if hidden_items:
        streams = [
            s for s in streams if str(s.get("stream_id", "")) not in hidden_items
        ]

    if addon.getSetting("sort_order_replay") == "Newest first":
        try:
            streams.sort(
                key=lambda s: int(s.get("added", 0) or 0), reverse=True
            )
        except Exception:
            pass

    # Pagination
    per_page = _get_pagination_limit("live")
    if per_page == 0:
        per_page = len(streams)
    total = len(streams)
    start = (page - 1) * per_page
    end = start + per_page
    page_streams = streams[start:end]

    xbmcplugin.setContent(addon_handle, "livetv")
    directory_items = []
    for s in page_streams:
        name = s.get("name", "Unknown")
        li = _new_listitem(name)
        if s.get("stream_icon"):
            li.setArt({"icon": s["stream_icon"], "thumb": s["stream_icon"]})
        q = {
            "mode": "replay_channel",
            "stream_id": str(s.get("stream_id", "")),
            "epg_id": s.get("epg_channel_id") or str(s.get("stream_id", "")),
            "name": name,
            "profile_num": pnum,
        }
        directory_items.append((build_url(q), li, True))

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
            "mode": "replay_channels",
            "cat_id": cat_id,
            "adult": adult,
            "profile_num": profile_num,
            "page": page + 1,
        }
        directory_items.append((build_url(q), li, True))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    _apply_sort("replay")
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def replay_channel(stream_id, epg_id, name="", profile_num=None):
    pnum = profile_num or pm.active
    epg = EPG(addon, profile_num=pnum)
    epg.load()
    try:
        days_back = int(addon.getSetting("replay_days") or "7")
    except ValueError:
        days_back = 7
    programs = epg.get_programs_for_channel(
        epg_id, channel_name=name, days_back=days_back
    )

    if not programs:
        now = datetime.datetime.now()
        directory_items = []
        directory_items = []
        for hours_back in range(1, 25):
            start = now - datetime.timedelta(hours=hours_back)
            start_fmt = start.strftime("%Y-%m-%d:%H-%M")
            title = f"{start.strftime('%d/%m %H:%M')} - {_t(30543)}"
            li = _new_listitem(title)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(title)
            info_tag.setDuration(3600)
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            q = {
                "mode": "replay_play",
                "stream_id": stream_id,
                "start": start_fmt,
                "duration": 3600,
                "profile_num": pnum,
            }
            directory_items.append((build_url(q), li, False))
    else:
        directory_items = []
        for prog in programs:
            if _parse_xmltv_time(prog["start"]) > time.time():
                continue
            title = f"{prog['start_str']} - {prog['title']}"
            li = _new_listitem(title)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(prog["title"])
            info_tag.setPlot(prog.get("desc", ""))
            info_tag.setDuration(int(prog["duration_sec"]))
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            q = {
                "mode": "replay_play",
                "stream_id": stream_id,
                "start": prog["start_timestamp"],
                "duration": prog["duration_sec"],
                "profile_num": pnum,
            }
            directory_items.append((build_url(q), li, False))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def replay_play(stream_id, start, duration, profile_num=None):
    pnum = profile_num or pm.active
    creds = _get_credentials_for_profile(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    try:
        duration = int(duration)
    except (ValueError, TypeError):
        duration = 3600
    play_url = IPTV.build_catchup_url(url, user, pwd, stream_id, start, duration)
    li = xbmcgui.ListItem(path=play_url)
    li.setProperty("IsPlayable", "true")
    info_tag = li.getVideoInfoTag()
    info_tag.setMediaType("video")
    info_tag.setTitle(f"Replay {stream_id}")
    _prepare_playback_item(li)
    xbmcplugin.setResolvedUrl(addon_handle, True, listitem=li)


def replay_channel_m3u(
    channel_name, epg_id, channel_url, catchup, catchup_source, logo, profile_num=None
):
    """Show replay/catchup programs for an M3U-based channel."""
    pnum = profile_num or pm.active
    epg = EPG(addon, profile_num=pnum)
    epg.load()
    try:
        days_back = int(addon.getSetting("replay_days") or "7")
    except ValueError:
        days_back = 7

    programs = epg.get_programs_for_channel(
        epg_id, channel_name=channel_name, days_back=days_back
    )

    if not programs:
        # No EPG data - show hourly slots going back

        now = datetime.datetime.now()
        for hours_back in range(1, 25):
            start = now - datetime.timedelta(hours=hours_back)
            start_ts = int(start.timestamp())
            end_ts = start_ts + 3600
            start_fmt = start.strftime("%Y-%m-%d:%H-%M")
            title = f"{start.strftime('%d/%m %H:%M')} - {_t(30543)}"
            li = _new_listitem(title)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(title)
            info_tag.setDuration(3600)
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            q = {
                "mode": "replay_play_m3u",
                "channel_name": channel_name,
                "channel_url": channel_url,
                "catchup": catchup,
                "catchup_source": catchup_source,
                "logo": logo,
                "start_ts": str(start_ts),
                "end_ts": str(end_ts),
                "profile_num": pnum,
            }
            directory_items.append((build_url(q), li, False))
    else:
        directory_items = []
        for prog in programs:
            title = f"{prog['start_str']} - {prog['title']}"
            li = _new_listitem(title)
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(prog["title"])
            info_tag.setPlot(prog.get("desc", ""))
            info_tag.setDuration(int(prog["duration_sec"]))
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            q = {
                "mode": "replay_play_m3u",
                "channel_name": channel_name,
                "channel_url": channel_url,
                "catchup": catchup,
                "catchup_source": catchup_source,
                "logo": logo,
                "start_ts": str(prog["start_timestamp"]),
                "end_ts": str(prog["start_timestamp"] + prog["duration_sec"]),
                "profile_num": pnum,
            }
            directory_items.append((build_url(q), li, False))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def replay_play_m3u(
    channel_name,
    channel_url,
    catchup,
    catchup_source,
    logo,
    start_ts,
    end_ts,
    profile_num=None,
):
    """Play M3U catchup stream."""
    channel_data = {
        "name": channel_name,
        "url": channel_url,
        "catchup": catchup,
        "catchup_source": catchup_source,
    }
    try:
        start_utc = int(start_ts)
        end_utc = int(end_ts)
    except (ValueError, TypeError):
        xbmcgui.Dialog().notification(
            "Xstream Pro", _t(30730), xbmcgui.NOTIFICATION_ERROR
        )
        return

    play_url = IPTV.build_m3u_catchup_url(channel_data, start_utc, end_utc)
    if not play_url:
        xbmcgui.Dialog().notification(
            "Xstream Pro", _t(30731), xbmcgui.NOTIFICATION_ERROR
        )
        return

    li = xbmcgui.ListItem(path=play_url)
    li.setProperty("IsPlayable", "true")
    info_tag = li.getVideoInfoTag()
    info_tag.setMediaType("video")
    info_tag.setTitle(f"Replay: {channel_name}")
    if logo:
        li.setArt({"icon": logo, "thumb": logo})
    _prepare_playback_item(li)
    xbmcplugin.setResolvedUrl(addon_handle, True, listitem=li)
