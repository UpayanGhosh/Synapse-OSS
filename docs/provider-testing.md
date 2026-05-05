# Provider Testing

Synapse supports more providers than one maintainer should personally pay for. Provider
quality is therefore tested in layers.

## 1. Contract Tests

These do not call provider networks or spend quota. They verify that every provider listed
in onboarding has a coherent Synapse contract:

- provider appears exactly once in the onboarding inventory
- API-key providers have a validation model and env var mapping
- multi-field providers such as Bedrock and Vertex AI validate without fake single-key assumptions
- Qianfan carries both access key and secret key
- `litellm.acompletion()` is called with `max_tokens=1`, timeout, and no retries
- router env injection matches onboarding provider config shapes

Run:

```bash
cd workspace
pytest tests/providers/test_provider_contracts.py -q
```

## 2. Live Smoke Tests

These are opt-in because they use real credentials and may spend quota. They still make the
smallest possible validation call (`max_tokens=1`) through the same onboarding validator.

Run all live provider tests that have matching env vars:

```bash
cd workspace
pytest tests/providers/test_provider_live.py --run-live-providers -q
```

Run one provider:

```bash
cd workspace
pytest tests/providers/test_provider_live.py --run-live-providers --live-provider gemini -q
```

Required env vars are the same as onboarding:

| Provider | Required env |
|---|---|
| `gemini` | `GEMINI_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `mistral` | `MISTRAL_API_KEY` |
| `xai` | `XAI_API_KEY` |
| `cohere` | `COHERE_API_KEY` |
| `togetherai` | `TOGETHERAI_API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY` |
| `minimax` | `MINIMAX_API_KEY` |
| `moonshot` | `MOONSHOT_API_KEY` |
| `zai` | `ZAI_API_KEY` |
| `volcengine` | `VOLCENGINE_API_KEY` |
| `huggingface` | `HUGGINGFACE_API_KEY` |
| `nvidia_nim` | `NVIDIA_NIM_API_KEY` |
| `qianfan` | `QIANFAN_AK` and `QIANFAN_SK` |
| `bedrock` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_REGION_NAME` |
| `vertex_ai` | `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `ollama` | local Ollama server, optional `OLLAMA_API_BASE` |

OAuth/subscription providers are validated by their login flows rather than a reusable API
key:

- `github_copilot`
- `openai_codex`
- `google_antigravity`
- `claude_cli`

Self-hosted `vllm` depends on the user's own endpoint and should be covered by a local
deployment smoke test for that endpoint.

## Release Policy

- Every PR should pass contract tests.
- Live smoke tests should run before releases for whichever provider secrets are available.
- Providers without maintainer credentials should be marked "contract-tested; needs community
  live verification" rather than advertised as maintainer live-verified.
