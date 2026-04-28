from __future__ import annotations

import pytest

from core.logging.schema import LogEventV1
from core.v2.errors import AppError


def test_log_event_schema_success():
    evt = LogEventV1.create(
        level="info",
        module="ui.main",
        event="UI_CLICK_SYNTH",
        session_id="sess_x",
        msg_zh="用户点击一键运行",
        fields={"voice_id": "胡桃#default", "text_len": 12},
    )
    d = evt.to_dict()
    assert d["event"] == "UI_CLICK_SYNTH"
    assert d["level"] == "INFO"
    assert d["fields"]["voice_id"] == "胡桃#default"


def test_log_event_schema_missing_required_fields():
    with pytest.raises(ValueError):
        LogEventV1.create(
            level="INFO",
            module="api",
            event="API_REQ_FAIL",
            fields={"status": 500, "error_code": "x"},
        )


def test_log_event_schema_bad_event_prefix():
    with pytest.raises(ValueError):
        LogEventV1.create(level="INFO", module="x", event="bad_event", fields={})


def test_app_error_contains_optional_message_zh():
    err = AppError(code="invalid_request", message="invalid", message_zh="请求无效", status=400)
    d = err.to_dict()
    assert d["error"]["message_zh"] == "请求无效"
