"""
fix_unicode.py - Replace all non-ASCII characters in workspace/*.py files with ASCII equivalents.

Purpose: Eliminate UnicodeEncodeError crashes that occur on Windows (cp1252 encoding)
when module-level print/log statements containing emoji are executed at import time.

Usage:
    py -3 fix_unicode.py          # Windows
    python3 fix_unicode.py        # Mac/Linux
"""

import os

REPLACEMENTS = {
    # Status emoji
    "\u2705": "[OK]",       # checkmark button
    "\u274c": "[ERROR]",    # cross mark
    "\u26a0\ufe0f": "[WARN]",  # warning sign + variation selector (two chars)
    "\u26a0": "[WARN]",     # warning sign (without variation selector)
    "\U0001f680": "[INFO]", # rocket
    # Action/state emoji
    "\U0001f4dd": "[LOG]",      # memo
    "\U0001f4c2": "[DIR]",      # open file folder
    "\U0001f50d": "[SEARCH]",   # magnifying glass
    "\u23f3": "[WAIT]",         # hourglass not done
    "\u23f8\ufe0f": "[PAUSED]", # pause button + variation selector
    "\u23f8": "[PAUSED]",       # pause button (without variation selector)
    "\u25b6\ufe0f": "[RESUME]", # play button + variation selector
    "\u25b6": "[RESUME]",       # play button (without variation selector)
    "\u2139\ufe0f": "[INFO]",   # information source + variation selector
    "\u2139": "[INFO]",         # information source (without variation selector)
    "\u23f1\ufe0f": "[TIME]",   # stopwatch + variation selector
    "\u23f1": "[TIME]",         # stopwatch (without variation selector)
    "\U0001f6d1": "[STOP]",     # stop sign
    "\U0001f44b": "[BYE]",      # waving hand
    "\U0001f441\ufe0f": "[WATCH]",  # eye + variation selector
    "\U0001f441": "[WATCH]",    # eye (without variation selector)
    "\U0001f6e1\ufe0f": "[GUARD]",  # shield + variation selector
    "\U0001f6e1": "[GUARD]",    # shield (without variation selector)
    "\U0001f33f": "[BRANCH]",   # herb
    "\U0001f6a8": "[ALERT]",    # police car light
    "\U0001f4ca": "[STATS]",    # bar chart
    "\U0001f4dc": "[HISTORY]",  # scroll
    "\U0001f9ec": "[PROC]",     # dna
    "\U0001f575\ufe0f": "[CHECK]",  # detective + variation selector
    "\U0001f575": "[CHECK]",    # detective (without variation selector)
    "\U0001f9f9": "[CLEAN]",    # broom
    "\U0001f517": "[LINK]",     # link
    "\U0001f310": "[WEB]",      # globe with meridians
    "\U0001f4e1": "[FETCH]",    # satellite antenna
    "\U0001f4ac": "[REPLY]",    # speech balloon
    "\U0001f9e0": "[MEM]",      # brain
    "\U0001f4e5": "[ADD]",      # inbox tray
    "\U0001f4d6": "[READ]",     # open book
    "\u2709\ufe0f": "[MSG]",    # envelope + variation selector
    "\u2709": "[MSG]",          # envelope (without variation selector)
    "\U0001f4e7": "[EMAIL]",    # e-mail
    "\U0001f4c5": "[CAL]",      # calendar
    "\U0001f465": "[CONTACTS]", # busts in silhouette
    "\U0001f4bb": "[CMD]",      # laptop
    "\u2699\ufe0f": "[EVAL]",   # gear + variation selector
    "\u2699": "[EVAL]",         # gear (without variation selector)
    "\U0001f5bc\ufe0f": "[IMG]",  # frame with picture + variation selector
    "\U0001f5bc": "[IMG]",      # frame with picture (without variation selector)
    "\U0001f916": "[BOT]",      # robot face
    "\U0001f464": "[USER]",     # bust in silhouette
    "\U0001f30d": "[WEB]",      # earth globe europe-africa
    "\U0001f4c8": "[CHART]",    # chart increasing
    "\U0001f512": "[LOCK]",     # locked
    "\U0001f513": "[UNLOCK]",   # unlocked
    "\U0001f331": "[NEW]",      # seedling
    # Box-drawing characters
    "\u2550": "=",    # double horizontal
    "\u2500": "-",    # single horizontal
    "\u2014": "--",   # em-dash
    # Arrow (found in test_e2e.py docstring)
    "\u2192": "->",   # right arrow
    # Checkmark without variation selector (U+2713)
    "\u2713": "[OK]", # check mark
    # Unicode bullet / middle dot variants sometimes present
    "\u2022": "*",    # bullet
    "\u00b7": ".",    # middle dot
}


def fix_file(path: str) -> int:
    """Apply all REPLACEMENTS to file. Returns number of replacements made."""
    try:
        content = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError) as e:
        print(f"[SKIP] {path} — could not read: {e}")
        return 0

    original = content
    for emoji, replacement in REPLACEMENTS.items():
        content = content.replace(emoji, replacement)

    if content != original:
        try:
            open(path, "w", encoding="utf-8").write(content)
        except OSError as e:
            print(f"[FAIL] {path} — could not write: {e}")
            return 0
        count = sum(original.count(e) for e in REPLACEMENTS)
        return count
    return 0


def main() -> None:
    project_root = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.join(project_root, "workspace")

    total_files = 0
    total_replacements = 0

    for dirpath, _dirnames, filenames in os.walk(workspace_dir):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, project_root)
            n = fix_file(filepath)
            if n > 0:
                print(f"[FIXED] {rel_path} ({n} replacements)")
                total_files += 1
                total_replacements += n

    print(f"\nDone. {total_files} files modified, {total_replacements} total replacements.")


if __name__ == "__main__":
    main()
