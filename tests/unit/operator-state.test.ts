import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdirSync } from "node:fs";
import { TempDir } from "../helpers/temp-files";
import {
  buildVerifierFeedbackLines,
  formatVerificationSummary,
  loadOperatorUiSnapshot,
} from "../../src/ui/operator-state";

describe("loadOperatorUiSnapshot", () => {
  const tempDir = new TempDir();

  beforeEach(async () => {
    await tempDir.create("ralph-operator-ui-");
    mkdirSync(tempDir.path(".ralph"), { recursive: true });
  });

  afterEach(async () => {
    await tempDir.cleanup();
  });

  it("reads canonical .ralph/prd.json before legacy root prd.json", async () => {
    await Bun.write(
      tempDir.path(".ralph", "prd.json"),
      JSON.stringify({ items: [{ description: "canonical task", passes: false }] }, null, 2)
    );
    await Bun.write(
      tempDir.path("prd.json"),
      JSON.stringify({ items: [{ description: "legacy task", passes: false }] }, null, 2)
    );

    const snapshot = await loadOperatorUiSnapshot({ workspaceDir: tempDir.dir });

    expect(snapshot.planFile).toBe(tempDir.path(".ralph", "prd.json"));
    expect(snapshot.planUsesLegacyRoot).toBe(false);
    expect(snapshot.tasks[0]?.text).toBe("canonical task");
  });

  it("reads .ralph/progress.txt before root progress.txt", async () => {
    await Bun.write(
      tempDir.path(".ralph", "prd.json"),
      JSON.stringify({ items: [{ description: "task", passes: false }] }, null, 2)
    );
    await Bun.write(tempDir.path(".ralph", "progress.txt"), "canonical progress\n");
    await Bun.write(tempDir.path("progress.txt"), "legacy progress\n");

    const snapshot = await loadOperatorUiSnapshot({ workspaceDir: tempDir.dir });

    expect(snapshot.progressFile).toBe(tempDir.path(".ralph", "progress.txt"));
    expect(snapshot.progressText).toContain("canonical progress");
    expect(snapshot.progressText).not.toContain("legacy progress");
  });

  it("recognizes .ralph/done and exposes present status", async () => {
    await Bun.write(
      tempDir.path(".ralph", "prd.json"),
      JSON.stringify({ items: [{ description: "task", passes: true }] }, null, 2)
    );
    await Bun.write(tempDir.path(".ralph", "done"), "");

    const snapshot = await loadOperatorUiSnapshot({ workspaceDir: tempDir.dir });

    expect(snapshot.doneFileExists).toBe(true);
    expect(snapshot.doneMarkerStatus).toBe("present");
  });

  it("loads verifierFeedback from canonical PRD items", async () => {
    await Bun.write(
      tempDir.path(".ralph", "prd.json"),
      JSON.stringify(
        {
          items: [
            {
              description: "Create alpha.txt containing exactly alpha",
              passes: false,
              verifierFeedback: {
                generatedAt: new Date().toISOString(),
                contradiction: false,
                summary: "Verifier rejected task",
                failures: [
                  {
                    path: "alpha.txt",
                    expected: "alpha",
                    actual: "alpha\n",
                    actualDisplay: '"alpha\\n"',
                    reason: "Trailing newline is not allowed for this task.",
                    correction: "Rewrite alpha.txt so it contains exactly \"alpha\" and no trailing newline.",
                  },
                ],
              },
            },
          ],
        },
        null,
        2
      )
    );

    const snapshot = await loadOperatorUiSnapshot({ workspaceDir: tempDir.dir });

    expect(snapshot.verifierFeedbackCount).toBe(1);
    expect(snapshot.tasks[0]?.verifierFeedback?.summary).toBe("Verifier rejected task");
  });

  it("does not silently hide contradiction feedback", () => {
    const lines = buildVerifierFeedbackLines({
      generatedAt: new Date().toISOString(),
      contradiction: true,
      summary: "Verifier rejected task",
      failures: [
        {
          path: "alpha.txt",
          expected: "alpha",
          actual: "beta",
          actualDisplay: '"beta"',
          reason: "Contradictory requirements.",
          correction: "Resolve the contradiction before marking complete.",
        },
      ],
    });

    expect(lines).toContain("Contradiction detected in task requirements.");
    expect(lines.some((line) => line.includes("Resolve the contradiction"))).toBe(true);
  });

  it("warns when falling back to legacy root files", async () => {
    await Bun.write(
      tempDir.path("prd.json"),
      JSON.stringify({ items: [{ description: "legacy task", passes: false }] }, null, 2)
    );
    await Bun.write(tempDir.path("progress.txt"), "legacy progress\n");

    const snapshot = await loadOperatorUiSnapshot({ workspaceDir: tempDir.dir });

    expect(snapshot.planUsesLegacyRoot).toBe(true);
    expect(snapshot.progressUsesLegacyRoot).toBe(true);
    expect(snapshot.warnings[0]).toContain("Legacy root-level Ralph files detected");
  });

  it("formats exact verification summaries for display", () => {
    expect(
      formatVerificationSummary({
        type: "file_exact_content",
        path: "alpha.txt",
        content: "alpha",
        allowTrailingNewline: false,
      })
    ).toBe('alpha.txt = "alpha"');
  });
});