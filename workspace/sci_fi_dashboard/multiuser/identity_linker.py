"""identity_linker.py — Pure peer-ID resolution via identity links.

No Synapse imports.  Single pure function used by session_key.build_session_key().
"""

from __future__ import annotations


def resolve_linked_peer_id(
    peer_id: str,
    channel: str,
    identity_links: dict,
    dm_scope: str,
) -> str | None:
    """Return the canonical identity that *peer_id* maps to, or ``None``.

    Args:
        peer_id:        Raw peer identifier (e.g. phone number, Telegram user ID).
        channel:        Channel name (e.g. ``"whatsapp"``, ``"telegram"``).
        identity_links: ``dict[canonical, str | list[str]]`` from ``synapse.json``
                        ``session.identityLinks``.  Values may be a bare ``str``
                        (legacy single-ID format) or ``list[str]``.
        dm_scope:       Active DM scope string.  Returns ``None`` immediately when
                        ``"main"`` — no substitution is performed in main scope.

    Returns:
        Canonical name string on match, ``None`` if no match or not applicable.
    """
    if not identity_links or dm_scope == "main":
        return None

    peer_lower = peer_id.lower()
    candidates = {peer_lower, f"{channel}:{peer_lower}"}

    for canonical, ids in identity_links.items():
        # Support both legacy bare-string and list-of-strings value formats.
        if isinstance(ids, str):
            ids = [ids]
        for link_id in ids:
            if isinstance(link_id, str) and link_id.lower() in candidates:
                return canonical

    return None
