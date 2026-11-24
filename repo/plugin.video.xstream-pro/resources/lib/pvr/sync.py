"""PVR sync/reset orchestration helpers for Xstream Pro."""

import os
import time

_OWNED = {'is_pvr_iptvsimple_installed', '_is_pvr_iptvsimple_installed_or_disabled', 'prompt_install_pvr', '_pvr_sync_lock_path', '_acquire_pvr_sync_lock', '_release_pvr_sync_lock', '_sync_pvr_force', '_sync_pvr_epg_only', '_remove_owned_pvr_instances', '_unload_pvr', 'reset_pvr_epg_db_action', '_maybe_show_pvr_first_run', 'sync_sports_pvr', 'switch_sports_pvr_profile', '_pvr_progress', '_sync_sports_pvr_during_pvr_sync', '_sync_sports_pvr_safe', 'reset_stale_channel_epg_ids', 'check_stale_channel_epg_ids'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def is_pvr_iptvsimple_installed():
    try:
        addon = xbmcaddon.Addon("pvr.iptvsimple")
        _log(f"PVR: IPTV Simple found, version={addon.getAddonInfo('version')}")
        return True
    except Exception as e:
        _log(f"PVR: IPTV Simple not installed: {e}")
        return False


def _is_pvr_iptvsimple_installed_or_disabled():
    return _pvr_instances._is_pvr_iptvsimple_installed_or_disabled()


def prompt_install_pvr():
    dlg = xbmcgui.Dialog()
    choice = dlg.yesno(_t(30560), _t(30561), yeslabel=_t(30182), nolabel=_t(30161))
    if choice:
        xbmc.executebuiltin("InstallAddon(pvr.iptvsimple)")
        # Wait for installation and notify
        for _ in range(30):
            xbmc.sleep(_tvos_sleep(1000))
            if is_pvr_iptvsimple_installed():
                xbmcgui.Dialog().notification(
                    "Xstream Pro", _t(30100), xbmcgui.NOTIFICATION_INFO, 5000
                )
                return True
    return choice


def _pvr_sync_lock_path():
    return _pvr_paths._pvr_sync_lock_path()


def _acquire_pvr_sync_lock():
    lock_path = _pvr_sync_lock_path()
    if os.path.exists(lock_path):
        try:
            age = time.time() - os.path.getmtime(lock_path)
            if age < 60:
                _log("PVR: Sync already in progress, skipping")
                xbmcgui.Dialog().notification(
                    "Xstream Pro", _t(30794), xbmcgui.NOTIFICATION_WARNING, 3000
                )
                return False
            else:
                _log("PVR: Stale sync lock found, removing")
                os.remove(lock_path)
        except Exception as e:
            _log(f"PVR: Lock check warning: {e}")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(time.time()))
    except FileExistsError:
        _log("PVR: Sync lock race lost, skipping")
        xbmcgui.Dialog().notification(
            "Xstream Pro", _t(30794), xbmcgui.NOTIFICATION_WARNING, 3000
        )
        return False
    except OSError as e:
        _log(f"PVR: Lock create failed: {e}")
        return False
    return True


def _release_pvr_sync_lock():
    try:
        lock_path = _pvr_sync_lock_path()
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception as e:
        _log(f"PVR: Lock release warning: {e}")


def _sync_pvr_force():
    """Sync PVR files and reload pvr.iptvsimple."""
    ok = False
    reload_pvr_addon = False
    epg_sync_ok = True
    if not _acquire_pvr_sync_lock():
        return False
    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", _t(30868))
    try:
        _pvr_export.clear_epg_instance_cache()
        _log("PVR: Starting sync")
        # Foreign Xstream/XStream addon instances are intentionally preserved.
        if not _is_pvr_iptvsimple_installed_or_disabled():
            _log("PVR: IPTV Simple not installed, prompting")
            prompt_install_pvr()
            return False

        try:
            removed_legacy = _cleanup_legacy_xstream_pvr_instances("PVR sync cleanup")
            if removed_legacy:
                _log(f"PVR: removed {removed_legacy} stale old XStream IPTV Simple instance(s) before sync")
        except Exception as e:
            _log(f"PVR: stale old XStream cleanup warning: {e}")

        progress.update(5, _t(30869))
        _log(
            "PVR: preserving foreign IPTV Simple instances; Kodi has no safe "
            "per-instance PVR Manager restart API"
        )
        xbmc.sleep(_tvos_sleep(200))

        progress.update(15, "Preparing IPTV Simple instances")
        _log("PVR: preparing files before IPTV Simple reload; foreign instance files preserved")
        xbmc.sleep(_tvos_sleep(200))

        ok = False
        try:
            try:
                # Kodi owns Epg16.db. Do not delete or truncate it while Kodi is running;
                # pvr.iptvsimple will reload from the generated XMLTV file.
                progress.update(25, _t(30871))
                _log("PVR: skipping Kodi Epg16.db reset during sync")

                # Export M3U and EPG using generated local files.
                progress.update(40, _t(30872))
                if not _export_pvr_m3u():
                    _log("PVR: M3U export failed, aborting sync")
                    xbmcgui.Dialog().notification("Xstream Pro", _t(30893))
                    return False

                # Only export EPG if file is missing, stale by user setting, or empty.
                progress.update(55, _t(30873))
                epg_path = _pvr_epg_path()
                m3u_path = _pvr_m3u_path()
                epg_fallback_rebuild = _pvr_epg_fallback_needs_rebuild(_get_pvr_profile_num(), "live")
                m3u_newer = (
                    os.path.exists(epg_path)
                    and os.path.exists(m3u_path)
                    and os.path.getmtime(m3u_path) > os.path.getmtime(epg_path)
                )
                epg_stale = (
                    not os.path.exists(epg_path)
                    or os.path.getsize(epg_path) == 0
                    or not epg_file_has_data(epg_path)
                    or epg_fallback_rebuild
                    or (
                        os.path.exists(epg_path)
                        and time.time() - os.path.getmtime(epg_path) > _pvr_epg_refresh_seconds()
                    )
                    or m3u_newer
                )
                if epg_fallback_rebuild:
                    _log("PVR: EPG fallback configuration changed, will re-export")
                if m3u_newer:
                    _log("PVR: M3U is newer than EPG file, will re-export")
                if epg_stale:
                    _log("PVR: Existing EPG file is empty or stale, will re-export")
                    epg_export_ok = _export_pvr_epg(force_fetch=True)
                else:
                    _log("PVR: Reusing existing EPG file (fresh)")
                    epg_export_ok = epg_file_has_data(epg_path)
                epg_match_ok = _validate_pvr_epg_m3u_match(_pvr_m3u_path(), epg_path)
                epg_sync_ok = bool(epg_export_ok and epg_match_ok)
                if not epg_export_ok:
                    _log("PVR WARNING: Live channels exported, but EPG export failed or produced no programmes")
                elif not epg_match_ok:
                    _log("PVR WARNING: Live channels exported, but EPG programme rows do not match M3U tvg-ids")
                if not epg_sync_ok:
                    try:
                        xbmcgui.Dialog().notification(
                            "Xstream Pro",
                            "PVR channels synced. EPG failed or did not match channels.",
                            xbmcgui.NOTIFICATION_WARNING,
                            5000,
                        )
                    except Exception:
                        pass

                # Configure Xstream-owned PVR instances without touching foreign instances.
                progress.update(70, _t(30874))
                if not _confirm_large_pvr_list(_pvr_m3u_path(), "Live TV PVR"):
                    _log("PVR: user cancelled large Live TV PVR load")
                    return False
                if not _configure_pvr_iptvsimple():
                    _log("PVR: IPTV Simple configuration failed, aborting sync")
                    return False

                # Configure favorites instance before requesting Kodi's PVR refresh.
                if addon.getSetting("pvr_favorites_enabled").lower() == "true":
                    _export_pvr_favs_m3u()
                    if _m3u_file_has_channels(_pvr_favs_m3u_path()):
                        _configure_pvr_favs_instance()
                    else:
                        _log("PVR Favorites: no channels during PVR sync, removing favorites instance")
                        _remove_pvr_favs_instance_config()
                else:
                    _remove_pvr_favs_instance_config(force=True)

                # Configure optional Sports-only PVR instances. These reuse the
                # selected profile XMLTV file and stay separate from main PVR.
                try:
                    _sync_sports_pvr_during_pvr_sync()
                except Exception as e:
                    _log(f"Sports PVR: sync warning: {e}")

                # Default native PVR scope after a full sync:
                # Enable instances based on whether their M3U has channels.
                # Foreign IPTV Simple instances are preserved.
                try:
                    if _role_has_instance("main"):
                        _set_owned_pvr_instance_enabled("main", True, "PVR sync")
                    favs_enabled = (
                        addon.getSetting("pvr_favorites_enabled").lower() == "true"
                        and _m3u_file_has_channels(_pvr_favs_m3u_path())
                    )
                    if _role_has_instance("favs"):
                        _set_owned_pvr_instance_enabled("favs", favs_enabled, "PVR sync")
                    if _role_has_instance("sports"):
                        _set_owned_pvr_instance_enabled("sports", False, "PVR sync")
                    if _role_has_instance("sports_favs"):
                        _set_owned_pvr_instance_enabled("sports_favs", False, "PVR sync")
                except Exception as e:
                    _log(f"PVR instance enablement warning: {e}")

                progress.update(80, _t(30877))
                ok = True
            finally:
                _log("PVR sync: PVR reload skipped; IPTV Simple will reload on next refresh interval. Restart Kodi for immediate effect.")
                progress.update(90, _t(30876))
                xbmc.sleep(_tvos_sleep(200))
        except Exception as e:
            _log(f"PVR sync error: {e}")
        if ok:
            _maybe_show_pvr_first_run()
            progress.update(100, "PVR files synced" if epg_sync_ok else "PVR channels synced; EPG needs attention")
            xbmc.sleep(_tvos_sleep(300))
            if epg_sync_ok:
                xbmcgui.Dialog().notification(
                    "Xstream Pro",
                    "PVR sync done. Restart Kodi for EPG guide to update.",
                    xbmcgui.NOTIFICATION_INFO,
                    5000,
                )
                _restart_or_prompt()
            else:
                xbmcgui.Dialog().notification(
                    "Xstream Pro",
                    "PVR channels synced. EPG failed or did not match channels.",
                    xbmcgui.NOTIFICATION_WARNING,
                    5000,
                )
    finally:
        try:
            progress.close()
        except Exception:
            pass
        _release_pvr_sync_lock()
    return ok


def _sync_pvr_epg_only(offer_reload=True):
    """Rebuild the active PVR scope's XMLTV, then optionally ask Kodi to reload EPG."""
    if not _acquire_pvr_sync_lock():
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "PVR sync is already running.",
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )
        return False

    progress = xbmcgui.DialogProgress()
    ok = False
    try:
        scope = _current_pvr_instance_scope()
        progress.create("Xstream Pro", "Syncing PVR EPG")
        progress.update(5, "Preparing EPG sync")

        if scope in ("main", "mixed", "none"):
            pnum = _get_pvr_profile_num()
            _log("PVR EPG-only sync: Live TV scope for profile {0}".format(pnum))
            epg_path = _pvr_epg_path_for_profile(pnum)
            m3u_path = _pvr_m3u_path_for_profile(pnum)
            progress.update(20, "Fetching Live TV EPG and applying fallback")
            live_ok = _export_pvr_epg_for_profile(pnum, force_fetch=True)
            ok = live_ok
            if live_ok:
                progress.update(55, "Validating Live TV EPG links")
                _validate_pvr_epg_m3u_match(m3u_path, epg_path, "PVR EPG-only", notify=False)
            else:
                _log("PVR EPG-only sync: Live TV EPG export failed")

        if scope in ("sports", "mixed") and addon.getSetting("sports_pvr_enabled").lower() == "true":
            sports_pnum = _get_sports_pvr_profile_num()
            pct_start = 55 if scope == "mixed" else 20
            progress.update(pct_start, "Syncing Sports PVR EPG")
            sports_channels = _export_sports_pvr_m3u()
            if sports_channels:
                sports_ok = _export_sports_pvr_epg_for_profile(
                    sports_pnum,
                    sports_channels,
                    force_fetch=True,
                )
                progress.update(pct_start + 20, "Validating Sports PVR EPG links")
                _validate_pvr_epg_m3u_match(
                    _sports_pvr_m3u_path(),
                    _sports_pvr_epg_path_for_profile(sports_pnum),
                    "Sports PVR EPG-only",
                    notify=False,
                )
                ok = sports_ok if scope == "sports" else (ok and sports_ok)
            else:
                _log("PVR EPG-only sync: Sports PVR enabled but no Sports channels were exported")

        if ok:
            progress.update(100, "PVR EPG sync complete")
            _log("PVR EPG-only sync: finished")
        else:
            progress.update(100, "PVR EPG sync failed")
            _log("PVR EPG-only sync: failed")
    except Exception as e:
        ok = False
        _log(f"PVR EPG-only sync error: {e}")
        _log(f"Traceback: {traceback.format_exc()}")
    finally:
        try:
            progress.close()
        except Exception:
            pass
        _release_pvr_sync_lock()

    if ok and offer_reload:
        if xbmcgui.Dialog().yesno(
            "Xstream Pro",
            "PVR EPG sync complete.\n\nReload Kodi PVR EPG now?",
            yeslabel="Reload EPG",
            nolabel="Later",
        ):
            _trigger_pvr_epg_reload()
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "PVR EPG reload requested.",
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "EPG changes apply after PVR EPG reload or Kodi restart.",
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )
    elif not ok:
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "PVR EPG sync failed.",
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )

    return ok


def _remove_owned_pvr_instances():
    """Remove IPTV Simple Client instances created by XStream Player only."""
    pvr_profile = xbmcvfs.translatePath("special://profile/addon_data/pvr.iptvsimple")
    if not os.path.exists(pvr_profile):
        return
    removed = 0
    for fname in os.listdir(pvr_profile):
        if not re.match(r"instance-settings-\d+\.xml$", fname):
            continue
        path = os.path.join(pvr_profile, fname)
        role = _pvr_instance_role(path)
        if role in ("main", "favs", "sports", "sports_favs"):
            try:
                os.remove(path)
                removed += 1
                _log(f"PVR: Removed IPTV Simple instance {fname}")
            except Exception as e:
                _log(f"PVR: IPTV Simple instance remove warning ({fname}): {e}")
    if removed:
        for setting in PVR_INSTANCE_SETTINGS.values():
            addon.setSetting(setting, "")


def _unload_pvr(progress=None):
    """Clear PVR M3U/EPG files. Does not globally disable/enable pvr.iptvsimple or restart PVR Manager."""
    own_progress = progress is None
    if own_progress:
        progress = xbmcgui.DialogProgress()
        progress.create("Xstream Pro", _t(30868))

    progress.update(5, _t(30869))

    progress.update(15, _t(30870))
    try:
        _remove_owned_pvr_instances()
    except Exception as e:
        _log(f"PVR: IPTV Simple settings cleanup warning (unload): {e}")

    progress.update(30, _t(31436))
    try:
        m3u_path = _pvr_m3u_path()
        if os.path.exists(m3u_path):
            os.remove(m3u_path)
            _log(f"PVR: Removed M3U {m3u_path}")
    except Exception as e:
        _log(f"PVR: M3U remove warning (unload): {e}")

    progress.update(45, _t(31437))
    try:
        epg_path = _pvr_epg_path()
        if os.path.exists(epg_path):
            os.remove(epg_path)
            _log(f"PVR: Removed EPG {epg_path}")
    except Exception as e:
        _log(f"PVR: EPG remove warning (unload): {e}")
    _log("PVR: skipped Kodi Epg16.db reset during unload")

    progress.update(60, _t(31438))
    progress.update(80, _t(30875))
    _log("PVR: unload complete. IPTV Simple will notice file changes on next refresh. Restart Kodi for immediate effect.")

    progress.update(100, _t(31439))
    if own_progress:
        progress.close()


def _early_log(msg):
    """Log helper for functions called before init() injects _log."""
    try:
        _log(msg)
    except NameError:
        import xbmc as _xbmc
        _xbmc.log("[Xstream Pro] {0}".format(msg), _xbmc.LOGINFO)


def _find_databases():
    """Locate TV and EPG database files under the Kodi profile Database dir.

    Returns (tv_db_path, epg_db_path) — either may be None if not found.
    """
    import xbmcvfs as _xbmcvfs
    db_dir = _xbmcvfs.translatePath("special://profile/Database")
    tv_db = None
    epg_db = None
    try:
        for fname in os.listdir(db_dir):
            fpath = os.path.join(db_dir, fname)
            try:
                sz = os.path.getsize(fpath)
            except OSError:
                continue
            if fname.startswith("TV") and fname.endswith(".db") and sz > 0:
                if tv_db is None or fname > os.path.basename(tv_db):
                    tv_db = fpath
            elif fname == "Epg16.db" and sz > 0:
                epg_db = fpath
    except OSError:
        pass
    return tv_db, epg_db


def check_stale_channel_epg_ids():
    """Check for EPG ID mismatches between TV and EPG databases.

    Uses ATTACH DATABASE for a single efficient JOIN (~60ms for 5K channels)
    instead of N+1 individual queries.

    Returns the number of mismatches found, 0 if all correct, or -1 on error.
    """
    try:
        import sqlite3 as _sqlite3

        tv_db, epg_db = _find_databases()
        if not tv_db:
            _early_log("EPG ID check: no TV database found")
            return -1
        if not epg_db:
            _early_log("EPG ID check: no EPG database found")
            return -1

        conn = _sqlite3.connect(tv_db, timeout=5)
        try:
            conn.execute("ATTACH ? AS epgdb", (epg_db,))
            cur = conn.execute(
                "SELECT COUNT(*) FROM channels c "
                "JOIN epgdb.epg e ON c.idEpg = e.idEpg "
                "WHERE c.iClientId IN ("
                "  SELECT idClient FROM clients WHERE sAddonID = 'pvr.iptvsimple'"
                ") AND c.idEpg > 0 AND c.sChannelName != e.sName"
            )
            count = cur.fetchone()[0]
            conn.execute("DETACH epgdb")
        finally:
            conn.close()

        if count > 0:
            _early_log("EPG ID check: {0} mismatch(es) detected".format(count))
        else:
            _early_log("EPG ID check: no mismatches")
        return count
    except Exception as exc:
        _early_log("EPG ID check error: {0}".format(exc))
        return -1


def reset_stale_channel_epg_ids():
    """Reset idEpg values in Kodi's TV database after Epg16.db is rebuilt.

    When Epg16.db is deleted and rebuilt, the new EPG entries get different
    IDs. The channels table in TV*.db still has the OLD idEpg values, which
    may now point to the wrong EPG entry (e.g., HRT 1 HD pointing to BHT 1 HD).

    Setting idEpg = -1 forces Kodi to recreate EPG entries with correct
    mappings on the next startup.

    Uses ATTACH DATABASE for a single efficient JOIN instead of N+1 queries.
    Returns the number of channels reset, or -1 on error.
    """
    try:
        import sqlite3 as _sqlite3

        tv_db, epg_db = _find_databases()
        if not tv_db:
            _early_log("EPG ID reset: no TV database found")
            return -1

        _early_log("EPG ID reset: using TV database {0}".format(os.path.basename(tv_db)))

        tv_conn = _sqlite3.connect(tv_db, timeout=5)

        client_ids = []
        try:
            tv_cur = tv_conn.cursor()
            tv_cur.execute("SELECT idClient FROM clients WHERE sAddonID = 'pvr.iptvsimple'")
            client_ids = [row[0] for row in tv_cur.fetchall()]
        except Exception:
            pass

        if not client_ids:
            tv_conn.close()
            _early_log("EPG ID reset: no pvr.iptvsimple clients found")
            return -1

        placeholders = ",".join(["?"] * len(client_ids))

        if epg_db and os.path.exists(epg_db):
            tv_conn.execute("ATTACH ? AS epgdb", (epg_db,))
            mismatch_rows = tv_conn.execute(
                "SELECT c.idChannel, c.sChannelName, c.idEpg, e.sName "
                "FROM channels c JOIN epgdb.epg e ON c.idEpg = e.idEpg "
                "WHERE c.iClientId IN ({0}) AND c.idEpg > 0 AND c.sChannelName != e.sName".format(
                    placeholders
                ),
                client_ids,
            ).fetchall()
            tv_conn.execute("DETACH epgdb")

            if mismatch_rows:
                reset_ids = [row[0] for row in mismatch_rows]
                for ch_id, ch_name, epg_id, epg_name in mismatch_rows[:10]:
                    _early_log(
                        "EPG ID reset: mismatch - channel '{0}' (idCh={1}) maps to EPG '{2}' (idEpg={3})".format(
                            ch_name, ch_id, epg_name, epg_id
                        )
                    )
                if len(mismatch_rows) > 10:
                    _early_log("EPG ID reset: ... and {0} more mismatch(es)".format(len(mismatch_rows) - 10))

                chunk_size = 100
                for i in range(0, len(reset_ids), chunk_size):
                    chunk = reset_ids[i : i + chunk_size]
                    ph = ",".join(["?"] * len(chunk))
                    tv_conn.execute(
                        "UPDATE channels SET idEpg = -1 WHERE idChannel IN ({0})".format(ph),
                        chunk,
                    )
                tv_conn.commit()
                _early_log("EPG ID reset: reset {0} mismatched channel(s)".format(len(reset_ids)))
            else:
                _early_log("EPG ID reset: no mismatches found")
            mismatched = len(reset_ids) if mismatch_rows else 0
        else:
            _early_log("EPG ID reset: no EPG database found; resetting all idEpg values")
            tv_conn.execute(
                "UPDATE channels SET idEpg = -1 WHERE iClientId IN ({0})".format(
                    placeholders
                ),
                client_ids,
            )
            tv_conn.commit()
            mismatched = tv_conn.rowcount
            _early_log("EPG ID reset: reset {0} channel(s) (no EPG DB to compare)".format(mismatched))

        tv_conn.close()
        return mismatched
    except Exception as exc:
        _early_log("EPG ID reset error: {0}".format(exc))
        _early_log("Traceback: {0}".format(traceback.format_exc()))
        return -1


def reset_pvr_epg_db_action():
    """Hard reset Kodi EPG DB plus XStream Live/Sports generated PVR files."""
    if not xbmcgui.Dialog().yesno(
        _t(31434),
        "Hard reset PVR/EPG now?\n\n"
        "This will stop playback, temporarily disable IPTV Simple, delete Kodi EPG DB, "
        "delete XStream generated Live/Sports PVR files and EPG caches, regenerate Live + Sports PVR files, "
        "then re-enable IPTV Simple.\n\n"
        "Restart Kodi after this finishes.",
        yeslabel="Hard Reset",
        nolabel="Cancel",
    ):
        _log("PVR: hard EPG/PVR reset cancelled by user")
        return

    progress = xbmcgui.DialogProgress()
    progress.create(_t(31434), "Hard resetting PVR/EPG")

    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    os.makedirs(profile_path, exist_ok=True)
    retry_flag = os.path.join(profile_path, "pvr_sync_retry_needed.flag")

    def _set_iptv_simple_enabled(enabled):
        try:
            xbmc.executeJSONRPC(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "Addons.SetAddonEnabled",
                        "params": {"addonid": "pvr.iptvsimple", "enabled": bool(enabled)},
                    }
                )
            )
            _log("PVR hard reset: pvr.iptvsimple enabled={0}".format(bool(enabled)))
            return True
        except Exception as exc:
            _log("PVR hard reset: pvr.iptvsimple enable/disable warning: {0}".format(exc))
            return False

    def _delete_path(path, label):
        try:
            if path and os.path.exists(path):
                os.remove(path)
                _log("PVR hard reset: deleted {0}: {1}".format(label, path))
                return True
        except Exception as exc:
            _log("PVR hard reset: delete warning for {0} {1}: {2}".format(label, path, exc))
        return False

    def _is_generated_pvr_file(fname):
        generated_prefixes = (
            "pvr_live_{0}_p".format(PVR_FILE_SLUG),
            "pvr_epg_{0}_p".format(PVR_FILE_SLUG),
            "pvr_favorites_{0}_p".format(PVR_FILE_SLUG),
            "pvr_sports_{0}_p".format(PVR_FILE_SLUG),
            "pvr_sports_epg_{0}_p".format(PVR_FILE_SLUG),
            "pvr_sports_favorites_{0}_p".format(PVR_FILE_SLUG),
        )
        generated_suffixes = (
            ".m3u8",
            ".m3u8.tmp",
            ".xml",
            ".xml.tmp",
            ".xml.lastgood",
        )
        return fname.startswith(generated_prefixes) and fname.endswith(generated_suffixes)

    try:
        progress.update(5, "Stopping playback")
        xbmc.executebuiltin("PlayerControl(Stop)")
        xbmc.sleep(_tvos_sleep(500))

        progress.update(10, "Disabling IPTV Simple")
        _set_iptv_simple_enabled(False)
        xbmc.sleep(_tvos_sleep(3000))
        if sys.platform.startswith("win") or xbmc.getCondVisibility("System.Platform.Android"):
            xbmc.sleep(_tvos_sleep(3000))

        progress.update(20, "Clearing in-memory EPG cache")
        try:
            _pvr_export.clear_epg_instance_cache()
            _log("PVR hard reset: cleared in-memory EPG instance cache")
        except Exception as exc:
            _log("PVR hard reset: in-memory EPG cache clear warning: {0}".format(exc))

        progress.update(30, "Deleting Kodi EPG database")
        db_base = xbmcvfs.translatePath("special://profile/Database/Epg16.db")
        db_deleted = True
        for suffix in ("", "-wal", "-shm", "-journal"):
            target = db_base + suffix
            if os.path.exists(target):
                if not _delete_path(target, "Kodi EPG DB"):
                    db_deleted = False

        if not db_deleted or os.path.exists(db_base):
            _log("PVR hard reset: Epg16.db could not be fully deleted, setting retry flag")
            try:
                with open(retry_flag, "w", encoding="utf-8") as f:
                    f.write("1")
            except Exception as exc:
                _log("PVR hard reset: retry flag write warning: {0}".format(exc))
            xbmcgui.Dialog().ok(
                _t(31434),
                "Kodi still has the EPG database locked. Restart Kodi and run Hard Reset again.",
            )
            return

        epg_reset_flag = os.path.join(profile_path, ".epg_db_rebuilt")
        try:
            with open(epg_reset_flag, "w", encoding="utf-8") as f:
                f.write("1")
            _log("PVR hard reset: wrote EPG DB rebuilt flag for next startup")
        except Exception as exc:
            _log("PVR hard reset: EPG DB rebuilt flag write warning: {0}".format(exc))

        progress.update(45, "Deleting XStream EPG caches")
        deleted_caches = 0
        for fname in list(os.listdir(profile_path)):
            is_cache = (
                fname == "epg_cache.json"
                or fname.startswith("epg_cache_profile_")
                or fname.startswith("data_cache_epg")
                or (fname.startswith("pvr_epg_fallback_") and fname.endswith(".stamp"))
            )
            if is_cache:
                if _delete_path(os.path.join(profile_path, fname), "addon EPG cache"):
                    deleted_caches += 1
        _log("PVR hard reset: deleted {0} addon EPG cache/stamp file(s)".format(deleted_caches))

        progress.update(55, "Deleting generated Live/Sports PVR files")
        deleted_generated = 0
        for fname in list(os.listdir(profile_path)):
            if _is_generated_pvr_file(fname):
                if _delete_path(os.path.join(profile_path, fname), "generated PVR file"):
                    deleted_generated += 1
        _log("PVR hard reset: deleted {0} generated PVR file(s)".format(deleted_generated))

        progress.update(65, "Regenerating Live TV PVR")
        live_m3u_ok = False
        live_epg_ok = False
        try:
            live_m3u_ok = bool(_export_pvr_m3u())
            _log("PVR hard reset: regenerated Live M3U result={0}".format(live_m3u_ok))
        except Exception as exc:
            _log("PVR hard reset: Live M3U regeneration failed: {0}".format(exc))

        try:
            live_epg_ok = bool(_export_pvr_epg(force_fetch=True))
            _log("PVR hard reset: regenerated Live XMLTV result={0}".format(live_epg_ok))
        except Exception as exc:
            _log("PVR hard reset: Live XMLTV regeneration failed: {0}".format(exc))

        try:
            if live_m3u_ok:
                _configure_pvr_iptvsimple()
        except Exception as exc:
            _log("PVR hard reset: Live IPTV Simple configure warning: {0}".format(exc))

        progress.update(78, "Regenerating Sports PVR")
        sports_ok = True
        sports_enabled = addon.getSetting("sports_pvr_enabled").lower() == "true"
        if sports_enabled:
            sports_ok = False
            try:
                sports_channels = _export_sports_pvr_m3u()
                _log(
                    "PVR hard reset: regenerated Sports M3U channels={0}".format(
                        len(sports_channels) if sports_channels else 0
                    )
                )
                if sports_channels:
                    sports_pnum = _get_sports_pvr_profile_num()
                    sports_epg_ok = bool(
                        _export_sports_pvr_epg_for_profile(
                            sports_pnum,
                            sports_channels,
                            force_fetch=True,
                        )
                    )
                    _log("PVR hard reset: regenerated Sports XMLTV result={0}".format(sports_epg_ok))
                    sports_ok = bool(sports_epg_ok)
                else:
                    _log("PVR hard reset: Sports PVR enabled but no Sports channels exported")
            except Exception as exc:
                _log("PVR hard reset: Sports regeneration failed: {0}".format(exc))

            try:
                _export_sports_pvr_favs_m3u()
            except Exception as exc:
                _log("PVR hard reset: Sports favorites export warning: {0}".format(exc))

            try:
                if _m3u_file_has_channels(_sports_pvr_m3u_path()):
                    _configure_sports_pvr_instance(enabled=False)
                else:
                    _remove_pvr_instance_config("sports", "Sports PVR", force=True)
            except Exception as exc:
                _log("PVR hard reset: Sports instance configure warning: {0}".format(exc))

            try:
                if _m3u_file_has_channels(_sports_pvr_favs_m3u_path()):
                    _configure_sports_pvr_favs_instance(enabled=False)
                else:
                    _remove_pvr_instance_config("sports_favs", "Sports PVR Favorites", force=True)
            except Exception as exc:
                _log("PVR hard reset: Sports favorites instance configure warning: {0}".format(exc))
        else:
            _log("PVR hard reset: Sports PVR disabled, skipping Sports regeneration")

        progress.update(90, "Validating generated EPG files")
        try:
            if live_m3u_ok and live_epg_ok:
                _validate_pvr_epg_m3u_match(_pvr_m3u_path(), _pvr_epg_path(), "PVR hard reset Live", notify=False)
        except Exception as exc:
            _log("PVR hard reset: Live validation warning: {0}".format(exc))

        try:
            if sports_enabled and sports_ok:
                _validate_pvr_epg_m3u_match(
                    _sports_pvr_m3u_path(),
                    _sports_pvr_epg_path_for_profile(_get_sports_pvr_profile_num()),
                    "PVR hard reset Sports",
                    notify=False,
                )
        except Exception as exc:
            _log("PVR hard reset: Sports validation warning: {0}".format(exc))

        progress.update(95, "Re-enabling IPTV Simple")
        _set_iptv_simple_enabled(True)

        success = bool(live_m3u_ok and live_epg_ok and sports_ok)
        if success:
            try:
                if os.path.exists(retry_flag):
                    os.remove(retry_flag)
            except Exception:
                pass
        else:
            try:
                with open(retry_flag, "w", encoding="utf-8") as f:
                    f.write("1")
                _log("PVR hard reset: set retry flag because regeneration was incomplete")
            except Exception as exc:
                _log("PVR hard reset: retry flag write warning: {0}".format(exc))

        progress.update(100, "Hard reset complete")
        xbmc.sleep(_tvos_sleep(300))
        progress.close()
        progress = None

        if success:
            xbmcgui.Dialog().ok(
                _t(31434),
                "Hard PVR/EPG reset complete.\n\n"
                "Live and Sports files were regenerated. Restart Kodi now so IPTV Simple reloads cleanly.",
            )
        else:
            xbmcgui.Dialog().ok(
                _t(31434),
                "Hard PVR/EPG reset finished, but one or more files failed to regenerate.\n\n"
                "Restart Kodi, then run Force Reload PVR.",
            )

    except Exception as exc:
        _log("PVR hard reset error: {0}".format(exc))
        _log("Traceback: {0}".format(traceback.format_exc()))
        try:
            with open(retry_flag, "w", encoding="utf-8") as f:
                f.write("1")
        except Exception:
            pass
        xbmcgui.Dialog().notification("Xstream Pro", "PVR hard reset error: {0}".format(exc))
    finally:
        try:
            if progress:
                progress.close()
        except Exception:
            pass


def _maybe_show_pvr_first_run():
    flag = os.path.join(
        xbmcvfs.translatePath(addon.getAddonInfo("profile")), "pvr_first_run_shown"
    )
    if os.path.exists(flag):
        return
    try:
        with open(flag, "w", encoding="utf-8") as f:
            f.write("1")
        xbmcgui.Dialog().ok("Xstream Pro", _t(30057) + "\n" + _t(30058))
    except Exception as e:
        _log(f"PVR first run flag write error: {e}")


def sync_sports_pvr(confirm=True):
    if confirm and not xbmcgui.Dialog().yesno(_t(31532), _t(31672)):
        return False

    if not _pvr_open_guard("Sports PVR reload"):
        return False

    try:
        addon.setSetting("sports_pvr_enabled", "true")
        ok = _sync_sports_pvr_safe()
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            _t(31676) if ok else _t(31677),
        )
        return ok
    finally:
        _pvr_open_release()


def switch_sports_pvr_profile():
    current = addon.getSetting("sports_pvr_profile") or "Active PVR Profile"
    options = [("Active PVR Profile", "Active PVR Profile")]
    for i in range(1, 11):
        if addon.getSetting(f"profile_{i}_enabled") != "true":
            continue
        has_xtream = bool(addon.getSetting(f"profile_{i}_xtream_url"))
        has_m3u = bool(addon.getSetting(f"profile_{i}_m3u"))
        if not has_xtream and not has_m3u:
            continue
        name = addon.getSetting(f"profile_{i}_name") or _t(30390, i)
        label = _t(31400, i, name) if name != _t(30390, i) else _t(30390, i)
        options.append((f"Profile {i}", label))
    labels = [label + (" [COLOR green]*[/COLOR]" if value == current else "") for value, label in options]
    idx = xbmcgui.Dialog().select(_t(31674), labels)
    if idx < 0:
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    selected_value = options[idx][0]
    if selected_value == current:
        xbmcgui.Dialog().notification("Xstream Pro", _t(30121))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    addon.setSetting("sports_pvr_profile", selected_value)
    addon.setSetting("sports_pvr_enabled", "true")
    if xbmcgui.Dialog().yesno(_t(31532), _t(31672)):
        sync_sports_pvr(confirm=False)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False)


def _pvr_progress(progress, percent, message):
    return _pvr_instances._pvr_progress(progress, percent, message)


def _sync_sports_pvr_during_pvr_sync(progress=None):
    if addon.getSetting("sports_pvr_enabled").lower() != "true":
        _remove_pvr_instance_config("sports", "Sports PVR", force=True)
        _remove_pvr_instance_config("sports_favs", "Sports PVR Favorites", force=True)
        return True
    pnum = _get_sports_pvr_profile_num()
    _pvr_progress(progress, 35, "Exporting Sports playlist")
    sports_channels = _export_sports_pvr_m3u()
    if not sports_channels:
        _remove_pvr_instance_config("sports", "Sports PVR", force=True)
        return False
    epg_path = _sports_pvr_epg_path()
    sports_m3u_path = _sports_pvr_m3u_path()
    _pvr_progress(progress, 50, "Checking Sports EPG")
    epg_fallback_rebuild = _pvr_epg_fallback_needs_rebuild(pnum, "sports")
    m3u_newer = (
        os.path.exists(epg_path)
        and os.path.exists(sports_m3u_path)
        and os.path.getmtime(sports_m3u_path) > os.path.getmtime(epg_path)
    )
    epg_stale = (
        not os.path.exists(epg_path)
        or os.path.getsize(epg_path) == 0
        or not epg_file_has_data(epg_path)
        or epg_fallback_rebuild
        or m3u_newer
        or (
            os.path.exists(epg_path)
            and time.time() - os.path.getmtime(epg_path) > _pvr_epg_refresh_seconds()
        )
    )
    if epg_fallback_rebuild:
        _log("Sports PVR: EPG fallback configuration changed, will re-export")
    if m3u_newer:
        _log("Sports PVR: M3U is newer than EPG file, will re-export")
    if epg_stale:
        _log("Sports PVR: Existing Sports EPG file is empty or stale, will re-export")
        sports_epg_ok = _export_sports_pvr_epg_for_profile(
            pnum, sports_channels, force_fetch=True
        )
    else:
        _log("Sports PVR: Reusing existing Sports EPG file (fresh)")
        sports_epg_ok = epg_file_has_data(epg_path)
    _pvr_progress(progress, 70, "Validating Sports EPG links")
    sports_epg_match_ok = _validate_pvr_epg_m3u_match(_sports_pvr_m3u_path(), epg_path, "Sports PVR", notify=False)
    if not epg_stale and not sports_epg_match_ok:
        _log("Sports PVR: fresh EPG file failed M3U validation, re-exporting with cache-only")
        _pvr_progress(progress, 60, "Re-exporting Sports EPG from cache")
        sports_epg_ok = _export_sports_pvr_epg_for_profile(
            pnum, sports_channels, force_fetch=False
        )
        sports_epg_match_ok = _validate_pvr_epg_m3u_match(_sports_pvr_m3u_path(), epg_path, "Sports PVR", notify=False)
    if not sports_epg_ok:
        _log("Sports PVR WARNING: channels exported, but Sports EPG export failed or produced no programmes")
    elif not sports_epg_match_ok:
        _log("Sports PVR WARNING: channels exported, but Sports EPG programme rows do not match M3U tvg-ids")
    _pvr_progress(progress, 78, "Configuring Sports PVR instance")
    _configure_sports_pvr_instance(enabled=False)
    _pvr_progress(progress, 84, "Cleaning duplicate Sports PVR instances")
    _remove_duplicate_pvr_instances("sports", _get_pvr_instance_id("sports"), "Sports PVR")
    _pvr_progress(progress, 88, "Exporting Sports favorites")
    _export_sports_pvr_favs_m3u()
    if _m3u_file_has_channels(_sports_pvr_favs_m3u_path()):
        _configure_sports_pvr_favs_instance(enabled=False)
        _remove_duplicate_pvr_instances(
            "sports_favs",
            _get_pvr_instance_id("sports_favs"),
            "Sports PVR Favorites",
        )
    else:
        _remove_pvr_instance_config("sports_favs", "Sports PVR Favorites", force=True)
    return True


def _sync_sports_pvr_safe():
    """Sync only Sports PVR files/owned instances without restarting shared IPTV Simple."""
    if not _is_pvr_iptvsimple_installed_or_disabled():
        prompt_install_pvr()
        return False

    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", "Preparing Sports PVR")
    ok = False

    try:
        _pvr_export.clear_epg_instance_cache()
        _pvr_progress(progress, 20, "Preparing Sports PVR files")
        ok = _sync_sports_pvr_during_pvr_sync(progress)

        if ok and not _confirm_large_pvr_list(_sports_pvr_m3u_path(), "Sports PVR"):
            _log("Sports PVR: user cancelled large Sports PVR load")
            ok = False
            return False

        if ok:
            _pvr_progress(progress, 90, "Selecting Sports PVR groups")
            ok = _ensure_pvr_instance_paths("sports", "Sports PVR safe", repair=True)
            _pvr_progress(progress, 100, "Sports PVR ready" if ok else "Sports PVR incomplete")
            xbmc.sleep(_tvos_sleep(300))
    finally:
        try:
            progress.close()
        except Exception:
            pass

    return ok

