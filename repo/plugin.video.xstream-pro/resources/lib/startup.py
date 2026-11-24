"""Startup checks and retry helpers for Xstream Pro."""

_OWNED = {'_check_account_expiry', '_run_startup_checks', '_profiles_refresh_stamp_path', '_get_profiles_last_refresh', '_set_profiles_last_refresh', '_profiles_auto_refresh_due', '_check_profiles_auto_refresh', '_check_credentials_refresh_prompt', '_check_pvr_startup_retry', '_schedule_pvr_startup_retry_sync', '_is_first_refresh', '_mark_first_refresh_done'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _check_account_expiry():
    """Warn if Xtream account expires within 7 days."""
    creds = _get_credentials()
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    if not url or not user or not pwd:
        return
    # Only check once per day using a per-profile flag file
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    flag = os.path.join(profile, f"expiry_checked_p{pm.active}")
    if os.path.exists(flag):
        try:
            age = time.time() - os.path.getmtime(flag)
            if age < 86400:  # check once per day
                return
        except Exception as e:
            _log(f"expiry flag age check warning: {e}")
    try:
        info = IPTV.validate_xtream(url, user, pwd)
        if not info:
            # HTTP/auth failure — don't write the flag, otherwise we'd rate-limit
            # ourselves for 24h after a transient failure.
            return
        if info.get("exp_date"):
            exp_dt = datetime.datetime.fromtimestamp(int(info["exp_date"]))
            days_left = (exp_dt - datetime.datetime.now()).days
            if days_left < 7:
                xbmcgui.Dialog().notification(
                    "Xstream Pro",
                    _t(30300, days_left),
                    xbmcgui.NOTIFICATION_WARNING,
                    5000,
                )
        try:
            with open(flag, "w", encoding="utf-8") as f:
                f.write("1")
        except Exception as e:
            _log(f"expiry flag write failed: {e}")
    except Exception as e:
        _log(f"account expiry check failed: {e}")


def _run_startup_checks():
    """Run startup checks in background thread. Called from main_menu()."""
    _log("Running startup checks")
    # Foreign Xstream/XStream addon instances are intentionally preserved.

    backup_display = _read_backup_folder()
    if addon.getSetting("backup_folder_display") != backup_display:
        addon.setSetting("backup_folder_display", backup_display)
    try:
        current = addon.getSetting("pvr_favorites_enabled").lower() == "true"
        saved = addon.getSetting("pvr_fav_saved_state")
        if saved != "" and current != (saved.lower() == "true"):
            profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
            fresh_bootstrap = not os.path.exists(os.path.join(profile_path, ".bootstrap_signature"))
            if not fresh_bootstrap:
                xbmcgui.Dialog().notification(
                    "Xstream Pro", _t(30729), xbmcgui.NOTIFICATION_INFO, 5000
                )
        new_saved = "true" if current else "false"
        if saved != new_saved:
            addon.setSetting("pvr_fav_saved_state", new_saved)
    except Exception as e:
        _log(f"PVR favorites state check error: {e}")
    _check_credentials_refresh_prompt()  # Prompt to refresh after first credentials entry

    # Skip auto-refresh if restore just completed — profiles will be loaded anyway
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    defer_flag = os.path.join(profile_path, "pvr_sync_after_profile_load.flag")
    if not os.path.exists(defer_flag):
        _check_profiles_auto_refresh()
    else:
        _log("Skipping auto-refresh — restore pending profile load")

    # PVR startup retry: if user declined PVR sync after restore, offer once more
    # Skip modal dialogs on tvOS — they crash Kodi during addon startup
    if not _is_tvos():
        _check_pvr_startup_retry()

    # Post-restore profile load: if restore just completed, prompt to load profiles
    if not _is_tvos():
        _prompt_load_profiles_after_restore()

    # Health check: re-enable pvr.iptvsimple if it was left disabled by a crash
    # or power loss during _sync_pvr_force() — but only when no pending PVR sync
    # exists. If a deferred or retry flag is set, pvr.iptvsimple must stay
    # disabled until _sync_pvr_force() regenerates M3U/XMLTV and re-enables it,
    # otherwise PVR Manager loads an empty channel list from missing files.
    try:
        resp = json.loads(
            xbmc.executeJSONRPC(
                '{"jsonrpc":"2.0","method":"Addons.GetAddonDetails","params":{"addonid":"pvr.iptvsimple","properties":["enabled"]},"id":1}'
            )
        )
        enabled = resp.get("result", {}).get("addon", {}).get("enabled", False)
        if not enabled:
            _pending_sync = (
                os.path.exists(os.path.join(profile_path, "pvr_sync_after_profile_load.flag"))
                or os.path.exists(os.path.join(profile_path, "pvr_sync_retry_needed.flag"))
            )
            if _pending_sync:
                _log("PVR is disabled but sync is pending — skipping auto-enable until sync regenerates files")
            else:
                xbmc.executeJSONRPC(
                    '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"pvr.iptvsimple","enabled":true},"id":1}'
                )
                _log("PVR was disabled, enabled it on launch")
        else:
            _log("PVR already enabled on launch")
    except Exception as e:
        _log(f"PVR load on launch error: {e}")

    # Deferred buffer fix restart prompt (tvOS-safe)
    if addon.getSetting("buffer_fix_needs_restart") == "true":
        addon.setSetting("buffer_fix_needs_restart", "")
        if not _is_tvos():
            try:
                if xbmcgui.Dialog().yesno(_t(30726), _t(30792)):
                    _restart_or_prompt()
            except Exception as e:
                _log(f"Buffer restart prompt error: {e}")

    # Run network checks in background with pinned profile snapshot.
    _profile_snapshot = pm.active

    def _bg_startup_checks():
        # Pin profile to snapshot to avoid race with main-thread profile switch.
        try:
            if pm.active != _profile_snapshot:
                _log(
                    f"startup checks: profile changed ({_profile_snapshot}->{pm.active}), pinning to snapshot"
                )
                pm.active = _profile_snapshot
        except Exception as e:
            _log(f"startup checks profile pin warning: {e}")
        try:
            try:
                _check_account_expiry()
            except Exception as e:
                _log(f"Account expiry check error: {e}")
            try:
                from updater import silent_check_on_startup

                silent_check_on_startup()
            except Exception as e:
                _log(f"Update check error: {e}")
        finally:
            try:
                if pm.active != _profile_snapshot:
                    pm.active = _profile_snapshot
            except Exception as e:
                _log(f"startup checks profile restore warning: {e}")

    # Skip background network thread on tvOS — daemon threads + network can crash
    if not _is_tvos():
        t = threading.Thread(target=_bg_startup_checks, name="XStreamStartupChecks")
        t.daemon = True
        t.start()
    else:
        _log("tvOS detected: skipping background startup network checks")
    try:
        current_version = addon.getAddonInfo("version")
        if addon.getSetting("current_version_display") != current_version:
            addon.setSetting("current_version_display", current_version)
    except Exception as e:
        _log(f"Version display update error: {e}")

    # Show changelog on first launch after update
    # Skip on tvOS — textviewer dialog during startup can crash Kodi
    if not _is_tvos():
        try:
            if addon.getSetting("show_changelog_on_update") != "false":
                current_version = addon.getAddonInfo("version")
                last_seen = addon.getSetting("last_seen_version") or "0.0.0"
                if current_version != last_seen:
                    changelog_path = os.path.join(
                        xbmcvfs.translatePath(addon.getAddonInfo("path")), "CHANGELOG.md"
                    )
                    shown = False
                    try:
                        with open(changelog_path, "r", encoding="utf-8") as f:
                            changelog = f.read().strip()
                        if changelog:
                            xbmcgui.Dialog().textviewer(
                                _t(30340, current_version), changelog
                            )
                            shown = True
                    except Exception as e:
                        _log(f"changelog read error: {e}")
                    if shown:
                        addon.setSetting("last_seen_version", current_version)
        except Exception as e:
            _log(f"Changelog display error: {e}")
    else:
        _log("tvOS detected: skipping changelog display")


def _profiles_refresh_stamp_path():
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    return os.path.join(profile, "profiles_auto_refresh.txt")


def _get_profiles_last_refresh():
    try:
        with open(_profiles_refresh_stamp_path(), "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:
        return 0


def _set_profiles_last_refresh():
    path = _profiles_refresh_stamp_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(time.time()))
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp, path)


def _profiles_auto_refresh_due():
    if addon.getSetting("auto_refresh_enabled").lower() != "true":
        return False
    interval = addon.getSetting("auto_refresh_interval") or "24"
    if interval.lower() == "never":
        return False
    try:
        hours = float(interval)
    except ValueError:
        hours = 24
    return (time.time() - _get_profiles_last_refresh()) > (hours * 3600)


def _check_profiles_auto_refresh():
    if _is_tvos():
        return
    if not _profiles_auto_refresh_due():
        return
    profiles = _enabled_profiles_with_credentials()
    if not profiles:
        _set_profiles_last_refresh()
        return
    if xbmcgui.Dialog().yesno(
        "Update profiles content?",
        "Your enabled provider profiles are due for a playlist refresh.\n\nUpdate all enabled profiles now?"
    ):
        _refresh_all_profiles_with_progress(profiles)
    _set_profiles_last_refresh()


def _check_credentials_refresh_prompt():
    return False


def _check_pvr_startup_retry():
    """Offer PVR sync at startup if user previously declined it.

    The deferred restore flag (pvr_sync_after_profile_load.flag) is NOT handled
    here — it is processed by _prompt_sync_pvr_if_needed() after the PVR-linked
    profile is actually loaded. This prevents a premature "Sync PVR?" dialog
    during the addon reload that follows restore.
    """
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    retry_flag = os.path.join(profile_path, "pvr_sync_retry_needed.flag")
    defer_flag = os.path.join(profile_path, "pvr_sync_after_profile_load.flag")

    # Deferred restore sync: do NOT show dialog here. The prompt will appear
    # after the PVR-linked profile is loaded via _prompt_sync_pvr_if_needed().
    if os.path.exists(defer_flag):
        _log("PVR sync deferred - will prompt after PVR-linked profile is loaded")
        return

    if not os.path.exists(retry_flag):
        return

    # Check if PVR addon is disabled — if so, the M3U/XMLTV files we regenerated
    # during EPG reset won't be loaded until pvr.iptvsimple is re-enabled via
    # _sync_pvr_force(). Do NOT clear the retry flag in this case.
    try:
        resp = json.loads(
            xbmc.executeJSONRPC(
                '{"jsonrpc":"2.0","method":"Addons.GetAddonDetails","params":{"addonid":"pvr.iptvsimple","properties":["enabled"]},"id":1}'
            )
        )
        pvr_enabled = resp.get("result", {}).get("addon", {}).get("enabled", False)
    except Exception:
        pvr_enabled = False

    if pvr_enabled:
        # pvr.iptvsimple is enabled — check if PVR data already exists
        try:
            pvr_path = _pvr_m3u_path()
            if os.path.exists(pvr_path) and os.path.getsize(pvr_path) > 0:
                os.remove(retry_flag)
                _log("PVR retry flag cleared — PVR already has data and addon is enabled")
                return
        except Exception as e:
            _log(f"PVR retry check warning: {e}")
    else:
        _log("PVR: pvr.iptvsimple is disabled — retry sync needed to re-enable it")

    if not _is_pvr_iptvsimple_installed_or_disabled():
        return

    _schedule_pvr_startup_retry_sync(retry_flag)


def _schedule_pvr_startup_retry_sync(retry_flag):
    """Run retry PVR sync in the background so main menu listing can return."""
    global _PVR_STARTUP_RETRY_THREAD
    try:
        with _PVR_STARTUP_RETRY_THREAD_LOCK:
            if (
                _PVR_STARTUP_RETRY_THREAD is not None
                and _PVR_STARTUP_RETRY_THREAD.is_alive()
            ):
                _log("PVR startup retry sync already running")
                return False

            def _worker():
                try:
                    creds = _get_pvr_credentials()
                    if not (creds.get("xtream_url") or creds.get("m3u_url")):
                        return
                    _log("PVR startup retry sync scheduled in background")
                    if _sync_pvr_force():
                        try:
                            if os.path.exists(retry_flag):
                                os.remove(retry_flag)
                        except OSError:
                            pass
                        _log("PVR sync completed via startup retry")
                    else:
                        _log("PVR startup retry sync did not complete")
                except Exception as e:
                    _log(f"PVR startup retry sync warning: {e}")
                    _log(f"Traceback: {traceback.format_exc()}")

            _PVR_STARTUP_RETRY_THREAD = threading.Thread(
                target=_worker,
                name="XstreamProPvrStartupRetry",
                daemon=True,
            )
            _PVR_STARTUP_RETRY_THREAD.start()
            return True
    except Exception as e:
        _log(f"PVR startup retry schedule warning: {e}")
        return False


def _is_first_refresh():
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    return not os.path.exists(os.path.join(profile, "first_refresh_done"))


def _mark_first_refresh_done():
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    with open(os.path.join(profile, "first_refresh_done"), "w", encoding="utf-8") as f:
        f.write("1")


