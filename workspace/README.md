# Agent Workspace

This folder is the runtime agent workspace used by Synapse.

For full setup and operation, start with [HOW_TO_RUN.md](../HOW_TO_RUN.md) and then read [docs/agent-workspace.md](../docs/agent-workspace.md).

## Workspace Purpose

The agent workspace is where runtime state, agent identity/context markdown, and local operational data live. It is separate from source code ownership boundaries and is designed to persist across daily usage.

## Canonical Files

Canonical workspace context files:

- `CORE.md`
- `CODE.md`
- `MEMORY.md`

Additional bootstrap/context files are managed under this directory as part of onboarding and repair flows.

## Non-Overwrite Policy

Workspace seeding/repair never overwrites existing workspace markdown files. Missing required files may be created, but existing user-edited files are preserved.

## Repair Command

Use doctor auto-repair to restore missing required workspace artifacts:

```bash
cd workspace
python synapse_cli.py doctor --fix
```

## Existing-Install Migration Note

If you already have an existing install, do not delete or recreate your workspace. Run doctor repair first, then review the canonical files list above and add any missing files intentionally.

## Targeted Test Commands

Run focused validation for workspace/bootstrap/doctor behavior:

```bash
cd workspace
pytest tests/test_doctor.py -v
pytest tests/test_onboard.py -k ensure_agent_workspace -v
pytest tests/test_agent_workspace_prefix.py -v
pytest tests/test_multiuser.py -k bootstrap -v
```
