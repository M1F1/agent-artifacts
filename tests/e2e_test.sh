#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting Extended End-to-End Onboarding Test for agent-artifacts...${NC}\n"

# 1. Create a fresh simulated user project
echo -e "${GREEN}[1/11] Creating a fresh mock project with pre-existing rules...${NC}"
rm -rf mock_onboarding_project
mkdir -p mock_onboarding_project
cd mock_onboarding_project

# Create some existing human content so we can test the sentinel wrapper
echo "- Maintainer notes: don't touch" > CLAUDE.md

# 2. List available artifacts
echo -e "\n${GREEN}[2/11] Simulating User: Browsing the catalog...${NC}"
aa list

# 3. Dry run a bundle installation
echo -e "\n${GREEN}[3/11] Simulating User: Dry-running a bundle installation...${NC}"
aa install --bundle base --profile claude --dry-run

# 4. Install specific artifacts
echo -e "\n${GREEN}[4/11] Simulating User: Installing house rules into Claude...${NC}"
aa install house --profile claude --yes

# 5. Verify the sentinel appended successfully
echo -e "\n${GREEN}[5/11] Simulating User: Verifying human notes were kept intact...${NC}"
grep "Maintainer notes" CLAUDE.md > /dev/null && echo "✅ Human content preserved!"
grep "agent-artifacts memory:house" CLAUDE.md > /dev/null && echo "✅ AI rules successfully injected!"

# 6. Simulate drift (User edits a tracked file manually)
echo -e "\n${GREEN}[6/11] Simulating User: Modifying a tracked guideline file (simulating drift)...${NC}"
aa install python-style --profile tabnine --yes
echo "Drift test!" >> .tabnine/guidelines/python-style.md

# 7. Check and Update (Drift Protection)
echo -e "\n${GREEN}[7/11] Simulating User: Running an update, expecting drift protection...${NC}"
aa update --yes
# The CLI should have kept the user's edits (since upstream didn't change, it's just drift, not a conflict)
if grep -q "Drift test!" .tabnine/guidelines/python-style.md; then
    echo "✅ Drift protection worked! The manual change was preserved."
else
    echo "❌ Drift protection failed! The file was overwritten."
    exit 1
fi

# 8. Force replace mode (Advanced)
echo -e "\n${GREEN}[8/11] Simulating User: Overwriting cleanly using force mode...${NC}"
aa install python-style --profile tabnine --force --yes
if grep -q "Drift test!" .tabnine/guidelines/python-style.md; then
    echo "❌ Force install failed to wipe file!"
    exit 1
else
    echo "✅ Force install cleanly wiped the file as requested!"
fi

# 9. Install a bundle
echo -e "\n${GREEN}[9/11] Simulating User: Installing the full backend bundle...${NC}"
aa install --bundle backend --profile claude --yes

# 10. Test JSON Integration mode
echo -e "\n${GREEN}[10/11] Simulating User: Running status in JSON mode (for CI/CD)...${NC}"
aa status --json | grep '"artifact":' > /dev/null && echo "✅ JSON output successfully generated!"

# 11. Clean up
echo -e "\n${GREEN}[11/11] Simulating User: Uninstalling all artifacts...${NC}"
aa uninstall --all --yes

# Clean up the mock project folder
cd ..
rm -rf mock_onboarding_project

echo -e "\n${BLUE}🎉 All Extended End-to-End steps executed successfully! The CLI is rock solid.${NC}"
