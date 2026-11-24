"""PVR favorites helpers for Xstream Pro."""

_OWNED = {'_pvr_favs_path', '_sports_pvr_favs_path', '_sports_pvr_favs_m3u_path', '_pvr_favs_load_all', '_pvr_favs_save_all', '_pvr_favs_load', '_pvr_favs_save', '_pvr_favs_add', '_pvr_favs_remove', '_pvr_favs_m3u_path', '_export_pvr_favs_m3u', '_sync_pvr_favorites', '_safe_sync_pvr_favorites_startup', '_sync_pvr_favorites_safe', 'pvr_favorites_manager', 'pvr_favs_manage_group', 'pvr_favs_group_current', 'pvr_favs_group_search', 'pvr_favs_manage_cat', '_pvr_favs_multiselect', '_sports_pvr_item_key', '_sports_pvr_source_country_groups', 'sports_pvr_favorites_manager', 'sports_pvr_favs_manage', 'sports_pvr_favs_manage_group', 'sports_pvr_favs_group_current', 'sports_pvr_favs_group_search', 'sports_pvr_favs_manage_country', '_sports_pvr_favs_multiselect', 'sports_pvr_favs_new_group', 'sports_pvr_favs_rename_group', 'sports_pvr_favs_delete_group', 'sports_pvr_fav_remove', '_sports_pvr_favs_load_all', '_sports_pvr_favs_save_all', '_sports_pvr_favs_load', '_sports_pvr_favs_save', '_export_sports_pvr_favs_m3u'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _pvr_favs_path():
    return _pvr_paths._pvr_favs_path()


def _sports_pvr_favs_path():
    return _pvr_paths._sports_pvr_favs_path()


def _sports_pvr_favs_m3u_path():
    return _pvr_paths._sports_pvr_favs_m3u_path()


def _pvr_favs_load_all():
    """Load all PVR favorite groups. Returns dict of {group_name: [channels]}."""
    try:
        with open(_pvr_favs_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    # Migration: old format was a flat list
    if isinstance(data, list):
        if data:
            return {"Favorites": data}
        return {}
    return data


def _pvr_favs_save_all(groups):
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    favs_path = _pvr_favs_path()
    tmp_file = favs_path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp_file, favs_path)


def _pvr_favs_load(group=None):
    """Load channels from a specific group, or all channels flat."""
    groups = _pvr_favs_load_all()
    if group:
        return groups.get(group, [])
    # All channels flat
    all_items = []
    for items in groups.values():
        all_items.extend(items)
    return all_items


def _pvr_favs_save(items, group=None):
    """Save channels to a specific group."""
    if group is None:
        group = _t(30703) or "Favorites"
    groups = _pvr_favs_load_all()
    groups[group] = items
    _pvr_favs_save_all(groups)


def _pvr_favs_add(channel, group=None):
    if group is None:
        group = _t(30703) or "Favorites"
    items = _pvr_favs_load(group)
    sid = str(channel.get("stream_id", "") or channel.get("id", ""))
    if any(str(i.get("stream_id", "")) == sid for i in items):
        return False
    items.append(channel)
    _pvr_favs_save(items, group)
    return True


def _pvr_favs_remove(stream_id, group=None):
    if group is None:
        group = _t(30703) or "Favorites"
    items = _pvr_favs_load(group)
    sid = str(stream_id)
    new_items = [i for i in items if str(i.get("stream_id", "")) != sid]
    if len(new_items) != len(items):
        _pvr_favs_save(new_items, group)
        return True
    return False


def _pvr_favs_m3u_path():
    return _pvr_paths._pvr_favs_m3u_path()


def _export_pvr_favs_m3u():
    """Export all PVR favorite groups to M3U for the second PVR instance."""
    groups = _pvr_favs_load_all()
    creds = _get_pvr_credentials()
    xt_url = creds.get("xtream_url", "")
    xt_user = creds.get("xtream_username", "")
    xt_pwd = creds.get("xtream_password", "")
    hide_adult = addon.getSetting("hide_adult_categories").lower() == "true"
    pvr_pnum = _get_pvr_profile_num()
    epg_programs = {}
    if _get_pvr_catchup_correction_mode() == "Provider metadata":
        try:
            epg = EPG(addon, profile_num=pvr_pnum)
            epg.load()
            epg_programs = epg.programs or {}
        except Exception as e:
            _log(f"PVR Favorites: Catchup correction EPG load warning: {e}")
    channels = []
    for gname, items in groups.items():
        for ch in items:
            name = ch.get("name", "Unknown")
            if hide_adult and _is_adult_category(name):
                continue
            icon = ch.get("stream_icon", "") or ch.get("icon", "")
            sid = str(ch.get("stream_id", ""))
            epg_id = ch.get("epg_channel_id") or sid
            catchup = ""
            catchup_source = ""
            catchup_days = ""
            url = ""
            if xt_url and xt_user and xt_pwd and sid:
                url = f"{xt_url}/live/{xt_user}/{xt_pwd}/{sid}.ts"
                # Only apply catchup if the original channel data indicated support
                has_catchup = (
                    _truthy_catchup(ch.get("tv_archive"))
                    or _truthy_catchup(ch.get("catchup"))
                    or ch.get("catchup_source")
                    or ch.get("catchup_days")
                )
                if has_catchup:
                    catchup = "default"
                    catchup_source = f"{xt_url}/live/{xt_user}/{xt_pwd}/{sid}.ts?utc={{utc}}&lutc=${{end}}"
                    catchup_days = str(ch.get("tv_archive_duration") or ch.get("catchup_days") or "7")
            elif ch.get("url"):
                url = ch.get("url").split("|")[0]  # strip any existing pipe params
                catchup = ch.get("catchup", "")
                catchup_source = ch.get("catchup_source", "")
                catchup_days = ch.get("catchup_days", "")
            else:
                continue
            channels.append(
                {
                    "name": name,
                    "url": url,
                    "tvg_id": epg_id,
                    "logo": icon,
                    "group": f"★ Favorites - {gname}",
                    "stream_type": ch.get("stream_type", ""),
                    "radio": ch.get("radio", ""),
                    "catchup": catchup,
                    "catchup_source": catchup_source,
                    "catchup_days": catchup_days,
                    "catchup_correction": _catchup_correction_for_channel(
                        epg_programs, epg_id, ch.get("catchup_correction", "")
                    ) if catchup else "",
                }
            )
    m3u_path = _pvr_favs_m3u_path()
    if not channels:
        tmp = m3u_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            try:
                f.flush()
                _safe_fsync(f)
            except OSError:
                pass
        os.replace(tmp, m3u_path)
        return m3u_path
    m3u_data = build_m3u_content(channels)
    tmp = m3u_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(m3u_data)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp, m3u_path)
    return m3u_path


def _sync_pvr_favorites():
    """Sync PVR favorites M3U and configure the second PVR instance."""
    if addon.getSetting("pvr_favorites_enabled").lower() != "true":
        _log("PVR Favorites: Disabled by user setting, removing PVR instance")
        try:
            settings_path = _pvr_instance_settings_path(_get_pvr_instance_id("favs"))
            if os.path.exists(settings_path):
                try:
                    os.remove(settings_path)
                    _log(f"PVR Favorites: Removed {os.path.basename(settings_path)}")
                except Exception as e:
                    _log(f"PVR Favorites: Error removing {os.path.basename(settings_path)}: {e}")
        except Exception as e:
            _log(f"PVR Favorites: Error during instance removal: {e}")
        _log("PVR Favorites: instance removed. Restart Kodi for changes to take effect.")
        return

    # Lightweight lock to prevent overlapping syncs
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    lock_path = os.path.join(profile, ".pvr_fav_sync.lock")
    try:
        if os.path.exists(lock_path):
            try:
                age = time.time() - os.path.getmtime(lock_path)
                if age < 30:
                    _log("PVR Favorites: Sync already in progress, skipping")
                    return
            except OSError:
                pass
            try:
                os.remove(lock_path)
            except OSError:
                pass
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(time.time()))
    except FileExistsError:
        _log("PVR Favorites: Sync lock race lost, skipping")
        return
    except OSError as e:
        _log(f"PVR Favorites: Lock create failed: {e}")
        return

    try:
        pvr_profile_dir = _pvr_iptvsimple_profile_dir()
        settings_path = _pvr_instance_settings_path(_get_pvr_instance_id("favs"))
        expected_m3u = _pvr_favs_m3u_path()
        json_path = _pvr_favs_path()
        m3u_stale = (
            not _m3u_file_has_channels(expected_m3u)
            or (
                os.path.exists(json_path)
                and os.path.exists(expected_m3u)
                and os.path.getmtime(json_path) > os.path.getmtime(expected_m3u)
            )
        )
        if m3u_stale:
            _export_pvr_favs_m3u()
        needs_config = True
        if os.path.exists(settings_path):
            try:
                tree = ET.parse(settings_path)
                root = tree.getroot()
                el = root.find(".//setting[@id='m3uPath']")
                if (
                    el is not None
                    and (el.text or "") == expected_m3u
                    and os.path.exists(expected_m3u)
                    and not m3u_stale
                ):
                    needs_config = False
                    _log(
                        f"PVR Favorites: {os.path.basename(settings_path)} already correct, skipping rewrite"
                    )
            except Exception as e:
                _log(f"PVR Favorites: XML read warning: {e}")
        if needs_config:
            try:
                _configure_pvr_favs_instance()
                _log("PVR Favorites: config rewritten. Restart Kodi for changes to take effect.")
            except Exception as e:
                _log(f"PVR Favorites: config rewrite error: {e}")
    finally:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception as e:
            _log(f"PVR Favorites: Lock remove warning: {e}")


def _safe_sync_pvr_favorites_startup():
    """Startup check only. Never stop/disable/reload PVR from main-menu startup."""
    try:
        expected_m3u = _pvr_favs_m3u_path()
        settings_path = _pvr_instance_settings_path(_get_pvr_instance_id("favs"))
        if not _m3u_file_has_channels(expected_m3u):
            _log("PVR Favorites: Startup sync skipped, no favorite channels")
            return
        if not os.path.exists(settings_path):
            _log("PVR Favorites: Startup sync deferred, favorites instance missing")
            return
        try:
            tree = ET.parse(settings_path)
            root = tree.getroot()
            el = root.find(".//setting[@id='m3uPath']")
            if el is not None and (el.text or "") == expected_m3u:
                _log(
                    f"PVR Favorites: Startup sync skipped, {os.path.basename(settings_path)} already correct"
                )
                return
        except Exception as e:
            _log(f"PVR Favorites: Startup XML read warning: {e}")
        _log("PVR Favorites: Startup sync deferred to manual favorites action")
    except Exception as e:
        _log(f"PVR Favorites: Startup state check error: {e}")


def _sync_pvr_favorites_safe():
    """Sync PVR favorites without stopping/disabling pvr.iptvsimple.

    Files are written atomically so there is no need to stop Kodi's PVR subsystem.
    Restart Kodi for changes to take effect immediately.
    """
    _sync_pvr_favorites()


def pvr_favorites_manager(group=None):
    """PVR Favorites Manager - groups with channels, similar to Favorites Manager."""
    groups = _pvr_favs_load_all()

    # Level 1: show groups + New Group
    if group is None:
        directory_items = []
        for gname, items in groups.items():
            count = len(items)
            li = _new_listitem(_t(30272).format(gname, count))
            li.setArt({"icon": "DefaultFavourites.png"})
            ctx_items = [
                (
                    _t(30320),
                    f"RunPlugin({build_url({'mode': 'pvr_favs_rename_group', 'group': gname})})",
                ),
                (
                    _t(30321),
                    f"RunPlugin({build_url({'mode': 'pvr_favs_delete_group', 'group': gname})})",
                ),
            ]
            li.addContextMenuItems(ctx_items)
            q = {"mode": "pvr_favorites_manager", "group": gname}
            directory_items.append((build_url(q), li, True))
        # + New PVR Group
        li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30200)))
        directory_items.append((build_url({"mode": "pvr_favs_new_group"}), li, False))
        if directory_items:
            xbmcplugin.addDirectoryItems(addon_handle, directory_items)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    # Level 2: inside a group - manage button + channels
    items = groups.get(group, [])
    directory_items = []
    li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30201)))
    li.setArt({"icon": "DefaultAddonService.png"})
    directory_items.append((build_url({"mode": "pvr_favs_manage_group", "group": group}), li, True))

    if not items:
        li = _new_listitem("[COLOR gray]{0}[/COLOR]".format(_t(30202)))
        directory_items.append(("", li, False))
    else:
        creds = _get_pvr_credentials()
        xt_url = creds.get("xtream_url", "")
        xt_user = creds.get("xtream_username", "")
        xt_pwd = creds.get("xtream_password", "")
        for ch in items:
            name = ch.get("name", "Unknown")
            icon = ch.get("stream_icon", "") or ch.get("icon", "")
            sid = str(ch.get("stream_id", ""))
            li = _new_listitem(name)
            li.setArt({"icon": icon, "thumb": icon})
            ctx_items = [
                (
                    _t(30322),
                    f"RunPlugin({build_url({'mode': 'pvr_fav_remove', 'stream_id': sid, 'group': group})})",
                ),
            ]
            li.addContextMenuItems(ctx_items)
            stream_url = f"{xt_url}/live/{xt_user}/{xt_pwd}/{sid}.ts" if xt_url else ""
            q = {
                "mode": "play_stream",
                "url": stream_url,
                "name": name,
                "icon": icon,
                "stype": "live",
            }
            directory_items.append((build_url(q), li, False))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def pvr_favs_manage_group(group):
    """Category browser for adding channels to a specific PVR group."""
    creds = _get_pvr_credentials()
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    if not url:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30056))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return
    # Current channels multiselect
    current_count = len(_pvr_favs_load(group))
    li = _new_listitem(
        "[COLOR gold]{0}[/COLOR]".format(_t(30203).format(current_count))
    )
    li.setArt({"icon": "DefaultFavourites.png"})
    directory_items = [
        (build_url({"mode": "pvr_favs_group_current", "group": group}), li, False)
    ]
    # Search
    li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30204)))
    li.setArt({"icon": "DefaultAddonsSearch.png"})
    directory_items.append((build_url({"mode": "pvr_favs_group_search", "group": group}), li, False))
    # Categories - filter out hidden (use PVR profile's hidden lists)
    pvr_pnum = _get_pvr_profile_num()
    cats = _get_cached_xtream_categories(url, user, pwd, "live")
    hidden_live = _get_hidden_subcats("live", pvr_pnum)
    for c in cats or []:
        cat_id = str(c.get("category_id", ""))
        if cat_id in hidden_live:
            continue
        cat_name = c.get("category_name", "Unknown")
        li = _new_listitem(cat_name)
        li.setArt({"icon": "DefaultFolder.png"})
        q = {
            "mode": "pvr_favs_manage_cat",
            "cat_id": cat_id,
            "cat_name": cat_name,
            "group": group,
        }
        directory_items.append((build_url(q), li, False))
    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def pvr_favs_group_current(group):
    """Multiselect dialog to keep/remove channels in a PVR group."""
    items = _pvr_favs_load(group)
    if not items:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30101))
        return
    dialog = xbmcgui.Dialog()
    names = [ch.get("name", "Unknown") for ch in items]
    preselect = list(range(len(items)))
    result = dialog.multiselect(_t(30330, group), names, preselect=preselect)
    if result is None:
        return
    if len(result) == len(items):
        return
    new_favs = [items[i] for i in result]
    _pvr_favs_save(new_favs, group)
    _sync_pvr_favorites_safe()
    removed = len(items) - len(new_favs)
    dialog.notification("Xstream Pro", _t(30168, removed))
    xbmc.sleep(_tvos_sleep(1500))
    dialog.ok("Xstream Pro", _t(30727))
    xbmc.executebuiltin("Container.Refresh")


def _pvr_search_history_slug(value):
    try:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "Favorites")).strip("_") or "Favorites"
    except Exception:
        return "Favorites"


def _pvr_search_history_path(kind, group):
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    name = "pvr_search_history_{0}_{1}.json".format(kind, _pvr_search_history_slug(group))
    return os.path.join(profile, name)


def _pvr_load_search_history(kind, group):
    try:
        with open(_pvr_search_history_path(kind, group), "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _pvr_save_search_history(kind, group, history):
    path = _pvr_search_history_path(kind, group)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(history[:10], handle, ensure_ascii=False)
    os.replace(tmp, path)


def _pvr_update_search_history(kind, group, query):
    if not query:
        return
    history = _pvr_load_search_history(kind, group)
    if query in history:
        history.remove(query)
    history.insert(0, query)
    _pvr_save_search_history(kind, group, history)


def _pvr_search_history_menu(mode, group, kind):
    history = _pvr_load_search_history(kind, group)
    items = []
    base = {"mode": mode, "group": group, "new_search": "true"}
    li = _new_listitem(_t(31252))
    li.setArt({"icon": _local_icon("search")})
    items.append((build_url(base), li, True))
    for entry in history:
        q = {"mode": mode, "group": group, "query": entry}
        li = _new_listitem(entry)
        li.setArt({"icon": _local_icon("search")})
        items.append((build_url(q), li, True))
    xbmcplugin.setContent(addon_handle, "files")
    xbmcplugin.addDirectoryItems(addon_handle, items, len(items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def pvr_favs_group_search(group, query="", new_search=False, prompt=True):
    """Search channels and multiselect to add/remove from a PVR group."""
    dialog = xbmcgui.Dialog()
    query = str(query or "").strip()
    if not query and new_search:
        query = dialog.input(_t(30146))
        if not query:
            return
        _pvr_update_search_history("live", group, query)
    elif not query and prompt:
        _pvr_search_history_menu("pvr_favs_group_search", group, "live")
        return
    if not query:
        return
    _pvr_update_search_history("live", group, query)
    creds = _get_pvr_credentials()
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    streams = _get_cached_xtream_streams(url, user, pwd, "live")
    pvr_pnum = _get_pvr_profile_num()
    hidden_live = _get_hidden_subcats("live", pvr_pnum)
    hidden_items = _get_hidden_items("live", pvr_pnum)
    if not streams:
        dialog.notification("Xstream Pro", _t(30067))
        return
    query_lower = query.lower()
    filtered = [
        s
        for s in streams
        if query_lower in s.get("name", "").lower()
        and str(s.get("category_id", "")) not in hidden_live
        and str(s.get("stream_id", "")) not in hidden_items
    ]
    if not filtered:
        dialog.notification("Xstream Pro", _t(30067))
        return
    _pvr_favs_multiselect(filtered, dialog, group)


def pvr_favs_manage_cat(cat_id, cat_name, group):
    """Pick a category: add entire or multiselect individual channels for a PVR group."""
    dialog = xbmcgui.Dialog()
    action = dialog.select(cat_name, [_t(30331, group), _t(30332)])
    if action < 0:
        return
    creds = _get_pvr_credentials()
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    streams = _get_cached_xtream_streams(url, user, pwd, "live")
    pvr_pnum = _get_pvr_profile_num()
    hidden_items = _get_hidden_items("live", pvr_pnum)
    filtered = [
        s
        for s in (streams or [])
        if str(s.get("category_id", "")) == cat_id
        and str(s.get("stream_id", "")) not in hidden_items
    ]
    if not filtered:
        dialog.notification("Xstream Pro", _t(30068))
        return
    if action == 0:
        current_favs = _pvr_favs_load(group)
        fav_ids = {str(i.get("stream_id", "")) for i in current_favs}
        added = 0
        for s in filtered:
            if str(s.get("stream_id", "")) not in fav_ids:
                current_favs.append(s)
                added += 1
        _pvr_favs_save(current_favs, group)
        _sync_pvr_favorites_safe()
        dialog.notification("Xstream Pro", _t(30169, added))
        xbmc.sleep(_tvos_sleep(1500))
        dialog.ok("Xstream Pro", _t(30727))
        xbmc.executebuiltin("Container.Refresh")
        return
    _pvr_favs_multiselect(filtered, dialog, group)


def _pvr_favs_multiselect(filtered, dialog, group=None):
    """Multiselect channels to add/remove from a PVR group."""
    if group is None:
        group = _t(30703) or "Favorites"
    names = [s.get("name", "Unknown") for s in filtered]
    current_favs = _pvr_favs_load(group)
    fav_ids = {str(i.get("stream_id", "")) for i in current_favs}
    preselect = [
        i for i, s in enumerate(filtered) if str(s.get("stream_id", "")) in fav_ids
    ]
    result = dialog.multiselect(_t(30151, group), names, preselect=preselect)
    if result is None:
        return
    filtered_ids = {str(s.get("stream_id", "")) for s in filtered}
    new_favs = [
        f for f in current_favs if str(f.get("stream_id", "")) not in filtered_ids
    ]
    for i in result or []:
        new_favs.append(filtered[i])
    _pvr_favs_save(new_favs, group)
    _sync_pvr_favorites_safe()
    dialog.notification("Xstream Pro", _t(30170, len(new_favs), group))
    xbmc.sleep(_tvos_sleep(1500))
    dialog.ok("Xstream Pro", _t(30727))
    xbmc.executebuiltin("Container.Refresh")


def _sports_pvr_item_key(ch):
    return str(ch.get("stream_id", "") or ch.get("tvg_id", "") or ch.get("url", ""))


def _sports_pvr_source_country_groups():
    groups = {}
    for ch in _sports_pvr_source_channels() or []:
        label = ch.get("group", "") or "Other Countries"
        for pfx in PVR_LEGACY_SPORTS_PREFIXES:
            if label.startswith(pfx):
                label = label[len(pfx):]
                break
        label = label.strip() or "Other Countries"
        groups.setdefault(label, []).append(ch)
    return sorted(
        groups.items(),
        key=lambda item: (item[0] == "Other Countries", item[0].lower()),
    )


def sports_pvr_favorites_manager(group=None):
    """PVR Favorites Manager - groups with channels, similar to Live TV PVR Favorites Manager."""
    groups = _sports_pvr_favs_load_all()

    if group is None:
        directory_items = []
        for gname, items in groups.items():
            count = len(items)
            li = _new_listitem(_t(30272).format(gname, count))
            li.setArt({"icon": "DefaultFavourites.png"})
            ctx_items = [
                (
                    _t(30320),
                    f"RunPlugin({build_url({'mode': 'sports_pvr_favs_rename_group', 'group': gname})})",
                ),
                (
                    _t(30321),
                    f"RunPlugin({build_url({'mode': 'sports_pvr_favs_delete_group', 'group': gname})})",
                ),
            ]
            li.addContextMenuItems(ctx_items)
            q = {"mode": "sports_pvr_favorites_manager", "group": gname}
            directory_items.append((build_url(q), li, True))
        li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30200)))
        directory_items.append((build_url({"mode": "sports_pvr_favs_new_group"}), li, False))
        if directory_items:
            xbmcplugin.addDirectoryItems(addon_handle, directory_items)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        return

    items = groups.get(group, [])
    directory_items = []
    li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30201)))
    li.setArt({"icon": "DefaultAddonService.png"})
    directory_items.append((build_url({"mode": "sports_pvr_favs_manage_group", "group": group}), li, True))

    if not items:
        li = _new_listitem("[COLOR gray]{0}[/COLOR]".format(_t(30202)))
        directory_items.append(("", li, False))
    else:
        for ch in items:
            name = ch.get("name", "Unknown")
            icon = ch.get("logo", "") or ch.get("stream_icon", "")
            sid = _sports_pvr_item_key(ch)
            li = _new_listitem(name)
            li.setArt({"icon": icon, "thumb": icon})
            li.setProperty("IsPlayable", "true")
            _prepare_playback_item(li)
            _set_live_props(li)
            ctx_items = [
                (
                    _t(30322),
                    f"RunPlugin({build_url({'mode': 'sports_pvr_fav_remove', 'stream_id': sid, 'group': group})})",
                ),
            ]
            li.addContextMenuItems(ctx_items)
            q = {
                "mode": "play_stream",
                "url": ch.get("url", ""),
                "name": name,
                "icon": icon,
                "stype": "live",
                "profile_num": ch.get("profile_num", _get_sports_pvr_profile_num()),
            }
            directory_items.append((build_url(q), li, False))

    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def sports_pvr_favs_manage(group=None):
    sports_pvr_favs_manage_group(group or "Favorites")


def sports_pvr_favs_manage_group(group):
    """Category browser for adding channels to a specific Sports PVR group."""
    current_count = len(_sports_pvr_favs_load(group))
    li = _new_listitem(
        "[COLOR gold]{0}[/COLOR]".format(_t(30203).format(current_count))
    )
    li.setArt({"icon": "DefaultFavourites.png"})
    directory_items = [
        (build_url({"mode": "sports_pvr_favs_group_current", "group": group}), li, False)
    ]
    li = _new_listitem("[COLOR yellow]{0}[/COLOR]".format(_t(30204)))
    li.setArt({"icon": "DefaultAddonsSearch.png"})
    directory_items.append((build_url({"mode": "sports_pvr_favs_group_search", "group": group}), li, False))
    for country, _channels in _sports_pvr_source_country_groups():
        li = _new_listitem(country)
        li.setArt({"icon": "DefaultFolder.png"})
        q = {
            "mode": "sports_pvr_favs_manage_country",
            "country": country,
            "group": group,
        }
        directory_items.append((build_url(q), li, False))
    if directory_items:
        xbmcplugin.addDirectoryItems(addon_handle, directory_items, len(directory_items))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def sports_pvr_favs_group_current(group):
    """Multiselect dialog to keep/remove channels in a Sports PVR group."""
    items = _sports_pvr_favs_load(group)
    if not items:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30101))
        return
    dialog = xbmcgui.Dialog()
    names = [ch.get("name", "Unknown") for ch in items]
    preselect = list(range(len(items)))
    result = dialog.multiselect(_t(30330, group), names, preselect=preselect)
    if result is None:
        return
    if len(result) == len(items):
        return
    new_favs = [items[i] for i in result]
    _sports_pvr_favs_save(new_favs, group)
    addon.setSetting("sports_pvr_enabled", "true")
    _sync_sports_pvr_safe()
    removed = len(items) - len(new_favs)
    dialog.notification("Xstream Pro", _t(30168, removed))
    xbmc.sleep(_tvos_sleep(1500))
    dialog.ok("Xstream Pro", _t(30727))
    xbmc.executebuiltin("Container.Refresh")


def sports_pvr_favs_group_search(group, query="", new_search=False, prompt=True):
    """Search sports channels and multiselect to add/remove from a Sports PVR group."""
    dialog = xbmcgui.Dialog()
    query = str(query or "").strip()
    if not query and new_search:
        query = dialog.input(_t(30146))
        if not query:
            return
        _pvr_update_search_history("sports", group, query)
    elif not query and prompt:
        _pvr_search_history_menu("sports_pvr_favs_group_search", group, "sports")
        return
    if not query:
        return
    _pvr_update_search_history("sports", group, query)
    channels = _sports_pvr_source_channels()
    if not channels:
        dialog.notification("Xstream Pro", _t(30067))
        return
    query_lower = query.lower()
    filtered = [
        ch for ch in channels
        if query_lower in ch.get("name", "").lower()
    ]
    if not filtered:
        dialog.notification("Xstream Pro", _t(30067))
        return
    _sports_pvr_favs_multiselect(filtered, dialog, group)


def sports_pvr_favs_manage_country(country, group):
    """Pick a country: multiselect individual channels for a Sports PVR group."""
    dialog = xbmcgui.Dialog()
    for cname, channels in _sports_pvr_source_country_groups():
        if cname == country:
            filtered = channels
            break
    else:
        dialog.notification("Xstream Pro", _t(30068))
        return
    if not filtered:
        dialog.notification("Xstream Pro", _t(30068))
        return
    _sports_pvr_favs_multiselect(filtered, dialog, group)


def _sports_pvr_favs_multiselect(filtered, dialog, group=None):
    """Multiselect channels to add/remove from a Sports PVR group."""
    if group is None:
        group = _t(30703) or "Favorites"
    names = [s.get("name", "Unknown") for s in filtered]
    current_favs = _sports_pvr_favs_load(group)
    fav_ids = {_sports_pvr_item_key(i) for i in current_favs}
    preselect = [
        i for i, s in enumerate(filtered) if _sports_pvr_item_key(s) in fav_ids
    ]
    result = dialog.multiselect(_t(30151, group), names, preselect=preselect)
    if result is None:
        return
    filtered_ids = {_sports_pvr_item_key(s) for s in filtered}
    new_favs = [
        f for f in current_favs if _sports_pvr_item_key(f) not in filtered_ids
    ]
    for i in result or []:
        new_favs.append(filtered[i])
    _sports_pvr_favs_save(new_favs, group)
    addon.setSetting("sports_pvr_enabled", "true")
    _sync_sports_pvr_safe()
    dialog.notification("Xstream Pro", _t(30170, len(new_favs), group))
    xbmc.sleep(_tvos_sleep(1500))
    dialog.ok("Xstream Pro", _t(30727))
    xbmc.executebuiltin("Container.Refresh")


def sports_pvr_favs_new_group():
    dialog = xbmcgui.Dialog()
    name = dialog.input(_t(30147))
    if name:
        groups = _sports_pvr_favs_load_all()
        if name in groups:
            dialog.notification("Xstream Pro", _t(30125))
        else:
            groups[name] = []
            _sports_pvr_favs_save_all(groups)
            dialog.notification("Xstream Pro", _t(30126, name))
            xbmc.sleep(_tvos_sleep(1500))
            dialog.ok("Xstream Pro", _t(30727))
            xbmc.executebuiltin("Container.Refresh")


def sports_pvr_favs_rename_group():
    old_name = args.get("group", [""])[0]
    dialog = xbmcgui.Dialog()
    new_name = dialog.input(_t(30148), defaultt=old_name)
    if new_name and new_name != old_name:
        groups = _sports_pvr_favs_load_all()
        if new_name in groups:
            dialog.notification("Xstream Pro", _t(30125))
        elif old_name in groups:
            items = groups.pop(old_name)
            groups[new_name] = items
            _sports_pvr_favs_save_all(groups)
            addon.setSetting("sports_pvr_enabled", "true")
            _sync_sports_pvr_safe()
            dialog.notification("Xstream Pro", _t(30178, new_name))
            xbmc.executebuiltin("Container.Refresh")


def sports_pvr_favs_delete_group():
    group_name = args.get("group", [""])[0]
    dialog = xbmcgui.Dialog()
    if dialog.yesno(_t(30038), _t(30252, group_name)):
        groups = _sports_pvr_favs_load_all()
        if group_name in groups:
            del groups[group_name]
            _sports_pvr_favs_save_all(groups)
            addon.setSetting("sports_pvr_enabled", "true")
            _sync_sports_pvr_safe()
            dialog.notification("Xstream Pro", _t(30179, group_name))
            xbmc.executebuiltin("Container.Refresh")


def sports_pvr_fav_remove(stream_id, group=None):
    group = group or "Favorites"
    items = _sports_pvr_favs_load(group)
    sid = str(stream_id)
    new_items = [
        ch for ch in items
        if _sports_pvr_item_key(ch) != sid
    ]
    if len(new_items) != len(items):
        _sports_pvr_favs_save(new_items, group)
        addon.setSetting("sports_pvr_enabled", "true")
        _sync_sports_pvr_safe()
    xbmc.executebuiltin("Container.Refresh")


def _sports_pvr_favs_load_all():
    try:
        with open(_sports_pvr_favs_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, list):
        return {"Favorites": data} if data else {}
    return data if isinstance(data, dict) else {}


def _sports_pvr_favs_save_all(groups):
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    favs_path = _sports_pvr_favs_path()
    tmp_file = favs_path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp_file, favs_path)


def _sports_pvr_favs_load(group=None):
    groups = _sports_pvr_favs_load_all()
    if group:
        return groups.get(group, [])
    out = []
    for items in groups.values():
        out.extend(items)
    return out


def _sports_pvr_favs_save(items, group=None):
    group = group or "Favorites"
    groups = _sports_pvr_favs_load_all()
    groups[group] = items
    _sports_pvr_favs_save_all(groups)


def _export_sports_pvr_favs_m3u():
    groups = _sports_pvr_favs_load_all()
    pnum = _get_sports_pvr_profile_num()
    channels = []
    for gname, items in groups.items():
        for ch in items:
            item = dict(ch)
            item["group"] = f"★ Sports Favorites - {gname}"
            channels.append(item)
    channels = _apply_pvr_catchup_corrections(channels, pnum, "Sports PVR Favorites")
    channels = _prepare_sports_pvr_channels_for_export(channels, pnum)
    m3u_path = _sports_pvr_favs_m3u_path()
    if not channels:
        _atomic_write_text(m3u_path, "#EXTM3U\n")
        return m3u_path
    m3u_data = build_m3u_content(channels)
    tmp = m3u_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(m3u_data)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp, m3u_path)
    _log(f"Sports PVR Favorites: Exported M3U with {len(channels)} channels")
    return m3u_path

