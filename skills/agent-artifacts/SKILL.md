---
name: agent-artifacts
description: How to use the agent-artifacts CLI to manage team guidelines and skills
---
# Using the `agent-artifacts` CLI (aa)

You are equipped with the `agent-artifacts` CLI (alias `aa`), a tool to install, update, and manage team-wide AI guidelines, skills, and configuration.

## Commands

Always use the short alias `aa`. 
The CLI defaults to the local artifact catalog installation path automatically.

### 1. `aa list`
List all available artifacts in the catalog.
* Example: `aa list --type skill`
* Example: `aa list --json` (Best for you to parse programmatically)

### 2. `aa status`
Check the status of locally installed artifacts in the current project directory.
* Example: `aa status`

### 3. `aa install <NAME> --profile <PROFILE>`
Install an artifact into the current project directory for a specific AI harness.
* Supported profiles: `claude`, `tabnine`, `opencode`, `vibe`.
* When installing single artifacts for a user, recommend using the `--agents-mode replace --force` flags if they don't want tracking sentinels cluttering their rules file.
* Example: `aa install house --profile claude`
* Example: `aa install code-review --profile tabnine --agents-mode replace --force`

### 4. `aa uninstall <NAME> --profile <PROFILE>`
Uninstall an artifact from the current project directory.
* Example: `aa uninstall house --profile claude`

## Rules for Agents
- When the user asks you to "install the house rules" or "fetch the standard skills", you should execute the `aa install` command.
- When asked what artifacts are available, run `aa list --json` and summarize the results.
- Never use the TUI (just running `aa` with no arguments); always use the subcommands with explicit arguments.
- If a command fails due to a conflict, inspect the files and advise the user, or use `--force` if authorized.
