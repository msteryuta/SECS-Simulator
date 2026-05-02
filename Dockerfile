# 使用最穩定的 Debian 作為基底
FROM debian:bookworm-slim

# 設定環境變數
ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1

# 安裝 Python 3, Tkinter, 虛擬螢幕和 VNC 工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-tk \
    xvfb x11vnc novnc websockify ca-certificates bash git openbox xterm \
    && rm -rf /var/lib/apt/lists/*

# 破解 noVNC 首頁陷阱
RUN ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# 建立 Hugging Face 規定的使用者
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user
WORKDIR $HOME/app

# 從你的 GitHub 抓取最新程式碼
RUN git clone https://github.com/msteryuta/SECS-Simulator.git .

# 安裝套件 (Debian 12 需要加上 --break-system-packages 才能在全域安裝)
RUN if [ -f "requirements.txt" ]; then pip3 install --break-system-packages --no-cache-dir -r requirements.txt; fi

EXPOSE 7860

# 直接把啟動指令寫在這裡，絕對不要呼叫外部 .sh 檔！
CMD bash -c " \
    Xvfb :1 -screen 0 1280x800x24 -ac +extension GLX +render -noreset & \
    sleep 2; \
    DISPLAY=:1 openbox-session & \
    DISPLAY=:1 xterm -e 'python3 main.py ; bash' & \
    x11vnc -display :1 -nopw -listen localhost -xkb -ncache 10 -ncache_cr -forever & \
    websockify --web /usr/share/novnc/ 7860 localhost:5900 \
"
