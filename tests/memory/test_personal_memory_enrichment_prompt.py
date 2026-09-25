from __future__ import annotations

import asyncio

from sci_fi_dashboard.user_memory_distiller_v2 import build_router_extractor


class CapturingRouter:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def call(self, _role, messages, **_kwargs) -> str:
        self.messages = messages
        return '{"observations":[],"candidate_facts":[],"confirmed_facts":[],"profile_updates":[],"relationship_updates":[]}'


def test_personal_extractor_requests_only_evidence_backed_relationship_updates() -> None:
    router = CapturingRouter()
    extractor = build_router_extractor(router)
    asyncio.run(
        extractor(
            {
                "text": "Please keep your replies short. I prefer a friendly tone.",
                "person_context_json": '{"person_id":"person:alice"}',
            }
        )
    )
    prompt = "\n".join(message["content"] for message in router.messages)

    assert "relationship_updates" in prompt
    assert all(field in prompt for field in ("tone", "verbosity", "humor", "formality", "address_as"))
    assert "evidence" in prompt
    assert "confidence" in prompt
    assert "style_control" in prompt
    assert "professional_precise" in prompt and "casual_witty" in prompt
    assert "concise" in prompt and "detailed" in prompt
    assert "Preserve the user's natural phrase unchanged" in prompt
    assert "omit style_control" in prompt
    assert "explicit" in prompt and "inferred" in prompt
    assert "Do not rewrite" in prompt or "do not rewrite" in prompt
