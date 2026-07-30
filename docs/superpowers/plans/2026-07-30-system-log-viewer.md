# 시스템 로그(app.log) 뷰어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/logs` 페이지에 "제어 로그" / "시스템 로그" 탭을 추가해, 지금까지 UI가 없던
`data/app.log`를 브라우저에서 볼 수 있게 한다.

**Architecture:** 신규 순수 함수 `tail_app_log()`(app.log의 마지막 N줄을 최신순으로 반환)를
FastAPI 라우트 `GET /logs/system`에서 호출하고, 기존 `logs.html` 템플릿 하나를 `view` 컨텍스트
값("control"/"system")에 따라 분기 렌더링하도록 확장한다. 저장소·로테이션 정책은 변경하지
않는다.

**Tech Stack:** FastAPI, Jinja2 (`app.templating.Jinja2Templates`), pytest + `fastapi.testclient.TestClient`.

## Global Constraints

- 로그에 계정정보(ID/PW)를 남기지 않는다는 기존 원칙(SPEC.md 12절)은 이번 작업 대상이 아님 —
  `tail_app_log()`은 이미 쓰인 파일을 그대로 읽어 보여줄 뿐, 새로 무엇을 로깅하지 않는다.
- 로테이션 정책(`maxBytes=5*1024*1024, backupCount=3`)과 로그 레벨(INFO)은 변경하지 않는다.
- 로그 레벨 필터링, 실시간 자동 갱신, 다운로드 버튼은 이번 스코프에 포함하지 않는다(설계
  문서 "범위 밖" 참고).
- 참고 문서: `docs/superpowers/specs/2026-07-30-system-log-viewer-design.md`

---

## Task 1: `tail_app_log` 유틸리티

**Files:**
- Create: `app/core/applog.py`
- Test: `tests/core/test_applog.py`

**Interfaces:**
- Produces: `tail_app_log(path: Path, n: int = 300) -> list[str]` — Task 2가 이 함수를 임포트해서 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/core/test_applog.py` 새로 생성:

```python
from app.core.applog import tail_app_log


def test_tail_app_log_missing_file_returns_empty(tmp_path):
    result = tail_app_log(tmp_path / "app.log")
    assert result == []


def test_tail_app_log_returns_all_lines_newest_first_when_under_limit(tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert tail_app_log(log_path, n=300) == ["line3", "line2", "line1"]


def test_tail_app_log_truncates_to_last_n_lines(tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
    result = tail_app_log(log_path, n=3)
    assert result == ["line10", "line9", "line8"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/core/test_applog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.applog'`

- [ ] **Step 3: 최소 구현 작성**

`app/core/applog.py` 새로 생성:

```python
"""시스템 로그(data/app.log) 조회 유틸 — /logs/system 뷰어에서 사용."""
from __future__ import annotations

from pathlib import Path


def tail_app_log(path: Path, n: int = 300) -> list[str]:
    """app.log의 마지막 n줄을 최신순(역순)으로 반환한다. 파일이 없으면 빈 리스트."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return list(reversed(lines[-n:]))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/core/test_applog.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add app/core/applog.py tests/core/test_applog.py
git commit -m "feat: add tail_app_log utility for system log viewer"
```

---

## Task 2: `/logs/system` 라우트 + 탭 UI + 스타일

**Files:**
- Modify: `app/main.py:1-30` (import 추가), `app/main.py:69-70` (`APP_LOG_PATH` 상수화),
  `app/main.py:86-91` (`app.state.app_log_path` 추가), `app/main.py:155-158` (`/logs` 라우트에
  `view="control"` 추가, `/logs/system` 라우트 신규 추가)
- Modify: `app/templates/logs.html` (탭 네비 + `view` 분기 렌더링)
- Modify: `app/static/css/style.css` (파일 끝, 499번째 줄 `.log-fail` 블록 다음에 추가)
- Modify: `tests/api/test_routes_logs.py` (`client` fixture에 `app.state.app_log_path` 추가,
  신규 테스트 추가)

**Interfaces:**
- Consumes: `tail_app_log(path: Path, n: int = 300) -> list[str]` (Task 1)
- Produces: `GET /logs/system` 라우트, `app.state.app_log_path: Path` (테스트에서 override
  가능한 시스템 로그 파일 경로)

- [ ] **Step 1: 실패하는 라우트 테스트 작성**

`tests/api/test_routes_logs.py`의 `client` fixture를 아래처럼 수정(마지막 줄에 한 줄 추가):

```python
@pytest.fixture
def client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault)
    )
    app.state.history = ControlHistory(tmp_path / "history.sqlite3")
    app.state.app_log_path = tmp_path / "app.log"
    return TestClient(app)
```

파일 끝에 아래 테스트들 추가:

```python
def test_system_log_page_renders_empty_state(client):
    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert "아직 기록된 시스템 로그가 없습니다" in resp.text


def test_system_log_page_renders_lines_newest_first(client):
    app.state.app_log_path.write_text(
        "2026-07-30 10:00:00 INFO app: first\n2026-07-30 10:00:01 WARNING app: second\n",
        encoding="utf-8",
    )
    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert resp.text.index("second") < resp.text.index("first")  # 최신 줄이 위로


def test_logs_page_shows_control_tab_active(client):
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert '<a href="/logs" class="active">제어 로그</a>' in resp.text
    assert '<a href="/logs/system" class="">시스템 로그</a>' in resp.text


def test_system_log_page_shows_system_tab_active(client):
    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert '<a href="/logs" class="">제어 로그</a>' in resp.text
    assert '<a href="/logs/system" class="active">시스템 로그</a>' in resp.text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/api/test_routes_logs.py -v`
Expected: 신규 4개 테스트 FAIL (`/logs/system`이 없어 404, 탭 마크업도 없음). 기존 5개 테스트는
여전히 PASS.

- [ ] **Step 3: `app/main.py` 수정**

Import 추가 (기존 `from app.core.driver_factory import build_driver_factory` 위나 아래,
알파벳 순서상 `app.core.applog`가 `app.core.driver_factory`보다 앞이므로 그 줄 위에 삽입):

```python
from app.core.applog import tail_app_log
from app.core.driver_factory import build_driver_factory
```

69-70번째 줄:

```python
APP_DIR, TEMPLATES_DIR, STATIC_DIR, DATA_DIR = _resolve_paths()
```
다음 줄을 아래로 교체:
```python
APP_LOG_PATH = DATA_DIR / "app.log"
_configure_logging(APP_LOG_PATH)
```

86-91번째 줄 근처, 기존 `app.state.history = ControlHistory(DATA_DIR / "history.sqlite3")` 줄
다음에 추가:

```python
app.state.app_log_path = APP_LOG_PATH
```

155-158번째 줄(기존 `/logs` 라우트)을 아래로 교체:

```python
@app.get("/logs")
async def logs_page(request: Request):
    entries = request.app.state.history.list_recent(limit=200)
    return templates.TemplateResponse(request, "logs.html", {"view": "control", "entries": entries})


@app.get("/logs/system")
async def system_log_page(request: Request):
    log_lines = tail_app_log(request.app.state.app_log_path)
    return templates.TemplateResponse(request, "logs.html", {"view": "system", "log_lines": log_lines})
```

- [ ] **Step 4: `app/templates/logs.html` 전체 교체**

```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>로그 - Codec Control Center</title>
  <link rel="stylesheet" href="/static/css/style.css" />
  <script src="/static/js/theme.js"></script>
</head>
<body>
  <header class="topbar">
    <h1>● Codec Control Center</h1>
    <button id="theme-toggle" class="theme-toggle-btn" type="button" title="다크모드 전환">🌙</button>
  </header>

  <div class="layout">
    <nav class="sidebar">
      <a href="/">대시보드</a>
      <a href="/settings">설정</a>
      <a class="active" href="/logs">로그</a>
    </nav>

    <main class="main">
      <div class="log-tabs">
        <a href="/logs" class="{{ 'active' if view == 'control' else '' }}">제어 로그</a>
        <a href="/logs/system" class="{{ 'active' if view == 'system' else '' }}">시스템 로그</a>
      </div>

      {% if view == 'system' %}
      <h2>시스템 로그</h2>
      {% if log_lines %}
      <pre class="app-log-view">{% for line in log_lines %}{{ line }}
{% endfor %}</pre>
      {% else %}
      <div class="empty-state">
        <p>아직 기록된 시스템 로그가 없습니다.</p>
      </div>
      {% endif %}
      {% else %}
      <h2>제어 이력</h2>
      {% if entries %}
      <div class="log-table-wrap">
        <table class="log-table">
          <thead>
            <tr>
              <th>시각</th>
              <th>장비</th>
              <th>동작</th>
              <th>결과</th>
              <th>상세</th>
            </tr>
          </thead>
          <tbody>
            {% for e in entries %}
            <tr>
              <td>{{ e.created_at }}</td>
              <td>{{ e.device_name }}</td>
              <td>{{ e.action }}</td>
              <td>
                {% if e.success %}
                <span class="log-badge log-ok">성공</span>
                {% else %}
                <span class="log-badge log-fail">실패</span>
                {% endif %}
              </td>
              <td>{{ e.detail or '' }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <div class="empty-state">
        <p>아직 기록된 제어 이력이 없습니다.</p>
      </div>
      {% endif %}
      {% endif %}
    </main>
  </div>
</body>
</html>
```

주의: `class="{{ 'active' if view == 'control' else '' }}"`는 비활성 탭일 때 `class=""`을
렌더링한다 — Step 1의 테스트 문자열(`class=""`)과 정확히 일치해야 하니 그대로 둔다.

- [ ] **Step 5: `app/static/css/style.css`에 스타일 추가**

파일 끝(499번째 줄, `.log-fail` 블록 다음)에 추가:

```css

.log-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--color-border);
}

.log-tabs a {
  padding: 0.5rem 1rem;
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: 0.9rem;
  border-bottom: 2px solid transparent;
}

.log-tabs a.active {
  color: var(--color-text);
  font-weight: 600;
  border-bottom-color: var(--color-text);
}

.app-log-view {
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 0.9rem 1.1rem;
  font-family: "Consolas", "Courier New", monospace;
  font-size: 0.8rem;
  white-space: pre-wrap;
  overflow-x: auto;
  max-height: 70vh;
  overflow-y: auto;
}
```

- [ ] **Step 6: 테스트 통과 확인 (신규 + 회귀)**

Run: `python -m pytest tests/api/test_routes_logs.py -v`
Expected: 9개 전부 PASS (기존 5개 + 신규 4개)

Run: `python -m pytest -q`
Expected: 전체 스위트 PASS (회귀 없음 확인)

- [ ] **Step 7: 커밋**

```bash
git add app/main.py app/templates/logs.html app/static/css/style.css tests/api/test_routes_logs.py
git commit -m "feat: add system log tab to /logs page"
```

- [ ] **Step 8: 수동 QA (PIPELINE.md 체크리스트에 추가할 항목)**

로컬에서 앱 실행 후 브라우저로 직접 확인:
1. `/logs` 접속 → "제어 로그" 탭이 강조돼 있고 기존 제어 이력 표가 그대로 보이는지.
2. "시스템 로그" 탭 클릭 → `/logs/system`으로 이동, `data/app.log` 내용이 최신 줄이 위로
   오는 순서로 모노스페이스 블록에 보이는지.
3. `data/app.log`를 아직 만든 적 없는 새 설치 상태(또는 파일을 임시로 지운 상태)에서
   "시스템 로그" 탭 → "아직 기록된 시스템 로그가 없습니다" 문구가 뜨는지.
4. 다크모드 토글 시 탭/로그 박스 색상이 자연스럽게 전환되는지.

---

## Self-Review 결과

- **스펙 커버리지**: 설계 문서 §2(메뉴 구조)→Task2 템플릿 탭, §3(백엔드)→Task1+Task2,
  §4(템플릿)→Task2 Step4, §5(CSS)→Task2 Step5, §6(테스트 계획)→Task1 Step1 + Task2 Step1.
  전부 반영. 범위 밖으로 명시한 항목(레벨 필터링/실시간 갱신/다운로드/로테이션 변경)은
  태스크에 포함하지 않음 — 의도한 대로.
- **플레이스홀더 스캔**: "TBD"/"나중에" 등 없음. 모든 스텝에 실제 코드/명령어 포함.
- **타입/시그니처 일관성**: `tail_app_log(path: Path, n: int = 300) -> list[str]`이 Task1과
  Task2에서 동일하게 쓰임. `app.state.app_log_path`도 Task2 전체에서 동일한 이름 사용.
