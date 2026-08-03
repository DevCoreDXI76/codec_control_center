import pytest
from fastapi.testclient import TestClient

from app.core.driver_factory import build_driver_factory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.settings import SettingsStore
from app.core.vault import CredentialVault
from app.main import app


@pytest.fixture
def client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.settings_store = SettingsStore(tmp_path / "settings.json")
    app.state.settings = app.state.settings_store.load()
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault),
        base_interval=app.state.settings.poll_interval,
        max_concurrency=app.state.settings.max_concurrency,
    )
    return TestClient(app)


def test_get_settings_defaults(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["poll_interval"] == 15.0
    assert body["max_concurrency"] == 8
    assert body["command_timeout"] == 7.0
    assert body["open_browser_on_start"] is True


def test_update_settings_persists_and_applies_to_scheduler(client, tmp_path):
    resp = client.put(
        "/api/settings",
        json={
            "poll_interval": 30.0,
            "max_concurrency": 3,
            "command_timeout": 12.0,
            "open_browser_on_start": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["poll_interval"] == 30.0

    assert app.state.scheduler.base_interval == 30.0
    assert app.state.scheduler.max_concurrency == 3

    reloaded = app.state.settings_store.load()
    assert reloaded.poll_interval == 30.0
    assert reloaded.command_timeout == 12.0


def test_update_settings_out_of_range_returns_422(client):
    resp = client.put(
        "/api/settings",
        json={
            "poll_interval": 500,
            "max_concurrency": 8,
            "command_timeout": 7.0,
            "open_browser_on_start": True,
        },
    )
    assert resp.status_code == 422


def test_update_settings_persists_teams_tenant_address(client):
    resp = client.put(
        "/api/settings",
        json={
            "poll_interval": 15.0,
            "max_concurrency": 8,
            "command_timeout": 7.0,
            "open_browser_on_start": True,
            "teams_tenant_address": "vc.poscodx.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["teams_tenant_address"] == "vc.poscodx.com"

    resp2 = client.get("/api/settings")
    assert resp2.json()["teams_tenant_address"] == "vc.poscodx.com"


def test_settings_page_renders(client):
    from app.__version__ import __version__

    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "설정" in resp.text
    assert "폴링 주기" in resp.text
    assert f"v{__version__}" in resp.text


def test_settings_page_escapes_default_empty_tenant_in_x_data_attribute(client):
    # `""|tojson` still emits two literal `"` characters, which — without |forceescape —
    # terminate the double-quoted x-data="..." HTML attribute early and break the whole
    # Alpine object literal for EVERY user, even with no tenant address configured
    # (the bug affects the default case, not just values containing a quote). Regression
    # test for Fix 1.
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "teams_tenant_address: &#34;&#34;," in resp.text
    assert 'teams_tenant_address: "",' not in resp.text


def test_settings_page_escapes_saved_tenant_address_in_x_data_attribute(client):
    client.put(
        "/api/settings",
        json={
            "poll_interval": 15.0,
            "max_concurrency": 8,
            "command_timeout": 7.0,
            "open_browser_on_start": True,
            "teams_tenant_address": "vc.poscodx.com",
        },
    )
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "teams_tenant_address: &#34;vc.poscodx.com&#34;," in resp.text
    assert 'teams_tenant_address: "vc.poscodx.com",' not in resp.text


def test_settings_page_renders_group_management_section(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "그룹 관리" in resp.text
