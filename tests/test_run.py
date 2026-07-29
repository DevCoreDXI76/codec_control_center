import time as real_time

import run
from app.core.settings import AppSettings


class _FakeSettingsStore:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def load(self) -> AppSettings:
        return self._settings


def test_main_starts_uvicorn_on_configured_host_port(monkeypatch):
    calls = {}
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: calls.setdefault("kwargs", k))
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=False))
    )

    run.main()

    assert calls["kwargs"]["host"] == run.HOST
    assert calls["kwargs"]["port"] == run.PORT


def test_main_opens_browser_when_setting_enabled(monkeypatch):
    opened = {}
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

    assert opened.get("url") == f"http://{run.HOST}:{run.PORT}/"


def test_main_skips_browser_when_setting_disabled(monkeypatch):
    opened = {}
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(
        run, "SettingsStore", lambda path: _FakeSettingsStore(AppSettings(open_browser_on_start=False))
    )
    monkeypatch.setattr(run.webbrowser, "open", lambda url: opened.setdefault("url", url))

    run.main()
    real_time.sleep(0.1)

    assert "url" not in opened
