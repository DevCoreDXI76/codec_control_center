# SPEC — 영상회의 코덱 통합 제어 앱 기술 명세서

- 문서 버전: v1.0
- 작성일: 2026-07-28
- 연관 문서: `PRD.md`, `PLAN.md`, `UX_SPEC.md`(화면설계서 — 프론트엔드 구현 스택 및 화면별 상세 설계는 해당 문서 참조)

> 본 문서에 등장하는 Poly/Cisco 구체 CLI·xAPI 명령어는 **예시(placeholder)**이며, 실제 구현 시 반드시 Poly Integrator Reference Guide(Group/HDX) 및 Cisco 해당 모델 API Reference Guide(xAPI)를 검색·대조하여 확정한다. 확인되지 않은 명령은 추측하여 구현하지 않는다.

---

## 1. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                  브라우저 (localhost UI)                  │
│           대시보드 / 장비관리 / 제어 / Teams 화면            │
└───────────────────────▲───────────────────────────────────┘
                         │ HTTP / WebSocket
┌───────────────────────┴───────────────────────────────────┐
│                    FastAPI 애플리케이션                     │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────┐ │
│  │ REST API      │  │ WebSocket     │  │ 템플릿 렌더링    │ │
│  │ (registry,    │  │ (실시간 상태   │  │ (Jinja2+HTMX)   │ │
│  │  control)     │  │  브로드캐스트)  │  │                 │ │
│  └───────┬───────┘  └───────┬───────┘  └────────────────┘ │
└──────────┼──────────────────┼──────────────────────────────┘
           │                  │
┌──────────▼──────────────────▼──────────────────────────────┐
│                     서비스/도메인 계층                        │
│  DeviceRegistryService / PollingScheduler(asyncio) /        │
│  CredentialVault(DPAPI) / TeamsMeetingService                │
└──────────────────────────┬──────────────────────────────────┘
                            │ DeviceDriver 인터페이스 (공통)
              ┌─────────────┴─────────────┐
              │                           │
     ┌────────▼────────┐         ┌────────▼────────┐
     │  PolyDriver      │         │  CiscoDriver     │
     │ (Telnet/SSH CLI) │         │ (SSH xAPI)       │
     └────────┬────────┘         └────────┬────────┘
              │                           │
     ┌────────▼────────┐         ┌────────▼────────┐
     │ 실장비 / 시뮬레이터 │         │ 실장비 / 시뮬레이터 │
     └─────────────────┘         └─────────────────┘
```

- UI: FastAPI가 서빙하는 로컬 웹 UI (`http://127.0.0.1:PORT`), 브라우저에서 접속. 화면 구성/와이어프레임/상태 색상 규칙 등 상세 설계는 `UX_SPEC.md` 참조.
- 실시간 상태 갱신은 WebSocket(또는 SSE)로 폴링 결과를 push.
- 상위 로직/UI는 `DeviceDriver` 공통 인터페이스만 알고, 제조사별 구현(Poly/Cisco)을 모른다 (Strategy 패턴).
- 배포: PyInstaller `--onefile`로 단일 EXE 빌드. FastAPI 정적 리소스는 빌드 시 번들.

## 2. 디렉토리 구조 (제안)

```
codec_control_center/
├─ app/
│  ├─ main.py                  # FastAPI 진입점
│  ├─ api/
│  │  ├─ routes_devices.py     # 장비 CRUD API
│  │  ├─ routes_control.py     # 제어 명령 API
│  │  ├─ routes_teams.py       # Teams/OBTP API
│  │  └─ ws_status.py          # WebSocket 상태 브로드캐스트
│  ├─ core/
│  │  ├─ driver_base.py        # DeviceDriver 추상 인터페이스
│  │  ├─ registry.py           # 장비 레지스트리 (저장/조회)
│  │  ├─ polling.py            # asyncio 병렬 폴링 스케줄러
│  │  └─ vault.py              # DPAPI 암호화 저장소
│  ├─ drivers/
│  │  ├─ poly/
│  │  │  ├─ poly_driver.py
│  │  │  └─ poly_commands.py   # CLI 명령 상수 (문서 대조 필요)
│  │  └─ cisco/
│  │     ├─ cisco_driver.py
│  │     └─ cisco_commands.py  # xAPI 명령 상수 (문서 대조 필요)
│  ├─ simulator/
│  │  ├─ poly_sim_server.py    # Poly CLI 모의 서버 (Telnet/SSH)
│  │  └─ cisco_sim_server.py   # Cisco xAPI 모의 서버 (SSH)
│  ├─ models/
│  │  ├─ device.py             # Device, DeviceStatus 데이터모델
│  │  └─ credential.py
│  ├─ templates/                # Jinja2 템플릿 (대시보드/모달/설정 등, 화면설계는 UX_SPEC.md 참조)
│  └─ static/                   # CSS, HTMX/Alpine.js 등 정적 리소스
├─ data/
│  └─ devices.enc.json         # 암호화된 장비 레지스트리(런타임 생성)
├─ tests/
├─ build.spec                  # PyInstaller 설정
└─ requirements.txt
```

## 3. 공통 드라이버 인터페이스

모든 제조사 드라이버는 아래 추상 인터페이스를 구현한다. 상위 로직(폴링 스케줄러, API 라우터)은 이 인터페이스만 호출한다.

```python
# app/core/driver_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ConnectionType(str, Enum):
    SSH = "ssh"
    TELNET = "telnet"


@dataclass
class DeviceStatus:
    online: bool
    in_call: bool
    muted: bool
    call_peer: str | None
    last_polled_at: str
    error: str | None = None


@dataclass
class CalendarEntry:
    subject: str
    start_time: str
    end_time: str
    join_uri: str | None  # SIP/CVI 발신 주소 등


class DeviceDriver(ABC):
    """모든 제조사 드라이버가 구현해야 하는 공통 인터페이스."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def get_status(self) -> DeviceStatus: ...

    @abstractmethod
    async def mute(self, on: bool) -> bool: ...

    @abstractmethod
    async def dial(self, address: str) -> bool: ...

    @abstractmethod
    async def hangup(self) -> bool: ...

    @abstractmethod
    async def reboot(self) -> bool: ...

    @abstractmethod
    async def get_calendar_status(self) -> str:
        """캘린더(Teams) 등록 상태: registered / not_registered / error"""
        ...

    @abstractmethod
    async def get_obtp_entries(self) -> list[CalendarEntry]:
        """예정된 회의(OBTP) 목록 조회."""
        ...

    @abstractmethod
    async def join_meeting(self, entry: CalendarEntry) -> bool:
        """SIP/CVI 주소 발신 또는 장비 자체 Join 명령으로 참가."""
        ...
```

## 4. Poly 드라이버 스펙 (Group/HDX, Telnet/SSH CLI)

- 접속: `telnetlib3`(Telnet) 또는 `paramiko`(SSH), 장비 설정에 따라 선택.
- 근거 문서: Poly Integrator Reference Guide (Group Series / HDX Series).
- 구현 원칙: 아래는 **명령 카테고리 목록**이며, 실제 명령 문자열/응답 포맷은 Phase ①에서 문서를 검색해 `poly_commands.py`에 상수로 확정한다.

| 기능 | 명령 카테고리 (예시, 문서 대조 필요) | 비고 |
|---|---|---|
| 상태 조회 | 시스템/통화 상태 조회 명령 | 응답 파싱 로직 별도 구현 |
| Mute | 마이크 음소거 토글 명령 | on/off 별도 명령 존재 가능 |
| Dial | 발신 명령 (주소 파라미터) | H.323/SIP 프로토콜 지정 필요 여부 확인 |
| Hangup | 통화 종료 명령 | |
| Reboot | 시스템 재시작 명령 | 재부팅 후 재연결 로직 필요 |
| 캘린더 상태 | 캘린더/Exchange 연동 상태 조회 명령 | 모델별 지원 여부 상이할 수 있음 |
| OBTP 조회 | 예정 회의 목록 조회 명령 | |

- 파싱: CLI 응답은 텍스트 기반(줄바꿈 구분)이므로 정규식/토큰 파서 작성. 명령 실행 → raw 응답 캡처 → `DeviceStatus`/`CalendarEntry`로 매핑.
- 세션: 명령마다 재접속하지 않고 세션을 유지하되, 유휴 시간 초과 시 재연결 (보안 오탐 회피를 위해 재연결 빈도 최소화).

## 5. Cisco 드라이버 스펙 (SSH xAPI: xStatus/xCommand)

- 접속: `paramiko` SSH, xAPI 텍스트/XML 모드 사용.
- 근거 문서: 대상 Cisco 모델의 API Reference Guide (모델 미확정 — Phase ⑤ 착수 전 확정 필요, PRD 오픈 이슈 참조).
- 구현 원칙: 아래는 **명령 카테고리 목록**이며, 실제 `xStatus`/`xCommand` 경로와 파라미터는 Phase ⑤에서 문서 대조 후 `cisco_commands.py`에 확정한다.

| 기능 | xAPI 카테고리 (예시, 문서 대조 필요) | 비고 |
|---|---|---|
| 상태 조회 | `xStatus Call`, `xStatus Audio Microphones Mute` 등 | 정확한 경로는 모델별 문서 확인 |
| Mute | `xCommand Audio Microphones Mute/Unmute` | |
| Dial | `xCommand Dial Number: <address>` | Protocol 파라미터(SIP 등) 확인 |
| Hangup | `xCommand Call Disconnect` | |
| Reboot | `xCommand SystemUnit Boot` | Action 파라미터 확인 |
| 캘린더 상태 | `xStatus Conference/Bookings` 관련 | Webex/Teams 연동 상태 조회 방식 확인 |
| OBTP 조회 | `xCommand Bookings List` 등 | |

- 응답 포맷: xAPI 텍스트 모드는 계층형 텍스트 응답. 파서는 들여쓰기/키-값 구조를 트리로 변환 후 필요한 필드 추출.

## 6. 데이터 모델

### 6.1 장비 레지스트리 (암호화 저장)

```json
{
  "devices": [
    {
      "id": "uuid",
      "name": "3층 대회의실",
      "vendor": "poly | cisco",
      "connection_type": "ssh | telnet",
      "host": "10.0.0.10",
      "port": 22,
      "group": "3F",
      "credential_ref": "encrypted-blob-id",
      "is_simulated": false
    }
  ]
}
```

- 민감정보(ID/PW)는 위 JSON에 직접 저장하지 않고, `CredentialVault`가 Windows DPAPI(`CryptProtectData`)로 암호화한 blob을 별도 저장, `credential_ref`로만 참조.
- 복호화는 런타임에 필요한 순간에만 메모리 상에서 수행, 로그에 평문 노출 금지.

### 6.2 상태 캐시 (메모리, 폴링 결과)

- `DeviceStatus` 객체를 장비 ID 기준 dict로 인메모리 캐시, WebSocket으로 변경분만 브로드캐스트.
- 영속 저장이 필요하면(이력 조회 등) SQLite 사용 검토 (Phase ⑥ 편의 기능에서 결정).

## 7. API 설계 (FastAPI)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/devices` | 등록 장비 목록 |
| POST | `/api/devices` | 장비 등록 |
| PUT | `/api/devices/{id}` | 장비 수정 |
| DELETE | `/api/devices/{id}` | 장비 삭제 |
| GET | `/api/devices/{id}/status` | 단일 장비 상태 조회 |
| POST | `/api/devices/{id}/mute` | mute/unmute (`{"on": true}`) |
| POST | `/api/devices/{id}/dial` | 발신 (`{"address": "..."}`) |
| POST | `/api/devices/{id}/hangup` | 통화 종료 |
| POST | `/api/devices/{id}/reboot` | 재부팅 (확인 필요, 프론트에서 confirm) |
| GET | `/api/devices/{id}/calendar` | 캘린더 등록 상태 |
| GET | `/api/devices/{id}/obtp` | 예정 회의(OBTP) 목록 |
| POST | `/api/devices/{id}/join` | 예정 회의 참가 |
| WS | `/ws/status` | 전체 장비 상태 실시간 브로드캐스트 |

- 인증: 로컬 단일 사용자 전제이므로 기본은 localhost 바인딩으로 접근 제한. 필요 시 간단한 로컬 토큰 인증 추가 검토(Phase ⑥).

## 8. 폴링 설계 (asyncio, 20대 이상 동시 처리)

- `asyncio.gather` + `Semaphore`로 동시 접속 수 제한 (보안 장비 오탐 방지를 위해 무제한 병렬 금지).
- 기본 폴링 주기: 10~30초 범위에서 시작(추후 보안팀/현장 협의로 조정 가능하도록 설정값으로 노출).
- 지수 백오프: 연속 실패 장비는 폴링 주기를 점진적으로 늘려(예: 30s → 60s → 120s) 불필요한 재시도로 인한 스캔성 트래픽을 줄인다.
- 세션 재사용: 매 폴링마다 새 SSH/Telnet 세션을 맺지 않고, 가능하면 연결을 유지한 채 명령만 반복 (연결/해제 빈도를 낮춰 IDS/IPS 탐지 패턴 회피).
- 타임아웃: 장비별 명령 타임아웃(예: 5~10초) 설정, 무응답 시 오프라인으로 표시.

## 9. 보안 설계

- **저장**: 계정정보는 DPAPI(`win32crypt.CryptProtectData`, 현재 사용자 컨텍스트)로 암호화 후 로컬 파일 저장. 앱 재시작/OS 재부팅 후에도 동일 사용자 계정에서만 복호화 가능해야 한다.
- **메모리**: 복호화된 평문 자격증명은 필요한 함수 호출 스코프 내에서만 유지, 전역 변수/로그에 남기지 않는다.
- **네트워크**: 폴링/제어 트래픽은 사내망 내부로 한정, 외부망에서는 시뮬레이터만 사용.
- **오탐 회피**: 위 8절의 폴링 주기·세션 재사용·백오프 정책을 통해 보안 스캐너가 이상 스캔으로 오인하지 않도록 설계.

## 10. 시뮬레이터 설계

- `poly_sim_server.py`: Telnet/SSH 서버를 로컬(예: `127.0.0.1:2323`)에 띄우고, Poly CLI 명령 문자열을 받아 문서 기준 형식의 응답을 반환하는 상태 기반(state machine) 모의 장비.
- `cisco_sim_server.py`: SSH 서버(예: `127.0.0.1:2222`)에서 xAPI 텍스트 명령을 받아 계층형 텍스트 응답을 반환.
- 각 시뮬레이터는 통화중/음소거/캘린더 등록 등 상태를 내부에 유지하며, 제어 명령에 따라 상태가 실제로 변하도록 구현하여 드라이버 로직을 실제 장비 없이도 end-to-end 검증 가능하게 한다.
- `is_simulated: true`인 장비는 UI에서 배지 등으로 구분 표시.

## 11. 배포 (PyInstaller)

- 빌드 대상: `app/main.py` 진입점, `--onefile --noconsole`(또는 콘솔 유지 옵션 선택), 템플릿/정적 리소스(`app/templates/`, `app/static/`)는 `--add-data`로 번들.
- 실행 시 로컬 포트(예: 8765)로 FastAPI 서버 구동 후 기본 브라우저 자동 오픈.
- `data/` 폴더(암호화된 레지스트리)는 실행 파일과 같은 경로 또는 `%APPDATA%` 하위에 생성.
- **장비 추가/IP 변경/이름 변경 등은 재배포 대상이 아니다.** 장비 등록 정보는 exe(코드)와 분리된 `data/` 폴더에 저장되며, 앱 내 UI(장비 등록/수정 화면, `UX_SPEC.md` 4.3절)에서 사용자가 직접 추가·수정·삭제한다. 변경 즉시 로컬 파일에 반영되고 서버(=exe) 재배포는 필요 없다.
- 재배포(새 exe 배포)가 필요한 경우는 **앱 자체의 기능 추가/버그 수정 등 코드 변경 시**로 한정한다. 이때도 `data/` 경로(실행 파일과 동일 폴더 또는 `%APPDATA%`)를 유지한 채 exe만 교체하면 기존에 등록된 장비 목록/자격증명이 그대로 유지된다 — 배포 가이드에 "설치 폴더의 `data/`는 삭제하지 말 것"을 명시한다.

### 11.1 exe 파일 전달 방법 — Gmail 첨부 사용 금지

**Gmail로 `CodecControlCenter.exe`를 첨부 전송하지 말 것.** 2026-07-29 실제로 시도했다가 차단됨 —
확인 결과 최근 정책 변경이 아니라 Gmail의 오래된 고정 정책이다: `.exe`를 포함한 실행파일류는
**내용과 무관하게 확장자만으로 무조건 차단**한다(zip으로 감싸도 내부 파일 목록을 봐서 동일하게
차단, 비밀번호 zip도 파일명 목록이 노출되는 경우가 많아 대부분 차단됨). 우회를 시도하지 말고
처음부터 사내 승인된 파일 전송 경로(사내 드라이브/파일 서버 등)를 사용한다 — 어차피 VDI 반입
자체도 보안팀 승인 절차를 거쳐야 하므로 이메일 전송을 시도할 이유가 없다.

**빌드된 exe 자체의 무결성은 확인됨** (2026-07-29, `dist/CodecControlCenter.exe`, 약 20MB):
- Windows Defender 전체 스캔: 위협 없음(threats found: 0)
- 디지털 서명: 없음(`NotSigned`) — 유료 코드서명 인증서 미보유로 인한 정상 상태. 최초 실행 시
  Windows SmartScreen이 "알 수 없는 게시자" 경고를 띄울 수 있으나 악성코드 경고가 아니다.
- 구성: 자체 작성 코드 + FastAPI/uvicorn/paramiko/pywin32/telnetlib3 등 공식 PyPI 패키지만
  사용, 난독화 없음, 외부 네트워크 호출 없음(127.0.0.1 로컬 바인딩 + 등록한 장비로만 통신).
- SHA256: `EF79E5F4BEC199B7B5E66E23E40F7BDAFEB119C69CCCA64B5210ABD464E81772`
  (재빌드 시 값이 달라지므로, 배포할 exe마다 새로 계산해 무결성 확인 근거로 남길 것.)

## 12. 오류 처리 & 로깅

- 드라이버 계층 예외는 공통 `DriverError`(연결 실패/인증 실패/명령 실패/타임아웃 세분화)로 표준화하여 상위 계층에 전달.
- 로그에는 IP/장비명 등은 남기되, 계정정보(ID/PW)는 어떤 경우에도 기록하지 않는다.
- UI에는 사용자 친화적 오류 메시지(예: "접속 실패 — 인증정보 확인 필요")로 변환하여 노출.
- Cisco 제어 명령(mute/dial/hangup)은 명령 실패 시 조용히 `False`를 반환하지 않고
  `DriverCommandError`에 장비 응답 원문을 담아 올린다 — 정확한 오류 코드 체계는
  공식 문서에 없지만, 원문을 그대로 `/logs`·UI 토스트에 노출하면 권한 부족/미지원
  명령 등 실패 원인을 사용자가 확인할 수 있다 (`cisco_driver._check_result_ok`).
- Cisco 계정은 최소 **USER** 역할이 있어야 mute/dial/reboot이 전부 동작한다
  (RoomOS 11 API Reference Guide 확인 — 상세는 `cisco_commands.py` 상단 주석).
  장비 등록 시 계정 권한 부족으로 인한 실패를 예방하려면 이 요구사항을 사용자에게 안내할 것.

## 13. Phase⑤ 검토 사항 (Cisco 드라이버 확장)

대상 모델 확정(2026-07-29: Room Kit/Room Kit Pro/Room Kit EQ/Room Bar/Room Bar Pro) 이후
PLAN.md Phase⑤ 체크리스트 중 "검토" 성격의 두 항목을 아래와 같이 정리한다.

### 13.1 추가 상태 정보 (카메라/화면공유/참가자 목록 등) — 검토 결과: 지금은 구현하지 않음

RoomOS 11 API Reference Guide에는 `xStatus Cameras Camera [n] ...`,
`xStatus Conference Presentation LocalInstance [n] ...`,
`xStatus Conference Call [n] Capabilities ...` 등 매우 세분화된 상태 경로가 존재하며,
확장 자체는 기술적으로 가능하다.

다만 다음 이유로 이번 단계에서는 구현하지 않기로 한다:
- `DeviceDriver`는 Poly/Cisco 공통 인터페이스다. Cisco 전용 필드를 `DeviceStatus`에
  추가하면 Poly 쪽 동등 기능 확인 전까지 인터페이스 대칭이 깨진다.
- PRD 핵심 목표(등록·상태감시·mute/dial/hangup/reboot·Teams 캘린더)에 카메라/화면공유/
  참가자 수 추적은 명시적으로 포함되어 있지 않다 — 실사용 니즈가 확인되면 그때
  `DeviceStatus`를 확장하거나 별도 엔드포인트(`/api/devices/{id}/details` 등)로 분리한다.
- 확인된 xStatus 경로들은 문서·주석으로 남겨두었으므로, 필요해지면 바로 착수 가능하다.

### 13.2 xAPI 이벤트 구독(Feedback Registration) — 검토 결과: 폴링 유지

RoomOS는 `xFeedback register <path>` 로 상태 변경을 push 받을 수 있다(예:
`xFeedback register /Status/Audio`). 폴링 대신 이걸 쓰면 이론적으로 지연 없이 상태를
받을 수 있고 불필요한 조회 트래픽도 줄어든다.

그럼에도 지금은 전환하지 않고 현재의 폴링(`PollingScheduler`, Semaphore 동시성 제한 +
지수 백오프) 구조를 유지하기로 한다:
- SPEC.md 8/9절의 핵심 설계 목표가 "보안 장비(IDS/IPS) 오탐 회피를 위한 보수적 폴링"이다.
  Feedback 구독은 세션을 계속 열어두는 push 방식이라, 이 목표와 상충하지는 않지만
  검증되지 않은 새로운 트래픽 패턴을 만든다 — Phase③ 보안팀 협의 없이 먼저 바꾸지 않는다.
- Poly에는 대응하는 confirmed 구독 메커니즘이 없다(Phase①에서 폴링 기반으로만 확정).
  Cisco만 push로 바꾸면 드라이버 계층의 일관성이 깨진다.
- 장비 수(PRD 기준 20대+) 규모에서 현재 폴링 주기(기본 15초, 설정 가능)로 이미
  "5초 이내 확인" 목표(PRD 8절)를 만족하므로, 지금 시점에 효율 개선이 급하지 않다.

재검토 조건: 장비 수가 크게 늘어나 폴링 트래픽이 부담되거나, Poly 쪽에서도 동등한
push 메커니즘이 확인되어 드라이버 계층을 일관되게 바꿀 수 있을 때.
