# P4 C1-C6 Execution Report (2026-02-11)

## Scope
- Execute checklist: `docs/archive/2026-02-11/P4_C1_C6_EXECUTABLE_CHECKLIST_2026-02-11.md`
- Goal: complete C1-C6 with verifiable gates (`Build -> Test -> Smoke -> Report`)

## Final Status
1. C1: Completed
2. C2: Completed
3. C3: Completed
4. C4: Completed (worker local path now engine-first with fallback)
5. C5: Completed (single-source voices and legacy write protection verified)
6. C6: Completed (strict acceptance report generated)

## Key Implementations

### C1 (Startup chain de-legacy)
- `core/server/main.py`
  - Removed `runpy.run_module(...)` bootstrap
  - Uses explicit runtime chain: parse args -> resolve config -> initialize runtime -> build context -> create app -> run
- `core/server/ctx.py`
  - Explicit `AppContext` with runtime inputs
- `core/server/app.py`
  - Explicit `create_app(ctx)` entry
- `core/api_legacy.py`
  - Extracted startup functions: `build_arg_parser`, `resolve_config_file`, `initialize_runtime`, `run_server`, `main`

### C2 (v2 misc extraction)
- `core/server/routes_v2_misc.py`
  - Owns concrete logic for `/health`, `/api/v2/health`, `/metrics`, `/api/v2/metrics`, `/api/v2/synthesize`
- `core/api_legacy.py`
  - Keeps registration/context injection, removes duplicate v2 misc route bodies

### C3 (normalization unification)
- `core/synthesis/normalize.py`
  - Added `clean_text_for_inference`, `normalize_inference_mode`
- `core/synthesis/__init__.py`
  - Exported new normalization APIs
- `core/api_legacy.py`, `core/worker.py`
  - Unified to synthesis normalization entry points
- Tests updated:
  - `tests/test_synthesis_normalization.py`
  - `tests/test_synthesis_key_parity.py`

### C4 (one engine, multi-entry)
- `core/api_legacy.py`
  - v1 `/` and `/api/tts` now execute through `_v2_run_engine` path
- `core/worker.py`
  - Added engine-first local worker path using `_syn_run_synthesis`
  - Added env gate: `WORKER_USE_SYNTHESIS_ENGINE` (default on)
  - Added legacy fallback path for robustness and rollback safety

### C5 (single source configuration)
- `core/storage/voices_file.py`
  - Runtime single-source voices store
  - Legacy write protection at runtime
- `core/api_legacy.py`, `ui/api_page.py`, `ui/main_window.py`
  - Continued single-source `v2_voices_config_path` route
- `scripts/import_legacy_voice_config_to_v2.py`
  - Kept as migration-only entry

### C6 (final acceptance packaging)
- Added strict acceptance doc:
  - `P4_STRICT_FINAL_ACCEPTANCE_REPORT_2026-02-11.md`
- Updated project docs with status pointers:
  - `README.md`
  - `PROJECT_OVERVIEW.md`

## Gate Results (Latest)

### Build
- `python -m py_compile core\api.py core\server\main.py core\server\app.py core\server\ctx.py core\server\routes_v2_misc.py core\api_legacy.py core\worker.py core\synthesis\normalize.py core\synthesis\engine.py tests\test_synthesis_engine_cache.py tests\test_synthesis_engine_errors.py tests\test_synthesis_normalization.py tests\test_synthesis_key_parity.py tests\test_voices_store_m4.py scripts\p2_backend_acceptance_test.py scripts\m4_final_acceptance_test.py`
- Result: PASS

### Test
- `python -m unittest tests\test_synthesis_engine_cache.py` -> PASS
- `python -m unittest tests\test_synthesis_engine_errors.py` -> PASS
- `python -m unittest tests\test_synthesis_normalization.py` -> PASS
- `python -m unittest tests\test_synthesis_key_parity.py` -> PASS
- `python -m unittest tests\test_voices_store_m4.py` -> PASS
- `python -m unittest discover -s tests -p "test_*.py"` -> PASS (`Ran 17 tests`)

### Smoke
- `python scripts\p2_backend_acceptance_test.py` -> PASS (`P2 backend acceptance test: OK`)
- `python scripts\m4_final_acceptance_test.py` -> PASS (`M4 final acceptance test: OK`)
- `python core\api.py --help` -> PASS

## Acceptance Conclusion
- P4 C1-C6 checklist is now executed to completion.
- Final verdict: **STRICT PASS**.


## Post-Acceptance Archival (2026-02-11)
- Archived historical planning/review/design docs into `docs/archive/2026-02-11/`.
- Moved deprecated runtime-adjacent files into `deprecated/`:
  - `deprecated/bridge_draft.py`
  - `deprecated/bridge_requirements.txt`
- Moved manual benchmark scripts into `scripts/benchmarks/`:
  - `scripts/benchmarks/api_stress_test.py`
  - `scripts/benchmarks/latency_test.py`
- Added index/readme files:
  - `docs/archive/2026-02-11/ARCHIVE_INDEX.md`
  - `deprecated/README.md`
  - `scripts/benchmarks/README.md`
- Updated checklist path references in:
  - `README.md`
  - `PROJECT_OVERVIEW.md`
  - `P4_C1_C6_EXECUTION_REPORT_2026-02-11.md`
