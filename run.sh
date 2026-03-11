#!/bin/bash

# Startup script to spawn multiple orchestrator instances
# Reads ORCHS environment variable (default: 2, max: 8)

set -e

# Use -x only while you are debugging your IP variable
set -x

# Get orchestrator count from environment, default to 2
ORCHS=${ORCHS:-2}
SLOTS=${SLOTS:-2}
EXT_IP=${EXT_IP:-0.0.0.0}

echo "Starting with External IP: $EXT_IP"

python route_to.py --ip $EXT_IP &
PID=$!

echo "Replaced files with $EXT_IP in process with ID $PID."

# Output file
OUTPUT_FILE="ports.json"

# Validate count (between 2 and 8)
if [ "$ORCHS" -lt 2 ] || [ "$ORCHS" -gt 8 ]; then
    echo "Error: ORCHS must be between 2 and 8"
    exit 1
fi

echo "Starting $ORCHS orchestrator instances..."

# Array to store PIDs for cleanup
PIDS=()

# Function to handle cleanup on exit
cleanup() {
    echo "Shutting down orchestrators..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait
    echo "All orchestrators stopped."
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Start orchestrators on ports 8001, 8002, ..., 800N
BASE_PORT=8001
# Create an empty array
ORCH_URLS=()

for i in $(seq 1 $ORCHS); do
    PORT=$((BASE_PORT + i - 1))
    echo "Starting orchestrator $i on port $PORT..."
    
    python -O orch.py --port "$PORT" --slots $SLOTS &
    PID=$!
    PIDS+=($PID)
    
    # Add elements
    ORCH_URLS+=($PORT)
    
    echo "Orch $i started with PID $PID on port $PORT"
    # Wait longer between starts to allow each orchestrator to fully initialize
    sleep 2  # Increased delay to allow FastAPI/uvicorn to start
done

# Wait additional time for all orchestrators to be fully ready
echo "Waiting for orchestrators to initialize..."
sleep 5

echo ""
echo "All orchestrators started successfully!"
# Convert array to JSON and write to file
printf '%s\n' "${ORCH_URLS[@]}" | jq -R . | jq -s . > "$OUTPUT_FILE"
echo ""

echo "JSON written to $OUTPUT_FILE"
sleep 5

python -O main.py &
PID=$!

echo "Access from other devices on LAN: http://0.0.0.0:8000"
echo "Load Balancer started with PID $PID on port 8000"
# Wait for all background processes
wait
