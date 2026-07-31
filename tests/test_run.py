import socket
import time as real_time

import pytest

import run
from app.core.settings import AppSettings


class _FakeSettingsStore:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def load(self) -> AppSettings:
        return self._settings


# --- _find_available_port ---


def test_find_available_port_returns_base_port_when_free():
    port = run._find_available_port("127.0.0.1", 41000, 3)
    assert port == 41000


def test_find_available_port_skips_occupied_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 41010))
        blocker.listen(1)
        port = run._find_available_port("127.0.0.1", 41010, 3)
    assert port == 41011


def test_find_available_port_returns_none_when_all_occupied():
    socks = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(3)]
    try:
        for offset, sock in enumerate(socks):
            sock.bind(("127.0.0.1", 41020 + offset))
            sock.listen(1)
        port = run._find_available_port("127.0.0.1", 41020, 3)
    finally:
        for sock in socks:
            sock.close()
    assert port is None


# --- main() ---


def test_main_starts_uvicorn_on_resolved_port(monkeypatch):
    calls = {}
    monkeypatch.setattr(run, "_find_available_port", lambda host, base, attempts: base)
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: calls.setdefault("kwargs", k))
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=False))
    )

    run.main()

    assert calls["kwargs"]["host"] == run.HOST
    assert calls["kwargs"]["port"] == run.PORT


def test_main_uses_fallback_port_when_base_occupied(monkeypatch):
    calls = {}
    monkeypatch.setattr(run, "_find_available_port", lambda host, base, attempts: base + 1)
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: calls.setdefault("kwargs", k))
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=False))
    )

    run.main()

    assert calls["kwargs"]["port"] == run.PORT + 1


def test_main_opens_browser_with_resolved_port(monkeypatch):
    opened = {}
    monkeypatch.setattr(run, "_find_available_port", lambda host, base, attempts: base + 2)
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=True))
    )
    monkeypatch.setattr(run.time, "sleep", lambda _: None)
    monkeypatch.setattr(run.webbrowser, "open", lambda url: opened.setdefault("url", url))

    run.main()
    for _ in range(20):
        if "url" in opened:
            break
        real_time.sleep(0.05)

    assert opened.get("url") == f"http://{run.HOST}:{run.PORT + 2}/"


def test_main_skips_browser_when_setting_disabled(monkeypatch):
    opened = {}
    monkeypatch.setattr(run, "_find_available_port", lambda host, base, attempts: base)
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=False))
    )
    monkeypatch.setattr(run.webbrowser, "open", lambda url: opened.setdefault("url", url))

    run.main()
    real_time.sleep(0.1)

    assert "url" not in opened


def test_main_exits_when_no_port_available(monkeypatch, capsys):
    monkeypatch.setattr(run, "_find_available_port", lambda host, base, attempts: None)
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=False))
    )

    with pytest.raises(SystemExit) as exc_info:
        run.main()

    assert exc_info.value.code == 1
    assert "오류" in capsys.readouterr().err
