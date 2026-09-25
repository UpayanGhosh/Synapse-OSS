"""The real SBS accessor must never reuse a learned profile across owners."""

from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def _production_accessor(tmp_root: Path):
    source = Path(__file__).resolve().parents[2] / "workspace" / "sci_fi_dashboard" / "_deps.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    node = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "get_sbs_for_target"
    )
    class FakeSBS:
        def __init__(self, data_dir, *, workspace_dir=None):
            self.data_dir = Path(data_dir)
            self.workspace_dir = Path(workspace_dir) if workspace_dir is not None else tmp_root / "shared"

    namespace = {
        "SBSOrchestrator": FakeSBS,
        "SBS_DATA_DIR": str(tmp_root / "global"),
        "PERSONAS_CONFIG": {"default_persona": "the_creator"},
        "sbs_registry": {"the_creator": FakeSBS(tmp_root / "global" / "the_creator")},
        "Path": Path,
        "hashlib": hashlib,
        "_synapse_cfg": SimpleNamespace(data_root=tmp_root),
        "_scoped_sbs_registry": {},
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["get_sbs_for_target"], namespace["sbs_registry"]


def test_sbs_accessor_uses_private_owner_data_and_workspace():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "sbs-scope" / uuid4().hex
    root.mkdir(parents=True)
    get_sbs, registry = _production_accessor(root)

    def scoped(person_id):
        kwargs = {"person_id": person_id} if "person_id" in inspect.signature(get_sbs).parameters else {}
        return get_sbs("the_creator", **kwargs)

    a = scoped("whatsapp:alice")
    b = scoped("whatsapp:bob")
    again = scoped("whatsapp:alice")

    assert a is again
    assert a is not b
    assert a is not registry["the_creator"]
    assert a.data_dir != b.data_dir
    assert a.workspace_dir != b.workspace_dir
    assert a.workspace_dir != registry["the_creator"].workspace_dir
    assert root in a.data_dir.parents
    assert root in a.workspace_dir.parents
