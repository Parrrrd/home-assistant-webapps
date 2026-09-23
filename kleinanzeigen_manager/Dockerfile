ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    git \
    chromium chromium-chromedriver \
    font-noto nss freetype harfbuzz ttf-freefont \
    xvfb x11vnc \
    && python3 -m venv /opt/venv

# Download noVNC
RUN git clone --depth=1 https://github.com/novnc/noVNC.git /opt/noVNC \
    && git clone --depth=1 https://github.com/novnc/websockify.git /opt/noVNC/utils/websockify

ENV PATH="/opt/venv/bin:${PATH}" \
    PIP_CONFIG_FILE="/dev/null" \
    PIP_INDEX_URL="https://pypi.org/simple" \
    PIP_EXTRA_INDEX_URL="" \
    PIP_PREFER_BINARY=1 \
    PIP_ONLY_BINARY="PyYAML,pydantic-core,psutil,curl-cffi,cryptography,cffi,aiohttp,yarl,multidict,frozenlist,propcache" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHROME_BIN="/usr/bin/chromium-browser" \
    CHROMEDRIVER_PATH="/usr/bin/chromedriver" \
    DISPLAY=":99"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check \
        --prefer-binary \
        --timeout 60 --retries 5 --resume-retries 10 \
        -r /tmp/requirements.txt \
    && pip install --no-cache-dir --disable-pip-version-check \
        --prefer-binary \
        --timeout 60 --retries 5 --resume-retries 10 \
        "kleinanzeigen-bot @ git+https://github.com/Second-Hand-Friends/kleinanzeigen-bot.git@54d3d21"

COPY kleinanzeigen_bot_init_patched.py /tmp/kleinanzeigen_bot_init_patched.py
RUN python -c "import pathlib, shutil, kleinanzeigen_bot; root=pathlib.Path(kleinanzeigen_bot.__file__).resolve().parent; shutil.copy2('/tmp/kleinanzeigen_bot_init_patched.py', root / '__init__.py'); print('patched kleinanzeigen_bot:', root / '__init__.py')" \
    && python -c "import pathlib, kleinanzeigen_bot; p=pathlib.Path(kleinanzeigen_bot.__file__).resolve().parent / '__init__.py'; s=p.read_text('utf-8'); assert 'package-shipping dialog fallback' in s; assert 'Individual shipping input not available' in s; assert 'fresh image remove click' in s; assert 'all existing images removed; uploading configured image set from scratch' in s; assert 'Shipping methods already match requested configuration in main form' in s; assert 'legacy shipping dialog is not required' in s; print('shipping and image sync fixes verified')"

COPY app /opt/kleinanzeigen_manager/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/kleinanzeigen_manager/app
CMD [ "/run.sh" ]
