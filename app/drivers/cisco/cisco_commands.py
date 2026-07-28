# app/drivers/cisco/cisco_commands.py
"""
Cisco RoomOS (Webex Room/Desk/Board, SX/MX 등 xAPI 공통) SSH 명령어 상수.

대상 정확한 기종은 아직 미확정 (PRD 오픈 이슈 — Phase⑤ 착수 전 확정 필요).
아래는 RoomOS 전반에서 공통인 "System Commands" 수준 xAPI만 사용하며,
근거는 다음 두 곳에서 상호 확인함:
  1) Cisco 공식 RoomOS 문서 소스 (github.com/cisco-ce/roomos.cisco.com,
     doc/TechDocs/xAPI.md — CE 9.14 API Reference Guide 발췌)
     -> 명령/응답 문법, 대소문자 무관, 공백 포함 값은 따옴표 필요, 응답 프리픽스(*s/*c/*r) 확인.
  2) 실제 프로덕션 RoomOS 드라이버 (github.com/PepperDash/epi-videoCodec-ciscoExtended,
     src/CiscoCodec.cs) -> 아래 각 명령의 정확한 문자열 확인.
모델별로 다를 수 있는 심화 기능(Bookings List 응답 스키마 등)은 여기 포함하지 않는다 —
Phase④/⑤에서 대상 모델 확정 후 문서 재확인 필요.
"""

# --- Audio Microphones Mute/Unmute (파라미터 없음) ---
# 확인: PepperDash CiscoCodec.cs PrivacyModeOn/Off
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

# --- Bookings (OBTP) — 명령/파라미터만 확인, 응답 스키마는 모델 확정 후 재확인 필요 ---
# 확인: BookingsWorkspaceIntegration.md(xCommand.Bookings.List 존재) + CiscoCodec.cs
#      ("xCommand Bookings List Days: 1 DayOffset: 0")
def bookings_list(days: int = 1, day_offset: int = 0) -> str:
    return f"xCommand Bookings List Days: {days} DayOffset: {day_offset}"
