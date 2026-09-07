# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# The loader enumerates tools/*.py at runtime, so keep that directory available
# as data as well as collecting every dynamic module below. Assets are resolved
# relative to the frozen application root by tools.app_paths.
datas = [
    ('tools', 'tools'),
    ('assets', 'assets'),
    ('third_party/NOTICE.md', 'third_party'),
    ('third_party/nerva.lock.json', 'third_party'),
    ('third_party/tailcat.lock.json', 'third_party'),
    ('third_party/trippy.lock.json', 'third_party'),
]
binaries = []
hiddenimports = []

nerva_binary = Path('third_party/nerva/nerva.exe')
if nerva_binary.is_file():
    binaries.append((str(nerva_binary), 'third_party/nerva'))
    for optional_name in ('source.json', 'LICENSE', 'LICENSE.txt', 'LICENSE.md'):
        optional_path = nerva_binary.parent / optional_name
        if optional_path.is_file():
            datas.append((str(optional_path), 'third_party/nerva'))

tailcat_binary = Path('third_party/tailcat/tailcat.exe')
if tailcat_binary.is_file():
    binaries.append((str(tailcat_binary), 'third_party/tailcat'))
    for optional_name in ('source.json', 'LICENSE', 'README.md'):
        optional_path = tailcat_binary.parent / optional_name
        if optional_path.is_file():
            datas.append((str(optional_path), 'third_party/tailcat'))

trippy_binary = Path('third_party/trippy/trip.exe')
if trippy_binary.is_file():
    binaries.append((str(trippy_binary), 'third_party/trippy'))
    for optional_name in ('source.json', 'LICENSE', 'LICENSE.txt', 'README.md'):
        optional_path = trippy_binary.parent / optional_name
        if optional_path.is_file():
            datas.append((str(optional_path), 'third_party/trippy'))


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
    'pypdf',
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
