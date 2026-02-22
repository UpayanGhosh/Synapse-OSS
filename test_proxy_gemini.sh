#!/bin/bash
echo "Testing Gemini via Proxy..."
for i in {1..7}; do
   echo "Request $i..."
   curl -s -X POST http://localhost:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "gemini-3-flash",
       "messages": [{"role": "user", "content": "Hi"}],
       "max_tokens": 10
     }' | grep -o "content" || echo "FAIL"
done
