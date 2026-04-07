# Phase 05: Browser Tool — Research

**Researched:** 2026-04-07
**Confidence:** HIGH
**Status:** Ready for planning

---

## RESEARCH COMPLETE

## 1. Existing Codebase Assets

### SSRF Guard (Already Production-Ready)
- **Location:** `workspace/sci_fi_dashboard/media/ssrf.py`
- Handles RFC 1918, loopback, CGNAT, link-local, IPv6-mapped IPv4, and redirect-hop validation
- The browser skill imports it directly — **no re-implementation needed**
- Same guard pattern referenced in CLAUDE.md media pipeline docs

### HTTP Client
- `httpx` is already in the stack — use `safe_httpx_client()` for all outbound fetches
- This ensures SSRF protection is applied at the HTTP layer

### Skill Structure (Phase 1 Dependency)
- Skills are directories at `~/.synapse/skills/` containing `SKILL.md` + optional `scripts/`
- `SkillRouter.match()` routes by intent matching against skill `description` fields
- Phase 5 creates: `~/.synapse/skills/browser/` with `SKILL.md` + `scripts/fetch_and_summarize.py`

### Hemisphere/Privacy Boundary
- Dual hemispheres: `hemisphere_tag = "safe" | "spicy"`
- Vault role only touches `spicy` hemisphere — enforces zero cloud leakage
- Privacy check must block any outbound HTTP in spicy hemisphere

---

## 2. Technology Decisions

### Content Extraction: trafilatura v2.0
- **Why:** v2.0.0 shipped Dec 2024, beats newspaper3k/readability-lxml in benchmarks
- **Tiered fallback:** readability-lxml -> jusText handles JS-heavy SPAs
- **Critical:** trafilatura is synchronous — must wrap in `asyncio.to_thread()` to avoid blocking the event loop
- **Critical:** `trafilatura.fetch_url()` must NOT be used — the project's `safe_httpx_client()` must do the HTTP fetch (SSRF protection), then pass response bytes to `trafilatura.extract()`. Using trafilatura's own fetcher bypasses the SSRF guard.

### Web Search: DDGS (duckduckgo-search)
- **Why:** Brave Search dropped its free tier in Feb 2026 (now $5 credit ~ 1000 queries/month). DDGS is the standard in open-source AI pipelines — no API key required.
- **Rate limiting is a real problem:** Documented across dozens of GitHub projects. Must implement 1 req/s + exponential backoff.
- **Mock in all non-smoke tests** to avoid flaky CI from search provider throttling.
- **Configurable provider:** Architecture should allow swapping DDGS for Brave/Serper via `synapse.json` config.

---

## 3. Architecture Decisions

### Hemisphere Guard Placement
- **Must live inside the skill script**, not the router
- `SkillRouter.match()` runs before hemisphere context is confirmed
- The guard must be the first line of `scripts/fetch_and_summarize.py`
- Open question: exact key name (`hemisphere_tag` vs `session_type`) that Phase 1's SkillRunner passes — plan 05-03 must read `skills/runner.py` first

### Source Attribution
- Every response that used a web fetch must include source URL(s)
- Implement as structured metadata in the skill return value
- The response formatter appends URLs at the end of the LLM response

### Graceful Degradation
- Removing the `browser/` skill directory must result in "I can't browse right now" — not a 500
- This is handled by Phase 1's skill discovery: missing skill = no match = fallback response
- Plan 05-04 must verify this path explicitly

### Rate Limiting Strategy
- Per-domain request delay: configurable, default 1 req/s
- Exponential backoff on 429/503 responses: base 2s, max 32s, 3 retries
- Config in `synapse.json -> skills.browser.rate_limit`

---

## 4. Dependency Analysis

| Dependency | Phase | Status | Impact |
|-----------|-------|--------|--------|
| Skill directory structure | Phase 1 | Pending | Browser is a skill — needs SKILL.md format |
| SkillRunner context dict | Phase 1 | Pending | Hemisphere key name needed for privacy guard |
| Zone 2 consent flow | Phase 2 | Pending | First-use consent before outbound fetches |
| SSRF guard | Existing | Ready | Import directly from media/ssrf.py |
| httpx client | Existing | Ready | Already in requirements |

---

## 5. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| SSRF bypass via trafilatura.fetch_url() | Never use trafilatura's fetcher; always use safe_httpx_client() |
| Event loop blocking from trafilatura | Wrap all trafilatura calls in asyncio.to_thread() |
| Search provider throttling | 1 req/s rate limit + exponential backoff + mock in tests |
| JS-heavy SPA extraction | trafilatura v2 tiered fallback handles most cases |
| Spicy hemisphere data leak | Hemisphere check as first line of skill script |
| Skill removal crash | Phase 1 skill discovery handles missing skills gracefully |

---

## 6. New Dependencies (pip)

| Package | Version | Purpose |
|---------|---------|---------|
| trafilatura | >=2.0.0 | HTML content extraction + readability fallback |
| duckduckgo-search | >=7.0.0 | Web search without API key |

Both are pure Python, no native extensions, compatible with Python 3.11.

---

## 7. Open Questions

1. **Hemisphere key name in SkillRunner context:** Is it `hemisphere_tag` or `session_type`? Must read Phase 1's `skills/runner.py` output at plan time. Plan 05-03 must resolve this.

---

## 8. Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | trafilatura v2 verified on PyPI; httpx already in stack; DDGS confirmed |
| Architecture | HIGH | SSRF guard, skill structure, hemisphere pattern are direct codebase observations |
| Pitfalls | MEDIUM-HIGH | Rate limiting confirmed by multiple GitHub issues; sync-blocking confirmed by trafilatura docs |
| Open Questions | 1 gap | Hemisphere key name — resolved by reading Phase 1 runner.py output at plan time |

---

*Phase: 05-browser-tool*
*Research completed: 2026-04-07 by gsd-phase-researcher*
