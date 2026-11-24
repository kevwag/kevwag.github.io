"""Playback and playback-monitor helpers for Xstream Pro."""

_OWNED = {'_playback_duration_path', '_save_playback_duration', '_load_playback_duration', '_epg_enabled', '_set_live_props', 'play_stream', '_monitor_playback', '_prepare_playback_item'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _history_class(name):
    getter = globals().get("_get_history_classes")
    if callable(getter):
        return getter()[name]
    return globals()[name]


def _playback_duration_path(stream_id):
    """Path for playback-discovered duration cache (global, keyed by stream_id)."""
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(stream_id))
    return os.path.join(profile, f"playback_duration_{safe_id}.json")


def _save_playback_duration(stream_id, duration):
    """Cache duration discovered during playback for reuse in list views."""
    if not stream_id or not duration:
        return
    path = _playback_duration_path(stream_id)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"duration": int(duration), "timestamp": time.time()}, f)
            try:
                f.flush()
                _safe_fsync(f)
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception as e:
        _log(f"Playback duration save error: {e}")


def _load_playback_duration(stream_id):
    """Return cached playback-discovered duration in seconds, or 0."""
    if not stream_id:
        return 0
    try:
        path = _playback_duration_path(stream_id)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return int(data.get("duration", 0))
    except Exception:
        return 0


def _epg_enabled():
    return addon.getSetting("show_epg_live").lower() == "true"


def _set_live_props(li):
    li.setContentLookup(False)


def _stream_language_matches(stream, wanted):
    wanted = str(wanted or "").strip().lower()
    if not wanted:
        return False
    if isinstance(stream, dict):
        values = [
            stream.get("language", ""),
            stream.get("name", ""),
            stream.get("label", ""),
        ]
    else:
        values = [stream]
    for value in values:
        text = str(value or "").strip().lower()
        if text and (text == wanted or text.startswith(wanted) or wanted in text):
            return True
    return False


def _apply_default_stream_languages(player):
    audio = (addon.getSetting("default_audio_language") or "").strip()
    subtitle = (addon.getSetting("default_subtitle_language") or "").strip()
    if audio:
        try:
            for idx, stream in enumerate(player.getAvailableAudioStreams() or []):
                if _stream_language_matches(stream, audio):
                    player.setAudioStream(idx)
                    break
        except Exception as exc:
            _log("Default audio language warning: {0}".format(exc))
    if subtitle:
        try:
            for idx, stream in enumerate(player.getAvailableSubtitleStreams() or []):
                if _stream_language_matches(stream, subtitle):
                    player.setSubtitleStream(idx)
                    try:
                        player.showSubtitles(True)
                    except Exception:
                        pass
                    break
        except Exception as exc:
            _log("Default subtitle language warning: {0}".format(exc))


def _resume_choice_for_item(pnum, name, play_url):
    behavior = addon.getSetting("resume_playback_behavior") or "Always ask before resuming"
    if behavior == "Never resume":
        return 0, 0
    try:
        for entry in _history_class("ResumePoints")(addon, profile_num=pnum).get_all():
            if entry.get("url") == play_url and entry.get("name") == name:
                pos = int(entry.get("position", 0) or 0)
                dur = int(entry.get("duration", 0) or 0)
                if pos <= 0:
                    return 0, 0
                if behavior == "Always resume":
                    return pos, dur
                minutes = max(1, int(pos / 60))
                if xbmcgui.Dialog().yesno(
                    "Xstream Pro",
                    "Resume from {0} minute(s)?".format(minutes),
                    yeslabel="Resume",
                    nolabel="Start over",
                ):
                    return pos, dur
                return 0, 0
    except Exception as exc:
        _log("Resume lookup warning: {0}".format(exc))
    return 0, 0


def play_stream(
    play_url,
    name,
    title="",
    plot="",
    icon="",
    stype="live",
    series_id="",
    season_num="",
    ep_id="",
    profile_num=None,
    kodi_props=None,
    stream_ua="",
    stream_ref="",
    resume_pos=0,
    resume_total=0,
    tmdb_id="",
):
    pnum = profile_num if profile_num is not None else pm.active
    if stype in ("movie", "series") and not resume_pos:
        resume_pos, resume_total = _resume_choice_for_item(pnum, name, play_url)
    li = xbmcgui.ListItem(path=play_url)
    li.setProperty("IsPlayable", "true")
    if resume_pos:
        li.setProperty("ResumeTime", str(resume_pos))
        li.setProperty("TotalTime", str(resume_total or 0))
    info_tag = li.getVideoInfoTag()
    info_tag.setMediaType("video")
    info_tag.setTitle(title or name)
    info_tag.setPlot(plot or "")
    if icon:
        li.setArt({"icon": icon, "thumb": icon})
    _prepare_playback_item(li)
    # Per-channel properties from #KODIPROP / #EXTVLCOPT
    if kodi_props:
        for k, v in kodi_props.items():
            li.setProperty(k, v)
    if stream_ua:
        li.setProperty("http-header", f"User-Agent={urllib.parse.quote(stream_ua)}")
    if stream_ref:
        li.setProperty("http-header", f"Referer={urllib.parse.quote(stream_ref)}")
    if stype == "live":
        _set_live_props(li)
    xbmcplugin.setResolvedUrl(addon_handle, True, listitem=li)
    upnext_data = None
    # Prepare next episode data for autoplay and/or Up Next
    autoplay_next = addon.getSetting("series_autoplay_next").lower() == "true"
    upnext_enabled = addon.getSetting("series_upnext_enabled").lower() == "true"
    if (
        stype == "series"
        and series_id
        and season_num
        and ep_id
        and (autoplay_next or upnext_enabled)
    ):
        try:
            creds = _get_credentials_for_profile(pnum)
            xt_url = creds.get("xtream_url", "")
            xt_user = creds.get("xtream_username", "")
            xt_pwd = creds.get("xtream_password", "")
            info = IPTV.get_xtream_series_info(xt_url, xt_user, xt_pwd, series_id)
            eps = info.get("episodes", {}).get(season_num, [])
            for i, ep in enumerate(eps):
                if str(ep.get("id", "")) == str(ep_id):
                    current_ep_num = ep.get("episode_num", "")
                    if i + 1 < len(eps):
                        next_ep = eps[i + 1]
                        next_ep_id = str(next_ep.get("id", ""))
                        next_title = next_ep.get("title") or _t(
                            30542, next_ep.get("episode_num", "?")
                        )
                        next_icon = next_ep.get("info", {}).get("movie_image") or icon
                        next_play_url = IPTV.build_xtream_stream_url(
                            xt_url, xt_user, xt_pwd, next_ep, "series"
                        )
                        next_li = xbmcgui.ListItem(path=next_play_url)
                        next_li.setProperty("IsPlayable", "true")
                        next_info = next_li.getVideoInfoTag()
                        next_info.setMediaType("episode")
                        next_info.setTitle(next_title)
                        next_info.setPlot(next_ep.get("info", {}).get("plot", ""))
                        if next_icon:
                            next_li.setArt({"icon": next_icon, "thumb": next_icon})
                        _prepare_playback_item(next_li)
                        next_url = build_url(
                            {
                                "mode": "play_stream",
                                "url": next_play_url,
                                "name": next_title,
                                "icon": next_icon,
                                "stype": "series",
                                "series_id": series_id,
                                "season_num": season_num,
                                "ep_id": next_ep_id,
                                "profile_num": pnum,
                            }
                        )
                        if autoplay_next:
                            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                            playlist.add(next_url, next_li)
                            _log(f"Queued next episode: {next_title}")
                        if upnext_enabled:
                            upnext_data = {
                                "current_episode": {
                                    "episodeid": ep_id,
                                    "tvshowid": series_id,
                                    "title": title or name,
                                    "art": {"thumb": icon},
                                    "season": season_num,
                                    "episode": current_ep_num,
                                    "showtitle": title or name,
                                    "plot": plot or "",
                                    "playcount": 0,
                                },
                                "next_episode": {
                                    "episodeid": next_ep_id,
                                    "tvshowid": series_id,
                                    "title": next_title,
                                    "art": {"thumb": next_icon},
                                    "season": season_num,
                                    "episode": next_ep.get("episode_num", ""),
                                    "showtitle": next_title,
                                    "plot": next_ep.get("info", {}).get("plot", ""),
                                    "playcount": 0,
                                },
                                "play_url": next_url,
                            }
                    break
        except Exception as e:
            _log(f"Next episode queue error: {e}")
    # Store series metadata in history for proper playback from Recently Watched
    extra = None
    if stype == "series" and series_id and season_num and ep_id:
        extra = {"series_id": series_id, "season_num": season_num, "ep_id": ep_id}
    # Extract stream_id for playback duration caching
    stream_id = ""
    if stype == "movie":
        m = re.search(r"/(\d+)\.[a-zA-Z0-9]+$", play_url)
        if m:
            stream_id = m.group(1)
    elif stype == "series" and ep_id:
        stream_id = str(ep_id)

    # Monitor playback for resume saving and error recovery
    _monitor_playback(name, play_url, stype, profile_num=pnum, upnext_data=upnext_data, stream_id=stream_id, icon=icon, extra=extra, tmdb_id=tmdb_id, title=title, plot=plot)


def _monitor_playback(name, url, stype="live", profile_num=None, upnext_data=None, stream_id="", icon="", extra=None, tmdb_id="", title="", plot=""):
    """Background thread to save resume position, detect stream errors, and notify Up Next."""
    pnum = profile_num if profile_num is not None else pm.active

    def _worker():
        class _PlaybackObserver(xbmc.Player):
            def __init__(self):
                xbmc.Player.__init__(self)
                self.started = False
                self.failed = False

            def reset_start_state(self):
                self.started = False
                self.failed = False

            def onAVStarted(self):
                self.started = True

            def onPlayBackStarted(self):
                self.started = True

            def onPlayBackError(self):
                self.failed = True

        player = _PlaybackObserver()

        def _wait_for_start_or_failure():
            deadline = time.time() + _PLAYBACK_STARTUP_TIMEOUT
            while time.time() < deadline:
                try:
                    if player.isPlaying() or player.started:
                        player.started = True
                        return "started"
                    if player.failed:
                        return "failed"
                except Exception:
                    pass
                xbmc.sleep(_tvos_sleep(_PLAYBACK_STARTUP_POLL))
            return "timeout"

        def _retry_after_source_failure():
            _log(f"Playback source failed for: {name}, retrying up to {_PLAYBACK_MAX_RETRIES} times")
            for attempt in range(1, _PLAYBACK_MAX_RETRIES + 1):
                player.reset_start_state()
                xbmcgui.Dialog().notification(
                    "Xstream Pro",
                    _t(31446).format(attempt, _PLAYBACK_MAX_RETRIES),
                    xbmcgui.NOTIFICATION_INFO,
                    2000,
                )
                li = xbmcgui.ListItem(path=url)
                li.setProperty("IsPlayable", "true")
                _prepare_playback_item(li)
                player.play(url, li)
                state = _wait_for_start_or_failure()
                if state == "started":
                    return True
                if state == "timeout":
                    _log(f"Playback retry timed out waiting for start: {name}")
                    return False
                xbmc.sleep(_tvos_sleep(_PLAYBACK_RETRY_DELAY))
            _log(f"All {_PLAYBACK_MAX_RETRIES} playback attempts failed for: {name}")
            xbmcgui.Dialog().notification(
                "Xstream Pro",
                _t(31447),
                xbmcgui.NOTIFICATION_ERROR,
                3000,
            )
            return False

        startup_state = _wait_for_start_or_failure()
        if startup_state != "started":
            if startup_state == "failed":
                if stype in ("movie", "series"):
                    if not _retry_after_source_failure():
                        return
                elif stype == "live":
                    _log(f"Live stream failed to start: {name}")
                    xbmcgui.Dialog().notification(
                        "Xstream Pro",
                        _t(31447),
                        xbmcgui.NOTIFICATION_ERROR,
                        3000,
                    )
                    return
            else:
                _log(f"Playback did not start within {_PLAYBACK_STARTUP_TIMEOUT}s for: {name}; not retrying without a player error")
                return
        _apply_default_stream_languages(player)
        if stype in ("movie", "series"):
            wh_extra = dict(extra) if extra else {}
            if tmdb_id:
                wh_extra["tmdb_id"] = str(tmdb_id)
            if title:
                wh_extra["title"] = str(title)
            if plot:
                wh_extra["plot"] = str(plot)
            _history_class("WatchHistory")(addon, profile_num=pnum).add(name, url, icon, stype, wh_extra)
        upnext_sent = False
        cached_dur = 0
        upnext_dur_warned = False
        last_pos = 0
        while player.isPlaying():
            try:
                pos = player.getTime()
                dur = player.getTotalTime()
                last_pos = pos
                if stype in ("movie", "series") and dur > 0:
                    resume_extra = {"stype": stype, "icon": icon}
                    if extra:
                        resume_extra.update(extra)
                    if title:
                        resume_extra["title"] = str(title)
                    if plot:
                        resume_extra["plot"] = str(plot)
                    _history_class("ResumePoints")(addon, profile_num=pnum).save_position(name, url, pos, dur, resume_extra)
                if dur > 0:
                    cached_dur = dur
                    if stream_id:
                        _save_playback_duration(stream_id, dur)
                if (
                    upnext_data
                    and addon.getSetting("series_upnext_enabled").lower() == "true"
                    and xbmc.getCondVisibility("System.HasAddon(service.upnext)")
                    and not upnext_sent
                ):
                    if cached_dur > 0 and (cached_dur - pos) <= 60:
                        try:
                            import base64

                            encoded = base64.b64encode(
                                json.dumps(upnext_data).encode("utf-8")
                            ).decode("ascii")
                            rpc_payload = {
                                "jsonrpc": "2.0",
                                "method": "JSONRPC.NotifyAll",
                                "params": {
                                    "sender": "plugin.video.xstream-pro.SIGNAL",
                                    "message": "upnext_data",
                                    "data": [encoded],
                                },
                                "id": 1,
                            }
                            xbmc.executeJSONRPC(json.dumps(rpc_payload))
                            upnext_sent = True
                            _log("Sent Up Next notification")
                        except Exception as e:
                            _log(f"Up Next notification error: {e}")
                    elif cached_dur == 0 and pos > 120 and not upnext_dur_warned:
                        _log("Up Next: stream duration unavailable, skipping upnext notification")
                        upnext_dur_warned = True
            except Exception as e:
                _log(f"Playback monitoring error: {e}")
            xbmc.sleep(_tvos_sleep(5000))
        if stype in ("movie", "series") and cached_dur > 0 and last_pos >= max(60, cached_dur * 0.90):
            try:
                if stype == "movie" and stream_id:
                    _history_class("WatchedMovies")(addon, profile_num=pnum).mark_watched(stream_id)
                elif stype == "series" and extra:
                    series_id = extra.get("series_id", "")
                    season_num = extra.get("season_num", "")
                    ep_id = extra.get("ep_id", "")
                    if series_id and season_num and ep_id:
                        _history_class("WatchedEpisodes")(addon, profile_num=pnum).mark_watched(series_id, season_num, ep_id)
            except Exception as exc:
                _log("Watched state update warning: {0}".format(exc))

    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()


def _prepare_playback_item(li):
    if addon.getSetting("use_inputstream_adaptive").lower() == "true":
        li.setProperty("inputstream", "inputstream.adaptive")
        li.setProperty("inputstream.adaptive.manifest_type", "hls")
    custom_ua = addon.getSetting("custom_user_agent")
    if custom_ua:
        li.setProperty("http-header", f"User-Agent={urllib.parse.quote(custom_ua)}")
