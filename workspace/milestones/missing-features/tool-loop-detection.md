# Tool Loop Detection — Missing in Synapse-OSS

## Overview

openclaw implements a multi-detector tool loop detection system in the agent
inference pipeline. When an agent repeatedly calls the same tool with the same
arguments and gets the same result (no progress), the system escalates from
warning to critical to blocking the session. Synapse-OSS has no equivalent.

---

## What openclaw has

**`src/agents/tool-loop-detection.ts`**

### Detector types
`LoopDetectorKind`:
- `"generic_repeat"` — any tool called N times with identical args (warn only)
- `"known_poll_no_progress"` — polling tools (`process poll`, `process log`,
  `command_status`) called N times with identical args and identical output
- `"global_circuit_breaker"` — any tool with identical args + output, hits the
  highest threshold
- `"ping_pong"` — alternating between two distinct tool calls with no output change

### Severity levels and thresholds (defaults)
| Threshold | Value | Effect |
|---|---|---|
| `warningThreshold` | 10 | Returns `level: "warning"` |
| `criticalThreshold` | 20 | Returns `level: "critical"` |
| `globalCircuitBreakerThreshold` | 30 | Returns `level: "critical"` (blocks) |
| History window | 30 calls | Sliding window for pattern detection |

All thresholds are configurable via `ToolLoopDetectionConfig` in the agent
config, with enforcement that `critical > warning` and `global > critical`.

### Core functions

**`detectToolCallLoop(state, toolName, params, config?): LoopDetectionResult`**
- Called before each tool execution in the inference loop
- Returns `{ stuck: false }` or `{ stuck: true, level, detector, count, message, warningKey }`
- Priority order: global circuit breaker → poll no-progress critical → poll
  no-progress warning → ping-pong critical → ping-pong warning → generic repeat

**`hashToolCall(toolName, params): string`**
- Stable SHA-256 of `toolName + stableStringify(params)`
- `stableStringify` sorts object keys for determinism across serialization order

**`recordToolCall(state, toolName, params, toolCallId?, config?)`**
- Appends to `state.toolCallHistory`, trims to `historySize`

**`recordToolCallOutcome(state, params)`**
- After a tool returns, back-fills `resultHash` into the matching history entry
- `hashToolOutcome` is aware of `process poll` and `process log` shapes and
  hashes only the stable fields (status, exitCode, aggregated) ignoring
  timestamps or ephemeral data

**`getToolCallStats(state)`**
- Returns `{ totalCalls, uniquePatterns, mostFrequent }` for debugging/monitoring

### Ping-pong detector detail
`getPingPongStreak(history, currentSignature)`:
- Detects A-B-A-B-... alternation in the tool call history
- Returns count, paired tool name, and `noProgressEvidence` flag
- `noProgressEvidence` requires both sides of the pair to have identical result
  hashes across the tail — prevents false positives when the agent is genuinely
  making progress

### Known poll tool check
`isKnownPollToolCall(toolName, params)`:
- Returns `true` for `command_status` or `process` with `action === "poll" | "log"`
- These tools are held to stricter thresholds since polling with no output
  change is a strong signal of a stuck loop

### Integration point
The detection hooks are called from
`src/agents/pi-embedded-subscribe.handlers.tools.ts` (the tool execution
handler inside the Pi agent loop). When `stuck: true` and `level: "critical"`,
the tool result is replaced with an error message and the session is flagged
to prevent further tool execution in that turn.

---

## What Synapse-OSS has (or lacks)

`sci_fi_dashboard/dual_cognition.py` has a `"stuck"` state in the `CognitiveState`
enum (line 119), but this refers to the agent's self-reported emotional/cognitive
state from LLM output parsing — it is not an automated detection system that
monitors tool call patterns.

There is no:
- Tool call history tracking
- Hash-based identical-call detection
- Polling loop detection
- Ping-pong alternation detection
- Warning/critical/blocking escalation thresholds
- Circuit breaker that stops tool execution
- `noProgressEvidence` check before escalating

---

## Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Tool call history sliding window | Yes (30 calls) | No |
| Identical-call hash (args + result) | Yes | No |
| Poll no-progress detector | Yes | No |
| Ping-pong alternation detector | Yes | No |
| Generic repeat detector | Yes | No |
| Global circuit breaker | Yes | No |
| Warning → critical → block escalation | Yes | No |
| Configurable thresholds | Yes | No |
| Per-tool result hash awareness | Yes (poll/log) | No |
| Tool execution blocked on critical | Yes | No |

---

## Implementation notes for porting

1. **History tracking**: Add a `tool_call_history: list[ToolCallRecord]` field to
   the session state. Each record stores `tool_name`, `args_hash`, `result_hash`,
   `tool_call_id`, `timestamp`.

2. **Hashing**: Use `hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()`
   for `args_hash`. Use a similar stable hash for `result_hash`, stripping
   timestamps and ephemeral fields.

3. **detectToolCallLoop**: Call this before each tool execution in the agent loop.
   Pass `tool_name`, `args`, and the session history. Return a `LoopDetectionResult`
   dataclass with `stuck: bool`, `level: str`, `detector: str`, `count: int`,
   `message: str`.

4. **Thresholds**: Default `warning=10`, `critical=20`, `global_circuit_breaker=30`.
   Make these configurable in `synapse.json` under `agents.loop_detection`.

5. **Critical action**: When `level == "critical"`, replace the tool result with
   an error message surfaced to the LLM, instructing it to stop the current
   approach. Optionally raise an exception that terminates the current inference
   turn.

6. **Poll detection**: Special-case `process poll`, `process log`, and any
   future polling tools. Lower the warning threshold for these since repeated
   identical poll output is a much stronger signal of a stuck loop.

7. **Ping-pong**: Track alternation between the last two distinct `args_hash`
   values. Require `noProgressEvidence` (both sides have identical result hashes
   in the tail) before escalating to critical to avoid false positives.
