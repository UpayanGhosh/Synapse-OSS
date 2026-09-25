# Development tooling report

## Hypothesis

Added `hypothesis==6.168.1` to the `dev` optional dependency and `requirements-dev.txt`.
Installed it into the repo-local audit target without changing the project runtime environment:

```powershell
rtk proxy uv pip install --target .tmp\synapse-audit\runtime-target hypothesis==6.168.1 --cache-dir .tmp\uv-cache
```

Verified imports report Hypothesis `6.168.1` and its required `sortedcontainers` `2.4.0`.
The property suite is [test_style_control_properties.py](../../../../tests/memory/test_style_control_properties.py).
It covers the field-specific enum contract, generated malformed controls rolling back an
earlier relationship update, and exact Unicode profile-value/evidence retention. Run it with:

```powershell
rtk proxy python -c "import sys; sys.path[:0] = [r'.tmp/synapse-audit/runtime-target', 'workspace']; import pytest; raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests/memory/test_style_control_properties.py']))"
```

Result: `5 passed`; targeted `python -m ruff check` also passed. Cache provider is disabled
because this Windows workspace denies pytest's default temp/cache paths.

The existing `uv.lock` was stale against `pyproject.toml`, recording only six root
dependencies. The lock was repaired and now includes the manifest's dependency groups and
Hypothesis pin. `uv lock --check --offline` passed with `UV_CACHE_DIR=.tmp/uv-cache`.

## RTK telemetry

RTK `0.49.0` now records telemetry in the normal sandbox. Its supported
`[tracking].database_path` setting points to the ignored repo-local `.tmp/rtk/history.db`;
the original config file was absent before this workspace setup. This path is specific to
this workspace, not a universal RTK default. A verified `rtk gain` snapshot reported 90
tracked commands, 144.7K estimated output tokens saved, and 27.9% savings. Those numbers
estimate filtered command output, not model billing or end-to-end token consumption.

## Context sync

`synapse_context_sync.bat` and `synapse_context_sync.sh` keep uv and MemPalace state in the
ignored repo-local `.tmp` directory and run pinned offline tools. The default MemPalace pass
mines `tasks` and `docs/audits` separately, with `--limit 50` on each. Missing directories are
reported and skipped. Set `SYNAPSE_CONTEXT_FULL_MINE=1` to opt into the previous full-project
mine. The earlier broad mine's execution session was lost; its exit status is unknown, so its
drawer count is not completion evidence.

The bounded Windows sync completed with exit 0: graph update, status, risk scan, then MemPalace
processed 3 task files (30 drawers) and 17 audit files (200 drawers), ending with
`[OK] Context sync complete.` A copied script under ignored `.tmp` with no local tool binaries
returned exit 1, verifying the preflight failure path. Git-bundled Bash parsed the shell script
with `bash -n` and exit 0. `.gitignore` excludes the generated root pytest cache directories,
the memory-test temporary directories, and `v/cache`.

Sources: [Hypothesis 6.168.1 release](https://github.com/HypothesisWorks/hypothesis/releases/tag/v6.168.1),
[Hypothesis quickstart](https://hypothesis.readthedocs.io/en/latest/quickstart.html),
[RTK config reference](https://github.com/rtk-ai/rtk/blob/develop/docs/guide/getting-started/configuration.md),
[RTK Windows AppContainer tracking issue](https://github.com/rtk-ai/rtk/issues/1577).
