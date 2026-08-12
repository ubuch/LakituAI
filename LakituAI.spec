# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LakituAI (Windows onedir build).

Build: pyinstaller --clean --noconfirm LakituAI.spec
Output: dist/LakituAI/ (folder, not onefile: torch is too large to unpack
per-launch, and onedir keeps startup fast).
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Packages with bundled data files (themes, tokenizer models, sentencepiece
# configs, etc.) that static analysis alone would miss.
for package in (
    "customtkinter",
    "transformers",
    "tokenizers",
    "sentencepiece",
    "huggingface_hub",
):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# Read-only assets resolved via runtime_paths.assets_dir() (sys._MEIPASS).
datas += [
    ("lakituai/gui/assets", "assets"),
    ("config/bots.json", "config"),
]

# torch is CPU-only (OCR runs on CPU; torchvision is not used at all).
# PyInstaller ships built-in torch hooks; nothing extra needed here.

a = Analysis(
    ["packaging/launcher.py"],
    # Include the repo root so the top-level `lakituai` package is collected.
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests",
        "torchvision",
        "matplotlib",
        "scipy",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LakituAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="packaging/logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LakituAI",
)
