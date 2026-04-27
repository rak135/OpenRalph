import path from "path";
import { log } from "./lib/log";
import { getDonePath } from "./lib/paths";
import {
  parsePrdItems,
  type FileAssertion,
  type PrdItem,
  type VerifierFeedback,
  type VerifierFeedbackFailure,
} from "./plan";

export type { FileAssertion };

// ─── Assertion extraction ────────────────────────────────────────────────────

/**
 * Return true if `p` is a safe relative path that:
 *   - Is not absolute
 *   - Does not contain ".." components
 *   - Has a file extension
 */
export function isValidRelativePath(p: string): boolean {
  if (!p || typeof p !== "string") return false;
  // No absolute paths (Unix or Windows)
  if (p.startsWith("/") || /^[a-zA-Z]:[\\/]/.test(p)) return false;
  // No parent traversal
  const normalized = p.replace(/\\/g, "/");
  if (normalized.split("/").some((part) => part === "..")) return false;
  // Must have a file extension
  if (!/\.[a-zA-Z0-9]+$/.test(normalized)) return false;
  return true;
}

/**
 * Normalise a matched path token.
 * Paths are trimmed because surrounding spaces are not meaningful path bytes.
 */
function cleanPathToken(s: string): string {
  return s.replace(/`/g, "").replace(/[.,;!?]+$/, "").trim();
}

/**
 * Normalise a matched content token.
 * For backtick-quoted content we preserve the bytes exactly as authored.
 */
function cleanContentToken(s: string): string {
  if (s.startsWith("`") && s.endsWith("`") && s.length >= 2) {
    return s.slice(1, -1);
  }
  return s.replace(/[.,;!?]+$/, "").trim();
}

/**
 * Extract deterministic file-content assertions from a task description.
 *
 * Supported patterns:
 *   1. Create/make [a file named] FILE [in <loc>] containing exactly [:]  CONTENT
 *   2. Change/set/update FILE to [contain] exactly [:] CONTENT
 *
 * If the same file path appears with two different expected contents in one
 * task, both assertions are returned (caller detects the contradiction).
 *
 * Conservative: returns [] when the wording is ambiguous.
 */
export function extractFileAssertions(taskText: string): FileAssertion[] {
  if (!taskText || typeof taskText !== "string") return [];

  const assertions: FileAssertion[] = [];

  // Regex atoms
  // FILE: backtick-quoted word OR bare filename-with-extension
  const FILE = "(`[^`\\n]+`|[\\w.\\-/]+\\.[a-zA-Z0-9]+)";
  // CONTENT: backtick-quoted phrase OR bare token (word-chars, hyphens, dots)
  const CONTENT = "(`[^`\\n]+`|[\\w.\\-]+)";

  // Pattern 1 — create/make [a file named] FILE [in <loc>] containing exactly [:]  CONTENT
  const createRe = new RegExp(
    `(?:create|make)\\s+(?:a\\s+file\\s+named\\s+)?${FILE}(?:[^.\\n]*?)\\bcontaining\\s+exactly\\s*:?\\s*${CONTENT}`,
    "gi"
  );

  let m: RegExpExecArray | null;
  while ((m = createRe.exec(taskText)) !== null) {
    const filePath = cleanPathToken(m[1]);
    const content = cleanContentToken(m[2]);
    if (!filePath || !content || !isValidRelativePath(filePath)) continue;

    assertions.push({
      type: "file_exact_content",
      path: filePath,
      content,
      allowTrailingNewline: false,
    });

    // Detect chained contradictions: "… containing exactly X and containing exactly Y"
    const afterMatch = taskText.slice((m.index ?? 0) + m[0].length);
    const chainRe = new RegExp(
      `\\band\\s+containing\\s+exactly\\s*:?\\s*${CONTENT}`,
      "gi"
    );
    let cm: RegExpExecArray | null;
    while ((cm = chainRe.exec(afterMatch)) !== null) {
      const content2 = cleanContentToken(cm[1]);
      if (content2) {
        assertions.push({
          type: "file_exact_content",
          path: filePath,
          content: content2,
          allowTrailingNewline: false,
        });
      }
    }
  }

  // Pattern 2 — change/set/update FILE to [contain] exactly [:] CONTENT
  const modifyRe = new RegExp(
    `(?:change|set|update)\\s+${FILE}\\s+to\\s+(?:contain\\s+)?exactly\\s*:?\\s*${CONTENT}`,
    "gi"
  );
  while ((m = modifyRe.exec(taskText)) !== null) {
    const filePath = cleanPathToken(m[1]);
    const content = cleanContentToken(m[2]);
    if (!filePath || !content || !isValidRelativePath(filePath)) continue;

    assertions.push({
      type: "file_exact_content",
      path: filePath,
      content,
      allowTrailingNewline: false,
    });
  }

  return assertions;
}

// ─── Verification ────────────────────────────────────────────────────────────

export type AssertionFailure = {
  path: string;
  expected: string;
  actual: string | null;
  reason: string;
};

export type { VerifierFeedback, VerifierFeedbackFailure };

export type TaskVerificationResult =
  | { pass: true; assertions: number }
  | {
      pass: false;
      assertions: number;
      failures: AssertionFailure[];
      contradiction: boolean;
    };

export type VerifierReport = {
  tasksChecked: number;
  tasksRejected: number;
  details: Array<{
    taskDescription: string;
    result: TaskVerificationResult;
  }>;
};

/**
 * Verify a single file-content assertion against actual disk state.
 */
async function verifyAssertion(
  assertion: FileAssertion,
  workspaceDir: string
): Promise<{ pass: boolean; failure?: AssertionFailure }> {
  // Security: resolve and ensure path stays inside workspace
  const resolved = path.resolve(workspaceDir, assertion.path);
  const workspaceResolved = path.resolve(workspaceDir);
  const sep = path.sep;
  if (
    resolved !== workspaceResolved &&
    !resolved.startsWith(workspaceResolved + sep)
  ) {
    return {
      pass: false,
      failure: {
        path: assertion.path,
        expected: assertion.content,
        actual: null,
        reason: `Path "${assertion.path}" resolves outside workspace`,
      },
    };
  }

  const file = Bun.file(resolved);
  if (!(await file.exists())) {
    return {
      pass: false,
      failure: {
        path: assertion.path,
        expected: assertion.content,
        actual: null,
        reason: `File "${assertion.path}" does not exist`,
      },
    };
  }

  const rawContent = await file.text();
  const expected = assertion.content;

  const pass = assertion.allowTrailingNewline
    ? rawContent === expected || rawContent === expected + "\n"
    : rawContent === expected;

  if (pass) return { pass: true };

  const trailingNewlineOnly =
    !assertion.allowTrailingNewline && rawContent === expected + "\n";
  const reason = trailingNewlineOnly
    ? "Trailing newline is not allowed for this task."
    : `File "${assertion.path}" content mismatch: expected ${JSON.stringify(expected)}, got ${JSON.stringify(rawContent.slice(0, 80))}`;

  return {
    pass: false,
    failure: {
      path: assertion.path,
      expected,
      actual: rawContent.slice(0, 200),
      reason,
    },
  };
}

function formatVisibleContent(value: string | null): string {
  if (value === null) return "(missing)";
  return JSON.stringify(value);
}

function buildCorrection(failure: AssertionFailure): string {
  if (failure.actual === null) {
    return `Create or rewrite ${failure.path} so it contains exactly ${JSON.stringify(failure.expected)}.`;
  }

  if (failure.reason === "Trailing newline is not allowed for this task.") {
    return `Rewrite ${failure.path} so it contains exactly ${JSON.stringify(failure.expected)} and no trailing newline.`;
  }

  return `Rewrite ${failure.path} so it matches the expected exact content byte-for-byte.`;
}

function buildVerifierFeedback(
  taskDescription: string,
  result: Exclude<TaskVerificationResult, { pass: true }>
): VerifierFeedback {
  const failures: VerifierFeedbackFailure[] = result.failures.map((failure) => ({
    path: failure.path,
    expected: failure.expected,
    actual: failure.actual,
    actualDisplay: formatVisibleContent(failure.actual),
    reason: failure.reason,
    correction: buildCorrection(failure),
  }));

  return {
    generatedAt: new Date().toISOString(),
    contradiction: result.contradiction,
    summary: `Verifier rejected task: ${taskDescription}`,
    failures,
  };
}

/**
 * Verify all passed tasks in an items array.
 * Tasks with no extractable assertions are skipped (no false-positive failures).
 */
export async function verifyPassedTasks(
  items: PrdItem[],
  workspaceDir: string
): Promise<VerifierReport> {
  const report: VerifierReport = {
    tasksChecked: 0,
    tasksRejected: 0,
    details: [],
  };

  for (const item of items) {
    if (!item.passes) continue;

    // Use stored verifications if present, else extract from description
    const assertions: FileAssertion[] =
      item.verifications && item.verifications.length > 0
        ? item.verifications
        : extractFileAssertions(item.description);

    if (assertions.length === 0) continue; // nothing to check

    report.tasksChecked++;

    // Detect contradictions: same path, different expected content
    const byPath = new Map<string, string[]>();
    for (const a of assertions) {
      const list = byPath.get(a.path) ?? [];
      list.push(a.content);
      byPath.set(a.path, list);
    }

    const contradictions: AssertionFailure[] = [];
    for (const [p, contents] of byPath.entries()) {
      const unique = [...new Set(contents)];
      if (unique.length > 1) {
        contradictions.push({
          path: p,
          expected: unique[0],
          actual: unique[1],
          reason: `Contradictory requirements: "${p}" cannot simultaneously contain "${unique[0]}" and "${unique[1]}"`,
        });
      }
    }

    if (contradictions.length > 0) {
      report.tasksRejected++;
      report.details.push({
        taskDescription: item.description,
        result: {
          pass: false,
          assertions: assertions.length,
          failures: contradictions,
          contradiction: true,
        },
      });
      continue;
    }

    // Verify each assertion against disk
    const failures: AssertionFailure[] = [];
    for (const assertion of assertions) {
      const { pass, failure } = await verifyAssertion(assertion, workspaceDir);
      if (!pass && failure) failures.push(failure);
    }

    if (failures.length > 0) {
      report.tasksRejected++;
      report.details.push({
        taskDescription: item.description,
        result: {
          pass: false,
          assertions: assertions.length,
          failures,
          contradiction: false,
        },
      });
    } else {
      report.details.push({
        taskDescription: item.description,
        result: { pass: true, assertions: assertions.length },
      });
    }
  }

  return report;
}

/**
 * Read prd.json, verify all tasks marked passes=true with deterministic assertions,
 * reset any false completions to passes=false, and write prd.json back.
 *
 * Returns the verification report.
 */
export async function rejectFalseCompletions(
  prdPath: string,
  workspaceDir: string
): Promise<VerifierReport> {
  const file = Bun.file(prdPath);
  if (!(await file.exists())) {
    return { tasksChecked: 0, tasksRejected: 0, details: [] };
  }

  const content = await file.text();
  const items = parsePrdItems(content);
  if (!items || items.length === 0) {
    return { tasksChecked: 0, tasksRejected: 0, details: [] };
  }

  const report = await verifyPassedTasks(items, workspaceDir);

  // Reset false-passed tasks to passes=false in the raw JSON and keep
  // verifier feedback in sync with the latest deterministic verification result.
  try {
    const parsed = JSON.parse(content) as Record<string, unknown>;

    let prdItems: Record<string, unknown>[];
    if (Array.isArray(parsed)) {
      prdItems = parsed as Record<string, unknown>[];
    } else if (parsed.items && Array.isArray(parsed.items)) {
      prdItems = parsed.items as Record<string, unknown>[];
    } else {
      log("verifier", "Cannot reset tasks: unexpected prd.json structure");
      return report;
    }

    const rejectedByDescription = new Map(
      report.details
        .filter((d) => !d.result.pass)
        .map((d) => [d.taskDescription, d.result as Exclude<TaskVerificationResult, { pass: true }>] as const)
    );
    const checkedDescriptions = new Set(report.details.map((d) => d.taskDescription));

    let resetCount = 0;
    let feedbackUpdates = 0;
    for (const item of prdItems) {
      const desc =
        typeof item.description === "string"
          ? item.description
          : typeof item.title === "string"
            ? item.title
            : null;
      if (!desc) continue;

      const rejected = rejectedByDescription.get(desc);
      if (rejected) {
        if (item.passes === true) {
          item.passes = false;
          resetCount++;
        }

        item.verifierFeedback = buildVerifierFeedback(desc, rejected);
        feedbackUpdates++;
        continue;
      }

      if (checkedDescriptions.has(desc) && item.verifierFeedback) {
        delete item.verifierFeedback;
        feedbackUpdates++;
      }
    }

    if (resetCount > 0 || feedbackUpdates > 0) {
      await Bun.write(prdPath, JSON.stringify(parsed, null, 2) + "\n");
      log("verifier", `Updated verifier state in prd.json`, {
        prdPath,
        rejected: report.tasksRejected,
        resetCount,
        feedbackUpdates,
      });
    }
  } catch (err) {
    log("verifier", "Failed to reset false completions", {
      error: err instanceof Error ? err.message : String(err),
    });
  }

  return report;
}

export type DeterministicVerificationGateResult = {
  report: VerifierReport;
  doneFileInvalidated: boolean;
};

export async function runDeterministicVerificationGate(
  prdPath: string,
  workspaceDir: string,
  doneFilePath: string = getDonePath(workspaceDir)
): Promise<DeterministicVerificationGateResult> {
  const report = await rejectFalseCompletions(prdPath, workspaceDir);
  let doneFileInvalidated = false;

  if (report.tasksRejected > 0) {
    const doneFile = Bun.file(doneFilePath);
    if (await doneFile.exists()) {
      await doneFile.delete();
      doneFileInvalidated = true;
    }
  }

  return { report, doneFileInvalidated };
}
