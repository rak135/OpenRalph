# Phase 3 Implementation Report

**Repository:** `C:\DATA\PROJECTS\OpenRalph` (Python rewrite of OpenRalph_source)  
**Date:** 2026-04-23  
**Test baseline entering Phase 3:** 49 tests, all passing  
**Test count after Phase 3:** 97 tests, all passing

---

## 1. Executive Summary

Phase 3 added three cohesive capabilities to the Python OpenRalph loop:

1. **Bounded text result contract** — workers must emit a `<ralph-result>` XML-like block; a deterministic local parser reads it and classifies every iteration's output as trusted or untrusted, with no reliance on vendor-native JSON.
2. **Multi-iteration control** — `run_loop()` orchestrates N iterations against a single workspace, stopping on `ALL_COMPLETE`, `MAX_ITERATIONS`, `NO_TASKS`, `ALREADY_COMPLETE`, `LOCK_CONFLICT`, or `ADAPTER_ERROR`.
3. **Session / lock discipline** — each `run_loop()` call acquires a PID-based workspace lock, generates a UUID session identifier, and persists `stop_reason` and `session_id` to `.ralph-state.json`. Concurrent invocations are rejected immediately (exit 3).

No TUI, GUI, PTY, memory system, planner redesign, multi-agent, or verifier agent work was undertaken.

---

## 2. What Was Learned From OpenRalph_source for Phase 3

`OpenRalph_source` (TypeScript/Bun reference) taught four specific patterns applied here:

| Source pattern | File in source | Applied in Python port |
|---|---|---|
| PID-based lock file (`.ralph-lock`) | `src/lib/lock.ts` | `workspace.py` — `Lock` dataclass + `acquire_lock()` |
| `.ralph-done` lifecycle marker | `src/state.ts` | `workspace.py` — `done_path` already existed; Phase 3 respects it |
| Session UUID per `run_loop` call | `src/loop.ts` — `sessionId` | `loop.py` — `session_id = str(uuid.uuid4())` at loop start |
| Output parser over PTY/SSE stream | `src/lib/output-parser.ts` | `result_contract.py` — regex over captured stdout (no PTY needed) |

Key divergence: the source uses SSE/PTY streaming and parses events as they arrive.  The Python port captures the full stdout of a subprocess in one shot and applies a single-pass regex.  The semantics are equivalent for the stop-reason and completion-confidence use cases.

---

## 3. Architectural Changes Made

### New files

| File | Purpose |
|---|---|
| `src/openralph_py/result_contract.py` | Bounded text block definition, deterministic parser, `WorkerResult` union type |
| `tests/test_result_contract.py` | 24 unit tests for the parser |
| `tests/test_phase3_loop.py` | 24 integration tests for multi-iteration loop, locks, confidence levels |

### Modified files

| File | Change summary |
|---|---|
| `src/openralph_py/workspace.py` | Added `LOCK_FILE`, `Lock` dataclass (context manager), `acquire_lock()`, updated `DEFAULT_PROMPT_TEMPLATE` with Rule 6 (`<ralph-result>` block instruction), Windows-safe `_is_process_running()` |
| `src/openralph_py/state.py` | Added `last_stop_reason: str \| None` and `session_id: str \| None` fields to `PersistedState` |
| `src/openralph_py/progress.py` | Extended `append_iteration_entry()` with `result_confidence` and `result_summary` kwargs |
| `src/openralph_py/loop.py` | Added `StopReason` enum, `LoopSummary` dataclass, extended `IterationOutcome` with `parsed_result` + `completion_confidence`, added `run_loop()` function |
| `src/openralph_py/cli.py` | Added `--max-iterations` flag to `run` subcommand; routes to `run_loop()` when non-default; exit codes 0/1/2/3 |

---

## 4. Bounded Text Contract: Design and Implementation

### Why bounded text over vendor-native JSON

Vendor CLIs differ:
- Codex 0.121.0: `--json` flag produces JSONL with internal event schema
- OpenCode 1.14.22: `--format json` produces JSONL with a different internal event schema
- Both schemas are undocumented and subject to change

Parsing either reliably would require maintaining two vendor-specific parsers and would still fail if the model produced malformed JSON inside the stream. Instead, a simple XML-like delimited block is injected into the system prompt and the model emits it in its natural text output, which every adapter captures verbatim.

### Block format

```
<ralph-result>
status: done|blocked|partial|error
summary: one-line description of what you did
verification: what you checked (tests run, files verified, etc.)
complete: true|false
blocker: none (or reason if the task is not complete)
</ralph-result>
```

### Parser rules (`parse_worker_result` in `result_contract.py`)

1. Find exactly one `<ralph-result>…</ralph-result>` span (case-insensitive, dotall).  Zero or ≥2 matches → `UntrustedResult`.
2. Extract all five required fields by splitting lines on the first `: ` colon.  Any missing field → `UntrustedResult`.
3. Validate `status` ∈ {done, blocked, partial, error}.  Invalid → `UntrustedResult`.
4. Validate `complete` ∈ {true, false}.  Invalid → `UntrustedResult`.
5. Enforce cross-field invariant: `complete=true` requires `status=done`.  Violation → `UntrustedResult`.
6. All checks pass → `WorkerResultBlock` (trusted, `is_trusted=True`).

### Completion confidence levels (on `IterationOutcome`)

| Level | Meaning |
|---|---|
| `promise-and-plan-confirmed` | Block says `complete=true` **and** prd.json `passes=true` |
| `plan-confirmed` | prd.json `passes=true` but no trusted block |
| `promise-only` | Block says `complete=true` but prd.json still `passes=false` — suspicious, never stops the loop |
| `unverified` | Neither plan nor block confirms completion |

**No-fake-success guarantee:** the loop halts a task only when prd.json `passes=true`.  A block claiming `complete=true` without a matching plan update yields `promise-only` confidence and the task is retried.

---

## 5. Exact Files Changed

```
src/openralph_py/result_contract.py   [NEW]
src/openralph_py/workspace.py         [modified: lock, prompt template, _is_process_running]
src/openralph_py/state.py             [modified: last_stop_reason, session_id fields]
src/openralph_py/progress.py          [modified: result_confidence, result_summary params]
src/openralph_py/loop.py              [modified: StopReason, LoopSummary, run_loop, IterationOutcome.parsed_result]
src/openralph_py/cli.py               [modified: --max-iterations, run_loop routing, exit codes]
tests/test_result_contract.py         [NEW]
tests/test_phase3_loop.py             [NEW]
```

Also fixed during Phase 2 (adapter verification, carried into Phase 3):
```
src/openralph_py/adapters/codex.py    [fixed: --skip-git-repo-check added]
src/openralph_py/adapters/opencode.py [fixed: --print → --format json]
tests/test_adapter_codex.py           [updated assertions]
tests/test_adapter_opencode.py        [updated assertions]
```

---

## 6. Tests Added / Updated and Results

### Test counts

| Suite | Tests | Status |
|---|---|---|
| Pre-Phase 3 baseline | 49 | All passing |
| `test_result_contract.py` (new) | 24 | All passing |
| `test_phase3_loop.py` (new) | 24 | All passing |
| **Total** | **97** | **All passing** |

### Notable test classes

**`test_result_contract.py`**
- Happy-path parse for all four valid statuses
- Parametrized missing-field tests (5 fields × 1 case each)
- Invariant violation: `complete=true` with `status=blocked` → `UntrustedResult`
- Multiple block spans → `UntrustedResult`
- `UntrustedResult.complete` is always `False` regardless of content

**`test_phase3_loop.py`**
- `FakeResultAdapter` — emits a valid `<ralph-result>` block and sets `passes=true` in prd.json
- `NoBlockAdapter` — sets `passes=true` in prd.json but emits no block
- All four confidence levels exercised
- All six `StopReason` values exercised
- Lock acquire/release, context manager, concurrent-PID lock (blocked), stale-PID lock (removed)
- State persistence: `last_stop_reason` and `session_id` round-trip through JSON
- Progress log enrichment: `Confidence:` and `Worker summary:` lines

### Windows-specific fix discovered during test runs

`_is_process_running()` originally used `os.kill(pid, 0)`.  On POSIX this is a safe "null signal" probe.  On Windows, signal `0` is `CTRL_C_EVENT`, so `os.kill(current_pid, 0)` sent a real Ctrl+C to the test process, causing a `KeyboardInterrupt` in the `colorama` output handler after 41 of 48 new tests had run.

Fix: on Windows, use `ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)` to check process liveness without sending any signal.  No new dependency; `ctypes` ships with every CPython build.

```python
if platform.system() == "Windows":
    import ctypes
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False
```

---

## 7. Real 2-Iteration Runtime Validation

### Setup

```
Sandbox: C:\DATA\PROJECTS\OpenRalph_runtime_sandbox  (git init already done)
prd.json: 2 tasks (task-1: create hello.txt, task-2: create world.txt), both passes=false
Adapter: codex (Codex CLI 0.121.0)
Command: openralph-py run --workspace C:\DATA\PROJECTS\OpenRalph_runtime_sandbox
              --adapter codex --max-iterations 2
```

### Exact output

```
Session:     6b8fdad2-29ec-4a6b-b4f3-b62c170dce63
Stop reason: max_iterations
Iterations:  2
Progress:    0/2 tasks complete
Iterations:
  #1 task=task-1 exit=0 confidence=unverified
  #2 task=task-1 exit=0 confidence=unverified
EXIT=0
```

### `.ralph-state.json` after run

```json
{
  "plan_file": "prd.json",
  "started_at": 1776973464.901,
  "iterations": 2,
  "iteration_durations": [46.47, 56.34],
  "last_run_at": 1776973586.002,
  "last_task_id": "task-1",
  "last_exit_code": 0,
  "last_stop_reason": "max_iterations",
  "session_id": "6b8fdad2-29ec-4a6b-b4f3-b62c170dce63"
}
```

### `progress.txt` after run

```markdown
## Iteration 1 - 2026-04-23T19:45:29Z
- Task: task-1 Create a file called hello.txt...
- Exit: 0
- Duration: 46.5s
- Confidence: unverified

## Iteration 2 - 2026-04-23T19:46:26Z
- Task: task-1 Create a file called hello.txt...
- Exit: 0
- Duration: 56.3s
- Confidence: unverified
```

### Analysis

**What worked (infrastructure layer):**
- Loop orchestrated exactly 2 iterations ✅
- Lock was acquired at loop start and released on completion (no `.ralph-lock` present afterwards) ✅
- Session UUID generated and persisted to state ✅
- `stop_reason=max_iterations` persisted to state ✅
- Progress log written with `Confidence:` per iteration ✅
- Parser ran on each iteration's stdout; correctly returned `UntrustedResult` when no block present ✅
- Confidence correctly reported as `unverified` (neither plan update nor trusted block) ✅

**What the worker (Codex) did not do:**
- Did not emit a `<ralph-result>` block → `UntrustedResult`, `confidence=unverified`
- Did not update `prd.json` `passes=true` → task never advanced; both iterations worked on `task-1`
- Codex ran for ~46s and ~56s (exit 0) but the outcome was not reflected in the plan file

**Why this is the correct, honest result:**

This validates the no-fake-success guarantee. The loop correctly refused to mark `task-1` complete despite two full codex invocations, because neither the plan file nor a trusted result block confirmed completion. A simpler system that trusted exit code 0 would have incorrectly reported 2/2 tasks complete.

The `confidence=unverified` signal is accurate: the worker ran, produced output, but neither the bounded text contract nor the plan corroborates success.

In a production deployment, the prompt template (Rule 6) instructs the worker to emit the block AND update `passes=true`. Codex followed neither instruction in these runs. The system responded correctly by continuing to retry and eventually stopping at `max_iterations`.

---

## 8. What Remains Intentionally Deferred

The following are **not** in scope for Phase 3 and were not started:

| Topic | Reason deferred |
|---|---|
| TUI / interactive display | Out of scope per Phase 3 requirements |
| PTY adapter (streaming) | Reference impl pattern; not required for headless use |
| Memory / knowledge system | No memory tooling in scope |
| Planner / task decomposition | Separate concern; prd.json is written by humans or upstream tooling |
| Multi-agent / verifier agent | Not required; plan file is the authoritative verifier |
| Automatic prd.json repair | Worker must update the plan; orchestrator does not second-guess |
| OpenCode runtime validation | Codex was used; OpenCode adapter is structurally identical and was verified in Phase 2 adapter verification |
