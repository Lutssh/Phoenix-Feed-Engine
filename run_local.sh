#!/bin/bash
set -e

# Function to check if a command exists
check_cmd() {
    if ! command -v "$1" &> /dev/null; then
        echo "❌ Error: '$1' is not installed."
        echo "   Please install it and try again."
        exit 1
    fi
}

echo "🔍 Checking System Dependencies..."
check_cmd redis-server
check_cmd cargo
check_cmd python3
check_cmd ffmpeg

# 1. Setup Python Environment
echo "🐍 Setting up Python Virtual Environment..."
if [ ! -d "django" ]; then
    python3 -m venv django
    echo "   Created venv."
fi

source django/bin/activate
echo "   Installing Python dependencies (this may take a while)..."
pip install -r smart_ingestion/requirements.txt > /dev/null

# 2. Setup Qdrant (Local Binary)
if [ ! -f "qdrant" ]; then
    echo "⬇️  Downloading Qdrant binary (High Performance Vector DB)..."
    # Download latest linux binary
    curl -L https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu -o qdrant
    chmod +x qdrant
fi

# 3. Start Services
echo "🚀 Starting Background Services..."

# Start Redis if not running
if ! pgrep redis-server > /dev/null; then
    echo "   Starting Redis Server..."
    redis-server --daemonize yes
else
    echo "   Redis is already running."
fi

# Start Qdrant
echo "   Starting Qdrant..."
./qdrant > qdrant.log 2>&1 &
QDRANT_PID=$!
echo "   Qdrant PID: $QDRANT_PID"

# Start Celery Worker
echo "   Starting Neural Worker (Celery)..."
export PYTHONPATH=$PYTHONPATH:$(pwd)
# We use concurrency=1 to avoid OOM on local machine if GPU VRAM is tight
celery -A neural_ingestion.celery_app worker --loglevel=info --concurrency=1 > celery.log 2>&1 &
CELERY_PID=$!
echo "   Celery Worker PID: $CELERY_PID"

echo "⏳ Waiting 5s for services to stabilize..."
sleep 5

# 4. Instructions
echo ""
echo "✅ SYSTEM IS RUNNING!"
echo "-----------------------------------------------------"
echo "   - Redis:   Running (Local)"
echo "   - Qdrant:  Running (PID $QDRANT_PID)"
echo "   - Worker:  Running (PID $CELERY_PID) -> Logs: tail -f celery.log"
echo "-----------------------------------------------------"
echo "to stop the background processes later, run: kill $QDRANT_PID $CELERY_PID"
echo ""
echo "🦀 Starting Rust Feed Engine (Foreground)..."
echo "   (Press Ctrl+C to stop the engine. Background workers will keep running)"
echo ""

# Start Rust Engine
cd rust_feed_engine
export REDIS_URL=redis://127.0.0.1:6379
export RUST_LOG=info
cargo run

# Cleanup helper (Optional, if you want to kill everything on exit)
# kill $QDRANT_PID $CELERY_PID
