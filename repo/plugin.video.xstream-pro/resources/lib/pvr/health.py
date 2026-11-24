"""PVR health report generation and EPG health diagnostics.

Call init() after addon module globals are available.
"""

import json
import os
import re
import time

import xbmc
import xbmcvfs

from pvr.constants import (
    PVR_INSTANCE_NAME,
    PVR_FAVS_INSTANCE_NAME,
    PVR_SPORTS_INSTANCE_NAME,
    PVR_SPORTS_FAVS_INSTANCE_NAME,
)
from pvr.paths import (
    _pvr_m3u_path_for_profile,
    _pvr_epg_path_for_profile,
    _sports_pvr_m3u_path,
    _sports_pvr_epg_path_for_profile,
    _get_pvr_profile_num,
    _get_sports_pvr_profile_num,
)

_addon = None
_log_fn = None
_parse_xmltv_time_fn = None
_m3u_file_has_channels_fn = None
_epg_file_has_data_fn = None
_role_has_instance_fn = None
_pvr_instance_matches_paths_fn = None
_get_pvr_instance_id_fn = None
_owned_pvr_instance_enabled_fn = None


def init(
    addon,
    log_fn,
    parse_xmltv_time_fn,
    m3u_file_has_channels_fn,
    epg_file_has_data_fn,
    role_has_instance_fn,
    pvr_instance_matches_paths_fn,
    get_pvr_instance_id_fn,
    owned_pvr_instance_enabled_fn,
):
    global _addon, _log_fn, _parse_xmltv_time_fn
    global _m3u_file_has_channels_fn, _epg_file_has_data_fn
    global _role_has_instance_fn, _pvr_instance_matches_paths_fn
    global _get_pvr_instance_id_fn, _owned_pvr_instance_enabled_fn
    _addon = addon
    _log_fn = log_fn
    _parse_xmltv_time_fn = parse_xmltv_time_fn
    _m3u_file_has_channels_fn = m3u_file_has_channels_fn
    _epg_file_has_data_fn = epg_file_has_data_fn
    _role_has_instance_fn = role_has_instance_fn
    _pvr_instance_matches_paths_fn = pvr_instance_matches_paths_fn
    _get_pvr_instance_id_fn = get_pvr_instance_id_fn
    _owned_pvr_instance_enabled_fn = owned_pvr_instance_enabled_fn


def _log(msg):
    if _log_fn:
        _log_fn(msg)


def _safe_file_size(path):
    try:
        size = os.path.getsize(path)
        if size < 1024:
            return "{0} B".format(size)
        if size < 1024 * 1024:
            return "{0:.1f} KB".format(size / 1024)
        return "{0:.1f} MB".format(size / (1024 * 1024))
    except OSError:
        return "missing"


def _safe_file_age(path):
    try:
        age = time.time() - os.path.getmtime(path)
        if age < 60:
            return "{0:.0f}s".format(age)
        if age < 3600:
            return "{0:.0f}m".format(age / 60)
        if age < 86400:
            return "{0:.0f}h {1:.0f}m".format(age / 3600, (age % 3600) / 60)
        return "{0:.0f}d {1:.0f}h".format(age / 86400, (age % 86400) / 3600)
    except OSError:
        return "missing"


def _m3u_channel_count(path):
    try:
        count = 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("#EXTINF"):
                    count += 1
        return count
    except Exception as e:
        _log(f"PVR: channel count warning for {os.path.basename(path)}: {e}")
        return 0


def _load_pvr_alias_map(alias_path):
    try:
        if not os.path.exists(alias_path):
            return {}
        with open(alias_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log("PVR EPG alias map read warning: {0}".format(exc))
        return {}


def _xmltv_id_summary(epg_path, wanted_ids=None):
    wanted = set(str(x or "").strip() for x in (wanted_ids or []) if str(x or "").strip())
    channel_re = re.compile(r'<channel\s+id="([^"]*)"')
    programme_re = re.compile(r'<programme\b[^>]*\schannel="([^"]*)"')
    stop_re = re.compile(r'\sstop="([^"]*)"')
    summary = {
        "programme_count": 0,
        "max_stop": 0,
        "channel_ids": set(),
        "programme_ids": set(),
        "max_stop_by_id": {},
    }
    try:
        with open(epg_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "<channel" in line:
                    match = channel_re.search(line)
                    if match:
                        cid = match.group(1)
                        if not wanted or cid in wanted:
                            summary["channel_ids"].add(cid)
                if "<programme" not in line:
                    continue
                summary["programme_count"] += 1
                channel_match = programme_re.search(line)
                stop_match = stop_re.search(line)
                if not channel_match:
                    continue
                cid = channel_match.group(1)
                if wanted and cid not in wanted:
                    continue
                summary["programme_ids"].add(cid)
                if stop_match:
                    stop_ts = _parse_xmltv_time_fn(stop_match.group(1))
                    if stop_ts:
                        summary["max_stop"] = max(summary["max_stop"], stop_ts)
                        summary["max_stop_by_id"][cid] = max(
                            summary["max_stop_by_id"].get(cid, 0),
                            stop_ts,
                        )
    except Exception as exc:
        _log("PVR EPG XMLTV scan warning: {0}".format(exc))
    return summary


def _live_pvr_epg_health(profile_num):
    m3u_path = _pvr_m3u_path_for_profile(profile_num)
    epg_path = _pvr_epg_path_for_profile(profile_num)
    alias_path = m3u_path + "_aliases.json"
    now = time.time()
    issues = []

    if not _m3u_file_has_channels_fn(m3u_path):
        issues.append("M3U missing or empty")

    if not _epg_file_has_data_fn(epg_path):
        issues.append("XMLTV missing, empty, or has no programme rows")
        return {"ok": False, "issues": issues}

    try:
        age = now - os.path.getmtime(epg_path)
        from pvr.paths import _pvr_epg_refresh_seconds
        if age > _pvr_epg_refresh_seconds():
            issues.append("XMLTV file is older than configured refresh interval")
    except Exception:
        issues.append("XMLTV file age could not be checked")

    alias_map = _load_pvr_alias_map(alias_path)
    wanted_ids = set(alias_map.keys())
    wanted_ids.update(
        str(info.get("source_tvg_id") or "").strip()
        for info in alias_map.values()
        if isinstance(info, dict)
    )
    wanted_ids.discard("")

    summary = _xmltv_id_summary(epg_path, wanted_ids)
    if summary["programme_count"] <= 0:
        issues.append("XMLTV scan found no programme rows")

    missing_aliases = 0
    stale_aliases = 0
    stale_sources = 0
    stale_cutoff = now + 1800
    for alias_id, info in alias_map.items():
        if not isinstance(info, dict):
            continue
        source_id = str(info.get("source_tvg_id") or "").strip()
        if not source_id:
            continue
        source_stop = summary["max_stop_by_id"].get(source_id, 0)
        if source_stop <= 0:
            continue
        alias_stop = summary["max_stop_by_id"].get(alias_id, 0)
        if alias_stop <= 0:
            missing_aliases += 1
        elif alias_stop < stale_cutoff:
            stale_aliases += 1
        if source_stop < stale_cutoff:
            stale_sources += 1

    if missing_aliases:
        issues.append("XMLTV missing programme rows for {0} aliased channels".format(missing_aliases))
    if stale_aliases:
        issues.append("XMLTV has stale programme rows for {0} aliased channels".format(stale_aliases))
    if stale_sources >= 3:
        issues.append("XMLTV has stale source programme rows for {0} channels".format(stale_sources))

    return {"ok": not issues, "issues": issues}


def _pvr_health_report():
    """Build PVR health diagnostic report for display."""
    lines = []
    profile_num = _get_pvr_profile_num()
    sports_pnum = _get_sports_pvr_profile_num()
    roles = [
        ("main", PVR_INSTANCE_NAME, profile_num),
        ("favs", PVR_FAVS_INSTANCE_NAME, profile_num),
        ("sports", PVR_SPORTS_INSTANCE_NAME, sports_pnum),
        ("sports_favs", PVR_SPORTS_FAVS_INSTANCE_NAME, sports_pnum),
    ]
    for role, name, pnum in roles:
        lines.append("[B]{}[/B]".format(name))
        if not _role_has_instance_fn(role):
            lines.append("  Instance: [COLOR red]not found[/COLOR]")
            lines.append("")
            continue
        iid = _get_pvr_instance_id_fn(role)
        enabled = _owned_pvr_instance_enabled_fn(role)
        if enabled is True:
            en_label = "enabled"
            en_color = "green"
        elif enabled is False:
            en_label = "disabled"
            en_color = "red"
        else:
            en_label = "unknown"
            en_color = "yellow"
        lines.append("  Instance {}: [COLOR {}]{}[/COLOR]".format(iid, en_color, en_label))
        if role in ("main", "favs"):
            m3u_path = _pvr_m3u_path_for_profile(pnum)
            epg_path = _pvr_epg_path_for_profile(pnum)
        else:
            m3u_path = _sports_pvr_m3u_path()
            epg_path = _sports_pvr_epg_path_for_profile(pnum)
        paths_ok = _pvr_instance_matches_paths_fn(role, m3u_path, epg_path if epg_path else "")
        pc = "green" if paths_ok else "red"
        lines.append("  Paths: [COLOR {}]{}[/COLOR]".format(pc, "match" if paths_ok else "mismatch"))
        m3u_ok = _m3u_file_has_channels_fn(m3u_path)
        mc = "green" if m3u_ok else "red"
        m3u_size = _safe_file_size(m3u_path)
        m3u_count = _m3u_channel_count(m3u_path) if m3u_ok else 0
        lines.append("  M3U: [COLOR {}]{}[/COLOR] ({} channels, {})".format(
            mc, "has channels" if m3u_ok else "empty/missing", m3u_count, m3u_size))
        epg_ok = _epg_file_has_data_fn(epg_path) if epg_path else False
        ec = "green" if epg_ok else "red"
        epg_size = _safe_file_size(epg_path) if epg_path else "missing"
        epg_age = _safe_file_age(epg_path) if epg_path else "missing"
        lines.append("  EPG: [COLOR {}]{}[/COLOR] ({}, age {})".format(
            ec, "has data" if epg_ok else "empty/missing", epg_size, epg_age))
        if role == "main":
            health = _live_pvr_epg_health(pnum)
            if health.get("issues"):
                for issue in health["issues"]:
                    lines.append("  [COLOR yellow]Issue: {}[/COLOR]".format(issue))
            else:
                lines.append("  [COLOR green]All checks OK[/COLOR]")
        lines.append("")
    lines.append("[B]EPG Database Integrity[/B]")
    try:
        import sqlite3 as _sqlite3
        db_dir = xbmcvfs.translatePath("special://profile/Database")
        tv_db = None
        epg_db = None
        for fname in os.listdir(db_dir):
            fpath = os.path.join(db_dir, fname)
            try:
                sz = os.path.getsize(fpath)
            except OSError:
                continue
            if fname.startswith("TV") and fname.endswith(".db") and sz > 0:
                if tv_db is None or fname > os.path.basename(tv_db):
                    tv_db = fpath
            elif fname == "Epg16.db" and sz > 0:
                epg_db = fpath
        if tv_db and epg_db:
            conn = _sqlite3.connect(tv_db, timeout=5)
            mismatches = []
            try:
                conn.execute("ATTACH ? AS epgdb", (epg_db,))
                rows = conn.execute(
                    "SELECT c.sChannelName, c.idEpg, e.sName "
                    "FROM channels c JOIN epgdb.epg e ON c.idEpg = e.idEpg "
                    "WHERE c.iClientId IN ("
                    "  SELECT idClient FROM clients WHERE sAddonID = 'pvr.iptvsimple'"
                    ") AND c.idEpg > 0 AND c.sChannelName != e.sName"
                ).fetchall()
                mismatches = [(r[0], r[1], r[2]) for r in rows]
                conn.execute("DETACH epgdb")
            finally:
                conn.close()
            if mismatches:
                lines.append("  [COLOR red]{} mismatched EPG mapping(s)[/COLOR]".format(len(mismatches)))
                for ch_name, epg_id, epg_name in mismatches[:5]:
                    lines.append("  [COLOR yellow]{0} -> idEpg={1} -> {2}[/COLOR]".format(ch_name, epg_id, epg_name))
                if len(mismatches) > 5:
                    lines.append("  ... and {0} more".format(len(mismatches) - 5))
                lines.append("  [COLOR yellow]Fix: run Hard Reset PVR/EPG[/COLOR]")
            else:
                lines.append("  [COLOR green]All EPG channel mappings correct[/COLOR]")
        else:
            lines.append("  [COLOR yellow]Database files not found[/COLOR]")
    except Exception as exc:
        lines.append("  [COLOR red]Check failed: {0}[/COLOR]".format(exc))
    return lines