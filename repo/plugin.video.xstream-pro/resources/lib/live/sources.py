"""Source search/select routes for Xstream Pro."""

import requests

_OWNED = {'_source_cache_dir', '_source_cache_key', '_source_cache_path', '_source_cache_load', '_source_cache_save', '_source_profile_data_signature', '_source_result_cache_key', '_source_size_cache_key', '_load_source_size_cache', '_save_source_size_cache', '_extract_quality', '_extract_size_bytes', '_format_source_size', '_source_probe_timeout', '_is_bad_source_name', '_safe_probe_redirect', '_source_size_from_headers', '_probe_source_size_bytes', '_probe_source_sizes', '_sort_source_results', '_prepare_source_results', '_source_result_label', '_normalize_title', '_filter_stop_words', '_title_match_score', '_search_xtream_vod', '_search_live_channels', '_search_m3u_vod', '_season_eps_from_info', '_all_eps_from_info', '_find_xtream_series_sources', '_search_all_profiles_vod', '_tmdb_return_url', '_return_to_xstream_tmdb_menu', '_select_source_result', '_source_progress_update', '_source_progress_close', '_source_auto_play_first_enabled', '_source_result_exact_tmdb_match', '_pick_autoplay_source', '_source_result_play_url', '_play_source_result', 'tmdb_source_action', 'source_select', 'source_autoplay', 'resolve_source', 'tmdb_series_action'}

def init(context):
    """Install addon.py compatibility globals without replacing moved functions."""
    for key, value in (context or {}).items():
        if key not in _OWNED:
            globals()[key] = value


def _source_cache_dir():
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    path = os.path.join(profile, "source_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _source_cache_key(payload):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_cache_path(prefix, key):
    safe_key = re.sub(r"[^a-fA-F0-9]", "", str(key))
    return os.path.join(_source_cache_dir(), "{0}_{1}.json".format(prefix, safe_key))


def _source_cache_load(prefix, key, ttl_seconds):
    path = _source_cache_path(prefix, key)
    try:
        if not os.path.exists(path):
            return None
        if ttl_seconds and time.time() - os.path.getmtime(path) > ttl_seconds:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        _log("Source cache load warning: {0}".format(exc))
        return None


def _source_cache_save(prefix, key, data):
    path = _source_cache_path(prefix, key)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            try:
                f.flush()
                _safe_fsync(f)
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception as exc:
        _log("Source cache save warning: {0}".format(exc))


def _source_profile_data_signature(profile_nums):
    profile_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    signature = []
    for pnum in profile_nums:
        p = str(pnum)
        filenames = (
            "data_cache_p{0}_xtream_streams_movie.json".format(p),
            "data_cache_p{0}_xtream_streams_series.json".format(p),
            "data_cache_p{0}_xtream_cats_movie.json".format(p),
            "data_cache_p{0}_xtream_cats_series.json".format(p),
            "data_cache_p{0}_m3u.json".format(p),
        )
        for filename in filenames:
            path = os.path.join(profile_dir, filename)
            try:
                stat = os.stat(path)
                signature.append([filename, int(stat.st_mtime), int(stat.st_size)])
            except OSError:
                signature.append([filename, 0, 0])
    return signature


def _source_result_cache_key(title, year, tmdb_type, season, episode, tmdb_id, profile_nums):
    return _source_cache_key({
        "version": SOURCE_RESULT_CACHE_VERSION,
        "title": title or "",
        "year": year or "",
        "tmdb_type": tmdb_type or "",
        "season": season or "",
        "episode": episode or "",
        "tmdb_id": tmdb_id or "",
        "profiles": [str(p) for p in profile_nums],
        "profile_data": _source_profile_data_signature(profile_nums),
    })


def _source_size_cache_key(url):
    return _source_cache_key({
        "version": SOURCE_SIZE_CACHE_VERSION,
        "url": url or "",
    })


def _load_source_size_cache(url):
    if not url:
        return 0
    cached = _source_cache_load("size", _source_size_cache_key(url), SOURCE_SIZE_CACHE_TTL_SECONDS)
    try:
        return int((cached or {}).get("size_bytes") or 0)
    except Exception:
        return 0


def _save_source_size_cache(url, size_bytes):
    try:
        size_bytes = int(size_bytes or 0)
    except Exception:
        size_bytes = 0
    if not url or size_bytes <= 0:
        return
    _source_cache_save("size", _source_size_cache_key(url), {
        "version": SOURCE_SIZE_CACHE_VERSION,
        "size_bytes": size_bytes,
        "saved_at": time.time(),
    })


def _extract_quality(name):
    """Extract resolution hint from stream name/category. Returns sortable int (higher = better)."""
    n = name.upper()
    if re.search(r"\b(4K|UHD|2160P?)\b", n):
        return 4
    if re.search(r"\b(1080P?|FHD|FULL\s+HD)\b", n):
        return 3
    if re.search(r"\b(720P?|HD)\b", n):
        return 2
    if re.search(r"\b(480P?|SD)\b", n):
        return 1
    return 0


def _extract_size_bytes(text):
    """Extract size hints like 1.4GB / 850 MB from source names."""
    if not text:
        return 0
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(GB|GIB|G|MB|MIB)\b", str(text), re.I)
    if not m:
        return 0
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2).upper()
    if unit in ("GB", "GIB", "G"):
        return int(value * 1024 * 1024 * 1024)
    return int(value * 1024 * 1024)


def _format_source_size(size_bytes):
    try:
        size_bytes = int(size_bytes or 0)
    except Exception:
        size_bytes = 0
    if size_bytes >= 1024 * 1024 * 1024:
        return "{0:.2f} GB".format(size_bytes / float(1024 * 1024 * 1024))
    if size_bytes >= 1024 * 1024:
        return "{0:.0f} MB".format(size_bytes / float(1024 * 1024))
    return ""


def _source_probe_timeout():
    try:
        return max(1, int(addon.getSetting("source_probe_timeout") or "4"))
    except Exception:
        return 4


def _is_bad_source_name(text):
    return bool(re.search(r"\b(CAM|HDCAM|HDTS|TS|TELESYNC|TC|HDTC|TELECINE|WORKPRINT|WP)\b", str(text or ""), re.I))


def _safe_probe_redirect(current_url, location):
    if not location:
        return ""
    next_url = urllib.parse.urljoin(current_url, location)
    parsed = urllib.parse.urlparse(next_url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    return next_url


def _source_size_from_headers(headers, ranged=False, status_code=0):
    content_range = headers.get("Content-Range") or headers.get("content-range") or ""
    m = re.search(r"/(\d+)\s*$", content_range)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    content_length = headers.get("Content-Length") or headers.get("content-length") or ""
    if content_length:
        try:
            size = int(content_length)
            if not ranged or status_code == 200:
                return size
        except Exception:
            pass
    return 0


def _probe_source_size_bytes(url, timeout=None, max_redirects=4):
    """Probe stream size using HEAD, then Range GET. Does not download the stream."""
    if not str(url or "").lower().startswith(("http://", "https://")):
        return 0
    if timeout is None:
        timeout = _source_probe_timeout()
    custom_ua = addon.getSetting("custom_user_agent") or "Kodi"
    base_headers = {"User-Agent": custom_ua}
    for method in ("HEAD", "GET"):
        current = url
        headers = dict(base_headers)
        ranged = method == "GET"
        if ranged:
            headers["Range"] = "bytes=0-0"
        for _hop in range(max_redirects + 1):
            resp = None
            try:
                resp = requests.request(
                    method,
                    current,
                    headers=headers,
                    stream=True,
                    allow_redirects=False,
                    timeout=timeout,
                )
                if 300 <= resp.status_code < 400:
                    next_url = _safe_probe_redirect(current, resp.headers.get("Location", ""))
                    if not next_url:
                        break
                    current = next_url
                    continue
                if resp.status_code in (200, 206):
                    size = _source_size_from_headers(resp.headers, ranged=ranged, status_code=resp.status_code)
                    if size > 0:
                        return size
                break
            except Exception as exc:
                _log("Source size probe warning: {0}".format(exc))
                break
            finally:
                try:
                    if resp is not None:
                        resp.close()
                except Exception:
                    pass
    return 0


def _probe_source_sizes(results, progress=None):
    """Probe only useful candidate sources, with a hard deadline and cache."""
    probed = []
    for pnum, pname, r in results:
        copied = dict(r)
        text = "{0} {1} {2}".format(
            copied.get("name", ""),
            copied.get("category", ""),
            copied.get("extension", ""),
        )
        parsed_size = _extract_size_bytes(text)
        copied["parsed_size_bytes"] = parsed_size
        copied["size_bytes"] = parsed_size
        cached_size = _load_source_size_cache(copied.get("url", ""))
        if cached_size:
            copied["size_bytes"] = cached_size
            copied["size_cache_hit"] = True
        probed.append([pnum, pname, copied])
    sort_order = _get_setting_fast("source_sort_order", "Quality then size") or "Quality then size"
    show_size = _get_setting_fast("source_show_size", "false").lower() == "true"
    needs_probe = show_size or sort_order in ("Size then quality", "Quality then size")
    if not needs_probe or not probed:
        return [(pnum, pname, r) for pnum, pname, r in probed]

    def preliminary_key(item):
        pnum, _pname, r = item
        quality = int(r.get("quality") or 0)
        score = int(r.get("score") or 0)
        parsed_size = int(r.get("parsed_size_bytes") or 0)
        return (-quality, -score, -parsed_size, pnum)

    ordered = sorted(probed, key=preliminary_key)
    candidates = []
    if sort_order == "Quality then size":
        by_quality = {}
        for item in ordered:
            quality = int(item[2].get("quality") or 0)
            by_quality.setdefault(quality, []).append(item)
        for quality in sorted(by_quality.keys(), reverse=True):
            for item in by_quality[quality][:SOURCE_PROBE_PER_QUALITY_LIMIT]:
                if item[2].get("size_cache_hit"):
                    continue
                candidates.append(item)
                if len(candidates) >= SOURCE_PROBE_LIMIT:
                    break
            if len(candidates) >= SOURCE_PROBE_LIMIT:
                break
    else:
        candidates = [item for item in ordered if not item[2].get("size_cache_hit")][:SOURCE_PROBE_LIMIT]

    if not candidates:
        return [(pnum, pname, r) for pnum, pname, r in probed]

    def worker(item):
        r = item[2]
        probed_size = _probe_source_size_bytes(r.get("url", ""))
        if probed_size:
            r["size_bytes"] = probed_size
            _save_source_size_cache(r.get("url", ""), probed_size)

    threads = []
    for item in candidates:
        t = threading.Thread(target=worker, args=(item,))
        t.daemon = True
        t.start()
        threads.append(t)

    deadline = time.monotonic() + SOURCE_PROBE_DEADLINE_SECONDS
    total = max(1, len(threads))
    while threads and time.monotonic() < deadline:
        if _source_progress_update(
            progress,
            "Checking Source Sizes",
            len(probed),
            50 + int(((total - len(threads)) / float(total)) * 45),
        ):
            _log("Source size probe cancelled by user")
            break
        remaining_threads = []
        for t in threads:
            t.join(0.03)
            if t.is_alive():
                remaining_threads.append(t)
        threads = remaining_threads
    _source_progress_update(progress, "Checking Source Sizes", len(probed), 95)

    return [(pnum, pname, r) for pnum, pname, r in probed]


def _sort_source_results(results):
    sort_order = _get_setting_fast("source_sort_order", "Quality then size") or "Quality then size"
    skip_cam = _get_setting_fast("source_skip_cam", "false").lower() == "true"
    if skip_cam:
        filtered = []
        for pnum, pname, r in results:
            text = "{0} {1}".format(r.get("name", ""), r.get("category", ""))
            if not _is_bad_source_name(text):
                filtered.append((pnum, pname, r))
        if filtered:
            results = filtered
    def key(item):
        pnum, _pname, r = item
        quality = int(r.get("quality") or 0)
        score = int(r.get("score") or 0)
        size = int(r.get("size_bytes") or 0)
        if sort_order == "Size then quality":
            return (-size, -quality, -score, pnum)
        if sort_order == "Best title match":
            return (-score, -quality, -size, pnum)
        if sort_order == "Profile order":
            return (pnum, -quality, -size, -score)
        return (-quality, -size, -score, pnum)
    results.sort(key=key)
    return results


def _prepare_source_results(results, progress=None):
    results = _probe_source_sizes(results, progress=progress)
    return _sort_source_results(results)


def _source_result_label(pname, r):
    quality_map = {4: "4K", 3: "1080p", 2: "720p", 1: "480p", 0: ""}
    parts = []
    q = quality_map.get(int(r.get("quality") or 0), "")
    if q:
        parts.append(q)
    if _get_setting_fast("source_show_size", "false").lower() == "true":
        size = _format_source_size(r.get("size_bytes", 0))
        if size:
            parts.append(size)
    if r.get("extension"):
        parts.append(r["extension"].upper())
    if r.get("category"):
        parts.append(r["category"])
    parts.append(pname)
    return "{0} | {1}".format(r["name"], " | ".join(parts))


def _normalize_title(title):
    """Lowercase and strip punctuation for fuzzy matching. Preserves spaces for word splitting."""
    return re.sub(r"[^a-z0-9\s]", "", title.lower())


def _filter_stop_words(word_set):
    """Remove common stop words from a word set for better matching."""
    return word_set - _STOP_WORDS


def _title_match_score(search_title, candidate_name):
    """Return match score 0-100. 100 = exact normalized match."""
    s = _normalize_title(search_title)
    c = _normalize_title(candidate_name)
    if not s or not c:
        return 0
    if s == c:
        return 100

    s_words = set(s.split())
    c_words = set(c.split())

    # Substring match: only if the shorter title has at least half the
    # word count of the longer one. Prevents "Mary" matching "Project Hail Mary".
    if len(s) >= 3 and len(c) >= 3:
        shorter_words = s_words if len(s_words) <= len(c_words) else c_words
        longer_words  = c_words if len(s_words) <= len(c_words) else s_words
        word_ratio = len(shorter_words) / max(len(longer_words), 1)
        if word_ratio >= 0.5 and (s in c or c in s):
            return 80

    # Word-level overlap (stop words excluded for meaningful matching)
    s_words_filtered = _filter_stop_words(s_words)
    c_words_filtered = _filter_stop_words(c_words)
    if s_words_filtered and c_words_filtered:
        overlap = len(s_words_filtered & c_words_filtered) / max(len(s_words_filtered), len(c_words_filtered))
        return int(overlap * 60)
    return 0


def _search_xtream_vod(creds, title, year=None, tmdb_type="movie", season="", episode="", tmdb_id=""):
    """Search Xtream VOD for title match. Returns list of dicts."""
    results = []
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    if not url or not user or not pwd:
        _log("  Xtream creds missing")
        return results

    stype = "series" if tmdb_type == "tv" else "movie"
    _log(f"  Searching Xtream {stype} catalog for: {title} tmdb_id={tmdb_id}")

    try:
        streams = _get_cached_xtream_streams(url, user, pwd, stype)
    except Exception as e:
        _log(f"  Xtream {stype} fetch error: {e}")
        return results

    _log(f"  Xtream {stype} catalog: {len(streams)} items")

    # Build category ID → name map for folder display
    cat_map = {}
    try:
        cats = _get_cached_xtream_categories(url, user, pwd, stype)
        for c in cats or []:
            cat_map[str(c.get("category_id", ""))] = c.get("category_name", "")
    except Exception:
        pass

    # --- TMDB ID fast path ---
    if tmdb_id:
        _log(f"  Trying TMDB ID match: {tmdb_id}")
        for s in streams:
            sid = str(s.get("stream_id") or s.get("series_id") or "")
            # 1) Check stream list item itself
            stream_tmdb = str(s.get("tmdb_id") or s.get("tmdb") or "")
            # 2) Check cached vod_info / series_info
            if not stream_tmdb and sid:
                cname = f"vod_info_{sid}" if stype == "movie" else f"series_info_{sid}"
                cached = _cache_load(cname)
                if cached:
                    stream_tmdb = str(cached.get("info", {}).get("tmdb_id") or cached.get("info", {}).get("tmdb") or "")
            if stream_tmdb and stream_tmdb == str(tmdb_id):
                _log(f"  TMDB ID direct match: {s.get('name')} (id={sid})")
                if tmdb_type == "tv" and season and episode:
                    # Need to resolve season/episode even on TMDB match
                    info = IPTV.get_xtream_series_info(url, user, pwd, s.get("series_id", ""))
                    eps = info.get("episodes", {}).get(str(season), [])
                    if not eps and str(season).isdigit():
                        eps = info.get("episodes", {}).get(int(season), [])
                    for ep in eps:
                        if str(ep.get("episode_num", "")) == str(episode):
                            ep_title = ep.get("title", f"S{season}E{episode}")
                            stream_url = IPTV.build_xtream_stream_url(url, user, pwd, ep, "series")
                            series_info = info.get("info", {})
                            icon = (s.get("stream_icon", "")
                                    or series_info.get("cover", "")
                                    or series_info.get("movie_image", "")
                                    or series_info.get("stream_icon", ""))
                            results.append({
                                "name": f"{s.get('name', '')} - {ep_title}",
                                "stream_id": str(ep.get("id", "")),
                                "series_id": str(s.get("series_id", "")),
                                "season_num": str(season),
                                "ep_id": str(ep.get("id", "")),
                                "extension": ep.get("container_extension", ""),
                                "url": stream_url,
                                "score": 100,
                                "quality": _extract_quality(
                                    f"{s.get('name', '')} {ep_title} {cat_map.get(str(s.get('category_id', '')), '')}"
                                ),
                                "source": "xtream",
                                "icon": icon,
                                "category": cat_map.get(str(s.get("category_id", "")), ""),
                                "tmdb_id": str(tmdb_id),
                                "exact_tmdb_match": True,
                            })
                            return results
                else:
                    stream_url = IPTV.build_xtream_stream_url(url, user, pwd, s, "movie")
                    results.append({
                        "name": s.get("name", ""),
                        "stream_id": sid,
                        "extension": s.get("container_extension", ""),
                        "url": stream_url,
                        "score": 100,
                        "quality": _extract_quality(
                            f"{s.get('name', '')} {cat_map.get(str(s.get('category_id', '')), '')}"
                        ),
                        "source": "xtream",
                        "icon": s.get("stream_icon", ""),
                        "category": cat_map.get(str(s.get("category_id", "")), ""),
                        "tmdb_id": str(tmdb_id),
                        "exact_tmdb_match": True,
                    })
                    return results
        _log("  No TMDB ID match in catalog")

    search_words = _filter_stop_words(set(_normalize_title(title).split()))

    if tmdb_type == "tv" and season and episode:
        # Find matching series, then resolve season/episode
        matched_series = []
        for s in streams:
            name = s.get("name", "")
            name_words = _filter_stop_words(set(_normalize_title(name).split()))
            if search_words and not (search_words & name_words):
                continue
            score = _title_match_score(title, name)
            if score < 50:
                continue
            if year and str(year) in name:
                score += 10
            if year:
                found_years = re.findall(r"\b(19\d{2}|20\d{2})\b", name)
                if found_years and str(year) not in found_years:
                    continue
            if year and not re.findall(r"\b(19\d{2}|20\d{2})\b", name):
                score -= 15
            matched_series.append((score, s))
        matched_series.sort(key=lambda x: -x[0])
        _log(f"  Series title matches (score>=50): {len(matched_series)}")
        for score, s in matched_series[:3]:  # Try top 3 matches
            series_id = s.get("series_id", "")
            if not series_id:
                continue
            _log(f"  Trying series '{s.get('name')}' (id={series_id}, score={score})")
            try:
                info = IPTV.get_xtream_series_info(url, user, pwd, series_id)
            except Exception as e:
                _log(f"  Series info error: {e}")
                continue
            eps = info.get("episodes", {})
            season_key = str(season)
            if season_key not in eps:
                season_key = int(season) if season.isdigit() else season
            season_eps = eps.get(season_key, [])
            if not season_eps:
                _log(f"  Season {season} not found in series")
                continue
            _log(f"  Season {season}: {len(season_eps)} episodes")
            for ep in season_eps:
                ep_num = str(ep.get("episode_num", ""))
                if ep_num == str(episode):
                    ep_title = ep.get("title", f"S{season}E{episode}")
                    stream_url = IPTV.build_xtream_stream_url(url, user, pwd, ep, "series")
                    series_info = info.get("info", {})
                    icon = (s.get("stream_icon", "")
                            or series_info.get("cover", "")
                            or series_info.get("movie_image", "")
                            or series_info.get("stream_icon", ""))
                    results.append({
                        "name": f"{s.get('name', '')} - {ep_title}",
                        "stream_id": str(ep.get("id", "")),
                        "series_id": str(series_id),
                        "season_num": str(season),
                        "ep_id": str(ep.get("id", "")),
                        "extension": ep.get("container_extension", ""),
                        "url": stream_url,
                        "score": score + 20,
                        "quality": _extract_quality(
                            f"{s.get('name', '')} {ep_title} {cat_map.get(str(s.get('category_id', '')), '')}"
                        ),
                        "source": "xtream",
                        "icon": icon,
                        "category": cat_map.get(str(s.get("category_id", "")), ""),
                    })
                    _log(f"  Found episode: {ep_title}")
                    return results  # Exact match found
            _log(f"  Episode {episode} not found in season {season}")
    else:
        # Movie search
        for s in streams:
            name = s.get("name", "")
            name_words = _filter_stop_words(set(_normalize_title(name).split()))
            if search_words and not (search_words & name_words):
                continue
            score = _title_match_score(title, name)
            if score < 50:
                continue
            if year and str(year) in name:
                score += 10
            if year:
                found_years = re.findall(r"\b(19\d{2}|20\d{2})\b", name)
                if found_years and str(year) not in found_years:
                    continue
            if year and not re.findall(r"\b(19\d{2}|20\d{2})\b", name):
                score -= 15
            stream_id = str(s.get("stream_id", ""))
            ext = s.get("container_extension", "")
            stream_url = IPTV.build_xtream_stream_url(url, user, pwd, s, "movie")
            results.append({
                "name": name,
                "stream_id": stream_id,
                "extension": ext,
                "url": stream_url,
                "score": score,
                "quality": _extract_quality(
                    f"{name} {cat_map.get(str(s.get('category_id', '')), '')}"
                ),
                "source": "xtream",
                "icon": s.get("stream_icon", ""),
                "category": cat_map.get(str(s.get("category_id", "")), ""),
            })
            _log(f"  Movie match: {name} (score={score})")
        return results


def _search_live_channels(creds, title, year=None):
    """Search live channels as fallback. Returns list of dicts."""
    results = []
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    if not url or not user or not pwd:
        return results
    try:
        channels = _get_cached_xtream_streams(url, user, pwd, "live")
    except Exception as e:
        _log(f"  Live channel search error: {e}")
        return results
    _log(f"  Live catalog: {len(channels)} items")
    cat_map = {}
    try:
        cats = _get_cached_xtream_categories(url, user, pwd, "live")
        for c in cats or []:
            cat_map[str(c.get("category_id", ""))] = c.get("category_name", "")
    except Exception:
        pass
    search_words = set(_normalize_title(title).split())
    for ch in channels:
        name = ch.get("name", "")
        if not (search_words & set(_normalize_title(name).split())):
            continue
        score = _title_match_score(title, name)
        if score < 40:
            continue
        if year and str(year) in name:
            score += 10
        if year:
            found_years = re.findall(r"\b(19\d{2}|20\d{2})\b", name)
            if found_years and str(year) not in found_years:
                continue
        if year and not re.findall(r"\b(19\d{2}|20\d{2})\b", name):
            score -= 15
        stream_url = IPTV.build_xtream_stream_url(url, user, pwd, ch, "live")
        results.append({
            "name": f"[Live] {name}",
            "stream_id": str(ch.get("stream_id", "")),
            "extension": "",
            "url": stream_url,
            "score": score,
            "quality": _extract_quality(
                f"{name} {cat_map.get(str(ch.get('category_id', '')), '')}"
            ),
            "source": "xtream_live",
            "category": cat_map.get(str(ch.get("category_id", "")), ""),
        })
        _log(f"  Live match: {name} (score={score})")
    return results


def _search_m3u_vod(creds, title, year=None):
    """Search M3U entries for title match (no-creds M3U). Returns list of dicts."""
    results = []
    m3u_url = creds.get("m3u_url", "")
    if not m3u_url:
        return results
    _log("  Searching M3U: {0}".format(_safe_url_for_log(m3u_url)))
    try:
        channels = _get_cached_m3u_channels(m3u_url)
    except Exception as e:
        _log(f"  M3U search error for {title}: {e}")
        return results
    _log(f"  M3U items: {len(channels)}")
    for ch in channels:
        name = ch.get("name", "")
        score = _title_match_score(title, name)
        if score < 30:
            continue
        if year:
            found_years = re.findall(r"\b(19\d{2}|20\d{2})\b", name)
            if found_years and str(year) not in found_years:
                continue
            if found_years and str(year) in found_years:
                score += 10
        if year and not re.findall(r"\b(19\d{2}|20\d{2})\b", name):
            score -= 15
        results.append({
            "name": name,
            "stream_id": ch.get("tvg_id", ""),
            "extension": "",
            "url": ch.get("url", ""),
            "score": score,
            "quality": _extract_quality(f"{name} {ch.get('group', '')}"),
            "source": "m3u",
            "category": ch.get("group", ""),
        })
        _log(f"  M3U match: {name} (score={score})")
    return results


def _season_eps_from_info(info, season):
    eps_map = info.get("episodes", {})
    season_key = str(season)
    eps = eps_map.get(season_key, [])
    if not eps and season_key.isdigit():
        eps = eps_map.get(int(season_key), [])
    return eps or []


def _all_eps_from_info(info):
    eps_map = info.get("episodes", {})
    out = []
    for season_key in sorted(eps_map.keys(), key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x))):
        for ep in eps_map.get(season_key, []) or []:
            out.append((season_key, ep))
    return out


def _find_xtream_series_sources(showname, year="", season=""):
    out = []
    for n in range(1, 11):
        if addon.getSetting(f"profile_{n}_enabled") != "true":
            continue
        if not addon.getSetting(f"profile_{n}_xtream_url"):
            continue
        creds = _get_credentials_for_profile(n)
        pname = creds.get("name") or addon.getSetting(f"profile_{n}_name") or _t(30390, n)
        url = creds.get("xtream_url", "")
        user = creds.get("xtream_username", "")
        pwd = creds.get("xtream_password", "")
        streams = _call_with_active_profile(
            n,
            _get_cached_xtream_streams,
            url,
            user,
            pwd,
            "series",
        )
        matches = []
        for s in streams:
            name = s.get("name", "")
            score = _title_match_score(showname, name)
            if score < 50:
                continue
            if year and str(year) in name:
                score += 10
            matches.append((score, s))
        matches.sort(key=lambda x: -x[0])
        for score, series in matches[:3]:
            info = IPTV.get_xtream_series_info(url, user, pwd, series.get("series_id", ""))
            items = _season_eps_from_info(info, season) if season else [ep for _, ep in _all_eps_from_info(info)]
            if items:
                out.append((n, pname, creds, series, info, score, len(items)))
    out.sort(key=lambda x: (-x[5], x[0]))
    return out


def _search_all_profiles_vod(title, year=None, tmdb_type="movie", season="", episode="", tmdb_id="", progress=None):
    """Search all enabled profiles for VOD matches. Returns list of (profile_num, profile_name, result_dict)."""
    all_results = []
    original_active = pm.active
    enabled_profiles = []
    for n in range(1, 11):
        if addon.getSetting(f"profile_{n}_enabled") == "true":
            enabled_profiles.append(n)
    cache_key = _source_result_cache_key(title, year, tmdb_type, season, episode, tmdb_id, enabled_profiles)
    cached = _source_cache_load("results", cache_key, SOURCE_RESULT_CACHE_TTL_SECONDS)
    if cached and isinstance(cached.get("results"), list):
        cached_results = []
        for row in cached.get("results", []):
            if isinstance(row, list) and len(row) == 3:
                try:
                    cached_results.append((int(row[0]), row[1], row[2]))
                except Exception:
                    pass
        _log("Source result cache hit: {0} results".format(len(cached_results)))
        _source_progress_update(progress, "Using Cached Sources", len(cached_results), 20)
        cached_results = _prepare_source_results(cached_results, progress=progress)
        _log(f"Overall results: {len(cached_results)}")
        return cached_results
    _log(f"Searching all profiles: title='{title}' year='{year}' type={tmdb_type} S{season}E{episode} tmdb_id={tmdb_id}")
    try:
        total_profiles = max(1, len(enabled_profiles))
        for idx, n in enumerate(enabled_profiles, 1):
            if _source_progress_update(
                progress,
                "Scanning Profiles",
                len(all_results),
                int(((idx - 1) / float(total_profiles)) * 45),
            ):
                _log("Source scan cancelled by user")
                return []
            pm.active = str(n)
            creds = _get_credentials_for_profile(n)
            profile_name = creds.get("name", f"Profile {n}")
            _log(f"Profile {n} ({profile_name}):")
            try:
                matches = []
                if creds.get("xtream_url"):
                    matches = _search_xtream_vod(creds, title, year, tmdb_type, season, episode, tmdb_id)
                    if not matches and tmdb_type == "movie":
                        live = _search_live_channels(creds, title, year)
                        matches.extend(live)
                elif creds.get("m3u_url"):
                    matches = _search_m3u_vod(creds, title, year=year)
                else:
                    _log("  No credentials configured")
                _log(f"  Total matches: {len(matches)}")
                for m in matches:
                    all_results.append((n, profile_name, m))
                _source_progress_update(
                    progress,
                    "Scanning Profiles",
                    len(all_results),
                    int((idx / float(total_profiles)) * 45),
                )
            except Exception as e:
                _log(f"Profile {n} VOD search error: {e}")
    finally:
        pm.active = original_active
    _source_cache_save("results", cache_key, {
        "version": SOURCE_RESULT_CACHE_VERSION,
        "saved_at": time.time(),
        "results": [[pnum, pname, r] for pnum, pname, r in all_results],
    })
    all_results = _prepare_source_results(all_results, progress=progress)
    _log(f"Overall results: {len(all_results)}")
    return all_results


def _tmdb_return_url(tmdb_type):
    mode_name = "xstream_tmdb_tvshows_menu" if tmdb_type == "tv" else "xstream_tmdb_movies_menu"
    return build_url({"mode": mode_name})


def _return_to_xstream_tmdb_menu(tmdb_type):
    try:
        xbmc.executebuiltin(
            "Container.Update({0},replace)".format(_tmdb_return_url(tmdb_type))
        )
    except Exception as e:
        _log(f"TMDB return navigation warning: {e}")


def _select_source_result(results):
    labels = [_source_result_label(pname, r) for _pnum, pname, r in results]
    xbmc.sleep(_tvos_sleep(300))
    idx = xbmcgui.Dialog().select(_t(31065), labels)
    if idx < 0:
        return None
    return results[idx]


def _source_progress_update(progress, heading, found_count=0, percent=0):
    if not progress:
        return False
    try:
        if progress.iscanceled():
            return True
        message = "{0} - Results Found: {1}".format(heading, found_count)
        progress.update(max(0, min(100, int(percent or 0))), message)
    except Exception:
        pass
    return False


def _source_progress_close(progress):
    if not progress:
        return
    try:
        progress.close()
    except Exception:
        pass


def _source_auto_play_first_enabled():
    return _get_setting_fast("source_auto_play_first", "true").lower() == "true"


def _source_result_exact_tmdb_match(result, tmdb_id):
    if not tmdb_id:
        return False
    if result.get("exact_tmdb_match"):
        return True
    return str(result.get("tmdb_id") or "").strip() == str(tmdb_id).strip()


def _pick_autoplay_source(results, tmdb_id):
    """Pick a safe autoplay source."""
    if not results:
        return None, "empty"
    if tmdb_id:
        exact = [row for row in results if _source_result_exact_tmdb_match(row[2], tmdb_id)]
        if exact:
            return exact[0], "exact_tmdb"
        return None, "weak_match"
    strong = []
    for row in results:
        try:
            score = int(row[2].get("score") or 0)
        except Exception:
            score = 0
        if score >= 80:
            strong.append(row)
    if strong:
        return strong[0], "strong_title"
    return None, "weak_match"


def _source_result_play_url(pnum, r, title, tmdb_type, tmdb_id):
    stype = "series" if tmdb_type == "tv" else "movie"
    icon = r.get("icon", "") or _local_icon("providers")
    q = {
        "mode": "play_stream",
        "url": r.get("url", ""),
        "name": r["name"],
        "title": title,
        "icon": icon,
        "stype": stype,
        "profile_num": pnum,
        "tmdb_id": tmdb_id,
    }
    if stype == "series":
        q["series_id"] = r.get("series_id", "")
        q["season_num"] = r.get("season_num", "")
        q["ep_id"] = r.get("ep_id") or r.get("stream_id", "")
    return build_url(q)


def _play_source_result(selected, title, tmdb_type, tmdb_id):
    pnum, pname, r = selected
    _log(f"Playing source: {r.get('name', '')} ({pname})")
    play_url = _source_result_play_url(pnum, r, title, tmdb_type, tmdb_id)
    xbmc.executebuiltin("PlayMedia({0})".format(play_url))
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)


def tmdb_source_action():
    item_title = args.get("title", [""])[0]
    showname = args.get("showname", [""])[0]
    tmdb_type = _normalize_tmdb_type(args.get("tmdb_type", ["movie"])[0]) or "movie"
    title = showname if tmdb_type == "tv" and showname else item_title
    year = args.get("year", [""])[0]
    tmdb_id = args.get("tmdb_id", [""])[0]
    season = args.get("season", [""])[0]
    episode = args.get("episode", [""])[0]
    intent = args.get("intent", ["play"])[0]
    if tmdb_id == "_":
        tmdb_id = ""
    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", "Scanning Profiles - Results Found: 0")
    try:
        results = _search_all_profiles_vod(title, year, tmdb_type, season, episode, tmdb_id, progress=progress)
    finally:
        _source_progress_close(progress)
    if not results:
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        return
    selected = _select_source_result(results)
    if not selected:
        return
    pnum, pname, r = selected
    if intent == "download":
        icon = r.get("icon", "") or _local_icon("providers")
        if _get_downloader_module().start_download(
            r["url"],
            title if tmdb_type == "tv" else r["name"],
            year=year,
            media_type="episode" if tmdb_type == "tv" else "movie",
            season=season,
            episode=episode,
            poster=icon,
            profile_num=pnum,
        ):
            xbmcgui.Dialog().notification("Xstream Pro", _t(30942))
        else:
            xbmcgui.Dialog().notification("Xstream Pro", _t(30949))
        return
    _play_source_result(selected, title, tmdb_type, tmdb_id)


def source_select():
    item_title = args.get("title", [""])[0]
    showname = args.get("showname", [""])[0]
    title = showname if args.get("tmdb_type", ["movie"])[0] == "tv" and showname else item_title
    year = args.get("year", [""])[0]
    tmdb_type = _normalize_tmdb_type(args.get("tmdb_type", ["movie"])[0]) or "movie"
    tmdb_id = args.get("tmdb_id", [""])[0]
    season = args.get("season", [""])[0]
    episode = args.get("episode", [""])[0]
    intent = args.get("intent", ["browse"])[0]
    if tmdb_id == "_":
        tmdb_id = ""
    if not title:
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
        return
    _set_tmdb_content(tmdb_type, season, episode)
    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", "Scanning Profiles - Results Found: 0")
    xbmc.sleep(150)
    try:
        results = _search_all_profiles_vod(title, year, tmdb_type, season, episode, tmdb_id, progress=progress)
    finally:
        _source_progress_close(progress)
    if not results:
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        li = _new_listitem(_t(31064))
        xbmcplugin.addDirectoryItems(addon_handle, [("", li, False)])
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
        _log_route_timing("source_select_empty")
        return
    if intent == "play" and _source_auto_play_first_enabled():
        selected, reason = _pick_autoplay_source(results, tmdb_id)
        if selected:
            pnum, pname, r = selected
            stype = "series" if tmdb_type == "tv" else "movie"
            _log(
                "Auto-playing source ({0}): {1} ({2}), score={3}".format(
                    reason,
                    r.get("name", ""),
                    pname,
                    r.get("score", ""),
                )
            )
            play_stream(
                r["url"],
                r["name"],
                title=title,
                icon=r.get("icon", "") or _local_icon("providers"),
                stype=stype,
                series_id=r.get("series_id", ""),
                season_num=r.get("season_num", ""),
                ep_id=r.get("ep_id") or r.get("stream_id", ""),
                profile_num=pnum,
                tmdb_id=tmdb_id,
            )
            return
        _log("Auto-play skipped: weak source match for tmdb_id={0}; showing source list".format(tmdb_id))
    stype = "series" if tmdb_type == "tv" else "movie"
    directory_items = []
    for pnum, pname, r in results:
        label = _source_result_label(pname, r)
        icon = r.get("icon", "") or _local_icon("providers")
        url = r.get("url", "")
        li = _new_listitem(label)
        art = {"poster": icon, "fanart": ""}
        _set_tmdb_item_info(
            li,
            r["name"],
            icon,
            art,
            tmdb_type,
            year,
            "",
            season,
            episode,
            0,
        )
        li.setProperty("IsPlayable", "true")
        play_url = _source_result_play_url(pnum, r, title, tmdb_type, tmdb_id)
        download_url = build_url({
            "mode": "download",
            "url": url,
            "title": title if tmdb_type == "tv" else r["name"],
            "year": year,
            "stype": stype,
            "tmdb_type": tmdb_type,
            "season": season,
            "episode": episode,
            "profile_num": pnum,
            "poster": icon,
        })
        fav_id = f"source:{pnum}:{r.get('source', '')}:{r.get('stream_id', '')}:{r['name']}"
        ctx = [
            (
                _t(31073),
                "PlayMedia({0})".format(play_url),
            )
        ]
        if is_url_downloadable(url):
            ctx.append((_t(30941), f"RunPlugin({download_url})"))
        ctx.extend(_build_favorite_ctx(
            fav_id,
            r["name"],
            stype,
            icon,
            play_url,
            profile_num=None,
            include_download=False,
        ))
        li.addContextMenuItems(ctx)
        item_url = download_url if intent == "download" else play_url
        directory_items.append((item_url, li, False))
    xbmcplugin.addDirectoryItems(addon_handle, directory_items)
    xbmcplugin.endOfDirectory(addon_handle, succeeded=True, updateListing=False, cacheToDisc=False)
    _log_route_timing("source_select")


def source_autoplay():
    """Resolve the first safe TMDB provider source as a playable Kodi route.

    Unlike source_select(), this route never renders a directory. It either
    calls play_stream() with a selected source or returns a failed playable
    result, which avoids Kodi trying to play a folder route.
    """
    item_title = args.get("title", [""])[0]
    showname = args.get("showname", [""])[0]
    tmdb_type = _normalize_tmdb_type(args.get("tmdb_type", ["movie"])[0]) or "movie"
    title = showname if tmdb_type == "tv" and showname else item_title
    year = args.get("year", [""])[0]
    tmdb_id = args.get("tmdb_id", [""])[0]
    season = args.get("season", [""])[0]
    episode = args.get("episode", [""])[0]
    if tmdb_id == "_":
        tmdb_id = ""
    if not title:
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", "Scanning Profiles - Results Found: 0")
    try:
        results = _search_all_profiles_vod(title, year, tmdb_type, season, episode, tmdb_id, progress=progress)
    finally:
        _source_progress_close(progress)

    selected, reason = _pick_autoplay_source(results, tmdb_id)
    if not selected:
        _log("Auto-play failed: no safe source for tmdb_id={0}, reason={1}".format(tmdb_id, reason))
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    pnum, pname, r = selected
    stype = "series" if tmdb_type == "tv" else "movie"
    _log(
        "Auto-playing source ({0}): {1} ({2}), score={3}".format(
            reason,
            r.get("name", ""),
            pname,
            r.get("score", ""),
        )
    )
    play_stream(
        r["url"],
        r["name"],
        title=title,
        icon=r.get("icon", "") or _local_icon("providers"),
        stype=stype,
        series_id=r.get("series_id", ""),
        season_num=r.get("season_num", ""),
        ep_id=r.get("ep_id") or r.get("stream_id", ""),
        profile_num=pnum,
        tmdb_id=tmdb_id,
    )


def resolve_source():
    """Auto-play fallback for cached play_movie/play_episode configs.

    If TMDB Helper still has an old cached player config using play_movie/
    play_episode, this auto-plays the first source without any dialogs.
    """
    title = args.get("showname", [""])[0] or args.get("title", [""])[0]
    year = args.get("year", [""])[0]
    tmdb_type = _normalize_tmdb_type(args.get("tmdb_type", ["movie"])[0]) or "movie"
    tmdb_id = args.get("tmdb_id", [""])[0]
    season = args.get("season", [""])[0]
    episode = args.get("episode", [""])[0]

    _log(f"Resolve source (auto-play fallback): title={title}, year={year}, type={tmdb_type} tmdb_id={tmdb_id}")

    if not title:
        _return_to_xstream_tmdb_menu(tmdb_type)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    xbmc.sleep(_tvos_sleep(600))
    try:
        results = _search_all_profiles_vod(title, year, tmdb_type, season, episode, tmdb_id)
    finally:
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")

    if not results:
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        _return_to_xstream_tmdb_menu(tmdb_type)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    selected, reason = _pick_autoplay_source(results, tmdb_id)
    if not selected:
        _log("Resolve source skipped: weak source match for tmdb_id={0}".format(tmdb_id))
        _return_to_xstream_tmdb_menu(tmdb_type)
        xbmcplugin.setResolvedUrl(addon_handle, False, _new_listitem())
        return
    pnum, pname, r = selected
    _log("Resolve source selected ({0}): {1} ({2})".format(reason, r.get("name", ""), pname))
    stype = "series" if tmdb_type == "tv" else "movie"
    play_stream(
        r["url"],
        r["name"],
        title=title,
        icon=r.get("icon", "") or _local_icon("providers"),
        stype=stype,
        series_id=r.get("series_id", ""),
        season_num=r.get("season_num", ""),
        ep_id=r.get("ep_id") or r.get("stream_id", ""),
        profile_num=pnum,
    )


def tmdb_series_action():
    showname = args.get("showname", [""])[0] or args.get("title", [""])[0]
    year = args.get("year", [""])[0]
    season = args.get("season", [""])[0]
    intent = args.get("intent", ["play"])[0]
    tmdb_id = args.get("tmdb_id", [""])[0]
    if not showname:
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        return
    sources = _find_xtream_series_sources(showname, year, season)
    if not sources:
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        return
    labels = []
    for pnum, pname, creds, series, info, score, count in sources:
        labels.append(f"{series.get('name', showname)} | {count} episodes | {pname}")
    xbmc.sleep(_tvos_sleep(300))
    idx = xbmcgui.Dialog().select(_t(31065), labels)
    if idx < 0:
        return
    pnum, pname, creds, series, info, score, count = sources[idx]
    if season:
        items = [(season, ep) for ep in _season_eps_from_info(info, season)]
    else:
        items = _all_eps_from_info(info)
    if not items:
        xbmcgui.Dialog().notification("Xstream Pro", _t(31064))
        return
    url = creds.get("xtream_url", "")
    user = creds.get("xtream_username", "")
    pwd = creds.get("xtream_password", "")
    if intent == "download":
        count = 0
        for season_num, ep in items:
            ep_num = ep.get("episode_num", "")
            play_url = IPTV.build_xtream_stream_url(url, user, pwd, ep, "series")
            if not is_url_downloadable(play_url):
                continue
            if _get_downloader_module().start_download(
                play_url,
                showname,
                year=year,
                media_type="episode",
                season=season_num,
                episode=ep_num,
                poster=ep.get("info", {}).get("movie_image", ""),
                plot=ep.get("info", {}).get("plot", ""),
                profile_num=pnum,
            ):
                count += 1
        xbmcgui.Dialog().notification("Xstream Pro", f"{_t(30953)}: {count}")
        return
    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
    playlist.clear()
    for season_num, ep in items:
        ep_id = str(ep.get("id", ""))
        ep_num = ep.get("episode_num", "")
        ep_title = ep.get("title") or _t(30542, ep_num or "?")
        play_url = IPTV.build_xtream_stream_url(url, user, pwd, ep, "series")
        plugin_url = build_url({
            "mode": "play_stream",
            "url": play_url,
            "name": ep_title,
            "title": showname,
            "icon": ep.get("info", {}).get("movie_image", ""),
            "stype": "series",
            "series_id": series.get("series_id", ""),
            "season_num": season_num,
            "ep_id": ep_id,
            "profile_num": pnum,
        })
        li = _new_listitem(ep_title)
        playlist.add(plugin_url, li)
    xbmc.Player().play(playlist)
