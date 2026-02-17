import tempfile
import unittest

from core.synthesis.engine import run_synthesis


class _FakeCache:
    def __init__(self, owner: bool):
        self.owner = owner
        self.end_calls = 0
        self.tmp = tempfile.TemporaryDirectory(prefix="engine_err_test_")

    def cleanup(self):
        self.tmp.cleanup()

    def get_path(self, request_hash: str):
        return None

    def put_bytes(self, request_hash: str, wav_bytes: bytes, meta=None):
        return None

    def begin_inflight(self, request_hash: str) -> bool:
        return bool(self.owner)

    def wait_inflight(self, request_hash: str, timeout_ms: int) -> bool:
        return False

    def end_inflight(self, request_hash: str) -> None:
        self.end_calls += 1


class TestSynthesisEngineErrors(unittest.TestCase):
    @staticmethod
    def _prepare(req):
        return {"name": "Alice#default"}

    @staticmethod
    def _compute_error(req, cfg, part_index):
        raise ValueError("bad request")

    @staticmethod
    def _compute_ok(req, cfg, part_index):
        return "k_err", dict(req or {}), ""

    @staticmethod
    def _run_sync_error(req_norm, cfg):
        raise RuntimeError("model failed")

    def test_compute_cache_key_error_passthrough(self):
        cache = _FakeCache(owner=True)
        try:
            with self.assertRaises(ValueError):
                run_synthesis(
                    {"text": "hello"},
                    prepare_char_config=self._prepare,
                    compute_cache_key=self._compute_error,
                    run_sync_synthesis=self._run_sync_error,
                    cache=cache,
                )
        finally:
            cache.cleanup()

    def test_end_inflight_only_when_owner(self):
        cache_owner = _FakeCache(owner=True)
        try:
            with self.assertRaises(RuntimeError):
                run_synthesis(
                    {"text": "hello"},
                    prepare_char_config=self._prepare,
                    compute_cache_key=self._compute_ok,
                    run_sync_synthesis=self._run_sync_error,
                    cache=cache_owner,
                    sync_wait_ms=0,
                    wait_inflight_on_conflict=True,
                )
            self.assertEqual(cache_owner.end_calls, 1)
        finally:
            cache_owner.cleanup()

        cache_non_owner = _FakeCache(owner=False)
        try:
            with self.assertRaises(RuntimeError):
                run_synthesis(
                    {"text": "hello"},
                    prepare_char_config=self._prepare,
                    compute_cache_key=self._compute_ok,
                    run_sync_synthesis=self._run_sync_error,
                    cache=cache_non_owner,
                    sync_wait_ms=0,
                    wait_inflight_on_conflict=True,
                )
            self.assertEqual(cache_non_owner.end_calls, 0)
        finally:
            cache_non_owner.cleanup()


if __name__ == "__main__":
    unittest.main()
