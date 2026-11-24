"""Tool menus and action handlers for Xstream Pro."""

import os
import re

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs


_addon = None
_addon_handle = None
_log = None
_t = None
_new_listitem = None
_addon_fanart = None
_local_icon = None
_build_url = None
_check_pin = None
_get_pvr_profile_num = None
_get_sports_pvr_profile_num = None
_pvr_m3u_path = None
_sports_pvr_m3u_path = None
_m3u_file_has_channels = None
_profile_has_data = None
_pvr_health_report = None
_tvos_sleep = None
_restart_or_prompt = None


def init(
    addon,
    addon_handle,
    log_fn,
    translate_fn,
    new_listitem_fn,
    addon_fanart_fn,
    local_icon_fn,
    build_url_fn,
    check_pin_fn,
    get_pvr_profile_num_fn,
    get_sports_pvr_profile_num_fn,
    pvr_m3u_path_fn,
    sports_pvr_m3u_path_fn,
    m3u_file_has_channels_fn,
    profile_has_data_fn,
    pvr_health_report_fn,
    tvos_sleep_fn,
    restart_or_prompt_fn,
):
    global _addon, _addon_handle, _log, _t, _new_listitem, _addon_fanart
    global _local_icon, _build_url, _check_pin
    global _get_pvr_profile_num, _get_sports_pvr_profile_num
    global _pvr_m3u_path, _sports_pvr_m3u_path, _m3u_file_has_channels
    global _profile_has_data, _pvr_health_report, _tvos_sleep, _restart_or_prompt

    _addon = addon
    _addon_handle = addon_handle
    _log = log_fn
    _t = translate_fn
    _new_listitem = new_listitem_fn
    _addon_fanart = addon_fanart_fn
    _local_icon = local_icon_fn
    _build_url = build_url_fn
    _check_pin = check_pin_fn
    _get_pvr_profile_num = get_pvr_profile_num_fn
    _get_sports_pvr_profile_num = get_sports_pvr_profile_num_fn
    _pvr_m3u_path = pvr_m3u_path_fn
    _sports_pvr_m3u_path = sports_pvr_m3u_path_fn
    _m3u_file_has_channels = m3u_file_has_channels_fn
    _profile_has_data = profile_has_data_fn
    _pvr_health_report = pvr_health_report_fn
    _tvos_sleep = tvos_sleep_fn
    _restart_or_prompt = restart_or_prompt_fn


def _add_menu_items(items, non_folder_modes=None):
    fanart = _addon_fanart()
    directory_items = []
    non_folder_modes = set(non_folder_modes or ())
    for label, query, icon in items:
        li = _new_listitem(label)
        art = {"icon": icon}
        if fanart:
            art["fanart"] = fanart
        li.setArt(art)
        if isinstance(query, str):
            url = query
            is_folder = True
        else:
            url = _build_url(query)
            is_folder = query.get("mode") not in non_folder_modes
        directory_items.append((url, li, is_folder))
    xbmcplugin.addDirectoryItems(_addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def main_tools_menu():
    _log("Opening main tools menu")
    items = [
        (_t(31390), {"mode": "profiles_search_menu"}, _local_icon("profiles")),
        (_t(30017, _get_pvr_profile_num()), {"mode": "switch_profile"}, _local_icon("live_tv_pvr")),
        (_t(30008), {"mode": "pvr_favorites_manager"}, _local_icon("favorites")),
        (_t(30740), {"mode": "manage_active_profiles"}, _local_icon("manage_user_profile")),
        (_t(31388), {"mode": "manage_main_menu_items"}, _local_icon("settings")),
        (_t(30718), {"mode": "reset_reload_menu"}, _local_icon("reset_reload")),
        (_t(30016), {"mode": "clear_cache_menu"}, _local_icon("clear_cache_history")),
        (_t(30020), {"mode": "check_update"}, _local_icon("check_for_update")),
        (_t(30723), {"mode": "account_iptv_menu"}, _local_icon("account_info")),
        (_t(30909), {"mode": "settings"}, _local_icon("settings")),
    ]
    _add_menu_items(
        items,
        {
            "settings",
            "clear_cache_menu",
            "manage_active_profiles",
            "manage_main_menu_items",
            "check_update",
        },
    )


def tools_menu():
    _log("Opening tools menu")
    if not _check_pin("Tools"):
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=False)
        return
    items = [
        ("[COLOR yellow]{0}[/COLOR]".format(_t(30011)), {"mode": "settings"}, "DefaultAddonProgram.png"),
        (_t(30017, _get_pvr_profile_num()), {"mode": "switch_profile"}, "DefaultAddonPVRClient.png"),
        (_t(30740), {"mode": "manage_active_profiles"}, "DefaultTVShows.png"),
        (_t(31388), {"mode": "manage_main_menu_items"}, "DefaultAddonProgram.png"),
        (_t(30718), {"mode": "reset_reload_menu"}, "DefaultAddonsUpdates.png"),
        (_t(30016), {"mode": "clear_cache_menu"}, "DefaultAddonNone.png"),
        (_t(30723), {"mode": "account_iptv_menu"}, "DefaultAddonWebSkin.png"),
        ("[COLOR green]{0}[/COLOR]".format(_t(30020)), {"mode": "check_update"}, "DefaultAddonsUpdates.png"),
    ]
    _add_menu_items(
        items,
        {
            "settings",
            "clear_cache_menu",
            "manage_active_profiles",
            "manage_main_menu_items",
        },
    )


def reset_reload_menu():
    _log("Opening reset/reload menu")
    items = [
        (_t(30012), {"mode": "refresh_profile_menu"}, _local_icon("reset_reload")),
        (_t(30719), {"mode": "force_reload_epg"}, _local_icon("reset_reload")),
        (_t(30720), {"mode": "force_reload_pvr"}, _local_icon("reset_reload")),
        (_t(31532), {"mode": "sync_sports_pvr"}, _local_icon("reset_reload")),
        (_t(31434), {"mode": "reset_pvr_epg_db"}, _local_icon("reset_reload")),
        (_t(30721), {"mode": "relaunch_kodi"}, _local_icon("reset_reload")),
    ]
    _add_menu_items(
        items,
        {
            "refresh_profile_menu",
            "force_reload_epg",
            "force_reload_pvr",
            "sync_sports_pvr",
            "reset_pvr_epg_db",
            "relaunch_kodi",
        },
    )


def account_iptv_menu():
    _log("Opening account info menu")
    items = [
        (_t(30724), {"mode": "test_connection"}, _local_icon("currently_airing")),
        (_t(30725), {"mode": "account_info"}, _local_icon("account_info")),
        (_t(30788), {"mode": "loaded_profiles_view"}, _local_icon("profiles")),
        (_t(31681), {"mode": "pvr_health_report"}, _local_icon("account_info")),
    ]
    _add_menu_items(
        items,
        {
            "test_connection",
            "account_info",
            "loaded_profiles_view",
            "pvr_health_report",
        },
    )


def loaded_profiles_view():
    pvr_profile = _addon.getSetting("active_pvr_profile") or "Profile 1"
    match = re.search(r"(\d+)$", pvr_profile)
    pvr_num = match.group(1) if match else "1"
    pvr_loaded = _m3u_file_has_channels(_pvr_m3u_path())
    pvr_status = f"[COLOR green]{_t(30786)}[/COLOR]" if pvr_loaded else f"[COLOR red]{_t(30787)}[/COLOR]"

    sports_num = _get_sports_pvr_profile_num()
    sports_loaded = _m3u_file_has_channels(_sports_pvr_m3u_path())
    sports_status = f"[COLOR green]{_t(30786)}[/COLOR]" if sports_loaded else f"[COLOR red]{_t(30787)}[/COLOR]"

    items = [
        f"{pvr_status} Live TV PVR {pvr_num}",
        f"{sports_status} Sports PVR {sports_num}",
    ]
    for n in range(1, 11):
        profile_name = _addon.getSetting(f"profile_{n}_name") or _t(30390, n)
        has_creds = bool(_addon.getSetting(f"profile_{n}_xtream_url") or _addon.getSetting(f"profile_{n}_m3u"))
        if not has_creds:
            items.append(f"[COLOR grey]{profile_name} ({_t(30864)})[/COLOR]")
            continue
        loaded = _profile_has_data(n)
        status = f"[COLOR green]{_t(30786)}[/COLOR]" if loaded else f"[COLOR red]{_t(30787)}[/COLOR]"
        items.append(f"{status} {profile_name}")
    xbmcgui.Dialog().select(_t(30788), items)


def pvr_health_report_action():
    _log("Opening PVR health report")
    xbmcgui.Dialog().select(_t(31682), _pvr_health_report())


def relaunch_kodi_action():
    dialog = xbmcgui.Dialog()
    confirm = dialog.yesno(_t(30721), _t(30726), yeslabel=_t(30165), nolabel=_t(30164))
    if not confirm:
        return
    _log("Relaunching Kodi")
    _restart_or_prompt()


def install_upnext():
    if xbmc.getCondVisibility("System.HasAddon(service.upnext)"):
        xbmcgui.Dialog().notification("Xstream Pro", _t(30859))
        return
    xbmc.executebuiltin("InstallAddon(service.upnext)")


def open_upnext_settings():
    xbmc.executebuiltin("Dialog.Close(all,true)")
    xbmc.sleep(_tvos_sleep(500))
    xbmcaddon.Addon("service.upnext").openSettings()


def trakt_restore_credentials_action():
    if not xbmcgui.Dialog().yesno(
        "Xstream Pro",
        _t(31350),
    ):
        return
    if _addon.getSetting("trakt_client_id"):
        _addon.setSetting("trakt_client_id", "")
    if _addon.getSetting("trakt_client_secret"):
        _addon.setSetting("trakt_client_secret", "")
    try:
        import trakt
        trakt.clear_tokens()
    except Exception as exc:
        _log("Trakt token clear warning: {0}".format(exc))
    xbmcgui.Dialog().notification("Xstream Pro", _t(31147))


def trakt_clear_cache_action():
    if not xbmcgui.Dialog().yesno("Xstream Pro", _t(31246)):
        return
    try:
        import trakt
        trakt.clear_cache()
    except Exception as exc:
        _log("Trakt cache clear warning: {0}".format(exc))
    xbmcgui.Dialog().notification("Xstream Pro", _t(31148))


def view_changelog():
    """Show full changelog from addon folder."""
    changelog_path = os.path.join(
        xbmcvfs.translatePath(_addon.getAddonInfo("path")), "CHANGELOG.md"
    )
    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            changelog = f.read()
        xbmcgui.Dialog().textviewer(_t(30341), changelog)
    except Exception:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30103))
