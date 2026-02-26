# Pre-Push Fixup Instructions

Run these on your personal machine before pushing to GitHub.
The CI is now strict (no more `--exit-zero`), so lint/format must pass.

## Step 1: Create a venv and install tools

```bash
cd Jarvis-OSS
python3 -m venv .fixup-venv
source .fixup-venv/bin/activate   # Mac/Linux
# .fixup-venv\Scripts\Activate.ps1  # Windows

pip install ruff black
```

## Step 2: Auto-fix lint and format

```bash
# Auto-fix what ruff can fix
ruff check --fix workspace/sci_fi_dashboard/

# Format with black
black workspace/sci_fi_dashboard/

# Verify both pass cleanly
ruff check workspace/sci_fi_dashboard/
black --check workspace/sci_fi_dashboard/
```

If ruff reports errors it can't auto-fix, fix them manually.
Common issues: unused imports, shadowed variables, mutable default arguments.

## Step 3: Verify tests pass

```bash
pip install pytest pytest-asyncio pytest-timeout

cd workspace
pytest tests/ -v --timeout=120 --tb=short
cd ..
```

## Step 4: Clean up and commit

```bash
deactivate
rm -rf .fixup-venv

git add -A
git commit -m "fix: auto-format source code with ruff and black"
```

## Step 5: Push everything

```bash
git push origin main
```

Then check GitHub Actions — the CI badge in the README will update
once the workflow completes.

## After push: Delete this file

This file is a one-time checklist. Delete it after the fixes are pushed:

```bash
git rm FIXUP_INSTRUCTIONS.md
git commit -m "chore: remove one-time fixup instructions"
git push
```
