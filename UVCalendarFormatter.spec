# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

sys.path.insert(0, SPECPATH)
from core import __version__


executable_name = f"UV-Calendar-Formatter-v{__version__}"
version_parts = tuple(int(part) for part in __version__.split("."))
if len(version_parts) != 3:
    raise ValueError("Application version must have exactly three numeric parts")
windows_version = (*version_parts, 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=windows_version, prodvers=windows_version),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("FileDescription", "UV Calendar Formatter"),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", "UV-Calendar-Formatter"),
                        StringStruct("OriginalFilename", f"{executable_name}.exe"),
                        StringStruct("ProductName", "UV Calendar Formatter"),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("core/ui/calendar_formatter.tcss", "core/ui")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=executable_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    contents_directory="runtime",
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    version=version_info,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="UV-Calendar-Formatter",
)
