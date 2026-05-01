"""Structured receipts for claims about actions Synapse actually performed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ReceiptStatus = Literal["verified", "failed", "unavailable", "inferred"]


_ACTION_ALIASES: dict[str, tuple[str, ...]] = {
    "web_query": ("search", "check", "lookup", "look_up"),
    "web_search": ("search", "check", "lookup", "look_up", "fetch"),
    "memory_save": ("save", "remember"),
    "message_capture": ("capture",),
    "reminder_schedule": ("schedule", "nudge", "remind"),
    "channel_send": ("send", "deliver"),
}


@dataclass(frozen=True)
class ActionReceipt:
    """Proof object for a tool, memory, schedule, or delivery action."""

    action: str
    status: ReceiptStatus
    evidence: str
    confidence: float = 0.0
    next_best_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def supports(self, claim_kind: str) -> bool:
        if self.status != "verified":
            return False
        action = self.action.lower().strip()
        claim = claim_kind.lower().strip()
        if claim == action:
            return True
        return claim in _ACTION_ALIASES.get(action, ())

    def to_prompt_line(self) -> str:
        parts = [
            f"action={self.action}",
            f"status={self.status}",
            f"confidence={self.confidence:.2f}",
            f"evidence={_one_line(self.evidence, 240)}",
        ]
        if self.next_best_action:
            parts.append(f"next={_one_line(self.next_best_action, 180)}")
        return "- " + "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "next_best_action": self.next_best_action,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "ActionReceipt | None":
        if isinstance(value, ActionReceipt):
            return value
        if not isinstance(value, dict):
            return None
        action = str(value.get("action") or "").strip()
        status = str(value.get("status") or "").strip().lower()
        if not action or status not in {"verified", "failed", "unavailable", "inferred"}:
            return None
        metadata = value.get("metadata")
        return cls(
            action=action,
            status=status,  # type: ignore[arg-type]
            evidence=str(value.get("evidence") or ""),
            confidence=float(value.get("confidence") or 0.0),
            next_best_action=str(value.get("next_best_action") or ""),
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=str(value.get("created_at") or datetime.now(UTC).isoformat()),
        )


def render_receipt_contract(receipts: list[ActionReceipt]) -> str:
    """Render receipts as a compact prompt contract."""

    lines = [
        "ACTION RECEIPTS:",
        "Only claim an action happened when its receipt status supports it.",
        "If a receipt is failed/unavailable, say you tried or could not verify; do not claim success.",
    ]
    if not receipts:
        lines.append("- none; do not claim live search/check/save/schedule/send actions happened.")
    else:
        lines.extend(receipt.to_prompt_line() for receipt in receipts)
    return "\n".join(lines)


def guard_reply_against_unreceipted_claims(
    reply: str, receipts: list[ActionReceipt]
) -> str:
    """Repair final text if it claims an action without a verified receipt."""

    text = str(reply or "")
    if not text.strip():
        return text

    repairs: list[str] = []

    if _has_success_search_claim(text) and not _has_receipt(receipts, "search"):
        text = _neutralize_search_claim(text)
        repairs.append("I haven't verified that live in this turn.")

    if _has_success_save_claim(text) and not _has_receipt(receipts, "save"):
        text = _neutralize_save_claim(text)
        repairs.append("I haven't saved that as memory in this turn.")

    if _has_success_schedule_claim(text) and not _has_receipt(receipts, "schedule"):
        text = _neutralize_schedule_claim(text)
        repairs.append("I haven't scheduled that in this turn.")

    if _has_success_send_claim(text) and not _has_receipt(receipts, "send"):
        text = _neutralize_send_claim(text)
        repairs.append("I haven't sent that anywhere in this turn.")

    if repairs:
        text = _cleanup_text(text)
        text = f"{text.rstrip()}\n\n{_dedupe_sentence_join(repairs)}".strip()
    return text


def _has_receipt(receipts: list[ActionReceipt], claim_kind: str) -> bool:
    return any(receipt.supports(claim_kind) for receipt in receipts)


def _has_success_search_claim(text: str) -> bool:
    lowered = text.lower()
    if "tried to search" in lowered or "couldn't search" in lowered or "could not search" in lowered:
        return False
    return bool(
        _search_regex(
            r"\bi\s+(?:searched|checked|looked\s+up|fetched)\b",
            text,
        )
        or _search_regex(r"\bi\s+(?:verified|confirmed)\s+(?:the\s+)?(?:live|web|online|official|source|results?)\b", text)
        or _search_regex(r"\bi\s+found\s+(?:the\s+)?(?:official|live|web|online|source|results?)\b", text)
        or _search_regex(r"\blive results?\b", text)
    )


def _has_success_save_claim(text: str) -> bool:
    lowered = text.lower()
    if "not saved" in lowered or "haven't saved" in lowered:
        return False
    return bool(_search_regex(r"\bi\s+(?:saved|remembered|stored|captured)\b", text))


def _has_success_schedule_claim(text: str) -> bool:
    lowered = text.lower()
    if "not scheduled" in lowered or "haven't scheduled" in lowered:
        return False
    return bool(
        _search_regex(r"\bi(?:'ll| will)\s+(?:nudge|remind|ping|notify)\s+you\b", text)
        or _search_regex(r"\bi\s+(?:scheduled|set)\b", text)
    )


def _has_success_send_claim(text: str) -> bool:
    lowered = text.lower()
    if "not sent" in lowered or "haven't sent" in lowered:
        return False
    return bool(_search_regex(r"\bi\s+(?:sent|delivered|forwarded)\b", text))


def _neutralize_search_claim(text: str) -> str:
    text = _replace_regex(
        r"\bI\s+(?:searched|checked|looked\s+up|fetched|verified|confirmed)\s+(?:the\s+)?(?:web|live\s+results?|results?|official\s+route)?\s*(?:and\s+)?",
        "",
        text,
    )
    text = _replace_regex(r"\bI\s+found\b", "A possible option is", text)
    text = _replace_regex(r"\blive results?\b", "details", text)
    return text


def _neutralize_save_claim(text: str) -> str:
    return _replace_regex(r"\bI\s+(?:saved|remembered|stored|captured)\b", "I noted", text)


def _neutralize_schedule_claim(text: str) -> str:
    text = _replace_regex(
        r"\bI(?:'ll| will)\s+(?:nudge|remind|ping|notify)\s+you\b",
        "I can nudge you",
        text,
    )
    return _replace_regex(r"\bI\s+(?:scheduled|set)\b", "I can schedule", text)


def _neutralize_send_claim(text: str) -> str:
    return _replace_regex(r"\bI\s+(?:sent|delivered|forwarded)\b", "I can send", text)


def _cleanup_text(text: str) -> str:
    text = _replace_regex(r"\s{2,}", " ", text)
    text = _replace_regex(r"\s+([.,!?])", r"\1", text)
    text = _replace_regex(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dedupe_sentence_join(sentences: list[str]) -> str:
    seen = set()
    out = []
    for sentence in sentences:
        key = sentence.lower()
        if key not in seen:
            seen.add(key)
            out.append(sentence)
    return " ".join(out)


def _one_line(value: str, max_chars: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 15)].rstrip() + " ... [truncated]"


def _search_regex(pattern: str, text: str) -> re.Match[str] | None:
    import re

    return re.search(pattern, text, flags=re.IGNORECASE)


def _replace_regex(pattern: str, repl: str, text: str) -> str:
    import re

    return re.sub(pattern, repl, text, flags=re.IGNORECASE)
