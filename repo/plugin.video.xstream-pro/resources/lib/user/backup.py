"""Backup and restore helpers for Xstream Pro."""

import datetime
import json
import os
import re
import zipfile

import xbmc
import xbmcgui
import xbmcvfs


BACKUP_SCHEMA_VERSION = "1"
_BACKUP_MAX_FILE_SIZE = 50 * 1024 * 1024
_BACKUP_MAX_TOTAL_SIZE = 250 * 1024 * 1024
_BACKUP_MAX_FILES = 500

_BACKUP_ALLOWED_PREFIXES = (
    "settings.xml",
    "favorites_global.json",
    "favorites_1.json",
    "favorites_2.json",
    "favorites_3.json",
    "favorites_4.json",
    "favorites_5.json",
    "favorites_6.json",
    "favorites_7.json",
    "favorites_8.json",
    "favorites_9.json",
    "favorites_10.json",
    "pvr_favorites_",
    "main_menu_order_",
    "hidden_subcats_",
    "hidden_items_",
    "category_prefs.json",
    "watch_history_",
    "resume_points_",
    "search_history_",
    "watched_movies_",
    "watched_episodes_",
    "backup_folder.txt",
)

addon = None
_log = None
_t = None
_safe_fsync = None
_cache_clear_all = None


def init(addon_obj, log_fn, translate_fn, safe_fsync_fn, cache_clear_all_fn):
    global addon, _log, _t, _safe_fsync, _cache_clear_all
    addon = addon_obj
    _log = log_fn
    _t = translate_fn
    _safe_fsync = safe_fsync_fn
    _cache_clear_all = cache_clear_all_fn


def get_default_downloads_dir():
    if xbmc.getCondVisibility("System.Platform.Android"):
        return "/storage/emulated/0/Download/"
    return xbmcvfs.translatePath("special://profile/downloads/")


def get_backup_folder_path():
    return os.path.join(
        xbmcvfs.translatePath(addon.getAddonInfo("profile")), "backup_folder.txt"
    )


def read_backup_folder():
    path = get_backup_folder_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ""


def write_backup_folder(path):
    file_path = get_backup_folder_path()
    tmp = file_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(path)
        try:
            f.flush()
            _safe_fsync(f)
        except OSError:
            pass
    os.replace(tmp, file_path)


def view_backup_path():
    """Show the current backup folder path in a dialog."""
    path = read_backup_folder() or xbmcvfs.translatePath("special://home")
    xbmcgui.Dialog().ok(_t(30042), path)


def change_backup_folder():
    dialog = xbmcgui.Dialog()
    chosen = dialog.browseSingle(3, _t(30789), "", "", False, False, "")
    if not chosen:
        return
    write_backup_folder(chosen)
    addon.setSetting("backup_folder_display", chosen)
    xbmcgui.Dialog().notification("Xstream Pro", _t(30791))


def build_backup_manifest(profile_path):
    """Build manifest dict from files present in profile dir."""
    files = []
    profiles_found = set()
    for fname in sorted(os.listdir(profile_path)):
        if not any(fname.startswith(p) for p in _BACKUP_ALLOWED_PREFIXES):
            continue
        fpath = os.path.join(profile_path, fname)
        if not os.path.isfile(fpath):
            continue
        ftype = "unknown"
        if fname == "settings.xml":
            ftype = "settings"
        elif fname.startswith("favorites"):
            ftype = "favorites"
        elif fname.startswith("pvr_favorites_"):
            ftype = "pvr_favorites"
            match = re.search(r"pvr_favorites_(\d+)", fname)
            if match:
                profiles_found.add(int(match.group(1)))
        elif fname.startswith("main_menu_order_"):
            ftype = "menu_order"
        elif fname.startswith("hidden_"):
            ftype = "hidden"
        elif fname == "category_prefs.json":
            ftype = "category_prefs"
        elif fname.startswith("watch_history_"):
            ftype = "watch_history"
        elif fname.startswith("resume_points_"):
            ftype = "resume_points"
        files.append({"path": fname, "type": ftype})
    return {
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "addon_id": addon.getAddonInfo("id"),
        "addon_name": addon.getAddonInfo("name"),
        "addon_version": addon.getAddonInfo("version"),
        "created_at": datetime.datetime.now().isoformat(),
        "profiles": sorted(list(profiles_found)),
        "files": files,
    }


def validate_zip_manifest(manifest, zip_entries):
    """Validate manifest integrity and compatibility before extraction."""
    if "addon_id" not in manifest:
        raise ValueError("Backup manifest missing addon_id")
    if manifest["addon_id"] != addon.getAddonInfo("id"):
        raise ValueError(
            f"Backup addon_id mismatch: expected {addon.getAddonInfo('id')}, "
            f"got {manifest['addon_id']}"
        )
    schema = manifest.get("backup_schema_version", "0")
    if schema != BACKUP_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported backup schema version: {schema} (expected {BACKUP_SCHEMA_VERSION})"
        )
    missing = [f["path"] for f in manifest["files"] if f["path"] not in zip_entries]
    if missing:
        raise ValueError(f"Backup is incomplete, missing: {missing}")


def backup_settings():
    dialog = xbmcgui.Dialog()
    options = [_t(30794), _t(30795)]
    choice = dialog.select(_t(30682), options)
    if choice < 0:
        return

    if choice == 0:
        backup_dir = get_default_downloads_dir()
        if not backup_dir or not os.path.isdir(backup_dir):
            xbmcgui.Dialog().notification("Xstream Pro", _t(30790))
            return
    else:
        chosen = dialog.browseSingle(3, _t(30789), "", "", False, False, "")
        if not chosen:
            return
        backup_dir = chosen
        write_backup_folder(chosen)

    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    version = addon.getAddonInfo("version")
    backup_path = os.path.join(
        backup_dir, f"xstream-pro-{version}-backup-{timestamp}.zip"
    )

    try:
        manifest = build_backup_manifest(profile_path)
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup_manifest.json", json.dumps(manifest, indent=2))
            for entry in manifest["files"]:
                fname = entry["path"]
                fpath = os.path.join(profile_path, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, fname)
        _log(f"Backup created: {backup_path} ({len(manifest['files'])} files)")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30089))
    except Exception as e:
        _log(f"Backup failed: {e}")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30090))


def finalize_restore(profile_path, manifest=None):
    """Common post-restore steps: credentials flag, cache clear, PVR favorites, PVR sync."""
    flag_file = os.path.join(profile_path, "credentials_saved")
    if not os.path.exists(flag_file):
        with open(flag_file, "w", encoding="utf-8") as f:
            f.write("1")

    try:
        _cache_clear_all()
        _log("All caches cleared after restore")
    except Exception as e:
        _log(f"Cache clear after restore warning: {e}")

    defer_flag = os.path.join(profile_path, "pvr_sync_after_profile_load.flag")
    with open(defer_flag, "w", encoding="utf-8") as f:
        f.write("1")
    _log("PVR sync deferred until PVR-linked profile is loaded")

    xbmc.executebuiltin(
        "Container.Update(plugin://plugin.video.xstream-pro/,replace)"
    )


def restore_settings():
    """Restore from a Pro backup ZIP. Only manifest-based backups are accepted."""
    dialog = xbmcgui.Dialog()
    options = [_t(30794), _t(30796)]
    choice = dialog.select(_t(30683), options)
    if choice < 0:
        return

    if choice == 0:
        custom = read_backup_folder()
        if not custom or not os.path.isdir(custom):
            xbmcgui.Dialog().notification("Xstream Pro", _t(30790))
            return
        start_dir = custom
    else:
        start_dir = ""

    zip_path = dialog.browse(1, _t(30337), "", ".zip", False, False, start_dir)
    if not zip_path:
        return

    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    progress = xbmcgui.DialogProgress()
    progress.create("Xstream Pro", _t(30879))

    try:
        progress.update(5, _t(30880))
        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_entries = set(zf.namelist())
            manifest_names = [
                n for n in zip_entries if n.endswith("backup_manifest.json")
            ]

            if len(manifest_names) != 1:
                raise ValueError("Backup must contain exactly one backup_manifest.json")

            manifest = json.loads(zf.read(manifest_names[0]).decode("utf-8"))
            validate_zip_manifest(manifest, zip_entries)
            restore_modern_backup(zf, manifest, profile_path, progress)

    except ValueError as e:
        _log(f"Restore validation failed: {e}")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30092))
    except Exception as e:
        _log(f"Restore failed: {e}")
        xbmcgui.Dialog().notification("Xstream Pro", _t(30092))
    finally:
        try:
            progress.close()
        except Exception:
            pass


def safe_backup_member(name):
    normalized = name.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    if not parts or any(p == ".." for p in parts):
        return None
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", normalized):
        return None
    base = parts[0]
    if not any(base.startswith(p) for p in _BACKUP_ALLOWED_PREFIXES):
        return None
    return "/".join(parts)


def restore_modern_backup(zf, manifest, profile_path, progress=None):
    """Restore a backup that has a valid manifest (schema v2+)."""
    files = manifest["files"]
    if len(files) > _BACKUP_MAX_FILES:
        raise ValueError("Backup contains too many files")
    total = len(files)
    total_bytes = 0
    profile_real = os.path.abspath(profile_path)
    for idx, entry in enumerate(files):
        fname = entry["path"]
        safe_name = safe_backup_member(fname)
        if not safe_name:
            _log(f"Skipped unsafe backup entry: {fname}")
            continue
        info = zf.getinfo(safe_name)
        if info.file_size > _BACKUP_MAX_FILE_SIZE:
            raise ValueError(f"Backup entry too large: {safe_name}")
        total_bytes += info.file_size
        if total_bytes > _BACKUP_MAX_TOTAL_SIZE:
            raise ValueError("Backup restore size limit exceeded")
        target = os.path.abspath(os.path.normpath(os.path.join(profile_path, safe_name)))
        if os.path.commonpath([profile_real, target]) != profile_real:
            _log(f"Skipped unsafe backup entry: {safe_name}")
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp_target = target + ".tmp"
        with zf.open(info, "r") as src, open(tmp_target, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
            try:
                dst.flush()
                _safe_fsync(dst)
            except OSError:
                pass
        os.replace(tmp_target, target)
        if progress and total:
            pct = 10 + int(((idx + 1) / total) * 30)
            progress.update(pct, _t(30881))

    if progress:
        progress.update(45, _t(30882))
    sync_restored_settings()

    if progress:
        progress.update(60, _t(30883))
    try:
        for n in range(1, 11):
            has_xtream = bool(addon.getSetting(f"profile_{n}_xtream_url"))
            has_m3u = bool(addon.getSetting(f"profile_{n}_m3u"))
            source_type = addon.getSetting(f"profile_{n}_source_type")
            if has_m3u and not has_xtream:
                if source_type != "M3U":
                    addon.setSetting(f"profile_{n}_source_type", "M3U")
                    _log(f"Restored profile {n} source_type inferred as M3U")
            elif has_xtream and source_type != "Xtream Codes":
                addon.setSetting(f"profile_{n}_source_type", "Xtream Codes")
                _log(f"Restored profile {n} source_type inferred as Xtream Codes")
            if has_xtream or has_m3u:
                enabled = addon.getSetting(f"profile_{n}_enabled")
                if enabled != "true":
                    addon.setSetting(f"profile_{n}_enabled", "true")
                    _log(f"Auto-enabled profile {n} after restore")
    except Exception as e:
        _log(f"Source type inference after restore warning: {e}")

    if progress:
        progress.update(80, _t(30884))
    finalize_restore(profile_path, manifest=manifest)

    if progress:
        progress.update(100, _t(30885))
    xbmcgui.Dialog().notification("Xstream Pro", _t(30091))


def sync_restored_settings():
    """Force Kodi to reload restored settings.xml into its live cache."""
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    settings_path = os.path.join(profile_path, "settings.xml")
    try:
        import xml.etree.ElementTree as ET

        try:
            tree = ET.parse(settings_path)
        except ET.ParseError as e:
            _log(f"Restored settings.xml is malformed: {e}")
            raise ValueError(f"Corrupted settings.xml in backup: {e}")

        restored_count = 0
        for setting in tree.findall(".//setting"):
            sid = setting.get("id")
            if sid is None:
                continue
            val = (setting.text or "").strip()
            if val:
                addon.setSetting(sid, val)
                restored_count += 1
        _log(f"Synced restored settings.xml: {restored_count} restored")
    except Exception as e:
        _log(f"Settings sync warning: {e}")
