# build.spec — PyInstaller 단일 EXE 빌드 설정 (SPEC.md 11절).
# 실행: pyinstaller build.spec
from __future__ import annotations

from app.__version__ import __version__

block_cipher = None

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    # (소스, 번들 내 목적지) — app/main.py의 _resolve_paths()가 frozen 모드에서
    # sys._MEIPASS/app/{templates,static}를 그대로 찾으므로 경로를 유지해야 한다.
    datas=[
        ("app/templates", "app/templates"),
        ("app/static", "app/static"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 별도 COLLECT 없이 EXE에 바로 binaries/zipfiles/datas를 담으면 onefile 빌드가 된다.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f"CodecControlCenter-v{__version__}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 초기 실장비 검증 단계에서는 로그 확인을 위해 콘솔 유지
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
