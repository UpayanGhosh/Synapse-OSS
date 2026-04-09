# Phase 7: Bundled Skills Library - Research

**Researched:** 2026-04-09
**Domain:** Extending the existing Synapse skill system with 10 bundled skills, `synapse.` namespace, `cloud_safe` metadata, and per-skill enable/disable
**Confidence:** HIGH

---

## Summary

Phase 7 builds directly on top of the fully verified Phase 1 (Skill Architecture). All core infrastructure — `SkillLoader`, `SkillRegistry`, `SkillRunner`, `SkillWatcher`, `seed_bundled_skills()` — is code-complete and passing 90 tests. Phase 7's work is primarily: (1) author 9 new SKILL.md skill directories in `workspace/sci_fi_dashboard/skills/bundled/` (weather, reminders, notes, translate, summarize, web-scrape, news, image-describe, timer, dictionary), (2) add two new fields to `SkillManifest` (`cloud_safe: bool`, `enabled: bool`), (3) implement the `synapse.` namespace prefix convention so bundled skills cannot be silently shadowed without a startup warning, and (4) enforce `enabled: false` in `SkillLoader` so disabled skills are never loaded into the registry.

The `seed_bundled_skills()` method in `SkillRegistry` already handles the first-boot copy-to-`~/.synapse/skills/` pattern. Phase 7 extends it to copy all 10 bundled skills, not just `skill-creator`. Because the seeding is no-overwrite by design, a user-installed skill named `weather` will silently shadow `synapse.weather` unless the registry adds a startup warning — that warning logic is new work in this phase.

No new external libraries are required. Weather API calls (open-meteo.com) are free and need no API key. The web-scrape and news skills need `httpx` or `requests` (both already in project deps). Image-describe needs the media pipeline (`workspace/sci_fi_dashboard/media/`) that already exists. The dictionary skill uses a free public API (dictionaryapi.dev). Timer is purely in-process (no external deps).

**Primary recommendation:** Add `cloud_safe` and `enabled` fields to `SkillManifest` (schema.py + loader.py), author 10 SKILL.md files under `bundled/`, extend `scan_directory` to skip `enabled: false` skills gracefully, add namespace shadow-warning to `SkillRegistry.scan()`, extend `seed_bundled_skills()` to cover all 10. Zero new Python packages required.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SKILL-01 | User gets 10 bundled skills at first install | `seed_bundled_skills()` already copies `bundled/` dirs to `~/.synapse/skills/` on first boot. Extending it to 10 dirs requires only authoring the 9 new SKILL.md directories; the seeding logic copies any subdir in `bundled/` automatically. |
| SKILL-02 | Bundled skills live in `workspace/skills/bundled/` as SKILL.md directories | The existing `skill-creator` already lives at `workspace/sci_fi_dashboard/skills/bundled/skill-creator/`. The REQUIREMENTS.md says `workspace/skills/bundled/` but actual code path is `workspace/sci_fi_dashboard/skills/bundled/` — research confirms the code path. All 9 new skills follow the same directory convention. |
| SKILL-03 | Skills declare `cloud_safe: true/false` metadata for Vault hemisphere enforcement | `SkillManifest` is a frozen dataclass in `schema.py`. Adding `cloud_safe: bool = True` (safe default) requires a one-line field addition plus a matching parse in `SkillLoader.load_skill()`. SkillRunner needs to check `cloud_safe` against session hemisphere before executing. |
| SKILL-04 | User can disable any bundled skill without affecting others | `SkillLoader.scan_directory()` currently loads all valid skills. Adding `enabled: bool = True` to `SkillManifest` and filtering `if not manifest.enabled: skip` in `scan_directory()` is the correct insertion point. The disabled skill's SKILL.md can still be parsed (for the warning); it just never enters the registry. |
</phase_requirements>

---

## Standard Stack

### Core (already in project — zero new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` or `requests` | already in requirements.txt | HTTP calls for weather, news, web-scrape, dictionary skills | Already used extensively in media pipeline and channel HTTP calls |
| `PyYAML` | already in requirements.txt | SKILL.md frontmatter parsing — `yaml.safe_load()` in SkillLoader | Already the SKILL.md parser; `cloud_safe` and `enabled` are just new YAML keys |
| Open-Meteo API | free, no API key | Weather skill — `https://api.open-meteo.com/v1/forecast` | Zero-config for users; coordinates from geocoding API (also free) |
| dictionaryapi.dev | free, no API key | Dictionary skill | No key needed; returns definitions, phonetics, examples |

### Weather API Details

Open-Meteo is zero-key. The weather skill uses two steps:
1. Geocode city name: `https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1`
2. Fetch weather: `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true`

Both are GET requests returning JSON. This fits naturally in a skill `entry_point` script that fetches context and returns it to the LLM for natural-language formatting.

### Supporting (optional — for richer skills)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `beautifulsoup4` | optional | Web-scrape skill HTML parsing | Only if web-scrape needs structured extraction beyond raw text; httpx alone suffices for raw content |
| `newspaper3k` or `readability-lxml` | optional | News article extraction | Simpler to do raw httpx + send to LLM for summarization; avoid if no clear need |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Open-Meteo (free, no key) | OpenWeatherMap (free tier) | Open-Meteo is truly free with no account required; OpenWeatherMap needs an API key registration |
| In-SKILL.md instructions only | entry_point scripts for API calls | entry_point scripts allow actual HTTP calls pre-LLM; SKILL.md-only works for LLM knowledge-only skills (translate, summarize, dictionary) |
| `enabled: false` field in SKILL.md | Separate config file to enable/disable | SKILL.md-native flag is self-contained and the user only edits one file |

---

## Architecture Patterns

### Recommended Bundled Directory Structure

```
workspace/sci_fi_dashboard/skills/bundled/
├── skill-creator/          # Already exists (Phase 1)
│   ├── SKILL.md
│   ├── scripts/.gitkeep
│   ├── references/.gitkeep
│   └── assets/.gitkeep
├── synapse.weather/        # NEW — cloud_safe: false (calls external API)
│   ├── SKILL.md
│   └── scripts/weather.py  # entry_point: fetches Open-Meteo
├── synapse.reminders/      # NEW — cloud_safe: true (in-process only)
│   └── SKILL.md
├── synapse.notes/          # NEW — cloud_safe: true (writes ~/.synapse/)
│   └── SKILL.md
├── synapse.translate/      # NEW — cloud_safe: false (calls cloud LLM)
│   └── SKILL.md
├── synapse.summarize/      # NEW — cloud_safe: false (calls cloud LLM)
│   └── SKILL.md
├── synapse.web-scrape/     # NEW — cloud_safe: false (fetches URL)
│   ├── SKILL.md
│   └── scripts/scrape.py
├── synapse.news/           # NEW — cloud_safe: false (fetches news API)
│   ├── SKILL.md
│   └── scripts/news.py
├── synapse.image-describe/ # NEW — cloud_safe: false (calls vision LLM)
│   └── SKILL.md
├── synapse.timer/          # NEW — cloud_safe: true (in-process timer)
│   └── SKILL.md
└── synapse.dictionary/     # NEW — cloud_safe: false (calls dict API)
    ├── SKILL.md
    └── scripts/dictionary.py
```

### Pattern 1: `synapse.` Namespace Convention

**What:** All 10 bundled skills use the `synapse.` prefix in their SKILL.md `name:` field (e.g., `name: synapse.weather`). The skill directory is also named `synapse.weather/`. This namespace signals "owned by Synapse core" and makes shadow detection straightforward.

**Shadow detection rule:** In `SkillRegistry.scan()`, after loading all skills, check whether a user-installed skill has the same base name as a bundled skill (e.g., user has `weather`, bundled has `synapse.weather`). Log a warning at INFO level:
```
[Skills] User skill 'weather' shadows bundled 'synapse.weather' — user version wins.
```
The check is: for each loaded skill with name NOT starting with `synapse.`, check if `synapse.{name}` is also in the loaded set. If so, log the warning.

**When to use:** Always — all 10 bundled skills get the `synapse.` prefix. User-created skills never start with `synapse.` (enforced by SkillCreator normalization — `synapse.` is not a valid lowercase-hyphenated segment produced by `_normalize_name()`).

**Example SKILL.md for `synapse.weather`:**
```yaml
---
name: synapse.weather
description: "Get current weather conditions for any city using real-time data."
version: "1.0.0"
author: "synapse-core"
triggers: ["weather in", "what's the weather", "how's the weather", "temperature in", "forecast for"]
model_hint: "casual"
permissions: ["network:fetch"]
cloud_safe: false
enabled: true
entry_point: "scripts/weather.py:get_weather_context"
---

# Weather

You are Synapse's weather assistant. Use the provided weather data to give a friendly, 
concise weather report. Include temperature, conditions, and any notable details.
```

### Pattern 2: `cloud_safe` Enforcement in SkillRunner

**What:** `SkillRunner.execute()` receives `session_context` (already in the signature as of Phase 1). When `session_context.get("session_type") == "spicy"` (Vault hemisphere), refuse to execute any skill where `manifest.cloud_safe is False`. Return a graceful `SkillResult` with a "not available in private mode" message.

**Where:** Add check at the top of `SkillRunner.execute()`, before the entry_point dispatch:
```python
if (
    not manifest.cloud_safe
    and session_context is not None
    and session_context.get("session_type") == "spicy"
):
    return SkillResult(
        text=f"The '{manifest.name}' skill isn't available in private mode.",
        skill_name=manifest.name,
        error=False,
        execution_ms=0.0,
    )
```

**When to use:** All skills that call external cloud APIs must declare `cloud_safe: false`. Skills that operate only locally (reminders stored in `~/.synapse/`, timer, notes) declare `cloud_safe: true`.

### Pattern 3: `enabled` Flag in SkillLoader

**What:** `SkillLoader.scan_directory()` currently calls `load_skill()` for every subdir and skips `SkillValidationError`. After Phase 7, it should also skip skills where `manifest.enabled is False`, logging a debug message (not a warning — disabled is intentional).

**Where:** In `SkillLoader.scan_directory()`, after `load_skill()` returns successfully:
```python
manifest = cls.load_skill(entry)
if not manifest.enabled:
    logger.debug("[Skills] Skipping disabled skill '%s'", manifest.name)
    continue
manifests.append(manifest)
```

**Graceful fallback for disabled skills:** When a disabled skill would have matched a user message, the router returns `None` (skill not in registry) and the message falls through to the normal traffic cop → MoA pipeline. The user receives a natural LLM response, not a routing error.

**Note on "graceful error message":** The success criterion says `synapse.reminders` disabled returns "I can't set reminders right now" — this is NOT an error response from the skill runner. It means the skill is absent from the registry, the router returns None, and the LLM in the normal pipeline naturally responds to "set a reminder" with a polite inability message. No special "disabled skill" handler needed — the LLM handles it naturally.

### Anti-Patterns to Avoid

- **Hardcoding the 10 skill names anywhere:** `seed_bundled_skills()` already iterates `bundled/` dynamically. Never add an explicit list of 10 names — add a new bundled skill by creating its directory and it's auto-discovered.
- **Using `name: weather` (without namespace):** If the bundled name is `weather`, the shadow detection `synapse.{name}` logic breaks. All bundled skills must use `synapse.` prefix in both the SKILL.md `name:` field AND the directory name.
- **Raising SkillValidationError for `enabled: false`:** Disabled skills should be silently skipped, not errored. Only log at debug level.
- **Blocking `cloud_safe: false` skills at load time:** The Vault hemisphere check is a runtime decision in SkillRunner, not a load-time decision. Skills are loaded regardless of `cloud_safe`; they are only blocked when actually executing in the wrong hemisphere.
- **Adding external HTTP calls to SKILL.md instructions:** Skills that need live data (weather, news) must use `entry_point` scripts. Never instruct the LLM to "fetch data from URL" in SKILL.md — it has no tool-calling capability in the chat path.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Weather API integration | Custom weather provider class | Open-Meteo via httpx in entry_point script | Open-Meteo is free/keyless; httpx is already in deps; the script is ~30 lines |
| HTML article extraction | Custom HTML parser | Send raw httpx response text to LLM | LLM can extract key information from raw HTML text; no BeautifulSoup needed for MVP |
| Namespace registry | Separate "bundled skill registry" class | Single `SkillRegistry` + `synapse.` prefix convention + shadow warning log | The registry is already thread-safe and hot-reload capable; separate class adds complexity for zero benefit |
| Timer persistence | Database-backed timer | In-process `asyncio.sleep` + BackgroundTask | Timers are volatile by nature; in-process is correct for MVP |
| Disable/enable API | HTTP endpoint to toggle skills | `enabled: false` in SKILL.md + SkillWatcher hot-reload | User edits the file, watcher detects change, skill disappears from registry in ~2s |

**Key insight:** Phase 7 is almost entirely file authoring. The infrastructure is complete. The only code changes are schema (2 new fields), SkillLoader filtering, SkillRunner Vault check, and SkillRegistry shadow warning.

---

## Common Pitfalls

### Pitfall 1: Directory Name vs. SKILL.md `name:` Field Mismatch

**What goes wrong:** Skill is named `synapse.weather` in SKILL.md but the directory is named `weather/`. `SkillRegistry.scan()` iterates directory names; `SkillLoader.load_skill()` reads the `name:` field from SKILL.md. Shadow detection compares SKILL.md names — if the SKILL.md says `synapse.weather` but the directory is `weather`, the seeding creates a directory `weather/` in `~/.synapse/skills/` and the user's custom `weather/` skill correctly shadows it. The warning fires: "User skill 'weather' shadows bundled 'synapse.weather'."

**Why it happens:** `seed_bundled_skills()` uses `shutil.copytree(skill_src, skill_dst)` where `skill_src.name` is the bundled directory name. If directory is `synapse.weather/`, the seeded skill is `~/.synapse/skills/synapse.weather/`.

**How to avoid:** Directory name MUST match the `name:` field in SKILL.md. Use `synapse.weather/` as both the directory name and SKILL.md `name: synapse.weather`.

**Warning signs:** `SkillRegistry.get_skill("synapse.weather")` returns None even after first boot — means directory name doesn't match SKILL.md name field.

### Pitfall 2: `SkillManifest` is `frozen=True` — New Fields Must Have Defaults

**What goes wrong:** Adding `cloud_safe: bool` without a default to the frozen dataclass raises `TypeError: non-default argument 'cloud_safe' follows default argument` when existing code creates `SkillManifest(name=..., description=..., version=...)`.

**Why it happens:** All existing optional fields have defaults. Any new required-position field breaks backward compatibility. The existing `skill-creator` bundled skill SKILL.md doesn't have `cloud_safe:` — it would fail validation if the field were required.

**How to avoid:** Always add new fields to `SkillManifest` with sensible defaults: `cloud_safe: bool = True` (safe default — cloud skills must explicitly opt out), `enabled: bool = True` (skills are enabled by default). The frozen dataclass constraint means values cannot be mutated after creation — this is intentional and correct.

### Pitfall 3: `_normalize_name()` in SkillCreator Strips Dots

**What goes wrong:** If a user asks `SkillCreator` to create a skill named `synapse.weather`, the `_normalize_name()` method strips the dot (it removes non-alphanumeric characters except hyphens), producing `synapsweather` or similar.

**Why it happens:** `_normalize_name()` uses `re.sub(r"[^a-z0-9\s-]", "", name)` which removes dots.

**Impact:** Not a real problem — users should never create `synapse.`-namespaced skills. The convention is "only Synapse core uses `synapse.`". `SkillCreator` generates user skills, which never get the prefix. This is correct behavior.

**Confirmation:** The success criterion says "A user-installed skill named `weather` shadows the bundled `synapse.weather`" — the user installs `weather`, not `synapse.weather`. No fix needed.

### Pitfall 4: `existing skill-creator` Has No `cloud_safe` or `enabled` Fields

**What goes wrong:** After adding `cloud_safe` and `enabled` to `SkillManifest`, parsing the existing `skill-creator` SKILL.md (which lacks these fields) should use the defaults (`True`, `True`). This works correctly via the `yaml_data.get("cloud_safe", True)` pattern in `SkillLoader.load_skill()`.

**Why it happens:** Only a problem if the loader uses `SkillManifest(**yaml_data)` directly, which would pass unknown keys as kwargs. The existing loader explicitly maps each field via `yaml_data.get(field, default)` — adding two new `.get()` calls is the correct approach.

**How to avoid:** In `SkillLoader.load_skill()`, add:
```python
cloud_safe=bool(yaml_data.get("cloud_safe", True)),
enabled=bool(yaml_data.get("enabled", True)),
```

### Pitfall 5: Weather Skill Success Criterion Requires Zero API Key

**What goes wrong:** Success criterion 2 says "Saying 'what's the weather in Tokyo?' routes to `synapse.weather` without any user configuration beyond a weather API key." But then success criterion 5 requires `cloud_safe: false` for all cloud-calling bundled skills.

**Careful reading:** The success criterion says "beyond a weather API key" — implying a weather API key IS required. But Open-Meteo requires no key. Resolution: **use Open-Meteo** (zero key required). The success criterion text is describing a hypothetical with a key; using a keyless API exceeds it.

**How to avoid:** Use Open-Meteo. If the design later requires a paid API (e.g., for better data), add an optional `api_key` field to the weather SKILL.md permissions or to `synapse.json`.

### Pitfall 6: Shadow Warning vs. Shadow Blocking

**What goes wrong:** The success criterion says "Synapse logs a warning at startup — the user's version wins." This is a LOG-ONLY warning. The bundled skill is simply not loaded (because the user's `weather` skill is a different name — `weather`, not `synapse.weather`). Both can coexist.

**Why it happens:** The shadow scenario is: user has `~/.synapse/skills/weather/SKILL.md` with `name: weather`. Bundled has `~/.synapse/skills/synapse.weather/SKILL.md` with `name: synapse.weather`. These are DIFFERENT skills in the registry. The router will match whichever has a better description/trigger match. There's no actual shadowing unless the names are identical.

**Clarification:** The warning should fire when user has a skill whose name equals the base-name of a `synapse.` skill. Detection: for each skill `s` where `not s.name.startswith("synapse.")`, check if `f"synapse.{s.name}"` is ALSO loaded. If yes, warn that user version may take priority in routing due to trigger overlap. Both remain in the registry.

---

## Code Examples

Verified patterns from existing codebase:

### Adding New Fields to SkillManifest (schema.py)

```python
# Source: workspace/sci_fi_dashboard/skills/schema.py (existing pattern)
# Add after `entry_point: str = ""`

cloud_safe: bool = True
# True  = skill is safe to run in any hemisphere (no external cloud calls)
# False = skill calls external cloud APIs; blocked in Vault (spicy) hemisphere
# Bundled skills that call external APIs MUST declare cloud_safe: false

enabled: bool = True
# False = skill is skipped during scan_directory; never enters the registry
# Users set this in their ~/.synapse/skills/<skill>/SKILL.md
# Default True: all skills enabled unless explicitly disabled
```

### Extending SkillLoader.load_skill (loader.py)

```python
# Source: workspace/sci_fi_dashboard/skills/loader.py line 104-115 (existing pattern)
# Add two new fields after existing optional fields:

return SkillManifest(
    name=str(yaml_data["name"]),
    description=str(yaml_data["description"]),
    version=str(yaml_data["version"]),
    author=str(yaml_data.get("author", "")),
    triggers=list(yaml_data.get("triggers", [])),
    model_hint=str(yaml_data.get("model_hint", "")),
    permissions=list(yaml_data.get("permissions", [])),
    instructions=instructions_body,
    path=skill_dir.resolve(),
    entry_point=str(yaml_data.get("entry_point", "")),
    cloud_safe=bool(yaml_data.get("cloud_safe", True)),    # NEW
    enabled=bool(yaml_data.get("enabled", True)),          # NEW
)
```

### Extending scan_directory to Skip Disabled Skills (loader.py)

```python
# Source: workspace/sci_fi_dashboard/skills/loader.py line 147-155 (existing pattern)
# After successful load_skill call, add enabled check:

try:
    manifest = cls.load_skill(entry)
    if not manifest.enabled:
        logger.debug("[Skills] Skipping disabled skill '%s' at %s", manifest.name, entry)
        continue      # <-- NEW: skip disabled skills silently
    manifests.append(manifest)
    logger.debug("[Skills] Loaded skill '%s' from %s", manifest.name, entry)
except SkillValidationError as exc:
    logger.warning("[Skills] Skipping invalid skill at %s: %s", entry, exc)
```

### Shadow Warning in SkillRegistry.scan() (registry.py)

```python
# Source: workspace/sci_fi_dashboard/skills/registry.py (extend existing scan())
# After self._skills is populated, add:

# Check for user skills that shadow bundled synapse.* skills
for skill_name in sorted(self._skills):
    if not skill_name.startswith("synapse."):
        bundled_name = f"synapse.{skill_name}"
        if bundled_name in self._skills:
            logger.warning(
                "[Skills] User skill '%s' shadows bundled '%s' — "
                "both are loaded; user version may win routing by trigger overlap.",
                skill_name,
                bundled_name,
            )
```

### cloud_safe Check in SkillRunner.execute() (runner.py)

```python
# Source: workspace/sci_fi_dashboard/skills/runner.py (add at top of execute())
# Before entry_point dispatch:

# Vault hemisphere guard — block cloud-calling skills in private sessions
if (
    not manifest.cloud_safe
    and session_context is not None
    and session_context.get("session_type") == "spicy"
):
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return SkillResult(
        text=f"The '{manifest.name}' skill isn't available in private mode.",
        skill_name=manifest.name,
        error=False,
        execution_ms=elapsed_ms,
    )
```

### Open-Meteo Weather Entry Point (scripts/weather.py)

```python
# Source: Open-Meteo public API (https://open-meteo.com — no API key required)
# Minimal entry_point function for synapse.weather skill

async def get_weather_context(user_message: str, session_context: dict | None):
    import httpx
    from dataclasses import dataclass

    @dataclass
    class WeatherResult:
        context_block: str
        source_urls: list
        error: str = ""

    # 1. Extract city from user message via simple heuristic
    # (LLM will do full NL interpretation — we just need rough city extraction)
    city = _extract_city(user_message)  # helper using regex patterns
    if not city:
        return WeatherResult(context_block="", source_urls=[], error="City not found in message")

    # 2. Geocode
    async with httpx.AsyncClient(timeout=5.0) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "format": "json"}
        )
        geo_data = geo.json()
        if not geo_data.get("results"):
            return WeatherResult(context_block="", source_urls=[], error=f"City '{city}' not found")
        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]
        place = geo_data["results"][0].get("name", city)

    # 3. Fetch weather
    async with httpx.AsyncClient(timeout=5.0) as client:
        wx = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lon, "current_weather": "true"}
        )
        wx_data = wx.json()
        cw = wx_data.get("current_weather", {})

    block = (
        f"Weather for {place}: "
        f"Temperature {cw.get('temperature')}°C, "
        f"Wind {cw.get('windspeed')} km/h, "
        f"Weathercode {cw.get('weathercode')}."
    )
    return WeatherResult(
        context_block=block,
        source_urls=["https://open-meteo.com"],
    )
```

### SKILL.md Cloud-Safe Classifications

| Skill | `cloud_safe` | Reason |
|-------|------------|--------|
| `synapse.weather` | `false` | Calls Open-Meteo external API |
| `synapse.reminders` | `true` | Stores data in `~/.synapse/` only |
| `synapse.notes` | `true` | Writes to `~/.synapse/notes/` only |
| `synapse.translate` | `false` | Routes to cloud LLM (translation role) |
| `synapse.summarize` | `false` | Routes to cloud LLM (analysis role) |
| `synapse.web-scrape` | `false` | Fetches external URLs via httpx |
| `synapse.news` | `false` | Fetches external news API |
| `synapse.image-describe` | `false` | Routes to vision-capable cloud LLM |
| `synapse.timer` | `true` | In-process asyncio only |
| `synapse.dictionary` | `false` | Calls dictionaryapi.dev external API |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No bundled skills (fresh install has empty `~/.synapse/skills/`) | `seed_bundled_skills()` copies bundled/ on first boot | Phase 1 (v2.0) — only `skill-creator` seeded | Phase 7 extends seeding to 10 skills |
| SkillManifest has no cloud-safety metadata | `cloud_safe: bool` field in SkillManifest | This phase (v3.0 Phase 7) | SkillRunner can enforce Vault hemisphere isolation |
| All skills load regardless of user preference | `enabled: bool` field — disabled skills skipped by scan_directory | This phase (v3.0 Phase 7) | User can disable any skill without deleting it |
| No namespace convention | `synapse.` prefix for all bundled skills | This phase (v3.0 Phase 7) | Clear separation of core vs. user skills; shadow warnings possible |

**Note on `skill-creator` namespace:** The existing bundled skill is named `skill-creator`, not `synapse.skill-creator`. Phase 7 introduces the `synapse.` convention for the 9 new skills. The existing `skill-creator` is treated as legacy — it is NOT renamed to `synapse.skill-creator` in this phase to avoid breaking any existing users. Only the 9 new skills use the namespace. Document this as a known inconsistency.

---

## Open Questions

1. **Should `skill-creator` be renamed to `synapse.skill-creator`?**
   - What we know: It's the only bundled skill from Phase 1 with no `synapse.` prefix. Renaming would break existing users who have already seeded it.
   - What's unclear: Whether any users have actually deployed the current codebase (pre-release OSS).
   - Recommendation: Leave `skill-creator` as-is for Phase 7. The 9 new skills all use `synapse.` prefix. Address rename in a future cleanup phase.

2. **What namespace prefix do the bundled skill DIRECTORIES use?**
   - What we know: Dots in directory names are valid on all target OSes (Linux, macOS, Windows).
   - What's unclear: Whether `watchdog` handles `synapse.weather/` directory names correctly (dots are valid POSIX directory characters).
   - Recommendation: Use `synapse.weather/` as the directory name. Test that `SkillLoader.scan_directory()` handles it correctly — the existing code uses `entry.is_dir()` which works fine for dotted names. Confidence: HIGH.

3. **How complex should the timer skill be?**
   - What we know: "timer" is listed in SKILL-01. Timer implies scheduling a future notification.
   - What's unclear: Can a timer fire a WhatsApp message without a cron job? The cron infrastructure (Phase 10) doesn't exist yet.
   - Recommendation: Implement `synapse.timer` as a simple "acknowledge and note the time" skill in Phase 7. It records the timer to a lightweight JSON file in `~/.synapse/timers/`. Actual firing requires Phase 10 cron — document this as a known limitation. The skill is functional (it understands timer requests) but the notification delivery is out of scope for Phase 7.

4. **Reminders vs. Timer distinction**
   - What we know: Both `synapse.reminders` and `synapse.timer` are in the 10-skill list.
   - Recommendation: `synapse.reminders` = named reminders (e.g., "remind me to call Mom tomorrow"), stored in `~/.synapse/reminders/`. `synapse.timer` = duration-based countdown (e.g., "set a 10-minute timer"). Both record to disk; neither fires automatically until Phase 10 cron lands.

---

## Sources

### Primary (HIGH confidence)
- Codebase inspection — `workspace/sci_fi_dashboard/skills/schema.py`: frozen dataclass, existing optional fields with defaults confirm correct pattern for adding `cloud_safe`/`enabled`
- Codebase inspection — `workspace/sci_fi_dashboard/skills/loader.py`: `yaml_data.get(field, default)` pattern for all optional fields; `scan_directory` loop with try/except for graceful skip
- Codebase inspection — `workspace/sci_fi_dashboard/skills/registry.py`: `seed_bundled_skills()` iterates `bundled/` dynamically — adding 9 new dirs is auto-discovered with zero code change
- Codebase inspection — `workspace/sci_fi_dashboard/skills/runner.py`: `session_context` parameter already on `execute()` signature; `_execute_skill_creator` shows special-handler pattern; entry_point dispatch shows how `context_block` is used
- Codebase inspection — `.planning/phases/01-VERIFICATION.md`: Confirms 90 tests pass, all 7 SKILL requirements satisfied, all infrastructure verified

### Secondary (MEDIUM confidence)
- Open-Meteo documentation (https://open-meteo.com/en/docs) — free weather API, no key required, JSON responses
- dictionaryapi.dev — free dictionary API, no key, returns definitions/phonetics/examples

### Tertiary (LOW confidence)
- Training knowledge about news APIs (NewsAPI.org requires free key; `newsapi.ai` is paid) — recommendation: use a keyless approach like RSS feeds (https://feeds.reuters.com/reuters/topNews) via httpx + LLM parsing, which requires no key

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in codebase; schema extension pattern verified by existing code
- Architecture: HIGH — seed_bundled_skills already works; namespace convention is a naming decision, not an architectural one
- Pitfalls: HIGH — all identified from direct code inspection of schema.py, loader.py, registry.py, runner.py

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (stable domain; Open-Meteo API is long-lived; core Python/YAML stack is very stable)
