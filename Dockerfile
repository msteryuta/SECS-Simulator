# 使用輕量級 Python 映像檔
FROM python:3.10-slim

# 安裝系統依賴：虛擬顯示器、VNC 伺服器、noVNC 及 Tkinter 必要的 X11 庫
RUN apt-get update && apt-get install -y \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    python3-tk \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製你的專案檔案（包含 main.py, core/, handlers/, gui/, config/）
COPY . .

# 暴露 noVNC 使用的連接埠
EXPOSE 6080

# 啟動腳本：同時啟動虛擬顯示器、VNC、noVNC 和你的 Python 程式
CMD Xvfb :1 -screen 0 1280x800x24 & \
    export DISPLAY=:1 && \
    x11vnc -display :1 -nopw -forever & \
    /usr/share/novnc/utils/launch.sh --vnc localhost:5900 --listen 6080 & \
    python main.py
