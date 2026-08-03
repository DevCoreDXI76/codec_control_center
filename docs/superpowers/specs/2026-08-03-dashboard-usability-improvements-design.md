# 설계 — 대시보드 사용성 개선 5건 (VDI 실사용 피드백)

- 작성일: 2026-08-03
- 배경: VDI 환경에서 v1.5.19를 실사용하던 중 나온 개선 요청 5건. 서로 독립적인 소규모
  UI/UX 변경이라 하나의 스펙 문서에 섹션별로 묶어 진행한다(각각 별도 브레인스토밍 사이클
  불필요).
- **범위 밖(명시적으로 제외)**: 그룹을 별도 엔티티로 승격(그룹 메타데이터 테이블 신설),
  회의 목록 서버사이드 정렬/페이지네이션(현재도 프런트엔드에서 device별 OBTP를 모아 합치는
  구조라 클라이언트 정렬로 충분), 로그 화면의 과거 이력 추가 조회(현재 화면 표시분 200건/
  300줄 이상은 이번 스코프 밖 — 필요해지면 별도 브레인스토밍).

## 0. 확정된 결정 사항

- 그룹 이름 변경 시 대상 이름이 이미 다른 그룹명과 같으면 **차단**(병합 안 함, 에러 메시지).
- 그룹 "삭제"는 그룹에 속한 장비들의 `group` 필드를 `""`로 비우는 것뿐 — **장비 자체는
  삭제되지 않는다.** 그룹 태그 없는 장비는 기존 동작 그대로 "전체" 탭에서만 보이고 그룹
  탭에는 안 뜬다.
- "오늘의 예정 회의" 정렬 기준/방향/페이지 크기는 `localStorage`에 저장해 다음 방문 때도
  유지. 페이지 **번호**는 새로고침 시 1로 리셋(표준 UX, 별도 저장 안 함).
- 로그 화면 복사/다운로드는 현재 화면에 로드된 범위만(제어 로그 최근 200건, 시스템 로그
  최근 300줄) — 백엔드 추가 조회 없음.

---

## 1. 그룹 관리 (이름 수정 / 삭제)

### 1.1 배경

`Device.group`은 자유 텍스트 필드일 뿐 별도 그룹 엔티티가 없다(`app/models/device.py`).
대시보드의 그룹 탭(`index.html` `{% for g in groups %}`)은 `main.py`에서
`sorted({d.group for d in devices if d.group})`로 매 요청마다 동적으로 계산된다. 그룹을
"관리"한다는 건 곧 그 태그를 가진 장비들을 일괄로 건드리는 것과 같다.

### 1.2 백엔드 — `app/core/registry.py`

```python
def rename_group(self, old_name: str, new_name: str) -> int:
    """old_name을 가진 모든 장비의 group을 new_name으로 바꾼다. 반환값은 변경된 장비 수.
    new_name이 old_name과 다르면서 이미 다른 장비가 쓰고 있으면 ValueError(차단)."""

def clear_group(self, name: str) -> int:
    """name을 가진 모든 장비의 group을 ""로 비운다(장비는 유지). 반환값은 변경된 장비 수."""
```

- 둘 다 `_read()` 한 번 → 메모리에서 순회하며 `dataclasses.replace()` → `_write()` 한 번으로
  처리(장비 수만큼 `update_device()`를 반복 호출하지 않음 — 파일 I/O 최소화, 기존
  `add_device`/`update_device` 패턴과 동일한 read-modify-write 구조).
- `rename_group`은 대상 이름이 이미 **다른** 그룹으로 존재하면(`old_name`을 가진 장비를
  빼고도 `new_name`을 가진 장비가 있으면) `ValueError`로 차단.
- 존재하지 않는 그룹명이 들어오면(변경 대상 장비 0건) 그것도 `ValueError` — 조용히 no-op
  하지 않는다(오탈자로 인한 착오를 바로 드러내기 위함).

### 1.3 API — 신규 `app/api/routes_groups.py`

```python
router = APIRouter(prefix="/api/groups", tags=["groups"])

GET    /api/groups              -> [{"name": str, "device_count": int}, ...]  (그룹명 오름차순)
PATCH  /api/groups/{name}       -> {"new_name": str}  성공 시 {"device_count": int} / 충돌 시 409
DELETE /api/groups/{name}       -> {"device_count": int}
```

- `main.py`에 `from app.api.routes_groups import router as groups_router` +
  `app.include_router(groups_router)` 추가(기존 라우터 등록 패턴과 동일).
- `PATCH`/`DELETE` 성공 후 `request.app.state.registry`를 갱신할 필요는 없음(레지스트리는
  파일 기반 상태 없는 조회 객체라 다음 조회부터 자동 반영) — 다만 대시보드 페이지 자체는
  새로고침해야 그룹 탭에 반영됨(기존 장비 등록/수정도 동일하게 `location.reload()` 패턴).

### 1.4 UI — `settings.html`에 "그룹 관리" 섹션 추가

- 페이지 로드시 `GET /api/groups` 호출해 목록 렌더(Alpine `x-data`로 별도 컴포넌트,
  기존 설정 폼과 독립적인 `x-data` 블록).
- 각 행: `그룹명 (장비 N대)` + ✎(이름 수정) + 🗑(삭제) 버튼.
  - ✎ 클릭 → 인라인 텍스트 입력으로 전환 → 저장 시 `PATCH`. 충돌(409) 시 "이미 존재하는
    그룹명입니다" 에러 문구.
  - 🗑 클릭 → `confirm('"${name}" 그룹 태그를 ${count}대 장비에서 제거합니다. 장비 자체는
    삭제되지 않습니다. 계속할까요?')` → 확인 시 `DELETE`.
  - 성공 시 목록 새로고침(그룹 API 재호출, 페이지 전체 리로드는 불필요).
- 그룹이 하나도 없으면(모든 장비가 미분류) "등록된 그룹이 없습니다" 안내 문구.

### 1.5 테스트 계획

- `tests/core/test_registry.py`: `rename_group`(정상/충돌/존재하지 않는 이름 3케이스),
  `clear_group`(정상/존재하지 않는 이름).
- `tests/api/test_routes_groups.py`(신규): GET 목록, PATCH 정상/409, DELETE 정상.

---

## 2. 그룹 일괄 제어 버튼 제거

### 2.1 변경 내용

- `index.html`: `#group-bulk-actions` 블록(그룹 전체 Mute/Unmute/재부팅 버튼) 전체 삭제.
- `dashboard.js`: `bulkMute()`, `bulkReboot()`, `visibleDeviceIdsInGroup()` 함수 삭제.
  `filterGroup()`에서 `group-bulk-actions` 표시/숨김 토글하던 부분(`bulkBar`/`label`
  관련 코드)도 함께 제거 — **그룹 탭 자체(필터링)는 그대로 유지.**
- `/api/devices/{id}/mute`, `/api/devices/{id}/reboot` 등 개별 제어 API는 변경 없음(그룹
  버튼이 이 API들을 반복 호출하던 것뿐이므로 백엔드는 손댈 게 없음).

### 2.2 테스트 계획

- 기존 대시보드 라우트 테스트(`tests/test_dashboard_route.py`)에 그룹 일괄 제어 관련
  검증이 있었다면 제거. 없으면 회귀 확인만.
- 수동 QA: 그룹 탭 클릭 시 필터링은 여전히 되지만 일괄 제어 버튼이 안 보이는지 확인
  (`docs/PIPELINE.md` §3 체크리스트에 항목 추가 권장).

---

## 3. "오늘의 예정 회의" 정렬 + 페이지네이션

### 3.1 현황

`dashboard.js`의 `loadUpcomingMeetings()`가 모든 장비의 OBTP 항목을 모아
`rows = [{deviceId, deviceName, entry}, ...]`로 만들고 시간순 정렬 후 `div.meeting-row`를
직접 DOM에 append한다(`#meetings-list`). 서버 API 변경 없이 이미 클라이언트에 전체 데이터가
있으므로 정렬/페이지네이션은 순수 프런트엔드 작업.

### 3.2 변경 — `index.html` + `dashboard.js`

- `#meetings-list`를 `<table>`로 교체, 헤더 4개: 시간 / 회의실 / 회의명 / 참가.
  - 각 `<th>` 클릭 시 해당 키로 정렬, 같은 헤더 재클릭 시 방향 반전(▲▼ 표시).
  - 정렬 키: 시간→`entry.start_time`, 회의실→`deviceName`, 회의명→`entry.subject`,
    참가→`entry.join_uri` 존재 여부(있는 행이 우선, 동률이면 시간순).
- 테이블 하단에 `페이지 크기: [5] [10] [20]` 버튼 그룹(기본 10) + `‹ 이전 / 다음 ›` 페이지
  버튼 + `N / 전체 M건` 표시.
- 상태(`sortKey`, `sortDir`, `pageSize`)는 `localStorage`(`bridgex.meetings.sort`,
  `bridgex.meetings.pageSize` 등 키)에 저장, `loadUpcomingMeetings()` 시작 시 복원. 현재
  페이지 번호는 상태에 안 넣고 매번 1로 시작.
- 기존 `renderCardTeamsSection()`(장비 카드 안의 "TEAMS · 오늘 남은 회의 N건" 위젯)은
  변경 없음 — 이번 정렬/페이지네이션은 상단 "오늘의 예정 회의" 전체 목록 위젯에만 적용.

### 3.3 테스트 계획

- 이 부분은 순수 클라이언트 JS(DOM 렌더링)라 기존 프로젝트에 JS 유닛 테스트 프레임워크가
  없음(pytest만 존재) — `docs/PIPELINE.md` §3 수동 QA 체크리스트에 케이스 추가:
  정렬 클릭 동작, 페이지 크기 변경, 페이지 이동, 새로고침 후 정렬/페이지 크기 유지 확인.
  자동화 테스트는 이번 스코프에서 추가하지 않음(기존 관례와 동일 — dashboard.js는 현재도
  E2E/유닛 테스트 대상이 아님).

---

## 4. 최초 설치 시 다크모드 기본값

### 4.1 변경 — `app/static/js/theme.js`

```js
function getPreferredTheme() {
  const stored = getStoredTheme();
  if (stored === "light" || stored === "dark") return stored;
  return "dark"; // 기존: prefers-color-scheme 체크 → 최초 설치 시 무조건 다크로 시작
}
```

- `localStorage`에 저장된 값이 있으면(사용자가 한 번이라도 토글했으면) 그 값을 그대로
  존중 — 토글 로직(`applyTheme`, 클릭 핸들러)은 변경 없음.
- OS가 라이트 모드여도 최초 실행은 다크로 시작(요청사항 그대로 — OS 설정 무시).

### 4.2 테스트 계획

- 순수 JS라 자동 테스트 없음(1번의 조건문 변경). 수동 확인: `localStorage.clear()` 후
  새로고침 시 다크로 뜨는지, 라이트로 토글 후 새로고침해도 라이트 유지되는지.

---

## 5. 로그 화면 복사/다운로드 버튼

### 5.1 변경 — `logs.html` + 신규 인라인 스크립트(또는 `logs.js`)

- 제어 로그(`view == 'control'`) 테이블 위/아래에 버튼 2개: "전체 복사", "txt 다운로드".
  - 직렬화 포맷: 헤더 포함 탭 구분 텍스트
    `시각\t장비\t동작\t결과\t상세` + 각 행. Jinja 템플릿이 이미 렌더한 `entries`를
    JS에서 다시 순회하기보다, 서버 렌더 시점에 `data-copy-text` 속성 하나로 미리
    직렬화해 심어둔다(FastAPI/Jinja는 이미 `entries`를 갖고 있으므로 별도 API 호출 불필요).
  - 시스템 로그(`view == 'system'`)는 `log_lines`를 그대로 줄바꿈 join한 텍스트.
- 버튼 동작:
  - "전체 복사": `navigator.clipboard.writeText(text)` → 성공 시 기존 `showToast` 스타일
    재사용한 토스트("복사되었습니다"). `dashboard.js`의 `showToast`는 `logs.html`에서
    로드 안 하므로 `logs.html` 전용으로 동일 패턴의 작은 헬퍼를 인라인 스크립트에 둔다
    (`dashboard.js` 전체를 로그 페이지에 끌어오지 않음 — 불필요한 의존 추가 방지).
  - "txt 다운로드": `Blob([text], {type: 'text/plain;charset=utf-8'})` +
    `<a download="control-log-YYYYMMDD-HHmm.txt">` 클릭 트리거. 파일명에 현재 시각 포함.
- 두 버튼 모두 `entries`/`log_lines`가 비어있으면(empty-state) 비활성화 또는 미노출.

### 5.2 테스트 계획

- 서버 렌더링 부분(`data-copy-text` 직렬화)은 `tests/api/test_routes_logs.py`에 응답
  본문에 해당 속성/텍스트가 포함되는지 검증 추가 가능.
- 클립보드/다운로드 자체(브라우저 API)는 자동 테스트 대상 아님 — 수동 QA 체크리스트에
  추가(복사 후 붙여넣기 확인, 다운로드된 txt 파일 내용 확인).

---

## 6. 영향받는 파일 요약

| 파일 | 변경 |
|---|---|
| `app/core/registry.py` | `rename_group`, `clear_group` 추가 |
| `app/api/routes_groups.py` | 신규 |
| `app/main.py` | groups 라우터 등록 |
| `app/templates/settings.html` | 그룹 관리 섹션 추가 |
| `app/templates/index.html` | 그룹 일괄 제어 블록 제거, 회의 목록 테이블화 |
| `app/static/js/dashboard.js` | bulk 함수 제거, 회의 목록 정렬/페이지네이션 로직 추가 |
| `app/static/js/theme.js` | 최초 기본값 다크로 변경 |
| `app/templates/logs.html` | 복사/다운로드 버튼 + 인라인 스크립트 |
| `tests/core/test_registry.py` | rename/clear 테스트 추가 |
| `tests/api/test_routes_groups.py` | 신규 |
| `tests/api/test_routes_logs.py` | 직렬화 속성 검증 추가(선택) |
