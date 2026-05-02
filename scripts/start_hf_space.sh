#!/usr/bin/env bash
# Starts virtual X11 + VNC + noVNC on :7860 (HF Spaces), then the Tkinter app.
set -euo pipefail

export DISPLAY=:1
MODEL="${HF_MODEL:-6600WB}"

Xvfb :1 -screen 0 1280x800x24 &
sleep 1

x11vnc -display :1 -nopw -forever -shared -listen 127.0.0.1 -rfbport 5900 &
sleep 1

cd /home/user/app
python3 main.py --model "${MODEL}" &
# Keep simulator running in background; foreground must stay alive for the container.
# HF Spaces expects HTTP on 0.0.0.0:7860 (noVNC UI + WebSocket to VNC).
exec websockify --web=/usr/share/novnc 0.0.0.0:7860 localhost:5900
