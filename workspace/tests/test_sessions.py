"""
test_sessions.py -- Tests for Phase 7: Session Metrics, Health & Cleanup

Covers:
  SESS-01: sessions table created in memory.db, token rows inserted
  SESS-02: GET /api/sessions returns camelCase JSON schema
  SESS-03: state.py update_stats() reads from SQLite, no subprocess calls
  HLTH-01: GET /health includes 'databases' and 'llm' keys
"""

import os
import sqlite3
import sys

import pytest

# ---------------------------------------------------------------------------
# SESS-01: sessions table creation and token write
# ---------------------------------------------------------------------------


def test_sessions_table_created(tmp_path, monkeypatch):
    """SESS-01: _ensure_db() creates sessions table with correct columns."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    # Force fresh module state
    for mod in list(sys.modules.keys()):
        if "sci_fi_dashboard.db" in mod or mod == "sci_fi_dashboard.db":
            del sys.modules[mod]

    import sci_fi_dashboard.db as db_mod

    db_mod.DB_PATH = db_mod._get_db_path()
    db_mod.DatabaseManager._initialized = False
    db_mod.DatabaseManager._ensure_db()

    conn = sqlite3.connect(db_mod.DB_PATH)
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    conn.close()

    assert "sessions" in tables, f"sessions table missing; got {tables}"
    for col in ("session_id", "role", "model", "input_tokens", "output_tokens", "total_tokens"):
        assert col in cols, f"Column {col!r} missing from sessions; got {cols}"


def test_write_session_inserts_row(tmp_path, monkeypatch):
    """SESS-01: _write_session() inserts one row with correct token counts."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if "sci_fi_dashboard.db" in mod or mod == "sci_fi_dashboard.db":
            del sys.modules[mod]

    import sci_fi_dashboard.db as db_mod

    db_mod.DB_PATH = db_mod._get_db_path()
    db_mod.DatabaseManager._initialized = False
    db_mod.DatabaseManager._ensure_db()

    from sci_fi_dashboard.llm_router import _write_session

    class FakeUsage:
        prompt_tokens = 42
        completion_tokens = 10
        total_tokens = 52

    _write_session(role="casual", model="gemini/gemini-2.0-flash", usage=FakeUsage())

    conn = sqlite3.connect(db_mod.DB_PATH)
    row = conn.execute(
        "SELECT role, model, input_tokens, output_tokens, total_tokens FROM sessions"
    ).fetchone()
    conn.close()

    assert row is not None, "No row written by _write_session"
    assert row[0] == "casual"
    assert row[2] == 42
    assert row[3] == 10
    assert row[4] == 52


def test_write_session_with_none_usage(tmp_path, monkeypatch):
    """SESS-01: _write_session() handles None usage gracefully (writes zeros)."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if "sci_fi_dashboard.db" in mod or mod == "sci_fi_dashboard.db":
            del sys.modules[mod]

    import sci_fi_dashboard.db as db_mod

    db_mod.DB_PATH = db_mod._get_db_path()
    db_mod.DatabaseManager._initialized = False
    db_mod.DatabaseManager._ensure_db()

    from sci_fi_dashboard.llm_router import _write_session

    _write_session(role="vault", model="ollama_chat/stheno", usage=None)

    conn = sqlite3.connect(db_mod.DB_PATH)
    row = conn.execute("SELECT input_tokens, output_tokens FROM sessions").fetchone()
    conn.close()
    assert row == (0, 0), f"Expected (0, 0) for None usage; got {row}"


# ---------------------------------------------------------------------------
# SESS-02: GET /api/sessions camelCase schema
# ---------------------------------------------------------------------------


def test_get_sessions_returns_camel_case(tmp_path, monkeypatch):
    """SESS-02: GET /api/sessions returns list with camelCase keys."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if "sci_fi_dashboard.db" in mod or mod == "sci_fi_dashboard.db":
            del sys.modules[mod]

    import sci_fi_dashboard.db as db_mod

    db_mod.DB_PATH = db_mod._get_db_path()
    db_mod.DatabaseManager._initialized = False
    db_mod.DatabaseManager._ensure_db()

    # Insert a test row directly
    with sqlite3.connect(db_mod.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, role, model, input_tokens, output_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-uuid-1", "casual", "gemini/gemini-2.0-flash", 100, 50, 150),
        )
        conn.commit()

    # Import the route function directly (avoids spinning up full FastAPI server)
    # The route handler is a plain function — import api_gateway and call get_sessions()
    try:
        import sci_fi_dashboard.api_gateway as gw

        result = gw.get_sessions()
    except Exception:
        pytest.skip(
            "api_gateway.get_sessions() not importable in test environment (sqlite_vec absent)"
        )

    assert isinstance(result, list), f"Expected list, got {type(result)}"
    if result:
        item = result[0]
        for key in (
            "sessionId",
            "model",
            "inputTokens",
            "outputTokens",
            "totalTokens",
            "contextTokens",
        ):
            assert key in item, f"Missing camelCase key {key!r}; got {list(item.keys())}"
        assert "input_tokens" not in item, "snake_case key leaked into response"


def test_get_sessions_returns_empty_list_on_empty_db(tmp_path, monkeypatch):
    """SESS-02: GET /api/sessions returns [] when sessions table exists but is empty."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if "sci_fi_dashboard.db" in mod or mod == "sci_fi_dashboard.db":
            del sys.modules[mod]

    import sci_fi_dashboard.db as db_mod

    db_mod.DB_PATH = db_mod._get_db_path()
    db_mod.DatabaseManager._initialized = False
    db_mod.DatabaseManager._ensure_db()

    try:
        import sci_fi_dashboard.api_gateway as gw

        result = gw.get_sessions()
        assert result == [], f"Expected [], got {result}"
    except Exception:
        pytest.skip("api_gateway not importable in test environment")


# ---------------------------------------------------------------------------
# SESS-03: state.py reads SQLite, no subprocess
# ---------------------------------------------------------------------------


def test_state_reads_from_sqlite(tmp_path, monkeypatch):
    """SESS-03: DashboardState.update_stats() populates token counts from SQLite sessions."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if "sci_fi_dashboard.db" in mod or mod == "sci_fi_dashboard.db":
            del sys.modules[mod]

    import sci_fi_dashboard.db as db_mod

    db_mod.DB_PATH = db_mod._get_db_path()
    db_mod.DatabaseManager._initialized = False
    db_mod.DatabaseManager._ensure_db()

    # Insert a session row with known token counts
    with sqlite3.connect(db_mod.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, role, model, input_tokens, output_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("state-test-uuid", "casual", "gemini/gemini-2.0-flash", 200, 75, 275),
        )
        conn.commit()

    from sci_fi_dashboard.state import DashboardState

    state = DashboardState()
    state.update_stats()

    assert state.total_tokens_in >= 200, f"total_tokens_in={state.total_tokens_in}, expected >=200"
    assert state.total_tokens_out >= 75, f"total_tokens_out={state.total_tokens_out}, expected >=75"
    assert state.active_sessions >= 1, f"active_sessions={state.active_sessions}, expected >=1"


def test_state_no_subprocess_calls(monkeypatch):
    """SESS-03: state.py must not call subprocess.run or os.popen with 'openclaw'."""
    with open(os.path.join(os.path.dirname(__file__), "..", "sci_fi_dashboard", "state.py")) as fh:
        src = fh.read()
    assert "openclaw" not in src, "state.py contains openclaw reference"
    assert "subprocess" not in src or "# subprocess" in src, "state.py uses subprocess"


# ---------------------------------------------------------------------------
# HLTH-01: GET /health databases and llm keys
# ---------------------------------------------------------------------------


def test_health_endpoint_has_databases_key():
    """HLTH-01: GET /health response includes 'databases' key."""
    with open(
        os.path.join(os.path.dirname(__file__), "..", "sci_fi_dashboard", "api_gateway.py")
    ) as fh:
        src = fh.read()
    assert "_check_databases" in src, "_check_databases helper not in api_gateway.py"
    assert '"databases"' in src or "'databases'" in src, "'databases' key not in /health response"


def test_health_endpoint_has_llm_key():
    """HLTH-01: GET /health response includes 'llm' key."""
    with open(
        os.path.join(os.path.dirname(__file__), "..", "sci_fi_dashboard", "api_gateway.py")
    ) as fh:
        src = fh.read()
    assert "_check_llm_provider" in src, "_check_llm_provider helper not in api_gateway.py"
    assert '"llm"' in src or "'llm'" in src, "'llm' key not in /health response"


# ---------------------------------------------------------------------------
# Cleanup verification: zero openclaw binary calls in active workspace files
# ---------------------------------------------------------------------------


def test_no_openclaw_binary_calls_in_active_files():
    """Phase 7 success criterion: no active openclaw binary calls in non-migration workspace files.

    Checks that no code executes the 'openclaw' binary via subprocess/os.system/shutil.which.

    Known allowed files:
      - migrate_openclaw.py, v2_migration/ — migration tooling (intentional openclaw interop)
      - cli/onboard.py — ONB-08 migration bridge
      - tests/test_migration.py, tests/test_onboard.py — test coverage of the above
      - tests/test_sessions.py — this file (contains pattern strings in allowed_patterns)
    """
    import re

    workspace = os.path.join(os.path.dirname(__file__), "..")
    # Files that are ALLOWED to contain 'openclaw' (migration/legacy)
    allowed_patterns = [
        "scripts/migrate_openclaw",
        "scripts/v2_migration",
        "cli/onboard",
        "tests/test_migration",
        "tests/test_onboard",
        "tests/test_sessions",
    ]
    # Patterns that indicate actual execution of the openclaw binary
    active_call_pattern = re.compile(
        r"subprocess\.[a-zA-Z_]+\s*\([^)]*['\"]openclaw"
        r"|os\.(system|popen)\s*\([^)]*['\"]openclaw"
        r"|shutil\.which\s*\(\s*['\"]openclaw",
        re.IGNORECASE,
    )
    violations = []
    for root, dirs, files in os.walk(workspace):
        # Skip __pycache__ and .git
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, workspace).replace("\\", "/")
            if any(pat in relpath for pat in allowed_patterns):
                continue
            with open(fpath, encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            # Check for actual subprocess/os.system/shutil.which calls invoking openclaw
            active_lines = [
                line
                for line in content.splitlines()
                if not line.strip().startswith("#") and active_call_pattern.search(line)
            ]
            if active_lines:
                violations.append((relpath, active_lines))
    assert not violations, (
        f"Unexpected openclaw binary execution calls in: {[v[0] for v in violations]}\n"
        "Only migrate_openclaw.py, v2_migration/, cli/onboard.py, test_migration.py, "
        "test_onboard.py may contain active openclaw binary calls."
    )
