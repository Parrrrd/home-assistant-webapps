#!/usr/bin/with-contenv bashio
set -euo pipefail

export PORT=8153
export DISPLAY=:99
export PULSE_SERVER=unix:/run/pulse/native

# Public Cloudflare hostname used only by the minimal Web-Push PWA.  The
# Flask app denies all normal manager routes when this Host header is used.
push_public_host="$(bashio::config 'push_public_host' 2>/dev/null || true)"
if [ -n "$push_public_host" ]; then
    export VINTED_PUSH_PUBLIC_HOST="$push_public_host"
fi

# noVNC carries the desktop picture and input, but not desktop audio.  Create
# a local PulseAudio sink so the manager can relay the Vinted challenge audio
# through its normal web port to a separate Safari tab.
if command -v pulseaudio >/dev/null 2>&1; then
    pulseaudio --system --daemonize=yes --exit-idle-time=-1 --disallow-exit --disable-shm >/tmp/pulseaudio.log 2>&1 || true
    for attempt in $(seq 1 20); do
        if pactl info >/dev/null 2>&1; then
            break
        fi
        sleep 0.25
    done
    if pactl info >/dev/null 2>&1; then
        pactl load-module module-null-sink sink_name=vinted_output sink_properties=device.description=VintedAudio >/tmp/vinted-audio-module.log 2>&1 || true
        pactl set-default-sink vinted_output >/tmp/vinted-audio-default.log 2>&1 || true
    else
        echo "[WARN] Der Audio-Dienst konnte nicht gestartet werden. Der VNC-Bildschirm bleibt verfügbar."
        cat /tmp/pulseaudio.log || true
    fi
fi

Xvfb "$DISPLAY" -screen 0 1280x1024x24 >/tmp/xvfb.log 2>&1 &
for attempt in $(seq 1 30); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.2
done

if [ ! -S /tmp/.X11-unix/X99 ]; then
    echo "[FATAL] Der virtuelle Bildschirm konnte nicht gestartet werden."
    cat /tmp/xvfb.log
    exit 1
fi

x11vnc -display "$DISPLAY" -forever -shared -rfbport 5900 -nopw >/tmp/x11vnc.log 2>&1 &
vnc_pid=$!
sleep 1
if ! kill -0 "$vnc_pid" 2>/dev/null; then
    echo "[FATAL] Der VNC-Dienst konnte nicht gestartet werden."
    cat /tmp/x11vnc.log
    exit 1
fi

/opt/noVNC/utils/novnc_proxy --vnc localhost:5900 --listen 6081 >/tmp/novnc.log 2>&1 &

exec python3 /opt/vinted_manager/app/app.py
