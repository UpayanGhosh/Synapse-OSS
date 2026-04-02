"""
file_ops/edit.py — Apply text patches to files with atomic writes.
"""
import os
from pathlib import Path


def apply_edit(
    path: str,
    old_text: str,
    new_text: str,
    *,
    expected_count: int = 1,
    project_root: str | None = None,
) -> dict:
    """
    Replace the first ``expected_count`` occurrences of ``old_text`` with
    ``new_text`` in the file at ``path``, using an atomic temp-file + rename write.

    Returns:
        {"ok": True, "bytes_written": int, "replacements": int}
        {"ok": False, "error": str}
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    count = content.count(old_text)

    if count == 0:
        return {"ok": False, "error": "old_text not found in file"}

    if count > expected_count:
        return {
            "ok": False,
            "error": (
                f"old_text found {count} times, expected {expected_count}. "
                "Provide more context."
            ),
        }

    # Replace first N occurrences via loop (not str.replace which does all)
    new_content = content
    count_replaced = 0
    while count_replaced < expected_count:
        idx = new_content.find(old_text)
        if idx == -1:
            break
        new_content = new_content[:idx] + new_text + new_content[idx + len(old_text):]
        count_replaced += 1

    # Atomic write: temp file + os.replace()
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(str(tmp), path)
    except Exception:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise

    return {
        "ok": True,
        "bytes_written": len(new_content.encode("utf-8")),
        "replacements": count_replaced,
    }
