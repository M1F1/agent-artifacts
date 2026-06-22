# agent-artifacts (aa)

Install your team's AI artifacts (skills, guidelines, MCP configs, hooks) from one central catalog directly into your local IDE harnesses (Claude Code, Tabnine, OpenCode, etc.). 

Used by humans and agents alike to sync team-wide AI behaviors instantly!

---

## 🚀 Getting Started

**1. Install the CLI:**
```sh
pip install -e .
```
*(Installing in editable mode allows the CLI to dynamically memorize its location, meaning you can run it from anywhere without needing to specify paths).*

**2. Launch the Interactive TUI:**
```sh
aa
```
Simply run `aa` in any project folder to visually browse, install, and uninstall artifacts from the catalog!

---

## 💻 CLI Usage

If you prefer the command line over the interactive UI:

**List all available artifacts:**
```sh
aa list
```

**Install an artifact (e.g., code-review) for a specific AI:**
```sh
aa install code-review --profile claude
aa install house --profile tabnine
```

**Check installed artifacts in the current folder:**
```sh
aa status
```

**Uninstall an artifact:**
```sh
aa uninstall code-review --profile claude
```

### Advanced Modes
By default, installing an agent rule wraps it in invisible HTML sentinels (`<!-- >>>`) so it can be safely updated/uninstalled later without deleting your manual notes. 

If you just want a perfectly clean file and don't care about the tracking, use `replace` mode to completely overwrite the target file with pure markdown:
```sh
aa install house --profile tabnine --agents-mode replace --force
```

---

## 🛠️ Developer Workflow

If you are actively developing `agent-artifacts`, you can enable the automatic version bumping and wheel building script. This ensures that every local commit automatically increments the package version and regenerates the `dist/*.whl` binary for distribution.

To enable the automatic Git hook, simply make the pre-commit script executable:
```sh
chmod +x .git/hooks/pre-commit
```
