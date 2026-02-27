
import os
import time
import json
import random
from datetime import datetime

LOG_DIR = "/tmp/openclaw"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"openclaw-{datetime.now().strftime('%Y-%m-%d')}.log")

# Ensure the file exists
if not os.path.exists(log_file):
    with open(log_file, 'w') as f:
        f.write("")

print(f"Simulating brain activity in {log_file}...")

EVENTS = [
    ('{"subsystem":"agent/embedded"}', 'embedded run prompt start: runId=123'),
    ('{"subsystem":"agent/embedded"}', 'embedded run tool start: tool=web_search'),
    ('{"subsystem":"gateway/channels/whatsapp/inbound"}', 'Inbound message +123 -> +456 (direct, 15 chars)'),
    ('{"subsystem":"agent/embedded"}', 'embedded run tool start: tool=read_file'),
    ('{"subsystem":"agent/embedded"}', 'embedded run tool end: tool=read_file'),
    ('{"subsystem":"agent/embedded"}', 'embedded run tool start: tool=exec_command'),
    ('{"subsystem":"agent/embedded"}', 'embedded run agent start: runId=123'),
    ('{"subsystem":"agent/embedded"}', 'embedded run agent end: runId=123'),
    ('{"subsystem":"diagnostic"}', 'lane task done: lane=main'),
]

THOUGHTS = [
    "Analyzing user intent...",
    "Querying the vast knowledge base...",
    "Calculating probabilities for optimal response...",
    "Detecting sarcasm patterns...",
    "Formulating a witty retort...",
    "Accessing long-term memory archives...",
    "Optimizing neural pathways...",
]

def write_log(subsystem, message):
    entry = {
        "0": subsystem,
        "1": message,
        "time": datetime.utcnow().isoformat() + "Z"
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

# Simulate thoughts
def write_thought():
    thought = random.choice(THOUGHTS)
    brain_state = os.path.join(os.path.expanduser("~/.openclaw"), "brain_state.json")
    with open(brain_state, "w") as f:
        json.dump({"thought": thought}, f)

while True:
    event = random.choice(EVENTS)
    write_log(event[0], event[1])
    print(f"Sent: {event[1]}")
    
    if random.random() < 0.3:
        write_thought()
        print("Updated thought")

    time.sleep(random.uniform(0.5, 2.0))
