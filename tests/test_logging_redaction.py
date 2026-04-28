from __future__ import annotations

from core.logging.redaction import redact_fields, redact_headers, redact_path, redact_text


def test_redact_text_summary():
    out = redact_text("a" * 200, max_preview=20)
    assert out["text_len"] == 200
    assert out["text_preview"].endswith("...")
    assert len(out["text_sha1"]) == 40


def test_redact_path_default():
    p = r"C:\Users\lilei\Desktop\voice\data\assets\audio\ref_x.wav"
    out = redact_path(p)
    assert out.endswith("/audio/ref_x.wav")
    assert out.startswith("...")


def test_redact_headers_allowlist_and_mask():
    out = redact_headers(
        {
            "Authorization": "Bearer abcdefghijklmn",
            "X-Request-Id": "req_x",
            "X-Secret-Thing": "hello",
        }
    )
    assert out["X-Request-Id"] == "req_x"
    assert out["X-Secret-Thing"] == "***"
    assert "*" in out["Authorization"]


def test_redact_fields_nested():
    out = redact_fields(
        {
            "text": "这是一个很长很长的文本内容",
            "file_path": r"C:\a\b\c.wav",
            "api_key": "abcdef0123456789",
            "headers": {"Authorization": "Bearer xxx"},
            "nested": {"prompt_text": "abc"},
        }
    )
    assert "text_preview" in out["text"]
    assert out["file_path"].startswith("...")
    assert "*" in out["api_key"]
    assert out["headers"]["Authorization"] != "Bearer xxx"
    assert "text_preview" in out["nested"]["prompt_text"]

