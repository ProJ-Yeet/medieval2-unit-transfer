"""Native Windows folder-picker dialog for the Settings "Browse..." button.

The UI is a browser page, and browsers deliberately never expose a real
filesystem path from an `<input type="file">` picker. But the server IS this
machine, so it can pop the OS's own folder dialog (`SHBrowseForFolderW`) and
hand the chosen path back over the API — the same trick a desktop app would
use, just triggered over HTTP instead of a local button handler.

ctypes + shell32 only (no tkinter): the portable build's embeddable Python
doesn't carry Tcl/Tk, but ctypes is always part of the stdlib.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional

BIF_RETURNONLYFSDIRS = 0x0001
BIF_NEWDIALOGSTYLE = 0x0040


class _BROWSEINFO(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wintypes.LPWSTR),
        ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    ]


# Explicit restype/argtypes: without them ctypes assumes a 32-bit int return,
# which truncates SHBrowseForFolderW's pointer on 64-bit Python and segfaults
# the moment it's dereferenced.
_shell32 = ctypes.windll.shell32
_ole32 = ctypes.windll.ole32
_shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
_shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFO)]
_shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
_shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
_ole32.CoTaskMemFree.restype = None
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]


def browse_for_folder(title: str = "Select a folder") -> Optional[str]:
    """Blocking native folder-picker. Returns the chosen path, or None if the
    user cancelled (or this isn't Windows)."""
    if sys.platform != "win32":
        return None
    ctypes.windll.ole32.CoInitialize(None)
    try:
        display_name = ctypes.create_unicode_buffer(260)
        bi = _BROWSEINFO()
        bi.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
        bi.lpszTitle = title
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
        pidl = _shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return None
        try:
            path_buf = ctypes.create_unicode_buffer(260)
            _shell32.SHGetPathFromIDListW(pidl, path_buf)
            return path_buf.value or None
        finally:
            _ole32.CoTaskMemFree(pidl)
    finally:
        ctypes.windll.ole32.CoUninitialize()
