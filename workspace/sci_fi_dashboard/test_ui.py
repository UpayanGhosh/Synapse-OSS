from state import DashboardState
from narrative import translate_log_to_narrative
from ui_components import UIComponents
from rich.console import Console

def test_render():
    state = DashboardState()
    state.add_activity("Test Activity", "Sub text")
    state.add_log("INFO", "Test log message")
    
    console = Console(width=100)
    
    # Test individual components
    print("Testing Header...")
    header = UIComponents.create_header(state)
    console.print(header)
    
    print("\nTesting Activity Stream...")
    stream = UIComponents.create_activity_stream(state)
    console.print(stream)
    
    print("\nTesting Sidebar...")
    sidebar = UIComponents.create_sidebar(state)
    console.print(sidebar)
    
    print("\nTesting System Log...")
    log = UIComponents.create_system_log(state)
    console.print(log)

if __name__ == "__main__":
    test_render()
