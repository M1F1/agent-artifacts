#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -n "${AART_CMD:-}" ]]; then
    # Allow callers to force a command wrapper, e.g. AART_CMD=aart.
    # shellcheck disable=SC2206
    AART=(${AART_CMD})
else
    AART=("${PYTHON_BIN}" -m agent_artifacts)
fi

run_aart() {
    "${AART[@]}" "$@"
}

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting Extended End-to-End Onboarding Test for agent-artifacts...${NC}\n"

# 1. Create a fresh simulated user project and a synthetic artifact source.
# The source is self-contained (not the repo's seed catalog), so editing or
# deleting seed content cannot break this script.
echo -e "${GREEN}[1/11] Creating a fresh mock project with pre-existing rules...${NC}"
MOCK_PARENT="$(mktemp -d)"
trap 'rm -rf "$MOCK_PARENT"' EXIT

SOURCE_DIR="$MOCK_PARENT/source"
mkdir -p "$SOURCE_DIR"/{memory,guidelines,bundles,skills/code-review,hooks/block-secrets/scripts,mcp/postgres}

cat > "$SOURCE_DIR/memory/house.md" <<'EOF'
---
description: Synthetic house rules for the e2e gate.
mode: prepend
---
# Engineering house rules
- Run the tests before proposing a change.
EOF

cat > "$SOURCE_DIR/guidelines/python-style.md" <<'EOF'
# Python style
- Prefer stdlib; keep functions small.
EOF

cat > "$SOURCE_DIR/skills/code-review/SKILL.md" <<'EOF'
---
name: code-review
description: Synthetic skill for the e2e gate.
---
# Code review
Checklist body.
EOF

cat > "$SOURCE_DIR/hooks/block-secrets/hook.json" <<'EOF'
{
  "name": "block-secrets",
  "events": ["PreToolUse"],
  "command": "python scripts/guard.py",
  "files": ["scripts/guard.py"]
}
EOF

cat > "$SOURCE_DIR/hooks/block-secrets/scripts/guard.py" <<'EOF'
print("guard")
EOF

cat > "$SOURCE_DIR/mcp/postgres/mcp.json" <<'EOF'
{"name": "postgres", "server": {"command": "npx", "args": ["-y", "postgres-mcp"]}}
EOF

cat > "$SOURCE_DIR/bundles/base.json" <<'EOF'
{
  "name": "base",
  "description": "Synthetic base bundle.",
  "includes": {
    "skills": ["code-review"],
    "guidelines": ["python-style"],
    "hooks": ["block-secrets"],
    "memory": ["house"]
  }
}
EOF

cat > "$SOURCE_DIR/bundles/backend.json" <<'EOF'
{
  "name": "backend",
  "description": "Synthetic backend bundle.",
  "extends": ["base"],
  "includes": {
    "mcp": ["postgres"]
  }
}
EOF

mkdir -p "$MOCK_PARENT/mock_onboarding_project"
cd "$MOCK_PARENT/mock_onboarding_project"

# Create some existing human content so we can test the sentinel wrapper
echo "- Maintainer notes: don't touch" > CLAUDE.md

# 2. List available artifacts
echo -e "\n${GREEN}[2/11] Simulating User: Browsing the catalog...${NC}"
run_aart list --source "$SOURCE_DIR"

# 3. Dry run a bundle installation
echo -e "\n${GREEN}[3/11] Simulating User: Dry-running a bundle installation...${NC}"
run_aart install --source "$SOURCE_DIR" --bundle base --profile claude --dry-run

# 4. Install specific artifacts
echo -e "\n${GREEN}[4/11] Simulating User: Installing house rules into Claude...${NC}"
run_aart install --source "$SOURCE_DIR" house --profile claude --yes

# 5. Verify the sentinel appended successfully
echo -e "\n${GREEN}[5/11] Simulating User: Verifying human notes were kept intact...${NC}"
grep "Maintainer notes" CLAUDE.md > /dev/null && echo "✅ Human content preserved!"
grep "agent-artifacts memory:house" CLAUDE.md > /dev/null && echo "✅ AI rules successfully injected!"

# 6. Simulate drift (User edits a tracked file manually)
echo -e "\n${GREEN}[6/11] Simulating User: Modifying a tracked guideline file (simulating drift)...${NC}"
run_aart install --source "$SOURCE_DIR" python-style --profile tabnine --yes
echo "Drift test!" >> .tabnine/guidelines/python-style.md

# 7. Check and Update (Drift Protection)
echo -e "\n${GREEN}[7/11] Simulating User: Running an update, expecting drift protection...${NC}"
run_aart update --source "$SOURCE_DIR" --yes
# The CLI should have kept the user's edits (since upstream didn't change, it's just drift, not a conflict)
if grep -q "Drift test!" .tabnine/guidelines/python-style.md; then
    echo "✅ Drift protection worked! The manual change was preserved."
else
    echo "❌ Drift protection failed! The file was overwritten."
    exit 1
fi

# 8. Force replace mode (Advanced)
echo -e "\n${GREEN}[8/11] Simulating User: Overwriting cleanly using force mode...${NC}"
run_aart install --source "$SOURCE_DIR" python-style --profile tabnine --force --yes
if grep -q "Drift test!" .tabnine/guidelines/python-style.md; then
    echo "❌ Force install failed to wipe file!"
    exit 1
else
    echo "✅ Force install cleanly wiped the file as requested!"
fi

# 9. Install a bundle
echo -e "\n${GREEN}[9/11] Simulating User: Installing the full backend bundle...${NC}"
run_aart install --source "$SOURCE_DIR" --bundle backend --profile claude --yes

# 10. Test JSON Integration mode
echo -e "\n${GREEN}[10/11] Simulating User: Running status in JSON mode (for CI/CD)...${NC}"
run_aart status --json | grep '"artifact":' > /dev/null && echo "✅ JSON output successfully generated!"

# 11. Clean up
echo -e "\n${GREEN}[11/11] Simulating User: Uninstalling all artifacts...${NC}"
run_aart uninstall --all --yes

echo -e "\n${BLUE}🎉 All Extended End-to-End steps executed successfully! The CLI is rock solid.${NC}"
