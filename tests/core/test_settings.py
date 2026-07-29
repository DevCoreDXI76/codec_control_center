import pytest

from app.core.settings import AppSettings, SettingsStore


def test_defaults():
    settings = AppSettings()
    assert settings.poll_interval == 15.0
    assert settings.max_concurrency == 8
    assert settings.command_timeout == 7.0
    assert settings.open_browser_on_start is True


def test_load_returns_defaults_when_file_missing(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = store.load()
    assert settings == AppSettings()


def test_save_and_load_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(poll_interval=30.0, max_concurrency=4, command_timeout=10.0, open_browser_on_start=False))

    reloaded = store.load()
    assert reloaded.poll_interval == 30.0
    assert reloaded.max_concurrency == 4
    assert reloaded.command_timeout == 10.0
    assert reloaded.open_browser_on_start is False


def test_load_fills_missing_fields_with_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"poll_interval": 20.0}', encoding="utf-8")
    settings = SettingsStore(path).load()
    assert settings.poll_interval == 20.0
    assert settings.max_concurrency == 8  # 기본값


@pytest.mark.parametrize(
    "kwargs",
    [
        {"poll_interval": 0.5},
        {"poll_interval": 301},
        {"max_concurrency": 0},
        {"max_concurrency": 65},
        {"command_timeout": 0.5},
        {"command_timeout": 61},
    ],
)
def test_out_of_range_values_rejected(kwargs):
    with pytest.raises(ValueError):
        AppSettings(**kwargs)
