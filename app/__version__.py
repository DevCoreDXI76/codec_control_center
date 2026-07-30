# app/__version__.py
"""앱 버전 (Semantic Versioning). 릴리즈마다 갱신한다.

1.0.0 = PLAN.md Phase①~⑥(시뮬레이터 기반 개발) + PyInstaller 패키징까지 완료된
첫 배포 가능 상태 (2026-07-29, git tag v0.8-pyinstaller 시점).
1.1.0 = Phase③ 실장비 검증 1차 피드백 반영 — Poly SSH 트랜스포트 추가,
장비 등록 시 즉시폴링 제거, 죽은 사이드바 링크 제거, 파일 로깅 추가.
1.2.0 = Teams 수동 다이얼(CVI 회의ID+테넌트 직접 다이얼) + 장비 카드 v2
(모델/가동시간 자동표시, 아이콘 제어버튼, Teams 오늘회의 목록, 장비 수정 모달).
1.2.1 = Phase③ VDI 실장비 검증 — Poly 실장비가 ssh-rsa(SHA-1)만 지원하는
호스트키 문제로 SSH 연결이 전부 실패하던 버그 수정.
1.3.0 = `/logs` 페이지에 제어 로그/시스템 로그 탭 분리 — data/app.log를
UI에서 조회 가능(신규 /logs/system 라우트).
이후 실장비 검증(Phase③)에서 드러나는 수정은 patch(1.x.y), 기능 추가는 minor(1.x.0)로 올린다.
"""

__version__ = "1.3.0"
