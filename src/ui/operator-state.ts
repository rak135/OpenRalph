import { resolve } from "node:path";
import {
  getDonePath,
  getLegacyPlanPath,
  getLegacyProgressPath,
  getLogsDir,
  getPlanPath,
  getProgressPath,
  getRalphDir,
  getStateFilePath,
  resolveCanonicalOrLegacyPath,
} from "../lib/paths";
import {
  parsePlan,
  parsePlanTasks,
  type FileAssertion,
  type Task,
  type VerifierFeedback,
} from "../plan";

export type DoneMarkerStatus = "present" | "accepted" | "invalidated" | "absent";

export type OperatorUiSnapshot = {
  workspaceDir: string;
  ralphDir: string;
  planFile: string;
  progressFile: string;
  stateFile: string;
  logsDir: string;
  planUsesLegacyRoot: boolean;
  progressUsesLegacyRoot: boolean;
  warnings: string[];
  tasks: Task[];
  done: number;
  total: number;
  planError?: string;
  progressText: string;
  progressTail: string[];
  doneFileExists: boolean;
  doneMarkerStatus: DoneMarkerStatus;
  stateFileExists: boolean;
  verifierFeedbackCount: number;
  contradictionCount: number;
};

type SnapshotOptions = {
  workspaceDir?: string;
  planFile?: string;
  progressFile?: string;
  allowLegacyFallback?: boolean;
};

function normalizePath(filePath: string): string {
  const resolved = resolve(filePath);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function shouldResolveWithLegacy(requestedPath: string | undefined, canonicalPath: string, legacyPath: string): boolean {
  if (!requestedPath) {
    return true;
  }

  const normalized = normalizePath(requestedPath);
  return normalized === normalizePath(canonicalPath) || normalized === normalizePath(legacyPath);
}

async function resolveOperatorPath(
  requestedPath: string | undefined,
  canonicalPath: string,
  legacyPath: string,
  allowLegacyFallback: boolean
): Promise<{ path: string; usedLegacy: boolean }> {
  if (allowLegacyFallback && shouldResolveWithLegacy(requestedPath, canonicalPath, legacyPath)) {
    return resolveCanonicalOrLegacyPath(canonicalPath, legacyPath);
  }

  const path = requestedPath ?? canonicalPath;
  return { path, usedLegacy: normalizePath(path) === normalizePath(legacyPath) };
}

function getProgressTail(progressText: string, maxLines: number = 3): string[] {
  return progressText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-maxLines);
}

export function getDoneMarkerStatus(tasks: Task[], doneFileExists: boolean, done: number, total: number): DoneMarkerStatus {
  if (doneFileExists) {
    return "present";
  }

  if (tasks.some((task) => task.verifierFeedback)) {
    return "invalidated";
  }

  if (total > 0 && done === total) {
    return "accepted";
  }

  return "absent";
}

export function buildVerifierFeedbackLines(feedback: VerifierFeedback): string[] {
  const lines = [feedback.summary];

  if (feedback.contradiction) {
    lines.push("Contradiction detected in task requirements.");
  }

  for (const failure of feedback.failures) {
    lines.push(`Path: ${failure.path}`);
    lines.push(`Expected: ${JSON.stringify(failure.expected)}`);
    lines.push(`Actual: ${failure.actualDisplay}`);
    lines.push(`Reason: ${failure.reason}`);
    lines.push(`Fix: ${failure.correction}`);
  }

  return lines;
}

export function formatVerificationSummary(assertion: FileAssertion): string {
  const newlinePolicy = assertion.allowTrailingNewline ? " (trailing newline allowed)" : "";
  return `${assertion.path} = ${JSON.stringify(assertion.content)}${newlinePolicy}`;
}

export async function loadOperatorUiSnapshot(options: SnapshotOptions = {}): Promise<OperatorUiSnapshot> {
  const workspaceDir = options.workspaceDir ?? process.cwd();
  const canonicalPlanPath = getPlanPath(workspaceDir);
  const legacyPlanPath = getLegacyPlanPath(workspaceDir);
  const canonicalProgressPath = getProgressPath(workspaceDir);
  const legacyProgressPath = getLegacyProgressPath(workspaceDir);
  const allowLegacyFallback = options.allowLegacyFallback ?? true;

  const resolvedPlan = await resolveOperatorPath(
    options.planFile,
    canonicalPlanPath,
    legacyPlanPath,
    allowLegacyFallback
  );
  const resolvedProgress = await resolveOperatorPath(
    options.progressFile,
    canonicalProgressPath,
    legacyProgressPath,
    allowLegacyFallback
  );

  const warnings: string[] = [];
  if (resolvedPlan.usedLegacy || resolvedProgress.usedLegacy) {
    warnings.push(
      "Legacy root-level Ralph files detected. Using compatibility paths. Run `ralph init --force` to migrate to canonical .ralph/ layout."
    );
  }

  const planProgress = await parsePlan(resolvedPlan.path);
  const tasks = await parsePlanTasks(resolvedPlan.path);
  const progressFile = Bun.file(resolvedProgress.path);
  const progressText = (await progressFile.exists()) ? await progressFile.text() : "";
  const stateFile = Bun.file(getStateFilePath(workspaceDir));
  const doneFile = Bun.file(getDonePath(workspaceDir));
  const doneFileExists = await doneFile.exists();

  return {
    workspaceDir,
    ralphDir: getRalphDir(workspaceDir),
    planFile: resolvedPlan.path,
    progressFile: resolvedProgress.path,
    stateFile: getStateFilePath(workspaceDir),
    logsDir: getLogsDir(workspaceDir),
    planUsesLegacyRoot: resolvedPlan.usedLegacy,
    progressUsesLegacyRoot: resolvedProgress.usedLegacy,
    warnings,
    tasks,
    done: planProgress.done,
    total: planProgress.total,
    planError: planProgress.error,
    progressText,
    progressTail: getProgressTail(progressText),
    doneFileExists,
    doneMarkerStatus: getDoneMarkerStatus(tasks, doneFileExists, planProgress.done, planProgress.total),
    stateFileExists: await stateFile.exists(),
    verifierFeedbackCount: tasks.filter((task) => Boolean(task.verifierFeedback)).length,
    contradictionCount: tasks.filter((task) => Boolean(task.verifierFeedback?.contradiction)).length,
  };
}