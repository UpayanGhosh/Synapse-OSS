# Model Parity Golden Suite

W4 turns model-agnostic behavior into a repeatable contract. It runs shared
scenarios against roles in `synapse.json`, scores each response, and writes:

- `parity_matrix.csv`
- `per_model_failures.md`
- `trend.json`
- `raw_results.json`

## Scenario Sets

The bundled `sci_fi_dashboard/model_parity/scenarios.yaml` is identity-agnostic
and safe for OSS users to run on a fresh fork. It checks general behavior such
as math, tool execution, instruction discipline, persona drift, and prose
similarity.

Identity-specific recall tests belong in a local scenario file. Start from:

```bash
sci_fi_dashboard/model_parity/scenarios.identity_specific.yaml.example
```

Replace the example names, memories, and required phrases with facts from your
own Synapse identity/memory files, then pass it explicitly:

```bash
python -m sci_fi_dashboard.model_parity.test_runner --scenarios sci_fi_dashboard/model_parity/scenarios.identity_specific.local.yaml --transport inprocess --models all
```

## Contract Tests

Fast CI checks validate schema loading, scoring, and artifact generation:

```bash
cd workspace
pytest tests/test_model_parity.py -q
```

## Live HTTP Run

Start Synapse with the parity override header enabled. The header is ignored
unless `SYNAPSE_PARITY_ALLOW_ROLE_HEADER=1`, so normal API behavior is unchanged.

```bash
cd workspace
set SYNAPSE_PARITY_ALLOW_ROLE_HEADER=1
uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000
```

Then run scenarios through the real `/chat/the_creator` endpoint:

```bash
cd workspace
python -m sci_fi_dashboard.model_parity.test_runner --transport http --models all
```

Use a narrower smoke run while iterating:

```bash
python -m sci_fi_dashboard.model_parity.test_runner --transport http --models casual,local --no-embeddings
```

## In-process Run

This uses the same `persona_chat` pipeline without HTTP/auth/rate-limit overhead:

```bash
cd workspace
python -m sci_fi_dashboard.model_parity.test_runner --transport inprocess --models all
```

## Tier Thresholds

Default similarity thresholds:

- `frontier`: `0.92`
- `strong_open`: `0.85`
- `mid_open`: `0.75`
- `small`: `0.60`

Individual scenarios can override these under `threshold_per_tier`.
