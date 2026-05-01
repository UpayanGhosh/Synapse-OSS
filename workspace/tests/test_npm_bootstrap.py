import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_JSON = REPO_ROOT / "package.json"
SYNAPSE_BIN = REPO_ROOT / "bin" / "synapse.js"


def test_package_declares_synapse_bin():
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

    assert package["name"] == "synapse-oss"
    assert package["version"] == "3.0.0"
    assert package["bin"] == {"synapse": "bin/synapse.js"}
    assert "workspace/*.py" in package["files"]
    assert "workspace/cli/**/*.py" in package["files"]
    assert "workspace/sci_fi_dashboard/**/*.py" in package["files"]
    assert "workspace/sci_fi_dashboard/synapse_data/**/*" not in package["files"]
    for forbidden in ("workspace/tests", "workspace/state", "workspace/sci_fi_dashboard/synapse_data"):
        assert all(forbidden not in pattern for pattern in package["files"])
    assert "pyproject.toml" in package["files"]
    assert "setup.py" in package["files"]
    assert package["engines"]["node"] == ">=20"


def test_synapse_bin_exists_and_lists_supported_commands():
    content = SYNAPSE_BIN.read_text(encoding="utf-8")

    assert content.startswith("#!/usr/bin/env node")
    for command in ("install", "onboard", "start", "stop", "doctor", "chat"):
        assert command in content


def test_synapse_bin_resolves_product_home_not_repo_workspace():
    content = SYNAPSE_BIN.read_text(encoding="utf-8")

    assert "SYNAPSE_HOME" in content
    assert ".synapse" in content
    assert "USERPROFILE" in content
    assert "process.env.HOME" in content
    assert "workspace" not in content


def test_synapse_install_bootstraps_uv_python_and_product_home():
    content = SYNAPSE_BIN.read_text(encoding="utf-8")

    assert "https://astral.sh/uv/install.ps1" in content
    assert "https://astral.sh/uv/install.sh" in content
    assert "UV_INSTALL_DIR" in content
    assert "UV_NO_MODIFY_PATH" in content
    assert "UV_PYTHON_BIN_DIR" in content
    assert "UV_PYTHON_CACHE_DIR" in content
    assert "UV_TOOL_DIR" in content
    assert "UV_TOOL_BIN_DIR" in content
    assert 'const runtimeTmp = path.join(home, "runtime", "tmp")' in content
    assert "TMPDIR: runtimeTmp" in content
    assert "TEMP: runtimeTmp" in content
    assert "TMP: runtimeTmp" in content
    assert "PLAYWRIGHT_BROWSERS_PATH" in content
    assert '"runtime/tmp"' in content
    assert '"runtime/python-bin"' in content
    assert "uv venv" not in content
    assert '"python"' in content
    assert '"install"' in content
    assert "pip" in content
    assert "install-home" in content
    assert "playwright" in content
    assert "npm" in content
    assert "runNpm" in content
    assert "cmd.exe" in content
    assert "Install helper not present yet" not in content


def test_synapse_install_is_idempotent_with_existing_venv():
    content = SYNAPSE_BIN.read_text(encoding="utf-8")
    ensure_dirs_block = content.split("function ensureDirs(home) {", 1)[1].split(
        "function runtimeEnv(home) {", 1
    )[0]

    assert '".venv"' not in ensure_dirs_block
    assert "fs.existsSync(pythonPath(home))" in content
    assert '"--clear"' in content


def test_npm_start_requires_installed_python_and_loopback_default():
    content = SYNAPSE_BIN.read_text(encoding="utf-8")

    assert "function requirePython" in content
    assert "Run: synapse install" in content
    assert '"127.0.0.1"' in content
    assert "SYNAPSE_GATEWAY_PORT" in content
    assert '"8000"' in content
    assert '"0.0.0.0"' not in content


def test_npm_stop_kills_gateway_process_tree_on_windows():
    content = SYNAPSE_BIN.read_text(encoding="utf-8")

    assert "function stopProcessTree" in content
    assert "taskkill" in content
    assert '"/T"' in content
    assert '"/PID"' in content
    assert "stopProcessTree(pid)" in content


def test_npm_package_manifest_excludes_tests_and_state():
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    include_patterns = "\n".join(package["files"])

    for forbidden in ("workspace/tests", "pytest-cache-files", "synapse_data", "auth_state", "node_modules"):
        assert forbidden not in include_patterns


def test_npm_bootstrap_avoids_forbidden_legacy_install_paths():
    package_content = PACKAGE_JSON.read_text(encoding="utf-8")
    bin_content = SYNAPSE_BIN.read_text(encoding="utf-8")
    combined = package_content + "\n" + bin_content

    for forbidden in ("pip install -e", "workspace/synapse_cli.py", "--app-dir"):
        assert forbidden not in combined
