"""
fix_unicode.py - Replace all non-ASCII characters in workspace/*.py files with ASCII equivalents.

Purpose: Eliminate UnicodeEncodeError crashes that occur on Windows (cp1252 encoding)
when module-level print/log statements containing emoji are executed at import time.

Usage:
    py -3 fix_unicode.py          # Windows
    python3 fix_unicode.py        # Mac/Linux
"""

import os
import re

REPLACEMENTS = {
    # -----------------------------------------------------------------------
    # Multi-char sequences FIRST (variation-selector combos must be matched
    # before their base characters; longer keys win because we iterate in
    # insertion order — Python 3.7+ dict preserves insertion order).
    # -----------------------------------------------------------------------

    # Status emoji (with variation selector)
    "\u26a0\ufe0f": "[WARN]",       # warning sign + VS-16
    "\u23f8\ufe0f": "[PAUSED]",     # pause button + VS-16
    "\u25b6\ufe0f": "[RESUME]",     # play button + VS-16
    "\u2139\ufe0f": "[INFO]",       # information source + VS-16
    "\u23f1\ufe0f": "[TIME]",       # stopwatch + VS-16
    "\U0001f441\ufe0f": "[WATCH]",  # eye + VS-16
    "\U0001f6e1\ufe0f": "[GUARD]",  # shield + VS-16
    "\U0001f575\ufe0f": "[CHECK]",  # detective + VS-16
    "\u2699\ufe0f": "[EVAL]",       # gear + VS-16
    "\U0001f5bc\ufe0f": "[IMG]",    # frame with picture + VS-16
    "\u2709\ufe0f": "[MSG]",        # envelope + VS-16
    "\U0001f5a5\ufe0f": "[PC]",     # desktop computer + VS-16
    "\U0001f5d1\ufe0f": "[DEL]",    # wastebasket + VS-16
    "\U0001f5e3\ufe0f": "[SPEAK]",  # speaking head + VS-16
    "\u2702\ufe0f": "[CUT]",        # scissors + VS-16
    "\u2764\ufe0f": "[HEART]",      # heart + VS-16
    "\u2696\ufe0f": "[BALANCE]",    # scales + VS-16
    "\u269b\ufe0f": "[ATOM]",       # atom symbol + VS-16
    "\u26a1\ufe0f": "[FLASH]",      # high voltage + VS-16
    "\U0001f6e0\ufe0f": "[TOOLS]",  # hammer and wrench + VS-16
    "\U0001f399\ufe0f": "[MIC]",    # studio microphone + VS-16
    # Flag sequences (regional indicator pairs)
    "\U0001f1ee\U0001f1f3": "[IN]", # India flag

    # -----------------------------------------------------------------------
    # Single-character emoji (base, without variation selector)
    # -----------------------------------------------------------------------
    # Status
    "\u2705": "[OK]",           # checkmark button
    "\u274c": "[ERROR]",        # cross mark
    "\u26a0": "[WARN]",         # warning sign
    "\U0001f680": "[INFO]",     # rocket
    # Action/state
    "\U0001f4dd": "[LOG]",      # memo
    "\U0001f4c2": "[DIR]",      # open file folder
    "\U0001f50d": "[SEARCH]",   # magnifying glass (left-pointing)
    "\U0001f50e": "[SEARCH]",   # magnifying glass (right-pointing)
    "\u23f3": "[WAIT]",         # hourglass not done
    "\u23f8": "[PAUSED]",       # pause button
    "\u25b6": "[RESUME]",       # play button
    "\u2139": "[INFO]",         # information source
    "\u23f1": "[TIME]",         # stopwatch
    "\U0001f6d1": "[STOP]",     # stop sign
    "\U0001f44b": "[BYE]",      # waving hand
    "\U0001f441": "[WATCH]",    # eye
    "\U0001f6e1": "[GUARD]",    # shield
    "\U0001f33f": "[BRANCH]",   # herb
    "\U0001f6a8": "[ALERT]",    # police car light
    "\U0001f4ca": "[STATS]",    # bar chart
    "\U0001f4dc": "[HISTORY]",  # scroll
    "\U0001f9ec": "[PROC]",     # dna
    "\U0001f575": "[CHECK]",    # detective
    "\U0001f9f9": "[CLEAN]",    # broom
    "\U0001f517": "[LINK]",     # link
    "\U0001f310": "[WEB]",      # globe with meridians
    "\U0001f4e1": "[FETCH]",    # satellite antenna
    "\U0001f4ac": "[REPLY]",    # speech balloon
    "\U0001f9e0": "[MEM]",      # brain
    "\U0001f4e5": "[ADD]",      # inbox tray
    "\U0001f4d6": "[READ]",     # open book
    "\u2709": "[MSG]",          # envelope
    "\U0001f4e7": "[EMAIL]",    # e-mail
    "\U0001f4c5": "[CAL]",      # calendar
    "\U0001f465": "[CONTACTS]", # busts in silhouette
    "\U0001f4bb": "[CMD]",      # laptop
    "\u2699": "[EVAL]",         # gear
    "\U0001f5bc": "[IMG]",      # frame with picture
    "\U0001f916": "[BOT]",      # robot face
    "\U0001f464": "[USER]",     # bust in silhouette
    "\U0001f30d": "[WEB]",      # earth globe europe-africa
    "\U0001f4c8": "[CHART]",    # chart increasing
    "\U0001f512": "[LOCK]",     # locked
    "\U0001f513": "[UNLOCK]",   # unlocked
    "\U0001f331": "[NEW]",      # seedling
    # Additional emoji found in codebase (not in original plan map)
    "\U0001f311": "[MOON]",     # new moon symbol
    "\U0001f319": "[MOON]",     # crescent moon
    "\U0001f324": "[CLOUD]",    # white sun with small cloud
    "\U0001f336": "[HOT]",      # hot pepper
    "\U0001f339": "[ROSE]",     # rose
    "\U0001f393": "[GRAD]",     # graduation cap
    "\U0001f399": "[MIC]",      # studio microphone
    "\U0001f3ac": "[VIDEO]",    # clapper board
    "\U0001f3ad": "[PERF]",     # performing arts
    "\U0001f3af": "[TARGET]",   # direct hit
    "\U0001f3c1": "[FLAG]",     # chequered flag
    "\U0001f3db": "[BLDG]",     # classical building
    "\U0001f419": "[OCTOPUS]",  # octopus
    "\U0001f423": "[CHICK]",    # hatching chick
    "\U0001f440": "[EYES]",     # eyes
    "\U0001f44a": "[FIST]",     # fisted hand sign
    "\U0001f477": "[WORKER]",   # construction worker
    "\U0001f4aa": "[STRONG]",   # flexed biceps
    "\U0001f4ad": "[THOUGHT]",  # thought balloon
    "\U0001f4be": "[SAVE]",     # floppy disk
    "\U0001f4c4": "[PAGE]",     # page facing up
    "\U0001f4cb": "[CLIPBOARD]",# clipboard
    "\U0001f4e4": "[OUTBOX]",   # outbox tray
    "\U0001f4e6": "[PKG]",      # package
    "\U0001f4e8": "[INBOX]",    # incoming envelope
    "\U0001f4e9": "[MAIL]",     # envelope with downwards arrow
    "\U0001f4f1": "[PHONE]",    # mobile phone
    "\U0001f501": "[REPEAT]",   # clockwise arrows
    "\U0001f504": "[REFRESH]",  # anticlockwise arrows
    "\U0001f50b": "[BATTERY]",  # battery
    "\U0001f525": "[FIRE]",     # fire
    "\U0001f527": "[WRENCH]",   # wrench
    "\U0001f52c": "[LAB]",      # microscope
    "\U0001f52e": "[MAGIC]",    # crystal ball
    "\U0001f534": "[RED]",      # large red circle
    "\U0001f5a5": "[PC]",       # desktop computer
    "\U0001f5d1": "[DEL]",      # wastebasket
    "\U0001f5e3": "[SPEAK]",    # speaking head in silhouette
    "\U0001f600": "[SMILE]",    # grinning face
    "\U0001f602": "[LOL]",      # face with tears of joy
    "\U0001f60a": "[HAPPY]",    # smiling face with smiling eyes
    "\U0001f60e": "[COOL]",     # smiling face with sunglasses
    "\U0001f622": "[SAD]",      # crying face
    "\U0001f624": "[TRIUMPH]",  # face with look of triumph
    "\U0001f634": "[SLEEP]",    # sleeping face
    "\U0001f6a6": "[SIGNAL]",   # vertical traffic light
    "\U0001f6a9": "[FLAG]",     # triangular flag on post
    "\U0001f6ab": "[NOPE]",     # no entry sign
    "\U0001f6e0": "[TOOLS]",    # hammer and wrench
    "\U0001f7e1": "[YELLOW]",   # large yellow circle
    "\U0001f7e2": "[GREEN]",    # large green circle
    "\U0001f923": "[ROFL]",     # rolling on floor laughing
    "\U0001f99e": "[LOBSTER]",  # lobster
    "\U0001f9d0": "[THINK]",    # face with monocle
    "\U0001f9d1": "[PERSON]",   # adult
    "\U0001f9e9": "[PUZZLE]",   # jigsaw puzzle piece
    "\U0001f9ea": "[TEST]",     # test tube
    "\U0001fae1": "[SALUTE]",   # saluting face
    # Misc unicode symbols found in codebase
    "\u2702": "[CUT]",          # black scissors
    "\u2714": "[OK]",           # heavy check mark
    "\u2728": "[SPARK]",        # sparkles
    "\u2764": "[HEART]",        # heavy black heart
    "\u2696": "[BALANCE]",      # scales
    "\u269b": "[ATOM]",         # atom symbol
    "\u26a1": "[FLASH]",        # high voltage sign
    "\u27e8": "<",              # mathematical left angle bracket
    "\u27e9": ">",              # mathematical right angle bracket
    "\u2190": "<-",             # leftwards arrow
    "\u20e3": "[KEYCAP]",       # combining enclosing keycap
    # Box-drawing characters
    "\u2550": "=",              # double horizontal
    "\u2500": "-",              # single horizontal
    "\u2502": "|",              # light vertical
    "\u250c": "+",              # light down and right
    "\u2510": "+",              # light down and left
    "\u2514": "+",              # light up and right
    "\u2518": "+",              # light up and left
    "\u251c": "+",              # light vertical and right
    "\u2588": "#",              # full block
    "\u2591": ".",              # light shade
    "\u2593": "#",              # dark shade
    "\u2014": "--",             # em-dash
    # Arrows
    "\u2192": "->",             # right arrow
    # Smart quotes (curly quotes)
    "\u2019": "'",              # right single quotation mark
    "\u201d": "\"",             # right double quotation mark
    # Checkmarks
    "\u2713": "[OK]",           # check mark (U+2713)
    # Unicode bullet / middle dot variants
    "\u2022": "*",              # bullet
    "\u00b7": ".",              # middle dot
    # Replacement character (U+FFFD) — already-corrupted byte, replace with ?
    "\ufffd": "?",
    # Variation selector-16 (U+FE0F) — invisible modifier, strip it
    # Note: must come AFTER all emoji+VS-16 pairs above
    "\ufe0f": "",
    # Regional indicator letters (if any standalone)
    "\U0001f1ee": "[I]",        # regional indicator I
    "\U0001f1f3": "[N]",        # regional indicator N
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
