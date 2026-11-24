"""Trakt API client with OAuth device-code flow, token management, and JSON cache.

Authenticated and public endpoints are supported. GET responses are cached with
MD5-keyed JSON files. Token refresh is handled automatically.
"""
import datetime
import json
import os
import urllib.parse
import threading

import requests
import xbmc
import xbmcaddon
import xbmcvfs

import cache

ADDON_ID = "plugin.video.xstream-pro"
BASE_URL = "https://api.trakt.tv"
API_VERSION = "2"
TRAKT_PAGE_LIMIT = 20
# Public Trakt app client ID. This is not an OAuth secret.
BUNDLED_CLIENT_ID = "808bdce29edf4f1f70127ba7dda4cfca6c8ac13d207ad6843a7aea0112dbb53e"
BUNDLED_CLIENT_SECRET = ""
_SESSION = None
_TOKEN_LOCK = threading.RLock()


def _addon():
    return xbmcaddon.Addon(ADDON_ID)


def _log(message, level=xbmc.LOGINFO):
    xbmc.log("[Xstream Pro Trakt] {0}".format(str(message)), level)


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
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20)
        _SESSION.mount("https://", adapter)
    return _SESSION


def enabled():
    return _addon().getSetting("trakt_enabled").lower() != "false"


def _custom_credentials():
    cid = (_addon().getSetting("trakt_client_id") or "").strip()
    secret = (_addon().getSetting("trakt_client_secret") or "").strip()
    return cid, secret


def client_id():
    return _custom_credentials()[0] or BUNDLED_CLIENT_ID


def client_secret():
    return _custom_credentials()[1] or BUNDLED_CLIENT_SECRET


def public_configured():
    return bool(client_id())


def auth_configured():
    return bool(client_id() and client_secret())


def configured():
    return public_configured()


def _data_dir():
    profile = xbmcvfs.translatePath(_addon().getAddonInfo("profile"))
    path = os.path.join(profile, "trakt")
    os.makedirs(path, exist_ok=True)
    return path


def _token_path():
    return os.path.join(_data_dir(), "trakt_tokens.json")


def _read_tokens():
    try:
        with open(_token_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_tokens(tokens):
    path = _token_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(tokens, fh, ensure_ascii=False)
        fh.flush()
        _safe_fsync(fh)
    os.replace(tmp, path)


def clear_tokens():
    try:
        os.remove(_token_path())
    except OSError:
        pass
    clear_cache()


def clear_cache():
    cache.clear_namespace("trakt_auth")
    cache.clear_namespace("trakt_public")


def authorized():
    return bool(_read_tokens().get("access_token"))


def _headers(auth=False):
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": API_VERSION,
        "trakt-api-key": client_id(),
    }
    if auth:
        token = _read_tokens().get("access_token")
        if token:
            headers["Authorization"] = "Bearer {0}".format(token)
    return headers


def _retry_after_seconds(resp, fallback=2):
    raw = ""
    try:
        raw = resp.headers.get("Retry-After", "")
    except Exception:
        raw = ""

    try:
        if raw:
            return max(1, min(60, int(float(raw))))
    except Exception:
        pass

    return max(1, min(20, int(fallback)))


def _http_request(method, url, max_429_retries=2, **kwargs):
    last_resp = None

    for attempt in range(max_429_retries + 1):
        resp = _session().request(method, url, **kwargs)
        last_resp = resp

        if resp.status_code != 429:
            return resp

        if attempt >= max_429_retries:
            return resp

        delay = _retry_after_seconds(resp, fallback=2 * (attempt + 1))
        _log("Trakt 429 rate limit; retrying in {0}s".format(delay), xbmc.LOGWARNING)
        xbmc.sleep(delay * 1000)

    return last_resp


def _raise_trakt_error(resp, action="request"):
    status = int(getattr(resp, "status_code", 0) or 0)

    if status == 429:
        raise RuntimeError("Trakt rate limited. Try again later.")

    if status == 401:
        raise RuntimeError("Trakt authorization expired or failed.")

    if status == 403:
        raise RuntimeError("Trakt access forbidden.")

    if status >= 400:
        raise RuntimeError("Trakt {0} failed ({1})".format(action, status))


def device_code():
    resp = _http_request(
        "POST",
        BASE_URL + "/oauth/device/code",
        json={"client_id": client_id()},
        headers=_headers(False),
        timeout=15,
    )

    if resp.status_code >= 400:
        _raise_trakt_error(resp, "device code")

    return resp.json()


def poll_device_token(device_code_value):
    payload = {
        "code": device_code_value,
        "client_id": client_id(),
        "client_secret": client_secret(),
    }

    resp = _http_request(
        "POST",
        BASE_URL + "/oauth/device/token",
        json=payload,
        headers=_headers(False),
        timeout=15,
    )

    if resp.status_code == 400:
        return None

    if resp.status_code >= 400:
        _raise_trakt_error(resp, "authorization")

    tokens = resp.json()
    _write_tokens(tokens)
    return tokens


def refresh_token():
    with _TOKEN_LOCK:
        tokens = _read_tokens()
        refresh = tokens.get("refresh_token")

        if not refresh:
            return False

        payload = {
            "refresh_token": refresh,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "grant_type": "refresh_token",
        }

        resp = _http_request(
            "POST",
            BASE_URL + "/oauth/token",
            json=payload,
            headers=_headers(False),
            timeout=15,
        )

        if resp.status_code == 429:
            _log("Trakt token refresh rate limited; keeping existing tokens", xbmc.LOGWARNING)
            raise RuntimeError("Trakt rate limited while refreshing token. Try again later.")

        if resp.status_code in (400, 401, 403):
            clear_tokens()
            return False

        if resp.status_code >= 400:
            _raise_trakt_error(resp, "token refresh")

        _write_tokens(resp.json())
        return True


def request(path, params=None, auth=True):
    resp = _http_request(
        "GET",
        BASE_URL + path,
        params=params or {},
        headers=_headers(auth),
        timeout=20,
    )

    if auth and resp.status_code == 401:
        with _TOKEN_LOCK:
            resp = _http_request(
                "GET",
                BASE_URL + path,
                params=params or {},
                headers=_headers(auth),
                timeout=20,
            )
            if resp.status_code == 401:
                if refresh_token():
                    resp = _http_request(
                        "GET",
                        BASE_URL + path,
                        params=params or {},
                        headers=_headers(auth),
                        timeout=20,
                    )

    if resp.status_code >= 400:
        _raise_trakt_error(resp, "request")

    total_pages = int(resp.headers.get("X-Pagination-Page-Count") or "1")

    try:
        payload = resp.json()
    except Exception:
        payload = []

    return payload, total_pages


def cached_request(path, params=None, auth=True, ttl=300):
    cache_key = cache.make_key(path, sorted((params or {}).items()), bool(auth))
    namespace = "trakt_auth" if auth else "trakt_public"
    cached = cache.get(namespace, cache_key)
    if cached is not None:
        return cached
    result = request(path, params, auth)
    cache.set(namespace, cache_key, result, ttl)
    return result


def _movie_item(movie, raw=None):
    ids = movie.get("ids") or {}
    return {
        "tmdb_type": "movie",
        "tmdb_id": str(ids.get("tmdb") or ""),
        "title": movie.get("title") or "Unknown",
        "year": str(movie.get("year") or ""),
        "plot": movie.get("overview") or "",
        "kind": "movie",
        "raw": raw or movie,
    }


def _show_item(show, raw=None):
    ids = show.get("ids") or {}
    return {
        "tmdb_type": "tv",
        "tmdb_id": str(ids.get("tmdb") or ""),
        "title": show.get("title") or "Unknown",
        "year": str(show.get("year") or ""),
        "plot": show.get("overview") or "",
        "kind": "tvshow",
        "raw": raw or show,
    }


def _normalize_entry(entry, media_hint=""):
    movie = entry.get("movie")
    show = entry.get("show")
    season_obj = entry.get("season")
    episode_obj = entry.get("episode")
    if movie:
        return _movie_item(movie, entry)
    if episode_obj and show:
        ids = show.get("ids") or {}
        return {
            "tmdb_type": "tv",
            "tmdb_id": str(ids.get("tmdb") or ""),
            "title": episode_obj.get("title") or "Episode {0}".format(episode_obj.get("number") or ""),
            "showtitle": show.get("title") or "",
            "year": str(show.get("year") or ""),
            "season": str(episode_obj.get("season") or ""),
            "episode": str(episode_obj.get("number") or ""),
            "plot": episode_obj.get("overview") or "",
            "kind": "episode",
            "raw": entry,
        }
    if season_obj and show:
        ids = show.get("ids") or {}
        return {
            "tmdb_type": "tv",
            "tmdb_id": str(ids.get("tmdb") or ""),
            "title": "Season {0}".format(season_obj.get("number") or ""),
            "showtitle": show.get("title") or "",
            "year": str(show.get("year") or ""),
            "season": str(season_obj.get("number") or ""),
            "plot": "",
            "kind": "season",
            "raw": entry,
        }
    if show:
        return _show_item(show, entry)
    if entry.get("ids"):
        return _show_item(entry, entry) if media_hint == "tv" else _movie_item(entry, entry)
    return None


def normalize_entries(entries, media_hint=""):
    out = []
    for entry in entries or []:
        item = _normalize_entry(entry, media_hint)
        if item and item.get("tmdb_id"):
            out.append(item)
    return out


def _media_path(section, media):
    if section == "collection":
        return "/sync/collection/{0}".format(media)
    if section == "favorites":
        return "/sync/favorites/{0}/rank".format(media)
    if section == "watchlist":
        return "/sync/watchlist/{0}/rank".format(media)
    if section == "history":
        return "/sync/history/{0}".format(media)
    if section == "watched":
        return "/sync/watched/{0}".format(media)
    if section == "recommendations":
        return "/recommendations/{0}".format(media)
    return "/sync/watchlist/{0}/rank".format(media)


def _trakt_media_name(tmdb_type):
    if tmdb_type == "tv":
        return "shows", "tv"
    if tmdb_type == "season":
        return "seasons", "tv"
    if tmdb_type == "episode":
        return "episodes", "tv"
    return "movies", "movie"


def _media_list_one(section, tmdb_type="movie", page=1):
    media, media_hint = _trakt_media_name(tmdb_type)
    payload, total_pages = request(
        _media_path(section, media),
        params={"extended": "full", "page": page, "limit": 20},
        auth=True,
    )
    return {
        "page": page,
        "total_pages": total_pages,
        "results": normalize_entries(payload, media_hint),
        "raw": payload,
    }


def media_list(section, tmdb_type="movie", page=1):
    if tmdb_type == "both":
        movies = _media_list_one(section, "movie", page)
        shows = _media_list_one(section, "tv", page)
        return {
            "page": page,
            "total_pages": max(movies.get("total_pages", 1), shows.get("total_pages", 1)),
            "results": movies.get("results", []) + shows.get("results", []),
            "raw": {"movies": movies.get("raw"), "shows": shows.get("raw")},
        }
    return _media_list_one(section, tmdb_type, page)


def playback(media_kind="movies", page=1):
    kind = "episodes" if media_kind == "episodes" else "movies"
    payload, total_pages = request(
        "/sync/playback/{0}".format(kind),
        params={"extended": "full", "page": page, "limit": TRAKT_PAGE_LIMIT},
        auth=True,
    )
    media_hint = "tv" if kind == "episodes" else "movie"
    return {
        "page": page,
        "total_pages": total_pages,
        "results": normalize_entries(payload, media_hint),
        "raw": payload,
    }


def public_list(section, tmdb_type="movie", page=1, period="weekly", genre="", years=""):
    is_tv = tmdb_type == "tv"
    media = "shows" if is_tv else "movies"
    media_hint = "tv" if is_tv else "movie"
    params = {"extended": "full", "page": page, "limit": TRAKT_PAGE_LIMIT}
    if genre:
        params["genres"] = str(genre)
    if years:
        params["years"] = str(years)
    if section == "trending":
        path = "/{0}/trending".format(media)
    elif section == "popular":
        path = "/{0}/popular".format(media)
    elif section == "anticipated":
        path = "/{0}/anticipated".format(media)
    elif section == "watched":
        path = "/{0}/watched/{1}".format(media, period or "weekly")
    elif section == "played":
        path = "/{0}/played/{1}".format(media, period or "weekly")
    elif section == "collected":
        path = "/{0}/collected/{1}".format(media, period or "weekly")
    elif section == "favorited":
        path = "/{0}/favorited/{1}".format(media, period or "weekly")
    elif section == "boxoffice" and not is_tv:
        path = "/movies/boxoffice"
    else:
        path = "/{0}/trending".format(media)
    payload, total_pages = cached_request(path, params=params, auth=False, ttl=1800)
    return {
        "page": page,
        "total_pages": total_pages,
        "results": normalize_entries(payload, media_hint),
        "raw": payload,
    }


def _quote(value):
    return urllib.parse.quote(str(value or ""), safe="")


def _list_summary(entry):
    list_data = entry.get("list") or entry
    user = list_data.get("user") or {}
    ids = list_data.get("ids") or {}
    user_ids = user.get("ids") or {}
    user_slug = (
        user_ids.get("slug")
        or user.get("username")
        or user.get("name")
        or "me"
    )
    list_slug = ids.get("slug") or str(ids.get("trakt") or "")
    return {
        "name": list_data.get("name") or "Untitled List",
        "description": list_data.get("description") or "",
        "item_count": list_data.get("item_count") or 0,
        "user_slug": str(user_slug),
        "list_slug": str(list_slug),
        "raw": entry,
    }


def trakt_lists(section="trending", page=1, query=""):
    params = {"page": page, "limit": 20}
    if section == "my":
        path = "/users/me/lists"
        auth = True
    elif section == "liked":
        path = "/users/likes/lists"
        auth = True
    elif section == "popular":
        path = "/lists/popular"
        auth = False
    elif section == "search":
        path = "/search/list"
        params["query"] = query
        auth = False
    else:
        path = "/lists/trending"
        auth = False
    payload, total_pages = cached_request(path, params=params, auth=auth, ttl=1800)
    return {
        "page": page,
        "total_pages": total_pages,
        "results": [_list_summary(item) for item in payload or []],
        "raw": payload,
    }


def list_items(user_slug, list_slug, item_type="", page=1, auth=None):
    type_map = {
        "movie": "movies",
        "tv": "shows",
        "season": "seasons",
        "episode": "episodes",
    }
    path = "/users/{0}/lists/{1}/items".format(_quote(user_slug), _quote(list_slug))
    item_path = type_map.get(item_type)
    if item_path:
        path += "/" + item_path
    if auth is None:
        auth = str(user_slug or "").lower() == "me"
    payload, total_pages = cached_request(
        path,
        params={"extended": "full", "page": page, "limit": 20},
        auth=auth,
        ttl=1800,
    )
    return {
        "page": page,
        "total_pages": total_pages,
        "results": normalize_entries(payload),
        "raw": payload,
    }


def post(path, payload=None, auth=True):
    resp = _http_request(
        "POST",
        BASE_URL + path,
        json=payload or {},
        headers=_headers(auth),
        timeout=20,
    )
    if auth and resp.status_code == 401:
        with _TOKEN_LOCK:
            resp = _http_request(
                "POST",
                BASE_URL + path,
                json=payload or {},
                headers=_headers(auth),
                timeout=20,
            )
            if resp.status_code == 401:
                if refresh_token():
                    resp = _http_request(
                        "POST",
                        BASE_URL + path,
                        json=payload or {},
                        headers=_headers(auth),
                        timeout=20,
                    )
    if resp.status_code >= 400:
        _raise_trakt_error(resp, "post")
    try:
        return resp.json()
    except Exception:
        return {}


def _sync_payload(tmdb_type, tmdb_id, season="", episode=""):
    tmdb_id_int = int(tmdb_id)
    if tmdb_type == "movie":
        return {"movies": [{"ids": {"tmdb": tmdb_id_int}}]}
    show = {"ids": {"tmdb": tmdb_id_int}}
    if season:
        season_item = {"number": int(season)}
        if episode:
            season_item["episodes"] = [{"number": int(episode)}]
        show["seasons"] = [season_item]
    return {"shows": [show]}


def sync_item(section, action, tmdb_type, tmdb_id, season="", episode=""):
    if section == "collection":
        path = "/sync/collection"
    elif section == "favorites":
        path = "/sync/favorites"
    elif section == "history":
        path = "/sync/history"
    else:
        path = "/sync/watchlist"
    if action == "remove":
        path += "/remove"
    return post(path, _sync_payload(tmdb_type, tmdb_id, season, episode), auth=True)


def calendar(tmdb_type="tv", days=14):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if tmdb_type == "movie":
        payload, total_pages = cached_request(
            "/calendars/my/movies/{0}/{1}".format(today, days),
            params={"extended": "full"},
            auth=True,
            ttl=900,
        )
        return {
            "page": 1,
            "total_pages": total_pages,
            "results": normalize_entries(payload, "movie"),
            "raw": payload,
        }
    if tmdb_type == "both":
        movies = calendar("movie", days)
        shows = calendar("tv", days)
        return {
            "page": 1,
            "total_pages": 1,
            "results": movies.get("results", []) + shows.get("results", []),
            "raw": {"movies": movies.get("raw"), "shows": shows.get("raw")},
        }
    payload, total_pages = cached_request(
        "/calendars/my/shows/{0}/{1}".format(today, days),
        params={"extended": "full"},
        auth=True,
        ttl=900,
    )
    return {
        "page": 1,
        "total_pages": total_pages,
        "results": normalize_entries(payload, "tv"),
        "raw": payload,
    }


def calendar_endpoint(endpoint="shows", tmdb_type="tv", days=14):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if endpoint == "movies":
        payload, total_pages = cached_request(
            "/calendars/my/movies/{0}/{1}".format(today, days),
            params={"extended": "full"},
            auth=True,
            ttl=900,
        )
        return {
            "page": 1,
            "total_pages": total_pages,
            "results": normalize_entries(payload, "movie"),
            "raw": payload,
        }
    if endpoint == "all":
        movies = calendar_endpoint("movies", days=days)
        shows = calendar_endpoint("shows", days=days)
        return {
            "page": 1,
            "total_pages": 1,
            "results": movies.get("results", []) + shows.get("results", []),
            "raw": {"movies": movies.get("raw"), "shows": shows.get("raw")},
        }
    if endpoint == "premieres":
        path = "/calendars/my/shows/premieres/{0}/{1}".format(today, days)
    elif endpoint == "new":
        path = "/calendars/my/shows/new/{0}/{1}".format(today, days)
    else:
        path = "/calendars/my/shows/{0}/{1}".format(today, days)
    payload, total_pages = cached_request(path, params={"extended": "full"}, auth=True, ttl=900)
    return {
        "page": 1,
        "total_pages": total_pages,
        "results": normalize_entries(payload, "tv"),
        "raw": payload,
    }


def next_episodes(limit=TRAKT_PAGE_LIMIT):
    payload, _ = cached_request(
        "/sync/playback/episodes",
        params={"extended": "full", "limit": limit},
        auth=True,
        ttl=900,
    )
    out = normalize_entries(payload, "tv")
    return {
        "page": 1,
        "total_pages": 1,
        "results": out[:limit],
        "raw": payload,
    }


def mark_watched(tmdb_type, tmdb_id, season="", episode=""):
    return sync_item("history", "add", tmdb_type, tmdb_id, season, episode)


def mark_unwatched(tmdb_type, tmdb_id, season="", episode=""):
    return sync_item("history", "remove", tmdb_type, tmdb_id, season, episode)


def checkin_item(tmdb_type, tmdb_id, season="", episode="", message=""):
    tmdb_id_int = int(tmdb_id)
    if tmdb_type == "movie":
        payload = {"movie": {"ids": {"tmdb": tmdb_id_int}}, "sharing": {"twitter": False, "tumblr": False, "medium": False}}
    else:
        payload = {
            "show": {"ids": {"tmdb": tmdb_id_int}},
            "episode": {"season": int(season) if season else 1, "number": int(episode) if episode else 1},
            "sharing": {"twitter": False, "tumblr": False, "medium": False},
        }
    if message:
        payload["message"] = message
    return post("/checkin", payload, auth=True)



