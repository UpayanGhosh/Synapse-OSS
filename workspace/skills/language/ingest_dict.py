import json
import urllib.request
import urllib.error
import sys

def ingest_banglish_dictionary():
    file_path = "/path/to/openclaw/workspace/skills/language/banglish_dict.json"
    api_url = "http://127.0.0.1:8989/add"

    try:
        with open(file_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading dictionary file: {e}")
        return

    print(f"Found {len(data)} entries. Starting ingestion...")

    count = 0
    errors = 0

    # Helper function to send POST request
    def send_post(content, category):
        payload = json.dumps({
            "content": content,
            "category": category
        }).encode('utf-8')
        
        req = urllib.request.Request(api_url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status == 200
        except urllib.error.URLError as e:
            print(f"Request failed: {e}")
            return False

    # Ingest the entire dictionary as one context block
    full_text = "Banglish to English Dictionary (Code-mixed Bengali-English):\n"
    for word, info in data.items():
        if isinstance(info, dict):
            meaning = info.get("meaning", "??")
            sentiment = info.get("sentiment", "")
            full_text += f"- {word}: {meaning} ({sentiment})\n"
        else:
             full_text += f"- {word}: {info}\n"
    
    if send_post(full_text, "language_skill_master_list"):
        print("Master list ingested successfully.")
    else:
        print("Failed to ingest master list.")
        errors += 1

    # Ingest individual terms
    for word, info in data.items():
        if isinstance(info, dict):
            meaning = info.get("meaning", "??")
            sentiment = info.get("sentiment", "Neutral")
            content_text = f"Banglish Word: '{word}'\nEnglish Meaning: {meaning}\nSentiment: {sentiment}\nUsage: Used in Bengali/Banglish conversations."
        else:
            # Fallback for simple key-value if mixed
            content_text = f"Banglish Word: '{word}'\nEnglish Meaning: {info}\nUsage: Used in Bengali/Banglish conversations."
        
        if send_post(content_text, "language_skill_entry"):
            print(f"Ingested: {word} -> {meaning}")
            count += 1
        else:
            print(f"Failed: {word}")
            errors += 1

    print(f"\nIngestion Complete. Success: {count}, Errors: {errors}")

if __name__ == "__main__":
    ingest_banglish_dictionary()
