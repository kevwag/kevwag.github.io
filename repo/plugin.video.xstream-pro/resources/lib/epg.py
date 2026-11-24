import sys
import calendar
import json
import os
import time
import re
import threading
import urllib.parse
import bz2
import gzip
import io
import lzma
import zipfile

import requests
import xbmc
import xbmcaddon
import xbmcvfs

from profiles import ProfileManager
from lang import _t
from iptv import _validate_url


def _safe_fsync(f):
    try:
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
        if xbmc.getCondVisibility("System.Platform.OSX") and (
            "Containers" in profile or "Library/Caches/Kodi" in profile
        ):
            return
        os.fsync(f.fileno())
    except OSError:
        pass


_CACHE_LOCKS = {}
_CACHE_LOCKS_GUARD = threading.Lock()
# EPG fetch de-duplication is module-level on purpose. Multiple plugin entries
# can reuse this module in one Kodi process, while the lock prevents concurrent
# HTTP fetches for the same profile.
_EPG_FETCH_IN_PROGRESS = {}
_EPG_FETCH_IN_PROGRESS_LOCK = threading.Lock()
_EPG_FILE_DATA_CACHE = {}
_EPG_FILE_DATA_CACHE_LOCK = threading.Lock()
_EPG_FILE_DATA_CACHE_MAX = 32

_RE_BRACKETS = re.compile(r"\[[^\]]*\]|\([^\)]*\)")
_RE_QUALIFIERS = re.compile(
    r"\b(uhd|fhd|fullhd|full hd|hd|sd|hevc|h265|h\.265|h264|h\.264|4k|8k|50fps|60fps|25fps|backup|raw|vip|event only|bk)\b",
    re.IGNORECASE,
)
_RE_NONWORD = re.compile(r"[^\w]+", re.UNICODE)
_RE_NONDIGIT = re.compile(r"\D")
_RE_XMLTV_TZ = re.compile(r"([+-]\d{2}:?\d{2})$")


def _cache_lock(path):
    key = os.path.abspath(path)
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CACHE_LOCKS[key] = lock
        return lock

# Use defusedxml if available. Always strip XMLTV DOCTYPE before parsing so
# common XMLTV DTD declarations do not break providers, while entity expansion
# still stays blocked.
try:
    from defusedxml import ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET


def _strip_xml_doctype(payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8", "ignore")
    lowered = payload.lower()
    start = lowered.find(b"<!doctype")
    if start < 0:
        return payload

    i = start + len(b"<!doctype")
    quote = None
    bracket_depth = 0
    while i < len(payload):
        ch = payload[i]
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in (34, 39):  # " or '
            quote = ch
        elif ch == 91:  # [
            bracket_depth += 1
        elif ch == 93 and bracket_depth:  # ]
            bracket_depth -= 1
        elif ch == 62 and bracket_depth == 0:  # >
            return payload[:start] + payload[i + 1:]
        i += 1
    raise ValueError("Malformed XML DOCTYPE")


def _safe_fromstring(text, forbid_entities=True):
    # Removing the DTD prevents external DTD fetches. If the document relied on
    # custom entities, ElementTree/defusedxml will fail on unresolved references
    # instead of expanding them.
    return ET.fromstring(_strip_xml_doctype(text))


EPG_MAX_BYTES = 200 * 1024 * 1024  # 200 MB
EPG_MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024  # 300 MB

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_startup_forced_profiles = set()


def _get_timeout():
    try:
        return int(xbmcaddon.Addon().getSetting("stream_timeout") or "15")
    except ValueError:
        return 15


def _get_headers():
    custom_ua = xbmcaddon.Addon().getSetting("custom_user_agent")
    if custom_ua:
        return {"User-Agent": custom_ua}
    return HEADERS


def _read_limited_fileobj(fileobj, limit=EPG_MAX_UNCOMPRESSED_BYTES):
    chunks = []
    total = 0
    while True:
        chunk = fileobj.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError(f"EPG decompressed payload exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _payload_looks_like_xml(payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8", "ignore")
    head = payload[:512].lstrip()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:].lstrip()
    lowered = head.lower()
    return (
        lowered.startswith(b"<?xml")
        or lowered.startswith(b"<tv")
        or lowered.startswith(b"<!doctype")
    )


def _decode_epg_payload(payload, headers=None, url=""):
    headers = headers or {}
    content_encoding = (headers.get("Content-Encoding") or "").lower()
    content_type = (headers.get("Content-Type") or "").lower()
    lower_url = (url or "").lower()

    # Requests may already decompress gzip transfer encoding while the response
    # header still says gzip. If the payload is XMLTV text, never try to gunzip it.
    if _payload_looks_like_xml(payload):
        return payload

    if payload.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as gz:
            return _read_limited_fileobj(gz)

    if "gzip" in content_encoding or lower_url.endswith((".gz", ".xml.gz", ".gzip")):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as gz:
                return _read_limited_fileobj(gz)
        except (OSError, EOFError, gzip.BadGzipFile):
            if _payload_looks_like_xml(payload):
                return payload
            raise

    if (
        payload.startswith(b"PK\x03\x04")
        or lower_url.endswith(".zip")
        or "zip" in content_type
    ):
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise ValueError("EPG zip archive is empty")
            preferred = [
                n for n in names
                if n.lower().endswith((".xml", ".xmltv", ".xml.gz", ".gz"))
            ]
            name = (preferred or names)[0]
            with zf.open(name) as inner:
                inner_payload = _read_limited_fileobj(inner)
            return _decode_epg_payload(inner_payload, {}, name)

    if payload.startswith(b"BZh") or lower_url.endswith(".bz2"):
        with bz2.BZ2File(io.BytesIO(payload)) as bz:
            return _read_limited_fileobj(bz)

    if payload.startswith(b"\xfd7zXZ\x00") or lower_url.endswith((".xz", ".lzma")):
        with lzma.LZMAFile(io.BytesIO(payload)) as xz:
            return _read_limited_fileobj(xz)

    return payload


_LOG_REDACT_PATH_RE = re.compile(
    r"(/(?:live|movie|series)/)([^/?\s]+)(/?)([^/?\s]*)", re.IGNORECASE
)
_LOG_REDACT_QUERY_RE = re.compile(r"(?i)\b(password|pwd|pass|username|user|token|key|apikey|api_key|auth)=([^&\s]+)")
_LOG_MAX_LEN = 4000


def _epg_log(msg):
    safe_msg = str(msg)
    safe_msg = _LOG_REDACT_PATH_RE.sub(
        lambda m: (
            m.group(1)
            + "***REDACTED***"
            + m.group(3)
            + ("***REDACTED***" if m.group(4) else "")
        ),
        safe_msg,
    )
    safe_msg = _LOG_REDACT_QUERY_RE.sub(r"\1=***REDACTED***", safe_msg)
    if len(safe_msg) > _LOG_MAX_LEN:
        safe_msg = safe_msg[:_LOG_MAX_LEN] + "...[truncated]"
    xbmc.log(f"[Xstream Pro EPG] {safe_msg}", xbmc.LOGINFO)


def _safe_url_for_log(url):
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        if not parsed.scheme:
            return "<url>"
        path = parsed.path or "/"
        if len(path) > 80:
            path = path[:80] + "...[truncated]"
        return "{0}://<redacted-host>{1}".format(parsed.scheme, path)
    except Exception:
        return "<url>"


class EPG:
    def __init__(self, addon, profile_num=None):
        self.addon = addon
        if profile_num is not None:
            active_profile = str(profile_num)
            # Import addon.py helper via local import to avoid circular dependency

            addon_module = sys.modules.get("resources.lib.addon")
            if addon_module is not None and hasattr(
                addon_module, "_get_credentials_for_profile"
            ):
                creds = addon_module._get_credentials_for_profile(active_profile)
            else:
                # Fallback: use ProfileManager directly
                pm = ProfileManager(addon)
                original = pm.active
                try:
                    pm.active = active_profile
                    creds = pm.get_credentials()
                finally:
                    pm.active = original
        else:
            pm = ProfileManager(addon)
            creds = pm.get_credentials()
            active_profile = pm.active

        self.profile_num = str(active_profile)

        source_type = creds.get("source_type", "Xtream Codes")

        if source_type == "M3U":
            self.epg_url = creds.get("epg_m3u", "")
        else:
            self.epg_url = creds.get("epg_xtream", "")

        self._auto_detected = False
        if not self.epg_url:
            xt_url = creds.get("xtream_url", "")
            xt_user = creds.get("xtream_username", "")
            xt_pwd = creds.get("xtream_password", "")
            if xt_url and xt_user and xt_pwd:
                self.epg_url = f"{xt_url.rstrip('/')}/xmltv.php?username={urllib.parse.quote(xt_user)}&password={urllib.parse.quote(xt_pwd)}"
                self._auto_detected = True
                _epg_log("Auto-detected EPG URL from Xtream credentials")
        self.cache_hours = 4
        try:
            self.cache_hours = max(1, int(addon.getSetting("pvr_epg_refresh") or "12"))
        except ValueError:
            self.cache_hours = 12
        self.offset_hours = 0.0
        self.profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
        self.cache_file = os.path.join(
            self.profile_path, f"epg_cache_profile_{active_profile}.json"
        )
        self.programs = {}
        self.channel_names = {}
        self._program_starts = {}
        self._id_index = None
        self._name_index_unambiguous = None
        self._name_index_norm = None
        self.is_refreshing = False
        self._bg_thread = None
        self._bg_thread_current = None
        self._programs_lock = threading.RLock()

    def _ensure_profile(self):
        os.makedirs(self.profile_path, exist_ok=True)

    def _cache_valid(self):
        if not os.path.exists(self.cache_file):
            return False
        age = time.time() - os.path.getmtime(self.cache_file)
        return age < (self.cache_hours * 3600)

    def _save_cache(self):
        self._ensure_profile()
        lock = _cache_lock(self.cache_file)
        with self._programs_lock:
            programs = {
                k: [dict(p) for p in (v or [])]
                for k, v in (self.programs or {}).items()
            }
            channel_names = dict(self.channel_names or {})
            program_starts = {
                k: list(v or [])
                for k, v in (self._program_starts or {}).items()
            }
        tmp_file = "{}.{}.tmp".format(self.cache_file, threading.get_ident())
        with lock:
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "programs": programs,
                            "channel_names": channel_names,
                            "program_starts": program_starts,
                        },
                        f,
                    )
                    try:
                        f.flush()
                        _safe_fsync(f)
                    except OSError:
                        pass

                for attempt in range(5):
                    try:
                        os.replace(tmp_file, self.cache_file)
                        return
                    except PermissionError:
                        if attempt >= 4:
                            raise
                        xbmc.sleep(150 * (attempt + 1))
            finally:
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except OSError:
                    pass

    def _load_cache(self):
        try:
            with _cache_lock(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if isinstance(data, dict) and "programs" in data:
                programs = data.get("programs", {})
                channel_names = data.get("channel_names", {})
                program_starts = data.get("program_starts", {})
            else:
                programs = data
                channel_names = {}
                program_starts = {}
            _epg_log(f"Loaded cache with {len(programs)} channels")
            with self._programs_lock:
                self.programs = programs
                self.channel_names = channel_names
                self._program_starts = program_starts
                self._invalidate_channel_indexes()
        except Exception as e:
            _epg_log(f"Cache load failed: {e}")
            with self._programs_lock:
                self.programs = {}
                self.channel_names = {}
                self._program_starts = {}
                self._invalidate_channel_indexes()

    def _try_fetch_epg(self, url):
        """Try to fetch and parse EPG from a URL. Returns ET root or None on failure."""
        if not _validate_url(url):
            _epg_log(f"EPG URL blocked by SSRF protection")
            return None
        # Security: never log provider host, query params, usernames, or passwords.
        safe_url = _safe_url_for_log(url)
        _epg_log(f"Fetching EPG from {safe_url}")
        try:
            # Credentials live in the query string, so a cross-host redirect
            # would leak username/password into a third-party access log.
            # Disable automatic redirects and only follow same-host ones.
            initial_host = urllib.parse.urlparse(url).netloc.lower()
            current_url = url
            resp = None
            for _hop in range(5):
                resp = requests.get(
                    current_url,
                    headers=_get_headers(),
                    timeout=_get_timeout(),
                    allow_redirects=False,
                    stream=True,
                )
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location", "")
                    if not loc:
                        break
                    next_url = urllib.parse.urljoin(current_url, loc)
                    if not _validate_url(next_url):
                        resp.close()
                        raise ValueError("EPG redirect blocked by SSRF protection")
                    next_host = urllib.parse.urlparse(next_url).netloc.lower()
                    if next_host != initial_host:
                        resp.close()
                        raise ValueError(
                            f"EPG redirect to different host blocked (creds protection): {next_host}"
                        )
                    current_url = next_url
                    resp.close()
                    continue
                break
            else:
                if resp is not None:
                    resp.close()
                raise ValueError("EPG redirect loop")
            resp.raise_for_status()
            # Bounded read so we cannot OOM on a hostile / misconfigured EPG URL.
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > EPG_MAX_BYTES:
                    resp.close()
                    raise ValueError(f"EPG payload exceeds {EPG_MAX_BYTES} bytes")
                chunks.append(chunk)
            resp.close()
            payload = b"".join(chunks)
            payload = _decode_epg_payload(payload, resp.headers, current_url)
            root = _safe_fromstring(payload, forbid_entities=True)
            root_tag = (root.tag or "").split("}", 1)[-1].lower()
            if root_tag != "tv":
                raise ValueError(f"EPG XML root is not tv: {root_tag}")
            return root
        except Exception as e:
            _epg_log(f"EPG fetch failed for {safe_url}: {e}")
            return None

    def fetch(self):
        if not self.epg_url:
            _epg_log("No EPG URL configured")
            with self._programs_lock:
                self.programs = {}
                self.channel_names = {}
                self._program_starts = {}
                self._invalidate_channel_indexes()
            return
        root = self._try_fetch_epg(self.epg_url)
        # If auto-detected and failed, try fallback endpoint
        if root is None and self._auto_detected:
            fallback_url = self.epg_url.replace(
                "/xmltv.php?", "/get_litepanels_xmltv.php?"
            )
            if fallback_url != self.epg_url:
                _epg_log("Trying fallback EPG endpoint")
                root = self._try_fetch_epg(fallback_url)
        if root is None:
            if os.path.exists(self.cache_file):
                _epg_log("EPG fetch failed; keeping existing cached EPG")
                self._load_cache()
            else:
                with self._programs_lock:
                    self.programs = {}
                    self.channel_names = {}
                    self._program_starts = {}
                    self._invalidate_channel_indexes()
            _epg_log(
                "EPG fetch failed; notification suppressed because fetch may run in a background thread"
            )
            return

        lang_pref = ""

        programs = {}
        channel_names = {}
        for ch_el in root.findall("channel"):
            ch_id = ch_el.get("id", "")
            if ch_id:
                disp = ch_el.find("display-name")
                channel_names[ch_id] = disp.text if disp is not None else ch_id

        for prog in root.findall("programme"):
            channel = prog.get("channel", "")
            if not channel:
                continue

            titles = prog.findall("title")
            title_el = titles[0] if titles else None
            if lang_pref and titles:
                for t in titles:
                    if (t.get("lang") or "").lower() == lang_pref:
                        title_el = t
                        break

            descs = prog.findall("desc")
            desc_el = descs[0] if descs else None
            if lang_pref and descs:
                for d in descs:
                    if (d.get("lang") or "").lower() == lang_pref:
                        desc_el = d
                        break

            icon_el = prog.find("icon")

            start = prog.get("start", "")
            stop = prog.get("stop", "")

            entry = {
                "title": title_el.text if title_el is not None else _t(30702),
                "desc": desc_el.text if desc_el is not None else "",
                "icon": icon_el.get("src") if icon_el is not None else "",
                "start": start,
                "stop": stop,
                "start_timestamp": _xmltv_time_to_simple(start),
                "start_str": _xmltv_time_to_display(start),
                "stop_timestamp": _xmltv_time_to_simple(stop),
                "duration_sec": _xmltv_duration_sec(start, stop),
            }
            programs.setdefault(channel, []).append(entry)

        try:
            past_days = int(self.addon.getSetting("epg_past_days") or "3")
        except ValueError:
            past_days = 3
        cutoff = time.time() - (past_days * 86400)

        program_starts = {}
        for ch in programs:
            programs[ch] = [
                p for p in programs[ch] if _parse_xmltv_time(p["stop"]) > cutoff
            ]
            programs[ch].sort(key=lambda x: x["start"])
            _seen = set()
            _deduped = []
            for p in programs[ch]:
                _key = (p.get("start", ""), p.get("stop", ""))
                if _key in _seen:
                    continue
                _seen.add(_key)
                _deduped.append(p)
            if len(_deduped) < len(programs[ch]):
                programs[ch] = _deduped
            program_starts[ch] = [
                _parse_xmltv_time(p["start"]) for p in programs[ch]
            ]
        _epg_log(f"Parsed {len(programs)} channels from XMLTV")
        with self._programs_lock:
            self.programs = programs
            self.channel_names = channel_names
            self._program_starts = program_starts
            self._invalidate_channel_indexes()
        self._save_cache()

    def _fetch_in_background(self):
        profile_key = str(self.profile_num)
        try:
            self.is_refreshing = True
            self.fetch()
        finally:
            self.is_refreshing = False
            self._bg_thread = None
            with _EPG_FETCH_IN_PROGRESS_LOCK:
                if _EPG_FETCH_IN_PROGRESS.get(profile_key) is self._bg_thread_current:
                    _EPG_FETCH_IN_PROGRESS.pop(profile_key, None)

    def _start_background_fetch(self):
        profile_key = str(self.profile_num)
        with _EPG_FETCH_IN_PROGRESS_LOCK:
            existing = _EPG_FETCH_IN_PROGRESS.get(profile_key)
            if existing is not None and existing.is_alive():
                _epg_log(f"Profile {profile_key}: EPG fetch already in progress; using stale cache")
                return
        if self._bg_thread is None or not self._bg_thread.is_alive():
            with _EPG_FETCH_IN_PROGRESS_LOCK:
                existing = _EPG_FETCH_IN_PROGRESS.get(profile_key)
                if existing is not None and existing.is_alive():
                    _epg_log(f"Profile {profile_key}: EPG fetch started by another instance; using stale cache")
                    return
                self._bg_thread_current = threading.Thread(target=self._fetch_in_background, daemon=True)
                self._bg_thread = self._bg_thread_current
                _EPG_FETCH_IN_PROGRESS[profile_key] = self._bg_thread
            self._bg_thread.start()

    def load(self):
        global _startup_forced_profiles
        force_startup = (
            self.addon.getSetting("epg_force_refresh_startup").lower() == "true"
        )
        if force_startup and self.profile_num not in _startup_forced_profiles:
            _epg_log("Startup force refresh triggered")
            _startup_forced_profiles.add(self.profile_num)
            if os.path.exists(self.cache_file):
                self._load_cache()
            else:
                with self._programs_lock:
                    self.programs = {}
                    self.channel_names = {}
                    self._program_starts = {}
                    self._invalidate_channel_indexes()
            self._start_background_fetch()
            return
        if self._cache_valid():
            _epg_log("EPG cache is valid, loading from disk")
            self._load_cache()
            return
        # Stale-cache-first: load expired cache immediately, refresh in background
        if os.path.exists(self.cache_file):
            _epg_log("EPG cache expired, loading stale data while refreshing in background")
            self._load_cache()
        else:
            _epg_log("EPG cache missing, will fetch in background")
            with self._programs_lock:
                self.programs = {}
                self.channel_names = {}
                self._program_starts = {}
                self._invalidate_channel_indexes()
        self._start_background_fetch()

    def _invalidate_channel_indexes(self):
        self._id_index = None
        self._name_index_unambiguous = None
        self._name_index_norm = None

    def _build_channel_indexes(self):
        with self._programs_lock:
            if self._id_index is not None:
                return
            programs = self.programs or {}
            channel_names = self.channel_names or {}
            id_index = {}
            name_count = {}
            for pid in programs:
                if not programs[pid]:
                    continue
                key = str(pid).strip().casefold()
                if key:
                    id_index[key] = pid
            self._id_index = id_index
            for pid, display_name in channel_names.items():
                if not programs.get(pid):
                    continue
                raw = str(display_name or "").strip()
                key = raw.casefold()
                if key:
                    name_count[key] = name_count.get(key, 0) + 1
            name_index = {}
            for pid, display_name in channel_names.items():
                if not programs.get(pid):
                    continue
                raw = str(display_name or "").strip()
                key = raw.casefold()
                if key and name_count[key] == 1:
                    name_index[key] = pid
            self._name_index_unambiguous = name_index
            norm_index = {}
            norm_count = {}
            for pid, display_name in channel_names.items():
                if not programs.get(pid):
                    continue
                normed = self._norm_channel_name(display_name)
                if normed:
                    norm_count[normed] = norm_count.get(normed, 0) + 1
            for pid, display_name in channel_names.items():
                if not programs.get(pid):
                    continue
                normed = self._norm_channel_name(display_name)
                if normed and norm_count[normed] == 1:
                    norm_index[normed] = pid
            for pid in programs:
                if not programs[pid]:
                    continue
                normed = self._norm_channel_name(pid)
                if normed and normed not in norm_index and norm_count.get(normed, 0) == 0:
                    norm_index[normed] = pid
            self._name_index_norm = norm_index

    @staticmethod
    def _norm_channel_name(value):
        text = str(value or "").casefold()
        text = _RE_BRACKETS.sub(" ", text)
        text = _RE_QUALIFIERS.sub(" ", text)
        text = _RE_NONWORD.sub(" ", text)
        return " ".join(text.split())

    def _apply_offset(self, ts):
        if not self.offset_hours:
            return ts
        return ts + (self.offset_hours * 3600)

    def _find_channel_id(self, channel_id, channel_name=""):
        with self._programs_lock:
            programs = self.programs or {}
        if not programs:
            return None

        cid = str(channel_id or "").strip()
        cname = str(channel_name or "").strip()
        if not cid and not cname:
            return None

        self._build_channel_indexes()

        if cid and programs.get(cid):
            return cid

        cid_lower = cid.casefold() if cid else ""
        cname_lower = cname.casefold() if cname else ""

        if cid_lower:
            found = self._id_index.get(cid_lower)
            if found is not None:
                return found

        if cname_lower:
            found = self._name_index_unambiguous.get(cname_lower)
            if found is not None:
                return found
            found = self._id_index.get(cname_lower)
            if found is not None:
                return found

        cname_norm = self._norm_channel_name(cname) if cname else ""
        if cname_norm:
            found = self._name_index_norm.get(cname_norm)
            if found is not None:
                return found

        return None

    _unmatched_logged = None

    def get_programs_for_channel(self, channel_id, channel_name="", days_back=None):
        with self._programs_lock:
            programs = self.programs or {}
        matched_id = self._find_channel_id(channel_id, channel_name)
        if not matched_id:
            key = str(channel_id or channel_name)
            with self._programs_lock:
                if self._unmatched_logged is None:
                    self._unmatched_logged = set()
                if key and key not in self._unmatched_logged:
                    self._unmatched_logged.add(key)
                    _epg_log("EPG unmatched channel: id={!r} name={!r}".format(channel_id, channel_name))
            return []
        if days_back is None:
            try:
                days_back = int(self.addon.getSetting("replay_days") or "7")
            except ValueError:
                days_back = 7
        cutoff = time.time() - (days_back * 86400)
        result = []
        for prog in programs.get(matched_id, []):
            stop = self._apply_offset(_parse_xmltv_time(prog["stop"]))
            if stop and stop > cutoff:
                result.append(prog)
        return result

    def export_xmltv(self, dest_path):
        with self._programs_lock:
            programs = self.programs
            channel_names = self.channel_names
        if not programs:
            return False
        try:
            from xml.sax.saxutils import escape

            self._ensure_profile()
            tmp_path = dest_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n<tv>\n')
                for channel_id in programs:
                    name = channel_names.get(channel_id, channel_id)
                    f.write(
                        '  <channel id="{0}"><display-name>{1}</display-name></channel>\n'.format(
                            escape(str(channel_id), {'"': "&quot;"}),
                            escape(str(name)),
                        )
                    )
                for channel_id, progs in programs.items():
                    for prog in progs:
                        attrs = {
                            "start": prog.get("start", ""),
                            "stop": prog.get("stop", ""),
                            "channel": str(channel_id),
                        }
                        f.write(
                            '  <programme start="{start}" stop="{stop}" channel="{channel}">\n'.format(
                                start=escape(attrs["start"], {'"': "&quot;"}),
                                stop=escape(attrs["stop"], {'"': "&quot;"}),
                                channel=escape(attrs["channel"], {'"': "&quot;"}),
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
                f.write("</tv>\n")
                try:
                    f.flush()
                    _safe_fsync(f)
                except OSError:
                    pass
            if not epg_file_header_valid(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise ValueError("Generated XMLTV has invalid header")
            os.replace(tmp_path, dest_path)
            _epg_log(f"Exported XMLTV to {dest_path}")
            return True
        except Exception as e:
            _epg_log(f"Export XMLTV failed: {e}")
            return False


def epg_file_header_valid(epg_path):
    try:
        with open(epg_path, "rb") as f:
            head = f.read(256)
        if head.startswith(b"\xef\xbb\xbf"):
            head = head[3:]
        head = head.lstrip()
        if not head:
            return False
        if head.startswith(b"<?xml"):
            close = head.find(b"?>")
            if close < 0:
                return False
            head = head[close + 2:].lstrip()
        return head.startswith(b"<tv>") or head.startswith(b"<tv ")
    except Exception:
        return False


def clear_epg_file_data_cache():
    with _EPG_FILE_DATA_CACHE_LOCK:
        _EPG_FILE_DATA_CACHE.clear()


def _epg_file_has_data_uncached(epg_path):
    try:
        if not epg_file_header_valid(epg_path):
            return False
        scanned = 0
        max_scan = 32 * 1024 * 1024
        with open(epg_path, "r", encoding="utf-8", errors="ignore") as f:
            while scanned < max_scan:
                chunk = f.read(32768)
                if not chunk:
                    return False
                if "<programme" in chunk:
                    return True
                scanned += len(chunk)
        return False
    except Exception:
        return False


def epg_file_has_data(epg_path):
    try:
        st = os.stat(epg_path)
        key = (os.path.abspath(epg_path), st.st_size, st.st_mtime_ns)
    except (OSError, AttributeError):
        return _epg_file_has_data_uncached(epg_path)
    with _EPG_FILE_DATA_CACHE_LOCK:
        if key in _EPG_FILE_DATA_CACHE:
            return _EPG_FILE_DATA_CACHE[key]
    result = _epg_file_has_data_uncached(epg_path)
    with _EPG_FILE_DATA_CACHE_LOCK:
        if len(_EPG_FILE_DATA_CACHE) < _EPG_FILE_DATA_CACHE_MAX:
            _EPG_FILE_DATA_CACHE[key] = result
    return result


def _parse_xmltv_time(ts):
    if not ts:
        return 0
    ts = str(ts).strip()
    if not ts:
        return 0

    offset_sec = 0

    tz_match = _RE_XMLTV_TZ.search(ts)
    if tz_match:
        tz = tz_match.group(1)
        base = ts[:tz_match.start()].strip()
        digits = tz[1:].replace(":", "")
        try:
            hours = int(digits[:2])
            minutes = int(digits[2:4])
            if hours <= 14 and minutes <= 59:
                sign = 1 if tz[0] == "+" else -1
                offset_sec = sign * (hours * 3600 + minutes * 60)
                ts = base
        except (ValueError, IndexError):
            offset_sec = 0

    ts = ts.rstrip("Z").strip()
    compact = _RE_NONDIGIT.sub("", ts)
    candidates = []
    if len(compact) == 14:
        candidates.append((compact, "%Y%m%d%H%M%S"))
    elif len(compact) == 12:
        candidates.append((compact, "%Y%m%d%H%M"))

    if ts not in (value for value, _fmt in candidates):
        if len(ts) == 14 and ts.isdigit():
            candidates.append((ts, "%Y%m%d%H%M%S"))
        elif len(ts) == 12 and ts.isdigit():
            candidates.append((ts, "%Y%m%d%H%M"))

    for value, fmt in candidates:
        try:
            parsed = time.strptime(value, fmt)
            return calendar.timegm(parsed) - offset_sec
        except ValueError:
            continue
    return 0


def _xmltv_time_to_simple(ts):
    t = _parse_xmltv_time(ts)
    if not t:
        return ts
    return time.strftime("%Y-%m-%d:%H-%M", time.localtime(t))


def _xmltv_time_to_display(ts):
    t = _parse_xmltv_time(ts)
    if not t:
        return ""
    return time.strftime("%d/%m %H:%M", time.localtime(t))


def _xmltv_duration_sec(start, stop):
    s = _parse_xmltv_time(start)
    e = _parse_xmltv_time(stop)
    if s and e:
        return int(e - s)
    return 3600
