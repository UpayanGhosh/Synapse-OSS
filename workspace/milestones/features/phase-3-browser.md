# Phase 3: Headless Web Browser Integration (Playwright)

## Overview

OpenClaw integrates headless browser control via a bundled `browser` extension that
wraps Playwright. It supports clicking, typing, form filling, navigation, screenshots,
accessibility snapshots, dialog handling, and file uploads — all exposed as a single
`browser` agent tool. Security is enforced through SSRF policy and two-phase navigation
validation.

---

## Key Files

| File | Role |
|------|------|
| `extensions/browser/src/browser-tool.ts` | Tool factory — creates the `browser` `AnyAgentTool` |
| `extensions/browser/src/browser-tool.schema.ts` | Zod schema — all 16 actions + 11 act kinds |
| `extensions/browser/src/browser-tool.actions.ts` | High-level action handler dispatch |
| `extensions/browser/index.ts` | Plugin entry point |
| `extensions/browser/src/browser/pw-session.ts` | Browser connection + page state management |
| `extensions/browser/src/browser/pw-tools-core.interactions.ts` | Click, type, fill, scroll, screenshot |
| `extensions/browser/src/browser/session-tab-registry.ts` | Tracks tabs opened per agent session |
| `extensions/browser/src/browser/navigation-guard.ts` | SSRF-aware navigation validation |
| `extensions/browser/src/browser/routes/agent.act.ts` | HTTP route: action dispatch |
| `extensions/browser/src/browser/routes/agent.snapshot.ts` | HTTP route: snapshot rendering |
| `extensions/browser/src/browser/routes/tabs.ts` | HTTP route: tab management |
| `extensions/browser/src/browser/routes/dispatcher.ts` | Route multiplexer |
| `extensions/browser/src/browser/client-actions-core.ts` | HTTP client for all endpoints |
| `src/infra/net/ssrf.ts` | SSRF policy enforcement |

---

## Tool Schema

The `browser` tool accepts one of 16 actions:

| Action | Purpose |
|--------|---------|
| `status` | Browser status (connected, profile, tabs) |
| `start` | Launch browser instance |
| `stop` | Terminate browser instance |
| `profiles` | List browser profiles |
| `tabs` | List open tabs |
| `open` | Open a new tab to a URL |
| `focus` | Focus an existing tab |
| `close` | Close a tab |
| `snapshot` | Capture accessibility or AI-optimized page tree |
| `screenshot` | Capture viewport/full-page/element image |
| `navigate` | Navigate current tab to URL |
| `console` | Retrieve console + error log |
| `pdf` | Export page as PDF |
| `upload` | Trigger file upload dialog |
| `dialog` | Accept or dismiss browser dialogs |
| `act` | Execute one or more page interactions |

### Act Kinds (used with `action: "act"`)

| Kind | Description |
|------|-------------|
| `click` | Single or double-click an element |
| `type` | Type text (optionally submit) |
| `press` | Send a single key (e.g., `"Enter"`) |
| `hover` | Hover over element |
| `drag` | Drag from one element to another |
| `select` | Select dropdown option(s) |
| `fill` | Bulk form fill (`fields[]`) |
| `resize` | Resize viewport |
| `wait` | Wait for text, element, URL, or load state |
| `evaluate` | Execute arbitrary JavaScript in page context |
| `batch` | Run multiple act requests sequentially |

---

## Browser Connection & Page State

### Connection Management (`pw-session.ts`)

Connections are cached by CDP URL:

```typescript
const cachedByCdpUrl: Map<string, ConnectedBrowser>
```

Retry logic: 3 attempts, 5000ms base timeout + 2000ms per attempt.

```typescript
type ConnectedBrowser = {
  browser: Browser
  cdpUrl: string
  onDisconnected?: () => void
}
```

### Page State (WeakMap)

Per-page state is stored in a `WeakMap` — automatically GC'd when pages close:

```typescript
const pageStates = new WeakMap<Page, PageState>()

type PageState = {
  console: BrowserConsoleMessage[]    // capped at 500
  errors: BrowserPageError[]          // capped at 200
  requests: BrowserNetworkRequest[]   // capped at 500
  roleRefs?: Record<string, { role: string; name?: string; nth?: number }>
  roleRefsMode?: "role" | "aria"
}
```

### Role Refs Cache

Survives page object replacement at the CDP level:

```typescript
const roleRefsByTarget: Map<`${cdpUrl}::${targetId}`, RoleRefsCacheEntry>
// Max 50 entries, LRU eviction
```

---

## Interaction Implementation

All interactions are in `pw-tools-core.interactions.ts`.

### Locator Resolution

```typescript
const locator = refLocator(page, ref) || page.locator(selector)
```

`refLocator()` maps symbolic refs (e.g., `e1`, `e2` from snapshots) to Playwright
locators via Playwright's aria-query. Falls back to CSS selectors.

### Key Functions

| Function | Inputs | Behavior |
|----------|--------|----------|
| `clickViaPlaywright()` | ref/selector, button, modifiers, delayMs | Single or double click |
| `typeViaPlaywright()` | ref/selector, text, submit, slowly | Fill + optional Enter |
| `fillFormViaPlaywright()` | `fields: BrowserFormField[]` | Batch form fill |
| `selectOptionViaPlaywright()` | ref/selector, values[] | Set dropdown selection |
| `dragViaPlaywright()` | startRef, endRef | Drag and drop |
| `pressKeyViaPlaywright()` | key (string), delayMs | Single key (arrows, Enter, Escape…) |
| `hoverViaPlaywright()` | ref/selector | Mouse hover |
| `evaluateViaPlaywright()` | fn (string), ref? | Execute JS in page context |
| `waitForViaPlaywright()` | text, selector, url, loadState | Flexible wait conditions |

### Timeout Constraints

| Limit | Value |
|-------|-------|
| Max click delay | 5000ms |
| Max wait time | 30000ms |
| Interaction timeout range | 500–60000ms (clamped) |
| Max batch actions | 100 |

---

## Screenshots

```typescript
takeScreenshotViaPlaywright({
  cdpUrl: string
  targetId?: string
  ref?: string           // element ref → element screenshot
  element?: string       // CSS selector → element screenshot
  fullPage?: boolean     // full page vs viewport
  type?: "png" | "jpeg"
}): Promise<{ buffer: Buffer }>
```

### Variants

1. **Full page** — `page.screenshot({ type, fullPage: true })`
2. **Viewport** — `page.screenshot({ type, fullPage: false })`
3. **Element by ref** — `refLocator(page, ref).screenshot({ type })`
4. **Element by selector** — `page.locator(selector).first().screenshot({ type })`
5. **With labels** — `screenshotWithLabelsViaPlaywright()` — renders ref badges (max 150)

### Normalization

- Max side dimension: 2000px
- Max file size: 5MB
- Adaptive JPEG compression with multi-step quality degradation
- Multiple resize passes until both constraints are satisfied

---

## Snapshots

Snapshots capture the page structure for LLM consumption without full screenshots.

| Format | Description |
|--------|-------------|
| `"aria"` | Full ARIA accessibility tree (`AriaSnapshotNode[]`) |
| `"ai"` | AI-optimized condensed snapshot with role-ref mapping |

```typescript
snapshotAiViaPlaywright({
  cdpUrl: string
  targetId?: string
  timeoutMs?: number
  maxChars?: number
}): Promise<{ snapshot: string; refs: RoleRefMap; truncated?: boolean }>
```

The AI snapshot uses `page._snapshotForAI()` (Playwright internal API), then builds
a role-ref map stored in `roleRefsByTarget` cache for use in subsequent `act` calls.

---

## SSRF Security & Navigation Guard

All navigation is validated in two phases.

### Phase 1 — Pre-Navigation Check

```typescript
assertBrowserNavigationAllowed({
  url: string
  lookupFn?: LookupFn
  ssrfPolicy?: SsrFPolicy
}): Promise<void>
```

- Only `http://` and `https://` protocols allowed
- `about:blank` is the only non-network URL permitted
- Blocked on literal private/loopback IPs and known internal hostnames

### Phase 2 — Post-Navigation Check

```typescript
assertBrowserNavigationResultAllowed({
  url: string          // final URL after navigation
  ...
}): Promise<void>
```

Re-validates the final URL to block public→private pivots via redirects.

### Redirect Chain Validation

```typescript
assertBrowserNavigationRedirectChainAllowed({
  request?: BrowserNavigationRequestLike | null
  ...
}): Promise<void>
```

Every hop in a redirect chain is individually validated.

### SSRF Policy

```typescript
type SsrFPolicy = {
  allowPrivateNetwork?: boolean
  dangerouslyAllowPrivateNetwork?: boolean
  allowRfc2544BenchmarkRange?: boolean
  allowedHostnames?: string[]
  hostnameAllowlist?: string[]
}
```

**Always blocked:**

| Category | Examples |
|----------|---------|
| Loopback | `127.0.0.0/8`, `::1` |
| Private IPv4 | `10.x`, `172.16.x`, `192.168.x` |
| Private IPv6 | `fe80::/10`, `fc00::/7` |
| Internal hostnames | `*.localhost`, `*.local`, `*.internal` |
| Metadata endpoints | `metadata.google.internal` |

**Pinned DNS Resolution** (`createPinnedLookup()`): DNS is resolved once and cached
to prevent DNS TOCTOU attacks (resolving to a safe IP then rebinding to a private one).

---

## Session & Tab Tracking

`session-tab-registry.ts` maps agent session keys to open browser tabs:

```typescript
trackSessionBrowserTab(sessionKey, targetId)
untrackSessionBrowserTab(sessionKey, targetId)
closeTrackedBrowserTabsForSessions(sessionKeys[])  // cleanup on session end
```

When a session ends, all tabs it opened are automatically closed.

---

## HTTP API Endpoints (Internal)

The browser extension exposes an internal HTTP service. The tool communicates with it
via `client-actions-core.ts`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Status |
| POST | `/start` | Launch browser |
| POST | `/stop` | Terminate browser |
| GET | `/tabs` | List tabs |
| POST | `/tabs/open` | New tab |
| POST | `/tabs/focus` | Focus tab |
| DELETE | `/tabs/{targetId}` | Close tab |
| POST | `/navigate` | Navigate to URL |
| GET | `/snapshot` | Page snapshot |
| POST | `/screenshot` | Capture image |
| GET | `/console` | Console + errors |
| POST | `/pdf` | Export PDF |
| POST | `/act` | Execute action(s) |
| GET | `/cookies` | List cookies |
| GET/POST | `/storage/{local|session}` | LocalStorage/SessionStorage |
| POST | `/hooks/file-chooser` | Arm file input |
| POST | `/hooks/dialog` | Accept/dismiss dialog |

---

## End-to-End Flow: `act` → click

```
Agent calls browser tool { action: "act", kind: "click", ref: "e3" }
│
├─ browser-tool.ts validates schema
├─ Action router → executeActAction(request)
├─ HTTP POST /act → dispatcher.ts → routes/agent.act.ts
├─ getPageForTargetId(cdpUrl, targetId) → Playwright Page
├─ clickViaPlaywright({ page, ref: "e3", button: "left" })
│    ├─ refLocator(page, "e3") → Playwright Locator (aria-ref)
│    └─ locator.click({ button, delay, modifiers })
├─ Returns { ok: true, targetId, url }
└─ Wrapped as AgentToolResult text block
```

---

## Key Invariants

1. **No direct browser access** — all actions go through the HTTP API layer; the tool never touches Playwright directly.
2. **Two-phase SSRF** — navigation is validated before and after, blocking redirect-based bypasses.
3. **Tab cleanup** — session-scoped tab registry ensures no orphan tabs on session end.
4. **Ref stability** — role-ref cache (`roleRefsByTarget`) persists across page navigation within the same CDP target, so snapshot refs remain valid for subsequent `act` calls.
5. **WeakMap GC** — page state is tied to the Playwright `Page` object lifetime, preventing memory leaks on tab close.
