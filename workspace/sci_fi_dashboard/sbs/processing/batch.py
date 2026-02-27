import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..processing.selectors.exemplar import ExemplarSelector
from ..profile.manager import ProfileManager


class BatchProcessor:
    """
    Periodic deep analysis engine.

    Trigger conditions (whichever comes first):
    - Every 50 new user messages
    - Every 6 hours
    - Manual trigger

    Responsibilities:
    1. Vocabulary Census -- track all terms, frequencies, emergence dates
    2. Linguistic Style Analysis -- Banglish ratio trends, sentence length trends
    3. Interaction Pattern Analysis -- active hours, response length preferences
    4. Domain Map Update -- what topics are hot right now
    5. Exemplar Re-selection -- pick the best few-shot examples
    6. Temporal Decay Sweep -- demote stale patterns
    """

    def __init__(self, db_path: Path, profile_manager: ProfileManager):
        self.db_path = db_path
        self.profile_mgr = profile_manager
        self.exemplar_selector = ExemplarSelector(db_path)

    def run(self, full_rebuild: bool = False):
        """
        Main batch processing entry point.

        Args:
            full_rebuild: If True, re-analyzes entire history.
                         If False, only processes since last run.
        """
        print(
            f"[BATCH] Starting {'full rebuild' if full_rebuild else 'incremental'} at {datetime.now()}"
        )

        meta = self.profile_mgr.load_layer("meta")
        last_run = meta.get("last_batch_run", "2000-01-01T00:00:00")

        if full_rebuild:
            messages = self._fetch_all_user_messages()
        else:
            messages = self._fetch_messages_since(last_run)

        if not messages:
            print("[BATCH] No new messages to process.")
            return

        print(f"[BATCH] Processing {len(messages)} messages...")

        # === STAGE 1: Vocabulary Census ===
        self._update_vocabulary(messages)

        # === STAGE 2: Linguistic Style ===
        self._update_linguistic_profile(messages)

        # === STAGE 3: Interaction Patterns ===
        self._update_interaction_patterns(messages)

        # === STAGE 4: Domain Map ===
        self._update_domain_map(messages)

        # === STAGE 5: Exemplar Re-selection ===
        # This ALWAYS works on full history for best coverage
        self._reselect_exemplars()

        # === STAGE 6: Decay Sweep ===
        self._run_decay_sweep()

        # === STAGE 7: Version Snapshot ===
        self.profile_mgr.snapshot_version()

        # Update meta
        meta["last_batch_run"] = datetime.now().isoformat()
        meta["total_messages_processed"] = self._get_total_count()
        meta["batch_run_count"] = meta.get("batch_run_count", 0) + 1
        self.profile_mgr.save_layer("meta", meta)

        print(f"[BATCH] Complete. Profile version: {meta['batch_run_count']}")

    def _update_vocabulary(self, messages: list[dict]):
        """
        Build/update vocabulary frequency table with temporal weights.
        """
        vocab = self.profile_mgr.load_layer("vocabulary")
        word_registry = vocab.get("registry", {})

        for msg in messages:
            words = msg["content"].lower().split()
            timestamp = msg["timestamp"]

            for word in words:
                # Skip very short or purely numeric
                if len(word) < 2 or word.isnumeric():
                    continue

                if word not in word_registry:
                    word_registry[word] = {
                        "total_count": 0,
                        "first_seen": timestamp,
                        "last_seen": timestamp,
                        "monthly_counts": {},  # {"2025-01": 5, "2025-02": 12}
                    }

                entry = word_registry[word]
                entry["total_count"] += 1
                entry["last_seen"] = timestamp

                # Check for length to avoid out-of-index
                if len(timestamp) >= 7:
                    month_key = timestamp[:7]  # "2025-01"
                    entry["monthly_counts"][month_key] = (
                        entry["monthly_counts"].get(month_key, 0) + 1
                    )

        # Compute "effective weight" with temporal decay
        now = datetime.now()
        for _word, data in word_registry.items():
            last_seen = datetime.fromisoformat(data["last_seen"])
            days_since = (now - last_seen).days

            # Decay: weight = count * e^(-0.03 * days_since_last_seen)
            decay_factor = math.exp(-0.03 * days_since)
            data["effective_weight"] = round(data["total_count"] * decay_factor, 2)

        # Extract top Banglish terms (for quick prompt access)
        banglish_terms = {}
        from .realtime import COMPILED_BANGLISH

        for word, data in word_registry.items():
            for pattern, normalized in COMPILED_BANGLISH.items():
                if pattern.search(word) and (
                    normalized not in banglish_terms
                    or data["effective_weight"] > banglish_terms[normalized]["weight"]
                ):
                    banglish_terms[normalized] = {
                        "weight": data["effective_weight"],
                        "variants": [word],
                        "last_seen": data["last_seen"],
                    }

        vocab["registry"] = word_registry
        vocab["top_banglish"] = dict(
            sorted(banglish_terms.items(), key=lambda x: x[1]["weight"], reverse=True)[:30]
        )  # Keep top 30
        vocab["total_unique_words"] = len(word_registry)
        vocab["last_updated"] = now.isoformat()

        self.profile_mgr.save_layer("vocabulary", vocab)

    def _update_linguistic_profile(self, messages: list[dict]):
        """
        Track communication style metrics over time.
        """
        linguistic = self.profile_mgr.load_layer("linguistic")

        # Analyze this batch
        banglish_msgs = 0
        english_msgs = 0
        mixed_msgs = 0
        total_words = 0
        total_msgs = len(messages)
        emoji_msgs = 0
        question_msgs = 0
        avg_lengths = []

        for msg in messages:
            lang = msg.get("rt_language", "en")
            if lang == "banglish":
                banglish_msgs += 1
            elif lang == "en":
                english_msgs += 1
            else:
                mixed_msgs += 1

            word_count = msg.get("word_count", len(msg["content"].split()))
            total_words += word_count
            avg_lengths.append(word_count)

            if msg.get("has_emoji"):
                emoji_msgs += 1
            if msg.get("is_question"):
                question_msgs += 1

        # Update rolling averages
        current_batch = {
            "timestamp": datetime.now().isoformat(),
            "banglish_ratio": round(banglish_msgs / max(total_msgs, 1), 3),
            "english_ratio": round(english_msgs / max(total_msgs, 1), 3),
            "mixed_ratio": round(mixed_msgs / max(total_msgs, 1), 3),
            "avg_message_length": round(sum(avg_lengths) / max(len(avg_lengths), 1), 1),
            "emoji_frequency": round(emoji_msgs / max(total_msgs, 1), 3),
            "question_frequency": round(question_msgs / max(total_msgs, 1), 3),
            "sample_size": total_msgs,
        }

        # Keep history of last 20 batch analyses for trend detection
        style_history = linguistic.get("style_history", [])
        style_history.append(current_batch)
        style_history = style_history[-20:]

        # Compute current style (weighted average of recent batches)
        # More recent batches get higher weight
        weights = [1.0 + (i * 0.2) for i in range(len(style_history))]
        total_weight = sum(weights)

        current_style = {
            "banglish_ratio": round(
                sum(h["banglish_ratio"] * w for h, w in zip(style_history, weights, strict=False))
                / total_weight,
                3,
            ),
            "avg_message_length": round(
                sum(
                    h["avg_message_length"] * w
                    for h, w in zip(style_history, weights, strict=False)
                )
                / total_weight,
                1,
            ),
            "emoji_frequency": round(
                sum(h["emoji_frequency"] * w for h, w in zip(style_history, weights, strict=False))
                / total_weight,
                3,
            ),
        }

        # Detect drift (compare current vs first half of history)
        if len(style_history) >= 4:
            old_banglish = sum(
                h["banglish_ratio"] for h in style_history[: len(style_history) // 2]
            ) / (len(style_history) // 2)
            new_banglish = sum(
                h["banglish_ratio"] for h in style_history[len(style_history) // 2 :]
            ) / (len(style_history) - len(style_history) // 2)
            drift = new_banglish - old_banglish
            current_style["banglish_drift"] = round(drift, 3)
            current_style["drift_direction"] = (
                "increasing" if drift > 0.05 else "decreasing" if drift < -0.05 else "stable"
            )

        linguistic["style_history"] = style_history
        linguistic["current_style"] = current_style
        linguistic["last_updated"] = datetime.now().isoformat()

        self.profile_mgr.save_layer("linguistic", linguistic)

    def _update_interaction_patterns(self, messages: list[dict]):
        """Track when the user is active, preferred response lengths, etc."""
        interaction = self.profile_mgr.load_layer("interaction")

        hourly_activity = interaction.get("hourly_activity", {str(i): 0 for i in range(24)})
        daily_activity = interaction.get("daily_activity", {})

        for msg in messages:
            if msg["role"] != "user":
                continue

            ts = datetime.fromisoformat(msg["timestamp"])
            hour = str(ts.hour)
            day = ts.strftime("%A")

            hourly_activity[hour] = hourly_activity.get(hour, 0) + 1
            daily_activity[day] = daily_activity.get(day, 0) + 1

        # Find peak hours
        sorted_hours = sorted(hourly_activity.items(), key=lambda x: x[1], reverse=True)
        peak_hours = [int(h) for h, _ in sorted_hours[:4]]

        # Compute preferred response length from assistant messages
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        if assistant_msgs:
            avg_response_len = sum(m.get("word_count", 50) for m in assistant_msgs) / len(
                assistant_msgs
            )
        else:
            avg_response_len = interaction.get("avg_response_length", 50)

        interaction["hourly_activity"] = hourly_activity
        interaction["daily_activity"] = daily_activity
        interaction["peak_hours"] = peak_hours
        interaction["avg_response_length"] = round(avg_response_len, 0)
        interaction["last_updated"] = datetime.now().isoformat()

        self.profile_mgr.save_layer("interaction", interaction)

    def _update_domain_map(self, messages: list[dict]):
        """Track what topics/domains the user is currently interested in."""
        domain = self.profile_mgr.load_layer("domain")

        # Simple keyword-based topic detection
        domain_keywords = {
            "machine_learning": [
                "model",
                "training",
                "dataset",
                "neural",
                "ml",
                "ai",
                "llm",
                "transformer",
                "bert",
                "gpt",
            ],
            "web_dev": [
                "react",
                "next",
                "api",
                "frontend",
                "backend",
                "css",
                "html",
                "node",
                "express",
            ],
            "devops": ["docker", "deploy", "server", "nginx", "ci/cd", "pipeline", "kubernetes"],
            "python": ["python", "pip", "venv", "django", "flask", "fastapi", "pandas"],
            "personal": [
                "the_partner_nickname",
                "family",
                "health",
                "gym",
                "sleep",
                "food",
                "movie",
            ],
            "career": ["job", "interview", "resume", "company", "salary", "startup"],
            "music": ["song", "gaan", "music", "spotify", "playlist", "guitar"],
        }

        topic_counts = defaultdict(int)
        for msg in messages:
            if msg["role"] != "user":
                continue
            text = msg["content"].lower()
            for topic, keywords in domain_keywords.items():
                for kw in keywords:
                    if kw in text:
                        topic_counts[topic] += 1
                        break

        # Update domain interest with decay
        domain_interests = domain.get("interests", {})
        now = datetime.now()

        for topic, count in topic_counts.items():
            if topic not in domain_interests:
                domain_interests[topic] = {
                    "total_mentions": 0,
                    "recent_mentions": 0,
                    "first_seen": now.isoformat(),
                    "last_seen": now.isoformat(),
                }
            domain_interests[topic]["total_mentions"] += count
            domain_interests[topic]["recent_mentions"] = count
            domain_interests[topic]["last_seen"] = now.isoformat()

        # Rank by recent activity
        active_domains = sorted(
            domain_interests.items(), key=lambda x: x[1]["recent_mentions"], reverse=True
        )

        domain["interests"] = domain_interests
        domain["active_domains"] = [d[0] for d in active_domains[:5]]
        domain["last_updated"] = now.isoformat()

        self.profile_mgr.save_layer("domain", domain)

    def _reselect_exemplars(self):
        """Delegate to ExemplarSelector for principled few-shot selection."""
        exemplars = self.exemplar_selector.select(max_exemplars=14)
        self.profile_mgr.save_layer(
            "exemplars",
            {
                "pairs": exemplars,
                "count": len(exemplars),
                "last_selected": datetime.now().isoformat(),
            },
        )

    def _run_decay_sweep(self):
        """Archive vocabulary entries that have decayed below threshold."""
        vocab = self.profile_mgr.load_layer("vocabulary")
        registry = vocab.get("registry", {})

        decay_threshold = 0.5
        archived = []
        active = {}

        for word, data in registry.items():
            if data.get("effective_weight", 0) < decay_threshold:
                archived.append(word)
            else:
                active[word] = data

        vocab["registry"] = active
        vocab["archived_count"] = vocab.get("archived_count", 0) + len(archived)

        self.profile_mgr.save_layer("vocabulary", vocab)

        if archived:
            print(f"[BATCH] Archived {len(archived)} decayed vocabulary entries.")

    # --- Helper queries ---

    def _fetch_all_user_messages(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in conn.execute("SELECT * FROM messages ORDER BY timestamp ASC").fetchall()
            ]

    def _fetch_messages_since(self, since: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM messages WHERE timestamp > ? ORDER BY timestamp ASC", (since,)
                ).fetchall()
            ]

    def _get_total_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
