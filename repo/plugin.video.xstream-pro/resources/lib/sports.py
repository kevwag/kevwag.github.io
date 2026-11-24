import hashlib
import json
import os
import re
import time
import urllib.parse

import xbmc
import xbmcvfs
import xbmcgui
import xbmcplugin
from iptv import IPTV

_CTX = {}
SPORTS_PAGE_SIZE = 20
SPORTS_PROCESSED_CACHE_VERSION = 2
ACTIVE_DOT = "[COLOR lime]\u25cf[/COLOR] "
SPORTS_PVR_GROUP_PREFIX = "Sports TV - "
SPORTS_LEGACY_PREFIXES = ("Sports TV - ", "Xstream Pro Sports TV - ", "Xstream Pro Sports TV", "Sports TV")

SPORT_GROUPS = (
    ("football", "Football / Soccer", (
        "football", "soccer", "premier league", "laliga", "la liga",
        "serie a", "bundesliga", "ligue 1", "champions league",
        "europa league", "conference league", "uefa", "fifa", "world cup",
        "euro ", "fa cup", "carabao", "mls", "eredivisie", "copa",
        "libertadores",
    )),
    ("basketball", "Basketball", (
        "basketball", "nba", "wnba", "euroleague", "euro league",
        "ncaa basket",
    )),
    ("tennis", "Tennis", (
        "tennis", "atp", "wta", "wimbledon", "roland garros",
        "us open tennis", "australian open",
    )),
    ("motorsport", "Motorsport", (
        "formula", "f1", "f 1", "motogp", "moto gp", "nascar", "indycar",
        "rally", "wec", "dtm", "superbike", "motorsport", "racing",
    )),
    ("combat", "Combat Sports", (
        "ufc", "mma", "boxing", "fight", "wwe", "aew", "wrestling",
        "pfl", "bellator", "one championship", "glory kickboxing",
    )),
    ("american", "American Sports", (
        "nfl", "mlb", "baseball", "nhl", "ice hockey", "hockey", "ncaaf",
        "college football", "super bowl", "stanley cup",
    )),
    ("hockey", "Hockey", (
        "hockey", "nhl", "ice hockey", "khl",
    )),
    ("golf", "Golf", (
        "golf", "pga", "liv golf", "ryder cup",
    )),
    ("cricket", "Cricket", (
        "cricket", "ipl", "icc", "ashes", "t20",
    )),
    ("rugby", "Rugby", (
        "rugby", "six nations", "nrl", "super rugby",
    )),
    ("darts_snooker", "Darts / Snooker", (
        "darts", "snooker", "billiards", "pool",
    )),
    ("winter", "Winter Sports", (
        "ski", "skiing", "snowboard", "biathlon", "winter sport",
        "ice skating",
    )),
    ("events_ppv", "Events / PPV", (
        "event", "events", "ppv", "pay per view", "match day", "live event",
    )),
    ("sports_news", "Sports News", (
        "sports news", "sport news", "sky sports news", "espn news",
    )),
)

SPORT_BRAND_KEYWORDS = (
    "sky sport", "sky sports", "tnt sport", "tnt sports", "bt sport",
    "bein sport", "bein sports", "dazn", "espn", "eurosport", "supersport",
    "sport klub", "arena sport", "maxsport", "max sport", "nova sport",
    "canal+ sport", "eleven sports", "ziggo sport", "optus sport",
    "fox sports", "premier sports", "viaplay sports", "sport tv",
    "sportska tv", "šport tv", "match tv", "match!", "setanta",
    "ssc sport", "sportdigital", "orf sport", "m4 sport", "digi sport",
    "polsat sport", "rmc sport", "trt spor", "ptv sports", "tsn",
    "sportsnet", "tudn", "sportv", "tyc sports", "sporza", "srf sport",
    "o2 tv sport", "cosmote sport", "diema sport", "star sports",
    "sports18", "kayo", "zonasport", "zona sport", "arena premium",
    "arena adrenalin", "sk esport", "sk esports", "esport", "esports",
)

SPORT_GENERIC_NAME_KEYWORDS = (
    "sport", "sports", "sportska", "šport", "spor",
)

SPORT_PROVIDER_GROUP_KEYWORDS = (
    "sport", "sports", "sport ex yu", "sport world", "sports world",
)

SPECIAL_SPORT_GROUPS = ("events_ppv", "sports_news")
OTHER_COUNTRIES_KEY = "other_countries"
MIN_COUNTRY_GROUP_SIZE = 6

COUNTRY_PREFIXES = {
    "us": "united_states",
    "usa": "united_states",
    "uk": "united_kingdom",
    "gb": "united_kingdom",
    "ie": "ireland",
    "ca": "canada",
    "mx": "mexico",
    "br": "brazil",
    "ar": "middle_east",
    "arg": "argentina",
    "fr": "france",
    "de": "germany",
    "es": "spain",
    "it": "italy",
    "pt": "portugal",
    "nl": "netherlands",
    "be": "belgium",
    "ch": "switzerland",
    "at": "austria",
    "pl": "poland",
    "cz": "czech_slovakia",
    "sk": "czech_slovakia",
    "hr": "croatia",
    "cro": "croatia",
    "sr": "serbia",
    "srb": "serbia",
    "rs": "serbia",
    "bih": "bosnia_herzegovina",
    "ba": "bosnia_herzegovina",
    "slo": "slovenia",
    "si": "slovenia",
    "cg": "montenegro",
    "mne": "montenegro",
    "mk": "north_macedonia",
    "mkd": "north_macedonia",
    "al": "albania",
    "gr": "greece",
    "tr": "turkey",
    "ro": "romania",
    "bg": "bulgaria",
    "hu": "hungary",
    "dk": "nordic",
    "se": "nordic",
    "no": "nordic",
    "fi": "nordic",
    "is": "nordic",
    "sa": "middle_east",
    "ksa": "middle_east",
    "qa": "middle_east",
    "ae": "middle_east",
    "za": "africa",
    "in": "india",
    "pk": "pakistan",
    "au": "australia",
    "nz": "new_zealand",
    "exyu": "exyu",
    "ex-yu": "exyu",
    "lt": "baltic",
    "lv": "baltic",
    "ee": "baltic",
    "ku": "middle_east",
    "kuw": "middle_east",
    "pe": "south_america",
    "cy": "europe",
    "il": "middle_east",
    "co": "south_america",
    "iraq": "middle_east",
    "ru": "russia",
    "ukr": "ukraine",
    "bahr": "middle_east",
    "ec": "south_america",
    "bo": "south_america",
    "cr": "central_america_caribbean",
    "ht": "central_america_caribbean",
    "car": "central_america_caribbean",
    "lby": "africa",
    "th": "asia",
    "ph": "asia",
    "bd": "south_asia",
    "afg": "south_asia",
    "aze": "caucasus",
    "arm": "caucasus",
    "ge": "caucasus",
    "mt": "europe",
    "sw": "nordic",
    "dstv": "africa",
    "af": "africa",
    "osn": "middle_east",
    "mbc": "middle_east",
    "bab": "south_asia",
    "ir": "middle_east",
    "jor": "middle_east",
    "omn": "middle_east",
    "tun": "africa",
}

COUNTRY_REGION_GROUPS = (
    ("united_states", "United States", (
        "united states", "usa", "u s", "us", "america", "american",
        "cbs sports", "nbc sports",
    )),
    ("united_kingdom", "United Kingdom", (
        "united kingdom", "great britain", "britain", "uk", "england",
        "scotland", "wales", "sky sports", "tnt sports", "bt sport",
        "premier sports uk",
    )),
    ("ireland", "Ireland", ("ireland", "irish", "eir sport")),
    ("canada", "Canada", ("canada", "canadian", "tsn", "sportsnet")),
    ("mexico", "Mexico", ("mexico", "mexican", "tudn", "azteca deportes")),
    ("brazil", "Brazil", ("brazil", "brasil", "brazilian", "sportv")),
    ("argentina", "Argentina", ("argentina", "argentinian", "tyc sports")),
    ("south_america", "South America", (
        "south america", "latin america", "latam", "conmebol", "copa libertadores",
        "peru", "peruvian", "colombia", "colombian",
        "ecuador", "ecuadorian", "bolivia", "bolivian",
    )),
    ("france", "France", ("france", "french", "rmc sport")),
    ("germany", "Germany", ("germany", "german", "deutschland", "sky sport bundesliga")),
    ("spain", "Spain", ("spain", "spanish", "espana", "laliga", "la liga", "movistar deportes")),
    ("italy", "Italy", ("italy", "italian", "italia", "serie a", "sky sport italia")),
    ("portugal", "Portugal", ("portugal", "portuguese", "sport tv")),
    ("netherlands", "Netherlands", ("netherlands", "dutch", "holland", "ziggo sport")),
    ("belgium", "Belgium", ("belgium", "belgian", "sporza")),
    ("switzerland", "Switzerland", ("switzerland", "swiss", "srf sport")),
    ("austria", "Austria", ("austria", "austrian", "orf sport")),
    ("poland", "Poland", ("poland", "polish", "canal+ sport polska", "polsat sport")),
    ("czech_slovakia", "Czech / Slovakia", (
        "czech", "cesko", "slovakia", "slovak", "o2 tv sport", "nova sport",
    )),
    ("exyu", "Ex-Yugoslavia", (
        "ex yu", "ex-yu", "exyu", "yugoslavia", "yugoslav", "balkan",
        "arena sport", "sport klub", "sport club", "max sport",
    )),
    ("croatia", "Croatia", ("croatia", "croatian", "hrvatska", "hr")),
    ("serbia", "Serbia", ("serbia", "serbian", "srbija", "srb", "rs")),
    ("bosnia_herzegovina", "Bosnia and Herzegovina", (
        "bosnia", "bosnian", "herzegovina", "bih", "bi h",
    )),
    ("slovenia", "Slovenia", ("slovenia", "slovenian", "slovenija", "slo")),
    ("montenegro", "Montenegro", ("montenegro", "crna gora", "cg", "mne")),
    ("north_macedonia", "North Macedonia", (
        "north macedonia", "macedonia", "macedonian", "mk", "mkd",
    )),
    ("albania", "Albania", ("albania", "albanian", "shqip", "alb")),
    ("greece", "Greece", ("greece", "greek", "nova sports", "cosmote sport")),
    ("turkey", "Turkey", ("turkey", "turkish", "trt spor", "beinsports tr")),
    ("romania", "Romania", ("romania", "romanian", "digi sport")),
    ("bulgaria", "Bulgaria", ("bulgaria", "bulgarian", "diema sport")),
    ("hungary", "Hungary", ("hungary", "hungarian", "m4 sport")),
    ("nordic", "Nordic", (
        "nordic", "denmark", "danish", "sweden", "swedish", "norway",
        "norwegian", "finland", "finnish", "iceland", "viaplay sports",
    )),
    ("europe", "Europe", (
        "europe", "european", "eurosport", "euroleague", "champions league",
        "europa league", "uefa", "cyprus", "malta",
    )),
    ("middle_east", "Middle East", (
        "middle east", "mena", "arab", "arabic", "saudi", "ksa", "qatar",
        "uae", "dubai", "abu dhabi", "bein sports", "ssc sport",
        "kuwait", "kuwaiti", "bahrain", "bahraini", "jordan", "jordanian",
        "oman", "omani", "palestine", "palestinian",
        "iraq", "iraqi", "israel", "israeli",
        "osn", "mbc", "kurdish",
    )),
    ("africa", "Africa", (
        "africa", "african", "south africa", "supersport", "nigeria", "ghana",
        "morocco", "egypt", "dstv", "libya", "libyan",
        "tunisia", "tunisian", "cameroon",
    )),
    ("india", "India", ("india", "indian", "star sports", "sports18")),
    ("pakistan", "Pakistan", ("pakistan", "pakistani", "ptv sports")),
    ("asia", "Asia", (
        "asia", "asian", "china", "chinese", "japan", "japanese", "korea",
        "korean", "thailand", "thai", "indonesia", "malaysia", "singapore",
        "philippines", "vietnam",
    )),
    ("australia", "Australia", ("australia", "australian", "fox sports australia", "kayo")),
    ("new_zealand", "New Zealand", ("new zealand", "nz", "sky sport nz")),
    ("baltic", "Baltic", (
        "baltic", "lithuania", "lithuanian", "lietuva",
        "latvia", "latvian", "latvija", "estonia", "estonian", "eesti",
    )),
    ("russia", "Russia", ("russia", "russian", "rossiya", "match tv")),
    ("ukraine", "Ukraine", ("ukraine", "ukrainian", "ukrayina")),
    ("caucasus", "Caucasus", ("caucasus", "armenia", "armenian", "azerbaijan", "georgia", "georgian", "sakartvelo")),
    ("central_america_caribbean", "Central America / Caribbean", (
        "central america", "caribbean", "costa rica", "dominican",
        "panama", "guatemala", "honduras", "el salvador",
        "nicaragua", "jamaica",
    )),
    ("south_asia", "South Asia", (
        "south asia", "bangladesh", "bengali", "afghanistan", "afghan",
        "sri lanka", "nepal",
    )),
)

EXCLUDE_KEYWORDS = (
    "adult", "xxx", "porn", "movie", "movies", "cinema", "cinemax",
    "cinematic", "film", "films", "drama", "crime", "documentary",
    "documentaries", "docs", "kids", "cartoon", "music", "radio",
    "series", "comedy", "family", "romance", "thriller", "horror",
    "sci fi", "sci-fi", "history", "nature", "travel", "food",
    "lifestyle", "cooking", "religion",
)


def setup(context):
    global _CTX
    _CTX = dict(context or {})


def c(name):
    return _CTX[name]


def _profile_cached_call(profile_num, helper_name, *args):
    runner = c("_call_with_active_profile")
    fn = c(helper_name)
    return runner(profile_num, fn, *args)


def _addon_profile_dir():
    import xbmcvfs

    profile = xbmcvfs.translatePath(c("addon").getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    return profile


def _sports_processed_cache_path(profile_num, include_replay_meta=False):
    suffix = "replay" if include_replay_meta else "live"
    safe_profile = re.sub(r"[^0-9A-Za-z_-]", "", str(profile_num))
    return os.path.join(
        _addon_profile_dir(),
        "sports_processed_p{0}_{1}.json".format(safe_profile, suffix),
    )


def _sports_raw_cache_mtimes(profile_num):
    profile = _addon_profile_dir()
    mtimes = {}
    for name in ("m3u", "xtream_cats_live", "xtream_streams_live"):
        path = os.path.join(profile, "data_cache_p{0}_{1}.json".format(profile_num, name))
        try:
            mtimes[name] = os.path.getmtime(path)
        except Exception:
            mtimes[name] = 0
    return mtimes


def _sports_processed_signature(profile_num, creds, include_replay_meta=False):
    password_hash = hashlib.sha256(
        (creds.get("xtream_password", "") or "").encode("utf-8")
    ).hexdigest()
    override_path = _sports_overrides_path()
    try:
        overrides_mtime = os.path.getmtime(override_path)
    except Exception:
        overrides_mtime = 0

    payload = {
        "version": SPORTS_PROCESSED_CACHE_VERSION,
        "profile_num": str(profile_num),
        "include_replay_meta": bool(include_replay_meta),
        "xtream_url": creds.get("xtream_url", "") or "",
        "xtream_username": creds.get("xtream_username", "") or "",
        "xtream_password_hash": password_hash,
        "m3u_url": creds.get("m3u_url", "") or "",
        "hide_adult_categories": c("addon").getSetting("hide_adult_categories") or "",
        "sports_detection_level": c("addon").getSetting("sports_detection_level") or "",
        "sports_overrides_mtime": overrides_mtime,
        "raw_cache_mtimes": _sports_raw_cache_mtimes(profile_num),
    }
    data = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _load_sports_processed_cache(profile_num, include_replay_meta, signature):
    path = _sports_processed_cache_path(profile_num, include_replay_meta)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception:
        return None

    if data.get("version") != SPORTS_PROCESSED_CACHE_VERSION:
        return None
    if data.get("signature") != signature:
        return None
    channels = data.get("channels")
    if not isinstance(channels, list):
        return None
    return channels


def _save_sports_processed_cache(profile_num, include_replay_meta, signature, channels):
    path = _sports_processed_cache_path(profile_num, include_replay_meta)
    tmp_path = path + ".tmp"
    payload = {
        "version": SPORTS_PROCESSED_CACHE_VERSION,
        "signature": signature,
        "created": time.time(),
        "channels": channels if isinstance(channels, list) else [],
    }
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as exc:
        try:
            c("_log")("Sports processed cache save failed: {0}".format(exc))
        except Exception:
            pass


def _clear_sports_processed_cache():
    profile = _addon_profile_dir()
    removed = 0
    try:
        for name in os.listdir(profile):
            if name.startswith("sports_processed_p") and name.endswith(".json"):
                try:
                    os.remove(os.path.join(profile, name))
                    removed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def _t(string_id, *args):
    return c("_t")(string_id, *args)


def _norm(value):
    value = str(value or "").lower()
    value = re.sub(r"[\[\]\(\)\{\}\|\_\-\.:/;,]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _profile_name(pnum):
    return (
        c("addon").getSetting("profile_{0}_name".format(pnum))
        or _t(30390, pnum)
    )


def _active_pvr_profile():
    try:
        return str(c("_get_pvr_profile_num")())
    except Exception:
        return "1"


def _active_sports_pvr_profile():
    try:
        return str(c("_get_sports_pvr_profile_num")())
    except Exception:
        return _active_pvr_profile()


def _enabled_profiles():
    try:
        return [(str(p), name) for p, name in c("_enabled_profiles_with_credentials")()]
    except Exception:
        out = []
        for pnum in range(1, 11):
            if c("addon").getSetting("profile_{0}_enabled".format(pnum)) == "true":
                if (
                    c("addon").getSetting("profile_{0}_xtream_url".format(pnum))
                    or c("addon").getSetting("profile_{0}_m3u".format(pnum))
                ):
                    out.append((str(pnum), _profile_name(pnum)))
        return out


def _folder(label, params, icon="DefaultFolder.png"):
    li = c("_new_listitem")(label)
    li.setArt(c("_menu_art")(c("_local_icon")(icon), c("_addon_fanart")()))
    return c("build_url")(params), li, True


def _action(label, params, icon="DefaultFolder.png"):
    li = c("_new_listitem")(label)
    li.setArt(c("_menu_art")(c("_local_icon")(icon), c("_addon_fanart")()))
    li.setProperty("IsPlayable", "false")
    return c("build_url")(params), li, False


def _empty(label):
    li = c("_new_listitem")(label)
    xbmcplugin.addDirectoryItem(c("addon_handle"), "", li, False)
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)


def _end(items, content=""):
    if content:
        xbmcplugin.setContent(c("addon_handle"), content)
    xbmcplugin.addDirectoryItems(c("addon_handle"), items)
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)
    timing = _CTX.get("_log_route_timing")
    if timing:
        timing()


def _is_hidden_live(pnum, category_id="", item_id=""):
    try:
        if category_id and str(category_id) in c("_get_hidden_subcats")("live", pnum):
            return True
        if item_id and str(item_id) in c("_get_hidden_items")("live", pnum):
            return True
    except Exception:
        return False
    return False


def _is_adult(text):
    try:
        return bool(c("_is_adult_category")(text))
    except Exception:
        return False


def _is_provider_separator_title(name):
    text = str(name or "").strip()
    if not text:
        return True
    # Some providers insert playable-looking section headers such as
    # "*** SPORT POLAND***". They are not real channels and fail on playback.
    if re.match(r"^[\*\-=#_~\s]+[^\*\-=#_~]+[\*\-=#_~\s]+$", text):
        return True
    return False


def _sports_detection_level():
    raw_value = c("addon").getSetting("sports_detection_level") or "Medium"
    value = raw_value.strip().lower()
    legacy = {
        "conservative": "low",
        "normal": "medium",
        "aggressive": "high",
    }
    mapped = legacy.get(value, value)
    if mapped != value:
        try:
            c("addon").setSetting("sports_detection_level", mapped.title())
        except Exception:
            pass
    value = mapped
    if value not in ("low", "medium", "high"):
        return "medium"
    return value


def _sports_page_size():
    raw = c("addon").getSetting("sports_page_size") or str(SPORTS_PAGE_SIZE)
    if str(raw).strip().lower() == "unlimited":
        return 0
    try:
        size = int(raw)
    except Exception:
        size = SPORTS_PAGE_SIZE
    if size not in (20, 40, 60, 80, 100, 200, 500):
        return SPORTS_PAGE_SIZE
    return size


def _sport_group_for(name, provider_group):
    name_text = _norm(name)
    group_text = _norm(provider_group)
    sports_news = _contains_any(name_text, ("sports news", "sport news", "sky sports news", "espn news"))
    if not sports_news and _contains_any("{0} {1}".format(name_text, group_text), EXCLUDE_KEYWORDS):
        return ""

    level = _sports_detection_level()
    provider_group_is_sport = _contains_any(group_text, SPORT_PROVIDER_GROUP_KEYWORDS)
    name_has_brand = _contains_any(name_text, SPORT_BRAND_KEYWORDS)
    name_has_generic_sport = _contains_any(name_text, SPORT_GENERIC_NAME_KEYWORDS)
    name_has_sport_word = False
    for key, _label, words in SPORT_GROUPS:
        if key in SPECIAL_SPORT_GROUPS:
            continue
        for word in words:
            if _term_in_text(name_text, word):
                name_has_sport_word = True
                break
        if name_has_sport_word:
            break

    for key, label, words in SPORT_GROUPS:
        if key not in SPECIAL_SPORT_GROUPS:
            continue
        if key == "events_ppv" and level == "low":
            continue
        for word in words:
            if _term_in_text(name_text, word) and (name_has_brand or name_has_generic_sport or name_has_sport_word or provider_group_is_sport):
                return key
    for key, label, words in SPORT_GROUPS:
        if key in SPECIAL_SPORT_GROUPS:
            continue
        for word in words:
            if _term_in_text(name_text, word):
                return key

    if name_has_brand:
        return "other"
    if level in ("medium", "high") and name_has_generic_sport:
        return "other"
    if level == "high" and provider_group_is_sport:
        return "other"
    return ""


def _sport_group_label(key):
    if key == "all":
        return "All Sports Channels"
    if key == "other":
        return "Sports"
    for group_key, label, _words in SPORT_GROUPS:
        if key == group_key:
            return label
    return "Sports"


def _term_in_text(text, term):
    term = _norm(term)
    if not term:
        return False
    return " {0} ".format(term) in " {0} ".format(text)


def _contains_any(text, terms):
    for term in terms:
        if _term_in_text(text, term):
            return True
    return False


def _country_prefix_for(name):
    match = re.match(r"\s*([A-Za-z]{2,4})\s*(?::|\|)", str(name or ""))
    if not match:
        return ""
    return COUNTRY_PREFIXES.get(match.group(1).lower(), "")


def _country_region_for(name, provider_group):
    prefixed = _country_prefix_for(name)
    if prefixed:
        return prefixed
    for text in (_norm(name), _norm(provider_group)):
        if not text:
            continue
        for key, _label, terms in COUNTRY_REGION_GROUPS:
            for term in terms:
                if _term_in_text(text, term):
                    return key
    return ""


def _country_region_label(key):
    if key == OTHER_COUNTRIES_KEY:
        return "Other Countries"
    for group_key, label, _terms in COUNTRY_REGION_GROUPS:
        if key == group_key:
            return label
    return ""


def _country_region_sort_label(key):
    if key == OTHER_COUNTRIES_KEY:
        return "zzzz other countries"
    label = _country_region_label(key)
    return label.lower() if label else "zzzz"


def _natural_key(value):
    parts = []
    for part in re.split(r"(\d+)", _norm(value)):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts)


def _truthy(value):
    try:
        return bool(c("_truthy_catchup")(value))
    except Exception:
        return str(value or "").strip().lower() in ("1", "yes", "true", "default")


def _sports_overrides_path():
    import os
    import xbmcvfs
    profile = xbmcvfs.translatePath(c("addon").getAddonInfo("profile"))
    os.makedirs(profile, exist_ok=True)
    return os.path.join(profile, "sports_detection_overrides.json")


def _load_sports_overrides():
    path = _sports_overrides_path()
    if not os.path.exists(path):
        return {"include": {}, "exclude": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception:
        data = {}
    include = data.get("include")
    exclude = data.get("exclude")
    if not isinstance(include, dict):
        include = {}
    if not isinstance(exclude, dict):
        exclude = {}
    return {"include": include, "exclude": exclude}


def _save_sports_overrides(data):
    path = _sports_overrides_path()
    tmp_path = path + ".tmp"
    payload = {
        "include": data.get("include") or {},
        "exclude": data.get("exclude") or {},
    }
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, ensure_ascii=False)
    os.replace(tmp_path, path)
    _clear_sports_processed_cache()


def _sports_channel_override_id(ch):
    profile_num = str(ch.get("profile_num") or "")
    source_type = str(ch.get("source_type") or "")
    stable = (
        ch.get("stream_id")
        or ch.get("tvg_id")
        or ch.get("name")
        or ""
    )
    return "{0}|{1}|{2}".format(profile_num, source_type, stable)


def _sports_channel_override_record(ch):
    return {
        "name": ch.get("name", ""),
        "provider_group": ch.get("provider_group", ""),
        "country_region": ch.get("country_region", "") or _country_region_for(ch.get("name"), ch.get("provider_group")),
        "sport_group": ch.get("sport_group", "") or "other_sports",
    }


def _sports_is_excluded(ch, overrides=None):
    overrides = overrides or _load_sports_overrides()
    return _sports_channel_override_id(ch) in (overrides.get("exclude") or {})


def _sports_included_record(ch, overrides=None):
    overrides = overrides or _load_sports_overrides()
    return (overrides.get("include") or {}).get(_sports_channel_override_id(ch))


def _fetch_profile_channels(pnum, include_replay_meta=False):
    pnum = str(pnum)
    creds = c("_get_credentials_for_profile")(pnum)
    cache_signature = _sports_processed_signature(pnum, creds, include_replay_meta)
    cached = _load_sports_processed_cache(pnum, include_replay_meta, cache_signature)
    if cached is not None:
        return cached
    xt_url = creds.get("xtream_url", "")
    xt_user = creds.get("xtream_username", "")
    xt_pwd = creds.get("xtream_password", "")
    m3u_url = creds.get("m3u_url", "")
    hide_adult = c("addon").getSetting("hide_adult_categories").lower() == "true"
    channels = []
    overrides = _load_sports_overrides()
    if xt_url and xt_user and xt_pwd:
        cats = _profile_cached_call(pnum, "_get_cached_xtream_categories", xt_url, xt_user, xt_pwd, "live") or []
        cat_map = {}
        for cat in cats:
            cat_map[str(cat.get("category_id", ""))] = cat.get("category_name", "Live TV")
        streams = _profile_cached_call(pnum, "_get_cached_xtream_streams", xt_url, xt_user, xt_pwd, "live") or []
        for provider_index, s in enumerate(streams):
            cat_id = str(s.get("category_id", ""))
            sid = str(s.get("stream_id", ""))
            group = cat_map.get(cat_id, "Live TV")
            name = s.get("name", "Unknown")
            if _is_provider_separator_title(name):
                continue
            if _is_hidden_live(pnum, cat_id, sid):
                continue
            if hide_adult and (_is_adult(group) or _is_adult(name)):
                continue
            sport_key = _sport_group_for(name, group)
            country_region = _country_region_for(name, group)
            candidate = {
                "name": name,
                "url": IPTV.build_xtream_stream_url(xt_url, xt_user, xt_pwd, s, "live"),
                "logo": s.get("stream_icon", ""),
                "tvg_id": s.get("epg_channel_id") or sid,
                "epg_channel_id": s.get("epg_channel_id") or "",
                "provider_group": group,
                "sport_group": sport_key,
                "country_region": country_region,
                "profile_num": pnum,
                "profile_name": _profile_name(pnum),
                "_provider_order": provider_index,
                "stream_id": sid,
                "source_type": "xtream",
                "catchup": "",
                "catchup_source": "",
                "catchup_days": "",
                "raw": s,
            }
            if sport_key:
                if _sports_is_excluded(candidate, overrides):
                    continue
            else:
                manual = _sports_included_record(candidate, overrides)
                if manual:
                    sport_key = manual.get("sport_group") or "other_sports"
                    country_region = manual.get("country_region") or country_region or OTHER_COUNTRIES_KEY
                else:
                    continue
            has_catchup = _truthy(s.get("tv_archive")) or _truthy(s.get("catchup"))
            catchup_source = ""
            if include_replay_meta and has_catchup:
                catchup_source = c("_xtream_timeshift_catchup_source")(xt_url, xt_user, xt_pwd, sid)
            candidate["sport_group"] = sport_key
            candidate["country_region"] = country_region
            candidate["catchup"] = "default" if has_catchup else ""
            candidate["catchup_source"] = catchup_source
            candidate["catchup_days"] = str(s.get("tv_archive_duration") or "7") if has_catchup else ""
            channels.append(candidate)
        save_signature = _sports_processed_signature(pnum, creds, include_replay_meta)
        _save_sports_processed_cache(pnum, include_replay_meta, save_signature, channels)
        return channels
    if m3u_url:
        for provider_index, ch in enumerate(_profile_cached_call(pnum, "_get_cached_m3u_channels", m3u_url) or []):
            name = ch.get("name", "Unknown")
            group = ch.get("group", "General")
            item_id = str(ch.get("tvg_id") or ch.get("url") or name)
            if _is_provider_separator_title(name):
                continue
            if _is_hidden_live(pnum, group, item_id):
                continue
            if hide_adult and (_is_adult(group) or _is_adult(name)):
                continue
            sport_key = _sport_group_for(name, group)
            country_region = _country_region_for(name, group)
            candidate = {
                "name": name,
                "url": ch.get("url", ""),
                "logo": ch.get("logo", ""),
                "tvg_id": ch.get("tvg_id") or name,
                "provider_group": group,
                "sport_group": sport_key,
                "country_region": country_region,
                "profile_num": pnum,
                "profile_name": _profile_name(pnum),
                "_provider_order": provider_index,
                "stream_id": item_id,
                "source_type": "m3u",
                "catchup": ch.get("catchup", ""),
                "catchup_source": ch.get("catchup_source", ""),
                "catchup_days": ch.get("catchup_days", ""),
                "raw": ch,
            }
            if sport_key:
                if _sports_is_excluded(candidate, overrides):
                    continue
            else:
                manual = _sports_included_record(candidate, overrides)
                if manual:
                    sport_key = manual.get("sport_group") or "other_sports"
                    country_region = manual.get("country_region") or country_region or OTHER_COUNTRIES_KEY
                else:
                    continue
            candidate["sport_group"] = sport_key
            candidate["country_region"] = country_region
            channels.append(candidate)
        save_signature = _sports_processed_signature(pnum, creds, include_replay_meta)
        _save_sports_processed_cache(pnum, include_replay_meta, save_signature, channels)
        return channels
    save_signature = _sports_processed_signature(pnum, creds, include_replay_meta)
    _save_sports_processed_cache(pnum, include_replay_meta, save_signature, channels)
    return channels


def _fetch_scope_channels(scope, profile_num="", include_replay_meta=False):
    if scope == "all":
        out = []
        for pnum, _name in _enabled_profiles():
            out.extend(_fetch_profile_channels(pnum, include_replay_meta=include_replay_meta))
        return out
    return _fetch_profile_channels(
        profile_num or _active_pvr_profile(),
        include_replay_meta=include_replay_meta,
    )


def _fetch_profile_all_live_candidates(pnum):
    pnum = str(pnum)
    creds = c("_get_credentials_for_profile")(pnum)
    xt_url = creds.get("xtream_url", "")
    xt_user = creds.get("xtream_username", "")
    xt_pwd = creds.get("xtream_password", "")
    m3u_url = creds.get("m3u_url", "")
    hide_adult = c("addon").getSetting("hide_adult_categories").lower() == "true"
    channels = []
    if xt_url and xt_user and xt_pwd:
        cats = _profile_cached_call(pnum, "_get_cached_xtream_categories", xt_url, xt_user, xt_pwd, "live") or []
        cat_map = {}
        for cat in cats:
            cat_map[str(cat.get("category_id", ""))] = cat.get("category_name", "Live TV")
        streams = _profile_cached_call(pnum, "_get_cached_xtream_streams", xt_url, xt_user, xt_pwd, "live") or []
        for s in streams:
            cat_id = str(s.get("category_id", ""))
            sid = str(s.get("stream_id", ""))
            group = cat_map.get(cat_id, "Live TV")
            name = s.get("name", "Unknown")
            if _is_provider_separator_title(name):
                continue
            if _is_hidden_live(pnum, cat_id, sid):
                continue
            if hide_adult and (_is_adult(group) or _is_adult(name)):
                continue
            channels.append({
                "name": name,
                "url": "",
                "logo": s.get("stream_icon", ""),
                "tvg_id": s.get("epg_channel_id") or sid,
                "epg_channel_id": s.get("epg_channel_id") or "",
                "provider_group": group,
                "sport_group": _sport_group_for(name, group) or "",
                "country_region": _country_region_for(name, group),
                "profile_num": pnum,
                "profile_name": _profile_name(pnum),
                "stream_id": sid,
                "source_type": "xtream",
                "raw": s,
            })
        return channels
    if m3u_url:
        for ch in _profile_cached_call(pnum, "_get_cached_m3u_channels", m3u_url) or []:
            name = ch.get("name", "Unknown")
            group = ch.get("group", "General")
            item_id = str(ch.get("tvg_id") or ch.get("url") or name)
            if _is_provider_separator_title(name):
                continue
            if _is_hidden_live(pnum, group, item_id):
                continue
            if hide_adult and (_is_adult(group) or _is_adult(name)):
                continue
            channels.append({
                "name": name,
                "url": "",
                "logo": ch.get("logo", ""),
                "tvg_id": ch.get("tvg_id") or name,
                "provider_group": group,
                "sport_group": _sport_group_for(name, group) or "",
                "country_region": _country_region_for(name, group),
                "profile_num": pnum,
                "profile_name": _profile_name(pnum),
                "stream_id": item_id,
                "source_type": "m3u",
                "raw": ch,
            })
        return channels
    return channels


def _fetch_scope_all_live_candidates(scope, profile_num=""):
    if scope == "all":
        out = []
        for pnum, _name in _enabled_profiles():
            out.extend(_fetch_profile_all_live_candidates(pnum))
        return out
    return _fetch_profile_all_live_candidates(profile_num or _active_pvr_profile())


def _pvr_group_assignments(channels, group_mode):
    group_mode = str(group_mode or "Countries / Regions")
    if group_mode == "Provider Groups":
        return {id(ch): (ch.get("provider_group") or "Sports") for ch in channels}
    if group_mode == "Sport Types":
        return {id(ch): _sport_group_label(ch.get("sport_group")) for ch in channels}
    if group_mode == "Flat List":
        return {id(ch): "Sports TV" for ch in channels}
    assignments = {}
    for region, region_channels in _country_regions(channels):
        label = _country_region_label(region) or "Other Countries"
        for ch in region_channels:
            assignments[id(ch)] = label
    return assignments


def _sports_pvr_special_group_for(ch):
    sport_group = ch.get("sport_group")
    if sport_group == "events_ppv":
        return "Events / PPV"
    if sport_group == "sports_news":
        return "Sports News"
    return ""


def _sports_pvr_sort_group_key(label):
    text = str(label or "")
    for pfx in SPORTS_LEGACY_PREFIXES:
        if text.startswith(pfx):
            text = text[len(pfx):]
            break

    special_order = {
        "Events / PPV": 0,
        "Sports News": 1,
    }
    if text in special_order:
        return (0, special_order[text], _natural_key(text))

    if text == "Other Countries":
        return (2, 0, _natural_key(text))

    return (1, 0, _natural_key(text))


def sports_pvr_channels_for_profile(profile_num, group_mode="Countries / Regions"):
    channels = _fetch_profile_channels(profile_num)
    group_assignments = _pvr_group_assignments(channels, group_mode)

    def _provider_order_value(ch):
        try:
            return int(ch.get("_provider_order", 999999999))
        except Exception:
            return 999999999

    out = []
    for ch in channels:
        special_group = _sports_pvr_special_group_for(ch)
        assigned = special_group or group_assignments.get(id(ch)) or "Other Countries"
        pvr_group = assigned
        out.append({
            "name": ch.get("name", "Unknown"),
            "url": ch.get("url", ""),
            "tvg_id": ch.get("tvg_id", ""),
            "epg_channel_id": ch.get("epg_channel_id", ""),
            "logo": ch.get("logo", ""),
            "group": pvr_group,
            "_provider_order": _provider_order_value(ch),
            "stream_type": ch.get("raw", {}).get("stream_type", ""),
            "radio": ch.get("raw", {}).get("radio", ""),
            "catchup": ch.get("catchup", ""),
            "catchup_source": ch.get("catchup_source", ""),
            "catchup_days": ch.get("catchup_days", ""),
            "catchup_correction": ch.get("raw", {}).get("catchup_correction", ""),
            "stream_id": ch.get("stream_id", ""),
            "source_type": ch.get("source_type", ""),
            "provider_group": ch.get("provider_group", ""),
            "sport_group": ch.get("sport_group", ""),
            "country_region": ch.get("country_region", ""),
            "profile_num": ch.get("profile_num", ""),
            "raw": ch.get("raw", {}),
        })

    out.sort(key=lambda ch: (
        _sports_pvr_sort_group_key(ch.get("group", "")),
        _provider_order_value(ch),
        _natural_key(ch.get("profile_num", "")),
        _natural_key(ch.get("name", "")),
    ))
    return out


def _provider_groups(channels):
    groups = {}
    for ch in channels:
        group = ch.get("provider_group") or "General"
        groups.setdefault(group, []).append(ch)
    return sorted(groups.items(), key=lambda item: _natural_key(item[0]))


def _country_regions(channels):
    groups = {}
    for ch in channels:
        region = ch.get("country_region") or OTHER_COUNTRIES_KEY
        groups.setdefault(region, []).append(ch)

    visible = {}
    other = []
    for region, region_channels in groups.items():
        if region == OTHER_COUNTRIES_KEY or len(region_channels) < MIN_COUNTRY_GROUP_SIZE:
            other.extend(region_channels)
        else:
            visible[region] = region_channels
    if other:
        visible[OTHER_COUNTRIES_KEY] = other
    return sorted(visible.items(), key=lambda item: _country_region_sort_label(item[0]))


def _country_region_filter(channels, region):
    if region != OTHER_COUNTRIES_KEY:
        return [ch for ch in channels if ch.get("country_region") == region]
    groups = {}
    for ch in channels:
        key = ch.get("country_region") or OTHER_COUNTRIES_KEY
        groups.setdefault(key, []).append(ch)
    small_regions = set()
    for key, region_channels in groups.items():
        if key == OTHER_COUNTRIES_KEY or len(region_channels) < MIN_COUNTRY_GROUP_SIZE:
            small_regions.add(key)
    return [ch for ch in channels if (ch.get("country_region") or OTHER_COUNTRIES_KEY) in small_regions]


def _channel_sort_key(ch):
    return (
        _country_region_sort_label(ch.get("country_region") or ""),
        _natural_key(ch.get("provider_group", "")),
        _natural_key(ch.get("name", "")),
        _natural_key(ch.get("profile_num", "")),
    )


def _page_items(items, page):
    page = max(1, int(page or 1))
    page_size = _sports_page_size()
    if page_size <= 0:
        return items, False
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], end < len(items)


def _sports_epg_enabled():
    return (c("addon").getSetting("show_epg_sports") or "true").lower() == "true"


def _sports_epg_for_channels(channels):
    if not channels or not _sports_epg_enabled():
        return {}
    epg_cls = _CTX.get("EPG")
    if not epg_cls or not _CTX.get("_make_epg_info"):
        return {}
    fallback_fn = _CTX.get("_apply_epg_fallback_from_other_profiles")
    epg_by_profile = {}
    profile_nums = sorted({str(ch.get("profile_num") or "") for ch in channels if ch.get("profile_num")})
    for pnum in profile_nums:
        try:
            epg = epg_cls(c("addon"), profile_num=pnum)
            epg.load()
            if getattr(epg, "is_refreshing", False):
                c("_log")("EPG background refresh in progress - showing cached/stale data")
            if not epg.programs:
                c("_log")("Sports EPG: profile {0} has no programmes after load".format(pnum))
            if fallback_fn:
                p_channels = [ch for ch in channels if str(ch.get("profile_num") or "") == pnum]
                fallback_targets = [
                    {
                        "tvg_id": ch.get("tvg_id") or ch.get("url") or ch.get("name", ""),
                        "name": ch.get("name", ""),
                        "group": ch.get("provider_group") or ch.get("sport_group") or ch.get("group") or "",
                    }
                    for ch in p_channels
                ]
                fallback_fn(
                    epg,
                    pnum,
                    fallback_targets,
                    target_id_key="tvg_id",
                    target_name_key="name",
                    log_prefix="Sports EPG UI",
                )
            if not epg.programs:
                continue
            epg_by_profile[pnum] = epg
        except Exception as exc:
            try:
                c("_log")("Sports EPG load failed for profile {0}: {1}".format(pnum, exc))
            except Exception:
                pass
    return epg_by_profile


def _sports_epg_aliases_for_channels(channels, epg_by_profile):
    builder = _CTX.get("_build_same_group_epg_aliases")
    if not builder or not channels or not epg_by_profile:
        return {}

    aliases_by_profile = {}
    for pnum, epg in epg_by_profile.items():
        profile_channels = [
            ch for ch in channels
            if str(ch.get("profile_num") or "") == str(pnum)
        ]
        if not profile_channels:
            continue
        fallback_group = ""
        for ch in profile_channels:
            g = ch.get("provider_group") or ch.get("sport_group") or ""
            if g:
                fallback_group = g
                break
        try:
            aliases_by_profile[str(pnum)] = builder(profile_channels, epg, fallback_group)
        except Exception as exc:
            try:
                c("_log")("Sports EPG same-group alias build failed for profile {0}: {1}".format(pnum, exc))
            except Exception:
                pass
    return aliases_by_profile


def _merge_epg_plot(epg_plot, sports_plot):
    if epg_plot and sports_plot:
        return "{0}\n\n{1}".format(epg_plot, sports_plot)
    return epg_plot or sports_plot


def _playable_item(ch, show_profile=True, epg=None, epg_aliases=None):
    name = ch.get("name", "Unknown")
    label = name
    current_title = ""
    epg_plot = ""
    if epg is not None:
        try:
            epg_id = str(ch.get("tvg_id", "") or "")
            if epg_aliases:
                epg_id = epg_aliases.get(epg_id, epg_id)
            epg_plot, label, current_title = c("_make_epg_info")(epg, epg_id, name)
        except Exception as exc:
            try:
                c("_log")("Sports EPG render failed for {0}: {1}".format(name, exc))
            except Exception:
                pass
    if show_profile:
        label = "{0} [COLOR gray]({1})[/COLOR]".format(label, ch.get("profile_name") or _t(30390, ch.get("profile_num")))
    li = c("_new_listitem")(label)
    logo = ch.get("logo") or c("_local_icon")("live_tv")
    li.setArt({"icon": logo, "thumb": logo})
    info = li.getVideoInfoTag()
    info.setMediaType("video")
    info.setTitle(current_title or name)
    sports_plot = "{0}\n{1}".format(ch.get("provider_group", ""), _sport_group_label(ch.get("sport_group"))).strip()
    info.setPlot(_merge_epg_plot(epg_plot, sports_plot))
    li.setProperty("IsPlayable", "true")
    li.setProperty("IsLiveTV", "1")
    li.setProperty("previewpath", ch.get("url", ""))
    c("_prepare_playback_item")(li)
    c("_set_live_props")(li)
    try:
        ctx = c("_build_favorite_ctx")(
            ch.get("stream_id", ""),
            ch.get("name", "Unknown"),
            "live",
            logo,
            ch.get("url", ""),
            epg_id=ch.get("tvg_id", ""),
            catchup=ch.get("catchup", ""),
            catchup_source=ch.get("catchup_source", ""),
            catchup_days=ch.get("catchup_days", ""),
            profile_num=ch.get("profile_num"),
        )
        li.addContextMenuItems(ctx)
    except Exception:
        pass
    url = c("build_url")({
        "mode": "play_stream",
        "url": ch.get("url", ""),
        "name": ch.get("name", "Unknown"),
        "title": current_title or ch.get("name", "Unknown"),
        "icon": logo,
        "profile_num": ch.get("profile_num", ""),
    })
    return url, li, False


def _pvr_label(label):
    profile_num = _active_sports_pvr_profile()
    scope_fn = c("_current_pvr_instance_scope")
    current = scope_fn() if scope_fn else "none"
    if current == "sports":
        color = "green"
    elif current == "mixed":
        color = "yellow"
    else:
        color = "red"
    dot = "[COLOR {0}]\u25cf[/COLOR]".format(color)
    return "{0} {1} ({2})".format(dot, label, profile_num)


def sports_menu():
    enabled_fn = c("_owned_pvr_instance_enabled")
    sports_guide_on = bool(enabled_fn and enabled_fn("sports"))
    guide_label = "Sports TV - Guide" if sports_guide_on else "[COLOR dimgray]Sports TV - Guide[/COLOR]"
    guide_mode = "sports_open_pvr_guide" if sports_guide_on else "pvr_not_active"
    items = [
        _action(_pvr_label("Sports TV - PVR"), {"mode": "sports_open_pvr"}, "live_tv_pvr"),
        _action(guide_label, {"mode": guide_mode}, "guide"),
        _folder("Sports Replay", {"mode": "sports_replay"}, "in_progress"),
        _folder("Events / PPV", {"mode": "sports_events_ppv"}, "highest_revenue"),
        _folder("Sports News", {"mode": "sports_news"}, "live_tv_pvr"),
        _folder("Results & Scores", {"mode": "sports_results_menu"}, "scores"),
        _folder("Search Sports", {"mode": "sports_search_menu"}, "search"),
        _folder("Sports Favorites", {"mode": "sports_favorites"}, "favorites"),
        _folder("Sports TV Profiles", {"mode": "sports_profiles"}, "profiles"),
        _folder("Sports Tools", {"mode": "sports_tools"}, "tools"),
    ]
    _end(items)


def sports_profiles_menu():
    items = [
        _folder("All Profiles", {"mode": "sports_profile", "scope": "all"}, "profiles")
    ]
    active = _active_sports_pvr_profile()
    for pnum, name in _enabled_profiles():
        label = name
        if str(pnum) == str(active):
            label = ACTIVE_DOT + label
        items.append(_folder(label, {"mode": "sports_profile", "scope": "profile", "profile_num": pnum}, "profiles"))
    _end(items)


def _special_sports_group_menu(group_key, icon="live_tv"):
    profiles = _enabled_profiles()
    if len(profiles) == 1:
        pnum, _name = profiles[0]
        sports_channels({
            "scope": ["profile"],
            "profile_num": [str(pnum)],
            "group": [group_key],
            "page": ["1"],
        })
        return

    if not profiles:
        _empty(_t(30067))
        return

    items = [
        _folder(
            "All Profiles",
            {"mode": "sports_channels", "scope": "all", "group": group_key, "page": "1"},
            icon,
        )
    ]
    active = _active_sports_pvr_profile()
    for pnum, name in profiles:
        label = name
        if str(pnum) == str(active):
            label = ACTIVE_DOT + label
        items.append(
            _folder(
                label,
                {
                    "mode": "sports_channels",
                    "scope": "profile",
                    "profile_num": str(pnum),
                    "group": group_key,
                    "page": "1",
                },
                icon,
            )
        )
    _end(items)


def sports_events_ppv_menu():
    _special_sports_group_menu("events_ppv", "highest_revenue")


def sports_news_menu():
    _special_sports_group_menu("sports_news", "live_tv")


def sports_profile_menu(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    base = {"scope": scope}
    if scope != "all":
        base["profile_num"] = profile_num
    items = [
        _folder("Provider Sport Groups", dict(base, mode="sports_provider_groups"), "providers"),
        _folder("Countries / Regions", dict(base, mode="sports_countries"), "providers"),
        _folder("All Sports Channels", dict(base, mode="sports_channels", group="all", page="1"), "live_tv"),
        _folder("Events / PPV", dict(base, mode="sports_channels", group="events_ppv", page="1"), "live_tv"),
        _folder("Sports News", dict(base, mode="sports_channels", group="sports_news", page="1"), "live_tv"),
    ]
    _end(items)


def sports_profiles_by_profile():
    items = []
    active = _active_sports_pvr_profile()
    for pnum, name in _enabled_profiles():
        label = name
        if str(pnum) == str(active):
            label = ACTIVE_DOT + label
        items.append(_folder(label, {"mode": "sports_profile", "scope": "profile", "profile_num": pnum}, "profiles"))
    _end(items)


def sports_provider_groups(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    channels = _fetch_scope_channels(scope, profile_num)
    base = {"scope": scope}
    if scope != "all":
        base["profile_num"] = profile_num
    items = []
    for group_name, group_channels in _provider_groups(channels):
        label = "{0} [COLOR gray]({1})[/COLOR]".format(group_name, len(group_channels))
        items.append(
            _folder(label, dict(base, mode="sports_channels", provider_group=group_name, page="1"), "providers")
        )
    if not items:
        _empty(_t(30074))
        return
    _end(items)


def sports_countries(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    channels = _fetch_scope_channels(scope, profile_num)
    base = {"scope": scope}
    if scope != "all":
        base["profile_num"] = profile_num
    items = []
    for region, region_channels in _country_regions(channels):
        label = "{0} [COLOR gray]({1})[/COLOR]".format(_country_region_label(region), len(region_channels))
        items.append(_folder(label, dict(base, mode="sports_channels", country_region=region, page="1"), "providers"))
    if not items:
        _empty(_t(30074))
        return
    _end(items)


def sports_channels(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    group_key = params.get("group", ["all"])[0]
    provider_group = params.get("provider_group", [""])[0]
    country_region = params.get("country_region", [""])[0]
    page = int(params.get("page", ["1"])[0] or 1)
    channels = _fetch_scope_channels(scope, profile_num)
    if country_region:
        channels = _country_region_filter(channels, country_region)
    elif provider_group:
        channels = [ch for ch in channels if ch.get("provider_group") == provider_group]
    elif group_key and group_key != "all":
        channels = [ch for ch in channels if ch.get("sport_group") == group_key]
    channels.sort(key=_channel_sort_key)
    page_channels, has_next = _page_items(channels, page)
    epg_by_profile = _sports_epg_for_channels(page_channels)
    epg_aliases_by_profile = _sports_epg_aliases_for_channels(channels, epg_by_profile)
    items = [
        _playable_item(
            ch,
            show_profile=(scope == "all"),
            epg=epg_by_profile.get(str(ch.get("profile_num") or "")),
            epg_aliases=epg_aliases_by_profile.get(str(ch.get("profile_num") or "")),
        )
        for ch in page_channels
    ]
    if has_next:
        q = dict(params)
        q["mode"] = ["sports_channels"]
        q["page"] = [str(page + 1)]
        flat_q = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
        items.append(_folder(_t(30232), flat_q, "next"))
    if not items:
        _empty(_t(30068))
        return
    _end(items, "livetv")


def sports_replay_menu():
    items = [_folder("All Profiles", {"mode": "sports_replay_profile", "scope": "all"}, "in_progress")]
    active = _active_sports_pvr_profile()
    for pnum, name in _enabled_profiles():
        label = name
        if str(pnum) == str(active):
            label = ACTIVE_DOT + label
        items.append(_folder(label, {"mode": "sports_replay_profile", "scope": "profile", "profile_num": pnum}, "in_progress"))
    _end(items)


def sports_replay_profile(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    base = {"scope": scope}
    if scope != "all":
        base["profile_num"] = profile_num
    items = [
        _folder("Provider Sport Groups", dict(base, mode="sports_replay_provider_groups"), "providers"),
        _folder("Countries / Regions", dict(base, mode="sports_replay_countries"), "providers"),
        _folder("All Sports Replay Channels", dict(base, mode="sports_replay_channels", group="all", page="1"), "in_progress"),
        _folder("Events / PPV", dict(base, mode="sports_replay_channels", group="events_ppv", page="1"), "in_progress"),
        _folder("Sports News", dict(base, mode="sports_replay_channels", group="sports_news", page="1"), "in_progress"),
    ]
    _end(items)


def sports_replay_provider_groups(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    channels = [
        ch for ch in _fetch_scope_channels(scope, profile_num, include_replay_meta=True)
        if ch.get("catchup") or ch.get("catchup_source") or ch.get("catchup_days")
    ]
    base = {"scope": scope}
    if scope != "all":
        base["profile_num"] = profile_num
    items = []
    for group_name, group_channels in _provider_groups(channels):
        label = "{0} [COLOR gray]({1})[/COLOR]".format(group_name, len(group_channels))
        items.append(_folder(label, dict(base, mode="sports_replay_channels", provider_group=group_name, page="1"), "providers"))
    if not items:
        _empty(_t(30074))
        return
    _end(items)


def sports_replay_countries(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    channels = [
        ch for ch in _fetch_scope_channels(scope, profile_num, include_replay_meta=True)
        if ch.get("catchup") or ch.get("catchup_source") or ch.get("catchup_days")
    ]
    base = {"scope": scope}
    if scope != "all":
        base["profile_num"] = profile_num
    items = []
    for region, region_channels in _country_regions(channels):
        label = "{0} [COLOR gray]({1})[/COLOR]".format(_country_region_label(region), len(region_channels))
        items.append(_folder(label, dict(base, mode="sports_replay_channels", country_region=region, page="1"), "providers"))
    if not items:
        _empty(_t(30074))
        return
    _end(items)


def sports_replay_channels(params):
    scope = params.get("scope", ["profile"])[0]
    profile_num = params.get("profile_num", [_active_pvr_profile()])[0]
    group_key = params.get("group", ["all"])[0]
    provider_group = params.get("provider_group", [""])[0]
    country_region = params.get("country_region", [""])[0]
    page = int(params.get("page", ["1"])[0] or 1)
    channels = [
        ch for ch in _fetch_scope_channels(scope, profile_num, include_replay_meta=True)
        if ch.get("catchup") or ch.get("catchup_source") or ch.get("catchup_days")
    ]
    if country_region:
        channels = _country_region_filter(channels, country_region)
    elif provider_group:
        channels = [ch for ch in channels if ch.get("provider_group") == provider_group]
    elif group_key and group_key != "all":
        channels = [ch for ch in channels if ch.get("sport_group") == group_key]
    channels.sort(key=_channel_sort_key)
    page_channels, has_next = _page_items(channels, page)
    items = []
    for ch in page_channels:
        label = ch.get("name", "Unknown")
        if scope == "all":
            label = "{0} [COLOR gray]({1})[/COLOR]".format(label, ch.get("profile_name", ""))
        li = c("_new_listitem")(label)
        logo = ch.get("logo") or c("_local_icon")("in_progress")
        li.setArt({"icon": logo, "thumb": logo})
        if ch.get("source_type") == "xtream":
            url = c("build_url")({
                "mode": "replay_channel",
                "stream_id": ch.get("stream_id", ""),
                "epg_id": ch.get("tvg_id", ""),
                "name": ch.get("name", ""),
                "profile_num": ch.get("profile_num", ""),
            })
        else:
            url = c("build_url")({
                "mode": "replay_channel_m3u",
                "channel_name": ch.get("name", ""),
                "epg_id": ch.get("tvg_id", ""),
                "channel_url": ch.get("url", ""),
                "catchup": ch.get("catchup", ""),
                "catchup_source": ch.get("catchup_source", ""),
                "logo": ch.get("logo", ""),
                "profile_num": ch.get("profile_num", ""),
            })
        items.append((url, li, True))
    if has_next:
        q = dict(params)
        q["mode"] = ["sports_replay_channels"]
        q["page"] = [str(page + 1)]
        flat_q = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
        items.append(_folder(_t(30232), flat_q, "next"))
    if not items:
        _empty(_t(30068))
        return
    _end(items, "livetv")


def sports_search_menu():
    items = [
        _folder("Search Sports Channels", {"mode": "sports_search", "scope": "all", "prompt": "true"}, "search"),
        _folder("Search Sports Replay", {"mode": "sports_search", "scope": "all", "replay": "true", "prompt": "true"}, "search"),
    ]
    _end(items)


def _sports_search_history_path(replay_only=False):
    profile = xbmcvfs.translatePath(c("addon").getAddonInfo("profile"))
    suffix = "replay" if replay_only else "channels"
    return os.path.join(profile, "sports_search_history_{0}.json".format(suffix))


def _sports_load_search_history(replay_only=False):
    try:
        with open(_sports_search_history_path(replay_only), "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _sports_save_search_history(history, replay_only=False):
    path = _sports_search_history_path(replay_only)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(history[:10], handle, ensure_ascii=False)
    os.replace(tmp, path)


def _sports_update_search_history(query, replay_only=False):
    if not query:
        return
    history = _sports_load_search_history(replay_only)
    if query in history:
        history.remove(query)
    history.insert(0, query)
    _sports_save_search_history(history, replay_only)


def _sports_search_history_menu(params, replay_only=False):
    history = _sports_load_search_history(replay_only)
    base = {k: (v[0] if isinstance(v, list) else v) for k, v in params.items()}
    base.pop("prompt", None)
    base["new_search"] = "true"
    items = [_folder(_t(31252), base, "search")]
    for entry in history:
        q = dict(base)
        q.pop("new_search", None)
        q["query"] = entry
        items.append(_folder(entry, q, "search"))
    _end(items)


def sports_search(params):
    query = params.get("query", [""])[0].strip()
    replay_only = params.get("replay", ["false"])[0] == "true"
    if params.get("new_search", ["false"])[0] == "true":
        query = xbmcgui.Dialog().input("Search Sports")
        if not query:
            xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
            return
        _sports_update_search_history(query, replay_only)
    elif params.get("prompt", ["false"])[0] == "true" and not query:
        _sports_search_history_menu(params, replay_only)
        return
    if not query:
        xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=False)
        return
    _sports_update_search_history(query, replay_only)
    channels = _fetch_scope_channels("all", include_replay_meta=replay_only)
    needle = _norm(query)
    out = []
    for ch in channels:
        text = _norm("{0} {1} {2} {3}".format(
            ch.get("name", ""),
            ch.get("provider_group", ""),
            ch.get("profile_name", ""),
            _sport_group_label(ch.get("sport_group")),
        ))
        if needle in text:
            if replay_only and not (ch.get("catchup") or ch.get("catchup_source") or ch.get("catchup_days")):
                continue
            out.append(ch)
    out.sort(key=_channel_sort_key)
    page = int(params.get("page", ["1"])[0] or 1)
    page_channels, has_next = _page_items(out, page)
    if replay_only:
        items = []
        for ch in page_channels:
            li = c("_new_listitem")("{0} [COLOR gray]({1})[/COLOR]".format(ch.get("name", "Unknown"), ch.get("profile_name", "")))
            logo = ch.get("logo") or c("_local_icon")("in_progress")
            li.setArt({"icon": logo, "thumb": logo})
            url = c("build_url")({
                "mode": "replay_channel" if ch.get("source_type") == "xtream" else "replay_channel_m3u",
                "stream_id": ch.get("stream_id", ""),
                "epg_id": ch.get("tvg_id", ""),
                "name": ch.get("name", ""),
                "channel_name": ch.get("name", ""),
                "channel_url": ch.get("url", ""),
                "catchup": ch.get("catchup", ""),
                "catchup_source": ch.get("catchup_source", ""),
                "logo": ch.get("logo", ""),
                "profile_num": ch.get("profile_num", ""),
            })
            items.append((url, li, True))
    else:
        epg_by_profile = _sports_epg_for_channels(page_channels)
        epg_aliases_by_profile = _sports_epg_aliases_for_channels(page_channels, epg_by_profile)
        items = [
            _playable_item(
                ch,
                show_profile=True,
                epg=epg_by_profile.get(str(ch.get("profile_num") or "")),
                epg_aliases=epg_aliases_by_profile.get(str(ch.get("profile_num") or "")),
            )
            for ch in page_channels
        ]
    if has_next:
        items.append(_folder(_t(30232), {
            "mode": "sports_search",
            "query": query,
            "scope": "all",
            "replay": "true" if replay_only else "false",
            "page": str(page + 1),
        }, "next"))
    if not items:
        _empty(_t(30223))
        return
    _end(items, "livetv")


def sports_favorites():
    items = [
        _folder("Favorite Sports Groups", {"mode": "favorites_menu"}, "favorites"),
        _folder("Sports PVR Favorites Manager", {"mode": "sports_pvr_favorites_manager"}, "favorites"),
    ]
    _end(items)


def sports_pvr_status():
    profile_num = _active_sports_pvr_profile()
    profile_name = _profile_name(profile_num)

    lines = [
        "Sports PVR profile: {0}".format(profile_name),
        "Sports page size: {0}".format(_sports_page_size()),
    ]

    try:
        lines.append("Sports detection level: {0}".format(c("addon").getSetting("sports_detection_level") or "Normal"))
    except Exception:
        lines.append("Sports detection level: Normal")

    try:
        lines.append("Sports group mode: {0}".format(c("addon").getSetting("sports_pvr_group_mode") or "Countries / Regions"))
    except Exception:
        lines.append("Sports group mode: Countries / Regions")

    try:
        pvr_path = c("_sports_pvr_m3u_path")()
        pvr_ready = c("_m3u_file_has_channels")(pvr_path)
        lines.append("Sports PVR file: {0}".format(pvr_path))
        lines.append("Sports PVR has channels: {0}".format("Yes" if pvr_ready else "No"))
    except Exception as exc:
        lines.append("Sports PVR status check failed: {0}".format(exc))

    try:
        detected_count = len(_fetch_profile_channels(profile_num))
        lines.append("Detected sports channels on Sports PVR profile: {0}".format(detected_count))
    except Exception as exc:
        lines.append("Detected channel count failed: {0}".format(exc))

    xbmcgui.Dialog().textviewer("Sports PVR Status", "\n".join(lines))


def sports_review_detected(params):
    try:
        page = max(1, int(params.get("page", ["1"])[0] or 1))
    except Exception:
        page = 1

    channels = _fetch_scope_channels("all", "")
    channels.sort(key=_channel_sort_key)

    page_channels, has_next = _page_items(channels, page)

    items = [
        _playable_item(ch, show_profile=True)
        for ch in page_channels
    ]

    if has_next:
        items.append(_folder(
            _t(30232),
            {
                "mode": "sports_review_detected",
                "page": str(page + 1),
            },
            "next",
        ))

    if not items:
        _empty(_t(30068))
        return

    _end(items, "livetv")


def sports_clear_cache():
    if not xbmcgui.Dialog().yesno(_t(31675), _t(31669)):
        return

    removed = _clear_sports_processed_cache()
    xbmcgui.Dialog().notification(
        "Xstream Pro",
        "Cleared {0} Sports cache file(s).".format(removed),
        xbmcgui.NOTIFICATION_INFO,
        4000,
    )


def sports_tools():
    items = [
        _action("Open Add-on Settings", {"mode": "settings"}, "settings"),
        _folder("Change Sports PVR Profile", {"mode": "switch_sports_pvr_profile"}, "profiles"),
        _action(_t(31532), {"mode": "sync_sports_pvr"}, "live_tv_pvr"),
        _action("Reload Sports Profiles", {"mode": "sports_refresh_profile_menu"}, "reset_reload"),
        _action("Sports Loaded Profiles", {"mode": "sports_loaded_profiles"}, "profiles"),
        _action("Sports PVR Status", {"mode": "sports_pvr_status"}, "live_tv_pvr"),
        _folder("Manage Detected Channels", {"mode": "sports_manage_detected_channels"}, "tools"),
        _action("Clear Sports Cache", {"mode": "sports_clear_cache"}, "tools"),
    ]
    _end(items)


def sports_manage_detected_channels():
    items = [
        _folder("Review Detected Channels", {"mode": "sports_manage_detected_review_countries"}, "live_tv"),
        _folder("Add Channels", {"mode": "sports_manage_detected_add_countries"}, "add"),
        _folder("Remove Channels", {"mode": "sports_manage_detected_remove_countries"}, "remove"),
    ]
    _end(items)


def _manage_country_menu(mode_name, detected=True):
    scope = "all"
    if detected:
        channels = _fetch_scope_channels(scope, "")
    else:
        overrides = _load_sports_overrides()
        detected_ids = set(_sports_channel_override_id(ch) for ch in _fetch_scope_channels(scope, ""))
        channels = []
        for ch in _fetch_scope_all_live_candidates(scope, ""):
            oid = _sports_channel_override_id(ch)
            if oid in detected_ids:
                continue
            if oid in (overrides.get("exclude") or {}):
                continue
            channels.append(ch)
    items = []
    for region, region_channels in _country_regions(channels):
        label = "{0} [COLOR gray]({1})[/COLOR]".format(_country_region_label(region), len(region_channels))
        items.append(_folder(label, {"mode": mode_name, "country_region": region, "page": "1"}, "providers"))
    if not items:
        _empty(_t(30223))
        return
    _end(items)


def sports_manage_detected_review_countries():
    _manage_country_menu("sports_manage_detected_review_channels", detected=True)


def sports_manage_detected_add_countries():
    _manage_country_menu("sports_manage_detected_add_channels", detected=False)


def sports_manage_detected_remove_countries():
    _manage_country_menu("sports_manage_detected_remove_channels", detected=True)


def _manage_detected_channel_rows(channels, country_region, page, action_mode):
    if country_region:
        channels = _country_region_filter(channels, country_region)
    channels.sort(key=_channel_sort_key)
    page_items, has_next = _page_items(channels, page)
    items = []
    for ch in page_items:
        label = "{0} [COLOR gray]({1} / {2})[/COLOR]".format(
            ch.get("name", "Unknown"),
            ch.get("profile_name", ""),
            ch.get("provider_group", ""),
        )
        params = {
            "mode": action_mode,
            "profile_num": ch.get("profile_num", ""),
            "source_type": ch.get("source_type", ""),
            "stream_id": ch.get("stream_id", ""),
            "tvg_id": ch.get("tvg_id", ""),
            "name": ch.get("name", ""),
            "provider_group": ch.get("provider_group", ""),
            "country_region": ch.get("country_region", ""),
        }
        items.append(_action(label, params, "live_tv"))
    if has_next:
        items.append(_folder(_t(30232), {
            "mode": {
                "sports_manage_detected_review_action": "sports_manage_detected_review_channels",
                "sports_manage_detected_add_action": "sports_manage_detected_add_channels",
                "sports_manage_detected_remove_action": "sports_manage_detected_remove_channels",
            }.get(action_mode, "sports_manage_detected_review_channels"),
            "country_region": country_region,
            "page": str(page + 1),
        }, "next"))
    if not items:
        _empty(_t(30223))
        return
    _end(items, "livetv")


def sports_manage_detected_review_channels(params):
    country_region = params.get("country_region", [""])[0]
    page = int(params.get("page", ["1"])[0] or 1)
    channels = _fetch_scope_channels("all", "")
    _manage_detected_channel_rows(channels, country_region, page, "sports_manage_detected_review_action")


def sports_manage_detected_add_channels(params):
    country_region = params.get("country_region", [""])[0]
    page = int(params.get("page", ["1"])[0] or 1)
    overrides = _load_sports_overrides()
    detected_ids = set(_sports_channel_override_id(ch) for ch in _fetch_scope_channels("all", ""))
    channels = []
    for ch in _fetch_scope_all_live_candidates("all", ""):
        oid = _sports_channel_override_id(ch)
        if oid in detected_ids:
            continue
        if oid in (overrides.get("exclude") or {}):
            continue
        channels.append(ch)
    _manage_detected_channel_rows(channels, country_region, page, "sports_manage_detected_add_action")


def sports_manage_detected_remove_channels(params):
    country_region = params.get("country_region", [""])[0]
    page = int(params.get("page", ["1"])[0] or 1)
    channels = _fetch_scope_channels("all", "")
    _manage_detected_channel_rows(channels, country_region, page, "sports_manage_detected_remove_action")


def _channel_from_action_params(params):
    return {
        "profile_num": params.get("profile_num", [""])[0],
        "source_type": params.get("source_type", [""])[0],
        "stream_id": params.get("stream_id", [""])[0],
        "tvg_id": params.get("tvg_id", [""])[0],
        "name": params.get("name", [""])[0],
        "provider_group": params.get("provider_group", [""])[0],
        "country_region": params.get("country_region", [""])[0],
        "sport_group": "other_sports",
    }


def sports_manage_detected_review_action(params):
    choice = xbmcgui.Dialog().select(
        "Manage Detected Channel",
        ["Remove from Sports", "Cancel"],
    )
    if choice == 0:
        sports_manage_detected_remove_action(params)


def sports_manage_detected_add_action(params):
    ch = _channel_from_action_params(params)
    overrides = _load_sports_overrides()
    oid = _sports_channel_override_id(ch)
    overrides.setdefault("include", {})[oid] = _sports_channel_override_record(ch)
    overrides.setdefault("exclude", {}).pop(oid, None)
    _save_sports_overrides(overrides)
    xbmcgui.Dialog().notification("Xstream Pro", _t(31666))
    xbmc.executebuiltin("Container.Refresh")


def sports_manage_detected_remove_action(params):
    ch = _channel_from_action_params(params)
    if not xbmcgui.Dialog().yesno("Xstream Pro", _t(31668)):
        return
    overrides = _load_sports_overrides()
    oid = _sports_channel_override_id(ch)
    overrides.setdefault("exclude", {})[oid] = _sports_channel_override_record(ch)
    overrides.setdefault("include", {}).pop(oid, None)
    _save_sports_overrides(overrides)
    xbmcgui.Dialog().notification("Xstream Pro", _t(31667))
    xbmc.executebuiltin("Container.Refresh")


def sports_loaded_profiles():
    """Show Sports PVR and profile load status without fetching provider data."""
    items = []
    active = _active_sports_pvr_profile()

    try:
        pvr_path = c("_sports_pvr_m3u_path")()
        pvr_loaded = c("_m3u_file_has_channels")(pvr_path)
        pvr_status = "[COLOR green]{0}[/COLOR]".format(_t(30786)) if pvr_loaded else "[COLOR red]{0}[/COLOR]".format(_t(30787))
        items.append("{0} Sports PVR {1}".format(pvr_status, _profile_name(active)))
    except Exception as exc:
        try:
            c("_log")("Sports loaded profiles: Sports PVR status check failed: {0}".format(exc))
        except Exception:
            pass
        items.append("[COLOR red]{0}[/COLOR] Sports PVR {1}".format(_t(30787), _profile_name(active)))

    for n in range(1, 11):
        name = c("addon").getSetting("profile_{0}_name".format(n)) or _profile_name(n)
        has_creds = bool(
            c("addon").getSetting("profile_{0}_xtream_url".format(n))
            or c("addon").getSetting("profile_{0}_m3u".format(n))
        )
        marker = ACTIVE_DOT if str(n) == str(active) else ""

        if not has_creds:
            items.append("[COLOR grey]{0}{1} ({2})[/COLOR]".format(marker, name, _t(30864)))
            continue

        try:
            loaded = c("_profile_has_data")(n)
        except Exception as exc:
            try:
                c("_log")("Sports loaded profiles: profile {0} status check failed: {1}".format(n, exc))
            except Exception:
                pass
            loaded = False

        status = "[COLOR green]{0}[/COLOR]".format(_t(30786)) if loaded else "[COLOR red]{0}[/COLOR]".format(_t(30787))
        items.append("{0} {1}{2}".format(status, marker, name))

    xbmcgui.Dialog().select(_t(31673), items)


def open_pvr(params=None):
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)
    guard = _CTX.get("_pvr_open_guard")
    release = _CTX.get("_pvr_open_release")
    if guard and not guard("Sports PVR"):
        return
    try:
        pnum = _active_sports_pvr_profile()
        if not c("_prompt_profile_credentials")(pnum):
            return

        c("addon").setSetting("sports_pvr_enabled", "true")

        try:
            if not c("_sports_pvr_ready")():
                if not c("_sync_sports_pvr_safe")():
                    return
        except Exception as exc:
            try:
                c("_log")("Sports PVR: readiness check failed: {0}".format(exc))
            except Exception:
                pass

        if not c("_switch_pvr_instance_scope")("sports", "Sports PVR"):
            return

        ensure_runtime = _CTX.get("_ensure_pvr_runtime_channels")
        if ensure_runtime and not ensure_runtime(
            "Sports PVR",
            c("_sports_pvr_m3u_path")(),
            role="sports",
        ):
            return

        wait = _CTX.get("_wait_for_pvr_ready_before_window")
        if wait and not wait(
            "Sports PVR",
            timeout_seconds=35,
            show_progress=True,
            role="sports",
            m3u_path=c("_sports_pvr_m3u_path")(),
        ):
            return

        xbmc.sleep(c("_tvos_sleep")(500))
        activate = _CTX.get("_activate_pvr_window_with_last_group")
        if activate:
            activate("TVChannels", scope="sports", role="sports")
        else:
            xbmc.executebuiltin("ActivateWindow(TVChannels)")
    finally:
        if release:
            release()

def open_pvr_guide(params=None):
    xbmcplugin.endOfDirectory(c("addon_handle"), succeeded=True, updateListing=False, cacheToDisc=False)
    if not c("_owned_pvr_instance_enabled")("sports"):
        xbmcgui.Dialog().notification("Xstream Pro", c("_t")(30787), xbmcgui.NOTIFICATION_WARNING, 3000)
        return
    guard = _CTX.get("_pvr_open_guard")
    release = _CTX.get("_pvr_open_release")
    if guard and not guard("Sports PVR Guide"):
        return
    try:
        pnum = _active_sports_pvr_profile()
        if not c("_prompt_profile_credentials")(pnum):
            return

        c("addon").setSetting("sports_pvr_enabled", "true")

        try:
            if not c("_sports_pvr_ready")():
                if not c("_sync_sports_pvr_safe")():
                    return
        except Exception as exc:
            try:
                c("_log")("Sports PVR: readiness check failed: {0}".format(exc))
            except Exception:
                pass

        if not c("_switch_pvr_instance_scope")("sports", "Sports PVR Guide"):
            return

        ensure_runtime = _CTX.get("_ensure_pvr_runtime_channels")
        if ensure_runtime and not ensure_runtime(
            "Sports PVR Guide",
            c("_sports_pvr_m3u_path")(),
            role="sports",
        ):
            return

        wait = _CTX.get("_wait_for_pvr_ready_before_window")
        if wait and not wait(
            "Sports PVR Guide",
            timeout_seconds=35,
            show_progress=True,
            role="sports",
            m3u_path=c("_sports_pvr_m3u_path")(),
        ):
            return

        xbmc.sleep(c("_tvos_sleep")(500))
        activate = _CTX.get("_activate_pvr_window_with_last_group")
        if activate:
            activate("TVGuide", scope="sports", role="sports")
        else:
            xbmc.executebuiltin("ActivateWindow(TVGuide)")
    finally:
        if release:
            release()

