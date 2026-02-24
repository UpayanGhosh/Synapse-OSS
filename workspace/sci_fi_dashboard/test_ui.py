import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from state import DashboardState
from narrative import translate_log_to_narrative
from ui_components import UIComponents
from rich.console import Console


def test_header_renders():
    """Dashboard header should render without errors."""
    state = DashboardState()
    console = Console(width=100)
    header = UIComponents.create_header(state)
    assert header is not None


def test_activity_stream_renders():
    """Activity stream should render with added activities."""
    state = DashboardState()
    state.add_activity("Test Activity", "Sub text")
    console = Console(width=100)
    stream = UIComponents.create_activity_stream(state)
    assert stream is not None


def test_sidebar_renders():
    """Sidebar should render without errors."""
    state = DashboardState()
    console = Console(width=100)
    sidebar = UIComponents.create_sidebar(state)
    assert sidebar is not None


def test_system_log_renders():
    """System log should render with log entries."""
    state = DashboardState()
    state.add_log("INFO", "Test log message")
    console = Console(width=100)
    log = UIComponents.create_system_log(state)
    assert log is not None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
