# Max Voice Assistant - Docker Deployment

Max is packaged as a single Docker container that bundles:

- **opencode** (v1.18.x, standalone binary) - agent runtime
- **ollama** (server binary) - local LLM runtime
- **Piper** German voice (`de_DE-thorsten-medium`)
- **faster-whisper** (`small`) pre-downloaded
- **pyannote.audio** (voiceprint identification)
- The **Max** application itself (`python -m max.main`)

## What is NOT in the image

The LLM models used by Max (`max-9b` and `qwen3.5:9b`) are **custom models** that are not
in the public Ollama registry. They must be provided via a volume mounted at `/data/ollama`.

## Providing the models

Option A - copy existing Ollama model blobs:
1. On the host, find your Ollama data directory (default `~/.ollama` or wherever
   `OLLAMA_MODELS` points).
2. Copy the `models/` directory contents into a Docker volume, e.g.:
   ```bash
   docker volume create ollama-models
   # copy ~/.ollama/models/* into the volume (see below)
   ```
3. The `docker-compose.yml` already mounts this volume at `/data/ollama`.

Option B - import GGUF files:
If you only have the GGUF files (e.g. `Qwen3.5-9B-GGUF`), start a container with a
writable `/data/ollama` volume and run:
```bash
ollama import <path-to-gguf> <model-name>
```

## Running

```bash
docker compose up -d
```

The container will:
1. Start `ollama serve` in the background.
2. Verify that `max-9b` and `qwen3.5:9b` are present in `/data/ollama`.
   If missing, it exits with a clear error telling you to provide them.
3. Seed the Piper voice into the runtime data directory.
4. Start `python -m max.main` (the voice assistant loop).

## Audio

Max captures microphone input and plays synthesized speech via `sounddevice`.
A container has no audio device by default. To run it with real audio, provide
host audio passthrough. For example, with Docker CLI:

```bash
docker run --device /dev/snd ...
```

or mount a PulseAudio socket. Without audio, the assistant cannot capture or play sound.
The container will still start and you can verify the pipeline over text if you adjust
the entry command, but the interactive voice loop needs an audio device.

## Verification

To verify the components without audio, run:
```bash
docker run --rm --entrypoint bash max-voice-assistant:latest -c \
  "opencode --version && /usr/local/bin/ollama --version && ls /opt/piper-voices"
```

## Files

- `Dockerfile` - builds the image
- `entrypoint.sh` - starts ollama, checks models, seeds piper voice, runs Max
- `docker-compose.yml` - service definition + volumes
- `config/opencode.global.json` - global opencode config (ollama provider)
- `.dockerignore` - excludes host-only files from the build context
