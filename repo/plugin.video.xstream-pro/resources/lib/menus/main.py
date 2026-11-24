"""Main menu route helpers for Xstream Pro."""

import threading

import xbmc
import xbmcgui
import xbmcplugin


addon = None
addon_handle = None
pm = None
_log = None
_t = None
_new_listitem = None
_local_icon = None
_menu_art = None
_addon_fanart = None
_build_url = None
_log_route_timing = None
_session_should_run = None
_safe_sync_pvr_favorites_startup = None
_run_startup_checks = None
_mark_zombie_downloads_failed = None
_get_setting_direct = None
_restart_or_prompt = None
_get_pvr_credentials = None
_get_pvr_profile_num = None
_m3u_has_credentials = None
_pvr_numbered_label = None
_owned_pvr_instance_enabled = None
_any_profile_has_credentials = None
_main_menu_customized_key = "main_menu_customized"
_NO_CREDS_NOTIFICATION_SHOWN = False


def init(
    addon_obj,
    addon_handle_value,
    profile_manager,
    log_fn,
    translate_fn,
    new_listitem_fn,
    local_icon_fn,
    menu_art_fn,
    addon_fanart_fn,
    build_url_fn,
    log_route_timing_fn,
    session_should_run_fn,
    safe_sync_pvr_favorites_startup_fn,
    run_startup_checks_fn,
    mark_zombie_downloads_failed_fn,
    get_setting_direct_fn,
    restart_or_prompt_fn,
    get_pvr_credentials_fn,
    get_pvr_profile_num_fn,
    m3u_has_credentials_fn,
    pvr_numbered_label_fn,
    owned_pvr_instance_enabled_fn,
    any_profile_has_credentials_fn,
    main_menu_customized_key="main_menu_customized",
):
    global addon, addon_handle, pm, _log, _t, _new_listitem, _local_icon
    global _menu_art, _addon_fanart, _build_url, _log_route_timing
    global _session_should_run, _safe_sync_pvr_favorites_startup
    global _run_startup_checks, _mark_zombie_downloads_failed
    global _get_setting_direct, _restart_or_prompt, _get_pvr_credentials
    global _get_pvr_profile_num, _m3u_has_credentials, _pvr_numbered_label
    global _owned_pvr_instance_enabled, _any_profile_has_credentials
    global _main_menu_customized_key

    addon = addon_obj
    addon_handle = addon_handle_value
    pm = profile_manager
    _log = log_fn
    _t = translate_fn
    _new_listitem = new_listitem_fn
    _local_icon = local_icon_fn
    _menu_art = menu_art_fn
    _addon_fanart = addon_fanart_fn
    _build_url = build_url_fn
    _log_route_timing = log_route_timing_fn
    _session_should_run = session_should_run_fn
    _safe_sync_pvr_favorites_startup = safe_sync_pvr_favorites_startup_fn
    _run_startup_checks = run_startup_checks_fn
    _mark_zombie_downloads_failed = mark_zombie_downloads_failed_fn
    _get_setting_direct = get_setting_direct_fn
    _restart_or_prompt = restart_or_prompt_fn
    _get_pvr_credentials = get_pvr_credentials_fn
    _get_pvr_profile_num = get_pvr_profile_num_fn
    _m3u_has_credentials = m3u_has_credentials_fn
    _pvr_numbered_label = pvr_numbered_label_fn
    _owned_pvr_instance_enabled = owned_pvr_instance_enabled_fn
    _any_profile_has_credentials = any_profile_has_credentials_fn
    _main_menu_customized_key = main_menu_customized_key or "main_menu_customized"


def main_menu_item_visible(visible, key):
    if key in ("main_tools", "tools"):
        return True
    customized = _main_menu_customized_key in visible
    if not customized:
        if key in ("live_pvr", "pvr_replay", "guide"):
            return key in visible
        return True
    return key in visible


def main_menu_available_item_labels():
    items = []

    pvr_creds = _get_pvr_credentials()
    pvr_has_live = bool(pvr_creds.get("xtream_url") or pvr_creds.get("m3u_url"))
    pvr_profile_num = _get_pvr_profile_num()
    pvr_m3u_url = pvr_creds.get("m3u_url", "")

    pvr_has_replay = (
        addon.getSetting(f"profile_{pvr_profile_num}_load_live") != "false"
        and (
            bool(pvr_creds.get("xtream_url"))
            or (bool(pvr_m3u_url) and _m3u_has_credentials(pvr_m3u_url))
        )
    )

    if pvr_has_live:
        items.append(("live_pvr", _pvr_numbered_label("Live TV - PVR", pvr_profile_num)))
        items.append(("guide", "Live TV - Guide"))
        if pvr_has_replay:
            items.append(("pvr_replay", _t(30006)))
        items.append(("sports", "Sports"))

    tmdb_enabled = addon.getSetting("tmdb_enabled").lower() != "false"

    if tmdb_enabled:
        items.extend([
            ("tmdb_movies", _t(30902)),
            ("tmdb_tvshows", _t(30903)),
            ("tmdb_animations", _t(31238)),
            ("tmdb_people", _t(30930)),
            ("tmdb_lists", _t(31239)),
            ("tmdb_randomised", _t(30904)),
            ("tmdb_discover", _t(31111)),
            ("tmdb_trakt", _t(30906)),
            ("tmdb_search", _t(30907)),
        ])
    else:
        has_search = False

        for n in range(1, 11):
            if addon.getSetting("profile_{0}_enabled".format(n)) == "true":
                name = addon.getSetting("profile_{0}_name".format(n)) or _t(30390, n)
                items.append(("profile_{0}".format(n), name))

            if (
                addon.getSetting("profile_{0}_xtream_url".format(n))
                or addon.getSetting("profile_{0}_m3u".format(n))
            ):
                has_search = True

        if has_search:
            items.append(("search_global", _t(30889)))

    items.extend([
        ("favorites", _t(30009)),
        ("downloads", _t(30940)),
    ])

    return items


def main_menu():
    global _NO_CREDS_NOTIFICATION_SHOWN

    _log("Opening main menu")

    _bg = xbmcgui.DialogProgressBG()
    _bg.create("Xstream Pro", "Loading Xstream Pro...")
    _bg.update(10, "Xstream Pro", "Checking PVR favorites...")

    if (
        addon.getSetting("pvr_favorites_enabled").lower() == "true"
        and _session_should_run("pvr_favs_startup", 300)
    ):
        try:
            threading.Thread(target=_safe_sync_pvr_favorites_startup, daemon=True).start()
        except Exception as e:
            _log(f"PVR Favorites startup sync error: {e}")

    _bg.update(30, "Xstream Pro", "Running startup checks...")

    if _session_should_run("startup_checks", 300):
        _run_startup_checks()

    _bg.update(60, "Xstream Pro", "Cleaning up...")

    if _session_should_run("zombie_download_cleanup"):
        try:
            _mark_zombie_downloads_failed()
        except Exception as e:
            _log(f"Zombie download cleanup error: {e}")

    _bg.update(80, "Xstream Pro", "Building menu...")

    if (_get_setting_direct("buffer_fix_needs_restart", "false") or "").lower() == "true":
        addon.setSetting("buffer_fix_needs_restart", "false")
        xbmcgui.Dialog().ok("Xstream Pro", _t(30569))

    last_pvr = addon.getSetting("last_pvr_profile")
    current_pvr = addon.getSetting("active_pvr_profile") or "Profile 1"

    if last_pvr and current_pvr != last_pvr:
        restart = xbmcgui.Dialog().yesno(
            "Xstream Pro",
            _t(30570),
            yeslabel=_t(30165),
            nolabel=_t(30164),
        )
        if restart:
            _restart_or_prompt()

    if current_pvr != last_pvr:
        addon.setSetting("last_pvr_profile", current_pvr)

    visible = set(pm.get_visible_categories())
    visible.update(("tools", "main_tools"))
    if addon.getSetting("sports_enabled").lower() != "false":
        visible.add("sports")
    else:
        visible.discard("sports")

    items_dict = {}

    pvr_creds = _get_pvr_credentials()
    pvr_has_live = bool(pvr_creds.get("xtream_url") or pvr_creds.get("m3u_url"))
    pvr_profile_num = _get_pvr_profile_num()
    pvr_m3u_url = pvr_creds.get("m3u_url", "")

    pvr_has_replay = (
        addon.getSetting(f"profile_{pvr_profile_num}_load_live") != "false"
        and (
            bool(pvr_creds.get("xtream_url"))
            or (bool(pvr_m3u_url) and _m3u_has_credentials(pvr_m3u_url))
        )
    )

    if "live_pvr" in visible and pvr_has_live:
        items_dict["live_pvr"] = (
            _pvr_numbered_label("Live TV - PVR", pvr_profile_num),
            {"mode": "open_pvr"},
            _local_icon("live_tv_pvr"),
            False,
        )

    if "guide" in visible and pvr_has_live:
        main_on = _owned_pvr_instance_enabled("main")
        guide_label = "Live TV - Guide" if main_on else "[COLOR dimgray]Live TV - Guide[/COLOR]"
        guide_mode = "open_pvr_guide" if main_on else "pvr_not_active"
        items_dict["guide"] = (
            guide_label,
            {"mode": guide_mode},
            _local_icon("guide"),
            False,
        )

    if "pvr_replay" in visible and pvr_has_replay:
        items_dict["pvr_replay"] = (
            _t(30006),
            {"mode": "replay_menu", "profile_num": pvr_profile_num},
            _local_icon("in_progress"),
            True,
        )

    if "sports" in visible and pvr_has_live:
        items_dict["sports"] = (
            "Sports",
            {"mode": "sports_menu"},
            _local_icon("sports"),
            True,
        )

    tmdb_enabled = addon.getSetting("tmdb_enabled").lower() != "false"

    if tmdb_enabled:
        items_dict["tmdb_movies"] = (
            _t(30902),
            {"mode": "xstream_tmdb_movies_menu"},
            _local_icon("movies"),
            True,
        )
        items_dict["tmdb_tvshows"] = (
            _t(30903),
            {"mode": "xstream_tmdb_tvshows_menu"},
            _local_icon("tv_shows"),
            True,
        )
        items_dict["tmdb_animations"] = (
            _t(31238),
            {"mode": "xstream_tmdb_animation_menu"},
            _local_icon("animation"),
            True,
        )
        items_dict["tmdb_people"] = (
            _t(30930),
            {"mode": "xstream_tmdb_people_menu"},
            _local_icon("people"),
            True,
        )
        items_dict["tmdb_lists"] = (
            _t(31239),
            {"mode": "xstream_tmdb_lists_menu"},
            _local_icon("lists"),
            True,
        )
        items_dict["tmdb_randomised"] = (
            _t(30904),
            {"mode": "xstream_tmdb_randomised_menu"},
            _local_icon("randomised"),
            True,
        )
        items_dict["tmdb_discover"] = (
            _t(31111),
            {"mode": "xstream_tmdb_discover_menu"},
            _local_icon("discover"),
            True,
        )
        items_dict["tmdb_trakt"] = (
            _t(30906),
            {"mode": "xstream_tmdb_trakt_menu"},
            _local_icon("trakt"),
            True,
        )
        items_dict["tmdb_search"] = (
            _t(30907),
            {"mode": "xstream_tmdb_search_menu"},
            _local_icon("search"),
            True,
        )
    else:
        for n in range(1, 11):
            if addon.getSetting(f"profile_{n}_enabled") == "true":
                name = addon.getSetting(f"profile_{n}_name") or _t(30390, n)
                items_dict[f"profile_{n}"] = (
                    name,
                    {"mode": "profile_menu", "pnum": n},
                    _local_icon("profiles"),
                    True,
                )

        has_search = any(
            bool(
                addon.getSetting(f"profile_{n}_xtream_url")
                or addon.getSetting(f"profile_{n}_m3u")
            )
            for n in range(1, 11)
        )

        if has_search:
            items_dict["search_global"] = (
                _t(30889),
                {"mode": "search_global"},
                _local_icon("search"),
                True,
            )

    items_dict["main_tools"] = (
        _t(30010),
        {"mode": "main_tools_menu"},
        _local_icon("tools"),
        True,
    )

    items_dict["favorites"] = (
        _t(30009),
        {"mode": "favorites_menu"},
        _local_icon("favorites"),
        True,
    )

    items_dict["downloads"] = (
        _t(30940),
        {"mode": "downloads_manager"},
        _local_icon("downloads"),
        True,
    )

    default_order = ["live_pvr", "guide", "pvr_replay", "sports"]

    if tmdb_enabled:
        default_order.extend([
            "tmdb_movies",
            "tmdb_tvshows",
            "tmdb_animations",
            "tmdb_people",
            "tmdb_lists",
            "tmdb_randomised",
            "tmdb_discover",
            "tmdb_trakt",
            "tmdb_search",
        ])
    else:
        for n in range(1, 11):
            key = f"profile_{n}"
            if key in items_dict:
                default_order.append(key)

        if "search_global" in items_dict:
            default_order.append("search_global")

    default_order.extend(["favorites", "downloads", "main_tools"])

    items = [
        items_dict[key]
        for key in default_order
        if key in items_dict and main_menu_item_visible(visible, key)
    ]

    fanart = _addon_fanart()
    directory_items = []

    for label, query, icon, is_folder in items:
        li = _new_listitem(label)
        li.setArt(_menu_art(icon, fanart))
        item_url = query if isinstance(query, str) else _build_url(query)
        directory_items.append((item_url, li, is_folder))

    xbmcplugin.addDirectoryItems(addon_handle, directory_items)

    _bg.update(100, "Xstream Pro", "Done!")
    _bg.close()

    if not _NO_CREDS_NOTIFICATION_SHOWN:
        has_any_credentials = _any_profile_has_credentials()
    else:
        has_any_credentials = True

    if not _NO_CREDS_NOTIFICATION_SHOWN and not has_any_credentials:
        _NO_CREDS_NOTIFICATION_SHOWN = True

        try:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                _t(31145),
                xbmcgui.NOTIFICATION_INFO,
                8000,
            )
        except Exception:
            pass

    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    _log_route_timing("main_menu")
