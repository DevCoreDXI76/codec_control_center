# Changelog

이 프로젝트의 모든 주요 변경사항을 이 파일에 기록한다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따른다.

## [Unreleased]

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
