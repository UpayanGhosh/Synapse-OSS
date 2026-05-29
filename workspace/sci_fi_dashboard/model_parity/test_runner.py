from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from sci_fi_dashboard.model_parity.scoring_engine import (
    ModelResponse,
    ScoreResult,
    score_response,
)

DEFAULT_SCENARIOS = Path(__file__).with_name("scenarios.yaml")


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    prompt: str
    scoring: dict[str, Any]


@dataclass(frozen=True)
class ModelCandidate:
    role: str
    model: str
    tier: str
    provider: str


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario_id: str
    category: str
    candidate: ModelCandidate
    score: ScoreResult
    response: ModelResponse


@dataclass(frozen=True)
class ParityRunResult:
    run_id: str
    output_dir: Path
    results: list[ScenarioRunResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(item.score.passed for item in self.results)


class ParityClient(Protocol):
    async def run_scenario(
        self, scenario: Scenario, candidate: ModelCandidate
    ) -> ModelResponse: ...


class HttpParityClient:
    """POST scenarios to /chat/{target}, using the env-gated parity role header."""

    def __init__(
        self,
        *,
        base_url: str,
        target: str = "the_creator",
        api_key: str | None = None,
        timeout_s: float = 180.0,
        user_id: str = "the_creator",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.target = target
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.user_id = user_id

    async def run_scenario(self, scenario: Scenario, candidate: ModelCandidate) -> ModelResponse:
        import httpx

        headers = {"X-Synapse-Model-Role": candidate.role}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        payload = {
            "message": scenario.prompt,
            "history": [],
            "user_id": self.user_id,
            "session_key": f"parity:{candidate.role}:{scenario.id}",
        }
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/chat/{self.target}",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _response_from_payload(data, latency_ms=latency_ms)


class InProcessParityClient:
    """Call persona_chat in-process and set the existing per-session model override."""

    def __init__(self, *, target: str = "the_creator", user_id: str = "the_creator") -> None:
        self.target = target
        self.user_id = user_id
        self._tools_initialized = False

    async def run_scenario(self, scenario: Scenario, candidate: ModelCandidate) -> ModelResponse:
        from sci_fi_dashboard import _deps as deps
        from sci_fi_dashboard.chat_pipeline import persona_chat
        from sci_fi_dashboard.schemas import ChatRequest
        from sci_fi_dashboard.tool_features import (
            clear_model_override,
            get_model_override,
            set_model_override,
        )

        self._ensure_tool_registry(deps)
        previous = get_model_override(self.user_id)
        set_model_override(self.user_id, candidate.role)
        started = time.perf_counter()
        try:
            payload = await persona_chat(
                ChatRequest(
                    message=scenario.prompt,
                    history=[],
                    user_id=self.user_id,
                    session_key=f"parity:{candidate.role}:{scenario.id}",
                ),
                self.target,
                None,
            )
        finally:
            if previous:
                set_model_override(self.user_id, previous)
            else:
                clear_model_override(self.user_id)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _response_from_payload(payload, latency_ms=latency_ms)

    def _ensure_tool_registry(self, deps: Any) -> None:
        if self._tools_initialized or deps.tool_registry is not None:
            self._tools_initialized = True
            return
        if getattr(deps, "_TOOL_REGISTRY_AVAILABLE", False) is not True:
            return
        try:
            from sci_fi_dashboard.tool_registry import ToolRegistry, register_builtin_tools
            from sci_fi_dashboard.tool_sysops import register_sysops_tools

            deps.tool_registry = ToolRegistry()
            register_builtin_tools(deps.tool_registry, deps.memory_engine, deps.WORKSPACE_ROOT)
            register_sysops_tools(deps.tool_registry, deps.memory_engine, deps.WORKSPACE_ROOT)
            self._tools_initialized = True
        except Exception:
            deps.tool_registry = None


class FixtureParityClient:
    """Deterministic client for unit tests and offline demos."""

    def __init__(self, replies: dict[tuple[str, str], ModelResponse | str]) -> None:
        self.replies = replies

    async def run_scenario(self, scenario: Scenario, candidate: ModelCandidate) -> ModelResponse:
        key = (candidate.role, scenario.id)
        value = self.replies.get(key) or self.replies.get(("*", scenario.id))
        if isinstance(value, ModelResponse):
            return value
        if isinstance(value, str):
            return ModelResponse(text=value, model=candidate.model, raw={"fixture": True})
        return ModelResponse(text="", model=candidate.model, raw={"fixture_missing": key})


async def run_parity(
    *,
    scenarios: list[Scenario],
    candidates: list[ModelCandidate],
    client: ParityClient,
    output_dir: Path | None = None,
    similarity_backend: Any | None = None,
    fail_fast: bool = False,
) -> ParityRunResult:
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = output_dir or Path("runs") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[ScenarioRunResult] = []
    for candidate in candidates:
        for scenario in scenarios:
            try:
                response = await client.run_scenario(scenario, candidate)
                score = score_response(
                    scenario,
                    response,
                    tier=candidate.tier,
                    similarity_backend=similarity_backend,
                )
            except Exception as exc:
                response = ModelResponse(
                    text="",
                    model=candidate.model,
                    raw={"error": str(exc), "error_type": type(exc).__name__},
                )
                score = ScoreResult(score=0.0, passed=False, reason=f"runner error: {exc}")
            item = ScenarioRunResult(
                scenario_id=scenario.id,
                category=scenario.category,
                candidate=candidate,
                score=score,
                response=response,
            )
            results.append(item)
            if fail_fast and not score.passed:
                _write_artifacts(out_dir, run_id, results)
                return ParityRunResult(run_id=run_id, output_dir=out_dir, results=results)

    _write_artifacts(out_dir, run_id, results)
    return ParityRunResult(run_id=run_id, output_dir=out_dir, results=results)


def load_scenarios(path: str | Path = DEFAULT_SCENARIOS) -> list[Scenario]:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    entries = raw.get("scenarios", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError("scenarios YAML must be a list or {scenarios: [...]}")
    scenarios: list[Scenario] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"scenario must be a mapping, got {type(entry).__name__}")
        scenarios.append(
            Scenario(
                id=str(entry["id"]),
                category=str(entry.get("category", "uncategorized")),
                prompt=str(entry["prompt"]),
                scoring=dict(entry.get("scoring", {})),
            )
        )
    return scenarios


def load_model_candidates(
    config: Any | None = None,
    *,
    include_roles: set[str] | None = None,
    dedupe_models: bool = False,
) -> list[ModelCandidate]:
    if config is None:
        from synapse_config import SynapseConfig

        config = SynapseConfig.load()
    mappings = getattr(config, "model_mappings", {}) or {}
    candidates: list[ModelCandidate] = []
    seen_models: set[str] = set()
    for role, raw_cfg in mappings.items():
        if include_roles and role not in include_roles:
            continue
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {"model": str(raw_cfg)}
        model = str(cfg.get("model", "")).strip()
        if not model:
            continue
        if dedupe_models and model in seen_models:
            continue
        seen_models.add(model)
        candidates.append(
            ModelCandidate(
                role=str(role),
                model=model,
                tier=_infer_tier(model, cfg),
                provider=model.split("/", 1)[0] if "/" in model else "unknown",
            )
        )
    return candidates


def build_similarity_backend(config: Any | None = None) -> Any | None:
    """Best-effort embedding backend for live runs; scoring falls back if absent."""

    try:
        from sci_fi_dashboard.embedding import get_provider

        return get_provider({"embedding": getattr(config, "embedding", {})} if config else None)
    except Exception:
        return None


def _write_artifacts(out_dir: Path, run_id: str, results: list[ScenarioRunResult]) -> None:
    _write_parity_matrix(out_dir / "parity_matrix.csv", results)
    _write_failures(out_dir / "per_model_failures.md", results)
    _write_trend(out_dir / "trend.json", run_id, results)
    _write_raw(out_dir / "raw_results.json", run_id, results)


def _write_parity_matrix(path: Path, results: list[ScenarioRunResult]) -> None:
    scenarios = sorted({(r.scenario_id, r.category) for r in results})
    roles = sorted({r.candidate.role for r in results})
    score_by_key = {(r.scenario_id, r.candidate.role): r.score.score for r in results}
    pass_by_key = {(r.scenario_id, r.candidate.role): r.score.passed for r in results}

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["scenario_id", "category", *roles])
        for scenario_id, category in scenarios:
            row = [scenario_id, category]
            for role in roles:
                score = score_by_key.get((scenario_id, role))
                if score is None:
                    row.append("")
                else:
                    suffix = "" if pass_by_key.get((scenario_id, role), False) else " FAIL"
                    row.append(f"{score:.4f}{suffix}")
            writer.writerow(row)


def _write_failures(path: Path, results: list[ScenarioRunResult]) -> None:
    failed = [r for r in results if not r.score.passed]
    lines = ["# Per-model Failures", ""]
    if not failed:
        lines.append("All scenarios passed.")
    for role in sorted({r.candidate.role for r in failed}):
        role_failures = [r for r in failed if r.candidate.role == role]
        candidate = role_failures[0].candidate
        lines.extend(
            [f"## {role}", "", f"- model: `{candidate.model}`", f"- tier: `{candidate.tier}`", ""]
        )
        for item in role_failures:
            lines.append(
                f"- `{item.scenario_id}` ({item.category}): "
                f"score={item.score.score:.4f}; {item.score.reason}"
            )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_trend(path: Path, run_id: str, results: list[ScenarioRunResult]) -> None:
    payload = {
        "run_id": run_id,
        "models": {},
        "tiers": {},
    }
    for item in results:
        role = item.candidate.role
        tier = item.candidate.tier
        payload["models"].setdefault(role, {"model": item.candidate.model, "scores": {}})
        payload["models"][role]["scores"][item.scenario_id] = {
            "score": item.score.score,
            "passed": item.score.passed,
            "reason": item.score.reason,
        }
        payload["tiers"].setdefault(tier, []).append(item.score.score)
    for tier, scores in list(payload["tiers"].items()):
        payload["tiers"][tier] = {
            "average": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "count": len(scores),
        }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_raw(path: Path, run_id: str, results: list[ScenarioRunResult]) -> None:
    payload = {
        "run_id": run_id,
        "results": [
            {
                "scenario_id": r.scenario_id,
                "category": r.category,
                "role": r.candidate.role,
                "model": r.candidate.model,
                "tier": r.candidate.tier,
                "score": r.score.score,
                "passed": r.score.passed,
                "reason": r.score.reason,
                "similarity": r.score.similarity,
                "threshold": r.score.threshold,
                "response": r.response.text,
                "tools_used": r.response.tools_used,
                "latency_ms": r.response.latency_ms,
                "raw": r.response.raw,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _response_from_payload(
    payload: dict[str, Any], *, latency_ms: int | None = None
) -> ModelResponse:
    text = str(payload.get("reply") or payload.get("response") or payload.get("text") or "")
    tools_used = payload.get("tools_used") or []
    if not isinstance(tools_used, list):
        tools_used = [str(tools_used)]
    tool_outputs = payload.get("tool_outputs") or []
    if not isinstance(tool_outputs, list):
        tool_outputs = [str(tool_outputs)]
    return ModelResponse(
        text=text,
        model=str(payload.get("model") or "unknown"),
        raw=payload,
        tools_used=[str(t) for t in tools_used],
        tool_outputs=[str(t) for t in tool_outputs],
        latency_ms=latency_ms,
    )


def _infer_tier(model: str, cfg: dict[str, Any]) -> str:
    explicit = cfg.get("capability_tier") or cfg.get("prompt_tier")
    if explicit:
        return str(explicit)
    m = model.casefold()
    if any(token in m for token in ("phi", "3b", "4b", "e4b")):
        return "small"
    if any(token in m for token in ("70b", "72b", "405b", "mixtral", "deepseek")):
        return "strong_open"
    if any(token in m for token in ("7b", "8b", "12b", "14b", "mistral-small", "gemma")):
        return "mid_open"
    if any(token in m for token in ("claude", "gpt-4", "gpt-5", "gemini", "mistral-large")):
        return "frontier"
    return "frontier"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Synapse golden model parity scenarios.")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--models", default="all", help="Comma-separated role names, or 'all'.")
    parser.add_argument("--dedupe-models", action="store_true")
    parser.add_argument("--transport", choices=["http", "inprocess"], default="http")
    parser.add_argument(
        "--base-url", default=os.environ.get("SYNAPSE_PARITY_BASE_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--target", default="the_creator")
    parser.add_argument("--api-key", default=os.environ.get("SYNAPSE_GATEWAY_TOKEN"))
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--no-embeddings", action="store_true")
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    roles = (
        None
        if args.models == "all"
        else {item.strip() for item in args.models.split(",") if item.strip()}
    )
    scenarios = load_scenarios(args.scenarios)
    candidates = load_model_candidates(include_roles=roles, dedupe_models=args.dedupe_models)
    if not candidates:
        raise SystemExit("No model candidates found in synapse.json model_mappings")

    client: ParityClient
    if args.transport == "http":
        client = HttpParityClient(
            base_url=args.base_url,
            target=args.target,
            api_key=args.api_key,
        )
    else:
        client = InProcessParityClient(target=args.target)

    backend = None if args.no_embeddings else build_similarity_backend()
    result = await run_parity(
        scenarios=scenarios,
        candidates=candidates,
        client=client,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        similarity_backend=backend,
        fail_fast=args.fail_fast,
    )
    print(f"run_id={result.run_id}")
    print(f"output_dir={result.output_dir}")
    print(f"passed={result.passed}")
    return 0 if result.passed else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
