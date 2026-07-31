# run.py
"""
PyInstaller EXE 진입점 (SPEC.md 11절).

app/main.py는 순수 ASGI 앱(테스트/개발 시 `uvicorn app.main:app`으로 구동)이고,
이 스크립트는 실제 배포용 실행 파일이 하는 두 가지 — 서버 구동 + 설정에 따른
기본 브라우저 자동 오픈 — 을 담당한다. app/main.py에 넣지 않는 이유는, 그러면
테스트에서 app을 import할 때마다 매번 실제 브라우저가 뜰 위험이 있기 때문이다.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app.core.settings import SettingsStore
from app.main import DATA_DIR, app

HOST = "127.0.0.1"
PORT = 8765
PORT_RETRY_COUNT = 5  # PORT ~ PORT+4 순서로 시도 (BACKLOG.md: 포트 충돌 시 자동 재시도)


def _find_available_port(host: str, base_port: int, attempts: int) -> int | None:
    """base_port부터 attempts개를 순서대로 시도해 실제로 바인딩 가능한 첫 포트를 반환한다.

    SO_REUSEADDR는 일부러 안 쓴다 — Windows에서는 POSIX와 달리 이미 다른 프로세스가
    붙어 있는 포트에도 바인딩이 "성공"하는 것처럼 보이는 경우가 있어(exclusive listen이
    아님), 있는 그대로의 bind() 결과만 신뢰해야 한다. uvicorn(asyncio)도 Windows에서는
    기본적으로 SO_REUSEADDR를 쓰지 않으므로, 여기서 확인한 결과와 실제 uvicorn 바인딩
    결과가 어긋나지 않는다.
    """
    for offset in range(attempts):
        port = base_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return None


def _open_browser_delayed(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    webbrowser.open(url)


def main() -> None:
    settings = SettingsStore(DATA_DIR / "settings.json").load()

    port = _find_available_port(HOST, PORT, PORT_RETRY_COUNT)
    if port is None:
        print(
            f"오류: {HOST}의 {PORT}~{PORT + PORT_RETRY_COUNT - 1}번 포트가 모두 사용 중이라 "
            "서버를 시작할 수 없습니다. 다른 프로그램을 종료한 뒤 다시 실행해 주세요.",
            file=sys.stderr,
        )
        sys.exit(1)
    if port != PORT:
        print(f"안내: 기본 포트 {PORT}번이 사용 중이라 {port}번으로 대신 실행합니다.")

    if settings.open_browser_on_start:
        url = f"http://{HOST}:{port}/"
        threading.Thread(target=_open_browser_delayed, args=(url,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
