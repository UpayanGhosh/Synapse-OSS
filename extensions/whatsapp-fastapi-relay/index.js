const DEFAULT_ENDPOINT = "http://127.0.0.1:8000/whatsapp/enqueue";
const DEFAULT_TIMEOUT_MS = 8_000;
const DEFAULT_TTL_MS = 30_000;

function keyOf(ctx, fallback) {
  return `${ctx.channelId}:${ctx.conversationId ?? fallback}`;
}

function withTimeout(ms) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), ms);
  return { signal: controller.signal, cancel: () => clearTimeout(t) };
}

function normalizePhone(value) {
  if (!value) return "";
  return String(value).replace(/\D/g, "");
}

function resolveMessageId(event, key) {
  return (
    event.messageId ||
    event.id ||
    event?.metadata?.messageId ||
    event?.raw?.key?.id ||
    `${key}:${Date.now()}`
  );
}

export default function register(api) {
  const logger = api.runtime.logging.getChildLogger({ plugin: "whatsapp-fastapi-relay" });

  const pluginCfg = api.pluginConfig ?? {};
  const endpoint = typeof pluginCfg.endpoint === "string" && pluginCfg.endpoint.trim()
    ? pluginCfg.endpoint.trim()
    : DEFAULT_ENDPOINT;
  const timeoutMs = Number.isFinite(pluginCfg.timeoutMs) && pluginCfg.timeoutMs > 0
    ? pluginCfg.timeoutMs
    : DEFAULT_TIMEOUT_MS;
  const ttlMs = Number.isFinite(pluginCfg.ttlMs) && pluginCfg.ttlMs > 0
    ? pluginCfg.ttlMs
    : DEFAULT_TTL_MS;
  const bridgeToken = typeof pluginCfg.bridgeToken === "string" && pluginCfg.bridgeToken.trim()
    ? pluginCfg.bridgeToken.trim()
    : (process.env.WHATSAPP_BRIDGE_TOKEN || "").trim();

  const suppress = new Map();
  let selfIdPromise = null;

  function sweep() {
    const now = Date.now();
    for (const [k, exp] of suppress.entries()) {
      if (exp <= now) suppress.delete(k);
    }
  }

  async function loadSelfId() {
    if (selfIdPromise) return selfIdPromise;
    selfIdPromise = (async () => {
      try {
        const info = await api.runtime.connections.getIdentity("whatsapp", "default");
        if (info?.details?.jid) {
          const raw = info.details.jid.replace(/:.*@/, "@");
          logger.info(`Loaded self ID: ${raw}`);
          return raw;
        }
      } catch (e) {
        logger.warn("Failed to load self ID", e);
      }
      return null;
    })();
    return selfIdPromise;
  }

  // Intercept inbound messages
  api.on("message_received", async (event) => {
    if (event.channelId !== "whatsapp" || !event.content || !event.conversationId) return;
    if (typeof event.content !== "string" || !event.content.trim()) return;

    const selfId = await loadSelfId();
    // Ignore updates from ourselves
    if (selfId && event.senderId === selfId) return;

    // Check if we recently replied to this via the bridge
    sweep();
    const key = keyOf(event, event.senderId);
    event.preventDefault();
    if (suppress.has(key)) {
      logger.debug(`Suppressing duplicate bridge handoff for ${key}`);
      return;
    }

    // Forward to FastAPI async ingress and return immediately.
    try {
      const messageId = resolveMessageId(event, key);
      const payload = {
        message_id: messageId,
        from_phone: normalizePhone(event.senderId),
        to_phone: normalizePhone(selfId),
        conversation_id: event.conversationId,
        text: event.content.trim(),
        timestamp: new Date().toISOString(),
        channel: "whatsapp",
      };

      logger.info(`Enqueueing ${messageId} from ${event.senderId}...`);
      const { signal, cancel } = withTimeout(timeoutMs);

      const headers = { "Content-Type": "application/json" };
      if (bridgeToken) headers["x-bridge-token"] = bridgeToken;

      const res = await fetch(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal
      });
      cancel();

      if (!res.ok) {
        const body = await res.text();
        logger.error(`FastAPI enqueue failed (${res.status}): ${body.slice(0, 200)}`);
        return;
      }

      const data = await res.json();
      suppress.set(key, Date.now() + ttlMs);
      logger.info(`Queued ${messageId} (job=${data.job_id ?? "n/a"}, duplicate=${Boolean(data.duplicate)})`);
    } catch (err) {
      if (err.name === 'AbortError') {
        logger.error("FastAPI enqueue request timed out");
      } else {
        logger.error("Bridge error", err);
      }
    }
  });
}
