"""System-operations tools — Claude-Code-like toolkit for the persona.

Tools exposed:
    bash_exec      — run a shell command with safety guards (owner-only)
    edit_file      — find/replace on a file, Sentinel-gated
    grep_tool      — ripgrep-powered search
    glob_tool      — filesystem pattern match
    edit_synapse_config
                   — edit ~/.synapse/synapse.json with JSON validation + backup
                     (lives outside Sentinel's project_root, so has its own safety)
    list_directory — directory listing (Sentinel-gated)

Safety contracts (shared across all write/exec tools):
    * owner_only = True   ← factory returns None for non-owner sessions
    * non-zero exit / SentinelError maps to ToolResult(is_error=True)
    * stdout/stderr capped at 60 KB per call
    * command timeout capped at 60 s
    * admin / privilege-escalation patterns are hard-blocked
    * deletes are NOT exposed — destructive ops require a separate consent path

See tool_registry.py for the ToolContext / SynapseTool contract.
"""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from sci_fi_dashboard.tool_registry import (
    SynapseTool,
    ToolContext,
    ToolFactory,
    ToolResult,
    error_result,
    text_result,
)

# ---------------------------------------------------------------------------
# Reachable-models discovery (shared by edit_synapse_config + list_available_models)
# ---------------------------------------------------------------------------

# Cache TTL — how long to trust a freshly fetched reachable list before re-querying.
# Tunable here without touching call sites.
_MODELS_CACHE_TTL_S = 300.0

# Auto-apply threshold — if a fuzzy match against the user's value scores at or
# above this similarity, we silently switch to the close match and tell the LLM
# what we did. Below this, we return suggestions and let the LLM retry. 0.85 is
# tuned so that "gemini-2.0-flash" auto-resolves to "github_copilot/gemini-2.0-flash-001"
# but "gemini-3-flash" (clearly a different generation) returns suggestions.
_FUZZY_AUTO_APPLY_THRESHOLD = 0.85
_FUZZY_SUGGESTION_CUTOFF = 0.5
_FUZZY_MAX_SUGGESTIONS = 5

# Module-level cache: {"models": [...], "expires_at": float, "fetched": bool}
# `fetched` tracks whether a discovery attempt has completed within the TTL —
# independent of whether it returned any models. Without this flag, an empty
# result (both endpoints offline) would falsify the cache check below and
# every subsequent call would burn another ~6s re-querying unreachable
# endpoints. With the flag, offline callers get the cached empty list for
# the full TTL window.
_models_cache: dict = {"models": [], "expires_at": 0.0, "fetched": False}


async def _discover_reachable_models(timeout: float = 3.0) -> list[str]:
    """Return list of reachable model strings (provider-prefixed).

    Queries Copilot /models endpoint and Ollama /api/tags. Returns empty list
    if neither reachable (best-effort, no exceptions raised). Caches result
    for ``_MODELS_CACHE_TTL_S`` seconds to avoid hammering endpoints when the
    LLM retries the tool repeatedly. The cache is considered fresh whenever a
    fetch has completed within the TTL — even if that fetch returned no
    models — so offline hosts don't re-query unreachable endpoints on every
    call.

    Returns provider-prefixed strings like:
        ["github_copilot/gpt-4o", "github_copilot/gemini-2.0-flash-001",
         "ollama_chat/llama3.2:3b", ...]
    """
    now = time.monotonic()
    if _models_cache["fetched"] and now < _models_cache["expires_at"]:
        return list(_models_cache["models"])

    models: list[str] = []

    try:
        import httpx  # type: ignore[import]
    except ImportError:
        # No httpx → can't reach any endpoints; return empty (best-effort).
        return []

    # --- GitHub Copilot /models ---
    try:
        from sci_fi_dashboard.llm_router import _get_copilot_token

        token = _get_copilot_token()
        if token and token != "missing":
            from litellm.llms.github_copilot.common_utils import (
                GITHUB_COPILOT_API_BASE,
                get_copilot_default_headers,
            )

            headers = {
                "Authorization": f"Bearer {token}",
                **get_copilot_default_headers(),
            }
            url = f"{GITHUB_COPILOT_API_BASE.rstrip('/')}/models"
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
            entries = data.get("data", data if isinstance(data, list) else [])
            for m in entries:
                mid = m.get("id") if isinstance(m, dict) else str(m)
                if mid:
                    models.append(f"github_copilot/{mid}")
    except Exception:
        pass  # Copilot unreachable — keep going

    # --- Ollama /api/tags ---
    try:
        base = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{base.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
        for m in data.get("models", []):
            name = m.get("name") if isinstance(m, dict) else None
            if name:
                models.append(f"ollama_chat/{name}")
    except Exception:
        pass  # Ollama unreachable — keep going

    deduped = sorted(set(models))
    _models_cache["models"] = deduped
    _models_cache["expires_at"] = now + _MODELS_CACHE_TTL_S
    # Mark the cache as fetched-within-TTL even when ``deduped`` is empty so
    # offline callers don't re-query both endpoints (~6s round trip) on every
    # subsequent call. TTL expiry still triggers a refetch.
    _models_cache["fetched"] = True
    return list(deduped)


_VERSION_DIGIT_RE = re.compile(r"\d+")


def _version_digits(s: str) -> tuple[str, ...]:
    """Extract digit-only tokens from a model name as a version signature.

    ``"gemini-2.0-flash"`` → ``("2", "0")``
    ``"gemini-2.5-flash"`` → ``("2", "5")``
    ``"gemini-2.0-flash-001"`` → ``("2", "0", "001")``
    ``"gpt-4o-mini"`` → ``("4",)``

    Used to guard against silently auto-applying a different-version model
    (the SequenceMatcher ratio is too tolerant of single-digit version diffs).
    """
    return tuple(_VERSION_DIGIT_RE.findall(s))


def _digit_compat(req: str, cand: str) -> bool:
    """Return True if ``req`` and ``cand`` have compatible version digits.

    Compatible = req's digits are a prefix of cand's digits, OR identical.
    This catches the common "drop the build suffix" pattern
    (``gemini-2.0-flash`` is compatible with ``gemini-2.0-flash-001``)
    while flagging cross-version confusion
    (``gemini-2.0-flash`` is NOT compatible with ``gemini-2.5-flash``).

    If req has no digits, anything is compatible (fall back to similarity alone).
    """
    rd = _version_digits(req)
    cd = _version_digits(cand)
    if not rd:
        return True
    if len(rd) > len(cd):
        return False
    return cd[: len(rd)] == rd


def _fuzzy_match_model(value: str, reachable: list[str]) -> tuple[list[str], str | None, float]:
    """Fuzzy-match ``value`` against ``reachable`` model strings.

    Returns ``(suggestions, top_match, similarity)`` where:
        * suggestions: deduped, ordered list of up to ``_FUZZY_MAX_SUGGESTIONS``
          closest matches against both full strings and bare model suffixes.
        * top_match: the highest-scoring candidate that has *compatible*
          version digits with the request (see ``_digit_compat``). If no
          digit-compatible candidate exists, falls back to the highest
          similarity overall but reports ``similarity`` capped below the
          auto-apply threshold so the caller treats it as ambiguous.
        * similarity: SequenceMatcher ratio for the top match (0..1).

    Pure function — no I/O, no side effects.
    """
    if not reachable:
        return ([], None, 0.0)

    # Match against full "provider/model" strings.
    close_full = difflib.get_close_matches(
        value, reachable, n=_FUZZY_MAX_SUGGESTIONS, cutoff=_FUZZY_SUGGESTION_CUTOFF
    )

    # Also match against bare model names (suffix after last "/") — user may
    # type "gemini-2.0-flash-001" without the "github_copilot/" prefix.
    suffix_map: dict[str, str] = {}
    for m in reachable:
        suffix = m.rsplit("/", 1)[-1]
        # First-wins so we don't accidentally collapse two providers' models
        # with identical local names.
        suffix_map.setdefault(suffix, m)
    value_suffix = value.rsplit("/", 1)[-1]
    close_suffix_keys = difflib.get_close_matches(
        value_suffix,
        list(suffix_map.keys()),
        n=_FUZZY_MAX_SUGGESTIONS,
        cutoff=_FUZZY_SUGGESTION_CUTOFF,
    )
    close_from_suffix = [suffix_map[s] for s in close_suffix_keys]

    # Score every candidate by max(full-similarity, suffix-similarity) and
    # remember whether its version digits are compatible with the request.
    scored: list[tuple[float, bool, str]] = []  # (similarity, digit_compat, model)
    seen_for_score: set[str] = set()
    for cand in close_full + close_from_suffix:
        if cand in seen_for_score:
            continue
        seen_for_score.add(cand)
        cand_suffix = cand.rsplit("/", 1)[-1]
        s = max(
            difflib.SequenceMatcher(None, value, cand).ratio(),
            difflib.SequenceMatcher(None, value_suffix, cand_suffix).ratio(),
        )
        compat = _digit_compat(value_suffix, cand_suffix)
        scored.append((s, compat, cand))

    if not scored:
        return ([], None, 0.0)

    # Build the suggestions list ordered by score (compat-first, then similarity).
    # Compat candidates always rank above non-compat ones — version sanity
    # beats raw similarity when picking what to surface to the LLM.
    scored.sort(key=lambda t: (t[1], t[0]), reverse=True)
    suggestions = [m for _, _, m in scored][:_FUZZY_MAX_SUGGESTIONS]

    # Pick the top match with care:
    #   * if any candidate is digit-compatible, take the highest-similarity
    #     compatible one and report its real similarity.
    #   * otherwise, the request is asking for a different version that we
    #     don't have. Return the closest by similarity but cap reported
    #     similarity below the auto-apply threshold so the caller surfaces
    #     suggestions instead of silently swapping versions.
    compatible = [(s, m) for s, ok, m in scored if ok]
    if compatible:
        compatible.sort(reverse=True)
        top_sim, top = compatible[0]
        return (suggestions, top, top_sim)

    # No digit-compatible candidate. Surface the closest by similarity, but
    # report a capped similarity so the caller treats this as ambiguous.
    top_sim, _, top = scored[0]
    capped = min(top_sim, _FUZZY_AUTO_APPLY_THRESHOLD - 0.01)
    return (suggestions, top, capped)


# ---------------------------------------------------------------------------
# RT3.6: trust-prefix fallback — configured-provider awareness
# ---------------------------------------------------------------------------

# Placeholder patterns that indicate a provider key was never set to a real value.
# Keys starting with these or matching these literal strings are NOT considered
# configured — provider stays out of the trusted set.
_PLACEHOLDER_KEY_PREFIXES = ("YOUR_",)
_PLACEHOLDER_KEY_LITERALS = frozenset({"PLACEHOLDER", "changeme"})

# Providers that always live in the trusted set regardless of synapse.json keys:
#   * github_copilot — uses JWT exchange in llm_router, not a synapse.json key
#   * ollama / ollama_chat — local daemon, no API key required
# These are the providers the fuzzy-match fast-path already queries for live
# models, so trust-prefix should accept them unconditionally.
_ALWAYS_TRUSTED_PROVIDERS = frozenset({"github_copilot", "ollama_chat", "ollama"})


def _get_configured_providers() -> set[str]:
    """Return the set of provider names trusted by the trust-prefix fallback.

    A provider is "configured" if:
      * Its ``api_key`` in ``synapse.json → providers.<name>`` is a non-empty
        string that is not a placeholder (does not start with ``YOUR_`` and is
        not literal ``PLACEHOLDER`` / ``changeme``), OR
      * It is one of the always-trusted special-auth providers
        (``github_copilot``, ``ollama_chat``, ``ollama``) — Copilot exchanges a
        JWT from ``~/.config/litellm/github_copilot/api-key.json`` and Ollama
        runs locally, so neither is gated by a synapse.json key.

    Intentionally NOT cached — ``synapse.json`` may be mutated by this very tool
    during a session, and we want the next call to see the new provider state.

    Returns the always-trusted set on any failure (config missing / malformed /
    import error), so trust-prefix degrades gracefully to "Copilot+Ollama only".
    """
    configured: set[str] = set(_ALWAYS_TRUSTED_PROVIDERS)

    try:
        from synapse_config import SynapseConfig  # local import — avoid cycles
        cfg = SynapseConfig.load()
        providers = getattr(cfg, "providers", None) or {}
    except Exception:
        return configured

    for name, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        key = provider_cfg.get("api_key", "")
        if not isinstance(key, str):
            continue
        key = key.strip()
        if not key:
            continue
        if any(key.startswith(p) for p in _PLACEHOLDER_KEY_PREFIXES):
            continue
        if key in _PLACEHOLDER_KEY_LITERALS:
            continue
        configured.add(name)

    return configured


def _trust_prefix_error(value: str, fuzzy_suggestions: list[str] | None = None) -> str | None:
    """Validate ``value`` via the trust-prefix fallback.

    Returns an error message if the value should be rejected, or ``None`` if
    the value's provider prefix is a configured provider (silently accept).

    Inputs without a ``/`` separator are rejected — we cannot infer which
    provider is intended. Inputs whose prefix is not a configured provider are
    rejected with an actionable hint pointing at synapse.json providers config
    and TOOLS.md's curl recipes.

    The optional ``fuzzy_suggestions`` list is surfaced in the unknown-provider
    error so the LLM still sees Copilot/Ollama alternatives it might want to
    pick instead (e.g. user typed ``deepseek/foo`` but a close Copilot model
    exists).
    """
    configured = _get_configured_providers()
    configured_list = ", ".join(sorted(configured))

    if "/" not in value:
        return (
            f"model value {value!r} is missing a provider prefix. "
            f"Configured providers: {configured_list}. "
            f"Format is 'provider/model-name' — e.g. 'anthropic/claude-3-5-sonnet-20241022'. "
            f"For unknown providers, run bash_exec with the provider's /models endpoint "
            f"(see TOOLS.md → Provider Model Discovery)."
        )

    prefix = value.split("/", 1)[0]
    if prefix not in configured:
        hint = ""
        if fuzzy_suggestions:
            hint = (
                f" Closest reachable models (Copilot/Ollama): "
                f"{', '.join(fuzzy_suggestions)}."
            )
        return (
            f"unknown provider {prefix!r} in {value!r}. "
            f"Configured providers (synapse.json): {configured_list}. "
            f"To use {prefix}, first add a real api_key to synapse.json → providers.{prefix}, "
            f"then verify the model name exists (see TOOLS.md → Provider Model Discovery "
            f"for the curl recipe).{hint}"
        )

    # Prefix matches a configured provider — accept. Runtime LLM call validates
    # the specific model name.
    return None


# ---------------------------------------------------------------------------
# Shared safety primitives
# ---------------------------------------------------------------------------

# Commands that attempt to escalate to admin / modify system state — always denied.
# Matched as whole words / tokens (case-insensitive) inside the command string.
_ADMIN_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsudo\b",
        r"\bsu\s",
        r"\brunas\b",
        r"\bnet\s+user\b",
        r"\bnet\s+localgroup\b",
        r"\bnetsh\b",
        r"\breg\s+add\s+HKLM",
        r"\breg\s+delete\s+HKLM",
        r"\bicacls\b.*\/grant",
        r"\btakeown\b",
        r"\bschtasks\b",
        r"\bmklink\s+\/D",
        r"\bformat\s+[a-z]:",
        r"\bdiskpart\b",
        r"\bshutdown\b",
        r"\brestart-computer\b",
        r"\bchown\b",
        r"\bchmod\b\s+\+s",  # setuid
    )
)

# Commands that delete or destroy data — require explicit consent workflow,
# which doesn't exist yet, so block until it does.
_DESTRUCTIVE_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brm\s+-rf\b",
        r"\brm\s+-fr\b",
        r"\brmdir\s+\/s",
        r"\brd\s+\/s",
        r"\bdel\s+\/s",
        r"\bformat\b",
        r">\s*\/dev\/sd",
        r"\bdd\s+.*of=\/dev",
        r"\bmkfs\b",
        r"\bgit\s+push.*--force\b",
        r"\bgit\s+push.*-f\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-fd\b",
    )
)

_MAX_OUTPUT_BYTES = 60_000
_MAX_TIMEOUT_S = 60
_DEFAULT_TIMEOUT_S = 30


def _reject(command: str) -> str | None:
    """Return a denial reason if the command is blocked, else None."""
    for p in _ADMIN_PATTERNS:
        if p.search(command):
            return f"admin/privileged command pattern denied: {p.pattern}"
    for p in _DESTRUCTIVE_PATTERNS:
        if p.search(command):
            return (
                f"destructive command pattern denied (consent workflow required): "
                f"{p.pattern}"
            )
    return None


def _truncate(data: bytes, limit: int = _MAX_OUTPUT_BYTES) -> str:
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace")
    head = data[: limit // 2].decode("utf-8", errors="replace")
    tail = data[-limit // 2 :].decode("utf-8", errors="replace")
    return f"{head}\n...[{len(data) - limit} bytes elided]...\n{tail}"


# ---------------------------------------------------------------------------
# bash_exec — shell execution with safety
# ---------------------------------------------------------------------------


def _bash_exec_factory(ctx: ToolContext) -> SynapseTool | None:
    if not ctx.sender_is_owner:
        return None

    async def _execute(arguments: dict) -> ToolResult:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return error_result("command is empty")
        deny = _reject(command)
        if deny:
            return error_result(deny)

        timeout = min(int(arguments.get("timeout", _DEFAULT_TIMEOUT_S)), _MAX_TIMEOUT_S)
        cwd = arguments.get("cwd") or ctx.workspace_dir

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return error_result(f"command timed out after {timeout}s")
        except Exception as e:
            return error_result(f"subprocess failed: {e}")

        payload = {
            "command": command,
            "cwd": cwd,
            "exit_code": proc.returncode,
            "stdout": _truncate(stdout),
            "stderr": _truncate(stderr),
        }
        is_error = proc.returncode != 0
        return ToolResult(content=json.dumps(payload, ensure_ascii=False), is_error=is_error)

    return SynapseTool(
        name="bash_exec",
        description=(
            "Run a shell command in the project. Output capped at 60KB, timeout capped "
            "at 60s. Denies sudo / runas / format / rm -rf / git push --force etc. "
            "Returns JSON {command, cwd, exit_code, stdout, stderr}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory. Defaults to workspace root.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds before the command is killed (max 60).",
                },
            },
            "required": ["command"],
        },
        execute=_execute,
        owner_only=True,
        serial=True,
    )


# ---------------------------------------------------------------------------
# edit_file — find/replace on an existing file (Sentinel-gated)
# ---------------------------------------------------------------------------


def _edit_file_factory(ctx: ToolContext) -> SynapseTool | None:
    if not ctx.sender_is_owner:
        return None

    async def _execute(arguments: dict) -> ToolResult:
        path = str(arguments.get("path", "")).strip()
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not path or old is None or new is None:
            return error_result("path, old_string, new_string are required")

        try:
            from sci_fi_dashboard.sbs.sentinel.tools import (
                agent_read_file,
                agent_write_file,
            )

            current = agent_read_file(path, reason="edit_file: pre-check")
            if current.startswith("[SENTINEL DENIED]"):
                return error_result(current)
            if old not in current:
                return error_result(
                    "old_string not found in file — the Edit tool requires exact match."
                )
            count = current.count(old)
            if count > 1 and not arguments.get("replace_all"):
                return error_result(
                    f"old_string appears {count}x; pass replace_all=true to replace all "
                    "or add surrounding context to make old_string unique."
                )
            updated = current.replace(old, new) if arguments.get("replace_all") else current.replace(
                old, new, 1
            )
            result = agent_write_file(path, updated, reason=arguments.get("reason", "edit_file"))
            if result.startswith("[SENTINEL DENIED]"):
                return error_result(result)
            return text_result(f"edited {path} ({count if arguments.get('replace_all') else 1} replacement(s))")
        except Exception as e:
            return error_result(f"edit_file failed: {e}")

    return SynapseTool(
        name="edit_file",
        description=(
            "Find-and-replace a string in a file. Sentinel-gated. old_string must be "
            "unique unless replace_all=true. Matches Claude Code's Edit tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path."},
                "old_string": {"type": "string", "description": "Exact text to find."},
                "new_string": {"type": "string", "description": "Replacement text."},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every occurrence (default false).",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    "description": "Short audit-log reason for the edit.",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        execute=_execute,
        owner_only=True,
    )


# ---------------------------------------------------------------------------
# grep_tool — search file contents (ripgrep if available, fallback to Python)
# ---------------------------------------------------------------------------


def _grep_factory(ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        pattern = str(arguments.get("pattern", ""))
        path = str(arguments.get("path", ctx.workspace_dir))
        glob = arguments.get("glob")
        ignore_case = arguments.get("ignore_case", False)
        max_results = min(int(arguments.get("max_results", 100)), 500)

        if not pattern:
            return error_result("pattern is required")

        rg = shutil.which("rg")
        if rg:
            args = [rg, "--no-heading", "--line-number", "--max-count", str(max_results)]
            if ignore_case:
                args.append("-i")
            if glob:
                args.extend(["--glob", glob])
            args.extend([pattern, path])
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                out = _truncate(stdout)
                if proc.returncode not in (0, 1):
                    return error_result(_truncate(stderr) or "rg failed")
                return text_result(out or "(no matches)")
            except asyncio.TimeoutError:
                return error_result("grep timed out")

        # Python fallback
        import re as _re

        flags = _re.IGNORECASE if ignore_case else 0
        try:
            rx = _re.compile(pattern, flags)
        except _re.error as e:
            return error_result(f"invalid regex: {e}")
        matches: list[str] = []
        base = Path(path)
        files = base.rglob(glob) if glob else base.rglob("*")
        for f in files:
            if not f.is_file():
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        matches.append(f"{f}:{i}:{line[:240]}")
                        if len(matches) >= max_results:
                            return text_result("\n".join(matches))
            except Exception:
                continue
        return text_result("\n".join(matches) if matches else "(no matches)")

    return SynapseTool(
        name="grep_tool",
        description=(
            "Search file contents for a regex pattern. Uses ripgrep when available; "
            "returns `path:line:preview` style matches. Max 500 results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern."},
                "path": {"type": "string", "description": "Directory or file to search."},
                "glob": {"type": "string", "description": "Optional glob to restrict files."},
                "ignore_case": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# glob_tool — find files by pattern
# ---------------------------------------------------------------------------


def _glob_factory(ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        pattern = str(arguments.get("pattern", "")).strip()
        root = str(arguments.get("path", ctx.workspace_dir))
        if not pattern:
            return error_result("pattern is required")
        max_results = min(int(arguments.get("max_results", 200)), 1000)
        base = Path(root)
        if not base.exists():
            return error_result(f"path does not exist: {root}")
        matches = []
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            if fnmatch.fnmatch(str(f), pattern) or fnmatch.fnmatch(f.name, pattern):
                matches.append(str(f))
                if len(matches) >= max_results:
                    break
        return text_result("\n".join(matches) if matches else "(no matches)")

    return SynapseTool(
        name="glob_tool",
        description=(
            "Find files whose path or name matches a glob pattern (e.g. '**/*.py'). "
            "Returns newline-delimited absolute paths."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern."},
                "path": {"type": "string", "description": "Root directory to search."},
                "max_results": {"type": "integer", "default": 200},
            },
            "required": ["pattern"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# edit_synapse_config — bespoke tool for ~/.synapse/synapse.json
# Lives outside Sentinel's project_root, so has its own JSON+backup safety.
# ---------------------------------------------------------------------------


def _edit_synapse_config_factory(ctx: ToolContext) -> SynapseTool | None:
    if not ctx.sender_is_owner:
        return None

    config_path = Path.home() / ".synapse" / "synapse.json"

    async def _execute(arguments: dict) -> ToolResult:
        action = str(arguments.get("action", "get"))

        if not config_path.exists():
            return error_result(f"config not found: {config_path}")

        try:
            raw = config_path.read_text(encoding="utf-8")
            cfg = json.loads(raw)
        except Exception as e:
            return error_result(f"failed to load config: {e}")

        if action == "get":
            key_path = arguments.get("key_path")
            if not key_path:
                return text_result(json.dumps(cfg, indent=2))
            node = cfg
            for part in key_path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return error_result(f"key_path not found: {key_path}")
                node = node[part]
            return text_result(json.dumps(node, indent=2))

        if action == "set":
            key_path = arguments.get("key_path")
            value = arguments.get("value")
            if not key_path:
                return error_result("key_path required for set")

            # Validate model mapping values. Two-stage pipeline:
            #   1. Fuzzy-match fast-path against reachable (Copilot + Ollama)
            #        * exact match      → apply as-is
            #        * close match ≥0.85 → auto-apply closest + surface note
            #   2. Trust-prefix fallback (RT3.6) for everything else
            #        * prefix is a configured provider     → accept silently
            #        * prefix unknown or missing           → reject with hint
            #
            # The fallback lets non-Copilot/Ollama providers (anthropic, openai,
            # gemini, etc.) through without ever touching their /models HTTP
            # endpoints — we trust the user's choice once we've confirmed the
            # provider is actually configured with a real key. Runtime LLM call
            # will catch mistyped model names.
            auto_applied_note: str | None = None
            if key_path.startswith("model_mappings.") and key_path.endswith(".model"):
                if not isinstance(value, str):
                    return error_result(
                        f"model value must be a string, got {type(value).__name__}"
                    )

                reachable = await _discover_reachable_models()

                if reachable and value not in reachable:
                    suggestions, top, similarity = _fuzzy_match_model(value, reachable)

                    if similarity >= _FUZZY_AUTO_APPLY_THRESHOLD and top is not None:
                        # Auto-apply the closest match — record what we changed
                        # so the success response can carry a note to the LLM.
                        auto_applied_note = (
                            f"requested model {value!r} was not reachable; "
                            f"auto-applied closest match {top!r} "
                            f"(similarity {similarity:.2f})"
                        )
                        value = top
                    else:
                        # No confident Copilot/Ollama match — fall back to the
                        # trust-prefix check. If the user's prefix is a configured
                        # provider, accept the value (runtime LLM call validates
                        # the specific model name). Otherwise surface an error
                        # that lists real configured providers and, when we have
                        # them, the closest Copilot/Ollama suggestions too.
                        trust_error = _trust_prefix_error(value, suggestions)
                        if trust_error:
                            return error_result(trust_error)
                elif not reachable:
                    # Copilot + Ollama both unreachable (offline or no token) —
                    # trust-prefix is the only safety net available. Same rules:
                    # accept configured providers, reject unknown ones.
                    trust_error = _trust_prefix_error(value)
                    if trust_error:
                        return error_result(trust_error)

            parts = key_path.split(".")
            node = cfg
            for part in parts[:-1]:
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]
            node[parts[-1]] = value

            # Atomic write with backup
            backup = config_path.with_suffix(f".json.bak.{int(time.time())}")
            backup.write_text(raw, encoding="utf-8")
            tmp = config_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            tmp.replace(config_path)

            # Hot-reload: re-read config into the running process and rebuild
            # the LLM router so the change takes effect immediately.
            reload_msg = ""
            try:
                from synapse_config import SynapseConfig
                from sci_fi_dashboard import _deps as deps

                new_cfg = SynapseConfig.load()
                deps._synapse_cfg = new_cfg
                if hasattr(deps, "synapse_llm_router") and deps.synapse_llm_router:
                    deps.synapse_llm_router._config = new_cfg
                    deps.synapse_llm_router._rebuild_router()
                    reload_msg = " — router hot-reloaded, no restart needed."
            except Exception as e:
                reload_msg = f" — hot-reload failed ({e}); restart server to apply."

            payload: dict = {
                "status": "applied",
                "key_path": key_path,
                "value": value,
                "backup": backup.name,
                "reload": reload_msg.strip(" —") or "ok",
            }
            if auto_applied_note:
                payload["note"] = auto_applied_note
            return text_result(json.dumps(payload, ensure_ascii=False))

        return error_result(f"unknown action: {action}")

    return SynapseTool(
        name="edit_synapse_config",
        description=(
            "Read or set values in ~/.synapse/synapse.json. action=get returns the "
            "config (or a sub-path via key_path like 'model_mappings.code.model'). "
            "action=set writes a new value with JSON validation, a timestamped "
            "backup, and a hot-reload of the LLM router (no server restart needed). "
            "For model keys (model_mappings.*.model), the value is fuzzy-matched "
            "against reachable Copilot + Ollama models — if your input is close to "
            "a real model name, the closest match auto-applies and the response "
            "includes a 'note' field explaining what was applied. If no close "
            "Copilot/Ollama match, the value is accepted as-is when its "
            "'provider/' prefix names a provider with a real api_key in "
            "synapse.json (anthropic, openai, gemini, etc.). Unknown or missing "
            "prefixes are rejected with an error listing the configured "
            "providers. Owner only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set"],
                    "description": "get reads, set writes.",
                },
                "key_path": {
                    "type": "string",
                    "description": "Dotted key path e.g. 'model_mappings.code.model'.",
                },
                "value": {
                    "description": "New value (any JSON) for set. Ignored for get.",
                },
            },
            "required": ["action"],
        },
        execute=_execute,
        owner_only=True,
    )


# ---------------------------------------------------------------------------
# list_directory — list a directory (Sentinel-gated)
# ---------------------------------------------------------------------------


def _list_directory_factory(_ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        path = str(arguments.get("path", ".")).strip()
        try:
            from sci_fi_dashboard.sbs.sentinel.tools import agent_list_directory

            out = agent_list_directory(path, reason=arguments.get("reason", "list_directory"))
            if out.startswith("[SENTINEL DENIED]"):
                return error_result(out)
            return text_result(out or "(empty)")
        except Exception as e:
            return error_result(f"list_directory failed: {e}")

    return SynapseTool(
        name="list_directory",
        description="List entries in a directory. Sentinel-gated.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path."},
                "reason": {"type": "string", "description": "Optional audit reason."},
            },
            "required": ["path"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# list_available_models — discover what models are actually reachable
# ---------------------------------------------------------------------------


def _list_available_models_factory(_ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        provider_filter = str(arguments.get("provider", "")).strip().lower()

        out: dict = {"providers": {}}

        # Reuse the shared discovery helper so both tools see the same view of
        # reachable models AND share the 5-minute cache (avoids re-hitting
        # Copilot /models when the LLM calls list → fuzzy-fail → list again).
        # Use a longer timeout here since callers explicitly invoke this tool
        # to discover what's available.
        all_reachable = await _discover_reachable_models(timeout=15.0)

        copilot_models = sorted(m for m in all_reachable if m.startswith("github_copilot/"))
        ollama_models = sorted(m for m in all_reachable if m.startswith("ollama_chat/"))

        if not provider_filter or provider_filter == "github_copilot":
            out["providers"]["github_copilot"] = copilot_models or {
                "error": "no copilot models reachable (token missing or endpoint down)"
            }

        if not provider_filter or provider_filter == "ollama":
            out["providers"]["ollama"] = ollama_models or {
                "error": "no ollama models reachable (daemon down or no models pulled)"
            }

        # --- Configured (synapse.json) providers as hints ---
        try:
            cfg_path = Path.home() / ".synapse" / "synapse.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg_providers = list((cfg.get("providers") or {}).keys())
                out["providers_configured"] = cfg_providers
                out["current_mappings"] = {
                    role: v.get("model")
                    for role, v in (cfg.get("model_mappings") or {}).items()
                }
        except Exception:
            pass

        return text_result(json.dumps(out, indent=2))

    return SynapseTool(
        name="list_available_models",
        description=(
            "Discover which LLM models are actually reachable from this host. "
            "Queries GitHub Copilot's /models endpoint and the local Ollama "
            "daemon, and returns the current synapse.json model mappings. Use "
            "this BEFORE edit_synapse_config when the user asks to change a "
            "model — so you pick a real model name, not a guess."
        ),
        parameters={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Optional filter: 'github_copilot' or 'ollama'.",
                }
            },
        },
        execute=_execute,
    )


def register_sysops_tools(registry, memory_engine=None, project_root: str = "") -> None:
    """Register the sysops tool bundle on the given ToolRegistry."""
    registry.register_factory("bash_exec", _bash_exec_factory)
    registry.register_factory("edit_file", _edit_file_factory)
    registry.register_factory("grep_tool", _grep_factory)
    registry.register_factory("glob_tool", _glob_factory)
    registry.register_factory("edit_synapse_config", _edit_synapse_config_factory)
    registry.register_factory("list_directory", _list_directory_factory)
    registry.register_factory("list_available_models", _list_available_models_factory)
