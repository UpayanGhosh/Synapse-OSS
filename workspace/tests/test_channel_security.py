"""Tests for channels/security.py — DmPolicy, ChannelSecurityConfig, PairingStore, resolve_dm_access.

Covers:
- DmPolicy enum values and string behavior
- ChannelSecurityConfig defaults and custom construction
- PairingStore load, approve, revoke, is_approved, load_all, corrupt line handling
- resolve_dm_access for all 4 policy variants
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.channels.security import (
    ChannelSecurityConfig,
    DmPolicy,
    PairingStore,
    resolve_dm_access,
)

# ===========================================================================
# DmPolicy Tests
# ===========================================================================


class TestDmPolicy:
    """Tests for DmPolicy StrEnum."""

    def test_values(self):
        assert DmPolicy.PAIRING == "pairing"
        assert DmPolicy.ALLOWLIST == "allowlist"
        assert DmPolicy.OPEN == "open"
        assert DmPolicy.DISABLED == "disabled"

    def test_is_string(self):
        """DmPolicy members are strings (StrEnum)."""
        assert isinstance(DmPolicy.OPEN, str)
        assert isinstance(DmPolicy.PAIRING, str)


# ===========================================================================
# ChannelSecurityConfig Tests
# ===========================================================================


class TestChannelSecurityConfig:
    """Tests for ChannelSecurityConfig dataclass."""

    def test_defaults(self):
        cfg = ChannelSecurityConfig()
        assert cfg.dm_policy == DmPolicy.OPEN
        assert cfg.allow_from == []
        assert cfg.group_policy == "open"
        assert cfg.group_allow_from == []

    def test_custom_values(self):
        cfg = ChannelSecurityConfig(
            dm_policy=DmPolicy.ALLOWLIST,
            allow_from=["+1234", "+5678"],
            group_policy="restricted",
            group_allow_from=["grp1"],
        )
        assert cfg.dm_policy == DmPolicy.ALLOWLIST
        assert cfg.allow_from == ["+1234", "+5678"]
        assert cfg.group_policy == "restricted"

    def test_no_shared_mutable_defaults(self):
        c1 = ChannelSecurityConfig()
        c2 = ChannelSecurityConfig()
        c1.allow_from.append("x")
        assert "x" not in c2.allow_from


# ===========================================================================
# PairingStore Tests
# ===========================================================================


class TestPairingStore:
    """Tests for PairingStore JSONL persistence."""

    @pytest.mark.asyncio
    async def test_load_empty_dir(self, tmp_path):
        """Loading from nonexistent file yields empty approved set."""
        store = PairingStore("whatsapp", data_root=tmp_path)
        await store.load()
        assert store.load_all() == []

    @pytest.mark.asyncio
    async def test_approve_and_is_approved(self, tmp_path):
        """approve() adds sender, is_approved() returns True."""
        store = PairingStore("whatsapp", data_root=tmp_path)
        await store.load()
        store.approve("user1")
        assert store.is_approved("user1") is True
        assert store.is_approved("user2") is False

    @pytest.mark.asyncio
    async def test_revoke_removes_sender(self, tmp_path):
        """revoke() removes sender from approved set."""
        store = PairingStore("whatsapp", data_root=tmp_path)
        await store.load()
        store.approve("user1")
        store.approve("user2")
        store.revoke("user1")
        assert store.is_approved("user1") is False
        assert store.is_approved("user2") is True

    @pytest.mark.asyncio
    async def test_load_all_returns_sorted(self, tmp_path):
        """load_all() returns sorted list of approved IDs."""
        store = PairingStore("whatsapp", data_root=tmp_path)
        await store.load()
        store.approve("charlie")
        store.approve("alice")
        store.approve("bob")
        result = store.load_all()
        assert result == ["alice", "bob", "charlie"]

    @pytest.mark.asyncio
    async def test_persistence_round_trip(self, tmp_path):
        """Approved senders persist across load cycles."""
        store1 = PairingStore("telegram", data_root=tmp_path)
        await store1.load()
        store1.approve("user_a")
        store1.approve("user_b")

        # Reload from disk
        store2 = PairingStore("telegram", data_root=tmp_path)
        await store2.load()
        assert store2.is_approved("user_a") is True
        assert store2.is_approved("user_b") is True

    @pytest.mark.asyncio
    async def test_revoke_persistence(self, tmp_path):
        """Revoke persists via atomic rewrite — not just append."""
        store1 = PairingStore("slack", data_root=tmp_path)
        await store1.load()
        store1.approve("user_x")
        store1.approve("user_y")
        store1.revoke("user_x")

        # Reload from disk
        store2 = PairingStore("slack", data_root=tmp_path)
        await store2.load()
        assert store2.is_approved("user_x") is False
        assert store2.is_approved("user_y") is True

    @pytest.mark.asyncio
    async def test_corrupt_lines_skipped(self, tmp_path):
        """Corrupt JSONL lines are skipped without crashing."""
        store = PairingStore("test", data_root=tmp_path)
        # Create the file manually with a corrupt line
        store._path.parent.mkdir(parents=True, exist_ok=True)
        store._path.write_text(
            '{"action":"approve","sender_id":"good_user"}\n'
            "NOT VALID JSON\n"
            '{"action":"approve","sender_id":"also_good"}\n'
        )
        await store.load()
        assert store.is_approved("good_user") is True
        assert store.is_approved("also_good") is True

    @pytest.mark.asyncio
    async def test_missing_sender_id_skipped(self, tmp_path):
        """Lines missing sender_id are skipped."""
        store = PairingStore("test", data_root=tmp_path)
        store._path.parent.mkdir(parents=True, exist_ok=True)
        store._path.write_text(
            '{"action":"approve"}\n' '{"action":"approve","sender_id":"valid"}\n'
        )
        await store.load()
        assert store.load_all() == ["valid"]

    @pytest.mark.asyncio
    async def test_approve_then_revoke_then_approve(self, tmp_path):
        """Approve-revoke-approve cycle works correctly."""
        store = PairingStore("test", data_root=tmp_path)
        await store.load()
        store.approve("user1")
        assert store.is_approved("user1") is True
        store.revoke("user1")
        assert store.is_approved("user1") is False
        store.approve("user1")
        assert store.is_approved("user1") is True

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_user_no_error(self, tmp_path):
        """Revoking a non-approved user does not raise."""
        store = PairingStore("test", data_root=tmp_path)
        await store.load()
        store.revoke("ghost")  # should not raise


# ===========================================================================
# resolve_dm_access Tests
# ===========================================================================


class TestResolveDmAccess:
    """Tests for resolve_dm_access() pure function."""

    def test_open_policy_allows_all(self):
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.OPEN)
        assert resolve_dm_access("anyone", cfg) == "allow"

    def test_disabled_policy_denies_all(self):
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.DISABLED)
        assert resolve_dm_access("anyone", cfg) == "deny"

    def test_allowlist_allows_listed(self):
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.ALLOWLIST, allow_from=["user1", "user2"])
        assert resolve_dm_access("user1", cfg) == "allow"
        assert resolve_dm_access("user2", cfg) == "allow"

    def test_allowlist_denies_unlisted(self):
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.ALLOWLIST, allow_from=["user1"])
        assert resolve_dm_access("stranger", cfg) == "deny"

    @pytest.mark.asyncio
    async def test_pairing_allows_from_allow_list(self, tmp_path):
        """Pairing mode: senders in allow_from are always allowed."""
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.PAIRING, allow_from=["trusted"])
        store = PairingStore("test", data_root=tmp_path)
        await store.load()
        assert resolve_dm_access("trusted", cfg, store) == "allow"

    @pytest.mark.asyncio
    async def test_pairing_allows_approved_sender(self, tmp_path):
        """Pairing mode: approved sender in PairingStore is allowed."""
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.PAIRING)
        store = PairingStore("test", data_root=tmp_path)
        await store.load()
        store.approve("approved_user")
        assert resolve_dm_access("approved_user", cfg, store) == "allow"

    @pytest.mark.asyncio
    async def test_pairing_returns_pending_for_unknown(self, tmp_path):
        """Pairing mode: unknown sender returns pending_approval."""
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.PAIRING)
        store = PairingStore("test", data_root=tmp_path)
        await store.load()
        assert resolve_dm_access("unknown", cfg, store) == "pending_approval"

    def test_pairing_without_store_returns_pending(self):
        """Pairing mode without PairingStore and not in allow_from returns pending."""
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.PAIRING)
        assert resolve_dm_access("unknown", cfg, pairing_store=None) == "pending_approval"

    def test_pairing_without_store_but_in_allow_from(self):
        """Pairing mode: sender in allow_from always allowed even without store."""
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.PAIRING, allow_from=["vip"])
        assert resolve_dm_access("vip", cfg, pairing_store=None) == "allow"
