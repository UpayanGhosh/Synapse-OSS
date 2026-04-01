# Interactive Messages: Missing Features in Synapse-OSS

## Overview

openclaw has a rich cross-channel interactive message layer: Telegram inline keyboards, Slack
Block Kit with interactive buttons and select menus, Discord Component V2 messages with modals,
exec-approval flows with per-channel button renderers, and emoji status reactions. Synapse-OSS
has no interactive message capability — all outbound messages are plain text.

---

## 1. Telegram Inline Keyboards

### What openclaw has

`extensions/telegram/src/inline-buttons.ts` resolves a `TelegramInlineButtonsScope`:
- `"off"` — disabled
- `"dm"` — enabled in DMs only
- `"group"` — enabled in groups only
- `"all"` — enabled everywhere
- `"allowlist"` — enabled for allowlisted users (default)

`extensions/telegram/src/button-types.ts` defines `TelegramInlineButtons` — a typed list of
button rows (`InlineKeyboardButton[][]`) that the outbound adapter attaches to
`sendMessage()` via `reply_markup.inline_keyboard`.

`extensions/telegram/src/model-buttons.ts` builds model-selection inline keyboards from the
agent config, allowing users to switch models by tapping a button.

`extensions/telegram/src/approval-native.ts` renders exec-approval prompts as inline keyboards
with Approve / Deny buttons, wiring back to the approval resolution pipeline.

### What Synapse-OSS has (or lacks)

`TelegramChannel.send()` calls `bot.send_message(chat_id, text)` — no `reply_markup`, no inline
keyboards, no buttons of any kind.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Inline keyboard rendering | Yes | No |
| Model-selection buttons | Yes | No |
| Approval Approve/Deny buttons | Yes | No |
| Scope gating (dm/group/all) | Yes | No |
| Callback query handling | Yes (`channel-actions.ts`) | No |

### Implementation notes for porting

1. Add `buttons: list[list[InlineKeyboardButton]] | None = None` to `ReplyPayload`.
2. Pass `reply_markup=InlineKeyboardMarkup(buttons)` in `send()` when buttons are present.
3. Register a PTB `CallbackQueryHandler` that routes button callbacks back to the pipeline.
4. Add scope resolution (`dm` / `group` / `all` / `allowlist`) to `TelegramChannel.__init__`.

---

## 2. Slack Block Kit with Interactive Replies

### What openclaw has

`extensions/slack/src/blocks-render.ts` translates openclaw's generic `InteractiveReply`
structure into Slack Block Kit JSON:

- Text blocks → `section` blocks with mrkdwn
- Button groups → `actions` blocks with `button` elements (styled `primary`/`danger`)
- Select menus → `actions` blocks with `static_select` elements
- Action IDs follow `openclaw:reply_button:<n>:<m>` and `openclaw:reply_select:<n>` patterns

`extensions/slack/src/block-kit-tables.ts` converts markdown tables into Slack native `table`
blocks with `column_settings` and capped at `SLACK_MAX_TABLE_ROWS = 100` rows.

`extensions/slack/src/interactive-replies.ts` — feature-gates Block Kit via
`isSlackInteractiveRepliesEnabled()` reading the `interactiveReplies` capability flag.

### What Synapse-OSS has (or lacks)

`SlackChannel.send()` calls `chat_postMessage(channel=chat_id, text=text)`. No `blocks`, no
Block Kit, no interactive elements.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Block Kit rendering | Yes | No |
| Button groups (actions block) | Yes | No |
| Select menus | Yes | No |
| Markdown table → native table | Yes | No |
| Capability-gating | `interactiveReplies` flag | No |

### Implementation notes for porting

1. Create `channels/slack_blocks.py` with `build_slack_interactive_blocks(interactive_reply)`.
2. Pass `blocks=blocks` to `chat_postMessage()` when blocks are non-empty; fall back to `text`.
3. Register a `block_actions` handler via `slack-bolt` for button/select callbacks.
4. Add `interactive_replies: bool = False` to the Slack account config.

---

## 3. Discord Component V2 Messages and Modals

### What openclaw has

`extensions/discord/src/components.ts` defines a full Discord Component V2 spec:

```typescript
// Buttons
type DiscordComponentButtonSpec = {
  label: string; style?: DiscordComponentButtonStyle; url?: string;
  callbackData?: string; allowedUsers?: string[]; emoji?: {...}; disabled?: boolean;
};

// Select menus: string / user / role / mentionable / channel
type DiscordComponentSelectSpec = { type?: DiscordComponentSelectType; callbackData?: string; ... };

// Modal fields: text / checkbox / radio / select / role-select / user-select
type DiscordComponentModalFieldType = "text"|"checkbox"|"radio"|"select"|"role-select"|"user-select";
```

`extensions/discord/src/send.components.ts` builds the full Discord REST payload (including
`SUPPRESS_NOTIFICATIONS_FLAG`, media file attachments) and sends it via `@buape/carbon` REST
client. Component interactions are registered in `components-registry.ts` and dispatched back
through `channel-actions.ts`.

### What Synapse-OSS has (or lacks)

`DiscordChannel.send()` calls `channel.send(text)`. No embeds, no buttons, no modals, no
component messages. `DiscordChannel.receive()` stores `reply_callable` in `raw` for native
Discord reply threading but it is never used for interactivity.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Button rows | Yes | No |
| Select menus (5 types) | Yes | No |
| Modal forms | Yes | No |
| User-allowlisted buttons | Yes | No |
| File attachment components | Yes | No |
| Component callback dispatch | Yes | No |

### Implementation notes for porting

1. Add `discord.ui.View` construction from `ReplyPayload.interactive`.
2. Register a view and `on_interaction` callback to route button presses back.
3. Add modal support via `discord.ui.Modal`.

---

## 4. Exec-Approval Flows with Per-Channel Button Renderers

### What openclaw has

All three major channels have native approval renderers:

- `extensions/telegram/src/exec-approvals.ts` — resolves approver list, renders Approve/Deny
  inline keyboard, handles callback queries, returns approved/denied status.
- `extensions/discord/src/exec-approvals.ts` — uses Discord Component V2 buttons with
  user-allowlisted interactions (only designated approvers can click).
- `extensions/slack/src/exec-approvals.ts` — renders Block Kit action buttons for approval.

`extensions/slack/src/approval-auth.ts` and `extensions/telegram/src/approval-auth.ts` gate
interactive responses to authorized approvers only.

The approval pipeline (`openclaw/plugin-sdk/approval-runtime`) normalizes these back to a
common `ApprovalResult` and unblocks the waiting agent tool call.

### What Synapse-OSS has (or lacks)

No approval flow exists anywhere in Synapse-OSS. There is no concept of blocking an agent tool
pending human confirmation, and no button-based approval UI on any channel.

### Implementation notes for porting

1. Create `agents/approval.py` with an `ApprovalRequest(session_key, tool_name, context)`.
2. Implement `TelegramChannel.send_approval_request()` using PTB inline keyboards.
3. Route `CallbackQueryHandler` responses to an `ApprovalRegistry` that unblocks the waiting task.
4. Repeat for Slack (Block Kit) and Discord (discord.py `ui.View`).

---

## 5. Emoji Status Reactions

### What openclaw has

`src/channels/status-reactions.ts` defines a `StatusReactionController` with states:

```
queued → thinking → tool/coding/web → done/error
                 ↓ stallSoft (⏳ after 10 s)
                 ↓ stallHard (⚠️ after 30 s)
```

Each state transition is debounced (`debounceMs = 700 ms`) to avoid flicker. The controller
exposes a `StatusReactionAdapter` interface:

```typescript
type StatusReactionAdapter = {
  setReaction: (emoji: string) => Promise<void>;
  removeReaction?: (emoji: string) => Promise<void>;
};
```

Each channel extension wires its own adapter:
- Telegram: reacts to the inbound message with emoji
- Discord: `reactMessageDiscord()` + `deleteReactionDiscord()`
- Slack: `reactions.add` / `reactions.remove` via `WebClient`

Stall detection is a feature — `stallSoftMs` and `stallHardMs` thresholds flag long-running
agents to the user without any code changes.

### What Synapse-OSS has (or lacks)

`BaseChannel.send_reaction()` exists (returns `False` by default). `TelegramChannel` and
`WhatsAppChannel` implement it. However there is no status reaction controller, no state machine,
no debounce, no stall detection, and no integration with the agent lifecycle.

### Implementation notes for porting

1. Create `channels/status_reactions.py` with a `StatusReactionController` dataclass.
2. Implement states: `queued`, `thinking`, `tool`, `done`, `error`, `stall_soft`, `stall_hard`.
3. Integrate with the message worker loop: call `set_thinking()` before agent inference,
   `set_tool(name)` on each tool call, `set_done()` / `set_error()` on completion.
4. Wire a stall monitor (`asyncio.wait_for` with escalating timeouts).
