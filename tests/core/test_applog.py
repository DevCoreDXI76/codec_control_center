from app.core.applog import tail_app_log


def test_tail_app_log_missing_file_returns_empty(tmp_path):
    result = tail_app_log(tmp_path / "app.log")
    assert result == []


def test_tail_app_log_returns_all_lines_newest_first_when_under_limit(tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert tail_app_log(log_path, n=300) == ["line3", "line2", "line1"]


def test_tail_app_log_truncates_to_last_n_lines(tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
    result = tail_app_log(log_path, n=3)
    assert result == ["line10", "line9", "line8"]
