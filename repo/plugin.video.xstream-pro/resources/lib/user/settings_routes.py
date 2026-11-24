"""Settings workflow route helpers for Xstream Pro."""

import re

_OWNED = {'_validate_settings', '_snapshot_credentials', '_detect_credential_changes', '_is_pvr_profile', '_prompt_load_single_profile', '_prompt_load_multiple_profiles', '_prompt_sync_pvr_if_needed', '_snapshot_pvr_replay_settings', 'settings', '_prompt_load_profiles_after_restore'}


def _provider_availability_marking_enabled():
    return (
        addon.getSetting("tmdb_provider_only_available").lower() == "true"
        or addon.getSetting("tmdb_mark_unavailable").lower() == "true"
    )


def _safe_setting_log_value(value):
    value = str(value or "")
    if not value:
        return "(none)"
    if "://" in value:
        return "<redacted-url>"
    if len(value) > 80:
        return value[:77] + "..."
    return value


def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _validate_settings():
    """Validate settings after user closes settings dialog."""
    from iptv import _validate_url

    _normalize_parental_pin()
    creds = _get_credentials()
    xt_url = creds.get("xtream_url", "")
    m3u_url = creds.get("m3u", "")
    for label, url in [(_t(30566), xt_url), (_t(30567), m3u_url)]:
        if not url:
            continue
        validated = _validate_url(url, allow_http=True)
        if not validated:
            xbmcgui.Dialog().notification(
                "Xstream Pro", _t(30308, label), xbmcgui.NOTIFICATION_WARNING, 5000
            )
        elif (
            url.startswith("http://")
            and addon.getSetting("warn_http").lower() == "true"
        ):
            xbmcgui.Dialog().notification(
                "Xstream Pro", _t(30309, label), xbmcgui.NOTIFICATION_WARNING, 3000
            )
            _log(f"Warning: {label} uses insecure HTTP connection")


def _snapshot_credentials():
    snapshot = {}
    keys = (
        "enabled",
        "source_type",
        "m3u",
        "xtream_url",
        "xtream_username",
        "xtream_password",
        "epg_m3u",
        "epg_xtream",
        "load_live",
        "load_movies",
        "load_series",
    )
    for n in range(1, 11):
        snapshot[n] = {
            key: _get_setting_direct(f"profile_{n}_{key}", "")
            for key in keys
        }
    _log("Credential snapshot taken for profiles 1-10.")
    return snapshot


def _detect_credential_changes(snapshot):
    added = []
    removed = []
    modified = []
    keys = (
        "enabled",
        "source_type",
        "m3u",
        "xtream_url",
        "xtream_username",
        "xtream_password",
        "epg_m3u",
        "epg_xtream",
        "load_live",
        "load_movies",
        "load_series",
    )
    for n in range(1, 11):
        current = {
            key: _get_setting_direct(f"profile_{n}_{key}", "")
            for key in keys
        }
        if snapshot.get(n) == current:
            continue
        had_creds = bool(snapshot.get(n, {}).get("xtream_url") or snapshot.get(n, {}).get("m3u"))
        has_creds = bool(current.get("xtream_url") or current.get("m3u"))
        if has_creds and not had_creds:
            added.append(n)
        elif had_creds and not has_creds:
            removed.append(n)
        elif had_creds and has_creds:
            modified.append(n)
        old_source = snapshot.get(n, {}).get("xtream_url", "") or snapshot.get(n, {}).get("m3u", "")
        new_source = current.get("xtream_url", "") or current.get("m3u", "")
        _log(
            "Profile {0} credential change: had_creds={1} has_creds={2} "
            "old_url={3} new_url={4}".format(
                n,
                had_creds,
                has_creds,
                _safe_setting_log_value(old_source),
                _safe_setting_log_value(new_source),
            )
        )
    return added, removed, modified


def _is_pvr_profile(pnum):
    """Check if a profile number is the currently active PVR profile."""
    pvr_profile = addon.getSetting("active_pvr_profile") or "Profile 1"
    match = re.search(r"(\d+)", pvr_profile)
    pvr_num = int(match.group(1)) if match else 1
    return int(pnum) == pvr_num


def _prompt_load_single_profile(pnum):
    dialog = xbmcgui.Dialog()
    profile_name = addon.getSetting(f"profile_{pnum}_name") or _t(30390, pnum)
    is_pvr = _is_pvr_profile(pnum)
    msg = _t(30861, profile_name) if is_pvr else _t(30862, profile_name)
    if dialog.yesno("Xstream Pro", msg):
        _refresh_profile_data(pnum)
        return [pnum]
    return []


def _prompt_load_multiple_profiles(changed_profiles):
    """Show multi-select dialog for loading changed profiles. Returns list of loaded profiles."""
    dialog = xbmcgui.Dialog()
    options = []
    preselect = []
    idx_map = []

    for pnum in changed_profiles:
        profile_name = addon.getSetting(f"profile_{pnum}_name") or _t(30390, pnum)
        has_creds = bool(
            addon.getSetting(f"profile_{pnum}_xtream_url")
            or addon.getSetting(f"profile_{pnum}_m3u")
        )

        if has_creds:
            is_pvr = _is_pvr_profile(pnum)
            label = f"{profile_name} {_t(30863) if is_pvr else ''}"
            options.append(label)
            preselect.append(len(options) - 1)
            idx_map.append(pnum)
        else:
            # Grey out empty profiles
            options.append(f"[COLOR grey]{profile_name} ({_t(30864)})[/COLOR]")
            idx_map.append(None)

    if not options:
        return []

    result = dialog.multiselect(_t(30865), options, preselect=preselect)
    if result is None:
        return []

    loaded = []
    for idx in result:
        pnum = idx_map[idx]
        if pnum is not None:
            _refresh_profile_data(pnum)
            loaded.append(pnum)

    return loaded


def _prompt_sync_pvr_if_needed(loaded_profiles):
    """Offer PVR sync if any loaded profile is the PVR profile.

    Handles restore-time deferred sync: if restore set the deferred flag,
    clear it and only prompt if the PVR-linked profile was actually loaded.
    """
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    defer_flag = os.path.join(profile_path, "pvr_sync_after_profile_load.flag")

    deferred = os.path.exists(defer_flag)
    if deferred:
        pvr_loaded = any(_is_pvr_profile(p) for p in loaded_profiles)
        if not pvr_loaded:
            _log("PVR sync deferred — PVR-linked profile not loaded yet")
            return
        _log("Restore-time deferred PVR sync — PVR-linked profile loaded")

    if not loaded_profiles:
        return

    pvr_loaded = any(_is_pvr_profile(p) for p in loaded_profiles)

    retry_flag = os.path.join(profile_path, "pvr_sync_retry_needed.flag")
    pending_sync = deferred or os.path.exists(retry_flag)

    pvr_installed = _is_pvr_iptvsimple_installed_or_disabled()
    _log(
        f"PVR sync check: loaded_profiles={loaded_profiles}, "
        f"pvr_loaded={pvr_loaded}, pvr_installed={pvr_installed}, "
        f"pending_sync={pending_sync}"
    )

    if not pvr_loaded:
        return

    if not pvr_installed and not pending_sync:
        return

    if not pvr_installed and pending_sync:
        _log("PVR sync pending while IPTV Simple reports not installed/disabled — allowing sync to continue")

    # Allow previous dialog to fully close before showing PVR prompt
    xbmc.sleep(_tvos_sleep(500))

    dialog = xbmcgui.Dialog()
    if dialog.yesno("Xstream Pro", _t(30866)):
        ok = _sync_pvr_force()
        if ok:
            if deferred and os.path.exists(defer_flag):
                os.remove(defer_flag)
            _log("PVR sync triggered after profile load")
        else:
            retry_flag = os.path.join(profile_path, "pvr_sync_retry_needed.flag")
            with open(retry_flag, "w", encoding="utf-8") as f:
                f.write("1")
    else:
        # User declined — flag for startup retry
        retry_flag = os.path.join(profile_path, "pvr_sync_retry_needed.flag")
        with open(retry_flag, "w", encoding="utf-8") as f:
            f.write("1")
        _log("PVR sync deferred after profile load, flagged for startup retry")


def _snapshot_pvr_replay_settings():
    keys = (
        "pvr_catchup_enabled",
        "pvr_catchup_days",
        "pvr_catchup_correction_mode",
        "pvr_catchup_correction",
        "pvr_epg_refresh",
    )
    return {key: _get_setting_direct(key, addon.getSetting(key) or "") for key in keys}


def _snapshot_buffer_settings():
    keys = ("buffer_fix_enabled", "buffer_size_mb", "buffer_read_factor")
    return {key: addon.getSetting(key) or "" for key in keys}


def _set_xml_child(parent, tag, value):
    import xml.etree.ElementTree as _ET

    child = parent.find(tag)
    if child is None:
        child = _ET.SubElement(parent, tag)
    child.text = str(value)


def _apply_buffer_settings_if_needed(before):
    after = _snapshot_buffer_settings()
    if before == after:
        return

    import shutil as _shutil
    import xml.etree.ElementTree as _ET

    enabled = after.get("buffer_fix_enabled", "").lower() == "true"
    profile_path = xbmcvfs.translatePath("special://profile")
    try:
        os.makedirs(profile_path, exist_ok=True)
    except Exception:
        pass
    advanced_path = os.path.join(profile_path, "advancedsettings.xml")
    backup_path = advanced_path + ".xstream-pro.bak"

    if os.path.exists(advanced_path):
        if not os.path.exists(backup_path):
            try:
                _shutil.copy2(advanced_path, backup_path)
            except Exception as exc:
                _log("Buffer settings backup warning: {0}".format(exc))
        try:
            tree = _ET.parse(advanced_path)
            root = tree.getroot()
        except Exception as exc:
            _log(
                "Buffer settings: advancedsettings.xml parse failed; leaving existing file untouched: {0}".format(exc)
            )
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Buffer settings not applied. Fix advancedsettings.xml first.",
                xbmcgui.NOTIFICATION_WARNING,
                5000,
            )
            return
    else:
        root = _ET.Element("advancedsettings")
        tree = _ET.ElementTree(root)

    cache = root.find("cache")
    if enabled:
        if cache is None:
            cache = _ET.SubElement(root, "cache")
        try:
            memory_size = max(0, int(after.get("buffer_size_mb") or "100")) * 1024 * 1024
        except Exception:
            memory_size = 100 * 1024 * 1024
        try:
            read_factor = float(after.get("buffer_read_factor") or "20")
        except Exception:
            read_factor = 20.0
        _set_xml_child(cache, "buffermode", "1")
        _set_xml_child(cache, "memorysize", memory_size)
        _set_xml_child(cache, "readfactor", read_factor)
        action = "updated"
    else:
        if cache is not None:
            for tag in ("buffermode", "memorysize", "readfactor"):
                child = cache.find(tag)
                if child is not None:
                    cache.remove(child)
            if len(list(cache)) == 0:
                root.remove(cache)
        action = "removed"

    try:
        _ET.indent(tree, space="  ")
    except Exception:
        pass
    tmp_path = advanced_path + ".tmp"
    with open(tmp_path, "wb") as handle:
        tree.write(handle, encoding="utf-8", xml_declaration=True)
        try:
            handle.flush()
            _safe_fsync(handle)
        except OSError:
            pass
    os.replace(tmp_path, advanced_path)
    addon.setSetting("buffer_fix_needs_restart", "true")
    xbmcgui.Dialog().notification(
        "Xstream Pro",
        "Buffer settings {0}. Restart Kodi to apply.".format(action),
        xbmcgui.NOTIFICATION_INFO,
        5000,
    )


def settings():
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
    if not _check_pin("Settings"):
        return
    _log("Settings opened.")

    # Snapshot credentials before settings change
    cred_snapshot = _snapshot_credentials()
    pvr_replay_snapshot = _snapshot_pvr_replay_settings()
    buffer_snapshot = _snapshot_buffer_settings()
    provider_availability_snapshot = _provider_availability_marking_enabled()
    fallback_snapshot = (
        str(
            _get_setting_direct(
                "pvr_epg_fallback_enabled",
                addon.getSetting("pvr_epg_fallback_enabled") or "false",
            )
            or "false"
        ).lower()
        == "true"
    )

    addon.openSettings()
    _invalidate_settings_xml_cache()
    _invalidate_fast_setting_cache()
    _validate_settings()
    _apply_buffer_settings_if_needed(buffer_snapshot)

    pvr_replay_changed = _snapshot_pvr_replay_settings() != pvr_replay_snapshot
    provider_availability_changed = _provider_availability_marking_enabled() != provider_availability_snapshot
    fallback_enabled_now = addon.getSetting("pvr_epg_fallback_enabled").lower() == "true"

    # Detect changes and prompt immediately
    added_profiles, removed_profiles, modified_profiles = _detect_credential_changes(cred_snapshot)
    profiles_to_reload = added_profiles + modified_profiles
    if profiles_to_reload:
        _log("Credential changes detected (reload): {0}".format(profiles_to_reload))
        if len(profiles_to_reload) == 1:
            loaded = _prompt_load_single_profile(profiles_to_reload[0])
            _prompt_sync_pvr_if_needed(loaded)
        else:
            loaded = _prompt_load_multiple_profiles(profiles_to_reload)
            _prompt_sync_pvr_if_needed(loaded)
    if removed_profiles:
        _log("Credential changes detected (removed): {0}".format(removed_profiles))
        for pnum in removed_profiles:
            name = addon.getSetting(f"profile_{pnum}_name") or _t(30390, pnum)
            if xbmcgui.Dialog().yesno(
                _t(30770), _t(30809, name), nolabel=_t(30163), yeslabel=_t(30162)
            ):
                count = _purge_profile_data(pnum)
                _log("Cleared {0} files for profile {1}".format(count, pnum))

    if not fallback_snapshot and fallback_enabled_now:
        _log("PVR EPG fallback enabled in settings")
        if xbmcgui.Dialog().yesno(
            "Xstream Pro",
            "EPG fallback was enabled.\n\nSync PVR EPG now?",
            yeslabel="Sync EPG",
            nolabel="Later",
        ):
            _sync_pvr_epg_only(offer_reload=True)
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "EPG fallback applies after PVR EPG sync.",
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )

    if pvr_replay_changed and is_pvr_iptvsimple_installed():
        _log("PVR replay settings changed")
        if xbmcgui.Dialog().yesno(
            "Xstream Pro",
            "PVR replay settings changed. Reload PVR now?"
        ):
            if not _sync_pvr_force():
                xbmcgui.Dialog().notification(
                    "Xstream Pro",
                    "PVR reload failed. Try Force Reload PVR.",
                    xbmcgui.NOTIFICATION_WARNING,
                    5000,
                )
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Replay changes apply after next PVR reload.",
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )

    if provider_availability_changed:
        if _provider_availability_marking_enabled():
            _rebuild_provider_availability_cache(show_progress=True)
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Provider availability cache updated.",
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )
        else:
            if xbmcgui.Dialog().yesno(
                "Xstream Pro",
                "Provider availability marking/filtering was disabled.\n\nDelete its availability cache?"
            ):
                _clear_provider_availability_cache()

    try:
        _configure_kodi_pvr_osd()
        _install_pvr_keymap()
    except Exception as e:
        _log(f"PVR keymap refresh after settings error: {e}")

    _log("Settings closed.")


def _prompt_load_profiles_after_restore():
    """If restore just completed, prompt to load profiles before PVR sync."""
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    defer_flag = os.path.join(profile_path, "pvr_sync_after_profile_load.flag")

    if not os.path.exists(defer_flag):
        return

    # Find all enabled profiles with credentials
    enabled_profiles = []
    for n in range(1, 11):
        if addon.getSetting(f"profile_{n}_enabled") == "true":
            has_xtream = bool(addon.getSetting(f"profile_{n}_xtream_url"))
            has_m3u = bool(addon.getSetting(f"profile_{n}_m3u"))
            if has_xtream or has_m3u:
                enabled_profiles.append(n)

    if not enabled_profiles:
        _log("Restore deferred flag set but no enabled profiles with credentials found")
        os.remove(defer_flag)
        return

    # Show multi-select dialog for loading restored profiles
    dialog = xbmcgui.Dialog()
    options = []
    preselect = []
    for pnum in enabled_profiles:
        profile_name = addon.getSetting(f"profile_{pnum}_name") or _t(30390, pnum)
        is_pvr = _is_pvr_profile(pnum)
        label = f"{profile_name} {_t(30863) if is_pvr else ''}"
        options.append(label)
        preselect.append(len(options) - 1)

    result = dialog.multiselect(_t(30887), options, preselect=preselect)
    if result is None:
        # User cancelled — keep flag so they can load profiles later
        _log("User cancelled profile load after restore")
        return

    selected_profiles = [enabled_profiles[idx] for idx in result]
    loaded = _refresh_profiles_batch(selected_profiles)

    if loaded:
        _log(f"Loaded profiles after restore: {loaded}")
        _prompt_sync_pvr_if_needed(loaded)
    else:
        _log("No profiles selected for loading after restore")


