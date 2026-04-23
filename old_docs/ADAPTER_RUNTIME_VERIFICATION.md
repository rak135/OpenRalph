# Adapter Runtime Verification

**Date:** 2026-04-23  
**Scope:** Codex CLI and OpenCode adapter runtime verification pass  
**Repo:** `C:\DATA\PROJECTS\OpenRalph`  
**Sandbox:** `C:\DATA\PROJECTS\OpenRalph_runtime_sandbox`

---

## 1. Executive Verdict

**Codex CLI:** Architecture-ready and runtime-verified with one bug fixed. `codex exec` works correctly in non-interactive mode. A required flag (`--skip-git-repo-check`) was absent from the adapter and has been added. After the fix the adapter is trustworthy for Phase 2 scope in any workspace directory.

**OpenCode:** Architecture-ready and runtime-verified with one bug fixed. `opencode run` works correctly in non-interactive mode. The adapter used an invalid `--print` flag (which does not exist in opencode's CLI surface). The correct flag is `--format json`. After the fix the adapter is trustworthy for Phase 2 scope.

---

## 2. Current Adapter Assumptions (Before Fixes)

### Codex adapter (`adapters/codex.py`) — before

| Assumption | Declared | Reality |
|---|---|---|
| Non-interactive subcommand | `codex exec` | ✅ Correct |
| Model flag | `--model <name>` | ✅ Correct |
| Provider prefix stripping | Strip `provider/` before passing model | ✅ Correct — Codex expects bare model names |
| Requires trusted/git dir | `requires_trusted_dir=False` | ❌ **Wrong** — Codex requires git repo unless `--skip-git-repo-check` is passed |
| Executable fallback | `codex.cmd` | ✅ Correct on Windows |

### OpenCode adapter (`adapters/opencode.py`) — before

| Assumption | Declared | Reality |
|---|---|---|
| Non-interactive subcommand | `opencode run` | ✅ Correct |
| Output control flag | `--print` | ❌ **Wrong** — `--print` is not a valid `opencode run` flag; does not exist in opencode 1.14.22 |
| Structured output flag | (none declared) | The correct flag is `--format json` which produces JSONL to stdout |
| Model passthrough | `--model <provider/model>` (unchanged) | ✅ Correct — OpenCode accepts provider-prefixed model strings |
| Requires trusted dir | `requires_trusted_dir=False` | ✅ Correct — OpenCode has no git-repo requirement |
| Executable fallback | `opencode.cmd` | ✅ Correct on Windows |

### Whether assumptions match official CLI behavior

- Codex: Partially. The subcommand and model flag are correct. The trusted-directory requirement was unaccounted for.
- OpenCode: Partially. The subcommand is correct. `--print` is entirely wrong and would cause a hard failure on every invocation.

---

## 3. Local Environment Status

### Codex CLI

- **Installed:** Yes
- **Version:** `codex-cli 0.121.0`
- **Resolution:** `shutil.which("codex.cmd")` → `C:\Users\Martin\AppData\Roaming\npm\codex.cmd`
- **Adapter env override:** `OPENRALPH_CODEX_PATH` (not set; default resolution used)
- **Notes:** `codex.ps1` and `codex.cmd` both present in npm global path. The `.cmd` wrapper is what the adapter resolves.

### OpenCode

- **Installed:** Yes
- **Version:** `1.14.22`
- **Resolution:** `shutil.which("opencode.cmd")` → `C:\Users\Martin\AppData\Roaming\npm\opencode.cmd`
- **Adapter env override:** `OPENRALPH_OPENCODE_PATH` (not set; default resolution used)
- **Notes:** `opencode.ps1` and `opencode.cmd` both present in npm global path.

---

## 4. Codex Runtime Verification

### Commands run

```
# 1. Check binary resolution
Get-Command codex.cmd
# → C:\Users\Martin\AppData\Roaming\npm\codex.cmd

# 2. Confirm exec subcommand exists
codex.cmd --help
# → "exec: Run Codex non-interactively [aliases: e]" — confirmed

# 3. Inspect exec flags
codex.cmd exec --help
# → --model / -m  model flag confirmed
# → --skip-git-repo-check: "Allow running Codex outside a Git repository" — confirmed

# 4. Test exec WITHOUT git repo (pre-fix condition, adapter missing --skip-git-repo-check)
Set-Location $env:TEMP\codex_nodir_test   # non-git directory
codex.cmd exec "say hello" --json
# → Error: "Not inside a trusted directory and --skip-git-repo-check was not specified."
# Exit code: 1

# 5. Test exec WITH git repo (adapter cwd happens to be git-tracked)
Set-Location C:\DATA\PROJECTS\OpenRalph_runtime_sandbox
git init
codex.cmd exec "say hello" --json
# → {"type":"thread.started",...}
# → {"type":"item.completed","item":{"text":"hello",...}}
# → {"type":"turn.completed",...}
# Exit code: 0  ✅

# 6. Test exec WITH --skip-git-repo-check (post-fix behavior)
Set-Location $env:TEMP\codex_nodir_test   # non-git directory
codex.cmd exec --skip-git-repo-check "say hello" --json
# → {"type":"thread.started",...}
# → {"type":"item.completed","item":{"text":"Hello",...}}
# → {"type":"turn.completed",...}
# Exit code: 0  ✅
```

### What succeeded

- Executable resolution via `shutil.which("codex.cmd")` — **verified**
- `codex exec` non-interactive invocation — **verified** (with git repo or `--skip-git-repo-check`)
- Prompt passing as positional argument — **verified** (`"say hello"` appeared in response)
- JSON output flag `--json` produces clean JSONL events — **verified**
- Completion and clean exit (exit code 0) — **verified**

### What failed (before fix)

- Running from a non-git directory without `--skip-git-repo-check` exits with code 1 and "Not inside a trusted directory" error. The adapter was missing this flag, so any workspace that is not a git repo would fail silently from the adapter's perspective.

### Remaining risks and unverified behavior

- **Timeout behavior:** Not tested with a live timeout scenario. The adapter passes `timeout_seconds` to the executor, which uses `subprocess.run(timeout=...)`. This is structurally correct but was not end-to-end verified with codex.
- **Auth expiry:** Tested with a valid session. Behavior when API key or auth token expires is not covered.
- **Long prompts:** Only short prompts tested. Edge behavior with very long prompt strings not verified.
- **Codex tool use / filesystem side effects:** The adapter only checks exit code and captures stdout/stderr. Any Codex tool use that modifies the workspace is not modeled.

### Adapter trustworthiness for Phase 2 scope

**Trustworthy** after the `--skip-git-repo-check` fix. The core path (resolve → build command → execute → capture output) is correct and verified.

---

## 5. OpenCode Runtime Verification

### Commands run

```
# 1. Check binary resolution
Get-Command opencode.cmd
# → C:\Users\Martin\AppData\Roaming\npm\opencode.cmd

# 2. Inspect run subcommand flags
opencode.cmd run --help
# → Positionals: message [array]
# → --format [choices: "default", "json"]  ← structured output flag
# → --model / -m  provider/model string
# → NO --print flag listed

# 3. Test run --print (pre-fix, adapter's current behavior)
Set-Location C:\DATA\PROJECTS\OpenRalph_runtime_sandbox
opencode.cmd run --print "say hello"
# → "Unknown argument: --print" / usage error
# Exit code: 1  ❌

# 4. Test run default (no format flag)
opencode.cmd run "say hello"
# → "> build · big-pickle"
# → "Hello! How can I help you today?"
# Exit code: 0 (exit code 1 in PowerShell due to stderr noise from opencode server startup,
#   actual process exit code verified below as 0)

# 5. Test run --format json (post-fix behavior)
$out = opencode.cmd run --format json "say hello" 2>$null; $LASTEXITCODE
# → 0
# → {"type":"step_start","timestamp":...,"sessionID":"ses_..."}
# → {"type":"text","timestamp":...,"part":{"type":"text","text":"\n\nHello!",...}}
# → {"type":"step_finish","timestamp":...,"reason":"stop",...}
# Exit code: 0  ✅
```

### What succeeded

- Executable resolution via `shutil.which("opencode.cmd")` — **verified**
- `opencode run --format json` non-interactive one-shot invocation — **verified**
- Prompt passing as positional argument — **verified** (response text matches prompt intent)
- JSONL event stream output (`step_start`, `text`, `step_finish`) — **verified**
- Clean exit (exit code 0) — **verified** (stderr noise from opencode's internal server output does not affect exit code)

### What failed (before fix)

- `opencode run --print "prompt"` was rejected by the CLI as an unknown argument. Every adapter invocation would fail before reaching the model.

### OpenCode stderr noise

`opencode` writes internal server/build log lines to stderr (`> build · session-name`). This is normal behavior, not an error. The `run_subprocess` executor captures stderr separately, so it does not corrupt stdout. This does not affect the adapter's correctness.

### Remaining risks and unverified behavior

- **Timeout behavior:** Not tested with a live timeout scenario. Structurally correct via `subprocess.run(timeout=...)`.
- **Auth expiry:** Tested with a valid session. No coverage of credential failure paths.
- **JSONL parsing:** The loop engine currently does not parse the JSONL event stream; it reads raw stdout. This means `text` events are consumed as-is (with surrounding JSON noise). Parsing JSONL to extract just the text content is a deferred concern.
- **`--dangerously-skip-permissions`:** OpenCode may prompt for tool-use permissions in some contexts. The adapter does not pass any permission flags, which could cause interactive prompts in certain scenarios.
- **Model flag behavior:** `--model provider/model` passthrough was not live-tested with a non-default model string. The flag exists per `opencode run --help` and its format is confirmed.

### Adapter trustworthiness for Phase 2 scope

**Trustworthy** after the `--print` → `--format json` fix. The core path is correct and verified.

---

## 6. Code Changes Made During Verification

### `src/openralph_py/adapters/codex.py`

**Why changed:** Runtime verification proved that `codex exec` fails with "Not inside a trusted directory" when the workspace is not a git repository, unless `--skip-git-repo-check` is passed. The adapter omitted this flag, making it unreliable from arbitrary workspaces.

**Changes:**
- Updated module docstring to document the `--skip-git-repo-check` requirement.
- In `build_command`: added `argv.append("--skip-git-repo-check")` before `argv.append(options.prompt)`. The flag is added unconditionally because the adapter must work from any workspace.
- In `capabilities.notes`: updated to reflect the actual command shape.

### `src/openralph_py/adapters/opencode.py`

**Why changed:** Runtime verification proved that `opencode run --print` is an invalid invocation (exit code 1, "Unknown argument: --print"). The correct structured-output flag is `--format json`.

**Changes:**
- Updated module docstring to document that `--print` is invalid and `--format json` is correct.
- In `build_command`: changed `argv = [self.executable, "run", "--print"]` to `argv = [self.executable, "run", "--format", "json"]`.
- In `capabilities.notes`: updated to reflect the actual command shape.

### `tests/test_adapter_codex.py`

**Why changed:** Test assertions reflected the old command shape without `--skip-git-repo-check`.

**Changes:**
- `test_build_command_with_provider_prefixed_model`: added `assert "--skip-git-repo-check" in spec.argv`.
- `test_build_command_without_model_omits_flag`: updated expected argv to `["codex", "exec", "--skip-git-repo-check", "p"]`.
- Updated module docstring to note the flag.

### `tests/test_adapter_opencode.py`

**Why changed:** Test `test_build_command_uses_run_print_form` asserted the now-invalid `--print` flag.

**Changes:**
- Renamed test to `test_build_command_uses_run_format_json_form`.
- Updated assertion from `spec.argv[:3] == ["opencode", "run", "--print"]` to `spec.argv[:4] == ["opencode", "run", "--format", "json"]`.
- Updated module docstring to note the `--print` invalidity.

### Test results after changes

```
49 passed in 0.39s
```
All 49 tests pass. No regressions.

---

## 7. Final Assessment

| Adapter | Status |
|---|---|
| **Codex CLI** | **Ready** — executable resolved, non-interactive path verified, bug fixed, tests green |
| **OpenCode** | **Ready** — executable resolved, non-interactive path verified, bug fixed, tests green |

Both adapters were **architecture-ready before this pass** but had real runtime bugs that would have caused failures in any live Phase 2 run. Both bugs are now fixed.

---

## 8. Deferred Items

The following items are **out of scope for this verification pass** and belong to later phases:

| Item | Reason deferred |
|---|---|
| Timeout end-to-end verification | Requires a deliberately slow prompt and live API spend; structural path is correct |
| JSONL event parsing for OpenCode output | Loop engine currently treats stdout as raw text; parsing is a feature, not a bug |
| OpenCode permission auto-approval (`--dangerously-skip-permissions`) | Policy decision, not a bug; deferred to integration phase |
| Codex tool-use / workspace side effects modeling | Out of scope for adapter boundary |
| Auth/credential failure handling | Error path coverage; not a Phase 2 blocker |
| Copilot adapter verification | Not requested in this pass |
| TUI, PTY, GUI, planner, memory | Explicitly out of scope per task definition |
