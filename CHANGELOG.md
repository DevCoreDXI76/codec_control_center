# Changelog

이 프로젝트의 모든 주요 변경사항을 이 파일에 기록한다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따른다.
언제 버전을 올리고 태그를 남기는지 등 절차 전체는 `docs/PIPELINE.md` 참조.

## [Unreleased]

## [1.6.1] - 2026-08-03

v1.6.0 VDI 재테스트 피드백 반영.

### Fixed
- Cisco Bookings List/Get이 UTC(Z 접미사)로 내려주는 회의 시간을 변환 없이 그대로
  표시하던 문제 — 실제보다 9시간 이른 시각으로 보였음(예: 13:30 KST 회의가 04:30으로
  표시). `cisco_driver.py`에서 UTC→KST 변환 후 Poly와 동일한 naive 형식으로 통일.
- 프런트엔드의 "지금(now)" 계산이 UTC 기준이라 KST naive 회의 시각과 비교 시 자정
  경계에서 어긋날 수 있던 문제 — KST 기준으로 계산하도록 수정.

### Changed
- "오늘의 예정 회의" 표에 시작~종료 시각을 함께 표기(기존엔 시작시간만). 장비 카드별
  TEAMS 위젯은 기존대로 시작시간만 표기.
- 종료된 회의 필터 조건을 "종료 시각이 지나지 않은 회의만"으로 단순화(동작은 동일).

### Known Issues
- 페이지당 표시 개수(5/10/20) 버튼 관련 문의는 재현 결과 정상 동작으로 확인됨(표시할
  회의가 선택한 개수보다 적으면 버튼 활성 표시만 바뀌고 목록 내용은 변화 없음) — 코드
  수정 없이 가이드에 설명 추가.

## [1.6.0] - 2026-08-03

대시보드 사용성 개선 5건 (VDI 실사용 피드백 기반).

### Added
- 그룹 관리 — 설정 화면에서 그룹 이름을 수정하거나 삭제할 수 있음(`/api/groups` REST API
  신설). 삭제는 장비의 그룹 태그만 지우고 장비 자체는 삭제하지 않음. 이미 존재하는
  그룹명으로는 병합 없이 이름 변경이 차단됨.
- "오늘의 예정 회의" 목록에 정렬(시간/회의실/회의명/참가 헤더 클릭)과 페이지네이션
  (5/10/20개, 이전/다음)을 추가. 정렬 기준·페이지 크기는 다음 방문에도 유지됨(localStorage).
- 로그 화면(제어 로그/시스템 로그)에 "전체 복사"·"txt 다운로드" 버튼 추가.

### Changed
- 최초 설치 시 다크모드를 기본값으로 변경(기존에는 OS `prefers-color-scheme`를 따름).
  이미 한 번이라도 테마를 바꾼 사용자의 선택은 그대로 유지됨.
- 인앱 가이드(`/guide`) 문서·스크린샷을 위 변경사항에 맞게 갱신.

### Removed
- 그룹 일괄 제어(Mute/Unmute/재부팅) 버튼 제거 — 오작동 시 여러 대에 동시에 영향을 줄 수
  있는 안전 리스크. 그룹 탭을 통한 필터링(보기)은 그대로 유지.

## [1.5.19] - 2026-07-31

Teams 연동 라운드 3차 — 통화 중 중복 참가 방지(안전), Poly 회의 제목 표시 버그 수정.

### Fixed
- **안전 문제**: Cisco 장비에서 통화 중에 회의 링크를 또 클릭하거나 direct-dial을 실행하면
  같은 회의에 중복 참가되며 하울링이 발생하는 사고 확인 — 통화 중일 때는 링크 참가/
  direct-dial을 프런트엔드에서 막고 안내 토스트를 띄우도록 수정(`dashboard.js`).
- Poly 카드는 통화 중에도 Cisco와 달리 회의 제목이 안 뜨던 문제 — 실장비 원문으로 확인한
  결과 call_peer를 잘못된 필드 인덱스에서 읽고 있었음(항상 빈 문자열). 올바른 인덱스로
  수정(`poly_driver.py`), 시뮬레이터도 실장비 필드 배치에 맞게 수정(`poly_sim_server.py`).

## [1.5.18] - 2026-07-31

Poly Teams 링크 참가 재발 — 이번엔 잘못된 dial 명령이 근본 원인이었음.

### Fixed
- v1.5.17 배포 후에도 Poly Teams 링크 참가가 "timeout waiting for device response"로
  재현. 실제 원문 확인 결과 `join_meeting()`이 쓰던 `dial phone sip "..."`에 장비가
  `info: AUDIO call not enabled`로 응답(거부)하고 있었음 — 밀린 잡음이 아니라 장비의 진짜
  거부 응답인데 재시도 로직이 계속 건너뛰다 타임아웃으로만 보였던 것. join_meeting()이
  direct-dial과 동일하게 검증된 `dial manual`을 쓰도록 변경, `_call_expecting()`이
  `info: `로 시작하는 줄은 곧장 반환(건너뛰지 않음)하도록 수정(`poly_driver.py`).

## [1.5.17] - 2026-07-31

Teams 연동/기능 체계적 테스트 라운드 — Teams 링크 참가 실패, 자기소개 블록 길이 과소평가 수정.

### Fixed
- Teams 회의 목록의 링크로 참가하면 Poly 2대 모두 "실패: 200"만 뜨던 문제(직접 회의ID
  다이얼은 정상 동작) — `join_meeting()`이 `dial()`/`hangup()`/`mute()`와 달리 응답 밀림
  대응(`_call_expecting()`)을 안 쓰고 있던 게 원인. dial()과 동일하게 수정, 실패 시 원문을
  담아 예외로 올리도록 함(`poly_driver.py`).
- v1.5.16 배포 후에도 "unexpected response" 오류가 간헐적으로 재발 — 세션이 스스로 보내는
  자기소개 블록이 13줄 넘게 이어지고 세션 중 아무 때나 끼어들 수 있음이 `/logs` 원문으로
  확인됨. 응답 밀림 재시도 한도를 3 → 25로 확대, 모델 정보의 "Model: 값" 형식도 인식하도록
  `_fetch_model()` 수정.

## [1.5.16] - 2026-07-31

Poly 세션 재정렬 문제 — "응답이 한 교환씩 밀린다"는 결정적 패턴 확인 후 일반적으로 해결.

### Fixed
- 5회 이상 반복 재현된 실장비 트레이스로 확정: 응답이 명령보다 정확히 한 교환씩 밀려
  들어온다(mute의 진짜 응답이 callinfo 자리에서, model의 진짜 응답이 mute 자리에서 나오는
  식). `_call_expecting()`을 추가해 응답이 그럴듯한지 확인하고 아니면 최대 3줄까지 더 읽어
  밀려 들어온 진짜 응답을 찾도록 함 — mute get/set, model 조회, uptime 조회, dial, hangup에
  모두 적용(`poly_driver.py`). 이전에는 callinfo만 개별적으로 에러 처리했고 mute get 등은
  조용히 잘못된 값을 받아들였는데, 이번엔 모든 호출부에 일반적으로 적용.

## [1.5.15] - 2026-07-31

calendarmeetings "회의 없음" 응답 형식 실측 확인 및 회귀 테스트 고정.

### Fixed
- v1.5.14의 Known Issue 해소: 사용자가 실장비에 직접 접속해 `calendarmeetings list "today"`
  원문을 확보 — 회의가 없으면 "calendarmeetings list begin" 바로 뒤에 내용 없이
  "calendarmeetings list end"가 옴. v1.5.14의 "-> " 프롬프트 에코 필터가 이미 이 케이스를
  올바르게 처리함을 확인, 이 원문 그대로 회귀 테스트로 고정(코드 변경 없음).

## [1.5.14] - 2026-07-31

Poly 세션 재정렬 문제 — 프롬프트 에코 필터 추가, calendarmeetings 관련 원인 후보 기록.

### Fixed
- 장비 셸이 "-> " 프롬프트 뒤에 이전에 받은 명령을 그대로 에코해 돌려보내는데(한두 교환
  뒤늦게 나타날 수 있음), `_read_line()`에서 이 프리픽스도 잡음으로 걸러내도록 추가
  (`poly_driver.py`).

### Known Issues
- 진단 로그에서 `calendarmeetings list "today"`(Teams 회의 목록 조회) 응답 블록이 조각나서
  mute/callinfo 응답 자리에 나타나는 현상이 확인됨. `get_obtp_entries()`가 자신의 응답을
  끝까지 기다리지 않고 조기 반환하는 것으로 추정되나, calendarmeetings의 "회의 없음" 실제
  응답 형식이 실장비로 확인된 적이 없어 추측으로 고치지 않음 — 다음 라운드에서 실장비 원문
  확보 필요.

## [1.5.13] - 2026-07-31

Poly 세션 재정렬 문제 — 진단 로그로 확보한 실제 트레이스 기반 일반화된 수정.

### Fixed
- v1.5.12의 진단 로그로 실제 송수신 원문을 여러 건 확보한 결과: (1) 연결 시 인사말이
  "Hi, my name is : ..." 한 줄이 아니라 몇 줄 더 이어지는 블록이었음(정확한 줄 수는 예측
  불가), (2) 모든 트레이스에 빈 줄이 잡음으로 반복 등장. 특정 문자열을 더 추가하는 대신
  일반적으로 수정: connect() 직후 명령을 보내기 전에 짧은 타임아웃으로 반복 읽어 조용해질
  때까지 전부 비우는 시작 잡음 제거 단계 추가(인사말이 몇 줄이든 안전), `_read_line()`에서
  빈 줄은 항상 잡음으로 간주해 버리도록 수정(`poly_driver.py`).

## [1.5.12] - 2026-07-31

Poly 세션 재정렬 문제 — 이번 릴리즈는 근본 수정이 아니라 진단 계측 추가.

### Changed
- v1.5.11로도 VDI에서 같은 계열 문제 재현(`unexpected response to 'callinfo all':
  'systemsetting get model'`). "채널이 방금 보낸 명령을 그대로 에코한다"는 가설로 고쳐봤으나
  시뮬레이터 회귀 테스트에서 바로 깨짐 — Poly의 mute on 명령은 정상 성공 응답 자체가 명령과
  동일한 문자열("mute near on")이라 이 방식은 정상 응답까지 에코로 오인한다. 되돌리고, 대신
  문제가 재발했을 때 화면 캡처로 한 줄씩 추측하지 않도록 최근 송수신 원문을 남겨뒀다가 검증
  실패 시 시스템 로그(`/logs`)에 남기도록 추가(`poly_driver.py`) — 동작 변경 없음, 진단 강화만.

## [1.5.11] - 2026-07-31

Poly "인사말 줄" 끼어들기로 인한 반복 재연결 실패 수정.

### Fixed
- v1.5.10 배포 직후 VDI에서 같은 증상이 계속 반복됨 — 실제 에러 메시지를 확인해보니
  `unexpected response to 'callinfo all': 'Hi, my name is : 판교 6층 영상회의실'`. Poly
  장비가 세션을 새로 열면 명령과 무관하게 인사말 한 줄을 스스로 먼저 보내는데, 도착 시점이
  불규칙해서(연결 직후 또는 몇 번의 폴링 뒤) v1.5.10의 엄격 검증에 매번 걸려 재연결해도
  반복 실패하고 있었음. `_read_line()`에서 이 인사말 줄을 만나면 무조건 버리고 다음 줄을
  읽도록 수정(`poly_driver.py`) — 어느 명령의 응답 자리에 끼어들든 투명하게 걸러진다.

## [1.5.10] - 2026-07-31

VDI 2차 재테스트 — Poly "가짜 통화중" 재발 수정, 오프라인 자가복구, 제어 로그 KST 표시.

### Fixed
- Poly 장비에서 실제로는 통화중이 아닌데 새로고침을 해도 계속 "통화중"으로 표시되던 문제가
  v1.5.3(장비별 락) 이후에도 재발. 원인은 `callinfo` 응답 파싱이 "system is not in a call"과
  다르기만 하면 무조건 in_call=True로 확정하던 fail-open 로직 — 세션이 한 번이라도 어긋나면
  (응답 줄 정렬이 밀리는 등) 엉뚱한 줄도 "통화중"으로 오판했고 오류 로그도 안 남았다.
  `_call_block()`에 엄격 검증 모드를 추가해 예상 밖 응답은 `DriverCommandError`로 올리도록
  수정(`poly_driver.py`).
- 위 수정 과정에서 발견된 별개의 구조적 문제: 드라이버가 예외 없이 `get_status()` 내부에서
  스스로 오류를 삼켜 `online=False`만 반환하면, `PollingScheduler`가 같은(깨진) 연결을 계속
  재사용해 영영 재연결하지 않던 문제 — 오프라인 상태를 받으면 항상 드라이버를 버리고 다음
  폴링에서 새로 연결하도록 수정(`polling.py`). Poly 외 Cisco에도 동일하게 적용됨.
- 제어 로그(`/logs`) 시각이 UTC 그대로 표시돼 실제 한국 시간과 9시간 어긋나 보이던 문제 —
  DB에는 UTC로 저장하되 표시 시점에 KST(UTC+9 고정 오프셋)로 변환(`history.py`). Windows
  실행 환경엔 `zoneinfo`용 `tzdata` 패키지가 없어(`ZoneInfoNotFoundError` 확인) 고정 오프셋을
  직접 사용.

## [1.5.9] - 2026-07-31

가이드 화면 "목차" 박스가 헤더에 가려진 채로 붙어있던 문제 수정.

### Fixed
- v1.5.8에서 헤더(`.topbar`)와 사이드바는 스크롤 시 고정되도록 고쳤지만, 가이드 본문의
  "목차"(`.guide-toc`) 박스는 여전히 스크롤을 따라 사라지는 것처럼 보이던 문제. 실제로는
  이미 `position: sticky`였고 붙는 동작 자체는 하고 있었으나, `top` 오프셋이 1.25rem(20px)
  뿐이라 새로 57px 높이로 고정된 헤더 뒤에 가려진 채로 붙어있던 것이었음. `top`을
  `57px + 1.25rem`으로 옮겨 헤더 바로 아래에 정상적으로 보이도록 수정.

## [1.5.8] - 2026-07-31

가이드 화면 스크롤 시 헤더/사이드바가 사라지던 문제 수정.

### Fixed
- `/guide`에서 마우스 스크롤을 내리면 상단 헤더(`.topbar`)와 좌측 사이드바가 페이지와 함께
  스크롤되어 화면 밖으로 사라지던 문제. v1.5.2에서 사이드바만 `position: sticky`였다가 화면이
  튀는 버그 때문에 sticky를 제거했는데, 그 결과 둘 다 고정되지 않는 회귀가 남아있었음.
  `.topbar`에 `position: sticky; top: 0`을 추가하고, `.sidebar`의 sticky `top`을 `.topbar`의
  실제 높이(57px — 기존 코드가 여기저기서 가정하던 53px은 실측과 4px 오차가 있었음)로 맞춰
  헤더 바로 아래에 처음부터 고정 위치로 붙였다. 이제 스크롤해도 튀지 않으면서 헤더/사이드바가
  항상 보인다.

## [1.5.7] - 2026-07-31

가이드 §4 Teams 연동 섹션에 스크린샷 추가, 회의ID 입력란 폭 버그 수정.

### Added
- `/guide` §4 Teams 연동("오늘 예정된 회의", "회의 ID로 직접 참가") 섹션에 스크린샷 2장 추가.

### Fixed
- 회의 ID(10자리) 입력란(`.dial-row .id-input`)이 너비 부족(4.6rem)으로 다 입력해도
  뒷자리가 스크롤되어 보이지 않던 문제 — 스크린샷 캡처 중 발견, 5.5rem으로 확장.

## [1.5.6] - 2026-07-31

가이드 화면에 스크린샷 추가, 제작사 표기 추가.

### Added
- `/guide` 화면에 실제 스크린샷 4장 추가(대시보드 전체·장비 등록 창·장비 카드 아이콘·설정 화면) —
  글로만 설명돼 있어 이해하기 어렵다는 피드백 반영. 시뮬레이터 장비로 실제 데이터를 채운 화면을
  캡처해 사용, 스크린샷은 `app/static/img/guide/`에 보관.
- 설정 화면 하단 버전 표시 옆에 coredxi 로고 + "coredxi 제작" 문구 추가 — 제작사 표기가 화면
  어디에도 없던 것을 보완.

## [1.5.5] - 2026-07-31

2026-07-31 VDI 1차 필드 테스트 3차 피드백 반영.

### Fixed
- 설정 화면의 Teams 테넌트 주소 입력란 플레이스홀더가 사내 실제 도메인
  (`vc.poscodx.com`)이라 이미 저장된 값처럼 보여, 실제로는 비어있는데 채워진
  걸로 착각하기 쉬웠다(같은 문제를 겪는 사용자가 더 있을 수 있다는 피드백). 플레이스홀더를
  예시임이 분명한 값(`vc.example.com`)으로 바꾸고, 비어있으면 경고 문구를 표시하도록
  수정. 플레이스홀더 글자 자체도 기울임체+옅은 색으로 실제 입력값과 뚜렷하게 구분되도록
  CSS를 추가(장비 등록/수정 모달의 테넌트 입력란도 동일하게 수정).
- 설정 화면 하단 버전 표시, FastAPI 앱 타이틀에 남아있던 "Codec Control Center"
  표기를 "BridgeX"로 정리 — 2026-07-31 브랜딩 작업(v1.4.0)에서 누락된 부분.

## [1.5.4] - 2026-07-31

2026-07-31 VDI 1차 필드 테스트 2차 피드백 반영 (Phase③).

### Fixed
- Cisco 코덱 mute/unmute가 두 장비 모두 항상 실패하던 문제. 실장비 응답 원문으로 확인한 결과
  결과 라인 프리픽스가 `"*r AudioMicrophonesMuteResult"`가 아니라 `"*r MicrophonesMuteResult"`
  ("Audio" 없음)였다 — `cisco_driver.py` `_mute_sync`의 기댓값을 실제 값으로 수정.
- Poly 코덱 모델명이 계속 "모델 확인 중..."에 머무르던 문제. `connect()` 시점에 모델 조회를
  1회만 시도하고 실패하면 재연결 전까지 다시 시도하지 않았다 — 모델을 못 얻었으면 폴링마다
  재시도하도록 수정.
- 통화 종료 아이콘이 통화 중이어도 마우스를 올려야만 빨간색으로 보이던 문제 — 통화 중이면
  항상 빨간색으로 표시해 사용자가 바로 인지할 수 있도록 변경.
- 제어 API가 실패해도(예외 없이 `False`만 반환) HTTP 200으로 응답해 프런트엔드가 "완료"
  토스트를 띄우던 문제 — `dashboard.js`가 응답 본문의 `{ok:false}`도 함께 확인하도록 수정.

### Changed
- Poly mute/dial/hangup이 예상 밖 응답을 조용히 `False`로 삼키던 것을, Cisco와 동일하게 응답
  원문을 담은 `DriverCommandError`로 올리도록 변경 — 다음에 비슷한 문제가 생기면 로그에서
  바로 원인을 확인할 수 있다.

## [1.5.3] - 2026-07-31

2026-07-31 VDI 1차 실장비 필드 테스트에서 발견된 버그 2건 수정 (Phase③).

### Fixed
- Cisco 코덱(판교 6층 B회의실)에서 Teams 회의 일정이 하나도 안 잡히던 문제. 실장비
  응답 원문으로 확인한 결과 `xCommand Bookings List` 응답의 모든 줄에
  `"*r BookingsListResult "` 프리픽스가 붙는데(다른 xCommand 결과와 동일한 RoomOS
  컨벤션), 기존 파서는 이를 고려하지 않아 모든 줄을 건너뛰고 있었다. 프리픽스를 제거한
  뒤 파싱하도록 수정(`cisco_driver.py` `_parse_bookings_list`) — List 응답에 Title/
  Time/DialInfo가 이미 다 포함돼 있어 회의별 `Bookings Get` 추가 호출도 필요 없어짐.
  실제 캡처한 응답 원문을 회귀 테스트로 고정.
- Poly 코덱(판교 6층 영상회의실)에서 통화가 끝났는데도 "통화중" 상태가 새로고침해도
  계속 고정되던 문제. 원인은 `PollingScheduler`에 장비별 배타 제어가 없어서 —
  세마포어는 전체 동시 접속 수만 제한할 뿐 "같은 장비"의 중복 폴링은 막지 않았다.
  수동 새로고침(`poll_once`)이 배경 자동 폴링(`_poll_loop`)과 같은 장비의 텔넷/SSH
  연결에 동시에 명령을 보내면 응답 줄이 뒤섞여 상태가 영구적으로 어긋난다. 장비별
  `asyncio.Lock`을 추가해 폴링/제어 동작이 항상 순서대로만 연결을 쓰도록 수정하고,
  제어 API(mute/dial/hangup/reboot/join/direct-dial/calendar/obtp)도 새 `run_with_driver()`
  경로로 전환해 같은 락을 공유하게 했다.

## [1.5.2] - 2026-07-31

배포 exe 파일명을 BridgeX 브랜드에 맞춰 변경, 가이드 화면 스크롤 버그 수정.

### Changed
- `build.spec`의 `EXE(name=...)`를 `CodecControlCenter-vX.Y.Z` → `BridgeX-vX.Y.Z`로 변경.
  내부 레포/프로젝트명(`codec_control_center`)은 그대로 유지 — 사용자에게 보이는 배포 산출물
  이름만 대상. 앱 내장 가이드(`/guide`)가 이미 "BridgeX-vX.Y.Z.exe"로 안내하고 있었는데 실제
  빌드 산출물 이름이 달랐던 불일치를 해소.

### Fixed
- `/guide`처럼 본문이 긴 화면에서 마우스로 스크롤할 때 화면이 튀는 버그. 원인은 `.topbar`가
  `position: sticky`가 아닌 상태에서 사이드바에만 `position: sticky; top: 0`를 걸어둔 것 —
  제거하고 사이드바 "맨 아래" 고정에 필요한 `align-self: flex-start` + 고정 높이만 남김.

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
