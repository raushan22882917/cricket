#!/usr/bin/env bash
# ==============================================================================
# Cricket YouTube Live AI Broadcast Engine - Single Command Launcher
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    /opt/homebrew/bin/python3.11 -m venv .venv || python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

# Load .env if present
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

echo "================================================================"
echo " 🏏 CRICKET AI YOUTUBE LIVE BROADCAST ENGINE "
echo "================================================================"
echo " Mode: ${STREAM_MODE:-preview}"
if [ -n "$YOUTUBE_STREAM_KEY" ]; then
    echo " Target: YouTube Live RTMP (Key: ${YOUTUBE_STREAM_KEY:0:4}****)"
else
    echo " Target: Local Preview Mode (${OUTPUT_PREVIEW_FILE:-broadcast_output.mp4})"
    echo " (Tip: Set YOUTUBE_STREAM_KEY in .env or pass --key to push directly to YouTube Live)"
fi
echo " Commentary Voice: ${TTS_VOICE:-en-IN-PrabhatNeural}"
echo " Event Webhook: http://localhost:${EVENT_SERVER_PORT:-8080}/event"
echo "================================================================"

exec .venv/bin/python3 main.py "$@"
