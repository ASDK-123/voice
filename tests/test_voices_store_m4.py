import json
import os
import tempfile
import unittest

from core.storage import VoicesFileStore


class TestVoicesFileStoreM4(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="voices_store_m4_")
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _path(self, *parts):
        return os.path.join(self.root, *parts)

    def test_roundtrip_and_normalize(self):
        voices_path = self._path("config", "voices_v2.json")
        store = VoicesFileStore(voices_path)

        store.upsert_voice(
            {
                "name": "Tom",
                "prompt_text": "hello",
                "ref_asset_ids": "bad_type",
            }
        )
        store.save()

        store2 = VoicesFileStore(voices_path)
        items = store2.list_voices()
        self.assertEqual(len(items), 1)
        v = items[0]
        self.assertEqual(v["name"], "Tom#default")
        self.assertEqual(v["character"], "Tom")
        self.assertEqual(v["emotion"], "default")
        self.assertEqual(v["selection_policy"], "random_per_text")
        self.assertEqual(v["ref_asset_ids"], [])

        cfg_dir = os.path.dirname(voices_path)
        leftovers = [x for x in os.listdir(cfg_dir) if ".tmp_" in x]
        self.assertEqual(leftovers, [])

    def test_name_from_character_and_emotion(self):
        voices_path = self._path("config", "voices_v2.json")
        store = VoicesFileStore(voices_path)
        saved = store.upsert_voice({"character": "Alice", "emotion": "calm"})
        self.assertEqual(saved["name"], "Alice#calm")

    def test_legacy_write_protected_by_default(self):
        legacy_path = self._path("config", "config.json")
        os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump([{"name": "Old#default"}], f, ensure_ascii=False, indent=2)

        store = VoicesFileStore(legacy_path, allow_legacy_write=False)
        with self.assertRaises(RuntimeError):
            store.upsert_voice({"name": "Blocked#default"})
        with self.assertRaises(RuntimeError):
            store.delete_voice("Old#default")
        with self.assertRaises(RuntimeError):
            store.save()

    def test_legacy_write_can_be_explicitly_enabled(self):
        legacy_path = self._path("config", "voice_config.json")
        os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

        store = VoicesFileStore(legacy_path, allow_legacy_write=True)
        store.upsert_voice({"name": "Allowed#default"})
        store.save()

        with open(legacy_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Allowed#default")


if __name__ == "__main__":
    unittest.main()
