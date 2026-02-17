# P4 Strict Final Acceptance Report (2026-02-11)

## Verdict
**STRICT PASS**

## Evidence Chain

### C1 Evidence
- No runpy bootstrap in server startup path
- Explicit runtime assembly via:
  - `core/server/main.py`
  - `core/server/ctx.py`
  - `core/server/app.py`

### C2 Evidence
- v2 misc routes implemented in:
  - `core/server/routes_v2_misc.py`
- Legacy duplicate v2 misc logic removed from primary route bodies in:
  - `core/api_legacy.py`

### C3 Evidence
- Unified normalization source:
  - `core/synthesis/normalize.py`
- API/worker aligned with synthesis normalization:
  - `core/api_legacy.py`
  - `core/worker.py`

### C4 Evidence
- Unified engine entry used by v1/v2 and worker:
  - `core/synthesis/engine.py`
  - `core/api_legacy.py` (route -> `_v2_run_engine`)
  - `core/worker.py` (`_run_segment_with_engine`, default enabled)
- Worker keeps rollback-safe fallback path:
  - `_run_segment_legacy`
  - `WORKER_USE_SYNTHESIS_ENGINE`

### C5 Evidence
- Single-source voices enforcement:
  - `core/storage/voices_file.py`
- Migration-only legacy route retained:
  - `scripts/import_legacy_voice_config_to_v2.py`
- UI/API single-source path references:
  - `ui/api_page.py`
  - `ui/main_window.py`
  - `core/api_legacy.py`

### C6 Evidence
- Full gate command set executed and passed
- Execution report updated:
  - `P4_C1_C6_EXECUTION_REPORT_2026-02-11.md`

## Gate Logs (Summary)
1. Build: PASS
   - `python -m py_compile ...`
2. Unit tests: PASS
   - `python -m unittest discover -s tests -p "test_*.py"`
   - Result: `Ran 17 tests, OK`
3. Product acceptance smoke: PASS
   - `python scripts/p2_backend_acceptance_test.py` -> `P2 backend acceptance test: OK`
   - `python scripts/m4_final_acceptance_test.py` -> `M4 final acceptance test: OK`
4. CLI smoke: PASS
   - `python core/api.py --help`

## Residual Risk Register
1. Worker engine path currently returns one merged output per segment in engine mode.
   - Impact: low-to-medium for extremely rare multi-part local generator patterns.
   - Mitigation: legacy fallback path remains available and tested.
2. Historical encoding noise exists in some old comments/strings.
   - Impact: low for runtime, medium for readability.
   - Mitigation: incrementally sanitize files during next maintenance cycle.

## Rollback SOP
1. Disable worker engine path quickly:
   - set environment variable `WORKER_USE_SYNTHESIS_ENGINE=false`
2. If route behavior regresses:
   - rollback `core/api_legacy.py` route-to-engine binding commit
3. If single-source voice behavior regresses:
   - rollback `core/storage/voices_file.py` integration while keeping migration scripts

## Release Recommendation
- Can proceed to production rollout with staged monitoring.
- Recommended canary window: 24h with focus on:
  - `/api/v2/synthesize` success rate
  - cache hit ratio
  - worker fallback frequency
