"""Phase 1 CLI.

Three subcommands:

    init    -- seed a workspace with a PRD JSON from a markdown plan
    run     -- execute exactly one iteration of the Ralph loop
    status  -- report progress across runs
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from openralph_py.adapters import AdapterError, get_adapter, list_adapters
from openralph_py.loop import build_status, run_iteration
from openralph_py.plan import load_tasks, write_prd_json
from openralph_py.prompt import write_default_prompt
from openralph_py.workspace import Workspace


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        "-w",
        type=Path,
        required=True,
        help="Workspace directory (where PRD and state live)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openralph-py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init", help="Initialize workspace state from a plan")
    init_cmd.add_argument("--from", dest="from_path", type=Path, required=True,
                          help="Source plan file (markdown or PRD JSON)")
    _add_workspace_arg(init_cmd)
    init_cmd.add_argument("--force", action="store_true",
                          help="Overwrite existing prd.json")

    run_cmd = subparsers.add_parser("run", help="Run exactly one Ralph iteration")
    _add_workspace_arg(run_cmd)
    run_cmd.add_argument("--adapter", default="codex",
                         choices=sorted(a.name for a in list_adapters()))
    run_cmd.add_argument("--model", default=None)
    run_cmd.add_argument("--timeout", type=float, default=None,
                         help="Per-iteration adapter timeout in seconds")

    status_cmd = subparsers.add_parser("status", help="Report workspace progress")
    _add_workspace_arg(status_cmd)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    ws.ensure()
    source: Path = args.from_path
    if not source.exists():
        print(f"error: plan file not found: {source}", file=sys.stderr)
        return 1

    tasks = load_tasks(source)
    if not tasks:
        print(f"error: no tasks found in {source}", file=sys.stderr)
        return 1

    if ws.prd_path.exists() and not args.force:
        print(f"error: {ws.prd_path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    created_at = datetime.now(timezone.utc).isoformat()
    write_prd_json(ws.prd_path, tasks, source_file=str(source), created_at=created_at)

    if not ws.progress_path.exists():
        ws.progress_path.write_text("", encoding="utf-8")
    if not ws.prompt_path.exists():
        write_default_prompt(ws.prompt_path)

    print(f"initialized workspace at {ws.root}")
    print(f"  prd:      {ws.prd_path}  ({len(tasks)} tasks)")
    print(f"  progress: {ws.progress_path}")
    print(f"  prompt:   {ws.prompt_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        adapter = get_adapter(args.adapter)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        outcome = run_iteration(
            args.workspace,
            adapter,
            model=args.model,
            timeout_seconds=args.timeout,
        )
    except AdapterError as exc:
        print(f"adapter error: {exc}", file=sys.stderr)
        return 1

    if outcome.status == "error":
        print(f"error: {outcome.message}", file=sys.stderr)
        return 1

    if outcome.status == "no_tasks":
        print(outcome.message)
        return 2

    if outcome.status == "already_complete":
        print(outcome.message)
        return 2

    result = outcome.adapter_result
    assert outcome.task is not None and result is not None
    print(
        f"iteration {outcome.iteration}: task {outcome.task.id} "
        f"exit={result.exit_code} duration={result.duration_seconds:.1f}s"
    )
    if result.timed_out:
        print("  (adapter timed out)")
    if outcome.completed_now:
        print("  all tasks complete — wrote .ralph-done")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    report = build_status(args.workspace)
    print(report.format())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "status":
        return cmd_status(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
