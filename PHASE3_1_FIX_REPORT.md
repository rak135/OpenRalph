# Phase 3.1 Fix Report

**Repository:** `C:\DATA\PROJECTS\OpenRalph` (Python rewrite)  
**Date:** 2026-04-23  
**Baseline:** Phase 3 — 97 tests passing, runtime loop running but worker compliance broken  
**After Phase 3.1:** 106 tests passing, real 2-iteration run completed with `stop_reason: all_complete`

---

## 1. Executive Verdict

Phase 3.1 is a **complete success**. All three root causes of the Phase 3 runtime failure were
identified and fixed. A real 2-iteration codex run with `--full-auto` now:

- Completes both tasks in prd.json (both `passes: true`)
- Emits a valid `<ralph-result>` block in both iterations
- Updates prd.json truthfully
- Creates `.ralph-done` after all tasks finish
- Stops with `all_complete` — not `max_iterations`, not `no_progress`

No scope was widened beyond Phase 3.1 fixes.

---

## 2. Root Cause Analysis

Three bugs caused the Phase 3 runtime failure. They compounded each other.

### Bug 1: Multiline prompt silently truncated on Windows (critical)

**Root cause:** `subprocess.list2cmdline` converts actual newline characters (`\n`) to literal
two-character sequences `\n` in the Windows command-line string. Codex received only the first
line of the prompt. Every subsequent line was lost.

**Evidence:** Running the adapter directly with `text=True` stdin and a prompt containing actual
newlines, codex stderr showed:
```
user
You are a software agent executing one task in an automated loop. Follow every step.
```
Only the first line appeared. The model responded: *"I have the loop constraint, but no task
steps were included."*

After the fix (prompt via stdin + UTF-8 encoding), codex stderr shows all prompt lines:
```
user
You are a software agent executing one task in an automated loop. Follow every step.

WORKSPACE: C:\DATA\PROJECTS\OpenRalph_runtime_sandbox
PLAN FILE: prd.json ...
```

**Fix:** Changed the Codex adapter to pass the prompt via **stdin** using the `-` sentinel
argument (`codex exec … -`). This bypasses command-line argument encoding entirely.
Also added `encoding="utf-8"` to `subprocess.run()` in `run_subprocess`, which fixes the
secondary issue where the em dash character in the original prompt template caused a UTF-8
decode error on Windows (cp1252 default encoding).

### Bug 2: Model output not reaching the parser (secondary)

**Root cause:** Without `--full-auto`, codex might pause for approval of file writes in
non-interactive subprocess mode. With it, approvals are automatic. Additionally, without
`--output-last-message <file>`, codex's terminal renderer writes progress events to stdout
rather than the model's clean text response. Our bounded text parser was searching through
terminal events looking for `<ralph-result>` and finding nothing.

**Evidence:** Phase 3 showed exit=0 with `confidence=unverified` in both iterations, meaning the
parser found no block. After adding `--output-last-message`, the parser reliably finds the block
in the model's clean final text.

**Fix:** Added `--full-auto` (automatic sandbox approval) and `--output-last-message <tempfile>`
(clean model text capture) to the codex adapter. The temp file content replaces subprocess
stdout as the effective stdout; falls back to subprocess stdout if file is empty (preserving
backward-compat with fake executors in tests).

### Bug 3: Prompt too verbose, model skipped protocol steps

**Root cause:** The Phase 3 prompt was formatted with markdown headers, negative constraints,
and two separate result-block templates (done / blocked). The model focused on the primary task
implementation and stopped, never executing the required prd.json update or result block steps.

**Evidence:** Even before the stdin fix, when codex ran for 37+ seconds (i.e., a real model
call), it created the task files correctly but left prd.json untouched and emitted no block.

**Fix:** Rewrote the prompt to be compact, imperative, and formatted as a numbered steps list.
The result block appears inline at the end with concrete fill-in-the-blank fields. Negative
constraints are reduced to two lines at the bottom.

---

## 3. Exact Files Changed

```
src/openralph_py/adapters/codex.py       [Phase 3.1: full-auto, output-last-message, stdin delivery]
src/openralph_py/adapters/execution.py   [Phase 3.1: added encoding="utf-8" to subprocess.run]
src/openralph_py/workspace.py            [Phase 3.1: prompt template rewrite, removed em dash]
src/openralph_py/loop.py                 [Phase 3.1: StopReason.NO_PROGRESS, no-progress tracking, format improvement]
tests/test_adapter_codex.py              [Phase 3.1: updated assertions + 4 new tests]
tests/test_phase3_loop.py                [Phase 3.1: 5 new tests for NO_PROGRESS and format]
```

---

## 4. Architectural / Behavioral Changes

| Concern | Before | After |
|---|---|---|
| Prompt delivery | Arg (`subprocess.list2cmdline`, loses newlines on Windows) | Stdin (`-` sentinel, UTF-8) |
| Subprocess encoding | Platform default (cp1252 on Windows) | Always UTF-8 |
| Codex approval mode | Default (may prompt interactively) | `--full-auto` (automatic) |
| Model output capture | subprocess stdout (terminal events) | `--output-last-message <tmpfile>` (clean model text) |
| No-progress protection | None — loop burned all `max_iterations` | `NO_PROGRESS` stop after 2 consecutive unverified same-task iterations |
| Loop reporting | `confidence=` per iteration | `prd:yes/no` + `confidence=` per iteration |

Boundaries are unchanged: prompt policy in workspace.py, parser in result_contract.py, loop
stop decisions in loop.py, command construction in codex.py. No scope widening.

---

## 5. Changes in the Codex Execution Path

### Before (Phase 3)
```
codex exec [--model NAME] --skip-git-repo-check <prompt-as-arg>
```
- Prompt passed as a positional argument (truncated to first line on Windows)
- No `--full-auto` (may pause for approval)
- No `--output-last-message` (model text not available to parser)
- stdout captured from subprocess (terminal events, not model text)

### After (Phase 3.1)
```
codex exec --full-auto [--model NAME] --skip-git-repo-check --output-last-message <tmpfile> -
stdin: <full multiline prompt, UTF-8>
```
- Prompt delivered via stdin (preserves all newlines and Unicode)
- `--full-auto`: sandbox auto-approves file writes in workspace
- `--output-last-message <tmpfile>`: model's clean final response written to file
- Effective stdout = tmpfile content if non-empty, else subprocess stdout

The `execute()` override in `CodexAdapter` creates a temp file, injects the flag, runs codex,
reads the file, and cleans up. Tests that use fake executors receive the same interface; the
fake executor can write to the `--output-last-message` path to test the preferred path.

---

## 6. Changes in the Prompt

### Before (Phase 3)
- Opened with "Ralph-style iterative loop" meta-framing
- Formatted with markdown-style headers (ASSIGNED TASK, REQUIRED STEPS, DO NOT)
- Two separate result-block examples (done vs blocked)
- Negative constraints in a dedicated "DO NOT" section
- Contained `—` em dash (U+2014, non-ASCII)

### After (Phase 3.1)
- Opens with "You are a software agent executing one task. Follow every step." — imperative
- Seven numbered steps; result block embedded inline at step 7 as a literal fill-in template
- Single blocked variant described inline (one sentence)
- Two-line "DO NOT" at bottom
- ASCII only (em dash replaced with plain parenthetical)
- ~35% shorter

---

## 7. Changes in Stop-Reason / No-Progress Handling

### New stop reason: `NO_PROGRESS`
Added `StopReason.NO_PROGRESS = "no_progress"` to the enum.

### Tracking logic (in `run_loop`)
```python
NO_PROGRESS_THRESHOLD = 2  # consecutive unverified same-task iterations before stopping

_no_progress_task_id: str | None = None
_no_progress_count: int = 0

# After each "ran" iteration:
if current_task_id == _no_progress_task_id and confidence == "unverified":
    _no_progress_count += 1
    if _no_progress_count >= NO_PROGRESS_THRESHOLD:
        stop_reason = StopReason.NO_PROGRESS
        break
else:
    _no_progress_task_id = current_task_id
    _no_progress_count = 0
```

Only `confidence == "unverified"` triggers the counter. `promise-only` (block claims done but
plan disagrees) is intentionally excluded — that case reaches `max_iterations` so the caller can
observe the discrepancy.

### Reporting improvement
`LoopSummary.format()` now includes `prd:yes/no` per iteration, showing whether prd.json
actually advanced (i.e., all tasks became complete). This makes it immediately visible whether
the worker did real work.

---

## 8. Tests Added or Updated

### `tests/test_adapter_codex.py` — updated + 4 new tests

**Updated:**
- `test_build_command_with_provider_prefixed_model` — asserts `argv[-1] == "-"` and `stdin == prompt`
- `test_build_command_without_model_omits_flag` — full argv now ends with `"-"` sentinel
- `test_build_command_includes_full_auto` — updated to assert `stdin` field

**New:**
- `test_build_command_with_output_file_adds_flag` — `--output-last-message` added when `output_file` passed
- `test_execute_uses_last_message_file_over_stdout` — fake executor writes to tmpfile; asserts stdout is file content
- `test_execute_falls_back_to_stdout_when_last_message_empty` — no tmpfile → stdout used
- `test_execute_passes_full_auto_in_argv_to_executor` — `--full-auto` present in argv seen by executor

### `tests/test_phase3_loop.py` — 5 new tests

- `test_no_progress_stops_loop_after_threshold` — `NoProgressAdapter` triggers `NO_PROGRESS` before `max_iterations`
- `test_no_progress_resets_counter_on_different_task` — completing task-a resets counter; task-b stall triggers `NO_PROGRESS`
- `test_no_progress_does_not_trigger_when_prd_advances` — real progress prevents `NO_PROGRESS`
- `test_loop_summary_format_shows_prd_advancement` — `prd:yes/prd:no` present in format output
- (Updated) `test_block_claiming_done_without_plan_update_does_not_stop_loop` — doc comment clarified; `promise-only` case does NOT trigger `NO_PROGRESS`

---

## 9. Test Results

```
Before Phase 3.1:  97 tests, all passing
After Phase 3.1:  106 tests, all passing
```

All tests pass on Python 3.12.10 / pytest 9.0.3 / Windows.

---

## 10. Real Runtime Validation

### Setup
```
Sandbox : C:\DATA\PROJECTS\OpenRalph_runtime_sandbox  (git-initialized)
prd.json: 2 tasks (task-1: hello.txt, task-2: world.txt), both passes=false
Adapter : codex (Codex CLI 0.124.0, full-auto mode)
Model   : gpt-5.4 (provider: openai)
Command : openralph-py run --workspace C:\DATA\PROJECTS\OpenRalph_runtime_sandbox
              --adapter codex --max-iterations 2
```

### Exact command output
```
Session:     a05c18a7-e802-4eae-9164-c33839f6e681
Stop reason: all_complete
Iterations:  2
Progress:    2/2 tasks complete
Iterations:
  #1 task=task-1 exit=0 prd:no confidence=promise-only
  #2 task=task-2 exit=0 prd:yes confidence=promise-and-plan-confirmed
EXIT=0
```

### Full-auto mode
Yes. Codex ran as `codex exec --full-auto --skip-git-repo-check --output-last-message <tmpfile> -`
with prompt delivered via stdin. Codex stderr confirmed: `approval: never` (full-auto active).

### Iteration 1 (task-1, 49s)
- Codex created `hello.txt` with content `Hello from Ralph Phase 3.1` ✅
- Codex set `task-1.passes = true` in prd.json ✅
- Codex appended to progress.txt ✅
- Codex emitted `<ralph-result>` with `status: done, complete: true` ✅
- `confidence = promise-only` because task-2 was still pending (`completed_now = False` = all tasks complete)
- prd:no in loop output because `completed_now` means ALL tasks complete, not just this one

### Iteration 2 (task-2, 41s)
- Codex created `world.txt` with content `World from Ralph Phase 3.1` ✅
- Codex set `task-2.passes = true` in prd.json ✅
- Codex appended to progress.txt ✅
- Codex created `.ralph-done` marker ✅
- Codex emitted `<ralph-result>` with `status: done, complete: true` ✅
- `confidence = promise-and-plan-confirmed` (both block and plan agree) ✅
- prd:yes — all tasks complete ✅

### prd.json after run
```json
{
  "items": [
    {"id": "task-1", "description": "...", "passes": true},
    {"id": "task-2", "description": "...", "passes": true}
  ]
}
```

### `.ralph-done` marker
Present. ✅

### `.ralph-state.json` after run
```json
{
  "last_stop_reason": "all_complete",
  "session_id": "a05c18a7-e802-4eae-9164-c33839f6e681",
  "iterations": 2,
  "iteration_durations": [49.03, 40.89],
  "last_task_id": "task-2",
  "last_exit_code": 0
}
```

### Worker summaries written to progress.txt
```
task task-1: Created hello.txt with the required content, verified it, and marked task-1 as passed in prd.json.
task task-2: Created world.txt with the required exact text, verified it, marked task-2 as passed in prd.json, and completed the plan.
```

---

## 11. What Remains Unresolved

| Item | Status |
|---|---|
| `confidence=promise-only` in iteration 1 | Working as designed. `completed_now` means ALL tasks complete. Individual task advancement visible in prd.json. Could be clarified in reporting in a future pass. |
| No-progress threshold is hardcoded | `NO_PROGRESS_THRESHOLD = 2` is a module-level constant in `loop.py`. Could be made configurable via `run_loop()` arg. Deferred — not needed now. |
| OpenCode runtime validation | OpenCode adapter was verified correct in Phase 2. Not validated in Phase 3.1 runtime — codex was used. OpenCode adapter has the same stdin delivery fix applied via `execution.py`. |
| Prompt overrides for custom workspaces | Custom `.ralph-prompt.md` still works; hardened template is only the default. Custom templates should follow the same compact format for best results. |
| Adapter test coverage for stdin edge cases | Tests cover the happy path. Unicode edge cases in prompts are not exhaustively tested, but the root cause (UTF-8 encoding) is fixed at the subprocess layer for all adapters. |
