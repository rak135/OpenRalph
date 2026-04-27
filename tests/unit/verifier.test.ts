import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import path from "path";
import os from "os";
import {
  extractFileAssertions,
  isValidRelativePath,
  verifyPassedTasks,
  rejectFalseCompletions,
  runDeterministicVerificationGate,
  type FileAssertion,
  type AssertionFailure,
} from "../../src/verifier";
import type { PrdItem } from "../../src/plan";

// â”€â”€â”€ isValidRelativePath â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

describe("isValidRelativePath", () => {
  it("accepts bare filename with extension", () => {
    expect(isValidRelativePath("alpha.txt")).toBe(true);
  });
  it("accepts relative path with extension", () => {
    expect(isValidRelativePath("subdir/notes.txt")).toBe(true);
  });
  it("rejects absolute Unix path", () => {
    expect(isValidRelativePath("/etc/passwd")).toBe(false);
  });
  it("rejects absolute Windows path", () => {
    expect(isValidRelativePath("C:\\windows\\system32\\foo.dll")).toBe(false);
  });
  it("rejects parent traversal", () => {
    expect(isValidRelativePath("../secret.txt")).toBe(false);
  });
  it("rejects path without extension", () => {
    expect(isValidRelativePath("README")).toBe(false);
  });
  it("rejects empty string", () => {
    expect(isValidRelativePath("")).toBe(false);
  });
});

// â”€â”€â”€ extractFileAssertions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

describe("extractFileAssertions", () => {
  it("extracts create pattern with bare names", () => {
    const result = extractFileAssertions(
      "Create alpha.txt containing exactly alpha"
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      type: "file_exact_content",
      path: "alpha.txt",
      content: "alpha",
      allowTrailingNewline: false,
    });
  });

  it("extracts create pattern with backtick quoting and period", () => {
    const result = extractFileAssertions(
      "Create `alpha.txt` in the workspace root containing exactly `alpha`."
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "alpha.txt",
      content: "alpha",
    });
  });

  it("extracts create pattern with colon separator", () => {
    const result = extractFileAssertions(
      "Create a file named alpha.txt containing exactly: alpha"
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "alpha.txt",
      content: "alpha",
    });
  });

  it("extracts beta.txt from backtick variant", () => {
    const result = extractFileAssertions(
      "Create `beta.txt` containing exactly: `beta`."
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "beta.txt",
      content: "beta",
    });
  });

  it("extracts modify pattern: change â€¦ to contain exactly", () => {
    const result = extractFileAssertions(
      "Change notes.txt to contain exactly new"
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "notes.txt",
      content: "new",
    });
  });

  it("extracts modify pattern: set â€¦ to exactly", () => {
    const result = extractFileAssertions("Set notes.txt to exactly new");
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "notes.txt",
      content: "new",
    });
  });

  it("extracts modify pattern with backtick quoting", () => {
    const result = extractFileAssertions(
      "Update `notes.txt` to contain exactly `new`."
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "notes.txt",
      content: "new",
    });
  });

  it("extracts hyphenated content (synthesize pattern)", () => {
    const result = extractFileAssertions(
      "Create combined.txt containing exactly left-right"
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "combined.txt",
      content: "left-right",
    });
  });

  it("preserves quoted content exactly without trimming", () => {
    const result = extractFileAssertions(
      "Create `alpha.txt` containing exactly ` alpha `."
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "alpha.txt",
      content: " alpha ",
    });
  });

  it("extracts contradictory assertions (same file, two contents)", () => {
    const result = extractFileAssertions(
      "Create `impossible.txt` containing exactly `alpha` and containing exactly `beta`."
    );
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject<Partial<FileAssertion>>({
      path: "impossible.txt",
      content: "alpha",
    });
    expect(result[1]).toMatchObject<Partial<FileAssertion>>({
      path: "impossible.txt",
      content: "beta",
    });
  });

  it("returns empty array for ambiguous task text", () => {
    const result = extractFileAssertions(
      "Implement the authentication module and add tests."
    );
    expect(result).toHaveLength(0);
  });

  it("returns empty array for empty input", () => {
    expect(extractFileAssertions("")).toHaveLength(0);
  });

  it("does not extract path without extension", () => {
    const result = extractFileAssertions(
      "Create README containing exactly some content"
    );
    // README has no extension â†’ should not be extracted
    expect(result).toHaveLength(0);
  });
});

// â”€â”€â”€ verifyPassedTasks (disk checks via temp dir) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

describe("verifyPassedTasks", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await Bun.file(os.tmpdir()).exists()
      ? path.join(os.tmpdir(), `ralph-verifier-test-${Date.now()}`)
      : path.join("/tmp", `ralph-verifier-test-${Date.now()}`);
    await Bun.write(path.join(tmpDir, ".keep"), "");
  });

  afterEach(async () => {
    // Best-effort cleanup
    try {
      const { rmSync } = await import("fs");
      rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  async function write(filename: string, content: string) {
    await Bun.write(path.join(tmpDir, filename), content);
  }

  function makeItem(description: string, passes: boolean): PrdItem {
    return { description, passes };
  }

  it("skips tasks with passes=false", async () => {
    const items = [makeItem("Create alpha.txt containing exactly alpha", false)];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksChecked).toBe(0);
    expect(report.tasksRejected).toBe(0);
  });

  it("skips tasks with no extractable assertions", async () => {
    const items = [makeItem("Implement the auth module", true)];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksChecked).toBe(0);
    expect(report.tasksRejected).toBe(0);
  });

  it("strict exact pass: file contains exactly expected content", async () => {
    await write("alpha.txt", "alpha");
    const items = [
      makeItem("Create alpha.txt containing exactly alpha", true),
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksChecked).toBe(1);
    expect(report.tasksRejected).toBe(0);
    expect(report.details[0].result.pass).toBe(true);
  });

  it("strict exact fail: file has trailing newline", async () => {
    await write("alpha.txt", "alpha\n");
    const items = [
      makeItem("Create alpha.txt containing exactly alpha", true),
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksChecked).toBe(1);
    expect(report.tasksRejected).toBe(1);
    expect(report.details[0].result.pass).toBe(false);
  });

  it("strict exact fail: CRLF is not normalized to LF", async () => {
    await write("alpha.txt", "alpha\r\n");
    const items = [
      makeItem("Create alpha.txt containing exactly alpha", true),
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksChecked).toBe(1);
    expect(report.tasksRejected).toBe(1);
    expect(report.details[0].result.pass).toBe(false);
  });

  it("allowTrailingNewline: passes when file has exactly one trailing newline", async () => {
    await write("alpha.txt", "alpha\n");
    const items: PrdItem[] = [
      {
        description: "Create alpha.txt",
        passes: true,
        verifications: [
          {
            type: "file_exact_content",
            path: "alpha.txt",
            content: "alpha",
            allowTrailingNewline: true,
          },
        ],
      },
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksChecked).toBe(1);
    expect(report.tasksRejected).toBe(0);
  });

  it("fails when file does not exist", async () => {
    const items = [
      makeItem("Create missing.txt containing exactly alpha", true),
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksRejected).toBe(1);
    const result = report.details[0].result;
    expect(result.pass).toBe(false);
    if (!result.pass) {
      expect(result.failures[0].reason).toContain("does not exist");
    }
  });

  it("detects contradictory assertions: same file, two different expected contents", async () => {
    await write("impossible.txt", "alpha");
    const items = [
      makeItem(
        "Create `impossible.txt` containing exactly `alpha` and containing exactly `beta`.",
        true
      ),
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksRejected).toBe(1);
    const result = report.details[0].result;
    expect(result.pass).toBe(false);
    if (!result.pass) {
      expect(result.contradiction).toBe(true);
      expect(result.failures[0].reason).toContain("Contradictory");
    }
  });

  it("uses stored verifications over live extraction", async () => {
    // File has exactly "stored-content" â€” stored verifications check for that
    // But description would extract "alpha"
    await write("target.txt", "stored-content");
    const items: PrdItem[] = [
      {
        description: "Create target.txt containing exactly alpha",
        passes: true,
        verifications: [
          {
            type: "file_exact_content",
            path: "target.txt",
            content: "stored-content",
            allowTrailingNewline: false,
          },
        ],
      },
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    // Should pass because stored verification matches disk
    expect(report.tasksRejected).toBe(0);
    expect(report.details[0].result.pass).toBe(true);
  });

  it("rejects path escaping workspace", async () => {
    const items: PrdItem[] = [
      {
        description: "bad task",
        passes: true,
        verifications: [
          {
            type: "file_exact_content",
            path: "../outside.txt",
            content: "x",
            allowTrailingNewline: false,
          },
        ],
      },
    ];
    const report = await verifyPassedTasks(items, tmpDir);
    expect(report.tasksRejected).toBe(1);
    const result = report.details[0].result;
    if (!result.pass) {
      expect(result.failures[0].reason).toContain("outside workspace");
    }
  });
});

// â”€â”€â”€ rejectFalseCompletions (prd.json integration) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

describe("rejectFalseCompletions", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = path.join(os.tmpdir(), `ralph-reject-test-${Date.now()}`);
    await Bun.write(path.join(tmpDir, ".keep"), "");
  });

  afterEach(async () => {
    try {
      const { rmSync } = await import("fs");
      rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  async function writePrd(items: object) {
    const prd = { metadata: { generated: true, generator: "test" }, items };
    await Bun.write(
      path.join(tmpDir, ".ralph/prd.json"),
      JSON.stringify(prd, null, 2) + "\n"
    );
  }

  async function readPrd(): Promise<{ items: PrdItem[] }> {
    const content = await Bun.file(path.join(tmpDir, ".ralph/prd.json")).text();
    return JSON.parse(content) as { items: PrdItem[] };
  }

  it("returns empty report when prd.json does not exist", async () => {
    const report = await rejectFalseCompletions(
      path.join(tmpDir, "missing.json"),
      tmpDir
    );
    expect(report.tasksChecked).toBe(0);
    expect(report.tasksRejected).toBe(0);
  });

  it("resets false completion: model wrote trailing newline, passes=true", async () => {
    await Bun.write(path.join(tmpDir, "alpha.txt"), "alpha\n");
    await writePrd([
      {
        description: "Create alpha.txt containing exactly alpha",
        passes: true,
        category: "functional",
      },
    ]);
    const report = await rejectFalseCompletions(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );
    expect(report.tasksRejected).toBe(1);

    const updated = await readPrd();
    expect(updated.items[0].passes).toBe(false);
    expect(updated.items[0].verifierFeedback?.failures[0].actualDisplay).toBe('"alpha\\n"');
    expect(updated.items[0].verifierFeedback?.failures[0].reason).toBe(
      "Trailing newline is not allowed for this task."
    );
  });

  it("does not reset correctly completed task", async () => {
    await Bun.write(path.join(tmpDir, "alpha.txt"), "alpha");
    await writePrd([
      {
        description: "Create alpha.txt containing exactly alpha",
        passes: true,
        category: "functional",
      },
    ]);
    const report = await rejectFalseCompletions(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );
    expect(report.tasksRejected).toBe(0);

    const updated = await readPrd();
    expect(updated.items[0].passes).toBe(true);
    expect(updated.items[0].verifierFeedback).toBeUndefined();
  });

  it("resets contradictory task even if model wrote a file", async () => {
    await Bun.write(path.join(tmpDir, "impossible.txt"), "alpha");
    await writePrd([
      {
        description:
          "Create `impossible.txt` containing exactly `alpha` and containing exactly `beta`.",
        passes: true,
        category: "functional",
      },
    ]);
    const report = await rejectFalseCompletions(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );
    expect(report.tasksRejected).toBe(1);

    const updated = await readPrd();
    expect(updated.items[0].passes).toBe(false);
    expect(updated.items[0].verifierFeedback?.contradiction).toBe(true);
    expect(updated.items[0].verifierFeedback?.failures[0].reason).toContain("Contradictory requirements");
  });

  it("clears stale verifier feedback when the exact file now passes", async () => {
    await Bun.write(path.join(tmpDir, "alpha.txt"), "alpha");
    await writePrd([
      {
        description: "Create alpha.txt containing exactly alpha",
        passes: true,
        category: "functional",
        verifierFeedback: {
          generatedAt: new Date().toISOString(),
          contradiction: false,
          summary: "stale",
          failures: [
            {
              path: "alpha.txt",
              expected: "alpha",
              actual: "alpha\n",
              actualDisplay: '"alpha\\n"',
              reason: "Trailing newline is not allowed for this task.",
              correction: "Rewrite alpha.txt",
            },
          ],
        },
      },
    ]);

    const report = await rejectFalseCompletions(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );

    expect(report.tasksRejected).toBe(0);
    const updated = await readPrd();
    expect(updated.items[0].verifierFeedback).toBeUndefined();
  });

  it("invalidates .ralph/done before a model can repair the file", async () => {
    await Bun.write(path.join(tmpDir, "alpha.txt"), "alpha\n");
    await Bun.write(path.join(tmpDir, ".ralph/done"), "");
    await writePrd([
      {
        description: "Create alpha.txt containing exactly alpha",
        passes: true,
        category: "functional",
      },
    ]);

    const gateResult = await runDeterministicVerificationGate(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );

    expect(gateResult.report.tasksRejected).toBe(1);
    expect(gateResult.doneFileInvalidated).toBe(true);

    const updated = await readPrd();
    expect(updated.items[0].passes).toBe(false);
    expect(updated.items[0].verifierFeedback?.failures[0].actualDisplay).toBe('"alpha\\n"');
    expect(await Bun.file(path.join(tmpDir, ".ralph/done")).exists()).toBe(false);
  });

  it("does not touch tasks with passes=false", async () => {
    await writePrd([
      {
        description: "Create alpha.txt containing exactly alpha",
        passes: false,
        category: "functional",
      },
    ]);
    const report = await rejectFalseCompletions(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );
    expect(report.tasksChecked).toBe(0);
    expect(report.tasksRejected).toBe(0);

    const updated = await readPrd();
    expect(updated.items[0].passes).toBe(false);
  });

  it("handles plain array prd.json format", async () => {
    await Bun.write(path.join(tmpDir, "alpha.txt"), "alpha\n");
    const items = [
      {
        description: "Create alpha.txt containing exactly alpha",
        passes: true,
      },
    ];
    await Bun.write(
      path.join(tmpDir, ".ralph/prd.json"),
      JSON.stringify(items, null, 2) + "\n"
    );

    const report = await rejectFalseCompletions(
      path.join(tmpDir, ".ralph/prd.json"),
      tmpDir
    );
    expect(report.tasksRejected).toBe(1);
  });
});

