# app/drivers/cisco/cisco_commands.py
"""
Cisco RoomOS (Webex Room/Desk/Board, SX/MX 등 xAPI 공통) SSH 명령어 상수.

대상 기종 확정 (2026-07-29, PRD 오픈 이슈 해소): Room Kit, Room Kit Pro,
Room Kit EQ, Room Bar, Room Bar Pro — 전부 RoomOS 통합 xAPI를 사용한다.

근거는 다음 세 곳에서 상호 확인함:
  1) Cisco 공식 RoomOS 문서 소스 (github.com/cisco-ce/roomos.cisco.com,
     doc/TechDocs/xAPI.md — CE 9.14 API Reference Guide 발췌)
     -> 명령/응답 문법, 대소문자 무관, 공백 포함 값은 따옴표 필요, 응답 프리픽스(*s/*c/*r) 확인.
  2) 실제 프로덕션 RoomOS 드라이버 (github.com/PepperDash/epi-videoCodec-ciscoExtended,
     src/CiscoCodec.cs, src/BookingsDataClasses.cs) -> 명령 문자열·JSON 응답 필드명 확인.
  3) Cisco 공식 "Cisco collaboration devices RoomOS 11 API Reference Guide"
     (D15502.02, 2023-02) 전문 — 명령 문법과 일부 응답 예시(Bookings status 등) 확인.

계정 권한(Requires user role) — 위 문서에서 확인됨. 계정 발급 시 최소 USER 역할이
있어야 아래 명령이 전부 동작한다 (권한 부족으로 인한 실패를 예방하려면 계정 설정
단계에서 이 요구사항을 안내할 것):
  - Audio Microphones Mute/Unmute: ADMIN, INTEGRATOR, USER
  - Dial: ADMIN, INTEGRATOR, USER
  - SystemUnit Boot: ADMIN, INTEGRATOR, USER
  - Call Disconnect: 문서에 개별 확인은 못 했으나 다른 통화 제어 명령과 동일하게
    ADMIN/INTEGRATOR/USER 수준일 가능성이 높음 (Phase③ 실장비에서 재확인 권장).
"""

# --- Audio Microphones Mute/Unmute (파라미터 없음) ---
# 확인: PepperDash CiscoCodec.cs PrivacyModeOn/Off
# 결과 라인 프리픽스 확인됨(2026-07-31 VDI 실장비 응답 원문): "*r MicrophonesMuteResult"/
# "*r MicrophonesUnmuteResult" — 명령 자체는 "Audio Microphones"지만 결과 이름에는 "Audio"가
# 안 붙는다(cisco_driver.py `_mute_sync` 참고).
AUDIO_MUTE = "xCommand Audio Microphones Mute"
AUDIO_UNMUTE = "xCommand Audio Microphones Unmute"

# --- Mute 상태 조회 ---
# 확인: xAPI.md Feedback 예제 -> "xStatus Audio Microphones Mute" 응답: "*s Audio Microphones Mute: Off"
STATUS_AUDIO_MUTE = "xStatus Audio Microphones Mute"

# --- Dial ---
# 확인: xAPI.md ("xCommand Dial Number: 123") + CiscoCodec.cs (따옴표 포함 형태)
def dial(number: str) -> str:
    return f'xCommand Dial Number: "{number}"'


# --- Call Disconnect ---
# 확인: xAPI.md Sandbox 튜토리얼("xCommand Call Disconnect", 인자 없이 현재 통화 종료)
#      + CiscoCodec.cs (CallId 지정 형태도 지원)
CALL_DISCONNECT = "xCommand Call Disconnect"


def call_disconnect(call_id: str) -> str:
    return f"xCommand Call Disconnect CallId: {call_id}"


# --- 통화 상태 조회 ---
# 확인: xAPI.md Ghost events 예제 -> "*s Call 2 DisplayName: ...", "*s Call 2 RemoteNumber: ..."
STATUS_CALL = "xStatus Call"

# --- Reboot ---
# 확인: CiscoCodec.cs Reboot() -> "xCommand SystemUnit Boot Action: Restart"
SYSTEMUNIT_BOOT_RESTART = "xCommand SystemUnit Boot Action: Restart"

# --- 캘린더/Bookings 상태 — 완전히 확인됨 ---
# 확인: RoomOS 11 API Reference Guide (D15502.02) p.386 "Bookings status", 응답 예시 포함:
#   xStatus Bookings Availability Status -> *s Bookings Availability Status: Free
#   (값: Free/FreeUntil/BookedUntil)
#   xStatus Bookings Current Id -> *s Bookings Current Id: "123"
STATUS_BOOKINGS_AVAILABILITY = "xStatus Bookings Availability Status"
STATUS_BOOKINGS_CURRENT_ID = "xStatus Bookings Current Id"

# --- Bookings List/Get (OBTP 목록) ---
# 확인(명령 문법): RoomOS 11 API Reference Guide p.257 "xCommand Bookings List"/"xCommand Bookings Get"
#   xCommand Bookings List [Days:] [DayOffset:] [Limit:] [Offset:]
#   xCommand Bookings Get Id:"<meeting id>"
# 확인됨(2026-07-31 VDI 실장비 응답 원문, cisco_driver.py `_parse_bookings_list` 참고):
#   Bookings List 응답은 모든 줄에 "*r BookingsListResult " 프리픽스가 붙고,
#   Title/Time StartTime·EndTime/DialInfo Calls Call 1 Number까지 이미 포함돼 있어
#   회의별 Bookings Get 호출이 필요 없다. 이전에는 이 프리픽스를 고려하지 않은 채
#   "Booking <n> 필드" 형태로만 파싱을 시도해 모든 줄을 건너뛰는 버그가 있었다.
# 미확인: Bookings Get 단독 호출의 정확한 필드 레이아웃(현재 드라이버가 쓰지 않음,
#   List와 동일한 컨벤션일 것으로 추정).
def bookings_list(days: int = 1, day_offset: int = 0) -> str:
    return f"xCommand Bookings List Days: {days} DayOffset: {day_offset}"


def bookings_get(meeting_id: str) -> str:
    return f'xCommand Bookings Get Id: "{meeting_id}"'


# --- SystemUnit 모델/가동시간 — 확인됨 ---
# 확인: Cisco TelePresence xStatus SystemUnit 상태 트리(SX20 Codec Reference Manual에서 실제
# 명령/응답 예시 확인 — RoomOS 계열 전반에서 일관 유지되는 경로).
#   xStatus SystemUnit ProductId -> *s SystemUnit ProductId: "Cisco TelePresence Codec C90"
STATUS_SYSTEMUNIT_PRODUCT_ID = "xStatus SystemUnit ProductId"
#   xStatus SystemUnit Uptime -> *s SystemUnit Uptime: 597095 (부팅 후 경과 초, 정수)
STATUS_SYSTEMUNIT_UPTIME = "xStatus SystemUnit Uptime"
