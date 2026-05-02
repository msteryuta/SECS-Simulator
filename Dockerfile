# Hugging Face Spaces (Docker SDK) — Tkinter via noVNC on port 7860
# Debian image + python3-tk: official python:*-slim images often lack working tkinter.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    HF_MODEL=6600WB

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-tk \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    ca-certificates \
    bash \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user

WORKDIR /home/user/app
COPY --chown=user:user . .
RUN chmod +x scripts/start_hf_space.sh

USER user

EXPOSE 7860

CMD ["/home/user/app/scripts/start_hf_space.sh"]
