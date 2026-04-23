# PHASE3.1 Follow-up Report

Date: 2026-04-23  
Repository: C:\DATA\PROJECTS\OpenRalph

## 1. Executive verdict

The follow-up pass is complete for the requested scope:

1. Confidence/reporting semantics were corrected so task-level confirmation is not mislabeled as promise-only when the current task is confirmed in prd.json.
2. No-progress threshold is now configurable (runtime argument + CLI flag), no longer hardcoded.
3. Real OpenCode runtime validation was performed for 2 iterations in sandbox. OpenCode completed tasks and advanced prd.json truthfully, but still did not emit a trusted bounded result block in that run.

No scope widening was performed.

## 2. Confidence/reporting issue analysis

Previous behavior conflated full-plan completion with current-task confirmation:

- completion_confidence used completed_now
- completed_now meant all_complete(tasks_after)
- so iteration 1 in a 2-task run could show promise-only even when task-1 was correctly updated to passes=true in prd.json

This was misleading because the current task had objective plan confirmation, but reporting only looked at full-plan completion.

## 3. Exact reporting-semantic fix made

In loop runtime outcome modeling:

- Added task_confirmed to IterationOutcome:
  - true when selected task id is passes=true in tasks_after
- Added prd_advanced to IterationOutcome:
  - true when completed task count increased from tasks_before to tasks_after
- Kept completed_now as plan-level completion (all tasks complete) for stop logic compatibility

Updated completion_confidence levels:

- promise-and-plan-confirmed: trusted complete=true block + current task confirmed + plan complete
- promise-and-task-confirmed: trusted complete=true block + current task confirmed, plan still partial
- task-confirmed: current task confirmed in prd.json, no trusted promise
- promise-only: trusted complete=true claim without plan confirmation
- unverified: no trusted promise and no task confirmation

Updated per-iteration summary reporting:

- replaced ambiguous prd:yes/no with:
  - prd-task:yes/no
  - prd-plan:yes/no

This explicitly separates current-task truth from full-plan truth.

## 4. Exact no-progress configurability change made

run_loop signature change:

- Added no_progress_threshold: int = 2
- Validation: no_progress_threshold must be >= 1, else ValueError
- no_progress detection now uses this parameter instead of a local hardcoded constant
- no_progress detection also requires not outcome.prd_advanced

CLI change:

- Added run flag: --no-progress-threshold N (default 2)
- Used only in multi-iteration path (when --max-iterations != 1)

Reporting change:

- LoopSummary now includes effective threshold:
  - No-progress threshold: N

## 5. Exact files changed

- src/openralph_py/loop.py
- src/openralph_py/cli.py
- src/openralph_py/adapters/opencode.py
- tests/test_phase3_loop.py
- tests/test_cli.py
- tests/test_adapter_opencode.py

## 6. Tests added or updated

Updated tests for corrected confidence/reporting semantics:

- tests/test_phase3_loop.py
  - test_completion_confidence_plan_confirmed_when_block_absent
    - expected task-confirmed (was plan-confirmed)
  - Added test_completion_confidence_promise_and_task_confirmed_when_plan_partial
  - Updated summary format assertion to prd-task/prd-plan fields

Added tests for configurable no-progress threshold:

- tests/test_phase3_loop.py
  - Added test_no_progress_threshold_is_configurable
  - Added test_no_progress_threshold_rejects_invalid_value
  - Updated default-threshold behavior assertion in test_no_progress_stops_loop_after_threshold

Added CLI wiring coverage:

- tests/test_cli.py
  - Added test_run_multi_iteration_accepts_no_progress_threshold

OpenCode runtime-path tests:

- tests/test_adapter_opencode.py
  - Added test_build_command_supports_attached_file_and_prompt_override
  - Added test_execute_windows_uses_file_transport
  - Added test_build_command_normalizes_multiline_prompt
  - Added test_execute_extracts_text_from_jsonl_events

## 7. Test results

Final full suite:

- 114 passed in 1.03s

No regressions in no-fake-success behavior were observed.

## 8. OpenCode runtime validation

Workspace used:

- C:\DATA\PROJECTS\OpenRalph_runtime_sandbox

Exact command(s) run:

1) Reset sandbox files and seed prd.json with 2 tasks (task-1 hello.txt, task-2 world.txt)
2) Run OpenRalph with OpenCode adapter:

- openralph-py run --workspace C:\DATA\PROJECTS\OpenRalph_runtime_sandbox --adapter opencode --max-iterations 2

Observed runtime output:

Session:     0462e864-5f63-4463-ae92-31e6355ad856
Stop reason: all_complete
Iterations:  2
Progress:    2/2 tasks complete
No-progress threshold: 2
Iterations:
  #1 task=task-1 exit=0 prd-task:yes prd-plan:no confidence=task-confirmed
  #2 task=task-2 exit=0 prd-task:yes prd-plan:yes confidence=task-confirmed

Iteration-by-iteration outcome:

Iteration 1:
- task-1 executed
- hello.txt created with expected content
- task-1 passes=true in prd.json
- confidence=task-confirmed

Iteration 2:
- task-2 executed
- world.txt created with expected content
- task-2 passes=true in prd.json
- .ralph-done created
- confidence=task-confirmed

Whether bounded contract was emitted:

- Not trusted/parsed in this OpenCode run.
- Evidence:
  - confidence remained task-confirmed (not promise-and-...)
  - no worker summary lines from trusted result block were logged by loop bookkeeping

Whether prd.json advanced:

- Yes. Both task-1 and task-2 ended with passes=true.

Final stop reason:

- all_complete

## 9. Any runtime blocker still remaining for OpenCode

Remaining blocker is worker compliance with bounded result block emission in this environment.

Details:

- OpenCode now performs real work and updates prd.json truthfully.
- However, bounded <ralph-result> block was not reliably emitted in the validated run, so parser trust signal remained absent.

Minimal in-scope runtime fix applied for OpenCode transport (to reach this state):

- Windows-safe prompt transport via temporary --file attachment in adapter execute path
  - avoids .cmd argument parsing failures caused by angle-bracket tag text in long prompt arguments
- deterministic extraction of assistant text from OpenCode JSONL text events before bounded parser runs

This fixed prior transport/runtime failure modes (exit=1 immediate failures) but did not force model-level block compliance.

## 10. What remains intentionally deferred

Intentionally not done in this follow-up scope:

- no TUI/GUI/PTY additions
- no memory subsystem changes
- no verifier/planner redesign
- no contract redesign
- no truth-source changes (prd.json remains source of truth)
- no Phase 4 expansion

The system remains strict on no-fake-success: plan truth in prd.json governs completion, and missing trusted block does not produce false completion confidence.
