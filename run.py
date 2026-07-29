# run.py
"""
PyInstaller EXE 진입점 (SPEC.md 11절).

app/main.py는 순수 ASGI 앱(테스트/개발 시 `uvicorn app.main:app`으로 구동)이고,
이 스크립트는 실제 배포용 실행 파일이 하는 두 가지 — 서버 구동 + 설정에 따른
기본 브라우저 자동 오픈 — 을 담당한다. app/main.py에 넣지 않는 이유는, 그러면
테스트에서 app을 import할 때마다 매번 실제 브라우저가 뜰 위험이 있기 때문이다.
"""
from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from app.core.settings import SettingsStore
from app.main import DATA_DIR, app

HOST = "127.0.0.1"
PORT = 8765


def _open_browser_delayed(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    webbrowser.open(url)


def main() -> None:
    settings = SettingsStore(DATA_DIR / "settings.json").load()
    if settings.open_browser_on_start:
        url = f"http://{HOST}:{PORT}/"
        threading.Thread(target=_open_browser_delayed, args=(url,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
