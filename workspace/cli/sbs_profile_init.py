"""sbs_profile_init.py — Maps onboarding wizard answers to SBS profile layers.

Called by cli/onboard.py's _run_sbs_questions() after synapse.json is written.
Seeds the sbs_the_creator persona with communication preferences collected during
the setup wizard, so the first interaction is already personalized.

Exports:
  - initialize_sbs_from_wizard() — main entry point
  - STYLE_CHOICES, INTEREST_CHOICES, PRIVACY_CHOICES, ENERGY_CHOICES — canonical value lists
  - STYLE_DISPLAY_MAP, PRIVACY_DISPLAY_MAP, ENERGY_DISPLAY_MAP — display→internal mappings
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical internal value lists
# ---------------------------------------------------------------------------

STYLE_CHOICES = [
    "casual_and_witty",
    "formal_and_precise",
    "technical_depth",
    "creative_and_playful",
]

INTEREST_CHOICES = [
    "technology",
    "music",
    "wellness",
    "finance",
    "science",
    "arts",
    "sports",
    "cooking",
]

PRIVACY_CHOICES = ["open", "selective", "private"]

ENERGY_CHOICES = ["high_energy", "calm_and_steady", "adaptive"]

# ---------------------------------------------------------------------------
# Display → internal value maps (used by wizard to translate prompter output)
# ---------------------------------------------------------------------------

STYLE_DISPLAY_MAP = {
    "Casual and witty": "casual_and_witty",
    "Formal and precise": "formal_and_precise",
    "Technical depth first": "technical_depth",
    "Creative and playful": "creative_and_playful",
}

PRIVACY_DISPLAY_MAP = {
    "Open - store freely": "open",
    "Selective - use judgment": "selective",
    "Private - minimal storage": "private",
}

ENERGY_DISPLAY_MAP = {
    "High-energy and intense": "high_energy",
    "Calm and steady": "calm_and_steady",
    "Varies - I adapt": "adaptive",
}

# Energy level → emotional_state.current_dominant_mood mapping
_ENERGY_TO_MOOD = {
    "high_energy": "energetic",
    "calm_and_steady": "calm",
    "adaptive": "neutral",
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def initialize_sbs_from_wizard(answers: dict, data_root: Path) -> None:  # noqa: ARG001
    """Write wizard answers into SBS profile layers for sbs_the_creator persona.

    Reads each layer, merges wizard-sourced values into it, and saves back.
    Each save_layer call is individually guarded — a failure on one layer does
    not prevent the others from being written.

    Args:
        answers:   Dict of wizard answers with keys:
                     communication_style: str (one of STYLE_CHOICES)
                     energy_level:        str (one of ENERGY_CHOICES)
                     interests:           list[str] (subset of INTEREST_CHOICES)
                     privacy_level:       str (one of PRIVACY_CHOICES)
        data_root: Path to the Synapse data root (e.g. ~/.synapse).
                   Currently unused — profile path is resolved via SynapseConfig
                   so it always matches the live config, not a hardcoded path.

    Note:
        Only sbs_the_creator is seeded. sbs_the_partner retains default layers
        because the wizard collects data about the primary user, not the partner.
        NEVER writes to core_identity — that layer raises PermissionError.
    """
    try:
        from synapse_config import SynapseConfig  # noqa: PLC0415
    except ImportError:
        logger.warning("SynapseConfig not importable — skipping SBS profile init")
        return

    try:
        config = SynapseConfig.load()
    except Exception:  # noqa: BLE001
        logger.warning("Could not load SynapseConfig — skipping SBS profile init")
        return

    profile_path = config.sbs_dir / "sbs_the_creator" / "profiles"

    try:
        from sci_fi_dashboard.sbs.profile.manager import ProfileManager  # noqa: PLC0415
    except ImportError:
        logger.warning("ProfileManager not importable — skipping SBS profile init")
        return

    mgr = ProfileManager(profile_path)

    # ------------------------------------------------------------------
    # 1. linguistic — write preferred_style into current_style sub-dict
    # ------------------------------------------------------------------
    try:
        linguistic = mgr.load_layer("linguistic")
        if "current_style" not in linguistic:
            linguistic["current_style"] = {}
        linguistic["current_style"]["preferred_style"] = answers.get(
            "communication_style", "casual_and_witty"
        )
        mgr.save_layer("linguistic", linguistic)
        logger.debug("SBS linguistic layer seeded: preferred_style=%s", answers.get("communication_style"))
    except Exception:  # noqa: BLE001
        logger.warning("Could not write linguistic layer — skipping", exc_info=True)

    # ------------------------------------------------------------------
    # 2. emotional_state — map energy_level to current_dominant_mood
    # ------------------------------------------------------------------
    try:
        emotional = mgr.load_layer("emotional_state")
        energy = answers.get("energy_level", "calm_and_steady")
        mood = _ENERGY_TO_MOOD.get(energy, "neutral")
        emotional["current_dominant_mood"] = mood
        mgr.save_layer("emotional_state", emotional)
        logger.debug("SBS emotional_state layer seeded: current_dominant_mood=%s", mood)
    except Exception:  # noqa: BLE001
        logger.warning("Could not write emotional_state layer — skipping", exc_info=True)

    # ------------------------------------------------------------------
    # 3. domain — write BOTH interests dict AND active_domains list
    #    _compile_domain() reads active_domains (list), not interests (dict).
    #    Without active_domains, user interest selections have no runtime effect.
    # ------------------------------------------------------------------
    try:
        domain = mgr.load_layer("domain")
        if "interests" not in domain:
            domain["interests"] = {}
        interests = list(answers.get("interests", []))
        for topic in interests:
            domain["interests"][topic] = 1.0
        # active_domains is the list that _compile_domain() actually consumes
        domain["active_domains"] = interests
        mgr.save_layer("domain", domain)
        logger.debug("SBS domain layer seeded: active_domains=%s", interests)
    except Exception:  # noqa: BLE001
        logger.warning("Could not write domain layer — skipping", exc_info=True)

    # ------------------------------------------------------------------
    # 4. interaction — write privacy_sensitivity
    # ------------------------------------------------------------------
    try:
        interaction = mgr.load_layer("interaction")
        interaction["privacy_sensitivity"] = answers.get("privacy_level", "selective")
        mgr.save_layer("interaction", interaction)
        logger.debug(
            "SBS interaction layer seeded: privacy_sensitivity=%s", answers.get("privacy_level")
        )
    except Exception:  # noqa: BLE001
        logger.warning("Could not write interaction layer — skipping", exc_info=True)
