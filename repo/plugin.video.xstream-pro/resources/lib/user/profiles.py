"""Profile and profile-menu route helpers for Xstream Pro."""

import traceback

import xbmc
import xbmcgui
import xbmcplugin

from core.ui import build_url

addon = None
addon_handle = None
pm = None
_log = None
_t = None
_new_listitem = None
_local_icon = None
_addon_fanart = None
_refresh_all_profiles_with_progress = None
_refresh_profile_data = None
_prompt_profile_credentials = None
_m3u_has_credentials = None
_m3u_simple_menu = None
_profile_section_visible = None
_pvr_m3u_path = None
_m3u_file_has_channels = None
_get_pvr_profile_num = None
_unload_pvr = None
_sync_pvr_force = None
_purge_profile_data = None
_main_menu_available_item_labels = None
_main_menu_item_visible = None
_main_menu_managed_keys = []
_main_menu_customized_key = "main_menu_customized"


def init(
    addon_obj,
    addon_handle_value,
    profile_manager,
    log_fn,
    translate_fn,
    new_listitem_fn,
    local_icon_fn,
    addon_fanart_fn,
    refresh_all_profiles_with_progress_fn,
    refresh_profile_data_fn,
    prompt_profile_credentials_fn,
    m3u_has_credentials_fn,
    m3u_simple_menu_fn,
    profile_section_visible_fn,
    pvr_m3u_path_fn,
    m3u_file_has_channels_fn,
    get_pvr_profile_num_fn,
    unload_pvr_fn,
    sync_pvr_force_fn,
    purge_profile_data_fn,
    main_menu_available_item_labels_fn,
    main_menu_item_visible_fn,
    main_menu_managed_keys=None,
    main_menu_customized_key="main_menu_customized",
):
    global addon, addon_handle, pm, _log, _t, _new_listitem, _local_icon, _addon_fanart
    global _refresh_all_profiles_with_progress, _refresh_profile_data
    global _prompt_profile_credentials, _m3u_has_credentials, _m3u_simple_menu
    global _profile_section_visible, _pvr_m3u_path, _m3u_file_has_channels
    global _get_pvr_profile_num, _unload_pvr, _sync_pvr_force, _purge_profile_data
    global _main_menu_available_item_labels, _main_menu_item_visible
    global _main_menu_managed_keys, _main_menu_customized_key
    addon = addon_obj
    addon_handle = addon_handle_value
    pm = profile_manager
    _log = log_fn
    _t = translate_fn
    _new_listitem = new_listitem_fn
    _local_icon = local_icon_fn
    _addon_fanart = addon_fanart_fn
    _refresh_all_profiles_with_progress = refresh_all_profiles_with_progress_fn
    _refresh_profile_data = refresh_profile_data_fn
    _prompt_profile_credentials = prompt_profile_credentials_fn
    _m3u_has_credentials = m3u_has_credentials_fn
    _m3u_simple_menu = m3u_simple_menu_fn
    _profile_section_visible = profile_section_visible_fn
    _pvr_m3u_path = pvr_m3u_path_fn
    _m3u_file_has_channels = m3u_file_has_channels_fn
    _get_pvr_profile_num = get_pvr_profile_num_fn
    _unload_pvr = unload_pvr_fn
    _sync_pvr_force = sync_pvr_force_fn
    _purge_profile_data = purge_profile_data_fn
    _main_menu_available_item_labels = main_menu_available_item_labels_fn
    _main_menu_item_visible = main_menu_item_visible_fn
    _main_menu_managed_keys = list(main_menu_managed_keys or [])
    _main_menu_customized_key = main_menu_customized_key or "main_menu_customized"

def sports_refresh_profile_menu():
    if not xbmcgui.Dialog().yesno(_t(31670), _t(31671)):
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    refresh_profile_menu()

def refresh_profile_menu():
    """Show menu to select which profile(s) to refresh with progress dialog."""
    try:
        dialog = xbmcgui.Dialog()

        # Build list of enabled profiles
        profiles = []
        for i in range(1, 11):
            if addon.getSetting(f"profile_{i}_enabled") == "true":
                name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
                profiles.append((i, name))

        if not profiles:
            dialog.notification(_t(30770), _t(30074))
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return

        # Build menu items
        items = [(_t(30736), "all")]  # Refresh All Enabled Profiles
        for num, name in profiles:
            label = (
                _t(31400, num, name)
                if name != _t(30390, num)
                else _t(30390, num)
            )
            items.append((label, num))

        idx = dialog.select(_t(30012), [i[0] for i in items])
        if idx < 0:
            xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
            return

        selected = items[idx][1]

        if selected == "all":
            # Refresh all enabled profiles with progress
            _refresh_all_profiles_with_progress(profiles)
        else:
            # Refresh single profile with progress
            _refresh_profile_data(selected)

        xbmc.executebuiltin("Container.Refresh")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
    except Exception as e:
        _log(f"refresh_profile_menu error: {e}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)

def profile_menu(pnum):
    """Show sub-menu for a specific profile (TV Classic, Movies, Series, etc)."""
    _log(f"Opening profile menu for profile {pnum}")

    profile_name = addon.getSetting(f"profile_{pnum}_name") or _t(30390, pnum)

    if not _prompt_profile_credentials(pnum):
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return

    # Temporarily set pm.active for credential loading
    original_active = pm.active
    pm.active = str(pnum)

    try:
        creds = pm.get_credentials()
        load_live = pm.get_profile_setting("load_live") != "false"
        load_movies = pm.get_profile_setting("load_movies") != "false"
        load_series = pm.get_profile_setting("load_series") != "false"
        has_xtream = bool(creds.get("xtream_url"))
        has_m3u_with_creds = bool(creds.get("m3u_url")) and _m3u_has_credentials(
            creds.get("m3u_url")
        )
        has_m3u_simple = bool(creds.get("m3u_url")) and not has_m3u_with_creds
        has_live = (has_xtream or has_m3u_with_creds or has_m3u_simple) and load_live
        has_movies = (has_xtream or has_m3u_with_creds) and load_movies
        has_series = (has_xtream or has_m3u_with_creds) and load_series
        has_replay = (has_xtream or has_m3u_with_creds) and load_live

        # M3U without creds - special layout: Favs, Recent, Search at top, then all channels
        if has_m3u_simple and load_live:
            # Top: Search
            li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30007)))
            li.setArt({"icon": _local_icon("search")})
            xbmcplugin.addDirectoryItems(
                addon_handle,
                [(build_url({"mode": "search_global", "profile_num": pnum}), li, True)],
                1,
            )

            # Then: All M3U channels directly
            _m3u_simple_menu(pnum)
            return

        # Xtream or M3U with creds - standard category layout
        _pmenu_visible = set(pm.get_visible_categories())
        items = []
        if has_live and _profile_section_visible(_pmenu_visible, pnum, "live"):
            items.append(
                (
                    _t(30002),
                    {"mode": "live_menu", "profile_num": pnum},
                    _local_icon("live_tv_pvr"),
                    True,
                )
            )
        if has_movies and _profile_section_visible(_pmenu_visible, pnum, "movies"):
            items.append(
                (
                    _t(30004),
                    {"mode": "movies_menu", "profile_num": pnum},
                    _local_icon("movies"),
                    True,
                )
            )
        if has_series and _profile_section_visible(_pmenu_visible, pnum, "series"):
            items.append(
                (
                    _t(30005),
                    {"mode": "series_menu", "profile_num": pnum},
                    _local_icon("tv_shows"),
                    True,
                )
            )
        if has_replay and _profile_section_visible(_pmenu_visible, pnum, "replay"):
            items.append(
                (
                    _t(30006),
                    {"mode": "replay_menu", "profile_num": pnum},
                    _local_icon("in_progress"),
                    True,
                )
            )
        if _profile_section_visible(_pmenu_visible, pnum, "search"):
            items.append(
                (
                    _t(30007),
                    {"mode": "search_global", "profile_num": pnum},
                    _local_icon("search"),
                    True,
                )
            )

        directory_items = []
        for label, q, icon, is_folder in items:
            li = _new_listitem(label)
            li.setArt({"icon": icon})
            directory_items.append((build_url(q), li, is_folder))
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    except Exception as e:
        _log(f"profile_menu error for profile {pnum}: {e}")

        _log(f"Traceback: {traceback.format_exc()}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
    finally:
        pm.active = original_active

def manage_active_profiles():
    """Show dialog to enable/disable PVR and profiles from main menu."""
    try:
        dialog = xbmcgui.Dialog()
        changed = False

        while True:
            items = []
            states = []

            # PVR item at the top
            pvr_path = _pvr_m3u_path()
            pvr_loaded = _m3u_file_has_channels(pvr_path)
            pvr_status = (
                f"[COLOR green]{_t(30786)}[/COLOR]"
                if pvr_loaded
                else f"[COLOR red]{_t(30787)}[/COLOR]"
            )
            pvr_label = f"{_t(30001)} ({_t(30390, _get_pvr_profile_num())})"
            items.append(f"{pvr_status} {pvr_label}")
            states.append(pvr_loaded)

            for n in range(1, 11):
                name = addon.getSetting(f"profile_{n}_name") or _t(30390, n)
                label = (
                    _t(31400, n, name) if name != _t(30390, n) else _t(30390, n)
                )
                has_creds = bool(
                    addon.getSetting(f"profile_{n}_xtream_url")
                    or addon.getSetting(f"profile_{n}_m3u")
                )
                if not has_creds:
                    items.append(f"[COLOR grey]{label} ({_t(30864)})[/COLOR]")
                    states.append(None)
                    continue
                enabled = addon.getSetting(f"profile_{n}_enabled") == "true"
                status = (
                    "[COLOR green]ON[/COLOR]" if enabled else "[COLOR red]OFF[/COLOR]"
                )
                items.append(f"{status} {label}")
                states.append(enabled)

            items.append("[COLOR yellow]{0}[/COLOR]".format(_t(30158)))

            choice = dialog.select(_t(30740), items)
            if choice == -1 or choice >= len(items) - 1:
                break

            # choice 0 = PVR
            if choice == 0:
                if states[0]:
                    # PVR is loaded — offer unload
                    unload_now = dialog.yesno(
                        _t(30770), _t(30894), nolabel=_t(30163), yeslabel=_t(30162)
                    )
                    if unload_now:
                        try:
                            _unload_pvr()
                        except Exception as e:
                            _log(f"PVR unload error: {e}")
                        dialog.notification("Xstream Pro", _t(30896))
                else:
                    # PVR is unloaded — offer load
                    load_now = dialog.yesno(
                        _t(30770), _t(30897), nolabel=_t(30403), yeslabel=_t(30162)
                    )
                    if load_now:
                        try:
                            _sync_pvr_force()
                        except Exception as e:
                            _log(f"PVR load error: {e}")
                        dialog.notification("Xstream Pro", _t(30878))
                continue

            # Profiles (shifted by +1 because PVR is at index 0)
            profile_num = choice
            if states[choice] is None:
                dialog.notification("Xstream Pro", _t(30893))
                continue

            current = addon.getSetting(f"profile_{profile_num}_enabled") == "true"
            new_state = "false" if current else "true"
            addon.setSetting(f"profile_{profile_num}_enabled", new_state)
            changed = True

            # If profile was enabled, auto-show it on main menu and ask to refresh data
            if new_state == "true":
                visible_cats = set(pm.get_visible_categories())
                if f"profile_{profile_num}" not in visible_cats:
                    visible_cats.add(f"profile_{profile_num}")
                    pm.set_visible_categories(list(visible_cats))
                name = addon.getSetting(f"profile_{profile_num}_name") or _t(
                    30390, profile_num
                )
                refresh_now = dialog.yesno(
                    _t(30770), _t(30748, name), nolabel=_t(30403), yeslabel=_t(30162)
                )
                if refresh_now:
                    _refresh_profile_data(profile_num)
            else:
                # Profile was disabled - ask to unload cached data
                name = addon.getSetting(f"profile_{profile_num}_name") or _t(
                    30390, profile_num
                )
                unload_now = dialog.yesno(
                    _t(30770), _t(30809, name), nolabel=_t(30163), yeslabel=_t(30162)
                )
                if unload_now:
                    count = _purge_profile_data(profile_num)
                    _log(f"Cleared {count} files for profile {profile_num}")

        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        if changed:
            xbmc.executebuiltin(
                "Container.Update(plugin://plugin.video.xstream-pro/)"
            )
    except Exception as e:
        _log(f"manage_active_profiles error: {e}")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)

def manage_main_menu_items():
    dialog = xbmcgui.Dialog()
    available = _main_menu_available_item_labels()

    if not available:
        dialog.notification("Xstream Pro", _t(31229))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return

    visible = set(pm.get_visible_categories())
    labels = [label for _key, label in available]

    preselect = [
        idx
        for idx, (key, _label) in enumerate(available)
        if _main_menu_item_visible(visible, key)
    ]

    result = dialog.multiselect(_t(31388), labels, preselect=preselect)

    if result is None:
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return

    selected = {available[idx][0] for idx in result}
    updated = visible - set(_main_menu_managed_keys) - {_main_menu_customized_key}
    updated.update(selected)
    updated.update({_main_menu_customized_key, "tools", "main_tools"})

    pm.set_visible_categories(list(updated))
    dialog.notification("Xstream Pro", _t(31389))
    xbmc.executebuiltin("Container.Update(plugin://plugin.video.xstream-pro/)")
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False)

def profiles_search_menu():
    """List enabled profiles and global search for the Tools hub."""
    _log("Opening profiles search menu")
    enabled_profiles = []
    profile_names = {}
    for n in range(1, 11):
        if addon.getSetting(f"profile_{n}_enabled") == "true":
            enabled_profiles.append(n)
            profile_names[n] = addon.getSetting(f"profile_{n}_name") or _t(30390, n)

    has_search = any(
        bool(
            addon.getSetting(f"profile_{n}_xtream_url")
            or addon.getSetting(f"profile_{n}_m3u")
        )
        for n in range(1, 11)
    )

    items = []
    for n in enabled_profiles:
        items.append(
            (
                profile_names[n],
                {"mode": "profile_menu", "pnum": n},
                _local_icon("profiles"),
                True,
            )
        )

    if has_search:
        items.append(
            (
                _t(30889),
                {"mode": "search_global"},
                _local_icon("search"),
                True,
            )
        )

    _fanart = _addon_fanart()
    directory_items = []
    for label, q, icon, is_folder in items:
        li = _new_listitem(label)
        art = {"icon": icon}
        if _fanart:
            art["fanart"] = _fanart
        li.setArt(art)
        directory_items.append((build_url(q), li, is_folder))
    xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)

def switch_profile():
    """Change the PVR profile and prompt for restart."""
    current = addon.getSetting("active_pvr_profile") or "Profile 1"
    current_num = current.replace("Profile ", "") if "Profile " in current else "1"
    profiles = []
    for i in range(1, 11):
        if addon.getSetting(f"profile_{i}_enabled") != "true":
            continue
        has_xtream = bool(addon.getSetting(f"profile_{i}_xtream_url"))
        has_m3u = bool(addon.getSetting(f"profile_{i}_m3u"))
        if not has_xtream and not has_m3u:
            continue
        name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
        label = _t(31400, i, name) if name != _t(30390, i) else _t(30390, i)
        marker = " [COLOR green]*[/COLOR]" if str(i) == current_num else ""
        profiles.append((str(i), f"{label}{marker}"))
    if not profiles:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30893))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    labels = [p[1] for p in profiles]
    idx = xbmcgui.Dialog().select(_t(30017), labels)
    if idx < 0:
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    selected_num = profiles[idx][0]
    if selected_num == current_num:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30121))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    selected_profile = _t(30390, selected_num)
    # Offer reload PVR or cancel
    dialog = xbmcgui.Dialog()
    options = [_t(30720), _t(30403)]  # Reload PVR, Cancel
    choice = dialog.select(_t(30732, selected_profile), options)
    if choice == 0:
        old_profile = current
        addon.setSetting("active_pvr_profile", selected_profile)
        ok = False
        try:
            ok = _sync_pvr_force()
        except Exception as e:
            _log(f"PVR reload error: {e}")

            _log(f"Traceback: {traceback.format_exc()}")
        if ok:
            addon.setSetting("last_pvr_profile", selected_profile)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30281))
        else:
            addon.setSetting("active_pvr_profile", old_profile)
            addon.setSetting("last_pvr_profile", old_profile)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30082))
    else:
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            _t(30307, profiles[idx][1].replace("[COLOR green]*[/COLOR]", "").strip()),
        )
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
