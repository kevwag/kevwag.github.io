"""PVR constants for Xstream Pro addon.

Instance IDs, names, group prefixes, setting keys, and fallback defaults.
"""

PVR_MAIN_INSTANCE_ID = 31
PVR_FAVS_INSTANCE_ID = 32
PVR_SPORTS_INSTANCE_ID = 33
PVR_SPORTS_FAVS_INSTANCE_ID = 34

PVR_INSTANCE_NAME = "Xstream Pro - Live TV"
PVR_FAVS_INSTANCE_NAME = "Xstream Pro - Favorites"
PVR_SPORTS_INSTANCE_NAME = "Xstream Pro - Sports TV"
PVR_SPORTS_FAVS_INSTANCE_NAME = "Xstream Pro - Sports Favorites"

PVR_LIVE_GROUP_PREFIX = "Live TV - "
PVR_LIVE_GROUP_PREFIX_TEXT = "Live TV - "
PVR_SPORTS_GROUP_PREFIX = "Sports TV - "

PVR_LEGACY_LIVE_PREFIXES = ("Live TV - ", "Xstream Pro - ")
PVR_LEGACY_SPORTS_PREFIXES = (
    "Sports TV - ",
    "Xstream Pro Sports TV - ",
    "Xstream Pro Sports TV",
    "Sports TV",
)
PVR_FAVS_GROUP_PREFIXES = ("★ Favorites - ", "Xstream Pro Favorites - ")
PVR_SPORTS_FAVS_GROUP_PREFIXES = ("★ Sports Favorites - ", "Xstream Pro Sports Favorites - ")

PVR_LEGACY_MAIN_NAMES = ("Xstream Pro",)

PVR_FILE_SLUG = "xstream_pro"
PVR_KEYMAP_VERSION = "4"

PVR_MAIN_INSTANCE_SETTING = "pvr_main_instance_id"
PVR_FAVS_INSTANCE_SETTING = "pvr_favs_instance_id"
PVR_SPORTS_INSTANCE_SETTING = "pvr_sports_instance_id"
PVR_SPORTS_FAVS_INSTANCE_SETTING = "pvr_sports_favs_instance_id"

PVR_INSTANCE_SETTINGS = {
    "main": PVR_MAIN_INSTANCE_SETTING,
    "favs": PVR_FAVS_INSTANCE_SETTING,
    "sports": PVR_SPORTS_INSTANCE_SETTING,
    "sports_favs": PVR_SPORTS_FAVS_INSTANCE_SETTING,
}

PVR_INSTANCE_FALLBACKS = {
    "main": PVR_MAIN_INSTANCE_ID,
    "favs": PVR_FAVS_INSTANCE_ID,
    "sports": PVR_SPORTS_INSTANCE_ID,
    "sports_favs": PVR_SPORTS_FAVS_INSTANCE_ID,
}