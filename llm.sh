#!/bin/bash

# Start Ollama in the background
ollama serve &

# Record the Process ID
pid=$!

# Wait for Ollama to start by checking the list command
echo "Waiting for Ollama to start..."
while ! ollama list > /dev/null 2>&1; do
    sleep 1
done

# Pull the specific Gemma 3 model
echo "Pulling $OLLAMA_MODEL..."
ollama pull $OLLAMA_MODEL

echo "$OLLAMA_MODEL is ready!"

# Keep the container alive
wait $pid