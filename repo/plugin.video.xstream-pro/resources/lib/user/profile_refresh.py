"""Profile refresh route helpers for Xstream Pro."""

_OWNED = {'_build_fetch_steps', '_run_profile_refresh_steps', '_prefetch_all_data', 'sports_refresh_profile_menu', 'refresh_profile_menu', '_refresh_all_profiles_with_progress', '_refresh_single_profile_silent', '_refresh_profile_data', '_refresh_profiles_batch', 'refresh_data'}


def _provider_availability_marking_enabled():
    return (
        addon.getSetting("tmdb_provider_only_available").lower() == "true"
        or addon.getSetting("tmdb_mark_unavailable").lower() == "true"
    )


def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _build_fetch_steps(xt_url, xt_user, xt_pwd, m3u_url, force=False):
    steps = []
    load_live = False
    if m3u_url and not _m3u_has_credentials(m3u_url):
        steps.append((_t(30350), lambda: _get_cached_m3u_channels(m3u_url, force=force)))
    if xt_url and xt_user and xt_pwd:
        load_live = pm.get_profile_setting("load_live") != "false"
        load_movies = pm.get_profile_setting("load_movies") != "false"
        load_series = pm.get_profile_setting("load_series") != "false"
        if load_live:
            steps.extend([
                (_t(30351), lambda: _get_cached_xtream_categories(xt_url, xt_user, xt_pwd, "live", force=force)),
                (_t(30352), lambda: _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "live", force=force)),
            ])
        if load_movies:
            steps.extend([
                (_t(30353), lambda: _get_cached_xtream_categories(xt_url, xt_user, xt_pwd, "movie", force=force)),
                (_t(30354), lambda: _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "movie", force=force)),
            ])
        if load_series:
            steps.extend([
                (_t(30355), lambda: _get_cached_xtream_categories(xt_url, xt_user, xt_pwd, "series", force=force)),
                (_t(30356), lambda: _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "series", force=force)),
            ])
    return steps, load_live


def _run_profile_refresh_steps(
    profile_num,
    progress=None,
    start_percent=20,
    end_percent=95,
    log_prefix="Refresh",
    force=False,
    heading=None,
):
    """Refresh profile data without deleting the previous cache first.

    When force=True, bypass cache and always fetch from the provider.
    Returns (success, failures_list, summary_dict).
    """
    creds = pm.get_credentials()
    xt_url = creds.get("xtream_url", "")
    xt_user = creds.get("xtream_username", "")
    xt_pwd = creds.get("xtream_password", "")
    m3u_url = creds.get("m3u_url", "")
    steps, load_live = _build_fetch_steps(xt_url, xt_user, xt_pwd, m3u_url, force=force)
    epg_inst = None
    if load_live:
        epg_inst = EPG(addon)
        steps.append((_t(30357), lambda: epg_inst.fetch()))

    failures = []
    total = len(steps)
    if not total:
        _log(f"{log_prefix} profile {profile_num}: no enabled data sections to refresh")
        return True, failures, {}

    for idx, (label, fn) in enumerate(steps):
        if progress and progress.iscanceled():
            failures.append("cancelled")
            _log(f"{log_prefix} profile {profile_num}: cancelled")
            break
        percent = start_percent + int(((idx + 1) / total) * (end_percent - start_percent))
        if progress:
            if heading:
                progress.update(percent, heading + "\n" + label)
            else:
                progress.update(percent, label)
        try:
            fn()
        except Exception as e:
            failures.append(label)
            _log(f"{log_prefix} profile {profile_num} error {label}: {e}")

    summary = {}
    try:
        if xt_url and xt_user and xt_pwd:
            _src_key = f"{xt_url}|{xt_user}|{xt_pwd}"
            for stype, label in [("live", "live_channels"), ("movie", "movies"), ("series", "series")]:
                streams_cache = _cache_load(f"xtream_streams_{stype}")
                if isinstance(streams_cache, dict) and streams_cache.get("_src") == _src_key:
                    summary[label] = len(streams_cache.get("_data") or [])
            for stype, label in [("live", "live_categories"), ("movie", "movie_categories"), ("series", "series_categories")]:
                cats_cache = _cache_load(f"xtream_cats_{stype}")
                if isinstance(cats_cache, dict) and cats_cache.get("_src") == _src_key:
                    summary[label] = len(cats_cache.get("_data") or [])
        if epg_inst is not None:
            try:
                summary["epg_channels"] = len(epg_inst.channel_names or {})
            except Exception:
                pass
    except Exception:
        pass

    return not failures, failures, summary


def _prefetch_all_data():
    creds = _get_credentials()
    xt_url = creds.get("xtream_url", "")
    xt_user = creds.get("xtream_username", "")
    xt_pwd = creds.get("xtream_password", "")
    m3u_url = creds.get("m3u_url", "")
    _steps, load_live = _build_fetch_steps(xt_url, xt_user, xt_pwd, m3u_url, force=False)

    pd = xbmcgui.DialogProgress()
    pd.create("Xstream Pro", _t(30284))

    ok, failures, _summary = _run_profile_refresh_steps(
        pm.active,
        progress=pd,
        start_percent=5,
        end_percent=95,
        log_prefix="Prefetch",
        force=False,
    )

    try:
        pd.close()
    except Exception:
        pass

    if not ok:
        xbmcgui.Dialog().notification(
            "Xstream Pro",
            "Profile refresh failed. Existing cache was kept.",
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )
        _log(f"Prefetch failed; kept existing cache. Failed steps: {', '.join(failures)}")
        return False

    if load_live and addon.getSetting("auto_sync_pvr").lower() == "true":
        try:
            _sync_pvr_force()
        except Exception as e:
            _log(f"Prefetch PVR sync error: {e}")

    xbmcgui.Dialog().notification("Xstream Pro", _t(30080))
    return True


def sports_refresh_profile_menu():
    return _user_profiles.sports_refresh_profile_menu()


def refresh_profile_menu():
    return _user_profiles.refresh_profile_menu()


def _refresh_all_profiles_with_progress(profiles):
    """Refresh all profiles with overall progress dialog and detailed summary."""
    if not _acquire_pvr_sync_lock():
        return
    total_profiles = len(profiles)
    if total_profiles == 0:
        _release_pvr_sync_lock()
        return

    progress = xbmcgui.DialogProgress()
    progress.create(_t(30012), _t(30736))
    failed_profiles = []
    profile_results = []

    try:
        for idx, (num, name) in enumerate(profiles):
            if progress.iscanceled():
                break

            profile_start = int((idx / total_profiles) * 100)
            profile_end = int(((idx + 1) / total_profiles) * 100)
            heading = _t(31400, num, name) + "  ({0}/{1})".format(idx + 1, total_profiles)
            progress.update(profile_start, heading)

            original_active = pm.active
            pm.active = str(num)

            before_counts = {"live": 0, "movie": 0, "series": 0, "epg": 0}
            try:
                _src_key = "{}|{}|{}".format(
                    pm.get_credentials().get("xtream_url", ""),
                    pm.get_credentials().get("xtream_username", ""),
                    pm.get_credentials().get("xtream_password", ""),
                )
                for stype in ("live", "movie", "series"):
                    cached = _cache_load(f"xtream_streams_{stype}")
                    if isinstance(cached, dict) and cached.get("_src") == _src_key:
                        before_counts[stype] = len(cached.get("_data") or [])
                try:
                    epg_before = EPG(addon)
                    if epg_before.channel_names is not None:
                        before_counts["epg"] = len(epg_before.channel_names or {})
                except Exception:
                    pass
            except Exception:
                pass

            try:
                ok, failures, summary = _run_profile_refresh_steps(
                    num,
                    progress=progress,
                    start_percent=profile_start,
                    end_percent=profile_end,
                    log_prefix="Refresh",
                    force=True,
                    heading=heading,
                )
            except Exception as e:
                ok = False
                failures = [str(e)]
                summary = {}
                _log(f"Refresh all: profile {num} error: {e}")

            pm.active = original_active

            if ok:
                profile_results.append((num, name, before_counts, summary))
                _log(f"Refresh all: profile {num} ok")
            else:
                failed_profiles.append(name)
                _log(f"Refresh all: profile {num} failed; kept existing cache")

        progress.update(100, _t(30080))
        xbmc.sleep(_tvos_sleep(500))
        progress.close()

        if not failed_profiles and _provider_availability_marking_enabled():
            _refresh_provider_availability_cache_after_profile_load(show_progress=True)

        if profile_results:
            lines = []
            for pnum, pname, before, after in profile_results:
                if len(profile_results) > 1:
                    lines.append("[B]Profile {0} - {1}[/B]".format(pnum, pname))
                live_after = after.get("live_channels", 0)
                live_delta = live_after - before.get("live", 0)
                lines.append("Live TV - {} {:+}".format(live_after, live_delta))
                movie_after = after.get("movies", 0)
                movie_delta = movie_after - before.get("movie", 0)
                lines.append("Movies - {} {:+}".format(movie_after, movie_delta))
                series_after = after.get("series", 0)
                series_delta = series_after - before.get("series", 0)
                lines.append("TV Shows - {} {:+}".format(series_after, series_delta))
            xbmcgui.Dialog().ok("Xstream Pro", "\n".join(lines))

        if failed_profiles:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Some profiles failed. Existing cache was kept.",
                xbmcgui.NOTIFICATION_WARNING,
                5000,
            )

    except Exception as e:
        try:
            progress.close()
        except Exception:
            pass
        _log(f"Refresh all error: {e}")
        xbmcgui.Dialog().notification(
            "Xstream Pro", _t(30074), xbmcgui.NOTIFICATION_ERROR
        )
    finally:
        _release_pvr_sync_lock()


def _refresh_single_profile_silent(profile_num, force=False):
    """Refresh data for a specific profile without progress dialog (for batch operations)."""
    original_active = pm.active
    pm.active = str(profile_num)

    try:
        ok, failures, _summary = _run_profile_refresh_steps(
            profile_num,
            log_prefix="Silent refresh",
            force=force,
        )
        if ok:
            _log(f"Silently refreshed profile {profile_num}")
        else:
            _log(
                "Silent refresh failed for profile {0}; kept existing cache. Failed steps: {1}".format(
                    profile_num,
                    ", ".join(failures),
                )
            )
        return ok
    finally:
        pm.active = original_active


def _refresh_profile_data(profile_num):
    """Refresh data for a specific profile with progress bar."""
    profile_name = addon.getSetting(f"profile_{profile_num}_name") or _t(
        30390, profile_num
    )
    progress = xbmcgui.DialogProgress()
    progress.create(_t(30012), _t(30749, profile_name))
    original_active = pm.active
    pm.active = str(profile_num)

    try:
        progress.update(10, _t(30750))
        before_counts = {"live": 0, "movie": 0, "series": 0, "epg": 0}
        try:
            _src_key = "{}|{}|{}".format(
                pm.get_credentials().get("xtream_url", ""),
                pm.get_credentials().get("xtream_username", ""),
                pm.get_credentials().get("xtream_password", ""),
            )
            for stype in ("live", "movie", "series"):
                cached = _cache_load(f"xtream_streams_{stype}")
                if isinstance(cached, dict) and cached.get("_src") == _src_key:
                    before_counts[stype] = len(cached.get("_data") or [])
            try:
                epg_before = EPG(addon)
                if epg_before.channel_names is not None:
                    before_counts["epg"] = len(epg_before.channel_names or {})
            except Exception:
                pass
        except Exception:
            pass
        ok, failures, summary = _run_profile_refresh_steps(
            profile_num,
            progress=progress,
            start_percent=25,
            end_percent=95,
            log_prefix="Refresh",
            force=True,
        )

        if ok and _provider_availability_marking_enabled():
            _refresh_provider_availability_cache_after_profile_load(show_progress=False)

        progress.update(100, _t(30080))
        xbmc.sleep(_tvos_sleep(500))
        if ok:
            lines = []
            live_after = summary.get("live_channels", 0)
            live_delta = live_after - before_counts.get("live", 0)
            lines.append("Live TV - {} {:+}".format(live_after, live_delta))
            movie_after = summary.get("movies", 0)
            movie_delta = movie_after - before_counts.get("movie", 0)
            lines.append("Movies - {} {:+}".format(movie_after, movie_delta))
            series_after = summary.get("series", 0)
            series_delta = series_after - before_counts.get("series", 0)
            lines.append("TV Shows - {} {:+}".format(series_after, series_delta))
            xbmcgui.Dialog().ok("Xstream Pro", "\n".join(lines))
        else:
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                "Profile refresh failed. Existing cache was kept.",
                xbmcgui.NOTIFICATION_WARNING,
                5000,
            )
            _log(
                "Refresh profile {0} failed; kept existing cache. Failed steps: {1}".format(
                    profile_num,
                    ", ".join(failures),
                )
            )
    except Exception as e:
        _log(f"Refresh profile data error: {e}")

        _log(f"Traceback: {traceback.format_exc()}")
        xbmcgui.Dialog().notification(
            "Xstream Pro", _t(30081), xbmcgui.NOTIFICATION_ERROR
        )
    finally:
        try:
            progress.close()
        except Exception as e:
            _log(f"PVR favorites progress close warning: {e}")
        pm.active = original_active


def _refresh_profiles_batch(profile_nums):
    """Load multiple profiles under a single progress dialog.

    Used after restore to avoid showing multiple 'Refresh' dialogs.
    """
    if not profile_nums:
        return []

    total_profiles = len(profile_nums)
    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", _t(31083, total_profiles))
    loaded = []

    try:
        for p_idx, profile_num in enumerate(profile_nums):
            profile_name = addon.getSetting(f"profile_{profile_num}_name") or _t(
                30390, profile_num
            )
            overall_pct = int((p_idx / total_profiles) * 100)
            progress.update(
                overall_pct,
                _t(31084, p_idx + 1, total_profiles, profile_name),
            )

            try:
                original_active = pm.active
                pm.active = str(profile_num)
                try:
                    ok, failures, _summary = _run_profile_refresh_steps(
                        profile_num,
                        progress=progress,
                        start_percent=overall_pct,
                        end_percent=min(100, overall_pct + int(100 / total_profiles)),
                        log_prefix="Batch load",
                        force=True,
                    )
                    if ok:
                        loaded.append(profile_num)
                        _log(f"Batch loaded profile {profile_num}")
                    else:
                        _log(
                            "Batch load failed for profile {0}; kept existing cache. Failed steps: {1}".format(
                                profile_num,
                                ", ".join(failures),
                            )
                        )
                finally:
                    pm.active = original_active
            except Exception as e:
                _log(f"Batch profile {profile_num} error: {e}")

            if progress.iscanceled():
                break

        progress.update(100, _t(31085))
        xbmc.sleep(_tvos_sleep(300))
    finally:
        try:
            progress.close()
        except Exception:
            pass

    if loaded and _provider_availability_marking_enabled():
        _refresh_provider_availability_cache_after_profile_load(show_progress=True)

    return loaded


def refresh_data():
    choice = xbmcgui.Dialog().yesno(
        "Xstream Pro",
        _t(30050) + "\n\n" + _t(30051),
        yeslabel=_t(30167),
        nolabel=_t(30161),
    )
    if not choice:
        return False

    if not _acquire_pvr_sync_lock():
        return False
    try:
        first_time = _is_first_refresh()
        pd = xbmcgui.DialogProgress()
        ok = False
        pd.create("Xstream Pro", _t(30286))
        try:
            pd.update(10, _t(31440))
            _log(
                "Refresh data: keeping existing profile cache until replacement data is fetched"
            )
            rt = RefreshTracker(addon)
            rt.set_last_refresh()
            pd.update(25, _t(31441))
            ok = _prefetch_all_data()
            if ok and _provider_availability_marking_enabled():
                _refresh_provider_availability_cache_after_profile_load(show_progress=False)
            pd.update(100, _t(30563))
        finally:
            pd.close()
        if not ok:
            return False
        if first_time:
            _mark_first_refresh_done()
        choice = xbmcgui.Dialog().yesno(
            "Xstream Pro", _t(30052), yeslabel=_t(30165), nolabel=_t(30164)
        )
        if choice:
            _restart_or_prompt()
            return
        xbmc.executebuiltin("Container.Refresh")
    finally:
        _release_pvr_sync_lock()


