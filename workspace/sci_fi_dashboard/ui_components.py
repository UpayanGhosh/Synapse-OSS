from rich.panel import Panel
from rich import box
from rich.table import Table
from rich.text import Text
from rich.progress import ProgressBar, Progress, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Group
from rich.align import Align
from state import DashboardState

class UIComponents:
    @staticmethod
    def create_header(state: DashboardState) -> Panel:
        status_color = "green" if "OPERATIONAL" in state.status else "red"
        title = Text.assemble(
            (" ⚡ ", "yellow"),
            (state.system_name, "cyan bold"),
            ("  │  ", "white"),
            (f"STATUS: ", "white"),
            (state.status, status_color + " bold"),
            ("  │  ", "white"),
            (f"⟨ {state.get_uptime_str()} ⟩", "magenta")
        )
        
        # Determine battery/health color
        health_color = "green" if state.network_health > 80 else "yellow" if state.network_health > 50 else "red"
        
        subtitle = Text.assemble(
            (f"Tasks: {state.active_tasks_count}", "blue"),
            ("  │  ", "white"),
            (f"CPU: {state.cpu_load}%", "cyan"),
            ("  │  ", "white"),
            (f"MEM: {state.memory_usage}", "cyan"),
            ("  │  ", "white"),
            (f"Network: ", "white"),
            ("█" * (state.network_health // 10), health_color),
            ("░" * (10 - state.network_health // 10), "bright_black"),
            (f" {state.network_health}%", health_color)
        )
        
        header_content = Group(
            Align.center(title),
            Align.center(subtitle)
        )
        
        return Panel(header_content, border_style="bright_blue", box=box.ROUNDED)

    @staticmethod
    def create_activity_stream(state: DashboardState) -> Panel:
        table = Table.grid(expand=True)
        table.add_column(width=8)
        table.add_column()

        for activity in state.activities:
            table.add_row(
                Text(f"⟨{activity.time_str}⟩", style="bright_black"),
                Text(activity.narrative, style="cyan")
            )
            if activity.sub_text:
                table.add_row(
                    "",
                    Text(f"└─ {activity.sub_text}", style="bright_black italic")
                )
            table.add_row("", "") # Spacer

        return Panel(table, title="[bold white]LIVE ACTIVITY STREAM[/]", border_style="bright_blue", box=box.SQUARE)

    @staticmethod
    def create_sidebar(state: DashboardState) -> Panel:
        content = []
        
        # Quota Watchdog
        content.append(Text("┌─ QUOTA WATCHDOG ──────┐", style="bright_red"))
        
        # Token usage calculation
        total_tokens = state.total_tokens_in + state.total_tokens_out
        usage_pct = (total_tokens / state.context_limit) * 100
        
        usage_color = "green" if usage_pct < 50 else "yellow" if usage_pct < 80 else "red"
        
        content.append(Text.assemble(("  Tokens: ", "white"), (f"{total_tokens / 1000:.1f}k", usage_color), (" / ", "white"), (f"{state.context_limit / 1000:.0f}k", "cyan")))
        
        # Mini progress bar for quota
        done = int(min(10, usage_pct / 10))
        bar = "█" * done + "░" * (10 - done)
        content.append(Text(f"  [{bar}] {usage_pct:.1f}%", style=usage_color))
        
        content.append(Text.assemble(("  Sessions: ", "white"), (f"{state.active_sessions}", "cyan")))
        content.append(Text("└───────────────────────┘", style="bright_red"))
        content.append(Text(""))

        content.append(Text("┌─ ACTIVE PROCESSES ────┐", style="bright_blue"))
        
        for name, proc in state.processes.items():
            icon = "▶" if proc.status == "ACTIVE" else "⏸"
            color = "cyan" if proc.status == "ACTIVE" else "bright_black"
            content.append(Text(f"{icon} {name}", style=color))
            
            # Progress bar
            done = int(proc.progress / 10)
            bar = "█" * done + "░" * (10 - done)
            content.append(Text(f"   {bar} {proc.progress:.0f}%", style=color))
            content.append(Text(""))

        content.append(Text("└───────────────────────┘", style="bright_blue"))
        return Panel(Group(*content), title="[bold white]SYSTEM STATUS[/]", border_style="bright_blue", box=box.SQUARE)

    @staticmethod
    def create_system_log(state: DashboardState) -> Panel:
        log_text = Text()
        for log in state.logs:
            level_color = "green" if log.level == "INFO" else "yellow" if log.level == "WARNING" else "red"
            level_icon = "🟢" if log.level == "INFO" else "🟡" if log.level == "WARNING" else "🔴"
            
            log_text.append(f"{level_icon} {log.timestamp}  ", style="bright_black")
            log_text.append(f"{log.message}\n", style="white")

        return Panel(log_text, title="[bold white]SYSTEM LOG[/]", border_style="bright_blue", box=box.SQUARE)
