# Teams 수동 다이얼 + 장비 카드 v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codec Control Center 장비 카드에 모델명/가동시간(재부팅 경과) 표시, 아이콘 기반 제어 버튼,
Teams 오늘 회의 목록(미래 회의만, 시간순)과 회의ID+테넌트 수동 다이얼 기능을 추가한다.

**Architecture:** 모델/가동시간은 Poly/Cisco 드라이버가 확인된 명령(`systemsetting get model`/
`uptime get`, `xStatus SystemUnit ProductId`/`Uptime`)으로 조회해 `DeviceStatus`에 실어 보내고,
`PollingScheduler`가 최초 확보된 모델명을 콜백으로 레지스트리에 1회성 반영한다. 수동 다이얼은
새 `POST /api/devices/{id}/direct-dial` 엔드포인트가 장비별/전역 테넌트 주소를 계산해 기존
`driver.dial()`을 재사용한다(드라이버 변경 불필요). 프론트엔드는 기존 카드 마크업을 확장하고
Alpine.js 등록 모달을 등록/수정 겸용으로 바꾼다.

**Tech Stack:** FastAPI, Jinja2, Alpine.js(CDN 없이 vendor 번들), 순수 JS(dashboard.js), pytest.

## Global Constraints

- 제조사 명령은 공식 문서로 확인된 것만 사용한다 — 이번 플랜에서 쓰는 명령은 모두
  `docs/superpowers/specs/2026-07-30-teams-direct-dial-device-card-design.md` §1에서 출처와
  함께 확인됨.
- 모든 백엔드 변경은 `pytest -q`(프로젝트 루트, `.venv`)로 검증하고, 새 동작마다 테스트를
  같이 추가한다 (`docs/PIPELINE.md` §2).
- 프론트엔드(JS/템플릿/CSS) 변경은 pytest로 검증할 수 없다 — 이 프로젝트에는 JS 테스트 러너가
  없다(기존 관례). 대신 dev 서버를 띄워 브라우저에서 직접 확인하고, `docs/PIPELINE.md` §3
  체크리스트에 항목을 추가해 QA 절차로 남긴다(마지막 태스크).
- 기존 `Device`/`AppSettings` 저장 파일은 새 필드가 없어도(구버전 파일) 기본값으로 정상
  로드되어야 한다 — 스키마 버전을 올릴 필요는 없다(기존 필드 추가 방식과 동일).
- 커밋은 태스크 단위로 작게 나눈다 (`docs/PIPELINE.md` §1).

---

### Task 1: DeviceStatus에 model/uptime_seconds 필드 추가

**Files:**
- Modify: `app/core/driver_base.py:12-19`
- Test: `tests/core/test_driver_base.py`

**Interfaces:**
- Produces: `DeviceStatus.model: str | None = None`, `DeviceStatus.uptime_seconds: int | None = None`
  — 이후 모든 태스크가 이 두 필드를 채우거나 읽는다.

- [ ] **Step 1: 기존 테스트 확인 (회귀 방지 기준선)**

Run: `cd c:/MyProjects/01_Portfolio/codec_control_center && .venv/Scripts/python.exe -m pytest tests/core/test_driver_base.py -v`
Expected: 기존 테스트 전부 PASS (아직 필드 없음 — 이 파일에 새 테스트가 없다면 통과할 테스트가
없다는 메시지가 떠도 정상. `tests/core/` 디렉터리에 `test_driver_base.py`가 없다면 이 스텝에서
새로 만든다).

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/core/test_driver_base.py` (파일이 없으면 새로 생성):
```python
from app.core.driver_base import DeviceStatus


def test_device_status_model_and_uptime_default_to_none():
    status = DeviceStatus(online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now")
    assert status.model is None
    assert status.uptime_seconds is None


def test_device_status_accepts_model_and_uptime():
    status = DeviceStatus(
        online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now",
        model="RealPresence Group 700", uptime_seconds=3660,
    )
    assert status.model == "RealPresence Group 700"
    assert status.uptime_seconds == 3660
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_driver_base.py -v`
Expected: FAIL — `TypeError: DeviceStatus.__init__() got an unexpected keyword argument 'model'`

- [ ] **Step 4: 필드 추가**

`app/core/driver_base.py` 12-19행을 다음으로 교체:
```python
@dataclass
class DeviceStatus:
    online: bool
    in_call: bool
    muted: bool
    call_peer: str | None
    last_polled_at: str
    error: str | None = None
    model: str | None = None
    uptime_seconds: int | None = None
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_driver_base.py -v`
Expected: PASS

- [ ] **Step 6: 전체 스위트로 회귀 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 기존 205개 전부 PASS + 새 테스트 2개

```bash
git add app/core/driver_base.py tests/core/test_driver_base.py
git commit -m "feat: add model/uptime_seconds fields to DeviceStatus"
```

---

### Task 2: Poly 드라이버 — 모델명/가동시간 조회

**Files:**
- Modify: `app/drivers/poly/poly_commands.py` (끝에 추가)
- Modify: `app/drivers/poly/poly_driver.py`
- Test: `tests/drivers/test_poly_driver.py`

**Interfaces:**
- Consumes: `DeviceStatus.model`/`uptime_seconds` (Task 1).
- Produces: `poly_commands.SYSTEMSETTING_GET_MODEL`, `poly_commands.UPTIME_GET` 상수;
  `poly_driver._parse_uptime(text: str) -> int | None`(모듈 레벨 함수, 다른 태스크에서 import
  하지 않음 — 테스트에서만 직접 참조); `PolyDriver.get_status()` 결과에 `model`/`uptime_seconds`
  포함.

- [ ] **Step 1: 실패하는 파서 단위 테스트 작성**

`tests/drivers/test_poly_driver.py` 파일 맨 위 import 블록에 추가:
```python
from app.drivers.poly.poly_driver import PolyDriver, _parse_uptime
```
(기존에 `from app.drivers.poly.poly_driver import PolyDriver`만 있다면 `_parse_uptime`을 같이
import하도록 수정.)

파일 끝에 추가:
```python
def test_parse_uptime_hours_and_minutes():
    assert _parse_uptime("1 Hour, 10 Minutes") == 3660


def test_parse_uptime_minutes_only():
    assert _parse_uptime("45 Minutes") == 2700


def test_parse_uptime_days_hours_minutes():
    assert _parse_uptime("3 Days, 2 Hours, 5 Minutes") == 3 * 86400 + 2 * 3600 + 5 * 60


def test_parse_uptime_unparseable_returns_none():
    assert _parse_uptime("garbage response") is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_poly_driver.py -k parse_uptime -v`
Expected: FAIL — `ImportError: cannot import name '_parse_uptime'`

- [ ] **Step 3: poly_commands.py에 명령 상수 추가**

`app/drivers/poly/poly_commands.py` 파일 끝(`calendarmeetings_info` 함수 다음)에 추가:
```python
# --- systemsetting model / uptime — 확인됨 (Integrator Reference Guide p.352, p.372) ---
# systemsetting get model -> 응답: systemsetting model "RealPresence Group 700"
SYSTEMSETTING_GET_MODEL = "systemsetting get model"
# uptime get -> 응답: "1 Hour, 10 Minutes" (사람이 읽는 문자열, 명령어 자체가 최상위 커맨드)
UPTIME_GET = "uptime get"
```

- [ ] **Step 4: poly_driver.py에 파서와 모델/가동시간 조회 로직 추가**

`app/drivers/poly/poly_driver.py` 상단 import 블록(`import asyncio` 다음 줄)에 `import re` 추가:
```python
import asyncio
import re
import socket
```

`PolyDriver.__init__`의 `self._ssh_buffer = b""` 다음 줄에 추가:
```python
        self._model: str | None = None
```

`connect()` 메서드 전체를 다음으로 교체 (기존 ssh 분기의 `return`을 제거하고 마지막에
`_fetch_model` 호출을 공통으로 추가):
```python
    async def connect(self) -> None:
        if self.transport == "ssh":
            await asyncio.to_thread(self._connect_ssh_sync)
        else:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    telnetlib3.open_connection(self.host, self.port), timeout=self.timeout
                )
            except asyncio.TimeoutError as exc:
                raise DriverTimeoutError(f"connect timeout: {self.host}:{self.port}") from exc
            except OSError as exc:
                raise DriverConnectionError(str(exc)) from exc
        await self._fetch_model()

    async def _fetch_model(self) -> None:
        """모델명은 하드웨어가 바뀌지 않는 한 안 변하므로 연결 시 1회만 조회해 캐시한다.
        조회 실패는 connect() 전체를 실패시키지 않는다(있으면 좋은 정보일 뿐)."""
        try:
            resp = await self._call(cmd.SYSTEMSETTING_GET_MODEL)
        except DriverError:
            return
        match = re.search(r'"([^"]+)"', resp)
        if match:
            self._model = match.group(1)
```

`get_status()` 메서드 전체를 다음으로 교체:
```python
    async def get_status(self) -> DeviceStatus:
        now = datetime.now(timezone.utc).isoformat()
        try:
            mute_resp = await self._call(cmd.MUTE_NEAR_GET)
            muted = mute_resp == "mute near on"

            call_lines = await self._call_block(cmd.CALLINFO_ALL, "callinfo begin", "callinfo end")
            in_call = bool(call_lines) and call_lines[0] != "system is not in a call"
            call_peer = None
            if in_call:
                parts = call_lines[0].split(":")
                if len(parts) > 2:
                    call_peer = parts[2]

            uptime_resp = await self._call(cmd.UPTIME_GET)
            uptime_seconds = _parse_uptime(uptime_resp)

            return DeviceStatus(
                online=True,
                in_call=in_call,
                muted=muted,
                call_peer=call_peer,
                last_polled_at=now,
                model=self._model,
                uptime_seconds=uptime_seconds,
            )
        except DriverError as exc:
            return DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=now,
                error=str(exc),
                model=self._model,
            )
```

파일 맨 끝(마지막 `join_meeting` 메서드 다음, 클래스 바깥)에 모듈 레벨 함수 추가:
```python
_UPTIME_UNIT_SECONDS = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}


def _parse_uptime(text: str) -> int | None:
    """Poly "uptime get" 응답("1 Hour, 10 Minutes" 형식)을 초로 환산한다.
    Day 단위 표기가 실제로 포함되는지는 문서에 예시가 없어 미확인 — Day/Hour/Minute/Second를
    느슨하게(대소문자 무관, 단수/복수 무관) 인식하고, 하나도 못 찾으면 None을 반환해
    상위 계층이 원문을 그대로 보여줄 수 있게 한다."""
    total = 0
    found = False
    for match in re.finditer(r"(\d+)\s*(day|hour|minute|second)s?", text, re.IGNORECASE):
        found = True
        value = int(match.group(1))
        unit = match.group(2).lower()
        total += value * _UPTIME_UNIT_SECONDS[unit]
    return total if found else None
```

- [ ] **Step 5: 파서 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_poly_driver.py -k parse_uptime -v`
Expected: PASS (4개)

- [ ] **Step 6: 시뮬레이터 대상 통합 테스트 추가 (아직 시뮬레이터가 응답 안 하므로 실패 예상)**

`tests/drivers/test_poly_driver.py`의 `test_full_lifecycle_no_exceptions` 함수 다음에 추가:
```python
async def test_get_status_includes_model_and_uptime(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.model == "RealPresence Group 500 (SIM)"
    assert status.uptime_seconds is not None
```

- [ ] **Step 7: 실패 확인 (시뮬레이터가 아직 이 명령을 모름)**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_poly_driver.py::test_get_status_includes_model_and_uptime -v`
Expected: FAIL — `assert None == "RealPresence Group 500 (SIM)"`

(Task 3에서 시뮬레이터를 구현하면 이 테스트가 통과한다 — 지금은 실패 상태로 커밋하지 않고
다음 태스크로 이어간다.)

- [ ] **Step 8: 여기까지 커밋 (Task 3 완료 후 이 테스트도 같이 커밋될 예정이므로 이 스텝은 생략
  하고 Task 3의 커밋에 포함시킨다)**

Task 2는 별도 커밋 없이 Task 3과 함께 커밋한다 — `test_get_status_includes_model_and_uptime`이
실패 상태로는 중간 커밋을 만들지 않는다(PIPELINE.md §2: pytest 전체 통과가 커밋 전 게이트).

---

### Task 3: Poly 시뮬레이터 — 모델/가동시간 응답 추가

**Files:**
- Modify: `app/simulator/poly_sim_server.py`

**Interfaces:**
- Consumes: 없음 (독립적인 시뮬레이터 상태 추가).
- Produces: `PolySimServer`가 `systemsetting get model`과 `uptime get`에 응답 — Task 2의
  `test_get_status_includes_model_and_uptime`이 이 태스크 완료 후 통과해야 한다.

- [ ] **Step 1: PolySimState에 모델/가동시간 필드 추가**

`app/simulator/poly_sim_server.py`의 `PolySimState` 데이터클래스(`calendar_established: bool = True`
줄 다음)에 추가:
```python
    model: str = "RealPresence Group 500 (SIM)"
    uptime_text: str = "2 Hours, 5 Minutes"
```

- [ ] **Step 2: handle()에 분기 추가**

`handle()` 메서드의 `if verb == "calendarmeetings":` 블록 다음(`return None` 이전)에 추가:
```python
        if verb == "systemsetting":
            return self._handle_systemsetting(tokens)
        if verb == "uptime":
            return self._handle_uptime(tokens)
```

`_handle_calendarmeetings` 메서드 다음(클래스 안, 파일 끝 direction)에 새 메서드 추가:
```python
    def _handle_systemsetting(self, tokens: list[str]) -> str | None:
        if tokens[1:3] == ["get", "model"]:
            return f'systemsetting model "{self.state.model}"'
        return None

    def _handle_uptime(self, tokens: list[str]) -> str | None:
        if tokens[1:] == ["get"]:
            return self.state.uptime_text
        return None
```

- [ ] **Step 3: Task 2에서 작성한 통합 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_poly_driver.py::test_get_status_includes_model_and_uptime -v`
Expected: PASS

- [ ] **Step 4: Poly 관련 전체 테스트 + 전체 스위트 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_poly_driver.py tests/simulator/test_poly_sim_server.py -v`
Expected: 전부 PASS

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 5: Task 2 + Task 3 함께 커밋**

```bash
git add app/drivers/poly/poly_commands.py app/drivers/poly/poly_driver.py app/simulator/poly_sim_server.py tests/drivers/test_poly_driver.py
git commit -m "feat: fetch Poly model/uptime via confirmed systemsetting/uptime commands"
```

---

### Task 4: Cisco 드라이버 — 모델명/가동시간 조회

**Files:**
- Modify: `app/drivers/cisco/cisco_commands.py` (끝에 추가)
- Modify: `app/drivers/cisco/cisco_driver.py`
- Test: `tests/drivers/test_cisco_driver.py`

**Interfaces:**
- Consumes: `DeviceStatus.model`/`uptime_seconds` (Task 1).
- Produces: `cisco_commands.STATUS_SYSTEMUNIT_PRODUCT_ID`, `cisco_commands.STATUS_SYSTEMUNIT_UPTIME`;
  `CiscoDriver.get_status()` 결과에 `model`/`uptime_seconds` 포함.

- [ ] **Step 1: cisco_commands.py에 명령 상수 추가**

`app/drivers/cisco/cisco_commands.py` 파일 끝(`bookings_get` 함수 다음)에 추가:
```python
# --- SystemUnit 모델/가동시간 — 확인됨 ---
# 확인: Cisco TelePresence xStatus SystemUnit 상태 트리(SX20 Codec Reference Manual에서 실제
# 명령/응답 예시 확인 — RoomOS 계열 전반에서 일관 유지되는 경로).
#   xStatus SystemUnit ProductId -> *s SystemUnit ProductId: "Cisco TelePresence Codec C90"
STATUS_SYSTEMUNIT_PRODUCT_ID = "xStatus SystemUnit ProductId"
#   xStatus SystemUnit Uptime -> *s SystemUnit Uptime: 597095 (부팅 후 경과 초, 정수)
STATUS_SYSTEMUNIT_UPTIME = "xStatus SystemUnit Uptime"
```

- [ ] **Step 2: 실패하는 통합 테스트 작성**

`tests/drivers/test_cisco_driver.py`의 기존 `sim_and_driver` fixture(1~20행, `CiscoSimServer`와
`CiscoDriver`를 함께 제공)를 그대로 재사용한다. 파일 끝에 추가:
```python
async def test_get_status_includes_model_and_uptime(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.model == "Room Kit Pro (SIM)"
    assert status.uptime_seconds == 7384
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_cisco_driver.py::test_get_status_includes_model_and_uptime -v`
Expected: FAIL — `AttributeError` 또는 `assert None == "Room Kit Pro (SIM)"`

- [ ] **Step 4: cisco_driver.py에 모델 캐싱 + 가동시간 조회 추가**

`app/drivers/cisco/cisco_driver.py`의 `CiscoDriver.__init__` 마지막 줄(`self._buffer = b""`)
다음에 추가:
```python
        self._model: str | None = None
```

`_connect_sync` 메서드의 마지막 3줄(`self._client = client` / `self._channel = channel` /
`self._buffer = b""`) 다음에 추가:
```python
        self._model = self._fetch_model_sync()
```

`_connect_sync` 메서드 다음에 새 메서드 추가:
```python
    def _fetch_model_sync(self) -> str | None:
        try:
            lines = self._call_block_sync(cmd.STATUS_SYSTEMUNIT_PRODUCT_ID)
        except DriverError:
            return None
        for line in lines:
            if line.startswith("*s SystemUnit ProductId:"):
                return line.split(":", 1)[-1].strip().strip('"')
        return None
```

`get_status()`(공개 async 메서드)의 `except DriverError as exc:` 블록에 `model=self._model,`
추가:
```python
    async def get_status(self) -> DeviceStatus:
        now = datetime.now(timezone.utc).isoformat()
        try:
            return await asyncio.to_thread(self._get_status_sync, now)
        except DriverError as exc:
            return DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=now,
                error=str(exc),
                model=self._model,
            )
```

`_get_status_sync` 메서드 전체를 다음으로 교체:
```python
    def _get_status_sync(self, now: str) -> DeviceStatus:
        mute_lines = self._call_block_sync(cmd.STATUS_AUDIO_MUTE)
        muted = any(line.rsplit(":", 1)[-1].strip() == "On" for line in mute_lines if "Audio Microphones Mute:" in line)

        call_lines = self._call_block_sync(cmd.STATUS_CALL)
        in_call = any(line.startswith("*s Call ") for line in call_lines)
        call_peer = None
        for line in call_lines:
            if "RemoteNumber:" in line:
                call_peer = line.split("RemoteNumber:", 1)[-1].strip().strip('"')
                break

        uptime_lines = self._call_block_sync(cmd.STATUS_SYSTEMUNIT_UPTIME)
        uptime_seconds = None
        for line in uptime_lines:
            if line.startswith("*s SystemUnit Uptime:"):
                try:
                    uptime_seconds = int(line.split(":", 1)[-1].strip())
                except ValueError:
                    uptime_seconds = None
                break

        return DeviceStatus(
            online=True,
            in_call=in_call,
            muted=muted,
            call_peer=call_peer,
            last_polled_at=now,
            model=self._model,
            uptime_seconds=uptime_seconds,
        )
```

- [ ] **Step 5: 아직 시뮬레이터가 응답 안 하므로 실패 상태 유지 확인 후 Task 5로 이동**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_cisco_driver.py::test_get_status_includes_model_and_uptime -v`
Expected: FAIL (시뮬레이터 미구현) — Task 5 완료 후 통과 예정, 지금은 커밋하지 않는다.

---

### Task 5: Cisco 시뮬레이터 — 모델/가동시간 응답 추가

**Files:**
- Modify: `app/simulator/cisco_sim_server.py`

**Interfaces:**
- Produces: `CiscoSimServer`가 `xStatus SystemUnit ProductId`/`xStatus SystemUnit Uptime`에 응답
  — Task 4의 테스트가 이 태스크 완료 후 통과해야 한다.

- [ ] **Step 1: CiscoSimState에 모델/가동시간 필드 추가**

`app/simulator/cisco_sim_server.py`의 `CiscoSimState` 데이터클래스(`bookings: list[CiscoBooking] = None`
줄 다음)에 추가:
```python
    model: str = "Room Kit Pro (SIM)"
    uptime_seconds: int = 7384
```

- [ ] **Step 2: handle()에 분기 추가**

`handle()` 메서드에서 `if command.startswith("xCommand Bookings Get"):` 블록 다음(`return None`
이전)에 추가:
```python
        if command == "xStatus SystemUnit ProductId":
            return f'*s SystemUnit ProductId: "{self.state.model}"\r\n** end'
        if command == "xStatus SystemUnit Uptime":
            return f"*s SystemUnit Uptime: {self.state.uptime_seconds}\r\n** end"
```

- [ ] **Step 3: Task 4에서 작성한 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_cisco_driver.py::test_get_status_includes_model_and_uptime -v`
Expected: PASS

- [ ] **Step 4: Cisco 관련 전체 테스트 + 전체 스위트 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/drivers/test_cisco_driver.py tests/simulator/test_cisco_sim_server.py -v`
Expected: 전부 PASS

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 5: Task 4 + Task 5 함께 커밋**

```bash
git add app/drivers/cisco/cisco_commands.py app/drivers/cisco/cisco_driver.py app/simulator/cisco_sim_server.py tests/drivers/test_cisco_driver.py
git commit -m "feat: fetch Cisco model/uptime via confirmed xStatus SystemUnit commands"
```

---

### Task 6: Device 모델에 model/teams_tenant_address 필드 추가

**Files:**
- Modify: `app/models/device.py`
- Modify: `app/core/registry.py`
- Test: `tests/core/test_registry.py`

**Interfaces:**
- Produces: `Device.model: str | None = None`, `Device.teams_tenant_address: str | None = None`;
  `DeviceRegistry.add_device(..., teams_tenant_address: str | None = None)`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/core/test_registry.py`의 `_add_sample` 헬퍼는 그대로 두고(기본값 없이도 동작해야 함),
파일 끝에 추가:
```python
def test_model_defaults_to_none(registry):
    device = _add_sample(registry)
    assert device.model is None


def test_teams_tenant_address_can_be_set(registry):
    device = _add_sample(registry, teams_tenant_address="vc.poscodx.com")
    assert device.teams_tenant_address == "vc.poscodx.com"
    assert registry.get_device(device.id).teams_tenant_address == "vc.poscodx.com"


def test_update_device_sets_model(registry):
    device = _add_sample(registry)
    updated = registry.update_device(device.id, model="RealPresence Group 700")
    assert updated.model == "RealPresence Group 700"
    assert registry.get_device(device.id).model == "RealPresence Group 700"


def test_reads_legacy_device_without_model_field(tmp_path):
    import json

    from app.core import dpapi
    from app.core.registry import SCHEMA_VERSION, _ENTROPY

    path = tmp_path / "devices.enc.json"
    legacy_device = {
        "id": "legacy-1", "name": "구버전 장비", "vendor": "poly", "connection_type": "telnet",
        "host": "127.0.0.1", "port": 2323, "group": "3F", "credential_ref": "ref-1",
        "is_simulated": True,
    }
    payload = json.dumps({"schema_version": SCHEMA_VERSION, "devices": [legacy_device]}, ensure_ascii=False).encode("utf-8")
    path.write_bytes(dpapi.protect(payload, _ENTROPY))

    devices = DeviceRegistry(path).list_devices()
    assert len(devices) == 1
    assert devices[0].model is None
    assert devices[0].teams_tenant_address is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_registry.py -k "model or tenant_address" -v`
Expected: FAIL — `TypeError: add_device() got an unexpected keyword argument 'teams_tenant_address'`
(첫 번째 테스트는 `Device`에 `model` 필드가 없으면 `AttributeError`)

- [ ] **Step 3: Device 모델에 필드 추가**

`app/models/device.py`의 `Device` 데이터클래스(`is_simulated: bool = False` 줄 다음)에 추가:
```python
    model: str | None = None
    teams_tenant_address: str | None = None
```

- [ ] **Step 4: DeviceRegistry.add_device에 파라미터 추가**

`app/core/registry.py`의 `add_device` 메서드 시그니처(`is_simulated: bool = False,` 다음)에
추가:
```python
        teams_tenant_address: str | None = None,
```
같은 메서드 안 `Device(...)` 생성자 호출(`is_simulated=is_simulated,` 다음)에 추가:
```python
            teams_tenant_address=teams_tenant_address,
```
(`model`은 `add_device`의 파라미터로 넣지 않는다 — 항상 `None`으로 시작해 최초 폴링 후
`update_device(device_id, model=...)`로만 채워진다. `update_device`는 이미 `**changes`를
받는 범용 구조라 별도 수정이 필요 없다.)

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_registry.py -v`
Expected: 전부 PASS

- [ ] **Step 6: 전체 스위트 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add app/models/device.py app/core/registry.py tests/core/test_registry.py
git commit -m "feat: add Device.model (auto-discovered) and teams_tenant_address fields"
```

---

### Task 7: AppSettings에 전역 Teams 테넌트 주소 추가

**Files:**
- Modify: `app/core/settings.py`
- Modify: `app/api/routes_settings.py`
- Modify: `app/templates/settings.html`
- Test: `tests/core/test_settings.py`
- Test: `tests/api/test_routes_settings.py`

**Interfaces:**
- Produces: `AppSettings.teams_tenant_address: str = ""`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/core/test_settings.py` 파일 끝에 추가:
```python
def test_teams_tenant_address_defaults_to_empty_string():
    assert AppSettings().teams_tenant_address == ""


def test_save_and_load_roundtrip_includes_teams_tenant_address(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(teams_tenant_address="vc.poscodx.com"))
    assert store.load().teams_tenant_address == "vc.poscodx.com"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_settings.py -k teams_tenant -v`
Expected: FAIL — `TypeError: AppSettings.__init__() got an unexpected keyword argument`

- [ ] **Step 3: AppSettings 필드 추가**

`app/core/settings.py`의 `_DEFAULTS` 딕셔너리(`"open_browser_on_start": True,` 다음)에 추가:
```python
    "teams_tenant_address": "",
```
`AppSettings` 데이터클래스(`open_browser_on_start: bool = True` 다음)에 추가:
```python
    teams_tenant_address: str = ""
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_settings.py -v`
Expected: 전부 PASS

- [ ] **Step 5: API 계층에도 필드 노출 — 실패하는 테스트 작성**

`tests/api/test_routes_settings.py`를 열어 기존 PUT 테스트 패턴을 확인한 뒤, 파일 끝에 추가:
```python
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
```

- [ ] **Step 6: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_routes_settings.py::test_update_settings_persists_teams_tenant_address -v`
Expected: FAIL — 422 (pydantic이 모르는 필드는 무시되지만, `AppSettings(**payload.model_dump())`
호출 시 `teams_tenant_address`가 빠진 채로 저장되어 응답 body에 없거나 빈 문자열로 덮어써짐)

- [ ] **Step 7: SettingsUpdateRequest에 필드 추가**

`app/api/routes_settings.py`의 `SettingsUpdateRequest` 클래스(`open_browser_on_start: bool`
다음)에 추가:
```python
    teams_tenant_address: str = ""
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_routes_settings.py -v`
Expected: 전부 PASS

- [ ] **Step 9: 설정 화면에 입력란 추가 (프론트엔드 — pytest 대상 아님)**

`app/templates/settings.html`의 Alpine `x-data` 객체(`open_browser_on_start: {{ 'true' if
settings.open_browser_on_start else 'false' }},` 다음 줄)에 추가:
```javascript
          teams_tenant_address: '{{ settings.teams_tenant_address }}',
```
`submit()` 메서드의 `body: JSON.stringify({...})` 안, `open_browser_on_start: this.open_browser_on_start,`
다음에 추가:
```javascript
                teams_tenant_address: this.teams_tenant_address,
```
`<form>` 안, "시작 시 자동으로 브라우저 열기" 체크박스 `<div class="field">` 다음에 새 필드
추가:
```html
          <div class="field">
            <label>Teams 테넌트 주소 (CVI, 예: vc.poscodx.com)</label>
            <input type="text" x-model="teams_tenant_address" placeholder="vc.poscodx.com" />
          </div>
```

- [ ] **Step 10: 전체 스위트 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add app/core/settings.py app/api/routes_settings.py app/templates/settings.html tests/core/test_settings.py tests/api/test_routes_settings.py
git commit -m "feat: add global Teams tenant address setting"
```

---

### Task 8: PollingScheduler — 발견된 모델명을 레지스트리에 1회 반영

**Files:**
- Modify: `app/core/polling.py`
- Modify: `app/main.py`
- Test: `tests/core/test_polling.py`

**Interfaces:**
- Consumes: `DeviceStatus.model` (Task 1), `DeviceRegistry.update_device` (Task 6 — 이미 범용).
- Produces: `PollingScheduler(..., on_model_discovered: Callable[[str, str], None] | None = None)`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/core/test_polling.py`의 `FakeDriver.get_status`는 현재 `model`을 채우지 않는다 —
`FakeDriverRegistry.status_for`를 확인하고, `FakeDriver` 클래스는 그대로 둔 채 이 테스트
전용으로 별도 드라이버를 만든다. 파일 끝에 추가:
```python
class _ModelReportingDriver(DeviceDriver):
    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(
            online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now",
            model="RealPresence Group 700",
        )

    async def mute(self, on: bool) -> bool:
        return True

    async def dial(self, address: str) -> bool:
        return True

    async def hangup(self) -> bool:
        return True

    async def reboot(self) -> bool:
        return True

    async def get_calendar_status(self) -> str:
        return "registered"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        return []

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        return True


async def test_on_model_discovered_called_with_device_id_and_model():
    discovered: list[tuple[str, str]] = []
    scheduler = PollingScheduler(
        driver_factory=lambda device_id: _ModelReportingDriver(),
        base_interval=15.0,
        on_model_discovered=lambda device_id, model: discovered.append((device_id, model)),
    )
    await scheduler.add_device("dev-1")
    await scheduler.poll_once("dev-1")
    assert discovered == [("dev-1", "RealPresence Group 700")]


async def test_on_model_discovered_not_called_when_model_is_none(registry):
    called = []
    scheduler = PollingScheduler(
        driver_factory=registry.factory, base_interval=15.0,
        on_model_discovered=lambda device_id, model: called.append((device_id, model)),
    )
    await scheduler.add_device("dev-1")
    await scheduler.poll_once("dev-1")
    assert called == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_polling.py -k on_model_discovered -v`
Expected: FAIL — `TypeError: PollingScheduler.__init__() got an unexpected keyword argument 'on_model_discovered'`

- [ ] **Step 3: PollingScheduler에 콜백 추가**

`app/core/polling.py`의 `PollingScheduler.__init__` 시그니처(`get_device_label:
Callable[[str], str] | None = None,` 다음)에 추가:
```python
        on_model_discovered: Callable[[str, str], None] | None = None,
```
같은 메서드 안, `self._get_device_label = get_device_label or (lambda device_id: device_id)`
다음 줄에 추가:
```python
        self._on_model_discovered = on_model_discovered
```
`_poll_device` 메서드에서 try/except 블록이 끝난 직후, `if status.online:` 줄 바로 앞에 추가:
```python
        if status.model and self._on_model_discovered is not None:
            self._on_model_discovered(device_id, status.model)

```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_polling.py -v`
Expected: 전부 PASS

- [ ] **Step 5: main.py에 실제 콜백 연결 (pytest 대상 아님 — 배선 코드)**

`app/main.py`의 `_device_label` 함수 정의 다음에 추가:
```python
def _on_model_discovered(device_id: str, model: str) -> None:
    """폴링에서 처음 확보한 모델명을 레지스트리에 1회 반영한다 — 이미 같은 값이면 쓰지 않는다
    (매 폴링마다 DPAPI 암호화+파일 쓰기가 일어나는 걸 막기 위함)."""
    device = app.state.registry.get_device(device_id)
    if device is not None and device.model != model:
        app.state.registry.update_device(device_id, model=model)
```
`PollingScheduler(...)` 생성자 호출의 `get_device_label=_device_label,` 다음에 추가:
```python
    on_model_discovered=_on_model_discovered,
```

- [ ] **Step 6: 전체 스위트 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add app/core/polling.py app/main.py tests/core/test_polling.py
git commit -m "feat: persist auto-discovered device model to registry via polling callback"
```

---

### Task 9: 장비 API에 model/teams_tenant_address 노출

**Files:**
- Modify: `app/api/routes_devices.py`
- Test: `tests/api/test_routes_devices.py`

**Interfaces:**
- Consumes: `Device.model`/`teams_tenant_address` (Task 6).
- Produces: `DeviceResponse.model`, `DeviceResponse.teams_tenant_address`;
  `DeviceCreateRequest.teams_tenant_address`, `DeviceUpdateRequest.teams_tenant_address`
  (둘 다 선택 필드, `model`은 요청 스키마에 없음 — 사용자가 직접 입력 불가).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_devices.py`를 열어 기존 등록 테스트 패턴을 확인한 뒤, 파일 끝에 추가:
```python
def test_create_device_with_teams_tenant_address(client):
    resp = client.post(
        "/api/devices",
        json={
            "name": "3층 대회의실", "vendor": "poly", "connection_type": "telnet",
            "host": "127.0.0.1", "port": 2323, "group": "3F",
            "username": "admin", "password": "pw", "is_simulated": True,
            "teams_tenant_address": "vc.poscodx.com",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["teams_tenant_address"] == "vc.poscodx.com"
    assert body["model"] is None


def test_device_response_omits_model_from_create_request_but_reflects_registry_value(client):
    resp = client.post(
        "/api/devices",
        json={
            "name": "5층 소회의실", "vendor": "cisco", "connection_type": "ssh",
            "host": "127.0.0.1", "port": 22, "group": "5F",
            "username": "admin", "password": "pw", "is_simulated": True,
        },
    )
    device_id = resp.json()["id"]
    app.state.registry.update_device(device_id, model="Room Kit Pro")
    resp2 = client.get(f"/api/devices/{device_id}")
    assert resp2.json()["model"] == "Room Kit Pro"
```
(`tests/api/test_routes_devices.py` 1~8행에 `from app.main import app`이 이미 있다 — 추가
import 불필요.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_routes_devices.py -k "teams_tenant_address or omits_model" -v`
Expected: FAIL — 응답에 `teams_tenant_address`/`model` 키가 없어 `KeyError` 또는 `assert None ==`

- [ ] **Step 3: DeviceResponse/CreateRequest/UpdateRequest/​_to_response 수정**

`app/api/routes_devices.py`의 `DeviceCreateRequest` 클래스(`is_simulated: bool = False` 다음)에
추가:
```python
    teams_tenant_address: str | None = None
```
`DeviceUpdateRequest` 클래스(`is_simulated: bool | None = None` 다음)에 추가:
```python
    teams_tenant_address: str | None = None
```
`DeviceResponse` 클래스(`is_simulated: bool` 다음)에 추가:
```python
    model: str | None
    teams_tenant_address: str | None
```
`_to_response` 함수 안(`is_simulated=device.is_simulated,` 다음)에 추가:
```python
        model=device.model,
        teams_tenant_address=device.teams_tenant_address,
```
`create_device` 핸들러의 `registry.add_device(...)` 호출(`is_simulated=payload.is_simulated,`
다음)에 추가:
```python
            teams_tenant_address=payload.teams_tenant_address,
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_routes_devices.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 스위트 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add app/api/routes_devices.py tests/api/test_routes_devices.py
git commit -m "feat: expose device model and teams_tenant_address via devices API"
```

---

### Task 10: POST /api/devices/{id}/direct-dial 엔드포인트

**Files:**
- Modify: `app/api/routes_teams.py`
- Test: `tests/api/test_routes_teams.py`

**Interfaces:**
- Consumes: `Device.teams_tenant_address`, `AppSettings.teams_tenant_address` (Task 6, 7),
  기존 `DeviceDriver.dial(address: str) -> bool`.
- Produces: `POST /{device_id}/direct-dial` — body `{"meeting_id": str}` → `{"ok": bool, "address": str}`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_routes_teams.py`의 `FakeTeamsDriver`에 다이얼 호출을 기록하는 필드를 추가한다.
`__init__` 메서드(`self.joined_entry: CalendarEntry | None = None` 다음)에 추가:
```python
        self.dialed_address: str | None = None
```
`dial` 메서드를 다음으로 교체:
```python
    async def dial(self, address: str) -> bool:
        self.dialed_address = address
        return True
```
`_register` 헬퍼 함수 시그니처를 다음으로 교체(테넌트 주소를 선택적으로 지정할 수 있게):
```python
def _register(client, calendar_supported: bool = True, teams_tenant_address: str | None = None) -> tuple[str, FakeTeamsDriver]:
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
    fake_driver = FakeTeamsDriver(calendar_supported=calendar_supported)
    app.state.scheduler = PollingScheduler(driver_factory=lambda device_id: fake_driver)
    asyncio.run(app.state.scheduler.add_device(device.id))
    return device.id, fake_driver
```
파일 끝에 추가:
```python
def test_direct_dial_uses_device_tenant_override(client):
    device_id, driver = _register(client, teams_tenant_address="room.vc.poscodx.com")
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "address": "1234567890@room.vc.poscodx.com"}
    assert driver.dialed_address == "1234567890@room.vc.poscodx.com"


def test_direct_dial_falls_back_to_global_tenant(client):
    app.state.settings_store.save(
        __import__("app.core.settings", fromlist=["AppSettings"]).AppSettings(teams_tenant_address="vc.poscodx.com")
    )
    app.state.settings = app.state.settings_store.load()
    device_id, _driver = _register(client)
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 200
    assert resp.json()["address"] == "1234567890@vc.poscodx.com"


def test_direct_dial_rejects_non_10_digit_meeting_id(client):
    device_id, _driver = _register(client, teams_tenant_address="vc.poscodx.com")
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "12345"})
    assert resp.status_code == 422


def test_direct_dial_without_any_tenant_configured_returns_422(client):
    from app.core.settings import AppSettings

    app.state.settings = AppSettings(teams_tenant_address="")
    device_id, _driver = _register(client)
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 422


def test_direct_dial_logs_to_history(client):
    device_id, _driver = _register(client, teams_tenant_address="vc.poscodx.com")
    client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].action == "direct_dial"
    assert entries[0].success is True
```
(`test_direct_dial_falls_back_to_global_tenant`의 `__import__` 트릭 대신 파일 상단에
`from app.core.settings import AppSettings`를 추가하고 `AppSettings(teams_tenant_address=...)`로
직접 쓰는 편이 깔끔하다 — import 블록 정리 시 이렇게 바꿀 것.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_routes_teams.py -k direct_dial -v`
Expected: FAIL — 404 (라우트 없음)

- [ ] **Step 3: 엔드포인트 구현**

`app/api/routes_teams.py` 상단 import 블록(`import dataclasses` 다음)에 추가:
```python
import re
```
`class JoinRequest(BaseModel):` 블록 다음에 추가:
```python
class DirectDialRequest(BaseModel):
    meeting_id: str


_MEETING_ID_RE = re.compile(r"^\d{10}$")
```
파일 끝(`join_meeting` 함수 다음)에 추가:
```python
@router.post("/{device_id}/direct-dial")
async def direct_dial(device_id: str, payload: DirectDialRequest, request: Request) -> dict:
    if not _MEETING_ID_RE.match(payload.meeting_id):
        raise HTTPException(status_code=422, detail="회의 ID는 숫자 10자리여야 합니다")

    registry: DeviceRegistry = request.app.state.registry
    device = registry.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    tenant = device.teams_tenant_address or request.app.state.settings.teams_tenant_address
    if not tenant:
        raise HTTPException(status_code=422, detail="Teams 테넌트 주소가 설정되지 않았습니다")

    address = f"{payload.meeting_id}@{tenant}"
    driver = await _get_driver(request, device_id)
    history: ControlHistory = request.app.state.history

    try:
        ok = await driver.dial(address)
    except DriverError as exc:
        history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=ok, detail=address)
    return {"ok": ok, "address": address}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_routes_teams.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 스위트 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add app/api/routes_teams.py tests/api/test_routes_teams.py
git commit -m "feat: add POST /devices/{id}/direct-dial for manual CVI dial fallback"
```

---

### Task 11: CSS — 아이콘 버튼/Teams 서브섹션/토스트 스타일

**Files:**
- Modify: `app/static/css/style.css`

**Interfaces:**
- Produces: `.icon-row`, `.icon-btn`(+ 상태 modifier `.on`, `.muted`, `.spin`), `.teams-box`,
  `.meeting-link`(+ `.tip` 툴팁), `.dial-row` 클래스 — Task 12/13/14가 이 클래스명을 그대로
  마크업/JS에서 사용한다.

- [ ] **Step 1: 스타일 추가**

`app/static/css/style.css` 파일 끝(`.log-fail` 블록 다음)에 추가:
```css
/* 장비 카드 v2 — 아이콘 버튼 (2026-07-30, Teams 수동 다이얼 브레인스토밍) */
.icon-row {
  display: flex;
  gap: 0.6rem;
  margin: 0.6rem 0 0.75rem;
}

.icon-btn {
  position: relative;
  width: 2.2rem;
  height: 2.2rem;
  border-radius: 50%;
  background: var(--color-bg);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
}

.icon-btn:hover {
  filter: brightness(1.1);
}

.icon-btn svg {
  width: 1.05rem;
  height: 1.05rem;
  stroke: var(--color-text);
  fill: none;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.icon-btn.on svg {
  stroke: var(--color-online);
}

.icon-btn.muted svg,
.icon-btn.mic-preview:hover svg,
.icon-btn.hangup-preview.on:hover svg {
  stroke: var(--color-error);
}

.icon-btn.disabled {
  opacity: 0.35;
  cursor: default;
  pointer-events: none;
}

.icon-btn .tip {
  position: absolute;
  bottom: 2.6rem;
  left: 50%;
  transform: translateX(-50%);
  background: #000;
  color: #fff;
  font-size: 0.7rem;
  padding: 0.2rem 0.45rem;
  border-radius: 5px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}

.icon-btn:hover .tip {
  opacity: 0.95;
}

.icon-btn.spin svg {
  animation: icon-spin 0.7s linear;
}

@keyframes icon-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.phone-icon {
  transform: rotate(135deg);
}

.teams-box {
  background: var(--color-bg);
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  margin-top: 0.5rem;
}

.teams-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-call);
  margin-bottom: 0.4rem;
}

.teams-meeting-row {
  font-size: 0.82rem;
  margin-bottom: 0.35rem;
}

.teams-meeting-row .time {
  color: var(--color-text-muted);
  margin-right: 0.4rem;
}

.meeting-link {
  color: var(--color-call);
  text-decoration: none;
  border-bottom: 1px dotted var(--color-call);
  position: relative;
}

.meeting-link .tip {
  position: absolute;
  bottom: 1.3rem;
  left: 0;
  background: #000;
  color: #fff;
  font-size: 0.7rem;
  padding: 0.2rem 0.45rem;
  border-radius: 5px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}

.meeting-link:hover .tip {
  opacity: 0.95;
}

.dial-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.5rem;
}

.dial-row .id-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: 7px;
  overflow: hidden;
  min-width: 0;
}

.dial-row input {
  background: transparent;
  border: none;
  color: var(--color-text);
  font-size: 0.78rem;
  padding: 0.35rem 0.5rem;
  outline: none;
  min-width: 0;
}

.dial-row .id-input {
  width: 4.6rem;
  flex-shrink: 0;
}

.dial-row .at {
  color: var(--color-text-muted);
}

.dial-row .tenant-input {
  flex: 1;
  color: var(--color-call);
  min-width: 0;
}

.dial-row .dial-btn {
  flex-shrink: 0;
  border: none;
  background: var(--color-bg);
  width: 1.9rem;
  height: 1.9rem;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.dial-row .dial-btn svg {
  width: 0.85rem;
  height: 0.85rem;
  stroke: var(--color-call);
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
```

- [ ] **Step 2: 전체 스위트 확인(회귀 없는지) 후 커밋**

CSS만 변경했으므로 pytest 영향 없음. 확인만:
Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS (기존과 동일 — CSS는 pytest 대상 아님)

```bash
git add app/static/css/style.css
git commit -m "style: add icon button / Teams subsection / dial row styles for device card v2"
```

---

### Task 12: 장비 카드 마크업 재구성 (모델/상태/아이콘 버튼/Teams 섹션)

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/api/routes_devices.py` (대시보드 렌더링용 device 딕셔너리는 이미 `_to_response`를
  거치지 않고 `main.py`의 `dashboard()`가 직접 `registry.list_devices()`를 쓰므로 별도 수정
  불필요 — Task 6에서 이미 `Device.model` 필드가 존재하므로 템플릿에서 `d.model`로 바로 접근
  가능함을 확인만 한다)

**Interfaces:**
- Consumes: `d.model`, `d.uptime`(아래에서 `s.uptime_seconds`로 접근), CSS 클래스(Task 11).
- Produces: 카드 마크업에 `data-field="model-text"`, `data-field="reboot-text"`, 아이콘 버튼
  `data-field="mute-icon-btn"`/`"hangup-icon-btn"`/`"refresh-icon-btn"`/`"reboot-icon-btn"`,
  Teams 섹션 `data-field="teams-box"` — Task 14의 dashboard.js가 이 선택자들을 그대로 쓴다.

- [ ] **Step 1: 카드 마크업 교체 (수동 확인 — pytest 대상 아님)**

`app/templates/index.html`의 `{% for item in devices %}` 블록 안 카드 전체(133~160행,
`<div class="card-head">`부터 `</div>`(card-actions 닫는 태그)까지)를 다음으로 교체:
```html
          <div class="card-head">
            <h3>{{ d.name }}{% if d.is_simulated %}<span class="meta" style="margin-left:0.4rem;font-size:0.68rem;">SIM</span>{% endif %}</h3>
            <a href="#" class="meta" style="text-decoration:none;" onclick="openEditDevice('{{ d.id }}'); return false;" title="장비 수정">✎</a>
          </div>
          <div class="meta" data-field="model-text">{{ d.model if d.model else '모델 확인 중...' }} · {{ d.vendor }} · {{ d.connection_type }} · {{ d.host }}</div>
          <div class="status-line">
            <span class="status-dot"></span>
            <span data-field="status-text">
              {% if not s %}미확인{% elif not s.online %}오프라인{% elif s.in_call %}통화중{% else %}대기중{% endif %}
            </span>
            <span data-field="call-subject"></span>
          </div>
          <div class="meta" data-field="last-updated">{{ s.last_polled_at if s else '아직 폴링 안됨' }}</div>
          <div class="meta" data-field="reboot-text" data-uptime-seconds="{{ s.uptime_seconds if s and s.uptime_seconds else '' }}"></div>
          <p class="error-text" data-field="error-text" style="{{ '' if s and s.error else 'display:none' }}">{{ s.error if s and s.error else '' }}</p>

          <div class="icon-row">
            <button
              class="icon-btn mic-preview"
              data-field="mute-icon-btn"
              data-muted="{{ '1' if s and s.muted else '0' }}"
              onclick="toggleMute('{{ d.id }}', this)"
            >
              <svg viewBox="0 0 24 24" data-icon="mic"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/></svg>
              <span class="tip">음소거</span>
            </button>
            <button class="icon-btn hangup-preview" data-field="hangup-icon-btn" onclick="hangupCall('{{ d.id }}', this)">
              <svg class="phone-icon" viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
              <span class="tip">통화 종료</span>
            </button>
            <button class="icon-btn" data-field="refresh-icon-btn" onclick="refreshStatusWithSpin('{{ d.id }}', this)">
              <svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><polyline points="18 3 18 7 14 7"/><polyline points="6 21 6 17 10 17"/></svg>
              <span class="tip">상태 새로고침</span>
            </button>
            <button class="icon-btn" data-field="reboot-icon-btn" onclick="rebootDevice('{{ d.id }}', '{{ d.name }}', this)">
              <svg viewBox="0 0 24 24"><path d="M12 2v6"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>
              <span class="tip">재부팅</span>
            </button>
          </div>

          <div class="teams-box" data-field="teams-box">
            <div class="teams-label" data-field="teams-label">Teams · 불러오는 중...</div>
            <div data-field="teams-meetings"></div>
            <div class="dial-row">
              <div class="id-wrap">
                <input class="id-input" type="text" inputmode="numeric" maxlength="10" placeholder="회의ID" data-field="dial-id-input" />
                <span class="at">@</span>
                <input class="tenant-input" type="text" value="{{ d.teams_tenant_address or '' }}" data-field="dial-tenant-input" />
              </div>
              <button class="dial-btn" title="다이얼 (Enter로도 실행)" data-field="dial-btn" onclick="directDial('{{ d.id }}', this)">
                <svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
              </button>
            </div>
          </div>
```
(기존 `삭제` 버튼은 이 마크업에서 제거됨 — Task 15에서 수정 모달 안으로 이동한다. 기존
`data-online`/`data-in-call` 속성이 있던 최상위 `<div class="device-card ...">` 여는 태그는
그대로 둔다 — 126~132행은 이번 태스크에서 건드리지 않는다.)

- [ ] **Step 2: 전체 스위트로 서버 렌더링 회귀 확인**

`tests/test_dashboard_route.py`의 기존 assert들(`data-device-id`, `"SIM"`, `id="meetings-list"`
등)은 삭제 버튼이나 `card-actions` 클래스를 검사하지 않으므로 수정 없이 그대로 통과해야 한다.

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_route.py -v`
Expected: 전부 PASS

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 3: 커밋**

```bash
git add app/templates/index.html
git commit -m "feat: restructure device card markup (model, icon buttons, Teams subsection)"
```

---

### Task 13: dashboard.js — 오늘 회의 필터링/정렬 공유 로직 + 상단 위젯 갱신

**Files:**
- Modify: `app/static/js/dashboard.js`

**Interfaces:**
- Produces: `async function fetchDeviceMeetings(deviceId)` → `Promise<CalendarEntry[]>`(현재
  시각 이후, 시간순 정렬 완료된 배열), `deviceMeetingsCache`(전역 `Map<deviceId, entries>`,
  Task 14가 통화중 회의 제목 매칭에 사용), `async function joinMeetingLink(deviceId, entry,
  linkEl)`.

- [ ] **Step 1: 공유 조회/필터 함수 추가 (기존 loadUpcomingMeetings 대체)**

`app/static/js/dashboard.js`의 `loadUpcomingMeetings` 함수 전체(242~305행)를 다음으로 교체:
```javascript
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

async function loadUpcomingMeetings() {
  const container = document.getElementById("meetings-list");
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

  if (!container) return;
  container.textContent = "";
  if (rows.length === 0) {
    const p = document.createElement("p");
    p.className = "meta";
    p.textContent = "오늘 예정된 회의가 없습니다.";
    container.appendChild(p);
    return;
  }

  rows.sort((a, b) => a.entry.start_time.localeCompare(b.entry.start_time));

  for (const row of rows) {
    const div = document.createElement("div");
    div.className = "meeting-row";

    const time = document.createElement("span");
    time.textContent = formatMeetingTime(row.entry.start_time);
    div.appendChild(time);

    const name = document.createElement("span");
    name.textContent = row.deviceName;
    div.appendChild(name);

    const subject = document.createElement("span");
    subject.textContent = row.entry.subject;
    div.appendChild(subject);

    if (row.entry.join_uri) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "meeting-link";
      link.textContent = row.entry.join_uri;
      link.title = "참여하기";
      link.addEventListener("click", (ev) => joinMeetingLink(ev, row.deviceId, row.entry));
      div.appendChild(link);
    } else {
      const span = document.createElement("span");
      span.className = "meta";
      span.textContent = "참가 정보 없음";
      div.appendChild(span);
    }

    container.appendChild(div);
  }
}

async function joinMeetingLink(ev, deviceId, entry) {
  ev.preventDefault();
  const ok = await callControl(deviceId, "join", entry);
  if (ok) {
    showToast(`"${entry.subject}" 참가 명령 전송됨`);
    await refreshStatus(deviceId);
  }
}
```

- [ ] **Step 2: 아직 없는 renderCardTeamsSection은 다음 태스크에서 정의 — 임시 no-op 추가**

같은 파일에서 `document.addEventListener("DOMContentLoaded", ...)` 블록 바로 위에 추가(Task 14가
이 함수를 실제 구현으로 교체한다):
```javascript
function renderCardTeamsSection(deviceId, entries) {
  // Task 14에서 실제 렌더링으로 교체됨
}
```

- [ ] **Step 3: 브라우저에서 수동 확인 (pytest 대상 아님)**

Run: `.venv/Scripts/python.exe run.py` (또는 기존 dev 서버 실행 방법 그대로) 후 `/`에 접속해
"오늘의 예정 회의" 위젯이 여전히 렌더링되는지, 콘솔에 JS 에러가 없는지 확인. 시뮬레이터 장비를
하나 등록해 오늘 날짜로 회의가 뜨는 상태를 만들 수 없다면(시드 데이터가 과거 날짜일 수 있음)
최소한 "오늘 예정된 회의가 없습니다" 문구가 에러 없이 뜨는지만 확인.

- [ ] **Step 4: 전체 pytest 스위트 회귀 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS (이 태스크는 JS만 변경 — 회귀 없어야 정상)

```bash
git add app/static/js/dashboard.js
git commit -m "feat: filter/sort today's meetings to future-only, switch join button to link"
```

---

### Task 14: dashboard.js — 카드 아이콘 상태·모델·Teams 섹션·수동 다이얼

**Files:**
- Modify: `app/static/js/dashboard.js`

**Interfaces:**
- Consumes: Task 12 마크업의 `data-field` 선택자, Task 13의 `deviceMeetingsCache`/
  `fetchDeviceMeetings`/`joinMeetingLink`/`formatMeetingTime`.
- Produces: `renderCardTeamsSection(deviceId, entries)`(Task 13의 no-op 교체),
  `directDial(deviceId, btnEl)`, `updateCard()` 확장(모델/재부팅/아이콘 상태 반영).

- [ ] **Step 1: renderCardTeamsSection 실제 구현으로 교체**

Task 13에서 추가한 no-op `renderCardTeamsSection` 함수를 다음으로 교체:
```javascript
function renderCardTeamsSection(deviceId, entries) {
  const card = document.querySelector(`[data-device-id="${deviceId}"]`);
  if (!card) return;

  const label = card.querySelector('[data-field="teams-label"]');
  if (label) {
    label.textContent = entries.length > 0 ? `Teams · 오늘 남은 회의 ${entries.length}건` : "Teams · 오늘 회의 수신 안됨";
  }

  const list = card.querySelector('[data-field="teams-meetings"]');
  if (!list) return;
  list.textContent = "";
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "teams-meeting-row";

    const time = document.createElement("span");
    time.className = "time";
    time.textContent = formatMeetingTime(entry.start_time);
    row.appendChild(time);

    row.appendChild(document.createTextNode(entry.subject + " · "));

    if (entry.join_uri) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "meeting-link";
      link.textContent = entry.join_uri;
      const tip = document.createElement("span");
      tip.className = "tip";
      tip.textContent = "참여하기";
      link.appendChild(tip);
      link.addEventListener("click", (ev) => joinMeetingLink(ev, deviceId, entry));
      row.appendChild(link);
    }

    list.appendChild(row);
  }
}
```

- [ ] **Step 2: 통화중 회의 제목 매칭 헬퍼 추가**

같은 파일에 `renderCardTeamsSection` 다음으로 추가:
```javascript
function findActiveMeetingSubject(deviceId, callPeer) {
  if (!callPeer) return null;
  const entries = deviceMeetingsCache.get(deviceId) || [];
  const match = entries.find((entry) => entry.join_uri === callPeer);
  if (!match) return null;
  return match.subject.length > 20 ? match.subject.slice(0, 20) + "..." : match.subject;
}
```

- [ ] **Step 3: 마지막 재부팅 표시 헬퍼 추가**

```javascript
const REBOOT_WARNING_SECONDS = 30 * 24 * 3600;

function formatLastReboot(uptimeSeconds) {
  if (uptimeSeconds === null || uptimeSeconds === undefined || uptimeSeconds === "") return "";
  const seconds = Number(uptimeSeconds);
  if (Number.isNaN(seconds)) return "";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  let text = "마지막 재부팅: ";
  text += days > 0 ? `${days}일 ${hours}시간 전` : `${hours}시간 전`;
  if (seconds >= REBOOT_WARNING_SECONDS) text += " ⚠";
  return text;
}
```

- [ ] **Step 4: directDial 함수 추가**

```javascript
async function directDial(deviceId, btn) {
  const card = btn.closest(".device-card");
  const idInput = card.querySelector('[data-field="dial-id-input"]');
  const tenantInput = card.querySelector('[data-field="dial-tenant-input"]');
  const meetingId = idInput.value.trim();
  if (!/^\d{10}$/.test(meetingId)) {
    showToast("회의 ID는 숫자 10자리여야 합니다");
    return;
  }
  if (!tenantInput.value.trim()) {
    showToast("Teams 테넌트 주소를 입력하세요");
    return;
  }
  btn.disabled = true;
  const resp = await fetch(`/api/devices/${deviceId}/direct-dial`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ meeting_id: meetingId }),
  });
  btn.disabled = false;
  if (resp.ok) {
    showToast("다이얼 명령 전송됨");
    await refreshStatus(deviceId);
  } else {
    const detail = await resp.json().catch(() => ({}));
    showToast(`다이얼 실패: ${detail.detail || resp.status}`);
  }
}

function wireDialEnterKey() {
  document.querySelectorAll('[data-field="dial-id-input"]').forEach((input) => {
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      const card = input.closest(".device-card");
      const btn = card.querySelector('[data-field="dial-btn"]');
      if (btn) btn.click();
    });
  });
}

async function refreshStatusWithSpin(deviceId, btn) {
  btn.classList.add("spin");
  setTimeout(() => btn.classList.remove("spin"), 700);
  await refreshStatus(deviceId);
}
```

- [ ] **Step 5: updateCard() 확장 — 모델/재부팅/아이콘 상태 반영**

`updateCard()` 함수의 마지막 두 줄(`card.dataset.online = ...` / `card.dataset.inCall = ...`)
앞에 삽입(기존 mute 텍스트/버튼 관련 코드 `muteText`/`muteBtn` 블록은 그대로 두되, `muteBtn`
블록을 아래로 교체):

기존:
```javascript
  const muteBtn = card.querySelector("[data-field=mute-btn]");
  if (muteBtn) {
    muteBtn.dataset.muted = status.muted ? "1" : "0";
    muteBtn.textContent = status.muted ? "🎤 Unmute" : "🔇 Mute";
  }
```
교체 후:
```javascript
  const muteBtn = card.querySelector('[data-field="mute-icon-btn"]');
  if (muteBtn) {
    muteBtn.dataset.muted = status.muted ? "1" : "0";
    muteBtn.classList.toggle("on", status.in_call && !status.muted);
    muteBtn.classList.toggle("muted", status.muted);
    const tip = muteBtn.querySelector(".tip");
    if (tip) tip.textContent = status.muted ? "음소거 해제" : "음소거";
  }

  const hangupBtn = card.querySelector('[data-field="hangup-icon-btn"]');
  if (hangupBtn) {
    hangupBtn.classList.toggle("on", status.in_call);
    hangupBtn.classList.toggle("disabled", !status.in_call);
  }

  const rebootBtn = card.querySelector('[data-field="reboot-icon-btn"]');
  if (rebootBtn) rebootBtn.classList.toggle("on", status.online);

  const modelText = card.querySelector('[data-field="model-text"]');
  if (modelText && status.model) {
    const rest = modelText.textContent.split(" · ").slice(1).join(" · ");
    modelText.textContent = `${status.model} · ${rest}`;
  }

  const rebootText = card.querySelector('[data-field="reboot-text"]');
  if (rebootText) rebootText.textContent = formatLastReboot(status.uptime_seconds);

  const callSubject = card.querySelector('[data-field="call-subject"]');
  if (callSubject) {
    const subject = status.in_call ? findActiveMeetingSubject(deviceId, status.call_peer) : null;
    callSubject.textContent = subject ? ` — "${subject}"` : "";
  }
```

(`toggleMute`/`hangupCall`/`rebootDevice` 함수들의 `btn.dataset.muted`/`btn.disabled` 참조는
`data-field="mute-btn"` → `data-field="mute-icon-btn"`로 선택자만 맞으면 그대로 동작한다 —
`toggleMute` 함수 안 `btn.dataset.muted === "1"` 로직은 변경 불필요, 이미 `onclick="toggleMute('{{
d.id }}', this)"`로 아이콘 버튼 자신이 넘어간다.)

- [ ] **Step 6: 초기 로드 시 재부팅 텍스트 채우기 (WS 갱신 전 서버 렌더 값 사용)**

`document.addEventListener("DOMContentLoaded", ...)` 블록을 다음으로 교체:
```javascript
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

- [ ] **Step 7: 브라우저에서 수동 확인 (pytest 대상 아님)**

Run 개발 서버 후 시뮬레이터 장비 등록 → 카드에 모델명("RealPresence Group 500 (SIM)" 또는
"Room Kit Pro (SIM)")이 표시되는지, 마이크 아이콘 호버 시 빨간 미리보기가 뜨는지(통화중 상태를
만들려면 그룹 다이얼 등으로 in_call을 true로 만들거나 devtools로 WS 메시지를 확인), 새로고침
아이콘 클릭 시 회전 애니메이션이 도는지, 마지막 재부팅 텍스트가 표시되는지 확인.

- [ ] **Step 8: 전체 pytest 스위트 회귀 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add app/static/js/dashboard.js
git commit -m "feat: wire icon button states, model/reboot display, direct-dial to device card"
```

---

### Task 15: 장비 수정 모달 (삭제 버튼 이동 포함)

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/static/js/dashboard.js`

**Interfaces:**
- Produces: `deviceForm()` Alpine 컴포넌트가 등록/수정 겸용으로 동작, `openEditDevice(deviceId)`
  전역 함수(Task 12 카드의 "✎" 링크가 이미 호출하도록 되어 있음).

- [ ] **Step 1: deviceForm()을 등록/수정 겸용으로 확장**

`app/static/js/dashboard.js`의 `deviceForm()` 함수 전체(199~240행)를 다음으로 교체:
```javascript
function deviceForm() {
  return {
    open: false,
    saving: false,
    error: "",
    editingId: null,
    name: "",
    vendor: "poly",
    connection_type: "telnet",
    host: "",
    port: 2323,
    group: "",
    username: "",
    password: "",
    teams_tenant_address: "",
    is_simulated: true,
    openCreate() {
      this.editingId = null;
      this.name = "";
      this.vendor = "poly";
      this.connection_type = "telnet";
      this.host = "";
      this.port = 2323;
      this.group = "";
      this.username = "";
      this.password = "";
      this.teams_tenant_address = "";
      this.is_simulated = true;
      this.error = "";
      this.open = true;
    },
    openEdit(device) {
      this.editingId = device.id;
      this.name = device.name;
      this.vendor = device.vendor;
      this.connection_type = device.connection_type;
      this.host = device.host;
      this.port = device.port;
      this.group = device.group;
      this.username = "";
      this.password = "";
      this.teams_tenant_address = device.teams_tenant_address || "";
      this.is_simulated = device.is_simulated;
      this.error = "";
      this.open = true;
    },
    async submit() {
      this.saving = true;
      this.error = "";
      const body = {
        name: this.name,
        vendor: this.vendor,
        connection_type: this.connection_type,
        host: this.host,
        port: Number(this.port),
        group: this.group,
        teams_tenant_address: this.teams_tenant_address,
        is_simulated: this.is_simulated,
      };
      let resp;
      if (this.editingId) {
        if (this.username) body.username = this.username;
        if (this.password) body.password = this.password;
        resp = await fetch(`/api/devices/${this.editingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        body.username = this.username;
        body.password = this.password;
        resp = await fetch("/api/devices", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }
      this.saving = false;
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        this.error = typeof detail.detail === "string" ? detail.detail : "저장 실패";
        return;
      }
      location.reload();
    },
    async remove() {
      if (!this.editingId) return;
      if (!confirm(`"${this.name}" 장비를 삭제하시겠습니까?`)) return;
      this.saving = true;
      const resp = await fetch(`/api/devices/${this.editingId}`, { method: "DELETE" });
      this.saving = false;
      if (resp.ok) {
        location.reload();
      } else {
        this.error = "삭제 실패";
      }
    },
  };
}

async function openEditDevice(deviceId) {
  const resp = await fetch(`/api/devices/${deviceId}`);
  if (!resp.ok) {
    showToast("장비 정보를 불러오지 못했습니다");
    return;
  }
  const device = await resp.json();
  window.dispatchEvent(new CustomEvent("open-edit-device", { detail: device }));
}
```

`deleteDevice` 함수(187~197행, 기존 카드 삭제 버튼용)는 삭제한다 — 더 이상 카드에서 호출되지
않는다(Task 12에서 이미 카드 마크업에서 삭제 버튼 제거됨).

- [ ] **Step 2: 템플릿에서 모달을 등록/수정 겸용으로 수정**

`app/templates/index.html`의 `<div class="toolbar" x-data="deviceForm()">` 블록(62~119행)을
다음으로 교체:
```html
      <div class="toolbar" x-data="deviceForm()" x-init="window.addEventListener('open-edit-device', (ev) => openEdit(ev.detail))">
        <div></div>
        <button class="btn btn-primary" type="button" @click="openCreate()">+ 장비 등록</button>

        <div class="modal-backdrop" x-show="open" x-cloak @keydown.escape.window="open = false">
          <div class="modal" @click.outside="open = false">
            <h2 x-text="editingId ? '장비 수정' : '장비 등록'"></h2>
            <form @submit.prevent="submit()">
              <div class="field">
                <label>이름</label>
                <input type="text" x-model="name" required />
              </div>
              <div class="field">
                <label>제조사</label>
                <select x-model="vendor">
                  <option value="poly">Poly</option>
                  <option value="cisco">Cisco</option>
                </select>
              </div>
              <div class="field">
                <label>접속방식</label>
                <select x-model="connection_type">
                  <option value="telnet">Telnet</option>
                  <option value="ssh">SSH</option>
                </select>
              </div>
              <div class="field">
                <label>IP/Host</label>
                <input type="text" x-model="host" required />
              </div>
              <div class="field">
                <label>Port</label>
                <input type="number" x-model="port" required />
              </div>
              <div class="field">
                <label>그룹(태그)</label>
                <input type="text" x-model="group" />
              </div>
              <div class="field">
                <label x-text="editingId ? '계정 ID (변경 시에만 입력)' : '계정 ID'"></label>
                <input type="text" x-model="username" />
              </div>
              <div class="field">
                <label x-text="editingId ? '계정 PW (변경 시에만 입력)' : '계정 PW'"></label>
                <input type="password" x-model="password" />
              </div>
              <div class="field">
                <label>Teams 테넌트 주소 (선택, 비워두면 전역 설정 사용)</label>
                <input type="text" x-model="teams_tenant_address" placeholder="vc.poscodx.com" />
              </div>
              <div class="field">
                <label><input type="checkbox" x-model="is_simulated" /> 시뮬레이터 장비로 등록</label>
              </div>
              <p class="error-text" x-show="error" x-text="error"></p>
              <div class="modal-actions">
                <button class="btn btn-danger" type="button" x-show="editingId" @click="remove()">삭제</button>
                <button class="btn" type="button" @click="open = false">취소</button>
                <button class="btn btn-primary" type="submit" :disabled="saving">저장</button>
              </div>
            </form>
          </div>
        </div>
      </div>
```
(모델 필드는 이 폼에 없다 — 자동 조회 값이라 사용자가 입력하지 않는다, Task 6/9에서 이미 결정됨.)

- [ ] **Step 3: 서버 렌더링 회귀 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_route.py -v`
Expected: 전부 PASS

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 4: 브라우저에서 수동 확인 (pytest 대상 아님)**

개발 서버에서 카드의 "✎" 클릭 → 기존 값이 채워진 수정 모달이 뜨는지, 저장하면 PUT이 가는지,
"삭제" 버튼이 모달 안에서 동작하는지, "+ 장비 등록"은 여전히 빈 폼으로 여는지 확인.

- [ ] **Step 5: 커밋**

```bash
git add app/templates/index.html app/static/js/dashboard.js
git commit -m "feat: add device edit modal, move delete button out of card"
```

---

### Task 16: PIPELINE.md QA 체크리스트에 이번 기능 항목 추가

**Files:**
- Modify: `docs/PIPELINE.md`

- [ ] **Step 1: 체크리스트 추가**

`docs/PIPELINE.md`의 "## 3. 수동 QA 체크리스트" 섹션, 기존 체크리스트 마지막 항목
(`- [ ] 앱 재시작 후 등록된 장비 목록/설정이 그대로 유지됨 (\`data/\` 영속성)`) 다음에 추가:
```markdown
- [ ] (2026-07-30 추가) 장비 카드에 모델명이 자동으로 표시됨 (등록 직후엔 "모델 확인 중...",
      첫 폴링 후 실제 모델명으로 바뀜)
- [ ] 마이크 아이콘에 마우스를 올리면(통화 중일 때) 빨간 음소거 미리보기 색이 뜸
- [ ] 새로고침 아이콘 클릭 시 회전 애니메이션이 돌고 멈춤
- [ ] "마지막 재부팅" 텍스트가 표시되고, 임계값(30일) 이상이면 ⚠ 표시됨
- [ ] 오늘 회의 목록이 현재 시각 이후 것만, 시간순으로 표시됨(지난 회의 안 보임)
- [ ] 회의 주소 링크 클릭 시 참가 명령이 가고 결과 토스트가 뜸
- [ ] 회의ID 10자리 입력 후 Enter 또는 다이얼 버튼 클릭 시 수동 다이얼이 실행되고 결과 토스트가 뜸
- [ ] 카드의 "✎"로 장비 수정 모달이 열리고, 기존 값이 채워지며, 삭제 버튼이 모달 안에서 동작함
```

- [ ] **Step 2: 커밋**

```bash
git add docs/PIPELINE.md
git commit -m "docs: add QA checklist items for Teams direct-dial + device card v2"
```

---

## 완료 후

전체 태스크 완료 후 `docs/PIPELINE.md` §4에 따라 버전을 올린다(이번 변경은 새 기능 추가이므로
MINOR — 예: 1.1.0 → 1.2.0), `CHANGELOG.md`에 항목 추가, `git tag v1.2.0`, exe 재빌드. 이 부분은
플랜 범위 밖(PIPELINE.md가 이미 다루는 절차이므로 별도 태스크로 만들지 않음) — 전체 태스크 완료
후 사용자에게 확인받고 진행한다.
