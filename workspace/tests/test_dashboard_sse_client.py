from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_sse_client_on_event_does_not_register_missing_dispatcher() -> None:
    script = (ROOT / "workspace" / "sci_fi_dashboard" / "static" / "dashboard" / "synapse.js").read_text(
        encoding="utf-8"
    )

    on_event_start = script.index("  onEvent(type, handler) {")
    open_source_start = script.index("  _openSource() {", on_event_start)
    on_event_body = script[on_event_start:open_source_start]

    assert "this._dispatch" not in on_event_body
    assert "this._handlers[type].push(handler);" in on_event_body
