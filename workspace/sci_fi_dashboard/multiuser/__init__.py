"""multiuser — Multi-user memory system for Synapse-OSS.

Re-exports every public symbol from the submodules so callers can do::

    from sci_fi_dashboard.multiuser import build_session_key, SessionStore, ...
"""

from __future__ import annotations

from sci_fi_dashboard.multiuser.compaction import (
    compact_session,
    compute_adaptive_chunk_ratio,
    estimate_tokens,
    make_compact_fn,
    prune_history_for_context_share,
    should_compact,
    split_by_token_share,
    strip_tool_result_details,
    summarize_with_fallback,
)
from sci_fi_dashboard.multiuser.context_assembler import (
    CONTEXT_WINDOW_HARD_MIN_TOKENS,
    CONTEXT_WINDOW_WARN_TOKENS,
    ContextWindowTooSmallError,
    assemble_context,
    build_system_prompt,
)
from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache
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
    LockMetadata,
    SessionEntry,
    SessionStore,
    SynapseFileLock,
    clean_stale_lock_files,
)
from sci_fi_dashboard.multiuser.tool_loop_detector import (
    ToolLoopDetector,
    ToolLoopError,
    ToolLoopLevel,
)
from sci_fi_dashboard.multiuser.transcript import (
    RepairReport,
    append_message,
    archive_transcript,
    limit_history_turns,
    load_messages,
    repair_all_transcripts,
    repair_orphaned_tool_pairs,
    transcript_path,
)

__all__ = [
    # compaction
    "compact_session",
    "compute_adaptive_chunk_ratio",
    "estimate_tokens",
    "make_compact_fn",
    "prune_history_for_context_share",
    "should_compact",
    "split_by_token_share",
    "strip_tool_result_details",
    "summarize_with_fallback",
    # context_assembler
    "CONTEXT_WINDOW_HARD_MIN_TOKENS",
    "CONTEXT_WINDOW_WARN_TOKENS",
    "ContextWindowTooSmallError",
    "assemble_context",
    "build_system_prompt",
    # conversation_cache
    "ConversationCache",
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
    "LockMetadata",
    "SessionEntry",
    "SessionStore",
    "SynapseFileLock",
    "clean_stale_lock_files",
    # tool_loop_detector
    "ToolLoopDetector",
    "ToolLoopError",
    "ToolLoopLevel",
    # transcript
    "RepairReport",
    "append_message",
    "archive_transcript",
    "limit_history_turns",
    "load_messages",
    "repair_all_transcripts",
    "repair_orphaned_tool_pairs",
    "transcript_path",
]
