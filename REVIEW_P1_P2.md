# REVIEW_P1_P2

## 1. Scope And Method

This review was done by reading the real TypeScript source in `C:\DATA\PROJECTS\OpenRalph_source` first, then reading the Python implementation in `C:\DATA\PROJECTS\OpenRalph`, then reading the existing Python tests before changing code.

The comparison was specifically anchored on:

- plan / PRD handling
- persisted state ownership
- loop orchestration
- prompt construction
- adapter boundary
- subprocess / runtime execution boundary
- what belongs to core versus PTY / TUI / presentation

The practical implementation question for Phase 2 was not "does an adapter layer exist at all?" because it already did. The real question was whether that adapter layer was durable enough to launch Codex, Copilot CLI, and OpenCode cleanly on a real machine, including Windows.

## 2. What The Source Repo Actually Shows

The source repo keeps a clean ownership split:

- plan / PRD parsing is its own concern
- persisted state is loop metadata, not task truth
- the loop owns one iteration of orchestration
- prompt handling is separate from state and loop truth
- adapters are the boundary around agent execution
- PTY, TUI, headless session UX, and presentation are not the same thing as core loop semantics

That means the correct Python target is not "recreate the source repo UI/runtime stack." The correct Python target is:

- keep `prd.json` as task truth
- keep `.ralph-state.json` as secondary run metadata
- keep one iteration as the loop unit
- keep prompt rendering outside adapters
- keep adapters as execution translators, not as loop owners

## 3. Phase 1 Review

Phase 1 in the Python repo is materially stronger than a superficial reading suggests.

What Phase 1 already got right:

- `prd.json` is the primary task truth source
- `.ralph-state.json` stores only loop metadata such as iterations and recent run data
- `run_iteration` is a durable one-iteration unit, and repeated invocations form the real loop
- prompt construction is isolated from adapters and from state persistence
- CLI ownership is thin enough: it resolves inputs, invokes the loop, and reports status
- `.ralph-done` handling is tied to actual task completion, not optimistic state

What Phase 1 does not appear to be getting wrong:

- it is not using state as the plan source of truth
- it is not collapsing prompt logic into adapters
- it is not treating the CLI as the business-logic owner
- it is not trying to port PTY/TUI concerns into the core Python loop

Conclusion: the Phase 1 loop semantics are already durable, and the source-of-truth boundary is already mostly correct.

## 4. Phase 2 Review Before Changes

Phase 2 was also more complete than the repo README implies.

The Python repo already had the right structural split:

- `ExecuteOptions` for loop-facing request data
- `CommandSpec` for adapter-built subprocess launches
- `run_subprocess` as the shared execution boundary
- `RawSubprocessResult` for raw executor output
- `ExecuteResult` for normalized loop-facing output
- concrete adapters that only build commands and describe capabilities

That is the right shape.

The real weakness was operational, not architectural:

- adapters hard-coded bare executable names (`codex`, `copilot`, `opencode`)
- availability checks only used the bare name on `PATH`
- there was no explicit per-adapter executable override
- there was no Windows-friendly `.cmd` fallback resolution

So the missing Phase 2 work was not "invent an adapter abstraction." It was "make the existing abstraction launch tools robustly enough to be real."

## 5. The Actual Gap And The Fix

The gap I treated as Phase 2 incomplete work was executable resolution.

Why this matters:

- on Windows, npm-installed CLIs commonly resolve through `.cmd` shims
- a bare `codex` / `copilot` / `opencode` lookup is often too optimistic
- a serious adapter layer needs a small execution-boundary hook for explicit local override without pushing special cases into the loop or CLI

Implemented fix:

- added shared executable candidate resolution in `SubprocessAdapter`
- added optional per-adapter environment override support
- added Windows `.cmd` fallback candidates for Codex, Copilot CLI, and OpenCode
- kept command construction separate from resolution
- kept the loop and CLI unaware of adapter-specific process-launch quirks

Environment overrides added:

- `OPENRALPH_CODEX_PATH`
- `OPENRALPH_COPILOT_PATH`
- `OPENRALPH_OPENCODE_PATH`

This keeps the fix in the right layer: the adapter boundary plus its minimal supporting execution behavior.

## 6. Exact Files Changed And Exact Files Deliberately Not Changed

Changed files:

- `src/openralph_py/adapters/base.py`
- `src/openralph_py/adapters/codex.py`
- `src/openralph_py/adapters/copilot.py`
- `src/openralph_py/adapters/opencode.py`
- `tests/test_adapter_codex.py`
- `tests/test_adapter_copilot.py`
- `tests/test_adapter_opencode.py`

Deliberately not changed:

- `src/openralph_py/loop.py`
- `src/openralph_py/plan.py`
- `src/openralph_py/state.py`
- `src/openralph_py/prompt.py`
- `src/openralph_py/cli.py`
- `src/openralph_py/adapters/execution.py`
- `src/openralph_py/adapters/registry.py`
- all workspace file-layout conventions in `workspace.py`

Why those were not changed:

- the loop already had the right ownership boundary
- `prd.json` already remained task truth
- prompt construction was already in the right place
- the CLI was already thin enough
- the shared executor did not need redesign; the missing behavior was executable discovery above it

## 7. Verification

Focused adapter validation run:

- `python -m pytest -q tests/test_adapter_registry.py tests/test_adapter_codex.py tests/test_adapter_copilot.py tests/test_adapter_opencode.py`

Result:

- passed

Broader regression check:

- `python -m pytest -q tests/test_loop.py tests/test_cli.py`

Result:

- passed

What this verification proves:

- the adapter layer still normalizes results correctly
- the new executable-resolution behavior is covered by focused tests
- loop and CLI behavior did not regress from the adapter-boundary change

What it does not prove:

- it does not prove that every real external CLI is installed and authenticated on this machine
- it does not prove that Codex, Copilot CLI, and OpenCode all behave identically once launched
- it does not solve any future stdin / interactive-mode quirks if a tool itself blocks in a non-interactive path

## 8. Direct Answers

`prd.json` remains the primary source of truth for tasks. Yes.

`.ralph-state.json` should remain secondary loop metadata, not task truth. Yes.

Are the Phase 1 loop semantics durable enough to keep? Yes.

Are prompt, state, plan, and CLI responsibilities mostly in the right place already? Yes.

Was Phase 2 actually missing a major business-logic architecture piece? No.

Was Phase 2 still incomplete in a real operational sense? Yes. The adapter execution boundary was still too brittle because executable resolution was underspecified.

Is Codex still treated as a hidden special case after this fix? No. Codex, Copilot CLI, and OpenCode all sit on the same shared adapter boundary, and the executable-resolution hardening was applied generically through `SubprocessAdapter`.

What remains outside this completed Phase 2 scope on purpose:

- PTY support
- TUI / GUI concerns
- streaming session UX
- richer verifier / memory / replanning systems
- any loop redesign that would move truth ownership out of `prd.json`

Bottom line:

Phase 1 already preserved the important source-repo ownership boundaries. Phase 2 already had the right adapter architecture. The real missing work was making that architecture operationally durable at the launch boundary, and that slice is now implemented and verified.