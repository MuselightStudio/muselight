"""Gives the app window Muselight's own identity on the Windows taskbar.

The window is a browser window, so by default the taskbar draws the browser's 16/32 px favicon copy, resized (blurry), and
groups it with the browser. Here the window is tagged with Muselight's app ID and icon (System.AppUserModel.* properties, the
same mechanism installed web apps use): the taskbar then reads the icon straight from Muselight's multi-size .ico at exactly the
size it draws, and pinning the button pins Muselight itself. Windows only; does nothing elsewhere.
"""
import ctypes
import sys
from ctypes import wintypes as W

APP_ID = "Muselight.Studio"
_done = set()


class GUID(ctypes.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        import uuid
        u = uuid.UUID(s)
        super().__init__(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", W.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", W.USHORT), ("r1", W.USHORT), ("r2", W.USHORT), ("r3", W.USHORT), ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


AUMID_FMT = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"  # System.AppUserModel.*
KEYS = {"ID": 5, "RelaunchCommand": 2, "RelaunchIconResource": 3, "RelaunchDisplayNameResource": 4}


def _set_props(hwnd, values):
    shell = ctypes.windll.shell32
    store = ctypes.c_void_p()
    iid = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")  # IPropertyStore
    if shell.SHGetPropertyStoreForWindow(W.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store)) != 0 or not store:
        return False
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    SetValue = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(vtbl[6])
    Commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[7])
    Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    try:
        # the ID goes last: the taskbar re-files the button under it, and by then the icon and relaunch command are in place
        for name in ("RelaunchIconResource", "RelaunchCommand", "RelaunchDisplayNameResource", "ID"):
            key = PROPERTYKEY(GUID(AUMID_FMT), KEYS[name])
            SetValue(store, ctypes.byref(key), ctypes.byref(PROPVARIANT(31, 0, 0, 0, values[name])))  # 31 = VT_LPWSTR
        Commit(store)
        return True
    except OSError:
        return False
    finally:
        Release(store)


def _set_icons(hwnd, ico):
    u = ctypes.windll.user32
    u.LoadImageW.restype = ctypes.c_void_p
    u.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, ctypes.c_void_p]
    dpi = u.GetDpiForWindow(W.HWND(hwnd)) or 96
    for which, metric in ((1, 11), (0, 49)):  # ICON_BIG / SM_CXICON, ICON_SMALL / SM_CXSMICON
        px = u.GetSystemMetricsForDpi(metric, dpi)
        h = u.LoadImageW(None, ico, 1, px, px, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE: the frame drawn for that size
        if h:
            u.SendMessageW(W.HWND(hwnd), 0x80, which, h)  # WM_SETICON


def windows(title="Muselight"):
    """Visible browser windows showing the app."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        if u.IsWindowVisible(h):
            buf, cls = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(64)
            u.GetWindowTextW(h, buf, 256); u.GetClassNameW(h, cls, 64)
            if buf.value == title and cls.value == "Chrome_WidgetWin_1":
                found.append(h)
        return True
    u.EnumWindows(cb, 0)
    return found


def brand(ico, relaunch, exe_icon=None):
    """Tag every open app window (once each). ico: a multi-size .ico file; relaunch: the command that starts Muselight."""
    if sys.platform != "win32":
        return 0
    n = 0
    for h in windows():
        if h in _done:
            continue
        _set_icons(h, str(ico))
        if _set_props(h, {"ID": APP_ID, "RelaunchCommand": relaunch, "RelaunchIconResource": exe_icon or str(ico),
                          "RelaunchDisplayNameResource": "Muselight"}):
            _done.add(h)
            n += 1
    return n
