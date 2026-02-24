import os
import logging
import re
import json
import urllib.error
import urllib.request

try:
    import ollama

    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLMRouter")

# NSFW Safety Overrides (configurable via LLM_SAFETY_LEVEL env var)
SAFETY_LEVEL = os.environ.get("LLM_SAFETY_LEVEL", "BLOCK_NONE")
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": SAFETY_LEVEL},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": SAFETY_LEVEL},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": SAFETY_LEVEL},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": SAFETY_LEVEL},
]


class LLMRouter:
    def __init__(self, cloud_models=None, backup_model="llama3.2:3b"):
        # Keep google-antigravity naming to match openclaw.json.
        self.cloud_models = cloud_models or ["google-antigravity/gemini-3-flash"]
        self.backup_model = backup_model
        # Backward-compatible attribute used by db/server.py status payload.
        self.kimi_model = self.cloud_models[0]

        self.gateway_url, self.gateway_token = self._load_gateway_config()
        if not self.gateway_token:
            logger.warning("OpenClaw gateway token missing; cloud route disabled.")

    def _load_gateway_config(self):
        """
        Resolve OpenClaw local gateway auth from env or openclaw.json.
        Priority:
          1) OPENCLAW_GATEWAY_URL / OPENCLAW_GATEWAY_TOKEN
          2) openclaw.json gateway.port + gateway.auth.token
        """
        env_url = os.getenv("OPENCLAW_GATEWAY_URL")
        env_token = os.getenv("OPENCLAW_GATEWAY_TOKEN")
        if env_url and env_token:
            return env_url, env_token

        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        config_path = os.getenv("OPENCLAW_CONFIG_PATH") or os.path.join(
            root_dir, "openclaw.json"
        )

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            gateway_cfg = cfg.get("gateway", {})
            port = gateway_cfg.get("port", 18789)
            token = gateway_cfg.get("auth", {}).get("token")
            bind = gateway_cfg.get("bind", "loopback")
            host = "127.0.0.1" if bind == "loopback" else "localhost"
            return f"http://{host}:{port}/v1/messages", token
        except Exception as e:
            logger.warning("Failed to read OpenClaw gateway config: %s", str(e))
            return os.getenv("OPENCLAW_GATEWAY_URL"), os.getenv(
                "OPENCLAW_GATEWAY_TOKEN"
            )

    def _normalize_google_model(self, model_name: str) -> str:
        """
        Convert provider-qualified names to model IDs expected by the local
        OpenClaw gateway oauth route.
        """
        if not model_name:
            return "gemini-3-flash"
        if model_name.startswith("google-antigravity/"):
            return model_name.split("/", 1)[1]
        if model_name.startswith("google/"):
            return model_name.split("/", 1)[1]
        return model_name

    def generate(
        self, prompt, system_prompt="You are a helpful assistant.", force_kimi=False
    ):
        """
        Attempts generation with OpenClaw local gateway (google-antigravity OAuth).
        Legacy arg `force_kimi` is ignored to prevent external NVAPI/Kimi routing.
        """

        # 1. PRIMARY: local gateway via google-antigravity OAuth.
        for model_name in self.cloud_models:
            try:
                text = self._call_antigravity(prompt, system_prompt, model_name)
                if text:
                    return self._sanitize(text)
            except Exception as e:
                logger.warning("Gateway model %s failed: %s", model_name, str(e))
                continue

        # 2. Local fallback only (no NVAPI/OpenAI credit route).
        return self._sanitize(self._call_ollama(prompt, system_prompt))

    def _call_antigravity(self, prompt, system_prompt, model_name):
        if not self.gateway_url or not self.gateway_token:
            return None

        # Try normalized model first, then raw provider-qualified fallback.
        candidates = []
        normalized = self._normalize_google_model(model_name)
        if normalized:
            candidates.append(normalized)
        if model_name not in candidates:
            candidates.append(model_name)

        headers = {
            "x-api-key": self.gateway_token,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        for candidate_model in candidates:
            payload = {
                "model": candidate_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
            }
            if system_prompt:
                payload["system"] = system_prompt

            req = urllib.request.Request(
                self.gateway_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                text = self._extract_gateway_text(data)
                if text:
                    self.kimi_model = model_name
                    return text
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                logger.warning(
                    "Gateway rejected model %s (%s): %s",
                    candidate_model,
                    e.code,
                    err_body[:200],
                )
                continue
            except Exception as e:
                logger.warning(
                    "Gateway call failed for model %s: %s", candidate_model, str(e)
                )
                continue

        return None

    def _extract_gateway_text(self, data):
        # Anthropic-style responses.
        content = data.get("content")
        if isinstance(content, list):
            text_chunks = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    text_chunks.append(block["text"])
            if text_chunks:
                return "".join(text_chunks)

        # OpenAI-style responses.
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message", {})
            content_text = msg.get("content")
            if isinstance(content_text, str):
                return content_text

        # Generic fallback field.
        if isinstance(data.get("output_text"), str):
            return data["output_text"]

        return None

    def _sanitize(self, text: str) -> str:
        """
        Strips internal reasoning blocks like <think>...</think> and
        metadata tags like <final>...</final> before sending to the user.
        """
        if not text:
            return ""
        # 1. Remove <think> blocks completely
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # 2. Extract content from <final> tags if they exist
        text = re.sub(
            r"<final>(.*?)</final>", r"\1", text, flags=re.DOTALL | re.IGNORECASE
        )
        # 3. Clean up generic thought headers
        text = re.sub(
            r"^Thought for\b.*$", "", text, flags=re.MULTILINE | re.IGNORECASE
        )
        # 4. Clean up any leftover thinking content (non-greedy)
        text = re.sub(r"\n+Thinking\n+.*?\n+", "\n\n", text, flags=re.IGNORECASE)

        return text.strip()

    def _call_kimi(self, prompt, system_prompt):
        """
        Backward-compat shim. External Kimi/NVIDIA path is intentionally disabled.
        """
        logger.warning(
            "Legacy Kimi/NVIDIA route disabled; using google-antigravity OAuth route."
        )
        return self._call_antigravity(
            prompt, system_prompt, self.kimi_model
        ) or self._call_ollama(prompt, system_prompt)

    def _call_ollama(self, prompt, system_prompt):
        if HAS_OLLAMA:
            try:
                response = ollama.chat(
                    model=self.backup_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                return response["message"]["content"]
            except Exception:
                pass
        return "Error: All backends failed."

    def embed(self, text, model="text-embedding-004"):
        if HAS_OLLAMA:
            return ollama.embeddings(model="nomic-embed-text", prompt=text)["embedding"]
        return []


# Singleton Instance
llm = LLMRouter()
