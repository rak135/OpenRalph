/**
 * Platform-aware path handling for Ralph
 *
 * Supports:
 * - macOS: ~/Library/{Logs,Application Support,Caches}/Ralph
 * - Windows: %LOCALAPPDATA%\Ralph\... and %APPDATA%\Ralph
 * - Linux: XDG Base Directory Specification
 *   https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html
 */
import { homedir } from "node:os";
import { join } from "node:path";
import { mkdirSync } from "node:fs";

// ============================================================================
// Workspace runtime path helpers
// ============================================================================

export const RALPH_DIR = ".ralph";

export const LEGACY_PLAN_FILE = "prd.json";
export const LEGACY_PROGRESS_FILE = "progress.txt";
export const LEGACY_PROMPT_FILE = ".ralph-prompt.md";
export const LEGACY_STATE_FILE = ".ralph-state.json";
export const LEGACY_DONE_FILE = ".ralph-done";

export function getRalphDir(workspace: string = process.cwd()): string {
  return join(workspace, RALPH_DIR);
}

export function getPlanPath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "prd.json");
}

export function getProgressPath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "progress.txt");
}

export function getPromptPath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "prompt.md");
}

export function getStateFilePath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "state.json");
}

export function getDonePath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "done");
}

export function getPausePath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "pause");
}

export function getLockPath(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "lock");
}

export function getLogsDir(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "logs");
}

export function getTmpDir(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "tmp");
}

export function getReportsDir(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "reports");
}

export function getValidationDir(workspace: string = process.cwd()): string {
  return join(getRalphDir(workspace), "validation");
}

export function getLegacyPlanPath(workspace: string = process.cwd()): string {
  return join(workspace, LEGACY_PLAN_FILE);
}

export function getLegacyProgressPath(workspace: string = process.cwd()): string {
  return join(workspace, LEGACY_PROGRESS_FILE);
}

export function getLegacyPromptPath(workspace: string = process.cwd()): string {
  return join(workspace, LEGACY_PROMPT_FILE);
}

export function getLegacyStatePath(workspace: string = process.cwd()): string {
  return join(workspace, LEGACY_STATE_FILE);
}

export function getLegacyDonePath(workspace: string = process.cwd()): string {
  return join(workspace, LEGACY_DONE_FILE);
}

export function ensureRalphWorkspaceDirs(workspace: string = process.cwd()): void {
  for (const dir of [
    getRalphDir(workspace),
    getLogsDir(workspace),
    getTmpDir(workspace),
    getReportsDir(workspace),
    getValidationDir(workspace),
  ]) {
    mkdirSync(dir, { recursive: true });
  }
}

export async function resolveCanonicalOrLegacyPath(
  canonicalPath: string,
  legacyPath: string
): Promise<{ path: string; usedLegacy: boolean }> {
  if (await Bun.file(canonicalPath).exists()) {
    return { path: canonicalPath, usedLegacy: false };
  }

  if (await Bun.file(legacyPath).exists()) {
    return { path: legacyPath, usedLegacy: true };
  }

  return { path: canonicalPath, usedLegacy: false };
}

/** Current platform for path resolution */
const platform = process.platform;

// ============================================================================
// XDG Base Directory helpers (Linux only)
// ============================================================================

/**
 * XDG_STATE_HOME for user-specific state files (logs, history, etc).
 * Default: ~/.local/state
 * Used only on Linux.
 */
export function getXdgStateHome(): string {
  return process.env.XDG_STATE_HOME?.trim() || join(homedir(), ".local", "state");
}

/**
 * XDG_CONFIG_HOME for user-specific configuration.
 * Default: ~/.config
 * Used only on Linux.
 */
export function getXdgConfigHome(): string {
  return process.env.XDG_CONFIG_HOME?.trim() || join(homedir(), ".config");
}

/**
 * XDG_CACHE_HOME for user-specific cache files.
 * Default: ~/.cache
 * Used only on Linux.
 */
export function getXdgCacheHome(): string {
  return process.env.XDG_CACHE_HOME?.trim() || join(homedir(), ".cache");
}

// ============================================================================
// Cross-platform directory resolution
// ============================================================================

/**
 * Central logging directory.
 * Can be overridden via RALPH_LOG_DIR environment variable.
 *
 * Paths:
 * - macOS: ~/Library/Logs/Ralph
 * - Windows: %LOCALAPPDATA%\Ralph\Logs
 * - Linux: $XDG_STATE_HOME/ralph/logs (~/.local/state/ralph/logs)
 */
export function getLogDir(): string {
  const override = process.env.RALPH_LOG_DIR?.trim();
  if (override) return override;

  if (platform === "darwin") {
    return join(homedir(), "Library", "Logs", "Ralph");
  }

  if (platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local");
    return join(localAppData, "Ralph", "Logs");
  }

  // Linux - XDG compliant
  return join(getXdgStateHome(), "ralph", "logs");
}

/**
 * State directory for persistent runtime state.
 * Can be overridden via RALPH_STATE_DIR environment variable.
 *
 * Paths:
 * - macOS: ~/Library/Application Support/Ralph
 * - Windows: %LOCALAPPDATA%\Ralph
 * - Linux: $XDG_STATE_HOME/ralph (~/.local/state/ralph)
 */
export function getStateDir(): string {
  const override = process.env.RALPH_STATE_DIR?.trim();
  if (override) return override;

  if (platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "Ralph");
  }

  if (platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local");
    return join(localAppData, "Ralph");
  }

  // Linux - XDG compliant
  return join(getXdgStateHome(), "ralph");
}

/**
 * Configuration directory for user settings.
 * Can be overridden via RALPH_CONFIG_DIR environment variable.
 *
 * Paths:
 * - macOS: ~/Library/Application Support/Ralph
 * - Windows: %APPDATA%\Ralph
 * - Linux: $XDG_CONFIG_HOME/ralph (~/.config/ralph)
 */
export function getConfigDir(): string {
  const override = process.env.RALPH_CONFIG_DIR?.trim();
  if (override) return override;

  if (platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "Ralph");
  }

  if (platform === "win32") {
    const appData = process.env.APPDATA || join(homedir(), "AppData", "Roaming");
    return join(appData, "Ralph");
  }

  // Linux - XDG compliant
  return join(getXdgConfigHome(), "ralph");
}

/**
 * Cache directory for temporary/regenerable files.
 * Can be overridden via RALPH_CACHE_DIR environment variable.
 *
 * Paths:
 * - macOS: ~/Library/Caches/Ralph
 * - Windows: %LOCALAPPDATA%\Ralph\Cache
 * - Linux: $XDG_CACHE_HOME/ralph (~/.cache/ralph)
 */
export function getCacheDir(): string {
  const override = process.env.RALPH_CACHE_DIR?.trim();
  if (override) return override;

  if (platform === "darwin") {
    return join(homedir(), "Library", "Caches", "Ralph");
  }

  if (platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local");
    return join(localAppData, "Ralph", "Cache");
  }

  // Linux - XDG compliant
  return join(getXdgCacheHome(), "ralph");
}

// ============================================================================
// Utility functions
// ============================================================================

/**
 * Ensure the log directory exists, creating it if necessary.
 */
export function ensureLogDir(): string {
  const dir = getLogDir();
  mkdirSync(dir, { recursive: true });
  return dir;
}

/**
 * Get the path to the central log file.
 * Logs are stored in platform-appropriate directory for persistence and easy monitoring.
 */
export function getLogFilePath(): string {
  return join(ensureLogDir(), "ralph.log");
}

/**
 * Get the path to a dated rolling log file (YYYY-MM-DD format).
 */
export function getRollingLogPath(): string {
  const date = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  return join(ensureLogDir(), `ralph-${date}.log`);
}
