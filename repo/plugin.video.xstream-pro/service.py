import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(ADDON_DIR, "resources", "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)


EPG_DB_REBUILT_FLAG = ".epg_db_rebuilt"
RESTART_PROMPT_PROP = "xstream_pro.restart_prompted"


def _prompt_restart_once(message):
    win = xbmcgui.Window(10000)
    if win.getProperty(RESTART_PROMPT_PROP) == "true":
        xbmc.log("[Xstream Pro] Restart already prompted this session; suppressing duplicate", xbmc.LOGINFO)
        return
    win.setProperty(RESTART_PROMPT_PROP, "true")
    xbmc.log("[Xstream Pro] Prompting restart: {0}".format(message), xbmc.LOGINFO)
    if xbmc.getCondVisibility("System.Platform.Android"):
        xbmcgui.Dialog().ok("Xstream Pro", message)
    else:
        xbmc.executebuiltin("RestartApp")


def _check_epg_db_rebuilt_flag():
    try:
        addon = xbmcaddon.Addon("plugin.video.xstream-pro")
        profile_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
        flag_path = os.path.join(profile_dir, EPG_DB_REBUILT_FLAG)
        if not os.path.exists(flag_path):
            return False
        xbmc.log("[Xstream Pro] EPG DB rebuilt flag found; resetting stale channel EPG IDs", xbmc.LOGINFO)
        try:
            from pvr.sync import reset_stale_channel_epg_ids
            count = reset_stale_channel_epg_ids()
            xbmc.log("[Xstream Pro] EPG ID reset result: {0} channel(s) reset".format(count), xbmc.LOGINFO)
        except Exception as exc:
            xbmc.log("[Xstream Pro] EPG ID reset failed: {0}".format(exc), xbmc.LOGWARNING)
        try:
            os.remove(flag_path)
        except OSError:
            pass
        _prompt_restart_once("EPG database was rebuilt. Restart Kodi now for correct EPG channel mappings.")
        return True
    except Exception as exc:
        xbmc.log("[Xstream Pro] EPG DB rebuilt flag check failed: {0}".format(exc), xbmc.LOGWARNING)
        return False


def _do_epg_id_safety_net():
    """Check for stale EPG ID mismatches even without the .epg_db_rebuilt flag.

    Runs after EPG guard and prefetch so that EPG XML files are known valid.
    If mismatches are found, resets stale idEpg values and restarts Kodi.

    This is a safety net: if the flag file was lost (disk cleanup, deployment
    timing, etc.) but stale idEpg mappings still exist, they get caught here.
    """
    try:
        from pvr.sync import check_stale_channel_epg_ids
        mismatches = check_stale_channel_epg_ids()
        if mismatches is None or mismatches == -1:
            return
        if mismatches <= 0:
            return
        xbmc.log("[Xstream Pro] Safety net: {0} stale EPG ID mismatch(es) detected; resetting".format(mismatches), xbmc.LOGINFO)
        try:
            from pvr.sync import reset_stale_channel_epg_ids
            reset_stale_channel_epg_ids()
        except Exception as exc:
            xbmc.log("[Xstream Pro] Safety net: EPG ID reset failed: {0}".format(exc), xbmc.LOGWARNING)
        _prompt_restart_once("EPG channel mappings were corrected. Restart Kodi now to see changes.")
    except Exception as exc:
        xbmc.log("[Xstream Pro] EPG ID safety net check failed: {0}".format(exc), xbmc.LOGWARNING)


try:
    from pvr_epg_guard import repair_pvr_epg_files
except Exception as exc:
    repair_pvr_epg_files = None
    xbmc.log("[Xstream Pro] EPG guard service unavailable: {0}".format(exc), xbmc.LOGWARNING)

try:
    from pvr_epg_guard import prefetch_stale_epg
except Exception as exc:
    prefetch_stale_epg = None
    xbmc.log("[Xstream Pro] EPG prefetch unavailable: {0}".format(exc), xbmc.LOGWARNING)

try:
    from pvr_epg_guard import check_and_schedule_epg_repair
except Exception as exc:
    check_and_schedule_epg_repair = None
    xbmc.log("[Xstream Pro] EPG periodic check unavailable: {0}".format(exc), xbmc.LOGWARNING)

try:
    from pvr_group_memory import remember_current_pvr_group
except Exception as exc:
    remember_current_pvr_group = None
    xbmc.log("[Xstream Pro] PVR group memory service unavailable: {0}".format(exc), xbmc.LOGWARNING)


xbmcgui.Window(10000).clearProperty(RESTART_PROMPT_PROP)

_epg_db_rebuilt = _check_epg_db_rebuilt_flag()

if _epg_db_rebuilt:
    xbmc.log("[Xstream Pro] EPG DB rebuilt flag processed; skipping EPG guard/prefetch this session", xbmc.LOGINFO)
else:
    _bg = xbmcgui.DialogProgressBG()
    _bg.create("Xstream Pro", "Starting Xstream Pro...")
    _step = 0
    _total = 3
    if repair_pvr_epg_files is not None:
        _step += 1
        _bg.update(int(_step / _total * 100), "Xstream Pro", "Repairing EPG files...")
        try:
            repair_pvr_epg_files()
        except Exception as exc:
            xbmc.log("[Xstream Pro] EPG guard service failed: {0}".format(exc), xbmc.LOGWARNING)

    if prefetch_stale_epg is not None:
        _step += 1
        _bg.update(int(_step / _total * 100), "Xstream Pro", "Prefetching EPG data...")
        try:
            prefetch_stale_epg()
        except Exception as exc:
            xbmc.log("[Xstream Pro] EPG prefetch failed: {0}".format(exc), xbmc.LOGWARNING)

    _step += 1
    _bg.update(int(_step / _total * 100), "Xstream Pro", "Checking EPG IDs...")
    _do_epg_id_safety_net()
    _bg.close()

EPG_CHECK_INTERVAL = 60 * 60

monitor = xbmc.Monitor()
last_epg_check = time.time()

while not monitor.abortRequested():
    if remember_current_pvr_group is not None:
        try:
            remember_current_pvr_group()
        except Exception as exc:
            xbmc.log("[Xstream Pro] PVR group memory service warning: {0}".format(exc), xbmc.LOGWARNING)

    if not _epg_db_rebuilt:
        now = time.time()
        if check_and_schedule_epg_repair is not None and now - last_epg_check >= EPG_CHECK_INTERVAL:
            last_epg_check = now
            try:
                check_and_schedule_epg_repair()
            except Exception as exc:
                xbmc.log("[Xstream Pro] EPG periodic check failed: {0}".format(exc), xbmc.LOGWARNING)

    if monitor.waitForAbort(5.0):
        break
