"""Hidden category/subcategory/item management menus.

Call init() after addon module globals are available.
"""

import json
import os

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

from core.ui import build_url, _new_listitem
from core.kodi import _safe_fsync

_addon = None
_addon_handle = None
_log_fn = None
_pm = None
_t_fn = None
_get_credentials_for_profile_fn = None
_get_cached_m3u_channels_fn = None
_get_cached_xtream_categories_fn = None
_get_cached_xtream_streams_fn = None
_m3u_has_credentials_fn = None
_refresh_profile_data_fn = None
_is_pvr_profile_fn = None
_is_pvr_iptvsimple_installed_or_disabled_fn = None
_sync_pvr_force_fn = None
_tvos_sleep_fn = None
_main_menu_customized_key = "main_menu_customized"


def init(addon, addon_handle, log_fn, pm, t_fn,
         get_credentials_for_profile_fn,
         get_cached_m3u_channels_fn,
         get_cached_xtream_categories_fn,
         get_cached_xtream_streams_fn,
         m3u_has_credentials_fn,
         refresh_profile_data_fn,
         is_pvr_profile_fn,
         is_pvr_iptvsimple_installed_or_disabled_fn,
         sync_pvr_force_fn,
         tvos_sleep_fn):
    global _addon, _addon_handle, _log_fn, _pm, _t_fn
    global _get_credentials_for_profile_fn
    global _get_cached_m3u_channels_fn
    global _get_cached_xtream_categories_fn
    global _get_cached_xtream_streams_fn
    global _m3u_has_credentials_fn
    global _refresh_profile_data_fn
    global _is_pvr_profile_fn
    global _is_pvr_iptvsimple_installed_or_disabled_fn
    global _sync_pvr_force_fn
    global _tvos_sleep_fn
    _addon = addon
    _addon_handle = addon_handle
    _log_fn = log_fn
    _pm = pm
    _t_fn = t_fn
    _get_credentials_for_profile_fn = get_credentials_for_profile_fn
    _get_cached_m3u_channels_fn = get_cached_m3u_channels_fn
    _get_cached_xtream_categories_fn = get_cached_xtream_categories_fn
    _get_cached_xtream_streams_fn = get_cached_xtream_streams_fn
    _m3u_has_credentials_fn = m3u_has_credentials_fn
    _refresh_profile_data_fn = refresh_profile_data_fn
    _is_pvr_profile_fn = is_pvr_profile_fn
    _is_pvr_iptvsimple_installed_or_disabled_fn = is_pvr_iptvsimple_installed_or_disabled_fn
    _sync_pvr_force_fn = sync_pvr_force_fn
    _tvos_sleep_fn = tvos_sleep_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _t(string_id, *args):
    return _t_fn(string_id, *args) if _t_fn else str(string_id)


def _profile_section_visible(visible, pnum, section):
    visible_set = set(visible)
    section_keys = {
        f"profile_{pnum}_live",
        f"profile_{pnum}_movies",
        f"profile_{pnum}_series",
        f"profile_{pnum}_replay",
        f"profile_{pnum}_favs",
        f"profile_{pnum}_recent",
        f"profile_{pnum}_search",
    }
    if section_keys & visible_set:
        return f"profile_{pnum}_{section}" in visible_set
    if _main_menu_customized_key in visible_set:
        return True
    return f"profile_{pnum}" in visible_set


def _get_hidden_subcats(stype, profile_num=None):
    pnum = profile_num or _pm.active
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    path = os.path.join(profile, f"hidden_subcats_{stype}_{pnum}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _set_hidden_subcats(stype, hidden, profile_num=None):
    pnum = profile_num or _pm.active
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    path = os.path.join(profile, f"hidden_subcats_{stype}_{pnum}.json")
    tmp_file = path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(list(hidden), f)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp_file, path)


def _get_hidden_items(stype, profile_num=None):
    pnum = profile_num or _pm.active
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    path = os.path.join(profile, f"hidden_items_{stype}_{pnum}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _set_hidden_items(stype, hidden, profile_num=None):
    pnum = profile_num or _pm.active
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    path = os.path.join(profile, f"hidden_items_{stype}_{pnum}.json")
    tmp_file = path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(list(hidden), f)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp_file, path)


def hidden_items_all_action(stype="live", pnum=None):
    """Manage all hidden items for a content type."""
    pnum = pnum or _pm.active
    hidden_items = _get_hidden_items(stype, pnum)
    if not hidden_items:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30075))
        return

    creds = _get_credentials_for_profile_fn(pnum)
    url = creds.get("xtream_url", "")
    m3u_url = creds.get("m3u_url", "")

    if not url and m3u_url:
        channels = _get_cached_m3u_channels_fn(m3u_url)
        hidden_entries = [
            ch
            for ch in channels
            if str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
            in hidden_items
        ]
        if not hidden_entries:
            xbmcgui.Dialog().notification("Xstream Pro", _t(30135))
            return
        h_names = [ch.get("name", "Unknown") for ch in hidden_entries]
        h_ids = [
            str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
            for ch in hidden_entries
        ]
    else:
        streams = _get_cached_xtream_streams_fn(
            url,
            creds.get("xtream_username", ""),
            creds.get("xtream_password", ""),
            stype,
        )
        hidden_entries = [
            s for s in (streams or []) if str(s.get("stream_id", "")) in hidden_items
        ]
        if not hidden_entries:
            xbmcgui.Dialog().notification("Xstream Pro", _t(30135))
            return
        h_names = [s.get("name", "Unknown") for s in hidden_entries]
        h_ids = [str(s.get("stream_id", "")) for s in hidden_entries]

    preselect = list(range(len(h_names)))
    result = xbmcgui.Dialog().multiselect(_t(30339), h_names, preselect=preselect)
    if result is None:
        return

    new_hidden = {h_ids[i] for i in result} if result else set()
    orphan_ids = hidden_items - set(h_ids)
    _set_hidden_items(stype, new_hidden | orphan_ids, pnum)
    unhidden = len(h_names) - (len(result) if result else 0)
    if unhidden:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30314, unhidden))
    xbmc.executebuiltin("Container.Refresh")


def _profile_has_data(profile_num):
    profile = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    prefix = f"data_cache_p{profile_num}_"
    try:
        for fname in os.listdir(profile):
            if fname.startswith(prefix):
                rest = fname[len(prefix):]
                if rest and rest[0].isdigit():
                    continue
                return True
    except OSError as e:
        _log(f"data cache list warning: {e}")
    return False


def manage_hidden_subcats(stype, profile_num=None):
    pnum = profile_num or _pm.active
    creds = _get_credentials_for_profile_fn(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    m3u_url = creds.get("m3u_url", "")

    is_m3u_only = not url and m3u_url
    if not url and not m3u_url:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30073))
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=False)
        return

    hidden = _get_hidden_subcats(stype, pnum)
    hidden_items = _get_hidden_items(stype, pnum)
    directory_items = []

    if is_m3u_only:
        channels = _get_cached_m3u_channels_fn(m3u_url)
        if not channels:
            xbmcgui.Dialog().notification("Xstream Pro", _t(30074))
            xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
            return

        li = _new_listitem("[COLOR red]{0}[/COLOR]".format(_t(30260)))
        li.setArt({"icon": "DefaultAddonNone.png"})
        q = {"mode": "hide_all_subcats", "stype": stype, "pnum": pnum, "action": "hide"}
        directory_items.append((build_url(q), li, False))
        li = _new_listitem("[COLOR green]{0}[/COLOR]".format(_t(30261)))
        li.setArt({"icon": "DefaultAddonNone.png"})
        q = {
            "mode": "hide_all_subcats",
            "stype": stype,
            "pnum": pnum,
            "action": "unhide",
        }
        directory_items.append((build_url(q), li, False))
        li = _new_listitem(
            "[COLOR gold]{0}[/COLOR]".format(_t(30262).format(len(hidden_items)))
        )
        li.setArt({"icon": "DefaultFavourites.png"})
        q = {"mode": "hidden_items_all", "stype": stype, "pnum": pnum}
        directory_items.append((build_url(q), li, False))

        sorted_channels = sorted(
            channels,
            key=lambda ch: (ch.get("group") or "General", ch.get("name", "").lower()),
        )
        for ch in sorted_channels:
            item_id = str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
            is_hidden = item_id in hidden_items
            name = ch.get("name", "Unknown")
            group = ch.get("group") or "General"
            label = (
                "[COLOR red]{0}[/COLOR] [{1}] {2}".format(_t(30191), group, name)
                if is_hidden
                else "[{0}] {1}".format(group, name)
            )
            li = _new_listitem(label)
            li.setArt({"icon": ch.get("logo", "") or "DefaultVideo.png"})
            q = {
                "mode": "hide_m3u_item_action",
                "stype": stype,
                "item_id": item_id,
                "item_name": name,
                "pnum": pnum,
            }
            directory_items.append((build_url(q), li, False))
        if directory_items:
            xbmcplugin.addDirectoryItems(_addon_handle, directory_items)
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    cats = _get_cached_xtream_categories_fn(url, user, pwd, stype)
    if not cats:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30074))
        xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    li = _new_listitem("[COLOR red]{0}[/COLOR]".format(_t(30260)))
    li.setArt({"icon": "DefaultAddonNone.png"})
    q = {"mode": "hide_all_subcats", "stype": stype, "pnum": pnum, "action": "hide"}
    directory_items.append((build_url(q), li, False))
    li = _new_listitem("[COLOR green]{0}[/COLOR]".format(_t(30261)))
    li.setArt({"icon": "DefaultAddonNone.png"})
    q = {"mode": "hide_all_subcats", "stype": stype, "pnum": pnum, "action": "unhide"}
    directory_items.append((build_url(q), li, False))
    li = _new_listitem(
        "[COLOR gold]{0}[/COLOR]".format(_t(30262).format(len(hidden_items)))
    )
    li.setArt({"icon": "DefaultFavourites.png"})
    q = {"mode": "hidden_items_all", "stype": stype, "pnum": pnum}
    directory_items.append((build_url(q), li, False))
    for c in cats:
        cat_id = str(c.get("category_id", ""))
        cat_name = c.get("category_name", "Unknown")
        is_hidden = cat_id in hidden
        label = (
            "[COLOR red]{0}[/COLOR] {1}".format(_t(30191), cat_name)
            if is_hidden
            else cat_name
        )
        li = _new_listitem(label)
        li.setArt({"icon": "DefaultFolder.png"})
        q = {
            "mode": "hide_subcat_action",
            "stype": stype,
            "cat_id": cat_id,
            "cat_name": cat_name,
            "pnum": pnum,
        }
        directory_items.append((build_url(q), li, False))
    if directory_items:
        xbmcplugin.addDirectoryItems(_addon_handle, directory_items)
    xbmcplugin.endOfDirectory(_addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def hide_m3u_item_action(stype, item_id, item_name, profile_num=None):
    pnum = profile_num or _pm.active
    hidden_items = _get_hidden_items(stype, pnum)
    is_hidden = item_id in hidden_items

    if is_hidden:
        hidden_items.discard(item_id)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30301, item_name))
    else:
        hidden_items.add(item_id)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30302, item_name))

    _set_hidden_items(stype, hidden_items, pnum)
    xbmc.executebuiltin("Container.Refresh")


def hide_subcat_action(stype, cat_id, cat_name, profile_num=None):
    pnum = profile_num or _pm.active
    hidden = _get_hidden_subcats(stype, pnum)
    is_hidden = cat_id in hidden
    dialog = xbmcgui.Dialog()
    if is_hidden:
        options = [_t(30525), _t(30526)]
    else:
        options = [_t(30527), _t(30526)]
    choice = dialog.select(cat_name, options)
    if choice < 0:
        return
    if choice == 0:
        if is_hidden:
            hidden.discard(cat_id)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30301, cat_name))
        else:
            hidden.add(cat_id)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30302, cat_name))
        _set_hidden_subcats(stype, hidden, pnum)
        xbmc.executebuiltin("Container.Refresh")
    elif choice == 1:
        creds = _get_credentials_for_profile_fn(pnum)
        url = creds.get("xtream_url", "")
        user = creds.get("xtream_username", "")
        pwd = creds.get("xtream_password", "")
        streams = _get_cached_xtream_streams_fn(url, user, pwd, stype)
        filtered = [
            s for s in (streams or []) if str(s.get("category_id", "")) == cat_id
        ]
        if not filtered:
            xbmcgui.Dialog().notification("Xstream Pro", _t(30136))
            return
        hidden_items = _get_hidden_items(stype, pnum)
        ids = [str(s.get("stream_id", "")) for s in filtered]
        names = [_t(30333), _t(30334)] + [s.get("name", "Unknown") for s in filtered]
        preselect = [i + 2 for i, sid in enumerate(ids) if sid in hidden_items]
        result = dialog.multiselect(_t(30528, cat_name), names, preselect=preselect)
        if result is None:
            return
        if 0 in result:
            preselect = list(range(2, len(names)))
            result = dialog.multiselect(_t(30528, cat_name), names, preselect=preselect)
            if result is None:
                return
        if 1 in result:
            result = dialog.multiselect(_t(30528, cat_name), names, preselect=[])
            if result is None:
                return
        real_result = [i - 2 for i in result if i >= 2] if result else []
        cat_ids = set(ids)
        new_hidden = (hidden_items - cat_ids) | (
            {ids[i] for i in real_result} if real_result else set()
        )
        _set_hidden_items(stype, new_hidden, pnum)
        hidden_count = len(result) if result else 0
        xbmcgui.Dialog().notification(
            "Xstream Pro", _t(30312, hidden_count, cat_name)
        )


def hide_all_subcats(stype, action, profile_num=None):
    pnum = profile_num or _pm.active
    creds = _get_credentials_for_profile_fn(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    m3u_url = creds.get("m3u_url", "")
    is_m3u_only = not url and m3u_url

    if is_m3u_only:
        channels = _get_cached_m3u_channels_fn(m3u_url)
        if not channels:
            return
        if action == "hide":
            new_hidden = {
                str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
                for ch in channels
            }
            _set_hidden_items(stype, new_hidden, pnum)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30313, len(new_hidden)))
        else:
            _set_hidden_items(stype, set(), pnum)
            xbmcgui.Dialog().notification("Xstream Pro", _t(30137))
        xbmc.executebuiltin("Container.Refresh")
        return

    cats = [
        str(c.get("category_id", ""))
        for c in _get_cached_xtream_categories_fn(url, user, pwd, stype)
    ]

    if not cats:
        return
    if action == "hide":
        new_hidden = set(cats)
        _set_hidden_subcats(stype, new_hidden, pnum)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30313, len(new_hidden)))
    else:
        _set_hidden_subcats(stype, set(), pnum)
        xbmcgui.Dialog().notification("Xstream Pro", _t(30137))
    xbmc.executebuiltin("Container.Refresh")


def _manage_load_content_toggles(profile_num):
    dialog = xbmcgui.Dialog()
    pnum = profile_num

    original_active = _pm.active
    _pm.active = str(pnum)
    try:
        creds = _pm.get_credentials()
        has_xtream = bool(creds.get("xtream_url"))
        has_m3u_with_creds = bool(creds.get("m3u_url")) and _m3u_has_credentials_fn(
            creds.get("m3u_url")
        )
        supports_categories = has_xtream or has_m3u_with_creds
    finally:
        _pm.active = original_active

    live = _addon.getSetting(f"profile_{pnum}_load_live") != "false"
    movies = _addon.getSetting(f"profile_{pnum}_load_movies") != "false"
    series = _addon.getSetting(f"profile_{pnum}_load_series") != "false"

    if supports_categories:
        options = [_t(30002), _t(30004), _t(30005)]
        preselect = []
        if live:
            preselect.append(0)
        if movies:
            preselect.append(1)
        if series:
            preselect.append(2)
    else:
        options = [_t(30002)]
        preselect = [0] if live else []

    result = dialog.multiselect(_t(30810), options, preselect=preselect)
    if result is None:
        return

    changed = False
    if supports_categories:
        new_live = "true" if 0 in result else "false"
        new_movies = "true" if 1 in result else "false"
        new_series = "true" if 2 in result else "false"
        if _addon.getSetting(f"profile_{pnum}_load_live") != new_live:
            changed = True
        if _addon.getSetting(f"profile_{pnum}_load_movies") != new_movies:
            changed = True
        if _addon.getSetting(f"profile_{pnum}_load_series") != new_series:
            changed = True
        _addon.setSetting(f"profile_{pnum}_load_live", new_live)
        _addon.setSetting(f"profile_{pnum}_load_movies", new_movies)
        _addon.setSetting(f"profile_{pnum}_load_series", new_series)
    else:
        new_live = "true" if 0 in result else "false"
        if _addon.getSetting(f"profile_{pnum}_load_live") != new_live:
            changed = True
        _addon.setSetting(f"profile_{pnum}_load_live", new_live)

    dialog.notification("Xstream Pro", _t(30083))

    if changed:
        if dialog.yesno(_t(30012), _t(30012)):
            _refresh_profile_data_fn(pnum)
            if _is_pvr_profile_fn(pnum) and _is_pvr_iptvsimple_installed_or_disabled_fn():
                xbmc.sleep(_tvos_sleep_fn(500))
                if dialog.yesno("Xstream Pro", _t(30867)):
                    try:
                        _sync_pvr_force_fn()
                        _log("PVR sync triggered after load toggle change")
                    except Exception as e:
                        _log(f"PVR sync after load toggle warning: {e}")
                else:
                    profile_path = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
                    retry_flag = os.path.join(
                        profile_path, "pvr_sync_retry_needed.flag"
                    )
                    with open(retry_flag, "w", encoding="utf-8") as f:
                        f.write("1")
                    _log(
                        "PVR sync deferred after load toggle, flagged for startup retry"
                    )


def _manage_content_select(profile_num):
    dialog = xbmcgui.Dialog()
    pnum = profile_num

    if not _profile_has_data(pnum):
        dialog.ok("Xstream Pro", _t(30759))
        return

    original_active = _pm.active
    _pm.active = str(pnum)
    try:
        creds = _pm.get_credentials()
        has_xtream = bool(creds.get("xtream_url"))
        has_m3u_with_creds = bool(creds.get("m3u_url")) and _m3u_has_credentials_fn(
            creds.get("m3u_url")
        )
        supports_categories = has_xtream or has_m3u_with_creds
    finally:
        _pm.active = original_active

    if supports_categories:
        options = [_t(30002), _t(30004), _t(30005)]
        stype_map = {0: "live", 1: "movie", 2: "series"}
    else:
        options = [_t(30002)]
        stype_map = {0: "live"}

    choice = dialog.select(_t(30760), options)
    if choice < 0:
        return

    stype = stype_map[choice]

    manage_content_dialog(stype, pnum)


def manage_content_dialog(stype, profile_num):
    pnum = profile_num or _pm.active
    creds = _get_credentials_for_profile_fn(pnum)
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    if not url:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30073))
        return
    cats = _get_cached_xtream_categories_fn(url, user, pwd, stype)
    if not cats:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30074))
        return
    dialog = xbmcgui.Dialog()
    streams = _get_cached_xtream_streams_fn(url, user, pwd, stype)
    stype_label_map = {
        "live": _t(30002),
        "movie": _t(30004),
        "series": _t(30005),
    }
    stype_label = stype_label_map.get(stype, stype.capitalize())
    changed = False
    while True:
        hidden = _get_hidden_subcats(stype, pnum)
        hidden_items = _get_hidden_items(stype, pnum)
        hidden_cat_count = len(hidden)
        hidden_item_count = len(hidden_items)
        labels = [
            "[COLOR gold]{0}[/COLOR]".format(_t(30159, hidden_cat_count)),
            "[COLOR gold]{0}[/COLOR]".format(_t(30190, hidden_item_count)),
        ]
        for c in cats:
            cat_name = c.get("category_name", "Unknown")
            labels.append(cat_name)
        choice = dialog.select(_t(30761, stype_label), labels)
        if choice < 0:
            break
        if choice == 0:
            cat_names = [_t(30333), _t(30334)] + [
                c.get("category_name", "Unknown") for c in cats
            ]
            cat_ids = [str(c.get("category_id", "")) for c in cats]
            preselect = [i + 2 for i, cid in enumerate(cat_ids) if cid in hidden]
            result = dialog.multiselect(_t(30335), cat_names, preselect=preselect)
            if result is None:
                continue
            if 0 in result:
                preselect = list(range(2, len(cat_names)))
                result = dialog.multiselect(_t(30335), cat_names, preselect=preselect)
                if result is None:
                    continue
            if 1 in result:
                result = dialog.multiselect(_t(30523), cat_names, preselect=[])
                if result is None:
                    continue
            real_result = [i - 2 for i in result if i >= 2] if result else []
            new_hidden = {cat_ids[i] for i in real_result} if real_result else set()
            if new_hidden != hidden:
                _set_hidden_subcats(stype, new_hidden, pnum)
                dialog.notification("Xstream Pro", _t(30174, len(new_hidden)))
                changed = True
            continue
        if choice == 1:
            if not hidden_items:
                dialog.notification("Xstream Pro", _t(30075))
                continue
            hidden_streams = [
                s
                for s in (streams or [])
                if str(s.get("stream_id", "")) in hidden_items
            ]
            if not hidden_streams:
                dialog.notification("Xstream Pro", _t(30135))
                continue
            h_names = [_t(30334)] + [s.get("name", "Unknown") for s in hidden_streams]
            h_ids = [str(s.get("stream_id", "")) for s in hidden_streams]
            preselect = list(range(1, len(hidden_streams) + 1))
            result = dialog.multiselect(
                _t(30152, stype_label), h_names, preselect=preselect
            )
            if result is None:
                continue
            if 0 in result:
                result = dialog.multiselect(
                    _t(30524, stype_label), h_names, preselect=[]
                )
                if result is None:
                    continue
            real_result = [i - 1 for i in result if i >= 1] if result else []
            new_hidden = {h_ids[i] for i in real_result} if real_result else set()
            orphan_ids = hidden_items - set(h_ids)
            _set_hidden_items(stype, new_hidden | orphan_ids, pnum)
            unhidden = len(hidden_streams) - (len(real_result) if real_result else 0)
            if unhidden:
                dialog.notification("Xstream Pro", _t(30175, unhidden))
                changed = True
            continue
        cat = cats[choice - 2]
        cat_id = str(cat.get("category_id", ""))
        cat_name = cat.get("category_name", "Unknown")
        filtered = [
            s for s in (streams or []) if str(s.get("category_id", "")) == cat_id
        ]
        if not filtered:
            dialog.notification("Xstream Pro", _t(30136))
            continue
        ids = [str(s.get("stream_id", "")) for s in filtered]
        names = [_t(30333), _t(30334)] + [s.get("name", "Unknown") for s in filtered]
        preselect = [i + 2 for i, sid in enumerate(ids) if sid in hidden_items]
        result = dialog.multiselect(_t(30336, cat_name), names, preselect=preselect)
        if result is None:
            continue
        if 0 in result:
            preselect = list(range(2, len(names)))
            result = dialog.multiselect(_t(30336, cat_name), names, preselect=preselect)
            if result is None:
                continue
        if 1 in result:
            result = dialog.multiselect(_t(30524, cat_name), names, preselect=[])
            if result is None:
                continue
        real_result = [i - 2 for i in result if i >= 2] if result else []
        cat_id_set = set(ids)
        new_hidden = (hidden_items - cat_id_set) | (
            {ids[i] for i in real_result} if real_result else set()
        )
        if new_hidden != hidden_items:
            _set_hidden_items(stype, new_hidden, pnum)
            hidden_count = len(result) if result else 0
            dialog.notification("Xstream Pro", _t(30176, hidden_count, cat_name))
            changed = True
    if changed and pnum == _pm.active and stype == "live":
        _sync_pvr_force_fn()
    if changed:
        if dialog.yesno(_t(30012), _t(30012)):
            _refresh_profile_data_fn(pnum)
            return
    xbmc.executebuiltin("Addon.OpenSettings(plugin.video.xstream-pro)")
    xbmc.sleep(_tvos_sleep_fn(300))
    xbmc.executebuiltin("SetFocus(9,1)")
    xbmc.executebuiltin("SetFocus(10,0)")
