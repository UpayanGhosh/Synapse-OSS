# SSRF Protection — Gap Analysis

## Overview

Both codebases implement SSRF protection, but openclaw's implementation is
significantly more complete: it adds pinned DNS resolution, IPv6 / embedded-IPv4
handling, legacy IPv4 literal detection, hostname allowlist patterns, and a
`PinnedDispatcher` that wires the SSRF policy directly into every HTTP request
via undici. Synapse-OSS has a narrower SSRF guard scoped only to media downloads.

---

## What openclaw has

### Core SSRF policy engine
**`src/infra/net/ssrf.ts`**

Key exports and their gap value:

- **`SsrFPolicy`** type — configurable policy object:
  - `allowPrivateNetwork` / `dangerouslyAllowPrivateNetwork` — explicit opt-out flags
  - `allowRfc2544BenchmarkRange` — RFC 2544 benchmark range (198.18.0.0/15) opt-in
  - `allowedHostnames` — per-hostname skip list (for internal services)
  - `hostnameAllowlist` — glob-style `*.example.com` allowlist; empty = allow all

- **`isPrivateIpAddress(address, policy?)`** — classifies an IP string as
  private/special-use. Handles:
  - Canonical dotted-decimal IPv4 (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, etc.)
  - IPv6 loopback, ULA (`fc00::/7`), link-local (`fe80::/10`), mapped IPv4
    (`::ffff:192.168.x.x`)
  - Extracted embedded IPv4 from IPv6 (`::ffff:c0a8:0101`)
  - Legacy IPv4 literals (octal `010.0.0.1`, hex `0xC0A80001`, short form `3232235521`)
  - Malformed IPv6 literals — fail-closed
  - RFC 2544 benchmark range (198.18.0.0/15) when not overridden

- **`BLOCKED_HOSTNAMES`** set — `localhost`, `localhost.localdomain`,
  `metadata.google.internal`
- **`isBlockedHostname(hostname)`** — blocks `.localhost`, `.local`, `.internal` suffixes

- **Two-phase DNS check in `resolvePinnedHostnameWithPolicy()`**:
  1. Pre-DNS: fail fast for literal IPs and known-blocked hostnames before any
     DNS side-effects
  2. Post-DNS: re-check every resolved IP address so public hostnames cannot
     pivot to private targets via DNS rebinding or split-horizon DNS

- **`createPinnedLookup(hostname, addresses)`** — returns a custom `dns.lookup`
  callback that round-robins across pre-resolved addresses. Prevents DNS
  re-resolution attacks mid-connection.

- **`createPinnedDispatcher(pinned, policy?, ssrfPolicy?)`** — creates an undici
  `Agent`, `EnvHttpProxyAgent`, or `ProxyAgent` with the pinned lookup injected
  into the `connect` options. This means SSRF policy enforcement is wired at the
  transport layer, not just before the request is initiated.

- **`PinnedDispatcherPolicy`** discriminated union — supports `"direct"`,
  `"env-proxy"`, `"explicit-proxy"` modes, all with the pinned lookup override.

- **`SsrFBlockedError`** — typed error class (name `"SsrFBlockedError"`) for
  upstream catch differentiation.

### Fetch guard
**`src/infra/net/fetch-guard.ts`** — wraps `globalThis.fetch` with an SSRF
pre-check using `isBlockedHostnameOrIp()`. Any fetch call to a private address
raises `SsrFBlockedError` before the TCP connection is attempted.

**`src/infra/net/undici-global-dispatcher.ts`** — installs a global undici
dispatcher that enforces SSRF policy on all undici-based HTTP calls (including
`node:http` when routed through undici).

### Hostname normalization
**`src/infra/net/hostname.ts`** — `normalizeHostname()`:
- Strips brackets from IPv6 literals (`[::1]` → `::1`)
- Lowercases and trims
- Returns `null` for empty/invalid input (used throughout SSRF checks to avoid
  processing malformed inputs)

---

## What Synapse-OSS has

**`sci_fi_dashboard/media/ssrf.py`** — `is_ssrf_blocked(url)`:
- Parses URL hostname with `urlparse`
- Checks against `_BLOCKED_HOSTNAMES` (`localhost`, `metadata.google.internal`)
- Checks `_BLOCKED_HOSTNAME_SUFFIXES` (`.local`, `.internal`, `.localhost`)
- Resolves via `loop.getaddrinfo(hostname, None)` (non-blocking)
- Checks resolved IPs against `_BLOCKED_NETS`:
  `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
  `169.254.0.0/16`, `::1/128`, `fc00::/7`
- Fail-closed on DNS error

Also provides `download_to_file()` which:
- Calls `is_ssrf_blocked()` before any HTTP request
- Rejects symlink destinations
- Enforces `max_bytes` download limit
- Streams with chunked I/O and atomic rename

---

## Gap analysis

Synapse-OSS covers the core private-IP detection use case for media downloads.
The gaps versus openclaw are:

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Private IPv4 ranges (RFC 1918) | Yes | Yes |
| IPv6 loopback + ULA | Yes | Yes |
| `.local` / `.internal` / `.localhost` hostname blocks | Yes | Yes |
| Blocked metadata endpoints | Yes | Yes |
| Legacy IPv4 literals (octal, hex, short) | Yes | No |
| Embedded IPv4 in IPv6 (`::ffff:c0a8:*`) | Yes | Partial (only `::1`) |
| Malformed IPv6 fail-closed | Yes | Partial |
| RFC 2544 benchmark range | Yes | No |
| Two-phase pre-DNS + post-DNS check (DNS rebinding) | Yes | No (single post-DNS check) |
| Pinned DNS resolution (no re-lookup) | Yes | No |
| Per-hostname policy allowlist (`*.example.com`) | Yes | No |
| Transport-level SSRF (PinnedDispatcher / undici) | Yes | No |
| Global fetch guard | Yes | No |
| Configured `allowPrivateNetwork` opt-out | Yes | No |
| `SsrFBlockedError` typed exception | Yes | No (PermissionError) |
| Applied to all outbound HTTP, not just media | Yes | No |

The most security-relevant gaps are:
- **DNS rebinding**: Synapse-OSS does a single post-DNS check in `getaddrinfo`.
  A DNS rebinding attack can return a public IP for the first lookup and a
  private IP for subsequent connections within the same HTTP session.
  openclaw's `createPinnedLookup` pins resolved addresses for the life of the
  connection, closing this window.
- **Legacy IPv4 literals**: `http://0177.0.0.1/` (octal 127) is not blocked by
  Synapse-OSS's `ipaddress.ip_address()` check (it raises `ValueError`, but the
  fallback path is not hardened).
- **Scope**: Synapse-OSS SSRF protection applies only to `media/ssrf.py` callers.
  Other outbound HTTP (LLM API calls, webhook deliveries, channel API calls) are
  not guarded.

---

## Implementation notes for porting

1. **Legacy IPv4 literals**: Extend `is_ssrf_blocked` to try parsing with
   `ipaddress.ip_address()` and also detect octal/hex forms by regex before
   passing to `getaddrinfo`.

2. **DNS rebinding**: After `getaddrinfo`, cache the resolved addresses and
   create a custom `ssl.SSLContext` / `aiohttp.TCPConnector` that uses a
   custom resolver returning only the cached addresses for the lifetime of
   the connection.

3. **Embedded IPv4 in IPv6**: After `getaddrinfo`, for `AF_INET6` results,
   check if the IPv6 address is an IPv4-mapped address (`::ffff:0:0/96`) and
   re-evaluate the embedded IPv4 octets.

4. **Global scope**: Move `is_ssrf_blocked` to a shared utility and call it
   from every `httpx.AsyncClient` / `aiohttp.ClientSession` creation via a
   custom event hook or transport wrapper. Do not rely on call-site opt-in.

5. **Allowlist**: Add a `ssrf_hostname_allowlist` config key (`list[str]`)
   that supports `*.domain.com` patterns for internal services that legitimately
   reside on private networks.
