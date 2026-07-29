import sys

from fastapi.testclient import TestClient

from app.main import app


def test_health_check():
    from app.__version__ import __version__

    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_resolve_paths_dev_mode():
    from app.main import _resolve_paths

    app_dir, templates_dir, static_dir, data_dir = _resolve_paths()
    assert app_dir.name == "app"
    assert templates_dir == app_dir / "templates"
    assert static_dir == app_dir / "static"
    assert data_dir.name == "data"
    assert data_dir.parent == app_dir.parent  # 프로젝트 루트/data


def test_resolve_paths_frozen_mode(monkeypatch, tmp_path):
    from app.main import _resolve_paths

    fake_meipass = tmp_path / "meipass"
    fake_exe_dir = tmp_path / "install_dir"
    fake_exe = fake_exe_dir / "CodecControlCenter.exe"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    app_dir, templates_dir, static_dir, data_dir = _resolve_paths()

    assert app_dir == fake_meipass / "app"
    assert templates_dir == fake_meipass / "app" / "templates"
    assert static_dir == fake_meipass / "app" / "static"
    assert data_dir == fake_exe_dir / "data"  # 실행 파일 옆 — _MEIPASS(임시 경로) 아님
