"""OBS-02: redact_identifier() tests. Wave 0 scaffold — will turn green in Plan 13-01."""

import re

import pytest

# Import from module Plan 13-01 will create. Raises ImportError on Wave 0 — expected.
pytest.importorskip("sci_fi_dashboard.observability.redact", reason="Plan 13-01 creates this")
from sci_fi_dashboard.observability.redact import redact_identifier  # noqa: E402


@pytest.mark.unit
def test_jid_redaction_golden():
    """OBS-02: A real WhatsApp JID must not leak its raw digit run."""
    out = redact_identifier("1234567890@s.whatsapp.net")
    # Must be stable "id_<8hex>" form, never contain 10-digit run
    assert re.fullmatch(r"id_[0-9a-f]{8}", out), f"unexpected shape: {out}"
    assert "1234567890" not in out
    assert "@s.whatsapp.net" not in out


@pytest.mark.unit
def test_redaction_idempotent():
    """OBS-02: redact(redact(x)) == redact(x) — stable under double-application."""
    once = redact_identifier("1234567890@s.whatsapp.net")
    twice = redact_identifier(once)
    assert once == twice, f"not idempotent: once={once} twice={twice}"


@pytest.mark.unit
def test_salt_sourced_correctly(tmp_path, monkeypatch):
    """OBS-02: Salt must be sourced from ~/.synapse/state/logging_salt (created if missing)."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    # Force re-import to pick up new salt path
    import importlib

    from sci_fi_dashboard.observability import redact as redact_mod

    importlib.reload(redact_mod)
    salt_path = tmp_path / "state" / "logging_salt"
    assert salt_path.exists(), f"salt file not created at {salt_path}"
    assert len(salt_path.read_bytes()) >= 16, "salt must be >= 16 bytes (CSPRNG)"


@pytest.mark.unit
def test_fuzz_no_digit_leak():
    """OBS-02: 1000 random 10-15 digit JIDs — zero outputs contain any 10-digit run."""
    import random

    random.seed(42)
    digit_run = re.compile(r"\d{10,}")
    for _ in range(1000):
        length = random.randint(10, 15)
        digits = "".join(str(random.randint(0, 9)) for _ in range(length))
        jid = f"{digits}@s.whatsapp.net"
        out = redact_identifier(jid)
        assert not digit_run.search(out), f"digit leak in redacted output: {out!r}"


@pytest.mark.unit
def test_bracketed_placeholders_passthrough():
    """OBS-02 (checker fix — T-13-PLACEHOLDER-01): bracketed sentinels are system
    markers, NOT user-supplied identifiers. They MUST pass through unchanged so
    grep/dashboard filters stay stable across runs. Re-hashing them would
    produce a meaningless id_XXXX and break log filters.

    Concrete cases (checker fix — exact assertions from revision_context):
      redact_identifier("<none>")    == "<none>"
      redact_identifier("<empty>")   == "<empty>"
      redact_identifier("<no-run>")  == "<no-run>"
      redact_identifier("<unknown>") == "<unknown>"
    """
    # Checker fix — exact assertions
    assert (
        redact_identifier("<none>") == "<none>"
    ), "bracketed sentinel <none> must pass through unchanged"
    assert (
        redact_identifier("<empty>") == "<empty>"
    ), "bracketed sentinel <empty> must pass through unchanged"
    # Additional sentinels to lock the contract
    assert (
        redact_identifier("<no-run>") == "<no-run>"
    ), "bracketed sentinel <no-run> must pass through unchanged"
    assert (
        redact_identifier("<unknown>") == "<unknown>"
    ), "bracketed sentinel <unknown> must pass through unchanged"
    # Must NOT be hashed — output should NOT match id_<8hex> shape
    for sentinel in ("<none>", "<empty>", "<no-run>", "<unknown>"):
        out = redact_identifier(sentinel)
        assert not re.fullmatch(
            r"id_[0-9a-f]{8}", out
        ), f"sentinel {sentinel!r} was hashed instead of passed through: {out!r}"
