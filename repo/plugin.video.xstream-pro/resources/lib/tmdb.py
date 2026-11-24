"""TMDB HTTP API client with JSON cache and result normalization.

Provides paged discovery, search, details, and a lightweight metadata cache
for fast hydration of folder items without blocking network calls.
"""
import json
import os
import time

import requests
import xbmc
import xbmcaddon
import xbmcvfs

import cache


BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
ADDON_ID = "plugin.video.xstream-pro"
BUNDLED_API_KEY = "c41717c1a7425979abbf813933fc9e06"

_SESSION = None


def _addon():
    return xbmcaddon.Addon(ADDON_ID)


def _log(message, level=xbmc.LOGINFO):
    xbmc.log("[Xstream Pro TMDB] {0}".format(str(message)), level)


def _is_tvos():
    if not xbmc.getCondVisibility("System.Platform.OSX"):
        return False
    profile = xbmcvfs.translatePath(_addon().getAddonInfo("profile"))
    return "Containers" in profile or "Library/Caches/Kodi" in profile


def _safe_fsync(fh):
    if _is_tvos():
        return
    try:
        os.fsync(fh.fileno())
    except OSError:
        pass


def _session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=50)
        _SESSION.mount("https://", adapter)
    return _SESSION


def api_key():
    return (_addon().getSetting("tmdb_api_key") or "").strip() or BUNDLED_API_KEY


def language():
    return (_addon().getSetting("tmdb_language") or "en-US").strip() or "en-US"


def region():
    return (_addon().getSetting("tmdb_region") or "US").strip() or "US"


def include_adult():
    return _addon().getSetting("tmdb_include_adult").lower() == "true"


def cache_hours():
    try:
        return max(1, int(_addon().getSetting("tmdb_cache_hours") or "12"))
    except Exception:
        return 12


def image_size():
    return _addon().getSetting("tmdb_image_size") or "w500"


def fanart_size():
    return _addon().getSetting("tmdb_fanart_size") or "w1280"


def _profile_dir():
    profile = xbmcvfs.translatePath(_addon().getAddonInfo("profile"))
    cache_dir = os.path.join(profile, "tmdb_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def meta_cache_get(tmdb_type, tmdb_id):
    return cache.meta_get(normalize_media_type(tmdb_type), tmdb_id)


def meta_cache_get_many(pairs):
    normalized = []
    for media_type, tmdb_id in pairs or []:
        tmdb_id = str(tmdb_id or "")
        if tmdb_id:
            normalized.append((normalize_media_type(media_type), tmdb_id))
    return cache.meta_get_many(normalized)


def meta_cache_set(tmdb_type, tmdb_id, data):
    cache.meta_set(normalize_media_type(tmdb_type), tmdb_id, data, ttl_seconds=604800)


def _tmdb_names(items):
    return [item.get("name") for item in (items or []) if item.get("name")]


def _runtime_seconds(payload, media_type):
    raw = payload.get("runtime")
    if not raw and media_type == "tv":
        values = payload.get("episode_run_time") or []
        raw = values[0] if values else 0
    try:
        minutes = int(raw or 0)
    except (TypeError, ValueError):
        minutes = 0
    return minutes * 60 if minutes > 0 else 0


def _certification(payload, media_type):
    wanted_region = region().upper()
    if media_type == "tv":
        for row in (payload.get("content_ratings") or {}).get("results", []) or []:
            if (row.get("iso_3166_1") or "").upper() == wanted_region and row.get("rating"):
                return row.get("rating")
        return ""
    for row in (payload.get("release_dates") or {}).get("results", []) or []:
        if (row.get("iso_3166_1") or "").upper() != wanted_region:
            continue
        for release in row.get("release_dates", []) or []:
            if release.get("certification"):
                return release.get("certification")
    return ""


def meta_summary(media_type, tmdb_id):
    media = normalize_media_type(media_type)
    payload = details(media, tmdb_id)
    credits = payload.get("credits") or {}
    crew = credits.get("crew") or []
    directors = [
        item.get("name")
        for item in crew
        if item.get("name") and item.get("job") == "Director"
    ]
    writers = [
        item.get("name")
        for item in crew
        if item.get("name") and item.get("job") in ("Writer", "Screenplay", "Teleplay")
    ]
    studios = _tmdb_names(payload.get("production_companies"))
    return {
        "schema": 2,
        "poster": image_url(payload.get("poster_path")),
        "fanart": fanart_url(payload.get("backdrop_path")),
        "plot": payload.get("overview") or "",
        "rating": payload.get("vote_average") or "",
        "votes": payload.get("vote_count") or "",
        "premiered": payload.get("release_date") or payload.get("first_air_date") or "",
        "title": payload.get("title") or payload.get("name") or "",
        "year": item_year(payload),
        "runtime": _runtime_seconds(payload, media),
        "cast": [
            {
                "name": item.get("name") or "",
                "role": item.get("character") or "",
                "thumbnail": image_url(item.get("profile_path")),
            }
            for item in (credits.get("cast") or [])[:10]
            if item.get("name")
        ],
        "genre": _tmdb_names(payload.get("genres")),
        "director": directors,
        "writer": writers,
        "studio": studios,
        "mpaa": _certification(payload, media),
        "tagline": payload.get("tagline") or "",
    }


def meta_summary_cached(media_type, tmdb_id):
    cached = meta_cache_get(media_type, tmdb_id)
    if cached and int(cached.get("schema") or 1) >= 2:
        return cached
    data = meta_summary(media_type, tmdb_id)
    meta_cache_set(media_type, tmdb_id, data)
    return data




def search_person(query, page=1):
    payload = _request("/search/person", {"query": query, "page": page}, ttl=1)
    data = normalize_people_page(payload, page=page, hydrate_names=True, require_profile=False)
    return {
        "page": data["page"],
        "total_pages": data["total_pages"],
        "results": [{"id": item["id"], "name": item["name"]} for item in data["results"]],
    }


def search_networks(query, page=1):
    payload = _request("/search/company", {"query": query, "page": page}, ttl=1)
    results = []
    for item in payload.get("results", []) or []:
        results.append({
            "id": str(item.get("id") or ""),
            "name": item.get("name") or "Unknown",
        })
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": results,
    }


def certifications(media_type):
    path = "/certification/movie/list" if media_type == "movie" else "/certification/tv/list"
    payload = _request(path, {}, ttl=168)
    certs = {}
    for country, items in (payload.get("certifications") or {}).items():
        certs[country] = [c.get("certification") or "" for c in items]
    return certs


_COMMON_REGIONS = [
    ("US", "United States"),
    ("GB", "United Kingdom"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("DE", "Germany"),
    ("FR", "France"),
    ("ES", "Spain"),
    ("IT", "Italy"),
    ("NL", "Netherlands"),
    ("BR", "Brazil"),
    ("MX", "Mexico"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("IN", "India"),
    ("RU", "Russia"),
    ("TR", "Turkey"),
    ("PL", "Poland"),
    ("SE", "Sweden"),
    ("NO", "Norway"),
    ("DK", "Denmark"),
    ("FI", "Finland"),
    ("BE", "Belgium"),
    ("AT", "Austria"),
    ("CH", "Switzerland"),
    ("IE", "Ireland"),
    ("NZ", "New Zealand"),
    ("ZA", "South Africa"),
    ("AR", "Argentina"),
    ("CL", "Chile"),
    ("CO", "Colombia"),
    ("HU", "Hungary"),
    ("CZ", "Czech Republic"),
    ("RO", "Romania"),
    ("BG", "Bulgaria"),
    ("HR", "Croatia"),
    ("SI", "Slovenia"),
    ("SK", "Slovakia"),
    ("LT", "Lithuania"),
    ("LV", "Latvia"),
    ("EE", "Estonia"),
    ("UA", "Ukraine"),
    ("GR", "Greece"),
    ("PT", "Portugal"),
    ("IS", "Iceland"),
    ("IL", "Israel"),
    ("AE", "United Arab Emirates"),
    ("SA", "Saudi Arabia"),
    ("EG", "Egypt"),
    ("TH", "Thailand"),
    ("ID", "Indonesia"),
    ("MY", "Malaysia"),
    ("PH", "Philippines"),
    ("SG", "Singapore"),
    ("VN", "Vietnam"),
    ("TW", "Taiwan"),
    ("HK", "Hong Kong"),
    ("CN", "China"),
]


_COMMON_LANGUAGES = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("hi", "Hindi"),
    ("ar", "Arabic"),
    ("tr", "Turkish"),
    ("pl", "Polish"),
    ("nl", "Dutch"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("no", "Norwegian"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("hu", "Hungarian"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("th", "Thai"),
    ("id", "Indonesian"),
    ("vi", "Vietnamese"),
]


def _request(path, params=None, ttl=None):
    key = api_key()
    if not key:
        raise RuntimeError("TMDB API key is not configured")
    query = dict(params or {})
    query.setdefault("api_key", key)
    query.setdefault("language", language())
    query.setdefault("region", region())
    query.setdefault("include_adult", "true" if include_adult() else "false")
    cache_key = cache.make_key(path, sorted(query.items()))
    cached = cache.get("tmdb_http", cache_key)
    if cached is not None:
        return cached
    safe_query = dict(query)
    safe_query.pop("api_key", None)
    _log("TMDB request: {0} | params: {1}".format(BASE_URL + path, safe_query), xbmc.LOGDEBUG)
    try:
        response = _session().get(BASE_URL + path, params=query, timeout=15)
    except requests.exceptions.Timeout:
        raise RuntimeError("TMDB request timed out")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("TMDB request failed: {0}".format(exc.__class__.__name__))
    if response.status_code >= 400:
        message = ""
        try:
            message = response.json().get("status_message") or ""
        except Exception:
            pass
        detail = ": {0}".format(message) if message else ""
        raise RuntimeError("TMDB request failed ({0}){1}".format(response.status_code, detail))
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("TMDB returned invalid JSON")
    cache.set("tmdb_http", cache_key, payload, int((ttl or cache_hours()) * 3600))
    return payload


def image_url(path, size=None):
    if not path:
        return ""
    if str(path).startswith("http"):
        return str(path)
    return "{0}/{1}{2}".format(IMAGE_BASE, size or image_size(), path)


def fanart_url(path):
    return image_url(path, fanart_size())


def item_year(item):
    date = item.get("release_date") or item.get("first_air_date") or item.get("air_date") or ""
    return str(date)[:4] if date else ""


def normalize_media_type(media_type, item=None):
    media = media_type or ""
    if not media and item:
        media = item.get("media_type") or ("tv" if item.get("name") else "movie")
    if media in ("tv", "show", "tvshow"):
        return "tv"
    return "movie"


def normalize_item(item, media_type=None):
    media = normalize_media_type(media_type, item)
    title = item.get("title") or item.get("name") or item.get("original_title") or item.get("original_name") or "Unknown"
    return {
        "tmdb_id": str(item.get("id") or ""),
        "tmdb_type": media,
        "title": title,
        "year": item_year(item),
        "plot": item.get("overview") or "",
        "poster": image_url(item.get("poster_path")),
        "fanart": fanart_url(item.get("backdrop_path")),
        "rating": item.get("vote_average") or "",
        "votes": item.get("vote_count") or "",
        "premiered": item.get("release_date") or item.get("first_air_date") or item.get("air_date") or "",
        "raw": item,
    }


def normalize_results(payload, media_type=None):
    return [normalize_item(item, media_type) for item in payload.get("results", []) if item.get("id")]


def paged(path, media_type=None, page=1, params=None, ttl=None):
    query = dict(params or {})
    query["page"] = page
    payload = _request(path, query, ttl=ttl)
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": normalize_results(payload, media_type),
        "raw": payload,
    }


def movie_list(list_name, page=1):
    mapping = {
        "popular": "/movie/popular",
        "top_rated": "/movie/top_rated",
        "now_playing": "/movie/now_playing",
        "upcoming": "/movie/upcoming",
        "trending_day": "/trending/movie/day",
        "trending_week": "/trending/movie/week",
    }
    if list_name == "revenue":
        return discover("movie", {"sort_by": "revenue.desc"}, page=page)
    if list_name == "most_voted":
        return discover("movie", {"sort_by": "vote_count.desc", "vote_count.gte": 100}, page=page)
    return paged(mapping.get(list_name, "/movie/popular"), "movie", page=page)


def tv_list(list_name, page=1):
    mapping = {
        "popular": "/tv/popular",
        "top_rated": "/tv/top_rated",
        "airing_today": "/tv/airing_today",
        "on_the_air": "/tv/on_the_air",
        "trending_day": "/trending/tv/day",
        "trending_week": "/trending/tv/week",
    }
    if list_name == "most_voted":
        return discover("tv", {"sort_by": "vote_count.desc", "vote_count.gte": 100}, page=page)
    return paged(mapping.get(list_name, "/tv/popular"), "tv", page=page)


def discover(media_type, params=None, page=1):
    media = normalize_media_type(media_type)
    return paged("/discover/{0}".format(media), media, page=page, params=params or {})


def _today():
    return time.strftime("%Y-%m-%d")


def _mostly_non_latin(value):
    text = str(value or "").strip()
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = [ch for ch in letters if ch.isascii()]
    return float(len(latin)) / float(len(letters)) < 0.5


def _english_title_candidate(value):
    text = str(value or "").strip()
    if not text or _mostly_non_latin(text):
        return ""
    return text


def english_title(media_type, tmdb_id):
    media = normalize_media_type(media_type)
    tmdb_id = str(tmdb_id or "")
    if not tmdb_id:
        return ""
    cache_key = cache.make_key("english_title_v2", media, tmdb_id)
    cached = cache.get("tmdb_titles", cache_key)
    if cached is not None:
        return cached.get("title") or ""
    title = ""
    payload = _request("/{0}/{1}/translations".format(media, tmdb_id), {}, ttl=168)
    for entry in payload.get("translations", []) or []:
        if entry.get("iso_639_1") != "en":
            continue
        data = entry.get("data") or {}
        title = _english_title_candidate(data.get("title") or data.get("name") or "")
        if title:
            break
    if not title:
        payload = _request("/{0}/{1}/alternative_titles".format(media, tmdb_id), {}, ttl=168)
        entries = payload.get("titles") or payload.get("results") or []
        preferred = []
        fallback = []
        for entry in entries:
            candidate = _english_title_candidate(entry.get("title") or entry.get("name") or "")
            if not candidate:
                continue
            country = (entry.get("iso_3166_1") or "").upper()
            if country in ("US", "GB", "CA", "AU"):
                preferred.append(candidate)
            else:
                fallback.append(candidate)
        if preferred:
            title = preferred[0]
        elif fallback:
            title = fallback[0]
    cache.set("tmdb_titles", cache_key, {"title": title}, 604800)
    return title


def _apply_english_titles(results):
    for item in results or []:
        if item.get("season") or item.get("episode"):
            continue
        if not _mostly_non_latin(item.get("title")):
            continue
        try:
            title = english_title(item.get("tmdb_type"), item.get("tmdb_id"))
            if title:
                item["title"] = title
        except Exception:
            pass
    return results


def apply_english_titles(results):
    return _apply_english_titles(results)


def search(media_type, query, page=1):
    media = normalize_media_type(media_type)
    return paged("/search/{0}".format(media), media, page=page, params={"query": query}, ttl=1)


def search_collections(query, page=1):
    payload = _request("/search/collection", {"query": query, "page": page}, ttl=1)
    results = []
    for item in payload.get("results", []) or []:
        results.append({
            "collection_id": str(item.get("id") or ""),
            "tmdb_id": str(item.get("id") or ""),
            "title": item.get("name") or "Unknown Collection",
            "plot": item.get("overview") or "",
            "poster": image_url(item.get("poster_path")),
            "fanart": fanart_url(item.get("backdrop_path")),
            "raw": item,
        })
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": results,
        "raw": payload,
    }


def search_companies(query, page=1):
    payload = _request("/search/company", {"query": query, "page": page}, ttl=1)
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": payload.get("results", []) or [],
        "raw": payload,
    }


def search_keywords(query, page=1):
    payload = _request("/search/keyword", {"query": query, "page": page}, ttl=1)
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": payload.get("results", []) or [],
        "raw": payload,
    }


def multi_search(query, page=1):
    payload = _request("/search/multi", {"query": query, "page": page}, ttl=1)
    results = []
    for item in payload.get("results", []):
        media = item.get("media_type")
        if media in ("movie", "tv"):
            results.append(normalize_item(item, media))
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": results,
        "raw": payload,
    }


def genres(media_type):
    media = normalize_media_type(media_type)
    return _request("/genre/{0}/list".format(media), {}, ttl=168).get("genres", [])


def watch_providers(media_type):
    media = normalize_media_type(media_type)
    payload = _request("/watch/providers/{0}".format(media), {}, ttl=168)
    return payload.get("results", []) or []


def details(media_type, tmdb_id):
    media = normalize_media_type(media_type)
    params = {
        "append_to_response": "external_ids,videos,credits,keywords,release_dates,content_ratings",
        "include_image_language": "en,null",
    }
    return _request("/{0}/{1}".format(media, tmdb_id), params, ttl=168)


def videos(media_type, tmdb_id):
    media = normalize_media_type(media_type)
    payload = _request("/{0}/{1}/videos".format(media, tmdb_id), {}, ttl=168)
    return payload.get("results", []) or []


def seasons(tmdb_id):
    payload = details("tv", tmdb_id)
    show_title = payload.get("name") or ""
    show_year = item_year(payload)
    out = []
    for season in payload.get("seasons", []) or []:
        number = season.get("season_number")
        if number is None:
            continue
        out.append({
            "tmdb_id": str(tmdb_id),
            "tmdb_type": "tv",
            "title": season.get("name") or "Season {0}".format(number),
            "showtitle": show_title,
            "year": show_year,
            "season": str(number),
            "plot": season.get("overview") or "",
            "poster": image_url(season.get("poster_path")),
            "fanart": fanart_url(payload.get("backdrop_path")),
            "premiered": season.get("air_date") or "",
            "episode_count": season.get("episode_count") or 0,
            "kind": "season",
        })
    return out


def episodes(tmdb_id, season_number):
    payload = _request("/tv/{0}/season/{1}".format(tmdb_id, season_number), {}, ttl=168)
    show = _request("/tv/{0}".format(tmdb_id), {}, ttl=168)
    show_title = show.get("name") or ""
    show_year = item_year(show)
    show_runtimes = show.get("episode_run_time") or []
    default_runtime = show_runtimes[0] if show_runtimes else None
    out = []
    for ep in payload.get("episodes", []) or []:
        ep_no = ep.get("episode_number")
        ep_runtime = ep.get("runtime")
        if not ep_runtime and default_runtime:
            ep_runtime = default_runtime
        out.append({
            "tmdb_id": str(tmdb_id),
            "tmdb_type": "tv",
            "title": ep.get("name") or "Episode {0}".format(ep_no),
            "showtitle": show_title,
            "year": show_year,
            "season": str(season_number),
            "episode": str(ep_no or ""),
            "plot": ep.get("overview") or "",
            "poster": image_url(ep.get("still_path")),
            "fanart": image_url(ep.get("still_path"), fanart_size()) or fanart_url(show.get("backdrop_path")),
            "rating": ep.get("vote_average") or "",
            "votes": ep.get("vote_count") or "",
            "premiered": ep.get("air_date") or "",
            "runtime": ep_runtime * 60 if ep_runtime else "",
            "kind": "episode",
        })
    return out


def related(media_type, tmdb_id, relation="similar", page=1):
    media = normalize_media_type(media_type)
    relation = "recommendations" if relation == "recommendations" else "similar"
    return paged("/{0}/{1}/{2}".format(media, tmdb_id, relation), media, page=page)


def _saved_collections_path():
    return os.path.join(xbmcvfs.translatePath("special://profile/addon_data/" + ADDON_ID), "saved_collections.json")


def get_saved_collections():
    try:
        with open(_saved_collections_path(), "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_collection(collection_id, title, poster="", fanart=""):
    saved = get_saved_collections()
    cid = str(collection_id)
    for item in saved:
        if str(item.get("collection_id")) == cid:
            return
    saved.append({"collection_id": cid, "title": title, "poster": poster, "fanart": fanart})
    _write_saved_collections(saved)


def unsave_collection(collection_id):
    saved = get_saved_collections()
    cid = str(collection_id)
    saved = [item for item in saved if str(item.get("collection_id")) != cid]
    _write_saved_collections(saved)


def is_collection_saved(collection_id):
    cid = str(collection_id)
    return any(str(item.get("collection_id")) == cid for item in get_saved_collections())


def _write_saved_collections(data):
    try:
        path = _saved_collections_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            _safe_fsync(f)
        os.replace(tmp, path)
    except Exception:
        pass


def collection(collection_id):
    payload = _request("/collection/{0}".format(collection_id), {}, ttl=168)
    results = [normalize_item(item, "movie") for item in payload.get("parts", []) or []]
    results.sort(key=lambda x: x.get("premiered") or "")
    return {"page": 1, "total_pages": 1, "results": results, "raw": payload}


def _norm_title(value):
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def tv_collection(show_refs):
    results = []
    for ref in show_refs or []:
        expected = ""
        if isinstance(ref, (list, tuple)):
            tmdb_id = str(ref[0] or "")
            expected = str(ref[1] or "") if len(ref) > 1 else ""
        else:
            tmdb_id = str(ref or "")
        if not tmdb_id:
            continue
        try:
            payload = details("tv", tmdb_id)
            if not payload:
                continue
            if expected:
                actual = payload.get("name") or payload.get("original_name") or ""
                if _norm_title(actual) != _norm_title(expected):
                    continue
            results.append(normalize_item(payload, "tv"))
        except Exception:
            continue
    results.sort(key=lambda x: x.get("premiered") or "", reverse=True)
    return {
        "page": 1,
        "total_pages": 1,
        "results": results,
        "raw": {},
    }


def _collection_part_art(raw):
    parts = raw.get("parts") or []
    parts = sorted(parts, key=lambda item: item.get("release_date") or "9999-99-99")
    part_poster = ""
    part_fanart = ""
    for part in parts:
        if not part_poster and part.get("poster_path"):
            part_poster = image_url(part.get("poster_path"))
        if not part_fanart and part.get("backdrop_path"):
            part_fanart = fanart_url(part.get("backdrop_path"))
        if part_poster and part_fanart:
            break
    return part_poster, part_fanart


def collection_summary(collection_data):
    if not collection_data:
        return None
    collection_id = str(collection_data.get("id") or "")
    poster = image_url(collection_data.get("poster_path"))
    fanart = fanart_url(collection_data.get("backdrop_path"))
    overview = collection_data.get("overview") or ""
    parts = collection_data.get("parts") or []
    enriched_raw = None
    needs_enrichment = collection_id and (not poster or not fanart or not overview or not parts)
    if needs_enrichment:
        try:
            details_data = collection(collection_id)
            enriched_raw = details_data.get("raw") or {}
        except Exception:
            pass
    if not poster or not fanart:
        raw = enriched_raw or {}
        poster = poster or image_url(raw.get("poster_path"))
        fanart = fanart or fanart_url(raw.get("backdrop_path"))
        part_poster, part_fanart = _collection_part_art(raw)
        poster = poster or part_poster or part_fanart
        fanart = fanart or part_fanart or poster
    if not overview and enriched_raw:
        overview = enriched_raw.get("overview") or ""
    if not parts and enriched_raw:
        parts = enriched_raw.get("parts") or []
    return {
        "collection_id": collection_id,
        "title": collection_data.get("name") or "Unknown Collection",
        "poster": poster,
        "fanart": fanart,
        "plot": overview,
        "raw": enriched_raw if enriched_raw else collection_data,
        "parts": parts,
    }


def collections_from_movie_list(list_name="popular", page=1, per_page=20, max_scan_pages=15):
    page = max(1, int(page or 1))
    per_page = max(1, int(per_page or 20))
    cache_key = cache.make_key("collections_from_movie_list", list_name, page, per_page, max_scan_pages)
    cached = cache.get("tmdb_collections", cache_key)
    if cached is not None:
        return cached
    target_start = (page - 1) * per_page
    target_end = target_start + per_page
    seen = set()
    collections = []
    source_page = 1
    source_total = 1
    while source_page <= min(source_total, max_scan_pages):
        movies = movie_list(list_name, page=source_page)
        source_total = int(movies.get("total_pages") or source_total or 1)
        for movie in movies.get("results", []) or []:
            tmdb_id = movie.get("tmdb_id") or ""
            if not tmdb_id:
                continue
            try:
                payload = details("movie", tmdb_id)
            except Exception:
                continue
            coll = payload.get("belongs_to_collection")
            if not coll:
                continue
            cid = str(coll.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            summary = collection_summary(coll)
            if summary:
                collections.append(summary)
            if len(collections) > target_end:
                break
        if len(collections) > target_end:
            break
        source_page += 1
    results = collections[target_start:target_end]
    has_more = len(collections) > target_end
    result = {
        "page": page,
        "total_pages": page + 1 if has_more else page,
        "results": results,
        "raw": {},
    }
    cache.set("tmdb_collections", cache_key, result, 604800)
    return result


def _latin_score(value):
    text = str(value or "")
    if not text:
        return 0
    score = 0
    for ch in text:
        if ch.isascii() and (ch.isalpha() or ch in " .-'"):
            score += 1
    return score


def _mostly_latin(value):
    text = str(value or "").strip()
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = [ch for ch in letters if ch.isascii()]
    return len(latin) >= max(1, int(len(letters) * 0.6))


def person_details(person_id):
    return _request("/person/{0}".format(person_id), {"append_to_response": "external_ids"}, ttl=168)


def person_display_name(item, hydrate=False):
    name = (item.get("name") or "").strip()
    if name and _mostly_latin(name):
        return name
    aliases = item.get("also_known_as") or []
    if not aliases and hydrate and item.get("id"):
        try:
            aliases = person_details(item.get("id")).get("also_known_as") or []
        except Exception:
            aliases = []
    candidates = [alias.strip() for alias in aliases if alias and _mostly_latin(alias)]
    if candidates:
        candidates.sort(key=_latin_score, reverse=True)
        return candidates[0]
    return name


def normalize_person(item, hydrate_name=False, require_profile=False):
    if not item or not item.get("id"):
        return None
    if item.get("adult") and not include_adult():
        return None
    if require_profile and not item.get("profile_path"):
        return None
    name = person_display_name(item, hydrate=hydrate_name)
    if not name or not _mostly_latin(name):
        return None
    return {
        "id": str(item.get("id") or ""),
        "name": name,
        "profile_path": item.get("profile_path") or "",
        "popularity": item.get("popularity") or 0,
        "known_for": item.get("known_for") or [],
        "raw": item,
    }


def normalize_people_page(payload, page=1, hydrate_names=False, require_profile=False):
    results = []
    seen = set()
    for item in payload.get("results", []) or []:
        person = normalize_person(item, hydrate_name=hydrate_names, require_profile=require_profile)
        if not person:
            continue
        pid = person["id"]
        if pid in seen:
            continue
        seen.add(pid)
        results.append(person)
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or 1),
        "results": results,
        "raw": payload,
    }


def people_popular(page=1):
    payload = _request("/person/popular", {"page": page}, ttl=24)
    return normalize_people_page(payload, page=page, hydrate_names=True, require_profile=True)


def people_trending(window="day", page=1):
    interval = "week" if window == "week" else "day"
    payload = _request("/trending/person/{0}".format(interval), {"page": page}, ttl=24)
    return normalize_people_page(payload, page=page, hydrate_names=True, require_profile=True)


def people_search(query, page=1):
    payload = _request("/search/person", {"query": query, "page": page}, ttl=1)
    return normalize_people_page(payload, page=page, hydrate_names=True, require_profile=False)


def person_movie_credits(person_id):
    return _request("/person/{0}/movie_credits".format(person_id), {}, ttl=168)


def person_tv_credits(person_id):
    return _request("/person/{0}/tv_credits".format(person_id), {}, ttl=168)
