"""Tests for optional channel registration policy."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import sci_fi_dashboard


def _fresh_channel_setup(monkeypatch, fake_deps, telegram_cls=None, slack_cls=None):
    original_deps = sys.modules.get("sci_fi_dashboard._deps")
    original_module = sys.modules.pop("sci_fi_dashboard.channel_setup", None)
    original_channels = sys.modules.get("channels")
    original_slack = sys.modules.get("channels.slack")
    original_pkg_telegram = sys.modules.get("sci_fi_dashboard.channels.telegram")
    original_pkg_slack = sys.modules.get("sci_fi_dashboard.channels.slack")

    monkeypatch.setitem(sys.modules, "sci_fi_dashboard._deps", fake_deps)
    monkeypatch.setattr(sci_fi_dashboard, "_deps", fake_deps, raising=False)
    sys.modules.pop("channels", None)
    sys.modules.pop("channels.telegram", None)
    sys.modules.pop("channels.slack", None)
    if telegram_cls is not None:
        telegram_module = types.ModuleType("sci_fi_dashboard.channels.telegram")
        telegram_module.TelegramChannel = telegram_cls
        monkeypatch.setitem(sys.modules, "sci_fi_dashboard.channels.telegram", telegram_module)
    if slack_cls is not None:
        slack_module = types.ModuleType("sci_fi_dashboard.channels.slack")
        slack_module.SlackChannel = slack_cls
        monkeypatch.setitem(sys.modules, "sci_fi_dashboard.channels.slack", slack_module)

    module = importlib.import_module("sci_fi_dashboard.channel_setup")

    def restore():
        sys.modules.pop("sci_fi_dashboard.channel_setup", None)
        if original_module is not None:
            sys.modules["sci_fi_dashboard.channel_setup"] = original_module
        if original_deps is not None:
            sys.modules["sci_fi_dashboard._deps"] = original_deps
        else:
            sys.modules.pop("sci_fi_dashboard._deps", None)
        if original_channels is not None:
            sys.modules["channels"] = original_channels
        else:
            sys.modules.pop("channels", None)
        if original_slack is not None:
            sys.modules["channels.slack"] = original_slack
        else:
            sys.modules.pop("channels.slack", None)
        if original_pkg_telegram is not None:
            sys.modules["sci_fi_dashboard.channels.telegram"] = original_pkg_telegram
        else:
            sys.modules.pop("sci_fi_dashboard.channels.telegram", None)
        if original_pkg_slack is not None:
            sys.modules["sci_fi_dashboard.channels.slack"] = original_pkg_slack
        else:
            sys.modules.pop("sci_fi_dashboard.channels.slack", None)

    return module, restore


def _fake_deps(slack_config: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _synapse_cfg=types.SimpleNamespace(
            channels={
                "telegram": {},
                "discord": {},
                "slack": slack_config,
            }
        ),
        channel_registry=MagicMock(),
        dedup=MagicMock(),
        flood=MagicMock(),
    )


def test_slack_tokens_do_not_register_without_explicit_enabled(monkeypatch):
    """Valid-looking Slack tokens must not start Socket Mode unless enabled=true."""

    class SlackChannel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @property
        def channel_id(self):
            return "slack"

    fake_deps = _fake_deps(
        {
            "bot_token": "xoxb-valid-looking",
            "app_token": "xapp-valid-looking",
        }
    )
    module, restore = _fresh_channel_setup(monkeypatch, fake_deps, SlackChannel)
    try:
        module.register_optional_channels()
    finally:
        restore()

    fake_deps.channel_registry.register.assert_not_called()


def test_telegram_registers_from_package_module_without_top_level_channels(monkeypatch):
    """Installed Synapse must not depend on a repo-root/top-level channels package."""

    class TelegramChannel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @property
        def channel_id(self):
            return "telegram"

    fake_deps = _fake_deps({})
    fake_deps._synapse_cfg.channels["telegram"] = {"token": "123456:fake-token"}
    module, restore = _fresh_channel_setup(monkeypatch, fake_deps, telegram_cls=TelegramChannel)
    try:
        module.register_optional_channels()
    finally:
        restore()

    fake_deps.channel_registry.register.assert_called_once()
    registered = fake_deps.channel_registry.register.call_args.args[0]
    assert registered.channel_id == "telegram"


def test_slack_registers_when_explicitly_enabled(monkeypatch):
    """Slack still registers when the user opts in and provides both tokens."""

    class SlackChannel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @property
        def channel_id(self):
            return "slack"

    fake_deps = _fake_deps(
        {
            "enabled": True,
            "bot_token": "xoxb-valid-looking",
            "app_token": "xapp-valid-looking",
        }
    )
    module, restore = _fresh_channel_setup(monkeypatch, fake_deps, SlackChannel)
    try:
        module.register_optional_channels()
    finally:
        restore()

    fake_deps.channel_registry.register.assert_called_once()
