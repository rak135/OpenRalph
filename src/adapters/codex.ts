import { existsSync } from "node:fs";
import { join } from "node:path";
import type { AgentAdapter, AgentSession, ExecuteOptions, AdapterEvent } from "./types";
import { spawnPty } from "../pty/spawn";

function getCodexOverridePath(): string | undefined {
  const override = process.env.RALPH_CODEX_PATH?.trim() || process.env.CODEX_PATH?.trim();
  return override || undefined;
}

function getWindowsCodexCandidates(): string[] {
  const candidates = new Set<string>();
  const appData = process.env.APPDATA?.trim();
  const npmPrefix = process.env.npm_config_prefix?.trim();
  const userProfile = process.env.USERPROFILE?.trim();

  if (appData) {
    candidates.add(join(appData, "npm", "codex.cmd"));
  }

  if (npmPrefix) {
    candidates.add(join(npmPrefix, "codex.cmd"));
  }

  if (userProfile) {
    candidates.add(join(userProfile, "AppData", "Roaming", "npm", "codex.cmd"));
  }

  return Array.from(candidates);
}

async function resolveCodexExecutable(): Promise<string> {
  const override = getCodexOverridePath();
  if (override) return override;

  if (process.platform !== "win32") {
    return "codex";
  }

  for (const candidate of getWindowsCodexCandidates()) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }

  for (const command of ["codex.cmd", "codex"] as const) {
    try {
      const proc = Bun.spawn(["where", command], {
        stdout: "pipe",
        stderr: "ignore",
      });
      const output = await new Response(proc.stdout).text();
      const exitCode = await proc.exited;
      if (exitCode !== 0) continue;

      const resolved = output
        .split(/\r?\n/)
        .map((line) => line.trim())
        .find(Boolean);

      if (resolved) {
        return resolved;
      }
    } catch {
      // Fall through to the existing bare command behavior.
    }
  }

  return "codex";
}

async function createPtySession(
  pty: ReturnType<typeof spawnPty>,
  signal: AbortSignal
): Promise<AgentSession> {
  const pendingEvents: AdapterEvent[] = [];
  let resolveNext: ((value: IteratorResult<AdapterEvent>) => void) | null = null;
  let done = false;

  const pushEvent = (event: AdapterEvent) => {
    if (done) return;
    if (resolveNext) {
      resolveNext({ value: event, done: false });
      resolveNext = null;
    } else {
      pendingEvents.push(event);
    }
  };

  pty.onData((data) => {
    pushEvent({ type: "output", data });
  });

  const exitPromise = new Promise<{ exitCode?: number }>((resolve) => {
    pty.onExit(({ exitCode }) => {
      pushEvent({ type: "exit", code: exitCode });
      done = true;
      if (resolveNext) {
        resolveNext({ value: undefined as unknown as AdapterEvent, done: true });
      }
      resolve({ exitCode });
    });
  });

  const onAbort = () => {
    pty.cleanup();
  };
  signal.addEventListener("abort", onAbort, { once: true });

  async function* events(): AsyncGenerator<AdapterEvent> {
    try {
      while (!done) {
        if (pendingEvents.length > 0) {
          yield pendingEvents.shift()!;
        } else {
          const result = await new Promise<IteratorResult<AdapterEvent>>((resolve) => {
            resolveNext = resolve;
          });
          if (result.done) break;
          yield result.value;
        }
      }
    } finally {
      signal.removeEventListener("abort", onAbort);
      pty.cleanup();
    }
  }

  return {
    events: events(),
    send: (input) => pty.write(input + "\n"),
    abort: () => pty.kill(),
    done: exitPromise,
  };
}

export class CodexAdapter implements AgentAdapter {
  readonly name = "codex";
  readonly displayName = "Codex CLI";
  readonly mode = "pty" as const;

  async isAvailable(): Promise<boolean> {
    try {
      const codexExecutable = await resolveCodexExecutable();
      const proc = Bun.spawn([codexExecutable, "--version"], {
        stdout: "ignore",
        stderr: "ignore",
      });
      const exitCode = await proc.exited;
      return exitCode === 0;
    } catch {
      return false;
    }
  }

  async execute(options: ExecuteOptions): Promise<AgentSession> {
    const { prompt, model, cwd, signal, cols, rows } = options;

    const codexExecutable = await resolveCodexExecutable();
    const args = [codexExecutable, "exec", "--skip-git-repo-check", "--full-auto"];
    if (model) {
      const modelName = model.includes("/") ? model.split("/")[1] : model;
      args.push("--model", modelName);
    }
    args.push(prompt);

    const pty = spawnPty(args, {
      cols,
      rows,
      cwd,
      // In Bun's Windows non-PTY fallback, leaving stdin open makes
      // `codex exec` wait for extra stdin input instead of exiting.
      stdinMode: "ignore",
    });
    const controller = new AbortController();
    const forwardAbort = () => controller.abort();
    signal.addEventListener("abort", forwardAbort, { once: true });

    const session = await createPtySession(pty, controller.signal);

    return {
      ...session,
      abort: () => {
        controller.abort();
        pty.kill();
      },
      done: session.done.finally(() => {
        signal.removeEventListener("abort", forwardAbort);
      }),
    };
  }
}
