# 대시보드 사용성 개선 5건 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VDI 실사용 피드백 5건(그룹 관리, 그룹 일괄제어 제거, 회의목록 정렬/페이지네이션, 다크모드 기본값, 로그 복사/다운로드)을 BridgeX 대시보드에 반영한다.

**Architecture:** 기존 FastAPI + Jinja2 서버 렌더링 + Alpine.js(폼) + 순수 JS(dashboard.js, WebSocket 실시간 갱신) 구조를 그대로 따른다. 그룹 관리만 신규 백엔드(레지스트리 메서드 + REST API)가 필요하고, 나머지 4건은 기존 라우트/템플릿/정적 파일 수정만으로 끝난다.

**Tech Stack:** Python 3.11+ / FastAPI / Jinja2 / pytest / vanilla JS + Alpine.js(CDN 없이 vendor 번들) / DPAPI 암호화 파일 저장소(`DeviceRegistry`)

## Global Constraints

- 그룹 이름 변경 시 대상 이름이 이미 다른 그룹명과 같으면 **차단**(병합 금지).
- 그룹 "삭제"는 장비의 `group` 필드를 `""`로 비우는 것뿐 — **장비 자체는 삭제하지 않는다.**
- "오늘의 예정 회의" 정렬 기준/방향/페이지 크기는 `localStorage`에 저장해 다음 방문에도 유지. 페이지 번호는 새로고침 시 1로 리셋.
- 로그 복사/다운로드는 현재 화면 표시분만(제어 로그 최근 200건, 시스템 로그 최근 300줄) — 백엔드 추가 조회 없음.
- 그룹 탭(필터링)은 유지하고, 그룹 **일괄 제어**(Mute/Unmute/재부팅) 버튼만 제거한다.
- 커밋은 각 태스크 끝에 한 번씩, 작고 목적이 분명하게 나눈다.

---

### Task 1: `DeviceRegistry.rename_group` / `clear_group`

**Files:**
- Modify: `app/core/registry.py` (delete_device 메서드, 82~84행 뒤에 추가)
- Test: `tests/core/test_registry.py`

**Interfaces:**
- Consumes: `app.models.device.Device` (기존), `self._read()` / `self._write()` (기존 private 헬퍼)
- Produces:
  - `DeviceRegistry.rename_group(old_name: str, new_name: str) -> int` — 변경된 장비 수 반환. `old_name`을 가진 장비가 없으면 `KeyError`. `new_name`이 이미 다른 그룹으로 쓰이고 있으면 `ValueError`.
  - `DeviceRegistry.clear_group(name: str) -> int` — 변경된 장비 수 반환. `name`을 가진 장비가 없으면 `KeyError`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/core/test_registry.py` 파일 끝에 추가:

```python
def test_rename_group_updates_all_matching_devices(registry):
    _add_sample(registry, name="A", group="3F")
    _add_sample(registry, name="B", group="3F")
    _add_sample(registry, name="C", group="5F")
    count = registry.rename_group("3F", "3층")
    assert count == 2
    groups = {d.group for d in registry.list_devices()}
    assert groups == {"3층", "5F"}


def test_rename_group_blocks_when_target_name_exists(registry):
    _add_sample(registry, name="A", group="3F")
    _add_sample(registry, name="B", group="5F")
    with pytest.raises(ValueError):
        registry.rename_group("3F", "5F")
    # 차단되면 원래 상태 그대로 유지돼야 한다
    groups = {d.group for d in registry.list_devices()}
    assert groups == {"3F", "5F"}


def test_rename_group_unknown_name_raises_keyerror(registry):
    with pytest.raises(KeyError):
        registry.rename_group("no-such-group", "x")


def test_clear_group_empties_group_field_but_keeps_devices(registry):
    _add_sample(registry, name="A", group="3F")
    _add_sample(registry, name="B", group="3F")
    count = registry.clear_group("3F")
    assert count == 2
    devices = registry.list_devices()
    assert len(devices) == 2  # 장비는 삭제되지 않음
    assert all(d.group == "" for d in devices)


def test_clear_group_unknown_name_raises_keyerror(registry):
    with pytest.raises(KeyError):
        registry.clear_group("no-such-group")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/core/test_registry.py -k "group" -v`
Expected: FAIL with `AttributeError: 'DeviceRegistry' object has no attribute 'rename_group'`

- [ ] **Step 3: 최소 구현 작성**

`app/core/registry.py`의 `delete_device` 메서드(현재 82~84행) 바로 뒤에 추가:

```python
    def rename_group(self, old_name: str, new_name: str) -> int:
        """old_name을 가진 모든 장비의 group을 new_name으로 바꾼다. 반환값은 변경된
        장비 수. old_name을 가진 장비가 없으면 KeyError(update_device의 미존재 id
        처리와 동일 패턴), new_name이 이미 다른 그룹으로 쓰이고 있으면 ValueError로
        차단한다(병합하지 않음)."""
        devices = self._read()
        matching_ids = {d.id for d in devices if d.group == old_name}
        if not matching_ids:
            raise KeyError(f"no devices found in group {old_name!r}")
        if any(d.group == new_name for d in devices if d.id not in matching_ids):
            raise ValueError(f"group {new_name!r} already exists")
        devices = [
            dataclasses.replace(d, group=new_name) if d.id in matching_ids else d
            for d in devices
        ]
        self._write(devices)
        return len(matching_ids)

    def clear_group(self, name: str) -> int:
        """name을 가진 모든 장비의 group을 ""로 비운다(장비 자체는 삭제하지 않음).
        반환값은 변경된 장비 수. name을 가진 장비가 없으면 KeyError."""
        devices = self._read()
        matching_ids = {d.id for d in devices if d.group == name}
        if not matching_ids:
            raise KeyError(f"no group named {name!r}")
        devices = [
            dataclasses.replace(d, group="") if d.id in matching_ids else d
            for d in devices
        ]
        self._write(devices)
        return len(matching_ids)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/core/test_registry.py -k "group" -v`
Expected: 5개 테스트 모두 PASS

- [ ] **Step 5: 전체 회귀 확인 후 커밋**

Run: `pytest tests/core/test_registry.py -v`
Expected: 전체 PASS (기존 테스트 깨짐 없음)

```bash
git add app/core/registry.py tests/core/test_registry.py
git commit -m "feat: DeviceRegistry에 그룹 이름 변경/삭제 메서드 추가"
```

---

### Task 2: 그룹 관리 REST API (`/api/groups`)

**Files:**
- Create: `app/api/routes_groups.py`
- Modify: `app/main.py:18` (import 블록), `app/main.py:123` (`app.include_router` 블록)
- Test: `tests/api/test_routes_groups.py` (신규)

**Interfaces:**
- Consumes: `DeviceRegistry.rename_group`/`clear_group`(Task 1), `DeviceRegistry.list_devices()`(기존), `request.app.state.registry`(기존 패턴)
- Produces:
  - `GET /api/groups` → `[{"name": str, "device_count": int}, ...]` (이름 오름차순)
  - `PATCH /api/groups/{name}` (body: `{"new_name": str}`) → `{"device_count": int}` / 대상 없음 404 / 이름 충돌 409
  - `DELETE /api/groups/{name}` → `{"device_count": int}` / 대상 없음 404

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_groups.py` 신규 생성:

```python
import pytest
from fastapi.testclient import TestClient

from app.core.driver_factory import build_driver_factory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.main import app


@pytest.fixture
def client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault)
    )
    return TestClient(app)


def _add_device(name, group):
    return app.state.registry.add_device(
        name=name,
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group=group,
        credential_ref="cred-ref-1",
        is_simulated=True,
    )


def test_list_groups_empty(client):
    resp = client.get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_groups_counts_devices(client):
    _add_device("A", "3F")
    _add_device("B", "3F")
    _add_device("C", "5F")
    resp = client.get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == [
        {"name": "3F", "device_count": 2},
        {"name": "5F", "device_count": 1},
    ]


def test_list_groups_ignores_ungrouped_devices(client):
    _add_device("A", "")
    resp = client.get("/api/groups")
    assert resp.json() == []


def test_rename_group_success(client):
    _add_device("A", "3F")
    resp = client.patch("/api/groups/3F", json={"new_name": "3층"})
    assert resp.status_code == 200
    assert resp.json() == {"device_count": 1}
    assert client.get("/api/groups").json() == [{"name": "3층", "device_count": 1}]


def test_rename_group_conflict_returns_409(client):
    _add_device("A", "3F")
    _add_device("B", "5F")
    resp = client.patch("/api/groups/3F", json={"new_name": "5F"})
    assert resp.status_code == 409


def test_rename_group_unknown_returns_404(client):
    resp = client.patch("/api/groups/no-such-group", json={"new_name": "x"})
    assert resp.status_code == 404


def test_delete_group_removes_tag_but_keeps_device(client):
    _add_device("A", "3F")
    resp = client.delete("/api/groups/3F")
    assert resp.status_code == 200
    assert resp.json() == {"device_count": 1}
    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["group"] == ""


def test_delete_group_unknown_returns_404(client):
    resp = client.delete("/api/groups/no-such-group")
    assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/api/test_routes_groups.py -v`
Expected: FAIL — `404 Not Found` (라우트가 아직 없음, `test_list_groups_empty`부터 실패)

- [ ] **Step 3: 라우터 구현**

`app/api/routes_groups.py` 신규 생성:

```python
# app/api/routes_groups.py
"""그룹(장비의 group 태그) 관리 API. 별도 그룹 엔티티가 없어 Device.group 문자열을
일괄로 조회/변경/제거한다(app/core/registry.py의 rename_group/clear_group 참고)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.registry import DeviceRegistry

router = APIRouter(prefix="/api/groups", tags=["groups"])


class GroupResponse(BaseModel):
    name: str
    device_count: int


class GroupRenameRequest(BaseModel):
    new_name: str


def _get_registry(request: Request) -> DeviceRegistry:
    return request.app.state.registry


@router.get("", response_model=list[GroupResponse])
async def list_groups(request: Request) -> list[GroupResponse]:
    devices = _get_registry(request).list_devices()
    counts: dict[str, int] = {}
    for device in devices:
        if device.group:
            counts[device.group] = counts.get(device.group, 0) + 1
    return [GroupResponse(name=name, device_count=count) for name, count in sorted(counts.items())]


@router.patch("/{name}")
async def rename_group(name: str, payload: GroupRenameRequest, request: Request) -> dict:
    registry = _get_registry(request)
    try:
        count = registry.rename_group(name, payload.new_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"device_count": count}


@router.delete("/{name}")
async def delete_group(name: str, request: Request) -> dict:
    registry = _get_registry(request)
    try:
        count = registry.clear_group(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"device_count": count}
```

`app/main.py`의 import 블록 — 현재 18행:
```python
from app.api.routes_devices import router as devices_router
```
바로 뒤에 추가:
```python
from app.api.routes_groups import router as groups_router
```

`app/main.py`의 라우터 등록 블록 — 현재:
```python
app.include_router(devices_router)
app.include_router(control_router)
```
사이에 추가해 다음과 같이 변경:
```python
app.include_router(devices_router)
app.include_router(groups_router)
app.include_router(control_router)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/api/test_routes_groups.py -v`
Expected: 8개 테스트 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/api/routes_groups.py app/main.py tests/api/test_routes_groups.py
git commit -m "feat: 그룹 관리 REST API(/api/groups) 추가"
```

---

### Task 3: 설정 페이지 — 그룹 관리 UI

**Files:**
- Modify: `app/templates/settings.html` (기존 `.settings-panel` div 뒤, `</main>` 앞에 추가)
- Modify: `app/static/css/style.css` (`.settings-panel` 관련 스타일 뒤에 추가)
- Test: `tests/api/test_routes_settings.py`

**Interfaces:**
- Consumes: Task 2의 `GET/PATCH/DELETE /api/groups`(fetch 호출), 기존 `.btn`/`.btn-primary`/`.btn-danger`/`.error-text`/`.meta` CSS 클래스
- Produces: 없음(터미널 UI 태스크)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_settings.py` 파일 끝에 추가:

```python
def test_settings_page_renders_group_management_section(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "그룹 관리" in resp.text
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/api/test_routes_settings.py -k group_management -v`
Expected: FAIL — `"그룹 관리" in resp.text`가 `False`

- [ ] **Step 3: 템플릿에 그룹 관리 섹션 추가**

`app/templates/settings.html`에서 기존 `.settings-panel` div의 닫는 태그(현재 106행 `</div>`)와 `</main>`(107행) 사이에 삽입:

```html
      <div
        class="settings-panel"
        x-data="{
          groups: [],
          error: '',
          editingName: null,
          editValue: '',
          async load() {
            const resp = await fetch('/api/groups');
            this.groups = resp.ok ? await resp.json() : [];
          },
          startEdit(g) {
            this.editingName = g.name;
            this.editValue = g.name;
            this.error = '';
          },
          cancelEdit() {
            this.editingName = null;
            this.error = '';
          },
          async saveEdit(oldName) {
            this.error = '';
            const resp = await fetch(`/api/groups/${encodeURIComponent(oldName)}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ new_name: this.editValue }),
            });
            if (!resp.ok) {
              this.error = resp.status === 409 ? '이미 존재하는 그룹명입니다' : '수정 실패';
              return;
            }
            this.editingName = null;
            await this.load();
          },
          async remove(g) {
            if (!confirm(`\"${g.name}\" 그룹 태그를 ${g.device_count}대 장비에서 제거합니다. 장비 자체는 삭제되지 않습니다. 계속할까요?`)) return;
            const resp = await fetch(`/api/groups/${encodeURIComponent(g.name)}`, { method: 'DELETE' });
            if (resp.ok) await this.load();
          },
        }"
        x-init="load()"
      >
        <h2>그룹 관리</h2>
        <template x-if="groups.length === 0">
          <p class="meta">등록된 그룹이 없습니다.</p>
        </template>
        <ul class="group-manage-list">
          <template x-for="g in groups" :key="g.name">
            <li class="group-manage-row">
              <template x-if="editingName !== g.name">
                <span x-text="`${g.name} (장비 ${g.device_count}대)`"></span>
              </template>
              <template x-if="editingName === g.name">
                <input type="text" x-model="editValue" />
              </template>
              <span class="group-manage-actions">
                <template x-if="editingName !== g.name">
                  <button class="btn" type="button" @click="startEdit(g)" title="이름 수정">✎</button>
                </template>
                <template x-if="editingName === g.name">
                  <button class="btn btn-primary" type="button" @click="saveEdit(g.name)">저장</button>
                </template>
                <template x-if="editingName === g.name">
                  <button class="btn" type="button" @click="cancelEdit()">취소</button>
                </template>
                <button class="btn btn-danger" type="button" @click="remove(g)" title="삭제">🗑</button>
              </span>
            </li>
          </template>
        </ul>
        <p class="error-text" x-show="error" x-text="error"></p>
      </div>
```

- [ ] **Step 4: CSS 추가**

`app/static/css/style.css`의 `.settings-panel` 관련 블록(현재 478~498행 부근, `.version-footer` 스타일 뒤) 다음에 추가:

```css
.group-manage-list {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0 0;
}

.group-manage-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--color-border);
}

.group-manage-row:last-child {
  border-bottom: none;
}

.group-manage-actions {
  display: flex;
  gap: 0.4rem;
  flex-shrink: 0;
}
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `pytest tests/api/test_routes_settings.py -v`
Expected: 전체 PASS

- [ ] **Step 6: 수동 확인**

`py run.py` 실행 → `/settings` 접속 → 장비를 몇 대 등록해 그룹을 부여한 뒤(기존 대시보드 "+ 장비 등록"에서 그룹란 입력) 설정 페이지에서 그룹 목록이 뜨는지, ✎로 이름 변경(중복 이름 시도 시 에러 문구), 🗑로 삭제(장비는 남고 그룹만 없어짐) 확인.

- [ ] **Step 7: 커밋**

```bash
git add app/templates/settings.html app/static/css/style.css tests/api/test_routes_settings.py
git commit -m "feat: 설정 페이지에 그룹 관리(이름 수정/삭제) UI 추가"
```

---

### Task 4: 그룹 일괄 제어 버튼 제거

**Files:**
- Modify: `app/templates/index.html:50-55`
- Modify: `app/static/js/dashboard.js:108-152`
- Modify: `app/static/css/style.css:210-219`
- Test: `tests/test_dashboard_route.py`

**Interfaces:**
- Consumes: 없음(제거 작업)
- Produces: 없음. `filterGroup(group, btn)` 시그니처는 유지(그룹 탭 필터링 기능은 그대로 남김).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_dashboard_route.py`의 `test_dashboard_renders_device_card` 함수 끝(현재 59행 `assert "display:none" in resp.text` 다음 줄)에 추가:

```python
    assert 'id="group-bulk-actions"' not in resp.text  # 그룹 일괄 제어 버튼 제거됨
    assert 'onclick="filterGroup(' in resp.text  # 그룹 탭 필터링은 유지
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_dashboard_route.py::test_dashboard_renders_device_card -v`
Expected: FAIL — `'id="group-bulk-actions"' not in resp.text`가 `False`(현재는 존재하므로)

- [ ] **Step 3: `index.html`에서 그룹 일괄 제어 블록 제거**

`app/templates/index.html`의 현재 43~56행:
```html
      {% if groups %}
      <div class="group-tabs" id="group-tabs">
        <button class="tab active" data-group="__all__" onclick="filterGroup('__all__', this)">전체</button>
        {% for g in groups %}
        <button class="tab" data-group="{{ g }}" onclick="filterGroup('{{ g }}', this)">{{ g }}</button>
        {% endfor %}
      </div>
      <div class="group-bulk-actions" id="group-bulk-actions" style="display:none">
        <span id="group-bulk-label" class="meta"></span>
        <button class="btn" onclick="bulkMute(true)">그룹 전체 Mute</button>
        <button class="btn" onclick="bulkMute(false)">그룹 전체 Unmute</button>
        <button class="btn btn-danger" onclick="bulkReboot()">그룹 전체 재부팅</button>
      </div>
      {% endif %}
```
다음으로 교체:
```html
      {% if groups %}
      <div class="group-tabs" id="group-tabs">
        <button class="tab active" data-group="__all__" onclick="filterGroup('__all__', this)">전체</button>
        {% for g in groups %}
        <button class="tab" data-group="{{ g }}" onclick="filterGroup('{{ g }}', this)">{{ g }}</button>
        {% endfor %}
      </div>
      {% endif %}
```

- [ ] **Step 4: `dashboard.js`에서 bulk 함수 제거**

현재 108~152행:
```js
let currentGroup = "__all__";

function filterGroup(group, btn) {
  currentGroup = group;
  document.querySelectorAll("#group-tabs .tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");

  document.querySelectorAll(".device-card").forEach((card) => {
    const match = group === "__all__" || card.dataset.group === group;
    card.style.display = match ? "" : "none";
  });

  const bulkBar = document.getElementById("group-bulk-actions");
  const label = document.getElementById("group-bulk-label");
  if (!bulkBar || !label) return;
  if (group === "__all__") {
    bulkBar.style.display = "none";
  } else {
    bulkBar.style.display = "flex";
    label.textContent = `"${group}" 그룹 일괄 제어:`;
  }
}

function visibleDeviceIdsInGroup() {
  return Array.from(document.querySelectorAll(".device-card"))
    .filter((card) => currentGroup === "__all__" || card.dataset.group === currentGroup)
    .map((card) => card.dataset.deviceId);
}

async function bulkMute(on) {
  const ids = visibleDeviceIdsInGroup();
  if (ids.length === 0) return;
  if (!confirm(`"${currentGroup}" 그룹 ${ids.length}대를 ${on ? "음소거" : "음소거 해제"}하시겠습니까?`)) return;
  await Promise.all(ids.map((id) => callControl(id, "mute", { on })));
  await Promise.all(ids.map((id) => refreshStatus(id)));
  showToast(`${ids.length}대 ${on ? "음소거" : "음소거 해제"} 완료`);
}

async function bulkReboot() {
  const ids = visibleDeviceIdsInGroup();
  if (ids.length === 0) return;
  if (!confirm(`"${currentGroup}" 그룹 ${ids.length}대를 전부 재부팅하시겠습니까?\n일시적으로 응답하지 않게 됩니다.`)) return;
  await Promise.all(ids.map((id) => callControl(id, "reboot")));
  showToast(`${ids.length}대 재부팅 명령 전송됨`);
}
```
다음으로 교체(그룹 필터링만 남김, `currentGroup` 상태는 더 이상 아무도 안 읽으므로 함께 제거):
```js
function filterGroup(group, btn) {
  document.querySelectorAll("#group-tabs .tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");

  document.querySelectorAll(".device-card").forEach((card) => {
    const match = group === "__all__" || card.dataset.group === group;
    card.style.display = match ? "" : "none";
  });
}
```

- [ ] **Step 5: CSS에서 `.group-bulk-actions` 제거**

`app/static/css/style.css`의 현재 210~219행 블록 전체 삭제:
```css
.group-bulk-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding: 0.5rem 0.75rem;
  background: var(--color-card-bg);
  border: 1px dashed var(--color-border);
  border-radius: 8px;
}
```

- [ ] **Step 6: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_dashboard_route.py -v`
Expected: 전체 PASS

- [ ] **Step 7: 전체 회귀 확인 후 커밋**

Run: `pytest -q`
Expected: 전체 PASS(제거된 함수를 참조하는 다른 테스트 없어야 함)

```bash
git add app/templates/index.html app/static/js/dashboard.js app/static/css/style.css tests/test_dashboard_route.py
git commit -m "fix: 그룹 일괄 제어(Mute/Unmute/재부팅) 버튼 제거 — 오작동 리스크 방지, 그룹 탭 필터링은 유지"
```

---

### Task 5: 최초 설치 시 다크모드 기본값

**Files:**
- Modify: `app/static/js/theme.js:13-17`

**Interfaces:**
- Consumes: 없음
- Produces: 없음(`getPreferredTheme()` 시그니처 동일, 내부 fallback 값만 변경)

- [ ] **Step 1: 변경 내용**

`app/static/js/theme.js`의 현재 13~17행:
```js
  function getPreferredTheme() {
    const stored = getStoredTheme();
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
```
다음으로 교체:
```js
  function getPreferredTheme() {
    const stored = getStoredTheme();
    if (stored === "light" || stored === "dark") return stored;
    return "dark"; // 최초 설치 시 OS 설정과 무관하게 다크모드로 시작
  }
```

- [ ] **Step 2: 수동 확인**

`py run.py` 실행 → 브라우저 개발자도구 콘솔에서 `localStorage.clear()` 실행 후 새로고침 → 다크모드로 뜨는지 확인. 우측 상단 🌙/☀ 토글로 라이트 전환 후 새로고침해도 라이트가 유지되는지 확인(저장된 선택은 존중).

이 파일은 순수 클라이언트 JS(조건문 1줄 변경)라 자동 테스트 대상이 아니다(`docs/superpowers/specs/2026-07-30-system-log-viewer-design.md`에서 확립된 것과 동일한 관례 — dashboard.js/theme.js는 pytest 대상 밖).

- [ ] **Step 3: 커밋**

```bash
git add app/static/js/theme.js
git commit -m "feat: 최초 설치 시 다크모드를 기본값으로 설정"
```

---

### Task 6: 로그 화면 복사/다운로드 버튼

**Files:**
- Modify: `app/main.py:158-167` (`/logs`, `/logs/system` 라우트)
- Modify: `app/templates/logs.html` (전체 재작성)
- Modify: `app/static/css/style.css` (`.log-tabs` 스타일 뒤에 `.log-actions` 추가)
- Test: `tests/api/test_routes_logs.py`

**Interfaces:**
- Consumes: `app.state.history.list_recent()`(기존), `app.core.applog.tail_app_log()`(기존)
- Produces: 템플릿 컨텍스트에 `copy_text: str` 추가(제어 로그는 헤더+탭구분 행, 시스템 로그는 `log_lines`를 그대로 줄바꿈 join). 빈 이력이면 `""`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_logs.py` 상단 import에 `import json`, `import re` 추가, 파일 끝에 테스트 추가:

```python
def test_logs_page_copy_text_includes_header_and_entries(client):
    app.state.history.log(
        device_id="dev-1", device_name="3층 대회의실", action="mute", success=True, detail="ok"
    )
    resp = client.get("/logs")
    assert resp.status_code == 200
    match = re.search(r"const LOG_COPY_TEXT = (.*);", resp.text)
    assert match is not None
    copy_text = json.loads(match.group(1))
    lines = copy_text.split("\n")
    assert lines[0] == "시각\t장비\t동작\t결과\t상세"
    assert lines[1].split("\t")[1:] == ["3층 대회의실", "mute", "성공", "ok"]


def test_logs_page_copy_text_empty_when_no_entries(client):
    resp = client.get("/logs")
    match = re.search(r"const LOG_COPY_TEXT = (.*);", resp.text)
    assert json.loads(match.group(1)) == ""


def test_logs_page_shows_copy_download_buttons_when_entries_exist(client):
    app.state.history.log(device_id="dev-1", device_name="x", action="mute", success=True)
    resp = client.get("/logs")
    assert "전체 복사" in resp.text
    assert "txt 다운로드" in resp.text


def test_logs_page_hides_copy_download_buttons_when_empty(client):
    resp = client.get("/logs")
    assert "전체 복사" not in resp.text


def test_system_log_page_copy_text_matches_log_lines_newest_first(client):
    app.state.app_log_path.write_text(
        "2026-07-30 10:00:00 INFO app: first\n2026-07-30 10:00:01 WARNING app: second\n",
        encoding="utf-8",
    )
    resp = client.get("/logs/system")
    match = re.search(r"const LOG_COPY_TEXT = (.*);", resp.text)
    copy_text = json.loads(match.group(1))
    assert copy_text.split("\n") == [
        "2026-07-30 10:00:01 WARNING app: second",
        "2026-07-30 10:00:00 INFO app: first",
    ]


def test_system_log_page_shows_copy_download_buttons_when_lines_exist(client):
    app.state.app_log_path.write_text("2026-07-30 10:00:00 INFO app: x\n", encoding="utf-8")
    resp = client.get("/logs/system")
    assert "전체 복사" in resp.text
    assert "txt 다운로드" in resp.text
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/api/test_routes_logs.py -k copy_text -v`
Expected: FAIL — `re.search(...)`가 `None`(아직 `LOG_COPY_TEXT`가 템플릿에 없음)

- [ ] **Step 3: `main.py` 라우트에 `copy_text` 계산 추가**

`app/main.py`의 현재 158~167행:
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
다음으로 교체:
```python
@app.get("/logs")
async def logs_page(request: Request):
    entries = request.app.state.history.list_recent(limit=200)
    copy_text = ""
    if entries:
        header = "\t".join(["시각", "장비", "동작", "결과", "상세"])
        rows = [
            "\t".join([e.created_at, e.device_name, e.action, "성공" if e.success else "실패", e.detail or ""])
            for e in entries
        ]
        copy_text = "\n".join([header, *rows])
    return templates.TemplateResponse(
        request, "logs.html", {"view": "control", "entries": entries, "copy_text": copy_text}
    )


@app.get("/logs/system")
async def system_log_page(request: Request):
    log_lines = tail_app_log(request.app.state.app_log_path)
    copy_text = "\n".join(log_lines)
    return templates.TemplateResponse(
        request, "logs.html", {"view": "system", "log_lines": log_lines, "copy_text": copy_text}
    )
```

- [ ] **Step 4: `logs.html` 전체 재작성**

`app/templates/logs.html` 전체를 다음으로 교체:

```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>로그 - BridgeX</title>
  <link rel="icon" href="/static/img/favicon.ico" />
  <link rel="stylesheet" href="/static/css/style.css" />
  <script src="/static/js/theme.js"></script>
</head>
<body>
  <header class="topbar">
    <h1 class="brand">
      <img class="brand-mark" src="/static/img/coredxi-mark.png" alt="coredxi" />
      <span class="brand-word">BridgeX</span>
    </h1>
    <button id="theme-toggle" class="theme-toggle-btn" type="button" title="다크모드 전환">🌙</button>
  </header>

  <div class="layout">
    <nav class="sidebar">
      <a href="/">대시보드</a>
      <a href="/settings">설정</a>
      <a class="active" href="/logs">로그</a>
      <a class="sidebar-guide-link" href="/guide">가이드</a>
    </nav>

    <main class="main">
      <div class="log-tabs">
        <a href="/logs" class="{{ 'active' if view == 'control' else '' }}">제어 로그</a>
        <a href="/logs/system" class="{{ 'active' if view == 'system' else '' }}">시스템 로그</a>
      </div>

      {% if view == 'system' %}
      <h2>시스템 로그</h2>
      {% if log_lines %}
      <div class="log-actions">
        <button class="btn" type="button" onclick="copyLogText()">전체 복사</button>
        <button class="btn" type="button" onclick="downloadLogText('system-log')">txt 다운로드</button>
      </div>
      <pre class="app-log-view">{{ copy_text }}</pre>
      {% else %}
      <div class="empty-state">
        <p>아직 기록된 시스템 로그가 없습니다.</p>
      </div>
      {% endif %}
      {% else %}
      <h2>제어 이력</h2>
      {% if entries %}
      <div class="log-actions">
        <button class="btn" type="button" onclick="copyLogText()">전체 복사</button>
        <button class="btn" type="button" onclick="downloadLogText('control-log')">txt 다운로드</button>
      </div>
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

  <script>
    const LOG_COPY_TEXT = {{ copy_text | tojson }};

    async function copyLogText() {
      try {
        await navigator.clipboard.writeText(LOG_COPY_TEXT);
        showLogToast("복사되었습니다");
      } catch (e) {
        showLogToast("복사 실패 — 브라우저 권한을 확인해주세요");
      }
    }

    function downloadLogText(prefix) {
      const now = new Date();
      const stamp = now.toISOString().slice(0, 16).replace(/[-:T]/g, "");
      const blob = new Blob([LOG_COPY_TEXT], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${prefix}-${stamp}.txt`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }

    function showLogToast(message) {
      const toast = document.createElement("div");
      toast.className = "toast";
      toast.textContent = message;
      document.body.appendChild(toast);
      setTimeout(() => toast.remove(), 2500);
    }
  </script>
</body>
</html>
```

- [ ] **Step 5: CSS에 `.log-actions` 추가**

`app/static/css/style.css`의 `.log-tabs a.active` 블록(현재 571~574행 부근) 다음에 추가:

```css
.log-actions {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
```

(`.toast` 클래스는 `dashboard.js`의 `showToast`가 이미 쓰고 있는 기존 스타일을 그대로 재사용 — 신규 CSS 불필요.)

- [ ] **Step 6: 테스트 실행해서 통과 확인**

Run: `pytest tests/api/test_routes_logs.py -v`
Expected: 전체 PASS(기존 테스트 포함)

- [ ] **Step 7: 수동 확인**

`py run.py` 실행 → `/logs`에서 제어 이력 있는 상태로 "전체 복사" 클릭 후 메모장에 붙여넣기(탭 구분 정상 확인), "txt 다운로드" 클릭 후 파일 내용 확인. `/logs/system`도 동일하게 확인.

- [ ] **Step 8: 커밋**

```bash
git add app/main.py app/templates/logs.html app/static/css/style.css tests/api/test_routes_logs.py
git commit -m "feat: 로그 화면에 전체 복사/txt 다운로드 버튼 추가"
```

---

### Task 7: "오늘의 예정 회의" 정렬 + 페이지네이션

**Files:**
- Modify: `app/templates/index.html:58-65` (meetings-widget 블록)
- Modify: `app/static/js/dashboard.js` (330~410행 재작성 + 542~551행 DOMContentLoaded 수정)
- Modify: `app/static/css/style.css:221-252` (`.meetings-list`/`.meeting-row` 블록 교체)
- Test: `tests/test_dashboard_route.py`

**Interfaces:**
- Consumes: `fetchDeviceMeetings(deviceId)`(기존, 변경 없음), `formatMeetingTime(isoString)`(기존, 변경 없음), `joinMeetingLink(ev, deviceId, entry)`(기존, 변경 없음), `renderCardTeamsSection(deviceId, entries)`(기존, 변경 없음)
- Produces:
  - `meetingsState` 전역 객체 `{ rows, sortKey, sortDir, pageSize, page }`
  - `loadMeetingsPrefs()` — localStorage에서 정렬/페이지크기 복원, 인자 없음, 반환값 없음
  - `renderMeetingsTable()` — `meetingsState.rows` 기준으로 `#meetings-list`를 다시 그림, 인자 없음, 반환값 없음
  - `setMeetingsSort(key)`, `setMeetingsPageSize(size)`, `changeMeetingsPage(delta)` — 전부 index.html의 onclick에서 호출

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_dashboard_route.py`의 `test_dashboard_renders_device_card` 함수 끝에 추가:

```python
    assert 'id="meetings-pagination"' in resp.text
    assert 'onclick="setMeetingsPageSize(5)"' in resp.text
    assert 'onclick="setMeetingsPageSize(10)"' in resp.text
    assert 'onclick="setMeetingsPageSize(20)"' in resp.text
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_dashboard_route.py::test_dashboard_renders_device_card -v`
Expected: FAIL — `'id="meetings-pagination"' in resp.text`가 `False`

- [ ] **Step 3: `index.html`의 meetings-widget 블록 수정**

현재 58~65행:
```html
      {% if devices %}
      <div class="meetings-widget">
        <h2>오늘의 예정 회의</h2>
        <div id="meetings-list" class="meetings-list">
          <p class="meta">불러오는 중...</p>
        </div>
      </div>
      {% endif %}
```
다음으로 교체:
```html
      {% if devices %}
      <div class="meetings-widget">
        <h2>오늘의 예정 회의</h2>
        <div id="meetings-list" class="meetings-list">
          <p class="meta">불러오는 중...</p>
        </div>
        <div id="meetings-pagination" class="meetings-pagination" style="display:none">
          <div class="meetings-page-size">
            <span class="meta">한 화면에</span>
            <button class="btn page-size-btn" data-size="5" onclick="setMeetingsPageSize(5)">5개</button>
            <button class="btn page-size-btn" data-size="10" onclick="setMeetingsPageSize(10)">10개</button>
            <button class="btn page-size-btn" data-size="20" onclick="setMeetingsPageSize(20)">20개</button>
          </div>
          <div class="meetings-page-nav">
            <button class="btn" onclick="changeMeetingsPage(-1)">‹ 이전</button>
            <span id="meetings-page-label" class="meta"></span>
            <button class="btn" onclick="changeMeetingsPage(1)">다음 ›</button>
          </div>
        </div>
      </div>
      {% endif %}
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_dashboard_route.py::test_dashboard_renders_device_card -v`
Expected: PASS

- [ ] **Step 5: `dashboard.js` — 정렬/페이지네이션 상태 및 렌더링 함수 추가**

현재 330~410행(`const deviceMeetingsCache = new Map();`부터 `loadUpcomingMeetings()` 끝까지, `formatMeetingTime`은 그대로 둠)을 다음으로 교체:

```js
const deviceMeetingsCache = new Map();

async function fetchDeviceMeetings(deviceId) {
  try {
    const resp = await fetch(`/api/devices/${deviceId}/obtp`);
    if (!resp.ok) return [];
    const data = await resp.json();
    if (!data.supported) return [];
    const now = new Date().toISOString();
    const upcoming = data.entries.filter((entry) => entry.start_time >= now || entry.end_time >= now);
    upcoming.sort((a, b) => a.start_time.localeCompare(b.start_time));
    return upcoming;
  } catch (e) {
    return [];
  }
}

function formatMeetingTime(isoString) {
  return isoString.replace("T", " ").slice(11, 16);
}

const MEETINGS_SORT_KEY = "bridgex.meetings.sort";
const MEETINGS_PAGE_SIZE_KEY = "bridgex.meetings.pageSize";
const MEETINGS_SORT_LABELS = { time: "시간", room: "회의실", subject: "회의명", join: "참가" };

const meetingsState = {
  rows: [],
  sortKey: "time",
  sortDir: "asc",
  pageSize: 10,
  page: 1,
};

function loadMeetingsPrefs() {
  try {
    const sort = JSON.parse(localStorage.getItem(MEETINGS_SORT_KEY) || "null");
    if (sort && sort.key && sort.dir) {
      meetingsState.sortKey = sort.key;
      meetingsState.sortDir = sort.dir;
    }
    const size = Number(localStorage.getItem(MEETINGS_PAGE_SIZE_KEY));
    if ([5, 10, 20].includes(size)) meetingsState.pageSize = size;
  } catch (e) {
    // localStorage 사용 불가 시 기본값(시간순 오름차순, 10개) 유지
  }
}

function saveMeetingsPrefs() {
  try {
    localStorage.setItem(
      MEETINGS_SORT_KEY,
      JSON.stringify({ key: meetingsState.sortKey, dir: meetingsState.sortDir })
    );
    localStorage.setItem(MEETINGS_PAGE_SIZE_KEY, String(meetingsState.pageSize));
  } catch (e) {
    // 무시 — 다음 방문 시 기본값으로 시작될 뿐 기능에는 영향 없음
  }
}

function meetingsSortValue(row, key) {
  if (key === "time") return row.entry.start_time;
  if (key === "room") return row.deviceName;
  if (key === "subject") return row.entry.subject;
  if (key === "join") return row.entry.join_uri ? 0 : 1; // 참가 링크 있는 행이 우선
  return "";
}

function sortMeetingsRows(rows) {
  const key = meetingsState.sortKey;
  const dir = meetingsState.sortDir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const av = meetingsSortValue(a, key);
    const bv = meetingsSortValue(b, key);
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return a.entry.start_time.localeCompare(b.entry.start_time);
  });
}

function setMeetingsSort(key) {
  if (meetingsState.sortKey === key) {
    meetingsState.sortDir = meetingsState.sortDir === "asc" ? "desc" : "asc";
  } else {
    meetingsState.sortKey = key;
    meetingsState.sortDir = "asc";
  }
  meetingsState.page = 1;
  saveMeetingsPrefs();
  renderMeetingsTable();
}

function setMeetingsPageSize(size) {
  meetingsState.pageSize = size;
  meetingsState.page = 1;
  saveMeetingsPrefs();
  renderMeetingsTable();
}

function changeMeetingsPage(delta) {
  const totalPages = Math.max(1, Math.ceil(meetingsState.rows.length / meetingsState.pageSize));
  meetingsState.page = Math.min(totalPages, Math.max(1, meetingsState.page + delta));
  renderMeetingsTable();
}

function renderMeetingsTable() {
  const container = document.getElementById("meetings-list");
  const pagination = document.getElementById("meetings-pagination");
  if (!container) return;
  container.textContent = "";

  if (meetingsState.rows.length === 0) {
    const p = document.createElement("p");
    p.className = "meta";
    p.textContent = "오늘 예정된 회의가 없습니다.";
    container.appendChild(p);
    if (pagination) pagination.style.display = "none";
    return;
  }

  const sorted = sortMeetingsRows(meetingsState.rows);
  const totalPages = Math.max(1, Math.ceil(sorted.length / meetingsState.pageSize));
  meetingsState.page = Math.min(meetingsState.page, totalPages);
  const start = (meetingsState.page - 1) * meetingsState.pageSize;
  const pageRows = sorted.slice(start, start + meetingsState.pageSize);

  const table = document.createElement("table");
  table.className = "meetings-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const key of ["time", "room", "subject", "join"]) {
    const th = document.createElement("th");
    const arrow = meetingsState.sortKey === key ? (meetingsState.sortDir === "asc" ? " ▲" : " ▼") : "";
    th.textContent = MEETINGS_SORT_LABELS[key] + arrow;
    th.addEventListener("click", () => setMeetingsSort(key));
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of pageRows) {
    const tr = document.createElement("tr");

    const timeTd = document.createElement("td");
    timeTd.textContent = formatMeetingTime(row.entry.start_time);
    tr.appendChild(timeTd);

    const roomTd = document.createElement("td");
    roomTd.textContent = row.deviceName;
    tr.appendChild(roomTd);

    const subjectTd = document.createElement("td");
    subjectTd.textContent = row.entry.subject;
    tr.appendChild(subjectTd);

    const joinTd = document.createElement("td");
    if (row.entry.join_uri) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "meeting-link";
      link.textContent = row.entry.join_uri;
      link.title = "참여하기";
      link.addEventListener("click", (ev) => joinMeetingLink(ev, row.deviceId, row.entry));
      joinTd.appendChild(link);
    } else {
      const span = document.createElement("span");
      span.className = "meta";
      span.textContent = "참가 정보 없음";
      joinTd.appendChild(span);
    }
    tr.appendChild(joinTd);

    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);

  if (pagination) {
    pagination.style.display = "flex";
    document.querySelectorAll(".page-size-btn").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.size) === meetingsState.pageSize);
    });
    const label = document.getElementById("meetings-page-label");
    if (label) label.textContent = `${meetingsState.page} / ${totalPages}페이지 (전체 ${sorted.length}건)`;
  }
}

async function loadUpcomingMeetings() {
  const rows = [];

  for (const card of document.querySelectorAll(".device-card")) {
    const deviceId = card.dataset.deviceId;
    const nameEl = card.querySelector("h3");
    const deviceName = nameEl ? nameEl.firstChild.textContent.trim() : deviceId;
    const entries = await fetchDeviceMeetings(deviceId);
    deviceMeetingsCache.set(deviceId, entries);
    for (const entry of entries) rows.push({ deviceId, deviceName, entry });
    renderCardTeamsSection(deviceId, entries);
  }

  meetingsState.rows = rows;
  renderMeetingsTable();
}
```

주의: 원본 파일의 `joinMeetingLink(...)`, `renderCardTeamsSection(...)` 함수는 이 블록 **뒤에** 그대로 남아있으므로 삭제하지 않는다 — 위 교체 범위는 `deviceMeetingsCache` 선언부터 기존 `loadUpcomingMeetings()`의 닫는 `}`까지다.

- [ ] **Step 6: DOMContentLoaded에 `loadMeetingsPrefs()` 호출 추가**

현재 542~551행:
```js
document.addEventListener("DOMContentLoaded", () => {
  connectStatusSocket();
  updateStatBar();
  loadUpcomingMeetings();
  wireDialEnterKey();
  document.querySelectorAll('[data-field="reboot-text"]').forEach((el) => {
    const seconds = el.dataset.uptimeSeconds;
    el.textContent = formatLastReboot(seconds);
  });
});
```
다음으로 교체:
```js
document.addEventListener("DOMContentLoaded", () => {
  connectStatusSocket();
  updateStatBar();
  loadMeetingsPrefs();
  loadUpcomingMeetings();
  wireDialEnterKey();
  document.querySelectorAll('[data-field="reboot-text"]').forEach((el) => {
    const seconds = el.dataset.uptimeSeconds;
    el.textContent = formatLastReboot(seconds);
  });
});
```

- [ ] **Step 7: CSS 교체**

`app/static/css/style.css`의 현재 234~252행:
```css
.meetings-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.meeting-row {
  display: grid;
  grid-template-columns: 90px 1fr 2fr auto;
  align-items: center;
  gap: 0.75rem;
  padding: 0.4rem 0.5rem;
  border-radius: 6px;
  font-size: 0.86rem;
}

.meeting-row:nth-child(odd) {
  background: var(--color-bg);
}
```
다음으로 교체:
```css
.meetings-list {
  font-size: 0.86rem;
}

.meetings-table {
  width: 100%;
  border-collapse: collapse;
}

.meetings-table th,
.meetings-table td {
  text-align: left;
  padding: 0.4rem 0.5rem;
}

.meetings-table th {
  cursor: pointer;
  color: var(--color-text-muted);
  font-weight: 600;
  user-select: none;
  border-bottom: 1px solid var(--color-border);
}

.meetings-table tbody tr:nth-child(odd) {
  background: var(--color-bg);
}

.meetings-pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.6rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.meetings-page-size,
.meetings-page-nav {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.page-size-btn.active {
  background: var(--color-call);
  border-color: var(--color-call);
  color: #fff;
}
```

- [ ] **Step 8: 전체 회귀 확인**

Run: `pytest -q`
Expected: 전체 PASS

- [ ] **Step 9: 수동 확인**

`py run.py` 실행 → 회의가 여러 건 있는 상태(시뮬레이터 장비로 충분)에서: 각 헤더(시간/회의실/회의명/참가) 클릭 시 정렬 방향이 바뀌는지, 페이지 크기 5/10/20 전환, 이전/다음 페이지 이동, 새로고침 후에도 정렬 기준·페이지 크기가 유지되는지(페이지 번호는 1로 리셋되는 게 정상) 확인. `docs/PIPELINE.md` §3 체크리스트에 이 케이스 추가를 권장(별도 태스크는 아님).

- [ ] **Step 10: 커밋**

```bash
git add app/templates/index.html app/static/js/dashboard.js app/static/css/style.css tests/test_dashboard_route.py
git commit -m "feat: 오늘의 예정 회의 목록에 정렬/페이지네이션 추가"
```

---

## Self-Review 결과

- **스펙 커버리지**: 설계 문서 5개 섹션 모두 Task 1~7에 매핑됨 — ①그룹 관리(Task 1~3), ②일괄 제어 제거(Task 4), ③정렬/페이지네이션(Task 7), ④다크모드 기본값(Task 5), ⑤로그 복사/다운로드(Task 6).
- **플레이스홀더 스캔**: "TBD"/"추후"/"적절히 처리" 등 없음 — 전 단계 실제 코드/커맨드 포함.
- **타입/시그니처 일관성**: `rename_group`/`clear_group`(Task 1) 시그니처가 Task 2 라우터 호출부와 일치, `meetingsState`/`renderMeetingsTable`/`setMeetingsSort` 등 Task 7 내부에서 이름 일관됨.
- **범위 점검**: 각 태스크가 독립적으로 커밋 가능한 단위이며, Task 1~3(그룹 관리)만 서로 의존(순서대로 실행 필요). Task 4~7은 서로 독립적이라 순서 무관하게 실행 가능.
