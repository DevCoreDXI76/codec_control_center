# 다중 PC 인스턴스 제어 명령 충돌 방지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 재부팅/다이얼/참가(join) 명령을 실제로 장비에 보내기 직전, 서버가 그 순간 장비의
실제 통화 상태를 fresh하게 재확인해, 다른 PC 인스턴스가 이미 시작한 통화를 놓치고 중복
참가·하울링·오재부팅으로 이어지는 사고를 막는다.

**Architecture:** 새 프로세스/공유 인프라 없음. `app/core/driver_base.py`에 `DriverConflictError`
예외를 추가하고, `app/api/routes_control.py`에 공용 가드 헬퍼 `reject_if_in_call()`을 추가해
`reboot`/`dial`(routes_control.py)과 `join`/`direct-dial`(routes_teams.py) 4개 라우트에서
`PollingScheduler.run_with_driver()`(이미 장비별 `asyncio.Lock`으로 직렬화됨)에 넘기는 동작을
"확인 → 실행"으로 감싼다. `DriverConflictError`는 각 라우트에서 409로 매핑한다.

**Tech Stack:** FastAPI, Python 3.11, pytest (기존 스택 그대로, 신규 의존성 없음).

## Global Constraints

- 스펙 문서: `docs/superpowers/specs/2026-08-03-multi-instance-control-race-guard-design.md`
- 적용 대상은 `reboot`, `dial`(routes_control.py), `direct-dial`, `join`(routes_teams.py) 4개
  라우트뿐 — `mute`/`unmute`/`hangup`은 대상 아님(스펙 §2).
- 재부팅은 통화 중이면 **차단**(경고 후 허용 아님) — 스펙에서 사용자가 확정한 정책.
- 프런트엔드 코드 변경 없음 — `dashboard.js`의 `callControl()`(118-133행)과 `directDial()`의
  raw fetch(590-623행) 둘 다 이미 `!resp.ok`일 때 `data.detail`을 토스트로 그대로 보여주므로,
  409 응답도 추가 코드 없이 자동으로 표시된다. 이 사실을 재확인 없이 다시 조사하지 말 것.
- 매 코드 수정 후 `pytest -q`(현재 299개, 프로젝트 루트에서 `.venv`로 실행)를 전체 통과시킨다
  (PIPELINE.md §2).
- 새 동작에는 반드시 테스트를 함께 추가한다(PIPELINE.md §2, 이 프로젝트의 기존 관행).

---

### Task 1: `DriverConflictError` 예외 추가

**Files:**
- Modify: `app/core/driver_base.py:44-49` (기존 `DriverCommandError`/`DriverTimeoutError` 사이 또는 뒤에 추가)
- Test: `tests/core/test_driver_base.py`

**Interfaces:**
- Produces: `app.core.driver_base.DriverConflictError` — `DriverError`의 서브클래스. 이후
  Task 2/3에서 `except DriverConflictError`로 잡아 409로 매핑하는 데 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/core/test_driver_base.py`의 기존 `test_driver_error_hierarchy` 아래에 추가:

```python
def test_driver_conflict_error_is_a_driver_error():
    from app.core.driver_base import DriverConflictError

    assert issubclass(DriverConflictError, DriverError)
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/core/test_driver_base.py::test_driver_conflict_error_is_a_driver_error -v`
Expected: FAIL — `ImportError: cannot import name 'DriverConflictError'`

- [ ] **Step 3: 최소 구현**

`app/core/driver_base.py`의 `class DriverTimeoutError(DriverError):` 블록(48-49행) 바로 뒤에 추가:

```python
class DriverConflictError(DriverError):
    """다른 위치(다른 PC 인스턴스 등)에서 이미 통화 중이라 명령을 거부함."""
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/core/test_driver_base.py -v`
Expected: 전체 PASS (기존 테스트 포함, 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add app/core/driver_base.py tests/core/test_driver_base.py
git commit -m "feat: add DriverConflictError for in-call command guard"
```

---

### Task 2: `routes_control.py` — reboot/dial에 fresh 재확인 가드 적용

**Files:**
- Modify: `app/api/routes_control.py`
- Test: `tests/api/test_routes_control.py`

**Interfaces:**
- Consumes: `DriverConflictError`(Task 1), `DeviceDriver.get_status() -> DeviceStatus`(기존, `driver_base.py`)
- Produces: `app.api.routes_control.reject_if_in_call(driver: DeviceDriver) -> None` — Task 3에서
  `routes_teams.py`가 그대로 import해서 재사용한다(로직 중복 작성 금지).
  `_run_control()`에 새 파라미터 `guard: Callable[[DeviceDriver], Awaitable[None]] | None = None` 추가
  (기존 호출부 3곳 중 `mute`/`hangup`은 `guard` 생략, `reboot`/`dial`만 지정).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_control.py`의 `_BoomDriver` 클래스 위(122행 근처)에 새 가짜 드라이버를 추가하고,
파일 맨 아래에 테스트 2개를 추가:

```python
class _InCallAwareDriver(DeviceDriver):
    """get_status()의 in_call을 자유롭게 설정해 가드 로직만 독립적으로 검증하기 위한 가짜 드라이버."""

    def __init__(self, in_call: bool = False) -> None:
        self.in_call = in_call
        self.reboot_called = False
        self.dialed_address: str | None = None

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(online=True, in_call=self.in_call, muted=False, call_peer=None, last_polled_at="now")

    async def mute(self, on: bool) -> bool:
        return True

    async def dial(self, address: str) -> bool:
        self.dialed_address = address
        return True

    async def hangup(self) -> bool:
        return True

    async def reboot(self) -> bool:
        self.reboot_called = True
        return True

    async def get_calendar_status(self) -> str:
        return "registered"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        return []

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        return True


def _register_device_with_driver(driver: DeviceDriver) -> str:
    credential_ref = app.state.vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = app.state.registry.add_device(
        name="통화중장비",
        vendor="cisco",
        connection_type="ssh",
        host="127.0.0.1",
        port=1,
        group="TEST",
        credential_ref=credential_ref,
        is_simulated=True,
    )
    app.state.scheduler = PollingScheduler(driver_factory=lambda device_id: driver)
    asyncio.run(app.state.scheduler.add_device(device.id))
    return device.id


def test_reboot_blocked_when_in_call(client):
    driver = _InCallAwareDriver(in_call=True)
    device_id = _register_device_with_driver(driver)

    resp = client.post(f"/api/devices/{device_id}/reboot")

    assert resp.status_code == 409
    assert "이미 통화 중" in resp.json()["detail"]
    assert driver.reboot_called is False
    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].action == "reboot"
    assert entries[0].success is False


def test_dial_blocked_when_in_call(client):
    driver = _InCallAwareDriver(in_call=True)
    device_id = _register_device_with_driver(driver)

    resp = client.post(f"/api/devices/{device_id}/dial", json={"address": "1234@example.com"})

    assert resp.status_code == 409
    assert "이미 통화 중" in resp.json()["detail"]
    assert driver.dialed_address is None
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_routes_control.py -k "blocked_when_in_call" -v`
Expected: 둘 다 FAIL — 현재는 `in_call` 여부와 무관하게 그냥 200이 돌아옴(`resp.status_code == 409` 단언 실패)

- [ ] **Step 3: 최소 구현**

`app/api/routes_control.py` 12행의 import를 아래로 교체:

```python
from app.core.driver_base import DeviceDriver, DriverConflictError, DriverError
```

`_get_registry` 함수(38-39행) 뒤에 새 함수 추가:

```python
async def reject_if_in_call(driver: DeviceDriver) -> None:
    """위험한 명령을 실제로 보내기 직전, 그 순간 장비의 실제 통화 상태를 재확인한다.
    폴링 캐시(최대 120초 지연)를 믿지 않고 매번 fresh하게 물어본다 — 여러 PC가 각자
    독립적으로 이 장비를 조작할 수 있어, 캐시만 믿으면 다른 PC가 방금 시작한 통화를
    놓치고 중복 참가/오재부팅으로 이어질 수 있다(2026-08 다중 PC 배포 이후 확인된 리스크,
    docs/superpowers/specs/2026-08-03-multi-instance-control-race-guard-design.md)."""
    status = await driver.get_status()
    if status.in_call:
        raise DriverConflictError("다른 위치에서 이미 통화 중입니다 — 종료 후 다시 시도해주세요")
```

`_run_control` 함수(75-104행) 전체를 아래로 교체:

```python
async def _run_control(
    request: Request,
    device_id: str,
    action_name: str,
    action: Callable[[DeviceDriver], Awaitable[bool]],
    detail: str | None = None,
    guard: Callable[[DeviceDriver], Awaitable[None]] | None = None,
) -> dict:
    scheduler = _get_scheduler(request)
    history = _get_history(request)
    device = _get_registry(request).get_device(device_id)
    device_name = device.name if device is not None else device_id

    async def guarded(driver: DeviceDriver) -> bool:
        if guard is not None:
            await guard(driver)
        return await action(driver)

    try:
        ok = await scheduler.run_with_driver(device_id, guarded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DriverConflictError as exc:
        logger.info("device %s %s blocked: %s", device_name, action_name, exc)
        history.log(device_id=device_id, device_name=device_name, action=action_name, success=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DriverError as exc:
        logger.warning("device %s %s failed: %s", device_name, action_name, exc)
        history.log(device_id=device_id, device_name=device_name, action=action_name, success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # DriverError가 아닌 예상 밖 예외 — 삼키지 않고 트레이스백까지 남긴다.
        logger.exception(
            "device %s %s raised unexpected error", device_name, action_name
        )
        history.log(
            device_id=device_id, device_name=device_name, action=action_name, success=False, detail=str(exc)
        )
        raise HTTPException(status_code=502, detail=f"unexpected error: {exc}") from exc

    history.log(device_id=device_id, device_name=device_name, action=action_name, success=ok, detail=detail)
    return {"ok": ok}
```

`reboot()`, `dial()` 라우트(52-72행)를 아래로 교체:

```python
@router.post("/{device_id}/mute")
async def mute(device_id: str, payload: MuteRequest, request: Request) -> dict:
    action = "mute" if payload.on else "unmute"
    return await _run_control(request, device_id, action, lambda driver: driver.mute(payload.on))


@router.post("/{device_id}/dial")
async def dial(device_id: str, payload: DialRequest, request: Request) -> dict:
    return await _run_control(
        request, device_id, "dial", lambda driver: driver.dial(payload.address), detail=payload.address,
        guard=reject_if_in_call,
    )


@router.post("/{device_id}/hangup")
async def hangup(device_id: str, request: Request) -> dict:
    return await _run_control(request, device_id, "hangup", lambda driver: driver.hangup())


@router.post("/{device_id}/reboot")
async def reboot(device_id: str, request: Request) -> dict:
    return await _run_control(request, device_id, "reboot", lambda driver: driver.reboot(), guard=reject_if_in_call)
```

(`tests/api/test_routes_control.py` 7행은 이미 `from app.core.driver_base import CalendarEntry, DeviceDriver, DeviceStatus`로
`CalendarEntry`를 import하고 있으므로 추가 작업 불필요.)

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_routes_control.py -v`
Expected: 전체 PASS — 새 테스트 2개 포함, 기존 `test_reboot`/`test_dial_and_hangup`(시뮬레이터
대상, `in_call=False` 기본값)도 회귀 없이 그대로 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add app/api/routes_control.py tests/api/test_routes_control.py
git commit -m "feat: block reboot/dial when device is already in a call"
```

---

### Task 3: `routes_teams.py` — direct-dial/join에 동일 가드 적용

**Files:**
- Modify: `app/api/routes_teams.py`
- Test: `tests/api/test_routes_teams.py`

**Interfaces:**
- Consumes: `app.api.routes_control.reject_if_in_call`(Task 2), `DriverConflictError`(Task 1)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_teams.py`의 `FakeTeamsDriver.__init__`(23-26행)과 `get_status()`(34-35행)를
아래로 교체(생성자에 `in_call` 파라미터 추가):

```python
class FakeTeamsDriver(DeviceDriver):
    def __init__(self, calendar_supported: bool = True, in_call: bool = False) -> None:
        self.calendar_supported = calendar_supported
        self.in_call = in_call
        self.joined_entry: CalendarEntry | None = None
        self.dialed_address: str | None = None

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(online=True, in_call=self.in_call, muted=False, call_peer=None, last_polled_at="now")
```

`_register()` 헬퍼(90-106행)의 시그니처와 내부 호출을 아래로 교체:

```python
def _register(
    client, calendar_supported: bool = True, teams_tenant_address: str | None = None, in_call: bool = False
) -> tuple[str, FakeTeamsDriver]:
    credential_ref = app.state.vault.store('{"username":"admin","password":"pw"}')
    device = app.state.registry.add_device(
        name="테스트 회의실",
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group="TEST",
        credential_ref=credential_ref,
        is_simulated=True,
        teams_tenant_address=teams_tenant_address,
    )
    fake_driver = FakeTeamsDriver(calendar_supported=calendar_supported, in_call=in_call)
    app.state.scheduler = PollingScheduler(driver_factory=lambda device_id: fake_driver)
    asyncio.run(app.state.scheduler.add_device(device.id))
    return device.id, fake_driver
```

파일 맨 아래에 테스트 2개 추가:

```python
def test_join_meeting_blocked_when_in_call(client):
    device_id, driver = _register(client, in_call=True)
    resp = client.post(
        f"/api/devices/{device_id}/join",
        json={
            "subject": "주간 전체회의",
            "start_time": "2026-07-29T14:00:00",
            "end_time": "2026-07-29T15:00:00",
            "join_uri": "sip:weekly@example.com",
        },
    )
    assert resp.status_code == 409
    assert driver.joined_entry is None


def test_direct_dial_blocked_when_in_call(client):
    device_id, driver = _register(client, teams_tenant_address="vc.poscodx.com", in_call=True)
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 409
    assert driver.dialed_address is None
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_routes_teams.py -k "blocked_when_in_call" -v`
Expected: 둘 다 FAIL — `resp.status_code == 409` 단언 실패(현재는 200)

- [ ] **Step 3: 최소 구현**

`app/api/routes_teams.py` 19행의 import를 아래로 교체:

```python
from app.core.driver_base import CalendarEntry, DriverConflictError, DriverError
from app.api.routes_control import reject_if_in_call
```

`join_meeting()`(73-94행)을 아래로 교체:

```python
@router.post("/{device_id}/join")
async def join_meeting(device_id: str, payload: JoinRequest, request: Request) -> dict:
    history: ControlHistory = request.app.state.history
    registry: DeviceRegistry = request.app.state.registry
    device = registry.get_device(device_id)
    device_name = device.name if device is not None else device_id

    entry = CalendarEntry(
        subject=payload.subject,
        start_time=payload.start_time,
        end_time=payload.end_time,
        join_uri=payload.join_uri,
    )

    async def guarded(driver):
        await reject_if_in_call(driver)
        return await driver.join_meeting(entry)

    try:
        ok = await _get_scheduler(request).run_with_driver(device_id, guarded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DriverConflictError as exc:
        history.log(device_id=device_id, device_name=device_name, action="join", success=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DriverError as exc:
        history.log(device_id=device_id, device_name=device_name, action="join", success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.log(device_id=device_id, device_name=device_name, action="join", success=ok, detail=payload.subject)
    return {"ok": ok}
```

`direct_dial()`(97-128행)의 마지막 `try` 블록(120-127행)을 아래로 교체:

```python
    try:
        async def guarded(driver):
            await reject_if_in_call(driver)
            return await driver.dial(address)

        ok = await _get_scheduler(request).run_with_driver(device_id, guarded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DriverConflictError as exc:
        history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DriverError as exc:
        history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=ok, detail=address)
    return {"ok": ok, "address": address}
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_routes_teams.py -v`
Expected: 전체 PASS — 새 테스트 2개 포함, 기존 `test_join_meeting_success`/`test_direct_dial_*`
(모두 `in_call` 기본값 False)도 회귀 없이 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add app/api/routes_teams.py tests/api/test_routes_teams.py
git commit -m "feat: block direct-dial/join when device is already in a call"
```

---

### Task 4: 전체 테스트 확인 + 버전/릴리즈 (PIPELINE.md §2/§4)

**Files:**
- Modify: `app/__version__.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/PIPELINE.md` (§3 수동 QA 체크리스트에 항목 추가)

**Interfaces:** 없음(문서/버전 정리 작업, 코드 인터페이스 변경 없음)

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 전체 PASS (Task 1~3 이전 299개 + 신규 4개 = 303개 근방, 정확한 숫자는 실행 결과로 확인)

- [ ] **Step 2: 버전 올림**

`app/__version__.py`의 docstring 마지막(1.6.1 항목 뒤)에 추가, `__version__` 값도 갱신:

```python
1.6.2 = 직원 배포 이후 여러 PC가 같은 장비를 동시에 폴링·제어하는 상황에서, v1.5.19의
"통화 중 중복 참가 방지" 가드가 인스턴스별 폴링 캐시(최대 120초 지연)에만 의존해 다른 PC의
조작을 놓칠 수 있는 레이스 윈도우를 확인 — 재부팅/다이얼/direct-dial/join 실행 직전 서버가
그 순간 장비 상태를 fresh하게 재확인해, 통화 중이면 명령을 보내지 않고 409로 차단하도록
수정(`routes_control.py`, `routes_teams.py`, 신규 `DriverConflictError`). 설계 근거는
docs/superpowers/specs/2026-08-03-multi-instance-control-race-guard-design.md.
"""

__version__ = "1.6.2"
```

- [ ] **Step 3: CHANGELOG.md 갱신**

`## [Unreleased]` 아래에 추가:

```markdown
## [1.6.2] - 2026-08-03

다중 PC 인스턴스 동시 제어 시 안전장치 추가.

### Fixed
- **안전 문제**: 여러 PC가 같은 장비를 각자 독립적으로 폴링·제어하는 상황에서, 한 PC가
  방금 시작한 통화를 다른 PC가 폴링 지연(최대 120초)으로 놓쳐 재부팅/다이얼/참가를
  중복 실행할 수 있는 레이스 컨디션 확인 — reboot/dial/direct-dial/join 실행 직전 서버가
  장비의 실제 통화 상태를 fresh하게 재확인하도록 수정, 통화 중이면 409로 차단
  (`routes_control.py`, `routes_teams.py`).
```

- [ ] **Step 4: PIPELINE.md 수동 QA 체크리스트에 항목 추가**

`docs/PIPELINE.md` §3 체크리스트(47-60행 근방)에 추가:

```markdown
- [ ] (2026-08-03 추가) 통화 중인 장비를 대상으로 다른 브라우저 탭에서 재부팅/다이얼/참가를
      시도 → "이미 통화 중입니다" 409 응답과 `/logs` 기록 확인
```

- [ ] **Step 5: 커밋 및 태그**

```bash
git add app/__version__.py CHANGELOG.md docs/PIPELINE.md
git commit -m "chore: v1.6.2 — 다중 PC 인스턴스 제어 명령 충돌 방지"
git tag v1.6.2
```
