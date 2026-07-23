# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — sestaví Spillway.app (menu bar appka, bez ikony v Docku).

    uv run pyinstaller build/spillway.spec --noconfirm

Whisper model se NESMÍ zabalit do bundlu (stahuje se za běhu, viz Spike D
v plánu) — proto tu není collect_data_files pro modely, jen pro balíčkové
konfigurační soubory faster_whisper/ctranslate2.
"""

import os

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
SRC = os.path.join(ROOT, "src")

# faster_whisper si nese nekódové assety — hlavně silero_vad_v6.onnx (VAD model
# pro vad_filter=True v transcribe.py). Bez nich přepis spadne za běhu
# (ONNXRuntimeError NO_SUCHFILE). PyInstaller je z importů neodvodí → přibalit ručně.
_datas = collect_data_files("faster_whisper")

# mlx GPU backend: nutné přibalit Metal shadery (mlx/lib/mlx.metallib) + nativní
# knihovny (libmlx.dylib…), jinak GPU cesta v .app spadne a kód spadne na CPU.
# mlx_whisper má taky nekódové assety (mel filtry, tokenizer).
_datas += collect_data_files("mlx")            # mlx.metallib
_datas += collect_data_files("mlx_whisper")    # assety whisperu
_mlx_binaries = collect_dynamic_libs("mlx")    # libmlx.dylib, core.so…
_mlx_hidden = collect_submodules("mlx") + collect_submodules("mlx_whisper")

a = Analysis(
    [os.path.join(ROOT, "run_spillway.py")],
    pathex=[SRC],
    binaries=_mlx_binaries,
    datas=_datas,
    hiddenimports=[
        # pyobjc frameworky použité napříč moduly — PyInstaller je z importů
        # samotných často nedokáže odvodit (dynamické načítání bridge kódu).
        "AppKit",
        "Foundation",
        "Quartz",
        "WebKit",
        "ApplicationServices",
        "objc",
        "rumps",
        "keyring.backends.macOS",
        "faster_whisper",
        "ctranslate2",
    ] + _mlx_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # torch tahá mlx_whisper jako závislost, ale při přepisu se NEnačítá (jen
    # v konvertoru torch_whisper.py) — vyloučit, ať bundle nenaroste o ~490 MB.
    excludes=["torch", "torchaudio", "torchvision"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Spillway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Spillway",
)

app = BUNDLE(
    coll,
    name="Spillway.app",
    icon=os.path.join(ROOT, "build", "icon.icns"),
    bundle_identifier="com.spillway.app",
    info_plist={
        "CFBundleName": "Spillway",
        "CFBundleDisplayName": "Spillway",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        # Menu bar appka — žádná ikona v Docku, žádné okno na startu.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        # TCC popisky (zobrazí se v systémovém dialogu při první žádosti).
        "NSMicrophoneUsageDescription": (
            "Spillway potřebuje mikrofon pro diktování — audio se přepisuje "
            "lokálně a nikdy neopouští tento počítač."
        ),
        "NSAppleEventsUsageDescription": (
            "Spillway umí zjistit URL aktivní karty v prohlížeči, aby lépe "
            "naformátoval diktovaný text (e-mail/chat/prompt)."
        ),
    },
)
