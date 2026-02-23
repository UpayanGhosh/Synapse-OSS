import os
import sys
import asyncio
import time

# Add path
sys.path.append(os.path.join(os.getcwd(), "workspace", "sci_fi_dashboard"))

from memory_engine import MemoryEngine

async def test_concurrent_writes():
    engine = MemoryEngine()
    print("🚀 Starting concurrent write test...")
    
    tasks = []
    # Attempt 5 rapid writes to trigger potential lock contention
    for i in range(5):
        tasks.append(asyncio.to_thread(engine.add_memory, f"Concurrency test message {i}", "test_run"))
    
    results = await asyncio.gather(*tasks)
    
    successes = [r for r in results if "id" in r]
    errors = [r for r in results if "error" in r]
    
    print(f"✅ Successes: {len(successes)}")
    print(f"❌ Errors: {len(errors)}")
    for e in errors:
        print(f"   Error: {e['error']}")

if __name__ == "__main__":
    asyncio.run(test_concurrent_writes())
