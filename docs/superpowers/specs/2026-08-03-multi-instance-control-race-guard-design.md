# 설계 — 다중 PC 인스턴스 제어 명령 충돌 방지(재부팅/다이얼/참가 실행 직전 fresh 재확인)

- 작성일: 2026-08-03
- 배경: 직원 배포 이후 여러 PC가 각자 독립 프로세스로 같은 코덱 장비를 개별 폴링·제어하는
  상황이 실제로 발생 중임을 확인. `docs/SCHEDULE.md` §4의 보안팀 협의("내부망이라 문제없음")는
  단일 인스턴스 기준 답변이었고, 네트워크 트래픽량 자체는 재확인 결과 문제 없음(보안팀 회신).
  다만 이번 검토 과정에서 보안팀 질문 범위 밖의 새 리스크가 드러났다 — v1.5.19에서 추가한
  "통화 중 중복 참가 방지" 가드(`dashboard.js`)는 **그 브라우저 인스턴스가 마지막으로 폴링한
  캐시 상태**에만 근거하는데, 여러 PC가 각자 독립적으로 폴링(기본 15초, 백오프 시 최대 120초
  주기)하므로 한 PC의 조작을 다른 PC가 알아채기까지 그 폴링 주기만큼 지연이 생긴다. 이 지연
  구간에 다른 PC에서 같은 장비를 조작하면 v1.5.19가 막으려 했던 것과 같은 계열의 안전 사고
  (중복 참가·하울링, 통화 중 오재부팅)가 재현될 수 있다.
- **범위 밖(명시적으로 제외)**: PC 간 공유 락/락 서버 등 새 공유 인프라 도입 — 이번 설계로
  레이스 윈도우를 15~120초에서 명령 왕복시간(1초 미만) 수준으로 줄이는 것으로 충분하다고
  판단(YAGNI). 필요성이 실제로 확인되면(§6 로그로 발동 빈도 추적) 별도 브레인스토밍으로
  재검토한다. 세션 한도(Cisco 계정당 20개 등) 대응은 이 설계의 대상이 아니다(운영 정책으로
  이미 별도 처리).

## 1. 핵심 아이디어

모든 PC 인스턴스는 결국 같은 물리 장비에 직접 SSH/Telnet으로 붙어 실제 장비 상태를 읽는다 —
즉 장비 자체가 이미 모든 인스턴스가 공유하는 유일한 진실 소스다. 프런트엔드가 자기 인스턴스의
"마지막 폴링 캐시"를 믿는 대신, **위험한 명령(재부팅·다이얼·참가)을 실제로 장비에 보내기
바로 직전에 그 장비에 fresh하게 다시 물어보고** 통화 중이면 명령을 보내지 않고 차단한다.
새 공유 인프라(락 파일, 락 서버, 중앙 DB) 없이도 다중 PC 문제 대부분이 해결된다 — 별도
아키텍처 변경이 아니라 기존 `PollingScheduler.run_with_driver()`가 이미 제공하는 장비별
`asyncio.Lock` 안에서 "확인 → 실행"을 하나로 묶기만 하면 된다.

## 2. 적용 범위

| 명령 | 적용 여부 | 이유 |
|---|---|---|
| `POST /api/devices/{id}/reboot` | ✅ 적용, **통화 중이면 차단**(경고 후 허용 아님) | 실제 유지보수 목적 재부팅이라도 통화 중이면 먼저 종료를 요구하는 쪽이 더 안전하다고 판단(사용자 확정) |
| `POST /api/devices/{id}/direct-dial` (`routes_teams.py`) | ✅ 적용, 차단 | 대시보드 UI가 실제로 쓰는 수동 다이얼 경로(E1 테스트케이스) |
| `POST /api/devices/{id}/join` (`routes_teams.py`) | ✅ 적용, 차단 | Teams 회의 링크 참가 — v1.5.19 하울링 사고의 원인 경로 |
| `POST /api/devices/{id}/dial` (`routes_control.py`) | ✅ 적용, 차단 | 대시보드 UI는 현재 이 경로를 호출하지 않지만(direct-dial로 대체됨), 같은 `driver.dial()`을 호출하는 공개 API라 방어적으로 동일 가드 적용 |
| `hangup`, `mute`/`unmute` | ❌ 적용 안 함 | 중복 실행돼도 위험하지 않음(종료 명령은 이미 끝난 통화에 보내도 안전, mute 토글은 상태 반전일 뿐 하울링/오재부팅 같은 사고를 유발하지 않음) — YAGNI |

## 3. 구현

### 3.1 공용 가드 헬퍼
새 함수 하나를 추가(위치: `app/api/routes_control.py`, 두 라우트 모듈에서 함께 import):

```python
async def _reject_if_in_call(driver: DeviceDriver) -> None:
    """위험한 명령을 실제로 보내기 직전, 그 순간 장비의 실제 통화 상태를 재확인한다.
    폴링 캐시(최대 120초 지연)를 믿지 않고 매번 fresh하게 물어본다 — 여러 PC가 각자
    독립적으로 이 장비를 조작할 수 있어, 캐시만 믿으면 다른 PC가 방금 시작한 통화를
    놓치고 중복 참가/오재부팅으로 이어질 수 있다(2026-08 다중 PC 배포 이후 확인된 리스크)."""
    status = await driver.get_status()
    if status.in_call:
        raise DriverCommandError("다른 위치에서 이미 통화 중입니다 — 종료 후 다시 시도해주세요")
```

### 3.2 `routes_control.py`
`_run_control()`에 선택적 `guard: Callable[[DeviceDriver], Awaitable[None]] | None = None` 파라미터를
추가. 지정되면 `operation` 실행 전에 같은 락 안에서 `await guard(driver)`를 먼저 호출한다.

```python
async def _run_control(
    request: Request,
    device_id: str,
    action_name: str,
    action: Callable[[DeviceDriver], Awaitable[bool]],
    detail: str | None = None,
    guard: Callable[[DeviceDriver], Awaitable[None]] | None = None,
) -> dict:
    ...
    async def guarded(driver: DeviceDriver) -> bool:
        if guard is not None:
            await guard(driver)
        return await action(driver)

    try:
        ok = await scheduler.run_with_driver(device_id, guarded)
    ...
```

`reboot()`, `dial()` 라우트에 `guard=_reject_if_in_call` 전달.

### 3.3 `routes_teams.py`
`join_meeting()`, `direct_dial()`도 같은 패턴 — `run_with_driver(device_id, ...)`에 넘기는
람다를 "먼저 `_reject_if_in_call(driver)` 호출 → 이후 원래 동작" 형태로 감싼다. 로직은
`routes_control.py`의 `_reject_if_in_call`을 그대로 import해서 재사용(중복 작성 금지).

### 3.4 에러 처리
- `_reject_if_in_call`이 던지는 예외는 기존 `DriverCommandError`(→ `DriverError` 서브클래스)이므로
  각 라우트의 기존 `except DriverError` 경로를 그대로 탄다.
- 다만 이 경우는 실제 장비 오류가 아니라 "정책적으로 막힘"이므로, 프런트엔드가 다른 실패와
  구분해 보여줄 수 있도록 상태 코드를 502 대신 **409 Conflict**로 분리한다(라우트에서
  `DriverCommandError`의 메시지가 이 가드에서 온 것인지 구분할 별도 예외 서브클래스
  `DriverConflictError`를 `driver_base.py`에 추가하고, 각 라우트의 except 블록에서
  `DriverConflictError`를 `DriverError`보다 먼저 잡아 409로 응답).
- `history.log()`에 `success=False, detail="다른 위치에서 이미 통화 중"`으로 기록 — 이 가드가
  실제로 몇 번 발동하는지가 다중 PC 충돌이 실제로 얼마나 자주 일어나는지 확인할 유일한
  단서이므로 반드시 로그에 남긴다.
- 프런트엔드(`dashboard.js`)는 409 응답을 받으면 기존 "이미 통화 중입니다" 토스트와 동일한
  문구를 보여주되, 이번엔 서버가 실시간으로 확인한 결과라는 점에서 기존 프런트엔드 캐시 체크
  (`card.dataset.inCall`)는 그대로 1차 필터로 유지한다(불필요한 요청을 줄이는 용도) — 서버
  가드가 최종 방어선이라는 점만 명확히 한다.

## 4. 데이터 흐름

1. 클라이언트 → `POST /api/devices/{id}/{reboot|direct-dial|join|dial}`
2. 서버가 `run_with_driver(device_id, guarded_action)` 호출 → 장비별 `asyncio.Lock` 획득(이미
   존재하는 동작, 이 프로세스 안에서는 여기서부터 끝까지 이 장비에 대한 다른 동작과 겹치지 않음)
3. 락 안에서 `driver.get_status()`로 그 순간 실제 장비 상태를 재조회(추가 명령 1~3개, §추정
   수신 바이트는 대기중 기준 60~90B 수준으로 무시 가능)
4. `in_call=True`면 실제 명령(reboot/dial/join)을 보내지 않고 `DriverConflictError` 발생 → 409
5. `in_call=False`면 원래 하려던 동작을 그대로 실행

## 5. 테스트 계획

- `tests/api/test_routes_control.py`: 드라이버 스텁의 `get_status()`가 `in_call=True`를 반환하도록
  설정 → `reboot`/`dial` 호출 시 409 반환 + 스텁의 `reboot()`/`dial()`이 호출되지 않았음을 assert.
  `in_call=False`일 때는 정상 진행(기존 테스트가 이미 커버 — 회귀 없는지만 확인).
- `tests/api/test_routes_teams.py`: `join`/`direct-dial`에 동일한 패턴의 테스트 추가.
- `driver_base.py`에 추가하는 `DriverConflictError`가 `DriverError`의 서브클래스인지, 기존
  `except DriverError`로도 잡히는지(하위 호환) 확인하는 단위 테스트 1개.
- 수동 QA(PIPELINE.md 체크리스트에 항목 추가): 통화 중인 장비를 대상으로 다른 브라우저 탭/PC
  에서 재부팅·다이얼·참가를 시도해 "이미 통화 중입니다" 응답과 `/logs` 기록을 실제로 확인.

## 6. 잔여 리스크

"확인 → 실행" 사이의 밀리초 단위 완전 동시 요청 경합(두 PC가 정말 같은 순간에 §4의 3번
단계를 동시에 통과)은 이론상 남는다. 목표는 레이스 윈도우를 15~120초에서 명령 왕복시간(1초
미만) 수준으로 줄이는 것이며, 이 잔여 리스크는 현재 규모(사내 소수 인원)에서 실무적으로
수용 가능하다고 판단한다. §3.4의 로그로 실제 발동 빈도를 추적해, 문제가 실제로 반복되면
§(범위 밖)의 공유 락 방식을 재검토한다.
