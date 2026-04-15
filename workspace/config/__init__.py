"""
config — Pydantic-validated configuration system for Synapse-OSS.

Provides layered resolution, merge-patch, env var substitution,
secret redaction, config includes, legacy migration, and group policy.
"""

from __future__ import annotations

from config.env_substitution import substitute_env_vars
from config.group_policy import GroupPolicyCache
from config.includes import resolve_includes
from config.layered_resolution import ConfigResolver
from config.merge_patch import merge_patch
from config.migration import migrate_legacy_config
from config.redaction import redact_snapshot, restore_snapshot
from config.schema import SynapseConfigSchema

__all__ = [
    "ConfigResolver",
    "GroupPolicyCache",
    "SynapseConfigSchema",
    "merge_patch",
    "migrate_legacy_config",
    "redact_snapshot",
    "resolve_includes",
    "restore_snapshot",
    "substitute_env_vars",
]
