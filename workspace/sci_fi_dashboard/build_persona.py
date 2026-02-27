#!/usr/bin/env python3
"""
Build Persona -- One-time CLI script to parse chat logs and generate persona profiles.

Usage:
    python build_persona.py                          # Build both profiles
    python build_persona.py --primary_user-only            # Build just primary_user profile
    python build_persona.py --partner_user-only            # Build just partner_user profile
    python build_persona.py --chat-dir /path/to/chats  # Custom chat directory
"""

import argparse
import json
import os

from chat_parser import PersonaProfile, build_persona_profile, save_profile

# Default paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONAS_DIR = os.path.join(SCRIPT_DIR, "personas")

# Default chat file locations (on Desktop from transfer)
DEFAULT_CHAT_DIR = os.path.expanduser("~/Desktop")


def find_chat_file(directory: str, filename: str) -> str:
    """Find a chat file, checking multiple locations."""
    candidates = [
        os.path.join(directory, filename),
        os.path.join(os.path.expanduser("~/Desktop"), filename),
        os.path.join(os.path.expanduser("~/Downloads"), filename),
        os.path.join(SCRIPT_DIR, filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def print_profile_summary(profile: PersonaProfile):
    """Print a human-readable summary of a generated profile."""
    print(f"\n{'=' * 60}")
    print(f"  [CLIPBOARD] Profile: {profile.target_user} ({profile.relationship_mode})")
    print(f"{'=' * 60}")
    print(
        f"  [CHART] Messages analyzed: {profile.total_synapse_messages} Synapse, "
        f"{profile.total_user_messages} {profile.target_user}"
    )
    print(f"  [REPLY] Conversation pairs: {profile.total_exchanges}")
    print(f"  [LOG] Avg message length: {profile.avg_message_length} chars")
    print(f"  [SMILE] Emoji density: {profile.emoji_density} per message")
    print(f"  [TARGET] Top emojis: {' '.join(profile.top_emojis[:8])}")
    print(f"  [SPEAK]  Catchphrases: {', '.join(profile.catchphrases[:5])}")
    print(f"  [IN] Banglish words: {len(profile.banglish_words)} found")
    print(f"  [CMD] Tech jargon: {len(profile.tech_jargon)} terms")
    print(f"  [DIR] Topics: {json.dumps(profile.topic_categories, indent=4)}")
    print(f"  [GRAD] Few-shot examples: {len(profile.few_shot_examples)}")
    print(f"  [HISTORY] Rules: {len(profile.rules)}")
    print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="Build Synapse persona profiles from chat logs")
    parser.add_argument(
        "--chat-dir", default=DEFAULT_CHAT_DIR, help="Directory containing chat .md files"
    )
    parser.add_argument(
        "--primary_user-only", action="store_true", help="Build only primary_user profile"
    )
    parser.add_argument(
        "--partner_user-only", action="store_true", help="Build only partner_user profile"
    )
    parser.add_argument("--output-dir", default=PERSONAS_DIR, help="Output directory for profiles")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("[MEM] Synapse Persona Builder v1.0")
    print(f"[DIR] Looking for chat files in: {args.chat_dir}")
    print(f"[DIR] Output directory: {args.output_dir}\n")

    profiles_built = 0

    # Build primary_user profile
    if not args.the_partner_only:
        the_creator_chat = find_chat_file(args.chat_dir, "Chat_with_primary_user_LLM.md")
        if the_creator_chat:
            print(f"[READ] Found primary_user chat: {the_creator_chat}")
            profile = build_persona_profile(
                filepath=the_creator_chat, user_name="primary_user", relationship_mode="brother"
            )
            output = os.path.join(args.output_dir, "the_creator_profile.json")
            save_profile(profile, output)
            print_profile_summary(profile)
            profiles_built += 1
        else:
            print("[ERROR] Could not find Chat_with_primary_user_LLM.md")
            print(f"   Searched: {args.chat_dir}, ~/Desktop, ~/Downloads, {SCRIPT_DIR}")

    # Build partner_user profile
    if not args.the_creator_only:
        the_partner_chat = find_chat_file(args.chat_dir, "Chat_with_partner_user_LLM.md")
        if the_partner_chat:
            print(f"[READ] Found partner_user chat: {the_partner_chat}")
            profile = build_persona_profile(
                filepath=the_partner_chat, user_name="partner_user", relationship_mode="caring_pa"
            )
            output = os.path.join(args.output_dir, "the_partner_profile.json")
            save_profile(profile, output)
            print_profile_summary(profile)
            profiles_built += 1
        else:
            print("[ERROR] Could not find Chat_with_partner_user_LLM.md")
            print(f"   Searched: {args.chat_dir}, ~/Desktop, ~/Downloads, {SCRIPT_DIR}")

    # Summary
    print(f"\n[FLAG] Done! Built {profiles_built} profile(s).")
    if profiles_built > 0:
        print(f"   Files saved to: {args.output_dir}/")

        # Quick validation
        for fname in ["the_creator_profile.json", "the_partner_profile.json"]:
            fpath = os.path.join(args.output_dir, fname)
            if os.path.exists(fpath):
                with open(fpath) as f:
                    data = json.load(f)
                print(
                    f"   [OK] {fname}: {len(data.get('few_shot_examples', []))} examples, "
                    f"{len(data.get('banglish_words', []))} vocab words"
                )


if __name__ == "__main__":
    main()
