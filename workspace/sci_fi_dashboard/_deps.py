"""Shared singleton registry for the Antigravity Gateway."""

import logging
import os
import sys
import uuid
from pathlib import Path

from rich import print

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup (mirrors api_gateway.py lines 39-43)
# ---------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)
if WORKSPACE_ROOT not in sys.path:
    sys.path.append(WORKSPACE_ROOT)

# ---------------------------------------------------------------------------
# Core module imports
# ---------------------------------------------------------------------------
from sci_fi_dashboard.conflict_resolver import ConflictManager  # noqa: E402
from sci_fi_dashboard.dual_cognition import (  # noqa: E402
    CognitiveMerge,
    DualCognitionEngine,
)
from sci_fi_dashboard.emotional_trajectory import EmotionalTrajectory  # noqa: E402
from sci_fi_dashboard.memory_engine import MemoryEngine  # noqa: E402
from sci_fi_dashboard.retriever import (  # noqa: E402
    get_db_stats,
    query_memories,
)
from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator  # noqa: E402
from sci_fi_dashboard.smart_entity import EntityGate  # noqa: E402
from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402
from sci_fi_dashboard.toxic_scorer_lazy import LazyToxicScorer  # noqa: E402

# ---------------------------------------------------------------------------
# Phase 3: Tool Execution Loop (optional)
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.tool_registry import (  # noqa: E402
        ToolRegistry,
        ToolContext,
        ToolResult,
        SynapseTool,
        register_builtin_tools,
    )

    _TOOL_REGISTRY_AVAILABLE = True
except ImportError:
    _TOOL_REGISTRY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Phase 4: Tool Safety Pipeline (optional)
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.tool_safety import (  # noqa: E402
        apply_tool_policy_pipeline,
        build_policy_steps,
        ToolHookRunner,
        ToolLoopDetector,
        ToolAuditLogger,
    )

    _TOOL_SAFETY_AVAILABLE = True
except ImportError:
    _TOOL_SAFETY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Phase 5: User-facing Tool Features (optional)
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.tool_features import (  # noqa: E402
        format_tool_footer,
        get_model_override,
        parse_command_shortcut,
    )

    _TOOL_FEATURES_AVAILABLE = True
except ImportError:
    _TOOL_FEATURES_AVAILABLE = False

# ---------------------------------------------------------------------------
# Tool execution loop constants
# ---------------------------------------------------------------------------
MAX_TOOL_ROUNDS = 5
TOOL_RESULT_MAX_CHARS = 4000
MAX_TOTAL_TOOL_RESULT_CHARS = 20_000

_tool_logger = logging.getLogger(__name__ + ".tools")

# ---------------------------------------------------------------------------
# Singletons (Optimized v3)
# ---------------------------------------------------------------------------
tool_registry: "ToolRegistry | None" = None  # initialized in lifespan if available
hook_runner: "ToolHookRunner | None" = None
audit_logger: "ToolAuditLogger | None" = None
brain = SQLiteGraph()
gate = EntityGate(entities_file="entities.json")
conflicts = ConflictManager(conflicts_file="conflicts.json")
toxic_scorer = LazyToxicScorer(idle_timeout=30.0)
emotional_trajectory = EmotionalTrajectory()
memory_engine = MemoryEngine(graph_store=brain, keyword_processor=gate)
dual_cognition = DualCognitionEngine(
    memory_engine=memory_engine,
    graph=brain,
    toxic_scorer=toxic_scorer,
    emotional_trajectory=emotional_trajectory,
)

# ---------------------------------------------------------------------------
# Async Gateway Components
# ---------------------------------------------------------------------------
from channels.base import ChannelMessage  # noqa: E402
from channels.registry import ChannelRegistry  # noqa: E402
from channels.stub import StubChannel  # noqa: E402
from channels.whatsapp import WhatsAppChannel  # noqa: E402
from gateway.dedup import MessageDeduplicator  # noqa: E402
from gateway.flood import FloodGate  # noqa: E402
from gateway.queue import MessageTask, TaskQueue  # noqa: E402
from gateway.worker import MessageWorker  # noqa: E402

task_queue = TaskQueue(max_size=100)
dedup = MessageDeduplicator(window_seconds=300)
flood = FloodGate(batch_window_seconds=3.0)

# Channel registry — all adapters register here; lifespan calls start_all()
channel_registry = ChannelRegistry()
# Phase 4: Real WhatsApp bridge via Baileys Node.js microservice (WA-02)
channel_registry.register(
    WhatsAppChannel(
        bridge_port=int(os.environ.get("BRIDGE_PORT", "5010")),
        python_webhook_url=os.environ.get(
            "PYTHON_WEBHOOK_URL",
            "http://127.0.0.1:8000/channels/whatsapp/webhook",
        ),
    )
)
channel_registry.register(StubChannel(channel_id="stub"))  # test/demo channel

# ---------------------------------------------------------------------------
# Sentinel (File Governance)
# ---------------------------------------------------------------------------
from sbs.sentinel.tools import init_sentinel  # noqa: E402

init_sentinel(project_root=Path(__file__).parent)

# ---------------------------------------------------------------------------
# SBS Orchestrator (Phase 1)
# ---------------------------------------------------------------------------
from synapse_config import SynapseConfig as _SbsConfig  # noqa: E402

SBS_DATA_DIR = str(_SbsConfig.load().sbs_dir)
os.makedirs(SBS_DATA_DIR, exist_ok=True)


def _load_personas_config() -> dict:
    """Load persona definitions from workspace/personas.yaml, with a built-in fallback."""
    cfg_path = Path(WORKSPACE_ROOT) / "personas.yaml"
    if cfg_path.exists():
        try:
            import yaml

            with open(cfg_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and "personas" in data:
                return data
        except Exception as exc:
            print(f"[WARN] Could not load personas.yaml: {exc}. Using built-in defaults.")
    # Fallback: two default personas
    return {
        "personas": [
            {
                "id": "the_creator",
                "display_name": "Primary User",
                "description": "Chat as Synapse -> primary user (Bro Mode)",
                "whatsapp_phones": [],
                "whatsapp_keywords": [],
            },
            {
                "id": "the_partner",
                "display_name": "Partner",
                "description": "Chat as Synapse -> partner (Caring PA Mode)",
                "whatsapp_phones": [],
                "whatsapp_keywords": [],
            },
        ],
        "default_persona": "the_creator",
    }


PERSONAS_CONFIG = _load_personas_config()
sbs_registry: dict[str, SBSOrchestrator] = {
    p["id"]: SBSOrchestrator(os.path.join(SBS_DATA_DIR, p["id"]))
    for p in PERSONAS_CONFIG["personas"]
}


def _resolve_target(raw_target: str) -> str:
    """Map a raw chat_id / phone number / keyword to a persona ID."""
    t = raw_target.lower()
    for p in PERSONAS_CONFIG["personas"]:
        if any(phone in t for phone in p.get("whatsapp_phones", [])):
            return p["id"]
        if any(kw in t for kw in p.get("whatsapp_keywords", [])):
            return p["id"]
    return PERSONAS_CONFIG.get("default_persona", "the_creator")


def get_sbs_for_target(target: str) -> SBSOrchestrator:
    return sbs_registry.get(target, sbs_registry[PERSONAS_CONFIG["default_persona"]])


# ---------------------------------------------------------------------------
# Environment validation + SynapseConfig + LLM Router
# ---------------------------------------------------------------------------
from utils.env_loader import load_env_file  # noqa: E402

load_env_file(anchor=Path(__file__))
# NOTE: validate_env() is NOT called here — it lives in api_gateway.py and
# references module-level helpers (_port_open, SynapseConfig) defined there.
# The gateway itself calls validate_env() before creating the router.

from synapse_config import SynapseConfig  # noqa: E402

from sci_fi_dashboard.llm_router import LLMResult, SynapseLLMRouter  # noqa: E402

_synapse_cfg = SynapseConfig.load()
synapse_llm_router = SynapseLLMRouter(_synapse_cfg)

# Module-level proactive engine reference — set in lifespan after engine starts
_proactive_engine = None
