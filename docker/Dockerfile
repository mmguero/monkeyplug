FROM python:3-slim

LABEL maintainer="mero.mero.guero@gmail.com"
LABEL org.opencontainers.image.authors='mero.mero.guero@gmail.com'
LABEL org.opencontainers.image.url='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.source='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.title='mmguero/monkeyplug'
LABEL org.opencontainers.image.description='Dockerized monkeyplug'

ENV DEBIAN_FRONTEND noninteractive
ENV TERM xterm
ENV PYTHONUNBUFFERED 1
ENV VOSK_MODEL /opt/vosk_model

# see https://alphacephei.com/vosk/models
# use "vosk-model-en-us-0.22" if you want more accurate recognition (and a large image)
ARG VOSK_MODEL_URL="https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip"

ADD . /usr/local/src/monkeyplug

RUN apt-get update -q && \
    apt-get -y install -qq --no-install-recommends libarchive-tools curl && \
    python3 -m ensurepip && \
    python3 -m pip install --no-cache /usr/local/src/monkeyplug && \
    mkdir -p /opt/vosk_model && \
    cd /opt/vosk_model && \
    echo "Downloading model \"$VOSK_MODEL_URL\"..." && \
    curl -fsSL -o ./model.zip "$VOSK_MODEL_URL" && \
    echo "Finished" && \
    bsdtar -xf model.zip -s'|[^/]*/||' && \
    cd / && \
    apt-get clean && \
      rm -rf /var/cache/apt/* /var/lib/apt/lists/* /tmp/* /var/tmp/* /usr/local/src/monkeyplug /opt/vosk_model/model.zip

COPY --from=mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/
COPY --from=mwader/static-ffmpeg:latest /ffprobe /usr/local/bin/

WORKDIR /tmp

ENTRYPOINT ["monkeyplug"]
CMD []
