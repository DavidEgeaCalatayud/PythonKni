# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

# The loader enumerates tools/*.py at runtime, so keep that directory available
# as data as well as collecting every dynamic module below. Assets are resolved
# relative to the frozen application root by tools.app_paths.
datas = [
    ('tools', 'tools'),
    ('assets', 'assets'),
]
binaries = []
hiddenimports = []

# Dynamic imports are invisible to PyInstaller's static analysis. Explicitly
# collect both the compatibility plugin package and the new domain package.
hiddenimports += collect_submodules('tools')
hiddenimports += collect_submodules('pythonkni')

for package in [
    'PyQt5',
    'PyPDF2',
    'pytesseract',
    'pdf2image',
    'PIL',
    'fitz',
    'docx',
    'py7zr',
    'psutil',
    'requests',
    'reportlab',
]:
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='PythonKni',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
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
    name='PythonKni',
)
