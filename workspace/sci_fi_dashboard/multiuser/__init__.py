"""multiuser — Multi-user memory system for Synapse-OSS.

Re-exports every public symbol from the seven submodules so callers can do::

    from sci_fi_dashboard.multiuser import build_session_key, SessionStore, ...
"""

from __future__ import annotations

from sci_fi_dashboard.multiuser.compaction import (
    compact_session,
    estimate_tokens,
    should_compact,
    split_by_token_share,
    strip_tool_result_details,
)
from sci_fi_dashboard.multiuser.context_assembler import (
    CONTEXT_WINDOW_HARD_MIN_TOKENS,
    CONTEXT_WINDOW_WARN_TOKENS,
    ContextWindowTooSmallError,
    assemble_context,
    build_system_prompt,
)
from sci_fi_dashboard.multiuser.identity_linker import resolve_linked_peer_id
from sci_fi_dashboard.multiuser.memory_manager import (
    BOOTSTRAP_FILES,
    MINIMAL_BOOTSTRAP_FILES,
    append_daily_note,
    is_subagent_or_cron_key,
    load_bootstrap_files,
    seed_workspace,
)
from sci_fi_dashboard.multiuser.session_key import (
    ParsedSessionKey,
    build_session_key,
    get_subagent_depth,
    is_cron_key,
    is_subagent_key,
    normalise_agent_id,
    parse_session_key,
)
from sci_fi_dashboard.multiuser.session_store import (
    SessionEntry,
    SessionStore,
)
from sci_fi_dashboard.multiuser.transcript import (
    append_message,
    archive_transcript,
    limit_history_turns,
    load_messages,
    transcript_path,
)

__all__ = [
    # compaction
    "compact_session",
    "estimate_tokens",
    "should_compact",
    "split_by_token_share",
    "strip_tool_result_details",
    # context_assembler
    "CONTEXT_WINDOW_HARD_MIN_TOKENS",
    "CONTEXT_WINDOW_WARN_TOKENS",
    "ContextWindowTooSmallError",
    "assemble_context",
    "build_system_prompt",
    # identity_linker
    "resolve_linked_peer_id",
    # memory_manager
    "BOOTSTRAP_FILES",
    "MINIMAL_BOOTSTRAP_FILES",
    "append_daily_note",
    "is_subagent_or_cron_key",
    "load_bootstrap_files",
    "seed_workspace",
    # session_key
    "ParsedSessionKey",
    "build_session_key",
    "get_subagent_depth",
    "is_cron_key",
    "is_subagent_key",
    "normalise_agent_id",
    "parse_session_key",
    # session_store
    "SessionEntry",
    "SessionStore",
    # transcript
    "append_message",
    "archive_transcript",
    "limit_history_turns",
    "load_messages",
    "transcript_path",
]
