import tempfile
import unittest
from pathlib import Path
import shutil
import gc

from core.v2.asset_texts import (
    get_asset_transcript_info,
    get_asset_transcript_text,
    resolve_prompt_text_voice_first,
)
from core.v2.assets_sqlite import AssetsSqliteStore


class TestAssetTranscriptSemantics(unittest.TestCase):
    def test_transcript_priority(self):
        text, src = get_asset_transcript_info({"transcript_text": "t1", "prompt_text": "legacy", "note": "n"})
        self.assertEqual(text, "t1")
        self.assertEqual(src, "transcript_text")

    def test_legacy_prompt_fallback(self):
        text, src = get_asset_transcript_info({"prompt_text": "legacy", "note": "n"})
        self.assertEqual(text, "legacy")
        self.assertEqual(src, "prompt_text")

    def test_note_is_not_prompt_source(self):
        text, src = get_asset_transcript_info({"note": "n only"})
        self.assertEqual(text, "")
        self.assertEqual(src, "")
        self.assertEqual(get_asset_transcript_text({"note": "n only"}), "")

    def test_voice_first_resolution_uses_voice_prompt(self):
        text, src = resolve_prompt_text_voice_first(
            "voice_prompt",
            {"transcript_text": "asset_transcript", "prompt_text": "legacy_prompt", "note": "n"},
        )
        self.assertEqual(text, "voice_prompt")
        self.assertEqual(src, "voice.prompt_text")

    def test_voice_first_resolution_fallbacks(self):
        text1, src1 = resolve_prompt_text_voice_first("", {"transcript_text": "asset_transcript", "prompt_text": "legacy_prompt"})
        self.assertEqual(text1, "asset_transcript")
        self.assertEqual(src1, "asset.transcript_text")

        text2, src2 = resolve_prompt_text_voice_first("", {"prompt_text": "legacy_prompt", "note": "n"})
        self.assertEqual(text2, "legacy_prompt")
        self.assertEqual(src2, "asset.prompt_text")

    def test_assets_store_keeps_transcript_when_note_changes(self):
        tmp = tempfile.mkdtemp(prefix="asset_transcript_")
        try:
            db_path = str(Path(tmp) / "assets.sqlite3")
            store = AssetsSqliteStore(db_path)
            store.upsert(
                {
                    "asset_id": "ref_test",
                    "kind": "ref",
                    "filename": "x.wav",
                    "path": str(Path(tmp) / "x.wav"),
                    "size": 1,
                    "created_at": 1,
                    "note": "old note",
                    "transcript_text": "hello world",
                    "linked": 1,
                }
            )
            before = store.get("ref_test")
            self.assertEqual((before or {}).get("transcript_text"), "hello world")

            updated = dict(before or {})
            updated["note"] = "new note"
            store.upsert(updated)
            after = store.get("ref_test")
            self.assertEqual((after or {}).get("note"), "new note")
            self.assertEqual((after or {}).get("transcript_text"), "hello world")
            del store
            gc.collect()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
