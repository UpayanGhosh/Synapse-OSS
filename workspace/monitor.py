import time
import psutil
import os
import glob
import json
import re
import subprocess
from datetime import datetime
from rich.live import Live
from rich.table import Table
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.style import Style
from rich.align import Align
from rich.progress_bar import ProgressBar
from rich.columns import Columns

console = Console()

# Configuration
LOG_DIR = "/tmp/openclaw"
SESSIONS_FILE = "/path/to/openclaw/agents/main/sessions/sessions.json"

# ═══════════════════════════════════════════
#  Tool Label Map — Technical → Human Readable
# ═══════════════════════════════════════════

TOOL_LABELS = {
    # Core tools
    "message":          "✉️  SENDING MESSAGE",
    "send":             "✉️  SENDING MESSAGE",
    "reply":            "💬 COMPOSING REPLY",

    # Memory & DB tools
    "memory":           "🧠 QUERYING MEMORY DB",
    "query":            "🔍 SEARCHING MEMORIES",
    "add":              "📥 STORING NEW MEMORY",
    "read":             "📖 READING FILE",
    "write":            "📝 WRITING FILE",

    # Web & external
    "web_search":       "🌍 SEARCHING THE WEB",
    "browse":           "🌐 BROWSING URL",
    "fetch":            "📡 FETCHING DATA",

    # System tools
    "exec":             "💻 RUNNING COMMAND",
    "bash":             "💻 EXECUTING SHELL",
    "command":          "💻 EXECUTING COMMAND",
    "eval":             "⚙️  EVALUATING CODE",

    # Communication tools
    "himalaya":         "📧 MANAGING EMAIL",
    "gmail":            "📧 CHECKING GMAIL",
    "calendar":         "📅 CHECKING CALENDAR",
    "contacts":         "👥 SEARCHING CONTACTS",

    # Media & generation
    "image":            "🖼️  GENERATING IMAGE",
    "transcribe":       "🎙️ TRANSCRIBING AUDIO",
    "whisper":          "🎙️ TRANSCRIBING AUDIO",
    "summarize":        "📋 SUMMARIZING CONTENT",

    # File ops
    "nano-pdf":         "📄 EDITING PDF",
    "video-frames":     "🎬 EXTRACTING FRAMES",

    # Skills
    "weather":          "🌤️  CHECKING WEATHER",
    "github":           "🐙 GITHUB OPERATION",
    "things":           "✅ MANAGING TASKS",

    # WhatsApp
    "send-v2":          "✉️  SENDING WHATSAPP",
    "contacts-list":    "👥 LOOKING UP CONTACT",
}

# ═══════════════════════════════════════════


class BrainDashboard:
    def __init__(self):
        self.log_file = None
        self.file_handle = None
        self.activity_stream = ["🟢 SYSTEM INITIALIZED"]
        self.thinking_buffer = ""           # Current model reasoning
        self.current_action = "IDLE"        # Human-readable current action
        self.neural_activity = 0
        self.last_update = time.time()
        self.boot_time = psutil.boot_time()

        # API Usage
        self.total_tokens_limit = 1_048_576  # Context window
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens_used = 0
        self.model_name = "gemini-3-flash"

        # Session tracking
        self.messages_processed = 0
        self.tools_called = 0
        self.errors_count = 0
        self.last_response_time = "—"

        self.action_priority = 0
        self.action_expires = 0

        self.connect_log()

    def connect_log(self):
        try:
            log_files = glob.glob(os.path.join(LOG_DIR, "openclaw-*.log"))
            if log_files:
                new_file = max(log_files, key=os.path.getmtime)
                if new_file != self.log_file:
                    self.log_file = new_file
                    if self.file_handle:
                        self.file_handle.close()
                    self.file_handle = open(self.log_file, "r")
                    file_size = os.path.getsize(self.log_file)
                    self.file_handle.seek(max(0, file_size - 4096), 0)
                    if self.file_handle.tell() > 0:
                        self.file_handle.readline()
        except Exception:
            pass

    def get_tool_label(self, tool_name: str) -> str:
        """Map a tool name to a human-readable label."""
        t = tool_name.lower().strip()
        # Direct match
        if t in TOOL_LABELS:
            return TOOL_LABELS[t]
        # Partial match
        for key, label in TOOL_LABELS.items():
            if key in t:
                return label
        return f"🛠️  USING TOOL: {tool_name.upper()}"

    def extract_thinking(self, msg: str) -> str | None:
        """Extract model thinking/reasoning from log messages."""
        # Look for thinking blocks
        if "<think>" in msg:
            match = re.search(r'<think>(.*?)</think>', msg, re.DOTALL)
            if match:
                return match.group(1).strip()[:200]
        # Look for reasoning patterns in the message
        if "reasoning" in msg.lower() or "thinking" in msg.lower():
            return msg[:200]
        return None

    def set_action(self, text: str, priority: int = 0, duration: float = 0):
        """Sets the current action if priority allows or previous action expired."""
        now = time.time()
        # Update if:
        # 1. New priority is higher or equal to current
        # 2. Current action has expired
        if priority >= self.action_priority or now > self.action_expires:
            self.current_action = text
            self.action_priority = priority
            if duration > 0:
                self.action_expires = now + duration
            else:
                self.action_expires = 0

    def translate_event(self, subsystem: str, message) -> str | None:
        """Translates technical logs into human-readable brain events."""
        msg = str(message)

        # --- Model Thinking ---
        thinking = self.extract_thinking(msg)
        if thinking:
            self.thinking_buffer = thinking
            self.set_action("🧠 THINKING...", priority=2, duration=1.0)
            return None  # Don't spam the stream with thoughts

        # --- Tool Usage ---
        if "embedded run tool start" in msg:
            tool = msg.split("tool=")[1].split(" ")[0] if "tool=" in msg else "unknown"
            label = self.get_tool_label(tool)
            self.set_action(label, priority=3, duration=1.5)
            self.tools_called += 1
            return label

        if "embedded run tool end" in msg:
            # Extract duration
            dur = ""
            if "durationMs=" in msg:
                try:
                    dur_ms = int(msg.split("durationMs=")[1].split(" ")[0])
                    dur = f" ({dur_ms}ms)"
                except Exception:
                    pass
            # Low priority update, won't override active tool label if it's still sticky
            self.set_action(f"✅ TOOL DONE{dur}", priority=1, duration=0.5)
            return None

        # --- Agent Lifecycle ---
        if "embedded run prompt start" in msg:
            self.set_action("⚡ PROCESSING PROMPT", priority=2, duration=1.0)
            self.neural_activity = 80
            return "⚡ PROCESSING PROMPT"

        if "embedded run agent start" in msg:
            self.set_action("🧠 MODEL IS REASONING", priority=2, duration=1.0)
            self.neural_activity = 90
            return "🧠 MODEL IS REASONING"

        if "embedded run prompt end" in msg:
            dur = ""
            if "durationMs=" in msg:
                try:
                    dur_ms = int(msg.split("durationMs=")[1].split(" ")[0])
                    dur = f" ({dur_ms/1000:.1f}s)"
                    self.last_response_time = f"{dur_ms/1000:.1f}s"
                except Exception:
                    pass
            self.set_action(f"✨ RESPONSE READY{dur}", priority=2, duration=2.0)
            return f"✨ RESPONSE GENERATED{dur}"

        if "embedded run done" in msg:
            self.set_action("IDLE", priority=0)
            self.neural_activity = max(self.neural_activity - 40, 5)
            return None

        # --- Inbound Messages ---
        if "Inbound message" in msg or "inbound" in msg.lower():
            sender = "USER"
            if "->" in msg:
                sender = msg.split("->")[0].split("message")[1].strip()[:20]
            self.messages_processed += 1
            self.set_action("📨 RECEIVED MESSAGE", priority=3, duration=2.0)
            self.neural_activity = 100
            return f"📨 MESSAGE FROM {sender.upper()}"

        # --- WhatsApp ---
        if "auto-reply sent" in msg.lower() or "Sent chunk" in msg:
            to = ""
            if "to" in msg and "+" in msg:
                match = re.search(r'\+\d+', msg)
                if match:
                    to = f" → {match.group()}"
            self.set_action(f"✉️  SENT{to}", priority=2, duration=1.0)
            return f"✉️  WHATSAPP DELIVERED{to}"

        if "Auto-replied" in msg:
            return None  # Duplicate of above

        # --- Session ---
        if "session state" in msg:
            if "new=idle" in msg:
                self.set_action("IDLE", priority=0)
            elif "new=processing" in msg:
                self.set_action("⏳ PROCESSING...", priority=1)
            return None

        # --- Errors ---
        if "error" in msg.lower() or "failed" in msg.lower():
            self.errors_count += 1
            short = msg[:80]
            self.set_action("⚠️ ERROR", priority=4, duration=3.0)
            return f"⚠️ {short}"

        # --- Lane completion ---
        if "lane task done" in msg:
            return None

        return None

    def update_api_usage(self):
        """Read API usage from sessions.json."""
        try:
            if os.path.exists(SESSIONS_FILE):
                with open(SESSIONS_FILE, "r") as f:
                    data = json.load(f)
                for key, session in data.items():
                    if isinstance(session, dict) and "totalTokens" in session:
                        self.total_tokens_limit = session.get("totalTokens", 1_048_576)
                        self.input_tokens = session.get("inputTokens", 0)
                        self.output_tokens = session.get("outputTokens", 0)
                        self.total_tokens_used = self.input_tokens + self.output_tokens
                        self.model_name = session.get("model", "unknown")
                        break
        except Exception:
            pass

    def process_logs(self):
        if not self.file_handle:
            self.connect_log()
            return

        try:
            while True:
                line = self.file_handle.readline()
                if not line:
                    break
                try:
                    data = json.loads(line)

                    # Handle message field — can be string or dict
                    msg_part = data.get("1", "")
                    if isinstance(msg_part, dict):
                        # Auto-reply messages contain the actual text
                        text = msg_part.get("text", "")
                        if text:
                            msg_part = f"auto-reply sent: {text[:100]}"
                        else:
                            msg_part = str(msg_part)

                    raw_subsystem = data.get("0", "")
                    subsystem = "unknown"
                    if isinstance(raw_subsystem, str) and raw_subsystem.startswith("{"):
                        try:
                            sub_data = json.loads(raw_subsystem)
                            subsystem = sub_data.get("subsystem") or sub_data.get("module") or subsystem
                        except Exception:
                            pass

                    translated = self.translate_event(subsystem, msg_part)
                    if translated:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        self.activity_stream.insert(0, f"[{timestamp}] {translated}")
                        self.activity_stream = self.activity_stream[:15]
                        self.neural_activity = min(100, self.neural_activity + 20)
                        self.last_update = time.time()

                except Exception:
                    continue
        except Exception:
            pass

    def decay_activity(self):
        elapsed = time.time() - self.last_update
        if elapsed > 3 and self.neural_activity > 5:
            self.neural_activity = max(5, self.neural_activity - 3)
        if elapsed > 10:
            self.current_action = "IDLE"


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def generate_layout(m: BrainDashboard):
    m.process_logs()
    m.update_api_usage()
    m.decay_activity()

    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    uptime = str(datetime.now() - datetime.fromtimestamp(m.boot_time)).split('.')[0]
    now = datetime.now().strftime("%H:%M:%S")

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="top", size=8),
        Layout(name="middle", ratio=2),
        Layout(name="footer", size=4),
    )

    # Split middle into stream + git history
    layout["middle"].split_row(
        Layout(name="stream", ratio=2),
        Layout(name="git_history", ratio=1),
    )

    # === HEADER ===
    log_name = os.path.basename(m.log_file) if m.log_file else "No log"
    layout["header"].update(Align.center(
        Text(f"🧠 JARVIS CORTEX v4.0 │ {log_name} │ {now}", style="bold white on blue")
    ))

    # === TOP SECTION (API + Current Action) ===
    layout["top"].split_row(
        Layout(name="api_usage", ratio=2),
        Layout(name="action", ratio=1),
    )

    # --- API Usage Panel ---
    usage_pct = (m.total_tokens_used / m.total_tokens_limit * 100) if m.total_tokens_limit > 0 else 0
    usage_color = "green"
    if usage_pct > 80:
        usage_color = "red"
    elif usage_pct > 50:
        usage_color = "yellow"

    # Build usage bar manually
    bar_width = 35
    filled = int((usage_pct / 100) * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    usage_text = Text()
    usage_text.append(f"  Model: ", style="dim")
    usage_text.append(f"{m.model_name}\n", style="bold cyan")
    usage_text.append(f"  Context: ", style="dim")
    usage_text.append(f"[{bar}]", style=f"bold {usage_color}")
    usage_text.append(f" {usage_pct:.1f}%\n", style=f"bold {usage_color}")
    usage_text.append(f"  Input:  ", style="dim")
    usage_text.append(f"{format_tokens(m.input_tokens)}", style="bold green")
    usage_text.append(f"  │  Output: ", style="dim")
    usage_text.append(f"{format_tokens(m.output_tokens)}", style="bold magenta")
    usage_text.append(f"  │  Total: ", style="dim")
    usage_text.append(f"{format_tokens(m.total_tokens_used)}", style=f"bold {usage_color}")
    usage_text.append(f" / {format_tokens(m.total_tokens_limit)}\n", style="dim")

    layout["top"]["api_usage"].update(Panel(
        usage_text,
        title="📊 API USAGE",
        border_style=usage_color,
        padding=(0, 1),
    ))

    # --- Current Action Panel ---
    action = m.current_action
    action_style = "bold green"
    if "ERROR" in action or "⚠️" in action:
        action_style = "bold red"
    elif "THINKING" in action or "PROCESSING" in action:
        action_style = "bold yellow"
    elif "IDLE" in action:
        action_style = "dim"

    # Activity pulse
    pulse_width = 20
    pulse_filled = int((m.neural_activity / 100) * pulse_width)
    pulse_color = "green"
    if m.neural_activity > 80:
        pulse_color = "red"
    elif m.neural_activity > 40:
        pulse_color = "yellow"
    pulse_bar = "▓" * pulse_filled + "░" * (pulse_width - pulse_filled)

    action_text = Text()
    action_text.append(f"\n  {action}\n\n", style=action_style)
    action_text.append(f"  [{pulse_bar}] {m.neural_activity}%\n", style=f"bold {pulse_color}")

    layout["top"]["action"].update(Panel(
        action_text,
        title="⚡ NOW",
        border_style="cyan",
        padding=(0, 0),
    ))

    # === ACTIVITY STREAM ===
    stream_text = Text()
    for i, item in enumerate(m.activity_stream):
        style = "green" if i > 0 else "bold bright_green"
        if "⚠️" in item:
            style = "red"
        elif "✉️" in item:
            style = "cyan"
        elif "🧠" in item:
            style = "yellow"
        stream_text.append(item + "\n", style=style)

    layout["middle"]["stream"].update(Panel(
        stream_text,
        title="🌊 ACTIVITY LOG",
        border_style="green",
        padding=(0, 1),
    ))

    # === GIT HISTORY ===
    git_text = Text()
    try:
        result = subprocess.run(
            ["git", "log", "-5", "--all", "--format=%h|%s|%ar"],
            cwd="/path/to/openclaw/workspace",
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                parts = line.split("|", 2)
                if len(parts) >= 3:
                    h, msg, ago = parts
                    icon = "🤖" if msg.startswith("[auto]") else "👤"
                    git_text.append(f"{icon} ", style="dim")
                    git_text.append(f"{h} ", style="yellow")
                    msg_short = msg[:35] + "…" if len(msg) > 35 else msg
                    git_text.append(f"{msg_short}\n", style="white")
                    git_text.append(f"   {ago}\n", style="dim")
        else:
            git_text.append("No commits yet", style="dim")
    except Exception:
        git_text.append("Git unavailable", style="dim red")

    layout["middle"]["git_history"].update(Panel(
        git_text,
        title="📜 RECENT CHANGES",
        border_style="yellow",
        padding=(0, 1),
    ))

    # === FOOTER (Stats) ===
    stats_table = Table.grid(expand=True)
    stats_table.add_column(justify="center", ratio=1)
    stats_table.add_column(justify="center", ratio=1)
    stats_table.add_column(justify="center", ratio=1)
    stats_table.add_column(justify="center", ratio=1)
    stats_table.add_column(justify="center", ratio=1)
    stats_table.add_column(justify="center", ratio=1)

    stats_table.add_row(
        f"[bold green]{m.messages_processed}[/] MSG",
        f"[bold cyan]{m.tools_called}[/] TOOLS",
        f"[bold red]{m.errors_count}[/] ERR",
        f"[bold yellow]{m.last_response_time}[/] RESP",
        f"[bold magenta]{ram}%[/] RAM",
        f"[bold blue]{uptime}[/] UP",
    )

    layout["footer"].update(Panel(
        stats_table,
        title="📈 SESSION STATS",
        border_style="blue",
        padding=(0, 0),
    ))

    return layout


if __name__ == "__main__":
    monitor = BrainDashboard()

    with Live(generate_layout(monitor), refresh_per_second=4, screen=True) as live:
        try:
            while True:
                live.update(generate_layout(monitor))
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
