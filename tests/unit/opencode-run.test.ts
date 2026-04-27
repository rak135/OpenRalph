import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

const spawnPtyMock = mock((_command: string[], _options: any) => ({
  write: () => {},
  resize: () => {},
  kill: () => {},
  onData: () => {},
  onExit: () => {},
  pid: 123,
  cleanup: () => {},
}));

mock.module("../../src/pty/spawn", () => ({
  spawnPty: spawnPtyMock,
}));

const { OpencodeRunAdapter } = await import("../../src/adapters/opencode-run");

describe("OpencodeRunAdapter", () => {
  let originalSpawn: typeof Bun.spawn;
  let originalPlatform: PropertyDescriptor | undefined;
  let originalRalphOpencodePath: string | undefined;
  let originalOpencodePath: string | undefined;

  beforeEach(() => {
    originalSpawn = Bun.spawn;
    originalPlatform = Object.getOwnPropertyDescriptor(process, "platform");
    originalRalphOpencodePath = process.env.RALPH_OPENCODE_PATH;
    originalOpencodePath = process.env.OPENCODE_PATH;
    spawnPtyMock.mockClear();
  });

  afterEach(() => {
    Bun.spawn = originalSpawn;
    if (originalPlatform) {
      Object.defineProperty(process, "platform", originalPlatform);
    }
    if (originalRalphOpencodePath === undefined) {
      delete process.env.RALPH_OPENCODE_PATH;
    } else {
      process.env.RALPH_OPENCODE_PATH = originalRalphOpencodePath;
    }
    if (originalOpencodePath === undefined) {
      delete process.env.OPENCODE_PATH;
    } else {
      process.env.OPENCODE_PATH = originalOpencodePath;
    }
  });

  it("builds opencode run args without --print", async () => {
    const adapter = new OpencodeRunAdapter();
    const controller = new AbortController();

    await adapter.execute({
      prompt: "Reply with exactly OK.",
      model: "openai/gpt-5.4",
      cwd: process.cwd(),
      signal: controller.signal,
      cols: 80,
      rows: 24,
    });

    expect(spawnPtyMock).toHaveBeenCalledTimes(1);
    const [command, spawnOptions] = spawnPtyMock.mock.calls[0] as [string[], Record<string, unknown>];
    expect(command[0]?.toLowerCase()).toContain("opencode");
    expect(command[1]).toBe("run");
    expect(command).toContain("--dangerously-skip-permissions");

    const modelIndex = command.indexOf("--model");
    expect(modelIndex).toBeGreaterThan(0);
    expect(command[modelIndex + 1]).toBe("openai/gpt-5.4");

    const fileIndex = command.indexOf("--file");
    expect(fileIndex).toBeGreaterThan(0);
    const promptFilePath = command[fileIndex + 1];
    expect(promptFilePath).toContain("ralph-opencode-prompt-");
    expect(command[fileIndex + 2]).toBe("--");
    expect(command[fileIndex + 3]).toBe(
      "Execute the attached Ralph prompt now. Make real workspace changes. Do not summarize the prompt."
    );
    expect(command[fileIndex + 3]?.includes("\n")).toBe(false);

    const promptFile = Bun.file(promptFilePath!);
    expect(await promptFile.text()).toBe("Reply with exactly OK.");
    await promptFile.delete();

    expect(command).not.toContain("--print");
    expect(command).not.toContain("Reply with exactly OK.");
    // stdin must be ignored so the pipe-mode fallback on Windows does not hang
    expect(spawnOptions?.stdinMode).toBe("ignore");
  });

  it("prefers RALPH_OPENCODE_PATH on Windows for availability checks", async () => {
    Object.defineProperty(process, "platform", {
      value: "win32",
      configurable: true,
    });
    process.env.RALPH_OPENCODE_PATH = "C:\\Tools\\opencode.cmd";
    delete process.env.OPENCODE_PATH;

    const spawnMock = mock((command: string[], _options: any) => ({
      stdout: null,
      stderr: null,
      exited: Promise.resolve(0),
    }));
    Bun.spawn = spawnMock as any;

    const adapter = new OpencodeRunAdapter();
    const available = await adapter.isAvailable();

    expect(available).toBe(true);
    expect(spawnMock).toHaveBeenCalledTimes(1);
    expect(spawnMock.mock.calls[0]?.[0]).toEqual(["C:\\Tools\\opencode.cmd", "--version"]);
  });
});