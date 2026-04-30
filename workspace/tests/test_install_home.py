from __future__ import annotations

from pathlib import Path


def test_install_home_creates_product_tree(tmp_path, monkeypatch):
    from cli.install_home import ensure_product_home

    home = tmp_path / ".synapse"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    result = ensure_product_home()

    assert result["data_root"] == str(home.resolve())
    for rel in [
        ".venv",
        "bin",
        "runtime",
        "workspace",
        "logs",
        "state",
        "bridges",
        "bridges/baileys",
        "skills",
    ]:
        assert (home / rel).is_dir(), rel

    assert (home / "workspace" / "BOOTSTRAP.md").exists()
    assert (home / "bin" / "synapse-gateway.bat").exists()
    assert (home / "bin" / "synapse-gateway.sh").exists()
    assert (home / "bridges" / "baileys" / "index.js").exists()
    assert (home / "bridges" / "baileys" / "package.json").exists()
    assert not (home / "bridges" / "baileys" / "node_modules").exists()


def test_install_home_preserves_user_workspace_files(tmp_path, monkeypatch):
    from cli.install_home import ensure_product_home

    home = tmp_path / ".synapse"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    ensure_product_home()
    user_file = home / "workspace" / "USER.md"
    user_file.write_text("custom user profile\n", encoding="utf-8")

    ensure_product_home()

    assert user_file.read_text(encoding="utf-8") == "custom user profile\n"


def test_install_home_repairs_managed_launchers(tmp_path, monkeypatch):
    from cli.install_home import ensure_product_home

    home = tmp_path / ".synapse"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    ensure_product_home()
    launcher = home / "bin" / "synapse-gateway.bat"
    launcher.write_text("stale dev launcher --app-dir workspace\n", encoding="utf-8")

    ensure_product_home()

    repaired = launcher.read_text(encoding="utf-8")
    assert "uvicorn sci_fi_dashboard.api_gateway:app" in repaired
    assert "--host 127.0.0.1" in repaired
    assert "0.0.0.0" not in repaired
    assert "--app-dir" not in repaired
    assert "workspace\\synapse_cli.py" not in repaired


def test_install_home_repairs_managed_bridge_assets(tmp_path, monkeypatch):
    from cli.install_home import ensure_product_home

    home = tmp_path / ".synapse"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    ensure_product_home()
    bridge_index = home / "bridges" / "baileys" / "index.js"
    bridge_index.write_text("stale bridge\n", encoding="utf-8")

    ensure_product_home()

    repaired = bridge_index.read_text(encoding="utf-8")
    assert "Baileys WhatsApp bridge microservice" in repaired


def test_install_home_cli_command_registered():
    from typer.testing import CliRunner

    from synapse_cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "install-home" in result.output
