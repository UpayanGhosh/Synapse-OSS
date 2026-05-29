"""Golden behavior parity testing for Synapse model mappings."""

from sci_fi_dashboard.model_parity.scoring_engine import (
    ModelResponse,
    ScoreResult,
    score_response,
)

__all__ = [
    "ModelCandidate",
    "ModelResponse",
    "ParityRunResult",
    "Scenario",
    "ScoreResult",
    "load_model_candidates",
    "load_scenarios",
    "run_parity",
    "score_response",
]

_RUNNER_EXPORTS = {
    "ModelCandidate",
    "ParityRunResult",
    "Scenario",
    "load_model_candidates",
    "load_scenarios",
    "run_parity",
}


def __getattr__(name: str):
    if name in _RUNNER_EXPORTS:
        from sci_fi_dashboard.model_parity import test_runner

        return getattr(test_runner, name)
    raise AttributeError(name)
