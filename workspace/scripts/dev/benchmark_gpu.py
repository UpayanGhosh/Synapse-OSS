import sys
import time
import warnings

sys.path.insert(0, ".")
warnings.filterwarnings("ignore")

import onnxruntime as ort

print("ONNX providers available:", ort.get_available_providers())

from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

p = FastEmbedProvider()
p.embed_query("warmup")

# Walk fastembed internals to find active ONNX session
embedder = p._get_embedder()
found_providers = None
for attr in ["model", "_model", "session", "_session"]:
    obj = getattr(embedder, attr, None)
    if obj is None:
        continue
    if hasattr(obj, "get_providers"):
        found_providers = obj.get_providers()
        print(f"Session providers (via .{attr}): {found_providers}")
        break
    for sub in ["session", "_session", "model", "_model"]:
        sub_obj = getattr(obj, sub, None)
        if sub_obj and hasattr(sub_obj, "get_providers"):
            found_providers = sub_obj.get_providers()
            print(f"Session providers (via .{attr}.{sub}): {found_providers}")
            break

if found_providers:
    if "CUDAExecutionProvider" in found_providers:
        print(">> RUNNING ON GPU (CUDA)")
    elif "TensorrtExecutionProvider" in found_providers:
        print(">> RUNNING ON GPU (TensorRT)")
    else:
        print(">> RUNNING ON CPU ONLY")

# Benchmark
texts = ["this is a test message number " + str(i) for i in range(500)]
t0 = time.perf_counter()
for t in texts:
    p.embed_query(t)
tps = 500 / (time.perf_counter() - t0)
print(f"\nThroughput single:   {tps:.0f} texts/sec")

t0 = time.perf_counter()
for i in range(0, 512, 64):
    p.embed_documents(texts[i % 500 : (i % 500) + 64] if i + 64 <= 500 else texts[-64:])
tps_b = 512 / (time.perf_counter() - t0)
print(f"Throughput batch-64: {tps_b:.0f} texts/sec")
