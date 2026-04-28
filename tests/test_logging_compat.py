from __future__ import annotations

from core.logging.compat import event_to_legacy_text, legacy_line_to_event, parse_legacy_level, strip_legacy_prefix


def test_parse_legacy_level():
    assert parse_legacy_level("[ERROR] boom") == "ERROR"
    assert parse_legacy_level("[warn] x") == "WARNING"
    assert parse_legacy_level("plain text") == "INFO"


def test_strip_legacy_prefix():
    assert strip_legacy_prefix("[INFO] hello") == "hello"
    assert strip_legacy_prefix("[WARNING] world") == "world"


def test_legacy_line_to_event():
    evt = legacy_line_to_event("[WARN] 测试", module="api", session_id="sess_a")
    d = evt.to_dict()
    assert d["event"] == "LEGACY_LOG"
    assert d["module"] == "api"
    assert d["msg_zh"] == "测试"
    assert d["level"] == "WARNING"


def test_event_to_legacy_text():
    txt = event_to_legacy_text({"level": "INFO", "module": "ui.main", "msg_zh": "启动"})
    assert "[INFO][ui.main] 启动" == txt

