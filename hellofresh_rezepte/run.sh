#!/usr/bin/with-contenv bashio
set -e

export HF_DATA_DIR=/data
export HF_SHARE_DIR=/share/HelloFresh
export HF_MEDIA_DIR=/media
export PORT=8131
export DISPLAY=:99

mkdir -p /media/Import/Rezepte/Fehler /share/HelloFresh/duplikate /share/HelloFresh/importiert /data/hellofresh-browser
chmod 700 /data/hellofresh-browser
chown -R hf-browser:hf-browser /data/hellofresh-browser

Xvfb "$DISPLAY" -screen 0 1280x1024x24 -ac >/tmp/hellofresh-xvfb.log 2>&1 &
for attempt in $(seq 1 30); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.2
done
if [ ! -S /tmp/.X11-unix/X99 ]; then
    echo "[FATAL] Der virtuelle HelloFresh-Bildschirm konnte nicht gestartet werden."
    cat /tmp/hellofresh-xvfb.log
    exit 1
fi

x11vnc -display "$DISPLAY" -forever -shared -rfbport 5900 -nopw >/tmp/hellofresh-x11vnc.log 2>&1 &
/opt/noVNC/utils/novnc_proxy --vnc localhost:5900 --listen 6082 >/tmp/hellofresh-novnc.log 2>&1 &

python /opt/hellofresh_rezepte/app/app.py
