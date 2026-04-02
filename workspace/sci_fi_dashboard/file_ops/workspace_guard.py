"""
file_ops/workspace_guard.py — Path traversal prevention for MCP contexts.

Lightweight guard for use when full Sentinel isn't available (e.g. remote
agent connections). Enforces that all resolved paths stay within a declared
workspace root.
"""
from pathlib import Path
from typing import Literal


class WorkspaceGuard:
    def __init__(self, root: str | Path, mode: Literal["rw", "ro", "none"] = "rw"):
        self.root = Path(root).resolve()
        self.mode = mode

    def assert_readable(self, path: str) -> Path:
        """Resolve path, ensure within root, return resolved Path. Raise on escape."""
        return self._resolve_and_check(path)

    def assert_writable(self, path: str) -> Path:
        """Like assert_readable, but also checks mode != 'ro' and mode != 'none'."""
        if self.mode == "ro":
            raise PermissionError(f"Workspace is read-only (mode='ro'): {path!r}")
        if self.mode == "none":
            raise PermissionError(f"Workspace access is disabled (mode='none'): {path!r}")
        return self._resolve_and_check(path)

    def _resolve_and_check(self, path: str) -> Path:
        """
        1. Resolve path relative to self.root if not absolute
        2. Call .resolve() to follow symlinks
        3. Check resolved.is_relative_to(self.root)
        4. Reject null bytes in path string
        5. Reject if resolved path is a symlink pointing outside root
        6. Return resolved path
        Raise PermissionError with clear message on any violation.
        """
        # 4. Reject null bytes
        if "\x00" in path:
            raise PermissionError(f"Path contains null bytes: {path!r}")

        p = Path(path)

        # 1. If not absolute, resolve relative to root
        if not p.is_absolute():
            p = self.root / p

        # 2. Follow symlinks
        resolved = p.resolve()

        # 3. Check resolved is within root
        if not resolved.is_relative_to(self.root):
            raise PermissionError(
                f"Path escape detected: {path!r} resolves to {resolved}, "
                f"which is outside workspace root {self.root}"
            )

        # 5. Explicit symlink check: p.resolve() already followed symlinks so the
        #    is_relative_to check above covers them. This explicit step re-confirms
        #    in case of multi-hop symlink chains.
        if p.is_symlink() and not resolved.is_relative_to(self.root):
            raise PermissionError(
                f"Symlink {path!r} points outside workspace root {self.root}"
            )

        return resolved
