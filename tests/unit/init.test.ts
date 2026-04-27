import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { runInit, isGeneratedPrd, isGeneratedPrompt, isGeneratedProgress, isGeneratedPlugin, isGeneratedAgents, GENERATED_PROMPT_MARKER, GENERATED_PLUGIN_MARKER, GENERATED_AGENTS_MARKER, GITIGNORE_ENTRIES, GITIGNORE_HEADER, buildGitignoreBlock } from "../../src/init";
import { TempDir } from "../helpers/temp-files";

describe("runInit", () => {
  const tempDir = new TempDir();

  beforeEach(async () => {
    await tempDir.create();
  });

  afterEach(async () => {
    await tempDir.cleanup();
  });

  it("should preserve markdown plan files and write PRD JSON to prd.json", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n- [ ] First task\n- [ ] Second task\n"
    );
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prdPath = tempDir.path(".ralph/prd.json");
    const prdContent = await Bun.file(prdPath).json();
    expect(prdContent.items.length).toBe(2);
    expect(prdContent.items[0]).toMatchObject({
      description: "First task",
      passes: false,
    });

    expect(result.created).toContain(prdPath);
  });

  it("should generate an action-first default prompt template", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] First task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const promptContent = await Bun.file(promptPath).text();
    expect(promptContent).toContain("Your job is to complete exactly ONE unfinished task from {{PLAN_FILE}}");
    expect(promptContent).toContain("Some tasks include deterministic verifications in {{PLAN_FILE}}.");
    expect(promptContent).toContain("Ralph will reject passes=true if deterministic verification fails.");
    expect(promptContent.match(/Some tasks include deterministic verifications in \{\{PLAN_FILE\}\}\./g)?.length).toBe(1);
    expect(promptContent).toContain("Do not add a trailing newline unless the expected content explicitly includes one");
    expect(promptContent).toContain("Do not merely summarize {{PLAN_FILE}} or {{PROGRESS_FILE}}.");
    expect(promptContent).not.toContain("READ all of {{PLAN_FILE}} and {{PROGRESS_FILE}}.");
  });

  it("should extract create exact verification from markdown init source", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Strict exact creation\n\n- [ ] Create `alpha.txt` in the workspace root containing exactly `alpha`.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].verifications).toEqual([
      {
        type: "file_exact_content",
        path: "alpha.txt",
        content: "alpha",
        allowTrailingNewline: false,
      },
    ]);
  });

  it("should extract colon and named-file verification", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n\n- [ ] Create a file named `beta.txt` containing exactly: `beta`.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].verifications?.[0]?.path).toBe("beta.txt");
    expect(prd.items[0].verifications?.[0]?.content).toBe("beta");
  });

  it("should extract plain unquoted create variant", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n\n- [ ] Create gamma.txt containing exactly gamma.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].verifications?.[0]?.path).toBe("gamma.txt");
    expect(prd.items[0].verifications?.[0]?.content).toBe("gamma");
  });

  it("should extract modify exact variants", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n\n- [ ] Change `notes.txt` to contain exactly `new`.\n- [ ] Set `notes.txt` to exactly `new`.\n- [ ] Update `notes.txt` to contain exactly: `new`.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    for (const item of prd.items) {
      expect(item.verifications?.[0]?.path).toBe("notes.txt");
      expect(item.verifications?.[0]?.content).toBe("new");
    }
  });

  it("should extract synthesized exact output verification", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n\n- [ ] Create `combined.txt` containing exactly `left-right`.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].verifications?.[0]?.path).toBe("combined.txt");
    expect(prd.items[0].verifications?.[0]?.content).toBe("left-right");
  });

  it("should store contradictory assertions for later rejection", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n\n- [ ] Create `impossible.txt` containing exactly `alpha` and containing exactly `beta`.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].verifications).toHaveLength(2);
    expect(prd.items[0].verifications?.[0]?.path).toBe("impossible.txt");
    expect(prd.items[0].verifications?.[1]?.path).toBe("impossible.txt");
    expect(prd.items[0].verifications?.[0]?.content).toBe("alpha");
    expect(prd.items[0].verifications?.[1]?.content).toBe("beta");
  });

  it("should keep ambiguous tasks without deterministic verification", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n\n- [ ] Improve README.\n");

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].description).toBe("Improve README.");
    expect(prd.items[0].verifications).toBeUndefined();
  });

  it("should ignore unsafe path assertions from markdown init", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      "# Plan\n\n- [ ] Create `..\\outside.txt` containing exactly `bad`.\n"
    );

    await runInit({
      planFile: planPath,
      progressFile: tempDir.path(".ralph/progress.txt"),
      promptFile: tempDir.path(".ralph/prompt.md"),
      pluginFile: tempDir.path(".opencode/plugin/ralph-write-guardrail.ts"),
      agentsFile: tempDir.path("AGENTS.md"),
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prd = await Bun.file(tempDir.path(".ralph/prd.json")).json() as { items: any[] };
    expect(prd.items[0].description).toContain("..\\outside.txt");
    expect(prd.items[0].verifications).toBeUndefined();
  });

  it("should handle checkmarked tasks and categories in markdown plan", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      `# Plan
- [x] Completed task
- [ ] Incomplete task
- [x] [ui] Completed UI task
- [ ] [backend] Incomplete backend task
- [X] Case insensitive completed task
- [-] Other status treated as incomplete
* List item without checkbox
1. Numbered item without checkbox
`
    );
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prdPath = tempDir.path(".ralph/prd.json");
    const prdContent = await Bun.file(prdPath).json();
    
    // Some tasks might be deduplicated if they are very similar
    // "Completed task" and "Case insensitive completed task" are similar
    expect(prdContent.items.length).toBeLessThanOrEqual(8);
    
    const descriptions = prdContent.items.map((i: any) => i.description);
    
    expect(descriptions).toContain("Completed task");
    expect(descriptions).toContain("Incomplete task");
  });

  it("should filter out noisy lines from markdown plans", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      `# Project Plan
## Overview
Summary: This is a complex project with many details.
Key Assumptions:
- No backend required
- Sample data included

| Feature | Status |
|---------|--------|
| Auth | [ ] |

### Tasks
- [ ] Implement UI
- [ ] Implement Logic
`
    );
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prdPath = tempDir.path(".ralph/prd.json");
    const prdContent = await Bun.file(prdPath).json();
    
    // Should NOT include Summary, assumptions, or table rows
    // Should ONLY include the items that look like tasks
    const descriptions = prdContent.items.map((i: any) => i.description);
    expect(descriptions).toContain("Implement UI");
    expect(descriptions).toContain("Implement Logic");
    expect(descriptions).not.toContain("Summary: This is a complex project with many details.");
    expect(descriptions).not.toContain("No backend required");
    expect(descriptions).not.toContain("| Feature | Status |");
    
    // Only the 2 tasks should be present
    expect(prdContent.items).toHaveLength(2);
  });

  it("should NEVER filter items that have explicit checkboxes", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      `# Plan
- [ ] no console logs (starts with lowercase)
- [ ] No: metadata style task
- [ ] Sample task name (starts with Sample)
`
    );
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prdPath = tempDir.path(".ralph/prd.json");
    const prdContent = await Bun.file(prdPath).json();
    
    // All 3 should be kept because they have [ ]
    expect(prdContent.items).toHaveLength(3);
    const descriptions = prdContent.items.map((i: any) => i.description);
    expect(descriptions).toContain("no console logs (starts with lowercase)");
    expect(descriptions).toContain("No: metadata style task");
    expect(descriptions).toContain("Sample task name (starts with Sample)");
  });

  it("should handle nested checkboxes and subtasks", async () => {
    const planPath = await tempDir.write(
      "plan.md",
      `# Project Plan
- [ ] Parent Task
  - [x] Nested Subtask
    - [ ] Deeply Nested Task
* [ ] Bullet Parent
  * [ ] Bullet Child
1. [ ] Numbered Parent
   1. [ ] Numbered Child
`
    );
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsFile = tempDir.path("AGENTS.md");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prdPath = tempDir.path(".ralph/prd.json");
    const prdContent = await Bun.file(prdPath).json();
    
    const descriptions = prdContent.items.map((i: any) => i.description);
    expect(descriptions).toContain("Parent Task");
    expect(descriptions).toContain("Nested Subtask");
    expect(descriptions).toContain("Deeply Nested Task");
    expect(descriptions).toContain("Bullet Parent");
    expect(descriptions).toContain("Bullet Child");
    expect(descriptions).toContain("Numbered Parent");
    expect(descriptions).toContain("Numbered Child");
    
    // Check completion status of nested item
    const subtask = prdContent.items.find((i: any) => i.description === "Nested Subtask");
    expect(subtask.passes).toBe(true);
  });

  it("should use plan.md when no args and prd.json does not exist", async () => {
    await tempDir.write("plan.md", "# Plan\n- [ ] First task\n- [ ] Second task\n");
    const prdPath = tempDir.path(".ralph/prd.json");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    const originalCwd = process.cwd();
    try {
      process.chdir(tempDir.dir);
      const result = await runInit({
        planFile: prdPath,
        progressFile: progressPath,
        promptFile: promptPath,
        pluginFile: pluginPath,
        agentsFile: agentsPath,
        gitignoreFile: tempDir.path(".gitignore"),
      });

      const prdContent = await Bun.file(prdPath).json();
      // PRD is now wrapped with metadata
      expect(prdContent.metadata).toBeDefined();
      expect(prdContent.items.length).toBe(2);
      expect(result.warnings.some((warning) => warning.includes("plan.md"))).toBe(true);
    } finally {
      process.chdir(originalCwd);
    }
  });

  it("should add frontmatter marker to generated prompt file", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const promptContent = await Bun.file(promptPath).text();
    expect(promptContent.startsWith(GENERATED_PROMPT_MARKER)).toBe(true);
    expect(isGeneratedPrompt(promptContent)).toBe(true);
  });

  it("should include sourceFile in PRD metadata when initialized from a source", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");
    const prdPath = tempDir.path(".ralph/prd.json");

    await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const prdContent = await Bun.file(prdPath).json();
    expect(prdContent.metadata.sourceFile).toBe(planPath);
  });

  it("should create plugin file with marker in .opencode/plugin directory", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const pluginExists = await Bun.file(pluginPath).exists();
    expect(pluginExists).toBe(true);

    const pluginContent = await Bun.file(pluginPath).text();
    expect(pluginContent.startsWith(GENERATED_PLUGIN_MARKER)).toBe(true);
    expect(isGeneratedPlugin(pluginContent)).toBe(true);
    expect(pluginContent).toContain("@opencode-ai/plugin");
    expect(pluginContent).toContain("tool.execute.before");
    expect(pluginContent).toContain(".ralph/prd.json");
    expect(pluginContent).toContain("AGENTS.md");

    expect(result.created).toContain(pluginPath);
  });

  it("should create AGENTS.md with marker when it doesn't exist", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
    });

    const agentsExists = await Bun.file(agentsPath).exists();
    expect(agentsExists).toBe(true);

    const agentsContent = await Bun.file(agentsPath).text();
    expect(agentsContent.startsWith(GENERATED_AGENTS_MARKER)).toBe(true);
    expect(isGeneratedAgents(agentsContent)).toBe(true);
    expect(agentsContent).toContain("Project-Specific Configuration");
    expect(agentsContent).toContain("Common Gotchas");

    expect(result.created).toContain(agentsPath);
  });

  it("should NEVER overwrite existing AGENTS.md even with --force", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    
    // Create an existing AGENTS.md with custom content
    const customAgentsContent = "# My Custom AGENTS.md\n\nDo not overwrite this!";
    const agentsPath = await tempDir.write("AGENTS.md", customAgentsContent);

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
      force: true, // Even with force, AGENTS.md should not be overwritten
    });

    const agentsContent = await Bun.file(agentsPath).text();
    expect(agentsContent).toBe(customAgentsContent);
    expect(result.skipped).toContain(agentsPath);
    expect(result.created).not.toContain(agentsPath);
  });

  it("should respect --force for plugin file but not for AGENTS.md", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    
    // Create existing plugin file
    const { mkdirSync } = await import("fs");
    mkdirSync(tempDir.path(".opencode/plugin"), { recursive: true });
    const oldPluginContent = "// Old plugin content";
    const pluginPath = await tempDir.write(".opencode/plugin/ralph-write-guardrail.ts", oldPluginContent);
    
    // Create existing AGENTS.md
    const customAgentsContent = "# My Custom AGENTS.md";
    const agentsPath = await tempDir.write("AGENTS.md", customAgentsContent);

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: tempDir.path(".gitignore"),
      force: true,
    });

    // Plugin should be overwritten with --force
    const pluginContent = await Bun.file(pluginPath).text();
    expect(pluginContent).not.toBe(oldPluginContent);
    expect(isGeneratedPlugin(pluginContent)).toBe(true);
    expect(result.created).toContain(pluginPath);

    // AGENTS.md should NOT be overwritten even with --force
    const agentsContent = await Bun.file(agentsPath).text();
    expect(agentsContent).toBe(customAgentsContent);
    expect(result.skipped).toContain(agentsPath);
  });

  it("should create new .gitignore with Ralph entries when it doesn't exist", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");
    const gitignorePath = tempDir.path(".gitignore");

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: gitignorePath,
    });

    const gitignoreExists = await Bun.file(gitignorePath).exists();
    expect(gitignoreExists).toBe(true);

    const gitignoreContent = await Bun.file(gitignorePath).text();
    expect(gitignoreContent).toContain(GITIGNORE_HEADER);
    for (const entry of GITIGNORE_ENTRIES) {
      expect(gitignoreContent).toContain(entry);
    }
    expect(result.created).toContain(gitignorePath);
    expect(result.gitignoreAppended).toBeUndefined();
  });

  it("should append Ralph entries to existing .gitignore without duplicates", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");
    
    // Create existing .gitignore with some content
    const existingContent = "node_modules/\n.env\n";
    const gitignorePath = await tempDir.write(".gitignore", existingContent);

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: gitignorePath,
    });

    const gitignoreContent = await Bun.file(gitignorePath).text();
    
    // Original content should be preserved
    expect(gitignoreContent).toContain("node_modules/");
    expect(gitignoreContent).toContain(".env");
    
    // Ralph entries should be added
    expect(gitignoreContent).toContain(GITIGNORE_HEADER);
    for (const entry of GITIGNORE_ENTRIES) {
      expect(gitignoreContent).toContain(entry);
    }
    
    expect(result.created).toContain(gitignorePath);
    expect(result.gitignoreAppended).toBe(true);
  });

  it("should skip .gitignore when all Ralph entries already present", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");
    
    // Create .gitignore that already has all Ralph entries
    const existingContent = `node_modules/
  .env
  # Ralph - AI agent loop files
  .ralph/logs/
  .ralph/tmp/
  .ralph/validation/
  .ralph/state.json
  .ralph/done
  .ralph/pause
  .ralph/lock
  .opencode/plugin/ralph-write-guardrail.ts
  `;
    const gitignorePath = await tempDir.write(".gitignore", existingContent);

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: gitignorePath,
    });

    const gitignoreContent = await Bun.file(gitignorePath).text();
    
    // Content should be unchanged
    expect(gitignoreContent).toBe(existingContent);
    
    // Should be skipped, not created
    expect(result.skipped).toContain(gitignorePath);
    expect(result.created).not.toContain(gitignorePath);
    expect(result.gitignoreAppended).toBeUndefined();
  });

  it("should only add missing Ralph entries to .gitignore", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");
    
    // Create .gitignore that already has some Ralph entries
    const existingContent = `node_modules/
.ralph/state.json
`;
    const gitignorePath = await tempDir.write(".gitignore", existingContent);

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: gitignorePath,
    });

    const gitignoreContent = await Bun.file(gitignorePath).text();
    
    // Original content should be preserved
    expect(gitignoreContent).toContain("node_modules/");
    
    // All Ralph entries should now be present
    for (const entry of GITIGNORE_ENTRIES) {
      expect(gitignoreContent).toContain(entry);
    }
    
    // Count occurrences of .ralph/state.json - should only appear once
    const matches = gitignoreContent.match(/\.ralph\/state\.json/g);
    expect(matches?.length).toBe(1);
    
    expect(result.created).toContain(gitignorePath);
    expect(result.gitignoreAppended).toBe(true);
  });

  it("should handle .gitignore without trailing newline", async () => {
    const planPath = await tempDir.write("plan.md", "# Plan\n- [ ] Task\n");
    const progressPath = tempDir.path(".ralph/progress.txt");
    const promptPath = tempDir.path(".ralph/prompt.md");
    const pluginPath = tempDir.path(".opencode/plugin/ralph-write-guardrail.ts");
    const agentsPath = tempDir.path("AGENTS.md");
    
    // Create .gitignore without trailing newline
    const existingContent = "node_modules/\n.env";  // No trailing newline
    const gitignorePath = await tempDir.write(".gitignore", existingContent);

    const result = await runInit({
      planFile: planPath,
      progressFile: progressPath,
      promptFile: promptPath,
      pluginFile: pluginPath,
      agentsFile: agentsPath,
      gitignoreFile: gitignorePath,
    });

    const gitignoreContent = await Bun.file(gitignorePath).text();
    
    // Original content should be preserved
    expect(gitignoreContent).toContain("node_modules/");
    expect(gitignoreContent).toContain(".env");
    
    // Ralph entries should be properly separated
    expect(gitignoreContent).toContain(GITIGNORE_HEADER);
    
    // Make sure there's a blank line before the header for readability
    expect(gitignoreContent).toContain("\n\n" + GITIGNORE_HEADER);
    
    expect(result.gitignoreAppended).toBe(true);
  });
});

describe("isGeneratedPrd", () => {
  it("should return true for generated PRD with metadata", () => {
    const content = JSON.stringify({
      metadata: {
        generated: true,
        generator: "ralph-init",
        createdAt: "2025-01-01T00:00:00.000Z",
      },
      items: [{ description: "Task", passes: false }],
    });
    expect(isGeneratedPrd(content)).toBe(true);
  });

  it("should return false for plain array PRD", () => {
    const content = JSON.stringify([{ description: "Task", passes: false }]);
    expect(isGeneratedPrd(content)).toBe(false);
  });

  it("should return true for PRD with any custom generator (generator-agnostic)", () => {
    const content = JSON.stringify({
      metadata: {
        generated: true,
        generator: "my-custom-tool",
        createdAt: "2025-01-01T00:00:00.000Z",
      },
      items: [{ description: "Task", passes: false }],
    });
    expect(isGeneratedPrd(content)).toBe(true);
  });

  it("should return false for PRD with empty generator string", () => {
    const content = JSON.stringify({
      metadata: {
        generated: true,
        generator: "",
        createdAt: "2025-01-01T00:00:00.000Z",
      },
      items: [{ description: "Task", passes: false }],
    });
    expect(isGeneratedPrd(content)).toBe(false);
  });

  it("should return false for non-JSON content", () => {
    expect(isGeneratedPrd("# Not JSON")).toBe(false);
  });

  it("should return false for invalid JSON", () => {
    expect(isGeneratedPrd("{ invalid json }")).toBe(false);
  });
});

describe("isGeneratedPrompt", () => {
  it("should return true for prompt with generated frontmatter", () => {
    const content = `---
generated: true
generator: ralph-init
safe_to_delete: true
---
READ all of plan.md`;
    expect(isGeneratedPrompt(content)).toBe(true);
  });

  it("should return false for prompt without frontmatter", () => {
    const content = "READ all of plan.md";
    expect(isGeneratedPrompt(content)).toBe(false);
  });

  it("should return false for prompt with different frontmatter", () => {
    const content = `---
title: My Custom Prompt
---
READ all of plan.md`;
    expect(isGeneratedPrompt(content)).toBe(false);
  });
});

describe("isGeneratedProgress", () => {
  it("should return true for progress with init marker", () => {
    const content = `# Ralph Progress

## Iteration 0 - Initialized 2025-01-01T00:00:00.000Z
- Plan: prd.json
- Notes: Initialized via ralph init.
`;
    expect(isGeneratedProgress(content)).toBe(true);
  });

  it("should return false for user-created progress", () => {
    const content = `# My Progress

## Task 1
- Did something
`;
    expect(isGeneratedProgress(content)).toBe(false);
  });
});

describe("isGeneratedPlugin", () => {
  it("should return true for plugin with generated marker", () => {
    const content = `// Generated by ralph init
// generator: ralph-init
// safe_to_delete: true

import type { Plugin } from "@opencode-ai/plugin"
export const RalphWriteGuardrail: Plugin = async () => { return {} }`;
    expect(isGeneratedPlugin(content)).toBe(true);
  });

  it("should return false for custom plugin", () => {
    const content = `// My custom plugin
import type { Plugin } from "@opencode-ai/plugin"
export const MyPlugin: Plugin = async () => { return {} }`;
    expect(isGeneratedPlugin(content)).toBe(false);
  });
});

describe("isGeneratedAgents", () => {
  it("should return true for AGENTS.md with generated marker", () => {
    const content = `<!-- Generated by ralph init -->
<!-- generator: ralph-init -->
<!-- safe_to_delete: true -->

# AGENTS.md - Project Configuration for AI Agents`;
    expect(isGeneratedAgents(content)).toBe(true);
  });

  it("should return false for custom AGENTS.md", () => {
    const content = `# AGENTS.md - My Custom Configuration

This is my custom configuration file.`;
    expect(isGeneratedAgents(content)).toBe(false);
  });
});

