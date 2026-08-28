#!/bin/bash
set -euo pipefail

# Ollama models live in a persistent volume
mkdir -p /data/ollama
export OLLAMA_MODELS=/data/ollama

# Start Ollama server in the background
ollama serve >/dev/null 2>&1 &
echo "[entrypoint] Ollama starting..."
for i in $(seq 1 60); do
  if curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
echo "[entrypoint] Ollama ready."

# The LLM models (max-9b, qwen3.5:9b) are custom and NOT in the public Ollama
# registry, so they must be provided in the /data/ollama volume.
MODELS_LIST=$(ollama list 2>/dev/null || true)
MISSING=""
for m in max-9b qwen3.5:9b; do
  if ! echo "$MODELS_LIST" | grep -q "$m"; then
    MISSING="$MISSING $m"
  fi
done
if [ -n "$MISSING" ]; then
  echo "[entrypoint] ERROR: required Ollama model(s) missing:$MISSING"
  echo "[entrypoint] Provide them in the /data/ollama volume: copy your existing"
  echo "[entrypoint] ollama model blobs into that directory, or import the GGUF files."
  exit 1
fi
echo "[entrypoint] Required models present."

# Seed the Piper voice into the runtime data dir (the /app/data volume may be empty on first run)
mkdir -p /app/data/voices
if [ ! -f /app/data/voices/de_DE-thorsten-medium.onnx ]; then
  cp -n /opt/piper-voices/* /app/data/voices/ || true
fi

# Start Max
exec python -m max.main "$@"
