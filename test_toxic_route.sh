#!/bin/bash
echo "🧪 Testing TOXIC Route (Ollama)..."
echo "   Message: \"My partner is being a complete asshole...\" (Known Score: ~0.97)"

response=$(curl -s -X POST http://localhost:8001/chat/the_creator \
    -H "Content-Type: application/json" \
    -d '{"message": "My partner is being a complete asshole about boundaries"}')

# Extract fields
model=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('model', 'ERROR'))")
score=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('toxicity_score', '0.0'))")

echo "   Score: $score"
echo "   Model: $model"

if [[ "$model" == *"LOCAL_SPICY"* ]]; then
    echo "✅ SUCCESS: Routed to Uncensored Hemisphere"
else
    echo "❌ FAILED: Routed to Safe Hemisphere"
fi
