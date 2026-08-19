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


class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


OFN_FILEMUSTEXIST = 0x00001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_EXPLORER = 0x00080000


def browse_for_file(title: str = "Select a file", filter_spec: str = "",
                    initial_dir: str = "") -> Optional[str]:
    """Blocking native file-open dialog. Returns the chosen path or None.

    ``filter_spec`` is the Win32 double-NUL filter form, given here as
    ``"Meshes (*.mesh)|*.mesh|All files (*.*)|*.*"`` — the editor needs a real
    filesystem path for the mesh/texture to import, which a browser file input
    can never hand back.
    """
    if sys.platform != "win32":
        return None
    spec = filter_spec or "All files (*.*)|*.*"
    filt = "\0".join(spec.split("|")) + "\0\0"
    buf = ctypes.create_unicode_buffer(2048)
    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.lpstrFilter = filt
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = len(buf)
    ofn.lpstrTitle = title
    ofn.lpstrInitialDir = initial_dir or None
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER
    comdlg32 = ctypes.windll.comdlg32
    comdlg32.GetOpenFileNameW.restype = wintypes.BOOL
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    if not comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return None
    return buf.value or None


OFN_OVERWRITEPROMPT = 0x00000002


def browse_for_save(title: str = "Save as", filter_spec: str = "",
                    initial_dir: str = "", default_name: str = "",
                    default_ext: str = "") -> Optional[str]:
    """Blocking native Save-As dialog. Returns the chosen path or None.

    The counterpart to :func:`browse_for_file`: exporting a unit pack has to end
    up somewhere the user picked, and a browser download would hand back a name
    with no path — which is no use to a server that has to write the file itself.
    Windows does the overwrite prompt for us (``OFN_OVERWRITEPROMPT``).
    """
    if sys.platform != "win32":
        return None
    spec = filter_spec or "All files (*.*)|*.*"
    filt = "\0".join(spec.split("|")) + "\0\0"
    buf = ctypes.create_unicode_buffer(2048)
    if default_name:
        buf.value = default_name
    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.lpstrFilter = filt
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = len(buf)
    ofn.lpstrTitle = title
    ofn.lpstrInitialDir = initial_dir or None
    ofn.lpstrDefExt = default_ext or None
    ofn.Flags = OFN_PATHMUSTEXIST | OFN_OVERWRITEPROMPT | OFN_EXPLORER
    comdlg32 = ctypes.windll.comdlg32
    comdlg32.GetSaveFileNameW.restype = wintypes.BOOL
    comdlg32.GetSaveFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    if not comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
        return None
    return buf.value or None


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


def reveal(path: str) -> bool:
    """Show ``path`` in the OS file manager, with the file itself selected.

    The same "the server IS this machine" trick as the dialogs above: a browser
    page cannot open a folder, but the process serving it can.

    Windows is the fussy one. ``explorer /select,<path>`` needs the comma glued
    to the switch and the path quoted *inside* the same argument, and passing a
    LIST does the opposite: :func:`subprocess.list2cmdline` wraps the whole
    ``/select,<a path with a space in it>`` token in quotes the moment the path
    has a space in it, Explorer fails to parse the switch, and it silently opens
    the user's Documents folder instead. Every real mod path has a space
    in it somewhere, so this passes one command STRING and quotes the path
    itself. ``normpath`` goes with it: Explorer will not follow forward slashes.

    Returns whether the file manager was launched. Explorer answers 1 even on
    success, so the exit code is not worth waiting for; anything that stops the
    process starting at all raises and comes back False.
    """
    import os
    import subprocess
    target = os.path.normpath(os.path.abspath(path))
    if not os.path.exists(target):
        return False
    try:
        if sys.platform == "win32":
            # one command string, path quoted inside the /select argument
            subprocess.Popen('explorer /select,"%s"' % target)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target])
        else:
            # no portable "select the file" on Linux — open the folder it is in
            subprocess.Popen(["xdg-open", os.path.dirname(target)])
    except OSError:
        return False
    return True
