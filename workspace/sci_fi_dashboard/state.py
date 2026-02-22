import time
import subprocess
import json
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class Process:
    name: str
    progress: float  # 0.0 to 100.0
    status: str = "ACTIVE"

@dataclass
class LogEntry:
    timestamp: str
    level: str  # INFO, WARNING, ERROR
    message: str

@dataclass
class Activity:
    time_str: str
    narrative: str
    sub_text: str = ""

class DashboardState:
    def __init__(self):
        self.system_name = "JARVIS v2.4"
        self.status = "OPERATIONAL"
        self.uptime_start = time.time()
        self.active_tasks_count = 0
        self.network_health = 82
        self.cpu_load = 34
        self.memory_usage = "2.1GB"
        
        # Real Quota Stats
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.context_limit = 1048576
        self.active_sessions = 0
        
        self.processes: Dict[str, Process] = {
            "Memory Indexing": Process("Memory Indexing", 12.0),
            "Sentiment Monitor": Process("Sentiment Monitor", 88.0),
            "Shadow Pushing": Process("Shadow Pushing", 45.0),
        }
        
        self.activities: List[Activity] = []
        self.logs: List[LogEntry] = []

    def get_uptime_str(self):
        uptime_seconds = int(time.time() - self.uptime_start)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

    def add_activity(self, narrative: str, sub_text: str = ""):
        time_str = time.strftime("%H:%M")
        self.activities.insert(0, Activity(time_str, narrative, sub_text))
        if len(self.activities) > 10:
            self.activities.pop()

    def add_log(self, level: str, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.logs.insert(0, LogEntry(timestamp, level, message))
        if len(self.logs) > 20:
            self.logs.pop()

    def update_stats(self):
        import random
        import os
        try:
            import psutil
            self.cpu_load = psutil.cpu_percent()
            self.memory_usage = f"{psutil.virtual_memory().used / (1024**3):.1f}GB"
        except ImportError:
            self.cpu_load = random.randint(15, 45)
            self.memory_usage = "2.4GB"

        # Fetch real API usage
        try:
            result = subprocess.run(["openclaw", "sessions", "list", "--json"], capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                sessions = data.get("sessions", [])
                self.active_sessions = len(sessions)
                self.total_tokens_in = sum(s.get("inputTokens", 0) for s in sessions)
                self.total_tokens_out = sum(s.get("outputTokens", 0) for s in sessions)
                if sessions:
                    self.context_limit = sessions[0].get("contextTokens", 1048576)
        except Exception:
            pass
            
        # Update Processes with real-ish metrics
        try:
            # Indexing based on memory folder size (simplified proxy)
            mem_files = sum([len(files) for r, d, files in os.walk("/path/to/openclaw/workspace/memory")])
            self.processes["Memory Indexing"].progress = min(100.0, (mem_files / 500) * 100)
            
            # Sentiment based on random drift for visual effect but could be linked to last log
            self.processes["Sentiment Monitor"].progress = random.uniform(85, 95)
            
            # Shadow Pushing (Active if it's day time)
            import datetime
            hour = datetime.datetime.now().hour
            self.processes["Shadow Pushing"].status = "ACTIVE" if 10 <= hour <= 23 else "IDLE"
        except Exception:
            pass
