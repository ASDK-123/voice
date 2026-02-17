import os
import tempfile
import threading
import unittest

from core.synthesis.engine import run_synthesis


class _FakeCache:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="engine_cache_test_")
        self._store = {}
        self._inflight = set()
        self._force_conflict = set()
        self._wait_hook = None

    def cleanup(self):
        self._tmp.cleanup()

    def _path_for(self, key: str) -> str:
        return os.path.join(self._tmp.name, f"{key}.wav")

    def get_path(self, request_hash: str):
        return self._store.get(request_hash)

    def put_bytes(self, request_hash: str, wav_bytes: bytes, meta=None):
        p = self._path_for(request_hash)
        with open(p, "wb") as f:
            f.write(wav_bytes)
        self._store[request_hash] = p
        return p

    def begin_inflight(self, request_hash: str) -> bool:
        if request_hash in self._force_conflict:
            return False
        if request_hash in self._inflight:
            return False
        self._inflight.add(request_hash)
        return True

    def wait_inflight(self, request_hash: str, timeout_ms: int) -> bool:
        if callable(self._wait_hook):
            self._wait_hook(request_hash, timeout_ms)
        return True

    def end_inflight(self, request_hash: str) -> None:
        self._inflight.discard(request_hash)


class TestSynthesisEngineCache(unittest.TestCase):
    def setUp(self):
        self.cache = _FakeCache()
        self.metrics = {"cache_hit": 0, "cache_miss": 0}
        self.metrics_lock = threading.Lock()
        self.calls = {"run_sync": 0}

    def tearDown(self):
        self.cache.cleanup()

    @staticmethod
    def _prepare(req):
        return {"name": "Alice#default"}

    @staticmethod
    def _compute(req, cfg, part_index):
        return "k1", dict(req or {}), "ref_1"

    def _run_sync(self, req_norm, cfg):
        self.calls["run_sync"] += 1
        return b"RIFF_ENGINE_WAV", cfg

    def test_cache_miss_then_hit(self):
        r1 = run_synthesis(
            {"text": "hello"},
            prepare_char_config=self._prepare,
            compute_cache_key=self._compute,
            run_sync_synthesis=self._run_sync,
            cache=self.cache,
            metrics=self.metrics,
            metrics_lock=self.metrics_lock,
            sync_wait_ms=0,
        )
        self.assertFalse(r1.cache_hit)
        self.assertEqual(r1.cache_key, "k1")
        self.assertEqual(self.calls["run_sync"], 1)
        self.assertEqual(r1.wav_bytes, b"RIFF_ENGINE_WAV")

        r2 = run_synthesis(
            {"text": "hello"},
            prepare_char_config=self._prepare,
            compute_cache_key=self._compute,
            run_sync_synthesis=self._run_sync,
            cache=self.cache,
            metrics=self.metrics,
            metrics_lock=self.metrics_lock,
            sync_wait_ms=0,
        )
        self.assertTrue(r2.cache_hit)
        self.assertEqual(r2.cache_key, "k1")
        self.assertEqual(self.calls["run_sync"], 1)
        self.assertEqual(r2.wav_bytes, b"RIFF_ENGINE_WAV")
        self.assertEqual(self.metrics["cache_miss"], 1)
        self.assertEqual(self.metrics["cache_hit"], 1)

    def test_inflight_wait_hits_cache(self):
        self.cache._force_conflict.add("k1")

        def _wait_hook(request_hash, _timeout_ms):
            self.cache.put_bytes(request_hash, b"RIFF_AFTER_WAIT", meta={})

        self.cache._wait_hook = _wait_hook

        r = run_synthesis(
            {"text": "hello"},
            prepare_char_config=self._prepare,
            compute_cache_key=self._compute,
            run_sync_synthesis=self._run_sync,
            cache=self.cache,
            metrics=self.metrics,
            metrics_lock=self.metrics_lock,
            sync_wait_ms=100,
            wait_inflight_on_conflict=True,
        )
        self.assertTrue(r.cache_hit)
        self.assertEqual(r.wav_bytes, b"RIFF_AFTER_WAIT")
        self.assertEqual(self.calls["run_sync"], 0)
        self.assertEqual(self.metrics["cache_miss"], 1)
        self.assertEqual(self.metrics["cache_hit"], 1)


if __name__ == "__main__":
    unittest.main()
