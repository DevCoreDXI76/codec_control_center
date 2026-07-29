from app.drivers.cisco import cisco_commands as cmd


def test_mute_unmute():
    assert cmd.AUDIO_MUTE == "xCommand Audio Microphones Mute"
    assert cmd.AUDIO_UNMUTE == "xCommand Audio Microphones Unmute"
    assert cmd.STATUS_AUDIO_MUTE == "xStatus Audio Microphones Mute"


def test_dial():
    assert cmd.dial("1234@example.com") == 'xCommand Dial Number: "1234@example.com"'


def test_call_disconnect():
    assert cmd.CALL_DISCONNECT == "xCommand Call Disconnect"
    assert cmd.call_disconnect("27") == "xCommand Call Disconnect CallId: 27"


def test_status_call():
    assert cmd.STATUS_CALL == "xStatus Call"


def test_reboot():
    assert cmd.SYSTEMUNIT_BOOT_RESTART == "xCommand SystemUnit Boot Action: Restart"


def test_bookings_list():
    assert cmd.bookings_list() == "xCommand Bookings List Days: 1 DayOffset: 0"
    assert cmd.bookings_list(days=7, day_offset=1) == "xCommand Bookings List Days: 7 DayOffset: 1"


def test_bookings_get():
    assert cmd.bookings_get("meeting-001") == 'xCommand Bookings Get Id: "meeting-001"'


def test_bookings_availability_status():
    assert cmd.STATUS_BOOKINGS_AVAILABILITY == "xStatus Bookings Availability Status"
    assert cmd.STATUS_BOOKINGS_CURRENT_ID == "xStatus Bookings Current Id"
