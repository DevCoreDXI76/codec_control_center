# app/drivers/poly/poly_commands.py
"""
Poly (Polycom RealPresence Group Series) Telnet/SSH API 명령어 상수.

근거 문서: Polycom RealPresence Group Series Integrator Reference Guide
(RS-232 / Telnet(23,24) / SSH API, "System Commands" 챕터).
각 명령 옆 주석의 페이지 번호는 해당 가이드 기준.
문서에 없는 명령은 절대 추측하지 않는다 — 필요 시 문서 재확인 후 추가.
"""

# --- mute (p.273) ---
# Syntax: mute <register|unregister> / mute near <get|on|off|toggle> / mute far get
MUTE_REGISTER = "mute register"
MUTE_UNREGISTER = "mute unregister"
MUTE_NEAR_GET = "mute near get"
MUTE_NEAR_ON = "mute near on"
MUTE_NEAR_OFF = "mute near off"
MUTE_FAR_GET = "mute far get"


def mute_near(on: bool) -> str:
    return MUTE_NEAR_ON if on else MUTE_NEAR_OFF


# --- dial (p.173-175) ---
# Syntax: dial manual "speed" "dialstr1" [h323|ip|sip]
#         dial phone <sip|h323|auto|sip_speakerphone> "dialstring"
def dial_manual(dialstr: str, speed: str = "384", call_type: str | None = None) -> str:
    base = f'dial manual "{speed}" "{dialstr}"'
    return f"{base} {call_type}" if call_type else base


def dial_phone(dialstring: str, phone_type: str = "sip") -> str:
    return f'dial phone {phone_type} "{dialstring}"'


# --- hangup (p.235) ---
# Syntax: hangup video ["callid"] / hangup all
HANGUP_ALL = "hangup all"


def hangup_video(call_id: str | None = None) -> str:
    return f'hangup video "{call_id}"' if call_id else "hangup video"


# --- reboot (p.302) ---
# Syntax: reboot [now]  (가이드 권장 형식: reboot now)
REBOOT_NOW = "reboot now"

# --- callinfo (p.148) — 통화 상태 조회 (polling, 세션 유지) ---
# Syntax: callinfo all / callinfo callid "callid"
CALLINFO_ALL = "callinfo all"


def callinfo_callid(call_id: str) -> str:
    return f'callinfo callid "{call_id}"'


# --- calendarstatus (p.146) — Exchange 캘린더 연동 상태 ---
# Syntax: calendarstatus get
# 응답: "calendarstatus established" | "calendarstatus unavailable"
CALENDARSTATUS_GET = "calendarstatus get"

# --- calendarmeetings (p.134-136) — OBTP 예정 회의 조회 ---
# Syntax: calendarmeetings list "starttime" ["endtime"]
#         calendarmeetings info "meetingid"
# 시간 형식: YYYY-MM-DD:HH:MM | today[:HH:MM] | tomorrow[:HH:MM]


def calendarmeetings_list(start_time: str = "today", end_time: str | None = None) -> str:
    if end_time:
        return f'calendarmeetings list "{start_time}" "{end_time}"'
    return f'calendarmeetings list "{start_time}"'


def calendarmeetings_info(meeting_id: str) -> str:
    return f'calendarmeetings info "{meeting_id}"'


# --- systemsetting model / uptime — 확인됨 (Integrator Reference Guide p.352, p.372) ---
# systemsetting get model -> 응답: systemsetting model "RealPresence Group 700"
SYSTEMSETTING_GET_MODEL = "systemsetting get model"
# uptime get -> 응답: "1 Hour, 10 Minutes" (사람이 읽는 문자열, 명령어 자체가 최상위 커맨드)
UPTIME_GET = "uptime get"
