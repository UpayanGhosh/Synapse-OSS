/**
 * synapse.js — Real-time pipeline visualization dashboard
 *
 * Subscribes to /pipeline/events (SSE) and animates the Synapse pipeline
 * diagram in real time. All modules are vanilla JS, no dependencies.
 *
 * Modules:
 *   SSEClient        — EventSource wrapper with auto-reconnect
 *   NodeAnimator     — Node glow/pulse/particle animations
 *   TensionMeter     — Animated tension bar + color coding
 *   TypewriterEffect — Character-by-character text reveal
 *   SBSPanel         — Soul-Brain Sync layer tile management
 *   TimelineBar      — Run-duration segment display
 *   MemoryPanel      — Memory result score bars + tier badge
 */

'use strict';

// ---------------------------------------------------------------------------
// Element ID maps (must match index.html)
// ---------------------------------------------------------------------------
const EL = {
  statusIndicator: 'panel-status-indicator',
  runId:           'panel-run-id',
  currentMessage:  'panel-current-message',
  lastResponse:    'panel-last-response',
  queueSize:       'panel-queue-size',

  complexityBadge: 'panel-complexity-badge',
  tensionLevel:    'panel-tension-level',
  tensionType:     'panel-tension-type',
  tensionBar:      'panel-tension-bar',
  strategy:        'panel-strategy',
  tone:            'panel-tone',
  innerMonologue:  'panel-inner-monologue',
  thought:         'panel-thought',
  memoryResults:   'panel-memory-results',
  contradictions:  'panel-contradictions',

  sbsLayers:       'panel-sbs-layers',
  sbsTokenBar:     'panel-sbs-token-bar',
  sbsTokenCount:   'panel-sbs-token-count',

  memoryTier:      'panel-memory-tier',

  timeline:        'panel-timeline',
};

const NODES = {
  floodgate:     'node-floodgate',
  dedup:         'node-dedup',
  queue:         'node-queue',
  memory:        'node-memory',
  toxicity:      'node-toxicity',
  dualcognition: 'node-dualcognition',
  sbs:           'node-sbs',
  trafficcop:    'node-trafficcop',
  llm:           'node-llm',
  response:      'node-response',
};

// ---------------------------------------------------------------------------
// Style constants
// ---------------------------------------------------------------------------
const COMPLEXITY_STYLES = {
  fast:     { bg: '#422006', border: '#FBBF24', text: '#FBBF24', label: 'FAST' },
  standard: { bg: '#0C4A6E', border: '#06B6D4', text: '#06B6D4', label: 'STANDARD' },
  deep:     { bg: '#2E1065', border: '#A855F7', text: '#A855F7', label: '★ DEEP ★' },
};

const STRATEGY_COLORS = {
  acknowledge: '#22C55E',
  challenge:   '#EF4444',
  support:     '#06B6D4',
  redirect:    '#F59E0B',
  quiz:        '#A855F7',
  celebrate:   '#EC4899',
};

function getTensionColor(level) {
  if (level < 0.3) return '#22C55E';
  if (level < 0.6) return '#F59E0B';
  if (level < 0.8) return '#F97316';
  return '#EF4444';
}

function getTensionClass(level) {
  if (level < 0.3) return 'tension-low';
  if (level < 0.6) return 'tension-mid';
  if (level < 0.8) return 'tension-high';
  return 'tension-critical';
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------
function el(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const node = el(id);
  if (!node) return;
  node.textContent = text;
}

function setHTML(id, html) {
  const node = el(id);
  if (!node) return;
  node.innerHTML = html;
}

function setStyle(id, prop, value) {
  const node = el(id);
  if (!node) return;
  node.style[prop] = value;
}

function addClass(id, cls) {
  const node = el(id);
  if (!node) return;
  node.classList.add(cls);
}

function removeClass(id, cls) {
  const node = el(id);
  if (!node) return;
  node.classList.remove(cls);
}

// ---------------------------------------------------------------------------
// 1. SSEClient
// ---------------------------------------------------------------------------
class SSEClient {
  constructor(url) {
    this._url = url;
    this._source = null;
    this._handlers = {};           // event type → [handler, ...]
    this._reconnectDelay = 1000;   // ms, doubles on each failure, max 30s
    this._reconnectTimer = null;
    this._intentionalClose = false;
  }

  connect() {
    this._intentionalClose = false;
    this._openSource();
  }

  disconnect() {
    this._intentionalClose = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._source) {
      this._source.close();
      this._source = null;
    }
    this._setStatus('DISCONNECTED', '#EF4444');
  }

  onEvent(type, handler) {
    if (!this._handlers[type]) {
      this._handlers[type] = [];
    }
    this._handlers[type].push(handler);

    // If source already exists, attach the listener immediately
    if (this._source) {
      this._source.addEventListener(type, (e) => this._dispatch(type, e));
    }
  }

  _openSource() {
    this._setStatus('CONNECTING', '#F59E0B');

    const source = new EventSource(this._url);
    this._source = source;

    source.onopen = () => {
      this._reconnectDelay = 1000;
      this._setStatus('LIVE', '#22C55E');
    };

    source.onerror = () => {
      source.close();
      this._source = null;
      this._setStatus('DISCONNECTED', '#EF4444');
      if (!this._intentionalClose) {
        this._scheduleReconnect();
      }
    };

    // Register all known event types
    const allTypes = [
      'connected',
      'pipeline.start', 'pipeline.done',
      'floodgate.debounce', 'floodgate.flush',
      'dedup.check',
      'queue.enqueued', 'queue.dequeued',
      'memory.query_start', 'memory.embedding_start', 'memory.embedding_done',
      'memory.lancedb_search_start', 'memory.lancedb_search_done',
      'memory.scoring', 'memory.fast_gate_hit',
      'memory.reranking_start', 'memory.query_done',
      'toxicity.check',
      'cognition.classify', 'cognition.fast_path',
      'cognition.analyze_start', 'cognition.analyze_done',
      'cognition.recall_start', 'cognition.recall_done',
      'cognition.merge_start', 'cognition.merge_done',
      'sbs.read_start', 'sbs.layer_read', 'sbs.compile_done',
      'traffic_cop.start', 'traffic_cop.skip', 'traffic_cop.done',
      'llm.route', 'llm.stream_start', 'llm.stream_done',
    ];

    for (const type of allTypes) {
      source.addEventListener(type, (e) => {
        let data = {};
        try { data = JSON.parse(e.data); } catch (_) {}
        this._fireHandlers(type, data);
      });
    }

    // Fallback for message events without an explicit type
    source.onmessage = (e) => {
      let data = {};
      try { data = JSON.parse(e.data); } catch (_) {}
      const type = data.event || 'message';
      this._fireHandlers(type, data);
    };
  }

  _scheduleReconnect() {
    const delay = this._reconnectDelay;
    this._setStatus(`RECONNECTING (${Math.round(delay / 1000)}s)`, '#F59E0B');
    this._reconnectTimer = setTimeout(() => {
      this._reconnectDelay = Math.min(this._reconnectDelay * 2, 30000);
      this._openSource();
    }, delay);
  }

  _fireHandlers(type, data) {
    const handlers = this._handlers[type];
    if (!handlers) return;
    for (const fn of handlers) {
      try { fn(data); } catch (err) {
        console.error(`[SSEClient] Handler error for "${type}":`, err);
      }
    }
  }

  _setStatus(label, color) {
    const node = el(EL.statusIndicator);
    if (!node) return;
    node.textContent = label;
    node.style.color = color;
    node.style.borderColor = color;
    node.style.boxShadow = `0 0 8px ${color}55`;
  }
}

// ---------------------------------------------------------------------------
// 2. NodeAnimator
// ---------------------------------------------------------------------------
class NodeAnimator {
  constructor() {
    this._clearTimers = {};   // nodeId → timeout handle
  }

  // Internal: get the element, null-safe
  _node(nodeId) {
    return el(nodeId);
  }

  // Remove all state classes from a node
  _clearClasses(nodeId) {
    const node = this._node(nodeId);
    if (!node) return;
    node.classList.remove(
      'node-active', 'node-processing', 'node-done',
      'node-error', 'node-fast', 'node-idle'
    );
  }

  // Schedule auto-reset to idle after delayMs
  _scheduleReset(nodeId, delayMs) {
    if (this._clearTimers[nodeId]) clearTimeout(this._clearTimers[nodeId]);
    this._clearTimers[nodeId] = setTimeout(() => {
      this._clearClasses(nodeId);
      const node = this._node(nodeId);
      if (node) node.classList.add('node-idle');
    }, delayMs);
  }

  setActive(nodeId) {
    const node = this._node(nodeId);
    if (!node) return;
    this._clearClasses(nodeId);
    node.classList.add('node-active');
    this._scheduleReset(nodeId, 10000);
  }

  setProcessing(nodeId) {
    const node = this._node(nodeId);
    if (!node) return;
    this._clearClasses(nodeId);
    node.classList.add('node-processing');
    this._scheduleReset(nodeId, 10000);
  }

  setDone(nodeId) {
    const node = this._node(nodeId);
    if (!node) return;
    this._clearClasses(nodeId);
    node.classList.add('node-done');
    this._scheduleReset(nodeId, 2000);
  }

  setError(nodeId) {
    const node = this._node(nodeId);
    if (!node) return;
    this._clearClasses(nodeId);
    node.classList.add('node-error');
    this._scheduleReset(nodeId, 3000);
  }

  setFast(nodeId) {
    const node = this._node(nodeId);
    if (!node) return;
    this._clearClasses(nodeId);
    node.classList.add('node-fast');
    this._scheduleReset(nodeId, 2000);
  }

  resetAll() {
    for (const nodeId of Object.values(NODES)) {
      if (this._clearTimers[nodeId]) clearTimeout(this._clearTimers[nodeId]);
      delete this._clearTimers[nodeId];
      this._clearClasses(nodeId);
      const node = this._node(nodeId);
      if (node) node.classList.add('node-idle');
    }
  }

  // Animate a glowing particle from one node to the next along an SVG edge.
  animateParticle(fromNodeId, toNodeId, durationMs = 600) {
    const fromKey = fromNodeId.replace('node-', '');
    const toKey   = toNodeId.replace('node-', '');
    const edgeId  = `edge-${fromKey}-${toKey}`;
    const edge    = document.getElementById(edgeId);
    if (!edge) return;

    const svg = edge.closest('svg');
    if (!svg) return;

    const ns = 'http://www.w3.org/2000/svg';
    const xlinkNs = 'http://www.w3.org/1999/xlink';

    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('r', '4');
    circle.setAttribute('fill', '#06B6D4');
    circle.style.filter = 'drop-shadow(0 0 6px #06B6D4)';

    const anim = document.createElementNS(ns, 'animateMotion');
    anim.setAttribute('dur', `${durationMs}ms`);
    anim.setAttribute('fill', 'remove');
    anim.setAttribute('repeatCount', '1');

    const mpath = document.createElementNS(ns, 'mpath');
    mpath.setAttributeNS(xlinkNs, 'href', `#${edgeId}`);

    anim.appendChild(mpath);
    circle.appendChild(anim);
    svg.appendChild(circle);

    anim.beginElement();
    setTimeout(() => { if (circle.parentNode) circle.remove(); }, durationMs + 150);
  }

  // Pulse all nodes green once (celebration)
  celebratePulse() {
    for (const nodeId of Object.values(NODES)) {
      const node = this._node(nodeId);
      if (!node) continue;
      node.classList.add('node-celebrate');
      setTimeout(() => node.classList.remove('node-celebrate'), 1200);
    }
  }
}

// ---------------------------------------------------------------------------
// 3. TensionMeter
// ---------------------------------------------------------------------------
class TensionMeter {
  constructor() {
    this._currentLevel = 0;
  }

  update(level, type) {
    if (typeof level !== 'number') return;
    this._currentLevel = level;

    const pct = Math.min(Math.max(level * 100, 0), 100);
    const color = getTensionColor(level);
    const cls   = getTensionClass(level);

    // Animate bar
    const bar = el(EL.tensionBar);
    if (bar) {
      bar.style.transition = 'width 0.5s ease, background-color 0.5s ease';
      bar.style.width = `${pct}%`;
      bar.style.backgroundColor = color;
      bar.style.boxShadow = `0 0 8px ${color}88`;
    }

    // Text labels
    setText(EL.tensionLevel, level.toFixed(2));
    if (type) setText(EL.tensionType, type.replace(/_/g, ' '));

    // Severity class on parent
    const parent = bar ? bar.parentElement : null;
    if (parent) {
      parent.classList.remove('tension-low', 'tension-mid', 'tension-high', 'tension-critical');
      parent.classList.add(cls);
    }
  }
}

// ---------------------------------------------------------------------------
// 4. TypewriterEffect
// ---------------------------------------------------------------------------
class TypewriterEffect {
  constructor() {
    this._timers = {};  // elementId → timer handle
  }

  type(elementId, text, speed = 30) {
    if (!text) return;
    const node = el(elementId);
    if (!node) return;

    // Cancel any existing animation on this element
    if (this._timers[elementId]) {
      clearInterval(this._timers[elementId]);
      delete this._timers[elementId];
    }

    node.textContent = '';
    let i = 0;
    const cursor = document.createElement('span');
    cursor.className = 'typewriter-cursor';
    cursor.textContent = '|';
    node.appendChild(cursor);

    this._timers[elementId] = setInterval(() => {
      if (i < text.length) {
        // Insert character before the cursor span
        cursor.insertAdjacentText('beforebegin', text[i]);
        i++;
      } else {
        clearInterval(this._timers[elementId]);
        delete this._timers[elementId];
        // Remove blinking cursor after typing is done (after a brief pause)
        setTimeout(() => {
          if (cursor.parentNode) cursor.remove();
        }, 800);
      }
    }, speed);
  }
}

// ---------------------------------------------------------------------------
// 5. SBSPanel
// ---------------------------------------------------------------------------
class SBSPanel {
  constructor() {
    this.layers = [
      'core_identity', 'linguistic', 'emotional_state', 'domain',
      'interaction', 'vocabulary', 'exemplars', 'meta',
    ];
    this._render();
  }

  _render() {
    const container = el(EL.sbsLayers);
    if (!container) return;
    container.innerHTML = '';
    for (const layer of this.layers) {
      const tile = document.createElement('div');
      tile.className = 'sbs-layer-tile';
      tile.id = `sbs-tile-${layer}`;
      tile.textContent = layer.replace(/_/g, ' ');
      container.appendChild(tile);
    }
  }

  activateLayer(layerName) {
    const tile = document.getElementById(`sbs-tile-${layerName}`);
    if (!tile) return;
    tile.classList.remove('sbs-tile-idle', 'sbs-tile-done');
    tile.classList.add('sbs-tile-active');
  }

  completeLayers(tokenCount) {
    // All tiles go green
    for (const layer of this.layers) {
      const tile = document.getElementById(`sbs-tile-${layer}`);
      if (!tile) continue;
      tile.classList.remove('sbs-tile-idle', 'sbs-tile-active');
      tile.classList.add('sbs-tile-done');
    }

    // Animate token bar
    const maxTokens = 2000;
    const pct = Math.min((tokenCount / maxTokens) * 100, 100);
    const bar = el(EL.sbsTokenBar);
    if (bar) {
      bar.style.transition = 'width 0.6s ease';
      bar.style.width = `${pct}%`;
    }
    setText(EL.sbsTokenCount, tokenCount ? `${tokenCount} tokens` : '');
  }

  reset() {
    for (const layer of this.layers) {
      const tile = document.getElementById(`sbs-tile-${layer}`);
      if (!tile) continue;
      tile.classList.remove('sbs-tile-active', 'sbs-tile-done');
      tile.classList.add('sbs-tile-idle');
    }

    const bar = el(EL.sbsTokenBar);
    if (bar) {
      bar.style.transition = 'none';
      bar.style.width = '0%';
    }
    setText(EL.sbsTokenCount, '');
  }
}

// ---------------------------------------------------------------------------
// 6. TimelineBar
// ---------------------------------------------------------------------------
class TimelineBar {
  constructor() {
    this._runStartMs = null;
    this._segments = [];   // { name, color, startMs, endMs }
  }

  startRun() {
    this._runStartMs = Date.now();
    this._segments = [];
    const container = el(EL.timeline);
    if (container) container.innerHTML = '';
  }

  addSegment(name, color, startMs, endMs) {
    this._segments.push({ name, color, startMs, endMs });
    this._repaint();
  }

  complete() {
    const endMs = Date.now();
    const container = el(EL.timeline);
    if (!container) return;

    // Show total run time
    if (this._runStartMs) {
      const total = endMs - this._runStartMs;
      const label = document.createElement('span');
      label.className = 'timeline-total';
      label.textContent = `${total}ms`;
      container.appendChild(label);
    }
  }

  _repaint() {
    const container = el(EL.timeline);
    if (!container) return;

    // Keep any existing total label
    const totalEl = container.querySelector('.timeline-total');
    container.innerHTML = '';
    if (totalEl) container.appendChild(totalEl);

    if (!this._segments.length) return;

    const totalSpan = this._segments.reduce((sum, s) => sum + (s.endMs - s.startMs), 0) || 1;

    // Insert before the total label
    for (const seg of this._segments) {
      const duration = seg.endMs - seg.startMs;
      const pct = (duration / totalSpan) * 100;

      const block = document.createElement('div');
      block.className = 'timeline-segment';
      block.style.width = `${pct}%`;
      block.style.backgroundColor = seg.color;
      block.style.position = 'relative';
      block.style.display = 'inline-block';
      block.style.height = '100%';
      block.style.minWidth = '2px';
      block.title = `${seg.name}: ${duration}ms`;

      const lbl = document.createElement('span');
      lbl.className = 'timeline-label';
      lbl.textContent = seg.name;
      block.appendChild(lbl);

      if (totalEl) {
        container.insertBefore(block, totalEl);
      } else {
        container.appendChild(block);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 7. MemoryPanel
// ---------------------------------------------------------------------------
class MemoryPanel {
  showResults(results) {
    const container = el(EL.memoryResults);
    if (!container) return;
    if (!Array.isArray(results) || !results.length) {
      container.innerHTML = '<span class="mem-empty">No results</span>';
      return;
    }

    container.innerHTML = '';
    for (const r of results) {
      const score = typeof r.score === 'number' ? r.score : 0;
      const pct   = Math.min(Math.max(score * 100, 0), 100);
      const color = this._scoreColor(score);

      const row = document.createElement('div');
      row.className = 'mem-result-row';

      const preview = document.createElement('div');
      preview.className = 'mem-result-text';
      preview.textContent = r.text ? r.text.slice(0, 80) + (r.text.length > 80 ? '…' : '') : '';

      const barWrap = document.createElement('div');
      barWrap.className = 'mem-score-bar-wrap';

      const bar = document.createElement('div');
      bar.className = 'mem-score-bar';
      bar.style.width = `${pct}%`;
      bar.style.background = color;
      bar.style.boxShadow = `0 0 6px ${color}88`;

      const scoreLbl = document.createElement('span');
      scoreLbl.className = 'mem-score-label';
      scoreLbl.textContent = score.toFixed(3);

      barWrap.appendChild(bar);
      row.appendChild(preview);
      row.appendChild(barWrap);
      row.appendChild(scoreLbl);
      container.appendChild(row);
    }
  }

  showTier(tier) {
    const node = el(EL.memoryTier);
    if (!node) return;
    node.textContent = tier === 'fast_gate' ? 'FAST GATE' : 'RERANKED';
    node.style.color         = tier === 'fast_gate' ? '#06B6D4' : '#A855F7';
    node.style.borderColor   = tier === 'fast_gate' ? '#06B6D4' : '#A855F7';
    node.style.backgroundColor = tier === 'fast_gate' ? '#0E7490' + '22' : '#7E22CE' + '22';
  }

  _scoreColor(score) {
    // red → yellow → green gradient based on score 0-1
    if (score < 0.4) return '#EF4444';
    if (score < 0.7) return '#F59E0B';
    return '#22C55E';
  }
}

// ---------------------------------------------------------------------------
// 8. Helper — complexity badge
// ---------------------------------------------------------------------------
function updateComplexityBadge(complexity) {
  const node = el(EL.complexityBadge);
  if (!node) return;
  const style = COMPLEXITY_STYLES[complexity] || COMPLEXITY_STYLES.standard;
  node.textContent = style.label;
  node.style.backgroundColor = style.bg;
  node.style.borderColor     = style.border;
  node.style.color           = style.text;
  node.style.boxShadow       = `0 0 10px ${style.border}55`;
}

// ---------------------------------------------------------------------------
// 9. Helper — strategy / tone badges
// ---------------------------------------------------------------------------
function updateStrategyBadge(strategy) {
  const node = el(EL.strategy);
  if (!node) return;
  const color = STRATEGY_COLORS[strategy] || '#94A3B8';
  node.textContent     = strategy ? strategy.replace(/_/g, ' ') : '';
  node.style.color     = color;
  node.style.borderColor = color;
  node.style.backgroundColor = color + '22';
}

function updateToneBadge(tone) {
  const node = el(EL.tone);
  if (!node) return;
  node.textContent = tone ? tone.replace(/_/g, ' ') : '';
}

// ---------------------------------------------------------------------------
// 10. Event handler wiring
// ---------------------------------------------------------------------------
function wireEvents(sse, nodeAnim, tensionMeter, typewriter, sbsPanel, timeline, memPanel) {

  // Timestamps for timeline segments
  let tMemStart        = 0;
  let tCognitionStart  = 0;
  let tSbsStart        = 0;
  let tTrafficStart    = 0;
  let tLlmStart        = 0;

  // ------------------------------------------------------------------ pipeline
  sse.onEvent('pipeline.start', (d) => {
    nodeAnim.resetAll();
    timeline.startRun();
    setText(EL.runId, d.run_id || '—');
    if (d.text) setText(EL.currentMessage, d.text.slice(0, 200));
    nodeAnim.setActive(NODES.floodgate);
  });

  sse.onEvent('pipeline.done', (d) => {
    nodeAnim.setDone(NODES.response);
    timeline.complete();
    nodeAnim.celebratePulse();

    const statusNode = el(EL.statusIndicator);
    if (statusNode) {
      const prev = statusNode.textContent;
      if (prev !== 'DISCONNECTED') {
        statusNode.textContent = 'IDLE';
        setTimeout(() => {
          if (statusNode.textContent === 'IDLE') statusNode.textContent = 'LIVE';
        }, 2500);
      }
    }
  });

  // ------------------------------------------------------------------ floodgate
  sse.onEvent('floodgate.debounce', () => {
    nodeAnim.setProcessing(NODES.floodgate);
  });

  sse.onEvent('floodgate.flush', (d) => {
    nodeAnim.setDone(NODES.floodgate);
    nodeAnim.animateParticle(NODES.floodgate, NODES.dedup, 500);
    nodeAnim.setActive(NODES.dedup);
  });

  // ------------------------------------------------------------------ dedup
  sse.onEvent('dedup.check', (d) => {
    if (d.is_duplicate) {
      nodeAnim.setError(NODES.dedup);
    } else {
      nodeAnim.setDone(NODES.dedup);
      nodeAnim.animateParticle(NODES.dedup, NODES.queue, 500);
    }
  });

  // ------------------------------------------------------------------ queue
  sse.onEvent('queue.enqueued', (d) => {
    nodeAnim.setProcessing(NODES.queue);
    if (typeof d.position === 'number') {
      setText(EL.queueSize, String(d.position));
    }
  });

  sse.onEvent('queue.dequeued', (d) => {
    nodeAnim.setDone(NODES.queue);
    setText(EL.queueSize, '0');
    // Fan out to both memory and toxicity
    nodeAnim.animateParticle(NODES.queue, NODES.memory, 500);
    setTimeout(() => nodeAnim.animateParticle(NODES.queue, NODES.toxicity, 500), 100);
  });

  // ------------------------------------------------------------------ memory
  sse.onEvent('memory.query_start', (d) => {
    tMemStart = Date.now();
    nodeAnim.setActive(NODES.memory);
    if (d.text) typewriter.type(EL.currentMessage, d.text, 20);
  });

  sse.onEvent('memory.embedding_start', () => {
    nodeAnim.setProcessing(NODES.memory);
  });

  sse.onEvent('memory.embedding_done', () => {
    nodeAnim.setActive(NODES.memory);
  });

  sse.onEvent('memory.lancedb_search_start', () => {
    nodeAnim.setProcessing(NODES.memory);
  });

  sse.onEvent('memory.lancedb_search_done', (d) => {
    nodeAnim.setActive(NODES.memory);
    // Optionally surface candidate count
  });

  sse.onEvent('memory.scoring', (d) => {
    if (Array.isArray(d.results)) {
      memPanel.showResults(d.results);
    }
  });

  sse.onEvent('memory.fast_gate_hit', () => {
    memPanel.showTier('fast_gate');
    // Flash cyan on memory node
    const node = el(NODES.memory);
    if (node) {
      node.classList.add('node-fast');
      setTimeout(() => node.classList.remove('node-fast'), 1000);
    }
  });

  sse.onEvent('memory.reranking_start', () => {
    const node = el(NODES.memory);
    if (node) {
      node.classList.remove('node-fast');
      node.classList.add('node-processing');
    }
  });

  sse.onEvent('memory.query_done', (d) => {
    nodeAnim.setDone(NODES.memory);
    if (d.tier) memPanel.showTier(d.tier);
    const endMs = Date.now();
    timeline.addSegment('Memory', '#06B6D4', tMemStart, endMs);
  });

  // ------------------------------------------------------------------ toxicity
  sse.onEvent('toxicity.check', (d) => {
    if (d.passed === false) {
      nodeAnim.setError(NODES.toxicity);
    } else {
      nodeAnim.setDone(NODES.toxicity);
    }
  });

  // ------------------------------------------------------------------ cognition
  sse.onEvent('cognition.classify', (d) => {
    tCognitionStart = Date.now();
    nodeAnim.setActive(NODES.dualcognition);
    if (d.complexity) {
      updateComplexityBadge(d.complexity);
      if (d.complexity === 'fast') {
        nodeAnim.setFast(NODES.dualcognition);
      }
    }
  });

  sse.onEvent('cognition.fast_path', () => {
    nodeAnim.setFast(NODES.dualcognition);
  });

  sse.onEvent('cognition.analyze_start', () => {
    nodeAnim.setProcessing(NODES.dualcognition);
  });

  sse.onEvent('cognition.analyze_done', (d) => {
    nodeAnim.setActive(NODES.dualcognition);
    // Could surface topics/intent here if panel elements exist
  });

  sse.onEvent('cognition.recall_start', () => {
    nodeAnim.setProcessing(NODES.dualcognition);
  });

  sse.onEvent('cognition.recall_done', () => {
    nodeAnim.setActive(NODES.dualcognition);
  });

  sse.onEvent('cognition.merge_start', () => {
    nodeAnim.setProcessing(NODES.dualcognition);
  });

  sse.onEvent('cognition.merge_done', (d) => {
    // Tension meter
    if (typeof d.tension_level === 'number') {
      tensionMeter.update(d.tension_level, d.tension_type || '');
    }

    // Inner monologue typewriter
    if (d.inner_monologue) {
      typewriter.type(EL.innerMonologue, d.inner_monologue, 18);
    }

    // Thought (deep path only)
    if (d.thought) {
      typewriter.type(EL.thought, d.thought, 18);
    }

    // Strategy + tone badges
    if (d.response_strategy) updateStrategyBadge(d.response_strategy);
    if (d.suggested_tone)    updateToneBadge(d.suggested_tone);

    // Contradictions list
    const contradictionEl = el(EL.contradictions);
    if (contradictionEl) {
      if (Array.isArray(d.contradictions) && d.contradictions.length) {
        contradictionEl.innerHTML = d.contradictions
          .map(c => `<li class="contradiction-item">${escapeHTML(String(c))}</li>`)
          .join('');
      } else {
        contradictionEl.innerHTML = '<li class="contradiction-none">None detected</li>';
      }
    }

    // Memory insights
    const memInsightEl = el(EL.memoryResults);
    if (memInsightEl && Array.isArray(d.memory_insights) && d.memory_insights.length) {
      // Append insights below existing results
      const insightSection = document.createElement('div');
      insightSection.className = 'mem-insights-section';
      insightSection.innerHTML = '<strong>Insights:</strong> ' +
        d.memory_insights.map(i => escapeHTML(String(i))).join(' · ');
      memInsightEl.appendChild(insightSection);
    }

    nodeAnim.setDone(NODES.dualcognition);
    const endMs = Date.now();
    timeline.addSegment('DualCognition', '#A855F7', tCognitionStart, endMs);
    nodeAnim.animateParticle(NODES.dualcognition, NODES.sbs, 600);
  });

  // ------------------------------------------------------------------ SBS
  sse.onEvent('sbs.read_start', () => {
    tSbsStart = Date.now();
    nodeAnim.setActive(NODES.sbs);
    sbsPanel.reset();
  });

  sse.onEvent('sbs.layer_read', (d) => {
    if (d.layer_name) sbsPanel.activateLayer(d.layer_name);
  });

  sse.onEvent('sbs.compile_done', (d) => {
    sbsPanel.completeLayers(d.token_estimate || 0);
    nodeAnim.setDone(NODES.sbs);
    const endMs = Date.now();
    timeline.addSegment('SBS', '#EC4899', tSbsStart, endMs);
    nodeAnim.animateParticle(NODES.sbs, NODES.trafficcop, 500);
  });

  // ------------------------------------------------------------------ traffic cop
  sse.onEvent('traffic_cop.start', () => {
    tTrafficStart = Date.now();
    nodeAnim.setActive(NODES.trafficcop);
  });

  sse.onEvent('traffic_cop.skip', (d) => {
    nodeAnim.setFast(NODES.trafficcop);
    // Show "STRATEGY SHORTCUT" badge if element exists
    const badgeEl = el('panel-traffic-badge');
    if (badgeEl) {
      badgeEl.textContent = 'STRATEGY SHORTCUT';
      badgeEl.style.color = '#F59E0B';
      badgeEl.style.borderColor = '#F59E0B';
    }
  });

  sse.onEvent('traffic_cop.done', (d) => {
    nodeAnim.setDone(NODES.trafficcop);
    const endMs = Date.now();
    if (tTrafficStart) timeline.addSegment('TrafficCop', '#F59E0B', tTrafficStart, endMs);

    // Show classification badge if element exists
    const classEl = el('panel-classification');
    if (classEl && d.classification) {
      classEl.textContent = d.classification;
    }

    nodeAnim.animateParticle(NODES.trafficcop, NODES.llm, 500);
  });

  // ------------------------------------------------------------------ LLM
  sse.onEvent('llm.route', (d) => {
    tLlmStart = Date.now();
    nodeAnim.setActive(NODES.llm);

    const modelEl = el('panel-model-name');
    if (modelEl && d.model) modelEl.textContent = d.model;

    const roleEl = el('panel-role-badge');
    if (roleEl && d.role) roleEl.textContent = d.role.toUpperCase();
  });

  sse.onEvent('llm.stream_start', () => {
    nodeAnim.setProcessing(NODES.llm);
  });

  sse.onEvent('llm.stream_done', (d) => {
    nodeAnim.setDone(NODES.llm);
    const endMs = Date.now();
    if (tLlmStart) timeline.addSegment('LLM', '#22C55E', tLlmStart, endMs);

    const tokenEl = el('panel-token-count');
    if (tokenEl && d.total_tokens) tokenEl.textContent = `${d.total_tokens} tok`;

    nodeAnim.animateParticle(NODES.llm, NODES.response, 600);
  });

  // ------------------------------------------------------------------ connected handshake
  sse.onEvent('connected', () => {
    // Backend acknowledged our subscription — nothing extra needed
  });
}

// ---------------------------------------------------------------------------
// 11. Utility — HTML escaping
// ---------------------------------------------------------------------------
function escapeHTML(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---------------------------------------------------------------------------
// 12. Initialization
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  // Instantiate all modules
  const sseClient    = new SSEClient('/pipeline/events');
  const nodeAnim     = new NodeAnimator();
  const tensionMeter = new TensionMeter();
  const typewriter   = new TypewriterEffect();
  const sbsPanel     = new SBSPanel();
  const timeline     = new TimelineBar();
  const memPanel     = new MemoryPanel();

  // Fetch initial state for dashboard population
  fetch('/pipeline/state')
    .then((r) => r.json())
    .then((state) => {
      if (state.sbs_profile) {
        // Surface any available profile data (mood, vocab_size, etc.)
        const moodEl = el('panel-sbs-mood');
        if (moodEl && state.sbs_profile.mood) {
          moodEl.textContent = state.sbs_profile.mood;
        }
        const vocabEl = el('panel-sbs-vocab');
        if (vocabEl && state.sbs_profile.vocab_size) {
          vocabEl.textContent = `${state.sbs_profile.vocab_size} terms`;
        }
      }
      if (state.queue && typeof state.queue.size === 'number') {
        setText(EL.queueSize, String(state.queue.size));
      }
    })
    .catch(() => {
      // Graceful failure — dashboard still works without initial state
    });

  // Wire all SSE event handlers
  wireEvents(sseClient, nodeAnim, tensionMeter, typewriter, sbsPanel, timeline, memPanel);

  // Connect to SSE stream
  sseClient.connect();
});
