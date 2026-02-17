# P4-M4 Final Acceptance Report (2026-02-11)

## Scope
- Complete M4: configuration single-source of truth for voices.
- Enforce legacy config write protection at runtime.
- Keep `/api/v2/voices` CRUD persistent and restart-consistent.
- Execute final acceptance validation.

## Implemented Changes

### 1) Runtime voices single-source store integrated
- Added `core/storage/voices_file.py` (`VoicesFileStore`):
  - thread-safe in-memory store
  - schema normalization (`name/character/emotion/selection_policy/ref_asset_ids`)
  - atomic JSON persistence (`tmp + os.replace`)
  - legacy runtime write protection (`config/config.json`, `config/voice_config.json`)
- Exported in `core/storage/__init__.py`.

### 2) `api_legacy.py` M4 wiring
- `CharacterConfig` now delegates to `VoicesFileStore` (single source file).
- Added `_resolve_default_voices_config_path()`:
  - priority: `app_config.json:v2_voices_config_path` -> `config/super_agent.json` -> `config/voices_v2.json`
- Added legacy import hint when v2 voices is empty but legacy files exist.
- `/api/v2/health` now returns `voices_config_path`.
- CLI `--config` default switched to `_resolve_default_voices_config_path()`.

### 3) Stability cleanup
- Repaired `core/api_legacy.py` broken syntax (legacy encoding-damaged literals/docstrings).
- Replaced inference mode parsing with normalized, robust implementation:
  - `zero_shot`, `reference_timbre`, `instruction`, `fine_grained`
  - supports stream path and speed-change path.

### 4) M4 test additions
- Added `tests/test_voices_store_m4.py`:
  - normalization/roundtrip
  - atomic save temp cleanup
  - legacy write-protect default
  - explicit legacy write override
- Added `scripts/m4_final_acceptance_test.py`:
  - `/api/v2/voices` create/update/reload/delete persistence
  - restart consistency
  - legacy write protection through API surface

## Final Acceptance Results

### Command Checks
1. `python -m py_compile core/api_legacy.py core/storage/voices_file.py tests/test_voices_store_m4.py scripts/m4_final_acceptance_test.py`
   - PASS
2. `python -m unittest discover -s tests -p "test_*.py"`
   - PASS (`Ran 16 tests`)
3. `python scripts/m4_final_acceptance_test.py`
   - PASS (`M4 final acceptance test: OK`)
4. `python scripts/p2_backend_acceptance_test.py`
   - PASS (`P2 backend acceptance test: OK`)
5. `python core/api.py --help`
   - PASS (CLI starts and prints updated `--config` default help)

## Acceptance Conclusion
- M4 completed and accepted:
  - voices runtime source is single-file (`v2_voices_config_path`)
  - legacy runtime write path is blocked by default
  - voices CRUD persistence and reload/restart consistency validated
  - baseline P2 acceptance remains green
