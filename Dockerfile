FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# System packages: Node.js (for opencode plugins), curl/wget, ALSA/Pulse for sounddevice
RUN apt-get update && apt-get install -y \
    curl wget nodejs npm zstd \
    libasound2 libpulse0 pulseaudio \
    && rm -rf /var/lib/apt/lists/*

# Ollama server (official tarball, extracted to /usr/local -> /usr/local/bin/ollama)
RUN curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst -o /tmp/ollama.tar.zst \
    && tar --zstd -xf /tmp/ollama.tar.zst -C /usr/local \
    && chmod +x /usr/local/bin/ollama \
    && rm /tmp/ollama.tar.zst

# opencode standalone binary (official install script)
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/root/.opencode/bin:${PATH}"

# Python application + dependencies
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY config/ config/
RUN pip install --upgrade pip && pip install .

# Piper German voice (de_DE-thorsten-medium) - kept outside /app/data so the
# runtime volume (mounted at /app/data) does not hide it.
RUN mkdir -p /opt/piper-voices \
    && python -m piper.download_voices de_DE-thorsten-medium --download-dir /opt/piper-voices

# Pre-download faster-whisper 'small' model so first request is fast
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu')"

# Global opencode config (ollama provider) -> ~/.config/opencode/opencode.json
RUN mkdir -p /root/.config/opencode \
    && cp /app/config/opencode.global.json /root/.config/opencode/opencode.json

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
