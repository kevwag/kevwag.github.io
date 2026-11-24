import calendar
import datetime
import json
import re
import time
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

import cache


_CTX = {}

RESULTS_CACHE_NS = "sportdb_results"
RESULTS_CACHE_TTL = 5 * 60
RESULTS_STATIC_CACHE_TTL = 24 * 60 * 60
RESULTS_PAGE_SIZE = 100
LIVE_WINDOW_SECONDS = 30 * 60
FINISHED_KEEP_SECONDS = 30 * 60
SPORTDB_BASE = "https://api.sportdb.dev"

POPULAR_LIVE_SPORTS = (
    ("football", "Football"),
    ("basketball", "Basketball"),
    ("tennis", "Tennis"),
    ("hockey", "Hockey"),
    ("baseball", "Baseball"),
    ("american-football", "American Football"),
    ("volleyball", "Volleyball"),
    ("handball", "Handball"),
    ("rugby-union", "Rugby Union"),
    ("rugby-league", "Rugby League"),
    ("cricket", "Cricket"),
    ("darts", "Darts"),
    ("snooker", "Snooker"),
    ("motorsport", "Motorsport"),
)

OTHER_LIVE_SPORTS = (
    ("badminton", "Badminton"),
    ("beach-volleyball", "Beach Volleyball"),
    ("boxing", "Boxing"),
    ("cycling", "Cycling"),
    ("floorball", "Floorball"),
    ("futsal", "Futsal"),
    ("golf", "Golf"),
    ("mma", "MMA"),
    ("rugby-sevens", "Rugby Sevens"),
    ("table-tennis", "Table Tennis"),
    ("water-polo", "Water Polo"),
)


def setup(context):
    global _CTX
    _CTX = dict(context or {})


def c(name):
    return _CTX[name]


def _t(string_id, *args):
    return c("_t")(string_id, *args)


def _api_key():
    value = (c("addon").getSetting("sportdb_api_key") or "").strip()
    if value.lower() in ("true", "false", "none", "null", "default"):
        return ""
    return value


def _timeout():
    try:
        return max(5, int(c("addon").getSetting("sportdb_timeout") or "12"))
    except Exception:
        return 12


def _sport_label(slug):
    return str(slug or "").replace("-", " ").replace("_", " ").strip().title()


def _notify_missing_key():
    xbmcgui.Dialog().notification(
        "Xstream Pro",
        "Add your SportDB.dev API in Tools / Settings / Sports",
        xbmcgui.NOTIFICATION_INFO,
        5000,
    )


def _require_api_key():
    if _api_key():
        return True
    _notify_missing_key()
    _end([_action("Open Settings", {"mode": "settings"}, "settings")])
    return False


def _url(path):
    return "{0}/{1}".format(SPORTDB_BASE.rstrip("/"), str(path or "").strip("/"))


def _path_part(value):
    return urllib.parse.quote(str(value or "").strip(), safe="")


def _api_link_path(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        value = parsed.path
        if parsed.query:
            value = value + "?" + parsed.query
    return value.lstrip("/")


def _flashscore_path(*parts):
    clean = [str(part).strip("/") for part in parts if str(part or "").strip()]
    return "api/flashscore/" + "/".join(_path_part(part) for part in clean)


def _row_link(row, *keys):
    if not isinstance(row, dict):
        return ""
    links = row.get("links") if isinstance(row.get("links"), dict) else {}
    for key in keys:
        path = _api_link_path(row.get(key) or links.get(key))
        if path:
            return path
    return ""


def _get_json(path, params=None, ttl=None):
    if not _api_key():
        return {}
    params = params or {}
    key = cache.make_key("sportdb", path, params)
    cached = cache.get(RESULTS_CACHE_NS, key)
    if cached is not None:
        return cached

    url = _url(path)
    try:
        response = requests.get(
            url,
            params=params,
            headers={"X-API-Key": _api_key(), "Accept": "application/json"},
            timeout=_timeout(),
            allow_redirects=False,
        )
        if response.status_code >= 400:
            body = ""
            try:
                body = (response.text or "").replace("\r", " ").replace("\n", " ")[:300]
            except Exception:
                body = ""
            if response.status_code == 429:
                message = "SportDB rate limit hit. Wait a moment and try again."
            else:
                message = "SportDB request failed (HTTP {0}). Check API key or endpoint.".format(response.status_code)
            try:
                c("_log")(
                    "SportDB request failed: {0} params={1} status={2} body={3}".format(
                        url, params, response.status_code, body
                    )
                )
            except Exception:
                pass
            return {"_sportdb_error": message, "_sportdb_status": response.status_code}
        data = response.json() or {}
    except Exception as exc:
        try:
            c("_log")("SportDB request failed: {0} params={1} error={2}".format(url, params, exc))
        except Exception:
            pass
        return {"_sportdb_error": "SportDB request failed. Check connection, API key, or endpoint."}

    if data:
        cache.set(RESULTS_CACHE_NS, key, data, ttl if ttl is not None else RESULTS_CACHE_TTL)
    return data


def _sportdb_error(data):
    if isinstance(data, dict):
        return data.get("_sportdb_error") or ""
    return ""


def _param(params, key, default=""):
    value = (params or {}).get(key, [default])
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def _query(params):
    out = {}
    for key, value in (params or {}).items():
        out[key] = value[0] if isinstance(value, (list, tuple)) else value
    return out


def _icon(name):
    try:
        return c("_local_icon")(name)
    except Exception:
        return name


def _art(icon):
    return c("_menu_art")(_icon(icon), c("_addon_fanart")())


def _apply_info(li, info):
    if not info:
        return
    li.setInfo("video", info)
    plot = str(info.get("plot") or "")
    outline = str(info.get("plotoutline") or "")
    genre = str(info.get("genre") or "")
    title = str(info.get("title") or "")
    if title:
        li.setProperty("title", title)
    if plot:
        li.setProperty("plot", plot)
        li.setProperty("Plot", plot)
        li.setProperty("description", plot)
        li.setProperty("summary", plot)
    if outline:
        li.setProperty("plotoutline", outline)
        try:
            li.setLabel2(outline)
        except Exception:
            pass
    if genre:
        li.setProperty("genre", genre)


def _folder(label, params, icon="DefaultFolder.png", info=None):
    li = c("_new_listitem")(label)
    li.setArt(_art(icon))
    li.setProperty("IsPlayable", "false")
    _apply_info(li, info)
    return c("build_url")(params), li, True


def _action(label, params, icon="DefaultFolder.png", info=None):
    li = c("_new_listitem")(label)
    li.setArt(_art(icon))
    li.setProperty("IsPlayable", "false")
    _apply_info(li, info)
    return c("build_url")(params), li, False


def _info_item(label, icon="DefaultFolder.png", info=None):
    li = c("_new_listitem")(label)
    li.setArt(_art(icon))
    li.setProperty("IsPlayable", "false")
    _apply_info(li, info)
    return c("build_url")({"mode": "sports_results_endpoint", "endpoint": "noop"}), li, True


def _end(items, content=""):
    if content:
        xbmcplugin.setContent(c("addon_handle"), content)
    xbmcplugin.addDirectoryItems(c("addon_handle"), items or [])
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)
    timing = _CTX.get("_log_route_timing")
    if timing:
        timing()


def _empty(label=None):
    li = c("_new_listitem")(label or _t(30223))
    xbmcplugin.addDirectoryItem(c("addon_handle"), "", li, False)
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _json_item(item):
    return json.dumps(item or {}, ensure_ascii=False)


def _item_from_params(params):
    raw = _param(params, "item", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _value(item, *keys):
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = item.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            nested = _value(value, "name", "title", "label")
            if nested:
                return nested
            continue
        if isinstance(value, list):
            parts = []
            for entry in value:
                if isinstance(entry, dict):
                    nested = _value(entry, "name", "title", "label")
                    if nested:
                        parts.append(nested)
                elif entry not in (None, ""):
                    parts.append(str(entry))
            if parts:
                return ", ".join(parts)
            continue
        return str(value)
    return ""


def _extract(data, *preferred):
    error = _sportdb_error(data)
    if error:
        return [{"_sportdb_error": error}]
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    keys = list(preferred) + [
        "data", "items", "results", "matches", "match", "fixtures", "fixture",
        "countries", "country", "competitions", "competition", "leagues", "league",
        "seasons", "season", "standings", "table", "rows", "clubs", "club",
        "teams", "team", "players", "player", "transfers", "transfer",
        "lineups", "lineup", "stats", "statistics",
    ]
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
    return []


def _page(params):
    try:
        return max(1, int(_param(params, "page", "1") or "1"))
    except Exception:
        return 1


def _paged(items, params):
    page = _page(params)
    start = (page - 1) * RESULTS_PAGE_SIZE
    end = start + RESULTS_PAGE_SIZE
    return page, items[start:end], end < len(items)


def _next_params(params, page):
    out = _query(params)
    out["page"] = str(page)
    return out


def _id(item, *extra):
    return _value(item, *(extra + ("id", "Id", "ID", "_id", "match_id", "club_id", "team_id", "player_id")))


def _clean_competition_part(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    return value.strip(" -:/")


def _competition_label_from_row(row):
    direct = _value(
        row,
        "tournamentName",
        "competition",
        "league",
        "league_name",
        "eventTournamentName",
        "tournamentStageName",
        "tournamentTemplateName",
    )
    if direct:
        return direct

    category = _value(row, "categoryName", "country", "countryName", "region")
    series = _value(row, "series", "tour", "organization", "competitionType")
    discipline = _value(row, "discipline", "gender", "eventType", "drawType")
    stage = _value(row, "stage", "round", "eventStage")
    name = _value(row, "name", "title")
    parts = [_clean_competition_part(v) for v in (series, discipline, category, name, stage)]
    parts = [v for v in parts if v]
    return " - ".join(parts) if parts else "Other live matches"


def _parse_event_timestamp(value):
    if value in (None, "", [], {}):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        if re.match(r"^\d+(\.\d+)?$", text):
            return float(text)
        if text.endswith("Z"):
            dt = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
            return float(calendar.timegm(dt.timetuple()))
        if "T" in text:
            text = text.split("+", 1)[0].split(".", 1)[0]
            dt = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
            return float(calendar.timegm(dt.timetuple()))
    except Exception:
        return None
    return None


def _event_start_ts(row):
    for key in ("startTime", "startUtime", "startDateTimeUtc", "eventStartTime", "time"):
        ts = _parse_event_timestamp(row.get(key) if isinstance(row, dict) else None)
        if ts is not None:
            return ts
    return None


def _event_stage_ts(row):
    for key in ("stageStartUtime", "eventStageStartTime", "lastUpdateTime"):
        ts = _parse_event_timestamp(row.get(key) if isinstance(row, dict) else None)
        if ts is not None:
            return ts
    return None


def _event_status_text(row):
    values = [
        _value(row, "eventStage"),
        _value(row, "status"),
        _value(row, "state"),
        _value(row, "eventType"),
    ]
    return " ".join([v for v in values if v]).strip()


def _event_status_upper(row):
    return _event_status_text(row).upper()


def _is_live_status(row):
    status = _event_status_upper(row)
    if not status:
        return False
    live_markers = (
        "LIVE",
        "IN PLAY",
        "IN-PROGRESS",
        "IN PROGRESS",
        "1ST HALF",
        "2ND HALF",
        "HALFTIME",
        "HALF TIME",
        "HT",
        "OT",
        "OVERTIME",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "QUARTER",
        "PERIOD",
        "SET",
        "INNING",
    )
    return any(marker in status for marker in live_markers)


def _is_finished_status(row):
    status = _event_status_upper(row)
    finished_markers = (
        "FINISHED",
        "ENDED",
        "FULL TIME",
        "FULL-TIME",
        "AFTER PEN",
        "AFTER ET",
        "FT",
    )
    return any(marker in status for marker in finished_markers)


def _event_in_live_window(row, now=None):
    now = float(now if now is not None else time.time())
    start_ts = _event_start_ts(row)
    stage_ts = _event_stage_ts(row)

    if _is_finished_status(row):
        reference = stage_ts if stage_ts is not None else start_ts
        return reference is not None and 0 <= now - reference <= FINISHED_KEEP_SECONDS

    if _is_live_status(row):
        if start_ts is not None and start_ts - now > LIVE_WINDOW_SECONDS:
            return False
        return True

    if start_ts is not None:
        delta = start_ts - now
        return 0 <= delta <= LIVE_WINDOW_SECONDS

    return False


def _format_event_time(row):
    ts = _event_start_ts(row)
    if ts is None:
        return ""
    try:
        return time.strftime("%H:%M", time.localtime(ts))
    except Exception:
        return ""


def _event_state(row):
    if _is_finished_status(row):
        return "finished"
    if _is_live_status(row):
        return "live"
    return "upcoming"


def _event_state_dot(row):
    state = _event_state(row)
    if state == "live":
        return "[COLOR lime]●[/COLOR]"
    if state == "finished":
        return "[COLOR red]●[/COLOR]"
    return "[COLOR dodgerblue]●[/COLOR]"


def _clean_phase_value(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    upper = text.upper()
    generic = (
        "LIVE",
        "SCHEDULED",
        "FINISHED",
        "ENDED",
        "POSTPONED",
        "CANCELLED",
        "CANCELED",
    )
    if upper in generic:
        return ""
    if text in ("-1", "0"):
        return ""
    if re.match(r"^\d+$", text):
        return "{0}'".format(text)
    return text


def _computed_elapsed_phase(row):
    if _event_state(row) != "live":
        return ""
    start_ts = _event_start_ts(row)
    if start_ts is None:
        return ""
    elapsed = int(max(0, time.time() - start_ts) // 60) + 1
    if elapsed <= 0:
        return ""
    sport = _value(row, "_sport_slug").lower()
    football_like = (
        "football",
        "soccer",
        "futsal",
        "handball",
        "rugby-union",
        "rugby-league",
    )
    if sport in football_like:
        return "{0}'".format(min(elapsed, 130))
    return ""


def _event_phase(row):
    stage = ""
    for key in (
        "period",
        "periodName",
        "currentPeriod",
        "currentQuarter",
        "currentSet",
        "currentInning",
        "eventStage",
        "eventStageName",
        "eventType",
        "stageName",
        "state",
        "status",
    ):
        stage = _clean_phase_value(_value(row, key))
        if stage:
            break

    clock = ""
    for key in (
        "gameTime",
        "clock",
        "minute",
        "matchTime",
        "matchClock",
        "timer",
        "remainingTime",
        "periodTime",
    ):
        clock = _clean_phase_value(_value(row, key))
        if clock:
            break

    if stage and clock:
        return "{0} {1}".format(stage, clock)
    if clock:
        return clock
    if stage:
        return stage

    computed = _computed_elapsed_phase(row)
    if computed:
        return computed

    if _event_state(row) == "finished":
        return "FT"
    return ""


def _event_time_phase(row):
    start = _format_event_time(row)
    phase = _event_phase(row)
    if start and phase:
        return "{0}/{1}".format(start, phase)
    return start or phase


def _event_score(row):
    home_score = _value(row, "homeFullTimeScore", "homeScore", "home_score", "score_home", "home_goals", "eventHomeScore")
    away_score = _value(row, "awayFullTimeScore", "awayScore", "away_score", "score_away", "away_goals", "eventAwayScore")
    if not home_score and not away_score:
        return ""
    score = "{0}-{1}".format(home_score or "0", away_score or "0")
    detail = _value(row, "playingOnSets", "sets", "setScores", "periodScores")
    if detail:
        score = "{0} ({1})".format(score, detail)
    return score


def _event_teams(row):
    home = _value(
        row,
        "homeName",
        "homeFirstName",
        "home_team",
        "homeTeam",
        "home",
        "home_name",
        "homeTeamName",
        "eventHomeParticipantName",
        "homeParticipantName",
    )
    away = _value(
        row,
        "awayName",
        "awayFirstName",
        "away_team",
        "awayTeam",
        "away",
        "away_name",
        "awayTeamName",
        "eventAwayParticipantName",
        "awayParticipantName",
    )
    if home and away:
        return "{0} vs {1}".format(home, away)
    return _value(row, "name", "title", "event", "match", "sortParticipant") or _t(31634)


def _event_title(row):
    first = " ".join([piece for piece in (_event_state_dot(row), _event_time_phase(row)) if piece])
    pieces = [
        first,
        _event_teams(row),
        _event_score(row),
    ]
    pieces = [piece for piece in pieces if piece]
    return " - ".join(pieces)


def _live_match_plot(row):
    title = _event_title(row)
    competition = _competition_label_from_row(row)
    teams = _event_teams(row)
    start = _format_event_time(row)
    phase = _event_phase(row)
    score = _event_score(row)
    sport = _value(row, "_sport_label")

    parts = []
    if title:
        parts.append(title)
    if competition:
        parts.append("League/Event: {0}".format(competition))
    if teams:
        parts.append("Match: {0}".format(teams))
    if start:
        parts.append("Start: {0}".format(start))
    if phase:
        parts.append("Game time: {0}".format(phase))
    if score:
        parts.append("Score: {0}".format(score))
    if sport:
        parts.append("Sport: {0}".format(sport))
    parts.append("Source: SportDB.dev / Flashscore")
    return "\n".join(parts)


def _event_info(row):
    label = _event_title(row)
    competition = _competition_label_from_row(row)
    return {
        "title": label,
        "plot": _live_match_plot(row),
        "plotoutline": competition,
        "genre": competition,
        "mediatype": "episode",
        "tvshowtitle": competition,
        "tagline": _event_teams(row),
    }


def _match_id(item):
    return _id(item, "match_id", "fixture_id", "game_id", "eventId")


def _match_label(item):
    return _event_title(item)


def _live_rows_for_sport(sport, sport_label=""):
    rows = _extract(_get_json(_flashscore_path(sport, "live")), "matches", "fixtures", "data")
    out = []
    now = time.time()
    for row in rows:
        if isinstance(row, dict):
            copy = dict(row)
            copy["_sport_slug"] = sport
            if sport_label:
                copy["_sport_label"] = sport_label
            if _event_in_live_window(copy, now):
                out.append(copy)
    out.sort(key=lambda row: (_event_start_ts(row) or 0, _competition_key(row).lower(), _event_teams(row).lower()))
    return out


def _competition_key(row):
    return _competition_label_from_row(row)


def _render_live_event_rows(rows, params, icon="calendar", content="episodes"):
    rows = [row for row in rows if isinstance(row, dict)]
    if rows and rows[0].get("_sportdb_error"):
        _empty(rows[0].get("_sportdb_error"))
        return
    if not rows:
        _empty(_t(31634))
        return
    page, chunk, has_next = _paged(rows, params)
    items = []
    for row in chunk:
        label = _event_title(row)
        info = _event_info(row)
        items.append(_info_item(label, icon, info))
    if has_next:
        items.append(_folder(_t(30232), _next_params(params, page + 1), "next"))
    _end(items, content)


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------

def results_menu():
    if not _require_api_key():
        return
    items = []
    for sport, label in POPULAR_LIVE_SPORTS:
        items.append(_folder(
            label,
            {"mode": "sports_results_endpoint", "endpoint": "live_sport", "sport": sport, "sport_label": label},
            "calendar",
            {
                "title": label,
                "plot": "Live scores from SportDB.dev / Flashscore.\nOpens all live matches and live competition groups.",
                "genre": "Live scores",
            },
        ))
    items.append(_folder(
        "Other",
        {"mode": "sports_results_endpoint", "endpoint": "other_sports"},
        "providers",
        {
            "title": "Other live sports",
            "plot": "Less common live sports supported by SportDB.dev / Flashscore.",
            "genre": "Live scores",
        },
    ))
    _end(items)


def _other_sports(params):
    if not _require_api_key():
        return
    items = []
    for sport, label in OTHER_LIVE_SPORTS:
        items.append(_folder(
            label,
            {"mode": "sports_results_endpoint", "endpoint": "live_sport", "sport": sport, "sport_label": label},
            "calendar",
            {
                "title": label,
                "plot": "Live scores from SportDB.dev / Flashscore.",
                "genre": "Live scores",
            },
        ))
    _end(items)


def _live_sport_menu(params):
    if not _require_api_key():
        return
    sport = _param(params, "sport", "")
    sport_label = _param(params, "sport_label", "") or _sport_label(sport)
    if not sport:
        results_menu()
        return
    rows = _live_rows_for_sport(sport, sport_label)
    groups = {}
    for row in rows:
        groups.setdefault(_competition_key(row), []).append(row)

    items = [_folder(
        "All Live [COLOR gray]({0})[/COLOR]".format(len(rows)),
        {"mode": "sports_results_endpoint", "endpoint": "live_events", "sport": sport, "sport_label": sport_label, "competition": ""},
        "calendar",
        {
            "title": "{0} - All Live".format(sport_label),
            "plot": "{0} live matches from SportDB.dev / Flashscore.".format(len(rows)),
            "genre": "Live scores",
        },
    )]

    for competition in sorted(groups, key=lambda name: name.lower()):
        items.append(_folder(
            "{0} [COLOR gray]({1})[/COLOR]".format(competition, len(groups[competition])),
            {"mode": "sports_results_endpoint", "endpoint": "live_events", "sport": sport, "sport_label": sport_label, "competition": competition},
            "providers",
            {
                "title": competition,
                "plot": "{0} live matches in {1}.".format(len(groups[competition]), competition),
                "genre": sport_label,
            },
        ))
    _end(items)


def _live_events(params):
    if not _require_api_key():
        return
    sport = _param(params, "sport", "")
    sport_label = _param(params, "sport_label", "") or _sport_label(sport)
    competition = _param(params, "competition", "")
    if not sport:
        results_menu()
        return
    rows = _live_rows_for_sport(sport, sport_label)
    if competition:
        rows = [row for row in rows if _competition_key(row) == competition]
    _render_live_event_rows(rows, params)


def live_menu():
    results_menu()


def today_menu(params=None):
    results_menu()


def yesterday_menu(params=None):
    results_menu()


def upcoming_menu(params=None):
    results_menu()


def leagues_menu(params=None):
    results_menu()


def teams_menu(params=None):
    results_menu()


def players_menu(params=None):
    results_menu()


def events_menu(params=None):
    results_menu()


def venues_menu(params=None):
    _empty("Venues are not available in Live Results.")


def tv_listings_menu(params=None):
    _empty("TV listings are not available in Live Results.")


def highlights_menu(params=None):
    _empty("Highlights are not available in Live Results.")


def api_catalog_menu(params=None):
    results_menu()


def search_menu(params=None):
    _empty("Search is not available in Live Results.")


def tools_menu():
    _end([
        _action("API status", {"mode": "sports_results_api_status"}, "settings"),
        _action("Clear cache", {"mode": "sports_results_clear_cache"}, "tools"),
        _action("Open settings", {"mode": "settings"}, "settings"),
    ])


# ---------------------------------------------------------------------------
# Match detail routes (Flashscore links)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _noop(params=None):
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)


def generic_endpoint(params):
    endpoint = _param(params, "endpoint", "")
    handlers = {
        "other_sports": _other_sports,
        "live_sport": _live_sport_menu,
        "live_events": _live_events,
        "live_scores": lambda p: results_menu(),
        "noop": _noop,
        "match_menu": _noop,
        "match_details": _noop,
        "match_lineups": _noop,
        "match_stats": _noop,
    }
    handler = handlers.get(endpoint)
    if not handler:
        results_menu()
        return
    handler(params or {})


def entity_details(params):
    item = _item_from_params(params)
    if not item:
        _empty(_t(31634))
        return
    _textviewer(_match_label(item), item)


def clear_cache():
    cache.clear_namespace(RESULTS_CACHE_NS)
    xbmcgui.Dialog().notification("Xstream Pro", "SportDB.dev cache cleared")
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)


def api_status():
    key = _api_key()
    if not key:
        xbmcgui.Dialog().textviewer(
            "SportDB.dev Status",
            "SportDB.dev API key is not configured.\nAdd your SportDB.dev API in Tools / Settings / Sports",
        )
        xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
        return
    data = _get_json(_flashscore_path("football", "live"), ttl=RESULTS_STATIC_CACHE_TTL)
    error = _sportdb_error(data)
    if error:
        message = "SportDB.dev: configured\nKey length: {0}\nStatus check failed: {1}".format(len(key), error)
    else:
        count = len(_extract(data, "matches", "fixtures", "data"))
        message = "SportDB.dev: configured\nKey length: {0}\nFootball live events returned: {1}".format(len(key), count)
    xbmcgui.Dialog().textviewer("SportDB.dev Status", message)
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
