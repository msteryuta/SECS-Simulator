# HF Space — Tkinter via Xvfb + x11vnc + noVNC + websockify (port 7860)
#
# 說明：Debian apt 提供的 `websockify` 可能把網頁根目錄指到 `/tmp/novnc`（空資料夾）
# → 瀏覽器 404。改為將 noVNC 靜態檔複製到 /srv/novnc，並用 pip 的 `python -m websockify` 服務該路徑。

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    HF_MODEL=6600WB

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-tk \
    xvfb x11vnc novnc ca-certificates bash git \
    && rm -rf /var/lib/apt/lists/*

# 固定網頁根目錄（勿用 Debian websockify 預設的 /tmp/novnc）
RUN mkdir -p /srv/novnc && cp -a /usr/share/novnc/. /srv/novnc/ \
    && ln -sf vnc.html /srv/novnc/index.html

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app
RUN git clone https://github.com/msteryuta/SECS-Simulator.git .

RUN if [ -f requirements.txt ]; then pip3 install --no-cache-dir --break-system-packages -r requirements.txt; fi

EXPOSE 7860

# 不依賴 Openbox／xterm，避免選單與 PyXDG 報錯；Tk 可直接畫在 Xvfb root window 上。
CMD bash -lc '\
    set -eu; \
    Xvfb :1 -screen 0 1280x800x24 -ac & \
    sleep 1; \
    python3 "${HOME}/app/main.py" --model "${HF_MODEL:-6600WB}" & \
    sleep 1; \
    x11vnc -display :1 -nopw -forever -shared -listen 127.0.0.1 -rfbport 5900 & \
    sleep 1; \
    exec python3 -m websockify --web /srv/novnc 0.0.0.0:7860 127.0.0.1:5900 \
'
