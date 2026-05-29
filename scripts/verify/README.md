# scripts/verify/

Ad-hoc verification scripts that exercise individual subsystems end-to-end with
mock dependencies. They are **not** pytest tests — they run as standalone CLI
programs (`python scripts/verify/<name>.py`) and print human-readable output for
manual inspection. Use them as smoke checks during development when you want a
quick "does this still wire up?" signal without booting the full gateway. They
were relocated here from `workspace/sci_fi_dashboard/` to keep that production
package free of one-off harnesses.

| Script | Subsystem under test |
|--------|----------------------|
| `verify_dual_cognition.py` | `DualCognitionEngine.think()` with mocked memory + LLM |
| `verify_soul.py` | Knowledge graph + entity gate slang -> entity resolution |
