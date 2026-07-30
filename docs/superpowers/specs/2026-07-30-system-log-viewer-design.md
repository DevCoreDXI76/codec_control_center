# 설계 — 시스템 로그(app.log) 뷰어

- 작성일: 2026-07-30
- 배경: 기존 `/logs` 페이지("제어 이력")는 `data/history.sqlite3`의 `control_log` 테이블만
  보여준다. 폴링 실패·드라이버 접속 오류 등은 별도로 `data/app.log`(`RotatingFileHandler`,
  `app/main.py:_configure_logging`)에 쌓이고 있지만 지금은 UI가 전혀 없어 개발자가 파일을
  직접 열어봐야 한다. 사용자가 "제어 로그"와 "시스템 로그"를 UI상에서 분리해 `app.log`도
  화면에서 확인할 수 있게 해달라고 요청.
- **범위 밖(명시적으로 제외)**: 로그 레벨 필터링, 실시간 자동 폴링/스트리밍, 로그 다운로드
  버튼, 로테이션 정책(5MB×3) 변경, 로그 레벨(INFO 고정)의 설정 UI 노출. 전부 이번 요청에
  없었고 YAGNI로 제외 — 필요해지면 별도 브레인스토밍.

## 1. 현황 정리 (변경 없음, 참고용)

| 항목 | 제어 로그 | 시스템 로그 |
|---|---|---|
| 저장소 | `data/history.sqlite3` (`control_log` 테이블) | `data/app.log` (+ 로테이션 백업 `.1~.3`) |
| 기록 모듈 | `app/core/history.py` (`ControlHistory`) | 루트 로거 + `RotatingFileHandler` (`app/main.py:_configure_logging`) |
| 로테이션 | 없음(누적) | `maxBytes=5*1024*1024, backupCount=3` — 시간 기반 아님, 기간 제한 없음 |
| 기존 UI | `/logs` 페이지, `/api/logs` | 없음(이번에 신규 추가) |

이번 작업은 이 표의 "저장소"·"로테이션" 자체를 바꾸지 않는다 — 신규 뷰어만 추가한다.

## 2. 메뉴 구조

사이드바의 `로그` 링크는 그대로 두고(신규 최상위 메뉴 추가 없음), `/logs` 페이지 안에 탭
2개를 추가한다: **제어 로그**(기존, 기본 선택) / **시스템 로그**(신규). 탭은 각각 별도
라우트로 이동하는 링크다.

- `GET /logs` — 기존 그대로, "제어 로그" 탭 active
- `GET /logs/system` — 신규, "시스템 로그" 탭 active

## 3. 백엔드

### 3.1 `app/core/applog.py` (신규 모듈)

```python
def tail_app_log(path: Path, n: int = 300) -> list[str]:
```

- 파일이 없으면(`app.log`가 아직 한 번도 안 만들어진 경우) 빈 리스트 반환.
- 있으면 전체를 읽어 마지막 `n`줄만 취하고, **최신 줄이 위로 오도록 역순**으로 반환한다
  (제어 로그 테이블이 최신순 정렬인 것과 톤을 맞춤).
- 파일 크기가 로테이션 정책상 최대 5MB로 제한돼 있어 전체를 메모리에 읽어도 문제 없음 —
  seek 기반 tail 최적화는 이번 스코프에서 불필요(YAGNI).
- 인코딩은 `_configure_logging`과 동일하게 `utf-8`.

### 3.2 `app/main.py`

- 현재 `_configure_logging(DATA_DIR / "app.log")` 호출에서 경로가 1회성으로만 쓰이는데,
  이를 `APP_LOG_PATH = DATA_DIR / "app.log"` 상수로 빼서 `_configure_logging(APP_LOG_PATH)`
  호출과 신규 라우트 양쪽에서 재사용한다.
- 신규 라우트:
  ```python
  @app.get("/logs/system")
  async def system_log_page(request: Request):
      lines = tail_app_log(APP_LOG_PATH)
      return templates.TemplateResponse(
          request, "logs.html", {"view": "system", "log_lines": lines}
      )
  ```
- 기존 `logs_page`도 템플릿에 `view="control"`을 넘기도록 한 줄 추가(탭 active 표시용).

## 4. 템플릿 (`logs.html`)

- `<main>` 최상단에 탭 네비 추가:
  ```html
  <div class="log-tabs">
    <a href="/logs" class="{{ 'active' if view == 'control' else '' }}">제어 로그</a>
    <a href="/logs/system" class="{{ 'active' if view == 'system' else '' }}">시스템 로그</a>
  </div>
  ```
- `view == 'control'`이면 기존 제어 이력 테이블/empty-state 그대로 렌더.
- `view == 'system'`이면 새 블록:
  ```html
  {% if log_lines %}
  <pre class="app-log-view">{% for line in log_lines %}{{ line }}
  {% endfor %}</pre>
  {% else %}
  <div class="empty-state"><p>아직 기록된 시스템 로그가 없습니다.</p></div>
  {% endif %}
  ```
- 새로고침은 탭 링크 재클릭 또는 브라우저 새로고침으로 충분 — 정적 페이지라 별도 버튼/JS
  불필요(사용자 확인 완료: "새로고침 버튼만, 정적").

## 5. CSS (`app/static/css/style.css`)

- `.log-tabs`, `.log-tabs a`, `.log-tabs a.active` — 기존 사이드바 active 스타일 톤 재사용,
  간단한 밑줄/배경 강조만.
- `.app-log-view` — 모노스페이스 폰트, `white-space: pre-wrap`, `overflow-x: auto`(가로
  스크롤 방지), 카드 배경과 통일된 톤.
- 최근 커밋(`c9559b1`, `.field input:not([type="checkbox"])` 스코프 수정)과 겹치는 선택자
  없음 — 충돌 없이 독립적으로 추가 가능.

## 6. 테스트 계획

- `tail_app_log` 유닛 테스트: 파일 없음(빈 리스트), 줄 수가 `n` 이하/초과인 경우, 최신줄이
  맨 위로 오는지.
- `/logs/system` 라우트 테스트: 200 응답, `app.log`가 없을 때 empty-state 문구 노출, 로그
  라인이 있을 때 응답 본문에 포함되는지.
- 기존 `/logs` 라우트·`test_configure_logging_writes_to_file` 테스트는 변경 없음 — 회귀
  없는지만 확인.
