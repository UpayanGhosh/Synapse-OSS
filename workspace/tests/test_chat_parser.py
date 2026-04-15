"""
test_chat_parser.py — Tests for the chat parser module.

Covers:
  - Message parsing from markdown format
  - Noise detection
  - Turn grouping
  - Conversation pair extraction
  - Synapse message extraction
  - Style analysis
  - Topic detection
  - Best example selection
  - PersonaProfile building
  - Profile saving/loading
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sci_fi_dashboard.chat_parser import (
    EMOJI_RE,
    TIMESTAMP_PATTERN,
    ConversationPair,
    Message,
    PersonaProfile,
    Turn,
    analyze_style,
    build_persona_profile,
    detect_topic,
    extract_conversation_pairs,
    extract_synapse_messages,
    group_into_turns,
    is_noise,
    parse_messages,
    save_profile,
    select_best_examples,
)

# --- Fixtures ---


@pytest.fixture
def sample_chat_file(tmp_path):
    """Create a temporary chat file with realistic content."""
    content = """# Chat Transcript
Format: [YYYY-MM-DD HH:MM] Name:

[2024-10-25 14:00] primary_user:
Hey Synapse, how's it going?

[2024-10-25 14:01] Synapse:
Hey bro! All good here. Working on some python stuff today. How about you?

[2024-10-25 14:02] primary_user:
Can you help me fix the fastapi server?

[2024-10-25 14:03] Synapse:
Of course! Let me take a look at the code. What error are you seeing? Is it a 500 or a timeout? I can debug it for you quickly.

[2024-10-25 14:10] primary_user:
It's a 500 error on the /chat endpoint

[2024-10-25 14:11] Synapse:
Achha, let me check the logs and fix it for you right away.
"""
    chat_file = tmp_path / "test_chat.md"
    chat_file.write_text(content, encoding="utf-8")
    return str(chat_file)


@pytest.fixture
def sample_messages():
    """Pre-built list of Message objects."""
    return [
        Message(timestamp="2024-10-25 14:00", speaker="primary_user", text="Hey Synapse"),
        Message(timestamp="2024-10-25 14:01", speaker="Synapse", text="Hey bro! All good."),
        Message(timestamp="2024-10-25 14:02", speaker="primary_user", text="Help with code?"),
        Message(
            timestamp="2024-10-25 14:03",
            speaker="Synapse",
            text="Of course! Let me look at the fastapi code for you.",
        ),
    ]


@pytest.fixture
def sample_turns():
    """Pre-built turns."""
    return [
        Turn(
            speaker="primary_user",
            messages=["Hey Synapse, how are you?"],
            timestamp="2024-10-25 14:00",
        ),
        Turn(
            speaker="Synapse",
            messages=["Hey bro! All good here. Working on python stuff."],
            timestamp="2024-10-25 14:01",
        ),
        Turn(
            speaker="primary_user",
            messages=["Can you help me fix the fastapi server?"],
            timestamp="2024-10-25 14:02",
        ),
        Turn(
            speaker="Synapse",
            messages=["Of course! Let me take a look at the code."],
            timestamp="2024-10-25 14:03",
        ),
    ]


# --- Tests: Data Classes ---


class TestDataClasses:
    """Tests for Message, Turn, ConversationPair, PersonaProfile dataclasses."""

    def test_message_fields(self):
        """Message should store timestamp, speaker, text."""
        msg = Message(timestamp="2024-01-01 12:00", speaker="User", text="Hello")
        assert msg.timestamp == "2024-01-01 12:00"
        assert msg.speaker == "User"
        assert msg.text == "Hello"

    def test_turn_full_text(self):
        """Turn.full_text should join all messages with newlines."""
        turn = Turn(speaker="Synapse", messages=["Line 1", "Line 2"])
        assert turn.full_text == "Line 1\nLine 2"

    def test_turn_empty_messages(self):
        """Turn with empty messages should produce empty full_text."""
        turn = Turn(speaker="User", messages=[])
        assert turn.full_text == ""

    def test_conversation_pair(self):
        """ConversationPair should store user and synapse turns."""
        pair = ConversationPair(user_turn="Hello", synapse_turn="Hi there!")
        assert pair.user_turn == "Hello"
        assert pair.synapse_turn == "Hi there!"

    def test_persona_profile_defaults(self):
        """PersonaProfile should have sensible defaults."""
        profile = PersonaProfile()
        assert profile.target_user == ""
        assert profile.relationship_mode == ""
        assert profile.avg_message_length == 0.0
        assert profile.emoji_density == 0.0
        assert profile.few_shot_examples == []
        assert profile.rules == []
        assert profile.total_synapse_messages == 0


# --- Tests: Regex Patterns ---


class TestRegexPatterns:
    """Tests for compiled regex patterns."""

    def test_timestamp_pattern_matches(self):
        """TIMESTAMP_PATTERN should match [YYYY-MM-DD HH:MM] Name:"""
        match = TIMESTAMP_PATTERN.match("[2024-10-25 14:00] Synapse:")
        assert match is not None
        assert match.group(1) == "2024-10-25 14:00"
        assert match.group(2) == "Synapse"

    def test_timestamp_pattern_no_match(self):
        """TIMESTAMP_PATTERN should not match plain text."""
        assert TIMESTAMP_PATTERN.match("Just some text") is None

    def test_emoji_regex(self):
        """EMOJI_RE should extract emoji characters."""
        found = EMOJI_RE.findall("Hello \U0001f600 World \U0001f525")
        assert len(found) >= 1


# --- Tests: parse_messages ---


class TestParseMessages:
    """Tests for the parse_messages function."""

    def test_parse_basic_file(self, sample_chat_file):
        """Should parse a valid chat file into Message objects."""
        messages = parse_messages(sample_chat_file)
        assert len(messages) > 0
        assert all(isinstance(m, Message) for m in messages)

    def test_parse_speakers(self, sample_chat_file):
        """Should correctly identify speakers."""
        messages = parse_messages(sample_chat_file)
        speakers = {m.speaker for m in messages}
        assert "primary_user" in speakers
        assert "Synapse" in speakers

    def test_parse_timestamps(self, sample_chat_file):
        """Should extract timestamps."""
        messages = parse_messages(sample_chat_file)
        for m in messages:
            assert m.timestamp  # non-empty

    def test_parse_empty_file(self, tmp_path):
        """Parsing an empty file should return empty list."""
        empty = tmp_path / "empty.md"
        empty.write_text("", encoding="utf-8")
        messages = parse_messages(str(empty))
        assert messages == []

    def test_parse_header_only_file(self, tmp_path):
        """File with only headers should return empty."""
        header = tmp_path / "header.md"
        header.write_text("# Chat Transcript\nFormat: [YYYY-MM-DD HH:MM] Name:\n", encoding="utf-8")
        messages = parse_messages(str(header))
        assert messages == []

    def test_parse_multiline_message(self, tmp_path):
        """Multi-line messages should be joined."""
        content = """[2024-01-01 12:00] User:
Line one
Line two
Line three
"""
        f = tmp_path / "multi.md"
        f.write_text(content, encoding="utf-8")
        messages = parse_messages(str(f))
        assert len(messages) == 1
        assert "Line one" in messages[0].text
        assert "Line two" in messages[0].text
        assert "Line three" in messages[0].text


# --- Tests: is_noise ---


class TestIsNoise:
    """Tests for the is_noise function."""

    def test_system_message_is_noise(self):
        """[SYSTEM] messages should be noise."""
        assert is_noise("[SYSTEM] Connection established")

    def test_media_omitted_is_noise(self):
        """Media omitted messages should be noise."""
        assert is_noise("<Media omitted>")

    def test_normal_text_is_not_noise(self):
        """Normal text should not be noise."""
        assert not is_noise("Hey, how are you doing?")

    def test_empty_string_is_not_noise(self):
        """Empty string should not be noise."""
        assert not is_noise("")

    def test_deleted_message_is_noise(self):
        """Deleted messages should be noise."""
        assert is_noise("You deleted this message")


# --- Tests: group_into_turns ---


class TestGroupIntoTurns:
    """Tests for the group_into_turns function."""

    def test_groups_consecutive_messages(self, sample_messages):
        """Consecutive messages from the same speaker should be grouped."""
        turns = group_into_turns(sample_messages)
        assert len(turns) == 4  # alternating speakers

    def test_empty_messages(self):
        """Empty input should return empty list."""
        assert group_into_turns([]) == []

    def test_single_speaker(self):
        """All messages from one speaker should be one turn."""
        msgs = [
            Message("2024-01-01 12:00", "User", "Hi"),
            Message("2024-01-01 12:01", "User", "How are you?"),
            Message("2024-01-01 12:02", "User", "Anyone there?"),
        ]
        turns = group_into_turns(msgs)
        assert len(turns) == 1
        assert turns[0].speaker == "User"
        assert len(turns[0].messages) == 3

    def test_noise_messages_filtered(self):
        """Noise messages should be filtered out."""
        msgs = [
            Message("2024-01-01 12:00", "User", "Hello"),
            Message("2024-01-01 12:01", "Synapse", "[SYSTEM] reset"),
            Message("2024-01-01 12:02", "Synapse", "Hi there!"),
        ]
        turns = group_into_turns(msgs)
        # The noise message should be skipped
        synapse_turns = [t for t in turns if t.speaker == "Synapse"]
        assert len(synapse_turns) == 1


# --- Tests: extract_conversation_pairs ---


class TestExtractConversationPairs:
    """Tests for extract_conversation_pairs function."""

    def test_basic_pair_extraction(self, sample_turns):
        """Should extract user->Synapse pairs."""
        pairs = extract_conversation_pairs(sample_turns, "primary_user")
        assert len(pairs) > 0
        for pair in pairs:
            assert isinstance(pair, ConversationPair)

    def test_empty_turns(self):
        """Empty turns should produce empty pairs."""
        assert extract_conversation_pairs([], "User") == []

    def test_short_exchanges_filtered(self):
        """Very short exchanges should be filtered."""
        turns = [
            Turn(speaker="User", messages=["Hi"]),  # < 5 chars
            Turn(speaker="Synapse", messages=["This is a longer response for sure."]),
        ]
        pairs = extract_conversation_pairs(turns, "User")
        assert len(pairs) == 0  # User turn too short

    def test_long_synapse_filtered(self):
        """Very long Synapse responses should be filtered."""
        turns = [
            Turn(speaker="User", messages=["Tell me everything"]),
            Turn(speaker="Synapse", messages=["x" * 2001]),  # > 2000 chars
        ]
        pairs = extract_conversation_pairs(turns, "User")
        assert len(pairs) == 0


# --- Tests: extract_synapse_messages ---


class TestExtractSynapseMessages:
    """Tests for extract_synapse_messages."""

    def test_extracts_synapse_only(self, sample_turns):
        """Should only return Synapse messages."""
        msgs = extract_synapse_messages(sample_turns)
        assert len(msgs) > 0
        # All should be strings (from Synapse turns)
        for m in msgs:
            assert isinstance(m, str)

    def test_filters_short_messages(self):
        """Messages <= 10 chars should be filtered."""
        turns = [
            Turn(speaker="Synapse", messages=["Ok"]),  # too short
            Turn(speaker="Synapse", messages=["This is long enough to pass the filter."]),
        ]
        msgs = extract_synapse_messages(turns)
        assert len(msgs) == 1

    def test_empty_turns(self):
        """No turns should produce empty list."""
        assert extract_synapse_messages([]) == []


# --- Tests: analyze_style ---


class TestAnalyzeStyle:
    """Tests for the analyze_style function."""

    def test_empty_messages(self):
        """Empty messages should return empty dict."""
        assert analyze_style([]) == {}

    def test_basic_style_keys(self):
        """Style dict should contain expected keys."""
        msgs = [
            "Hey bro! How's it going? Let me check that python code for you.",
            "Achha, got it. The fastapi server needs a fix. I'll deploy it now.",
        ]
        style = analyze_style(msgs)
        expected_keys = [
            "avg_message_length",
            "emoji_density",
            "top_emojis",
            "top_words",
            "banglish_words",
            "tech_jargon",
            "greeting_patterns",
            "closing_patterns",
            "catchphrases",
        ]
        for key in expected_keys:
            assert key in style, f"Missing key: {key}"

    def test_avg_message_length(self):
        """avg_message_length should be a reasonable number."""
        msgs = ["Hello world", "Goodbye world"]
        style = analyze_style(msgs)
        assert style["avg_message_length"] == round(len("Hello world") / 1, 1)  # average

    def test_emoji_density(self):
        """emoji_density should be 0 when no emojis."""
        msgs = ["No emojis here", "None here either"]
        style = analyze_style(msgs)
        assert style["emoji_density"] == 0

    def test_banglish_detection(self):
        """Known Banglish words should be detected."""
        msgs = ["Achha bro, korbo toh ektu wait"]
        style = analyze_style(msgs)
        # 'achha', 'toh', 'ektu' are in BANGLISH_MARKERS
        found = style["banglish_words"]
        assert any(w in found for w in ["achha", "toh", "ektu"])

    def test_tech_jargon_detection(self):
        """Known tech jargon should be detected."""
        msgs = ["Deploy the fastapi server with docker and sqlite"]
        style = analyze_style(msgs)
        jargon = style["tech_jargon"]
        assert "fastapi" in jargon
        assert "docker" in jargon
        assert "sqlite" in jargon

    def test_greeting_detection(self):
        """Greeting patterns should be detected."""
        msgs = ["Hey bro, what's up?", "Good morning everyone!"]
        style = analyze_style(msgs)
        assert len(style["greeting_patterns"]) > 0


# --- Tests: detect_topic ---


class TestDetectTopic:
    """Tests for the detect_topic function."""

    def test_career_topic(self):
        """Career-related keywords should classify as career."""
        assert detect_topic("I have a job interview tomorrow") == "career"
        assert detect_topic("What about my salary?") == "career"

    def test_relationship_topic(self):
        """Relationship keywords should classify as relationship."""
        assert detect_topic("How is the_partner doing?") == "relationship"

    def test_gaming_topic(self):
        """Gaming keywords should classify as gaming."""
        assert detect_topic("Let's play elden ring tonight") == "gaming"
        assert detect_topic("My Sims build is amazing") == "gaming"

    def test_tech_topic(self):
        """Tech keywords should classify as tech."""
        assert detect_topic("Fix the python fastapi server") == "tech"
        assert detect_topic("Deploy the API endpoint") == "tech"

    def test_daily_life_topic(self):
        """Daily life keywords should classify as daily_life."""
        assert detect_topic("I'm so tired, need sleep") == "daily_life"

    def test_tasks_topic(self):
        """Task keywords should classify as tasks."""
        assert detect_topic("Check my email in gmail") == "tasks"

    def test_emotional_support_topic(self):
        """Emotional keywords should classify as emotional_support."""
        assert detect_topic("I feel so sad and depressed") == "emotional_support"

    def test_general_topic(self):
        """Unmatched text should classify as general."""
        assert detect_topic("The weather is nice today") == "general"

    def test_empty_string(self):
        """Empty string should classify as general."""
        assert detect_topic("") == "general"


# --- Tests: select_best_examples ---


class TestSelectBestExamples:
    """Tests for the select_best_examples function."""

    def test_returns_at_most_n(self):
        """Should return at most n examples."""
        pairs = [
            ConversationPair(
                user_turn=f"Question about topic {i}? " * 5,
                synapse_turn=f"Answer about topic {i}. " * 20,
            )
            for i in range(20)
        ]
        examples = select_best_examples(pairs, n=5)
        assert len(examples) <= 5

    def test_empty_pairs(self):
        """Empty pairs should return empty examples."""
        assert select_best_examples([], n=5) == []

    def test_each_example_has_keys(self):
        """Each example should have user, synapse, topic keys."""
        pairs = [
            ConversationPair(
                user_turn="Can you help with python?",
                synapse_turn="Of course! Let me check the code for you right now.",
            )
        ]
        examples = select_best_examples(pairs, n=5)
        if examples:
            for ex in examples:
                assert "user" in ex
                assert "synapse" in ex
                assert "topic" in ex

    def test_topic_diversity_cap(self):
        """No more than 3 examples per topic."""
        # All same topic (tech)
        pairs = [
            ConversationPair(
                user_turn=f"Fix the python code #{i}",
                synapse_turn=f"Sure, deploying the api server fix now. This is attempt {i}.",
            )
            for i in range(20)
        ]
        examples = select_best_examples(pairs, n=12)
        topics = [e["topic"] for e in examples]
        from collections import Counter

        counts = Counter(topics)
        for topic, count in counts.items():
            assert count <= 3, f"Topic '{topic}' has {count} examples, max is 3"


# --- Tests: save_profile ---


class TestSaveProfile:
    """Tests for the save_profile function."""

    def test_saves_json(self, tmp_path):
        """save_profile should write valid JSON."""
        profile = PersonaProfile(
            target_user="test_user",
            relationship_mode="brother",
            total_synapse_messages=10,
        )
        output = str(tmp_path / "profiles" / "test_profile.json")
        save_profile(profile, output)

        assert os.path.exists(output)
        with open(output) as f:
            data = json.load(f)
        assert data["target_user"] == "test_user"
        assert data["relationship_mode"] == "brother"
        assert data["total_synapse_messages"] == 10

    def test_creates_directory(self, tmp_path):
        """save_profile should create parent directories."""
        profile = PersonaProfile()
        output = str(tmp_path / "deep" / "nested" / "dir" / "profile.json")
        save_profile(profile, output)
        assert os.path.exists(output)


# --- Tests: build_persona_profile ---


class TestBuildPersonaProfile:
    """Tests for the build_persona_profile function."""

    def test_basic_build(self, sample_chat_file):
        """Should build a profile from a chat file."""
        profile = build_persona_profile(sample_chat_file, "primary_user", "brother")
        assert isinstance(profile, PersonaProfile)
        assert profile.target_user == "primary_user"
        assert profile.relationship_mode == "brother"
        assert profile.total_synapse_messages >= 0

    def test_brother_mode_rules(self, sample_chat_file):
        """Brother mode should have brother-specific rules."""
        profile = build_persona_profile(sample_chat_file, "primary_user", "brother")
        rules_text = " ".join(profile.rules)
        assert "brother" in rules_text.lower() or "primary_user_nickname" in rules_text.lower()

    def test_caring_pa_mode_rules(self, sample_chat_file):
        """Caring PA mode should have partner-specific rules."""
        profile = build_persona_profile(sample_chat_file, "partner_user", "caring_pa")
        rules_text = " ".join(profile.rules)
        assert "princess" in rules_text.lower() or "primary_partner" in rules_text.lower()

    def test_profile_has_relationship_context(self, sample_chat_file):
        """Profile should have relationship_context dict."""
        profile = build_persona_profile(sample_chat_file, "primary_user", "brother")
        assert isinstance(profile.relationship_context, dict)
        assert "relationship" in profile.relationship_context

    def test_profile_identity_source(self, sample_chat_file):
        """identity_source should be the filename."""
        profile = build_persona_profile(sample_chat_file, "primary_user")
        assert "test_chat.md" in profile.identity_source
