# Browser Tool — Gaps in Synapse-OSS

## Overview

openclaw ships a fully integrated Playwright-based headless browser tool as a bundled plugin (`extensions/browser/`). It exposes 16 actions across 11 act kinds, implements a two-phase SSRF navigation guard with pinned DNS, produces AI/ARIA accessibility snapshots, and manages a per-session tab registry. Synapse-OSS has a minimal single-function web scraping helper (`db/tools.py`) that dispatches to Crawl4AI (macOS/Linux) or raw Playwright (Windows) — essentially `page.inner_text("body")` truncated to 3000 characters, with no security guards, no tab management, no snapshot formats, and no integrated tool schema beyond a single `search_web` function.

---

## What openclaw Has

### 1. Tool Schema — 16 Actions, 11 Act Kinds (`extensions/browser/src/browser-tool.schema.ts`)

**16 top-level actions:**
`status`, `start`, `stop`, `profiles`, `tabs`, `open`, `focus`, `close`, `snapshot`, `screenshot`, `navigate`, `console`, `pdf`, `upload`, `dialog`, `act`

**11 act kinds (sub-actions within `act`):**
`click`, `type`, `press`, `hover`, `drag`, `select`, `fill`, `resize`, `wait`, `evaluate`, `close`

The schema is a single flat TypeBox object (not a union) to satisfy Vertex AI's rejection of top-level `anyOf`. The `act` sub-schema is embedded as an optional `request` field plus legacy flattened params for backward compatibility.

**File:** `extensions/browser/src/browser-tool.schema.ts`

### 2. Browser Tool Dispatch (`extensions/browser/src/browser-tool.ts`)

Imports from `core-api.ts`:
- `browserStart` / `browserStop` — Playwright launch/teardown.
- `browserNavigate` — SSRF-guarded navigation.
- `browserOpenTab` / `browserCloseTab` / `browserFocusTab` — multi-tab registry.
- `browserScreenshotAction` — normalized PNG/JPEG output.
- `browserPdfSave` — save current page as PDF.
- `browserArmDialog` / `browserArmFileChooser` — pre-arm intercept before triggering action.
- `browserProfiles` — named browser profiles (sandbox / host / node).
- `trackSessionBrowserTab` / `untrackSessionBrowserTab` — per-session cleanup registry.
- `getBrowserProfileCapabilities` — runtime capability probe per profile.
- `applyBrowserProxyPaths` / `persistBrowserProxyFiles` — proxy config materialization.
- `resolveExistingPathsWithinRoot` — path-safety for upload paths.
- `resolveNodeIdFromList` / `selectDefaultNodeFromList` — ARIA node resolution.

**File:** `extensions/browser/src/browser-tool.ts`

### 3. Snapshot Formats (`extensions/browser/src/browser-tool.actions.ts`)

Two accessibility snapshot formats:
- `"aria"` — raw ARIA tree dump.
- `"ai"` — condensed AI-optimized format.

Snapshot options:
- `snapshotFormat`: `"aria"` | `"ai"`
- `refs`: `"role"` | `"aria"` — roleRefs cache for stable cross-turn element references.
- `mode`: `"efficient"` — compact output mode.
- `interactive`: filter to interactive elements only.
- `compact`: reduce whitespace.
- `depth`: limit tree depth.
- `maxChars`: character budget.

The `wrapExternalContent` wrapper adds an untrusted-content marker with `source: "browser"` to all snapshot, console, and tabs outputs — prevents the model from treating browser-controlled HTML as trusted system content.

**File:** `extensions/browser/src/browser-tool.actions.ts`

### 4. SSRF Two-Phase Navigation Guard (`src/infra/net/ssrf.ts`)

openclaw's SSRF guard is significantly more complete than Synapse-OSS's:

- **Phase 1 (pre-DNS):** Rejects known hostnames: `localhost`, `localhost.localdomain`, `metadata.google.internal`; rejects suffix patterns: `.local`, `.internal`, `.localhost`.
- **Phase 2 (post-DNS):** Resolves the hostname via `dns.lookup`, then checks every returned IP against blocked networks using `isBlockedSpecialUseIpv4Address` and `isBlockedSpecialUseIpv6Address` (RFC 1918, loopback, link-local, ULA, documentation ranges, RFC 2544 benchmark range).
- **Pinned DNS:** `resolvePinnedHostname(hostname)` returns a `lookup` function that is passed directly to `http.request` / `https.request`. This ensures the IP resolved by the SSRF check is the same IP used for the actual connection — no TOCTOU window.
- **Policy flags:** `allowPrivateNetwork`, `dangerouslyAllowPrivateNetwork`, `allowRfc2544BenchmarkRange`, `allowedHostnames` (allowlist), `hostnameAllowlist`.
- **IPv6 embedded IPv4 extraction:** `extractEmbeddedIpv4FromIpv6` handles `::ffff:192.168.1.1` style addresses.
- **Legacy IP literal detection:** `isLegacyIpv4Literal` catches octal/hex-encoded IPs that some DNS resolvers accept.
- **Redirect header stripping:** `retainSafeHeadersForCrossOriginRedirect` drops `Authorization`, `Cookie`, etc. on cross-origin redirects.

**Files:** `src/infra/net/ssrf.ts`, `src/shared/net/ip.ts`, `src/infra/net/redirect-headers.ts`

Synapse-OSS `media/ssrf.py` has a single-phase async DNS check (no pinned DNS, no IPv6 embedded IPv4, no TOCTOU protection, no redirect handling).

### 5. Per-Session Tab Registry

`trackSessionBrowserTab(sessionKey, tabId)` / `untrackSessionBrowserTab(sessionKey, tabId)` maintain a per-session set of open tab IDs. On session end, the gateway calls cleanup to close all tabs opened by that session, preventing tab accumulation across sessions.

**File:** `extensions/browser/src/core-api.ts` (imports of `trackSessionBrowserTab` and `untrackSessionBrowserTab`)

### 6. Screenshot Normalization

`browserScreenshotAction` returns a normalized `{type: "image", data: base64, mimeType}` block. Supports PNG and JPEG (`type` parameter). `fullPage` flag for full-page capture. Output goes through `imageResultFromFile` which applies size normalization.

### 7. Console Log Capture

`browserConsoleMessages` / `executeConsoleAction` captures browser console output (log, warn, error) as a structured list wrapped in the untrusted-content envelope.

### 8. Multi-Profile Support

Profiles: `"sandbox"`, `"host"`, `"node"`. Each profile runs a separate Playwright browser instance with isolated storage. `getBrowserProfileCapabilities(profile)` queries what the profile can do. `browserProfiles()` lists configured profiles. Config at `extensions/browser/src/config/` controls proxy paths per profile.

### 9. Form/Dialog/File Automation

- `browserArmDialog(accept, promptText)` — pre-arms a dialog handler before triggering.
- `browserArmFileChooser(paths)` — pre-arms a file chooser with upload paths.
- `browserAct({kind: "fill", fields: [...]})` — multi-field form fill in a single action.
- `browserAct({kind: "drag", startRef, endRef})` — drag-and-drop via ARIA refs.

### 10. PDF Export

`browserPdfSave` exports the current page as a PDF file, returns the file path.

---

## What Synapse-OSS Has (or Lacks)

`workspace/db/tools.py` — `ToolRegistry.search_web(url)`:

- Single function, no actions, no schema beyond one JSON Schema entry.
- Dispatches to `AsyncWebCrawler` (Crawl4AI) on Linux/macOS or `playwright.async_api` on Windows.
- Returns `page.inner_text("body")[:3000]` — truncated visible text only.
- No SSRF guard.
- No tab management.
- No snapshot formats.
- No screenshot capability.
- No console capture.
- No PDF export.
- No form/dialog/file automation.
- No multi-profile support.
- No session cleanup.
- No external-content trust boundary wrapping.

| Feature | Synapse-OSS | openclaw |
|---|---|---|
| Actions count | 1 (`search_web`) | 16 |
| Act kinds | 0 | 11 |
| SSRF guard | None | Two-phase with pinned DNS |
| Snapshot formats | None | AI + ARIA |
| Screenshots | None | PNG/JPEG, full-page |
| Tab management | None | Full per-session registry |
| Console capture | None | Structured log capture |
| PDF export | None | Yes |
| File upload | None | Yes (path-safe) |
| Dialog intercept | None | Pre-arm pattern |
| Multi-profile | None | sandbox / host / node |
| Trust boundary | None | `wrapExternalContent` |

---

## Gap Summary

Synapse-OSS's browser capability is essentially a read-only URL scraper. Every interactive capability — click, type, form fill, drag, file upload, dialog handling, tab management, PDF export, accessibility snapshots — is absent. The security posture is also significantly weaker: no SSRF guard, no pinned DNS, no cross-origin redirect header stripping.

---

## Implementation Notes for Porting

1. **SSRF guard** — Port `is_ssrf_blocked` from `media/ssrf.py` (already exists) but add: (a) pinned DNS by resolving first then connecting to the resolved IP; (b) IPv6 embedded IPv4 handling; (c) redirect header stripping for cross-origin redirects.

2. **Tool schema** — Define a flat Python dataclass/TypedDict schema with all 16 actions. Use a discriminator-based dispatch dict for routing.

3. **Playwright integration** — Wrap `playwright.async_api` with an async context manager that tracks pages per session key. On session end, close all tracked pages.

4. **Snapshot formats** — For `"ai"` format: query `page.accessibility.snapshot()` and post-process to compact form. For `"aria"` format: return the raw Playwright accessibility tree JSON.

5. **Trust boundary** — Wrap all browser-sourced content in a marker block (e.g. `<!-- BROWSER:UNTRUSTED -->...<!-- END -->`) before returning to the model.

6. **Multi-profile** — Maintain a dict of `{profile_name: BrowserContext}` instances. Launch lazily on first use, keep alive across turns within the same session.
