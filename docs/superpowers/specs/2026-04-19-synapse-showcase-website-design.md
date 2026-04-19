# Synapse Showcase Website — Design Spec v2

> **Purpose:** Definitive handover for the dev team building the Synapse product showcase site.
> **Audience:** Website designer/developer + design reviewers.
> **Date:** 2026-04-19
> **Supersedes:** `PRODUCT_SHOWCASE_HANDOVER.md` (develop branch, 2026-04-10) — kept as appendix source material.
> **Status:** Draft for user review.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Design Philosophy](#2-design-philosophy)
3. [Brand Tokens](#3-brand-tokens)
4. [Tech Stack (Locked)](#4-tech-stack-locked)
5. [Reusable Components](#5-reusable-components)
6. [Site Structure](#6-site-structure)
7. [Section 1 — Hero](#section-1--hero)
8. [Section 2 — About / The Problem](#section-2--about--the-problem)
9. [Section 3 — The Brain (Centerpiece)](#section-3--the-brain-centerpiece)
10. [Section 4 — Soul-Brain Sync (SBS)](#section-4--soul-brain-sync-sbs)
11. [Section 5 — Memory System](#section-5--memory-system)
12. [Section 6 — Dual Cognition](#section-6--dual-cognition)
13. [Section 7 — Privacy Vault](#section-7--privacy-vault)
14. [Section 8 — Multi-Channel](#section-8--multi-channel)
15. [Section 9 — Onboarding](#section-9--onboarding)
16. [Section 10 — Tech Stack](#section-10--tech-stack)
17. [Section 11 — Community](#section-11--community)
18. [Section 12 — Footer / CTA](#section-12--footer--cta)
19. [Global Navigation](#13-global-navigation)
20. [Accessibility](#14-accessibility)
21. [Performance Targets](#15-performance-targets)
22. [SEO & Meta](#16-seo--meta)
23. [Dependencies to Add](#17-dependencies-to-add)
24. [Asset Checklist](#18-asset-checklist)
25. [Launch Checklist](#19-launch-checklist)
26. [Open Items — TO CONFIRM](#20-open-items--to-confirm)
27. [Appendix A — Source Material](#appendix-a--source-material)
28. [Appendix B — Animation Reference](#appendix-b--animation-reference)

---

## 1. Executive Summary

**Product:** Synapse — an open-source, self-hosted AI companion with persistent memory, adaptive personality (Soul-Brain Sync), inner-monologue reasoning (Dual Cognition), zero-cloud private vault, and multi-channel messaging (WhatsApp, Telegram, Discord, Slack).

**Site goal:** Convert visitors into installers. The only real CTA is **`npm install synapse`** (command is in progress — see Open Items) and the GitHub repo. No email capture, no waitlist, no pricing. Install-first, OSS-native.

**Hero message:** *A brain that **remembers**.* Italic on "remembers" (Instrument Serif italic). The brain is the hero metaphor — everything else is anatomy.

**Tone arc:** Emotion → Technical credibility → Onboarding.
The first three sections hook on feelings (amnesiac AIs are cold; Synapse isn't). Mid-sections earn credibility through architecture (SBS 8-layer profiles, Dual Cognition split-streams, hybrid RAG). Closing sections deliver install and community.

**Visual strategy:** 100% custom animations. No AI-generated video, no real product footage, no stock. Every moving pixel is built in React + framer-motion + SVG/Canvas. This guarantees brand consistency, zero licensing, and signature "only Synapse looks like this" identity — at the cost of significant dev time.

**Design language:** Inherited from the existing template. `bg-black` throughout, Instrument Serif for display text, liquid-glass surfaces for every card/pill/button, framer-motion scroll reveals. One signature accent color — electric cyan `#00E5FF` — used sparingly for neural firings, active states, tension indicators.

---

## 2. Design Philosophy

### The Brain is the Hero
Synapse's marketable difference from ChatGPT/Gemini/Copilot is not "another LLM wrapper." It's that Synapse has a **brain** — one that remembers, learns style, reasons about you, splits private from public, and reaches you on every channel. The site must make this brain legible. Not with stock "AI brain" imagery — with custom anatomy the visitor can explore.

### Three Brain Pillars
Every feature maps to one of three brain regions. Use this ontology throughout copy and visuals:

| Pillar | Brain Region | Features |
|---|---|---|
| **Soul** | Personality | SBS (8-layer profile), implicit feedback detection, YAML patterns |
| **Cortex** | Memory | Hybrid RAG, knowledge graph, LanceDB ANN, FlashRank |
| **Inner Voice** | Reasoning | Dual Cognition, tension scoring, response strategy |

Supporting systems (Privacy Vault, Multi-Channel, Traffic Cop) wrap around this trio.

### Motion as Meaning
Every animation must answer: *what concept is this teaching?* No decorative motion.

- Neural pulses = the brain is alive and firing.
- Radar fills = SBS learning over time.
- Graph nodes lighting = memory retrieval in action.
- Split-screen merges = Present + Memory → Response strategy.
- Hemisphere toggle = public vs private split.
- Channel icons converging = one brain, every platform.

Reference: [motionsites.ai](https://motionsites.ai) — we want their level of *deliberate* motion, not their specific animations.

### Monochrome Discipline + Cyan Accent
The template is pure monochrome. Keep it that way, except for **electric cyan `#00E5FF`** used exclusively for:
- Neural firing pulses
- Active/hover states on interactive viz
- Tension meter "high" indicator
- "Thinking" loading dots
- Install command syntax highlight (optional)

Cyan must feel earned. If a cyan element doesn't connote "active neural activity," it's wrong.

---

## 3. Brand Tokens

### Colors

```css
/* tailwind.config.js — extend.colors */
colors: {
  ink: '#000000',          /* bg */
  bone: '#FFFFFF',         /* text */
  ghost: {
    90: 'rgba(255,255,255,0.90)',
    70: 'rgba(255,255,255,0.70)',  /* body */
    50: 'rgba(255,255,255,0.50)',  /* secondary */
    40: 'rgba(255,255,255,0.40)',  /* labels */
    10: 'rgba(255,255,255,0.10)',  /* dividers */
    05: 'rgba(255,255,255,0.05)',  /* hover bg */
    01: 'rgba(255,255,255,0.01)',  /* liquid-glass base */
  },
  neural: {
    DEFAULT: '#00E5FF',    /* cyan accent */
    dim: 'rgba(0,229,255,0.40)',
    glow: 'rgba(0,229,255,0.20)',
  },
}
```

### Typography

```css
/* index.css */
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap');

/* Usage */
.font-display { font-family: 'Instrument Serif', serif; }   /* hero, section headings */
.font-body    { font-family: 'Inter', system-ui; }          /* all body, UI */
.font-mono    { font-family: 'JetBrains Mono', monospace; } /* code, commands, terminal */
```

Hierarchy:
- **Display (hero):** Instrument Serif, `text-7xl md:text-8xl lg:text-9xl`, white, `tracking-tight whitespace-nowrap`.
- **Section heading:** Instrument Serif, `text-5xl md:text-7xl lg:text-8xl`, white, `tracking-tight`. One word italic for emphasis (pattern locked: `I <em>remember</em> you.`).
- **Sub-heading / label:** Inter, `text-xs md:text-sm`, `tracking-widest uppercase`, `text-ghost-40`.
- **Body:** Inter, `text-base md:text-lg`, `text-ghost-70`, `leading-relaxed`.
- **Mono (code/terminal):** JetBrains Mono, `text-sm`, `text-ghost-90` on `bg-ghost-05`.

### Spacing

Use the template's existing rhythm: `py-28 md:py-40` for sections, `px-6` for mobile gutters, `max-w-6xl mx-auto` for content width (except the hero which is full-viewport). Cards use `p-6 md:p-8` inside; `rounded-2xl` for cards, `rounded-3xl` for video/viz containers, `rounded-full` for pills and buttons.

### Motion Principles

All section reveals use `framer-motion` `useInView` with `{ once: true, margin: "-100px" }`. Standard timings:

```ts
// Section reveal defaults
const revealFade     = { initial:{opacity:0, y:40}, animate:{opacity:1, y:0}, transition:{duration:0.8, ease:[0.22,1,0.36,1]} };
const revealFadeFast = { initial:{opacity:0, y:20}, animate:{opacity:1, y:0}, transition:{duration:0.6, ease:[0.22,1,0.36,1]} };
const revealSlideL   = { initial:{opacity:0, x:-40}, animate:{opacity:1, x:0}, transition:{duration:0.9, ease:[0.22,1,0.36,1]} };
const revealSlideR   = { initial:{opacity:0, x:40},  animate:{opacity:1, x:0}, transition:{duration:0.9, ease:[0.22,1,0.36,1]} };
const staggerChild   = { delayChildren:0.15, staggerChildren:0.12 };
```

Easing: custom cubic-bezier `[0.22, 1, 0.36, 1]` — smooth ease-out, feels expensive.

Interactive states:
- `whileHover={{ scale: 1.03 }}` on cards
- `whileHover={{ scale: 1.05 }}` on buttons
- `whileTap={{ scale: 0.95 }}` on buttons
- Cyan glow on hover via `box-shadow` transition (see component specs)

Never use linear easing. Never use durations <0.3s for reveals (too snappy). Never use >1.2s for reveals (feels sluggish).

### Liquid-Glass (inherited)

Keep the `.liquid-glass` class from the existing template exactly as-is. Use it on every card, pill, and raised surface.

---

## 4. Tech Stack (Locked)

Inherited from existing template — do not change:

- **React 18+** with TypeScript
- **Vite** (build tool)
- **Tailwind CSS** (utility styling, `@layer components` for liquid-glass)
- **framer-motion** (all animations)
- **lucide-react** (icons)

Add for this project:

- **@react-three/fiber** + **three** — for the 3D brain viz in Section 3 (optional; SVG+Canvas fallback is acceptable)
- **react-intersection-observer** — if framer-motion's `useInView` needs supplementing
- **@vercel/analytics** or **umami** — privacy-friendly analytics (pick one; see Open Items)

Deploy target: **Vercel** or **Cloudflare Pages** — both support Vite + Edge. [TO CONFIRM]

---

## 5. Reusable Components

Build these first, then assemble sections from them. All TypeScript, all accept `className` for one-off overrides.

### 5.1 `<LiquidGlassCard>`
```tsx
interface Props { children: ReactNode; className?: string; interactive?: boolean }
// Wraps children in .liquid-glass rounded-3xl, optional whileHover scale when interactive
```

### 5.2 `<LiquidGlassPill>`
```tsx
interface Props { children: ReactNode; as?: 'button' | 'a' | 'div'; href?: string; onClick?: () => void; size?: 'sm'|'md'|'lg' }
// .liquid-glass rounded-full with size-driven px/py
```

### 5.3 `<SectionLabel>`
```tsx
interface Props { children: string }
// text-ghost-40 text-xs md:text-sm tracking-widest uppercase mb-4
```

### 5.4 `<DisplayHeading>`
```tsx
interface Props { children: ReactNode; size?: 'hero'|'section' }
// Instrument Serif, tracking-tight, sized by prop
// Supports <em> children for italic emphasis
```

### 5.5 `<CyanPulse>` — neural firing dot
```tsx
interface Props { x: number; y: number; delay?: number; size?: number }
// Absolute-positioned dot, animate: scale 0→1→0.6, opacity 0→1→0, duration 1.6s, repeat: Infinity
// Cyan center, cyan-glow box-shadow
```
Used in: Section 3 (Brain), Section 5 (Memory graph), Section 6 (Dual Cognition merge point), hover states throughout.

### 5.6 `<TypingTerminal>` — simulated terminal
```tsx
interface Props {
  lines: TerminalLine[];       // { prompt?: string, text: string, pauseAfter?: number, color?: 'default'|'muted'|'cyan'|'success' }
  charDelay?: number;          // ms per char, default 30
  lineDelay?: number;          // ms between lines, default 400
  loop?: boolean;              // default false
  startOnView?: boolean;       // default true (starts when scrolled into view)
}
// Liquid-glass card, JetBrains Mono text, blinking block cursor at end of current line
// Cyan prompt symbol ($), ghost-90 command text, ghost-50 output, success=green-400 (sparingly)
```
Used in: Section 9 (Onboarding) — the centerpiece.

### 5.7 `<KnowledgeGraphViz>`
```tsx
interface Props { nodes: Node[]; edges: Edge[]; highlightPath?: string[]; autoPulse?: boolean }
// SVG-based. Nodes = circles (bone fill, cyan on active). Edges = curved lines (ghost-10, neural on active).
// On autoPulse: randomly light up a node → cascade along edges → fade out (1.5s per pulse, 2s between pulses)
// On highlightPath: light up specific sequence of nodes in order (for "query in action" demo)
```
Used in: Section 5 (Memory).

### 5.8 `<NeuralBrain>` — centerpiece brain viz
```tsx
interface Props { activeRegion?: 'soul'|'cortex'|'innervoice'|null; onRegionHover?: (r: string) => void }
// SVG or R3F. Three labeled lobes. Each lobe has cluster of CyanPulse dots firing.
// On region hover/tap: lobe brightens, label appears, pulse density increases 3x, other lobes dim
// Idle state: slow random pulses across all three, subtle rotation (if R3F) or subtle translate (if SVG)
```
Used in: Section 3 (The Brain) — the hero of the page.

### 5.9 `<SBSRadarChart>`
```tsx
interface Props { values: number[8]; labels: string[8]; animate?: boolean; animateFromZero?: boolean }
// 8-axis radar using SVG. Lines = ghost-10. Axis labels = ghost-50 text-xs.
// Active polygon = cyan stroke + cyan-glow fill 0.15 opacity.
// If animateFromZero: values start at 0 and tween to target on view (duration 2.5s, ease-out)
```
Used in: Section 4 (SBS).

### 5.10 `<SplitStreamMerge>` — Dual Cognition viz
```tsx
// Two panels side-by-side (stacked on mobile), each streaming text downward (Present vs Memory).
// On interval: a "thought" leaves each panel and meets in the center.
// Merge point = cyan pulse burst, then outputs a single "response strategy" card below.
// Loops with different example content (3-4 scenarios).
```
Used in: Section 6 (Dual Cognition).

### 5.11 `<HemisphereToggle>` — Privacy Vault viz
```tsx
interface Props { mode: 'safe'|'spicy'; onToggle: (m: 'safe'|'spicy') => void }
// Two-sided card: left = "Cloud (Safe)" with cloud icon + OpenAI/Anthropic/Gemini logos in ghost-40
//                 right = "Local (Spicy)" with lock icon + Ollama badge in cyan
// Toggle slides a liquid-glass divider. Active side = cyan-lit border. Inactive = dimmed.
// Caption below updates: "Hemisphere: safe → cloud LLMs" vs "Hemisphere: spicy → local Ollama only"
```
Used in: Section 7 (Privacy Vault).

### 5.12 `<ChannelConverge>`
```tsx
// Four channel icons (WhatsApp, Telegram, Discord, Slack) arranged in a circle around a central brain icon.
// Each icon emits a cyan line toward the brain, pulsing inward sequentially.
// On brain-hit: brain icon flashes cyan, lines fade.
// Loops every 3.5s with staggered channel lighting (0.2s offset per channel).
```
Used in: Section 8 (Multi-Channel).

### 5.13 `<ArchitectureDiagram>`
```tsx
interface Props { highlightLayer?: 'channel'|'gateway'|'worker'|'engine'|'llm'|null }
// Static SVG stack: Channel Layer → Gateway (FloodGate/Dedup/Queue) → Workers → Engine (SBS/DualCog/Memory) → LLM Router
// Hover a layer → cyan highlight + tooltip with brief description
```
Used in: Section 10 (Tech Stack).

### 5.14 `<CyanPulseButton>` — primary CTA
```tsx
interface Props { children: ReactNode; href: string; prominent?: boolean }
// Base: liquid-glass rounded-full px-8 py-3, white text
// prominent=true adds cyan glow ring via animated box-shadow (opacity 0.2→0.5→0.2, duration 2.4s, loop)
// On hover: ring intensifies, scale 1.03
```
Used for: install command button, GitHub button (prominent variant sparingly).

---

## 6. Site Structure

Single-page scroll with 12 sections. Sticky navbar stays glass through scroll. Footer is section 12. No modal overlays. No pop-ups. No cookie banner unless legally required (Vercel/CF analytics in privacy mode shouldn't trigger one).

```
┌─────────────────────────────────────┐
│  Navbar (sticky, liquid-glass pill) │
├─────────────────────────────────────┤
│  1. Hero                            │  full viewport, neural bg
│  2. About / The Problem             │
│  3. The Brain (centerpiece)         │  ← the hero section
│  4. SBS                             │
│  5. Memory                          │
│  6. Dual Cognition                  │
│  7. Privacy Vault                   │
│  8. Multi-Channel                   │
│  9. Onboarding                      │
│  10. Tech Stack                     │
│  11. Community                      │
│  12. Footer / CTA                   │
└─────────────────────────────────────┘
```

Navbar links scroll to anchors: `#brain`, `#sbs`, `#memory`, `#cognition`, `#vault`, `#channels`, `#install`. "Docs" and "GitHub" are external.

---

## Section 1 — Hero

**ID:** `#hero`
**Goal:** Stop the scroll. Plant the "brain that remembers" idea. Deliver install command within 3 seconds of decision.

### Layout
Full-viewport (`min-h-screen`), `overflow-hidden relative flex flex-col`.

### Background — Custom Neural Animation (replaces template's video)
Full-bleed absolute Canvas or SVG element (`absolute inset-0 w-full h-full`).

**What it shows:** A slowly rotating field of ~200 cyan-tinted neural points connected by faint ghost-10 edges. Points pulse to cyan at random intervals; cascade of 3-5 connected points fires every 2-3 seconds, like thought patterns forming and dissolving.

**Tech:** React Three Fiber (preferred) for depth, or Canvas 2D for simpler perf. SVG is acceptable but may struggle with 200+ elements.

**Perf budget:** 60fps on a MacBook Air M1 / mid-tier Windows laptop. If FPS drops, halve point count. Pause animation when `document.hidden` is true.

**Behavior:** Starts at opacity 0. Fades in over 600ms on mount. Never stops (no loop seams). On scroll out of hero, fades to 0 over 300ms.

### Navbar (inherited from template)
Replace text "Asme" with "Synapse" and swap Globe icon for a custom **synapse/brain logomark** (see Open Items — logomark TBD; placeholder: use `Brain` from lucide-react initially).

Links: `Features` → `#brain`, `Docs` → external, `GitHub` → external.

Right-side: Remove "Sign Up" entirely. Replace "Login" with `<CyanPulseButton href="#install" prominent>Install</CyanPulseButton>`.

### Hero Content Block
`relative z-10 flex-1 flex flex-col items-center justify-center px-6 py-12 text-center -translate-y-[20%]`

```tsx
<DisplayHeading size="hero">
  A brain that <em>remembers</em>.
</DisplayHeading>

<p className="mt-8 text-ghost-70 text-base md:text-lg max-w-xl mx-auto leading-relaxed">
  Synapse is a self-hosted AI companion with persistent memory,
  adaptive personality, and zero cloud leakage for your private conversations.
  Talks to you on WhatsApp, Telegram, Discord, and Slack.
</p>

<div className="mt-10 w-full max-w-xl">
  <InstallCommandPill command="npm install synapse" />    {/* TODO: confirm exact command */}
</div>

<div className="mt-6 flex gap-3">
  <LiquidGlassPill href="#brain" as="a">Explore the brain ↓</LiquidGlassPill>
  <LiquidGlassPill href="https://github.com/UpayanGhosh/Synapse-OSS" as="a">Star on GitHub</LiquidGlassPill>
</div>
```

### `<InstallCommandPill>` spec
Replaces the template's email input. Same outer shape (`liquid-glass rounded-full pl-6 pr-2 py-2 flex items-center gap-3`).

- Left: `$` prompt in cyan, followed by the command text in `font-mono text-ghost-90`.
- Right: copy-to-clipboard button (white circular, `bg-white rounded-full p-3`), contains `Copy` icon (lucide). On click: copy, swap icon to `Check` in cyan for 1.5s, toast "Copied" at bottom.

### Social/Footer Row (inherited, adapted)
Remove Instagram. Keep Twitter, Globe. Add **GitHub** and **Discord** icons.

### Motion
- Neural background: as described above.
- Heading: opacity 0 → 1, y: 30 → 0, duration 1.0s, delay 0.2s.
- Sub-copy: same, delay 0.5s.
- Install pill: same, delay 0.7s.
- CTA row: same, delay 0.9s.
- Social row: opacity 0 → 1, duration 0.6, delay 1.1s.

### Responsive
- `<768px`: heading `text-6xl` whitespace-normal (wraps), install command pill full-width, CTA buttons stack vertically.
- Neural background: reduce point count to 100 on mobile.

### Copy variants (for A/B later — not launch)
- A: "A brain that *remembers*."
- B: "Your *second* mind."
- C: "AI that *knows* you."

Launch with A.

---

## Section 2 — About / The Problem

**ID:** `#about`
**Goal:** Frame the problem so the rest of the site feels inevitable. Establish emotional stakes.

### Layout
`bg-black pt-32 md:pt-44 pb-16 md:pb-24 px-6 overflow-hidden max-w-6xl mx-auto`.
Subtle radial gradient overlay at top: `bg-[radial-gradient(ellipse_at_top,_rgba(0,229,255,0.04)_0%,_transparent_70%)]`. Cyan tint, very low opacity.

### Copy

```tsx
<SectionLabel>The problem</SectionLabel>

<DisplayHeading size="section">
  Every new AI model <em>forgets</em> you.
</DisplayHeading>

<div className="mt-12 max-w-3xl space-y-6 text-ghost-70 text-lg md:text-xl leading-relaxed">
  <p>
    You tell ChatGPT you're a backend engineer who hates writing CSS.
    Three months later, a new model launches. You open a fresh chat.
    It's polite. Friendly. And completely blank.
  </p>
  <p>
    Your AI relationships shouldn't reset every release cycle.
    The personality, memory, and style you built over months
    should belong to <em className="text-bone">you</em> — not to a cloud provider's roadmap.
  </p>
  <p className="text-bone">
    Synapse is the middleware between you and every AI.
    A brain that remembers, across every model, forever.
  </p>
</div>
```

### Visual
No full-width video here (template pattern). Instead: a **persistent-state diagram** at right side on desktop — two columns showing "ChatGPT Thread 2024" (fades to black after) vs "Synapse Memory" (stays lit, pulses with cyan). Column divider animates from full-height to the middle over 2.5s as user scrolls.

Dev: build as 2-column SVG with `framer-motion` animating the divider and the "ChatGPT" column's opacity. Stacks vertically on mobile.

### Motion
- Label: revealFadeFast (see Motion Principles).
- Heading: revealFade, delay 0.1s.
- Paragraphs: stagger children, 0.15s per paragraph, each revealFadeFast.
- Diagram: on view, divider animates over 2.5s.

### CTA
None in this section. Emotional build only.

---

## Section 3 — The Brain (Centerpiece)

**ID:** `#brain`
**Goal:** Make the brain metaphor concrete. Introduce the three pillars. Make visitors want to explore.

### Layout
`bg-black py-28 md:py-40 px-6 overflow-hidden max-w-6xl mx-auto`.
Subtle radial from center: `bg-[radial-gradient(ellipse_at_center,_rgba(0,229,255,0.06)_0%,_transparent_60%)]`.

### Header

```tsx
<SectionLabel>The anatomy</SectionLabel>

<DisplayHeading size="section">
  Meet the <em>brain</em>.
</DisplayHeading>

<p className="mt-8 max-w-2xl text-ghost-70 text-lg leading-relaxed">
  Most AIs are stateless text generators in a trench coat.
  Synapse has three working organs: a soul that adapts to you,
  a cortex that remembers, and an inner voice that thinks before it speaks.
</p>
```

### Centerpiece — `<NeuralBrain>` viz
Large, ~`aspect-[4/3]` container centered below the intro. Three labeled lobes arranged in a loose triangle:
- **Soul** (top-left) — personality layer
- **Cortex** (top-right) — memory
- **Inner Voice** (bottom-center) — reasoning

Idle state: each lobe has 15-25 CyanPulse dots firing randomly at ~1 per second per lobe. Subtle rotation/drift of ~3° over 8s (SVG `transform` animation).

Interactive: on hover/tap of a lobe → that lobe's pulses intensify (3x rate, cyan bloom behind), other lobes dim to 30% opacity, label appears next to active lobe with a 1-sentence description:

- **Soul**: "Your style, learned — not configured."
- **Cortex**: "Memory that connects the dots."
- **Inner Voice**: "It doesn't just respond. It thinks."

### Three Pillar Cards (below centerpiece)
3-column grid (`grid-cols-1 md:grid-cols-3 gap-6`). Each card = `<LiquidGlassCard interactive>`.

```tsx
{[
  {
    label: 'Soul',
    title: 'Soul-Brain Sync',
    body: 'An 8-layer behavioral profile. Learns your vocabulary, formality, preferred length, emotional triggers — without a settings page.',
    link: '#sbs',
    icon: <Sparkles className="w-6 h-6 text-neural" />,
  },
  {
    label: 'Cortex',
    title: 'Hybrid Memory',
    body: 'Vector search + full-text + knowledge graph + neural reranker. Retrieves the right context in under 350ms.',
    link: '#memory',
    icon: <Database className="w-6 h-6 text-neural" />,
  },
  {
    label: 'Inner Voice',
    title: 'Dual Cognition',
    body: 'Two parallel thought streams merge before every reply: what you\'re saying now vs what it knows about you.',
    link: '#cognition',
    icon: <Brain className="w-6 h-6 text-neural" />,
  },
].map(pillar => <PillarCard {...pillar} />)}
```

Each card: label top-left (`SectionLabel`), icon top-right, title (Instrument Serif `text-3xl`), body (`text-ghost-70`), "Learn more →" link at bottom. Hover: card lifts 4px, cyan border glow intensifies.

### Motion
- Header: revealFade.
- Centerpiece brain: fades in with revealFadeFast over 1.0s after view. Internal pulses begin after fade completes.
- Pillar cards: staggered reveal (0.15s between), each revealFade.
- On scroll-linked parallax: the brain slowly rotates an additional 8° as section scrolls through viewport (framer-motion `useScroll` + `useTransform`).

---

## Section 4 — Soul-Brain Sync (SBS)

**ID:** `#sbs`
**Goal:** Prove the "Soul" claim with architecture depth. Show the 8 layers filling in over time.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Soul — the personality layer</SectionLabel>

<DisplayHeading size="section">
  Your style, <em>learned</em> — not configured.
</DisplayHeading>

<p className="mt-8 max-w-2xl text-ghost-70 text-lg">
  By message #50, Synapse knows your vocabulary, formality, emoji habits,
  and emotional triggers. Say "too long" once — it adjusts permanently.
  No settings page. No prompt engineering. Just you, talking normally.
</p>
```

### Visual — 2-column layout

**Left column:** `<SBSRadarChart animate animateFromZero>`. 8-axis radar filling from center outward over 2.5s on view. Axes labeled with the 8 layer names (see below).

**Right column:** animated conversation playback — a liquid-glass card simulating a WhatsApp-style chat thread. Messages appear one at a time (1.2s each). After each message, a tiny cyan pulse flies from the message into the radar chart and the corresponding axis grows. Sequence:

1. User: "hey u up?" → *Linguistic* (casual register) + *Interaction* (short-form preference) grow.
2. User: "wanted to push the backend fix, the one we discussed yday" → *Domain* (backend) + *Vocabulary* (project-specific terms) grow.
3. User: "bruhhh this is too long 😂" → *Linguistic* (emoji habit, Banglish-ish) + *Interaction* (prefers short) grow.
4. User: "celebrate with pizza tonight?" → *Emotional State* (positive baseline) + *Exemplars* (captured as a reference example) grow.

Loops every ~15s with a subtle reset.

**Below both columns:** a tidy grid (2 rows × 4 cols) of the 8 layers with icons and one-line descriptions. **Names match the actual profile layers in the code** (`sbs/profile/manager.py`):

| # | Layer (code name) | One-liner |
|---|---|---|
| 1 | Core Identity | Your name, the bot's name, personality pillars, relationship frame |
| 2 | Linguistic | Formality, vocabulary complexity, language-mix ratio |
| 3 | Emotional State | Mood baseline, trigger map, 72h peak-end trajectory |
| 4 | Domain | Topics where you expect depth |
| 5 | Interaction | Response length preference, question format, emoji habit |
| 6 | Vocabulary | Signature phrases, preferred terminology |
| 7 | Exemplars | Few-shot example exchanges in your voice |
| 8 | Meta | Layer versioning, last-updated timestamps, confidence scores |

### Dev detail callout card
Small liquid-glass card at bottom-right: `BatchProcessor distills profiles every 50 messages. YAML-configurable feedback patterns at sbs/feedback/language_patterns.yaml. Profiles survive model switches.` — keeps dev audience bought in.

### Motion
- Header: revealFade.
- Left (radar): `revealSlideL`, then radar fills from zero over 2.5s.
- Right (chat): `revealSlideR`, messages stream in sequentially.
- 8-layer grid: staggerChildren, each revealFadeFast.

---

## Section 5 — Memory System

**ID:** `#memory`
**Goal:** Show the "Cortex" — hybrid retrieval in action. Make the graph beautiful.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Cortex — the memory layer</SectionLabel>

<DisplayHeading size="section">
  Memory that <em>connects</em> the dots.
</DisplayHeading>

<p className="mt-8 max-w-3xl text-ghost-70 text-lg">
  Synapse doesn't just store facts — it understands relationships.
  Vector search, full-text indexing, knowledge graph traversal, and
  neural reranking combine to find the right context in under 350 milliseconds.
  Your AI knows that Alice is your colleague, Bob is her husband,
  and you met them both at a conference in 2024.
</p>
```

### Visual — `<KnowledgeGraphViz>`
Center of section, ~`aspect-[16/10]` container. Pre-seeded graph with ~15 nodes:

```
User ─ works_at ─ Acme
  │
  ├─ knows ─ Alice ─ married_to ─ Bob
  │             │
  │             └─ attended ─ "2024 Conference" ─ in_city ─ Berlin
  │
  ├─ owns ─ "Labrador" ─ named ─ Max
  └─ lives_in ─ Brooklyn
```

Idle: nodes are ghost-40 circles, edges are ghost-10 curved lines. Every 3s, a random node pulses cyan and the pulse cascades along 2-3 connected edges. On hover of any node, that node and its 1-hop neighbors light up, edge labels appear.

Scripted demo overlay — "Query in action":
A liquid-glass caption strip below the graph scrolls through queries, and for each one the graph highlights the traversal path in cyan:

1. `"Remind me about Alice"` → User → knows → Alice (2-hop)
2. `"What was Alice's husband's name?"` → User → knows → Alice → married_to → Bob (4-hop)
3. `"Who did I meet in Berlin?"` → Berlin → in_city → "2024 Conference" → attended (reverse) → Alice (4-hop)

Each query: cyan line pulses along the path left-to-right, then fades. Loops.

### Side rail — retrieval pipeline
Small column at right on desktop (hidden on mobile, moved below on tablet):

```
Query
  │
  ├─ Embed (Ollama nomic-embed / FastEmbed)
  │
  ├─ Vector search (LanceDB)
  ├─ Full-text search (SQLite FTS5)
  ├─ Graph traversal (SQLiteGraph)
  │
  ├─ Rerank (FlashRank cross-encoder)
  │
  └─ Top-K context
```

Each step is a small liquid-glass pill. On scroll, lights up top-to-bottom (stagger 0.2s).

### Motion
- Header: revealFade.
- Graph: revealFadeFast, internal scripting starts after fade.
- Side rail: staggered pills, scripted alongside the graph demo.

---

## Section 6 — Dual Cognition

**ID:** `#cognition`
**Goal:** Sell the "Inner Voice" — prove this isn't another LLM wrapper. Use the worked example.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Inner voice — the reasoning layer</SectionLabel>

<DisplayHeading size="section">
  It doesn't just respond. It <em>thinks</em>.
</DisplayHeading>

<p className="mt-8 max-w-3xl text-ghost-70 text-lg">
  Before every reply, Synapse runs two parallel thought streams —
  "what are they saying right now?" and "what do I know about this person?"
  They merge to detect tension, alignment, or contradiction, producing
  an inner monologue and a response strategy. The AI reasons about you
  before speaking.
</p>
```

### Visual — `<SplitStreamMerge>`
Big container, `aspect-[16/9]` on desktop. Two liquid-glass columns side-by-side separated by a vertical divider that glows cyan at the midpoint.

**Left column (Present Stream):** label "Present Stream" top, currently-incoming user message displayed, below it metadata filling in as it's "analyzed":
```
sentiment: positive ✓
intent: announcement ✓
topics: [career, transition] ✓
emotional: excited ✓
```

**Right column (Memory Stream):** label "Memory Stream" top, retrieved context loads in:
```
recalling relevant memories...
• "Mentioned job search 3 weeks ago"
• "Expressed anxiety about interviews"
• "Referred to 'the Stripe role' on 2026-03-28"
```

**Center merge point:** once both streams finish (~3s), cyan energy pulses from both sides meet in the middle. Burst animation. A result card drops below:

```
Inner monologue:
"They got the Stripe role. Last time this came up,
 they were nervous. Time to celebrate and reassure."

Tension level:     ▓▓▓▓░░░░░░  0.4
Response strategy: celebrate + reassure
```

Tension meter fills left-to-right in cyan. Strategy pill has subtle cyan glow.

**Rotating scenarios:** Cycle through 3-4 worked examples every 10s:
1. **New job announcement** (above) — positive event + past anxiety = celebrate + reassure
2. **Rant about coworker** — high negative sentiment + known context ("mentioned this person before") = validate + de-escalate
3. **Late-night philosophical question** — low energy + unusual topic + temporal (2am) = go deep, skip the cheer
4. **Simple factual query** — no tension + known domain = direct answer, skip strategy

A small caption strip below identifies which scenario is running.

### Dev callout
Small liquid-glass strip below viz: `Complexity classifier (fast / standard / deep), 5s configurable timeout, pre-cached memory (zero double query), tension scoring 0.0-1.0.`

### Motion
- Header: revealFade.
- Split columns: left revealSlideL, right revealSlideR, simultaneous.
- Merge animation: scripted, runs continuously after entry.

---

## Section 7 — Privacy Vault

**ID:** `#vault`
**Goal:** Convert the privacy-concerned. Make the split physical.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Privacy vault</SectionLabel>

<DisplayHeading size="section">
  Private stays <em>private</em>. Period.
</DisplayHeading>

<p className="mt-8 max-w-3xl text-ghost-70 text-lg">
  Synapse splits memory into two hemispheres — Safe (shareable) and Spicy (private).
  Private content routes <em>exclusively</em> to local Ollama models.
  Not a UI toggle. A database-level guarantee — enforced at the SQL WHERE clause.
  Your private conversations never touch OpenAI, Anthropic, or Google.
</p>
```

### Visual — `<HemisphereToggle>`
2-panel split display. Left = "Cloud (Safe)" with subtle ghost-40 logos of GPT/Claude/Gemini. Right = "Local (Spicy)" with lock icon + Ollama badge in cyan. A center toggle switches the active hemisphere. Behind each panel: faint neural pattern (cloud panel = conventional, local panel = denser + cyan-tinted).

Below: a code snippet card (liquid-glass, mono font) showing the SQL enforcement:

```sql
SELECT * FROM documents
WHERE hemisphere_tag = ?    ← bound at query time, not filtered in Python
  AND embedding MATCH ?
```

Caption: "One WHERE clause. Zero leakage. Enforced in SQL, not in code — because code can be bypassed."

### Motion
- Header: revealFade.
- Hemisphere panels: left revealSlideL, right revealSlideR.
- Code snippet: revealFade, delay 0.4s.
- On toggle interaction: 0.4s crossfade between hemisphere styles + caption updates.

---

## Section 8 — Multi-Channel

**ID:** `#channels`
**Goal:** Prove "one brain, every platform." Visual convergence metaphor.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Reach</SectionLabel>

<DisplayHeading size="section">
  One brain. <em>Every</em> channel.
</DisplayHeading>

<p className="mt-8 max-w-3xl text-ghost-70 text-lg">
  Shared memory across WhatsApp, Telegram, Discord, and Slack.
  Text it from Signal at 2am, ask about it on Discord the next day —
  same context, same tone, same brain.
</p>
```

### Visual — `<ChannelConverge>`
Centered, `aspect-[16/9]`. Four channel icons (WhatsApp green, Telegram blue, Discord purple, Slack magenta — but rendered monochrome ghost-40 on idle) arranged at compass points around a central brain icon.

Every 3.5s, each channel icon pulses cyan in turn (staggered 0.2s), sending a cyan line toward the center brain. On contact, brain flashes cyan, all lines fade, loop restarts.

Below: 4 small liquid-glass cards, one per channel, with a sample message and "via [channel]" tag:

- **WhatsApp**: "`Baileys` bridge — zero Meta business API needed. Works with personal numbers."
- **Telegram**: "`python-telegram-bot` — long-polling, no webhook setup."
- **Discord**: "`discord.py` — bot token + server install."
- **Slack**: "`slack_bolt` — socket mode, no public URL needed."

### Motion
- Header: revealFade.
- Viz: revealFadeFast, internal animation starts after.
- Channel cards: staggerChildren, each revealFadeFast.

---

## Section 9 — Onboarding

**ID:** `#install`
**Goal:** Convert to install. Zero friction. Show that install is 5 minutes flat.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-4xl mx-auto`. Narrower than other sections to focus attention.

### Copy

```tsx
<SectionLabel>Installation</SectionLabel>

<DisplayHeading size="section">
  Running in <em>five minutes</em>.
</DisplayHeading>

<p className="mt-8 text-ghost-70 text-lg">
  macOS, Linux, or Windows. Python 3.11+. That's it.
  Everything else — embeddings, LLM routing, databases —
  gets bootstrapped by the onboarding wizard.
</p>
```

### Visual — `<TypingTerminal>` (centerpiece)
Large liquid-glass terminal card, `aspect-[4/3]` or fixed height ~`h-[520px]`, JetBrains Mono text. Types out the full install flow with realistic timing. Scripted lines:

```
$ npm install synapse              ← [TO CONFIRM — exact command]
  ✓ installed synapse v1.0.0 (packages: 42, 18MB)

$ synapse onboard --flow quickstart
  [1/5] Validating environment...       ✓ Python 3.11.7, 16GB RAM
  [2/5] Installing core dependencies... ✓ FastEmbed ready (100MB)
  [3/5] Creating synapse.json...        ✓ config at ~/.synapse/
  [4/5] Configuring LLM provider...
    ? Pick default provider: (use arrow keys)
    > Gemini (recommended — free tier)
      Claude
      OpenAI
      Ollama (local only)
  [5/5] Connecting channels...          ✓ ready

  🧠 Synapse is running at http://localhost:8000
  Docs: https://synapse-oss.dev/docs
```

Timing: ~30-40s to play through once. Loops with a 4s pause between runs. Optional pause-on-hover for visitor to read.

Cursor blink at end of current line (`animate-pulse` or framer-motion opacity loop).

### Alternative install paths (below terminal)
3-column grid of liquid-glass cards:

```tsx
{[
  {
    title: 'Advanced Wizard',
    body: 'Full 30-minute setup with all channels, MCP servers, voice, and vault.',
    cmd: 'synapse onboard --flow advanced',
  },
  {
    title: 'Docker',
    body: 'Containerized — preconfigured image for homelabs and servers.',
    cmd: 'docker run -p 8000:8000 synapse-oss/synapse:latest',
  },
  {
    title: 'From source',
    body: 'Clone the repo, hack on the brain.',
    cmd: 'git clone https://github.com/UpayanGhosh/Synapse-OSS',
  },
].map(path => <InstallCard {...path} />)}
```

Each card = liquid-glass, title (Instrument Serif), body text, mono command at bottom with copy button.

### Setup Checklist (below install cards)
Liquid-glass checklist showing what to do in your first 10 minutes. Visual: vertical list, cyan checkmark in front of each.

```
✓  Install: npm install synapse
✓  Run the wizard: synapse onboard --flow quickstart
□  Ingest your Day-1 facts (name, location, role) via the onboarding prompts
□  Connect WhatsApp (optional — pairing QR in terminal)
□  Say hi: curl -X POST http://localhost:8000/chat/the_creator -H 'Content-Type: application/json' -d '{"message":"hi"}'
□  Chat normally for 2-3 days — the brain starts remembering.
□  Optional: customize your persona in workspace/personas.yaml
```

### Motion
- Header: revealFade.
- Terminal: revealFadeFast, typing starts after entry.
- Install cards: staggerChildren.
- Checklist: staggerChildren, cyan check fade-in.

### CTA
At bottom of section, one big `<CyanPulseButton prominent href="#">Copy install command</CyanPulseButton>` — copies the primary npm command to clipboard on click.

---

## Section 10 — Tech Stack

**ID:** `#stack`
**Goal:** Earn dev credibility. Anchor the architecture in real components.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Under the hood</SectionLabel>

<DisplayHeading size="section">
  Built on <em>open</em> primitives.
</DisplayHeading>

<p className="mt-8 max-w-3xl text-ghost-70 text-lg">
  No proprietary lock-in. Every layer is swappable, inspectable, and self-hosted.
</p>
```

### Visual — `<ArchitectureDiagram>`
Static SVG stacked diagram (5 layers from top to bottom):

```
┌─ Channels ─────────────────────────────────┐
│  WhatsApp · Telegram · Discord · Slack    │
├─ Gateway ──────────────────────────────────┤
│  FloodGate · Dedup · TaskQueue            │
├─ Workers ──────────────────────────────────┤
│  MessageWorker × 2                         │
├─ Engine ───────────────────────────────────┤
│  SBS · DualCognition · MemoryEngine       │
├─ LLM Router ───────────────────────────────┤
│  Gemini · Claude · Ollama · OpenAI        │
└────────────────────────────────────────────┘
```

On hover of any layer: cyan border glow + tooltip with specifics:
- Channels: "BaseChannel ABC. Swap/extend without touching core."
- Gateway: "3s FloodGate batching, 5-min dedup TTL, async queue max 100."
- Workers: "Two concurrent asyncio workers. Backpressure-aware."
- Engine: "SBS 8-layer profile + Dual Cognition split-stream + hybrid RAG."
- LLM Router: "litellm.Router multi-provider. Copilot token auto-refresh."

### Stack badges (below diagram)
3-row grid of tech badges (liquid-glass pills, logo + name). Categories:
- **Storage:** SQLite · sqlite-vec · LanceDB · SQLiteGraph
- **LLM/ML:** litellm · Ollama · FastEmbed · FlashRank · Toxic-BERT
- **Runtime:** FastAPI · asyncio · Python 3.11+ · pydantic

### Motion
- Header: revealFade.
- Diagram: revealFadeFast, on view each layer pulses cyan top-to-bottom (0.2s stagger) once.
- Badges: staggerChildren.

---

## Section 11 — Community

**ID:** `#community`
**Goal:** Social proof. Show it's alive.

### Layout
`bg-black py-28 md:py-40 px-6 max-w-6xl mx-auto`.

### Copy

```tsx
<SectionLabel>Community</SectionLabel>

<DisplayHeading size="section">
  Open source. <em>Yours</em> to fork.
</DisplayHeading>

<p className="mt-8 max-w-2xl text-ghost-70 text-lg">
  Synapse is MIT-licensed and built in public.
  Join the contributors shaping the brain.
</p>
```

### Stats row
4 liquid-glass stat cards:

```
★ GitHub Stars    [live count]   [TO CONFIRM — wire via GitHub API]
◆ Contributors    [live count]
⬇ Installs/month  [count]        [TO CONFIRM — npm registry API when shipped]
⚡ Issues closed  [count]
```

Numbers animate from 0 on view (count-up, 1.5s).

### Contributor grid
2 rows × 6 cols of avatars (liquid-glass pill around each), pulled from GitHub contributors API. On hover: name + commit count tooltip.

### Community links
Row of `<LiquidGlassPill>` buttons:
- `GitHub — star the repo` (primary, cyan glow)
- `Read the docs`
- `Join Discord`
- `Follow on X/Twitter`
- `Report a bug`
- `Read CONTRIBUTING.md`

### Motion
- Header: revealFade.
- Stat cards: staggerChildren + count-up animation.
- Avatar grid: staggerChildren (0.05s between each for dense feel).

---

## Section 12 — Footer / CTA

**ID:** `#footer`
**Goal:** Last chance to install. Tidy links.

### Layout
`bg-black pt-24 pb-12 px-6 max-w-6xl mx-auto border-t border-ghost-10`.

### Final CTA (center)

```tsx
<DisplayHeading size="section">
  Start remembering <em>everything</em>.
</DisplayHeading>

<div className="mt-10 flex justify-center">
  <InstallCommandPill command="npm install synapse" />
</div>

<div className="mt-6 flex justify-center gap-3">
  <CyanPulseButton prominent href="https://github.com/...">Star on GitHub</CyanPulseButton>
  <LiquidGlassPill href="#" as="a">Read the docs</LiquidGlassPill>
</div>
```

### Link columns (below CTA)

4 columns:

| Product | Resources | Community | Legal |
|---|---|---|---|
| Brain | Docs | GitHub | License (MIT) |
| SBS | API reference | Discord | Privacy |
| Memory | Changelog | Twitter | Contact |
| Dual Cognition | Architecture | Contributors | |
| Privacy Vault | | | |
| Channels | | | |

### Bottom strip
`Synapse — a brain that remembers. © 2026. MIT licensed.` — centered, `text-ghost-40 text-xs`.

### Motion
- Final heading: revealFade.
- Install pill + CTAs: staggerChildren.
- Columns: single revealFadeFast.

---

## 13. Global Navigation

Sticky top, `fixed top-0 inset-x-0 z-50`. Liquid-glass pill style from template. On scroll past hero: reduce padding (`py-3 → py-2`), tighten. On mobile (<768px): collapse links into a hamburger menu opening a liquid-glass sheet.

Active section indicator: as user scrolls, the nav link matching the current section gets a subtle cyan underline (framer-motion layoutId for smooth transitions).

---

## 14. Accessibility

- All interactive elements keyboard-accessible (Tab/Enter/Space).
- Focus rings visible — use `focus-visible:ring-2 focus-visible:ring-neural` on all buttons/pills.
- Respect `prefers-reduced-motion`: disable neural background loop, radar fill, stream merge, channel converge. Replace with static end-state.
- All animations pause on `document.hidden`.
- Color contrast: body text `text-ghost-70` on `bg-black` clears AAA (>7:1). Labels `text-ghost-40` clears AA normal (≥4.5:1) — dev should verify exact ratios in final palette. Cyan accent is decorative, never load-bearing for information.
- Alt text on every icon (lucide icons accept `aria-label`).
- Video elements (if any added later): `aria-hidden="true"` since they're decorative.
- Skip-to-content link at top of DOM.

---

## 15. Performance Targets

- **LCP:** <2.0s on 4G (hero paint is cheap — custom bg renders quickly after initial fonts load).
- **INP:** <200ms — all animations GPU-composited (`transform` + `opacity` only, no `width`/`height` animations).
- **CLS:** <0.05 — reserve space for all lazy-loaded content (no layout shifts on images/graphs).
- **Bundle size:** <250KB gzipped initial load. Code-split sections below the fold.
- **Neural background:** 60fps on mid-tier hardware. Fallback to static starfield on reduced-motion OR low FPS detected.
- **Fonts:** preload Instrument Serif with `<link rel="preload">`. Display `swap` to avoid FOIT.
- **Images/SVG:** inline critical SVGs (brain, architecture) for zero HTTP waterfall.

---

## 16. SEO & Meta

- **Title:** `Synapse — A brain that remembers.`
- **Description:** `Open-source, self-hosted AI companion with persistent memory, adaptive personality, and zero cloud leakage for private conversations. WhatsApp · Telegram · Discord · Slack.`
- **OG image:** 1200×630 — custom render of neural brain on black + "Synapse" wordmark in Instrument Serif italic. [TO CREATE]
- **Twitter card:** `summary_large_image`.
- **Canonical:** `https://synapse-oss.dev/` [TO CONFIRM — domain]
- **JSON-LD:** `SoftwareApplication` schema with name, description, operatingSystem, offers (free), applicationCategory (DeveloperApplication).
- **Sitemap:** single-page, single URL + anchor links.
- **robots.txt:** allow all.

---

## 17. Dependencies to Add

On top of template's existing `react`, `typescript`, `vite`, `tailwindcss`, `framer-motion`, `lucide-react`:

```json
{
  "dependencies": {
    "@react-three/fiber": "^8.x",
    "three": "^0.160.x",
    "react-intersection-observer": "^9.x",
    "@vercel/analytics": "^1.x"
  },
  "devDependencies": {
    "@types/three": "^0.160.x"
  }
}
```

If dev team decides against R3F for the brain viz (and uses SVG + Canvas instead), drop `@react-three/fiber`, `three`, `@types/three`.

---

## 18. Asset Checklist

Dev team must produce or procure:

| Asset | Format | Size | Who |
|---|---|---|---|
| Synapse logomark | SVG | scalable | Designer [TO COMMISSION] |
| Synapse wordmark (Instrument Serif) | SVG | scalable | Designer |
| OG social image | PNG | 1200×630 | Designer |
| Favicon set | ICO + PNG | 16/32/48/192/512 | Designer |
| Neural background parameters | code | — | Dev |
| `<NeuralBrain>` lobe shapes | SVG paths | — | Designer + Dev |
| `<KnowledgeGraphViz>` seed data | JSON | — | Content |
| 4 channel icons (monochrome) | SVG | — | Dev (lucide or custom) |
| Architecture diagram | SVG | — | Dev |

---

## 19. Launch Checklist

Before shipping to production:

- [ ] All 12 sections built and scrollable on desktop + mobile
- [ ] Install command finalized (see Open Items) and wired into pill + terminal
- [ ] Hero headline renders with correct italic emphasis
- [ ] Accent cyan is the ONLY color besides monochrome (grep for stray colors)
- [ ] All animations respect `prefers-reduced-motion`
- [ ] Lighthouse Performance ≥90 on desktop, ≥80 on mobile
- [ ] Lighthouse Accessibility = 100
- [ ] All copy proofread for typos + factual accuracy (SBS layer names, tension score range, perf numbers)
- [ ] GitHub stars + contributors wire up to live API
- [ ] Domain DNS + SSL verified
- [ ] 404 page + error boundaries
- [ ] Analytics installed (Vercel/CF/umami — [TO CONFIRM])
- [ ] OG image renders in preview tools (Twitter card validator, LinkedIn inspector)
- [ ] `robots.txt` + sitemap served
- [ ] Mobile device test on real iPhone + Android
- [ ] Keyboard-only navigation test
- [ ] Screen reader smoke test (VoiceOver or NVDA)

---

## 20. Open Items — TO CONFIRM

Items requiring decisions before or during build:

1. **npm install command — exact syntax.** User indicated "working on that." Current assumption: `npm install synapse`. Alternatives to decide between: `npm install synapse`, `npm install @synapse-oss/synapse`, `npx synapse-cli`, `pip install synapse-ai`. If Python-first, the Node/npm branding may mislead.

2. **Domain.** Placeholder assumed `synapse-oss.dev`. Other options: `synapse.ai` (likely taken), `synapse-oss.com`, `getsynapse.io`. Who owns / will own the chosen domain?

3. **GitHub repo URL.** Assumed `github.com/UpayanGhosh/Synapse-OSS`. Confirm.

4. **Sub-hero line.** Default proposed: "Synapse is a self-hosted AI companion with persistent memory, adaptive personality, and zero cloud leakage for your private conversations. Talks to you on WhatsApp, Telegram, Discord, and Slack." Is this the final copy or should it be tightened?

5. **Logomark design.** Custom mark needed. Placeholder: lucide `Brain` icon. Who designs? Timeline?

6. **Launch timeline.** Determines whether all-custom scope is feasible vs needing v1 (simpler animations) → v2 (full animations).

7. **Analytics.** Vercel Analytics (free, privacy-friendly, first-party) vs umami (self-hosted) vs Plausible (paid). Pick one.

8. **Community section — live counts.** Star count + contributors come from GitHub API. Need: decision on caching interval (5min? 1hr?) and a fallback value for API outages.

9. **Discord link.** Is there an active Synapse Discord? If not, should one be set up before launch?

10. **Twitter/X handle.** Is there `@SynapseOSS` or similar? Or will one be created?

11. **A11y sign-off.** Will there be a formal accessibility audit or self-certify at launch?

12. **OSS legal.** MIT is stated throughout — confirm the repo's LICENSE file matches.

---

## Appendix A — Source Material

The following documents informed this spec and remain authoritative for facts:

- `PRODUCT_SHOWCASE_HANDOVER.md` (develop branch, 2026-04-10) — positioning, 20-feature catalog, design trends. This spec supersedes it for the showcase site but the feature catalog is still a valid reference for future sections or blog posts.
- `CLAUDE.md` (root) — architecture ground truth. LLM routing, SBS pipeline, memory flow, gotchas. Refer to this for any technical claim in copy.
- `HOW_TO_RUN.md` (root, 2026-04-19) — install flow. The terminal animation in Section 9 mirrors this document's sequence. Keep them in sync.
- `SYMBOLS.md` (root) — class/function names. When copy refers to implementation details (BatchProcessor, FloodGate, litellm.Router), names must match this file.

## Appendix B — Animation Reference

External references for the dev team. We aim for the *level* of polish, not the specific animations:

- **motionsites.ai** — overall tone and deliberate motion.
- **linear.app** — liquid-glass cards done right, restrained animation, scroll-linked parallax.
- **vercel.com** — dev-facing copy + terminal UI.
- **stripe.com** — multi-section scroll storytelling.
- **ollama.com** — OSS + install command pattern.
- **anthropic.com** — Instrument Serif usage, monochrome discipline.

Specific motion patterns we're borrowing:

- Scroll-linked parallax on large viz → inspired by Linear's feature sections.
- Count-up number animations → `react-countup` or framer-motion `useSpring` on a ref.
- Typewriter terminal → common pattern; acceptable implementations: `typed.js`, custom `useEffect` + `setInterval`, or framer-motion `animate()` over chars.
- Staggered grid reveals → framer-motion `staggerChildren`.

---

*End of spec. Send feedback or questions to [TO CONFIRM — project owner / design Slack channel].*
