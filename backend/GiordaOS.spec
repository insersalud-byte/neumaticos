# -*- mode: python ; coding: utf-8 -*-

import sys
import os

block_cipher = None

# Rutas
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(SPEC)))
FRONTEND_DIR = os.path.join(BACKEND_DIR, "..", "frontend")
DB_PATH = os.path.join(BACKEND_DIR, "giorda.db")
UPLOADS_DIR = os.path.join(BACKEND_DIR, "uploads")

a = Analysis(
    [os.path.join(BACKEND_DIR, "main.py")],
    pathex=[BACKEND_DIR],
    binaries=[],
    datas=[
        (FRONTEND_DIR, "frontend"),
        (UPLOADS_DIR, "uploads"),
        (DB_PATH, "."),
    ],
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.auto",
        "fastapi",
        "starlette",
        "sqlalchemy",
        "pydantic",
        "reportlab",
        "PIL",
        "jinja2",
        "python_multipart",
        "passlib.handlers.bcrypt",
        "passlib.handlers.argon2",
        "bcrypt",
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
    [],
    exclude_binaries=True,
    name="GiordaOS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GiordaOS",
)
