# app/__version__.py
"""앱 버전 (Semantic Versioning). 릴리즈마다 갱신한다.

1.0.0 = PLAN.md Phase①~⑥(시뮬레이터 기반 개발) + PyInstaller 패키징까지 완료된
첫 배포 가능 상태 (2026-07-29, git tag v0.8-pyinstaller 시점).
이후 실장비 검증(Phase③)에서 드러나는 수정은 patch(1.0.x), 기능 추가는 minor(1.x.0)로 올린다.
"""

__version__ = "1.0.0"
