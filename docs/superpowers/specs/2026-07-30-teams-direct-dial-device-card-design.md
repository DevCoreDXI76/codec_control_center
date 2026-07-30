# 설계 — Teams 수동 다이얼 + 장비 카드 v2

- 작성일: 2026-07-30
- 배경: PLAN.md Phase④(Teams 스케줄/발신) 진행 중, 회사가 Teams CVI를 Pexip(OTJ, Azure 호스팅)로
  구성해 운영 중임을 확인. 코덱이 OTJ로 오늘자 회의 일정을 수신하지만, 수신 실패 시를 대비해
  회의 ID + 테넌트 주소로 직접 다이얼하는 수동 경로가 필요하다는 요구에서 시작. 브레인스토밍
  도중 사용자 피드백으로 장비 카드 UI 전반(모델 표시, 상태 표시, 아이콘 버튼, 마지막 재부팅
  등)까지 범위가 확장되어 함께 다룬다.
- **범위 밖(명시적으로 제외, 향후 재검토)**: 실시간 통화 품질(패킷로스/지터/inbound·outbound
  비트레이트) — Poly/Cisco 드라이버에 없는 완전히 새 기능이며, SPEC.md 13.1절에서 이미
  "Cisco 전용 확장 상태는 Poly와 인터페이스 대칭이 깨지고 PRD 핵심 목표에도 없어 지금은
  구현 안 함"이라 결론 낸 사안과 겹침. 별도 브레인스토밍으로 재검토.

## 1. 확인된 명령어 (문서 근거)

| 항목 | Poly (Group Series, Telnet/SSH) | Cisco (RoomOS xAPI) |
|---|---|---|
| 모델명 | `systemsetting get model` → `systemsetting model "RealPresence Group 700"` (Integrator Reference Guide p.352) | `xStatus SystemUnit ProductId` → `*s SystemUnit ProductId: "Cisco TelePresence Codec C90"` (RoomOS/TelePresence API Reference Guide, SystemUnit 상태 트리) |
| 가동시간 | `uptime get` → `1 Hour, 10 Minutes` (사람이 읽는 문자열, p.372) | `xStatus SystemUnit Uptime` → `*s SystemUnit Uptime: 597095` (부팅 후 경과 초, 정수) |
| 오늘 회의 목록 | `calendarmeetings list "today"` — 기존 구현·확정 | `xCommand Bookings List`/`Get` — 명령은 확정, **응답 필드 레이아웃은 미확정**(기존 Known Issue, Phase③ 실장비 검증 대기) |

Poly `uptime get`의 정확한 문자열 형식(일 단위 포함 여부 등)은 장시간 가동된 실장비로 검증 전까지
100% 확정은 아니다 — 파싱 실패 시 원문을 그대로 노출하는 폴백을 둔다(§4 참고).

## 2. 데이터 모델

### Device (`app/models/device.py`, `app/core/registry.py`)
- `model: str | None = None` — 기기가 직접 보고한 모델명. **사용자가 입력하지 않는다**(§3에서
  자동 조회). 등록 직후에는 None이고, 최초 성공적인 접속 이후 채워진다.
- `teams_tenant_address: str | None = None` — 이 장비 전용 CVI 테넌트 주소(선택). None이면
  전역 설정값을 쓴다.
- 두 필드 모두 기존 파일의 `Device(**item)` 생성 방식과 호환(누락 시 기본값 사용) — 스키마
  버전을 올릴 필요 없음.

### AppSettings (`app/core/settings.py`)
- `teams_tenant_address: str = ""` — 전역 기본 CVI 테넌트 주소(예: `vc.poscodx.com`). 설정
  화면에 입력란 추가.

### DeviceStatus (`app/core/driver_base.py`)
```python
@dataclass
class DeviceStatus:
    online: bool
    in_call: bool
    muted: bool
    call_peer: str | None
    last_polled_at: str
    error: str | None = None
    model: str | None = None            # 신규
    uptime_seconds: int | None = None   # 신규
```
`last_reboot_at`(정확한 시각)은 드라이버가 아니라 **표시 계층에서** `now - uptime_seconds`로
계산한다 — 드라이버는 측정값(uptime)만 보고하고, "지금 몇 시인가"는 관심사가 아니다.

## 3. 드라이버 동작

- **모델**: `connect()` 성공 직후 1회만 조회해 드라이버 인스턴스에 캐시(`self._model`). 모델은
  하드웨어가 바뀌지 않는 한 안 변하므로 매 폴링마다 재조회하지 않는다. 조회 실패는 `connect()`
  전체를 실패시키지 않고 `self._model = None`으로 남긴다(경고 로그만).
- **가동시간**: `get_status()`가 호출될 때마다(매 폴링) 함께 조회 — 재부팅되면 즉시 반영되어야
  하는 값이라 mute/통화상태와 동일한 주기로 갱신한다.
- 두 값 다 실패해도(`DriverError`) 기존 폴링 실패 처리와 동일하게 `online=False` 상태로
  떨어질 뿐, 별도 예외 경로를 만들지 않는다.
- Poly `uptime get`의 "1 Hour, 10 Minutes" 형식은 정규식으로 `Day(s)?/Hour(s)?/Minute(s)?`
  단위를 느슨하게 파싱해 초로 환산한다. 파싱 실패 시 `uptime_seconds=None`으로 두고, UI는
  "마지막 재부팅: 확인 필요"처럼 표시(원문은 로그에만 남김 — SPEC.md 12절 로깅 정책과 일관).

## 4. 시뮬레이터 반영

- `poly_sim_server.py`: `systemsetting get model` → `systemsetting model "Group 500 (SIM)"`,
  `uptime get` → 고정값(예: `"2 Hours, 5 Minutes"`) 추가.
- `cisco_sim_server.py`: `xStatus SystemUnit ProductId` → `*s SystemUnit ProductId: "Room Kit Pro (SIM)"`,
  `xStatus SystemUnit Uptime` → 고정 초 값 추가.
- 두 시뮬레이터 다 기존 `handle()` 함수에 분기만 추가하면 되고, 상태 갱신 로직은 필요 없다
  (모델/가동시간은 시뮬레이터 상태와 무관한 고정값).

## 5. 백엔드 — 수동 다이얼 API

`POST /api/devices/{device_id}/direct-dial`, body `{"meeting_id": "1234567890"}`.

- 서버 검증: `meeting_id`가 정확히 숫자 10자리 아니면 422.
- 테넌트 주소 계산: `device.teams_tenant_address` → 없으면 `settings.teams_tenant_address` →
  둘 다 비어있으면 422("Teams 테넌트 주소가 설정되지 않았습니다").
- 최종 주소 `f"{meeting_id}@{tenant}"` 조립 → 기존 `driver.dial(address)` 그대로 재사용
  (드라이버 수정 불필요 — 이미 임의 문자열을 받는 manual dial을 지원).
- 성공/실패 모두 `/logs`에 액션명 `direct_dial`로 기록 (기존 `_run_control` 패턴과 동일하게
  `DriverError`는 502 + 원문 노출, 예상 밖 예외는 트레이스백 로깅 후 502).
- OBTP 회의 링크 클릭으로 참가하는 기존 `POST /{device_id}/join`도 결과를 프론트에서 토스트로
  보여주도록 프론트만 변경(API 자체는 이미 `{"ok": bool}` 반환 중이라 백엔드 변경 없음).

## 6. 프론트엔드

### 6.1 장비 등록/수정 모달
- `모델` 입력란 **제거** — 자동 조회로 대체.
- `Teams 테넌트 주소(선택)` 입력란 추가 — placeholder "비워두면 전역 설정 사용".
- **삭제 버튼을 여기로 이동**(기존 카드에 있던 삭제 버튼 제거, §6.2).

### 6.2 장비 카드
브레인스토밍에서 승인된 최종 시안(스크린샷 기준) 요약:

- 상단: 이름 + (작고 은은한) `SIM` 표기, 모델·연결방식·IP(포트 제외) 한 줄.
- 상태 줄: `🟢 온라인 · 통화 중 — "회의제목..."` 형태로 온라인여부+통화여부+회의제목(있으면,
  20자 내외로 말줄임) 통합 표시. 회의 제목은 `call_peer`를 오늘 OBTP 목록의 `join_uri`와
  대조해 일치하는 항목의 `subject`를 사용 — 일치하는 게 없으면 제목 생략하고 "통화 중"만 표시.
- 메타 줄: `방금 갱신됨 · 마지막 재부팅: 3일 12시간 전` — `uptime_seconds`가 30일(2,592,000초)
  이상이면 `⚠` 표시 추가(재부팅 권장 신호, 임계값은 상수로 분리해 나중에 조정 가능하게).
- 아이콘 버튼 4개(삭제 버튼은 카드에서 제거): 음소거, 통화종료, 새로고침, 재부팅.
  - 원형, 배경은 카드 배경과 통일된 톤(`#26262b`), 아이콘만 보이는 스타일.
  - 마우스오버 시 툴팁(무슨 버튼인지) 표시.
  - 색상 규칙: 기본은 흰색(`#e6e6e6`). **재부팅** 아이콘은 온라인일 때 초록. **음소거·통화종료**
    아이콘은 통화 중일 때 초록, 그 상태에서 마우스를 올리면(또는 음소거가 실제 on 상태이면)
    빨간색으로 전환(다음 클릭 시 어떤 동작이 일어날지 미리보기 역할). **새로고침**은 상태색 없이
    항상 흰색이되, 클릭 시 0.7초 회전 애니메이션 후 정지.
  - 아이콘 모양은 전부 Feather 아이콘 스타일 라인 아이콘(A안) 통일, 통화종료/다이얼 버튼만
    전화 수화기 모양(통화종료는 135도 회전, 다이얼 버튼은 회전 없음)으로 구분.
- Teams 서브섹션(카드 배경보다 한 톤 밝은 사각형으로 구분):
  - 라벨 `TEAMS · 오늘 남은 회의 N건` (또는 회의 0건이면 `오늘 회의 수신 안됨`).
  - 회의 목록: **현재 시각 이후(start_time ≥ now) 회의만, 시간순 전체 표시** — 이미 지난
    회의는 숨김. 이 필터링은 카드별 위젯과 상단 "오늘의 예정 회의" 위젯 양쪽에 동일하게 적용
    (일관성 — 기존 위젯 로직도 함께 수정).
  - 각 회의: `15:30 디자인 리뷰 · 1234567890@vc.poscodx.com`(주소 부분이 링크) — 기존
    "참가▶" 버튼 제거, 주소 텍스트를 클릭 가능한 링크로 대체. 마우스오버 시 "참여하기" 툴팁.
    클릭 시 기존 `join_meeting` 액션 호출(백엔드 API 동일, `/join` 그대로 사용) 후 결과를
    토스트로 표시(성공/실패). 상단 "오늘의 예정 회의" 위젯의 "참가▶" 버튼도 동일한
    링크+툴팁+토스트 패턴으로 통일(일관성 있는 인터랙션을 위한 자연스러운 확장 — 이 부분은
    명시적으로 요청받진 않았으나 두 UI에 서로 다른 참가 방식이 공존하는 걸 막기 위해 포함).
  - 하단 수동 다이얼 입력: `[회의ID(좁게)] @ [테넌트주소(프리필, 수정가능)] [작은 원형 다이얼
    버튼(수화기 아이콘)]`. **Enter 키로도 제출 가능**하고 버튼 클릭으로도 가능(양쪽 다 지원).
    결과는 마찬가지로 토스트 표시.

### 6.3 반응형
- 카드 폭은 `max-width`만 걸고 내부 요소는 %/flex 기반이라 기존 대시보드 그리드의 반응형
  동작을 그대로 물려받는다(이미 있는 CSS 그리드 브레이크포인트 재사용, 새 미디어쿼리 불필요).

## 7. 테스트 계획

- **드라이버 단위 테스트**: Poly/Cisco 시뮬레이터에 모델/가동시간 응답 추가 후, `get_status()`
  결과에 `model`/`uptime_seconds`가 채워지는지, 모델이 재폴링 시 재조회되지 않고 캐시되는지
  (연결이 끊겨 재연결될 때만 재조회) 확인.
- **Poly uptime 파서 단위 테스트**: "1 Hour, 10 Minutes", "45 Minutes", 파싱 불가능한 임의
  문자열(폴백 확인) 각각.
- **`/direct-dial` API 테스트**: 10자리 아닌 ID 거부, 장비별 테넌트 우선순위, 전역 설정
  폴백, 둘 다 없을 때 422, 성공/실패 시 `/logs` 기록 확인.
- **Device/AppSettings 필드 테스트**: `model`/`teams_tenant_address` 필드가 없는 구버전
  JSON을 읽어도 기본값으로 정상 로드되는지(레지스트리/설정 테스트에 케이스 추가).
- **프론트엔드(JS)**: 오늘 회의 시간 필터링·정렬, 아이콘 상태색 전환, 토스트 표시는 pytest
  범위 밖 — PIPELINE.md의 수동 QA 체크리스트에 이번 기능 전용 항목을 추가해 브라우저에서
  직접 확인한다(장비 등록 → 모델 자동 표시 확인, 회의 링크 클릭 → 토스트 확인, 수동 다이얼
  Enter/버튼 둘 다 확인, 재부팅 30일 경과 경고 표시 확인 등).
