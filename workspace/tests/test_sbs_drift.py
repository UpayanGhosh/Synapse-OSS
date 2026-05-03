"""SBS drift regression — for known synthetic conversation patterns, the profile
fields update predictably (or stay stable). Catches regressions where the batch
processor silently changes the distillation algorithm.

Pipeline entry point used:
    SBSOrchestrator.on_message()  -> realtime processing + SQLite ingestion
    SBSOrchestrator.force_batch() -> deterministic synchronous BatchProcessor.run()

LLM stub strategy: NONE NEEDED.
    The entire SBS distillation pipeline (RealtimeProcessor + BatchProcessor +
    ExemplarSelector) is purely deterministic — regex mood detection, lexicon
    sentiment, word-frequency counters, and SQL queries. No litellm/Ollama/Gemini
    calls live anywhere on the rebuild path. We only seed `random.seed()` to make
    the ExemplarSelector wildcard slot deterministic, and we monkeypatch the
    orchestrator's threaded `_schedule_batch` into a no-op so the only batch
    run is our explicit `force_batch(full_rebuild=True)` — otherwise the
    50-msg auto-trigger races our synchronous call.

These tests assert *contract* (every layer present, fields update in the expected
direction), not LLM-quality. They will catch:
    - A regression that drops a profile layer.
    - A regression that flaps `core_identity` (which is documented IMMUTABLE).
    - A regression where vocabulary stops accumulating salient words.
    - A regression where mood detection silently stops firing on stress signals.
"""

import random
import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator  # noqa: E402
from sci_fi_dashboard.sbs.profile.manager import ProfileManager  # noqa: E402

# 50-msg threshold per SBSConfig.batch_threshold; bump past it for 1+ rebuilds.
_PAST_THRESHOLD = 60
_TWO_REBUILDS = 110


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _deterministic_random():
    """Seed stdlib random so ExemplarSelector wildcard slot is deterministic."""
    random.seed(0xC0FFEE)
    yield


@pytest.fixture
def fresh_sbs(tmp_path):
    """Fresh SBSOrchestrator with empty state, isolated to tmp_path.

    The orchestrator's threaded `_schedule_batch` is patched to a no-op so
    only our explicit `force_batch()` calls drive the rebuild. Without this,
    the 50-msg auto-trigger spins a daemon thread that races the test reads.
    """
    orch = SBSOrchestrator(data_dir=str(tmp_path / "sbs_data"))
    # Disable the threaded auto-batch path; tests own the rebuild cadence.
    orch._schedule_batch = lambda: None
    return orch


def synthetic_msg(content: str, *, role: str = "user") -> dict:
    """Factory for the canonical synthetic-message shape used by `run_batch_pipeline`.

    Kept as a helper so tests read like the spec — `synthetic_msg("yes.")` —
    without exposing the orchestrator's full RawMessage signature.
    """
    return {"role": role, "content": content}


def run_batch_pipeline(orch: SBSOrchestrator, messages: list) -> SBSOrchestrator:
    """Feed `messages` through on_message() then force a synchronous batch rebuild.

    `messages` may be a list of plain strings (treated as user content) or dicts
    produced by `synthetic_msg`. Returns the same orchestrator (mutated in
    place) so tests can chain calls across multiple rebuilds.
    """
    for m in messages:
        if isinstance(m, dict):
            orch.on_message(role=m.get("role", "user"), content=m["content"], session_id="drift-test")
        else:
            orch.on_message(role="user", content=str(m), session_id="drift-test")
    # Synchronous rebuild — bypasses the thread-scheduled path so tests are
    # deterministic. force_batch() also resets _unbatched_count.
    orch.force_batch(full_rebuild=True)
    return orch


def profile_layer(orch: SBSOrchestrator, name: str) -> dict:
    """Convenience accessor — orch.profile_mgr.load_layer wraps file IO."""
    return orch.profile_mgr.load_layer(name)


# ---------------------------------------------------------------------------
# Stability tests — same input, profile must not flap
# ---------------------------------------------------------------------------


def test_terse_inputs_keep_message_length_small(fresh_sbs):
    """Terse user messages must drive the linguistic avg_message_length down.

    NOTE: the schema's actual linguistic field set has no `directness` (see
    sbs/profile/manager.py defaults — `current_style` carries `banglish_ratio`,
    `avg_message_length`, `emoji_frequency`). For "yes." style inputs, the
    rolling-weighted avg_message_length should stay <= 2 words.
    """
    msgs = [synthetic_msg("yes.") for _ in range(_PAST_THRESHOLD)]
    orch = run_batch_pipeline(fresh_sbs, msgs)

    linguistic = profile_layer(orch, "linguistic")
    avg_len = linguistic["current_style"]["avg_message_length"]
    # Each "yes." is 1 word; allow tiny rounding slack.
    assert avg_len <= 2.0, f"avg_message_length {avg_len} too high for terse corpus"
    # And the linguistic layer must record that an update happened.
    assert linguistic.get("last_updated") is not None


def test_emotional_state_shifts_under_stress(fresh_sbs):
    """Stress-keyworded messages must move dominant mood to a stress family.

    `MOOD_KEYWORDS["stressed"]` matches "deadline"; "overwhelmed" routes to
    "anxious". Either is an acceptable shift away from the default "neutral".
    Note: emotional_state is hot-updated by RealtimeProcessor — batch run does
    not overwrite it. The mood detector fires on every user message, so by the
    time we read the layer, the dominant mood reflects the most recent inputs.
    """
    calm = [synthetic_msg("everything's good") for _ in range(50)]
    stressed = [
        synthetic_msg("I can't keep up, deadlines everywhere, exhausted") for _ in range(50)
    ]
    orch = run_batch_pipeline(fresh_sbs, calm + stressed)

    emotional = profile_layer(orch, "emotional_state")
    pattern = emotional["current_dominant_mood"]
    assert pattern in {"stressed", "anxious", "overwhelmed", "tired"}, (
        f"got {pattern!r} — expected a stress-family mood after deadline-heavy inputs"
    )
    # And mood_history must have logged the shift.
    assert len(emotional["mood_history"]) > 0


def test_vocabulary_layer_grows_with_unique_words(fresh_sbs):
    """Unique tokens across 60+ messages must populate the vocabulary registry.

    The user-spec'd `salient` field does not exist in this SBS implementation —
    actual schema uses `vocabulary.registry` (dict of word -> entry) and
    `vocabulary.total_unique_words` (int). We assert on those.
    """
    msgs = [synthetic_msg(f"alpha{i} beta{i * 7} gamma{i * 13}") for i in range(_PAST_THRESHOLD)]
    orch = run_batch_pipeline(fresh_sbs, msgs)

    vocab = profile_layer(orch, "vocabulary")
    # We injected ~3 distinct prefix-suffix combos per message x 60 messages.
    # After dedup we expect well over 60 unique tokens.
    assert vocab["total_unique_words"] > 60, (
        f"expected >60 unique words after 60-msg burst, got {vocab['total_unique_words']}"
    )
    assert len(vocab["registry"]) > 0
    # Each registry entry must carry the contract fields used by decay / banglish
    # extraction; if any of these go missing later code crashes silently.
    sample_word, sample_entry = next(iter(vocab["registry"].items()))
    for required_field in ("total_count", "first_seen", "last_seen", "effective_weight"):
        assert required_field in sample_entry, (
            f"vocabulary entry {sample_word!r} missing field {required_field!r}"
        )


def test_core_identity_stable_across_two_rebuilds(fresh_sbs):
    """core_identity is documented IMMUTABLE — must survive two full rebuilds.

    The batch processor must never write to core_identity (ProfileManager guards
    this with PermissionError on save_layer). This test pins that contract: even
    after 110+ messages and two batch runs, core_identity bytes are unchanged.
    """
    msgs = [synthetic_msg("I am a software engineer.") for _ in range(_TWO_REBUILDS)]
    orch = run_batch_pipeline(fresh_sbs, msgs)
    snapshot1 = dict(profile_layer(orch, "core_identity"))

    # Second rebuild on the same orchestrator — feeds 50 more identical messages.
    orch = run_batch_pipeline(orch, [synthetic_msg("I am a software engineer.") for _ in range(50)])
    snapshot2 = dict(profile_layer(orch, "core_identity"))

    assert snapshot1 == snapshot2, (
        "core_identity flapped across rebuilds — IMMUTABLE invariant broken"
    )


# ---------------------------------------------------------------------------
# Layer presence — every layer must exist after a rebuild
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layer",
    [
        "core_identity",
        "linguistic",
        "emotional_state",
        "domain",
        "interaction",
        "vocabulary",
        "exemplars",
        "meta",
    ],
)
def test_every_layer_present_after_rebuild(fresh_sbs, layer):
    """All 8 ProfileManager.LAYERS must exist as dicts after a rebuild.

    Catches regressions where someone removes a layer from the rebuild path
    (e.g. stops calling _update_X or breaks the load_layer contract).
    """
    msgs = [synthetic_msg(f"hello {i}") for i in range(_PAST_THRESHOLD)]
    orch = run_batch_pipeline(fresh_sbs, msgs)

    # Load via ProfileManager — same path the rest of SBS reads from.
    data = orch.profile_mgr.load_layer(layer)
    assert isinstance(data, dict), f"layer {layer!r} not a dict: got {type(data).__name__}"
    # And the static LAYERS list must still match — pin the canonical order.
    assert layer in ProfileManager.LAYERS, f"{layer!r} fell out of ProfileManager.LAYERS"


# ---------------------------------------------------------------------------
# Meta + version bookkeeping — rebuild must increment counters
# ---------------------------------------------------------------------------


def test_meta_records_rebuild_event(fresh_sbs):
    """A successful batch rebuild must update meta.last_batch_run and bump
    meta.batch_run_count. (current_version is a known-buggy field; see
    test_sbs.py::test_full_run_creates_snapshot — we don't assert on it here.)
    """
    msgs = [synthetic_msg(f"checkpoint {i}") for i in range(_PAST_THRESHOLD)]
    pre_meta = profile_layer(fresh_sbs, "meta")
    pre_count = pre_meta.get("batch_run_count", 0)

    orch = run_batch_pipeline(fresh_sbs, msgs)
    post_meta = profile_layer(orch, "meta")

    assert post_meta["batch_run_count"] >= pre_count + 1, (
        "batch_run_count did not increment after force_batch(full_rebuild=True)"
    )
    assert post_meta["last_batch_run"] is not None, "last_batch_run not recorded"


def test_archive_snapshot_created_on_rebuild(fresh_sbs):
    """snapshot_version() runs at the end of every batch — archive must grow."""
    msgs = [synthetic_msg(f"snapshot test {i}") for i in range(_PAST_THRESHOLD)]
    pre_archives = list(fresh_sbs.profile_mgr.archive_dir.iterdir())

    orch = run_batch_pipeline(fresh_sbs, msgs)

    post_archives = list(orch.profile_mgr.archive_dir.iterdir())
    assert len(post_archives) > len(pre_archives), (
        f"archive did not grow: pre={len(pre_archives)} post={len(post_archives)}"
    )


# ---------------------------------------------------------------------------
# Domain map — keyword-based topic detection drift
# ---------------------------------------------------------------------------


def test_domain_map_picks_up_python_keywords(fresh_sbs):
    """The domain map's keyword detector for `python` must fire on python-heavy
    inputs. This is a structural test — if someone removes the `python` bucket
    from `_update_domain_map.domain_keywords`, this test fails loudly.
    """
    msgs = [
        synthetic_msg(f"writing python with fastapi for endpoint {i}") for i in range(_PAST_THRESHOLD)
    ]
    orch = run_batch_pipeline(fresh_sbs, msgs)

    domain = profile_layer(orch, "domain")
    assert "python" in domain["interests"], (
        f"python not detected in domain.interests: keys={list(domain['interests'].keys())}"
    )
    # And python should rank in the top active_domains given input dominance.
    assert "python" in domain["active_domains"], (
        f"python not in active_domains: {domain['active_domains']}"
    )


# ---------------------------------------------------------------------------
# Determinism — same inputs twice on fresh state must yield identical core fields
# ---------------------------------------------------------------------------


def test_rebuild_is_deterministic_for_fixed_inputs(fresh_sbs, tmp_path):
    """Two fresh orchestrators fed identical message sequences must produce
    matching vocabulary registries. Catches regressions where the rebuild leaks
    nondeterminism (e.g. dict iteration order escaping into JSON snapshots, or
    the ExemplarSelector wildcard wandering — that's why we seed random above).
    """
    msgs = [synthetic_msg(f"deterministic input {i}") for i in range(_PAST_THRESHOLD)]
    run_batch_pipeline(fresh_sbs, msgs)
    vocab1 = profile_layer(fresh_sbs, "vocabulary")["registry"]

    # Second orchestrator with its own tmp dir.
    second = SBSOrchestrator(data_dir=str(tmp_path / "second_sbs"))
    second._schedule_batch = lambda: None  # match fresh_sbs fixture behavior
    run_batch_pipeline(second, msgs)
    vocab2 = profile_layer(second, "vocabulary")["registry"]

    # Compare just the keys + total_count — `last_seen` / `effective_weight`
    # carry datetime.now() drift, so comparing by structural keys keeps the
    # test from flaking on millisecond differences.
    assert set(vocab1.keys()) == set(vocab2.keys()), (
        f"deterministic rebuild diverged: only-in-1={set(vocab1) - set(vocab2)}, "
        f"only-in-2={set(vocab2) - set(vocab1)}"
    )
    for word in vocab1:
        assert vocab1[word]["total_count"] == vocab2[word]["total_count"], (
            f"total_count diverged for {word!r}: {vocab1[word]['total_count']} vs "
            f"{vocab2[word]['total_count']}"
        )
