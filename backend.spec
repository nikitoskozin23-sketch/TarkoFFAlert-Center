# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_root = Path.cwd()

datas = []

static_dir = project_root / 'backend' / 'static'
if static_dir.exists():
    datas.append((str(static_dir), 'static'))

config_yaml = project_root / 'backend' / 'config.yaml'
if config_yaml.exists():
    datas.append((str(config_yaml), '.'))

config_example_yaml = project_root / 'backend' / 'config.example.yaml'
if config_example_yaml.exists():
    datas.append((str(config_example_yaml), '.'))

credentials_dir = project_root / 'backend' / 'credentials'
if credentials_dir.exists():
    datas.append((str(credentials_dir), 'credentials'))

a = Analysis(
    ['backend/main.py'],
    pathex=['backend', '.'],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules('providers'),
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
    [],
    exclude_binaries=True,
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='backend',
)