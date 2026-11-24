

class AddonRuntime:
    """Minimal runtime context for Xstream Pro addon.

    Carries the objects that moved modules need from addon.py.
    Persistent caches and locks remain as module-level state in their
    own modules (settings.py, cache.py, epg.py) because
    reuselanguageinvoker=true keeps module state alive across calls.
    """

    def __init__(self, addon, addon_handle, base_url, args, mode, pm):
        self.addon = addon
        self.addon_handle = addon_handle
        self.base_url = base_url
        self.args = args
        self.mode = mode
        self.pm = pm