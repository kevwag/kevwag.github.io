import hashlib
import json
import os
import sqlite3
import threading
import time

import xbmc
import xbmcaddon
import xbmcvfs

ADDON_ID = "plugin.video.xstream-pro"
# Module-level cache and connection state is intentional. Kodi keeps modules
# alive with reuselanguageinvoker=true, so these locks protect shared state
# accessed by route calls and background workers without moving it into runtime.
_MEM = {}
_MEM_LOCK = threading.Lock()
_ADDON = None
_DB_PATH = None
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()
_CONN_LOCK = threading.RLock()
_CONN = None


def _addon():
    global _ADDON
    if _ADDON is None:
        _ADDON = xbmcaddon.Addon(ADDON_ID)
    return _ADDON


def _db_path():
    global _DB_PATH
    if _DB_PATH is None:
        profile = xbmcvfs.translatePath(_addon().getAddonInfo("profile"))
        folder = os.path.join(profile, "cache")
        os.makedirs(folder, exist_ok=True)
        _DB_PATH = os.path.join(folder, "xstream_cache.db")
    return _DB_PATH


def _init_schema(db):
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS kv_cache ("
        "namespace TEXT NOT NULL, "
        "cache_key TEXT NOT NULL, "
        "payload TEXT NOT NULL, "
        "expires INTEGER NOT NULL, "
        "created INTEGER NOT NULL, "
        "PRIMARY KEY(namespace, cache_key))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS meta_cache ("
        "media_type TEXT NOT NULL, "
        "tmdb_id TEXT NOT NULL, "
        "payload TEXT NOT NULL, "
        "expires INTEGER NOT NULL, "
        "PRIMARY KEY(media_type, tmdb_id))"
    )
    db.commit()


def _get_conn():
    global _CONN, _SCHEMA_READY
    if _CONN is not None:
        try:
            _CONN.execute("SELECT 1")
            return _CONN
        except Exception:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
    db = sqlite3.connect(_db_path(), timeout=20, check_same_thread=False)
    db.execute("PRAGMA synchronous=NORMAL")
    if not _SCHEMA_READY:
        with _SCHEMA_LOCK:
            if not _SCHEMA_READY:
                _init_schema(db)
                _SCHEMA_READY = True
    _CONN = db
    return db


def _reset_conn():
    global _CONN
    with _CONN_LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None


def make_key(*parts):
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def get(namespace, cache_key):
    now = int(time.time())
    mem_key = (namespace, cache_key)
    with _MEM_LOCK:
        item = _MEM.get(mem_key)
    if item and item[0] > now:
        return item[1]
    try:
        with _CONN_LOCK:
            db = _get_conn()
            row = db.execute(
                "SELECT payload, expires FROM kv_cache WHERE namespace=? AND cache_key=?",
                (namespace, cache_key),
            ).fetchone()
            if not row:
                return None
            payload, expires = row
            if int(expires) <= now:
                db.execute("DELETE FROM kv_cache WHERE namespace=? AND cache_key=?", (namespace, cache_key))
                db.commit()
                return None
        data = json.loads(payload)
        with _MEM_LOCK:
            _MEM[mem_key] = (int(expires), data)
        return data
    except Exception:
        _reset_conn()
        return None


def set(namespace, cache_key, payload, ttl_seconds):
    now = int(time.time())
    expires = now + int(ttl_seconds)
    payload_json = json.dumps(payload, ensure_ascii=False)
    with _MEM_LOCK:
        _MEM[(namespace, cache_key)] = (expires, payload)
    try:
        with _CONN_LOCK:
            db = _get_conn()
            db.execute(
                "INSERT OR REPLACE INTO kv_cache VALUES (?, ?, ?, ?, ?)",
                (namespace, cache_key, payload_json, expires, now),
            )
            db.commit()
    except Exception as exc:
        _reset_conn()
        xbmc.log("[Xstream Pro Cache] write failed: {0}".format(exc), xbmc.LOGWARNING)


def delete(namespace, cache_key):
    with _MEM_LOCK:
        _MEM.pop((namespace, cache_key), None)
    try:
        with _CONN_LOCK:
            db = _get_conn()
            db.execute("DELETE FROM kv_cache WHERE namespace=? AND cache_key=?", (namespace, cache_key))
            db.commit()
    except Exception:
        _reset_conn()


def clear_namespace(namespace):
    with _MEM_LOCK:
        keys_to_remove = [k for k in _MEM if k[0] == namespace]
        for k in keys_to_remove:
            _MEM.pop(k, None)
    try:
        with _CONN_LOCK:
            db = _get_conn()
            db.execute("DELETE FROM kv_cache WHERE namespace=?", (namespace,))
            db.commit()
    except Exception:
        _reset_conn()


def meta_get(media_type, tmdb_id):
    now = int(time.time())
    mem_key = ("meta", media_type, str(tmdb_id))
    with _MEM_LOCK:
        item = _MEM.get(mem_key)
    if item and item[0] > now:
        return item[1]
    try:
        with _CONN_LOCK:
            db = _get_conn()
            row = db.execute(
                "SELECT payload, expires FROM meta_cache WHERE media_type=? AND tmdb_id=?",
                (media_type, str(tmdb_id)),
            ).fetchone()
            if not row:
                return None
            payload, expires = row
            if int(expires) <= now:
                db.execute("DELETE FROM meta_cache WHERE media_type=? AND tmdb_id=?", (media_type, str(tmdb_id)))
                db.commit()
                return None
        data = json.loads(payload)
        with _MEM_LOCK:
            _MEM[mem_key] = (int(expires), data)
        return data
    except Exception:
        _reset_conn()
        return None


def meta_get_many(pairs):
    now = int(time.time())
    results = {}
    missing = []
    for media_type, tmdb_id in pairs or []:
        media_type = str(media_type or "")
        tmdb_id = str(tmdb_id or "")
        if not media_type or not tmdb_id:
            continue
        key = (media_type, tmdb_id)
        if key in results:
            continue
        mem_key = ("meta", media_type, tmdb_id)
        with _MEM_LOCK:
            item = _MEM.get(mem_key)
        if item and item[0] > now:
            results[key] = item[1]
        else:
            missing.append(key)
    if not missing:
        return results
    try:
        with _CONN_LOCK:
            db = _get_conn()
            by_type = {}
            for media_type, tmdb_id in missing:
                by_type.setdefault(media_type, []).append(tmdb_id)
            for media_type, ids in by_type.items():
                placeholders = ",".join("?" for _ in ids)
                rows = db.execute(
                    "SELECT media_type, tmdb_id, payload, expires FROM meta_cache "
                    "WHERE media_type=? AND tmdb_id IN ({0})".format(placeholders),
                    [media_type] + ids,
                ).fetchall()
                for row_media_type, row_tmdb_id, payload, expires in rows:
                    if int(expires) <= now:
                        continue
                    data = json.loads(payload)
                    key = (row_media_type, row_tmdb_id)
                    results[key] = data
                    with _MEM_LOCK:
                        _MEM[("meta", row_media_type, row_tmdb_id)] = (int(expires), data)
    except Exception:
        _reset_conn()
    return results


def meta_set(media_type, tmdb_id, payload, ttl_seconds=604800):
    expires = int(time.time()) + int(ttl_seconds)
    payload_json = json.dumps(payload, ensure_ascii=False)
    with _MEM_LOCK:
        _MEM[("meta", media_type, str(tmdb_id))] = (expires, payload)
    try:
        with _CONN_LOCK:
            db = _get_conn()
            db.execute(
                "INSERT OR REPLACE INTO meta_cache VALUES (?, ?, ?, ?)",
                (media_type, str(tmdb_id), payload_json, expires),
            )
            db.commit()
    except Exception as exc:
        _reset_conn()
        xbmc.log("[Xstream Pro Cache] meta write failed: {0}".format(exc), xbmc.LOGWARNING)


def meta_delete(media_type, tmdb_id):
    with _MEM_LOCK:
        _MEM.pop(("meta", media_type, str(tmdb_id)), None)
    try:
        with _CONN_LOCK:
            db = _get_conn()
            db.execute("DELETE FROM meta_cache WHERE media_type=? AND tmdb_id=?", (media_type, str(tmdb_id)))
            db.commit()
    except Exception:
        _reset_conn()


def clean_expired():
    now = int(time.time())
    try:
        with _CONN_LOCK:
            db = _get_conn()
            db.execute("DELETE FROM kv_cache WHERE expires <= ?", (now,))
            db.execute("DELETE FROM meta_cache WHERE expires <= ?", (now,))
            db.commit()
    except Exception:
        _reset_conn()
