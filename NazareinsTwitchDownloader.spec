# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Ensure the icon exists and get its absolute path
icon_file = os.path.abspath(os.path.join('frontend', 'build', 'icon.ico'))
if not os.path.exists(icon_file):
    icon_file = os.path.abspath('icon.ico')
    if not os.path.exists(icon_file):
        print("WARNING: icon.ico not found! The executable will not have an icon.")
        icon_file = None
else:
    print(f"Using icon file: {icon_file}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Maintain the expected structure: frontend/build
        ('frontend/build', 'frontend/build'),
        # Include system tray icon as a separate data file at the root level
        (icon_file, '.') if icon_file else [],
        ('frontend/build/favicon.ico', '.'),
    ],
    hiddenimports=[
        'aiohttp',
        'websockets',
        'streamlink',
        'streamlink.plugins',
        'streamlink.plugins.twitch',
        'streamlink.stream',
        'streamlink.session',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'winreg',
        'backend.src.config',
        'backend.src.services',
        'backend.src.web',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NazareinsTwitchDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if icon_file else None,
)