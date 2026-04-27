import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AgentAdapter, AgentSession, ExecuteOptions, AdapterEvent } from "./types";
import { spawnPty } from "../pty/spawn";

const OPENCODE_RUN_DIRECTIVE =
  "Execute the attached Ralph prompt now. Make real workspace changes. Do not summarize the prompt.";

function createPromptTempPath(): string {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return join(tmpdir(), `ralph-opencode-prompt-${suffix}.md`);
}

function getOpencodeOverridePath(): string | undefined {
  const override = process.env.RALPH_OPENCODE_PATH?.trim() || process.env.OPENCODE_PATH?.trim();
  return override || undefined;
}

function shouldSkipOpencodePermissions(): boolean {
  const value = process.env.RALPH_OPENCODE_SKIP_PERMISSIONS?.trim().toLowerCase();
  if (!value) return true;
  return !["0", "false", "no", "off"].includes(value);
}

function getWindowsOpencodeCandidates(): string[] {
  const candidates = new Set<string>();
  const appData = process.env.APPDATA?.trim();
  const npmPrefix = process.env.npm_config_prefix?.trim();
  const userProfile = process.env.USERPROFILE?.trim();

  if (appData) {
    candidates.add(join(appData, "npm", "opencode.cmd"));
  }

  if (npmPrefix) {
    candidates.add(join(npmPrefix, "opencode.cmd"));
  }

  if (userProfile) {
    candidates.add(join(userProfile, "AppData", "Roaming", "npm", "opencode.cmd"));
  }

  return Array.from(candidates);
}

async function resolveOpencodeExecutable(): Promise<string> {
  const override = getOpencodeOverridePath();
  if (override) return override;

  if (process.platform !== "win32") {
    return "opencode";
  }

  for (const candidate of getWindowsOpencodeCandidates()) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }

  for (const command of ["opencode.cmd", "opencode"] as const) {
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

  return "opencode";
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

export class OpencodeRunAdapter implements AgentAdapter {
  readonly name = "opencode-run";
  readonly displayName = "OpenCode (Headless)";
  readonly mode = "pty" as const;

  async isAvailable(): Promise<boolean> {
    try {
      const opencodeExecutable = await resolveOpencodeExecutable();
      const proc = Bun.spawn([opencodeExecutable, "--version"], {
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

    const opencodeExecutable = await resolveOpencodeExecutable();
    const promptFile = createPromptTempPath();
    await Bun.write(promptFile, prompt);

    const args = [opencodeExecutable, "run"];
    if (shouldSkipOpencodePermissions()) {
      args.push("--dangerously-skip-permissions");
    }
    if (model) {
      args.push("--model", model);
    }
    args.push("--file", promptFile, "--", OPENCODE_RUN_DIRECTIVE);

    // Use stdinMode:"ignore" so that when Bun PTY is unavailable on Windows and
    // the fallback pipe-mode path is taken, OpenCode does not block waiting on
    // an open stdin pipe. The prompt body is attached via --file.
    const pty = spawnPty(args, { cols, rows, cwd, stdinMode: "ignore" });
    const controller = new AbortController();
    const forwardAbort = () => controller.abort();
    signal.addEventListener("abort", forwardAbort, { once: true });

    const cleanupPromptFile = async () => {
      try {
        const file = Bun.file(promptFile);
        if (await file.exists()) {
          await file.delete();
        }
      } catch {
        // Best effort cleanup for temp prompt file.
      }
    };

    const session = await createPtySession(pty, controller.signal);

    return {
      ...session,
      abort: () => {
        controller.abort();
        pty.kill();
        void cleanupPromptFile();
      },
      done: session.done.finally(async () => {
        signal.removeEventListener("abort", forwardAbort);
        await cleanupPromptFile();
      }),
    };
  }
}
