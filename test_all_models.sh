#!/bin/bash

# Function to test a model
test_model() {
    name=$1
    message=$2
    expected_model=$3
    
    echo "---------------------------------------------------"
    echo "🧪 Testing $name..."
    echo "   Message: \"$message\""
    
    response=$(curl -s -X POST http://localhost:8001/chat/the_creator \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$message\"}")
    
    # Extract fields using python (more reliable than grep/sed for json)
    model=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('model', 'ERROR'))" 2>/dev/null)
    reply=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('reply', '')[:50].replace('\n', ' '))" 2>/dev/null)
    
    if [[ "$model" == *"$expected_model"* ]]; then
        echo "✅ SUCCESS"
        echo "   Routed to: $model"
        echo "   Reply: $reply..."
    else
        echo "❌ FAILED"
        echo "   Expected: $expected_model"
        echo "   Got: $model"
        echo "   Raw: $response"
    fi
}

# 1. AG_CASUAL (Gemini)
test_model "AG_CASUAL (Gemini)" "Hi, just saying hello!" "AG_CASUAL"

# 2. AG_CODE (Claude Sonnet)
test_model "AG_CODE (Claude Sonnet)" "Write a Python function to calculate fibonacci numbers." "AG_CODE"

# 3. AG_ORACLE (Claude Opus)
test_model "AG_ORACLE (Claude Opus)" "Analyze the geopolitical implications of quantum computing." "AG_ORACLE"

# 4. LOCAL_SPICY (Ollama)
test_model "LOCAL_SPICY (Ollama/Chloe)" "You are annoying me. Shut up." "LOCAL_SPICY"
