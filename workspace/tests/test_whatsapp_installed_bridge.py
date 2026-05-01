from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_install_home_bridge_dir_honors_synapse_home(tmp_path, monkeypatch):
    from cli.install_home import baileys_bridge_dir

    home = tmp_path / "home"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    assert baileys_bridge_dir() == home.resolve() / "bridges" / "baileys"


def test_whatsapp_runtime_bridge_dir_is_product_home(tmp_path, monkeypatch):
    from sci_fi_dashboard.channels import whatsapp

    home = tmp_path / "home"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    bridge_dir = whatsapp.resolve_bridge_dir()

    assert bridge_dir == home.resolve() / "bridges" / "baileys"
    assert "baileys-bridge" not in bridge_dir.parts


def test_onboard_resolves_whatsapp_bridge_from_product_home(tmp_path, monkeypatch):
    from cli.onboard import _resolve_whatsapp_bridge_dir

    home = tmp_path / "home"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    assert _resolve_whatsapp_bridge_dir() == home.resolve() / "bridges" / "baileys"


def test_whatsapp_runtime_auth_state_lives_under_state(tmp_path, monkeypatch):
    from sci_fi_dashboard.channels import whatsapp

    home = tmp_path / "home"
    monkeypatch.setenv("SYNAPSE_HOME", str(home))

    auth_dir = whatsapp.resolve_auth_state_dir()

    assert auth_dir == home.resolve() / "state" / "whatsapp" / "auth_state"
    assert "baileys-bridge" not in str(auth_dir)


@pytest.mark.asyncio
async def test_whatsapp_runtime_requires_node_20(monkeypatch):
    from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel

    monkeypatch.setattr("shutil.which", lambda name: "node.exe" if name == "node" else None)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="v18.19.0\n", stderr="", returncode=0),
    )

    with pytest.raises(RuntimeError, match=r"Node.js 20\+ is required"):
        await WhatsAppChannel._validate_nodejs()
