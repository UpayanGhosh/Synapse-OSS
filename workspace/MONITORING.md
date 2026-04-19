# Monitoring Synapse in Real-Time

To see what the bot is doing in real-time, you can run the `monitor.py` script. It tails the system logs and formats them to show:

- 📥 **Inbound Messages**: When someone messages the bot.
- 🧠 **Thinking**: When the bot is processing and reasoning.
- 🔍 **DB Queries**: When the bot is searching its memory or database.
- 📖 **Reading**: When the bot is reading files or information.
- 📤 **Outbound Messages**: When the bot replies.

## How to run:

Open a new terminal and run:

```bash
~/.synapse/.venv/bin/python ~/.synapse/workspace/scripts/monitor.py
```

## Icons used in the monitor:

- 🚀 `AGENT START`: Agent session initialization.
- 🧠 `THINKING`: Reasoning phase (LLM processing).
- 🔍 `DB QUERY`: Accessing long-term memory or databases.
- 📖 `READING`: Reading content from files or context.
- 📥 `INBOUND`: Receiving a WhatsApp message.
- 📤 `OUTBOUND`: Sending a response.
- ✅ `DONE`: Completion of a tool or action.
