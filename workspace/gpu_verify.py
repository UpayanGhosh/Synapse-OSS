import sys, time, os
sys.path.insert(0, '.')
os.environ['PYTHONIOENCODING'] = 'utf-8'

import warnings
warnings.filterwarnings('ignore')

from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider
from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

fe = FastEmbedProvider()
ol = OllamaProvider(api_base='http://127.0.0.1:11434')

# Confirm GPU usage
embedder = fe._get_embedder()
try:
    providers = embedder.model.model.session.get_providers()
except:
    try:
        providers = embedder.model.model.get_providers()
    except:
        providers = ['unknown']

print(f'FastEmbed session providers: {providers}')
gpu_ok = any('CUDA' in p or 'Tensorrt' in p for p in providers)
print(f'FastEmbed on GPU: {gpu_ok}')
print(f'Ollama available: {ol.available}')
print()

texts = ['test message number ' + str(i) for i in range(200)]

# Warmup
fe.embed_query('warmup')
ol.embed_query('warmup')

# FastEmbed single
t0 = time.perf_counter()
for t in texts:
    fe.embed_query(t)
fe_single = 200 / (time.perf_counter() - t0)

# FastEmbed batch-64
t0 = time.perf_counter()
for i in range(0, 200, 64):
    fe.embed_documents(texts[i:i+64])
fe_batch = 200 / (time.perf_counter() - t0)

# Ollama single
t0 = time.perf_counter()
for t in texts:
    ol.embed_query(t)
ol_single = 200 / (time.perf_counter() - t0)

# Ollama batch-64
t0 = time.perf_counter()
for i in range(0, 200, 64):
    ol.embed_documents(texts[i:i+64])
ol_batch = 200 / (time.perf_counter() - t0)

print(f'                   FastEmbed(GPU)   Ollama(GPU)')
print(f'Single throughput: {fe_single:>8.0f}/s    {ol_single:>8.0f}/s')
print(f'Batch-64 thruput:  {fe_batch:>8.0f}/s    {ol_batch:>8.0f}/s')
print()
if gpu_ok:
    print('[PASS] Both providers confirmed on GPU - fair comparison ready.')
else:
    print('[WARN] FastEmbed NOT on GPU - check CUDA DLL setup.')
