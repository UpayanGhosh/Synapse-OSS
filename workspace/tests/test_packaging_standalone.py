from __future__ import annotations

import re
import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _requirement_names(path: str) -> set[str]:
    names: set[str] = set()
    for raw_line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~;,\[]", line, maxsplit=1)[0].strip().lower()
        if name:
            names.add(name.replace("_", "-"))
    return names


def _dep_names(values: list[str]) -> set[str]:
    names: set[str] = set()
    for value in values:
        name = re.split(r"[<>=!~;,\[]", value, maxsplit=1)[0].strip().lower()
        names.add(name.replace("_", "-"))
    return names


def test_standalone_package_data_includes_runtime_assets() -> None:
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]
    sci_fi_data = set(package_data["sci_fi_dashboard"])

    expected_patterns = {
        "agent_workspace/*.md.template",
        "agent_workspace/INSTRUCTIONS.md",
        "agent_workspace/CORE.md",
        "agent_workspace/AGENTS.md",
        "entities.json",
        "skills/bundled/**/*",
        "sbs/feedback/*.yaml",
        "model_parity/*.yaml",
        "model_parity/*.yaml.example",
        "static/**/*",
        "runtime_assets/baileys-bridge/**/*",
    }

    assert expected_patterns <= sci_fi_data
    assert "synapse_data/**/*" not in sci_fi_data


def test_baileys_bridge_runtime_assets_are_bundled_without_state_or_tests() -> None:
    bridge = ROOT / "workspace" / "sci_fi_dashboard" / "runtime_assets" / "baileys-bridge"

    required_assets = {
        "index.js",
        "package.json",
        "package-lock.json",
        "lib/creds_queue.js",
        "lib/restore.js",
        "lib/send_payload.js",
    }

    for relative_path in required_assets:
        assert (bridge / relative_path).is_file(), relative_path

    forbidden_parts = {"node_modules", "auth_state", "media_cache", "test", "tests"}
    bundled_files = [path.relative_to(bridge).parts for path in bridge.rglob("*") if path.is_file()]
    assert bundled_files
    assert all(forbidden_parts.isdisjoint(parts) for parts in bundled_files)


def test_baileys_bridge_locks_safe_protobuf_resolution() -> None:
    bridge = ROOT / "workspace" / "sci_fi_dashboard" / "runtime_assets" / "baileys-bridge"
    package = json.loads((bridge / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((bridge / "package-lock.json").read_text(encoding="utf-8"))

    assert package["overrides"]["protobufjs"] == "7.5.5"
    for name, metadata in lock["packages"].items():
        if name.endswith("node_modules/protobufjs"):
            assert metadata["version"] >= "7.5.5", name


def test_wheel_discovery_excludes_dev_test_packages() -> None:
    setuptools_config = _pyproject()["tool"]["setuptools"]
    setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")

    assert setuptools_config["include-package-data"] is False
    assert "def find_package_modules" in setup_py
    assert 'item[0] == "sci_fi_dashboard"' in setup_py
    assert 'item[1].startswith("test_")' in setup_py

    package_find = setuptools_config["packages"]["find"]
    assert "tests" in package_find["exclude"]
    assert "tests.*" in package_find["exclude"]

    exclude_package_data = setuptools_config["exclude-package-data"]
    assert "test_*.py" in exclude_package_data["sci_fi_dashboard"]


def test_default_and_optional_dependencies_cover_runtime_requirement_drift() -> None:
    pyproject = _pyproject()["project"]
    default_deps = _dep_names(pyproject["dependencies"])
    optional_deps = set()
    for values in pyproject.get("optional-dependencies", {}).values():
        optional_deps.update(_dep_names(values))

    required_default = _requirement_names("requirements.txt") | _requirement_names(
        "requirements-channels.txt"
    )
    approved_optional = _requirement_names("requirements-optional.txt") | _requirement_names(
        "requirements-ml.txt"
    )

    missing_default = required_default - default_deps
    missing_optional = approved_optional - default_deps - optional_deps

    assert missing_default == set()
    assert missing_optional == set()
