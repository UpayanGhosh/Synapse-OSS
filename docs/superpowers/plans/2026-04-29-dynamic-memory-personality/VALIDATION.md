# Dynamic Memory Personality Validation

## Fresh DB Test

Command:

```powershell
$env:TEMP='C:\tmp'; $env:TMP='C:\tmp'; D:\Shorty\Synapse-OSS\.venv\Scripts\python.exe -m pytest workspace\tests\test_dynamic_memory_personality_acceptance.py -q -o cache_dir=C:\tmp\pytest-cache-synapse-acceptance
```

Expected:

- 1 test passes.
- `documents == 1`.
- `facts >= 2`.
- `affect == 1`.
- Prompt contains `concise technical replies`.
- Prompt contains `Blue Lantern`.

## Installed Synapse Save Probe

Command:

```powershell
D:\Shorty\Synapse-OSS\.venv\Scripts\python.exe workspace\synapse_cli.py memory save-probe --content "I prefer crisp technical replies."
```

Expected:

- CLI prints `documents=<previous + 1>`.
- CLI prints `memory_affect=<previous + 1>`.
- LanceDB `memories` row count increases by 1.

## Two User Differentiation Probe

Command:

```powershell
D:\Shorty\Synapse-OSS\.venv\Scripts\python.exe workspace\scripts\eval_personality_differentiation.py
```

Expected:

- `user_a_contains` is `concise technical replies`.
- `user_b_contains` is `warm emotionally supportive replies`.
- `prompts_are_different` is `true`.
