"""PVR export functions for Xstream Pro addon.

M3U and EPG export for Live TV PVR and Sports PVR instances.

Functions depend on addon (xbmcaddon.Addon) and several helpers from
addon.py (passed via init and lazy imports). Call init() after addon
module globals are available.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time
import traceback

import xbmc
import xbmcvfs

from pvr.constants import PVR_LIVE_GROUP_PREFIX, PVR_SPORTS_GROUP_PREFIX
from pvr.paths import (
    _pvr_m3u_path,
    _pvr_epg_path,
    _pvr_m3u_path_for_profile,
    _pvr_epg_path_for_profile,
    _sports_pvr_m3u_path,
    _sports_pvr_epg_path_for_profile,
    _get_pvr_profile_num,
    _get_sports_pvr_profile_num,
    _pvr_live_group_label,
    _strip_pvr_live_group_prefix,
)

_EPG_FALLBACK_VERSION = "2026-05-17-provider-cache-v3-expanded-aliases"

_addon = None
_log_fn = None
_pm = None
_safe_fsync_fn = None
_atomic_write_text_fn = None
_epg_file_has_data_fn = None
_epg_class = None
_epg_parse_xmltv_time_fn = None
_iptv_build_url_fn = None
_m3u_safe_fn = None
_build_m3u_content_fn = None
_get_hidden_subcats_fn = None
_get_hidden_items_fn = None
_is_adult_category_fn = None
_get_pvr_credentials_fn = None
_m3u_has_credentials_fn = None
_get_cached_m3u_channels_fn = None
_get_cached_xtream_streams_fn = None
_get_cached_xtream_categories_fn = None
_m3u_extinf_attr_fn = None
_get_pvr_catchup_correction_mode_fn = None
_catchup_correction_for_channel_fn = None
_sports_pvr_source_channels_fn = None
_apply_pvr_catchup_corrections_fn = None
_profile_has_epg_fallback_source_fn = None
_load_epg_for_fallback_profile_fn = None
_setup_sports_routes_fn = None
_sports_routes_module = None
_epg_exact_program_id_fn = None
_epg_fallback_source_targets_for_profile_fn = None
_epg_fallback_profile_state_signature_fn = None
_get_setting_direct_fn = None

_EPG_INSTANCE_CACHE = {}
_EPG_INSTANCE_CACHE_LOCK = threading.Lock()


def clear_epg_instance_cache():
    with _EPG_INSTANCE_CACHE_LOCK:
        _EPG_INSTANCE_CACHE.clear()


def get_cached_epg_for_profile(profile_num):
    with _EPG_INSTANCE_CACHE_LOCK:
        return _EPG_INSTANCE_CACHE.get(str(profile_num))


def _epg_instance_cache_put(profile_num, epg):
    with _EPG_INSTANCE_CACHE_LOCK:
        _EPG_INSTANCE_CACHE[str(profile_num)] = epg


def init(
    addon,
    log_fn,
    pm,
    safe_fsync_fn,
    atomic_write_text_fn,
    epg_file_has_data_fn,
    epg_class,
    epg_parse_xmltv_time_fn,
    iptv_build_url_fn,
    m3u_safe_fn,
    build_m3u_content_fn,
    get_hidden_subcats_fn,
    get_hidden_items_fn,
    is_adult_category_fn,
    get_pvr_credentials_fn,
    m3u_has_credentials_fn,
    get_cached_m3u_channels_fn,
    get_cached_xtream_streams_fn,
    get_cached_xtream_categories_fn,
    m3u_extinf_attr_fn,
    get_pvr_catchup_correction_mode_fn,
    catchup_correction_for_channel_fn,
    sports_pvr_source_channels_fn,
    apply_pvr_catchup_corrections_fn,
    profile_has_epg_fallback_source_fn,
    load_epg_for_fallback_profile_fn,
    setup_sports_routes_fn,
    sports_routes_module,
    epg_exact_program_id_fn,
    epg_fallback_source_targets_for_profile_fn,
    epg_fallback_profile_state_signature_fn,
    get_setting_direct_fn,
):
    global _addon, _log_fn, _pm, _safe_fsync_fn, _atomic_write_text_fn
    global _epg_file_has_data_fn, _epg_class, _epg_parse_xmltv_time_fn
    global _iptv_build_url_fn, _m3u_safe_fn, _build_m3u_content_fn
    global _get_hidden_subcats_fn, _get_hidden_items_fn, _is_adult_category_fn
    global _get_pvr_credentials_fn, _m3u_has_credentials_fn
    global _get_cached_m3u_channels_fn, _get_cached_xtream_streams_fn
    global _get_cached_xtream_categories_fn, _m3u_extinf_attr_fn
    global _get_pvr_catchup_correction_mode_fn, _catchup_correction_for_channel_fn
    global _sports_pvr_source_channels_fn, _apply_pvr_catchup_corrections_fn
    global _profile_has_epg_fallback_source_fn, _load_epg_for_fallback_profile_fn
    global _setup_sports_routes_fn, _sports_routes_module
    global _epg_exact_program_id_fn, _epg_fallback_source_targets_for_profile_fn
    global _epg_fallback_profile_state_signature_fn, _get_setting_direct_fn
    _addon = addon
    _log_fn = log_fn
    _pm = pm
    _safe_fsync_fn = safe_fsync_fn
    _atomic_write_text_fn = atomic_write_text_fn
    _epg_file_has_data_fn = epg_file_has_data_fn
    _epg_class = epg_class
    _epg_parse_xmltv_time_fn = epg_parse_xmltv_time_fn
    _iptv_build_url_fn = iptv_build_url_fn
    _m3u_safe_fn = m3u_safe_fn
    _build_m3u_content_fn = build_m3u_content_fn
    _get_hidden_subcats_fn = get_hidden_subcats_fn
    _get_hidden_items_fn = get_hidden_items_fn
    _is_adult_category_fn = is_adult_category_fn
    _get_pvr_credentials_fn = get_pvr_credentials_fn
    _m3u_has_credentials_fn = m3u_has_credentials_fn
    _get_cached_m3u_channels_fn = get_cached_m3u_channels_fn
    _get_cached_xtream_streams_fn = get_cached_xtream_streams_fn
    _get_cached_xtream_categories_fn = get_cached_xtream_categories_fn
    _m3u_extinf_attr_fn = m3u_extinf_attr_fn
    _get_pvr_catchup_correction_mode_fn = get_pvr_catchup_correction_mode_fn
    _catchup_correction_for_channel_fn = catchup_correction_for_channel_fn
    _sports_pvr_source_channels_fn = sports_pvr_source_channels_fn
    _apply_pvr_catchup_corrections_fn = apply_pvr_catchup_corrections_fn
    _profile_has_epg_fallback_source_fn = profile_has_epg_fallback_source_fn
    _load_epg_for_fallback_profile_fn = load_epg_for_fallback_profile_fn
    _setup_sports_routes_fn = setup_sports_routes_fn
    _sports_routes_module = sports_routes_module
    _epg_exact_program_id_fn = epg_exact_program_id_fn
    _epg_fallback_source_targets_for_profile_fn = epg_fallback_source_targets_for_profile_fn
    _epg_fallback_profile_state_signature_fn = epg_fallback_profile_state_signature_fn
    _get_setting_direct_fn = get_setting_direct_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _safe_replace(src, dst, retries=5, delay=0.5):
    for attempt in range(1, retries + 1):
        try:
            os.replace(src, dst)
            return
        except (PermissionError, OSError) as exc:
            if attempt < retries:
                _log(
                    "PVR EPG: file replace retry {0}/{1} for {2}: {3}".format(
                        attempt, retries, os.path.basename(dst), exc
                    )
                )
                time.sleep(delay * attempt)
            else:
                raise


def _unique_tmp_path(base_path):
    tid = threading.current_thread().ident
    return base_path + ".tmp." + str(tid)


def _t(string_id, *args):
    if _addon:
        try:
            result = _addon.getLocalizedString(string_id)
            return result.format(*args) if args and result else (result or "")
        except Exception:
            return str(string_id)
    return str(string_id)


_EPG_FALLBACK_NOISE_TOKENS = frozenset({
    "hd", "fhd", "uhd", "4k", "8k", "sd", "tv", "channel", "live",
    "stream", "free", "premium", "test", "backup", "hevc", "h265",
    "h264", "raw", "vip",
})
_EPG_FALLBACK_COUNTRY_ALIASES = {
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "us": "United States",
    "usa": "United States",
    "ca": "Canada",
    "au": "Australia",
    "nz": "New Zealand",
    "ie": "Ireland",
    "de": "Germany",
    "at": "Austria",
    "ch": "Switzerland",
    "fr": "France",
    "it": "Italy",
    "es": "Spain",
    "pt": "Portugal",
    "nl": "Netherlands",
    "be": "Belgium",
    "se": "Sweden",
    "no": "Norway",
    "dk": "Denmark",
    "fi": "Finland",
    "pl": "Poland",
    "cz": "Czech Republic",
    "tr": "Turkey",
    "gr": "Greece",
    "ro": "Romania",
    "hu": "Hungary",
    "bg": "Bulgaria",
    "hr": "Croatia",
    "rs": "Serbia",
    "si": "Slovenia",
    "sk": "Slovakia",
    "ua": "Ukraine",
    "ru": "Russia",
    "in": "India",
    "pk": "Pakistan",
    "bd": "Bangladesh",
    "lk": "Sri Lanka",
    "ph": "Philippines",
    "my": "Malaysia",
    "id": "Indonesia",
    "th": "Thailand",
    "vn": "Vietnam",
    "kr": "South Korea",
    "jp": "Japan",
    "cn": "China",
    "tw": "Taiwan",
    "hk": "Hong Kong",
    "sg": "Singapore",
    "il": "Israel",
    "ae": "UAE",
    "sa": "Saudi Arabia",
    "eg": "Egypt",
    "za": "South Africa",
    "ng": "Nigeria",
    "br": "Brazil",
    "ar": "Argentina",
    "mx": "Mexico",
    "co": "Colombia",
    "cl": "Chile",
    "pe": "Peru",
    "ve": "Venezuela",
    "ec": "Ecuador",
    "cu": "Cuba",
    "pa": "Panama",
    "do": "Dominican Republic",
    "ba": "Bosnia and Herzegovina",
    "bih": "Bosnia and Herzegovina",
    "hrv": "Croatia",
    "srb": "Serbia",
    "mk": "North Macedonia",
    "mkd": "North Macedonia",
    "mne": "Montenegro",
    "alb": "Albania",
    "al": "Albania",
    "xk": "Kosovo",
    "kos": "Kosovo",
    "svn": "Slovenia",
    "cze": "Czech Republic",
    "svk": "Slovakia",
    "rou": "Romania",
    "bgr": "Bulgaria",
    "hun": "Hungary",
    "grc": "Greece",
    "esp": "Spain",
    "ita": "Italy",
    "fra": "France",
    "deu": "Germany",
    "pol": "Poland",
    "nld": "Netherlands",
    "bel": "Belgium",
    "prt": "Portugal",
    "swe": "Sweden",
    "nor": "Norway",
    "dnk": "Denmark",
    "fin": "Finland",
    "aut": "Austria",
    "che": "Switzerland",
    "irl": "Ireland",
    "gbr": "United Kingdom",
    "tur": "Turkey",
    "ukr": "Ukraine",
}


_RE_FB_BRACKETS = re.compile(r"[\[\(].*?[\]\)]")
_RE_FB_NONALPHA = re.compile(r"[^a-zA-Z0-9\s]")
_RE_FB_SPACES = re.compile(r"\s+")


def _normalize_epg_fallback_name(name):
    if not name:
        return ""
    raw = _RE_FB_BRACKETS.sub("", name)
    raw = _RE_FB_NONALPHA.sub(" ", raw)
    raw = _RE_FB_SPACES.sub(" ", raw).strip().lower()
    return raw


def _epg_fallback_unique(values):
    seen = set()
    out = []
    for value in values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _epg_fallback_group_key(group):
    raw = _normalize_epg_fallback_name(_strip_pvr_live_group_prefix(group))
    tokens = []
    for token in raw.split():
        mapped_country = _EPG_FALLBACK_COUNTRY_ALIASES.get(token)
        if mapped_country:
            tokens.append(mapped_country)
            continue
        if token in _EPG_FALLBACK_NOISE_TOKENS:
            continue
        tokens.append(token)
    return " ".join(tokens)


def _epg_fallback_strict_share_key(name):
    raw = _normalize_epg_fallback_name(name)
    tokens = raw.split()
    if not tokens:
        return ""

    region = ""
    core_tokens = []
    for token in tokens:
        mapped_country = _EPG_FALLBACK_COUNTRY_ALIASES.get(token)
        if mapped_country:
            region = mapped_country
            continue
        if token in _EPG_FALLBACK_NOISE_TOKENS:
            continue
        core_tokens.append(token)

    if not region or len(core_tokens) < 2:
        return ""

    number = ""
    base_tokens = []
    for token in core_tokens:
        if not number and token.isdigit():
            number = token
            continue
        base_tokens.append(token)

    if not number or not base_tokens:
        return ""

    return "{0}|{1}|{2}".format(" ".join(base_tokens), number, region)


def _epg_fallback_match_keys(name, group=""):
    candidates = []
    values = [name]
    if group:
        values.append("{0} {1}".format(name, group))

    for value in values:
        raw = _normalize_epg_fallback_name(value)
        if len(raw) >= 3:
            candidates.append(raw)

        tokens = raw.split()
        if not tokens:
            continue

        country = ""
        core_tokens = []
        for token in tokens:
            mapped_country = _EPG_FALLBACK_COUNTRY_ALIASES.get(token)
            if mapped_country:
                country = mapped_country
                continue
            if token in _EPG_FALLBACK_NOISE_TOKENS:
                continue
            core_tokens.append(token)

        if len(core_tokens) < 2:
            continue

        core = " ".join(core_tokens)
        if country:
            candidates.append("{0} {1}".format(core, country))
            candidates.append("{0} {1}".format(country, core))
        candidates.append(core)

    return _epg_fallback_unique(candidates)


def _parse_pvr_m3u_epg_targets(m3u_path):
    targets = []
    if not os.path.exists(m3u_path):
        return targets
    try:
        with open(m3u_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.startswith("#EXTINF"):
                    continue
                tvg_id = _m3u_extinf_attr_fn(line, "tvg-id")
                if not tvg_id:
                    continue
                tvg_name = _m3u_extinf_attr_fn(line, "tvg-name")
                group = _m3u_extinf_attr_fn(line, "group-title")
                display_name = ""
                if "," in line:
                    display_name = line.split(",", 1)[1].strip()
                name = tvg_name or display_name or tvg_id
                targets.append(
                    {
                        "tvg_id": tvg_id,
                        "source_tvg_id": tvg_id,
                        "name": name,
                        "display_name": display_name,
                        "group": group,
                    }
                )
    except Exception as exc:
        _log(f"PVR EPG fallback: M3U target parse warning: {exc}")
    return targets


def _build_epg_fallback_name_index(epg):
    buckets = {}
    for channel_id, programmes in (getattr(epg, "programs", {}) or {}).items():
        if not programmes:
            continue
        display_name = (getattr(epg, "channel_names", {}) or {}).get(channel_id, "")
        keys = []
        keys.extend(_epg_fallback_match_keys(display_name))
        keys.extend(_epg_fallback_match_keys(channel_id))
        for key in _epg_fallback_unique(keys):
            if len(key) >= 3:
                buckets.setdefault(key, set()).add(channel_id)

    index = {}
    variant_index = {}
    ambiguous_keys = 0
    for key, ids in buckets.items():
        valid_ids = [
            channel_id
            for channel_id in ids
            if (getattr(epg, "programs", {}) or {}).get(channel_id)
        ]
        if len(valid_ids) == 1:
            index[key] = valid_ids[0]
        elif len(valid_ids) > 1:
            ambiguous_keys += 1
            variant_index[key] = max(
                valid_ids,
                key=lambda channel_id: len((getattr(epg, "programs", {}) or {}).get(channel_id) or []),
            )
    return index, variant_index, ambiguous_keys


def _build_epg_fallback_group_strict_index(profile_num, epg):
    buckets = {}
    for source in _epg_fallback_source_targets_for_profile_fn(profile_num):
        source_id = str(source.get("source_tvg_id") or source.get("tvg_id") or "").strip()
        source_name = str(source.get("name") or source.get("display_name") or source_id).strip()
        source_group = str(source.get("group") or "").strip()
        group_key = _epg_fallback_group_key(source_group)
        strict_key = _epg_fallback_strict_share_key(source_name)
        if not source_id or not group_key or not strict_key:
            continue

        matched_id = _epg_exact_program_id_fn(epg, source_id, source_name)
        if not matched_id:
            continue
        buckets.setdefault((group_key, strict_key), set()).add(matched_id)

    index = {}
    ambiguous = 0
    for key, ids in buckets.items():
        if len(ids) == 1:
            index[key] = next(iter(ids))
        elif len(ids) > 1:
            ambiguous += 1
    return index, ambiguous


def _pvr_epg_fallback_stamp_path(profile_num, scope="live"):
    profile_dir = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
    return os.path.join(
        profile_dir,
        "pvr_epg_fallback_{0}_p{1}.stamp".format(scope, profile_num),
    )


def _pvr_epg_fallback_signature(profile_num, scope="live"):
    enabled = _addon.getSetting("pvr_epg_fallback_enabled").lower() == "true"
    fallback_profiles = [
        str(i)
        for i in range(1, 11)
        if str(i) != str(profile_num) and _profile_has_epg_fallback_source_fn(i)
    ]
    profile_states = [str(profile_num)] + fallback_profiles
    state_signature = ",".join(
        _epg_fallback_profile_state_signature_fn(pnum) for pnum in profile_states
    )
    return "version={0};enabled={1};profile={2};scope={3};fallback_profiles={4};states={5}".format(
        _EPG_FALLBACK_VERSION,
        "1" if enabled else "0",
        profile_num,
        scope,
        ",".join(fallback_profiles),
        state_signature,
    )


def _pvr_epg_fallback_needs_rebuild(profile_num, scope="live"):
    if _addon.getSetting("pvr_epg_fallback_enabled").lower() != "true":
        return False
    stamp_path = _pvr_epg_fallback_stamp_path(profile_num, scope)
    signature = _pvr_epg_fallback_signature(profile_num, scope)
    try:
        if not os.path.exists(stamp_path):
            return True
        with open(stamp_path, "r", encoding="utf-8") as f:
            return f.read().strip() != signature
    except Exception:
        return True


def _pvr_epg_fallback_mark_built(profile_num, scope="live"):
    if _addon.getSetting("pvr_epg_fallback_enabled").lower() != "true":
        return
    stamp_path = _pvr_epg_fallback_stamp_path(profile_num, scope)
    try:
        os.makedirs(os.path.dirname(stamp_path), exist_ok=True)
        with open(stamp_path, "w", encoding="utf-8") as f:
            f.write(_pvr_epg_fallback_signature(profile_num, scope))
    except Exception as exc:
        _log(f"PVR EPG fallback: stamp write warning: {exc}")


def _live_pvr_alias_id(ch, profile_num, salt=""):
    stable = (
        ch.get("stream_id")
        or ch.get("url")
        or ch.get("source_tvg_id")
        or ch.get("tvg_id")
        or ch.get("name")
        or ""
    )
    raw = "live|{0}|{1}|{2}".format(profile_num, stable, salt)
    digest = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return "xstream-live-p{0}-{1}".format(profile_num, digest)


def _sports_pvr_alias_id(ch, profile_num, salt=""):
    stable = (
        ch.get("stream_id")
        or ch.get("url")
        or ch.get("source_tvg_id")
        or ch.get("tvg_id")
        or ch.get("name")
        or ""
    )
    raw = "sports|{0}|{1}|{2}".format(profile_num, stable, salt)
    digest = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return "xstream-sports-p{0}-{1}".format(profile_num, digest)


def _prepare_live_pvr_channels_for_export(channels, profile_num):
    seen_tvg_ids = {}
    prepared = []
    for index, ch in enumerate(channels or [], 1):
        item = dict(ch)
        item["group"] = PVR_LIVE_GROUP_PREFIX + _pvr_live_group_label(item.get("group") or "General")
        source_tvg_id = item.get("tvg_id") or ""
        item["source_tvg_id"] = source_tvg_id
        if source_tvg_id and source_tvg_id in seen_tvg_ids:
            item["tvg_id"] = _live_pvr_alias_id(item, profile_num, str(index))
        elif source_tvg_id:
            seen_tvg_ids[source_tvg_id] = index
        prepared.append(item)
    return prepared


def _prepare_sports_pvr_channels_for_export(channels, profile_num):
    seen_source_ids = {}
    prepared = []
    for index, ch in enumerate(channels or [], 1):
        item = dict(ch)
        source_tvg_id = (
            item.get("source_tvg_id")
            or item.get("epg_channel_id")
            or item.get("tvg_id")
            or ""
        )
        item["source_tvg_id"] = source_tvg_id
        if source_tvg_id and source_tvg_id in seen_source_ids:
            item["tvg_id"] = _sports_pvr_alias_id(item, profile_num, salt=str(index))
        elif source_tvg_id:
            seen_source_ids[source_tvg_id] = index
        group = item.get("group") or "Sports TV"
        if not group.startswith(("★ ", "Sports TV - ", "Xstream Pro ", "Live TV - ")):
            group = PVR_SPORTS_GROUP_PREFIX + group
        item["group"] = group
        prepared.append(item)
    return prepared


def _validate_and_backup_epg(epg_path):
    if not _epg_file_has_data_fn(epg_path):
        _log(f"EPG validation: {os.path.basename(epg_path)} has no programme data")
        return False
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(epg_path)
        root = tree.getroot()
        channel_ids = set()
        for ch in root.findall("channel"):
            cid = ch.get("id", "")
            if cid:
                channel_ids.add(cid)
        if not channel_ids:
            _log(f"EPG validation: {os.path.basename(epg_path)} has no channel elements")
            return False
        matched = False
        for prog in root.findall("programme"):
            if prog.get("channel", "") in channel_ids:
                matched = True
                break
        if not matched:
            _log(f"EPG validation: {os.path.basename(epg_path)} has no programmes matching any channel")
            return False
    except Exception as e:
        _log(f"EPG validation: {os.path.basename(epg_path)} XML parse error: {e}")
        return False
    lastgood = epg_path + ".lastgood"
    try:
        shutil.copy2(epg_path, lastgood)
    except Exception:
        pass
    return True


def _augment_pvr_epg_with_aliases(epg, epg_path, profile_num, m3u_path=None):
    if m3u_path is None:
        m3u_path = _pvr_m3u_path_for_profile(profile_num)
    alias_path = m3u_path + "_aliases.json"
    if not os.path.exists(alias_path):
        return False
    try:
        with open(alias_path, "r", encoding="utf-8") as f:
            alias_map = json.load(f)
    except Exception:
        return False
    if not alias_map:
        return False

    aliases = []
    for alias_id, info in alias_map.items():
        source_id = info.get("source_tvg_id", "")
        display_name = info.get("name", alias_id)
        if not source_id and not display_name:
            continue
        try:
            matched_id = epg._find_channel_id(source_id, display_name)
        except Exception:
            matched_id = source_id if source_id and source_id in epg.programs else None
        if matched_id and epg.programs.get(matched_id):
            aliases.append((alias_id, matched_id, display_name))
        elif source_id and epg.programs.get(source_id):
            aliases.append((alias_id, source_id, display_name))
    if not aliases:
        return False

    tmp_path = _unique_tmp_path(epg_path)
    try:
        from xml.sax.saxutils import escape as _esc

        existing_ids = set()
        closing_seen = False
        with open(epg_path, "r", encoding="utf-8", errors="ignore") as src:
            for line in src:
                if "</tv>" in line:
                    closing_seen = True
                match = re.search(r"<channel\b[^>]*\bid=([\"'])(.*?)\1", line)
                if match:
                    existing_ids.add(match.group(2))

        if not closing_seen:
            _log("PVR EPG alias augmentation warning: XMLTV closing tag missing")
            return False

        aliases_to_write = [
            (alias_id, source_id, display_name)
            for alias_id, source_id, display_name in aliases
            if alias_id not in existing_ids
        ]
        if not aliases_to_write:
            _log("PVR EPG: alias augmentation skipped, all alias IDs already exist")
            return True

        inserted = False
        programme_count = 0
        with open(epg_path, "r", encoding="utf-8", errors="ignore") as src, open(
            tmp_path, "w", encoding="utf-8", newline="\n"
        ) as dst:
            for line in src:
                if "</tv>" in line and not inserted:
                    before, after = line.split("</tv>", 1)
                    if before:
                        dst.write(before)

                    for alias_id, _source_id, display_name in aliases_to_write:
                        dst.write(
                            '  <channel id="{0}"><display-name>{1}</display-name></channel>\n'.format(
                                _esc(alias_id, {'"': "&quot;"}),
                                _esc(display_name),
                            )
                        )

                    for alias_id, source_id, _display_name in aliases_to_write:
                        _seen_alias_times = set()
                        for prog in epg.programs.get(source_id, []):
                            _alias_key = (prog.get("start", ""), prog.get("stop", ""))
                            if _alias_key in _seen_alias_times:
                                continue
                            _seen_alias_times.add(_alias_key)
                            dst.write(
                                '  <programme start="{0}" stop="{1}" channel="{2}">\n'.format(
                                    _esc(str(prog.get("start", "")), {'"': "&quot;"}),
                                    _esc(str(prog.get("stop", "")), {'"': "&quot;"}),
                                    _esc(alias_id, {'"': "&quot;"}),
                                )
                            )
                            dst.write(
                                "    <title>{0}</title>\n".format(
                                    _esc(str(prog.get("title", "Unknown")))
                                )
                            )
                            if prog.get("desc"):
                                dst.write(
                                    "    <desc>{0}</desc>\n".format(_esc(str(prog["desc"])))
                                )
                            if prog.get("icon"):
                                dst.write(
                                    '    <icon src="{0}" />\n'.format(
                                        _esc(str(prog["icon"]), {'"': "&quot;"})
                                    )
                                )
                            dst.write("  </programme>\n")
                            programme_count += 1

                    dst.write("</tv>")
                    if after:
                        dst.write(after)
                    else:
                        dst.write("\n")
                    inserted = True
                else:
                    dst.write(line)
            try:
                dst.flush()
                _safe_fsync_fn(dst)
            except OSError:
                pass

        if not inserted:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            _log("PVR EPG alias augmentation warning: did not find XMLTV closing tag")
            return False

        _safe_replace(tmp_path, epg_path)
        _log(
            "PVR EPG: augmented with {0} aliased channel EPG entries ({1} programmes)".format(
                len(aliases_to_write),
                programme_count,
            )
        )
        return True
    except Exception as e:
        _log(f"PVR EPG alias augmentation warning: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def _apply_epg_fallback_from_other_profiles(
    epg,
    profile_num,
    targets,
    target_id_key="tvg_id",
    target_name_key="name",
    log_prefix="PVR EPG",
):
    if _addon.getSetting("pvr_epg_fallback_enabled").lower() != "true":
        return 0

    pnum = str(profile_num)
    usable_targets = []
    existing = set()
    for channel_id, programmes in (getattr(epg, "programs", {}) or {}).items():
        if programmes:
            existing.add(str(channel_id))

    for target in targets or []:
        target_id = str(target.get(target_id_key) or target.get("tvg_id") or "").strip()
        if not target_id or target_id in existing:
            continue
        target_name = str(target.get(target_name_key) or target.get("name") or target_id).strip()
        target_group = str(target.get("group") or "").strip()
        match_keys = _epg_fallback_match_keys(target_name, target_group)
        strict_key = _epg_fallback_strict_share_key(target_name)
        group_key = _epg_fallback_group_key(target_group)
        if not match_keys and not strict_key:
            continue
        usable_targets.append(
            {
                "target_id": target_id,
                "name": target_name,
                "keys": match_keys,
                "strict_key": strict_key,
                "group_key": group_key,
            }
        )

    if not usable_targets:
        _log(f"{log_prefix}: fallback skipped, no missing target channels")
        return 0

    filled_channels = 0
    filled_programmes = 0
    fallback_profiles = [
        str(i)
        for i in range(1, 11)
        if str(i) != pnum and _profile_has_epg_fallback_source_fn(i)
    ]

    if not fallback_profiles:
        _log(f"{log_prefix}: fallback skipped, no other enabled profiles with sources")
        return 0

    missing = usable_targets
    for fallback_profile in fallback_profiles:
        try:
            fallback_epg = _load_epg_for_fallback_profile_fn(fallback_profile, log_prefix)
        except Exception as exc:
            _log(f"{log_prefix}: fallback profile {fallback_profile} load warning: {exc}")
            continue

        if not getattr(fallback_epg, "programs", None):
            _log(f"{log_prefix}: fallback profile {fallback_profile} has no EPG programmes")
            continue

        name_index, variant_index, ambiguous_keys = _build_epg_fallback_name_index(fallback_epg)
        strict_group_index, strict_group_ambiguous = _build_epg_fallback_group_strict_index(fallback_profile, fallback_epg)
        still_missing = []
        exact_matches = 0
        strict_group_matches = 0
        name_matches = 0
        variant_matches = 0

        for target in missing:
            target_id = target["target_id"]
            if target_id in existing:
                continue

            match_id = ""
            match_kind = ""
            if target_id in fallback_epg.programs and fallback_epg.programs.get(target_id):
                match_id = target_id
                match_kind = "exact"

            if not match_id and target.get("strict_key") and target.get("group_key"):
                match_id = strict_group_index.get((target["group_key"], target["strict_key"]), "")
                if match_id:
                    match_kind = "strict-group"
                else:
                    still_missing.append(target)
                    continue

            if not match_id:
                for key in target["keys"]:
                    match_id = name_index.get(key, "")
                    if match_id:
                        match_kind = "name"
                        break
            if not match_id:
                for key in target["keys"]:
                    match_id = variant_index.get(key, "")
                    if match_id:
                        match_kind = "variant"
                        break
            if not match_id:
                still_missing.append(target)
                continue

            programmes = fallback_epg.programs.get(match_id) or []
            if not programmes:
                still_missing.append(target)
                continue

            with epg._programs_lock:
                epg.programs[target_id] = [dict(p) for p in programmes]
                epg.channel_names[target_id] = target["name"]
                try:
                    epg._program_starts[target_id] = [
                        _epg_parse_xmltv_time_fn(p.get("start", "")) for p in programmes
                    ]
                except Exception:
                    pass
                epg._invalidate_channel_indexes()

            existing.add(target_id)
            filled_channels += 1
            filled_programmes += len(programmes)
            if match_kind == "exact":
                exact_matches += 1
            elif match_kind == "strict-group":
                strict_group_matches += 1
            elif match_kind == "variant":
                variant_matches += 1
            else:
                name_matches += 1

        missing = still_missing
        _log(
            f"{log_prefix}: fallback profile {fallback_profile} filled exact={exact_matches}, strict_group={strict_group_matches}, name={name_matches}, variant={variant_matches}, ambiguous_keys={ambiguous_keys}, strict_group_ambiguous={strict_group_ambiguous}, remaining={len(missing)}"
        )
        if not missing:
            break

    _log(
        f"{log_prefix}: fallback filled {filled_channels} channels with {filled_programmes} programmes from other profiles"
    )
    return filled_channels


def export_pvr_m3u():
    _log("PVR: Starting M3U export")
    creds = _get_pvr_credentials_fn()
    m3u_url = creds.get("m3u_url", "")
    xt_url = creds.get("xtream_url", "")
    xt_user = creds.get("xtream_username", "")
    xt_pwd = creds.get("xtream_password", "")
    if not m3u_url and not (xt_url and xt_user and xt_pwd):
        _log("PVR: No credentials configured for PVR profile")
        return False
    _log(f"PVR: m3u_url={bool(m3u_url)}, xt_url={bool(xt_url)}")

    channels = []
    total_streams = 0

    pvr_profile = _addon.getSetting("active_pvr_profile") or "Profile 1"
    pvr_pnum = (
        re.search(r"(\d+)$", pvr_profile).group(1)
        if re.search(r"(\d+)$", pvr_profile)
        else "1"
    )
    original_active = _pm.active
    try:
        _pm.active = pvr_pnum

        hidden_live = _get_hidden_subcats_fn("live", pvr_pnum)
        hidden_live_items = _get_hidden_items_fn("live", pvr_pnum)
        hide_adult = _addon.getSetting("hide_adult_categories").lower() == "true"
        epg_programs = {}
        if _get_pvr_catchup_correction_mode_fn() == "Provider metadata":
            try:
                epg = _epg_class(_addon, profile_num=pvr_pnum)
                epg.load()
                epg_programs = epg.programs or {}
            except Exception as e:
                _log(f"PVR: Catchup correction EPG load warning: {e}")

        def _append_m3u_channels_from_url(source_url, source_label):
            added = 0
            for ch in _get_cached_m3u_channels_fn(source_url):
                group = ch.get("group", "General")
                if group in hidden_live:
                    continue
                item_id = str(ch.get("tvg_id") or ch.get("url") or ch.get("name", ""))
                if item_id in hidden_live_items:
                    continue
                if hide_adult and (
                    _is_adult_category_fn(group) or _is_adult_category_fn(ch.get("name", ""))
                ):
                    continue
                channels.append(
                    {
                        "name": ch.get("name", "Unknown"),
                        "url": ch.get("url", ""),
                        "tvg_id": ch.get("tvg_id", ""),
                        "logo": ch.get("logo", ""),
                        "group": group,
                        "catchup": ch.get("catchup", ""),
                        "catchup_source": ch.get("catchup_source", ""),
                        "catchup_days": ch.get("catchup_days", ""),
                        "catchup_correction": _catchup_correction_for_channel_fn(
                            epg_programs, ch.get("tvg_id", ""), ch.get("catchup_correction", "")
                        ),
                    }
                )
                added += 1
            if added:
                _log(f"PVR M3U export: added {added} channels from {source_label}")
            return added

        m3u_is_xtream_like = bool(m3u_url) and _m3u_has_credentials_fn(m3u_url)
        if m3u_url and not m3u_is_xtream_like:
            _append_m3u_channels_from_url(m3u_url, "M3U")
        streams = []
        if xt_url and xt_user and xt_pwd:
            cats = _get_cached_xtream_categories_fn(xt_url, xt_user, xt_pwd, "live")
            cat_map = {}
            for c in cats or []:
                cat_map[str(c.get("category_id", ""))] = c.get(
                    "category_name", "Live TV"
                )

            _log(
                f"PVR M3U export: {len(hidden_live)} hidden categories: {hidden_live}, {len(hidden_live_items)} hidden items"
            )
            streams = _get_cached_xtream_streams_fn(xt_url, xt_user, xt_pwd, "live")
        total_streams = len(streams) if xt_url and xt_user and xt_pwd else 0
        skipped = 0
        if xt_url and xt_user and xt_pwd:
            for s in streams:
                cat_id = str(s.get("category_id", ""))
                if cat_id in hidden_live:
                    skipped += 1
                    continue
                if str(s.get("stream_id", "")) in hidden_live_items:
                    skipped += 1
                    continue
                group = cat_map.get(cat_id, "Live TV")
                if hide_adult and (
                    _is_adult_category_fn(group) or _is_adult_category_fn(s.get("name", ""))
                ):
                    skipped += 1
                    continue
                sid = str(s.get("stream_id", ""))
                epg_id = s.get("epg_channel_id") or sid
                url = _iptv_build_url_fn(xt_url, xt_user, xt_pwd, s, "live")
                tv_arch = str(s.get("tv_archive", "")).lower()
                catchup_flag = str(s.get("catchup", "")).lower()
                has_catchup = tv_arch in ("1", "yes", "true") or catchup_flag in (
                    "1",
                    "yes",
                    "true",
                    "default",
                )
                channels.append(
                    {
                        "name": s.get("name", "Unknown"),
                        "url": url,
                        "tvg_id": epg_id,
                        "logo": s.get("stream_icon", ""),
                        "group": group,
                        "stream_type": s.get("stream_type", ""),
                        "catchup": "default" if has_catchup else "",
                        "catchup_source": f"{xt_url}/live/{xt_user}/{xt_pwd}/{sid}.ts?utc={{utc}}&lutc=${{end}}"
                        if has_catchup
                        else "",
                        "catchup_days": str(s.get("tv_archive_duration", "") or "7")
                        if has_catchup
                        else "",
                        "catchup_correction": _catchup_correction_for_channel_fn(
                            epg_programs, epg_id
                        ) if has_catchup else "",
                    }
                )

        if m3u_url and m3u_is_xtream_like and not channels:
            _log("PVR M3U export: Xtream API returned no channels, trying credential-bearing M3U directly")
            _append_m3u_channels_from_url(m3u_url, "credential-bearing M3U")

        _log(
            f"PVR M3U export: {total_streams} total streams, {skipped} skipped, {len(channels)} exported"
        )

        if not channels:
            _log("PVR M3U export: no channels after filtering; leaving existing M3U unchanged")
            return False

        channels = _prepare_live_pvr_channels_for_export(channels, pvr_pnum)
        _log(f"PVR M3U export: {len(channels)} channels after deduplication")

        m3u_path = _pvr_m3u_path()

        alias_map = {}
        for ch in channels:
            source_tvg_id = ch.get("source_tvg_id", "")
            tvg_id = ch.get("tvg_id", "")
            export_tvg_id = _m3u_safe_fn(tvg_id) or _m3u_safe_fn(ch.get("name", "")) or "unknown"
            if source_tvg_id and tvg_id != source_tvg_id and tvg_id.startswith("xstream-live-p"):
                alias_map[export_tvg_id] = {
                    "source_tvg_id": source_tvg_id,
                    "name": ch.get("name", ""),
                }
            elif not source_tvg_id and export_tvg_id:
                alias_map[export_tvg_id] = {
                    "source_tvg_id": "",
                    "name": ch.get("name", ""),
                }
        alias_path = m3u_path + "_aliases.json"
        if alias_map:
            try:
                _atomic_write_text_fn(alias_path, json.dumps(alias_map, ensure_ascii=False))
                _log(f"PVR M3U export: saved {len(alias_map)} alias mappings")
            except Exception as e:
                _log(f"PVR M3U export: could not save alias map: {e}")
        else:
            try:
                if os.path.exists(alias_path):
                    os.remove(alias_path)
                    _log("PVR M3U export: removed stale alias mappings")
            except Exception as e:
                _log(f"PVR M3U export: stale alias cleanup warning: {e}")

        m3u_data = _build_m3u_content_fn(channels)
        tmp = _unique_tmp_path(m3u_path)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(m3u_data)
            try:
                f.flush()
                _safe_fsync_fn(f)
            except OSError:
                pass
        _safe_replace(tmp, m3u_path)
        bad_lines = [
            ln
            for ln in m3u_data.splitlines()
            if ln.startswith("#EXTINF:") and "," not in ln
        ]
        if bad_lines:
            _log(f"M3U validation failed on {len(bad_lines)} lines")
            return False
        _log(f"Exported PVR M3U with {len(channels)} channels")
        return True
    finally:
        _pm.active = original_active


def _export_live_pvr_epg_xmltv(epg, epg_path, m3u_path, profile_num, log_prefix="PVR EPG"):
    from xml.sax.saxutils import escape

    alias_path = m3u_path + "_aliases.json"
    alias_map = {}
    if os.path.exists(alias_path):
        try:
            with open(alias_path, "r", encoding="utf-8") as f:
                alias_map = json.load(f)
            if alias_map:
                _log(f"{log_prefix}: loaded {len(alias_map)} alias mappings")
        except Exception:
            pass

    targets = _parse_pvr_m3u_epg_targets(m3u_path)
    if not targets:
        _log(f"{log_prefix}: no M3U targets found")
        return False

    _log(f"{log_prefix}: loaded {len(targets)} M3U targets")

    merged_count = 0
    for target in targets:
        tvg_id = target["tvg_id"]
        if tvg_id in alias_map:
            info = alias_map[tvg_id]
            source = info.get("source_tvg_id", "")
            if source:
                target["source_tvg_id"] = source
            name = info.get("name", "")
            if name:
                target["name"] = name
            merged_count += 1
    if merged_count:
        _log(f"{log_prefix}: merged {merged_count} alias mappings into targets")

    safe_to_id = {}
    with epg._programs_lock:
        provider_ids = list(epg.programs.keys())
    for pid in provider_ids:
        safe_pid = _m3u_safe_fn(pid)
        if safe_pid and safe_pid not in safe_to_id:
            safe_to_id[safe_pid] = pid

    seen_ids = set()
    channel_rows = []
    matched = []
    counts = {"exact": 0, "alias": 0, "find_source": 0, "find_tvg": 0, "safe": 0}
    unmatched_count = 0
    unmatched_examples = []
    unmatched_targets = []

    for target in targets:
        tvg_id = target["tvg_id"]
        source_id = target.get("source_tvg_id") or tvg_id
        name = target.get("name") or tvg_id

        if tvg_id in seen_ids:
            continue
        seen_ids.add(tvg_id)
        channel_rows.append((tvg_id, name))

        try:
            if epg.programs.get(tvg_id):
                matched.append((tvg_id, name, epg.programs[tvg_id]))
                counts["exact"] += 1
                continue
        except Exception:
            pass

        if source_id != tvg_id:
            try:
                if epg.programs.get(source_id):
                    matched.append((tvg_id, name, epg.programs[source_id]))
                    counts["alias"] += 1
                    continue
            except Exception:
                pass

        try:
            mid = epg._find_channel_id(source_id, name)
            if mid and epg.programs.get(mid):
                matched.append((tvg_id, name, epg.programs[mid]))
                counts["find_source"] += 1
                continue
        except Exception:
            pass

        if tvg_id != source_id:
            try:
                mid = epg._find_channel_id(tvg_id, name)
                if mid and epg.programs.get(mid):
                    matched.append((tvg_id, name, epg.programs[mid]))
                    counts["find_tvg"] += 1
                    continue
            except Exception:
                pass

        safe_pid = safe_to_id.get(tvg_id)
        if safe_pid and epg.programs.get(safe_pid):
            matched.append((tvg_id, name, epg.programs[safe_pid]))
            counts["safe"] += 1
            continue

        unmatched_count += 1
        if len(unmatched_examples) < 10:
            unmatched_examples.append(f"{name} (id={source_id}, tvg_id={tvg_id})")
        unmatched_targets.append((tvg_id, source_id, name))

    _log(
        f"{log_prefix}: matched exact={counts['exact']} alias={counts['alias']} "
        f"find_source={counts['find_source']} find_tvg={counts['find_tvg']} "
        f"safe={counts['safe']} unmatched={unmatched_count}/{len(channel_rows)}"
    )
    if unmatched_count > 0:
        _log(f"{log_prefix}: unmatched examples: {', '.join(unmatched_examples)}")

    if unmatched_targets:
        _program_ids = set(epg.programs.keys())
        _channel_names = epg.channel_names or {}
        provider_empty = 0
        provider_id_conflict = 0
        id_not_found = 0
        for _tvg_id, _source_id, _name in unmatched_targets:
            _check_id = _source_id if _source_id in _channel_names else _tvg_id
            if _check_id in _channel_names:
                if _check_id not in _program_ids:
                    _epg_name = _channel_names[_check_id]
                    _norm_m3u = _name.casefold().strip()
                    _norm_epg = _epg_name.casefold().strip()
                    if _norm_epg and _norm_m3u and (_norm_epg in _norm_m3u or _norm_m3u in _norm_epg):
                        provider_empty += 1
                    else:
                        provider_id_conflict += 1
                else:
                    provider_empty += 1
            else:
                id_not_found += 1
        _log(
            f"{log_prefix}: unmatched breakdown: provider_empty={provider_empty} "
            f"provider_id_conflict={provider_id_conflict} id_not_found={id_not_found}"
        )

    tmp_path = _unique_tmp_path(epg_path)
    programme_count = 0
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<tv>\n')
            for tvg_id, name in channel_rows:
                f.write(
                    '  <channel id="{0}"><display-name>{1}</display-name></channel>\n'.format(
                        escape(tvg_id, {'"': "&quot;"}),
                        escape(name),
                    )
                )
            for tvg_id, _name, progs in matched:
                _seen_times = set()
                for prog in progs:
                    _prog_key = (prog.get("start", ""), prog.get("stop", ""))
                    if _prog_key in _seen_times:
                        continue
                    _seen_times.add(_prog_key)
                    f.write(
                        '  <programme start="{0}" stop="{1}" channel="{2}">\n'.format(
                            escape(str(prog.get("start", "")), {'"': "&quot;"}),
                            escape(str(prog.get("stop", "")), {'"': "&quot;"}),
                            escape(tvg_id, {'"': "&quot;"}),
                        )
                    )
                    f.write("    <title>{0}</title>\n".format(escape(str(prog.get("title", "Unknown")))))
                    if prog.get("desc"):
                        f.write("    <desc>{0}</desc>\n".format(escape(str(prog["desc"]))))
                    if prog.get("icon"):
                        f.write(
                            '    <icon src="{0}" />\n'.format(
                                escape(str(prog["icon"]), {'"': "&quot;"})
                            )
                        )
                    f.write("  </programme>\n")
                    programme_count += 1
            f.write("</tv>\n")
            try:
                f.flush()
                _safe_fsync_fn(f)
            except OSError:
                pass

        _safe_replace(tmp_path, epg_path)
        _log(
            f"{log_prefix}: exported {len(channel_rows)} channels "
            f"({len(matched)} with programmes) and {programme_count} programmes"
        )
        return True
    except (OSError, PermissionError):
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise
    except Exception as e:
        _log(f"{log_prefix}: XMLTV write failed: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def export_pvr_epg_for_profile(profile_num, force_fetch=False):
    epg_path = _pvr_epg_path_for_profile(profile_num)
    pvr_pnum = str(profile_num)
    try:
        cached_epg = get_cached_epg_for_profile(pvr_pnum)
        if cached_epg is not None and cached_epg.programs:
            epg = cached_epg
            _log(f"PVR EPG: reusing in-memory EPG ({len(epg.programs)} channels)")
        elif force_fetch:
            epg = _epg_class(_addon, profile_num=pvr_pnum)
            _t0 = time.monotonic()
            epg.fetch()
            _log(f"PVR EPG: provider fetch took {time.monotonic() - _t0:.1f}s")
        else:
            epg = _epg_class(_addon, profile_num=pvr_pnum)
            if os.path.exists(epg.cache_file):
                _t0 = time.monotonic()
                epg._load_cache()
                _log(f"PVR EPG: cache load took {time.monotonic() - _t0:.1f}s")
            else:
                _log("PVR EPG: no cache available; keeping existing EPG file")
                if _epg_file_has_data_fn(epg_path):
                    return True
                lastgood = epg_path + ".lastgood"
                if os.path.exists(lastgood) and _epg_file_has_data_fn(lastgood):
                    try:
                        shutil.copy2(lastgood, epg_path)
                        _log("PVR EPG: restored from last-good backup")
                        return True
                    except Exception:
                        pass
                return False

        if epg.programs:
            _epg_instance_cache_put(pvr_pnum, epg)

        m3u_path = _pvr_m3u_path_for_profile(pvr_pnum)
        fallback_targets = _parse_pvr_m3u_epg_targets(m3u_path)
        _apply_epg_fallback_from_other_profiles(
            epg,
            pvr_pnum,
            fallback_targets,
            target_id_key="tvg_id",
            target_name_key="name",
            log_prefix="PVR EPG",
        )

        export_write_error = False
        try:
            if epg.programs and _export_live_pvr_epg_xmltv(epg, epg_path, m3u_path, profile_num):
                if _validate_and_backup_epg(epg_path):
                    _pvr_epg_fallback_mark_built(profile_num, "live")
                else:
                    _log("EPG validation failed after export; keeping previous backup")
            elif epg.programs and _epg_file_has_data_fn(epg_path):
                _log("EPG export produced no fresh data; keeping existing PVR EPG")
                _augment_pvr_epg_with_aliases(epg, epg_path, profile_num)
                return True
        except (OSError, PermissionError) as write_err:
            _log(f"PVR EPG: file-write error during export: {write_err}; keeping existing file")
            export_write_error = True

        if _epg_file_has_data_fn(epg_path):
            return True

        if os.path.exists(epg_path) and os.path.getsize(epg_path) > 0:
            _log("EPG export produced no guide data; keeping existing empty/stub PVR EPG")
            return False

        lastgood = epg_path + ".lastgood"
        if os.path.exists(lastgood) and _epg_file_has_data_fn(lastgood):
            try:
                shutil.copy2(lastgood, epg_path)
                _log("EPG export: restored from last-good backup instead of writing stub")
                return True
            except Exception:
                pass

        _log("EPG export: no guide data and no last-good backup available; not writing empty stub")
        return False
    except Exception as e:
        _log(f"EPG export failed: {e}")
        return False


def export_pvr_epg(force_fetch=False):
    return export_pvr_epg_for_profile(_get_pvr_profile_num(), force_fetch=force_fetch)


def export_sports_pvr_epg_for_profile(profile_num, channels, force_fetch=False):
    epg_path = _sports_pvr_epg_path_for_profile(profile_num)
    pvr_pnum = str(profile_num)
    try:
        cached_epg = get_cached_epg_for_profile(pvr_pnum)
        if cached_epg is not None and cached_epg.programs:
            epg = cached_epg
            _log(f"Sports PVR EPG: reusing in-memory EPG ({len(epg.programs)} channels)")
        elif force_fetch:
            epg = _epg_class(_addon, profile_num=pvr_pnum)
            _t0 = time.monotonic()
            epg.fetch()
            _log(f"Sports PVR EPG: provider fetch took {time.monotonic() - _t0:.1f}s")
        else:
            epg = _epg_class(_addon, profile_num=pvr_pnum)
            if os.path.exists(epg.cache_file):
                _t0 = time.monotonic()
                epg._load_cache()
                _log(f"Sports PVR EPG: cache load took {time.monotonic() - _t0:.1f}s")
            else:
                _log("Sports PVR EPG: no cache available; keeping existing EPG file")
                if _epg_file_has_data_fn(epg_path):
                    return True
                lastgood = epg_path + ".lastgood"
                if os.path.exists(lastgood) and _epg_file_has_data_fn(lastgood):
                    try:
                        shutil.copy2(lastgood, epg_path)
                        _log("Sports PVR EPG: restored from last-good backup")
                        return True
                    except Exception:
                        pass
                return False

        if epg.programs:
            _epg_instance_cache_put(pvr_pnum, epg)

        _apply_epg_fallback_from_other_profiles(
            epg,
            profile_num,
            channels,
            target_id_key="source_tvg_id",
            target_name_key="name",
            log_prefix="Sports PVR EPG",
        )

        if not epg.programs:
            if _epg_file_has_data_fn(epg_path):
                _log("Sports PVR: no fresh EPG data; keeping existing Sports EPG")
                return True
            lastgood = epg_path + ".lastgood"
            if os.path.exists(lastgood) and _epg_file_has_data_fn(lastgood):
                try:
                    shutil.copy2(lastgood, epg_path)
                    _log("Sports PVR: restored EPG from last-good backup instead of writing stub")
                    return True
                except Exception:
                    pass
            _atomic_write_text_fn(epg_path, '<?xml version="1.0" encoding="utf-8"?>\n<tv>\n</tv>\n')
            _log("Sports PVR: exported empty Sports EPG because provider EPG has no programmes")
            return False

        from xml.sax.saxutils import escape

        m3u_path = _sports_pvr_m3u_path()
        alias_path = m3u_path + "_aliases.json"
        alias_map = {}
        if os.path.exists(alias_path):
            try:
                with open(alias_path, "r", encoding="utf-8") as af:
                    alias_map = json.load(af)
                if alias_map:
                    _log(f"Sports PVR EPG: loaded {len(alias_map)} alias mappings")
            except Exception:
                pass

        channel_rows = []
        matched = []
        seen_ids = set()
        counts = {"exact": 0, "alias": 0, "find_source": 0, "find_tvg": 0, "safe": 0, "fuzzy": 0}
        unmatched_count = 0
        unmatched_examples = []
        unmatched_targets = []
        fuzzy_examples = []

        safe_to_id = {}
        with epg._programs_lock:
            provider_ids = list(epg.programs.keys())
        for pid in provider_ids:
            safe_pid = _m3u_safe_fn(pid)
            if safe_pid and safe_pid not in safe_to_id:
                safe_to_id[safe_pid] = pid

        fuzzy_name_index, _fuzzy_variant_index, _fuzzy_ambiguous = _build_epg_fallback_name_index(epg)

        for ch in channels or []:
            tvg_id = str(ch.get("tvg_id") or "").strip()
            source_id = str(ch.get("source_tvg_id") or "").strip()
            name = str(ch.get("name") or tvg_id or "Unknown")

            export_tvg_id = _m3u_safe_fn(tvg_id) if tvg_id else ""
            if export_tvg_id and export_tvg_id in alias_map:
                info = alias_map[export_tvg_id]
                alias_source = info.get("source_tvg_id", "")
                if alias_source:
                    source_id = alias_source
                alias_name = info.get("name", "")
                if alias_name:
                    name = alias_name

            if not tvg_id or tvg_id in seen_ids:
                continue
            seen_ids.add(tvg_id)
            channel_rows.append((tvg_id, name))

            if not source_id:
                source_id = tvg_id

            try:
                if epg.programs.get(tvg_id):
                    matched.append((tvg_id, name, epg.programs[tvg_id]))
                    counts["exact"] += 1
                    continue
            except Exception:
                pass

            if source_id != tvg_id:
                try:
                    if epg.programs.get(source_id):
                        matched.append((tvg_id, name, epg.programs[source_id]))
                        counts["alias"] += 1
                        continue
                except Exception:
                    pass

            try:
                mid = epg._find_channel_id(source_id, name)
                if mid and epg.programs.get(mid):
                    matched.append((tvg_id, name, epg.programs[mid]))
                    counts["find_source"] += 1
                    continue
            except Exception:
                pass

            if tvg_id != source_id:
                try:
                    mid = epg._find_channel_id(tvg_id, name)
                    if mid and epg.programs.get(mid):
                        matched.append((tvg_id, name, epg.programs[mid]))
                        counts["find_tvg"] += 1
                        continue
                except Exception:
                    pass

            safe_pid = safe_to_id.get(tvg_id) or safe_to_id.get(source_id)
            if safe_pid and epg.programs.get(safe_pid):
                matched.append((tvg_id, name, epg.programs[safe_pid]))
                counts["safe"] += 1
                continue

            group = str(ch.get("group") or "").strip()
            fuzzy_mid = None
            fuzzy_key = ""
            for fkey in _epg_fallback_match_keys(name, group):
                fmid = fuzzy_name_index.get(fkey)
                if fmid and epg.programs.get(fmid):
                    fuzzy_mid = fmid
                    fuzzy_key = fkey
                    break
            if fuzzy_mid and epg.programs.get(fuzzy_mid):
                matched.append((tvg_id, name, epg.programs[fuzzy_mid]))
                counts["fuzzy"] += 1
                if len(fuzzy_examples) < 20:
                    fuzzy_examples.append(
                        '"{0}" id={1} -> "{2}" key="{3}"'.format(
                            name[:60],
                            source_id or tvg_id,
                            epg.channel_names.get(fuzzy_mid, fuzzy_mid)[:60],
                            fuzzy_key,
                        )
                    )
                continue

            matched_id_source = source_id if source_id else tvg_id
            unmatched_count += 1
            if len(unmatched_examples) < 10:
                unmatched_examples.append(f"{name} (id={matched_id_source}, tvg_id={tvg_id})")
            unmatched_targets.append((tvg_id, matched_id_source, name))

        _log(
            "Sports PVR EPG: matched exact={0} alias={1} "
            "find_source={2} find_tvg={3} safe={4} fuzzy={5} unmatched={6}/{7}".format(
                counts["exact"], counts["alias"],
                counts["find_source"], counts["find_tvg"],
                counts["safe"], counts["fuzzy"], unmatched_count, len(channel_rows),
            )
        )
        if unmatched_count > 0:
            _log("Sports PVR EPG: unmatched examples: {0}".format(", ".join(unmatched_examples)))
        if counts["fuzzy"] > 0 and fuzzy_examples:
            _log("Sports PVR EPG fuzzy: {0}".format("; ".join(fuzzy_examples)))

        if unmatched_targets:
            _program_ids = set(epg.programs.keys())
            _channel_names = epg.channel_names or {}
            provider_empty = 0
            provider_id_conflict = 0
            id_not_found = 0
            for _tvg_id, _source_id, _name in unmatched_targets:
                _check_id = _source_id if _source_id in _channel_names else _tvg_id
                if _check_id in _channel_names:
                    if _check_id not in _program_ids:
                        _epg_name = _channel_names[_check_id]
                        _norm_m3u = _name.casefold().strip()
                        _norm_epg = _epg_name.casefold().strip()
                        if _norm_epg and _norm_m3u and (_norm_epg in _norm_m3u or _norm_m3u in _norm_epg):
                            provider_empty += 1
                        else:
                            provider_id_conflict += 1
                    else:
                        provider_empty += 1
                else:
                    id_not_found += 1
            _log(
                "Sports PVR EPG: unmatched breakdown: provider_empty={0} "
                "provider_id_conflict={1} id_not_found={2}".format(
                    provider_empty, provider_id_conflict, id_not_found
                )
            )

        if not matched:
            if _epg_file_has_data_fn(epg_path):
                _log("Sports PVR: no matching Sports EPG programmes; keeping existing Sports EPG")
                return True
            lastgood = epg_path + ".lastgood"
            if os.path.exists(lastgood) and _epg_file_has_data_fn(lastgood):
                try:
                    shutil.copy2(lastgood, epg_path)
                    _log("Sports PVR: restored EPG from last-good backup")
                    return True
                except Exception:
                    pass
            _atomic_write_text_fn(epg_path, '<?xml version="1.0" encoding="utf-8"?>\n<tv>\n</tv>\n')
            _log("Sports PVR: no matching EPG programmes for Sports channels (no last-good backup)")
            return False

        tmp_path = _unique_tmp_path(epg_path)
        programme_count = 0
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<tv>\n')
            for tvg_id, name in channel_rows:
                f.write(
                    '  <channel id="{0}"><display-name>{1}</display-name></channel>\n'.format(
                        escape(tvg_id, {'"': "&quot;"}),
                        escape(name),
                    )
                )
            for tvg_id, _name, progs in matched:
                for prog in progs:
                    f.write(
                        '  <programme start="{0}" stop="{1}" channel="{2}">\n'.format(
                            escape(str(prog.get("start", "")), {'"': "&quot;"}),
                            escape(str(prog.get("stop", "")), {'"': "&quot;"}),
                            escape(tvg_id, {'"': "&quot;"}),
                        )
                    )
                    f.write("    <title>{0}</title>\n".format(escape(str(prog.get("title", "Unknown")))))
                    if prog.get("desc"):
                        f.write("    <desc>{0}</desc>\n".format(escape(str(prog["desc"]))))
                    if prog.get("icon"):
                        f.write(
                            '    <icon src="{0}" />\n'.format(
                                escape(str(prog["icon"]), {'"': "&quot;"})
                            )
                        )
                    f.write("  </programme>\n")
                    programme_count += 1
            f.write("</tv>\n")
            try:
                f.flush()
                _safe_fsync_fn(f)
            except OSError:
                pass
        _safe_replace(tmp_path, epg_path)

        if alias_map:
            try:
                _augment_pvr_epg_with_aliases(epg, epg_path, profile_num, m3u_path=m3u_path)
            except Exception as aug_exc:
                _log(f"Sports PVR EPG: alias augmentation warning: {aug_exc}")

        if _validate_and_backup_epg(epg_path):
            _pvr_epg_fallback_mark_built(profile_num, "sports")
        else:
            _log("Sports PVR: EPG validation failed after export; keeping previous backup")
        _log(
            "Sports PVR: Exported namespaced EPG with {0} channels ({1} with programmes) and {2} programmes".format(
                len(channel_rows),
                len(matched),
                programme_count,
            )
        )
        return True
    except Exception as e:
        _log(f"Sports PVR: EPG export failed: {e}")
        _log(f"Traceback: {traceback.format_exc()}")
        return False


def export_sports_pvr_m3u():
    pnum = _get_sports_pvr_profile_num()
    channels = _sports_pvr_source_channels_fn()
    channels = _apply_pvr_catchup_corrections_fn(channels, pnum, "Sports PVR")
    channels = _prepare_sports_pvr_channels_for_export(channels, pnum)
    m3u_path = _sports_pvr_m3u_path()
    if not channels:
        _log("Sports PVR: no sports channels, writing empty M3U")
        _atomic_write_text_fn(m3u_path, "#EXTM3U\n")
        try:
            alias_path = m3u_path + "_aliases.json"
            if os.path.exists(alias_path):
                os.remove(alias_path)
        except OSError:
            pass
        return []

    alias_map = {}
    for ch in channels:
        source_tvg_id = ch.get("source_tvg_id", "")
        tvg_id = ch.get("tvg_id", "")
        export_tvg_id = _m3u_safe_fn(tvg_id) or _m3u_safe_fn(ch.get("name", "")) or "unknown"
        if source_tvg_id and tvg_id != source_tvg_id and tvg_id.startswith("xstream-sports-p"):
            alias_map[export_tvg_id] = {
                "source_tvg_id": source_tvg_id,
                "name": ch.get("name", ""),
            }
        elif not source_tvg_id and export_tvg_id:
            alias_map[export_tvg_id] = {
                "source_tvg_id": "",
                "name": ch.get("name", ""),
            }
    alias_path = m3u_path + "_aliases.json"
    if alias_map:
        try:
            _atomic_write_text_fn(alias_path, json.dumps(alias_map, ensure_ascii=False))
            _log(f"Sports PVR M3U export: saved {len(alias_map)} alias mappings")
        except Exception as e:
            _log(f"Sports PVR M3U export: could not save alias map: {e}")
    else:
        try:
            if os.path.exists(alias_path):
                os.remove(alias_path)
                _log("Sports PVR M3U export: removed stale alias mappings")
        except Exception as e:
            _log(f"Sports PVR M3U export: stale alias cleanup warning: {e}")

    m3u_data = _build_m3u_content_fn(channels)
    tmp = _unique_tmp_path(m3u_path)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(m3u_data)
        try:
            f.flush()
            _safe_fsync_fn(f)
        except OSError:
            pass
    _safe_replace(tmp, m3u_path)
    _log(f"Sports PVR: Exported M3U with {len(channels)} channels")
    return channels
