# Changelog

이 프로젝트의 모든 주요 변경사항을 이 파일에 기록한다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따른다.

## [Unreleased]

### Added
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
