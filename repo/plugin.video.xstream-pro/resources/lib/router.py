"""Route registry for Xstream Pro addon."""

import json
import os
import traceback

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

from lang import _t

ROUTES = {}
_CTX = {}


def init(context):
    _CTX.clear()
    _CTX.update(context or {})


def route(mode):
    def decorator(func):
        if mode in ROUTES:
            raise RuntimeError("Duplicate route registration: {0}".format(mode))
        ROUTES[mode] = func
        return func
    return decorator


def dispatch(runtime):
    handler = ROUTES.get(runtime.mode)
    if handler is None:
        return False
    handler(runtime)
    return True


def _ctx(name, default=None):
    return _CTX.get(name, default)


def _ctx_module(name):
    getter = _ctx(name)
    if callable(getter):
        return getter()
    return None


def _ctx_required_module(name):
    module = _ctx_module(name)
    if module is None:
        raise RuntimeError("Router context missing: {0}".format(name))
    return module


def _log(msg):
    log_fn = _ctx("_log")
    if log_fn:
        log_fn(msg)


def _int_arg(args, key, default=None):
    try:
        raw = args.get(key, [default])[0]
        if raw is None:
            return default
        return int(raw)
    except (TypeError, ValueError):
        return default


def _int_float_arg(args, key, default=0):
    try:
        return int(float(args.get(key, [default])[0] or default))
    except (TypeError, ValueError):
        return default


def _setup_module(setup_key, module_key):
    setup_fn = _ctx(setup_key)
    module_getter = _ctx(module_key)
    if not setup_fn or not module_getter:
        _log("Router setup missing for {0}/{1}".format(setup_key, module_key))
        return None
    if not setup_fn():
        return None
    return module_getter()


def _get_downloader():
    getter = _ctx("get_downloader_module")
    if not getter:
        raise RuntimeError("Downloader route context missing")
    return getter()


def _normalize_tmdb_type(value):
    normalizer = _ctx("normalize_tmdb_type")
    if normalizer:
        return normalizer(value)
    raw = str(value or "").lower()
    if raw in ("tv", "tvshow", "show", "season", "episode"):
        return "tv"
    if raw in ("movie", "movies"):
        return "movie"
    return ""


def _build_url(query):
    builder = _ctx("build_url")
    if not builder:
        return ""
    return builder(query)


def _call_ctx(name, *args, **kwargs):
    func = _ctx(name)
    if not func:
        raise RuntimeError("Router context missing: {0}".format(name))
    return func(*args, **kwargs)


def _end_false(runtime):
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


def _is_playing_pvr_video():
    try:
        if xbmc.getCondVisibility("Pvr.IsPlayingTv") or xbmc.getCondVisibility("Pvr.IsPlayingRadio"):
            return True
        playing_path = xbmc.getInfoLabel("Player.Filenameandpath") or ""
        return playing_path.startswith("pvr://")
    except Exception:
        return False


def _pvr_osd_key_action(direction):
    if direction == "left":
        pvr_action = "ActivateWindow(PVROSDChannels)"
        fallback_action = "Action(StepBack)"
    else:
        pvr_action = "ActivateWindow(PVROSDGuide)"
        fallback_action = "Action(StepForward)"
    xbmc.executebuiltin(pvr_action if _is_playing_pvr_video() else fallback_action)


def _handle_download_error(label, exc, notify_id=None):
    _log("{0} error: {1}".format(label, exc))
    if notify_id is not None:
        xbmcgui.Dialog().notification("Xstream Pro", _t(notify_id))


def _user_tools_module():
    return _ctx_required_module("get_user_tools_module")


def _user_profiles_module():
    return _ctx_required_module("get_user_profiles_module")


def _pvr_favorites_module():
    return _ctx_required_module("get_pvr_favorites_module")


@route("main_tools_menu")
def _main_tools_menu(runtime):
    _user_tools_module().main_tools_menu()


@route("tools_menu")
def _tools_menu(runtime):
    _user_tools_module().tools_menu()


@route("reset_reload_menu")
def _reset_reload_menu(runtime):
    _user_tools_module().reset_reload_menu()


@route("account_iptv_menu")
def _account_iptv_menu(runtime):
    _user_tools_module().account_iptv_menu()


def _user_tool_action(runtime, action_name):
    getattr(_user_tools_module(), action_name)()
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("loaded_profiles_view")
def _loaded_profiles_view(runtime):
    _user_tool_action(runtime, "loaded_profiles_view")


@route("pvr_health_report")
def _pvr_health_report(runtime):
    _user_tool_action(runtime, "pvr_health_report_action")


@route("relaunch_kodi")
def _relaunch_kodi(runtime):
    _user_tool_action(runtime, "relaunch_kodi_action")


@route("install_upnext")
def _install_upnext(runtime):
    _user_tool_action(runtime, "install_upnext")


@route("open_upnext_settings")
def _open_upnext_settings(runtime):
    _user_tool_action(runtime, "open_upnext_settings")


@route("live_menu")
def _live_menu(runtime):
    browse = _ctx_required_module("get_live_browse_module")

    browse.live_menu(runtime.args.get("profile_num", [None])[0])


@route("m3u_group")
def _m3u_group(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse.m3u_group(
        args.get("group", [""])[0],
        _int_arg(args, "pnum", 0),
        _int_arg(args, "page", 1),
    )


@route("m3u_simple_section")
def _m3u_simple_section(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse._show_all_m3u_channels(
        _int_arg(args, "pnum", 0),
        _int_arg(args, "page", 1),
        args.get("stype", [""])[0],
    )


@route("m3u_all_channels")
def _m3u_all_channels(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse._show_all_m3u_channels(
        _int_arg(args, "pnum", 0),
        _int_arg(args, "page", 1),
    )


@route("xtream_categories")
def _xtream_categories(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse.xtream_categories(
        args.get("type", ["live"])[0],
        args.get("profile_num", [None])[0],
    )


@route("xtream_streams")
def _xtream_streams(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse.xtream_streams(
        args.get("type", ["live"])[0],
        args.get("cat_id", [""])[0],
        _int_arg(args, "page", 1),
        args.get("adult", ["0"])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("xtream_series")
def _xtream_series(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse.xtream_series(
        args.get("series_id", [""])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("xtream_season")
def _xtream_season(runtime):
    args = runtime.args
    browse = _ctx_required_module("get_live_browse_module")

    browse.xtream_season(
        args.get("series_id", [""])[0],
        args.get("season_num", [""])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("recently_added_menu")
def _recently_added_menu(runtime):
    menus = _ctx_required_module("get_live_menus_module")

    menus.recently_added_menu(runtime.args.get("type", ["movie"])[0])


@route("movies_menu")
def _movies_menu(runtime):
    menus = _ctx_required_module("get_live_menus_module")

    menus.movies_menu(runtime.args.get("profile_num", [None])[0])


@route("series_menu")
def _series_menu(runtime):
    menus = _ctx_required_module("get_live_menus_module")

    menus.series_menu(runtime.args.get("profile_num", [None])[0])


@route("replay_menu")
def _replay_menu(runtime):
    replay = _ctx_required_module("get_live_replay_module")

    replay.replay_menu(runtime.args.get("profile_num", [None])[0])


@route("replay_channels")
def _replay_channels(runtime):
    args = runtime.args
    replay = _ctx_required_module("get_live_replay_module")

    replay.replay_channels(
        args.get("cat_id", [""])[0],
        _int_arg(args, "page", 1),
        args.get("adult", ["0"])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("replay_channel")
def _replay_channel(runtime):
    args = runtime.args
    replay = _ctx_required_module("get_live_replay_module")

    replay.replay_channel(
        args.get("stream_id", [""])[0],
        args.get("epg_id", [""])[0],
        args.get("name", [""])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("replay_play")
def _replay_play(runtime):
    args = runtime.args
    replay = _ctx_required_module("get_live_replay_module")

    replay.replay_play(
        args.get("stream_id", [""])[0],
        args.get("start", [""])[0],
        args.get("duration", [""])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("replay_channel_m3u")
def _replay_channel_m3u(runtime):
    args = runtime.args
    replay = _ctx_required_module("get_live_replay_module")

    replay.replay_channel_m3u(
        args.get("channel_name", [""])[0],
        args.get("epg_id", [""])[0],
        args.get("channel_url", [""])[0],
        args.get("catchup", [""])[0],
        args.get("catchup_source", [""])[0],
        args.get("logo", [""])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("replay_play_m3u")
def _replay_play_m3u(runtime):
    args = runtime.args
    replay = _ctx_required_module("get_live_replay_module")

    replay.replay_play_m3u(
        args.get("channel_name", [""])[0],
        args.get("channel_url", [""])[0],
        args.get("catchup", [""])[0],
        args.get("catchup_source", [""])[0],
        args.get("logo", [""])[0],
        args.get("start_ts", [""])[0],
        args.get("end_ts", [""])[0],
        _int_arg(args, "profile_num", 0),
    )


@route("search_global")
def _search_global(runtime):
    args = runtime.args
    search = _ctx_required_module("get_live_search_module")

    search.search_global(
        args.get("query", [None])[0],
        profile_num=_int_arg(args, "profile_num", None),
        stype=args.get("stype", [None])[0],
    )


@route("search_all_combined")
def _search_all_combined(runtime):
    search = _ctx_required_module("get_live_search_module")

    search.search_all_profiles_combined(runtime.args.get("query", [""])[0])


@route("search_m3u")
def _search_m3u(runtime):
    args = runtime.args
    search = _ctx_required_module("get_live_search_module")

    search.search_m3u(args.get("query", [None])[0], stype=args.get("stype", [None])[0])


@route("refresh_data")
def _refresh_data(runtime):
    profile_refresh = _ctx_required_module("get_user_profile_refresh_module")

    profile_refresh.refresh_data()
    _end_false(runtime)


@route("refresh_profile_menu")
def _refresh_profile_menu(runtime):
    profile_refresh = _ctx_required_module("get_user_profile_refresh_module")

    profile_refresh.refresh_profile_menu()


@route("sports_refresh_profile_menu")
def _sports_refresh_profile_menu(runtime):
    profile_refresh = _ctx_required_module("get_user_profile_refresh_module")

    profile_refresh.sports_refresh_profile_menu()


@route("profile_menu")
def _profile_menu(runtime):
    _user_profiles_module().profile_menu(_int_arg(runtime.args, "pnum", 1))


@route("profiles_search_menu")
def _profiles_search_menu(runtime):
    _user_profiles_module().profiles_search_menu()


@route("manage_active_profiles")
def _manage_active_profiles(runtime):
    _user_profiles_module().manage_active_profiles()


@route("manage_main_menu_items")
def _manage_main_menu_items(runtime):
    _user_profiles_module().manage_main_menu_items()


@route("switch_profile")
def _switch_profile(runtime):
    _user_profiles_module().switch_profile()


@route("open_pvr")
def _open_pvr(runtime):
    _call_ctx("open_pvr")


@route("open_pvr_guide")
def _open_pvr_guide(runtime):
    _call_ctx("open_pvr_guide")


@route("pvr_not_active")
def _pvr_not_active(runtime):
    xbmcgui.Dialog().notification("Xstream Pro", _t(30787), xbmcgui.NOTIFICATION_WARNING, 3000)
    _end_false(runtime)


@route("sync_sports_pvr")
def _sync_sports_pvr(runtime):
    try:
        pvr_sync = _ctx_required_module("get_pvr_sync_module")

        pvr_sync.sync_sports_pvr()
    except Exception as exc:
        _log("Sports PVR sync error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
    _end_false(runtime)


@route("switch_sports_pvr_profile")
def _switch_sports_pvr_profile(runtime):
    pvr_sync = _ctx_required_module("get_pvr_sync_module")

    pvr_sync.switch_sports_pvr_profile()


@route("pvr_favorites_manager")
def _pvr_favorites_manager(runtime):
    _pvr_favorites_module().pvr_favorites_manager(runtime.args.get("group", [None])[0])


@route("pvr_favs_manage_group")
def _pvr_favs_manage_group(runtime):
    _pvr_favorites_module().pvr_favs_manage_group(runtime.args.get("group", [_t(30703) or "Favorites"])[0])


@route("pvr_favs_group_current")
def _pvr_favs_group_current(runtime):
    _pvr_favorites_module().pvr_favs_group_current(runtime.args.get("group", [_t(30703) or "Favorites"])[0])


@route("pvr_favs_group_search")
def _pvr_favs_group_search(runtime):
    args = runtime.args
    _pvr_favorites_module().pvr_favs_group_search(
        args.get("group", [_t(30703) or "Favorites"])[0],
        query=args.get("query", [""])[0],
        new_search=str(args.get("new_search", ["false"])[0]).lower() == "true",
        prompt=str(args.get("prompt", ["true"])[0]).lower() != "false",
    )
    _end_false(runtime)


@route("pvr_favs_manage_cat")
def _pvr_favs_manage_cat(runtime):
    args = runtime.args
    _pvr_favorites_module().pvr_favs_manage_cat(
        args.get("cat_id", [""])[0],
        args.get("cat_name", [""])[0],
        args.get("group", [_t(30703) or "Favorites"])[0],
    )
    _end_false(runtime)


@route("pvr_favs_new_group")
def _pvr_favs_new_group(runtime):
    dialog = xbmcgui.Dialog()
    name = dialog.input(_t(30147))
    if name:
        groups = _call_ctx("_pvr_favs_load_all")
        if name in groups:
            dialog.notification("Xstream Pro", _t(30125))
        else:
            groups[name] = []
            _call_ctx("_pvr_favs_save_all", groups)
            dialog.notification("Xstream Pro", _t(30126, name))
            xbmc.sleep(_call_ctx("_tvos_sleep", 1500))
            dialog.ok("Xstream Pro", _t(30727))
            xbmc.executebuiltin("Container.Refresh")
    _end_false(runtime)


@route("pvr_favs_rename_group")
def _pvr_favs_rename_group(runtime):
    old_name = runtime.args.get("group", [""])[0]
    dialog = xbmcgui.Dialog()
    new_name = dialog.input(_t(30148), defaultt=old_name)
    if new_name and new_name != old_name:
        groups = _call_ctx("_pvr_favs_load_all")
        if new_name in groups:
            dialog.notification("Xstream Pro", _t(30125))
        elif old_name in groups:
            items = groups.pop(old_name)
            groups[new_name] = items
            _call_ctx("_pvr_favs_save_all", groups)
            _call_ctx("_sync_pvr_favorites_safe")
            dialog.notification("Xstream Pro", _t(30178, new_name))
            xbmc.executebuiltin("Container.Refresh")
            options = [_t(30720), _t(30165), _t(30403)]
            choice = dialog.select(_t(30732, new_name), options)
            if choice == 0:
                try:
                    _call_ctx("_sync_pvr_force")
                except Exception as exc:
                    _log("PVR reload error: {0}".format(exc))
                    _log("Traceback: {0}".format(traceback.format_exc()))
                dialog.notification("Xstream Pro", _t(30281))
            elif choice == 1:
                _call_ctx("_restart_or_prompt")
    _end_false(runtime)


@route("pvr_favs_delete_group")
def _pvr_favs_delete_group(runtime):
    group_name = runtime.args.get("group", [""])[0]
    dialog = xbmcgui.Dialog()
    if dialog.yesno(_t(30038), _t(30252, group_name)):
        groups = _call_ctx("_pvr_favs_load_all")
        if group_name in groups:
            del groups[group_name]
            _call_ctx("_pvr_favs_save_all", groups)
            _call_ctx("_sync_pvr_favorites_safe")
            dialog.notification("Xstream Pro", _t(30179, group_name))
            xbmc.executebuiltin("Container.Refresh")
    _end_false(runtime)


@route("pvr_fav_add")
def _pvr_fav_add(runtime):
    args = runtime.args
    sid = args.get("stream_id", [""])[0]
    name = args.get("name", [""])[0]
    icon = args.get("icon", [""])[0]
    group = args.get("group", [_t(30703) or "Favorites"])[0]
    channel = {"stream_id": sid, "name": name, "stream_icon": icon}
    try:
        creds = _call_ctx("_get_pvr_credentials")
        streams = _call_ctx(
            "_get_cached_xtream_streams",
            creds.get("xtream_url", ""),
            creds.get("xtream_username", ""),
            creds.get("xtream_password", ""),
            "live",
        )
        for stream in streams or []:
            if str(stream.get("stream_id", "")) == sid:
                channel.update(stream)
                break
    except Exception as exc:
        _log("PVR favorite metadata lookup warning: {0}".format(exc))
    if _call_ctx("_pvr_favs_add", channel, group):
        _call_ctx("_sync_pvr_favorites_safe")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30084).format(group))
        xbmc.sleep(_call_ctx("_tvos_sleep", 1500))
        xbmcgui.Dialog().ok("Xstream Pro", _t(30727))
        xbmc.executebuiltin("Container.Refresh")
    _end_false(runtime)


@route("pvr_fav_remove")
def _pvr_fav_remove(runtime):
    args = runtime.args
    sid = args.get("stream_id", [""])[0]
    group = args.get("group", [_t(30703) or "Favorites"])[0]
    if _call_ctx("_pvr_favs_remove", sid, group):
        _call_ctx("_sync_pvr_favorites_safe")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30085).format(group))
        xbmc.executebuiltin("Container.Refresh")
    _end_false(runtime)


@route("sports_pvr_favs_manage_group")
def _sports_pvr_favs_manage_group(runtime):
    _pvr_favorites_module().sports_pvr_favs_manage_group(runtime.args.get("group", ["Favorites"])[0])


@route("sports_pvr_favs_group_current")
def _sports_pvr_favs_group_current(runtime):
    _pvr_favorites_module().sports_pvr_favs_group_current(runtime.args.get("group", ["Favorites"])[0])


@route("sports_pvr_favs_group_search")
def _sports_pvr_favs_group_search(runtime):
    args = runtime.args
    _pvr_favorites_module().sports_pvr_favs_group_search(
        args.get("group", ["Favorites"])[0],
        query=args.get("query", [""])[0],
        new_search=str(args.get("new_search", ["false"])[0]).lower() == "true",
        prompt=str(args.get("prompt", ["true"])[0]).lower() != "false",
    )
    _end_false(runtime)


@route("sports_pvr_favs_manage_country")
def _sports_pvr_favs_manage_country(runtime):
    args = runtime.args
    _pvr_favorites_module().sports_pvr_favs_manage_country(
        args.get("country", ["Other Countries"])[0],
        args.get("group", ["Favorites"])[0],
    )
    _end_false(runtime)


def _sports_pvr_action(runtime, action_name):
    getattr(_pvr_favorites_module(), action_name)()
    _end_false(runtime)


@route("sports_pvr_favs_new_group")
def _sports_pvr_favs_new_group(runtime):
    _sports_pvr_action(runtime, "sports_pvr_favs_new_group")


@route("sports_pvr_favs_rename_group")
def _sports_pvr_favs_rename_group(runtime):
    _sports_pvr_action(runtime, "sports_pvr_favs_rename_group")


@route("sports_pvr_favs_delete_group")
def _sports_pvr_favs_delete_group(runtime):
    _sports_pvr_action(runtime, "sports_pvr_favs_delete_group")


@route("sports_pvr_favorites_manager")
def _sports_pvr_favorites_manager(runtime):
    _pvr_favorites_module().sports_pvr_favorites_manager(runtime.args.get("group", [None])[0])


@route("sports_pvr_favs_manage")
def _sports_pvr_favs_manage(runtime):
    _pvr_favorites_module().sports_pvr_favs_manage(runtime.args.get("group", ["Favorites"])[0])


@route("sports_pvr_fav_remove")
def _sports_pvr_fav_remove(runtime):
    args = runtime.args
    _pvr_favorites_module().sports_pvr_fav_remove(
        args.get("stream_id", [""])[0],
        args.get("group", ["Favorites"])[0],
    )
    _end_false(runtime)


@route("user_playlists_menu")
def _user_playlists_menu(runtime):
    _call_ctx("user_playlists_menu")


@route("trakt_restore_credentials")
def _trakt_restore_credentials(runtime):
    _user_tools_module().trakt_restore_credentials_action()


@route("trakt_clear_cache")
def _trakt_clear_cache(runtime):
    _user_tools_module().trakt_clear_cache_action()


@route("hidden_items_all")
def _hidden_items_all(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    args = runtime.args
    hidden_menu_module.hidden_items_all_action(
        args.get("stype", ["live"])[0],
        args.get("pnum", [None])[0] or runtime.pm.active,
    )


@route("pvr_osd_left")
def _pvr_osd_left(runtime):
    _pvr_osd_key_action("left")
    _end_false(runtime)


@route("pvr_osd_right")
def _pvr_osd_right(runtime):
    _pvr_osd_key_action("right")
    _end_false(runtime)


@route("settings")
def _settings(runtime):
    settings_routes = _ctx_required_module("get_user_settings_module")

    settings_routes.settings()


@route("view_changelog")
def _view_changelog(runtime):
    _user_tools_module().view_changelog()
    _end_false(runtime)


@route("test_connection")
def _test_connection(runtime):
    _call_ctx("test_connection")
    _end_false(runtime)


@route("account_info")
def _account_info(runtime):
    _call_ctx("account_info")
    _end_false(runtime)


@route("check_update")
def _check_update(runtime):
    from updater import check_and_install_update

    check_and_install_update()
    _end_false(runtime)


@route("revert_version")
def _revert_version(runtime):
    from updater import revert_version_menu

    revert_version_menu()
    _end_false(runtime)


@route("toggle_setting")
def _toggle_setting(runtime):
    key = runtime.args.get("key", [""])[0]
    addon = runtime.addon
    if key:
        current = addon.getSetting(key).lower() == "true"
        addon.setSetting(key, "false" if current else "true")
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            _t(30306, key.replace("_", " ").title(), _t(30371 if current else 30370)),
        )
        xbmc.executebuiltin("Container.Refresh")
    _end_false(runtime)


def _safe_action(runtime, action_name, log_label, notify_id=None):
    try:
        _call_ctx(action_name)
    except Exception as exc:
        _log("{0} error: {1}".format(log_label, exc))
        if notify_id is not None:
            xbmcgui.Dialog().notification("Xstream Pro", _t(notify_id))
    _end_false(runtime)


@route("clear_cache_menu")
def _clear_cache_menu(runtime):
    _safe_action(runtime, "clear_cache_menu", "Clear cache menu")


@route("clear_epg_cache")
def _clear_epg_cache(runtime):
    _safe_action(runtime, "clear_epg_cache", "Clear EPG cache")


@route("reset_pvr_epg_db")
def _reset_pvr_epg_db(runtime):
    try:
        _call_ctx("reset_pvr_epg_db_action")
    except Exception as exc:
        _log("Reset PVR EPG DB error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
    _end_false(runtime)


@route("sync_pvr_epg_only")
def _sync_pvr_epg_only(runtime):
    try:
        if xbmcgui.Dialog().yesno(
            "Xstream Pro",
            "Sync PVR EPG now?\n\nThis rebuilds the EPG for the currently active PVR scope (Live TV or Sports).",
            yeslabel="Sync EPG",
            nolabel="Cancel",
        ):
            _call_ctx("_sync_pvr_epg_only", offer_reload=True)
    except Exception as exc:
        _log("PVR EPG-only sync route error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
    _end_false(runtime)


@route("schedule_live_epg_repair")
def _schedule_live_epg_repair_route(runtime):
    profile_num = _int_arg(runtime.args, "profile", 1)
    try:
        from addon import _schedule_live_epg_repair
        _schedule_live_epg_repair(profile_num)
    except Exception:
        pass


@route("schedule_sports_epg_repair")
def _schedule_sports_epg_repair_route(runtime):
    profile_num = _int_arg(runtime.args, "profile", 1)
    try:
        from addon import _schedule_sports_epg_repair
        _schedule_sports_epg_repair(profile_num)
    except Exception:
        pass


@route("force_reload_pvr")
def _force_reload_pvr(runtime):
    try:
        if xbmcgui.Dialog().yesno("Xstream Pro", _t(30820)):
            ok = _call_ctx("_sync_pvr_force")
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                _t(30281) if ok else _t(30082),
            )
    except Exception as exc:
        _log("Force reload PVR error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
    _end_false(runtime)


@route("tmdb_series_action")
def _tmdb_series_action(runtime):
    sources = _ctx_required_module("get_live_sources_module")

    sources.tmdb_series_action()
    _end_false(runtime)


@route("tmdb_source_action")
def _tmdb_source_action(runtime):
    sources = _ctx_required_module("get_live_sources_module")

    sources.tmdb_source_action()
    _end_false(runtime)


@route("source_select")
def _source_select(runtime):
    sources = _ctx_required_module("get_live_sources_module")

    sources.source_select()


@route("source_autoplay")
def _source_autoplay(runtime):
    sources = _ctx_required_module("get_live_sources_module")

    sources.source_autoplay()


@route("resolve_source")
def _resolve_source(runtime):
    sources = _ctx_required_module("get_live_sources_module")

    sources.resolve_source()


@route("play_stream")
def _play_stream(runtime):
    args = runtime.args
    playback = _ctx_required_module("get_live_playback_module")

    pnum = _int_arg(args, "profile_num", runtime.pm.active)
    raw_kodi_props = args.get("kodi_props", [""])[0]
    kodi_props = None
    if raw_kodi_props:
        try:
            kodi_props = json.loads(raw_kodi_props)
        except Exception:
            pass
    playback.play_stream(
        args.get("url", [""])[0],
        args.get("name", [""])[0],
        args.get("title", [""])[0],
        args.get("plot", [""])[0],
        args.get("icon", [""])[0],
        args.get("stype", ["live"])[0],
        args.get("series_id", [""])[0],
        args.get("season_num", [""])[0],
        args.get("ep_id", [""])[0],
        profile_num=pnum,
        kodi_props=kodi_props,
        stream_ua=args.get("stream_ua", [""])[0],
        resume_pos=_int_float_arg(args, "resume_pos", 0),
        resume_total=_int_float_arg(args, "resume_total", 0),
        tmdb_id=args.get("tmdb_id", [""])[0],
        stream_ref=args.get("stream_ref", [""])[0],
    )


@route("clear_all_caches")
def _clear_all_caches(runtime):
    try:
        count = _call_ctx("_cache_clear_all")
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            _t(30832) + " ({0} files)".format(count),
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )
    except Exception as exc:
        _log("Clear cache error: {0}".format(exc))
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Clear cache failed",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
    _end_false(runtime)


@route("tmdb_rebuild_provider_cache")
def _tmdb_rebuild_provider_cache(runtime):
    provider_availability = _ctx_required_module("get_provider_availability_module")

    try:
        provider_availability._rebuild_provider_availability_cache(show_progress=True)
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Provider cache rebuilt",
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )
    except Exception as exc:
        _log("Provider cache rebuild error: {0}".format(exc))
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Provider cache rebuild failed",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
    _end_false(runtime)


@route("clear_cache")
def _clear_cache(runtime):
    try:
        import cache

        cache.clear_namespace("tmdb_http")
        cache.clear_namespace("tmdb_titles")
        cache.clear_namespace("tmdb_collections")
        cache.clear_namespace("tmdb_company_logo")
        cache.clear_namespace("provider_exact_pages")
        cache.clear_namespace("provider_filter")
        cache.clear_namespace("trakt_auth")
        cache.clear_namespace("trakt_public")
        try:
            profile_path = xbmcvfs.translatePath(runtime.addon.getAddonInfo("profile"))
            pa_path = os.path.join(profile_path, "tmdb_provider_availability.json")
            if os.path.exists(pa_path):
                os.remove(pa_path)
        except Exception:
            pass
        _log("Cleared TMDb/Trakt cache")
    except Exception as exc:
        _log("Clear direct cache error: {0}".format(exc))
    try:
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            _t(30832),
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )
    except Exception:
        pass
    _end_false(runtime)


@route("clear_background")
def _clear_background(runtime):
    artwork_module = _ctx_required_module("get_user_artwork_module")

    try:
        if artwork_module.clear_background():
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Background cleared",
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Failed to clear background",
                xbmcgui.NOTIFICATION_WARNING,
                3000,
            )
    except Exception as exc:
        _log("Clear background error: {0}".format(exc))
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Clear background failed",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
    _end_false(runtime)


@route("restore_background")
def _restore_background(runtime):
    artwork_module = _ctx_required_module("get_user_artwork_module")

    try:
        if artwork_module.restore_background():
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Addon background restored",
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Failed to restore background",
                xbmcgui.NOTIFICATION_WARNING,
                3000,
            )
    except Exception as exc:
        _log("Restore background error: {0}".format(exc))
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Restore background failed",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
    _end_false(runtime)


@route("backup_settings")
def _backup_settings(runtime):
    backup_module = _ctx_required_module("get_user_backup_module")

    try:
        backup_module.backup_settings()
    except Exception as exc:
        _log("Backup settings error: {0}".format(exc))
        xbmcgui.Dialog().notification("Xstream Pro", _t(30090))
    _end_false(runtime)


@route("restore_settings")
def _restore_settings(runtime):
    backup_module = _ctx_required_module("get_user_backup_module")

    try:
        backup_module.restore_settings()
    except Exception as exc:
        _log("Restore settings error: {0}".format(exc))
        xbmcgui.Dialog().notification("Xstream Pro", _t(30092))
    _end_false(runtime)


@route("view_backup_path")
def _view_backup_path(runtime):
    backup_module = _ctx_required_module("get_user_backup_module")

    try:
        backup_module.view_backup_path()
    except Exception as exc:
        _log("View backup path error: {0}".format(exc))
    _end_false(runtime)


@route("change_backup_folder")
def _change_backup_folder_legacy(runtime):
    backup_module = _ctx_required_module("get_user_backup_module")

    try:
        backup_module.change_backup_folder()
    except Exception as exc:
        _log("Change backup folder error: {0}".format(exc))
        xbmcgui.Dialog().notification("Xstream Pro", _t(30790))
    _end_false(runtime)


@route("force_reload_epg")
def _force_reload_epg(runtime):
    try:
        addon = runtime.addon
        selected = _call_ctx("_select_profile_or_all", allow_all=True)
        if selected is None:
            pass
        elif selected == "all":
            pd = xbmcgui.DialogProgress()
            pd.create("Xstream Pro", _t(30289))
            try:
                enabled = [
                    i
                    for i in range(1, 11)
                    if addon.getSetting("profile_{0}_enabled".format(i)) == "true"
                ]
                total = len(enabled) if enabled else 1
                scope = _call_ctx("_current_pvr_instance_scope")
                for idx, i in enumerate(enabled):
                    if pd.iscanceled():
                        break
                    pct = int((idx / total) * 90)
                    pd.update(pct, _t(31442, i))
                    _call_ctx("EPG", addon, profile_num=i).fetch()
                if scope in ("main", "mixed", "none"):
                    pnum = _call_ctx("_get_pvr_profile_num")
                    if not any(str(i) == str(pnum) for i in enabled):
                        pd.update(91, _t(31442, pnum))
                        _call_ctx("EPG", addon, profile_num=int(pnum)).fetch()
                    pd.update(93, _t(31443))
                    _call_ctx("_export_pvr_epg", force_fetch=False)
                if scope in ("sports", "mixed", "none"):
                    if addon.getSetting("sports_pvr_enabled").lower() == "true":
                        sports_pnum = _call_ctx("_get_sports_pvr_profile_num")
                        if not any(str(i) == str(sports_pnum) for i in enabled):
                            pd.update(94, _t(31442, sports_pnum))
                            _call_ctx("EPG", addon, profile_num=int(sports_pnum)).fetch()
                        pd.update(96, _t(31445))
                        sports_channels = _call_ctx("_export_sports_pvr_m3u")
                        if sports_channels:
                            _call_ctx(
                                "_export_sports_pvr_epg_for_profile",
                                sports_pnum,
                                sports_channels,
                                force_fetch=False,
                            )
                        else:
                            _log("Reload EPG: Sports PVR enabled but no Sports channels exported")
                pd.update(100, _t(30563))
            finally:
                pd.close()
            _call_ctx("_trigger_pvr_epg_reload")
            xbmcgui.Dialog().notification("Xstream Pro", _t(30280))
        else:
            pd = xbmcgui.DialogProgress()
            pd.create("Xstream Pro", _t(30289))
            try:
                scope = _call_ctx("_current_pvr_instance_scope")
                pd.update(30, _t(31444))
                _call_ctx("EPG", addon, profile_num=int(selected)).fetch()
                if scope in ("main", "mixed", "none") and str(selected) == str(_call_ctx("_get_pvr_profile_num")):
                    pd.update(60, _t(31445))
                    _call_ctx("_export_pvr_epg", force_fetch=False)
                    _call_ctx("_trigger_pvr_epg_reload")
                if scope in ("sports", "mixed", "none") and addon.getSetting("sports_pvr_enabled").lower() == "true":
                    sports_pnum = _call_ctx("_get_sports_pvr_profile_num")
                    if str(selected) == str(sports_pnum):
                        sports_channels = _call_ctx("_export_sports_pvr_m3u")
                        if sports_channels:
                            pd.update(80, _t(31445))
                            _call_ctx(
                                "_export_sports_pvr_epg_for_profile",
                                sports_pnum,
                                sports_channels,
                                force_fetch=False,
                            )
                            _call_ctx("_trigger_pvr_epg_reload")
                pd.update(100, _t(30563))
            finally:
                pd.close()
            xbmcgui.Dialog().notification("Xstream Pro", _t(30280))
    except Exception as exc:
        _log("Force reload EPG error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
    _end_false(runtime)


@route("toggle_tmdb_watched")
def _toggle_tmdb_watched(runtime):
    from history import WatchedEpisodes, WatchedMovies

    args = runtime.args
    tmdb_id = args.get("tmdb_id", [""])[0]
    tmdb_type = args.get("tmdb_type", [""])[0]
    season = args.get("season", [""])[0]
    episode = args.get("episode", [""])[0]
    pnum = int(runtime.pm.active) if runtime.pm.active and str(runtime.pm.active).isdigit() else 1
    if tmdb_id and tmdb_type == "movie":
        wm = WatchedMovies(runtime.addon, profile_num=pnum)
        if wm.is_watched(tmdb_id):
            wm.mark_unwatched(tmdb_id)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31121))
        else:
            wm.mark_watched(tmdb_id)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31120))
    elif tmdb_id and tmdb_type == "tv" and season and episode:
        we = WatchedEpisodes(runtime.addon, profile_num=pnum)
        if we.is_watched(tmdb_id, season, episode):
            we.mark_unwatched(tmdb_id, season, episode)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31121))
        else:
            we.mark_watched(tmdb_id, season, episode)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31120))
    elif tmdb_id and tmdb_type == "tv" and season:
        wm = WatchedMovies(runtime.addon, profile_num=pnum)
        season_key = "season:{0}:{1}".format(tmdb_id, season)
        if wm.is_watched(season_key):
            wm.mark_unwatched(season_key)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31121))
        else:
            wm.mark_watched(season_key)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31120))
    elif tmdb_id and tmdb_type == "tv":
        wm = WatchedMovies(runtime.addon, profile_num=pnum)
        show_key = "tvshow:{0}".format(tmdb_id)
        if wm.is_watched(show_key):
            wm.mark_unwatched(show_key)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31121))
        else:
            wm.mark_watched(show_key)
            xbmcgui.Dialog().notification("Xstream Pro", _t(31120))
    xbmc.executebuiltin("Container.Refresh")
    if tmdb_id and tmdb_type == "tv":
        xbmc.executebuiltin("Container.Update(plugin://plugin.video.xstream-pro/?mode=xstream_tmdb_seasons&tmdb_id={0}&tmdb_type=tv,replace)".format(tmdb_id))
    _end_false(runtime)


@route("favorites_menu")
def _favorites_menu(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    args = runtime.args
    favorites_menu_module.favorites_menu(
        args.get("folder", [None])[0],
        args.get("stype_filter", [None])[0],
    )


@route("toggle_fav")
def _toggle_fav(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    args = runtime.args
    favorites_menu_module.toggle_favorite(
        args.get("id", [""])[0],
        args.get("name", [""])[0],
        args.get("stype", ["live"])[0],
        args.get("icon", [""])[0],
        args.get("url", [""])[0],
        args.get("epg_id", [""])[0],
        args.get("folder", [_t(30009) or "Favorites"])[0],
        args.get("catchup", [""])[0],
        args.get("catchup_source", [""])[0],
        args.get("catchup_days", [""])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("toggle_profile_fav")
def _toggle_profile_fav(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    args = runtime.args
    favorites_menu_module.toggle_profile_favorite(
        args.get("id", [""])[0],
        args.get("name", [""])[0],
        args.get("stype", ["live"])[0],
        args.get("icon", [""])[0],
        args.get("url", [""])[0],
        args.get("epg_id", [""])[0],
        args.get("pnum", [1])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("fav_new_folder")
def _fav_new_folder(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    favorites_menu_module.fav_new_folder()
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("fav_rename_folder")
def _fav_rename_folder(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    favorites_menu_module.fav_rename_folder(runtime.args.get("folder", [""])[0])
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("fav_delete_folder")
def _fav_delete_folder(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    favorites_menu_module.fav_delete_folder(runtime.args.get("folder", [""])[0])
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("fav_move")
def _fav_move(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    args = runtime.args
    favorites_menu_module.fav_move(
        args.get("id", [""])[0],
        args.get("from_folder", [_t(30009) or "Favorites"])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("export_favorites")
def _export_favorites(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    favorites_menu_module.export_favorites(runtime.args.get("folder", [None])[0])
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("fav_remove")
def _fav_remove(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    args = runtime.args
    favorites_menu_module.fav_remove(
        args.get("id", [""])[0],
        args.get("folder", ["__all__"])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("fav_remove_by_type")
def _fav_remove_by_type(runtime):
    favorites_menu_module = _ctx_required_module("get_menus_favorites_module")

    args = runtime.args
    favorites_menu_module.fav_remove_by_type(
        args.get("folder", [""])[0],
        args.get("stype", [""])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("manage_content_dialog")
def _manage_content_dialog(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    args = runtime.args
    hidden_menu_module.manage_content_dialog(
        args.get("stype", ["live"])[0],
        args.get("pnum", [None])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("manage_load_content")
def _manage_load_content(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    hidden_menu_module._manage_load_content_toggles(
        _int_arg(runtime.args, "pnum", 1)
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("manage_content_select")
def _manage_content_select(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    hidden_menu_module._manage_content_select(_int_arg(runtime.args, "pnum", 1))
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("manage_hidden_subcats")
def _manage_hidden_subcats(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    args = runtime.args
    hidden_menu_module.manage_hidden_subcats(
        args.get("stype", ["live"])[0],
        args.get("pnum", [None])[0],
    )


@route("hide_m3u_item_action")
def _hide_m3u_item_action(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    args = runtime.args
    hidden_menu_module.hide_m3u_item_action(
        args.get("stype", ["live"])[0],
        args.get("item_id", [""])[0],
        args.get("item_name", [""])[0],
        args.get("pnum", [None])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("hide_subcat_action")
def _hide_subcat_action(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    args = runtime.args
    hidden_menu_module.hide_subcat_action(
        args.get("stype", ["live"])[0],
        args.get("cat_id", [""])[0],
        args.get("cat_name", [""])[0],
        args.get("pnum", [None])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("hide_all_subcats")
def _hide_all_subcats(runtime):
    hidden_menu_module = _ctx_required_module("get_menus_hidden_module")

    args = runtime.args
    hidden_menu_module.hide_all_subcats(
        args.get("stype", ["live"])[0],
        args.get("action", ["hide"])[0],
        args.get("pnum", [None])[0],
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("toggle_provider_episode_watched")
def _toggle_provider_episode_watched(runtime):
    from history import WatchedEpisodes
    recent_menu_module = _ctx_required_module("get_menus_recent_module")

    args = runtime.args
    recent_menu_module.toggle_provider_episode_watched(
        args.get("series_id", [""])[0],
        args.get("season_num", [""])[0],
        args.get("ep_id", [""])[0],
        WatchedEpisodes,
        _int_arg(args, "profile_num", None),
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("toggle_provider_movie_watched")
def _toggle_provider_movie_watched(runtime):
    from history import WatchedMovies
    recent_menu_module = _ctx_required_module("get_menus_recent_module")

    args = runtime.args
    recent_menu_module.toggle_provider_movie_watched(
        args.get("stream_id", [""])[0],
        WatchedMovies,
        _int_arg(args, "profile_num", None),
    )
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("tmdb_local_recent")
def _tmdb_local_recent(runtime):
    from history import WatchHistory
    recent_menu_module = _ctx_required_module("get_menus_recent_module")

    recent_menu_module.tmdb_local_recent(
        runtime.args.get("tmdb_type", ["movie"])[0],
        WatchHistory,
    )


@route("tmdb_local_in_progress")
def _tmdb_local_in_progress(runtime):
    from history import ResumePoints
    recent_menu_module = _ctx_required_module("get_menus_recent_module")

    recent_menu_module.tmdb_local_in_progress(
        runtime.args.get("tmdb_type", ["movie"])[0],
        ResumePoints,
    )


def _register_tmdb_route(mode, method_name, arg_style="none"):
    @route(mode)
    def _handler(runtime, method_name=method_name, arg_style=arg_style):
        module = _setup_module("setup_tmdb_routes", "get_tmdb_routes")
        if not module:
            return
        method = getattr(module, method_name)
        if arg_style == "args":
            method(runtime.args)
        elif arg_style == "tmdb_type":
            method(runtime.args.get("tmdb_type", ["movie"])[0])
        else:
            method()


def _register_sports_route(mode, method_name, arg_style="none", end_false=False):
    @route(mode)
    def _handler(runtime, method_name=method_name, arg_style=arg_style, end_false=end_false):
        module = _setup_module("setup_sports_routes", "get_sports_routes")
        if not module:
            xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)
            return
        method = getattr(module, method_name)
        if arg_style == "args":
            method(runtime.args)
        else:
            method()
        if end_false:
            xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


def _register_sports_results_route(mode, method_name, arg_style="none"):
    @route(mode)
    def _handler(runtime, method_name=method_name, arg_style=arg_style):
        module = _setup_module("setup_sports_results_routes", "get_sports_results_routes")
        if not module:
            return
        method = getattr(module, method_name)
        if arg_style == "args":
            method(runtime.args)
        else:
            method()


_TMDB_ROUTE_SPECS = [
    ("xstream_tmdb_movies_menu", "movies_menu", "none"),
    ("xstream_tmdb_tvshows_menu", "tvshows_menu", "none"),
    ("xstream_tmdb_animation_menu", "animation_menu", "none"),
    ("xstream_tmdb_animation_anime_menu", "animation_anime_menu", "none"),
    ("xstream_tmdb_animation_movies_menu", "animation_movies_menu", "none"),
    ("xstream_tmdb_animation_tv_menu", "animation_tv_menu", "none"),
    ("xstream_tmdb_animation_kids_menu", "animation_kids_menu", "none"),
    ("xstream_tmdb_animation_studios_menu", "animation_studios_menu", "args"),
    ("xstream_tmdb_animation_collections_menu", "animation_collections_menu", "none"),
    ("xstream_tmdb_animation_search_root", "animation_search_root", "none"),
    ("xstream_tmdb_animation_random_menu", "animation_random_menu", "none"),
    ("xstream_tmdb_animation_list", "animation_list_route", "args"),
    ("xstream_tmdb_animation_company", "animation_company_route", "args"),
    ("xstream_tmdb_animation_network", "animation_network_route", "args"),
    ("xstream_tmdb_animation_movie_collections", "animation_movie_collections_menu", "args"),
    ("xstream_tmdb_animation_collection_search", "animation_collection_search_route", "args"),
    ("xstream_tmdb_animation_collection", "animation_collection_route", "args"),
    ("xstream_tmdb_animation_search", "animation_search_route", "args"),
    ("xstream_tmdb_animation_random", "animation_random_route", "args"),
    ("xstream_tmdb_people_menu", "people_menu", "none"),
    ("xstream_tmdb_lists_menu", "lists_menu", "none"),
    ("xstream_tmdb_trakt_menu", "trakt_menu", "none"),
    ("xstream_trakt_authorize", "trakt_authorize_route", "args"),
    ("xstream_trakt_revoke", "trakt_revoke_route", "args"),
    ("xstream_trakt_list", "trakt_list_route", "args"),
    ("xstream_trakt_playback", "trakt_playback_route", "args"),
    ("xstream_trakt_lists", "trakt_lists_route", "args"),
    ("xstream_trakt_list_items", "trakt_list_items_route", "args"),
    ("xstream_trakt_calendar", "trakt_calendar_route", "args"),
    ("xstream_trakt_calendar_endpoint", "trakt_calendar_endpoint_route", "args"),
    ("xstream_trakt_next_episodes", "trakt_next_episodes_route", "args"),
    ("xstream_trakt_public", "trakt_public_route", "args"),
    ("xstream_trakt_item_action", "trakt_item_action_route", "args"),
    ("xstream_tmdb_collection_search", "collection_search_route", "args"),
    ("xstream_tmdb_collections_menu", "collections_menu", "none"),
    ("xstream_tmdb_collection_list", "collection_list_route", "args"),
    ("xstream_tmdb_collection_browse", "collection_browse_route", "args"),
    ("xstream_tmdb_saved_collections", "saved_collections_menu", "none"),
    ("xstream_tmdb_save_collection", "save_collection_action", "args"),
    ("xstream_tmdb_unsave_collection", "unsave_collection_action", "args"),
    ("xstream_tmdb_tv_collections_menu", "tv_collections_menu", "none"),
    ("xstream_tmdb_tv_universes_menu", "tv_universes_menu", "args"),
    ("xstream_tmdb_tv_collection", "tv_collection_route", "args"),
    ("xstream_tmdb_company_search", "company_search_route", "args"),
    ("xstream_tmdb_keyword_search", "keyword_search_route", "args"),
    ("xstream_tmdb_randomised_menu", "randomised_menu", "none"),
    ("xstream_tmdb_random_genre", "random_genre_route", "args"),
    ("xstream_tmdb_random_keyword", "random_keyword_route", "args"),
    ("xstream_trakt_recommendations", "trakt_recommendations_route", "args"),
    ("xstream_trakt_random_public", "trakt_random_public_route", "args"),
    ("xstream_trakt_random_list", "trakt_random_list_route", "args"),
    ("xstream_tmdb_discover_menu", "discover_menu", "none"),
    ("tmdb_discover_menu", "discover_menu", "none"),
    ("xstream_tmdb_discover_builder", "discover_builder_menu", "args"),
    ("xstream_tmdb_discover_builder_set", "discover_builder_set_route", "args"),
    ("xstream_tmdb_discover_builder_add", "discover_builder_add_route", "args"),
    ("xstream_tmdb_discover_builder_quick", "discover_builder_quick_route", "args"),
    ("xstream_tmdb_discover_builder_run", "discover_builder_run_route", "args"),
    ("xstream_tmdb_discover_builder_show", "discover_builder_show_route", "args"),
    ("xstream_tmdb_discover_builder_save", "discover_builder_save_route", "args"),
    ("xstream_tmdb_discover_history", "discover_history_menu", "none"),
    ("xstream_tmdb_discover_history_load", "discover_history_load_route", "args"),
    ("xstream_tmdb_discover_history_delete", "discover_history_delete_route", "args"),
    ("xstream_tmdb_search_menu", "search_menu", "none"),
    ("xstream_tmdb_list", "list_route", "args"),
    ("xstream_tmdb_search", "search_route", "args"),
    ("xstream_tmdb_discover", "discover_route", "args"),
    ("xstream_tmdb_genres", "genres_route", "args"),
    ("xstream_tmdb_watch_providers", "watch_providers_route", "args"),
    ("xstream_tmdb_years_menu", "years_menu", "tmdb_type"),
    ("xstream_tmdb_decades_menu", "decades_menu", "tmdb_type"),
    ("xstream_tmdb_seasons", "seasons_route", "args"),
    ("xstream_tmdb_episodes", "episodes_route", "args"),
    ("xstream_tmdb_similar", "related_route", "args"),
    ("xstream_tmdb_recommendations", "related_route", "args"),
    ("xstream_tmdb_collection", "collection_route", "args"),
    ("xstream_tmdb_collection_from_movie", "collection_from_movie_route", "args"),
    ("xstream_tmdb_trailer", "trailer_route", "args"),
    ("xstream_tmdb_people", "people_route", "args"),
    ("xstream_tmdb_person_credits", "person_credits_route", "args"),
    ("xstream_tmdb_because_watched", "because_watched_route", "args"),
]

for _mode, _method, _style in _TMDB_ROUTE_SPECS:
    _register_tmdb_route(_mode, _method, _style)


_SPORTS_ROUTE_SPECS = [
    ("sports_menu", "sports_menu", "none", False),
    ("sports_open_pvr", "open_pvr", "args", False),
    ("sports_open_pvr_guide", "open_pvr_guide", "args", False),
    ("sports_events_ppv", "sports_events_ppv_menu", "none", False),
    ("sports_news", "sports_news_menu", "none", False),
    ("sports_profiles", "sports_profiles_menu", "none", False),
    ("sports_profile", "sports_profile_menu", "args", False),
    ("sports_profiles_by_profile", "sports_profiles_by_profile", "none", False),
    ("sports_provider_groups", "sports_provider_groups", "args", False),
    ("sports_countries", "sports_countries", "args", False),
    ("sports_channels", "sports_channels", "args", False),
    ("sports_replay", "sports_replay_menu", "none", False),
    ("sports_replay_profile", "sports_replay_profile", "args", False),
    ("sports_replay_provider_groups", "sports_replay_provider_groups", "args", False),
    ("sports_replay_countries", "sports_replay_countries", "args", False),
    ("sports_replay_channels", "sports_replay_channels", "args", False),
    ("sports_search_menu", "sports_search_menu", "none", False),
    ("sports_search", "sports_search", "args", False),
    ("sports_favorites", "sports_favorites", "none", False),
    ("sports_loaded_profiles", "sports_loaded_profiles", "none", False),
    ("sports_pvr_status", "sports_pvr_status", "none", True),
    ("sports_review_detected", "sports_review_detected", "args", False),
    ("sports_clear_cache", "sports_clear_cache", "none", True),
    ("sports_tools", "sports_tools", "none", False),
    ("sports_manage_detected_channels", "sports_manage_detected_channels", "none", False),
    ("sports_manage_detected_review_countries", "sports_manage_detected_review_countries", "none", False),
    ("sports_manage_detected_add_countries", "sports_manage_detected_add_countries", "none", False),
    ("sports_manage_detected_remove_countries", "sports_manage_detected_remove_countries", "none", False),
    ("sports_manage_detected_review_channels", "sports_manage_detected_review_channels", "args", False),
    ("sports_manage_detected_add_channels", "sports_manage_detected_add_channels", "args", False),
    ("sports_manage_detected_remove_channels", "sports_manage_detected_remove_channels", "args", False),
    ("sports_manage_detected_review_action", "sports_manage_detected_review_action", "args", False),
    ("sports_manage_detected_add_action", "sports_manage_detected_add_action", "args", False),
    ("sports_manage_detected_remove_action", "sports_manage_detected_remove_action", "args", False),
]

for _mode, _method, _style, _sports_end_false in _SPORTS_ROUTE_SPECS:
    _register_sports_route(_mode, _method, _style, _sports_end_false)


_SPORTS_RESULTS_ROUTE_SPECS = [
    ("sports_results_menu", "results_menu", "none"),
    ("sports_results_live", "live_menu", "none"),
    ("sports_results_today", "today_menu", "args"),
    ("sports_results_yesterday", "yesterday_menu", "args"),
    ("sports_results_upcoming", "upcoming_menu", "args"),
    ("sports_results_leagues", "leagues_menu", "args"),
    ("sports_results_teams", "teams_menu", "args"),
    ("sports_results_players", "players_menu", "args"),
    ("sports_results_events", "events_menu", "args"),
    ("sports_results_venues", "venues_menu", "args"),
    ("sports_results_tv", "tv_listings_menu", "args"),
    ("sports_results_highlights", "highlights_menu", "args"),
    ("sports_results_catalog", "api_catalog_menu", "args"),
    ("sports_results_search", "search_menu", "args"),
    ("sports_results_tools", "tools_menu", "none"),
    ("sports_results_endpoint", "generic_endpoint", "args"),
    ("sports_results_details", "entity_details", "args"),
    ("sports_results_clear_cache", "clear_cache", "none"),
    ("sports_results_api_status", "api_status", "none"),
]

for _mode, _method, _style in _SPORTS_RESULTS_ROUTE_SPECS:
    _register_sports_results_route(_mode, _method, _style)


@route("download")
def _download(runtime):
    args = runtime.args
    try:
        url = args.get("url", [""])[0]
        title = args.get("title", [""])[0] or args.get("name", [""])[0]
        year = args.get("year", [""])[0]
        stype = args.get("stype", ["movie"])[0]
        pnum = args.get("profile_num", [runtime.pm.active])[0]
        tmdb_type = _normalize_tmdb_type(args.get("tmdb_type", ["movie"])[0]) or "movie"
        season = args.get("season", [""])[0]
        episode = args.get("episode", [""])[0]
        media_type = "episode" if tmdb_type == "tv" or stype == "series" else "movie"
        dl_id = _get_downloader().start_download(
            url=url,
            title=title,
            year=year,
            media_type=media_type,
            season=season,
            episode=episode,
            poster=args.get("poster", [""])[0],
            plot=args.get("plot", [""])[0],
            profile_num=pnum,
        )
        xbmcgui.Dialog().notification("Xstream Pro", _t(30942 if dl_id else 30949))
    except Exception as exc:
        _handle_download_error("Download start", exc, 30944)
    finally:
        xbmc.executebuiltin("Container.Refresh")
        xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("downloads_manager")
def _downloads_manager(runtime):
    try:
        _get_downloader().downloads_menu(
            runtime.addon_handle,
            runtime.args.get("pnum", [runtime.pm.active])[0],
        )
    except Exception as exc:
        _log("Downloads manager error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
        xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("downloads_refresh")
def _downloads_refresh(runtime):
    xbmc.executebuiltin("Container.Refresh")
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


def _download_item_action(runtime, method_name, prompt_id, success_id, log_label):
    args = runtime.args
    try:
        dl_id = args.get("id", [""])[0]
        pnum = args.get("pnum", [runtime.pm.active])[0]
        if dl_id and xbmcgui.Dialog().yesno("Xstream Pro", _t(prompt_id)):
            if getattr(_get_downloader(), method_name)(dl_id, pnum):
                xbmcgui.Dialog().notification("Xstream Pro", _t(success_id))
                xbmc.executebuiltin("Container.Refresh")
    except Exception as exc:
        _log("{0} error: {1}".format(log_label, exc))
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("download_cancel")
def _download_cancel(runtime):
    _download_item_action(runtime, "cancel_download", 31140, 30945, "Download cancel")


@route("download_retry")
def _download_retry(runtime):
    _download_item_action(runtime, "retry_download", 31143, 30948, "Download retry")


@route("download_remove_from_list")
def _download_remove_from_list(runtime):
    _download_item_action(
        runtime, "remove_download_from_list", 31142, 30947, "Download remove from list"
    )


@route("download_delete")
def _download_delete(runtime):
    _download_item_action(runtime, "delete_download", 31141, 30947, "Download delete")


@route("download_pause")
def _download_pause(runtime):
    _download_item_action(runtime, "pause_download", 31138, 31076, "Download pause")


@route("download_resume")
def _download_resume(runtime):
    _download_item_action(runtime, "resume_download", 31139, 31077, "Download resume")


@route("change_download_folder")
def _change_download_folder(runtime):
    try:
        changer = _ctx("change_download_folder")
        if changer:
            changer()
    except Exception as exc:
        _log("Change download folder error: {0}".format(exc))
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("downloads_tools")
def _downloads_tools(runtime):
    try:
        pnum = runtime.args.get("pnum", [runtime.pm.active])[0]
        module = _get_downloader()
        downloads = module.get_downloads_list(pnum)
        if downloads:
            has_active_queued = any(d.get("status") in ("active", "queued") for d in downloads)
            has_paused_failed_cancelled = any(d.get("status") in ("paused", "failed", "cancelled") for d in downloads)
            has_active_queued_paused = any(d.get("status") in ("active", "queued", "paused") for d in downloads)
            has_completed_failed_cancelled = any(d.get("status") in ("completed", "failed", "cancelled") for d in downloads)
            has_missing = module.count_missing_downloads(pnum) > 0

            labels = []
            actions = []
            if has_active_queued:
                labels.append(_t(31132))
                actions.append(_build_url({"mode": "download_pause_all", "pnum": pnum}))
            if has_paused_failed_cancelled:
                labels.append(_t(31087))
                actions.append(_build_url({"mode": "download_start_all", "pnum": pnum}))
            if has_active_queued_paused:
                labels.append(_t(31088))
                actions.append(_build_url({"mode": "download_cancel_all", "pnum": pnum}))
            if has_completed_failed_cancelled:
                labels.append(_t(31089))
                actions.append(_build_url({"mode": "download_delete_all", "pnum": pnum}))
            if has_missing:
                labels.append(_t(31104))
                actions.append(_build_url({"mode": "download_clean_missing", "pnum": pnum}))

            if labels:
                idx = xbmcgui.Dialog().select(_t(30010), labels)
                if 0 <= idx < len(actions):
                    xbmc.executebuiltin("RunPlugin({0})".format(actions[idx]))
            else:
                xbmcgui.Dialog().notification("Xstream Pro", _t(31144))
        else:
            xbmcgui.Dialog().notification("Xstream Pro", _t(31144))
    except Exception as exc:
        _log("Downloads tools error: {0}".format(exc))
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


def _download_bulk_action(runtime, method_name, prompt_id, success_id, empty_id, log_label):
    try:
        pnum = runtime.args.get("pnum", [runtime.pm.active])[0]
        if xbmcgui.Dialog().yesno("Xstream Pro", _t(prompt_id)):
            count = getattr(_get_downloader(), method_name)(pnum)
            if count:
                xbmcgui.Dialog().notification("Xstream Pro", _t(success_id, count))
                xbmc.executebuiltin("Container.Refresh")
            else:
                xbmcgui.Dialog().notification("Xstream Pro", _t(empty_id))
    except Exception as exc:
        _log("{0} error: {1}".format(log_label, exc))
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)


@route("download_pause_all")
def _download_pause_all(runtime):
    _download_bulk_action(runtime, "pause_all_downloads", 31136, 31137, 31090, "Download pause all")


@route("download_start_all")
def _download_start_all(runtime):
    _download_bulk_action(runtime, "start_all_downloads", 31095, 31099, 31091, "Download start all")


@route("download_cancel_all")
def _download_cancel_all(runtime):
    _download_bulk_action(runtime, "cancel_all_downloads", 31096, 31100, 31092, "Download cancel all")


@route("download_delete_all")
def _download_delete_all(runtime):
    _download_bulk_action(runtime, "delete_all_downloads", 31097, 31101, 31093, "Download delete all")


@route("download_clean_missing")
def _download_clean_missing(runtime):
    try:
        pnum = runtime.args.get("pnum", [runtime.pm.active])[0]
        module = _get_downloader()
        missing = module.count_missing_downloads(pnum)
        if not missing:
            xbmcgui.Dialog().notification("Xstream Pro", _t(31107))
        elif xbmcgui.Dialog().yesno("Xstream Pro", _t(31105, missing)):
            count = module.clean_missing_downloads(pnum)
            if count:
                xbmcgui.Dialog().notification("Xstream Pro", _t(31106, count))
                xbmc.executebuiltin("Container.Refresh")
            else:
                xbmcgui.Dialog().notification("Xstream Pro", _t(31107))
    except Exception as exc:
        _log("Download clean missing error: {0}".format(exc))
    xbmcplugin.endOfDirectory(runtime.addon_handle, succeeded=False)
