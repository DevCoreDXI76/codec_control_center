from app.drivers.poly import poly_commands as cmd


def test_mute_near():
    assert cmd.mute_near(True) == "mute near on"
    assert cmd.mute_near(False) == "mute near off"
    assert cmd.MUTE_NEAR_GET == "mute near get"
    assert cmd.MUTE_FAR_GET == "mute far get"


def test_dial_manual():
    assert cmd.dial_manual("5551212") == 'dial manual "384" "5551212"'
    assert cmd.dial_manual("5551212", speed="1920", call_type="sip") == 'dial manual "1920" "5551212" sip'


def test_dial_phone():
    assert cmd.dial_phone("1234") == 'dial phone sip "1234"'
    assert cmd.dial_phone("1234", phone_type="h323") == 'dial phone h323 "1234"'


def test_hangup():
    assert cmd.hangup_video() == "hangup video"
    assert cmd.hangup_video("42") == 'hangup video "42"'
    assert cmd.HANGUP_ALL == "hangup all"


def test_reboot():
    assert cmd.REBOOT_NOW == "reboot now"


def test_callinfo():
    assert cmd.CALLINFO_ALL == "callinfo all"
    assert cmd.callinfo_callid("36") == 'callinfo callid "36"'


def test_calendarstatus():
    assert cmd.CALENDARSTATUS_GET == "calendarstatus get"


def test_calendarmeetings():
    assert cmd.calendarmeetings_list() == 'calendarmeetings list "today"'
    assert (
        cmd.calendarmeetings_list("2026-07-28:00:00", "2026-07-29:00:00")
        == 'calendarmeetings list "2026-07-28:00:00" "2026-07-29:00:00"'
    )
    assert cmd.calendarmeetings_info("abc123") == 'calendarmeetings info "abc123"'
