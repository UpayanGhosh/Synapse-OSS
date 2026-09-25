# Learned style controls

Root-approved scope: preserve the extractor's raw relationship phrase and exact evidence, while storing a separate optional canonical runtime control. Only `tone` and `verbosity` map into the current `StylePolicy` fields (`tone` and `length`). Humor stays descriptive; it does not silently force a formal or playful tone. Current-turn intent remains higher priority than learned style, then defaults.

The accepted controls are field-specific:

| Relationship field | Runtime controls |
| --- | --- |
| `tone` | `professional_precise`, `casual_witty`, `technical_depth`, `creative_playful` |
| `verbosity` | `concise`, `normal`, `detailed` |

`validate_style_control(field, control)` rejects unknown values and cross-field controls. An omitted control is abstention. The extractor prompt asks for a control only when its model-classified interpretation supports one; it preserves the natural phrase as `value` and does not attach controls to `humor`, `formality`, or `address_as`. Evidence/owner checks and the existing transaction still gate writes.

`personal_relationship_updates.style_control` is nullable and added through an in-place SQLite column migration. `get_relationship()` returns raw `preferences`, raw inferred phrases, and an owner-scoped `runtime_style` projection. Inferred controls promote only after two distinct high-confidence source episodes agree on the same field and control; different source phrases remain unchanged, with the newest original phrase shown rather than a fabricated merged statement. Exact legacy aliases are interpreted only from the latest active `tone` or `verbosity` phrase. Superseded sources cannot provide an active control.

For an already stored relationship row, a grounded re-extraction can fill `style_control` only when that row's value is still null. It preserves the existing row ID, raw value, evidence, confidence, and timestamps. Existing processed phrases are not fuzzy-migrated or automatically re-extracted; until a grounded re-extraction or a new explicit preference supplies a control, a non-alias phrase remains descriptive and the runtime uses its prior/default policy. Model-classified intent is not deterministic proof of semantic intent.

The extractor prompt now describes these controls in `workspace/sci_fi_dashboard/user_memory_distiller_v2.py`. Validation lives in `workspace/sci_fi_dashboard/personal_memory.py` and `workspace/sci_fi_dashboard/personal_memory_service.py`; runtime application and current-turn precedence live in `workspace/sci_fi_dashboard/chat_pipeline.py`. The focused acceptance cases are in `tests/memory/test_style_control_projection.py`, `tests/memory/test_style_control_properties.py`, and `tests/memory/test_personal_prompt_runtime.py`.

## RED/GREEN evidence

- Before implementation, the natural-phrase, control isolation, inferred agreement, and invalid-control suite reported **18 failed**. After implementation it passed. A separate same-source legacy re-extraction test first failed because `INSERT OR IGNORE` discarded the control; the constrained null-only upsert made it pass.
- Before retrieval exclusion wiring, six Alice prompt cases failed with `persona_chat() got an unexpected keyword argument 'exclude_episode_id'`; eight other cases passed. After pass-through to scoped recall and `ToolContext`, the focused prompt suite reported **14 passed**.
- The definitive integrated run over `tests/memory`, `tests/gateway`, and `tests/scheduler` reported **144 passed**, with three upstream deprecation warnings and no skips. It used the existing pinned runtime target because default Python cannot import the required `pyarrow.Schema` through this Windows ACL configuration.
- The prior suite's separate file-relay carryover, `tests/tools/test_luna_file_relay.py`, was run once after the integrated run and reported **8 passed**. These are separate invocations; together they cover 152 passing tests without a single combined-run claim.
- Touched-file Ruff, compileall, and `git diff --check` passed. No live Luna inference, real channel transport, or private-reference comparison was run for this phase.

Reproducible integrated command (PowerShell, elevated on this Windows host due to ACLs on the pinned dependency target):

```powershell
$env:PYTHONPATH = "workspace;.tmp/synapse-audit/runtime-target"
$env:TEMP = ".tmp/synapse-audit"
$env:TMP = $env:TEMP
$env:PYTHONPYCACHEPREFIX = ".tmp/synapse-audit/pycache"
rtk proxy python -m pytest -q -p no:cacheprovider -p no:tmpdir -rs tests/memory tests/gateway tests/scheduler
rtk proxy python -m pytest -q -p no:cacheprovider -p no:tmpdir tests/tools/test_luna_file_relay.py
```

The required closeout attempt, `rtk proxy powershell -NoProfile -Command "& .\synapse_context_sync.bat"`, stopped during graph update because `uv` could not open `<USER_UV_CACHE>/sdists-v9/.git` (`Access is denied`, OS error 5). No global cache or settings were changed.
