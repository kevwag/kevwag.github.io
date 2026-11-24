"""Provider availability and TMDB filtering helpers for Xstream Pro."""

_OWNED = {'_provider_only_tmdb_enabled', '_provider_availability_path', '_provider_title_key', '_provider_year', '_provider_availability_add', '_load_provider_availability_cache', '_save_provider_availability_cache', '_clear_provider_availability_cache', '_provider_tmdb_id_set', '_provider_availability_item_available', '_filter_provider_available_items', '_filter_provider_available_items_strict', '_find_provider_series_id_for_show', '_xtream_series_seasons_available', '_xtream_episodes_available', '_filter_provider_seasons', '_filter_provider_episodes', '_rebuild_provider_availability_cache', '_provider_item_available_for_tmdb'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _provider_only_tmdb_enabled():
    return addon.getSetting("tmdb_provider_only_available").lower() == "true"


def _provider_availability_path():
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    return os.path.join(profile, "tmdb_provider_availability.json")


def _provider_title_key(value):
    value = str(value or "").lower()
    value = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", value)
    value = re.sub(
        r"\b(4k|uhd|2160p|1080p|720p|480p|x264|x265|h264|h265|hevc|hdr|webdl|web-dl|webrip|bluray|brrip|hdrip|dvdrip|cam|ts)\b",
        " ",
        value,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _provider_year(*values):
    for value in values:
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
        if match:
            return match.group(1)
    return ""


def _provider_availability_add(index, media_type, name, item=None):
    key = _provider_title_key(name)
    if not key:
        return
    item = item or {}
    bucket = index.setdefault(media_type, {"titles": {}, "tmdb_ids": []})
    titles = bucket.setdefault("titles", {})
    years = titles.setdefault(key, [])
    year = _provider_year(
        name,
        item.get("year"),
        item.get("release_date"),
        item.get("first_air_date"),
    )
    if year and year not in years:
        years.append(year)
    for id_key in ("tmdb_id", "tmdb", "tmdbid"):
        tmdb_id = str(item.get(id_key) or "").strip()
        if tmdb_id and tmdb_id not in bucket["tmdb_ids"]:
            bucket["tmdb_ids"].append(tmdb_id)


def _load_provider_availability_cache():
    path = _provider_availability_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _PROVIDER_AVAILABILITY_MEM.update({"path": path, "mtime": None, "data": None, "sets": {}})
        return None
    if (
        _PROVIDER_AVAILABILITY_MEM.get("path") == path
        and _PROVIDER_AVAILABILITY_MEM.get("mtime") == mtime
        and _PROVIDER_AVAILABILITY_MEM.get("data") is not None
    ):
        return _PROVIDER_AVAILABILITY_MEM["data"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _PROVIDER_AVAILABILITY_MEM.update({"path": path, "mtime": mtime, "data": data, "sets": {}})
        return data
    except Exception:
        return None


def _save_provider_availability_cache(index):
    path = _provider_availability_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp, path)
    try:
        _PROVIDER_AVAILABILITY_MEM.update({
            "path": path,
            "mtime": os.path.getmtime(path),
            "data": index,
            "sets": {},
        })
    except Exception:
        pass


def _clear_provider_availability_cache():
    try:
        path = _provider_availability_path()
        if os.path.exists(path):
            os.remove(path)
            _log("Provider availability cache deleted")
    except Exception as e:
        _log(f"Provider availability cache delete warning: {e}")
    _PROVIDER_AVAILABILITY_MEM.update({"path": "", "mtime": None, "data": None, "sets": {}})


def _provider_tmdb_id_set(cache, tmdb_type):
    sets = _PROVIDER_AVAILABILITY_MEM.setdefault("sets", {})
    key = (id(cache), tmdb_type)
    if key in sets:
        return sets[key]
    bucket = (cache.get(tmdb_type) or {})
    values = set(str(v) for v in (bucket.get("tmdb_ids") or []) if v)
    sets[key] = values
    return values


def _provider_availability_item_available(item, cache, strict_title_year=False):
    tmdb_type = "tv" if item.get("tmdb_type") == "tv" else "movie"
    bucket = cache.get(tmdb_type) or {}
    tmdb_id = str(item.get("tmdb_id") or "").strip()
    if tmdb_id and tmdb_id in _provider_tmdb_id_set(cache, tmdb_type):
        return True
    title = (
        item.get("showtitle")
        or item.get("tvshowtitle")
        or item.get("title")
        or item.get("name")
        or ""
    )
    key = _provider_title_key(title)
    if not key:
        return False
    titles = bucket.get("titles") or {}
    provider_years = titles.get(key)
    if not provider_years:
        return False
    provider_years = [str(y) for y in provider_years if y]
    item_year = _provider_year(
        item.get("year"),
        item.get("release_date"),
        item.get("first_air_date"),
        item.get("premiered"),
    )
    known_years = {y for y in provider_years if y}
    if not item_year:
        return not strict_title_year
    if known_years:
        return item_year in known_years
    return not strict_title_year


def _filter_provider_available_items(items):
    if not _provider_only_tmdb_enabled():
        return items
    cache = _load_provider_availability_cache()
    if not cache:
        cache = _refresh_provider_availability_cache_after_profile_load(show_progress=False)
    if not cache:
        return []
    return [item for item in (items or []) if _provider_availability_item_available(item, cache)]


def _filter_provider_available_items_strict(items):
    if not _provider_only_tmdb_enabled():
        return items
    cache = _load_provider_availability_cache()
    if not cache:
        cache = _refresh_provider_availability_cache_after_profile_load(show_progress=False)
    if not cache:
        return []
    return [
        item
        for item in (items or [])
        if _provider_availability_item_available(item, cache, strict_title_year=True)
    ]


def _find_provider_series_id_for_show(tmdb_id, title):
    """Search enabled profiles for a series matching tmdb_id or title.
    Returns (url, user, pwd, series_id) or (None, None, None, None).
    """
    for pnum, pname in _enabled_profiles_with_credentials():
        creds = _get_credentials_for_profile(pnum)
        xt_url = creds.get("xtream_url", "")
        xt_user = creds.get("xtream_username", "")
        xt_pwd = creds.get("xtream_password", "")
        if not (xt_url and xt_user and xt_pwd):
            continue
        for item in _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "series"):
            if str(item.get("tmdb_id") or "").strip() == str(tmdb_id):
                return xt_url, xt_user, xt_pwd, item.get("series_id")
        # Fallback: title match
        key = _provider_title_key(title)
        if key:
            for item in _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "series"):
                if _provider_title_key(item.get("name", "")) == key:
                    return xt_url, xt_user, xt_pwd, item.get("series_id")
    return None, None, None, None


def _xtream_series_seasons_available(url, user, pwd, series_id):
    """Return set of season numbers that have episodes from Xtream series info."""
    try:
        info = IPTV.get_xtream_series_info(url, user, pwd, series_id)
        seasons = set()
        for ep_list in info.get("episodes", {}).values():
            for item in ep_list:
                try:
                    seasons.add(int(item.get("season", "1")))
                except (ValueError, TypeError):
                    pass
        return seasons
    except Exception as e:
        _log(f"Xtream seasons lookup error: {e}")
        return None


def _xtream_episodes_available(url, user, pwd, series_id, season_num):
    """Return set of episode numbers available for a specific season."""
    try:
        info = IPTV.get_xtream_series_info(url, user, pwd, series_id)
        episodes = set()
        for ep_list in info.get("episodes", {}).values():
            for item in ep_list:
                try:
                    if int(item.get("season", "1")) == season_num:
                        episodes.add(int(item.get("episode_num", item.get("num", ""))))
                except (ValueError, TypeError):
                    pass
        return episodes
    except Exception as e:
        _log(f"Xtream episodes lookup error: {e}")
        return None


def _filter_provider_seasons(tmdb_id, showtitle, seasons):
    _filter_off = not _provider_only_tmdb_enabled() and addon.getSetting("tmdb_mark_unavailable").lower() != "true"
    if _filter_off:
        return seasons
    url, user, pwd, series_id = _find_provider_series_id_for_show(tmdb_id, showtitle)
    if not series_id:
        return seasons
    provider_seasons = _xtream_series_seasons_available(url, user, pwd, series_id)
    if provider_seasons is None:
        return seasons
    if not provider_seasons:
        return seasons
    seasons = [dict(s) for s in (seasons or [])]
    for s in seasons:
        try:
            sn = int(s.get("season", 0))
        except (ValueError, TypeError):
            sn = 0
        if sn not in provider_seasons:
            s["provider_unavailable"] = True
    if _provider_only_tmdb_enabled():
        seasons = [s for s in seasons if not s.get("provider_unavailable")]
    return seasons


def _filter_provider_episodes(tmdb_id, showtitle, season, episodes):
    _filter_off = not _provider_only_tmdb_enabled() and addon.getSetting("tmdb_mark_unavailable").lower() != "true"
    if _filter_off:
        return episodes
    url, user, pwd, series_id = _find_provider_series_id_for_show(tmdb_id, showtitle)
    if not series_id:
        return episodes
    try:
        season_num = int(season)
    except (ValueError, TypeError):
        return episodes
    provider_eps = _xtream_episodes_available(url, user, pwd, series_id, season_num)
    if provider_eps is None:
        return episodes
    episodes = [dict(ep) for ep in (episodes or [])]
    if not provider_eps:
        for ep in episodes:
            ep["provider_unavailable"] = True
        if _provider_only_tmdb_enabled():
            episodes = [ep for ep in episodes if not ep.get("provider_unavailable")]
        return episodes
    for ep in episodes:
        try:
            en = int(ep.get("episode", 0))
        except (ValueError, TypeError):
            en = 0
        if en not in provider_eps:
            ep["provider_unavailable"] = True
    if _provider_only_tmdb_enabled():
        episodes = [ep for ep in episodes if not ep.get("provider_unavailable")]
    return episodes


def _rebuild_provider_availability_cache(show_progress=False):
    """Build provider availability index from all enabled profiles' VOD/series data."""
    index = {"movie": {"titles": {}, "tmdb_ids": []}, "tv": {"titles": {}, "tmdb_ids": []}}
    if show_progress:
        progress = xbmcgui.DialogProgress()
        progress.create(_t(30012), "Building provider availability cache...")
    profiles = _enabled_profiles_with_credentials()
    total = len(profiles)
    try:
        for idx, (pnum, pname) in enumerate(profiles):
            if show_progress and progress.iscanceled():
                break
            if show_progress:
                pct = int(((idx + 1) / total) * 90) if total else 50
                progress.update(pct, "Scanning profile {0}/{1}...".format(idx + 1, total))
            creds = _get_credentials_for_profile(pnum)
            xt_url = creds.get("xtream_url", "")
            xt_user = creds.get("xtream_username", "")
            xt_pwd = creds.get("xtream_password", "")
            m3u_url = creds.get("m3u_url", "")
            original_active = pm.active
            pm.active = str(pnum)
            try:
                if xt_url and xt_user and xt_pwd:
                    for item in _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "movie"):
                        name = item.get("name", "")
                        _provider_availability_add(index, "movie", name, item)
                        for s in (item.get("streams") or []):
                            _provider_availability_add(index, "movie", s.get("name", name), s)
                    for item in _get_cached_xtream_streams(xt_url, xt_user, xt_pwd, "series"):
                        name = item.get("name", "")
                        _provider_availability_add(index, "tv", name, item)
                if m3u_url and not _m3u_has_credentials(m3u_url):
                    for ch in _get_cached_m3u_channels(m3u_url):
                        group = (ch.get("group") or "").lower()
                        stype = "tv" if any(kw in group for kw in ("series", "tvshow", "show")) else "movie"
                        _provider_availability_add(index, stype, ch.get("name", ""), ch)
            finally:
                pm.active = original_active
        # Deduplicate tmdb_ids
        for media_type in ("movie", "tv"):
            ids = index.get(media_type, {}).get("tmdb_ids", [])
            seen = set()
            deduped = []
            for id_val in ids:
                if id_val not in seen:
                    seen.add(id_val)
                    deduped.append(id_val)
            index.setdefault(media_type, {})["tmdb_ids"] = deduped
        _save_provider_availability_cache(index)
        return index
    finally:
        if show_progress:
            try:
                progress.update(100, "Done")
                xbmc.sleep(200)
            except Exception:
                pass
            try:
                progress.close()
            except Exception:
                pass


def _provider_item_available_for_tmdb(item, strict_title_year=False):
    cache = _load_provider_availability_cache()
    if not cache:
        cache = _rebuild_provider_availability_cache(show_progress=False)
    if not cache:
        return True
    return _provider_availability_item_available(item, cache, strict_title_year=strict_title_year)


