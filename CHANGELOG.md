# Changelog

이 프로젝트의 모든 주요 변경사항을 이 파일에 기록한다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따른다.
언제 버전을 올리고 태그를 남기는지 등 절차 전체는 `docs/PIPELINE.md` 참조.

## [Unreleased]

## [1.5.1] - 2026-07-31

로컬 포트(8765) 충돌 시 자동 재시도 (`docs/BACKLOG.md` 첫 항목 처리).

### Fixed
- 다른 프로그램이 이미 8765번 포트를 쓰고 있으면 `uvicorn.run()`이 `OSError`로 죽는데,
  브라우저 자동 오픈 타이머는 이와 무관하게 독립 실행돼 "사이트에 연결할 수 없음"만 뜨고
  원인은 콘솔 로그에만 남던 문제. `run.py`가 8765~8769를 순서대로 실제 바인딩 시도해 처음
  성공하는 포트로 서버를 켜고 그 포트로만 브라우저를 열도록 수정. 전부 사용 중이면 콘솔에
  사람이 읽을 수 있는 오류 메시지를 남기고 깨끗하게 종료(exit code 1).

## [1.5.0] - 2026-07-31

미래 BridgeX 고객을 대상으로 한 앱 내장 사용자 가이드 추가.

### Added
- `GET /guide` — 설치/최초 실행, 장비 등록, 일상 사용, Teams 연동, 설정, 문제 해결, 부록으로
  구성된 사용자 가이드 화면. 목차(앵커 링크)로 원하는 항목만 바로 찾아볼 수 있음.
- 사이드바 맨 아래에 "가이드" 링크 추가(대시보드/설정/로그/가이드 4개 화면 공통).

### Fixed
- 사이드바가 `.main`(본문) 콘텐츠 높이만큼 함께 늘어나, 사이드바 맨 아래 요소가 뷰포트
  밖(페이지 끝)으로 밀려나던 레이아웃 버그 — 가이드 화면처럼 본문이 뷰포트보다 긴 화면에서만
  드러나던 문제라 이전 화면들에서는 보이지 않았음. `align-self: flex-start` + 고정 높이 +
  `position: sticky`로 수정.

## [1.4.0] - 2026-07-31

제품 브랜드를 "BridgeX"로 확정(coredxi 제품군)하고, 로고/아이콘을 실제 화면·배포물에 통합.

### Added
- `coredxi` 사내 로고를 대시보드/설정/로그 화면 상단바에 통합, `<title>`을 "BridgeX"로 변경.
- `favicon.ico`(16/32/48px), `app-icon.ico`(16/32/48/256px) 신규 생성 — `build.spec`의 `EXE()`에
  아이콘으로 연결해 다음 빌드부터 exe 아이콘에도 반영.
- 16px 파비콘 전용 단순화 로고(`coredxi-mark-simplified.png`) — 원본의 육각 체인 디테일이 16px에서
  뭉개지는 문제를 3배 슈퍼샘플링 후 다운스케일 방식으로 해결(계단현상·번짐 없이 안티앨리어싱).

### Changed
- 내부 레포/프로젝트명(`codec_control_center`, exe 파일명 `CodecControlCenter-vX.Y.Z.exe`)과
  `PLAN.md`/`PRD.md`/`SPEC.md` 등 기획 문서 제목은 유지 — 이번 변경은 화면에 보이는 브랜딩
  (제목/헤더/파비콘/exe 아이콘 이미지)범위로 한정.

## [1.3.0] - 2026-07-30

`/logs` 페이지에서 시스템 로그(`data/app.log`)를 볼 수 있는 뷰어 추가.

### Added
- `GET /logs/system` — `data/app.log`의 마지막 300줄을 최신순으로 표시. `/logs` 페이지에 "제어 로그"/"시스템 로그" 탭을 추가해 전환.
- 로그 로테이션/보관 정책(5MB × backupCount 3)은 변경 없음 — 조회 UI만 추가.

## [1.2.1] - 2026-07-30

Phase③ VDI 실장비 검증 중 발견된 Poly SSH 연결 실패 수정.

### Fixed
- Poly Group Series 실장비 중 SSH 호스트키로 `ssh-rsa`(SHA-1)만 지원하는 장비가 `Incompatible ssh peer (no acceptable host key)` 오류로 아예 연결되지 않던 문제. paramiko 5.x가 보안 강화를 위해 기본 제외한 `ssh-rsa` 협상/서명 검증 경로를 연결 시점에 복구하도록 수정 (`app/drivers/poly/poly_driver.py`). 다른 암호/키교환/MAC 알고리즘은 최신 기본값 유지.

## [1.2.0] - 2026-07-30

Teams 수동 다이얼(Pexip OTJ 캘린더 동기화 실패 대비) + 장비 카드 v2.

### Added
- `POST /api/devices/{id}/direct-dial` — 회의 ID(숫자 10자리) + Teams 테넌트 주소(장비별 우선, 없으면 전역 설정)로 CVI 게이트웨이에 직접 다이얼.
- 설정 화면 및 장비 등록/수정 모달에 Teams 테넌트 주소 입력란 추가(전역 기본값 + 장비별 override).
- 장비 카드에 모델명·마지막 재부팅 경과 자동 표시 — Poly `systemsetting get model`/`uptime get`, Cisco `xStatus SystemUnit ProductId`/`Uptime` 확인된 명령으로 조회, 30일 이상 미재부팅 시 경고 표시.
- 장비 카드 아이콘 제어버튼(음소거/종료/새로고침/재부팅)으로 UI 개편, 통화 중 회의 제목 표시.
- 카드별 "오늘 남은 회의" 목록(현재 시각 이후, 시간순) — 회의 주소 링크 클릭으로 참가.
- 장비 수정 모달(✎) 추가 — 기존 카드의 삭제 버튼을 이 모달 안으로 이동.

### Fixed
- 장비별/전역 Teams 테넌트 주소에 `"`/`'`/개행 문자를 금지해 다이얼 명령 조작 방지.
- Poly와 Cisco가 서로 다른 회의 시각 포맷을 반환해 회의 목록 필터링 시 Poly 회의가 전부 "지난 회의"로 잘못 판정되던 문제.
- 설정 화면 Alpine.js 컴포넌트가 `x-data` 속성 안에서 깨져 전체 설정 폼이 동작하지 않던 문제(JSON 이스케이프가 HTML 속성 경계를 보호하지 못함).

### Known Issues
- 실제 VDI/실장비 대상 수동 QA는 아직 진행 전 — 브라우저 기반 자동 QA(Playwright, 시뮬레이터 대상)만 완료됨.

## [1.1.0] - 2026-07-29

Phase③ 실장비(VDI) 검증 1차 피드백 반영.

### Fixed
- Poly 장비를 `connection_type="ssh"`로 등록하면 `driver_factory`가 이를 무시하고 항상 Telnet(telnetlib3)으로 접속을 시도해 `connection closed by device` 오류가 발생하던 문제. `PolyDriver`에 SSH 트랜스포트(paramiko)를 추가하고 `connection_type`에 따라 선택하도록 수정.
- 사이드바의 "장비관리"/"Teams" 메뉴가 만들어진 적 없는 죽은 링크(`href="#"`)였던 문제 — 각각 대시보드의 "+장비 등록" 모달과 "오늘의 예정 회의" 위젯으로 이미 대체 구현되어 있어 링크 제거.

### Changed
- 장비를 새로 등록하면 곧바로 접속을 시도하지 않고 한 폴링 주기가 지난 뒤 첫 폴링을 수행하도록 변경 — 등록 직후 아직 준비되지 않은 장비가 즉시 오류로 표시되는 것을 방지.

### Added
- `data/app.log`에 폴링/드라이버 접속 오류를 파일로 기록 (RotatingFileHandler, 5MB x 3).
  - 폴링 실패뿐 아니라 Mute/Dial/Hangup/Reboot 등 제어 API 실패도 함께 기록.
  - 로그에 device_id(uuid) 대신 장비 이름을 남겨 어느 회의실인지 바로 식별 가능.
  - DriverError(예상된 접속/명령 오류)는 warning으로, 그 외 예상 밖 예외는 트레이스백 포함 error로 구분 기록 — 폴링 루프가 버그로 조용히 죽는 것도 방지.
- 영속 저장 파일(`devices.enc.json`, `settings.json`, `credentials.enc.json`, `history.sqlite3`)에 데이터 스키마 버전 관리 도입.

## [1.0.0] - 2026-07-29

PLAN.md Phase①~⑥(시뮬레이터 기반 개발) + PyInstaller 패키징까지 완료된 첫 배포 가능 상태.

### Added
- `DeviceDriver` 공통 인터페이스와 Poly(telnetlib3)/Cisco(paramiko) 드라이버 구현 (Phase①).
- Poly/Cisco 시뮬레이터 서버 및 DPAPI 기반 자격증명/장비 레지스트리 암호화 저장 (Phase①).
- FastAPI REST + WebSocket 백엔드, 장비 등록/제어(음소거·통화종료·재부팅) API (Phase②).
- HTMX/Alpine.js 기반 대시보드 UI — 장비 카드, 등록 모달, 그룹 제어, 다크모드, 실시간 상태 갱신 (Phase②).
- `PollingScheduler`: 세마포어 기반 동시성 제한 폴링, 지수 백오프, 연결 재사용 (Phase②).
- SQLite 기반 제어 이력 로깅(`ControlHistory`) 및 로그 조회 화면 (Phase⑥).
- 설정 화면(폴링 주기·동시 접속 제한·명령 타임아웃·시작 시 브라우저 자동 열기) (Phase⑥).
- Teams/OBTP 캘린더 연동 — Poly는 완전 구현, Cisco는 필드 레이아웃 미확인으로 best-effort 구현 (Phase④⑤).
- PyInstaller 단일 EXE 패키징, frozen 모드에서 `data/`가 실행파일 옆에 영속되도록 경로 해석 (`app/main.py:_resolve_paths()`).
- 앱 버전 표시(semver) — `/api/health`, 설정 화면 하단, EXE 파일명(`CodecControlCenter-v{version}.exe`)에 노출.

### Known Issues
- Cisco `get_obtp_entries()`는 공식 문서에 텍스트 모드 응답의 정확한 필드 레이아웃이 명시되어 있지 않아 best-effort로 구현됨 — Phase③ 실장비 검증에서 확인 필요.
- Phase③(VDI/실장비 검증)은 물리적 접근 권한이 없어 보류 상태.
