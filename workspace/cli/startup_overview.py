from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cli.chat_types import ChatLaunchOptions
from cli.first_run_bootstrap import needs_first_run_bootstrap


@dataclass(frozen=True)
class StartupDiagnostics:
    config_status: str
    config_path: Path
    safe_chat_model: str | None
    target: str
    gateway_url: str
    gateway_reachable: bool | None
    gateway_detail: str
    first_run_pending: bool
    next_action: str
    style_policy: dict[str, Any] | None = None


def collect_startup_diagnostics(
    options: ChatLaunchOptions,
    client: object | None = None,
) -> StartupDiagnostics:
    data_root = _resolve_data_root()
    config_path = data_root / "synapse.json"
    config_status, raw_config = _load_config(config_path)
    safe_model = _safe_chat_model(raw_config, options.target)

    port = int(options.port or (raw_config.get("gateway") or {}).get("port") or 8000)
    gateway_url = f"http://127.0.0.1:{port}"
    reachable, detail = _probe_gateway(client)
    style_policy = _probe_style_policy(client, options.resolved_session_key())

    workspace_dir = options.workspace_dir or data_root / "workspace"
    first_run_pending = _first_run_pending(workspace_dir)

    return StartupDiagnostics(
        config_status=config_status,
        config_path=config_path,
        safe_chat_model=safe_model,
        target=options.target,
        gateway_url=gateway_url,
        gateway_reachable=reachable,
        gateway_detail=detail,
        first_run_pending=first_run_pending,
        next_action=_next_action(config_status, first_run_pending),
        style_policy=style_policy,
    )


def build_startup_overview(diagnostics: StartupDiagnostics) -> str:
    model = diagnostics.safe_chat_model or "not configured"
    gateway = _format_gateway(diagnostics)
    first_run = "pending" if diagnostics.first_run_pending else "complete"
    lines = [
        "Hi, I'm Synapse.",
        "Use this shell when setup, model routing, gateway, or local chat feels off.",
        f"Config: {diagnostics.config_status} ({diagnostics.config_path})",
        f"Safe-chat model: {model}",
        f"Persona/default target: {diagnostics.target}",
        gateway,
    ]
    style = _format_style(diagnostics.style_policy)
    if style:
        lines.append(style)
    lines.extend(
        [
            f"First-run: {first_run}",
            f"Next: {diagnostics.next_action}",
        ]
    )
    return "\n".join(lines)


def normalize_safe_chat_model(model: str | None) -> str | None:
    if not model:
        return None
    value = str(model).strip()
    if not value:
        return None
    try:
        from sci_fi_dashboard.openai_codex_provider import (  # noqa: PLC0415
            is_openai_codex_model,
            normalize_openai_codex_model,
        )

        if is_openai_codex_model(value):
            return f"openai_codex/{normalize_openai_codex_model(value)}"
    except Exception:
        if _is_openai_codex_model(value):
            return f"openai_codex/{_normalize_openai_codex_model(value)}"
    return value


def _resolve_data_root() -> Path:
    raw = os.environ.get("SYNAPSE_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".synapse"


def _load_config(config_path: Path) -> tuple[str, dict[str, Any]]:
    if not config_path.exists():
        return "missing", {}
    try:
        with open(config_path, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except Exception:
        return "invalid", {}
    if not isinstance(raw, dict):
        return "invalid", {}

    try:
        from synapse_config import SynapseConfig  # noqa: PLC0415

        cfg = SynapseConfig.load()
        return "valid", {
            "providers": cfg.providers or {},
            "channels": cfg.channels or {},
            "model_mappings": cfg.model_mappings or {},
            "gateway": cfg.gateway or {},
            "session": cfg.session or {},
        }
    except Exception:
        return "valid", raw


def _safe_chat_model(raw_config: dict[str, Any], target: str) -> str | None:
    mappings = raw_config.get("model_mappings") or {}
    if not isinstance(mappings, dict):
        return None
    for key in ("casual", "chat", target, "safe"):
        model = _model_from_mapping(mappings.get(key))
        if model:
            return normalize_safe_chat_model(model)
    for value in mappings.values():
        model = _model_from_mapping(value)
        if model:
            return normalize_safe_chat_model(model)
    return None


def _model_from_mapping(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        model = value.get("model")
        return str(model) if model else None
    return None


def _probe_gateway(client: object | None) -> tuple[bool | None, str]:
    probe = getattr(client, "probe_health", None)
    if not callable(probe):
        return None, "not probed"
    try:
        reachable, detail = probe()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return bool(reachable), str(detail or "ok")


def _probe_style_policy(client: object | None, session_key: str) -> dict[str, Any] | None:
    probe = getattr(client, "get_style_policy", None)
    if not callable(probe):
        return None
    try:
        ok, payload = probe(session_key)
    except Exception:
        return None
    if ok and isinstance(payload, dict):
        return payload
    return None


def _format_style(policy: dict[str, Any] | None) -> str:
    if not policy:
        return ""
    tone = str(policy.get("tone") or "unknown")
    length = str(policy.get("length") or "unknown")
    source = str(policy.get("source") or "unknown")
    scope = str(policy.get("scope") or "unknown")
    return f"Style: {tone}, {length}, source={source}, scope={scope}"


def _first_run_pending(workspace_dir: Path) -> bool:
    try:
        return needs_first_run_bootstrap(workspace_dir)
    except Exception:
        return False


def _next_action(config_status: str, first_run_pending: bool) -> str:
    if config_status != "valid":
        return "run synapse onboard"
    if first_run_pending:
        return "send a message"
    return "send a message"


def _format_gateway(diagnostics: StartupDiagnostics) -> str:
    state = diagnostics.gateway_reachable
    if state is True:
        return f"Gateway: reachable at {diagnostics.gateway_url} ({diagnostics.gateway_detail})"
    if state is False:
        return f"Gateway: unreachable at {diagnostics.gateway_url} ({diagnostics.gateway_detail})"
    return f"Gateway: not probed at {diagnostics.gateway_url} ({diagnostics.gateway_detail})"


_OPENAI_CODEX_PREFIXES = ("openai_codex/", "openai-codex/", "codex/")
_OPENAI_CODEX_ALIASES = {
    "gpt-5": "gpt-5.4",
    "gpt5": "gpt-5.4",
    "codex": "gpt-5.4",
    "codex-latest": "gpt-5.4",
    "gpt-5-codex": "gpt-5.4",
    "gpt-5-mini": "gpt-5.4",
    "gpt5-mini": "gpt-5.4",
    "codex-mini": "gpt-5.4",
    "codex-mini-latest": "gpt-5.4",
    "gpt-5-codex-mini": "gpt-5.4",
}


def _is_openai_codex_model(model_ref: str) -> bool:
    lowered = model_ref.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _OPENAI_CODEX_PREFIXES)


def _normalize_openai_codex_model(model_ref: str) -> str:
    bare = model_ref.strip()
    lowered = bare.lower()
    for prefix in _OPENAI_CODEX_PREFIXES:
        if lowered.startswith(prefix):
            bare = bare[len(prefix) :]
            break
    return _OPENAI_CODEX_ALIASES.get(bare.lower(), bare or "gpt-5.4")
