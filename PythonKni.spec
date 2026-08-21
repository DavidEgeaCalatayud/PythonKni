# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# The loader enumerates tools/*.py at runtime, so keep that directory available
# as data as well as collecting every dynamic module below. Assets are resolved
# relative to the frozen application root by tools.app_paths.
datas = [
    ('tools', 'tools'),
    ('assets', 'assets'),
]
binaries = []
hiddenimports = []


def local_python_modules(root_name):
    """Return import names for every local Python module below root_name."""
    modules = []
    for path in Path(root_name).rglob('*.py'):
        parts = list(path.with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        if parts:
            modules.append('.'.join(parts))
    return modules


# Dynamic imports are invisible to PyInstaller's static analysis. Build this
# list from the repository tree instead of relying on collect_submodules(),
# which requires the local package to be importable while the spec is evaluated.
hiddenimports += local_python_modules('tools')
hiddenimports += local_python_modules('pythonkni')

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
