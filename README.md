# OpenRalph (Python Phase 1)

A Python Phase 1 port of the Ralph-style iterative task-execution loop,
inspired by [OpenRalph](https://github.com/shuv1337/openralph).

One run processes **exactly one incomplete task**. Repeated invocations of
`run` over the persisted workspace state form the real multi-step loop.

## Scope

Phase 1 carries the real core of Ralph:

- Persistent PRD/progress state across runs
- Deterministic single-task selection per iteration
- Adapter boundary (Codex via non-interactive subprocess)
- Completion marker handling
- Status reporting

Phase 1 explicitly **does not** include: TUI, GUI, PTY, live streaming
terminal UI, session UX, autonomous replanning, memory systems, verifier
agents, or multi-agent orchestration. Those belong to later phases.

## Install (dev)

```
pip install -e .[dev]
```

## Usage

```
python -m openralph_py.cli init --from plan.md --workspace ./my-repo
python -m openralph_py.cli run  --workspace ./my-repo --adapter codex --model gpt-5.4 --timeout 300
python -m openralph_py.cli status --workspace ./my-repo
```

Invoke `run` repeatedly (in CI, from a shell loop, or manually); each call
advances the loop by one iteration and truthfully updates workspace state.

## Workspace files

| File | Purpose |
|------|---------|
| `prd.json` | Tasks with `passes` boolean |
| `progress.txt` | Append-only progress log |
| `.ralph-prompt.md` | Worker prompt template (`{plan}`, `{progress}`, `{task}`) |
| `.ralph-state.json` | Persisted loop state (iteration count, timings) |
| `.ralph-done` | Completion marker (written when all tasks done) |

## Tests

```
pytest
```
