# PyInstaller analysis for the internal obfush CLI.
# This file is an optional local build recipe; release workflows build Python
# distributions and do not publish or claim a configured PyInstaller release.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = [
    *collect_submodules("obfush.layers"),
    *collect_submodules("obfush.compiler"),
]
datas = collect_data_files("obfush.gui")

a = Analysis(
    ["obfush/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="obfush",
    console=True,
    debug=False,
    strip=False,
    upx=False,
)
