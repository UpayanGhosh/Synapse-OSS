import requests
import sys
import os
import time

API_URL = "http://localhost:8000/add"

def ingest_file(file_path):
    print(f"📖 Ingesting: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    with open(file_path, 'r') as f:
        content = f.read()

    # Simple chunking by double newline (paragraphs)
    chunks = content.split('\n\n')
    
    total = len(chunks)
    print(f"🧩 Found {total} chunks. Starting ingestion...")

    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
            
        print(f"[{i+1}/{total}] Processing chunk ({len(chunk)} chars)...")
        
        try:
            payload = {
                "content": chunk,
                "category": "history_ingestion"
            }
            response = requests.post(API_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status")
                if status == "memorized":
                    print(f"   ✅ Memorized: {data.get('triple')}")
                else:
                    print(f"   ⚠️ Failed: {status}")
            else:
                print(f"   ❌ API Error: {response.status_code}")
                
        except Exception as e:
            print(f"   🚨 Script Error: {e}")

        # Rate limiting for local LLM health
        time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest_memories.py <file_or_directory>")
        sys.exit(1)
        
    target = sys.argv[1]
    
    if os.path.isdir(target):
        print(f"📂 Scanning directory: {target}")
        for root, dirs, files in os.walk(target):
            for file in files:
                if file.endswith(".md") or file.endswith(".txt"):
                    full_path = os.path.join(root, file)
                    ingest_file(full_path)
    else:
        ingest_file(target)
